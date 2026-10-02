# SR1 — step 0: the incremental-implementation probe on build_042_bm1's netlist

Spec: `docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md` §4.3.
Brief: `.superpowers/sdd/2026-09-27-seq-rtl/task-SR1-brief.md`.
No RTL change, no board. Every number below is cited to a log under
`evidence/qwen9b/sr/`, each written by `evidence/qwen9b/sr/sr_run.sh` on snoke,
and every report it quotes post-dates the launch (§2.1).

## 0. Verdict: CLOSES

One incremental implementation of build_042_bm1's synthesised netlist (the
board-idle-counter netlist, VERSION 9b588e78), run against the shipped signoff
checkpoint, **meets G5D §10's unrelaxed bar** (`evidence/qwen9b/g5/G5D_TIMING.md:1255`):

* design WNS **0.000**, WHS **+0.001**, **0** failing setup of 1,321,075,
  **0** failing hold of 1,317,939 and **0** failing pulse-width of 392,942
  endpoints (`evidence/qwen9b/sr/n005_SR1_score_build_043.log:92`);
* every named clock meets timing, with the aclk at 0.000 and the four MIG UI clocks at +0.026 … +0.114
  (`evidence/qwen9b/sr/n005_SR1_score_build_043.log:103-108`);
* DRC is clean. Bitgen's DRC reports 0 Errors (`evidence/qwen9b/sr/n005_SR1_score_build_043.log:70`),
  and the routed `report_drc` has 0 Error and 0 Critical Warning rule rows
  (`evidence/qwen9b/sr/n008_SR1_drc_table_build_043.log:31`);
* the clock-root check passes: `CLOCKROOT_SLR_OK SLR0`, rc 0
  (`evidence/qwen9b/sr/n006_SR1_clockroot_check_build_043.log:264`, `evidence/qwen9b/sr/n006_SR1_clockroot_check_build_043.log:268`);
* `synth/scripts/final_verify.tcl` returns FV_OK with 0 / 0 failing
  (`evidence/qwen9b/sr/n007_SR1_final_verify_build_043.log:100`, `evidence/qwen9b/sr/n007_SR1_final_verify_build_043.log:106`, `evidence/qwen9b/sr/n007_SR1_final_verify_build_043.log:141`).

The nine ordinary rolls of this netlist missed timing, and the best of them was −0.124
(`evidence/qwen9b/bm/n45_T3_spread2_score_ENDl.log:29`). **Reuse was 99.78 %
of cells after the incremental read and 99.35 % after routing**
(`evidence/qwen9b/sr/n005_SR1_score_build_043.log:152`, `evidence/qwen9b/sr/n005_SR1_score_build_043.log:211`).
The shipped `layer_0` placement survived: 226,033 of its cells were reused,
0 were new, 0 were discarded as illegal, and 1,740 (0.76 %) were discarded to improve timing
(`evidence/qwen9b/sr/n005_SR1_score_build_043.log:281`). The run took
**4 h 48 m 30 s** of wall time (16:22:47 → 21:11:17, `evidence/qwen9b/sr/n003_SR1_launch_incr_build_043.log:1`, `evidence/qwen9b/sr/n003_SR1_launch_incr_build_043.log:10`).
That is above the spec's unmeasured 2–4 h estimate (§1.4).

Because it closes, the fallback list of spec §4.3
(`docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md:646`) is not needed. It is stated in §6 for completeness, and none of it was executed.

## 1. What ran

### 1.1 The property names, verified from Vivado itself (`evidence/qwen9b/sr/n001_SR1_vivado_help_probe.log`, snoke, rc 0)

The spec's names came from memory (`evidence/qwen9b/bm/BM1_T3_BUILD.md:731`). Vivado
2024.2's own `help` output and `list_property` on a throwaway project in `/tmp` show the following.

* **impl run properties.** There are four:
  * INCREMENTAL_CHECKPOINT (type file)
  * INCREMENTAL_CHECKPOINT.DIRECTIVE (string)
  * INCREMENTAL_CHECKPOINT.MORE_OPTIONS
  * AUTO_INCREMENTAL_CHECKPOINT (bool, default 0)

  They are at `evidence/qwen9b/sr/n001_SR1_vivado_help_probe.log:1271-1275` and `:1299-1307`.
* **The read_checkpoint -incremental directive.** It takes RuntimeOptimized (the default, which targets the reference's WNS),
  TimingClosure (target WNS 0, where failing paths are "ripped up") or Quick
  (`evidence/qwen9b/sr/n001_SR1_vivado_help_probe.log:121-126`). The command also has
  `-auto_incremental` and `-force_incr` (`evidence/qwen9b/sr/n001_SR1_vivado_help_probe.log:104`, `:144`).
* **report_incremental_reuse.** It takes `-hierarchical` and `-hierarchical_depth`
  (`evidence/qwen9b/sr/n001_SR1_vivado_help_probe.log:1157`).
* **route_design.** Its help says only Explore, Quick and Default directives are compatible with
  the incremental flow (`evidence/qwen9b/sr/n001_SR1_vivado_help_probe.log:616`). The
  project's route step *requests* Default, but the run did not use it: TimingClosure overrode it
  and the router ran **Explore** (Route 72-6 and Route 35-559, `evidence/qwen9b/sr/n013_SR1fix1_runme_excerpts.log:18-19`; §1.3).

### 1.2 Choices, and why

* **Project mode**, as the ckr2 recipe did. `synth/scripts/launch_po2.sh` rsyncs a
  built `proj/`, and `synth/scripts/full_impl.tcl` re-runs impl_1. The synth checkpoint
  build_042's ckr2 rolls consumed is
  `synth/out_build_042_bm1/proj/stage1.runs/synth_1/bd_wrapper.dcp` (607,216 B,
  sha256 9d68af21…, `evidence/qwen9b/sr/n002_SR1_preflight.log:26`). It is the BD
  top, and the OOC IP netlists are linked into it only by the run's own link_design. That
  makes a non-project `open_checkpoint` of it the wrong unit.
* **The new files.** They are `synth/scripts/incr_impl.tcl`, beside `synth/scripts/full_impl.tcl`, which is unedited, and
  `synth/scripts/launch_incr.sh`, the launch_po2 isolation pattern for a single
  named out dir.
  * The script sets AUTO_INCREMENTAL_CHECKPOINT to 0, INCREMENTAL_CHECKPOINT to the reference and
    INCREMENTAL_CHECKPOINT.DIRECTIVE to TimingClosure.
  * It keeps full_impl.tcl's recipe lines: place AltSpreadLogic_high, post-place and post-route
    phys_opt AggressiveExplore, and the clock-root XDC applied implementation-only.
  * It then prints the same TIMING / PBLOCK_COUNT / WHS_GATE lines and adds
    `report_drc` and `report_incremental_reuse -hierarchical`.
* **TimingClosure rather than the default RuntimeOptimized.** Both target 0 here,
  because the reference's recorded WNS is 0.000
  (`evidence/qwen9b/sr/n005_SR1_score_build_043.log:161`). TimingClosure additionally
  rips up failing paths. The step's question is whether the run closes, so the mode that pursues
  closure was chosen.
* **No -force_incr.** This leaves the tool's own reuse criteria in charge, as spec §4.3
  describes. The tool did not fall back (§3).
* **Isolation.** The out dir `synth/out_build_043_incr_probe/` was new. Preflight
  showed it free, with no Vivado on snoke and highest existing build 042
  (`evidence/qwen9b/sr/n002_SR1_preflight.log:16-18`). The source `proj/` was only
  rsynced out of. The reference dcp was read by path, and the INCREMENTAL_CHECKPOINT
  property holds that path (`evidence/qwen9b/sr/n004_SR1_launch_verify.log:33`).
  Nothing was written into any existing out dir.
* **Inputs, by sha256** (`evidence/qwen9b/sr/n002_SR1_preflight.log:25-27`):
  * the reference, `synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp`,
    288,126,447 B, 84b42d2a…
  * the synth dcp, 9d68af21…
  * the XDC, 72c3d197…, identical to BM1-T3's preflight hash
    (`evidence/qwen9b/bm/n23_T3_preflight_snoke.log:51`).

### 1.3 What Vivado actually did with the directives (a finding)

**The TimingClosure incremental directive overrides the recipe's directives.** Vivado says so
itself: *"This will override place_design, post-place phys_opt_design and route_design directives."*
(`evidence/qwen9b/sr/n005_SR1_score_build_043.log:38`).
* The placer reports that TimingClosure overwrote `-directive AltSpreadLogic_high` and ran **Explore** with a target WNS of 0
  (`evidence/qwen9b/sr/n005_SR1_score_build_043.log:40-41`).
* The router reports the same: TimingClosure overwrote route_design's requested `Default`, and
  route_design ran **Explore** with a target WNS of 0
  (`evidence/qwen9b/sr/n013_SR1fix1_runme_excerpts.log:18-19`).
* **The post-place phys_opt's effective directive is not named anywhere in the log.** Its Command
  line reads `-directive AggressiveExplore` (`evidence/qwen9b/sr/n013_SR1fix1_runme_excerpts.log:16`),
  and 12-9151 says that directive is overridden, but no message names what replaced it.
* **The post-route phys_opt is outside 12-9151's list** and ran AggressiveExplore as requested
  (`evidence/qwen9b/sr/n013_SR1fix1_runme_excerpts.log:20`).
* So what ran is the reference's placement plus the incremental placer's Explore, a post-place phys_opt
  with an unnamed directive, the Explore router, and post-route phys_opt AggressiveExplore. The
  scripts' FULL_IMPL_CFG and TIMING lines recorded what was *requested*, not what ran; fix round 1
  adds REQUESTED= and EFFECTIVE= fields and an EFFECTIVE_DIRECTIVES line to `synth/scripts/incr_impl.tcl`
  for later runs (checked without launching anything, `evidence/qwen9b/sr/n011_SR1fix1_incr_impl_nolaunch_check.log:12-13`).
* **What closed the design was the router's own in-router physical synthesis, on one net.** The
  router's estimate was WNS −0.010 (`evidence/qwen9b/sr/n013_SR1fix1_runme_excerpts.log:22`). Its
  Phase 29, "Physical Synthesis in Router" (runme.log 2547–2580), processed one net,
  `u_attn/g_lane[127].pv_p_reg[127]_i_3_psdsp_n`, and took WNS from −0.009 to 0.000
  (`evidence/qwen9b/sr/n013_SR1fix1_runme_excerpts.log:30-32`, `evidence/qwen9b/sr/n005_SR1_score_build_043.log:66`).
  The separate post-route phys_opt step then only held 0.000 / +0.001
  (`evidence/qwen9b/sr/n005_SR1_score_build_043.log:67`; `evidence/qwen9b/sr/n013_SR1fix1_runme_excerpts.log:41`).
  **Closure was thin: one net, in-router.**

### 1.4 Timeline (`evidence/qwen9b/sr/n003_SR1_launch_incr_build_043.log`, `evidence/qwen9b/sr/n004_SR1_launch_verify.log`)

| step | time (2026-09-27, MDT) | cite |
|---|---|---|
| launch (detached, `setsid nohup`) | 16:22:47 | `evidence/qwen9b/sr/n003_SR1_launch_incr_build_043.log:1` |
| rsync of build_042's proj done | 16:27:47 | `evidence/qwen9b/sr/n003_SR1_launch_incr_build_043.log:6` |
| opt_design done (opt dcp written) | 17:02:59 | `evidence/qwen9b/sr/n004_SR1_launch_verify.log:43` |
| launch verified: 0 ERROR, `read_checkpoint -incremental` running | 17:03:53 | `evidence/qwen9b/sr/n004_SR1_launch_verify.log:41-42` |
| bitstream written | 20:52:57 | `evidence/qwen9b/sr/n005_SR1_score_build_043.log:9` |
| launcher returns, rc 0 | 21:11:17 | `evidence/qwen9b/sr/n003_SR1_launch_incr_build_043.log:9-10` |

Vivado's own stage times (`evidence/qwen9b/sr/n005_SR1_score_build_043.log:229-232`) are as follows:
* read_checkpoint: 0:49
* place: 0:31, against the reference's 1:36
* post-place phys_opt: 0:04, against 0:29
* route: **1:40**, against 0:55

The router went through two rounds. Midway it re-placed cells, reporting a post-placement WNS of 0.071
(`evidence/qwen9b/sr/n005_SR1_score_build_043.log:53`), and then routed again
(`evidence/qwen9b/sr/n005_SR1_score_build_043.log:54-65`). The incremental flow saved placement time and
spent it in routing. **Snoke was shared.** Another agent's OOC synthesis runs
(`out_ooc9b_sr3_*`) and Verilator jobs ran during this build, so the 4 h 48 m is an upper
reading, not a clean measurement. The launch verification ran at 41 minutes, not
within 10. At the 10-minute mark the run was still in link_design, and link plus opt took 35 minutes. That
is recorded here rather than hidden.

## 2. Timing, per clock, against the bar and the comparands

### 2.1 Freshness

All reports and artifacts post-date the 16:22:47 launch
(`evidence/qwen9b/sr/n005_SR1_score_build_043.log:9-20`):
* routed dcp: 20:32:39
* postroute_physopt dcp: 20:42:07
* mmi: 20:42:18
* bit: 20:52:57
* timing_summary: 21:07:14
* drc: 21:11:01

The score log reports 0 ERROR lines in either log, 0 CRITICAL WARNING lines in runme.log, and 0 counts of
Timing 38-282, the tool's "failed to meet timing" message (`evidence/qwen9b/sr/n005_SR1_score_build_043.log:34-36`).
Unlike the ship (G5D §8.5), this run has **no** CRITICAL WARNING. The ship's Place 30-890 clock-root critical warning
is absent from this run's runme.log (0 occurrences), and only the plain WARNING Place 30-934 appears (6 occurrences).
Both counts were read from the gitignored runme.log and are not in a committed log.

### 2.2 The table

Setup WNS in ns, with the failing endpoints where there are any. Sources: SR1 is `evidence/qwen9b/sr/n005_SR1_score_build_043.log:92`, `:103-108`. The ship is
`evidence/qwen9b/g5/141_t14b_roll_ckr2_AltSpreadLogic_high.txt:7`, `:18-23`. The best BM1 roll,
`ckr2b_ExtraNetDelay_low`, is `evidence/qwen9b/bm/n45_T3_spread2_score_ENDl.log:29`, `:40-45`.

| | bar | **SR1 incr probe** | shipped signoff (build_041 ckr2) | best BM1 roll (build_042 END_low) |
|---|---|---|---|---|
| design WNS | ≥ 0.000 | **0.000** | 0.000 | −0.124 |
| failing setup EP | 0 | **0** of 1,321,075 | 0 of 1,319,855 | 2,308 |
| design WHS | ≥ 0.000 | **+0.001** | +0.001 | 0.000 |
| failing hold / PW EP | 0 / 0 | **0 / 0** | 0 / 0 | 0 / 0 |
| xdma_0_axi_aclk | ≥ 0 | **0.000** (WHS +0.001) | 0.000 | −0.124 / 2,214 EP |
| mmcm_clkout0 (MIG ch0 UI) | ≥ 0 | **+0.047** (WHS +0.004) | +0.003 | −0.010 / 94 EP |
| mmcm_clkout0_1 | ≥ 0 | **+0.026** (WHS +0.010) | +0.026 | +0.004 |
| mmcm_clkout0_2 | ≥ 0 | **+0.114** (WHS +0.010) | +0.031 | +0.002 |
| mmcm_clkout0_3 | ≥ 0 | **+0.039** (WHS +0.010) | +0.016 | +0.003 |
| pipe_clk | ≥ 0 | **+0.766** | +0.766 | +0.707 |
| PBLOCK_COUNT | (none used) | 0 (`evidence/qwen9b/sr/n005_SR1_score_build_043.log:30`) | 0 | 0 |

Three of the four MIG UI clocks gained margin over the ship (+0.023 to +0.083); mmcm_clkout0_1 is unchanged at +0.026. The aclk is exactly
where the ship was, at 0.000. `synth/scripts/final_verify.tcl` re-derives the result independently:
FV_WNS 0.000, FV_WHS 0.001, 0 failing setup, 0 failing hold
(`evidence/qwen9b/sr/n007_SR1_final_verify_build_043.log:92-106`). Its still-checked families are all
positive (`evidence/qwen9b/sr/n007_SR1_final_verify_build_043.log:135-139`):
* u_dn: +0.017
* u_dma: +0.024
* u_attn: +0.057
* seq_0 u_seq: +0.307
* the xline_q0 CE cone: +0.224

**The binding path** is xdma_0_axi_aclk at 0.000,
`layer_0/…/g_kvslot[0].mem_reg_uram_42/CLK` → `…/u_attn/g_lane[194].prod_reg[194]/DSP…/B[2]`
(`evidence/qwen9b/sr/n005_SR1_score_build_043.log:131-133`). That is the same KV-cache URAM → attention DSP
hop (ATTN_DSP) that bound the ship at 0.000 (G5D §8.3, §11's "residual owner"). So the reused
placement reproduced the ship's binding path, not a new one. 0 printed paths touch
seq_0 or the counters (`evidence/qwen9b/sr/n005_SR1_score_build_043.log:134`). Since 0 endpoints
fail anywhere, no failing path can touch them either.

### 2.3 Against the bar (G5D §10)

| criterion | measured | PASS |
|---|---|---|
| WNS ≥ 0.000 on all clocks | 0.000 (0 failing setup EP design-wide) | yes |
| WHS ≥ 0.000 | +0.001 (0 failing hold EP) | yes |
| 0 failing pulse-width EP | 0 of 392,942 | yes |
| DRC clean | bitgen 0 Errors; report_drc 0 Error / 0 Critical Warning rows (Warnings only: DSP pipelining DPIP-2 / DPOP-3 / DPOP-4, PDCN-1569 ×3, PDRC pair-equation, REQP-1731, one RTSTAT-10; plus the REQP-1680 advisory ×2; `evidence/qwen9b/sr/n008_SR1_drc_table_build_043.log:18-30`) | yes |
| clock-root check | USER_CLOCK_ROOT X2Y2 carried by the build (`evidence/qwen9b/sr/n006_SR1_clockroot_check_build_043.log:117`); layer_0 URAMs 182 of 182 in SLR0 (`evidence/qwen9b/sr/n006_SR1_clockroot_check_build_043.log:252`); root SLR0 (`evidence/qwen9b/sr/n006_SR1_clockroot_check_build_043.log:186`); CLOCKROOT_SLR_OK SLR0, rc 0 | yes |
| waivers | none | yes |

**CLOSES.**

## 3. The reuse report

### 3.1 Flat (`evidence/qwen9b/sr/n005_SR1_score_build_043.log:135-252`)

| | after `read_checkpoint -incremental` (pre-place) | after route |
|---|---|---|
| cells matched | 99.83 % | 99.83 % |
| cells reused | **99.78 %** of 767,286 | **99.35 %** |
| nets reused | 99.53 % | 96.86 % |
| pins reused | 99.64 % | 87.53 % |
| ports | 100 % | 100 % |
| non-reused cells: new / illegal / discarded for timing | 0.15 / 0.06 / 0.01 % | 0.15 / 0.05 / 0.43 % |

(The pre-place figures are at `evidence/qwen9b/sr/n005_SR1_score_build_043.log:152-155` and `:188-190`; the post-route ones at `evidence/qwen9b/sr/n005_SR1_score_build_043.log:211-214` and `:247-249`.)

**Reuse is far above the "about 85 %" fallback figure**
(`evidence/qwen9b/bm/BM1_T3_BUILD.md:731`), and the tool did not fall back to a default placement.
Its placer ran the "Incremental Placer flow for unplaced cells"
(`evidence/qwen9b/sr/n005_SR1_score_build_043.log:39`).

**A correction to the spec.** It said the flow "cannot reuse the reference's phys_opt replicas"
(`docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md:640`;
`evidence/qwen9b/bm/BM1_T3_BUILD.md:722-723`). **This is false for Vivado 2024.2.** The
incremental read *replays* the reference's physical-synthesis transforms, and every one of
them was reused with 0 not reused (`evidence/qwen9b/sr/n005_SR1_score_build_043.log:177-184`):
* hold_fix: 867
* fanout_opt: 279
* dsp_register_opt: 155
* equ_drivers_opt: 88
* critical_cell_opt: 16
* shift_register_opt: 6
* slr_crossing_opt: 2

### 3.2 Hierarchical, post-route (the out dir's `synth/out_build_043_incr_probe/reports/incr_reuse_routed_hier.rpt`, rows in `evidence/qwen9b/sr/n005_SR1_score_build_043.log:254-346`)

Columns: Reused / New / Discarded(Illegal) / Discarded(Timing). All other discard columns are 0.

| instance | reused | new | illegal | timing | reading |
|---|---|---|---|---|---|
| bd_wrapper (all) | 762,329 | 1,155 | 446 | 3,356 | `evidence/qwen9b/sr/n005_SR1_score_build_043.log:254` |
| **layer_0** | **226,033** | **0** | **0** | 1,740 | **the shipped placement survives**; `evidence/qwen9b/sr/n005_SR1_score_build_043.log:281` |
| ↳ u_attn / u_dn | 79,551 / 76,069 | 0 / 0 | 0 / 0 | 861 / 792 | the discards are timing ripping around the ATTN_DSP / DN hops; `evidence/qwen9b/sr/n005_SR1_score_build_043.log:301`, `:305` |
| ↳ u_alu / u_dma / u_vn | 7,409 / 27,406 / 4,903 | 0 | 0 | 2 / 14 / 9 | `evidence/qwen9b/sr/n005_SR1_score_build_043.log:300`, `:304`, `:309` |
| **seq_0** | 6,159 | **1,151** | **430** | 540 | the netlist change (reading: the counters and their re-synthesised neighbourhood are the new/illegal cells); `evidence/qwen9b/sr/n005_SR1_score_build_043.log:288` |
| ↳ u_seq / u_mov | 3,277 / 2,871 | 1,080 / 70 | 408 / 22 | 413 / 127 | `evidence/qwen9b/sr/n005_SR1_score_build_043.log:345-346` |
| mvchan_0..3 | 33,901 / 33,904 / 33,828 / 33,901 | 1 each | 0 | 12 / 22 / 104 / 1 | the one extra flop per channel is the 1 new cell each; the OOC re-synthesis did **not** break the name match; `evidence/qwen9b/sr/n005_SR1_score_build_043.log:282-285` |
| csr_0 | 238 | 0 | 0 | 45 | no new or illegal cells despite the VERSION constant differing (c973c18a against 9b588e78); 45 re-placed for timing (which cells, not examined); `evidence/qwen9b/sr/n005_SR1_score_build_043.log:272` |
| xdma_0 / ddr4_0..3 | 57,093 / ~38.2 k each | 0 | 0 | 7 / 5 / 14 / 8 / 0 | vendor IP essentially untouched; `evidence/qwen9b/sr/n005_SR1_score_build_043.log:273-276`, `:293` |

**The cell-name identity** that BM1 §12.3 left unverified (the OOC dcp bytes differ) **holds
in practice**: 0 new and 0 illegal cells in layer_0, and 1 new cell per mvchan.

One tooling note: the hierarchical *pre-place* report the script also tried to write did not
appear. The project run's generated script sources the place_design TCL.PRE hook *before*
its own read_checkpoint -incremental, so the hook ran with no reference loaded. Vivado printed
INFO Vivado_Tcl 4-1062 "Incremental flow is disabled" twice and threw nothing
(`evidence/qwen9b/sr/n013_SR1fix1_runme_excerpts.log:9-10`), so the run was unaffected. The post-route hierarchical report, and the run's own flat
pre_placed and routed reports, carry the measurement. A future use of
`synth/scripts/incr_impl.tcl` needed that hook moved; fix round 1 moved it to place_design's TCL.POST
(the property exists, `evidence/qwen9b/sr/n012_SR1fix1_place_tcl_post_prop.log:9`), for later runs.

## 4. The bitstream (NOT loaded: the board was not touched)

```
synth/out_build_043_incr_probe/proj/stage1.runs/impl_1/bd_wrapper.bit
  53,085,629 bytes   2026-09-27 20:52:57 -0600
  sha256 991dafb453addca86e64b188d35000baa17c7850e580a448fc6647f2d52609e0
checkpoint: …/impl_1/bd_wrapper_postroute_physopt.dcp  291,053,779 bytes  20:42:07
mmi:        …/impl_1/bd_wrapper.mmi  29,668 bytes  20:42:18
VERSION = 9b588e78 (build_042_bm1's create_project; the netlist is build_042's)
```

The size and sha256 are at `evidence/qwen9b/sr/n005_SR1_score_build_043.log:82-83`. The mtimes are at `evidence/qwen9b/sr/n005_SR1_score_build_043.log:9`, `:13-14`. The VERSION is at `evidence/qwen9b/sr/n005_SR1_score_build_043.log:85`.
Nothing was programmed and no DMA, CSR access or board lock was used.
VERSION 9b588e78 is the same as build_042_bm1's, so on the board this bitstream is
indistinguishable by CSR from build_042's rolls. Only the sha256 identifies it.

## 5. What is NOT established

* **Nothing here is a board measurement.** The bitstream has not been loaded. That it runs the
  counters and decodes correctly on silicon is untested. The functional claim remains
  BM1-T1's TB and S4's replay, on the same RTL.
* **One placement, not a margin.** As G5D said of the ship, 0.000 on the aclk is one routed
  result (`evidence/qwen9b/g5/G5D_TIMING.md:1341`). A re-run is not guaranteed to reproduce it.
* **R1 / R2 reuse is extrapolated, not measured.** This netlist's changes (seq_0 +187 LUT /
  +415 FF and one flop per mvchan) are **smaller than or comparable to** what R1 and R2 will change.
  Here the seq_0 change was 1,151 new cells and 430 illegal, and it still closed. An R1/R2 netlist
  that touches seq_0 and mvchan again is likely to reuse layer_0 the same way, because layer_0's RTL is
  unchanged. Any change *inside* layer_0 (for example the §4.2 ALU stage) is not covered.
* **The wall time is contaminated** by other agents' concurrent jobs on snoke (§1.4). A
  clean incremental run time is unknown. The upper reading is 4 h 48 m.
* **The directive override (§1.3)** means this run did not execute AltSpreadLogic_high, the
  requested Default router, or (as far as the log says) the post-place AggressiveExplore. Whether RuntimeOptimized (which may
  honour them) would also close is unmeasured.
* **No pre-place hierarchical reuse report exists for this run** (the hook bug, §3.2). Per-hierarchy
  reuse is known only post-route. Fixed in fix round 1 for later runs (a post-place report), not
  re-measured here.
* **This bitstream needs its own Q9 load ruling before it is programmed.** Q9 is the plan's rule that
  each round bitstream gets its own ruling (`docs/superpowers/plans/2026-09-27-seq-rtl-round.md:27`,
  `docs/superpowers/plans/2026-09-27-seq-rtl-round.md:542`). It meets the bar, but whether it
  replaces the waived −0.124 roll as the BM1 measurement bitstream is the user's decision.
* **The routed hierarchical reuse is measured against the reference as loaded.** It does not say
  how far each reused cell's *routing* was kept. Nets are 96.86 % reused and pins 87.53 %.

## 6. What step 0 tells the round

1. **The incremental flow works on this design, and it is the round's implementation path.** It
   turned a netlist that nine ordinary rolls could not close (best −0.124) into a signoff at
   0.000 / +0.001 with 0 failing endpoints in one run. It kept 99.35 % of the ship's cells in place,
   and all of layer_0 except the 0.76 % the timing pass itself chose to move.
2. **The three unknowns of spec §4.3, measured:**
   * reuse fraction: 99.78 % pre-place, 99.35 % post-route
   * does layer_0's shipped placement survive: yes (0 new, 0 illegal)
   * does it close: yes
3. **Corrections to carry into the plan:**
   * phys_opt replicas ARE reused, via the iphys_opt replay (§3.1).
   * TimingClosure overrides the place, post-place phys_opt and route directives (§1.3).
   * The place TCL.PRE hook runs before the incremental read (§3.2).
   * One run cost 4 h 48 m on a shared host, not 2 h.
4. **A measurement bitstream that meets the bar now exists** for build_042_bm1's counter netlist
   (§4). Whether to load it on the board (the BM1 measurement that §12.4 of BM1_T3_BUILD.md was blocked
   on) is the controller's and the user's call. This task did not touch the board.
5. **The fallback list, NOT executed and not needed** (spec §4.3,
   `docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md:646`):
   1. a four-directive spread with the clock-root XDC
   2. the phys_opt playbook
   3. the ALU op-stage (§4.2) or the attention output-gather RTL round
   4. a clock cut (the user's decision)

## 7. Logs

All under `evidence/qwen9b/sr/`, written on snoke by `evidence/qwen9b/sr/sr_run.sh`.

| log | what | status |
|---|---|---|
| n001 | Vivado help + impl_1 property list (throwaway /tmp project) | used |
| n002 | preflight: out dir free, no Vivado, input sha256s | used |
| n003 | the launch, rc 0, 16:22:47 → 21:11:17 | used |
| n004 | launch verification at 17:03 | used |
| n005 | score from the run's own reports | used |
| n006 | clock-root check, CLOCKROOT_SLR_OK SLR0 | used |
| n007 | final_verify, FV_OK | used |
| n008 | DRC summary table | used |
| n009 | spec_cites LAST (first try) | **VOID**: its stamp carries a stale-NFS " M" on this doc (git diff was empty on both hosts); same PASS as n010 |
| n010 | spec_cites LAST at 4b7f6cf, FAIL 0 | superseded as LAST by fix round 1's own |
| n011 | fix 1: tclsh no-launch check of `synth/scripts/incr_impl.tcl`, CHK_OK, no Vivado before/after | used |
| n012 | fix 1: STEPS.PLACE_DESIGN.TCL.POST exists (throwaway /tmp project, no run) | used |
| n013 | fix 1: build_043 runme.log excerpts (hook INFOs, directive overrides, in-router physical synthesis) | used |
| n014 | fix 1: spec_cites LAST over this doc | the LAST |
