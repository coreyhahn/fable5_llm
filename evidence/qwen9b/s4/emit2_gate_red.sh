#!/usr/bin/env bash
# emit2_gate_red.sh — the GREEN and the three REDs for `w9_9b_model_script`'s
# emit-twice gate (S4 fix round 1, review I1), at SECONDS instead of hours.
#
#   bash evidence/qwen9b/s4/emit2_gate_red.sh
#
# WHAT IS BEING PROVED.  S4's review established, three ways, that the
# emit-twice gate S3 wired into `tb/Makefile`'s `w9_9b_model_script` could
# never fire on the model artifact: the emitter was a plain recipe line, the
# 9B emitter exits NON-ZERO BY DESIGN on the runtime range audit
# (`ref/gen_model_script.py:711-721`, no `--allow-clip`), and
# `evidence/qwen9b/s3/emit_repeat.sh` FAILED on any non-zero rc.  All three
# are fixed; a fix to a gate is worth nothing until the gate is seen to fire
# BOTH ways, and firing it for real costs 7 hours of GPTQ per seed.
#
# So `MODELPY` is replaced by `evidence/qwen9b/s4/emit_shim.py`, which writes
# deterministic seed-dependent bytes at the four compared suffixes and
# reproduces the emitter's exit contract exactly (the finalizer's `SEQ:` line,
# the `RANGE AUDIT FAILED` line, rc 1).  No GPTQ, no checkpoint, no HF cache.
#
#   GREEN  the block is REACHED on the audit rc and the four files compare
#          IDENTICAL -> `EMIT_REPEAT: PASS 1 identical emission(s)`; the
#          target still exits with the emitter's rc (make reports Error 1
#          and exits 2), which is what keeps `=== rc: 2` meaning what
#          Task 11's and S4's emission logs say it means.
#   RED 1  EMIT2_FORCE_FAIL=1 perturbs the second emission's seed -> the
#          comparison must REFUSE it (`DIFFERS`, `EMIT_REPEAT: FAIL`) and
#          the target must exit non-zero.
#   RED 2  the emitter exits 1 with NO audit line -> the recipe must ABORT
#          BEFORE the block: no `EMIT_REPEAT:` verdict may appear at all.
#   RED 3  the emitter prints a Traceback and then the audit line -> the
#          recipe must ABORT BEFORE the block for the same reason.
#
# Run ON SNOKE (the campaign's Global Constraints keep darthplagueis out of
# numeric compute; this runs no arithmetic, but it runs `make` in `tb/` and
# the campaign keeps one host for the whole rung).
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
SHIM=$ROOT/evidence/qwen9b/s4/emit_shim.py
TMP=$(mktemp -d "${TMPDIR:-/tmp}/s4_emit2_gate.XXXXXX")
SHIMDIR=$ROOT/tb/scripts/w9/shim
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$SHIMDIR"

FAIL=0
echo "EMIT2_GATE_RED: host $(hostname)"
echo "  shim      = evidence/qwen9b/s4/emit_shim.py"
echo "  artifacts = tb/scripts/w9/shim/ (gitignored build area)"
echo "  make      = $(make --version | head -1)"

arm () {  # $1 = label, $2 = W9_BASE tag, $3 = extra env (may be empty)
  label=$1; tag=$2; extra=$3
  echo
  echo "=== $label   env: ${extra:-<none>}   W9_BASE=scripts/w9/shim/$tag"
  rm -f "$SHIMDIR/$tag".*
  rm -rf "$ROOT/tb/scripts/w9/emit2/$tag" "$ROOT/tb/scripts/w9/emit2/$tag".*
  T0=$(date +%s)
  # shellcheck disable=SC2086
  env $extra make -C "$ROOT/tb" w9_9b_model_script \
      W9_EMIT2=1 W9_SEED=1 W9_NTOK=3 \
      W9_BASE=scripts/w9/shim/$tag MODELPY="$SHIM" \
      > "$TMP/$label.out" 2>&1
  rc=$?
  T1=$(date +%s)
  # `grep -v '\\$'` drops the lines make ECHOES of the recipe itself (they
  # all end in a backslash continuation), leaving only what ran.
  grep -E "W9_EMIT2 GATE:|EMIT_REPEAT:|IDENTICAL|DIFFERS|distinct sha|run 1 |^make: \*\*\*" \
    "$TMP/$label.out" | grep -v '\\$' | sed 's/^/    /'
  echo "    make rc=$rc  wall=$((T1 - T0))s"
}

want () {  # $1 = label, $2 = "yes"|"no", $3 = pattern, $4 = why
  if grep -qE "$3" "$TMP/$1.out"; then have=yes; else have=no; fi
  if [ "$have" = "$2" ]; then
    echo "    ok   $4"
  else
    echo "    FAIL $4  (expected $2, got $have for /$3/)"; FAIL=1
  fi
}

wantrc () {  # $1 = label, $2 = expected rc
  if [ "$3" = "$2" ]; then echo "    ok   make rc = $2"
  else echo "    FAIL make rc: got $3, expected $2"; FAIL=1; fi
}

# ------------------------------------------------------------------ GREEN
arm green green_s1 ""
G_RC=$rc
want green yes "W9_EMIT2 GATE: rc 1 is the KNOWN deliberate range-audit failure" \
     "the recipe recognised the by-design audit rc"
want green yes "EMIT_REPEAT: PASS 1 identical emission" \
     "the emit-twice block was REACHED and PASSED"
for s in "\.txt" "\.e4\.seq" "\.e4\.seqdata\.bin" "\.state_final\.bin"; do
  want green yes "$s  IDENTICAL" "  $s compared IDENTICAL"
done
wantrc green 2 "$G_RC"

# ------------------------------------------------------------------ RED 1
arm red1_force_fail red1_s1 "EMIT2_FORCE_FAIL=1"
R1_RC=$rc
want red1_force_fail yes "EMIT2_FORCE_FAIL: seed perturbed" \
     "the second emission was perturbed"
want red1_force_fail yes "DIFFERS" "the comparison CAUGHT the difference"
want red1_force_fail yes "EMIT_REPEAT: FAIL" "the block REFUSED the artifact"
want red1_force_fail no  "EMIT_REPEAT: PASS" "and did not also pass"
if [ "$R1_RC" = 0 ]; then
  echo "    FAIL the target exited 0 on a refused artifact"; FAIL=1
else
  echo "    ok   the target exited non-zero ($R1_RC)"
fi

# ------------------------------------------------------------------ RED 2
arm red2_no_audit red2_s1 "SHIM_MODE=no_audit"
R2_RC=$rc
want red2_no_audit yes "W9_EMIT2 GATE: ABORT" "the recipe ABORTED on an unknown rc"
want red2_no_audit no  "EMIT_REPEAT:" "the emit-twice block was NOT reached"
if [ "$R2_RC" = 0 ]; then
  echo "    FAIL the target exited 0 after an unknown emitter failure"; FAIL=1
else
  echo "    ok   the target exited non-zero ($R2_RC)"
fi

# ------------------------------------------------------------------ RED 3
arm red3_traceback red3_s1 "SHIM_MODE=traceback"
R3_RC=$rc
want red3_traceback yes "W9_EMIT2 GATE: ABORT" "the recipe ABORTED on the traceback"
want red3_traceback no  "EMIT_REPEAT:" "the emit-twice block was NOT reached"
if [ "$R3_RC" = 0 ]; then
  echo "    FAIL the target exited 0 after a traceback"; FAIL=1
else
  echo "    ok   the target exited non-zero ($R3_RC)"
fi

rm -rf "$SHIMDIR"
rm -rf "$ROOT"/tb/scripts/w9/emit2/green_s1* "$ROOT"/tb/scripts/w9/emit2/red1_s1* \
       "$ROOT"/tb/scripts/w9/emit2/red2_s1* "$ROOT"/tb/scripts/w9/emit2/red3_s1*

echo
if [ "$FAIL" = 0 ]; then
  echo "EMIT2_GATE_RED: PASS — the model target's emit-twice block is REACHED"
  echo "  on the by-design audit rc and PASSES; it REFUSES a perturbed second"
  echo "  emission; and it is NOT reached when the emitter fails for any other"
  echo "  reason (no audit line, or a traceback)"
  exit 0
fi
echo "EMIT2_GATE_RED: FAIL"
exit 1
