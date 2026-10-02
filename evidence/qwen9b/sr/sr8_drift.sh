#!/usr/bin/env bash
# sr8_drift.sh — SR8: the o3 cite-drift pass for the lines SR8 moved in
# NEXT_SESSION.md (its §1 gained an 11-line paragraph and §1/§3/§6 rows were
# rewritten, commit ac16a0d) since a4cf5e6 (SR8's base).  Docs are read from
# the committed tree (--doc-base).  Excluded: SR8's own gate doc (written in
# the final coordinates), o3's own docstring, and the historical records the
# earlier passes excluded (sr13b_drift.sh's list).
#   evidence/qwen9b/sr/sr8_drift.sh <doc-base> --plan|--fix|--verify [extra]
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
DB=${1:?}; shift
exec /home/cah/.venv/bin/python evidence/qwen9b/o3/o3_cite_drift.py \
  --base a4cf5e6 --doc-base "$DB" --edited NEXT_SESSION.md \
  --exclude evidence/qwen9b/sr/SR8_R1_BOARD.md \
  --exclude evidence/qwen9b/o3/o3_cite_drift.py \
  --exclude evidence/qwen9b/s3/S3_CHAIN.md \
  --exclude tb/tb_seq_chip.sv \
  --exclude evidence/qwen9b/sr/sr6_hand_repairs.py \
  --exclude evidence/qwen9b/sr/sr6_drift.sh \
  --exclude evidence/qwen9b/sr/sr6fix1_hand_repairs.py \
  --exclude evidence/qwen9b/sr/sr6fix1_drift.sh \
  --exclude evidence/qwen9b/sr/sr7_drift.sh \
  --exclude evidence/qwen9b/sr/sr7f1_drift.sh \
  "$@"
