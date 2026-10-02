#!/usr/bin/env bash
# g6_15d_chip.sh — Task 15-D: ONE chip run of the divergent prompt, or of a
# BODY-TRUNCATED copy of it, with the lane counters bracketing it and the KV
# rows around the prompt end read back afterwards.
#
#   bash evidence/qwen9b/run.sh g6/<n>_15d_<tag>.log \
#        bash evidence/qwen9b/g6/g6_15d_chip.sh <n> <copies> <ntok> <tag>
#
# THE PROMPT IS `g6_longctx_rung.sh`'s, CHARACTER FOR CHARACTER — the same
# instruction line and the same sentence, repeated <copies> times instead of
# 16.  Truncating at whole sentences is what "cut at token boundaries" means
# here: every copy is the same id sequence, so k copies is a prefix of 16
# copies in id space and the templated wrapper (12 ids) is untouched.
# `chat_seq.py` prints the id count it actually templated and the run's JSON
# records it, so the exact N is a fact of the log and not of this header.
#
# WHY EACH STEP IS HERE
#  [1] lane counters --clear   `chat_seq` never writes them, so a clear here
#      and a read in [3] bracket exactly this session.  §14.5: L_LCYC wraps
#      at ~420 launches of this program, so a short run's reading is a
#      measurement and a 500-step one's is not — the step prints both the
#      reading and the launch count so the reader can tell which it has.
#  [2] the session itself, greedy, --nch 4, --max-ctx 700.
#  [3] the two lanes over exactly that session.
#  [4] g6_kv_rows.py over rows N-2..N+3, where N is the templated id count
#      this run's own JSON records: N-1 is the last prefill position, N-1 is
#      decode 1's position and N is decode 2's — the step that diverged at
#      N = 503.  Rows above the run's own depth are LEFTOVERS from whatever
#      session ran before it (the KV region is never cleared between
#      sessions) and mean nothing; the rows the run wrote are the evidence.
#
# Board rails: no reprogram, no flash, no sudo; every step takes the shared
# lock itself and releases it.  Run ON SNOKE.
set -u
cd "$(dirname "$0")/../../.."
N=${1:?usage: g6_15d_chip.sh <log-number> <copies> <ntok> <tag>}
COPIES=${2:?copies of the passage sentence}
NTOK=${3:?tokens to decode}
TAG=${4:?short tag for the artifact names}
PY=/home/cah/.venv/bin/python
G6=evidence/qwen9b/g6
PFX=tb/scripts/w9/model_9b_s1
export FABLE5_MODEL=9b

# g6_longctx_rung.sh's two strings, verbatim.
SENT="The city of Paris grew from a settlement on an island in the Seine, and its streets, bridges and markets were rebuilt many times over the centuries. "
PROMPT="Summarise the following passage in one sentence. "
for _ in $(seq "$COPIES"); do PROMPT="$PROMPT$SENT"; done

JSON=$G6/${N}_15d_chip_${TAG}.json

echo "########## [1] the lane counters, cleared"
$PY -u $G6/g6_lane_counters.py --clear
echo "   rc=$?"; echo

echo "########## [2] the session: $COPIES x the passage sentence, --ntok $NTOK"
$PY -u sw/chat_seq.py --nch 4 --max-ctx 700 --ntok "$NTOK" \
    --prompt "$PROMPT" --out "$JSON"
echo "   rc=$?"; echo

LAUNCH=$($PY -c "import json,sys; r=json.load(open(sys.argv[1])); print(r['launches'])" "$JSON" 2>/dev/null || echo 0)
CTX=$($PY -c "import json,sys; r=json.load(open(sys.argv[1])); print(r['context'])" "$JSON" 2>/dev/null || echo 0)
# context = nids + ntok - 1  (nids-1 prefill launches + ntok decode steps)
NIDS=$((CTX - NTOK + 1))
echo "  derived    launches=$LAUNCH context=$CTX ntok=$NTOK -> templated ids N=$NIDS"
echo "             decode 1 is position $((NIDS - 1)), decode 2 is position $NIDS"
echo

echo "########## [3] the two lanes over exactly this session"
$PY -u $G6/g6_lane_counters.py --read --steps "$LAUNCH" --tokens "$NTOK" \
    --t "$CTX" --out $G6/${N}_15d_lanes_${TAG}.json
echo "   rc=$?"; echo

LO=$((NIDS - 2)); HI=$((NIDS + 3))
echo "########## [4] the KV rows around the prompt end — $LO..$HI"
$PY -u $G6/g6_kv_rows.py --prefix $PFX --rows ${LO}-${HI} \
    --tag "chip-${TAG}" --out $G6/${N}_15d_kv_rows_${TAG}.json
echo "   rc=$?"; echo
