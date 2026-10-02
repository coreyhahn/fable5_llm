#!/usr/bin/env python3
"""ddr_fit2.py — DDR fit for the TWO-BOARD study: Qwen3.5-27B and -35B-A3B.

A NEW script, not an edit of evidence/qwen_next/feas/ddr_fit.py (the committed
4B/9B study's logs cite that file by line).  What is different here:

 1. **The LKD workaround is GONE, because the bug it worked around is FIXED.**
    ddr_fit.py passed `linear_key_head_dim = (LNKH*LDK)//LNVH` to route around
    `bytes_per_token.geometry`'s `LKD = LNVH * LDK`.  At HEAD that function
    reads `LKD = LNKH * cfg["linear_key_head_dim"]`
    (ref/scripts/bytes_per_token.py:131), so this script passes the TRUE
    config values and CHECKS the derived CONV_DIM against the checkpoint's own
    conv1d tensor.  Re-using ddr_fit.py unchanged at HEAD would now be wrong.

 2. **An MoE inventory.**  `bytes_per_token.inventory` builds a dense
    gate/up/down triple per layer from `intermediate_size`, and the 35B-A3B has
    no `intermediate_size` at all.  `moe_inventory` below replaces it, keyed off
    the checkpoint's FUSED expert tensors: one image for all 256 experts'
    gate_up (256*1024 rows x 2048) and one for their down (256*2048 rows x 512),
    plus the shared expert's three, plus the router.  It is installed by
    monkeypatching `B.inventory`, so `fit`, `packed_footprint` and
    `per_channel_bytes` — the shipped allocator and this project's own
    re-implementation of the split — run UNCHANGED over it.

 3. **Footprint and stream are separated for the MoE.**  A dense model streams
    its whole pack every token; the MoE streams `num_experts_per_tok` of 256.
    `stream_bytes()` takes an `active` flag and the two numbers are never added.

VALIDATION, before any new number: the shipped 9B W4 g128 pack must reproduce
  4,091,805,696 B/token and the per-channel 978.40 / 975.30 / 974.27 / 974.27
  MiB that `evidence/qwen9b/g6/RD9_GATE.md` 10.3 transcribes off the board's
  own plan.  If it does not, this script fails and prints nothing else.
"""
import json
import os
import sys

ROOT = "/home/cah/r2d2/code/fpga/fable5_llm"
sys.path.insert(0, os.path.join(ROOT, "sw"))
sys.path.insert(0, os.path.join(ROOT, "ref"))
sys.path.insert(0, os.path.join(ROOT, "ref", "scripts"))
os.environ.setdefault("FABLE5_MODEL", "9b")

import bytes_per_token as B                                    # noqa: E402
import hwmap as HW                                             # noqa: E402
import w4a8_ref as W                                           # noqa: E402

GEOM = json.load(open(os.path.join(ROOT,
                                   "evidence/qwen_next/feas2/geometry2_raw.json")))
MIB = 2 ** 20
GIB = 2 ** 30
CH_BYTES = 4 * GIB          # one DDR4 channel on the BCU-1525 (4 GB UDIMM)
NCH = 4
WINDOW_BUILT = HW.EMB_BASE - HW.W_BASE      # 1,280 MiB, compile-time, per chan


# ---------------------------------------------------------------- configs
def cfg_dense(hidden, ffn, nlayers, nq, nkv, hd, lnvh, lnkh, ldk, ldv, vocab,
              interval=4):
    types = ["full_attention" if (i % interval) == (interval - 1)
             else "linear_attention" for i in range(nlayers)]
    return {"hidden_size": hidden, "intermediate_size": ffn,
            "num_hidden_layers": nlayers, "layer_types": types,
            "num_attention_heads": nq, "num_key_value_heads": nkv,
            "head_dim": hd, "linear_num_value_heads": lnvh,
            "linear_num_key_heads": lnkh,
            "linear_key_head_dim": ldk, "linear_value_head_dim": ldv,
            "vocab_size": vocab}


#                       H    FFN  NL  NQ NKV  HD LNVH LNKH LDK LDV   VOCAB
CFG = {
    "9B":  cfg_dense(4096, 12288, 32, 16, 4, 256, 32, 16, 128, 128, 248320),
    "27B": cfg_dense(5120, 17408, 64, 24, 4, 256, 48, 16, 128, 128, 248320),
}
# the MoE: no intermediate_size at all; the expert dims come from the tensors
MOE = dict(cfg_dense(2048, None, 40, 16, 2, 256, 32, 16, 128, 128, 248320))
MOE.update(num_experts=256, num_experts_per_tok=8, moe_intermediate_size=512,
           shared_expert_intermediate_size=512)
CFG["35B-A3B"] = MOE
REPO = {"9B": "Qwen/Qwen3.5-9B", "27B": "Qwen/Qwen3.5-27B",
        "35B-A3B": "Qwen/Qwen3.5-35B-A3B"}
IS_MOE = {"9B": False, "27B": False, "35B-A3B": True}

_dense_inventory = B.inventory


def moe_inventory(cfg):
    """The 35B-A3B's image list, from the checkpoint's FUSED expert tensors.

    `mlp.experts.gate_up_proj` is [E, 2*mff, H] and `mlp.experts.down_proj` is
    [E, H, mff] — ONE tensor each, all experts stacked.  The natural DDR image
    is therefore one image per layer per side, with the expert index becoming a
    ROW RANGE inside it: expert e owns rows [e*2*mff, (e+1)*2*mff) of gate_up
    and [e*H, (e+1)*H) of down.  That is what makes expert gather a row-offset
    problem rather than an image-selection problem, and it is why this
    inventory is built this way rather than as 256 separate images.
    """
    d = B.geometry({**cfg, "intermediate_size": 0})
    H, VOCAB = d["H"], d["VOCAB"]
    E = cfg["num_experts"]
    mff = cfg["moe_intermediate_size"]
    sff = cfg["shared_expert_intermediate_size"]
    img = []

    def add(cls, name, nrows, k, amax=False, tag=None):
        img.append({"cls": cls, "name": name, "nrows": int(nrows), "k": int(k),
                    "amax": amax, "tag": tag})

    for i, t in enumerate(d["TYPES"]):
        p = f"layers.{i}."
        # the 256 routed experts, fused
        add("gate_up", p + "mlp.experts.gate_up", E * 2 * mff, H, tag="routed")
        add("down", p + "mlp.experts.down", E * H, mff, tag="routed")
        # the one shared expert, always active
        add("gate_up", p + "mlp.shared.gate", sff, H, tag="shared")
        add("gate_up", p + "mlp.shared.up", sff, H, tag="shared")
        add("down", p + "mlp.shared.down", H, sff, tag="shared")
        # the router: E scores from H — a [E, H] matrix, always active
        add("router", p + "mlp.gate", E, H, tag="router")
        if t == "linear_attention":
            add("dn_in", p + "dn.in_qkv", d["CONV_DIM"], H)
            add("dn_in", p + "dn.in_z", d["LVD"], H)
            add("dn_in", p + "dn.in_b", d["LNH"], H)
            add("dn_in", p + "dn.in_a", d["LNH"], H)
            add("dn_out", p + "dn.out", H, d["LVD"])
        else:
            add("qkv", p + "attn.q_proj", 2 * d["NQ"] * d["HD"], H)
            add("qkv", p + "attn.k_proj", d["NKV"] * d["HD"], H)
            add("qkv", p + "attn.v_proj", d["NKV"] * d["HD"], H)
            add("o_proj", p + "attn.o_proj", H, d["NQ"] * d["HD"])
    add("lm_head", "lm_head", VOCAB, H, amax=True)
    return img


def inv_for(name):
    cfg = CFG[name]
    return moe_inventory(cfg) if IS_MOE[name] else _dense_inventory(cfg)


def plan_for(spec, router_quant="w8g128"):
    plan = B.parse_map(spec)[0]
    plan["router"] = router_quant       # the router is NOT a W4A8 class
    return plan


def stride_of(k, quant):
    return B.image_bytes(1, k, quant)


def stream_bytes(name, plan, active=True):
    """Bytes read from DDR for ONE token.  For the MoE with active=True the
    routed-expert images contribute only `num_experts_per_tok` experts' rows."""
    cfg = CFG[name]
    tot = 0
    for im in inv_for(name):
        rows = im["nrows"]
        if active and IS_MOE[name] and im.get("tag") == "routed":
            rows = rows * cfg["num_experts_per_tok"] // cfg["num_experts"]
        tot += rows * stride_of(im["k"], plan[im["cls"]])
    return tot


def footprint(name, plan, nch=NCH):
    """Bytes RESERVED per channel under sw/hwmap.py:plan_weights' packing law
    (images back to back from W_BASE, each start rounded up to WID_ALIGN),
    using this project's own re-implementation `packed_footprint`."""
    B.inventory = (lambda cfg: inv_for(name))
    try:
        return B.packed_footprint(CFG[name], plan, nch)
    finally:
        B.inventory = _dense_inventory


def per_channel_stream(name, plan, nch=NCH):
    B.inventory = (lambda cfg: inv_for(name))
    try:
        return B.per_channel_bytes(CFG[name], plan, nch)
    finally:
        B.inventory = _dense_inventory


def emb(name):
    """The embedding table: H int16 per row, and the row stride the EMBLOG2
    CSR can express (a power of two, `rtl/seq_unit.sv`'s shift)."""
    H = CFG[name]["hidden_size"]
    V = CFG[name]["vocab_size"]
    nat = 2 * H
    log2 = nat.bit_length() - 1
    pow2 = (1 << log2) if (1 << log2) == nat else (1 << (log2 + 1))
    return nat, pow2, V * nat, V * pow2, (pow2.bit_length() - 1)


MAPS = ["all:w8g128", "all:w4g128", "all:w4g64"]


def hdr(s):
    print()
    print("=" * 78)
    print(s)
    print("=" * 78)


# ====================================================================== main
if __name__ == "__main__":
    hdr("VALIDATION 1 — the SHIPPED 9B W4 g128 pack, reproduced")
    plan = plan_for("all:w4g128")
    got = stream_bytes("9B", plan, active=False)
    WANT_TOK = 4_091_805_696
    WANT_CH = [1_025_925_120, 1_022_681_088, 1_021_599_744, 1_021_599_744]
    ch = per_channel_stream("9B", plan)
    print(f"  bytes/token   {got:,}   want {WANT_TOK:,}   "
          f"{'OK' if got == WANT_TOK else '*** MISMATCH ***'}")
    print(f"                {got/MIB:.2f} MiB  (RD9_GATE 10.3 total 3,902.25 MiB)")
    for c in range(NCH):
        print(f"  chan {c}        {ch[c]:,} = {ch[c]/MIB:8.2f} MiB   "
              f"want {WANT_CH[c]:,} = {WANT_CH[c]/MIB:8.2f} MiB   "
              f"{'OK' if ch[c] == WANT_CH[c] else '*** MISMATCH ***'}")
    assert got == WANT_TOK and ch == WANT_CH, \
        "the 9B anchor does not reproduce — every number below would be suspect"
    print("  max/min       %.6f  (RD9_GATE 10.3: 1.004234)" % (max(ch) / min(ch)))

    hdr("VALIDATION 2 — every image list vs the checkpoint's own tensors")
    for name in ("9B", "27B", "35B-A3B"):
        d = GEOM[REPO[name]]
        reps = d["representative_tensors"]
        cd = B.geometry({**CFG[name], "intermediate_size":
                         CFG[name]["intermediate_size"] or 0})
        conv = reps["model.language_model.layers.0.linear_attn.conv1d.weight"]["shape"][0]
        ok = cd["CONV_DIM"] == conv
        print(f"  {name:8s} derived CONV_DIM {cd['CONV_DIM']:6d}  checkpoint "
              f"conv1d rows {conv:6d}  {'OK' if ok else '*** MISMATCH ***'}")
        assert ok
        tot = sum(im["nrows"] * im["k"] for im in inv_for(name))
        census = d["by_prefix"]["model.language_model"]["params"] + \
            d["by_prefix"]["lm_head"]["params"]
        print(f"           image list {tot:>15,} params vs checkpoint "
              f"(text+head) {census:>15,}   ratio {tot/census:.6f}")
        print(f"           images {len(inv_for(name)):d}")

    hdr("STREAMED BYTES PER TOKEN, and the FOOTPRINT — ONE BOARD, nch=4")
    print(f"{'model':9s} {'map':10s} {'images':>7s} {'B/token':>17s} "
          f"{'MiB/tok':>10s} {'b/w':>6s} {'pack MiB':>10s} "
          f"{'busiest ch':>11s} {'% 1280':>8s} {'% 3840':>8s}")
    rows = {}
    for name in ("9B", "27B", "35B-A3B"):
        for mp in MAPS:
            plan = plan_for(mp)
            st = stream_bytes(name, plan, active=True)
            fp = footprint(name, plan)
            nrows_k = sum(im["nrows"] * im["k"] for im in inv_for(name))
            bw = 8.0 * sum(im["nrows"] * stride_of(im["k"], plan[im["cls"]])
                           for im in inv_for(name)) / nrows_k
            rows[(name, mp)] = dict(stream=st, pack=sum(fp), chans=fp, bw=bw)
            print(f"{name:9s} {mp:10s} {len(inv_for(name)):7d} {st:>17,} "
                  f"{st/MIB:10.1f} {bw:6.3f} {sum(fp)/MIB:10.1f} "
                  f"{max(fp)/MIB:11.1f} {100.0*max(fp)/WINDOW_BUILT:8.1f} "
                  f"{100.0*max(fp)/(3840*MIB):8.1f}")
    print()
    print("  '% 1280' is the AS-BUILT per-channel weight window "
          f"(EMB_BASE-W_BASE = {WINDOW_BUILT/MIB:.0f} MiB, sw/hwmap.py:483-486).")
    print("  '% 3840' is the window a per-channel RUNTIME EmB_BASE would give on a")
    print("  channel with no embedding table (4096 - 256 MiB W_BASE) — "
          "docs/QWEN35_NEXT_FEASIBILITY.md 3.2.")

    hdr("THE EMBEDDING TABLE, and the EMBLOG2 row stride")
    print(f"{'model':9s} {'H':>6s} {'nat row B':>10s} {'pow2 row B':>11s} "
          f"{'EMBLOG2':>8s} {'nat MiB':>10s} {'padded MiB':>11s} {'waste MiB':>10s}")
    for name in ("9B", "27B", "35B-A3B"):
        nat, pw, tn, tp, lg = emb(name)
        print(f"{name:9s} {CFG[name]['hidden_size']:6d} {nat:10d} {pw:11d} "
              f"{lg:8d} {tn/MIB:10.1f} {tp/MIB:11.1f} {(tp-tn)/MIB:10.1f}")

    hdr("ONE BOARD: does the whole model fit 4 x 4 GiB = 16 GiB?")
    print(f"{'model':9s} {'map':10s} {'weights GiB':>12s} {'emb GiB':>9s} "
          f"{'total GiB':>10s} {'% of 16':>8s} {'verdict':>10s}")
    for name in ("9B", "27B", "35B-A3B"):
        _, _, _, tp, _ = emb(name)
        for mp in MAPS:
            r = rows[(name, mp)]
            tot = r["pack"] + tp
            print(f"{name:9s} {mp:10s} {r['pack']/GIB:12.3f} {tp/GIB:9.3f} "
                  f"{tot/GIB:10.3f} {100.0*tot/(4*CH_BYTES):8.1f} "
                  f"{'FITS' if tot <= 4*CH_BYTES else 'OVER':>10s}")

    hdr("TWO BOARDS — the three splits, per board")
    print("Board A keeps the PCIe host (XDMA) and the embedding table; board B")
    print("has power only.  'stream/tok' is what that board reads from its own")
    print("DDR for one token; the embedding table is a single row read, not a")
    print("stream, and is excluded from stream/tok exactly as it is on one board.")

    def layer_images(name, lo, hi):
        """images of layers [lo, hi), by name prefix."""
        out = []
        for im in inv_for(name):
            n = im["name"]
            if n.startswith("layers."):
                i = int(n.split(".")[1])
                if lo <= i < hi:
                    out.append(im)
        return out

    for name in ("27B", "35B-A3B"):
        NL = CFG[name]["num_hidden_layers"]
        for mp in ("all:w4g128", "all:w8g128"):
            plan = plan_for(mp)
            _, _, _, emb_pad, _ = emb(name)
            head = [im for im in inv_for(name) if im["cls"] == "lm_head"]

            def pack(ims):
                t = 0
                for im in ims:
                    for _c, (_r0, n) in enumerate(
                            B.split_rows(im["nrows"], NCH)):
                        if n:
                            sz = n * stride_of(im["k"], plan[im["cls"]])
                            t += -(-sz // HW.WID_ALIGN) * HW.WID_ALIGN
                return t

            def strm(ims):
                t = 0
                for im in ims:
                    rows_ = im["nrows"]
                    if IS_MOE[name] and im.get("tag") == "routed":
                        rows_ = rows_ * CFG[name]["num_experts_per_tok"] \
                            // CFG[name]["num_experts"]
                    t += rows_ * stride_of(im["k"], plan[im["cls"]])
                return t

            print(f"\n--- {name}  {mp}  ({NL} layers) ---")
            # PIPELINE: split at the midpoint, both orderings for the head
            cut = NL // 2
            fa, fb = layer_images(name, 0, cut), layer_images(name, cut, NL)
            for who, hd_ in (("A holds the head", "A"), ("B holds the head", "B")):
                pa = pack(fa) + emb_pad + (pack(head) if hd_ == "A" else 0)
                pb = pack(fb) + (pack(head) if hd_ == "B" else 0)
                sa = strm(fa) + (strm(head) if hd_ == "A" else 0)
                sb = strm(fb) + (strm(head) if hd_ == "B" else 0)
                print(f"  PIPELINE cut@{cut:2d}, {who:16s}  "
                      f"A {pa/GIB:6.3f} GiB / {sa/MIB:8.1f} MiB/tok   "
                      f"B {pb/GIB:6.3f} GiB / {sb/MIB:8.1f} MiB/tok   "
                      f"{'A OVER ' if pa > 4*CH_BYTES else ''}"
                      f"{'B OVER' if pb > 4*CH_BYTES else ''}")
            # TENSOR-PARALLEL (dense only): every image split by output rows
            if not IS_MOE[name]:
                allim = [im for im in inv_for(name) if im["cls"] != "lm_head"]
                half = pack(allim) / 2.0
                hh = pack(head) / 2.0
                sA = (strm(allim) + strm(head)) / 2.0
                print(f"  TENSOR-PAR (rows halved)              "
                      f"A {(half+hh+emb_pad)/GIB:6.3f} GiB / {sA/MIB:8.1f} MiB/tok   "
                      f"B {(half+hh)/GIB:6.3f} GiB / {sA/MIB:8.1f} MiB/tok")
            # EXPERT-PARALLEL (MoE only)
            else:
                routed = [im for im in inv_for(name) if im.get("tag") == "routed"]
                rest = [im for im in inv_for(name)
                        if im.get("tag") != "routed" and im["cls"] != "lm_head"]
                E = CFG[name]["num_experts"]
                k = CFG[name]["num_experts_per_tok"]
                pr = pack(routed) / 2.0          # 128 experts per board
                # expected active experts per board = k/2 if the router is
                # balanced; the WORST case is all k on one board
                s_bal = strm(routed) / 2.0
                s_worst = strm(routed)
                print(f"  EXPERT-PAR, mixers REPLICATED         "
                      f"A {(pr+pack(rest)+pack(head)+emb_pad)/GIB:6.3f} GiB   "
                      f"B {(pr+pack(rest))/GIB:6.3f} GiB")
                print(f"     per board routed stream/tok: balanced "
                      f"{s_bal/MIB:.1f} MiB (E/2 hold k/2={k//2}), "
                      f"worst case {s_worst/MIB:.1f} MiB (all {k} on one board)")
                print(f"     mixers+shared+router/tok {strm(rest)/MIB:.1f} MiB, "
                      f"head {strm(head)/MIB:.1f} MiB")
                print(f"  EXPERT-PAR, mixers SPLIT (TP on attn/DN)  "
                      f"A {(pr+pack(rest)/2+pack(head)/2+emb_pad)/GIB:6.3f} GiB   "
                      f"B {(pr+pack(rest)/2+pack(head)/2)/GIB:6.3f} GiB")

    hdr("DONE")
