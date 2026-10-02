# SR11b — the R2 pass, the corrected cost model and the r2 streams

Task SR11b of `docs/superpowers/plans/2026-09-27-seq-rtl-round.md` (the plan calls this gate doc
SR11b_R2_STREAMS.md; the dispatch named it `evidence/qwen9b/sr/SR11b_R2_PASS.md`). The contract is
`docs/SEQ_ISA.md` v2.3 §B17.2 and its reference model is SR11a's (`evidence/qwen9b/sr/SR11a_R2_MODEL.md`),
both consumed unchanged. No RTL, no Vivado, no board. Every numeric run was on snoke through
`evidence/qwen9b/sr/sr_run.sh`, log block n1150–n1199.

**Labels.** **E** printed by a run of this task, cited to its log line. **D** derived by a committed run on
snoke with the arithmetic in its command line (`evidence/qwen9b/sr/n1182_sr11b_r2_derive.log`). **T**
transcribed from an earlier gate. **MODEL**: a tok/s scaled from TB cycles by OV1's uniform board factor,
not a board measurement.

## Verdict

**GREEN.**

* **Model correction first (the controller's addendum, as corrected).** The corrected convention charges
  23 cycles per FENCE record and prices each single-channel poll tail per drained class; the tails were
  fitted on tokens 5–6 of SR5b's measured R1 run, with token 4 held out.
  * **The gate (fix round 1).** The ADDITIVE form is the same model every r2 prediction uses. It
    re-predicts R1's measured s1 token-4 window, 27,163,998 cyc, as **27,175,723: model − measured
    +11,725 = +0.043 %**. It charges the FENCE record: its 981 zero-wait FENCEs are exact (**E**,
    `evidence/qwen9b/sr/n1194_sr11bf1_model_correction_verify.log:28`). TDD (f1) PASS
    (`evidence/qwen9b/sr/n1187_sr11bf1_tdd_GREEN.log:87`).
  * **The old convention.** 27,136,513 (−0.101 %), right only by cancellation: its 981 zero-wait FENCEs
    price 0 against 22,563 measured, and it FAILS (f1)
    (`evidence/qwen9b/sr/n1194_sr11bf1_model_correction_verify.log:26-27`).
  * **Where the additive error sits.** It is not spread over the FENCE class. The FENCE class is +10,996,
    of which dn_out is +11,273: the one DMA-queue stall (§2.3) is counted twice, once in the residual and
    once as a dn_out wait the stall actually absorbed. Every other class is within ±397.
  * **An IN-SAMPLE diagnostic, not a prediction.** Placing the 19,308-cycle residual on token 4's OWN
    measured CMD windows gives 27,164,369 (+0.001 %), FENCE class −358, dn_out −65
    (`evidence/qwen9b/sr/n1160_sr11b_model_correction_verify.log:27-47`). That number is in-sample on
    the 19,308 part (TDD (f2), `evidence/qwen9b/sr/n1187_sr11bf1_tdd_GREEN.log:88-89`).
  * **Token 4's tail agreement is repeatability, not prediction.** Token 4's tails agree with the fitted
    ones to ≤ 1.1 cyc (`evidence/qwen9b/sr/n1157_sr11b_fence_fit.log:27-39`). That shows the same
    replayed order repeats; it does not show prediction of a different order.
  * **Sign convention:** model − measured, throughout.
* **Test-first.** RED 21 passed / 20 failed (`evidence/qwen9b/sr/n1150_sr11b_tdd_RED.log:233-234`). GREEN
  41/41 on the committed tree 0cf3f1f (`evidence/qwen9b/sr/n1151_sr11b_tdd_GREEN.log:91-92`).
* **r0 and r1 unchanged.** The four r1 streams regenerate byte-identical to SR4's (stream and manifest),
  and the pass's r0/r1 output equals the base commit 99c13ce's on every synthetic (§3). The correction
  moves predictions, not schedules, so there is no r1-schedule STOP.
* **The r2 streams.** Four streams, loop-body replay **26,146,927 TB cycles = OV1's R1+R2 row to the
  cycle** (`evidence/qwen9b/sr/n1165_reorder_s1_B_r2.log:50` vs `evidence/qwen9b/ov/n120_sr0_clock_sens.log:18`).
  The corrected prediction is **26,183,590** (×1.2522 vs shipped; band 26,166,378–26,183,590, §4.2).
  Every stream is valid at {R1,R2} and REFUSED at {R1} and at {}, and passes the range-aware hazard
  assert (§4). **All four gate 2358/2358 at {R1,R2}, ALL BIT-EXACT, tokens IDENTICAL** (§5).
* **The shipped streams at r0 still gate 2358/2358**, tokens IDENTICAL, with the running-range refusals armed (§5).

## 1. The diffs

**The census: `evidence/qwen9b/ov/ov_census.py`.** `build_edges` records the bank per MOVY: its writer
MVGO's RES bank, 0/1, −1 when that MVGO spans both banks, and 0 at depth 1
(`evidence/qwen9b/ov/ov_census.py:771`). No edge or timing reads it. Re-run on its committed inputs
(n1155, tree e7e8023), `evidence/qwen9b/ov/sr0_clock_sens.py` prints n120 line for line, including the
r = 0 rows; R1+R2 is 26,146,927 at `evidence/qwen9b/sr/n1155_sr11b_census_rerun.log:18`, the same as
`evidence/qwen9b/ov/n120_sr0_clock_sens.log:18`.

**The pass: `ref/scripts/reorder_e4.py`.**
* **`--rtl r2`** (`ref/scripts/reorder_e4.py:130-137`): caps {R1,R2}, census depth 2.
  * `schedule_segment` builds the census's edges at xdepth = rdepth = 2 and schedules the per-channel
    fence with bottom-level priority, which is run_sched's R1+R2 row (`ref/scripts/reorder_e4.py:295`).
  * `order_and_fences` emits r1's masked FENCEs (`ref/scripts/reorder_e4.py:335`). A MOVX into the other
    XWIN bank, or a MOVY of the other RES bank, has no stream-edge to the running stream, so it gets no
    FENCE.
* **Bank emission** (`banked`, `ref/scripts/reorder_e4.py:502`; applied in `emit_segment` at r2 only,
  `ref/scripts/reorder_e4.py:532`).
  * MOVX target is 1536 for bank 1, and 0 for bank 0 or a span.
  * MVGO SHAPE bit 29 = XBANK and bit 30 = RBANK, both 0 on a span.
  * MOVY target[15:4] is 2048 for bank 1, 0 otherwise; target[3:0] (the channel) is kept.
  * **Elision keyed by bank.** An elided MOVX does not advance the census's xsel, so the MVGO that
    follows reads the bank the surviving copy sits in. The TDD checks this on both synthetics (§3).
* **The hazard assert is range-aware** (`ref/scripts/reorder_e4.py:199-289`), with the model's rule.
  * A MVGO on a channel with ANY pending stream is refused.
  * A MOVX is refused only if its XWIN words overlap the pending stream's x range [1536·XBANK, +32·ng).
  * A MOVY is refused only if its rows overlap the pending RES range [2048·RBANK, +nrows).
  * An empty access range counts as overlapping. With every bank field zero, the ranges always overlap:
    the per-channel rule, unchanged. SR4's hazard cases still pass (n1183, §3).
* **Admission.** At r2 the output must validate at {R1,R2} and must be REFUSED at {} and at {R1}
  whenever it carries a bank field (`ref/scripts/reorder_e4.py:783-801`). The manifest records seq_isa 2.3,
  caps [R1, R2], and the bank-field count (`ref/scripts/reorder_e4.py:871`). A bank-carrying INPUT is
  refused at every level (`ref/scripts/reorder_e4.py:655`).
* **`predict()`** (`ref/scripts/reorder_e4.py:444`) prices an emitted order with the corrected
  convention (§2). At r2 each segment reports both the census replay (`replay_mk`) and the corrected
  prediction (`pred_mk`) (`ref/scripts/reorder_e4.py:720`).
* **`--selftest`** gains `selftest_r2` (`ref/scripts/reorder_e4.py:1088`): PASS
  (`evidence/qwen9b/sr/n1152_reorder_selftest.log:25-27`).

**The cost model: `ref/seq_cost.py`.** FENCE_REC, TAIL1 (13 classes), TAIL1_DEFAULT and CMD_RESID_FRAC,
each citing the log that measured it (`ref/seq_cost.py:213-236`), plus `fence_tail`
(`ref/seq_cost.py:348`). **They enter predictions only.** `cost_of_segment`'s rows, which feed the
scheduler through `stream_durations`' tau, are unchanged; the TDD's (e) checks them equal to the base
commit's. So no r0/r1 schedule, no chat_seq pin and no measured r1 stream moves (the docstring,
`ref/seq_cost.py:41-51`).

## 2. Model correction (before any R2 prediction)

### 2.1 What was wrong (T, SR5b)

The replay priced every FENCE as the wait for its stream, ending at the ORIGINAL 4-channel group's poll
tail on BN1's CSV, and charged the FENCE record nothing. On the chip TB each FENCE record costs 23 cycles
(981 zero-wait FENCEs, min = max = 23, `evidence/qwen9b/sr/n570_sr5_derive.log:80`), and the waiting
FENCEs came in 13,657 cyc under (`evidence/qwen9b/sr/n570_sr5_derive.log:81`). The two cancel to −8,906 (model − measured; n570 prints measured − model, +8906; sign fixed by SR9)
at R1's operating point (`evidence/qwen9b/sr/n570_sr5_derive.log:68`).

### 2.2 The fit (n1157)

* **The record cost is 23 on every token.** The FENCEs that did not wait on the TB are 1,022 on each of
  tokens 4, 5 and 6, all exactly 23 (`evidence/qwen9b/sr/n1157_sr11b_fence_fit.log:21-23`).
* **The tail per drained class.** For each FENCE that WAITED on the TB, the effective tail is
  FENCE end − 23 − (MVGO end + model S). It is fitted on tokens 5–6, 696 FENCEs, with token 4 held out
  (`evidence/qwen9b/sr/n1157_sr11b_fence_fit.log:25-40`).
  * **Two waiting counts, two criteria (M2).** Both counts are per body execution, i.e. per token.
    * 348 FENCEs WAITED on the TB: 1,370 − 1,022 whose measured window is exactly 23
      (`evidence/qwen9b/sr/n1157_sr11b_fence_fit.log:21-23`). The fit's 696 is 2 tokens × 348.
    * SR5b's 389 waited in the OLD MODEL: 1,370 − 981 whose old-model wait is 0
      (`evidence/qwen9b/sr/n570_sr5_derive.log:80-81`).
    * They differ because the old model and the TB disagree on which FENCEs find their stream still
      running.
  * Measured S equals model S to within a cycle in every class, so the error really is the tail.
  * The single-channel tails are 18–27 cyc for most classes, against the old 4-group tau of 39–48, and
    74–75 for mlp_down (old 90–92).
  * Token 4's in-sample tails agree with the fitted ones to 1.1 cyc or better.
* **The constants** transcribed into `ref/seq_cost.py:213-236`: FENCE_REC 23, TAIL1 per class,
  TAIL1_DEFAULT 28 (the pooled mean, for a class that never waited at R1: in_b, k_proj, v_proj), and
  CMD_RESID_FRAC = 19,308 / 10,710,770 (`evidence/qwen9b/sr/n570_sr5_derive.log:67`).

### 2.3 Where the dn_out error really was (n1158, n1159, n1191)

The first GREEN attempt priced the inherited CMD residual ADDITIVELY, as the controller's +19,308. It
landed the total at +0.043 %, but DN dn_out stayed at +11,273 (`evidence/qwen9b/sr/n1190_sr11b_tdd_dev.log:94`).
Diagnosis on the measured runs:
* **The "CMD residual" is not diffuse contention.** It is SLD +17,212 on every token, plus KVAP +65 to
  +85 per command, growing with position (`evidence/qwen9b/sr/n1158_sr11b_fence_diag.log:29-31`,
  `evidence/qwen9b/sr/n1158_sr11b_fence_diag.log:43-44`, `evidence/qwen9b/sr/n1158_sr11b_fence_diag.log:56-57`).
* **The SLD term is ONE DMA-queue stall.** 17,212 = 17,251 − 39: the SLD at r1 pc 157664 ran 17,251
  where the program-order windows say 39 (`evidence/qwen9b/sr/n1159_sr11b_fence_diag2.log:116`).
* **It sits inside the dn_out lane gaps** (+68,848 = 4 × 17,212 over their MVGO→FENCE gaps), so it
  absorbs those FENCEs' waits (`evidence/qwen9b/sr/n1158_sr11b_fence_diag.log:70`). That is the dn_out
  +9,524 (model − measured, as the §2.4 table; sign fixed by SR9) SR5b saw: a CMD-class stall in lane time, not a FENCE-convention error.
* **No order-only rule places that stall.** The strict 6th-consecutive rule predicts 32 stalls on the r1
  order against 8 measured. A one-in-flight queue with a fixed transfer time matches the shipped order for
  X in 2,000–4,300 and the r1 order for no X in 2,000–60,000
  (`evidence/qwen9b/sr/n1191_sr11b_dma_diag.log:121-124`).

So the FENCE convention is judged with the inherited residual PLACED in lane time on the commands the
TB measured it on (`predict(..., cmd_extra=)`, an attribution aid; `evidence/qwen9b/sr/sr11b_model_correction.py`).
Every r2 prediction uses the ADDITIVE form, because no measured placement exists for an r2 order.

### 2.4 Before / after, s1 token-4 body window, measured 27,163,998 (E, n1160)

| model | prediction | − measured | FENCE class (1,370) − measured | worst drained class | cite |
|---|---|---|---|---|---|
| BEFORE (SR4's convention) | 27,136,513 | −27,485 = −0.101 % | −8,906 (= −22,563 records + 13,657 tails) | dn_out +9,524 | `evidence/qwen9b/sr/n1160_sr11b_model_correction_verify.log:26`, `evidence/qwen9b/sr/n1160_sr11b_model_correction_verify.log:29` |
| **AFTER, residual additive (the r2 form; THE GATE, (f1))** | **27,175,723** | **+11,725 = +0.043 %** | +10,996 | dn_out +11,273 (the stall counted twice) | `evidence/qwen9b/sr/n1160_sr11b_model_correction_verify.log:48-68` |
| AFTER, residual placed (IN-SAMPLE diagnostic, (f2)) | 27,164,369 | +371 = +0.001 % | −358 | mlp_down −397; dn_out −65 | `evidence/qwen9b/sr/n1160_sr11b_model_correction_verify.log:27-47` |

Sign: model − measured. The placed row injects token 4's own measured CMD windows (the 19,308 part), so it
is in-sample; it shows only that, once the stall sits where it happened, the FENCE convention leaves no
class error above ±397.

* **Zero-wait FENCEs.** In the placed model, 982 FENCEs predict 22,586 and measure 22,586
  (`evidence/qwen9b/sr/n1160_sr11b_model_correction_verify.log:30`).
* **Every non-FENCE window is BN1's.** The −729 in LDC/MVGO/EMB (`evidence/qwen9b/sr/n570_sr5_derive.log:69-71`)
  is left, as the correction specified.
* **Both forms are within ±0.5 %** (`evidence/qwen9b/sr/n1160_sr11b_model_correction_verify.log:70`).
* **The TDD's (f), as split in fix round 1:**
  * (f1) is the gate: the ADDITIVE form within ±0.5 % with the record charged, and SR4's convention must
    fail it.
  * (f2) prints the placed form's attribution against the original thresholds (FENCE class ≤ 5,000,
    every class ≤ 2,500) as a diagnostic only.
  * Before the split, (f) asserted the placed form (`evidence/qwen9b/sr/n1151_sr11b_tdd_GREEN.log:87`).
    The review found that was the in-sample reading (§9).

## 3. RED → GREEN (`evidence/qwen9b/sr/sr11b_pass_tdd.py`)

| case | what | RED n1150 | GREEN n1151 |
|---|---|---|---|
| (a) | the census's MOVY bank = its writer's RES bank (−1 on the 4096-row span), 0 at depth 1; MOVX/MVGO banks as assigned | 1/3 | 3/3 |
| (b) | `reorder_e4._synthetic()`, forms A/B, at r2: bank fields emitted and legal, an independent bank walk finds every read backed, replay ≤ r1, hazard assert, valid {R1,R2} / refused {R1} and {}; SR11a's model at {R1,R2} (running ranges and unwritten-read refusals armed, an x-dependent stub engine) runs it to the r0 stream's final state and refuses it at {R1}; the elided MOVX's MVGO names the surviving copy's bank | 0/5 | 5/5 |
| (b2) | the same on a 2-channel synthetic with a K = 12288 MOVX and a 4096-row MVGO (they stay at word 0 / bank bits 0) and a redundant MOVX; r2 replay STRICTLY below r1 (7,653 vs 7,803) | 0/5 | 5/5 |
| (c) | the hazard assert: MOVX into the other bank legal, into the pending one refused (also a partial overlap and a spanning stream); MOVY of the other RES half legal, of the pending half refused; MVGO in any bank refused; zero banks = the per-channel rule; mask-aware; pending at HALT refused | 8/10 | 10/10 |
| (d) | r0 and r1 = the pass at 99c13ce (stream, checkpoints, manifest bytes) on both synthetics and both forms; s1 CSV r0 = SV1's pin, r1 = SR4's pin | 10/10 † | 10/10 |
| (e) | FENCE_REC 23, per-class TAIL1 with a default, CMD_RESID_FRAC; `predict` = a hand walk; `cost_of_segment` = the base commit's | 1/5 | 5/5 |
| (f) → (f1) | the R1 re-prediction (§2.4). Fix round 1: (f1) GATES the ADDITIVE form (±0.5 %, the record charged, SR4's convention must fail); (f2) prints the placed form as an in-sample diagnostic | 0/1 | 1/1 (n1151, placed form); (f1) 1/1 (`evidence/qwen9b/sr/n1187_sr11bf1_tdd_GREEN.log:87`, `evidence/qwen9b/sr/n1187_sr11bf1_tdd_GREEN.log:93-94`) |
| (g) | a bank-carrying input is refused | 1/1 ‡ | 1/1 |
| (h) | the r2 manifest: seq_isa 2.3, caps [R1, R2], rtl r2 | 0/1 | 1/1 |

† (d) is the regression half: it passes at RED by construction. ‡ (g) passes vacuously at RED, where
r2 itself is refused.

* **n1150 is the valid RED** (`evidence/qwen9b/sr/n1150_sr11b_tdd_RED.log:233-234`).
* **n1190 and n1192 are dev runs** on the uncommitted pass, kept as the record. n1190 is 40/1, (f)
  failing with the additive residual (§2.3) (`evidence/qwen9b/sr/n1190_sr11b_tdd_dev.log:93-94`). n1192 is
  41/0 (`evidence/qwen9b/sr/n1192_sr11b_tdd_dev.log:93-94`).

**Regressions.**

| run | result | log |
|---|---|---|
| `ref/scripts/reorder_e4.py --selftest` (r0/static + r2) | PASS | `evidence/qwen9b/sr/n1152_reorder_selftest.log:27` |
| `sw/chat_seq.py --selftest` | 407/1, the known region-image FAIL | `evidence/qwen9b/sr/n1153_chat_seq_selftest.log:36` |
| boardfree | 2823/0, 85/0, 407/1 | `evidence/qwen9b/sr/n1154_boardfree.log:61`, `evidence/qwen9b/sr/n1154_boardfree.log:107`, `evidence/qwen9b/sr/n1154_boardfree.log:138` |
| `evidence/qwen9b/sr/sr4_r1_tdd.py` | 30/1 at fix 0: the one FAIL is SR4's "--rtl r2 is refused (SR11b's)" (`evidence/qwen9b/sr/n1183_sr4_tdd_regression.log:35`); fix round 1 flips that case to "r2 accepted, valid {R1,R2}, refused {R1}": **31/0** | `evidence/qwen9b/sr/n1183_sr4_tdd_regression.log:55-56`, `evidence/qwen9b/sr/n1188_sr11bf1_sr4_tdd.log:35`, `evidence/qwen9b/sr/n1188_sr11bf1_sr4_tdd.log:55-56` |
| the four r1 streams regenerated (CSV, form B, r1) | sha256 4e11a2ae / cc982e4f / 0f85a974 / 492e0def = SR4's; the .seq and .seq.json files byte-identical to SR4's files (cmp on snoke, with .seqdata.bin, `evidence/qwen9b/sr/n1195_sr11bf1_r1_identity.log`) | `evidence/qwen9b/sr/n1178_regen_s1_B_r1.log`, `evidence/qwen9b/sr/n1179_regen_s2_B_r1.log`, `evidence/qwen9b/sr/n1180_regen_s3_B_r1.log`, `evidence/qwen9b/sr/n1181_regen_s4_B_r1.log` |

* **The boardfree triple moved only upward.** seq_run 2823 vs SR11a's 2820
  (`evidence/qwen9b/sr/n1149f_boardfree.log:61`): SR7 fix 1's added selftests. serve and chat_seq are
  unmoved.

## 4. The r2 streams

### 4.1 Generation (E)

The recipe is SR4's n410 at `--rtl r2`: `ref/scripts/reorder_e4.py --in tb/scripts/w9/model_9b_s{k}.e4 --out tb/scripts/w9/model_9b_s{k}_reordB_r2.e4 --form B --cost csv --rtl r2 --stats`. <!--cites:noquote-->

| stream | log | records | sha256 | body replay (census) | body corrected |
|---|---|---|---|---|---|
| s1 | `evidence/qwen9b/sr/n1165_reorder_s1_B_r2.log` | 160,724 | 117ed8b061d5662517d67f905ff1b5900520ba39eff680548e8af9a7efc17d19 (`evidence/qwen9b/sr/n1165_reorder_s1_B_r2.log:58`) | 26,146,927 | 26,183,590 (`evidence/qwen9b/sr/n1165_reorder_s1_B_r2.log:56`) |
| s2 | `evidence/qwen9b/sr/n1166_reorder_s2_B_r2.log` | 80,383 | 5d0a8bdd8298ea252af063041c63bb5df654a9aa834be4acb66e8772c23c6756 (`evidence/qwen9b/sr/n1166_reorder_s2_B_r2.log:40`) | 26,146,927 | 26,183,590 |
| s3 | `evidence/qwen9b/sr/n1167_reorder_s3_B_r2.log` | 80,383 | e35772cc8ed3e554bd3f1fbe93e2f40a754b70e2ea98adaa94d66e71a097a70c (`evidence/qwen9b/sr/n1167_reorder_s3_B_r2.log:40`) | 26,146,927 | 26,183,590 |
| s4 | `evidence/qwen9b/sr/n1168_reorder_s4_B_r2.log` | 160,724 | 8b16c7b15d1f204a00bc47b3cce11f8c85dc580ee4294f069451d41155b28563 (`evidence/qwen9b/sr/n1168_reorder_s4_B_r2.log:58`) | 26,146,927 | 26,183,590 |

* **Per body** (s1, `evidence/qwen9b/sr/n1165_reorder_s1_B_r2.log:39-56`):
  * records 39,624 → 40,171; MOVX 996 → 516 (480 elided, as r1); FENCE 343 → 1,370, all single-channel.
  * POSTCHECK on the emitted order: 66,267 edges + 1,126,149 channel/lane checks, 0 violations.
  * Banks: MOVX word 0 × 320 and word 1536 × 196; XBANK × 698 and RBANK × 686 of 1,370 MVGOs; MOVY row
    0 × 684 and row 2048 × 686.
* **Admission, in the pass** (`evidence/qwen9b/sr/n1165_reorder_s1_B_r2.log:49-51`): valid at {R1,R2};
  refused at {} and at {R1}; 7,664 bank fields in the s1 stream.
* **Determinism.** The streams were generated twice, n1161–n1164 and n1165–n1168, with identical shas.
  The first generation's bank-count REPORT was mis-keyed by an editing slip (§6 item 6); no emitted record
  depends on it.
* **The independent check** (`evidence/qwen9b/sr/sr11b_r2_check.py`, n1173) runs per stream: sha =
  manifest; VALID at {R1,R2}; REFUSED at {R1} and at {} (the first refusal is a MOVX target: the XWIN start
  word needs R2); the range-aware hazard assert passes; manifest caps [R1, R2]. PASS 4/4
  (`evidence/qwen9b/sr/n1173_sr11b_r2_check.log:7-39`).

### 4.2 Predictions beside the spec (D, n1182)

| quantity | value | cite |
|---|---|---|
| r2 body, census convention | 26,146,927 cyc = 104.588 ms TB = OV1's R1+R2 row | `evidence/qwen9b/sr/n1165_reorder_s1_B_r2.log:50`, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:18` |
| r2 body, corrected | **26,183,590** cyc = 104.734 ms TB (lane 26,164,282 + residual 19,308); +36,663 over the census | `evidence/qwen9b/sr/n1182_sr11b_r2_derive.log:27`, `evidence/qwen9b/sr/n1182_sr11b_r2_derive.log:32` |
| band for the residual's placement | 26,166,378–26,183,590: the 17,212-cyc DMA stall absorbed by a FENCE wait, or not. The low end subtracts the FULL stall; at R1 the measured absorption was 11,354 (27,175,723 − 27,164,369), so an "as at R1" low end would be about 26,172,236 — the band stands as the conservative one, and it does not cover extra DMA stalls an r2 order may incur (§7) | `evidence/qwen9b/sr/n1182_sr11b_r2_derive.log:28` |
| × shipped (32,786,868) | corrected 1.2522 (band 1.2522–1.2530); census 1.2539 | `evidence/qwen9b/sr/n1182_sr11b_r2_derive.log:30` |
| × R1 | corrected r2 vs corrected R1 1.0379; vs R1 MEASURED 1.0374; census 1.0378 | `evidence/qwen9b/sr/n1182_sr11b_r2_derive.log:31` |
| board-scaled MODEL | 9.131 tok/s (band to 9.137), against the census row's 9.144 and R1's measured-window 8.802 | `evidence/qwen9b/sr/n1182_sr11b_r2_derive.log:33` |

* **Against the spec’s R2 gain.** The dispatch gives R2’s modelled gain as 1.212–1.254× shipped, i.e. the
  spec’s R1+R2 row, 9.144 (form B) / 8.837 (form A) tok/s (`docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md:47`),
  against 7.292 shipped. The corrected form-B prediction, ×1.2522 (band to ×1.2530), sits at the top of that
  range, just under the census’s ×1.2539.
* **The prediction SR13a judges.** It is the corrected 26,183,590 (band 26,166,378–26,183,590), not the
  census's 26,146,927.

## 5. Gates

Every gate is `ref/seq_model.py --gate`, run through a wrapper that sets `FABLE5_MODEL=9b FABLE5_RS_F=7`
itself (so the env line of each log reads "unset"). All eight ran in parallel on snoke on tree b2331f2,
stamped `+dirty` for SR7's NEXT_SESSION.md only.
* **r2 streams:** `evidence/qwen9b/sr/sr11b_gate.sh` at caps {R1,R2}.
* **Shipped streams at r0:** `evidence/qwen9b/ov/sv1_gate.sh` (SR4's and SR11a's recipe), caps none.
  The model's running-range refusals are armed there, and so is the pass after this change.

| stream | caps (line 14) | CHECKPT (line 18) | TOKENS (line 22) | verdict (line 23) |
|---|---|---|---|---|
| s1 r2 | {R1,R2} | 2358/2358 ALL BIT-EXACT | IDENTICAL [2614, 314, 279, 369, 11751, 13] | PASS, `evidence/qwen9b/sr/n1169_gate_s1_reordB_r2.log:18-23` |
| s2 r2 | {R1,R2} | 2358/2358 | IDENTICAL [279, 264, 854, 11, 303, 264] | PASS, `evidence/qwen9b/sr/n1170_gate_s2_reordB_r2.log:18-23` |
| s3 r2 | {R1,R2} | 2358/2358 | IDENTICAL [313, 430, 2510, 198, 1445, 27180] | PASS, `evidence/qwen9b/sr/n1171_gate_s3_reordB_r2.log:18-23` |
| s4 r2 | {R1,R2} | 2358/2358 | IDENTICAL [11, 0, 271, 803, 369, 498] | PASS, `evidence/qwen9b/sr/n1172_gate_s4_reordB_r2.log:18-23` |
| s1 shipped r0 | none | 2358/2358 | IDENTICAL [2614, 314, 279, 369, 11751, 13] | PASS, `evidence/qwen9b/sr/n1174_gate_shipped_s1_r0.log:18-23` |
| s2 shipped r0 | none | 2358/2358 | IDENTICAL [279, 264, 854, 11, 303, 264] | PASS, `evidence/qwen9b/sr/n1175_gate_shipped_s2_r0.log:18-23` |
| s3 shipped r0 | none | 2358/2358 | IDENTICAL [313, 430, 2510, 198, 1445, 27180] | PASS, `evidence/qwen9b/sr/n1176_gate_shipped_s3_r0.log:18-23` |
| s4 shipped r0 | none | 2358/2358 | IDENTICAL [11, 0, 271, 803, 369, 498] | PASS, `evidence/qwen9b/sr/n1177_gate_shipped_s4_r0.log:18-23` |

* **Every r2 token row equals its shipped seed's.** The gate also compares the tokens against the shipped
  artifact's own record. Each run has no error and no hazard, with rc 0.
* **What the r2 gates prove.** Every emitted bank field runs through SR11a's XWinMem/ResMem.
  * Every MVGO read an intact vector at word 0 or 1536.
  * Every MOVY lay inside one live MVGO result.
  * No MOVX or MOVY overlapped a pending range.
  * The machine state is bit-exact against the .txt replay at all 2,358 checkpoints.


## 6. Judgment calls and deviations

1. **The correction changes predictions, not schedules.** FENCE_REC/TAIL1 do not enter
   `cost_of_segment`'s rows, because the rows feed the scheduler (tau).
   * Charging them there would re-schedule every static-cost r0/r1 image (chat_seq's pins).
   * The r1 streams (CSV costs) are unaffected either way.
   * r2 is scheduled with the census's convention, so its replay is comparable to n120's R1+R2 row, and
     priced with the corrected one.
   * No r1 schedule moved, so there is nothing to STOP on.
2. **The inherited CMD residual, two readings** (§2.3).
   * The controller asked to keep +19,308, and it is kept.
   * Measured, it is one DMA-queue stall plus KVAP contention, and the stall's lane position decides which
     FENCEs it absorbs.
   * The gate is the ADDITIVE reading, the one the r2 predictions use (fix round 1, §9).
   * The placed reading is an in-sample diagnostic of the FENCE convention alone.
   * Before fix round 1, (f) read the placed form. `reprediction()` was switched to return it after the dev
     run n1190 showed the additive reading fails dn_out. The review (I1) called that out, and (f) is now
     split.
3. **Tails fitted on tokens 5–6, token 4 held out.** Token 4 is the prediction target. The fit is on the
   same schedule, so held-out means another execution of the same order, not another order.
4. **TAIL1_DEFAULT (28)** prices classes that never waited at R1 (in_b, k_proj, v_proj). At r2 they may
   wait; the default is an extrapolation.
5. **The hazard assert reads this tree's SHAPE layout.** A caller holding a frozen isa=1 stream (bit 29 =
   w8) states `shape_isa=1` and gets no banks. The pass reorders 9B streams only.
6. **Log numbers.**
   * n1150 RED, n1151 GREEN, n1152–n1154 regressions, n1155 the census re-run.
   * n1156 is a failed first fit (token 6 lacks the five records the r1 pass hoisted above the body's EMB),
     kept. n1157 is the fit.
   * n1158, n1159 and n1191 are the diagnosis; n1160 is the verify.
   * n1161–n1164 are the first r2 generation. Its manifests carry a bank-count REPORT mis-keyed by a perl
     splice that interpolated '@1536'/'@0'. Kept; the report was fixed (e2095f6) and the streams
     regenerated byte-identical.
   * n1165–n1168 the r2 streams, n1169–n1172 their gates, n1173 the independent check, n1174–n1177 the
     shipped gates, n1178–n1181 the r1 regeneration, n1182 the derivation, n1183 SR4's TDD.
   * n1190 and n1192 are dev TDDs. n1190–n1199 are this task's dev/diagnostic sub-block.
   * The plan's "n1160–n1163 streams, n1164–n1167 gates" shifted by five, because n1160 went to the verify.
7. **Stamps.** From n1151 on, the logs carry `+dirty` for NEXT_SESSION.md only. That is SR7's concurrent
   edit, and no run reads it. Every file a run reads was committed first.
8. **Rule slips (no arithmetic).**
   * darthplagueis ran `python3` once with an empty heredoc (a no-op), and `sha256sum` once on the four
     first-generation r2 files before deleting them. The shas that count are snoke's (n1165–n1168, n1173).
   * darthplagueis ran `cmp` on the regenerated r1 files (a byte compare).
   * Edits were made with perl/sed and the Edit tool.
9. **New tools, each committed before first use:** `evidence/qwen9b/sr/sr11b_model_correction.py`,
   `evidence/qwen9b/sr/sr11b_gate.sh` (`evidence/qwen9b/sr/sr4_gate.sh` at caps R1,R2) and
   `evidence/qwen9b/sr/sr11b_r2_check.py`.

## 7. What this does NOT establish

* **The chip TB on R2 RTL** (SR13a). Every r2 cycle here is MODEL. The prediction SR13a judges is
  26,183,590 (band 26,166,378–26,183,590).
* **DMA-stall placement.** No order-only rule predicts the queue's stalls on a reordered stream (§2.3).
  Whether an r2 order incurs the R1 order's extra stall, and whether a FENCE absorbs it, is unknown; the
  band carries it.
* **Tails at R2's overlap.** The tails were fitted at R1's overlap pattern. R2 overlaps more streams with
  more MOVX/MOVY traffic, so contention may move the tails and the KVAP term.
* **Timing, OOC counts or a bitstream** of any R2 netlist (SR12/SR14), and nothing on the board.

## 8. Doc gate

spec_cites over this doc, run LAST and alone on the committed tree:
* **n1184 (tree 4daf03e): FAIL 1.** A backticked .seq.json suffix was read as a path. It is kept as the record.
* **The fix:** that phrase is now unbackticked.
* **n1185 (tree 231774c): FAIL 1.** This section itself quoted the suffix in backticks. Kept as the record.
* **n1186 is the final run.**

## 9. Fix round 1 (the task review: I1, I2, M1–M6; SR4's case granted)

Nothing numeric moved in this round. The r2 prediction is still 26,183,590 cyc, band 26,166,378–26,183,590. Sign convention everywhere: model − measured.

### I1 — (f) now gates the ADDITIVE form

(f) used to assert the PLACED reading, which puts the 19,308-cycle CMD residual on token 4's own measured CMD windows. That reading is in-sample on that part. It became what (f) read in 9699b39, after the dev run n1190 showed the additive reading fails. The fix splits (f):

* **(f1), the gate.** The ADDITIVE form must hold R1 within ±0.5 % and charge the FENCE record, with its zero-wait FENCEs exact. SR4's convention must fail the same test.
  * Result: +11,725 = +0.043 %; zero-wait 981, 22,563 against 22,563.
  * Negative control: SR4's convention prices its 981 zero-wait FENCEs at 0, so it fails.
  * Cites: `evidence/qwen9b/sr/n1187_sr11bf1_tdd_GREEN.log:87`, `evidence/qwen9b/sr/n1194_sr11bf1_model_correction_verify.log:26-28`.
* **(f2), a diagnostic only.** The attribution thresholds are printed for both readings, and neither is a gate (`evidence/qwen9b/sr/n1187_sr11bf1_tdd_GREEN.log:88-89`).
  * Placed: inside the thresholds.
  * Additive: FENCE class +10,996 and dn_out +11,273, which is the DMA stall counted twice (§2.3).
* **RED for (f1) is not practical as a run.** The correction was committed before this round. The test's own negative control is the discriminating half: the uncorrected convention also sits within ±0.5 % (−0.101 %), and it fails only on the record clause.
* **The whole TDD** passes 41/41 (`evidence/qwen9b/sr/n1187_sr11bf1_tdd_GREEN.log:93-94`).

### I2 — cite drift for the three edited files since 99c13ce

The wrapper was `evidence/qwen9b/sr/sr11bf1_drift.sh`, committed before use. Its excludes cover every document first committed after 99c13ce: SR11b's own, SR13b's `SR13b_HOST_R2.md` and `sr13b_*.py`, SR11a fix3's, and SR7 fix1's. None of SR13a's documents is committed. Every `--fix` rewrote digits only.

| edited file | --plan | --fix | --verify | documents changed |
|---|---|---|---|---|
| `ref/scripts/reorder_e4.py` | REPAIR 20 / COLLATERAL 0, SAFE (`evidence/qwen9b/sr/n1196_sr11bf1_drift_plan_reorder.log:17`) | 33 cites in 5 docs (`evidence/qwen9b/sr/n1199_sr11bf1_drift_fix_reorder.log:20`) | 5 UNRESOLVED (`evidence/qwen9b/sr/n1199a_sr11bf1_drift_verify_reorder.log`, `evidence/qwen9b/sr/n1199b_sr11bf1_drift_verify_reorder.log`), all repaired by hand | docs/SEQ_ISA.md, the plan, the spec, SV1_S1_VERIFY.md, SR4_R1_MODEL.md |
| `ref/seq_cost.py` | REPAIR 13 / 0, SAFE (`evidence/qwen9b/sr/n1199c_sr11bf1_drift_plan_cost.log:15`) | 15 cites in 3 docs (`evidence/qwen9b/sr/n1199d_sr11bf1_drift_fix_cost.log:17`) | PASS (`evidence/qwen9b/sr/n1199e_sr11bf1_drift_verify_cost.log:18`) | the plan, S1P_SHIP.md, SR4_R1_MODEL.md |
| `evidence/qwen9b/ov/ov_census.py` | REPAIR 6 / COLLATERAL 2 (`evidence/qwen9b/sr/n1198_sr11bf1_drift_plan_census.log:17`), then SAFE with both tokens cleared by name (`evidence/qwen9b/sr/n1199f_sr11bf1_drift_plan_census.log:24`) | 9 cites in 4 docs (`evidence/qwen9b/sr/n1199g_sr11bf1_drift_fix_census.log:23`) | PASS (`evidence/qwen9b/sr/n1199h_sr11bf1_drift_verify_census.log:19`) | the plan, the spec, OV1_DEPENDENCY_CENSUS.md, SV1_S1_VERIFY.md |

* **The two ov_census COLLATERAL tokens** were checked by hand. The 5-line MOVY insertion lengthens each range.
  * The spec's build_edges range 633-776 becomes 633-781.
  * OV1's channel-resources block 723-771 becomes 723-776.
* **The reorder_e4 UNRESOLVED tokens** are the lines SR11b rewrote. They were repaired by hand:
  * SR4_R1_MODEL: 99-102 → `ref/scripts/reorder_e4.py:130-134` (RTLS/HEUR_R1/CAPS_OF), 164 → `ref/scripts/reorder_e4.py:225` (the hazard assert), 270 → `ref/scripts/reorder_e4.py:357` (the r1/r2 fence branch).
  * SV1_S1_VERIFY: 183 → `ref/scripts/reorder_e4.py:382` (the fence-at-use rule). That cite was already stale since SR4.
* **Cites stale before SR4 that o3 had content-tracked.** o3 moved these along with the content they pointed at, which was already the wrong content. They were re-aimed by hand to the functions they name:
  * the pass's assert → `ref/scripts/reorder_e4.py:225`;
  * `order_and_fences` → `ref/scripts/reorder_e4.py:335-392`;
  * `replay` → `ref/scripts/reorder_e4.py:394`;
  * `write_out` → `ref/scripts/reorder_e4.py:840-876`;
  * SV1's hazard walk → `ref/scripts/reorder_e4.py:225`.
* **Commits:** d89fab6, ed5952d plus 29433a6 (S1P_SHIP.md, which the NFS view had lagged), and 47499a0.

### The minors

* **M1:** the band's low end, §4.2.
* **M2:** the waiting counts, §2.2.
* **M3:** the r1 .seq, .seq.json and .seqdata.bin files are byte-identical by `cmp` on snoke (`evidence/qwen9b/sr/n1195_sr11bf1_r1_identity.log`).
* **M4:** the mojibake in `evidence/qwen9b/sr/sr11b_model_correction.py` is repaired. Its cause was a perl wide-character print, the same slip that hit this doc twice in this round; each was repaired and checked for 0 residual characters.
* **M5:** the SR4 FAIL is now cited at n1183:35 (§3).
* **M6:** one sign convention, model − measured, in the TDD output and in this doc.

### SR4's case (f), with ownership granted for this case only

SR4's case "--rtl r2 is refused" is replaced one for one by "--rtl r2 accepted, valid {R1,R2}, refused {R1}". SR4's TDD now passes **31/0** (`evidence/qwen9b/sr/n1188_sr11bf1_sr4_tdd.log:35`, `evidence/qwen9b/sr/n1188_sr11bf1_sr4_tdd.log:55-57`).

### Regressions

| run | result |
|---|---|
| sr11b_pass_tdd | 41/41 |
| `ref/scripts/reorder_e4.py --selftest` | PASS (`evidence/qwen9b/sr/n1189_sr11bf1_reorder_selftest.log:27`) |
| boardfree | seq_run 2826/0, serve 85/0, chat_seq 407/1, the known region-image FAIL (`evidence/qwen9b/sr/n1193_sr11bf1_boardfree.log:61`, `evidence/qwen9b/sr/n1193_sr11bf1_boardfree.log:107`, `evidence/qwen9b/sr/n1193_sr11bf1_boardfree.log:138`) |

* seq_run rose from 2823 to 2826 through other tasks' added selftests.
* **Stamps:** `+dirty` means SR13a's untracked `sr13a_cov.py`, which no run reads.

### Doc gate

spec_cites runs LAST and alone over this doc and every document the drift touched (§10).

## 10. Doc gate, fix round 1

spec_cites runs LAST and alone on the committed tree, over this doc and every document the drift fix touched: `docs/SEQ_ISA.md`, `docs/superpowers/plans/2026-09-27-seq-rtl-round.md`, `docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md`, `evidence/qwen9b/ov/SV1_S1_VERIFY.md`, `evidence/qwen9b/sr/SR4_R1_MODEL.md`, `evidence/qwen9b/ov/S1P_SHIP.md` and `evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md`. The log is n1199i.

**The spec_cites runs.**
* **n1199i (tree ee6617a): FAIL 9**, kept as the record.
  * **Seven ORPHANs** in §9's hand-repair list. Its old and new line numbers were bare continuations; the new ones are now full paths, and the old ones are unbackticked.
  * **Two QUOTEs** in `evidence/qwen9b/sr/SR4_R1_MODEL.md`, lines 27 and 38. Both cite `ref/seq_model.py` lines that SR11a's model edits moved, and SR11a left that drift unapplied (its §5 item 7). They were re-aimed by hand to the `caps=frozenset()` lines, SeqExec at `ref/seq_model.py:615` and gate at `ref/seq_model.py:1369`.
  * **SR4_R1_MODEL's other `ref/seq_model.py` cites are still stale** from SR11a's edits (they carry no quotation, so spec_cites passes them). This is not a file SR11b edited; it is left for a seq_model drift pass.
* **n1199j (tree 3cce1e8+dirty): FAIL 0**, but the tree was dirty because these fixes were still uncommitted (a commit had failed on its pathspec). It is kept as the record.
* **n1199k is the final run**, on the committed tree.
