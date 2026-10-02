#!/usr/bin/env bash
# sr6_drift.sh — Task SR6: the o3 citation-drift pass after SR6's host edits
# (sw/seq_run.py, sw/chat_seq.py, sw/serve.py), at base 7e72126 (SR6's
# parent).  One place for the argument list so --plan, --fix and --verify
# ask the SAME question.
#   evidence/qwen9b/sr/sr6_drift.sh --plan|--fix|--verify|--check [extra]
# Run through evidence/qwen9b/sr/sr_run.sh on snoke (log block n600-n699).
#
# --exclude: evidence/qwen9b/sr/SR6_HOST.md is SR6's gate doc, written in
# post-SR6 coordinates (not in the 7e72126 tree; excluded by name so the log
# says so).  The o3 tool's own docstring is excluded as it asks.
#   evidence/qwen9b/s3/S3_CHAIN.md: its only two tokens (sw/chat_seq.py:441-462
#     and :579) sit in its hand-repair TABLE, a record of coordinates at an
#     earlier repair (and already stale in content at 7e72126); not re-aimed.
#   tb/tb_seq_chip.sv: SR5a's territory (tb/), never touched by SR6; its one
#     comment token (sw/seq_run.py:1242, already stale in content at
#     7e72126: it names EMBLOG2 programming, the line is BM_IDENT) is left
#     for its owner and recorded in SR6_HOST.md.
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
exec /home/cah/.venv/bin/python evidence/qwen9b/o3/o3_cite_drift.py \
  --base 7e72126 \
  --edited sw/seq_run.py,sw/chat_seq.py,sw/serve.py \
  --exclude evidence/qwen9b/sr/SR6_HOST.md \
  --exclude evidence/qwen9b/o3/o3_cite_drift.py \
  --exclude evidence/qwen9b/s3/S3_CHAIN.md \
  --exclude tb/tb_seq_chip.sv \
  "$@"
