# SR12 — R2 RTL: the XWIN/RES bank fields in `seq_0` and the four `mvchan`s

Task SR12 of the sequencer RTL round (`docs/superpowers/plans/2026-09-27-seq-rtl-round.md`,
Task SR12; contract `docs/SEQ_ISA.md` v2.3 §B17.2, FINAL after SR11a's review; spec
`docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md` §1.2). RTL + unit TBs + OOC counts
+ the isa_bits B17.2 rows only: **no build, no board.** Base 2910d4d; the RTL/TB commits are
f4c1fb7 and 2327d7a (§6 item 1). Every run is on snoke through `evidence/qwen9b/sr/sr_run.sh`,
log block n1200–n1299 (used n1200–n1246); every TB builds into task-private obj_dirs
(tb/obj_dir_*_sr12*, one host).

**Acceptance, one line each.**
1. **RED → GREEN.** Unit TB on the base RTL: 0/40 (`evidence/qwen9b/sr/n1205_tb_seq_RED_base.log:632`);
   matvec TBs on the base RTL: 20/50, every one of the 30 bank runs FAILs and every non-bank run
   passes (`evidence/qwen9b/sr/n1236_tb_matvec_RED_base.log:506`). GREEN: 40/40
   (`evidence/qwen9b/sr/n1213_tb_seq_each_GREEN.log:616`), 50/50
   (`evidence/qwen9b/sr/n1237_tb_matvec_each_GREEN.log:312`); the make targets of record, 4 seeds
   each: `tb_seq_all` 66/66 SEQ PASS (`evidence/qwen9b/sr/n1230_tb_seq_all_GREEN.log:909-911`),
   `tb_matvec` (`evidence/qwen9b/sr/n1231_tb_matvec_GREEN.log:211`), `tb_matvec_ng`
   (`evidence/qwen9b/sr/n1232_tb_matvec_ng_GREEN.log:413`), `tb_matvec_chan`
   (`evidence/qwen9b/sr/n1244_tb_matvec_chan_GREEN_final.log:330`).
2. **Lint:** 0 warnings — `lint_seq_unit`, `lint_matvec`, `lint_mvshim_b`, `lint_seq_chip_9b`
   (`evidence/qwen9b/sr/n1242_lint.log:34`); every TB build is -Wall.
3. **Backward compatibility.** Every existing golden byte-identical: 280 of 280, and the 35
   caps.hex files move exactly fab1ca01 → fab1ca03 (`evidence/qwen9b/sr/n1218_golden_same.log:27-29`).
   Cycle-identical: 32 of 32 unit vectors (`evidence/qwen9b/sr/n1214_cycles_base_vs_r2.log:58`),
   44 of 44 engine/channel runs byte-identical transcripts (`evidence/qwen9b/sr/n1239_mv_cycles_base_vs_r2.log:59`).
4. **Negative control.** A mutant that ignores every bank field is caught by all 6 bank/range
   unit vectors (`evidence/qwen9b/sr/n1219_tb_seq_mutant.log:575`) and all 28 matvec bank runs
   (`evidence/qwen9b/sr/n1238_tb_matvec_mutant.log:508`); a start-row-only mutant by 5
   (`evidence/qwen9b/sr/n1221_tb_seq_mutant_rowonly.log:586`).
5. **SEQ_CAPS** = HW.seq_caps_word({"R1","R2"}) = 0xFAB1CA03 on all 66 `tb_seq_all` runs, read
   against the per-vector caps.hex the generator writes from hwmap.
6. **OOC:** no new BRAM/URAM/DSP in `seq_unit` or `matvec_chan`; LUT/FF deltas §5; `layer_chan`
   unchanged (§5).
7. **isa_bits:** B17.2 rows RED on the base RTL (`evidence/qwen9b/sr/n1202_isa_bits_shape_RED_baseRTL.log:45-47`),
   GREEN (`evidence/qwen9b/sr/n1240_isa_bits_shape_GREEN.log:41-43`); each of the six R2
   perturbations refused by its own row (`evidence/qwen9b/sr/n1228_isa_bits_r2_perturb.log`);
   the gate and its 19-of-19 negative control unmoved, VNW ceiling row untouched
   (`evidence/qwen9b/sr/n1224_isa_bits_GREEN.log:73`, `evidence/qwen9b/sr/n1225_isa_bits_negctl.log:44-47`).

## 1. The RTL, by site (line numbers at 2327d7a; re-aimed to the fix-round-1 tree where its edits moved them)

| file | change | where |
|---|---|---|
| `rtl/seq_unit.sv` | SEQ_CAPS r2 = 1 (the literal is 0xFAB1CA03) | `rtl/seq_unit.sv:338-339` |
| | R2_XWIN_WORDS 3072 / R2_RES_ROWS 4096 (twins of ref/seq_format, tied by isa_bits §7) | `rtl/seq_unit.sv:344-345` |
| | range rules as ROOM compares (no adder on the 24-bit length): MOVX len ≤ 4·(3072 − start), start ≤ 3071, target[15:12] = 0; MOVY len ≤ 4096 − start row | `rtl/seq_unit.sv:773-778` |
| | validator: MOVX refusal E_RSVD (after the ind/chan/env checks, the generator twin's order) | `rtl/seq_unit.sv:810` |
| | validator: MOVY target[15:4] no longer reserved; the range refusal E_RSVD | `rtl/seq_unit.sv:821` |
| | mv_xword / mv_row declared, reset with mv_fmask | `rtl/seq_unit.sv:892`, `rtl/seq_unit.sv:977` |
| | dispatch: MOVX mv_xword from target[11:0], MOVY mv_row from target[15:4] | `rtl/seq_unit.sv:1089`, `rtl/seq_unit.sv:1105` |
| | u_mov ports | `rtl/seq_unit.sv:1521` |
| `rtl/seq_movers.sv` | header note (XPTR write stays 0, RES_PTR carries the start row, SHAPE whole) | `rtl/seq_movers.sv:36` |
| | cmd_xword / cmd_row ports | `rtl/seq_movers.sv:104-105` |
| | xword_q declared; res_row_q and xword_q latched from the command | `rtl/seq_movers.sv:252`, `rtl/seq_movers.sv:643-644` |
| | XWIN burst base = MVB_XWIN + 4·start word; the sim-only overflow $error includes it | `rtl/seq_movers.sv:674`, `rtl/seq_movers.sv:683` |
| `rtl/matvec_chan.sv` | header: SHAPE {spare[31], rbank[30], xbank[29], …}, readback unchanged | `rtl/matvec_chan.sv:18-31` |
| | csr_static_xbank / csr_static_rbank declared, reset with the statics, latched from wdata bits 29/30 (bit 31 dropped) | `rtl/matvec_chan.sv:231-232`, `rtl/matvec_chan.sv:324`, `rtl/matvec_chan.sv:345-346` |
| | SHAPE readback: the pre-SR12 word, [31:29] read 0 (§6 item 1) | `rtl/matvec_chan.sv:375` |
| | two engine inputs | `rtl/matvec_chan.sv:446` |
| `rtl/matvec_engine.sv` | cfg_xbank / cfg_rbank inputs | `rtl/matvec_engine.sv:155` |
| | XB_LINE 48 / RB_ROW 2048 localparams | `rtl/matvec_engine.sv:196-197` |
| | **the bank is a reset VALUE**: x_line loads XB_LINE at start and at every row end, row_in loads RB_ROW at start | `rtl/matvec_engine.sv:480-481`, `rtl/matvec_engine.sv:495` |
| | **the accumulator index moves from x_line to g_cnt** (§6 item 2) | `rtl/matvec_engine.sv:326` |
| | sim-only bank-legality $fatal twins: XBANK needs 48 + ng − 1 ≤ 95, RBANK needs 2048 + nrows ≤ 4096 | `rtl/matvec_engine.sv:729`, `rtl/matvec_engine.sv:734` |

The new registers in the mvchan are named csr_static_*, so the quasi-static false path into the
UI clocks covers them by name (`synth/constraints/fable5_cdc.xdc:14-15`); that coverage on the
routed design is SR14's. The x_mem ADDRESS is still the bare x_line flop (only its reset value
gained a 1-bit mux on bits 5:4), the RES write address is still the row tag, and no adder sits
on either — the spec §1.2 construction. No RTL interlock was added (Q8).

## 2. The tests

**Unit TB and golden generator** (`tb/tb_seq_unit.sv`, `tb/scripts/gen_seq_unit_vectors.py`).
* BUILD_CAPS is {"R1","R2"} (`tb/scripts/gen_seq_unit_vectors.py:136`): the vectors validate
  at that caps set and caps.hex is HW.seq_caps_word of it — never a re-typed literal.
* The generator's twin validator gains the B17.2 clauses in the RTL's order
  (`tb/scripts/gen_seq_unit_vectors.py:406`, `tb/scripts/gen_seq_unit_vectors.py:422`); its
  executor carries the MOVX start word and the MOVY start row (RES_PTR written with it, the
  stub's row-addressed words read from it: `tb/scripts/gen_seq_unit_vectors.py:491`,
  `tb/scripts/gen_seq_unit_vectors.py:572`); its RunningChannelError twin becomes ref/seq_model's
  running ranges (`tb/scripts/gen_seq_unit_vectors.py:509`).
* **New side file <prefix>.xwa** (`tb/scripts/gen_seq_unit_vectors.py:1037`): every MOVX's
  (chan, start word, words) and MOVY's (chan, start row, rows). The TB checks EVERY mvchan
  burst beat's window address against it (`tb/tb_seq_unit.sv:554`, hooked at
  `tb/tb_seq_unit.sv:708` and `tb/tb_seq_unit.sv:728`) and requires every window consumed at
  HALT (`tb/tb_seq_unit.sv:996`). Without it the start word would be invisible: the .wtr/.rtr
  canonicalise each beat to ONE CSR address and the stub's xsum is address-blind.
* `seq_h_bank` ×4 channel permutations (`tb/scripts/gen_seq_unit_vectors.py:838`,
  `tb/scripts/gen_seq_unit_vectors.py:1407`): a bank-0 x feeding a RBANK result; a bank-1 x
  feeding a NO-WAIT XBANK stream into RES bank 0 and, WHILE it runs, a MOVY of the other RES
  half and a MOVX into the other XWIN bank; a masked FENCE; drains of both halves (one at an
  odd row); bank 1 filled to word 3072 exactly; XBANK at ng 48 with RBANK nrows 2048; MOVYs of
  the last row and ending at 4096; start words 5 (ragged tail), 1020 (across the 4 KiB page —
  the burst splitter), 3071.
* Error vectors `mxrsvd`, `mxstart`, `mxrange`, `myrange` (`tb/scripts/gen_seq_unit_vectors.py:814-825`),
  each after legal records and, where the rule has an edge, after the LEGAL edge in the same
  stream (the TB checks the faulting PC, SR3's rule).
* The stub (`tb/seq_stub_mvchan.sv`) needs no bank state: both windows are address-carried, SHAPE
  stays opaque (isa_bits requires it); its header says so.

**Engine and channel TBs.**
* `tb/tb_matvec.sv` (`tb/tb_matvec.sv:39`): +xbank (x at word 1536 + i over a bank 0 POISONED
  with ~x, `tb/tb_matvec.sv:348`), +rbank (row tags 2048 + r), +pingpong (case i in bank i%2;
  case i+1's x written into the other bank by a loader process WHILE case i streams,
  `tb/tb_matvec.sv:259`, `tb/tb_matvec.sv:292`), +bankguard (`tb/tb_matvec.sv:434`), and the
  SR12_NO_BANK_PORTS define that builds it against the pre-SR12 engine for the RED.
* `tb/tb_matvec_chan.sv` (`tb/tb_matvec_chan.sv:149`): +xbank/+rbank through the real CSR (SHAPE
  bits 29/30 in the write, `tb/tb_matvec_chan.sv:256`), +overlap: A in bank 0 and, while A
  streams, B's x into XWIN bank 1 (STATUS sampled every 32 words — busy must be seen,
  `tb/tb_matvec_chan.sv:294`), then B on XBANK|RBANK: B's rows at 2048 AND A's rows at 0 both
  bit-exact (`tb/tb_matvec_chan.sv:345`).
* Makefile (`tb/Makefile`): MV1DIR / CHANDIR / MV_RTL / MV_DEFS (`tb/Makefile:42`) so a task
  builds its own dirs and the RED reads a git-show extract; SEQ_ERRS/SEQ_DIRECTED gain the SR12
  vectors (`tb/Makefile:933`, `tb/Makefile:948`); the bank runs follow the frozen runs in
  `tb_matvec`, `tb_matvec_ng` and `tb_matvec_chan` (`tb/Makefile:67`, `tb/Makefile:240`,
  `tb/Makefile:307`), 4 seeds each with +verilator+seed+s (§6 item 4).

## 3. RED → GREEN, lint

| step | log | result |
|---|---|---|
| base RTL extract (git show 2910d4d:rtl/…, sha256 c2b97a82… / 644f9ccb… / 00e36da1… / 9320047d…) and the mutant | `evidence/qwen9b/sr/n1235_rtl_copies_final.log` | 5 mutated lines |
| RED unit TB, base RTL, the final vector set | `evidence/qwen9b/sr/n1205_tb_seq_RED_base.log:632` | **0 PASS / 40 FAIL**: every vector reads SEQ_CAPS fab1ca01 ≠ fab1ca03; `seq_h_bank` ×4 die at the first bank-1 MOVX beat — mvchan word 0, want 1536 (`evidence/qwen9b/sr/n1205_tb_seq_RED_base.log:606`); mxrsvd runs its MOVX (a write beyond the golden, `evidence/qwen9b/sr/n1205_tb_seq_RED_base.log:338`); mxstart halts with err 0 (`evidence/qwen9b/sr/n1205_tb_seq_RED_base.log:345`); mxrange writes its legal edge at word 0 (`evidence/qwen9b/sr/n1205_tb_seq_RED_base.log:352`); myrange faults one record early, at the legal MOVY from row 4000 — the pre-round refusal (`evidence/qwen9b/sr/n1205_tb_seq_RED_base.log:359`) |
| RED matvec TBs, base RTL | `evidence/qwen9b/sr/n1236_tb_matvec_RED_base.log:506` | **20 PASS / 30 FAIL**: all 30 bank runs FAIL (wrong x, wrong row tags, the guard absent), all 20 non-bank runs pass |
| lint | `evidence/qwen9b/sr/n1242_lint.log` | 0 %Warning, rc 0 ×4 |
| GREEN unit TB, each vector | `evidence/qwen9b/sr/n1213_tb_seq_each_GREEN.log:616` | 40/40 |
| GREEN matvec TBs, each run | `evidence/qwen9b/sr/n1237_tb_matvec_each_GREEN.log:312` | 50/50; pingpong loads busy at their first and last word (`evidence/qwen9b/sr/n1237_tb_matvec_each_GREEN.log:69`); overlap busy at 5 of 28 samples (`evidence/qwen9b/sr/n1237_tb_matvec_each_GREEN.log:268`) |
| `make tb_seq_all` (SEQ_SEEDS 1 2 3 4, `evidence/qwen9b/sr/n1230_tb_seq_all_GREEN.log:8`) | `evidence/qwen9b/sr/n1230_tb_seq_all_GREEN.log:909-911` | rc 0; 66 SEQ PASS, 66 TB_SEQ_FMASK, 66 TB_SEQ_XWA, 66 SEQ_CAPS fab1ca03 == hwmap fab1ca03 |
| `make tb_matvec` | `evidence/qwen9b/sr/n1231_tb_matvec_GREEN.log:208-211` | 4 frozen + 12 bank runs; both bank guards trip |
| `make tb_matvec_ng` (V2SEEDS 1 2 3 4, `evidence/qwen9b/sr/n1232_tb_matvec_ng_GREEN.log:8`) | `evidence/qwen9b/sr/n1232_tb_matvec_ng_GREEN.log:413` | all rows incl. XBANK+RBANK over NG 1..4/36/48 |
| `make tb_matvec_chan` on 2327d7a | `evidence/qwen9b/sr/n1244_tb_matvec_chan_GREEN_final.log:330` | 4 frozen + 12 9B + 12 bank runs + the hwmap selftest |
| tb_streamer_engine and tb_mvshim_b (their instantiation / stub were edited) | `evidence/qwen9b/sr/n1243_regress_se_mvshim.log:29-32` | PASS ×4 each; sabotage still trips |

n1230–n1232 ran on f4c1fb7: the RTL they read (seq_unit, seq_movers, matvec_engine) is identical
at 2327d7a, which changed only matvec_chan's SHAPE readback; the matvec_chan target was re-run on
2327d7a (n1244).

**Negative control.** `evidence/qwen9b/sr/sr12_rtl_copies.sh` copies the R2 RTL with the MOVX
start word and MOVY start row latched as 0 and x_line/row_in loaded as if XBANK/RBANK were 0 —
every signal still read, so the copy is -Wall clean and only the TBs can catch it. Unit TB:
34/40, the 6 failures exactly seq_h_bank ×4, mxrange, myrange (`evidence/qwen9b/sr/n1219_tb_seq_mutant.log:575`).
Matvec TBs: 22/50, every bank run caught, every non-bank run and both guard self-tests pass
(`evidence/qwen9b/sr/n1238_tb_matvec_mutant.log:508`). A start-row-only mutant: 35/40, caught
by the RES_PTR write data before the window check (`evidence/qwen9b/sr/n1221_tb_seq_mutant_rowonly.log:586`).

## 4. Backward compatibility

* **Goldens.** Base generator (2910d4d) vs SR12 generator, 4 seeds: 315 base files, 280
  byte-identical, 0 differ, and the 35 caps.hex move exactly fab1ca01 → fab1ca03 as hwmap
  derives them (`evidence/qwen9b/sr/n1218_golden_same.log:27-29`). New files: .xwa and the new
  vectors only. (n1216 is the same run with a broken caps derivation in the script, kept.)
* **Cycle identity, unit level.** SR3's `evidence/qwen9b/sr/sr3_cycles.py` over the base-RTL
  block (n1205) and the R2 block (n1213), LAT 4: 32 of 32 vectors — every existing vector and
  the SR3 error vectors — identical in records, cycles, AXI-Lite writes/reads, polls,
  fetch stalls and DDR beats (`evidence/qwen9b/sr/n1214_cycles_base_vs_r2.log:58`).
* **Cycle identity, engine and channel.** `evidence/qwen9b/sr/sr12_mv_cycles.sh`: 44 non-bank
  runs (frozen, NG sweep random / chunk=1 / nogap with the stall bounds, the 9B q shapes random
  and nogap, mixed, and the channel frozen + q runs with +shapeback) on the base-RTL and R2-RTL
  binaries of the same TB: 44 byte-identical transcripts, `thru:` cycle counts and `perf:`
  cycles included (`evidence/qwen9b/sr/n1239_mv_cycles_base_vs_r2.log:59`).

## 5. OOC counts

`evidence/qwen9b/g4/run_g4b_ooc.sh` (run with bash), fresh out dirs, 8 threads, beside SR7's two
incremental implementations (not touched). Base runs on 2910d4d before any RTL edit.

All counts from one collection log, `evidence/qwen9b/sr/n1245_ooc_r2.log` (the base summaries
were first collected before any RTL edit in `evidence/qwen9b/sr/n1200_ooc_base.log`).

| top | run (tree) | LUT | FF | RAMB36 / RAMB18 | URAM | DSP | log lines |
|---|---|---|---|---|---|---|---|
| `seq_unit` | base 2910d4d (synth/out_ooc9b_sr12_seq_base/) | 4,049 | 3,002 | 0 / 0 | 0 | 0 | `evidence/qwen9b/sr/n1245_ooc_r2.log:14-18` |
| | R2 f4c1fb7 = 2327d7a for this file set (synth/out_ooc9b_sr12_seq_r2/) | 4,100 | 3,050 | 0 / 0 | 0 | 0 | `evidence/qwen9b/sr/n1245_ooc_r2.log:28-32` |
| | **Δ R2** | **+51** | **+48** | 0 / 0 | 0 | 0 | CARRY8 233 → 237 |
| `matvec_chan` (one of four) | base 2910d4d (synth/out_ooc9b_sr12_mvchan_base/) | 14,946 | 14,109 | 4 / 0 | 0 | 2 | `evidence/qwen9b/sr/n1245_ooc_r2.log:42-46` |
| | R2 final 2327d7a (synth/out_ooc9b_sr12_mvchan_r2final/) | 14,958 | 14,123 | 4 / 0 | 0 | 2 | `evidence/qwen9b/sr/n1245_ooc_r2.log:70-74` |
| | **Δ R2** per channel (×4 = +48 LUT, +56 FF) | **+12** | **+14** | 0 / 0 | 0 | 0 | CARRY8 773 = 773 |
| | f4c1fb7, with the bank readback (superseded, kept) | 14,943 | 14,116 | 4 / 0 | 0 | 2 | `evidence/qwen9b/sr/n1245_ooc_r2.log:56-60` |
| `layer_chan` | control, f4c1fb7 (synth/out_ooc9b_sr12_layer/) | 113,216 | 61,437 | **79 / 8** | **182** | **1840** | `evidence/qwen9b/sr/n1245_ooc_r2.log:84-88` |
| | SR3's control (5c369c2) and T14A (1dd2889), same log | 113,216 | 61,437 | 79 / 8 | 182 | 1840 | `evidence/qwen9b/sr/n1245_ooc_r2.log:100-112` |

* **No new BRAM, URAM or DSP** in either changed top (spec §1.2 "no new BRAM"). The +48 FF in
  seq_unit are the three new 12-bit registers (mv_xword, mv_row, xword_q = 36) plus
  synthesis-level movement; the +51 LUT the two room compares, the reserved nibble, the reset and
  the mover's burst-base add. The mvchan's +14 FF / +12 LUT are the two csr_static bank flops,
  the reset-value muxes on x_line[5:4] and row_in[11], and the g_q source move; no attribution
  cell by cell was done. No numeric bound was set (the spec sets none).
* **`layer_chan` is exact** in every count against SR3's and T14A's runs. As SR3 recorded
  (`evidence/qwen9b/sr/SR3_R1_RTL.md` §5), the plan's quoted 77 / 1838 are the pre-T14A S5
  numbers; the standing counts are 182 / 79 / 8 / 1840, which is what the dispatch expected.
  layer_chan reads none of the four files SR12 edits, and the file 2327d7a changed after this
  run (rtl/matvec_chan.sv) is not in its list.

## 6. Judgment calls and deviations

1. **SHAPE readback.** f4c1fb7 read bits 29/30 back in place. tb_mvshim_b's T1 round-trip pins
   [31:29] reading 0 and failed on it (`evidence/qwen9b/sr/n1234_regress_se_mvshim.log`); B17.2
   says nothing about the readback, so 2327d7a returns it to the pre-SR12 word — host-visible
   register semantics unchanged, the banks proved by results — and re-ran what reads it.
2. **The accumulator index (a spec gap, settled inside the structure).** In the engine, x_line
   was also the group index that tags each beat into the accumulator banks (g_q); loading it
   with 48 made the retire walk (r_g = 0..ng−1) read empty entries — y32 = 0 on every XBANK row
   (`evidence/qwen9b/sr/n1210_tb_matvec_each_GREEN.log`). g_q now takes g_cnt, which equals
   x_line on every weight beat when XBANK = 0 (both reset at start and row end, both +1 per
   weight beat) — bank-0 cycle identity is n1239. It moves one flop's D source; no adder, and
   the x_mem address is untouched. Spec §1.2 names only the x_line / row_in sites; the ISA
   semantics are unaffected, so this is recorded, not escalated.
3. **Files beyond the dispatch list, from the plan's own list:** `tb/tb_matvec.sv`,
   `tb/tb_matvec_chan.sv`, `tb/seq_stub_mvchan.sv` (plan SR12 "TBs"), and — because the new engine
   ports would otherwise break their builds — `tb/tb_streamer_engine.sv` (ties the banks to 0)
   and `tb/mvshim_b_stubs.sv` (the stub engine gains the two unused inputs).
4. **Seeds.** Verilator ignores `--seed`; the historical tb_matvec/tb_matvec_chan runs pass it
   and differ only by vector set. The SR12 bank runs reuse vector sets, so they pass
   +verilator+seed+s (n1211 showed four identical transcripts without it); the frozen runs are
   left alone so they stay cycle-reproducible. **Correction (fix round 1):** every "4 seeds"
   claim on tb_matvec / tb_matvec_chan in earlier gate docs was four VECTOR SETS under ONE
   $urandom stream, not four random streams; NEXT_SESSION.md §9(d) carries the same note.
5. **pingpong loader.** A fork inside the run task crashed Verilator 5.020 --timing with SIGILL
   (`evidence/qwen9b/sr/n1208_dev_pingpong_crash.log`); the loader is a free-running process
   handed its job through flags.
6. **The unit TB's bank vectors check PLUMBING** (start word, start row, SHAPE pass-through, the
   running-range overlap the RTL does not refuse); bank SEMANTICS are the engine's and are proved
   by tb_matvec / tb_matvec_chan. The generator does not replicate ref/seq_model's stricter
   UnwrittenReadError; the bank vectors were written to satisfy it anyway (every MOVY reads rows
   a MVGO wrote).
7. **Bank legality stays validator-side on silicon** (addendum): seq_unit does not refuse XBANK
   with ng > 48 or RBANK with nrows > 2048; the engine's twin is the sim-only $fatal.
8. **Logs.** n1201 (a test bug, int8 overflow), n1206 (TB lint), n1207 (pingpong SIGILL), n1208
   (the crash), n1210/n1211 (the g_q bug; seeds), n1216 (script bug), n1204/n1229 (lint of an
   earlier tree), n1209/n1212/n1220 (superseded by n1236–n1238 after the readback change),
   n1222/n1223 (isa_bits' SHAPE readback parse tripped on a comment inside the concat — the
   control then refused everything vacuously; fixed, n1240/n1241) are kept as records.
9. **isa_bits scope.** Section 7 is new and runs under `--shape` (the matvec_chan/SEQ field
   mode); its six perturbations join `--shape-control`, each refused by its own row
   (`evidence/qwen9b/sr/n1228_isa_bits_r2_perturb.log:68`). The main gate and its negative
   control are untouched and unmoved: 348 × 29 (`evidence/qwen9b/sr/n1224_isa_bits_GREEN.log:65`),
   19 of 19 with the VNW ceiling row refusing vnw_n (`evidence/qwen9b/sr/n1225_isa_bits_negctl.log:44`).

## 7. Does NOT establish

UI-clock timing, the false-path coverage of csr_static_xbank/_rbank on a routed design (SR14);
chip-level cycle identity and any emitted r2 stream (SR11b/SR13); the host's R2 admission on a
device (SR13b). Citation drift from the RTL edits is not repaired here (SR3's precedent).

**SR14 checklist (the UI-clock cones this netlist touches).** x_line[5:4] (its reset/row-end
value gains the XBANK mux, `rtl/matvec_engine.sv:480`, `rtl/matvec_engine.sv:495`); row_in[11]
(the RBANK start value, `rtl/matvec_engine.sv:481`); and the **g_cnt → g_q fanout** (+7 loads,
`rtl/matvec_engine.sv:326`) on a counter that also feeds the waived xline_q CE compares
(is_scale_beat / is_last_scale / row_start_blocked). Plus the csr_static_xbank/_rbank false-path
coverage on the routed design.

**SR13a list.** Run `tb_seq_offifo` on the R2 RTL: it was NOT run here because the target is
hard-wired to obj_dir_tb_seq (`tb/Makefile` tb_seq_offifo recipe), not a task-private obj_dir.
Its seq_f_of* streams carry no MOVX/MOVY, but the target is unrun on this RTL.

## 8. Fix round 1 (the review's six minors)

| item | change | evidence |
|---|---|---|
| 1 | the stale "x_line tracks g_cnt exactly" comment replaced: x_line = g_cnt + 48·XBANK on every weight beat, g_q takes g_cnt, and sourcing g_q from x_line breaks every XBANK y32 (comment only; the file's sha256 moves 39b514c1… → 014a3e2e…, 0 non-comment lines changed) | `evidence/qwen9b/sr/n1247_lint.log:14-16`, lint 0 (`evidence/qwen9b/sr/n1247_lint.log:36`); tb_matvec GREEN (`evidence/qwen9b/sr/n1248_tb_matvec_GREEN.log:217`) |
| 2 | tb_matvec_chan: +rbank alone at q2 / q3 (ng 64 / 96, K 8192 / 12288 — rows XBANK cannot take), 4 seeds with +verilator+seed, in the make target; +dumprows prints every RES word read | `make tb_matvec_chan` GREEN (`evidence/qwen9b/sr/n1249_tb_matvec_chan_GREEN.log:411`); 8 of 8 pairs bit-exact against the golden AND word-identical to the bank-0 run of the same vectors and seed (`evidence/qwen9b/sr/n1250_rbank_q_vs_bank0.log:23`, `evidence/qwen9b/sr/sr12f1_rbank_q.sh`) |
| 3 | tb_matvec pingpong: busy at the first word was true by construction; the check now counts busy at the LAST word written | every load, whole and chunked, 4 seeds, busy at its last word (`evidence/qwen9b/sr/n1248_tb_matvec_GREEN.log:209`) |
| 4 | `docs/SEQ_ISA.md` §B17.2, one sentence: the SHAPE readback returns [31:29] as 0; the banks are not readable | `docs/SEQ_ISA.md:1519` |
| 5 | the "4 seeds" correction | §6 item 4 above; NEXT_SESSION.md §9(d), one appended line |
| 6 | the SR14 checklist and the SR13a tb_seq_offifo item | §7 above |

The fix-round runs carry a +dirty stamp of SR11a round 2's in-flight files (sw/seq_run.py,
sw/chat_seq.py, ref/seq_chat.py), none an input to a TB or to lint.
