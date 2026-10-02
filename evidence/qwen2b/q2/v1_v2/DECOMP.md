# Q2 / Task 5 — V1/V2 scoring and the weight-vs-datapath decomposition at 2B

Machine: darthplagueis. Model: Qwen3.5-2B, checkpoint header sha256
`ccba2c1f645fe59268f89ee7ea552e02ce6bf0c8a087bf332fb0e3bd99bfee9d`
(matches `evidence/qwen2b/q0/checkpoint_verify.md`). Golden cache
`tb/scripts_scratch/golden_bf16_2b.npz`, sha256 `853852e8e573…`, same header sha.
Corpus `ref/ppl_corpus_eval.txt`, sha256 `6bf4f8677a3b…`, window 512, batch 4,
24528 scored positions.

Every number below is quoted from a committed json or log in this directory;
derived figures (differences, percentages) are arithmetic on values cited in
the same row or table, e.g. the emb16+cw13 increment is A1 - A3.

## 0. What was measured, and the two config choices

`ref/perplexity_eval.py` measures **WEIGHT damage only** (production quantizers,
dequantized back into the HF float model). `ref/fidelity_check.py` measures
**weights + the fixed-point datapath** against the bf16 golden trajectory.
The ablation ladder joins them: `exact -> w4deq (float) -> fixed`.

Choice 1 — **the HW-complete weight set is what V1/V2 inject.** `all:` covers
only the seven W4A8 matvec classes, so V1/V2 name `dn_conv:cw13` and
`emb:emb16` explicitly, which makes the PPL rows price the weight set the
hardware actually ships. A W4-only control (`all:w4g128`, nothing else) was run
to price that increment separately — see Table A.

Be precise about what this does *not* fix. The float `w4deq` rows of Table B
carry **no** emb16 and **no** cw13 (`fidelity_check --ablate` uses the exact
float embedding lookup and leaves conv weights in float), while the fixed rows
quantize both unconditionally. So the emb16 + cw13 weight damage does **not**
cancel in `(fixed - w4deq)` — it leaks into the datapath bucket. What bounds
that leak is measurement, not construction: A1 - A3 in Table A puts the whole
emb16 + cw13 increment at -0.0003 PPL, and the fixed runs show the emb table
using |q|max 202 (S=4) / 404 (S=8) of 32767. So the leak is **bounded in
magnitude and negligible; its sign is not established** — A1 - A3 is itself a
small *improvement*, so adding emb16 + cw13 could as easily deflate the
datapath bucket as inflate it. Either way it cannot move the §2 verdict, whose
margin is 1-7 top-1 steps against a weight-damage term this cannot plausibly
reach.

Choice 2 — **`--res-scale 8` on every emb16 run** (controller ruling: the study
scores what the hardware ships, Q4.11). Held fixed across V1 and V2 and
recorded in `res_scale` in both jsons. The W4-only control carries
`res_scale 1.0` because res_scale has no effect without emb16 (a power-of-two
rescale leaves every W4 image bit-identical; `perplexity_eval.check_res_scale`
rejects the combination outright).

Reconciliation with §3, which recommends **S=4** for the fixed-point path:
adopting S=4 would move the emb table from Q4.11 to Q5.10 — one bit coarser,
i.e. a 2x larger quantization step (|q|max 202 vs 404 of 32767) — so V1/V2
would strictly need re-scoring to stay HW-exact. Order-of-magnitude bound on
that re-score: roughly **2x** the measured emb16 + cw13 increment, i.e. ~0.0006
PPL against a 1.83 PPL weight-damage signal. V1/V2 are reported at S=8 per the
ruling and are not re-run; if the controller freezes S=4, the PPL numbers stand
to well within that bound.

## Table A — PPL, weight damage only (float compute)

| # | config | inject | res_scale | PPL | vs bf16 | bits/weight | json |
|---|--------|--------|-----------|-----|---------|-------------|------|
| A0 | 2B bf16 anchor | *(none)* | 1 | **12.346298** | — | 16.000 | `../../q1/ppl_2b_bf16.json` |
| A1 | **V1** | `all:w4g128,dn_conv:cw13,emb:emb16` | 8 | **14.176885** | +1.830587 (+14.83%) | 6.742 | `ppl_v1.json` |
| A2 | **V2** | `all:w4g64,dn_conv:cw13,emb:emb16` | 8 | **13.744231** | +1.397933 (+11.32%) | 6.753 | `ppl_v2.json` |
| A3 | W4-only control | `all:w4g128` | 1 | 14.177184 | +1.830886 (+14.83%) | 6.742 | `ppl_2b_w4g128_only.json` |
| A4 | 0.8B bf16 anchor | *(none)* | 1 | 17.480045 | — | 16.000 | `../../q1/ppl_08b_bf16.json` |
| A5 | 0.8B W4 | `all:w4g128` | 1 | 22.432251 | +4.952206 (+28.33%) | 7.367 | `../../q1/ppl_08b_w4g128.json` |

Three readings:

1. **g64 buys 3.05 % of PPL for 0.011 bits/weight.** V2 − V1 = −0.432654 PPL
   (−3.05 % relative) at +0.0105 avg bits/weight (6.7420 → 6.7525). That is
   the cheapest quality on the board so far.
2. **emb16 + cw13 are free.** A1 − A3 = **−0.000299 PPL** (−0.002 %). Both
   evaluations are deterministic, so that difference is exact, not scatter: it
   is a real but negligible improvement, and the two runs differ only in the
   emb table and the conv weights. The int16 Q4.11 embedding table and the
   Q2.13 conv weights cost nothing that matters at this resolution.
   Corroborated inside the fixed-point runs: the emb table only reaches
   |q|max 202 of 32767 at S=4 and 404 at S=8, i.e. it is nowhere near its rail.
3. **The 2B model takes W4 roughly half as badly as the 0.8B.** +14.8 %
   (A3/A0) versus +28.3 % (A5/A4) for the identical injection. W4 damage
   shrinks with model size, exactly the direction the Track Q hypothesis needs.

## Table B — the ablation ladder (108 teacher-forced steps = 4 prompts x 27)

`ref/fidelity_check.py`, golden-cache teacher forcing, `--ntok 24 --free-ntok 24`.
Rows 1-5 are float (`--ablate`, `ablate_2b.log`); rows 6-9 are the full
fixed-point FxRunner (one json each). `mse` is the production group-scale rule
since Phase 1A; `max` is the historical rule and is shown only to price the rule.

| # | row | quantizer | top1 /108 | rank med | rank max | top5 ovl | free-run text | source |
|---|-----|-----------|-----------|----------|----------|----------|---------------|--------|
| B1 | exact float | checkpoint weights | **108/108** | 0.0 | 0 | — | reproduces the bf16 golden text verbatim on all 4 prompts | `ablate_2b.log` |
| B2 | w4deq g128 | mse (production) | **93/108** | 0.0 | 8 | — | 4/4 fluent, content drifts; p1 `<think>` collapses to empty (format signal, see below) | `ablate_2b.log` |
| B3 | w4deq g128 (2nd impl) | mse | 93/108 | 0.0 | 8 | — | identical to B2 | `ablate_2b.log` |
| B4 | w4deq g64 | mse (production) | **94/108** | 0.0 | 3 | — | 4/4 fluent | `ablate_2b.log` |
| B5 | w4deq g64 | max (historical) | 91/108 | 0.0 | 15 | — | 4/4 fluent | `ablate_2b.log` |
| B6 | fixed g128 S=4 | mse | **80/108** | 0.0 | 9 | 3.39 | 4/4 readable, 3/4 clean; p1 restates its answer | `fixed_g128_S4.json` |
| B7 | fixed g128 S=8 | mse | **83/108** | 0.0 | 8 | 3.49 | **3/4 readable, 2/4 clean**; p4 collapses to `** ** **`, p1 repeats a phrase | `fixed_g128_S8.json` |
| B8 | fixed g64 S=4 | mse | **80/108** | 0.0 | 911 | 3.46 | 4/4 readable, 3/4 clean; p1 hard repetition loop | `fixed_g64_S4.json` |
| B9 | fixed g64 S=8 | mse | **86/108** | 0.0 | 1312 | 3.56 | 4/4 readable, 3/4 clean; p4 restarts one clause | `fixed_g64_S8.json` |
| B10 | fixed g128 S=16 | mse | **ABORT** | — | — | — | — | `fixed_g128_S16.log` (see §3) |

Scored to one standard: *readable* = fluent, on-topic English or valid code;
*clean* = readable with no repetition artifact. **No fixed configuration is
artifact-free.** B6, B8 and B9 each carry exactly one repetition artifact and
stay 4/4 readable; B7 is the only one that loses a prompt outright (p4).

**`<think>` format signal** (the brief's named check). The bf16 golden answers
p1 and then opens `<think>` with content (`\nThinking Process:\n\n1.  **Analyze`).
B2/B3/B4 answer correctly but collapse the block to an empty `<think>\n\n</think>`
before continuing in prose; B9 re-opens it with content
(`<think>\nThe user is asking a simple fact-checking question`). These are
**format** differences at a genre boundary, scored as such — not semantic
degradation, and not counted against the text verdicts above.

Per-prompt top-1 (out of 27 each), p1..p4:

| row | p1 | p2 | p3 | p4 |
|-----|----|----|----|----|
| B1 exact | 27 | 27 | 27 | 27 |
| B2 w4deq g128 mse | 26 | 24 | 22 | 21 |
| B4 w4deq g64 mse | 26 | 20 | 25 | 23 |
| B5 w4deq g64 max | 26 | 19 | 23 | 23 |
| B6 fixed g128 S=4 | 23 | 15 | 20 | 22 |
| B7 fixed g128 S=8 | 23 | 19 | 20 | 21 |
| B8 fixed g64 S=4 | 24 | 15 | 21 | 20 |
| B9 fixed g64 S=8 | 25 | 18 | 21 | 22 |

Two integrity checks fell out of this table for free:

* **B1 = 108/108 with rank max 0.** The numpy float reference (`layer_ref`)
  reproduces the torch golden's argmax at every one of the 108 steps *and*
  its free-run text verbatim on all four prompts (compare
  `evidence/qwen2b/q0/golden_2b.md` §3). The float anchor contributes exactly
  zero to the loss budget at 2B, so the whole ladder below it is attributable.
* **B2 = B3.** Two independent implementations of the g128 mse W4 image — the
  production `layer_fixed.quant_linear(mse_scale=True)` and
  `fidelity_check.w4_roundtrip(rule="mse")` — agree on all 108 argmaxes, all
  ranks and all four free-run texts.

## 1. The decomposition

    weight damage   = exact - w4deq        (float compute both sides)
    datapath damage = w4deq - fixed        (same W4 weights both sides)

| wire group | res_scale | weight damage | datapath damage | total |
|------------|-----------|---------------|-----------------|-------|
| g128 | S=4 | 108→93 = **−15** | 93→80 = **−13** | −28 |
| g128 | S=8 | 108→93 = **−15** | 93→83 = **−10** | −25 |
| g64  | S=4 | 108→94 = **−14** | 94→80 = **−14** | −28 |
| g64  | S=8 | 108→94 = **−14** | 94→86 = **−8**  | −22 |

**At 2B the W4 WEIGHT format is the larger of the two losses in every measured
cell — 14-15 top-1 steps of 108 versus 8-13 for the entire fixed-point
datapath — and the datapath never exceeds it (it ties once, at g64 S=4).**

Secondary metrics, same direction with one dissent:

* **rank median** is 0.0 for every row in the table, weight and datapath
  alike — at 2B the golden token is the fixed-point model's own top pick in
  the median step even after both damages. No discrimination here.
* **rank max**: weight damage moves it 0 → 8 (g128) and 0 → 3 (g64).
  Datapath moves it 8 → 8/9 at g128 (negligible) but 3 → 911/1312 at g64 —
  the one signal in this study that points the other way. It is a **step-0**
  artifact, and step 0 is the single highest-entropy position in the whole
  measurement: it predicts from a ONE-token context (`p1_seq[0] = 760`,
  `'The'`), not from the 4-token prompt (that is step 3). Both g64 outliers sit
  there (911 and 1312 at p1 step 0); neither g128 config has a step-0 outlier
  at all (their maxima are 9 at p2 step 26 and 8 at p3 step 12). Cross-check
  against the shipped 0.8B production run: the same step-0 blow-up is already
  there — rank 136 at p1 step 0 and 845 at p2 step 0
  (`evidence/stage5/fidelity_mq15_prod.log`). It is a structural property of
  ranking a one-token context, not a 2B or g64 signal, and it is why rank
  *median* (0.0 everywhere) is the metric that carries information here.
* **text**: weight damage changes *content* while staying fluent (different
  name, different story, valid but different imports). Datapath damage adds
  *repetition* (B6 p1 restates, B7 p4 collapses into `** ** **`, B8 p1 loops a
  sentence three times) but never gibberish, never cross-lingual drift, never
  a dead model. On text alone the datapath is arguably the uglier of the two.

Cross-model context (do not over-read): `docs/FIDELITY_REDESIGN.md` records the
0.8B ladder as exact 24/24 → w4deq 12/24 → fixed 0/24, and post-redesign
production fixed = 15-16/24. That w4deq row predates Phase 1A and used the
**max** rule, so it is not the same quantizer as B2/B4 here — which is exactly
why 0.8B "fixed" can sit above 0.8B "w4deq". The 2B ladder above is internally
consistent (mse everywhere); only it should be used for the ratio.

## 2. THE V6 DECISION

> **The V6 axis does NOT open.** It opens iff datapath damage > weight damage
> on both fidelity metrics and on text quality. At 2B the datapath loss is
> 8-13 top-1 steps against the weight format's 14-15 in every configuration
> measured, rank median is 0.0 on both sides, and the only metric that favours
> the datapath hypothesis (rank max at g64) rests on one step of one prompt.
> Precision work in the RTL is therefore not the binding constraint at 2B, and
> no V6 modeling task is added before Task 10.

Practical consequence for the plan: the cheapest remaining quality is on the
**weight** axis — g64 buys 3.05 % of PPL for 0.011 bits/weight (A1→A2), on the
float axis where that decision is made.

**Whether the fixed-point path banks that gain depends on res_scale, and at the
recommended S=4 it does not.** At S=8 it does: B7→B9 is 83→86 of 108. At S=4,
g64 buys **zero** top-1 steps (B6→B8, 80→80) and is *worse* on text — B8's p1
falls into a hard repetition loop where B6's p1 merely restates its answer.
Anyone adopting §3's S=4 recommendation should read the g64 case as "free on
PPL, neutral on fixed-point top-1, slightly worse on text", not as the S=8
result. The two knobs interact, which is why they were swept together.

## 3. res_scale is a per-model calibration — the 2B sweep

`--res-scale 8` is the 0.8B production value. At 2B it saturates the int16
residual. Sweep (`--ntok 24 --free-ntok 24`, g128 unless noted):

| res_scale | top1 /108 | \|x\|max (rail 32768) | residual clips | S_F sat | verdict |
|-----------|-----------|----------------------|----------------|---------|---------|
| 4 | 80/108 | 23165 (71 %) | **0** | 414 | clip-free, headroom left |
| 4 (g64) | 80/108 | 26465 (81 %) | **0** | 391 | clip-free |
| 8 | 83/108 | **32768 (rail)** | 13 | 425 | best top-1, but clipping |
| 8 (g64) | 86/108 | **32768 (rail)** | 22 | 415 | best top-1, but clipping |
| 16 | — | — | — | — | **run aborts**, see below |

**Recommendation: S=4 for 2B, with S=8 recorded as the higher-scoring but
saturating alternative — a controller call, not settled here.** S=8 wins on
top-1 by 3-6 steps on this 108-step sample, but it reaches the int16 rail and
clips 13-22 times; clipping is a hard nonlinearity whose incidence grows with
context length, so its advantage on 24 generated tokens is not evidence that
it holds at 512. S=4 keeps 29 % headroom with zero clips. Note the embedding
table is not the binding term either way (|q|max 202 at S=4, 404 at S=8, of
32767) — what saturates is the *accumulated residual*, which is what scales
with hidden size.

**S=16 aborts, and the abort is a HOST TRANSIENT, not a property of S=16.**
`fixed_g128_S16.log`: bare `AssertionError` at `ref/w4a8_ref.py:161`, the int32
accumulator guard `assert np.abs(acc).max() < (1 << 31)`. See §3.1 — this one
matters beyond S=16 and is written up as its own finding.

### 3.1 The S=16 abort is a transient host fault (READ THIS)

> **SECOND OCCURRENCE, 2026-08-13 (track R task R-b).** The same guard —
> `ref/w4a8_ref.py:161`, `assert np.abs(acc).max() < (1 << 31)` — tripped
> once on darthplagueis during the first `ref/scripts/regen_gate.sh` run of
> that task (0.8B, `--res-scale=8`, decode step 5), and then did not
> reproduce: three later runs of the identical tree, plus the reviewer's on
> a different interpreter, all rebuilt the gold stream byte-identically
> (sha `a69864d2…`). Both occurrences were under heavy concurrent load.
> This section's diagnosis is therefore not S=16-specific — see
> `.superpowers/sdd/2026-08-12-qwen2b-track-r/task-5-report.md` §8.1.

Every number in this section is quoted from a committed file; the file is named
on each line. Three S=16 attempts were made — the scored run (`fixed_g128_S16.log`)
and two instrumented reproductions (`fixed_g128_S16_diag.log`,
`fixed_g128_S16_diag_retry.log`) driven by the committed wrapper
`diag_s16_wrapper.py`, which monkeypatches `layer_fixed.matvec_y32` without
touching any repo source file.

Provenance, stated exactly: the committed wrapper is the final version, the one
that produced `fixed_g128_S16_diag_retry.log`. `fixed_g128_S16_diag.log` was
produced by the same wrapper with the same `sys.argv` before the
traceback-print and retry lines were added to its `except` handler — code that
runs only *after* a failure, so the path up to the abort was identical in both
runs. The logs record the wrapper's then-current path under the session
scratchpad; the file is committed here verbatim.

1. **The guard cannot legitimately trip.** It is
   `assert np.abs(acc).max() < (1 << 31)` (`ref/w4a8_ref.py:161`) on the
   per-group dot product of int4 weights with an int8 activation. Its
   arithmetic maximum is `g * 8 * 127 = 130048` — four orders of magnitude
   below the guard.
2. **The inputs were in range and the recomputed result passes.** Caught at
   the failure, in the same frame, from the same arrays
   (`fixed_g128_S16_diag.log`): `w4 (6144,2048) int8 min -8 max 7`,
   `x8 (2048,) int8 min -107 max 97`, `m min 871 max 15872`, `sh=6 g=128`,
   `|acc|max = 2311`, `|y|max = 648709` — both guards pass with room to spare
   (the acc guard by ~6 orders of magnitude, the y guard by ~3.5). The retry run agrees on the shape of the finding with different
   values (`fixed_g128_S16_diag_retry.log`): `x8 min -87 max 90`,
   `m min 338 max 9458`, `|acc|max = 1750`, `|y|max = 601147`.
3. **The identical call succeeds on retry.** `fixed_g128_S16_diag_retry.log`
   ends with `RETRY of the identical call SUCCEEDED` — the wrapper re-invoked
   the unmodified `w4a8_ref.matvec_y32` on the same objects immediately after
   catching its AssertionError.
4. **Two runs with byte-identical arguments abort at different places.** The
   two diag logs differ in the weight matrix that tripped (`m max 15872` vs
   `m max 9458`, i.e. different matrices — both are 6144×2048 at 2B) and in
   the activation seen. The pipeline is fully deterministic, so identical
   inputs cannot select different call sites.
5. **The reduction itself does not fault on an idle host.** 6 processes ×
   240 s, 5624 iterations (the sum of the log's six per-process lines) at the
   same shape and dtypes. Each iteration checks
   the production guard, the arithmetic bound above, and an **independent
   re-reduction of the same operands compared elementwise**: **0 anomalies**
   (`int64_reduction_soak.log`, `int64_reduction_soak.py`). This is a null
   result — it says the reduction did not misbehave under *these* conditions
   (idle host, minutes), which is exactly the contrast with (3) and (4).

Conclusion: a transient wrong result from a large int64 reduction under
sustained heavy load, not a numerical property of `res_scale 16`. The load is
not an anecdote — it is visible in the aborting run itself: identical
quantization work took **225.2 s** (LM head) and **444.6 s** (24 layers) in
`fixed_g128_S16.log`, against **51.4 s / 135.7 s** and **51.2 s / 136.4 s** in
the two diag runs on a quiet box — a 3-4x contention signature.

Why res_scale cannot be the mechanism, in two independent steps:

* **The guard is unreachable for these dtypes at any S.** `w4` is int4-valued
  and `x8` is int8 by construction, so `|acc| <= g * 8 * 127 = 130048` for
  *any* inputs whatsoever — 2^31 is not reachable by a correct evaluation, and
  no property of the activations can change that.
* **A power-of-two residual rescale does not even change the matvec input.**
  Every W4A8 matvec quantizes its input with `dyn_quant_i8`
  (`ref/fixedpoint.py:24-33`), a shift-only absmax requant: scaling `x16` by
  2^k moves the chosen shift `e` by exactly k and leaves `x8` **bit-identical**
  (`ref/layer_fixed.py:864-866` relies on the same invariance for the attention
  output path). So S=4 → S=8 → S=16 is not a lever on `x8` at all, modulo the
  int16 residual clipping that S=8 already incurs.

Which specific matrix tripped is *not* determinable from the diag logs — their
tracebacks start at the wrapper frame. The scored run's traceback does name its
call site:
`mlp_fx` → `qm["up"]`, `ref/layer_fixed.py:990`. At 2B `gate`, `up` and
`in_qkv` are all 6144×2048, so the diag logs' shapes cannot disambiguate, and
no matrix is named for them here.

**What this costs the study, and why the delivered numbers still stand.** A
host that can silently produce a wrong reduction can in principle corrupt a
result that does *not* trip a guard. Five independent reproducibility checks
in this task all passed, which is what the numbers above rest on:

| check | result |
|-------|--------|
| B1 exact-float vs the torch golden | 108/108 argmax + 4/4 texts verbatim |
| B2 vs B3, two independent W4 g128 mse implementations | identical on all 108 steps, ranks and texts |
| `fixed_g128_S4` vs the earlier sweep job, separate processes | identical per-prompt top-1 and free text |
| `fixed_g64_S4` vs the earlier sweep job, separate processes | identical per-prompt top-1 and free text |
| `fixed_g128_S8` / `fixed_g64_S8` vs `*_S8_rerun`, separate processes | **identical**: top-1, ranks, argmaxes, free text, `resid_max`, clips, `s_sat` |

Recommended follow-ups (controller call, outside this task): a memtest /
under-load arithmetic soak on darthplagueis before the next long numeric
campaign, and a re-run of S=16 if that data point is ever wanted. S=16 is out
of contention on its own merits regardless — S=8 already rails the residual.

## 4. Traceability index

| claim | file |
|-------|------|
| V1 PPL 14.176885 | `ppl_v1.json` / `ppl_v1.log` |
| V2 PPL 13.744231 | `ppl_v2.json` / `ppl_v2.log` |
| W4-only control 14.177184 | `ppl_2b_w4g128_only.json` / `.log` |
| ablation rows B1-B5 | `ablate_2b.log` |
| fixed g128 S=4 / S=8 | `fixed_g128_S4.{json,log}` / `fixed_g128_S8.{json,log}` |
| fixed g64 S=4 / S=8 | `fixed_g64_S4.{json,log}` / `fixed_g64_S8.{json,log}` |
| S=16 abort + diagnosis | `fixed_g128_S16.log`, `fixed_g128_S16_diag.log`, `fixed_g128_S16_diag_retry.log`, `diag_s16_wrapper.py` |
| int64 reduction soak (null result) | `int64_reduction_soak.log`, `int64_reduction_soak.py` |
| rank-max step-0 artifact in the 0.8B baseline | `../../../stage5/fidelity_mq15_prod.log` |
| S=4 determinism cross-check | `fixed_g128_sweepjob_partial.log`, `fixed_g64_sweepjob_partial.log` |
| S=8 determinism cross-check | `fixed_g128_S8_rerun.{json,log}`, `fixed_g64_S8_rerun.{json,log}` |
| bf16 anchors, 2B and 0.8B | `../../q1/ppl_2b_bf16.json`, `../../q1/ppl_08b_bf16.json`, `../../q1/ppl_08b_w4g128.json` |
| bf16 golden reference texts | `../../q0/golden_2b.md` |

### Note on the two `*_sweepjob_partial.log` files

The S=4 configs were first produced by two `--res-scale 4,8,16` sweep jobs that
run the configs serially (~54 min each) and only write their json after all
three. Those jobs were stopped after their S=4 configs completed and the sweep
was re-sharded into one process per config so the five configs could run in
parallel. The partial logs are kept because they are an unplanned determinism
check: the re-sharded `fixed_g128_S4` and `fixed_g64_S4` runs reproduce the
partial jobs' per-prompt top-1 (23/15/20/22 and 24/15/21/20) and free-run text
exactly, in a different process, with different co-tenants on the machine.

### Runtimes (darthplagueis, contended — timings are not benchmarks)

PPL 2B: build 333-683 s, eval 264-429 s per run. Fixed-point config at 2B:
~445 s to quantize 24 layers + ~225 s for the LM head + ~3250-4000 s for
216 decode steps (4 prompts x (27 teacher-forced + 27 free-running)).
Float ablation: 181 s (exact) to 815 s (a W4 config) per row.
