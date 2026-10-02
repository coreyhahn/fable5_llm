# BM1-T3 — build_042_bm1: the board-idle-counter build, to the shipped timing bar

**Status: CLOSED — MISS on all nine implementations (base, spread 1 ×4, spread 2 ×4; best −0.124, `ckr2b_ExtraNetDelay_low`); the phys_opt playbook +0.000; §4.3 step-3 hand-off to the user in §12.**
Spec: `docs/superpowers/specs/2026-09-24-board-idle-counters-design.md` §4.
Brief: `.superpowers/sdd/2026-09-24-overlap/task-BM1-T3-brief.md`.

## 1. Preflight (`n23_T3_preflight_snoke.log`, snoke, 2026-09-24T23:15:56-06:00, rc 0)

* **Tree:** the tree was clean when checked (`PF tracked-dirty: 0`, `PF untracked outside evidence/qwen9b/{bm,bn}: 0`).
  The preflight ran on `022459f`. The SV1 agent committed `9b588e7`
  (evidence-only: `evidence/qwen9b/ov/n69_spec_cites_LAST.log`, +22 lines) at
  23:16:06, three seconds before the launch. So **the build's commit is `9b588e7`**
  (`VERSION 9b588e78`, from `=== create_project (9b588e78) ===`), and the
  launch log's tree stamp is clean (`=== tree: 9b588e7`). Between BM1-T1's
  approved `d1b7e1a` and `9b588e7`, `git diff --stat d1b7e1a..9b588e7 -- rtl synth sw tb`
  is empty. Ruling B1 holds: no RTL change.
* **Other Vivado jobs on snoke:** none were running (`PF   none`). Only the 9
  idle `vivado-mcp` daemons were present. Load average was 1.42 on 48 cores,
  with 239 GB of RAM available.
* **Out dirs:** `synth/out_build_042_bm1` and the four planned spread dirs
  `synth/out_build_042_bm1_ckr2_{AltSpreadLogic_high,AltSpreadLogic_medium,ExtraNetDelay_high,ExtraTimingOpt}`
  were all free. The highest existing build is 041.
* **Tool and licence:** `vivado v2024.2 (64-bit)`, sourced from
  `/home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh`. The renewed
  licence `~/.Xilinx/Xilinx (1).lic` (written 2026-09-23) carries
  `Vivado_System_Edition_Eval expires 07-nov-2026`. The other three files
  expired 22-sep / 06-aug.
* **Recipe inputs (sha256 recorded in n23):** `synth/constraints/fable5_clockroot_9b.xdc`
  has one active line, `set_property USER_CLOCK_ROOT X2Y2` on the `PHY_USERCLK`
  net. That is the same single line G5D §8 closed on. The log also records
  hashes for `launch_build.sh`, `synth/scripts/launch_po2.sh`, `synth/scripts/create_project.tcl`,
  `synth/scripts/build.tcl` and `synth/scripts/full_impl.tcl`.

## 2. The recipe: two launcher steps, as shipped

G5D §1 rows 103/134 and §9 row 9 show the shipped roll came from two separate
launcher invocations. Spec §4.1 reproduces both:

1. **Base build (LAUNCHED):** `synth/scripts/launch_build.sh build_042_bm1`.
   This step runs create_project, then synth_1, then the default impl_1
   through write_bitstream, then reports (`synth/scripts/build.tcl`). **It does
   NOT run the spread.** It is the analogue of `build_041` (row 1, 3 h 40 m).
2. **The spread (TO LAUNCH ON RESUME, after `=== DONE` in the base build's build.log):**
   `TAG=ckr2 XDC=/home/cah/r2d2/code/fpga/fable5_llm/synth/constraints/fable5_clockroot_9b.xdc synth/scripts/launch_po2.sh build_042_bm1 AltSpreadLogic_high AltSpreadLogic_medium ExtraNetDelay_high ExtraTimingOpt`.
   This rsyncs `proj/` into four fresh `synth/out_build_042_bm1_ckr2_<D>`
   dirs. `synth/scripts/full_impl.tcl` then does `reset_run impl_1` with place `-directive D`
   and post-place plus post-route `phys_opt AggressiveExplore`, with the XDC
   added as implementation-only. The four run in parallel. That makes it
   `ckr2_AltSpreadLogic_high` exactly (G5D row 9), plus the three next-best
   directives (rows 3, 4, 6), all carrying the XDC, per spec §4.1.

## 3. The launch (`n24_T3_launch_build_042_bm1.log`, in flight)

```
ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm && nohup bash evidence/qwen9b/bm/bm_run.sh \
  n24_T3_launch_build_042_bm1.log synth/scripts/launch_build.sh build_042_bm1 \
  > /dev/null 2>&1 < /dev/null &'
```

* Started **2026-09-24T23:16:09-06:00** on snoke, tree `9b588e7`. The
  wrapper log gets its `=== rc` / `=== end` lines when the launcher exits, the
  same way the shipped `evidence/qwen9b/g5/103_t14b_build_041.log` did. Commit it on resume.
* Out dir: `synth/out_build_042_bm1/`. Logs: build.log (launcher stages),
  create.log, build_run.log, `proj/stage1.runs/{synth_1,impl_1}/runme.log`.

## 4. Launch verification (`n25_T3_launch_verify.log`, 23:21:40, rc 0), plus the synth-launch check at 23:25:24

* **`validate_bd_design` PASSED with the four new `mv_busy_bm` scalar pins.** This
  settles the reviewer's ⚠️ item. the out dir's create.log line 758 is `validate_bd_design: Time (s): cpu = 00:00:43` (quoted in `evidence/qwen9b/bm/n25_T3_launch_verify.log:46`),
  and its line 795 is CREATE_PROJECT_OK at 23:21:23 (`evidence/qwen9b/bm/n25_T3_launch_verify.log:47`). There were **0 ERRORs**.
  The create.log has **11 CRITICAL WARNINGs**, and that set is **byte-identical after
  sort** to `synth/out_build_041/create.log`'s 11 (BD 41-1354 address-overlap ×4
  and BD 41-237 MAX_BURST_LENGTH ×7, both pre-existing). The **87 WARNINGs** form
  an identical set (the diff is empty). No message names `mv_busy_bm`.
* The build stage (`synth/scripts/build.tcl`) started at 23:21:34. `launch_runs synth_1` fired
  the OOC IP runs at **23:25:20** (line 203 of the out dir's build_run.log, which is uncommitted). Vivado pids were alive
  at 23:25:24: 1077487 (`synth/scripts/build.tcl`, the parent), the OOC synth runs (e.g.
  1081485 `bd_layer_0_0`, 1081486 `bd_seq_0_0`), and the launcher chain
  1075477 → 1075478 → 1075492 (bm_run) → 1075545 (`launch_build.sh`).

## 5. Expected completion (spec §4.4, the shipped campaign's wall times)

| step | comparand | expected |
|---|---|---|
| base build (`launch_build.sh`) | 3 h 40 m (build_041) | about **03:00** 2026-09-25 |
| four-roll `ckr2` spread, launched on resume | 5 h 35 m (the po2 spread) | about **08:40** if launched promptly |
| checks (final_verify, clock-root, census) | minutes to an hour | about **09:30–10:00** |

## 6. BASE ROLL: build_042_bm1 (`launch_build.sh` default recipe, no XDC)

The base build finished `BUILD_OK`. Its wrapper log `n24_T3_launch_build_042_bm1.log`
ends `=== rc : 0`, `=== end : 2026-09-25T03:19:04-06:00`, so it took **4 h 03 m**
against build_041's 3 h 40 m. The numbers below come from **n36**
(`n36_T3_base_roll_042_bm1.log`, which runs `evidence/qwen9b/g5/g5d_roll_summary.sh`
on both rolls, plus the first path per named clock and top-level utilization)
and **n37** (`n37_T3_base_roll_util_hier.log`, the hierarchical rows). Both ran
on snoke with rc 0.

**Freshness.** Every report and artifact post-dates the 23:16:09 launch. From n36:
* timing_summary.rpt: 2026-09-25 03:14:12
* utilization.rpt: 03:14:59
* utilization_hier.rpt: 03:15:31
* `bd_wrapper_routed.dcp`: 02:52:40
* `bd_wrapper.mmi`: 02:52:51
* `bd_wrapper.bit`: 03:06:49, 52,376,509 bytes

The launcher also printed `CLOCK_GATE_OK: 250MHz clocks: pipe_clk xdma_0_axi_aclk`
and `TIMING: WNS=-0.687 WHS=0.001`.

**The comparand is the shipped campaign's own BASE roll**, `build_041`
(G5D §9 row 1: default recipe, no XDC, WNS −0.859, TNS −5,879.083, 29,237
failing setup EP, WHS +0.006). The shipped final (row 9, 0.000) is **not** the
comparand. That figure is a full-recipe `ckr2` roll, and the spread below is
what gets compared to it.

| (T, n36) | **build_042_bm1** | build_041 (G5D §9 row 1) | Δ |
|---|---|---|---|
| WNS, design | **−0.687** | −0.859 | +0.172 |
| TNS | −6,717.958 | −5,879.083 | −838.875 |
| failing setup EP | 36,472 of 1,321,575 | 29,237 of 1,321,608 | +7,235 |
| WHS / failing hold EP | +0.001 / 0 | +0.006 / 0 | |
| failing pulse-width EP | 0 of 391,787 | 0 of 393,278 | |
| `xdma_0_axi_aclk` WNS / TNS / fail | −0.687 / −4,866.754 / 23,559 | −0.859 / −4,672.020 / 21,523 | |
| `mmcm_clkout0` (ch0 UI) | −0.307 / −255.776 / 2,650 | −0.524 / −957.757 / 5,084 | |
| `mmcm_clkout0_1` | −0.345 / −98.096 / 881 | −0.070 / −9.377 / 327 | |
| `mmcm_clkout0_2` | −0.378 / −439.885 / 3,372 | −0.310 / −18.632 / 233 | |
| `mmcm_clkout0_3` | −0.601 / −1,057.447 / 6,010 | −0.336 / −221.297 / 2,070 | |
| `pipe_clk` | +0.914 | +1.049 | |

The router's post-route estimate (Route 35-57) was WNS −0.779 / TNS −7,050.9.
The signoff `report_timing_summary` above supersedes it.

**The worst path's owner (n36, the first Max Delay path of each named clock).**
On `xdma_0_axi_aclk`, the design WNS runs
`bd_i/layer_0/inst/u_core/u_dma/x_kind_reg[1]/C` → `…/u_dma/fmem_reg_0_255_314_314/DP.A/I`
at −0.687. That is `layer_0`'s `u_dma` LUTRAM write, **the same owner class as
build_041's own worst path** (`…/u_dma/f_rp_reg[0]/C` → `…/u_dma/fmem_reg_0_255_50_50/DP.A/I`,
−0.859). It falls in G5D's `layer_0` owner class (§4.3), inside the `u_dma` set
that `FV_STILL_CHECKED` watches (§8.3). It is **not** the counters, and it is
not the ship's post-XDC `ATTN_DSP` path either, because a default-recipe roll
has no clock-root file. The four MIG UI clocks' worst paths are all inside the
`mvchan_*` streamer/engine, the same family as build_041's
(`matvec_engine`'s 300 MHz cone). No worst path of the 144 printed touches
`seq_0` or the `mv_busy_bm` nets (the complete check is §12.3a, n57). The default recipe runs no post-route `phys_opt`, and in
G5D the base roll was never the scored roll (§3.1).

**Reading it.** One default-recipe roll against one default-recipe roll carries
the placer's run-to-run spread, which is ±0.5 ns across G5D's own rolls (§9).
This is **not** evidence that the counters helped or hurt timing. It shows the
netlist implements and routes, lands in the same place as the shipped base roll,
and that no new owner class shows up.

**Utilization delta (n36 top level, n37 hierarchy; same default recipe, both base rolls):**

| | build_042_bm1 | build_041 | Δ |
|---|---|---|---|
| CLB LUTs (device) | 310,085 | 309,669 | **+416** |
| CLB Registers (device) | 318,432 | 319,915 | −1,483 |
| BRAM tile / URAM / DSP | 251 / 182 / 1,860 | 251 / 182 / 1,860 | 0 / 0 / 0 |
| `seq_0` LUTs / FFs | 3,992 / 2,990 | 3,805 / 2,575 | **+187 / +415** |
| `mvchan_0..3` FFs | 14,175 / 14,210 / 14,132 / 14,180 | 14,184 / 14,130 / 14,133 / 14,142 | −9 / +80 / −1 / +38 |
| `layer_0` LUTs / FFs | 114,215 / 63,573 | 114,082 / 65,578 | +133 / −2,005 |

The counters' own cost is the `seq_0` row: **+187 LUTs, +415 FFs**. That is
consistent with eleven 32-bit counters (352 FFs) plus the synchroniser,
alignment and readback flops. It uses no BRAM, URAM or DSP. The device-level
register drop comes from `layer_0` (−2,005 FFs). Its RTL is unchanged
(§1.1 of the spec), so that drop is the implementation's replication and
`phys_opt` choices differing between rolls, not the counters.

## 7. THE SPREAD: four `ckr2` rolls (launch record)

**Launch (`n38_T3_launch_po2_ckr2.log`, in flight; it gets its `=== rc` / `=== end` lines when `synth/scripts/launch_po2.sh` returns):**

```
ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm && setsid nohup bash evidence/qwen9b/bm/bm_run.sh \
  n38_T3_launch_po2_ckr2.log env TAG=ckr2 XDC=/home/cah/r2d2/code/fpga/fable5_llm/synth/constraints/fable5_clockroot_9b.xdc \
  synth/scripts/launch_po2.sh build_042_bm1 AltSpreadLogic_high AltSpreadLogic_medium ExtraNetDelay_high ExtraTimingOpt \
  >/dev/null 2>&1 </dev/null &'
```

* **Started 2026-09-25T03:23:19-06:00** on snoke. This is G5D §9 row 9's recipe
  (`ckr2`, AltSpreadLogic_high) plus rows 3, 4 and 6's directives, all
  carrying the clock-root XDC (spec §4.1). The `env TAG=… XDC=…` values are in
  the log's `=== cmd` line, which log 134 of the shipped roll lacked.
* **Tree stamp caveat.** n38 reads `=== tree: 2db4918+dirty` with
  `=== dirty:  M evidence/qwen9b/bm/BM1_T3_BUILD.md`. That file was committed
  unchanged in `2db4918` seconds earlier. Checked right after,
  `git status --porcelain --untracked-files=no` and `git diff --stat` were
  empty on both darthplagueis and snoke. So this was a stale NFS stat entry
  in git's index (the commit was made on darthplagueis and the stamp computed
  on snoke), not a content change. The file is also not a build input. The
  spread's inputs (the base project `synth/out_build_042_bm1/proj`, VERSION
  9b588e78, and the XDC with the sha256 in n23) are unchanged.
* **Verified within 10 minutes (`n39_T3_po2_ckr2_launch_verify.log`, 03:26:32, rc 0).**
  Four full_impl Vivados were alive, each in its own fresh dir (`/proc/<pid>/cwd`):
  * 1347954: `synth/out_build_042_bm1_ckr2_AltSpreadLogic_high`
  * 1348086: `…_ckr2_AltSpreadLogic_medium`
  * 1348691: `…_ckr2_ExtraNetDelay_high`
  * 1349637: `…_ckr2_ExtraTimingOpt`

  All four logged
  `EXTRA_XDC: …/fable5_clockroot_9b.xdc (implementation-only)` and
  `FULL_IMPL_CFG: place=<D> phys_opt=AggressiveExplore (post-place AND post-route enabled)`,
  with 0 ERRORs. The launcher chain is 1347770 → 1347771 (bm_run) → 1347840 (`synth/scripts/launch_po2.sh`).
* **Expected completion:** the po2 spread took 5 h 35 m (G5D §1 row 109), which
  puts this at about **09:00** on 2026-09-25. The shipped `ckr2` roll alone took
  4 h 54 m.

## 8. SPREAD 1: scoring against G5D §10's unrelaxed bar

**The bar** (G5D §10): WNS ≥ 0 and WHS ≥ 0 on all clocks, 0 failing
setup/hold/pulse-width endpoints, no waiver. **Instrument:**
`evidence/qwen9b/bm/bm1_roll_score.sh`, committed in `45b16d4` before its first
use. It is read-only. For each roll it prints the report and artifact mtimes,
the fullimpl `TIMING`/`WHS_GATE`/`PBLOCK_COUNT` lines,
`evidence/qwen9b/g5/g5d_roll_summary.sh`'s design row and six named clocks, the worst Max Delay
path per named clock, and a count of printed paths touching `bd_i/seq_0/`,
`mv_busy_bm` or `bm_*_reg`.

### 8.1 The two rolls that have landed (`n40_T3_spread1_score_ETO_ASLh.log`, 08:21:01, rc 0)

Freshness: every report and artifact is dated 2026-09-25, after the spread's
03:23:19 launch. ETO: routed dcp 06:52:33, postroute_physopt dcp 07:11:04,
bit 07:19:50, timing_summary 07:28:54. ASL_high: routed dcp 07:10:21,
postroute_physopt dcp 07:50:04, bit 07:58:16, timing_summary 08:06:57. Both
have `PBLOCK_COUNT: 0`, `WHS_GATE: OK`, `BUILD_OK` and 0 ERROR lines.

| roll (ckr2 XDC, full recipe) | WNS | TNS | failing setup EP | WHS | failing hold / PW EP | verdict |
|---|---|---|---|---|---|---|
| `ckr2_ExtraTimingOpt` | **−0.173** | −255.151 | 4,351 of 1,322,032 | +0.002 | 0 / 0 | **MISS** |
| `ckr2_AltSpreadLogic_high` | **−0.385** | −946.076 | 8,713 of 1,320,290 | +0.001 | 0 / 0 | **MISS** |

Per clock (WNS / failing EP), from n40:

| clock | ETO | ASL_high |
|---|---|---|
| `xdma_0_axi_aclk` | −0.173 / 4,351 | −0.385 / 7,773 |
| `mmcm_clkout0` | +0.002 / 0 | −0.259 / 940 |
| `mmcm_clkout0_1` | +0.008 / 0 | +0.029 / 0 |
| `mmcm_clkout0_2` | +0.010 / 0 | +0.009 / 0 |
| `mmcm_clkout0_3` | **0.000** / 0 | +0.007 / 0 |
| `pipe_clk` | +0.346 | +0.899 |

**Worst-path owners (n40): the design's known set. None of the paths the two
reports print touches `seq_0`, the counters or the `mv_busy_bm` nets** (count 0
on both rolls) (bounded: the scoring logs see only what `report_timing_summary` prints, the worst setup and hold path per clock group, 144 `Slack` lines per report, because `synth/scripts/full_impl.tcl:74` runs it without `-max_paths`; the complete check is §12.3a, on the best roll only).

* **`xdma_0_axi_aclk`, both rolls: the DN cache URAM → `u_dn` DSP read.**
  * ETO: `…/u_core/g_dnslot[0].mem_reg_uram_26/CLK` → `…/u_dn/g_lane[119].dec_p_reg[119]/DSP_A_B_DATA_INST/A[6]`.
  * ASL_high: `…/g_dnslot[1].mem_reg_uram_12/CLK` → `…/u_dn/p_1_out__18__5/DSP_A_B_DATA_INST/A[7]`.

  This is G5D's `layer_0 / u_dn` class (DN_SLOT → DN lane DSP). It is the same
  shape as G5D §4.7's `g_dnslot[1].mem_reg_uram_12/CLK → u_dn/p_1_out__2__13/…A[7]`
  at −0.147. On the ship it closed at +0.003 (G5D §8.3's class table). **So
  the design's binding path moved from `u_attn` (ATTN_DSP, 0.000 on the ship)
  to its sibling `u_dn`.** Both are a URAM cache read into the layer's DSP
  array, with the same mechanism (§8.2: clock skew on a URAM → DSP hop), and
  both sit in `layer_0`, whose RTL is unchanged. What moved is placement.
* **MIG UI clocks:** `mvchan_*` `u_engine` (`r_g_reg`/`g_cnt_reg` → `scales_q_reg` CE,
  `sum64_q_reg` CE) and `u_streamer` (`f_rd_reg` → fifo WE, `beats_to_req_reg` →
  `m_arlen_reg` CE). This is G5D's `matvec_engine` CE family. It closes on ETO
  (0.000 … +0.010) and misses on ASL_high's `mmcm_clkout0` (−0.259).
* **`pipe_clk`:** `xdma_0` PHY internals, met.

**Against G5D §9 on the same directives** (G5D rolls #2/#4 carried no XDC; #9
is the only G5D *placement* with the XDC. Row 10, the playbook run on #9, also
carried it, but it is not an independent placement, `evidence/qwen9b/g5/G5D_TIMING.md:1173`):

| directive | G5D, no XDC | G5D, ckr2 XDC | **BM1, ckr2 XDC** |
|---|---|---|---|
| `ExtraTimingOpt` | −0.196 (#4) | not run | **−0.173** |
| `AltSpreadLogic_high` | −0.156 (#2) | **0.000 (#9)** | **−0.385** |
| `AltSpreadLogic_medium` | −0.159 (#3) | not run | −0.344 (final, §8.2a) |
| `ExtraNetDelay_high` | −0.139 (#6) | not run | −0.554 (final, §8.2a) |

The shipped directive with the shipped XDC lands 0.385 ns short on this
netlist. The only netlist change is the counters (spec §1; the `seq_0` delta
is in §6), and the worst path is a `layer_0` path the counters do not touch.
Taken with G5D §9's own note (the five full-recipe rolls there span 0.512 ns),
this reads as the placer landing somewhere different on a reseeded netlist,
not as the counters costing slack. **This is an inference (I), not a
measurement.** Only an A/B on the same directive with and without the counters
could measure it, and B1 rules that out.

### 8.2 The last two rolls (`n43_T3_spread1_score_ASLm.log`, 10:11:00; `n44_T3_spread1_score_ENDh.log`, 10:36:28; both rc 0)

**Freshness:**
* ASL_medium: routed dcp 07:24:13, postroute_physopt dcp 09:49:01, bit 09:59:09, timing_summary 10:08:22.
* END_high: routed dcp 08:53:11, postroute_physopt dcp 10:16:57, bit 10:24:50, timing_summary 10:33:48.

Both show `PBLOCK_COUNT: 0`, `WHS_GATE: OK`, `BUILD_OK` and 0 ERROR lines.
The spread's wrapper log `n38_T3_launch_po2_ckr2.log` ends `=== rc : 0`,
`=== end : 2026-09-25T10:36:15`, so the spread ran 7 h 13 m, including the
overlap with spread 2 from 08:50.

| roll (ckr2 XDC, full recipe) | WNS | TNS | failing setup EP | WHS | failing hold / PW EP | verdict |
|---|---|---|---|---|---|---|
| `ckr2_AltSpreadLogic_medium` | **−0.344** | −1,485.636 | 14,061 of 1,322,256 | 0.000 | 0 / 0 | **MISS** |
| `ckr2_ExtraNetDelay_high` | **−0.554** | −3,221.275 | 21,457 of 1,321,301 | 0.000 | 0 / 0 | **MISS** |

Per clock (WNS / failing EP):

| clock | ASL_medium | END_high |
|---|---|---|
| `xdma_0_axi_aclk` | −0.344 / 8,340 | −0.384 / 13,644 |
| `mmcm_clkout0` | −0.169 / 599 | 0.000 / 0 |
| `mmcm_clkout0_1` | −0.275 / 1,976 | **−0.554** / 5,940 |
| `mmcm_clkout0_2` | −0.277 / 1,978 | −0.127 / 1,758 |
| `mmcm_clkout0_3` | −0.132 / 1,168 | −0.064 / 112 |
| `pipe_clk` | +0.779 | +0.943 |

**Worst-path owners: still the known set, still 0 printed paths on
`seq_0`/counters/`mv_busy_bm`** (bounded: the scoring logs see only what `report_timing_summary` prints, the worst setup and hold path per clock group, 144 `Slack` lines per report, because `synth/scripts/full_impl.tcl:74` runs it without `-max_paths`; the complete check is §12.3a, on the best roll only).
* **ASL_medium, aclk:** `…/u_core/dma_kind_reg[0]/C` → `…/u_core/g_kvslot[0].mem_reg_uram_29/CAS_IN_ADDR_B[4]`.
  This is the KV cache's URAM address (G5D's `layer_0` caches DN/KV/CV class, `KV_SLOT`).
  * `mmcm_clkout0/_1/_2` worst paths: `mvchan_*` `u_engine`/`u_streamer`, the
    `matvec_engine` CE family (`xline_q0`, `scales_q`).
  * `mmcm_clkout0_3` worst path: MIG-internal
    `ddr4_2/…/u_io_addr_sync` → `u_ddr_cal_addr_decode/cal_WE_B_reg[1]/CE`
    (G5D's `VENDOR_MIG` family).
* **END_high:** the design WNS is on the MIG UI clock `mmcm_clkout0_1`:
  `mvchan_3/…/u_engine/x_line_reg[1]_rep__16/C` → `…/xline_q0_reg[12]__26/D`.
  That is exactly the `matvec_engine` 300 MHz `xline_q0` cone G5D watches
  (§4.7, §10.1 item 3: "the directive family … keeps [it] closed"; this one
  does not).
  * aclk: `layer_0/…/u_alu/op_q_reg[0]/C` → `…/u_alu/ps_rnd_reg[13]/D`
    (G5D's `LAYER_OTHER`).

### 8.2a Spread 1, all four rolls

| directive | G5D no-XDC (§9) | G5D ckr2 | **BM1 ckr2** | aclk worst owner | MIG UI clocks |
|---|---|---|---|---|---|
| `ExtraTimingOpt` | −0.196 | — | **−0.173** | DN URAM → `u_dn` DSP | all met (0.000 … +0.010) |
| `AltSpreadLogic_medium` | −0.159 | — | **−0.344** | `u_core` → KV URAM addr | all four negative |
| `AltSpreadLogic_high` | −0.156 | **0.000** | **−0.385** | DN URAM → `u_dn` DSP | `clkout0` −0.259 |
| `ExtraNetDelay_high` | −0.139 | — | **−0.554** | `u_alu` (aclk −0.384) | `clkout0_1` −0.554 (`xline_q0`) |

**Spread 1 MISSES the bar on all four rolls.** WHS is ≥ 0 on all four, and
every roll has 0 failing hold and 0 failing pulse-width endpoints, so hold is
not the problem. Setup fails on every roll. The best is `ExtraTimingOpt` at −0.173
with 4,351 failing endpoints, all on `xdma_0_axi_aclk`. The four span
0.381 ns, which is inside G5D's own 0.512 ns full-recipe span (§9). The binding
owners are all `layer_0` or `matvec_engine` paths from G5D's known list. None
is the new counter logic.

### 8.3 Spread-1 verdict and the decision to launch spread 2 before §8.2 landed

**Correction after the fact (§8.2):** the reasoning below leaned on G5D
§10.1 item 5 (post-route `phys_opt` +0.000). On this netlist, post-route
`phys_opt` moved ASL_medium from −0.463 to **−0.344** (+0.119, `Post Physical
Optimization Timing Summary` in its impl_1/runme.log) and END_high from
−0.565 to −0.554. So the premise was wrong for ASL_medium. The decision did
not rest on it in the end: both rolls finished negative.


The two scored rolls MISS. The two unscored rolls stand at −0.463 and −0.565,
each in its last optimisation stage. G5D §10.1 item 5 measured the post-route
`phys_opt` stage at +0.000 on both the negative and the closing position, so
neither can reasonably reach 0.000. Under the controller's ruling B4 (spec
§4.3 step 1, no waiting), **spread 2 is launched now rather than about an hour
later.** If §8.2's final numbers somehow pass, spread 2 is stopped (it is
this task's own job) and the passing roll goes to the closing checks.

## 9. SPREAD 2: choices, stated before launch

Same netlist (`synth/out_build_042_bm1/proj`), same ckr2 XDC, same full recipe
(`synth/scripts/full_impl.tcl`: place `-directive D`, post-place and post-route `phys_opt
AggressiveExplore`), `TAG=ckr2b`, so the dirs are fresh
`synth/out_build_042_bm1_ckr2b_<D>`.

**Why no literal "reroll".** `synth/scripts/full_impl.tcl` exposes no placer seed. Vivado's
placer is designed to be deterministic for identical inputs, and a same-tool,
same-thread-count rerun of `ExtraTimingOpt` on the identical netlist and XDC
would, as designed, reproduce spread 1's −0.173. That would spend 5 h on no new
sample. (The global note that placer non-determinism causes ±3 ns WNS variation
concerns the multi-SLR spread between *different* runs; it is not relied on
here.) **The nearest-variant directive** is therefore used for each "reroll".
Changing `synth/scripts/full_impl.tcl` to add a seed-like knob would be new tooling, which
spec §4.3 puts in step 3.

| # | directive | why |
|---|---|---|
| 1 | `ExtraPostPlacementOpt` | log 138's second supplementary directive (`evidence/qwen9b/g5/138_t14b_spread_po4.log`: `launch_po2.sh build_041 ExtraNetDelay_high ExtraPostPlacementOpt`). Its first, `ExtraNetDelay_high`, is already in spread 1. It has never been scored: G5D #7 routed but failed bitgen with 24 × `DRC RTSTAT-11` in a vendor SmartConnect FIFO. **Watch item:** the same DRC may recur. |
| 2 | `ExtraNetDelay_low` | the nearest variant of log 138's first directive, `ExtraNetDelay_high`, which was the best unconstrained directive of G5D's campaign (−0.139, #6) |
| 3 | `AltSpreadLogic_low` | the nearest variant of the ship's closing directive `AltSpreadLogic_high` (G5D #9, 0.000), the second-best directive of spread 1 |
| 4 | `EarlyBlockPlacement` | the "reroll" of spread 1's best directive, `ExtraTimingOpt` (−0.173), which has no low/high variant. `EarlyBlockPlacement` places the RAM and DSP blocks first, timing-driven, and anchors the rest of the logic to them. The binding path in both scored rolls is a **URAM → DSP** hop (`g_dnslot` → `u_dn` DSP, §8.1), so this is the directive that targets the owner. |

Expected wall time: about 5 h 35 m, like the po2 spread (G5D §1 row 109).
Spread 1's two unfinished rolls are still running for up to about an hour of
overlap. snoke had 208 GB of RAM available and a load of 6 on 48 cores at
08:49, so six concurrent Vivado jobs fit.

**Launch (`n41_T3_launch_po2_ckr2b.log`, in flight, tree stamp `46bd0cc` clean):**
`timeout 30 ssh -f snoke 'cd … && setsid nohup bash evidence/qwen9b/bm/bm_run.sh n41_T3_launch_po2_ckr2b.log env TAG=ckr2b XDC=/home/cah/r2d2/code/fpga/fable5_llm/synth/constraints/fable5_clockroot_9b.xdc synth/scripts/launch_po2.sh build_042_bm1 ExtraPostPlacementOpt ExtraNetDelay_low AltSpreadLogic_low EarlyBlockPlacement >/dev/null 2>&1 </dev/null &'`.
It started at **2026-09-25T08:49:49-06:00**, and the ssh returned at once (rc 0).

**Verified (`n42_T3_po2_ckr2b_launch_verify.log`, 08:53:01, rc 0).** Four new
full_impl Vivados were running, each in its own fresh dir (`/proc/<pid>/cwd`):
* 2048811: `synth/out_build_042_bm1_ckr2b_ExtraPostPlacementOpt`
* 2048932: `…_ckr2b_ExtraNetDelay_low`
* 2049362: `…_ckr2b_AltSpreadLogic_low`
* 2050415: `…_ckr2b_EarlyBlockPlacement`

All four logged `EXTRA_XDC: …/fable5_clockroot_9b.xdc (implementation-only)` and
`FULL_IMPL_CFG: place=<D> phys_opt=AggressiveExplore (post-place AND post-route enabled)`,
with 0 ERRORs. Spread 1's `AltSpreadLogic_medium` (1348086) and
`ExtraNetDelay_high` (1348691) were still running beside them. Load was 11.0,
with 201 GB of RAM available. **Expected completion is about 14:30** (5 h 35 m
from 08:50).

## 10. SPREAD 2: scoring

### 10.1 `ckr2b_ExtraNetDelay_low`, the best roll of either spread (`n45_T3_spread2_score_ENDl.log`, 14:09:29, rc 0)

**Freshness:** all artifacts are dated 2026-09-25, after the 08:49:49 launch:
routed dcp 12:58:21, postroute_physopt dcp 13:46:43 (288,066,231 bytes),
mmi 13:46:53, bit 13:58:23 (52,710,545 bytes), timing_summary 14:07:05. The
fullimpl log shows `PBLOCK_COUNT: 0`, `WHS_GATE: OK whs=0.000`, `BUILD_OK`
and 0 ERROR lines.

| | WNS | TNS | failing setup EP | WHS | failing hold / PW EP | verdict |
|---|---|---|---|---|---|---|
| design | **−0.124** | −94.611 | 2,308 of 1,322,333 | 0.000 | 0 / 0 | **MISS** |
| `xdma_0_axi_aclk` | −0.124 | −94.171 | 2,214 | +0.004 | 0 | |
| `mmcm_clkout0` | −0.010 | −0.440 | 94 | 0.000 | 0 | |
| `mmcm_clkout0_1` / `_2` / `_3` | +0.004 / +0.002 / +0.003 | 0 | 0 | | | |
| `pipe_clk` | +0.707 | | | | | |

**Owners:**
* aclk: `…/u_core/u_attn/og_i_reg[1]_rep__4/C` → `…/u_attn/o_g8_reg[18][15]/D`.
  This is `layer_0`'s `u_attn` output gather (register → register fan-out),
  G5D's `layer_0 / u_attn` class. It is not the ATTN_DSP URAM → DSP hop.
* `mmcm_clkout0`: `mvchan_0/…/u_streamer/f_rd_reg[0]/C` → (hidden), the
  `matvec_engine` streamer/engine family, at −0.010 on 94 endpoints.
* **0 printed paths touch `seq_0`, the counters or `mv_busy_bm`** (bounded: the scoring logs see only what `report_timing_summary` prints, the worst setup and hold path per clock group, 144 `Slack` lines per report, because `synth/scripts/full_impl.tcl:74` runs it without `-max_paths`; the complete check is §12.3a, on the best roll only). **The complete check over all 2,308 failing endpoints also finds 0** (§12.3a).

**Against G5D:** `ExtraNetDelay_low` was never run in G5D. Its sibling
`ExtraNetDelay_high` was −0.139 with no XDC (G5D #6) and −0.554 here (§8.2).
This is the closest any BM1 roll has come. It is 0.124 ns and 2,308 endpoints
from the bar, against the ship's pre-XDC best of −0.139 / 3,461.

### 10.2 The other three (still in post-route `phys_opt` at 14:10)

Their impl_1/runme.log estimates:

| roll | estimate |
|---|---|
| `ExtraPostPlacementOpt` | −0.606 / TNS −3,444.9 |
| `EarlyBlockPlacement` | −0.629 / −2,424.2 |
| `AltSpreadLogic_low` | −0.694 / −2,688.6 |

They are scored from their own reports when they land (§10.3). The largest
post-route `phys_opt` gain seen on this netlist is +0.119 (§8.3's correction),
so none can reach 0.000 or overtake −0.124. Under ruling B5, **§4.3 step 2 is
launched now on `ckr2b_ExtraNetDelay_low`**.

## 11. §4.3 STEP 2: the post-route `phys_opt` playbook on the best roll (choices stated before launch)

**Source checkpoint:**
`synth/out_build_042_bm1_ckr2b_ExtraNetDelay_low/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp`
(13:46:43, the checkpoint behind §10.1's −0.124). Across both spreads it has
the best WNS (−0.124 against spread 1's best, ETO at −0.173), the fewest
failing endpoints (2,308 against 4,351), and three of the four MIG UI clocks
met.

**Script:** `evidence/qwen9b/g5/g5b_physopt_playbook.tcl`, **unchanged**,
invoked the way G5D ran it (`evidence/qwen9b/g5/148_t14b_playbook_ckr2.log`: `bash -c 'source
…/settings64.sh && exec vivado -mode batch -nolog -nojournal -source
evidence/qwen9b/g5/g5b_physopt_playbook.tcl -tclargs <src_dcp> <out_dir>'`),
through `bm_run.sh`. Out dir: the fresh
`synth/out_build_042_bm1_po3_ENDl_playbook`.

| step (the script's fixed order) | why |
|---|---|
| `phys_opt_design -directive AlternateReplication` | the directives the full recipe did NOT spend (it ran AggressiveExplore at both stages). Replication targets exactly the aclk owner here, a `rep__`-replicated register fanning out across the `u_attn` `o_g8` gather. |
| `-directive AggressiveFanoutOpt` | the same fan-out owner |
| `-directive Explore` | the playbook's broad pass |
| `-directive AggressiveExplore` | the playbook's last pass on the best checkpoint so far |
| hold guard (`POPB_HOLD_REGRESSION`: stop if WHS < 0) | WHS is **0.000** on this roll, so the guard matters here more than on any G5D roll |
| `route_design -preserve`, then reports | as recorded |
| `write_bitstream` **only if WNS ≥ 0 and WHS ≥ 0** (`POPB_CLOSED`) | the script's own gate |

**What is deliberately NOT added:**
* `cascade_height` (the memory's BRAM/URAM-cascade lesson). It is a synthesis
  attribute on the RTL's memories, so it would need a re-synthesis and is
  excluded by ruling B1.
* Moving the clock root. That is a constraint change beyond the recorded
  recipe, and G5D §10.1 used only the one `X2Y2` file.
* Pblocks: they are excluded, and G5D priced them at −0.879 ns.

**Expectation, stated honestly:** G5D measured this playbook at +0.000 on both
of its positions (§6, §8.4), because its residual owner was a URAM → DSP hop
with 1.7 ns of cell delay. This roll's owner is a register fan-out path, which
is the kind of path `phys_opt` replication does address. So this is a real try,
not only a confirmation step. G5D's playbook runs took 1 h 15 m (log 119) and
53 m (log 148), so **expect about 14:15 + 1 h ≈ 15:15–15:30**.

**Launch (`n46_T3_playbook_ENDl.log`, in flight).** Started
**2026-09-25T14:10:14-06:00** via `timeout 30 ssh -f snoke … setsid nohup bm_run.sh n46_T3_playbook_ENDl.log bash -c "source …/settings64.sh >/dev/null && exec vivado -mode batch -nolog -nojournal -source evidence/qwen9b/g5/g5b_physopt_playbook.tcl -tclargs <src dcp above> /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_042_bm1_po3_ENDl_playbook"`.
* **Verified at 14:18:45.** The Vivado pid is 2849983. The out dir was
  created fresh at 14:10 (`reports/`). The log shows
  `POPB_SRC: …/out_build_042_bm1_ckr2b_ExtraNetDelay_low/…/bd_wrapper_postroute_physopt.dcp`
  and `POPB_PASS0: WNS=-0.124 WHS=0.000` (the checkpoint reads back §10.1's
  numbers), with no FATAL or ERROR.
* **Tree stamp:** `d778d91+dirty`, naming `BM1_T3_BUILD.md`. This is the same
  NFS stat artifact as n38 (§7). The file had been committed seconds earlier in
  `d778d91`, and `git status --porcelain --untracked-files=no` was empty right
  after. It is not an input of this run.
* **ETA:** about 15:15–15:30 (G5D's playbook runs took 53 m to 1 h 15 m).
  Result lines: `POPB_AFTER_<directive>`, `POPB_FINAL`, and
  `POPB_CLOSED` / `POPB_NOT_CLOSED`.

## 10.3 SPREAD 2, complete table (n45, n47, n54)

| roll (ckr2 XDC, full recipe) | WNS | TNS | fail setup EP | WHS | hold / PW fail | design-WNS owner | cite |
|---|---|---|---|---|---|---|---|
| `ExtraNetDelay_low` | **−0.124** | −94.611 | 2,308 | 0.000 | 0 / 0 | aclk: `u_attn` `og_i_reg[1]_rep__4` → `o_g8_reg[18][15]` (output gather) | `evidence/qwen9b/bm/n45_T3_spread2_score_ENDl.log:29`, `evidence/qwen9b/bm/n45_T3_spread2_score_ENDl.log:68` |
| `AltSpreadLogic_low` | −0.408 | −2,177.148 | 17,741 | 0.000 | 0 / 0 | `mmcm_clkout0_1`: `mvchan_3` streamer `f_wr_reg[5]` → engine `scales_q_reg[17][0]/CE`; aclk −0.370 on `u_alu` `op_q` → `ps_rnd` | `evidence/qwen9b/bm/n47_T3_spread2_score_ASLl_EPPO.log:30`, `evidence/qwen9b/bm/n47_T3_spread2_score_ASLl_EPPO.log:61` |
| `ExtraPostPlacementOpt` | −0.490 | −2,970.404 | 21,173 | 0.000 | 0 / 0 | aclk: `u_dn` `row_reg[1]` → `g_lane[115].p2_p_reg[115]_i_9_psdsp_5/D` (DN lane DSP input) | `evidence/qwen9b/bm/n47_T3_spread2_score_ASLl_EPPO.log:96`, `evidence/qwen9b/bm/n47_T3_spread2_score_ASLl_EPPO.log:135` |
| `EarlyBlockPlacement` | −0.507 | −1,957.363 | 14,709 | 0.000 | 0 / 0 | aclk: `u_dn` `row_reg[0]` → `g_lane[66].p2_p_reg[66]_i_16_psdsp/D` (DN lane DSP input); all four MIG UI clocks negative (`clkout0` −0.244) | `evidence/qwen9b/bm/n54_T3_spread2_score_EBP.log:29`, `evidence/qwen9b/bm/n54_T3_spread2_score_EBP.log:68` |

In n47, 0 printed paths touch `seq_0`, the counters or `mv_busy_bm` on either
roll (bounded: the scoring logs see only what `report_timing_summary` prints, the worst setup and hold path per clock group, 144 `Slack` lines per report, because `synth/scripts/full_impl.tcl:74` runs it without `-max_paths`; the complete check is §12.3a, on the best roll only). **EPPO's bitgen DRC did not recur.** `write_bitstream` ran,
`BUILD_OK` is at `evidence/qwen9b/bm/n47_T3_spread2_score_ASLl_EPPO.log:88`,
and the bit (51,463,577 bytes, 15:30:00) is at
`evidence/qwen9b/bm/n47_T3_spread2_score_ASLl_EPPO.log:75`. So G5D #7's
RTSTAT-11 did not happen on this netlist.

### 10.4 `ckr2b_EarlyBlockPlacement` (`n54_T3_spread2_score_EBP.log`, 2026-09-26T10:03:34, rc 0)

**Freshness:** the artifacts are dated 2026-09-25, after the spread's 08:49:49
launch: postroute_physopt dcp 16:34:51, bit 16:44:07, timing_summary
16:52:43 (`evidence/qwen9b/bm/n54_T3_spread2_score_EBP.log:10`,
`evidence/qwen9b/bm/n54_T3_spread2_score_EBP.log:8`,
`evidence/qwen9b/bm/n54_T3_spread2_score_EBP.log:12`). The fullimpl log shows
`PBLOCK_COUNT: 0`, `WHS_GATE: OK whs=0.000`, `BUILD_OK` and 0 ERROR lines.
Every `DRC finished` line in the fullimpl log, bitgen's included, reads
**0 Errors** (`evidence/qwen9b/bm/n54_T3_spread2_score_EBP.log:78`).

WNS is **−0.507**, TNS −1,957.363, with 14,709 failing setup endpoints; WHS is
0.000, with 0 failing hold and 0 failing pulse-width endpoints
(`evidence/qwen9b/bm/n54_T3_spread2_score_EBP.log:29`). **MISS.** The aclk
worst path is `u_dn/row_reg[0]` → a DN lane DSP input
(`evidence/qwen9b/bm/n54_T3_spread2_score_EBP.log:70`). All four MIG UI
clocks are negative, from −0.023 to −0.244, on `mvchan_*` engine/streamer
paths. 0 printed paths touch `seq_0`, the counters or `mv_busy_bm`
(`evidence/qwen9b/bm/n54_T3_spread2_score_EBP.log:71`) (bounded: the scoring logs see only what `report_timing_summary` prints, the worst setup and hold path per clock group, 144 `Slack` lines per report, because `synth/scripts/full_impl.tcl:74` runs it without `-max_paths`; the complete check is §12.3a, on the best roll only). The directive aimed
at the URAM → DSP owner did not help. It placed the blocks early and landed
0.383 ns behind `ExtraNetDelay_low`.

### 11.1 The playbook's result: NOT CLOSED, +0.000 (`n46_T3_playbook_ENDl.log`, rc 0, 14:10:14 → 15:53:09, 1 h 43 m)

| step | WNS | WHS | cite |
|---|---|---|---|
| in (`ckr2b_ExtraNetDelay_low`) | −0.124 | 0.000 | `evidence/qwen9b/bm/n46_T3_playbook_ENDl.log:100` |
| AlternateReplication | −0.124 | 0.000 | `evidence/qwen9b/bm/n46_T3_playbook_ENDl.log:220` |
| AggressiveFanoutOpt | −0.124 | 0.000 | `evidence/qwen9b/bm/n46_T3_playbook_ENDl.log:286` |
| Explore | −0.124 | 0.000 | `evidence/qwen9b/bm/n46_T3_playbook_ENDl.log:391` |
| AggressiveExplore | −0.124 | 0.000 | `evidence/qwen9b/bm/n46_T3_playbook_ENDl.log:473` |
| `route_design -preserve` (`POPB_FINAL`) | **−0.124** | **0.000** | `evidence/qwen9b/bm/n46_T3_playbook_ENDl.log:863` |

The log ends `POPB_NOT_CLOSED` (`evidence/qwen9b/bm/n46_T3_playbook_ENDl.log:891`).
No bitstream was written, and the hold guard never fired. That is the same
+0.000 G5D measured on both of its playbook runs (G5D §6, §8.4). §11
expected a fan-out owner to respond to replication, and that expectation was
wrong. The `og_i_reg[1]_rep__4` source is already a replica, and the
directives found nothing further to replicate or move.

## 12. §4.3 STEP 3: HAND-OFF TO THE USER (decision D6, spec `docs/superpowers/specs/2026-09-24-board-idle-counters-design.md:530`, `docs/superpowers/specs/2026-09-24-board-idle-counters-design.md:705`)

**Nothing further has been launched.** The campaign's bar (user decision 5,
G5D §10: WNS ≥ 0, WHS ≥ 0, 0 failing endpoints, no waiver) has **not** been
met on any of the nine implementations of this netlist.

### 12.1 The best roll

`synth/out_build_042_bm1_ckr2b_ExtraNetDelay_low` (bit and dcp in its
`proj/stage1.runs/impl_1/`) scores WNS **−0.124**, TNS −94.611, **2,308**
failing setup endpoints, WHS **0.000**, 0 failing hold and 0 failing
pulse-width endpoints (`evidence/qwen9b/bm/n45_T3_spread2_score_ENDl.log:29`).
The playbook did not move it (`evidence/qwen9b/bm/n46_T3_playbook_ENDl.log:863`).

Its failing classes:
* `xdma_0_axi_aclk`: −0.124 on 2,214 EP. The worst path is `layer_0/u_core/u_attn/og_i_reg[1]_rep__4` →
  `u_attn/o_g8_reg[18][15]` (`evidence/qwen9b/bm/n45_T3_spread2_score_ENDl.log:68`),
  the attention output gather.
* `mmcm_clkout0` (MIG ch0 UI, 300 MHz): −0.010 on 94 EP. The worst path starts
  at `bd_i/mvchan_0/inst/u_chan/u_streamer/f_rd_reg[0]` (`evidence/qwen9b/bm/n45_T3_spread2_score_ENDl.log:48`).
* Every other named clock meets timing.

### 12.2 Everything tried (all on snoke, the same netlist `9b588e78`, with no RTL, pblock or constraint change beyond the recorded ckr2 recipe)

| step | wall time | result | cite |
|---|---|---|---|
| base build (`launch_build.sh`, default recipe) | 4 h 03 m (23:16:09 → 03:19:04) | −0.687 / 36,472 EP | `evidence/qwen9b/bm/n24_T3_launch_build_042_bm1.log:1`, `evidence/qwen9b/bm/n24_T3_launch_build_042_bm1.log:19`, `evidence/qwen9b/bm/n36_T3_base_roll_042_bm1.log:46` |
| spread 1 (ckr2: ETO, ASL_high, ASL_medium, END_high) | 7 h 13 m (03:23:19 → 10:36:15) | −0.173 / −0.385 / −0.344 / −0.554 | `evidence/qwen9b/bm/n38_T3_launch_po2_ckr2.log:1`, `evidence/qwen9b/bm/n38_T3_launch_po2_ckr2.log:13`, `evidence/qwen9b/bm/n40_T3_spread1_score_ETO_ASLh.log:29`, `evidence/qwen9b/bm/n40_T3_spread1_score_ETO_ASLh.log:95`, `evidence/qwen9b/bm/n43_T3_spread1_score_ASLm.log:29`, `evidence/qwen9b/bm/n44_T3_spread1_score_ENDh.log:29` |
| spread 2 (ckr2b: END_low, ASL_low, EPPO, EBP) | 8 h 05 m (08:49:49 → 16:55:01, `evidence/qwen9b/bm/n41_T3_launch_po2_ckr2b.log:1`, `evidence/qwen9b/bm/n41_T3_launch_po2_ckr2b.log:12`) | −0.124 / −0.408 / −0.490 / −0.507 | `evidence/qwen9b/bm/n45_T3_spread2_score_ENDl.log:29`, `evidence/qwen9b/bm/n47_T3_spread2_score_ASLl_EPPO.log:30`, `evidence/qwen9b/bm/n47_T3_spread2_score_ASLl_EPPO.log:96`, `evidence/qwen9b/bm/n54_T3_spread2_score_EBP.log:29` |
| phys_opt playbook on END_low | 1 h 43 m (14:10:14 → 15:53:09) | −0.124 → −0.124 (+0.000), `POPB_NOT_CLOSED` | `evidence/qwen9b/bm/n46_T3_playbook_ENDl.log:891` |

**The `+dirty` tree stamps on n47, n48 and n52** (`=== dirty: ?? tight_setup_hold_pins.txt`)
come from a Vivado route artifact. The playbook run (n46) wrote
tight_setup_hold_pins.txt into the repo root, its working directory. That
file is not an input of any run, and it has since been moved into
`synth/out_build_042_bm1_po3_ENDl_playbook/`. Nothing tracked was dirty.

### 12.3 What the failing paths are, and what they are not

Across the nine rolls, the design-WNS owners are:
* `layer_0` `u_dma` on the base roll: `x_kind_reg` → the `fmem` LUTRAM (`evidence/qwen9b/bm/n36_T3_base_roll_042_bm1.log:106`, `evidence/qwen9b/bm/n36_T3_base_roll_042_bm1.log:107`)
* `matvec_engine` on the MIG UI clock `mmcm_clkout0_1` for END_high (−0.554, `mvchan_3` `xline_q0`, `evidence/qwen9b/bm/n44_T3_spread1_score_ENDh.log:60`, `evidence/qwen9b/bm/n44_T3_spread1_score_ENDh.log:62`) and ASL_low (−0.408, `mvchan_3` `scales_q` CE, `evidence/qwen9b/bm/n47_T3_spread2_score_ASLl_EPPO.log:61`, `evidence/qwen9b/bm/n47_T3_spread2_score_ASLl_EPPO.log:63`)
* on the other six rolls, `layer_0` paths on `xdma_0_axi_aclk`:
  * the DN cache URAM → `u_dn` lane DSP (`evidence/qwen9b/bm/n40_T3_spread1_score_ETO_ASLh.log:70`, `evidence/qwen9b/bm/n40_T3_spread1_score_ETO_ASLh.log:136`)
  * the KV cache URAM cascade address (`evidence/qwen9b/bm/n43_T3_spread1_score_ASLm.log:70`)
  * (`u_alu` is the aclk worst path, not the design WNS, on END_high and ASL_low: `evidence/qwen9b/bm/n44_T3_spread1_score_ENDh.log:70`, `evidence/qwen9b/bm/n47_T3_spread2_score_ASLl_EPPO.log:71`)
  * the `u_dn` lane DSP input (`evidence/qwen9b/bm/n47_T3_spread2_score_ASLl_EPPO.log:137`)
  * the `u_attn` output gather (`evidence/qwen9b/bm/n45_T3_spread2_score_ENDl.log:70`)

Some are `matvec_engine` CE/`xline_q0` paths on the MIG UI clocks
(`evidence/qwen9b/bm/n44_T3_spread1_score_ENDh.log:62`,
`evidence/qwen9b/bm/n47_T3_spread2_score_ASLl_EPPO.log:63`). The rest are
vendor MIG internals (`evidence/qwen9b/bm/n47_T3_spread2_score_ASLl_EPPO.log:51`).

**Bounded check, all nine rolls:** no path *printed* in any of the nine reports
touches `seq_0`, the counters or the `mv_busy_bm` nets, and each scoring log's
counter-touch count is 0. That covers only the worst setup and hold path per
clock group, 144 `Slack` lines per report. `report_timing_summary` runs without
`-max_paths` in `synth/scripts/full_impl.tcl:74`, `synth/scripts/build.tcl:62`
and `evidence/qwen9b/g5/g5b_physopt_playbook.tcl:52`. It is **not** a
statement about all failing endpoints.

### 12.3a The complete check on the best roll (`evidence/qwen9b/bm/n57_T3_fix1_exoneration_ENDl.log`, 2026-09-26T10:11 → 10:20:46, rc 0)

This is a read-only Vivado batch session on snoke:
`evidence/qwen9b/bm/bm1_exoneration.tcl` (committed in `c5a0305` before its
first use) via `bm_run.sh`. It runs `open_checkpoint` on
`synth/out_build_042_bm1_ckr2b_ExtraNetDelay_low/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp`,
then timing queries and `report_timing` only. Report files went to the fresh
`synth/out_build_042_bm1_po3_ENDl_exoneration/`; nothing was written into any
existing out dir. The sets:
* the primitive cells under bd_i/seq_0 (`evidence/qwen9b/bm/bm1_exoneration.tcl:13`): **8,315** cells (`evidence/qwen9b/bm/n57_T3_fix1_exoneration_ENDl.log:96`)
* the nets matching mv_busy_bm (`evidence/qwen9b/bm/bm1_exoneration.tcl:14`): **28** nets, from the four BD nets down both hierarchies (`evidence/qwen9b/bm/n57_T3_fix1_exoneration_ENDl.log:98`)

| query | result | cite |
|---|---|---|
| all failing setup paths, one per endpoint, capped at 5,000 (`evidence/qwen9b/bm/bm1_exoneration.tcl:27`) | **2,308** paths. That is below the 5,000 cap, so complete, and equals the design's 2,308 failing endpoints (`evidence/qwen9b/bm/n45_T3_spread2_score_ENDl.log:29`) | `evidence/qwen9b/bm/n57_T3_fix1_exoneration_ENDl.log:164` |
| … of those, STARTPOINT_PIN or ENDPOINT_PIN inside `bd_i/seq_0/*` | **0 of 2,308** | `evidence/qwen9b/bm/n57_T3_fix1_exoneration_ENDl.log:165` |
| failing setup paths through the 28 nets | **0** | `evidence/qwen9b/bm/n57_T3_fix1_exoneration_ENDl.log:166` |
| failing setup paths to / from the seq_0 cells | **0 / 0** | `evidence/qwen9b/bm/n57_T3_fix1_exoneration_ENDl.log:167`, `evidence/qwen9b/bm/n57_T3_fix1_exoneration_ENDl.log:168` |
| worst setup `-to` / `-from` seq_0 | **+0.037** / **+0.037**: `u_seq/rec_reg[7]` → `u_seq/tcnt_seq_reg[31]`, the sequencer's pre-existing loop counter, not a BM1 counter | `evidence/qwen9b/bm/n57_T3_fix1_exoneration_ENDl.log:169`, `evidence/qwen9b/bm/n57_T3_fix1_exoneration_ENDl.log:189` |
| worst setup `-through` mv_busy_bm | **+1.340**: `mvchan_0/…/mv_busy_bm_reg` → `seq_0/…/bm_mvb_q1_reg[0]` | `evidence/qwen9b/bm/n57_T3_fix1_exoneration_ENDl.log:1910` |
| all failing hold paths, same query | **0** failing hold paths design-wide | `evidence/qwen9b/bm/n57_T3_fix1_exoneration_ENDl.log:2164` |
| worst hold `-to` / `-from` / `-through` | **+0.015** / **+0.011** / **+0.126** | `evidence/qwen9b/bm/n57_T3_fix1_exoneration_ENDl.log:2169`, `evidence/qwen9b/bm/n57_T3_fix1_exoneration_ENDl.log:2705`, `evidence/qwen9b/bm/n57_T3_fix1_exoneration_ENDl.log:3243` |

**Complete result: on the best roll, no failing setup or hold endpoint starts
or ends in `seq_0` or passes through a `mv_busy_bm` net.** The counters' own
paths meet timing. Their crossing has +1.340 ns of setup slack. The thinnest
`seq_0` margin (+0.037) belongs to a pre-BM1 register. The −0.124 roll's
violations cannot corrupt the counters' values *through the counters' own
paths*. Whether a violating `layer_0` path upsets what the sequencer does
(and so what it counts) is a separate question, the same one that decides
whether the tokens are right (§12.4(c)). This check was run on
`ckr2b_ExtraNetDelay_low` only. The other eight rolls carry only the bounded
statement above.

**(I) `layer_0`'s netlist is very likely unchanged, but that is inferred, not proven.** Its RTL did not change between the
shipped tree `c973c18` and `9b588e7`: the only RTL files that differ are
`rtl/matvec_chan.sv`, `rtl/matvec_chan_ipi.v`, `rtl/seq_unit.sv` and `rtl/seq_unit_ipi.v`
(`evidence/qwen9b/bm/n48_T3_incr_feasibility.log:57`). Its out-of-context
synthesis report is identical, byte for byte, apart from the header
(`util_body_md5=069979d67696` on both, `evidence/qwen9b/bm/n48_T3_incr_feasibility.log:30`,
`evidence/qwen9b/bm/n48_T3_incr_feasibility.log:31`; 116,093 LUTs / 61,470
FFs / 1,840 DSPs on both, `evidence/qwen9b/bm/n48_T3_incr_feasibility.log:47`,
`evidence/qwen9b/bm/n48_T3_incr_feasibility.log:50`). The OOC checkpoints'
**bytes differ**, however: the dcp md5 and size differ at
`evidence/qwen9b/bm/n48_T3_incr_feasibility.log:30` and
`evidence/qwen9b/bm/n48_T3_incr_feasibility.log:31`. So cell-name identity,
which is what option (a)'s reuse depends on, is **unverified**. **Reading (I):** the
counters (`seq_0` +187 LUT / +415 FF, §6) and the one extra flop per `mvchan`
reseed the placer, and it lands the unchanged `layer_0` differently. The
shipped 0.000 was one roll of ten, and the only independent placement carrying the clock-root
file (`evidence/qwen9b/g5/G5D_TIMING.md:1172`; row 10, the playbook run on it, also carried the file, `evidence/qwen9b/g5/G5D_TIMING.md:1173`). No roll here reproduced that
placement.

### 12.4 Options, with costs (the user decides; the order is the controller's, and it is not a ranking)

**(a) Incremental implementation against the shipped closing roll's checkpoint (D6 "new tooling").**
* **The reference.** G5D §9.2 names the shipped checkpoint
  `synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp`,
  288,126,447 bytes (`evidence/qwen9b/g5/G5D_TIMING.md:1239`). **It is on disk,
  byte-size identical, mtime 2026-09-07 20:34:57**
  (`evidence/qwen9b/bm/n48_T3_incr_feasibility.log:22`). Its roll printed
  `TIMING: WNS=0.000 WHS=0.001 … AltSpreadLogic_high … fable5_clockroot_9b.xdc`
  (`evidence/qwen9b/bm/n48_T3_incr_feasibility.log:25`), and its project was
  created at `c973c18a` (`evidence/qwen9b/bm/n48_T3_incr_feasibility.log:27`;
  VERSION `evidence/qwen9b/g5/G5D_TIMING.md:1234`).
  * It is **not** `out_build_041/…/impl_1/bd_wrapper_routed.dcp`, which is the
    default-recipe base roll (−0.859, `evidence/qwen9b/g5/G5D_TIMING.md:1164`).
  * Spec §4.3 named the ckr2 roll's `bd_wrapper_routed.dcp` (20:00:43,
    `evidence/qwen9b/bm/n48_T3_incr_feasibility.log:23`). That is the
    pre-post-route-phys_opt checkpoint. The **signoff** checkpoint is the
    postroute_physopt one.
  * **One trap:** the shipped VERSION CSR value `c973c18a` is baked into
    `csr_0`'s constants. The new build's is `9b588e78`
    (`evidence/qwen9b/bm/n48_T3_incr_feasibility.log:29`), so those few cells
    differ by design and would be re-implemented.
* **How it would work (unverified, from memory of UG904).** Vivado 2024.2 runs `read_checkpoint -incremental <ref.dcp>`
  after `opt_design`. In project mode that is `set_property INCREMENTAL_CHECKPOINT <ref.dcp> [get_runs impl_1]`.
  Vivado then matches the new design's cells and nets **by name** against the
  reference, reuses the placement and routing of the matches, and places and
  routes only what did not match.
  * (I) The matchable part is probably large. `layer_0` and the vendor IPs
    have the same RTL and the same utilization body. Their OOC dcp bytes
    differ, and cell-name identity is unverified (§12.3). The `bd_layer_0_0`, `bd_xdma_0_0` and `bd_ddr4_0_0`
    OOC utilization bodies are identical (`evidence/qwen9b/bm/n48_T3_incr_feasibility.log:30`, `evidence/qwen9b/bm/n48_T3_incr_feasibility.log:31`, and the xdma/ddr4 rows below them).
  * `seq_0` (`evidence/qwen9b/bm/n48_T3_incr_feasibility.log:40`,
    `evidence/qwen9b/bm/n48_T3_incr_feasibility.log:41`) and the four
    `mvchan`s (`evidence/qwen9b/bm/n48_T3_incr_feasibility.log:32`,
    `evidence/qwen9b/bm/n48_T3_incr_feasibility.log:33`) differ. The `mvchan`
    difference is one flop each, but their OOC synthesis reruns, so their
    cell *names* may shift.
  * The reference's own `phys_opt` replicas (`*_rep*`, `*_replica*`) have no
    counterpart before `phys_opt` runs, so they drop out of the match.
* **Unverified behaviour (from memory).** I could not verify the fallback
  behaviour in the documentation this session: the Vivado MCP
  `vivado_doc_search` timed out after 30 min and the local guide index had no
  entry. So the following comes from memory of UG904's
  incremental-implementation chapter and is marked **(unverified)**:
  * The flow reports its cell/net/pin reuse (`report_incremental_reuse`).
  * In the default incremental mode it reverts to a standard placement when
    reuse is too low (the controller's figure is about 85 %), or when the
    reference does not meet timing well enough.
  * Timing-critical paths that fail in the new design may be re-placed rather
    than reused.

  The reference meets timing (WNS 0.000), and the changed fraction is roughly
  `seq_0` ≈ 4 k of about 310 k LUTs (§6) plus the `mvchan` renames, so reuse
  above 90 % is plausible. **It is not measured.**
* **Cost.**
  * Tooling: a new script beside `synth/scripts/full_impl.tcl` (not an edit of
    it, which is recorded), about 10 lines, setting `INCREMENTAL_CHECKPOINT`
    and the ckr2 XDC, with the same `TIMING:`/`WHS_GATE` lines.
  * Wall time: **estimated** at about 2–4 h for one run, not measured, with no spread needed.
  * Risk 1: a low-reuse fallback turns it into one more ordinary roll.
  * Risk 2: the reused shipped placement puts `seq_0`'s new counters wherever
    there is room, including on the SLR crossing (`mvchan_0` → `seq_0`).
  * **Stake:** if it lands at 0.000, the shipped `layer_0` placement, the one
    that closed, is what the board runs.

**(b) Another four-directive spread.** It costs about 5.5–7.5 h wall time
(spread 1 took 7 h 13 m). It is placement luck: the two spreads' best rolls
were −0.173 and −0.124, and the eight full-recipe rolls span −0.124 … −0.554.
No directive in either spread reached zero, and G5D's own campaign reached zero
on exactly one independent placement of ten (its row 10 is the playbook run on that same placement).

**(c) Accept the −0.124 roll for the MEASUREMENT only. This is the user's
call, not a recommendation.**
* **What violates:** 2,214 aclk endpoints led by the `u_attn` output gather,
  and 94 `mmcm_clkout0` endpoints in `mvchan_0`'s streamer (§12.1). These are
  compute and datapath paths in `layer_0` and a matvec channel. `seq_0` and
  the counters are not on them: **0 of 2,308** failing endpoints start or end in
  `seq_0`, and 0 pass through `mv_busy_bm` (the complete check, §12.3a).
* **What that means for the result.** Violating paths risk wrong
  arithmetic, which would show up as wrong tokens in the board run's own
  token-identity check. The counters count sequencer events, and the TB
  measured their per-step schedule as exact and identical across four seeds
  (BM1-T1). The spec notes the board's run-to-run spread comes from DDR
  refresh, not the TB (`docs/superpowers/specs/2026-09-24-board-idle-counters-design.md:608`).
* **What it costs.** The campaign's bar (decision 5) is **unrelaxed**, and a
  measurement-only bitstream with a stated negative WNS is something the user
  has never done, and the spec does not recommend it
  (`docs/superpowers/specs/2026-09-24-board-idle-counters-design.md:534`). Taking it is a waiver, and waivers are the user's alone.

**(d) Ruling B1's excluded items.** They were excluded because any RTL change
voids the TB gate that proved the counters on this exact RTL
(`.superpowers/sdd/2026-09-24-overlap/task-BM1-T3-brief.md:4`), and each
would need that gate re-run (4 seeds, about 1 h on snoke) plus a fresh base
build and spread (about 11 h).
* **Drop the synchronous reset on `bm_mvb_q1/q2`** (`rtl/seq_unit.sv:1413`).
  This gives placer freedom on the SLR crossing. It is cheap in RTL, but the
  crossing is not on any failing path here (complete check: its worst setup
  slack is +1.340, §12.3a), so it is unlikely to move WNS.
* **D6's extra pipeline flop on the crossing**
  (`docs/superpowers/specs/2026-09-24-board-idle-counters-design.md:534`).
  The reasoning is the same: the crossing has +1.340 ns of setup slack, and 0
  failing endpoints pass through it on the best roll (§12.3a). A flop there
  adds latency to a level that is counted every cycle, which the TB gate would
  need to re-prove, and it does not touch any failing path.
* **`cascade_height` on the KV/DN cache URAMs.** G5D used `cascade_height = 2`
  on `layer_chan`'s scratchpad (`rtl/layer_chan.sv:503`, measured in
  `evidence/qwen9b/g5/G5D_TIMING.md:250`). ASL_medium's worst path ends on a
  KV URAM `CAS_IN_ADDR` (`evidence/qwen9b/bm/n43_T3_spread1_score_ASLm.log:70`),
  so it would address that one owner. It changes `layer_0`'s netlist, which
  gives up option (a)'s reuse.
* **A G5C-style RTL round on the attention output gather** (pipeline the
  `og_i` → `o_g8` fan-out). G5D priced its last RTL round at +0.091 ns
  (`evidence/qwen9b/g5/G5D_TIMING.md:374`). It needs a design note, the TB,
  and a full build campaign, which is a task, not a step.
