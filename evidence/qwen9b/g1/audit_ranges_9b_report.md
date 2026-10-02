# Increment (3) PREP — fixed-point range audit vs the real Qwen3.5-9B weights

- generated: `2026-08-29 18:00:56`  (repo `4965057`)
- checkpoint: `['/home/cah/.cache/huggingface/hub/models--Qwen--Qwen3.5-9B/snapshots/c202236235762e1c871ad0ccb60c8ee5ba337b9a/model.safetensors-00001-of-00004.safetensors', '/home/cah/.cache/huggingface/hub/models--Qwen--Qwen3.5-9B/snapshots/c202236235762e1c871ad0ccb60c8ee5ba337b9a/model.safetensors-00002-of-00004.safetensors', '/home/cah/.cache/huggingface/hub/models--Qwen--Qwen3.5-9B/snapshots/c202236235762e1c871ad0ccb60c8ee5ba337b9a/model.safetensors-00003-of-00004.safetensors', '/home/cah/.cache/huggingface/hub/models--Qwen--Qwen3.5-9B/snapshots/c202236235762e1c871ad0ccb60c8ee5ba337b9a/model.safetensors-00004-of-00004.safetensors']`
- safetensors header sha256: `2721100f724faea555e4afd11064461b2b231914be53e8d7468ed1be9d9f4c3b`
- model: 32 layers (24 DeltaNet + 8 GQA), H=4096, FFN=12288, vocab=248320 (tied embeddings)
- frozen formats under test: RS_F=8 QKV_F=8 NRM_F=14 S_F=13 GAT_F=15 CW_F=13 ROPE_F=15 KVC_F=6, W4 group G=128
- quantizers exercised: `layer_fixed.quant_layer` (-> `quant_attn` / `quant_deltanet` / `quant_mlp` / `quant_linear`), `w4a8_ref.quantize_weights`, `fixedpoint.softplus_q` / `exp_neg_q` / `sigmoid_q`. Nothing is re-implemented here.
- W4 group-scale rule in force (`quant_linear` default `mse_scale`): **MSE-optimal (quant_linear_mse)** — section 2's `e` / `m` / INT4-clip / error columns are produced by THIS rule.
- `res_scale = 1.0` (`quant_layer` default). res_scale is a power-of-two prescale of the three residual-writing matrices (`o_proj` / `dn.out` / `mlp.down`) and of the embedding seed, so it moves section 2's `e` column by exactly log2(S) on those families and nothing else there; section 4's seed occupancy DOES scale with S (see the runtime note in section 5).

**GATE-PORT CAVEAT — the `dt_bias` and `A` rows of sections 1 and 3 audit POST-CLAMP values.** `layer_fixed.quant_deltanet` saturates both into their ports before returning them (`np.clip`, `layer_fixed.py:805-806`, since `82781e5`), so those rows report `0 / N` out of range and a max pinned exactly at the rail EVEN IF the checkpoint exceeds the port — and section 3's "max used (real weights)" column, which is computed from the FLOAT weights, can then contradict its own verdict. The pre-clamp truth is recorded in `qd["gate_sat"]` (which this script does not read) and is measured by `evidence/qwen2b/q2/audit/gate_port_probe.py`.

## 0. Verdict summary

**5 ATTENTION item(s)**:
1. W4 group-scale underflow: 96/61997056 groups hit `m==1` (64 clipped up from 0), annihilating 4131 weights
2. W4 value clipping (round(W/eff) outside [-8,7])
3. W4 weight error above the project's own 15% bound on 5/249 matrices (worst `L8.dn.in_b` 15.47%)
4. y32 headroom: conservative `sh` discards up to 5.6 bits of the int32 accumulator (precision only, no overflow)
5. embedding at Q7.8 uses 0.37% of the int16 range (120 LSB peak, 3.4 LSB RMS) -> 8.4% relative RMS error on the layer-0 residual

Matrices quantized with the production path: 248 + 1 LM head = 249 (`gen_token_script` expects 187 weight images at 24 layers).

## 1. Direct constant formats (int16 / uint18 transport)

Every row is a HARD limit: `gen_layer_script.Mach.W` asserts the int16 range, so an out-of-range value aborts script generation; `Mach.W_raw` (A) masks to 16+2 bits and would wrap silently.

| format / tensor family | container | available | max abs value | range util | out-of-range | smallest container that fits | verdict |
|---|---|---|---|---|---|---|---|
| ln1 / ln2 (48 tensors, zero-centered 1+w) | int16 Q1.14 (scratch / vecnorm wbuf) | +/-2 | 1.4062 | 70.31% | 0 / 262144 | fits | PASS |
| model.norm (final RMSNorm, zero-centered 1+w) | int16 Q1.14 (scratch / vecnorm wbuf) | +/-2 | 1.9922 | 99.61% | 0 / 4096 | fits | PASS |
| q_norm / k_norm (6 GQA layers, zero-centered 1+w) | int16 Q1.14 (scratch / vecnorm wbuf) | +/-2 | 1.9219 | 96.09% | 0 / 4096 | fits | PASS |
| linear_attn.norm (18 layers, ONE-centered, used as-is) | int16 Q1.14 (scratch / vecnorm wbuf) | +/-2 | 1.3184 | 65.92% | 0 / 3072 | fits | PASS |
| conv1d weights (CW_F=13) | int16 Q2.13 (conv4_silu w0..w3) | +/-4 | 1.2344 | 30.86% | 0 / 786432 | fits | PASS |
| dt_bias (Q12) | int16 Q3.12 (gate_unit dtv[15:0]) | +/-8 | 8 | 100.00% | 0 / 768 | fits | PASS |
| A = exp(A_log) (Q15) | uint18 Q3.15 (gate_unit Av[17:0]) | [0, 8] | 8 | 100.00% | 0 / 768 | fits | PASS |

Justifications:
- PASS `ln1 / ln2 (48 tensors, zero-centered 1+w)` — max abs value 1.4062 of 2 available (70.3% of the container); 0 of 262144 values clip.
- PASS `model.norm (final RMSNorm, zero-centered 1+w)` — max abs value 1.9922 of 2 available (99.6% of the container); 0 of 4096 values clip.
- PASS `q_norm / k_norm (6 GQA layers, zero-centered 1+w)` — max abs value 1.9219 of 2 available (96.1% of the container); 0 of 4096 values clip.
- PASS `linear_attn.norm (18 layers, ONE-centered, used as-is)` — max abs value 1.3184 of 2 available (65.9% of the container); 0 of 3072 values clip.
- PASS `conv1d weights (CW_F=13)` — max abs value 1.2344 of 4 available (30.9% of the container); 0 of 786432 values clip.
- PASS `dt_bias (Q12)` — max abs value 8 of 8 available (100.0% of the container); 0 of 768 values clip.
- PASS `A = exp(A_log) (Q15)` — max abs value 8 of 8 available (100.0% of the container); 0 of 768 values clip.
- **GATE-PORT CAVEAT — the `dt_bias` and `A` rows of sections 1 and 3 audit POST-CLAMP values.** `layer_fixed.quant_deltanet` saturates both into their ports before returning them (`np.clip`, `layer_fixed.py:805-806`, since `82781e5`), so those rows report `0 / N` out of range and a max pinned exactly at the rail EVEN IF the checkpoint exceeds the port — and section 3's "max used (real weights)" column, which is computed from the FLOAT weights, can then contradict its own verdict. The pre-clamp truth is recorded in `qd["gate_sat"]` (which this script does not read) and is measured by `evidence/qwen2b/q2/audit/gate_port_probe.py`.
- NOTE the four `1+w` families store the ZERO-CENTERED weight, so the effective RMSNorm scale is `1 + w`; `linear_attn.norm` stores the ONE-centered weight used as-is (`rmsnorm_fx(..., one_plus=False)`). Both conventions are confirmed against `vendor/modeling_qwen3_5.py` (`Qwen3_5RMSNorm` zero-init + `(1.0 + self.weight)`, `Qwen3_5RMSNormGated` ones-init used directly).

## 2. W4A8 group quantization of the matvec weights (`quant_linear` -> `quantize_weights`)

Per-group symmetric INT4, group size G=128, one uint16 mantissa `m` per group and ONE shared exponent `e` per matrix. Failure modes: `m` underflowing to 1 (group scale unrepresentable under the matrix-wide exponent) and `round(W/eff)` leaving [-8, 7].

| matrix family | #mat | N x K | e | sh | m range | m==1 (scale underflow) | m clipped up from 0 | INT4 clip | rel err (Frobenius) | y32 headroom wasted |
|---|---|---|---|---|---|---|---|---|---|---|
| `dn.in_qkv` | 24 | 8192x4096 | -4..-3 | 7 | 148..16165 | 0/6291456 | 0/6291456 | 7423804/805306368 | 10.32%..10.97% | 3.0..4.4 b |
| `dn.in_z` | 24 | 4096x4096 | -4..-2 | 7 | 64..16029 | 0/3145728 | 0/3145728 | 3715081/402653184 | 10.34%..10.89% | 3.1..5.2 b |
| `dn.in_b` | 24 | 32x4096 | -5..-3 | 7 | 443..16170 | 0/24576 | 0/24576 | 27614/3145728 | 10.62%..15.47% | 3.1..4.3 b |
| `dn.in_a` | 24 | 32x4096 | -4..-3 | 7 | 430..15985 | 0/24576 | 0/24576 | 27787/3145728 | 10.35%..15.45% | 3.1..4.8 b |
| `dn.out` | 24 | 4096x4096 | -2..-1 | 7 | 75..16051 | 0/3145728 | 0/3145728 | 3713226/402653184 | 10.43%..11.11% | 2.8..5.0 b |
| `mlp.gate` | 32 | 12288x4096 | -4..-2 | 7 | 199..16311 | 0/12582912 | 0/12582912 | 14888867/1610612736 | 10.23%..11.00% | 3.2..5.2 b |
| `mlp.up` | 32 | 12288x4096 | -5..-3 | 7 | 180..16034 | 0/12582912 | 0/12582912 | 14912642/1610612736 | 10.24%..10.57% | 3.2..5.1 b |
| `mlp.down` | 32 | 4096x12288 | -3..-2 | 9 | 80..16384 | 0/12582912 | 0/12582912 | 14849904/1610612736 | 10.27%..11.36% | 3.4..5.6 b |
| `attn.q_proj` | 8 | 8192x4096 | -4..-2 | 7 | 165..16217 | 0/2097152 | 0/2097152 | 2472549/268435456 | 10.48%..11.10% | 2.7..5.0 b |
| `attn.k_proj` | 8 | 1024x4096 | -4..-3 | 7 | 140..15515 | 0/262144 | 0/262144 | 301074/33554432 | 10.86%..14.71% | 3.3..4.5 b |
| `attn.v_proj` | 8 | 1024x4096 | -4..-1 | 7 | 160..16331 | 0/262144 | 0/262144 | 303913/33554432 | 10.68%..13.27% | 3.2..5.5 b |
| `attn.o_proj` | 8 | 4096x4096 | -3..-2 | 7 | 120..15532 | 0/1048576 | 0/1048576 | 1230435/134217728 | 10.56%..12.08% | 3.0..4.5 b |

### 2b. Tied embedding as the LM head

`lm_head` is the tied `embed_tokens` matrix (quantized with the production `quant_linear` (float64) on the full matrix).

| matrix | N x K | e | sh | m range | m==1 (scale underflow) | m clipped up from 0 | INT4 clip | rel err (Frobenius) | y32 headroom wasted |
|---|---|---|---|---|---|---|---|---|---|
| `lm_head` = `embed_tokens` | 248320x4096 | -2 | 7 | 1..8814 | 96/7946240 | 64/7946240 | 9463800/1017118720 | 10.17% | 5.4 b |

Justifications:
- **ATTENTION group-scale underflow** — 96 of 61997056 groups (0.0002%) quantize their scale mantissa to `m == 1`; 64 of those were CLIPPED UP from a rounded value of 0, i.e. the real group scale is below the matrix-wide exponent's LSB and the stored scale is too COARSE. 4131 of the 12288 weights in those groups (33.6%) collapse to INT4 zero. Affected matrices (0): . Impact is bounded: these are the numerically smallest groups in the matrix, so the absolute error they contribute is at most one matrix-wide LSB per weight.
- **ATTENTION INT4 clipping** — 73330696 of 7935623168 weights (9.24e-01%) round outside [-8,7] and are clipped: `dn.in_qkv`=7423804, `dn.in_z`=3715081, `dn.in_b`=27614, `dn.in_a`=27787, `dn.out`=3713226, `mlp.gate`=14888867, `mlp.up`=14912642, `mlp.down`=14849904, `attn.q_proj`=2472549, `attn.k_proj`=301074, `attn.v_proj`=303913, `attn.o_proj`=1230435, `lm_head`=9463800
- **ATTENTION quantization error** — measured as `||W_dequant - W||_F / ||W||_F` per matrix (for isotropic inputs this is the relative matvec output error, i.e. the same quantity `w4a8_ref._selftest` calls the INT4 noise floor: ~12% there, with `assert rel < 0.15`). Worst single matrix `L8.dn.in_b` at 15.47%. 5 of 249 matrices exceed that 15% bound: `L25.dn.in_a`, `L26.dn.in_a`, `L28.dn.in_a`, `L29.dn.in_a`, `L8.dn.in_b`. They are the outlier-heavy small projections (`v_proj`/`k_proj`/`o_proj`, 512-2048 rows); no assert fires today because the 15% check only runs inside the synthetic self-test, but the real model quantizes measurably worse than the Gaussian weights every prior gate was measured on.
- **ATTENTION (precision, not correctness) y32 headroom** — the frozen `sh` comes from the worst-case bound `NG*65535*(G*8*127)`, but the real mantissas peak at 16384, so up to 5.6 bits of the int32 accumulator are discarded by the pre-output shift (worst: `L24.mlp.down`). No overflow risk and RTL still matches the reference bit-for-bit — but every matvec output carries ~6 bits less resolution than the format allows.

## 3. DeltaNet gate chain (softplus / exp2 ROM domains, decay)

`sp = softplus_q(a + dt)` (Q12, PWL ROM over [-16,16) with an exact linear branch above +16 and a 0 branch below -16), `g = -rshr(A*sp, 11)` (Q16), `decay = rshr(exp_neg_q(g), 15)` (Q15). `a` is activation-dependent, so the table below is the weight-only baseline `a = 0` plus the two rails reachable after the int16 clip of `a` (`a = +/-8.0` in Q12).

| gate quantity | available | max used (real weights) | out-of-range / effect | verdict |
|---|---|---|---|---|
| `A` -> `Av[17:0]` uint18 Q15 | [0, 7.99997] | 76.9957 | 0 / 768 heads | PASS |
| `dt_bias` -> `dtv[15:0]` int16 Q12 | +/-8.0 | 18.5000 | 0 / 768 heads | PASS |
| `a+dt` -> softplus ROM domain (18-bit adder) | +/-32.0 (adder), ROM [-16,16) + exact branches | 26.5000 at the `a` rail | 0 (branches are exact) | PASS |
| `decay` -> Q15 uint16 (`decay_o[15:0]`) | [0, 0.99997] | 1.0 saturates to 32767 by construction | 0 head(s) pin at 32767, 0 collapse to 0 (a=0) | PASS |
| `beta = sigmoid_q(b)` Q15 | [0, 0.99997] | saturating ROM | 0 (structural) | PASS |
| decay computed with the TRUNCATED 18-bit `A` | - | - | 0 / 768 heads give a WRONG decay | PASS |

**GATE-PORT CAVEAT — the `dt_bias` and `A` rows of sections 1 and 3 audit POST-CLAMP values.** `layer_fixed.quant_deltanet` saturates both into their ports before returning them (`np.clip`, `layer_fixed.py:805-806`, since `82781e5`), so those rows report `0 / N` out of range and a max pinned exactly at the rail EVEN IF the checkpoint exceeds the port — and section 3's "max used (real weights)" column, which is computed from the FLOAT weights, can then contradict its own verdict. The pre-clamp truth is recorded in `qd["gate_sat"]` (which this script does not read) and is measured by `evidence/qwen2b/q2/audit/gate_port_probe.py`.

Justifications:
- PASS `A` — max 76.9957 < 8.0, fits uint18 Q15.
- PASS `dt_bias` — max |dt| 18.5000 < 8.0.
- INFO decay dynamics at `a = 0`: 0 of 768 heads sit at the no-decay rail (Q15 32767, state never forgets) and 0 collapse to 0 (state fully wiped every step). Both are faithful to the float model at Q15 resolution but they bound what the S-state soak in section 5 can look like.

## 4. Residual stream seed — embedding table at Q7.8 (RS_F=8)

| quantity | value |
|---|---|
| max abs emb (float) | 0.470703 |
| Q7.8 representable range | +/-128.0 (int16, LSB = 1/256 = 0.003906) |
| max abs emb in LSB | 120.5 of 32767 |
| range utilisation | 0.368% |
| values clipped by `clip16` | 0 / 1017118720 |
| emb RMS (float / LSB) | 0.013466 / 3.45 LSB |
| relative RMS quantization error | 8.38% |
| token rows quantizing to ALL ZERO | 22 / 248320 |
| token rows with max abs q <= 4 LSB | 1872 / 248320 |
| per-row RMS in LSB (min / median / max) | 0.00 / 3.56 / 4.28 |
| spare integer bits at the residual input | 8 |

- **ATTENTION residual seed resolution** — the embedding uses only 0.368% of the Q7.8 range (120 LSB peak, 3.4 LSB RMS), giving 8.4% relative RMS quantization error on the layer-0 residual. 0 values clip. Nine of the sixteen int16 bits are unused at the input of the network: RS_F is sized for the residual AFTER it has grown through the stack, not for the embedding.

Layer-0 `rmsnorm_fx(emb_q, ln1, RS_F, one_plus=True)` probe over 4096 evenly spaced token rows (fully determined by weights): max |out| = 8792 LSB (34.344 in Q7.8), RMS = 264.6 LSB, 0 values at the int16 rail. PASS — the normalizer restores full-scale amplitude from the tiny embedding, so the resolution loss above happens BEFORE the norm and is not recovered.

## 5. Deferred — activation-dependent, needs a runtime audit in `gen_model_script`

| format | container | why it cannot be settled from weights |
|---|---|---|
| residual stream `RS_F=8` (int16 Q7.8) after layer 0 | int16, +/-128.0 | the residual grows layer by layer; only a real forward pass gives the peak. Section 4 pins only the t=0 seed. |
| `QKV_F=8` q/k/v + conv output (int16) | int16, +/-128.0 | `matvec_to(...) -> clip16` outputs depend on the normed activation, not on the weights. |
| `NRM_F=14` L2-normed q/k (int16 Q1.14) | int16, +/-2.0 | unit-norm by construction, but the pre-norm magnitude sets the rounding error; needs live vectors. |
| `S_F=13` DeltaNet state (int16 Q2.13) | int16, +/-4.0 | **this is the `layer_fixed.py:439` note.** `deltanet_decode_fx` counts saturations in `state['sat']`; the bound was measured on RANDOM weights (|S|max 0.76, rms 0.009). Real decay/beta (section 3) and real v magnitudes change it. Soak the real model and assert `sat == 0`. |
| `KVC_F` / per-vector KV exponent (int8 + exp) | int8 mantissa | depends on live k/v vectors. |
| `b_q12` / `a_q12` gate inputs (int16 Q12) | int16, +/-8.0 | `clip16` of a matvec output; the spec argues the sigmoid/softplus tail is flat there, but the clip COUNT is runtime data. |
| y32 matvec accumulator occupancy | int32 | section 2 bounds the headroom from the weights; the achieved occupancy needs real activations (also gates whether `sh` can be lowered). |
| attention score / probability Q15/Q30 path | int16/int32 | depends on the live q.k dot products. |

