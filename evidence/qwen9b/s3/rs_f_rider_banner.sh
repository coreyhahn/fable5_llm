#!/usr/bin/env bash
# RED/GREEN for review I-2: FABLE5_RS_F_RIDER=1 overrode the RS_F law in
# SILENCE.  Since 2026-09-10 `ref/layer_fixed.py` prints ONE line on stderr
# whenever the rider fires, naming the tag, the law's value and the override.
#
# RUN ON SNOKE, through evidence/qwen9b/run.sh.  Nothing is written inside
# tb/scripts/w9: both emissions go to their own scratch directories, which
# are removed at the end.  The board is not touched.
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm
ROOT=$PWD
PY=/home/cah/.venv/bin/python
S=$(mktemp -d -t rsfr.XXXXXX)
trap 'rm -rf "$S"' EXIT INT TERM HUP
FAIL=0
chk() { if [ "$2" = "$3" ]; then echo "  PASS  $1"; else
  echo "  FAIL  $1"; echo "        expected: $2"; echo "        actual:   $3"
  FAIL=$((FAIL + 1)); fi; }

echo "=== the law and the rider, as they stand:"
grep -n 'RS_F_BY_TAG = \|^_RS_F_LAW\|^_RS_F_ENV\|FABLE5_RS_F_RIDER=1: RS_F\|^RS_F = ' ref/layer_fixed.py | sed 's/^/    /'
echo

# ---------------------------------------------------------------- CASE A
# The MODULE half, both ways, on one command line each.  a4a1f68's module is
# `git show`n into $S and imported with ref/ behind it on PYTHONPATH, so its
# siblings resolve; nothing in the tree is modified.
git show a4a1f68:ref/layer_fixed.py > "$S/layer_fixed.py"
echo "=== CASE A (RED) — a4a1f68's module, FABLE5_MODEL=9b FABLE5_RS_F=8 FABLE5_RS_F_RIDER=1"
# NOT from inside ref/: with `python -c` sys.path[0] is the CWD, which would
# put the WORKING module ahead of $S and make case A test the fixed file.
# `-P` (ignore CWD) plus PYTHONPATH="$S:$ROOT/ref" is the honest RED, and the
# import path is echoed below so the log shows which file was loaded.
A_ENV="FABLE5_MODEL=9b FABLE5_RS_F=8 FABLE5_RS_F_RIDER=1"
A_ERR=$(cd "$S" && env $A_ENV PYTHONPATH="$S:$ROOT/ref" $PY -P -c \
        'import layer_fixed as L; print("RS_F", L.RS_F, L.__file__)' 2>&1 >/dev/null)
A_OUT=$(cd "$S" && env $A_ENV PYTHONPATH="$S:$ROOT/ref" $PY -P -c \
        'import layer_fixed as L; print("RS_F", L.RS_F)' 2>/dev/null)
echo "    module loaded: $(cd "$S" && env $A_ENV PYTHONPATH="$S:$ROOT/ref" $PY -P -c \
        'import layer_fixed as L; print(L.__file__)' 2>/dev/null)"
echo "    (that path is \$TMPDIR, i.e. a4a1f68's file, not the working one)"
echo "    stdout: $A_OUT"
echo "    stderr: ${A_ERR:-(empty)}"
chk "A the rider fires at a4a1f68 (RS_F 8, not the law 7)" "RS_F 8" "$A_OUT"
chk "A ...and says NOTHING — the defect" "0" \
    "$(printf '%s\n' "$A_ERR" | grep -c FABLE5_RS_F_RIDER)"

echo "=== CASE A' (GREEN) — the SAME command on the working module"
B_ERR=$(cd "$ROOT/ref" && env $A_ENV \
        $PY -c 'import layer_fixed as L; print("RS_F", L.RS_F)' 2>&1 >/dev/null)
B_OUT=$(cd "$ROOT/ref" && env $A_ENV \
        $PY -c 'import layer_fixed as L; print("RS_F", L.RS_F)' 2>/dev/null)
echo "    module loaded: $(cd "$ROOT/ref" && env $A_ENV $PY -c \
        'import layer_fixed as L; print(L.__file__)' 2>/dev/null)"
echo "    stdout: $B_OUT"
echo "    stderr: $B_ERR"
chk "A' same override" "RS_F 8" "$B_OUT"
chk "A' ONE line on stderr" "1" "$(printf '%s\n' "$B_ERR" | grep -c FABLE5_RS_F_RIDER)"
chk "A' it names the tag" "1" "$(printf '%s\n' "$B_ERR" | grep -c "FABLE5_MODEL='9b'")"
chk "A' it names the law" "1" "$(printf '%s\n' "$B_ERR" | grep -c 'the law RS_F=7')"
chk "A' it names the override" "1" "$(printf '%s\n' "$B_ERR" | grep -c 'RS_F=8 OVERRIDES')"
chk "A' nothing on stdout" "0" "$(printf '%s\n' "$B_OUT" | grep -c FABLE5_RS_F_RIDER)"

echo "=== CASE A'' — the law path prints NOTHING (the instrument is not stuck on)"
C_ERR=$(cd "$ROOT/ref" && FABLE5_MODEL=9b FABLE5_RS_F=7 FABLE5_RS_F_RIDER=1 \
        $PY -c 'import layer_fixed as L; print("RS_F", L.RS_F)' 2>&1 >/dev/null)
D_ERR=$(cd "$ROOT/ref" && FABLE5_MODEL=9b \
        $PY -c 'import layer_fixed as L; print("RS_F", L.RS_F)' 2>&1 >/dev/null)
chk "A'' env AGREES + rider set -> silent" "0" \
    "$(printf '%s\n' "$C_ERR" | grep -c FABLE5_RS_F_RIDER)"
chk "A'' env unset -> silent" "0" \
    "$(printf '%s\n' "$D_ERR" | grep -c FABLE5_RS_F_RIDER)"

# ---------------------------------------------------------------- the emissions
REF=tb/scripts/w9
cmp_set() {  # cmp_set <dir> ; prints "<same> <diff>"
  same=0; diff=0
  for f in $REF/lay9b_s1.* $REF/lay9b_s1_*; do
    [ -f "$f" ] || continue
    b=$(basename "$f")
    if [ -f "$1/$b" ] && cmp -s "$f" "$1/$b"; then same=$((same+1));
    else diff=$((diff+1)); fi
  done
  echo "$same $diff"
}

emit() {  # emit <tag> <W9_MODEL...> ; emits into tb/scripts/w9_<tag>
  d=$1; shift
  rm -rf "tb/scripts/w9_$d"
  make -C tb w9_9b_smoke_scripts W9_DIR="scripts/w9_$d" W9_SEEDS=1 \
       MODELPY=$PY VECPY=$PY W9_MODEL="$*" 2>&1
  echo "MAKE_RC=$?"
}

echo
echo "=== CASE B (GREEN) — the 1-layer/2-token SMOKE emission WITH the rider"
echo "===   W9_MODEL='FABLE5_MODEL=9b FABLE5_RS_F=8 FABLE5_RS_F_RIDER=1'"
BLOG=$S/rider.log
emit rider 'FABLE5_MODEL=9b FABLE5_RS_F=8 FABLE5_RS_F_RIDER=1' > "$BLOG"
tail -6 "$BLOG" | sed 's/^/    /'
NB=$(grep -c 'FABLE5_RS_F_RIDER=1: RS_F=8 OVERRIDES the law RS_F=7' "$BLOG")
echo "    FABLE5_RS_F_RIDER banner lines in the emission output: $NB"
grep -m1 'FABLE5_RS_F_RIDER=1: RS_F' "$BLOG" | sed 's/^/    /'
chk "B the emission rc is 0" "1" "$(grep -c '^MAKE_RC=0' "$BLOG")"
chk "B the rider ANNOUNCES ITSELF on the emit path" "1" \
    "$([ "$NB" -ge 1 ] && echo 1 || echo 0)"
set -- $(cmp_set tb/scripts/w9_rider)
echo "    vs the committed smoke set: $1 identical, $2 differing"
chk "B a rider artifact is NOT the shipping one (some file differs)" "1" \
    "$([ "$2" -ge 1 ] && echo 1 || echo 0)"

echo
echo "=== CASE C (GREEN) — the SAME emission at the LAW, env unset"
echo "===   W9_MODEL='FABLE5_MODEL=9b'"
CLOG=$S/law.log
emit law 'FABLE5_MODEL=9b' > "$CLOG"
tail -4 "$CLOG" | sed 's/^/    /'
chk "C the emission rc is 0" "1" "$(grep -c '^MAKE_RC=0' "$CLOG")"
chk "C NO rider line anywhere in the emission output" "0" \
    "$(grep -c FABLE5_RS_F_RIDER "$CLOG")"
set -- $(cmp_set tb/scripts/w9_law)
echo "    vs the committed smoke set: $1 identical, $2 differing"
chk "C the digests are UNCHANGED (0 differing)" "0" "$2"
echo "    state.bin sha256:"
sha256sum tb/scripts/w9_law/lay9b_s1.state.bin | sed 's/^/      /'
chk "C state.bin is S3_CHAIN.md section 9.4's value" "1" \
    "$(sha256sum tb/scripts/w9_law/lay9b_s1.state.bin | grep -c 36969da490db28c48693f0b9c50dd72ca8fedb40b5a2cb33605ff41b42054854)"

rm -rf tb/scripts/w9_rider tb/scripts/w9_law
echo "    the two scratch emission directories are removed; tb/scripts/w9 untouched"
ls -d tb/scripts/w9_rider tb/scripts/w9_law 2>&1 | sed 's/^/    /'

# ---------------------------------------------------------------- the selftest
echo
echo "=== LAYER_FIXED SELFTEST (0.8b and 2b), re-run on the working module"
for t in 0.8b 2b; do
  echo "--- FABLE5_MODEL=$t"
  ST=$( cd ref && FABLE5_MODEL=$t $PY layer_fixed.py 2>&1 )
  printf '%s\n' "$ST" | tail -3 | sed 's/^/    /'
  chk "SELFTEST PASS at $t" "1" \
      "$(printf '%s\n' "$ST" | grep -c 'LAYER_FIXED SELFTEST PASS')"
  chk "SELFTEST at $t prints no rider line" "0" \
      "$(printf '%s\n' "$ST" | grep -c FABLE5_RS_F_RIDER)"
done

echo
if [ "$FAIL" -eq 0 ]; then echo "RS_F_RIDER_BANNER: PASS (0 problem(s))";
else echo "RS_F_RIDER_BANNER: FAIL ($FAIL check(s))"; fi
exit $((FAIL > 0))
