#!/usr/bin/env bash
# Re-review round 1, m4: `evidence/qwen9b/s3/097_rs_f_rider_banner.log:52`
# records CASE B as "21 identical, 7 differing" and names NOT ONE of the
# seven — `cmp_set` (`evidence/qwen9b/s3/rs_f_rider_banner.sh:76-85`) prints
# only two counts, and both scratch emission directories were removed at the
# end of that run, so the set could afterwards only be INFERRED.
#
# This re-takes CASE B's COMPARISON alone and ECHOES EVERY BASENAME.  Same
# emission command, same glob, same reference set; the counts are CHECKED
# against 097's 21/7, so a set that does not reproduce 097 is a FAIL rather
# than a quiet re-definition of what CASE B measured.
#
# RUN ON SNOKE, through evidence/qwen9b/run.sh.  Nothing is written inside
# tb/scripts/w9: the emission goes to its own scratch directory, which is
# removed at the end.  The board is not touched.  The smoke emission uses
# RANDOM weights (tb/Makefile's own note), so no checkpoint, no HF cache and
# no GPTQ Hessian are read.
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm
PY=/home/cah/.venv/bin/python
REF=tb/scripts/w9
TAG=rider_names
OUT=tb/scripts/w9_$TAG
trap 'rm -rf "$OUT"' EXIT INT TERM HUP
FAIL=0
chk() { if [ "$2" = "$3" ]; then echo "  PASS  $1"; else
  echo "  FAIL  $1"; echo "        expected: $2"; echo "        actual:   $3"
  FAIL=$((FAIL + 1)); fi; }

echo "=== the reference set: $REF (the COMMITTED smoke set)"
echo "=== the glob: \$REF/lay9b_s1.* \$REF/lay9b_s1_*  (cmp_set's own, verbatim)"
N=0
for f in $REF/lay9b_s1.* $REF/lay9b_s1_*; do [ -f "$f" ] && N=$((N + 1)); done
echo "    files in the comparison set: $N"
chk "the comparison set is 097's 28 files" "28" "$N"

echo
echo "=== the CASE B emission, re-taken WITH the rider"
echo "===   W9_MODEL='FABLE5_MODEL=9b FABLE5_RS_F=8 FABLE5_RS_F_RIDER=1'"
rm -rf "$OUT"
BLOG=$(mktemp -t rsfrn.XXXXXX)
make -C tb w9_9b_smoke_scripts W9_DIR="scripts/w9_$TAG" W9_SEEDS=1 \
     MODELPY=$PY VECPY=$PY \
     W9_MODEL='FABLE5_MODEL=9b FABLE5_RS_F=8 FABLE5_RS_F_RIDER=1' \
     > "$BLOG" 2>&1
echo "MAKE_RC=$?" >> "$BLOG"
tail -4 "$BLOG" | sed 's/^/    /'
NB=$(grep -c 'FABLE5_RS_F_RIDER=1: RS_F=8 OVERRIDES the law RS_F=7' "$BLOG")
echo "    FABLE5_RS_F_RIDER banner lines in the emission output: $NB"
chk "the emission rc is 0" "1" "$(grep -c '^MAKE_RC=0' "$BLOG")"
chk "the rider ANNOUNCES ITSELF on the emit path" "1" \
    "$([ "$NB" -ge 1 ] && echo 1 || echo 0)"
rm -f "$BLOG"

echo
echo "=== every file in the set, NAMED (DIFF = the rider moved it)"
same=0; diff=0; names=
for f in $REF/lay9b_s1.* $REF/lay9b_s1_*; do
  [ -f "$f" ] || continue
  b=$(basename "$f")
  if [ -f "$OUT/$b" ] && cmp -s "$f" "$OUT/$b"; then
    same=$((same + 1)); echo "    same  $b"
  else
    diff=$((diff + 1)); names="$names $b"; echo "    DIFF  $b"
  fi
done
echo
echo "    vs the committed smoke set: $same identical, $diff differing"
echo "    THE SEVEN, NAMED:$names"
chk "097's 21 identical reproduce" "21" "$same"
chk "097's 7 differing reproduce"  "7"  "$diff"

rm -rf "$OUT"
echo "    the scratch emission directory is removed; tb/scripts/w9 untouched"
ls -d "$OUT" 2>&1 | sed 's/^/    /'

echo
if [ "$FAIL" = 0 ]; then echo "RS_F_RIDER_DIFFNAMES: PASS (0 problem(s))"; else
  echo "RS_F_RIDER_DIFFNAMES: FAIL ($FAIL problem(s))"; fi
exit "$FAIL"
