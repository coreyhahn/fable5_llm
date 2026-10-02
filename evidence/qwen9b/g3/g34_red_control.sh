#!/usr/bin/env bash
# evidence/qwen9b/g3/g34_red_control.sh — G3.4's RED control.
#
# The directed banking/envelope modes tb_layer_chan gained at G3.4
# (+dnbank / +envtest) are only worth anything if they FAIL on the geometry
# they were written to reject.  This script builds the SAME testbench
# against the PRE-G3.4 RTL and shows that they do, twice over:
#
#   RED-a  the committed pre-G3.4 tree, UNMODIFIED.  Its `ifndef SYNTHESIS
#          datapath-envelope block $fatals on DNST head >= 16 before the
#          test can even reach the banking, and +envtest dies inside
#          vecnorm_unit's OWN sim-only nlog2 guard -- which is spec 5.4
#          S9's point: on silicon neither of those exists.
#   RED-b  the same tree with that sim-only block STRIPPED, so what shows
#          is the ALIASING itself and not the refusal: head 16 aliases
#          head 0, dn_slot 18/23 have no bank so their stores never
#          advance, kv_slot 6/7 read a bank that is not there, and the
#          two extra kvheads share kvhead 0/1's counters.
#
# Usage:  bash evidence/qwen9b/run.sh g3/<log> \
#           bash evidence/qwen9b/g3/g34_red_control.sh <pre-G3.4-sha>
# Default sha is 8138d66, the tree G3.4 started from.
set -u
cd "$(dirname "$0")/../../.."
BASE=${1:-8138d66}
RED=${G34_RED_DIR:-/tmp/g34_red}
rm -rf "$RED"; mkdir -p "$RED/rtl" "$RED/obj_a" "$RED/obj_b"
for f in fx_pkg fx_rsqrt fx_recip fx_silu vecnorm_unit rope_unit conv4_silu \
         dn_step attn_core gate_unit vec_alu layer_chan; do
  git show "$BASE:rtl/$f.sv" > "$RED/rtl/$f.sv" || exit 2
done
SRC="$RED/rtl/fx_pkg.sv $RED/rtl/fx_rsqrt.sv $RED/rtl/fx_recip.sv
     $RED/rtl/fx_silu.sv $RED/rtl/vecnorm_unit.sv $RED/rtl/rope_unit.sv
     $RED/rtl/conv4_silu.sv $RED/rtl/dn_step.sv $RED/rtl/attn_core.sv
     $RED/rtl/gate_unit.sv $RED/rtl/vec_alu.sv $RED/rtl/layer_chan.sv"
cd tb
echo "=== RED-a: the COMMITTED $BASE RTL, unmodified ==="
verilator --binary --timing -j 8 -Wall --Mdir "$RED/obj_a" -o tb_reda \
  --top-module tb_layer_chan $SRC tb_layer_chan.sv > "$RED/build_a.log" 2>&1 \
  || { echo "BUILD-A FAILED"; tail -20 "$RED/build_a.log"; exit 2; }
"$RED/obj_a/tb_reda" +dnbank  +watchdog_ms=4000; echo "RED-a dnbank rc=$?"
"$RED/obj_a/tb_reda" +envtest +watchdog_ms=4000; echo "RED-a envtest rc=$?"
echo
echo "=== RED-b: the SAME RTL with the sim-only envelope guards STRIPPED ==="
python3 - "$RED/rtl/layer_chan.sv" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
i = s.index("    // G3.1 DATAPATH ENVELOPE.")
j = s.index("`endif\n\nendmodule")
open(p, "w").write(s[:i] + s[j:])
print("stripped the pre-G3.4 sim envelope block")
PY
verilator --binary --timing -j 8 -Wall --Mdir "$RED/obj_b" -o tb_redb \
  --top-module tb_layer_chan $SRC tb_layer_chan.sv > "$RED/build_b.log" 2>&1 \
  || { echo "BUILD-B FAILED"; tail -20 "$RED/build_b.log"; exit 2; }
"$RED/obj_b/tb_redb" +dnbank  +watchdog_ms=4000; echo "RED-b dnbank rc=$?"
"$RED/obj_b/tb_redb" +envtest +watchdog_ms=4000; echo "RED-b envtest rc=$?"
