# SR3 — R1 RTL: the FENCE channel mask and SEQ_CAPS in `seq_0`

Task SR3 of the sequencer RTL round (`docs/superpowers/plans/2026-09-27-seq-rtl-round.md`,
Task SR3; contract `docs/SEQ_ISA.md` v2.3 §B17.0/§B17.1; spec
`docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md` §1.1). RTL + unit TB +
OOC counts only: **no build, no board.** Base commit 3ae0ff9; the RTL/TB commit is
5c369c2. Every run is on snoke through `evidence/qwen9b/sr/sr_run.sh`, log block
n300–n399; the unit TB builds into its own obj_dirs (`tb/obj_dir_seq_unit_sr3*`,
created by this task, used by no other).

**Acceptance, one line each.** (1) RED: every vector fails the SEQ_CAPS read on the
base RTL and `seq_h_fmask` ×4 fault err 0x06 (n307/n308); GREEN: 58/58 with
`TB_SEQ_FMASK PASS` on seeds 1..4 (n309, n316 on the committed tree). (2) Lint: 0
warnings, `lint_seq_unit` (n302) and `lint_seq_chip_9b` (n304). (3) Every existing
golden byte-identical (n310) and every vector both RTLs finish cycle-identical (n314).
(4) `seq_unit` +15 LUT / +10 FF, no BRAM/URAM/DSP; `layer_chan` 182 / 79 / 8 / 1840 —
identical to the T14A run, NOT the plan's stale 77 / 1838 (§5). (5) SEQ_CAPS in sim
= `HW.seq_caps_word({"R1"})` = 0xFAB1CA01 on all 58 runs.

## 1. The RTL, by site (line numbers at 5c369c2)

`rtl/seq_unit.sv` (+24/−2) and `rtl/seq_movers.sv` (+13/−3): 16 functional lines
(the spec estimated ~15), the rest comments.

| site | change | where |
|---|---|---|
| header map | new `0x64 SEQ_CAPS` row (read-only, host-only, no write decode, tied to hwmap by the TB) | `rtl/seq_unit.sv:49-55` |
| the caps literal, beside IDENT | `localparam logic [31:0] SEQ_CAPS = {24'hFAB1CA, 5'd0,` r3=0, r2=0, r1=1 | `rtl/seq_unit.sv:338-339` |
| validator: FENCE split from HALT | FENCE faults E_RSVD (0x06) on flags, target[15:4], imm32, addr_lo, addr_hi; target[3:0] is free | `rtl/seq_unit.sv:834-837` |
| validator: HALT | today's all-zero condition, verbatim | `rtl/seq_unit.sv:838-841` |
| `mv_fmask` declared beside `mv_op` | `logic [3:0]  mv_fmask;` | `rtl/seq_unit.sv:891` |
| `mv_fmask` reset with `mv_op` | `mv_fmask <= '0;` | `rtl/seq_unit.sv:977` |
| FENCE dispatch | `mv_fmask <= r_tgt[3:0];` (still `mv_op <= 2'd3`, so §B16's C5 counts it unchanged) | `rtl/seq_unit.sv:1113` |
| `u_mov` port | `.cmd_fmask(mv_fmask)` | `rtl/seq_unit.sv:1520` |
| read mux | `10'h019: s_axil_rdata <= SEQ_CAPS;` — the 0xDEADC0DE default stays for every other unmapped word | `rtl/seq_unit.sv:1636` |
| movers header note under the FENCE poll path | mask semantics, one channel per cycle, no interlock | `rtl/seq_movers.sv:30-35` |
| movers port after `cmd_nowait` | `input  wire  [3:0]  cmd_fmask,` | `rtl/seq_movers.sv:103` |
| `fmask_q` declared, reset | beside `fence_chan`; reset with `chan_pend` | `rtl/seq_movers.sv:257`, `rtl/seq_movers.sv:615` |
| latched at S_IDLE | `fmask_q <= (cmd_fmask == 4'd0) ? 4'hF : cmd_fmask;` | `rtl/seq_movers.sv:642` |
| F_SCAN | `if (chan_pend[fence_chan] && fmask_q[fence_chan]) begin` — still walks 0..3 one channel per cycle, so a mask-0 FENCE takes exactly the pre-SR3 cycles; the poll-return path is untouched | `rtl/seq_movers.sv:846` |

No RTL interlock was added (Q8): a pending channel outside the mask stays pending
and nothing in `seq_0` stalls a later MOVX/MVGO/MOVY on it — the reference gate
and the pass's assert remain the only refusal (§B17.1).

## 2. The unit TB and the golden generator

**Generator** (`tb/scripts/gen_seq_unit_vectors.py`, the twin of `ref/seq_format.py` /
`ref/seq_model.py`):

* `BUILD_CAPS = frozenset({"R1"})` (`tb/scripts/gen_seq_unit_vectors.py:123`) — the
  capability set of the RTL under test; vectors are validated with it
  (`tb/scripts/gen_seq_unit_vectors.py:812`), exactly as ref/seq_format's validate_stream with caps
  admits a mask only with "R1".
* executor: FENCE clears only the pending channels in the mask, 0 = all
  (`tb/scripts/gen_seq_unit_vectors.py:312`), and records the per-FENCE poll set.
* validator mirror: B17.1's rule, `tmask = 0xFFF0 if "R1" in self.caps else 0xFFFF`
  (`tb/scripts/gen_seq_unit_vectors.py:403`); HALT keeps the all-zero rule.
* hazard twin (added): MOVX/MVGO/MOVY on a still-pending channel raises
  `SM.RunningChannelError` (`tb/scripts/gen_seq_unit_vectors.py:463`), so no vector
  can encode a stream the reference gate would refuse.
* `build_fmask` (`tb/scripts/gen_seq_unit_vectors.py:730`): no-wait MVGOs on 0, 1, 2;
  FENCE mask 0b0010 (drains 1 only); MOVY 1; FENCE 0b0101; MOVY 0, 2; a no-wait MVGO
  on 3; FENCE mask 0; MOVY 3; then a mask naming a NOT-pending channel while another
  channel is pending and unmasked (0b1000: no poll, no hang), a mask that SKIPS a
  pending channel (0b0100 drains 2, leaves 1), and the later mask-0 FENCE that must
  poll it. **Four seeds:** the same stream under a channel permutation per seed
  (`tb/scripts/gen_seq_unit_vectors.py:1159`; seed 1 = identity = the plan's
  `seq_h_fmask`, seeds 2..4 `seq_h_fmask2..4`), so every physical channel plays every
  role (single-bit drain, skipped-then-drained, not-pending-but-masked).
* error vectors, each after LEGAL records (a no-wait MVGO drained by a mask-0 FENCE),
  the `env0` pattern: `fmrsvd` FENCE target 0x0010 (`tb/scripts/gen_seq_unit_vectors.py:721`),
  `fmimm` a legal mask with imm32 = 1 (added, `tb/scripts/gen_seq_unit_vectors.py:723`),
  `haltmask` HALT target 0x0001 (`tb/scripts/gen_seq_unit_vectors.py:725`) — all err 0x06.
* side files per vector: `<prefix>.fpolls` — per FENCE record index its MAY and MUST
  channel sets (`tb/scripts/gen_seq_unit_vectors.py:850`); and the caps side file,
  `HW.seq_caps_word(BUILD_CAPS)` (`tb/scripts/gen_seq_unit_vectors.py:856`), the one
  definition in `sw/hwmap.py`, never re-typed.

**TB** (`tb/tb_seq_unit.sv`):

* every mvchan STATUS poll (0x1004..0x4004, the ones the `.rtr` excludes) is counted
  per channel, bucketed by `dut.pc` — which holds the FENCE's record index until the
  mover retires it (`tb/tb_seq_unit.sv:580`); at HALT a FENCE bucket that polled a
  channel outside its may-set, or skipped one in its must-set, is a `$fatal`; then
  it prints TB_SEQ_FMASK PASS with the fence count (`tb/tb_seq_unit.sv:897`).
* SEQ 0x64 is read right after IDENT (`tb/tb_seq_unit.sv:799`) and compared with
  `<prefix>.caps.hex`: a mismatch is printed at once and `$fatal`ed at the end
  (`tb/tb_seq_unit.sv:1041`), so a RED run still shows every other check of the vector.
* (added) a golden error vector must fault AT its record: the faulting PC is checked
  (`tb/tb_seq_unit.sv:880`), skipped only under `+experr` fault injection. This is what
  makes the "after a legal record" construction of fmrsvd/fmimm/haltmask a proof.

**Makefile** (`tb/Makefile`): `SEQ_ERRS` gains `fmrsvd fmimm haltmask`
(`tb/Makefile:865`), `SEQ_DIRECTED` gains `fmask fmask2 fmask3 fmask4`
(`tb/Makefile:876`), and (added) `SEQ_OBJ ?= obj_dir_tb_seq` (`tb/Makefile:881`)
parameterises the tb_seq_all family's obj_dir stem so this task could build its own
dirs (one host per obj_dir); the default keeps every other target unchanged.

## 3. RED → GREEN, lint

| step | log | result |
|---|---|---|
| RED on the base RTL, working tree (RTL still unedited), 29 vectors | `evidence/qwen9b/sr/n307_tb_seq_RED.log` | 0 PASS / 29 FAIL: every vector prints `SEQ_CAPS MISMATCH: SEQ 0x64 reads deadc0de, hwmap caps.hex fab1ca01` and `$fatal`s on it; `seq_h_fmask` `$fatal`s first on `err_code 6, expected 0 (STATUS 06000006)` — the pre-round validator refusing its first masked FENCE (record 7 of the stream). 28 vectors print `TB_SEQ_FMASK PASS` before the caps fatal: every other check of every existing vector passes on the base RTL |
| RED, final vector set (fmask ×4), base RTL built from `git show 3ae0ff9:rtl/…` (sha256 ad9018e9…/e303863c…) | `evidence/qwen9b/sr/n308_tb_seq_RED_base.log` | 0 PASS / 32 FAIL (`evidence/qwen9b/sr/n308_tb_seq_RED_base.log:497`); `seq_h_fmask`, `fmask2..4` each err 0x06 (`evidence/qwen9b/sr/n308_tb_seq_RED_base.log:471`); fmrsvd/fmimm/haltmask pass every check but the caps read (the base RTL faults them too, at the same record) |
| lint `seq_unit`+`seq_movers`+stubs | `evidence/qwen9b/sr/n302_lint.log` | 0 `%Warning`, rc 0 |
| lint the 9B chip TB (instantiates `seq_unit`) | `evidence/qwen9b/sr/n304_lint_chip.log` | 0 `%Warning`, rc 0 |
| GREEN `make -C tb tb_seq_all` (uncommitted tree) | `evidence/qwen9b/sr/n309_tb_seq_all_GREEN.log` | rc 0; 58 `SEQ PASS`, 58 `TB_SEQ_FMASK PASS`, 58 `SEQ_CAPS fab1ca01 == hwmap fab1ca01` |
| GREEN again on the COMMITTED tree 5c369c2 (clean stamp) | `evidence/qwen9b/sr/n316_tb_seq_all_GREEN_committed.log` | rc 0; 58 / 58 / 58 — seeds 1..4 (`seq_u_s1..4`, `repack1..4`, `fmask`/`fmask2..4`), all 12 SEQ_ERRS, 6 SEQ_MICRO, all SEQ_DIRECTED, the guard, LAT 0/8 and sideband; each fmask vector `TB_SEQ_FMASK PASS: 6 fences` (`evidence/qwen9b/sr/n316_tb_seq_all_GREEN_committed.log:347`) |

58 = tb_seq 32 + guard 2 + LAT 0/8 2 × 10 + sideband 4. The make target `-Wall`-builds
the TB itself, so TB lint is inside n309/n316.

**Negative control — the poll check has teeth.** A mutant copy of `rtl/seq_movers.sv` whose F_SCAN
ignores the mask (`fmask_q[...] | 1'b1`, built from a scratch copy, never committed):
28 PASS / 4 FAIL, exactly the four fmask vectors, each at its first masked FENCE —
`FENCE @7 polled channel 0 1 times; its may-set is 2` (`evidence/qwen9b/sr/n313_tb_seq_mutant_nomask.log:414`,
summary `evidence/qwen9b/sr/n313_tb_seq_mutant_nomask.log:437`). The `.wtr`/`.rtr`
compare passed every mutant vector up to that point — the mask is invisible to it,
which is why the poll accounting exists.

## 4. Backward compatibility (acceptance 3)

* **Goldens byte-identical.** The base generator (`git show 3ae0ff9:…`) and the SR3
  generator, 4 seeds each: 196 base files, 196 byte-identical, 0 differ
  (`evidence/qwen9b/sr/n310_golden_same.log:16`) — every existing `.wtr`, `.rtr`,
  `.sb.*`, `.exp`, `.ddr.hex`, `.dis`. New files are only `.fpolls`, `.caps.hex` and
  the new vectors.
* **Cycle-identical.** For every vector both RTLs run to HALT (28: all existing ones plus
  fmrsvd/fmimm/haltmask), the base-RTL block (n308) against the R1 block (n309), LAT 4,
  with byte-identical stream images: cycles START→HALT, AXI-Lite writes, reads, STATUS
  polls, fetch-empty stalls and DDR beats all equal — `SR3 CYCLES: 28 vectors compared,
  28 identical, 0 differ` (`evidence/qwen9b/sr/n314_cycles_base_vs_r1.log:44`).
  Unit level only; chip-level cycle identity is SR5a's.

## 5. OOC counts (acceptance 4)

`evidence/qwen9b/g4/run_g4b_ooc.sh`, fresh out dirs, 8 threads, alongside SR1's
running build_043 job (which was not touched). The base run is on the clean base
tree before any RTL edit; the R1 and layer runs are on the committed tree 5c369c2.

| top | run | LUT | FF | RAMB36 / RAMB18 | URAM | DSP | log |
|---|---|---|---|---|---|---|---|
| `seq_unit` | base 3ae0ff9 (`synth/out_ooc9b_sr3_seq_base/`) | 4,034 | 2,992 | 0 / 0 | 0 | 0 | `evidence/qwen9b/sr/n300_ooc_seq_base.log` |
| `seq_unit` | R1 5c369c2 (`synth/out_ooc9b_sr3_seq_r1/`) | 4,049 | 3,002 | 0 / 0 | 0 | 0 | `evidence/qwen9b/sr/n305_ooc_seq_r1.log` |
| | **Δ R1** | **+15** | **+10** | 0 / 0 | 0 | 0 | |
| | BM1's seq_0 delta, for scale (placed, device level) | +187 | +415 | 0 | 0 | 0 | `evidence/qwen9b/bm/BM1_T3_BUILD.md:160` |
| `layer_chan` | control, 5c369c2 (`synth/out_ooc9b_sr3_layer/`) | 113,216 | 61,437 | **79 / 8** | 182 | **1840** | `evidence/qwen9b/sr/n306_ooc_layer.log:18-22` |
| | the plan's reference, S5 (`evidence/qwen9b/s5/S5_STRUCT.md:519-521`) | | | 77 / 8 | 182 | 1838 | |
| | T14A at 1dd2889, the shipped layer netlist (`evidence/qwen9b/g5/G5C_RTL.md:775-777`) | 113,216 | 61,437 | 79 / 8 | 182 | 1840 | `evidence/qwen9b/g5/088_t14a_ooc_layer.log:16570-16574` |

**`layer_chan` does NOT match the plan's literal 77 / 1838 — and that is the plan's
reference, not this task.** SR3 changes no file `layer_chan` reads (the diff
3ae0ff9..5c369c2 in `rtl/` is `rtl/seq_unit.sv` and `rtl/seq_movers.sv` only). The S5
numbers the plan quotes predate T14A: G5C recorded the move to RAMB36 79 (+2, all
of it the scratchpad cascade cap) and DSP 1840 on 2026-09-07 (`evidence/qwen9b/g5/G5C_RTL.md:775-777`),
and no later task re-baselined the plan's quote. This run
reproduces the T14A run in EVERY count — URAM 182, RAMB36 79, RAMB18 8, DSP 1840,
LUT 113,216, FF 61,437, CARRY8 7,839 (`evidence/qwen9b/sr/n306_ooc_layer.log:37-44`
prints the two side by side) — so the control holds: the layer netlist is
unchanged. The plan's standing-ladder numbers (and any later task quoting them)
should read 182 / 79 / 8 / 1840; this doc does not edit the plan.

`seq_unit` adds no BRAM, URAM or DSP. The +10 FF is consistent with the two new
4-bit mask registers (`mv_fmask`, `fmask_q`) plus synthesis-level noise, the +15
LUT with the split validator arm, the 0 → F latch, the F_SCAN AND and the read-mux
arm (not attributed cell by cell). No numeric bound was set (spec
states none); it is ~8 % of BM1's LUT delta and ~2 % of its FF delta.

## 6. Deviations from the plan text, each a routine call

1. `sh run_g4b_ooc.sh` fails on snoke (`/bin/sh` is dash; the script uses
   `set -o pipefail`): every OOC was launched with `bash`.
2. Logs: n301 is a first RED attempt that stopped on a TB width lint (`exists()` in a
   conditional); the RED of record is n307/n308. n303 is a GREEN before the fmask
   vector became four seeds; n309/n316 supersede it. n311 stopped on a duplicate
   LAT-4 block (tb_seq_guard re-runs `seq_h_embrow`); n314 is the rerun with the
   first-block rule. n312 is the mutant control failing lint (unused `fmask_q`); n313
   is the control. All kept as records.
3. Added beyond the plan's list: the `fmimm` error vector; fmask ×4 channel
   permutations; the faulting-PC check on golden error vectors; the
   RunningChannelError twin in the generator; the per-vector `.caps.hex` (one per
   vector rather than one per directory, so every vector — including the offifo and
   BLAT targets that reuse the binary — carries its expected word); `SEQ_OBJ`.
4. Commits are split: the RTL/TB/test evidence first (5c369c2, the green gate), then
   this doc with the OOC logs, so the R1 OOC ran on a committed tree.

## 7. Citation drift — NOT repaired here (pending)

`evidence/qwen9b/o3/o3_cite_drift.py --base 3ae0ff9 --edited <the 5 files> --plan`
(`evidence/qwen9b/sr/n315_cite_drift_plan.log`): the edits move lines that **45
documents cite 328 times** (REPAIR 319, COLLATERAL 9 — the tool calls a `--fix`
UNSAFE). Among them the contract itself: `docs/SEQ_ISA.md` (10, incl. §B17.1's
CHANNEL BINDING cites into `rtl/seq_movers.sv`), the round plan (22 + 2), the spec
(32 + 1), `NEXT_SESSION.md` (5), `evidence/qwen9b/sr/SR2_ISA.md` (1), and 40 older gate
docs and sources, several owned by other tasks of this round. Rewriting them is outside
SR3's file list and would collide with concurrent tasks, so no `--fix` was run; this
doc cites only 5c369c2 coordinates. A dedicated drift pass (plan → hand-check the 9
collateral tokens → `--fix --exclude evidence/qwen9b/sr/SR3_R1_RTL.md` → `--verify`)
is the controller's call.

## 8. Does NOT establish

Chip-level cycle identity (SR5a); timing (SR7); any emitted R1 stream (SR4); the
host's device-keyed admission (SR6).
