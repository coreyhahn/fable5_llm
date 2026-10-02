#!/usr/bin/env python3
"""d_stage_check.py — D-STAGE: does DERIVING the staging mask move a golden?

    python3 evidence/qwen9b/g2/d_stage_check.py

D-STAGE (spec §9) is `tb/scripts/gen_chat_i1_vectors.py`'s staging mask, which
was the bare literal `np.zeros(16384)` where its sibling `ref/seq_model.py:1395`
derives the same thing.  The spec's disposition is *"derive it, and record
whether deriving it changes any committed i1 golden (it should not at 0.8B,
which is the point of checking)"* — so this file CHECKS it rather than
asserting it.

METHOD.  Run the real generator TWICE on the same tree, changing exactly one
thing: `gen_layer_script.SCRATCH` is forced to the old literal 16384 for the
first run and left derived for the second.  Everything else — the template,
the artifact, the seed, the tree — is identical, so a difference in the output
can only be the mask.  Compare `.chip` (the golden), `.seq` and
`.seqdata.bin` by sha256.

WHY `GLS.SCRATCH` AND NOT `sw/hwmap.SCRATCH_WORDS`, which is what the spec's
D-STAGE row names: the mask indexes `L["mem"]`, which is
`gen_layer_script.Mach.mem` — depth `GLS.SCRATCH`, the EMITTER's power-of-two
scratch depth for this geometry (16384 at 0.8B).  `SCRATCH_WORDS` is the
HARDWARE array, which G2a moved to 65,536.  Deriving from the hardware number
was tried first and it does not merely change the golden, it dies:
`IndexError: index 16384 is out of bounds for axis 0 with size 16384` from the
MEM writer.  That is recorded here because it is the whole reason the row says
"record whether", and because the two numbers being different is exactly the
coupling G2a's `SCRATCH_WORDS` comment warns about.

NOT A COMPARISON AGAINST `tb/scripts/w4/chat_i1.chip` ON DISK.  That file is a
gitignored build artifact from 2026-08-13 and predates R-c/R-d changes to the
chain, so it differs for reasons that have nothing to do with this mask.  The
controlled A/B above is the test; the on-disk sha is printed for the record.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "..", ".."))
GEN = os.path.join(ROOT, "tb", "scripts", "gen_chat_i1_vectors.py")
BASE = os.path.join(ROOT, "tb", "scripts", "w4", "model_v2_s1")
ONDISK = os.path.join(ROOT, "tb", "scripts", "w4", "chat_i1.chip")


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run(td, tag, force_old):
    out = os.path.join(td, tag)
    shim = os.path.join(td, f"shim_{tag}.py")
    with open(shim, "w") as f:
        f.write(
            "import sys, os, runpy\n"
            f"sys.path.insert(0, os.path.join(r'{ROOT}', 'ref'))\n"
            f"sys.path.insert(0, os.path.join(r'{ROOT}', 'sw'))\n"
            "import gen_layer_script as GLS\n"
            + ("GLS.SCRATCH = 16384   # the pre-G2a literal\n"
               if force_old else "")
            + f"sys.argv = [r'{GEN}', r'{out}', '--base', r'{BASE}']\n"
            f"runpy.run_path(r'{GEN}', run_name='__main__')\n")
    r = subprocess.run([sys.executable, shim], capture_output=True,
                       text=True, cwd=ROOT)
    print(f"  run [{tag}] (SCRATCH {'forced 16384' if force_old else 'derived'})"
          f": rc {r.returncode}")
    if r.returncode:
        print(r.stdout[-1500:])
        print(r.stderr[-1500:])
        sys.exit(1)
    return out


def main():
    if not os.path.exists(BASE + ".weights.json"):
        sys.exit(f"missing artifact {BASE}.weights.json — this check needs the "
                 f"model_v2_s1 build products (gitignored, regenerable)")
    td = tempfile.mkdtemp(prefix="d_stage_")
    try:
        a = run(td, "pre_fix", True)
        b = run(td, "derived", False)
        bad = 0
        for ext in (".chip", ".seq", ".seqdata.bin"):
            ha, hb = sha(a + ext), sha(b + ext)
            same = ha == hb
            bad += 0 if same else 1
            print(f"  {ext:16s} pre-fix {ha[:16]}  derived {hb[:16]}  "
                  f"{'IDENTICAL' if same else '*** DIFFERS ***'}")
        if os.path.exists(ONDISK):
            print(f"  (for the record: the gitignored on-disk "
                  f"tb/scripts/w4/chat_i1.chip is {sha(ONDISK)[:16]}, built "
                  f"2026-08-13, and is NOT the comparison above)")
        print("D_STAGE " + ("PASS — deriving the mask moved no golden byte"
                            if not bad else
                            f"FAIL — {bad} artifact(s) moved"))
        return 1 if bad else 0
    finally:
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
