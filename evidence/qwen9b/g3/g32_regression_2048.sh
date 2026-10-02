#!/usr/bin/env bash
# g32_regression_2048.sh — G3.2's byte-identity control for the 2048 set.
#
# Task 8 added a SECOND vecnorm vector set (N=4096) to
# tb/scripts/gen_seq_c_vectors.py.  That generator draws every case from ONE
# shared numpy Generator, consumed in order, so an insertion anywhere but the
# END silently re-rolls everything after it — and the N=2048 set is the 2B
# REGRESSION this gate is not allowed to disturb.  The brief says keep it; this
# script proves it was kept, rather than asserting it.
#
# Method (M): regenerate the PRE-G3.2 generator out of git at <base> into a
# scratch tree, run the CURRENT one through the normal `make seq_c_vectors`
# path, and `cmp` every file the old generator produced.  All eight per seed
# (the three case files AND the six 2048 hex files) must be byte-identical on
# all four seeds; the two 4096 sets must be NEW files, present only in the new
# tree.
#
# The scratch tree lives under tb/vecseq/, which .gitignore already ignores.
#
# Usage:  bash evidence/qwen9b/g3/g32_regression_2048.sh [base-sha] [python]
#   default base   ec08638   (the tree G3.2 started from)
#   default python /home/cah/.venv/bin/python on snoke, ref/.venv/bin/python
#                  otherwise — `ref/.venv/bin/python` is a DANGLING SYMLINK on
#                  snoke, so the probe is `test -x`, never a name check.
set -u
cd "$(dirname "$0")/../../.."

BASE=${1:-ec08638}
if [ $# -ge 2 ]; then
  PY=$2
elif [ -x /home/cah/.venv/bin/python ]; then
  PY=/home/cah/.venv/bin/python
elif [ -x ref/.venv/bin/python ]; then
  PY=ref/.venv/bin/python
else
  echo "no usable interpreter (probed /home/cah/.venv and ref/.venv)"; exit 2
fi
echo "base=$BASE  python=$PY"

CTL=tb/vecseq/_g32_regression
rm -rf "$CTL"; mkdir -p "$CTL"
git show "$BASE:tb/scripts/gen_seq_c_vectors.py" > "$CTL/gen_base.py" || exit 2

for s in 1 2 3 4; do
  PYTHONPATH="$PWD/ref" "$PY" "$CTL/gen_base.py" "$CTL/base_s$s" "$s" || exit 2
done
( cd tb && make VECPY="$PY" seq_c_vectors ) || exit 2

FILES="dynq16_cases.txt probe8_cases.txt epsnorm_cases.txt
       rms2048_x16.hex rms2048_w14.hex rms2048_y16.hex
       l2n2048_x16.hex l2n2048_y16.hex"
NEW="rms4096_x16.hex rms4096_w14.hex rms4096_y16.hex
     l2n4096_x16.hex l2n4096_y16.hex"

rc=0; same=0; diff=0; new=0
for s in 1 2 3 4; do
  for f in $FILES; do
    if cmp -s "$CTL/base_s$s/$f" "tb/vecseq/s$s/$f"; then
      same=$((same + 1))
    else
      echo "  DIFFERS   s$s/$f"; diff=$((diff + 1)); rc=1
    fi
  done
  for f in $NEW; do
    if [ -s "tb/vecseq/s$s/$f" ] && [ ! -e "$CTL/base_s$s/$f" ]; then
      new=$((new + 1))
    else
      echo "  NOT NEW   s$s/$f (missing now, or already present at $BASE)"
      rc=1
    fi
  done
  # the 4096 hex files must really be 4096 lines long
  for f in $NEW; do
    n=$(wc -l < "tb/vecseq/s$s/$f")
    [ "$n" = "4096" ] || { echo "  BAD LEN   s$s/$f = $n lines"; rc=1; }
  done
done

echo "G32_REGRESSION_2048: identical=$same differs=$diff new4096=$new"
if [ $rc -eq 0 ]; then
  echo "G32_REGRESSION_2048 PASS — the N=2048 regression is BYTE-IDENTICAL to"
  echo "  $BASE on all 4 seeds, and the N=4096 set is new and 4096 long"
else
  echo "G32_REGRESSION_2048 FAIL"
fi
exit $rc
