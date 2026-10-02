# fable5_floorplan_9b_layer0.xdc — 9B FLOORPLAN CANDIDATE 4'b add-on (the layer_0 pblock — O4) (G5a / Task 13, the OOC floorplan
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

# WHAT THIS FILE TESTS (brief variant 4', the "with a layer_0 pblock" half, and
# the O4 fork): the 2B campaign's T5 lesson is that constraining `layer_0` in
# ANY form cost ~1 ns (fable5_floorplan_a.xdc:8-10, TIMING_035.md 11.7), and
# fable5_floorplan_a.xdc's key result is the DELIBERATE ABSENCE of a layer_0
# pblock.  O4 asks whether the 9B floorplan may have one after all.
#
# ORDERING (load-bearing): a cell belongs to AT MOST ONE pblock, and
# add_cells_to_pblock MOVES it.  This file claims every cell in the design, so
# it MUST be read BEFORE fable5_floorplan_9b_dnslr.xdc, which then takes the DN
# URAM288 cells back out of it.  Reading it second silently empties the DN
# pblocks (measured: evidence/qwen9b/g5/001_pblock_preflight.log).
#
# THE ARITHMETIC FIRST.  At 928 of 960 URAM288 a layer_0 pblock has almost no
# freedom left: URAM288 sites live only in CLOCKREGION columns X1..X4, 16 per
# clock region, so a range that holds 928 must contain ALL FOUR URAM columns and
# ALL FIFTEEN clock-region rows.  The ONLY degrees of freedom are the two
# URAM-free columns X0 and X5.  This file therefore takes the TIGHTEST layer_0
# pblock the URAM arithmetic permits — CLOCKREGION_X0Y0:X4Y14, the whole device
# minus column X5 — and applies it to EVERY cell of the OOC design (in OOC,
# layer_chan IS layer_0).  In-context, column X5 is exactly the kind of area a
# floorplan would want to keep for the four mvchans.
#
# CAPACITY CHECK for this range, from the same measured census (per CLOCKREGION
# COLUMN, summed over all 15 rows: URAM288 / DSP48E2 / RAMBFIFO36):
#   X0   0 / 1,800 /  540      X3  240 / 1,080 / 180
#   X1 240 / 1,080 /  180      X4  240 / 1,080 / 360
#   X2 240 / 1,080 /  540      X5    0 /   720 / 360   <- the only column dropped
# Keeping X0..X4 leaves URAM288 960 >= 928, DSP48E2 6,120 >= 1,838 and
# RAMBFIFO36 1,800 >= the ~658 block RAM tiles layer_chan needs.
# SOFT, like every other pblock here.
#
# `get_cells *` (top level, NOT -hierarchical) is deliberate: it returns every
# top-level cell INCLUDING the hierarchical submodule instances, and a
# hierarchical cell in a pblock constrains its whole subtree.  A
# `-hierarchical -filter {IS_PRIMITIVE}` form would be both slower and, for any
# cell the filter misses, silently incomplete.
#
# IT IS ALSO THE ONE LINE IN THIS FILE SET THAT DOES NOT PREFIX-REWRITE.  Every
# other pattern here becomes its in-context form by prepending
# `bd_i/layer_0/`; `get_cells *` at OOC top level means "the whole design",
# which in context would mean the whole BD, not layer_0.  The in-context form
# of this pblock is the single hierarchical cell:
#     add_cells_to_pblock pb_layer0 [get_cells bd_i/layer_0]
# which is also exactly the constraint fable5_floorplan_a.xdc:8-10 says the 2B
# campaign found catastrophic, and is what O4 asks the user about.
create_pblock pb_layer0
add_cells_to_pblock pb_layer0 [get_cells -quiet *]
resize_pblock pb_layer0 -add {CLOCKREGION_X0Y0:CLOCKREGION_X4Y14}

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
