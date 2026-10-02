#!/usr/bin/env bash
# g7_block_identity.sh — the GREEN half of Task 16's citation-drift pass, for
# the class `o3_cite_drift.py --doc-cites` cannot close by itself.
#
# WHY IT EXISTS.  The G7 ship moved `NEXT_SESSION.md`'s whole dated stack into
# `docs/HISTORY.md`.  `o3_cite_drift.py` builds its line map per FILE
# (difflib over `git show <base>:<file>` vs the worktree), so a line that
# leaves one file for another maps to None and the tool reports
# "<file>:<n> was rewritten away; <citer> must be re-read by hand" — which is
# the tool naming the hand work, not a failure.  This script IS that hand
# work, done mechanically and once for the whole block instead of 37 times.
#
# It also answers the lesson Task 15's collection round left
# (RD9_GATE.md §18.3): keep the harness in the tree beside its log.
#
# THREE CHECKS, and each can fail:
#   1. THE BLOCK IS BYTE-IDENTICAL.  `git show $BASE:NEXT_SESSION.md` lines
#      $NS_LO..$NS_HI equal `docs/HISTORY.md` lines $H_LO..$H_HI in the
#      worktree.  One `diff`, and it must be empty.  That single fact makes
#      every `NEXT_SESSION.md:N -> docs/HISTORY.md:N+$OFF` repair correct,
#      for every N in the block, without checking them one at a time.
#   2. EVERY REPAIRED CITATION LANDS IN THE BLOCK.  Each number this pass
#      wrote as `docs/HISTORY.md:M` in a citing document must satisfy
#      $H_LO <= M <= $H_HI, i.e. it names a line that came from the block and
#      not some pre-existing HISTORY.md line that merely moved.  (The five
#      pre-existing `docs/HISTORY.md` citations that DID merely move are the
#      tool's own business and it verifies them; they are excluded by being
#      outside the block.)
#   3. NO LIVE `NEXT_SESSION.md:N` CITATION SURVIVES outside the file itself.
#      The two admissible residues are named here and nowhere else:
#        * a `<sha>:NEXT_SESSION.md:N` PIN — a statement about a tree that
#          cannot move, which `o3_cite_drift.py` skips by construction (#158);
#        * `evidence/qwen9b/g3/G3_3_MATVEC.md:697`, which QUOTES the drift
#          tool's own message about NEXT_SESSION.md line 449 being rewritten
#          away (written out of citation form in this comment for the same
#          reason).  Renumbering a quotation would fabricate it.  Left on
#          purpose, and
#          this is where that decision is recorded mechanically rather than
#          in prose.
#
# NEGATIVE CONTROL.  A checker that cannot fail proves nothing, so
# `--negative-control` shifts the landing window by ONE line and requires
# check 1 to FAIL and check 2 to report tokens outside the block.  It exits 0
# when both CAUGHT and non-zero if either MISSED.
#
# Usage:  bash evidence/qwen9b/o3/g7_block_identity.sh [BASE] [--negative-control]
set -u
cd "$(dirname "$0")/../../.."
BASE=f9828f2
NEG=0
for a in "$@"; do
  case "$a" in
    --negative-control) NEG=1 ;;
    *) BASE=$a ;;
  esac
done

NS_LO=6;  NS_HI=731          # the moved block, in NEXT_SESSION.md at $BASE
H_LO=46;  H_HI=771           # where it landed, in docs/HISTORY.md
if [ "$NEG" -eq 1 ]; then    # one line off, on purpose
  H_LO=47; H_HI=772
  echo "MODE  NEGATIVE CONTROL — the landing window is deliberately one line off"
fi
OFF=$(( H_LO - NS_LO ))      # 40 (41 under the control)

rc=0
echo "G7_BLOCK: base=$BASE  NEXT_SESSION.md:$NS_LO-$NS_HI -> docs/HISTORY.md:$H_LO-$H_HI  (offset +$OFF)"

# ---- 1. the block is byte-identical -----------------------------------
if diff <(git show "$BASE:NEXT_SESSION.md" | sed -n "${NS_LO},${NS_HI}p") \
        <(sed -n "${H_LO},${H_HI}p" docs/HISTORY.md) > /tmp/g7_block_diff.$$ 2>&1; then
  echo "G7_BLOCK_IDENTICAL: PASS  ($(( NS_HI - NS_LO + 1 )) lines, diff empty)"
else
  echo "G7_BLOCK_IDENTICAL: *** FAIL ***"
  head -20 /tmp/g7_block_diff.$$
  rc=1
fi
rm -f /tmp/g7_block_diff.$$

# ---- 2. every repaired citation lands inside the block -----------------
# The citing documents this pass repaired, named rather than globbed, so a
# file that quietly grows a citation later is not silently blessed.
CITERS="docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md
evidence/qwen9b/g3/G3_3_MATVEC.md
evidence/qwen9b/g3/G3_4_LAYER.md
evidence/qwen9b/g5/G5D_TIMING.md
evidence/qwen9b/g6/RD9_GATE.md"
n_in=0; n_out=0
for f in $CITERS; do
  # full tokens and bare continuations bound to a docs/HISTORY.md mention
  for m in $(grep -o 'docs/HISTORY\.md:[0-9]\+\(-[0-9]\+\)\?' "$f" \
             | sed 's|docs/HISTORY\.md:||' | tr '-' '\n'); do
    if [ "$m" -ge "$H_LO" ] && [ "$m" -le "$H_HI" ]; then
      n_in=$(( n_in + 1 ))
    else
      echo "  ! OUTSIDE THE BLOCK  $f names docs/HISTORY.md:$m"
      n_out=$(( n_out + 1 ))
    fi
  done
done
if [ "$n_out" -eq 0 ]; then
  echo "G7_REPAIRS_IN_BLOCK: PASS  ($n_in number(s) checked, 0 outside)"
else
  echo "G7_REPAIRS_IN_BLOCK: *** FAIL *** ($n_out outside the block)"
  rc=1
fi

# ---- 3. no live NEXT_SESSION.md:N citation survives --------------------
# A pin carries a leading <sha>: and is skipped, exactly as the tool skips it.
# `git grep` over the TRACKED tree: citations live in committed documents,
# and a plain `grep -r` here would also walk the gitignored 72 GiB of w9
# artifacts.
live=$(git grep -n 'NEXT_SESSION\.md:[0-9]' -- '*.md' '*.py' '*.sh' '*.tcl' \
       | grep -v '^NEXT_SESSION\.md:' \
       | grep -v '[0-9a-f]\{7,40\}:NEXT_SESSION\.md:' \
       | grep -v '^evidence/qwen9b/g3/G3_3_MATVEC\.md:697:' \
       | grep -v '^evidence/qwen9b/o3/g7_block_identity\.sh:')
if [ -z "$live" ]; then
  echo "G7_NO_LIVE_NS_CITE: PASS  (only the pins and the one quoted tool message remain)"
else
  echo "G7_NO_LIVE_NS_CITE: *** FAIL ***"
  echo "$live"
  rc=1
fi

# ---- the two admissible residues, PRINTED so they are never silent -----
echo "--- the residues, by name (each must be exactly one line):"
git grep -n '[0-9a-f]\{7,40\}:NEXT_SESSION\.md:[0-9]' -- '*.md' \
  | sed 's/^/    PIN   /'
grep -n 'NEXT_SESSION\.md:449 was rewritten away' \
  evidence/qwen9b/g3/G3_3_MATVEC.md | sed 's|^|    QUOTE evidence/qwen9b/g3/G3_3_MATVEC.md:|'

if [ "$NEG" -eq 1 ]; then
  # rc is 1 when the shifted window was CAUGHT by checks 1 and 2.
  if [ "$rc" -ne 0 ]; then
    echo "G7_BLOCK_IDENTITY NEGATIVE CONTROL: CAUGHT"
    exit 0
  fi
  echo "G7_BLOCK_IDENTITY NEGATIVE CONTROL: *** MISSED ***"
  exit 1
fi
[ "$rc" -eq 0 ] && echo "G7_BLOCK_IDENTITY: PASS" || echo "G7_BLOCK_IDENTITY: FAIL"
exit $rc
