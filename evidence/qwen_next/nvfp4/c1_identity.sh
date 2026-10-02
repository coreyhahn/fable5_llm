#!/usr/bin/env bash
# c1_identity.sh — Ruling C1: the pre/post-change same-host A/B must be
# BYTE-identical in nll_sum, ppl, n_positions, total_bits,
# avg_bits_per_weight and the whole `classes` block (timing/host fields and
# the NV1-added fields may differ).  Secondary: the delta vs the committed
# cross-host json (torch 2.6.0+cu124, another host).
#   c1_identity.sh PRE.json POST.json COMMITTED.json
set -u
PRE="$1"; POST="$2"; OLD="$3"
field() { grep -E "^ \"$1\": " "$2"; }
block() { awk '/^ "classes": \{/{on=1} on{print} on&&/^ \},?$/{exit}' "$1"; }
echo "--- full text diff PRE vs POST (expect only timing + NV1-added fields)"
diff "$PRE" "$POST"
echo "--- required fields"
fail=0
for k in nll_sum ppl n_positions total_bits avg_bits_per_weight; do
  a="$(field "$k" "$PRE")"; b="$(field "$k" "$POST")"
  if [ -n "$a" ] && [ "$a" = "$b" ]; then echo "IDENTICAL  $a"
  else echo "DIFFERENT  pre=[$a] post=[$b]"; fail=1; fi
done
if cmp -s <(block "$PRE") <(block "$POST") && [ -n "$(block "$PRE")" ]; then
  echo "IDENTICAL  classes block ($(block "$PRE" | wc -l) lines, sha256 $(block "$PRE" | sha256sum | cut -c1-16))"
else
  echo "DIFFERENT  classes block"; diff <(block "$PRE") <(block "$POST"); fail=1
fi
echo "--- secondary: POST vs the committed cross-host json"
for k in nll_sum ppl; do
  a="$(field "$k" "$POST" | sed 's/.*: //; s/,$//')"
  c="$(field "$k" "$OLD" | sed 's/.*: //; s/,$//')"
  awk -v a="$a" -v c="$c" -v k="$k" 'BEGIN{printf "%-8s post %s committed %s  rel diff %.3e\n", k, a, c, (a-c)/c}'
done
field torch "$OLD" || echo " (committed json has no torch field)"
field torch "$POST"
[ "$fail" = 0 ] && echo "C1 BYTE-IDENTITY: PASS" || echo "C1 BYTE-IDENTITY: FAIL"
exit "$fail"
