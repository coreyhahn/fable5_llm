#!/usr/bin/env bash
# Track Q V5 + V4mix scoring runs (Task 9).  All five share corpus, window,
# batch, res-scale and checkpoint with V1/V2/V3/V4gptq and with the bf16
# anchor; they differ ONLY in which classes carry W8 rows.
#
#   V5        every W4A8 matvec class at W8            (the "W8 everywhere" point)
#   V4mix-k   the k most PPL-sensitive classes at W8   (Task 7's ranking:
#             gate_up > lm_head > dn_in > down > o_proj > qkv > dn_out),
#             the rest at w4g64 = V2's rule, so the ladder's baseline is V2.
#
# No --calib-stats: neither w4g64 nor w8g128 consumes calibration statistics
# (the harness rejects the flag when nothing in the plan would use it).
# ALL COMPUTE ON SNOKE (Q8's host ruling).  Run FROM snoke.
cd "$(dirname "$0")/../../../.."   # repo root
UV="$HOME/.local/bin/uv run --no-project --with torch --with transformers --with numpy python"
OUT=evidence/qwen2b/q2/v4_v5
run() {   # $1 = tag, $2 = inject spec
  FABLE5_MODEL=2b OMP_NUM_THREADS=8 nohup nice -n 5 $UV ref/perplexity_eval.py \
    --corpus ref/ppl_corpus_eval.txt \
    --inject "$2" --res-scale 8 \
    --json-out $OUT/ppl_$1.json > $OUT/ppl_$1.log 2>&1 &
}
W4=all:w4g64
TAIL=dn_conv:cw13,emb:emb16
run v5              "all:w8g128,$TAIL"
run v5_rerun        "all:w8g128,$TAIL"
run v4mix_top1      "$W4,gate_up:w8g128,$TAIL"
run v4mix_top2      "$W4,gate_up:w8g128,lm_head:w8g128,$TAIL"
run v4mix_top3      "$W4,gate_up:w8g128,lm_head:w8g128,dn_in:w8g128,$TAIL"
sleep 2
echo "launched 5 on $(hostname)"

# ---------------------------------------------------------------------------
# ADDED after V5 landed at 12.360678 (a 1.03 % residual): with GPTQ recovering
# 57 % of the W4 gap at ZERO byte cost, the interesting mixed point is no
# longer "V2 + W8" but "the BEST W4 base + the cheapest W8 promotion".  Same
# ladder step as v4mix_top1, one variable changed: the W4 rule underneath.
# Run separately (it needs the Hessian npz, and it costs ~30 min of build).
#   bash evidence/qwen2b/q2/v4_v5/run_v4_v5.sh gptq
if [ "$1" = "gptq" ]; then
  NPZ=ref/calib_stats_2b_h.npz
  FABLE5_MODEL=2b OMP_NUM_THREADS=8 nohup nice -n 5 $UV ref/perplexity_eval.py \
    --corpus ref/ppl_corpus_eval.txt \
    --inject "all:w4g64gptq,gate_up:w8g128,$TAIL" \
    --calib-stats $NPZ --res-scale 8 \
    --json-out $OUT/ppl_v4mix_gptq_top1.json \
    > $OUT/ppl_v4mix_gptq_top1.log 2>&1 &
  sleep 2
  echo "launched the GPTQ-base mixed point on $(hostname)"
fi
