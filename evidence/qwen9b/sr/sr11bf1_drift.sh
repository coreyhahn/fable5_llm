#!/usr/bin/env bash
# sr11bf1_drift.sh — SR11b fix round 1 (review I2): the o3 cite-drift pass
# for the lines SR11b moved since 99c13ce in ref/scripts/reorder_e4.py,
# ref/seq_cost.py and evidence/qwen9b/ov/ov_census.py.  Docs are read from
# the committed tree (--doc-base).  Excluded: every document first committed
# after 99c13ce (their cites were written against the post-edit lines and
# must not be shifted) — SR11b's own gate doc and scripts, SR13b's gate doc
# and scripts, SR11a fix3's and SR7 fix1's new scripts — plus the standing
# exclusions of sr7f1_drift.sh / sr13b_drift.sh (o3's docstring, S3_CHAIN,
# tb_seq_chip.sv, the hand-repair records and drift scripts).
#   evidence/qwen9b/sr/sr11bf1_drift.sh <reorder|cost|census> <doc-base> --plan|--fix|--verify [extra]
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
W=${1:?}; DB=${2:?}; shift 2
case "$W" in
  reorder) E=ref/scripts/reorder_e4.py ;;
  cost)    E=ref/seq_cost.py ;;
  census)  E=evidence/qwen9b/ov/ov_census.py ;;
  *) echo "usage"; exit 2 ;;
esac
exec /home/cah/.venv/bin/python evidence/qwen9b/o3/o3_cite_drift.py \
  --base 99c13ce --doc-base "$DB" --edited "$E" \
  --exclude evidence/qwen9b/sr/SR11b_R2_PASS.md \
  --exclude evidence/qwen9b/sr/sr11b_gate.sh \
  --exclude evidence/qwen9b/sr/sr11b_model_correction.py \
  --exclude evidence/qwen9b/sr/sr11b_pass_tdd.py \
  --exclude evidence/qwen9b/sr/sr11b_r2_check.py \
  --exclude evidence/qwen9b/sr/sr11bf1_drift.sh \
  --exclude evidence/qwen9b/sr/SR13b_HOST_R2.md \
  --exclude evidence/qwen9b/sr/sr13b_drift.sh \
  --exclude evidence/qwen9b/sr/sr13b_host_tdd.py \
  --exclude evidence/qwen9b/sr/sr13b_r2_pins.py \
  --exclude evidence/qwen9b/sr/sr11a_fix3_host_tdd.py \
  --exclude evidence/qwen9b/sr/sr7f1_clock_guidance2.tcl \
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
