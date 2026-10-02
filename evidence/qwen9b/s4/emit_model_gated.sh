#!/usr/bin/env bash
# emit_model_gated.sh — S4: emit ONE 9B MODEL stream TWICE and keep it only
# if the two emissions agree byte for byte.
#
#   bash evidence/qwen9b/s4/emit_model_gated.sh <seed>
#   (bash, NOT sh: the emitter's rc is taken from PIPESTATUS below)
#
# Emission A is the KEPT artifact, `tb/scripts/w9/model_9b_s<seed>`.
# Emission B is an independent re-run into `tb/scripts/w9/emit2/model_9b_s<seed>/rep2`.
# Both go through the SAME make target with only `W9_BASE` different, so the
# two emissions cannot differ by command construction or by an environment
# variable — that is S3's rule (`evidence/qwen9b/s3/emit_repeat.sh`), kept.
#
# WHY THIS EXISTS AND IS NOT `make -C tb w9_9b_model_script` ON ITS OWN.
# S3 fix round 2 wired the emit-twice gate into the three artifact targets.
# It worked for the two SMOKE targets; WHEN THIS SCRIPT WAS WRITTEN it could
# not fire for the MODEL target at all, for two independent reasons, both of
# them the runtime range audit that G4a §3.4 measured and this campaign
# deliberately does not silence:
#
#   1. `gen_model_script.py` exits NON-ZERO at 9B without `--allow-clip`
#      (the audit fails; the artifacts are still written, by the atexit
#      hook in `ref/seq_format._finalize`).  The emitter was a PLAIN recipe
#      line -- no `-` prefix, no `|| true` -- so make abandoned the recipe
#      there and the `if [ "$(W9_EMIT2)" = 1 ]` block below it never ran.
#      G4a's own emission logs show it:
#      `make: *** [Makefile:1267: w9_9b_model_script] Error 1`,
#      `=== rc: 2` (`evidence/qwen9b/g4/030_emit_9b_s2.log`).
#   2. Even if it were reached, `evidence/qwen9b/s3/emit_repeat.sh` treated
#      a non-zero emitter rc as `run i ABORTED` and FAILED -- so the gate
#      could never PASS on an artifact whose emitter exits non-zero by
#      design.  It also discarded the emitter's stdout, so it could not have
#      inspected the audit line even if it had wanted to.
#
# BOTH ARE FIXED NOW -- S4 fix round 1, review I1.  `tb/Makefile:1409-1439`
# captures the emitter's rc and applies exactly the contract below before
# running the emit-twice block at `tb/Makefile:1431-1438`, and
# `evidence/qwen9b/s3/emit_repeat.sh` carries the same contract and keeps
# each run's output.  Both halves are proved to fire BOTH ways, at shim
# scale, by `evidence/qwen9b/s4/emit2_gate_red.sh` (one GREEN, three REDs).
# This script is kept, unchanged in behaviour, because it is the record of
# what produced `evidence/qwen9b/s4/001_emit_9b_s1.log` and its three
# siblings, and because it compares a strictly LARGER file set than the
# Makefile gate does -- see below.
#
# WHAT IS COMPARED.  S3's four — `.txt`, `.e4.seq`, `.e4.seqdata.bin`,
# `.state_final.bin` — and then, because a model emission also carries
# 3.9 GiB of quantized weight images and a 1.9 GiB embedding table that no
# smoke artifact has and that the four-file list therefore does not cover:
# `.state.bin`, `.e4.seq.json`, `.weights.json`, `.emb.bin`, and a
# CONTENT digest over the 249 `_w<wid>.bin` images (the same shape of
# digest `evidence/qwen9b/g4/g4a_artifact_inventory.py:100-115` computes,
# keyed by wid so the two prefixes' different basenames cannot matter).
# Every one of them is load-bearing for the replay, and every one of them
# is a place the darthplagueis arithmetic defect (S3 fix round 1, C1) would
# have shown up.
#
#   rc 0  EMIT_GATED s<seed>: PASS — the two emissions are identical
#   rc 1  EMIT_GATED s<seed>: FAIL — they are not; the artifact MUST NOT be
#         kept, and both trees are left on disk for the post-mortem
#   rc 2  EMIT_GATED s<seed>: ABORTED — an emission died for a reason that
#         is NOT the known range audit; the run is PRESERVED, not retried
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
S=${1:?usage: emit_model_gated.sh <seed>}
MODELPY=${MODELPY:-/home/cah/.venv/bin/python}

KEEP_REL=scripts/w9/model_9b_s$S
REP_DIR=$ROOT/tb/scripts/w9/emit2/model_9b_s$S
REP_REL=scripts/w9/emit2/model_9b_s$S/rep2
KEEP=$ROOT/tb/$KEEP_REL
REP=$ROOT/tb/$REP_REL
mkdir -p "$REP_DIR"

echo "EMIT_GATED s$S: two independent emissions, byte-compared"
echo "  host    = $(hostname)"
echo "  MODELPY = $MODELPY"
echo "  keep    = tb/$KEEP_REL"
echo "  repeat  = tb/$REP_REL"
echo "  python  = $("$MODELPY" -c 'import sys,numpy;print(sys.version.split()[0],"numpy",numpy.__version__)')"

# ---------------------------------------------------------------- emit
emit () {  # $1 = tag (A|B), $2 = W9_BASE (relative to tb/), $3 = capture file
  echo
  echo "=== emission $1: make -C tb w9_9b_model_script W9_SEED=$S W9_BASE=$2"
  echo "=== emission $1 start: $(date -Is)"
  nice -n 10 make -C "$ROOT/tb" w9_9b_model_script \
      W9_EMIT2=0 W9_SEED="$S" W9_BASE="$2" MODELPY="$MODELPY" 2>&1 | tee "$3"
  rc=${PIPESTATUS[0]}
  echo "=== emission $1 end: $(date -Is)  rc=$rc"
  if [ "$rc" = 0 ]; then
    echo "=== emission $1: rc 0"
    return 0
  fi
  # The ONE non-zero rc this campaign accepts, and only with its own
  # evidence in the output: the runtime range audit, failed deliberately
  # because `--allow-clip` is not passed (G4a §3.4).  The artifacts are
  # written on that path -- `ref/seq_format._finalize` is an atexit hook --
  # and the SEQ line proves the stream was finalized.
  if grep -q "^RANGE AUDIT FAILED" "$3" && grep -q "^SEQ: .* records .* -> " "$3"; then
    if grep -qE "Traceback \(most recent call last\)|AssertionError" "$3"; then
      echo "=== emission $1: ABORTED — a traceback/assert is present as well"
      return 2
    fi
    echo "=== emission $1: rc $rc is the KNOWN deliberate range-audit failure"
    echo "===             (G4a §3.4: no --allow-clip), artifacts written"
    return 0
  fi
  echo "=== emission $1: ABORTED — rc $rc is NOT the known range-audit failure"
  grep -nE "Traceback \(most recent call last\)|Error|assert" "$3" | tail -20
  return 2
}

emit A "$KEEP_REL" "$REP_DIR/emitA.out" || { rc=$?; \
  [ "$rc" = 2 ] && { echo "EMIT_GATED s$S: ABORTED (emission A preserved)"; exit 2; }; }
emit B "$REP_REL" "$REP_DIR/emitB.out" || { rc=$?; \
  [ "$rc" = 2 ] && { echo "EMIT_GATED s$S: ABORTED (emission B preserved)"; exit 2; }; }

# The two command lines the recipe actually ran, side by side: they must
# differ in the prefix and in NOTHING else.
echo
echo "=== the two emitter command lines, as make echoed them"
grep -h "gen_model_script.py" "$REP_DIR/emitA.out" | head -2
grep -h "gen_model_script.py" "$REP_DIR/emitB.out" | head -2

# ------------------------------------------------------------- compare
FAIL=0
cmp_one () {  # $1 = suffix, $2 = "gate"|"extra"
  a="$KEEP$1"; b="$REP$1"
  if [ ! -f "$a" ] || [ ! -f "$b" ]; then
    printf '  %-18s MISSING   keep:%s repeat:%s\n' "$1" \
      "$([ -f "$a" ] && echo yes || echo NO)" \
      "$([ -f "$b" ] && echo yes || echo NO)"
    FAIL=1; return
  fi
  ha=$(sha256sum "$a" | cut -d' ' -f1)
  hb=$(sha256sum "$b" | cut -d' ' -f1)
  sz=$(stat -c %s "$a")
  if [ "$ha" = "$hb" ]; then
    printf '  %-18s IDENTICAL %14s B  %s\n' "$1" "$sz" "$ha"
  else
    printf '  %-18s DIFFERS   %14s B  keep %s  repeat %s\n' "$1" "$sz" "$ha" "$hb"
    FAIL=1
  fi
}

# a CONTENT digest over the weight images, keyed by wid (the basenames
# differ between the two prefixes, the wids do not)
imgsha () {  # $1 = prefix -> "<count> <sha256>"
  # NOT one pipeline: the left side of a pipeline runs in a subshell, so a
  # counter incremented there would not survive it.
  n=$(ls "$1"_w*.bin 2>/dev/null | wc -l)
  d=$(for f in "$1"_w*.bin; do
        [ -f "$f" ] || continue
        w=${f##*_w}; w=${w%.bin}
        printf '%s %s %s\n' "$w" "$(stat -c %s "$f")" \
          "$(sha256sum "$f" | cut -d' ' -f1)"
      done | sort -n | sha256sum | cut -d' ' -f1)
  echo "$n $d"
}

echo
echo "=== the S3 four (evidence/qwen9b/s3/emit_repeat.sh's list)"
for s in .txt .e4.seq .e4.seqdata.bin .state_final.bin; do cmp_one "$s" gate; done

echo
echo "=== beyond the S3 four — everything else a model emission writes"
for s in .state.bin .e4.seq.json .emb.bin; do cmp_one "$s" extra; done
# `.weights.json` is the ONE artifact that legitimately differs between two
# emissions: `Mach.dump_weights` records each image's BASENAME
# (`ref/gen_layer_script.py:1745` for the conv images, and the per-wid
# "file" keys), and the two emissions have different prefixes by
# construction.  Verified against S3's smoke pair, whose two manifests
# differ in exactly those name fields and nothing else.  So it is compared
# with the prefix normalised away -- which still catches every numeric
# field: shapes, e/sh exponents, bases, ng, the state plan and its sha.
manrepr () { b=$(basename "$1"); sed "s/\"$b/\"PREFIX/g" "$1.weights.json" \
             | sha256sum | cut -d' ' -f1; }
MA=$(manrepr "$KEEP"); MB=$(manrepr "$REP")
if [ "$MA" = "$MB" ]; then
  printf '  %-18s IDENTICAL (prefix-normalised) %s\n' ".weights.json" "$MA"
else
  printf '  %-18s DIFFERS   keep %s  repeat %s\n' ".weights.json" "$MA" "$MB"
  FAIL=1
fi
for f in "$KEEP"_cv*.bin; do
  [ -f "$f" ] || continue
  cmp_one "_cv${f##*_cv}" extra
done
IA=$(imgsha "$KEEP"); IB=$(imgsha "$REP")
if [ "$IA" = "$IB" ]; then
  printf '  %-18s IDENTICAL %s images, content sha256 %s\n' "_w*.bin" \
    "${IA%% *}" "${IA#* }"
else
  printf '  %-18s DIFFERS   keep [%s]  repeat [%s]\n' "_w*.bin" "$IA" "$IB"
  FAIL=1
fi

# ------------------------------------------------------- the manifest's
# own state sha, against the file's bytes (S3 fix round 2's check; the
# dispatch note requires it on every NEW model manifest)
echo
echo "=== the manifest's state.sha256 against the file's bytes"
"$MODELPY" - "$KEEP" <<'PY' || FAIL=1
import hashlib, json, os, sys
p = sys.argv[1]
man = json.load(open(f"{p}.weights.json"))
st = man.get("state")
if st is None:
    print("  STATE_SHA: FAIL — the manifest carries no 'state' key")
    raise SystemExit(1)
h = hashlib.sha256()
with open(f"{p}.state.bin", "rb") as f:
    for c in iter(lambda: f.read(1 << 22), b""):
        h.update(c)
ok = h.hexdigest() == st["sha256"]
print(f"  state.bin      {os.path.getsize(f'{p}.state.bin')} B  "
      f"manifest {st['sha256'][:16]}  file {h.hexdigest()[:16]}  "
      f"{'MATCH' if ok else 'MISMATCH'}")
print(f"  state plan     dn={st['dn']} kv={st['kv']} cv={st['cv']} end={st['end']}")
print(f"  conv images    {len(man.get('conv_images') or [])}")
raise SystemExit(0 if ok else 1)
PY

echo
if [ "$FAIL" = 0 ]; then
  echo "EMIT_GATED s$S: PASS — two independent emissions, byte-identical"
  exit 0
fi
echo "EMIT_GATED s$S: FAIL — the two emissions DIFFER; the artifact is not"
echo "  reproducible on this host and MUST NOT be kept (both trees left in"
echo "  place: tb/$KEEP_REL and tb/$REP_REL)"
exit 1
