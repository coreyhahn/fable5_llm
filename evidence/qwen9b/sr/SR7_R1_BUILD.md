# SR7 — the R1 build: incremental implementation against the shipped signoff, scored to G5D §10

Spec: `docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md` §4.3.
Brief: `.superpowers/sdd/2026-09-27-seq-rtl/task-SR7-brief.md` (the SR7 task text plus four controller addenda).
Every log below is under `evidence/qwen9b/sr/`, written on snoke by `evidence/qwen9b/sr/sr_run.sh`
(block n700–n799). No board action: nothing was programmed, no CSR was read, no lock was taken.

## 0. Verdict: SIGNED OFF (rung 1, the incremental run) — pending its own load ruling (Q9)

`build_044_r1_incr` — the R1 netlist (the FENCE channel mask + the BM1 counters), synthesised from the
committed tree `e3c2ff1` (VERSION **e3c2ff1e**), implemented incrementally against the shipped signoff
checkpoint — **meets G5D §10's unrelaxed bar** (`evidence/qwen9b/g5/G5D_TIMING.md:1255`):

* design WNS **+0.001**, WHS **+0.001**; **0** failing setup of 1,321,099, **0** failing hold of 1,317,963,
  **0** failing pulse-width of 392,950 endpoints (`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:82`);
* every tracked clock meets timing (`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:93-98`, §2);
* the clock-root check passed on the routed checkpoint **before** final_verify: CLOCKROOT_SLR_OK SLR0, rc 0
  (`evidence/qwen9b/sr/n722_SR7_clockroot_check_build_044_r1_incr.log:266`, `evidence/qwen9b/sr/n722_SR7_clockroot_check_build_044_r1_incr.log:270`);
* `synth/scripts/final_verify.tcl` then: FV_WNS 0.001, FV_WHS 0.001, 0 / 0 failing, FV_OK
  (`evidence/qwen9b/sr/n723_SR7_final_verify_build_044_r1_incr.log:94-108`, `evidence/qwen9b/sr/n723_SR7_final_verify_build_044_r1_incr.log:143`);
* DRC: bitgen and opt DRC 0 Errors (`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:59-60`); the routed
  `report_drc` has 13 rule rows and 0 Error / Critical Warning rows (`evidence/qwen9b/sr/n728_SR7_drc_table_build_044_r1_incr.log:26-27`);
* no waiver.

**Rung reached: 1** (the incremental run). The fallback ladder (§6) was not needed and none of it ran.
SR7C (the new clock domain) and any UI cut were not touched. The bitstream is written and hashed (§4), and **not loaded** here (SR8 loaded it once on 2026-09-29 under the user's Q9 ruling and restored build_041, `evidence/qwen9b/sr/SR8_R1_BOARD.md`).

A second incremental run of the same netlist, with SR1's routed checkpoint as the reference, **also closes**
(0.000 / +0.001, 0 failing; §3). It is kept as an alternate. Its bitstream carries the **same VERSION**, and
only its sha256 tells it apart.

## 1. Preconditions and launch

### 1.1 Preflight (`evidence/qwen9b/sr/n700_SR7_preflight.log`, 06:11, rc 0)

* HEAD `e3c2ff1` descends from `a9cef01` (`evidence/qwen9b/sr/n700_SR7_preflight.log:25-26`). The tree was clean
  apart from the preflight's own log (`evidence/qwen9b/sr/n700_SR7_preflight.log:27`).
* The rtl/ delta from SR3's commit `5c369c2` to HEAD is comment-only: 0 non-comment lines
  (`evidence/qwen9b/sr/n700_SR7_preflight.log:33`).
* SR1's verdict is CLOSES (`evidence/qwen9b/sr/n700_SR7_preflight.log:37`), and SR5b's is GREEN, "the model held"
  (`evidence/qwen9b/sr/n700_SR7_preflight.log:40`). SR3–SR6 are committed.
* No other Vivado job was running (`evidence/qwen9b/sr/n700_SR7_preflight.log:48`), and the load was 1.46 on 48 cores
  (`evidence/qwen9b/sr/n700_SR7_preflight.log:49`). The three out dirs were free and the highest build was 043
  (`evidence/qwen9b/sr/n700_SR7_preflight.log:56-59`).
* The inputs were hashed (`evidence/qwen9b/sr/n700_SR7_preflight.log:61-63`):
  * the shipped reference: 84b42d2a…, the same bytes SR1 used;
  * the SR1 routed dcp: 68d5eb71…;
  * the clock-root XDC: 72c3d197…, unchanged since BM1/SR1.
* Tool: vivado v2024.2 (`evidence/qwen9b/sr/n700_SR7_preflight.log:71`).
* **The incr_impl.tcl fixes the addendum asked for were already in the tree.** SR1's fix round 1 (`6f92fdc`)
  had moved the reuse hook to place_design's TCL.POST and added the REQUESTED/EFFECTIVE directive print. Both
  are present at launch, and both worked in this run (§2.3). No script change was needed.
* The controller's step-1 ruling ("attempt the incremental step at all"): SR1 reused 99.35 %, so there was
  no reason to skip it, and it was attempted.

### 1.2 The netlist (`evidence/qwen9b/sr/n701_SR7_launch_build_044_r1.log`)

`synth/scripts/launch_build.sh build_044_r1` started at 06:11:47 on tree `e3c2ff1`. It stamped
`=== create_project (e3c2ff1e) ===` (`evidence/qwen9b/sr/n701_SR7_launch_build_044_r1.log:6`), so **VERSION = e3c2ff1e**.
* create_project reported 0 ERROR. Its 11 CRITICAL WARNINGs are a set identical to build_042_bm1's, and it has
  87 WARNINGs (`evidence/qwen9b/sr/n709_SR7_launch_verify.log:18-20`).
* The one "CSR VERSION set-failure" that count reports (`evidence/qwen9b/sr/n709_SR7_launch_verify.log:21`) is
  the echoed source line of `synth/scripts/create_project.tcl`, not a printed WARN. The same two echo lines
  appear in build_042_bm1's create.log. No `WARN: could not set` line was printed.
* synth_1 finished at 06:32:50.

**A self-inflicted loss: the base (default-recipe) roll was killed.** The plan launches the incremental run
"as soon as synth_1 is complete". I launched it at 06:33:45, while the base build's impl_1 had just started
in the same `proj/` (06:33:26). `synth/scripts/launch_incr.sh` rsyncs that `proj/`, and the copied
`impl_1/.vivado.begin.rst` carried the running base process's PID and host. The copy's `reset_run impl_1`
then killed the base implementation.
* The base runme.log ends `Killed`, and build_run.log shows impl_1 finishing and failing at 06:35:03
  (`evidence/qwen9b/sr/n712_SR7_base_roll_killed.log:27`, `evidence/qwen9b/sr/n712_SR7_base_roll_killed.log:31`).
* The second copy's reset found the process already gone: "Attempt to kill process failed"
  (`evidence/qwen9b/sr/n712_SR7_base_roll_killed.log:43`).
* The launcher exited rc 1 (`evidence/qwen9b/sr/n701_SR7_launch_build_044_r1.log:18`).
* Both incremental runs ran in their own dirs (`evidence/qwen9b/sr/n712_SR7_base_roll_killed.log:48-49`) and
  were unaffected. They had copied a complete synth_1, and their impl_1 was reset anyway.
* The base roll was only "one more data point" (plan step 2), not a rung. It was **not re-run**: a re-run
  would need a new out dir from a newer tree, which means a different VERSION.
* **Hazard for later rounds:** never launch_incr / launch_po2 from a `proj/` whose impl_1 is running.
  Wait for the base build's `=== DONE`, or copy before the impl launches.

### 1.3 The two incremental runs (`evidence/qwen9b/sr/n710_SR7_launch_incr_build_044_r1_incr.log`, `evidence/qwen9b/sr/n711_SR7_launch_incr_build_044_r1_incr_bm1ref.log`)

Both were launched at 06:33:45 with SR1's launcher and SR1's choices: place AltSpreadLogic_high,
TimingClosure, and the clock-root XDC implementation-only. **Both file arguments were absolute.**

| run | reference | launched → rc 0 | wall |
|---|---|---|---|
| `build_044_r1_incr` (the spec's run) | shipped signoff `out_build_041_ckr2_AltSpreadLogic_high/…/bd_wrapper_postroute_physopt.dcp` | 06:33:45 → 10:09:37 | 3 h 36 m |
| `build_044_r1_incr_bm1ref` (judgment option) | SR1's routed `out_build_043_incr_probe/…/bd_wrapper_postroute_physopt.dcp` | 06:33:45 → 10:07:31 | 3 h 34 m |

**Judgment call: the second reference ran concurrently, not after a miss.** The plan's step 3 names it as a
concurrent option if SR1 CLOSED (it did). The addendum calls it "the alternative reference for a second
attempt". Running it concurrently cost CPU only: snoke was otherwise idle, with 206 GB available at the 45-min check
(`evidence/qwen9b/sr/n713_SR7_incr_launch_verify.log`). It saved ~3.5 h had the first run missed. The spec's
run (the shipped reference) stays the primary.

**Launch verification at 45 min** (`evidence/qwen9b/sr/n713_SR7_incr_launch_verify.log`, 07:19):
* 0 ERROR in either run;
* the opt checkpoints were written at 07:16 / 07:15;
* Vivado 12-9151, TimingClosure, was in effect in both (`evidence/qwen9b/sr/n713_SR7_incr_launch_verify.log:26`, `evidence/qwen9b/sr/n713_SR7_incr_launch_verify.log:41`);
* the INCREMENTAL_CHECKPOINT properties named the right references (`evidence/qwen9b/sr/n713_SR7_incr_launch_verify.log:17`, `evidence/qwen9b/sr/n713_SR7_incr_launch_verify.log:32`).

(n702 is VOID: its script path was on the local scratchpad, which snoke cannot see, so it exited rc 127. n709 is the same check from the repo.)

## 2. `build_044_r1_incr` against the bar

### 2.1 Freshness

The launch was at 06:33:45. Every artifact and report post-dates it (`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:10-23`):
* routed dcp: 09:37:45
* postroute_physopt dcp: 09:41:18
* mmi: 09:41:28
* bit: 09:52:04
* timing_summary: 10:05:46
* drc: 10:09:21

The logs have 0 ERROR lines (`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:38`) and 0 Timing 38-282 messages (`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:41`).

**One CRITICAL WARNING**, which SR1's run did not have: `[Route 35-4475] 2 global clock net(s) has(have) incomplete placer guidance tree`
(`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:40`). The bm1ref run has the same warning for 1 net
(`evidence/qwen9b/sr/n721_SR7_score_build_044_r1_incr_bm1ref.log:40`). It is a router note about clock-net
placer guidance. Timing, DRC and the clock-root check are all clean on the result. Which nets it names was narrowed
by fix round 1 to two of three candidate clock nets, not named exactly (§7, §9 M-2; re-aimed by SR9, 2026-09-29). It is recorded, not waived.

### 2.2 Per clock (`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:82`, `:93-98`)

Setup WNS / WHS in ns, with failing endpoints. Comparands: SR1 (`evidence/qwen9b/sr/SR1_INCR_PROBE.md` §2.2) and the ship
(`evidence/qwen9b/g5/141_t14b_roll_ckr2_AltSpreadLogic_high.txt:7`).

| | bar | **build_044_r1_incr** | build_044_r1_incr_bm1ref | SR1 (build_043) | ship (build_041 ckr2) |
|---|---|---|---|---|---|
| design WNS / WHS | ≥ 0 / ≥ 0 | **+0.001 / +0.001** | 0.000 / +0.001 | 0.000 / +0.001 | 0.000 / +0.001 |
| failing setup / hold / PW EP | 0 / 0 / 0 | **0 / 0 / 0** | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| xdma_0_axi_aclk | ≥ 0 | **+0.001** (WHS +0.001) | 0.000 | 0.000 | 0.000 |
| mmcm_clkout0 (MIG ch0 UI) | ≥ 0 | **+0.012** (WHS +0.010) | +0.044 | +0.047 | +0.003 |
| mmcm_clkout0_2 (ch1) | ≥ 0 | **+0.035** (WHS +0.010) | +0.114 | +0.114 | +0.031 |
| mmcm_clkout0_3 (ch2) | ≥ 0 | **+0.023** (WHS +0.010) | +0.068 | +0.039 | +0.016 |
| mmcm_clkout0_1 (ch3) | ≥ 0 | **+0.026** (WHS +0.010) | +0.089 | +0.026 | +0.026 |
| pipe_clk | ≥ 0 | **+0.766** (WHS +0.011) | +0.766 | +0.766 | +0.766 |
| PBLOCK_COUNT | — | 0 (`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:34`) | 0 | 0 | 0 |

The bm1ref column is `evidence/qwen9b/sr/n721_SR7_score_build_044_r1_incr_bm1ref.log:86`, `:97-102`.
"All clocks" is carried by the design-wide endpoint counts (G5D §10).

**The binding path** is xdma_0_axi_aclk +0.001:
`layer_0/…/g_kvslot[1].mem_reg_uram_16/CLK` → `…/u_attn/g_lane[72].pv_p_reg[72]/DSP…/A[2]`
(`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:120-123`). That is the KV URAM → attention DSP hop
(ATTN_DSP) that bound the ship and SR1. **0 printed paths touch seq_0 or the counters**
(`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:124`), and 0 endpoints fail anywhere.

**seq_0's own margin** comes from final_verify's still-checked family `*seq_0*u_seq/*/D`, which is **+0.242**
(`evidence/qwen9b/sr/n723_SR7_final_verify_build_044_r1_incr.log:140`). The comparands:
* ship: +0.397 (`evidence/qwen9b/g5/G5D_TIMING.md:1031`)
* SR1: +0.307 (SR1 §2.2)
* the BM1 −0.124 roll: +0.037 (`evidence/qwen9b/bm/BM1_T3_BUILD.md:650`)

The R1 cone costs margin against SR1's netlist, but not near the bar.

The other still-checked families (`evidence/qwen9b/sr/n723_SR7_final_verify_build_044_r1_incr.log:137-141`):
* u_dn: +0.021
* u_dma: +0.056
* u_attn: +0.019
* the xline_q0 CE cone: +0.138

### 2.3 What the tool actually ran (the SR1 fix-round print, working)

`EFFECTIVE_DIRECTIVES` (`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:32`) shows:
* place: **Explore**;
* post-place phys_opt: UNNAMED (the 12-9151 override of AggressiveExplore);
* route: **Explore**;
* post-route phys_opt: AggressiveExplore;
* incr_override: yes.

The REQUESTED field alongside it is AltSpreadLogic_high / AggressiveExplore / Default / AggressiveExplore
(`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:33`). The tool's own messages agree
(`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:43-49`).

The estimates along the way (`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:47`, `:50-57`):
* post-placement WNS −0.038;
* the router's intermediate summaries between −0.035 and 0.000;
* the router's final estimate: **WNS +0.001 / WHS +0.001**.

Unlike SR1, the router's estimate already met the bar, with no one-net in-router rescue visible in the summary lines.

Vivado's stage times, incremental against the reference (`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:219-222`):

| stage | incremental | reference |
|---|---|---|
| read_checkpoint | 0:46 | — |
| place | 0:34 | 1:36 |
| post-place phys_opt | 0:04 | — |
| route | **0:30** | 0:55 |

SR1's route took 1:40. The wall time was 3 h 36 m, against SR1's 4 h 48 m. Snoke was quieter this time: the
load was 5–7 with two runs at the 45-min mark (`evidence/qwen9b/sr/n713_SR7_incr_launch_verify.log`).

## 3. Reuse

Flat, from Vivado's own pre-placed and routed reports (`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:142-144`, `:201-203`, `:236-243`):

| | pre-place (reused) | after route (current) | SR1 after route |
|---|---|---|---|
| cells | **99.78 %** of 767,287 | **99.58 %** | 99.35 % |
| nets | 99.50 % | 98.16 % | 96.86 % |
| pins | 99.61 % | 88.72 % | 87.53 % |
| non-reused cells: new / illegal / timing | 0.17 / 0.03 / 0.01 % | 0.17 / 0.05 / 0.18 % | 0.15 / 0.05 / 0.43 % |

The reference's physical-synthesis transforms were **all replayed, 0 not reused** (`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:168-174`):
* hold_fix: 867
* fanout_opt: 279
* dsp_register_opt: 155
* equ_drivers_opt: 88
* critical_cell_opt: 16
* shift_register_opt: 6
* slr_crossing_opt: 2

Hierarchical (the routed report `evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:245-337`; the new post-place
hook's report carries the same rows at `evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:347-386`, the first per-hierarchy
reuse measured at placement time). Columns are Reused / New / Discarded (illegal) / Discarded (timing):

| instance | reused | new | illegal | timing | cite |
|---|---|---|---|---|---|
| bd_wrapper | 764,118 | 1,344 | 428 | 1,396 | `evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:245` |
| **layer_0** | **227,773** | **0** | **0** | **0** | `evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:272` |
| **seq_0** | 5,644 | **1,340** | 421 | 875 | `evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:279` |
| ↳ u_seq / u_mov | 5,633 / 2,748 | 1,339 / 172 | 421 / 35 | 875 / 143 | `evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:335`, `:337` |
| mvchan_0..3 | 33,913 / 33,926 / 33,928 / 33,902 | 1 each | 0 | 0 / 0 / 4 / 0 | `evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:273-276` |
| csr_0 | 281 | 0 | 0 | 2 | `evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:263` |
| xdma_0 | 57,100 | 0 | 0 | 0 | `evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:284` |

**The shipped layer_0 placement survives whole**: 0 new, 0 illegal and 0 moved for timing. SR1 moved 1,740.
The netlist change lives in seq_0: the BM1 counters plus R1's decode/F_SCAN cone, 1,340 new cells against
SR1's 1,151.

The bm1ref run, whose reference already carries the counters, reused more (`evidence/qwen9b/sr/n721_SR7_score_build_044_r1_incr_bm1ref.log:146-148`, `:205-207`):
* cells: 99.89 % pre-place, 99.80 % after route;
* seq_0: 7,023 reused / **589** new / 179 illegal / 490 timing (`evidence/qwen9b/sr/n721_SR7_score_build_044_r1_incr_bm1ref.log:282`);
* mvchan: 0 new (`evidence/qwen9b/sr/n721_SR7_score_build_044_r1_incr_bm1ref.log:276-279`).

That is spec §4.4's expectation, measured.

## 4. The bitstream (NOT loaded by SR7; loaded once by SR8 on 2026-09-29 and restored)

```
synth/out_build_044_r1_incr/proj/stage1.runs/impl_1/bd_wrapper.bit
  53,076,057 bytes   2026-09-28 09:52:04 -0600
  sha256 92a2e52573ad37afaa9f4616a637616494b23bb9858bcf54575f6c9960b50816
checkpoint: …/impl_1/bd_wrapper_postroute_physopt.dcp  290,607,708 bytes  09:41:18
mmi:        …/impl_1/bd_wrapper.mmi  29,668 bytes  09:41:28
VERSION = e3c2ff1e   expected SEQ_CAPS = 0xFAB1CA01 ({R1})
```

The size and sha256 are at `evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:72-73`, the mtimes at
`evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:10-15`, and the VERSION at `evidence/qwen9b/sr/n720_SR7_score_build_044_r1_incr.log:75`.

The alternate, `build_044_r1_incr_bm1ref`, has sha256 `2b04919b…d8cc8f` (`evidence/qwen9b/sr/n721_SR7_score_build_044_r1_incr_bm1ref.log:77`)
and the **same VERSION e3c2ff1e**. On the board the two are indistinguishable by CSR. A session that loads
one must name it by path and sha256.

## 5. Host step (addenda 1–3)

* **SEQ_VERSIONS rows carry the expected SEQ_CAPS word, and the gate compares it.** The rows for build_041/042
  expect `HW.SEQ_CSR_UNMAPPED` (0xDEADC0DE). The identity gate reads SEQ 0x64 after the seq IDENT, records it
  as `ident["seq_caps"]`, and refuses on a mismatch, exactly like VERSION. It closes the SEQ gate, so
  `main()` refuses before any DMA.
  * TDD: `evidence/qwen9b/sr/sr7_host_tdd.py`, all mocks, no device.
  * RED: 3 passed / 10 failed (`evidence/qwen9b/sr/n703_SR7_host_tdd_RED.log:27`).
  * GREEN: 19 / 0 (`evidence/qwen9b/sr/n707_SR7_host_tdd_GREEN.log:34`). n704 is a stale-NFS partial of the same run.
* **The R1 row, admitted only when named.** After the sign-off, `0xE3C2FF1E: (SHAPE_ISA_9B, "build_044_r1_incr
  (R1 FENCE mask + BM1 counters; admitted only when named)", HW.seq_caps_word({"R1"}))` was added, with the
  same hash → SHAPE_ISA_9B in `sw/hwmap.py`'s SHAPE_ISA_BY_VERSION. The SHAPE decode is unchanged by R1.
  * RED: 19 / 2 (`evidence/qwen9b/sr/n730_SR7_host_tdd_r1row_RED.log`).
  * GREEN: 28 / 0 (`evidence/qwen9b/sr/n734_SR7_host_tdd_r1row_GREEN.log`). The GREEN run covers four gate cases:
    * an R1 board with the R1 word → READY;
    * the R1 VERSION with 0xDEADC0DE → REFUSED;
    * an R1 board under the default expect → REFUSED;
    * `parse_expect_version("e3c2ff1e")`.
  * n731–n733 are VOID (stale NFS on snoke right after the edit).
  * Note: with the hwmap row, the four direct-CSR tools (`sw/tok_meter.py`, `sw/infer.py`, `sw/layer_test.py`,
    `sw/matvec_test.py`) also accept this VERSION, with no naming step. They gate on the identity registers
    and CALIB only (fix round 1, M-1).
* **bm1_ident reads SEQ_CAPS.** `evidence/qwen9b/bm/bm1_ident.py` now reads BAR 0x6064. It prints the raw
  word and the set decoded by `hwmap.seq_caps_set`, and FAILs unless the set equals `--want-caps` (default
  `none`). An unknown magic decodes as "none"; an unknown bit under the magic is a FAIL. The pure part,
  `judge()`, is driven by the same TDD. It still runs under the system python3, since it imports only
  `sw/hwmap.py`.
* **seq_run selftest** 2820 / 0 (`evidence/qwen9b/sr/n735_SR7_seq_run_selftest.log`; `evidence/qwen9b/sr/n705_SR7_seq_run_selftest.log:55`).
  **Boardfree** at SR6's environment (FABLE5_MODEL unset) gives the same triple as SR6's n627: seq 2820/0,
  serve 85/0, chat 407/1. The chat failure is the pre-existing region-image check
  (`evidence/qwen9b/sr/n737_SR7_boardfree_noenv.log:140`).
  n708 and n736 are VOID as boardfree comparands: FABLE5_MODEL=9b in the environment flips serve's default
  template (`sw/serve.py:1785`).
* **SR6's own TDD no longer passes on this tree, by design.** Six of its cases put the R1 word on build_041's
  VERSION (`evidence/qwen9b/sr/n706_SR7_sr6_host_tdd_impact.log:15-61`), and the SR7 gate now refuses that
  combination. No real bitstream has it. The script was not edited here, because it is SR6's evidence.
  **Owner (the controller's ruling, fix round 1 M-1): SR11a round 2.** It moved the R1 mocks to build_044_r1's
  VERSION 0xE3C2FF1E in `evidence/qwen9b/sr/sr6_host_tdd.py` (commit `a26f612`).
* **Docs.**
  * `docs/USAGE.md`'s fail-fast sentence was reworded: `--reorder-check` catches B6 without the board, and
    VERSION plus bm1_ident's SEQ_CAPS line catch a non-R1 bitstream.
  * The "No R1 bitstream exists yet" sentence was updated.
  * `NEXT_SESSION.md` §3's selftest count was updated to 2,820 / 0, with its cite.
  * `NEXT_SESSION.md` §8 item 3 got one line.

## 5a. Citation drift from the host edits

The host edits moved lines in `sw/seq_run.py` and `sw/hwmap.py`, so SR7 ran the o3 pass
`evidence/qwen9b/sr/sr7_drift.sh`. It ran at base `6a5a8b8`, read the citing documents from the committed tree,
and excluded this gate doc, SR6's records and SR11a's files.
* **Plan, first run:** UNSAFE, REPAIR 200 / COLLATERAL 8 (`evidence/qwen9b/sr/n740_SR7_drift_plan.log`).
* **The 8 collateral tokens were checked by hand and cleared by name:**
  * the `SHAPE_ISA_BY_VERSION` dict range grows by the R1 row;
  * `SEQ_CAP_BITS` moves 353-355 → 354-356;
  * the rest follow the content they already named.
* **Plan, second run:** SAFE (`evidence/qwen9b/sr/n741_SR7_drift_plan.log`).
* **--fix:** 180 citations in 35 documents (`evidence/qwen9b/sr/n742_SR7_drift_fix.log`). Every file differs
  from HEAD in digits only, checked per file.
* **--verify:** PASS, 0 problems (`evidence/qwen9b/sr/n743_SR7_drift_verify.log`).

The other drift class covers citations INTO the two docs SR7 edited (`NEXT_SESSION.md` +3 lines, `docs/USAGE.md` +8).
The check reported 70 of 91 citations drifted (`evidence/qwen9b/sr/n744_SR7_doc_cites_check.log`).
**Repaired by hand, 4 live pointers** that named the right lines at the parent tree:
* `ref/scripts/regen_gate.sh:5` and `docs/superpowers/plans/2026-08-12-qwen2b-track-r.md` ×2: USAGE 584-588 → 592-596, the frozen-artifacts block;
* `evidence/qwen9b/o3/BOARD_LOCK.md:411`: USAGE 464 → 472, the flock paragraph.

**Left alone, deliberately:**
* 43 tokens in SR6's hand-repair records (`evidence/qwen9b/sr/sr6_hand_repairs.py`, `evidence/qwen9b/sr/sr6fix1_hand_repairs.py`),
  which record SR6-era coordinates.
* RD9's commit-prefixed `f9828f2:` quotes and G3_3's "was rewritten away" row, which are history.
* BOARD_LOCK's old → new re-point tables, which are history.
* Citations that already named other text at the parent tree:
  * `docs/superpowers/plans/2026-08-16-qwen2b-v5-w8.md:238` (USAGE 569-583);
  * `evidence/qwen9b/sr/SR2_ISA.md:104` (NEXT_SESSION 1087-1092, which is not the serve note at the parent tree either).

  Moving those would not make them right.

**spec_cites.** Over the 37 other documents SR7 touched, the spec_cites FAILs are all pre-existing.
The baseline (`evidence/qwen9b/sr/sr7_spec_cites_baseline.sh`) compares the tree without SR7's edits
(SR11a's and SR12's commits kept) against this tree. It found 275 FAIL keys in each and **0 introduced**
(`evidence/qwen9b/sr/n747_SR7_spec_cites_baseline.log`). The documents SR7 wrote are held to FAIL 0 by the
LAST run: this doc, `NEXT_SESSION.md` and `docs/USAGE.md`.

## 6. The fallback ladder — NOT executed, not needed

For the record, the ladder (spec §4.3; plan step 5) is:
* (a) the four-directive ckr2 spread;
* (b) the post-route phys_opt playbook;
* (c) the layer_0 RTL rounds;
* (d′) an R1 retiming fix;
* (e) SR7C.

None of them ran. The exoneration check (`evidence/qwen9b/bm/bm1_exoneration.tcl`) was not run either,
because there are 0 failing endpoints.

## 7. NOT established

* **No board measurement here** (SR8 made them since: `evidence/qwen9b/sr/SR8_R1_BOARD.md`). Nothing was loaded. That the R1 bitstream decodes a masked FENCE correctly on
  silicon, reports SEQ_CAPS 0xFAB1CA01 and VERSION e3c2ff1e, and calibrates is untested. The functional
  claims remain SR3's unit TB and SR5a/SR5b's chip TB on the same RTL.
* **One placement, not a margin.** +0.001 on the aclk is one routed result, as G5D said of the ship.
  **The thin margins are not in seq_0** (fix round 1, M-1):
  * the aclk at +0.001, on the shipped ATTN_DSP path (§2.2);
  * final_verify's `u_attn` +0.019 and `u_dn` +0.021 (`evidence/qwen9b/sr/n723_SR7_final_verify_build_044_r1_incr.log:137-139`).

  R1's own `seq_0 u_seq` family is at +0.242.
* **This bitstream needs its own Q9 load ruling** (the plan's per-bitstream rule) before any programming — given by the user on 2026-09-29 ("yes to both", `.superpowers/sdd/2026-09-27-seq-rtl/progress.md`, gitignored, cited by path and date).
* The Route 35-4475 critical warning (§2.1) is narrowed to three candidate nets but **not named exactly**
  (fix round 1, §9 M-2). Vivado's verbose mode does not print the net list.
* The base default-recipe roll does not exist (§1.2).
* Which of the two closing placements is "better" beyond the aclk figure is not established. The primary
  has +0.001 on the aclk, and the alternate has more UI margin (§2.2).
* The routed hierarchical reuse table is identical to the post-place hook's table, apart from the top row's
  reused count differing by 1 (764,118 routed, 764,119 post-place). So it most likely reflects placement-time
  reuse, not how much routing was kept. The flat routed figures (nets 98.16 %, pins 88.72 %) are the routing measure.

## 9. Fix round 1 (2026-09-28; the task review's I-1, M-1..M-5; I-2 on the controller's go)

* **I-1: bm1_ident's BM_IDENT expectation.** The R1 netlist carries the BM1 block, so SEQ 0x100 reads
  0xFAB1B301. bm1_ident expected 0xDEADC0DE for every VERSION but 9b588e78, so the documented pre-flight
  would have FAILed on the R1 bitstream.
  * The expectation now comes from ONE table, `sw/hwmap.py`'s `SEQ_BM_IDENT_BY_VERSION`:
    * 034 / 035 / 041 → 0xDEADC0DE;
    * 042 and e3c2ff1e → `SEQ_BM_IDENT` 0xFAB1B301.
  * The table was appended before hwmap's `__main__` guard, so no cited line moves. `evidence/qwen9b/bm/bm1_ident.py` reads it.
  * TDD, `evidence/qwen9b/sr/sr7_host_tdd.py` (j):
    * RED 30 / 4 (`evidence/qwen9b/sr/n749_SR7fix1_host_tdd_RED.log`).
    * n750 was 35 / 1: SR11a's in-flight build_035 `SEQ_VERSIONS` row had no BM_IDENT expectation, so it was added.
    * GREEN 36 / 0 (`evidence/qwen9b/sr/n753_SR7fix1_host_tdd_GREEN.log`). In it, an R1 board with BM_IDENT
      0xFAB1B301 and the R1 word PASSES `--want-version e3c2ff1e --want-caps R1`, and the same without the
      BM1 block FAILs. The case also checks that hwmap's magic equals `sw/seq_run.py`'s `SEQ_BM_IDENT`, and
      that every `SEQ_VERSIONS` row has an expectation.
  * The hwmap selftest passes (`evidence/qwen9b/sr/n754_SR7fix1_hwmap_selftest.log`).
  * bm1_ident still imports under the system python3 (`evidence/qwen9b/sr/n752_SR7fix1_bm1_ident_syspython.log`).
* **M-2: Route 35-4475.** The routed clock-utilization reports of build_043 and build_044_r1_incr differ
  in one cell only: g0 (the aclk) has 123,809 → 123,817 loads. Its root is X2Y2 (U) in both. The read-only
  probes named the candidates but not the nets:
  * `evidence/qwen9b/sr/sr7f1_clock_guidance.tcl` found that route_design -nets is refused in the
    incremental flow (`evidence/qwen9b/sr/n755_SR7fix1_clock_guidance.log`).
  * `evidence/qwen9b/sr/sr7f1_clock_guidance2.tcl` ran a full in-memory `route_design -verbose` on the
    post-place checkpoint. It reproduces the warning with the same Phase 1 checksum, but the verbose mode
    prints **no net list** (`evidence/qwen9b/sr/n759_SR7fix1_clock_guidance2.log:132`).
  * In that checkpoint, 25 of the 28 top-level global clock nets are ROUTED. **Three carry CONFLICTS**
    (partial routing inherited from the reference; `evidence/qwen9b/sr/n759_SR7fix1_clock_guidance2.log:86-114`):
    * `bd_i/xdma_0_axi_aclk`
    * `bd_i/ddr4_0_c0_ddr4_ui_clk` (the ddr4_0 UI clock)
    * `bd_i/ddr4_2_c0_ddr4_ui_clk` (the ddr4_2 UI clock)
  * The two nets of the warning are, by that evidence, two of these three. Which two is **not established**.
  * Their worst hold on the routed signoff dcp (`evidence/qwen9b/sr/n755_SR7fix1_clock_guidance.log:19649-19677`):
    * xdma_0_axi_aclk +0.001
    * all four MIG UI clocks (mmcm_clkout0, _1, _2, _3) +0.010, whichever of them is ddr4_0's and ddr4_2's
      (the ddr4-instance-to-clock-name map was not queried)
    * pipe_clk +0.011

    All meet timing.
  * The controller judged the warning non-blocking, because the closure stands on the fully routed clock tree (the routed design's route status: 660,491 of 660,491 routable nets fully routed, 0 with routing errors, `evidence/qwen9b/sr/n900_sr9_readonly.log:21-23`; cite added by SR9).
  * The n759 run was killed deliberately once Phase 2 began, so its log has no `rc` line. Nothing was
    written into any out dir: the checkpoints, bit and reports keep their run-time mtimes.
* **M-3: the launcher guard.** `synth/scripts/proj_busy.sh` reports a project as busy when:
  * a run has a begin marker with no end/error marker and a live pid on this host;
  * a run began on a foreign host;
  * a run is queued; or
  * a live process names the project.

  `synth/scripts/launch_incr.sh` calls it before the rsync and refuses on busy.
  `LAUNCH_INCR_CHECK_ONLY=1` stops before rsync and Vivado. The no-launch check,
  `evidence/qwen9b/sr/sr7f1_guard_check.sh`, ran twice:
  * First run: 12 / 2 (`evidence/qwen9b/sr/n756_SR7fix1_guard_check.log`). One case's `sleep <path>`
    exited at once, and `out_build_044_r1_incr/proj` was reported BUSY. That was correct: the M-2 probe
    had its checkpoint open.
  * After fix 1: **13 / 0** (`evidence/qwen9b/sr/n757_SR7fix1_guard_check.log`). Seven fake-project cases
    passed, the three real signed-off projects were IDLE, and the check-only launch ran the guard without
    creating an out dir.
* **M-4:** `sw/seq_run.py --selftest` gains the SEQ_CAPS half of the gate:
  * the shipped VERSION reporting the R1 word → REFUSED;
  * the named R1 VERSION reporting 0xDEADC0DE → REFUSED.

  The count goes **2,820 → 2,822 / 0** (`evidence/qwen9b/sr/n758_SR7fix1_seq_run_selftest.log`). A RED was
  not practical, because the compare had already landed in `3dcb045`; its RED is `evidence/qwen9b/sr/n703_SR7_host_tdd_RED.log`.
* **M-5:** the fix round's Vivado ran from the repo root. SR7's n722–n725 clock-root and final_verify runs
  cd'd into the two out dirs, as SR1's did, and each left an **empty `.Xil/` directory** there, at 10:35:36 (`out_build_044_r1_incr`) and 10:35:30 (`out_build_044_r1_incr_bm1ref`) (`evidence/qwen9b/sr/n900_sr9_readonly.log:7`, `evidence/qwen9b/sr/n900_sr9_readonly.log:9`; SR9 corrected the earlier "10:22").
  These appear after every artifact and report. They were not removed, since no out dir is edited.
* **M-1:** §5 now names SR6's TDD owner and adds tok_meter to the tools that accept e3c2ff1e. §7 now names
  the thin margins.
* **Cite drift.** `sw/seq_run.py` moved from `925d29d^`: SR7 M-4's 18 selftest lines, plus SR11a fix3's
  `fa7f5df`, whose owner re-aimed only its own doc. `evidence/qwen9b/sr/sr7f1_drift.sh` handled it:
  * **Plan:** 52 REPAIR / 1 COLLATERAL (`evidence/qwen9b/sr/n760_SR7fix1_drift_plan_seq_run.log`). The
    COLLATERAL token was checked by hand: the `_gate` VERSION-mismatch block is now at 1198-1206. It was
    cleared, and the second plan was SAFE (`evidence/qwen9b/sr/n762_SR7fix1_drift_plan_seq_run.log`).
  * **--fix:** 82 citations in 13 documents, digits only (`evidence/qwen9b/sr/n763_SR7fix1_drift_fix_seq_run.log`).
  * **--verify:** PASS (`evidence/qwen9b/sr/n764_SR7fix1_drift_verify_seq_run.log`).

  **Not applied: the `sw/hwmap.py` plan** (`evidence/qwen9b/sr/n761_SR7fix1_drift_plan_hwmap.log`), REPAIR 137 /
  COLLATERAL 8. Its shift comes from SR11a fix3's `fa7f5df` (+4 lines from the SHAPE table on), not from SR7:
  I-1's table sits after every cited line. It also touches `docs/SEQ_ISA.md`, which SR12 owns, so it was
  handed to the controller.

  Citations INTO `NEXT_SESSION.md` moved by I-2's insertions (`evidence/qwen9b/sr/n765_SR7fix1_doc_cites_check.log`).
  Three live pointers were repaired by hand:
  * `docs/NVFP4_STUDY.md:59`: 322 → 323;
  * the board-idle spec :46 and `evidence/qwen9b/sr/SR6_HOST.md:361`: 385 → 386.

  The rest are records or history, left as §5a left them.
* **I-2:** `NEXT_SESSION.md` §3 gains the build_044_r1_incr row (full path, size, sha256, NOT loaded, the
  shared VERSION with the alternate) and the admission sentence. §6 gains the R1 note (the direct-CSR tools
  incl. tok_meter accept e3c2ff1e; CALIB is their only guard), and §9 (d) gains item 17 (rd_chat2b.sh).

## 8. Logs

| log | what | status |
|---|---|---|
| n700 | preflight | used |
| n701 | build_044_r1 create + synth (base impl killed, rc 1) | used |
| n702 | launch verify, script on local scratchpad (rc 127) | **VOID** |
| n703 / n704 / n707 | host TDD RED / stale-NFS partial / GREEN | used / VOID / used |
| n705 | seq_run selftest 2820/0 | used |
| n706 | SR6's TDD on the new gate (6 FAIL by design) | used |
| n708 | boardfree with FABLE5_MODEL=9b | **VOID** as a comparand |
| n709 | launch verify (create/synth) | used |
| n710 / n711 | the two incremental launches, rc 0 | used |
| n712 | base roll killed by the copy's reset_run | used |
| n713 | 45-min incremental verify | used |
| n720 / n721 | scores | used |
| n722 / n724 | clock-root checks (before final_verify) | used |
| n723 / n725 | final_verify | used |
| n726 / n727 | DRC table via `evidence/qwen9b/sr/sr1_drc_table.sh`, whose range exits at the Table of Contents, so its count is vacuous | **VOID** |
| n728 / n729 | DRC table via `evidence/qwen9b/sr/sr7_drc_table.sh` | used |
| n730 / n734 | R1-row TDD RED / GREEN | used |
| n731–n733 | stale NFS | **VOID** |
| n735 | seq_run selftest after the R1 row | used |
| n736 | boardfree with FABLE5_MODEL=9b | **VOID** as a comparand |
| n737 | boardfree at SR6's env | used |
| n740 / n741 | cite-drift plan: UNSAFE (COLLATERAL 8), then SAFE with the 8 checked tokens cleared | used |
| n742 / n743 | cite-drift --fix (180 in 35 docs) / --verify PASS | used |
| n744 | citations into NEXT_SESSION.md / docs/USAGE.md: 70 of 91 flagged, 4 live ones repaired by hand (§5a) | used |
| n745 | spec_cites over all 38 documents SR7 touched: FAIL, all pre-existing (n747) | used |
| n746 | baseline, the first keying: 16 pre-existing QUOTE failures re-keyed by the +1 move | superseded by n747 |
| n747 | `evidence/qwen9b/sr/sr7_spec_cites_baseline.sh`: 275 base / 275 work FAIL keys, **0 introduced** | used |
| n748 | spec_cites LAST over this doc, NEXT_SESSION.md, docs/USAGE.md | superseded by fix round 1's LAST |
| n749 / n750 / n753 | fix 1 I-1 TDD RED / partial (missing build_035 BM row) / GREEN | used |
| n751 / n754 | hwmap selftest | used |
| n752 | bm1_ident under the system python3 | used |
| n755 / n759 | M-2 probes (per-clock hold; in-memory verbose route, killed after Phase 1) | used |
| n756 / n757 | M-3 guard check 12/2 → 13/0 | used |
| n758 | M-4 seq_run selftest 2822/0 | used |
| n760 / n762 | seq_run cite-drift plan UNSAFE / SAFE (1 collateral cleared) | used |
| n761 | hwmap cite-drift plan (SR11a fix3's shift) — not applied | used |
| n763 / n764 | seq_run --fix (82 in 13 docs) / --verify PASS | used |
| n765 | citations into NEXT_SESSION.md: 3 live pointers repaired by hand | used |
| n766 | spec_cites LAST over this doc, NEXT_SESSION.md, docs/USAGE.md | the LAST |
