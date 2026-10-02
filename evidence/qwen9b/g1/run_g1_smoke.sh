#!/usr/bin/env bash
# G1 — the six-step 9B smoke at ONE state law.  RUN ON SNOKE.
#
#   bash evidence/qwen9b/g1/run_g1_smoke.sh <law> [rs_f] [run-tag]
#
#     <law>     int16 | int8:<k> | int8t:<k> | int8e      (FABLE5_DN_STATE)
#     [rs_f]    8 (default) | 7                           (FABLE5_RS_F)
#     [run-tag] optional suffix when the same setting is run twice
#
# Six teacher-forced steps on prompt 1 at w4g128gptq — NOT at W8.  Track L's
# res_scale sweep is the model for the SHAPE of this sweep and not for its
# point: it ran W8 on a single prompt (`LADDER.md` §4), and W4+GPTQ is what
# this build ships.  A six-step single-prompt smoke SELECTS a k; it does not
# score it.  The score is run_g1_point.sh.
#
# Why the pinning is here and not in the caller: the whole sweep has to be
# single-variable, so the thread count, the nice level, the golden, the
# Hessian and the harness flags are FIXED IN THIS FILE and only the law moves.
set -u
cd "$(dirname "$0")/../../.."
ROOT=$PWD

LAW=${1:?usage: run_g1_smoke.sh <law> [rs_f] [run-tag]}
RSF=${2:-8}
TAG=${3:-}

# ---- the golden is a gitignored CACHE with a pinned sha256, not an artifact.
# Hash it before use and refuse on a mismatch (.gitignore:39, LADDER.md §1,
# the mechanism Task 5 Step 2 spells out).  A stale or rebuilt-differently
# golden would silently move every top-1 in this gate.
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

# tag: int8:6 -> int8_k6, int8t:6 -> int8t_k6, int16 -> int16, int8e -> int8e
LAWTAG=$(echo "$LAW" | sed 's/:/_k/')
OUT=smoke_9b_w4g128gptq_${LAWTAG}_rsf${RSF}${DIAG:+_diag_$DIAG}${TAG:+_$TAG}

echo "=== G1 smoke: law=$LAW RS_F=$RSF ${DIAG:+DIAG=$DIAG }-> evidence/qwen9b/g1/$OUT.{log,json}"
check_sha "$GOLDEN" "$GOLDEN_SHA"
check_sha "$HESS" "$HESS_SHA"

# WQ_CACHE holds the quantized-weight artifacts, which do NOT depend on the
# state law or on RS_F — the cost item spec §4.1 makes G1's first task.
# WQ_VERIFY re-quantizes that layer live and requires byte-equality with the
# cache; -1 disables.  Layer 2 is `linear_attention` at 9B (the layer type
# whose weights an int8 STATE could conceivably reach), layer 3 is
# `full_attention`.
WQ_CACHE=${WQ_CACHE:-/var/tmp/fable5_wq}
WQ_VERIFY=${WQ_VERIFY:-2}
VERIFY_ARG=""
[ "$WQ_VERIFY" != "-1" ] && VERIFY_ARG="--wq-cache-verify $WQ_VERIFY"

# DIAG=<key> prices ONE frozen format against the same pinning — G1 uses it
# for `gateport`, which relaxes DT_Q12_MIN/DT_Q12_MAX/A_Q15_MAX and therefore
# answers "what does the gate-port clamp cost in top-1 at 9B?".  A diag run
# CANNOT use the weight cache (fidelity_check refuses the combination: those
# three constants are read by quant_deltanet), so it pays its own
# quantization pass.  Everything else — golden, Hessian, prompts, steps,
# threads, nice — is identical, which is the reason it lives in this file.
CACHE_ARG="--wq-cache $WQ_CACHE $VERIFY_ARG"
# DN_PROBE=1 adds the state DISTRIBUTION probe (rms / zero fraction / log2
# histogram of the pre-narrowing accumulator).  It costs a few seconds a step
# and it is the measurement that says whether a container's problem is RANGE
# or RESOLUTION — which is the question the k sweep is actually asking.
PROBE_ARG=""
[ "${DN_PROBE:-0}" = "1" ] && PROBE_ARG="--dn-probe"
DIAG_ARG=""
if [ -n "${DIAG:-}" ]; then
  CACHE_ARG=""
  DIAG_ARG="--diag $DIAG"
  echo "  DIAG=$DIAG -> no weight cache for this run (see the header)"
fi

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
  $UV ref/fidelity_check.py --wire-group 128 --prompts 1 --ntok 3 \
    --no-freerun --res-scale 1 \
    --cache "$ROOT/$GOLDEN" \
    $CACHE_ARG $DIAG_ARG $PROBE_ARG \
    --json-out "$ROOT/evidence/qwen9b/g1/$OUT.json"
