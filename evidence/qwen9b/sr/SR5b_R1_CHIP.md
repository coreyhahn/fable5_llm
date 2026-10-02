# SR5b — R1 on the chip TB, part 2: the r1 streams token-identical, the round's first TB number

Task SR5b of `docs/superpowers/plans/2026-09-27-seq-rtl-round.md`. The four r1
streams SR4 produced (one masked FENCE per MVGO, SEQ_ISA v2.3 B17.1) ran on
SR5a's chip-TB binary, unchanged. Their measured cycles were judged against
the model's prediction, under bands committed before any run landed. A second
rung, added by the controller, ran chat_seq's own r1 step images (the images
SR6 pinned) against the shipped order, launch by launch. No RTL changed, no
Vivado ran and the board was not touched. Every run was on snoke through
`evidence/qwen9b/sr/sr_run.sh`, and every log is in this task's block
`n550–n599`.

**Labels.** **E** = printed by a run of this task, cited to its log line.
**D** = derived by `evidence/qwen9b/sr/sr_derive.py` or
`evidence/qwen9b/sr/sr5b_chat_compare.py` on snoke, cited to the log line that
printed it. **T** = transcribed from an earlier gate, cited there. **MODEL** =
a tok/s scaled from TB cycles by OV1's uniform board factor; it is not a board
measurement.

## Verdict

**GREEN. The model held. There is nothing to STOP on.**

* **Tokens IDENTICAL, 4 of 4.** All four r1 streams print `TB_SEQ_CHIP PASS`,
  and their six tokens equal the shipped record (§2).
* **s1: the model held, +0.101 %.** The token-4 body window measured
  **27,163,998 cyc** against the prediction of 27,136,513. That is +27,485 cyc,
  inside the ±0.5 % band (**D**,
  `evidence/qwen9b/sr/n570_sr5_derive.log:39`).
* **s2–s4: held.** Each seed's whole-run R1 / S1-B is < 1 and within 0.0011 %
  of s1's, and its R1 / shipped within 0.0013 % (**D**,
  `evidence/qwen9b/sr/n570_sr5_derive.log:43-45`). The band verdict is HELD for
  every stream (**D**, `evidence/qwen9b/sr/n570_sr5_derive.log:47-51`).
* **The whole run is ×1.2070 against shipped and ×1.0538 against S1-B**, at
  108.645 ms/token on the TB. Board-scaled (MODEL) that is 8.803 tok/s, against
  the model's 8.811 (**D**, `evidence/qwen9b/sr/n570_sr5_derive.log:21-22`).
* **The residual is mostly the CMD class, not the mask semantics NET.** 70 %
  of the +27,485 cyc is layer-command windows running longer than BN1 measured
  them in program order; this is the SV1 residual class. 32 % is the FENCE
  class. Gross, the mask's per-record cost (+22,563 cyc, 23 per FENCE record,
  which the model prices at zero) is the largest single term, mostly offset by
  its cheaper tails: the model over-prices the single-channel poll tails (§4).
* **The r1 chat images: tokens IDENTICAL, 4 scenarios × 5 launches.** Both
  orders ran on the R1 binary, all 8 runs PASS. The r1 images run ×1.1977 (lite)
  and ×1.2063 (full) against shipped, and 0.10–0.16 % over their own static
  model makespans (§5). The shipped side ran cycle-identical to S1T's
  shipped-RTL runs, launch by launch. **This is the per-image proof SR8's
  board session needs.**

## 1. What ran

| item | value | cite |
|---|---|---|
| binary | `tb/obj_dir_seq_chip_sr5/tb_seq_chip_9b_sr5`, SR5a's, **unchanged**, sha256 f7b64e5a1c39503371db0cee64ceedb363b56a4cc7e8d2fadb9b31c7acc0353e | **E**, `evidence/qwen9b/sr/n560_sr5b_chip_s1_r1_control.log:7`; **T**, `evidence/qwen9b/sr/n500_build_sr5.log:71` |
| runner | `evidence/qwen9b/sr/run_sr_chip.sh`, SR5a's, control mode with the shipped cycles as its cycles-today check (SV1's use) and the token record read from `evidence/qwen9b/s4/S4_REPLAY.md` under the shipped stem | **E**, `evidence/qwen9b/sr/n560_sr5b_chip_s1_r1_control.log:3` |
| the obj_dir | before the launch, `pgrep` on snoke, kyloren and darthplagueis found no other user of any `obj_dir_seq_chip` binary | — |
| parallelism | 13 simulations at once (4 controls, the timeline, 8 chat runs). Peak 13 processes, **0.851 GiB** total RSS, 226 GiB available at launch | **E**, `evidence/qwen9b/sr/n565_sr5b_memwatch.log:11`, `evidence/qwen9b/sr/n565_sr5b_memwatch.log:43` |
| wall | 7,687–7,812 s per stream control, 7,801 s for the timeline, 4,858–5,753 s per chat run | **E**, line 14 of n560–n563, `evidence/qwen9b/sr/n564_sr5b_chip_s1_r1_timeline.log:15`, line 12 of n580–n587 |

**New scripts, each committed before its first use (a4f9841).**
* `evidence/qwen9b/sr/sr_chipvec.sh` is a copy of
  `evidence/qwen9b/ov/sv1_chipvec.sh` with a third argument: the capability
  set the stream is validated and executed at.
* `tb/scripts/gen_seq_chip_vectors.py` gained `--caps` to carry it. The
  default is the empty set, so every earlier invocation is unchanged.
* `evidence/qwen9b/sr/sr_derive.py` is a copy of
  `evidence/qwen9b/ov/sv1_derive.py`, retargeted (§4).
* `evidence/qwen9b/sr/sr5b_streams.sh` checks stream identity.
* `evidence/qwen9b/sr/sr5b_chat_vectors.py` and
  `evidence/qwen9b/sr/sr5b_chat_compare.py` are copies of S1T's
  `evidence/qwen9b/ov/s1t_chat_vectors.py` and
  `evidence/qwen9b/ov/s1t_compare.py`, at r1 (§5).

## 2. The four r1 streams — identity, goldens, runs

**Step 1, the prediction and the bands, committed before any run landed**
(59b5538; **D**, `evidence/qwen9b/sr/n550_sr5_predictions.log:7-11`):
* s1's token-4 body window against **27,136,513** cyc. HELD is
  27,000,830–27,272,196; LOOSE (attribute by class) is 26,593,783–27,679,243;
  outside that is a STOP.
* s2–s4's whole-run ratios against s1's, at the same ±0.5 % / ±2 %.

**Step 2, stream identity.** All four r1 `.seq` files match three ways: the
sha256 SR4 logged, the file on disk, and a fresh regeneration by n410's own
recipe (the CSV cost path) into a new prefix. The `.seqdata.bin` copies are
identical too (**E**, `evidence/qwen9b/sr/n551_sr5b_stream_identity.log:17`,
`evidence/qwen9b/sr/n551_sr5b_stream_identity.log:29`,
`evidence/qwen9b/sr/n551_sr5b_stream_identity.log:41`,
`evidence/qwen9b/sr/n551_sr5b_stream_identity.log:53-54`).

**Step 3, the goldens.** Each r1 golden, generated at caps {R1}, is identical
to the shipped golden except NREC and PC: 0 other lines differ (**E**, line 22
and line 24 of n552–n555, for example
`evidence/qwen9b/sr/n552_sr5b_chipvec_s1_r1.log:22`).

**Step 4, the runs.**

| seed | .seq / .chip | TB_SEQ_CHIP | cycles / 6 tok | ms/token (D) | ×shipped (D) | ×S1-B (D) | tokens | verdict |
|---|---|---|---|---|---|---|---|---|
| s1 | 4e11a2ae… / fa6a57cc… (`evidence/qwen9b/sr/n560_sr5b_chip_s1_r1_control.log:8`) | PASS (`evidence/qwen9b/sr/n560_sr5b_chip_s1_r1_control.log:37`) | **162,967,117** (`evidence/qwen9b/sr/n560_sr5b_chip_s1_r1_control.log:30`) | 108.645 | 1.2070 | 1.0538 | IDENTICAL (`evidence/qwen9b/sr/n560_sr5b_chip_s1_r1_control.log:34`) | HELD |
| s2 | cc982e4f… / af973f81… (`evidence/qwen9b/sr/n561_sr5b_chip_s2_r1_control.log:8`) | PASS (`evidence/qwen9b/sr/n561_sr5b_chip_s2_r1_control.log:37`) | **162,965,710** (`evidence/qwen9b/sr/n561_sr5b_chip_s2_r1_control.log:30`) | 108.644 | 1.2070 | 1.0538 | IDENTICAL (`evidence/qwen9b/sr/n561_sr5b_chip_s2_r1_control.log:34`) | HELD |
| s3 | 0f85a974… / 19bea94a… (`evidence/qwen9b/sr/n562_sr5b_chip_s3_r1_control.log:8`) | PASS (`evidence/qwen9b/sr/n562_sr5b_chip_s3_r1_control.log:37`) | **162,965,710** (`evidence/qwen9b/sr/n562_sr5b_chip_s3_r1_control.log:30`) | 108.644 | 1.2070 | 1.0538 | IDENTICAL (`evidence/qwen9b/sr/n562_sr5b_chip_s3_r1_control.log:34`) | HELD |
| s4 | 492e0def… / 6cff0d04… (`evidence/qwen9b/sr/n563_sr5b_chip_s4_r1_control.log:8`) | PASS (`evidence/qwen9b/sr/n563_sr5b_chip_s4_r1_control.log:37`) | **162,967,195** (`evidence/qwen9b/sr/n563_sr5b_chip_s4_r1_control.log:30`) | 108.645 | 1.2070 | 1.0538 | IDENTICAL (`evidence/qwen9b/sr/n563_sr5b_chip_s4_r1_control.log:34`) | HELD |
| s1 | timeline | PASS (`evidence/qwen9b/sr/n564_sr5b_chip_s1_r1_timeline.log:69`) | 162,967,117, = the control (`evidence/qwen9b/sr/n564_sr5b_chip_s1_r1_timeline.log:32`) | — | — | — | IDENTICAL (`evidence/qwen9b/sr/n564_sr5b_chip_s1_r1_timeline.log:36`) | — |

* The derived columns are `evidence/qwen9b/sr/n570_sr5_derive.log:21-28`.
* The references are T: shipped 196,706,821 / 196,707,670 / 196,707,670 /
  196,706,833 (`evidence/qwen9b/s4/S4_REPLAY.md:398-401`) and S1-B 171,731,320 /
  171,731,695 / 171,731,695 / 171,731,425 (`evidence/qwen9b/ov/SV1_S1_VERIFY.md` §3).
* `TB_SEQ_CHIP PASS` compares the full architectural end state against the r1
  golden: every scratch word, the XRF, TCNT and the 112 state blocks. That
  golden is identical to the shipped one apart from NREC and PC (step 3).
* **The timeline is inert.** It reproduces the control's cycle count exactly.
  Its CSV is gitignored; the sha256 is committed at
  `evidence/qwen9b/sr/sr5b_timeline_model_9b_s1_reordB_r1.csv.sha256`
  (**E**, `evidence/qwen9b/sr/n564_sr5b_chip_s1_r1_timeline.log:37`), and
  sr_derive checks it before it reads a row
  (`evidence/qwen9b/sr/n570_sr5_derive.log:54`).
* **Beside SV1's informational whole-run model** (the replayed segments plus
  the launch cycles no window holds; no band), every seed is +0.100 %
  (`evidence/qwen9b/sr/n570_sr5_derive.log:21`,
  `evidence/qwen9b/sr/n570_sr5_derive.log:27`).

## 3. The band verdict, every stream

| stream | quantity | measured | against | Δ | band | cite |
|---|---|---|---|---|---|---|
| s1 | token-4 body window | 27,163,998 cyc | 27,136,513 (n120:17 = SR4's replay) | +27,485 cyc = **+0.101 %** | **HELD** (±0.5 %) | **D**, `evidence/qwen9b/sr/n570_sr5_derive.log:39` |
| s2 | R1/S1-B; R1/shipped, vs s1's 0.948966; 0.828477 | 0.948955; 0.828466 | s1's | −0.0011 %; −0.0013 % | **HELD** | **D**, `evidence/qwen9b/sr/n570_sr5_derive.log:43` |
| s3 | the same | 0.948955; 0.828466 | s1's | −0.0011 %; −0.0013 % | **HELD** | **D**, `evidence/qwen9b/sr/n570_sr5_derive.log:44` |
| s4 | the same | 0.948965; 0.828478 | s1's | −0.0000 %; +0.0000 % | **HELD** | **D**, `evidence/qwen9b/sr/n570_sr5_derive.log:45` |

Every R1/S1-B is < 1, as the band requires. Per token, R1 runs ×1.2070–1.2077
against shipped and ×1.0537–1.0544 against S1-B, on tokens 1–6 of the s1
timeline (**D**, `evidence/qwen9b/sr/n570_sr5_derive.log:33-38`).
Board-scaled, token 4 is 8.802 tok/s (MODEL) against the model's 8.811 (**D**,
`evidence/qwen9b/sr/n570_sr5_derive.log:40`).

**Token 0 is 17,197 cyc, against 211 for shipped and for S1-B.** This is an
accounting effect, not a cost. The timeline splits tokens at the EMB record.
The r1 pass scheduled five records of segment 0 above that segment's EMB, so
they fall in token 0:
* an LDC of 4,662 cyc (**E**, `evidence/qwen9b/sr/n571_sr5b_token0_rows.log:10`);
* a CMD of 12,315 cyc (**E**, `evidence/qwen9b/sr/n571_sr5b_token0_rows.log:14`);
* and CSRWRs.

The EMB lands at pc 44 (**E**,
`evidence/qwen9b/sr/n571_sr5b_token0_rows.log:15`). The body (token 4) has no
such shift. Its rows cover exactly the body's pcs, and they sum to the
timeline's own token-4 count (**D**,
`evidence/qwen9b/sr/n570_sr5_derive.log:64`).

## 4. Attribution by class — token 4, s1 (the SR4 review's reading guide)

The band was held, so attribution was not required. It was done anyway, for
the record, with the addendum's split: the FENCE class apart from the CMD
class.

**Method.** sr_derive rebuilds the model with the pass's own functions:
* the body schedule at r1 with BN1's CSV windows;
* the emitted order, and its replay.

It then:
* **reproduces 27,136,513 exactly**, with a zero tail (**D**,
  `evidence/qwen9b/sr/n570_sr5_derive.log:61-62`);
* **checks the emitted body against the r1 stream on disk, record by record:
  40,171 of 40,171 identical** (**D**,
  `evidence/qwen9b/sr/n570_sr5_derive.log:63`).

Every body record therefore has two windows: the model's and the TB's.

| class | records | model (cyc) | measured (cyc) | measured − model | share of +27,485 |
|---|---|---|---|---|---|
| CMD (with its ARG CSRWRs) | 35,284 | 10,710,770 | 10,730,078 | **+19,308** (+0.071 % of the prediction) | +70.2 % |
| FENCE | 1,370 | 9,971,687 | 9,980,593 | **+8,906** (+0.033 %) | +32.4 % |
| LDC / MVGO / EMB | 161 / 1,370 / 1 | — | — | −593 / −88 / −48 | −2.2 % / −0.3 % / −0.2 % |
| MOVX / MOVY / CSRWR / XOP / JMP / AMAXL | — | — | — | 0 each | 0 |

(**D**, `evidence/qwen9b/sr/n570_sr5_derive.log:65-78`.)

**The FENCE class, split** (**D**, `evidence/qwen9b/sr/n570_sr5_derive.log:79-81`):
* **1,370 FENCEs per body, all single-channel.** Four segments of 1,370 make
  the stream's 5,480 (T, `evidence/qwen9b/sr/n410_reorder_s1_B_r1.log:45`).
  The addendum's check of the count holds. The printed line 79 garbles this
  as "x 4 tokens = 5480 + the unrolled segments"; the right reading is 4
  segments × 1,370 = 5,480.
* **The per-record cost the model does not charge.** 981 FENCEs have nothing
  to wait on in the model. On the TB each costs **exactly 23 cycles** (min =
  max = 23), 22,563 cyc in all.
  * That is decode, the F_SCAN walk and S_DONE, which the model prices at
    zero.
  * The SR4 reviewer estimated about 10 cyc per record. It is 23.
* **The poll tails.** 389 FENCEs wait in the model. There the TB is **13,657
  cyc under** the model, −35.11 cyc per FENCE, including each FENCE's own
  record cost.
  * **Net of the 23-cycle record cost** (389 × 23 = 8,947), the tails are
    over-priced by **22,604 cyc per body, −58.11 per waiting FENCE** (**D**,
    `evidence/qwen9b/sr/n591_sr5b_fix1_tail_net.log:16-17`).
  * The model's convention prices each single-channel tail at its MVGO's
    original 4-group tau. It over-prices them.
  * The largest single class is DN dn_out, −0.038 ms ≈ −9,525 cyc over 96
    FENCEs (`evidence/qwen9b/sr/n570_sr5_derive.log:83`;
    `evidence/qwen9b/sr/n591_sr5b_fix1_tail_net.log:19`).
  * Every other drained class is +0.0007 to +0.0121 ms
    (`evidence/qwen9b/sr/n570_sr5_derive.log:84-98`).
* **Net FENCE: +8,906 cyc.** The two conventions the addendum named (a tail
  priced at the 4-group tau, nothing charged per record) err in opposite
  directions. At this operating point they largely cancel.

**The CMD class is the SV1 residual, barely grown.**
* Against BN1's program-order windows, R1's layer commands take +0.0772 ms
  per token.
* Against S1-B's measured CMD lane work, the growth is only **+0.0084 ms**
  (**D**, `evidence/qwen9b/sr/n570_sr5_derive.log:101`).
* SV1 measured this class at +0.069 ms/token at S1 (**T**,
  `evidence/qwen9b/ov/SV1_S1_VERIFY.md` §4.2).

So most of R1's CMD residual was already present at S1; R1's extra overlap adds
a little. **In the addendum's terms, the gap is in the CMD class (contention,
or the form-B resource list), not in the mask semantics NET: gross, the mask's
per-record cost (+22,563) is the largest single term, mostly offset by its
cheaper tails.**

**Where R1's gain over S1-B sits.** The FENCE lane work drops from 45.770 to
39.922 ms per token. Every other opcode moves by at most 0.009 ms (**D**,
`evidence/qwen9b/sr/n570_sr5_derive.log:100-110`).

## 5. The r1 CHAT images — the per-image proof for SR8

**The recipe is S1T's** (`evidence/qwen9b/ov/S1T_FORMB_IMAGE_TB.md` §1), with
the second side at `--seq-rtl r1 --reorder B`:
* ChatSession builds the r1 lite and full images and refuses unless they equal
  the pins in sw/chat_seq.py.
* The golden executor runs at the side's capability set: {R1} on the r1 side,
  empty on the shipped side.
* The generator asserts **golden lines identical launch by launch** (XRF, TOK,
  TCNT, EOUT/AMAX, SMEM, every checked scratch word). It also checks that the
  image is reordered, the head records are unmoved and the const blob is
  identical.

The scenarios are S1T's four: 3-token prompts with last positions 3 / 86 / 300
/ 510.

**Model level, before any chip run** (n556–n559, all `SR5B_CHAT_VECTORS PASS`,
for example `evidence/qwen9b/sr/n556_sr5b_chat_vectors_c1.log:42`):
* **The r1 images are the pins.** lite 99991122…0723 (39,314 records, 1,248
  masked FENCEs) and full bf115a04…7281 (40,173 records, 1,370 masked FENCEs)
  (**E**, `evidence/qwen9b/sr/n556_sr5b_chat_vectors_c1.log:24-25`, the same
  lines in n557–n559). They are SR6's (**T**,
  `evidence/qwen9b/sr/n601_r1_pins.log:22-23`).
* **The shipped side's vectors are byte-identical to S1T's.** The .seq,
  .seqdata.bin and .chip match on every scenario (**E**,
  `evidence/qwen9b/sr/n556_sr5b_chat_vectors_c1.log:32-34` and the same lines
  in n557–n559).

**On the R1 binary: 8 of 8 PASS, tokens IDENTICAL launch by launch, all 4
scenarios** (**D**, `evidence/qwen9b/sr/n588_sr5b_chat_compare.log:46`).

| launch kind | shipped cycles (8 launches) | r1 cycles | ×shipped | ×r0 form B (S1T) | r1 vs its static model |
|---|---|---|---|---|---|
| lite | 30,210,226–30,215,128 | 25,221,328–25,228,270 | 1.1977–1.1978 | 1.0327–1.0328 | +0.104 % … +0.132 % (vs 25,195,119) |
| full | 32,781,847–32,786,773 | 27,173,524–27,178,738 | 1.2063–1.2064 | 1.0532 | +0.141 % … +0.160 % (vs 27,135,354) |

(**D**, `evidence/qwen9b/sr/n588_sr5b_chat_compare.log:41`,
`evidence/qwen9b/sr/n588_sr5b_chat_compare.log:43`, and the per-launch lines
9–12, 17–20, 25–28, 33–36.)

* **Totals per scenario:** 125,994,152–125,994,254 → 104,802,011–104,802,101,
  ×1.2022 on every scenario (**D**,
  `evidence/qwen9b/sr/n588_sr5b_chat_compare.log:13`,
  `evidence/qwen9b/sr/n588_sr5b_chat_compare.log:37`).
* **The shipped-order side on the R1 RTL equals S1T's shipped-RTL runs**, to
  the cycle and token, on all 20 launches. This is SR5a's rung 1 repeated per
  launch on the multi-launch chat path (**D**,
  `evidence/qwen9b/sr/n588_sr5b_chat_compare.log:46`).
* **The model comparison uses this lineage's own static makespans**, n601's
  25,195,119 / 27,135,354 (**T**, `evidence/qwen9b/sr/n601_r1_pins.log:9`,
  `evidence/qwen9b/sr/n601_r1_pins.log:15`), not n120's number, as SR4 §4 and
  SR6 §2 require. The plan sets no band here; the chip runs 0.10–0.16 % over
  them.

## 6. Judgment calls and deviations, each recorded

1. **gen_seq_chip_vectors.py gained `--caps`.** The plan's file list names
   only sr_chipvec.sh. The generator validated and executed every stream at
   the empty set, and an r1 stream is refused there. The option defaults to
   empty, so no earlier invocation changes. No other task names the file.
2. **The chat rung ran both sides on the R1 binary**, 8 runs, not only the r1
   side against S1T's shipped-RTL logs. The shipped side is therefore also a
   per-launch compatibility control. Its cycles are compared with S1T's and
   must be identical, and they are (§5).
3. **The chat scripts are copies in `evidence/qwen9b/sr/`**, not edits of
   S1T's committed scripts. Those are cited by S1T's gate.
4. **Log numbering inside n550–n599:**
   * n550 predictions, n551 identity;
   * n552–n555 goldens, n556–n559 chat vectors;
   * n560–n564 runs, n565 memwatch;
   * n570 derive, n571 the token-0 rows;
   * n580–n587 chat runs, n588 chat compare;
   * n590 onward spec_cites.
5. **The runner's cycles-today check is the shipped count** (SV1's use), so a
   run slower than S1-B would still PASS the runner. The band against S1-B is
   judged by sr_derive, stated before the runs (n550).
6. **SR5a's doc, the controller's three edits** (18f728c):
   * The "every existing stream" wording was in the opening only. §2 got a
     one-line scope sentence to the same effect.
   * §3's mask-0 drain is labelled as inferred.
   * §7 got the three caveats.
7. **The regenerated streams** (n551) went to new gitignored prefixes,
   `tb/scripts/w9/sr5b_regen_s{1..4}_r1.e4.*`. The runs used SR4's files, which
   are byte-identical to them.
8. **A no-op python3 on darthplagueis.** While editing the generator, python3
   was invoked once on darthplagueis with an empty heredoc. It ran nothing and
   computed nothing. The edit itself was made with perl.
9. **The memwatch launcher's ssh session hung.** Its local wrapper was later
   reported failed. The watcher itself ran to completion on snoke (**E**,
   `evidence/qwen9b/sr/n565_sr5b_memwatch.log:43`).
10. **Another task committed during the runs.** The stream runs are stamped
    82e2ecb and the chat compare 42b2ebe (SR10's commits landed meanwhile).
    None of SR10's files are an input to any run; every stamp is clean.

## 7. What this does NOT establish

* **Board speed.** 8.803 tok/s is MODEL, the TB scaled by OV1's uniform factor
  (spec §0). The board number is SR8's.
* **Timing, OOC counts or a bitstream of the R1 netlist** (SR7 onward).
* **Context beyond the chip TB's scenario shape.** That is 6 tokens on the
  streams, and on the chat images positions up to 510 with KV ≤ 4 rows (S1T §3).
* **A tighter model.** The FENCE class nets +8,906 cyc only because two
  convention errors cancel:
  * **+23 cyc per FENCE record, measured.** The 981 zero-wait FENCEs have min =
    max = 23 (`evidence/qwen9b/sr/n570_sr5_derive.log:80`). The model charges
    zero.
  * **The single-channel tails are over-priced by ≈22,604 cyc per body**
    across the 389 waiting FENCEs, ≈ −58.1 each NET of the record cost
    (`evidence/qwen9b/sr/n591_sr5b_fix1_tail_net.log:17`). The error is
    class-dependent: DN dn_out is ≈ −9,500 over 96, and the other classes are
    positive (`evidence/qwen9b/sr/n570_sr5_derive.log:83-98`).
  * **The re-fit is REQUIRED before any R2/R3 prediction (SR11b).** A stream
    with a different mix of waiting and non-waiting FENCEs, or of drained
    classes, would not cancel the same way.
* **One TB build.** One Verilator binary (SR5a's) produced every number here.
* **The token-0 accounting shift.** The r1 pass hoists five segment-0 records
  above the first EMB (`evidence/qwen9b/sr/n571_sr5b_token0_rows.log:10-15`),
  so the timeline's token 0 is 17,197 cyc
  (`evidence/qwen9b/sr/n570_sr5_derive.log:32`). No per-token reading of
  an R1 timeline may take token 0 or token 1 at face value.
* **Form B's internal-resource list is still unproven complete** (OV1 §9
  item 3). The chip TB passing 4 streams and 20 chat launches is evidence,
  not proof.

## 8. Logs

| log | what |
|---|---|
| `evidence/qwen9b/sr/n550_sr5_predictions.log` | the prediction and bands (before any run) |
| `evidence/qwen9b/sr/n551_sr5b_stream_identity.log` | r1 stream identity ×3 |
| `evidence/qwen9b/sr/n552_sr5b_chipvec_s1_r1.log` … `evidence/qwen9b/sr/n555_sr5b_chipvec_s4_r1.log` | r1 goldens vs shipped |
| `evidence/qwen9b/sr/n556_sr5b_chat_vectors_c1.log` … `evidence/qwen9b/sr/n559_sr5b_chat_vectors_c4.log` | chat vectors, both orders |
| `evidence/qwen9b/sr/n560_sr5b_chip_s1_r1_control.log` … `evidence/qwen9b/sr/n563_sr5b_chip_s4_r1_control.log` | the four r1 stream runs |
| `evidence/qwen9b/sr/n564_sr5b_chip_s1_r1_timeline.log` | s1 timeline |
| `evidence/qwen9b/sr/n565_sr5b_memwatch.log` | memory |
| `evidence/qwen9b/sr/n570_sr5_derive.log` | derive, verdict, attribution |
| `evidence/qwen9b/sr/n571_sr5b_token0_rows.log` | token 0's rows |
| `evidence/qwen9b/sr/n591_sr5b_fix1_tail_net.log` | fix round 1: the waiting tails net of the record cost |
| `evidence/qwen9b/sr/n580_sr5b_chat_chip_c1_ship.log` … `evidence/qwen9b/sr/n587_sr5b_chat_chip_c4_r1.log` | chat runs |
| `evidence/qwen9b/sr/n588_sr5b_chat_compare.log` | chat compare |
| `evidence/qwen9b/sr/sr5_seed_model_9b_s1_reordB_r1_control.log` (and s2–s4, the s1 timeline, the eight sr5b chat logs) | the simulators' own stdout |

## 9. Fix round 1 (the task review; no re-runs)

* **I2.** §4 and §7 now state the tail error net of the record cost. The
  −35.11 cyc per waiting FENCE already includes that FENCE's 23-cycle record.
  Net, the tails are over-priced by 22,604 cyc per body, −58.11 each
  (`evidence/qwen9b/sr/n591_sr5b_fix1_tail_net.log:16-17`). §7 says the re-fit
  is required before any R2/R3 prediction (SR11b).
* **M1.** §7 names the single TB build and the token-0 accounting shift.
* **M2.** The verdict and §4 now say "not in the mask semantics NET": gross,
  the mask's per-record cost is the largest single term.
* **I1.** `evidence/qwen9b/sr/SR5a_R1_COMPAT.md`, edited at 18f728c after its
  last cites check (n531), is in this round's spec_cites LAST set.
