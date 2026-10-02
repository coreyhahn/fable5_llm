#!/usr/bin/env bash
# t4_bytes_unmoved.sh — did the R-c ALU widening change any EMITTED BYTE?
#
# It should not.  `Mach.alu` always packed `op | (n << 4)` UNMASKED, so the
# 2B stream already carried ARG0 = 0x18000; what changed is that the RTL now
# DECODES bit 16 instead of dropping it, and that both emitters and the
# golden now refuse a count they cannot encode.  Asserts do not move bytes.
#
# That matters for the gate table: if it holds, RC_GATE section 2's artifact
# shas STAND and the 2B set does not need regenerating.  So prove it rather
# than assert it — regenerate the 1-layer 2B W8 smoke (the cheapest artifact
# that carries the 6144-element DYNQ8) into a temp dir and cmp.
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
PY=${MODELPY:-/home/cah/.venv/bin/python}
cd "$ROOT" || exit 1
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

SEED=${SEED:-1}
OLD=tb/scripts/w5/lay2b_w8_s$SEED
echo "gold: $OLD.* (emitted BEFORE the widening, 2026-08-22T12:48)"
[ -f "$OLD.txt" ] || { echo "gold artifact missing -- regenerate first"; exit 1; }

( cd ref && FABLE5_MODEL=2b SEQ_PROFILE=epsnorm SEQ_NCH=4 SEQ_REPACK=1 \
    SEQ_EMIT=$TMP/lay.e "$PY" gen_layer_script.py "$TMP/lay.txt" "$SEED" 2 \
    --wq=w8 ) || exit 1

rc=0
for ext in txt e.seq e.seq.json e.seqdata.bin; do
  if cmp -s "$TMP/lay.$ext" "$OLD.$ext"; then
    echo "  IDENTICAL  .$ext  ($(wc -c < "$OLD.$ext") B)"
  else
    echo "  *** DIFFERS *** .$ext"
    rc=1
  fi
done
# .weights.json carries each image's FILENAME, which differs by prefix
# between the temp regeneration and the gold set.  Normalise that one field
# (and only it) before comparing; everything else must match exactly.
if diff -q \
     <(sed "s/lay_w/PFX_w/g"                    "$TMP/lay.weights.json") \
     <(sed "s/lay2b_w8_s$SEED""_w/PFX_w/g"      "$OLD.weights.json") \
     >/dev/null; then
  echo "  IDENTICAL  .weights.json  (image filenames normalised)"
else
  echo "  *** DIFFERS *** .weights.json (beyond the filename prefix)"
  rc=1
fi
# the weight images too (same quantizer, same packer)
nd=0
for f in "$OLD"_w*.bin; do
  b=$(basename "$f" | sed "s/^lay2b_w8_s$SEED/lay/")
  cmp -s "$TMP/$b" "$f" || { echo "  *** DIFFERS *** $b"; nd=$((nd+1)); rc=1; }
done
echo "  weight images: $(ls "$OLD"_w*.bin | wc -l) compared, $nd differ"
echo
if [ "$rc" = 0 ]; then
  echo "BYTES_UNMOVED PASS — the widening changed no emitted byte;"
  echo "RC_GATE section 2's artifact shas stand, no regeneration needed."
else
  echo "BYTES_UNMOVED FAIL — the artifact set must be regenerated and"
  echo "RC_GATE section 2's shas updated."
fi
exit $rc
