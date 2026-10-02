# SR13a — R2 on the chip TB: R2 moves neither shipped nor R1, the census, the coverage list, the r2 streams

Task SR13a of `docs/superpowers/plans/2026-09-27-seq-rtl-round.md`, run under the controller's
Addendum 2 ORDERING RULING. Part 1 (§1–§5): Steps 2 and 3 and the SR12 review's coverage items
(1)–(5), handed back as `DONE_STEPS_2_3`. Part 2 (§10–§12), after the controller's resume confirmed
SR11b's review verdict: Step 1 (the prediction, committed at da226ff BEFORE the first r2 run) and
Step 4 (the four r2 streams). No Vivado, no board. Every run was on snoke through
`evidence/qwen9b/sr/sr_run.sh`, log block `n1300–n1349` then `n1349a…` (SR11a's precedent).

**Labels.** **E** = printed by a run of this task, cited to its log line. **D** = derived by
`evidence/qwen9b/sr/sr13a_derive.py` on snoke, cited to the line that printed it. **T** = transcribed
from an earlier gate, cited to its source. **MODEL** = a tok/s scaled from TB cycles by OV1's uniform
board factor (137.121 / 131.138 ms), not a board measurement. **Sign convention: measured − model
throughout** (as SR5b); SR11b_R2_PASS.md states model − measured, so its signs are the opposite of this doc's.

## Verdict

**GREEN. The model held. There is nothing to STOP on.**

* **The r2 streams: tokens IDENTICAL, 4 of 4.** All four print `TB_SEQ_CHIP PASS` and their six tokens
  equal the shipped record (§11).
* **s1: HELD, −0.047 %.** The token-4 body window measured **26,171,253 cyc** against the committed
  prediction **26,183,590** (SR11b's corrected, additive form): −12,337 cyc, inside ±0.5 % AND inside the
  placement band 26,166,378–26,183,590 (**D**, `evidence/qwen9b/sr/n1349g_sr13a_derive.log:42`). Beside it,
  the plan's uncorrected census replay 26,146,927 is +0.093 % off (same line).
* **s2–s4: HELD.** Every r2 / R1 is < 1 and within 0.0013 % of s1's; r2 / shipped within 0.0001 %
  (**D**, `evidence/qwen9b/sr/n1349g_sr13a_derive.log:46-48`).
* **Whole run ×1.2528 vs shipped and ×1.0379 vs R1** on every seed: 104.674 ms/token on the TB; 9.137
  tok/s board-scaled (MODEL), against shipped 7.293 and R1 8.803 (**D**,
  `evidence/qwen9b/sr/n1349g_sr13a_derive.log:24-25`). Token 4 alone: 9.136 against the model's 9.131
  (`evidence/qwen9b/sr/n1349g_sr13a_derive.log:43`).
* **The residual is the DMA stall the band was built for.** Measured − model = −12,337: the additive
  residual's −19,308 and the CMD class's +19,308 cancel exactly (CMD lane work is R1's to the cycle);
  the FENCE class is −11,608, of which dn_out is −11,286 — the one SLD stall absorbed by a dn_out wait,
  as at R1; LDC/MVGO/EMB −729 as at R1 (§12).
* **Rung 1 (part 1): R2 moves neither shipped nor R1**, cycle-identical ×8; the census bit-exact;
  coverage (2)–(5) 12/12 + offifo PASS, the mutant caught (§2–§5).

### Part 1 verdict (Steps 2, 3 and coverage (1)–(5))

**GREEN on every item run (handed back as DONE_STEPS_2_3).**

* **Rung 1: R2 moves neither shipped nor R1.** The four shipped streams run on the R2 binary in
  **196,706,821 / 196,707,670 / 196,707,670 / 196,706,833 cycles, identical to S4's to the cycle**, and
  the four r1 streams in **162,967,117 / 162,965,710 / 162,965,710 / 162,967,195, identical to SR5b's to
  the cycle**; all eight `TB_SEQ_CHIP PASS` with tokens IDENTICAL (§2). This is also coverage item (1)'s
  full-chip bank-0 identity (every MVGO in these streams runs at bank 0 on the 9B shapes through the moved g_q source).
* **The layer census: bit-exact**, 56,576 commands / 8,600,034 checks, the per-opcode table
  byte-identical to T14A's (§3).
* **Coverage (2) XBANK at ng 32 and 48, (3) RBANK at ng 64 and 96, (4) the overlap pattern**: synthetic
  streams through seq_unit, the movers, the four real matvec_chan / matvec_engine instances,
  bit-exact against `ref/seq_model.py` on all 65,536 scratch words, **4 seeds each, 12 of 12 PASS**; the
  timeline shows **8 of 8** MOVX/MOVY under a running stream with the engine busy their whole window on
  every seed; SR12's bank-blind mutant FAILS all three (§4).
* **Coverage (5): `tb_seq_offifo` on the R2 RTL, PASS** (41 runs, SEQ_CAPS fab1ca03 on each) (§5).
* **SEQ_CAPS:** the chip binary reads back **fab1ca03** after every run (§1).


## 1. The binary

| item | value | cite |
|---|---|---|
| RTL | 9eeaacb (SR12 complete); `git diff --stat 9eeaacb HEAD -- rtl/ tb/*.sv tb/*.cpp tb/*.svh tb/Makefile` was EMPTY at ecd536c | checked before any edit |
| named commit | 0044b1b = 9eeaacb's RTL + this task's two TB edits (§6 item 1) | **E**, `evidence/qwen9b/sr/n1301_build_sr13.log:27` (63 files byte-identical to 0044b1b) |
| binary | `tb/obj_dir_seq_chip_sr13/tb_seq_chip_9b_sr13`, sha256 0aa1c5acfd2556bbaa5861c2c9b5d5572429879b3fc4dc09bcd59e3019d2a373 | **E**, `evidence/qwen9b/sr/n1301_build_sr13.log:76` |
| recipe | `evidence/qwen9b/sr/sr_build.sh 0044b1b 13` (SR5a's snapshot build, the census recipe `tb_seq_chip_9b_tl_build`, NMV 4, WIMGPC 1, -Wall) | **E**, `evidence/qwen9b/sr/n1301_build_sr13.log:4` |
| lint of the edited TB | `make lint_seq_chip_9b_tl`, rc 0, 0 warnings | **E**, `evidence/qwen9b/sr/n1300_sr13a_lint_chip_tl.log` |
| SEQ_CAPS | the binary reads **fab1ca03** = hwmap's {R1,R2} word, on every run of it (the new post-run readback) | **E**, `evidence/qwen9b/sr/sr13_seed_sr13a_cov_rbank_control.log:15`; `evidence/qwen9b/sr/n1340_sr13a_chip_cov_seeds234.log:27`; rung 1: `evidence/qwen9b/sr/sr13_seed_model_9b_s1_control.log:21` and the same line of the other seven |
| obj_dir hygiene | before the build and before the mutant build, `pgrep` on snoke, kyloren and darthplagueis found no other user of any `obj_dir_seq_chip_sr13*` | — |
| HEAD since the binary | SR11c's cite-drift commits (f25c955) touched `rtl/layer_chan.sv`, `rtl/matvec_engine.sv`, `rtl/state_dma.sv` in COMMENTS only: `git diff 0044b1b HEAD -- rtl/ tb/` with `//` comments stripped differs in 0 lines; the binary stays valid for every run here | **E**, `evidence/qwen9b/sr/n1349f_sr13a_rtl_comment_only.log` |

## 2. Rung 1 on the R2 RTL — shipped ×4 and r1 ×4 (Step 2; coverage item (1))

Every stream's `.seq` / `.chip` sha256 was re-checked first against the earlier gates' runs
(**E**, `evidence/qwen9b/sr/n1302_sr13a_stream_identity.log`; the shipped `.seq` = SR4's pins, the r1 `.seq`
= SR4's pins 4e11a2ae / cc982e4f / 0f85a974 / 492e0def, the `.chip` goldens = those SR5a/SR5b ran,
e.g. `evidence/qwen9b/sr/n510_chip_s1_compat.log:8`, `evidence/qwen9b/sr/n560_sr5b_chip_s1_r1_control.log:8`).
Each run used `--cycles-equal` against the reference, so ANY cycle difference FAILS the runner.

| stream | .seq / .chip sha256 | TB_SEQ_CHIP | cycles (R2 RTL) | reference | Δ | tokens | wall | verdict |
|---|---|---|---|---|---|---|---|---|
| shipped s1 | 9760899d… / e8839281… | PASS (`evidence/qwen9b/sr/n1310_sr13a_chip_s1_shipped.log:31`) | **196,706,821** (`evidence/qwen9b/sr/n1310_sr13a_chip_s1_shipped.log:33`) | 196,706,821 (S4) | **0** | IDENTICAL (`evidence/qwen9b/sr/n1310_sr13a_chip_s1_shipped.log:36`) | 8,770 s | PASS (`evidence/qwen9b/sr/n1310_sr13a_chip_s1_shipped.log:39`) |
| shipped s2 | dae58734… / f5db0869… | PASS (`evidence/qwen9b/sr/n1311_sr13a_chip_s2_shipped.log:31`) | **196,707,670** (`evidence/qwen9b/sr/n1311_sr13a_chip_s2_shipped.log:33`) | 196,707,670 (S4) | **0** | IDENTICAL (`evidence/qwen9b/sr/n1311_sr13a_chip_s2_shipped.log:36`) | 8,992 s | PASS (`evidence/qwen9b/sr/n1311_sr13a_chip_s2_shipped.log:39`) |
| shipped s3 | 8dfad7db… / 8090d0b1… | PASS (`evidence/qwen9b/sr/n1312_sr13a_chip_s3_shipped.log:31`) | **196,707,670** (`evidence/qwen9b/sr/n1312_sr13a_chip_s3_shipped.log:33`) | 196,707,670 (S4) | **0** | IDENTICAL (`evidence/qwen9b/sr/n1312_sr13a_chip_s3_shipped.log:36`) | 8,929 s | PASS (`evidence/qwen9b/sr/n1312_sr13a_chip_s3_shipped.log:39`) |
| shipped s4 | 3483d82a… / 09f38d87… | PASS (`evidence/qwen9b/sr/n1313_sr13a_chip_s4_shipped.log:31`) | **196,706,833** (`evidence/qwen9b/sr/n1313_sr13a_chip_s4_shipped.log:33`) | 196,706,833 (S4) | **0** | IDENTICAL (`evidence/qwen9b/sr/n1313_sr13a_chip_s4_shipped.log:36`) | 8,963 s | PASS (`evidence/qwen9b/sr/n1313_sr13a_chip_s4_shipped.log:39`) |
| r1 s1 | 4e11a2ae… / fa6a57cc… | PASS (`evidence/qwen9b/sr/n1314_sr13a_chip_s1_r1.log:31`) | **162,967,117** (`evidence/qwen9b/sr/n1314_sr13a_chip_s1_r1.log:33`) | 162,967,117 (SR5b) | **0** | IDENTICAL (`evidence/qwen9b/sr/n1314_sr13a_chip_s1_r1.log:36`) | 7,754 s | PASS (`evidence/qwen9b/sr/n1314_sr13a_chip_s1_r1.log:39`) |
| r1 s2 | cc982e4f… / af973f81… | PASS (`evidence/qwen9b/sr/n1315_sr13a_chip_s2_r1.log:31`) | **162,965,710** (`evidence/qwen9b/sr/n1315_sr13a_chip_s2_r1.log:33`) | 162,965,710 (SR5b) | **0** | IDENTICAL (`evidence/qwen9b/sr/n1315_sr13a_chip_s2_r1.log:36`) | 7,730 s | PASS (`evidence/qwen9b/sr/n1315_sr13a_chip_s2_r1.log:39`) |
| r1 s3 | 0f85a974… / 19bea94a… | PASS (`evidence/qwen9b/sr/n1316_sr13a_chip_s3_r1.log:31`) | **162,965,710** (`evidence/qwen9b/sr/n1316_sr13a_chip_s3_r1.log:33`) | 162,965,710 (SR5b) | **0** | IDENTICAL (`evidence/qwen9b/sr/n1316_sr13a_chip_s3_r1.log:36`) | 7,506 s | PASS (`evidence/qwen9b/sr/n1316_sr13a_chip_s3_r1.log:39`) |
| r1 s4 | 492e0def… / 6cff0d04… | PASS (`evidence/qwen9b/sr/n1317_sr13a_chip_s4_r1.log:31`) | **162,967,195** (`evidence/qwen9b/sr/n1317_sr13a_chip_s4_r1.log:33`) | 162,967,195 (SR5b) | **0** | IDENTICAL (`evidence/qwen9b/sr/n1317_sr13a_chip_s4_r1.log:36`) | 7,670 s | PASS (`evidence/qwen9b/sr/n1317_sr13a_chip_s4_r1.log:39`) |

References (**T**): the S4 counts, `evidence/qwen9b/ov/SV1_S1_VERIFY.md:146-148` (and
`evidence/qwen9b/s4/S4_REPLAY.md:398-401`); SR5b's r1 counts, `evidence/qwen9b/sr/SR5b_R1_CHIP.md` §2
(`evidence/qwen9b/sr/n560_sr5b_chip_s1_r1_control.log:30` and its three siblings). The runner reads each token record
out of `evidence/qwen9b/s4/S4_REPLAY.md` under the shipped stem. `TB_SEQ_CHIP PASS` also compares the full
architectural end state (scratch, XRF, TCNT, the 112 state blocks) against each stream's golden. All
eight ran in parallel on snoke beside the census and the coverage runs.


## 3. The layer census control (Step 3)

* **Bit-exact.** `TB_LAYER_CENSUS PASS: 56576 cmds, 8600034 checks bit-exact` (**E**,
  `evidence/qwen9b/sr/n1320_sr13a_layer_census.log:78`; header line (errors=0) at
  `evidence/qwen9b/sr/n1320_sr13a_layer_census.log:42`), the check count T14A and SR5a reported (**T**,
  `evidence/qwen9b/sr/n520_layer_census_sr5.log:76`).
* **The per-opcode table is byte-identical to T14A's**: `evidence/qwen9b/s4/census_sr13.txt` and
  `evidence/qwen9b/s4/census_t14a.txt` are both sha256 98b9451c…, `cmp` agrees (**E**,
  `evidence/qwen9b/sr/n1321_sr13a_census_table_vs_t14a.log:7-9`). The layer sources differ from T14A's
  1dd2889 in comments only, as SR5a recorded (same log, lines 10-13).
* Recipe: SR5a's (`evidence/qwen9b/s4/run_s4_census.sh`, G5C's invocation, LAT 8, draining), because
  `evidence/qwen9b/g4/run_g4b_census.sh` is SUPERSEDED and refuses to run (SR5a §6 item 2). Built from
  the working tree 0044b1b with rtl/ clean (**E**, `evidence/qwen9b/sr/n1320_sr13a_layer_census.log:2`;
  the +dirty stamp is other tasks' non-RTL files, §6 item 5). Wall 4,029 s.
* `layer_0` is untouched by R2: SR12 edits none of the census's files.

## 4. Coverage items (2)–(4): synthetic R2 streams on the REAL engine

**The artifacts.** `evidence/qwen9b/sr/sr13a_cov.py` writes, per kind and seed, a W4 g128 weight set
(`ref/w4a8_ref.py` quantize + pack, the 9B shifts 7 / 8 / 8 / 9 at K 4096 / 6144 / 8192 / 12288,
per-channel repack over 4 channels, planned by `sw/hwmap.py` `plan_weights`) and a record stream of
LDC / MOVX / MVGO / MOVY / FENCE / HALT built with `ref/seq_format.py`. It then checks, before
reporting PASS:
* the stream is VALID at caps {R1,R2} with the 9B SHAPE layout stated, and REFUSED at {R1} and at {}
  (the first refusal printed: a MOVX start word, or MVGO SHAPE bits 29/30) (**E**,
  `evidence/qwen9b/sr/n1304_sr13a_cov_xbank.log:10-12`, `evidence/qwen9b/sr/n1305_sr13a_cov_rbank.log:10-12`,
  `evidence/qwen9b/sr/n1306_sr13a_cov_overlap.log:10-12`);
* `ref/seq_model.py` (SR11a's R2 model, running ranges and unwritten-read refusals armed) runs it to
  HALT at {R1,R2} against the files on disk, nothing pending at HALT, and its final scratch equals the
  script's own direct computation (matvec_y32 + the MOVY shift/clip) on all 65,536 words (**E**,
  `evidence/qwen9b/sr/n1304_sr13a_cov_xbank.log:55-56`, `evidence/qwen9b/sr/n1305_sr13a_cov_rbank.log:55-56`,
  `evidence/qwen9b/sr/n1306_sr13a_cov_overlap.log:59-60`).

The golden is the campaign's own generator, `tb/scripts/gen_seq_chip_vectors.py --caps R1,R2` (SR5b's
option), which replays the stream through `ref/seq_model.py` and checks EVERY scratch word (65,536, no
staging words), the XRF, TCNT, EOUT/AMAX and the final PC (**E**,
`evidence/qwen9b/sr/n1307_sr13a_chipvec_xbank.log:15`, `evidence/qwen9b/sr/n1308_sr13a_chipvec_rbank.log:15`,
`evidence/qwen9b/sr/n1309_sr13a_chipvec_overlap.log:15`). The chip TB is the full SEQ-driven chip:
seq_unit, seq_movers, the four REAL matvec_chan/matvec_engine instances, the real layer_chan and the
per-channel weight regions — no stub. Seeds: s1 (1301/1302/1303) and s2–s4 (x301/x302/x303), 12
artifacts.

| item | stream (per seed) | what it exercises | chip TB, s1 | chip TB, s2–s4 |
|---|---|---|---|---|
| (2) XBANK | `xbank`: ch0 ng 32, ch1 ng 48, ch2 ng 48, ch3 ng 32; bank 1 = xB loaded FIRST, then bank 0 = xA; an XBANK MVGO (512 rows), a bank-0 MVGO, an XBANK\|RBANK MVGO read back from row 2048; at ng 48 bank 1 fills XWIN words 1536..3071 exactly | 41 records, 16 bank fields | PASS, 275,845 cyc, 65,536 words bit-exact (**E**, `evidence/qwen9b/sr/n1330_sr13a_chip_cov_xbank.log:26`) | PASS ×3, 275,845 cyc each (**E**, `evidence/qwen9b/sr/n1340_sr13a_chip_cov_seeds234.log`) |
| (3) RBANK | `rbank`: ch0 ng 64, ch1 ng 96, ch2 ng 64, ch3 ng 96; RES bank 0 = W·xA and bank 1 = W·xB at the full 2048 rows; both halves drained, a MOVY ending at row 4096, rows 3000..3100, a pairs32 MOVY of bank 1, a bank-0 slice, a partial 512-row RBANK run | 41 records, 18 bank fields | PASS, 1,404,487 cyc (**E**, `evidence/qwen9b/sr/n1331_sr13a_chip_cov_rbank.log:26`) | PASS ×3, 1,404,487 cyc each (same log) |
| (4) overlap | `overlap`, on (ch0 main, ch1 other, ng 32) and (ch2, ch3, ng 48) — see below | 45 records, 6 no-wait MVGOs, 4 FENCEs (2 masked, 2 two-channel) | PASS, 217,156 cyc (**E**, `evidence/qwen9b/sr/n1332_sr13a_chip_cov_overlap.log:26`) | PASS ×3, 217,156 cyc each (same log) |

The overlap stream, per pair (main c, other o), in issue order: a waiting MVGO leaves W·xA in RES bank 1;
MOVX xB into XWIN bank 0; **a NO-WAIT bank-0 MVGO**; **a bank-1 MOVX (xC) while it runs**; **a MOVY of
rows 2048.. drained while that MVGO rewrites RES bank 0**; a no-wait MVGO on o; **a MASKED FENCE of c
only**; a MOVY of c's bank 0; a no-wait XBANK|RBANK MVGO on c; **a bank-0 MOVX (xA) while it runs**; a
MOVY of RES bank 0 while it writes bank 1; a FENCE of c and o; the two results drained; a final waiting
bank-0 MVGO proving the mid-run MOVX landed.

**It really overlapped.** The timeline instrument (`+timeline=`, which reproduces the control's cycle
count: 217,156 = 217,156, **E**, `evidence/qwen9b/sr/n1333_sr13a_chip_cov_overlap_timeline.log:28`) records
each record window's per-channel engine-busy count. `evidence/qwen9b/sr/sr13a_overlap_tl.py` marks every
MOVX/MOVY issued on a channel whose no-wait MVGO is still pending: **8 of 8 ran with that channel's
engine busy for every cycle of their window**, on every seed (**E**,
`evidence/qwen9b/sr/n1334_sr13a_overlap_timeline_read.log:54-55`;
`evidence/qwen9b/sr/n1340_sr13a_chip_cov_seeds234.log:103-104`, `:202-203`, `:301-302`). The masked FENCE
(pc 12, mask 0b0001) drains ch0 while ch1 stays busy through the next record, the ch0 MOVY (**E**,
`evidence/qwen9b/sr/n1334_sr13a_overlap_timeline_read.log:21-22`). The CSV is gitignored in
`tb/scripts/w9/`; its sha256 is printed by the run (**E**,
`evidence/qwen9b/sr/n1333_sr13a_chip_cov_overlap_timeline.log:30`).

**Non-vacuity: the bank-blind mutant FAILS all three.** `evidence/qwen9b/sr/sr13a_mut_build.sh` applies
SR12's negative-control mutant (the five seds of `evidence/qwen9b/sr/sr12_rtl_copies.sh`: MOVX start word
and MOVY start row latched as 0, x_line / row_in loaded as if XBANK / RBANK were 0) to a snapshot of
0044b1b — exactly 5 changed lines (**E**, `evidence/qwen9b/sr/n1335_sr13a_build_mut.log:18`) — and builds
`tb/obj_dir_seq_chip_sr13_mut` (sha256 32022fcb…, `evidence/qwen9b/sr/n1335_sr13a_build_mut.log:67`). On it,
xbank, rbank and overlap each die on `too many scratch mismatches` (**E**,
`evidence/qwen9b/sr/n1336_sr13a_chip_cov_xbank_MUTANT.log:16`, `evidence/qwen9b/sr/n1337_sr13a_chip_cov_rbank_MUTANT.log:16`,
`evidence/qwen9b/sr/n1338_sr13a_chip_cov_overlap_MUTANT.log:16`). The generator's own sequential estimate
agrees: 8 of 12, 8 of 14 and 4 of 12 MOVY blocks per stream differ under a bank-blind RTL, at least one
per channel and case (**E**, `evidence/qwen9b/sr/n1304_sr13a_cov_xbank.log:70`,
`evidence/qwen9b/sr/n1305_sr13a_cov_rbank.log:72`, `evidence/qwen9b/sr/n1306_sr13a_cov_overlap.log:74`).

## 5. Coverage item (5): tb_seq_offifo on the R2 RTL

The target was hard-wired to `obj_dir_tb_seq`; it now runs `$(SEQ_OBJ)` (default unchanged; `tb/Makefile`,
commit 0044b1b). Run as `make tb_seq_offifo SEQ_OBJ=obj_dir_seq_unit_sr13 SEQ_VEC=scripts_scratch/seqvec_sr13`
on the tree 0044b1b: `TB_SEQ_OFFIFO OK: 3 depths x {axil, blat 0, blat 8} + 24 race runs + 8 stream
races + depth self-test` (**E**, `evidence/qwen9b/sr/n1325_sr13a_tb_seq_offifo.log:618`), 41 `SEQ PASS`,
each reading `SEQ_CAPS fab1ca03 == hwmap fab1ca03` (for example
`evidence/qwen9b/sr/n1325_sr13a_tb_seq_offifo.log:88`). The race-on-normal-streams leg runs the four seeds.

## 6. Judgment calls and deviations, each recorded

1. **Two TB edits, committed before the build (0044b1b).** (a) `tb/tb_seq_chip.sv` reads SEQ_CAPS (0x64)
   and prints it, with an optional `+caps_expect=`: the addendum asks that the binary's caps be read
   back, and the chip TB had no such read. The read sits AFTER every launch and after the two AXI-Lite
   counter reads, so it cannot move a measured cycle or a printed count — rung 1's cycle identity (§2)
   is the check. `tb/tb_seq_chip.sv` is outside the brief's file list; recorded here. (b) `tb/Makefile`
   `tb_seq_offifo` uses `$(SEQ_OBJ)`, the addendum's item (5) fix.
2. **The coverage streams are synthetic, not emitted.** They are built from `ref/seq_format.py` records
   and replayed by `ref/seq_model.py` as the golden, as the dispatch specifies. Their artifacts live in
   the gitignored `tb/scripts/w9/sr13a_cov_*`; every sha256 is in the generation logs
   (n1304–n1309, n1339). Only the generator, the timeline reader and the mutant builder are committed.
3. **n1303 is superseded, kept.** It used a shift of worst-case + 7 (14/15, not the 9B manifests' 7/9)
   and loaded XWIN bank 0 first, which left the XBANK blocks vacuous under a bank-blind RTL; both fixed
   (137ee23) and regenerated as n1304. Its artifacts were deleted before n1304 wrote the same stem.
4. **Seeds 2–4 were generated and run in one log each** (n1339, n1340) to keep inside the task's log
   block. The generation pipeline filtered the disassembly with a pattern that also dropped the VALID /
   REFUSED lines of seeds 2–4; each seed's `SR13A_COV … PASS` line is printed only after those checks
   pass (`evidence/qwen9b/sr/n1339_sr13a_cov_seeds234.log:34` and the eight like it). The timeline reads
   in n1340 hash the CSV they read rather than the run's logged sha (the s1 read, n1334, checks the logged
   one).
5. **Stamps.** The runs from n1301 on carry `+dirty` for other tasks' in-flight files only
   (`evidence/qwen9b/sr/sr11b_model_correction.py`, SR11b's fix round; SR13b's gate doc), none an input to
   any run here. SR11b's fix round committed during the runs (93380f8); no file it touched is an input.
6. **Rule slip (text only).** darthplagueis ran `python3` once, to splice the two TB edits into
   `tb/tb_seq_chip.sv` and `tb/Makefile` (a string replace; no arithmetic). Every numeric run was on
   snoke; later edits used perl.
7. **The caps-readback edit is mine** (0044b1b, accepted by the controller; the task review checks the
   diff). Proof that it moved nothing measured: rung 1's eight runs on the edited binary are Δ 0 against
   S4 and SR5b (§2). The r2 runs read fab1ca03 too
   (`evidence/qwen9b/sr/sr13_seed_model_9b_s1_reordB_r2_control.log:21`), so the r2 streams ran on a
   device reporting {R1,R2}, as the addendum requires before they are admitted.
8. **The r2 runs use `--cycles-today` = each seed's R1 count**, so the runner itself fails an r2 run
   that is not faster than R1; the bands are judged by `evidence/qwen9b/sr/sr13a_derive.py`.
9. **Log numbering, part 2:** n1343–n1349, then n1349a–n1349g (SR11a's lettered precedent);
   spec_cites follows at n1349h onward.

## 7. What this does NOT establish

* **Board speed.** 9.137 tok/s is MODEL (the TB scaled by OV1's uniform factor), not a board log.
* **A placed DMA stall.** The r2 order incurred the same SLD stall R1 did and a dn_out FENCE absorbed
  it (§12); no order-only rule predicts that (SR11b §2.3). It fell inside the placement band; another
  order may not.
* **One TB build**, and the synthetic streams do not load the 9B model's weights.
* The synthetic streams check bank semantics and the overlap on the real engine at 512–2048 rows; they
  do not load the 9B model's weights and do not measure a speed.
* Timing, OOC counts or any bitstream of the R2 netlist (SR14), and nothing on the board.

## 8. Logs

| log | what |
|---|---|
| `evidence/qwen9b/sr/n1300_sr13a_lint_chip_tl.log` | lint of the edited chip TB |
| `evidence/qwen9b/sr/n1301_build_sr13.log` | the binary |
| `evidence/qwen9b/sr/n1302_sr13a_stream_identity.log` | shipped / r1 / r2 stream hashes |
| `evidence/qwen9b/sr/n1303_sr13a_cov_xbank.log` | superseded first xbank generation (§6 item 3) |
| `evidence/qwen9b/sr/n1304_sr13a_cov_xbank.log` … `evidence/qwen9b/sr/n1306_sr13a_cov_overlap.log` | coverage artifacts, s1 |
| `evidence/qwen9b/sr/n1307_sr13a_chipvec_xbank.log` … `evidence/qwen9b/sr/n1309_sr13a_chipvec_overlap.log` | their chip goldens |
| `evidence/qwen9b/sr/n1310_sr13a_chip_s1_shipped.log` … `evidence/qwen9b/sr/n1317_sr13a_chip_s4_r1.log` | rung 1 |
| `evidence/qwen9b/sr/n1320_sr13a_layer_census.log`, `evidence/qwen9b/sr/n1321_sr13a_census_table_vs_t14a.log` | the census |
| `evidence/qwen9b/sr/n1325_sr13a_tb_seq_offifo.log` | tb_seq_offifo |
| `evidence/qwen9b/sr/n1330_sr13a_chip_cov_xbank.log` … `evidence/qwen9b/sr/n1333_sr13a_chip_cov_overlap_timeline.log`, `evidence/qwen9b/sr/n1334_sr13a_overlap_timeline_read.log` | coverage on the chip, s1 |
| `evidence/qwen9b/sr/n1335_sr13a_build_mut.log`, `evidence/qwen9b/sr/n1336_sr13a_chip_cov_xbank_MUTANT.log` … `evidence/qwen9b/sr/n1338_sr13a_chip_cov_overlap_MUTANT.log` | the negative control |
| `evidence/qwen9b/sr/n1339_sr13a_cov_seeds234.log`, `evidence/qwen9b/sr/n1340_sr13a_chip_cov_seeds234.log` | seeds 2–4 |
| `evidence/qwen9b/sr/n1343_sr13a_predictions.log` | Step 1: the prediction and bands (committed before any r2 run) |
| `evidence/qwen9b/sr/n1344_sr13a_r2_stream_identity.log` | r2 stream hashes vs SR11b |
| `evidence/qwen9b/sr/n1345_sr13a_chipvec_s1_r2.log` … `evidence/qwen9b/sr/n1348_sr13a_chipvec_s4_r2.log` | r2 goldens |
| `evidence/qwen9b/sr/n1349a_sr13a_chip_s1_r2.log` … `evidence/qwen9b/sr/n1349d_sr13a_chip_s4_r2.log`, `evidence/qwen9b/sr/n1349e_sr13a_chip_s1_r2_timeline.log` | Step 4 runs |
| `evidence/qwen9b/sr/n1349f_sr13a_rtl_comment_only.log` | HEAD's rtl/ delta is comment-only |
| `evidence/qwen9b/sr/n1349g_sr13a_derive.log` | derive, band verdict, attribution |
| `evidence/qwen9b/sr/sr13_seed_*.log`, `evidence/qwen9b/sr/sr13_mut_seed_*.log` | the simulators' own stdout |

## 9. Doc gate

spec_cites over this doc, LAST and alone on the committed tree: n1341 (tree d6d0b45) FAIL 1, a backticked
header quote cited 36 lines from its own line; kept as the record, the quote unbackticked; n1342 is the
run of record for part 1. Part 2 (§10–§12 and the edits to §1, §6–§8): spec_cites LAST and alone
again, n1349h onward.

## 10. Step 1 — the prediction and bands, committed before the first r2 run

Committed at da226ff (the r2 runs launched at 15:11 on fb1ea0e, after it; **D**,
`evidence/qwen9b/sr/n1343_sr13a_predictions.log`):
* **s1 token-4 body window: 26,183,590 cyc** = 104.734 ms, SR11b's corrected prediction in the
  ADDITIVE form (`reorder_e4.predict()`: lane 26,164,282 + the inherited CMD residual 19,308; **T**,
  `evidence/qwen9b/sr/n1165_reorder_s1_B_r2.log:56`, `evidence/qwen9b/sr/n1182_sr11b_r2_derive.log:27`), with its
  placement band **26,166,378–26,183,590** (the 17,212-cyc DMA stall absorbed by a FENCE wait or not;
  `evidence/qwen9b/sr/n1182_sr11b_r2_derive.log:28`) (**D**, `evidence/qwen9b/sr/n1343_sr13a_predictions.log:7-8`).
* **Beside it, the uncorrected body replay 26,146,927** (the census R1+R2 row,
  `evidence/qwen9b/ov/n120_sr0_clock_sens.log:18` = `evidence/qwen9b/sr/n1165_reorder_s1_B_r2.log:50`) (**D**,
  `evidence/qwen9b/sr/n1343_sr13a_predictions.log:9`).
* **Bands (SR5b's):** HELD ±0.5 % = 26,052,672–26,314,508; LOOSE ±2 % = 25,659,918–26,707,262
  (attribute by class per SR5b §7 before calling a miss); outside ±2 % a STOP (**D**,
  `evidence/qwen9b/sr/n1343_sr13a_predictions.log:11-13`).
* **s2–s4:** whole-run r2 / R1 (SR5b's measured cycles, same seed) < 1 and within ±0.5 % of s1's;
  r2 / shipped likewise (**D**, `evidence/qwen9b/sr/n1343_sr13a_predictions.log:14`).
* **Streams re-hashed first:** the four r2 `.seq` files are SR11b's 117ed8b0 / 5d0a8bdd / e35772cc /
  8b16c7b1, equal to the shas n1165–n1168 wrote (**E**, `evidence/qwen9b/sr/n1344_sr13a_r2_stream_identity.log`).
* **Goldens:** `evidence/qwen9b/sr/sr_chipvec.sh … R1,R2`; each r2 golden is identical to the shipped
  golden except NREC/PC (**E**, for example `evidence/qwen9b/sr/n1345_sr13a_chipvec_s1_r2.log`, its
  `SR_CHIPVEC … GOLDEN IDENTICAL TO SHIPPED` line; the same in n1346–n1348).

## 11. Step 4 — the four r2 streams on the R2 chip TB

| seed | .seq | TB_SEQ_CHIP | cycles / 6 tok | ms/token (D) | ×shipped (D) | ×R1 (D) | r2/R1 (D) | tokens | band (D) |
|---|---|---|---|---|---|---|---|---|---|
| s1 | 117ed8b0… | PASS (`evidence/qwen9b/sr/n1349a_sr13a_chip_s1_r2.log:29`) | **157,010,908** (`evidence/qwen9b/sr/n1349a_sr13a_chip_s1_r2.log:30`) | 104.674 | 1.2528 | 1.0379 | 0.963451 | IDENTICAL (`evidence/qwen9b/sr/n1349a_sr13a_chip_s1_r2.log:34`) | HELD, token 4 −0.047 % |
| s2 | 5d0a8bdd… | PASS (`evidence/qwen9b/sr/n1349b_sr13a_chip_s2_r2.log:29`) | **157,011,556** (`evidence/qwen9b/sr/n1349b_sr13a_chip_s2_r2.log:30`) | 104.674 | 1.2528 | 1.0379 | 0.963464 | IDENTICAL (`evidence/qwen9b/sr/n1349b_sr13a_chip_s2_r2.log:34`) | HELD, +0.0013 % vs s1 |
| s3 | e35772cc… | PASS (`evidence/qwen9b/sr/n1349c_sr13a_chip_s3_r2.log:29`) | **157,011,490** (`evidence/qwen9b/sr/n1349c_sr13a_chip_s3_r2.log:30`) | 104.674 | 1.2528 | 1.0379 | 0.963463 | IDENTICAL (`evidence/qwen9b/sr/n1349c_sr13a_chip_s3_r2.log:34`) | HELD, +0.0012 % |
| s4 | 8b16c7b1… | PASS (`evidence/qwen9b/sr/n1349d_sr13a_chip_s4_r2.log:29`) | **157,010,986** (`evidence/qwen9b/sr/n1349d_sr13a_chip_s4_r2.log:30`) | 104.674 | 1.2528 | 1.0379 | 0.963451 | IDENTICAL (`evidence/qwen9b/sr/n1349d_sr13a_chip_s4_r2.log:34`) | HELD, +0.0000 % |
| s1 | timeline | PASS (`evidence/qwen9b/sr/n1349e_sr13a_chip_s1_r2_timeline.log:31`) | 157,010,908 = the control (`evidence/qwen9b/sr/n1349e_sr13a_chip_s1_r2_timeline.log:32`) | — | — | — | — | IDENTICAL (`evidence/qwen9b/sr/n1349e_sr13a_chip_s1_r2_timeline.log:36`) | — |

* Derived columns: `evidence/qwen9b/sr/n1349g_sr13a_derive.log:24-31`; bands
  `evidence/qwen9b/sr/n1349g_sr13a_derive.log:42` and `evidence/qwen9b/sr/n1349g_sr13a_derive.log:46-48`; 4/4
  tokens IDENTICAL and runner PASS (`evidence/qwen9b/sr/n1349g_sr13a_derive.log:55`).
* **s1 token-4 body window 26,171,253 cyc** (`evidence/qwen9b/sr/n1349e_sr13a_chip_s1_r2_timeline.log:56`),
  −12,337 = **−0.047 %** vs 26,183,590, inside the placement band, +0.093 % vs the uncorrected 26,146,927
  (**D**, `evidence/qwen9b/sr/n1349g_sr13a_derive.log:42`).
* **Per token** (shipped / R1 / r2): every body token is ×1.2527–1.2535 vs shipped and ×1.0379–1.0380
  vs R1 (**D**, `evidence/qwen9b/sr/n1349g_sr13a_derive.log:34-41`); token 0 carries R1's 17,197-cyc hoist
  accounting shift unchanged (SR5b §3).
* **Speed, MODEL on the TB** (OV1 uniform factor): 104.674 ms/token = **9.137 tok/s** whole run, against
  shipped 7.293 and R1 8.803 (**D**, `evidence/qwen9b/sr/n1349g_sr13a_derive.log:25`); token 4 9.136
  against the model's 9.131 (`evidence/qwen9b/sr/n1349g_sr13a_derive.log:43`). SR11b's modelled
  ×1.2522 vs shipped is met (×1.2528 measured on the body window and on the whole run).
* The informational whole-run model (no band) is −0.048 % off on every seed
  (`evidence/qwen9b/sr/n1349g_sr13a_derive.log:24`).
* The timeline CSV is gitignored; its sha256 is committed at
  `evidence/qwen9b/sr/sr13a_timeline_model_9b_s1_reordB_r2.csv.sha256` and checked before any row is read.

## 12. Attribution by class, token 4, s1 (SR5b's method)

The band was held, so attribution was not required; done for the record.
`evidence/qwen9b/sr/sr13a_derive.py` rebuilds the r2 schedule with the pass's own functions,
**reproduces both 26,146,927 (census replay) and 26,183,590 (predict())**, and checks the emitted body
against the r2 stream on disk: **40,171 of 40,171 records identical** (**D**,
`evidence/qwen9b/sr/n1349g_sr13a_derive.log:64-65`). Measured − model = −12,337 (**D**,
`evidence/qwen9b/sr/n1349g_sr13a_derive.log:67`):

| class | model | measured | measured − model | cite |
|---|---|---|---|---|
| (the additive CMD residual) | 19,308 | 0 | −19,308 | `evidence/qwen9b/sr/n1349g_sr13a_derive.log:69` |
| CMD + ARG | 10,710,770 | 10,730,078 | **+19,308** | `evidence/qwen9b/sr/n1349g_sr13a_derive.log:70` |
| FENCE (1,370) | 8,999,456 | 8,987,848 | **−11,608** | `evidence/qwen9b/sr/n1349g_sr13a_derive.log:71` |
| LDC / MVGO / EMB | — | — | −593 / −88 / −48 | `evidence/qwen9b/sr/n1349g_sr13a_derive.log:72` and below |
| MOVX / MOVY / CSRWR / XOP / JMP / AMAXL | — | — | 0 each | same block |

* **The CMD residual lands exactly where SR11b put it.** CMD lane work is **10,650,689 cyc, R1's to the
  cycle** (`evidence/qwen9b/sr/n1349g_sr13a_derive.log:104`): the +19,308 over BN1's windows is the same
  SLD DMA stall plus KVAP term as at R1, so the additive residual nets to zero.
* **The FENCE class is the stall's absorption.** Zero-wait FENCEs: 914, each exactly 23 cyc, model exact
  (`evidence/qwen9b/sr/n1349g_sr13a_derive.log:83`). Waiting: 456, −11,608 (**−25.46 per FENCE**,
  `evidence/qwen9b/sr/n1349g_sr13a_derive.log:84`), of which **DN dn_out −11,286** over 96
  (`evidence/qwen9b/sr/n1349g_sr13a_derive.log:86`) — the 17,212-cyc stall absorbed by dn_out waits, the case
  the placement band's low end was built for (SR11b §2.3); every other class within ±397.
* **Where R2's gain sits.** Against R1 measured, FENCE lane work drops 9,980,593 → 8,987,848
  (−992,745 cyc/token); every other opcode is unchanged to the cycle
  (`evidence/qwen9b/sr/n1349g_sr13a_derive.log:107`, and lines 103-113).
