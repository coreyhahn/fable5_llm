# SR14 — the R2 build: incremental implementation against the R1 sign-off, scored to G5D §10

Plan: `docs/superpowers/plans/2026-09-27-seq-rtl-round.md` Task SR14.
Brief: `.superpowers/sdd/2026-09-27-seq-rtl/task-SR14-brief.md` (the task text plus the controller addendum and its three later additions).
Every log below is under `evidence/qwen9b/sr/`, written on snoke by `evidence/qwen9b/sr/sr_run.sh`
(block n1400–n1499). No board action of any kind: nothing was programmed, no CSR was read, no lock was taken,
no flash was touched, no DMA.

## 0. Verdict: SIGNED OFF (rung 1, the incremental run) — pending its own load ruling (Q9)

`build_045_r2_incr` — the R2 netlist (XWIN/RES double-banking in seq_0 and the four mvchans, on top of R1 and
the BM1 counters), synthesised from the committed tree `266e3ae` (VERSION **266e3ae7**), implemented
incrementally against **the R1 signed-off routed checkpoint** — **meets G5D §10's unrelaxed bar**
(`evidence/qwen9b/g5/G5D_TIMING.md:1255`):

* design WNS **+0.004**, WHS **+0.001**; **0** failing setup of 1,321,426, **0** failing hold of 1,318,290,
  **0** failing pulse-width of 393,059 endpoints (`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:97`);
* every tracked clock meets timing (`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:108-113`, §2);
* **the R2 false-path coverage check: COVERED** — the eight `csr_static_xbank_reg` / `csr_static_rbank_reg`
  registers (two per mvchan) sit inside the `csr_static_*` → `mmcm_clkout0*` false path, and all 384 paths
  from them into the UI clocks are false paths with no timed slack (§3;
  `evidence/qwen9b/sr/n1422_SR14_fpcover_build_045_r2_incr.log:316`);
* the clock-root check passed on the routed checkpoint **before** final_verify: CLOCKROOT_SLR_OK SLR0, CRC_OK, rc 0
  (`evidence/qwen9b/sr/n1423_SR14_clockroot_check_build_045_r2_incr.log:263-267`);
* `synth/scripts/final_verify.tcl` then: FV_WNS 0.004, FV_WHS 0.001, 0 / 0 failing, FV_OK
  (`evidence/qwen9b/sr/n1424_SR14_final_verify_build_045_r2_incr.log:91-105`, `evidence/qwen9b/sr/n1424_SR14_final_verify_build_045_r2_incr.log:140-142`);
* DRC: opt, route and bitgen DRC 0 Errors (`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:73-75`); the routed
  `report_drc` has 13 rule rows and 0 Error / Critical Warning rows (`evidence/qwen9b/sr/n1425_SR14_drc_table_build_045_r2_incr.log:23-24`);
* the routed design has 0 nets with routing errors (`evidence/qwen9b/sr/n1426_SR14_identity_build_045_r2_incr.log:34`);
* no waiver.

**Rung reached: 1** (the incremental run). The ladder of step 5 (the spread, the UI cut, DROP R2) was not
needed and none of it ran: no spread, no 877 ps edit, no UI-cut computation. SR7C was not touched. The
bitstream is written and hashed (§4), and **not loaded** here (SR15 loaded it once on 2026-09-29 under the user's Q9 ruling and restored build_041, `evidence/qwen9b/sr/SR15_R2_BOARD.md`).

## 1. Preconditions and launch

### 1.1 Preflight (`evidence/qwen9b/sr/n1400_SR14_preflight.log`, 17:33, rc 0)

* HEAD `266e3ae` (short8 266e3ae7) descends from `222f80a` (`evidence/qwen9b/sr/n1400_SR14_preflight.log:30-31`). The
  tree was clean apart from the preflight's own log. `266e3ae` is the SR13a doc fix's last commit; the other agent's
  doc-only work on `SR13a_R2_CHIP.md` had landed before this task's first commit, and that file was never touched here.
* **The build's RTL identity.** The rtl/ delta from SR12's R2 commit `9eeaacb` to HEAD is comment-only: 0 non-comment
  lines (`evidence/qwen9b/sr/n1400_SR14_preflight.log:39`; the three files SR11c's cite-drift commits touched). The
  sha256 of every rtl/ file at HEAD is recorded at `evidence/qwen9b/sr/n1400_SR14_preflight.log:40-71` (the addendum's
  ask: SR12's `014a3e2e` for matvec_engine.sv is history; at HEAD it is `a655cc75…`). `rtl/seq_unit.sv` at the
  launch tree equals HEAD's blob (`evidence/qwen9b/sr/n1426_SR14_identity_build_045_r2_incr.log:44-45`).
* The RTL literals: SEQ_CAPS = `{24'hFAB1CA, 5'd0, r3=0, r2=1, r1=1}` = 0xFAB1CA03, BM_IDENT = 0xFAB1B301
  (`evidence/qwen9b/sr/n1426_SR14_identity_build_045_r2_incr.log:40-42`).
* SR7's verdict SIGNED OFF and SR13a's GREEN were read. The launcher's proj_busy guard is wired
  (`evidence/qwen9b/sr/n1400_SR14_preflight.log:93`).
* No other Vivado job was running (`evidence/qwen9b/sr/n1400_SR14_preflight.log:94-95`); load 2.00 on 48 cores
  (`evidence/qwen9b/sr/n1400_SR14_preflight.log:96`). Both out dirs were free, the highest build 044
  (`evidence/qwen9b/sr/n1400_SR14_preflight.log:102-105`). The MIG period is the shipped 833 ps
  (`evidence/qwen9b/sr/n1400_SR14_preflight.log:122`). Tool: vivado v2024.2 (`evidence/qwen9b/sr/n1400_SR14_preflight.log:123`).
* **Step 1 — the reference checkpoint (the controller's ruling: SR7 signed off).** The R1 signed-off routed
  checkpoint SR7 §4 names, `synth/out_build_044_r1_incr/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp`:
  290,607,708 B, mtime 2026-09-28 09:41:18, sha256 **5d8a699795efab1a6aeb6bd5d381ff7f3db6fd8e88bf4c389a2b66d36ad9e332**
  (`evidence/qwen9b/sr/n1400_SR14_preflight.log:107-108`); its project was idle (`evidence/qwen9b/sr/n1400_SR14_preflight.log:110`).
  The alternate `_incr_bm1ref` was not used. The clock-root XDC is `72c3d197…`, unchanged since BM1/SR1/SR7
  (`evidence/qwen9b/sr/n1400_SR14_preflight.log:112`); the launcher / flow / guard hashes are at
  `evidence/qwen9b/sr/n1400_SR14_preflight.log:115-117`.

### 1.2 The netlist (`evidence/qwen9b/sr/n1401_SR14_launch_build_045_r2.log`)

`synth/scripts/launch_build.sh build_045_r2` started at 17:34:19 on tree `266e3ae`; it stamped
`=== create_project (266e3ae7) ===`, so **VERSION = 266e3ae7** (`evidence/qwen9b/sr/n1426_SR14_identity_build_045_r2_incr.log:26-27`).
* create_project: 0 ERROR; its 11 CRITICAL WARNINGs are the set build_042_bm1 had, identically
  (`evidence/qwen9b/sr/n1407_SR14_launch_verify_build_045_r2.log:14-16`). synth_1 finished at 17:54; the base impl_1 was
  launched at 17:54:30 (`evidence/qwen9b/sr/n1407_SR14_launch_verify_build_045_r2.log:25`).
* The base (default-recipe) roll completed: rc 0 at 21:19:02 (`evidence/qwen9b/sr/n1401_SR14_launch_build_045_r2.log:19-20`).

**Judgment call — the incremental run waited for the base build's DONE.** The plan launches it "as soon as
synth_1 is complete", but build.tcl launches impl_1 the moment synth_1 ends, and SR7's lesson (its §1.2: the
copy's `reset_run` killed a running base impl) is now enforced by the proj_busy guard, which refuses a
source proj/ with a run in flight. Launching while the base impl ran would have been a guaranteed BUSY
refusal (a stop), so I waited for `=== DONE` (the guard's own advice) and kept the base roll as SR7 meant it:
one more data point. Cost: ~3 h 25 min of wall time.

**The base default roll (a data point, not a rung)** (`evidence/qwen9b/sr/n1411_SR14_base_roll_build_045_r2.log`):
WNS **−0.865** (aclk −0.865, 27,587 failing), ch0 −0.625, ch3 −0.183, ch1 +0.007, ch2 +0.005, WHS +0.010
(`evidence/qwen9b/sr/n1411_SR14_base_roll_build_045_r2.log:9`, `evidence/qwen9b/sr/n1411_SR14_base_roll_build_045_r2.log:28-33`).
Default placement without the clock-root XDC misses on this design as it always has (the shipped
netlist's own base roll missed all four UI clocks, `evidence/qwen9b/g5/G5D_TIMING.md:322-325`); it says
nothing about R2 and is not a rung.

### 1.3 The incremental run (`evidence/qwen9b/sr/n1410_SR14_launch_incr_build_045_r2_incr.log`)

Launched at 21:24:41 with SR1/SR7's launcher and choices; **every file argument absolute**:

```
synth/scripts/launch_incr.sh build_045_r2 build_045_r2_incr AltSpreadLogic_high \
  /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_044_r1_incr/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp \
  TimingClosure /home/cah/r2d2/code/fpga/fable5_llm/synth/constraints/fable5_clockroot_9b.xdc
```

* The guard printed PROJ_IDLE for the source project before the rsync (`evidence/qwen9b/sr/n1410_SR14_launch_incr_build_045_r2_incr.log:6`).
* rc 0 at 02:23:41, **wall 4 h 59 m** (`evidence/qwen9b/sr/n1410_SR14_launch_incr_build_045_r2_incr.log:1`, `evidence/qwen9b/sr/n1410_SR14_launch_incr_build_045_r2_incr.log:10-11`).
* **Launch verification** at ~28 min (`evidence/qwen9b/sr/n1412_SR14_incr_launch_verify.log`): 0 ERROR
  (`evidence/qwen9b/sr/n1412_SR14_incr_launch_verify.log:15`), and INCREMENTAL_CHECKPOINT named the R1 reference
  (`evidence/qwen9b/sr/n1412_SR14_incr_launch_verify.log:11`).

## 2. `build_045_r2_incr` against the bar

### 2.1 Freshness

Every artifact and report post-dates the 21:24:41 launch (`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:8-21`):
routed dcp 01:52:18, postroute_physopt dcp 01:55:45, mmi 01:55:56, bit 02:06:37, timing_summary 02:19:58, drc 02:23:25
(all 2026-09-29). The logs have 0 ERROR lines (`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:36`) and 0
Timing 38-282 messages (`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:39`).

**One CRITICAL WARNING, the known one:** Route 35-4475, one global clock net with an incomplete placer
guidance tree (`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:38`). This is the message the addendum
ruled NON-BLOCKING on both R1 incremental runs (SR7 §2.1, §9 M-2: the candidates are the aclk and two MIG UI
clock nets, partially routed in the reference). It recurred here for 1 net (SR7's primary had 2, its bm1ref 1).
Recorded the same way: closure stands on the fully routed clock tree — the route-status report has 0 nets with
routing errors (`evidence/qwen9b/sr/n1426_SR14_identity_build_045_r2_incr.log:30-34`) — with hold ≥ +0.001 on every
clock. No NEW critical warning appeared, so there was nothing to stop on.

### 2.2 Per clock (`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:97`, `:108-113`)

Setup WNS (TNS) / WHS in ns, failing endpoints. Comparands: SR7's build_044_r1_incr (SR7 §2.2) and the ship.

| | bar | **build_045_r2_incr** | build_044_r1_incr (R1) | ship (build_041 ckr2) |
|---|---|---|---|---|
| design WNS / WHS | ≥ 0 / ≥ 0 | **+0.004 / +0.001** | +0.001 / +0.001 | 0.000 / +0.001 |
| failing setup / hold / PW EP | 0 / 0 / 0 | **0 / 0 / 0** | 0 / 0 / 0 | 0 / 0 / 0 |
| xdma_0_axi_aclk | ≥ 0 | **+0.012** (TNS 0.000; WHS +0.001) | +0.001 | 0.000 |
| mmcm_clkout0 (MIG ch0 UI) | ≥ 0 | **+0.064** (0.000; WHS +0.010) | +0.012 | +0.003 |
| mmcm_clkout0_2 (ch1) | ≥ 0 | **+0.055** (0.000; WHS +0.010) | +0.035 | +0.031 |
| mmcm_clkout0_3 (ch2) | ≥ 0 | **+0.055** (0.000; WHS +0.010) | +0.023 | +0.016 |
| mmcm_clkout0_1 (ch3) | ≥ 0 | **+0.026** (0.000; WHS +0.004) | +0.026 | +0.026 |
| pipe_clk | ≥ 0 | **+0.766** (0.000; WHS +0.011) | +0.766 | +0.766 |
| PBLOCK_COUNT | — | 0 (`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:32`) | 0 | 0 |

"All clocks" is carried by the design-wide endpoint counts (G5D §10).

**The design WNS +0.004 is not one of the six tracked clocks.** It is the inter-clock pair
GTYE4_CHANNEL_TXOUTCLK[3]_1 → xdma_0_axi_aclk inside the XDMA's PCIe block (+0.004, 0 failing of 2,383;
`evidence/qwen9b/sr/n1421_SR14_interclock_build_045_r2_incr.log:54`). Every inter-clock and async-default row
meets (`evidence/qwen9b/sr/n1421_SR14_interclock_build_045_r2_incr.log`).

**The worst paths per clock** (`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:115-138`): aclk +0.012 is
`layer_0/…/g_kvslot[1].mem_reg_uram_28/CLK` → `…/u_attn/g_lane[127].pv_p_reg[127]_i_3_psdsp/D`, the KV URAM →
attention DSP hop (ATTN_DSP) that bound the ship and R1; the UI clocks' worst are engine-internal
(`r_g_reg` replicas → `pa_q_reg` DSP / `xline_q0_reg` CE). **0 printed paths touch seq_0 or the BM1 counters**
(`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:139`) and **0 touch the R2 mvchan cones**
(`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:404`).

**seq_0's own margin**: worst setup into any `seq_0` D pin **+0.247**, worst hold +0.010, the setup path
`u_seq/rec_reg[37]` → `u_seq/xrf_ovf_reg` (`evidence/qwen9b/sr/n1422_SR14_fpcover_build_045_r2_incr.log:343-346`);
final_verify's still-checked `*seq_0*u_seq/*/D` agrees, +0.247 (`evidence/qwen9b/sr/n1424_SR14_final_verify_build_045_r2_incr.log:137`).
Comparands: R1 +0.242 (`evidence/qwen9b/sr/n1405_SR14_fpcover_posctl_sh_build_044_r1_incr.log:387`; SR7 §2.2), ship +0.397
(`evidence/qwen9b/g5/G5D_TIMING.md:1031`). The R2 changes in seq_0 cost it nothing measurable.

The other still-checked families (`evidence/qwen9b/sr/n1424_SR14_final_verify_build_045_r2_incr.log:124-138`):
u_dn +0.015, u_dma +0.062, u_attn +0.012, the xline_q0 CE cone +0.032 (per channel +0.186 / +0.055 / +0.168 / +0.032).

**SR12's SR14 checklist — the UI-clock cones R2 touches**, worst setup per channel, R2 vs the same probe on the
R1 checkpoint (`evidence/qwen9b/sr/n1422_SR14_fpcover_build_045_r2_incr.log:330-333` vs
`evidence/qwen9b/sr/n1405_SR14_fpcover_posctl_sh_build_044_r1_incr.log:374-377`):

| cone (endpoints) | mvchan_0 | mvchan_1 | mvchan_2 | mvchan_3 |
|---|---|---|---|---|
| x_line (XBANK mux on bits 5:4) | +0.542 (R1 +0.589) | +0.255 (+0.606) | +0.555 (+0.944) | +0.348 (+0.715) |
| row_in (RBANK start, bit 11) | +0.943 (+0.963) | +0.592 (+0.698) | +0.685 (+0.906) | +0.783 (+1.180) |
| g_q (the g_cnt → g_q fanout) | +1.934 (+1.845) | +2.344 (+2.202) | +1.405 (+1.585) | +1.793 (+2.358) |
| g_cnt | +2.504 (+2.386) | +2.058 (+2.249) | +1.357 (+2.368) | +2.096 (+2.162) |

The x_line cone lost margin (to +0.255 at worst) but stays far from the bar; none of these cones is a UI
clock's worst path.

### 2.3 What the tool actually ran

`EFFECTIVE_DIRECTIVES` (`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:30`): place **Explore**, post-place
phys_opt UNNAMED (the 12-9151 override of AggressiveExplore), route **Explore**, post-route phys_opt
AggressiveExplore, incr_override yes. REQUESTED was AltSpreadLogic_high / AggressiveExplore / Default /
AggressiveExplore (`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:31`); the tool's own messages agree
(`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:41-47`). The TIMING line of the launch log is
`evidence/qwen9b/sr/n1410_SR14_launch_incr_build_045_r2_incr.log:9`.

**The estimates along the way — unlike R1, closure came late.** Post-placement WNS **−0.791**
(`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:45`; R1's was −0.038), post-place phys_opt −0.647, the
router's summaries between −0.725 and −0.320. **Closure came inside route_design itself** (fix round 1, I-2 —
corrected; the first version of this section credited the post-route phys_opt, wrongly). The incremental
TimingClosure router (effective directive Explore) ran its own **Phase 13 Incr Placement Change** — an in-router
re-placement (Post Placement −0.058) — and re-routed, ending at the **Post Routing Timing Summary WNS=0.004 /
WHS=0.001** (`evidence/qwen9b/sr/n1457_SR14f1_closure_and_twin.log:23-26`; the router's intermediate summaries `evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:58-71`).
The routed timing report, written at 01:46:45 BEFORE any post-route phys_opt, already reads +0.004 / +0.001 with 0 / 0
failing (`evidence/qwen9b/sr/n1457_SR14f1_closure_and_twin.log:32-33`). The post-route phys_opt AggressiveExplore then found WNS 0.004, skipped every setup optimisation
and printed "The netlist was not modified" (`evidence/qwen9b/sr/n1457_SR14f1_closure_and_twin.log:27-30`): it was a no-op, and the bitstream was written from its
unchanged checkpoint (`evidence/qwen9b/sr/n1457_SR14f1_closure_and_twin.log:31`). **R1 (SR7) closed WITHOUT the in-router re-place**: its run has no Incr Placement Change
phase (count 0) and a post-place WNS of −0.038 (`evidence/qwen9b/sr/n1457_SR14f1_closure_and_twin.log:34-36`). So the load-bearing step for R2 was the incremental
TimingClosure router's re-place + re-route, not the post-route phys_opt — **the baseline for any reroll and for SR15**:
a reroll of this netlist should expect to need that in-router re-place, and R1's cleaner path is not the R2 norm.
The incremental-vs-reference stage table (`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:235-238`): place −0.791
vs −0.038 (0:55 vs 0:34), phys_opt −0.647 vs 0.000, route **+0.004** vs +0.001 (1:46 vs 0:30 — the extra time is the
in-router re-place). This margin is one placement's, as R1's was (§8).

## 3. The R2 false-path coverage check (step 4, R2-specific)

The probe `evidence/qwen9b/sr/sr14_fp_cover.tcl` opens a routed checkpoint read-only (no out dir written; its
reports go to a /tmp scratch dir) and checks, for the registers a filter names: the count and grouping; that
every one is inside the constraint's own `-from` set; `report_exceptions -from` them; and every setup/hold path
from them into the four UI clocks, counting the ones that are NOT a false path with infinite slack.

**Controls first, on the R1 checkpoint** (which has no bank registers):
* n1402 — the default filter matches 0 cells there (`evidence/qwen9b/sr/n1402_SR14_fpcover_negctl_build_044_r1_incr.log:91`); the
  first version then aborted on `report_timing` with an empty set (rc 1), fixed by an empty-set guard.
* n1403 — VOID: a filter with spaces split in `-tclargs`; the probe now takes comma-separated globs.
* n1404 — the positive control on the pre-existing `csr_static_sh` registers found that `get_timing_paths` DOES return
  a false-pathed crossing (slack inf, Timing Exception: False Path) and that 2024.2's `report_timing` has no
  `-unconstrained` (rc 1); the path count was changed to count timed-vs-false paths.
* **n1405 — positive control, COVERED**: 24 cells / 4 groups, 640 UI paths all False Path / inf, 0 timed
  (`evidence/qwen9b/sr/n1405_SR14_fpcover_posctl_sh_build_044_r1_incr.log:101`, `:144`, `:264`, `:360`).
* **n1406 — negative control, NOT_COVERED**: a UI-domain register set outside the false path (`u_engine/g_cnt`, 28
  cells) gives 2,000 timed paths (`evidence/qwen9b/sr/n1406_SR14_fpcover_negctl_gcnt_build_044_r1_incr.log:2267`, `:2366`). The
  probe detects an uncovered register.

**On the R2 routed checkpoint (n1422):**
* `get_cells -hierarchical -filter {NAME =~ */csr_static_xbank_reg* || NAME =~ */csr_static_rbank_reg*}` returns
  **8 cells in 8 groups**, one `csr_static_xbank_reg` and one `csr_static_rbank_reg` (FDRE, 1 bit, on
  xdma_0_axi_aclk) per mvchan (`evidence/qwen9b/sr/n1422_SR14_fpcover_build_045_r2_incr.log:101`, `:132`); all 8 are
  inside the constraint's `csr_static_*_reg*` set (`evidence/qwen9b/sr/n1422_SR14_fpcover_build_045_r2_incr.log:138`).
* Their fanout lands in each channel's own UI clock: rbank → 1 endpoint (`row_in_reg[11]`), xbank → 47
  (`x_line` replicas) — mvchan_0 → mmcm_clkout0, _1 → mmcm_clkout0_2, _2 → mmcm_clkout0_3, _3 → mmcm_clkout0_1.
* **`report_exceptions -from` them** (`evidence/qwen9b/sr/n1422_SR14_fpcover_build_045_r2_incr.log:185-187`, and `-to` the UI
  clocks at `evidence/qwen9b/sr/n1422_SR14_fpcover_build_045_r2_incr.log:216`):

  ```
  Position  From                                                             Through  To                                            Setup  Hold
  262       [get_cells -hierarchical -filter {NAME =~ */csr_static_*_reg*}]  *        [get_clocks -filter {NAME =~ mmcm_clkout0*}]  false  false
  ```

  — the false path of `synth/constraints/fable5_cdc.xdc:14-15`, with an empty Status (not ignored, not partial).
* **Timed paths to the UI clocks: none.** 384 setup+hold paths, all False Path with infinite slack, 0 timed
  (`evidence/qwen9b/sr/n1422_SR14_fpcover_build_045_r2_incr.log:236`, `:310`).
* **FPC_VERDICT: COVERED** (`evidence/qwen9b/sr/n1422_SR14_fpcover_build_045_r2_incr.log:316`). No register was uncovered, so
  the task's STOP (fix the name, not the constraint) did not arise.

## 4. The bitstream (NOT loaded by SR14; loaded once by SR15 on 2026-09-29 and restored)

```
synth/out_build_045_r2_incr/proj/stage1.runs/impl_1/bd_wrapper.bit
  53,080,061 bytes   2026-09-29 02:06:37 -0600
  sha256 c4caeb096b298206c207facca031652a904962a0b0f8a27e98233342af8b4dcb
checkpoint: …/impl_1/bd_wrapper_postroute_physopt.dcp  288,942,161 bytes  01:55:45  sha256 abb6a2d5f0621d79…
routed:     …/impl_1/bd_wrapper_routed.dcp             288,944,909 bytes  01:52:18
mmi:        …/impl_1/bd_wrapper.mmi                         29,668 bytes  01:55:56  sha256 c647a5560d168743…
VERSION = 266e3ae7   expected SEQ_CAPS = 0xFAB1CA03 ({R1, R2})   expected BM_IDENT = 0xFAB1B301
```

**WARNING — a TWIN bitstream shares this VERSION (fix round 1, I-3; SR7's alternate-bitstream warning, applied here).**
The base default roll of §1.2 wrote

```
synth/out_build_045_r2/proj/stage1.runs/impl_1/bd_wrapper.bit     <- NOT the signed-off bitstream
  49,900,081 bytes   2026-09-28 21:06:28 -0600   WNS -0.865 (a timing MISS)
  sha256 de6ad3635f1fbdcd3e798350909fd9b0950a576a89c2965cc3e29147fd21acaa
```

(`evidence/qwen9b/sr/n1457_SR14f1_closure_and_twin.log:38-40`; its timing `evidence/qwen9b/sr/n1411_SR14_base_roll_build_045_r2.log:9`). It is the same netlist, so it
carries the **same VERSION 266e3ae7, SEQ_CAPS 0xFAB1CA03 and BM_IDENT 0xFAB1B301**: neither the `SEQ_VERSIONS` row nor
`evidence/qwen9b/bm/bm1_ident.py` can tell it from the signed-off one. It is kept as evidence (not deleted). Therefore:
**the load ruling names the file by path AND sha256** — `synth/out_build_045_r2_incr/proj/stage1.runs/impl_1/bd_wrapper.bit`,
53,080,061 B, sha256 c4caeb096b298206c207facca031652a904962a0b0f8a27e98233342af8b4dcb (re-hashed at `evidence/qwen9b/sr/n1457_SR14f1_closure_and_twin.log:42-43`) — and
**the session's pre-flight re-hashes the file (size and sha256) immediately before `sw/program_fpga.sh`**, refusing on any
mismatch. The twin above is NOT the signed-off bitstream and must never be programmed.

Sizes, mtimes and hashes: `evidence/qwen9b/sr/n1426_SR14_identity_build_045_r2_incr.log:18-25`; the bit's sha256 also at
`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:88`; the VERSION at `evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:90`.

**The identity expectation** (the addendum's re-run of SR7's readback expectation): hwmap's
`seq_caps_word({R1,R2})` = 0xFAB1CA03 and `SEQ_BM_IDENT` = 0xFAB1B301, matching the RTL literals
(`evidence/qwen9b/sr/n1426_SR14_identity_build_045_r2_incr.log:36-42`). Through the documented pre-flight's pure `judge()`
(`evidence/qwen9b/bm/bm1_ident.py`, scripted words, no device; `evidence/qwen9b/sr/sr14_ident_expect.py`): the R2 identity
PASSES `--want-version 266e3ae7 --want-caps R1,R2`, and the R1 word, 0xDEADC0DE, a missing BM1 block and the R1 VERSION
named as R2 all FAIL; the R1 control still passes — 6 / 0 (`evidence/qwen9b/sr/n1443_SR14_ident_expect.log:68`).

## 5. Reuse

Flat, from Vivado's own reports (`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:157-159`, `:216-218`, `:251-256`):

| | pre-place (reused) | after route (current) | R1 (SR7) after route |
|---|---|---|---|
| cells | **99.84 %** of 767,468 | **99.47 %** | 99.58 % |
| nets | 99.44 % | 97.91 % | 98.16 % |
| pins | 98.27 % | 90.59 % | 88.72 % |
| non-reused cells: new / illegal / timing | 0.10 / 0.04 / 0.01 % | 0.10 / 0.06 / 0.34 % | 0.17 / 0.05 / 0.18 % |

The reference's physical-synthesis replay reused all but 23: fanout_opt 277 / 2 not reused, equ_drivers_opt 67 / 21,
hold_fix 867 / 0 (`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:182-188`).

Hierarchical, after route (`evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:261-300`, subtrees `:321-353`). Columns
Reused / New / Discarded (illegal) / Discarded (timing):

| instance | reused | new | illegal | timing | cite |
|---|---|---|---|---|---|
| bd_wrapper | 763,442 | 831 | 461 | 2,621 | `evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:261` |
| layer_0 | 226,434 | **0** | **0** | 1,339 | `evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:288` |
| seq_0 | 7,236 | **564** | 366 | 200 | `evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:295` |
| ↳ u_seq / u_mov | 7,226 / 2,925 | 562 / 123 | 365 / 26 | 200 / 48 | `evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:351`, `:353` |
| mvchan_0..3 | 33,831 / 33,795 / 33,804 / 33,332 | 66 / 67 / 66 / 68 | 23 / 18 / 14 / 24 | 15 / 29 / 73 / 435 | `evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:289-292` |
| csr_0 | 283 | 0 | 0 | 0 | `evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:279` |
| xdma_0 | 57,059 | 0 | 0 | 41 | `evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:300` |

The netlist change is where R2 put it: seq_0 (564 new — the MOVX target / XWIN start and MOVY row decode, against the R1
reference that already carries R1 and the counters) and ~66 new cells per mvchan (the bank registers and the x_line /
row_in reset muxes). **At placement layer_0 was reused whole** (227,773 reused, 0 new / illegal / timing; the post-place
hook, `evidence/qwen9b/sr/n1420_SR14_score_build_045_r2_incr.log:390`); the 1,339 layer_0 cells in the routed table's timing
column were moved by route_design's in-router re-place (Phase 13, §2.3), and mvchan_3's 435 likewise (post-place it had 47). This differs
from SR7, where the routed and post-place hierarchical tables were near-identical.

## 6. The fallback ladder — NOT executed, not needed

For the record, step 5's order on a miss: (1) the incremental run → (2) the four-directive spread with the
clock-root XDC → (3) the UI cut ≤ 5 % (877 ps; only under SR10 + Q3, with the modelled net computed and reported
BEFORE any 877 ps build; the default expectation DROP R2) → (4) DROP R2, keep R1; an aclk miss → the spread → DROP
R2 or the user decides; SR7C not on R2's ladder. Rung 1 closed, so none of it ran; the `UI_CLK_HZ` host hazard of the
cut rung does not arise (the build is at the shipped 833 ps / 300.12 MHz UI, `evidence/qwen9b/sr/n1400_SR14_preflight.log:122`).

## 7. Host rows (the last step; the bitstream is kept and signed off)

* `sw/seq_run.py` `SEQ_VERSIONS` gains **0x266E3AE7**: (SHAPE_ISA_9B, build_045_r2_incr, admitted only when named,
  expected SEQ_CAPS `HW.seq_caps_word({"R1", "R2"})` = 0xFAB1CA03). `sw/hwmap.py` gains the agreeing
  `SHAPE_ISA_BY_VERSION` row (isa=2) and the `SEQ_BM_IDENT_BY_VERSION` row (0xFAB1B301) — all three together, as the
  selftest's agreement check requires.
* **Judgment call — zero-drift placement.** The seq_run row and the hwmap SHAPE row are ASSIGNED after every cited
  line (the seq_run row just before the `__main__` guard, the hwmap SHAPE row after the BM_IDENT table), and each dict's
  closing line says where; the BM_IDENT row sits in its table (only hwmap's `__main__` guard moves, as in SR7's I-1).
  The new selftest cases are a function `_selftest_sr14` defined after `_emit` and called on what was `_selftest`'s
  blank line. Result: **no cited line moved** — the o3 cite-drift plans from `764760b` are REPAIR 0 / COLLATERAL 0 for
  both files (`evidence/qwen9b/sr/n1441_SR14_drift_plan_seq_run.log:9`, `evidence/qwen9b/sr/n1442_SR14_drift_plan_hwmap.log:9`).
  The rows are module-level assignments executed at import, before any caller can look a VERSION up.
* **The selftest additions** (in `_selftest_sr14`): the R2 row and its hwmap rows agree; `parse_expect_version('266e3ae7')`;
  through the real `Dev._gate` — the R2 VERSION named with 0xFAB1CA03 → SEQ READY; with the R1 word, with 0xDEADC0DE, or
  under the default expect → REFUSED; the R1 VERSION reporting the R2 word → REFUSED. **SR13b's two parked minors**:
  m4 — `FROZEN_PRE_G3_STREAMS` holds chat_seq's `TEMPLATE_SHA256` and `TEMPLATE4_BY_MODEL[None]` shas, and each frozen
  stream's on-disk `.seq` hashes to its key; m2 — a mutated `model_w8_2b_s1.e` (one bit of its last record flipped,
  the keyless manifest rewritten with the new sha) is REFUSED at isa=1 through the real `Artifacts` path by the key
  rule, while the unmutated stream is admitted keyless.
* **RED → GREEN.** n1431, the rows withheld: 2,829 passed / 2 failed (the two R2-row cases; the three frozen-stream
  cases already pass) (`evidence/qwen9b/sr/n1431_SR14_seq_run_selftest_RED.log:59`). GREEN, the rows in: **2,836 / 0** on the clean committed tree
  (`evidence/qwen9b/sr/n1448_SR14f1_seq_run_selftest.log:55`; n1432, the first GREEN, ran on 764760b+dirty and is superseded — below; cite moved by SR9 fix round 1). (n1430 is an earlier RED of the same cases inserted
  mid-`_selftest`, which would have moved cited lines; superseded by the zero-drift placement.)
* **The regressions** (the addendum's list). **Correction (fix round 1, I-1):** n1432–n1440 ran on a DIRTY tree —
  stamped `764760b+dirty` with `sw/hwmap.py` and `sw/seq_run.py` modified; the rows were committed afterwards in
  `f2cd9c1` — not "on the committed rows' tree" as this line first said. They are superseded by **n1448–n1456, re-run on
  the clean committed tree `01564d8`** (git status clean on snoke before the runs; every log's stamp is `01564d8` with no
  dirty line, e.g. `evidence/qwen9b/sr/n1448_SR14f1_seq_run_selftest.log:2`), with identical counts: seq_run **2,836 / 0**
  (`evidence/qwen9b/sr/n1448_SR14f1_seq_run_selftest.log:55`); chat_seq **407 / 1** — the one failure is the pre-existing
  region-image case (`evidence/qwen9b/sr/n1449_SR14f1_chat_seq_selftest.log:33-35`); SR6 **45 / 0**
  (`evidence/qwen9b/sr/n1450_SR14f1_sr6_host_tdd.log:133`); SR7 **36 / 0** (`evidence/qwen9b/sr/n1451_SR14f1_sr7_host_tdd.log:50`);
  SR13b **42 / 0** (`evidence/qwen9b/sr/n1452_SR14f1_sr13b_host_tdd.log:117`); SR11a fix2 12 / 0 and fix3 8 / 0
  (`evidence/qwen9b/sr/n1453_SR14f1_sr11afix2_tdd.log:62`, `evidence/qwen9b/sr/n1454_SR14f1_sr11afix3_tdd.log:31`); the hwmap
  selftest PASS (`evidence/qwen9b/sr/n1455_SR14f1_hwmap_selftest.log:6`); boardfree (FABLE5_MODEL unset, SR6's environment)
  seq 2,836 / 0, serve 85 / 0, chat 407 / 1 (`evidence/qwen9b/sr/n1456_SR14f1_boardfree.log:61`,
  `evidence/qwen9b/sr/n1456_SR14f1_boardfree.log:107`, `evidence/qwen9b/sr/n1456_SR14f1_boardfree.log:138`) — unmoved except
  upward by the added cases. (The GREEN n1432 is likewise superseded by n1448; the RED n1431 is dirty by necessity.)
* **Note:** with the hwmap row, the four direct-CSR tools (`sw/tok_meter.py`, `sw/infer.py`, `sw/layer_test.py`,
  `sw/matvec_test.py`) accept 266e3ae7 with no naming step; CALIB is their only guard (as for e3c2ff1e, SR7 §5).
* `NEXT_SESSION.md` §3 gains the build_045_r2_incr row (path, size, full sha256, NOT LOADED, its own Q9 ruling, the
  named admission and the bm1_ident pre-flight), and §8 item 3 one sentence. The row was added without moving any later
  line (the next paragraph's two lines were joined), so no citation into NEXT_SESSION.md drifts.

## 8. NOT established

* **No board measurement here** (SR15 made them since: `evidence/qwen9b/sr/SR15_R2_BOARD.md`). Nothing was loaded. That the R2 bitstream reports VERSION 266e3ae7, SEQ_CAPS 0xFAB1CA03 and
  BM_IDENT 0xFAB1B301 on silicon, calibrates, and runs an r2 stream token-identically is untested; the functional claims
  remain SR12's unit TB and SR13a's chip TB on the same RTL. R2's ×1.0379 over R1 is MODEL (SR13a), not a board number.
* **One placement, not a margin.** +0.004 design / +0.012 aclk / +0.026 ch3 is one routed result, and this one closed
  only through route_design's in-router re-place (Phase 13 Incr Placement Change) and re-route — not the post-route
  phys_opt, which was a no-op; R1 closed without the re-place (§2.3). The thin margins are not in seq_0 (+0.247) and not in the R2 cones: they are
  the XDMA GT → aclk pair (+0.004), ATTN_DSP (aclk +0.012, u_attn +0.012), u_dn +0.015, and the xline_q0 CE cone
  (+0.032 on mvchan_3).
* **This bitstream needs its own Q9 load ruling** before any programming (SR15) — given by the user on 2026-09-29 ("yes to both", `.superpowers/sdd/2026-09-27-seq-rtl/progress.md`, gitignored, cited by path and date).
* The Route 35-4475 net is not named (verbose mode prints no list; SR7 §9 M-2).
* Why placement started so much worse than R1's (−0.791 vs −0.038 post-place) is not analysed; it closed, and the
  census of the post-place failing paths was not taken.
* The UI-cut rung's modelled net was not computed (the rung was not reached).

## 9. Logs

| log | what | status |
|---|---|---|
| n1400 | preflight | used |
| n1401 | build_045_r2 create + synth + base roll, rc 0 | used |
| n1402 | coverage probe, negative control on R1 (0 cells; aborted at report_timing, rc 1) | used (drove the empty-set guard) |
| n1403 | coverage probe, positive control — the spaced filter split in -tclargs | **VOID** |
| n1404 | positive control: false paths come back from get_timing_paths; no `-unconstrained` (rc 1) | used (drove the timed-vs-false count) |
| n1405 / n1406 | positive control COVERED / negative control NOT_COVERED, on the R1 checkpoint | used |
| n1407 | launch verify of the base build | used |
| n1410 | the incremental launch, rc 0 | used |
| n1411 | the base default roll's score (a data point) | used |
| n1412 | incremental launch verify | used |
| n1420 | score of build_045_r2_incr | used |
| n1421 | inter-clock / other path groups (the design WNS owner) | used |
| n1422 | the false-path coverage check on the R2 routed checkpoint: COVERED | used |
| n1423 | clock-root check (before final_verify) | used |
| n1424 | final_verify | used |
| n1425 | DRC table | used |
| n1426 | bitstream / checkpoint identity, route status, expected identity words | used |
| n1430 | seq_run selftest RED, cases at the first (line-moving) placement | superseded by n1431 |
| n1431 / n1432 | seq_run selftest RED 2829/2 / GREEN 2836/0 (both 764760b+dirty) | RED used; GREEN superseded by n1448 |
| n1433–n1440 | chat_seq, SR6, SR7, SR13b, SR11a fix2/fix3, hwmap, boardfree | superseded by n1448–n1456 (dirty tree, 764760b+dirty) |
| n1441 / n1442 | cite-drift plans for seq_run.py / hwmap.py: REPAIR 0 | used |
| n1443 | the R2 identity expectation through bm1_ident.judge, 6/0 | used |
| n1444 | spec_cites pre-check over this doc and NEXT_SESSION.md: FAIL 2 (a split quote, a bare line-number continuation), both repaired | superseded |
| n1445 | spec_cites: FAIL 1, this table's own row named the bare continuation in backticks; reworded | superseded |
| n1446 / n1447 | spec_cites over this doc and NEXT_SESSION.md, FAIL 0 (n1446 stamped +dirty by a stale NFS view; n1447 the clean re-run) | superseded by fix round 1 |
| n1448–n1456 | fix round 1 (I-1): seq_run, chat_seq, SR6, SR7, SR13b, SR11a fix2/fix3, hwmap, boardfree on the clean committed 01564d8 | used (supersede n1432–n1440) |
| n1457 | fix round 1 (I-2, I-3): the closure sequence from runme.log, R1's comparison, the twin bitstream's identity | used |
| n1458 | spec_cites LAST over this doc and NEXT_SESSION.md (fix round 1) | the LAST |
