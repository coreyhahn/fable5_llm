# SR4 — R1 software: the reference model, the static cost model and the reorder pass emit masked fences

Task SR4 of `docs/superpowers/plans/2026-09-27-seq-rtl-round.md`. The contract
is `docs/SEQ_ISA.md` v2.3 §B17.1: bit c of FENCE target[3:0] is channel c,
mask 0 means all four channels, and a pending channel outside the mask stays
pending. There is **no RTL interlock**. The model's `RunningChannelError` and
the pass's hazard assert are the only guard, and both stay armed. This task
made no RTL change, ran no build and took no board action. Every run was on
snoke through `evidence/qwen9b/sr/sr_run.sh`.

**Verdict.**
* **Test-first.** RED is FAIL on (a)/(b)/(e)/(f)/(h)/(i)
  (`evidence/qwen9b/sr/n400_sr4_tdd_RED.log:108`). GREEN passes 31/31
  (`evidence/qwen9b/sr/n401_sr4_tdd_GREEN.log:54`).
* **Shipped streams.** All four still gate 2358/2358 at r0 with the refusals
  armed.
* **r1 streams.** All four gate 2358/2358 at caps {R1}, with tokens IDENTICAL
  to the shipped artifacts.
* **Model cycles.** The pass's r1 loop-body makespan is **27,136,513 TB
  cycles**, equal to OV1's R1 row to the cycle (**E**,
  `evidence/qwen9b/sr/n410_reorder_s1_B_r1.log:49` vs
  `evidence/qwen9b/ov/n120_sr0_clock_sens.log:17`).

## 1. The diffs, by line

**The reference model: `ref/seq_model.py`**
* SeqExec gains `caps=frozenset()` (`ref/seq_model.py:615`), normalised
  with `hwmap.seq_caps_check` (`ref/seq_model.py:682`). Every record
  is validated at that set (`ref/seq_model.py:1063`). The model is a software
  gate: the CALLER names the caps and the manifest is never read. With an
  empty set, a masked FENCE is refused exactly as today.
* **The FENCE arm** (`ref/seq_model.py:1116-1122`). Mask 0 clears `running`. A
  non-zero mask removes only the masked channels, so a channel the FENCE
  forgot stays running.
* **The three refusals are unchanged.** MOVX, MVGO and MOVY still raise
  `RunningChannelError` explicitly (`ref/seq_model.py:944`,
  `ref/seq_model.py:961`, `ref/seq_model.py:1035`), so they survive `python -O`.
* **The gate.** gate gains `caps=frozenset()` (`ref/seq_model.py:1369`) and passes the set to
  `validate_stream` and to `SeqExec` (`ref/seq_model.py:1435`). The CLI takes
  `--caps R1` (`ref/seq_model.py:2096`), and the gate prints the set it ran
  at.
* **The refusal selftest** gains four streams at caps {R1}
  (`ref/seq_model.py:1887`). One legal masked order, plus MOVX, MVGO and MOVY
  on a channel the mask skipped. Result: 8/8 hazards refused, also under
  `python -O` (`evidence/qwen9b/sr/n421_model_refusal_selftest.log:6`,
  `evidence/qwen9b/sr/n422_model_refusal_selftest_O.log:6`).

**The static cost model: `ref/seq_cost.py`**
* Pending streams now carry their channel (`ref/seq_cost.py:401`).
* A FENCE row drains only the masked group and prices its tail at
  `_tau(len(group))` (`ref/seq_cost.py:376`). Mask 0 prices exactly as
  before; test (h) checks this.
* The docstrings (`ref/seq_cost.py:35`, `ref/seq_cost.py:74`,
  `ref/seq_cost.py:339`) record the extrapolation. Masked groups of sizes 1
  and 3 take the nearest measured size, TAU[2] = 61. Size 3 is a tie between 2
  and 4, and a tie takes the smaller.
* Selftest: PASS (`evidence/qwen9b/sr/n420_seq_cost_selftest.log:30`).

**The pass: `ref/scripts/reorder_e4.py`**
* **`--rtl` r0 or r1** (`ref/scripts/reorder_e4.py:1148`; `RTLS`/`HEUR_R1`/`CAPS_OF` at `ref/scripts/reorder_e4.py:130-134`). Any other level is refused (r2 is SR11b's).
* **The schedule at r1** is OV1's per-channel-fence schedule with fence
  "perchan" and bottom-level priority, which is `run_sched`'s R1 row
  (`ref/scripts/reorder_e4.py:295`). `evidence/qwen9b/ov/ov_census.py` is
  unchanged and imported.
* **Fence placement** (`order_and_fences`, `ref/scripts/reorder_e4.py:335`).
  The r1 branch (`ref/scripts/reorder_e4.py:357`) emits ("FENCE", mask).
  The mask is exactly the channels of the unfenced MVGOs that the next
  record's stream-edges need, or every pending channel at the JMP, and only
  those channels are cleared. An MVGO onto a channel that still has an
  unfenced stream raises `ReorderError`.
* **The replay** drains only the masked channels
  (`ref/scripts/reorder_e4.py:394`). The emitted FENCE record carries
  target = mask (`ref/scripts/reorder_e4.py:554`).
* **The hazard assert is mask-aware** (`ref/scripts/reorder_e4.py:225`, the
  FENCE arm at `ref/scripts/reorder_e4.py:277`). Mask 0 still clears
  everything.
* **reorder, `rtl="r0"` by default** (`ref/scripts/reorder_e4.py:638`) refuses an
  input that already carries masked FENCEs
  (`ref/scripts/reorder_e4.py:648`), because OV1's `stream_durations` assumes
  the global drain.
* **Validation at r1** (`ref/scripts/reorder_e4.py:769`). The output is
  validated at caps {"R1"}, and the pass requires it to be REFUSED at the
  empty set.
* **The manifest** records `"seq_isa": "2.3"` and `"caps": ["R1"]` at r1
  (`ref/scripts/reorder_e4.py:864`). These are informational. Nothing new is
  written at r0.
* **r0 is byte-identical**, proven three ways (§2 (g)): the form-A pin, SV1's
  CSV pin, and the form-B image pins.

## 2. RED → GREEN (`evidence/qwen9b/sr/sr4_r1_tdd.py`)

| case | what | RED n400 | GREEN n401 |
|---|---|---|---|
| (a) | MVGO ch0+ch1, FENCE 0b0010, MOVX ch0 → `RunningChannelError` (+ ch2/ch3 twin) | 0/2 | 2/2 |
| (b) | the same with MVGO and with MOVY; MOVY ch1 after FENCE 0b0001 | 0/3 | 3/3 |
| (c) | FENCE 0b0011 then MOVX ch0 accepted; drained-channel MOVY accepted | 2/2 | 2/2 |
| (d) | mask 0 state == today's FENCE; 0b1111 == mask 0 | 2/2 | 2/2 |
| (e) | `assert_no_pending_hazard` refuses (a)'s order and the MVGO/MOVY/HALT variants; legal orders pass | 2/6 | 6/6 |
| (f) | r1 on `_synthetic()` and a two-channel synthetic, forms A/B: masks carried, replay ≤ r0, masks ⊆ pending, valid at {R1}, refused at ∅; manifest; masked input refused; r2 refused | 0/7 | 7/7 |
| (g) | r0 byte-identical: default == explicit r0; form-A pin b6ced3f9 (static); SV1's CSV pin 57ec3051 | 2/3 † | 3/3 |
| (h) | a mask-{c} FENCE costs `_tau(1)` = 61 over the masked stream only; mask 0 unchanged; documented | 2/4 | 4/4 |
| (i) | caps ∅ refuses a masked FENCE; `gate()` takes `caps=` | 1/2 | 2/2 |

RED is at `evidence/qwen9b/sr/n400_sr4_tdd_RED.log:108`; GREEN is at
`evidence/qwen9b/sr/n401_sr4_tdd_GREEN.log:54` (31 passed, 0 failed).

On RED, (a)–(d) ran through the script's fallback wrapper, which calls the
validator at caps {R1}. What RED shows is therefore the semantic gap (today's
FENCE clears every channel), not a TypeError.

† **The RED (g) failure was a bug in the test, not in the pass.** Its CSV pin
constant was mistyped by one dropped hex digit. The regenerated stream, the
file on disk and the SV1 pin all matched `57ec3051…`. The constant was fixed
in the commit after the RED log.

The same synthetic in both forms shows R1 working. Replay at r1 is 3403
cycles against 5468 at r0, with masks 0b0001 then 0b0010
(`evidence/qwen9b/sr/n401_sr4_tdd_GREEN.log`, case (f)).

**Selftests.**

| run | result | log |
|---|---|---|
| `reorder_e4.py --selftest`, including its static selftest | PASS | `evidence/qwen9b/sr/n402_reorder_selftest.log:24` |
| `sw/chat_seq.py --selftest` | 407/1 | `evidence/qwen9b/sr/n423_chat_seq_selftest_unset.log:35` |
| boardfree | 2810/0, 85/0, 407/1 | `evidence/qwen9b/sr/n404_boardfree.log:71`, `evidence/qwen9b/sr/n404_boardfree.log:117`, `evidence/qwen9b/sr/n404_boardfree.log:148` |

* **The one chat_seq FAIL is pre-existing.** It is the region-image check,
  and it is identical in the SR2 baseline
  (`evidence/qwen9b/sr/n290_sr2_boardfree_baseline_HEAD.log:150`).
* **Boardfree moved only upward.** The serve count went from SR2's 84/1 to
  85/0, which is SR2b's fix, not this task's.
* **The form-B pins regenerate unchanged.** `chat_seq --nch 4 --reorder B
  --reorder-check` regenerates the lite and full images equal to their pins,
  and the B6 exact replay passes (`evidence/qwen9b/sr/n419_chat_seq_reorderB_check_nch4.log:22`).

## 3. The four shipped streams at r0, refusals armed (spec §4.1 rung 2)

| seed | log | CHECKPT | tokens |
|---|---|---|---|
| s1 | `evidence/qwen9b/sr/n405_gate_shipped_s1_r0.log:17` | 2358/2358 | IDENTICAL (`evidence/qwen9b/sr/n405_gate_shipped_s1_r0.log:21`) |
| s2 | `evidence/qwen9b/sr/n406_gate_shipped_s2_r0.log:17` | 2358/2358 | IDENTICAL |
| s3 | `evidence/qwen9b/sr/n407_gate_shipped_s3_r0.log:17` | 2358/2358 | IDENTICAL |
| s4 | `evidence/qwen9b/sr/n408_gate_shipped_s4_r0.log:17` | 2358/2358 | IDENTICAL |

All four ran `evidence/qwen9b/ov/sv1_gate.sh` unchanged, at caps none. That
script sets `FABLE5_MODEL=9b FABLE5_RS_F=7` itself, so the wrapper's env line
reads "unset" for n405–n408.

## 4. The four r1 streams

The r1 streams were generated with the SV1 invocation plus `--cost csv --rtl
r1`. Today the pass defaults to the static cost table, so `--cost csv` is
written out explicitly. That was SV1's cost source, and it is the one n120's
R1 row used.

| seed | reorder log | records in → out | FENCE in → out | mask histogram (0001/0010/0100/1000) | stream sha256 | loop-body makespan (replay = scheduler) | gate at {R1} |
|---|---|---|---|---|---|---|---|
| s1 | `evidence/qwen9b/sr/n410_reorder_s1_B_r1.log:50` | 158536 → 160724 | 1372 → 5480 | 1372/1372/1368/1368 | 4e11a2ae…cb28 | 27,136,513 | 2358/2358, IDENTICAL (`evidence/qwen9b/sr/n414_gate_s1_reordB_r1.log:17`, `evidence/qwen9b/sr/n414_gate_s1_reordB_r1.log:21`) |
| s2 | `evidence/qwen9b/sr/n411_reorder_s2_B_r1.log:34` | 79289 → 80383 | 686 → 2740 | 686/686/684/684 | cc982e4f…bbd4 | 27,136,513 | 2358/2358, IDENTICAL (`evidence/qwen9b/sr/n415_gate_s2_reordB_r1.log:17`) |
| s3 | `evidence/qwen9b/sr/n412_reorder_s3_B_r1.log:34` | 79289 → 80383 | 686 → 2740 | 686/686/684/684 | 0f85a974…fe3b | 27,136,513 | 2358/2358, IDENTICAL (`evidence/qwen9b/sr/n416_gate_s3_reordB_r1.log:17`) |
| s4 | `evidence/qwen9b/sr/n413_reorder_s4_B_r1.log:50` | 158536 → 160724 | 1372 → 5480 | 1372/1372/1368/1368 | 492e0def…6c95 | 27,136,513 | 2358/2358, IDENTICAL (`evidence/qwen9b/sr/n417_gate_s4_reordB_r1.log:17`) |

* **The full sha256 values** are at `evidence/qwen9b/sr/n410_reorder_s1_B_r1.log:51`,
  `evidence/qwen9b/sr/n411_reorder_s2_B_r1.log:35`,
  `evidence/qwen9b/sr/n412_reorder_s3_B_r1.log:35` and
  `evidence/qwen9b/sr/n413_reorder_s4_B_r1.log:51`. The streams are gitignored
  and regenerable; SR5b re-checks them against these lines.
* **Every stream passed the pass's own checks.** The hazard assert passed
  (`evidence/qwen9b/sr/n410_reorder_s1_B_r1.log:45`). The stream was valid at
  {R1} and refused at ∅ (`evidence/qwen9b/sr/n410_reorder_s1_B_r1.log:48`).
  OV1's postcheck found 0 violations on every segment's emitted order: the s1
  loop body has 66,023 edges (`evidence/qwen9b/sr/n410_reorder_s1_B_r1.log:43`).
* **Every emitted mask is single-channel.** At r1 every stream is fenced on
  its own, just before its first consumer, so there is one FENCE per MVGO.

**Model vs OV1.** The pass's replay of the emitted s1 loop body is 27,136,513
TB cycles (**E**, `evidence/qwen9b/sr/n410_reorder_s1_B_r1.log:49`). That is
n120's B:R1 row to the cycle (**T**,
`evidence/qwen9b/ov/n120_sr0_clock_sens.log:17`). The same body at r0 (S1) is
28,612,019 (`evidence/qwen9b/ov/n32_reorder_s1_B.log:48`). This is the MODEL.
Whether the RTL executes it that way is SR5b's question.

**Cost-source dependence (fix round 1).** The r1 bytes and this makespan hold
for the cost source that made them, and only for it.
* **These streams use the CSV source.** They are `--cost csv`: BN1's timeline
  windows mapped by segment skeleton. Both the emitted ORDER and the replay
  makespan are functions of those windows.
* **r0 already shows the source matters.** The same pass at r0 gives two
  different pins by cost source: static costs give the form-A template
  `b6ced3f9…` (`sw/chat_seq.py` `REORDER4_BY_FORM`), and the CSV gives SV1's
  form-B stream `57ec3051…` (`evidence/qwen9b/ov/n32_reorder_s1_B.log:54`).
  These are different forms, but the pass itself does not decide the bytes;
  the cost source does.
* **The static r1 path has not been run on 9B.** `--rtl r1 --cost static` has
  run only on the synthetics of `sr4_r1_tdd.py`.
* **chat_seq's future r1 images (Task SR6) are a different lineage.** They
  will be reordered per image at static costs, as form B is today. Their
  model makespan is NOT 27,136,513. A later board or TB comparison must not
  apply n120's number to them; it must use the makespan the static pass
  prints for those images.

## 5. What this does NOT establish, and the concerns

* **This work does not show the RTL executes the masked streams as the model
  does, and gives no speed beyond the model's makespan.** Both are SR5b's.
  **No chip-TB run of any r1 stream exists yet.** Every r1 result above comes
  from the Python reference model and the pass.
* **OV1's form-B caveat carries forward to these streams.** OV1 §9 item 3
  (`evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md:749`) says there is no proof
  that form B's internal-resource list is complete. The r1 streams are form
  B, so an unlisted piece of layer-internal state could make them illegal
  even though the model gate passes. The chip TB (SR5b) is the final check,
  as it was for S1.
* **The r1 streams carry 4× the FENCE records: 5480 against 1372 on s1, +2188
  records.** OV1's model gives a FENCE no issue cost of its own beyond its
  poll tail. On the RTL each one costs decode plus F_SCAN's walk of 0..3 plus
  wr_idle. That per-record cost sits inside SR5b's "model held" band. It is
  not measured here.
* **The poll tail is priced by nearest neighbour.** Every r1 group has size 1,
  so the replay uses each MVGO's original-group tau (OV1's convention).
  `ref/seq_cost.py` prices size 1 at TAU[2] = 61. Neither value is measured
  for a single-channel poll. **No production path uses seq_cost's masked-group
  branch today.** The pass prices the r0 INPUT stream, whose FENCEs all have
  mask 0. The prediction above therefore prices each single-channel tail at
  the tau of the MVGO's original measured group (OV1's replay convention),
  never at TAU[2].
* **The pass reorders r0 streams only.** A masked input is refused, because
  OV1's FENCE groups assume the global drain.

**Rule slips and failed attempts, all kept:**
* python3 was invoked once on darthplagueis, for a text-only search-and-replace
  edit of `ref/seq_model.py`. No arithmetic and no run happened there; all
  later edits used the editor.
* `evidence/qwen9b/sr/n403_chat_seq_selftest.log` was run at
  `FABLE5_MODEL=9b` and died in a 9B template check. The selftest's operating
  point is unset, as n423 and boardfree use.
* `evidence/qwen9b/sr/n409_chat_seq_reorderB_check.log` was missing `--nch 4`;
  n419 is the valid run.

## 6. Fix round 1 (the task review's five minors)

* **§4: cost-source dependence.** The r1 bytes and makespan are CSV-lineage.
  The static r1 path has not been run on 9B. SR6's chat_seq images are a
  static lineage whose makespan is not n120's.
* **§5: no chip TB yet, and OV1 §9 item 3 carried forward.** No chip-TB run
  of any r1 stream exists yet, and OV1's form-B completeness caveat now
  applies to the r1 streams.
* **§5: the masked-group cost branch is unused.** It is used by no production
  path today, and the prediction uses each MVGO's original group tau.
* **The refusal selftest is tightened.** A hazard now counts as refused only
  on `RunningChannelError` (`ref/seq_model.py:1920`). Any other exception is
  recorded as "error" and fails the selftest (`ref/seq_model.py:1925`), so a
  `SeqValidationError` at the wrong caps cannot pass vacuously.
  * The re-runs pass 8/8, and 8/8 under `python -O`
    (`evidence/qwen9b/sr/n425_model_refusal_selftest.log:6`,
    `evidence/qwen9b/sr/n426_model_refusal_selftest_O.log:6`).
  * **Negative control** (`evidence/qwen9b/sr/sr4_refusal_negctl.py`). The
    same selftest with SeqExec's caps forced to the empty set reports the four
    r1_ cases as errors, counts 5/8 refused, and FAILS as it must
    (`evidence/qwen9b/sr/n427_refusal_negctl.log:11-12`).
* **Clean RED.** `evidence/qwen9b/sr/n428_sr4_tdd_RED_clean.log` ran the
  committed test against the pre-SR4 code.
  * **How.** A detached `git worktree` on snoke at aaefc54
    (`/tmp/sr4red_aaefc54`, removed afterwards) holds the test with the
    mistyped constant fixed. Its ref/, sw/ and evidence/qwen9b/ov/ are
    byte-identical to 1cccc51, as `git diff --quiet 1cccc51 HEAD` confirms
    (`evidence/qwen9b/sr/n428_sr4_tdd_RED_clean.log:6`).
  * **Gitignored inputs.** The two gitignored inputs, tb/scripts/w9/ and BN1's
    timeline CSV, are symlinked to the main tree's copies.
  * **The stamp.** The wrapper's stamp names the main tree (2f5b213), and line
    6 names the tree actually run.
  * **Result: 12 passed, 19 failed** (`evidence/qwen9b/sr/n428_sr4_tdd_RED_clean.log:112`).
    The failures are in (a) 0/2, (b) 0/3, (e) 2/6, (f) 0/7, (h) 2/4 and
    (i) 1/2. (g) is 3/3, since only the mistyped constant had failed it in
    n400.
