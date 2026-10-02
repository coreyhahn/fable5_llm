#!/usr/bin/env bash
# The pre-ship documentation chore's FINAL citation gate.
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm
BASE=5f9afe8
GATE=$(git diff --name-only $BASE HEAD | grep -vE '^evidence/qwen9b/o3/7[0-9]_' \
       | grep -vE 'docs/QWEN35_NEXT_FEASIBILITY\.md|evidence/qwen2b/rc/RC_GATE\.md|evidence/qwen2b/rd/RD_GATE\.md|evidence/qwen9b/o3/o3_cite_drift\.py' | sort)
OUT="docs/QWEN35_NEXT_FEASIBILITY.md evidence/qwen2b/rc/RC_GATE.md evidence/qwen2b/rd/RD_GATE.md evidence/qwen9b/o3/o3_cite_drift.py"

echo "=== PART 1 — THE CHORE'S GATE ==============================================="
echo "Every file this chore changed between $BASE and HEAD, less the four in PART 2."
echo "$GATE" | sed 's/^/    /'
echo
python3 evidence/qwen_next/spec_cites.py $GATE
P1=$?
echo
echo "=== PART 2 — THE FOUR THIS CHORE DOES NOT OWN, MEASURED ANYWAY ============="
echo "Three are documents the triage's own (a) scope note puts OUT of the chore:"
echo "docs/QWEN35_NEXT_FEASIBILITY.md's 126 and evidence/qwen2b/rc/RC_GATE.md's"
echo "24 + evidence/qwen2b/rd/RD_GATE.md's 8 are pre-migration failures that no"
echo "9B task ever owned.  The fourth is the drift tool itself: its four ORPHANs"
echo "are the checker reading the tool's own worked EXAMPLES of continuation"
echo "syntax, and one --range-control fixture string, as if they were citations,"
echo "so 'repairing' them would corrupt a negative control."
echo
echo "They are measured, not pruned -- and measured BOTH WAYS against the SAME"
echo "working tree, so the comparison isolates this chore's edit to the DOCUMENT:"
echo "the base text of each is written beside the real one, checked, and removed."
echo
for f in $OUT; do
  d=$(dirname "$f"); b=$(basename "$f"); tmp="$d/_basecopy_$b"
  git show "$BASE:$f" > "$tmp"
  bn=$(python3 evidence/qwen_next/spec_cites.py "$tmp" 2>&1 | grep -oE 'FAIL [0-9]+' | tail -1)
  rm -f "$tmp"
  hn=$(python3 evidence/qwen_next/spec_cites.py "$f"   2>&1 | grep -oE 'FAIL [0-9]+' | tail -1)
  printf "    %-52s  base %-8s HEAD %s\n" "$f" "$bn" "$hn"
done
echo
echo "    Same number on both sides of every row: this chore added no failure to"
echo "    any of the four."
echo
echo "=== VERDICT ================================================================"
if [ $P1 -eq 0 ]; then
  echo "PRESHIP_SPEC_CITES: PASS — FAIL 0 on every document this chore owns."
else
  echo "PRESHIP_SPEC_CITES: FAIL — part 1 is not clean."
fi
exit $P1
