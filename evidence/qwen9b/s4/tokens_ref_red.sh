#!/usr/bin/env bash
# tokens_ref_red.sh — the RED and the GREEN for `run_g4a_replay.sh
# --tokens-ref`, the check S4's acceptance bar rests on.
#
#   bash evidence/qwen9b/s4/tokens_ref_red.sh
#
# A comparison nobody has seen FAIL is a comparison nobody has seen work, and
# this one decides whether the state-spill design is accepted.  So it is run
# four times against the SAME simulation — one 9B token-smoke seed, replayed
# by the UNMODIFIED `evidence/qwen9b/g4/run_g4a_replay.sh` — with four
# different reference documents:
#
#   GREEN  the real evidence/qwen9b/g4/G4A_REPLAY.md   -> IDENTICAL, rc 0
#   RED 1  a document recording DIFFERENT tokens       -> DIFFER,    rc 1
#   RED 2  a document recording NOTHING for this stem  -> NO RECORD, rc 1
#   RED 3  a document recording TWO different lists    -> AMBIGUOUS, rc 1
#
# RED 2 is the one that matters most: a checker that silently passes when it
# cannot find its reference is worse than no checker, because it reports
# agreement it never established.
#
# `tok9b_s1` is the vehicle rather than a model stream because it decodes real
# tokens (`[2380, 6362]`, G4A_REPLAY.md §4.1) and costs ~3 minutes instead of
# ~3 hours.  The three fabricated documents are written to a temp directory,
# PRINTED here so the reader can see exactly what was fed, and DELETED at the
# end: a fabricated token record must never survive next to the evidence.
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
RUN=$ROOT/evidence/qwen9b/g4/run_g4a_replay.sh
REAL=$ROOT/evidence/qwen9b/g4/G4A_REPLAY.md
STEM=tok9b_s
SEED=1
TMP=$(mktemp -d "${TMPDIR:-/tmp}/s4_tokref_red.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

echo "TOKENS_REF_RED: the fabricated documents live in $TMP and are deleted on exit"

# The real record, read out of the real document, so the fabrications are
# built from it rather than from a number retyped here.
REALTOK=$(awk -v t="${STEM}${SEED}" '
  index($0, "`" t "`") == 0 { next }
  { s = $0; cand = ""
    while (match(s, /\[[0-9]+(,[ ]*[0-9]+)*\]/)) {
      cand = substr(s, RSTART, RLENGTH); s = substr(s, RSTART + RLENGTH) }
    if (cand != "") { gsub(/[][ ]/, "", cand); print cand } }' "$REAL" \
  | sort -u)
echo "TOKENS_REF_RED: G4A_REPLAY.md records [$REALTOK] for ${STEM}${SEED}"
[ -n "$REALTOK" ] || { echo "TOKENS_REF_RED: FAIL — the real document has no record"; exit 1; }

FIRST=${REALTOK%%,*}
REST=${REALTOK#*,}

{ echo "# fabricated RED 1 — the same stem, DIFFERENT tokens"
  echo "| \`${STEM}${SEED}\` | IDENTICAL \`[$((FIRST + 1)), $REST]\` |"
} > "$TMP/wrong.md"
{ echo "# fabricated RED 2 — a document that records NOTHING for this stem"
  echo "| \`some_other_stream\` | IDENTICAL \`[1, 2]\` |"
} > "$TMP/silent.md"
{ echo "# fabricated RED 3 — the document CONTRADICTS ITSELF"
  echo "| \`${STEM}${SEED}\` | IDENTICAL \`[$REALTOK]\` |"
  echo "| \`${STEM}${SEED}\` | IDENTICAL \`[$((FIRST + 1)), $REST]\` |"
} > "$TMP/ambiguous.md"
for f in "$TMP"/*.md; do echo "--- $f"; sed 's/^/    /' "$f"; done

FAIL=0
one () {  # $1 = label, $2 = doc, $3 = expected rc, $4 = expected marker
  echo
  echo "=== $1: --tokens-ref $(basename "$2"), expecting rc $3 and '$4'"
  # S4 fix round 1 (I2): the four `seedlogs_tokref_*` directories this
  # originally wrote are COMMITTED now, and `run_g4a_replay.sh` refuses a
  # LOGDIR that holds tracked evidence.  The default is unchanged so the
  # committed `010_tokens_ref_red.log` still says what it said; a RE-RUN
  # must name a fresh root -- `TOKREF_LOGROOT=<dir> bash tokens_ref_red.sh`.
  LOGDIR=${TOKREF_LOGROOT:-$ROOT/evidence/qwen9b/s4}/seedlogs_tokref_$1 \
    bash "$RUN" "$STEM" "$SEED" --tokens-ref "$2" > "$TMP/$1.out" 2>&1
  rc=$?
  grep -E "TOKENS|G4A_REPLAY|TB_SEQ_CHIP PASS" "$TMP/$1.out" | sed 's/^/    /'
  echo "    rc=$rc"
  if [ "$rc" != "$3" ]; then
    echo "    UNEXPECTED rc: got $rc, expected $3"; FAIL=1; fi
  if ! grep -q "$4" "$TMP/$1.out"; then
    echo "    MARKER NOT FOUND: '$4'"; FAIL=1; fi
}

one green     "$REAL"              0 "TOKENS IDENTICAL TO G4A"
one red_wrong "$TMP/wrong.md"      1 "TOKENS DIFFER FROM G4A"
one red_silent "$TMP/silent.md"    1 "TOKENS NO RECORD"
one red_ambig "$TMP/ambiguous.md"  1 "TOKENS RECORD IS AMBIGUOUS"

echo
if [ "$FAIL" = 0 ]; then
  echo "TOKENS_REF_RED: PASS — the token compare agrees when it should and"
  echo "  REFUSES on a wrong record, a MISSING record and an AMBIGUOUS one"
  exit 0
fi
echo "TOKENS_REF_RED: FAIL — the check did not behave as specified above"
exit 1
