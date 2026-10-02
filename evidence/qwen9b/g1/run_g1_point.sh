#!/usr/bin/env bash
# G1 — the FULL 168-step 9B fidelity point at one state law.  RUN ON SNOKE.
#
#   bash evidence/qwen9b/g1/run_g1_point.sh <law> <rs_f> <run-tag>
#
# Forked from `evidence/qwen_next/ladder/run_fidelity.sh`, which must NOT be
# run in place at 9B: it writes `evidence/qwen_next/ladder/fixed_9b_*.{json,log}`
# — Track L's COMMITTED evidence, cited by line from LADDER.md.  This fork
# writes evidence/qwen9b/g1/fixed_9b_w4g128gptq_<law>_rsf<rs_f>_<run-tag>.*
# and evidence/qwen9b/run.sh refuses to overwrite an existing log.
#
# The point, exactly as spec §4.1(b) defines it and exactly as the committed
# baseline row was taken: 9B, w4g128gptq, S=1, prompts 1,2,3,4, --ntok 24,
# --free-ntok 12 => 108 teacher-forced + 60 free = 168 steps, teacher-forced
# against the committed golden.  RES_SCALE is 1 and is NOT inherited from the
# ladder's default of 4: at H=4096 the raw residual reaches the Q7.8 rail with
# no rescale applied at all (spec §4.4), so S=1 is the point this build ships.
#
# THE ONLY THING THAT MOVES BETWEEN RUNS IS <law> AND <rs_f>.
set -u
cd "$(dirname "$0")/../../.."
ROOT=$PWD

LAW=${1:?usage: run_g1_point.sh <law> <rs_f> <run-tag>}
RSF=${2:?usage: run_g1_point.sh <law> <rs_f> <run-tag>}
TAG=${3:?usage: run_g1_point.sh <law> <rs_f> <run-tag>}

GOLDEN=evidence/qwen_next/ladder/golden_bf16_9b.npz
GOLDEN_SHA=4fd0616bae5086b8e449901740355a9f192b33ae1c9d18eafc160c0987408fd3
HESS=ref/calib_stats_9b_h.npz
HESS_SHA=36689b5990c80e1208060b7864841a9387e19ea27e27ec09f0bfd4dd081dd7d4
check_sha() {
  [ -f "$1" ] || { echo "MISSING $1 — rebuild it (see the header)" >&2; exit 3; }
  got=$(sha256sum "$1" | cut -d' ' -f1)
  [ "$got" = "$2" ] || { echo "SHA MISMATCH $1: $got != $2" >&2; exit 3; }
  echo "  sha256 OK  $1  $got"
}

LAWTAG=$(echo "$LAW" | sed 's/:/_k/')
OUT=fixed_9b_w4g128gptq_${LAWTAG}_rsf${RSF}_${TAG}

echo "=== G1 point: law=$LAW RS_F=$RSF tag=$TAG -> evidence/qwen9b/g1/$OUT.{log,json}"
check_sha "$GOLDEN" "$GOLDEN_SHA"
check_sha "$HESS" "$HESS_SHA"

WQ_CACHE=${WQ_CACHE:-/var/tmp/fable5_wq}
WQ_VERIFY=${WQ_VERIFY:-2}
VERIFY_ARG=""
[ "$WQ_VERIFY" != "-1" ] && VERIFY_ARG="--wq-cache-verify $WQ_VERIFY"

export FABLE5_MODEL=9b
export FABLE5_DN_STATE=$LAW
export FABLE5_RS_F=$RSF
# The RS_F RIDER SWEEP is what this script IS, so it says so (#26,
# 2026-09-10): `ref/layer_fixed.py` derives RS_F from FABLE5_MODEL
# (9b => 7) and REFUSES a disagreeing FABLE5_RS_F, because an
# emission that forgets the variable is self-consistent and wrong.
# A MEASUREMENT that deliberately sweeps the rider sets this too.
# WHY IT IS EXPORTED SCRIPT-WIDE AND THAT IS STILL PER-INVOCATION (I-2,
# 2026-09-10): this script `exec`s exactly ONE emission (the `exec nice ...
# run.sh` at the end), so the export reaches that command and nothing else.
# And the escape is no longer silent: when RSF disagrees with the law,
# `ref/layer_fixed.py` prints ONE FABLE5_RS_F_RIDER line on stderr, which
# `evidence/qwen9b/run.sh` tees into this run's own log; when RSF IS the
# law value (7) the rider is inert -- the env agrees and nothing is
# overridden.
export FABLE5_RS_F_RIDER=1
export FABLE5_CALIB_STATS=$HESS
export FABLE5_CALIB_MODE=gptq
export OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 OPENBLAS_NUM_THREADS=6

UV="$HOME/.local/bin/uv run --no-project --with torch --with transformers --with numpy python -u"
exec nice -n 10 bash evidence/qwen9b/run.sh "g1/$OUT.log" \
  $UV ref/fidelity_check.py --wire-group 128 --prompts 1,2,3,4 \
    --ntok 24 --free-ntok 12 --res-scale 1 \
    --cache "$ROOT/$GOLDEN" \
    --wq-cache "$WQ_CACHE" $VERIFY_ARG \
    --json-out "$ROOT/evidence/qwen9b/g1/$OUT.json"
