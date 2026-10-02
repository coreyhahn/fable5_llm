#!/usr/bin/env bash
# feas_run.sh — run one step of the Qwen3.5-next feasibility study ON SNOKE
# with a host/date/tree stamp, modelled on evidence/qwen2b/rd/rd_run.sh.
#   evidence/qwen_next/feas/feas_run.sh <log-name> <command...>
# Every numeric step of this study runs through this, so every log carries its
# own provenance. All numeric Python runs on snoke: darthplagueis produced
# wrong arithmetic 8x (docs/QWEN2B_QUANT_STUDY.md 6.4).
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
cd "$ROOT" || exit 1
LOG="$1"; shift
mkdir -p evidence/qwen_next/feas
{
  echo "=== host: $(hostname)  date: $(date -Is)"
  echo "=== tree: $(git rev-parse --short HEAD)$([ -n "$(git status --porcelain)" ] && echo +dirty)"
  echo "=== cmd : $*"
  echo "=== venv: $(/home/cah/.venv/bin/python -c 'import sys,numpy;print(sys.version.split()[0], "numpy", numpy.__version__)' 2>&1)"
  "$@"
  echo "=== rc  : $?"
  echo "=== end : $(date -Is)"
} 2>&1 | tee "evidence/qwen_next/feas/$LOG"
