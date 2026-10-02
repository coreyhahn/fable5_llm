#!/usr/bin/env python3
"""sr8_ident.py — Task SR8: the R1 board session's identity check, READ-ONLY.

A copy of evidence/qwen9b/bm/bm1_ident.py (its REGS table and judge() are
imported, not re-typed) plus the SEQ_CAPS word checked EXACTLY: bm1_ident
judges the DECODED set; this also requires the raw SEQ 0x64 word to equal
the word the expected set implies — HW.seq_caps_word(caps) for a non-empty
set, HW.SEQ_CSR_UNMAPPED (0xDEADC0DE, the pre-round read-mux default) for
the empty set.  Both come from sw/hwmap.py (the one definition).

    python3 evidence/qwen9b/sr/sr8_ident.py --expect c973c18a            # build_041
    python3 evidence/qwen9b/sr/sr8_ident.py --expect e3c2ff1e --want-caps R1
    python3 evidence/qwen9b/sr/sr8_ident.py --selftest                   # boardless

Prints every register, then `IDENT: PASS` / `IDENT: FAIL`; exit 0 only on
PASS.  Raw os.pread of the AXI-Lite BAR: no write, no DMA, no SEQ window
drive, no lock needed (bm1_ident's convention).  Refuses when
/dev/xdma0_user is absent.
"""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "sw"))
sys.path.insert(0, os.path.join(_ROOT, "evidence", "qwen9b", "bm"))
import hwmap as HW          # noqa: E402
import bm1_ident as BI      # noqa: E402


def want_word(caps):
    return HW.seq_caps_word(caps) if caps else HW.SEQ_CSR_UNMAPPED


def judge(r, want_version, want_caps):
    lines, ok = BI.judge(r, want_version, want_caps)
    lines = [ln for ln in lines if not ln.startswith("IDENT:")]
    ww = want_word(HW.seq_caps_check(want_caps))
    good = (r["SEQ_CAPS"] == ww)
    ok = ok and good
    lines.append(f"  {'CAPS_WORD':<12} {r['SEQ_CAPS']:#010x}  want "
                 f"{ww:#010x}  {'OK' if good else 'MISMATCH'}")
    lines.append("IDENT: " + ("PASS" if ok else "FAIL"))
    return lines, ok


def selftest():
    n = bad = 0
    base = {"MAGIC": 0xFAB1E001, "CALIB": 0xF, "LAYER_IDENT": 0xFAB1E5A0,
            "SEQ_IDENT": 0xFAB1E5E0, "TOPK_IDENT": 0xFAB1704B}
    r1 = dict(base, VERSION=0xE3C2FF1E, BM_IDENT=0xFAB1B301,
              SEQ_CAPS=0xFAB1CA01)
    g41 = dict(base, VERSION=0xC973C18A, BM_IDENT=0xDEADC0DE,
               SEQ_CAPS=0xDEADC0DE)
    cases = [
        ("R1 as expected", r1, 0xE3C2FF1E, {"R1"}, True),
        ("build_041 as expected", g41, 0xC973C18A, set(), True),
        ("R1 read with no caps expected", r1, 0xE3C2FF1E, set(), False),
        ("R1 CALIB 0x7", dict(r1, CALIB=0x7), 0xE3C2FF1E, {"R1"}, False),
        ("R1 VERSION wrong", r1, 0xC973C18A, {"R1"}, False),
        ("R1 caps word R1+R2", dict(r1, SEQ_CAPS=0xFAB1CA03), 0xE3C2FF1E,
         {"R1"}, False),
        ("R1 caps word DEADC0DE", dict(r1, SEQ_CAPS=0xDEADC0DE), 0xE3C2FF1E,
         {"R1"}, False),
        ("R1 BM_IDENT absent", dict(r1, BM_IDENT=0xDEADC0DE), 0xE3C2FF1E,
         {"R1"}, False),
        ("041 caps word 0 (no magic: decodes empty, word differs)",
         dict(g41, SEQ_CAPS=0), 0xC973C18A, set(), False),
        ("R1 unknown cap bit", dict(r1, SEQ_CAPS=0xFAB1CA81), 0xE3C2FF1E,
         {"R1"}, False),
    ]
    for name, regs, v, caps, want in cases:
        r = {k: regs[k] for k in BI.REGS}
        _, ok = judge(r, v, frozenset(caps))
        n += 1
        res = "ok" if ok == want else "WRONG"
        bad += (ok != want)
        print(f"  [{n:2d}] {name}: judged {'PASS' if ok else 'FAIL'}, "
              f"want {'PASS' if want else 'FAIL'}  {res}")
    print(f"expected R1 word {HW.seq_caps_word({'R1'}):#010x}, "
          f"empty-set word {HW.SEQ_CSR_UNMAPPED:#010x}")
    print(f"SR8_IDENT_SELFTEST: {n - bad} passed, {bad} failed")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", default="/dev/xdma0_user")
    ap.add_argument("--expect", type=lambda s: int(s, 16))
    ap.add_argument("--want-caps", default="none", type=BI.parse_caps)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.expect is None:
        ap.error("--expect <8-hex VERSION> is required")
    if not os.path.exists(a.dev):
        print(f"REFUSING: {a.dev} does not exist")
        return 2
    f = os.open(a.dev, os.O_RDWR)   # as bm1_ident (pread only)
    rd = lambda x: int.from_bytes(os.pread(f, 4, x), "little")  # noqa: E731
    r = {k: rd(off) for k, off in BI.REGS.items()}
    os.close(f)
    print(f"--- expect VERSION {a.expect:#010x}, caps "
          f"{{{BI.caps_text(a.want_caps)}}}")
    lines, ok = judge(r, a.expect, a.want_caps)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
