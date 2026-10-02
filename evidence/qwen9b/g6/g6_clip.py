#!/usr/bin/env python3
"""g6_clip.py — the residual clip counters, OBSERVED on hardware.

    python3 evidence/qwen9b/g6/g6_clip.py --prefix tb/scripts/w9/model_9b_s1.e4

WHAT STEP 7 IS ASKING FOR, and what the hardware actually offers.

The plan wants §4.4's accepted fragility "observed rather than assumed": the
int16 Q7.8 residual rail at |x|max 32767, whose 95/108 top-1 was measured
WITH the container in place and which Track L reads as an UPPER BOUND rather
than a clean measurement.  There is NO dedicated clip-counter CSR in the
RTL — `rtl/layer_chan.sv` and `rtl/vec_alu.sv` clip (clip16/clip20/clip32)
without counting — so this reads the three things the silicon does publish
and derives the count from the residual itself:

  * the post-halt SCRATCHPAD, all 65,536 words, read through SPTR/SWIN.  The
    residual vectors live there, so a word sitting exactly at +32767 or
    -32768 is a residual that reached the rail.  That count IS the clip
    count, taken from the chip's own memory rather than from a model.
  * `L_MAXPL`/`L_MAXPH` — vec_alu op-8's max|prod| probe, 48 bits, the
    headroom measurement the RTL does keep.
  * `L_AMAXI`/`L_AMAXV` — the LM head's argmax index and value, which is
    what a clipped residual would move.

It is the FIRST observation of any of this on silicon, and it is reported as
an observation: a count, not a verdict.

BOARD SAFETY.  Never programs, never flashes, never sudoes.  Shared board
lock.  The layer CSRs are read only after the sequencer has HALTED.
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
for _p in (os.path.join(_ROOT, "sw"), os.path.join(_ROOT, "ref")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np                                             # noqa: E402
import board_lock as BL                                        # noqa: E402
import hwmap as HW                                             # noqa: E402
import seq_run as SR                                           # noqa: E402

I16_MAX, I16_MIN = 32767, -32768


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--base", default=None)
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--chan", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--json", default=None)
    BL.add_lock_args(ap)
    a = ap.parse_args(argv)
    try:
        lk = BL.from_args(a, tool="g6_clip.py").acquire()
    except BL.BoardLockError as e:
        print("*** %s" % e)
        return 4

    art = SR.Artifacts(a.prefix, base=a.base)
    plan = SR.plan_ddr(art.meta, len(art.stream), len(art.blob), chan=a.chan)
    recs, _ = SR.relocate(art.recs, art.meta, plan, len(art.blob))
    dev = SR.Dev(a.dev, chan=a.chan, allow_seq=True)
    print(f"--- board: MAGIC={dev.ident['magic']:#010x} "
          f"VERSION={dev.ident['version']:#010x} CALIB={dev.ident['calib']:#x}")
    if not dev.seq_ok:
        print("REFUSING: " + dev.seq_why)
        return 1
    SR.upload(dev, art, plan, recs, do_weights=False, verify=True)
    # the same two hygiene steps the census learned the hard way (019)
    st = art.state
    chan, base, nby = st["dn"] >> 32, st["dn"] & 0xFFFF_FFFF, st["end"] - st["dn"]
    SR.verify_state_image(art)
    with open(art.base + ".state.bin", "rb") as f:
        off = 0
        while off < nby:
            b = f.read(min(32 << 20, nby - off))
            dev.dma_write_chan(chan, base + off, b)
            off += len(b)
    dev.layer_zero_scratch()
    print(f"--- fresh state region + zeroed {HW.SCRATCH_WORDS_BUILT}-word pad")

    run = SR.seq_start_and_poll(dev, art, plan, timeout=a.timeout)
    want = SR.expected_tokens(art.meta)
    print(f"  tokens {run['tokens']}  "
          + ("IDENTICAL" if run["tokens"] == want else f"MISMATCH want {want}"))
    if run["status"]["err_code"]:
        print("HALTED WITH AN ERROR — not reporting counters off a bad run")
        return 1

    # ---- the residual, out of the chip's own scratchpad ------------------
    scr = dev.layer_read_scratch(0, HW.SCRATCH_WORDS_BUILT)
    s16 = np.asarray(scr, dtype=np.int64)
    s16 = np.where(s16 >= 1 << 15, s16 - (1 << 16), s16).astype(np.int32)
    nz = s16 != 0
    hi = int(np.count_nonzero(s16 == I16_MAX))
    lo = int(np.count_nonzero(s16 == I16_MIN))
    amax = int(np.max(np.abs(s16))) if s16.size else 0
    rs_f = HW.load_weights_manifest(art.base)[1].get("rs_f",
                                                     HW.RS_F_DEFAULT)
    print(f"--- THE RESIDUAL RAIL, on chip (int16 Q{15 - rs_f}.{rs_f} "
          f"from the manifest's rs_f={rs_f}; |x|max {I16_MAX})")
    print(f"  scratch words        {s16.size} read back, "
          f"{int(nz.sum())} non-zero")
    print(f"  AT +32767            {hi}")
    print(f"  AT -32768            {lo}")
    print(f"  CLIPPED TOTAL        {hi + lo}   "
          f"({(hi + lo) / max(int(nz.sum()), 1) * 100:.4f} % of the non-zero "
          f"words)")
    print(f"  |x|max observed      {amax}  "
          f"({amax / I16_MAX * 100:.2f} % of the rail)")
    for th in (0.5, 0.75, 0.9, 0.95, 0.99):
        n = int(np.count_nonzero(np.abs(s16) >= int(th * I16_MAX)))
        print(f"  |x| >= {th * 100:>4.0f} % rail   {n}")
    # ---- the probes the RTL does keep ------------------------------------
    mpl, mph = dev.rd(HW.L_MAXPL), dev.rd(HW.L_MAXPH)
    maxp = (mph << 32) | mpl
    ai, av = dev.rd(HW.L_AMAXI) & 0x3FFFF, dev.rd(HW.L_AMAXV)
    print(f"--- the RTL's own headroom probes")
    print(f"  L_MAXP (vec_alu op-8 max|prod|, 48b)  {maxp}  "
          f"(lo {mpl:#010x} hi {mph:#06x})")
    print(f"  L_AMAXI / L_AMAXV (LM head argmax)    {ai} / {av:#010x} "
          f"({av if av < 2**31 else av - 2**32})")
    rep = {"prefix": a.prefix, "version": hex(dev.ident["version"]),
           "tokens": run["tokens"], "tokens_ok": run["tokens"] == want,
           "scratch_words": int(s16.size), "nonzero": int(nz.sum()),
           "at_pos_rail": hi, "at_neg_rail": lo, "clipped_total": hi + lo,
           "abs_max": amax,
           "near_rail": {str(t): int(np.count_nonzero(
               np.abs(s16) >= int(t * I16_MAX))) for t in
               (0.5, 0.75, 0.9, 0.95, 0.99)},
           "l_maxp": maxp, "l_amaxi": ai, "l_amaxv": av,
           "rs_f": rs_f}
    if a.json:
        json.dump(rep, open(a.json, "w"), indent=1)
        print(f"  json -> {a.json}")
    del lk
    print("G6_CLIP: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
