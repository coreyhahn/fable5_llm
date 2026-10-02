#!/usr/bin/env bash
# g6_longctx_rung.sh — the long-context rung: ONE 9B chat session whose
# context passes the retired 512 ceiling, with the KV region read back to
# prove it and the two lane counters bracketing it.
#
#   bash evidence/qwen9b/run.sh g6/<n>_longctx_9b.log \
#        bash evidence/qwen9b/g6/g6_longctx_rung.sh <n>
#
# WHY EACH STEP IS HERE
#
#  [1] g6_state.py --write-initial   the KV region is the ONLY witness that
#      the context really passed 512, and it only means something from a
#      known start: `sw/seq_run.upload_state` and `chat_seq`'s context reset
#      both leave KV alone by design (TCNT is 0 after a reset, so no KV row
#      is read before it is written).  This writes `<base>.state.bin`
#      VERBATIM — KV included, i.e. zeroed — and hashes it back.
#  [2] g6_kv_depth.py --tag before   the control: 0 non-zero rows.
#  [3] g6_lane_counters.py --clear   `chat_seq` never writes L_LCYC /
#      L_SDMA_CYC, so clearing here and reading in [5] brackets exactly the
#      session.
#  [4] the session itself.  The prompt is 16 copies of one sentence after a
#      one-line instruction, which renders to 503 templated ids; with
#      --ntok 24 that is 502 prefill + 24 decode = 526 forward steps, the
#      smallest round total that clears 512 by a comfortable margin.
#  [5] g6_kv_depth.py --tag after    the deepest KV row the silicon wrote.
#  [6] g6_lane_counters.py --read    the two lanes and the state traffic.
#
# Board rails: no reprogram, no flash, no sudo; every step takes the shared
# lock itself and releases it.  Run ON SNOKE.
set -u
cd "$(dirname "$0")/../../.."
N=${1:?usage: g6_longctx_rung.sh <log-number>}
PY=/home/cah/.venv/bin/python
G6=evidence/qwen9b/g6
PFX=tb/scripts/w9/model_9b_s1
export FABLE5_MODEL=9b

SENT="The city of Paris grew from a settlement on an island in the Seine, and its streets, bridges and markets were rebuilt many times over the centuries. "
PROMPT="Summarise the following passage in one sentence. "
for _ in $(seq 16); do PROMPT="$PROMPT$SENT"; done

echo "########## [1] the INITIAL state region, verbatim (KV zeroed)"
$PY -u $G6/g6_state.py --prefix $PFX.e4 --write-initial \
    --json $G6/${N}_longctx_state_initial.json
echo "   rc=$?"; echo

echo "########## [2] KV depth BEFORE — the control"
$PY -u $G6/g6_kv_depth.py --prefix $PFX --tag before \
    --out $G6/${N}_longctx_kv_before.json
echo "   rc=$?"; echo

echo "########## [3] the lane counters, cleared"
$PY -u $G6/g6_lane_counters.py --clear
echo "   rc=$?"; echo

A=$(mktemp); B=$(mktemp)
echo "########## [4] the session: 526 forward steps, context 526 > 512"
echo "           prompt = 1 instruction + 16 x the passage sentence"
$PY -u sw/chat_seq.py --nch 4 --max-ctx 700 --ntok 24 \
    --prompt "$PROMPT" --out $G6/${N}_longctx_chat.json | tee "$A"
echo "   rc=${PIPESTATUS[0]}"; echo

echo "########## [5] KV depth AFTER"
$PY -u $G6/g6_kv_depth.py --prefix $PFX --tag after \
    --out $G6/${N}_longctx_kv_after.json
echo "   rc=$?"; echo

echo "########## [6] the two lanes, and the state traffic at this T"
$PY -u $G6/g6_lane_counters.py --read --steps 526 --tokens 24 --t 526 \
    --out $G6/${N}_longctx_lanes.json
echo "   rc=$?"; echo

echo "########## [7] the SAME session again — determinism on silicon"
$PY -u sw/chat_seq.py --nch 4 --max-ctx 700 --ntok 24 \
    --prompt "$PROMPT" --out $G6/${N}_longctx_chat_b.json | tee "$B"
echo "   rc=${PIPESTATUS[0]}"; echo
echo "  run A ids: $(tr -d '\r' < "$A" | grep -m1 '^  ids ')"
echo "  run B ids: $(tr -d '\r' < "$B" | grep -m1 '^  ids ')"
if [ "$(tr -d '\r' < "$A" | grep -m1 '^  ids ')" = "$(tr -d '\r' < "$B" | grep -m1 '^  ids ')" ] \
   && [ -n "$(tr -d '\r' < "$A" | grep -m1 '^  ids ')" ]; then
  echo "  LONGCTX DETERMINISM: IDENTICAL"
else
  echo "  LONGCTX DETERMINISM: DIFFERS"
fi
rm -f "$A" "$B"
