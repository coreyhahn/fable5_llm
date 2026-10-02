#!/usr/bin/env bash
# Track L — the GPTQ calibration pass for one geometry.  RUN FROM SNOKE.
#
#   bash evidence/qwen_next/ladder/run_calib.sh <tag>      # 4b | 9b
#
# Same discipline as the 2B campaign (`docs/QWEN2B_QUANT_STUDY.md` §6.3.1):
# the calibration corpus is `ref/ppl_corpus_calib.txt` — the TRAIN slice,
# DISJOINT from the scored eval slice — and `calib_stats.main()` refuses the
# eval corpus by filename as a second line of defence.  `--hessian` adds the
# per-input-site second moment E[x x^T] that ref/gptq.py consumes.
#
# The npz is BIG and is deliberately not committed: one K x K float32 matrix
# per input site, 129 sites at 32 layers —
#   4B: 32*(2*2560^2 + 4096^2 + 9216^2) + 2560^2  = 13.71 GiB
#   9B: 32*(3*4096^2 + 12288^2)         + 4096^2  = 24.06 GiB
# (the 2B's was 4.5 GiB).  Delete it once both GPTQ points of that geometry
# have been scored — its sha256 and this log are the provenance.
set -u
cd "$(dirname "$0")/../../.."   # repo root
TAG=$1
OUT=ref/calib_stats_${TAG}_h.npz
LOG=evidence/qwen_next/ladder/calib_${TAG}.log
UV="$HOME/.local/bin/uv run --no-project --with torch --with transformers --with numpy python"
THREADS=8

df -h / | tail -1 > $LOG
FABLE5_MODEL=$TAG OMP_NUM_THREADS=$THREADS MKL_NUM_THREADS=$THREADS \
  nice -n 10 $UV ref/calib_stats.py \
    --corpus ref/ppl_corpus_calib.txt --out $OUT --hessian \
    --threads $THREADS >> $LOG 2>&1
# calib_stats.py already prints the npz's sha256 as its last line — do NOT
# re-checksum here: it is a second full read of a 13-24 GiB file over NFS.
ls -l $OUT >> $LOG
df -h / | tail -1 >> $LOG
echo "calib $TAG done: $(tail -3 $LOG | head -1)"
