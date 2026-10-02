#!/usr/bin/env bash
# t3_sw_selftests.sh — the pure-python host gates for R-c Task 3.
# seq_selftest is the gate Task 4/6 run FIRST on a new artifact; since the
# R-c review it also builds a SYNTHETIC REPACKED artifact and runs the whole
# artifact loop over it (write_synth_repack_artifact), so the per-channel
# path is gated rather than merely reachable.
set -e
cd "$(dirname "$0")/../../../sw"
echo "=== t3 sw selftests: $(date -Is)  host=$(hostname)"
echo "  python = $(readlink -f ./.venv/bin/python)"
echo "  tree   = $(git rev-parse HEAD)$(git diff --quiet || echo ' +dirty')"
echo
echo "--- make seq_selftest  (sw/seq_run.py --selftest)"
make seq_selftest
echo
echo "--- make serve_test    (sw/serve.py --selftest)"
make serve_test | tail -3
echo
echo "--- chat_seq.py --selftest"
./.venv/bin/python -u chat_seq.py --selftest | tail -3
