#!/usr/bin/env bash
# t4_wall8_red_green.sh — would the improved fail-fast have caught wall 8?
#
# Wall 8 cost 66 minutes to surface because the only 2B fail-fast was the
# 1-layer smoke, which emits EMB = AMAXL = JMP = 0 — it generates no tokens
# at all, so nothing in the embed / argmax / decode-loop path was exercised.
# The new token smoke (make w8_2b_tok_smoke_scripts) runs the real token
# loop over a 8192-entry vocab: 1,244 records, EMB 2 / AMAXL 2 / JMP 2.
#
# RED   the token smoke against a host BFM WITHOUT the EMBLOG2 write (a
#       scratch copy of the TB; the repo file is not touched) — it must FAIL,
#       and fail in minutes.
# GREEN the same vectors against the repo TB, which programs EMBLOG2 from
#       the artifact — it must PASS.
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
SCRATCH=$ROOT/tb/scripts_scratch/wall8
MDIR=$SCRATCH/obj_dir_wall8
SEEDS=${SEEDS:-1 2 3 4}
XLIB="-f /home/cah/r2d2/code/verilator_lib/verilator_lib.f \
      /home/cah/r2d2/code/verilator_lib/verilator_xilinx.vlt"
RTL=$ROOT/rtl
cd "$ROOT/tb" || exit 1

mkdir -p "$SCRATCH"
python3 - "$ROOT/tb/tb_seq_chip.sv" "$SCRATCH/tb_seq_chip.sv" <<'PATCH'
import sys, re
src, dst = sys.argv[1], sys.argv[2]
s = open(src).read()
a = "            hwr(32'h60, exp_emblog2);"
assert a in s, "the EMBLOG2 write is not where this expected it"
s = s.replace(a, "            // RED CONTEXT: the pre-fix host BFM never wrote EMBLOG2")
s = re.sub(r"\n *hrd\(32'h60, v\);\n"
           r" *if \(v !== exp_emblog2\)\n"
           r" *\$fatal\(1, \"EMBLOG2 readback[^;]*;\n", "\n", s)
open(dst, "w").write(s)
print("RED-context copy made (repo tb_seq_chip.sv untouched)")
PATCH
echo "repo TB modifications: $(cd "$ROOT" && git status --porcelain tb/tb_seq_chip.sv | wc -l) (expect 0 or 1 for the staged fix, never a scratch edit)"
echo

build () {  # $1 = tb source, $2 = mdir, $3 = exe
  verilator --binary --timing -j "${JOBS:-16}" -Wall $XLIB \
    --Mdir "$2" -o "$3" -GNMV=4 -GWIMGPC=1 --top-module tb_seq_chip \
    $RTL/seq_unit.sv $RTL/seq_movers.sv $RTL/fx_pkg.sv $RTL/fx_rsqrt.sv \
    $RTL/fx_recip.sv $RTL/fx_silu.sv $RTL/vecnorm_unit.sv $RTL/rope_unit.sv \
    $RTL/conv4_silu.sv $RTL/dn_step.sv $RTL/attn_core.sv $RTL/gate_unit.sv \
    $RTL/vec_alu.sv $RTL/layer_chan.sv $RTL/matvec_engine.sv \
    $RTL/ddr_rd_streamer.sv $RTL/matvec_chan.sv \
    seq_fabric_model.sv seq_burst_fabric.sv seq_mem_file.sv "$1" 2>&1 \
    | grep -vE '^g\+\+|^/usr/bin|^make\[|^Archive|^echo |^rm |^ *$' | tail -3
}

echo "############ RED — token smoke vs a host BFM that never programs EMBLOG2"
build "$SCRATCH/tb_seq_chip.sv" "$MDIR" tb_wall8red
red_fail=0
for s in $SEEDS; do
  "$MDIR/tb_wall8red" +seq=scripts/w5/tok2b_w8_s$s.e \
      +base=scripts/w5/tok2b_w8_s$s +watchdog_ms=600000 2>&1 | tail -6
  [ "${PIPESTATUS[0]}" = 0 ] || red_fail=$((red_fail+1))
done
echo "RED: $red_fail of 4 seeds FAILED (4 = the improved smoke catches wall 8)"

echo
echo "############ GREEN — the same vectors on the repo TB (programs EMBLOG2)"
rc=0
for s in $SEEDS; do
  obj_dir_tb_seq_chip_w8/tb_seq_chip_w8 +seq=scripts/w5/tok2b_w8_s$s.e \
      +base=scripts/w5/tok2b_w8_s$s +watchdog_ms=600000 2>&1 | tail -6
  [ "${PIPESTATUS[0]}" = 0 ] || { echo "seed $s FAILED"; rc=1; }
done
echo
echo "wall8 red/green: RED_failures=$red_fail/4  GREEN_rc=$rc"
[ "$red_fail" = 4 ] && [ "$rc" = 0 ] && echo "VERDICT: the improved fail-fast catches wall 8, and the fix clears it."
exit $rc
