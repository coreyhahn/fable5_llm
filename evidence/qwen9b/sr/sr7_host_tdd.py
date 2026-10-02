#!/usr/bin/env python3
"""sr7_host_tdd.py — Task SR7's host step: the VERSION row carries the
EXPECTED SEQ_CAPS word, and bm1_ident reads SEQ_CAPS.

    /home/cah/.venv/bin/python evidence/qwen9b/sr/sr7_host_tdd.py [--r1 <hash>]

BOARD-FREE.  Every device read is a MOCK: the REAL sw/seq_run.Dev._gate runs
over a scripted CSR map (object.__new__(Dev) + a dict rd, 0xDEADC0DE =
HW.SEQ_CSR_UNMAPPED outside it, the pattern of seq_run's own BM1-T4prep
selftest), and evidence/qwen9b/bm/bm1_ident.py's judge() is fed a scripted
register dict.  No device is opened.

The two SEQ_CAPS words come from sw/hwmap.py (the ONE definition, B17.0):
HW.seq_caps_word({"R1"}) (= 0xFAB1CA01) and HW.SEQ_CSR_UNMAPPED
(= 0xDEADC0DE, what every pre-round bitstream reads at SEQ 0x64).

Cases (controller addenda to the SR7 brief):
  (a) every SEQ_VERSIONS row is (shape_isa, what, expected SEQ_CAPS word);
      build_041 / build_042 expect 0xDEADC0DE
  (b) gate: shipped board reading 0xDEADC0DE at 0x64 -> SEQ READY
  (c) gate: shipped VERSION but SEQ_CAPS reads the R1 word -> REFUSED,
      the reason names SEQ_CAPS and both words (a mismatch refuses like
      VERSION does: before any DMA, seq_ok False)
  (d) gate, a scripted R1 row (the table patched for the test only):
      R1 VERSION + R1 word -> READY; R1 VERSION + 0xDEADC0DE -> REFUSED;
      R1 VERSION + an unknown capability bit -> REFUSED
  (e) the gate records the raw SEQ_CAPS word in dev.ident
  (f) parse_expect_version's unknown-hash message still lists the rows
  (g) bm1_ident: judge() reports SEQ_CAPS raw + decoded; 0xDEADC0DE ->
      "none" and PASS with the default --want-caps none; the R1 word with
      --want-caps none -> FAIL (fail-closed); with --want-caps R1 -> PASS;
      an unknown magic decodes as "none"; an unknown capability bit under
      the magic -> FAIL, never guessed
  (h) bm1_ident reads BAR 0x6064 (SEQ 0x64) in its register list
  (j) fix round 1, I-1: the expected BM_IDENT comes from ONE table,
      hwmap.SEQ_BM_IDENT_BY_VERSION (041 -> 0xDEADC0DE, 042 and e3c2ff1e ->
      the BM1 magic, which equals seq_run.SEQ_BM_IDENT); an R1 board with
      its BM1 block and the R1 word PASSES bm1_ident
With --r1 <hash> (only once the R1 bitstream is signed off):
  (i) the R1 row exists, is admitted only when named (not the default),
      decodes SHAPE_ISA_9B, expects HW.seq_caps_word({"R1"}); and
      hwmap.SHAPE_ISA_BY_VERSION has the same hash -> SHAPE_ISA_9B
"""
import argparse
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "sw"))
import hwmap as HW          # noqa: E402
import seq_run as SR        # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "bm1_ident", os.path.join(ROOT, "evidence/qwen9b/bm/bm1_ident.py"))
BI = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BI)

R1W = HW.seq_caps_word({"R1"})
UNM = HW.SEQ_CSR_UNMAPPED
V041, VBM1 = 0xC973C18A, 0x9B588E78
NP = NF = 0


def check(name, cond, detail=""):
    global NP, NF
    if cond:
        NP += 1
        print(f"  PASS {name}")
    else:
        NF += 1
        print(f"  FAIL {name}  {detail}")


def gate(board_ver, expect, caps_word):
    regs = {SR.R_MAGIC: SR.MAGIC, SR.R_VERSION: board_ver,
            SR.R_CALIB: SR.CALIB_ALL, SR.L_IDENT: SR.LAYER_IDENT,
            SR.S_IDENT: SR.SEQ_IDENT, HW.S_SEQ_CAPS: caps_word}
    regs.update({SR.mv_base(c) + SR.R_IDENT: SR.MV_IDENT0 + c
                 for c in range(4)})
    d = object.__new__(SR.Dev)
    d.rd = lambda a: regs.get(a, UNM)
    return d._gate(expect, True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--r1", type=lambda s: int(s, 16), default=None)
    a = ap.parse_args()
    print(f"R1 word {R1W:#010x}  unmapped {UNM:#010x}")

    print("(a) SEQ_VERSIONS rows carry the expected SEQ_CAPS word")
    rows = SR.SEQ_VERSIONS
    check("every row is (shape_isa, what, caps_word)",
          all(isinstance(r, tuple) and len(r) == 3 and isinstance(r[2], int)
              for r in rows.values()), repr(rows))
    check("build_041 expects 0xDEADC0DE",
          len(rows[V041]) == 3 and rows[V041][2] == UNM, repr(rows[V041]))
    check("build_042_bm1 expects 0xDEADC0DE",
          len(rows[VBM1]) == 3 and rows[VBM1][2] == UNM, repr(rows[VBM1]))

    print("(b)/(c) the gate compares SEQ_CAPS against the row")
    try:
        _i, ok, why = gate(V041, V041, UNM)
        check("(b) shipped board + 0xDEADC0DE -> READY", ok, why)
        _i, ok, why = gate(V041, V041, R1W)
        check("(c) shipped VERSION + R1 word -> REFUSED",
              not ok and "SEQ_CAPS" in why and "0xfab1ca01" in why
              and "0xdeadc0de" in why, why)
        _i, ok, why = gate(VBM1, VBM1, R1W)
        check("(c) BM1 VERSION + R1 word -> REFUSED", not ok, why)
    except Exception as e:
        check("(b)/(c) run", False, repr(e))

    print("(d) a scripted R1 row (table patched for this test only)")
    FAKE = 0x0BADF00D
    saved = dict(SR.SEQ_VERSIONS)
    try:
        SR.SEQ_VERSIONS[FAKE] = (HW.SHAPE_ISA_9B, "scripted R1 row", R1W)
        _i, ok, why = gate(FAKE, FAKE, R1W)
        check("(d) R1 VERSION + R1 word -> READY", ok, why)
        _i, ok, why = gate(FAKE, FAKE, UNM)
        check("(d) R1 VERSION + 0xDEADC0DE -> REFUSED (caps missing)",
              not ok and "SEQ_CAPS" in why, why)
        _i, ok, why = gate(FAKE, FAKE, R1W | 0x08)
        check("(d) R1 VERSION + an unknown capability bit -> REFUSED",
              not ok and "SEQ_CAPS" in why, why)
        ident, ok, why = gate(FAKE, FAKE, R1W)
        check("(e) the gate records the raw SEQ_CAPS word",
              ident.get("seq_caps") == R1W, repr(ident))
    except Exception as e:
        check("(d)/(e) run", False, repr(e))
    finally:
        SR.SEQ_VERSIONS.clear()
        SR.SEQ_VERSIONS.update(saved)

    print("(f) parse_expect_version's refusal lists the rows")
    try:
        SR.parse_expect_version("0badf00e")
        msg = ""
    except ValueError as e:
        msg = str(e)
    except Exception as e:
        msg = "CRASH " + repr(e)
    check("(f) unknown hash -> ValueError listing c973c18a and 9b588e78",
          "0xc973c18a" in msg and "0x9b588e78" in msg, msg[:160])

    print("(g)/(h) bm1_ident reads and judges SEQ_CAPS")
    base = {"MAGIC": 0xFAB1E001, "VERSION": V041, "CALIB": 0xF,
            "LAYER_IDENT": 0xFAB1E5A0, "SEQ_IDENT": 0xFAB1E5E0,
            "TOPK_IDENT": 0xFAB1704B, "BM_IDENT": UNM}
    judge = getattr(BI, "judge", None)
    check("(g) bm1_ident has judge(regs, want_version, want_caps)",
          callable(judge))
    check("(h) bm1_ident reads BAR 0x6064",
          getattr(BI, "REGS", {}).get("SEQ_CAPS") == 0x6064,
          repr(getattr(BI, "REGS", None)))
    if callable(judge):
        try:
            lines, ok = judge(dict(base, SEQ_CAPS=UNM), V041, frozenset())
            txt = "\n".join(lines)
            check("(g) 0xDEADC0DE + want none -> PASS, decoded 'none'",
                  ok and "SEQ_CAPS" in txt and "0xdeadc0de" in txt
                  and "none" in txt, txt)
            lines, ok = judge(dict(base, SEQ_CAPS=R1W), V041, frozenset())
            check("(g) R1 word + want none -> FAIL (fail-closed)", not ok,
                  "\n".join(lines))
            lines, ok = judge(dict(base, SEQ_CAPS=R1W), V041,
                              frozenset({"R1"}))
            txt = "\n".join(lines)
            check("(g) R1 word + want R1 -> PASS, decoded R1",
                  ok and "0xfab1ca01" in txt and "R1" in txt, txt)
            lines, ok = judge(dict(base, SEQ_CAPS=UNM), V041,
                              frozenset({"R1"}))
            check("(g) 0xDEADC0DE + want R1 -> FAIL", not ok,
                  "\n".join(lines))
            lines, ok = judge(dict(base, SEQ_CAPS=0x12345601), V041,
                              frozenset())
            txt = "\n".join(lines)
            check("(g) an unknown magic decodes as 'none'",
                  ok and "none" in txt, txt)
            lines, ok = judge(dict(base, SEQ_CAPS=R1W | 0x08), V041,
                              frozenset({"R1"}))
            txt = "\n".join(lines)
            check("(g) an unknown capability bit -> FAIL, named",
                  not ok and "bit 3" in txt, txt)
        except Exception as e:
            check("(g) run", False, repr(e))

    if a.r1 is not None:
        print(f"(i) the R1 row {a.r1:#010x}")
        row = SR.SEQ_VERSIONS.get(a.r1)
        check("(i) the R1 row exists", row is not None)
        if row is not None:
            check("(i) decodes SHAPE_ISA_9B", row[0] == HW.SHAPE_ISA_9B)
            check("(i) expects the R1 word", row[2] == R1W, repr(row))
            check("(i) admitted only when named (not the default)",
                  SR.EXPECTED_SEQ_VERSION != a.r1
                  and "admitted only when named" in row[1], row[1])
            check("(i) parse_expect_version takes the bare hash",
                  SR.parse_expect_version(f"{a.r1:08x}") == a.r1)
            _i, ok, why = gate(a.r1, a.r1, R1W)
            check("(i) gate: R1 board + R1 word -> READY", ok, why)
            _i, ok, why = gate(a.r1, a.r1, UNM)
            check("(i) gate: R1 VERSION + 0xDEADC0DE -> REFUSED", not ok, why)
            _i, ok, why = gate(a.r1, V041, R1W)
            check("(i) gate: R1 board + default expect -> REFUSED", not ok,
                  why)
        check("(i) hwmap.SHAPE_ISA_BY_VERSION maps it to SHAPE_ISA_9B",
              HW.SHAPE_ISA_BY_VERSION.get(a.r1) == HW.SHAPE_ISA_9B)

    # SR7 fix round 1, I-1: the expected BM_IDENT is keyed by VERSION from
    # ONE table in sw/hwmap.py; the R1 netlist carries the BM1 block.
    print("(j) BM_IDENT expected per VERSION (fix round 1, I-1)")
    tab = getattr(HW, "SEQ_BM_IDENT_BY_VERSION", None)
    check("(j) hwmap.SEQ_BM_IDENT_BY_VERSION exists", isinstance(tab, dict))
    if isinstance(tab, dict):
        check("(j) build_041 -> 0xDEADC0DE, build_042 / e3c2ff1e -> the "
              "BM1 magic", tab.get(V041) == UNM
              and tab.get(VBM1) == SR.SEQ_BM_IDENT
              and tab.get(0xE3C2FF1E) == SR.SEQ_BM_IDENT, repr(tab))
        check("(j) every SEQ_VERSIONS row has a BM_IDENT expectation",
              all(v in tab for v in SR.SEQ_VERSIONS), repr(sorted(tab)))
    check("(j) hwmap's BM1 magic == seq_run.SEQ_BM_IDENT",
          getattr(HW, "SEQ_BM_IDENT", None) == SR.SEQ_BM_IDENT)
    if callable(judge):
        r1 = dict(base, VERSION=0xE3C2FF1E, BM_IDENT=SR.SEQ_BM_IDENT,
                  SEQ_CAPS=R1W)
        lines, ok = judge(r1, 0xE3C2FF1E, frozenset({"R1"}))
        check("(j) R1 board (BM1 block, R1 word), --want-version e3c2ff1e "
              "--want-caps R1 -> PASS", ok, "\n".join(lines))
        lines, ok = judge(dict(r1, BM_IDENT=UNM), 0xE3C2FF1E,
                          frozenset({"R1"}))
        check("(j) R1 VERSION without the BM1 block -> FAIL", not ok,
              "\n".join(lines))
        lines, ok = judge(dict(base, VERSION=VBM1, BM_IDENT=SR.SEQ_BM_IDENT,
                               SEQ_CAPS=UNM), VBM1, frozenset())
        check("(j) build_042 (BM1, no caps) -> PASS", ok, "\n".join(lines))
        lines, ok = judge(dict(base, SEQ_CAPS=UNM), V041, frozenset())
        check("(j) build_041 (0xDEADC0DE at 0x100) -> PASS", ok,
              "\n".join(lines))

    print(f"sr7_host_tdd: {NP} passed, {NF} failed")
    return 0 if NF == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
