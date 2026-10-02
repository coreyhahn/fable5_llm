#!/usr/bin/env bash
# o3_cite_drift_fixture.sh — the RED/GREEN fixture for triage (b)1 (#158),
# the sha-pin gap, and for the `--fix` non-idempotence recorded in
# `evidence/qwen9b/g6/RD9_GATE.md` section 18.2.
#
#   bash evidence/qwen9b/o3/o3_cite_drift_fixture.sh
#
# WHY A THROWAWAY REPO AND NOT THIS ONE.  Both questions are about what
# `--fix` WRITES, and `--fix` writes into the working tree.  Asking them
# here would either dirty committed gate documents or require a revert the
# reader has to trust.  The fixture builds a four-file git repo in a temp
# directory, copies `o3_cite_drift.py` into it at the same relative path
# (the tool derives REPO from its own location), and deletes it again.
# Nothing outside $TMPDIR is touched, and the script is the whole input.
#
# THE FOUR CASES.  A and B are one pass over one document; C and D are the
# idempotence pair.
#
#   A  SHA PIN.  A citation written `<sha>:path:line` is a HISTORICAL pin —
#      it names where a line was in THAT commit, and it is correct forever.
#      `--fix` must leave it byte-identical.
#   B  LIVE CITE.  A bare `path:line` in the same document must still be
#      renumbered, or A passes vacuously by a rewriter that refuses
#      everything.
#   C  RUN IT TWICE, CLEAN.  A second `--fix` at the same base must not
#      change a byte.
#   D  RUN IT TWICE, MIXED.  One document already repaired by hand (in
#      post-fix coordinates) and one still stale: `--verify` is dirty
#      because of the stale one, so a guard that only asks `--verify`
#      lets the pass through and DOUBLE-SHIFTS the repaired one.  That is
#      section 18.2's hour, reproduced in eight lines.
#   E  THE ESCAPE FROM D's REFUSAL (review of the pre-ship tool chore, I-1).
#      D's refusal is right, and DOCUMENT-GRANULAR: on the real tree a plan
#      is usually mostly REPAIR with one collateral token an operator has
#      checked by hand (S5's own pass read REPAIR 11 / COLLATERAL 1), and
#      the only documented remedy, `--exclude`, forfeits that document's
#      eleven repairs.  `--allow-collateral` clears the token INSTEAD, and
#      loudly: the pass then applies D1's stale repair, and the cleared
#      rewrite is printed BY NAME so the operator's decision is in the log.
#      Case E is that, on the SAME mixed tree D refuses.
#   F  A PARTLY CLEARED RUN STILL REFUSES, AND NEVER SAYS "ALLOWED"
#      (re-review of fix round 1, m7).  `_print_allowed` runs BEFORE the
#      refusal, so a run that clears one collateral token and leaves another
#      used to print "ALLOWED N ... on the operator's assertion" and then
#      write nothing at all.  Two collateral tokens, one cleared: the run
#      must refuse (rc 2), must say WOULD CLEAR, must not contain the word
#      ALLOWED anywhere, and must leave both documents byte-unchanged.
#   G  THE REASON REACHES THE LOG (m6).  `--allow-collateral <value>=<why>`
#      prints the why beside the token it clears; without one the log says
#      so in as many words.  Until 2026-09-10 the flag recorded only WHAT
#      was cleared, which is enough to stop a silent widening and not enough
#      for a reader a year later.
#
# Exit 0 only when all seven report PASS.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
TOOL=$HERE/o3_cite_drift.py
W=$(mktemp -d -t o3fixt.XXXXXX)
trap 'rm -rf "$W"' EXIT INT TERM HUP

FAIL=0
say() { printf '%s\n' "$*"; }
chk() {  # chk <name> <expected> <actual>
  if [ "$2" = "$3" ]; then say "  PASS  $1"; else
    say "  FAIL  $1"; say "        expected: $2"; say "        actual:   $3"
    FAIL=$((FAIL + 1)); fi
}

# ---------------------------------------------------------------- the repo
mkdir -p "$W/sw" "$W/docs" "$W/evidence/qwen9b/o3"
cp "$TOOL" "$W/evidence/qwen9b/o3/o3_cite_drift.py"
seq 1 12 | sed 's/^/line /' > "$W/sw/fixture_only_foo.pyx"
cat > "$W/docs/D1.md" <<'EOF'
# D1

The live one: `sw/fixture_only_foo.pyx:5` is the thing this document is about.

The pin: at `deadbee1:sw/fixture_only_foo.pyx:5` the same statement lived here, and that
sentence is true of `deadbee1` forever.
EOF
cat > "$W/docs/D2.md" <<'EOF'
# D2

The other live one: `sw/fixture_only_foo.pyx:9`.
EOF
cat > "$W/docs/D3.md" <<'EOF'
# D3

A third live one: `sw/fixture_only_foo.pyx:3`.  Case F needs TWO collateral
tokens in TWO documents, so that clearing one leaves the other refused.
EOF
git -C "$W" init -q
git -C "$W" -c user.email=f@x -c user.name=f add -A >/dev/null
git -C "$W" -c user.email=f@x -c user.name=f commit -qm base
BASE=$(git -C "$W" rev-parse HEAD)

# the edit: two lines inserted at the top, so every base line n -> n+2
printf 'inserted A\ninserted B\n' > "$W/sw/fixture_only_foo.pyx.new"
cat "$W/sw/fixture_only_foo.pyx" >> "$W/sw/fixture_only_foo.pyx.new"
mv "$W/sw/fixture_only_foo.pyx.new" "$W/sw/fixture_only_foo.pyx"

run_fix() { python3 "$W/evidence/qwen9b/o3/o3_cite_drift.py" \
              --base "$BASE" --edited sw/fixture_only_foo.pyx --fix "$@"; }

# the MIXED tree, rebuilt from the base text each time: D2 hand-repaired to
# the post-fix coordinate, D1 left stale.  Cases D and E both start here.
mixed() {
  git -C "$W" checkout -q -- docs/D1.md docs/D2.md docs/D3.md
  sed -i 's|sw/fixture_only_foo\.pyx:9|sw/fixture_only_foo.pyx:11|' \
      "$W/docs/D2.md"
}

# TWO collateral tokens, in two documents: D2 and D3 both hand-repaired to
# post-fix coordinates, D1 still stale.  Clearing ONE of them must not turn
# the run into a pass (case F).
mixed2() {
  mixed
  sed -i 's|sw/fixture_only_foo\.pyx:3|sw/fixture_only_foo.pyx:5|' \
      "$W/docs/D3.md"
}

say "=== fixture: base $BASE, sw/fixture_only_foo.pyx 12 -> 14 lines (+2 at the top)"
say "=== pass 1"
run_fix; say "=== pass 1 rc $?"

# ------------------------------------------------------------- A, B
chk "A sha pin left byte-identical" \
    "1" "$(grep -c 'deadbee1:sw/fixture_only_foo\.pyx:5' "$W/docs/D1.md")"
chk "A no rewritten pin" \
    "0" "$(grep -c 'deadbee1:sw/fixture_only_foo\.pyx:7' "$W/docs/D1.md")"
chk "B live cite 5 -> 7" \
    "1" "$(grep -c '^The live one: .sw/fixture_only_foo\.pyx:7.' "$W/docs/D1.md")"
chk "B D2 live cite 9 -> 11" \
    "1" "$(grep -c 'sw/fixture_only_foo\.pyx:11' "$W/docs/D2.md")"

# ------------------------------------------------------------- C
S1=$(md5sum "$W/docs/D1.md" "$W/docs/D2.md" | md5sum)
say "=== pass 2 (same base, same tree — must change nothing)"
run_fix; say "=== pass 2 rc $?"
S2=$(md5sum "$W/docs/D1.md" "$W/docs/D2.md" | md5sum)
chk "C second --fix is a no-op" "$S1" "$S2"

# ------------------------------------------------------------- D
mixed
say "=== mixed tree: D2 already at :11 by hand, D1 still stale at :5"
run_fix; RCD=$?; say "=== mixed rc $RCD"
chk "D mixed tree REFUSED (rc 2)" "2" "$RCD"
chk "D hand-repaired D2 not moved again" \
    "1" "$(grep -c 'sw/fixture_only_foo\.pyx:11' "$W/docs/D2.md")"
chk "D no double shift to :13" \
    "0" "$(grep -c 'sw/fixture_only_foo\.pyx:13' "$W/docs/D2.md")"
chk "D D1's stale :5 is NOT repaired either — the refusal is whole-pass" \
    "1" "$(grep -c '^The live one: .sw/fixture_only_foo\.pyx:5.' "$W/docs/D1.md")"

# ------------------------------------------------------------- E
# The same mixed tree, with the ONE collateral token cleared by hand.  This
# is the shape --exclude cannot serve: excluding D2 would drop D1's repair
# only if D1 were the excluded one, but on the real tree the collateral and
# the repairs live in the SAME document (S5: REPAIR 11, COLLATERAL 1), and
# excluding it forfeits all eleven.
mixed
say "=== mixed tree + --allow-collateral docs/D2.md"
OUT=$(run_fix --allow-collateral docs/D2.md 2>&1); RCE=$?
say "$OUT"; say "=== allowed rc $RCE"
chk "E cleared pass APPLIES (rc 0)" "0" "$RCE"
chk "E D1's stale :5 IS repaired to :7" \
    "1" "$(grep -c '^The live one: .sw/fixture_only_foo\.pyx:7.' "$W/docs/D1.md")"
chk "E the cleared token is named in the output" "1" \
    "$(printf '%s\n' "$OUT" | grep -c 'ALLOWED COLLATERAL docs/D2.md  sw/fixture_only_foo.pyx:11 -> sw/fixture_only_foo.pyx:13')"
chk "E the cleared token IS moved — that is what clearing it means" \
    "1" "$(grep -c 'sw/fixture_only_foo\.pyx:13' "$W/docs/D2.md")"
chk "E the sha pin is STILL not rewritten" \
    "1" "$(grep -c 'deadbee1:sw/fixture_only_foo\.pyx:5' "$W/docs/D1.md")"

# per-CITATION granularity, and a typo must clear nothing
mixed
OUT=$(run_fix --allow-collateral sw/fixture_only_foo.pyx:11 2>&1); RCE2=$?
say "=== per-citation form rc $RCE2"
chk "E per-citation --allow-collateral clears the same token" "0" "$RCE2"
mixed
OUT=$(run_fix --allow-collateral docs/NOT_A_DOC.md 2>&1); RCE3=$?
say "=== typo rc $RCE3"
chk "E a value naming no collateral token clears NOTHING (rc 2)" "2" "$RCE3"
chk "E ...and says so" "1" \
    "$(printf '%s\n' "$OUT" | grep -c 'ALLOW-COLLATERAL docs/NOT_A_DOC.md matches no collateral token')"
chk "E typo run wrote nothing: D2 still at :11" \
    "1" "$(grep -c 'sw/fixture_only_foo\.pyx:11' "$W/docs/D2.md")"

# ------------------------------------------------------------- F
# One collateral token cleared, one NOT.  The run must refuse and must not
# describe itself as having allowed anything (m7).
mixed2
say "=== two collateral tokens, only docs/D2.md cleared"
OUT=$(run_fix --allow-collateral docs/D2.md 2>&1); RCF=$?
say "$OUT"; say "=== partly cleared rc $RCF"
chk "F a partly cleared run still REFUSES (rc 2)" "2" "$RCF"
chk "F the cleared token is announced as WOULD CLEAR" "1" \
    "$(printf '%s\n' "$OUT" | grep -c 'WOULD CLEAR COLLATERAL docs/D2.md')"
chk "F the word ALLOWED appears NOWHERE in a refused run" "0" \
    "$(printf '%s\n' "$OUT" | grep -c 'ALLOWED')"
chk "F the token that was NOT cleared is named" "1" \
    "$(printf '%s\n' "$OUT" | grep -c '! COLLATERAL docs/D3.md')"
chk "F nothing was written: D2 still at :11" "1" \
    "$(grep -c 'sw/fixture_only_foo\.pyx:11' "$W/docs/D2.md")"
chk "F nothing was written: D3 still at :5" "1" \
    "$(grep -c 'sw/fixture_only_foo\.pyx:5' "$W/docs/D3.md")"

# ------------------------------------------------------------- G
# The REASON, and the honest report of its absence (m6).
mixed
say "=== --allow-collateral docs/D2.md=<reason>"
OUT=$(run_fix --allow-collateral \
      'docs/D2.md=checked by hand against the base tree' 2>&1); RCG=$?
say "$OUT"; say "=== reason rc $RCG"
chk "G a value carrying =<reason> still clears its token (rc 0)" "0" "$RCG"
chk "G the reason is printed beside the cleared token" "1" \
    "$(printf '%s\n' "$OUT" | grep -c 'REASON  checked by hand against the base tree')"
chk "G the token is still named in full" "1" \
    "$(printf '%s\n' "$OUT" | grep -c 'ALLOWED COLLATERAL docs/D2.md  sw/fixture_only_foo.pyx:11 -> sw/fixture_only_foo.pyx:13')"
mixed
OUT=$(run_fix --allow-collateral docs/D2.md 2>&1)
chk "G with NO reason the log says so, rather than staying silent" "1" \
    "$(printf '%s\n' "$OUT" | grep -c 'REASON  (NONE GIVEN')"

say ""
if [ "$FAIL" -eq 0 ]; then say "O3_CITE_DRIFT FIXTURE: PASS (7 cases, 28 checks)"; else
  say "O3_CITE_DRIFT FIXTURE: FAIL ($FAIL check(s))"; fi
exit $((FAIL > 0))
