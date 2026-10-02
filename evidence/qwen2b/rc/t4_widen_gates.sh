#!/usr/bin/env bash
# t4_widen_gates.sh — the frozen-invisibility gate set for R-c's ALU
# element-count widening (rtl/vec_alu.sv cfg_len 12 -> 13 bits).
#
# The widening's whole claim is that it changes NOTHING at 0.8B: every
# frozen stream's ALU counts are <= 3584 and none of them ever sets
# arg0[16] (ref/scripts/scan_spare_bits.py proves that over 248,218 ALU
# records).  These are the TBs that would notice if it were wrong.
#
# tb_ru2_diff is the load-bearing one: tb_vecalu_diff drives ONE randomized
# stimulus into BOTH the FROZEN legacy vec_alu copy (tb/legacy/, 12-bit
# cfg_len, deliberately NOT widened) and the current RTL, and requires them
# to agree element for element.  Its length generator tops out inside the
# old 12-bit range, so it is exactly a proof that the widened unit is
# bit-identical to the pre-widening one over the whole legacy domain.
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
PY=${VECPY:-/home/cah/.venv/bin/python}
J=${JOBS:-16}
cd "$ROOT/tb" || exit 1
rc=0
for t in tb_vec_alu tb_vecnorm tb_ru2_diff tb_layer_chan tb_token tb_seq_layer; do
  echo
  echo "################ $t"
  # NB: MAKE's status, not grep's.  A filtered pipeline exits with the LAST
  # stage's code, so `if make ... | grep -v ...` reports a failed build as
  # OK — which it did on the first run of this script, and the tb_ru2_diff
  # compile error it swallowed is why this comment exists.
  set -o pipefail
  make "$t" JOBS="$J" VECPY="$PY" GENPY="$PY" MODELPY="$PY" 2>&1 \
    | grep -vE '^g\+\+|^/usr/bin|^make\[|^Archive|^echo |^rm |^verilator |^  --|^  \.\./'
  st=${PIPESTATUS[0]}
  set +o pipefail
  if [ "$st" = 0 ]; then
    echo "GATE $t OK"
  else
    echo "GATE $t FAIL rc=$st"
    rc=1
  fi
done
echo
echo "widen-gate summary rc=$rc"
exit $rc
