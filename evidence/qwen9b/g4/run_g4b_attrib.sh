#!/bin/bash
# run_g4b_attrib.sh — run ooc_dnpipe_attrib.tcl on the two layer_chan
# post-synth checkpoints.  ON SNOKE (Vivado).
set -uo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
set +u
source /home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh
set -u
cd "$REPO_ROOT/synth/out_ooc9b_layer_p2"
vivado -mode batch -nojournal -nolog \
    -source "$SCRIPT_DIR/ooc_dnpipe_attrib.tcl" \
    -tclargs "$REPO_ROOT/synth/out_ooc9b_layer_p0/post_synth.dcp" \
             "$REPO_ROOT/synth/out_ooc9b_layer_p2/post_synth.dcp" \
    2>&1 | grep -E "^(ATTRIB|ERROR|FATAL)"
