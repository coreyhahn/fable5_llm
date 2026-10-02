#!/usr/bin/env bash
# sr_chipvec.sh — the SEQUENCER RTL ROUND (Task SR5b onward): the chip-TB
# golden (`<seq>.e4.chip`) of an r1 (or later) REORDERED stream.  A copy of
# evidence/qwen9b/ov/sv1_chipvec.sh, changed in two places only:
#   * a third argument names the capability set the stream is validated and
#     executed at (`R1` for an r1 stream with masked FENCEs; SEQ_ISA v2.3
#     B17.0), passed to the generator's `--caps` (tb/scripts/gen_seq_chip_vectors.py,
#     SR5b addition; default empty = every earlier invocation unchanged);
#   * the verdict line says SR_CHIPVEC.
# sv1_chipvec.sh's header follows: the campaign's own generator
# (tb/scripts/gen_seq_chip_vectors.py, `seq_chip_vectors_9b`'s recipe) with
# `--no-wimg`: the per-channel weight images belong to the shipped artifact
# (--base) and are NOT rewritten.  Then the new golden is compared line by
# line with the SHIPPED artifact's golden: only NREC and PC (the stream is
# longer or shorter) may differ — tokens, XRF, TCNT, EOUT/AMAX, every scratch
# word and every state block must be identical.
#
#   bash evidence/qwen9b/sr/sr_chipvec.sh <seq-stem> <base-stem> <caps>
#
# Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
PY=/home/cah/.venv/bin/python
SEQ=${1:?usage: sr_chipvec.sh <seq-stem> <base-stem> <caps>}
BASE=${2:?usage: sr_chipvec.sh <seq-stem> <base-stem> <caps>}
CAPS=${3:?usage: sr_chipvec.sh <seq-stem> <base-stem> <caps> (e.g. R1)}
cd "$ROOT/tb" || exit 1
W9=scripts/w9
[ -e "$W9/$SEQ.e4.chip" ] && { echo "REFUSING: $W9/$SEQ.e4.chip exists"; exit 2; }
echo "=== seq  $W9/$SEQ.e4.seq sha256 $(sha256sum "$W9/$SEQ.e4.seq" | cut -d' ' -f1)"
echo "=== base $W9/$BASE   caps $CAPS"
T0=$(date +%s)
FABLE5_MODEL=9b FABLE5_RS_F=7 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 "$PY" \
    scripts/gen_seq_chip_vectors.py "$W9/$SEQ.e4" --base "$W9/$BASE" --no-wimg \
    --caps "$CAPS"
rc=$?
echo "=== generator wall $(( $(date +%s) - T0 ))s rc=$rc"
[ "$rc" = 0 ] || exit "$rc"
echo "=== golden $W9/$SEQ.e4.chip sha256 $(sha256sum "$W9/$SEQ.e4.chip" | cut -d' ' -f1)"
echo "--- vs the shipped golden $W9/$BASE.e4.chip (lines differing, by key):"
diff <(sort "$W9/$BASE.e4.chip") <(sort "$W9/$SEQ.e4.chip") \
  | grep '^[<>]' | awk '{print $1, $2}' | sort | uniq -c
BAD=$(diff <(grep -v -E '^(NREC|PC) ' "$W9/$BASE.e4.chip") \
           <(grep -v -E '^(NREC|PC) ' "$W9/$SEQ.e4.chip") | grep -c '^[<>]')
echo "    NREC/PC: $(grep -E '^(NREC|PC) ' "$W9/$BASE.e4.chip" | tr '\n' ' ') -> $(grep -E '^(NREC|PC) ' "$W9/$SEQ.e4.chip" | tr '\n' ' ')"
echo "    lines other than NREC/PC that differ: $BAD"
grep '^TOK ' "$W9/$SEQ.e4.chip" | tr '\n' ' '; echo
if [ "$BAD" = 0 ]; then echo "SR_CHIPVEC $SEQ: GOLDEN IDENTICAL TO SHIPPED (except NREC/PC)"; exit 0
else echo "SR_CHIPVEC $SEQ: GOLDEN DIFFERS FROM SHIPPED"; exit 1; fi
