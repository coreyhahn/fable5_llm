# NVFP4 on the shipped Qwen3.5-9B: the simulation study (Task NV1, Deliverable 4)

**Status: this is the study deliverable. It decides nothing.** It gathers
what rungs 0–2 measured into one decision surface for the **shipped 9B**
design. §7 lists the options and does not pick one. §8 has a blank for the
user's decision.

**It covers the 9B only.** On 2026-09-23, after the 2B table, the user ruled:
"i only care about 9B from this point forward." So §1's decision table is the
9B. The 2B ranking (rung 1) was a screen. Appendix A keeps it in compact form,
and §3 states in full the three places where the 9B contradicts it.

**Everything here is a Python simulation on snoke.** No RTL was touched, no
board action was taken, and no Vivado run was made. Every number in this
document was either produced by a run through the provenance wrapper
`evidence/qwen_next/nvfp4/nvfp4_run.sh` or read from a committed source.

---

## 0. Reading rule, setup, and the format

### 0.0 How to read every number (stated before the numbers)

This document uses the campaign's reading rule, taken from
`evidence/qwen9b/g6/RD9_GATE.md` §0 in the form `docs/QWEN35_2BOARD_FEASIBILITY.md`
states it (`docs/QWEN35_2BOARD_FEASIBILITY.md:56-59`):

| label | means here |
|---|---|
| **T** | **transcribed** from a named run's json field or log line, where that log's `=== rc  :` and `=== end :` lines both exist. Every PPL figure is **T**: it is the `"ppl"` field of the run's json, cited by line. |
| **D** | **derived** by a committed script that **asserts** its inputs before it prints anything: `evidence/qwen_next/nvfp4/rung2_table.py` for the 9B (log `evidence/qwen_next/nvfp4/n63_rung2_table.log`) and `evidence/qwen_next/nvfp4/rung1_table.py` for the 2B (log `evidence/qwen_next/nvfp4/n36_rung1_table.log`). Every Δ, %, byte count, ms figure, tok/s figure and bit width is D, and each cites the log line that printed it. None was computed by hand or on darthplagueis. |
| **S** | **stated** by a cited source: an RTL comment, a timing report, the BN census. |
| **E** | **extrapolated past every measurement, or assumed.** Used only where a sentence says so. |

**A label change from rung 1, stated so nobody misreads it.**
`evidence/qwen_next/nvfp4/NVFP4_RUNG1.md` used **E** to mean "measured by a run"
(`evidence/qwen_next/nvfp4/NVFP4_RUNG1.md:13-15`). This document follows the
campaign rule above, so the same numbers are **T** here, and **E** is kept for
extrapolation.

**Citations.** A cite of the form path:line points at the json field, the log
line, or the RTL line. `evidence/qwen_next/spec_cites.py` checks every cite
mechanically on the committed tree (§8).

### 0.1 Setup (every 9B row)

- **Model:** Qwen3.5-9B checkpoint (header sha256 `2721100f…`).
- **Corpus:** `ref/ppl_corpus_eval.txt`, pinned by `--expect-corpus-sha256 6bf4f867…`.
- **Eval settings:** window 512, batch 4, **24,528 scored positions**.
- **Host:** snoke, CPU, float32 model, shipped venv `/home/cah/.venv`, 12 threads.
- `evidence/qwen_next/nvfp4/rung2_table.py` **asserts** these fields are identical across every row
  before it prints anything (**T**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:5`).
- The launcher is `evidence/qwen_next/nvfp4/rung2_launch.sh`. Its queue log is
  `evidence/qwen_next/nvfp4/n48_rung2_queue.log`.
- The P40 was **not used for any row** (ruling C13, §8).

**The 9B bf16 anchor is new.** The shipped campaign had no 9B perplexity
anchor. It declined "the perplexity point (≈ 7 h)" on 2026-09-09
(`NEXT_SESSION.md:344`). The anchor, n46, took **14.7 min** (177 s build +
706 s eval, **T**, `evidence/qwen_next/nvfp4/n46_ppl_9b_bf16_cpu.json:161-162`,
`evidence/qwen_next/nvfp4/n63_rung2_table.log:85`). Its PPL is **8.218339**
(**T**, `evidence/qwen_next/nvfp4/n46_ppl_9b_bf16_cpu.json:155`). The brief's
"≈ 7 h" figure was 28.5× the measured wall (**D**,
`evidence/qwen_next/nvfp4/n63_rung2_table.log:85`).

**The shipped point is `all:w4g128 --act a8`**: W4 g128 weights through the
production quantizer (`LF.quant_linear`, MSE scale search,
`ref/perplexity_eval.py:304-335`) **plus** the A8 activation rule. Its gap to
bf16 is **+1.341880 PPL** (**D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:12`).
The column **"% of the shipped gap left"** is ΔPPL divided by that +1.341880.
The shipped row itself is 100 % and bf16 is 0 %.

**What `all:` covers.** `all:` resolves to the seven W4 matvec classes: qkv,
o_proj, gate_up, down, dn_in, dn_out, lm_head. The embedding and the DeltaNet
conv stay float in every row, exactly as in the anchor.

**Hooked sites (ruling C4).** The `--act` hooks fake-quantize the input of
**249 matvecs on 129 input sites**. By class (matvecs / sites): dn_in 96/24,
dn_out 24/24, down 32/32, gate_up 64/32, lm_head 1/1, o_proj 8/8, qkv 24/8
(**T**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:97`).

### 0.2 The format, exactly as coded (`ref/nvfp4.py`)

The rounding rules below are the code's, and the `--selftest` asserts each one
(clean-HEAD pass `evidence/qwen_next/nvfp4/n40_nvfp4_selftest_HEAD.log`).

**Element: E2M1**
- Magnitudes {0, 0.5, 1, 1.5, 2, 3, 4, 6}, sign separate (`ref/nvfp4.py:68`).
- Rounds to the nearest grid point. **A tie goes to the EVEN code**, the
  neighbour whose mantissa bit is 0: 0.25→0, 0.75→1, 1.25→1, 1.75→2, 2.5→2,
  3.5→4, 5→4.
- |v| > 6 saturates to 6.
- **One code table and one tie routine serve both quantize and dequantize**, so
  the tie rule cannot drift between the two (`ref/nvfp4.py:6-12`,
  `ref/nvfp4.py:90-108`).
- Codes are carried as q2 = 2·value, an integer in [−12, 12].

**Stage 1: one UE4M3 scale per block of 16 along K**
- Format: unsigned E4M3, bias 7, 3 mantissa bits, max 448.
- 127 finite codes. 0x7F (NaN) is never produced.
- **Subnormals are kept** down to 2^-9. A ratio at or below 2^-10 rounds to 0
  (exactly 2^-10 is a tie that goes to the even code, 0), and that block
  dequantizes to zeros.
- Rounding: RNE, ties to the even mantissa, saturating at 448.
- The encoded value is amax(block)/6/s_t (`ref/nvfp4.py:13-20`,
  `ref/nvfp4.py:111-124`).

**Stage 2: one FP32 tensor scale**
- s_t = fp32(amax/(6·448)) (`ref/nvfp4.py:21-26`, `ref/nvfp4.py:127-130`).
- **Weights:** one s_t per matrix, taken from the rotated matrix under RHT.
- **Activations:** one s_t per token (`:dyn`), or per input site from a
  calibration pass (`:static`, ruling C3).
- **At 9B only `:dyn` was run.** Static scales were measured on the 2B only (§4).

**Effective block scale**
- S = ue4m3(code)·s_t, exact in float64. The element is e2m1_rne(x/S).
- The one inexact step is the final cast to float32, at most 2^-24 relative
  (`ref/nvfp4.py:27-30`).

**RHT (ruling C8): the form as corrected**
- **M = H16·diag(D)/4**: the signs flip FIRST, then the 16-point Sylvester
  Hadamard mixes (`ref/nvfp4.py:31-43`, `ref/nvfp4.py:201-203`).
- **D is on the INPUT side.** There is one 16-entry ±1 vector per **input site**,
  derived from (seed, crc32(site)). Every 16-block of every matrix that reads
  the site shares it, so q/k/v share one vector, gate/up share one, and the four
  DeltaNet in_proj share one.
- There are **129 sites at 9B** (**T**,
  `evidence/qwen_next/nvfp4/n52_ppl_9b_nvfp4h_a8_seed0_cpu.json:464`).
- **Weights are rotated offline.** The harness injects Q(W·Mᵀ)·M.
- **The `--act` hook computes Mᵀ·Q(M·x)**, so the float model computes
  exactly Q(W')·Q(x').
- **Why the brief's literal form was replaced.** The brief wrote the rotation
  as (D·H16/4)·x. In that order D only flips the signs of the outputs. Every
  quantizer here is sign-symmetric, so D cancels and every seed gives the same
  model. Measured: seed 1 reproduced seed 0's nll_sum bit for bit
  (`evidence/qwen_next/nvfp4/n36_rung1_table.log:6`).

**Row padding rule (the DDR layout priced in §1 Panel B)**
- Each row is ceil(K/128) 64-byte weight beats (128 E2M1 nibbles each), plus
  ceil((K/16)/64) scale beats (64 UE4M3 bytes each). The row is padded to whole
  beats, and each matrix carries one 32-bit s_t (`ref/nvfp4.py:44-48`,
  `ref/nvfp4.py:272-291`). This is the shipped `row_stride` law carried over
  (`ref/w4a8_ref.py:111`).
- **Every 9B K is 4096 or 12288** (**D**,
  `evidence/qwen_next/nvfp4/n63_rung2_table.log:100`). Both are multiples of
  1024, so every 9B row packs at exactly **4.5 b/w**, against the shipped
  **4.125** (**D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:32-34`).

**A8 (ruling C5): the shipped rule as found**
- Scale: per matvec input vector (= per token), a power-of-two scale 2^e, where
  e is the smallest integer with round_half_away(amax/2^e) ≤ 127.
- Quantize: x8 = clip(round_half_away(x/2^e), ±127).
- It is dynamic and uncalibrated. It is `fixedpoint.dyn_quant_i8`
  (`ref/fixedpoint.py:24-33`) as `layer_fixed.matvec_fx` feeds it
  (`ref/layer_fixed.py:1201-1221`), and vec_alu op DYNQ8 in RTL
  (`rtl/vec_alu.sv:13-14`).
- **Modelled in float:** there is no upstream int16 grid and no e ≥ 0 floor
  (`ref/nvfp4.py:51-52`).
- **On an RHT site it quantizes the ROTATED input.** The hardware would have to
  rotate first.

**Exact-integer property**
- Every element is (q2/2) with q2 an integer in [−12, 12].
- Every UE4M3 value is μ·2^k, with μ an integer in [1, 15].
- So a block's contribution to a dot product is an integer block sum multiplied
  by a 4-bit mantissa and shifted by an exponent. **A bit-exact fixed-point
  reference is a block-floating-point accumulation with shifts, with no
  floating point anywhere** except the per-tensor s_t, which folds into the
  output requant constant (`ref/nvfp4.py:54-57`).
- Selftest section E asserts that decomposition.
- **That reference was not built in NV1.** §5 prices it.

---

## 1. THE DECISION TABLE (Qwen3.5-9B)

The two panels use the same row keys. **Every quality delta sits beside its
modelled 9B throughput delta**, because the user asked about throughput first.

**The throughput column** (**D**) is rung 1's cost model applied to each 9B
row's weight bytes:

> modelled ms/token = 137.121 + 54.408 × (r − 1)

- 137.121 ms/token is the board token (**S**, `evidence/qwen9b/bn/BN_CENSUS.md:19`).
- 54.408 ms/token is the census's weight-streaming term (**S**,
  `evidence/qwen9b/bn/BN_CENSUS.md:41`), measured inside the 131.138 ms
  testbench token (**S**, `evidence/qwen9b/bn/BN_CENSUS.md:18`).
- r is the busiest-channel byte ratio against the shipped pack.

**What the model leaves out.** Activation formats move no DDR bytes, so this
model counts them as free. What they do cost is hardware, and §5 prices that.
The engine's timing closure is not modelled either.

### Panel A — quality, with the modelled 9B throughput beside it

| row | run | weights | activations | PPL (T) | ΔPPL vs bf16 (D) | Δ % (D) | % of shipped gap left (D) | 9B tok/s (D) | Δ tok/s vs shipped (D) | cite |
|---|---|---|---|---|---|---|---|---|---|---|
| **bf16 anchor** | n46 | bf16 | float | **8.218339** | — | — | 0.00 % | n/a | n/a | `evidence/qwen_next/nvfp4/n46_ppl_9b_bf16_cpu.json:155`, `evidence/qwen_next/nvfp4/n63_rung2_table.log:11` |
| **SHIPPED** W4 g128 + A8 | n47 | w4g128 | a8 | **9.560220** | +1.341880 | +16.33 % | 100.00 % | **7.293** | +0.000 (0.00 %) | `evidence/qwen_next/nvfp4/n47_ppl_9b_w4g128_a8_cpu.json:331`, `evidence/qwen_next/nvfp4/n63_rung2_table.log:12` |
| W4 g64 GPTQ + A8 | n54 | w4g64gptq | a8 | 8.880120 | +0.661781 | +8.05 % | 49.32 % | 7.206 | −0.087 (−1.19 %)¹ | `evidence/qwen_next/nvfp4/n54_ppl_9b_w4g64gptq_a8_cpu.json:353`, `evidence/qwen_next/nvfp4/n63_rung2_table.log:13` |
| NVFP4 + A8 | n53 | nvfp4 | a8 | 8.954712 | +0.736373 | +8.96 % | 54.88 % | 7.039 | −0.254 (−3.48 %) | `evidence/qwen_next/nvfp4/n53_ppl_9b_nvfp4_a8_cpu.json:331`, `evidence/qwen_next/nvfp4/n63_rung2_table.log:14` |
| **NVFP4 + RHT + A8**, seed 0 | n52 | nvfp4h | a8 (rotated) | **8.592140** | +0.373800 | +4.55 % | 27.86 % | 7.039 | −0.254 (−3.48 %) | `evidence/qwen_next/nvfp4/n52_ppl_9b_nvfp4h_a8_seed0_cpu.json:461`, `evidence/qwen_next/nvfp4/n63_rung2_table.log:15` |
| **NVFP4 + RHT + A8**, seed 1 | n59 | nvfp4h | a8 (rotated) | **8.572686** | +0.354347 | +4.31 % | 26.41 % | 7.039 | −0.254 (−3.48 %) | `evidence/qwen_next/nvfp4/n59_ppl_9b_nvfp4h_a8_seed1_cpu.json:461`, `evidence/qwen_next/nvfp4/n63_rung2_table.log:16` |
| **full NVFP4**, dyn | n51 | nvfp4 | nvfp4:dyn | **8.696983** | +0.478644 | +5.82 % | 35.67 % | 7.039 | −0.254 (−3.48 %) | `evidence/qwen_next/nvfp4/n51_ppl_9b_nvfp4_actdyn_cpu.json:331`, `evidence/qwen_next/nvfp4/n63_rung2_table.log:17` |
| *weights only:* NVFP4 | n55 | nvfp4 | float | 8.409468 | +0.191128 | +2.33 % | 14.24 % | (7.039)² | (−0.254)² | `evidence/qwen_next/nvfp4/n55_ppl_9b_nvfp4_cpu.json:163`, `evidence/qwen_next/nvfp4/n63_rung2_table.log:18` |
| *weights only:* NVFP4 + RHT, seed 0 | n56 | nvfp4h | float | 8.539954 | +0.321615 | +3.91 % | 23.97 % | (7.039)² | (−0.254)² | `evidence/qwen_next/nvfp4/n56_ppl_9b_nvfp4h_seed0_cpu.json:163`, `evidence/qwen_next/nvfp4/n63_rung2_table.log:19` |
| *acts only:* A8 | n57 | bf16 | a8 | 8.708991 | +0.490651 | +5.97 % | 36.56 % | n/a | n/a | `evidence/qwen_next/nvfp4/n57_ppl_9b_bf16_a8_cpu.json:323`, `evidence/qwen_next/nvfp4/n63_rung2_table.log:20` |
| *acts only:* NVFP4 dyn | n58 | bf16 | nvfp4:dyn | 8.441624 | +0.223285 | +2.72 % | 16.64 % | n/a | n/a | `evidence/qwen_next/nvfp4/n58_ppl_9b_bf16_actnvfp4dyn_cpu.json:323`, `evidence/qwen_next/nvfp4/n63_rung2_table.log:21` |

¹ The W4 g64 row's hardware class is not "none" on the 9B engine (Panel B
note). Its tok/s is the byte model's figure for a restored g64 mode.
² The weights-only rows are decomposition references, not operating points.
With float activations they cannot run on the engine. The tok/s shown is
their weight bytes' figure alone.

**Ranking of the deployable rows** (**D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:23`):
NVFP4 + RHT + A8 s1 8.572686 < s0 8.592140 < full NVFP4 8.696983 <
W4 g64 GPTQ + A8 8.880120 < NVFP4 + A8 8.954712 < SHIPPED 9.560220.

**The readings that matter.**

**(a) Every NVFP4 row beats the shipped point on quality and loses 3.48 % on
throughput.**
- **Throughput:** the NVFP4 weight format is +9.09 % bytes on every 9B matrix
  (×1.090909 busiest channel). That is **+4.946 ms/token → 142.067 ms,
  7.039 tok/s against 7.293** (**D**,
  `evidence/qwen_next/nvfp4/n63_rung2_table.log:34`). There is no throughput
  gain anywhere in this study: activations live on chip, so a 4-bit activation
  format saves no DDR bytes.
- **Quality:** it buys between 45.12 % (NVFP4 + A8) and 73.59 %
  (NVFP4 + RHT + A8, seed 1) of the shipped gap back (**D**,
  `evidence/qwen_next/nvfp4/n63_rung2_table.log:47-50`).

**(b) The best measured deployable row is NVFP4 weights + RHT + the shipped
A8 rule.**
- **Quality:** 8.592140 / 8.572686 on two seeds, 27.86 % / 26.41 % of the
  shipped gap left.
- **What it needs:** the new NVFP4 weight datapath, plus a 16-point rotation
  ahead of the existing A8 quantizer. It does NOT need an NVFP4 activation
  quantizer.
- **Full NVFP4** (NVIDIA's recipe, no rotation) is 0.104843 PPL behind the
  worse of the two NVFP4 + RHT + A8 seeds (**D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:81`).
- **Full NVFP4 lands at the quality of bf16 + A8:** 8.696983 against 8.708991,
  −0.012007 (**D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:61`).

**(c) W4 g64 GPTQ + A8 is the cheapest row per PPL point in bytes, and not
the best row.** "Cheapest" prices DDR bytes only. Its hardware delta includes
widening a timing-marginal mux (Panel B note).
- **Quality:** 8.880120, 49.32 % of the shipped gap left. That is behind both
  RHT + A8 seeds and full NVFP4, and ahead of NVFP4 + A8 (**T**,
  `evidence/qwen_next/nvfp4/n54_ppl_9b_w4g64gptq_a8_cpu.json:353`; **D**,
  `evidence/qwen_next/nvfp4/n63_rung2_table.log:13`).
- **Cost:** +1.649 ms/token, 7.206 tok/s (−1.19 %). It has the lowest
  ms-per-PPL-point of any row: 2.424, against 5.009–8.169 for the NVFP4 rows
  (**D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:46-50`).
- **At 2B this was the best deployable row. At 9B it is third of four
  configurations** (fourth of five rows, if the two RHT seeds count
  separately)
  (**D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:23`,
  `evidence/qwen_next/nvfp4/n63_rung2_table.log:76`). That is a fourth
  2B-to-9B change, in ranking rather than sign (§3.1).

### Panel B — cost

| row | packed b/w (matvec) | bytes/token 9B | × shipped bytes | busiest-channel ratio | Δ ms/token (D) | ms/token (D) | tok/s (D) | hardware delta class | cite |
|---|---|---|---|---|---|---|---|---|---|
| bf16 anchor | 16.0000 | 15,871,246,336 | 3.8788 | n/a | n/a | n/a | n/a | float reference | `evidence/qwen_next/nvfp4/n63_rung2_table.log:31` |
| **SHIPPED** W4 g128 + A8 | 4.1250 | 4,091,805,696 | 1.0000 | 1.000000 | +0.000 | 137.121 | **7.293** | **none**: the shipped engine as built | `evidence/qwen_next/nvfp4/n63_rung2_table.log:32` |
| W4 g64 GPTQ + A8 | 4.2500 | 4,215,799,808 | 1.0303 | 1.030303 | +1.649 | 138.770 | 7.206 | **the deleted g64 row format, restored**: scale-beat field, two-scale retire, and the scale bank NSCAL 96 → 192, which widens the timing-marginal NSCAL:1 `scales_q` mux (below) | `evidence/qwen_next/nvfp4/n63_rung2_table.log:33` |
| NVFP4 + A8 | 4.5000 | 4,463,789,028 | 1.0909 | 1.090909 | +4.946 | 142.067 | 7.039 | **new weight datapath** | `evidence/qwen_next/nvfp4/n63_rung2_table.log:34` |
| NVFP4 + RHT + A8 (either seed) | 4.5000 | 4,463,789,028 | 1.0909 | 1.090909 | +4.946 | 142.067 | 7.039 | **new weight datapath + activation rotation** (butterfly ahead of A8) | `evidence/qwen_next/nvfp4/n63_rung2_table.log:35-36` |
| full NVFP4, dyn | 4.5000 | 4,463,789,028 | 1.0909 | 1.090909 | +4.946 | 142.067 | 7.039 | **new weight + new activation datapath** (no rotation) | `evidence/qwen_next/nvfp4/n63_rung2_table.log:37` |

**Where the bytes come from.**
- The bytes are each row's own json field `bytes_per_token_matvec`.
- `evidence/qwen_next/nvfp4/rung2_table.py` asserts that the shipped row's value equals
  `ref/scripts/bytes_per_token.py`'s 9B all:w4g128 figure, 4,091,805,696, and
  that every NVFP4 row's value equals the rung-1 cost model's 4,463,789,028
  (**D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:26`).
- Busiest channel: 1,025,925,120 B shipped against 1,119,191,040 B NVFP4 (**D**,
  `evidence/qwen_next/nvfp4/n63_rung2_table.log:27`,
  `evidence/qwen_next/nvfp4/n63_rung2_table.log:29`).

**The GPTQ g64 row's hardware class is NOT "none" at 9B. This corrects a rung-1
sentence.**
- `evidence/qwen_next/nvfp4/NVFP4_RUNG1.md:165-167` said the W4 g64 GPTQ row
  "needs no new datapath". That is true of the 2B engine
  (`docs/QWEN2B_QUANT_STUDY.md`). It is false for the engine that ships the 9B.
- G3.3 deleted the g64 row format from `rtl/matvec_engine.sv`. At the 9B's
  NG = 96, its scale-beat count overflows the 2-bit `n_scale_beats` field, so
  g64 is "UNREPRESENTABLE" on the shipped 9B engine (**S**,
  `rtl/matvec_engine.sv:25-28`, `rtl/matvec_engine.sv:259`).
- The GPTQ g64 row therefore needs that mode restored, in three parts:
  - a wider scale-beat count (`rtl/matvec_engine.sv:259`);
  - the two-scales-per-beat retire G3.3 removed (`rtl/matvec_engine.sv:536-539`);
  - **a doubled scale bank.** At NG = 96 a g64 row carries 2·NG = 192 scales
    in ceil(2·NG/32) scale beats (**S**, `rtl/matvec_engine.sv:25-26`). G3.3
    deliberately shrank the buffer to NSCAL = 32·ceil(MAX_NG/32) = 96, "not
    2*MAX_NG, which was mode 1's 2-scales-per-group cadence" (**S**,
    `rtl/matvec_engine.sv:179-182`). Restoring g64 takes NSCAL from 96 to
    192.
- **That buffer feeds the NSCAL:1 `scales_q` mux, which owns a +0.001 ui_clk
  cone** (**S**, `rtl/matvec_engine.sv:117-118`). So the g64 delta includes
  doubling the input count of a timing-marginal mux.
- **This bears on reading (c).** The row's 2.424 ms per PPL point prices its
  bytes only. It does not price that timing risk.
- The delta is smaller than an NVFP4 datapath, but it is not zero.

---

## 2. What a PPL point costs in bytes: the frontier, with the shipped row

Every row below is compared with the shipped point. "Recovered" means shipped
PPL minus row PPL.

| row | PPL (T) | recovered PPL (D) | % of the shipped gap closed (D) | extra MB/token (D) | extra ms/token (D) | ms per PPL point recovered (D) | % tok/s lost per 10 points of gap closed (D) | cite |
|---|---|---|---|---|---|---|---|---|
| **SHIPPED** | 9.560220 | 0 | 0.00 % | 0 | 0 | — | — | `evidence/qwen_next/nvfp4/n63_rung2_table.log:45` |
| W4 g64 GPTQ + A8 | 8.880120 | +0.680100 | 50.68 % | +123.994 | +1.649 | 2.424 | 0.234 | `evidence/qwen_next/nvfp4/n63_rung2_table.log:46` |
| NVFP4 + A8 | 8.954712 | +0.605507 | 45.12 % | +371.983 | +4.946 | 8.169 | 0.772 | `evidence/qwen_next/nvfp4/n63_rung2_table.log:47` |
| NVFP4 + RHT + A8, s0 | 8.592140 | +0.968080 | 72.14 % | +371.983 | +4.946 | 5.109 | 0.483 | `evidence/qwen_next/nvfp4/n63_rung2_table.log:48` |
| NVFP4 + RHT + A8, s1 | 8.572686 | +0.987533 | 73.59 % | +371.983 | +4.946 | 5.009 | 0.473 | `evidence/qwen_next/nvfp4/n63_rung2_table.log:49` |
| full NVFP4, dyn | 8.696983 | +0.863237 | 64.33 % | +371.983 | +4.946 | 5.730 | 0.541 | `evidence/qwen_next/nvfp4/n63_rung2_table.log:50` |

- **All NVFP4 rows cost the same bytes, so they differ only in quality.**
  Every NVFP4 variant pays the same +371.983 MB/token. Within the NVFP4 family,
  the frontier is decided by quality alone, and the RHT + A8 rows sit on it.
- **Two different price tags.** The bytes column prices only the weight
  stream. The activation side (a rotation for the RHT rows, a whole NVFP4
  activation quantizer for full NVFP4) is a hardware cost, not a byte cost,
  and §5 prices it separately.
- **There is only one point between the shipped row and NVFP4.** W4 g64 GPTQ
  sits at +1.649 ms/token and +123.994 MB/token, 0.333 of NVFP4's +4.946 ms
  (busiest channel ×1.030303 against ×1.090909, **D**,
  `evidence/qwen_next/nvfp4/n63_rung2_table.log:28-29`).
  It closes 50.68 % of the gap at 2.424 ms per PPL point, the cheapest
  byte-cost rate on the chart. Its scale-bank and mux delta is not priced here
  (Panel B note) (**D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:46`). The
  NVFP4 + RHT + A8 rows close more of the gap (72.14 % / 73.59 %) at about
  twice the rate per point (5.109 / 5.009).
- **The bf16 anchor is off this chart.** At 15,871,246,336 B/token it would be
  3.8788× the shipped bytes (**D**,
  `evidence/qwen_next/nvfp4/n63_rung2_table.log:31`). It is the quality
  reference, not an operating point.

---

## 3. The decomposition at 9B: weight damage, activation damage, the RHT

All figures are ΔPPL against bf16. Interaction = combined − weight − activation
(**D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:53-61`).

| pairing | weight damage | activation damage | combined | interaction |
|---|---|---|---|---|
| NVFP4 × A8 | +0.191128 (n55) | +0.490651 (n57) | +0.736373 (n53) | +0.054593 |
| NVFP4 × NVFP4 act, dyn | +0.191128 (n55) | +0.223285 (n58) | +0.478644 (n51) | +0.064231 |
| W4 g128 × A8 (shipped) | not separable³ | +0.490651 (n57) | +1.341880 (n47) | weight + interaction = +0.851229 |
| NVFP4 + RHT × rotated A8 | +0.321615 (n56) | not separable⁴ | +0.373800 (n52, s0) / +0.354347 (n59, s1) | activation + interaction = +0.052186 (s0) |

³ No 9B weight-only W4 g128 row was run, so the shipped row's weight damage
and its interaction with A8 cannot be separated at 9B.
⁴ No bf16 + ROTATED A8 row was run, so this interaction is not separable.

| RHT effect (RHT row − no-RHT row, same activations) | 9B | cite |
|---|---|---|
| weights only (seed 0) | **+0.130486** (the rotation COSTS) | `evidence/qwen_next/nvfp4/n63_rung2_table.log:58` |
| + A8 | **−0.362573** (s0), **−0.382026** (s1), mean −0.372299 | `evidence/qwen_next/nvfp4/n63_rung2_table.log:59` |
| + NVFP4 act, dyn | **not run at 9B** (no nvfp4h + nvfp4h:dyn row) | `evidence/qwen_next/nvfp4/n63_rung2_table.log:60` |

**What the 9B decomposition says.**

- **Weights.** NVFP4 weight damage alone is +0.191128, **14.24 % of the shipped
  gap** (**D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:18`). The shipped
  W4 g128 carries up to +0.851229 of weight damage plus interaction.
- **Activations are the larger half of every NVFP4 combination.** A8 alone
  costs +0.490651 and NVFP4 dyn activations alone cost +0.223285.
- **The damages add almost linearly.** Both interactions are ≤ 0.065.
- **The RHT is paid for on the weight side and repaid on the activation side.**
  - On the weights alone, the rotation makes NVFP4 **worse** by +0.130486.
  - With A8 activations, it makes the row **better** by 0.36–0.38.
  - A plausible mechanism, not measured here (**E**): A8 uses one
    power-of-two scale per token, so a few outlier channels set the step for
    the whole vector. The rotation spreads those outliers across each block of
    16.
  - The net win is 0.36–0.38 PPL against NVFP4 + A8. It is 18.6× the seed
    spread (**D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:82`).

### 3.1 Where the 9B contradicts the 2B screen, stated plainly

The table has four sign flips, which make three findings: the last two rows
marked NO are one finding (#3 below). The rows are printed side by side from
the committed jsons of both models (**D**,
`evidence/qwen_next/nvfp4/n63_rung2_table.log:63-76`).

| quantity | 2B | 9B | agree? | cite |
|---|---|---|---|---|
| NVFP4-dyn activation damage − A8 activation damage (bf16 weights) | **+0.310700** | **−0.267367** | **NO** | `evidence/qwen_next/nvfp4/n63_rung2_table.log:67` |
| RHT effect, weights only | **−0.073082** | **+0.130486** | **NO** | `evidence/qwen_next/nvfp4/n63_rung2_table.log:68` |
| RHT effect, + A8 | −0.534363 | −0.362573 | yes | `evidence/qwen_next/nvfp4/n63_rung2_table.log:69` |
| full NVFP4 − bf16+A8 | **+1.462609** | **−0.012007** | **NO** | `evidence/qwen_next/nvfp4/n63_rung2_table.log:70` |
| full NVFP4 − NVFP4+A8 | **+0.276999** | **−0.257729** | **NO** | `evidence/qwen_next/nvfp4/n63_rung2_table.log:71` |
| NVFP4 weight damage as a fraction of the shipped gap | 0.456340 | 0.142433 | the sign agrees; the size does not (0.456340 at 2B against 0.142433 at 9B) | `evidence/qwen_next/nvfp4/n63_rung2_table.log:72` |

1. **At 9B, NVFP4 dynamic activations cost LESS than A8, the reverse of the
   2B.**
   - On the 2B, block-16 FP4 activations lost more than the shipped per-token
     int8 (+0.807301 against +0.496600).
   - On the 9B, they lose about half as much (+0.223285 against +0.490651).
   - Rung 1's reading (b), "the NVFP4 activation format is the weaker half"
     (`evidence/qwen_next/nvfp4/NVFP4_RUNG1.md:134-137`), **does not hold at
     9B.** A8's damage is nearly the same on both models (+0.496600 on the
     2B, +0.490651 on the 9B, **D**,
     `evidence/qwen_next/nvfp4/n63_rung2_table.log:65`). The flip comes from
     the NVFP4 activation side, whose damage fell from +0.807301 to +0.223285
     (**D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:66`).
2. **At 9B the rotation costs on the weight side and pays only through the A8
   activations.**
   - On the 2B the RHT helped the weights a little (−0.073082).
   - On the 9B it hurts them (+0.130486).
   - The one RHT benefit that survives the change of model is the A8 one.
3. **Full NVFP4 lands at the quality of bf16 + A8.**
   - On the 2B, full NVFP4 was 1.46 PPL behind bf16 + A8 and behind NVFP4 + A8.
   - On the 9B, it is level with bf16 + A8 (−0.012007) and ahead of
     NVFP4 + A8 by 0.257729.
   - So the 2B ranking "every A8 row with improved weights beats full NVFP4"
     (`evidence/qwen_next/nvfp4/NVFP4_RUNG1.md:127-130`) **flips for the plain
     NVFP4 + A8 row at 9B.**
   - It still holds for the RHT + A8 rows (8.572686 / 8.592140 < 8.696983).

**The 2B's relative orders of the common rows differ.**
- 2B: A8 < ADYN < NVH < GPTQ < NV < NVH_A8 < NV_A8 < NV_DYN < SHIP.
- 9B: NV < ADYN < NVH < NVH_A8 < NV_DYN < A8 < GPTQ < NV_A8 < SHIP.
- Source: **D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:74-75`.
- **The 2B was a screen, and at three of its sign-level conclusions it screened
  wrong for the 9B.** Nothing in the 2B table that the 9B did not re-measure
  should be carried to the 9B. That covers the static activation scale and the
  RHT with NVFP4 activations (§6).

---

## 4. Seed and scale-mode sensitivity

**At 9B: two RHT seeds on NVFP4 + RHT + A8.**

| seed | PPL (T) | cite |
|---|---|---|
| 0 (n52) | 8.592140 | `evidence/qwen_next/nvfp4/n52_ppl_9b_nvfp4h_a8_seed0_cpu.json:461`, `evidence/qwen_next/nvfp4/n52_ppl_9b_nvfp4h_a8_seed0_cpu.json:465` |
| 1 (n59) | 8.572686 | `evidence/qwen_next/nvfp4/n59_ppl_9b_nvfp4h_a8_seed1_cpu.json:461`, `evidence/qwen_next/nvfp4/n59_ppl_9b_nvfp4h_a8_seed1_cpu.json:465` |

- **Spread:** mean 8.582413, spread **0.019453 PPL = 1.45 % of the 9B shipped
  gap** (**D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:81`).
- **The worse seed still beats the no-RHT rows.** It is 0.362573 better than
  NVFP4 + A8 and 0.104843 better than full NVFP4 (**D**,
  `evidence/qwen_next/nvfp4/n63_rung2_table.log:81`).
- **The RHT's A8 benefit is 18.6× the spread.** The rotated-weights-only cost
  is 6.7× it (**D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:82`).
- **The 9B is less seed-sensitive than the 2B was.** The 2B's three-seed
  spreads were 6.0× (dynamic) and 3.6× (static) the 9B's, each as a share of
  its own model's shipped gap (**D**,
  `evidence/qwen_next/nvfp4/n63_rung2_table.log:82`). Two seeds are what ran
  at 9B; that a third would leave the ranking unchanged is an assumption (**E**).

**At 2B (rung 1, for contrast only):** three seeds on each full-NVFP4 + RHT row.
- Dynamic activation scale: spread **0.220174 = 8.76 %** of the 2B shipped gap.
- Static activation scale: spread **0.131566 = 5.23 %**.
- Source: **D**, `evidence/qwen_next/nvfp4/n36_rung1_table.log:68`,
  `evidence/qwen_next/nvfp4/n36_rung1_table.log:72`.

**Static vs dynamic activation scale: measured on the 2B only.**
- Static − dynamic was +0.080414 at seed 0 and −0.040309 averaged over three
  seeds (**D**, `evidence/qwen_next/nvfp4/n36_rung1_table.log:62`,
  `evidence/qwen_next/nvfp4/n36_rung1_table.log:73`). That is within the 2B
  seed noise.
- **No static-scale row ran at 9B.** Given §3.1, the 2B result is not evidence
  about the 9B.

---

## 5. What a hardware version needs: priced, not built

Everything in this section is a structural reading of the shipped RTL and
reference (**S**, cited lines) plus arithmetic printed by `evidence/qwen_next/nvfp4/rung2_table.py`
(**D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:99-106`). Nothing was
synthesized. Effort, LUT and timing figures are not claimed, because no tool
produced them.

### 5.1 The engine that would change: `rtl/matvec_engine.sv`

**What the engine does today**, bit-exact to `ref/w4a8_ref.py`:
- acc_g = Σ w4·x8 over a 128-group, then p = Σ_g m_g·acc_g in 48 bits, then
  one final rounding shift (**S**, `rtl/matvec_engine.sv:39-42`).
- **One 128-weight beat is one group.**
- The 128 products are 12-bit (`rtl/matvec_engine.sv:361`).
- A pipelined adder tree reduces them 128 → 64 → 16 → 4 → two 64-lane halves
  (`rtl/matvec_engine.sv:387`,
  `rtl/matvec_engine.sv:403`, `rtl/matvec_engine.sv:421`,
  `rtl/matvec_engine.sv:442`).
- Group sums are banked (`rtl/matvec_engine.sv:456`).
- A **retire walk** reads one group per cycle and multiplies it by its uint16
  scale in two DSP48E2s (`rtl/matvec_engine.sv:649`,
  `rtl/matvec_engine.sv:658`).
- The retire walk sums into the 48-bit accumulator `p_acc`
  (`rtl/matvec_engine.sv:561`, `rtl/matvec_engine.sv:675`).
- It requantizes with a round-half-away shift
  (`rtl/matvec_engine.sv:579-584`, `rtl/matvec_engine.sv:682`).

**The accumulator and the requant are the block NVFP4 changes.**

**Its timing standing**, from `evidence/qwen9b/g5/G5D_TIMING.md`. This is
stated exactly because the task brief calls it "the block that owns the worst
timing endpoints", which was true of the first 9B campaign but not of the
shipped roll:
- `matvec_engine`'s 300 MHz `xline_q0` CE cone **owned the first 9B timing
  campaign's design WNS at −0.130** (**S**,
  `evidence/qwen9b/g5/G5D_TIMING.md:661-662`).
- It is one of the six tracked owner classes (**S**,
  `evidence/qwen9b/g5/G5D_TIMING.md:1045-1050`).
- **On the shipped (closing) roll it passes at +0.138 … +0.402 ns on all four
  channels** (**S**, `evidence/qwen9b/g5/G5D_TIMING.md:1045`).
- The shipped design's WNS of exactly 0.000 is owned by `layer_0`'s
  `ATTN_DSP`, not by the matvec (**S**,
  `evidence/qwen9b/g5/G5D_TIMING.md:1053`).
- Two engine cones are named timing-sensitive in the RTL itself:
  - the x_mem address, the "waived xline_q cone" (**S**,
    `rtl/matvec_engine.sv:241-246`);
  - the NSCAL:1 scale mux, which "owns a +0.001 ui_clk cone" (**S**,
    `rtl/matvec_engine.sv:117-118`).
- **So the engine is a historical owner of the design WNS with a thin current
  margin, and NVFP4 would change exactly the parts of it that were
  timing-critical.** It is not the current owner of the worst endpoint.

### 5.2 The deltas, one block at a time

| # | block | what changes | size of the delta | label / cite |
|---|---|---|---|---|
| 1 | **E2M1 decode** (weight lanes) | Each nibble becomes a signed half-unit magnitude: a 16-entry LUT maps the 4-bit code to q2 ∈ [−12, 12], a **5-bit signed magnitude**, in place of today's sign-extended nibble, where any 4-bit pattern is a legal INT4 (`rtl/matvec_engine.sv:358-361`) | 128 LUT decodes per beat per channel; the product stays **12 b** (1536 = 12 × 128 against 1024 today) | **D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:103-104` |
| 2 | **block-16 UE4M3 scaling inside the tree** | The shipped scale is applied once per 128-group at retire. NVFP4 has **8 blocks per beat**, and 256 (K = 4096) or 768 (K = 12288) block entries per row, against a stream of 36 or 108 beats. **A retire that issues one entry per cycle would make the row 7.11× longer than its stream**, so the block scale has to move INTO the tree. The tree's 16-lane stage (each sum16 entry covers 8 k) is where block-16 boundaries fall: pairs of sum16 entries form a block. Each block then needs one 16 b × 4 b mantissa multiply and one exponent shift (0..14), with 8 of each per beat per channel | block sum **16 b**; × mantissa ≤ 15 → **20 b**; shifted term **34 b**; worst-case row bound at K = 12288 **44 b**, which fits the 48 b `p_acc` | **D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:101-104`; tree `rtl/matvec_engine.sv:403`, `rtl/matvec_engine.sv:421`; `p_acc` `rtl/matvec_engine.sv:561` |
| 3 | **scale beats and the scale bank** | NVFP4 rows carry 4 (K = 4096) or 12 (K = 12288) scale beats of 64 UE4M3 bytes, against 1 or 3 today. The 2-bit `n_scale_beats` (`rtl/matvec_engine.sv:259`) must become 4 bits. The scale bank grows from NSCAL = 96 uint16 (`rtl/matvec_engine.sv:182`, `rtl/matvec_engine.sv:463`) to 768 bytes. Its read side, today the NSCAL:1 mux that owns a +0.001 cone, must deliver 8 scales per beat | scale bits per row ×4.00 (1,536 → 6,144 at K = 12288); 8 reads per beat, not 1 per retire cycle | **D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:101-102`; **S**, `rtl/matvec_engine.sv:117-118` |
| 4 | **requant** | The per-matrix FP32 s_t folds into the existing output requant constant offline: a uint32 multiplier plus a shift (`ref/w4a8_ref.py:325-329`). **For A8 activations the activation scale stays a power of two**, a shift, so nothing new happens at runtime. **For NVFP4 activations** the per-token s_t = amax/2688 is a non-power-of-two FP32 per token, so the requant would need a runtime per-token multiply | A8 rows: offline only. Full NVFP4: one new runtime multiply per token | **S**, `ref/w4a8_ref.py:325-329`; **E**, not modelled |
| 5 | **full NVFP4 only: the activation lane** | The engine's activation memory holds 128 int8 per line (`rtl/matvec_engine.sv:219`). For NVFP4 activations it would hold 128 E2M1 codes + 8 UE4M3 scales. The products shrink to **9 b** (144 = 12 × 12). But the block term now carries two mantissas (≤ 225) and two exponents (span 28), and the **worst-case row bound is 58 b, which does NOT fit the 48 b `p_acc`**. The accumulator must widen, or the exponent window must be bounded by alignment | product 9 b, block sum 13 b, term 48 b, bound 58 b | **D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:105`; `rtl/matvec_engine.sv:561` |
| 6 | **full NVFP4 only: the activation quantizer** | The shipped A8 quantizer is vec_alu op DYNQ8: a shift-only requant after an amax pass (`rtl/vec_alu.sv:13-14`, `rtl/vec_alu.sv:695-699`). NVFP4 activations need a per-token amax (exists), s_t = amax/2688 (a constant reciprocal multiply), a per-16 block amax, a UE4M3 RNE encode of amax_b/6/s_t, and an E2M1 RNE encode of every x/S: seven midpoint compares against the scaled grid, with the even-code tie rule of §0.2 | a new vec_alu operation: two passes over the vector plus a divide-free encoder | **S**, `rtl/vec_alu.sv:13-14`; **E** for the structure |
| 7 | **RHT rows only: the activation-side 16-point butterfly + requant** | Before DYNQ8 on each of the **129** rotated input sites (**T**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:97`), each input vector goes through a sign flip by the site's 16-bit D, then a 4-stage fast Walsh–Hadamard (**64 add/sub per 16 elements; 16,384 per K = 4096 vector**), then /4. An int16 input grows 4 b before the /4 shift, so the rotated vector needs a requant back to the scratch width before DYNQ8. Weights are rotated offline by the emitter, which costs nothing at runtime | 64 add/sub per 16 elements; +4 b headroom; one extra pass per rotated site | **D**, `evidence/qwen_next/nvfp4/n63_rung2_table.log:106` |
| 8 | **the packer / emitter for the new layout** | The emitter picks `pack_ddr_rows` or `pack_ddr_rows8` per image (`ref/gen_layer_script.py:1624`, `ref/w4a8_ref.py:349`). The replay reads images back through the matching unpack (`ref/seq_model.py:448`). NVFP4 needs a third packer and unpacker for [weight beats of 128 E2M1 nibbles and scale beats of 64 UE4M3 bytes], the row law `ref/nvfp4.py:272-291`, the per-matrix s_t in the image header, the offline rotation for RHT rows, and a shape-word encoding the engine can decode | software only | **S**, cited lines |
| 9 | **the integer-exact reference** | `ref/w4a8_ref.py`'s `matvec_y32` is the law the RTL is built to (`ref/w4a8_ref.py:254-290`, `rtl/matvec_engine.sv:39-42`). In `ref/layer_fixed.py`, `matvec_fx` is the production call (`ref/layer_fixed.py:1201-1221`). It already dispatches W8 through the quantized dict. `matvec_to` is the entry point most callers use (`ref/layer_fixed.py:1224`). The only other call of `matvec_y32` there is a self-check (`ref/layer_fixed.py:2129`). An NVFP4 twin is y = Σ_blocks μ_b·2^(k_b)·Σ_{i∈b} q2_i·x8_i in integers (the §0.2 property), then the requant of row 4. **It does not exist.** Without it nothing here is bit-exact, and the fixed-point top-1 gate (`ref/fidelity_check.py`) cannot score an NVFP4 row | software only; the gate before any RTL | **S**, cited lines |

**The hardware classes, summarized.**

- **Shipped point:** none.
- **W4 g64 GPTQ:** restore G3.3's deleted g64 mode (Panel B note). That means
  the scale-beat field, the retire's two-scale select, and doubling the scale
  bank from NSCAL = 96 to 192 (**S**, `rtl/matvec_engine.sv:25-26`,
  `rtl/matvec_engine.sv:179-182`). The last one widens the NSCAL:1 `scales_q`
  mux, which owns a +0.001 ui_clk cone (**S**,
  `rtl/matvec_engine.sv:117-118`). **The g64 delta therefore includes widening
  a timing-marginal mux.**
- **NVFP4 + A8:** rows 1–4, 8 and 9. This is a new weight datapath. The block
  scale moves into the adder tree of the engine whose x-line cone owned the
  first campaign's WNS.
- **NVFP4 + RHT + A8:** rows 1–4 and 7–9. That is the new weight datapath plus
  the activation butterfly, and still the A8 quantizer.
- **Full NVFP4:** rows 1–6, 8 and 9. That is a new weight datapath, a new
  activation quantizer, a new activation memory layout, and a wider
  accumulator. It is the largest delta, and the only one that breaks the
  48-bit accumulator's worst-case bound.

---

## 6. What this does NOT establish

- **PPL is not the fixed-point top-1 gate.** Every row is float fake-quant
  inside a float32 torch model. The shipped acceptance gate is
  `ref/fidelity_check.py`'s fixed-point top-1 against the bf16 golden. No
  NVFP4 row has a fixed-point score, because no fixed-point NVFP4 reference
  exists (§5 row 9).
- **Nothing is bit-exact and nothing ran on silicon.**
  - A8 is modelled in float, with no int16 upstream grid and no e ≥ 0 floor
    (§0.2).
  - The shipped row's "W4 g128 + A8" is therefore the float model of the
    board's arithmetic, not the board's arithmetic itself.
- **The throughput column models the weight stream only** (§1).
  - It says nothing about the engine's timing after the §5 changes. The
    block-scale move into the tree lands in a cone family with a thin margin
    (§5.1).
  - It says nothing about the cost of an activation-side pass (§5 rows 6–7).
- **The P40 was not used for any decision row** (rulings C2, C13).
  - It was validated at 2B (fp16 +0.000485 PPL, 23.2× faster,
    `evidence/qwen_next/nvfp4/n36_rung1_table.log:76-78`).
  - It was never run at 9B. The user's Ollama server held it, and it was not
    touched.
  - Rows **n49 and n50** (the P40 duplicates of n46/n47) were **retired and
    never run**. Their numbers are not reused.
- **Rows the 9B did not run.** None of the following can be read off the 2B
  (§3.1):
  - nvfp4h + nvfp4h:dyn (the RHT with NVFP4 activations);
  - any `:static` activation-scale row;
  - a weight-only W4 g128 row (so the shipped row's weight/interaction split,
    §3 note 3);
  - bf16 + rotated A8;
  - the optional `nvfp4gptq`;
  - W4 **g128** GPTQ. The shipped engine has one row format, g128
    (**S**, `rtl/matvec_engine.sv:4`). GPTQ changes code and scale values,
    not the layout: its images pack through the same `pack_ddr_rows`
    (**S**, `ref/gptq.py:335`) at the same `row_stride` (**S**,
    `ref/w4a8_ref.py:111`). So it is the one unrun weight format that would
    need no hardware change at the shipped bytes (**E**: a reading of the
    code, not a build).
- **The NVFP4 quantizer is the plain amax recipe.** There is no scale search
  and no GPTQ. The shipped W4 g128 has MSE scale search
  (`ref/perplexity_eval.py:304-335`), so the NVFP4 rows are, if anything,
  handicapped in the weight comparison.
- **Two RHT seeds at 9B.** Their spread is small (§4), but it is two points.
- **W4 g64 GPTQ (n54) ran to completion inside its 4 h bound.** It took
  11,782 s of queue wall (**T**, `evidence/qwen_next/nvfp4/n48_rung2_queue.log:45`),
  of which the GPTQ build was 10,343 s (**T**,
  `evidence/qwen_next/nvfp4/n54_ppl_9b_w4g64gptq_a8_cpu.json:359`). Its
  calibration is `ref/calib_stats_9b_h.npz`. One GPTQ calibration and one
  run: no seed or calibration-set sensitivity was measured for it. It also
  needs a deleted engine mode back (Panel B note), which this study did not
  price beyond naming it.

---

## 7. Recommendation: WITHHELD

The study does not choose. The options, with what was measured and what was
modelled, are:

| option | 9B PPL (T) | % of shipped gap left (D) | modelled 9B tok/s (D) | hardware delta (§5) |
|---|---|---|---|---|
| keep the shipped point | 9.560220 | 100.00 % | 7.293 | none |
| W4 g64 GPTQ + A8 | 8.880120 | 49.32 % | 7.206 | restore the g64 row mode deleted at G3.3, including the scale bank 96 → 192 and its timing-marginal mux |
| NVFP4 weights + A8 | 8.954712 | 54.88 % | 7.039 | new weight datapath (§5 rows 1–4, 8, 9) |
| NVFP4 weights + RHT + A8 | 8.592140 (s0) / 8.572686 (s1) | 27.86 % / 26.41 % | 7.039 | new weight datapath + activation butterfly (§5 rows 1–4, 7–9) |
| full NVFP4 (weights + dynamic activations) | 8.696983 | 35.67 % | 7.039 | new weight + activation datapath, wider accumulator (§5 rows 1–6, 8, 9) |

The PPL figures are cited in §1 Panel A, and the tok/s figures in Panel B.

**Caveat on the tok/s column.** It is the weight-stream model only. It
excludes the activation-side passes (§5 rows 6–7) and any retire or timing
change. No row has a fixed-point top-1 score (§6).

---

## 8. The user's decision, and traceability

### 8.1 The user's decision

> **Decision:** keep the shipped point — **W4 g128 + A8**, the first row of
> §7's table. No NVFP4 or GPTQ g64 variant is adopted, and no hardware delta
> of §5 is taken.
>
> **Date:** 2026-09-24 **Notes:** the user's direction of 2026-09-24, item 4,
> "keep the shipped W4 g128 + A8" — recorded as the USER DIRECTION entry of
> the overlap campaign's ledger, `.superpowers/sdd/2026-09-24-overlap/progress.md`
> (gitignored; cited by path and date, never by line), with the gloss
> "NVFP4 §8.1 = keep shipped". The same direction turned the campaign to
> single-sequence throughput and overlap, which is where the next speed-up
> was found (`NEXT_SESSION.md` §2). Filled in 2026-09-27 (NS1); no number in
> this document changed.

### 8.2 Every run → its commit

All rows below are under `evidence/qwen_next/nvfp4/` and ran on snoke through
`evidence/qwen_next/nvfp4/nvfp4_run.sh`. The "tree" is the stamp in each log header.

| n## | row | tree (stamp) | evidence commit |
|---|---|---|---|
| n01–n45 | rungs 0 and 1 (2B screen, selftests, C1 A/B, P40 check, spec_cites) | per the `=== tree:` line in each log header | c84a55b..45a64f7 |
| n46 | 9B bf16 anchor | 1ad70a1 | d05ccf5 |
| n47 | 9B shipped all:w4g128 + a8 | 1ad70a1 | d05ccf5 |
| n48 | the rung-2 CPU queue log | e603b0c | d05ccf5 (as of n54's START), 26bab1b (final, QUEUE DONE) |
| n49, n50 | retired (P40 duplicates of n46/n47), never run | — | — |
| n51 | full NVFP4 (nvfp4 + nvfp4:dyn) | e603b0c | d05ccf5 |
| n52 | nvfp4h + a8, seed 0 | e603b0c | d05ccf5 |
| n53 | nvfp4 + a8 | e603b0c | d05ccf5 |
| n54 | w4g64gptq + a8 (`ref/calib_stats_9b_h.npz`, 4 h json bound) | e603b0c | 26bab1b |
| n55 | nvfp4, weights only | e603b0c | d05ccf5 |
| n56 | nvfp4h, weights only, seed 0 | e603b0c | d05ccf5 |
| n57 | bf16 + a8 | e603b0c | d05ccf5 |
| n58 | bf16 + nvfp4:dyn | e603b0c | d05ccf5 |
| n59 | nvfp4h + a8, seed 1 | e603b0c | d05ccf5 |
| n60 | `evidence/qwen_next/nvfp4/rung2_table.py`, the 9B table | 6438dbf | f6e119d |
| n61 | the 9B table, superseded (its `+dirty` stamp from the untracked doc draft added a `=== dirty:` header line that shifts every line by one) | f6e119d+dirty | f2fd5ff |
| n62 | the 9B table on a clean tree, n54 absent | f2fd5ff | c12a25d |
| n63 | **the 9B table this document cites**, n54 present, same line layout as n62 | 26bab1b | 845ddb6 |
| n64 | `evidence/qwen_next/spec_cites.py` over the first committed version (a467321), FAIL 0 | a467321 | b866c61 |
| n65 | `evidence/qwen_next/spec_cites.py` over fix round 1 (1f3f97c), FAIL 0; its stamp reads +dirty from NFS attribute lag on snoke right after the commit, so it is superseded | 1f3f97c+dirty | 3b49ded |
| n66 | `evidence/qwen_next/spec_cites.py` over fix round 1 (1465c0b), FAIL 0 | 1465c0b | 18e68bd |
| n67, n68 | `evidence/qwen_next/spec_cites.py` LAST over this document (n67) and over `evidence/qwen_next/nvfp4/NVFP4_RUNG1.md` (n68), after the final fix wave, on the committed tree | (this commit) | the final commit |

**Wall times** (**D**, the sums of each json's seconds_build + seconds_eval;
`evidence/qwen_next/nvfp4/n63_rung2_table.log:85-95`):
- **Plain rows:** 14.7 min (bf16) to 38.7 min (weights-only NVFP4 + RHT).
- **Rows with `--act` hooks:** 29.3 to 80.7 min at 3 concurrent.
- **The shipped row:** 77.8 min. Its production W4 build took 3,055 s.
- **W4 g64 GPTQ (n54, alone):** 195.2 min (**D**), of which the GPTQ build
  took 10,343 s (**T**) (`evidence/qwen_next/nvfp4/n63_rung2_table.log:87`).

### 8.3 The rulings this study ran under (the ledger's C1–C14)

- **C1:** backward compatibility is proven by a same-host A/B at the final tree.
  n01 against n43; n44 is the byte-identity PASS.
- **C2:** `--device`, in a separate P40 venv. The P40 was validated at 2B
  (n09: +0.000485 PPL, 23× faster) and used for no decision row.
- **C3:** static activation scales come from a calibration pass over
  `ref/ppl_corpus_calib.txt`.
- **C4:** the LM head's input fake-quant is applied in the harness's head path.
- **C5:** the A8 rule is the one found in the shipped path (§0.2).
- **C6:** the 2B deliverable is `evidence/qwen_next/nvfp4/NVFP4_RUNG1.md`.
- **C7:** selftests are behind `--selftest`.
- **C8:** the brief's RHT form (D·H16/4)·x was inert, since n19 equals n23 bit
  for bit. The accepted form is H16·diag(D)/4 with D on the input side. The
  four plain-H 2B rows are superseded.
- **C9:** the rung-0/1 commits carry an Opus trailer. Whether to reword them is
  the user's call before the push.
- **C10:** fix round 1 of rung 1.
- **C11 and C12:** the P40 queue plan, superseded by C13.
- **C13:** every 9B row runs on CPU in the shipped venv. The ruling's rate
  (≈ 20 min for a plain row, ≈ 55 min with `--act` hooks at 3 concurrent) was
  an early estimate. The plain NVFP4 rows measured 36.9–38.7 min (**D**,
  `evidence/qwen_next/nvfp4/n63_rung2_table.log:92-93`). Either way, the
  brief's "≈ 7 h" was wrong. The P40 is held by the user's Ollama server
  and was not touched.
- **C14:** the doc's fix round 1. It carries the reviewer's Important finding
  (the g64 restore's scale bank and mux) and the citation minors, and it
  re-runs spec_cites LAST.
- **The user's ruling of 2026-09-23:** 9B only from this point. That is why
  this document leads with the 9B.

The ledger with every ruling in full is
.superpowers/sdd/2026-09-23-nvfp4-study/progress.md (git-ignored by
`.superpowers/sdd/.gitignore`, as the campaign's ledgers are). The brief and
the rung reports sit beside it.

### 8.4 Where every number comes from

| claim | evidence |
|---|---|
| 9B PPLs | each row's json `"ppl"` field, cited in Panel A |
| every 9B Δ, %, byte, ms, tok/s, frontier, decomposition, 2B-vs-9B, seed, wall and bit-width figure | `evidence/qwen_next/nvfp4/rung2_table.py` → `evidence/qwen_next/nvfp4/n63_rung2_table.log` |
| 2B figures (Appendix A, §4) | `evidence/qwen_next/nvfp4/rung1_table.py` → `evidence/qwen_next/nvfp4/n36_rung1_table.log`; `evidence/qwen_next/nvfp4/NVFP4_RUNG1.md` |
| the format, RHT, A8, byte accounting | `ref/nvfp4.py` (selftest `evidence/qwen_next/nvfp4/n40_nvfp4_selftest_HEAD.log`) |
| the harness (`nvfp4`/`nvfp4h`, `--act`, `--rht-seed`) | `ref/perplexity_eval.py` (selftest `evidence/qwen_next/nvfp4/n41_ppl_eval_selftest_HEAD.log`) |
| backward compatibility | `evidence/qwen_next/nvfp4/n44_c1_byte_identity_final.log` |
| the streaming term and board token | `evidence/qwen9b/bn/BN_CENSUS.md` |
| timing standing of `matvec_engine` | `evidence/qwen9b/g5/G5D_TIMING.md` |
| launcher, plan, queue | `evidence/qwen_next/nvfp4/rung2_launch.sh`, `evidence/qwen_next/nvfp4/RUNG2_PLAN.md`, `evidence/qwen_next/nvfp4/n48_rung2_queue.log` |
| the citation check (last commit) | `evidence/qwen_next/spec_cites.py` → evidence/qwen_next/nvfp4/n67_spec_cites_NVFP4_STUDY_LAST_final.log (written after this commit, so named here without a checked cite) |

---

## Appendix A. The 2B screen (rung 1), compact

This is the Qwen3.5-2B ranking that preceded the 9B. It is kept as the screen
it was. Its full form, with every cite, is
`evidence/qwen_next/nvfp4/NVFP4_RUNG1.md` §1.

| row (2B) | PPL (T) | % of 2B shipped gap left (D) | cite |
|---|---|---|---|
| bf16 anchor | 12.346298 | 0.00 % | `evidence/qwen_next/nvfp4/n36_rung1_table.log:10` |
| SHIPPED W4 g128 + A8 | 14.860742 | 100.00 % | `evidence/qwen_next/nvfp4/n36_rung1_table.log:11` |
| W4 g64 GPTQ + A8 | 13.423831 | 42.85 % | `evidence/qwen_next/nvfp4/n36_rung1_table.log:13` |
| NVFP4 + A8 | 14.028509 | 66.90 % | `evidence/qwen_next/nvfp4/n36_rung1_table.log:16` |
| NVFP4 + RHT + A8 | 13.494146 | 45.65 % | `evidence/qwen_next/nvfp4/n36_rung1_table.log:17` |
| full NVFP4, dyn | 14.305507 | 77.92 % | `evidence/qwen_next/nvfp4/n36_rung1_table.log:18` |
| full NVFP4 + RHT, dyn / static | 14.710242 / 14.790656 | 94.01 % / 97.21 % | `evidence/qwen_next/nvfp4/n36_rung1_table.log:19-20` |
| weights only: NVFP4 / NVFP4 + RHT | 13.493740 / 13.420657 | 45.63 % / 42.73 % | `evidence/qwen_next/nvfp4/n36_rung1_table.log:14-15` |
| acts only: A8 / NVFP4 dyn | 12.842898 / 13.153599 | 19.75 % / 32.11 % | `evidence/qwen_next/nvfp4/n36_rung1_table.log:21-22` |

**Where the 9B and the 2B agree.**
- Every NVFP4 row beats the shipped point.
- The RHT helps A8 activations.
- The damages add nearly linearly.

**Where they disagree** (§3.1). Three sign flips:
- the activation formats' order;
- the RHT's weight-side sign;
- full NVFP4 against the A8 rows.

It also changes one ranking: W4 g64 GPTQ + A8 goes from best deployable row
to third of four configurations (fourth of five rows, with the two RHT seeds
counted separately; §1 reading c).

**The 2B's best deployable row (W4 g64 GPTQ + A8) is third of four
configurations at 9B** (fourth of five rows with both RHT seeds)
(8.880120, §1 reading c).
