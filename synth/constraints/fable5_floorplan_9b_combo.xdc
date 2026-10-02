# fable5_floorplan_9b_combo.xdc - 9B FLOORPLAN CANDIDATE 5'cr (G5a fix
# round 1).  5''s KV floorplan AND 2'cr's clock-region DN pins, together.
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

# WHAT THIS FILE TESTS.  G5a round 1 concluded that "the KV array must scatter
# across all three SLRs no matter how it is floorplanned".  The review refuted
# the arithmetic: it holds only for an EVEN 232-per-SLR DN split, and the
# unconstrained 1'a run put the KV array in TWO SLRs by itself
# (`evidence/qwen9b/g5/g5_v1a_uram_slr_census.rpt`: `KV_CACHE : SLR0=200
# SLR1=32`).  So this file MEASURES it instead of asserting it.
#
# THE PARTITION, and it is arithmetic, not preference.  KV = 8 banks x 29 = 232
# URAM288; a DN bank is 29; an SLR holds 320.  Putting the whole KV array in one
# SLR leaves 88 there = 3 DN banks, so the 24 DN banks split 11 / 3 / 10:
#   SLR0  g_grp[0] banks 0-7 (232) + g_grp[1] banks 0-2 (87)          = 319
#   SLR1  THE KV ARRAY (232)        + g_grp[1] banks 3-5 (87)          = 319
#   SLR2  g_grp[1] banks 6-7 (58)   + g_grp[2] banks 0-7 (232)         = 290
# 319 + 319 + 290 = 928, every SLR <= 320.  KV goes in SLR1, the MIDDLE SLR,
# because that is where the placer already puts the compute that reads it
# (2' per-SLR: CLB 37.6 %, DSP 65.4 %, BRAM 69.2 % in SLR1) - so the KV read
# into `u_attn`'s DSP lanes gets shorter at the same time as the KV write.
#
# WHICH GROUPS STRADDLE (the ruling asks for this explicitly): `g_grp[0]` is
# WHOLE in SLR0 and `g_grp[2]` is WHOLE in SLR2, both keeping 2''s
# co-location.  **`g_grp[1]` straddles all three SLRs, 3 / 3 / 2 banks.**  Its
# fan-out registers and `g_lmux` are pinned to SLR1, the middle of its own
# span.  That is the price of the KV floorplan and it is part of what is being
# measured: five of the 24 DN banks now have a cross-SLR write path.
#
# CAPACITY CHECK: URAM288 319 / 319 / 290 of 320.  The KV pblock also carries
# the `emem` exp memories (16 RAMBFIFO36) into SLR1, where 2' already placed
# 498 of 720 tiles - 514 of 720, still clear.  No DSP48E2 is pinned by any
# pblock here, so the 1,836 DSPs stay free.
#
# THE KV MEMBER SET, taken from a probe of 2''s placed netlist rather than from
# the RTL identifiers (`evidence/qwen9b/g5/013_kv_register_probe.log`): the
# write-control sources over the 40 worst KV-write paths are `kv_layer_r_reg[*]`
# (94 cells - Vivado replicated it), `kv_we_reg` and its `_replica_*` copies.
# `at_kvdata_reg` does NOT exist in the placed netlist and is not pinned.


# WHY THIS FILE EXISTS.  Fix round 1 ran two constraints that fix DIFFERENT
# path families, and each left the other family binding:
#   2'cr (clock-region DN fan-out pins)  DN write -0.001  KV write -0.368  WNS -0.554
#   5'  (KV array into one SLR)          DN write -0.525  KV write +0.315  WNS -0.663
# Neither is a superset of the other, and nothing about them conflicts: 2'cr
# constrains DN registers and banks in X/Y, 5' constrains the KV array and the
# DN bank-to-SLR assignment.  This file is the union, so it is a MEASUREMENT of
# whether the two gains compose or trade against each other.
#
# It is 5''s partition (the 11 / 3 / 10 DN split that makes room for the whole
# KV array in SLR1) with 2'cr's TWO refinements layered on:
#   (i)  every DN bank pblock is narrowed from the full SLR to the SLR's URAM
#        CLOCKREGION columns X1..X4, and
#   (ii) every group's LAST fan-out stage is pinned to the CENTRE clock-region
#        ROW of its own span instead of anywhere in the SLR.
# `g_grp[1]` still straddles all three SLRs (3 / 3 / 2 banks) and its fan-out
# registers still go to SLR1's centre row, the middle of its own span.

# ---- pb_kv: the whole KV array + its write-control and read-return registers -> SLR1
create_pblock pb_kv
add_cells_to_pblock pb_kv [get_cells -quiet -hierarchical -filter {NAME =~ *g_kv* || NAME =~ kv_layer_r_reg* || NAME =~ kv_we_reg* || NAME =~ kv_waddr_reg* || NAME =~ kv_wrow_reg* || NAME =~ kv_wexp_reg* || NAME =~ at_kvexp_reg*}]
resize_pblock pb_kv -add {CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}

# ---- g_grp[0]: WHOLE in SLR0.  Banks + local mux to the URAM columns; the
# ---- last fan-out stage to the CENTRE clock-region row of those columns.
create_pblock pb_dn_grp0
add_cells_to_pblock pb_dn_grp0 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?0?.g_dn* || NAME =~ *g_grp?0?.g_lmux*}]
resize_pblock pb_dn_grp0 -add {CLOCKREGION_X1Y0:CLOCKREGION_X4Y4}
create_pblock pb_dn_fo0
add_cells_to_pblock pb_dn_fo0 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?0?.ra_p_reg?1?* || NAME =~ *g_grp?0?.wa_p_reg?1?* || NAME =~ *g_grp?0?.wd_p_reg?1?* || NAME =~ *g_grp?0?.w_p_reg?1?* || NAME =~ *g_grp?0?.bs_p_reg?1?*}]
resize_pblock pb_dn_fo0 -add {CLOCKREGION_X1Y2:CLOCKREGION_X4Y2}

# ---- g_grp[2]: WHOLE in SLR2, same treatment
create_pblock pb_dn_grp2
add_cells_to_pblock pb_dn_grp2 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?2?.g_dn* || NAME =~ *g_grp?2?.g_lmux*}]
resize_pblock pb_dn_grp2 -add {CLOCKREGION_X1Y10:CLOCKREGION_X4Y14}
create_pblock pb_dn_fo2
add_cells_to_pblock pb_dn_fo2 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?2?.ra_p_reg?1?* || NAME =~ *g_grp?2?.wa_p_reg?1?* || NAME =~ *g_grp?2?.wd_p_reg?1?* || NAME =~ *g_grp?2?.w_p_reg?1?* || NAME =~ *g_grp?2?.bs_p_reg?1?*}]
resize_pblock pb_dn_fo2 -add {CLOCKREGION_X1Y12:CLOCKREGION_X4Y12}

# ---- g_grp[1]: STRADDLES 3 / 3 / 2, banks pinned individually to their SLR's
# ---- URAM columns; local mux and last fan-out stage to SLR1's centre row.
create_pblock pb_dn_grp1_slr0
add_cells_to_pblock pb_dn_grp1_slr0 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?1?.g_dn?0?.* || NAME =~ *g_grp?1?.g_dn?1?.* || NAME =~ *g_grp?1?.g_dn?2?.*}]
resize_pblock pb_dn_grp1_slr0 -add {CLOCKREGION_X1Y0:CLOCKREGION_X4Y4}

create_pblock pb_dn_grp1_slr1
add_cells_to_pblock pb_dn_grp1_slr1 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?1?.g_dn?3?.* || NAME =~ *g_grp?1?.g_dn?4?.* || NAME =~ *g_grp?1?.g_dn?5?.*}]
resize_pblock pb_dn_grp1_slr1 -add {CLOCKREGION_X1Y5:CLOCKREGION_X4Y9}

create_pblock pb_dn_grp1_slr2
add_cells_to_pblock pb_dn_grp1_slr2 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?1?.g_dn?6?.* || NAME =~ *g_grp?1?.g_dn?7?.*}]
resize_pblock pb_dn_grp1_slr2 -add {CLOCKREGION_X1Y10:CLOCKREGION_X4Y14}

create_pblock pb_dn_grp1_fanout
add_cells_to_pblock pb_dn_grp1_fanout [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?1?.g_lmux* || NAME =~ *g_grp?1?.ra_p_reg?1?* || NAME =~ *g_grp?1?.wa_p_reg?1?* || NAME =~ *g_grp?1?.wd_p_reg?1?* || NAME =~ *g_grp?1?.w_p_reg?1?* || NAME =~ *g_grp?1?.bs_p_reg?1?*}]
resize_pblock pb_dn_grp1_fanout -add {CLOCKREGION_X1Y7:CLOCKREGION_X4Y7}

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
