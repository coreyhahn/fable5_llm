#!/usr/bin/env bash
# Track Q V4 scoring runs — all four share corpus/positions/res-scale/calib npz
# and differ in ONE thing: the W4 group-scale/rounding rule.
cd "$(dirname "$0")/../../../.."   # repo root
UV="$HOME/.local/bin/uv run --no-project --with torch --with transformers --with numpy python"
OUT=evidence/qwen2b/q2/v4
NPZ=ref/calib_stats_2b_h.npz
run() {   # $1 = tag, $2 = quant
  FABLE5_MODEL=2b OMP_NUM_THREADS=10 nohup nice -n 5 $UV ref/perplexity_eval.py \
    --corpus ref/ppl_corpus_eval.txt \
    --inject "all:$2,dn_conv:cw13,emb:emb16" \
    --calib-stats $NPZ --res-scale 8 \
    --json-out $OUT/ppl_$1.json > $OUT/ppl_$1.log 2>&1 &
}
run v3_recal   w4g64s
run v4h        w4g64h
run v4gptq     w4g64gptq
run v4gptq_rerun w4g64gptq
sleep 2
echo "launched 4"
