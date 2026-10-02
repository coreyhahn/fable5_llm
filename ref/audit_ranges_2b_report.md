# Increment (3) PREP — fixed-point range audit vs the real Qwen3.5-2B weights

- generated: `2026-08-13 09:51:59`  (repo `ccfad30`)
- checkpoint: `/home/cah/.cache/huggingface/hub/models--Qwen--Qwen3.5-2B/snapshots/15852e8c16360a2fea060d615a32b45270f8a8fc/model.safetensors-00001-of-00001.safetensors`
- safetensors header sha256: `ccba2c1f645fe59268f89ee7ea552e02ce6bf0c8a087bf332fb0e3bd99bfee9d`
- model: 24 layers (18 DeltaNet + 6 GQA), H=2048, FFN=6144, vocab=248320 (tied embeddings)
- frozen formats under test: RS_F=8 QKV_F=8 NRM_F=14 S_F=13 GAT_F=15 CW_F=13 ROPE_F=15 KVC_F=6, W4 group G=128
- quantizers exercised: `layer_fixed.quant_layer` (-> `quant_attn` / `quant_deltanet` / `quant_mlp` / `quant_linear`), `w4a8_ref.quantize_weights`, `fixedpoint.softplus_q` / `exp_neg_q` / `sigmoid_q`. Nothing is re-implemented here.
- W4 group-scale rule in force (`quant_linear` default `mse_scale`): **MSE-optimal (quant_linear_mse)** — section 2's `e` / `m` / INT4-clip / error columns are produced by THIS rule.
- `res_scale = 1.0` (`quant_layer` default). res_scale is a power-of-two prescale of the three residual-writing matrices (`o_proj` / `dn.out` / `mlp.down`) and of the embedding seed, so it moves section 2's `e` column by exactly log2(S) on those families and nothing else there; section 4's seed occupancy DOES scale with S (see the runtime note in section 5).

**GATE-PORT CAVEAT — the `dt_bias` and `A` rows of sections 1 and 3 audit POST-CLAMP values.** `layer_fixed.quant_deltanet` saturates both into their ports before returning them (`np.clip`, `layer_fixed.py:805-806`, since `82781e5`), so those rows report `0 / N` out of range and a max pinned exactly at the rail EVEN IF the checkpoint exceeds the port — and section 3's "max used (real weights)" column, which is computed from the FLOAT weights, can then contradict its own verdict. The pre-clamp truth is recorded in `qd["gate_sat"]` (which this script does not read) and is measured by `evidence/qwen2b/q2/audit/gate_port_probe.py`.

## 0. Verdict summary

**6 ATTENTION item(s)**:
1. `model.norm (final RMSNorm, zero-centered 1+w)`: 1890/2048 values exceed int16 Q1.14 (scratch / vecnorm wbuf) (max 5.375 vs 2)
2. W4 group-scale underflow: 224/14697472 groups hit `m==1` (224 clipped up from 0), annihilating 28672 weights
3. W4 value clipping (round(W/eff) outside [-8,7])
4. W4 weight error above the project's own 15% bound on 15/187 matrices (worst `L19.attn.v_proj` 17.28%)
5. y32 headroom: conservative `sh` discards up to 5.9 bits of the int32 accumulator (precision only, no overflow)
6. embedding at Q7.8 uses 0.15% of the int16 range (50 LSB peak, 3.8 LSB RMS) -> 7.5% relative RMS error on the layer-0 residual

Matrices quantized with the production path: 186 + 1 LM head = 187 (`gen_token_script` expects 187 weight images at 24 layers).

## 1. Direct constant formats (int16 / uint18 transport)

Every row is a HARD limit: `gen_layer_script.Mach.W` asserts the int16 range, so an out-of-range value aborts script generation; `Mach.W_raw` (A) masks to 16+2 bits and would wrap silently.

| format / tensor family | container | available | max abs value | range util | out-of-range | smallest container that fits | verdict |
|---|---|---|---|---|---|---|---|
| ln1 / ln2 (48 tensors, zero-centered 1+w) | int16 Q1.14 (scratch / vecnorm wbuf) | +/-2 | 1.2031 | 60.16% | 0 / 98304 | fits | PASS |
| model.norm (final RMSNorm, zero-centered 1+w) | int16 Q1.14 (scratch / vecnorm wbuf) | +/-2 | 5.375 | 268.75% | 1890 / 2048 | Q3.12 in int16, or 18 bits at Q14 | ATTENTION |
| q_norm / k_norm (6 GQA layers, zero-centered 1+w) | int16 Q1.14 (scratch / vecnorm wbuf) | +/-2 | 1.5938 | 79.69% | 0 / 3072 | fits | PASS |
| linear_attn.norm (18 layers, ONE-centered, used as-is) | int16 Q1.14 (scratch / vecnorm wbuf) | +/-2 | 1.2373 | 61.87% | 0 / 2304 | fits | PASS |
| conv1d weights (CW_F=13) | int16 Q2.13 (conv4_silu w0..w3) | +/-4 | 1.5625 | 39.06% | 0 / 442368 | fits | PASS |
| dt_bias (Q12) | int16 Q3.12 (gate_unit dtv[15:0]) | +/-8 | 8 | 100.00% | 0 / 288 | fits | PASS |
| A = exp(A_log) (Q15) | uint18 Q3.15 (gate_unit Av[17:0]) | [0, 8] | 8 | 100.00% | 0 / 288 | fits | PASS |

Justifications:
- PASS `ln1 / ln2 (48 tensors, zero-centered 1+w)` — max abs value 1.2031 of 2 available (60.2% of the container); 0 of 98304 values clip.
- **ATTENTION `model.norm (final RMSNorm, zero-centered 1+w)`** — 1890 of 2048 values exceed the container (max abs value 5.375 vs 2 representable, 169% over). Offenders: model.norm[0]=2.766, model.norm[1]=2.703, model.norm[2]=3.875, model.norm[3]=2.906, model.norm[4]=2.016, model.norm[5]=2.609 ... Would fit at Q.12 in the same container, or at the frozen Q.14 with 18 bits.
- PASS `q_norm / k_norm (6 GQA layers, zero-centered 1+w)` — max abs value 1.5938 of 2 available (79.7% of the container); 0 of 3072 values clip.
- PASS `linear_attn.norm (18 layers, ONE-centered, used as-is)` — max abs value 1.2373 of 2 available (61.9% of the container); 0 of 2304 values clip.
- PASS `conv1d weights (CW_F=13)` — max abs value 1.5625 of 4 available (39.1% of the container); 0 of 442368 values clip.
- PASS `dt_bias (Q12)` — max abs value 8 of 8 available (100.0% of the container); 0 of 288 values clip.
- PASS `A = exp(A_log) (Q15)` — max abs value 8 of 8 available (100.0% of the container); 0 of 288 values clip.
- **GATE-PORT CAVEAT — the `dt_bias` and `A` rows of sections 1 and 3 audit POST-CLAMP values.** `layer_fixed.quant_deltanet` saturates both into their ports before returning them (`np.clip`, `layer_fixed.py:805-806`, since `82781e5`), so those rows report `0 / N` out of range and a max pinned exactly at the rail EVEN IF the checkpoint exceeds the port — and section 3's "max used (real weights)" column, which is computed from the FLOAT weights, can then contradict its own verdict. The pre-clamp truth is recorded in `qd["gate_sat"]` (which this script does not read) and is measured by `evidence/qwen2b/q2/audit/gate_port_probe.py`.
- NOTE the four `1+w` families store the ZERO-CENTERED weight, so the effective RMSNorm scale is `1 + w`; `linear_attn.norm` stores the ONE-centered weight used as-is (`rmsnorm_fx(..., one_plus=False)`). Both conventions are confirmed against `vendor/modeling_qwen3_5.py` (`Qwen3_5RMSNorm` zero-init + `(1.0 + self.weight)`, `Qwen3_5RMSNormGated` ones-init used directly).

## 2. W4A8 group quantization of the matvec weights (`quant_linear` -> `quantize_weights`)

Per-group symmetric INT4, group size G=128, one uint16 mantissa `m` per group and ONE shared exponent `e` per matrix. Failure modes: `m` underflowing to 1 (group scale unrepresentable under the matrix-wide exponent) and `round(W/eff)` leaving [-8, 7].

| matrix family | #mat | N x K | e | sh | m range | m==1 (scale underflow) | m clipped up from 0 | INT4 clip | rel err (Frobenius) | y32 headroom wasted |
|---|---|---|---|---|---|---|---|---|---|---|
| `dn.in_qkv` | 18 | 6144x2048 | -4..-3 | 6 | 1..15651 | 224/1769472 | 224/1769472 | 2077607/226492416 | 10.66%..11.79% | 2.8..4.1 b |
| `dn.in_z` | 18 | 2048x2048 | -4..-3 | 6 | 242..14921 | 0/589824 | 0/589824 | 693391/75497472 | 10.55%..11.19% | 2.9..4.2 b |
| `dn.in_b` | 18 | 16x2048 | -5..-4 | 6 | 806..14835 | 0/4608 | 0/4608 | 5100/589824 | 12.72%..16.12% | 2.6..4.1 b |
| `dn.in_a` | 18 | 16x2048 | -5..-4 | 6 | 542..16279 | 0/4608 | 0/4608 | 5210/589824 | 10.88%..15.61% | 2.6..3.9 b |
| `dn.out` | 18 | 2048x2048 | -4..-3 | 6 | 92..16294 | 0/589824 | 0/589824 | 691372/75497472 | 10.63%..11.54% | 3.0..4.0 b |
| `mlp.gate` | 24 | 6144x2048 | -5..-3 | 6 | 318..16229 | 0/2359296 | 0/2359296 | 2782681/301989888 | 10.35%..11.69% | 2.5..4.0 b |
| `mlp.up` | 24 | 6144x2048 | -5..-3 | 6 | 235..16274 | 0/2359296 | 0/2359296 | 2788597/301989888 | 10.29%..10.94% | 3.2..4.4 b |
| `mlp.down` | 24 | 2048x6144 | -4..-1 | 8 | 70..15978 | 0/2359296 | 0/2359296 | 2770680/301989888 | 10.39%..11.67% | 2.9..5.9 b |
| `attn.q_proj` | 6 | 4096x2048 | -4..-3 | 6 | 145..16294 | 0/393216 | 0/393216 | 457423/50331648 | 10.74%..11.92% | 2.9..3.8 b |
| `attn.k_proj` | 6 | 512x2048 | -4 | 6 | 239..11189 | 0/49152 | 0/49152 | 56490/6291456 | 11.34%..16.42% | 3.7..4.0 b |
| `attn.v_proj` | 6 | 512x2048 | -4..-2 | 6 | 291..14702 | 0/49152 | 0/49152 | 55857/6291456 | 11.36%..17.28% | 3.4..4.8 b |
| `attn.o_proj` | 6 | 2048x2048 | -4..-3 | 6 | 117..14957 | 0/196608 | 0/196608 | 228942/25165824 | 10.69%..12.92% | 3.0..3.7 b |

### 2b. Tied embedding as the LM head

`lm_head` is the tied `embed_tokens` matrix (quantized with the production `quant_linear` (float64) on the full matrix).

| matrix | N x K | e | sh | m range | m==1 (scale underflow) | m clipped up from 0 | INT4 clip | rel err (Frobenius) | y32 headroom wasted |
|---|---|---|---|---|---|---|---|---|---|
| `lm_head` = `embed_tokens` | 248320x2048 | -4 | 6 | 1100..12697 | 0/3973120 | 0/3973120 | 4607035/508559360 | 11.26% | 3.3 b |

Justifications:
- **ATTENTION group-scale underflow** — 224 of 14697472 groups (0.0015%) quantize their scale mantissa to `m == 1`; 224 of those were CLIPPED UP from a rounded value of 0, i.e. the real group scale is below the matrix-wide exponent's LSB and the stored scale is too COARSE. 28672 of the 28672 weights in those groups (100.0%) collapse to INT4 zero. Affected matrices (1): `L0.dn.in_qkv`. Impact is bounded: these are the numerically smallest groups in the matrix, so the absolute error they contribute is at most one matrix-wide LSB per weight.
- **ATTENTION INT4 clipping** — 17220385 of 1881276416 weights (9.15e-01%) round outside [-8,7] and are clipped: `dn.in_qkv`=2077607, `dn.in_z`=693391, `dn.in_b`=5100, `dn.in_a`=5210, `dn.out`=691372, `mlp.gate`=2782681, `mlp.up`=2788597, `mlp.down`=2770680, `attn.q_proj`=457423, `attn.k_proj`=56490, `attn.v_proj`=55857, `attn.o_proj`=228942, `lm_head`=4607035
- **ATTENTION quantization error** — measured as `||W_dequant - W||_F / ||W||_F` per matrix (for isotropic inputs this is the relative matvec output error, i.e. the same quantity `w4a8_ref._selftest` calls the INT4 noise floor: ~12% there, with `assert rel < 0.15`). Worst single matrix `L19.attn.v_proj` at 17.28%. 15 of 187 matrices exceed that 15% bound: `L17.dn.in_b`, `L18.dn.in_b`, `L19.attn.v_proj`, `L2.dn.in_b`, `L20.dn.in_a`, `L20.dn.in_b`, `L21.dn.in_a`, `L21.dn.in_b`, `L22.dn.in_a`, `L22.dn.in_b`, `L23.attn.k_proj`, `L23.attn.v_proj` .... They are the outlier-heavy small projections (`v_proj`/`k_proj`/`o_proj`, 512-2048 rows); no assert fires today because the 15% check only runs inside the synthetic self-test, but the real model quantizes measurably worse than the Gaussian weights every prior gate was measured on.
- **ATTENTION (precision, not correctness) y32 headroom** — the frozen `sh` comes from the worst-case bound `NG*65535*(G*8*127)`, but the real mantissas peak at 16294, so up to 5.9 bits of the int32 accumulator are discarded by the pre-output shift (worst: `L23.mlp.down`). No overflow risk and RTL still matches the reference bit-for-bit — but every matvec output carries ~6 bits less resolution than the format allows.

## 3. DeltaNet gate chain (softplus / exp2 ROM domains, decay)

`sp = softplus_q(a + dt)` (Q12, PWL ROM over [-16,16) with an exact linear branch above +16 and a 0 branch below -16), `g = -rshr(A*sp, 11)` (Q16), `decay = rshr(exp_neg_q(g), 15)` (Q15). `a` is activation-dependent, so the table below is the weight-only baseline `a = 0` plus the two rails reachable after the int16 clip of `a` (`a = +/-8.0` in Q12).

| gate quantity | available | max used (real weights) | out-of-range / effect | verdict |
|---|---|---|---|---|
| `A` -> `Av[17:0]` uint18 Q15 | [0, 7.99997] | 10.4202 | 0 / 288 heads | PASS |
| `dt_bias` -> `dtv[15:0]` int16 Q12 | +/-8.0 | 12.3125 | 0 / 288 heads | PASS |
| `a+dt` -> softplus ROM domain (18-bit adder) | +/-32.0 (adder), ROM [-16,16) + exact branches | 20.3125 at the `a` rail | 0 (branches are exact) | PASS |
| `decay` -> Q15 uint16 (`decay_o[15:0]`) | [0, 0.99997] | 1.0 saturates to 32767 by construction | 1 head(s) pin at 32767, 0 collapse to 0 (a=0) | PASS |
| `beta = sigmoid_q(b)` Q15 | [0, 0.99997] | saturating ROM | 0 (structural) | PASS |
| decay computed with the TRUNCATED 18-bit `A` | - | - | 0 / 288 heads give a WRONG decay | PASS |

**GATE-PORT CAVEAT — the `dt_bias` and `A` rows of sections 1 and 3 audit POST-CLAMP values.** `layer_fixed.quant_deltanet` saturates both into their ports before returning them (`np.clip`, `layer_fixed.py:805-806`, since `82781e5`), so those rows report `0 / N` out of range and a max pinned exactly at the rail EVEN IF the checkpoint exceeds the port — and section 3's "max used (real weights)" column, which is computed from the FLOAT weights, can then contradict its own verdict. The pre-clamp truth is recorded in `qd["gate_sat"]` (which this script does not read) and is measured by `evidence/qwen2b/q2/audit/gate_port_probe.py`.

Justifications:
- PASS `A` — max 10.4202 < 8.0, fits uint18 Q15.
- PASS `dt_bias` — max |dt| 12.3125 < 8.0.
- INFO decay dynamics at `a = 0`: 1 of 288 heads sit at the no-decay rail (Q15 32767, state never forgets) and 0 collapse to 0 (state fully wiped every step). Both are faithful to the float model at Q15 resolution but they bound what the S-state soak in section 5 can look like.

## 4. Residual stream seed — embedding table at Q7.8 (RS_F=8)

| quantity | value |
|---|---|
| max abs emb (float) | 0.197266 |
| Q7.8 representable range | +/-128.0 (int16, LSB = 1/256 = 0.003906) |
| max abs emb in LSB | 50.5 of 32767 |
| range utilisation | 0.154% |
| values clipped by `clip16` | 0 / 508559360 |
| emb RMS (float / LSB) | 0.015008 / 3.84 LSB |
| relative RMS quantization error | 7.52% |
| token rows quantizing to ALL ZERO | 0 / 248320 |
| token rows with max abs q <= 4 LSB | 0 / 248320 |
| per-row RMS in LSB (min / median / max) | 2.27 / 3.81 / 6.68 |
| spare integer bits at the residual input | 9 |

- **ATTENTION residual seed resolution** — the embedding uses only 0.154% of the Q7.8 range (50 LSB peak, 3.8 LSB RMS), giving 7.5% relative RMS quantization error on the layer-0 residual. 0 values clip. Nine of the sixteen int16 bits are unused at the input of the network: RS_F is sized for the residual AFTER it has grown through the stack, not for the embedding.

Layer-0 `rmsnorm_fx(emb_q, ln1, RS_F, one_plus=True)` probe over 4096 evenly spaced token rows (fully determined by weights): max |out| = 3145 LSB (12.285 in Q7.8), RMS = 288.9 LSB, 0 values at the int16 rail. PASS — the normalizer restores full-scale amplitude from the tiny embedding, so the resolution loss above happens BEFORE the norm and is not recovered.

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


---

## 6. Diff vs the 0.8B audit (Track Q task 6, appended by hand)

**This section is NOT emitted by `audit_ranges.py`.** It was appended after
the run; re-running the script with `-o ref/audit_ranges_2b_report.md`
rewrites the file and drops it. Everything below is measured — the raw
outputs are `evidence/qwen2b/q2/audit/`.

### 6.1 What is being compared, and the two confounders

| id | report | model | generated | repo | group-scale rule | gate clamp |
|---|---|---|---|---|---|---|
| **A** | `ref/audit_ranges_report.md` (committed) | 0.8B | 2026-07-25 | `763396b` | max\|W_g\|/7 | absent |
| **B** | `evidence/qwen2b/q2/audit/audit_ranges_0.8b_control.md` | 0.8B | 2026-08-13 | `ccfad30` | MSE (`quant_linear_mse`) | present |
| **C** | this report | 2B | 2026-08-13 | `ccfad30` | MSE (`quant_linear_mse`) | present |

Two production changes landed AFTER report A was generated, and both change
what the auditor sees:

1. `07e2d89` (2026-07-26) made `mse_scale=True` the `quant_linear` default.
   Section 2's `e` / `m` / INT4-clip / error columns are a different
   quantizer in A than in B/C.
2. `82781e5` (2026-07-26) added the gate-port clamp at `layer_fixed.py:805-806`
   (`dt_q = clip(dt_spec, int16)`, `A_q = clip(A_spec, 0, 2^18-1)`).
   `audit_ranges.py` feeds sections 1 and 3 with the CLAMPED values, so from
   that commit on it can no longer see a gate-port overflow at all (§6.5).

So **model-vs-model deltas are B -> C**; A -> B is code evolution, not
weights. Control run B exists for exactly this reason and is committed with
this task.

**Host integrity** (the darthplagueis caveat in `evidence/qwen2b/q2/v1_v2/DECOMP.md`
§3.1): B reproduces A to the digit on every number the two code changes
cannot touch — `model.norm` 976/1024 over, max 5.3125; embedding 0.180%
util / 5.73% rel RMS; layer-0 rmsnorm probe max 2828 LSB, RMS 321.8 — and
the W4 group underflow is unchanged at 112 groups / 14336 weights in
`L0.dn.in_qkv` despite the rule change (those rows are FLT_MIN under any
rule, §6.4). The gate probe (§6.5)
independently reproduces A's three corrupted-decay heads value-for-value.
Both audit runs exited 0 (`audit_time_*.txt`); nothing anomalous appeared,
so no re-run was needed.

Both reports were then regenerated once more, after review, to carry the
GATE-PORT CAVEAT from the script itself (§6.5). The regenerated files are
line-identical to the first pass apart from the `generated:` stamp and the
three inserted caveat lines — i.e. every measurement in this report has been
produced twice, on two different runs, with identical output.

Run cost, for the record (regenerated pass): 2B 4:22.9 wall / 24.8 GiB peak
RSS; 0.8B 2:11.4 / 12.1 GiB (both concurrent on darthplagueis, 32 cores,
~100 GiB free). First pass: 4:54.8 / 24.8 GiB and 2:42.8 / 12.1 GiB.

### 6.2 Section 1 — direct constant containers (B -> C)

| family | container | 0.8B (B) | 2B (C) | verdict |
|---|---|---|---|---|
| `ln1`/`ln2` | int16 Q1.14 | 1.4688 (73.4%), 0/49152 | **1.2031 (60.2%)**, 0/98304 | PASS -> PASS, more margin |
| `model.norm` | int16 Q1.14 | 5.3125 (265.6%), 976/1024 | **5.375 (268.8%)**, 1890/2048 | ATTENTION -> ATTENTION (auditor format is stale, see §6.3) |
| `q_norm`/`k_norm` | int16 Q1.14 | 1.6328 (81.6%), 0/3072 | **1.5938 (79.7%)**, 0/3072 | PASS -> PASS |
| `linear_attn.norm` | int16 Q1.14 | 1.1943 (59.7%), 0/2304 | **1.2373 (61.9%)**, 0/2304 | PASS -> PASS |
| `conv1d` weights | int16 Q2.13 (CW_F=13) | 1.8203 (45.5%), 0/442368 | **1.5625 (39.1%)**, 0/442368 | PASS -> PASS, **more** margin |
| `dt_bias` | int16 Q3.12 | rail-pinned by the clamp | rail-pinned by the clamp | see §6.5 — the row is blind |
| `A = exp(A_log)` | uint18 Q3.15 | rail-pinned by the clamp | rail-pinned by the clamp | see §6.5 — the row is blind |

Geometry note that explains most of this table: the 2B model widens only
`hidden_size` (1024 -> 2048) and `intermediate_size` (3584 -> 6144). The
DeltaNet block geometry is IDENTICAL (18 DN layers x 16 heads = 288 gate
heads; `in_qkv` 6144 rows, `in_z` 2048 rows, `out` 2048 columns, 442368
conv taps, S state unchanged), and so are the attention head count and the
vocab. Every per-head / per-tap
container therefore faces the same NUMBER of values at 2B; only the
projection matrices grow.

**No container that passed at 0.8B saturates at 2B.** The scratch int16
rail, the `Av` uint18 Q3.15 port and the conv `CW_F` rail all hold, and most
gain margin. The one row that loses a little is `linear_attn.norm`
(59.72% -> 61.87% of the Q1.14 rail, still 0 of 2304 out of range); at the
production Q3.12 fold `model.norm` likewise tightens slightly (78.9% ->
79.7%, §6.3).

### 6.3 `conv_w` headroom — the Q4 question, settled

Task 4 left this open: "max\|conv_w\| 1.82 vs the 4.00 rail at 0.8B; 2B
unverified", because the PPL harness's `cw13` class hard-errors on an int16
clip while production `quant_deltanet` stores `round(conv_w * 2^13)`
**unclipped** and lets `gen_layer_script.Mach.W` assert.

**Answer: 2B has MORE headroom than 0.8B.** max\|conv_w\| = **1.5625** of
the ±4.0 rail (39.06%, 0 of 442368 taps out of range; `q`max = 12800 of
32767). The `Mach.W` assert cannot fire on 2B conv weights, and the
harness's stricter `cw13` class is clip-free at 2B as well. 2.56x margin.

Related stale-format note, same section: `model.norm` is flagged ATTENTION
in section 1 because the auditor quantizes it at Q1.14 like `ln1`/`ln2`.
The real-model emitter does not: `gen_model_script.py:401-406` folds it to
`(1+w)` at **Q3.12** and asserts. Measured (`ln_f_fold_probe.txt`):

| model | max \|1+w\| | prod `round((1+w)*2^12)` | over int16 |
|---|---|---|---|
| 0.8B | 6.3125 | 25856 / 32767 (78.9%) | 0 / 1024 |
| 2B | **6.375** | **26112 / 32767 (79.7%)** | **0 / 2048** |

So the ln_f ATTENTION does not transfer to a production blocker at either
size — but 2B sits at 79.7% of the rail in the format production actually
uses, i.e. 1.25x margin, and that margin is a *weight* fact that any future
checkpoint can spend.

### 6.4 Section 2 — W4A8 of the matvec weights (B -> C)

| quantity | 0.8B (B) | 2B (C) | reading |
|---|---|---|---|
| `sh` | 5 (K=1024), 6 (K=2048), 7 (K=3584) | **6** (K=2048), **8** (K=6144) | mechanical: `sh` tracks K |
| group-scale underflow `m==1` | 112 / 5,874,176 (0.0019%) | **224 / 14,697,472 (0.0015%)** | the SAME 14 dead rows of `L0.dn.in_qkv` (8 groups/row -> 16), 14336 -> 28672 weights annihilated |
| INT4 clip | 6,912,284 / 751,894,528 (0.919%) | 17,220,385 / 1,881,276,416 (**0.915%**) | unchanged rate; this column is the MSE rule DELIBERATELY clipping outliers, and is absent from report A only because A used the max rule |
| worst matrix rel err | 14.00% (`L19.attn.v_proj`) | **17.28%** (`L19.attn.v_proj`) | **regression** |
| matrices over the 15% bound | **0 / 187** | **15 / 187** | **regression** |
| `lm_head` rel err | 10.74% | **11.26%** | slightly worse |
| y32 headroom wasted (worst) | 5.3 b (`L23.attn.v_proj`) | **5.9 b** (`L23.mlp.down`) | precision only |

"The same 14 dead rows" is measured, not inferred (`deadrow_probe.txt`):
both checkpoints underflow on row indices
`397, 423, 438, 453, 470, 476, 479, 2445, 2471, 2486, 2501, 2518, 2524, 2527`
of `L0.dn.in_qkv`, every one of them entirely `1.175e-37` (= FLT_MIN) —
a structural artifact of the Qwen3.5 DeltaNet input projection that
survived the scale-up unchanged, not a quantizer failure.

The 15%-bound regression is the one substantive section-2 finding. The
auditor prints at most 12 names; `over15_probe.txt` re-measures every small
projection with the production quantizer and reproduces the audit's counts
exactly, so the complete list at 2B is:

`L19.attn.v_proj` 17.28%, `L23.attn.k_proj` 16.42%, `L4.dn.in_b` 16.12%,
`L23.attn.v_proj` 15.79%, `L17.dn.in_b` 15.76%, `L21.dn.in_b` 15.70%,
`L2.dn.in_b` 15.65%, `L21.dn.in_a` 15.61%, `L20.dn.in_b` 15.59%,
`L5.dn.in_b` 15.59%, `L22.dn.in_a` 15.50%, `L18.dn.in_b` 15.45%,
`L22.dn.in_b` 15.35%, `L6.dn.in_b` 15.34%, `L20.dn.in_a` 15.16%.

Twelve of the fifteen are the 16x2048 DeltaNet gate projections
(`dn.in_a` -> `a`, `dn.in_b` -> `beta`): they doubled in K without gaining a
row, so each of their 16 rows now spends twice as many INT4 nibbles under
one shared exponent. At 0.8B the same family topped out at 12.43%. This is
a weight-quantization fact, consistent with Q5's "weight damage >= datapath
damage in every cell", and it lands on the two matrices that drive the gate
chain of §6.5. No assert fires: the 15% bound only exists inside
`w4a8_ref._selftest`.

### 6.5 Section 3 — the gate ports, and why sections 1/3 above are blind

Since `82781e5`, `quant_deltanet` SATURATES `dt_bias` and `A` into their
ports before the auditor sees them, so section 1 reports "max abs value 8,
100.00% of the container, 0/288 out of range" and section 3 prints the
self-contradicting line *"PASS `A` — max 10.4202 < 8.0"* (its "max used"
column is computed from the float weights, its verdict from the clamped
integers). **Read sections 1 and 3 of this report only together with the
table below.** `quant_deltanet` still records the truth in `qd["gate_sat"]`,
which `audit_ranges.py` never reads — a one-call fix for a later pass, NOT
made here (this task reports, it does not change what ships). What this
task DID add is the caveat itself: `audit_ranges.GATE_CLAMP_NOTE` is now
emitted in the header and beside both sets of gate rows, so every report the
script writes carries the warning even when this hand-appended section does
not travel with it.

`gate_port_probe.py` re-runs the section-3 chain on the PRE-clamp values
(and reproduces report A's numbers exactly at 0.8B, which is what validates
it):

| gate fact | 0.8B | 2B |
|---|---|---|
| max `A = exp(A_log)` (port [0, 8.0)) | 10.5843 | **10.4202** |
| `A` over the uint18 Q3.15 port | 1 / 288 (`L1h15`) | **1 / 288** (`L1h15`) |
| max \|`dt_bias`\| (port ±8.0) | 13.0625 | **12.3125** |
| `dt_bias` over int16 Q3.12 | 2 / 288 | **5 / 288** |
| heads whose decay the production clamp CHANGES | 2 / 288 | **5 / 288** |
| heads whose decay the pre-clamp 18-bit/int16 WRAP changed | 3 / 288 | 6 / 288 |
| largest ABSOLUTE decay change from the clamp | `L1h15` 0.96198 -> 0.97113 (+0.0092) | **`L0h13` 0.24435 -> 0.33292 (+0.0886)** |
| largest RELATIVE decay change from the clamp | `L0h3` 0.00864 -> 0.01068 (+24%) | **`L0h3` 0.01047 -> 0.02151 (+105%)** |

More 2B heads want a bigger `dt_bias` than the port holds (2 -> 5), and the
worst production distortion is larger in absolute terms: `L0h13`'s decay
moves +0.089 (+36% relative), i.e. that head keeps a third of its state per
step where the float model keeps a quarter; the largest RELATIVE distortion
doubles a head's retention (`L0h3` 0.0105 -> 0.0215). The saturating clamp is still
far better than the pre-clamp wrap (which sent `L0h3` from 0.0086 to
0.9997), and it is bounded and deterministic — but at 2B it is no longer a
2-head curiosity.

Everything else in section 3 is structural and unchanged: the softplus ROM
domain is exact at both sizes (max `a+dt` at the `a` rail is 21.0625 at
0.8B and 20.3125 at 2B, both inside the ±32 adder and both served by the
exact linear branch above +16), `beta`'s sigmoid ROM saturates by
construction, and exactly
1 of 288 heads sits at the no-decay rail at `a = 0` in both models.

### 6.6 Section 4 — the residual seed, and the res_scale ruling

Section 4 above is measured at `quant_layer`'s default `res_scale = 1`.
Production is not: `gen_model_script.py:421` seeds the residual with
`clip16(round(emb * S * 2^RS_F))` and `:425` asserts zero clipped values.
Q5 ruled **S = 4** the 2B fixed-point default (S = 8, the 0.8B production
value, rails the 2B int16 residual: 13-22 clips). `res_scale_seed_probe.txt`:

| quantity | 0.8B @ S=8 (prod) | 2B @ S=4 (Q5 ruling) | 2B @ S=1 (section 4 above) |
|---|---|---|---|
| seed peak / 32767 | 472 (1.440%) | **202 (0.616%)** | 50 (0.153%) |
| values clipped (`:425` asserts 0) | **0** / 254,279,680 | **0** / 508,559,360 | 0 / 508,559,360 |
| rel RMS error of the seed | 0.750% | **1.893%** | 7.518% |

The 2B embedding is intrinsically *smaller* than the 0.8B one (max 0.1973
vs 0.2305, RMS 0.01501 vs 0.01970), so at equal S the 2B seed is coarser:
at the ruled S = 4 the seed carries 1.89% relative RMS error against the
0.8B production point's 0.75%. **Nothing clips at any S up to 16** at
either size, so the `:425` assert is not the binding constraint — the
residual PEAK downstream is (Q5's measurement), which is why S dropped
rather than rose. Every other number in section 4 is scale-invariant
(`rmsnorm_fx` normalizes), so the layer-0 probe — max 3145 LSB (12.285 in
Q7.8), RMS 288.9 LSB, **0 values at the int16 rail** — holds at any S.

### 6.7 For the study doc's V1/V2 risk column

**No NEW hard saturation appears at 2B.** Ranked by what the numbers
actually support:

1. **W4 error above the project's own 15% bound: 0/187 -> 15/187**, worst
   17.28%. Twelve are the 16x2048 DeltaNet gate projections. Weight-side,
   no assert, consistent with Q5's decomposition. (RISK: fidelity)
2. **Gate-port overflow doubles-plus: `dt_bias` 2 -> 5 of 288 heads**, and
   the production clamp now changes 5 head decays, worst 0.244 -> 0.333.
   Bounded and deterministic, but it silently changes the model. (RISK:
   fidelity, DeltaNet-specific)
3. **The auditor is blind to (2)**: sections 1 and 3 report PASS / "0 of 288"
   because `quant_deltanet` clamps first, and section 3 prints a literally
   false justification ("max 10.4202 < 8.0"). The script now SAYS so —
   `GATE_CLAMP_NOTE` in the header and beside both gate tables — but it
   still does not measure it: any range claim about `A` / `dt_bias` must
   come from `qd["gate_sat"]` or `gate_port_probe.py`. (RISK:
   process/evidence, not silicon)
4. **`model.norm` needs the production Q3.12 fold** (79.7% of the rail at
   2B, vs 78.9% at 0.8B) — section 1's Q1.14 ATTENTION is the auditor's
   format, not the emitter's. (RISK: none today, 1.25x margin)
5. **Residual seed resolution: 5.73% -> 7.52% at S=1, 1.89% at the ruled
   S=4.** No clipping at any S <= 16. (RISK: fidelity, already priced into
   the S=4 ruling)
6. **y32 headroom wasted grows 5.3 -> 5.9 bits** (`L23.mlp.down`, K=6144).
   Precision only; the RTL still matches the reference bit-for-bit. (RISK:
   precision)

Improved at 2B, for the record: conv `CW_F` occupancy (45.5% -> 39.1% of
the rail), `ln1`/`ln2` occupancy (73.4% -> 60.2%), max `A` (10.58 -> 10.42),
max \|`dt_bias`\| (13.06 -> 12.31), and the W4 group-underflow RATE
(0.0019% -> 0.0015%, same 14 dead rows).
