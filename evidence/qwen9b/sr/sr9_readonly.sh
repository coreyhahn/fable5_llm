#!/usr/bin/env bash
# sr9_readonly.sh — Task SR9 (the docs pass): read-only facts two SR7 gate-doc
# corrections cite (the SR7 fix-round-1 re-review's minors).  Nothing is
# written, opened for write or removed; no Vivado, no board.
#   (a) the mtimes of the two empty .Xil/ directories SR7's n722–n725 runs left
#       in the signed-off out dirs (SR7 §9 M-5 says "10:22");
#   (b) the routed checkpoint's route status report of build_044_r1_incr — the
#       file behind "the closure stands on the fully routed clock tree".
# Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
echo "--- (a) the .Xil/ dirs in the two SR7 out dirs (full-iso mtimes; entries)"
for d in synth/out_build_044_r1_incr synth/out_build_044_r1_incr_bm1ref; do
  ls -la --time-style=full-iso -d "$d/.Xil"
  echo "  entries: $(ls -A "$d/.Xil" | wc -l)"
done
R=synth/out_build_044_r1_incr/proj/stage1.runs/impl_1/bd_wrapper_route_status.rpt
echo "--- (b) $R"
ls -la --time-style=full-iso "$R"
sha256sum "$R"
cat -n "$R"
