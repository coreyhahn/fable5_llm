#!/usr/bin/env bash
# emit_repeat.sh — emit ONE artifact N times and require every sha to agree.
#
#   sh evidence/qwen9b/s3/emit_repeat.sh <n> <outdir> [<seed>] [<ntok>]
#
# `EMIT_GEN` (default gen_layer_script.py) and `EMIT_ARGS` (default
# "<seed> <ntok>") select the generator, so the SAME gate covers the smoke
# artifact and S4's model emits; `EMIT_ENV` adds env for the run (the model
# needs FABLE5_CALIB_STATS / FABLE5_CALIB_MODE).  `REF_PREFIX` compares run 1
# against an emission already on disk -- which is how the KEPT-ARTIFACT
# targets use it: they emit once, then call this with `n = 1` and
# `REF_PREFIX = <the kept prefix>`, so the artifact is accepted only if a
# second, independent emission reproduces it byte for byte.
#
# `EMIT_SEQ_ENV` is the STREAM ENVIRONMENT and defaults to the 9B operating
# point; the artifact targets pass their OWN `$(W9_ENV)`, so the second
# emission cannot differ from the first by an environment variable (fix
# round 2, C1 part 3's out-of-scope note).
#
# `EMIT2_FORCE_FAIL=1` perturbs the second emission (seed + 1) so the gate's
# RED can be committed: an emit-twice check that has never failed is a
# check nobody has seen work.
#
# WHY IT EXISTS (S3 fix round 1, C1).  Three emitter runs on darthplagueis
# aborted inside `ref/w4a8_ref.matvec_y32`'s
# `assert np.abs(acc).max() < (1 << 31)` with a value of `true + 2^33` --
# arithmetically impossible for that expression, whose maximum is 123,904 --
# and the reviewer reproduced it 3 times in 9 on the same host from a clean
# committed tree.  darthplagueis is the host the campaign's Global
# Constraints ban from numeric compute, for exactly this class.  An assert
# that fires is the LUCKY case: the same corruption below the assert
# threshold would produce a silently wrong artifact.
#
# So this is the guard the campaign needs on every emission it keeps: emit
# the same artifact more than once, under different prefixes, and refuse
# unless every byte agrees.  A single bit flipped anywhere in the emission
# changes the .txt, the .seq, the .seqdata.bin or the state image.
#
# `MODELPY` must be a numpy interpreter (snoke: /home/cah/.venv/bin/python;
# the repo's ref/.venv is a dangling symlink there).  Every run is
# SEQUENTIAL -- concurrent runs would share nothing but would make a
# host-memory explanation harder to read, not easier.
#
#   rc 0  EMIT_REPEAT: PASS <n> identical emission(s)
#   rc 1  EMIT_REPEAT: FAIL — the shas differ; the artifact is not
#         reproducible on this host and MUST NOT be kept
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
N=${1:-2}
OUT=${2:-/tmp/emit_repeat}
SEED=${3:-1}
NTOK=${4:-2}
MODELPY=${MODELPY:-$([ -x /home/cah/.venv/bin/python ] && echo /home/cah/.venv/bin/python \
                     || echo "$ROOT/ref/.venv/bin/python")}
mkdir -p "$OUT"
echo "emit_repeat: n=$N gen=${EMIT_GEN:-gen_layer_script.py} args='${EMIT_ARGS:-$SEED $NTOK}'  host=$(hostname)"
echo "  MODELPY = $MODELPY"
echo "  python  = $("$MODELPY" -c 'import sys,numpy;print(sys.version.split()[0],"numpy",numpy.__version__)')"
echo "  out     = $OUT"

# the four files a bit-flip anywhere in the emission would move
SFX=".txt .e4.seq .e4.seqdata.bin .state_final.bin"

for i in $(seq 1 "$N"); do
  P="$OUT/rep$i"
  A=${EMIT_ARGS:-$SEED $NTOK}
  if [ "${EMIT2_FORCE_FAIL:-0}" = 1 ]; then
    A=$(( SEED + 1 ))" $NTOK"
    echo "  run $i  [EMIT2_FORCE_FAIL: seed perturbed to $(( SEED + 1 ))]"
  fi
  # S4 FIX ROUND 1 (review I1b): THE rc IS CONTRACTED, AND THE OUTPUT IS KEPT.
  # `ref/gen_model_script.py:711-721` raises SystemExit when the runtime
  # range audit fails and `--allow-clip` is not passed, so the 9B MODEL
  # emitter exits NON-ZERO BY DESIGN with its artifacts already written by
  # `ref/seq_format._finalize`'s atexit hook.  Treating every non-zero rc as
  # ABORTED made this gate impossible to pass on the campaign's most
  # expensive artifact, and discarding stdout meant it could not have
  # inspected the audit line even if it had wanted to.  The contract is the
  # one `evidence/qwen9b/s4/emit_model_gated.sh:82-102` implements: a
  # non-zero rc is accepted ONLY with the audit line AND the finalizer's
  # `SEQ: ... records ... -> ` line AND no traceback/assert.  Each run's
  # output is kept beside its artifacts in `$P.emit.log`.
  ( cd "$ROOT/ref" && env ${EMIT_SEQ_ENV:-FABLE5_MODEL=9b FABLE5_RS_F=7 \
      SEQ_PROFILE=epsnorm SEQ_NCH=4 SEQ_REPACK=1} SEQ_EMIT="$P.e4" \
      ${EMIT_ENV:-} \
      "$MODELPY" "${EMIT_GEN:-gen_layer_script.py}" "$P.txt" $A ) \
    > "$P.emit.log" 2>&1
  rc=$?
  if [ "$rc" != 0 ]; then
    if grep -q '^RANGE AUDIT FAILED' "$P.emit.log" \
       && grep -q '^SEQ: .* records .* -> ' "$P.emit.log" \
       && ! grep -qE 'Traceback \(most recent call last\)|AssertionError' \
              "$P.emit.log"; then
      echo "  run $i  rc $rc = the KNOWN deliberate range audit (no --allow-clip); artifacts written"
    else
      echo "  run $i  rc $rc is NOT the known range-audit failure; last lines:"
      tail -20 "$P.emit.log" | sed 's/^/      /'
      echo "EMIT_REPEAT: FAIL — run $i ABORTED"; exit 1
    fi
  fi
  L=""
  for s in $SFX; do L="$L $(sha256sum "$P$s" | cut -d' ' -f1 | cut -c1-16)"; done
  echo "  run $i $L"
done

FAIL=0
for s in $SFX; do
  U=$(for i in $(seq 1 "$N"); do sha256sum "$OUT/rep$i$s" | cut -d' ' -f1; done \
      | sort -u | wc -l)
  H=$(sha256sum "$OUT/rep1$s" | cut -d' ' -f1)
  echo "  $s  $U distinct sha over $N run(s)   $H"
  [ "$U" = 1 ] || FAIL=1
done

# and, when the caller names one, against a REFERENCE prefix already on disk
if [ -n "${REF_PREFIX:-}" ]; then
  echo "  --- against the reference emission $REF_PREFIX"
  for s in $SFX; do
    A=$(sha256sum "$OUT/rep1$s" | cut -d' ' -f1)
    B=$(sha256sum "$REF_PREFIX$s" | cut -d' ' -f1)
    if [ "$A" = "$B" ]; then echo "  $s  IDENTICAL   $A"
    else echo "  $s  DIFFERS  got $A  ref $B"; FAIL=1; fi
  done
fi

if [ "$FAIL" = 0 ]; then echo "EMIT_REPEAT: PASS $N identical emission(s)"
else echo "EMIT_REPEAT: FAIL"; fi
exit "$FAIL"
