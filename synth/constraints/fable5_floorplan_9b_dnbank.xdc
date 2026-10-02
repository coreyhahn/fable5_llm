# fable5_floorplan_9b_dnbank.xdc — 9B FLOORPLAN CANDIDATE 3' (per-BANK fan-out) (G5a / Task 13, the OOC floorplan
# experiment).  DERIVED FROM synth/constraints/fable5_floorplan_a.xdc, the 2B
# campaign winner, which the spec calls "the starting point, not the answer";
# its four soft mvchan pblocks and its deliberate ABSENCE of a layer_0 pblock
# are the baseline every variant here is measured against.
# =============================================================================
# ADDRESSING FORM: **OOC**.  This file is written for
# `synth/exp_uram/scripts/exp_ooc.tcl`, where `layer_chan` is the TOP module and
# there is no `bd_i/` hierarchy.  Every cell pattern below is therefore relative
# to layer_chan.  The Task-14 in-context form of the same constraint prefixes
# each pattern with `bd_i/layer_0/`.
#
# IMPLEMENTATION-ONLY: exp_ooc.tcl `read_xdc`s this AFTER synth_design and
# BEFORE opt_design, which is the non-project equivalent of full_impl.tcl's
# `add_files -fileset constrs_1` + `USED_IN_SYNTHESIS false`
# (synth/scripts/full_impl.tcl:21-30).  No RTL moves.
#
# FLAT XDC — no foreach (Designutils 20-1307), same as fable5_floorplan_a.xdc.
# ALL PBLOCKS SOFT, in fable5_floorplan_a.xdc's sense: no CONTAIN_ROUTING and
# no EXCLUDE_PLACEMENT, so non-member cells (the KV array in particular) may
# still be placed inside these ranges.
#
# `?` is the single-character wildcard of Vivado's -filter glob and is how a
# literal `[` or `]` is matched: `*g_grp?0?.` means `...g_grp[0].`.  The cell
# names it targets were MEASURED off the G4b post-synth netlist
# (synth/exp_uram/scripts/probe_names.tcl, evidence/qwen9b/g5/003_probe_names.log),
# not guessed — an earlier revision of this file used a pattern that matched
# ZERO cells, which Vivado reports only as a CRITICAL WARNING.
#
# SLR geometry, MEASURED off the part by synth/exp_uram/scripts/dev_geom_census.tcl
# (evidence/qwen9b/g5/002_dev_geom_census.log), not assumed:
#   SLR0 = CLOCKREGION_X0Y0..X5Y4   SLR1 = X0Y5..X5Y9   SLR2 = X0Y10..X5Y14
#   each: 320 URAM288 / 2,280 DSP48E2 / 720 RAMBFIFO36 / 49,260 SLICE
#   URAM288 sites live ONLY in CLOCKREGION columns X1..X4 (16 per clock region,
#   4 columns x 16 x 15 rows = 960).  X0 and X5 carry no URAM.
#
# CAPACITY CHECK (the standing rule: check DSP and BRAM per SLR BEFORE
# constraining anything):
#   DN state = 24 banks x 29 URAM288 = 696; 8 banks per SLR = 232 of 320 (72.5 %).
#   KV cache = 8 banks x 29 = 232, left UNCONSTRAINED — the 3 x 88 = 264
#     URAM288 these pblocks do not claim is enough for it, and the pblocks are
#     soft so it may also share their ranges.
#   These pblocks hold NO DSP48E2 and NO block RAM, so the 1,836 DSPs and the
#   ~690 BRAM tiles are unconstrained by this file.  (1,836 / 690 are what the
#   SHIPPING rtl/ synthesises - evidence/qwen9b/g5/g5_v1a_util_synth.rpt.  An
#   earlier revision of this header said 1,838 / ~658, which are Track P's
#   numbers for the EXPERIMENT COPY, a different design.)
#
# NEVER pblocked (standing rule): xdma_0/PCIe/GTs (fixed sites), the ddr4_*
# MIGs.  Neither exists in the OOC context; both are named here so the Task-14
# in-context derivation of this file cannot forget them.
# =============================================================================

# WHAT THIS FILE TESTS (brief variant 3'): DN_BPG = 1 gives every bank its own
# fan-out register set, and UNCONSTRAINED that was WORSE than DN_BPG = 8
# (-1.956 vs -1.391; PLACE_EXP.md 3.8, r3pipe2bank_summary.log).  The hypothesis
# is that it is worse ONLY because nothing PLACED the copies: `dont_touch` stops
# synthesis merging them but nothing places them.  This file is the direct test
# — the same co-location as fable5_floorplan_9b_dngrp.xdc at per-bank
# granularity.
# MUST be run with DN_BPG = 1, which makes DN_GRP = 24: one g_grp per bank, and
# the local-mux scope is `g_lmux1` rather than `g_lmux` (rtl/layer_chan.sv:640,
# :644 — the NB > 1 / NB == 1 arms).  The pattern `g_lmux*` below matches
# either, so this file does not depend on which arm the parameter selects.
# Banks 0-7 -> SLR0, 8-15 -> SLR1, 16-23 -> SLR2 (8 banks = 232 URAM288 per SLR,
# the same partition as the DN_BPG = 8 file).

# ---- pb_dn_bank00: DN pipeline group 0 -> SLR0 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank00
add_cells_to_pblock pb_dn_bank00 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?0?.g_dn* || NAME =~ *g_grp?0?.g_lmux* || NAME =~ *g_grp?0?.ra_p_reg?1?* || NAME =~ *g_grp?0?.wa_p_reg?1?* || NAME =~ *g_grp?0?.wd_p_reg?1?* || NAME =~ *g_grp?0?.w_p_reg?1?* || NAME =~ *g_grp?0?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank00 -add {CLOCKREGION_X0Y0:CLOCKREGION_X5Y4}

# ---- pb_dn_bank01: DN pipeline group 1 -> SLR0 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank01
add_cells_to_pblock pb_dn_bank01 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?1?.g_dn* || NAME =~ *g_grp?1?.g_lmux* || NAME =~ *g_grp?1?.ra_p_reg?1?* || NAME =~ *g_grp?1?.wa_p_reg?1?* || NAME =~ *g_grp?1?.wd_p_reg?1?* || NAME =~ *g_grp?1?.w_p_reg?1?* || NAME =~ *g_grp?1?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank01 -add {CLOCKREGION_X0Y0:CLOCKREGION_X5Y4}

# ---- pb_dn_bank02: DN pipeline group 2 -> SLR0 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank02
add_cells_to_pblock pb_dn_bank02 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?2?.g_dn* || NAME =~ *g_grp?2?.g_lmux* || NAME =~ *g_grp?2?.ra_p_reg?1?* || NAME =~ *g_grp?2?.wa_p_reg?1?* || NAME =~ *g_grp?2?.wd_p_reg?1?* || NAME =~ *g_grp?2?.w_p_reg?1?* || NAME =~ *g_grp?2?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank02 -add {CLOCKREGION_X0Y0:CLOCKREGION_X5Y4}

# ---- pb_dn_bank03: DN pipeline group 3 -> SLR0 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank03
add_cells_to_pblock pb_dn_bank03 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?3?.g_dn* || NAME =~ *g_grp?3?.g_lmux* || NAME =~ *g_grp?3?.ra_p_reg?1?* || NAME =~ *g_grp?3?.wa_p_reg?1?* || NAME =~ *g_grp?3?.wd_p_reg?1?* || NAME =~ *g_grp?3?.w_p_reg?1?* || NAME =~ *g_grp?3?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank03 -add {CLOCKREGION_X0Y0:CLOCKREGION_X5Y4}

# ---- pb_dn_bank04: DN pipeline group 4 -> SLR0 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank04
add_cells_to_pblock pb_dn_bank04 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?4?.g_dn* || NAME =~ *g_grp?4?.g_lmux* || NAME =~ *g_grp?4?.ra_p_reg?1?* || NAME =~ *g_grp?4?.wa_p_reg?1?* || NAME =~ *g_grp?4?.wd_p_reg?1?* || NAME =~ *g_grp?4?.w_p_reg?1?* || NAME =~ *g_grp?4?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank04 -add {CLOCKREGION_X0Y0:CLOCKREGION_X5Y4}

# ---- pb_dn_bank05: DN pipeline group 5 -> SLR0 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank05
add_cells_to_pblock pb_dn_bank05 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?5?.g_dn* || NAME =~ *g_grp?5?.g_lmux* || NAME =~ *g_grp?5?.ra_p_reg?1?* || NAME =~ *g_grp?5?.wa_p_reg?1?* || NAME =~ *g_grp?5?.wd_p_reg?1?* || NAME =~ *g_grp?5?.w_p_reg?1?* || NAME =~ *g_grp?5?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank05 -add {CLOCKREGION_X0Y0:CLOCKREGION_X5Y4}

# ---- pb_dn_bank06: DN pipeline group 6 -> SLR0 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank06
add_cells_to_pblock pb_dn_bank06 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?6?.g_dn* || NAME =~ *g_grp?6?.g_lmux* || NAME =~ *g_grp?6?.ra_p_reg?1?* || NAME =~ *g_grp?6?.wa_p_reg?1?* || NAME =~ *g_grp?6?.wd_p_reg?1?* || NAME =~ *g_grp?6?.w_p_reg?1?* || NAME =~ *g_grp?6?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank06 -add {CLOCKREGION_X0Y0:CLOCKREGION_X5Y4}

# ---- pb_dn_bank07: DN pipeline group 7 -> SLR0 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank07
add_cells_to_pblock pb_dn_bank07 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?7?.g_dn* || NAME =~ *g_grp?7?.g_lmux* || NAME =~ *g_grp?7?.ra_p_reg?1?* || NAME =~ *g_grp?7?.wa_p_reg?1?* || NAME =~ *g_grp?7?.wd_p_reg?1?* || NAME =~ *g_grp?7?.w_p_reg?1?* || NAME =~ *g_grp?7?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank07 -add {CLOCKREGION_X0Y0:CLOCKREGION_X5Y4}

# ---- pb_dn_bank08: DN pipeline group 8 -> SLR1 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank08
add_cells_to_pblock pb_dn_bank08 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?8?.g_dn* || NAME =~ *g_grp?8?.g_lmux* || NAME =~ *g_grp?8?.ra_p_reg?1?* || NAME =~ *g_grp?8?.wa_p_reg?1?* || NAME =~ *g_grp?8?.wd_p_reg?1?* || NAME =~ *g_grp?8?.w_p_reg?1?* || NAME =~ *g_grp?8?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank08 -add {CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}

# ---- pb_dn_bank09: DN pipeline group 9 -> SLR1 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank09
add_cells_to_pblock pb_dn_bank09 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?9?.g_dn* || NAME =~ *g_grp?9?.g_lmux* || NAME =~ *g_grp?9?.ra_p_reg?1?* || NAME =~ *g_grp?9?.wa_p_reg?1?* || NAME =~ *g_grp?9?.wd_p_reg?1?* || NAME =~ *g_grp?9?.w_p_reg?1?* || NAME =~ *g_grp?9?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank09 -add {CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}

# ---- pb_dn_bank10: DN pipeline group 10 -> SLR1 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank10
add_cells_to_pblock pb_dn_bank10 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?10?.g_dn* || NAME =~ *g_grp?10?.g_lmux* || NAME =~ *g_grp?10?.ra_p_reg?1?* || NAME =~ *g_grp?10?.wa_p_reg?1?* || NAME =~ *g_grp?10?.wd_p_reg?1?* || NAME =~ *g_grp?10?.w_p_reg?1?* || NAME =~ *g_grp?10?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank10 -add {CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}

# ---- pb_dn_bank11: DN pipeline group 11 -> SLR1 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank11
add_cells_to_pblock pb_dn_bank11 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?11?.g_dn* || NAME =~ *g_grp?11?.g_lmux* || NAME =~ *g_grp?11?.ra_p_reg?1?* || NAME =~ *g_grp?11?.wa_p_reg?1?* || NAME =~ *g_grp?11?.wd_p_reg?1?* || NAME =~ *g_grp?11?.w_p_reg?1?* || NAME =~ *g_grp?11?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank11 -add {CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}

# ---- pb_dn_bank12: DN pipeline group 12 -> SLR1 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank12
add_cells_to_pblock pb_dn_bank12 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?12?.g_dn* || NAME =~ *g_grp?12?.g_lmux* || NAME =~ *g_grp?12?.ra_p_reg?1?* || NAME =~ *g_grp?12?.wa_p_reg?1?* || NAME =~ *g_grp?12?.wd_p_reg?1?* || NAME =~ *g_grp?12?.w_p_reg?1?* || NAME =~ *g_grp?12?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank12 -add {CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}

# ---- pb_dn_bank13: DN pipeline group 13 -> SLR1 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank13
add_cells_to_pblock pb_dn_bank13 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?13?.g_dn* || NAME =~ *g_grp?13?.g_lmux* || NAME =~ *g_grp?13?.ra_p_reg?1?* || NAME =~ *g_grp?13?.wa_p_reg?1?* || NAME =~ *g_grp?13?.wd_p_reg?1?* || NAME =~ *g_grp?13?.w_p_reg?1?* || NAME =~ *g_grp?13?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank13 -add {CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}

# ---- pb_dn_bank14: DN pipeline group 14 -> SLR1 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank14
add_cells_to_pblock pb_dn_bank14 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?14?.g_dn* || NAME =~ *g_grp?14?.g_lmux* || NAME =~ *g_grp?14?.ra_p_reg?1?* || NAME =~ *g_grp?14?.wa_p_reg?1?* || NAME =~ *g_grp?14?.wd_p_reg?1?* || NAME =~ *g_grp?14?.w_p_reg?1?* || NAME =~ *g_grp?14?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank14 -add {CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}

# ---- pb_dn_bank15: DN pipeline group 15 -> SLR1 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank15
add_cells_to_pblock pb_dn_bank15 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?15?.g_dn* || NAME =~ *g_grp?15?.g_lmux* || NAME =~ *g_grp?15?.ra_p_reg?1?* || NAME =~ *g_grp?15?.wa_p_reg?1?* || NAME =~ *g_grp?15?.wd_p_reg?1?* || NAME =~ *g_grp?15?.w_p_reg?1?* || NAME =~ *g_grp?15?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank15 -add {CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}

# ---- pb_dn_bank16: DN pipeline group 16 -> SLR2 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank16
add_cells_to_pblock pb_dn_bank16 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?16?.g_dn* || NAME =~ *g_grp?16?.g_lmux* || NAME =~ *g_grp?16?.ra_p_reg?1?* || NAME =~ *g_grp?16?.wa_p_reg?1?* || NAME =~ *g_grp?16?.wd_p_reg?1?* || NAME =~ *g_grp?16?.w_p_reg?1?* || NAME =~ *g_grp?16?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank16 -add {CLOCKREGION_X0Y10:CLOCKREGION_X5Y14}

# ---- pb_dn_bank17: DN pipeline group 17 -> SLR2 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank17
add_cells_to_pblock pb_dn_bank17 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?17?.g_dn* || NAME =~ *g_grp?17?.g_lmux* || NAME =~ *g_grp?17?.ra_p_reg?1?* || NAME =~ *g_grp?17?.wa_p_reg?1?* || NAME =~ *g_grp?17?.wd_p_reg?1?* || NAME =~ *g_grp?17?.w_p_reg?1?* || NAME =~ *g_grp?17?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank17 -add {CLOCKREGION_X0Y10:CLOCKREGION_X5Y14}

# ---- pb_dn_bank18: DN pipeline group 18 -> SLR2 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank18
add_cells_to_pblock pb_dn_bank18 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?18?.g_dn* || NAME =~ *g_grp?18?.g_lmux* || NAME =~ *g_grp?18?.ra_p_reg?1?* || NAME =~ *g_grp?18?.wa_p_reg?1?* || NAME =~ *g_grp?18?.wd_p_reg?1?* || NAME =~ *g_grp?18?.w_p_reg?1?* || NAME =~ *g_grp?18?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank18 -add {CLOCKREGION_X0Y10:CLOCKREGION_X5Y14}

# ---- pb_dn_bank19: DN pipeline group 19 -> SLR2 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank19
add_cells_to_pblock pb_dn_bank19 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?19?.g_dn* || NAME =~ *g_grp?19?.g_lmux* || NAME =~ *g_grp?19?.ra_p_reg?1?* || NAME =~ *g_grp?19?.wa_p_reg?1?* || NAME =~ *g_grp?19?.wd_p_reg?1?* || NAME =~ *g_grp?19?.w_p_reg?1?* || NAME =~ *g_grp?19?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank19 -add {CLOCKREGION_X0Y10:CLOCKREGION_X5Y14}

# ---- pb_dn_bank20: DN pipeline group 20 -> SLR2 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank20
add_cells_to_pblock pb_dn_bank20 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?20?.g_dn* || NAME =~ *g_grp?20?.g_lmux* || NAME =~ *g_grp?20?.ra_p_reg?1?* || NAME =~ *g_grp?20?.wa_p_reg?1?* || NAME =~ *g_grp?20?.wd_p_reg?1?* || NAME =~ *g_grp?20?.w_p_reg?1?* || NAME =~ *g_grp?20?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank20 -add {CLOCKREGION_X0Y10:CLOCKREGION_X5Y14}

# ---- pb_dn_bank21: DN pipeline group 21 -> SLR2 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank21
add_cells_to_pblock pb_dn_bank21 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?21?.g_dn* || NAME =~ *g_grp?21?.g_lmux* || NAME =~ *g_grp?21?.ra_p_reg?1?* || NAME =~ *g_grp?21?.wa_p_reg?1?* || NAME =~ *g_grp?21?.wd_p_reg?1?* || NAME =~ *g_grp?21?.w_p_reg?1?* || NAME =~ *g_grp?21?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank21 -add {CLOCKREGION_X0Y10:CLOCKREGION_X5Y14}

# ---- pb_dn_bank22: DN pipeline group 22 -> SLR2 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank22
add_cells_to_pblock pb_dn_bank22 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?22?.g_dn* || NAME =~ *g_grp?22?.g_lmux* || NAME =~ *g_grp?22?.ra_p_reg?1?* || NAME =~ *g_grp?22?.wa_p_reg?1?* || NAME =~ *g_grp?22?.wd_p_reg?1?* || NAME =~ *g_grp?22?.w_p_reg?1?* || NAME =~ *g_grp?22?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank22 -add {CLOCKREGION_X0Y10:CLOCKREGION_X5Y14}

# ---- pb_dn_bank23: DN pipeline group 23 -> SLR2 (DN_BPG = 1: 1 bank = 29 URAM288)
create_pblock pb_dn_bank23
add_cells_to_pblock pb_dn_bank23 [get_cells -quiet -hierarchical -filter {NAME =~ *g_grp?23?.g_dn* || NAME =~ *g_grp?23?.g_lmux* || NAME =~ *g_grp?23?.ra_p_reg?1?* || NAME =~ *g_grp?23?.wa_p_reg?1?* || NAME =~ *g_grp?23?.wd_p_reg?1?* || NAME =~ *g_grp?23?.w_p_reg?1?* || NAME =~ *g_grp?23?.bs_p_reg?1?*}]
resize_pblock pb_dn_bank23 -add {CLOCKREGION_X0Y10:CLOCKREGION_X5Y14}

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
