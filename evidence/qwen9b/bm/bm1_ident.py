#!/usr/bin/env python3
"""bm1_ident.py — BM1-T4: the USAGE §1 identity check, READ-ONLY (raw os.pread
of the AXI-Lite BAR; no write, no DMA).  Prints MAGIC/VERSION/CALIB/LAYER/SEQ/
TOPK IDENTs, the B16 BM_IDENT at SEQ 0x100 (BAR 0x6100; docs/SEQ_ISA.md B16)
and (Task SR7) SEQ_CAPS at SEQ 0x64 (BAR 0x6064; docs/SEQ_ISA.md B17.0), raw
and decoded by sw/hwmap.seq_caps_set — the one definition.

    python3 evidence/qwen9b/bm/bm1_ident.py --want-version c973c18a
    python3 evidence/qwen9b/bm/bm1_ident.py --want-version <R1 hash> --want-caps R1

Exit 0 only if MAGIC=0xfab1e001, VERSION=--want-version, CALIB=0xf, the
BM_IDENT matches hwmap.SEQ_BM_IDENT_BY_VERSION (0xfab1b301 for 9b588e78 and
e3c2ff1e, 0xdeadc0de otherwise) and the
DECODED SEQ_CAPS set equals --want-caps (default "none": every pre-round
bitstream reads 0xDEADC0DE there, the empty set).  Fail-closed: a word
without the SEQ_CAPS magic decodes as "none"; a set bit under the magic that
names no capability is a FAIL, never guessed at; an R1 bitstream read
without --want-caps R1 FAILs.  Refuses to open the device when
/dev/xdma0_user is absent.  judge() is the pure part (the SR7 TDD drives it
with scripted registers, evidence/qwen9b/sr/sr7_host_tdd.py).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "sw"))
import hwmap as HW  # noqa: E402  (pure Python: json/os only)

# SR7 fix round 1 (I-1): the expected BM_IDENT per VERSION is
# hwmap.SEQ_BM_IDENT_BY_VERSION (one definition); a VERSION outside it is a
# pre-BM1 bitstream and reads the unmapped value.
WANT_BM = HW.SEQ_BM_IDENT_BY_VERSION
# BAR offsets read, in print order.  SEQ_CAPS = SEQ 0x64 = HW.S_SEQ_CAPS.
REGS = {"MAGIC": 0x00, "VERSION": 0x04, "CALIB": 0x0C,
        "LAYER_IDENT": 0x5024, "SEQ_IDENT": 0x6028, "TOPK_IDENT": 0x5048,
        "BM_IDENT": 0x6100, "SEQ_CAPS": HW.S_SEQ_CAPS}


def caps_text(caps):
    return ",".join(sorted(caps)) if caps else "none"


def judge(r, want_version, want_caps):
    """r: {name: raw word} for every REGS name -> (report lines, ok)."""
    want = {"MAGIC": 0xFAB1E001, "VERSION": want_version, "CALIB": 0xF,
            "LAYER_IDENT": 0xFAB1E5A0, "SEQ_IDENT": 0xFAB1E5E0,
            "TOPK_IDENT": 0xFAB1704B,
            "BM_IDENT": WANT_BM.get(want_version, HW.SEQ_CSR_UNMAPPED)}
    lines, ok = [], True
    for k, v in r.items():
        if k == "SEQ_CAPS":
            continue
        good = (v == want[k])
        ok &= good
        lines.append(f"  {k:<12} {v:#010x}  want {want[k]:#010x}  "
                     f"{'OK' if good else 'MISMATCH'}")
    w = r["SEQ_CAPS"]
    want_caps = HW.seq_caps_check(want_caps)
    try:
        got = HW.seq_caps_set(w)
        dec, good = caps_text(got), (got == want_caps)
    except ValueError as e:          # the magic with an unknown bit
        dec, good = f"UNKNOWN ({e})", False
    ok &= good
    lines.append(f"  {'SEQ_CAPS':<12} {w:#010x}  decoded {{{dec}}}  want "
                 f"{{{caps_text(want_caps)}}}  {'OK' if good else 'MISMATCH'}")
    lines.append("IDENT: " + ("PASS" if ok else "FAIL"))
    return lines, ok


def parse_caps(s):
    s = s.strip()
    if s.lower() in ("", "none"):
        return frozenset()
    return HW.seq_caps_check(x.strip() for x in s.split(","))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", default="/dev/xdma0_user")
    ap.add_argument("--want-version", required=True, type=lambda s: int(s, 16))
    ap.add_argument("--want-caps", default="none", type=parse_caps,
                    help="expected decoded SEQ_CAPS set: 'none' (default; "
                         "every pre-round bitstream) or e.g. 'R1'")
    a = ap.parse_args()
    if not os.path.exists(a.dev):
        print(f"REFUSING: {a.dev} does not exist")
        return 2
    f = os.open(a.dev, os.O_RDWR)
    rd = lambda x: int.from_bytes(os.pread(f, 4, x), "little")  # noqa: E731
    r = {k: rd(off) for k, off in REGS.items()}
    os.close(f)
    lines, ok = judge(r, a.want_version, a.want_caps)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
