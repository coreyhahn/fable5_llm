# R3-4 — the cost model's one-window assumption: stated, characterised, handed to the TB (no pricing change)

Task R3-4 of the R3 campaign (MOVX broadcast, form (a); plan `docs/superpowers/plans/2026-09-29-r3-broadcast.md`,
Task R3-4). Every number below is **MODEL** unless it names a board or chip-TB log; none does. Labels: **S** stated by a
cited source, **E** printed by a committed run, **D** derived by a committed script run on snoke, **T** transcribed.

## Verdict

**GREEN — no price moved.**

* **Why this is not a TDD task (plan review I-3).** `ref/seq_cost.py` already prices every MOVX by its length alone.
  The `_record_dur` MOVX row (`ref/seq_cost.py:314-315`, coefficients `ref/seq_cost.py:189`) never reads the
  channel, so a broadcast record (flags[7:4] = 0xF) is ALREADY priced as one unicast window of its length. No RED
  exists. The channel-keyed paths that would meet 0xF (the census's per-channel MOVX elision key, the pass's
  per-channel hazard bookkeeping) are R3-5's, and its RED covers them.
* **The assumption, stated** where the code is: the module docstring (`ref/seq_cost.py:78-91`) and a comment at the
  MOVX pricing site (`ref/seq_cost.py:310-315`). Its text: a broadcast MOVX costs ONE MOVX window; the siblings it
  replaces cost zero; this is the spec §1.3 (a) pricing (**S**,
  `docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md:330`) and the plan's default, which the chip TB tests
  (R3-9a's one-window measurement on the coverage streams, R3-9b's measured saving on the r3 streams, both after
  R3-7's committed prediction).
* **Characterised.** `seq_cost --selftest` gains section (d), labelled **CHARACTERISATION (passes at base, not a
  RED)** (`ref/seq_cost.py:569-595`):
  * `MOVX_BCAST` = 0xF;
  * a broadcast x4096 = the unicast = (4216, 0), and x12288 = (12507, 0);
  * one broadcast x4096 in a segment = 4216, four unicasts x4096 = 4 × 4216 = 16,864.
  * It PASSED at the base commit before it was added: the same four checks, run by the committed tool against the
    unedited module (**E**, `evidence/qwen9b/sr/n2600_r3_4_char_AT_BASE.log:6-11`, tree 68f7fd8).
* **Selftest count before → after: 21 passed / 0 failed → 25 passed / 0 failed**; the 4 added lines are the
  characterisation, nothing else moved (**E**, `evidence/qwen9b/sr/n2603_r3_4_selftest_count_BEFORE.log:31`,
  `evidence/qwen9b/sr/n2611_r3_4_selftest_count_AFTER_clean.log:36`).
* **No price moved — proof.** `seq_cost`'s rows (the scheduler's input) were computed for every record of all twenty
  w9 model_9b_s{1..4} streams (shipped, reordA, reordB, reordB_r1, reordB_r2; each FULL sha256 checked against its
  manifest) by the edited module AND by the base commit a299358's module:
  * every stream's rows are identical, 20/20 (**E**, `evidence/qwen9b/sr/n2612_r3_4_fingerprint_AFTER_vs_base_clean.log:11`
    … `evidence/qwen9b/sr/n2612_r3_4_fingerprint_AFTER_vs_base_clean.log:49`);
  * the static table (32 upper-case constants) is identical (`evidence/qwen9b/sr/n2612_r3_4_fingerprint_AFTER_vs_base_clean.log:9`);
  * the all-stream digest f788ab35… equals the base run's
    (`evidence/qwen9b/sr/n2607_r3_4_fingerprint_BEFORE.log:28`, `evidence/qwen9b/sr/n2612_r3_4_fingerprint_AFTER_vs_base_clean.log:50`).
  So no r0/r1/r2 schedule, stream or pin can move. `ref/scripts/reorder_e4.py --selftest` (its static pins) PASS
  (`evidence/qwen9b/sr/n2613_r3_4_reorder_selftest_clean.log:26`). `sw/chat_seq.py --selftest` is 407/1, the known
  [22] region-image baseline (`evidence/qwen9b/sr/n2616_r3_4_chat_seq_selftest_unset.log:35`).
* **The FENCE-convention correction (SR11b) is carried unchanged.** FENCE_REC 23 cycles per FENCE record, the per-class
  single-channel tail TAIL1 (default 28), and the CMD residual CMD_RESID_FRAC (`ref/seq_cost.py:213-236`) are not
  touched. They are in the 32-constant table the proof above checks. They enter predictions only
  (`reorder_e4.predict`), never the scheduler's rows.

## 1. The numbers R3-7 consumes (MODEL, D)

All derived by `evidence/qwen9b/sr/r3_4_cost.py --derive` from committed log lines, which it reads back and prints
(`evidence/qwen9b/sr/n2606_r3_4_derive.log:8-14`). It cross-checks them before deriving
(`evidence/qwen9b/sr/n2606_r3_4_derive.log:16-20`):

* n1600's R2/R3 makespans equal n120's rows;
* the census saving equals n1600's SAVE line;
* SAVE = siblings removed − lane-idle rise;
* siblings = 3 × carriers exactly, i.e. every live matvec has four live MOVX of one length.

The TB clock is the 250 MHz aclk: 1 ms = 250,000 cycles.

| quantity (per token, s1 token-4 loop body, form B) | cycles | ms TB | source |
|---|---|---|---|
| census row R1+R2 | 26,146,927 | 104.588 | `evidence/qwen9b/ov/n120_sr0_clock_sens.log:18` (**E**) |
| census row R1+R2+R3 (siblings free) | 24,102,767 | 96.411 | `evidence/qwen9b/ov/n120_sr0_clock_sens.log:19` (**E**) |
| sibling MOVX removed: 387 (129 broadcasts × 3), mean 6,273.43 cyc each, 75.00 % of the live MOVX window | 2,427,816 | 9.711264 | `evidence/qwen9b/sr/n2606_r3_4_derive.log:22` (**D**, from `evidence/qwen9b/sr/n1600_sr16_r3_census.log:20`) |
| lane idle on weight streams (rises) | +383,656 | +1.534624 | `evidence/qwen9b/sr/n2606_r3_4_derive.log:23` (**D**, from `evidence/qwen9b/sr/n1600_sr16_r3_census.log:36`) |
| **NET modelled saving** | **2,044,160** | **8.176640** | `evidence/qwen9b/sr/n2606_r3_4_derive.log:24` (**D**) |
| ratio R1+R2 / R1+R2+R3 | ×1.0848 (−7.818 % of R1+R2) | | `evidence/qwen9b/sr/n2606_r3_4_derive.log:25` (**D**) |
| per broadcast | 15,846.2 net (18,820.3 removed) | | `evidence/qwen9b/sr/n2606_r3_4_derive.log:26` (**D**) |

**How R3-7 should use it.** The primary form is measured-previous-rung minus the modelled absolute saving (the plan's
Global Constraints). The absolute saving is **2,044,160 TB cycles = 8.177 ms per token**. The ratio form (×1.0848) and
the census form go beside it.

**Caveats.** These are the plan's standing hazards, restated because they bind this number:

1. **Census convention, not SR11b's corrected one.** The 2,044,160 is OV1's census replay over BN1 windows. At R2, the
   corrected convention priced the r2 body 36,663 cycles above the census (26,183,590 vs 26,146,927,
   `evidence/qwen9b/sr/n1182_sr11b_r2_derive.log:27`). The corrected R3 value exists only once an r3 order exists
   (R3-5/R3-6) and `reorder_e4.predict` prices it. It is R3-7's to compute, not this task's.
2. **The pass's real broadcast node (R3-5) may move it.** The census zeroes the siblings with their own-channel
   dependencies. A real broadcast waits on the latest of the four channels' readers
   (`evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md:771-773`).
   * SR16's latest-of-four sensitivity gave the same makespan to the cycle
     (`evidence/qwen9b/sr/n1600_sr16_r3_census.log:32-34`).
   * Bank forcing is inferred, not modelled.
3. **The one-window pricing is the spec's assumption, untested.** R3-9a measures it and R3-9b measures the saving.
   Nothing in this task establishes it.
4. **DMA-queue stalls in a new order are not predictable** by an order-only rule. At 0.069 ms each, eight more would
   be ≈ 7 % of the saving (`evidence/qwen9b/sr/SR16_R3_DECISION.md:172-175`).

## 2. Diffs

| commit | what |
|---|---|
| 68f7fd8 | the tools, committed before first use: `evidence/qwen9b/sr/r3_4_cost.py` (`--char`, `--selftest-count`, `--fingerprint [--base]`, `--derive`; reads `ref/seq_cost.py` only) and `evidence/qwen9b/sr/r3_4_drift.sh` (the o3 wrapper; refuses a non-commit code base or doc base) |
| a299358 | tool fix after the first fingerprint run failed (n2604): the pass's OUTPUT streams (reordB_r1/_r2) fail `reorder_e4.segments`' input check (the JMP must close the last segment), so they are cut at every EMB and the JMP target (printed per stream). a299358 is the code base of every before/after comparison, and its `ref/seq_cost.py` is 68f7fd8's (sha256 d76b7c86…, `evidence/qwen9b/sr/n2607_r3_4_fingerprint_BEFORE.log:6`). |
| bbc891a | `ref/seq_cost.py`: docstring R3 paragraph (15 lines), MOVX-site comment (4 lines), selftest (d) (28 lines). No code path of the pricing changed. |
| 4a79cf7 | o3 cite-drift repair (§3) and logs n2600–n2623 |

## 3. Cite drift (bbc891a moved `ref/seq_cost.py`'s old lines 78–294 by +15 and 295 onward by +19)

The wrapper is `evidence/qwen9b/sr/r3_4_drift.sh`, with code base a299358 and doc base c2fdfb3; both are commits and the
wrapper refuses anything else.

* **Plan: REPAIR 16 / COLLATERAL 0, SAFE** (`evidence/qwen9b/sr/n2620_r3_4_drift_plan.log:15-16`).
* **Fix: 15 citations in 5 documents, digits only** (`evidence/qwen9b/sr/n2622_r3_4_drift_fix.log:20`). The plan's
  16 counts occurrences; `evidence/qwen9b/sr/SR11b_R2_PASS.md` cites the constants block twice, so there are 15 distinct
  (document, citation) pairs. The 16 occurrences by document:
  * the round plan: 2 cites;
  * the R3 plan: 4 cites, including this task's own `ref/seq_cost.py:314-315`, `ref/seq_cost.py:189`,
    `ref/seq_cost.py:399-401` and `ref/seq_cost.py:508`;
  * `evidence/qwen9b/ov/S1P_SHIP.md`: 4;
  * `evidence/qwen9b/sr/SR11b_R2_PASS.md`: 3;
  * `evidence/qwen9b/sr/SR4_R1_MODEL.md`: 3.
* **Verify: PASS over 22 citations, 15 relocated, 0 problems** — a non-zero count, read
  (`evidence/qwen9b/sr/n2623_r3_4_drift_verify.log:15-20`).
* **Excluded: `evidence/qwen9b/sr/SR11c_CITE_DRIFT.md`.** Its seq_cost tokens record where SR11c aimed each repair.
  They are historical and deliberately kept, and `--verify` cannot tell them from a missed repair (a known o3 defect,
  `NEXT_SESSION.md` §9 (f) item 11).
  They now name pre-R3-4 coordinates.
* **Also excluded:** the concurrent tasks' documents (R3-0, R3-3), none of which cites `ref/seq_cost.py`.
* **The per-document drift base.** Every live citation into `ref/seq_cost.py` was last verified against 0cf3f1f's
  version (SR11b fix round 1, SR11c), and a299358's file is byte-identical to it. So one code base serves every
  document.

## 4. Judgment calls

1. **The characterisation run at base is a committed TOOL, not the selftest.** The case cannot be in the base
   commit's selftest before it is written. `r3_4_cost.py --char` runs the same four checks against the unedited
   module (n2600, tree 68f7fd8) and, after the edit, against the edited one (n2614). The selftest's own (d) prints the
   same four PASS lines (n2611).
2. **The unchanged-cost proof is widened.** SR11b's (e) compared `cost_of_segment` on two synthetics. Here every row of
   twenty real streams is compared, plus the constant table. The shipped reorder pins are covered by
   reorder_e4's selftest (n2613).
3. **The r1/r2 streams are segmented by a fallback** (EMB cuts plus the JMP target) because the pass's input-side
   `segments()` refuses its own output. The proof needs only the SAME cut before and after, and it has one.
4. **Stale-NFS logs kept, superseded.** n2601, n2602, n2605 and n2609 stamp `bbc891a+dirty` with ` M ref/seq_cost.py`.
   snoke's git view lagged the commit made on darthplagueis. The file content already equalled the committed blob:
   sha256 99748832…, checked on snoke against `git show HEAD:ref/seq_cost.py`; the clean-tree run prints it at
   `evidence/qwen9b/sr/n2612_r3_4_fingerprint_AFTER_vs_base_clean.log:7`. They are kept as
   the record and superseded by n2611–n2614 on the clean tree a2ec680. a2ec680 descends from bbc891a; its only later
   changes are R3-3's TDD script and its log, neither an input to these runs.
5. **n2604 (fingerprint, rc 1) is kept as the failed first run** that found the segmentation refusal. n2607 is the
   BEFORE fingerprint of record.
6. **n2615 ran chat_seq's selftest at `FABLE5_MODEL=9b`**, which is the wrong operating point for that 0.8b selftest;
   it crashed in a template check. It was also on a tree dirty with R3-3's in-flight `ref/seq_model.py`. n2616 is the
   rerun as the baseline was run (unset, clean tree c2fdfb3): 407/1. Kept as the record.
7. **Log numbers n2608, n2610 and n2617–n2619 are unused.**
8. **One non-numeric command ran on darthplagueis:** a `python3 -c` that printed a manifest's JSON keys (parsing, no
   arithmetic). A second, `python3 - <<EOF`, applied the text edits to `ref/seq_cost.py` and the tool. No number here
   came from darthplagueis.

## 5. What this does NOT establish

* That a form-(a) broadcast costs one MOVX window on the RTL. R3-9a measures it on the coverage streams and R3-9b on
  the r3 streams.
* The corrected-convention R3 saving: it needs the r3 order (R3-5/R3-6) and R3-7's run of `reorder_e4.predict`.
* Anything about the latest-of-four dependency beyond SR16's sensitivity, bank forcing, DMA-queue stalls, or the
  board.

## 6. Logs

| log | what |
|---|---|
| `evidence/qwen9b/sr/n2600_r3_4_char_AT_BASE.log` | characterisation at base (68f7fd8): 4/4 PASS |
| `evidence/qwen9b/sr/n2603_r3_4_selftest_count_BEFORE.log` | seq_cost selftest before: 21/0 |
| `evidence/qwen9b/sr/n2604_r3_4_fingerprint_BEFORE.log` | first fingerprint, rc 1 (segmentation refusal; judgment call 5) |
| `evidence/qwen9b/sr/n2606_r3_4_derive.log` | the R3-7 numbers (§1) |
| `evidence/qwen9b/sr/n2607_r3_4_fingerprint_BEFORE.log` | fingerprint before (a299358) |
| n2601 / n2602 / n2605 / n2609 | after-edit runs on the stale-NFS `+dirty` view (judgment call 4) |
| `evidence/qwen9b/sr/n2611_r3_4_selftest_count_AFTER_clean.log` | seq_cost selftest after: 25/0 |
| `evidence/qwen9b/sr/n2612_r3_4_fingerprint_AFTER_vs_base_clean.log` | every row of 20 streams and the table = base's |
| `evidence/qwen9b/sr/n2613_r3_4_reorder_selftest_clean.log` | reorder_e4 selftest PASS |
| `evidence/qwen9b/sr/n2614_r3_4_char_AFTER_clean.log` | characterisation after: 4/4 PASS |
| n2615, `evidence/qwen9b/sr/n2616_r3_4_chat_seq_selftest_unset.log` | chat_seq selftest (n2615 wrong env, kept; n2616 407/1) |
| n2620 – n2623 | cite drift: plan, check, fix, verify |
| n2630, n2699 | spec_cites precheck, then LAST, alone, on the committed tree |
