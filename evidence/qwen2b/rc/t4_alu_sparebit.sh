#!/usr/bin/env bash
# t4_alu_sparebit.sh — is widening the ALU count field to arg0[16:4] FREE
# for the frozen streams?  The R-b `scan_spare_bits` argument, applied to
# the one field R-c found truncating (RC_GATE.md sections 5-6).
#
# `C <op> <a0> <a1> <a2>` with op = b (11 = ALU): arg0 = {len[15:4],
# aop[3:0]}.  A widening to arg0[16:4] is bit-identical for any stream in
# which arg0 bit 16 is never set, i.e. every stream whose ALU counts are
# all < 4096.  Reported per script rather than asserted, so the number is
# visible.
set -u
cd "$(dirname "$0")/../../.." || exit 1
echo "ALU ARG0 bit-16 scan (R-b scan_spare_bits argument, ALU count field)"
echo
printf "%-46s %-8s %-10s %s\n" script ALU max_len "arg0>=2^16"
tot=0
for f in tb/scripts/w4/model_v2_s1.txt \
         tb/scripts/w3/lay_s1.txt tb/scripts/w3/tok2_s1.txt \
         tb/scripts/w5/bis/bis_08_w4_n4.txt \
         tb/scripts/w5/bis/bis_08_w8_n4.txt \
         tb/scripts/w5/bis/bis_2b_w4_n4.txt \
         tb/scripts/w5/lay2b_w8_s1.txt \
         tb/scripts/w5/model_w8_2b_s1.txt; do
  [ -f "$f" ] || { printf "%-46s (absent)\n" "$f"; continue; }
  awk -v F="$f" '
    $1=="C" && $2=="b" {
      a = strtonum("0x" $3); n = int(a/16)
      if (n > mx) mx = n
      if (a >= 65536) ov++
      t++
    }
    END { printf "%-46s %-8d %-10d %d\n", F, t, mx, ov+0 }' "$f"
  tot=$((tot+1))
done
echo
echo "READING: every 0.8B script has max_len 3584 < 4096 and never sets"
echo "arg0 bit 16, so cfg_len [11:0] -> [12:0] with .cfg_len(arg0[16:4]) is"
echo "BIT-IDENTICAL for them.  The 2B scripts are the ones that need it."
