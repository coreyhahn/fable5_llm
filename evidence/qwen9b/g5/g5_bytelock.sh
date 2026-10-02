#!/bin/bash
# g5_bytelock.sh — the G5a vehicle byte-lock.
#
# THE CLAIM (evidence/qwen9b/g5/G5A_FLOORPLAN.md:173-174): the G5a placement
# runs were LAUNCHED from a working tree with 9 dirty files (their run.log
# headers say "tree: 09840877 9 dirty files"), and those 9 files are EXACTLY
# what commit 5ee5f0e landed, byte for byte — so the placed vehicle and the
# committed vehicle are the same bytes.
#
# ===== S5 fix round 1 (2026-09-05): THE COMPARAND IS RE-PINNED ==============
# The claim above is about the PAST and it does not decay.  What decayed is the
# COMPARISON this script used to make it with: it hashed the WORKING TREE, so
# every later edit to one of the nine files turned an established fact into a
# false alarm.  By 2026-09-05 SIX of the nine differed from 5ee5f0e:
#   * synth/exp_uram/scripts/exp_ooc.tcl and .../launch_exp.sh — S5's harness
#     repair (state_dma in the file list, DN_PIPE/DN_BPG retired, the 182
#     prediction), commit 011ee16.  These are SUBSTANTIVE edits: the S5 vehicle
#     is deliberately NOT the G5a vehicle, so re-pinning them to today's bytes
#     would assert something false.
#   * the four Task-13 XDCs — S5's SUPERSEDED banner, commit 18641a1, comment
#     lines only.
# and `git diff 0984087 HEAD -- rtl/` printed four changed files (S2's
# state-spill rewrite) under a sentence that says "no lines above = unchanged".
# The script also had NO verdict line, so it could not pass or fail: a reader
# had to eyeball nine rows.  Evidence of all of that: the RED run
# evidence/qwen9b/s5/084_bytelock_red.log.
#
# So the comparand moves from "the tree NOW" to $EVIDENCE — the commit the
# committed proof evidence/qwen9b/g5/006_bytelock_vehicle.log ran on — which is
# what the claim was ever about.  The lock keeps a LIVE half: the four banner-ed
# XDCs are checked against 5ee5f0e AT HEAD and must differ by comment lines
# ONLY, so a future substantive edit to any of them still fires.
#
#   bash evidence/qwen9b/g5/g5_bytelock.sh
#   G5_BYTELOCK_EVIDENCE=HEAD bash evidence/qwen9b/g5/g5_bytelock.sh   # the
#       negative control: points the comparand back at the moving tree, where
#       six of the nine differ, and MUST print FAIL.
# ===========================================================================
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 2

VEHICLE=5ee5f0e                          # the commit that landed the 9 files
EVIDENCE=${G5_BYTELOCK_EVIDENCE:-6493ca8}  # the tree 006_bytelock_vehicle.log ran on
BANNERS=18641a1                          # S5's SUPERSEDED banner commit
RTLBASE=0984087                          # the tree the run.log headers name
bad=0

echo "pins: vehicle=$VEHICLE evidence=$EVIDENCE banners=$BANNERS rtl_base=$RTLBASE"
echo
echo "run.log header of every variant (host / date / tree / rtl / extra_xdc):"
for v in g5_v1a g5_v1b g5_v2 g5_v2alt g5_v3 g5_v4a g5_v4b; do
  echo "--- $v"
  if [ -f "synth/out_exp_uram_$v/run.log" ]; then
    sed -n '2,8p' "synth/out_exp_uram_$v/run.log" | sed 's/^/    /'
  else
    echo "    (absent — synth/out_* is gitignored and this dir is gone; the"
    echo "     headers are quoted in evidence/qwen9b/g5/006_bytelock_vehicle.log)"
  fi
done
echo
echo "the 9 files that were dirty at launch, and their sha1 in $VEHICLE vs $EVIDENCE:"
for f in synth/exp_uram/scripts/exp_ooc.tcl synth/exp_uram/scripts/launch_exp.sh \
         synth/exp_uram/scripts/check_pblocks.tcl synth/exp_uram/scripts/dev_geom_census.tcl \
         synth/exp_uram/scripts/probe_names.tcl \
         synth/constraints/fable5_floorplan_9b_dngrp.xdc \
         synth/constraints/fable5_floorplan_9b_dnbank.xdc \
         synth/constraints/fable5_floorplan_9b_dnslr.xdc \
         synth/constraints/fable5_floorplan_9b_layer0.xdc; do
  a=$(git rev-parse "$VEHICLE:$f" 2>/dev/null)
  b=$(git rev-parse "$EVIDENCE:$f" 2>/dev/null)
  if [ -n "$a" ] && [ "$a" = "$b" ]; then s="MATCH  "; else s="DIFFERS"; bad=$((bad+1)); fi
  printf "  %s %s  %s\n" "$s" "${a:0:12}" "$f"
done
echo
echo "the four of those nine that S5 banner-ed at $BANNERS: comment-only at HEAD?"
for f in synth/constraints/fable5_floorplan_9b_dngrp.xdc \
         synth/constraints/fable5_floorplan_9b_dnbank.xdc \
         synth/constraints/fable5_floorplan_9b_dnslr.xdc \
         synth/constraints/fable5_floorplan_9b_layer0.xdc; do
  d=$(git diff -U0 "$VEHICLE" HEAD -- "$f")
  all=$(printf '%s\n' "$d" | grep -cE '^[+-]([^+-]|$)')
  code=$(printf '%s\n' "$d" | grep -E '^[+-]([^+-]|$)' | grep -vcE '^[+-][[:space:]]*(#.*)?$')
  if [ "$code" -eq 0 ]; then s="COMMENT-ONLY"; else s="CODE CHANGED "; bad=$((bad+1)); fi
  printf "  %s  %2d changed line(s), %d of them non-comment  %s\n" "$s" "$all" "$code" "$f"
done
echo
echo "and the SHIPPING rtl/ the vehicle read, between $RTLBASE and $EVIDENCE:"
rtl=$(git diff --stat "$RTLBASE" "$EVIDENCE" -- rtl/)
if [ -z "$rtl" ]; then
  echo "  (empty = rtl/ byte-identical to the tree the runs' header names)"
else
  printf '%s\n' "$rtl" | sed 's/^/  /'
  bad=$((bad+1))
fi
echo
if [ "$bad" -eq 0 ]; then
  echo "G5_BYTELOCK: PASS — 9 vehicle files byte-identical, 4 banner-ed XDCs comment-only, rtl/ unmoved"
  exit 0
else
  echo "G5_BYTELOCK: FAIL ($bad check(s))"
  exit 1
fi
