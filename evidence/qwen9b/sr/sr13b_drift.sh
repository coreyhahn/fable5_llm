#!/usr/bin/env bash
# sr13b_drift.sh — SR13b: the o3 cite-drift PLAN for the lines SR13b moved in
# sw/seq_run.py and sw/chat_seq.py since 966cbcf (SR13b's base; commit
# 3eb0728 is the only edit to either file since).  Docs are read from the
# committed tree (--doc-base).  Excluded: SR13b's own gate doc, the drift /
# hand-repair records of SR6 / SR7, o3's own docstring, and the historical
# records every earlier pass excluded (S3_CHAIN.md, tb/tb_seq_chip.sv).
#   evidence/qwen9b/sr/sr13b_drift.sh <seq_run|chat_seq> <doc-base> --plan [extra]
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
W=${1:?}; DB=${2:?}; shift 2
case "$W" in
  seq_run)  E=sw/seq_run.py ;;
  chat_seq) E=sw/chat_seq.py ;;
  *) echo "usage"; exit 2 ;;
esac
exec /home/cah/.venv/bin/python evidence/qwen9b/o3/o3_cite_drift.py \
  --base 966cbcf --doc-base "$DB" --edited "$E" \
  --exclude evidence/qwen9b/sr/SR13b_HOST_R2.md \
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
