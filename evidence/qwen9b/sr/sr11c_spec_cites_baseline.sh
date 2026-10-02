#!/usr/bin/env bash
# sr11c_spec_cites_baseline.sh — Task SR11c: which spec_cites FAILs over the
# documents SR11c touched are PRE-EXISTING, and does SR11c introduce any?
# (evidence/qwen9b/sr/sr3c_spec_cites_baseline.sh's method, one base ref.)
# spec_cites is run twice over the same file list:
#   base = a `git archive` of BASE (72a4713, the tree SR11c was dispatched on)
#   work = this tree
# Each FAIL is keyed `<doc basename>:<line> <KIND>`; SR11c changes digits only,
# so a document's line numbers do not move — EXCEPT NEXT_SESSION.md, where
# SR11c inserts one dated line after NS_AT (env, default 0 = no shift).
# INTRODUCED = in work, not in base (exit 1 if any); REPAIRED = the reverse.
# Nothing numeric.  Run on snoke via sr_run.sh.
#   [NS_AT=<line>] evidence/qwen9b/sr/sr11c_spec_cites_baseline.sh <file>...
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
cd "$ROOT" || exit 1
PY=/home/cah/.venv/bin/python
BASE=72a4713
T=$(mktemp -d /tmp/sr11c_sc.XXXXXX)
trap 'rm -rf "$T"' EXIT
git ls-files -o -i --exclude-standard --directory > "$T/ignored"
mkdir -p "$T/b"
git ls-tree -r --name-only "$BASE" > "$T/all"
awk -F/ '{print $NF}' "$T/all" | sort -u > "$T/base"
for f in "$@"; do git show "$BASE:$f" 2>/dev/null; done \
  | grep -oFf "$T/base" | sort -u > "$T/hit"
{ printf '%s\n' "$@" evidence/qwen_next/spec_cites.py
  awk -F/ 'NR==FNR {h[$0]=1; next} ($NF in h)' "$T/hit" "$T/all"
} | sort -u | grep -xFf "$T/all" > "$T/want"
git archive "$BASE" $(cat "$T/want") | tar -x -C "$T/b"
while read -r ig; do
  ig="${ig%/}"
  [ -e "$T/b/$ig" ] && continue
  mkdir -p "$T/b/$(dirname "$ig")"
  ln -s "$ROOT/$ig" "$T/b/$ig"
done < "$T/ignored"
NS_AT=${NS_AT:-0}
NS_N=$(( $(wc -l < NEXT_SESSION.md) - $(git show "$BASE:NEXT_SESSION.md" | wc -l) ))
keys() {
  local r="$1"; shift
  ( cd "$r" && for f in "$@"; do "$PY" evidence/qwen_next/spec_cites.py "$f"; done ) \
    | grep -E '^  \S+:[0-9]+  (EXIST|RANGE|QUOTE|AMBIG|ORPHAN) ' \
    | awk '{print $1, $2}'
}
FILES=("$@")
keys "$T/b" "${FILES[@]}" | sort -u > "$T/base.k"
keys "$ROOT" "${FILES[@]}" \
  | awk -v at="$NS_AT" -v n="$NS_N" '{split($1,a,":"); \
      if (at>0 && a[1]=="NEXT_SESSION.md" && a[2]+0>at) $1=a[1]":"(a[2]-n); print}' \
  | sort -u > "$T/work.k"
echo "files ${#FILES[@]}   base $BASE   (NEXT_SESSION.md shift: $NS_N lines after $NS_AT)"
echo "FAIL keys  base $(wc -l < "$T/base.k")   work $(wc -l < "$T/work.k")"
echo "--- per document, base / work"
cat "$T/base.k" "$T/work.k" | awk '{split($1,a,":"); print a[1]}' | sort -u | while read -r d; do
  printf '  %-58s %4d %4d\n' "$d" "$(grep -c "^$d:" "$T/base.k")" "$(grep -c "^$d:" "$T/work.k")"
done
echo "--- REPAIRED (in base, not in work)"
comm -23 "$T/base.k" "$T/work.k" | sed 's/^/  /'
echo "--- INTRODUCED (in work, not in base)"
comm -13 "$T/base.k" "$T/work.k" | sed 's/^/  /' | tee "$T/intro"
echo "--- documents with ZERO FAIL keys in work"
for f in "${FILES[@]}"; do
  b=$(basename "$f"); grep -q "^$b:" "$T/work.k" || echo "  $f"
done
if [ -s "$T/intro" ]; then echo "SR11C_SPEC_CITES_BASELINE: FAIL (introduced)"; exit 1; fi
echo "SR11C_SPEC_CITES_BASELINE: PASS (every work FAIL is pre-existing at $BASE)"
