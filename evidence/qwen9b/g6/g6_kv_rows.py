#!/usr/bin/env python3
"""g6_kv_rows.py — the BYTES of a window of KV rows, off the board or out of a
reference region image, so the two can be compared ROW BY ROW.

Task 15-D.  `evidence/qwen9b/g6/g6_kv_depth.py` answers "how deep did the
silicon write" — it counts non-zero rows and names the deepest.  That is the
right instrument for §8.7's ceiling claim and the wrong one for a
DIVERGENCE: `106_longctx_lockstep_ref.log` has the chip and the reference
emitting different tokens at decode step 2 of a 502-token prompt, and
localising that needs the CONTENT of the rows around the prompt end, not
their population count.

    # the chip side (takes the shared lock, reads only)
    g6_kv_rows.py --prefix tb/scripts/w9/model_9b_s1 --rows 500-525 \
        --tag post526 --out g6/<n>_kv_rows.json

    # the reference side (NO BOARD): the same window out of a region image
    g6_kv_rows.py --prefix ... --rows 60-67 --image <dump>.state.bin \
        --tag refN64 --out g6/<n>_kv_rows_refN64.json

    # compare two such JSONs, row by row (NO BOARD, no lock)
    g6_kv_rows.py --compare A.json B.json

WHAT A ROW IS.  B15.1: the KV block for (layer, kvhead, K|V) is
`STATE_KV_STRIDE` = 2 MiB; the first `TCNT` rows of `HD` = 256 B hold the
cache, and an int8 exponent side array of `TCNT` entries starts
`STATE_KV_EXP_OFF` = 1 MiB into the same block.  Row `r` IS position `r`.
Both halves are dumped: a row can agree while its exponent does not, and
that distinction is the whole point of the instrument (§14 and the KV
exponent memories per 64-row block).

WHAT IS RECORDED PER ROW: sha256 of the 256 B, the first 32 B verbatim in
hex, the row's exponent byte, and whether the row is all-zero.  The window
is small on purpose (26 rows x 6 blocks is a few tens of KiB of JSON) — this
file is meant to be COMMITTED, unlike the 155 MiB region it samples.

ALSO RECORDED, once per run: sha256 of the WHOLE state region and of the DN
sub-region alone, against the manifest's `sha256` (the artifact's initial
image) and `final_sha256` (the emitter's end state) — reported, never
asserted, because a board that has run a chat session matches neither and
that is not a fault.

BOARD SAFETY.  Never programs the FPGA, never touches flash, never runs
sudo, never calls pcie_helper.sh, writes not one byte to DDR.  It takes the
same shared lock every other tool takes and opens the device through
`sw/seq_run.Dev`, which is the identity gate (MAGIC, VERSION, CALIB).
`--image` and `--compare` open no device at all.
"""
import argparse
import hashlib
import json
import os
import sys

import numpy as np

TOP = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
for _p in (os.path.join(TOP, "sw"), os.path.join(TOP, "ref")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hwmap as HW                                              # noqa: E402

HD = 256                       # bytes per KV row (B15.1)
CHUNK = 32 << 20
HEXN = 32                      # bytes of each row shown verbatim


def kv_block_addr(plan, layer, kvhead, isv):
    """B15.1: i = (layer*4 + kvhead)*2 + isv, block i at kv + i*STRIDE.

    The SAME arithmetic `g6_kv_depth.py` uses, and the same one
    `ref/seq_model.StateRegion._blk` reaches with head = kvhead*2 + isv.
    """
    i = (layer * 4 + kvhead) * 2 + isv
    return int(plan["kv"]) + i * HW.STATE_KV_STRIDE


def parse_rows(s):
    lo, _, hi = s.partition("-")
    lo = int(lo)
    hi = int(hi) if hi else lo
    if not (0 <= lo <= hi < HW.STATE_T_MAX):
        raise SystemExit(f"--rows {s} outside 0..{HW.STATE_T_MAX - 1}")
    return lo, hi


def row_record(r, raw, expb):
    return {"row": int(r),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "zero": bool(not raw.any()),
            "exp": int(expb),
            "hex": bytes(raw[:HEXN]).hex()}


class BoardSide(object):
    """Reads a window out of the resident region, through the identity gate."""

    def __init__(self, args, plan):
        import board_lock as BL
        import seq_run as SR
        self.SR = SR
        self.chan = int(plan["dn"]) >> 32
        self.lock = BL.from_args(args, tool="g6_kv_rows.py").acquire()
        self.lock.__enter__()
        self.dev = SR.Dev(args.dev, chan=self.chan, allow_seq=False)
        self.ident = self.dev.ident
        print(f"  board      MAGIC={self.ident['magic']:#010x} "
              f"VERSION={self.ident['version']:#010x} "
              f"CALIB={self.ident['calib']:#x}")

    def read(self, addr, n):
        return self.dev.dma_read_chan(self.chan, addr & 0xFFFF_FFFF, n)

    def close(self):
        self.lock.__exit__(None, None, None)


class ImageSide(object):
    """Reads the same window out of a flat region image on disk."""

    def __init__(self, path, plan):
        self.path = path
        self.base = int(plan["dn"])
        self.span = int(plan["end"]) - self.base
        n = os.path.getsize(path)
        if n != self.span:
            raise SystemExit(f"{path} is {n} B, the region spans {self.span}")
        self.fh = open(path, "rb")
        self.ident = None
        print(f"  image      {path} {n} B (no board, no lock)")

    def read(self, addr, n):
        self.fh.seek(int(addr) - self.base)
        b = self.fh.read(n)
        assert len(b) == n
        return b

    def close(self):
        self.fh.close()


def dump(side, plan, layers, kvhead, lo, hi, region_sha=True, log=print):
    rep = {"kv_base": int(plan["kv"]), "rows": [lo, hi],
           "kvhead": int(kvhead), "layers": list(layers), "blocks": []}
    if region_sha:
        h_all, h_dn = hashlib.sha256(), hashlib.sha256()
        base, end, kv = int(plan["dn"]), int(plan["end"]), int(plan["kv"])
        off = base
        while off < end:
            n = min(CHUNK, end - off)
            b = side.read(off, n)
            h_all.update(b)
            if off < kv:
                h_dn.update(b[:min(n, kv - off)])
            off += n
        rep["region_sha256"] = h_all.hexdigest()
        rep["dn_sha256"] = h_dn.hexdigest()
        rep["region_bytes"] = end - base
        rep["dn_bytes"] = kv - base
        log(f"  region     {(end - base) / 2**20:.0f} MiB "
            f"[{base:#x},{end:#x})  sha256 {rep['region_sha256']}")
        log(f"  DN alone   {(kv - base) / 2**20:.0f} MiB  "
            f"sha256 {rep['dn_sha256']}")
    n = hi - lo + 1
    for layer in layers:
        for isv, nm in ((0, "K"), (1, "V")):
            a = kv_block_addr(plan, layer, kvhead, isv)
            raw = np.frombuffer(side.read(a + lo * HD, n * HD),
                                dtype=np.uint8).reshape(n, HD)
            exp = np.frombuffer(
                side.read(a + HW.STATE_KV_EXP_OFF + lo, n), dtype=np.uint8)
            rows = [row_record(lo + i, raw[i], exp[i]) for i in range(n)]
            nz = sum(0 if r["zero"] else 1 for r in rows)
            rep["blocks"].append({"layer": int(layer), "kvhead": int(kvhead),
                                  "kind": nm, "addr": int(a), "rows": rows})
            log(f"  L{layer:<2d} kvh{kvhead} {nm}  addr {a:#013x}  "
                f"rows {lo}..{hi}: {nz}/{n} non-zero  "
                f"exp {[int(r['exp']) for r in rows[:8]]}...")
    return rep


def compare(pa, pb, log=print):
    a, b = json.load(open(pa)), json.load(open(pb))
    log(f"=== KV ROW COMPARE")
    log(f"  A {pa}  tag={a.get('tag')}")
    log(f"  B {pb}  tag={b.get('tag')}")
    for k in ("region_sha256", "dn_sha256"):
        if k in a and k in b:
            log(f"  {k:14s} {'SAME' if a[k] == b[k] else 'DIFFER'}  "
                f"A {a[k][:16]}…  B {b[k][:16]}…")
    ka = {(x["layer"], x["kvhead"], x["kind"]): x for x in a["blocks"]}
    kb = {(x["layer"], x["kvhead"], x["kind"]): x for x in b["blocks"]}
    nbad = 0
    for key in sorted(set(ka) & set(kb)):
        ra = {r["row"]: r for r in ka[key]["rows"]}
        rb = {r["row"]: r for r in kb[key]["rows"]}
        for row in sorted(set(ra) & set(rb)):
            x, y = ra[row], rb[row]
            same = (x["sha256"] == y["sha256"])
            sexp = (x["exp"] == y["exp"])
            if not (same and sexp):
                nbad += 1
                log(f"  L{key[0]} kvh{key[1]} {key[2]} row {row}: "
                    f"{'rows DIFFER' if not same else 'rows same'}, "
                    f"exp {x['exp']} vs {y['exp']}"
                    + ("" if same else
                       f"\n      A {x['hex']}\n      B {y['hex']}"))
    first = None
    for key in sorted(set(ka) & set(kb)):
        ra = {r["row"]: r for r in ka[key]["rows"]}
        rb = {r["row"]: r for r in kb[key]["rows"]}
        for row in sorted(set(ra) & set(rb)):
            if ra[row]["sha256"] != rb[row]["sha256"] or \
               ra[row]["exp"] != rb[row]["exp"]:
                first = row if first is None else min(first, row)
    log(f"  KV ROW COMPARE: {'IDENTICAL' if nbad == 0 else f'{nbad} rows differ'}"
        + ("" if first is None else f", lowest differing row {first}"))
    return 0 if nbad == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", help="artifact base (…/model_9b_s1)")
    ap.add_argument("--rows", default="0-0", help="row window, e.g. 500-525")
    ap.add_argument("--layers", default="0,4,7")
    ap.add_argument("--kvhead", type=int, default=0)
    ap.add_argument("--tag", default="")
    ap.add_argument("--out", default=None)
    ap.add_argument("--image", default=None,
                    help="read a flat region image instead of the board")
    ap.add_argument("--no-region-sha", action="store_true")
    ap.add_argument("--compare", nargs=2, default=None,
                    help="compare two dumps, row by row; no board")
    ap.add_argument("--dev", default="/dev/xdma0")
    try:
        import board_lock as BL
        BL.add_lock_args(ap)
    except ImportError:                                  # pragma: no cover
        pass
    args = ap.parse_args()

    if args.compare:
        return compare(*args.compare)
    if not args.prefix:
        ap.error("--prefix is required unless --compare")

    _wids, meta = HW.load_weights_manifest(args.prefix)
    plan = meta["state"]
    if plan is None:
        raise SystemExit(f"{args.prefix} declares no state plan")
    lo, hi = parse_rows(args.rows)
    layers = [int(x) for x in args.layers.split(",") if x != ""]
    print(f"=== KV ROWS {args.tag}")
    print(f"  region     dn={plan['dn']:#x} kv={plan['kv']:#x} "
          f"cv={plan['cv']:#x} end={plan['end']:#x} "
          f"(chan {int(plan['dn']) >> 32})")
    print(f"  window     rows {lo}..{hi}, layers {layers}, kvhead "
          f"{args.kvhead}, K and V")

    side = (ImageSide(args.image, plan) if args.image
            else BoardSide(args, plan))
    try:
        rep = dump(side, plan, layers, args.kvhead, lo, hi,
                   region_sha=not args.no_region_sha)
    finally:
        side.close()
    rep["tag"] = args.tag
    rep["prefix"] = args.prefix
    rep["source"] = args.image if args.image else "board"
    if side.ident:
        rep["version"] = hex(side.ident["version"])
        rep["calib"] = side.ident["calib"]
    man = meta["state"]
    for k in ("sha256", "final_sha256"):
        w = man.get(k)
        if w and "region_sha256" in rep:
            print(f"  vs manifest {k:13s} "
                  f"{'MATCH' if w == rep['region_sha256'] else 'differs'} "
                  f"({w[:16]}…)")
            rep["vs_" + k] = (w == rep["region_sha256"])
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(rep, fh, indent=1)
        print(f"report -> {args.out}")
    print("G6_KV_ROWS: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
