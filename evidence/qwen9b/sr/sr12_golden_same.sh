#!/usr/bin/env bash
# sr12_golden_same.sh — Task SR12 backward compatibility at unit level (the
# SR3 method, evidence/qwen9b/sr/sr3_golden_same.sh): every golden file the
# BASE generator writes is byte-identical in the SR12 generator's output —
# EXCEPT <prefix>.caps.hex, which is the RTL-under-test's capability word and
# MUST move (HW.seq_caps_word({"R1"}) -> HW.seq_caps_word({"R1","R2"})): each
# of those is listed with both words and required to be exactly that pair.
# Files only the SR12 generator writes (.xwa, the new bank/error vectors)
# are listed, not compared.  4 seeds each, into gitignored scratch dirs.
# Run ON SNOKE through sr_run.sh.   sr12_golden_same.sh <base-commit>
set -u
BASE=${1:?base commit}
# R3-8 (flags, not copies): the two capability sets the caps.hex must move
# between, comma lists; the defaults are SR12's ({"R1"} -> {"R1","R2"}), so
# every committed SR12 log reproduces unchanged.  R3-8 passes R1,R2 R1,R2,R3.
OLDSET=${2:-R1}; NEWSET=${3:-R1,R2}
PY=/home/cah/.venv/bin/python
ROOT=$(cd "$(dirname "$0")/../../.." && pwd); cd "$ROOT" || exit 1
S=tb/scripts_scratch/sr12_golden; rm -rf "$S"; mkdir -p "$S/base" "$S/new"
git show "$BASE:tb/scripts/gen_seq_unit_vectors.py" > tb/scripts_scratch/sr12_gen_base.py || exit 1
echo "base generator: $BASE sha256 $(sha256sum < tb/scripts_scratch/sr12_gen_base.py | cut -c1-16)"
echo "new  generator: working tree sha256 $(sha256sum < tb/scripts/gen_seq_unit_vectors.py | cut -c1-16)"
for s in 1 2 3 4; do
  PYTHONPATH=tb/scripts $PY tb/scripts_scratch/sr12_gen_base.py "$S/base" $s > /dev/null || exit 1
  $PY tb/scripts/gen_seq_unit_vectors.py "$S/new" $s > /dev/null || exit 1
done
OLDCAPS=$(cd sw && $PY -c "import hwmap; print('%08x' % hwmap.seq_caps_word(set('$OLDSET'.split(','))))")
NEWCAPS=$(cd sw && $PY -c "import hwmap; print('%08x' % hwmap.seq_caps_word(set('$NEWSET'.split(','))))")
[ -n "$OLDCAPS" ] && [ -n "$NEWCAPS" ] || { echo "hwmap caps words not derived"; exit 1; }
echo "caps.hex must move: $OLDCAPS -> $NEWCAPS (hwmap)"
nb=$(ls "$S/base" | wc -l); nsame=0; ndiff=0; ncaps=0; nbadcaps=0
for f in $(ls "$S/base"); do
  case "$f" in
    *.caps.hex)
      o=$(cat "$S/base/$f"); n=$(cat "$S/new/$f" 2>/dev/null)
      if [ "$o" = "$OLDCAPS" ] && [ "$n" = "$NEWCAPS" ]; then ncaps=$((ncaps+1))
      else nbadcaps=$((nbadcaps+1)); echo "CAPS WRONG: $f base $o new $n"; fi ;;
    *)
      if cmp -s "$S/base/$f" "$S/new/$f"; then nsame=$((nsame+1))
      else ndiff=$((ndiff+1)); echo "DIFFERS: $f"; fi ;;
  esac
done
echo "new-only files: $(cd "$S/new" && ls | while read f; do [ -e "../base/$f" ] || echo "$f"; done | tr '\n' ' ')"
echo "SR12 GOLDEN: $nb base files: $nsame byte-identical, $ndiff differ; $ncaps caps.hex moved $OLDCAPS -> $NEWCAPS, $nbadcaps wrong"
[ $ndiff -eq 0 ] && [ $nbadcaps -eq 0 ]
