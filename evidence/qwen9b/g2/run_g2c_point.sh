#!/usr/bin/env bash
# G2c — the FULL 168-step 9B fidelity point at one (state law, RS_F).  SNOKE.
#
#   bash evidence/qwen9b/g2/run_g2c_point.sh <law> <rs_f> <run-tag>
#   NTOK=3 NOFREE=1 ... run_g2c_point.sh ...     # the cheap cache-warming smoke
#
# A FORK of `evidence/qwen9b/g1/run_g1_point.sh`, which must not be run in
# place: it writes `evidence/qwen9b/g1/fixed_9b_*.{json,log}`, G1's COMMITTED
# evidence, cited by section from RUNG_INT8_STATE.md.  This fork writes
# `evidence/qwen9b/g2/g2c_fixed_9b_*` and nothing else moves — same golden,
# same Hessian, same prompts, same steps, same threads, same nice level, same
# `--res-scale 1`.  Only <law> and <rs_f> move between runs, which is what
# makes the pair below single-variable.
#
# WHY THIS GATE RUNS IT AT ALL.  Two questions, one harness:
#   * `int16` + `RS_F=8` must REPRODUCE G1's committed baseline — 95/108,
#     rank max 5, top-5 3.69, 23 clips — on the POST-G2a/G2c tree.  Every
#     file in `ref/fidelity_check._WQ_SOURCES` that G2a and G2c touched moves
#     the quantizer source digest, so this run pays a cold cache and then
#     proves the host generalizations changed no number.
#   * `int16` + `RS_F=7` is A1.8's one open rider — measured under the
#     container that actually ships, which G1 never did (it measured the
#     rider at `int8:6` global and at `int8e` per-row and got opposite
#     signs).  INSTRUCTION-GATED: the plan's Step 4' says take it only on an
#     explicit instruction, and this gate was given one.  It DECIDES NOTHING.
#
# THE RS_F=8 HALF NO LONGER RUNS AS WRITTEN, and that is #26 working (dated
# 2026-09-10, pre-ship tool chore fix round 2; re-review m8 — the same note
# `run_g2c_emit.sh` carries, on the fourth script that exports FABLE5_RS_F).
# `ref/layer_fixed.py` now DERIVES RS_F from FABLE5_MODEL — 9b => 7 — and
# REFUSES a disagreeing FABLE5_RS_F, so `export FABLE5_RS_F=$RSF` below exits
# non-zero at import whenever <rs_f> is 8.  The RS_F=7 half is unaffected: it
# AGREES with the law and runs exactly as it did.  Nothing is relaxed to get
# the 8 back: at 9b an artifact emitted at RS_F=8 is self-consistent and
# WRONG against the shipping bitstream, which is the class #26 closed.  This
# script is KEPT AS THE RECORD of the pair `G2C_CHAIN.md` reports (reading it
# is right, running the 8 is not).  To re-take that half AS A RIDER SWEEP,
# add `FABLE5_RS_F_RIDER=1` — the refusal names it, and the run then
# announces itself on stderr on every emit path.
set -u
cd "$(dirname "$0")/../../.."
ROOT=$PWD

LAW=${1:?usage: run_g2c_point.sh <law> <rs_f> <run-tag>}
RSF=${2:?usage: run_g2c_point.sh <law> <rs_f> <run-tag>}
TAG=${3:?usage: run_g2c_point.sh <law> <rs_f> <run-tag>}

# The golden and the Hessian are gitignored REGENERABLE CACHES with pinned
# sha256s (plan Task 5 Step 2: "Verify both by hash against those records
# first; rebuild only if a hash fails or the file is gone").  Hash them
# before every run and refuse on a mismatch — a silently different golden
# would move every top-1 in this gate without a symptom.
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
NTOK=${NTOK:-24}
FREE=${FREE:-12}
OUT=g2c_fixed_9b_w4g128gptq_${LAWTAG}_rsf${RSF}_${TAG}

echo "=== G2c point: law=$LAW RS_F=$RSF ntok=$NTOK free=$FREE tag=$TAG"
echo "===   -> evidence/qwen9b/g2/$OUT.{log,json}"
check_sha "$GOLDEN" "$GOLDEN_SHA"
check_sha "$HESS" "$HESS_SHA"

# The quantized-weight cache is keyed by everything the artifacts depend on,
# INCLUDING a sha256 over the `ref/` sources that define the quantizer, and
# NOT by the state law or RS_F — which is the claim `--wq-cache-verify` puts
# under test on every run by re-quantizing one layer live and requiring
# byte-equality.  Layer 2 is `linear_attention` at 9B.
WQ_CACHE=${WQ_CACHE:-/var/tmp/fable5_wq}
WQ_VERIFY=${WQ_VERIFY:-2}
VERIFY_ARG=""
[ "$WQ_VERIFY" != "-1" ] && VERIFY_ARG="--wq-cache-verify $WQ_VERIFY"

FREE_ARG="--free-ntok $FREE"
[ "${NOFREE:-0}" = "1" ] && FREE_ARG="--no-freerun"

export FABLE5_MODEL=9b
export FABLE5_DN_STATE=$LAW
export FABLE5_RS_F=$RSF
export FABLE5_CALIB_STATS=$HESS
export FABLE5_CALIB_MODE=gptq
export OMP_NUM_THREADS=${THREADS:-6}
export MKL_NUM_THREADS=$OMP_NUM_THREADS
export OPENBLAS_NUM_THREADS=$OMP_NUM_THREADS

UV="$HOME/.local/bin/uv run --no-project --with torch --with transformers --with numpy python -u"
exec nice -n 10 bash evidence/qwen9b/run.sh "g2/$OUT.log" \
  $UV ref/fidelity_check.py --wire-group 128 --prompts "${PROMPTS:-1,2,3,4}" \
    --ntok "$NTOK" $FREE_ARG --res-scale 1 \
    --cache "$ROOT/$GOLDEN" \
    --wq-cache "$WQ_CACHE" $VERIFY_ARG \
    --json-out "$ROOT/evidence/qwen9b/g2/$OUT.json"
