#!/usr/bin/env bash
# g6_i2_green.sh — the GREEN half of round-3 I-1/I-2, on the COMMITTED tree.
#
#  [1] sw/chat_seq.py --selftest        (0.8b: the FROZEN --nch 1 path)
#  [2] ref/seq_chat.py --selftest       (agent A's own suite)
#  [3] sw/seq_run.py + sw/hwmap.py --selftest — untouched, the controls
#  [4] the frozen --nch 1 footprint at HEAD: it must be 4662b06's, byte
#      for byte (108 printed both trees' numbers)
#  [5] T_MAX at both selections, from the constants themselves
#  [6] m15: what SeqModelVerifier.state_region costs per context reset —
#      the sha256 of <base>.state.bin plus StateRegion.load, twice
#
# NO BOARD, NO LOCK, NO DMA.  Run ON SNOKE through evidence/qwen9b/run.sh.
set -u
cd "$(dirname "$0")/../../.."
PY=/home/cah/.venv/bin/python
G6=evidence/qwen9b/g6
TPL=/home/cah/r2d2/code/fpga/fable5_llm/tb/scripts/w4/model_v2_s1.e

echo "########## [1] sw/chat_seq.py --selftest  (FABLE5_MODEL unset = 0.8b)"
$PY -u sw/chat_seq.py --selftest 2>&1 | grep -E "^  \[|FAIL|passed," | tail -30
echo "   rc=${PIPESTATUS[0]}"; echo

echo "########## [2] ref/seq_chat.py --selftest"
$PY -u ref/seq_chat.py --selftest 2>&1 | tail -3
echo "   rc=${PIPESTATUS[0]}"; echo

echo "########## [3] the untouched controls"
$PY -u sw/seq_run.py --selftest 2>&1 | tail -2
echo "   rc=${PIPESTATUS[0]}"
$PY -u sw/hwmap.py --selftest 2>&1 | tail -2
echo "   rc=${PIPESTATUS[0]}"; echo

echo "########## [4] the frozen --nch 1 footprint at HEAD"
$PY -u $G6/g6_frozen_footprint.py --template $TPL
echo "   rc=$?"; echo

echo "########## [5] T_MAX at both selections"
for M in 0.8b 2b 9b; do
  FABLE5_MODEL=$M $PY -c "
import sys; sys.path[:0] = ['sw', 'ref']
import seq_chat as SC, model_select as MS
print(f'  FABLE5_MODEL={MS.TAG:5s} seq_chat.T_MAX={SC.T_MAX:5d}  '
      f'POS_STRIDE={SC.POS_STRIDE}  pool={SC.T_MAX * SC.POS_STRIDE} B  '
      f'XRF_POS_MAX={SC.XRF_POS_MAX}')"
done
echo "   rc=$?"; echo

echo "########## [6] m15: the per-context-reset cost of state_region()"
FABLE5_MODEL=9b $PY -u - <<'PYEOF'
import os
import sys
import time
sys.path[:0] = ["sw", "ref"]
import chat_seq as C
import seq_run as SR
import seq_model as SM


class _S(object):
    pass


base = SR.derive_base(C.TEMPLATE4_PREFIX)
s = _S()
s.base = base
s.state = None
import json
meta = json.load(open(base + ".weights.json"))
s.state = meta.get("state")
sz = os.path.getsize(base + ".state.bin")
print(f"  image      {os.path.basename(base)}.state.bin  {sz} B "
      f"= {sz / 2**20:.1f} MiB  (on NFS)")
for i in (1, 2):
    t0 = time.monotonic()
    SR.verify_state_image(s)
    t1 = time.monotonic()
    reg = SM.StateRegion.load(base)
    t2 = time.monotonic()
    print(f"  reset {i}    verify_state_image {t1 - t0:6.2f}s  "
          f"StateRegion.load {t2 - t1:6.2f}s  total {t2 - t0:6.2f}s"
          f"  ({2 * sz / 2**20:.0f} MiB read)")
print("M15 COST: PRINTED")
PYEOF
echo "   rc=$?"
