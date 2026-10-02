#!/usr/bin/env python3
"""addrmap_options.py — what the "does not fit" verdicts actually cost to fix.

Two verdicts from ddr_fit.py need unpacking rather than reporting:

  * 9B at W8 g128 is refused at 150.6 % of the per-channel weight WINDOW —
    but the window is `EMB_BASE - W_BASE`, and EMB_BASE is a HOST constant
    (sw/hwmap.py:486).  The hardware takes the embedding base from the EMB
    record itself (rtl/seq_unit.sv:934-935: `emb_a = {r_tgt, r_imm} +
    (xrf[3] << emb_row_log2)`), so moving it is host/emitter work, which is
    exactly what plan_weights' own assert message says
    (sw/hwmap.py:754: "move EMB_BASE or split the images across DDR channels").
    The real question is the CAPACITY question: 4 x 4 GiB = 16 GiB total.

  * 4B's 5,120 B embedding row is rejected by seq_emb_log2 because the
    hardware addresses rows with a SHIFT.  This enumerates the options.

Nothing here is a proposal.  It is the arithmetic a decision needs.
"""
import json
import os
import sys

ROOT = "/home/cah/r2d2/code/fpga/fable5_llm"
sys.path.insert(0, os.path.join(ROOT, "sw"))
sys.path.insert(0, os.path.join(ROOT, "ref"))
sys.path.insert(0, os.path.join(ROOT, "ref", "scripts"))
sys.path.insert(0, os.path.join(ROOT, "evidence/qwen_next/feas"))
os.environ.setdefault("FABLE5_MODEL", "2b")

import bytes_per_token as B                                    # noqa: E402
import hwmap as HW                                             # noqa: E402
from ddr_fit import cfg_for, MODELS                            # noqa: E402
from toks_model import counters, plan_of, movers_ms, matvec_ms, layer_ms, \
    fit_layer, MEAS, UI                                        # noqa: E402

MiB = 2 ** 20
CH = HW.CH_STRIDE // MiB                     # 4096 MiB per channel
SEQ_TOP = (HW.SEQ_DATA_BASE + (64 << 20)) // MiB if hasattr(HW, "SEQ_DATA_BASE") \
    else 256                                 # everything below W_BASE
WBASE = HW.W_BASE // MiB                     # 256 MiB


def emb_bytes(H, row):
    return 248320 * row


if __name__ == "__main__":
    A, Bv, _, _ = fit_layer()

    print("=" * 78)
    print("1. THE CAPACITY QUESTION — is 16 GiB enough at all?")
    print("=" * 78)
    print(f"    channel {CH} MiB x 4 = {4*CH} MiB total; everything below "
          f"W_BASE = {WBASE} MiB/chan is SEQ stream + LDC blob + slack")
    print(f"    {'model':6s} {'map':11s} {'weights MiB':>12s} {'emb MiB':>9s} "
          f"{'sum MiB':>9s} {'of 16 GiB':>10s}")
    for name, mapspec, embrow in (("2B", "all:w8g128", 4096),
                                  ("4B", "all:w8g128", 8192),
                                  ("4B", "all:w4g128", 8192),
                                  ("9B", "all:w8g128", 8192),
                                  ("9B", "all:w4g128", 8192)):
        cfg = cfg_for(*MODELS[name])
        c = counters(cfg, plan_of(mapspec))
        w = c["total_bytes"] / MiB
        e = emb_bytes(cfg["hidden_size"], embrow) / MiB
        print(f"    {name:6s} {mapspec:11s} {w:12.1f} {e:9.1f} {w+e:9.1f} "
              f"{100*(w+e)/(4*CH):9.1f} %")
    print("    -> capacity is never the binding constraint; the ADDRESS MAP is.")

    print()
    print("=" * 78)
    print("2. 9B AT W8 — what a runtime EMB_BASE would buy")
    print("=" * 78)
    cfg9 = cfg_for(*MODELS["9B"])
    c9 = counters(cfg9, plan_of("all:w8g128"))
    tot = c9["total_bytes"] / MiB
    bal = tot / 4
    e9 = emb_bytes(4096, 8192) / MiB
    print(f"    9B W8 weights {tot:.1f} MiB, embedding table {e9:.1f} MiB")
    print(f"    balanced split = {bal:.1f} MiB/chan; today's busiest is "
          f"{c9['busiest_bytes']/MiB:.1f} MiB (the row split is slightly uneven)")
    print()
    print("    OPTION A — today's map: window = EMB_BASE - W_BASE = "
          f"{(HW.EMB_BASE-HW.W_BASE)/MiB:.0f} MiB on EVERY channel")
    print(f"      need {bal:.1f} MiB/chan, have {(HW.EMB_BASE-HW.W_BASE)/MiB:.0f} "
          f"-> REFUSED ({100*bal/((HW.EMB_BASE-HW.W_BASE)/MiB):.1f} %)")
    print()
    print("    OPTION B — EMB_BASE becomes a per-channel runtime value placed")
    print("      ABOVE the weight pack.  Only the channel that hosts the table")
    print("      is constrained; the other three run to the top of their 4 GiB.")
    cap_emb_chan = CH - WBASE - e9          # weights allowed on the emb channel
    cap_other = CH - WBASE
    print(f"      emb-hosting channel: {cap_emb_chan:.1f} MiB of weights allowed")
    print(f"      other three:         {cap_other:.1f} MiB each")
    if bal <= cap_emb_chan:
        print(f"      balanced {bal:.1f} MiB/chan fits ALL FOUR -> no asymmetry needed")
        busiest_B = bal
    else:
        busiest_B = (tot - cap_emb_chan) / 3
        print(f"      balanced {bal:.1f} > {cap_emb_chan:.1f}: cap the emb channel "
              f"and spread the rest -> busiest {busiest_B:.1f} MiB")
    pen = busiest_B / (c9["busiest_bytes"] / MiB)
    print(f"      matvec-term penalty vs today's split: x{pen:.4f}")
    print()
    print("    OPTION C — keep EMB_BASE fixed, split the images asymmetrically")
    cap_c = (HW.EMB_BASE - HW.W_BASE) / MiB
    busiest_C = (tot - cap_c) / 3
    print(f"      ch0 capped at {cap_c:.0f} MiB, other three {busiest_C:.1f} MiB "
          f"each -> but {busiest_C:.1f} > {cap_c:.0f}, still REFUSED by the same "
          "assert (it is per-channel and uniform)")
    print()
    print("    Throughput of option B, against the balanced model:")
    for lab, scale in (("today's split (does not fit)", 1.0),
                       ("option B", pen)):
        mv = matvec_ms(c9, 1.1037) * scale
        mo = movers_ms(c9) * 0.9117
        lo = layer_ms(cfg9, A, Bv, False)
        hi = layer_ms(cfg9, A, Bv, True)
        print(f"      {lab:30s} matvec {mv:7.2f}  step {mv+mo+lo:7.2f}.."
              f"{mv+mo+hi:7.2f} ms  {1000/(mv+mo+hi):5.2f}..{1000/(mv+mo+lo):5.2f} tok/s")

    print()
    print("=" * 78)
    print("3. 4B's 5,120-BYTE EMBEDDING ROW — the options, costed")
    print("=" * 78)
    V = 248320
    packed, padded = 5120, 8192
    print(f"    vocab {V:,}; packed row 2*H = {packed} B; next power of two {padded} B")
    print()
    print(f"    (a) PAD to {padded} B      table {V*padded/MiB:.1f} MiB "
          f"(+{V*(padded-packed)/MiB:.1f} MiB, +{100*(padded-packed)/packed:.0f} %), "
          f"EMBLOG2 = 13")
    print(f"        RTL delta NONE. Host delta: gen_model_script writes padded "
          f"rows; manifest emb_row_bytes = {padded}.")
    print(f"        Channel-0 budget: W_BASE {WBASE} + weights + table "
          f"{V*padded/MiB:.1f} MiB")
    for mapspec in ("all:w8g128", "all:w4g128"):
        c4 = counters(cfg_for(*MODELS["4B"]), plan_of(mapspec))
        used = WBASE + c4["busiest_bytes"] / MiB + V * padded / MiB
        print(f"          {mapspec:11s} -> {used:.1f} MiB of {CH} "
              f"({100*used/CH:.1f} %)  {'FITS' if used <= CH else 'OVER'}")
    print()
    print(f"    (b) NON-POWER-OF-TWO row addressing in RTL")
    print(f"        {packed} = 4096 + 1024 = (x<<12) + (x<<10): a TWO-TERM shift-add,")
    print(f"        not a general multiplier.  rtl/seq_unit.sv:934-935 today is")
    print(f"        one shift and one add; this makes it two shifts and two adds.")
    print(f"        Saves {V*(padded-packed)/MiB:.1f} MiB of DDR that the channel "
          f"demonstrably has (see (a)).")
    print(f"        COST: it lands in the SEQ MOV/EMB address path, which is one")
    print(f"        of the three classes that carried waived endpoints on")
    print(f"        build_034 (evidence/qwen2b/rb/TIMING.md: seq_0 MOV addressing,")
    print(f"        3 endpoints).  build_035 closes at WNS 0.000 with ZERO margin")
    print(f"        (RD_GATE 6), so any added logic there re-opens timing.")
    print(f"        Also needs the EMBLOG2 CSR to become a row-BYTES field or a")
    print(f"        2-term encoding; today it is a 4-bit log2 with range [8,13].")
    print()
    print(f"    (c) NARROW the embedding to int8       row {2560} B — still not a")
    print(f"        power of two, so it does not avoid (b); and it is a fidelity")
    print(f"        change, which this study has no measurement for.")
    print()
    print(f"    VERDICT ARITHMETIC: (a) costs {V*(padded-packed)/MiB:.1f} MiB of a "
          f"channel that ends up {100*(WBASE + counters(cfg_for(*MODELS['4B']), plan_of('all:w8g128'))['busiest_bytes']/MiB + V*padded/MiB)/CH:.0f} % full at W8;")
    print(f"    (b) costs new logic in a zero-margin timing path.  (a) is the")
    print(f"    cheap one unless the channel budget tightens.")

    print()
    print("=" * 78)
    print("4. EMBLOG2 HEADROOM")
    print("=" * 78)
    print(f"    sw/hwmap.py:343  SEQ_EMBLOG2_MIN, SEQ_EMBLOG2_MAX = "
          f"{HW.SEQ_EMBLOG2_MIN}, {HW.SEQ_EMBLOG2_MAX}")
    for name, H in (("0.8B", 1024), ("2B", 2048), ("4B", 2560), ("9B", 4096)):
        row = 2 * H
        pad = 1 << (row - 1).bit_length()
        print(f"    {name:5s} H={H:5d} row {row:6d} B  padded {pad:6d} B  "
              f"EMBLOG2 {pad.bit_length()-1:2d}  "
              f"{'AT THE CEILING' if pad.bit_length()-1 == HW.SEQ_EMBLOG2_MAX else 'ok'}")
    print("    -> BOTH targets land on EMBLOG2 13, the maximum the CSR encodes.")
    print("       Any future model with H > 4096 needs the field widened even if")
    print("       its row size is a clean power of two.")
