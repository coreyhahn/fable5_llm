#!/usr/bin/env bash
# O3 BOARD LOCK (2026-09-01): this script drives the board and does
# NOT take the shared lock (sw/board_lock.py) -- it predates the O3
# ruling and its logic is frozen R-d evidence, so it was not rewritten.
# It does a bare pcie_helper remove/rescan around a reprogram.
# Take the lock around it by hand:
#     python3 sw/board_lock.py --tool <why> --exec -- <this script>
# rd_program_035.sh — the SAFE reprogram flow, build_035_fp2a_exc_po.
#   remove -> JTAG (volatile) -> rescan -> load
# `load` is needed here because snoke rebooted on 2026-08-19 (after the R-b
# gate): the xdma module never autoloads, and the volatile config the board
# held was lost with the power cycle — see hw_00_board_prestate.log.
# Flash is NEVER written; synth/scripts/program.tcl only calls
# program_hw_devices on the JTAG device (volatile configuration).
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
H=/home/cah/r2d2/code/fpga/fable5_llm/sw/pcie_helper.sh
BIT=synth/out_build_035_fp2a_exc_po/bd_wrapper.bit

echo "### 1. pcie_helper.sh remove"
sudo -n "$H" remove; echo "  rc=$?"

echo "### 2. program_fpga.sh (JTAG, VOLATILE) $BIT"
time ./sw/program_fpga.sh "$BIT"; echo "  rc=$?"

echo "### 3. pcie_helper.sh rescan"
sudo -n "$H" rescan; echo "  rc=$?"

echo "### 4. pcie_helper.sh load (xdma.ko — gone since the 08-19 reboot)"
sudo -n "$H" load; echo "  rc=$?"

echo "### 5. enumeration"
lspci -s 82:00.0 || echo "  (82:00.0 ABSENT)"
lspci -s 82:00.0 -vv 2>/dev/null | grep -E "LnkSta:|LnkCap:" || true
ls -la /dev/xdma0_* || echo "  (no char devices)"
