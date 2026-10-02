#!/usr/bin/env bash
# spec_cites_selftest_regression.sh — G2b mini-round: the regression that
# guards the --selftest repair.
#
# THE REPAIR.  evidence/qwen_next/spec_cites.py's --selftest asserted out on
# three classes of document, all found at G2b:
#   (a) no `rtl/*.sv:N` citation to perturb   -> crash before any control ran
#   (b) no line carrying a cite AND a quotation of it -> crash at the second
#       assert.  The trigger is a ZERO-QUOTE document, NOT a host-only one:
#       evidence/qwen9b/g2/G2A_HOST.md has three rtl cites, passes (a), and
#       still crashed here.
#   (c) the perturbed copy lives in a temp dir, so resolve()'s
#       document's-own-directory fallback pointed at the temp dir and every
#       bare-filename cite stopped resolving -- 18 invented EXIST failures on
#       FINAL_BYTELOCK.md, so even the POSITIVE control failed.
#
# THE POINT OF THIS SCRIPT is that (c) has a wrong fix which looks right and
# is much worse than the bug: make bare names "resolve" by adding an
# always-existing candidate (os.devnull) to resolve().  That does not relocate
# the lookup, it DISABLES the EXIST check for every document.  Part 3 below
# builds exactly that variant and measures the damage, so the reason the real
# fix threads a directory instead is on record as a measurement rather than an
# assertion.
#
# Expected values, not a recording: every number below is compared and this
# script exits non-zero on any deviation.  The counts are the state at
# c9d2a2f, HEAD and the repair alike -- normal mode must not move at all.
set -u
cd "$(dirname "$0")/../../.." || exit 2
SC=evidence/qwen_next/spec_cites.py
rc=0
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

fails() { python3 "$1" "$2" 2>&1 | grep -oE "FAIL [0-9]+" | head -1 | cut -d' ' -f2; }
# The QUOTE-CHECK COUNT is pinned too, since 2026-09-10 (#64, triage (b)2).
# FAIL alone cannot see the failure mode that item was: a QUOTE check that is
# silently never PERFORMED reads exactly like one that passes.  Dropping `|`
# from PROSE_MARK moved this number and nothing else, and pinning it means
# putting it back would be caught here rather than by a re-audit.
quotes() { python3 "$1" "$2" 2>&1 | grep -oE "[0-9]+ quote" | head -1 | cut -d' ' -f1; }

echo "=== 1. NORMAL MODE — the repair must not move a single count ==="
# doc:expected-FAIL.  RUNG_INT8_STATE and D_TOL carry pre-existing failures
# that predate this campaign's G2b work (verified at c9d2a2f); they are here
# to prove the repair does not touch them, not because they are clean.
#
# RE-PINNED 2026-09-02 (G3.4, Task 10): RUNG_INT8_STATE 2 -> 1.  ONE of its
# two pre-existing failures was a QUOTE whose citation had ALREADY drifted
# before this campaign: it named line 2526 of ref/layer_fixed.py, then line
# 2540 after G3.4's mechanical renumber, while the line it quoted was 2555.
# ALL THREE NUMBERS ARE HISTORICAL COORDINATES ON THE G3.4 GATE TREE bbda679
# and are written as PROSE deliberately (review m1, 2026-09-10): as citation
# tokens a drift pass renumbered the two full ones and left the bare
# continuation behind, which is the "half repaired and reads as if it were
# checked" hazard o3_cite_drift.py's own docstring warns about.  G3.4 edited
# that file, so it fixed the pointer rather than leave a known-wrong one
# behind.
# What remains is the ORPHAN bare continuation at RUNG_INT8_STATE.md:823,
# which is untouched.  The count is LOWER, not different in kind.
#
# CORRECTION 2026-09-10 (pre-ship tool chore, fix round 2, re-review I-A).
# The first two numbers read 2566 and 2580 here from b1cff80 until bddd092.
# They were NOT G3.4 coordinates: b1cff80's drift pass had already moved the
# two full tokens +40 while they were still live citations, and the round
# that froze them as prose froze the MOVED values and then asserted, in the
# sentence above, that they were the G3.4 tree's.  The G3.4 tree's are
# 2526 / 2540 / 2555, each read off the gate commit itself with
# `git show bbda679:ref/layer_fixed.py | sed -n`: bbda679:ref/layer_fixed.py:2526
# is the `es = np.array([fp.exp_neg_q(...)` line, :2540 the tolerance comment
# and :2555 the `_blk("attn softmax+pv", ...)` call that the citation quotes.
# evidence/qwen9b/o3/108_preship_fix1_cite_drift_residuals.log line 33 states
# the wrong triple ("2566/2580/2555 are true of the G3.4 tree"); committed
# logs are never amended, so THIS note, the fix-round report and the ledger
# carry the correction instead.
#
# RE-PINNED 2026-09-10 (pre-ship tool chore, triage (b)2 / #64).  Rows are
# now `doc:FAIL:quote`.  THREE FAIL COUNTS MOVED AND NONE OF THEM MOVED HERE:
# RC_GATE 27 -> 24, D_TOL 3 -> 0 and RUNG_INT8_STATE 1 -> 0 were already the
# measured state at b9e0851, before this chore touched the checker -- the
# pre-ship documentation chore repaired D_TOL's and RUNG_INT8_STATE's ORPHAN
# bare continuations, and RC_GATE's 27 predates that.  Measured both ways on
# the same working tree (`git show b9e0851:...spec_cites.py` with REPO pinned
# vs HEAD): every FAIL count in this table is IDENTICAL under the two
# checkers, so dropping `|` from PROSE_MARK added no failure to any pinned
# document.  What it moved is the QUOTE column, which is why that column now
# exists.
EXPECT="
evidence/qwen2b/rc/RC_GATE.md:24:1
evidence/qwen2b/rd/RD_GATE.md:8:0
evidence/qwen9b/g2/FINAL_BYTELOCK.md:0:0
evidence/qwen9b/g2/G2A_HOST.md:0:0
evidence/qwen9b/g2/D_TOL.md:0:7
evidence/qwen9b/g1/RUNG_INT8_STATE.md:0:7
docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md:0:22
docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md:0:3
"
for row in $EXPECT; do
  d=${row%%:*}; rest=${row#*:}; want=${rest%:*}; wantq=${rest##*:}
  got=$(fails "$SC" "$d"); gotq=$(quotes "$SC" "$d")
  if [ "$got" = "$want" ] && [ "$gotq" = "$wantq" ]; then
    printf '  ok        FAIL %-4s quote %-4s %s\n' "$got" "$gotq" "$d"
  else
    printf '  *** FAIL %s (want %s)  quote %s (want %s)  %s\n' \
      "$got" "$want" "$gotq" "$wantq" "$d"; rc=1
  fi
done

echo
echo "=== 2. --selftest — six controls CAUGHT + the positive control ==="
# The last two were IMPOSSIBLE before the repair: FINAL_BYTELOCK.md crashed at
# assert (a), G2A_HOST.md at assert (b).
for d in docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md \
         docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md \
         evidence/qwen9b/g2/FINAL_BYTELOCK.md \
         evidence/qwen9b/g2/G2A_HOST.md; do
  out=$(python3 "$SC" --selftest "$d" 2>&1)
  n=$(printf '%s\n' "$out" | grep -c "CAUGHT")
  v=$(printf '%s\n' "$out" | grep -oE "SELFTEST: (PASS|FAIL)" | tail -1)
  syn=$(printf '%s\n' "$out" | grep -c "SYNTHETIC CITE LINE")
  if [ "$v" = "SELFTEST: PASS" ] && [ "$n" = 6 ]; then
    printf '  ok        %s  %s/6 CAUGHT%s  %s\n' "$v" "$n" \
      "$([ "$syn" -gt 0 ] && echo ' (synthesized)')" "$(basename "$d")"
  else
    printf '  *** %s  %s/6 CAUGHT  %s\n' "$v" "$n" "$(basename "$d")"; rc=1
    printf '%s\n' "$out" | grep -E "MISSED|does not pass|vacuous|Error" | sed 's/^/        /'
  fi
done

echo
echo "=== 3. COUNTER-EXPERIMENT — the fix that would have broken the checker ==="
# Build the os.devnull variant of resolve() and measure what it does to a
# document with 27 real failures.  REPO is derived from __file__, so it is
# pinned to a literal here and the variant can live outside the tree.
SC="$SC" OUT="$TMP/sc_devnull.py" ROOT="$PWD" python3 - <<'MUT'
import os, re
src = open(os.environ["SC"]).read()
# pin REPO, which is normally derived from __file__
src = re.sub(r'^REPO = .*$', "REPO = %r" % os.environ["ROOT"], src,
             count=1, flags=re.M)
# insert the always-existing candidate ahead of the real ones
anchor = "    for cand in (os.path.join(REPO, p),"
assert anchor in src, "resolve() moved"
src = src.replace(anchor, anchor + "\n                 os.devnull,  # THE TRAP",
                  1)
open(os.environ["OUT"], "w").write(src)
MUT
if ! grep -q "THE TRAP" "$TMP/sc_devnull.py"; then
  echo "  *** could not build the counter-experiment — resolve() moved? ***"; rc=1
else
  real=$(fails "$SC" evidence/qwen2b/rc/RC_GATE.md)
  trap_n=$(fails "$TMP/sc_devnull.py" evidence/qwen2b/rc/RC_GATE.md)
  printf '  RC_GATE.md  real resolve(): FAIL %s   os.devnull sentinel: FAIL %s\n' \
    "$real" "$trap_n"
  if [ "$trap_n" -lt "$real" ]; then
    printf '  ok        the sentinel SUPPRESSES %s real failures — a checker\n' \
      "$((real - trap_n))"
    printf '            that stops failing.  This is why the repair threads a\n'
    printf '            directory instead of widening the candidate list.\n'
  else
    printf '  *** the counter-experiment did not reproduce the degradation;\n'
    printf '      it is the reason for the design and must stay demonstrable\n'; rc=1
  fi
fi

echo
if [ "$rc" = 0 ]; then
  echo "SPEC_CITES_REGRESSION PASS"
else
  echo "SPEC_CITES_REGRESSION FAIL"
fi
exit $rc
