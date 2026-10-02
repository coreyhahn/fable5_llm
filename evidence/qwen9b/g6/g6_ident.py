#!/usr/bin/env python3
"""g6_ident.py — read the resident bitstream's identity CSRs, and NOTHING else.

    python3 evidence/qwen9b/g6/g6_ident.py                 # just look
    python3 evidence/qwen9b/g6/g6_ident.py --require-calib \
        --expect-version 0xc973c18a                        # the identity gate

WHY THIS FILE EXISTS.  `evidence/qwen9b/g5/G5D_TIMING.md` §11 records the
resident bitstream as build_035 (`VERSION 54443b9f`) but flags the
attribution as inherited from `NEXT_SESSION.md`, not read back; the plan's
Step 1 says the readback must be TEED this time, because R-b's attribution
of the previously resident bitstream is `UNCONFIRMED` on record precisely
because nobody teed one.  So: a reader that takes the shared board lock,
opens ONLY `/dev/xdma0_user`, and does ZERO DMA — safe to run before a
reprogram, on an unknown bitstream, without disturbing anyone's resident
weights.

BOARD SAFETY.  Never programs the FPGA, never touches flash, never runs
sudo, never calls pcie_helper.sh, never opens h2c/c2h.  The 0x6000 SEQ
window is read ONLY when VERSION is one this campaign knows carries a
sequencer; on any other VERSION it is not touched at all.
"""
import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_SW = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "sw"))
if _SW not in sys.path:
    sys.path.insert(0, _SW)

import board_lock as BL                                        # noqa: E402
import hwmap as HW                                             # noqa: E402

# VERSION words this campaign knows carry a seq_unit at 0x6000.  Reading the
# SEQ IDENT on anything else would be touching a window that may not exist.
SEQ_BEARING = {
    0x33D720E5: "build_033",
    0x4F908DF2: "build_034 (R-b)",
    0x54443B9F: "build_035_fp2a_exc_po (R-d, the 2B W8 design)",
    0xC973C18A: "build_041_ckr2_AltSpreadLogic_high (Task 14-B, the 9B design)",
}


def read_ident(dev="/dev/xdma0"):
    fd = os.open(dev + "_user", os.O_RDONLY)
    try:
        def rd(a):
            return int.from_bytes(os.pread(fd, 4, a), "little")
        d = {
            "magic":   rd(HW.R_MAGIC),
            "version": rd(HW.R_VERSION),
            "scratch": rd(HW.R_SCRATCH),
            "calib":   rd(HW.R_CALIB),
            "uptime_lo": rd(HW.R_UPTIME_LO),
            "uptime_hi": rd(HW.R_UPTIME_HI),
            "layer_ident": rd(HW.L_IDENT),
            "mv_ident": [rd(HW.mv_base(c) + HW.R_IDENT) for c in range(4)],
        }
        d["uptime_cyc"] = (d["uptime_hi"] << 32) | d["uptime_lo"]
        d["uptime_s"] = d["uptime_cyc"] / HW.ACLK_HZ
        if d["version"] in SEQ_BEARING:
            d["seq_ident"] = rd(HW.S_IDENT)
            d["seq_note"] = SEQ_BEARING[d["version"]]
        else:
            d["seq_ident"] = None
            d["seq_note"] = ("UNKNOWN VERSION — the 0x6000 window was NOT "
                             "touched")
        return d
    finally:
        os.close(fd)


def report(d, log=print):
    log(f"  MAGIC        {d['magic']:#010x} "
        f"({'OK' if d['magic'] == HW.MAGIC else 'WANT %#010x' % HW.MAGIC})")
    log(f"  VERSION      {d['version']:#010x}   {d['seq_note']}")
    log(f"  SCRATCH      {d['scratch']:#010x}")
    log(f"  CALIB        {d['calib']:#x}        "
        f"({'ALL FOUR CHANNELS CALIBRATED' if d['calib'] == HW.CALIB_ALL else 'NOT 0xF'})")
    log(f"  UPTIME       {d['uptime_cyc']} cycles = {d['uptime_s']:.3f} s "
        f"@ {HW.ACLK_HZ / 1e6:.0f} MHz  (lo {d['uptime_lo']:#010x} hi "
        f"{d['uptime_hi']:#010x})")
    log(f"  layer IDENT  {d['layer_ident']:#010x} "
        f"({'OK' if d['layer_ident'] == HW.LAYER_IDENT else 'WANT %#010x' % HW.LAYER_IDENT})")
    for c, v in enumerate(d["mv_ident"]):
        w = HW.MV_IDENT0 + c
        log(f"  matvec{c} IDENT {v:#010x} ({'OK' if v == w else 'WANT %#010x' % w})")
    if d["seq_ident"] is not None:
        log(f"  SEQ IDENT    {d['seq_ident']:#010x} "
            f"({'OK' if d['seq_ident'] == HW.SEQ_IDENT else 'WANT %#010x' % HW.SEQ_IDENT})")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--expect-version", default=None,
                    help="fail unless VERSION reads this (hex ok)")
    ap.add_argument("--require-calib", action="store_true",
                    help="fail unless CALIB reads 0xF")
    ap.add_argument("--wait-calib", type=float, default=0.0,
                    help="poll up to N seconds for CALIB to reach 0xF")
    ap.add_argument("--json", default=None)
    BL.add_lock_args(ap)
    a = ap.parse_args(argv)

    try:
        lk = BL.from_args(a, tool="g6_ident.py").acquire()
    except BL.BoardLockError as e:
        print("*** %s" % e)
        return 4

    print("--- resident bitstream identity (AXI-Lite reads only; no DMA)")
    d = read_ident(a.dev)
    t0 = time.monotonic()
    while (d["calib"] != HW.CALIB_ALL
           and time.monotonic() - t0 < a.wait_calib):
        time.sleep(0.5)
        d = read_ident(a.dev)
    if a.wait_calib:
        print(f"  CALIB poll   {time.monotonic() - t0:.1f} s of "
              f"{a.wait_calib:.0f} s budget")
    report(d)

    bad = []
    if d["magic"] != HW.MAGIC:
        bad.append(f"MAGIC {d['magic']:#010x} != {HW.MAGIC:#010x}")
    if a.expect_version is not None:
        want = int(a.expect_version, 0)
        if d["version"] != want:
            bad.append(f"VERSION {d['version']:#010x} != expected "
                       f"{want:#010x}")
        else:
            print(f"  VERSION MATCHES the expected netlist word "
                  f"{want:#010x}")
    if a.require_calib and d["calib"] != HW.CALIB_ALL:
        bad.append(f"CALIB {d['calib']:#x} != {HW.CALIB_ALL:#x} — NO DMA IS "
                   f"PERMITTED (CLAUDE.md)")
    if a.json:
        with open(a.json, "w") as f:
            json.dump({k: v for k, v in d.items()}, f, indent=1, sort_keys=True)
        print(f"  json -> {a.json}")
    if bad:
        print("G6_IDENT: FAIL")
        for b in bad:
            print("  ! " + b)
        return 1
    print("G6_IDENT: OK")
    del lk
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
