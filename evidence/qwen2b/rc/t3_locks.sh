#!/usr/bin/env bash
# t3_locks.sh — R-c Task 3's frozen-behaviour locks.
#
# The 0.8B artifacts must regenerate byte-identical with the per-channel
# repack in the tree and SEQ_REPACK unset:
#   lock A  ref/scripts/regen_gate.sh — the 1-chan .e stream + the .txt
#   lock B  the SEQ_NCH=4 .e4 stream, AND its .seq.json
#
# Lock B compares the JSON as well as the stream (review I4): the weight
# plan — the very thing the repack changes — lives in `<p>.seq.json`, which
# is NOT covered by the .seq sha256 the gate hashes.  A base map that moved
# while the record stream happened not to would otherwise pass.
#
# Everything regenerates into a mktemp dir; the committed tb/scripts/w4/
# artifacts are never written.
set -e
cd "$(dirname "$0")/../../.."
# torch-capable interpreter, chosen exactly the way regen_gate.sh chooses it
MODELPY=${MODELPY:-$([ -x /home/cah/.venv/bin/python ] \
  && echo /home/cah/.venv/bin/python || command -v python3)}
export MODELPY
echo "=== t3 locks: $(date -Is)  host=$(hostname)"
echo "  MODELPY = $MODELPY"
echo "  tree    = $(git rev-parse HEAD 2>/dev/null)$(git diff --quiet 2>/dev/null || echo ' +dirty')"
echo "--- lock A: regen_gate.sh (the .e stream + the .txt)"
bash ref/scripts/regen_gate.sh
echo "--- lock B: the 4-chan .e4 stream AND its .seq.json"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cd ref
SEQ_EMIT=$TMP/model_v2_s1.e4 SEQ_PROFILE=epsnorm SEQ_NCH=4 \
  "$MODELPY" gen_model_script.py $TMP/model_v2_s1.txt 1 3 \
  --res-scale=8 --allow-clip
GOT4=$(sha256sum $TMP/model_v2_s1.e4.seq | cut -d' ' -f1)
GOLD4=$(sha256sum ../tb/scripts/w4/model_v2_s1.e4.seq | cut -d' ' -f1)
echo "  e4 got  = $GOT4"
echo "  e4 gold = $GOLD4  (committed tb/scripts/w4/model_v2_s1.e4.seq)"
[ "$GOT4" = "$GOLD4" ] || { echo E4_LOCK_FAIL; exit 1; }
echo "  e4 .seq.json cmp (the WEIGHT PLAN — outside the hashed stream):"
cmp $TMP/model_v2_s1.e4.seq.json ../tb/scripts/w4/model_v2_s1.e4.seq.json \
  || { echo E4_LOCK_FAIL_JSON; exit 1; }
echo "    identical ($(sha256sum ../tb/scripts/w4/model_v2_s1.e4.seq.json \
  | cut -c1-16)…, $(wc -c < ../tb/scripts/w4/model_v2_s1.e4.seq.json) B)"
echo "  e4 .txt cmp:"
cmp $TMP/model_v2_s1.txt ../tb/scripts/w4/model_v2_s1.txt
echo "    identical"
ls -l $TMP/model_v2_s1.e4.seq
echo E4_LOCK_PASS
