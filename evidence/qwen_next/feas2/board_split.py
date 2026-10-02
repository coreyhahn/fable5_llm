#!/usr/bin/env python3
"""board_split.py — per-BOARD, per-CHANNEL DDR fit for the two-board study,
plus the loader volume and the time to push it into a host-less board B.

Everything here is arithmetic on ddr_fit2.py's image lists and the shipped
allocator's packing law.  Nothing is measured; nothing runs on a board.

The three windows this checks against, all per CHANNEL:
  AS BUILT   1,280 MiB   EMB_BASE - W_BASE, a COMPILE-TIME constant on every
                         channel (sw/hwmap.py:483-486)
  RUNTIME    3,840 MiB   4,096 - 256 (W_BASE) on a channel with no embedding
                         table, if EMB_BASE became a per-channel runtime value
                         placed ABOVE the pack (docs/QWEN35_NEXT_FEASIBILITY.md 3.2)
  RUNTIME-E  4,096 - 256 - (the embedding table) on the channel that hosts it
"""
import os
import sys

ROOT = "/home/cah/r2d2/code/fpga/fable5_llm"
sys.path.insert(0, os.path.join(ROOT, "evidence/qwen_next/feas2"))
import ddr_fit2 as F                                           # noqa: E402

MIB, GIB = 2 ** 20, 2 ** 30
NCH = 4
CH = 4 * GIB
W_BASE_MIB = 256
WIN_BUILT = 1280 * MIB
WIN_RUNTIME = 3840 * MIB

# ---- LINK RATES.  Every one of these is an ASSUMPTION (label E) ----------
# QSFP28 = 4 lanes x 25.78125 Gb/s line rate.  64B/66B line coding is already
# inside that figure for both Aurora 64B/66B and 100G Ethernet, so the
# post-coding payload rate is 4 x 25.78125 x 64/66 = 100.0 Gb/s = 12.50 GB/s.
LANE_GBPS = 25.78125
LINK_PAYLOAD_GBs = 4 * LANE_GBPS * (64.0 / 66.0) / 8.0        # 12.50 GB/s
RATES = {
    "Aurora 64B/66B x4 (ideal payload)": LINK_PAYLOAD_GBs,
    "Aurora 64B/66B x4 @ 90 % of that": 0.90 * LINK_PAYLOAD_GBs,
    "100GbE CMAC x4, 9000 B jumbo UDP":
        LINK_PAYLOAD_GBs * (9000 - 8 - 20 - 8) / (9000 + 20 + 12),  # hdrs+IFG+prmbl
    "100GbE CMAC x4, 1500 B MTU UDP":
        LINK_PAYLOAD_GBs * (1500 - 8 - 20 - 8) / (1500 + 20 + 12),
    "Aurora 64B/66B x1 lane": LINK_PAYLOAD_GBs / 4,
    "10GbE SFP+ (snoke's 82599), 1500 B UDP":
        10.0 * (64.0 / 66.0) / 8.0 * (1500 - 8 - 20 - 8) / (1500 + 20 + 12),
}


def hdr(s):
    print()
    print("=" * 78)
    print(s)
    print("=" * 78)


def pack_images(name, plan, ims, nch=NCH):
    """per-channel packed bytes for a SUBSET of images, the allocator's law."""
    tot = [0] * nch
    for im in ims:
        stride = F.stride_of(im["k"], plan[im["cls"]])
        pieces = (F.B.ilv_chunks(im["nrows"], nch) if (im["amax"] and nch > 1)
                  else [(c, r0, n) for c, (r0, n)
                        in enumerate(F.B.split_rows(im["nrows"], nch))])
        for (c, _r0, n) in pieces:
            if n:
                sz = n * stride
                tot[c] += -(-sz // F.HW.WID_ALIGN) * F.HW.WID_ALIGN
    return tot


def stream_images(name, plan, ims, active=True):
    tot = 0
    cfg = F.CFG[name]
    for im in ims:
        rows = im["nrows"]
        if active and F.IS_MOE[name] and im.get("tag") == "routed":
            rows = rows * cfg["num_experts_per_tok"] // cfg["num_experts"]
        tot += rows * F.stride_of(im["k"], plan[im["cls"]])
    return tot


def layer_range(name, lo, hi):
    out = []
    for im in F.inv_for(name):
        n = im["name"]
        if n.startswith("layers.") and lo <= int(n.split(".")[1]) < hi:
            out.append(im)
    return out


def verdict(chans, emb_bytes_on_ch0):
    """PASS/FAIL against the three windows, worst channel."""
    worst = max(chans)
    e = chans[0] + emb_bytes_on_ch0
    win_e = 4 * GIB - W_BASE_MIB * MIB - emb_bytes_on_ch0
    return (worst <= WIN_BUILT, worst <= WIN_RUNTIME,
            chans[0] <= win_e and max(chans[1:]) <= WIN_RUNTIME,
            worst, win_e, e)


if __name__ == "__main__":
    hdr("PER-BOARD, PER-CHANNEL FOOTPRINT — every model x map x split")
    print("cols: the four channels' PACKED MiB, then the worst against the")
    print("      as-built 1280 MiB window and the runtime 3840 MiB one.")
    print("      The last column is CHANNEL 0's weight room under a per-channel")
    print("      runtime EMB_BASE: 4096 - 256 (W_BASE) - (the embedding table).")
    print("      A NEGATIVE ceiling means the table alone does not fit the")
    print("      channel beside W_BASE, before one weight byte is placed.")

    for name in ("27B", "35B-A3B"):
        NL = F.CFG[name]["num_hidden_layers"]
        cut = NL // 2
        for mp in ("all:w4g128", "all:w8g128"):
            plan = F.plan_for(mp)
            _, pow2row, nat_tbl, pad_tbl, lg = F.emb(name)
            head = [im for im in F.inv_for(name) if im["cls"] == "lm_head"]
            mix = [im for im in F.inv_for(name)
                   if im["cls"] not in ("lm_head",)]
            print(f"\n### {name}  {mp}   (emb table padded {pad_tbl/MIB:.0f} MiB,"
                  f" EMBLOG2 {lg})")

            splits = []
            fa = layer_range(name, 0, cut)
            fb = layer_range(name, cut, NL)
            splits.append(("PIPE cut@%d, head on B" % cut, fa, fb + head))
            splits.append(("PIPE cut@%d, head on A" % cut, fa + head, fb))
            if not F.IS_MOE[name]:
                splits.append(("TENSOR-PAR (half the rows each)", None, None))
            else:
                routed = [im for im in F.inv_for(name)
                          if im.get("tag") == "routed"]
                rest = [im for im in F.inv_for(name)
                        if im.get("tag") != "routed" and im["cls"] != "lm_head"]
                splits.append(("EXPERT-PAR, mixers replicated, head on B",
                               None, None))

            for label, ia, ib in splits:
                if ia is not None:
                    ca, cb = pack_images(name, plan, ia), pack_images(name, plan, ib)
                elif "TENSOR" in label:
                    whole = pack_images(name, plan, mix + head)
                    ca = [x / 2.0 for x in whole]
                    cb = list(ca)
                else:   # expert-parallel
                    routed = [im for im in F.inv_for(name)
                              if im.get("tag") == "routed"]
                    rest = [im for im in F.inv_for(name)
                            if im.get("tag") != "routed" and im["cls"] != "lm_head"]
                    cr = pack_images(name, plan, routed)
                    cx = pack_images(name, plan, rest)
                    chd = pack_images(name, plan, head)
                    ca = [cr[i] / 2.0 + cx[i] for i in range(NCH)]
                    cb = [cr[i] / 2.0 + cx[i] + chd[i] for i in range(NCH)]
                for who, c in (("A", ca), ("B", cb)):
                    embt = pad_tbl if who == "A" else 0
                    b1, b2, b3, worst, win_e, ch0 = verdict(c, embt)
                    print(f"  {label:42s} {who}  "
                          + " ".join(f"{x/MIB:8.1f}" for x in c)
                          + f"  | tot {sum(c)/GIB:6.3f} GiB"
                          + f"  worst {worst/MIB:7.1f} MiB"
                          + f"  1280:{'PASS' if b1 else 'FAIL'}"
                          + f"  3840:{'PASS' if b2 else 'FAIL'}"
                          + (f"  | ch0 weights {c[0]/MIB:7.1f} MiB of the"
                             f" {win_e/MIB:7.1f} MiB left under the"
                             f" {embt/MIB:.0f} MiB table: "
                             f"{'PASS' if b3 else 'FAIL'}" if embt else ""))

    hdr("THE 27B's EMBEDDING ROW — the one number that decides ONE board vs TWO")
    plan = F.plan_for("all:w4g128")
    fp = sum(F.footprint("27B", plan))
    nat, pow2row, nat_tbl, pad_tbl, lg = F.emb("27B")
    print(f"  27B W4 g128 weight pack            {fp/GIB:7.3f} GiB")
    print(f"  embedding, NATURAL row {nat} B    {nat_tbl/GIB:7.3f} GiB "
          f"-> total {(fp+nat_tbl)/GIB:7.3f} GiB of 16.000  "
          f"({100.0*(fp+nat_tbl)/(4*CH):.1f} %)  "
          f"{'FITS' if fp+nat_tbl <= 4*CH else 'OVER'}")
    print(f"  embedding, PADDED  row {pow2row} B   {pad_tbl/GIB:7.3f} GiB "
          f"-> total {(fp+pad_tbl)/GIB:7.3f} GiB of 16.000  "
          f"({100.0*(fp+pad_tbl)/(4*CH):.1f} %)  "
          f"{'FITS' if fp+pad_tbl <= 4*CH else 'OVER'}")
    print(f"  the padding costs {(pad_tbl-nat_tbl)/MIB:.0f} MiB and the overflow "
          f"is {(fp+pad_tbl-4*CH)/MIB:.0f} MiB — "
          "so the 27B's one-board verdict turns entirely on EMBLOG2.")
    print(f"  NOTE the padded row needs EMBLOG2 = {lg}, one MORE than the 13 the")
    print("  shipped 9B uses (NEXT_SESSION.md 1).")

    hdr("THE LOADER — GiB to push into a host-less board B, and how long")
    print("Board B has POWER ONLY: no PCIe, no XDMA, no BAR.  Everything below")
    print("crosses the QSFP28 link once per model load (E: rates assumed, see")
    print("the RATES table; no link has been built or measured).")
    print()
    print("assumed payload rates (GB/s, 1 GB = 1e9 B):")
    for k, v in RATES.items():
        print(f"   {k:44s} {v:8.3f}")
    print()
    print(f"{'model':9s} {'map':10s} {'split':34s} {'B-side GiB':>11s}"
          + "".join(f"{n.split(' ')[0][:9]:>11s}" for n in RATES))
    for name in ("27B", "35B-A3B"):
        NL = F.CFG[name]["num_hidden_layers"]
        cut = NL // 2
        for mp in ("all:w4g128",):
            plan = F.plan_for(mp)
            head = [im for im in F.inv_for(name) if im["cls"] == "lm_head"]
            cases = []
            cases.append(("PIPE cut@%d, head on B" % cut,
                          sum(pack_images(name, plan,
                                          layer_range(name, cut, NL) + head))))
            if not F.IS_MOE[name]:
                mix = [im for im in F.inv_for(name)]
                cases.append(("TENSOR-PAR (half the rows)",
                              sum(pack_images(name, plan, mix)) / 2.0))
            else:
                routed = [im for im in F.inv_for(name)
                          if im.get("tag") == "routed"]
                rest = [im for im in F.inv_for(name)
                        if im.get("tag") != "routed" and im["cls"] != "lm_head"]
                cases.append(("EXPERT-PAR, mixers replicated + head",
                              sum(pack_images(name, plan, routed)) / 2.0
                              + sum(pack_images(name, plan, rest))
                              + sum(pack_images(name, plan, head))))
            for lbl, by in cases:
                row = f"{name:9s} {mp:10s} {lbl:34s} {by/GIB:11.3f}"
                for k, v in RATES.items():
                    row += f"{by/1e9/v:10.1f}s"
                print(row)
    print()
    print("  Plus the SEQ stream, the const blob and the initial state region,")
    print("  which are small beside the weights but must cross the same link:")
    print("  the shipped 9B's stream is 158,536 records at 0x9000000 and its")
    print("  const blob is 8,940,032 B (NEXT_SESSION.md 1).")

    hdr("THE STATE REGION per board — DN / KV / conv at the new geometries")
    print("The shipped law (docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md 2):")
    print("  DN   n_DN layers x LNVH heads x 128 rows x 256 B, stride 32 KiB per head")
    print("  KV   n_GQA x NKV x {K,V}, stride 2 MiB per block (1 MiB data + exps)")
    print("  CV   n_DN layers x 128 KiB")
    for name in ("9B", "27B", "35B-A3B"):
        cfg = F.CFG[name]
        d = F.B.geometry({**cfg, "intermediate_size": cfg["intermediate_size"] or 0})
        ndn = d["TYPES"].count("linear_attention")
        nga = d["TYPES"].count("full_attention")
        for T in (512, 4096):
            dn = ndn * d["LNH"] * 32 * 1024
            kv = nga * d["NKV"] * 2 * 2 * MIB
            cv = ndn * 128 * 1024
            # per-token DDR traffic: DN read+write every layer, CV likewise,
            # KV read T rows + write T rows per kvhead per attention layer
            tr_dn = 2 * ndn * d["LNH"] * 128 * 256
            tr_cv = 2 * ndn * 8192 * 16
            tr_kv = 2 * nga * d["NKV"] * 2 * T * 256
            print(f"  {name:8s} T={T:5d}  region DN {dn/MIB:8.2f} + KV "
                  f"{kv/MIB:8.2f} + CV {cv/MIB:6.2f} = {(dn+kv+cv)/MIB:9.2f} MiB"
                  f"   traffic/token {(tr_dn+tr_cv+tr_kv)/MIB:8.2f} MiB")
    print("  (the 9B T=512 traffic row must read 70.06 MiB — RD9_GATE 10.3 —")
    print("   and the T=4096 row 182.50 MiB.)")
