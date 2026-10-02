# SR — the sequencer RTL round (R1 fence mask, R2 XWIN/RES banks, R3 MOVX broadcast): design spec

**Status: DRAFT for the user's review (2026-09-27). Nothing here has been
built, simulated or run on the board.** This file specifies the three
sequencer RTL changes OV1 named, the clocks they live on, what a "small
clock hit" costs and buys, the build and verification ladder, and the
options. It changes no RTL, TB, tool or constraint; the implementation is a
later task that starts only after the user rules on §7.

**Fix round 1 (2026-09-27)** — the review's I1/I2 and minors a–i are applied
in place; the IP facts of §2.1 now come from a read-only Vivado query
(`evidence/qwen9b/ov/n131_sr0_ip_query.log`, `evidence/qwen9b/ov/n132_sr0_ip_defs.log`).

Written at HEAD `78d0eec` on `main` (the controller's evidence-only commit
`a214e54` landed while this was being written; it touches no source this
spec cites). Every statement about existing RTL, CSRs, scripts and tools is
cited `path:line`; every number is transcribed from a committed log or gate
document (**S**) or printed by this task's one numeric run (**E**,
`evidence/qwen9b/ov/n120_sr0_clock_sens.log`, run on snoke through
`evidence/qwen9b/ov/ov_run.sh`, tree stamp `ad7b62b` clean, rc 0). No number
in this file was worked out by hand, and nothing numeric ran on
darthplagueis.

---

## 0. Reading rule, and the verdict first

**Reading rule.** The campaign's: **S** = stated by a cited source, **E** =
printed by a committed run, **D** = derived with the arithmetic shown.
**Every tok/s figure in this file is MODEL** — OV1's list schedule over the
chip-TB's measured record windows (`evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md`
§0, §4), board-scaled by OV1's uniform factor 137.121/131.138 unless it
says "split". None is a board measurement. "The census" means
`evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md`; "G5D" means
`evidence/qwen9b/g5/G5D_TIMING.md`; "T3" means
`evidence/qwen9b/bm/BM1_T3_BUILD.md`.

**The verdict, in six lines.**

1. **R1 (FENCE channel mask) is small, lives entirely in `seq_0` on aclk,
   and is worth 8.811 against S1's 8.356 tok/s (form B; A: 8.621 against
   8.109).** It stays ahead of S1 at full clock until aclk is cut by
   **9.57 %** (B) / **10.89 %** (A) (**E**,
   `evidence/qwen9b/ov/n120_sr0_clock_sens.log:35-36`,
   `evidence/qwen9b/ov/n120_sr0_clock_sens.log:105`,
   `evidence/qwen9b/ov/n120_sr0_clock_sens.log:109`).
2. **R1+R2 is 9.144 (B) / 8.837 (A)**, break-even at an aclk cut of
   15.80 % / 14.99 % (**E**, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:37`,
   `evidence/qwen9b/ov/n120_sr0_clock_sens.log:106`,
   `evidence/qwen9b/ov/n120_sr0_clock_sens.log:110`) — **but R2's timing risk
   is on the MIG UI clocks, not on aclk, and the only way to slow those is to
   slow the DDR4 itself.** The MIG IP declares its memory period as a free
   integer (10..5000 ps, `evidence/qwen9b/ov/n132_sr0_ip_defs.log:8`), so
   intermediate periods may exist — whether a given one validates with this
   part and 300 MHz refclk, and whether the DIMMs calibrate there, is NOT
   established (§6 item 7) — **settled 2026-09-29 (SR9 records SR10): with the 3332 ps refclk the MIG accepts exactly three periods in 833..940 ps — 833 / 877 / 937 — and 1071 is also accepted; the rest of 941–1600 was not swept beyond 1600 (refused), and the ratio enumeration predicts six more legal periods between 940 and 1071 (`evidence/qwen9b/sr/SR10_MIG_PERIOD.md:172-175`, `evidence/qwen9b/sr/SR10_MIG_PERIOD.md:321`; corrected in SR9 fix round 1); DDR4-2133's nominal 938 ps is REFUSED (its legal neighbour is 937 ps, an 11.11 % cut), and the only admissible cut ≤ 5 % is 877 ps, exactly 5.000 % (`evidence/qwen9b/sr/SR10_MIG_PERIOD.md` §0, §2); calibration there is still unproven**. On the model, R1+R2 stays above R1-at-full-clock
   (8.811) at a 5 % UI cut (8.906) but not at 10 % (8.656); at DDR4-2133
   (−11.12 %) it is 8.598 (**E**,
   `evidence/qwen9b/ov/n120_sr0_clock_sens.log:72-73`,
   `evidence/qwen9b/ov/n120_sr0_clock_sens.log:140`). So R2 is worth taking
   only if the UI clocks close at or very near 300 MHz.
3. **R1+R2+R3 is 9.920 (B) / 9.559 (A)** in OV1's optimistic form (zero-cost
   sibling MOVX), 9.727 / 9.377 if the broadcast is a staging buffer
   (**E**, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:38-39`,
   `evidence/qwen9b/ov/n120_sr0_clock_sens.log:47-48`); break-even 28.62 % /
   27.40 % of aclk — an extrapolation past the 20 % grid (**E**, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:107`,
   `evidence/qwen9b/ov/n120_sr0_clock_sens.log:111`). It is the largest RTL
   item and the least-proven model number.
4. **A "small clock hit" is not a free knob on this design.** aclk is the
   XDMA's own 250 MHz user clock (`synth/scripts/create_project.tcl:125`),
   and the XDMA IP offers only 62.5 / 125 / 250 MHz for it
   (`evidence/qwen9b/ov/n132_sr0_ip_defs.log:22-24`); a
   slower compute clock means a **new MMCM-derived clock domain** for
   `seq_0`, `layer_0`, the mvchan CSR side and the burst fabric, with clock
   conversion in two SmartConnects — a new clock and new CDC, which the
   project rule says needs the user's explicit OK (§2.3, §7 Q1).
5. **Recommended: stage it.** Step 0 is the incremental-implementation
   probe on the netlist that already exists (build_042_bm1, which differs
   from the ship in exactly the blocks R1–R2 touch); then **R1 alone** as
   the first build; then R2 as its own build, dropped only if the UI clocks
   still miss after a spread and/or an incremental run that reuses the
   shipped mvchan placement;
   R3 decided after R1/R2 are on silicon (§5).
6. **The ALU op-stage pipeline is NOT the first RTL item** (§4.2): it is
   in `layer_0`, whose untouched placement is what the incremental flow is
   for; it has never been the design WNS on any of the nine BM1 rolls; and
   it buys no throughput (at an ASSUMED +1 cycle per ALU command it costs
   0.0148 % of the token, **D**, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:152`;
   at 3 cycles it would still be under 0.05 %).

---

## 1. R1, R2, R3 in RTL terms

### 1.0 What the RTL does today — read, not assumed

| fact | cite |
|---|---|
| the mover keeps one pending bit per channel, set by a no-wait MVGO after its doorbell drains | `rtl/seq_movers.sv:255`, `rtl/seq_movers.sv:727-731` |
| the MVGO path never looks at that bit (a second MVGO re-starts the engine) | `rtl/seq_movers.sv:727-739`, `rtl/matvec_engine.sv:478-485` |
| FENCE walks channels 0..3 in order and polls every pending one; it also waits for the AXI-Lite write pipe | `rtl/seq_movers.sv:655`, `rtl/seq_movers.sv:845-856` |
| a poll that sees done clears that channel's bit and returns to the scan | `rtl/seq_movers.sv:750-758` |
| the decoder faults (err 0x06) on ANY non-zero FENCE field | `rtl/seq_unit.sv:834-841` |
| MOVY's target[15:4] must be zero (err 0x06); target[3:0] is the channel | `rtl/seq_unit.sv:813-821` |
| MOVX/MVGO: the channel is flags[7:4], and a value of 4 or more faults (err 0x05); the RTL does not look at MOVX target at all, and uses only MVGO target[0] (no-wait) | `rtl/seq_unit.sv:727`, `rtl/seq_unit.sv:798-805`, `rtl/seq_unit.sv:1098`, `docs/SEQ_ISA.md:692-697` |
| MOVX always writes the XWIN from word 0: the burst address is the window base | `rtl/seq_movers.sv:191`, `rtl/seq_movers.sv:674` |
| the matvec_chan XWIN burst shim already takes the start word from the burst address | `rtl/matvec_chan.sv:619`, `rtl/matvec_chan.sv:599` |
| MOVY's RES start row is a 12-bit register, hard-wired to 0 at dispatch, already carried in the burst address and the RES_PTR write | `rtl/seq_movers.sv:643`, `rtl/seq_movers.sv:781`, `rtl/seq_movers.sv:916-917` |
| the RES burst read takes its start row from the address, full 12 bits | `rtl/matvec_chan.sv:557` |
| SHAPE stores only sh, nrows and ng; bits 31:29 are spare and dropped | `rtl/matvec_chan.sv:18`, `rtl/matvec_chan.sv:341-347` |
| x_mem is 32 banks x 96 lines of 32-bit LUTRAM, written whenever the x FIFO pops | `rtl/matvec_engine.sv:219-224` |
| x_line (the x_mem read address) is a bare register: 0 at reset, at start and at each row end, +1 per weight beat | `rtl/matvec_engine.sv:472`, `rtl/matvec_engine.sv:480`, `rtl/matvec_engine.sv:495`, `rtl/matvec_engine.sv:513` |
| the x_mem read into xline_q is enabled by the beat-fire CE (the FV class "xline_q0 CE") | `rtl/matvec_engine.sv:317-330` |
| row_in (the row tag that becomes the RES write address) is 0 at reset and at start | `rtl/matvec_engine.sv:473`, `rtl/matvec_engine.sv:481`, `rtl/matvec_engine.sv:496`, `rtl/matvec_engine.sv:620` |
| the RES BRAM port-A address is the engine's row tag | `rtl/matvec_chan.sv:469` |

**Nothing in the RTL enforces the pending-channel hazard.** A MOVX, MVGO
or MOVY on a channel with a pending stream is silently wrong on silicon; it
is refused only by the model gate (`ref/seq_model.py:930-932`,
`ref/seq_model.py:953-955`, `ref/seq_model.py:1024-1026`) and the reorder
pass's own assert (`ref/scripts/reorder_e4.py:225`). This spec keeps it
that way (decision D4).

### 1.1 R1 — the FENCE channel mask

**Semantic change.** FENCE target[3:0] is a channel mask. The FENCE drains
exactly the pending channels in the mask; **mask 0 means all four** — today's
meaning. F_SCAN still waits for the AXI-Lite write pipe (wr_idle,
`rtl/seq_movers.sv:845`) in every case; the burst write engine needs no
FENCE-side drain because MOVX and MOVY already wait for it (bw_idle) before
they retire (`rtl/seq_movers.sv:707`, `rtl/seq_movers.sv:836`). HALT keeps
its all-zero rule.

**RTL (`seq_0`, aclk only).**
* `rtl/seq_unit.sv` — split the FENCE/HALT validator arm
  (`rtl/seq_unit.sv:834-841`): FENCE requires flags, imm32, addr_lo,
  addr_hi and target[15:4] zero; target[3:0] is free. The dispatch
  (`rtl/seq_unit.sv:1111-1116`) latches target[3:0] into a new 4-bit
  mv_fmask beside mv_op.
* `rtl/seq_movers.sv` — a new 4-bit command input (cmd_fmask), latched at
  S_IDLE with the rest of the command (`rtl/seq_movers.sv:635-656`); a zero
  mask is latched as 4'hF. F_SCAN (`rtl/seq_movers.sv:845-856`) tests
  chan_pend AND mask instead of chan_pend. The poll-return path
  (`rtl/seq_movers.sv:750-758`) is unchanged.
* The BM1 FENCE counter (C5, mover busy with mv_op 3) needs no change: a
  masked FENCE is still mv_op 3 (`docs/SEQ_ISA.md` §B16).
* Estimated size: about 15 changed lines of RTL across the two files.

**ISA — v2.3, new section B17.1.** FENCE: target[3:0] = channel mask, 0 =
all; every other field zero (err 0x06). Validator: `ref/seq_format.py:688-689`
admits target[3:0] on FENCE only (HALT unchanged), under an explicit
isa="2.3" argument so validating for a v2.2 bitstream still refuses it.

**Emitter / pass.** `ref/scripts/reorder_e4.py` gains an RTL level
(r0 = today, r1, r2, r3). At r1 it schedules with OV1's per-channel fence
(`evidence/qwen9b/ov/ov_census.py:783-846`, the "perchan" mode already
modelled), and its fence placement (`ref/scripts/reorder_e4.py:335-392`,
today "a FENCE before each record that needs an issued, unfenced stream")
emits a FENCE whose mask is exactly the channels whose pending streams that
record needs. The replay (`ref/scripts/reorder_e4.py:394`) models a masked
drain. `evidence/qwen9b/ov/ov_census.py` needs no model change for R1.

**Reference model.** `ref/seq_model.py:1100-1102` today clears the whole
running set on FENCE; under R1 it removes only the masked channels (mask 0
= all). **The gate keeps catching hazards under the new semantics without
any further change**: a MOVX/MVGO/MOVY on a channel whose stream is pending
still raises `RunningChannelError` (`ref/seq_model.py:455`), and a masked
FENCE that forgets a channel leaves it in the running set, so the next
access to it is refused.

**Chip TB.** None beyond new streams and goldens: `tb/tb_seq_chip.sv` runs
the real `seq_unit` and `matvec_chan`. Unit TB: `tb/tb_seq_unit.sv` gets
masked-FENCE cases (mask 0 against today's golden; a mask that skips a
pending channel, whose later poll must still see it pending).

**Backward compatibility — holds.** Every existing stream carries FENCE
target 0 (the RTL faults otherwise today), which is mask 0, which is
today's drain. **Forward** (an R1 stream on build_041/042): a non-zero mask
faults err 0x06 at the first masked FENCE, **before** any wrong result is
consumed — fail-closed.

**Timing.** Cone: `seq_0`'s decode and the mover's F_SCAN, aclk. Margin: the
`seq_0` class closes at **+0.397** on the shipped roll (G5D FV line,
`evidence/qwen9b/g5/G5D_TIMING.md:1031`) — **but only +0.037 on the BM1 best
roll** (`u_seq/rec_reg` into the pre-existing `tcnt_seq` counter, T3 §12.3a,
`evidence/qwen9b/bm/BM1_T3_BUILD.md:650`). `seq_0` sits in SLR1 while the
closing clock root is in SLR0 (G5D §8.2, `evidence/qwen9b/g5/G5D_TIMING.md:994-997`),
so its skew is the price of the root. "Low risk" means small cone, not
large margin.

### 1.2 R2 — XWIN and RES bank bits (no new BRAM)

**Semantic change.** A second x vector can be loaded into a channel while its
stream runs, and a finished stream's RES can be drained while the next
stream on that channel writes the other half. Banks exist only where the
matvec fits half the buffer: K ≤ 6144 (48 of x_mem's 96 lines) and at most
2048 rows (half the 4096-row RES) (census §6.2 row R2b, R2a,
`evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md:631-632`). mlp_down (K = 12288)
stays single and spans both XWIN banks, as the census modelled
(`evidence/qwen9b/ov/ov_census.py:723-734`).

**Encoding — chosen so every new field lands where the RTL already
carries it.**

| field | where | meaning | today's RTL on a non-zero value |
|---|---|---|---|
| MOVX target[11:0] | the record | XWIN start WORD (0..3071); bank 1 is word 1536 | **ignored** (`docs/SEQ_ISA.md:692-697`) |
| MVGO SHAPE bit 29 = XBANK | imm32 | x_line starts at line 48 instead of 0 | **ignored** (not stored, `rtl/matvec_chan.sv:341-347`) |
| MVGO SHAPE bit 30 = RBANK | imm32 | result rows land at 2048 + r | **ignored** |
| MOVY target[15:4] | the record | RES start row (12 bits) | **faults err 0x06** (`rtl/seq_unit.sv:821`) |

**RTL.**
* `rtl/seq_unit.sv` — MOVY: the validator stops refusing target[15:4]
  (`rtl/seq_unit.sv:821`) and the dispatch (`rtl/seq_unit.sv:1102-1110`)
  passes it as a new 12-bit mv_row; MOVX dispatch
  (`rtl/seq_unit.sv:1082-1092`) passes target[11:0] as a new mv_xword. The
  validator adds the two range checks the ISA states (start word + words ≤
  3072; start row + rows ≤ 4096) as err 0x06.
* `rtl/seq_movers.sv` — MOVY loads res_row_q from the command instead of 0
  (`rtl/seq_movers.sv:643`); both of its uses already consume it
  (`rtl/seq_movers.sv:781`, `rtl/seq_movers.sv:916-917`). MOVX adds the start
  word to the XWIN burst base (`rtl/seq_movers.sv:674`); the burst splitter
  already never crosses 4 KiB and the shim takes the word from the address
  (`rtl/matvec_chan.sv:619`).
* `rtl/matvec_chan.sv` — the SHAPE write (`rtl/matvec_chan.sv:341-347`)
  stores bits 29 and 30 in two new registers **named csr_static_xbank and
  csr_static_rbank**, so the existing quasi-static false path into the UI
  clocks covers them by name (`synth/constraints/fable5_cdc.xdc:14-15`) —
  they are written before the doorbell and stable during the run, exactly
  like csr_static_ng. Two new engine inputs.
* `rtl/matvec_engine.sv` — **the bank is a reset VALUE of the bare
  registers, never an adder on their outputs** (census §6.2, R2b row):
  x_line's start and row-end zero-assignments (`rtl/matvec_engine.sv:480`,
  `rtl/matvec_engine.sv:495`) load 48 when XBANK is set (the reset site,
  `rtl/matvec_engine.sv:472`, needs no bank value) (only bits 5:4 of the constant change); row_in's start value
  (`rtl/matvec_engine.sv:481`) loads 2048 when RBANK is set. The row tag
  then carries the bank to the RES write address with no logic added on
  that path (`rtl/matvec_chan.sv:469`). The engine's envelope check is a
  sim-only $fatal on cfg_ng (`rtl/matvec_engine.sv:716-736`); it gains the
  bank rule (48 + ng − 1 ≤ 95 when XBANK is set), also sim-only. **Corrected 2026-09-29 (SR9): loading x_line with 48 alone is WRONG.** In `rtl/matvec_engine.sv` x_line was also the accumulator group index (g_q), so sourcing g_q from x_line left the indices ≥ 48 unretired (y32 = 0 on every XBANK row); as built, x_line = g_cnt + 48·XBANK on weight beats and g_q takes g_cnt (`evidence/qwen9b/sr/SR12_R2_RTL.md` §6 item 2).
* Estimated size: about 40 changed RTL lines over four files.

**Which cone R2 lengthens — concretely.** It is **not** the xline_q CE cone
(beat fire → 1,024 CE pins, `rtl/matvec_engine.sv:317-330`; FV class
+0.138, `evidence/qwen9b/g5/G5D_TIMING.md:1032`): the CE term and the x_mem
address are untouched. It adds one variable input to the D-input of x_line
bits 5:4 and of row_in bit 11, from a false-pathed quasi-static flop. On
logic depth that is near zero. **The real risk is placement, not depth —
and it is not specific to R2.** The four UI clocks close at only
+0.003 … +0.031 on the ship (`evidence/qwen9b/g5/G5D_TIMING.md:1010-1013`),
and the **shipped netlist's own base roll**, with the mvchan RTL unchanged,
missed all four (ch0 −0.524, `evidence/qwen9b/g5/G5D_TIMING.md:322-325`);
BM1's rolls missed UI on several of nine too (T3 §8.2a, §10.3:
`evidence/qwen9b/bm/BM1_T3_BUILD.md:334-337`,
`evidence/qwen9b/bm/BM1_T3_BUILD.md:519-521`). UI misses are placement
luck on every build of this design. What protects any round netlist — R1
only included — is an incremental run that reuses the shipped mvchan
placement (§4.3), or a spread.

**ISA — v2.3, B17.2.** The four fields above, the two range rules, and the
rule that a bank is legal only where the matvec fits it (K ≤ 6144 for XBANK,
nrows ≤ 2048 for RBANK) — the validator refuses otherwise.

**Emitter / pass.** At r2, `ref/scripts/reorder_e4.py` schedules with the
census's depth-2 buffers (`evidence/qwen9b/ov/ov_census.py:633-781`, the
xdepth/rdepth = 2 path) and **emits the bank the model assigned**: the
per-channel alternation the model already computes (its xsel/rsel,
`evidence/qwen9b/ov/ov_census.py:718-756`) becomes MOVX target (0 or 1536),
SHAPE bits 29/30, and MOVY target[15:4] (0 or 2048). The model's node needs
its bank recorded per MOVY too (today only MOVX/MVGO carry it,
`evidence/qwen9b/ov/ov_census.py:727`, `evidence/qwen9b/ov/ov_census.py:755-756`).
Elision stays keyed by channel and source (`evidence/qwen9b/ov/ov_census.py:666-674`)
**plus bank**: an elided MOVX's MVGO must name the bank the surviving copy
is in.

**Reference model — the gate under R2.** `ref/seq_model.py` stops keeping
one x vector and one RES per channel (`ref/seq_model.py:923-947`,
`ref/seq_model.py:1003`) and keeps the storage as the RTL does: a 12,288-byte
x_mem and a 4,096-row RES per channel. MOVX writes at its start word; MVGO
reads x from line 48·XBANK for K/128 lines and writes rows at 2048·RBANK;
MOVY reads from its start row. **The running set becomes running ranges**:
per channel, the pending stream's x-line range and RES-row range. MVGO on a
channel with any pending stream is still refused (one engine); a MOVX is
refused only if its XWIN word range overlaps the pending stream's x range;
a MOVY only if its row range overlaps the pending stream's RES range. The
refusal stays an explicit raise of `RunningChannelError` (survives
python -O, SV1 fix round 1, `evidence/qwen9b/ov/SV1_S1_VERIFY.md:289-293`).
The SHAPE-spare assert (`ref/seq_model.py:985-986`) admits bits 29/30 at
isa 2.3. With every bank bit and start word zero, this model is exactly
today's.

**Chip TB.** None beyond new streams, goldens and the timeline's class
decode (unchanged: MVGO/MOVX/MOVY keep their mv_op). Unit TBs:
`tb/tb_matvec.sv` and `tb/tb_matvec_chan.sv` gain bank-1 cases (x at line
48, rows at 2048, and a MOVX into bank 1 while a bank-0 stream runs, with
bit-exact results); `tb/seq_stub_mvchan.sv` models the RES start row it
already partly models (its header, `tb/seq_stub_mvchan.sv:30-40`).

**Backward compatibility — holds.** Every shipped stream has MOVX target 0,
SHAPE bits 29/30 zero (the model asserts it today, `ref/seq_model.py:985-986`)
and MOVY target[15:4] zero (the RTL faults otherwise). That is word 0,
line 0, row 0: today's behaviour exactly.
**Forward — NOT fail-closed.** An R2 stream on build_041/042 faults only at
its first bank-1 MOVY; a bank-1 MOVX and an XBANK MVGO are silently
ignored, so a MVGO whose RES goes to bank 0 would compute on the wrong x
without faulting. Hence the host-side rule of D5: SEQ_CAPS plus VERSION.

### 1.3 R3 — MOVX broadcast

**Semantic change.** One MOVX reads the scratch source once and writes the
same x into the XWIN of all four channels (the census's "one scratch read,
four XWIN writes", `evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md:633`).

**Encoding.** MOVX channel field flags[7:4] = 4'hF means "all four". Today
any value of 4 or more faults err 0x05 (`rtl/seq_unit.sv:798-800`), so a
broadcast MOVX on build_041/042 **fails closed**. Values 4..14 stay
reserved (fault).

**RTL — three implementations (decision D3).**
* **(a) Direct x-push bus (recommended if R3 is taken).** `seq_movers`
  drives one new aclk-only point-to-point push port per channel — 32-bit
  word, 12-bit word index, valid — and each `matvec_chan` takes it as a
  third source on its XWIN FIFO mux beside the AXI-Lite and burst legs
  (`rtl/matvec_chan.sv:257-263`), AXI-Lite still winning. A broadcast word
  is pushed only when all four FIFOs have room (lockstep). Cost: about 45
  new BD nets per channel in `synth/scripts/create_project.tcl` (the same
  kind of wiring as the BM1 mv_busy_bm nets, `synth/scripts/create_project.tcl:352-362`),
  one of which crosses into SLR0 to `mvchan_0` (G5D §8.3,
  `evidence/qwen9b/g5/G5D_TIMING.md:1062-1064`); registered at both ends.
  It prices as OV1's R3 (siblings free).
* **(b) Staging buffer in `seq_movers`.** 3,072 words x 32 b = **three
  BRAM36** (census, `evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md:633`); the
  first channel's write fills it, the other three replay it through the
  existing burst fabric. Each sibling still pays its write side — modelled
  here at a quarter of a MOVX window (MOVX reads one int8 per scratch beat
  and writes one word per four, `rtl/seq_movers.sv:547`) — which is the
  "(buf)" row of §3. No BD change.
* **(c) A custom four-way write splitter in place of `burst_smc`.** Not
  recommended: it replaces a vendor block on every mover path.

Estimated size: (a) about 150 RTL lines over `rtl/seq_movers.sv`,
`rtl/seq_unit.sv`, `rtl/matvec_chan.sv` and both _ipi.v wrappers, plus
about 15 lines of `synth/scripts/create_project.tcl`; (b) about 120 lines in
`rtl/seq_movers.sv` alone.

**ISA — v2.3, B17.3.** MOVX flags[7:4] = 0xF broadcast; target[11:0] start
word applies to all four; the validator requires every destination
channel's XWIN bank free.

**Emitter / pass.** `evidence/qwen9b/ov/ov_census.py` models R3 by zeroing
the siblings' windows (`evidence/qwen9b/ov/ov_census.py:1374-1388`), which
is not an emittable stream: the pass needs a real broadcast node that
writes four XWINs, waits on the latest of the four channels' readers (the
census's own caveat, `evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md:771-773`),
and forces the four channels onto the same bank.

**Reference model.** `_movx` (`ref/seq_model.py:923-947`) writes all four
channels' x_mem for chan 0xF and applies the range refusal of §1.2 on each.

**Chip TB.** For (a) the chip TB's top must wire the new push ports as
create_project.tcl does — a TB change, the first of the round; for (b)
none. Unit TB: `tb/tb_burst_fabric.sv` (b) or a new push-bus case in
`tb/tb_matvec_chan.sv` (a).

**Backward compatibility — holds** (no shipped stream uses chan ≥ 4).

**Timing.** (a) new datapath out of `seq_0` into all four channels,
including an SLR crossing; (b) three BRAM36 beside `seq_0`, whose margin on
the BM1 netlist was +0.037 (§1.1).

### 1.4 The ISA version and the host-side guard (decision D5)

`docs/SEQ_ISA.md` becomes **v2.3** with a section B17 (B17.1 R1, B17.2 R2,
B17.3 R3), in the file's addendum style (`docs/SEQ_ISA.md:11-31`). Because
R2 is not fail-closed on an old bitstream (§1.2), the round adds a
**read-only SEQ_CAPS word at SEQ 0x64** — today an unmapped read that
returns 0xDEADC0DE (`rtl/seq_unit.sv:1641`) — reading a fixed magic in the
high bits and one bit per built feature (R1, R2, R3). Host tools refuse to
load a stream whose manifest says isa 2.3 unless SEQ_CAPS has the bits it
needs, **and** the new bitstream's VERSION must be admitted in
`sw/seq_run.py`'s table (`sw/seq_run.py:164-189`), exactly as BM1's was.

---

## 2. The clocks, and where the failures are

### 2.1 Every clock in the design

| clock (Vivado name) | frequency | source | what it clocks | can it be reduced, how, at what granularity |
|---|---|---|---|---|
| `pcie_refclk` | 100 MHz | board, `synth/constraints/fable5_pcie_clk.xdc:5` (the only create_clock in the tree) | the XDMA GT reference | no — PCIe spec |
| `xdma_0_axi_aclk` | **250 MHz** (**S**, `evidence/qwen9b/bm/n45_T3_spread2_score_ENDl.log:37`) | the XDMA's PHY user clock, a BUFG_GT in the GT column of SLR1 (G5D §8.2, `evidence/qwen9b/g5/G5D_TIMING.md:982-988`); axisten_freq 250, 256-bit (`synth/scripts/create_project.tcl:124-125`) | **`seq_0`, `layer_0`, `csr_0`, the CSR/XWIN side of `mvchan_0..3`, `axil_smc`, `burst_smc`, the aclk side of `axi_smc`** (`synth/scripts/create_project.tcl:226`, `synth/scripts/create_project.tcl:246`, `synth/scripts/create_project.tcl:259`, `synth/scripts/create_project.tcl:275`, `synth/scripts/create_project.tcl:281`, `synth/scripts/create_project.tcl:333`, `synth/scripts/create_project.tcl:375`) | **not as an IP parameter at 5–20 % granularity**: the XDMA IP's axisten_freq choices are 62.5 / 125 / 250 MHz and axi_data_width 64/128/256/512 bits (`evidence/qwen9b/ov/n132_sr0_ip_defs.log:22-24`, `evidence/qwen9b/ov/n132_sr0_ip_defs.log:28-32`; current 250 / 256_bit, `evidence/qwen9b/ov/n131_sr0_ip_query.log:162-163`) — the smallest IP step is a halving, and whether 125 MHz is legal at Gen3 x8 / 256 bits was not queried. The only fine-grained route is a NEW clock (§2.3) |
| `pipe_clk` | 250 MHz (`evidence/qwen9b/bm/n45_T3_spread2_score_ENDl.log:36`) | XDMA GT | PCIe PIPE logic | no |
| `c0_sys_clk_p` of each MIG (the four DIMM refclks) | 300 MHz, period 3.332 ns, one per DIMM | board oscillators (`synth/constraints/BCU1525_DIMM0.xdc:148-150`), constrained by the MIG IP's own generated XDC (`synth/out_build_041/proj/stage1.gen/sources_1/bd/bd/ip/bd_ddr4_0_0/par/bd_ddr4_0_0.xdc:7`, a gitignored build artifact) | each MIG's MMCM input; InputClockPeriod 3332 (`evidence/qwen9b/ov/n131_sr0_ip_query.log:135`) | no — board parts |
| `mmcm_clkout0`, `_1`, `_2`, `_3` | **300.12 MHz**, period 3.332 ns, one per DIMM (`evidence/qwen9b/bm/n45_T3_spread2_score_ENDl.log:32-35`) | each MIG's internal MMCM from its 300 MHz DIMM refclk (`synth/scripts/create_project.tcl:168-170`, `synth/scripts/create_project.tcl:214-216`, `synth/constraints/BCU1525_DIMM0.xdc:148-150`); UI = DDR4 data rate / 8 (DDR4_TimePeriod 833 ps = DDR4-2400) | the DDR4 controllers, `smc_ch0..3`, the MIG side of `axi_smc`, and **each mvchan's streamer + engine + RES write port** (`synth/scripts/create_project.tcl:229-244`; `rtl/matvec_chan.sv:3-5`) | **only by slowing the DDR4**: DDR4_TimePeriod (833 ps today, PhyClockRatio 4:1, `evidence/qwen9b/ov/n131_sr0_ip_query.log:134`, `evidence/qwen9b/ov/n131_sr0_ip_query.log:152`) is declared by the IP as a free integer 10..5000 ps (`evidence/qwen9b/ov/n132_sr0_ip_defs.log:8`), not a list of grades; which periods validate for this part and refclk, and calibrate on these DIMMs, is NOT established (**validation settled by SR10, pointer added by SR17 2026-09-29:** with the 3332 ps refclk exactly 833 / 877 / 937 are accepted in 833..940 and 1071 also, 877 = the only ≤ 5 % cut, `evidence/qwen9b/sr/SR10_MIG_PERIOD.md` §0, §2; calibration there is still NOT established, §3.2 below). The speed grades are the known-good points (2133 → UI 266.6 MHz, 1866 → 233.3 MHz, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:140-141`); any cut costs weight bandwidth by the same fraction. A separate engine clock would be new CDC on the 512-bit weight path |
| GT/QPLL tree, `pll_clk*`, `dbg_hub` BSCAN | IP-internal | vendor | vendor | no (G5D §10, `evidence/qwen9b/g5/G5D_TIMING.md:1271-1276`) |

**Which clock owns which cost.** The layer lane (`busy_cmp`), MOVX, MOVY,
MVGO issue, CSRWR, LDC/EMB issue and every FENCE poll tail are aclk cycles —
the chip-TB windows OV1 schedules and every `ref/seq_cost.py` constant
("cycles of the 250 MHz aclk", its docstring) including the E1 per-key
ALU/VN costs (`evidence/qwen9b/sd/014_e1_analysis.log:13-41`, busy_cmp
cycles). **The weight streams are not**: they are MIG-UI/DDR time, and on
the board they alone carry the 4.56 % board-vs-TB gap (engine busy
board/TB 1.0622, layer lane 0.9995; `evidence/qwen9b/bm/BM1_BOARD_IDLE.md`
§1 reading 2, `evidence/qwen9b/bm/n84_T4fix1_board_table.log:14`).

### 2.2 The failing-path families, on the clocks and on R1–R3's cones

| family (T3 §12.3, G5D §8.3) | clock | block / SLR | touched by R1 | R2 | R3 |
|---|---|---|---|---|---|
| `u_attn` output gather (BM1 best roll's WNS, −0.124) | aclk | `layer_0`, SLR0 | no | no | no |
| DN URAM → `u_dn` lane DSP | aclk | `layer_0` | no | no | no |
| KV URAM cascade address | aclk | `layer_0` | no | no | no |
| `u_alu` op_q → ps_rnd (aclk worst on 2 rolls, never design WNS) | aclk | `layer_0` | no | no | no |
| `u_dma` fmem LUTRAM (base roll) | aclk | `layer_0` | no | no | no |
| mvchan streamer / engine: xline_q0 CE, scales_q CE, f_rd | MIG UI | `mvchan_0` SLR0, `mvchan_1..3` SLR1 | no | **yes (placement)** | (a): the XWIN push leg, aclk side |
| `seq_0` (+0.397 ship, +0.037 BM1) | aclk | `seq_0`, SLR1 | **yes** | yes (decode, mover) | **yes** |

Sources: `evidence/qwen9b/bm/BM1_T3_BUILD.md:607-622`,
`evidence/qwen9b/bm/BM1_T3_BUILD.md:650`,
`evidence/qwen9b/g5/G5D_TIMING.md:1041-1050`,
`evidence/qwen9b/g5/G5D_TIMING.md:1062-1066`.

**Reading.** None of R1–R3 touches the `layer_0` families that own the aclk
WNS on every BM1 roll. So an aclk clock cut would be paying for **placement
luck in `layer_0`**, not for the R-changes; and the one family R2 does
touch is on a clock whose cut costs bandwidth one-for-one. **What an aclk
cut would have had to be**, for the BM1 rolls' own aclk worst paths: 3.01 %
for the best roll's −0.124, 8.47–8.76 % for the `u_alu` rolls, 11.25 % for
the worst `u_dn` roll (**E**, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:144-147`).
For the UI side: 0.30 % for the best roll's −0.010, 10.91–14.26 % for the
bad `mvchan_3` rolls (**E**, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:148-150`)
— the MIG declares a free period (§2.1), so a sub-grade UI cut may be
possible, but only the grades (first: 11.12 %) are known-good points.

### 2.3 How a compute-clock cut would be built (decision D7)

**There is no single knob.** The workable route is an MMCM (clocking
wizard) fed from the XDMA's axi_aclk (or a DIMM refclk), producing the
compute clock for `seq_0`, `layer_0`, `mvchan_*/aclk` and `burst_smc`, with
`axil_smc` and `axi_smc` doing clock conversion from the XDMA's master
ports. MMCM output granularity is fine (fractional multiply and divide, well
under 1 %; from memory of UG572, unverified). What it touches:
* **a new clock domain and new CDC** (SmartConnect converters, plus
  `csr_0`'s and the host path's crossing) — **the project rule forbids that
  without the user's explicit OK** (the FPGA-level CLAUDE.md, "always use a single clock domain unless
  explicitly told otherwise");
* `synth/scripts/create_project.tcl`'s hard assertions that the state DMA
  runs at 250 MHz in the XDMA's own domain (`synth/scripts/create_project.tcl:317-322`,
  `synth/scripts/create_project.tcl:576-583`), which exist precisely to keep
  SmartConnect from inferring a converter on that path;
* the CDC false paths written against the name "axi_aclk"
  (`synth/constraints/fable5_cdc.xdc:17-18`);
* the clock-root constraint, which names the XDMA user-clock net
  (`synth/constraints/fable5_clockroot_9b.xdc`) — the compute clock would
  need its own root and its own SLR check (G5D §11,
  `evidence/qwen9b/g5/G5D_TIMING.md:1352-1365`);
* it defeats the incremental flow of §4.3: a new clock tree is a new
  netlist and a new placement problem.

**Sign-off at a reduced clock** is the same gate at the new period: WNS ≥ 0,
WHS ≥ 0, zero failing endpoints on every clock, no waiver (G5D §10,
`evidence/qwen9b/g5/G5D_TIMING.md:1255-1269`), the clock-root check on the
routed checkpoint, then the RD9 board ladder, **plus** a board step-time
measurement at the new clock, because §3's figures are a model.

**An XDC-only "cut" is not a cut.** Loosening a create_clock the tools
derive from the IP would make timing pass on paper at a frequency the
silicon does not run.

---

## 3. The "small clock hit", quantified (MODEL)

**Method** (the script is `evidence/qwen9b/ov/sr0_clock_sens.py`, committed
before its run). OV1's own
functions, imported unchanged, re-run on the same stream and the same
BN1 windows, with the windows scaled by clock: **scenario K** cuts aclk by
r (every lane window and poll tail x 1/(1−r), streams unchanged);
**scenario U** cuts the MIG UI clock (streams x 1/(1−r), lane unchanged).
At r = 0 it reproduces OV1 to the cycle: 28,612,019 / 27,136,513 /
26,146,927 / 24,102,767 cycles for S1 / R1 / R1+R2 / R1+R2+R3 in form B
(**E**, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:16-19`), the census's
§4.2 table (`evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md:440-443`, which
cites n06; n15's result lines are identical).
LDC/EMB and the DMA holds inside CMD windows contain DDR latency but are
scaled with aclk in K — so K **overstates** the hit slightly.

### 3.1 Scenario K — aclk cut (the "compute clock"); board-scaled tok/s, form B (form A)

| option | 0 % | 5 % | 10 % | 15 % | 20 % | break-even vs S1 @ 0 % |
|---|---|---|---|---|---|---|
| shipped | 7.292 (7.292) | 7.074 | 6.847 | 6.609 | 6.361 | — |
| **S1** | **8.356** (8.109) | 8.117 (7.873) | 7.866 (7.628) | 7.603 (7.371) | 7.329 (7.102) | — |
| **R1** | **8.811** (8.621) | 8.579 (8.392) | 8.335 (8.154) | 8.078 (7.901) | 7.809 (7.633) | **9.57 %** = 226.1 MHz (A: 10.89 %) |
| **R1+R2** | **9.144** (8.837) | 8.910 (8.608) | 8.650 (8.369) | 8.400 (8.108) | 8.114 (7.840) | **15.80 %** = 210.5 MHz (A: 14.99 %) |
| **R1+R2+R3** | **9.920** (9.559) | 9.690 (9.331) | 9.447 (9.092) | 9.175 (8.828) | 8.912 (8.557) | **28.62 %** = 178.4 MHz (A: 27.40 %) |
| R1+R2+R3, staging buffer | 9.727 (9.377) | 9.497 (9.148) | 9.253 (8.909) | 8.982 (8.649) | 8.718 (8.360) | 25.83 % (A: 24.24 %) |

(**E**, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:34-39`,
`evidence/qwen9b/ov/n120_sr0_clock_sens.log:43-48`,
`evidence/qwen9b/ov/n120_sr0_clock_sens.log:105-112`.) The two R1+R2+R3
break-evens (and the staging-buffer ones) lie **beyond the 20 % grid**: the
bisection ran the model there, but no measured window was ever taken at
such a clock, so treat them as extrapolations (the review's separable fit
gives ~29.6 % for the 28.62 %).

**Reading.** Only about 55–60 % of the token is aclk-lane time, so an aclk
cut costs less than its size: a 10 % cut takes R1+R2 from 9.144 to 8.650
(−5.4 %). **At a 5 % cut every RTL option still beats S1 at full clock; at
10 %, R1 is at break-even and R1+R2 is still 3.5 % ahead.** The BM1 rolls'
aclk misses needed 3–11 % (§2.2).

### 3.2 Scenario U — MIG UI (DDR4) cut, form B

| option | 0 % | 5 % | 10 % | 15 % | 20 % | break-even | at DDR4-2133 (−11.12 %) |
|---|---|---|---|---|---|---|---|
| S1 | 8.356 | 8.168 | 7.968 | 7.755 | 7.527 | — | 7.921 |
| R1 | 8.811 | 8.591 | 8.359 | 8.114 | 7.851 | 10.05 % | 8.305 |
| R1+R2 | 9.144 | 8.906 | 8.656 | 8.393 | 8.113 | 15.68 % | **8.598** |
| R1+R2+R3 | 9.920 | 9.641 | 9.348 | 9.042 | 8.717 | 25.26 % | 9.281 |

(**E**, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:70-74`,
`evidence/qwen9b/ov/n120_sr0_clock_sens.log:121-123`,
`evidence/qwen9b/ov/n120_sr0_clock_sens.log:140`.)

**Reading.** The UI cut is the one R2 would need if its risk lands. R1+R2
stays above R1-at-full-clock (8.811) at a 5 % UI cut (8.906) and falls below
it by 10 % (8.656); at DDR4-2133 it is 8.598. The BM1 best roll's UI miss
needed only 0.30 % (`evidence/qwen9b/ov/n120_sr0_clock_sens.log:148`).
**If** the MIG validates a sub-grade period (the IP declares a free integer,
`evidence/qwen9b/ov/n132_sr0_ip_defs.log:8`) and the DIMMs calibrate there
(§6 item 7), a UI cut of up to ~5 % keeps R2 worth having (**SR10, 2026-09-29: 877 ps = 5.000 % is the only sub-grade period the MIG accepts; 938 is refused, 937 is the next, `evidence/qwen9b/sr/SR10_MIG_PERIOD.md` §0**). Otherwise R2 is
dropped — but only after a spread and/or an incremental run that reuses the
shipped mvchan placement has also missed (§1.2: UI misses are placement
luck on every build, the ship's own base roll included).

### 3.3 The board convention, checked

OV1's uniform factor reproduces the board's shipped step to 0.01 %
(137.1309 vs 137.1195 ms) and S1 form A to 0.2 % (123.3255 vs 123.5655)
(**E**, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:29-30`). The
physically motivated "split" convention (streams x 1.0622, lane x 1.0) is
**worse**: −1.65 % and −1.76 % (same lines), because it scales only
engine-busy time and the board's FENCE wait grows by more than the streams
alone explain. The split grid moves every break-even by at most 0.4 points
(**E**, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:113-120`,
`evidence/qwen9b/ov/n120_sr0_clock_sens.log:129-136`), so the verdict does
not depend on the convention; the uniform figures are quoted.

---

## 4. The build and verification ladder

### 4.1 The standing ladder, per netlist (NEXT_SESSION §9)

lint (`-Wall`, Verilator 5.020) → the unit TBs, **4 seeds** each →
the layer census **bit-exact** → the S4 replay **token-identical, no
re-emission** → **OOC counts** (`OOC9B_URAM: 182`, BRAM 79/8, DSP 1840 — the post-T14A counts, `evidence/qwen9b/g5/G5C_RTL.md:773-777`; the 77/1838 here before SR9 were S5's, pre-T14A) →
a full build with `evidence/qwen9b/g5/g5d_clockroot_check.tcl` on the
routed checkpoint **before** `synth/scripts/final_verify.tcl` → the safe
reprogram → the RD9 ladder (`NEXT_SESSION.md` §9, "The standing RTL ladder"). Round-specific rungs:

1. **Backward compatibility, measured**: the four shipped `model_9b_s1..s4`
   streams on the new RTL in the chip TB, **tokens identical and cycle
   counts identical** to S4's (196,706,821 … on s1,
   `evidence/qwen9b/ov/SV1_S1_VERIFY.md:146-148`). A mask-0 FENCE walks the
   same F_SCAN, so any cycle difference must be explained before moving on.
2. **The gate first, then the RTL** (TDD, as SV1 did): the model's new
   range refusals RED then GREEN on synthetic hazards (masked FENCE that
   skips a pending channel; bank-1 MOVX over a pending bank-1 read; MOVY
   over a pending RES range), and the four shipped streams still gate
   bit-exact with the refusals armed.
3. **The R streams**: the pass at the new level on s1..s4, the model gate
   2358/2358 (`evidence/qwen9b/ov/SV1_S1_VERIFY.md:135`), the pass's
   hazard assert and OV1's postcheck, then the chip TB on 4 seeds in
   parallel on snoke (7,742–8,255 s each in SV1,
   `evidence/qwen9b/ov/SV1_S1_VERIFY.md:67`) with the timeline on seed 1.
   **Prediction committed before the runs**: the n120 r = 0 figures.
4. The layer census is unaffected by R1–R3 (`layer_0` is untouched); it is
   run once as the control that says so.

### 4.2 The ALU op-stage pipeline — argued NOT first

The controller's timing map put `u_alu` first as "an aclk worst path on two
of the nine BM1 rolls" and "the largest compute term"
(`NEXT_SESSION.md` §8 item 3 as it stood at `78d0eec`; S1D has since
rewritten §8, whose item 3 now defers the round's decisions to this spec).
Against that, from the sources:
* its path is op_q → ps_rnd (`evidence/qwen9b/bm/BM1_T3_BUILD.md:519`),
  the per-command round-constant decode at dispatch and at DYNQ16's pass
  change (`rtl/vec_alu.sv:634-635`, `rtl/vec_alu.sv:733-734`) — control,
  not the per-element datapath; **it was never the design WNS**
  (`evidence/qwen9b/bm/BM1_T3_BUILD.md:615`);
* it is inside `layer_0`, the one block whose shipped placement the
  incremental flow (§4.3) exists to keep; any `layer_0` RTL change reruns
  its OOC synthesis and risks the cell-name match
  (`evidence/qwen9b/bm/BM1_T3_BUILD.md:666-683`);
* **it buys no throughput**: ALU is 41.2 % of the compute lane because of
  its element count, not its decode. ASSUMING the stage adds one cycle per
  ALU command, it costs +4,843 cycles/token, 0.0148 % (**D**, the log's
  arithmetic on that assumption, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:152`);
  even at three cycles per command it stays under 0.05 %.
**Keep it as the first fallback** if the round's own builds show `u_alu`
among the failing paths — a one-state change in the C_IDLE → C_RUN
dispatch, with the TB ladder of G5C (`evidence/qwen9b/g5/G5C_RTL.md` §5).

### 4.3 The incremental-implementation flow

**What.** A new script beside `synth/scripts/full_impl.tcl` (not an edit of
it) that opens the round's project, adds the clock-root XDC
implementation-only as full_impl.tcl does
(`synth/scripts/full_impl.tcl:20-30`), sets the impl run's
INCREMENTAL_CHECKPOINT to the shipped signoff checkpoint
`synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp`
(288,126,447 B, on disk, `evidence/qwen9b/bm/BM1_T3_BUILD.md:688-696`),
keeps the full recipe (post-place and post-route phys_opt
AggressiveExplore, `synth/scripts/full_impl.tcl:33-37`), runs to
write_bitstream, and prints the same TIMING / WHS_GATE / PBLOCK_COUNT lines
plus `report_incremental_reuse`. About 15 lines. The exact property names
and the incremental directive are from memory of UG904 and unverified
(`evidence/qwen9b/bm/BM1_T3_BUILD.md:707-733`); the first run verifies them.

**Step 0 — run it on build_042_bm1 first, no RTL change.** build_042_bm1's
netlist differs from the ship in `seq_0` and one flop per `mvchan`
(`evidence/qwen9b/bm/BM1_T3_BUILD.md:666-669`) — **the same blocks R1 and
R2 change**. So one incremental run of an already-synthesised netlist
measures, for the cost of one implementation, the three unknowns the round
depends on: the reuse fraction, whether the shipped `layer_0` placement
survives, and whether the result closes. If it closes it also turns the
measurement bitstream into a signed-off one. It also re-implements the few
`csr_0` VERSION-constant cells, which differ by design (`c973c18a` against
`9b588e78`, `evidence/qwen9b/bm/BM1_T3_BUILD.md:703-706`).

**What it costs.** Estimated 2–4 h per run on snoke, unmeasured
(`evidence/qwen9b/bm/BM1_T3_BUILD.md:743`), against 4 h 03 m for a base
build and 7–8 h for a four-roll spread (`evidence/qwen9b/bm/BM1_T3_BUILD.md:596-598`).

**What it cannot do.** It cannot reuse the reference's phys_opt replicas
(`evidence/qwen9b/bm/BM1_T3_BUILD.md:722-723`) — **WRONG for Vivado 2024.2 (corrected 2026-09-29, SR9): the incremental read replays the reference's physical-synthesis transforms, every one reused, 0 not reused (`evidence/qwen9b/sr/SR1_INCR_PROBE.md` §3.1; again in `evidence/qwen9b/sr/SR7_R1_BUILD.md` §3)**; on low reuse it falls back
to an ordinary placement, i.e. one more roll (unverified behaviour,
`evidence/qwen9b/bm/BM1_T3_BUILD.md:724-735`); it cannot survive a new
clock tree (§2.3); and a 0.000 on one run is, as G5D said of the ship, one
placement, not a reproducible margin (`evidence/qwen9b/g5/G5D_TIMING.md:1337-1344`).
If it misses, the fallback order is: a four-directive spread with the
clock-root XDC (`evidence/qwen9b/bm/BM1_T3_BUILD.md:44-50`) → the phys_opt
playbook (priced at +0.000 twice, `evidence/qwen9b/g5/G5D_TIMING.md:1317-1318`)
→ the ALU stage (§4.2) or the attention output-gather RTL round
(`evidence/qwen9b/bm/BM1_T3_BUILD.md:795-798`) → a clock cut (§2.3, the
user's decision).

### 4.4 The counters (decision D6)

The BM1 counters are already in `main`'s RTL (`docs/SEQ_ISA.md` §B16);
removing them is itself a netlist change. They cost +187 LUT / +415 FF in
`seq_0` (`evidence/qwen9b/bm/BM1_T3_BUILD.md:160`) and none of their paths
fails on the BM1 best roll (crossing slack +1.340,
`evidence/qwen9b/bm/BM1_T3_BUILD.md:651`). They are the instrument that
shows an R-option working on silicon: the FENCE wait (C5) is exactly what
R1/R2 shrink (census §7, `evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md:690-693`).
**Keep them.** The shipped reference dcp lacks them, so `seq_0`'s reuse is
low either way — Step 0 measures it.

### 4.5 Order of the round (the recommended option, §5 option 2)

| step | what | where | wall (est.) |
|---|---|---|---|
| 0 | incremental probe on build_042_bm1 (no RTL) | snoke | 2–4 h |
| 1 | ISA v2.3 text, SEQ_CAPS; model + validator + pass at r1 (TDD) | snoke | software |
| 2 | R1 RTL; lint; unit TBs x4; shipped streams cycle-identical; R1 streams gate + chip TB x4 | snoke | ~1 h + ~2.3 h |
| 3 | R1 build: incremental (if step 0 worked) else base + spread; clock-root check; final_verify | snoke | 2–4 h, or ~11–12 h |
| 4 | safe reprogram, RD9 ladder, R1 on silicon with the counters | board | a session |
| 5 | R2: the same, as its own netlist; dropped only if UI still misses after a spread and/or an incremental run reusing the shipped mvchan placement | snoke, board | as 2–4 |
| 6 | R3: decided on steps 4–5's silicon figures | — | — |

---

## 5. Options for the user

All tok/s MODEL, form B (form A in brackets), from §3.1; "break-even" is the
aclk cut at which the option equals S1 at full clock.

| # | scope | tok/s at full clock | at its break-even | RTL size (est.) | risks | build-hours (est., snoke) | what it does NOT buy |
|---|---|---|---|---|---|---|---|
| 1 | **ALU stage alone first** | 7.292 shipped / 8.356 with S1 — unchanged | — | ~10 lines, `rtl/vec_alu.sv` | touches `layer_0` (loses the incremental premise) | 1 TB + 1 build campaign | no throughput; closes one of five aclk families at best |
| **2** | **R1, then R2 as a second build (RECOMMENDED)** | R1 8.811 (8.621); R1+R2 9.144 (8.837) | R1 9.57 % (10.89 %); R1+R2 15.80 % (14.99 %) | R1 ~15 + R2 ~40 RTL lines; ~200 Python | R1: `seq_0` (+0.037 on BM1), and UI can miss on any build (placement luck, §1.2) — protected by reusing the shipped mvchan placement (incremental) or a spread; R2: the same UI placement risk over four mvchans; R2 not fail-closed on old bitstreams (SEQ_CAPS) | 2 campaigns: ~10 h each with incremental, ~17 h each without | R3's 0.8 tok/s; nothing on `layer_0`'s WNS families |
| 3 | R1 only | 8.811 (8.621) | 9.57 % (10.89 %) | ~15 RTL lines | smallest cone, one campaign; UI can still miss (the ship's own base roll did, §1.2) — protected by incremental reuse of the mvchan placement | ~10–17 h | R2's +0.33, R3's +0.78 |
| 4 | R1+R2 in one netlist | 9.144 (8.837) | 15.80 % (14.99 %) | ~55 | if it misses you cannot tell whether R1 or R2 did it; a UI miss forces dropping R2 anyway | one campaign, ~10–17 h | R3 |
| 5 | R1+R2+R3 in one netlist | 9.920 (9.559); staging buffer 9.727 (9.377) | 28.62 % (27.40 %); buffer 25.83 % (24.24 %) | ~200 RTL (+15 BD) for (a) | all of the above plus new SLR-crossing datapath or 3 BRAM36; the least-proven model row (census §9 item 6) | one or two campaigns; plus a chip-TB top change | — (it is the ceiling at this granularity short of 11.027, census §4.3) |

**Recommendation: option 2**, because (i) R1 alone carries 0.455 of the
0.788 tok/s R1+R2 adds over S1 and lives entirely on aclk in `seq_0`, the
clock and block where a small cut or the incremental flow can actually
help; (ii) R2's risk is on the UI clocks, where a clock remedy means
slowing the DDR4 (at most ~5 % is worth it, and only if the MIG and DIMMs
allow a sub-grade period, §3.2) — so R2 must be judged on its own netlist,
and dropped only after a spread and/or an incremental run reusing the
shipped mvchan placement has missed too; (iii) R3 is the largest
change, rests on the most optimistic model row, and its value should be
decided from R1/R2's silicon counters, not from the TB model alone. The
cost of staging is one extra build campaign (~10 h if incremental works).

---

## 6. What is NOT established

1. **Every tok/s here is a TB-model estimate.** OV1's R-values are list
   schedules over chip-TB windows, board-scaled by a uniform factor; S1 is
   the only tier measured on silicon (1.11–1.14×,
   `evidence/qwen9b/bm/BM1_BOARD_IDLE.md` §3). The model hit S1 to
   +0.043 % on the TB (`evidence/qwen9b/ov/SV1_S1_VERIFY.md:38-40`); R1–R3
   have no TB run at all.
2. **The clock scenarios are arithmetic on those windows.** They assume
   every aclk window scales exactly as 1/(1−r) and no stream does; DDR
   latency inside LDC/EMB/holds is scaled anyway (conservative). A new
   compute clock would also change CDC latencies nobody has measured.
3. **Form B's internal-resource list is not proven complete** (census §9
   item 3); form A's figures are the safe side of every range.
4. **R3's model is optimistic** (siblings free, own-channel dependencies
   only; census §9 item 6). The staging-buffer row uses a quarter-window
   approximation, not a measurement.
5. **The incremental flow has never been run on this design**; its reuse,
   its fallback behaviour and its wall time are unverified, and the
   Vivado property names in §4.3 are from memory.
6. **The XDMA's axi_aclk choices are now read from the IP**
   (62.5 / 125 / 250 MHz, `evidence/qwen9b/ov/n132_sr0_ip_defs.log:22-24`),
   but not which of them the IP accepts at Gen3 x8 / 256 bits; the MMCM's
   granularity is still from memory (UG572), unchecked.
7. **No DDR4 period other than 833 ps has ever been validated by the MIG
   for this custom part, or calibrated on these DIMMs.** The IP declares
   the period as a free integer 10..5000 ps
   (`evidence/qwen9b/ov/n132_sr0_ip_defs.log:8`); `list_property_value`
   returned no allowed list (`evidence/qwen9b/ov/n131_sr0_ip_query.log:134`),
   so whether any sub-grade period is legal is UNVERIFIED. Scenario U
   assumes the chosen period works.
8. **R2's timing risk is argued from UI placement history, not measured
   for R2.** The ship's own base roll missed all four UI clocks with the
   mvchan RTL unchanged (`evidence/qwen9b/g5/G5D_TIMING.md:322-325`), and
   BM1's rolls missed UI on several of nine: the UI domain misses by
   placement luck on every build. Nothing says R2's two flops and two
   D-mux inputs make that better or worse.
9. **Channel-3 contention** under overlap is bounded, not measured, for
   form B and for any R tier (`evidence/qwen9b/ov/S1P_SHIP.md` §5).
10. **T < 512 only.** Nothing here moves `rtl/attn_core.sv:114`'s ceiling.
11. **Line counts and build-hours are estimates**, the latter from BM1's
    and G5D's wall times.

---

## 7. Open questions for the user (each with the default this spec assumes)

1. **May the round add a compute clock domain** (an MMCM-derived clock for
   `seq_0`/`layer_0`/mvchan aclk side/burst fabric, with SmartConnect clock
   conversion) **if a build cannot close at 250 MHz?** This is the only
   fine-grained way to "take a small clock hit" (§2.3) and it is new
   CDC. *Default: no new clock this round; a miss goes down the §4.3
   fallback list and comes back to you with numbers.*
2. **What is "small"?** The model says an aclk cut up to ~9.5 % still
   leaves R1 at or above S1, ~15 % for R1+R2 (§3.1). *This question is
   moot under Q1's default (no new clock this round, so there is no aclk
   knob to turn); if Q1 is answered yes, the default is: accept up to 5 %
   (every option still clearly ahead), ask beyond.*
3. **Is a UI (DDR4) clock cut ever acceptable** to close the UI clocks?
   *Default: a UI cut of up to ~5–7 % if the MIG permits it and the DIMMs
   calibrate (§6 item 7) — R1+R2 is still above R1-at-full at 5 % (§3.2);
   never a full grade (at DDR4-2133 R1+R2 is below R1 at full clock).*
4. **Option 2 (R1, then R2 as its own build; R3 later)?** *Default: yes.*
5. **Run Step 0 (the incremental probe on build_042_bm1) first?** It costs
   one implementation run and may also sign off the measurement bitstream.
   *Default: yes.*
6. **R3's implementation if it is taken later**: direct x-push bus (a),
   staging buffer (b) or custom splitter (c)? *Default: (a).*
7. **Keep the BM1 counters in the round's netlists?** *Default: yes (§4.4).*
8. **Keep the pending-channel hazard emitter-enforced (no RTL
   interlock)?** An interlock that stalls a MOVX/MVGO/MOVY on a pending
   channel is cheap in `seq_movers` but becomes bank-aware under R2.
   *Default: no interlock; the model gate and the pass assert enforce it,
   as today.*
9. **Does the −0.124 roll's measurement waiver cover the R-round's
   silicon measurement sessions if a round netlist also misses?**
   (`NEXT_SESSION.md` §8 item 3 as it stands after S1D's rewrite, which
   lists this waiver question among "the round's own decisions" that come
   from this spec.) *Default: no — each round bitstream needs its own
   ruling.*

### Decisions table

| # | decision | options | recommended |
|---|---|---|---|
| D1 | R1 encoding | FENCE target[3:0] mask, 0 = all | the only one proposed |
| D2 | R2 encoding | (a) MOVX target start word + SHAPE bits 29/30 + MOVY target[15:4] start row; (b) the banks in MVGO target[2:1] | **(a)**: the SHAPE bits reach `matvec_chan` on the SHAPE write that already happens and inherit its false path |
| D3 | R3 implementation | (a) push bus, (b) staging buffer, (c) splitter | **(a)**, if R3 is taken |
| D4 | RTL hazard interlock | (a) none, (b) stall on a pending channel | **(a)** |
| D5 | old-bitstream guard | (a) SEQ_CAPS at 0x64 + VERSION table, (b) VERSION table only | **(a)** |
| D6 | counters | keep / remove | **keep** |
| D7 | clock cut mechanism | new MMCM domain / sub-grade DDR4 period / DDR grade / none | **none this round** for aclk (Q1–Q2); a ≤ ~5 % UI cut only if the MIG and DIMMs allow it (Q3) |
| D8 | ALU stage | first / fallback / never | **fallback** |
