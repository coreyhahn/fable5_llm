#!/usr/bin/env bash
# rd_chat2b.sh — a chat_seq session on the 2B W8 (V5) artifact.
#
#   rd_chat2b.sh <out-tag> [extra chat_seq args...]
#
# FABLE5_MODEL=2b is REQUIRED: ref/gen_layer_script carries the
# model_select-chosen geometry (H/FFN/layers) that ref/seq_model's Mach and
# the tokenizer path are built from — the same env R-c's `seq_model --gate`
# ran under.  --any-template is REQUIRED because chat_seq pins the two 0.8B
# template sha256s; the 2B stream is a third artifact and its geometry is
# DERIVED structurally (derive_geometry), not re-pinned here.
set -u
R=/home/cah/r2d2/code/fpga/fable5_llm
TAG="$1"; shift
export FABLE5_MODEL=2b
exec "$R"/sw/.venv/bin/python -u "$R"/sw/chat_seq.py \
  --nch 4 --template "$R"/tb/scripts/w5/model_w8_2b_s1.e --any-template \
  --out "$R/evidence/qwen2b/rd/chat2b_$TAG.json" "$@"
