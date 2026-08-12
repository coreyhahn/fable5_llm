#!/usr/bin/env python3
"""layer_test.py — stage-3 hardware gate: replay gen_layer_script.py command
scripts against layer_chan over XDMA AXI-Lite, with REAL matvecs on the
stage-2 matvec_chan engine (weights in DDR) verified at every V record.

Usage (on snoke):
  uv run python layer_test.py --scripts ../tb/scripts/layer_s{1,2,3,4}.txt \
      --runs 2 --out ../evidence/stage3/layer_hw_<build>.json

Per charter: each script (seed) is run --runs times WITHOUT reprogramming;
every R/E record and every V (matvec) comparison must be bit-exact.
"""
import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# device map / CSR offsets: single source of truth in hwmap.py
from hwmap import (                                             # noqa: E402
    R_MAGIC, R_VERSION, R_CALIB, MAGIC, CALIB_ALL,
    R_CTRL, R_STATUS, R_WBASE_LO, R_WBASE_HI, R_WBEATS, R_SHAPE, shape_word,
    R_XWIN, R_XPTR, R_RES_PTR, R_RES_DATA, R_IDENT, MV_IDENT0, mv_base,
    LB, L_CMD, L_STAT, L_ARG0, L_ARG1, L_ARG2,
    L_SPTR, L_SWIN, L_EOUT, L_TCNT, L_IDENT, L_AMAXI, L_AMAXV, L_LAYER,
    LAYER_IDENT, SCRATCH_WORDS,
    CH_STRIDE, W_BASE, WID_ALIGN, RES_DEPTH, EMB_BASE,
)


def plan_weights(man, wdir):
    """Pack the manifest's weight images into chan-0 DDR, variable stride.

    A fixed 16 MiB per-wid stride only fits 80 images below EMB_BASE; a
    24-layer token script needs 187.  Instead lay the images out
    back-to-back from W_BASE in wid order, each start aligned up to
    WID_ALIGN.

    The image footprint is exactly nbeats*64 == nrows*stride == the file
    size (pack_ddr_rows emits nrows fixed-size, 64B-aligned rows and
    nothing else), so the intra-image row math the matvec engine uses
    (wbase = base[wid] + r0*stride, wbeats = rc*stride/64) is untouched
    by the packing — only each image's base address moves.

    This is group-size agnostic: `stride` and `nbeats` come from the
    manifest, which pack_ddr_rows already computed from the row format, so
    a g=64 image (one extra 64B scale beat per row when K > 2048) needs no
    special case here.  The per-row arithmetic is re-derived and asserted
    below so a hand-edited manifest cannot silently mis-place an image.

    Returns (base_of_wid, top) where top is the first free address.
    """
    base, a = {}, W_BASE
    for wid, m in sorted(man.items(), key=lambda kv: int(kv[0])):
        sz = int(m["nbeats"]) * 64
        assert sz == int(m["nrows"]) * int(m["stride"]), \
            f"wid {wid}: nbeats*64={sz} != nrows*stride"
        # v2 row format cross-check: stride == (K//128 + ceil((K/g)/32))*64,
        # and the SHAPE ng field is the WEIGHT-beat count in both modes.
        K, g = int(m["k"]), int(m.get("g", 128))
        assert g in (128, 64), f"wid {wid}: unsupported group size {g}"
        assert K % 128 == 0, f"wid {wid}: K={K} is not a multiple of 128"
        wb = K // 128
        sb = -(-(K // g) // 32)
        assert int(m["ng"]) == wb, \
            f"wid {wid}: manifest ng={m['ng']} != weight beats {wb}"
        assert int(m["stride"]) == (wb + sb) * 64, (
            f"wid {wid}: stride {m['stride']} != ({wb}w+{sb}s)*64 for "
            f"K={K} g={g}")
        fsz = os.path.getsize(os.path.join(wdir, m["file"]))
        assert fsz == sz, f"wid {wid}: {m['file']} is {fsz}B, manifest {sz}B"
        base[int(wid)] = a
        a += (sz + WID_ALIGN - 1) // WID_ALIGN * WID_ALIGN
    assert a < EMB_BASE, (
        f"weight images ({len(man)} wids, {a - W_BASE} bytes packed from "
        f"{W_BASE:#x}) reach {a:#x}, past EMB_BASE {EMB_BASE:#x} — "
        f"move EMB_BASE or split the images across DDR channels")
    return base, a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scripts", nargs="+", required=True)
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--chan", type=int, default=0)
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--no-matvec", action="store_true",
                    help="skip V verification (inject-only smoke mode)")
    ap.add_argument("--stop-after", type=int, default=None,
                    help="stop before issuing command N+1 (debug bisection)")
    ap.add_argument("--zero-scratch", action="store_true",
                    help="zero all 16K scratch words before each run "
                         "(match the model's fresh state for --dump diffs)")
    ap.add_argument("--dump", default=None,
                    help="dump full 16K scratch to .npy at stop/end")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    user = os.open(f"{args.dev}_user", os.O_RDWR)
    h2c = os.open(f"{args.dev}_h2c_0", os.O_WRONLY)
    c2h = os.open(f"{args.dev}_c2h_0", os.O_RDONLY)

    def rd(a):
        return int.from_bytes(os.pread(user, 4, a), "little")

    def wr(a, v):
        os.pwrite(user, int(v).to_bytes(4, "little"), a)

    magic, calib = rd(R_MAGIC), rd(R_CALIB)
    print(f"MAGIC={magic:08x} VERSION={rd(R_VERSION):08x} CALIB={calib:x}")
    assert magic == MAGIC, "wrong design"
    assert calib == CALIB_ALL, "DDR not calibrated"
    li = rd(L_IDENT)
    assert li == LAYER_IDENT, f"layer_chan IDENT={li:08x}"
    mb = mv_base(args.chan)
    assert rd(mb + R_IDENT) == MV_IDENT0 + args.chan, "mvchan ident"

    report = {
        "test": "stage3_layer_hw_gate",
        "git": subprocess.run(["git", "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              cwd=os.path.dirname(os.path.abspath(__file__))
                              ).stdout.strip(),
        "version_csr": hex(rd(R_VERSION)),
        "runs": args.runs, "chan": args.chan, "real_matvec": not args.no_matvec,
        "results": [], "pass": True,
    }

    def run_matvec(man, wbase_of, wid, x8_words):
        """Run weight image wid on the engine; chunk rows > RES_DEPTH."""
        m = man[str(wid)] if str(wid) in man else man[wid]
        nrows, ng, sh, stride = m["nrows"], m["ng"], m["sh"], m["stride"]
        g = int(m.get("g", 128))       # v2 group size; absent == 128 legacy
        xb = bytes((w & 0xFF) for w in x8_words)
        xb += b"\x00" * (-len(xb) % 4)
        out = np.zeros(nrows, dtype=np.int64)
        r0 = 0
        while r0 < nrows:
            rc = min(RES_DEPTH, nrows - r0)
            wbase = wbase_of[int(wid)] + r0 * stride
            wr(mb + R_WBASE_LO, wbase & 0xFFFFFFFF)
            wr(mb + R_WBASE_HI, wbase >> 32)
            wr(mb + R_WBEATS, rc * stride // 64)
            wr(mb + R_SHAPE, shape_word(rc, sh, ng, g))
            wr(mb + R_XPTR, 0)
            for i in range(0, len(xb), 4):
                wr(mb + R_XWIN, int.from_bytes(xb[i:i + 4], "little"))
            t0 = time.monotonic()
            wr(mb + R_CTRL, 1)
            while True:
                st = rd(mb + R_STATUS)
                if st & 0x2:
                    break
                if time.monotonic() - t0 > 10:
                    sys.exit(f"FATAL: matvec wid={wid} timeout STATUS={st:x}")
            assert not (st & 0xC), f"matvec wid={wid} STATUS={st:x}"
            wr(mb + R_RES_PTR, 0)
            for r in range(rc):
                v = rd(mb + R_RES_DATA)
                out[r0 + r] = v - (1 << 32) if v >= (1 << 31) else v
            r0 += rc
        return out

    for script in args.scripts:
        prefix = script.rsplit(".", 1)[0]
        man = json.load(open(f"{prefix}.weights.json"))
        wdir = os.path.dirname(script)
        # packed variable-stride layout, shared by the upload and every V
        wbase_of, wtop = plan_weights(man, wdir)
        print(f"{os.path.basename(script)}: {len(man)} weight images, "
              f"{wtop - W_BASE} bytes packed {W_BASE:#x}..{wtop:#x}")
        # weight images -> DDR (once per script; persist across runs)
        for wid, m in sorted(man.items(), key=lambda kv: int(kv[0])):
            img = open(os.path.join(wdir, m["file"]), "rb").read()
            n = os.pwrite(h2c, img,
                          args.chan * CH_STRIDE + wbase_of[int(wid)])
            # images are adjacent now: a short DMA would clip the next one
            assert n == len(img), f"wid {wid}: short write {n}/{len(img)}"
        # embedding table -> DDR (stage 4; M records read it back per token)
        embf = f"{prefix}.emb.bin"
        if os.path.exists(embf):
            os.pwrite(h2c, open(embf, "rb").read(),
                      args.chan * CH_STRIDE + EMB_BASE)
        toks = open(script).read().split()

        for run in range(args.runs):
            errors = 0
            ncmd = nchk = nmv = 0
            p = 0
            t_start = time.monotonic()
            if args.zero_scratch:
                wr(L_SPTR, 0)
                for _ in range(SCRATCH_WORDS):
                    wr(L_SWIN, 0)

            def nx():
                nonlocal p
                v = toks[p]
                p += 1
                return v

            while p < len(toks):
                t = nx()
                if t == "W":
                    a, n = int(nx(), 16), int(nx(), 16)
                    wr(L_SPTR, a)
                    for _ in range(n):
                        wr(L_SWIN, int(nx(), 16))
                elif t == "C":
                    if args.stop_after is not None and ncmd == args.stop_after:
                        break
                    op = int(nx(), 16)
                    wr(L_ARG0, int(nx(), 16))
                    wr(L_ARG1, int(nx(), 16))
                    wr(L_ARG2, int(nx(), 16))
                    cnt0 = rd(L_STAT) >> 16
                    wr(L_CMD, op)
                    t0 = time.monotonic()
                    while True:
                        st = rd(L_STAT)
                        if (st >> 16) == ((cnt0 + 1) & 0xFFFF) and not (st & 1):
                            break
                        if time.monotonic() - t0 > 10:
                            sys.exit(f"FATAL: cmd {ncmd} (op {op}) timeout "
                                     f"STATUS={st:08x}")
                    if st & 2:
                        errors += 1
                        print(f"FAIL cmd {ncmd}: err_op")
                    ncmd += 1
                elif t == "R":
                    a, n = int(nx(), 16), int(nx(), 16)
                    wr(L_SPTR, a)
                    for i in range(n):
                        want = int(nx(), 16)
                        got = rd(L_SWIN) & 0xFFFF
                        if got != want:
                            errors += 1
                            if errors < 20:
                                print(f"FAIL R[{a:#x}+{i}] after cmd {ncmd}: "
                                      f"got {got:04x} want {want:04x}")
                        nchk += 1
                elif t == "E":
                    want = int(nx(), 16)
                    got = rd(L_EOUT) & 0xF
                    if got != want:
                        errors += 1
                        print(f"FAIL E after cmd {ncmd}: got {got} want {want}")
                    nchk += 1
                elif t == "T":
                    wr(L_TCNT, int(nx(), 16))
                elif t == "L":
                    wr(L_LAYER, int(nx(), 16))
                elif t == "V":
                    wid, x8a = int(nx(), 16), int(nx(), 16)
                    nin, nrows = int(nx(), 16), int(nx(), 16)
                    exp = np.array([int(nx(), 16) for _ in range(nrows)],
                                   dtype=np.uint32).astype(np.int32)
                    if not args.no_matvec:
                        wr(L_SPTR, x8a)
                        x8 = [rd(L_SWIN) & 0xFF for _ in range(nin)]
                        got = run_matvec(man, wbase_of, wid, x8)
                        bad = int((got != exp.astype(np.int64)).sum())
                        if bad:
                            errors += 1
                            print(f"FAIL V wid={wid} after cmd {ncmd}: "
                                  f"{bad}/{nrows} rows differ")
                        nchk += nrows
                        nmv += 1
                elif t == "M":       # embedding lookup from device DDR
                    tokid, a, n = int(nx(), 16), int(nx(), 16), int(nx(), 16)
                    row = os.pread(c2h, n * 2, args.chan * CH_STRIDE
                                   + EMB_BASE + tokid * n * 2)
                    wr(L_SPTR, a)
                    for i in range(n):
                        wr(L_SWIN, int.from_bytes(row[2*i:2*i+2], "little"))
                elif t == "A":       # AMAX32 winner check
                    widx, wval = int(nx(), 16), int(nx(), 16)
                    gi = rd(L_AMAXI) & 0x3FFFF
                    gv = rd(L_AMAXV)
                    if gi != widx or gv != wval:
                        errors += 1
                        print(f"FAIL A after cmd {ncmd}: got idx={gi} "
                              f"val={gv:08x} want idx={widx} val={wval:08x}")
                    nchk += 2
                elif t == "Q":
                    break
                else:
                    sys.exit(f"FATAL: bad token '{t}' at {p}")
                if errors >= 20:
                    break

            if args.dump:
                wr(L_SPTR, 0)
                scr = np.array([rd(L_SWIN) & 0xFFFF for _ in range(SCRATCH_WORDS)],
                               dtype=np.uint16)
                np.save(args.dump, scr)
                print(f"scratch dump ({ncmd} cmds) -> {args.dump}")

            dt = time.monotonic() - t_start
            res = {"script": os.path.basename(script), "run": run,
                   "cmds": ncmd, "checks": nchk, "matvecs": nmv,
                   "errors": errors, "seconds": round(dt, 1)}
            report["results"].append(res)
            ok = "PASS" if errors == 0 else "FAIL"
            print(f"{ok} {script} run {run}: {ncmd} cmds, {nchk} checks, "
                  f"{nmv} hw matvecs, {errors} errors, {dt:.1f}s")
            if errors:
                report["pass"] = False

    print("STAGE3 LAYER HW:", "PASS" if report["pass"] else "FAIL")
    if args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, indent=1)
        print(f"report -> {args.out}")
    sys.exit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
