# fable5_floorplan_c.xdc — VARIANT C: layer compute cluster ONLY.
# Isolates the layer_0 coherence effect with the mvchans left entirely free.
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

# ---- layer_0 compute cluster: u_dn AND u_attn TOGETHER, in SLR2 -----------
# Iteration 1 pblocked u_dn ALONE to SLR2 and the placer answered by evicting
# u_attn (37,190 LUT, 526 DSP) from SLR2 into SLR1 — turning a pair that had
# been partly co-resident into one that is 100% split. Every u_dn<->u_attn
# connection then crossed an SLL. These two are 85% of layer_0's LUTs and are
# tightly coupled; they must be constrained as ONE cluster or not at all.
create_pblock pb_layer_compute
add_cells_to_pblock pb_layer_compute [get_cells bd_i/layer_0/inst/u_core/u_dn]
add_cells_to_pblock pb_layer_compute [get_cells bd_i/layer_0/inst/u_core/u_attn]
resize_pblock pb_layer_compute -add {CLOCKREGION_X0Y10:CLOCKREGION_X5Y14}
