# fable5_floorplan_9b_1slr.xdc — THE STATE-SPILL FLOORPLAN: the whole layer in
# ONE SLR (S5 of the 2026-09-04 state-spill plan; spec §12 risk 1 is the gate
# this file exists to test).  DERIVED FROM synth/constraints/fable5_floorplan_a.xdc,
# the 2B campaign winner, whose four soft mvchan pblocks and deliberate ABSENCE
# of a layer_0 pblock are the baseline this variant is measured against.
# =============================================================================
# WHAT SUPERSEDES WHAT.  Task 13's eight `fable5_floorplan_9b_*.xdc` candidates
# all floorplan the G3.4 layer: a 928-URAM288 DN/KV BANK ARRAY that spans all
# three SLRs by arithmetic (2 x 320 = 640 < 928) and whose banks, groups and
# fan-out register sets are the cells those files name.  S2 RETIRED that array
# — the layer state lives in DDR now behind `state_dma`, and what stays on chip
# is two cache slots per kind, 182 URAM288 in total (spec §3).  Every pattern in
# those eight files therefore matches ZERO cells on this design, which Vivado
# reports only as a CRITICAL WARNING; each of them now carries a SUPERSEDED
# banner saying so.  This file replaces all eight.
#
# ADDRESSING FORM: **OOC**.  This file is written for
# `synth/exp_uram/scripts/exp_ooc.tcl`, where `layer_chan` is the TOP module and
# there is no `bd_i/` hierarchy.  `get_cells *` at OOC top level means "every
# top-level cell of layer_chan", and a hierarchical cell in a pblock constrains
# its whole subtree, so the one line below claims the ENTIRE design.
#
# THE TASK-14 IN-CONTEXT REWRITE, stated here as Task 13's files state theirs.
# `get_cells *` is exactly the pattern that does NOT prefix-rewrite: in context
# it would mean the whole block design, not the layer.  The in-context form of
# this pblock is the single hierarchical cell —
#
#     create_pblock pb_layer_1slr
#     add_cells_to_pblock pb_layer_1slr [get_cells bd_i/layer_0]
#     resize_pblock pb_layer_1slr -add {CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}
#
# — and NOTHING else changes: same range, same SOFT-ness, same one pblock.
#
# IMPLEMENTATION-ONLY: exp_ooc.tcl `read_xdc`s this AFTER synth_design and
# BEFORE opt_design, which is the non-project equivalent of full_impl.tcl's
# `add_files -fileset constrs_1` + `USED_IN_SYNTHESIS false`
# (synth/scripts/full_impl.tcl:21-30).  No RTL moves.
#
# FLAT XDC — no foreach (Designutils 20-1307), same as fable5_floorplan_a.xdc.
# SOFT, in fable5_floorplan_a.xdc's sense: no CONTAIN_ROUTING and no
# EXCLUDE_PLACEMENT, so the placer may still put non-member cells inside the
# range and may spill a member if it must.  Softness is deliberate: the reading
# rule (evidence/qwen9b/g5/G5A_FLOORPLAN.md §0) is that the OOC run is a
# measurement, and a hard pblock would turn "does it fit" into "did the placer
# give up", which is a worse answer.  The `*_uram_slr_census.rpt` counts, not
# the pblock's existence, are what say whether the layer actually landed in one
# SLR.
#
# SLR geometry, MEASURED off the part by synth/exp_uram/scripts/dev_geom_census.tcl
# (evidence/qwen9b/g5/002_dev_geom_census.log), not assumed:
#   SLR0 = CLOCKREGION_X0Y0..X5Y4   SLR1 = X0Y5..X5Y9   SLR2 = X0Y10..X5Y14
#   each: 320 URAM288 / 2,280 DSP48E2 / 720 RAMBFIFO36 / 49,260 SLICE
#   URAM288 sites live ONLY in CLOCKREGION columns X1..X4 (16 per clock region,
#   4 columns x 16 x 15 rows = 960).  X0 and X5 carry no URAM.
#
# WHY SLR1 and not SLR0 or SLR2 (fable5_floorplan_a.xdc:20-24): the MIG anchors
# are fixed by their IO banks — ddr4_0 in SLR0, **ddr4_1 and ddr4_2 in SLR1**,
# ddr4_3 in SLR2.  The layer's new `m_axis` state-DMA master (spec §4) reaches
# DDR through the central SmartConnect, so the SLR that carries two of the four
# MIGs is the one that shortens that path, and it is also the middle SLR — every
# other block is at most one SLR crossing away.
#
# CAPACITY CHECK (the standing rule: check DSP and BRAM per SLR BEFORE
# constraining anything).  Against ONE SLR's budget:
#   URAM288      182 of   320   57 %   (spec §3: DN 2x29 + KV 2x58 + CV 2x4)
#   DSP48E2    1,836 of 2,280   81 %   <- the TIGHT resource (spec §12 risk 1)
#   RAMB tiles   ~90 of   720   13 %   (the scratchpad dominates)
#   LUT       ~110 K of ~394 K   28 %   (49,260 SLICE x 8 LUT)
# The DSP row is the one to watch: 81 % of an SLR's DSP columns in a soft pblock
# is a real constraint on the placer, and it is exactly the number spec §12
# risk 1 names as the reason this is a gate and not an assumption.
#
# NEVER pblocked (standing rule): xdma_0/PCIe/GTs (fixed sites), the ddr4_*
# MIGs.  Neither exists in the OOC context; both are named here so the Task-14
# in-context derivation of this file cannot forget them.  In context this pblock
# holds `bd_i/layer_0` ONLY — it must never be widened to `bd_i`.
#
# THE 2B CAMPAIGN'S WARNING, which this file deliberately re-tests: constraining
# `layer_0` in ANY form cost ~1 ns on the 2B design (fable5_floorplan_a.xdc:8-10,
# TIMING_035.md §11.7), and fable5_floorplan_a.xdc's key result is the
# DELIBERATE ABSENCE of a layer_0 pblock.  The 9B state-spill layer is a
# different design — 182 URAM instead of 928, no banked array to straddle — so
# the question is reopened, and the UNCONSTRAINED baseline run beside this one
# is what answers it.  If the baseline is better, this file is not the answer.
# =============================================================================

# ---- pb_layer_1slr: EVERY cell of layer_chan -> SLR1
create_pblock pb_layer_1slr
add_cells_to_pblock pb_layer_1slr [get_cells -quiet *]
resize_pblock pb_layer_1slr -add {CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}

# =============================================================================
# MEASURED, 2026-09-05 (S5 fix round 1) — appended at the END so every line
# above keeps its number.  The CAPACITY CHECK block above is spec §3's
# PREDICTION, written before the layer had ever been synthesized.  It has now
# been measured out of context by two independent harnesses
# (evidence/qwen9b/s5/090_ooc_counts_exp.log,
#  evidence/qwen9b/s5/091_ooc_counts_g4b.log), and the prediction was right
# about the resource that binds and wrong about one that does not:
#   URAM288      182 of   320   57 %   as predicted
#   DSP48E2    1,838 of 2,280   81 %   as predicted (1,836) — still the TIGHT one
#   RAMB tiles    81 of   720   11 %   predicted "~90"; spec amendment A2.2
#   LUT      114,106 of ~394 K  29 %   predicted "~110 K"
# Nothing in this file changes as a result: the pblock is the same range over
# the same cells, and the layer placed inside it with zero SLL crossings.
# The placement rows are evidence/qwen9b/s5/S5_STRUCT.md §3.
# =============================================================================
