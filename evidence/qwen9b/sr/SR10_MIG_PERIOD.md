# SR10 — the MIG's accepted DDR4 periods, and the route to prove the DIMMs calibrate there

Task SR10 of the sequencer RTL round
(`docs/superpowers/plans/2026-09-27-seq-rtl-round.md`, the SR10 task text, lines 375-392).
It answers spec §6 item 7, the part of Q3 that could be checked without the board
(`docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md:730-736`).
No RTL, no synthesis, no implementation, no bitstream, no board action.

## 0. Verdict

1. **With this design's 300 MHz DIMM refclk (InputClockPeriod 3332 ps) and the
   custom part BLS4G4D240FSB-2400, the MIG accepts exactly three periods in
   833..940 ps: 833, 877 and 937.** It refuses the other 105, and it refuses them
   on the refclk. For each of those periods the IP says 3332 is not an input-clock
   period its MMCM can use (E, `evidence/qwen9b/sr/n1002_sr10_mig_sweep.log:629-631`).
   The period itself is legal from 833 to 1600 ps
   (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:1078`). What limits it is the
   integer MMCM ratio from a fixed refclk.
2. **877 ps is exactly a 5.000 % UI-clock cut** (the MMCM makes 19/20 of the
   300.12 MHz refclk: M=19, D=4, O=5, UI = 285.114 MHz;
   `evidence/qwen9b/sr/n1002_sr10_mig_sweep.log:369`). It is the only accepted period
   between 0 % and 11.1 %. **No cut smaller than 5 % is available** with this
   refclk: not 0.3 % (the BM1 best roll's need), not 1–4 %. The MIG's
   Specify-M-and-D mode does not open any either (§2.3).
3. The spec's "next grade", DDR4-2133 at 938 ps, is **refused**. Its legal
   neighbour is **937 ps**, an 11.11 % cut (M=8, D=3, O=3;
   `evidence/qwen9b/sr/n1002_sr10_mig_sweep.log:624`). The Q3 answer rules out a
   full grade anyway (plan line 21).
4. At 877 the IP keeps everything else the same as the shipped configuration:
   CL 16 / CWL 12, the same part, and the same refclk constraint (the generated XDC
   still has `create_clock -period 3.332` on `c0_sys_clk_p`,
   `evidence/qwen9b/sr/n1001_sr10_mig_period.log:602`). The create_project dict
   *as written*, with only the period changed (CLKOUT0_DIVIDE 5 kept), is accepted
   (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:1116`). On the bitstream side an R2 UI-cut
   build is therefore a one-number edit at `synth/scripts/create_project.tcl:168`
   (833 → 877). **The host side must follow.** `sw/hwmap.py:21` hard-codes
   UI_CLK_HZ = 300.12e6, and that constant would misreport an 877 bitstream by
   5 %. The block design's validation at 877 was also never run. Both are §5
   items; neither is established here.
5. **Calibration route (step 2): a smaller buildable bitstream exists.** It is the
   stage-1 design (XDMA + four MIGs + CSR, no `layer_0`/`seq_0`) at commit
   35d95a5, the one build_007 was built from. It passed the stage-1 hardware gate
   at 833 ps. Rebuilt with the one-number period edit (bitstream side; its host tools read
   no UI clock, §3.1), it costs **about 75 min of
   build on snoke** and **about 25 min of board session** (§3). SR10 did not build
   it and did not touch the board. Whether to use it, or the default route
   (calibration as the first rung of the UI-cut R2 session), is the controller's
   call (§3.3).

## 1. Method

- **Where:** three new scratch projects on snoke, part xcvu9p-fsgd2104-2L-e:
  `synth/out_sr10_mig_probe/`, `synth/out_sr10_mig_probe_sweep/` and
  `synth/out_sr10_mig_probe_mandd/`. Each script refuses to run if its directory
  exists. No existing project was opened, including build_041's.
- **What:** `create_ip` of ddr4 v2.2, then `set_property -dict` with the DDR4
  configuration of `synth/scripts/create_project.tcl:166-176`: the imported custom
  CSV, isCustom, UDIMMs, BLS4G4D240FSB-2400, DataWidth 64, AXI, InputClockPeriod
  3332, and the period under test. Then a readback of what the IP holds,
  `validate_ip`, and for the ladder's accepted instances
  `generate_target {synthesis instantiation_template}` (output products only).
  **A period counts as ACCEPTED only if** the set raises no error, the IP still
  holds the requested period, refclk 3332 and the requested part, and no new ERROR
  is counted. Vivado rolls back a refused set (IP_Flow 19-3438, then undo), so the
  readback of a refused row shows the previous configuration.
- **Runs** (all on snoke through `evidence/qwen9b/sr/sr_run.sh`; every script
  committed before its first use):

| log | script | what |
|---|---|---|
| `evidence/qwen9b/sr/n1000_sr10_vivado_procs_before.log` | — | `pgrep -a -x vivado` before: none (rc=1, line 7) |
| `evidence/qwen9b/sr/n1001_sr10_mig_period.log` | `evidence/qwen9b/sr/sr10_mig_period.tcl` | the ladder (plan step 1): 833, 834, the 1–5 % cut periods, 876, 896, 926, 938 (both part rows), 1071, 1600, controls 750 / 1700; "noDIV" (period only) and "asPROJ" (create_project's dict incl. CLKOUT0_DIVIDE 5) variants; validate + generate |
| `evidence/qwen9b/sr/n1002_sr10_mig_sweep.log` | `evidence/qwen9b/sr/sr10_mig_sweep.tcl` | every integer 833..940 |
| `evidence/qwen9b/sr/n1003_sr10_mig_mandd.log` | `evidence/qwen9b/sr/sr10_mig_mandd.tcl` | 834..876 under the IP's Specify-M-and-D option |
| `evidence/qwen9b/sr/n1004_sr10_ratio_enum.log` | `evidence/qwen9b/sr/sr10_ratio_enum.py` | arithmetic cross-check (not evidence of acceptance) |
| `evidence/qwen9b/sr/n1005_sr10_vivado_procs_after.log` | — | `pgrep -a -x vivado` after: none (rc=1, line 7); no `.runs` directory in any scratch project (line 9); no `.dcp`/`.bit` (lines 10-11) |

The brief asks for `pgrep -af vivado`. The logs use `pgrep -a -x vivado`
(process name) because `-af` matches the wrapper's own command line, which
contains the word vivado. n1000's `-af lnx64.o/vivado` probe shows that
self-match (lines 9-12: only the probe's own shells).

## 2. Results

### 2.1 The ladder (n1001) — the plan's periods, validated and generated

| period (ps) | why | UI cut | verdict | Vivado's reason (log line) | IP's M / D / O | UI clock from the MMCM |
|---|---|---|---|---|---|---|
| 833 | baseline, DDR4-2400 | 0 | **ACCEPTED** (both variants) | — (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:1103-1104`) | 5 / 1 / 5 (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:236-238`) | 3332 ps = 300.120 MHz |
| 834 | 1 ps step | 0.12 % | REFUSED | IP_Flow 19-3461: 3332 not a valid InputClockPeriod (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:299`); for 834 the valid ones near it are 3335 / 3336 | — | — |
| 841 | 1 % cut (0.951 %, `evidence/qwen9b/sr/n1001_sr10_mig_period.log:47`) | | REFUSED | 19-3461 (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:354`) | — | — |
| 850 | 2 % (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:48`) | | REFUSED | 19-3461 (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:408`) | — | — |
| 859 | 3 % (3.027 %, `evidence/qwen9b/sr/n1001_sr10_mig_period.log:49`) | | REFUSED | 19-3461 (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:462`) | — | — |
| 868 | 4 % (4.032 %, `evidence/qwen9b/sr/n1001_sr10_mig_period.log:50`) | | REFUSED | 19-3461 (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:516`) | — | — |
| **877** | **5 % (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:51`)** | **5.000 %** | **ACCEPTED** (both variants) | — (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:1115-1116`) | 19 / 4 / 5 (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:582-584`; generated `evidence/qwen9b/sr/n1001_sr10_mig_period.log:629-631`) | 3507.368 ps = 285.114 MHz |
| 876 | 5 % floor | 4.91 % | REFUSED | 19-3461 (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:692`) | — | — |
| 896 | beyond | 7.03 % | REFUSED | 19-3461 (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:746`) | — | — |
| 926 | beyond | 10.04 % | REFUSED | 19-3461 (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:793`) | — | — |
| 938 | DDR4-2133, -2400 row | 11.19 % | REFUSED | 19-3461 (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:835`); for 938 the valid ones near it are 3335 / 3336 and 3282–3284 | — | — |
| 938 | DDR4-2133, the CSV's -2133 row | 11.19 % | REFUSED | 19-3461 (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:877`) | — | — |
| 1071 | DDR4-1866 | 22.22 % | **ACCEPTED** (both variants) | — (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:1126-1127`) | 14 / 3 / 6 (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:951-953`) | 4284 ps = 233.43 MHz |
| 1600 | the CSV row's max period | 47.9 % | REFUSED | 19-3461 (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:1009`) | — | — |
| 750 | CONTROL: below the part's 833 | — | REFUSED | five errors, incl. 19-3478 "supported only for a memory device interface speed between 833 and 1600" (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:1052-1056`) | — | — |
| 1700 | CONTROL: above the part's 1600 | — | REFUSED | six errors, incl. 19-3458 TimePeriod "out of the range (750,1600)" (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:1077-1082`) | — | — |

The accepted instances' generated products (`synth/out_sr10_mig_probe/`,
gitignored) keep the refclk constraint unchanged at every accepted period.
The same create_clock of period 3.332 on c0_sys_clk_p appears at 833, 877 and
1071 (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:209`,
`evidence/qwen9b/sr/n1001_sr10_mig_period.log:602`,
`evidence/qwen9b/sr/n1001_sr10_mig_period.log:924`). The MMCM parameters
appear in the IP top file as CLKIN_PERIOD_MMCM 3332 and the M/D/O above, with
tCK 877 (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:624-631`). The
UI clock is not an XDC constraint. Vivado derives it from the MMCM. (The 3750 /
938 values printed from ddr4_v2_2_infrastructure.sv and the _mem_intfc.sv file are
those modules' parameter defaults. The top overrides them.) At 877 the IP holds
CL 16 / CWL 12, the same as at 833 (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:588-589`).
The `validate=1` column on refused rows only means the IP validated in its
rolled-back state. The verdict comes from the set/readback.

### 2.2 The full sweep 833..940 (n1002)

**ACCEPTED: 833, 877, 937. REFUSED: all other 105**
(`evidence/qwen9b/sr/n1002_sr10_mig_sweep.log:629-631`).

| period | UI cut (of the MMCM UI clock) | M / D / O | MMCM CLKOUT0 = UI | VCO |
|---|---|---|---|---|
| 833 | 0 | 5 / 1 / 5 | 3332.000 ps, 300.120 MHz | 1500.6 MHz (`evidence/qwen9b/sr/n1002_sr10_mig_sweep.log:99`) |
| 877 | **5.000 %** | 19 / 4 / 5 | 3507.368 ps, 285.114 MHz | 1425.6 MHz (`evidence/qwen9b/sr/n1002_sr10_mig_sweep.log:369`) |
| 937 | 11.111 % | 8 / 3 / 3 | 3748.500 ps, 266.773 MHz | 800.3 MHz (`evidence/qwen9b/sr/n1002_sr10_mig_sweep.log:624`) |

(The log's "cut=" column is 1 − 833/P, the nominal tCK cut: 5.017 % at 877. The
UI cut in this table is 1 − 3332/CLKOUT0: 1 − 19/20 = exactly 5.000 % at
877 and 1 − 8/9 = 11.111 % at 937. The MMCM's clock is the one that runs the
fabric. The IP's timing parameters use tCK = 877 (0.16 ps, 0.02 %, longer than
the real 876.84), which is a negligible difference.)
The first 100 refusals print Vivado's 19-3461. After that Vivado's own
100-message limit hides the text
(`evidence/qwen9b/sr/n1002_sr10_mig_sweep.log:607`), so the last five
(935, 936, 938, 939, 940) show only the failed set and the rolled-back
readback. 938's own message is in n1001 (§2.1).

### 2.3 Specify-M-and-D does not open a sub-5 % period (n1003)

The IP has a mode where the user gives M/D/O and the IP derives the refclk
(xgui ddr4_v2_2.tcl, proc update_storeInputClkPeriod, read in the Vivado install,
not in this tree). For 834..876 the probe searched integer M/D/O within the
MMCM's VCO/PFD ranges for a ratio that gives 3332 ± 2 ps. The result:

- The shipped values are accepted in this mode (833 with 5/1/5,
  `evidence/qwen9b/sr/n1003_sr10_mig_mandd.log:109`).
  A deliberately wrong ratio is refused (834 with 5/1/5,
  `evidence/qwen9b/sr/n1003_sr10_mig_mandd.log:116`). That control shows the mode still checks the refclk.
- 834..839: no integer ratio at all (`evidence/qwen9b/sr/n1003_sr10_mig_mandd.log:157-162`).
- 840..876: **the ≤ 3 nearest candidates per period, all with D ≥ 5, REFUSED
  by Vivado**. That no D ≤ 4 candidate exists is arithmetic under the assumed
  VCO bound of 800–1600 MHz (§2.4), not a Vivado result (first row
  `evidence/qwen9b/sr/n1003_sr10_mig_mandd.log:202`, last row
  `evidence/qwen9b/sr/n1003_sr10_mig_mandd.log:906`, accepted list empty
  `evidence/qwen9b/sr/n1003_sr10_mig_mandd.log:908`). All candidates needed a pre-divider D ≥ 5. The IP refuses those
  with 19-3478 "CLKIN/D value should be >= 70MHz" (first instance
  `evidence/qwen9b/sr/n1003_sr10_mig_mandd.log:165`). In this mode it still checks 3332 against its valid list
  (19-3461, `evidence/qwen9b/sr/n1003_sr10_mig_mandd.log:166`).
  (The probe's search did not know the 70 MHz rule; it came from the IP.
  The "best M/D/O=" field in these rows prints D, M, O in that order.)

### 2.4 Arithmetic cross-check (n1004 — D, not the evidence)

Enumerating integer M/D/O under the IP's CLKIN/D ≥ 70 MHz rule (D ≤ 4) and an
*assumed* 800–1600 MHz VCO gives 833, 877 and 937 as the only legal periods in
833..940 (`evidence/qwen9b/sr/n1004_sr10_ratio_enum.log:17`). That is n1002's
list exactly. It also gives the same M/D/O the IP chose. Up to 1071 it
predicts 952, 961, 980, 1025, 1041, 1052 and 1071
(`evidence/qwen9b/sr/n1004_sr10_ratio_enum.log:18`). Only 1071 of those
was put to Vivado (§2.1); the rest were not.
**Why no small cut exists:** with D ≤ 4 and O limited by the VCO, the ratios
D·O/M just above 1 are 20/19 (5.26 % longer tCK, a 5.00 % UI cut), then 16/15,
15/14, and so on. Nothing lies between 1 and 20/19.

### 2.5 What each accepted period is worth (MODEL, spec §3.2; no interpolation)

| period | UI cut | S1 | R1 | R1+R2 | R1+R2+R3 | source |
|---|---|---|---|---|---|---|
| 833 | 0 % | 8.356 | 8.811 | 9.144 | 9.920 | T, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:70-74` (r=0 column) |
| **877** | **5.000 %** — the grid point exactly | 8.168 | 8.591 | **8.906** | 9.641 | T, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:70-74` (r=5 % column) |
| 937 | 11.111 % | — (not a grid point; the model's nearest evaluated point is the DDR4-2133 row at r = 11.12 %: 7.921 / 8.305 / 8.598 / 9.281, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:140` — 0.009 points away, quoted as that point, not re-derived) | | | | |
| 1071 | 22.22 % | — (beyond the 20 % grid; n120's DDR4-1866 row is at r = 22.25 %, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:141`) | | | | |

Board-scaled tok/s, form B. At 877, R1+R2 (8.906) still beats R1 at full clock
(8.811). This is the spec's own reading
(`docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md:528-530`). The same
row shows that the cut costs R1+R2 2.6 % against its full-clock 9.144.

**What 877 buys for timing:** the UI period grows from 3.332 to 3.507 ns
(+0.175 ns). That covers the BM1 best roll's UI miss (−0.010 ns, a 0.30 % need,
`evidence/qwen9b/ov/n120_sr0_clock_sens.log:148`). It does **not** cover the bad
`mvchan_3` rolls (10.91 % and 14.26 %, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:149-150`).
Because no period between 833 and 877 exists, a 0.3 % miss costs the full 5 %
of weight bandwidth if the cut rung is taken. SR14 should weigh that against
another placement roll.

## 3. Step 2 — the calibration route (time-boxed reading, ~40 min used)

### 3.1 Found: the stage-1 bitstream

- **What it is.** The stage-1 design is XDMA Gen3 x8 + the four DDR4 MIGs + the
  CSR block (MAGIC / VERSION / CALIB) and nothing else. It was built as build_007
  from commit 35d95a5 and passed the stage-1 hardware gate: CALIB 0xF, and
  4 seeds × 2 runs × 4 ch × 4 GiB bit-exact
  (`evidence/stage1/STAGE1_GATE.md:1-18`). Its DDR4 block is the same code
  as today's: the same custom CSV, 3332 refclk, UDIMMs, the same part. Of the
  six constraint files it imports (DIMM0-3, PCIe clock, CDC), five are unchanged
  since 35d95a5. The sixth, `synth/constraints/fable5_cdc.xdc`, has only gained
  three false-path groups for the later `matvec_chan` crossings (lines added,
  none changed). The other 17 differences under `synth/constraints/` are files
  added for later stages (git diff --name-only --diff-filter=M / =A 35d95a5
  HEAD). A worktree at 35d95a5 uses that commit's own copies in any case.
- **Build cost (measured once, June).** build_007 took 3 min for create
  (08:04:02–08:07:07) and 73 min for synth+impl+bitstream (08:07:21–09:20:06).
  The host was snoke (host memory 265784 MB). These figures come from the
  gitignored logs synth/out_build_007/create.log and build_run.log. Say
  **~75 min**, one run, on snoke. This is against ~4 h for a full 9B build.
- **Board cost.** The stage-1 bring-up script `sw/stage1_hw_bringup.sh` runs
  remove → JTAG → rescan → CSR gates → quick then full `sw/ddr_test.py` under
  one board-lock hold. At HEAD it still takes a bitstream and an expected VERSION
  (`sw/stage1_hw_bringup.sh:4`). Its June run took 09:25:07 → 09:48:34, **~23 min**
  (`evidence/stage1/hw_bringup_20260611_092507.log:2`,
  `evidence/stage1/hw_bringup_20260611_092507.log:110`). Restoring build_041
  afterwards (program + identity) adds a few minutes.
- **How it would be built (not done).** Use a git worktree at 35d95a5, on a new
  branch. Make a dated, committed one-number edit: DDR4_TimePeriod 833 → 877. This is
  the bitstream side only. The stage-1 gate tools read CSR and DMA data, not UI
  cycle counts, so UI_CLK_HZ (§5) does not enter this route.
  CLKOUT0_DIVIDE 5 may stay, because the asPROJ variant accepted it
  (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:1116`). Build with that
  commit's own create/launch scripts into a new synth/out_ directory of its own. The CSR
  VERSION is that commit's hash. Then, under the board lock and with the
  controller's go: sw/stage1_hw_bringup.sh with the bitstream and that hash. The pass criterion is
  CALIB 0xF, then the full `sw/ddr_test.py` pattern bit-exact on all four
  channels. Then restore build_041 and read its identity. **Do not** DMA
  anything else, and do not load SEQ streams: this bitstream has no sequencer,
  so the `SEQ_VERSIONS` admission rule does not apply to it and nothing may
  drive it.
- **What it proves and what it does not.** It proves the four DIMMs calibrate
  and hold data at tCK 877 / UI 285.114 MHz. The MIG, PHY and I/O banks are
  pinned by the board, and the MIG IP is identical, so this carries over to any
  bitstream with the same DDR4 configuration. It does **not** prove the R2
  bitstream's timing or its own calibration run. The R2 session still reads
  CALIB 0xF as part of its identity check (plan SR15).
- **The failure path.** CALIB ≠ 0xF, or a `sw/ddr_test.py` failure at 877,
  means:
  1. no further DMA;
  2. restore build_041 under the safe flow (`sw/program_fpga.sh`);
  3. read its identity;
  4. record;
  5. STOP.
  SR14's UI-cut rung is then dropped (877 is the only sub-grade period, §2.2),
  and R2 follows the rest of SR14's order.

### 3.2 Not a route: today's `synth/scripts/create_project.tcl` without `layer_0`

`layer_0` is wired into the address maps, `axi_smc`, `burst_smc` and `seq_0`'s
private map (`synth/scripts/create_project.tcl:279-282`,
`synth/scripts/create_project.tcl:328`,
`synth/scripts/create_project.tcl:417-418`). The script has no option to leave
it out, so removing it would mean a new script. The stage-1 commit is the
existing, proven minimal design, so this route was not pursued.

### 3.3 Optional cheap pre-rung (sim, not DIMMs)

`synth/scripts/sim_ddr4_ex_gen.tcl` generates the DDR4 example design with the
same custom part and runs its xsim calibration + traffic test. That was the
stage-1 "sim before hardware" evidence (`evidence/stage1/STAGE1_GATE.md:9-12`).
It hard-codes 833 (`synth/scripts/sim_ddr4_ex_gen.tcl:25`). A copy at 877
would show, in minutes, that the MIG's calibration sequence completes against
the memory model at that period. It says nothing about these DIMMs.

**The two routes, for the controller.** (a) Build and run the stage-1 877 ps
calibration bitstream **before** committing to an R2 UI-cut build: ~75 min of
build plus ~25 min of board, and a failure costs no R2 build. (b) The plan's
default: calibration is the first rung of the UI-cut R2 bitstream's own board
session (SR15 step 3). That costs nothing extra up front, but a failure throws
away a ~4 h build. Route (a) is available and cheaper on failure. SR10 does not
choose, because the choice includes a board session, which needs the
controller's go.

## 4. Judgment calls

1. **Three scratch projects, not one.** The plan names one scratch directory. The
   sweep and the M/D probe were not planned at first; they followed from n1001's
   finding that acceptance is set by the refclk ratio. Each got a new sibling
   directory, so no out directory was reused.
2. **Two extra probes beyond the plan's ladder** (n1002, n1003). They were
   needed to answer the question the brief actually asks ("which in-between
   periods") once the ladder showed sparse acceptance. Both use set_property
   only.
3. **The ladder rounds each cut to the nearest integer and adds a floor at
   5 %.** 877 (5.017 % tCK) is the round, 876 the floor.
4. **The "next grade" was tested at 938 with both CSV rows** (the -2400 row at a
   slower speed, and the -2133 row). Both were refused. The legal 937 came from
   the sweep.
5. **The `generate_synth_checkpoint false` guard did not match** (WARNING
   Vivado 12-818 "No files matched '*.xci'" in n1001). This is harmless: no
   `create_ip_run`/`launch_runs` was ever issued, and n1005 shows no `.runs`
   directory and no `.dcp`.
6. **InputClockPeriod was kept at 3332** throughout. The board's oscillator is
   nominally 300.000 MHz (3333.3 ps) but the shipped design says 3332. Changing
   the refclk constraint to open more periods would be a different, untested
   change, and SR10 does not propose it.

## 5. NOT established

- **That the DIMMs calibrate at 877 ps**, or hold data there. §3 gives the route.
- **Timing at 877 ps** for any netlist.
- That the MMCM VCO range used in §2.4 (800–1600 MHz) is right. It was assumed,
  not read. The evidence is Vivado's own acceptance (§2.1–§2.3), which does not
  depend on it.
- That no other refclk setting, or a fractional MMCM ratio outside the IP's
  integer parameters, could give a smaller cut. The IP declares M/D/O as
  integers and the refclk was held at 3332 by design.
- Periods above 940 other than 1071 and 1600 were not asked of Vivado.
- **The five message-capped refusals** (935, 936, 938, 939 and 940 in n1002).
  Vivado's 100-message limit
  (`evidence/qwen9b/sr/n1002_sr10_mig_sweep.log:607`) hid their 19-3461 text.
  Their verdict rests on the failed set plus the rolled-back readback, not on a
  printed reason. 938's own reason is printed in n1001
  (`evidence/qwen9b/sr/n1001_sr10_mig_period.log:835`).
- **That the cut is fine enough to be worth its cost.** The smallest legal cut
  is 5 %. The BM1 best roll's UI miss needed 0.30 %
  (`evidence/qwen9b/ov/n120_sr0_clock_sens.log:148`). The bad `mvchan_3` rolls
  needed 10.91–14.26 %
  (`evidence/qwen9b/ov/n120_sr0_clock_sens.log:149-150`), which 5 % does not
  cover. So the rung either overpays (a small miss) or does not close (a
  large one).
- **The host's UI clock at 877.** `sw/hwmap.py:21` fixes
  UI_CLK_HZ = 300.12e6. That constant feeds:
  - `sw/tok_meter.py:630` (matvec time) and `sw/tok_meter.py:731` (GB/s);
  - `sw/cycle_census.py:26`;
  - `sw/matvec_test.py:154` (GB/s).

  On an 877 bitstream the UI clock is 285.114 MHz (§2.2), so these tools would
  understate time by 5.0 % (285.114/300.12 = 19/20) and overstate GB/s by
  5.26 % (20/19). UI_CLK_HZ must become per-VERSION (285.114 MHz for an 877
  bitstream) before any census or tok_meter run on it. That is SR15's job
  (with the SEQ_VERSIONS row). SR10 changes no host code.
- **validate_bd_design at 877.** The block design's validation
  (`synth/scripts/create_project.tcl:569`) was never run at 877. A standalone
  create_ip probe cannot show it. At 877, a UI FREQ_HZ of about 285.1 MHz has
  to propagate from each MIG's ui_clk to the SmartConnects and the mvchan
  interfaces. (The 300 MHz FREQ_HZ at
  `synth/scripts/create_project.tcl:215` is the DIMM refclk port, which is
  unchanged.) SR14 reads the UI-cut build's create log for that validation
  before trusting the build.
