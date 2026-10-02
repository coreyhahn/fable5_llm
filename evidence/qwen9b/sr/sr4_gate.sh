#!/usr/bin/env bash
# sr4_gate.sh — Task SR4: `ref/seq_model.py --gate` on ONE r1 stream against
# ONE set of generator artifacts, at the capability set {R1}.  A copy of
# evidence/qwen9b/ov/sv1_gate.sh (run_g4a_seqgate.sh's discipline, the .seq
# prefix and the --base prefix given separately, because a REORDERED stream
# shares the shipped artifact's .txt / weights / emb / state images) that
# passes `--caps R1`: an r1 stream (ref/scripts/reorder_e4.py --rtl r1)
# carries masked FENCEs (docs/SEQ_ISA.md v2.3 B17.1), which the validator
# admits only at caps {R1}.  The model is a software gate: the caps are named
# HERE, by the caller, never read from the stream's manifest.  The
# running-channel refusals (RunningChannelError) stay armed.
#
#   bash evidence/qwen9b/sr/sr4_gate.sh <seq-stem> [<base-stem>]
#
# Both stems are relative to tb/scripts/w9 and name the artifact without
# `.e4`; the gate runs on `<seq-stem>.e4` with `--base <base-stem>`
# (default: <seq-stem>).  PASS needs rc 0 AND the `SEQ GATE: PASS` line.
# Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
cd "$ROOT/ref"
PY=/home/cah/.venv/bin/python
W9=$ROOT/tb/scripts/w9
SEQ=${1:?usage: sr4_gate.sh <seq-stem> [<base-stem>]}
BASE=${2:-$SEQ}
CAPS=R1
echo "=== interpreter $PY ; seq $W9/$SEQ.e4 ; base $W9/$BASE ; caps $CAPS"
echo "=== seq sha256 $(sha256sum "$W9/$SEQ.e4.seq" | cut -c1-64)"
T0=$(date +%s)
FABLE5_MODEL=9b FABLE5_RS_F=7 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 "$PY" \
    seq_model.py --gate "$W9/$SEQ.e4" --base "$W9/$BASE" --caps "$CAPS"
rc=$?
echo "=== gate wall $(( $(date +%s) - T0 ))s rc=$rc"
exit $rc
