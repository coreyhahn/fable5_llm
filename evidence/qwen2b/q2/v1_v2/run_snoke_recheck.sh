#!/usr/bin/env bash
# Track Q task 10 — cross-host re-check of the three ladder points that were
# produced on darthplagueis INSIDE the host-fault window and never re-scored
# anywhere else: the 2B bf16 anchor, V1 and V2.
#
# Why: `../v3/V3.md` §6 documents transient wrong int64 reductions on
# darthplagueis.  V3 was closed by re-scoring on snoke (`../v3/ppl_v3_snoke.json`)
# and everything from task 8b onward ran on snoke only — but the anchor and the
# W4 baseline, which every Delta in the study is measured against, had only
# same-host agreement behind them.  This closes that.
#
# The float PPL path has no arithmetic guard, and it is NOT bit-reproducible
# across torch builds / thread counts (~1e-8 relative on nll_sum — `../v3/V3.md`
# §4, `../v4/GPTQ.md` §2.1).  The study's convention therefore applies: agreement
# to the six PUBLISHED decimals of `ppl`, with the nll_sum delta reported.
#
# Originals: darthplagueis, torch 2.6.0+cu124, threads=16 (per the logs).
# Here:      snoke, torch 2.12.0+cpu, threads=6, nice 15 (Vivado is building).
#
#   bash evidence/qwen2b/q2/v1_v2/run_snoke_recheck.sh        # RUN FROM SNOKE
cd "$(dirname "$0")/../../../.."   # repo root
UV="$HOME/.local/bin/uv run --no-project --with torch --with transformers --with numpy python"
TAIL=dn_conv:cw13,emb:emb16

run() {   # $1 = json/log path stem, $2 = extra args
  FABLE5_MODEL=2b OMP_NUM_THREADS=6 nohup nice -n 15 $UV ref/perplexity_eval.py \
    --corpus ref/ppl_corpus_eval.txt $2 \
    --json-out $1.json > $1.log 2>&1 &
}

# the bf16 anchor: no --inject, no --res-scale (res_scale has no effect
# without emb16, and the harness rejects the combination)
run evidence/qwen2b/q1/ppl_2b_bf16_snoke ""
run evidence/qwen2b/q2/v1_v2/ppl_v1_snoke "--inject all:w4g128,$TAIL --res-scale 8"
run evidence/qwen2b/q2/v1_v2/ppl_v2_snoke "--inject all:w4g64,$TAIL  --res-scale 8"
sleep 2
echo "launched 3 on $(hostname)"
