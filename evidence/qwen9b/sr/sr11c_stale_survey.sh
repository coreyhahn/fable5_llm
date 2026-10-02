#!/usr/bin/env bash
# sr11c_stale_survey.sh — SR11c pass 4: the PRE-EXISTING stale citations the
# digit shifts preserved, surveyed repo-wide.  spec_cites
# (evidence/qwen_next/spec_cites.py) is run over every tracked .md/.txt under
# docs/ and evidence/ (+ NEXT_SESSION.md, CHARTER.md) that cites one of this
# round's edited files by line, and only the failures whose citation is INTO
# one of those files are kept: EXIST / RANGE (the number is past the file, so
# provably stale) and QUOTE (a quotation beside the cite is not at the line).
# Read-only; nothing numeric.  Run on snoke via sr_run.sh.
#   evidence/qwen9b/sr/sr11c_stale_survey.sh
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
PY=/home/cah/.venv/bin/python
T='(sw/hwmap\.py|sw/seq_run\.py|sw/chat_seq\.py|ref/seq_chat\.py|ref/seq_model\.py|ref/seq_format\.py|ref/seq_cost\.py|rtl/seq_unit\.sv|rtl/seq_movers\.sv|rtl/matvec_chan\.sv|rtl/matvec_engine\.sv)'
mapfile -t DOCS < <(git ls-files -- 'docs/*.md' 'docs/*.txt' 'evidence/*.md' 'evidence/*.txt' NEXT_SESSION.md CHARTER.md \
  | xargs grep -l -E "$T:[0-9]" 2>/dev/null | sort)
echo "documents citing the round's files by line: ${#DOCS[@]}"
OUT=$(mktemp /tmp/sr11c_survey.XXXXXX); trap 'rm -f "$OUT"' EXIT
for d in "${DOCS[@]}"; do
  "$PY" evidence/qwen_next/spec_cites.py "$d" 2>&1 \
    | grep -E '^  \S+:[0-9]+  (EXIST|RANGE|QUOTE|AMBIG|ORPHAN)  ' \
    | grep -E "$T" | sed "s#^  #  $d | #" >> "$OUT"
done
for k in EXIST RANGE QUOTE AMBIG ORPHAN; do
  echo "$k $(grep -c "  $k  " "$OUT")"
done
echo "--- failures citing the round's files (doc | basename:line KIND message)"
cat "$OUT"
echo "SR11C_STALE_SURVEY: $(wc -l < "$OUT") failure(s) into the round's files over ${#DOCS[@]} documents"
