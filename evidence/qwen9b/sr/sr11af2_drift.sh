#!/usr/bin/env bash
# sr11af2_drift.sh — SR11a fix round 2: the o3 citation-drift question over
# the fix's host edits (sw/seq_run.py, sw/chat_seq.py, ref/seq_chat.py) at
# base 9c8e73b (the parent of cfbf90f).  One place for the argument list so
# --plan / --fix / --verify ask the same question.  The o3 docstring is
# excluded as it asks.  Pass --only-docs to restrict the pass.
#   evidence/qwen9b/sr/sr11af2_drift.sh --plan|--check|--fix|--verify [extra]
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
exec /home/cah/.venv/bin/python evidence/qwen9b/o3/o3_cite_drift.py \
  --base 9c8e73b \
  --edited sw/seq_run.py,sw/chat_seq.py,ref/seq_chat.py \
  --exclude evidence/qwen9b/o3/o3_cite_drift.py \
  "$@"
