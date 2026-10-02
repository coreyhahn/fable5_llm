#!/usr/bin/env bash
# g6_state_rung.sh — the amendment's on-chip SMEM golden, end to end.
#   write the artifact's INITIAL region image verbatim (KV included, which
#   upload_state deliberately does not) -> hash it back against the
#   manifest's state["sha256"] -> run with --skip-weights so the program
#   touches the region and the host does not -> hash all 162,529,280 B back
#   against state["final_sha256"].
set -euo pipefail
cd "$(dirname "$0")/../../.."
PY=/home/cah/.venv/bin/python
P=tb/scripts/w9/model_9b_s1.e4
G=evidence/qwen9b/g6

echo "########## [1] the INITIAL region image, verbatim, and read back"
$PY $G/g6_state.py --prefix $P --write-initial --json $G/018_state_initial.json

echo
echo "########## [2] run it — --skip-weights writes the CSRs and NO region byte"
$PY sw/seq_run.py --prefix $P --four-chan --skip-weights --zero-scratch \
    --out $G/018_run.json

echo
echo "########## [3] the FINAL region image, off the chip"
$PY $G/g6_state.py --prefix $P --readback --json $G/018_state_final.json
