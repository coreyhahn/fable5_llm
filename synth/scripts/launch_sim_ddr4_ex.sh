#!/bin/bash
# launch_sim_ddr4_ex.sh — run the DDR4 example-design simulation on snoke.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
OUT_DIR="$REPO_ROOT/synth/out_sim_ddr4ex"
[ -d "$OUT_DIR" ] && { echo "FATAL: $OUT_DIR exists"; exit 1; }
mkdir -p "$OUT_DIR"
set +u
source /home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh
set -u
cd "$OUT_DIR"
# generate IP + example project (stops before sim; sim runs separately so the
# custom-part TB guard can be patched first)
vivado -mode batch -nojournal -log gen.log \
    -source "$SCRIPT_DIR/sim_ddr4_ex_gen.tcl" -tclargs "$OUT_DIR" 2>&1 | tail -3
python3 "$SCRIPT_DIR/patch_ddr4_ex_tb.py" "$OUT_DIR/ex/ddr4_ex0_ex/imports/sim_tb_top.sv"
vivado -mode batch -nojournal -log sim_run.log \
    -source "$SCRIPT_DIR/sim_ddr4_ex_run.tcl" -tclargs "$OUT_DIR" 2>&1 | tail -3
