#!/usr/bin/env bash
# sr6_spec_cites_baseline.sh — Task SR6 (a copy of sr3c_spec_cites_baseline.sh): which spec_cites FAILs over
# the documents SR6's drift pass touched are PRE-EXISTING, and does SR6
# introduce any?  spec_cites is run three times over the same file list:
#   base  = a `git archive` of 7e72126 (SR6's parent)
#   pre   = a `git archive` of 860d018 (SR6's code + USAGE paragraph landed,
#           docs not yet re-pointed)
#   work  = this tree (after the pass)
# Each FAIL is keyed as `<doc>:<line> <KIND>`.  The pass is digits-only, so
# no document's line numbering moved except docs/USAGE.md's (the new §3
# paragraph); USAGE keys past its insertion are shifted back by its length.
# INTRODUCED = in work, not in base.  Exit 1 if any.  Nothing numeric.
#   evidence/qwen9b/sr/sr6_spec_cites_baseline.sh <file>...
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
cd "$ROOT" || exit 1
PY=/home/cah/.venv/bin/python
T=$(mktemp -d /tmp/sr6_sc.XXXXXX)
trap 'rm -rf "$T"' EXIT
# Only the files spec_cites can reach are exported: the documents, the
# checker, and every tracked path any of the documents names (a whole-tree
# archive is ~370 MB over NFS).  A path a document names that is absent at
# that ref is absent from the export too, which is what EXIST should see.
git ls-files -o -i --exclude-standard --directory > "$T/ignored"
for ref in 7e72126 860d018; do
  mkdir -p "$T/$ref"
  git ls-tree -r --name-only "$ref" > "$T/$ref.all"
  # match on BASENAMES (a document may cite `SEQ_ISA.md:115` relative to
  # its own directory) and export every tracked path carrying one
  awk -F/ '{print $NF}' "$T/$ref.all" | sort -u > "$T/$ref.base"
  for f in "$@"; do git show "$ref:$f" 2>/dev/null; done \
    | grep -oFf "$T/$ref.base" | sort -u > "$T/$ref.hit"
  { printf '%s\n' "$@" evidence/qwen_next/spec_cites.py
    awk -F/ 'NR==FNR {h[$0]=1; next} ($NF in h)' "$T/$ref.hit" "$T/$ref.all"
  } | sort -u | grep -xFf "$T/$ref.all" > "$T/$ref.want"
  git archive "$ref" $(cat "$T/$ref.want") | tar -x -C "$T/$ref"
  # IGNORED paths (.superpowers/ ledgers, synth/out_* builds) are cited but
  # never in git: link them in from this tree, or every such cite would be a
  # false EXIST in the export that could mask a real one on the same line
  while read -r ig; do
    ig="${ig%/}"
    [ -e "$T/$ref/$ig" ] && continue
    mkdir -p "$T/$ref/$(dirname "$ig")"
    ln -s "$ROOT/$ig" "$T/$ref/$ig"
  done < "$T/ignored"
done
# docs/USAGE.md: SR6 inserts its --seq-rtl paragraph before the REPL heading
U_AT=$(git show 7e72126:docs/USAGE.md | grep -n '^### REPL commands' | cut -d: -f1)
U_N=$(( $(wc -l < docs/USAGE.md) - $(git show 7e72126:docs/USAGE.md | wc -l) ))
keys() {  # $1 = tree root; rest = files
  local r="$1"; shift
  ( cd "$r" && "$PY" evidence/qwen_next/spec_cites.py "$@" ) \
    | grep -E '^  \S+:[0-9]+  (EXIST|RANGE|QUOTE|AMBIG|ORPHAN) ' \
    | awk '{print $1, $2}'
}
shiftu() { awk -v at="$U_AT" -v n="$U_N" '{split($1,a,":"); \
      if (a[1]=="USAGE.md" && a[2]+0>=at+n) $1=a[1]":"(a[2]-n); print}'; }
FILES=("$@")
keys "$T/7e72126" "${FILES[@]}" | sort -u > "$T/base.k"
keys "$T/860d018" "${FILES[@]}" | shiftu | sort -u > "$T/pre.k"
keys "$ROOT" "${FILES[@]}" | shiftu | sort -u > "$T/work.k"
echo "files     ${#FILES[@]}   (docs/USAGE.md shift: $U_N lines from base line $U_AT)"
echo "FAIL keys base(7e72126) $(wc -l < "$T/base.k")  pre(860d018) $(wc -l < "$T/pre.k")  work $(wc -l < "$T/work.k")"
echo "--- per document, base / pre / work"
cat "$T/base.k" "$T/pre.k" "$T/work.k" | awk '{split($1,a,":"); print a[1]}' | sort -u | while read -r d; do
  printf '  %-58s %4d %4d %4d\n' "$d" \
    "$(grep -c "^$d:" "$T/base.k")" "$(grep -c "^$d:" "$T/pre.k")" "$(grep -c "^$d:" "$T/work.k")"
done
echo "--- REPAIRED by the pass (in pre, not in work)"
comm -23 "$T/pre.k" "$T/work.k" | sed 's/^/  /'
echo "--- INTRODUCED (in work, not in base)"
comm -13 "$T/base.k" "$T/work.k" | sed 's/^/  /' | tee "$T/intro"
echo "--- documents with ZERO FAIL keys in work"
for f in "${FILES[@]}"; do
  b=$(basename "$f"); grep -q "^$b:" "$T/work.k" || echo "  $f"
done
if [ -s "$T/intro" ]; then echo "SR6_SPEC_CITES_BASELINE: FAIL (introduced)"; exit 1; fi
echo "SR6_SPEC_CITES_BASELINE: PASS (every work FAIL is pre-existing at 7e72126)"
