#!/usr/bin/env python3
"""sr14_ident_expect.py -- SR14 (the addendum's "re-run SR7's BM_IDENT/SEQ_CAPS
readback expectation"): the R2 netlist build_045_r2_incr (VERSION 0x266e3ae7)
must report SEQ_CAPS 0xFAB1CA03 ({R1, R2}) and BM_IDENT 0xFAB1B301.  Drives the
pure judge() of evidence/qwen9b/bm/bm1_ident.py (the documented pre-flight)
with SCRIPTED register words -- no device is opened -- for the expected R2
identity and four mutations of it, plus the R1 identity as a control that the
new hwmap row did not disturb.  Run on snoke through sr_run.sh.

Task R3-6 (a flag, not a copy): --want-version HEX / --want-caps LIST name
the expected identity (defaults 266e3ae7 / R1,R2: today's run, byte for
byte).  At --want-caps R1,R2,R3 (0xFAB1CA07) the mutations also cover the
R1+R2 word 0xFAB1CA03 and the R2 bitstream named as R3.  judge() takes the
BM_IDENT expectation from hwmap.SEQ_BM_IDENT_BY_VERSION, so a VERSION with no
row there (no R3 bitstream exists yet; its rows are R3-10's) needs the
caller to supply one -- evidence/qwen9b/sr/r3_host_tdd.py injects a mock
row and runs this file in-process."""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bm"))
import bm1_ident as BI  # noqa: E402
HW = BI.HW

R2V, R1V = 0x266E3AE7, 0xE3C2FF1E
ap = argparse.ArgumentParser()
ap.add_argument("--want-version", default="266e3ae7",
                type=lambda s: int(s, 16))
ap.add_argument("--want-caps", default="R1,R2")
A = ap.parse_args()
WV, WC = A.want_version, BI.parse_caps(A.want_caps)
L = sorted(WC)[-1] if WC else "none"          # "R2" / "R3": the level name
BASE = {"MAGIC": 0xFAB1E001, "VERSION": WV, "CALIB": 0xF,
        "LAYER_IDENT": 0xFAB1E5A0, "SEQ_IDENT": 0xFAB1E5E0,
        "TOPK_IDENT": 0xFAB1704B, "BM_IDENT": 0xFAB1B301,
        "SEQ_CAPS": HW.seq_caps_word(WC)}
npass = nfail = 0


def case(name, regs, want_version, want_caps, expect_ok):
    global npass, nfail
    lines, ok = BI.judge(dict(regs), want_version, BI.parse_caps(want_caps))
    good = (ok == expect_ok)
    npass += good
    nfail += (not good)
    print(f"{'PASS' if good else 'FAIL'}  {name}: judge -> "
          f"{'PASS' if ok else 'FAIL'} (want {'PASS' if expect_ok else 'FAIL'})")
    for ln in lines:
        print("      " + ln)


print(f"expected words: SEQ_CAPS {HW.seq_caps_word(WC):#010x}  "
      f"BM_IDENT {HW.SEQ_BM_IDENT_BY_VERSION.get(WV, 0):#010x}  "
      f"SHAPE isa {HW.shape_isa_for_version(WV)}")
case(f"{L} board, --want-version {WV:08x} --want-caps {A.want_caps}", BASE,
     WV, A.want_caps, True)
if "R3" in WC:
    case(f"{L} VERSION reporting the R1+R2 word 0xFAB1CA03",
         dict(BASE, SEQ_CAPS=HW.seq_caps_word({"R1", "R2"})), WV,
         A.want_caps, False)
case(f"{L} VERSION reporting the R1 word 0xFAB1CA01",
     dict(BASE, SEQ_CAPS=HW.seq_caps_word({"R1"})), WV, A.want_caps, False)
case(f"{L} VERSION reporting 0xDEADC0DE (a pre-round read)",
     dict(BASE, SEQ_CAPS=HW.SEQ_CSR_UNMAPPED), WV, A.want_caps, False)
case(f"{L} VERSION without the BM1 block (BM_IDENT 0xDEADC0DE)",
     dict(BASE, BM_IDENT=HW.SEQ_CSR_UNMAPPED), WV, A.want_caps, False)
if WV != R2V:
    case(f"the R2 bitstream (VERSION 266e3ae7) named as {L}",
         dict(BASE, VERSION=R2V, SEQ_CAPS=HW.seq_caps_word({"R1", "R2"})),
         WV, A.want_caps, False)
case(f"the R1 bitstream (VERSION e3c2ff1e) named as {L}",
     dict(BASE, VERSION=R1V, SEQ_CAPS=HW.seq_caps_word({"R1"})), WV,
     A.want_caps, False)
case(f"control: the R1 bitstream judged as R1 (unchanged by the {L} row)",
     dict(BASE, VERSION=R1V, SEQ_CAPS=HW.seq_caps_word({"R1"})), R1V,
     "R1", True)
print(f"SR14_IDENT_EXPECT: {npass} passed, {nfail} failed -> "
      f"{'PASS' if nfail == 0 else 'FAIL'}")
sys.exit(0 if nfail == 0 else 1)
