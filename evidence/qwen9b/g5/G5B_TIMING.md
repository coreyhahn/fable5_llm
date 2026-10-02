# G5b — the full in-context build and timing closure (Task 14)

**STATUS: THE GATE FAILS — ESCALATION TO THE USER.** Best of eleven
implementation runs: **WNS −0.130**, 4,265 failing setup endpoints, three of
six clocks failing. Hold is clean everywhere (WHS 0.000, zero failing hold
endpoints, no `WHS_GATE: NEGATIVE` in the campaign). The pass criterion —
WNS >= 0.000 and WHS >= 0.000 on all clocks, zero failing endpoints, no waiver
— is **not met**, the house playbook is spent, and **a negative WNS is not
this agent's to accept**. The verdict, the options and what is NOT established
are sections 10 and 11. **No bitstream from this task is a Task 15 candidate,
and the board was never touched.**

## 0. HOW TO READ EVERY NUMBER BELOW — stated before the numbers

* **Labels.** **T** = measured, taken from a named report or log in this
  directory; **D** = derived, with the arithmetic shown; **S** = stated by a
  source, with the source named. Nothing here is modelled.
* **Every out dir is gitignored.** `synth/out_build_*` never enters the repo,
  so every number this document cites is quoted from a COMMITTED copy in
  `evidence/qwen9b/g5/` — a `evidence/qwen9b/run.sh`-wrapped log or a report section copied out
  of the roll that produced it. Where a table cell comes from a roll's own
  report, the file is named beside it.
* **Vivado ran only on snoke**, Vivado 2024.2, one fresh out dir per roll,
  never reused. Every log carries `=== host: snoke` from
  `evidence/qwen9b/run.sh`.
* **The board was not touched.** Task 14 produces a bitstream and records its
  path, size, mtime and `VERSION`; programming is Task 15. The BCU-1525 stayed
  on the 2B `build_035_fp2a_exc_po` bitstream throughout.
* **The pass criterion is not this document's to relax**: WNS >= 0.000 and
  WHS >= 0.000 on all clocks, zero failing endpoints, no waiver — the standard
  build_035 set (`evidence/qwen2b/rc/TIMING_035.md` section 13.6: the first
  bitstream this project produced that required no waiver at all). A negative
  best roll is an escalation to the user, not a decision taken here.
* **What OOC established and what it did not.** S5 placed this layer alone on
  the die inside one SLR and it MET post-place — WNS +0.030 (Default) / +0.034
  (`AltSpreadLogic_medium`), TNS 0.000, zero failing setup endpoints, 0 SLLs
  (`evidence/qwen9b/s5/S5_STRUCT.md` section 3.3). S5's own reading rule (its
  section 0) is that OOC success is necessary and not sufficient, and that
  nothing there is routed (its section 6). **This build is the test**: in
  context, routed, beside XDMA at fixed sites, four MIGs, four matvec channels
  and the sequencer. Where an S5 number appears below it is a comparand, never
  a substitute for an in-context measurement.
* **One S4 figure may not be re-used as a board number.** The state-DMA lane's
  5.133 ms/token (`evidence/qwen9b/s4/S4_REPLAY.md`) is MODELLED at LAT 8.
  Nothing in this document quotes it as a measurement, and Task 15 is where a
  board figure can exist.

## 1. THE HARNESS DEFECT THE FIRST THREE ROLLS FOUND

Three build numbers were spent before this design reached synthesis, none of
them on more than ten minutes of Vivado. They are recorded in full because the
first two repairs were wrong, the third is right, and the reason the third is
right is a measurement rather than a third guess.

### 1.1 build_036 — `validate_bd_design` ERROR, one error, 10 minutes

`evidence/qwen9b/g5/030_build_036.log` (`=== rc: 1`), launched at tree
`3091d4b`:

```
ERROR: [BD 41-237] Bus Interface property FREQ_HZ does not match between
/axi_smc/S02_AXI(250000000) and /layer_0/m_axis(100000000)
```

preceded in create.log by
`CRITICAL WARNING: [BD 41-967] AXI interface pin /layer_0/m_axis is not
associated to any clock pin` and two SmartConnect clock-domain CRITICAL
WARNINGs on `S02_AXI`. Every other CRITICAL WARNING in that log — the four
`[BD 41-1354]` master-segment overlaps and the seven `MAX_BURST_LENGTH`
mismatches on the AXI-Lite slices — is present on build_035 too and is not new.
**One ERROR, and it was read before anything was changed.**

**The cause, off the wrapper rather than pattern-matched to a prior fix.**
`rtl/layer_chan_ipi.v:9` declares
`ASSOCIATED_BUSIF s_axil:s_axib, ASSOCIATED_RESET aresetn` on `aclk`. S2 added
the `m_axis` state-DMA master to that wrapper and never added it to that list,
although `rtl/layer_chan_ipi.v:123` says in words that the master is "on the
SAME aclk". `rtl/seq_unit_ipi.v:12` is the working comparand — it lists all
four of its bundles, `s_axil:m_axil:m_axi:m_axib`, which is why `seq_0`, with
three masters on the same clock, has never hit this. Unassociated, IPI gives
`m_axis` its default 100 MHz and no clock domain at all.

### 1.2 build_037 and build_038 — two wrong repairs, each caught by its own guard

| roll | repair attempted | how it died | minutes |
|---|---|---|---|
| build_037 | `CONFIG.ASSOCIATED_BUSIF {s_axil:s_axib:m_axis}` on `layer_0/aclk`, then assert `m_axis` FREQ_HZ | `FATAL: layer_0/m_axis FREQ_HZ = '100000000', wanted 250000000` | 7 |
| build_038 | same, plus an explicit `CONFIG.FREQ_HZ`, asserting the ASSOCIATED_BUSIF read-back FIRST | `FATAL: layer_0/aclk ASSOCIATED_BUSIF = 's_axil:s_axib', m_axis not in it` | 7 |

`evidence/qwen9b/g5/031_build_037.log` and
`evidence/qwen9b/g5/032_build_038.log`, both `=== rc: 1`.

**Both guards were worth their place.** build_037's told us the association had
not produced a frequency; build_038's told us why — the `set_property` had not
taken at all, and had said nothing while not taking. That is precisely the trap
this script's own header names at `synth/scripts/create_project.tcl:97-98`:
*"set_property on BD cells only WARNS for unknown CONFIG params, so every
config below is re-read and asserted afterwards"*. Without the read-back the
run would have proceeded to a SmartConnect quietly inserting a clock converter.

### 1.3 The measurement that ended the guessing

Two failed repairs at seven minutes each is a pattern, not bad luck, so the
third question was answered by experiment rather than by inference.
`evidence/qwen9b/g5/g5b_bd_pin_probe.tcl` builds the smallest design that can
answer it — one `-type module` reference cell of `layer_chan_ipi`, no XDMA, no
MIGs, no SmartConnect — and reports for each property what it was, whether the
write errored, and what it is afterwards. Four minutes, `=== rc: 0`,
`evidence/qwen9b/g5/033_bd_pin_probe.log`:

```
PROBE_ABIF_BEFORE:   's_axil:s_axib'
PROBE_ABIF_SET_ERR:  (none)
PROBE_ABIF_AFTER:    's_axil:s_axib'
PROBE_FREQ_BEFORE:   '100000000'
PROBE_FREQ_SET_ERR:  (none)
PROBE_FREQ_AFTER:    '250000000'
PROBE_CLKDOM_BEFORE: ''
PROBE_CLKDOM_SET_ERR: (none)
PROBE_CLKDOM_AFTER:  'probe_clk_domain'
```

**T**, all three rows. `CONFIG.ASSOCIATED_BUSIF` on a module-reference cell's
clock pin is **silently ignored** — no error raised, value unchanged. It comes
from the HDL attribute and nothing in the block design can override it. The two
**bus parameters on the interface pin are both writable.**

### 1.4 The repair that works, and what it asserts

Between them `FREQ_HZ` and `CLK_DOMAIN` state exactly what the association
would have propagated, so `synth/scripts/create_project.tcl` sets both
explicitly and asserts each where its answer exists:

| property | where set | what it fixes | assertion |
|---|---|---|---|
| `CONFIG.FREQ_HZ 250000000` | `layer_0/m_axis`, in the layer section | the value `[BD 41-237]` compares against `axi_smc/S02_AXI` | read back immediately — `SDMA_FREQ_OK` |
| `CONFIG.CLK_DOMAIN` | `layer_0/m_axis`, just before `validate_bd_design` | puts `m_axis` in `aclk`'s domain so SmartConnect infers no clock converter | copied from the first donor that carries one, every donor printed; read back — `SDMA_CLKDOM_SET` |
| — | after `validate_bd_design` | propagation has run by then | `axi_smc/S02_AXI` must share `S00_AXI`'s CLK_DOMAIN — `SDMA_CLOCK_OK` |

The last row is the decisive one and it is deliberately not a check that the
values stuck. `S00_AXI` is XDMA's own master, the known-good SI on that
interconnect; **equal clock domains on S00 and S02 is what says no CDC was
inserted on the state-DMA path.** A matching `FREQ_HZ` alone would silence the
ERROR and still let SmartConnect treat `S02_AXI` as asynchronous — a
**functional** change, not a timing one, and exactly the kind of thing a green
build hides.

**Why the repair is in `synth/scripts/create_project.tcl` and not in the wrapper.** The
wrapper is the frozen tree S4 replayed and S5 placed. The correct one-line fix
is `rtl/layer_chan_ipi.v:9` gaining `:m_axis`; it is an `X_INTERFACE_PARAMETER`
attribute, IPI metadata that synthesis does not read, so it could not change a
cell of the netlist — but it would move that tree, and the block design can
state the same thing itself. **The wrapper repair is recorded as a follow-on**
(section 9).

### 1.5 A SECOND missing piece, found by reading rather than by running

While build_039 was in `create_project` with the clock fix, the source list was
read rather than trusted, and `rtl/state_dma.sv` was not in it.

`rtl/layer_chan.sv:705` instantiates `state_dma u_dma` — S2's 512-bit AXI4
state-DMA engine, the entire reason this campaign exists. S2 added the `m_axis`
bundle to the wrapper and the third SmartConnect SI to
`synth/scripts/create_project.tcl`, and never added the module's **source file**
to the project.

**The omission is silent through `create_project`, which is why three builds
did not find it.** `create_bd_cell -type module -reference layer_chan_ipi`
built the cell, and `validate_bd_design` ran far enough to report the FREQ_HZ
mismatch on build_036 — nothing said the engine was absent. The first
complaint would have come out of synthesis, hours later, or **not at all** if
the missing module had been black-boxed, which would have produced a bitstream
whose state DMA does nothing while every gate above it stayed green.

build_039 was **killed in `create_project`** rather than allowed to run into
that. Its `evidence/qwen9b/run.sh` log therefore never received a `=== rc:` line, so it could
not be committed under the campaign's provenance rule and is not in this
directory; the log number 034 is deliberately unused, and this section plus
commit `82b54ba` are its record.

The repair adds `rtl/state_dma.sv` to the list and adds a `LAYER_SOURCES_OK`
assertion over the twelve modules `layer_chan` instantiates. A missing source
is the one defect class this script could not otherwise see, and it costs
milliseconds to check there instead of a synthesis log. It passed first time on
build_040: `LAYER_SOURCES_OK: 12 layer modules present`.

### 1.6 Four burnt build numbers, and why they are not reused

`synth/out_build_036`, `_037`, `_038` and `_039` exist on snoke holding failed
or killed `create_project` runs. `synth/scripts/launch_build.sh:14-17` refuses
an existing out dir and the campaign rule is that an out dir is never reused,
so the first roll of this design that reaches synthesis is **build_040**. The
plan's AMENDED 2026-09-05 block names build_036 as the first roll; that name is
spent on the RED above, which is the honest record.

**The whole detour cost under 21 minutes of Vivado.** `=== date:` to
`=== end:` on the four committed logs, **T** off the headers: build_036
**10:04** (20:26:57 -> 20:37:01), build_037 **3:03** (20:41:24 -> 20:44:27),
build_038 **3:03** (20:47:00 -> 20:50:03), the probe **0:38**
(20:51:30 -> 20:52:08), plus build_039's killed run at roughly 4 minutes.
**D**: 10:04 + 3:03 + 3:03 + 0:38 + ~4:00 = **~20:48**. Each stop but one was a
guard written for exactly this; the exception — the missing source — was found
by reading the file the guards had already forced open.


### 1.7 The GREEN — both repairs verified on build_040's `create_project`

`evidence/qwen9b/g5/035_build_040.log`, tree `82b54ba` clean, launched
2026-09-05T20:57:48-06:00. From that roll's create.log, **T**:

```
LAYER_SOURCES_OK: 12 layer modules present
SDMA_FREQ_OK: layer_0/m_axis FREQ_HZ=250000000
SDMA_CLKDOM_DONOR xdma_0/axi_aclk  = 'bd_xdma_0_0_axi_aclk'
SDMA_CLKDOM_DONOR xdma_0/M_AXI     = ''
SDMA_CLKDOM_DONOR axi_smc/S00_AXI  = ''
SDMA_CLKDOM_DONOR layer_0/s_axil   = ''
SDMA_CLKDOM_DONOR layer_0/s_axib   = ''
SDMA_CLKDOM_SET: layer_0/m_axis CLK_DOMAIN=bd_xdma_0_0_axi_aclk
SDMA_CLOCK_OK: m_axis FREQ_HZ=250000000 CLK_DOMAIN=bd_xdma_0_0_axi_aclk;
               axi_smc S02==S00 domain 'bd_xdma_0_0_axi_aclk'
```

**The donor list earned its place.** Only the FIRST donor carried a domain;
all four fallbacks read `''` at that point, because parameter propagation had
not run yet — the same fact that made build_037's check fire. Had the script
read `layer_0/s_axil` alone, as the obvious choice, it would have FATALed on an
empty string.

**The decisive number is the last line, and it is a subtraction the log
supports directly.** build_036's create.log carried one
`[BD 41-967] … not associated to any clock pin` and two SmartConnect
*"do not share a common clock domain/frequency"* CRITICAL WARNINGs on
`S02_AXI`. On build_040 `grep -c` over the same file gives **0** and **0**, and
`axi_smc/S02_AXI` reports the same `CLK_DOMAIN` string as `S00_AXI` — XDMA's
own master on that interconnect. **No clock converter was inferred on the
state-DMA path**, which is the property that mattered and the one a matching
`FREQ_HZ` alone would not have bought.


---

## 2. WHAT RAN, WHERE, AND ON WHICH TREE

Every Vivado invocation below ran on **snoke** under
`evidence/qwen9b/run.sh`, which stamps host, date, tree sha and dirty flag,
command, interpreters and CPU count into the log before the command and
`=== rc:` / `=== end:` after it. Vivado 2024.2, sourced by the launchers
themselves. **Nothing numeric ran on darthplagueis**; the text tools
(`evidence/qwen9b/o3/o3_cite_drift.py`, `evidence/qwen_next/spec_cites.py`) did.

### 2.1 The log table

| # | log | what it ran | tree | rc | wall |
|---|---|---|---|---|---|
| 030 | `030_build_036.log` | `launch_build.sh build_036` | `3091d4b` | **1** | 10:04 |
| 031 | `031_build_037.log` | `launch_build.sh build_037` | `25d82cc` | **1** | 3:03 |
| 032 | `032_build_038.log` | `launch_build.sh build_038` | `3ec3185` | **1** | 3:03 |
| 033 | `033_bd_pin_probe.log` | `evidence/qwen9b/g5/g5b_bd_pin_probe.tcl` (the one-cell probe) | `3ec3185+dirty` | 0 | 0:38 |
| — | (034 unused) | `build_039`, KILLED in `create_project` — no `=== rc:`, so not committed (section 1.5) | `675c714+dirty` | — | ~4:00 |
| 035 | `035_build_040.log` | `launch_build.sh build_040` — **the first roll** | `82b54ba` | | |

**The two `+dirty` trees are declared here rather than left to be noticed.**
At 033 and 034 the working tree carried two files that were not yet committed:
this gate document (`evidence/qwen9b/g5/G5B_TIMING.md`, being written as the
campaign ran) and `evidence/qwen9b/g5/g5b_family_census.tcl`. Neither is read
by Vivado and neither can change a build; both are committed now. Every log
that carries a NUMBER used below is on a clean tree.

### 2.2 The tree the netlist is

**`82b54ba`** — the `VERSION` CSR of every bitstream this task produces is
`82b54bac`, as `synth/scripts/launch_build.sh` computes it
(`git rev-parse --short=8 HEAD` at launch). Against the tree S5 closed on, it
carries only this task's own commits: the in-context floorplan XDC, the two
`synth/scripts/create_project.tcl` repairs of section 1, the `synth/scripts/final_verify.tcl` instrument
change of section 2.3, and evidence. **No RTL was touched** — `rtl/` is
byte-identical to the tree S4 replayed and S5 placed.

### 2.3 The two instruments that had to change, declared

`synth/scripts/final_verify.tcl` — changed, and **the reason first given for
changing it was wrong; the correction is recorded here rather than quietly
dropped.** Its still-analysed loop asserts a pattern and exits `FV_FATAL` if
the pattern matches nothing. The pattern names the W8-era register
`*u_engine/xline_q0_reg*/CE`, and `rtl/matvec_engine.sv` contains no such
identifier — `grep -n xline` over that file returns four lines and the
declaration at `rtl/matvec_engine.sv:300` is `logic [1023:0] xline_q;`. The
inference drawn from that, that the pattern would match zero pins on this
netlist and FATAL a healthy design, **is refuted by the netlist itself**:
`evidence/qwen9b/g5/043_census_po2.log` reports `XLINE_CE_PIN_COUNT: 4096` and
names them, e.g.
`bd_i/mvchan_0/inst/u_chan/u_engine/xline_q0_reg[20]__3/CE`. Vivado's
synthesised name for that register carries a `0` the source does not, so the
W8-era pattern still matches — 1,024 bits x 4 channels = 4,096 pins, **D**.

The change is kept, on its OTHER justification and with the first one
withdrawn. What it now does: it resolves the pattern from the checkpoint,
trying the W8 name FIRST — which is what matches on both build_035's netlist
and this one, so behaviour is unchanged on both — falling back to `xline_q_reg`
and FATALing only if neither exists, and printing which it chose as
`FV_XLINE_PATTERN`. That is defensive rather than necessary. **The part that
was necessary** is the same loop gaining `*layer_0*u_core/u_dma/*/D` and
`*layer_0*u_core/u_attn/*/D`: the state DMA and the ATTN_DSP family are the two
endpoint classes the state spill created, the plan's amendment names both as
new census classes, and neither had a line in the signoff script that exists to
catch a class silently ceasing to be analysed.

`evidence/qwen9b/g5/g5b_family_census.tcl` — S5's `evidence/qwen9b/s5/s5_family_census.tcl`
**copied, not edited**, for the reason S5 copied Task 13's: S5's gate document
cites its instrument by name and this task's commit block does not include
`evidence/qwen9b/s5/`. Three differences, each stated in its header: it opens a
project roll's **routed** checkpoint instead of the OOC `post_place.dcp`; the
`SDMA` and `ATTN_DSP` patterns gain a leading `*`, because in context every one
of those cells sits under `bd_i/layer_0/inst/u_core/` and the unprefixed
pattern would match zero cells and print a silent `0 n/a`; and the 200-worst
histogram gains seven in-context families so the residual is readable. The six
S5 families keep their meaning exactly — first match wins and they still come
first.

`synth/scripts/census_035.tcl` is **NOT** changed, and one of its markers reads
zero as a result: its `xline_q0_reg` probe reports `XLINE_CE_PIN_COUNT: 0` on
this netlist for the same W8-strip reason. That is a measurement of the strip,
not a defect, and the per-channel numbers it would have produced are recovered
by `synth/scripts/final_verify.tcl`'s adaptive pattern. It is recorded here so a reader does
not take the zero for a missing check.


---

## 3. THE NETLIST — synthesis, and the check that it is the design S5 placed

### 3.1 A zero that is not a defect, recorded so nobody chases it

bd_wrapper_utilization_synth.rpt from build_040's top-level `synth_1` reports
**0 for every resource** — 0 LUT, 0 FF, 0 BRAM, 0 URAM, 0 DSP. That is the
per-IP out-of-context flow, not an empty design: every BD cell has its own
synthesis run (`bd_layer_0_0_synth_1`, `bd_mvchan_0_0_synth_1` … 41 of them),
and at top level they are black boxes until `link_design`. **The comparand
settles it**: build_035's own top-level synth report, still on disk, reads
`URAM 0` and `DSPs 0` in the same two rows. It is recorded here because a
0-URAM report on a build whose whole point is 182 URAM is exactly the number
somebody would stop on.

### 3.2 The layer's own synthesis — it IS the state-spill design

`evidence/qwen9b/g5/036_build_040_layer_util_synth.rpt`, copied out of
`synth/out_build_040/proj/stage1.runs/bd_layer_0_0_synth_1/` (the out dir is
gitignored). **T**, against S5's out-of-context measurement of the same RTL
(`evidence/qwen9b/s5/S5_STRUCT.md` sections 2.4 and 3.4):

| resource | build_040 `bd_layer_0_0` synth | S5 OOC | reading |
|---|---|---|---|
| **URAM288** | **182** | **182** | exact — the two-slot caches, DN 2×29 + KV 2×58 + CV 2×4 |
| **DSP48E2** | **1,838** | **1,838** | exact |
| LUT as Logic | 108,989 | — | |
| LUT as Memory | 4,496 | — | |
| **LUT total** | **113,485** | 114,106 (synth) / 109,357 (placed) | **D**: 108,989 + 4,496 = 113,485, 0.5 % under S5's synth figure |
| CLB Registers | 59,835 | 62,362 (placed) | placed counts include phys_opt replicas |
| Block RAM Tile | 79 (+8 RAMB18) | 81 (placed) | |

**The two numbers that had to be exact are exact.** 182 URAM is S5's fix-round
result — the count that only appears with the `ram_style = "ultra"` attribute
on the conv slots, and whose absence was S5's RED at 174. 1,838 DSP is the
resource S5 named as the tight one at 80.6 % of an SLR. Their agreement to the
unit is the evidence that the netlist this build implements is the netlist S5
placed, and — with `state_dma` now actually in the project — that the DMA
engine is present rather than black-boxed.

`grep -c '^ERROR'` over that run's runme.log is **0**.


---

## 4. THE CAMPAIGN

### 4.1 build_040 — the first roll, and what it is NOT

`evidence/qwen9b/g5/035_build_040.log` (rc 0, tree `82b54ba` clean, 20:57:48 ->
00:32:42 = **3h35m**) and `evidence/qwen9b/g5/037_build_040_verdict.txt`, which
carries the lines `synth/scripts/launch_build.sh` pipes through `tail -5` and therefore keeps
out of the run log.

```
CLOCK_GATE_OK: 250MHz clocks: pipe_clk xdma_0_axi_aclk
TIMING: WNS=-0.988 WHS=0.010
BUILD_OK
```

**`CLOCK_GATE_OK` is the marker the plan's Step 1 asks this roll for.** It
exists only in `synth/scripts/build.tcl` — `synth/scripts/full_impl.tcl` does not re-run it,
so re-implementation rolls inherit rather than re-check it, and this is the roll
where it is actually exercised. Two clocks answer the 4 ns window,
`pipe_clk` and `xdma_0_axi_aclk`, as on build_035.

Design Timing Summary, from that roll's own
reports/timing_summary.rpt (**T**, quoted in `037_…verdict.txt`):

| | build_040 |
|---|---|
| WNS | **−0.988** |
| TNS | **−16,181.674** |
| failing setup endpoints | **52,609** of 1,319,661 |
| WHS | **+0.010** |
| THS / failing hold | 0.000 / **0** of 1,316,525 |
| WPWS / pulse-width failures | 0.000 / **0** of 389,262 |

**This roll is the BASELINE, not a candidate.** It carries no floorplan —
`synth/scripts/create_project.tcl` imports the board XDCs, `synth/constraints/fable5_pcie_clk.xdc`,
`synth/constraints/fable5_cdc.xdc` and `synth/constraints/layer_mcp.xdc` and nothing else — and it runs the project
default strategy with **neither** `phys_opt` stage. It is what the design does
with no help, and it is the comparand the floorplan and the recipe are measured
against. Its bitstream is not a shipping candidate.

For scale, build_035's own base roll was WNS −0.480 / 16,677 failing
(`evidence/qwen2b/rc/TIMING_035.md` section 13.6). This design is bigger and
starts further out, which is what the plan's 6-10 build cycles were priced for.

### 4.2 The floorplan is proved to take BEFORE the spread is scored

`synth/scripts/floorplan_check.tcl` exists to dry-run a floorplan against a
real netlist rather than discover after hours that a pblock matched nothing —
*"A pblock matching zero cells is silently harmless in Vivado — the classic way
to run a floorplan campaign that measures nothing."* Run on build_040's own
routed checkpoint with the ctx XDC:
`evidence/qwen9b/g5/039_floorplan_check_ctx.log`, rc 0.

```
FPCHECK_XDC_READ_OK
FPCHECK_PBLOCK_COUNT: 1
FPCHECK_ASSIGNED pb_layer_1slr top_cells=1 leaf_cells=202527
  ranges     : CLOCKREGION_X0Y5:CLOCKREGION_X5Y9
  need(macro): DSP48E2=1838 URAM*=182
  DSP fit    : 1838 / 2280 = 80.6%
  URAM fit   : 182 / 320 = 56.9%
FPCHECK_OK
```

**T.** One pblock, one top cell — `bd_i/layer_0` — expanded to **202,527 leaf
cells**, not zero. The two capacity rows reproduce S5's out-of-context figures
**exactly**: DSP 1,838 / 2,280 = 80.6 % and URAM 182 / 320 = 56.9 %
(`evidence/qwen9b/s5/S5_STRUCT.md` section 3.4). The in-context rewrite of
`[get_cells *]` into `[get_cells bd_i/layer_0]` therefore names the same cells
in context that the OOC file named out of context, which is the one thing that
had to be true about this file.

**One row in that report is an artifact and is not quoted as capacity.**
`region has : … RAMB36=112` undercounts the SLR's block RAM: the script buckets
by `SITE_TYPE =~ RAMB36*`, and most block-RAM sites on this part report
`RAMBFIFO36E2`. The layer needs 79 tiles plus 8 RAMB18 against an SLR's real
720, so the fit is not in question, but 112 is a property of the query and not
of the device.

### 4.3 The spread — four directives, both XDCs, the full recipe

`TAG=fp1`, launched 00:33 on build_040's project, log
`evidence/qwen9b/g5/038_spread_fp1.log`. Each roll gets its own fresh out dir
(`synth/out_build_040_fp1_<directive>`), `rsync`-copied — never `cp -a`, the
documented NFS hang. **T**, from each roll's own fullimpl.log: all four print

```
EXTRA_XDC: …/synth/constraints/fable5_floorplan_a.xdc (implementation-only)
EXTRA_XDC: …/synth/constraints/fable5_floorplan_9b_1slr_ctx.xdc (implementation-only)
FULL_IMPL_CFG: place=<directive> phys_opt=AggressiveExplore (post-place AND post-route enabled)
```

— two `EXTRA_XDC` lines each, **in order**, which is the check that
`synth/scripts/launch_po2.sh`'s unquoted `${XDC:-}` split the two paths into two arguments
rather than passing one impossible filename. `synth/constraints/fable5_floorplan_a.xdc` and
`synth/constraints/fable5_floorplan_9b_1slr.xdc` are byte-untouched; the geometry is LAYERED, as
`synth/scripts/full_impl.tcl:11-16` says the argument list exists to allow.

The four directives, and why each:

| directive | why |
|---|---|
| `AltSpreadLogic_high` | won build_034 and build_035; the plan names it first |
| `AltSpreadLogic_medium` | S5's best OOC roll, `1slr-alt` at +0.034 |
| `Default` | S5's other MET OOC roll, `1slr` at +0.030 |
| `ExtraTimingOpt` | the fourth from the playbook's valid list; ran on build_035's fp3 |


### 4.4 The fp1 spread's results — and the question they force

Every row **T**, from that roll's own fullimpl.log `TIMING:` /
`WHS_GATE:` / `PBLOCK` lines. `XDC` is the ordered list `synth/scripts/full_impl.tcl`
reported as `EXTRA_XDC:`.

| roll | XDCs | directive | recipe | **WNS** | **WHS** | `WHS_GATE:` |
|---|---|---|---|---|---|---|
| **build_040** (baseline) | none | Default (project default) | **no phys_opt** | **−0.988** | +0.010 | n/a (build.tcl) |
| `fp1_ExtraTimingOpt` | A + ctx | `ExtraTimingOpt` | full | **−0.996** | 0.000 | OK |
| `fp1_AltSpreadLogic_high` | A + ctx | `AltSpreadLogic_high` | full | **−1.126** | 0.000 | OK |
| `fp1_AltSpreadLogic_medium` | A + ctx | `AltSpreadLogic_medium` | full | **−1.333** | +0.001 | OK |

**No `WHS_GATE: NEGATIVE` on any roll.** Hold is non-negative everywhere, which
is the one thing that would have stopped the campaign for a human immediately.

**The pblocks took, on every roll.** `synth/scripts/full_impl.tcl`'s own report, five pblocks
each, one hierarchical top cell apiece:

```
PBLOCK pb_layer_1slr cells=1 range={CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}
PBLOCK pb_mvchan_0   cells=1 range={CLOCKREGION_X0Y0:CLOCKREGION_X5Y4}
PBLOCK pb_mvchan_1   cells=1 range={CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}
PBLOCK pb_mvchan_2   cells=1 range={CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}
PBLOCK pb_mvchan_3   cells=1 range={CLOCKREGION_X0Y10:CLOCKREGION_X5Y14}
```

`cells=1` is the ASSIGNED cell count, not a primitive count — each pblock holds
one hierarchical cell, which constrains its whole subtree; section 4.2's
independent expansion of the same pblock counted **202,527 leaves**. So this
campaign is not the kind that measures nothing.

**And that is the problem.** The floorplan took, the full recipe ran with both
`phys_opt` stages, and **not one floorplanned roll beats a bare default roll
with no `phys_opt` at all.** The best of the three, `ExtraTimingOpt` at −0.996,
is **0.008 ns WORSE** than the unconstrained baseline; the worst is 0.345 ns
worse. **D**: −0.996 − (−0.988) = **−0.008**; −1.333 − (−0.988) = **−0.345**.

That is the reading `synth/constraints/fable5_floorplan_a.xdc:8-10` warns
about in as many words — *"The key result is what is ABSENT: there is
deliberately NO layer_0 pblock. Constraining layer_0 in any form cost ~1 ns"* —
and it is the question this task's own ctx XDC header says the campaign must
answer: **if the unconstrained roll is better, this file is not the answer.**

**But the fp1 table cannot answer it**, because the baseline differs from the
floorplanned rolls in TWO variables at once — the floorplan AND the recipe.
A bare roll beating a full-recipe roll only bounds the floorplan's cost from
below. So the next cycle is a controlled A/B at ONE directive and ONE recipe,
with the floorplan as the only variable.

### 4.5 The controlled A/B — one directive, one recipe, three floorplans

Launched 07:00 on the same build_040 project, `AltSpreadLogic_high` (the
directive that won builds 034 and 035) and the identical full recipe in all
three arms. **T**, each roll's own fullimpl.log:

| arm | log | out dir | `EXTRA_XDC:` |
|---|---|---|---|
| **A + ctx** (layer pblock) | `038_spread_fp1.log` | `…_fp1_AltSpreadLogic_high` | `synth/constraints/fable5_floorplan_a.xdc`, then `synth/constraints/fable5_floorplan_9b_1slr_ctx.xdc` |
| **A only** (mvchan pblocks) | `040_spread_fp2_mvchanonly.log` | `…_fp2_AltSpreadLogic_high` | `synth/constraints/fable5_floorplan_a.xdc` |
| **none** | `041_spread_fp3_nofloorplan.log` | `…_po2_AltSpreadLogic_high` | `none` |

**A naming honesty note.** The third arm's log is named `…fp3…` but its out dir
is `out_build_040_po2_AltSpreadLogic_high`: the launch omitted `TAG=fp3`, so
`synth/scripts/launch_po2.sh` used its default `TAG=po2`
(`synth/scripts/launch_po2.sh:7`). Nothing about the run differs — the recipe,
the directive and the empty XDC list are as intended, and `EXTRA_XDC: none` in
that roll's own log is the proof — but the directory is named `po2` and is
referred to by that name everywhere below rather than renamed to match the
log.

This is the comparison `synth/constraints/fable5_floorplan_a.xdc`'s key result was established
by on the 2B design, now run on the 9B state-spill netlist, where S5's OOC
experiment said the answer should be the opposite way round.


### 4.6 fp1's fourth roll did not route, and that is a result

`fp1_Default` is the one roll in this campaign that produced no `TIMING:` line
— `evidence/qwen9b/g5/038_spread_fp1.log` ends with `NO TIMING LINE: Default`,
which is `synth/scripts/launch_po2.sh`'s own report for a roll whose fullimpl.log has none.
Its runme.log, read rather than guessed at:

```
Phase 9 Verifying routed nets | Checksum: 28bd6c873
Time (s): cpu = 17:18:43 ; elapsed = 06:31:42 …
ERROR: [Route 35-2] Design is not legally routed. There are 1340 node overlaps.
ERROR: [Common 17-39] 'route_design' failed due to earlier errors.
```

**T.** Six and a half hours of routing, then a legality failure with **1,340
node overlaps**. This is a congestion outcome, not a harness defect: the router
could not legalise the placement `Default` produced under the two pblocks.
Vivado's own resolution text points at `report_design_analysis -congestion`,
and S5 had already flagged congestion as the one asymmetry it could see
(`evidence/qwen9b/s5/S5_STRUCT.md` section 4.5: a single `[Place 46-14]`
highly-congested warning, on the floorplanned run only). It is recorded as a
campaign row with no WNS, because it has none.

### 4.7 THE CONTROLLED A/B — and it is monotone

Three arms, **one directive (`AltSpreadLogic_high`), one recipe (full, both
`phys_opt` stages), one netlist (build_040's)**. The only variable is the XDC
list, and each roll's own fullimpl.log states which it got.

| arm | XDCs (`EXTRA_XDC:`) | **WNS** | **WHS** | `WHS_GATE:` |
|---|---|---|---|---|
| **none** — `po2_AltSpreadLogic_high` | `none` | **−0.247** | 0.000 | OK |
| **A only** — `fp2_AltSpreadLogic_high` | `synth/constraints/fable5_floorplan_a.xdc` | **−0.768** | 0.000 | OK |
| **A + ctx** — `fp1_AltSpreadLogic_high` | `synth/constraints/fable5_floorplan_a.xdc`, `synth/constraints/fable5_floorplan_9b_1slr_ctx.xdc` | **−1.126** | 0.000 | OK |

**Every pblock added makes it worse, and the ordering is strict.** **D**, from
the column:

* the four mvchan pblocks cost **0.521 ns** — −0.247 → −0.768;
* the layer pblock costs a **further 0.358 ns** — −0.768 → −1.126;
* the two together cost **0.879 ns** — −0.247 → −1.126.

**This answers the question the ctx XDC's own header set, and the answer is
no.** That header says, in the file itself: *"the question is reopened, and
build_036's UNCONSTRAINED first roll is the baseline that answers it. If the
unconstrained roll is better, this file is not the answer."* The unconstrained
roll is better by 0.879 ns at matched directive and matched recipe. **The
one-SLR layer pblock is not the answer on this design in this context.**

**It also refutes something Task 13 and build_035 established, which is the
more surprising half.** `synth/constraints/fable5_floorplan_a.xdc` is the 2B
campaign winner — the floorplan that took build_035 from −0.136 to −0.004 and
whose four mvchan pblocks are the reason that bitstream shipped without a
waiver. On the 9B state-spill netlist those same four pblocks **cost 0.521 ns**.
Neither floorplan transfers.

**And it is exactly what S5's own reading rule said to expect.**
`evidence/qwen9b/s5/S5_STRUCT.md` section 0: OOC success is necessary, not
sufficient; section 3.4 measured the pblock BUYING 0.618 ns with `layer_chan`
alone on the die. The difference between that die and this one is XDMA at fixed
sites, four MIGs, four matvec channels and a sequencer — and with them present,
confining the layer to SLR1 and the channels to their MIGs' SLRs takes away the
room the placer needs. S5 said the OOC result was a measurement, not a
prediction. It was right, and the prediction it declined to make would have
been wrong.

### 4.8 The state of the campaign at this point

| # | roll | XDCs | directive | recipe | **WNS** | **WHS** |
|---|---|---|---|---|---|---|
| 1 | `build_040` | none | project default | none | −0.988 | +0.010 |
| 2 | `fp1_ExtraTimingOpt` | A + ctx | `ExtraTimingOpt` | full | −0.996 | 0.000 |
| 3 | `fp1_AltSpreadLogic_high` | A + ctx | `AltSpreadLogic_high` | full | −1.126 | 0.000 |
| 4 | `fp1_AltSpreadLogic_medium` | A + ctx | `AltSpreadLogic_medium` | full | −1.333 | +0.001 |
| 5 | `fp1_Default` | A + ctx | `Default` | full | **route FAILED** | — |
| 6 | `fp2_AltSpreadLogic_high` | A only | `AltSpreadLogic_high` | full | −0.768 | 0.000 |
| 7 | **`po2_AltSpreadLogic_high`** | **none** | `AltSpreadLogic_high` | full | **−0.247** | 0.000 |

**The best roll is the one with no floorplan at all, at −0.247**, and it is
0.741 ns better than the best floorplanned roll. It is also the first number in
this campaign inside the same order of magnitude as the house playbook's known
reach — the 2B campaign closed −0.091 in one post-route `phys_opt` pass
(`evidence/qwen2b/rc/TIMING_035.md` section 3) — though −0.247 is still 2.7x
that distance and nothing here is closed.

The next cycle is therefore the playbook's reroll spread **from the
unconstrained position**: four more directives, no XDC, same full recipe
(`TAG=po3`, `evidence/qwen9b/g5/042_spread_po3_nofloorplan.log`) —
`ExtraTimingOpt`, `Explore`, `AltSpreadLogic_medium`, `WLDrivenBlockPlacement`.


---

## 5. THE CENSUS OF THE BEST ROLL

`po2_AltSpreadLogic_high` — no floorplan, `AltSpreadLogic_high`, full recipe.
Censused on its own post-route-phys_opt checkpoint,
`bd_wrapper_postroute_physopt.dcp`, mtime 2026-09-06 12:16:56, by the three
instruments the plan names plus the family census:
`evidence/qwen9b/g5/043_census_po2.log` (`synth/scripts/census_035.tcl`),
`044_slr_census_po2.log` (`synth/scripts/slr_census.tcl`),
`045_family_census_po2.log` (`evidence/qwen9b/g5/g5b_family_census.tcl`),
`047_final_verify_po2.log` (`synth/scripts/final_verify.tcl`) — all rc 0.

### 5.1 Headline, and the per-clock table

From `evidence/qwen9b/g5/046_po2_best_reports.txt`, copied out of that roll's
own reports/timing_summary.rpt:

| | best roll | build_040 baseline | build_035 SHIPPED |
|---|---|---|---|
| WNS | **−0.247** | −0.988 | **0.000** |
| TNS | **−542.860** | −16,181.674 | **0.000** |
| failing setup EP | **6,090** of 1,316,897 | 52,609 of 1,319,661 | **0** of 1,203,486 |
| WHS | **0.000** | +0.010 | 0.000 |
| THS / failing hold | 0.000 / **0** of 1,313,761 | 0.000 / 0 | 0.000 / **0** |
| WPWS / failures | 0.000 / **0** of 391,262 | 0.000 / 0 | 0.000 / 0 |

**D** against the baseline: TNS improved **29.8x** (−16,181.674 → −542.860) and
failing endpoints **8.6x** (52,609 → 6,090), from the recipe alone with no
floorplan.

**Five of the six clocks MEET with zero failing endpoints, and the entire
deficit is on one domain** — the 250 MHz `xdma_0_axi_aclk` the custom RTL runs
on. Intra Clock Table, same file:

| clock | WNS | TNS | failing EP | total EP | WHS | failing hold |
|---|---|---|---|---|---|---|
| `mmcm_clkout0` (ch0 UI) | 0.000 | 0.000 | **0** | 173,211 | +0.010 | 0 |
| `mmcm_clkout0_2` (ch1 UI) | **+0.005** | 0.000 | **0** | 173,235 | +0.011 | 0 |
| `mmcm_clkout0_3` (ch2 UI) | 0.000 | 0.000 | **0** | 173,174 | +0.007 | 0 |
| `mmcm_clkout0_1` (ch3 UI) | 0.000 | 0.000 | **0** | 173,102 | +0.001 | 0 |
| `pipe_clk` | **+0.894** | 0.000 | **0** | 4,764 | +0.013 | 0 |
| **`xdma_0_axi_aclk`** | **−0.247** | **−542.860** | **6,090** | 574,755 | 0.000 | 0 |

**D**: 6,090 on one clock reconciles exactly with the design summary's 6,090.
On build_035 three of six clocks failed before its final closure; here four DDR
UI domains and the PCIe pipe clock are already closed and only the layer's own
clock is not.

### 5.2 The per-SLR census — the placer found the one-SLR answer BY ITSELF

`synth/scripts/slr_census.tcl`'s SLICE-bucketed histogram
(`evidence/qwen9b/g5/044_slr_census_po2.log`), on the roll with **no pblock of
any kind**:

| instance | SLR0 | SLR1 | SLR2 |
|---|---|---|---|
| `bd_i/layer_0` | 0 | 2 | **204,149 (100 %)** |
| `bd_i/mvchan_0` | 0 | **28,835 (100 %)** | 0 |
| `bd_i/mvchan_1` | 0 | **28,836 (100 %)** | 0 |
| `bd_i/mvchan_2` | 0 | **28,820 (100 %)** | 0 |
| `bd_i/mvchan_3` | 0 | 0 | **28,797 (100 %)** |
| `bd_i/seq_0` | 0 | **7,408 (100 %)** | 0 |

and the dedicated-block half, from `report_utilization`'s SLR section
(`046_po2_best_reports.txt`):

| resource | SLR0 | SLR1 | **SLR2** |
|---|---|---|---|
| **URAM** | **0** | **0** | **182 = 56.88 %** |
| **DSP** | 3 | 12 | **1,843 = 80.83 %** |
| Block RAM Tile | 25.5 | 113 | 108.5 |
| CLB LUT | 15,507 | 141,215 | 149,590 |
| CLB Registers | 21,490 | 181,883 | 114,493 |

**This is the single most useful thing this campaign measured.** The floorplan
existed to force one outcome: the whole layer in one SLR, its 182 URAM and
~1,838 DSP together, no SLL crossing on the state paths. **The placer produces
exactly that outcome with no pblock at all** — 182 URAM in one SLR and **0** in
the other two, 1,843 of the design's 1,858 DSPs beside them at 80.83 % of that
SLR's budget, and `layer_0` 100 % in one SLR to within 2 slices of 204,151.

It simply picks a **different** SLR. S5 reasoned SLR1, because `ddr4_1` and
`ddr4_2` anchor there and it is the middle die
(`synth/constraints/fable5_floorplan_9b_1slr.xdc`'s header). The placer picks
**SLR2**, and puts three of the four matvec channels plus the sequencer in SLR1
instead. **That is the mechanism behind section 4.7's 0.879 ns**: the ctx XDC
pins the layer into SLR1 while `synth/constraints/fable5_floorplan_a.xdc` pins `mvchan_1` and
`mvchan_2` into the *same* SLR1 — 202,527 leaf cells of layer plus two whole
channels competing for one die — so both get stretched. Unconstrained, the
placer separates them onto different dies. The two XDCs were each individually
reasonable and are together over-subscribed, which is a thing only the
in-context run could show.

**D**, the DSP arithmetic that makes it concrete: layer 1,838 + two channels is
1,838 + 2x~2 DSP, which fits — but the LUT does not. SLR2 holds 149,590 LUTs
for the layer alone; SLR1 holds 141,215 for three channels and the sequencer.
Forcing layer + 2 channels into one SLR asks for roughly 149,590 + 2/3 x
141,215 ~ 243,700 LUTs against an SLR's ~394,000 raw — feasible on paper,
which is why the capacity check passed, and evidently not feasible for the
router, which is why `fp1_Default` did not route at all (section 4.6).

### 5.3 The endpoint owner tally

`synth/scripts/census_035.tcl`'s `OWNER` tally over the failing setup paths
(`043_census_po2.log`). **Note the instrument's cap**: `synth/scripts/census_035.tcl` asks
for `-max_paths 5000`, so `CENSUS_COUNT: 5000` is the LIMIT, not the count; the
true total is **6,090** from the design summary. The tally below is therefore
of the 5,000 worst, and the proportions, not the absolute numbers, are what it
supports.

| owner | endpoints (of the 5,000 worst) | kind |
|---|---|---|
| **`bd_i/layer_0/inst`** | **4,669 (93.4 %)** | custom |
| `bd_i/axi_smc/inst` | 189 | vendor (SmartConnect) |
| `bd_i/mvchan_3/inst` | 104 | custom |
| `bd_i/axil_slice_4/inst` | 19 | vendor |
| `bd_i/xdma_0/inst` | 9 | vendor |
| `bd_i/axil_slice_5/inst` | 7 | vendor |
| `bd_i/axil_smc/inst` | 3 | vendor |

**The layer owns 93.4 % of the deficit.** Vendor IP contributes 218 of 5,000
(4.4 %), which is the same order as build_035's 233 of 2,773 and is not the
problem here.

### 5.4 The family census — every family, and what owns the WNS

`evidence/qwen9b/g5/g5b_family_census.tcl` on the same checkpoint
(`045_family_census_po2.log`). `cells` is the family's endpoint CELL count, not
an endpoint count.

| family | cells | worst slack | levels | datapath | logic | route | route % | start SLR | end SLR |
|---|---|---|---|---|---|---|---|---|---|
| `DN_SLOT` | 4,230 | **−0.231** | 1 | 3.772 | 0.204 | 3.568 | **94.6** | SLR2 | SLR2 |
| `KV_SLOT` | 4,329 | **−0.234** | 2 | 3.597 | 0.330 | 3.267 | **90.8** | SLR2 | SLR2 |
| `CV_SLOT` | 540 | **+0.090** | 3 | 3.449 | 0.451 | 2.998 | 86.9 | SLR2 | SLR2 |
| `SDMA` | 27,867 | **−0.244** | 4 | 4.104 | 0.482 | 3.622 | 88.3 | SLR2 | SLR2 |
| `ATTN_DSP` | 81,244 | **−0.243** | 4 | 4.505 | 0.368 | 4.137 | **91.8** | SLR2 | SLR2 |
| `SCRATCH` | 303 | **−0.212** | 1 | 3.689 | 0.118 | 3.571 | **96.8** | SLR2 | SLR2 |

**Every family's worst path starts and ends in SLR2.** There is not one SLR
crossing left on any of them, which is the property the floorplan was for.

Histogram of the 200 worst setup paths in the design:

| family | paths | worst |
|---|---|---|
| **`LAYER_OTHER`** | **108** | **−0.247** ← owns the design WNS |
| `ATTN_DSP` | 42 | −0.243 |
| `VENDOR_SMC` | 35 | −0.233 |
| `SDMA` | 8 | −0.244 |
| `KV_SLOT` | 3 | −0.234 |
| `OTHER` | 3 | −0.240 |
| `DN_SLOT` | 1 | −0.231 |

**Everything is within 0.035 ns of everything else.** The design is not held by
one path or one family; it is a flat wall at ~−0.24 across six families and
1,300 endpoints of margin apiece. That shape matters for what can fix it: there
is no single cone to cut.


### 5.5 What owns the WNS, decomposed — and it is NOT a routing problem

`synth/scripts/census_035.tcl`'s route/logic split of the four worst paths
(`route = DATAPATH_DELAY − DATAPATH_LOGIC_DELAY`), **T**:

| slack | logic | route | total | endpoint |
|---|---|---|---|---|
| **−0.247** | **2.596 (66.8 %)** | 1.289 | 3.885 | `layer_0/inst/u_core/dn_vdata_reg[7]/D` |
| −0.247 | 0.239 (6.3 %) | **3.583 (93.7 %)** | 3.822 | `layer_0/inst/u_core/u_dn/g_lane[84].p2_p_reg[84]/DSP_A_B_DATA_INST/B[1]` |
| **−0.247** | **2.557 (63.5 %)** | 1.467 | 4.024 | `layer_0/inst/u_core/at_qdata_reg[0]_rep__6/D` |
| **−0.247** | **2.553 (65.0 %)** | 1.372 | 3.925 | `layer_0/inst/u_core/dn_vdata_reg[10]/D` |

**Three of the four worst paths in this design are LOGIC-dominated, and they
are the same path.** Their startpoints are `smem_a_reg_bram_8/CLKBWRCLK`,
`smem_a_reg_bram_0/CLKBWRCLK` and `smem_a_reg_bram_16/CLKBWRCLK` — the
**scratchpad block RAM** — and their endpoints are `dn_vdata_reg` and
`at_qdata_reg`, the registers that take a scratchpad word into the DeltaNet and
attention datapaths. Each carries **~2.55 ns of pure logic** against a 4.000 ns
period: a combinational cone between the scratchpad read port and the consuming
register that occupies **64 % of the clock**.

**This is the finding that decides what the next cycle should be, and it is why
more placement rolls are the wrong lever.** A path that is 64 % logic does not
move for a floorplan, a placer directive or a `phys_opt` pass — those buy
routing, and there is only 1.29-1.47 ns of routing on these paths to buy. It is
an RTL shape: the scratchpad read mux into `dn_vdata`/`at_qdata` needs a
pipeline stage. The one path in the top four that IS route-dominated (93.7 %,
the `u_dn` row broadcast into the DSP `B` port) is the kind the playbook can
help, and it is already tied at the same −0.247.

The `LAYER_OTHER` family that owns 108 of the 200 worst paths is exactly this
cone: `dn_vdata` and `at_qdata` sit in `u_core` and belong to none of the six
slot/DSP families, which is why the histogram put them in `LAYER_OTHER` rather
than in `SCRATCH` (whose pattern `*smem_*` names the memory cells, not the
registers they feed).

**Precedent, and how it differs.** build_035 had one logic-heavy path in its top
four too — `s_axil_rdata_reg[3]/D` at 72 % logic, which
`evidence/qwen2b/rc/TIMING_035.md` section 6 named as *"the only endpoint in the
top four that is"* RTL-fixable, and noted that cutting it alone would not have
moved WNS because two other paths tied. Here the proportion is reversed: three
of the four are the logic-heavy family, and the tie is at −0.247 across all
four.

### 5.6 The three build_034/035 owner classes, plus the two the state spill added

`synth/scripts/final_verify.tcl` on the same checkpoint (`047_final_verify_po2.log`, rc 0)
asserts each class is still ANALYSED and reports its worst slack. The
comparand is build_035 SHIPPED, which had **zero** failing endpoints in every
class (`evidence/qwen2b/rc/TIMING_035.md` section 13.6), so every negative
below is a regression against it by construction.

| class | build_035 shipped | best roll here | verdict |
|---|---|---|---|
| **`matvec_engine`** — the W8 `xline_q0/CE` cone | 0 EP; +0.077 … +0.221 across four channels | **0 negative**; mvchan_0 **+0.009**, 1 **+0.185**, 2 **+0.047**, 3 **+0.072** | **KEPT CLOSED.** `XLINE_CE_NEGATIVE_COUNT: 0` over 1,000 paths and 4,096 CE pins. Margin is thinner on ch0 (+0.009 vs +0.173) but positive on all four |
| **`layer_0` — the caches** | class did not exist (banked array) | DN_SLOT **−0.231**, KV_SLOT **−0.234**, CV_SLOT **+0.090** | **NEGATIVE, new structures.** S5 had all three POSITIVE out of context (+0.208 / +0.120 / +0.340) |
| **`layer_0` — `u_dma`** | did not exist | **−0.155** (`FV_STILL_CHECKED`), family worst **−0.244** | **NEGATIVE, new.** S5 had SDMA at +0.203 / +0.087 |
| **`layer_0` — `ATTN_DSP`** | 0 EP | **−0.243** | **WORSENED.** S5 had it at +0.109 / +0.034 |
| **`layer_0` — `u_dn`** (the 034/035 class B) | 0 EP; +0.001 at signoff | **−0.244** | **WORSENED** |
| **`seq_0` MOV** (class C) | 0 EP; +0.011 at signoff | **+0.037** | **KEPT CLOSED**, with more margin than build_035 shipped with |

**Two of the six classes are closed and four are not**, and the four that are
not are all inside `layer_0` — consistent with section 5.3's 93.4 %.

**Every S5 family that was positive out of context is negative in context**, by
0.3-0.4 ns: DN +0.208 → −0.231, KV +0.120 → −0.234, SDMA +0.203 → −0.244,
ATTN_DSP +0.109 → −0.243. **D**: −0.439, −0.354, −0.447, −0.352. The
consistency of that offset across four independent families is itself
informative — it is not one family that regressed, it is the whole layer paying
roughly the same 0.35-0.45 ns for being in context rather than alone on the
die.

**`FV_FAILING_SETUP: 5000` is the script's cap, not a count.**
`synth/scripts/final_verify.tcl` asks `get_timing_paths -max_paths 5000`; the design has
**6,090**. The marker is recorded as it printed and read with that caveat.

**The exception XDC was applied in that run and changes nothing material.**
`synth/scripts/final_verify.tcl` takes `synth/constraints/fable5_xdma_rst_exception.xdc` —
the one-line `set_false_path` the user chose over a waiver for build_035
(`evidence/qwen2b/rc/TIMING_035.md` section 13.1) — and `FV_WNS: -0.247` is
identical to the un-excepted design summary. It cannot help here: it is scoped
`-to */udma_wrapper/dma_top/user_rst_*_reg*/CLR` inside `xdma_0`, and `xdma_0`
owns 9 of 5,000 failing endpoints while the WNS is owned by `layer_0`.


---

## 6. THE SECOND SPREAD — the playbook's reroll, from the unconstrained position

`TAG=po3`, four more directives, **no XDC**, same full recipe, same build_040
project. `evidence/qwen9b/g5/042_spread_po3_nofloorplan.log`, rc 0, launched
12:36 and finished 17:58. Every row **T** from that roll's own fullimpl.log.

| roll | directive | **WNS** | **WHS** | `WHS_GATE:` |
|---|---|---|---|---|
| **`po3_ExtraTimingOpt`** | `ExtraTimingOpt` | **−0.163** | +0.001 | OK |
| `po2_AltSpreadLogic_high` | `AltSpreadLogic_high` | −0.247 | 0.000 | OK |
| `po3_Explore` | `Explore` | −0.365 | 0.000 | OK |
| `po3_WLDrivenBlockPlacement` | `WLDrivenBlockPlacement` | −0.552 | +0.001 | OK |
| `po3_AltSpreadLogic_medium` | `AltSpreadLogic_medium` | −0.595 | 0.000 | OK |

**Five unconstrained rolls span −0.163 … −0.595, a 0.432 ns spread, and none
reaches 0.000.** That is the same shape build_035 saw and recorded as a warning
(`evidence/qwen2b/rc/TIMING_035.md` section 13.5: seven rolls spanning
−0.004 … −0.428, and *"No roll ever measured 0.000"*). `WHS_GATE: OK` on every
one; **no `WHS_GATE: NEGATIVE` anywhere in this campaign's ten rolls.**

### 6.1 The best-WNS roll is NOT the best roll on every axis

`po3_ExtraTimingOpt` wins WNS by 0.084 ns, and the census says it buys that
somewhere. Both rolls, side by side, each from its own reports:

| | `po3_ExtraTimingOpt` | `po2_AltSpreadLogic_high` |
|---|---|---|
| WNS | **−0.163** | −0.247 |
| TNS | **−325.573** | −542.860 |
| failing setup EP | **5,024** of 1,316,849 | 6,090 of 1,316,897 |
| WHS / failing hold | +0.001 / **0** | 0.000 / **0** |
| **clocks with failures** | **3 of 6** | **1 of 6** |
| ch2 UI (`mmcm_clkout0_3`) | **−0.161**, 1,126 EP | **0.000**, 0 EP |
| ch3 UI (`mmcm_clkout0_1`) | **−0.137**, 652 EP | **0.000**, 0 EP |
| `xdma_0_axi_aclk` | −0.163, 3,246 EP | −0.247, 6,090 EP |
| **W8 `xline_q0/CE` cone** | **677 NEGATIVE**, worst **−0.161** | **0 negative**, +0.009 … +0.185 |

**D**: 1,126 + 652 + 3,246 = 5,024, reconciling with its design summary.

**Two things about that table matter more than the 0.084 ns.**

**First, `ExtraTimingOpt` breaks the W8 cone.** `XLINE_CE_NEGATIVE_COUNT: 677`
with mvchan_2 at −0.161 and mvchan_3 at −0.136
(`evidence/qwen9b/g5/049_census_eto.log`). That cone is the subject of
`evidence/qwen2b/rc/RC_W8_GATE.md`'s outstanding debt, the thing build_035 closed with margin on
all four channels, and the reason `synth/scripts/census_035.tcl` reports it by name at all.
`AltSpreadLogic_high` keeps it clean. A roll that wins WNS by breaking a class
the project tracks separately is not obviously the better candidate, and the
choice is not this document's to make.

**Second, it fails on three clocks where the other fails on one.** The pass
criterion is WNS >= 0 **on all clocks**. `AltSpreadLogic_high` has four DDR UI
domains and `pipe_clk` closed and one clock to fix; `ExtraTimingOpt` has spread
the deficit into two of the 300 MHz DDR UI domains that were closed.

### 6.2 The placer's SLR choice REPRODUCES

`synth/scripts/slr_census.tcl` on `po3_ExtraTimingOpt`
(`evidence/qwen9b/g5/050_slr_census_eto.log`), against the same census on
`po2_AltSpreadLogic_high` (section 5.2):

| instance | `ExtraTimingOpt` | `AltSpreadLogic_high` |
|---|---|---|
| `bd_i/layer_0` | **SLR2 204,444 (100 %)**, SLR1 2 | **SLR2 204,149 (100 %)**, SLR1 2 |
| `bd_i/mvchan_0` | SLR1 28,823 | SLR1 28,835 |
| `bd_i/mvchan_1` | SLR1 28,842 | SLR1 28,836 |
| `bd_i/mvchan_2` | SLR1 28,836 | SLR1 28,820 |
| `bd_i/mvchan_3` | SLR2 28,840 | SLR2 28,797 |
| `bd_i/seq_0` | SLR1 7,408 | SLR1 7,408 |

**Two independent placements, different directives, identical partition** — the
layer alone in SLR2, three channels and the sequencer in SLR1, `mvchan_3` with
the layer. To within a couple of hundred slices out of 204,000 and two slices
of leakage into SLR1 in both.

**That is not placer noise; it is the placer solving the same problem the same
way twice.** It also means the floorplan's error was specific and diagnosable:
not *"do not put the layer in one SLR"* — the placer wants the layer in one SLR
— but *"not that SLR, and not while `synth/constraints/fable5_floorplan_a.xdc` is putting two
channels in it."*


---

## 7. UTILIZATION — the state spill's price, on the device

Device totals from the best roll's own `report_utilization`
(`evidence/qwen9b/g5/046_po2_best_reports.txt`), against build_035 SHIPPED
(`evidence/qwen2b/rc/TIMING_035.md` section 8b). Both are post-route,
both are what would ship.

| resource | build_035 shipped | **build_040 best roll** | delta | |
|---|---|---|---|---|
| **CLB LUTs** | 277,965 → **299,076** | **306,312 (25.91 %)** | **+7,236** | **D**: +2.4 % |
| — LUT as Logic | 260,396 | 256,409 | −3,987 | |
| — LUT as Memory | 33,724 | **49,903** | **+16,179** | distributed RAM +10,056 |
| SRLs (LUT as Shift Register) | 4,956 | 6,123 | +1,167 | |
| **CLB Registers** | 292,520 | **317,866 (13.44 %)** | **+25,346** | **D**: +8.7 % |
| **CARRY8** | 13,681 | **11,727 (7.94 %)** | **−1,954** | **D**: −14.3 % |
| **Block RAM Tile** | 561 (+31 RAMB18) | **247** | **−314** | **D**: −56.0 % |
| **URAM288** | **348 (36.25 %)** | **182 (18.96 %)** | **−166** | **D**: −47.7 % |
| **DSP48E2** | 1,858 (27.16 %) | **1,858 (27.16 %)** | **0** | |

**The state spill's headline is the URAM row and it landed exactly as
specified.** 348 → **182**: the 2B design's on-chip state is replaced by two
cache slots per kind (DN 2x29 + KV 2x58 + CV 2x4 = 182, spec section 3), and
the difference lives in DDR behind `state_dma`. Block RAM falls with it,
−314 tiles, because the KV exponent memories and the conv state moved too.

**And the resource that binds is unchanged.** DSP is **identical at 1,858** —
the 9B layer's 1,838 plus the channels' handful is, to the unit, what the 2B
design used. The DSP row is why S5 called DSP the tight resource, and it is
still 80.83 % of one SLR (section 5.2) with the layer gathered there.

**LUT as Memory is the one row that grew sharply**, +16,179 (+48 %), almost all
distributed RAM. That is the ownership-mux and DMA-queue machinery S2 added
around the slots, and it is the price spec A1.2 said would be paid in LUT
rather than in timing. It is 8.43 % of the device's distributed-RAM capacity
and is not near any limit.

**Nothing here is a fit problem.** The largest device utilization on this build
is 25.91 % (LUTs); URAM is 18.96 %, DSP 27.16 %, block RAM 11.44 %. The design
is not close to full on any axis, which is worth stating plainly because it
rules out the simplest explanation for the timing deficit: **this build does
not fail timing because the part is full.**


---

## 8. THE PLAYBOOK'S LAST STEP, AND WHERE IT STOPS

The house closure playbook is census -> reroll spread -> post-route `phys_opt`.
Sections 5-7 are the census, section 6 the spread. This is the third step, run
on the best roll (`po3_ExtraTimingOpt`) with
`evidence/qwen9b/g5/g5b_physopt_playbook.tcl` — `synth/scripts/po_035.tcl`
with its two hardcoded build_035 paths taken as arguments and nothing else
changed. Log `evidence/qwen9b/g5/048_physopt_playbook_eto.log`, rc 0, 18:04 ->
21:41 (**3h37m**). Every line **T**:

```
POPB_PASS0:                      WNS=-0.163 WHS=0.001
POPB_AFTER_AlternateReplication: WNS=-0.151 WHS=0.001   POPB_NEWBEST: -0.151
POPB_AFTER_AggressiveFanoutOpt:  WNS=-0.150 WHS=0.001   POPB_NEWBEST: -0.150
POPB_AFTER_Explore:              WNS=-0.130 WHS=0.000   POPB_NEWBEST: -0.130
POPB_AFTER_AggressiveExplore:    WNS=-0.130 WHS=0.000
POPB_FINAL:                      WNS=-0.130 WHS=0.000
POPB_NOT_CLOSED
```

**WNS/TNS before and after every step**, as the user's standing rule requires:

| step | WNS | delta | WHS |
|---|---|---|---|
| in (post-route phys_opt of the roll) | −0.163 | — | +0.001 |
| after `AlternateReplication` | −0.151 | **+0.012** | +0.001 |
| after `AggressiveFanoutOpt` | −0.150 | **+0.001** | +0.001 |
| after `Explore` | −0.130 | **+0.020** | 0.000 |
| after `AggressiveExplore` | −0.130 | **0.000** | 0.000 |
| after `route_design -preserve` | **−0.130** | 0.000 | **0.000** |

**D**: the whole playbook step is worth **+0.033 ns**, and its last directive
is worth **nothing**. `AggressiveExplore` returning the number unchanged is the
saturation signature build_034 and build_035 both recorded
(`evidence/qwen2b/rc/TIMING_035.md` section 3, *"saturated, as it did on 034"*).
**The hold guard never fired** — WHS stayed non-negative through every pass, so
no setup was traded for hold.

`POPB_NOT_CLOSED`: the script emits a bitstream only when WNS >= 0 **and**
WHS >= 0, so the absence of a `.bit` in that directory is itself the gate's
verdict.

### 8.1 The final artifact, measured

`synth/out_g5b_po_eto/bd_wrapper_po_routed.dcp`, re-derived independently by
`synth/scripts/final_verify.tcl` in a fresh session
(`evidence/qwen9b/g5/055_final_verify_popb.log`, rc 0) and quoted from its own
reports in `evidence/qwen9b/g5/056_final_artifact_reports.txt`:

```
FV_WNS: -0.130          FV_WHS: 0.000
FV_FAILING_SETUP: 4265  FV_FAILING_HOLD: 0
FV_XLINE_PATTERN: *u_engine/xline_q0_reg*/CE
FV_XLINE_WORST_mvchan_0: 0.003   mvchan_2: -0.130   mvchan_3: -0.097
FV_STILL_CHECKED *layer_0*u_core/u_dn/*/D    slack=-0.122
FV_STILL_CHECKED *layer_0*u_core/u_dma/*/D   slack=-0.102
FV_STILL_CHECKED *layer_0*u_core/u_attn/*/D  slack=-0.122
FV_STILL_CHECKED *seq_0*u_seq/*/D            slack=0.038
FV_STILL_CHECKED *u_engine/xline_q0_reg*/CE  slack=-0.130
FV_OK
```

**`FV_FAILING_SETUP: 4265` is a true count here, not the cap** — 4,265 is below
`synth/scripts/final_verify.tcl`'s `-max_paths 5000` and it reconciles exactly with the
design summary's 4,265. (On the two earlier signoffs the marker read 5000 and
was the cap; section 5.6 says so.)

Design summary and per-clock, `056_final_artifact_reports.txt`:

| | value |
|---|---|
| WNS | **−0.130** |
| TNS | **−227.826** |
| failing setup EP | **4,265** of 1,316,849 |
| WHS / THS / failing hold | 0.000 / 0.000 / **0** of 1,313,713 |
| WPWS / pulse-width failures | 0.000 / **0** of 391,607 |

| clock | WNS | TNS | failing EP | WHS |
|---|---|---|---|---|
| `mmcm_clkout0` (ch0 UI) | **+0.003** | 0.000 | **0** | +0.010 |
| `mmcm_clkout0_2` (ch1 UI) | **0.000** | 0.000 | **0** | +0.011 |
| **`mmcm_clkout0_3`** (ch2 UI) | **−0.130** | −42.014 | **866** | +0.008 |
| **`mmcm_clkout0_1`** (ch3 UI) | **−0.102** | −26.665 | **539** | +0.002 |
| `pipe_clk` | **+0.104** | 0.000 | **0** | +0.013 |
| **`xdma_0_axi_aclk`** | **−0.122** | −159.147 | **2,860** | 0.000 |

**D**: 866 + 539 + 2,860 = 4,265, reconciling with the summary.

**Note what moved.** The playbook pulled `xdma_0_axi_aclk` from −0.163 to
−0.122, and in doing so the design's WNS owner became a **DDR UI domain**
(ch2 at −0.130), not the layer's clock. Three of six clocks fail.


---

## 9. THE CAMPAIGN TABLE, COMPLETE

Eleven implementation runs on one netlist (`VERSION 82b54bac`), plus four
`create_project` failures before it. Every WNS/WHS **T** from that roll's own
fullimpl.log or build_run.log.

| # | roll / artifact | XDCs | directive | recipe | **WNS** | **WHS** | `WHS_GATE:` | failing EP |
|---|---|---|---|---|---|---|---|---|
| 0 | `build_040` | none | project default | none | −0.988 | +0.010 | n/a | 52,609 |
| 1 | `fp1_ExtraTimingOpt` | A + ctx | `ExtraTimingOpt` | full | −0.996 | 0.000 | OK | — |
| 2 | `fp1_AltSpreadLogic_high` | A + ctx | `AltSpreadLogic_high` | full | −1.126 | 0.000 | OK | — |
| 3 | `fp1_AltSpreadLogic_medium` | A + ctx | `AltSpreadLogic_medium` | full | −1.333 | +0.001 | OK | — |
| 4 | `fp1_Default` | A + ctx | `Default` | full | **route FAILED** | — | — | 1,340 node overlaps |
| 5 | `fp2_AltSpreadLogic_high` | A only | `AltSpreadLogic_high` | full | −0.768 | 0.000 | OK | — |
| 6 | `po2_AltSpreadLogic_high` | none | `AltSpreadLogic_high` | full | −0.247 | 0.000 | OK | 6,090 |
| 7 | `po3_AltSpreadLogic_medium` | none | `AltSpreadLogic_medium` | full | −0.595 | 0.000 | OK | — |
| 8 | `po3_WLDrivenBlockPlacement` | none | `WLDrivenBlockPlacement` | full | −0.552 | +0.001 | OK | — |
| 9 | `po3_Explore` | none | `Explore` | full | −0.365 | 0.000 | OK | — |
| 10 | `po3_ExtraTimingOpt` | none | `ExtraTimingOpt` | full | **−0.163** | +0.001 | OK | 5,024 |
| 11 | **`out_g5b_po_eto` (playbook)** | none | (post-processing of #10) | full + 4 phys_opt | **−0.130** | **0.000** | n/a (`POPB_NOT_CLOSED`) | **4,265** |

**No `WHS_GATE: NEGATIVE` on any roll**, and **zero failing hold endpoints** on
every artifact measured. The hold half of the criterion is met throughout.

**The setup half is not met anywhere.** Best = **−0.130**, and the gate needs
**>= 0.000**.

### 9.1 Waiver decisions

**There are none, because none was taken.** No waiver was applied, proposed as
applied, or assumed. The one constraint in play, `synth/constraints/fable5_xdma_rst_exception.xdc`
— which is a *constraint the user chose over a waiver* for build_035
(`evidence/qwen2b/rc/TIMING_035.md` section 13.1) — was applied in the
`final_verify` runs and **changes WNS by nothing** on this design (section 5.6),
because it is scoped inside `xdma_0` and the deficit is inside `layer_0`.

`synth/scripts/full_impl.tcl` and `evidence/qwen9b/g5/g5b_physopt_playbook.tcl` both refuse to
call a roll closed below zero, and `POPB_NOT_CLOSED` is that refusal firing.

### 9.2 The artifacts, and why none is a Task 15 candidate

`VERSION` = **`82b54bac`** on all of them — `git rev-parse --short=8 HEAD` at
`synth/scripts/launch_build.sh` time, tree `82b54ba` clean. **T**, from
`evidence/qwen9b/g5/056_final_artifact_reports.txt`:

| artifact | bytes | mtime | WNS |
|---|---|---|---|
| `synth/out_g5b_po_eto/bd_wrapper_po_routed.dcp` (best) | 290,287,336 | 2026-09-06 21:41:11 | **−0.130** |
| `synth/out_build_040_po3_ExtraTimingOpt/…/bd_wrapper.bit` | 50,901,125 | 2026-09-06 17:30:42 | −0.163 |
| `synth/out_build_040_po2_AltSpreadLogic_high/…/bd_wrapper.bit` | 51,319,689 | 2026-09-06 12:24:13 | −0.247 |
| `synth/out_build_040/…/bd_wrapper.bit` (baseline) | 51,024,377 | 2026-09-06 00:20:15 | −0.988 |

**BITSTREAM: none of these ships.** The best artifact is a checkpoint, not a
bitstream, precisely because the playbook script refuses to write one below
zero. The three `.bit` files exist because Vivado's `write_bitstream` step runs
regardless of timing; each is a routed implementation of a design that does not
meet timing, and **none is a candidate for Task 15**. **The board was not
touched at any point in this task** and still carries the 2B
`build_035_fp2a_exc_po` bitstream.

---

## 10. VERDICT — **THE GATE FAILS. ESCALATION, NOT A WAIVER THIS AGENT CAN TAKE.**

**The pass criterion**: WNS >= 0.000 and WHS >= 0.000 on all clocks, zero
failing endpoints, no waiver — what build_035 achieved, and the standard this
project set for itself.

**The measurement**: WNS **−0.130** on the best of eleven implementation runs,
**4,265 failing setup endpoints**, **three of six clocks** failing. Hold is
clean everywhere (WHS 0.000, zero failing hold endpoints, no `WHS_GATE:
NEGATIVE` in the campaign).

**The gap is 0.130 ns**, and the house playbook is spent: census done, ten-roll
spread done spanning 0.432 ns with no roll near zero, post-route `phys_opt`
done and saturated on its last directive. **A negative WNS is not a pass and is
not this agent's to accept** — build_035's own record is that waiving −0.004
was **declined by the user** (`evidence/qwen2b/rc/TIMING_035.md` section 13.1),
and this is 32x that number.

### 10.1 What the evidence says the next move is — for the user to decide

Three findings constrain the options, and each is measured, not inferred.

**(1) The floorplan is not the lever, and the placer already does its job.**
The layer-in-one-SLR goal is achieved with no pblock at all (section 5.2), and
adding pblocks costs **0.879 ns** monotonically (section 4.7). Task 13's and
S5's floorplan work is not wasted — it established what the layout should look
like — but there is no floorplan edit left that this campaign's evidence
supports. Re-pinning the layer to SLR2 and the channels away from it is the one
untried variant, and it would be asking the placer to do what it already does.

**(2) More rolls are low-yield.** Five unconstrained rolls span
−0.163 … −0.595. Drawing again from that distribution has some chance of
beating −0.163, but the playbook then adds only ~0.033, and the distance to
zero is 0.130. **D**: the best roll plus the full playbook lands 0.130 short;
a roll would have to be ~0.16 ns better than the best of five to close, which
is outside the spread observed.

**(3) The residual is partly LOGIC, and that is an RTL question.** On
`po2_AltSpreadLogic_high` three of the four worst paths carry **2.55-2.60 ns of
logic in a 4.000 ns period** — the scratchpad block RAM into `dn_vdata_reg` /
`at_qdata_reg` (section 5.5). On `po3_ExtraTimingOpt` the logic-heavy pair are
`u_conv/u_silu/m3_reg` at 2.316 and `s_axil_rdata_reg[4]/D` at 2.725 — and that
second one is **the same AXI-Lite readback mux build_035 named as its only
RTL-fixable path** (`evidence/qwen2b/rc/TIMING_035.md` section 6). Placement
buys routing; these paths do not have enough routing left to buy.

**The options this document can put to the user, without recommending one:**

* **A — an RTL pipeline stage** on the scratchpad read into the DN/attention
  datapaths, and on the AXI-Lite readback mux. Directly attacks the
  logic-dominated cones. Cost: it reopens the frozen RTL that S4 replayed
  bit-exactly, so it needs the replay re-run — it is not a free change.
* **B — relax the clock.** 250 MHz is 4.000 ns; the deficit is 0.130 ns, i.e.
  **3.25 %**. **D**: 1/(4.000 + 0.130) = **242.1 MHz** would close the setup
  side outright with no RTL change. The cost is throughput and it touches the
  XDMA `axisten_freq` and every derived number in the perf model.
* **C — keep rolling.** Honest odds are in (2): low, and each cycle is 6-10
  hours of snoke.
* **D — a waiver.** Named for completeness and **not recommended by this
  document**: 4,265 failing endpoints across three clocks is not the shape of
  anything this project has waived, and the precedent is that a 6-endpoint,
  −0.004 waiver was declined.

**This is where Task 14 stops.** The orchestrator prompts; the user decides.

### 10.2 What this build DID establish, and it is not nothing

* The state-spill netlist builds, routes and produces a bitstream in context —
  **182 URAM, 1,838 DSP, matching S5 to the unit** (section 3.2).
* **`state_dma` is in the design and on the right clock**, with no CDC inferred
  on its path to the SmartConnect (section 1.7), after two harness defects that
  would each have shipped silently.
* **Hold is clean everywhere** — 0 failing hold endpoints on every artifact,
  no `WHS_GATE: NEGATIVE` in eleven runs. build_035 shipped on +0.000 hold and
  flagged it as a bring-up risk; this design is no worse.
* **Two of the six tracked endpoint classes are closed** — `matvec_engine`'s W8
  cone (on the `AltSpreadLogic_high` family of rolls) and `seq_0` MOV
  (everywhere, at +0.037/+0.038).
* **The floorplan question is settled with a controlled experiment** rather
  than an opinion, and the placer's own partition is now known and reproducible.
* **The part is not full** — 25.91 % LUT, 18.96 % URAM, 27.16 % DSP.

## 11. WHAT IS *NOT* ESTABLISHED

* **Nothing about the board.** No bitstream was programmed; no DMA, no CSR
  read, no token. Every number here is from static timing analysis of a routed
  design.
* **No perf figure.** S4's DMA-lane 5.133 ms/token is MODELLED at LAT 8 and is
  not quoted here as anything else; the compute-lane 45.674 ms/token is S4's
  too. Neither is a board measurement and neither is affected by this task.
* **Whether `po3_ExtraTimingOpt`'s W8 regression is intrinsic to that
  directive** or to that placement draw. One roll of each is not a
  distribution.
* **Whether option B's 242.1 MHz actually closes.** That is arithmetic on this
  build's WNS, not a build. The four DDR UI domains are 300 MHz and independent
  of the layer clock, and two of them fail on the final artifact — so a
  250 -> 242 MHz change on `axisten_freq` would have to be re-measured, not
  assumed, for those two.


---

## 12. CITATIONS

### 12.1 Drift

Task 14 inserted three blocks into `synth/scripts/create_project.tcl` (the
`rtl/state_dma.sv` source plus the `LAYER_SOURCES_OK` assertion, the `m_axis`
FREQ_HZ block, the CLK_DOMAIN block before `validate_bd_design`), so every
citation into that file below line 69 moved.
`evidence/qwen9b/o3/o3_cite_drift.py --base 3091d4b --doc-base 3091d4b`
repaired **27 citations in four documents**; `--verify` passes with 0 problems
(`O3_CITE_DRIFT VERIFY PASS`).

**Four citations the tool cannot see were repaired BY HAND** from the same
`difflib` map, each checked to land on byte-identical content:

| document | old | new | why the tool missed it |
|---|---|---|---|
| `synth/scripts/ooc_9b.tcl:73` | `synth/scripts/create_project.tcl:69-82` | `synth/scripts/create_project.tcl:69-101` | flagged COLLATERAL — line 69 does not move, so the staleness test passes while the range END is stale |
| `synth/exp_uram/scripts/exp_ooc.tcl:158` | `synth/scripts/create_project.tcl:69-82` | `synth/scripts/create_project.tcl:69-101` | written bare, without the `synth/scripts/` prefix the CITE regex needs |
| `docs/ARCHITECTURE.md:187` | `synth/scripts/create_project.tcl:391-418` | `synth/scripts/create_project.tcl:450-477` | same |
| `docs/RUNG3_SPEC.md:29` | `synth/scripts/create_project.tcl:230-244` | `synth/scripts/create_project.tcl:249-263` | same |

**One citation is deliberately NOT repaired**, and this is the record of why.
`evidence/qwen2b/rb/TIMING.md:574` cites `synth/scripts/create_project.tcl:416-433` for an
R-b-era assertion of *"131072 / 128K"*. At the drift base `3091d4b` that line
**already** read `256 KiB of scratch` — G3.1 superseded it long before this
task — so the citation is content-stale independently of any line movement.
Renumbering it would aim the same wrong prose at a fresh coordinate and make an
unchecked citation look checked. It is a sha-pinned historical record, excluded
by hand.

### 12.2 `spec_cites`, and two pre-existing failures that are NOT this task's

The final `spec_cites` run covers the documents Task 14 created or edited and
that it can hold at **FAIL 0**: this gate document,
`docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md` and
`docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md`.

**Two documents the drift repair touched are NOT in it, and their failures are
demonstrably older than this task.** `evidence/qwen9b/g3/G3_1_ISA.md` reports
6 QUOTE failures and `evidence/qwen9b/s2/S2_RTL.md` reports 1, all of them
quotations of `sw/chat_seq.py`, `ref/gen_layer_script.py`, `rtl/layer_chan.sv`
and `tb/tb_layer_sdma.sv` — **files this task never edited**. The proof is
positional and mechanical rather than an assertion:

| document | line ranges THIS TASK changed (`git diff ef0d887 HEAD`) | lines that FAIL |
|---|---|---|
| `evidence/qwen9b/g3/G3_1_ISA.md` | 780-788, 891-898 | **550, 551, 552, 555, 556, 557** |
| `evidence/qwen9b/s2/S2_RTL.md` | 467-480 | **352** |

No failing line is inside any hunk this task wrote, and every failing citation
names a source file outside this task's commit block. The same class shows up
on the migration **spec** (8 QUOTE failures at
the migration spec at lines 216, 219, 222, 923, 944, 950, 1433 and 2558), a document this task did not
open at all. **They are carried forward, unfixed and named here**, because
silently widening the gate's scope to hide them or silently narrowing it
without saying so would both be worse than recording them.

### 12.3 The `PENDING` prune

`evidence/qwen_next/spec_cites.py`'s `PENDING` set named two paths for T14:
`evidence/qwen9b/g5/G5B_TIMING.md` and
`synth/constraints/fable5_floorplan_9b_1slr_ctx.xdc`. **Both landed in this
task, so both are removed.** `PENDING` is checked BEFORE `EXIST`, so a stale
entry would let a typo in either path — or a deletion of the file — pass
silently on every document that cites it. That is the S5 lesson, applied on the
task that created the files rather than a round later.
