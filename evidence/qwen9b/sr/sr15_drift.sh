#!/usr/bin/env bash
# sr15_drift.sh — SR15: the o3 cite-drift pass for the lines SR15 moved in
# NEXT_SESSION.md (its §1 gained a 10-line paragraph, §1/§3 rows were rewritten and
# §6 gained an R2 paragraph, commit 4a02083) since 2c66d67 (SR15's base). Docs from
# the committed tree (--doc-base).  Excluded: SR15's own gate doc (written in
# the final coordinates), o3's own docstring, and the historical records the
# earlier passes excluded (sr8_drift.sh's list, plus sr8_drift.sh itself).
#   evidence/qwen9b/sr/sr15_drift.sh <doc-base> --plan|--fix|--verify [extra]
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
DB=${1:?}; shift
exec /home/cah/.venv/bin/python evidence/qwen9b/o3/o3_cite_drift.py \
  --base 2c66d67 --doc-base "$DB" --edited NEXT_SESSION.md \
  --exclude evidence/qwen9b/sr/SR15_R2_BOARD.md \
  --exclude evidence/qwen9b/o3/o3_cite_drift.py \
  --exclude evidence/qwen9b/s3/S3_CHAIN.md \
  --exclude tb/tb_seq_chip.sv \
  --exclude evidence/qwen9b/sr/sr6_hand_repairs.py \
  --exclude evidence/qwen9b/sr/sr6_drift.sh \
  --exclude evidence/qwen9b/sr/sr6fix1_hand_repairs.py \
  --exclude evidence/qwen9b/sr/sr6fix1_drift.sh \
  --exclude evidence/qwen9b/sr/sr7_drift.sh \
  --exclude evidence/qwen9b/sr/sr7f1_drift.sh \
  --exclude evidence/qwen9b/sr/sr8_drift.sh \
  "$@"
