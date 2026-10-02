#!/usr/bin/env bash
# r3_4_drift.sh — Task R3-4 (R3 campaign): the o3 cite-drift pass for the lines
# R3-4's comment/docstring/selftest edit moved in ref/seq_cost.py.  The shape
# of r3_2_drift.sh: BOTH the code base and the documents' base MUST be real
# commits (o3 accepts an unresolvable ref and reads 0 citations, n1523; this
# wrapper refuses one).  The code base is the commit before R3-4's seq_cost
# edit; its seq_cost.py is byte-identical to 0cf3f1f's, the version every
# live citation into it was last verified against (SR11b fix round 1, SR11c).
# Excluded: R3-4's own gate doc (written in post-edit coordinates);
# SR11c_CITE_DRIFT.md (its seq_cost tokens are the RECORD of where SR11c
# aimed each repair — historical, kept); the concurrent tasks' files (R3-0,
# R3-3 — a drifted cite there is REPORTED, not fixed); and the standing
# exclusions of r3_2_drift.sh (o3's own docstring, S3_CHAIN, tb_seq_chip.sv,
# the hand-repair records and the drift scripts).
#   evidence/qwen9b/sr/r3_4_drift.sh <code-base> <doc-base> --plan|--fix|--verify [extra]
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
B=${1:?code-base}; DB=${2:?doc-base}; shift 2
for c in "$B" "$DB"; do
  git rev-parse --verify -q "$c^{commit}" >/dev/null \
    || { echo "r3_4_drift.sh: '$c' is not a commit — REFUSED" >&2; exit 2; }
done
exec /home/cah/.venv/bin/python evidence/qwen9b/o3/o3_cite_drift.py \
  --base "$B" --doc-base "$DB" --edited ref/seq_cost.py \
  --exclude docs/HISTORY.md \
  --exclude evidence/qwen9b/sr/R3_4_COST.md \
  --exclude evidence/qwen9b/sr/r3_4_cost.py \
  --exclude evidence/qwen9b/sr/r3_4_drift.sh \
  --exclude evidence/qwen9b/sr/SR11c_CITE_DRIFT.md \
  --exclude evidence/qwen9b/sr/R3_0_TOOLING.md \
  --exclude evidence/qwen9b/sr/R3_3_MODEL.md \
  --exclude evidence/qwen9b/sr/r3_preflight.sh \
  --exclude evidence/qwen9b/sr/r3_2_drift.sh \
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
  --exclude evidence/qwen9b/sr/sr9_drift.sh \
  --exclude evidence/qwen9b/sr/sr11a_drift.sh \
  --exclude evidence/qwen9b/sr/sr11af2_drift.sh \
  --exclude evidence/qwen9b/sr/sr11bf1_drift.sh \
  --exclude evidence/qwen9b/sr/sr11c_drift.sh \
  --exclude evidence/qwen9b/sr/sr13b_drift.sh \
  --exclude evidence/qwen9b/sr/sr3c_drift.sh \
  --exclude evidence/qwen9b/sr/sr15_drift.sh \
  --exclude evidence/qwen9b/sr/sr17_drift.sh \
  "$@"
