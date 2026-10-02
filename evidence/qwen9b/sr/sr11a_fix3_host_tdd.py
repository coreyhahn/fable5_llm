#!/usr/bin/env python3
"""sr11a_fix3_host_tdd.py — SR11a fix round 3 (round-2 re-review I1, I2).

    FABLE5_MODEL=9b /home/cah/.venv/bin/python \
        evidence/qwen9b/sr/sr11a_fix3_host_tdd.py

BOARD-FREE, on SR6's mock SEQ window (evidence/qwen9b/sr/sr6_host_tdd.py
make_dev / run_seq: the REAL seq_run.Dev identity gate over a scripted CSR
map, every write / DMA / upload a tripwire).  "LOADS" = reached the upload
tripwire; "REFUSED" = exited before any DMA.

Cases (.superpowers/sdd/2026-09-27-seq-rtl/task-SR11a-fix3-brief.md):
  (A) I1 — build_042_bm1 (VERSION 0x9B588E78; SEQ_CAPS 0xDEADC0DE, BM_IDENT
      0xFAB1B301), named with --expect-version 9b588e78, is ADMITTED through
      seq_run's identity + SHAPE-layout path (a 9B r0 fixture LOADS);
  (B) I1 — chat_seq's open_board re-key admits it too (open_board on a stub
      session: the device's layout isa=2 reaches admit_caps);
  (C) I2 — seq_run compares the artifact's DECLARED meta["shape_isa"] with
      the device's layout, before any DMA: a 9B artifact (shape_isa 2) named
      at build_035 (isa=1) is REFUSED naming both layouts; an isa=1-declared
      artifact at build_041 is REFUSED; a 9B artifact at build_041 and at
      build_044_r1_incr LOADS; the W8 artifact with NO key at build_035
      LOADS (round 2's (a));
  (D) I1 — every seq_run.SEQ_VERSIONS key has a hwmap.SHAPE_ISA_BY_VERSION
      row and the two layouts agree (the assertion seq_run --selftest gains).
"""
import json
import os
import shutil
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sr6_host_tdd as H6                                      # noqa: E402
from sr6_host_tdd import SR, SF, HW                            # noqa: E402

W5 = os.path.join(H6.ROOT, "tb", "scripts", "w5", "model_w8_2b_s1.e")
V035, V041, V042, V044 = 0x54443B9F, 0xC973C18A, 0x9B588E78, 0xE3C2FF1E
W_OLD = HW.SEQ_CSR_UNMAPPED
W_R1 = HW.seq_caps_word({"R1"})
RESULTS = []


def check(case, name, cond, detail=""):
    RESULTS.append((case, bool(cond)))
    print(f"  [{case}] {'PASS' if cond else 'FAIL'} {name}"
          + (f"  -- {detail}" if detail else ""))


def declared_fixture(d, isa):
    """SR6's r0 synthetic artifact with meta["shape_isa"] = isa."""
    p, _ = H6.make_fixture(d)
    meta = json.load(open(p + ".seq.json"))
    meta["shape_isa"] = isa
    json.dump(meta, open(p + ".seq.json", "w"), indent=1)
    return p


def seq_cases(tmp, ltmp):
    print("=== seq_run on mock SEQ windows")
    D035 = H6.make_dev(W_OLD, version=V035)
    D041 = H6.make_dev(W_OLD, version=V041)
    D044 = H6.make_dev(W_R1, version=V044)
    D042 = H6.make_dev(W_OLD, version=V042,
                       extra_regs={SR.S_BM_IDENT: SR.SEQ_BM_IDENT})
    p9 = declared_fixture(os.path.join(tmp, "d9"), HW.SHAPE_ISA_9B)
    p1 = declared_fixture(os.path.join(tmp, "d1"), HW.SHAPE_ISA_PRE_G3)

    # (A) build_042_bm1 admitted
    r = H6.run_seq(["--prefix", p9, "--expect-version", "9b588e78"], D042,
                   ltmp, "A")
    H6.say("(A) 9B at build_042_bm1", r)
    check("A", "build_042_bm1 (9b588e78) named: a 9B artifact LOADS through "
               "the identity + SHAPE-layout path", H6.loaded(r), r[0][:200])

    # (C) declared layout vs the device's
    r = H6.run_seq(["--prefix", p9, "--expect-version", "54443b9f"], D035,
                   ltmp, "C1")
    H6.say("(C) 9B-declared at build_035", r)
    m = r[0] + "\n" + r[2]
    check("C", "a 9B artifact (declared shape_isa 2) at build_035 (isa=1) is "
               "REFUSED before any DMA, naming both layouts",
          H6.refused_before_dma(r) and "isa=2" in m and "isa=1" in m
          and "declare" in m, r[0][:220])
    r = H6.run_seq(["--prefix", p1], D041, ltmp, "C2")
    H6.say("(C) isa1-declared at build_041", r)
    check("C", "an isa=1-declared artifact at build_041 (isa=2) is REFUSED",
          H6.refused_before_dma(r) and "declare" in (r[0] + r[2]),
          r[0][:220])
    r = H6.run_seq(["--prefix", p9], D041, ltmp, "C3")
    check("C", "a 9B artifact at build_041 LOADS", H6.loaded(r), r[0][:200])
    r = H6.run_seq(["--prefix", p9, "--expect-version", "e3c2ff1e"], D044,
                   ltmp, "C4")
    check("C", "a 9B artifact at build_044_r1_incr LOADS", H6.loaded(r),
          r[0][:200])
    r = H6.run_seq(["--prefix", W5, "--four-chan", "--expect-version",
                    "54443b9f"], D035, ltmp, "C5")
    check("C", "the W8 artifact with NO shape_isa key LOADS at build_035 "
               "(round 2's (a))", H6.loaded(r), r[0][:200])


def chat_case():
    print("=== chat_seq open_board re-key at build_042_bm1 (stub session)")
    import chat_seq as CS
    D042 = H6.make_dev(W_OLD, version=V042, expect=V042,
                       extra_regs={SR.S_BM_IDENT: SR.SEQ_BM_IDENT})
    got = {}

    class _Args(object):
        dev, chan = "/dev/xdma0", 0

    class _Stub(object):
        args = _Args()
        shape_isa = HW.SHAPE_ISA_9B

        def log(self, *a, **k):
            pass

        def admit_caps(self, caps, word=None):
            got["caps"], got["shape"] = caps, self.shape_isa

    saved = SR.Dev
    SR.Dev = D042
    try:
        s = _Stub()
        try:
            CS.ChatSession.open_board(s)
            o = "ok"
        except Exception as e:                               # noqa: BLE001
            o = f"{type(e).__name__}: {e}"
    finally:
        SR.Dev = saved
    check("B", "chat_seq open_board ADMITS build_042_bm1: the device's "
               "layout isa=2 reaches admit_caps",
          o == "ok" and got.get("shape") == HW.SHAPE_ISA_9B, f"{o} {got}")


def table_case():
    print("=== the two version tables agree")
    bad = []
    for v, row in SR.SEQ_VERSIONS.items():
        h = HW.SHAPE_ISA_BY_VERSION.get(v)
        if h is None or h != row[0]:
            bad.append(f"{v:#010x}: SEQ_VERSIONS isa={row[0]} hwmap={h}")
    check("D", "every SEQ_VERSIONS key has a hwmap.SHAPE_ISA_BY_VERSION row "
               "with the same layout", not bad, "; ".join(bad) or "all agree")


def main():
    t0 = time.monotonic()
    print(f"SR11a fix 3 host TDD — FABLE5_MODEL="
          f"{os.environ.get('FABLE5_MODEL')}")
    tmp = tempfile.mkdtemp(prefix="sr11af3_fx_")
    ltmp = tempfile.mkdtemp(prefix="sr11af3_lock_")
    try:
        for fn, a in ((seq_cases, (tmp, ltmp)), (chat_case, ()),
                      (table_case, ())):
            try:
                fn(*a)
            except Exception as e:                           # noqa: BLE001
                traceback.print_exc()
                check(fn.__name__, "block ran to the end", False, repr(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(ltmp, ignore_errors=True)
    by = {}
    for c, ok in RESULTS:
        by.setdefault(c, []).append(ok)
    print("per case: " + "  ".join(f"({c}) {sum(v)}/{len(v)}"
                                   for c, v in by.items()))
    npass = sum(ok for _c, ok in RESULTS)
    print(f"SR11A_FIX3_HOST_TDD: {npass} passed, {len(RESULTS) - npass} "
          f"failed ({time.monotonic() - t0:.0f} s) -> "
          + ("PASS" if npass == len(RESULTS) else "FAIL"))
    return npass == len(RESULTS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
