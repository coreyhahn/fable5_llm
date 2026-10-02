#!/usr/bin/env bash
# t4_wall2_scratch_experiment.sh — does correcting ONLY the testbench index
# clear the 2B chip replay, or is there another wall behind it?
#
# DIAGNOSIS-ONLY.  The repo's tb/tb_seq_chip.sv is NOT modified: the patched
# copy lives in a scratch directory and is built into a scratch obj_dir, so
# nothing that serves the 0.8B gates is touched.  The fix itself is held for
# a ruling (RC_GATE 5b).
#
# The patch is two characters' worth: `smem_a[..._mem_a[i][13:0]]` ->
# `[14:0]` at tb_seq_chip.sv lines 668 and 807.  `layer_chan.smem_a` is
# 32,768 words; a 14-bit index aliases every address >= 16384 down by 16K.
#
#   SCRATCH=<dir with the patched tb_seq_chip.sv> t4_wall2_scratch_experiment.sh
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
# Self-contained: makes its own patched copy under tb/scripts_scratch/
# (gitignored, and on NFS so snoke can build it).  The repo TB is read-only
# here and the check below proves it.
SCRATCH=${SCRATCH:-$ROOT/tb/scripts_scratch/wall2}
MDIR=$SCRATCH/obj_dir_wall2
mkdir -p "$SCRATCH"
python3 - "$ROOT/tb/tb_seq_chip.sv" "$SCRATCH/tb_seq_chip.sv" <<'PATCH'
import sys
src, dst = sys.argv[1], sys.argv[2]
s = open(src).read()
for name in ("prev_mem_a", "exp_mem_a"):
    a = f"u_layer.smem_a[{name}[i][13:0]]"
    b = f"u_layer.smem_a[{name}[i][14:0]]"
    assert s.count(a) == 1, f"{name}: expected exactly one 14-bit index"
    s = s.replace(a, b)
open(dst, "w").write(s)
print("patched a COPY: [13:0] -> [14:0] at both scratch-index sites")
PATCH
SEEDS=${SEEDS:-1 2 3 4}
XLIB="-f /home/cah/r2d2/code/verilator_lib/verilator_lib.f \
      /home/cah/r2d2/code/verilator_lib/verilator_xilinx.vlt"
RTL=$ROOT/rtl
cd "$ROOT/tb" || exit 1

echo "patched TB   : $SCRATCH/tb_seq_chip.sv"
echo "repo TB      : $(cd "$ROOT" && git status --porcelain tb/tb_seq_chip.sv | wc -l) modifications (0 = untouched)"
echo "the two changed lines:"
diff "$ROOT/tb/tb_seq_chip.sv" "$SCRATCH/tb_seq_chip.sv" | sed 's/^/    /'
echo

verilator --binary --timing -j "${JOBS:-16}" -Wall $XLIB \
  --Mdir "$MDIR" -o tb_wall2 -GNMV=4 -GWIMGPC=1 \
  --top-module tb_seq_chip \
  $RTL/seq_unit.sv $RTL/seq_movers.sv $RTL/fx_pkg.sv $RTL/fx_rsqrt.sv \
  $RTL/fx_recip.sv $RTL/fx_silu.sv $RTL/vecnorm_unit.sv $RTL/rope_unit.sv \
  $RTL/conv4_silu.sv $RTL/dn_step.sv $RTL/attn_core.sv $RTL/gate_unit.sv \
  $RTL/vec_alu.sv $RTL/layer_chan.sv $RTL/matvec_engine.sv \
  $RTL/ddr_rd_streamer.sv $RTL/matvec_chan.sv \
  seq_fabric_model.sv seq_burst_fabric.sv seq_mem_file.sv \
  "$SCRATCH/tb_seq_chip.sv" 2>&1 \
  | grep -vE '^g\+\+|^/usr/bin|^make\[|^Archive|^echo |^rm |^ *$' | tail -5
[ -x "$MDIR/tb_wall2" ] || { echo "BUILD FAILED"; exit 1; }

rc=0
for s in $SEEDS; do
  echo
  echo "--- seed $s"
  "$MDIR/tb_wall2" +seq=scripts/w5/lay2b_w8_s$s.e \
      +base=scripts/w5/lay2b_w8_s$s +watchdog_ms=600000 2>&1 | tail -12
  st=${PIPESTATUS[0]}
  [ "$st" = 0 ] || { echo "seed $s rc=$st"; rc=1; }
done
echo
echo "wall2 scratch experiment rc=$rc"
exit $rc
