#!/usr/bin/env python3
# O3 BOARD LOCK (2026-09-01): this script drives the board and does
# NOT take the shared lock (sw/board_lock.py) -- it predates the O3
# ruling and its logic is frozen R-d evidence, so it was not rewritten.
# It reads board CSRs directly.
# Take the lock around it by hand:
#     python3 sw/board_lock.py --tool <why> --exec -- <this script>
"""rd_identity.py — the CSR identity gate, READ-ONLY, before any DMA.

Every value below is printed to a tee'd log (R-b's gate was burned by a
VERSION readback that only ever existed in a session transcript).  Nothing
here writes a CSR and nothing here touches DDR: the rule is that DMA waits
for CALIB == 0xF, which this script is what proves.
"""
import os
import sys

EXPECT_VERSION = 0x54443B9F      # build_035_fp2a_exc_po
WANT = [
    ("MAGIC",   0x0000, 0xFAB1E001),
    ("VERSION", 0x0004, EXPECT_VERSION),
    ("CALIB",   0x000C, 0xF),
    ("LAYER  IDENT", 0x5024, 0xFAB1E5A0),
    ("SEQ    IDENT", 0x6028, 0xFAB1E5E0),
    ("TOPK   IDENT", 0x5048, 0xFAB1704B),
    # matvec_chan c is at 0x1000*(c+1); its IDENT is R_IDENT = +0x34 and
    # reads MV_IDENT0 + c (sw/hwmap.py:37).  (The first pass of this script
    # read +0x24 = R_XWIN by mistake and printed 0xdeadc0de four times —
    # hw_03a_identity_035_mvoffset_typo.log; the six gated CSRs above read
    # identically in both passes.)
    ("MV0    IDENT", 0x1034, 0xFAB1C4A0),
    ("MV1    IDENT", 0x2034, 0xFAB1C4A1),
    ("MV2    IDENT", 0x3034, 0xFAB1C4A2),
    ("MV3    IDENT", 0x4034, 0xFAB1C4A3),
]

f = os.open("/dev/xdma0_user", os.O_RDWR)


def rd(a):
    return int.from_bytes(os.pread(f, 4, a), "little")


bad = 0
for name, off, want in WANT:
    got = rd(off)
    if want is None:
        print(f"  {name:<12} {off:#06x} = {got:#010x}")
        continue
    ok = (got == want)
    bad += (not ok)
    print(f"  {name:<12} {off:#06x} = {got:#010x} "
          f"(want {want:#010x})  {'OK' if ok else '*** MISMATCH ***'}")

up_lo, up_hi = rd(0x10), rd(0x14)
print(f"  UPTIME       0x0010 = {up_lo:#010x} / 0x0014 = {up_hi:#010x}")
print(f"  SCRATCH      0x0008 = {rd(0x0008):#010x}")
# SEQ 0x60 EMBLOG2 — read-only here; seq_run programs it from the artifact.
print(f"  EMBLOG2      0x6060 = {rd(0x6060)} (reset 11 = 2048 B emb rows)")

print("IDENTITY_PASS" if bad == 0 else f"IDENTITY_FAIL ({bad} mismatched)")
sys.exit(1 if bad else 0)
