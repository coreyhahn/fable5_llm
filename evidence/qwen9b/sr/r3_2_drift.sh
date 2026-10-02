#!/usr/bin/env bash
# r3_2_drift.sh — Task R3-2 (R3 campaign): the o3 cite-drift pass for the lines
# R3-2's validator edit moved in ref/seq_format.py (implementation commit
# dfd8863, parent 15132b2 = --base).  A copy of sr17_drift.sh's shape:
# documents are read from the committed tree at --doc-base, which MUST be a
# real commit (o3 accepts an unresolvable ref and reads 0 citations, n1523;
# this wrapper refuses one), and the historical records the earlier passes
# excluded stay excluded.  Also excluded: R3-2's own gate doc (written in
# post-edit coordinates) and the concurrent task R3-0's files (a drifted cite
# there is REPORTED to the controller, not fixed).
#   evidence/qwen9b/sr/r3_2_drift.sh <doc-base> --plan|--fix|--verify [extra]
# Task R3-3 flags ("flags, not copies"; defaults = R3-2's run, so its logs
# reproduce): R3_DRIFT_BASE (the code base, default 15132b2), R3_DRIFT_EDITED
# (the edited file, default ref/seq_format.py), R3_DRIFT_EXCLUDE (extra
# space-separated --exclude paths, e.g. the calling task's own gate doc).
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
DB=${1:?doc-base}; shift
git rev-parse --verify -q "$DB^{commit}" >/dev/null \
  || { echo "r3_2_drift.sh: --doc-base '$DB' is not a commit — REFUSED" >&2; exit 2; }
git rev-parse --verify -q "${R3_DRIFT_BASE:-15132b2}^{commit}" >/dev/null \
  || { echo "r3_2_drift.sh: R3_DRIFT_BASE '${R3_DRIFT_BASE:-}' is not a commit — REFUSED" >&2; exit 2; }
exec /home/cah/.venv/bin/python evidence/qwen9b/o3/o3_cite_drift.py \
  --base "${R3_DRIFT_BASE:-15132b2}" --doc-base "$DB" \
  --edited "${R3_DRIFT_EDITED:-ref/seq_format.py}" \
  $(for x in ${R3_DRIFT_EXCLUDE:-}; do printf -- '--exclude %s ' "$x"; done) \
  --exclude docs/HISTORY.md \
  --exclude evidence/qwen9b/sr/R3_2_VALIDATOR.md \
  --exclude evidence/qwen9b/sr/R3_0_TOOLING.md \
  --exclude evidence/qwen9b/sr/r3_preflight.sh \
  --exclude evidence/qwen9b/sr/r3_2_drift.sh \
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
  --exclude evidence/qwen9b/sr/sr17_drift.sh \
  "$@"
