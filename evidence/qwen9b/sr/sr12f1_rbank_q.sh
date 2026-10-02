#!/usr/bin/env bash
# sr12f1_rbank_q.sh — SR12 fix round 1, item 2: RBANK alone at the 9B rows
# XBANK cannot take (q2 ng 64 / K 8192, q3 ng 96 / K 12288), 4 seeds
# (+verilator+seed+s).  Each +rbank run must be bit-exact against the Python
# golden (the TB's own check, rc 0) AND its RES words (+dumprows, read from
# RES_PTR 2048) identical to a bank-0 run of the same vectors and seed (read
# from RES_PTR 0).  Uses tb_matvec_chan's binary from `make tb_matvec_chan
# CHANDIR=<obj_dir>` (built first).  Run ON SNOKE through sr_run.sh.
#   evidence/qwen9b/sr/sr12f1_rbank_q.sh <obj_dir>
set -u
CHD=${1:?obj_dir}
cd "$(dirname "$0")/../../../tb" || exit 1
B=$CHD/tb_chan
echo "binary $B $(ls -la --time-style=full-iso $B | awk '{print $6, $7}')"
nok=0; nbad=0
for s in 1 2 3 4; do for nm in q2 q3; do
  v=vecv2/${nm}${s}_g128
  o0=$($B --seed $s +verilator+seed+$s +shapeback +dumprows +vecdir=$v 2>&1); r0=$?
  o1=$($B --seed $s +verilator+seed+$s +rbank +shapeback +dumprows +vecdir=$v 2>&1); r1=$?
  n0=$(echo "$o0" | grep -c '^ROWVAL'); n1=$(echo "$o1" | grep -c '^ROWVAL')
  if [ $r0 -eq 0 ] && [ $r1 -eq 0 ] && [ "$n0" -gt 0 ] && \
     [ "$(echo "$o0" | grep '^ROWVAL')" == "$(echo "$o1" | grep '^ROWVAL')" ]; then
    nok=$((nok+1)); verdict=IDENTICAL
  else nbad=$((nbad+1)); verdict=DIFFERS; fi
  echo "$verdict $v s$s: bank0 rc $r0 ($n0 rows) / rbank rc $r1 ($n1 rows): $(echo "$o1" | grep -E 'PASS|FAIL' | tail -1)"
done; done
echo "SR12F1 RBANK_Q: $((nok+nbad)) pairs, $nok bit-exact vs golden AND identical to bank 0, $nbad not"
[ $nbad -eq 0 ]
