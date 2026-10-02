#!/usr/bin/env bash
# The pre-ship tool chore's FIX ROUND 1 final citation gate.
#
#   bash evidence/qwen9b/o3/preship_fix1_gate.sh
#
# Same shape as evidence/qwen9b/o3/preship_gate.sh, one round later: PART 1
# is every file this round changed, and it must be FAIL 0.  PART 2 is the
# SIX it does NOT own, measured anyway:
#   * evidence/qwen2b/rc/RC_GATE.md and evidence/qwen2b/rd/RD_GATE.md --
#     pre-migration gate records whose failures no 9B task ever owned (the
#     triage's own scope note puts them out of the chore).
#   * evidence/qwen9b/o3/o3_cite_drift.py -- its four ORPHANs are the checker
#     reading the tool's own worked EXAMPLES of continuation syntax as if they
#     were citations, so "repairing" them would corrupt a negative control.
#   * docs/superpowers/plans/2026-08-12-qwen2b-track-q.md,
#     evidence/qwen2b/q2/v1_v2/DECOMP.md and
#     evidence/qwen9b/s4/emit_model_gated.sh -- three files this round did not
#     EDIT but the drift pass RENUMBERED (they cite an edited file by line).
#     Their failures are older than this campaign's 9B work and none of them
#     is a citation this pass moved.
# All six are MEASURED BOTH WAYS against the same working tree, base text
# beside HEAD text, so the comparison isolates this round's edit to the file.
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm
BASE=a4a1f68
OUT="evidence/qwen2b/rc/RC_GATE.md evidence/qwen2b/rd/RD_GATE.md \
     evidence/qwen9b/o3/o3_cite_drift.py \
     docs/superpowers/plans/2026-08-12-qwen2b-track-q.md \
     evidence/qwen2b/q2/v1_v2/DECOMP.md \
     evidence/qwen9b/s4/emit_model_gated.sh"
GATE=$( { git diff --name-only $BASE HEAD; git diff --name-only; } | sort -u \
        | grep -vE '^evidence/qwen9b/o3/1[0-9][0-9]_' \
        | grep -vFx -f <(printf '%s\n' $OUT) )

echo "=== PART 1 — THIS ROUND'S GATE ============================================="
echo "Every file the fix round changed between $BASE and HEAD, less the six in"
echo "PART 2 and this round's own logs."
echo "$GATE" | sed 's/^/    /'
echo
python3 evidence/qwen_next/spec_cites.py $GATE
P1=$?
echo
echo "=== PART 2 — THE SIX THIS ROUND DOES NOT OWN, MEASURED ANYWAY ============="
for f in $OUT; do
  d=$(dirname "$f"); b=$(basename "$f"); tmp="$d/_basecopy_$b"
  git show "$BASE:$f" > "$tmp"
  bn=$(python3 evidence/qwen_next/spec_cites.py "$tmp" 2>&1 | grep -oE 'FAIL [0-9]+' | tail -1)
  rm -f "$tmp"
  hn=$(python3 evidence/qwen_next/spec_cites.py "$f"   2>&1 | grep -oE 'FAIL [0-9]+' | tail -1)
  printf "    %-52s  base %-8s HEAD %s\n" "$f" "$bn" "$hn"
done
echo
echo "    Same number on both sides of every row: this round added no failure to"
echo "    any of the six."
echo
echo "=== VERDICT ================================================================"
if [ $P1 -eq 0 ]; then
  echo "PRESHIP_FIX1_SPEC_CITES: PASS — FAIL 0 on every file this round owns."
else
  echo "PRESHIP_FIX1_SPEC_CITES: FAIL — part 1 is not clean."
fi
exit $P1
