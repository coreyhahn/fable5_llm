# fable5_floorplan_9b_dngrpcr.xdc - 9B FLOORPLAN CANDIDATE 2'cr (G5a fix
# round 1, controller ruling R-B).  THE BRIEF'S CLOCK-REGION-GRANULAR VARIANT.
# =============================================================================
# ADDRESSING FORM: **OOC**.  Written for `synth/exp_uram/scripts/exp_ooc.tcl`,
# where `layer_chan` is the TOP module and there is no `bd_i/` hierarchy.  The
# Task-14 in-context form prefixes every pattern with `bd_i/layer_0/`.
#
# IMPLEMENTATION-ONLY: `read_xdc` AFTER synth_design and BEFORE opt_design, the
# non-project equivalent of `synth/scripts/full_impl.tcl:21-30`.  No RTL moves.
# FLAT XDC - no foreach (Designutils 20-1307).  ALL PBLOCKS SOFT in
# `synth/constraints/fable5_floorplan_a.xdc`'s sense: no CONTAIN_ROUTING and no
# EXCLUDE_PLACEMENT, so non-member cells may still be placed inside the ranges.
#
# `?` is the single-character wildcard of Vivado's -filter glob and is how a
# literal `[` or `]` is matched: `*g_grp?0?.` means `...g_grp[0].`.
#
# Device geometry, MEASURED (`evidence/qwen9b/g5/002_dev_geom_census.log`):
#   SLR0 = CLOCKREGION_X0Y0..X5Y4  SLR1 = X0Y5..X5Y9  SLR2 = X0Y10..X5Y14
#   each: 320 URAM288 / 2,280 DSP48E2 / 720 RAMBFIFO36 / 49,260 SLICE
#   URAM288 sites exist ONLY in CLOCKREGION columns X1..X4, 16 per region.
# NEVER pblocked (standing rule): xdma_0/PCIe/GTs, the ddr4_* MIGs.  Neither
# exists in OOC; both are named so the Task-14 derivation cannot forget them.
# =============================================================================

# WHAT THIS FILE TESTS.  The brief's Step 2 asks for a pblock "pinning each
# per-group fan-out register set into the CLOCK REGION of the banks it drives".
# Round 1 shipped `fable5_floorplan_9b_dngrp.xdc` (2'), whose ranges are
# SLR-WIDE, and `_dnbank.xdc` (3'), whose 24 pblocks share only three SLR-wide
# ranges - so the clock-region-granular constraint the brief names was never
# tested.  This file is it, and it is a RANGE-ONLY change from 2': the member
# sets are the same, split into two pblocks so the two ranges can differ.
#
# THE RANGES, taken from `evidence/qwen9b/g5/g5_v2_uram_slr_census.rpt` (the
# per-DN-group URAM clock-region census 2' produced):
#   g_grp[0] URAM CR: X1Y0..Y4  X2Y0..Y2  X3Y0..Y3  X4Y0..Y4   -> all of SLR0's
#   g_grp[1] URAM CR: X1Y5..Y9  X2Y5..Y9  X3Y5..Y9  X4Y5..Y9      URAM columns
#   g_grp[2] URAM CR: X1Y10..Y14 X2Y12..Y14 X3Y11..Y14 X4Y10..Y14
# Every group's banks occupy the URAM columns X1..X4 across all five clock-
# region ROWS of its SLR, so "the clock regions of its banks" is
# `CLOCKREGION_X1Y<5N>:X4Y<5N+4>` - strictly tighter than 2''s
# `X0Y<5N>:X5Y<5N+4>`, which also offered the URAM-free columns X0 and X5.
#
# AND THE FAN-OUT REGISTERS GO TIGHTER STILL, which is the actual experiment:
# they are pinned to the CENTRE clock-region ROW of their group's URAM columns
# (`X1Y<5N+2>:X4Y<5N+2>`), so a fan-out register is at most two clock-region
# rows from any bank it drives instead of up to four.  2''s worst DN write path
# was already intra-SLR (`SLR2 -> SLR2`) and still spent 3.882 of 4.053 ns in
# route, which is a WITHIN-SLR haul - exactly what a row constraint attacks.
#
# CAPACITY CHECK.  Banks: 232 URAM288 into X1..X4 of one SLR = 320 sites, 72.5 %.
# Fan-out: the pinned set is `ra_p`/`wa_p`/`wd_p`/`w_p`/`bs_p`_reg[1][*] =
# 12 + 12 + 2048 + 1 + 5 = 2,078 flip-flops into four clock regions
# (X1..X4 of one row) = 4 x 1,642 SLICE = ~52,500 flip-flops.  `g_lmux` (8,192
# cells) stays with the banks, in the wider range.  No DSP48E2 and no block RAM
# is pinned by this file.
#
# `g_lmux` IS pinned, exactly as 2' pins it (R-B allows either, stated): it
# holds the group's local read mux and its first return register `rq_p_reg[0]`
# (`rtl/layer_chan.sv:640-643`), which belong with the banks.

# ---- g_grp[0]: banks + local read mux -> SLR0's URAM columns
create_pblock pb_dn_grp0
add_cells_to_pblock pb_dn_grp0 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?0?.g_dn* || NAME =~ *g_grp?0?.g_lmux*}]
resize_pblock pb_dn_grp0 -add {CLOCKREGION_X1Y0:CLOCKREGION_X4Y4}
# ---- g_grp[0]: the LAST fan-out stage -> the CENTRE clock-region row of those columns
create_pblock pb_dn_fo0
add_cells_to_pblock pb_dn_fo0 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?0?.ra_p_reg?1?* || NAME =~ *g_grp?0?.wa_p_reg?1?* || NAME =~ *g_grp?0?.wd_p_reg?1?* || NAME =~ *g_grp?0?.w_p_reg?1?* || NAME =~ *g_grp?0?.bs_p_reg?1?*}]
resize_pblock pb_dn_fo0 -add {CLOCKREGION_X1Y2:CLOCKREGION_X4Y2}

# ---- g_grp[1] -> SLR1's URAM columns, fan-out to its centre row
create_pblock pb_dn_grp1
add_cells_to_pblock pb_dn_grp1 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?1?.g_dn* || NAME =~ *g_grp?1?.g_lmux*}]
resize_pblock pb_dn_grp1 -add {CLOCKREGION_X1Y5:CLOCKREGION_X4Y9}
create_pblock pb_dn_fo1
add_cells_to_pblock pb_dn_fo1 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?1?.ra_p_reg?1?* || NAME =~ *g_grp?1?.wa_p_reg?1?* || NAME =~ *g_grp?1?.wd_p_reg?1?* || NAME =~ *g_grp?1?.w_p_reg?1?* || NAME =~ *g_grp?1?.bs_p_reg?1?*}]
resize_pblock pb_dn_fo1 -add {CLOCKREGION_X1Y7:CLOCKREGION_X4Y7}

# ---- g_grp[2] -> SLR2's URAM columns, fan-out to its centre row
create_pblock pb_dn_grp2
add_cells_to_pblock pb_dn_grp2 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?2?.g_dn* || NAME =~ *g_grp?2?.g_lmux*}]
resize_pblock pb_dn_grp2 -add {CLOCKREGION_X1Y10:CLOCKREGION_X4Y14}
create_pblock pb_dn_fo2
add_cells_to_pblock pb_dn_fo2 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?2?.ra_p_reg?1?* || NAME =~ *g_grp?2?.wa_p_reg?1?* || NAME =~ *g_grp?2?.wd_p_reg?1?* || NAME =~ *g_grp?2?.w_p_reg?1?* || NAME =~ *g_grp?2?.bs_p_reg?1?*}]
resize_pblock pb_dn_fo2 -add {CLOCKREGION_X1Y12:CLOCKREGION_X4Y12}

# =============================================================================
# SUPERSEDED 2026-09-04 (state spill) — DO NOT USE ON THE 9B DESIGN.
# Every cell pattern above names the G3.4 928-URAM288 DN/KV BANK ARRAY — its
# banks (`g_dn[*]`), its pipeline groups (`g_grp[*]`), its per-group fan-out
# registers (`*_p_reg`), its conv bank array (`g_cv[*]`).  S2 moved the layer
# state to DDR behind `state_dma` and left TWO CACHE SLOTS per kind, 182
# URAM288 in all (docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md
# §3; measured by S5, evidence/qwen9b/s5/S5_STRUCT.md).  Those patterns now
# match ZERO cells, which Vivado reports only as a CRITICAL WARNING — i.e.
# this file would silently constrain NOTHING while looking like it worked.
# The replacement is synth/constraints/fable5_floorplan_9b_1slr.xdc (S5).
#
# The files stay in the tree, unedited above this line, because
# evidence/qwen9b/g5/G5A_FLOORPLAN.md is a measurement OF THEM: its eleven
# placement rows and its §4.4 family tables are only readable beside the
# constraint text that produced them.
#
# THIS BANNER IS COMMENT-ONLY and sits at the END of the file so that every
# citation into it keeps its line number (G5A_FLOORPLAN.md:316 cites
# fable5_floorplan_9b_dngrp.xdc:78).  No constraint line was touched — the
# same kind of after-the-fact banner fable5_floorplan_a.xdc:11-12 records.
# CONSEQUENCE TO DECLARE: evidence/qwen9b/g5/g5_bytelock.sh compares four of
# these eight files (dngrp, dnbank, dnslr, layer0) against 5ee5f0e and will
# now print DIFFERS for those four.  Its verdict is already committed in
# evidence/qwen9b/g5/006_bytelock_vehicle.log; the whole difference is these
# comment lines.
# =============================================================================
