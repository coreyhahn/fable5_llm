#!/usr/bin/env python3
"""bm1_census.py — BM1-T4: the per-step board census, the two lanes and the
B16 idle counters, on either bitstream.  Modelled on
evidence/qwen9b/g6/g6_census.py (RD9 §10's path).  Run ON SNOKE.

TWO MODES

  --chat [--json F] [--want-ids a,b,c] -- <chat_seq args...>
      Runs sw/chat_seq.py's own main() UNCHANGED, with its module-level
      `_launch` wrapped: before each launch (sequencer IDLE — the arbitration
      rule, docs/SEQ_ISA.md) L_LCYC and L_SDMA_CYC are cleared and read back
      0; after the HALT (idle again) both lanes and L_TCNT are read.  The
      launch report `_launch` returns already carries `perf` = seq_perf(),
      which includes the B16 `bm` dict when BM_IDENT (SEQ 0x100) reads
      0xFAB1B301 — feature detection, so build_041 simply has no `bm`.
      Every launch is appended to --json with its image, pos, tokens, perf,
      device_ms and lanes.  chat_seq's identity gate (SR.Dev: seq_ok) and its
      refusals run exactly as in a plain chat_seq run: a closed gate refuses
      before any DMA.  Admission of BM1 = FABLE5_SEQ_EXPECT_VERSION=9b588e78
      in the environment (T4prep).
      --want-ids (fix round 1, I2) makes the run FAIL-CLOSED on its tokens:
      the reply ids (the tokens of every launch, in order) must equal the
      list exactly, or the tool exits 1 printing both lists.  A non-zero
      chat_seq rc is never masked.

  --stream --prefix <.e4 prefix> [--fresh-state]
      g6_census.py's run of a whole multi-token stream (weights assumed
      resident: stream + blob only), plus the B16 block read after HALT.
      REFUSES before any DMA when seq_ok is false.

Never programs the FPGA, never touches flash, never runs sudo.
"""
import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
for _p in (os.path.join(_ROOT, "sw"), os.path.join(_ROOT, "ref")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np                                             # noqa: E402
import hwmap as HW                                             # noqa: E402
import seq_run as SR                                           # noqa: E402

F = HW.ACLK_HZ


# ======================================================================
# --chat
# ======================================================================
def parse_ids(s):
    out = []
    for x in str(s).split(","):
        x = x.strip()
        if not x.isdigit():
            raise ValueError(f"--want-ids: {x!r} is not a token id")
        out.append(int(x))
    if not out:
        raise ValueError("--want-ids: empty list")
    return out


def run_ids(log):
    return [int(t) for r in log for t in (r.get("tokens") or [])]


def verdict(log, rc, want):
    """The exit code of a --chat run: chat_seq's rc, and — when `want` is
    given — 1 on ANY difference between the run's ids and `want`."""
    if want is None:
        return rc
    got = run_ids(log)
    if got == list(want):
        print(f"TOKENS IDENTICAL to --want-ids {list(want)}")
        return rc
    print(f"TOKENS MISMATCH: got  {got}")
    print(f"                 want {list(want)}")
    return rc if rc else 1


def split_chat_argv(rest):
    jp, want = None, None
    while rest and rest[0] in ("--json", "--want-ids"):
        if len(rest) < 2:
            raise SystemExit(f"{rest[0]} needs a value")
        if rest[0] == "--json":
            jp = rest[1]
        else:
            want = parse_ids(rest[1])
        rest = rest[2:]
    if rest and rest[0] == "--":
        rest = rest[1:]
    return jp, want, rest


def chat_mode(json_path, chat_argv, want=None):
    import chat_seq as CS
    orig = CS._launch
    log = []

    def _launch_census(dev, image, *a, **k):
        st = dev.seq_status()
        if st["busy"]:
            raise CS.ChatSeqError("bm1_census: sequencer busy before a "
                                  "launch — lanes NOT touched")
        dev.wr(HW.L_LCYC, 0)
        dev.wr(HW.L_SDMA_CYC, 0)
        z = (dev.rd(HW.L_LCYC), dev.rd(HW.L_SDMA_CYC))
        rep = orig(dev, image, *a, **k)
        rec = {"n": len(log), "image": image.name, "pos": rep.get("pos"),
               "tok_in": rep.get("tok_in"), "tokens": rep.get("tokens"),
               "device_ms": rep.get("device_ms"), "wall_ms": rep.get("wall_ms"),
               "perf": rep.get("perf"), "lanes_cleared": list(z),
               "l_lcyc": dev.rd(HW.L_LCYC),
               "l_sdma_cyc": dev.rd(HW.L_SDMA_CYC),
               "l_tcnt": dev.rd(HW.L_TCNT)}
        log.append(rec)
        return rep

    CS._launch = _launch_census
    sys.argv = ["chat_seq.py"] + chat_argv
    rc = 0
    t0 = time.monotonic()
    try:
        CS.main()
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        CS._launch = orig
        out = {"tool": "bm1_census --chat", "argv": chat_argv, "rc": rc,
               "env": {k: os.environ.get(k) for k in
                       ("FABLE5_MODEL", "FABLE5_SEQ_EXPECT_VERSION")},
               "wall_s": round(time.monotonic() - t0, 1), "launches": log}
        if json_path:
            with open(json_path, "w") as f:
                json.dump(out, f, indent=1, default=str)
        summarize(log)
        rc = verdict(log, rc, want)
        print(f"BM1_CENSUS_CHAT: rc {rc}, {len(log)} launches"
              + (f" -> {json_path}" if json_path else ""))
    return rc


def summarize(log):
    for kind in ("preamble", "step.lite", "step.full"):
        L = [r for r in log if r["image"] == kind or
             r["image"].endswith(kind.split(".")[-1])]
        if not L:
            continue
        cyc = np.array([r["perf"]["cyc"] for r in L], dtype=float)
        print(f"--- {kind}: {len(L)} launches; PERF_CYC mean {cyc.mean():.1f} "
              f"(= {cyc.mean() / F * 1e3:.4f} ms) min {cyc.min():.0f} "
              f"max {cyc.max():.0f}")
        lc = np.array([r["l_lcyc"] for r in L], dtype=float)
        sd = np.array([r["l_sdma_cyc"] for r in L], dtype=float)
        print(f"    L_LCYC mean {lc.mean():.1f} ({lc.mean() / cyc.mean() * 100:.2f} %)"
              f"  L_SDMA_CYC mean {sd.mean():.1f} ({sd.mean() / cyc.mean() * 100:.2f} %)")
        if all("bm" in r["perf"] for r in L):
            for k in L[0]["perf"]["bm"]:
                v = np.array([r["perf"]["bm"][k] for r in L], dtype=float)
                pct = (f" ({v.mean() / cyc.mean() * 100:.2f} % of PERF_CYC)"
                       if k not in ("BM_IDENT", "BM_STEPS") else "")
                print(f"    {k:<14} mean {v.mean():.1f}{pct}  "
                      f"min {v.min():.0f} max {v.max():.0f}")
        else:
            print("    (no B16 block: BM_IDENT did not match — feature absent)")


# ======================================================================
# --stream (g6_census.py + the B16 block)
# ======================================================================
def stream_mode(a):
    import board_lock as BL
    try:
        lk = BL.from_args(a, tool="bm1_census.py --stream").acquire()
    except BL.BoardLockError as e:
        print("*** %s" % e)
        return 4
    art = SR.Artifacts(a.prefix, base=a.base)
    plan = SR.plan_ddr(art.meta, len(art.stream), len(art.blob), chan=a.chan)
    recs, _ = SR.relocate(art.recs, art.meta, plan, len(art.blob))
    dev = SR.Dev(a.dev, chan=a.chan, allow_seq=True)
    print(f"--- board: MAGIC={dev.ident['magic']:#010x} "
          f"VERSION={dev.ident['version']:#010x} "
          f"CALIB={dev.ident['calib']:#x}  "
          f"SEQ={'READY' if dev.seq_ok else 'REFUSED'}")
    if not dev.seq_ok:
        print("REFUSING before any DMA: " + dev.seq_why)
        return 1
    if dev.ident["calib"] != 0xF:
        print("REFUSING before any DMA: CALIB != 0xF")
        return 1
    want = SR.expected_tokens(art.meta)
    ntok = len(want)
    print(f"--- {a.prefix}: {art.nrec} records, {ntok} tokens")
    urep, _wb, _s = SR.upload(dev, art, plan, recs, do_weights=False,
                              verify=True)
    print(f"  stream/blob re-uploaded and verified "
          f"({urep['verified_bytes'] / 2**20:.1f} MiB)")
    if a.fresh_state:
        st = art.state
        chan, base = st["dn"] >> 32, st["dn"] & 0xFFFF_FFFF
        nby = st["end"] - st["dn"]
        sha = SR.verify_state_image(art)
        with open(art.base + ".state.bin", "rb") as f:
            off = 0
            while off < nby:
                b = f.read(min(32 << 20, nby - off))
                dev.dma_write_chan(chan, base + off, b)
                off += len(b)
        print(f"--- fresh state: {nby / 2**20:.0f} MiB -> {st['dn']:#x} "
              f"(chan {chan}), sha256 {sha[:16]}")
    dev.layer_zero_scratch()
    dev.wr(HW.L_LCYC, 0)
    dev.wr(HW.L_SDMA_CYC, 0)
    print(f"--- lanes cleared: {dev.rd(HW.L_LCYC)} {dev.rd(HW.L_SDMA_CYC)}")
    SR.seq_set_emb_row_bytes(dev, art.emb_row_bytes)
    SR.seq_check_state_bases(dev, art)
    dev.seq_wr(HW.S_ENTRY, 0)
    base = plan["stream_base"] + dev.ddr_off
    dev.seq_wr(HW.S_BASE_LO, base & 0xFFFFFFFF)
    dev.seq_wr(HW.S_BASE_HI, (base >> 32) & 0x3)
    dev.seq_wr(HW.S_LEN, art.nrec)
    for i in range(HW.SEQ_XRF_N):
        dev.seq_wr(HW.s_xrf(i), 0)
    toks, trace = [], []
    t0 = time.monotonic()
    dev.seq_wr(HW.S_CTRL, HW.SEQ_CTRL_START)
    last_pc = -1
    while True:
        pc = dev.seq_rd(HW.S_PC)
        cy = dev.seq_rd(HW.S_PERF_CYC)
        stt = dev.seq_status()
        if pc < last_pc:
            trace.append({"pc": pc, "cyc": cy})
        last_pc = pc
        while True:
            v = dev.seq_rd(HW.S_OUT_FIFO)
            if not (v & HW.SEQ_OUT_VALID):
                break
            toks.append(v & HW.SEQ_OUT_TOK_MASK)
        if not stt["busy"]:
            break
        if time.monotonic() - t0 > a.timeout:
            raise SystemExit("TIMEOUT")
    stt = dev.seq_status()
    while True:
        v = dev.seq_rd(HW.S_OUT_FIFO)
        if not (v & HW.SEQ_OUT_VALID):
            break
        toks.append(v & HW.SEQ_OUT_TOK_MASK)
    perf = dev.seq_perf()
    cyc = perf["cyc"]
    lcyc, sdma = dev.rd(HW.L_LCYC), dev.rd(HW.L_SDMA_CYC)
    dev_ms = cyc / F * 1e3
    print(f"--- run: err_code={stt['err_code']:#04x} tokens {toks}")
    print(f"  S_PERF_CYC {cyc} = {dev_ms:.3f} ms = {dev_ms / ntok:.4f} ms/token")
    print(f"  L_LCYC {lcyc} ({lcyc / cyc * 100:.2f} %)  L_SDMA_CYC {sdma} "
          f"({sdma / cyc * 100:.2f} %)")
    bm = perf.get("bm")
    if bm:
        for k, v in bm.items():
            print(f"  {k:<14} {v}" + ("" if k in ("BM_IDENT", "BM_STEPS")
                                      else f"  ({v / cyc * 100:.2f} %)"))
    else:
        print("  (no B16 block)")
    for i, t in enumerate(trace):
        d = t["cyc"] - trace[i - 1]["cyc"] if i else None
        print(f"  loop edge {i}: pc->{t['pc']} cyc {t['cyc']}"
              + (f" delta {d} = {d / F * 1e3:.3f} ms" if d else ""))
    ok = toks == want and not stt["err_code"]
    print("  TOKENS " + ("IDENTICAL to the .seq.json" if toks == want
                         else f"MISMATCH want {want}"))
    rep = {"prefix": a.prefix, "version": hex(dev.ident["version"]),
           "tokens": toks, "want": want, "err_code": stt["err_code"],
           "perf": perf, "device_ms": dev_ms, "ntok": ntok,
           "l_lcyc": lcyc, "l_sdma_cyc": sdma, "loop_edges": trace}
    if a.json:
        json.dump(rep, open(a.json, "w"), indent=1)
    del lk
    print("BM1_CENSUS_STREAM: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--chat":
        jp, want, rest = split_chat_argv(argv[1:])
        return chat_mode(jp, rest, want)
    import board_lock as BL
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stream", action="store_true", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--base", default=None)
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--chan", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--fresh-state", action="store_true")
    ap.add_argument("--json", default=None)
    BL.add_lock_args(ap)
    return stream_mode(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
