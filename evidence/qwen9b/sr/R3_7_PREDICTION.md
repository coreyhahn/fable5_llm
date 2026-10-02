# R3-7 — the PREDICTION: the r3 chip-TB expectation, committed before any r3 chip-TB run

Task R3-7 of the R3 campaign (MOVX broadcast, form (a); plan `docs/superpowers/plans/2026-09-29-r3-broadcast.md`,
Task R3-7, with the controller's addendum and its amendment for R3-5's numbers). No RTL, no chip-TB run and no
board action happened here. The one numeric run was made on snoke through `evidence/qwen9b/sr/sr_run.sh`, log
n2900. **Every number below is MODEL.** No number here names a chip-TB or board run of an r3 stream, because none
has happened. Labels: **E** printed by a committed run, **D** derived by a committed script run on snoke,
**T** transcribed, **S** stated by a cited source.

**Ordering.** The tool was committed at 7cd851c before its first use. The prediction log and this document are
committed before any chip-TB run that executes a broadcast, as R3-9a's Step 4 and R3-9b's Step 1 require. The
plan's Step 2 asks for the controller's review of these numbers. That review happens on this commit and must finish
before the first r3 measurement.

## 1. The prediction — the s1 token-4 body window of the r3 stream on the chip TB

The quantity is SR13a's (`SEQ_TIMELINE tcyc 4` of the s1 timeline run). The base is SR13a's MEASURED r2 window,
**26,171,253 cyc** (**T**, `evidence/qwen9b/sr/n1349e_sr13a_chip_s1_r2_timeline.log:56`).

| form | value (cyc) | how | cite (D) |
|---|---|---|---|
| **P-A (PRIMARY): absolute, corrected-model saving** | **24,127,093** (96.508 ms) | 26,171,253 − (pred_mk r2 26,183,590 − pred_mk r3 24,139,430 = 2,044,160) | `evidence/qwen9b/sr/n2900_r3_predictions.log:28` |
| P-B: absolute, census saving | 24,127,093 (P-B − P-A = +0) | 26,171,253 − (replay_mk r2 26,146,927 − replay_mk r3 24,102,767 = 2,044,160) | `evidence/qwen9b/sr/n2900_r3_predictions.log:29` |
| P-C: the pass's own corrected r3 prediction (SR13a's form) | 24,139,430, placement band 24,122,218 … 24,139,430 | pred_mk r3; the band is SR11b's 17,212-cyc DMA stall, absorbed by a FENCE wait or not | `evidence/qwen9b/sr/n2900_r3_predictions.log:30` |
| R2's offset carried onto P-C | 24,127,093 (absolute, = P-A) / 24,128,056 (relative, −0.0471 %) | measured r2 − corrected r2 = −12,337 cyc | `evidence/qwen9b/sr/n2900_r3_predictions.log:31` |
| ratio forms (informational, no band) | 24,128,056 (corrected ratio, +0.004 % vs P-A); 24,125,191 (census ×1.0848, −0.008 %) | 26,171,253 × r3/r2 | `evidence/qwen9b/sr/n2900_r3_predictions.log:32` |

**All the forms agree to within 0.051 %.** The reason is that the corrected and census conventions give the same
r2→r3 saving, **2,044,160 cyc = 8.177 ms/token**. The pred − replay excess is +36,663 at both r2 and r3
(`evidence/qwen9b/sr/R3_5_PASS.md` §5.2), so P-A and P-B coincide. P-C sits exactly R2's measured-minus-model
residual (−12,337) above P-A. The expected saving rests on the **unmeasured one-window pricing** of a form-(a)
broadcast (R3-4, `evidence/qwen9b/sr/R3_4_COST.md` §1 caveat 3). R3-9b is its first test
(`evidence/qwen9b/sr/n2900_r3_predictions.log:33`).

Inputs (every one read back from its committed line and cross-checked, 10 of 10 PASS,
`evidence/qwen9b/sr/n2900_r3_predictions.log:16-25`):
* pred_mk and replay_mk: r2 from `evidence/qwen9b/sr/n1165_reorder_s1_B_r2.log:50` and
  `evidence/qwen9b/sr/n1165_reorder_s1_B_r2.log:56`; r3 from `evidence/qwen9b/sr/n2720_r3_5_reorder_s1_B_r3.log:49`
  and `evidence/qwen9b/sr/n2720_r3_5_reorder_s1_B_r3.log:59`.
* The census rows and saving are from `evidence/qwen9b/sr/n1600_sr16_r3_census.log:23`,
  `evidence/qwen9b/sr/n1600_sr16_r3_census.log:26` and `evidence/qwen9b/sr/n1600_sr16_r3_census.log:36`; R3-4's net is
  `evidence/qwen9b/sr/n2606_r3_4_derive.log:24`.
* The stall is `evidence/qwen9b/sr/n1182_sr11b_r2_derive.log:28`.
* The stream shas are checked against the lines that wrote them: `evidence/qwen9b/sr/n1165_reorder_s1_B_r2.log:58`
  and `evidence/qwen9b/sr/n2720_r3_5_reorder_s1_B_r3.log:61`.

### 1.1 Bands on P-A (SR5b's) and the STOP rule

The verdict is judged on |measured / P-A − 1| (**D**, `evidence/qwen9b/sr/n2900_r3_predictions.log:35-41`):

| verdict | window (cyc) | as a measured saving, 26,171,253 − measured (cyc) |
|---|---|---|
| **HELD**, ±0.5 % | 24,006,457.5 … 24,247,728.5 (±120,635.5) | 1,923,525 … 2,164,795 |
| **HELD LOOSELY**, ±2 % — attribute by class | 23,644,551.1 … 24,609,634.9 (±482,541.9) | 1,561,618 … 2,526,702 |
| **MISSED**, outside ±2 % | — | — |

* **A HELD LOOSELY result must be attributed by class before R3-10 launches.** The classes are MOVX, FENCE (with
  the dn_out sub-class apart) and CMD, read from the s1 r3 timeline. §2 gives the reference.
* **Outside ±2 % → STOP.** The campaign stops before the full build (R3-10), so no Vivado time is spent, and the
  controller returns to the user. The ±2 % band is the plan's rule (Global Constraints, "Predictions before
  measurements").
* **How a DMA stall moves the result.** One more or one fewer 17,212-cyc DMA stall moves the window by 0.071 % of
  P-A, so the HELD band is 7.0 such stalls wide on each side (`evidence/qwen9b/sr/n2900_r3_predictions.log:39`).
  SR16's bound (eight more stalls ≈ 7 % of the saving, `evidence/qwen9b/sr/SR16_R3_DECISION.md:172-175`) therefore
  sits just outside HELD and well inside LOOSE.
* **MODEL context:** ×1.0847 against r2 measured, ×1.3589 against the shipped body, 9.910 tok/s board-scaled by
  OV1's uniform factor (MODEL, `evidence/qwen9b/sr/n2900_r3_predictions.log:42`).

### 1.2 s2–s4 — the whole run

**Criterion.** Each seed's measured r3 / r2 must be < 1. It must also be within ±0.5 % of s1's r3 / r2, and r3 /
shipped must be within ±0.5 % of s1's (the SR13a criterion; outside ±0.5 % attribute, outside ±2 % STOP;
`evidence/qwen9b/sr/n2900_r3_predictions.log:45`). The bases are SR13a's measured r2 cycles, 157,010,908 /
157,011,556 / 157,011,490 / 157,010,986 (**T**, `evidence/qwen9b/sr/n1349a_sr13a_chip_s1_r2.log:30`,
`evidence/qwen9b/sr/n1349b_sr13a_chip_s2_r2.log:30`, `evidence/qwen9b/sr/n1349c_sr13a_chip_s3_r2.log:30`,
`evidence/qwen9b/sr/n1349d_sr13a_chip_s4_r2.log:30`).

**Predicted.** Every segment of every seed saves 2,044,160 in both conventions. Each run has six token windows,
so each saves 12,264,960 cyc. The predicted whole runs are **144,745,948 / 144,746,596 / 144,746,530 /
144,746,026** cyc, which is 96.497–96.498 ms/token, **r3 / r2 = 0.921885** on every seed and r3 / shipped =
0.735846 (×1.3590). s2–s4 are +0.0000 % from s1 on both ratios (**D**,
`evidence/qwen9b/sr/n2900_r3_predictions.log:46-52`).

## 2. The per-class expectation, token 4, s1 (the attribution's reference)

The pass's own schedule was rebuilt at r2 and at r3. Each rebuild reproduces its committed replay_mk and pred_mk
exactly, and each emitted body equals the stream on disk record by record: r2 40,171 / 40,171, r3 39,784 / 39,784
(**D**, `evidence/qwen9b/sr/n2900_r3_predictions.log:61`, `evidence/qwen9b/sr/n2900_r3_predictions.log:68`). The
expected r3 value of each class is r2's MEASURED class (SR13a, `evidence/qwen9b/sr/n1349g_sr13a_derive.log:69-81`)
plus the model's r2→r3 delta for that class (**D**, `evidence/qwen9b/sr/n2900_r3_predictions.log:69-84`):

| class | records r2 → r3 | model delta | r2 measured | **r3 expected** |
|---|---|---|---|---|
| MOVX | 516 → 129 | −2,427,816 | 3,237,088 | **809,272** |
| FENCE | 1,370 → 1,370 | **+383,656** | 8,987,848 | **9,371,504** |
| CMD + ARG | 35,284 | 0 | 10,730,078 | 10,730,078 |
| MOVY / LDC / MVGO / EMB / CSRWR / XOP / JMP / AMAXL | unchanged | 0 | 2,847,256 / 320,125 / 43,840 / 4,662 / 264 / 36 / 39 / 17 | the same |
| sum | | −2,044,160 | 26,171,253 | **24,127,093 = P-A** |

* **The MOVX class** is the census's siblings removed (387 of 516, 75.00 %).
* **The FENCE class** absorbs the census's lane-idle rise. The four channels' streams no longer overlap the
  removed sibling windows, so the lane waits on them at the next FENCE instead. This matches n1600's split
  exactly: removed 2,427,816, idle +383,656 (`evidence/qwen9b/sr/n1600_sr16_r3_census.log:36`).
* **Every other class** is predicted unchanged to the cycle, as R2 left every class but FENCE unchanged against R1
  (`evidence/qwen9b/sr/n1349g_sr13a_derive.log:103-113`).

## 3. The one-window assumption, stated for measurement (reported, not banded)

**The assumption.** A form-(a) broadcast MOVX costs one unicast MOVX window of its length, and its three siblings
cost zero (R3-4; spec §1.3 (a)).

**The measure.** The mean broadcast window divided by the mean r2 unicast window of the same length. It is
expected to be 1.00 plus the broadcast's fixed extra, which is three more closing STATUS reads (R3-8's X_STATW
walk, `rtl/seq_movers.sv:712-715`). R3-9a's coverage item (5) and R3-9b's s1 timeline measure it.

**The denominator,** from SR13a's r2 timeline CSV, whose sha256 f2e24609… matches the committed
`evidence/qwen9b/sr/sr13a_timeline_model_9b_s1_reordB_r2.csv.sha256` (**D**,
`evidence/qwen9b/sr/n2900_r3_predictions.log:89-93`):

| length (words) | r2 unicast MOVX, token 4 | mean measured window (min … max) | r3 broadcasts of that length | expected broadcast lane work at one window |
|---|---|---|---|---|
| 4,096 | 388 | 4,216.99 (4,216 … 4,219) | 97 | 409,048 |
| 12,288 | 128 | 12,507.00 (12,507 … 12,507) | 32 | 400,224 |

**Expected result.** The r3 body's 129 MOVX are all broadcasts, the census's 129 carriers. At exactly one window
the MOVX class is **809,272 cyc, 25.00 % of r2's measured 3,237,088**. That is a fall of 2,427,816 (75.00 %: the
387 siblings of 516), **plus 129 × the fixed extra**, which R3-9a measures
(`evidence/qwen9b/sr/n2900_r3_predictions.log:94`).

**What the fixed extra costs.** It enters 129 times per token. Against HELD's ±120,635-cyc half-width it matters
only if it reaches hundreds of cycles per broadcast, far more than three STATUS reads should cost. A miss would
therefore more likely come from the lockstep push rate, back-pressure or the stream overlap than from the closing
reads.

## 4. The r3 chat images — the formula (the number is left for R3-9b's brief)

R3-6's r3 image pins (`evidence/qwen9b/sr/sr13b_r2_pins.py` at `--rtl r3`) were **not committed** when n2900 ran.
Per the addendum, the formula and its inputs are stated here and the number is not waited for
(`evidence/qwen9b/sr/n2900_r3_predictions.log:102`). The tool takes R3-6's log as its optional --r3-pins-log argument and prints the
numbers when re-run under a new log name.

* **The chip TB (R3-9b Step 4).** No r2 chat image has ever run on the chip TB (SR15 §4), so the measured previous
  rung is SR5b's r1:
  **P-chat(kind) = SR5b's measured r1 image − (r1 static replay − r3 static replay)**. The same static model
  prices both sides, as SR15's P1′ did. The inputs (**T**/**E**, `evidence/qwen9b/sr/n2900_r3_predictions.log:97`):
  * r1 measured per launch: lite 25,221,328 … 25,228,270 and full 27,173,524 … 27,178,738
    (`evidence/qwen9b/sr/n588_sr5b_chat_compare.log:41`, `evidence/qwen9b/sr/n588_sr5b_chat_compare.log:43`);
  * r1 static replay: 25,195,119 / 27,135,354 (`evidence/qwen9b/sr/n601_r1_pins.log:9`,
    `evidence/qwen9b/sr/n601_r1_pins.log:15`);
  * r2 static replay / corrected: 24,341,703 / 24,377,574 (lite) and 26,131,018 / 26,168,056 (full)
    (`evidence/qwen9b/sr/n1351_sr13b_r2_pins.log:9`, `evidence/qwen9b/sr/n1351_sr13b_r2_pins.log:15`).

  The r1→r2 part is already known: 853,416 (lite) and 1,004,336 (full) cyc. It implies an r2 chip-TB image of
  24,367,912 … 24,374,854 / 26,169,188 … 26,174,402, which was never measured
  (`evidence/qwen9b/sr/n2900_r3_predictions.log:100-101`). **The r2→r3 part awaits R3-6's pins.**
* **The board (R3-11 P1′, the plan's formula; its number is R3-11's).** n1508 − (r2 corrected static − r3
  corrected static) per image kind. These are the corrected makespans, per SR15 review M2
  (`evidence/qwen9b/sr/SR15_R2_BOARD.md:184`).
* **The chat and stream ladders are quoted separately, always.** The stream's 8.177 ms/token is not a chat
  prediction.

## 5. NEXT_SESSION.md §8

The §8 heading line alone was rewritten in place (line-count neutral, 1 line changed, 1,562 lines before and
after). "the sequencer RTL round's R3 ruling, PENDING" now reads "the sequencer RTL round's R3 ruling: A — form (a),
the direct x-push bus (the user, 2026-09-29)". The heading's update stamp is now R3-7's. §8's body is left to
R3-12, per the controller's addendum (judgment call 3).

## 6. What this does NOT establish

* **Anything measured about r3.** Every number above is MODEL: the census windows, R3-4's one-window pricing and
  the pass's corrected convention, anchored on SR13a's measured r2 numbers.
* **That a form-(a) broadcast costs one MOVX window.** Neither the lockstep push rate nor back-pressure has been
  measured (R3-9a, R3-9b).
* **The DMA-queue stalls of the r3 order.** No order-only rule predicts them (SR11b). They are bounded by §1.1's
  stall arithmetic, not predicted.
* **The r3 chat-image numbers** (§4, pending R3-6's pins), board speed and timing.

## 7. Judgment calls

1. **A new file, `evidence/qwen9b/sr/r3_predict.py`, not `sr13a_derive.py --rtl r3`.** The plan gives
   sr13a_derive.py's `--rtl r3` flag, with its inputs as arguments, to R3-9b, the measured side (plan Task R3-9b,
   "Files"). R3-7's content also differs from that tool's: an absolute-saving primary anchored on a measured
   window, three forms side by side, the r2→r3 per-class delta, the one-window baseline and the chat formulas. The
   tool imports sr13a_derive's helpers (ms, tps, the shipped references, the uniform factor, the CSV reader), so
   nothing is copied except the model half of `class_compare`. That part is re-parameterised by rtl because the
   original hard-codes r2's stream, sha and predictions. The plan names this file r3_predict_tb.py; the dispatch
   named it r3_predict.py, and the dispatch's name is used.
2. **P-A = P-B = P-A-via-offset.** Because the two conventions give the same saving, the census cross-check does
   not separate them this round. The corrected-model form P-C is the one that differs from P-A, by exactly R2's
   measured residual. All are printed, and P-A carries the bands.
3. **§8: the heading line only.** The dispatch and the addendum restrict R3-7 to the heading. The plan's Step 3
   also names a one-line §8 entry and the "Open now … the round's R3 decision" sentence (NEXT_SESSION.md §8, the
   memtest paragraph). Neither was touched. R3-12's task text says it will only *check* that R3-7 fixed that
   sentence, so the controller should route the sentence (and the one-line entry) to R3-9b or R3-12.
4. **The run's tree stamp is `7cd851c+dirty`**, and the only dirty entry is R3-8's untracked
   evidence/qwen9b/sr/R3_8_RTL.md (uncommitted at the time), which is not an input to this tool
   (`evidence/qwen9b/sr/n2900_r3_predictions.log:2-3`). The tool file itself is the committed one.
5. **The chip-TB chat formula anchors on r1 (SR5b), not r2.** No r2 chat image ran on the chip TB. The r1→r3
   static saving is taken in the replay convention on both sides, because no r1 corrected static makespan is
   committed. The board formula (R3-11) stays the plan's corrected r2→r3 form.

## 8. Logs and commits

| log / commit | what |
|---|---|
| 7cd851c | `evidence/qwen9b/sr/r3_predict.py`, committed before its first run |
| `evidence/qwen9b/sr/n2900_r3_predictions.log` | the prediction: forms, bands, the STOP rule, s2–s4, per-class, one-window, chat formula |
| `evidence/qwen9b/sr/n2901_r3_7_spec_cites_precheck.log` | spec_cites precheck on the uncommitted doc: FAIL 1 (a backticked flag read as a quote of the n2900 line it sat beside; reworded) |
| `evidence/qwen9b/sr/n2902_r3_7_spec_cites_precheck2.log` | precheck after the rewording: FAIL 0 |
| n2999 | spec_cites LAST, alone, on the committed tree, over this document and `NEXT_SESSION.md` |
