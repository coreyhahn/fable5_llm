#!/usr/bin/env bash
# rd_run.sh — run one Task-6 (R-d) step ON SNOKE with a host/date/tree stamp.
#   evidence/qwen2b/rd/rd_run.sh <log-name> <command...>
# Every hardware and numeric step of R-d runs through this, so every log
# carries its own provenance (the R-b gate was burned by an un-tee'd
# VERSION readback — nothing here is read without a log).
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
cd "$ROOT" || exit 1
LOG="$1"; shift
{
  echo "=== host: $(hostname)  date: $(date -Is)"
  echo "=== tree: $(git rev-parse --short HEAD)$([ -n "$(git status --porcelain)" ] && echo +dirty)"
  echo "=== cmd : $*"
  echo "=== venv: $(/home/cah/.venv/bin/python -c 'import sys,numpy;print(sys.version.split()[0], "numpy", numpy.__version__)' 2>&1)"
  "$@"
  echo "=== rc  : $?"
  echo "=== end : $(date -Is)"
} 2>&1 | tee "evidence/qwen2b/rd/$LOG"
