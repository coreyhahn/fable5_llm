#!/usr/bin/env bash
# evidence/qwen9b/run.sh — the 9B campaign's provenance wrapper.
#
#   bash evidence/qwen9b/run.sh <log-name> <cmd> [args...]
#
# <log-name> is RELATIVE TO evidence/qwen9b/ (e.g. g1/smoke_int8_k6.log) and
# is NEVER overwritten: an existing log is a hard error, because a committed
# gate doc that cites a log by line is destroyed by a re-run in place (Track L
# did exactly that — plan "Standing hazards", global constraint "Never re-run a
# committed evidence script in place").  New runs get new names.
#
# Emits the R-c/R-d provenance header (host, date, tree sha + dirty flag, cmd,
# interpreter), runs "$@", then the return code and the end stamp, teeing
# everything to the log so stdout stays watchable.
#
# Style follows evidence/qwen2b/rc/t3_locks.sh: cd to the repo root first so
# every relative path in the command means the same thing on every host.
set -u
cd "$(dirname "$0")/../.."

if [ $# -lt 2 ]; then
  echo "usage: bash evidence/qwen9b/run.sh <log-name> <cmd> [args...]" >&2
  exit 2
fi
LOGNAME=$1; shift
LOG=evidence/qwen9b/$LOGNAME
if [ -e "$LOG" ]; then
  echo "REFUSING: $LOG exists — pick a new name (see the header of this file)" >&2
  exit 2
fi
mkdir -p "$(dirname "$LOG")"

# The interpreter answer is PER HOST and the only safe test is `test -x`
# (plan "Standing hazards"): ref/.venv/bin/python is a dangling symlink on
# snoke, /home/cah/.venv/bin/python does not exist on darthplagueis.  We do
# not choose one here — the commands below choose — but we RECORD what the
# two candidates are on THIS host so the gate doc never has to guess.
probe() { [ -x "$1" ] && echo "$1 (exists)" || echo "$1 (ABSENT)"; }

# THE OPERATING POINT, NOT THE ENVIRONMENT (RD9_GATE.md §22.12 A').  The
# `=== env:` line below prints `FABLE5_RS_F=unset`, which records the ABSENCE
# OF AN OVERRIDE and NOT THE VALUE IN FORCE: `evidence/qwen9b/g6/106_longctx_lockstep_ref.log:9`
# and `evidence/qwen9b/g6/149_15d_bisect_ref_N503.log:9` are the IDENTICAL
# line and the two runs executed at RS_F 8 and RS_F 7 — 12,096 wrong conv
# shifts in `106`, invisible for 17 h.  So ask the tools' own module what the
# derived value IS: `ref/layer_fixed.py`'s `RS_F_BY_TAG[model_select.TAG]`,
# imported the way `ref/gen_layer_script.py:44` imports it, through the same
# interpreter `=== venv:` records.
#
# TWO PROPERTIES THIS PROBE MUST HAVE.
#   * it REPORTS a disagreeing `FABLE5_RS_F` instead of dying on it.
#     `ref/layer_fixed.py:105`-`107` REFUSES a value that disagrees with the
#     law (that is the guard, and it stays the tools' job), so the probe
#     strips `FABLE5_RS_F`/`FABLE5_RS_F_RIDER` from ITS OWN environment and
#     prints the law beside the environment's value.  `derived=7 env=8` in a
#     header is the whole point: it is what `106`'s line 9 could not say.
#   * it can NEVER fail the wrapped command.  Every error path prints
#     `=== rs_f: unavailable (<reason>)` and returns 0.  A 17 h replay does
#     not die because a venv moved.
RSF_PY=
for _c in /home/cah/.venv/bin/python ref/.venv/bin/python; do
  [ -x "$_c" ] && { RSF_PY=$_c; break; }
done
rsf_line() {
  case "${FABLE5_RS_F_RIDER:-}" in 1|true|yes) _rider=1 ;; *) _rider=0 ;; esac
  _env=${FABLE5_RS_F:-unset}
  if [ -z "${FABLE5_MODEL:-}" ]; then
    echo "=== rs_f: derived=n/a (FABLE5_MODEL unset) env=$_env rider=$_rider"
    return 0
  fi
  if [ -z "$RSF_PY" ]; then
    echo "=== rs_f: unavailable (no interpreter: neither /home/cah/.venv/bin/python nor ref/.venv/bin/python is executable) env=$_env rider=$_rider"
    return 0
  fi
  _out=$(FABLE5_RS_F= FABLE5_RS_F_RIDER= "$RSF_PY" - <<'PYEOF' 2>&1
import os, sys
os.environ.pop("FABLE5_RS_F", None)        # the LAW, not the override
os.environ.pop("FABLE5_RS_F_RIDER", None)
sys.path.insert(0, os.path.join(os.getcwd(), "ref"))
import model_select as MS
import layer_fixed as LF
print("derived=%d (tag %s)" % (LF.RS_F, MS.TAG))
PYEOF
  )
  _rc=$?
  if [ $_rc -ne 0 ] || [ -z "$_out" ]; then
    echo "=== rs_f: unavailable (import rc=$_rc: $(echo "$_out" | tail -1)) env=$_env rider=$_rider"
    return 0
  fi
  echo "=== rs_f: $(echo "$_out" | tail -1) env=$_env rider=$_rider"
  return 0
}

{
  echo "=== host: $(hostname)"
  echo "=== date: $(date -Is)"
  echo "=== tree: $(git rev-parse --short HEAD 2>/dev/null)$(git diff --quiet 2>/dev/null || echo '+dirty')"
  echo "=== cmd:  $*"
  echo "=== venv: $(probe /home/cah/.venv/bin/python)"
  echo "===       $(probe ref/.venv/bin/python)"
  echo "===       uv: $(probe "$HOME/.local/bin/uv")"
  # `nproc` HONOURS OMP_NUM_THREADS, so it would echo the pinning back at us
  # instead of describing the machine; --all is the machine.
  echo "=== cpu:  nproc=$(nproc --all) OMP_NUM_THREADS=${OMP_NUM_THREADS:-unset} MKL_NUM_THREADS=${MKL_NUM_THREADS:-unset}"
  echo "=== env:  FABLE5_MODEL=${FABLE5_MODEL:-unset} FABLE5_DN_STATE=${FABLE5_DN_STATE:-unset} FABLE5_RS_F=${FABLE5_RS_F:-unset}"
  echo "===       FABLE5_CALIB_STATS=${FABLE5_CALIB_STATS:-unset} FABLE5_CALIB_MODE=${FABLE5_CALIB_MODE:-unset}"
  rsf_line
  echo "=== ---"
} 2>&1 | tee "$LOG"

set +e
"$@" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
set -e
{
  echo "=== rc: $RC"
  echo "=== end: $(date -Is)"
} 2>&1 | tee -a "$LOG"
exit "$RC"
