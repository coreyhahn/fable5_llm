#!/usr/bin/env bash
# smoke_regate.sh — re-run the SMOKE target's emit-twice gate once, through
# the REPAIRED `evidence/qwen9b/s3/emit_repeat.sh`, and prove the smoke path
# still passes and still produces the same bytes (S4 fix round 1, review I1).
#
#   bash evidence/qwen9b/s4/smoke_regate.sh
#
# WHY.  Fix round 1 changed `emit_repeat.sh`'s rc handling for the MODEL
# target's sake.  The two SMOKE targets go through the same script and their
# artifacts are what `evidence/qwen9b/s4/041_census_state_red.log`,
# `073_census_nodrain_red.log` and S3's own gates replay, so the change has
# to be shown NOT to have broken them.
#
# `w9_9b_smoke_scripts` emits `lay9b_s<seed>`, emits it AGAIN into
# `$(EMIT2_DIR)` and compares — but it compares the two NEW emissions with
# each other, so on its own it could not notice a re-emission that agreed
# with itself and disagreed with the artifact already on disk.  This script
# closes that: it digests the five files BEFORE and AFTER and requires every
# one to be unmoved, ON TOP of the gate's own `EMIT_REPEAT: PASS`.
#
# ONE SEED (`W9_SEEDS=1`), declared: the target's code path does not vary
# with the seed, and one seed keeps the rung to minutes on a machine that is
# also running the two model censuses.
#
# Run ON SNOKE.
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
MODELPY=${MODELPY:-/home/cah/.venv/bin/python}
VECPY=${VECPY:-$MODELPY}
SFX=".txt .e4.seq .e4.seqdata.bin .state_final.bin .state.bin"
P=$ROOT/tb/scripts/w9/lay9b_s1

echo "SMOKE_REGATE: host $(hostname)"
BEFORE=""
for s in $SFX; do BEFORE="$BEFORE $(sha256sum "$P$s" | cut -d' ' -f1)"; done
echo "  BEFORE:"
i=0
for s in $SFX; do
  i=$((i + 1))
  echo "    lay9b_s1$s  $(echo "$BEFORE" | cut -d' ' -f$((i + 1)))"
done

echo
echo "=== make -C tb w9_9b_smoke_scripts W9_SEEDS=1  (emit, emit again, compare)"
FAIL=0
T0=$(date +%s)
env FABLE5_MODEL=9b FABLE5_RS_F=7 make -C "$ROOT/tb" w9_9b_smoke_scripts \
    W9_SEEDS=1 MODELPY="$MODELPY" VECPY="$VECPY"
rc=$?
T1=$(date +%s)
echo "=== make rc=$rc  wall=$((T1 - T0))s"
[ "$rc" = 0 ] || { echo "    UNEXPECTED make rc $rc"; FAIL=1; }

echo
echo "  AFTER, against BEFORE:"
i=0
for s in $SFX; do
  i=$((i + 1))
  b=$(echo "$BEFORE" | cut -d' ' -f$((i + 1)))
  a=$(sha256sum "$P$s" | cut -d' ' -f1)
  if [ "$a" = "$b" ]; then echo "    lay9b_s1$s  UNMOVED   $a"
  else echo "    lay9b_s1$s  MOVED  was $b  now $a"; FAIL=1; fi
done

echo
if [ "$FAIL" = 0 ]; then
  echo "SMOKE_REGATE: PASS — the smoke target's emit-twice gate still passes"
  echo "  through the repaired emit_repeat.sh, and every byte of lay9b_s1 is"
  echo "  where it was"
  exit 0
fi
echo "SMOKE_REGATE: FAIL"
exit 1
