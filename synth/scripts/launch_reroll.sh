#!/bin/bash
# launch_reroll.sh — re-place/route an existing build's netlist with different
# placer directives (fresh project copy per directive; synthesis is reused).
# Run ON SNOKE:  ./launch_reroll.sh <build_name> <directive> [<directive>...]
# e.g.           ./launch_reroll.sh build_023 Explore ExtraTimingOpt
# Detach with:   nohup ./launch_reroll.sh build_023 Explore > /dev/null 2>&1 &
set -euo pipefail

BUILD_NAME=${1:?usage: launch_reroll.sh <build_name> <directive>...}
shift
[ $# -ge 1 ] || { echo "FATAL: need at least one placer directive" >&2; exit 1; }

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
SRC_DIR="$REPO_ROOT/synth/out_${BUILD_NAME}"
[ -d "$SRC_DIR/proj" ] || { echo "FATAL: $SRC_DIR/proj not found" >&2; exit 1; }

# Refuse overwrites up front, before any copies start
for D in "$@"; do
    if [ -d "$REPO_ROOT/synth/out_${BUILD_NAME}_rr_${D}" ]; then
        echo "FATAL: out_${BUILD_NAME}_rr_${D} already exists — builds are never overwritten" >&2
        exit 1
    fi
done

# Xilinx settings64.sh references unset vars; relax -u while sourcing
set +u
source /home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh
set -u

for D in "$@"; do
    RR_DIR="$REPO_ROOT/synth/out_${BUILD_NAME}_rr_${D}"
    mkdir -p "$RR_DIR"
    cp -a "$SRC_DIR/proj" "$RR_DIR/proj"
    (
        cd "$RR_DIR"
        vivado -mode batch -nojournal -log reroll.log \
            -source "$SCRIPT_DIR/reroll_impl.tcl" \
            -tclargs "$RR_DIR/proj/stage1.xpr" "$D" \
            > reroll_run.out 2>&1
    ) &
done
wait

echo "=== rerolls done: ${BUILD_NAME} $* ==="
for D in "$@"; do
    LOG="$REPO_ROOT/synth/out_${BUILD_NAME}_rr_${D}/reroll.log"
    grep -h "^TIMING:" "$LOG" || echo "NO TIMING LINE: $D (see $LOG)"
done
