#!/usr/bin/env python3
"""Stage-2 hardware test: streamed W4A8 matvec on all 4 DDR4 channels.

Per (seed, channel): generate fp weights/activations, quantize via
ref/w4a8_ref.py (THE reference), pack the DDR image, DMA it into the
channel, configure the channel's matvec CSR block, load x via XWIN,
doorbell, poll done, read back y32 results and compare bit-exact against
the reference. Reports sustained DDR4 read bandwidth from the on-chip
perf counters (ui_clk = 300.12 MHz).

Charter acceptance: 4 seeds x 2 runs x 4 channels, single programming.

Usage (snoke):  .venv/bin/python matvec_test.py --evidence ../evidence/stage2
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ref"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board_lock as BL                                         # noqa: E402
from w4a8_ref import quantize_weights, quantize_acts, matvec_y32, pack_ddr_rows
# device map / CSR offsets: single source of truth in hwmap.py
from hwmap import (                                             # noqa: E402
    UI_CLK_HZ, CH_STRIDE, W_BASE as W_LOCAL_BASE,
    R_MAGIC, R_VERSION, R_CALIB, MAGIC, CALIB_ALL,
    R_CTRL, R_STATUS, R_WBASE_LO, R_WBASE_HI, R_WBEATS, R_SHAPE,
    R_PERF_CYC_LO, R_PERF_CYC_HI, R_PERF_BEATS,
    R_XWIN, R_XPTR, R_RES_PTR, R_RES_DATA, R_IDENT,
    MV_IDENT0, MV_ST_DONE, MV_ST_ERR_RRESP, MV_ST_XOVFL, mv_base,
    shape_word, shape_isa_for_version, UnknownBitstream,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--seeds", type=lambda s: [int(x, 0) for x in s.split(",")],
                    default=[0xFA8001, 0xFA8002, 0xFA8003, 0xFA8004])
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--channels", type=lambda s: [int(x) for x in s.split(",")],
                    default=[0, 1, 2, 3])
    ap.add_argument("--N", type=int, default=4096)
    ap.add_argument("--K", type=int, default=3584)
    ap.add_argument("--evidence", default=None)
    BL.add_lock_args(ap)                        # O3: --lock / --no-lock
    args = ap.parse_args()

    # O3 (user ruling 2026-08-29): THE shared board lock, taken FIRST —
    # before any artifact is opened and long before the first device fd,
    # so a refusal is instant and this tool can no longer drive the board
    # out from under a live session.
    try:
        _lock = BL.from_args(args, tool="matvec_test.py").acquire()
    except BL.BoardLockError as e:
        print("*** %s" % e)
        raise SystemExit(4)


    user = os.open(f"{args.dev}_user", os.O_RDWR)
    h2c = os.open(f"{args.dev}_h2c_0", os.O_WRONLY)

    def rd(a): return int.from_bytes(os.pread(user, 4, a), "little")
    def wr(a, v): os.pwrite(user, int(v).to_bytes(4, "little"), a)

    log = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "git": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip(),
        "seeds": [hex(s) for s in args.seeds], "runs": args.runs,
        "channels": args.channels, "N": args.N, "K": args.K,
        "results": [], "pass": True,
    }

    # sanity: stage-1 CSR + channel idents
    magic, ver = rd(R_MAGIC), rd(R_VERSION)
    assert magic == MAGIC, "wrong design"
    assert rd(R_CALIB) == CALIB_ALL, "DDR not calibrated"
    # WHICH R_SHAPE LAYOUT THE RESIDENT BITSTREAM DECODES (G3.3), gated in
    # the SAME place as MAGIC/CALIB and BEFORE anything is packed.  This tool
    # used to hand-roll the SHAPE word; it now delegates to the ONE packer
    # (sw/hwmap.shape_word) with the ISA the VERSION CSR names, and an image
    # this checkout has no layout for REFUSES rather than guessing.
    try:
        shape_isa = shape_isa_for_version(ver)
    except UnknownBitstream as ex:
        raise SystemExit("REFUSING TO TOUCH THE BOARD — " + str(ex))
    print(f"MAGIC={magic:08x} VERSION={ver:08x} CALIB={rd(R_CALIB):x} "
          f"SHAPE_ISA={shape_isa}")
    report["version_csr"] = f"{ver:#010x}"
    report["shape_isa"] = shape_isa
    for c in args.channels:
        ident = rd(mv_base(c) + R_IDENT)
        assert ident == MV_IDENT0 + c, f"ch{c} IDENT={ident:08x}"

    for run in range(args.runs):
        for seed in args.seeds:
            for c in args.channels:
                base = mv_base(c)
                rng = np.random.default_rng(seed * 16 + c)
                W = rng.normal(0, 0.02, (args.N, args.K))
                x = rng.normal(0, 1.0, args.K)
                w4, m, e, sh = quantize_weights(W)
                x8, _ = quantize_acts(x)
                golden = matvec_y32(w4, m, sh, x8)
                img, stride = pack_ddr_rows(w4, m)
                nbeats = len(img) // 64
                ng = args.K // 128

                # load weight image (host global address)
                os.pwrite(h2c, img, c * CH_STRIDE + W_LOCAL_BASE)

                # configure channel
                wr(base + R_WBASE_LO, W_LOCAL_BASE & 0xFFFFFFFF)
                wr(base + R_WBASE_HI, W_LOCAL_BASE >> 32)
                wr(base + R_WBEATS, nbeats)
                wr(base + R_SHAPE,
                   shape_word(args.N, int(sh), ng, isa=shape_isa))
                # x vector
                wr(base + R_XPTR, 0)
                xb = x8.astype(np.int8).tobytes()
                xb += b"\x00" * (-len(xb) % 4)
                for i in range(0, len(xb), 4):
                    wr(base + R_XWIN, int.from_bytes(xb[i:i+4], "little"))
                assert rd(base + R_XPTR) == len(xb) // 4

                # go
                t0 = time.monotonic()
                wr(base + R_CTRL, 1)
                while True:
                    st = rd(base + R_STATUS)
                    if st & MV_ST_DONE:
                        break
                    if time.monotonic() - t0 > 10:
                        sys.exit(f"FATAL: ch{c} timeout STATUS={st:x}")
                assert not (st & MV_ST_ERR_RRESP), f"ch{c} err_rresp"
                assert not (st & MV_ST_XOVFL), f"ch{c} xfifo overflow"

                # results
                wr(base + R_RES_PTR, 0)
                got = np.zeros(args.N, dtype=np.uint32)
                for r in range(args.N):
                    got[r] = rd(base + R_RES_DATA)
                errs = int((got.astype(np.int32) != golden).sum())

                cyc = rd(base + R_PERF_CYC_LO) | (rd(base + R_PERF_CYC_HI) << 32)
                beats = rd(base + R_PERF_BEATS)
                bw = beats * 64 / (cyc / UI_CLK_HZ) / 1e9 if cyc else 0.0
                res = {"run": run, "seed": hex(seed), "ch": c,
                       "beats": beats, "cycles": cyc,
                       "ddr_read_GBps": round(bw, 2), "row_errors": errs}
                if errs:
                    bad = np.nonzero(got.astype(np.int32) != golden)[0][:8]
                    res["first_bad"] = [{"row": int(r), "got": int(got[r]),
                                         "exp": int(golden[r])} for r in bad]
                    log["pass"] = False
                log["results"].append(res)
                status = "OK " if errs == 0 else "FAIL"
                print(f"[{status}] run{run} seed={seed:#x} ch{c}: "
                      f"{beats} beats, {bw:.2f} GB/s sustained DDR read, "
                      f"errors={errs}", flush=True)

    print("PASS" if log["pass"] else "FAIL")
    if args.evidence:
        os.makedirs(args.evidence, exist_ok=True)
        fn = os.path.join(args.evidence,
                          f"matvec_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(fn, "w") as f:
            json.dump(log, f, indent=1)
        print(f"evidence: {fn}")
    sys.exit(0 if log["pass"] else 1)


if __name__ == "__main__":
    main()
