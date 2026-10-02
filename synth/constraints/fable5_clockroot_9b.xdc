# fable5_clockroot_9b.xdc — IMPLEMENTATION-ONLY. Task 14-B's one constraint-side
# arm: move the 250 MHz aclk's CLOCK ROOT into the SLR that holds `layer_0`.
#
# ---------------------------------------------------------------------------
# WHAT THIS FILE IS FOR, and the measurement that justifies it
# ---------------------------------------------------------------------------
# Task 14-A's design note section 7.3 recorded a term nobody had costed: the
# layer's paths carry ~0.2 ns MORE clock skew than everything else on an aclk
# net with a fan-out of ~150,000, and said it was "a clocking/placement
# question, not an RTL one".  Task 14-B's brief made it the one constraint-side
# arm, on the condition that a READ-ONLY probe support it FIRST.
#
# The probe is `evidence/qwen9b/g5/g5d_clockskew_probe.tcl`, run on the best
# roll of 14-B's spread (`evidence/qwen9b/g5/125_t14b_skewprobe_ash.log`,
# rc 0, on `po2_AltSpreadLogic_high`'s post-route-phys_opt checkpoint).  It
# says three things, all measured:
#
#   1. The aclk net `.../phy_clk_i/PHY_USERCLK` (driven by BUFG_GT_X1Y203)
#      has `CLOCK_ROOT = X2Y5` and `USER_CLOCK_ROOT = (none)` — i.e. the
#      placer chose it, and X2Y5 is the BOTTOM ROW OF SLR1
#      (SLR0 = clock-region rows Y0..Y4, SLR1 = Y5..Y9, SLR2 = Y10..Y14, from
#      `evidence/qwen9b/g5/116_t14b_slrcensus_ash.log`'s SLR_GEOMETRY block).
#
#   2. All 2,101 of `bd_i/layer_0`'s dedicated blocks (DSP48E2 + URAM288 +
#      RAMB36) are in clock-region rows Y0..Y4 — the WHOLE LAYER IS IN SLR0 on
#      that roll, by the placer's own choice and with no pblock of any kind
#      (`PBLOCK_COUNT: 0`).  The same log's SLICE histogram reads
#      `bd_i/layer_0 SLR0=205807(100%) SLR1=6(0%) SLR2=0(0%)`.
#
#   3. The design's worst path is inside that layer and its clock legs BOTH
#      cross `SLR Crossing[1->0]`:
#         Clock Path Skew:        -0.372 ns
#         Source Clock Delay:      4.225 ns   Clock Net Delay (Source): 4.010
#         Destination Clock Delay: 3.599 ns   Clock Net Delay (Dest)  : 3.407
#      against `seq_0` — which sits in SLR1, beside the root — at skew
#      -0.058 ns with net delays 3.571 / 3.233.  The layer pays 0.314 ns more
#      skew than the sequencer on the same clock, and the report names the
#      mechanism: the root is on the far side of an SLR boundary from every
#      load on the failing path, so the two legs differ by 0.603 ns of clock
#      net delay after the crossing.
#
# ---------------------------------------------------------------------------
# THE COORDINATE, and why this one
# ---------------------------------------------------------------------------
# X2Y2 is the CENTROID of the layer's dedicated blocks, computed from the
# probe's own clock-region histogram (`CSK_LOADS bd_i/layer_0` in log 125),
# not chosen by eye:
#
#   rows    Y0=347  Y1=452  Y2=512  Y3=487  Y4=303   (sum 2101)
#           weighted mean = 4149/2101 = 1.975 -> Y2
#   columns X0=502  X1=429  X2=395  X3=315  X4=388  X5=72   (sum 2101)
#           weighted mean = 4076/2101 = 1.940 -> X2
#
# `layer_0` owns 2,467 of the best roll's 2,507 failing setup endpoints
# (98.4 %, `evidence/qwen9b/g5/115_t14b_census_ash.log`'s OWNER tally), so the
# centroid of the layer is the right target for a clock root that has to serve
# one owner well.
#
# WHAT IT COSTS, stated rather than discovered: `seq_0` (+0.278), `xdma_0`
# (0 failing endpoints on that roll) and 78 % of `axi_smc` are in SLR1 and
# their clock legs get LONGER.  That is the trade this arm measures.  It is
# reported as an A/B against the identical directive with no XDC, and if it
# loses, it loses.
#
# ---------------------------------------------------------------------------
# HOW IT IS APPLIED, and what it does NOT do
# ---------------------------------------------------------------------------
# Passed through `synth/scripts/full_impl.tcl`'s ordered implementation-only
# XDC list (`XDC=<abs path> synth/scripts/launch_po2.sh …`), so it is read with
# `USED_IN_SYNTHESIS false` and changes no RTL and no synthesis result.
#
# It adds NO clock, NO MMCM, NO BUFG and NO CDC: `USER_CLOCK_ROOT` only tells
# the clock placer where to drive an EXISTING global net from.  The design
# stays single-clock-domain, exactly as CLAUDE.md requires.
#
# It creates NO pblock.  14-B's primary arms carry no floorplan by design
# (Task 14's controlled A/B measured pblocks costing 0.879 ns — G5B_TIMING.md
# section 4.7), and this file does not reintroduce one.
#
# ---------------------------------------------------------------------------
# WHY THERE IS NO GUARD IN THIS FILE, and where the guard actually is
# ---------------------------------------------------------------------------
# The first version of this file carried its own assertion — two `if` guards
# and a confirming `puts`.  Vivado's MANAGED-PROJECT XDC parser accepts
# `set_property` but NOT `if` and NOT `puts`, so it dropped all three with a
# CRITICAL WARNING each and the file would have run with no assertion at all.
# That roll was killed 22 minutes in and its evidence is
# `evidence/qwen9b/g5/132_t14b_clockroot_xdc_RED.txt`.
#
# So this file is now ONE parser-legal `set_property` and no control flow, and
# the guard lives in `evidence/qwen9b/g5/g5d_clockroot_check.tcl` — a read-only
# `-source` script, where the full Tcl interpreter IS available.  It opens a
# real checkpoint, reads `USER_CLOCK_ROOT` BEFORE (expects none), applies this
# file, reads it AFTER (requires X2Y2), and exits non-zero otherwise.  Reading
# the property back off the netlist is a stronger check than echoing what was
# just set, and it runs BEFORE the four-hour roll rather than after it.
#
# A `set_property` on an empty object list is silent in Vivado, which is
# exactly how a constraint campaign measures nothing — the same failure class
# `synth/scripts/floorplan_check.tcl`'s header exists for.  The check script is
# what stops that here, and the roll's own routed checkpoint is re-probed
# afterwards so the shipped number and the applied constraint are tied together.

# ---------------------------------------------------------------------------
# THE DEPENDENCY THIS CONSTANT RESTS ON — READ THIS BEFORE REUSING THE FILE
# ---------------------------------------------------------------------------
# X2Y2 is VALID ONLY WHILE THE PLACER KEEPS `bd_i/layer_0` IN SLR0.  It is the
# centroid of that layer's dedicated blocks on the placement measured above,
# and three campaigns have now landed the layer on three different dies
# (S5 SLR1, Task 14 SLR2, Task 14-B SLR0).  If a future roll's placer chooses
# a different die, X2Y2 pulls the clock root AWAY from its own loads and this
# arm becomes a COST rather than a gain — silently, because a `set_property`
# that lands in the wrong place still succeeds.
#
# `evidence/qwen9b/g5/g5d_clockroot_check.tcl` ASSERTS IT.  It censuses
# `layer_0`'s URAM288 cells by clock region, maps each region to its SLR with
# the device-measured mapping `synth/scripts/slr_census.tcl` uses, and requires
# the SLR holding the majority of them to be the SLR of this file's clock
# root: `CLOCKROOT_SLR_OK <slr>`, or `CLOCKROOT_SLR_MISMATCH layer=<slr>
# root=<slr>` and exit 1.
#
# RE-PROBE ON ANY NETLIST OR DIRECTIVE CHANGE.  Run
#   vivado -mode batch -nojournal -source \
#     evidence/qwen9b/g5/g5d_clockroot_check.tcl \
#     -tclargs <candidate routed.dcp> synth/constraints/fable5_clockroot_9b.xdc \
#              X2Y2 verify
# on every candidate BEFORE `synth/scripts/final_verify.tcl`.  If it reports
# `CLOCKROOT_SLR_MISMATCH`, do NOT ship the roll: recompute the centroid from
# `evidence/qwen9b/g5/g5d_clockskew_probe.tcl`'s `CSK_LOADS bd_i/layer_0`
# histogram on that placement and edit the coordinate, or drop the file.

set_property USER_CLOCK_ROOT X2Y2 [get_nets -hier -filter {NAME =~ *diablo_gt.diablo_gt_phy_wrapper/phy_clk_i/PHY_USERCLK}]
