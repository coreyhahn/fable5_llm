#!/usr/bin/env bash
# spec_cites_tablecell_fixture.sh — the RED/GREEN fixture for triage (b)2
# (#64): `evidence/qwen_next/spec_cites.py`'s `PROSE_MARK` contains `|`, so
# ANY backticked span carrying a pipe is exempt from the QUOTE check.
#
#   bash evidence/qwen9b/o3/spec_cites_tablecell_fixture.sh
#
# WHAT THE PIPE WAS FOR, and why removing it is safe.  `backtick_spans`
# pairs backticks EXACTLY (`line.split("`")`, odd pieces are the spans), so
# a well-formed table row never yields a span containing a cell separator —
# the separator lives in the EVEN pieces.  A span can only carry a `|` in
# two cases: the line has an ODD number of backticks (mis-pairing, which the
# exact pairing already made rare), or THE QUOTED SOURCE LINE ITSELF
# CONTAINS A PIPE.  The second is the common one in this campaign — SystemVerilog
# `||`, Python `|`, a shell pipeline — and it was silently unchecked.
#
# THE FIXTURE.  One markdown table whose third cell quotes a real line of a
# real cited file, `rtl/vec_alu.sv:168`, which contains `||`.  Three cases:
#
#   A  the honest quotation is CHECKED (`quote` count > 0) — RED: 0 today.
#   B  the document PASSES on it, so A is not passing by failing.
#   C  a PERTURBED cell (one literal changed) FAILS with QUOTE — RED: PASS
#      today, because the span is never looked at.
#   D  THE NECESSARY OTHER HALF, `quote_forms()` (review m7).  Markdown
#      REQUIRES a `|` inside a table cell to be written `\|`, so an HONEST
#      quotation of a pipe-bearing line does not match its own source
#      character for character.  Dropping the pipe from `PROSE_MARK` without
#      unescaping would therefore turn every correctly-escaped cell into a
#      QUOTE failure — the fix would punish the documents that got the
#      markdown right.  `quote_forms()` tries the raw form FIRST and the
#      unescaped form second, so it can only convert a failure into a pass;
#      D checks both halves of that: the escaped-and-HONEST cell passes its
#      QUOTE check, and the escaped-and-PERTURBED cell still fails one.
#      Until this case existed the function's only evidence was a real-tree
#      document (`evidence/qwen9b/g3/G3_3_MATVEC.md`).
#
# The fixture writes only into $TMPDIR and reads only committed files.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
# The checker under test.  Overridable so the RED can be taken against an
# EARLIER checker (`git show <sha>:evidence/qwen_next/spec_cites.py`)
# without touching the tree -- review m7, 2026-09-10.
SC=${SC:-$REPO/evidence/qwen_next/spec_cites.py}
W=$(mktemp -d -t sctc.XXXXXX)
trap 'rm -rf "$W"' EXIT INT TERM HUP

FAIL=0
say() { printf '%s\n' "$*"; }
chk() { if [ "$2" = "$3" ]; then say "  PASS  $1"; else
    say "  FAIL  $1"; say "        expected: $2"; say "        actual:   $3"
    FAIL=$((FAIL + 1)); fi; }

# the quoted line, taken from the tree so the fixture cannot go stale
SRC=$(sed -n '168p' "$REPO/rtl/vec_alu.sv")
say "=== quoted source line, rtl/vec_alu.sv:168:"
say "    $SRC"
case "$SRC" in *"|"*) ;; *) say "  FAIL  rtl/vec_alu.sv:168 no longer carries a pipe — re-pick the line"
                            exit 1;; esac

mk() {  # mk <outfile> <cell text>
  { printf '# fixture\n\n'
    printf '| what | where | the line |\n|---|---|---|\n'
    printf '| the op_pr2 predicate | `rtl/vec_alu.sv:168` | `%s` |\n' "$2"
  } > "$1"
}
mk "$W/good.md" "$SRC"
mk "$W/bad.md"  "$(printf '%s' "$SRC" | sed "s/4'd1/4'd7/")"
# the SAME two cells with every pipe escaped, which is how markdown requires
# a table cell to carry one (case D)
mk "$W/esc.md"    "$(printf '%s' "$SRC" | sed 's/|/\\|/g')"
mk "$W/escbad.md" "$(printf '%s' "$SRC" | sed "s/4'd1/4'd7/" | sed 's/|/\\|/g')"

run() { python3 "$SC" "$1" 2>&1; }
G=$(run "$W/good.md"); B=$(run "$W/bad.md")
E=$(run "$W/esc.md");  EB=$(run "$W/escbad.md")
say "=== honest cell:"; printf '%s\n' "$G" | sed 's/^/    /'
say "=== perturbed cell (4'd1 -> 4'd7):"; printf '%s\n' "$B" | sed 's/^/    /'
say "=== honest cell, pipes ESCAPED as markdown requires:"
say "    cell text: $(sed -n '5p' "$W/esc.md")"
printf '%s\n' "$E" | sed 's/^/    /'
say "=== perturbed cell, pipes ESCAPED:"; printf '%s\n' "$EB" | sed 's/^/    /'

nq=$(printf '%s\n' "$G" | grep -oE '[0-9]+ quote' | head -1 | cut -d' ' -f1)
chk "A the table-cell quotation is QUOTE-checked" "1" "${nq:-0}"
chk "B the honest document PASSES" \
    "1" "$(printf '%s\n' "$G" | grep -c 'SPEC CITES: PASS')"
chk "C the perturbed cell FAILs with QUOTE" \
    "1" "$(printf '%s\n' "$B" | grep -c 'QUOTE')"
neq=$(printf '%s\n' "$E" | grep -oE '[0-9]+ quote' | head -1 | cut -d' ' -f1)
chk "D the ESCAPED honest cell is QUOTE-checked" "1" "${neq:-0}"
chk "D the ESCAPED honest cell PASSES (quote_forms unescapes it)" \
    "1" "$(printf '%s\n' "$E" | grep -c 'SPEC CITES: PASS')"
chk "D the ESCAPED PERTURBED cell still FAILs with QUOTE" \
    "1" "$(printf '%s\n' "$EB" | grep -c 'QUOTE')"

say ""
if [ "$FAIL" -eq 0 ]; then say "SPEC_CITES_TABLECELL FIXTURE: PASS (6 checks)"; else
  say "SPEC_CITES_TABLECELL FIXTURE: FAIL ($FAIL check(s))"; fi
exit $((FAIL > 0))
