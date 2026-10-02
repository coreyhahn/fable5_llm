"""RED control for evidence/qwen9b/g2/damage_defect_b.py.

Puts defect B's four literals BACK into sw/infer.py, requires the regression
to FAIL, then restores the file byte-for-byte and re-runs to require GREEN.
A test that has never been seen to fail is not a test.
"""
import hashlib
import os
import subprocess
import sys

ROOT = "/home/cah/r2d2/code/fpga/fable5_llm"
P = os.path.join(ROOT, "sw", "infer.py")
TEST = os.path.join(ROOT, "evidence", "qwen9b", "g2", "damage_defect_b.py")
PY = "/home/cah/.venv/bin/python"

orig = open(P).read()
before = hashlib.sha256(orig.encode()).hexdigest()
print(f"sw/infer.py sha256 before: {before}")

dmg = (orig
       .replace("        M.vnw_(STG, LR.H)\n",
                "        M.vnw_(STG, 1024)\n")
       .replace("        M.vn(1, LR.H, RS_F, RS_F, X0, XN)\n",
                "        M.vn(1, 1024, RS_F, RS_F, X0, XN)\n")
       .replace("        M.alu(0, LR.H, 0, XN, 0, X8)\n",
                "        M.alu(0, 1024, 0, XN, 0, X8)\n")
       .replace("M.matvec(self.qw_head, X8, LR.H, rowchunk=ROWCHUNK)",
                "M.matvec(self.qw_head, X8, 1024, rowchunk=ROWCHUNK)"))
assert dmg != orig, "the damage did not apply — the fix is not where expected"
assert dmg.count("1024") - orig.count("1024") == 4, \
    "expected exactly four literals to come back"

rc_red = None
try:
    open(P, "w").write(dmg)
    print("\n=== RED: the four literals are back in sw/infer.py ===")
    r = subprocess.run([PY, TEST], capture_output=True, text=True,
                       cwd=ROOT, env=dict(os.environ, FABLE5_MODEL="2b"))
    print(r.stdout.rstrip())
    if r.stderr.strip():
        print(r.stderr[-800:])
    rc_red = r.returncode
    print(f"RED rc = {rc_red}")
finally:
    open(P, "w").write(orig)

after = hashlib.sha256(open(P, "rb").read().decode().encode()).hexdigest()
print(f"\nsw/infer.py sha256 after restore: {after}")
assert after == before, "RESTORE FAILED — sw/infer.py is not byte-identical"
print("restore verified: byte-identical")

print("\n=== GREEN: the fix is back ===")
g = subprocess.run([PY, TEST], capture_output=True, text=True,
                   cwd=ROOT, env=dict(os.environ, FABLE5_MODEL="2b"))
print(g.stdout.rstrip())
print(f"GREEN rc = {g.returncode}")

ok = (rc_red == 1 and g.returncode == 0)
print("\nRED->GREEN " + ("PASS — the regression fails on damaged code and "
                         "passes on fixed code"
                         if ok else
                         f"FAIL — red rc {rc_red}, green rc {g.returncode}"))
sys.exit(0 if ok else 1)
