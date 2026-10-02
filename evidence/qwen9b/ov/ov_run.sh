#!/usr/bin/env bash
# ov_run.sh — run one step of the OVERLAP dependency census (Task OV1) ON SNOKE
# with a host/date/tree stamp; a copy of evidence/qwen_next/nvfp4/nvfp4_run.sh
# (its tree-stamp-before-tee fix, dirty detail and named-interpreter line kept),
# retargeted to evidence/qwen9b/ov/.  OV1 change: only UNTRACKED LOGS (*.log)
# under evidence/qwen9b/ov/ are excluded from the dirty stamp, so an
# uncommitted SCRIPT there still stamps +dirty; and the env line records
# FABLE5_MODEL (the operating point).
#   evidence/qwen9b/ov/ov_run.sh <log-name> <command...>
# Every numeric step of this study runs through this, so every log carries its
# own provenance. All numeric Python runs on snoke: darthplagueis produced
# wrong arithmetic 8x (docs/QWEN2B_QUANT_STUDY.md 6.4).
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
cd "$ROOT" || exit 1
LOG="$1"; shift
mkdir -p evidence/qwen9b/ov
# never overwrite a log (task 2B1 rule): refuse rather than clobber.
if [ -e "evidence/qwen9b/ov/$LOG" ]; then
  echo "ov_run.sh: REFUSING to overwrite evidence/qwen9b/ov/$LOG" >&2
  exit 2
fi
# The tree stamp is computed BEFORE the tee pipeline below.  feas_run.sh
# evaluates it INSIDE the block that is piped into `tee <the log>`, so bash has
# already created the (untracked) log file by then and `git status --porcelain`
# always sees at least that -- every log of the earlier feas/ study reads
# "+dirty" for that reason alone, on a clean tree as much as a dirty one.
# Excluding the log's own path makes the stamp mean something.  (Task 2B1 fix
# round 1, finding M-12; logs f01..f14 were written by the un-fixed version.)
# NV1 addition: two classes of UNTRACKED paths are also excluded, because
# neither is an input to any run: the BN1 CSVs/seedlogs under
# evidence/qwen9b/bn/ (uncommitted by design since c84a55b) and the other
# in-flight OUTPUTS of this study (rung-1 rows run in parallel, so a sibling
# run's log/json is untracked while this one starts).  A MODIFIED tracked file
# anywhere, and any other untracked file, still stamps "+dirty".
TREE="$(git rev-parse --short HEAD)"
DIRTY="$(git status --porcelain | grep -v -F -- "evidence/qwen9b/ov/$LOG" \
      | grep -v -E "^\?\? evidence/qwen9b/bn/" \
      | grep -v -E "^\?\? evidence/qwen9b/ov/[^/]*\.log$")"
if [ -n "$DIRTY" ]; then
  TREE="$TREE+dirty"
fi
# NV1 fix round 1 (M3): the venv line reports the interpreter the COMMAND
# names (the first argument ending in /python or /python3), falling back to
# the shipped venv only when the command names none — a P40 run uses
# /home/cah/.venv_nvfp4_cuda and its log must say so.
PY=/home/cah/.venv/bin/python
PYSRC="shipped venv (no interpreter named in cmd)"
for arg in "$@"; do
  case "$arg" in
    */python|*/python3) PY="$arg"; PYSRC="named in cmd"; break ;;
  esac
done
{
  echo "=== host: $(hostname)  date: $(date -Is)"
  echo "=== tree: $TREE"
  # NV1 fix round 1 (M1): a +dirty stamp records WHAT was dirty
  if [ -n "$DIRTY" ]; then
    printf '%s\n' "$DIRTY" | sed 's/^/=== dirty: /'
  fi
  echo "=== cmd : $*"
  echo "=== env : FABLE5_MODEL=${FABLE5_MODEL:-unset}"
  echo "=== venv: $PY ($PYSRC): $("$PY" -c 'import sys,numpy;print(sys.version.split()[0], "numpy", numpy.__version__)' 2>&1)"
  "$@"
  echo "=== rc  : $?"
  echo "=== end : $(date -Is)"
} 2>&1 | tee "evidence/qwen9b/ov/$LOG"
