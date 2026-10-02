#!/usr/bin/env bash
set -eu
cd /home/cah/r2d2/code/fpga/fable5_llm
/home/cah/.venv/bin/python evidence/qwen_next/feas/fetch_geometry.py \
  Qwen/Qwen3.5-4B Qwen/Qwen3.5-9B Qwen/Qwen3.5-2B Qwen/Qwen3.5-0.8B \
  > evidence/qwen_next/feas/geometry_raw.json
echo "wrote evidence/qwen_next/feas/geometry_raw.json ($(stat -c%s evidence/qwen_next/feas/geometry_raw.json) bytes)"
