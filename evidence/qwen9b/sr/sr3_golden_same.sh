#!/usr/bin/env bash
# sr3_golden_same.sh — Task SR3 acceptance 3 (backward compatibility at unit
# level): the vectors of every EXISTING stream are byte-identical between the
# generator at the base commit and the SR3 generator.  Generates both sets
# (4 seeds each) into gitignored scratch dirs and cmp's every file the BASE
# generator writes; files only the SR3 generator writes (.fpolls, .caps.hex,
# the new fmask/fmrsvd/fmimm/haltmask vectors) are listed, not compared.
# Run ON SNOKE through sr_run.sh.   sr3_golden_same.sh <base-commit>
set -u
BASE=${1:?base commit}
PY=/home/cah/.venv/bin/python
ROOT=$(cd "$(dirname "$0")/../../.." && pwd); cd "$ROOT" || exit 1
S=tb/scripts_scratch/sr3_golden; rm -rf "$S"; mkdir -p "$S/base" "$S/new"
git show "$BASE:tb/scripts/gen_seq_unit_vectors.py" > tb/scripts_scratch/sr3_gen_base.py || exit 1
echo "base generator: $BASE sha256 $(sha256sum < tb/scripts_scratch/sr3_gen_base.py | cut -c1-16)"
echo "new  generator: working tree sha256 $(sha256sum < tb/scripts/gen_seq_unit_vectors.py | cut -c1-16)"
for s in 1 2 3 4; do
  # the base copy sits in tb/scripts_scratch (same depth, so its ../../ref
  # and ../../sw resolve as the original's do); tb/scripts goes on its path
  # for gen_layer_script
  PYTHONPATH=tb/scripts $PY tb/scripts_scratch/sr3_gen_base.py "$S/base" $s > /dev/null || exit 1
  $PY tb/scripts/gen_seq_unit_vectors.py "$S/new" $s > /dev/null || exit 1
done
nb=$(ls "$S/base" | wc -l); nsame=0; ndiff=0
for f in $(ls "$S/base"); do
  if cmp -s "$S/base/$f" "$S/new/$f"; then nsame=$((nsame+1))
  else ndiff=$((ndiff+1)); echo "DIFFERS: $f"; fi
done
echo "new-only files: $(cd "$S/new" && ls | while read f; do [ -e "../base/$f" ] || echo "$f"; done | tr '\n' ' ')"
echo "SR3 GOLDEN: $nb base files, $nsame byte-identical, $ndiff differ"
[ $ndiff -eq 0 ]
