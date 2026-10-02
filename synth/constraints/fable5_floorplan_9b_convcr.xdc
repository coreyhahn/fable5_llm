# fable5_floorplan_9b_convcr.xdc - 9B FLOORPLAN CANDIDATE 6' (G5a fix round 2,
# controller ruling R-C).  2'cr PLUS THE CONV BRAM BANKS.
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


# WHAT THIS FILE ADDS TO 2'cr.  The technique has now closed two path families:
# the DN write fan-out (-1.141 -> -0.001, 2'cr) and the KV write fan-out
# (-0.831 -> +0.315 MET, 5').  Under 2'cr the WNS is owned by a THIRD family
# with the same signature - the conv BRAM write, -0.554, 3 logic levels,
# 93.3 % route, SLR1 -> SLR2, worst path
#   st_reg[3]/C -> g_cv[4].wm_reg_bram_7/CASDOMUXEN_B
# (evidence/qwen9b/g5/g5_v2cr_family_run.log).  R-C asks whether the third
# family yields to the same technique.  This file is 2'cr byte-for-byte plus
# two pblocks, so the comparison isolates the conv constraint.
#
# THE CONV MEMBER SET, probed off 2'cr's placed netlist rather than guessed
# (evidence/qwen9b/g5/020_conv_register_probe.log):
#   g_cv[*]                624 BRAM cells (RAMB36 + RAMB18), the 24 conv banks
#   st_reg[*]               24 cells - the CONV FSM state register, the source
#                           of the worst path
#   dn_layer_r_reg[*]       41 cells - the bank select
# `rstn_i_reg_replica` also appears as a source; it is a reset replica the
# placer made and is deliberately NOT pinned (pinning a reset replica fights
# the tool that created it).
#
# WHERE.  In 2'cr the conv banks are split SLR1=384 / SLR2=240, which is what
# the SLR1 -> SLR2 worst path is.  They go to SLR1, with the two control
# registers pinned to SLR1's CENTRE clock-region row - the same shape as the DN
# pins above (banks in a region, control registers in the middle of it).  SLR1
# is the right SLR rather than SLR2 because that is where the placer already
# puts the compute that reads them (2'cr: DSP 166 / 1504 / 166).
#
# CAPACITY CHECK BEFORE CONSTRAINING (the standing rule).  Per SLR there are
# 720 RAMBFIFO36 and 4,320 RAMB18 sites; the whole design uses 674 RAMB36 + 32
# RAMB18 = ~690 tiles and the conv banks are 624 of those cells.  Confining
# them to SLR1 is ~616 of 720 tiles (86 %), leaving the KV `emem` (16 cells)
# and the scratchpad (62 cells) free to go elsewhere - they are NOT pinned.
# BRAM sites per CLOCKREGION COLUMN, measured
# (evidence/qwen9b/g5/002_dev_geom_census.log, summed over 15 rows):
#   X0 540   X1 180   X2 540   X3 180   X4 360   X5 360
# so SLR1's five rows carry 720 across all six columns, and no column is
# excluded here - the conv pblock takes the whole SLR width.
# This file pins NO DSP48E2 and NO URAM288 beyond what 2'cr already pins.

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

# ---- pb_conv: the 24 conv BRAM banks -> SLR1
create_pblock pb_conv
add_cells_to_pblock pb_conv [get_cells -quiet -hierarchical -filter {NAME =~ *g_cv*}]
resize_pblock pb_conv -add {CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}

# ---- pb_conv_ctl: the conv write-control registers -> SLR1's CENTRE row
create_pblock pb_conv_ctl
add_cells_to_pblock pb_conv_ctl [get_cells -quiet -hierarchical -filter {NAME =~ st_reg* || NAME =~ dn_layer_r_reg*}]
resize_pblock pb_conv_ctl -add {CLOCKREGION_X0Y7:CLOCKREGION_X5Y7}

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
