# fable5_floorplan.xdc — SLR floorplan for the W8 (V5) netlist.
# =============================================================================
# SUPERSEDED 2026-08-24 — THIS FLOORPLAN LOST. DO NOT USE.
# It scored WNS -0.624 (vs -0.136 with no floorplan at all). Its defect is
# diagnosed in evidence/qwen2b/rc/TIMING_035.md §11.5: pinning u_dn alone into
# SLR2 made the placer evict u_attn out of SLR2, splitting a tightly-coupled
# pair across an SLL boundary.
# THE WINNER IS fable5_floorplan_a.xdc — mvchan channel affinity ONLY, no
# layer_0 pblock at all (WNS -0.004). Constraining layer_0 in ANY form was
# catastrophic: see §11.7's A/B/C decomposition (-1.078 and -1.148).
# Retained only so the iteration-1 rolls stay reproducible.
# (This banner is a comment-only edit made AFTER the rolls; no constraint
# line was touched.)
# =============================================================================
# IMPLEMENTATION-ONLY (USED_IN_SYNTHESIS false). No RTL is affected, so every
# frozen sim gate and the R-c W8 gate stay valid.
#
# FLAT XDC — no foreach. (Designutils 20-1307 rejects foreach in .xdc; see
# layer_mcp.xdc's header for the same hard-won note.)
#
# ============================================================================
# WHY THIS FILE EXISTS
# ============================================================================
# build_035 (W8 everywhere) missed timing at WNS -0.136 with 2,773 failing
# endpoints. evidence/qwen2b/rc/TIMING_035.md §8c established that the cause is
# not logic depth — 93-98% of the critical delay is routing, and the W8 cone
# itself got FASTER and one level SHALLOWER (§7) — but SLR spread: the W8 lane
# array added +21,111 LUTs, SLR1 could not absorb them, and the placer spread
# the design outward until SLL crossings rose 23% (4,090 -> 5,032).
#
# The design has never had a single pblock. This is the first.
#
# ============================================================================
# MEASURED FACTS THIS FLOORPLAN IS BUILT ON  (synth/scripts/slr_census.tcl,
# run on out_build_035_full_AltSpreadLogic_high; log committed as
# evidence/qwen2b/rc/t5_08_slr_census_035.log)
# ============================================================================
# SLR geometry, verified from the device (not assumed from part folklore):
#   SLR0 = CLOCKREGION_X0Y0 .. X5Y4    (SLICE Y   0..299)
#   SLR1 = CLOCKREGION_X0Y5 .. X5Y9    (SLICE Y 300..599)
#   SLR2 = CLOCKREGION_X0Y10.. X5Y14   (SLICE Y 600..899)
# Per-SLR ceilings: 24,600 SLICEL + 24,660 SLICEM = 49,260 CLB;
#                   2,280 DSP48E2; 320 URAM288; 720 BRAM tiles.
#
# MIG anchors — FIXED by the memory-interface IO banks, immovable:
#   ddr4_0  anchor clock regions X2Y1..X2Y3    -> SLR0
#   ddr4_1  anchor clock regions X4Y5..X4Y8    -> SLR1
#   ddr4_2  anchor clock regions X2Y7..X2Y9    -> SLR1
#   ddr4_3  anchor clock regions X4Y11..X4Y13  -> SLR2
#
# Where build_035 actually put things (SLICE-cell distribution):
#   mvchan_0  SLR0 100%   <- matches ddr4_0. correct.
#   mvchan_1  SLR1 100%   <- matches ddr4_1. correct.
#   mvchan_2  SLR1 100%   <- matches ddr4_2. correct.
#   mvchan_3  SLR1 100%   <- ddr4_3 IS IN SLR2. WRONG SLR. **
#   layer_0   SLR1  30% / SLR2 70%
#     u_dn    SLR1  74% / SLR2 26%   <- split across the SLR boundary **
#     u_attn  SLR2 100%              <- already coherent
#     u_topk  SLR2 100%   u_alu SLR2 100%
#   seq_0     SLR1 100%   xdma_0 SLR1 100%
#   smc_ch3   SLR1  60% / SLR2 40%   <- straddles, bridging the mvchan_3 split
#   SLR CLB occupancy: SLR0 17.89%, SLR1 73.90%, SLR2 33.54%
#
# ============================================================================
# WHAT THE PER-CHANNEL EVIDENCE ACTUALLY SAYS
# ============================================================================
# A first pass at this file blamed clock-SLR remoteness. Censusing build_034's
# placement REFUTED that and the rationale was rewritten: on build_034 ALL FOUR
# mvchans sat in SLR1, mvchan_3 included, so nothing about mvchan_3's placement
# changed between the two builds. (Recorded because TIMING.md §7 finding 6 —
# "re-census the shipped roll, never a predecessor" — exists precisely because
# this project has shipped a wrong causal claim before.)
#
# The real correlation, all four channels of build_035 side by side:
#
#   ch  mvchan  MIG   co-located?  SLR load   xline CE worst  domain  failEP
#   --  ------  ----  -----------  ---------  --------------  ------  ------
#   0   SLR0    SLR0  yes          17.89%       +0.092        +0.006      0
#   1   SLR1    SLR1  yes          73.90%       -0.080        -0.103    348
#   2   SLR1    SLR1  yes          73.90%       (>worst-1000)  0.000      0
#   3   SLR1    SLR2  NO           73.90%       -0.087        -0.087    649
#
# Read it in that order and it is unambiguous:
#   * CONGESTION IS THE PRIMARY AXIS. The only channel with real margin is the
#     one in the nearly empty SLR (+0.092, the sole positive xline CE slack in
#     the design). All three channels sharing the 73.90%-full SLR1 sit at or
#     below zero, co-located or not.
#   * REMOTENESS IS A SECONDARY AGGRAVATOR. Among the three crowded channels,
#     the one that is ALSO remote from its MIG (ch3) carries 649 failing
#     endpoints against ch1's 348 and ch2's zero, and drags smc_ch3 into a
#     60/40 straddle with another 161. Its worst W8 path has clock delays of
#     5.051/5.077 ns and skew -0.281, against 3.369/3.703 and -0.131 for the
#     equivalent path in a co-located channel (build_034's mvchan_2).
#   * And on build_034 — engines 39% smaller — SLR1 held all four mvchans and
#     three of the four channels MET timing. SLR1's capacity was the latent
#     single point of failure all along; W8's +41.5% per channel crossed it.
#
# ============================================================================
# THE TWO MOVES THIS FILE MAKES
# ============================================================================
# (1) mvchan_3 SLR1 -> SLR2. This is the one pblock that relocates an engine.
#     It does BOTH things the evidence asks for at once: it takes a full
#     engine off the congested SLR1, and it lands that engine beside its own
#     MIG and MMCM, which is the one remaining non-co-located channel.
#     mvchan_0/1/2 are pblocked to the SLR they already occupy — that costs
#     nothing today and stops the placer from re-scattering them as pressure
#     shifts under the other constraints.
#
# (2) u_dn split 74/26 across the SLR1/SLR2 boundary -> one SLR.
#     u_dn owns 1,237 of the 2,773 failing endpoints, by far the largest
#     single owner, and is the WNS driver's block. Splitting a block that
#     tightly coupled across an SLL boundary is the worst case for it.
#     SLR2 is the destination, for load balance — see below.
#
# ============================================================================
# WHY u_dn GOES TO SLR2 AND NOT SLR1 (where 74% of it already is)
# ============================================================================
# The goal is to RELIEVE SLR1, which is at 73.90% CLB. Projected CLB
# occupancy (LUT counts scaled at the design's measured 4.93 LUTs/CLB):
#   u_dn -> SLR1 : SLR1 ~70.7%, SLR2 ~35.6%   <- barely relieves anything
#   u_dn -> SLR2 : SLR1 ~52.8%, SLR2 ~53.4%   <- balanced. chosen.
# u_dn is free to move: it holds 43,391 LUTs and 1,280 DSPs but ZERO URAM,
# ZERO BRAM and only 80 LUTRAM, so it has no memory anchor tying it anywhere.
#
# *** DSP CAPACITY CHECK — the house-rule pitfall, checked before writing. ***
# u_dn is DSP-heavy. With u_dn (1,280) in SLR2 alongside u_attn (526) and the
# small layer_0 consumers (u_alu 7, u_vn 9, u_conv 7, u_gate 7, u_recip 4,
# u_rope 2) plus mvchan_3 (2), SLR2 needs ~1,844 of its 2,280 DSP48E2 = 81%.
# That is LEGAL but it is the tightest number in this floorplan and it is the
# thing to watch: if iteration 1 shows DSP-driven congestion in SLR2, the
# fallbacks are (a) let u_attn migrate to SLR1 (it is not pblocked here,
# precisely so it can), or (b) split u_dn's lane array across two SLRs
# deliberately rather than letting the placer do it.
# URAM is the hard limit that CANNOT be satisfied in one SLR: layer_0 needs
# 348 URAM and an SLR has 320, so layer_chan's memory level MUST straddle.
# It is deliberately left unconstrained so the placer can put 320 in SLR2 and
# spill only the remainder — better than build_035's 189/159 split.
#
# ============================================================================
# WHAT IS DELIBERATELY *NOT* PBLOCKED
# ============================================================================
# - xdma_0 / PCIe / GTs. HOUSE RULE: never pblock GT or PCIe blocks — they
#   have fixed physical locations. Measured here: PCIE40E4_X1Y2 in clock
#   region X5Y5 and 8 x GTYE4_CHANNEL in X5Y7/X5Y8, all SLR1. xdma_0 is
#   anchored there by hardware and needs no pblock.
# - ddr4_* MIGs. Anchored by their IO banks; a pblock would add nothing.
# - layer_0's memory level and u_attn. See the URAM note above; u_attn is
#   already 100% coherent in SLR2 and is left free so it can act as the
#   DSP-pressure relief valve.
# - seq_0, smc_ch*, axi_smc. Left free to follow their masters. smc_ch3 in
#   particular should stop straddling once mvchan_3 and ddr4_3 are on the
#   same side.
#
# ALL PBLOCKS HERE ARE SOFT: no CONTAIN_ROUTING, no EXCLUDE_PLACEMENT. They
# constrain where the named cells may be PLACED and nothing else. Tighten only
# if a census says the soft form was not enough.
# ============================================================================

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

# the one that actually moves: ddr4_3 and its MMCM are in SLR2
create_pblock pb_mvchan_3
add_cells_to_pblock pb_mvchan_3 [get_cells bd_i/mvchan_3]
resize_pblock pb_mvchan_3 -add {CLOCKREGION_X0Y10:CLOCKREGION_X5Y14}

# ---- keep the 1,237-endpoint block coherent in one SLR ---------------------
create_pblock pb_layer_dn
add_cells_to_pblock pb_layer_dn [get_cells bd_i/layer_0/inst/u_core/u_dn]
resize_pblock pb_layer_dn -add {CLOCKREGION_X0Y10:CLOCKREGION_X5Y14}
