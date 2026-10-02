#!/usr/bin/env bash
# r3_5_regen.sh — Task R3-5 step 4: regenerate ONE pinned reorder_e4.py stream
# (r0 / r1 / r2, form B, CSV windows — the recipes of SV1 n32-n36, SR4
# n410-n413, SR11b n1161-n1168) into the SCRATCH directory
# tb/scripts/w9_r3regen/, NEVER onto the pins under tb/scripts/w9/ (plan
# review I-8: the pins are gitignored and consumed by R3-9a / R3-11).
#
#   bash evidence/qwen9b/sr/r3_5_regen.sh <r0|r1|r2> <k 1..4> [--first]
#
# --first REFUSES if the scratch directory already exists, then creates it;
# without it the directory must exist.  Every run asserts that its --out
# resolves OUTSIDE tb/scripts/w9/ (realpath).  The comparison with the pins
# is r3_5_pin_compare.sh (read-only on the pins).  Run ON SNOKE through
# evidence/qwen9b/sr/sr_run.sh.
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
cd "$ROOT" || exit 1
RTL=${1:?usage: r3_5_regen.sh <r0|r1|r2> <k> [--first]}
K=${2:?usage: r3_5_regen.sh <r0|r1|r2> <k> [--first]}
DIR=tb/scripts/w9_r3regen
case "$RTL" in
  r0) STEM=model_9b_s${K}_reordB; RFLAG="" ;;
  r1|r2) STEM=model_9b_s${K}_reordB_${RTL}; RFLAG="--rtl $RTL" ;;
  *) echo "r3_5_regen.sh: rtl must be r0, r1 or r2" >&2; exit 2 ;;
esac
if [ "${3:-}" = "--first" ]; then
  if [ -e "$DIR" ]; then
    echo "r3_5_regen.sh: REFUSING: $DIR exists (the scratch dir must be new)" >&2
    exit 2
  fi
  mkdir "$DIR" || exit 2
  echo "=== created $DIR"
fi
[ -d "$DIR" ] || { echo "r3_5_regen.sh: $DIR missing (run one with --first)" >&2; exit 2; }
OUT=$DIR/$STEM.e4
PINDIR=$(realpath tb/scripts/w9)
OUTDIR=$(realpath "$(dirname "$OUT")")
case "$OUTDIR/" in
  "$PINDIR"/*) echo "r3_5_regen.sh: REFUSING: $OUT resolves under $PINDIR" >&2; exit 2 ;;
esac
echo "=== out $OUT -> $OUTDIR (pins: $PINDIR): outside the pin directory"
FABLE5_MODEL=9b FABLE5_RS_F=7 /home/cah/.venv/bin/python ref/scripts/reorder_e4.py \
    --in tb/scripts/w9/model_9b_s${K}.e4 --out "$OUT" --form B --cost csv \
    $RFLAG --stats
