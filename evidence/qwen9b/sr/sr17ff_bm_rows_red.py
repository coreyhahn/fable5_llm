"""sr17ff_bm_rows_red.py -- the seq-rtl round final fix round, item 2 (final
review minor 2): RED for the four new sw/seq_run.py selftest cases that tie
EVERY SEQ_VERSIONS row to hwmap.SEQ_BM_IDENT_BY_VERSION.

The committed tables are correct, so the new cases pass on the clean tree.
RED is shown by mutating the tables IN THIS PROCESS ONLY (never on disk, never
committed) and running the real sw/seq_run._selftest against each mutation:

  control    no mutation                               -> PASS
  m1         the build_042_bm1 BM row deleted          -> RED (missing row; pin)
  m2         the R2 (266e3ae7) BM row deleted          -> RED (missing row;
             caps/BM agreement; pin; and the SR14 R2 row check)
  m3         e3c2ff1e (caps {R1}) BM -> 0xDEADC0DE     -> RED (caps/BM; pin)
  m4         build_041's BM -> 0x12345678              -> RED (value; pin)
  m5         a NEW SEQ_VERSIONS row (caps {R1}) with no BM row -> RED (missing
             row; caps/BM agreement -- and the pre-existing SHAPE-row check)

Each mutation must fail at least the named new cases; the script exits 0
only when every expectation holds.  Board-free, no file writes beyond what
_selftest itself does (a temp dir it removes).
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(HERE, "sw"))
import seq_run as SR  # noqa: E402

HW = SR.HW
T = HW.SEQ_BM_IDENT_BY_VERSION
V = SR.SEQ_VERSIONS
T0, V0 = dict(T), dict(V)

MISS = "every SEQ_VERSIONS key"
VAL = "each row's BM_IDENT is the unmapped read"
AGREE = "a row expecting a SEQ_CAPS word"
PIN = "BM_IDENT pins"


def restore():
    T.clear()
    T.update(T0)
    V.clear()
    V.update(V0)


def run(tag, mutate, must_fail):
    restore()
    mutate()
    lines = []
    ok = SR._selftest(log=lines.append)
    restore()
    fails = [ln for ln in lines if "FAIL" in ln]
    summ = [ln for ln in lines if "seq_run selftest:" in ln]
    hit = all(any(m in f for f in fails) for m in must_fail)
    good = ok if not must_fail else (not ok and hit)
    print(f"== {tag}: selftest {'PASS' if ok else 'RED'}; expected "
          f"{'PASS' if not must_fail else 'RED naming ' + ' | '.join(must_fail)}"
          f" -> {'OK' if good else 'UNEXPECTED'}")
    for ln in fails + summ:
        print(ln)
    return good


def _set(d, k, v):
    d[k] = v


results = [
    run("control (no mutation)", lambda: None, []),
    run("m1 build_042_bm1 BM row deleted",
        lambda: T.pop(0x9B588E78), [MISS, PIN]),
    run("m2 266e3ae7 (R2) BM row deleted",
        lambda: T.pop(0x266E3AE7), [MISS, AGREE, PIN]),
    run("m3 e3c2ff1e BM -> 0xDEADC0DE",
        lambda: _set(T, 0xE3C2FF1E, HW.SEQ_CSR_UNMAPPED), [AGREE, PIN]),
    run("m4 build_041 BM -> 0x12345678",
        lambda: _set(T, 0xC973C18A, 0x12345678), [VAL, PIN]),
    run("m5 new SEQ_VERSIONS row 0x11111111 (caps {R1}) without a BM row",
        lambda: _set(V, 0x11111111, (HW.SHAPE_ISA_9B, "sr17ff test row",
                                      HW.seq_caps_word({"R1"}))),
        [MISS, AGREE]),
]
print(f"SR17FF_BM_ROWS_RED: {sum(results)}/{len(results)} as expected -> "
      f"{'PASS' if all(results) else 'FAIL'}")
sys.exit(0 if all(results) else 1)
