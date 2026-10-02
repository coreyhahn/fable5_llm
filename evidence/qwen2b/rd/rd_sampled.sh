#!/usr/bin/env bash
# rd_sampled.sh <seed> <tag> — one sampled 0.8B chat session, nch=4,
# the R-b prompt and knobs verbatim (temp 0.8, top-k 32, ntok 24).
set -u
R=/home/cah/r2d2/code/fpga/fable5_llm
exec "$R"/sw/.venv/bin/python -u "$R"/sw/chat_seq.py --nch 4 \
  --temp 0.8 --seed "$1" --ntok 24 \
  --prompt "Write a haiku about winter." \
  --out "$R/evidence/qwen2b/rd/chat_sampled_seed$2.json"
