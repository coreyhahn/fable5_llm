#!/usr/bin/env python3
"""cycle_census.py — where does a 150 ms decode step actually go?

Phase 1 of the rung-3 decision census (docs/SPEEDUP_LADDER.md): run the
canned 6-step schedule launch-per-step and snapshot, around EVERY launch:
  - S_PERF_CYC/REC/AXW/AXR (seq, @250 MHz, resets at START)
  - L_LCYC (layer_chan busy accumulator, @250 MHz, free-running delta)
  - matvec chan0 PERF_CYC/BEATS (@300.12 MHz, free-running delta)
Decomposition per step (sequencer v1 executes records to completion, so
layer-busy and matvec-busy are disjoint covered intervals inside the seq
total; CMD DONE-polling overlaps layer busy and is charged to layer):
  total(seq) = layer_busy + matvec_busy + REST
  REST = movers (MOVX/MOVY bulk AXIL) + LDC/EMB DDR + fetch/decode/issue
Cross-check: AXW/AXR counts x an AXIL cost/beat estimated from the same
run must roughly reproduce REST.

Usage (snoke): .venv/bin/python cycle_census.py --out ../evidence/rung3/census_step.json
"""
import argparse, json, sys, time

import board_lock as BL
import chat_seq as CS
import hwmap as HW

ACLK = HW.ACLK_HZ if hasattr(HW, "ACLK_HZ") else 250e6
UICLK = HW.UI_CLK_HZ


def snap(dev):
    mv0 = HW.mv_base(0) if hasattr(HW, "mv_base") else 0x1000
    return {
        "lcyc": dev.rd(HW.L_LCYC),
        "mv_cyc": (dev.rd(mv0 + HW.R_PERF_CYC_HI) << 32)
                  | dev.rd(mv0 + HW.R_PERF_CYC_LO),
        "mv_beats": dev.rd(mv0 + HW.R_PERF_BEATS),
    }


def seq_perf(dev):
    return {
        "cyc": dev.rd(HW.S_PERF_CYC),
        "rec": dev.rd(HW.S_PERF_REC),
        "axw": dev.rd(HW.S_PERF_AXW),
        "axr": dev.rd(HW.S_PERF_AXR),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--prefill", default="full", choices=("lite", "full"))
    # O3: the device was hard-coded, so this tool could not be pointed away
    # from the board even for a dry check.  It can now.
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--chan", type=int, default=0)
    BL.add_lock_args(ap)                        # O3: --lock PATH / --no-lock
    args_c = ap.parse_args()

    # O3: the shared board lock, FIRST — before the board, before bring-up.
    try:
        lock = BL.from_args(args_c, tool="cycle_census.py",
                            error=CS.ChatSeqError).acquire()
    except CS.ChatSeqError as e:
        print("*** %s" % e)
        raise SystemExit(4)

    # args namespace ChatSession reads (mirrors serve.py's adapter)
    import types
    a = types.SimpleNamespace(
        dev=args_c.dev, chan=args_c.chan, template=CS.TEMPLATE_PREFIX,
        any_template=False, t_max=CS.T_MAX, max_ctx=500, pos_mode="auto",
        prefill=args_c.prefill, ntok=8, force_upload=False,
        timeout=30.0, preamble_timeout=30.0, lock=args_c.lock,
        no_lock=args_c.no_lock, verify=False,
        out=None, prompt=[], canned=False, smoke=False, selftest=False,
        model_only=False, continue_context=False, steps=0)

    sess = CS.ChatSession(a, log=print)
    sess.open_board()
    sess.bring_up()
    rep_pre = sess.preamble()

    rows = []
    # canned prompt + expected argmax feedback, from the artifact meta
    prompt = [760, 6511, 314, 9338]
    expect = list(sess.meta.get("expect_tokens", []))
    nsteps = 6
    toks = prompt + expect[3:5]          # feed for steps 0..5
    for i in range(nsteps):
        lite = (args_c.prefill == "lite" and i < len(prompt) - 1)
        s0 = snap(sess.dev)
        t0 = time.monotonic()
        out, rep = sess.step(toks[i], lite=lite)
        wall = time.monotonic() - t0
        s1 = snap(sess.dev)
        sp = seq_perf(sess.dev)
        d_lcyc = (s1["lcyc"] - s0["lcyc"]) & 0xFFFFFFFF
        d_mvc = s1["mv_cyc"] - s0["mv_cyc"]
        d_mvb = s1["mv_beats"] - s0["mv_beats"]
        total_ms = sp["cyc"] / ACLK * 1e3
        layer_ms = d_lcyc / ACLK * 1e3
        mv_ms = d_mvc / UICLK * 1e3
        rest_ms = total_ms - layer_ms - mv_ms
        rows.append(dict(step=i, kind="lite" if lite else "full", out=out,
                         seq=sp, lcyc=d_lcyc, mv_cyc=d_mvc, mv_beats=d_mvb,
                         total_ms=total_ms, layer_ms=layer_ms, mv_ms=mv_ms,
                         rest_ms=rest_ms, wall_s=wall))
        print(f"  step {i} {'lite' if lite else 'full'}: total {total_ms:8.2f} ms"
              f" = layer {layer_ms:7.2f} + matvec {mv_ms:7.2f} + REST {rest_ms:7.2f}"
              f"   (axw {sp['axw']:,} axr {sp['axr']:,} beats {d_mvb:,})")

    tot = sum(r["total_ms"] for r in rows)
    lay = sum(r["layer_ms"] for r in rows)
    mv = sum(r["mv_ms"] for r in rows)
    rest = sum(r["rest_ms"] for r in rows)
    axw = sum(r["seq"]["axw"] for r in rows)
    axr = sum(r["seq"]["axr"] for r in rows)
    print(f"\n  6-step totals: {tot:.1f} ms = layer {lay:.1f} ({lay/tot*100:.1f}%)"
          f" + matvec {mv:.1f} ({mv/tot*100:.1f}%)"
          f" + REST {rest:.1f} ({rest/tot*100:.1f}%)")
    print(f"  AXIL: {axw:,} writes + {axr:,} reads over {tot:.1f} ms"
          f" -> implied {(rest/1e3)*ACLK/max(axw+axr,1):.2f} cyc per AXIL op if REST were all AXIL")
    if args_c.out:
        json.dump({"rows": rows, "preamble": rep_pre,
                   "totals": dict(total_ms=tot, layer_ms=lay, mv_ms=mv,
                                  rest_ms=rest, axw=axw, axr=axr)},
                  open(args_c.out, "w"), indent=1)
        print(f"  -> {args_c.out}")
    lock.release()


if __name__ == "__main__":
    main()
