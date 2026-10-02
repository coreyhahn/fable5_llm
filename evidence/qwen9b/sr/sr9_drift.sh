#!/usr/bin/env bash
# sr9_drift.sh — SR9 (the docs pass): the o3 cite-drift pass for the lines SR9
# moved in ONE edited document, since 544ee30 (SR9's base).  A copy of
# sr15_drift.sh's shape: docs are read from the committed tree (--doc-base,
# which MUST be a real commit — o3 accepts an unresolvable ref and reads 0
# citations, n1523; this wrapper refuses one), the historical records the
# earlier passes excluded stay excluded, plus:
#   * docs/HISTORY.md — a VERBATIM archive ("as it stood at <sha>"): its
#     tokens name the tree they were written against, never repaired;
#   * SR16's files (a concurrent task; SR9 never touches them) — any drifted
#     cite in them is REPORTED to the controller, not fixed.
#   evidence/qwen9b/sr/sr9_drift.sh <edited-doc> <doc-base> --plan|--fix|--verify [extra]
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
ED=${1:?edited doc}; DB=${2:?doc-base}; shift 2
git rev-parse --verify -q "$DB^{commit}" >/dev/null \
  || { echo "sr9_drift.sh: --doc-base '$DB' is not a commit — REFUSED" >&2; exit 2; }
EXCL_HIST=(--exclude docs/HISTORY.md)
[ "$ED" = docs/HISTORY.md ] && EXCL_HIST=()
exec /home/cah/.venv/bin/python evidence/qwen9b/o3/o3_cite_drift.py \
  --base 544ee30 --doc-base "$DB" --edited "$ED" \
  "${EXCL_HIST[@]}" \
  --exclude evidence/qwen9b/sr/SR16_R3_DECISION.md \
  --exclude evidence/qwen9b/sr/sr16_decision_table.py \
  --exclude evidence/qwen9b/sr/sr16_r3_census.py \
  --exclude evidence/qwen9b/sr/sr16_round_clock.sh \
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
  --exclude evidence/qwen9b/sr/sr15_drift.sh \
  --exclude evidence/qwen9b/sr/sr9_drift.sh \
  "$@"
