#!/bin/bash
# run_g4b_pacc_sim.sh — G4b Step 2, the SIM half: build tb_seq_chip at the 9B
# elaboration WITH evidence/qwen9b/g4/pacc_probe.sv bound into every
# matvec_engine, and replay a 9B chip stream through it.
#
#   ./run_g4b_pacc_sim.sh <stream-prefix> <base> [watchdog_ms]
#
# e.g.  ./run_g4b_pacc_sim.sh scripts/w9/lay9b_s1.e4 scripts/w9/lay9b_s1
#
# Its OWN obj_dir (obj_dir_tb_seq_chip_9b_pacc), never obj_dir_tb_seq_chip_9b:
# that one is G4a's and the house rule is one obj_dir per elaboration, one
# machine at a time.  The probe drives nothing, so the DUT is bit-identical
# with it -- and the run still checks the .chip golden, so a probe that broke
# something would fail the replay rather than print a quiet number.
#
# Run ON SNOKE.
set -euo pipefail

SEQ=${1:?usage: run_g4b_pacc_sim.sh <stream-prefix> <base> [watchdog_ms]}
BASE=${2:?}
WD=${3:-600000}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
TB="$REPO_ROOT/tb"
RTL="$REPO_ROOT/rtl"
MDIR=obj_dir_tb_seq_chip_9b_pacc
BIN=tb_seq_chip_9b_pacc

SEQ_RTL="$RTL/seq_unit.sv $RTL/seq_movers.sv"
LAYER_RTL="$RTL/fx_pkg.sv $RTL/fx_rsqrt.sv $RTL/fx_recip.sv $RTL/fx_silu.sv \
  $RTL/vecnorm_unit.sv $RTL/rope_unit.sv $RTL/conv4_silu.sv $RTL/dn_step.sv \
  $RTL/attn_core.sv $RTL/gate_unit.sv $RTL/vec_alu.sv $RTL/layer_chan.sv"
CHIP_RTL="$SEQ_RTL $LAYER_RTL $RTL/matvec_engine.sv $RTL/ddr_rd_streamer.sv \
  $RTL/matvec_chan.sv"
CHIP_TBSRC="seq_fabric_model.sv seq_burst_fabric.sv seq_mem_file.sv tb_seq_chip.sv"
XLIB="-f /home/cah/r2d2/code/verilator_lib/verilator_lib.f \
  /home/cah/r2d2/code/verilator_lib/verilator_xilinx.vlt"

cd "$TB"
echo "=== build $BIN into $MDIR (NMV=4 WIMGPC=1 + pacc_probe bind) ==="
# shellcheck disable=SC2086
verilator --binary --timing -j "${JOBS:-8}" -Wall $XLIB \
    --Mdir "$MDIR" -o "$BIN" \
    -GNMV=4 -GWIMGPC=1 \
    --top-module tb_seq_chip \
    $CHIP_RTL "$SCRIPT_DIR/pacc_probe.sv" $CHIP_TBSRC

echo "=== run $BIN on $SEQ ==="
T0=$(date +%s)
# `RC=$?` on the next line would be UNREACHABLE under `set -e`: a
# non-zero exit aborts the script first, so the rc= line below could
# only ever print 0 and the wall clock would be lost on a failure.
# `|| RC=$?` suppresses errexit for exactly this command, so both are
# reported honestly and the script still exits with the real code.
RC=0
"./$MDIR/$BIN" +seq="$SEQ" +base="$BASE" +watchdog_ms="$WD" || RC=$?
T1=$(date +%s)
echo "=== pacc sim rc=$RC wall=$((T1 - T0)) s ==="
exit $RC
