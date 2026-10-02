#!/usr/bin/env bash
# g6_longctx_lanes.sh — the long-context rung's MISSING half.
#
#   bash evidence/qwen9b/run.sh g6/<n>_longctx_lanes.log \
#        bash evidence/qwen9b/g6/g6_longctx_lanes.sh <n>
#
# `evidence/qwen9b/g6/083_longctx_9b.log` ran the 526-step session, proved
# the KV region carries row 525, and then LOST both lane counters: steps [3]
# and [6] died in `sw/seq_run.Dev` on `/dev/xdma0_user_user`, because
# `g6_lane_counters.py`'s `--dev` default was a device node where `Dev` wants
# the stem.  That default is fixed; this re-runs the SAME session with the
# counters bracketing it, and settles the determinism question `083` step [7]
# botched (its comparison included the wall-clock suffix, so two identical
# token lists printed `DIFFERS` — the two `ids [...]` lines in `083` are
# byte-identical and this script compares the LISTS).
#
# The state region is NOT re-initialised here: `083` left it post-run, and
# `chat_seq`'s own bring-up + context reset put DN and the conv taps back,
# which is exactly the path a second session takes in normal use.  The KV
# region is never read before it is written (TCNT 0 after a reset), so the
# tokens must reproduce anyway — and that is the claim.
#
# Board rails: shared lock per step, no reprogram, no flash, no sudo.
set -u
cd "$(dirname "$0")/../../.."
N=${1:?usage: g6_longctx_lanes.sh <log-number>}
PY=/home/cah/.venv/bin/python
G6=evidence/qwen9b/g6
export FABLE5_MODEL=9b

SENT="The city of Paris grew from a settlement on an island in the Seine, and its streets, bridges and markets were rebuilt many times over the centuries. "
PROMPT="Summarise the following passage in one sentence. "
for _ in $(seq 16); do PROMPT="$PROMPT$SENT"; done

echo "########## [1] the lane counters, cleared"
$PY -u $G6/g6_lane_counters.py --clear
echo "   rc=$?"; echo

C=$(mktemp)
echo "########## [2] the SAME 526-step session (run C)"
$PY -u sw/chat_seq.py --nch 4 --max-ctx 700 --ntok 24 \
    --prompt "$PROMPT" --out $G6/${N}_longctx_chat_c.json 2>&1 \
  | grep -vE '^  prefill [0-9]+/' | tee "$C"
echo "   rc=${PIPESTATUS[0]}"; echo

echo "########## [3] the two lanes over that session, and the traffic at T"
$PY -u $G6/g6_lane_counters.py --read --steps 527 --tokens 24 --t 526 \
    --out $G6/${N}_longctx_lanes.json
echo "   rc=$?"; echo

echo "########## [4] determinism — the TOKEN LISTS, run A vs run B vs run C"
$PY - "$G6/083_longctx_9b.log" "$C" <<'EOF'
import re, sys
def ids(path):
    out = []
    for line in open(path, errors="replace").read().replace("\r", "\n").split("\n"):
        m = re.match(r"^  ids (\[[0-9, ]+\])", line)
        if m:
            out.append(m.group(1))
    return out
a = ids(sys.argv[1])
c = ids(sys.argv[2])
for i, v in enumerate(a):
    print(f"  083 run {chr(65+i)}: {v}")
for v in c:
    print(f"  this run C: {v}")
allv = a + c
ok = len(allv) >= 2 and len(set(allv)) == 1
print(f"  {len(allv)} run(s) of the same 526-step context")
print("LONGCTX DETERMINISM: " + ("IDENTICAL" if ok else "DIFFERS"))
raise SystemExit(0 if ok else 1)
EOF
echo "   rc=$?"; echo
rm -f "$C"
