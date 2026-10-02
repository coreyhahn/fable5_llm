#!/usr/bin/env bash
# feas2_run.sh — run one step of the Qwen3.5-next feasibility study (TWO-BOARD) ON SNOKE
# with a host/date/tree stamp, modelled on evidence/qwen2b/rd/rd_run.sh.
#   evidence/qwen_next/feas2/feas2_run.sh <log-name> <command...>
# Every numeric step of this study runs through this, so every log carries its
# own provenance. All numeric Python runs on snoke: darthplagueis produced
# wrong arithmetic 8x (docs/QWEN2B_QUANT_STUDY.md 6.4).
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
cd "$ROOT" || exit 1
LOG="$1"; shift
mkdir -p evidence/qwen_next/feas2
# never overwrite a log (task 2B1 rule): refuse rather than clobber.
if [ -e "evidence/qwen_next/feas2/$LOG" ]; then
  echo "feas2_run.sh: REFUSING to overwrite evidence/qwen_next/feas2/$LOG" >&2
  exit 2
fi
# The tree stamp is computed BEFORE the tee pipeline below.  feas_run.sh
# evaluates it INSIDE the block that is piped into `tee <the log>`, so bash has
# already created the (untracked) log file by then and `git status --porcelain`
# always sees at least that -- every log of the earlier feas/ study reads
# "+dirty" for that reason alone, on a clean tree as much as a dirty one.
# Excluding the log's own path makes the stamp mean something.  (Task 2B1 fix
# round 1, finding M-12; logs f01..f14 were written by the un-fixed version.)
TREE="$(git rev-parse --short HEAD)"
if [ -n "$(git status --porcelain | grep -v -F -- "evidence/qwen_next/feas2/$LOG")" ]; then
  TREE="$TREE+dirty"
fi
{
  echo "=== host: $(hostname)  date: $(date -Is)"
  echo "=== tree: $TREE"
  echo "=== cmd : $*"
  echo "=== venv: $(/home/cah/.venv/bin/python -c 'import sys,numpy;print(sys.version.split()[0], "numpy", numpy.__version__)' 2>&1)"
  "$@"
  echo "=== rc  : $?"
  echo "=== end : $(date -Is)"
} 2>&1 | tee "evidence/qwen_next/feas2/$LOG"
