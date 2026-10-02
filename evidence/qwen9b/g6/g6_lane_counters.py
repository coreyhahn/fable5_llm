#!/usr/bin/env python3
"""g6_lane_counters.py — clear / read the layer's two lane counters.

Task 15 fix round 2, the long-context rung.  `evidence/qwen9b/g6/
g6_census.py` reports `L_LCYC` (compute lane, `busy_cmp`) and
`L_SDMA_CYC` (the DMA lane, `sw/hwmap.py:229`) around a `seq_run`
program.  The long-context rung is a `sw/chat_seq.py` session instead, and
`chat_seq` does not touch these CSRs at all — so the counters can be
CLEARED before it and READ after it, from this process, and what they hold
is that whole session.

Both are accumulators at `ACLK_HZ` and "any write clears" (A1.4), so:

    g6_lane_counters.py --clear     before the session
    <the chat session>              chat_seq never writes them
    g6_lane_counters.py --read --steps N --tokens M --t T

Board rails: takes the SHARED lock (`sw/board_lock.py`), opens the device
through `sw/seq_run.Dev`, which is the identity gate — MAGIC, VERSION,
CALIB — and NEVER programs, never DMAs, never sudo.  Two AXI-Lite
accesses.
"""
import argparse
import json
import os
import sys

TOP = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
for _p in (os.path.join(TOP, "sw"), os.path.join(TOP, "ref")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import board_lock as BL                                         # noqa: E402
import hwmap as HW                                              # noqa: E402
import seq_run as SR                                            # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--read", action="store_true")
    ap.add_argument("--steps", type=int, default=0,
                    help="forward steps the session ran (launches)")
    ap.add_argument("--tokens", type=int, default=0,
                    help="tokens the session decoded")
    ap.add_argument("--t", type=int, default=0,
                    help="the context depth T the run reached")
    ap.add_argument("--out", default=None)
    # `sw/seq_run.Dev` appends `_user`/`_h2c_0`/`_c2h_0` itself, so this
    # is the STEM, not a device node.  (It was `/dev/xdma0_user` in the
    # first cut and every call died on `/dev/xdma0_user_user` —
    # `evidence/qwen9b/g6/083_longctx_9b.log` steps [3] and [6].)
    ap.add_argument("--dev", default="/dev/xdma0")
    BL.add_lock_args(ap)
    args = ap.parse_args()
    if not (args.clear or args.read):
        ap.error("pass --clear or --read")

    lock = BL.from_args(args, tool="g6_lane_counters.py").acquire()
    with lock:
        dev = SR.Dev(args.dev, chan=0, allow_seq=True)
        print(f"  board      MAGIC={dev.ident['magic']:#010x} "
              f"VERSION={dev.ident['version']:#010x} "
              f"CALIB={dev.ident['calib']:#x}")
        if args.clear:
            dev.wr(HW.L_LCYC, 0)
            dev.wr(HW.L_SDMA_CYC, 0)
            print(f"  cleared    L_LCYC={dev.rd(HW.L_LCYC)} "
                  f"L_SDMA_CYC={dev.rd(HW.L_SDMA_CYC)}")
            return 0
        lcyc, sdma = dev.rd(HW.L_LCYC), dev.rd(HW.L_SDMA_CYC)
    f = HW.ACLK_HZ
    rep = {"aclk_hz": f, "l_lcyc": lcyc, "l_sdma_cyc": sdma,
           "steps": args.steps, "tokens": args.tokens, "t": args.t}
    print(f"  ACLK_HZ    {f}")
    print(f"  L_LCYC     {lcyc} cycles = {lcyc / f * 1e3:.3f} ms  "
          f"(compute lane, busy_cmp)")
    print(f"  L_SDMA_CYC {sdma} cycles = {sdma / f * 1e3:.3f} ms  "
          f"(DMA lane, busy_dma)")
    if args.steps:
        rep["l_lcyc_ms_per_step"] = lcyc / f * 1e3 / args.steps
        rep["l_sdma_cyc_ms_per_step"] = sdma / f * 1e3 / args.steps
        print(f"  per STEP   L_LCYC {lcyc / f * 1e3 / args.steps:.3f} ms  "
              f"L_SDMA_CYC {sdma / f * 1e3 / args.steps:.3f} ms  "
              f"({args.steps} forward steps)")
    if args.t:
        import tok_meter as TM
        b = TM.state_bytes_per_token(args.t)
        rep["state_bytes_per_token"] = b
        tot = b if isinstance(b, int) else b.get("total")
        print(f"  traffic    sw/tok_meter.state_bytes_per_token({args.t}) = "
              f"{b}")
        if isinstance(tot, int):
            print(f"             = {tot / 2**20:.2f} MiB/token  "
                  f"(label D, the model — DDR channel 3 holds the region)")
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(rep, fh, indent=1)
        print(f"report -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
