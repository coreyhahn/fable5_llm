#!/usr/bin/env bash
# crosslock_setcheck.sh — the second half of G2b's corroboration sweep.
#
# final_bytelock_pin.sh --crosslock asks "has this exact DIGEST been recorded
# before?".  For the six image-set rows that question is too narrow: the pin
# digests a whole image set into one canonical value, and an older record may
# hold the same bytes as 187 SEPARATE per-file sha256 lines.  The digest is
# then absent while the bytes are fully corroborated, and --crosslock reports
# "no prior record" — true about the digest, misleading about the artifact.
#
# This script closes that gap mechanically.  For each image set it takes the
# first member's sha256, finds the committed file recording it (excluding
# evidence/qwen9b/, this campaign's own work), and then requires **every**
# member of the set to appear in that same file.  A partial match is reported
# as partial rather than rounded up.
#
# Found by review at G2b: the 0.8B 187-image set is recorded per file in
# evidence/stage5/phase1a_model_v2_artifacts.sha256, which --crosslock could
# not see.  That moves group A from 12/14 to 13/14 and the pin's total from
# 19/54 to 20/54.
set -u
export LC_ALL=C
cd "$(dirname "$0")/../../.." || exit 2
rc=0

check_set() {                     # $1 = label, $2 = glob
  local label=$1 glob=$2 n first cand miss total
  n=$(ls $glob 2>/dev/null | wc -l)
  if [ "$n" = 0 ]; then
    printf '  %-42s *** no files match %s\n' "$label" "$glob"; rc=1; return
  fi
  first=$(sha256sum "$(ls $glob | head -1)" | cut -d' ' -f1)
  cand=$(git grep -l "$first" -- . ':!evidence/qwen9b/' 2>/dev/null | head -1)
  if [ -z "$cand" ]; then
    printf '  %-42s %3d files, NO per-file record either\n' "$label" "$n"
    return
  fi
  miss=0; total=0
  while read -r s _; do
    total=$((total+1))
    grep -q "$s" "$cand" || miss=$((miss+1))
  done < <(sha256sum $glob)
  if [ "$miss" = 0 ]; then
    printf '  %-42s %3d/%3d recorded in %s\n' "$label" "$total" "$total" "$cand"
  else
    printf '  %-42s PARTIAL %d/%d in %s\n' \
      "$label" "$((total-miss))" "$total" "$cand"
  fi
}

echo "--- image-set rows of the pin, checked for a PER-FILE prior record ---"
check_set "0.8B model_v2_s1_w[N].bin"       "tb/scripts/w4/model_v2_s1_w*.bin"
check_set "2B   model_w8_2b_s1_w[N].bin"    "tb/scripts/w5/model_w8_2b_s1_w*.bin"
for s in 1 2 3 4; do
  check_set "lock gold lay2b_w8_s${s}_w[N].bin" "tb/scripts/w5/lay2b_w8_s${s}_w*.bin"
done

echo
echo "--- the single-file rows --crosslock already reported as uncorroborated ---"
for f in tb/scripts/w4/model_v2_s1.wimg.bin \
         tb/scripts/w5/model_w8_2b_s1.wimg0.bin \
         tb/scripts/w5/model_w8_2b_s1.wimg1.bin \
         tb/scripts/w5/model_w8_2b_s1.wimg2.bin \
         tb/scripts/w5/model_w8_2b_s1.wimg3.bin; do
  s=$(sha256sum "$f" | cut -d' ' -f1)
  c=$(git grep -l "$s" -- . ':!evidence/qwen9b/' 2>/dev/null | head -1)
  printf '  %-46s %s\n' "$(basename "$f")" "${c:-no prior record}"
done

echo
[ "$rc" = 0 ] && echo "CROSSLOCK_SETCHECK done" || echo "CROSSLOCK_SETCHECK FAIL"
exit $rc
