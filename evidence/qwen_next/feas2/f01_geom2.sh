#!/usr/bin/env bash
# f01_geom2.sh — exact checkpoint geometry for the TWO-BOARD study's two targets,
# plus the shipped 9B as the reproduction anchor.  Headers only, no weights.
set -eu
cd /home/cah/r2d2/code/fpga/fable5_llm
/home/cah/.venv/bin/python evidence/qwen_next/feas/fetch_geometry.py \
  Qwen/Qwen3.5-27B Qwen/Qwen3.5-35B-A3B Qwen/Qwen3.5-9B \
  > evidence/qwen_next/feas2/geometry2_raw.json
echo "wrote evidence/qwen_next/feas2/geometry2_raw.json ($(stat -c%s evidence/qwen_next/feas2/geometry2_raw.json) bytes)"
