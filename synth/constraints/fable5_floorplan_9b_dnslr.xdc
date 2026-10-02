# fable5_floorplan_9b_dnslr.xdc — 9B FLOORPLAN CANDIDATE 4'a (three-SLR DN array floorplan) (G5a / Task 13, the OOC floorplan
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

# WHAT THIS FILE TESTS (brief variant 4'): a three-SLR floorplan for the DN
# ARRAY ITSELF — 8 banks per SLR — and NOTHING else.  A1.4: at 928 URAM288 the
# array spans all three SLRs by arithmetic (2 x 320 = 640 < 928), so the only
# question a floorplan can answer is WHICH banks go WHERE, not whether they
# straddle.  Members are the URAM288 cells ONLY: no register is pinned, which is
# exactly what separates this file from fable5_floorplan_9b_dngrp.xdc and
# isolates the effect of pinning the fan-out registers.
# DN_BPG = 8 (three groups of eight banks).

# ---- pb_dn_slr0: DN group 0's URAM288 BANKS ONLY -> SLR0
create_pblock pb_dn_slr0
add_cells_to_pblock pb_dn_slr0 [get_cells -quiet -hierarchical -filter {REF_NAME =~ URAM288* && NAME =~ *g_grp?0?.g_dn*}]
resize_pblock pb_dn_slr0 -add {CLOCKREGION_X0Y0:CLOCKREGION_X5Y4}

# ---- pb_dn_slr1: DN group 1's URAM288 BANKS ONLY -> SLR1
create_pblock pb_dn_slr1
add_cells_to_pblock pb_dn_slr1 [get_cells -quiet -hierarchical -filter {REF_NAME =~ URAM288* && NAME =~ *g_grp?1?.g_dn*}]
resize_pblock pb_dn_slr1 -add {CLOCKREGION_X0Y5:CLOCKREGION_X5Y9}

# ---- pb_dn_slr2: DN group 2's URAM288 BANKS ONLY -> SLR2
create_pblock pb_dn_slr2
add_cells_to_pblock pb_dn_slr2 [get_cells -quiet -hierarchical -filter {REF_NAME =~ URAM288* && NAME =~ *g_grp?2?.g_dn*}]
resize_pblock pb_dn_slr2 -add {CLOCKREGION_X0Y10:CLOCKREGION_X5Y14}

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
