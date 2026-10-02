#!/usr/bin/env bash
# sv1_gate.sh — Task SV1: `ref/seq_model.py --gate` on ONE stream against ONE
# set of generator artifacts (run_g4a_seqgate.sh's discipline, with the .seq
# prefix and the --base prefix given separately, because a REORDERED stream
# shares the shipped artifact's .txt / weights / emb / state images).
#
#   bash evidence/qwen9b/ov/sv1_gate.sh <seq-stem> [<base-stem>]
#
# Both stems are relative to tb/scripts/w9 and name the artifact without
# `.e4`; the gate runs on `<seq-stem>.e4` with `--base <base-stem>`
# (default: <seq-stem>).  PASS needs rc 0 AND the `SEQ GATE: PASS` line.
# Run ON SNOKE through evidence/qwen9b/ov/ov_run.sh.
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
cd "$ROOT/ref"
PY=/home/cah/.venv/bin/python
W9=$ROOT/tb/scripts/w9
SEQ=${1:?usage: sv1_gate.sh <seq-stem> [<base-stem>]}
BASE=${2:-$SEQ}
echo "=== interpreter $PY ; seq $W9/$SEQ.e4 ; base $W9/$BASE"
echo "=== seq sha256 $(sha256sum "$W9/$SEQ.e4.seq" | cut -c1-16)"
T0=$(date +%s)
FABLE5_MODEL=9b FABLE5_RS_F=7 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 "$PY" \
    seq_model.py --gate "$W9/$SEQ.e4" --base "$W9/$BASE"
rc=$?
echo "=== gate wall $(( $(date +%s) - T0 ))s rc=$rc"
exit $rc
