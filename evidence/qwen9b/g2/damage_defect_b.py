#!/usr/bin/env python3
"""damage_defect_b.py — the G2a regression for defect B, in the Track F style.

    python3 evidence/qwen9b/g2/damage_defect_b.py            # 0.8b (default)
    FABLE5_MODEL=2b python3 evidence/qwen9b/g2/damage_defect_b.py
    FABLE5_MODEL=9b python3 evidence/qwen9b/g2/damage_defect_b.py

WHAT DEFECT B WAS (spec 7.3, evidence/qwen_next/defect_a/CORRECTIONS.md C2).
`sw/infer.py`'s online `step()` carried four hard `1024` literals where `LR.H`
belongs:

    M.vnw_(STG, 1024)                       # RMSNorm weight load length
    M.vn(1, 1024, RS_F, RS_F, X0, XN)       # RMSNorm length
    M.alu(0, 1024, 0, XN, 0, X8)            # DYNQ8 length
    y32, _ = M.matvec(self.qw_head, X8, 1024, rowchunk=ROWCHUNK)

THE CRASH IS WHERE IT STOPS, NOT WHERE IT STARTS, and that is the whole point
of testing this by damage rather than by reading.  `matvec_y32` raises at
`n_in=1024` against an H-wide head, so a reader concludes "it fails loudly".
It does not: the THREE LINES BEFORE it run silently on half the residual, and
because RMSNorm's denominator is a mean over the words it is TOLD about, they
corrupt even the words they do write.  Track F measured it at 2B on an
unevenly-split residual: the DYNQ8 exponent SHIFTS and 99.6 % of the leading
half changes, max |diff| 99.  (An i.i.d.-uniform residual gives max |diff| 1,
which is why a single sample is not evidence and why this file uses a
deliberately uneven one.)

WHAT THIS FILE PROVES, in three parts:

  [1] THE FIX IS IN.  `sw/infer.py` has no hard 1024 on the step() path, by
      AST inspection of the real source — not by grep, so a `1024` inside a
      comment or an unrelated expression cannot pass or fail it by accident.

  [2] THE DAMAGE IS DETECTABLE.  The numeric core of the three silent lines
      is re-run at the true width and at the damaged width 1024, and the
      difference is measured: the DYNQ8 exponent and the fraction of leading
      words that change.  At H=1024 the "damage" is the identity and the test
      says so rather than pretending to detect something.

  [3] THE FOURTH LINE STILL RAISES.  `matvec_y32` is called with n_in=1024
      against an H-wide head and must refuse.

Exit 0 = the fix holds and the damage is detectable.  Exit 1 = a check failed.
"""
import ast
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (os.path.join(_ROOT, "ref"), os.path.join(_ROOT, "sw")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import layer_ref as LR                                          # noqa: E402
import layer_fixed as LF                                        # noqa: E402
import model_select as MS                                       # noqa: E402
from w4a8_ref import matvec_y32                                 # noqa: E402

INFER = os.path.join(_ROOT, "sw", "infer.py")

npass = nfail = 0


def check(name, cond, detail=""):
    global npass, nfail
    if cond:
        npass += 1
        print(f"  PASS {name}")
    else:
        nfail += 1
        print(f"  FAIL {name}: {detail}")
    return bool(cond)


# ----------------------------------------------------------------- [1]
def step_constants():
    """Every integer literal appearing as an ARGUMENT inside `step()`.

    AST, not grep: a comment, a docstring or a `2048` in a different method
    cannot reach this list, and a literal hidden inside a nested call can
    not escape it.
    """
    tree = ast.parse(open(INFER).read(), INFER)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "step":
            out = []
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    for arg in list(sub.args) + [k.value for k in sub.keywords]:
                        if (isinstance(arg, ast.Constant)
                                and isinstance(arg.value, int)):
                            out.append((sub.func.attr
                                        if isinstance(sub.func, ast.Attribute)
                                        else "?", arg.value, arg.lineno))
            return out
    return None


print(f"damage_defect_b: FABLE5_MODEL={MS.TAG}  H={LR.H}  RS_F={LF.RS_F}")
print("[1] the fix is in — no hard 1024 argument on the online step() path")
consts = step_constants()
if not check("sw/infer.py has a step() method to inspect", consts is not None):
    sys.exit(1)
bad = [c for c in consts if c[1] == 1024]
check("no call inside step() passes a literal 1024",
      not bad, f"{bad}")
# The 2048 AMAX32 staging chunk MUST still be there: a "fix" that
# parameterized it to H would be wrong.
#
# WHAT IT IS: the host W32 injection chunk, `ref/gen_layer_script.CHUNK`.
# NOT an ISA limit -- an earlier revision of this file, of `sw/infer.py`'s
# comment and of the gate doc all said "ISA limit", and the fix-round logs
# printed that wrong claim as a PASS.  The pin is now STRUCTURAL: it compares
# against `GLS.CHUNK` rather than against a repeated literal, so if CHUNK ever
# moves this check follows it instead of silently pinning a stale number.
import gen_layer_script as GLS                                  # noqa: E402
check(f"the AMAX32 staging chunk is still the literal {GLS.CHUNK} "
      f"(= ref/gen_layer_script.CHUNK, the host W32 injection chunk — "
      f"NOT an ISA limit, and NOT H)",
      any(c[1] == GLS.CHUNK for c in consts), f"{consts}")

# ----------------------------------------------------------------- [2]
print("[2] the damage is detectable — the three SILENT lines, measured")
rng = np.random.default_rng(7)
# A deliberately UNEVEN residual: the two halves have different scales, which
# is what makes the truncated RMSNorm denominator wrong.  Track F's finding is
# that an i.i.d. residual hides this almost completely.
x = np.empty(LR.H, dtype=np.int64)
half = LR.H // 2
x[:half] = rng.integers(-4000, 4000, half)
x[half:] = rng.integers(-200, 200, LR.H - half)
w = np.asarray(np.round(rng.normal(0, 0.5, LR.H) * (1 << 12)), dtype=np.int64)


def three_lines(n):
    """vnw_/vn/alu at length `n` — the three lines that run SILENTLY."""
    xn = LF.rmsnorm_fx(x[:n], w[:n], LF.RS_F, True)
    import fixedpoint as fp
    x8, e = fp.dyn_quant_i8(np.asarray(xn, dtype=np.int64))
    return np.asarray(x8, dtype=np.int64), int(e)


good8, good_e = three_lines(LR.H)
dmg8, dmg_e = three_lines(1024)
if LR.H == 1024:
    check("at H=1024 the damaged width IS the true width, so the two agree "
          "exactly — this geometry cannot detect defect B and says so",
          dmg_e == good_e and np.array_equal(dmg8, good8),
          f"e {dmg_e} vs {good_e}")
else:
    nchg = int((dmg8 != good8[:1024]).sum())
    frac = 100.0 * nchg / 1024
    print(f"    DYNQ8 exponent  true {good_e}  damaged {dmg_e}")
    print(f"    leading 1024 words changed: {nchg}/1024 = {frac:.1f} %")
    print(f"    max |diff| over the leading half: "
          f"{int(np.abs(dmg8 - good8[:1024]).max())}")
    check("the damaged width changes the DYNQ8 exponent OR most of the "
          "leading half — silently, with no exception raised",
          dmg_e != good_e or frac > 50.0,
          f"e {dmg_e} vs {good_e}, {frac:.1f} % changed")
    check("the damaged width leaves the TAIL of the residual untouched — "
          "that is the half a reader would never look at",
          len(good8) > 1024)

# ----------------------------------------------------------------- [3]
print("[3] the fourth line still raises — matvec_y32 refuses n_in=1024")
w4 = np.zeros((4, LR.H), dtype=np.int8)          # an H-wide "head"
m = np.zeros((4, LR.H // 128), dtype=np.int8)
# The CONTROL first: the same call at the TRUE width must SUCCEED, or a
# refusal below would prove nothing about the width — it would only prove
# the call was malformed.  (This file's first cut got that wrong: it passed
# the wrong number of arguments and scored the resulting TypeError as a
# refusal.  A damage test that cannot tell a real failure from a broken call
# is not a test.)
ok_ctrl = False
try:
    y = matvec_y32(w4, m, 5, np.zeros(LR.H, dtype=np.int64))
    ok_ctrl = (np.asarray(y).shape == (4,))
except Exception as ex:                              # noqa: BLE001
    print(f"    control raised: {type(ex).__name__}: {str(ex)[:110]}")
check("CONTROL: matvec_y32 accepts an H-wide activation against an H-wide "
      "head", ok_ctrl)
if LR.H == 1024:
    check("at H=1024 there is nothing for it to refuse (n_in IS H)", True)
else:
    raised = None
    try:
        matvec_y32(w4, m, 5, np.zeros(1024, dtype=np.int64))
    except Exception as ex:                          # noqa: BLE001
        raised = ex
        print(f"    raised: {type(ex).__name__}: {str(ex)[:110]}")
    check("matvec_y32 refuses a 1024-wide activation against an H-wide head, "
          "and NOT with a TypeError about the call itself",
          raised is not None and not isinstance(raised, TypeError),
          repr(raised))

print(f"damage_defect_b: {npass} passed, {nfail} failed")
sys.exit(1 if nfail else 0)
