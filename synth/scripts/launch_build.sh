#!/bin/bash
# launch_build.sh — create + build a stage1 bitstream in an isolated out dir.
# Run ON SNOKE:  ./launch_build.sh <build_name>
# e.g.           ./launch_build.sh build_001
# Detach with:   nohup ./launch_build.sh build_001 > /dev/null 2>&1 &
set -euo pipefail

BUILD_NAME=${1:?usage: launch_build.sh <build_name>}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
OUT_DIR="$REPO_ROOT/synth/out_${BUILD_NAME}"
VERSION=$(cd "$REPO_ROOT" && git rev-parse --short=8 HEAD)

if [ -d "$OUT_DIR" ]; then
    echo "FATAL: $OUT_DIR already exists — builds are never overwritten" >&2
    exit 1
fi
# R3-0 (ii) (evidence/qwen9b/sr/R3_0_TOOLING.md): SYNTH_ONLY=1 passes build.tcl
# a second word `synth_only` — synth_1 only, no impl_1, no bitstream; the
# synth_1 checkpoint is left for synth/scripts/launch_incr.sh — and ends with
# `=== SYNTH DONE: <out dir> ===`.  Unset / 0: the full build, as before.
case "${SYNTH_ONLY:-0}" in
    0) BUILD_ARGS=("$OUT_DIR") ;;
    1) BUILD_ARGS=("$OUT_DIR" synth_only) ;;
    *) echo "FATAL: SYNTH_ONLY='${SYNTH_ONLY}' — 1 (synth only) or 0 / unset (the full build)" >&2; exit 2 ;;
esac
mkdir -p "$OUT_DIR"

# Xilinx settings64.sh references unset vars; relax -u while sourcing
set +u
source /home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh
set -u

cd "$OUT_DIR"
echo "=== create_project ($VERSION) ===" | tee build.log
vivado -mode batch -nojournal -log create.log \
    -source "$SCRIPT_DIR/create_project.tcl" -tclargs "$OUT_DIR" "$VERSION" \
    2>&1 | tail -5 | tee -a build.log
grep -q CREATE_PROJECT_OK create.log || { echo "FATAL: create_project failed (see $OUT_DIR/create.log)" | tee -a build.log; exit 1; }

echo "=== build ===" | tee -a build.log
vivado -mode batch -nojournal -log build_run.log \
    -source "$SCRIPT_DIR/build.tcl" -tclargs "${BUILD_ARGS[@]}" \
    2>&1 | tail -5 | tee -a build.log
if [ "${SYNTH_ONLY:-0}" = 1 ]; then
    grep -q '^SYNTH_OK' build_run.log || { echo "FATAL: synth-only build failed (see $OUT_DIR/build_run.log)" | tee -a build.log; exit 1; }
    echo "=== SYNTH DONE: $OUT_DIR ===" | tee -a build.log
    exit 0
fi
grep -q BUILD_OK build_run.log || { echo "FATAL: build failed (see $OUT_DIR/build_run.log)" | tee -a build.log; exit 1; }

echo "=== DONE: $OUT_DIR ===" | tee -a build.log
