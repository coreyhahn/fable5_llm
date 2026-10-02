# fable5_floorplan_a.xdc — VARIANT A: mvchan channel affinity ONLY.
# =============================================================================
# *** CAMPAIGN WINNER (2026-08-24) — this is the canonical floorplan. ***
# WNS -0.004 / WHS 0.000 with AltSpreadLogic_high on build_035's netlist:
# 6 failing endpoints (all vendor-IP async reset recovery), ZERO custom-RTL
# endpoints, all six clocks meeting, hold clean, W8 xline cone positive on all
# four channels. Roll: synth/out_build_035_fp2a_AltSpreadLogic_high.
# The key result is what is ABSENT: there is deliberately NO layer_0 pblock.
# Constraining layer_0 in any form cost ~1 ns (TIMING_035.md §11.7, variants
# B and C). Give the placer the four channel anchors and let it solve layer_0.
# (This banner is a comment-only edit made AFTER the roll; no constraint line
# was touched.)
# =============================================================================
# Isolates the engine-relocation effect with layer_0 left entirely free.
# IMPLEMENTATION-ONLY (USED_IN_SYNTHESIS false). No RTL moves, so every frozen
# gate and the R-c W8 sim gate stay valid. FLAT XDC — no foreach
# (Designutils 20-1307). All pblocks SOFT: no CONTAIN_ROUTING, no
# EXCLUDE_PLACEMENT.
#
# SLR geometry, measured from the device (t5_08_slr_census_035.log):
#   SLR0 = CLOCKREGION_X0Y0 ..X5Y4    SLR1 = X0Y5..X5Y9    SLR2 = X0Y10..X5Y14
#   each: 49,260 CLB / 2,280 DSP48E2 / 320 URAM288
# MIG anchors (fixed by IO banks): ddr4_0 SLR0, ddr4_1 SLR1, ddr4_2 SLR1,
#   ddr4_3 SLR2.
# NEVER pblocked: xdma_0/PCIe/GTs (fixed sites), the ddr4_* MIGs,
#   layer_chan's memory level (348 URAM > one SLR's 320, so it MUST straddle).

# ---- mvchan channel affinity: each engine in the SLR of its own MIG --------
create_pblock pb_mvchan_0
add_cells_to_pblock pb_mvchan_0 [get_cells bd_i/mvchan_0]
resize_pblock pb_mvchan_0 -add {CLOCKREGION_X0Y0:CLOCKREGION_X5Y4}

create_pblock pb_mvchan_1
add_cells_to_pblock pb_mvchan_1 [get_cells bd_i/mvchan_1]
resize_pblock pb_mvchan_1 -add {CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}

create_pblock pb_mvchan_2
add_cells_to_pblock pb_mvchan_2 [get_cells bd_i/mvchan_2]
resize_pblock pb_mvchan_2 -add {CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}

create_pblock pb_mvchan_3
add_cells_to_pblock pb_mvchan_3 [get_cells bd_i/mvchan_3]
resize_pblock pb_mvchan_3 -add {CLOCKREGION_X0Y10:CLOCKREGION_X5Y14}
