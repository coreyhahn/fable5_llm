# Track Q V4 — GPTQ-lite, the error-feedback W4 quantizer (task 8b)

*Evidence of record for task 8b. Directory choice, stated: a new `q2/v4/`
rather than `q2/v3/GPTQ.md`, because this task ships a second quantizer with
its own calibration artifact and four scoring runs, not an addendum to V3.*

Every number below is quoted from a committed log/json in this directory.
**All compute ran on snoke** (darthplagueis is under the arithmetic-fault
embargo of `../v3/V3.md` §6); every json and log carries `host snoke`.

---

## 0. Headline

| | value |
|---|---|
| **V4 PPL (2B, GPTQ-lite)** | **12.941240** (`ppl_v4gptq.json`), reproduced in a second process with a **bit-identical `nll_sum` 62801.959165** (`ppl_v4gptq_rerun.json`) |
| anchors | bf16 12.346298 · V2 13.744231 · V3 13.391781 |
| **gap recovered (V2 → bf16)** | **57.441%** — V3 recovered 25.212% |
| **improvement over V3** | **−0.450541 PPL** vs V3 as published (−0.450602 vs V3 re-scored on this task's calibration file, row B1), i.e. a further **43.1% of the gap V3 left open** |
| decomposition (B1→B2→B3, §4) | the right diagonal (`E[x^2]`) buys −0.175659; **error feedback buys −0.274943** — the feedback is the larger half |
| bits/weight | **6.752534427466289 — identical to V2 and V3 to the last digit.** V4 is free quality, not a bit-rate trade |
| wire format | untouched: same `w4`/`m`/`e`/`sh`/`g=64`, same `row_stride`, packs and round-trips; **the group scales `m`,`e` are unchanged too** — only the nibbles move |
| per-matrix output error vs V3 | **−41.7% mean, better on 7/7** real matrices (`matrix_error_check.log`) |
| cost | +1030 s of image-build time for the whole 2B model, one 241 s calibration run, **zero** at inference |
| brief's proposed ship rule (≥25% of the remaining gap, ≤13.131 PPL) | **PASS by a wide margin: 43.1%, 12.941240** |
| fixed-point spot-check S=4 | **85/108** vs V3's 86 and V2's 80 — clip-free, no regression; McNemar p=1.000, and the probe cannot resolve even V3's +6 over V2 (p=0.263), so it neither confirms nor contradicts the float gain (§7) |
| shipping path | the DDR image generator was **not calibration-wired at all** (V3 shipped with the same gap); wired here, regen gate still PASS, all 187 lookups resolve (§8.1) |

---

## 1. What was built, and the finding that shaped it

### 1.1 A diagonal Hessian cannot do error feedback — proven, not argued

The task brief proposed "sequential per-column quantization with error
feedback … using a diagonal Hessian approximation", and the dispatch flagged
that mean-|x| salience is insufficient and suggested per-channel `E[x^2]`.
That statistic is indeed the right *diagonal*, but on its own it cannot
produce error feedback at all. GPTQ's update after quantizing column *j* is

```
W[:, F] -= (w_j - q_j) / [H^-1]_jj * [H^-1]_j,F        (F = columns not yet done)
```

If `H` is diagonal, `H^-1` is diagonal, so `[H^-1]_j,F` is identically zero:
**the feedback term vanishes and GPTQ degenerates to plain rounding.** All a
diagonal statistic can do is weight the group-scale search — which is exactly
what V3 already does.

This is not a derivation on paper; it is asserted as a bit-identity in three
places, so it cannot rot:

| test | assertion |
|---|---|
| `ref/gptq.py --selftest` case 1 | `quant_linear_gptq(W, hess=diag(d))` is **byte-identical** to `quant_linear_mse(W, salience=sqrt(d))`, and `hess=I` to the unweighted rule, at g=64 and g=128 |
| `ref/layer_fixed.py` `_gptq_invariance` | through the env plumb, on a whole synthetic layer: a diagonal-Hessian npz in `mode=gptq` reproduces `mode=h2` on **8/8** matrices bit-identically |
| `ref/perplexity_eval.py --selftest` D3 | through the injection plumbing: `w4g64gptq` with a diagonal Hessian == `w4g64h`, exactly |

So the task needed the **full** `K x K` second moment, and the deliverable is
real GPTQ, not a diagonal surrogate of it. The measurements below vindicate
the choice twice over: the diagonal-only variant is worth −0.176 PPL and the
feedback it cannot express is worth a further −0.275.

### 1.2 The quantizer (`ref/gptq.py`)

`quant_linear_gptq(Wf, g, hess)` returns the same dict as `quant_linear_mse`
— `w4` (N,K) int8, `m` (N,NG) uint16, one shared `e`, the same `sh` and `g`.
Two passes:

1. **Group scales**: the *existing* 17-point MSE grid search, weighted by
   `E[x_k^2]` (the exact diagonal of the objective GPTQ minimises), reached
   through `layer_fixed._salience_weights` — the same helper V3 uses, which is
   what makes the diagonal bit-identity above hold.
2. **The sweep**: Cholesky of the damped inverse Hessian
   (`damp = 0.01 * mean(diag H)`, GPTQ's own), then columns left to right with
   the error of each fed into the not-yet-quantized columns of the same row,
   in the standard blocked ("lazy batch") form with the block equal to the
   quantization group. Lazy batching is *exact*, not an approximation: a
   column outside the block is not read until the block's accumulated update
   has been applied.

**Rows are independent** (the scales are per (row, group) and the feedback
never leaves a row), so the sweep row-chunks exactly — asserted at
`rowchunk=7` vs one-shot in `gptq --selftest` case 4, and across the two
production entry points in `gen_model_script._selfcheck`. That is why the
248320-row tied head needs no separate "big" twin: it takes the same path.

A channel that never fires on the calibration corpus (`diag H == 0`) gets the
damping value on its diagonal and is quantized by plain rounding with no
feedback — deliberately *not* the reference implementation's "zero those
weights", which would discard information the corpus merely failed to
exercise. Measured on the real 2B checkpoint: **0 dead channels out of
296960** across all 97 sites (`calib_identity_check.log`), so the choice
never bites here — it is a robustness property, not a live one.

### 1.3 What is "lite"

* **No act-order.** Reordering input channels by activation magnitude is the
  usual extra tenth of a PPL point in GPTQ, and it **breaks the wire format** —
  the RTL walks a weight row in beat order. Out of scope by construction (the
  brief and the dispatch both say so).
* **Group scales are fixed before the sweep**, from the original weights.
  Textbook group-wise GPTQ re-fits each group's scale mid-sweep on the
  already-compensated weights. Here that is a **two-pass problem**, because
  the wire format stores one shared exponent `e` per matrix: `e` is
  `ceil(log2(max group scale)) + 1`, so it cannot be known until the last
  group's scale is, and every group's mantissa `m` is expressed relative to
  it. Doing it properly means sweeping once to learn the scales, fixing `e`,
  and sweeping again — which also makes `e` a function of the feedback.
  **The cost of not doing it is unmeasured here.** (The reviewer's idealized
  probe put the textbook variant ~3.6% better on output error on a synthetic
  case; quoted as an unmeasured upside, not as our number.) What *is* certain
  is the direction: since pass 1 runs on the original weights, `m` and `e` are
  identical to the no-feedback rule **by construction** — that is not evidence
  the choice is free, it is a restatement of the choice, and §5's per-matrix
  assertion of it is a wire-format check, not a quality one.
* Everything else is textbook: full `K x K` Hessian, Cholesky of the damped
  inverse, sequential feedback, damping, dead-channel handling.

---

## 2. The calibration artifact

`ref/calib_stats.py` grew an opt-in `--hessian` collector. Same read-only
forward hooks on the same bf16 model over the same calibration corpus; it
additionally accumulates `sum_t x x^T` per **input site**.

*Sites, not tensors*: a matrix's Hessian depends only on its input, and q/k/v
share one, gate/up share one, the four DeltaNet `in_proj_*` share one. 187
tensors collapse to **97 sites**. The sharing is declared in `SITE_OF_SUFFIX`
and **verified at collection time by tensor identity** — two members of a site
handed different tensors inside one forward is a hard error, not a silent
double count (`Collector._hess_acc`, which also installs a per-forward counter
hook so "inside one forward" is exact).

```
ref/calib_stats_2b_h.npz
  sha256 71a4e21be18ad0ae97b460ff854c6e15a935c253906bb57727b923e94a1714f3
  4627.1 MiB   187 salience vectors + 97 Hessian sites + 97 E[x^2] vectors
  32768 tokens of ref/ppl_corpus_calib.txt (sha256 522afbcaa928956d…)
  checkpoint header ccba2c1f…   collected in 241.0 s on snoke, torch 2.12.0+cpu
```

(`calib_stats_2b_h.log`; gitignored by the existing `ref/calib_stats_*.npz`
rule, regenerable in ~4 minutes. The calibration corpus is the **train**
slice and `main()` still refuses the eval corpus by filename, so every number
in §4 is measured on data the quantizer never saw.)

### 2.1 The change is ADDITIVE — the V3 vectors do not move

`calib_identity_check.log` / `.py`, four collector runs on snoke:

| comparison | result |
|---|---|
| HEAD's collector vs this branch's, **both at torch threads=16** | **187/187 salience vectors BIT-IDENTICAL** |
| this branch without `--hessian` vs **with** it, threads=16 | **187/187 BIT-IDENTICAL** |
| HEAD's collector at threads=16 vs threads=**10** | 4/187 identical, worst **1.125e-07** relative |

The third row is the control that makes the first two meaningful: the
collector's output is only reproducible at a **fixed thread count** (a threaded
GEMM's reduction order depends on it), at the same 1e-7 level the V3
cross-host study found. Held fixed, the code change is provably inert. (The
npz *files* cannot be compared: `np.savez` is a zip with embedded timestamps
and `_meta_json` carries `generated`/`seconds_*`/`host`. What is compared is
the arrays every consumer actually reads.)

The `h2/` second moments are the **stored diagonals** of the stored Hessians
(97/97 exact, same log), not a second accumulation — so the diagonal-weighted
quantizer and GPTQ weight their scale searches by bit-identical numbers,
which is what makes the §1.1 bit-identity testable end to end.

---

## 3. Wire format and the frozen flow

### 3.1 Wire-format invariance

| check | result |
|---|---|
| returned dict: keys / shapes / dtypes / `g` / `sh` | identical to `quant_linear_mse` (`gptq --selftest` 2) |
| group scales `m` and shared exponent `e` | **identical** to the no-feedback rule on every synthetic matrix and all 7 real matrices of §5 (asserted, not merely observed) |
| `w4a8_ref.pack_ddr_rows` → `unpack_ddr_rows` | round-trips a GPTQ image exactly, `row_stride` unchanged (`gptq --selftest` 5) |
| bits/weight, whole model | **6.752534427466289** in all four scoring jsons — identical to V2/V3 to the last digit |
| the real 248320-row tied head | GPTQ gives it `e=-4 sh=6` — the same shared exponent and requant shift V3's fixed-point run reports (`fixed_v4gptq_g64_S4.log` vs `../v3/fixed_v3_g64_S4.log`) |
| act-order / column permutation | none: rejected as wire-breaking, never implemented |

### 3.2 Frozen-flow guard (all on snoke, post-all-edits)

| check | result |
|---|---|
| `ref/w4a8_ref.py` selftest vs HEAD | **BYTE_IDENTICAL** (`selftest_diff_vs_head.log`) |
| `ref/layer_fixed.py` selftest vs HEAD | identical on every pre-existing line; **4 added lines** (`30a31,34`), all new `gptq:` guards |
| `ref/scripts/regen_gate.sh` | **REGEN_GATE_PASS** — the frozen 0.8B `model_v2_s1` stream reproduces sha256 `a69864d2…` and the `.txt` compares equal (`regen_gate_snoke.log`) |
| `gen_model_script._selfcheck` | **True**, extended with a GPTQ row-chunk case |
| `ref/gptq.py --selftest` | **PASS** (7 cases, `selftest_gptq.log`) |
| `ref/calib_stats.py --selftest` | **PASS** (A–F; E and F are new) |
| `ref/perplexity_eval.py --selftest` | **PASS** (D3 is new) |
| `ref/scripts/regen_gate.sh` **after wiring the emitters** (§8.1) | **REGEN_GATE_PASS** again — the wiring is inert with the plumb off |
| emitter calibration lookups resolve (§8.1) | **186 layer + 1 head**, in both `gptq` and `salience` modes (`emitter_wiring_check.log`) |

One production quantizer, two harnesses: `perplexity_eval --inject
all:w4g64gptq --calib-stats FILE` and `fidelity_check` under
`FABLE5_CALIB_STATS=FILE FABLE5_CALIB_MODE=gptq` reach the **same**
`gptq.quant_linear_gptq`. D3 re-checks the cross-harness key derivation in
both directions — now for the **site** names as well as the tensor names (on
the selftest's tiny model: 9 sites from 16 tensors; the same derivation
produces the real model's 97 from 187), because a wrong site would weight a
matrix by another block's second moments and both harnesses would still
appear to work.

---

## 4. Table A — PPL, weight damage only (float compute)

All rows: same corpus (`ref/ppl_corpus_eval.txt`, sha256 `6bf4f867…`), same
**24528 positions**, `--res-scale 8`, `dn_conv:cw13,emb:emb16`. A0/A2/A6 are
quoted from `../v3/V3.md` Table A; B-rows are this task, all on snoke at
torch 2.12.0+cpu, threads=10.

| # | config | inject (`all:`) | PPL | vs bf16 | gap recovered | json |
|---|--------|-----------------|-----|---------|---------------|------|
| A0 | 2B bf16 anchor | *(none)* | **12.346298** | — | — | `../../q1/ppl_2b_bf16.json` |
| A2 | **V2** | `w4g64` | **13.744231** | +1.397933 | 0% | `../v1_v2/ppl_v2.json` |
| A6 | **V3** (task 8) | `w4g64s` | **13.391781** | +1.045483 | 25.212% | `../v3/ppl_v3.json` |
| B1 | V3 re-scored on THIS npz | `w4g64s` | 13.391842 | +1.045544 | 25.208% | `ppl_v3_recal.json` |
| B2 | **V4h** (diagonal only) | `w4g64h` | **13.216183** | +0.869885 | **37.773%** | `ppl_v4h.json` |
| B3 | **V4 GPTQ-lite** | `w4g64gptq` | **12.941240** | +0.594942 | **57.441%** | `ppl_v4gptq.json` |
| B4 | V4 GPTQ, rerun | `w4g64gptq` | **12.941240** | — | — | `ppl_v4gptq_rerun.json` |

Every row's `avg_bits_per_weight` is **6.752534427466289**; the four B-jsons
agree on `res_scale` (8.0), `corpus_sha256`, `n_positions` (24528) and
`calib_stats_sha256` (`71a4e21b…`). Each step is a **single-variable**
comparison:

```
B1 -> B2   change the diagonal weight   (mean|x|)^2  ->  E[x^2]      -0.175659
B2 -> B3   add error feedback           (nothing else moves)         -0.274943
B1 -> B3   V4 vs V3, like for like                                   -0.450602
```

### 4.1 Reproducibility, and why row B1 exists

**B3 and B4 are bit-identical**: `nll_sum 62801.959165` in both, PPL
12.941240 to all six published decimals. Two separate processes, same host,
same thread count.

B1 keeps the headline from being confounded by the calibration file. V3's
published number (A6) was scored against a *darthplagueis-collected* npz at
torch threads=24; every V4 row uses the new snoke-collected one at
threads=10. Re-scoring V3's own quantizer under the B-row conditions gives
**13.391842 vs 13.391781 — a delta of +0.000061**, which is those two
1e-7-level effects together (the calibration difference of `../v3/V3.md` §6,
and the fact that the float PPL path is reproducible across thread counts to
~1e-8 relative rather than bit-exactly — §4 there). It is **0.014% of the
0.450602 improvement**, so the V4-vs-V3 conclusion is unaffected whichever V3
row you compare against: 57.441% vs 25.212% published, or vs 25.208%
re-scored.

Thread count is then held at 10 across all four B-rows, so every comparison
*within* Table A's B block is free of that term — which is why B1 is measured
rather than inherited from A6.

---

## 5. Table B — what the QUANTIZER does, matrix by matrix

PPL says what the model does. This says what the quantizer does, in the units
it is actually optimising: `||(W - Wq) X^T||_F / sqrt(T) = sqrt(tr(D H D^T))`
— `H` is the T-normalised second moment, so the figures below are per-token
RMS output error, not the raw Frobenius norm — on the
real checkpoint with the real Hessians (`matrix_error_check.py/.log`, one
matrix per injection class). The tied head is represented by its **first 8192
rows** — a sample, stated as one: rows are independent under both rules, but
the matrix-wide shared exponent `e` is chosen from the largest group scale
among the rows present, so a row slice is not guaranteed to reproduce a
full-head run's `e`. All four rules see the same slice, so the comparison
between them is unaffected.

| matrix | shape | V2 | V3 | V4h | **V4** | V4 vs V3 |
|---|---|---|---|---|---|---|
| `layers.0.linear_attn.in_proj_qkv` | (6144, 2048) | 6.59 | 6.08 | 6.07 | **3.33** | **+45.2%** |
| `layers.0.linear_attn.out_proj` | (2048, 2048) | 0.29 | 0.21 | 0.21 | **0.12** | **+44.8%** |
| `layers.12.mlp.gate_proj` | (6144, 2048) | 3.26 | 2.74 | 2.74 | **1.85** | **+32.6%** |
| `layers.12.mlp.down_proj` | (2048, 6144) | 0.22 | 0.21 | 0.21 | **0.14** | **+32.9%** |
| `layers.19.self_attn.q_proj` | (4096, 2048) | 5.20 | 3.93 | 3.93 | **2.52** | **+36.0%** |
| `layers.19.self_attn.o_proj` | (2048, 2048) | 0.90 | 0.67 | 0.66 | **0.31** | **+54.5%** |
| `lm_head` (first 8192 rows) | (8192, 2048) | 21.02 | 18.91 | 18.88 | **10.24** | **+45.8%** |

```
V3  vs V2 : +16.1% mean  (+3.5% .. +26.4%),  better on 7/7
V4h vs V3 :  +0.6% mean  (+0.1% ..  +1.5%),  better on 7/7
V4  vs V3 : +41.7% mean (+32.6% .. +54.5%),  better on 7/7
```

Two things to read here.

1. **GPTQ delivers a large, uniform reduction** in the quantity that matters —
   41.7% mean, no matrix worse. That is the mechanism behind the PPL result,
   measured independently of it.
2. **This metric does NOT explain the V3 → V4h PPL step.** On it the two
   diagonals are indistinguishable (+0.6%), yet swapping `(mean|x|)^2` for
   `E[x^2]` is worth −0.176 PPL. The same script measures how far apart the
   two diagonals actually are, per input channel:

   ```
   E[x^2] / (mean|x|)^2 :  median 1.97   p95 3.94   max 51.1   (mean over the 7)
   V3 -> V4h moves 18.1% of the group scales (mean over the 7 sampled
   matrices; 5.3% .. 36.1% each)
   ```

   So they are the same in the bulk and far apart in the tail — Jensen's
   `(E|x|)^2 <= E[x^2]`, with the gap concentrated exactly on the heavy-tailed
   channels — and the change is not cosmetic: on the sampled matrices it
   re-picks about a fifth of the group scales. That the tail channels matter to the model far more than their
   share of a Frobenius norm is the natural reading, and it is consistent with
   every number here, but **the causal step is a hypothesis, not a
   measurement** — what is measured is the ratio distribution, the scale
   churn, the near-tie on Frobenius error, and the PPL delta.

GPTQ also **increases** the weight error it is allowed to trade away
(`||W - Wq||_F` rises 5.510 → 7.010 on the first row, and on every row): it
buys output fidelity with weight fidelity, exactly as designed. Any future
audit that scores W4 images by weight error alone will rank V4 *worse*; that
metric is the wrong one, and this table is the reason.

---

## 6. The decision

```
gap to close   = V2 - bf16      = 13.744231 - 12.346298 = 1.397933
V3 recovered   = V2 - V3        = 13.744231 - 13.391781 = 0.352450  (25.212%)
remaining gap  = V3 - bf16                              = 1.045483
V4 recovers    = V2 - V4        = 13.744231 - 12.941240 = 0.802991  (57.441%)
V4 over V3     = V3 - V4        = 13.391781 - 12.941240 = 0.450541
   as a share of the gap V3 left open   0.450541 / 1.045483 = 43.09%
   (against the re-scored B1 baseline:  0.450602 / 1.045544 = 43.10%)
```

The brief proposed (controller to set): *GPTQ-lite ships only if it recovers
a further ≥ 25% of the remaining 1.045483 gap, i.e. ≥ 0.261 PPL, taking V4 to
≤ 13.131.*

> ### **V4 recovers 43.1% of the remaining gap and lands at 12.941240 — the rule passes by 1.7x, not by a margin anyone has to squint at.**
>
> Unlike task 8's qualified 25.212%-vs-25% trigger, nothing here is near a
> threshold: the improvement is 0.450541 PPL against a 0.261 bar, the two runs
> are bit-identical, and the per-matrix mechanism (§5) is independently
> measured. The 0.000061 calibration-file effect (§4.1) is four orders below
> the decision quantity.

### Recommendation for gate D

**Adopt GPTQ-lite (`w4g64gptq`) as the production W4 quantizer for 2B; keep
V3 only as the fallback if the extra ~17 minutes of image-build time or the
4.5 GiB build-time calibration file is unacceptable.** It is wire-format
identical, bit-rate identical, costs the board nothing, needs no RTL change,
and recovers 57.4% of the W4 weight-damage gap where V3 recovered 25.2%.

**With one qualification the controller should hear before deciding:** that
57.4% is *weight damage in float*. The 108-step fixed-point probe at S=4
scores V4 at 85/108 against V3's 86 — statistically a tie, and clip-free
either way (§7). The recommendation rests on the PPL measurement (24528
positions, bit-identically reproduced) and on the per-matrix mechanism (§5);
it does **not** rest on the fixed-point probe, which is too coarse to see a
change of 3.4% of PPL (= 43% of the gap V3 left open) and says so — by its own
McNemar arithmetic it cannot even resolve V3's +6 steps over V2 (p=0.263).

---

## 7. Fixed-point spot check (S=4)

The dispatch's rule: run one S=4 fidelity check if the PPL gain is material
(> 5% of the gap over V3). The gain is **32.2% of the gap** — 6.4x the
threshold — so the check was run:

```
FABLE5_MODEL=2b FABLE5_CALIB_STATS=ref/calib_stats_2b_h.npz FABLE5_CALIB_MODE=gptq \
  python3 ref/fidelity_check.py --cache tb/scripts_scratch/golden_bf16_2b.npz \
  --res-scale 4 --wire-group 64 --ntok 24 --free-ntok 24
```

### 7.1 Result — and it does NOT reproduce the float gain

| config (S=4, g64, mse) | top-1 | rank med | rank max | top5 ovl | `\|x\|`max | clips | S_F sat | source |
|---|---|---|---|---|---|---|---|---|
| **V2** | **80/108** | 0.0 | **911** | 3.46 | 26465 (81%) | 0 | 391 | `../v1_v2/DECOMP.md` B8 |
| **V3** | **86/108** | 0.0 | 7 | 3.56 | 27820 (85%) | 0 | 414 | `../v3/fixed_v3_g64_S4.json` |
| **V4 GPTQ** | **85/108** | 0.0 | 68 | 3.49 | 28068 (86%) | **0** | 380 | `fixed_v4gptq_g64_S4.json` |

Per prompt (of 27 steps each): V3 `24 18 22 22`, V4 `23 16 23 23` — V4 wins
two prompts, loses two, nets **−1 step in 108**. Free-running text is readable
on all four prompts, with the same repetition-loop failure mode V2 and V3 show
on prompt 1.

**The honest reading: this probe cannot resolve a −0.45 float-PPL
improvement, and it did not.** Three reasons, in order of size:

1. **It measures a different damage.** PPL here is *weight* damage only; the
   fixed-point run adds datapath damage (int16 Q4.11 residual, per-head block
   floating, DYNQ8). Q5's ablation ladder priced that at 108 → 93-94 (float
   W4-dequant) → 80-86 (fixed): the datapath step is comparable to the whole
   weight step, so an improvement of 3.4% of PPL (= 43% of the gap V3 left
   open) sits well inside it.
2. **108 teacher-forced steps is a coarse ruler.** ±2 steps of per-prompt
   swing is normal here (V3 vs V4 swing by −1, −2, +1, +1); one step is 0.9%.
3. The two quantizers are in the *same* fixed-point regime: both clip-free at
   S=4, rank median 0.0, top-5 overlap 3.5, and both far above V2's 80.

What the check *does* establish, which is what a spot check is for: **V4 is
safe in fixed point** — no new clipping (0 at S=4), residual peak 28068 =
86% of the int16 rail (V3 85%, still 1.17x margin), S_F saturation *lower*
than V3 (380 vs 414), the same `e=-4 sh=6` head, and the same readable
free-running behaviour. It introduces no fixed-point regression that would
block shipping it.

**The tail moved the wrong way, and not only at the maximum.** Rank median
is 0.0 for all three configs, but every aggregate is worse than V3's
(`fixed_significance.py/.log`, parsed straight from the three committed logs):

| S=4 g64 mse | top-1 | rank max | rank sum | rank mean | rank p90 |
|---|---|---|---|---|---|
| V2 | 80/108 | 911 | 992 | 9.185 | 2 |
| V3 | **86/108** | **7** | **45** | **0.417** | **1** |
| V4 | 85/108 | 68 | 132 | 1.222 | 2 |

**Two steps carry 93% of it.** The sum rises by 87 (45 → 132), of which
**66 is step 39** (rank 2 → 68) and **15 is step 0** (rank 0 → 15); the
other 106 steps net **+6 between them**. Per step: **13 worse, 13 better, 82
unchanged** — outside those two outliers the probe sees noise, not a broad
worsening. (An earlier draft of this section read "a broad, small worsening";
the per-step data says otherwise and this is the corrected reading. The p90
1 → 2 shift is the 13 worse steps showing up at the decile, not a trend.)
V2's 911/992/9.185/2 puts all of it in perspective: V4 is far better than the
pre-V3 baseline on exactly this tail metric, and worse than V3 on it.

**And no top-1 difference in this table is statistically resolvable.**
McNemar's exact test on the paired per-step outcomes (same 108 golden steps,
so only the discordant pairs carry information):

```
V2 vs V3 : b=7  c=13  p = 0.263     <- even V3's +6 steps does not reach p<0.05
V3 vs V4 : b=9  c=8   p = 1.000     <- the -1 step is exactly noise
V2 vs V4 : b=5  c=10  p = 0.302
```

If a **+6-step** improvement cannot be resolved by this probe, a −1-step
difference certainly cannot. That is the "coarse ruler" argument made exactly:
the check is a safety screen, not a quality comparison. (These figures were
recomputed here from the logs rather than quoted; the script is committed.)

*Run hygiene: unlike V3's darthplagueis runs this used the **unmodified**
production path — no `guarded_matvec_wrapper` shim — and `w4a8_ref.py:161`
never fired, so the log is what the production code produced, first attempt.*

### 7.2 What it cost

`fixed_v4gptq_g64_S4.log`: LM head 415.2 s (V3: 209.2 s), 24 layers 1343.1 s
(V3: 560.1 s), then ~83 minutes of fixed-point decode identical in cost to
V3's — GPTQ is a build-time cost only, as §8 says. The dispatch budgeted
~30 min for this check; the real figure on contended snoke is **~1 h 50 m**,
of which 29 minutes is quantization.

---

## 8. Cost, and what shipping V4 would mean

| stage | cost (snoke, contended with a Vivado build and 3 sibling runs) |
|---|---|
| calibration, **one-off per model** | 241 s collect; **4.5 GiB** npz (gitignored, regenerable in ~4 min) |
| quantize the whole 2B model | **1949 s** with GPTQ vs **918 s** for V2/V3 rounding — **+1030 s (+112%)** |
| inference / RTL / DDR image | **zero**: same wire format, same `row_stride`, same bits/weight, same engine |

### 8.1 The image generator had to be wired first — it now is

Review caught this, and it was real: **before this task the DDR image
generator could not produce a calibrated image at all.** `gen_model_script`
called `LF.quant_layer(wf, ...)` with no `layer_idx` (a hard SystemExit with
the plumb on) and quantized the LM head with `quant_linear_big(emb_f, g=...)`
— no calibration arguments at all, i.e. a *silently* unweighted V2 head under
a calibrated name, which is exactly the mixed-image failure the rest of this
work is built to prevent. V3 shipped with the same gap; nobody had run the
generator with the plumb on.

Wired in this task, in the two emitters that quantize the **real checkpoint**:

| file | change |
|---|---|
| `ref/gen_model_script.py` (DDR image generator) | `quant_layer(..., layer_idx=i)`; head takes `salience=LF.calib_salience("lm_head")`, `hess=LF.calib_hess("lm_head")` |
| `ref/seq_chat.py` (host-side chat runner) | the same two |

**The full census.** `grep -rn 'quant_layer(' --include='*.py'` finds **12
call sites in 9 files** outside `layer_fixed`'s own selftests (8 more, all
synthetic). Earlier drafts of this section published a shorter list and a
wrong rationale for `audit_ranges`; this is the swept one:

| # | site | weights | wired? |
|---|---|---|---|
| 1 | `ref/gen_model_script.py:431` — DDR image generator | real ckpt | **wired here** |
| 2 | `ref/seq_chat.py:1256` — host-side chat runner | real ckpt | **wired here** |
| 3 | `ref/fidelity_check.py:207` — `quantize_model` | real ckpt | already wired (V3) |
| 4 | `ref/fidelity_check.py:451` — `--ablate`'s quantize | real ckpt | already wired (V3) |
| 5 | `ref/fidelity_check.py:524` — `--blocks` block probe | real ckpt | **no** — single-layer DeltaNet diagnostic, CLI-reachable; refuses loudly |
| 6 | `ref/audit_ranges.py:361` — frozen-format range audit | **real ckpt** (`LQ.load_layer` at `:360`, real embedding at `:493`) | **no** — a *decision*, not a non-applicability: whether the audit should score calibrated images is Q10-adjacent (§10.3) |
| 7 | `sw/infer.py:682` — per-MMIO board REPL | **real ckpt** | **no** — the file calls itself "the legacy per-MMIO reference path" (`sw/infer.py:407`); production chat moved to `seq_chat`/`chat_seq` (9.3 s/token → sequencer, `evidence/chat/CHAT_SEQ_GATE.md`). Reviving it calibrated means wiring `:682` **and** its head at `:695` |
| 8-9 | `ref/gen_layer_script.py:1507`, `:1527` | random | n/a |
| 10 | `ref/gen_chain_script.py:91` | random | n/a |
| 11 | `ref/gen_token_script.py:135` | random | n/a |
| 12 | `tb/scripts/gen_seq_c_vectors.py:107` | random | n/a |

Rows 8-12 quantize `LR.init_layer_weights` random weights, where activation
calibration of a real checkpoint is meaningless. Every unwired site refuses
**loudly** with the plumb on (missing `layer_idx` ⇒ SystemExit), and
`gen_layer_script` now says why in a comment. That matters most for row 7:
`sw/infer.py` also quantizes its head with no calibration arguments
(`sw/infer.py:695` — the *silent* failure class), but its layer call at `sw/infer.py:682` raises
first, so it cannot emit a mixed image; it simply cannot run calibrated.

Verification, both mandatory after touching emitter territory:

| check | result |
|---|---|
| `ref/scripts/regen_gate.sh` after the wiring | **REGEN_GATE_PASS** — frozen 0.8B stream still sha256 `a69864d2…` (`regen_gate_snoke.log`) |
| every argument the emitter now passes actually resolves | **186 layer lookups over layers 0..23 + the head**, in `mode=gptq` (186 Hessian factors) *and* `mode=salience` (186 vectors), against the real 2B npz — `emitter_wiring_check.py/.log` |

**Not claimed:** a full calibrated 2B image has not been emitted (≈30 min and
gigabytes of artifacts, and no gate consumes one yet). What is established is
that the lookups succeed for every tensor the emitter will ask for, and that
the quantizer behind them is the one `fidelity_check` ran end to end for
1 h 50 m (§7).

### 8.2 The recipe

```bash
FABLE5_MODEL=2b FABLE5_CALIB_STATS=ref/calib_stats_2b_h.npz \
  FABLE5_CALIB_MODE=gptq python3 ref/gen_model_script.py <out> <seed> <ntok> \
  --res-scale=8
```

With **`FABLE5_CALIB_STATS` unset**, every generator, testbench and frozen
artifact is byte-identical to today (§3.2). The two variables are not
symmetric and neither is a no-op on its own: `FABLE5_CALIB_STATS` set with
`FABLE5_CALIB_MODE` unset defaults to **V3 salience** (a calibrated image, not
the frozen one), and `FABLE5_CALIB_MODE` set with `FABLE5_CALIB_STATS` unset
is a **SystemExit at import** by design (§3.2's knob-must-bite discipline).
The 4.5 GiB Hessian file is a **build-time** input only — nothing about it
reaches the board.

## 9. Reproduction

```bash
# 0. calibration (once per model, ~4 min, 4.5 GiB)
FABLE5_MODEL=2b python3 ref/calib_stats.py --corpus ref/ppl_corpus_calib.txt \
    --out ref/calib_stats_2b_h.npz --hessian --threads 16

# 1. the four scoring runs (run_v4.sh in this directory)
FABLE5_MODEL=2b python3 ref/perplexity_eval.py --corpus ref/ppl_corpus_eval.txt \
    --inject all:w4g64gptq,dn_conv:cw13,emb:emb16 \
    --calib-stats ref/calib_stats_2b_h.npz --res-scale 8 \
    --json-out evidence/qwen2b/q2/v4/ppl_v4gptq.json

# 2. the quantizer's own tests
python3 ref/gptq.py --selftest
python3 ref/layer_fixed.py                                  # incl. _gptq_invariance
FABLE5_MODEL=2b python3 ref/perplexity_eval.py --selftest   # incl. D3
FABLE5_MODEL=2b python3 ref/calib_stats.py --selftest       # incl. E, F
bash ref/scripts/regen_gate.sh                              # frozen 0.8B flow

# 3. the per-matrix error table and the calibration identity proof
python3 evidence/qwen2b/q2/v4/matrix_error_check.py
python3 evidence/qwen2b/q2/v4/calib_identity_check.py

# 4. the fixed-point probe's own statistics, and the emitter wiring
python3 evidence/qwen2b/q2/v4/fixed_significance.py
FABLE5_MODEL=2b FABLE5_CALIB_STATS=ref/calib_stats_2b_h.npz \
    FABLE5_CALIB_MODE=gptq python3 evidence/qwen2b/q2/v4/emitter_wiring_check.py
```

On snoke the interpreter is `/home/cah/.venv/bin/python` for numpy-only
scripts and `~/.local/bin/uv run --no-project --with torch --with
transformers --with numpy python` for anything that needs torch.

## 10. Concerns and limits

1. **The gain is calibration-dependent by construction.** GPTQ compensates
   errors with respect to the *calibration* activations (32768 tokens of the
   train slice). It is scored on a **disjoint** eval slice, so the −0.45 PPL is
   genuine generalisation, not fitting — but a deployment whose input
   distribution is far from this corpus would see less. V3 has the same
   exposure through its salience, to a smaller degree.
2. **Build time doubles** (918 s → 1949 s for the model). Irrelevant to the
   board, relevant to anyone iterating on images.
3. **Weight error rises, and one tool in this repo will mis-rank V4 because
   of it** (§5). `ref/audit_ranges.py` reports a per-matrix Frobenius relative
   error for the W4 images (its section-2 column, the one that priced the
   max-rule → MSE-rule change at ~12%); on V4 that column rises — 5.510 →
   7.010 on `layers.0.linear_attn.in_proj_qkv`, and on every matrix sampled —
   so a re-run of that audit against a V4 image will read as a **regression**
   while the model is measurably better. GPTQ minimises `||(W-Wq)X^T||`, not
   `||W-Wq||`, and trades the second for the first by design. **Action item
   for Q10's decision table:** if V4 is adopted, `audit_ranges` needs two
   things. (a) It **cannot score a V4 image at all today**: it re-quantizes
   from the checkpoint rather than reading an image, and with the calibration
   plumb on it SystemExits (no `layer_idx` at `:361`, §8.1) — so it needs either that
   wiring or an image-reading mode. (b) Once it can, its Frobenius column must
   be labelled "not the objective for calibrated quantizers", or given an
   output-error column beside it; otherwise the next person to run it will
   file a bug against a working quantizer.
4. **`e` and `m` were asserted identical on the matrices measured, not proven
   invariant in general.** GPTQ cannot move them by construction (they are
   computed before the sweep), but the shared exponent is data, not format — a
   future variant that re-fits scales mid-sweep would break that.
5. **The V3 → V4h step is measured; its cause is a hypothesis** (§5).
6. **The fixed-point probe is a tie, not a confirmation** (§7). 85/108 vs
   V3's 86 on 108 teacher-forced steps. It rules out a fixed-point regression
   — clip-free, lower S_F saturation, same head `e`/`sh`, readable
   free-running text — and it does not, and at this size cannot, corroborate
   the float gain. Rank max is the one metric that moved the wrong way
   (68 vs 7; V2's was 911).
7. **Task 8's host finding still stands.** Nothing in this task ran on
   darthplagueis; the memtest recommendation of `../v3/V3.md` §6 is unchanged
   and still leads the gate-D presentation.
