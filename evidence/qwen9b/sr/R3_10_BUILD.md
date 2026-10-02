# R3-10 — the R3 build: synth-only, incremental against R2's sign-off, scored to G5D §10

Plan: `docs/superpowers/plans/2026-09-29-r3-broadcast.md` Task R3-10.
Brief: `.superpowers/sdd/2026-09-29-r3-broadcast/task-R3-10-brief.md` (the task text, the controller addenda and the
2026-10-01 dispatch addendum). Every log below is under `evidence/qwen9b/sr/`, written on snoke by
`evidence/qwen9b/sr/sr_run.sh` (block n3200–n3299). No board action of any kind: nothing was programmed, no CSR
was read, no lock was taken, no flash was touched, no DMA.

## 0. Verdict: SIGNED OFF (rung 1, the incremental run) — NOT LOADED, pending its own load ruling (Q9)

`build_046_r3_incr` — the R3 netlist (the MOVX broadcast x-push bus of R3-8, on top of R2, R1 and the BM1 counters),
synthesised synth-only from the committed tree `2e87459` (VERSION **2e874592**), implemented incrementally against
**R2's signed-off routed checkpoint** — **meets G5D §10's unrelaxed bar** (`evidence/qwen9b/g5/G5D_TIMING.md:1255`):

* design WNS **+0.004**, WHS **+0.001**; **0** failing setup of 1,323,185, **0** failing hold of 1,320,049, **0**
  failing pulse-width of 393,702 endpoints (`evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:82`);
* every tracked clock meets timing (`evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:93-98`, §2);
* **the push bus is aclk-only at both ends and timed with NO exception** — 376 bus flops (4 × 94), every one on
  `xdma_0_axi_aclk`, `report_exceptions` from / to them empty, every bus path timed with finite slack, no path from
  the bus to a UI clock: **PP_VERDICT TIMED_NO_EXCEPTION** (`evidence/qwen9b/sr/n3227_R3_10_push_probe_build_046_r3_incr.log:793`, §3). No
  false path and no XDC edit were added;
* the R2 false-path coverage still **COVERED** 8 / 8 (`evidence/qwen9b/sr/n3222_R3_10_fpcover_build_046_r3_incr.log:316`);
* the clock-root check passed on the routed checkpoint **before** final_verify: CLOCKROOT_SLR_OK SLR0, CRC_OK
  (`evidence/qwen9b/sr/n3216_R3_10_clockroot_check_build_046_r3_incr.log:263-265`);
* `synth/scripts/final_verify.tcl` then: FV_WNS 0.004, FV_WHS 0.001, 0 / 0 failing, FV_OK
  (`evidence/qwen9b/sr/n3217_R3_10_final_verify_build_046_r3_incr.log:91-105`, `evidence/qwen9b/sr/n3217_R3_10_final_verify_build_046_r3_incr.log:140`);
* the post-impl sanity block (R3-0's `synth/scripts/postimpl_sanity.tcl`, read-only): CLOCK_GATE_OK, 0 unclocked
  register pins, PCIE / GT LOC identical to build_045_r2_incr's (§2.4);
* DRC: opt and bitgen DRC 0 Errors (`evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:59-60`); the routed
  `report_drc` has 13 rule rows and 0 Error / Critical Warning rows (`evidence/qwen9b/sr/n3218_R3_10_drc_table_build_046_r3_incr.log:23-24`);
  0 nets with routing errors (`evidence/qwen9b/sr/n3219_R3_10_identity_build_046_r3_incr.log:38`);
* no waiver.

**Rung reached: 1.** The ladder of step 5 (the four-directive spread, then STOP-and-report) was not needed and
none of it ran. **No base roll ran (synth-only), so the VERSION names exactly one `.bit`** (§4). The bitstream is
written and hashed, and **not loaded** — R3-11 needs the user's own load ruling naming file + sha256.

## 1. Preconditions and launch

### 1.1 Preflight (`evidence/qwen9b/sr/n3200_R3_10_preflight.log`, 09:24, rc 0)

* HEAD `2e87459` (short8 2e874592), descending from the dispatch HEAD; the tree clean but for the preflight's own
  log (`evidence/qwen9b/sr/n3200_R3_10_preflight.log:32-34`). R3-9b's verdict HELD was read.
* **The build's RTL identity.** `git diff e4d8166 HEAD -- rtl` is empty: 0 changed lines
  (`evidence/qwen9b/sr/n3200_R3_10_preflight.log:38`), so rtl/ is R3-8's; the sha256 of every rtl/ file at the launch tree
  is printed in the same log, and `rtl/seq_unit.sv` at the launch tree equals its 2e87459 blob
  (`evidence/qwen9b/sr/n3219_R3_10_identity_build_046_r3_incr.log:49-50`).
* No other Vivado job of this project or any other (`evidence/qwen9b/sr/n3200_R3_10_preflight.log:107-108`); both out dirs
  free (`evidence/qwen9b/sr/n3200_R3_10_preflight.log:116-117`).
* **The reference checkpoint** — R2's signed-off routed checkpoint
  `synth/out_build_045_r2_incr/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp`: 288,942,161 B, sha256
  **abb6a2d5f0621d79679d2ad02e8ee046fc049893877aab0e18f93bc76cd014a5**, REF_MATCH against the brief's figures, its
  project PROJ_IDLE (`evidence/qwen9b/sr/n3200_R3_10_preflight.log:120-124`). The twin under `synth/out_build_045_r2/` was
  never used. The clock-root XDC is `72c3d197…`, SR14's (`evidence/qwen9b/sr/n3200_R3_10_preflight.log:126`).

### 1.2 The synth-only netlist (`evidence/qwen9b/sr/n3201_launch_build_046_r3.log`)

`SYNTH_ONLY=1 synth/scripts/launch_build.sh build_046_r3`, detached at 09:24:25; it stamped
`=== create_project (2e874592) ===`, so **VERSION = 2e874592** (`evidence/qwen9b/sr/n3201_launch_build_046_r3.log:6`).
* create_project: CREATE_PROJECT_OK, 0 ERROR, 11 CRITICAL WARNINGs — the set build_045_r2 had, identically
  (`evidence/qwen9b/sr/n3202_R3_10_launch_verify_build_046_r3.log:13-15`, `evidence/qwen9b/sr/n3202_R3_10_launch_verify_build_046_r3.log:42`). (Its
  "CSR VERSION set-failures: 1" counts the echoed source line, not a failure; SR14's n1407 printed the same.)
* `=== SYNTH DONE` at 09:45:25, rc 0 (`evidence/qwen9b/sr/n3201_launch_build_046_r3.log:18-19`). **The R3-0 hand-off as
  assumed** (`evidence/qwen9b/sr/n3205_R3_10_synth_done_check.log`): SYNTH_OK, impl_1 never launched (its run directory is
  empty / absent), **0 `.bit` under the out dir**, synth_1 0 ERROR / 0 CRITICAL WARNING, PROJ_IDLE, and
  the launcher's CHECK_ONLY mode accepted it (`evidence/qwen9b/sr/n3205_R3_10_synth_done_check.log:11`,
  `evidence/qwen9b/sr/n3205_R3_10_synth_done_check.log:60-61`, `evidence/qwen9b/sr/n3205_R3_10_synth_done_check.log:67-72`). **No base roll, therefore no twin.**

### 1.3 The incremental run (`evidence/qwen9b/sr/n3203_R3_10_launch_incr_build_046_r3_incr.log`)

Launched detached at 09:49:14 with SR14's recipe, every file argument absolute:

```
synth/scripts/launch_incr.sh build_046_r3 build_046_r3_incr AltSpreadLogic_high \
  /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_045_r2_incr/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp \
  TimingClosure /home/cah/r2d2/code/fpga/fable5_llm/synth/constraints/fable5_clockroot_9b.xdc
```

* The guard printed PROJ_IDLE for the synth-only project before the rsync (`evidence/qwen9b/sr/n3203_R3_10_launch_incr_build_046_r3_incr.log:7`).
  **The synth-only → launch_incr flow worked end to end as R3-0 assumed**: `reset_run impl_1` + `launch_runs impl_1`
  on a never-launched impl_1 ran the full incremental recipe with no error.
* rc 0 at 13:15:38, **wall 3 h 26 m** (`evidence/qwen9b/sr/n3203_R3_10_launch_incr_build_046_r3_incr.log:10-12`); synth-only 21 m before it.
* The log's stamp `2e87459+dirty` names only the then-untracked probe `evidence/qwen9b/sr/r3_push_probe.tcl`, not an
  input of the run; VERSION was fixed at create time from the clean tree.
* **Launch verification** (`evidence/qwen9b/sr/n3204_R3_10_incr_launch_verify.log`): INCREMENTAL_CHECKPOINT names the R2
  reference, 0 ERROR (`evidence/qwen9b/sr/n3204_R3_10_incr_launch_verify.log:11`, `evidence/qwen9b/sr/n3204_R3_10_incr_launch_verify.log:15`).

## 2. `build_046_r3_incr` against the bar

### 2.1 Freshness and messages

Every artifact and report post-dates the 09:49:14 launch (`evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:8-21`):
routed dcp 12:44:04, postroute_physopt dcp 12:47:36, mmi 12:47:47, bit 12:58:16, timing_summary 13:11:48, drc 13:15:22
(2026-10-01). 0 ERROR lines, 0 Timing 38-282 (`evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:36`, `evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:39`).

**One CRITICAL WARNING, the known kind:** Route 35-4475, incomplete placer guidance tree — for **4** global clock nets
here (R2: 1, R1: 2) (`evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:38`). It is the message SR7 §2.1 / §9 M-2 ruled
NON-BLOCKING; recorded the same way: closure stands on the fully routed clock tree (0 nets with routing errors,
`evidence/qwen9b/sr/n3219_R3_10_identity_build_046_r3_incr.log:38`) with hold ≥ +0.001 on every clock. The count rose; no NEW
message appeared.

### 2.2 Per clock (`evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:82`, `:93-98`)

Setup WNS (TNS) / WHS in ns. Comparand: build_045_r2_incr (`evidence/qwen9b/sr/SR14_R2_BUILD.md` §2.2).

| | bar | **build_046_r3_incr** | build_045_r2_incr (R2) |
|---|---|---|---|
| design WNS / WHS | ≥ 0 / ≥ 0 | **+0.004 / +0.001** | +0.004 / +0.001 |
| failing setup / hold / PW EP | 0 / 0 / 0 | **0 / 0 / 0** | 0 / 0 / 0 |
| xdma_0_axi_aclk | ≥ 0 | **+0.012** (TNS 0.000; WHS +0.001) | +0.012 (+0.001) |
| mmcm_clkout0 (ch0) | ≥ 0 | **+0.064** (0.000; WHS +0.010) | +0.064 |
| mmcm_clkout0_2 (ch1) | ≥ 0 | **+0.055** (0.000; WHS +0.010) | +0.055 |
| mmcm_clkout0_3 (ch2) | ≥ 0 | **+0.055** (0.000; WHS +0.010) | +0.055 |
| mmcm_clkout0_1 (ch3) | ≥ 0 | **+0.026** (0.000; WHS +0.004) | +0.026 |
| pipe_clk | ≥ 0 | **+0.766** (0.000; WHS +0.011) | +0.766 |
| PBLOCK_COUNT | — | 0 | 0 |

**Failing endpoints: none.** **The design WNS +0.004 is the inter-clock pair GTYE4_CHANNEL_TXOUTCLK[3]_1 →
xdma_0_axi_aclk** inside the XDMA (+0.004, 0 failing of 2,383; `evidence/qwen9b/sr/n3211_R3_10_interclock_build_046_r3_incr.log:55`),
as on R2. The worst path per clock (`evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:100-123`) is R2's: aclk +0.012 the
KV URAM → attention DSP hop (ATTN_DSP), the UI clocks engine-internal; **0 printed paths touch seq_0 or the BM1
counters, 0 the R2 cones** (`evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:124`, `evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:387`). **None of
the thin margins is on the push bus** (§3).

**seq_0's own margin**: worst setup into any `seq_0` D pin **+0.324** (R2 +0.247), hold +0.010, the path
`u_mov/aw_left_reg[9]` → `u_mov/aw_addr_reg[30]` (`evidence/qwen9b/sr/n3222_R3_10_fpcover_build_046_r3_incr.log:343-344`); final_verify's
`*seq_0*u_seq/*/D` agrees (`evidence/qwen9b/sr/n3217_R3_10_final_verify_build_046_r3_incr.log:137`). The still-checked families
(`evidence/qwen9b/sr/n3217_R3_10_final_verify_build_046_r3_incr.log:124-138`): u_dn +0.015, u_dma +0.062, u_attn +0.012, the xline_q0 CE
cone +0.055 (per channel +0.186 / +0.055 / +0.168 / +0.068) — R2's, except mvchan_3's CE cone +0.068 (R2 +0.032).
The R2 cones (`evidence/qwen9b/sr/n3222_R3_10_fpcover_build_046_r3_incr.log:330-333`) equal R2's but mvchan_3's x_line (+0.384, R2 +0.348).

### 2.3 What the tool actually ran — the closure step, credited correctly

`EFFECTIVE_DIRECTIVES` (`evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:30`): place **Explore**, post-place phys_opt
UNNAMED (the 12-9151 override), route **Explore**, post-route phys_opt AggressiveExplore, incr_override yes.

**Unlike R2, closure did NOT come from route_design's in-router re-place.** Post-placement estimate WNS −0.009
(`evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:45`; R2's was −0.791); the post-place phys_opt's own estimate was already
WNS 0.004 and it printed "The netlist was not modified" (`evidence/qwen9b/sr/n3211_R3_10_interclock_build_046_r3_incr.log:80-82`); the
router's intermediate summaries dipped to −0.060 and ended at the estimated 0.001 / 0.001
(`evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:48-57`), with **no Phase "Incr Placement Change"** (count 0,
`evidence/qwen9b/sr/n3211_R3_10_interclock_build_046_r3_incr.log:89`). The routed timing report, written before the post-route phys_opt,
already reads +0.004 / +0.001 with 0 / 0 failing (`evidence/qwen9b/sr/n3211_R3_10_interclock_build_046_r3_incr.log:91`); the post-route
phys_opt was a no-op (`evidence/qwen9b/sr/n3211_R3_10_interclock_build_046_r3_incr.log:85-87`). **The load-bearing steps were the
incremental placement (reusing 99.72 % of cells) and the incremental Explore route** — R1's cleaner path, not R2's.

### 2.4 The post-impl sanity block (plan review I-7; `synth/scripts/postimpl_sanity.tcl` read-only)

Driven by `evidence/qwen9b/sr/r3_postimpl_sanity_run.tcl` on the routed checkpoint (`evidence/qwen9b/sr/n3215_R3_10_postimpl_sanity_build_046_r3_incr.log`):
CLOCK_GATE_OK (`pipe_clk xdma_0_axi_aclk`), `check_timing -override_defaults no_clock`: **0** register/latch pins
with no clock, PCIE40E4_X1Y2, GTYE4_CHANNEL_X1Y28 … X1Y35 (`evidence/qwen9b/sr/n3215_R3_10_postimpl_sanity_build_046_r3_incr.log:91-110`).
**The same run on build_045_r2_incr's checkpoint** (`evidence/qwen9b/sr/n3223_R3_10_postimpl_sanity_build_045_r2_incr.log`) prints the
identical gate, no-clock and LOC lines (only the scratch report path differs). These are the first PCIE_LOC / GT_LOC lines
on a real netlist from the factored procs (R3-0 §7).

## 3. The push-bus probe — no CDC, no new false path (step 4)

`evidence/qwen9b/sr/r3_push_probe.tcl` opens a routed checkpoint read-only and, per channel, collects four groups of
flops: SEQ_FWD (`u_mov/xp_v_q_reg[c]`, `g_xp[c].xp_i_q_reg[c][*]`, `g_xp[c].xp_d_q_reg[c][*]`, 45), MV_FWD
(`xp_in_v_reg`, `xp_in_d_reg[*]`, 45), MV_RET (`xpush_room_reg`, `xpush_busy_reg`, 2), SEQ_RET (`xp_room_q_reg[c]`,
`xp_busy_q_reg[c]`, 2) — 47 nets per channel, both ends — and checks (a) counts, (b) clocks, (c) `report_exceptions`
from / to / from-to them (rows counted: an explicit empty result), (d) the forward and return hops and the paths into /
out of every group plus the R3-8 review's watch list (xp_cnt → ws_can → s_axib_wready; skid → u_xfifo din), every path
timed (finite slack, no EXCEPTION), (e) the fanout endpoint clocks and any bus → UI-clock path.

**Controls first, on build_045_r2_incr's routed checkpoint:**
* n3212 — positive: the BM1 `mv_busy_bm` registers (aclk → aclk, mvchan → seq_0 across SLRs): 4 cells, 0 exception
  rows from / to, 8 timed paths → **TIMED_NO_EXCEPTION** (`evidence/qwen9b/sr/n3212_R3_10_probe_posctl_build_045_r2_incr.log:199-223`).
* n3213 — negative: the `csr_static_xbank` registers: 1 exception row (the fable5_cdc false path), 376 / 376 paths
  false → **EXCEPTED** (`evidence/qwen9b/sr/n3213_R3_10_probe_negctl_build_045_r2_incr.log:201`, `evidence/qwen9b/sr/n3213_R3_10_probe_negctl_build_045_r2_incr.log:599-600`).
* n3214 — the push mode on the pre-R3 checkpoint: 0 bus cells → **FAIL** (`evidence/qwen9b/sr/n3214_R3_10_probe_pushmode_negctl_build_045_r2_incr.log:210`,
  `evidence/qwen9b/sr/n3214_R3_10_probe_pushmode_negctl_build_045_r2_incr.log:10746`): the probe cannot pass vacuously.

**n3221 — VOID by a NAME, fixed, never a constraint.** The first run on the R3 checkpoint found 1 of 45 SEQ_FWD
flops per channel: the generate-loop copies are named `g_xp[c].xp_*_q_reg`, not `xp_*_q_reg`. `evidence/qwen9b/sr/r3_bus_names.tcl`
listed seq_0's OOC netlist (n3226; n3224 void, a shell-quoting error, rc 1), the filter was fixed (`46e926a`), and n3227
re-ran. Everything else in n3221 already passed.

**n3227 on the R3 routed checkpoint — TIMED_NO_EXCEPTION** (`evidence/qwen9b/sr/n3227_R3_10_push_probe_build_046_r3_incr.log:793`):
* (a)/(b) 16 groups at their expected counts, **376 cells**, every one on `xdma_0_axi_aclk`, no replicas
  (`evidence/qwen9b/sr/n3227_R3_10_push_probe_build_046_r3_incr.log:195`, `evidence/qwen9b/sr/n3227_R3_10_push_probe_build_046_r3_incr.log:588`; the group lines 195–584);
* (c) exception rows from 0, to 0, from-to 0 (`evidence/qwen9b/sr/n3227_R3_10_push_probe_build_046_r3_incr.log:611`, `:633`, `:655`);
* (d) every path timed — worst slack per channel, setup / hold, ns (`evidence/qwen9b/sr/n3227_R3_10_push_probe_build_046_r3_incr.log:674-736`):

| hop | mvchan_0 | mvchan_1 | mvchan_2 | mvchan_3 |
|---|---|---|---|---|
| forward seq_0 → mvchan (90 paths) | +1.130 / +0.147 | +2.451 / +0.034 | +3.055 / +0.019 | +2.294 / +0.158 |
| return mvchan → seq_0 (4 paths) | +0.910 / +0.392 | +3.051 / +0.212 | +2.795 / +0.190 | +2.698 / +0.269 |
| into the seq_0 output flops | +0.930 / +0.080 | +0.960 / +0.147 | +0.710 / +0.205 | +0.768 / +0.246 |
| out of the mvchan input register | +1.246 / +0.018 | +0.787 / +0.023 | +2.269 / +0.018 | +1.758 / +0.055 |
| into room / busy (from xp_cnt) | +0.471 / +0.100 | +1.063 / +0.075 | +1.947 / +0.054 | +1.408 / +0.054 |
| out of the seq_0 room / busy flops (xp_fire, CEs) | +1.433 / +0.279 | +1.344 / +0.313 | +1.262 / +0.357 | +1.297 / +0.331 |
| watch 4: xp_cnt → … → s_axib_wready | +0.299 / +0.043 | +0.974 / +0.052 | +1.095 / +0.054 | +1.027 / +0.046 |
| watch 5: skid → u_xfifo din | +1.829 / +0.319 | +2.174 / +0.368 | +2.253 / +0.208 | +1.893 / +0.389 |

* **The three named SLR crossings on mvchan_0** (`evidence/qwen9b/sr/n3227_R3_10_push_probe_build_046_r3_incr.log:753-758`), all 0 logic
  levels, no exception:
  * forward SLR1 → SLR0, the 45-path bundle: setup **+1.130** (`g_xp[0].xp_i_q_reg[0][11]` → `xp_in_d_reg[43]`,
    datapath 2.655), hold **+0.147** (`xp_d_q_reg[0][6]` → `xp_in_d_reg[6]`);
  * room SLR0 → SLR1, `xpush_room_reg` → `xp_room_q_reg[0]`: setup **+1.915**, hold **+0.392**;
  * busy SLR0 → SLR1, `xpush_busy_reg` → `xp_busy_q_reg[0]`: setup **+0.910**, hold **+0.934**.
  The placer put some of mvchan_0's MV_FWD input flops in SLR1 (its group spans SLR0 + SLR1,
  `evidence/qwen9b/sr/n3227_R3_10_push_probe_build_046_r3_incr.log:241`), so for those bits the SLL hop is the input-register → skid
  hop instead — timed and met (+1.246 / +0.018).
* (e) every bus flop's fanout endpoints are on `xdma_0_axi_aclk` only; **0** paths from the bus to a UI clock
  (`evidence/qwen9b/sr/n3227_R3_10_push_probe_build_046_r3_incr.log:767`, `evidence/qwen9b/sr/n3227_R3_10_push_probe_build_046_r3_incr.log:771`). The only aclk → UI crossing
  the push feeds is the existing `u_xfifo` (an `xpm_fifo_async`), reached through the skid, not from a bus flop.

**The thinnest bus numbers** are the watch-4 term on mvchan_0 (+0.299 setup) and the input-register → skid hold
(+0.018); neither is near the design's binding pairs (+0.004 GT, +0.012 aclk). **No push-bus path is under any
exception, so the task's STOP did not arise; no constraint was added or edited.**

**The R2 false-path coverage on the R3 checkpoint** (`evidence/qwen9b/sr/sr14_fp_cover.tcl`, unchanged): 8 cells in 8 groups, all
inside the constraint's `-from` set, 384 UI paths all false / inf, 0 timed → **COVERED**
(`evidence/qwen9b/sr/n3222_R3_10_fpcover_build_046_r3_incr.log:101-138`, `evidence/qwen9b/sr/n3222_R3_10_fpcover_build_046_r3_incr.log:236`, `evidence/qwen9b/sr/n3222_R3_10_fpcover_build_046_r3_incr.log:316`).

## 4. The bitstream (NOT loaded)

```
synth/out_build_046_r3_incr/proj/stage1.runs/impl_1/bd_wrapper.bit
  53,079,665 bytes   2026-10-01 12:58:16 -0600
  sha256 8b6675315ed8fd832aeea189638587e2dda86641e8665408f9140dbc67964993
checkpoint: …/impl_1/bd_wrapper_postroute_physopt.dcp  292,160,094 bytes  12:47:36  sha256 e134d1b0c54ce16d…
routed:     …/impl_1/bd_wrapper_routed.dcp             292,157,558 bytes  12:44:04
mmi:        …/impl_1/bd_wrapper.mmi                         29,668 bytes  12:47:47  sha256 c647a5560d168743…
VERSION = 2e874592   expected SEQ_CAPS = 0xFAB1CA07 ({R1, R2, R3})   expected BM_IDENT = 0xFAB1B301
```

(`evidence/qwen9b/sr/n3219_R3_10_identity_build_046_r3_incr.log:19-26`; the bit's sha256 also `evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:73`, the VERSION
`evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:75`.)

**The bitstream-count statement (plan review m9).** Closure came at the incremental run; no base roll (synth-only)
and no spread ran, so **VERSION 2e874592 names exactly one `.bit`**: the find over both out dirs lists only the file
above (`evidence/qwen9b/sr/n3219_R3_10_identity_build_046_r3_incr.log:28-29`). There is no twin. The load ruling still names the file
by path AND sha256 (Q9, each bitstream its own ruling), and R3-11's pre-flight re-hashes it inside the programming
lock hold (`sw/program_fpga.sh --expect-sha256`, R3-0).

**The identity expectation.** hwmap's `seq_caps_word({R1,R2,R3})` = 0xFAB1CA07, `SEQ_BM_IDENT` = 0xFAB1B301, matching
the RTL literals (`evidence/qwen9b/sr/n3219_R3_10_identity_build_046_r3_incr.log:40-42`). Through the documented pre-flight's pure
`judge()` (`evidence/qwen9b/sr/sr14_ident_expect.py --want-version 2e874592 --want-caps R1,R2,R3`, scripted words, no device): the R3
identity PASSES, and the R1+R2 word, the R1 word, 0xDEADC0DE, a missing BM1 block, and the R2 / R1 VERSIONs named as
R3 all FAIL — **8 / 0** (`evidence/qwen9b/sr/n3244_R3_10_ident_expect.log:87`). (n3220, the same command run before the hwmap
rows existed, stopped rc 1 at `shape_isa_for_version` — UnknownBitstream; superseded by n3244.)

## 5. Reuse

Flat (`evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:142`, `evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:201`): cells **99.72 %** reused
pre-place of 768,209 (matched 99.76 %), **99.55 %** after route; nets 99.17 % / 98.86 %; pins 99.46 % / 97.52 %.
**Higher than SR14's** (99.84 → 99.47 % cells) at the routed point, against the brief's expectation of lower reuse. The
reference's physical-synthesis replay reused every entry (fanout_opt 277 / 0, hold_fix 867 / 0, equ_drivers_opt 67 / 0, …).

Hierarchical, after route (`evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:244-283`; columns Reused / New / Discarded
(illegal) / Discarded (timing)):

| instance | reused | new | illegal | timing |
|---|---|---|---|---|
| bd_wrapper | 764,788 | 1,631 | 451 | 1,339 |
| layer_0 | 227,773 | **0** | **0** | **0** |
| seq_0 (u_seq / u_mov) | 6,932 (6,919 / 2,854) | **822** (821 / 382) | 399 (399 / 14) | 476 (476 / 95) |
| mvchan_0..3 | 33,836 / 33,860 / 33,853 / 33,789 | 203 / 201 / 202 / 203 | 15 / 9 / 7 / 9 | 2 / 3 / 15 / 44 |
| csr_0 / xdma_0 | 283 / 57,100 | 0 / 0 | 0 / 0 | 0 / 0 |

The netlist change is where R3 put it: seq_0's movers (the output flops, the elastic buffer's pop, the lockstep fire)
and ~202 new cells per mvchan (the input register, the 8-entry skid, the room / busy flops, the 3:1 FIFO mux). The
post-place and post-route hierarchical tables are identical (`evidence/qwen9b/sr/n3210_R3_10_score_build_046_r3_incr.log:346-385`) —
consistent with no in-router re-place (§2.3); layer_0 was reused whole.

## 6. The ladder — NOT executed, not needed

Step 5's order on a miss: the incremental run → the four-directive spread with the clock-root XDC on the synth-only
project (`synth/scripts/launch_po2.sh`, not exercised on a synth-only project — R3-0 §7) → STOP and report to the user
(the fallback to form (b) is the user's ruling). Rung 1 closed; nothing else ran.

## 7. Host rows (the last step; the bitstream is kept and signed off)

* `sw/seq_run.py` `SEQ_VERSIONS` gains **0x2E874592** (SHAPE_ISA_9B, build_046_r3_incr, admitted only when named,
  expected SEQ_CAPS `HW.seq_caps_word({"R1", "R2", "R3"})` = 0xFAB1CA07); `sw/hwmap.py` gains the agreeing
  `SHAPE_ISA_BY_VERSION` (isa=2) and `SEQ_BM_IDENT_BY_VERSION` (0xFAB1B301) rows — together, in one commit (`0a0b156`).
* **Zero drift.** All three rows are module-level assignments after every cited line (the seq_run row and the new
  `_selftest_r3_10` after `_selftest_r3`, called from its last line; both hwmap rows after SR14's SHAPE row), so only
  the two `__main__` guards move. The o3 cite-drift plans from `2e87459`: **REPAIR 0 / COLLATERAL 0** for both files
  (`evidence/qwen9b/sr/n3232_R3_10_drift_plan_seq_run.log:11`, `evidence/qwen9b/sr/n3233_R3_10_drift_plan_hwmap.log:11`).
* **RED → GREEN** (the failing cases named in advance, plan review m10). n3230, the rows withheld, the cases in:
  2,850 passed / **3 failed** — "the R3 VERSION 0x2E874592 is a SEQ_VERSIONS key … with agreeing hwmap SHAPE / BM_IDENT
  rows", "gate: R3 VERSION 2e874592 (named) reporting 0xFAB1CA07 -> SEQ READY" (the real `Dev._gate`), and the block
  running the rest (it raises at `parse_expect_version`) (`evidence/qwen9b/sr/n3230_R3_10_seq_run_selftest_RED.log:57-61`). GREEN with the
  rows: **2,858 / 0** on the clean committed tree (`evidence/qwen9b/sr/n3234_R3_10_seq_run_selftest.log:57`; n3231 the dirty first
  GREEN, superseded).
* **Two R3-6 assertions amended in place, line-count neutral** (each said "no row expects 0xFAB1CA07 — the R3 row is
  R3-10's", now false by design): `sw/seq_run.py`'s R3-6 selftest check, and `rows_reporting()` in
  `evidence/qwen9b/sr/r3_host_tdd.py` (its first clean-tree run, n3238, was 70 / 2 on exactly those two setup checks; after the
  fix `b373b0a` n3247 is **72 / 0**, R3-6's own count, `evidence/qwen9b/sr/n3247_R3_10_r3_host_tdd.log:163`).
* **The regressions on the clean committed tree** (`0a0b156`; n3247 on `b373b0a`, which changed only that tool), at the 9B operating
  point `FABLE5_MODEL=9b FABLE5_RS_F=7` as R3-6 ran them, against R3-6's logs: seq_run **2,858 / 0** (R3-6 2,850 + the 8
  new); SR6 **45 / 0** (`evidence/qwen9b/sr/n3236_R3_10_sr6_host_tdd.log:133`); SR13b **42 / 0** (`evidence/qwen9b/sr/n3237_R3_10_sr13b_host_tdd.log:117`);
  SR7 **36 / 0** (`evidence/qwen9b/sr/n3240_R3_10_sr7_host_tdd.log:50`); SR11a fix2 12 / 0, fix3 8 / 0
  (`evidence/qwen9b/sr/n3241_R3_10_sr11afix2_tdd.log:62`, `evidence/qwen9b/sr/n3242_R3_10_sr11afix3_tdd.log:31`); R3-6 **72 / 0**; hwmap PASS
  (`evidence/qwen9b/sr/n3239_R3_10_hwmap_selftest.log:6`); serve 84 / 1 (`evidence/qwen9b/sr/n3243_R3_10_serve_selftest.log:50`) and chat_seq's
  template-check exception (`evidence/qwen9b/sr/n3235_R3_10_chat_seq_selftest.log:28`) — both **identical to R3-6's at 9b**
  (n2813, n2805). With the operating point unset (SR6's environment): seq_run 2,858 / 0
  (`evidence/qwen9b/sr/n3246_R3_10_seq_run_selftest_unset.log:57`), boardfree seq 2,858 / 0, serve 85 / 0, chat 407 / 1 — the known
  [22] region-image baseline — BOARDFREE_FAIL as R3-6's n2822 (`evidence/qwen9b/sr/n3245_R3_10_boardfree_unset.log:63`,
  `evidence/qwen9b/sr/n3245_R3_10_boardfree_unset.log:109`, `evidence/qwen9b/sr/n3245_R3_10_boardfree_unset.log:140-142`). Unmoved except upward by the added cases.
* With the hwmap row, the four direct-CSR tools accept 2e874592 with no naming step; CALIB is their only guard (as for
  266e3ae7, SR14 §7).
* `NEXT_SESSION.md` §3 gains the build_046_r3_incr row (path, size, full sha256, NOT LOADED, "the load ruling names
  file + sha256", the named admission, the bm1_ident pre-flight) and §8 one sentence, both without moving a later line
  (the paragraph after the table had its two lines joined, as SR14 did). `docs/SEQ_ISA.md` §B17.3: the status line
  → AS BUILT (BUILT, VERSION, sha), "the R3 RTL does not exist yet" rewritten, and the FORWARD COMPATIBILITY cite re-pointed
  at the pre-R3 commit `a65f87c:rtl/seq_unit.sv:798-800` — line-count neutral; `evidence/qwen9b/sr/sr2_isa_tdd.py --r3`'s three
  checks that pinned the old text were amended in place to the AS BUILT text (n3248).

## 8. NOT established

* **No board measurement.** Nothing was loaded. That the R3 bitstream reports VERSION 2e874592, SEQ_CAPS 0xFAB1CA07
  and BM_IDENT 0xFAB1B301 on silicon, calibrates, and runs an r3 stream token-identically is untested (R3-11, under its
  own load ruling); the functional claims remain R3-8's unit TB and R3-9a/9b's chip TB on the same RTL. R3's ×1.085
  over R2 is MODEL (R3-9b), not a board number.
* **One placement, not a margin.** +0.004 design / +0.012 aclk / +0.026 ch3 is one routed result; the binding paths are
  R2's (the GT pair, ATTN_DSP, u_dn), none on the push bus or in seq_0.
* The four Route 35-4475 nets are not named (verbose mode prints no list).
* The OOC deltas R3-8 predicted (seq_unit LUT −22 / FF +205; matvec_chan LUT +54 / FF +57) were not re-measured on the
  full netlist; only the reuse table's new-cell counts (§5) speak to them.
* `synth/scripts/launch_po2.sh` on a synth-only project is still not exercised (no spread was needed).

## 9. Logs

| log | what | status |
|---|---|---|
| n3200 | preflight | used |
| n3201 | the synth-only launch build_046_r3, rc 0 | used |
| n3202 | its launch verify | used |
| n3203 | the incremental run build_046_r3_incr, rc 0 | used |
| n3204 | incremental launch verify | used |
| n3205 | the synth-only hand-off check (no impl_1, no .bit, PROJ_IDLE, CHECK_ONLY) | used |
| n3210 | score of build_046_r3_incr | used |
| n3211 | inter-clock / other path groups; the closure sequence | used |
| n3212 / n3213 / n3214 | probe controls on build_045_r2_incr: TIMED_NO_EXCEPTION / EXCEPTED / FAIL (no cells) | used |
| n3215 / n3223 | post-impl sanity on the R3 / R2 routed checkpoints | used |
| n3216 | clock-root check (before final_verify) | used |
| n3217 | final_verify | used |
| n3218 | DRC table | used |
| n3219 | bitstream / checkpoint identity, the .bit count, route status, expected words | used |
| n3220 | ident_expect before the hwmap rows existed (rc 1, UnknownBitstream) | superseded by n3244 |
| n3221 | push probe, first run: SEQ_FWD 1 / 45 per channel (a NAME bug) | **VOID** (fixed in 46e926a) |
| n3222 | sr14_fp_cover on the R3 checkpoint: COVERED; seq_0 +0.324 | used |
| n3224 | name lister, shell-quoting error, rc 1 | **VOID** |
| n3225 / n3226 | seq_0 OOC names (xp_*; all of u_mov) — found `g_xp[c].xp_*_q_reg` | used |
| n3227 | push probe on the R3 checkpoint: TIMED_NO_EXCEPTION | used |
| n3230 / n3231 | seq_run selftest RED 2850/3 (rows withheld) / GREEN 2858/0 (dirty) | RED used; GREEN superseded by n3234 |
| n3232 / n3233 | cite-drift plans for seq_run.py / hwmap.py: REPAIR 0 | used |
| n3234–n3237, n3239–n3246 | regressions on the clean committed tree 0a0b156 | used |
| n3238 | r3_host_tdd 70 / 2 (R3-6's two no-R3-row assertions) | superseded by n3247 |
| n3247 | r3_host_tdd 72 / 0 after the in-place fix | used |
| n3248 | sr2_isa_tdd.py --r3 on the committed AS BUILT text | used |
| n3249+ | spec_cites (LAST) | the LAST |
