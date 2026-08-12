#!/bin/bash
# program_fpga.sh — JTAG-program a volatile bitstream on the BCU-1525.
# Run ON SNOKE. Usage: ./program_fpga.sh <path/to/bitfile.bit>
#
# IMPORTANT: only call this after `sudo sw/pcie_helper.sh remove`
# (see docs/STAGE1.md hardware procedure), and rescan afterwards.
set -euo pipefail
BIT=${1:?usage: program_fpga.sh <bitfile>}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

set +u
source /home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh
set -u

vivado -mode batch -nojournal -nolog \
    -source "$SCRIPT_DIR/../synth/scripts/program.tcl" -tclargs "$BIT" \
    | grep -E "PROGRAM_OK|FATAL|ERROR" || true
