#!/usr/bin/env bash
# t3_audit_prod.sh — the R-c address audit at PRODUCTION shape (187 images).
#
# Emits the 0.8B model script a SECOND time with the per-channel repack ON
# (SEQ_NCH=4 SEQ_REPACK=1, to a TEMP prefix — the frozen w4/ artifacts are
# never touched), then audits BOTH packs with evidence/qwen2b/rc/t3_audit.py:
# host-written spans == engine-read spans on every channel, the ILV head in
# GLOBAL row terms, and the three address mutations killed.
set -e
cd "$(dirname "$0")/../../.."
PY=${MODELPY:-$([ -x /home/cah/.venv/bin/python ] \
  && echo /home/cah/.venv/bin/python || command -v python3)}
echo "t3_audit_prod: $(date -Is)  host=$(hostname)"
echo "  python = $PY"
echo "  tree   = $(git rev-parse HEAD 2>/dev/null)$(git diff --quiet 2>/dev/null || echo ' +dirty')"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
( cd ref && SEQ_EMIT=$TMP/model_v2_s1.er SEQ_PROFILE=epsnorm SEQ_NCH=4 \
    SEQ_REPACK=1 "$PY" gen_model_script.py $TMP/model_v2_s1.txt 1 3 \
    --res-scale=8 --allow-clip ) 2>&1 | tail -3
echo
"$PY" evidence/qwen2b/rc/t3_audit.py \
  "$TMP/model_v2_s1.er" tb/scripts/w4/model_v2_s1.e4
