#!/bin/bash
# s5fix_rtl_bytes.sh — S5 fix round 1: the five Vivado runs of this round were
# launched on trees whose `rtl/` is NOT byte-identical to the tree this round
# commits.  This says by how much, and the answer has to be "comment text
# only" or every number in the gate doc is about a different design.
#
# WHY THERE IS A DIFFERENCE AT ALL.  203cca8 added the two `ram_style`
# attributes and ONE comment line above them; the counts (5cb1899) and the
# three placements (56459a6) ran on that.  d9cb8e4 then withdrew the added
# comment line — one line in rtl/layer_chan.sv drove a 228-citation drift
# cascade through documents outside this round's commit block — and folded the
# same sentence into the comment block that already carries the URAM
# arithmetic, at the same line count.  Nothing else in rtl/ moved.
#
# The same question is asked of the FLOORPLAN the two constrained placements
# read: synth/constraints/fable5_floorplan_9b_1slr.xdc gained a MEASURED
# capacity block at its end after those runs had already read it, and that
# block must likewise be comment text only or the placed floorplan is not the
# committed floorplan.  Both paths are checked together.
#
# A comment cannot synthesize, so the netlists are the same netlists; but
# "cannot" is an argument and this is the measurement.  Usage:
#   bash evidence/qwen9b/s5/s5fix_rtl_bytes.sh [<run-tree> ...]
# with no arguments it checks the two trees this round's runs name.
#
# Negative control: pass a tree whose rtl/ really did change, e.g. the S2 base
#   bash evidence/qwen9b/s5/s5fix_rtl_bytes.sh 0984087
# which MUST print CODE CHANGED and exit non-zero.
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 2
# `#` opens a comment in XDC/Tcl, `//` in SystemVerilog; both are allowed.
PATHS=(rtl/ synth/constraints/fable5_floorplan_9b_1slr.xdc)
TREES=("$@")
[ ${#TREES[@]} -eq 0 ] && TREES=(5cb1899 56459a6)
HEAD_SHA=$(git rev-parse --short HEAD)
echo "S5FIXRTL_HEAD: $HEAD_SHA"
bad=0
for t in "${TREES[@]}"; do
  d=$(git diff -U0 "$t" HEAD -- "${PATHS[@]}")
  all=$(printf '%s\n' "$d" | grep -cE '^[+-]([^+-]|$)')
  code=$(printf '%s\n' "$d" | grep -E '^[+-]([^+-]|$)' | grep -vcE '^[+-][[:space:]]*((//|#).*)?$')
  files=$(git diff --name-only "$t" HEAD -- "${PATHS[@]}" | tr '\n' ' ')
  if [ "$code" -eq 0 ]; then s="COMMENT-ONLY"; else s="CODE CHANGED "; bad=$((bad+1)); fi
  printf 'S5FIXRTL_ROW %s  %s..%s  %d changed line(s), %d non-comment  files: %s\n' \
         "$s" "$t" "$HEAD_SHA" "$all" "$code" "${files:-none}"
done
if [ "$bad" -eq 0 ]; then
  echo "S5FIXRTL: PASS — every run tree differs from HEAD in comment text only, over ${PATHS[*]}"
  exit 0
fi
echo "S5FIXRTL: FAIL ($bad tree(s) with a non-comment difference)"
exit 1
