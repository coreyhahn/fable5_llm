#!/usr/bin/env bash
# sr11a_drift.sh — Task SR11a: the o3 citation-drift question after SR11a's
# edits (ref/seq_format.py, ref/seq_model.py, docs/SEQ_ISA.md) at base
# 7e64d05 (the parent of the implementation commit d501068).  One place for
# the argument list so --plan / --check / --verify ask the SAME question.
#   evidence/qwen9b/sr/sr11a_drift.sh --plan|--check|--fix|--verify [extra]
# Run through evidence/qwen9b/sr/sr_run.sh on snoke (log block n1100-n1149).
# Excluded: SR11a's own gate doc (written in post-SR11a coordinates) and the
# o3 tool's own docstring, as it asks.
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
exec /home/cah/.venv/bin/python evidence/qwen9b/o3/o3_cite_drift.py \
  --base 7e64d05 \
  --edited ref/seq_format.py,ref/seq_model.py,docs/SEQ_ISA.md \
  --exclude evidence/qwen9b/sr/SR11a_R2_MODEL.md \
  --exclude evidence/qwen9b/o3/o3_cite_drift.py \
  "$@"
