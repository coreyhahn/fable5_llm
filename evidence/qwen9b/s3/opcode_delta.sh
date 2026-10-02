#!/usr/bin/env bash
# opcode_delta.sh — the layerv2_s1 command census, pre-S3 vs S3.
#
#   sh evidence/qwen9b/s3/opcode_delta.sh
#
# S3 retires the CONVW/CONVZ preamble and the 768 DNZ and adds SLD/SST, so
# `tb_layer_chan`'s command count moves and its CHECK count must not.  This
# re-emits the pre-S3 script from a copy of `ref/gen_layer_script.py` and
# `ref/seq_format.py` at `07eea51` (the tree S3 started from) and histograms
# both scripts' opcodes, so the delta is measured rather than reasoned.
#
# The pre-S3 copy lives under `tb/scripts_scratch/` (gitignored) with the
# rest of `ref/` symlinked beside it and `07eea51`'s `sw/hwmap.py` on the
# path; `PRE_DIR` overrides it.  MUST run on snoke: it EMITS (S3 fix round
# 1, C1 — no numeric emission on darthplagueis).
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
PRE=${PRE_DIR:-$ROOT/tb/scripts_scratch/refold_s3}
OUT=${OUT_DIR:-$ROOT/tb/scripts_scratch/opdelta}
MODELPY=${MODELPY:-$([ -x /home/cah/.venv/bin/python ] && echo /home/cah/.venv/bin/python \
                     || echo "$ROOT/ref/.venv/bin/python")}
NEW=$ROOT/tb/scripts/layerv2_s1.txt
mkdir -p "$OUT"
echo "opcode_delta: host=$(hostname)  MODELPY=$MODELPY"
echo "  pre-S3 generator copy: $PRE  (07eea51)"
echo "  S3 script:             $NEW"

hist() { /usr/bin/grep "^C " "$1" | awk '{print $2}' | sort -n | uniq -c | sort -k2 -n; }
cnt()  { /usr/bin/grep -c "^C " "$1"; }

( cd "$PRE" && PYTHONPATH="$PRE/sw" FABLE5_MODEL=9b FABLE5_RS_F=7 \
    "$MODELPY" gen_layer_script.py "$OUT/pre_s1.txt" 1 ) || exit 1
echo
echo "=== pre-S3 (07eea51), cmds=$(cnt "$OUT/pre_s1.txt")"
hist "$OUT/pre_s1.txt"
echo "=== S3, cmds=$(cnt "$NEW")"
hist "$NEW"
echo
echo "op 5 = CONVW/CONVZ, 12 (c) = DNZ, 13 (d) = SLD, 14 (e) = SST"
PRE_N=$(cnt "$OUT/pre_s1.txt"); NEW_N=$(cnt "$NEW")
RET=$(( $(/usr/bin/grep -c "^C 5 " "$OUT/pre_s1.txt") \
        + $(/usr/bin/grep -c "^C c " "$OUT/pre_s1.txt") ))
ADD=$(( $(/usr/bin/grep -c "^C d " "$NEW") + $(/usr/bin/grep -c "^C e " "$NEW") ))
echo "RETIRED: $RET (op5 CONVW/CONVZ + op12 DNZ)   ADDED: $ADD (SLD + SST)"
echo "$PRE_N - $RET + $ADD = $(( PRE_N - RET + ADD ))   measured S3 = $NEW_N"
if [ $(( PRE_N - RET + ADD )) = "$NEW_N" ]; then
  echo "OPCODE_DELTA: PASS ($PRE_N -> $NEW_N accounted for exactly)"
else
  echo "OPCODE_DELTA: FAIL"; exit 1
fi
