#!/usr/bin/env bash
# sr7f1_drift.sh — SR7 fix round 1: the o3 cite-drift pass for the lines
# moved in sw/seq_run.py since 925d29d^ (SR7 M-4's +18 selftest lines at the
# SEQ_VERSIONS admission block, and SR11a fix3's fa7f5df edits after it, which
# re-aimed only SR11a's own doc) and in sw/hwmap.py since c8aef0e^ (SR7 I-1's
# BM_IDENT table before the __main__ guard; SR11a fix3's build_042 SHAPE row).
# Docs are read from the committed tree (--doc-base).  Excluded: SR7's gate
# doc, SR11a's gate doc (re-aimed by its owner), the hand-repair records and
# drift scripts of SR6/SR7, o3's own docstring.
#   evidence/qwen9b/sr/sr7f1_drift.sh <seq_run|hwmap> <doc-base> --plan|--fix|--verify [extra]
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
W=${1:?}; DB=${2:?}; shift 2
case "$W" in
  seq_run) B=925d29d^; E=sw/seq_run.py ;;
  hwmap)   B=c8aef0e^; E=sw/hwmap.py ;;
  *) echo "usage"; exit 2 ;;
esac
exec /home/cah/.venv/bin/python evidence/qwen9b/o3/o3_cite_drift.py \
  --base "$(git rev-parse --short "$B")" --doc-base "$DB" --edited "$E" \
  --exclude evidence/qwen9b/sr/SR7_R1_BUILD.md \
  --exclude evidence/qwen9b/sr/SR11a_R2_MODEL.md \
  --exclude evidence/qwen9b/o3/o3_cite_drift.py \
  --exclude evidence/qwen9b/s3/S3_CHAIN.md \
  --exclude tb/tb_seq_chip.sv \
  --exclude evidence/qwen9b/sr/sr6_hand_repairs.py \
  --exclude evidence/qwen9b/sr/sr6_drift.sh \
  --exclude evidence/qwen9b/sr/sr6fix1_hand_repairs.py \
  --exclude evidence/qwen9b/sr/sr6fix1_drift.sh \
  --exclude evidence/qwen9b/sr/sr7_drift.sh \
  "$@"
