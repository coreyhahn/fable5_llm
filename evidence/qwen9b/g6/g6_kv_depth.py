#!/usr/bin/env python3
"""g6_kv_depth.py — how deep into the KV region did the silicon actually write?

Task 15 fix round 2, the long-context rung.  `sw/chat_seq.py` reports the
context it reached as `sess.T`, which is a HOST counter.  This reads the
DDR back and asks the region the same question, so "the context passed 512"
is a physical fact about the board and not a number the driver printed.

B15.1's KV block is `STATE_KV_STRIDE` = 2 MiB per (layer, kvhead, K|V):
`TCNT` rows of `HD` = 256 B from the block base, and the exponent side
array of `TCNT` int8 at `STATE_KV_EXP_OFF` = 1 MiB into it.  So the last
non-zero 256 B row IS the deepest position that layer's SST stored.

The comparison only means something from a KNOWN start, so the sequence is

    evidence/qwen9b/g6/g6_state.py --write-initial   (KV zeroed, verbatim)
    g6_kv_depth.py                                   (0 rows — the control)
    <the long-context chat session>
    g6_kv_depth.py                                   (T rows)

`sw/seq_run.upload_state` and `chat_seq`'s context reset both leave the KV
region alone by design ("128 MiB of DMA this host does not do"; TCNT is 0
after a reset, so no KV row is read before it is written), which is exactly
why the pre-zeroing has to be explicit.

BOARD SAFETY: the shared lock, `sw/seq_run.Dev`'s identity gate (MAGIC,
VERSION, CALIB), reads only.  Never programs, never sudo.
"""
import argparse
import json
import os
import sys

import numpy as np

TOP = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
for _p in (os.path.join(TOP, "sw"), os.path.join(TOP, "ref")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import board_lock as BL                                         # noqa: E402
import hwmap as HW                                              # noqa: E402
import seq_run as SR                                            # noqa: E402

HD = 256                       # bytes per KV row (B15.1)


def kv_block_addr(plan, layer, kvhead, isv):
    """B15.1: i = (layer*4 + kvhead)*2 + isv, block i at kv + i*STRIDE."""
    i = (layer * 4 + kvhead) * 2 + isv
    return int(plan["kv"]) + i * HW.STATE_KV_STRIDE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", required=True,
                    help="artifact base (…/model_9b_s1) for the state plan")
    ap.add_argument("--layers", default="0,4,7",
                    help="attention layers to probe (0..7)")
    ap.add_argument("--kvhead", type=int, default=0)
    ap.add_argument("--rows", type=int, default=4096,
                    help="rows to read per block (<= STATE_T_MAX)")
    ap.add_argument("--tag", default="")
    ap.add_argument("--out", default=None)
    ap.add_argument("--dev", default="/dev/xdma0")
    BL.add_lock_args(ap)
    args = ap.parse_args()

    _wids, meta = HW.load_weights_manifest(args.prefix)
    plan = meta["state"]
    if plan is None:
        raise SystemExit(f"{args.prefix} declares no state plan")
    chan = int(plan["kv"]) >> 32
    nrows = min(int(args.rows), HW.STATE_T_MAX)
    print(f"=== KV DEPTH {args.tag}")
    print(f"  region     kv={plan['kv']:#x} (chan {chan}), "
          f"stride {HW.STATE_KV_STRIDE} B, {nrows} rows x {HD} B probed")
    rep = {"tag": args.tag, "kv_base": int(plan["kv"]), "rows_probed": nrows,
           "blocks": []}
    lock = BL.from_args(args, tool="g6_kv_depth.py").acquire()
    with lock:
        dev = SR.Dev(args.dev, chan=chan, allow_seq=False)
        print(f"  board      MAGIC={dev.ident['magic']:#010x} "
              f"VERSION={dev.ident['version']:#010x} "
              f"CALIB={dev.ident['calib']:#x}")
        for layer in [int(x) for x in args.layers.split(",") if x != ""]:
            for isv, nm in ((0, "K"), (1, "V")):
                a = kv_block_addr(plan, layer, args.kvhead, isv)
                raw = dev.dma_read_chan(chan, a & 0xFFFF_FFFF, nrows * HD)
                rows = np.frombuffer(raw, dtype=np.uint8).reshape(nrows, HD)
                nz = np.flatnonzero(rows.any(axis=1))
                exp = np.frombuffer(
                    dev.dma_read_chan(
                        chan,
                        (a + HW.STATE_KV_EXP_OFF) & 0xFFFF_FFFF, nrows),
                    dtype=np.uint8)
                enz = np.flatnonzero(exp)
                b = {"layer": layer, "kvhead": args.kvhead, "kind": nm,
                     "addr": int(a),
                     "rows_nonzero": int(nz.size),
                     "last_row_nonzero": (int(nz[-1]) if nz.size else None),
                     "exp_nonzero": int(enz.size),
                     "last_exp_nonzero": (int(enz[-1]) if enz.size else None)}
                rep["blocks"].append(b)
                print(f"  L{layer:<2d} kvh{args.kvhead} {nm}  "
                      f"addr {a:#013x}  rows non-zero {b['rows_nonzero']:5d}"
                      f"  deepest row {b['last_row_nonzero']}"
                      f"   exp non-zero {b['exp_nonzero']:5d}"
                      f"  deepest {b['last_exp_nonzero']}")
    deep = [b["last_row_nonzero"] for b in rep["blocks"]
            if b["last_row_nonzero"] is not None]
    rep["deepest_row"] = max(deep) if deep else None
    print(f"  DEEPEST KV ROW WRITTEN: {rep['deepest_row']}  "
          f"(the old on-chip ceiling was T <= 512)")
    if args.out:
        with open(args.out, "w") as f:
            json.dump(rep, f, indent=1)
        print(f"report -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
