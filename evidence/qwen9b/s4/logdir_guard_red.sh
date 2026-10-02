#!/usr/bin/env bash
# logdir_guard_red.sh — the RED and the GREEN for `run_g4a_replay.sh`'s
# TRACKED-LOGDIR refusal (S4 fix round 1, I2).
#
#   bash evidence/qwen9b/s4/logdir_guard_red.sh
#
# THE DEFECT.  `evidence/qwen9b/g4/run_g4a_replay.sh`'s default LOGDIR is
# `evidence/qwen9b/g4/seedlogs_<stem>`.  For `model_9b_s` those four files
# are TRACKED — they are Task 11's committed per-seed logs, the record
# `--tokens-ref` reads §4.1a out of.  A re-run of the rung with the default
# would overwrite the evidence the rung compares itself against.  S4 avoided
# it by passing LOGDIR=; the script now REFUSES instead.
#
# THE TWO ARMS, and the second is the one that keeps the guard honest — a
# refusal that fires on everything is not a guard, it is a wall:
#
#   RED    the DEFAULT LOGDIR for `model_9b_s` must exit 4, print
#          `REFUSING: ... holds TRACKED evidence`, and launch NO SIMULATION
#          (the guard sits before the binary check and before every `LAUNCH`,
#          so neither line may appear in its output).
#   GREEN  an UNTRACKED LOGDIR must not trigger it: the same script, the same
#          binary, one real `tok9b_s1` replay into a fresh temp directory,
#          must run to `ALL PASS` with rc 0.
#
# Run ON SNOKE (the GREEN arm is a real Verilator simulation).
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
RUN=$ROOT/evidence/qwen9b/g4/run_g4a_replay.sh
TMP=$(mktemp -d "${TMPDIR:-/tmp}/s4_logdir_guard.XXXXXX")
# The GREEN arm's LOGDIR is INSIDE the repository and UNTRACKED, because
# that is the realistic case the guard must not break; it is removed on exit
# so no untracked directory is left beside the evidence.
GDIR=$ROOT/evidence/qwen9b/s4/seedlogs_guard_green_tmp
trap 'rm -rf "$TMP" "$GDIR"' EXIT

FAIL=0
echo "LOGDIR_GUARD_RED: host $(hostname), scratch $TMP"
echo "  tracked check, for the record:"
for d in evidence/qwen9b/g4/seedlogs_model_9b_s \
         evidence/qwen9b/s4/seedlogs_model_9b_s; do
  n=$(git -C "$ROOT" ls-files "$d" | wc -l)
  echo "    $d  $n tracked file(s)"
done

# ---------------------------------------------------------------- RED
echo
echo "=== RED: the DEFAULT LOGDIR for model_9b_s (expect rc 4, no simulation)"
T0=$(date +%s)
( cd "$ROOT/evidence/qwen9b/g4" && bash "$RUN" model_9b_s --seeds 1 ) \
  > "$TMP/red.out" 2>&1
rc=$?
T1=$(date +%s)
sed 's/^/    /' "$TMP/red.out"
echo "    rc=$rc  wall=$((T1 - T0))s"
[ "$rc" = 4 ] || { echo "    UNEXPECTED rc: got $rc, expected 4"; FAIL=1; }
grep -q "REFUSING: .* holds TRACKED evidence" "$TMP/red.out" \
  || { echo "    MARKER NOT FOUND: 'REFUSING: ... holds TRACKED evidence'"; FAIL=1; }
# the refusal must precede every sign of a simulation
for m in "=== binary" "LAUNCH" "TB_SEQ_CHIP"; do
  if grep -q "$m" "$TMP/red.out"; then
    echo "    A SIMULATION WAS REACHED: '$m' is in the output"; FAIL=1; fi
done

# --------------------------------------------------------------- GREEN
echo
echo "=== GREEN: an UNTRACKED LOGDIR must not trigger it (real tok9b_s1 replay)"
mkdir -p "$GDIR"
echo "    LOGDIR = $GDIR  ($(git -C "$ROOT" ls-files "$GDIR" 2>/dev/null | wc -l) tracked file(s))"
T0=$(date +%s)
LOGDIR=$GDIR bash "$RUN" tok9b_s 1 > "$TMP/green.out" 2>&1
rc=$?
T1=$(date +%s)
grep -E "=== binary|LAUNCH|TB_SEQ_CHIP|G4A_REPLAY|REFUSING" "$TMP/green.out" \
  | sed 's/^/    /'
echo "    rc=$rc  wall=$((T1 - T0))s"
[ "$rc" = 0 ] || { echo "    UNEXPECTED rc: got $rc, expected 0"; FAIL=1; }
grep -q "REFUSING" "$TMP/green.out" \
  && { echo "    THE GUARD FIRED ON AN UNTRACKED DIRECTORY"; FAIL=1; }
grep -q "ALL PASS" "$TMP/green.out" \
  || { echo "    MARKER NOT FOUND: 'ALL PASS'"; FAIL=1; }

echo
if [ "$FAIL" = 0 ]; then
  echo "LOGDIR_GUARD_RED: PASS — the default LOGDIR for model_9b_s is REFUSED"
  echo "  (rc 4, no simulation) and an untracked LOGDIR still replays clean"
  exit 0
fi
echo "LOGDIR_GUARD_RED: FAIL"
exit 1
