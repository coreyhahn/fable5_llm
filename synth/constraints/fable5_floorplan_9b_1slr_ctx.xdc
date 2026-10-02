# fable5_floorplan_9b_1slr_ctx.xdc — THE IN-CONTEXT FORM of the state-spill
# floorplan: the whole 9B layer in ONE SLR, written for the FULL stage-1 design
# (Task 14 / G5b of docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md).
# =============================================================================
# WHAT THIS FILE IS.  synth/constraints/fable5_floorplan_9b_1slr.xdc is the OOC
# original: S5 placed `layer_chan` alone on the die with it and both constrained
# runs MET post-place (WNS +0.030 Default / +0.034 AltSpreadLogic_medium, TNS
# 0.000, zero failing setup endpoints, 0 SLLs — evidence/qwen9b/s5/S5_STRUCT.md
# section 3.3).  That file is addressed for the OOC harness, where `layer_chan`
# is the TOP module: its one `add_cells_to_pblock` line uses `[get_cells *]`,
# meaning "every top-level cell of layer_chan".
#
# `get_cells *` is exactly the pattern that does NOT prefix-rewrite.  In the
# in-context design `*` at the top level means the whole block design — xdma_0,
# the four MIGs, the four mvchans, seq_0 — which would be a catastrophically
# different constraint, and a silent one.  So the OOC file states its own
# in-context rewrite verbatim in its header, and THIS FILE IS THAT REWRITE:
# the single hierarchical cell `bd_i/layer_0`, the same CLOCKREGION range, the
# same softness, one pblock and nothing else.
#
# THE OOC FILE IS NOT EDITED.  It is byte-locked by
# evidence/qwen9b/g5/g5_bytelock.sh, and it is the artifact S5's gate doc cites.
# synth/constraints/fable5_floorplan_a.xdc — the 2B campaign winner, whose four
# soft mvchan pblocks this build also needs — is likewise byte-untouched.
# synth/scripts/full_impl.tcl takes argv 2 onward as an ordered LIST of
# implementation-only XDCs (synth/scripts/full_impl.tcl:11-16) precisely so the
# two geometries are LAYERED rather than merged into an edited copy.  Pass both,
# in order:
#
#   XDC="<abs>/fable5_floorplan_a.xdc <abs>/fable5_floorplan_9b_1slr_ctx.xdc"
#
# IMPLEMENTATION-ONLY.  full_impl.tcl adds each file with
# `add_files -fileset constrs_1` + `USED_IN_SYNTHESIS false`
# (synth/scripts/full_impl.tcl:21-30), so no RTL moves and every frozen gate
# stays valid.
#
# FLAT XDC — no foreach (Designutils 20-1307), same as fable5_floorplan_a.xdc
# and the OOC original.
#
# SOFT, in fable5_floorplan_a.xdc's sense: no CONTAIN_ROUTING and no
# EXCLUDE_PLACEMENT.  The placer may still put non-member cells inside the range
# and may spill a member if it must.  The per-SLR census
# (synth/scripts/slr_census.tcl) and report_utilization's SLR section, not the
# pblock's existence, are what say whether the layer actually landed in one SLR.
#
# SLR geometry, MEASURED off the part (evidence/qwen9b/g5/002_dev_geom_census.log):
#   SLR0 = CLOCKREGION_X0Y0..X5Y4   SLR1 = X0Y5..X5Y9   SLR2 = X0Y10..X5Y14
#   each: 320 URAM288 / 2,280 DSP48E2 / 720 RAMBFIFO36 / 49,260 SLICE
#
# WHY SLR1: the MIG anchors are fixed by their IO banks — ddr4_0 in SLR0,
# ddr4_1 and ddr4_2 in SLR1, ddr4_3 in SLR2
# (synth/constraints/fable5_floorplan_a.xdc:20-24).  The layer's `m_axis`
# state-DMA master reaches DDR through the central SmartConnect, so the SLR
# carrying two of the four MIGs shortens that path, and it is the middle SLR —
# every other block is at most one crossing away.
#
# CAPACITY, MEASURED OOC on the shipped 182-URAM netlist
# (evidence/qwen9b/s5/S5_STRUCT.md section 3.4), against ONE SLR's budget:
#   URAM288      182 of   320   56.9 %
#   DSP48E2    1,838 of 2,280   80.6 %   <- the TIGHT resource
#   Block RAM     81 of   720   11.3 %
#   CLB LUT  109,357 of ~394 K  27.8 %
# In context the mvchans, seq_0, XDMA and the MIGs compete for the same SLR1
# sites that fable5_floorplan_a.xdc already sends mvchan_1 and mvchan_2 into,
# so the DSP row is the one to watch and the in-context census is the answer.
#
# NEVER PBLOCKED (standing rule): xdma_0/PCIe/GTs (fixed sites) and the ddr4_*
# MIGs.  This pblock holds `bd_i/layer_0` ONLY and must never be widened to
# `bd_i`.
#
# THE 2B CAMPAIGN'S WARNING, deliberately re-tested here: constraining
# `layer_0` in ANY form cost about 1 ns on the 2B design
# (synth/constraints/fable5_floorplan_a.xdc:8-10, evidence/qwen2b/rc/TIMING_035.md
# section 11.7), and fable5_floorplan_a.xdc's key result is the DELIBERATE
# ABSENCE of a layer_0 pblock.  The 9B state-spill layer is a different design —
# 182 URAM instead of 928, no banked array to straddle — so the question is
# reopened, and build_036's UNCONSTRAINED first roll is the baseline that
# answers it.  If the unconstrained roll is better, this file is not the answer.
# =============================================================================

# ---- pb_layer_1slr: the whole 9B layer -> SLR1
create_pblock pb_layer_1slr
add_cells_to_pblock pb_layer_1slr [get_cells bd_i/layer_0]
resize_pblock pb_layer_1slr -add {CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}
