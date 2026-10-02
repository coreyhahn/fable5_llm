#!/usr/bin/env python3
"""g6_census.py — the perf census on silicon: BOTH lanes, BOTH conventions.

    python3 evidence/qwen9b/g6/g6_census.py --prefix tb/scripts/w9/model_9b_s1.e4

WHAT THE AMENDMENT ASKS FOR that no existing tool reports.

  * **Two lanes.**  `L_LCYC` is the compute lane (`busy_cmp`) and
    `L_SDMA_CYC` is the DMA lane (`sw/hwmap.py:229`); "any write clears", so
    both are cleared before START and read after HALT.  They are LAYER CSRs,
    so they are touched ONLY while the sequencer is idle — the arbitration
    rule in docs/SEQ_ISA.md.  S4's comparands: the compute lane 45.674
    ms/token (S4 §5.3.1), and a MODELLED 5.133 ms/token for the DMA lane
    which the board number REPLACES rather than adds to.

  * **Both amortization conventions.**  RD_GATE §1 defines them: the GATE
    convention is device/ntok; the STEADY-STATE convention subtracts the
    session-once preamble.  At 2B that constant came from a `chat --canned`
    session, and `sw/chat_seq.py` cannot run a 9B artifact (its templates
    are byte slices of tb/scripts/w4/model_v2_s1.e, TEMPLATE_NREC 60495,
    against this stream's 158,536).  So the preamble is MEASURED HERE, ON
    CHIP, instead of inherited: `S_PERF_CYC` counts cycles busy since START
    and is readable WHILE busy, so polling it beside `S_PC` and recording
    the value at each backward jump gives the exact device cycles of each
    loop iteration — and the preamble is the total minus what the iterations
    account for.  No host clock enters the number.

  * **The per-channel matvec spread**, from each engine's own
    `R_PERF_CYC_LO/HI` and `R_PERF_BEATS`.

BOARD SAFETY.  Never programs the FPGA, never touches flash, never runs
sudo.  It assumes the pack is already resident (it passes do_weights=False)
and re-uploads only the stream and the blob, which is what a re-run needs.
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
import board_lock as BL                                        # noqa: E402
import hwmap as HW                                             # noqa: E402
import seq_run as SR                                           # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--base", default=None)
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--chan", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--fresh-state", action="store_true",
                    help="write <base>.state.bin over the region first.  "
                         "REQUIRED for a token-correct re-run: this tool "
                         "uploads no weights, and sw/seq_run.upload_state "
                         "under --skip-weights is CSRs-only, so the DN and "
                         "conv state left by the PREVIOUS run would be the "
                         "state this one loads through SLD.  019 is the log "
                         "of getting that wrong: the run halted cleanly with "
                         "err_code 0x00 and produced [760, 369, 279, 13, 198, "
                         "760] instead of §4.1a's tokens, with nothing "
                         "anywhere reporting a fault.")
    ap.add_argument("--json", default=None)
    BL.add_lock_args(ap)
    a = ap.parse_args(argv)
    try:
        lk = BL.from_args(a, tool="g6_census.py").acquire()
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
        print("REFUSING: " + dev.seq_why)
        return 1
    ntok = len(SR.expected_tokens(art.meta))
    print(f"--- {a.prefix}: {art.nrec} records, {art.meta['steps']} steps, "
          f"loop {art.meta['loop_steps']} steps, {ntok} tokens")

    # stream + blob only: the pack is resident (do_weights=False)
    urep, _wb, _s = SR.upload(dev, art, plan, recs, do_weights=False,
                              verify=True)
    print(f"  stream/blob re-uploaded and verified "
          f"({urep['verified_bytes'] / 2**20:.1f} MiB)")

    if a.fresh_state:
        st = art.state
        chan, base = st["dn"] >> 32, st["dn"] & 0xFFFF_FFFF
        nby = st["end"] - st["dn"]
        want = SR.verify_state_image(art)
        with open(art.base + ".state.bin", "rb") as f:
            off = 0
            while off < nby:
                b = f.read(min(32 << 20, nby - off))
                dev.dma_write_chan(chan, base + off, b)
                off += len(b)
        print(f"--- fresh state: {nby / 2**20:.0f} MiB of "
              f"{os.path.basename(art.base)}.state.bin -> {st['dn']:#x} "
              f"(chan {chan}), sha256 {want[:16]}")

    # ---- the scratchpad, for the same reason ----------------------------
    dev.layer_zero_scratch()
    nz = int(np.count_nonzero(dev.layer_read_scratch(0,
                                                     HW.SCRATCH_WORDS_BUILT)))
    print(f"--- scratch: {HW.SCRATCH_WORDS_BUILT} words zeroed and read back, "
          f"{nz} non-zero")

    # ---- clear the two lane counters, idle ------------------------------
    dev.wr(HW.L_LCYC, 0)
    dev.wr(HW.L_SDMA_CYC, 0)
    l0, s0 = dev.rd(HW.L_LCYC), dev.rd(HW.L_SDMA_CYC)
    print(f"--- lane counters cleared: L_LCYC={l0} L_SDMA_CYC={s0}")

    # ---- START, and sample (S_PC, S_PERF_CYC) while busy ----------------
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
        if pc < last_pc:                       # a backward jump: loop edge
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
    wall = time.monotonic() - t0
    stt = dev.seq_status()
    while True:
        v = dev.seq_rd(HW.S_OUT_FIFO)
        if not (v & HW.SEQ_OUT_VALID):
            break
        toks.append(v & HW.SEQ_OUT_TOK_MASK)
    cyc = dev.seq_rd(HW.S_PERF_CYC)
    rec = dev.seq_rd(HW.S_PERF_REC)
    pc = dev.seq_rd(HW.S_PC)

    # ---- the two lanes, read while IDLE ---------------------------------
    lcyc = dev.rd(HW.L_LCYC)
    sdma = dev.rd(HW.L_SDMA_CYC)
    mv = []
    for c in range(4):
        b = HW.mv_base(c)
        lo, hi = dev.rd(b + HW.R_PERF_CYC_LO), dev.rd(b + HW.R_PERF_CYC_HI)
        mv.append({"chan": c, "cyc": (hi << 32) | lo,
                   "beats": dev.rd(b + HW.R_PERF_BEATS)})

    F = HW.ACLK_HZ
    dev_ms = cyc / F * 1e3
    print(f"--- run: pc={pc}/{art.nrec} err_code={stt['err_code']:#04x} "
          f"({SR.seq_err_name(stt['err_code'])}) wall {wall:.3f}s")
    print(f"  tokens        {toks}")
    print(f"  S_PERF_CYC    {cyc} cycles = {dev_ms:.3f} ms device "
          f"@ {F/1e6:.0f} MHz;  S_PERF_REC {rec}")
    print(f"--- THE TWO LANES (SEQ_ISA v2.1 A1.4)")
    print(f"  L_LCYC        {lcyc} cycles = {lcyc / F * 1e3:.3f} ms "
          f"= {lcyc / F * 1e3 / ntok:.3f} ms/token   (compute lane, busy_cmp)")
    print(f"  L_SDMA_CYC    {sdma} cycles = {sdma / F * 1e3:.3f} ms "
          f"= {sdma / F * 1e3 / ntok:.3f} ms/token   (DMA lane, busy_dma)")
    print(f"  sum of lanes  {(lcyc + sdma) / F * 1e3:.3f} ms of "
          f"{dev_ms:.3f} ms device "
          f"({(lcyc + sdma) / max(cyc, 1) * 100:.1f} %)")
    print(f"--- per-channel matvec spread")
    tot = [m["cyc"] for m in mv]
    for m in mv:
        print(f"  matvec{m['chan']}      {m['cyc']} cycles "
              f"= {m['cyc'] / F * 1e3:.3f} ms, {m['beats']} beats "
              f"= {m['beats'] * 64 / 2**20:.1f} MiB")
    if max(tot) and min(tot):
        print(f"  spread        max/min = {max(tot) / min(tot):.4f} "
              f"({max(tot) - min(tot)} cycles = "
              f"{(max(tot) - min(tot)) / F * 1e3:.3f} ms)")
    print(f"--- the loop edges seen on chip (backward jumps of S_PC)")
    for i, t in enumerate(trace):
        d = t["cyc"] - trace[i - 1]["cyc"] if i else None
        print(f"  edge {i}: pc -> {t['pc']:>7}  S_PERF_CYC {t['cyc']:>12}"
              + (f"   delta {d} cycles = {d / F * 1e3:.3f} ms" if d else ""))
    steady = None
    if len(trace) >= 2:
        ds = [trace[i]["cyc"] - trace[i - 1]["cyc"]
              for i in range(1, len(trace))]
        steady = float(np.mean(ds)) / F * 1e3
        print(f"  loop iteration (steady-state step): mean "
              f"{steady:.3f} ms over {len(ds)} interval(s), "
              f"spread {min(ds)}..{max(ds)} cycles")
    print(f"--- BOTH CONVENTIONS (RD_GATE §1)")
    print(f"  gate         device/ntok = {dev_ms:.3f}/{ntok} = "
          f"{dev_ms / ntok:.4f} ms/token = {ntok / (dev_ms / 1e3):.4f} tok/s")
    if steady:
        pre = dev_ms - steady * art.meta["steps"]
        print(f"  steady-state one loop iteration = {steady:.4f} ms/token "
              f"= {1e3 / steady:.4f} tok/s")
        print(f"  the preamble it implies: {dev_ms:.3f} - "
              f"{steady:.4f}*{art.meta['steps']} = {pre:.3f} ms "
              f"(the 2B constant was 8.671 ms, and it was a 2B measurement)")
    rep = {"prefix": a.prefix, "version": hex(dev.ident["version"]),
           "tokens": toks, "ntok": ntok, "pc": pc,
           "err_code": stt["err_code"], "seq_perf_cyc": cyc,
           "seq_perf_rec": rec, "device_ms": dev_ms, "wall_s": wall,
           "aclk_hz": F, "l_lcyc": lcyc, "l_sdma_cyc": sdma,
           "l_lcyc_ms": lcyc / F * 1e3, "l_sdma_cyc_ms": sdma / F * 1e3,
           "matvec": mv, "loop_edges": trace,
           "steady_ms": steady,
           "gate_ms_per_tok": dev_ms / ntok,
           "gate_tok_s": ntok / (dev_ms / 1e3),
           "steady_tok_s": (1e3 / steady) if steady else None}
    want = SR.expected_tokens(art.meta)
    ok = (toks == want) and not stt["err_code"]
    rep["tokens_ok"] = (toks == want)
    print("  TOKENS " + ("IDENTICAL to the .seq.json"
                         if toks == want else f"MISMATCH want {want}"))
    if a.json:
        json.dump(rep, open(a.json, "w"), indent=1)
        print(f"  json -> {a.json}")
    del lk
    print("G6_CENSUS: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
