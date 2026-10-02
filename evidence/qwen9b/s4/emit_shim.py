#!/usr/bin/env python3
"""emit_shim.py — a stand-in for MODELPY that proves the emit-twice gate on
`tb/Makefile`'s `w9_9b_model_script` FIRES, at seconds instead of 3.5 hours.

S4's review (I1) established that the wired gate could not fire on the model
target: `tb/Makefile`'s emitter was a plain recipe line, `gen_model_script.py`
exits non-zero BY DESIGN on the runtime range audit, and
`evidence/qwen9b/s3/emit_repeat.sh` treated any non-zero rc as ABORTED.  All
three are fixed.  Proving the fix must NOT cost another GPTQ pass, so this
script is substituted for `MODELPY`: the recipe runs

    cd ../ref && <env> SEQ_EMIT=<prefix>.e4 $(MODELPY) gen_model_script.py \\
        <prefix>.txt <seed> <ntok> <flags...>

and this shim ignores argv[1] (the generator name), writes the four files a
9B emission is compared on, and REPRODUCES THE EMITTER'S EXIT CONTRACT:

  * the finalizer's `SEQ: <n> records (<b> B) + <c> B const blob -> <path>
    [profile=epsnorm loop_steps=3]` line, on stdout, the way
    `ref/seq_format._finalize`'s atexit hook prints it;
  * `RANGE AUDIT FAILED: ...` on stderr, the way
    `ref/gen_model_script.py:711-721`'s `raise SystemExit(msg)` does;
  * exit status 1 — the audit's by-design rc, which make reports as
    `Error 1` and translates into its own exit status 2.

THE BYTES ARE A FUNCTION OF THE SEED ALONE, deterministically, which is what
makes the RED possible: `EMIT2_FORCE_FAIL=1` makes `emit_repeat.sh` re-emit
at seed + 1, the bytes move, and the comparison must CATCH it.

  SHIM_MODE=green      (default) audit line + SEQ line, rc 1  -> the block
                       must be REACHED and must PASS
  SHIM_MODE=no_audit   rc 1 with NO audit line                -> the recipe
                       must ABORT BEFORE the block
  SHIM_MODE=traceback  audit line + SEQ line + a Traceback, rc 1
                       -> the recipe must ABORT BEFORE the block

Nothing this writes is an artifact anything else reads; the prefixes live
under `tb/scripts/w9/shim/`, which is a gitignored build area.
"""
import hashlib
import os
import sys

MODE = os.environ.get("SHIM_MODE", "green")

# `emit_repeat.sh:58` banners the interpreter with `"$MODELPY" -c '...'`
# before it emits anything.  Answer that the way an interpreter would, so the
# banner is a line and not an error.
if len(sys.argv) > 1 and sys.argv[1] == "-c":
    print("emit_shim (not a python) numpy n/a")
    raise SystemExit(0)

# argv: [shim, <generator>.py, <prefix>.txt, <seed>, <ntok>, <flags>...]
if len(sys.argv) < 4:
    sys.stderr.write("emit_shim: usage <gen.py> <prefix>.txt <seed> [ntok] ...\n")
    raise SystemExit(3)
gen = sys.argv[1]
txt = sys.argv[2]
seed = sys.argv[3]
rest = sys.argv[4:]
if not txt.endswith(".txt"):
    sys.stderr.write("emit_shim: argv[2] must end in .txt, got %r\n" % txt)
    raise SystemExit(3)
prefix = txt[: -len(".txt")]
seq = os.environ.get("SEQ_EMIT", prefix + ".e4")

for d in {os.path.dirname(os.path.abspath(txt)),
          os.path.dirname(os.path.abspath(seq))}:
    os.makedirs(d, exist_ok=True)


def blob(tag, n):
    """n deterministic bytes that depend on the SEED and the tag only."""
    out = bytearray()
    k = 0
    while len(out) < n:
        out += hashlib.sha256(("%s|%s|%d" % (tag, seed, k)).encode()).digest()
        k += 1
    return bytes(out[:n])


with open(txt, "w") as f:
    f.write("# emit_shim %s seed=%s rest=%s\n" % (gen, seed, " ".join(rest)))
    f.write(blob("txt", 4096).hex())
    f.write("\nQ\n")
with open(seq + ".seq", "wb") as f:
    f.write(blob("seq", 8192))
with open(seq + ".seqdata.bin", "wb") as f:
    f.write(blob("seqdata", 2048))
with open(prefix + ".state_final.bin", "wb") as f:
    f.write(blob("state_final", 4096))

sys.stdout.write(
    "SEQ: %d records (%d B) + %d B const blob -> %s.seq  "
    "[profile=epsnorm loop_steps=3]\n" % (158536, 2536576, 563712, seq))
sys.stdout.flush()

if MODE == "traceback":
    sys.stderr.write(
        "Traceback (most recent call last):\n"
        '  File "gen_model_script.py", line 1, in <module>\n'
        "    emit_shim synthetic failure\n"
        "AssertionError: emit_shim synthetic failure\n")

if MODE != "no_audit":
    sys.stderr.write(
        "RANGE AUDIT FAILED: a frozen fixed-point format SATURATES on the "
        "real weights (details above).\n")
else:
    sys.stderr.write(
        "emit_shim: SHIM_MODE=no_audit — exiting non-zero with NO audit "
        "line; the recipe must abort BEFORE the emit-twice block.\n")
sys.stderr.flush()
raise SystemExit(1)
