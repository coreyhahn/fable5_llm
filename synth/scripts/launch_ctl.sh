#!/bin/bash
# launch_ctl.sh — build a control bitstream (XDMA+BRAM). Usage: launch_ctl.sh <A|B>
set -euo pipefail
V=${1:?A or B}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
OUT_DIR="$REPO_ROOT/synth/out_ctl_$V"
[ -d "$OUT_DIR" ] && { echo "FATAL: $OUT_DIR exists"; exit 1; }
mkdir -p "$OUT_DIR"
set +u; source /home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh; set -u
cd "$OUT_DIR"
vivado -mode batch -nojournal -log create.log \
    -source "$SCRIPT_DIR/create_ctl.tcl" -tclargs "$OUT_DIR" "$V" 2>&1 | tail -3
grep -q CREATE_PROJECT_OK create.log || { echo "FATAL: create failed"; exit 1; }
# build.tcl expects stage1.xpr; controls have own names — generate a build script
cat > build_ctl.tcl <<TCL
set_param general.maxThreads 16
open_project $OUT_DIR/proj/ctl$V.xpr
launch_runs synth_1 -jobs 8
wait_on_run synth_1
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] != "100%"} { puts "FATAL: impl failed"; exit 1 }
puts "BITSTREAM: [glob $OUT_DIR/proj/ctl$V.runs/impl_1/*.bit]"
puts "BUILD_OK"
TCL
vivado -mode batch -nojournal -log build_run.log -source build_ctl.tcl
grep -q BUILD_OK build_run.log || { echo "FATAL: build failed"; exit 1; }
echo "=== DONE: $OUT_DIR ==="
