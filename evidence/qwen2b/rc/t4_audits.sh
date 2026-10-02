#!/usr/bin/env bash
# t4_audits.sh — the R-c Task-4 artifact audits, run on the REAL 2B W8
# repacked artifact set (tb/scripts/w5/model_w8_2b_s1).
#
#   1. t3_audit.py    RANGE EQUALITY per channel + the mutation kills, at
#                     the production 187-image / 4-channel / W8 shape.  This
#                     is what the R-c review built the audit FOR.
#   2. the sha256 manifest of the artifact set (the artifacts themselves are
#      regenerable and stay uncommitted; the hashes are the evidence).
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
PY=${MODELPY:-/home/cah/.venv/bin/python}
BASE=${BASE:-tb/scripts/w5/model_w8_2b_s1}
cd "$ROOT" || exit 1

echo "=== 1. t3_audit.py on the 2B W8 repacked stream"
FABLE5_MODEL=2b "$PY" evidence/qwen2b/rc/t3_audit.py "$BASE.e"
rc=$?
echo "t3_audit rc=$rc"

echo
echo "=== 2. sha256 manifest of the artifact set"
( cd "$(dirname "$BASE")" && b=$(basename "$BASE") \
  && ls -la "$b".txt "$b".emb.bin "$b".weights.json "$b".e.seq \
       "$b".e.seq.json "$b".e.seqdata.bin 2>/dev/null \
  && echo "--- sha256 (stream + manifest + script + emb) ---" \
  && sha256sum "$b".e.seq "$b".e.seq.json "$b".e.seqdata.bin \
       "$b".weights.json "$b".txt "$b".emb.bin \
  && echo "--- 187 weight images: count, total bytes, sha256 OF THE SHA LIST ---" \
  && ls "$b"_w*.bin | wc -l \
  && du -cb "$b"_w*.bin | tail -1 \
  && sha256sum "$b"_w*.bin | sha256sum )
echo "=== done: $(date -Is)"
exit $rc
