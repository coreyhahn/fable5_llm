#!/usr/bin/env bash
# Track L — the fixed-point fidelity harness at one geometry / one point.
# RUN FROM SNOKE.
#
#   bash evidence/qwen_next/ladder/run_fidelity.sh <tag> golden
#   bash evidence/qwen_next/ladder/run_fidelity.sh <tag> w8g128
#   bash evidence/qwen_next/ladder/run_fidelity.sh <tag> w4g128|w4g64|w4g128gptq|w4g64gptq
#
# Settings match the 2B W8 run on record
# (`evidence/qwen2b/rc/t4_11_fidelity_2b_w8.log`) on the metric that carries
# the comparison: `--ntok 24` = 27 teacher-forced steps x 4 prompts = 108, on
# the same four committed prompts, so the top-1/108 column is directly
# comparable with 2B's.
#
# TWO deliberate differences, both stated because they are visible in the logs:
#  * `--free-ntok 12` instead of 24.  The free-run pass is a readability check,
#    not a scored metric, and 12 is the PRODUCTION setting on record
#    (`ref/fidelity_check.py` docstring: "--res-scale 8 --free-ntok 12").  At
#    9B a step costs ~85 s, so 24 free tokens would add ~1.1-1.2 h per point
#    for no extra scored number.  MEASURED after the fact from both 9B runs:
#    89.05 s/step at W8 (14,960.0 s / 168 steps) and 81.13 s/step at W4+GPTQ
#    (13,630.5 s / 168).  The ~120 s figure was an estimate and was 35-48%
#    high.  NOTE the denominator: a run executes 168 steps, not 156 --
#    4 prompts x (4 prompt tokens + ntok - 1) = 108 teacher-forced, PLUS
#    4 x (4 + free_ntok - 1) = 60 free-running.  Only the 108 are scored;
#    `resid_clip` runs over all 168; **`s_sat` does NOT** -- it is captured
#    BEFORE the free-run pass, so every committed `s_sat` figure (the 4,392
#    on record included) is a 108-STEP count and must not be compared with
#    an all-168 number.  (Clause added 2026-09-10; the line read "the
#    resid_clip / s_sat counters run over all 168".)
#  * RES_SCALE is a per-geometry argument, not a constant.  0.8B ships S=8, the
#    2B campaign RULED S=4 (§6.2: S=8 rails the int16 residual at H=2048), and
#    the 9B smoke on record here (`fidelity_9b_w8_SMOKE*.log`) shows S=4 rails
#    at H=4096 too.  Pass the right one; do not inherit 2B's.
RES_SCALE=${RES_SCALE:-4}
#
# 4B is REFUSED up front by `fidelity_check.check_norm_geometry`: H=2560 is
# not a power of two and the fixed-point normalizer has no representation for
# it (feasibility §2.3, wall 2).  That refusal is the measurement.
set -u
cd "$(dirname "$0")/../../.."
TAG=$1; POINT=$2
D=evidence/qwen_next/ladder
CACHE=$D/golden_bf16_${TAG}.npz
UV="$HOME/.local/bin/uv run --no-project --with numpy --with torch --with transformers python -u"

if [ "$POINT" = "golden" ]; then
  FABLE5_MODEL=$TAG nice -n 10 $UV ref/fidelity_check.py --golden --ntok 24 \
    --cache $CACHE > $D/golden_${TAG}.log 2>&1
  echo "golden $TAG -> $CACHE ($(tail -1 $D/golden_${TAG}.log))"
  exit 0
fi

OUT=$D/fixed_${TAG}_${POINT}
case "$POINT" in
  w8g128)      ARGS="--w8 --wire-group 128"; unset FABLE5_CALIB_STATS ;;
  w4g128)      ARGS="--wire-group 128" ;;
  w4g64)       ARGS="--wire-group 64" ;;
  w4g128gptq)  ARGS="--wire-group 128"; export FABLE5_CALIB_STATS=ref/calib_stats_${TAG}_h.npz FABLE5_CALIB_MODE=gptq ;;
  w4g64gptq)   ARGS="--wire-group 64";  export FABLE5_CALIB_STATS=ref/calib_stats_${TAG}_h.npz FABLE5_CALIB_MODE=gptq ;;
  *) echo "unknown point $POINT" >&2; exit 2 ;;
esac

echo "=== host $(hostname)  $(date -Is)"  > $OUT.log
echo "=== tree $(git rev-parse --short HEAD)"  >> $OUT.log
echo "=== res_scale $RES_SCALE" >> $OUT.log
FABLE5_MODEL=$TAG nice -n 10 $UV ref/fidelity_check.py $ARGS \
  --res-scale $RES_SCALE --ntok 24 --free-ntok 12 --cache $CACHE \
  --json-out $OUT.json >> $OUT.log 2>&1
echo "=== rc $?" >> $OUT.log
echo "fidelity $TAG/$POINT done"
