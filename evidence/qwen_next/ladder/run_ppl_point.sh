#!/usr/bin/env bash
# Track L — one point of the qwen-next quality ladder.  RUN FROM SNOKE.
#
#   bash evidence/qwen_next/ladder/run_ppl_point.sh <tag> <point> [nohup]
#     tag   : 4b | 9b   (FABLE5_MODEL)
#     point : bf16 | w4g128 | w4g64 | w8g128 | w4g128gptq | w4g64gptq
#
# The injection specs REPRODUCE the 2B study's exactly
# (`docs/QWEN2B_QUANT_STUDY.md` §8, the committed q1/q2 jsons):
#   anchor  : no --inject, no --res-scale (res_scale has no meaning without
#             emb16 and perplexity_eval.check_res_scale rejects the pair)
#   variant : `all:<quant>,dn_conv:cw13,emb:emb16 --res-scale 8`
# so every cross-study delta is single-variable.  This campaign PINS the
# thread count at 6 everywhere, at both geometries, because the feasibility
# study's :1173 records that its own priced five ran at 6/6/6/10/8 and are
# therefore "a real elapsed cost on this machine but not a controlled
# per-point comparison".  (That figure is the feasibility study's caveat --
# an earlier version of this comment mis-attributed it to a "§6.5" of
# docs/QWEN2B_QUANT_STUDY.md and called it an instruction.)
set -u
cd "$(dirname "$0")/../../.."   # repo root
TAG=$1; POINT=$2
OUT=evidence/qwen_next/ladder/ppl_${TAG}_${POINT}
UV="$HOME/.local/bin/uv run --no-project --with torch --with transformers --with numpy python"
TAIL=dn_conv:cw13,emb:emb16
CALIB=ref/calib_stats_${TAG}_h.npz
THREADS=6
# THE PINNED-CORPUS GATE.  Until 2026-08-26 this campaign said "corpus sha
# verified before use" while the sha was only RECORDED into the json -- a
# description of a gate that did not exist.  It exists now: perplexity_eval
# refuses to score if ref/ppl_corpus_eval.txt does not hash to this.  The
# value is the 2B study's pinned eval corpus (docs/QWEN2B_QUANT_STUDY.md,
# feasibility study section 5), and it is what makes every cross-study delta
# in evidence/qwen_next/ladder/LADDER.md section 3 legitimate.
CORPUS_SHA=6bf4f8677a3b3fff178c6915e2a55b7326e534f6e54650067e33b056e4c27876

case "$POINT" in
  bf16)        ARGS="" ;;
  w4g128)      ARGS="--inject all:w4g128,$TAIL --res-scale 8" ;;
  w4g64)       ARGS="--inject all:w4g64,$TAIL  --res-scale 8" ;;
  w8g128)      ARGS="--inject all:w8g128,$TAIL --res-scale 8" ;;
  w4g128gptq)  ARGS="--inject all:w4g128gptq,$TAIL --res-scale 8 --calib-stats $CALIB" ;;
  w4g64gptq)   ARGS="--inject all:w4g64gptq,$TAIL  --res-scale 8 --calib-stats $CALIB" ;;
  *) echo "unknown point $POINT" >&2; exit 2 ;;
esac

FABLE5_MODEL=$TAG OMP_NUM_THREADS=$THREADS MKL_NUM_THREADS=$THREADS \
  nice -n 10 $UV ref/perplexity_eval.py \
    --corpus ref/ppl_corpus_eval.txt --expect-corpus-sha256 $CORPUS_SHA \
    --threads $THREADS $ARGS \
    --json-out $OUT.json > $OUT.log 2>&1
echo "$TAG/$POINT -> $(tail -1 $OUT.log)"
