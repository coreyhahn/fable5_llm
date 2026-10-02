#!/usr/bin/env python3
"""tok_meter.py — stage-5 increment 4: measured tok/s from DEVICE counters.

Replays a gen_model_script.py command script (default model_s1) on the
board exactly like layer_test.py, but instruments every token with the
on-chip counters instead of trusting the wall clock:

  t_matvec  matvec_chan PERF_CYC/PERF_BEATS (ui_clk 300.12 MHz), summed
            over the V records of the token.  This is DDR-stream
            occupancy: start -> last beat, per engine run.
  t_layer   layer_chan LCYC (aclk 250 MHz) busy-cycle accumulator,
            read-and-differenced around every C record.  Never cleared
            mid-run: deltas are taken mod 2^32, which is exact because a
            single command can never busy for 2^32 cycles (17 s > the
            10 s command timeout).
  wall      time.monotonic across the token, i.e. what the *host* takes
            when it is the sequencer (MMIO-orchestration bound).

Token boundaries are M records (embedding fetch = start of a token).
Everything before the first M is reported separately as "init".

Mode 1 (default): one matvec_chan, one DDR channel — the stage-3/4/5
replay topology.

Mode 2 (--four-chan): each weight image is row-split into 4 contiguous
pieces, piece c living in DDR channel c *at the same packed byte offset*
it would have in a single-channel image (c*CH_STRIDE + wbase[wid] +
r0*stride).  All 4 matvec_chans are then fired concurrently per V record
and the results stitched.  Row splitting is exact: every output row is
an independent dot product over the full k, and the per-image shift `sh`
is global, so a row range computed on any engine is bit-identical.  The
stitched vector is compared against the V record's y32 -- any mismatch
is a hard FAIL.  Time charged per chunk index is the MAX over channels;
bytes are the SUM.

Chunking (why the LM head still works): the engine can retire at most
RES_DEPTH=4096 rows per run.  The split is done in two independent
stages -- first rows -> channels (nrows//4, the first nrows%4 channels
taking one extra row, so unequal/indivisible row counts are legal), then
each channel chunks *its own* range by RES_DEPTH.  No divisibility
constraint is ever imposed on nrows.  The 248,320-row LM head becomes
62,080 rows per channel = 15 chunks of 4096 + 1 of 640 on every channel
(64 engine runs vs 61 for one channel), perfectly balanced.  (Those are row
counts, so they hold at every geometry this project has -- the vocabulary is
248,320 at 0.8B, 2B, 4B and 9B alike.  What is NOT geometry-independent is
the PACK: see D-TOK below.)

Usage (on snoke, board already programmed -- this tool NEVER programs):
  .venv/bin/python tok_meter.py --smoke-lcyc
  .venv/bin/python tok_meter.py --script ../tb/scripts/model_s1.txt --runs 2
  .venv/bin/python tok_meter.py --four-chan --runs 2
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board_lock as BL                                         # noqa: E402
import hwmap as HW                                              # noqa: E402
from hwmap import (                                             # noqa: E402
    UI_CLK_HZ, ACLK_HZ,
    R_MAGIC, R_VERSION, R_CALIB, MAGIC, CALIB_ALL,
    R_CTRL, R_STATUS, R_WBASE_LO, R_WBASE_HI, R_WBEATS, R_SHAPE, shape_word,
    shape_isa_for_version, UnknownBitstream,
    R_PERF_CYC_LO, R_PERF_CYC_HI, R_PERF_BEATS,
    R_XWIN, R_XPTR, R_RES_PTR, R_RES_DATA, R_IDENT,
    MV_IDENT0, MV_ST_DONE, MV_ST_ERR_RRESP, MV_ST_XOVFL, mv_base,
    L_CMD, L_STAT, L_ARG0, L_ARG1, L_ARG2, L_SPTR, L_SWIN, L_EOUT,
    L_TCNT, L_IDENT, L_AMAXI, L_AMAXV, L_LAYER, L_LCYC, LAYER_IDENT,
    OP_ALU, ALU_AMAX32,
    CH_STRIDE, W_BASE, RES_DEPTH, EMB_BASE,
)
from layer_test import plan_weights                             # noqa: E402


# ---------------------------------------------------------------- helpers
def split_rows(nrows, nch):
    """Contiguous row split of an image across nch DDR channels.

    Returns [(row0, count)] * nch.  nrows need not divide by nch: the
    first (nrows % nch) channels take one extra row.  Zero-count entries
    are legal (nrows < nch) and are skipped by the caller.
    """
    base, rem = divmod(nrows, nch)
    out, r = [], 0
    for c in range(nch):
        n = base + (1 if c < rem else 0)
        out.append((r, n))
        r += n
    assert r == nrows
    return out


def res_chunks(r0, n, depth=RES_DEPTH):
    """Cut a channel's row range into <=depth engine runs."""
    out = []
    while n > 0:
        rc = min(depth, n)
        out.append((r0, rc))
        r0 += rc
        n -= rc
    return out


def man_entry(man, wid):
    return man[str(wid)] if str(wid) in man else man[wid]


# ------------------------------------------------------------------ token
OPNAME = {1: "VN", 2: "VNW", 3: "ROPET", 4: "ROPE", 5: "CONVW", 6: "CONV",
          7: "GATE", 8: "DNST", 9: "KVAP", 10: "ATTN", 11: "ALU", 12: "DNZ"}


def new_acc(t):
    return {"cmds": 0, "matvecs": 0, "checks": 0, "errors": 0,
            "mv_cycles": 0, "mv_beats": 0, "mv_runs": 0, "lcyc": 0,
            "man_bytes": 0, "t0": t, "tok_in": None,
            "lcyc_by_op": {}, "cmds_by_op": {}}


def state_bytes_per_token(T, n_dn=24, n_kv=8, nkvh=4):
    """DDR bytes the STATE traffic costs per token, at context length T.

    LABEL D (derived from the plan, not measured): every term is a count of
    transfers the emitter's schedule actually emits (spec 6.1-6.3, SEQ_ISA
    v2.1 B15.1), times the block size the ISA fixes.

      DN    2 x 24 x 1 MiB     one SLD + one SST per DeltaNet layer
      conv  2 x 24 x 128 KiB   the same pair for the conv block
      KV    2 x 8 x 4 x 2 x (T*256 + 64*ceil(T/64))
            per attention layer, per kvhead, for K and V: one SLD and one
            SST of TCNT rows of 256 B plus the exponent side array rounded
            up to one 64 B beat (B15.1's "Length")

    At T = 512 that is ~70 MiB and at T = 4,096 ~182 MiB.  **The spec's 9
    "~ 50 MiB at T = 512" was low and this number corrects it**: it counted
    the DN traffic once per layer rather than once each way, and left the
    conv pair out.
    """
    T = int(T)
    dn = 2 * n_dn * HW.STATE_DN_LAYER
    cv = 2 * n_dn * HW.STATE_CV_STRIDE
    exp = 64 * ((T + 63) // 64)
    kv = 2 * n_kv * nkvh * 2 * (T * 256 + exp)
    return {"dn": dn, "cv": cv, "kv": kv, "total": dn + cv + kv}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", default="../tb/scripts/model_s1.txt")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--chan", type=int, default=0,
                    help="DDR/matvec channel for 1-chan mode")
    ap.add_argument("--four-chan", action="store_true",
                    help="row-split every weight image over all 4 DDR "
                         "channels and fire the 4 engines concurrently")
    ap.add_argument("--verify", choices=["full", "matvec"], default="full",
                    help="full: also check every R/E/A record (default). "
                         "matvec: only the V (matvec) comparisons -- the "
                         "wall clock then excludes scratch read-back "
                         "traffic a real sequencer would not do.")
    ap.add_argument("--skip-upload", action="store_true",
                    help="weights/embedding already in DDR from a previous "
                         "run of this same script+mode")
    ap.add_argument("--smoke-lcyc", action="store_true",
                    help="probe the LCYC counter with a known AMAX32 "
                         "command before measuring")
    ap.add_argument("--smoke-only", action="store_true",
                    help="run the LCYC smoke test and stop (no DMA)")
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--out", default=None)
    # S3: the context length the state-traffic line (label D) is stated at.
    ap.add_argument("--ctx", type=int, default=512,
                    help="context length T for the state bytes/token line")
    BL.add_lock_args(ap)                        # O3: --lock / --no-lock
    args = ap.parse_args()

    # O3 (user ruling 2026-08-29): THE shared board lock, taken FIRST —
    # before any artifact is opened and long before the first device fd,
    # so a refusal is instant and this tool can no longer drive the board
    # out from under a live session.
    try:
        _lock = BL.from_args(args, tool="tok_meter.py").acquire()
    except BL.BoardLockError as e:
        print("*** %s" % e)
        raise SystemExit(4)


    chans = [0, 1, 2, 3] if args.four_chan else [args.chan]
    nch = len(chans)

    user = os.open(f"{args.dev}_user", os.O_RDWR)
    h2c = os.open(f"{args.dev}_h2c_0", os.O_WRONLY)
    c2h = os.open(f"{args.dev}_c2h_0", os.O_RDONLY)

    def rd(a):
        return int.from_bytes(os.pread(user, 4, a), "little")

    def wr(a, v):
        os.pwrite(user, int(v).to_bytes(4, "little"), a)

    # ---- board identity gate (never DMA without it) --------------------
    magic, ver, calib = rd(R_MAGIC), rd(R_VERSION), rd(R_CALIB)
    assert magic == MAGIC, "wrong design"
    assert calib == CALIB_ALL, "DDR not calibrated"
    # WHICH R_SHAPE LAYOUT THE RESIDENT BITSTREAM DECODES (G3.3), gated in
    # the SAME place as MAGIC/CALIB and BEFORE anything is packed: the word
    # goes straight to a live BAR, so it follows the VERSION CSR and not this
    # checkout's RTL, and an image this checkout has no layout for REFUSES
    # rather than guessing (the two layouts decode each other's words as
    # plausible garbage -- sw/hwmap.UnknownBitstream).
    try:
        shape_isa = shape_isa_for_version(ver)
    except UnknownBitstream as ex:
        raise SystemExit("REFUSING TO TOUCH THE BOARD — " + str(ex))
    print(f"MAGIC={magic:08x} VERSION={ver:08x} CALIB={calib:x} "
          f"SHAPE_ISA={shape_isa}")
    li = rd(L_IDENT)
    assert li == LAYER_IDENT, f"layer_chan IDENT={li:08x}"
    for c in chans:
        ident = rd(mv_base(c) + R_IDENT)
        assert ident == MV_IDENT0 + c, f"ch{c} IDENT={ident:08x}"

    report = {
        "test": "stage5_inc4_tok_meter",
        "utc": datetime.now(timezone.utc).isoformat(),
        "git": subprocess.run(["git", "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              cwd=os.path.dirname(os.path.abspath(__file__))
                              ).stdout.strip(),
        "version_csr": f"{ver:#010x}",
        "shape_isa": shape_isa,
        "script": os.path.basename(args.script),
        "mode": "4chan" if args.four_chan else "1chan",
        "channels": chans, "runs": args.runs, "verify": args.verify,
        "ui_clk_hz": UI_CLK_HZ, "aclk_hz": ACLK_HZ,
        "smoke_lcyc": None, "runs_out": [], "pass": True,
    }

    # ================================================================
    # LCYC smoke test: clear, run ONE known command, read back.
    # AMAX32 (vec_alu op 10) is the safest probe on a live board: it
    # only READS scratch (len {lo,hi} pairs from srca) and writes no
    # scratch word; the only state it touches is AMAXI/AMAXV, which
    # every script re-establishes with a fresh scan (p0[0]=1) before
    # its own A check.
    # ================================================================
    def smoke_lcyc():
        wr(L_LCYC, 0)
        z = rd(L_LCYC)
        print(f"LCYC smoke: after write-clear LCYC={z} (expect 0)")
        rows = [{"len": 0, "lcyc": z, "note": "cleared"}]
        ok = (z == 0)
        prev = None
        for ln in (256, 512, 1024, 2048):
            wr(L_LCYC, 0)
            wr(L_ARG0, (ln << 4) | ALU_AMAX32)
            wr(L_ARG1, 0)          # srca = srcb = scratch word 0
            wr(L_ARG2, 1)          # p0[0]=1 -> fresh scan, dst unused
            cnt0 = rd(L_STAT) >> 16
            t0 = time.monotonic()
            wr(L_CMD, OP_ALU)
            while True:
                st = rd(L_STAT)
                if (st >> 16) == ((cnt0 + 1) & 0xFFFF) and not (st & 1):
                    break
                if time.monotonic() - t0 > 10:
                    sys.exit(f"FATAL: LCYC smoke timeout STATUS={st:08x}")
            wall_us = (time.monotonic() - t0) * 1e6
            lc = rd(L_LCYC)
            dev_us = lc / ACLK_HZ * 1e6
            print(f"LCYC smoke: AMAX32 len={ln:5d} -> LCYC={lc:7d} cyc "
                  f"({lc / ln:.2f} cyc/elem, {dev_us:8.2f} us device, "
                  f"{wall_us:8.2f} us wall)")
            rows.append({"len": ln, "lcyc": lc, "cyc_per_elem": lc / ln,
                         "device_us": dev_us, "wall_us": wall_us})
            ok = ok and lc > 0 and dev_us < wall_us
            if prev is not None:
                ok = ok and abs(lc / prev - 2.0) < 0.10   # linear in len
            prev = lc
        print("LCYC smoke:", "PASS" if ok else "FAIL")
        return {"pass": bool(ok), "rows": rows}

    if args.smoke_lcyc or args.smoke_only:
        report["smoke_lcyc"] = smoke_lcyc()
        if not report["smoke_lcyc"]["pass"]:
            report["pass"] = False
        if args.smoke_only:
            if args.out:
                with open(args.out, "w") as f:
                    json.dump(report, f, indent=1)
                print(f"report -> {args.out}")
            sys.exit(0 if report["pass"] else 1)

    # ================================================================
    # weight/embedding placement
    # ================================================================
    prefix = args.script.rsplit(".", 1)[0]
    man, wmeta = HW.load_weights_manifest(prefix)
    wdir = os.path.dirname(args.script)

    # ---- D-TOK (spec 9): this tool could not plan a 2B pack, and could not
    # have planned a 9B one either.  It called `plan_weights(man, wdir)` --
    # the NCH-INDEPENDENT path, in which EVERY channel reserves the WHOLE
    # image -- while its own uploader had always split rows across channels.
    # At 0.8B the images are small enough that the 4x over-reservation still
    # fits below EMB_BASE; at 2B it does not, and `plan_weights` aborts on
    # its own assert before any DMA (RD_GATE.md follow-on 3).  At 9B the pack
    # is 3,902 MiB against a 1,280 MiB window, so the same thing happens
    # harder.
    #
    # The fix is to ask for the layout this tool ACTUALLY uploads.  Its row
    # law is `split_rows` -- one contiguous row-quarter per channel, which is
    # `seq_format.LAYOUT_CONTIG` -- so `rows_of` is exactly that split's row
    # counts, and each channel then packs only the rows it owns.
    repack = nch > 1

    def _rows_of(_wid, nrows):
        return [n for (_r0, n) in split_rows(nrows, nch)]

    if repack:
        wbase_of, wtop = plan_weights(man, wdir, nch=nch, rows_of=_rows_of)
    else:
        wbase_of, wtop = plan_weights(man, wdir)

    def wbase_chan(wid, i):
        """Channel-slot `i`'s base for image `wid` (repacked or shared)."""
        b = wbase_of[int(wid)]
        return b[i] if isinstance(b, (list, tuple)) else b

    _tops = wtop if isinstance(wtop, (list, tuple)) else (wtop,)
    man_bytes_of = {int(k): int(v["nbeats"]) * 64 for k, v in man.items()}
    print(f"{os.path.basename(args.script)}: {len(man)} weight images, "
          f"{max(_tops) - W_BASE} bytes packed {W_BASE:#x}.."
          f"{'/'.join(f'{t:#x}' for t in _tops)}"
          f"{' (per-channel repack)' if repack else ''}; "
          f"mode={'4chan' if args.four_chan else '1chan'} chans={chans}")

    # precompute the per-V engine plan once (pure arithmetic, no MMIO).
    # plan[wid] = [(slot, chan, chan_row0, [(row0, rowcount), ...]), ...] --
    # channels with no rows at all (nrows < nch) are dropped, keeping the
    # chan binding explicit rather than positional.  `chan_row0` is the
    # GLOBAL row that channel's packed block starts at, which is what turns
    # a global row into a channel-local byte offset under the repack.
    plan = {}
    for k, m in man.items():
        wid = int(k)
        parts = split_rows(int(m["nrows"]), nch)
        plan[wid] = [(i, chans[i], r0, res_chunks(r0, n))
                     for i, (r0, n) in enumerate(parts) if n > 0]

    if not args.skip_upload:
        t0 = time.monotonic()
        nbytes = 0
        for k, m in sorted(man.items(), key=lambda kv: int(kv[0])):
            wid, stride = int(k), int(m["stride"])
            img = open(os.path.join(wdir, m["file"]), "rb").read()
            mv = memoryview(img)
            for i, c in enumerate(chans):
                r0, n = split_rows(int(m["nrows"]), nch)[i]
                if n == 0:
                    continue
                off, sz = r0 * stride, n * stride
                # repacked: the channel's block starts at ITS first row, so
                # the local offset is 0; shared: every channel holds the
                # whole image and the global offset applies.
                wa = (c * CH_STRIDE + wbase_chan(wid, i)
                      + (0 if repack else off))
                got = os.pwrite(h2c, mv[off:off + sz], wa)
                assert got == sz, f"wid {wid} ch{c}: short write {got}/{sz}"
                nbytes += sz
        embf = f"{prefix}.emb.bin"
        if os.path.exists(embf):
            emb = open(embf, "rb").read()
            got = os.pwrite(h2c, emb, chans[0] * CH_STRIDE + EMB_BASE)
            assert got == len(emb), f"emb short write {got}/{len(emb)}"
            nbytes += len(emb)
        print(f"upload: {nbytes / 1e6:.1f} MB in "
              f"{time.monotonic() - t0:.1f}s")

    # ================================================================
    # the instrumented matvec
    # ================================================================
    def run_matvec(wid, x8_words):
        """Run image `wid` across `chans`; return (y32, cycles, beats).

        cycles = sum over chunk index of max-over-channels PERF_CYC
                 (the channels of one chunk index run concurrently)
        beats  = sum over every engine run of PERF_BEATS
        """
        m = man_entry(man, wid)
        nrows, ng, sh, stride = (int(m["nrows"]), int(m["ng"]),
                                 int(m["sh"]), int(m["stride"]))
        # v2 W4 group size (manifest "g", ABSENT == 128).  Everything else
        # here is already manifest-driven — stride/nbeats come from
        # pack_ddr_rows and so already include the extra g=64 scale beat, and
        # the PERF_BEATS cross-check below is `rc*stride//64` — so the mode
        # bit in SHAPE is the only thing the group size changes.
        g = int(m.get("g", 128))
        # V5 weight width (manifest "w8", ABSENT == W4).  Same story as
        # `g`: stride/nbeats already come from the packer's row law, so
        # SHAPE bit 29 is the only thing the width changes here.
        w8 = bool(m.get("w8", False))
        xb = bytes((w & 0xFF) for w in x8_words)
        xb += b"\x00" * (-len(xb) % 4)
        xw = [int.from_bytes(xb[i:i + 4], "little")
              for i in range(0, len(xb), 4)]
        clists = plan[int(wid)]
        out = np.zeros(nrows, dtype=np.int64)
        cyc_tot = beats_tot = runs = 0

        for j in range(max(len(cl) for (_i, _c, _r, cl) in clists)):
            active = [(i, c, cr0, cl[j])
                      for (i, c, cr0, cl) in clists if j < len(cl)]
            for i, c, cr0, (r0, rc) in active:
                b = mv_base(c)
                wbase = (wbase_chan(wid, i)
                         + (r0 - (cr0 if repack else 0)) * stride)
                wr(b + R_WBASE_LO, wbase & 0xFFFFFFFF)
                wr(b + R_WBASE_HI, wbase >> 32)
                wr(b + R_WBEATS, rc * stride // 64)
                wr(b + R_SHAPE,
                   shape_word(rc, sh, ng, g, w8=w8, isa=shape_isa))
                wr(b + R_XPTR, 0)
                for w in xw:
                    wr(b + R_XWIN, w)
            # doorbells last and back to back: the 4 engines overlap
            for _i, c, _cr0, _rc in active:
                wr(mv_base(c) + R_CTRL, 1)
            t0 = time.monotonic()
            for _i, c, _cr0, _rc in active:
                b = mv_base(c)
                while True:
                    st = rd(b + R_STATUS)
                    if st & MV_ST_DONE:
                        break
                    if time.monotonic() - t0 > 10:
                        sys.exit(f"FATAL: matvec wid={wid} ch{c} timeout "
                                 f"STATUS={st:x}")
                assert not (st & (MV_ST_ERR_RRESP | MV_ST_XOVFL)), \
                    f"matvec wid={wid} ch{c} STATUS={st:x}"
            cyc_j = 0
            for _i, c, _cr0, (r0, rc) in active:
                b = mv_base(c)
                cyc = rd(b + R_PERF_CYC_LO) | (rd(b + R_PERF_CYC_HI) << 32)
                beats = rd(b + R_PERF_BEATS)
                assert beats == rc * stride // 64, \
                    f"wid={wid} ch{c}: {beats} beats, want {rc*stride//64}"
                cyc_j = max(cyc_j, cyc)
                beats_tot += beats
                runs += 1
                wr(b + R_RES_PTR, 0)
                for r in range(rc):
                    v = rd(b + R_RES_DATA)
                    out[r0 + r] = v - (1 << 32) if v >= (1 << 31) else v
            cyc_tot += cyc_j
        return out, cyc_tot, beats_tot, runs

    # ================================================================
    # replay
    # ================================================================
    toks = open(args.script).read().split()

    for run in range(args.runs):
        segs = []
        mv_shape = {}          # "nrows x k" -> {n, beats, cycles}
        seen_m = False
        lprev = rd(L_LCYC)
        acc = new_acc(time.monotonic())
        errors = 0
        p = 0

        def nx():
            nonlocal p
            v = toks[p]
            p += 1
            return v

        def flush(tag):
            acc["seg"] = tag
            acc["seconds"] = time.monotonic() - acc.pop("t0")
            segs.append(acc)

        t_run0 = time.monotonic()
        while p < len(toks):
            t = nx()
            if t == "W":
                a, n = int(nx(), 16), int(nx(), 16)
                wr(L_SPTR, a)
                for _ in range(n):
                    wr(L_SWIN, int(nx(), 16))
            elif t == "C":
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
                        sys.exit(f"FATAL: cmd (op {op}) timeout "
                                 f"STATUS={st:08x}")
                lnow = rd(L_LCYC)
                d = (lnow - lprev) & 0xFFFFFFFF
                lprev = lnow
                acc["lcyc"] += d
                nm = OPNAME.get(op, f"op{op}")
                acc["lcyc_by_op"][nm] = acc["lcyc_by_op"].get(nm, 0) + d
                acc["cmds_by_op"][nm] = acc["cmds_by_op"].get(nm, 0) + 1
                if st & 2:
                    errors += 1
                    acc["errors"] += 1
                    print(f"FAIL cmd {acc['cmds']}: err_op")
                acc["cmds"] += 1
            elif t == "R":
                a, n = int(nx(), 16), int(nx(), 16)
                want = [int(nx(), 16) for _ in range(n)]
                if args.verify == "full":
                    wr(L_SPTR, a)
                    for i in range(n):
                        got = rd(L_SWIN) & 0xFFFF
                        if got != want[i]:
                            errors += 1
                            acc["errors"] += 1
                            if errors < 20:
                                print(f"FAIL R[{a:#x}+{i}]: got {got:04x} "
                                      f"want {want[i]:04x}")
                        acc["checks"] += 1
            elif t == "E":
                want = int(nx(), 16)
                if args.verify == "full":
                    got = rd(L_EOUT) & 0xF
                    if got != want:
                        errors += 1
                        acc["errors"] += 1
                        print(f"FAIL E: got {got} want {want}")
                    acc["checks"] += 1
            elif t == "T":
                wr(L_TCNT, int(nx(), 16))
            elif t == "L":
                wr(L_LAYER, int(nx(), 16))
            elif t == "V":
                wid, x8a = int(nx(), 16), int(nx(), 16)
                nin, nrows = int(nx(), 16), int(nx(), 16)
                exp = np.array([int(nx(), 16) for _ in range(nrows)],
                               dtype=np.uint32).astype(np.int32)
                wr(L_SPTR, x8a)
                x8 = [rd(L_SWIN) & 0xFF for _ in range(nin)]
                got, cyc, beats, nruns = run_matvec(wid, x8)
                bad = int((got != exp.astype(np.int64)).sum())
                if bad:
                    errors += 1
                    acc["errors"] += 1
                    br = np.nonzero(got != exp.astype(np.int64))[0][:4]
                    print(f"FAIL V wid={wid}: {bad}/{nrows} rows differ, "
                          f"first {[(int(r), int(got[r]), int(exp[r])) for r in br]}")
                acc["checks"] += nrows
                acc["matvecs"] += 1
                acc["mv_cycles"] += cyc
                acc["mv_beats"] += beats
                acc["mv_runs"] += nruns
                acc["man_bytes"] += man_bytes_of[int(wid)]
                mm = man_entry(man, wid)
                sk = f"{mm['nrows']}x{mm['k']}"
                e = mv_shape.setdefault(sk, {"n": 0, "runs": 0, "beats": 0,
                                             "cycles": 0})
                e["n"] += 1
                e["runs"] += nruns
                e["beats"] += beats
                e["cycles"] += cyc
            elif t == "M":
                tokid, a, n = int(nx(), 16), int(nx(), 16), int(nx(), 16)
                flush("token" if seen_m else "init")
                acc = new_acc(time.monotonic())
                acc["tok_in"] = tokid
                seen_m = True
                # D-TOK (spec 9): the row STRIDE on DDR is the manifest's
                # `emb_row_bytes`, and the hardware addresses it by a SHIFT
                # (seq_unit's EMBLOG2), not by a multiply.  `n * 2` agrees
                # with that only when 2*H is the power of two the CSR
                # encodes — true at 0.8B (2048), 2B (4096) and 9B (8192),
                # and a COINCIDENCE at every one of them.  Assert it rather
                # than depend on it, and address with the real stride.
                row_bytes = int(wmeta["emb_row_bytes"])
                assert row_bytes == n * 2, (
                    f"the manifest says {row_bytes} B embedding rows but "
                    f"the script's M record reads {n} words = {n * 2} B")
                assert row_bytes == 1 << HW.seq_emb_log2(row_bytes), (
                    f"embedding row stride {row_bytes} is not the power of "
                    f"two seq_unit's EMBLOG2 can encode")
                row = os.pread(c2h, n * 2,
                               chans[0] * CH_STRIDE + EMB_BASE
                               + tokid * row_bytes)
                wr(L_SPTR, a)
                for i in range(n):
                    wr(L_SWIN, int.from_bytes(row[2 * i:2 * i + 2], "little"))
            elif t == "A":
                widx, wval = int(nx(), 16), int(nx(), 16)
                if args.verify == "full":
                    gi, gv = rd(L_AMAXI) & 0x3FFFF, rd(L_AMAXV)
                    if gi != widx or gv != wval:
                        errors += 1
                        acc["errors"] += 1
                        print(f"FAIL A: got idx={gi} val={gv:08x} "
                              f"want idx={widx} val={wval:08x}")
                    acc["checks"] += 2
            elif t == "Q":
                break
            else:
                sys.exit(f"FATAL: bad token '{t}' at {p}")
            if errors >= 20:
                sys.exit("FATAL: 20 errors, aborting (hard FAIL)")
        flush("token" if seen_m else "init")
        t_run = time.monotonic() - t_run0
        p = 0

        # ---------------------------------------------------------- report
        tokens = [s for s in segs if s["seg"] == "token"]
        for s in segs:
            s["t_matvec_s"] = s["mv_cycles"] / UI_CLK_HZ
            s["t_layer_s"] = s["lcyc"] / ACLK_HZ
            s["t_device_s"] = s["t_matvec_s"] + s["t_layer_s"]
            s["stream_bytes"] = s["mv_beats"] * 64
            s["bytes_match"] = (s["stream_bytes"] == s["man_bytes"])
            s["device_toks"] = (1.0 / s["t_device_s"]) if s["t_device_s"] else None
            s["wall_toks"] = 1.0 / s["seconds"] if s["seconds"] else None
            if not s["bytes_match"]:
                report["pass"] = False
            if s["errors"]:
                report["pass"] = False

        print()
        print(f"=== run {run}  mode={'4chan' if args.four_chan else '1chan'}"
              f"  verify={args.verify}  {os.path.basename(args.script)} ===")
        hdr = (f"{'seg':>5} {'tok_in':>7} {'V':>4} {'runs':>5} {'C':>6} "
               f"{'MB':>8} {'t_mv ms':>9} {'GB/s':>7} {'t_lc ms':>9} "
               f"{'dev ms':>9} {'dev tok/s':>10} {'wall s':>8} "
               f"{'wall tok/s':>11} {'B=man':>6} {'err':>4}")
        print(hdr)
        print("-" * len(hdr))
        for i, s in enumerate(segs):
            gbs = (s["stream_bytes"] / s["t_matvec_s"] / 1e9
                   if s["t_matvec_s"] else 0.0)
            print(f"{s['seg'][:5]:>5} "
                  f"{('-' if s['tok_in'] is None else s['tok_in']):>7} "
                  f"{s['matvecs']:>4} {s['mv_runs']:>5} {s['cmds']:>6} "
                  f"{s['stream_bytes']/1e6:>8.1f} "
                  f"{s['t_matvec_s']*1e3:>9.3f} {gbs:>7.2f} "
                  f"{s['t_layer_s']*1e3:>9.3f} {s['t_device_s']*1e3:>9.3f} "
                  f"{(s['device_toks'] or 0):>10.2f} {s['seconds']:>8.2f} "
                  f"{(s['wall_toks'] or 0):>11.3f} "
                  f"{'OK' if s['bytes_match'] else 'MISMATCH':>6} "
                  f"{s['errors']:>4}")

        n = len(tokens)
        tmv = sum(s["t_matvec_s"] for s in tokens)
        tlc = sum(s["t_layer_s"] for s in tokens)
        twall = sum(s["seconds"] for s in tokens)
        sbytes = sum(s["stream_bytes"] for s in tokens)
        mbytes = sum(s["man_bytes"] for s in tokens)
        agg = {
            "run": run, "tokens": n,
            "t_matvec_s": tmv, "t_layer_s": tlc, "t_device_s": tmv + tlc,
            "t_wall_tokens_s": twall, "t_wall_run_s": t_run,
            "stream_bytes": sbytes, "manifest_bytes": mbytes,
            "bytes_per_token": sbytes // n if n else 0,
            "bytes_match": sbytes == mbytes,
            "device_toks": n / (tmv + tlc) if (tmv + tlc) else None,
            "wall_toks": n / twall if twall else None,
            "ddr_GBps": sbytes / tmv / 1e9 if tmv else None,
            "matvec_frac": tmv / (tmv + tlc) if (tmv + tlc) else None,
            "errors": sum(s["errors"] for s in segs),
            "mv_by_shape": mv_shape,
            "segments": segs,
        }
        # where the layer_chan busy time goes, per token (opcode profile)
        by_op = {}
        for s in tokens:
            for k, v in s["lcyc_by_op"].items():
                q = by_op.setdefault(k, [0, 0])
                q[0] += v
                q[1] += s["cmds_by_op"][k]
        agg["layer_by_op"] = {
            k: {"cycles_per_token": v[0] // n, "cmds_per_token": v[1] // n,
                "ms_per_token": v[0] / n / ACLK_HZ * 1e3,
                "pct": 100.0 * v[0] / sum(x[0] for x in by_op.values())}
            for k, v in sorted(by_op.items(), key=lambda kv: -kv[1][0])
        } if n else {}
        report["runs_out"].append(agg)
        if not agg["bytes_match"] or agg["errors"]:
            report["pass"] = False
        print("-" * len(hdr))
        print(f"TOTAL {n} tokens: t_matvec={tmv*1e3:.2f} ms "
              f"t_layer={tlc*1e3:.2f} ms  device={(tmv+tlc)*1e3:.2f} ms")
        print(f"  DEVICE tok/s = {agg['device_toks']:.2f}   "
              f"(matvec {100*agg['matvec_frac']:.1f}% / layer_chan "
              f"{100*(1-agg['matvec_frac']):.1f}%)")
        print(f"  WALL   tok/s = {agg['wall_toks']:.3f}   "
              f"({twall:.1f}s of token replay, {t_run:.1f}s incl. init)")
        # S3 (spec 7.1, 9): the STATE traffic the SLD/SST schedule adds,
        # beside the weight traffic measured above.  Label D -- it is the
        # schedule's own arithmetic, not a measurement, and it is stated at
        # the run's own context length.
        sb = state_bytes_per_token(getattr(args, "ctx", 512))
        agg["state_bytes_per_token"] = sb
        print(f"  state    {sb['total'] / 2**20:.0f} MiB/token at T="
              f"{getattr(args, 'ctx', 512)} (D): DN {sb['dn'] / 2**20:.0f} + "
              f"conv {sb['cv'] / 2**20:.0f} + KV {sb['kv'] / 2**20:.0f} MiB")
        print(f"  streamed {agg['bytes_per_token']} B/token, "
              f"{agg['ddr_GBps']:.2f} GB/s aggregate DDR read; "
              f"beats*64 vs manifest: "
              f"{'EXACT MATCH' if agg['bytes_match'] else 'MISMATCH'} "
              f"({sbytes} vs {mbytes})")
        print("  layer_chan busy by opcode (per token):")
        for k, v in agg["layer_by_op"].items():
            print(f"    {k:>6} {v['cmds_per_token']:>5} cmds "
                  f"{v['ms_per_token']:>8.3f} ms {v['pct']:>5.1f}%")
        print("  matvec engine by image shape (whole run):")
        for k, v in sorted(mv_shape.items(),
                           key=lambda kv: -kv[1]["cycles"]):
            gb = v["beats"] * 64 / (v["cycles"] / UI_CLK_HZ) / 1e9
            print(f"    {k:>12} x{v['n']:<4} {v['runs']:>4} runs "
                  f"{v['beats']*64/1e6:>8.1f} MB "
                  f"{v['cycles']/UI_CLK_HZ*1e3:>8.2f} ms {gb:>6.2f} GB/s")

    print()
    print("TOK_METER:", "PASS" if report["pass"] else "FAIL")
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(report, f, indent=1)
        print(f"report -> {args.out}")
    sys.exit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
