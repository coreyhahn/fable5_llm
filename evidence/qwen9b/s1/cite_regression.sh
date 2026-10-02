#!/usr/bin/env bash
# cite_regression.sh — what did S1's line insertions do to the citation
# checkers, measured BOTH SIDES.
#
# S1 inserts ~84 lines into ref/seq_format.py and ~28 into sw/hwmap.py at
# the anchors the plan names, so every citation into those files BELOW an
# insertion moves.  `o3_cite_drift.py --plan` counts them all; this script
# answers the narrower and more consequential question: which documents
# does `evidence/qwen_next/spec_cites.py` now REFUSE that it accepted
# before?  (spec_cites only cross-checks a quotation that shares a markdown
# line with its citation, so it sees a small subset of the drift — the
# subset that is a hard gate.)
#
# BOTH SIDES IN ONE PLACE, reproducibly.  A throwaway `git worktree` at the
# base commit is the BEFORE tree; the AFTER tree is that same worktree with
# S1's three edited files copied in over it.  Measuring both columns in the
# SAME worktree matters: a worktree holds only TRACKED files, so some EXIST
# checks fail there that pass in the working tree (generated artifacts).
# That contamination is then IDENTICAL on both sides and cancels out of the
# delta, which is the number this script is for.  (Measured: the working
# tree reports 0 failures for the migration spec where the worktree reports
# 19 — so a working-tree "after" against a worktree "before" would have
# hidden every regression in that document.)
#
#   bash evidence/qwen9b/s1/cite_regression.sh [base]      # default e905cd3
set -u
cd "$(dirname "$0")/../../.."
BASE=${1:-e905cd3}
PY=ref/.venv/bin/python
WT=${TMPDIR:-/tmp}/s1_cite_base_$$

DOCS="docs/ARCHITECTURE.md
docs/QWEN35_NEXT_FEASIBILITY.md
docs/SEQ_ISA.md
docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md
docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md
docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md
docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md
evidence/qwen2b/q2/v4_v5/V4_V5.md
evidence/qwen9b/g2/G2C_CHAIN.md
evidence/qwen9b/g3/G3_1_ISA.md
evidence/qwen9b/g3/G3_3_MATVEC.md
evidence/qwen9b/g3/G3_4_LAYER.md
evidence/qwen9b/o3/BOARD_LOCK.md"

EDITED="docs/SEQ_ISA.md ref/seq_format.py sw/hwmap.py"
# the documents S1 hand-repaired because its insertions moved a line they
# QUOTE (spec_cites' one hard check).  They belong in the AFTER tree too,
# or the table would report a regression S1 has already closed.
REPAIRED="docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md
docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md
evidence/qwen9b/g2/G2C_CHAIN.md
evidence/qwen9b/g3/G3_4_LAYER.md"

verdict() {   # $1 = repo root to run in, $2 = doc
  ( cd "$1" && "$PWD_MAIN/$PY" evidence/qwen_next/spec_cites.py "$2" 2>&1 ) \
    | /usr/bin/grep -E "^checked:" | sed 's/.*|  //'
}

PWD_MAIN=$PWD
echo "=== base $BASE, worktree $WT"
rm -rf "$WT"
git worktree add --detach "$WT" "$BASE" >/dev/null 2>&1
[ -f "$WT/CHARTER.md" ] || { echo "cannot create the base worktree"; exit 2; }

# the BEFORE column first, on the untouched base worktree
declare -A BEFORE
for d in $DOCS; do BEFORE[$d]=$(verdict "$WT" "$d"); done
# then S1's three files copied in, and the same 13 documents re-checked
for f in $EDITED $REPAIRED; do cp "$PWD_MAIN/$f" "$WT/$f"; done
echo "=== copied into the worktree: $EDITED"
echo "===   plus the hand-repaired documents: $(echo $REPAIRED | tr '\n' ' ')"
echo

printf '%-64s %-10s %-10s %s\n' document before after delta
bad=0
for d in $DOCS; do
  b=${BEFORE[$d]}
  a=$(verdict "$WT" "$d")
  bn=${b##FAIL }; an=${a##FAIL }
  mark=""
  if [ "$an" -gt "$bn" ]; then mark="  <-- S1 REGRESSION (+$((an - bn)))"; bad=$((bad + an - bn)); fi
  printf '%-64s %-10s %-10s %s\n' "$d" "$b" "$a" "$mark"
done

git worktree remove --force "$WT" >/dev/null 2>&1
git worktree prune
rm -rf "$WT"

echo
if [ "$bad" -eq 0 ]; then
  echo "S1_CITE_REGRESSION: NONE (0 new spec_cites failures)"
else
  echo "S1_CITE_REGRESSION: $bad new spec_cites failure(s) — see the table"
fi
