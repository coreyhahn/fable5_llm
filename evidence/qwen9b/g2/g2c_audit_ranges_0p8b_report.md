# Increment (3) PREP — fixed-point range audit vs the real Qwen3.5-0.8B weights

- generated: `2026-08-31 11:48:55`  (repo `b242370`)
- checkpoint: `/home/cah/.cache/huggingface/hub/models--Qwen--Qwen3.5-0.8B/snapshots/2fc06364715b967f1860aea9cf38778875588b17/model.safetensors-00001-of-00001.safetensors`
- safetensors header sha256: `c894b6055113f9d5a9c5c68e703662de8ba27df5a9631b47f10b75ac3fe0b083`
- model: 24 layers (18 DeltaNet + 6 GQA), H=1024, FFN=3584, vocab=248320 (TIED embeddings: the LM head is a copy of `embed_tokens`)
- frozen formats under test: RS_F=8 QKV_F=8 NRM_F=14 S_F=13 GAT_F=15 CW_F=13 ROPE_F=15 KVC_F=6, W4 group G=128
- quantizers exercised: `layer_fixed.quant_layer` (-> `quant_attn` / `quant_deltanet` / `quant_mlp` / `quant_linear`), `w4a8_ref.quantize_weights`, `fixedpoint.softplus_q` / `exp_neg_q` / `sigmoid_q`. Nothing is re-implemented here.
- W4 group-scale rule in force (`quant_linear` default `mse_scale`): **MSE-optimal (quant_linear_mse)** — section 2's `e` / `m` / INT4-clip / error columns are produced by THIS rule.
- `res_scale = 1.0` (`quant_layer` default). res_scale is a power-of-two prescale of the three residual-writing matrices (`o_proj` / `dn.out` / `mlp.down`) and of the embedding seed, so it moves section 2's `e` column by exactly log2(S) on those families and nothing else there; section 4's seed occupancy DOES scale with S (see the runtime note in section 5).

**GATE-PORT CAVEAT — the `dt_bias` and `A` rows of sections 1 and 3 audit POST-CLAMP values.** `layer_fixed.quant_deltanet` saturates both into their ports before returning them (`np.clip`, `layer_fixed.py:805-806`, since `82781e5`), so those rows report `0 / N` out of range and a max pinned exactly at the rail EVEN IF the checkpoint exceeds the port — and section 3's "max used (real weights)" column, which is computed from the FLOAT weights, can then contradict its own verdict. The pre-clamp truth is recorded in `qd["gate_sat"]` (which this script does not read) and is measured by `evidence/qwen2b/q2/audit/gate_port_probe.py`.

## 0. Verdict summary

**5 ATTENTION item(s)**:
1. `model.norm (final RMSNorm, zero-centered 1+w)`: 976/1024 values exceed int16 Q1.14 (scratch / vecnorm wbuf) (max 5.3125 vs 2)
2. W4 group-scale underflow: 112/5874176 groups hit `m==1` (112 clipped up from 0), annihilating 14336 weights
3. W4 value clipping (round(W/eff) outside [-8,7])
4. y32 headroom: conservative `sh` discards up to 5.3 bits of the int32 accumulator (precision only, no overflow)
5. embedding at Q7.8 uses 0.18% of the int16 range (59 LSB peak, 5.0 LSB RMS) -> 5.7% relative RMS error on the layer-0 residual

Matrices quantized with the production path: 186 + 1 LM head = 187 (`gen_token_script` expects 187 weight images at 24 layers: 8 per DeltaNet layer, 7 per full-attention layer, + the LM head).

## 1. Direct constant formats (int16 / uint18 transport)

Every row is a HARD limit: `gen_layer_script.Mach.W` asserts the int16 range, so an out-of-range value aborts script generation; `Mach.W_raw` (A) masks to 16+2 bits and would wrap silently.

| format / tensor family | container | available | max abs value | range util | out-of-range | smallest container that fits | verdict |
|---|---|---|---|---|---|---|---|
| ln1 / ln2 (48 tensors, zero-centered 1+w) | int16 Q1.14 (scratch / vecnorm wbuf) | +/-2 | 1.4688 | 73.44% | 0 / 49152 | fits | PASS |
| model.norm (final RMSNorm, zero-centered 1+w) | int16 Q1.14 (scratch / vecnorm wbuf) | +/-2 | 5.3125 | 265.62% | 976 / 1024 | Q3.12 in int16, or 18 bits at Q14 | ATTENTION |
| q_norm / k_norm (6 GQA layers, zero-centered 1+w) | int16 Q1.14 (scratch / vecnorm wbuf) | +/-2 | 1.6328 | 81.64% | 0 / 3072 | fits | PASS |
| linear_attn.norm (18 layers, ONE-centered, used as-is) | int16 Q1.14 (scratch / vecnorm wbuf) | +/-2 | 1.1943 | 59.72% | 0 / 2304 | fits | PASS |
| conv1d weights (CW_F=13) | int16 Q2.13 (conv4_silu w0..w3) | +/-4 | 1.8203 | 45.51% | 0 / 442368 | fits | PASS |
| dt_bias (Q12) | int16 Q3.12 (gate_unit dtv[15:0]) | +/-8 | 8 | 100.00% | 0 / 288 | fits | PASS |
| A = exp(A_log) (Q15) | uint18 Q3.15 (gate_unit Av[17:0]) | [0, 8] | 8 | 100.00% | 0 / 288 | fits | PASS |

Justifications:
- PASS `ln1 / ln2 (48 tensors, zero-centered 1+w)` — max abs value 1.4688 of 2 available (73.4% of the container); 0 of 49152 values clip.
- **ATTENTION `model.norm (final RMSNorm, zero-centered 1+w)`** — 976 of 1024 values exceed the container (max abs value 5.3125 vs 2 representable, 166% over). Offenders: model.norm[1]=2.75, model.norm[2]=2.641, model.norm[3]=3.062, model.norm[4]=2.703, model.norm[5]=2.781, model.norm[6]=3 ... Would fit at Q.12 in the same container, or at the frozen Q.14 with 18 bits.
- PASS `q_norm / k_norm (6 GQA layers, zero-centered 1+w)` — max abs value 1.6328 of 2 available (81.6% of the container); 0 of 3072 values clip.
- PASS `linear_attn.norm (18 layers, ONE-centered, used as-is)` — max abs value 1.1943 of 2 available (59.7% of the container); 0 of 2304 values clip.
- PASS `conv1d weights (CW_F=13)` — max abs value 1.8203 of 4 available (45.5% of the container); 0 of 442368 values clip.
- PASS `dt_bias (Q12)` — max abs value 8 of 8 available (100.0% of the container); 0 of 288 values clip.
- PASS `A = exp(A_log) (Q15)` — max abs value 8 of 8 available (100.0% of the container); 0 of 288 values clip.
- **GATE-PORT CAVEAT — the `dt_bias` and `A` rows of sections 1 and 3 audit POST-CLAMP values.** `layer_fixed.quant_deltanet` saturates both into their ports before returning them (`np.clip`, `layer_fixed.py:805-806`, since `82781e5`), so those rows report `0 / N` out of range and a max pinned exactly at the rail EVEN IF the checkpoint exceeds the port — and section 3's "max used (real weights)" column, which is computed from the FLOAT weights, can then contradict its own verdict. The pre-clamp truth is recorded in `qd["gate_sat"]` (which this script does not read) and is measured by `evidence/qwen2b/q2/audit/gate_port_probe.py`.
- NOTE the four `1+w` families store the ZERO-CENTERED weight, so the effective RMSNorm scale is `1 + w`; `linear_attn.norm` stores the ONE-centered weight used as-is (`rmsnorm_fx(..., one_plus=False)`). Both conventions are confirmed against `vendor/modeling_qwen3_5.py` (`Qwen3_5RMSNorm` zero-init + `(1.0 + self.weight)`, `Qwen3_5RMSNormGated` ones-init used directly).

## 2. W4A8 group quantization of the matvec weights (`quant_linear` -> `quantize_weights`)

Per-group symmetric INT4, group size G=128, one uint16 mantissa `m` per group and ONE shared exponent `e` per matrix. Failure modes: `m` underflowing to 1 (group scale unrepresentable under the matrix-wide exponent) and `round(W/eff)` leaving [-8, 7].

| matrix family | #mat | N x K | e | sh | m range | m==1 (scale underflow) | m clipped up from 0 | INT4 clip | rel err (Frobenius) | y32 headroom wasted |
|---|---|---|---|---|---|---|---|---|---|---|
| `dn.in_qkv` | 18 | 6144x1024 | -4..-2 | 5 | 1..16091 | 112/884736 | 112/884736 | 1043863/113246208 | 10.41%..11.04% | 2.6..3.9 b |
| `dn.in_z` | 18 | 2048x1024 | -4..-3 | 5 | 168..13827 | 0/294912 | 0/294912 | 348467/37748736 | 10.31%..10.87% | 2.9..4.0 b |
| `dn.in_b` | 18 | 16x1024 | -5..-4 | 5 | 866..16294 | 0/2304 | 0/2304 | 2714/294912 | 10.51%..12.31% | 2.6..4.2 b |
| `dn.in_a` | 18 | 16x1024 | -4..-3 | 5 | 287..13260 | 0/2304 | 0/2304 | 2739/294912 | 10.25%..12.43% | 2.8..4.4 b |
| `dn.out` | 18 | 1024x2048 | -4..-3 | 6 | 137..15626 | 0/294912 | 0/294912 | 344637/37748736 | 10.57%..11.78% | 2.9..4.4 b |
| `mlp.gate` | 24 | 3584x1024 | -4..-3 | 5 | 210..16029 | 0/688128 | 0/688128 | 814536/88080384 | 10.20%..11.23% | 2.8..3.7 b |
| `mlp.up` | 24 | 3584x1024 | -5..-3 | 5 | 151..13923 | 0/688128 | 0/688128 | 813464/88080384 | 10.31%..10.82% | 3.1..4.6 b |
| `mlp.down` | 24 | 1024x3584 | -5..-3 | 7 | 183..16096 | 0/688128 | 0/688128 | 808873/88080384 | 10.37%..11.41% | 2.9..4.6 b |
| `attn.q_proj` | 6 | 4096x1024 | -4..-3 | 5 | 80..16096 | 0/196608 | 0/196608 | 231014/25165824 | 10.33%..11.30% | 2.4..4.0 b |
| `attn.k_proj` | 6 | 512x1024 | -5..-4 | 5 | 298..15018 | 0/24576 | 0/24576 | 28824/3145728 | 10.41%..12.84% | 2.8..4.2 b |
| `attn.v_proj` | 6 | 512x1024 | -4..-2 | 5 | 196..12080 | 0/24576 | 0/24576 | 28533/3145728 | 10.91%..14.00% | 3.7..5.3 b |
| `attn.o_proj` | 6 | 1024x2048 | -4..-3 | 6 | 152..14800 | 0/98304 | 0/98304 | 114298/12582912 | 10.83%..13.23% | 3.0..3.9 b |

### 2b. Tied embedding as the LM head

`lm_head` is the tied `embed_tokens` matrix (quantized with the production `quant_linear` (float64) on the full matrix).

| matrix | N x K | e | sh | m range | m==1 (scale underflow) | m clipped up from 0 | INT4 clip | rel err (Frobenius) | y32 headroom wasted |
|---|---|---|---|---|---|---|---|---|---|
| `lm_head` = `embed_tokens` | 248320x1024 | -4 | 5 | 1383..13378 | 0/1986560 | 0/1986560 | 2330322/254279680 | 10.74% | 3.3 b |

Justifications:
- **ATTENTION group-scale underflow** — 112 of 5874176 groups (0.0019%) quantize their scale mantissa to `m == 1`; 112 of those were CLIPPED UP from a rounded value of 0, i.e. the real group scale is below the matrix-wide exponent's LSB and the stored scale is too COARSE. 14336 of the 14336 weights in those groups (100.0%) collapse to INT4 zero. Affected matrices (1): `L0.dn.in_qkv`. Impact is bounded: these are the numerically smallest groups in the matrix, so the absolute error they contribute is at most one matrix-wide LSB per weight.
- **ATTENTION INT4 clipping** — 6912284 of 751894528 weights (9.19e-01%) round outside [-8,7] and are clipped: `dn.in_qkv`=1043863, `dn.in_z`=348467, `dn.in_b`=2714, `dn.in_a`=2739, `dn.out`=344637, `mlp.gate`=814536, `mlp.up`=813464, `mlp.down`=808873, `attn.q_proj`=231014, `attn.k_proj`=28824, `attn.v_proj`=28533, `attn.o_proj`=114298, `lm_head`=2330322
- INFO quantization error — measured as `||W_dequant - W||_F / ||W||_F` per matrix (for isotropic inputs this is the relative matvec output error, i.e. the same quantity `w4a8_ref._selftest` calls the INT4 noise floor: ~12% there, with `assert rel < 0.15`). Worst single matrix `L19.attn.v_proj` at 14.00%. Every matrix stays inside the 15% bound, so real weights quantize no worse than the synthetic weights every prior gate was measured on.
- **ATTENTION (precision, not correctness) y32 headroom** — the frozen `sh` comes from the worst-case bound `NG*65535*(G*8*127)`, but the real mantissas peak at 16294, so up to 5.3 bits of the int32 accumulator are discarded by the pre-output shift (worst: `L23.attn.v_proj`). No overflow risk and RTL still matches the reference bit-for-bit — but every matvec output carries ~5 bits less resolution than the format allows.

## 3. DeltaNet gate chain (softplus / exp2 ROM domains, decay)

`sp = softplus_q(a + dt)` (Q12, PWL ROM over [-16,16) with an exact linear branch above +16 and a 0 branch below -16), `g = -rshr(A*sp, 11)` (Q16), `decay = rshr(exp_neg_q(g), 15)` (Q15). `a` is activation-dependent, so the table below is the weight-only baseline `a = 0` plus the two rails reachable after the int16 clip of `a` (`a = +/-8.0` in Q12).

| gate quantity | available | max used (real weights) | out-of-range / effect | verdict |
|---|---|---|---|---|
| `A` -> `Av[17:0]` uint18 Q15 | [0, 7.99997] | 10.5843 | 0 / 288 heads | PASS |
| `dt_bias` -> `dtv[15:0]` int16 Q12 | +/-8.0 | 13.0625 | 0 / 288 heads | PASS |
| `a+dt` -> softplus ROM domain (18-bit adder) | +/-32.0 (adder), ROM [-16,16) + exact branches | 21.0625 at the `a` rail | 0 (branches are exact) | PASS |
| `decay` -> Q15 uint16 (`decay_o[15:0]`) | [0, 0.99997] | 1.0 saturates to 32767 by construction | 1 head(s) pin at 32767, 0 collapse to 0 (a=0) | PASS |
| `beta = sigmoid_q(b)` Q15 | [0, 0.99997] | saturating ROM | 0 (structural) | PASS |
| decay computed with the TRUNCATED 18-bit `A` | - | - | 0 / 288 heads give a WRONG decay | PASS |

**GATE-PORT CAVEAT — the `dt_bias` and `A` rows of sections 1 and 3 audit POST-CLAMP values.** `layer_fixed.quant_deltanet` saturates both into their ports before returning them (`np.clip`, `layer_fixed.py:805-806`, since `82781e5`), so those rows report `0 / N` out of range and a max pinned exactly at the rail EVEN IF the checkpoint exceeds the port — and section 3's "max used (real weights)" column, which is computed from the FLOAT weights, can then contradict its own verdict. The pre-clamp truth is recorded in `qd["gate_sat"]` (which this script does not read) and is measured by `evidence/qwen2b/q2/audit/gate_port_probe.py`.

Justifications:
- PASS `A` — max 10.5843 < 8.0, fits uint18 Q15.
- PASS `dt_bias` — max |dt| 13.0625 < 8.0.
- INFO decay dynamics at `a = 0`: 1 of 288 heads sit at the no-decay rail (Q15 32767, state never forgets) and 0 collapse to 0 (state fully wiped every step). Both are faithful to the float model at Q15 resolution but they bound what the S-state soak in section 5 can look like.

## 4. Residual stream seed — embedding table at Q7.8 (RS_F=8)

| quantity | value |
|---|---|
| max abs emb (float) | 0.230469 |
| Q7.8 representable range | +/-128.0 (int16, LSB = 1/256 = 0.003906) |
| max abs emb in LSB | 59.0 of 32767 |
| range utilisation | 0.180% |
| values clipped by `clip16` | 0 / 254279680 |
| emb RMS (float / LSB) | 0.019697 / 5.04 LSB |
| relative RMS quantization error | 5.73% |
| token rows quantizing to ALL ZERO | 0 / 248320 |
| token rows with max abs q <= 4 LSB | 0 / 248320 |
| per-row RMS in LSB (min / median / max) | 2.78 / 4.99 / 8.45 |
| spare integer bits at the residual input | 9 |

- **ATTENTION residual seed resolution** — the embedding uses only 0.180% of the Q7.8 range (59 LSB peak, 5.0 LSB RMS), giving 5.7% relative RMS quantization error on the layer-0 residual. 0 values clip. Nine of the sixteen int16 bits are unused at the input of the network: RS_F is sized for the residual AFTER it has grown through the stack, not for the embedding.

Layer-0 `rmsnorm_fx(emb_q, ln1, RS_F, one_plus=True)` probe over 4096 evenly spaced token rows (fully determined by weights): max |out| = 2828 LSB (11.047 in Q7.8), RMS = 321.8 LSB, 0 values at the int16 rail. PASS — the normalizer restores full-scale amplitude from the tiny embedding, so the resolution loss above happens BEFORE the norm and is not recovered.

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

