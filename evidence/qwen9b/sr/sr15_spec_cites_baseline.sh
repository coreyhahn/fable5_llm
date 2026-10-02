#!/usr/bin/env bash
# sr15_spec_cites_baseline.sh — Task SR15: a copy of sr8_spec_cites_baseline.sh with
# base = a `git archive` of 2c66d67 (SR15's base, before any SR15 edit); nothing else changed.
# per-file overrides (nothing concurrent committed during SR8).  SR7's header:
# which spec_cites FAILs over the documents SR7 touched are PRE-EXISTING, and
# does SR7 introduce any?  spec_cites runs twice over the same file list:
#   base = a `git archive` of PRE (the tree just before SR7's cite re-point,
#          0e47ade) with SR7's own edits taken OUT again: sw/seq_run.py,
#          sw/hwmap.py and evidence/qwen9b/bm/bm1_ident.py as at 6a5a8b8
#          (SR7's parent), NEXT_SESSION.md and docs/USAGE.md as at db325d6
#          (their parent before SR7's doc commit).  Everything the concurrent
#          tasks (SR11a, SR12) committed meanwhile is IN the base, so their
#          effects are not attributed to SR7.
#   work = this tree.
# A FAIL is keyed as `<doc> <KIND> <message>` WITHOUT the citing line number,
# so SR7's line insertions into NEXT_SESSION.md / docs/USAGE.md do not
# re-key their unchanged citations; and the CITED line numbers inside the
# message's "(cited: path:NNN, ...)" are normalised to path:N (fix 1, after
# n746: the o3 pass moves a stale in-range quote cite by exactly the lines
# SR7 inserted, which re-keyed 16 pre-existing QUOTE failures as "new").  INTRODUCED = in work, not in base.
# Exit 1 if any.  Nothing numeric.
#   evidence/qwen9b/sr/sr7_spec_cites_baseline.sh <file>...
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
cd "$ROOT" || exit 1
PY=/home/cah/.venv/bin/python
PRE=2c66d67
T=$(mktemp -d /tmp/sr15_sc.XXXXXX)
trap 'rm -rf "$T"' EXIT
git ls-files -o -i --exclude-standard --directory > "$T/ignored"
ref=$PRE; B="$T/base"; mkdir -p "$B"
git ls-tree -r --name-only "$ref" > "$T/all"
awk -F/ '{print $NF}' "$T/all" | sort -u > "$T/basen"
for f in "$@"; do git show "$ref:$f" 2>/dev/null; cat "$f"; done \
  | grep -oFf "$T/basen" | sort -u > "$T/hit"
{ printf '%s\n' "$@" evidence/qwen_next/spec_cites.py
  awk -F/ 'NR==FNR {h[$0]=1; next} ($NF in h)' "$T/hit" "$T/all"
} | sort -u | grep -xFf "$T/all" > "$T/want"
git archive "$ref" $(cat "$T/want") | tar -x -C "$B"
while read -r ig; do
  ig="${ig%/}"
  [ -e "$B/$ig" ] && continue
  mkdir -p "$B/$(dirname "$ig")"
  ln -s "$ROOT/$ig" "$B/$ig"
done < "$T/ignored"
keys() {  # $1 = tree root; rest = files
  local r="$1"; shift
  ( cd "$r" && "$PY" evidence/qwen_next/spec_cites.py "$@" ) \
    | grep -E '^  \S+:[0-9]+  (EXIST|RANGE|QUOTE|AMBIG|ORPHAN|RETIRED) ' \
    | sed -E 's/^  (\S+):[0-9]+  /\1 /' \
    | sed -E 's/(\(cited: .*)$/\1/; :a; s/(\(cited: [^)]*[a-zA-Z_.\/]):[0-9]+(-[0-9]+)?/\1:N/; ta'
}
keys "$B" "$@" | sort -u > "$T/base.k"
keys "$ROOT" "$@" | sort -u > "$T/work.k"
echo "files     $#"
echo "FAIL keys (line-free) base $(wc -l < "$T/base.k")  work $(wc -l < "$T/work.k")"
echo "--- per document, base / work"
cat "$T/base.k" "$T/work.k" | awk '{print $1}' | sort -u | while read -r d; do
  printf '  %-58s %4d %4d\n' "$d" "$(grep -c "^$d " "$T/base.k")" "$(grep -c "^$d " "$T/work.k")"
done
echo "--- REPAIRED (in base, not in work)"
comm -23 "$T/base.k" "$T/work.k" | cut -c1-240 | sed 's/^/  /'
echo "--- INTRODUCED (in work, not in base)"
comm -13 "$T/base.k" "$T/work.k" | cut -c1-240 | sed 's/^/  /' | tee "$T/intro"
if [ -s "$T/intro" ]; then echo "SR15_SPEC_CITES_BASELINE: FAIL (introduced)"; exit 1; fi
echo "SR15_SPEC_CITES_BASELINE: PASS (every work FAIL is pre-existing without SR15's edits)"
