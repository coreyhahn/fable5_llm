#!/usr/bin/env bash
# run_g4a_bytelock_08b.sh — G4a fix round 1, finding I2.
#
#   bash evidence/qwen9b/g4/run_g4a_bytelock_08b.sh [<base-commit>]
#
# Task 10 hand-on 1 has TWO halves: a 9B artifact must DECLARE `shape_isa`,
# and a byte-locked tag (0.8b / 2b) must NOT — because
# `evidence/qwen2b/rc/t3_locks.sh:39-43` `cmp`s the whole 0.8B `.e4.seq.json`.
# The 9B half was measured by the emit itself.  The 0.8B half was ASSERTED,
# with no run behind it, and that is what this script closes.
#
# It matters twice over, because `ref/seq_format.SeqEmitter.finish` now calls
# `validate_stream(recs, shape_isa=SHAPE_ISA_9B)` UNCONDITIONALLY — for every
# tag, including the byte-locked ones.  That is a behaviour change on the
# 0.8B emit path, so it needs a 0.8B run.
#
# WHAT IT MEASURES, and the last one is the decisive one:
#
#   1  emit a 0.8B layer stream at HEAD, and read the meta's keys back:
#      `shape_isa` must be ABSENT and `rs_f` must be ABSENT.
#   2  emit the SAME stream from a worktree at <base-commit> (default
#      1c62570, the tree this task started from), i.e. from the emitter as
#      it was BEFORE `shape_isa` and the unconditional validate.
#   3  `cmp` the two `.seq` files AND the two `.seq.json` files.  IDENTICAL
#      is the claim "this task moved no 0.8B artifact byte", and it is the
#      only form of that claim that is a measurement rather than a reading
#      of the gating condition.
#   4  `ref/seq_model.py --gate` on the HEAD stream -> `SEQ GATE: PASS`,
#      which is what says the unconditional validate did not start refusing
#      a legitimate 0.8B stream.
#   5  the same emit at FABLE5_MODEL=9b, showing `shape_isa` PRESENT — the
#      other half of the table, in the same log.
#
# A2.5 IS OBSERVED: steps 1-4 run with FABLE5_RS_F ABSENT from the
# environment (the byte-locked tags must be emitted at the default), and only
# step 5 sets it.  The wrapper's header records `FABLE5_RS_F=unset`.
#
# WHAT THE BYTE-LOCK ACTUALLY COVERS is printed too, because "unmoved" is
# ambiguous otherwise: `ref/scripts/regen_gate.sh:5` pins the 0.8B
# `model_v2_s1.e.seq` sha256 and `:41` `cmp`s the `.txt`;
# `evidence/qwen9b/g2/FINAL_BYTELOCK.md` pins 54 file shas including both
# `.seq` and `.seq.json` of the committed 0.8B and 2B sets.  Those locks are
# checked against a re-emission from the CURRENT tree, and G3.1 SPENT them:
# the committed artifacts are SEQ_ISA v1.7 and this tree emits v2.0, so a
# re-emission cannot reproduce them and `ref/gen_layer_script.py:56-62` says
# so in the source.  The lock this task must not move is therefore the one
# that is still live: HEAD against its own immediate ancestry, which is
# exactly what step 3 measures.
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
BASE=${1:-1c62570}
PY=${PY:-$([ -x /home/cah/.venv/bin/python ] && echo /home/cah/.venv/bin/python \
           || echo "$ROOT/ref/.venv/bin/python")}
TMP=$(mktemp -d /var/tmp/g4a_bl_XXXXXX)
WT=$TMP/base_tree
trap 'rm -rf "$TMP"; git -C "$ROOT" worktree remove --force "$WT" 2>/dev/null' EXIT

echo "=== interpreter $PY"
echo "=== HEAD        $(git -C "$ROOT" rev-parse --short HEAD)"
echo "=== base        $BASE"
echo "=== FABLE5_RS_F in env: ${FABLE5_RS_F:-<unset>}   (A2.5: must be unset here)"
if [ -n "${FABLE5_RS_F:-}" ]; then
  echo "REFUSING: FABLE5_RS_F is exported; a byte-locked tag must be emitted"
  echo "  at the default (spec A2.5).  Unset it and re-run." >&2
  exit 3
fi
FAIL=0

emit08() {   # <outdir> <srcroot>
  mkdir -p "$1"
  ( cd "$2/ref" && SEQ_EMIT=$1/lay_s1.e SEQ_PROFILE=epsnorm \
      "$PY" gen_layer_script.py "$1/lay_s1.txt" 1 2 ) >"$1/emit.log" 2>&1
}

echo
echo "--- 1  a 0.8B layer stream from HEAD"
emit08 "$TMP/head" "$ROOT" || { echo "HEAD emit FAILED"; cat "$TMP/head/emit.log"; exit 3; }
tail -1 "$TMP/head/emit.log" | sed 's/^/    /'
"$PY" - "$TMP/head/lay_s1.e.seq.json" <<'EOF' | sed 's/^/    /'
import json, sys
m = json.load(open(sys.argv[1]))
print("meta keys that must be ABSENT at a byte-locked tag:")
for k in ("shape_isa", "rs_f"):
    print("      %-10s %s" % (k, "PRESENT -> %r" % m[k] if k in m else "ABSENT"))
EOF
for k in shape_isa rs_f; do
  if grep -q "\"$k\"" "$TMP/head/lay_s1.e.seq.json"; then
    echo "    ! $k is PRESENT in a 0.8B meta"; FAIL=1
  fi
done

echo
echo "--- 2  the SAME emit from a worktree at $BASE"
git -C "$ROOT" worktree add --detach "$WT" "$BASE" >/dev/null 2>&1 \
  || { echo "could not create the worktree at $BASE" >&2; exit 3; }
emit08 "$TMP/base" "$WT" || { echo "base emit FAILED"; cat "$TMP/base/emit.log"; exit 3; }
tail -1 "$TMP/base/emit.log" | sed 's/^/    /'

echo
echo "--- 3  byte comparison, HEAD vs $BASE"
for f in lay_s1.e.seq lay_s1.e.seq.json lay_s1.e.seqdata.bin lay_s1.txt; do
  a=$TMP/head/$f; b=$TMP/base/$f
  if cmp -s "$a" "$b"; then
    echo "    IDENTICAL  $(wc -c <"$a" | tr -d ' ') B  $f"
  else
    echo "    DIFFER     $f"; FAIL=1
  fi
done
echo "    HEAD .seq sha256 $(sha256sum "$TMP/head/lay_s1.e.seq" | cut -d' ' -f1)"
echo "    base .seq sha256 $(sha256sum "$TMP/base/lay_s1.e.seq" | cut -d' ' -f1)"

echo
echo "--- 4  ref/seq_model.py --gate on the HEAD 0.8B stream"
( cd "$ROOT/ref" && "$PY" seq_model.py --gate "$TMP/head/lay_s1.e" \
    --base "$TMP/head/lay_s1" ) >"$TMP/gate.log" 2>&1
GRC=$?
sed 's/^/    /' "$TMP/gate.log"
grep -q "^SEQ GATE: PASS" "$TMP/gate.log" || { echo "    ! no SEQ GATE: PASS (rc=$GRC)"; FAIL=1; }

echo
echo "--- 5  the 9B half of the same table, for contrast"
mkdir -p "$TMP/nine"
( cd "$ROOT/ref" && FABLE5_MODEL=9b FABLE5_RS_F=7 SEQ_PROFILE=epsnorm \
    SEQ_NCH=4 SEQ_REPACK=1 SEQ_EMIT=$TMP/nine/lay9b.e4 \
    "$PY" gen_layer_script.py "$TMP/nine/lay9b.txt" 1 2 ) >"$TMP/nine/emit.log" 2>&1 \
  || { echo "9B emit FAILED"; cat "$TMP/nine/emit.log"; exit 3; }
tail -1 "$TMP/nine/emit.log" | sed 's/^/    /'
"$PY" - "$TMP/nine/lay9b.e4.seq.json" <<'EOF' | sed 's/^/    /'
import json, sys
m = json.load(open(sys.argv[1]))
for k in ("shape_isa", "rs_f"):
    print("      %-10s %s" % (k, "PRESENT -> %r" % m[k] if k in m else "ABSENT"))
EOF
grep -q '"shape_isa"' "$TMP/nine/lay9b.e4.seq.json" \
  || { echo "    ! a 9B meta does NOT declare shape_isa"; FAIL=1; }

echo
echo "--- what the byte-lock covers, and against which emitter"
echo "    ref/scripts/regen_gate.sh:5   GOLD_SEQ_SHA for tb/scripts/w4/model_v2_s1.e.seq"
grep -n "^GOLD_SEQ_SHA" "$ROOT/ref/scripts/regen_gate.sh" | sed 's/^/      /'
echo "    the committed 0.8B artifact it is checked against:"
if [ -f "$ROOT/tb/scripts/w4/model_v2_s1.e.seq" ]; then
  echo "      $(sha256sum "$ROOT/tb/scripts/w4/model_v2_s1.e.seq")"
else
  echo "      tb/scripts/w4/model_v2_s1.e.seq ABSENT (gitignored build product)"
fi
echo "    ref/seq_format.SEQ_ISA_VERSION = $("$PY" -c "import sys;sys.path.insert(0,'$ROOT/ref');import seq_format as SF;print(SF.SEQ_ISA_VERSION)")  (this tree emits v2.0; the frozen artifacts are v1.7)"

echo
if [ "$FAIL" = 0 ]; then echo "G4A_BYTELOCK_08B: PASS"
else echo "G4A_BYTELOCK_08B: FAIL"; fi
exit "$FAIL"
