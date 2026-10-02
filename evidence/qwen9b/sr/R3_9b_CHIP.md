# R3-9b — the chip TB, part 2: the r3 streams against the committed prediction; the r3 chat images

Task R3-9b of `docs/superpowers/plans/2026-09-29-r3-broadcast.md` (brief
`.superpowers/sdd/2026-09-29-r3-broadcast/task-R3-9b-brief.md` with its controller addenda). No rtl/ or tb/
change, no rebuild, no Vivado, no board. Every run was on snoke through `evidence/qwen9b/sr/sr_run.sh`;
logs `n3150–n3183` plus the spec_cites log `n3199`. The binary is R3-9a's, re-hashed before the runs and
in every run log.

**Labels.** **E** printed by a run of this task, cited to its log line. **D** derived by a committed
script run on snoke (`evidence/qwen9b/sr/sr13a_derive.py` with the r3 flag, `evidence/qwen9b/sr/sr5b_chat_compare.py`
with the r3 flags). **T** transcribed from an earlier gate. Every speed number is the chip TB's or MODEL;
no number here is a board number.

## Verdict

**HELD — the stream prediction holds at +0.011 %. The campaign may proceed to R3-10 on this gate.**

* **s1 token-4 body window 24,129,766 cyc against P-A 24,127,093: +2,673 cyc = +0.011 % → HELD**
  (±0.5 %) (**D**, `evidence/qwen9b/sr/n3170_r3_9b_derive.log:36`). Against the corrected model's
  24,139,430 it is −0.040 %, inside the placement band (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:37`).
* **The measured saving r2 → r3 is 2,041,487 cyc = 8.166 ms/token, 99.87 % of the 2,044,160 cyc (8.177 ms)
  the census, R3-4 and R3-5 priced** (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:38`). This is the first real
  test of the one-window pricing, and it holds.
* **The one-window price is exact plus R3-9a's fixed +19.** Every real r3 broadcast window is the r2 unicast
  window of the same length plus 19.00 cyc (4,235.99 vs 4,216.99 at 4,096 bytes; 12,526.00 vs 12,507.00 at
  12,288). The MOVX class is 811,723 = 809,272 + 129 × 19 to the cycle (**D**,
  `evidence/qwen9b/sr/n3170_r3_9b_derive.log:122-124`). The fixed term (2,451 cyc/token) is 91.7 % of the
  +2,673 gap (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:70`).
* **s2–s4 HELD**: r3/r2 0.921983–0.921990 (< 1), within 0.0008 % of s1's on both ratios
  (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:42-44`). Each whole run is +0.011 % over its prediction
  (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:18`, :20, :22, :24).
* **4/4 PASS, tokens IDENTICAL to the shipped record; 774 broadcast X_END exits per run, landed == sent on
  every built channel** (§2). No $fatal, no token difference, no run failure.
* **×1.0846 vs r2, ×1.3588 vs shipped** (body window and whole run alike). **96.508 ms/token on the TB =
  9.910 tok/s MODEL** with OV1's uniform board factor, against r2's 9.137 (§3).
* **The r3 chat images: 8/8 PASS, tokens IDENTICAL on 4 scenarios, the shipped side equal to S1T's to the
  cycle, and all 16 lite/full launches −0.003 % against the committed chat prediction → HELD** (§5).

## 1. Order, identity, goldens

| item | result | cite |
|---|---|---|
| R3-7's prediction 82d2677 precedes the runs | 82d2677 IS AN ANCESTOR OF HEAD; 0 r3 chip runs before | **E** `evidence/qwen9b/sr/n3150_r3_9b_precondition.log:8`, `evidence/qwen9b/sr/n3150_r3_9b_precondition.log:11` |
| the binary | `tb/obj_dir_seq_chip_srr3b/tb_seq_chip_9b_srr3b` 54d174a4…8d32, equal to its build record | **E** `evidence/qwen9b/sr/n3151_r3_9b_identity.log:24` |
| the four r3 streams | FULL sha256 equal to the lines R3-5 wrote (s1 3e77e57c…, s2 4584810a…, s3 b282ca19…, s4 735a7388…) | **E** `evidence/qwen9b/sr/n3151_r3_9b_identity.log:25-41` |
| the r3 goldens at caps {R1,R2,R3} | each identical to the shipped golden except NREC/PC | **E** `evidence/qwen9b/sr/n3152_r3_9b_chipvec_s1_r3.log:24` and the same line of `n3153–n3155` |
| no other user of the binary | pgrep on snoke, kyloren and darthplagueis before the runs: none | **E** `evidence/qwen9b/sr/n3159_r3_9b_pgrep_prerun.log` |
| the chat-image prediction committed before the first chat run | n3157 at 5f1d4e2; the chat runs were launched from 5cb4e2f | **E** `evidence/qwen9b/sr/n3157_r3_9b_chat_prediction.log:102-103` |

## 2. The four r3 streams on the chip TB

Each run is `evidence/qwen9b/sr/run_sr_chip.sh` with K=r3b, the default LOGDIR, `+caps_expect=fab1ca07`, the
tokens record from `evidence/qwen9b/s4/S4_REPLAY.md`, and cycles-today set to that seed's r2 count (the run
fails unless r3 is faster). The binary's sha is re-printed at line 7 of every log.

| seed | TB_SEQ_CHIP | cycles / 6 tok (**E**) | below r2 by (**E**) | tokens (**E**) | broadcast X_END exits (**E**) | vs the predicted whole run (**D**) |
|---|---|---|---|---|---|---|
| s1 | PASS `evidence/qwen9b/sr/n3160_r3_9b_chip_s1_r3.log:30` | **144,762,463** (line 35) | −12,248,445 (line 36) | IDENTICAL (line 39) | 774, landed == sent, min margin 3 (line 34) | 144,745,948: +0.011 % |
| s2 | PASS `evidence/qwen9b/sr/n3161_r3_9b_chip_s2_r3.log:30` | **144,761,998** (line 35) | −12,249,558 (line 36) | IDENTICAL (line 39) | 774 (line 34) | 144,746,596: +0.011 % |
| s3 | PASS `evidence/qwen9b/sr/n3162_r3_9b_chip_s3_r3.log:30` | **144,761,998** (line 35) | −12,249,492 (line 36) | IDENTICAL (line 39) | 774 (line 34) | 144,746,530: +0.011 % |
| s4 | PASS `evidence/qwen9b/sr/n3163_r3_9b_chip_s4_r3.log:30` | **144,762,607** (line 35) | −12,248,379 (line 36) | IDENTICAL (line 39) | 774 (line 34) | 144,746,026: +0.011 % |
| s1 timeline | PASS `evidence/qwen9b/sr/n3164_r3_9b_chip_s1_r3_timeline.log:32` | 144,762,463 = the control (line 37) | — | IDENTICAL (line 41) | 774 (line 36) | — |

The predicted column is R3-7's (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:14`, read from n2900); the
percentages are `evidence/qwen9b/sr/n3170_r3_9b_derive.log:18`, `evidence/qwen9b/sr/n3170_r3_9b_derive.log:20`,
`evidence/qwen9b/sr/n3170_r3_9b_derive.log:22`, `evidence/qwen9b/sr/n3170_r3_9b_derive.log:24`. The r2 base is SR13a's
measured whole runs, the same counts R3-9a's rung 1 re-measured on this binary (**T**,
`evidence/qwen9b/sr/R3_9a_CHIP.md:82-85`). 774 = 6 tokens × 129 broadcasts. The timeline CSV is gitignored;
its sha256 98db8056… is committed in `evidence/qwen9b/sr/r3_9b_timeline_model_9b_s1_reordB_r3.csv.sha256`
(`evidence/qwen9b/sr/n3165_r3_9b_timeline_csv_sha.log:6`) and checked before any row is read.

## 3. The band verdict, every stream

| quantity | measured | prediction | Δ | band | cite (**D**) |
|---|---|---|---|---|---|
| **s1 token-4 body window** | **24,129,766** (96.519 ms) | **P-A 24,127,093** | **+2,673 = +0.011 %** | **HELD** (±120,635.5) | `evidence/qwen9b/sr/n3170_r3_9b_derive.log:36` |
| beside it: P-C (the pass's corrected r3) | 24,129,766 | 24,139,430 (band 24,122,218 … 24,139,430) | −9,664 = −0.040 %; inside the band | — | `evidence/qwen9b/sr/n3170_r3_9b_derive.log:37` |
| beside it: P-B (census) | 24,129,766 | 24,127,093 | +2,673 | — | same line |
| the saving r2 → r3 (token 4) | 2,041,487 = 8.1659 ms | 2,044,160 = 8.1766 ms | −2,673 (99.87 %) | — | `evidence/qwen9b/sr/n3170_r3_9b_derive.log:38` |
| s2 r3/r2 vs s1's | 0.921983 | 0.921990 (s1) | −0.0007 % | HELD | `evidence/qwen9b/sr/n3170_r3_9b_derive.log:42` |
| s3 r3/r2 vs s1's | 0.921983 | 0.921990 | −0.0007 % | HELD | `evidence/qwen9b/sr/n3170_r3_9b_derive.log:43` |
| s4 r3/r2 vs s1's | 0.921990 | 0.921990 | +0.0000 % | HELD | `evidence/qwen9b/sr/n3170_r3_9b_derive.log:44` |

The bands are SR5b's on P-A, read from the committed prediction log, not re-typed
(`evidence/qwen9b/sr/n3170_r3_9b_derive.log:11-12`). Every stream is HELD and 4/4 runs are tokens IDENTICAL with
runner PASS (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:46-51`).

**Per token** (shipped / r2 / r3): every body token is ×1.0846 vs r2 and ×1.3587–1.3596 vs shipped, and saves
2,041,120–2,041,578 cyc against r2. Token 0 is unchanged at 17,197 (**D**,
`evidence/qwen9b/sr/n3170_r3_9b_derive.log:28-35`).

**Speed (MODEL on the TB, OV1's uniform factor, as SR13a):** 96.508 ms/token on the whole run = **9.910 tok/s**,
against shipped 7.293 and r2 9.137 (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:19`); token 4 9.909 against
P-A's 9.910 (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:39`). **×r2 1.0846, ×shipped 1.3588, ×R1 1.1258** on
the whole run (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:18`); the body window gives the same ×r2 1.0846 and
×shipped 1.3588 (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:39`).

## 4. Attribution by class, token 4, s1

The band held, so attribution was not required; it was done anyway, for the record and because the brief
asks for the one-window measurement. `evidence/qwen9b/sr/sr13a_derive.py` with the r3 flag rebuilds the pass's own
schedule at r2 and at r3. Each rebuild reproduces its committed replay_mk and pred_mk (r3: 24,102,767 /
24,139,430 = R3-5's n2720), each emitted body equals the stream on disk record by record (r2 40,171 / 40,171,
r3 39,784 / 39,784), and both CSVs match their committed sha256 (**D**,
`evidence/qwen9b/sr/n3170_r3_9b_derive.log:66-67`). R3-7's EXPECTED per class is r2 measured plus the model's
r2→r3 delta, and it sums to P-A (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:83`):

| class | n r2→r3 | r2 measured | r3 EXPECTED (R3-7) | **r3 measured** | measured − expected | cite (**D**) |
|---|---|---|---|---|---|---|
| MOVX | 516 → 129 | 3,237,088 | 809,272 | **811,723** | **+2,451** (91.7 % of the gap) | `evidence/qwen9b/sr/n3170_r3_9b_derive.log:70` |
| LDC | 161 | 320,125 | 320,125 | 320,581 | +456 | `evidence/qwen9b/sr/n3170_r3_9b_derive.log:71` |
| FENCE | 1,370 | 8,987,848 | 9,371,504 | 9,371,270 | −234 | `evidence/qwen9b/sr/n3170_r3_9b_derive.log:72` |
| CMD + ARG | 35,284 | 10,730,078 | 10,730,078 | 10,730,078 | 0 | `evidence/qwen9b/sr/n3170_r3_9b_derive.log:73` |
| MOVY / MVGO / EMB / CSRWR / XOP / JMP / AMAXL | unchanged | — | — | — | 0 each | the same block |
| **sum** | | **26,171,253** | **24,127,093 = P-A** | **24,129,766** | **+2,673** | `evidence/qwen9b/sr/n3170_r3_9b_derive.log:36` |

* **MOVX: the one-window price plus R3-9a's fixed +19, exactly.** All 129 body MOVX are broadcasts (channel
  field 0xF). At 4,096 bytes 97 broadcasts average 4,235.99 cyc (4,235 … 4,238) against r2's 388 unicasts at
  4,216.99. At 12,288 bytes 32 broadcasts take 12,526 each against r2's 12,507. **Broadcast − unicast =
  +19.00 at both lengths, +0.00 beyond R3-9a's synthetic +19** (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:122-123`).
  So the class is 809,272 + 129 × 19 = 811,723, a residual of +0
  (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:124`). The lockstep push costs nothing beyond the three closing
  STATUS reads on the real stream either: no back-pressure stall and no rate loss.
* **FENCE: the lane-idle rise landed as modelled.** FENCE lane work rose 8,987,848 → 9,371,270 (+383,422
  against the census's +383,656, `evidence/qwen9b/sr/n3170_r3_9b_derive.log:108`). The rise sits where the
  removed siblings' overlap was: DN mlp_up +131,495, GQA q_proj +101,192, DN mlp_gate +70,993, GQA mlp_up
  +41,496, GQA mlp_gate +26,000, HEAD lm_head +12,649. Each is within ±222 of the r3 model
  (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:86-101`).
* **dn_out apart:** r2 186,095, r3 186,108 (+13). The r3 model's 197,381 is −11,273 off, the same SLD DMA stall
  absorbed by dn_out waits that SR13a found at r2 (−11,286). The stall did not move
  (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:102`).
* **No new DMA stall.** L_DMA-busy cycles in token 4 are 1,289,504 at both r2 and r3; they moved between
  classes only, from MOVX windows into FENCE windows (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:116`).
  Fetch-empty stall cycles are 36 → 36. The named risk (new DMA-queue stalls, ≈137,696 cyc for eight) did not
  materialise.
* **LDC +456** is the only other non-zero class (0.0019 % of P-A). CMD lane work is 10,650,689, r2's to the
  cycle (`evidence/qwen9b/sr/n3170_r3_9b_derive.log:104-114`).

## 5. The r3 chat images on the chip TB

**The recipe is SR5b's** (S1T's generator), run with the r3 level flag. Four scenarios, each run as two
multi-launch runs (shipped order and r3) on the srr3b binary with K=r3b and `+caps_expect=fab1ca07`.

**Vectors (model level, before any chip run): 4/4 PASS** (**E**,
`evidence/qwen9b/sr/n3171_r3_9b_chat_vectors_c1.log:42` and the same line of `n3172–n3174`):
* The r3 images are R3-6's pins: lite 8a226ca1… with 38,930 records, 1,248 masked FENCEs and **128 broadcast
  MOVX**; full fdfc6d0c… with 39,786 records, 1,370 masked FENCEs and **129 broadcast MOVX**
  (`evidence/qwen9b/sr/n3171_r3_9b_chat_vectors_c1.log:24-25`).
* The shipped side is byte-identical to S1T's vectors (`evidence/qwen9b/sr/n3171_r3_9b_chat_vectors_c1.log:34`).
* The golden lines are identical launch by launch.

**Why 128 and 129.** The lite image stops before the LM head. The full image's 129th broadcast is the LM
head's four MOVX from one source, full-image records 38857–38860, merged into one. In the static model that
129th broadcast saves 0 cycles, so the r2→r3 static image saving is 2,043,872 cyc for both kinds
(`evidence/qwen9b/sr/n3157_r3_9b_chat_prediction.log:102-103`).

**The prediction (committed at 5f1d4e2, before the first chat run).** No r2 image has ever run on the chip TB,
so the measured base is SR5b's r1. Per launch, the prediction is r1 measured (same scenario and launch) minus
the r1→r3 static replay saving: 2,897,288 for lite and 3,048,208 for full. That gives lite 22,324,040 …
22,330,982 and full 24,125,316 … 24,130,530. The bands are SR15's, on the absolute form (**D**,
`evidence/qwen9b/sr/n3157_r3_9b_chat_prediction.log:102-103`).

**On the r3 binary: 8 of 8 PASS, tokens IDENTICAL launch by launch on all 4 scenarios.** Every r3 run checked
514 broadcast X_END exits (128 + 128 + 129 + 129), landed == sent on each
(`evidence/qwen9b/sr/n3176_r3_9b_chat_chip_c1_r3.log:40` and the same line in n3178, n3180, n3182).

| launch kind | shipped cycles (8 launches) | **r3 cycles** | ×shipped | vs the prediction | vs the r3 static model | cite (**D**) |
|---|---|---|---|---|---|---|
| lite | 30,210,226–30,215,128 | **22,323,388–22,330,252** | 1.3531–1.3533 | **−0.003 %** on all 8 (−652 … −730 cyc) → HELD | +0.115 … +0.145 % (vs 22,297,831) | `evidence/qwen9b/sr/n3183_r3_9b_chat_compare.log:46`, `evidence/qwen9b/sr/n3183_r3_9b_chat_compare.log:51` |
| full | 32,781,847–32,786,773 | **24,124,648–24,129,847** | 1.3588–1.3589 | **−0.003 %** on all 8 (−629 … −695 cyc) → HELD | +0.156 … +0.177 % (vs 24,087,146) | `evidence/qwen9b/sr/n3183_r3_9b_chat_compare.log:48`, `evidence/qwen9b/sr/n3183_r3_9b_chat_compare.log:52` |

* **CHAT PREDICTION VERDICT (16 launches): HELD (worst −0.003 %)**
  (`evidence/qwen9b/sr/n3183_r3_9b_chat_compare.log:53`). On the TB, the r1→r3 image saving is 629–730 cyc
  larger than the static model's; the per-launch lines show it (`evidence/qwen9b/sr/n3183_r3_9b_chat_compare.log:11-14`).
* **Totals per scenario:** 125,994,152–125,994,254 → 92,908,310–92,908,361, ×1.3561 on every scenario
  (`evidence/qwen9b/sr/n3183_r3_9b_chat_compare.log:15`, :24, :33, :42).
* **The shipped side on the r3 binary equals S1T's shipped-RTL runs** to the cycle and token on all 20
  launches, and the r3 tokens equal SR5b's r1 tokens on all 20
  (`evidence/qwen9b/sr/n3183_r3_9b_chat_compare.log:54`).
* **The chat and stream ladders stay separate.** The image numbers are lite and full launch windows, not a
  stream's ms/token.

## 6. Judgment calls

1. **The Step 0 lines, read from the RTL.** A SEQ stream cannot collide with the AXI-Lite XWIN register during
   a push. The mover owns the sequencer's AXI-Lite master for its whole job, and it never writes 0x24. Reading
   the RTL also showed that a CSRWR record to csr_id 0x1c24 *can* reach that register (`rtl/seq_unit.sv:928-934`;
   the model treats MV-space CSRWRs as no-ops, `ref/seq_model.py:774-775`), but only between mover jobs. The
   wording in `evidence/qwen9b/sr/R3_9a_CHIP.md` §7 is "cannot collide", not "cannot reach". Commit 5caa4f2;
   spec_cites `evidence/qwen9b/sr/n3156_r3_9b_spec_cites_r3_9a_s7.log` FAIL 0.
2. **Flags, not copies.**
   * `evidence/qwen9b/sr/sr13a_derive.py` got the r3 flag. Its inputs are arguments (prediction log, base window
     log, base whole-run logs, chip logs, timeline log), and every r3 number is READ from a committed line.
   * The r2 path is untouched. With default flags it reproduces n1349g line for line, except for the order of
     zero-delta tie rows: those follow Python's per-process string hash (n3158, rc 1 on order only). n3166
     shows the two outputs identical as sorted lines (109 lines,
     `evidence/qwen9b/sr/n3166_r3_9b_derive_default_repro_sorted.log:7`).
   * `evidence/qwen9b/sr/sr5b_chat_compare.py` also got flags: the level, K and the prediction log. The plan names
     only the vector generator, but the compare tool hard-coded r1, K=5 and r1's static model. A copy would
     have broken I-5.
3. **Chat vector file names.** Above r1 the generator writes sr5b<level>_<tag>_*, so SR5b's own sr5b_<tag>_*
   vectors (which its logs cite by sha) were never rewritten.
4. **The chat images ran in parallel with the streams** (13 simulations at once on snoke, 233 GiB available).
   SR5b did the same, and the whole task fit well under the brief's 3-hour chat allowance.
5. **NEXT_SESSION.md was not touched.** The plan's Step 5 names a §8 line, but the controller addendum gives
   the §8 entry and the "Open now … R3 decision" sentence to R3-12, and this dispatch's ownership list does not
   include NEXT_SESSION.md.
6. **FABLE5_MODEL=unset in the chip-run headers.** Those runs replay committed, re-hashed streams and run no
   reference, emitter or pass (R3-9a §6 item 6). The runs that do (the goldens through sr_chipvec.sh, the chat
   vectors, the derive and the prediction) set FABLE5_MODEL=9b FABLE5_RS_F=7 on their command line.
7. **Log numbering.** n3150–n3159 cover preconditions, goldens and the prediction; n3160–n3166 the stream runs,
   the CSV sha and the reproduction checks; n3170 the derive; n3171–n3183 the chat images; n3190 a spec_cites precheck on the uncommitted
   document; n3199 spec_cites LAST. n3167–n3169, n3184–n3189 and n3191–n3198 are unused.

## 7. What is NOT established here

* **No board number.** Every tok/s here is MODEL (the TB scaled by OV1's uniform factor). The R3 bitstream does
  not exist yet (R3-10), and nothing ran on the board.
* **No timing.** R3's netlist has not been through a full build, and the R2 margin it must fit into is one
  placement's (`evidence/qwen9b/sr/SR14_R2_BUILD.md` §2.2).
* **The r2 chat image on the chip TB** is still unmeasured. The chat prediction is anchored on r1, so the
  r2→r3 image saving (2,043,872 static) cannot be measured on its own here.
* The chip TB's DDR and XDMA models are the round's own. The board's DMA-queue behaviour under the r3 order
  is R3-11's to observe.

## 8. Logs and commits

| log / commit | what |
|---|---|
| 5caa4f2 | `evidence/qwen9b/sr/R3_9a_CHIP.md` §7, the two granted lines |
| `evidence/qwen9b/sr/n3156_r3_9b_spec_cites_r3_9a_s7.log` | spec_cites over R3_9a_CHIP.md after the edit: FAIL 0 |
| 2a18ef5 | the tools: sr13a_derive.py r3 flag; sr5b_chat_vectors.py and sr5b_chat_compare.py level flags |
| `evidence/qwen9b/sr/n3150_r3_9b_precondition.log`, `evidence/qwen9b/sr/n3151_r3_9b_identity.log` | the order and identity checks |
| `evidence/qwen9b/sr/n3152_r3_9b_chipvec_s1_r3.log` … `evidence/qwen9b/sr/n3155_r3_9b_chipvec_s4_r3.log` | the r3 goldens |
| `evidence/qwen9b/sr/n3157_r3_9b_chat_prediction.log` (5f1d4e2) | the chat-image prediction, before any chat run |
| `evidence/qwen9b/sr/n3158_r3_9b_derive_default_repro.log`, `evidence/qwen9b/sr/n3166_r3_9b_derive_default_repro_sorted.log` | the default path reproduces n1349g |
| `evidence/qwen9b/sr/n3159_r3_9b_pgrep_prerun.log` | pgrep on the three hosts |
| `evidence/qwen9b/sr/n3160_r3_9b_chip_s1_r3.log` … `evidence/qwen9b/sr/n3164_r3_9b_chip_s1_r3_timeline.log`, `evidence/qwen9b/sr/n3165_r3_9b_timeline_csv_sha.log` | the r3 stream runs and the CSV sha |
| `evidence/qwen9b/sr/n3170_r3_9b_derive.log` | the derivation and the verdict |
| `evidence/qwen9b/sr/n3171_r3_9b_chat_vectors_c1.log` … `evidence/qwen9b/sr/n3174_r3_9b_chat_vectors_c4.log` | the chat vectors |
| `evidence/qwen9b/sr/n3175_r3_9b_chat_chip_c1_ship.log` … `evidence/qwen9b/sr/n3182_r3_9b_chat_chip_c4_r3.log`, `evidence/qwen9b/sr/n3183_r3_9b_chat_compare.log` | the chat runs and the comparison |
| n3199 | spec_cites LAST, alone, on the committed tree, over this document |
