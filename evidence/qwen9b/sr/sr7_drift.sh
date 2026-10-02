#!/usr/bin/env bash
# sr7_drift.sh — SR7's o3 citation-drift pass over its host-step edits
# (sw/seq_run.py: the SEQ_VERSIONS 3-tuples + the gate's SEQ_CAPS compare +
# the R1 row; sw/hwmap.py: the R1 SHAPE row; evidence/qwen9b/bm/bm1_ident.py:
# the SEQ_CAPS read), at base 6a5a8b8 (the parent of SR7's first host commit
# 3dcb045).  Citing documents are read from the COMMITTED tree HEAD at the
# time of the run (--doc-base), so no concurrent task's uncommitted edit is
# read or written.  Excluded: SR7's own gate doc (written in final
# coordinates), o3_cite_drift.py's docstring, the documents SR6's passes
# excluded for their own reasons, and the files of the concurrent task SR11a
# (docs/SEQ_ISA.md, ref/seq_format.py, ref/seq_model.py) — never touched.
#   evidence/qwen9b/sr/sr7_drift.sh <doc-base> --plan|--fix|--verify [extra]
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
DB=${1:?usage: sr7_drift.sh <doc-base> --plan|--fix|--verify}; shift
exec /home/cah/.venv/bin/python evidence/qwen9b/o3/o3_cite_drift.py \
  --base 6a5a8b8 --doc-base "$DB" \
  --edited sw/seq_run.py,sw/hwmap.py,evidence/qwen9b/bm/bm1_ident.py \
  --exclude evidence/qwen9b/sr/SR7_R1_BUILD.md \
  --exclude evidence/qwen9b/o3/o3_cite_drift.py \
  --exclude evidence/qwen9b/s3/S3_CHAIN.md \
  --exclude tb/tb_seq_chip.sv \
  --exclude evidence/qwen9b/sr/sr6_hand_repairs.py \
  --exclude evidence/qwen9b/sr/sr6_drift.sh \
  --exclude evidence/qwen9b/sr/sr6fix1_hand_repairs.py \
  --exclude evidence/qwen9b/sr/sr6fix1_drift.sh \
  --exclude docs/SEQ_ISA.md \
  --exclude ref/seq_format.py \
  --exclude ref/seq_model.py \
  "$@"
