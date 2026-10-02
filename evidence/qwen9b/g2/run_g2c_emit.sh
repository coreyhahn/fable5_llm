#!/usr/bin/env bash
# G2c Step 3 — the 9B artifact emission, attempted at the ratified operating
# point.  RUN ON SNOKE.
#
#   bash evidence/qwen9b/g2/run_g2c_emit.sh <run-tag>
#
# THE RATIFIED OPERATING POINT, spelled out so the run is not a guess:
#   --wq=w4 (the default, so it is not passed — passing it would be identical)
#   --w4-group=128            D1, and the g64 strip is ratified O2
#   --res-scale=1             spec 4.4: at H=4096 the raw residual reaches the
#                             Q7.8 rail with no rescale applied at all
#   FABLE5_RS_F=8             A1.8 — the shipped value; the RS_F=7 rider is a
#                             fidelity measurement, not an artifact setting
#   FABLE5_CALIB_STATS/MODE   the GPTQ pair, ref/calib_stats_9b_h.npz
#   FABLE5_DN_STATE unset     = int16, the ratified container (A1)
#
# WHAT THIS RUN IS EXPECTED TO DO.  It is expected to REFUSE, in the emit
# loop, on a SEQ_ISA v1.7 ARG field — and to refuse AFTER paying the full
# quantization, because `ref/gen_model_script.py` quantizes every layer and
# the head before it opens the output file.  `Mach.dump_weights` packs only
# the wids `Mach.matvec` registered, and `Mach.matvec` is reached only from
# the token body, so NO 9B weight image can be emitted until Tasks 7/8/9/10
# widen those fields.  The refusal is the measurement; it is recorded, and
# nothing here is relaxed to get past it (plan Global Constraints; a guard
# that is weakened to make an artifact emit is the failure mode, not the fix).
#
# The golden and the Hessian are verified by sha256 first — Step 2's whole
# instruction is "verify, do not rebuild".
#
# IT NO LONGER RUNS AS WRITTEN, and that is #26 working (dated 2026-09-10,
# pre-ship tool chore; review m9).  `ref/layer_fixed.py` now DERIVES RS_F
# from FABLE5_MODEL — 9b => 7 — and REFUSES a disagreeing FABLE5_RS_F, so
# the `export FABLE5_RS_F=8` below exits non-zero at import, before any
# quantization.  Nothing here is relaxed to get past it: at RS_F=8 a 9B
# artifact is self-consistent and WRONG against the shipping bitstream,
# which is exactly the class #26 closed.  This script is KEPT AS THE RECORD
# of the A1.8 operating point and of the SEQ_ISA v1.7 ARG refusal it
# measured (`G2C_CHAIN.md` cites it by line: reading it is right, running it
# is not).  To re-take it AS A RIDER SWEEP, add `FABLE5_RS_F_RIDER=1` — the
# refusal names it, and the emission then announces itself on stderr.
set -u
cd "$(dirname "$0")/../../.."
ROOT=$PWD
TAG=${1:?usage: run_g2c_emit.sh <run-tag>}

GOLDEN=evidence/qwen_next/ladder/golden_bf16_9b.npz
GOLDEN_SHA=4fd0616bae5086b8e449901740355a9f192b33ae1c9d18eafc160c0987408fd3
HESS=ref/calib_stats_9b_h.npz
HESS_SHA=36689b5990c80e1208060b7864841a9387e19ea27e27ec09f0bfd4dd081dd7d4
check_sha() {
  [ -f "$1" ] || { echo "MISSING $1" >&2; return 3; }
  got=$(sha256sum "$1" | cut -d' ' -f1)
  if [ "$got" = "$2" ]; then echo "  sha256 OK       $1  $got"
  else echo "  sha256 MISMATCH $1: $got != $2" >&2; return 3; fi
}

OUTDIR=${OUTDIR:-$(mktemp -d /var/tmp/g2c_emit_XXXXXX)}
echo "=== G2c emit attempt: FABLE5_MODEL=9b, W4 g128 + GPTQ, res_scale=1, RS_F=8"
echo "===   artifacts would land in $OUTDIR"
echo
echo "--- Step 2: the two inherited caches, VERIFIED not rebuilt ---"
check_sha "$GOLDEN" "$GOLDEN_SHA" || exit 3
check_sha "$HESS" "$HESS_SHA" || exit 3
echo "  both match their committed records (LADDER.md and calib_9b.log);"
echo "  Step 2 is discharged by verification — no 40 min pass, no 3.03 h rebuild."
echo

export FABLE5_MODEL=9b
export FABLE5_RS_F=8
# ABSOLUTE.  The emit below runs from `ref/` (the generator resolves its own
# sibling imports from there), so a repo-relative Hessian path would not
# resolve and the run would die on a FileNotFoundError — which the first
# attempt did, and which this script then scored as the expected ISA refusal.
# That is the "passed for the wrong reason" class; the verdict block at the
# bottom now DISCRIMINATES, and this line removes the cause.
export FABLE5_CALIB_STATS=$ROOT/$HESS
export FABLE5_CALIB_MODE=gptq
export OMP_NUM_THREADS=${THREADS:-8}
export MKL_NUM_THREADS=$OMP_NUM_THREADS
export OPENBLAS_NUM_THREADS=$OMP_NUM_THREADS

echo "--- the guard suite at this geometry, BEFORE the emit ---"
UVP="$HOME/.local/bin/uv run --no-project --with numpy python -u"
$UVP evidence/qwen9b/g2/isa_guards_check.py
echo "  (guard suite rc=$?)"
echo

echo "--- Step 3: ref/gen_model_script.py at 9B ---"
UV="$HOME/.local/bin/uv run --no-project --with torch --with transformers --with numpy python -u"
ERR=$OUTDIR/emit_stderr.txt
set +e
( cd ref && nice -n 10 $UV gen_model_script.py "$OUTDIR/model_9b_s1.txt" 1 3 \
    --w4-group=128 --res-scale=1 ) 2> >(tee "$ERR" >&2)
RC=$?
set -e
echo
echo "--- what the run left behind ---"
ls -la "$OUTDIR" || true
echo "  weight images written: $(ls "$OUTDIR"/*_w*.bin 2>/dev/null | wc -l)"
echo "  weights manifest:      $(ls "$OUTDIR"/*.weights.json 2>/dev/null | wc -l)"
echo "  emb table:             $(ls "$OUTDIR"/*.emb.bin 2>/dev/null | wc -l)"
echo
# DISCRIMINATE.  A non-zero exit is NOT by itself the expected result: the
# first attempt died on a FileNotFoundError (a relative Hessian path against a
# `cd ref`) and a bare rc test scored that as the ISA refusal.  The expected
# refusal must name one of the five SEQ_ISA v1.7 ARG fields; anything else is
# a different failure and is reported as one.
# Each alternative is TEXT FROM A GUARD'S OWN MESSAGE, never a bare field
# name.  `CONV` alone was here at first and is exactly the wrong shape: it
# matches any traceback line that happens to contain the substring — a path, a
# `CONV_DIM` reference in an unrelated frame — and would re-create the
# "passed for the wrong reason" failure this block exists to prevent
# (T5 review).  Both `_conv_fields` asserts are named explicitly instead.
WANT='ISA_SADDR_MAX|VNW count|does not fit ARG0|ALU_LEN_MAX|vec_alu.sv cfg_len|CONV channel count|CONV first-channel|SEQ_ISA v1.7'
if [ "$RC" = 0 ]; then
  echo "G2C_EMIT UNEXPECTED_PASS — the emitter produced a 9B artifact set."
  echo "  That contradicts G2a's recorded refusals; do not use the artifacts"
  echo "  until the discrepancy is explained."
elif /usr/bin/grep -Eq "$WANT" "$ERR"; then
  echo "  the refusal names:"
  /usr/bin/grep -Eo "$WANT[^\"]*" "$ERR" | head -3 | sed 's/^/    /'
  echo "G2C_EMIT REFUSED_AS_EXPECTED rc=$RC — a SEQ_ISA v1.7 ARG field cannot"
  echo "  encode a 9B layer body, and dump_weights runs only after the body."
else
  echo "G2C_EMIT UNEXPECTED_FAILURE rc=$RC — the run failed, but NOT on an"
  echo "  ARG-field guard.  This is not the measurement; fix the cause and"
  echo "  re-run.  Last stderr lines:"
  tail -5 "$ERR" | sed 's/^/    /'
fi
exit "$RC"
