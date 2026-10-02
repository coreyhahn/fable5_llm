#!/usr/bin/env bash
# bm1_chat511.sh — BM1-T4: the spec §5.1 session (the committed 16-copy
# long-context prompt, built exactly as evidence/qwen9b/g6/g6_longctx_rung.sh:38-40)
# at --max-ctx 511 --ntok 9, through bm1_census.py --chat (lanes + TCNT + B16
# per launch).  Extra chat_seq args (e.g. --reorder A) follow the JSON path.
#   bash evidence/qwen9b/bm/bm1_chat511.sh <json-out> [chat_seq args...]
# Run ON SNOKE through evidence/qwen9b/bm/bm_run.sh.  FABLE5_MODEL=9b is set
# here; FABLE5_SEQ_EXPECT_VERSION is taken from the caller's environment.
# Fix round 1 (I2): $BM1_WANT_IDS (a comma list, e.g. the pinned reference
# 760,20438,18253,5134,421,279,3177,314,11751) is passed as --want-ids, so
# the run exits non-zero on any token difference.
set -u
cd "$(dirname "$0")/../../.."
OUT=${1:?usage: bm1_chat511.sh <json-out> [chat_seq args...]}; shift
export FABLE5_MODEL=9b
SENT="The city of Paris grew from a settlement on an island in the Seine, and its streets, bridges and markets were rebuilt many times over the centuries. "
PROMPT="Summarise the following passage in one sentence. "
for _ in $(seq 16); do PROMPT="$PROMPT$SENT"; done
echo "=== prompt sha256 $(printf '%s' "$PROMPT" | sha256sum | cut -c1-16)  (${#PROMPT} chars)"
WANT=()
if [ -n "${BM1_WANT_IDS:-}" ]; then WANT=(--want-ids "$BM1_WANT_IDS"); fi
echo "=== want-ids: ${BM1_WANT_IDS:-unset}"
exec /home/cah/.venv/bin/python -u evidence/qwen9b/bm/bm1_census.py --chat --json "$OUT" "${WANT[@]}" -- \
    --nch 4 --max-ctx 511 --ntok 9 --prompt "$PROMPT" "$@"
