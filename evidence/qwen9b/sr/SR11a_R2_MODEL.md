# SR11a — R2's contract, the validator's device-keyed admission and the model's running ranges

Task SR11a of `docs/superpowers/plans/2026-09-27-seq-rtl-round.md`. The contract is
`docs/SEQ_ISA.md` v2.3 §B17.2 (`docs/SEQ_ISA.md:1498-1587`), written here from spec §1.2
(`docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md:191-306`). No RTL, no build, no board.
Every run was on snoke through `evidence/qwen9b/sr/sr_run.sh`, log block n1100–n1149.

**Verdict: GREEN.**
* **Test-first.** RED is 31 passed / 28 failed (`evidence/qwen9b/sr/n1113_sr11a_tdd_RED_fixed.log:177-178`).
  GREEN is 59/59 on the committed tree d501068 (`evidence/qwen9b/sr/n1101_sr11a_tdd_GREEN.log:76-77`).
* **The shipped streams at r0 still gate 2358/2358**, ALL BIT-EXACT, tokens IDENTICAL, with the running-range
  refusals armed (§3).
* **Caps-keyed refusal holds.** Every R2 record is refused at caps {} and at {R1}, and admitted at {R1,R2}
  (`evidence/qwen9b/sr/n1101_sr11a_tdd_GREEN.log:40-43`).
* **The zero-bank model is today's.** It is bit-identical to the e3c2ff1 model on the synthetic streams
  (`evidence/qwen9b/sr/n1101_sr11a_tdd_GREEN.log:49-60`), and the four shipped gates agree.
* **isa_bits** PASS before and after the change: 348 × 29, negative control 19 of 19 (§4).

## 1. The diffs

**The contract: `docs/SEQ_ISA.md` §B17.2.**
* The encoding table (`docs/SEQ_ISA.md:1507-1520`) follows spec §1.2 verbatim. MOVX target[11:0] is the XWIN start
  word (0..3071; bank 1 is word 1536). MVGO SHAPE bit 29 is XBANK and bit 30 is RBANK. MOVY target[15:4] is the
  RES start row. Bit 31 stays spare, and MOVX target[15:12] is reserved.
* The range rules, err 0x06 (`docs/SEQ_ISA.md:1521-1525`), and the bank-legality rule, K ≤ 6144 for XBANK and
  nrows ≤ 2048 for RBANK (`docs/SEQ_ISA.md:1527-1533`). The section states that bank legality is enforced by the
  validator only on silicon; the engine's twin is a sim-only $fatal.
* **NO RTL INTERLOCK: running ranges** (`docs/SEQ_ISA.md:1541-1556`), in the B17.1 style. The section also states
  that the model is stricter than the RTL about what a MVGO or MOVY may read.
* The validator rule (`docs/SEQ_ISA.md:1558-1577`) and **FORWARD COMPATIBILITY — NOT fail-closed**
  (`docs/SEQ_ISA.md:1579-1587`). The only guard is admission at the DEVICE's caps (B17.0). An R2 record is refused
  at {} and at {R1}.

**The validator: `ref/seq_format.py`.**
* The R2 constants are derived, not re-typed: XWIN_WORDS = MVGO_MAX_NG·32 = 3072, XBANK_WORD 1536,
  RES_ROWS = hwmap.RES_DEPTH, RBANK_ROW 2048, SHAPE_XBANK/SHAPE_RBANK, and `movx_words` (ceil(len/4))
  (`ref/seq_format.py:527`, `ref/seq_format.py:537`).
* **MOVX** (`ref/seq_format.py:600-617`). Without R2, target must be 0 (today's rule). With R2, target[15:12] must
  be 0, and start word + ceil(len/4) ≤ 3072 with start ≤ 3071.
* **MVGO SHAPE** (`ref/seq_format.py:618-645`). Bit 31 is refused always. Bits 29/30 are refused without R2. With
  R2, XBANK needs ng ≤ 48 and RBANK needs nrows ≤ 2048. The clause applies whenever the caller has NOT stated the
  frozen isa=1 layout (§5 item 1).
* **MOVY** (`ref/seq_format.py:671-681`). Without R2, target[15:4] must be 0 (today's rule). With R2, start row +
  len ≤ 4096.
* Without R2 no rule changed, except the new SHAPE bit 29/30/31 refusal, which the brief requires.

**The model: `ref/seq_model.py`.**
* **Storage as the RTL keeps it.** `XWinMem` (`ref/seq_model.py:478`) holds a 12,288-byte x_mem per channel, and
  `ResMem` (`ref/seq_model.py:544`) a 4,096-row RES per channel.
  * A MOVX writes at its start word.
  * A MVGO reads x at word 1536·XBANK and writes its rows at 2048·RBANK.
  * A MOVY reads from its start row.
* **Both keep today's dict face** (`xwin[c] = v`, `.get`, `[]`, `.items()`; `res[c]` = the latest MVGO's rows).
  Three callers need it unchanged: `evidence/qwen9b/g3/isa_bits.py:1318`, `evidence/qwen9b/sr/sr4_r1_tdd.py:159`,
  and the model's own W8/repack selftests.
* **Running ranges** (`ref/seq_model.py:676`). `running` is chan → (x word lo, hi, RES row lo, hi) of the pending
  stream. Its keys are the running channels, so `c in running` and `sorted(running)` work as before.
  * **MVGO:** refused on ANY pending stream (`ref/seq_model.py:961`).
  * **MOVX:** refused only on overlap with the pending x range (`ref/seq_model.py:944`).
  * **MOVY:** refused only on overlap with the pending RES range (`ref/seq_model.py:1035`).
  * Each refusal is an explicit `raise RunningChannelError`. An EMPTY access range counts as overlapping
    (`ref/seq_model.py:471`), so a zero-length MOVX/MOVY on a running channel is refused exactly as today.
* **The FENCE arm** pops the masked channels (`ref/seq_model.py:1122`).
* **The SHAPE-spare assert** admits bits 29/30 only under R2 and never bit 31 (`ref/seq_model.py:995`).
* **The executor's per-record validate** now states the frozen isa=1 layout when the SeqExec runs isa=1
  (`ref/seq_model.py:1064`). Otherwise the layout stays unstated, so the ng envelope stays off, as before.
* **The refusal selftest** gains five r2_ streams at caps {R1,R2} (`ref/seq_model.py:1895-1906`): two legal (the
  other bank; draining bank 0 while an RBANK stream runs) and three hazards. The result is 11/11 hazards refused,
  also under `python -O` (`evidence/qwen9b/sr/n1104_model_refusal_selftest.log:6`,
  `evidence/qwen9b/sr/n1114_model_refusal_selftest_O.log:6`).

## 2. RED → GREEN (`evidence/qwen9b/sr/sr11a_r2_tdd.py`)

| case | what | RED n1113 | GREEN n1101 |
|---|---|---|---|
| (a) | bank-1 MOVX over a pending bank-1 read → refused (whole, partial); bank-1 MOVX while a bank-0 stream runs → admitted and the XBANK MVGO computes on the bank-1 x; K = 12288 pending spans both banks → bank-1 MOVX refused; MVGO in the other banks refused; other channel free | 1/6 | 6/6 |
| (b) | MOVY over the pending RES range → refused (row 2048, partial 2046.., row 0 under RBANK 0); MOVY of the other half while the RBANK stream runs → admitted, reads the earlier stream's rows; never-written rows → assert | 1/5 | 5/5 |
| (c) | validator at {R1,R2}: XBANK ng 96/49 refused, 48 admitted; RBANK 2049 refused, 2048 admitted; MOVX and MOVY ranges at their edges (ragged tail counts; start 3072 refused; target[15:12] refused); bit 31 refused at every caps | 9/19 | 19/19 |
| (d) | XBANK MVGO, RBANK MVGO, MOVX word 1536, MOVY row 2048: refused at {R1} and {} (layout stated or not), admitted at {R1,R2} and {R2}; validate_stream the same; the model at {R1} refuses an R2 stream before executing it; a frozen isa=1 W8 word still validates at shape_isa=1 | 2/7 | 7/7 |
| (e) | zero banks == today: the same streams on the e3c2ff1 model (loaded from git) and on this tree — machine state, stats, running set, XWIN and RES views bit-identical; the same refusals | 12/12 † | 12/12 |
| (f) | the model's SHAPE-spare assert: 29/30 refused without R2, admitted with it; bit 31 never | 2/3 | 3/3 |
| (g) | explicit `raise RunningChannelError` in _movx/_mvgo/_movy; the refusal selftest carries r2_ cases and passes | 1/2 | 2/2 |
| (h) | B17.2 states the encoding, ranges, legality, err 0x06, NOT fail-closed, the caps rule | 0/2 | 2/2 |
| (i) | the shipped s1 stream (sha256 9760899d…) validates, every record, at {}, {R1}, {R1,R2} | 3/3 | 3/3 |

† (e) passes at RED by construction: on the pre-change tree both sides are the same model.
It is the regression half of the test.

**n1100 is a failed attempt, kept as the record.** In it, the (e) "mixed" stream put its MOVY destinations inside a
later MOVX source. That made both models fail on the int8 source assert, a vacuous compare. The test was fixed
before any implementation (commit 9f0064a). The destinations moved to 20000+, and (e) now requires a legal
stream to actually run. n1113 is the valid RED; its counts are the same as n1100's
(`evidence/qwen9b/sr/n1100_sr11a_tdd_RED.log:177-178`).

## 3. The four shipped streams at r0, refusals armed (spec §4.1 rung 2)

| seed | log | caps | CHECKPT | tokens |
|---|---|---|---|---|
| s1 | `evidence/qwen9b/sr/n1105_gate_shipped_s1_r0.log:17` | none | 2358/2358 ALL BIT-EXACT | IDENTICAL (`evidence/qwen9b/sr/n1105_gate_shipped_s1_r0.log:21`) |
| s2 | `evidence/qwen9b/sr/n1106_gate_shipped_s2_r0.log:17` | none | 2358/2358 | IDENTICAL (`evidence/qwen9b/sr/n1106_gate_shipped_s2_r0.log:21`) |
| s3 | `evidence/qwen9b/sr/n1107_gate_shipped_s3_r0.log:17` | none | 2358/2358 | IDENTICAL (`evidence/qwen9b/sr/n1107_gate_shipped_s3_r0.log:21`) |
| s4 | `evidence/qwen9b/sr/n1108_gate_shipped_s4_r0.log:17` | none | 2358/2358 | IDENTICAL (`evidence/qwen9b/sr/n1108_gate_shipped_s4_r0.log:21`) |
| s1 | `evidence/qwen9b/sr/n1109_gate_shipped_s1_capsR1R2.log:15` | {R1,R2} | 2358/2358 | IDENTICAL (`evidence/qwen9b/sr/n1109_gate_shipped_s1_capsR1R2.log:19`) |

* **The recipe.** n1105–n1108 are SR4's recipe, `evidence/qwen9b/ov/sv1_gate.sh` unchanged at caps none, on the
  committed tree d501068. It sets `FABLE5_MODEL=9b FABLE5_RS_F=7` itself, so the wrapper's env line reads "unset".
* **n1109 is an extra.** It runs the same s1 artifact at caps {R1,R2}, calling `ref/seq_model.py --gate` directly
  with the operating point in `env`.
* **What the gates prove.** Every shipped MOVX, MVGO and MOVY now runs through XWinMem, ResMem and the range checks,
  and the machine state is bit-exact against the .txt replay.

## 4. isa_bits, selftests and regressions

| run | before (pre-change tree 6a5a8b8) | after (d501068) |
|---|---|---|
| `evidence/qwen9b/g3/isa_bits.py` | PASS (`evidence/qwen9b/sr/n1110_isa_bits_BASE_HEAD.log:57`) | PASS, 348 × 29 (`evidence/qwen9b/sr/n1116_isa_bits_GREEN.log:46`, `evidence/qwen9b/sr/n1116_isa_bits_GREEN.log:54`) |
| `--negative-control` | 19 of 19 (`evidence/qwen9b/sr/n1111_isa_bits_negctl_BASE_HEAD.log:30-31`) | 19 of 19, PASS (`evidence/qwen9b/sr/n1117_isa_bits_negctl_GREEN.log:27-28`) |
| `--shape` | PASS (`evidence/qwen9b/sr/n1112_isa_bits_shape_BASE_HEAD.log:23`) | PASS (`evidence/qwen9b/sr/n1118_isa_bits_shape_GREEN.log:20`) |

* **The VNW ceiling row is untouched.** It still refuses the narrowed field in the negative control; no file of
  isa_bits was edited.
* **"RED-first on the encodings" is read as a before/after pair, not an injected failure.** isa_bits has no row for
  the R2 record fields (MOVX target, SHAPE 29/30, MOVY target[15:4]). They are record fields that no RTL decodes
  yet (SR12), and isa_bits is not this task's file.
* **What isa_bits does exercise.** Its section-6 SHAPE round trip drives `SeqExec._mvgo` through `xwin[0] = …`
  (`evidence/qwen9b/g3/isa_bits.py:1318`), which is why XWinMem keeps the dict face. Its unstated-layout ng row
  (`evidence/qwen9b/g3/isa_bits.py:915`) never sets bits 29–31, so the new SHAPE refusal leaves it passing.

| regression | result | log |
|---|---|---|
| `ref/seq_model.py --selftest` (W8, repack, state region, refusal) | PASS, rc 0 | `evidence/qwen9b/sr/n1115_model_selftest.log:13` |
| `evidence/qwen9b/sr/sr4_r1_tdd.py` (R1's test, on the new model) | 31/31 | `evidence/qwen9b/sr/n1119_sr4_tdd_regression.log:55` |
| `evidence/qwen9b/sr/sr2_isa_tdd.py` | 39/0 PASS | `evidence/qwen9b/sr/n1120_sr2_tdd_regression.log:47` |
| `sw/chat_seq.py --selftest` (operating point unset, as n423) | 407/1 | `evidence/qwen9b/sr/n1102_chat_seq_selftest.log:35` |
| boardfree | 2820/0, 85/0, 407/1 | `evidence/qwen9b/sr/n1103_boardfree.log:59`, `evidence/qwen9b/sr/n1103_boardfree.log:105`, `evidence/qwen9b/sr/n1103_boardfree.log:136` |

* **The boardfree triple is unmoved.** It equals SR6 fix 1's (`evidence/qwen9b/sr/n627_sr6fix1_boardfree.log:59`,
  `evidence/qwen9b/sr/n627_sr6fix1_boardfree.log:105`, `evidence/qwen9b/sr/n627_sr6fix1_boardfree.log:136`).
* **The one chat_seq FAIL is pre-existing:** the region-image check (`evidence/qwen9b/sr/n1102_chat_seq_selftest.log:33`),
  the same one SR4 recorded.

## 5. Judgment calls

1. **The SHAPE 29/30 refusal also applies when the layout is unstated.** `sw/seq_run.py` and `sw/chat_seq.py`
   validate with no `shape_isa`, and that is the board-admission path an R2 stream must not pass on build_041/042.
   * The cost: a frozen isa=1 W8 artifact (bit 29 = w8) now validates only when its caller states
     `shape_isa=1`.
   * `ref/seq_model.SeqExec` states it for isa=1 runs. `evidence/qwen9b/g3/g34_shape_isa_paths.py` passes the
     manifest's key. Test (d) checks the isa=1 W8 word.
   * **(Fix round 1, I2) The frozen 2B W8 board paths are REFUSED** until their callers state the layout. Bit 29
     is ambiguous without a stated layout: it is w8 on build_034/035 and XBANK on build_041 onward. The two
     affected paths:
     * `evidence/qwen2b/rd/RD_GATE.md` T4's `seq_run4` on build_035;
     * `evidence/qwen2b/rd/rd_chat2b.sh`, the `tb/scripts/w5/` W8 template through `sw/chat_seq.py`.

     `sw/seq_run.py` and `sw/chat_seq.py` must pass the DEVICE's layout (`hwmap.shape_isa_for_version` of its
     VERSION). That fix is scheduled as SR11a round 2, once SR7 stops editing `sw/seq_run.py`.
     **Fix round 2 did it (§8), and both paths are admitted again at build_035.**
   * **"Boardfree unmoved" does NOT cover these paths.** Boardfree never loads a w5 artifact.
2. **Bank legality and ranges apply only with R2.** Without R2 the validator gains no MOVX/MOVY range check (today's
   rules), because no pre-round RTL has one.
3. **The start word may be any word 0..3071; line alignment is not required.** The spec fixes only the range, and
   the RTL shim takes the word from the burst address.
4. **The model is stricter than the RTL about reads.**
   * A MVGO reads the vector of the last MOVX that started at its x word, and only while nothing overwrote it.
   * A MOVY must lie inside one live MVGO result.
   * With zero banks this is today's rule (one vector, one y per channel). An RTL stream that relies on stale
     x_mem or RES bytes is refused, not replayed.
   * **(Fix round 1, M1) Both refusals are explicit raises** of `UnwrittenReadError` (an AssertionError
     subclass), so they survive `python -O`. They were bare `assert`s in d501068.
   * The refusal selftest gains one case for each, refused ONLY by that error. §7 has the logs.
5. **An empty MOVX/MOVY range on a running channel is refused**, and a zero-row MVGO kills the segment at its
   start row. Both preserve today's behaviour exactly.
   * **(Fix round 1, M2) One tightening at r0 is NOT today's behaviour.** `XWinMem.write` now refuses a MOVX
     longer than 12,288 B (3072 words) EVEN WITHOUT R2. The old model stored any length silently, and failed only
     at a later MVGO's K check, if one came.
   * **No gated stream has such a MOVX.** SR4 gated the four shipped streams (n1105–n1108, 2358/2358) and the four
     r1 streams at {R1} on the model's `_movx` path. Here, the four shipped streams ran through this new model and
     passed, so none carries one.
   * **Not re-gated here: the r1 streams.** SR4 gated them before this change. Their largest MOVX is K = 12288
     (mlp_down), the same MOVX set as the shipped streams, since the pass only reorders records.
6. **The x range of a pending stream is ng lines**, i.e. the engine's reads (32·ng words from 1536·XBANK), not the
   MOVX's length.
7. **The citation drift was planned but not applied.** n1121: `--plan` finds REPAIR 194 / COLLATERAL 8 across about
   30 documents (`evidence/qwen9b/sr/n1121_sr11a_drift_plan.log:49-50`). The biggest groups are the spec, the plan,
   NEXT_SESSION.md, SR4_R1_MODEL.md and the G3/G4/OV1 docs, most of which cite the pre-R2 `ref/seq_model.py` mover
   lines. A `--fix` would rewrite files owned by concurrently running tasks (NEXT_SESSION.md is SR5b's), and the
   plan is UNSAFE (8 collateral). It is left to the controller as a separate step.
   * SEQ_ISA.md's own B17.1 cite (`ref/seq_model.py:455`, RunningChannelError) still holds, because nothing above
     line 455 moved.
   * Its three REPAIR tokens are B10/B11's historic cites of `ref/seq_format.py` (lines 694, 696 and 717 of the
     ISA). They were already off their named content before this task and are outside §B17.2.
8. **Rule slips (text only, no arithmetic):** darthplagueis ran `python3` for four search-and-replace edits and
   splices of the test, `ref/seq_model.py` and `docs/SEQ_ISA.md`. Every run was on snoke.

## 6. What this does NOT establish

* **No emitted r2 stream, no pass change.** Those are SR11b's (`ref/scripts/reorder_e4.py`), which consumes this
  validator and model unchanged.
* **No RTL.** SR12 must implement exactly B17.2: the two range checks as err 0x06, the MOVY start row, the MOVX
  start word, and csr_static_xbank/rbank.
* **The unit-TB golden generator's twin validator and executor are not updated**
  (`tb/scripts/gen_seq_unit_vectors.py`, a standing hazard of the plan). SR12/SR13 must land B17.2 there too; until
  then it refuses R2 records under its own rules.
* **The reorder pass's hazard assert** (`ref/scripts/reorder_e4.py`) is still per-channel, which is conservative.
  Making it range-aware is SR11b's.
* **The host paths already carry the device's caps** (SR6, SR7). No host file was touched here; an R2 stream is
  refused on every bitstream whose SEQ_CAPS lacks the r2 bit.
* **(Fix round 1) The frozen 2B W8 board paths do not run today.** `RD_GATE.md` T4's `seq_run4` and
  `evidence/qwen2b/rd/rd_chat2b.sh` are refused by the host validator until SR11a round 2 makes `sw/seq_run.py`
  and `sw/chat_seq.py` state the device's SHAPE layout (§5 item 1). **Superseded by fix round 2 (§8): both paths
  now pass the host checks on a build_035 mock. A board run of them on this tree is not established.**

## 7. Fix round 1 (the task review: I2, M1, M2 — own files only)

* **I2.** The two comments in `ref/seq_format.py` that said an unstated layout gets the pre-G3 behaviour are
  rewritten. They now say that a frozen isa=1 W8 stream validates ONLY with `shape_isa = SHAPE_ISA_PRE_G3`, and that
  the board callers must state `hwmap.shape_isa_for_version(VERSION)`, which is SR11a round 2.
  * §B17.2 now states the bit-29 ambiguity and that the two frozen 2B W8 board paths are refused; §5 item 1 says
    the same. The code commit is 90c7b22.
  * No host file was touched: `sw/seq_run.py` is SR7's until it stops editing.
* **M1.** The two stricter-read refusals are explicit raises of `UnwrittenReadError`, an AssertionError subclass.
  The refusal selftest gains `read_mvgo_no_intact_x` and `read_movy_outside_result`, each refused only by that
  error.

  | run | result | log |
  |---|---|---|
  | refusal selftest | 11/11 hazards, 2/2 unwritten reads, PASS | `evidence/qwen9b/sr/n1141_sr11afix1_refusal_selftest.log:11` |
  | the same under `python -O` | PASS | `evidence/qwen9b/sr/n1142_sr11afix1_refusal_selftest_O.log:11` |
  | `ref/seq_model.py --selftest` | PASS | `evidence/qwen9b/sr/n1145_sr11afix1_model_selftest.log:17` |
  | TDD | 59/59 | `evidence/qwen9b/sr/n1143_sr11afix1_tdd_GREEN.log:81-82` |
  | isa_bits | PASS | `evidence/qwen9b/sr/n1144_sr11afix1_isa_bits.log:59` |

  * **How the TDD changed.** Its (e) compare maps `UnwrittenReadError` to the base model's bare AssertionError for
    the same stream, so `movy_past_rows` stays "both AssertionError". Its (b) never-written-rows case now requires
    `UnwrittenReadError` by name (`evidence/qwen9b/sr/n1143_sr11afix1_tdd_GREEN.log:23`).
* **M2.** §5 item 5 discloses that `XWinMem.write` refuses a MOVX longer than 12,288 B even without R2.
* **Stamps.** n1141–n1145 carry `90c7b22+dirty`. The dirty files are this round's uncommitted `docs/SEQ_ISA.md` and
  this gate doc, plus SR7's `NEXT_SESSION.md`, `docs/USAGE.md` and its `evidence/qwen9b/sr/sr7_incr_verify.sh`.
  Every code file was committed at 90c7b22. The only one of these files a run reads is `docs/SEQ_ISA.md`, in TDD
  (h), and there §B17.2 only grew.
* **The shipped gates were not re-run.** The M1 change turns two asserts into explicit raises that fire on the same
  conditions, which the shipped streams never reach (§3).
* **Rule slip, again text only.** The M1 edit of `ref/seq_model.py` was a `python3` search-and-replace script on
  darthplagueis. No arithmetic ran there.
* **Cites re-aimed.** The M1 class and the I2 comments moved lines in both ref files. After n1146 (spec_cites
  FAIL 0, but at the pre-move coordinates, a drift that stays in range and that spec_cites cannot see), every
  `ref/seq_model.py`, `ref/seq_format.py` and §B17.2 cite in this doc was re-aimed by hand to its current line.
  * n1146 is kept as the record. n1147 is the LAST run.
  * `ref/seq_model.py:455` (RunningChannelError) did not move.

## 8. Fix round 2 (review I1: the SHAPE layout is keyed by the device at the board-admission sites)

**Why.** Since SR11a, `ref/seq_format.py` refuses MVGO SHAPE bits 29/30 whenever no layout is stated; that refusal
is the R2 guard. Bit 29, though, is w8 on build_034/035 and XBANK on build_041 onward. With no layout stated, the
frozen 2B W8 board paths (RD_GATE T4's `seq_run4`; `evidence/qwen2b/rd/rd_chat2b.sh`) were therefore refused.

**The fix (commit cfbf90f).** The layout is keyed by the device, exactly as the caps are.

`sw/seq_run.py`:
* `Artifacts` and `relocate` take `shape_isa` (`sw/seq_run.py:365`, `sw/seq_run.py:661`).
* **A SEQ run** validates at `hwmap.shape_isa_for_version(VERSION)` for the VERSION the identity gate just
  admitted (`sw/seq_run.py:3456-3473`).
  * The value is cross-checked against that VERSION's SEQ_VERSIONS row.
  * An unknown VERSION is refused before any DMA.
  * `--shape-isa` on a SEQ run is refused.
* **`--dry-run`** states `--shape-isa` (`sw/seq_run.py:3363`) or nothing. With nothing stated, a stream that sets
  bit 29/30 is refused, and the message names `--shape-isa`.
* **SEQ_VERSIONS gains build_035** (`sw/seq_run.py:185`): 0x54443B9F, isa=1, expected SEQ_CAPS 0xDEADC0DE (the
  pre-round read default). It is admitted only when named, with `--expect-version 54443b9f`.
  * SR7 fix 1 saw this row while it was in flight and added its BM_IDENT expectation to `sw/hwmap.py` (commit
    c8aef0e).

`sw/chat_seq.py`:
* **`--shape-isa`** (`sw/chat_seq.py:6894`) is the layout the session is built at before the board is open. The
  default is the artifact's own `shape_isa` key; 9B artifacts carry 2.
* **Every session validation runs at that layout:** the template, the independent slices, the form-B images and the
  relocation (`sw/chat_seq.py:2558`, `sw/chat_seq.py:2701`, `sw/chat_seq.py:2742`, `sw/chat_seq.py:2851-2860`).
* **`open_board` re-keys to the device's layout** (`sw/chat_seq.py:2793`). It refuses, before any upload, a
  session that was built at a different layout.
* **A layout refusal is now a clean ChatSeqError** that names `--shape-isa` (`sw/chat_seq.py:2754-2776`). Before,
  a SeqValidationError escaped uncaught.

`ref/seq_chat.py`:
* `Templates` and `TurnCompiler` take a stated `shape_isa` (`ref/seq_chat.py:359`, `ref/seq_chat.py:387`,
  `ref/seq_chat.py:548`). A stated layout that contradicts the artifact's own key is refused.
* This is one file beyond the brief's list. The chat path cannot be admitted without it: agent A's TurnCompiler
  validates its step images with the layout taken from the artifact's meta, and the W8 template carries no key.

**Test-first** (`evidence/qwen9b/sr/sr11a_fix2_host_tdd.py`, on SR6's mock SEQ window). RED is 3 of 11
(`evidence/qwen9b/sr/n1149_sr11afix2_tdd_RED.log`); GREEN is 12 of 12 (`evidence/qwen9b/sr/n1149b_sr11afix2_tdd_GREEN.log:64-65`).

| case | what | GREEN |
|---|---|---|
| (a) | the frozen 2B W8 artifact (`tb/scripts/w5/model_w8_2b_s1.e`, T4's `--four-chan`) LOADS at build_035's VERSION with caps {}, validated at isa=1 | 2/2 |
| (b) | an XBANK record is REFUSED at build_041's VERSION with caps {} and at build_044_r1_incr's with caps {R1}, naming R2 | 2/2 |
| (c) | the same stream LOADS on a mock that reports caps {R1,R2} (a SEQ_VERSIONS row that exists only in the test) | 1/1 |
| (d) | a dry-run of the W8 artifact without `--shape-isa` is REFUSED, naming `--shape-isa`; with `--shape-isa 1` it proceeds; `--shape-isa` on a SEQ run is refused | 3/3 |
| (e) | chat_seq with FABLE5_MODEL=2b, following `evidence/qwen2b/rd/rd_chat2b.sh`'s recipe (`FABLE5_SEQ_EXPECT_VERSION=54443b9f`), is checked three ways: it loads with `--shape-isa 1` (reaches bring_up); it is refused without it (clear message, naming `--shape-isa`); and a session built at isa=1 is refused on an isa=2 device | 3/3 |
| (f) | on a SEQ run every seq_run validate_stream call states isa=2 on build_041 (spy) | 1/1 |

**RED details.**
* (b) and (c) already passed at RED, because the R2 guard itself held.
* The (f) check of the first dev run was wrong: it counted the fixture writer's own validation. It was fixed
  before GREEN.

**Regressions.**

| run | result | log |
|---|---|---|
| SR6's host TDD | 45/45, green again | `evidence/qwen9b/sr/n1149c_sr6_host_tdd_GREEN.log:133-134` |
| seq_run selftest | 2820/0 | `evidence/qwen9b/sr/n1149d_seq_run_selftest.log:55` |
| chat_seq selftest | 407/1, the known region-image FAIL | `evidence/qwen9b/sr/n1149e_chat_seq_selftest.log:34-36` |
| boardfree | 2820/0, 85/0, 407/1, unmoved | `evidence/qwen9b/sr/n1149f_boardfree.log:61`, `evidence/qwen9b/sr/n1149f_boardfree.log:107`, `evidence/qwen9b/sr/n1149f_boardfree.log:138` |
| SR11a TDD | 59/59 | `evidence/qwen9b/sr/n1149g_sr11a_tdd_regression.log:77-78` |

* **SR6's script had two kinds of breakage** at 899f03e (`evidence/qwen9b/sr/n1148_sr6_host_tdd_HEAD.log`):
  * Six by-design failures, plus an abort in (m). Since SR7 the identity gate compares SEQ_CAPS against the
    VERSION's row, and SR6's mocks put the R1 word on build_041's VERSION.
  * **The fix:** the R1 mocks moved to build_044_r1_incr's VERSION 0xE3C2FF1E, named, through
    `make_dev(expect=, use_env=)`.
  * **The unknown-bit case (m)** is now refused by the gate's raw word compare. The decoder's by-bit refusal is
    checked directly.

**Citation drift.**
* **The plan.** `--plan` finds REPAIR 293 / COLLATERAL 13 across the repo
  (`evidence/qwen9b/sr/n1149h_sr11af2_drift_plan.log`), because `sw/seq_run.py` and `sw/chat_seq.py` are cited
  everywhere.
* **What was fixed.** Only NEXT_SESSION.md, the doc this round edits, was fixed: 26 tokens
  (`evidence/qwen9b/sr/n1149k_sr11af2_drift_fix_nextsession.log`). n1149j is the refused first attempt, kept.
  * Three COLLATERAL tokens were cleared by hand, with the reasons recorded in that log.
  * `sw/seq_run.py:121` was already stale before this pass. It now reads `:127`, where EXPECTED_SEQ_VERSION sits.
* **The verify.** `--verify` then lists NEXT_SESSION only for that deliberate `sw/seq_run.py:127`
  (`evidence/qwen9b/sr/n1149l_sr11af2_drift_verify_nextsession.log:14`). Every other document's drift, including
  `docs/USAGE.md`'s 2 tokens, is left for a dedicated pass, as in rounds 0 and 1.

**Log names.** The block n1100–n1149 ran out at n1149, and n1150+ is SR11b's. This round's logs after n1149
therefore carry letter suffixes (n1149b…n1149m): still this task's block, and they cannot collide.

**Not established.**
* **No board run** of the frozen 2B W8 path on this tree. Everything above is mocks: the SEQ window and the DMA are
  tripwires.
* **Whether the HEAD host tools drive build_035 end to end** (upload, run, the post-halt reads) is not tested here.
  T4 ran on an older tree (dcdf5cd).
* **Cites re-aimed (round 2).** The §B17.2 frozen-path sentence grew by 3 lines, so this doc's three B17.2 range
  cites that follow it were re-aimed by hand.

## 9. Fix round 3 (the round-2 re-review: I1, I2, m4, m6)

**I1: build_042_bm1 was refused.** Round 2 keyed the layout by VERSION through `hwmap.shape_isa_for_version`, but
`hwmap.SHAPE_ISA_BY_VERSION` had no row for the measurement bitstream 0x9B588E78. Both seq_run and chat_seq's
`open_board` therefore refused it.
* **The fix:** the row `0x9B588E78: SHAPE_ISA_9B` (`sw/hwmap.py:104`).
* **The guard:** `seq_run --selftest` now asserts that every SEQ_VERSIONS key has an hwmap row with the same layout
  (`sw/seq_run.py:2910`). The selftest count moves 2822 → 2823: 2822 is SR7 fix 1's
  (`evidence/qwen9b/sr/n758_SR7fix1_seq_run_selftest.log`), and 2823 is `evidence/qwen9b/sr/n1149t_seq_run_selftest.log:54`.

**I2: seq_run never compared an artifact's declared layout with the device's.**
* `Artifacts` now refuses, before any DMA, a `meta["shape_isa"]` that differs from the layout the stream is
  validated at: the device's on a SEQ run, `--shape-isa` on a dry-run (`sw/seq_run.py:389`). This mirrors
  `ref/seq_chat.Templates`.
* An artifact with no key, such as the frozen W8 ones, is validated at the stated layout alone.

**m6.** The dead `row is not None` guard is now a hard assert with a message (`sw/seq_run.py:3479`).

**m4.** Round 2's (d) check now reads the refusal itself for the `--shape-isa` hint, not the status line printed
before it. It passed at once (`evidence/qwen9b/sr/n1149p_sr11afix2_tdd_m4_RED.log`): the hint was in the refusal
all along, and the old check was merely weak.

**Test-first** (`evidence/qwen9b/sr/sr11a_fix3_host_tdd.py`, mocks only). RED is 3 of 8
(`evidence/qwen9b/sr/n1149o_sr11afix3_tdd_RED.log`); GREEN is 8 of 8 on fa7f5df
(`evidence/qwen9b/sr/n1149q_sr11afix3_tdd_GREEN.log:30-31`).

| case | what | RED | GREEN |
|---|---|---|---|
| (A) | build_042_bm1 (0x9B588E78; SEQ_CAPS 0xDEADC0DE, BM_IDENT 0xFAB1B301), named with `--expect-version 9b588e78`: a 9B artifact LOADS | 0/1 | 1/1 |
| (B) | chat_seq `open_board` on a stub session admits it: the device's layout isa=2 reaches `admit_caps` | 0/1 | 1/1 |
| (C) | a declared-9B artifact at build_035 is REFUSED, naming both layouts; an isa=1-declared artifact at build_041 is REFUSED; a 9B artifact at 041 and at 044 LOADS; the keyless W8 artifact at 035 LOADS | 3/5 | 5/5 |
| (D) | every SEQ_VERSIONS key has an agreeing hwmap row | 0/1 | 1/1 |

**Regressions** (all on fa7f5df or d39c587, a clean tree):

| run | result | log |
|---|---|---|
| fix 2 TDD | 12/12 | `evidence/qwen9b/sr/n1149r_sr11afix2_tdd_regression.log:61-62` |
| SR6's host TDD | 45/0 | `evidence/qwen9b/sr/n1149s_sr6_host_tdd.log:133` |
| seq_run selftest | 2823/0 | `evidence/qwen9b/sr/n1149t_seq_run_selftest.log:54` |
| hwmap selftest | PASS | `evidence/qwen9b/sr/n1149u_hwmap_selftest.log:6` |
| chat_seq selftest | 407/1 (the known region-image FAIL) | `evidence/qwen9b/sr/n1149v_chat_seq_selftest.log:33-35` |
| boardfree | 2823/0, 85/0, 407/1 | `evidence/qwen9b/sr/n1149w_boardfree.log:60`, `evidence/qwen9b/sr/n1149w_boardfree.log:106`, `evidence/qwen9b/sr/n1149w_boardfree.log:137` |

**Cites.** The round-3 edit moved lines in `sw/seq_run.py`, so §8's cites into it were re-aimed by hand. The
repo-wide drift from the host edits is unchanged in kind and still left for a dedicated pass. NEXT_SESSION.md is
not touched in this round (SR7 I-2 is in flight).

**Not established.** No board run was made on build_042_bm1 or build_035 from this tree.
