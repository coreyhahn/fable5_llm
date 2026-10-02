#!/usr/bin/env bash
# drift_plan_prerepair.sh — the --plan verdict S1 saw BEFORE it repaired
# anything, reconstructed so it can be re-run instead of remembered.
#
# WHY IT EXISTS (fix round 1, I1).  S1's gate doc quoted
# "REPAIR 109 / COLLATERAL 5 across 19 citing files" — the state of the tree
# when the drift was first measured, before `--fix` touched docs/SEQ_ISA.md
# and before the seven hand repairs.  The committed
# evidence/qwen9b/s1/006_cite_drift_plan.log was taken AFTER those repairs
# and reads REPAIR 94 / COLLATERAL 20, because a repaired citation stops
# being "stale" and becomes "already correct".  Re-running --plan on the
# tree as it now stands can never reproduce the first number, so the first
# STATE is reconstructed instead:
#
#   a throwaway `git worktree` at the base commit — every citing document
#   exactly as it was, unrepaired — with ONLY the two edited code files
#   copied in from the working tree, which is what moved the lines.
#
# docs/SEQ_ISA.md is deliberately NOT copied in: it is both an edited file
# and a citing document, and its citations must be seen unrepaired.  B15 is
# a pure append that names no line of either code file, so leaving it out
# cannot change the count — and the reproduction agreeing with the number
# the gate doc quotes is the check on that.
#
#   bash evidence/qwen9b/s1/drift_plan_prerepair.sh [base] [work-ref]
set -u
cd "$(dirname "$0")/../../.."
BASE=${1:-e905cd3}
WORK=${2:-}                     # empty = the working tree's edited files
WT=${TMPDIR:-/tmp}/s1_prerepair_$$
PY=$PWD/ref/.venv/bin/python
MAIN=$PWD
EDITED="ref/seq_format.py sw/hwmap.py"

echo "=== base $BASE; edited files from ${WORK:-the working tree}"
rm -rf "$WT"
git worktree add --detach "$WT" "$BASE" >/dev/null 2>&1
[ -f "$WT/CHARTER.md" ] || { echo "cannot create the base worktree"; exit 2; }
for f in $EDITED; do
  if [ -n "$WORK" ]; then git show "$WORK:$f" > "$WT/$f"; else cp "$MAIN/$f" "$WT/$f"; fi
done

( cd "$WT" && "$PY" evidence/qwen9b/o3/o3_cite_drift.py \
    --base "$BASE" --edited ref/seq_format.py,sw/hwmap.py,docs/SEQ_ISA.md \
    --exclude evidence/qwen9b/s1/S1_ISA.md --plan )
rc=$?

git worktree remove --force "$WT" >/dev/null 2>&1
git worktree prune
rm -rf "$WT"
echo "=== o3_cite_drift --plan rc: $rc  (1 = UNSAFE, which is the point)"
