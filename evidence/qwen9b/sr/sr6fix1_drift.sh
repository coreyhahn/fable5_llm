#!/usr/bin/env bash
# sr6fix1_drift.sh — SR6 fix round 1: the o3 citation-drift pass after the
# fix's sw/seq_run.py edit (docstring + --caps help + the dry-run stop), at
# base 3b3c727 (the fix round's parent).  Excludes as sr6_drift.sh, plus the
# gate doc (edited in post-fix coordinates by hand), and SR6's own two
# records (sr6_hand_repairs.py, n617's list in 013d9a3 coordinates;
# sr6_drift.sh's comment naming tb_seq_chip's stale token).
#   evidence/qwen9b/sr/sr6fix1_drift.sh --plan|--fix|--verify|--check [extra]
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
exec /home/cah/.venv/bin/python evidence/qwen9b/o3/o3_cite_drift.py \
  --base 3b3c727 \
  --edited sw/seq_run.py \
  --exclude evidence/qwen9b/sr/SR6_HOST.md \
  --exclude evidence/qwen9b/o3/o3_cite_drift.py \
  --exclude evidence/qwen9b/s3/S3_CHAIN.md \
  --exclude tb/tb_seq_chip.sv \
  --exclude evidence/qwen9b/sr/sr6_hand_repairs.py \
  --exclude evidence/qwen9b/sr/sr6_drift.sh \
  "$@"
