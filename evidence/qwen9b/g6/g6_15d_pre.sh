#!/usr/bin/env bash
# g6_15d_pre.sh — Task 15-D step 0: PRESERVE what the board holds, then
# confirm it is the board we think it is, BEFORE any new chip run.
#
#   bash evidence/qwen9b/run.sh g6/<n>_15d_pre.log \
#        bash evidence/qwen9b/g6/g6_15d_pre.sh <n>
#
# WHY EACH STEP IS HERE
#
#  [1] g6_ident.py --require-calib --expect-version   the netlist word off
#      the silicon.  build_041 = 0xc973c18a; anything else and the whole
#      investigation is about a different chip.
#  [2] g6_residency.py --witness-probe   `0 MISS` means the resident
#      `model_9b_s1` pack is the one the divergent run used.  It REPORTS;
#      the escalation branch uploads nothing from this tool.
#  [3] g6_kv_rows.py --rows 500-525   THE PERISHABLE EVIDENCE.  The KV
#      region is not cleared between sessions, so rows 500..525 on the board
#      right now are still the 526-step session's own — the very rows the
#      divergent decode steps read.  The next chat session overwrites the
#      rows beneath them; these are dumped (sha per row + exponent byte +
#      32 B verbatim) and COMMITTED before anything else touches the board.
#      The whole 155 MiB region is NOT committed — its sha256 is, and the
#      region itself stays on the board (and, if it is ever needed as bytes,
#      `g6_state.py --readback` can re-read it; nothing in this repo stores
#      a 155 MiB image outside tb/scripts/w9/).
#
# Board rails: no reprogram, no flash, no sudo, NOT ONE BYTE WRITTEN to DDR.
# Every step takes the shared lock itself and releases it.  Run ON SNOKE.
set -u
cd "$(dirname "$0")/../../.."
N=${1:?usage: g6_15d_pre.sh <log-number>}
PY=/home/cah/.venv/bin/python
G6=evidence/qwen9b/g6
PFX=tb/scripts/w9/model_9b_s1
export FABLE5_MODEL=9b

echo "########## [1] identity — the netlist word, off the silicon"
$PY -u $G6/g6_ident.py --require-calib --expect-version 0xc973c18a \
    --json $G6/${N}_15d_ident.json
echo "   rc=$?"; echo

echo "########## [2] residency — is the divergent run's weight pack still there?"
$PY -u $G6/g6_residency.py --prefix $PFX.e4 --witness-probe \
    --json $G6/${N}_15d_witness.json
echo "   rc=$?"; echo

echo "########## [3] the KV tail the 526-step session left — rows 500..525"
$PY -u $G6/g6_kv_rows.py --prefix $PFX --rows 500-525 --tag pre-15d \
    --out $G6/${N}_15d_kv_rows_pre.json
echo "   rc=$?"; echo
