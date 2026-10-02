# S5 — structure and placement: the OOC counts and the one-SLR floorplan

**Task S5 of the Qwen3.5-9B state-spill amendment. THE STRUCTURAL GATE the
amendment exists for.** S1–S4 built the ISA, the RTL, the chain and the proof
that the whole 9B model on the new RTL decodes Task 11's tokens bit-exactly
(`evidence/qwen9b/s4/S4_REPLAY.md`). S5 asks the two questions that decide
whether Task 14's full build has a floorplan to start from:

1. does the state-spill layer synthesize to the **182 URAM288** the spec's
   cache table predicts?
2. does it **place inside ONE SLR**, and what does the ownership mux on the
   cache write ports cost (spec A1.2)?

**The answers are YES and YES — after one attribute.** The first count was
**174**, not 182: eight short, and the eight were exactly the conv slots,
whose two memories carried no `ram_style` while the DN and KV slot memories
carried `(* ram_style = "ultra" *)`. That is the RED this gate exists to
produce and it is kept below, measured, in §2.1–§2.3. The controller ruled
that the RTL follows the approved spec rather than the other way round; fix
round 1 added the attribute, and the re-count from BOTH OOC harnesses is
**182** with block RAM 81 tiles (§2.4). All three placements were re-run on
that netlist, and the two one-SLR runs do not merely land inside the
playbook's reach — they **meet timing post-place**, WNS +0.030 and +0.034
with TNS 0.000 and zero failing setup endpoints (§3.3).

**This document is written in two layers and says which is which.** §2.1–§2.3
and §3.1–§3.2 are the FIRST round, on the 174-URAM netlist, unedited. §2.4,
§3.3–§3.5, §4.4–§4.5 and §7 are fix round 1, on the 182-URAM netlist, and
they are the result. Where a number is superseded the superseding one is
named beside it.

---

## 0. HOW TO READ EVERY NUMBER BELOW — stated before the numbers

This is Task 13's reading rule (`evidence/qwen9b/g5/G5A_FLOORPLAN.md` §0,
itself Track P's `evidence/qwen_next/place_exp/PLACE_EXP.md` §2.1) and it
governs this document unchanged.

**Out-of-context means `layer_chan` ALONE on the whole VU9P.** No XDMA/PCIe/GTs
at their fixed sites, no four DDR4 MIGs anchored to their IO banks, no four
`matvec_chan`s, no `seq_unit`, and none of the ~200 K CLB LUTs a full build
spends outside `layer_0`. Therefore:

* a **failure here is DEFINITIVE** — the in-context problem is strictly harder;
* a **success here is NECESSARY BUT NOT SUFFICIENT** — it is the best case that
  exists, not a prediction of the full build.

**All timing below is POST-PLACE, PRE-ROUTE, PRE-`phys_opt_design`.** The house
playbook's reach is ≈ −0.1 to −0.3 ns at OOC closing at the full build with a
post-route `phys_opt` pass (build_035 closed −0.091 → 0.000 in one pass).

**Directive spread is SAMPLED, NOT CHARACTERISED.** One directive change moved
WNS by 0.475 ns in Track P's own runs (`PLACE_EXP.md` §3.6). S5 samples TWO
directives on the constrained variant and ONE on the baseline, so any gap
below 0.475 ns between two rows here is inside the noise this experiment can
see, and is read that way.

**Label.** Every number in §2–§5 is **T (toolchain-measured)** — Vivado 2024.2
`synth_design -mode out_of_context` (→ `opt_design` → `place_design` for §3–§5)
on `xcvu9p-fsgd2104-2L-e` at 4.000 ns, on snoke, on the SHIPPING `rtl/`.
**D** marks a number derived here with its arithmetic shown; **S** marks a
number stated by a source that is named.

### 0.1 The two stop protocols, and which one fired

| protocol | test | outcome |
|---|---|---|
| **the counts STOP** (brief Step 1) | URAM288 ≠ 182 | **FIRED — 174**, and was ANSWERED. §2.1–§2.3 report it as round 1 measured it, with no RTL edited: the brief reserved the fork for the user. The controller chose the RTL fix; §2.4 is the re-count, **182 from two harnesses**. |
| **the STOP-back** (brief Step 2, spec §12 risk 1) | the one-SLR layer is outside the playbook's reach at OOC | **did NOT fire**, in either round. §3.2: −0.245 and −0.166 on the 174 netlist, both inside ≈ −0.1 … −0.3. §3.3: **+0.030 and +0.034** on the 182 netlist, past the reach and into positive margin. |

Both were written into this document's draft before the runs came back, and
you have only this sentence for that; the thresholds themselves are inherited
(the 182 from spec §3's table, the reach from the timing-closure playbook, the
0.475 ns spread from `PLACE_EXP.md` §3.6), not chosen here to fit.

---

## 1. What ran, where, and on which tree

Every Vivado run is on **snoke** through `bash evidence/qwen9b/run.sh`, whose
header line `=== host: snoke` is in each log.

**One `=== host:` line in this directory means something narrower than it
looks, and §4.1–§4.3 depend on the difference.** Round 1's six collected
per-variant logs — `evidence/qwen9b/s5/s5_base_finish_run.log` and its five
siblings — carry `=== host: darthplagueis`, and so do round 1's two citation
logs `evidence/qwen9b/s5/060_spec_cites.log` and
`evidence/qwen9b/s5/061_spec_cites.log`. That header is written at COLLECTION
time by `synth/exp_uram/scripts/collect_evidence.sh:39` and records where the
COLLECTION ran, not where Vivado ran. The Vivado invocations behind those six
files are `evidence/qwen9b/s5/030_finish_reports.log` and
`evidence/qwen9b/s5/031_family_census.log`; both read `=== host: snoke` and
both print `S5FC_LAUNCH` (not `S5FC_REFUSE`) for all three variants, which is
the guard that refuses to run Vivado anywhere else. So every number in §4 is
off a snoke run, and fix round 1's collected logs read `snoke` throughout.

| log | run | tree at launch | wall | rc |
|---|---|---|---|---|
| `010_ooc_counts.log` | `launch_exp.sh s5_counts … 0` (synth only) | `011ee16` | 20 min | 0 |
| `020_place_base.log` | `s5_base`, no XDC, Default | `011ee16` | 44 min | 0 |
| `021_place_1slr.log` | `s5_1slr`, `synth/constraints/fable5_floorplan_9b_1slr.xdc`, Default | `011ee16` | 47 min | 0 |
| `022_place_1slralt.log` | `s5_1slralt`, same XDC, `AltSpreadLogic_medium` | `011ee16` | 47 min | 0 |
| `011_mem_census.log` | `s5_mem_census.tcl` on `s5_counts/post_synth.dcp` | `18641a1` | 2 min | 0 |
| `030_finish_reports.log` | `synth/exp_uram/scripts/finish_reports.tcl` ×3, concurrent | `282705b` | 4 min | 0 |
| `031_family_census.log` | `s5_family_census.tcl` ×3, concurrent | `282705b` | 4 min | 0 |

**Fix round 1 (2026-09-05)** — the same instruments on the netlist with the
attribute. Every one of these is `=== host: snoke` on a tree with no dirty
flag:

| log | run | tree at launch | wall | rc |
|---|---|---|---|---|
| `evidence/qwen9b/s5/080_lint_layer_chan.log` | `make -C tb lint_layer_chan`, gating the edit before it was committed | `6b88724+dirty` | 2 s | 0 |
| `evidence/qwen9b/s5/081_tb_layer_sdma.log` | `make -C tb tb_layer_sdma`, same | `6b88724+dirty` | 2 min | 0 |
| `evidence/qwen9b/s5/082_lint_layer_chan_clean.log` | the same lint on the committed tree | `5cb1899` | 2 s | 0 |
| `evidence/qwen9b/s5/083_tb_layer_sdma_clean.log` | the same testbench on the committed tree | `5cb1899` | 2 min | 0 |
| `evidence/qwen9b/s5/090_ooc_counts_exp.log` | `launch_exp.sh s5fix_counts … 0` (synth only) | `5cb1899` | 17 min | 0 |
| `evidence/qwen9b/s5/091_ooc_counts_g4b.log` | `run_g4b_ooc.sh s5fix_layer layer_chan`, the REPAIRED `synth/scripts/ooc_9b.tcl` | `5cb1899` | 17 min | 0 |
| `evidence/qwen9b/s5/092_mem_census.log` | `s5_mem_census.tcl` on the `s5fix_counts` run's own `post_synth.dcp` — that DCP was written at `5cb1899`; the census OF it ran later | `56459a6` | 6 min | 0 |
| `evidence/qwen9b/s5/093_lint_layer_chan.log` | the lint again, after the comment moved | `d9cb8e4` | 2 s | 0 |
| `evidence/qwen9b/s5/094_tb_layer_sdma.log` | the testbench again, after the comment moved | `d9cb8e4` | 2 min | 0 |
| `evidence/qwen9b/s5/113_lint_layer_chan.log` | **the lint on the FINAL RTL bytes** | `cdf7d6c+dirty` | 2 s | 0 |
| `evidence/qwen9b/s5/114_tb_layer_sdma.log` | **the testbench on the FINAL RTL bytes**, `240 checks` ×4 | `cdf7d6c+dirty` | 2 min | 0 |
| `evidence/qwen9b/s5/100_place_base.log` | `s5fix_base`, no XDC, Default | `56459a6` | 38 min | 0 |
| `evidence/qwen9b/s5/101_place_1slr.log` | `s5fix_1slr`, `synth/constraints/fable5_floorplan_9b_1slr.xdc`, Default | `56459a6` | 39 min | 0 |
| `evidence/qwen9b/s5/102_place_1slralt.log` | `s5fix_1slralt`, same XDC, `AltSpreadLogic_medium` | `56459a6` | 41 min | 0 |
| `evidence/qwen9b/s5/103_finish_reports.log` | `synth/exp_uram/scripts/finish_reports.tcl` ×3, concurrent | `74cf100` | 5 min | 0 |
| `evidence/qwen9b/s5/104_family_census.log` | `s5_family_census.tcl` ×3, concurrent | `74cf100` | 5 min | 0 |

**Fix round 2 (2026-09-05)** — one run, on the same netlist, so that the
probe §1.1 widened has a committed output of its own. Its tree carries no
dirty flag, because the harness edit was committed before the run that
exercises it:

| log | run | tree at launch | wall | rc |
|---|---|---|---|---|
| `evidence/qwen9b/s5/140_counts_probe.log` | `launch_exp.sh s5fix2_counts … 0` (synth only), the WIDENED probe | `93c7ceb` | 17 min | 0 |

**The run trees are not HEAD, and the difference is measured rather than
argued.** The counts ran at `5cb1899` and the placements at `56459a6`; the
RTL then changed once more (`d9cb8e4`, why in §7.2) and the floorplan XDC
gained a measured-capacity block at its end. `evidence/qwen9b/s5/s5fix_rtl_bytes.sh`
diffs both run trees against HEAD over `rtl/` and
`synth/constraints/fable5_floorplan_9b_1slr.xdc` and requires every changed
line to be comment text: `evidence/qwen9b/s5/115_bytes_comment_only.log` is
`S5FIXRTL: PASS`, 22 changed lines, **0 non-comment**. Its negative control
`evidence/qwen9b/s5/116_bytes_comment_only_control.log` points the same
script at the S2 base and gets `CODE CHANGED`, 1,055 non-comment lines, rc 1.
A comment cannot synthesize — but that is an argument, and this is the
measurement.

**Four logs of this round read `+dirty`, and each says which file.** 080/081
gated the attribute before it was committed — the dirt is the four RTL lines
in the commit they licensed, and 082/083 repeat them on the committed tree.
113/114/115/116 ran at `cdf7d6c+dirty`, where the ONE modified file is THIS
document, which is unavoidable: a gate doc cannot be checked before it is
written and cannot be committed before it is checked. Nothing under `rtl/`,
`synth/` or `evidence/qwen9b/s5/`'s data was modified at any of those moments.

**Fix round 2's eight text-tool logs read `+dirty` too, and the dirt is the
same three files throughout.** 141–144 (§10.2) ran at `f50f939+dirty`, before
the citation repair they licensed was committed; 145–150 (§9.1) ran at
`4df19ec+dirty`, after it. In both cases the modified files are THIS document,
the spec's A2.2 paragraph and `evidence/qwen_next/spec_cites.py`'s `PENDING`
set — the three things the round's last commit-but-one lands, dirty for the
same unavoidable reason a gate doc always is. The one Vivado run of this
round, 140, ran on a CLEAN tree: the harness edit it exercises was committed
first, which is why its header reads `93c7ceb` with no flag. Nothing under
`rtl/` or `synth/out_*` was modified at any of these moments.

The four Vivado runs were launched within four minutes of each other and ran
concurrently on snoke's 48 cores at 8 threads each. **`011ee16` is a clean
tree** — `evidence/qwen9b/run.sh`'s `=== tree:` carries no `+dirty` on any of
the four. Each
run's own `launch_exp.sh` header says `1 dirty files`: that count is
`git status --porcelain`, which sees the run's own untracked log. **Nothing
under `rtl/` was dirty on any run**, which is what the numbers are about.

### 1.1 The harness, and what S5 had to change in it

The vehicle is `synth/exp_uram/scripts/exp_ooc.tcl`, pointed at the SHIPPING
`rtl/` since Task 13. Three of its facts were about the design S2 deleted, and
all three are fixed in `011ee16` before any run:

* **`rtl/state_dma.sv` was not in its file list.** `layer_chan` instantiates it
  (`rtl/layer_chan.sv:705`), so the list as it stood would have elaborated the
  DMA as a black box — a warning, not an error, and every LUT/FF number would
  have been silently short. The list now matches `tb/Makefile`'s `LAYER_RTL`
  (`tb/Makefile:629-633`) file for file.
* **`DN_PIPE` and `DN_BPG` no longer exist**, as `-generic`s or as positional
  arguments; `layer_chan`'s only non-ROM parameter is `SDMA_NOFENCE`
  (`rtl/layer_chan.sv:241`), a testbench knob left at its shipping default 0.
  `launch_exp.sh`'s `-tclargs` line moved with them.
* **the URAM prediction** is the two-slot arithmetic of spec §3, derived from
  row width and depth by a `uram_of` proc rather than typed as a constant:
  `EXP_PREDICT: DN 2 x 29 + KV 2 x 58 + CV 2 x 4 = 182 URAM288`.

**A harness gap round 1 did NOT close — fix round 1 DID.** The brief's Step 1 command is `evidence/qwen9b/g4/run_g4b_ooc.sh`, which
sources `synth/scripts/ooc_9b.tcl` — and that script has the SAME two defects
(no `rtl/state_dma.sv` in its `Files` list — `synth/scripts/ooc_9b.tcl` lines
77-78 as of `6b88724`, written out of citation form because fix round 1 moved
and rewrote both, and a renumbering would point this sentence at text that
does not say what it says it says — and `set PRED 928`, line 167 of the same
file at the same commit). Repairing it would reach
outside S5's commit block, so **the counts in §2 come from `exp_ooc.tcl` with
`place=0` instead**: same part, same `synth_design -top layer_chan -part
xcvu9p-fsgd2104-2L-e -mode out_of_context`, same single `create_clock -period
4.000 -name aclk`, same `report_utilization -file …/util_synth.rpt`. The
report is committed under the name the plan cites,
`evidence/qwen9b/s5/ooc_s5_layer_util_synth.rpt`.

**Fix round 1 repaired it**, since the controller's ruling put
`synth/scripts/ooc_9b.tcl` inside the round's commit block: `state_dma` joins
its `Files` list; `PRED` is no longer the retired `928` but is DERIVED, by the
same `uram_of {depth width}` proc `synth/exp_uram/scripts/exp_ooc.tcl` uses,
as 2 × (29 + 58 + 2 + 2) = 182 — so the two harnesses' predictions cannot
disagree by a typed digit; the split patterns become the S2 slot names
(`g_dnslot`, `g_kvslot`, `g_cvslot`) with a `cv=` field on the URAM split and
a `kvexp=` field on the block RAM one; and the DN-only "fell out of URAM"
probe becomes `OOC9B_SLOT_NONURAM_CELLS` over all three kinds, because a
DN-only probe read **0** on the very netlist whose conv slots had gone to
block RAM. §2.5 is what the repaired harness measured.

**That widening landed in ONE of the two harnesses, and fix round 2 closes the
other** (review round 1, I-2). Round 1 widened `synth/scripts/ooc_9b.tcl` and
left `synth/exp_uram/scripts/exp_ooc.tcl` — the vehicle every one of the six
placements and both count runs actually RAN on — still matching `*g_dn*`,
under a comment that said "Any DN/KV bank". Two things follow, and both are
disclosed rather than argued away:

* **The `EXP_SYNTH_DN_NONURAM_CELLS: 0` quoted inside §2.1's RED block was
  true and uninformative.** It was taken from a netlist whose CONV slots had
  gone to block RAM, and a filter on `*g_dn*` cannot see a conv slot. What
  caught the 174 was `EXP_SYNTH_URAM` against `EXP_PREDICT`, and what located
  the eight missing URAMs was the per-memory census of §2.2 — not this marker.
* **The repaired `OOC9B_SLOT_NONURAM_CELLS` was never run on the 174 netlist
  either.** It came into existence in fix round 1, after the attribute, so no
  committed log anywhere shows a widened probe reading non-zero. §2.6 says
  what that costs and what stands in for it.

Fix round 2 gives `synth/exp_uram/scripts/exp_ooc.tcl` the same three filters,
COPIED from `synth/scripts/ooc_9b.tcl` so the two harnesses cannot drift into
probing different cells: `g_dnslot`, `g_kvslot` minus `emem` (block RAM by
design), `g_cvslot`. `EXP_SYNTH_DN_NONURAM_CELLS` is kept, so the older logs
stay comparable, and `EXP_SYNTH_KV_NONURAM_CELLS`,
`EXP_SYNTH_CV_NONURAM_CELLS` and a `total=` roll-up join it. The harness was
committed BEFORE the run that exercises it, so that run's `=== tree:` names a
clean committed tree.

---

## 2. THE COUNTS — the stop condition that FIRED, and the re-count that answers it

**§2.1–§2.3 are round 1, unedited: the RED.** §2.4 and §2.5 are fix round 1.

### 2.1 URAM288 = 174, predicted 182 — **FAIL** (round 1)

**T**, `s5_counts_summary.log`:

```
EXP_PREDICT: DN 2 x 29 + KV 2 x 58 + CV 2 x 4 = 182 URAM288
EXP_SYNTH_URAM: 174  (predicted 182)
EXP_SYNTH_BRAM: RAMB36=127 RAMB18=10
EXP_SYNTH_DSP: 1838
EXP_SYNTH_URAM_MATCH: NO — inferred 174, study predicts 182
EXP_SYNTH_DN_NONURAM_CELLS: 0
```

`ooc_s5_layer_util_synth.rpt` §2 BLOCKRAM carries the same three numbers off
the utilization table rather than the netlist: `URAM 174`, `Block RAM Tile
132`, `RAMB36/FIFO 127`, `RAMB18 10`.

**The last line of that block is a marker that was BLIND, and it is left in
the quotation because it was.** `EXP_SYNTH_DN_NONURAM_CELLS: 0` matched
`*g_dn*` and nothing else in the harness as of `011ee16`, so on a netlist
whose CONV slots had gone to block RAM it was reading cells that were never in
question: the zero is true, and it is not evidence about the failure this
section is about. Nothing in §2.2's attribution rests on it — that comes from
a census that names every cell. Fix round 2 widened the marker to all three
slot kinds (§1.1) and ran it (§2.6); the RED it would have printed here is not
reproducible without reverting the RTL attribute and re-synthesizing, so no
committed log shows a widened probe reading non-zero.

### 2.2 WHERE the eight URAMs went — the per-memory census

`s5_mem_census.tcl` on the count run's own `post_synth.dcp`
(`011_mem_census.log`), with a completeness check so the attribution is
exhaustive rather than illustrative:

```
MEM_COVER URAM288 total=174 named=174 unnamed=0
MEM_COVER RAMB36  total=127 named=127 unnamed=0
MEM_COVER RAMB18  total=10  named=10  unnamed=0
```

| memory (RTL declaration) | spec §3 says | **measured (T)** | verdict |
|---|---|---|---|
| DN slots, `mem [4096]` ×2 | 2 × 29 = 58 URAM | **58 URAM** | matches |
| KV slots, `mem [8192]` ×2 | 2 × 58 = 116 URAM | **116 URAM** | matches |
| KV exponent, `emem [8192]` ×2 | block RAM, 2 tiles | **4 RAMB36** | 4 tiles, not 2 |
| **conv slots, `wm`+`sm` ×2** | **2 × 4 = 8 URAM** | **0 URAM; 50 RAMB36 + 2 RAMB18** | **THE SHORTFALL** |
| scratchpad `smem_a`/`smem_b` | — | 32 + 30 RAMB36 | 62 tiles |
| `u_attn` (`sc_mem`, `es_mem`, `u_recip`) | 4 + 4 tiles (A1.5) | 7 RAMB36 + 3 RAMB18 | 8.5 tiles |
| `u_vn`, `u_gate`, `u_alu`, `u_conv` | — | 4 RAMB36 + 5 RAMB18 | 6.5 tiles |

**The cause, and it is one line of RTL.** The DN row memory carries
`(* ram_style = "ultra" *)` at `rtl/layer_chan.sv:772`, and the KV row memory
carries it at `rtl/layer_chan.sv:836`.

The conv pair, at `rtl/layer_chan.sv` lines 891-892 — the coordinates are
still 891-892, but the LINES are what fix round 1 changed, so this quotation
is of the file as of `6b88724` and is deliberately not in citation form — was
declared

```
        logic [63:0] wm [CVD];
        logic [47:0] sm [CVD];
```

with **no ram_style attribute at all**, so Vivado inferred block RAM for
them, exactly as it does for `emem` — where `rtl/layer_chan.sv:813` says the
absence is deliberate. For the conv pair the spec's table says URAM.

**Both headline deviations are the same deviation.** **D**: block RAM is 132
tiles against spec §3's "≈ 90"; the conv pair is 50 RAMB36 + 2 RAMB18 = 51
tiles; 132 − 51 = **81 tiles**, which is the "≈ 90" the spec predicts for a
design whose conv slots are in URAM. Take the conv pair out of block RAM and
put it in URAM and both numbers land: 174 + 8 = 182 URAM, 132 − 51 = 81 ≈ 90
tiles.

**One row of the census table is known-imprecise and is not used above.** The
`KV_slot_mem` pattern `*g_kvslot*mem_reg*` also matches `emem_reg`, so its
`RAMB36 4` is the SAME four cells as the `KV_slot_emem` row, not four more.
The URAM column is unaffected (the exponent memories are block RAM) and
`MEM_COVER`'s counts are de-duplicated, so no total here is wrong.

### 2.3 The full counts table, against Task 12

**T** for the S5 column (`ooc_s5_layer_util_synth.rpt`) and for both Task 12
columns (`evidence/qwen9b/g4/G4B_STRUCT.md:180-191`, itself off
`evidence/qwen9b/g4/ooc_layer_p0_util_synth.rpt` and
`evidence/qwen9b/g4/ooc_layer_p2_util_synth.rpt`). Task 12's `DN_PIPE = 2`
column is the design that shipped at Task 12; `DN_PIPE = 0` is its control and
is the more useful comparison here, because S5 retired the pipeline the
parameter switched on.

| row | T12 `DN_PIPE=0` | T12 `DN_PIPE=2` | **S5** | Δ vs `DN_PIPE=2` |
|---|---|---|---|---|
| CLB LUTs | 109,986 | 110,367 | **113,104** | **+2,737** |
| — LUT as Logic | 109,608 | 109,728 | 108,608 | −1,120 |
| — LUT as Distributed RAM | 344 | 600 | **4,456** | **+3,856** |
| — LUT as Shift Register | 34 | 39 | 40 | +1 |
| CLB Registers | 54,433 | 79,078 | **59,829** | **−19,249** |
| CARRY8 | 7,827 | 7,834 | 7,844 | +10 |
| Block RAM Tile | 690.5 | 690.0 | **132** | **−558** |
| — RAMB36 / RAMB18 | 674 / 33 | 674 / 32 | 127 / 10 | −547 / −22 |
| **URAM288** | 928 | 928 | **174** | **−754** |
| DSPs | 1,837 | 1,836 | **1,838** | +2 |

**The deltas attributed, each to a named contributor**
(`ooc_s5_layer_util_synth_hier.rpt` is the per-instance report; `u_dma` is the
`state_dma` row in it):

* **Flip-flops, −19,249 vs `DN_PIPE=2`.** Task 12 measured the DN pipeline at
  **+24,645** FF over its own control (`evidence/qwen9b/g4/G4B_STRUCT.md:186`);
  S2 retired it, so
  the right comparison is against the **control**. **D**: 59,829 − 54,433 =
  **+5,396**. `u_dma` alone is **5,073 FF** (T, hierarchical report), leaving
  **+323** for the ownership muxes, the slot tags and the new CSRs. The brief's
  "≈ −24.6 K from the retired `DN_PIPE` FFs, plus the DMA engine and the
  ownership muxes" is measured: −24,645 + 5,073 + 323 = −19,249. ✅
* **LUT as Distributed RAM, +3,856.** `u_dma` is **4,096 LUTRAM cells** (T,
  `MEM_ROW SDMA … 4096`) — the 256-beat × 512-bit burst FIFO spec §4 specifies.
  The census's cell count and the utilization row's LUT-site count are
  different units and are not equated here; the attribution is that one block
  owns essentially all of the increase (`u_rope` 200, `u_gate` 84, `u_dn` 80
  are the rest, and were there before).
* **Total LUTs, only +2,737** even though `u_dma` is 15,051 LUTs: the 24-bank
  DN array's address decode, bank muxes and 2048-bit return mux went with the
  array. **D**: 15,051 − 2,737 ≈ 12.3 K LUTs freed by the retirement.
* **DSP, +2.** The layer's arithmetic is untouched by the amendment
  (plan Global Constraints, "no arithmetic changes anywhere"); +2 against
  `DN_PIPE=2` and +1 against `DN_PIPE=0` is the tool re-inferring a boundary
  adder, the same ±1 Task 12 saw between its own two runs.
* **URAM, −754 and Block RAM, −558.** The point of the amendment. Both are
  **8 URAM / 51 tiles away from the spec's own prediction**, in the direction
  §2.2 explains.

---

### 2.4 THE FIX, and the re-count: URAM288 = 182 — **PASS**

The controller's ruling on §7's fork was **option A**: the RTL follows the
approved spec, so the attribute is what changes. `rtl/layer_chan.sv` now
declares the conv pair the way the DN and KV slot memories are declared:

```
        (* ram_style = "ultra" *) logic [63:0] wm [CVD];
        (* ram_style = "ultra" *) logic [47:0] sm [CVD];
```

64 b × 8192 is 2 URAM288 (one wide, two deep) and 48 b × 8192 is 2 more, so
4 per slot and 8 in all — spec §3's conv row, arithmetically. The comment
block that already carries the layer's URAM arithmetic says so and names the
RED it answers; **no line was added to the file**, for the reason in §7.2.

**A synthesis attribute cannot change what the RTL computes**, so there is no
model-scale replay here and none is owed: `ram_style` selects the primitive
the inference engine targets. The gate is that the design still lints and the
DMA testbench still passes, on the bytes that were committed:

| log | command | verdict |
|---|---|---|
| `evidence/qwen9b/s5/093_lint_layer_chan.log` | `make -C tb lint_layer_chan` | rc 0, and Verilator 5.020 emits **no diagnostic at all** — the log's body is the two `verilator` command lines and nothing else, so there is no count line to quote |
| `evidence/qwen9b/s5/094_tb_layer_sdma.log` | `make -C tb tb_layer_sdma` | rc 0, four seeds from one binary: `TB_LAYER_SDMA PASS: 240 checks, seed 1` … `seed 4` |

240 checks per seed is what THIS log reads; it is not carried over from S2's
or S4's figure.

**The re-count.** `synth/exp_uram/scripts/exp_ooc.tcl` at `place=0`, the same
path §2.1 took, on the clean tree `5cb1899`
(`evidence/qwen9b/s5/090_ooc_counts_exp.log`, and its marker stream alone in
`evidence/qwen9b/s5/s5fix_counts_summary.log`):

```
EXP_PREDICT: DN 2 x 29 + KV 2 x 58 + CV 2 x 4 = 182 URAM288
EXP_SYNTH_URAM: 182  (predicted 182)
EXP_SYNTH_BRAM: RAMB36=77 RAMB18=8
EXP_SYNTH_DSP: 1838
EXP_SYNTH_URAM_MATCH: YES
EXP_SYNTH_DN_NONURAM_CELLS: 0
```

**The per-memory census, again exhaustive** (`evidence/qwen9b/s5/092_mem_census.log`,
`s5_mem_census.tcl` on the re-count's own `post_synth.dcp`):

| memory (RTL declaration) | spec §3 says | round 1 (T) | **fix round (T)** |
|---|---|---|---|
| DN slots, `mem [4096]` ×2 | 2 × 29 = 58 URAM | 58 URAM | **58 URAM** |
| KV slots, `mem [8192]` ×2 | 2 × 58 = 116 URAM | 116 URAM | **116 URAM** |
| **conv slots, `wm`+`sm` ×2** | **2 × 4 = 8 URAM** | 0 URAM; 50 RAMB36 + 2 RAMB18 | **8 URAM (4 + 4)** |
| KV exponent, `emem [8192]` ×2 | block RAM, "2 tiles" | 4 RAMB36 | **4 RAMB36** — spec amendment A2.1 |
| scratchpad `smem_a`/`smem_b` | — | 32 + 30 RAMB36 | **62 tiles** |
| `u_attn` (`sc_mem`, `es_mem`, `u_recip`) | 4 + 4 tiles (A1.5) | 7 RAMB36 + 3 RAMB18 | **8.5 tiles** |
| `u_vn`, `u_gate`, `u_alu`, `u_conv` | — | 4 RAMB36 + 5 RAMB18 | **6.5 tiles** |

```
MEM_COVER URAM288 total=182 named=182 unnamed=0
MEM_COVER RAMB36  total=77  named=77  unnamed=0
MEM_COVER RAMB18  total=8   named=8   unnamed=0
MEM_CONV CV_wm -> LUT3=1 LUT4=167 LUT5=2 URAM288=4
MEM_CONV CV_sm -> LUT3=1 LUT4=135 LUT5=2 URAM288=4
```

**D**: 4 + 62 + 8.5 + 6.5 = **81.0 tiles**, which is 77 RAMB36 + 8 RAMB18 read
the other way, and it is the "≈ 90" spec §3 predicted for a design whose conv
slots are in URAM. §2.2's arithmetic said 132 − 51 = 81 before the run; the
run says 81. Spec amendment A2.2 records it.

**The delta against the 174 netlist is the attribute and nothing else.** Both
`report_utilization` reports are committed
(`evidence/qwen9b/s5/ooc_s5_layer_util_synth.rpt` for round 1,
`evidence/qwen9b/s5/ooc_s5fix_layer_util_synth.rpt` for this one):

| row | round 1 (174) | **fix round (182)** | Δ |
|---|---|---|---|
| CLB LUTs | 113,104 | **114,106** | **+1,002** |
| — LUT as Logic | 108,608 | 109,610 | +1,002 |
| — LUT as Memory | 4,496 | 4,496 | 0 |
| CLB Registers | 59,829 | **59,836** | +7 |
| CARRY8 | 7,844 | 7,844 | **0** |
| Block RAM Tile | 132 | **81** | **−51** |
| — RAMB36 / RAMB18 | 127 / 10 | 77 / 8 | −50 / −2 |
| **URAM288** | 174 | **182** | **+8** |
| DSPs | 1,838 | 1,838 | **0** |

**Where the +1,002 LUTs are, per instance** (**T**, the two hierarchical
reports `evidence/qwen9b/s5/ooc_s5_layer_util_synth_hier.rpt` and
`evidence/qwen9b/s5/ooc_s5fix_layer_util_synth_hier.rpt`, differenced row by
row). The whole memory change is at the TOP level, where the conv slots are
declared — RAMB36 116 → 66, RAMB18 2 → 0, URAM 174 → 182 — and it costs
**+1,178 LUTs there**: URAM address, enable and byte-write logic in place of
block RAM's. Every other block moves by **−176 in total** (`u_vn` −164,
`u_rope` +118, `u_alu` −70, `u_dn` −40, `u_dma` −31, `u_attn` +34 and small
change), none of which changed a line — that is the tool re-synthesising
unrelated logic, and it is the size of the noise floor on a 114 K-LUT design.
**D**: +1,178 − 176 = +1,002.

**The SHIPPING netlist against Task 12, without composing two tables.** §2.3's
S5 column is the **174** netlist; the netlist that ships is the 182 one, so the
two rows the brief asks for are restated here directly. **D**, off
`evidence/qwen9b/s5/ooc_s5fix_layer_util_synth.rpt` against Task 12's two
columns at `evidence/qwen9b/g4/G4B_STRUCT.md:180-191`:

| row | T12 `DN_PIPE=0` | T12 `DN_PIPE=2` | **S5 shipping (182)** | Δ vs `DN_PIPE=2` | Δ vs `DN_PIPE=0` |
|---|---|---|---|---|---|
| CLB LUTs | 109,986 | 110,367 | **114,106** | **+3,739** | **+4,120** |
| CLB Registers | 54,433 | 79,078 | **59,836** | **−19,242** | **+5,403** |

Every attribution in §2.3's bullets carries over unchanged, because the block
that owns them barely moved: `u_dma` is **15,020 LUT / 5,072 FF** on this
netlist (**T**, `evidence/qwen9b/s5/ooc_s5fix_layer_util_synth_hier.rpt`)
against 15,051 / 5,073 on the 174 — −31 LUT and −1 FF, inside the noise floor
the paragraph above measures. The FF decomposition therefore reads
−24,645 + 5,072 + 331 = **−19,242** on the shipping netlist: §2.3's +323
residual becomes **+331**, which is the +7 flip-flops the attribute cost plus
the one flip-flop `u_dma` gave back.

### 2.5 The two harnesses agree — on every row, not only on URAM

The brief allowed LUT and FF to differ between the two harnesses by
implementation strategy. They do not differ at all.
`evidence/qwen9b/s5/091_ooc_counts_g4b.log` is the REPAIRED
`synth/scripts/ooc_9b.tcl` driven by `evidence/qwen9b/g4/run_g4b_ooc.sh`,
launched two seconds after the other on the same clean tree:

```
OOC9B_URAM: 182
OOC9B_BRAM: RAMB36=77 RAMB18=8 tiles=81.0
OOC9B_DSP: 1838
OOC9B_LUT: 114106 (logic 109610, memory 4496)
OOC9B_FF: 59836
OOC9B_CARRY8: 7844
OOC9B_URAM_PREDICT: 182 (2 slots x (DN 29 + KV 58 + CV 2 + 2))
OOC9B_URAM_MATCH: YES
OOC9B_SLOT_NONURAM_CELLS: dn=0 kv=0 cv=0
OOC9B_URAM_SPLIT: dn=58 kv=116 cv=8 other=0
OOC9B_BRAM_SPLIT: scratch=62 conv=0 kvexp=4
```

Every `report_utilization` row is identical to §2.4's: LUT 114,106 (logic
109,610, memory 4,496), FF 59,836, CARRY8 7,844, block RAM 81 tiles, URAM
182, DSP 1,838. **What that is and is not.** It is not two independent
measurements of one quantity — both call the same `synth_design -mode
out_of_context` on the same part at the same 4.000 ns, with no strategy
difference, so identical numbers are what a correct pair of harnesses must
produce. What it checks is the two things that CAN differ and that have
differed: the two file lists (a missing `state_dma` black-boxes the DMA and
undercounts LUT/FF silently — that is why round 1 could not use this
harness), and the two predictions, which are now derived by the same
arithmetic in both scripts rather than typed. `conv=0` in `OOC9B_BRAM_SPLIT`
is §2.2's finding stated in the negative by the instrument that was blind to
it before.

### 2.6 Fix round 2 — the widened probe, run

`synth/exp_uram/scripts/exp_ooc.tcl` at `place=0` for the third time, variant
`s5fix2_counts`, on snoke on the clean committed tree `93c7ceb`
(`evidence/qwen9b/s5/140_counts_probe.log`):

```
EXP_SYNTH_URAM: 182  (predicted 182)
EXP_SYNTH_BRAM: RAMB36=77 RAMB18=8
EXP_SYNTH_DSP: 1838
EXP_SYNTH_URAM_MATCH: YES
EXP_SYNTH_DN_NONURAM_CELLS: 0
EXP_SYNTH_KV_NONURAM_CELLS: 0
EXP_SYNTH_CV_NONURAM_CELLS: 0
EXP_SYNTH_SLOT_NONURAM_CELLS: dn=0 kv=0 cv=0 total=0
```

**Nothing moved except the instrument.** **D**: the `EXP_` marker stream of
this run and of `evidence/qwen9b/s5/090_ooc_counts_exp.log` differ by the
three lines the widening adds, **plus `EXP_VARIANT`, which names the run and
so differs in both blocks** — a reader running the diff gets those two lines
as well and should not read them as a netlist change. URAM 182, RAMB36 77,
RAMB18 8, DSP 1,838
and every other marker are byte-identical between them. So the widening is a
new reading of the same netlist, not a new netlist, and §2.4's counts stand
unchanged.

**The three zeros, and which one is the point.** `CV` is the line that did not
exist when it was needed: it is the marker that would have fired on the 174
netlist, where the conv weight and state memories sat in 50 RAMB36 + 2 RAMB18
(§2.2). `KV` covers the slot rows while excluding `emem`, which is block RAM
by design. `DN` is the old marker, kept so the earlier logs stay comparable.

**What this run is, and what it is NOT.** It is the GREEN half by itself. The
matching RED — a widened probe printing a non-zero count — is not reproducible
without reverting `(* ram_style = "ultra" *)` on the conv pair and
re-synthesizing, which would re-establish by a third counts run a fault this
round has already measured twice: by census (`evidence/qwen9b/s5/011_mem_census.log`,
50 RAMB36 + 2 RAMB18 named to `wm` and `sm`) and by the utilization delta
(§2.4's −51 tiles). What stands in for the control is that the filters are not
vacuous: `synth/scripts/ooc_9b.tcl` uses the same **DN and CV** patterns for
its `OOC9B_URAM_SPLIT`, and **a SUPERSET of the KV one** — the split's KV
selector at `synth/scripts/ooc_9b.tcl:230` has no `emem` exclusion where the
non-URAM count at `synth/scripts/ooc_9b.tcl:219` does — and that split finds
`dn=58 kv=116 cv=8` on this
netlist (§2.5) — patterns that matched nothing could not have found 182 cells
under them. The superset costs nothing here, and the witness is the census:
`evidence/qwen9b/s5/092_mem_census.log:93-97` puts **0** URAM under
`KV_slot_emem` (its 4 tiles are RAMB36), so including it or excluding it
gives the same 116. *(This sentence said "the SAME three `NAME` patterns"
until 2026-09-10, and a non-vacuity argument should not lean on a pattern
equality that is not one.)*

**Handoff to Task 14.** These are pre-build checks on an out-of-context
synthesis of one module; an in-context build reads its own
`report_utilization -hierarchical` for `bd_i/layer_0` and does not need either
probe to know where the layer's memories went.

---

## 3. THE PLACEMENT — three runs on the 174 netlist, three on the 182

**§3.1 and §3.2 are round 1, on the 174-URAM netlist. §3.3 is the result:
the same three runs on the 182-URAM netlist, where both one-SLR variants MEET
timing post-place.**

`EXP_PBLOCK pb_layer_1slr cells=20520 range={CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}`
on both constrained runs: the floorplan matched cells. `exp_ooc.tcl` FATALs
when a pblock matches zero, which is how a floorplan campaign measures nothing;
it did not fire, and no run produced any `ERROR` or `CRITICAL WARNING`.

| # | variant | XDC | directive | URAM | place | design SLR span | **SLLs** | WNS | TNS | failing EP |
|---|---|---|---|---|---|---|---|---|---|---|
| base | unconstrained | none | Default | 174 | PLACED (1,677 s) | **2** (SLR0+SLR1) | **503** | **−0.136** | −5.205 | 145 |
| 1slr | one SLR | `synth/constraints/fable5_floorplan_9b_1slr.xdc` | Default | 174 | PLACED (1,784 s) | **1** (SLR1) | **0** | −0.245 | −120.640 | 2,066 |
| 1slr-alt | one SLR | same | `AltSpreadLogic_medium` | 174 | PLACED (1,747 s) | **1** (SLR1) | **0** | −0.166 | −28.215 | 843 |

Every cell of every row is **T**, from that run's own committed
`*_summary.log` / `*_finish_run.log` (`EXP_`/`FIN_TIMING_SUMMARY`) and
`*_util_placed_slr.rpt`. Hold is clean on all three: WHS +0.011 / +0.016 /
+0.020, THS 0.000, zero failing hold endpoints.

### 3.1 "URAM span 1" is not "one SLR", and the difference is the whole result

`EXP_URAM_SLR_SPAN: 1` on **all three** runs, the baseline included — with
`layer_chan` alone on the device there is nothing to compete for URAM columns,
so the 174 land in one SLR whether or not anyone asks. The baseline's URAM is
in SLR0.

The **design** is a different question, and the per-SLR utilization answers it
(`*_util_placed_slr.rpt` §3, and §1 for the SLLs):

| resource (SLR budget) | base SLR0 | base SLR1 | **1slr — SLR1** | **1slr-alt — SLR1** |
|---|---|---|---|---|
| URAM288 (320) | 174 | 0 | **174 = 54.4 %** | **174 = 54.4 %** |
| DSP48E2 (2,280) | 1,810 | 28 | **1,838 = 80.6 %** | **1,838 = 80.6 %** |
| Block RAM tiles (720) | 125.5 | 6.5 | **132 = 18.3 %** | **132 = 18.3 %** |
| CLB LUTs (≈ 394 K) | 102,066 | 5,851 | **108,628 = 27.6 %** | **108,484 = 27.5 %** |
| CLB registers | 57,814 | 4,182 | 62,793 | 62,973 |
| **SLLs used** | \-\- 503 across the SLR0↔SLR1 boundary \-\- | | **0** | **0** |
| SLR0 / SLR2 occupancy | — | — | **empty / empty** | **empty / empty** |

**So the answer to the gate's second question is YES, and it needs the
pblock.** Left alone, the placer spilled 5,851 LUTs, 28 DSPs and 6.5 block RAM
tiles into the next SLR and paid 503 SLL crossings for it. With
`synth/constraints/fable5_floorplan_9b_1slr.xdc` the layer is entirely inside
SLR1 and crosses
nothing, at both directives sampled. **The DSP row is the tight one at 80.6 %
of an SLR's 2,280**, exactly as spec §12 risk 1 predicted it would be; it fits.

### 3.2 Reading the WNS

Against the house playbook's reach (≈ −0.1 … −0.3 ns at OOC closes at the full
build with a post-route `phys_opt` pass): **−0.245 and −0.166 are both inside
it**, so the STOP-back of spec §12 risk 1 does not fire.

Two things this does NOT say. First, §0's rule: the OOC success is necessary,
not sufficient — Task 14 adds XDMA at fixed sites, four MIGs, four mvchans and
a sequencer, and only that build decides. Second, the 0.079 ns between the two
one-SLR rows is far inside the 0.475 ns directive spread Track P measured, so
this experiment cannot tell the two directives apart; the choice is Task 14's
roll, not S5's finding.

`superlative-check: quoted` — this paragraph ranks the FIRST round's three
rows, which the checker no longer holds; §3.3 is what it ranks now, and there
the ordering reverses. In round 1 the unconstrained row, `base`, had the best
WNS of the three at −0.136. It is
also the row that spans two SLRs and burns 503 SLLs, so it is not a floorplan
candidate — it is the measurement of what the constraint costs: **D**, −0.136 −
(−0.245) = 0.109 ns against the same-directive `1slr` run.
**DO NOT QUOTE 0.109 ns AS "WHAT THE PBLOCK COSTS".** It is a subtraction
across two runs whose ORDER REVERSED on the 182-URAM netlist: in §3.3 the
unconstrained `base` row is the **worst** of the three (−0.588) where here it
was the best, so the same subtraction there has the opposite sign. The number
below is a first-round reading, kept as the record of that round; nothing in
this document's conclusions rests on it. That is the 2B
campaign's T5 lesson (`synth/constraints/fable5_floorplan_a.xdc:8-10`:
constraining `layer_0` in any form cost ≈ 1 ns) reproduced at roughly a tenth
of its old size on the new design.

---

### 3.3 THE PLACEMENTS ON THE 182-URAM NETLIST — both one-SLR runs MEET timing

Three runs, launched within six seconds of each other on the clean tree
`56459a6`, concurrent on snoke, each into a fresh out dir. All rc 0, and
**no `ERROR` and no `CRITICAL WARNING` on any of them**.
`EXP_PBLOCK pb_layer_1slr cells=21622 range={CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}`
on both constrained runs — `exp_ooc.tcl` FATALs on a pblock that matches zero
cells, which is how a floorplan campaign measures nothing; it did not fire.

| # | variant | XDC | directive | URAM | place | design SLR span | **SLLs** | **WNS** | TNS | failing EP |
|---|---|---|---|---|---|---|---|---|---|---|
| base | `s5fix_base` | none | Default | 182 | PLACED (1,718 s) | **2** (SLR0+SLR1) | **501** | **−0.588** | −1,016.503 | 6,920 |
| 1slr | `s5fix_1slr` | `synth/constraints/fable5_floorplan_9b_1slr.xdc` | Default | 182 | PLACED (1,768 s) | **1** (SLR1) | **0** | **+0.030** | **0.000** | **0** |
| 1slr-alt | `s5fix_1slralt` | same | `AltSpreadLogic_medium` | 182 | PLACED (1,907 s) | **1** (SLR1) | **0** | **+0.034** | **0.000** | **0** |

Every cell is **T**, from that run's own committed
`evidence/qwen9b/s5/s5fix_<variant>_summary.log` and
`evidence/qwen9b/s5/s5fix_<variant>_finish_run.log` (`EXP_`/`FIN_TIMING_SUMMARY`)
and `evidence/qwen9b/s5/s5fix_<variant>_util_placed_slr.rpt`. Hold is clean on
all three: WHS +0.014 / +0.012 / +0.020, THS 0.000, zero failing hold
endpoints.

**The four rankings this table supports, written so a machine can check
them.** `1slr-alt` has the best WNS of the three at +0.034. `1slr` and
`1slr-alt` have the fewest SLL crossings, 0 each, where `base` pays 501.
`1slr-alt` holds the best DN write fan-out of the three at +0.218 (§4.4).
`1slr` holds the best KV write slack of the three at +0.120 (§4.4). Each of
those is attributed to a column and re-derived from the committed logs by
`evidence/qwen9b/s5/s5_superlatives.py`, which fails if the variant named is
not the one that holds the extremum (§9).

**The two one-SLR runs do not just land inside the playbook's reach — they are
past it.** TNS 0.000 with zero failing setup endpoints is timing MET at
post-place, on a netlist that is 8 URAM larger and 51 block-RAM tiles smaller
than the one §3.1 placed. §0's rule still governs and is not softened by a
positive number: this is `layer_chan` alone on the die, and Task 14's build
adds XDMA at fixed sites, four MIGs, four `matvec_chan`s and a sequencer.
What OOC can say is that the floorplan is not the thing that will be short.

### 3.4 Per-SLR, and what the constraint is worth on this netlist

`evidence/qwen9b/s5/s5fix_<variant>_util_placed_slr.rpt` §3, and §1 for the
SLLs:

| resource (SLR budget) | base SLR0 | base SLR1 | **1slr — SLR1** | **1slr-alt — SLR1** |
|---|---|---|---|---|
| URAM288 (320) | 0 | 182 | **182 = 56.9 %** | **182 = 56.9 %** |
| DSP48E2 (2,280) | 25 | 1,813 | **1,838 = 80.6 %** | **1,838 = 80.6 %** |
| Block RAM tiles (720) | 68 | 13 | **81 = 11.3 %** | **81 = 11.3 %** |
| CLB LUTs (≈ 394 K) | 11,764 | 99,479 | **109,357 = 27.8 %** | **109,621 = 27.8 %** |
| CLB registers | 7,906 | 54,150 | 62,362 | 62,364 |
| **SLLs used** | \-\- 501 across the SLR0↔SLR1 boundary \-\- | | **0** | **0** |
| SLR0 / SLR2 occupancy | — | — | **empty / empty** | **empty / empty** |

`EXP_URAM_SLR SLR1 182` and `EXP_URAM_SLR_SPAN: 1` on **all three**, the
baseline included — §3.1's point unchanged: with `layer_chan` alone on the
device nothing competes for URAM columns, so URAM span is not the question.
The design span is, and only the pblocked runs answer it.

**On this netlist the unconstrained run is the WORST of the three, not the
best, and by 0.6 ns.** `superlative-check: scoped` — the ranking the checker
computes for WNS over the three variants is printed beside this sentence in
`evidence/qwen9b/s5/122_superlatives.log`; the claim here is the ordering
`base` < `1slr` < `1slr-alt`, which that ranking is. **D**: +0.030 − (−0.588)
= **0.618 ns** that the floorplan BUYS at the same directive, where on the 174
netlist the same subtraction cost 0.109 ns. The reason is visible in the
family census (§4.4): unconstrained, the placer put 11,764 LUTs and 68 of the
81 block RAM tiles in SLR0 while every URAM stayed in SLR1, so the DN and KV
slot **write** paths ended up crossing SLR0 → SLR1 —
`EXP_DNWRITE_SLR: SLR0 -> SLR1`, decomposed `levels=2 datapath=4.081
logic=0.165 route=3.916 route_pct=96.0`. A 96 %-route path across an SLL
boundary is exactly the shape Track P and Task 13 spent eleven placements on.

This REVERSES round 1's reading of the same comparison and supersedes it. It
does not reverse the 2B campaign's T5 warning
(`synth/constraints/fable5_floorplan_a.xdc:8-10`, constraining `layer_0` cost
≈ 1 ns on the 2B design) — it says that warning was about a design whose
layer had no reason to be gathered, and this one does: 182 URAM288 that only
exist in four clock-region columns, feeding 1,838 DSPs.

### 3.5 The directive, still not chosen

+0.030 and +0.034 differ by **0.004 ns**, which is two orders of magnitude
inside the 0.475 ns directive spread Track P measured
(`evidence/qwen_next/place_exp/PLACE_EXP.md` §3.6, quoted at §0). This
experiment cannot tell the two directives apart and does not try; Task 14
rolls directives on the in-context netlist as the playbook says. The one
asymmetry worth carrying is not timing: the single `[Place 46-14]` congestion
warning is on `1slr-alt` only, where round 1 had one on BOTH one-SLR runs and
none on the baseline (§4.5).

---

## 4. WHAT THE OWNERSHIP MUX COSTS — spec A1.2, measured

**§4.1–§4.3 are round 1, on the 174-URAM netlist. §4.4 and §4.5 are the same
measurements on the 182-URAM netlist and are the ones A1.2 is answered with.**

Spec A1.2 WITHDREW §3's claim that there is "no timing change on the compute
side", because the DMA reaches each slot through a 2:1 mux on read address,
write address, write data and write enable — sitting on the DN and KV write
fan-out, the family Task 13 measured. This is the measurement it asked for.

`s5_family_census.tcl` on each run's own `post_place.dcp`: the worst setup path
into each family's endpoint cells, and the family histogram of the 200 worst
setup PATHS. "cells" counts endpoint CELLS, not timing endpoints — one URAM288
carries many endpoint pins. The families are S5's, because Task 13's named the
banked array S2 deleted; `evidence/qwen9b/s5/s5_family_census.tcl`'s header
records the mapping.

### 4.1 The fan-out rows, against Task 13's chosen floorplan

Task 13's `2'cr` (`synth/constraints/fable5_floorplan_9b_dngrpcr.xdc`) is the
row this compares
against: it was the floorplan Task 13 chose, at WNS −0.554
(`evidence/qwen9b/g5/G5A_FLOORPLAN.md:204`, §4.4's `2'cr` table).

| write fan-out family | Task 13 `1'a` (no floorplan) | Task 13 `2'cr` (chosen) | **S5 base** | **S5 1slr** | **S5 1slr-alt** |
|---|---|---|---|---|---|
| **DN** slot write | −1.141 | −0.001 | **+0.192** | **+0.166** | **+0.214** |
| **KV** slot write | −0.853 | −0.368 | **+0.008** | **−0.110** | **+0.048** |
| conv slot write | −0.686 | −0.554 | **+0.079** | **+0.302** | **+0.533** |

**The ownership mux does not cost what A1.2 was right to worry about.**
`superlative-check: scoped` — the three Task-13 columns come from a DIFFERENT
DESIGN and a different experiment (`evidence/qwen9b/g5/G5A_FLOORPLAN.md` §4.4),
so no ranking that
mentions them is inside S5's own checker; they are quoted for scale, and the S5
columns are this document's numbers. The DN write fan-out — Track P's binding
path at −1.391, Task 13's at −1.141 unconstrained and −0.001 under the
floorplan it chose — is positive on all three S5 runs, without any floorplan
aimed at it. The KV write fan-out is positive on two of the three round-1 runs
and −0.110 on the third. The conv write is positive on all three. **D**: DN
improves by 0.167 … 0.215 ns on Task 13's `2'cr` number and by 1.307 … 1.355 ns
on its unconstrained `1'a` one.

The reason is structural rather than lucky: the mux replaced a **24-bank
address decode and write-enable broadcast** with a **2:1 select whose control
is stable for a whole transfer**. One 2:1 mux is cheaper than the fan-out it
replaced, and there is no longer a bank array to spread across three SLRs.
Decomposition of the DN row under `1slr`: `levels=2 datapath=3.342 logic=0.227
route=3.115 route_pct=93.2` — still route-dominated, as every URAM write path
in this design has been, but with 0.658 ns of margin instead of a deficit.

### 4.2 What owns the residual now — every family, every run

| family | endpoint cells | **base** | **1slr** | **1slr-alt** | in the 200 worst (1slr) |
|---|---|---|---|---|---|
| DN_SLOT | 4,228–4,231 | +0.192 | +0.166 | +0.214 | — |
| KV_SLOT | 4,294 | +0.008 | −0.110 | +0.048 | — |
| CV_SLOT | 680 | +0.079 | +0.302 | +0.533 | — |
| SDMA | 28,005–28,008 | +0.023 | +0.001 | +0.006 | — |
| **ATTN_DSP** | 80,762–80,811 | **−0.057** | **−0.245** | **−0.166** | **172 paths, worst −0.245** |
| SCRATCH | 238 | +0.361 | +0.347 | +0.426 | — |
| OTHER | — | −0.136 | −0.150 | −0.127 | 28 paths |

`superlative-check: scoped` — this paragraph ranks across FAMILIES within one
run, which the checker cannot do (it ranks one column across the three
variants); the ranking is the §4.2 table's own rows, read down each column.
**`ATTN_DSP` is the worst family on all three ROUND-1 runs**, and on both
round-1 one-SLR runs it IS the design's WNS. (§4.5 is where the 182 netlist
answers the same question, and there it is the worst family on `base` and
`1slr-alt` but not on `1slr`.) Its path, decomposed (`FAM_ROW`/`FAM_PATH`, `1slr`):

```
g_kvslot[0].mem_reg_uram_20/CLK  ->  u_attn/g_lane[92].prod_reg[92]/DSP_A_B_DATA_INST/B[10]
levels=2  datapath=3.882  logic=1.587  route=2.295  route_pct=59.1   SLR1 -> SLR1
```

That is the KV cache URAM's clock-to-out feeding `attn_core`'s per-lane
multiplier input: **the compute READ path out of the KV slot**, not a write
path and not a DMA path. It is 59 % route and 41 % logic — a mixed path, unlike
the 93–98 % pure-route paths that bound Track P and Task 13 — and it is inside
one SLR with no crossing left to remove. The three one-SLR runs put it at
−0.057, −0.245 and −0.166, a 0.188 ns spread across placements of the same
netlist, which is itself smaller than the sampled directive spread.

`SDMA`, the family that did not exist in Task 13, sits at **+0.001 … +0.023** —
positive on all three runs but with essentially no margin, and it is the family
to watch when Task 14 adds context. Its worst paths are inside the burst FIFO
(`u_dma/f_wp_reg[…]/C -> u_dma/fmem_reg_…`) and the beat accumulator.

The baseline's WNS is not `ATTN_DSP` at all: `FAM_OTHER_WORST` names
`u_alu/op_q_reg[1]/C -> u_alu/r_res_reg[22]/D`, `levels=17`, 74.7 % route — a
logic-DEPTH path in the vector ALU, which no floorplan addresses. It is the
reason S5's census script names the worst OTHER path instead of leaving a
bucket unexplained.

### 4.3 Congestion

Both one-SLR runs carry exactly one `WARNING: [Place 46-14] The placer has
determined that this design is highly congested and may have difficulty
routing`; the unconstrained baseline carries none. **T**, and the count is off
the COMMITTED run logs, not the gitignored out dir: `grep -c 'Place 46-14'`
over `evidence/qwen9b/s5/020_place_base.log`,
`evidence/qwen9b/s5/021_place_1slr.log` and
`evidence/qwen9b/s5/022_place_1slralt.log` gives **0 / 1 / 1**. Nothing
here is routed (§6), so this is a flag for Task 14 and
not a result: packing 27.6 % of an SLR's LUTs and 80.6 % of its DSPs into one
SLR is what produced it.

---

### 4.4 The A1.2 fan-out rows on the 182-URAM netlist

Same instrument, each run's own `post_place.dcp`
(`evidence/qwen9b/s5/104_family_census.log`, collected per variant into
`evidence/qwen9b/s5/s5fix_<variant>_family_run.log`). Task 13's `2'cr` column
is repeated from §4.1 for scale only.

| write fan-out family | T13 `1'a` | T13 `2'cr` | round 1 `1slr` | **base** | **1slr** | **1slr-alt** |
|---|---|---|---|---|---|---|
| **DN** slot write | −1.141 | −0.001 | +0.166 | **−0.588** | **+0.208** | **+0.218** |
| **KV** slot write | −0.853 | −0.368 | −0.110 | **−0.459** | **+0.120** | **+0.081** |
| conv slot write (`CV_SLOT`) | −0.686 | −0.554 | +0.302 | **+1.140** | **+0.340** | **+0.181** |

`superlative-check: scoped` — the three Task-13 columns and the round-1 column
come from other netlists, so no ranking that mentions them is inside this
document's checker; the S5 columns are the ones it holds.

**The ownership mux still costs nothing measurable, and the KV row is now
positive on both floorplanned runs** where round 1 left it at −0.110. **D**
against Task 13's chosen floorplan: DN +0.209 / +0.219, KV **+0.488 / +0.449**,
conv +0.894 / +0.735. Against Task 13's unconstrained `1'a`: DN +1.349 /
+1.359.

**The KV delta's COMPARAND is one draw, and the delta must be read that way.**
Task 13's `2'cr` KV number, −0.368, is the best of **nine** Task-13 runs that
constrain nothing about the KV write path, across which that row moves −0.368
to −1.216 — an **0.848 ns** spread produced entirely by where the placer put
an unconstrained array, which `evidence/qwen9b/g5/G5A_FLOORPLAN.md:358-364`
states in those words. So **+0.488 / +0.449** is a delta against a sample, not
against a characterised baseline, and it is 0.36 ns smaller than the spread of
the thing it is measured from. §0's caveat covers rankings that mention the
Task-13 columns; this sentence covers the subtraction. The claim the section
actually makes — that the ownership mux costs nothing measurable — rests on
S5's own ABSOLUTE numbers (+0.208 / +0.218 DN, +0.120 / +0.081 KV, both
positive on both floorplanned runs of one netlist) and is unaffected.

**The `CV_SLOT` family moved into URAM and its rows say so.** Its endpoint
pins are URAM pins now — `g_cvslot[0].wm_reg_uram_1/CAS_IN_ADDR_A[2]` under
`1slr`, where round 1's was `g_cvslot[0].sm_reg_bram_7/ADDRBWRADDR[13]` — and
its endpoint-cell count falls **680 → 540** with the block RAM it replaced.
Its slack moves both ways against round 1 — +0.302 → +0.340 under `1slr`,
+0.533 → +0.181 under `1slr-alt` — a 0.352 ns spread across two placements of
one netlist, which is the noise this experiment sees and not a trend. §7.1
named the risk that a URAM write port is a different, slower endpoint than a
block-RAM one; if that cost is in these numbers it is smaller than the
placement spread, and it is paid out of margin the family has. The lower of
the two constrained conv rows is +0.181, and no conv path is within 0.14 ns
of either run's WNS.

**Task 13's conv probe is now silent, and that is the measurement.**
`synth/exp_uram/scripts/finish_reports.tcl` is UNMODIFIED from Task 13 and its
conv query filters on `RAMB36*`/`RAMB18*`; it reports
`FIN_CONV_BRAM_CELLS: 0` on all three runs and skips its report. An instrument
built to find conv memories in block RAM finding none is §2.4 seen from the
placer.

**A SECOND Task-13 probe matches nothing, on all six runs, and it is not the
same kind of silence.** `synth/exp_uram/scripts/finish_reports.tcl:77-89` hunts
the KV bank read mux by three names in turn — `*at_kvdata_reg*`, then
`*at_kvdata*`, then `*kv_rdq_b*` — and every one of the six `s5_*` and
`s5fix_*` finish logs prints `FIN_KVMUX_TRY` 0, 0, 0 followed by
`FIN_KVMUX_WORST_SLACK: n/a`. Nothing is wrong: that mux was part of the
banked KV array S2 deleted, so the probe is looking for cells this design does
not have, and the KV read path it was aimed at is now inside the `KV_SLOT`
family measured above. It is recorded because a marker reading `n/a` and a
marker reading `0` mean different things, and neither is a result.

### 4.5 What owns the residual now, and the congestion flag

| family | endpoint cells | **base** | **1slr** | **1slr-alt** | in the 200 worst (1slr) |
|---|---|---|---|---|---|
| DN_SLOT | 4,227–4,231 | −0.588 | +0.208 | +0.218 | 119 paths (base only) |
| KV_SLOT | 4,351 | −0.459 | +0.120 | +0.081 | 1 path |
| CV_SLOT | 540 | +1.140 | +0.340 | +0.181 | — |
| SDMA | 27,852–27,855 | −0.349 | +0.203 | +0.087 | — |
| **ATTN_DSP** | 80,569–80,701 | −0.467 | **+0.109** | **+0.034** | **49 paths** |
| SCRATCH | 231–232 | +0.452 | +0.235 | +0.177 | — |
| OTHER | — | −0.465 | **+0.030** | +0.043 | 150 paths |

`superlative-check: scoped` — this table ranks across FAMILIES within one run,
which the checker cannot do (it ranks one column across the three variants);
the ranking is this table's own rows, read down each column.

**The residual owner changes with the floorplan, and neither owner is a write
path.** Under `1slr` the design's WNS is not `ATTN_DSP` at all: `OTHER` holds
it at **+0.030**, and `FAM_OTHER_PATH` names
`u_dn/g_lane[124].kvm_acc_reg[124]/DSP_OUTPUT_INST/CLK ->
u_dn/p_0_out__8__3_i_18_psdsp/D`, `levels=7 datapath=3.921 logic=0.816
route=3.105 route_pct=79.2` — a DSP-to-DSP accumulation inside `dn_step`, a
logic-depth path no floorplan addresses. Under `1slr-alt` the WNS is
`ATTN_DSP` at +0.034, `g_kvslot[0].mem_reg_uram_52/CLK ->
u_attn/g_lane[239].pv_p_reg[239]/DSP_A_B_DATA_INST/A[3]`, `levels=2
datapath=3.635 logic=1.657 route=1.978 route_pct=54.4` — the compute READ out
of the KV slot into the attention multipliers, 54 % route and 46 % logic,
inside one SLR with no crossing left to remove. Round 1 named that same family
and that same shape of path as the residual owner at −0.245; it is the same
path, now positive.

**`SDMA` gained margin.** +0.203 and +0.087, where round 1 had +0.001 and
+0.006 — still the family to watch when Task 14 adds context, but no longer
sitting on zero.

**Congestion.** One `WARNING: [Place 46-14] … highly congested` on
`1slr-alt` only; `base` and `1slr` carry none. **T**, off the COMMITTED run
logs rather than the gitignored out dir: `grep -c 'Place 46-14'` over
`evidence/qwen9b/s5/100_place_base.log`,
`evidence/qwen9b/s5/101_place_1slr.log` and
`evidence/qwen9b/s5/102_place_1slralt.log` gives **0 / 0 / 1**. Round
1 had one on BOTH one-SLR runs (0 / 1 / 1 by the same count). Nothing here is routed (§6), so this is a flag
for Task 14 and not a result.

---

## 5. THE FLOORPLAN FOR TASK 14

**`synth/constraints/fable5_floorplan_9b_1slr.xdc`** — one SOFT pblock over
`CLOCKREGION_X0Y5:CLOCKREGION_X5Y9` (SLR1) holding every cell of the layer.
Its header carries the capacity check against one SLR's budget, the reason for
SLR1 (`ddr4_1` and `ddr4_2` anchor there,
`synth/constraints/fable5_floorplan_a.xdc:20-24`, and
the layer's new state-DMA master reaches DDR through them), and the in-context
rewrite Task 14 applies, in full:

```
create_pblock pb_layer_1slr
add_cells_to_pblock pb_layer_1slr [get_cells bd_i/layer_0]
resize_pblock pb_layer_1slr -add {CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}
```

Task 13's eight candidates are superseded and say so at the end of each file:
every pattern in them names the banked array S2 deleted, so each would match
zero cells and constrain nothing while looking like it worked. The banners are
comment-only and appended at the END so that citations into those files keep
their line numbers (`evidence/qwen9b/g5/G5A_FLOORPLAN.md:317` names
`synth/constraints/fable5_floorplan_9b_dngrp.xdc:78`, still line 78).

**The directive is NOT chosen here.** On the 174 netlist −0.245 (Default) and
−0.166 (`AltSpreadLogic_medium`) differed by 0.079 ns; on the 182 netlist
+0.030 and +0.034 differ by 0.004. Both gaps are far inside the 0.475 ns
spread this experiment cannot see past; Task 14 rolls directives on the
in-context netlist as the playbook says.

**Unchanged by fix round 1, and re-confirmed by it.** The choice of this XDC
was made on the 174 netlist and the 182 netlist agrees more strongly, not less:
same pblock, same range, same softness, zero SLLs, and the whole layer in SLR1
at 56.9 % of its URAM and 80.6 % of its DSP. The file itself gained ONE
comment-only block at its END (`MEASURED, 2026-09-05`) carrying the four
measured capacity rows beside the predicted ones it already had — 182 / 320,
1,838 / 2,280, 81 / 720, 114,106 / ≈ 394 K. No constraint line moved, and
`evidence/qwen9b/s5/115_bytes_comment_only.log` is the proof that the file the
two constrained runs read differs from the committed one in comment text only.

---

## 6. WHAT IS *NOT* ESTABLISHED

* **Nothing is routed.** Every timing number here is post-place, pre-route,
  pre-`phys_opt_design`. The playbook's reach is an empirical claim about the
  FULL build, not a promise about this netlist.
* **Nothing is in context.** No XDMA/PCIe/GTs, no four MIGs, no four
  `matvec_chan`s, no `seq_unit`, none of the ~200 K LUTs outside `layer_0`.
  Per §0, success here is necessary and not sufficient.
* **Directive spread is sampled, not characterised**: two directives on the
  constrained variant, one on the baseline, one placement each. Track P's own
  measured spread is 0.475 ns and every number here carries it.
* **Two netlists are reported and they are not interchangeable.** §3.1–§3.2
  and §4.1–§4.3 are placements of the 174-URAM netlist; §3.3–§3.5 and
  §4.4–§4.5 are placements of the 182-URAM one. The second supersedes the
  first everywhere they disagree, and they disagree about more than URAM: the
  unconstrained baseline's WNS reverses from best of three to worst of three.
  No row of one table may be read beside a row of the other without saying
  which netlist it came from.
* **Timing MET at OOC is not timing met.** §3.3's +0.030 and +0.034 are
  post-place, pre-route, pre-`phys_opt`, out of context, on one placement each.
  A positive OOC number does not weaken §0's rule that OOC success is necessary
  and not sufficient — it moves the question to Task 14 without answering it.
* **No throughput or latency claim** is made or repeated here. S4's DMA-lane
  figure is MODELLED and is not a board number
  (`evidence/qwen9b/s4/S4_REPLAY.md`); S5 measures
  structure and placement only.
* **The one congestion warning is not a routing result.** It is a placer
  heuristic on an unrouted design.

---

## 7. THE STOP, its cause, and the fix

**Round 1 stopped here and put the fork to the user; §7.1 is that fork as it
was written, unedited. §7.2 is the ruling and what it cost. §7.3 is the
byte-lock decision the round also had to make.**

### 7.1 The fork as round 1 stated it

The counts gate did not pass and the brief forbids repairing it here. Both
options below are stated with their measured consequences so the choice can be
made on numbers; **S5 does not choose, and no RTL was edited.**

**Option A — make the RTL match the spec.** Add `(* ram_style = "ultra" *)` to
`wm` and `sm` at `rtl/layer_chan.sv` lines 891-892 (as of `6b88724`; §2.4 is
what those two lines say now), exactly as
`rtl/layer_chan.sv:772` and `:836` already do for the DN and KV rows. Predicted
result: URAM 174 → **182** (57 % of one SLR), block RAM 132 → **81** tiles
(11 %) — spec §3's table as written. Cost: one re-run of §2 (20 min) and, to
keep §3–§4 honest, one re-run of the `1slr` placement (50 min). Risk: the conv
slots' compute read path currently ends at a block-RAM `ENARDEN`/`ADDRB` pin;
in URAM it ends at a URAM pin with different timing, and `CV_SLOT` has +0.302
of margin to spend.

**Option B — make the spec match the RTL.** Amend spec §3's conv row to say
block RAM (50 RAMB36 + 2 RAMB18 = 51 tiles) and its totals to URAM **174** /
block RAM **≈ 132 tiles**. Both still fit one SLR with room (54 % / 18 %), and
§3–§4 of this document stand as measured with no re-run at all. Cost: a spec
edit and a note in the plan; nothing rebuilds.

**What is true either way:** the layer places inside ONE SLR with zero SLL
crossings, the ownership mux of A1.2 costs nothing measurable on the DN, KV or
conv write fan-out, and the residual is `ATTN_DSP` at −0.245 / −0.166 — inside
the playbook's reach.

### 7.2 The ruling, the fix, and the one thing it cost

**The controller chose option A**, on the ground that the RTL follows the
approved spec rather than the spec following whatever the tool inferred. The
attribute went in, the counts and the placements were re-run, and the 174 run
stays in this document as the RED that fired the gate. That is §2.4, §2.5,
§3.3–§3.5 and §4.4–§4.5, and the answer is the one the spec predicted: **182
URAM288, 81 block-RAM tiles**, both from two harnesses that agree on every
utilization row.

**Option A's stated risk, checked.** §7.1 said the conv slots' compute path
would move from a block-RAM pin to a URAM pin "with different timing", and
gave `CV_SLOT` its +0.302 of margin to spend. Measured: the family's endpoint
pins are URAM pins now, its cell count fell 680 → 540, and its slack is +0.340
under `1slr` and +0.181 under `1slr-alt` — moving in both directions against
round 1's +0.302 / +0.533, i.e. inside the placement spread rather than
resolvable into a cost (§4.4). No conv path is near either run's WNS.

**What the fix cost that §7.1 did not predict: one line of RTL, and it was one
line too many.** The first form of the fix (commit `203cca8`) put the
attributes on the declarations AND added a one-line comment above them.
`evidence/qwen9b/o3/o3_cite_drift.py --base 6b88724 --plan` over that tree
reported **TOTAL REPAIR 228, COLLATERAL 30** and refused with `O3_FIX_PLAN:
UNSAFE`: every citation into `rtl/layer_chan.sv` below the insertion point
shifts by one, and they live in `docs/SEQ_ISA.md`, three plans,
`docs/QWEN35_NEXT_FEASIBILITY.md`, six gate docs of G3/G4/S2/S3/S4, two
testbench sources and `sw/seq_run.py` — none of them in this round's commit
block, and thirty of the proposed rewrites would have moved a citation that
was already correct. The note is worth having; a 228-citation cascade to carry
it is not. Commit `d9cb8e4` withdrew the added line and rewrote the comment
block that already states the layer's URAM arithmetic, **at the same line
count**, so the file is 2,819 lines at `6b88724` and 2,819 lines now and the
same drift plan is **REPAIR 3, COLLATERAL 0, SAFE** (§10.1). This is worth
recording as a method note, not only as a fact about this file: on a file this
heavily cited, *where* a comment goes is a design decision with a measurable
cost, and the cost is legible before the edit is committed.

**The gates on the attribute.** `evidence/qwen9b/s5/093_lint_layer_chan.log`
and `evidence/qwen9b/s5/094_tb_layer_sdma.log`, on the final bytes `d9cb8e4`;
`evidence/qwen9b/s5/082_lint_layer_chan_clean.log` and
`evidence/qwen9b/s5/083_tb_layer_sdma_clean.log` on `5cb1899`, the bytes the
counts were taken from; and `evidence/qwen9b/s5/080_lint_layer_chan.log` /
`evidence/qwen9b/s5/081_tb_layer_sdma.log`, which gated the edit before it was
committed and read `6b88724+dirty`. All six on snoke, all rc 0, `240 checks`
at each of four seeds. **No model-scale replay was run and none is owed** — a
synthesis attribute selects a primitive; it cannot change what the RTL
computes. The number that could change is the URAM count, and that is what was
re-measured.

### 7.3 The byte-lock: RE-PINNED, not left DIFFERS-by-design

Round 1 declared a consequence: appending the `SUPERSEDED` banners to Task
13's XDCs would make `evidence/qwen9b/g5/g5_bytelock.sh` print DIFFERS on four
of the nine files it locks. Run on this round's clean tree, it is worse than
that — `evidence/qwen9b/s5/084_bytelock_red.log`, the RED:

* **SIX of nine differ, not four.** The four banner-ed XDCs, and also
  `synth/exp_uram/scripts/exp_ooc.tcl` and
  `synth/exp_uram/scripts/launch_exp.sh`, which round 1 edited substantively.
* the `rtl/` section prints a four-file diffstat under a sentence that reads
  "(no lines above = rtl/ byte-identical …)" — S2's rewrite, which the script
  predates;
* and there is **no verdict line at all**: rc 0 on nine DIFFERS. An instrument
  that cannot fail has not checked anything.

**The decision, and why.** The claim the script exists to make
(`evidence/qwen9b/g5/G5A_FLOORPLAN.md:173-174`: the nine files dirty when the
G5a placements launched are byte for byte what commit `5ee5f0e` landed) is
about the PAST and does not decay. What decayed is the COMPARISON — it hashed
the working tree, so every later edit turned an established fact into a false
alarm. A blanket re-pin of the digests to today's bytes was NOT available: two
of the six differ because the S5 vehicle is deliberately not the G5a vehicle,
and pinning those to today would assert something false. So **the comparand
moves, not the digests**: `5ee5f0e` against `6493ca8`, the tree the committed
proof `evidence/qwen9b/g5/006_bytelock_vehicle.log` ran on.

**A pin that can only pass is not a lock, so the script keeps a live half.**
The four banner-ed XDCs are diffed `5ee5f0e`..HEAD and must be COMMENT-ONLY —
35/35/35/44 changed lines, 0 non-comment, which also covers Task 13's own
1,836/690 header correction. A future substantive edit to any of them fires.
The script now ends in a verdict line and a non-zero exit, and
`G5_BYTELOCK_EVIDENCE` overrides the comparand so it HAS a negative control.

| log | verdict |
|---|---|
| `evidence/qwen9b/s5/084_bytelock_red.log` | the RED, on the committed tree `d1e4eff`: six DIFFERS, rc 0, no verdict line |
| `evidence/qwen9b/s5/087_bytelock_repinned.log` | `G5_BYTELOCK: PASS` — 9 vehicle files byte-identical, 4 banner-ed XDCs comment-only, rtl/ unmoved |
| `evidence/qwen9b/s5/088_bytelock_control.log` | the same script with `G5_BYTELOCK_EVIDENCE=HEAD`, i.e. the comparand pointed back at the moving tree: `G5_BYTELOCK: FAIL (7 check(s))`, rc 1 |

**One thing this round did NOT do.** The eight XDC banners carry a
"CONSEQUENCE TO DECLARE" paragraph saying this script "will now print DIFFERS
for those four". That was true between `18641a1` and `f716023` and is
superseded by the re-pin. The banners are left byte-untouched: their whole
point is that nothing above them moves, and editing eight files to update a
declared consequence that this document records is churn, not accuracy.
**Ledgered for whoever opens them next** (review round 1, m7): the paragraph
is now text that says something untrue in eight files, and the round that next
opens any of them for a reason of its own should strike it there rather than
open eight files to do only that.

---

## 8. The log table

Every number above traces to one of these, all committed. Where a marker is not
on the log's last line, the section that uses it names the marker.

| file | what it carries |
|---|---|
| `010_ooc_counts.log` | the counts run in full; `EXP_SYNTH_URAM: 174` is its verdict line |
| `s5_counts_summary.log` | the same run's `EXP_` marker stream alone |
| `ooc_s5_layer_util_synth.rpt` | §2.1 and §2.3's rows (`URAM 174`, `Block RAM Tile 132`, `DSPs 1838`, the CLB table) |
| `ooc_s5_layer_util_synth_hier.rpt` | §2.3's per-instance attribution (`u_dma` 15,051 LUT / 5,073 FF) |
| `011_mem_census.log` | §2.2's table; `MEM_COVER` is its completeness proof |
| `020/021/022_place_*.log` | the three placements in full |
| `s5_{base,1slr,1slralt}_summary.log` | their `EXP_` streams (`EXP_TIMING_SUMMARY`, `EXP_PBLOCK`, `EXP_URAM_SLR`) |
| `s5_*_finish_run.log` | `FIN_KVWRITE_*`, `FIN_CONV_*`, `FIN_DNMUX_*`, the re-stated WNS |
| `s5_*_family_run.log` | §4.2's table (`FAM_ROW`, `FAM_HIST_ROW`, `FAM_OTHER_WORST`) |
| `s5_*_util_placed_slr.rpt` | §3.1's per-SLR census and the SLL counts |
| `s5_*_uram_slr_census.rpt` | the per-slot URAM clock-region census; `CV_CACHE :` is empty on all three, which is §2.2 seen from the placer |
| `s5_*_{dn_write_fanout,kv_write_fanout,conv_bram,dn_bank_mux}_paths.rpt` | the full `report_timing` behind every §4 row |
| `s5_*_timing_summary_placed.rpt` | the WNS/TNS/failing-endpoint table each row's `TIMING_SUMMARY` marker was parsed from |
| `030_finish_reports.log`, `031_family_census.log` | the two completion passes, with their own host/date/tree headers |
| `040_superlatives.log` | the checker's own RED: a `NameError` in S5's copy, kept |
| `042_superlatives.log` | the checker FAILING on this document's §3.2 — see §9 |
| `046_superlatives.log`, `047_superlatives_control.log` | §9's PASS and its negative control, on the document before §9-§10 were written |
| `048_superlatives.log`, `049_superlatives_control.log` | the same two after §9-§10 were written |
| `055_superlatives.log`, `056_superlatives_control.log` | the same two before the `spec_cites` repair round |
| `057_superlatives.log`, `058_superlatives_control.log` | the same two before §11's own repair |
| `070_superlatives.log`, `071_superlatives_control.log` | **the pair that gated this document at the FIRST close** — superseded by 122/123 and then by 149/150 |
| `060_spec_cites.log` | §11's RED half |
| `050_cite_drift_plan.log`, `051_cite_drift_check.log`, `052_cite_drift_fix.log` | §10's dry run, RED half and fix |
| `053_cite_drift_verify.log`, `054_cite_drift_verify.log` | §10's verify before and after the hand repair |

**Fix round 1.** Same rule: every number in §2.4–§2.5, §3.3–§3.5, §4.4–§4.5
and §7.2–§7.3 traces to one of these, all committed, all `=== host: snoke`.

| file | what it carries |
|---|---|
| `evidence/qwen9b/s5/080_lint_layer_chan.log`, `evidence/qwen9b/s5/081_tb_layer_sdma.log` | the gates that licensed the attribute, run on the edit before it was committed (`6b88724+dirty`) |
| `evidence/qwen9b/s5/082_lint_layer_chan_clean.log`, `evidence/qwen9b/s5/083_tb_layer_sdma_clean.log` | the same two on the committed tree `5cb1899` — the bytes the counts were taken from |
| `evidence/qwen9b/s5/093_lint_layer_chan.log`, `evidence/qwen9b/s5/094_tb_layer_sdma.log` | the same two after `d9cb8e4` moved the comment |
| `evidence/qwen9b/s5/113_lint_layer_chan.log`, `evidence/qwen9b/s5/114_tb_layer_sdma.log` | **the pair that gates the RTL as committed** (`cdf7d6c`); `TB_LAYER_SDMA PASS: 240 checks` ×4 |
| `evidence/qwen9b/s5/084_bytelock_red.log` | the byte-lock's RED: six DIFFERS, rc 0, no verdict line |
| `evidence/qwen9b/s5/087_bytelock_repinned.log`, `evidence/qwen9b/s5/088_bytelock_control.log` | §7.3's PASS and its negative control |
| `evidence/qwen9b/s5/090_ooc_counts_exp.log` | the re-count through `synth/exp_uram/scripts/exp_ooc.tcl`; `EXP_SYNTH_URAM: 182  (predicted 182)` is its verdict line |
| `evidence/qwen9b/s5/s5fix_counts_summary.log` | the same run's `EXP_` marker stream alone |
| `evidence/qwen9b/s5/091_ooc_counts_g4b.log`, `evidence/qwen9b/s5/ooc_s5fix_layer_summary.log` | the re-count through the repaired `synth/scripts/ooc_9b.tcl`; `OOC9B_URAM: 182`, the splits, `OOC9B_SLOT_NONURAM_CELLS` |
| `evidence/qwen9b/s5/ooc_s5fix_layer_util_synth.rpt`, `evidence/qwen9b/s5/s5fix_counts_util_synth.rpt` | §2.4's counts table, one per harness — every row identical |
| `evidence/qwen9b/s5/ooc_s5fix_layer_util_synth_hier.rpt`, `evidence/qwen9b/s5/s5fix_counts_util_synth_hier.rpt` | §2.4's per-instance attribution of the +1,002 LUTs |
| `evidence/qwen9b/s5/092_mem_census.log` | §2.4's per-memory table; `MEM_COVER … unnamed=0` is its completeness proof |
| `evidence/qwen9b/s5/100_place_base.log`, `evidence/qwen9b/s5/101_place_1slr.log`, `evidence/qwen9b/s5/102_place_1slralt.log` | the three placements in full |
| `evidence/qwen9b/s5/s5fix_base_summary.log`, `evidence/qwen9b/s5/s5fix_1slr_summary.log`, `evidence/qwen9b/s5/s5fix_1slralt_summary.log` | their `EXP_` streams (`EXP_TIMING_SUMMARY`, `EXP_PBLOCK`, `EXP_URAM_SLR`) |
| `evidence/qwen9b/s5/s5fix_base_finish_run.log`, `evidence/qwen9b/s5/s5fix_1slr_finish_run.log`, `evidence/qwen9b/s5/s5fix_1slralt_finish_run.log` | `FIN_KVWRITE_*`, `FIN_CONV_BRAM_CELLS: 0`, `FIN_PBLOCK`, the re-stated WNS |
| `evidence/qwen9b/s5/s5fix_base_family_run.log`, `evidence/qwen9b/s5/s5fix_1slr_family_run.log`, `evidence/qwen9b/s5/s5fix_1slralt_family_run.log` | §4.4 and §4.5's tables (`FAM_ROW`, `FAM_PATH`, `FAM_HIST_ROW`, `FAM_OTHER_WORST`) |
| `evidence/qwen9b/s5/s5fix_base_util_placed_slr.rpt`, `evidence/qwen9b/s5/s5fix_1slr_util_placed_slr.rpt`, `evidence/qwen9b/s5/s5fix_1slralt_util_placed_slr.rpt` | §3.4's per-SLR census and the SLL counts |
| `evidence/qwen9b/s5/s5fix_base_timing_summary_placed.rpt`, `evidence/qwen9b/s5/s5fix_1slr_timing_summary_placed.rpt`, `evidence/qwen9b/s5/s5fix_1slralt_timing_summary_placed.rpt` | the WNS/TNS/failing-endpoint tables each row was parsed from |
| `evidence/qwen9b/s5/s5fix_base_dn_write_fanout_paths.rpt`, `evidence/qwen9b/s5/s5fix_1slr_dn_write_fanout_paths.rpt`, `evidence/qwen9b/s5/s5fix_1slralt_dn_write_fanout_paths.rpt` | the full `report_timing` behind §4.4's DN rows (and the KV and DN-mux ones beside them) |
| `evidence/qwen9b/s5/s5fix_base_uram_slr_census.rpt`, `evidence/qwen9b/s5/s5fix_1slr_uram_slr_census.rpt`, `evidence/qwen9b/s5/s5fix_1slralt_uram_slr_census.rpt` | the per-slot URAM clock-region census — `CV_CACHE` is NON-empty on all three now, which is §2.4 seen from the placer |
| `evidence/qwen9b/s5/103_finish_reports.log`, `evidence/qwen9b/s5/104_family_census.log` | the two completion passes, with their own host/date/tree headers |
| `evidence/qwen9b/s5/095_rtl_comment_only.log`, `evidence/qwen9b/s5/096_rtl_comment_only_control.log` | the run-tree bytes check over `rtl/` only — superseded by 097/098 |
| `evidence/qwen9b/s5/097_bytes_comment_only.log`, `evidence/qwen9b/s5/098_bytes_comment_only_control.log` | the same over `rtl/` AND the floorplan XDC, at `7d416cf` — superseded by 115/116 |
| `evidence/qwen9b/s5/115_bytes_comment_only.log`, `evidence/qwen9b/s5/116_bytes_comment_only_control.log` | **the pair §1 cites**: 22 changed lines, 0 non-comment, against the FINAL RTL; the control at 1,055 non-comment |
| `evidence/qwen9b/s5/110_superlatives.log`, `evidence/qwen9b/s5/111_superlatives_control.log` | §9.1's PASS and control on the draft before §11's first five repairs |
| `evidence/qwen9b/s5/117_superlatives.log`, `evidence/qwen9b/s5/118_superlatives_control.log` | the same two on the draft before §11's last three |
| `evidence/qwen9b/s5/122_superlatives.log`, `evidence/qwen9b/s5/123_superlatives_control.log` | **the pair that gated this document at the end of FIX ROUND 1** — superseded by 149/150 |
| `evidence/qwen9b/s5/120_spec_cites.log` | this round's `spec_cites` RED: the three failures §11's own sentence re-created |
| `evidence/qwen9b/s5/105_cite_drift_plan.log`, `evidence/qwen9b/s5/106_cite_drift_check.log`, `evidence/qwen9b/s5/107_cite_drift_fix.log` | §10.1's dry run, RED half and fix |
| `evidence/qwen9b/s5/108_cite_drift_verify.log`, `evidence/qwen9b/s5/109_cite_drift_verify.log` | §10.1's verify without and with its four hand-justified exclusions |

**Fix round 2.** Same rule again: every number in §2.6 and every count §9.1
quotes traces to one of these. §11's citation figures come from the round's
final `spec_cites` run, which this table deliberately does not name — §11 says
why.

| file | what it carries |
|---|---|
| `evidence/qwen9b/s5/140_counts_probe.log` | §2.6's run: the WIDENED non-URAM probe on the 182 netlist, `EXP_SYNTH_SLOT_NONURAM_CELLS: dn=0 kv=0 cv=0 total=0`, with URAM/BRAM/DSP unmoved |
| `evidence/qwen9b/s5/141_cite_drift_plan.log`, `evidence/qwen9b/s5/142_cite_drift_check.log`, `evidence/qwen9b/s5/143_cite_drift_fix.log` | §10.2's dry run, RED half and repair |
| `evidence/qwen9b/s5/144_cite_drift_verify.log` | §10.2's GREEN half, no exclusions |
| `evidence/qwen9b/s5/145_superlatives.log`, `evidence/qwen9b/s5/146_superlatives_control.log` | the same two on the draft before §1's `+dirty` note — superseded |
| `evidence/qwen9b/s5/147_superlatives.log`, `evidence/qwen9b/s5/148_superlatives_control.log` | the same two before §11's figures were scoped — superseded |
| `evidence/qwen9b/s5/149_superlatives.log`, `evidence/qwen9b/s5/150_superlatives_control.log` | **the pair that gates this document as committed** — the live one; the two rows above carried this same label until 2026-09-10, which made the table ambiguous exactly where a reader checks a claim |

## 9. The superlative check

`evidence/qwen9b/s5/s5_superlatives.py` — Task 13's checker re-pointed at S5's
three variants, S5's family names and this document. It reads the SAME
committed logs §3 and §4 are built from, computes the extremum and runner-up of
each column, then requires every superlative sentence here to name the variant
that actually holds it.

**It caught a real one in this document, before any synthetic control.**
`superlative-check: quoted` — this paragraph restates a claim that was false
when it was written and is false again on the 182 netlist, in order to record
that the checker caught it; the ranking it names is round 1's.
`042_superlatives.log` is `S5SUP: FAIL (1)` on §3.2, whose sentence read "the
unconstrained baseline's −0.136 is the best WNS of the three" while naming only
the label `1slr` — "baseline's" is not the label `base`, so the claim as
written attributed the extremum to the wrong row. §3.2 now names `base`.
`040_superlatives.log` is one step earlier still: a `NameError` in S5's copy of
the script, kept because a checker that crashes is a checker that passes
nothing, and the log says which.

`046_superlatives.log` is the PASS on the repaired document
(`S5SUP: PASS`, 2 sentences machine-checked, 2 SCOPED, 12 UNCHECKED) and
`047_superlatives_control.log` is the negative control, which plants a claim
that is false by construction — the row with the WORST WNS is awarded the best
WNS of the three — and requires the checker to catch it:
`S5SUP_CONTROL: CAUGHT — the checker is live`. A control that is NOT caught is
itself a failure and exits non-zero.

**Which run gates which text.** `046`/`047` are the PASS and the control on the
draft before §9 and §10 existed; that is the run the paragraph below
enumerates, and its UNCHECKED count is 12. `048`/`049` are the same two after
§9 and §10 were written, at 14 UNCHECKED — the two extra are §9's own
sentences ABOUT the checker, which carry superlative words because they quote
the planted claim. `055`/`056` are the same two before this document's
`spec_cites` repair round (§11), `057`/`058` the same again mid-round, and
`070`/`071` the pair run on the document exactly as committed — the ones that
gate it: `S5SUP: PASS` and
`S5SUP_CONTROL: CAUGHT — the checker is live`. `046` and `047` ran on the clean
tree `7cf6119`, `048`/`049` and `055`/`056` on `cf5b541`; `057`/`058` and
`070`/`071` ran at `ad66aef+dirty`, where the ONE modified file is this
document — which is unavoidable, since a document cannot be checked before it
is written and cannot be committed before it is checked;
`042` ran at `938e025+dirty`, where the one modified file was the checker's own
`default=G5` → `default=S5` fix, committed unchanged at `7cf6119`.

**The 12 UNCHECKED sentences are not silently passed.** The checker attributes
a sentence to a column by the words around it and needs a variant LABEL to
rank; a sentence with a superlative word but no variant is printed rather than
judged. All twelve are hand-verified in the S5 report, and none of them ranks
S5's variants: they are the reading rule quoted from
`evidence/qwen9b/g5/G5A_FLOORPLAN.md` §0
(":32", ":293"), method sentences (":59", ":317", ":392"), `only`-as-in-"the
only parameter left" (":94" — `layer_chan`'s parameters are five ROM path
strings and `SDMA_NOFENCE`, `rtl/layer_chan.sv:210-241`), the two `u_dma`
attributions of §2.3 (":216", both re-derived there with their arithmetic), the
`SDMA` path names (":387", quoted verbatim from `FAM_PATH SDMA`), the banner
note (":424"), S4's modelled-figure caveat (":440") and §9's own description of
the control (":533").

**One instrument wart, recorded.** The checker's cue list tests `write fan-out`
(the DN column) before `KV write`, so §4.1's sentence about the KV row is
reported SCOPED beside the DN ranking rather than the KV one. SCOPED prints a
ranking next to a claim; it does not assert the claim, so nothing here rests on
it — but a reader of `046_superlatives.log` should not take that ranking as the
one the sentence is about.

### 9.1 Fix round 1 — the checker re-pointed, and what it now holds

The checker's `ORDER` becomes the three `s5fix_*` runs — the placements on the
182-URAM netlist — keeping the labels `base` / `1slr` / `1slr-alt`, because
those are what this document's prose names and §3.3 is now its placement
table. **The alternative was worse:** ranking all six runs together would make
"the best of the three" mean the best of six numbers off two different
netlists. The superseded 174 rows stay as DATA, inside tables, which the
checker skips by design; the one paragraph that RANKS them — §3.2's, whose
ordering the 182 netlist reverses — carries `superlative-check: quoted`, the
hatch this checker already provides for a superseded claim restated in order
to correct it.

`evidence/qwen9b/s5/122_superlatives.log` is the PASS on this document as
committed and `evidence/qwen9b/s5/123_superlatives_control.log` is its
negative control (`S5SUP_CONTROL: CAUGHT — the checker is live`); they are the
pair that gates the text you are reading, and `070`/`071` gate round 1's.
`evidence/qwen9b/s5/110_superlatives.log` /
`evidence/qwen9b/s5/111_superlatives_control.log` and
`evidence/qwen9b/s5/117_superlatives.log` /
`evidence/qwen9b/s5/118_superlatives_control.log` are the same two, one and
two steps earlier: on the draft before `evidence/qwen_next/spec_cites.py`
caught the first five failures §11 records, and on the draft before it caught
the three that the sentence describing those five re-created. All three pairs
are kept, because a document edit invalidates the run before it and the log
table has to say which run gates which text.
The instrument wart recorded below is unchanged.

**Fix round 2 adds three more pairs, for the same reason.** This round
appended §2.6, §10.2 and the paragraphs below and rewrote §4.2's endpoint-cell
column into ranges, so `evidence/qwen9b/s5/122_superlatives.log` no longer
describes the text you are reading.
`evidence/qwen9b/s5/149_superlatives.log` is the PASS on the document as
committed and `evidence/qwen9b/s5/150_superlatives_control.log` is its
negative control; they are the pair that gates it.
`evidence/qwen9b/s5/145_superlatives.log` /
`evidence/qwen9b/s5/146_superlatives_control.log` and
`evidence/qwen9b/s5/147_superlatives.log` /
`evidence/qwen9b/s5/148_superlatives_control.log` are the same two on the two
drafts before it — before §1's `+dirty` note, and before §11's citation
figures were scoped — kept for the reason all the others are: an edit
invalidates the run before it, so the log table has to say which run gates
which text. `122`/`123` now gate fix round 1's text exactly as `070`/`071`
gate round 1's. The checker itself is byte-untouched by this round; across
the three pairs the UNCHECKED count moves from 41 to 42, the extra sentence
being §11's own scoping clause.

**What the PASS covers: 4 machine-checked, 3 QUOTED, 4 SCOPED, 42
UNCHECKED.**
Round 1's PASS covered 2 checked sentences; a checker that holds nothing
passes everything, so §3.3 states four rankings in the form the script can
attribute — the WNS extremum, the SLL extremum, the DN write fan-out extremum
and the KV write extremum — and each names the variant that the committed logs
say holds it. The 42 UNCHECKED are printed, not passed silently.

**Two of them DO rank the three variants of this netlist against each other,
and fix round 2 names them rather than claiming none does** (review round 1,
m3). They are §3.5's "the single congestion warning is on `1slr-alt` only" and
§4.5's "`base` and `1slr` carry none" — congestion, which is not one of the
eleven columns `evidence/qwen9b/s5/s5_superlatives.py` reads, so it cannot
attribute the claim and drops both sentences into UNCHECKED without a word.
Both are hand-checked instead, and the check is printed beside each claim:
`grep -c 'Place 46-14'` over the three COMMITTED place logs of each netlist —
**0 / 0 / 1** here (§4.5) and **0 / 1 / 1** in round 1 (§4.3). The rest of the
UNCHECKED set ranks nothing: it is the reading rule, method sentences, the
`u_dma` attributions of §2.3 and §2.4 (re-derived there with their
arithmetic), path names quoted verbatim from `FAM_PATH`, the banner and
byte-lock notes, and §9–§11's own descriptions of the instruments.
Two carry claims worth naming here because they are arithmetic rather than
prose, and both are re-derivable from the tables above: §4.4's "the lower of
the two constrained conv rows is +0.181, and no conv path is within 0.14 ns of
either run's WNS" (+0.181 − +0.034 = 0.147, +0.340 − +0.030 = 0.310), and
§6's "the unconstrained baseline's WNS reverses from best of three to worst of
three" (−0.136 against −0.245 / −0.166 in round 1; −0.588 against +0.030 /
+0.034 here).

---

## 10. Citation drift

`evidence/qwen9b/o3/o3_cite_drift.py` at base `e16a3ec`, edited set = the ten
non-`s5/` files S5 touched (`exp_ooc.tcl`, `launch_exp.sh`, the eight Task-13
XDCs). The eight XDCs contribute nothing: their banners are appended at the END
and `synth/constraints/fable5_floorplan_9b_dngrp.xdc:78`, the one line anything
cites, is
byte-identical to `e16a3ec`. `exp_ooc.tcl` is where the drift is.

`051_cite_drift_check.log` is the RED half: **7 drifted, 9 unresolved, 1
half-mapped** across three citing files. `052_cite_drift_fix.log` repairs the
seven. `053_cite_drift_verify.log` is the verify BEFORE the hand repair below —
`VERIFY FAIL (11)`, kept because it is the record of what the tool could and
could not do.

**The nine UNRESOLVED and the one HALF-MAPPED are hand-repaired, and the
repair is not a renumbering.** All ten are in the plan's own **Task S5 task
description** (`docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md:595`,
which carries `<!--cites:noquote-->`): they named `set DN_BPG …`, `-generic
DN_PIPE=$DN_PIPE …`, `set PRED [expr {$DN_NB * $DN_PER …}]` and the rest — the
lines S5 was INSTRUCTED to delete. Renumbering an instruction onto whatever now
occupies those coordinates would make it describe lines that do not say what it
says they say, so they are **rewritten OUT of citation form** — the tool's own
documented remedy for a citation whose code no longer exists — with the
`e16a3ec` coordinates kept in prose and `git show e16a3ec:…` named as the file
they described. The one exception is the file-list range that was lines 129-130
at `e16a3ec`, which the tool refused as HALF-MAPPED because its end endpoint
changed
(`… vec_alu layer_chan} {` became `… vec_alu state_dma layer_chan} {`): both
endpoints still exist, so it IS renumbered, by hand, to
`synth/exp_uram/scripts/exp_ooc.tcl:164-165`.

`054_cite_drift_verify.log` is the GREEN half after that hand repair:
`O3_CITE_DRIFT VERIFY PASS (0 problem(s))`, with the plan excluded — `--exclude`
is the tool's own mechanism for a document repaired by hand in the final tree's
coordinates. The plan's three surviving citations are hand-checked instead, and
the content is quoted here so the check is not a claim.
`synth/exp_uram/scripts/exp_ooc.tcl:75` is
`set Rtl       "$RepoRoot/rtl"`.
`synth/exp_uram/scripts/exp_ooc.tcl:141` is
`set geom_ok 1`.
`synth/exp_uram/scripts/exp_ooc.tcl:164-165` is
`foreach f {fx_pkg fx_rsqrt fx_recip fx_silu vecnorm_unit rope_unit conv4_silu`
followed by
`           dn_step attn_core gate_unit vec_alu state_dma layer_chan} {`.

**A commit-block extension, declared.** The seven repairs land in
`docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md`,
`evidence/qwen9b/g5/G5A_FLOORPLAN.md` and one comment line of
`rtl/layer_chan.sv:341` — none of which is in S5's commit block. Leaving them
stale is not an option: `plans/…:42` carries the quotation
`set Rtl "$RepoRoot/rtl"` on the same line as the cite, which is exactly what
`evidence/qwen_next/spec_cites.py` checks, so the gate cannot go green with the
citation pointing 18 lines away. They are committed in a separate,
citation-repair-only commit; `git diff --stat` over `rtl/layer_chan.sv` shows
one line changed, and no RTL statement is touched.

### 10.1 Fix round 1 — base `6b88724`

Edited set = the six non-`s5/` files this round touched: `rtl/layer_chan.sv`,
`synth/scripts/ooc_9b.tcl`, `evidence/qwen9b/g5/g5_bytelock.sh`,
`docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md`,
`synth/exp_uram/scripts/exp_ooc.tcl` and
`synth/constraints/fable5_floorplan_9b_1slr.xdc`. Four of the six are
constructed so that they contribute NOTHING: the spec is append-only, the XDC
gained a block at its END, `exp_ooc.tcl`'s edit is one comment line in place,
and `rtl/layer_chan.sv` is 2,819 lines before and after (§7.2 is why that
mattered). `evidence/qwen9b/g5/g5_bytelock.sh` is rewritten but nothing
cites it.

So the drift is `synth/scripts/ooc_9b.tcl`'s, which this round deliberately
repaired. `evidence/qwen9b/s5/105_cite_drift_plan.log`: **REPAIR 5,
COLLATERAL 0**, `O3_FIX_PLAN: SAFE` — three in
`evidence/qwen9b/g4/G4B_STRUCT.md` and two in `evidence/qwen9b/s2/S2_RTL.md`,
every one a pure renumbering of a citation into the file whose file list,
prediction and synth block moved. `evidence/qwen9b/s5/106_cite_drift_check.log`
is the RED half (6 drifted, 4 unresolved, 1 half-mapped),
`evidence/qwen9b/s5/107_cite_drift_fix.log` the repair (`FIXED 6 citation(s)
in 2 document(s)`).

**Two edits this round made ONLY to keep citations resolvable** are in §7.2
and in the commit `cdf7d6c`: `rtl/layer_chan.sv:359-360` put back to their
exact base text, because `evidence/qwen9b/g3/G3_1_ISA.md` cites them; and
`synth/scripts/ooc_9b.tcl`'s `set generics {}` RESTORED after being deleted as
dead, because `evidence/qwen9b/s2/S2_RTL.md` cites it as the evidence for S2's
own M2 fix — deleting a line is a poor way to preserve the record that the
line is empty on purpose. Both were found by `--check`, before either was
committed in its final form.

**The verify, and the four documents it excludes.**
`evidence/qwen9b/s5/108_cite_drift_verify.log` is the verify WITHOUT
exclusions — `VERIFY FAIL (5)`, kept, because it is the record of what the
tool can and cannot resolve. `evidence/qwen9b/s5/109_cite_drift_verify.log` is
`O3_CITE_DRIFT VERIFY PASS (0 problem(s))` with four documents excluded, each
for a reason that is checked by hand here:

| excluded | why | hand-check |
|---|---|---|
| `evidence/qwen9b/s5/S5_STRUCT.md` | written in the FINAL tree's coordinates; `--fix` would map it a second time and double-shift (the tool's own documented case) | the four citations the tool names are §1.1's and §2.2's, and all four are REWRITTEN OUT of citation form above, with the `6b88724` coordinates kept in prose — the same remedy round 1 used at §10 |
| `evidence/qwen9b/s3/S3_CHAIN.md` | its citation is **sha-pinned**, `d2d774b:rtl/layer_chan.sv:891` | a sha-pinned citation names a tree that cannot move; the drift tool treats it as live, which is the gap the S5 dispatch context names. Verified by eye: `evidence/qwen9b/s3/S3_CHAIN.md` line 745 carries the `d2d774b:` prefix |
| `evidence/qwen_next/feas/toks_model.py` | the same sha-pin, twice | lines 223 and 335 both carry `d2d774b:` |
| `evidence/qwen9b/g3/G3_4_LAYER.md` | a HISTORICAL table row: it records an old citation *and its repair* side by side | the row names `rtl/layer_chan.sv:891` as the OLD coordinate and `rtl/layer_chan.sv:1209` at `8ef57a8` as the repaired one; renumbering the old half would destroy the record |

None of the four is a citation this round made stale. The two it did make
stale — `rtl/layer_chan.sv:891-892`, whose LINES did not move but whose TEXT
this round changed — are this document's own, and are the ones rewritten out
of citation form.

**A commit-block extension, declared.** `evidence/qwen9b/g4/G4B_STRUCT.md` and
`evidence/qwen9b/s2/S2_RTL.md` are not in this round's block; leaving Task
12's and S2's gate docs pointing at lines that have moved is not an option,
and all five repairs are pure renumbering. They are committed in a separate,
citation-repair-only commit.

**One extension that is NOT a pure renumbering, and why it is left standing**
(review round 1, m11). Round 1's own drift pass (§10) rewrote nine coordinates
in the plan's Task-S5 entry OUT of citation form and added an italic paragraph
saying so — prose, not a renumbering, in a file whose extension was declared
as drift-only. That is the drift tool's DOCUMENTED remedy for a citation whose
code the task was instructed to delete: renumbering such a cite onto whatever
now occupies the coordinate makes it describe lines that do not say what it
says they say. The remedy keeps the `e16a3ec` coordinates in prose and names
`git show e16a3ec:…` as the file they described, and it is declared both in
that commit's message and in §10 above. The plan is left exactly as it
stands.

**One citation the tool cannot see, repaired by hand.**
`synth/exp_uram/scripts/exp_ooc.tcl:158` cites `synth/scripts/ooc_9b.tcl`'s
file list. `evidence/qwen9b/o3/o3_cite_drift.py`'s roots are `docs/` and
`evidence/`, so a comment under `synth/` is outside its sweep. That citation
was ALREADY stale at `6b88724` — it named lines 68-69 of that file, and the
list had moved to lines 77-78 before this round — and this round moved the
list again by adding `state_dma` to it. Renumbered by hand to
`synth/scripts/ooc_9b.tcl:83-85`, in a one-line commit that adds and removes
nothing else. (The three ranges in this paragraph are written as prose rather
than as bare `:NNN` continuations, which bind to no file and are therefore
checked by nothing — the ORPHAN class `evidence/qwen_next/spec_cites.py`
caught three times in round 1's §11.)

### 10.2 Fix round 2 — base `0274fe8`

Edited set = the three non-`s5/` files this round touched:
`synth/exp_uram/scripts/exp_ooc.tcl` (the widened probe),
`evidence/qwen_next/spec_cites.py` (the `PENDING` prune) and
`docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md` (A2.2's
wording). Two of the three contribute nothing: nothing in the repository cites
the citation checker by line, and the spec's edit is inside A2, which sits at
the END of the file, so no line any document cites moved — confirmed by
`git diff`, whose only hunk on that file starts well past A2's heading.

`synth/exp_uram/scripts/exp_ooc.tcl` is where the drift is, and it is the
mechanical kind: the widened probe adds 18 lines at what was line 213, so
everything below shifts by 18.
`evidence/qwen9b/s5/141_cite_drift_plan.log` is the dry run —
**REPAIR 2, COLLATERAL 0**, `O3_FIX_PLAN: SAFE`.
`evidence/qwen9b/s5/142_cite_drift_check.log` is the RED half: `CHECK FAIL`,
**3 drifted, 0 unresolved, 0 missing, 0 half-mapped**, all three endpoints in
two sentences of `evidence/qwen9b/g5/G5A_FLOORPLAN.md` —
`evidence/qwen9b/g5/G5A_FLOORPLAN.md:71`, which names the endpoint-selection
line, and `evidence/qwen9b/g5/G5A_FLOORPLAN.md:176`, which names the pblock
sanity block.
`evidence/qwen9b/s5/143_cite_drift_fix.log` renumbers them
(`FIXED 3 citation(s) in 1 document(s)`) and
`evidence/qwen9b/s5/144_cite_drift_verify.log` is
`O3_CITE_DRIFT VERIFY PASS (0 problem(s))` — **with no exclusions at all**,
which is the difference from §10 and §10.1: nothing sha-pinned and nothing
hand-repaired was proposed, so nothing had to be argued out of the sweep.

**A commit-block extension, declared.** `evidence/qwen9b/g5/G5A_FLOORPLAN.md`
is not in this round's block. Leaving Task 13's gate doc pointing 18 lines away
from the code it quotes is not an option, and the repair is two lines of pure
renumbering — line 406 becomes line 424 and the range 250-266 becomes 268-284,
both written here as prose rather than as bare colon-number continuations,
which bind to no file and are checked by nothing (§11's ORPHAN class). `git
diff` over that file is 2 insertions / 2 deletions with no prose touched.
It is committed together with the four drift logs and nothing else.

---

## 11. `spec_cites` and the repair round it forced

`evidence/qwen_next/spec_cites.py` over this document, the plan and Task 13's
gate doc. Its first pass — `060_spec_cites.log`, `SPEC CITES: FAIL`,
**22 failures, every one of them in text S5 wrote** — is committed as the RED
half rather than quietly repaired:

* **15 EXIST**: this document named files by BASENAME — fable5_floorplan_9b_1slr.xdc,
  finish_reports.tcl, run.sh, state_dma.sv, G4B_STRUCT.md, S4_REPLAY.md and
  the rest, written here deliberately WITHOUT backticks so this sentence does
  not re-create the defect it describes. A bare basename resolves only if it
  sits beside the citing document; for a file anywhere else it is not a
  citation at all, just a word that looks like one. All fifteen are now
  repo-relative paths, except the per-run Vivado log, which lives in a
  gitignored `synth/out_*` directory and is written as prose instead.
* **2 QUOTE**: §2.2 put the `wm`/`sm` declarations and the `ram_style`
  attribute on markdown lines carrying a DIFFERENT `rtl/layer_chan.sv` cite, so
  the checker paired each quotation with the wrong line. §2.2 now gives each
  quotation its own cite.
* **3 ORPHAN**: §10's bare backticked line-range continuations (129-130 and
  164-165) sat on lines naming no file, so they bound to nothing and were not
  checked at all. The live one is now written as a full path; the dead one is
  prose.

The GREEN half is the `spec_cites` log numbered 061 in this directory. It is
the LAST commit of round 1 and contains that log and nothing else, so the
tree its header names is the tree every other claim here was checked on.

**Fix round 1 keeps the same rule, and `spec_cites` caught five failures in
the fix round's own text before it went green.** §1's run table named
Task 13's finish-report script and §10.1 named the byte-lock script by
BASENAME — written here without backticks, as the bullets above are, so this
sentence does not re-create the defect it describes — which is the EXIST
class round 1 hit fifteen times, recurring twice in text written AFTER this
section described it. And §10.1 wrote three line ranges as bare
colon-number continuations on lines naming no file: the ORPHAN class,
recurring three times. All five are repaired — the two basenames are
repo-relative paths and the three ranges are prose — and the run that caught
them is the log numbered 120 in this directory, kept as this round's RED
half. **Fix round 1's GREEN `spec_cites` log** is the one
numbered 130 in this directory; it is the LAST commit of the round, contains that log
and nothing else, and runs on the committed tree of the commit immediately
before it — which is the tree that carries every sentence added above. It is
not cited by any sentence of this document, deliberately: a document that
cites the log of its own final check cannot be checked by it.

**Fix round 2: the closing gate was not checking this task's own
deliverables.** `evidence/qwen_next/spec_cites.py`'s `PENDING` set still listed
five paths that had LANDED — the floorplan XDC this task exists to produce,
this document, its superlative checker, its round-1 utilization report, and
S4's gate doc. `PENDING` is tested BEFORE `EXIST`, so every citation to those
five was REPORTED and SKIPPED rather than checked, and the log numbered 130 in
this directory says so on its own headline: `pending 27`, of which **15 were
citations in this document** — including the **eight** of the XDC's twelve
that are this document's — **11 in the plan** and **1 in the state-spill
design spec**. 15 + 11 + 1 = 27. *(Recounted from the log itself on
2026-09-10: this read "15 … and 9 in the plan", which is 24.)* No number was wrong: none of the 27 carries a line range,
so only the EXIST check was suppressed and all five files do exist. But a
closing gate that skips the task's own deliverables is not a gate, and Task 14
would have inherited the hole with its own citations into the XDC and into
this document.

**The five are pruned**, the way S1, S2 and S3 each pruned theirs at close,
and for the reason the instrument's own comment block gives a dozen times: a
stale `PENDING` entry lets a typo in the path — or a deletion of the file —
pass silently. `PENDING` now holds **two** entries, both genuinely future: the
Task 14 and Task 15 gate documents, named here WITHOUT backticks so this
sentence does not create the citation it is describing, and neither is cited
by any of the four documents this gate reads. So the round's final
`spec_cites` reports **pending 0** — the disclosure review round 1 asked for,
and the number is zero rather than a residue.

**What the prune bought, isolated from everything else this round wrote.**
Measured on the same four documents at the text 130 ran against, so that the
only difference is the five deleted entries: the 27 skipped citations become
27 more EXIST checks, **751 → 778 exist**, with range and quote unchanged at
238 and 5 and FAIL still 0. The round's own final log counts higher than that
on both axes, because the sections above added citations of their own — its
headline reads 842 exist, 244 range, 5 quote, pending 0, retired 0, FAIL 0 —
so 778 is the prune's effect and **842** is this document's size, and neither
should be read as the other. *(838 until 2026-09-10 — a transposition; the
headline three lines above reads 842.)* Every citation to the floorplan XDC, to this
document, to `evidence/qwen9b/s5/s5_superlatives.py`, to
`evidence/qwen9b/s5/ooc_s5_layer_util_synth.rpt` and to
`evidence/qwen9b/s4/S4_REPLAY.md` is checked now, and **none of them needed
repair** — the prune added checks, it did not force a single citation to
move. **Fix round 2's GREEN log** is the one numbered 160 in this directory:
the LAST commit of the round, holding that log and nothing else, run on the
committed tree of the commit immediately before it, and — like 061 and 130 —
cited by no sentence here.
