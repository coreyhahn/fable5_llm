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
    -source "$SCRIPT_DIR/build.tcl" -tclargs "$OUT_DIR" \
    2>&1 | tail -5 | tee -a build.log
grep -q BUILD_OK build_run.log || { echo "FATAL: build failed (see $OUT_DIR/build_run.log)" | tee -a build.log; exit 1; }

echo "=== DONE: $OUT_DIR ===" | tee -a build.log
