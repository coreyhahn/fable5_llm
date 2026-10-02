#!/usr/bin/env python3
"""toks2_model.py — modelled tok/s for 27B and 35B-A3B, on ONE board and on TWO.

EXTENDS evidence/qwen_next/feas/toks_model.py; it does not replace it.  That
module is IMPORTED and its constants, its mover cost law, its counters, its
two-component layer proxy and its (r, m) solve are used unchanged.  What is
added here:

  * a THIRD silicon anchor.  When toks_model.py was written the 9B was a
    projection; it has since SHIPPED, and `evidence/qwen9b/g6/RD9_GATE.md`
    10.1/10.2 measured 137.1210 ms/token and a layer lane `L_LCYC` of 41.588
    ms/token.  Section A below scores the committed model against both.
  * the per-BOARD decomposition: the image list is partitioned by a split, and
    matvec / movers / layer are computed per board from that board's share.
  * the LINK term: transfers/token x (latency + bytes/rate).  EVERY link number
    is an ASSUMPTION (label E) — no link exists, nothing was measured, and the
    latency is given as a three-point bracket rather than a value.
  * the MoE: only `num_experts_per_tok` of 256 experts stream, and a routed
    image costs k MVGO records instead of one.

NOTHING HERE IS MEASURED ON TWO BOARDS.  There is one board in this lab.
"""
import json
import os
import sys

ROOT = "/home/cah/r2d2/code/fpga/fable5_llm"
for p in ("sw", "ref", "ref/scripts", "evidence/qwen_next/feas",
          "evidence/qwen_next/feas2"):
    sys.path.insert(0, os.path.join(ROOT, p))
os.environ.setdefault("FABLE5_MODEL", "9b")

import bytes_per_token as B                                    # noqa: E402
import toks_model as TM                                        # noqa: E402
import ddr_fit2 as F                                           # noqa: E402

MIB = 2 ** 20
NCH = TM.NCH
ACLK, UI, CHUNK_ROWS = TM.ACLK, TM.UI, TM.CHUNK_ROWS

# ---- the silicon anchors ------------------------------------------------
# RD_GATE.md 1/3 (0.8B, 2B) and RD9_GATE.md 10.1/10.2 (9B).  The 9B point is
# a DIFFERENT BITSTREAM and a different design — post state-spill, its layer
# state in DDR behind URAM caches — so it is used as a SCORE, not folded into
# the fit that produced A and Bv.  Saying otherwise would mix two machines.
MEAS9B = dict(step_gate=137.1210, step_steady=137.1413, layer=41.588,
              sdma=5.125, tok_s=7.2928,
              src="evidence/qwen9b/g6/RD9_GATE.md 10.1, 10.2")

# ---- LINK ASSUMPTIONS (label E, every one) ------------------------------
LANE_GBPS = 25.78125
LINK_GBs = 4 * LANE_GBPS * (64.0 / 66.0) / 8.0     # 12.50 GB/s post-64B/66B
LINK_RATES = {"x4 @100 % payload": LINK_GBs,
              "x4 @90 %": 0.90 * LINK_GBs,
              "x1 lane": LINK_GBs / 4}
LINK_LAT_US = (0.5, 1.0, 2.0)      # one-way, fabric->GT->fabric.  ASSUMED.
ACT_BYTES_PER_H = 2                # the residual is int16 Q8.7 (rs_f=7)
RED_BYTES_PER_H = 4                # a partial SUM before requantisation


# ---- the layer proxy, re-implemented because the COMMITTED script no longer
# ---- runs at HEAD ------------------------------------------------------
# evidence/qwen_next/feas/toks_model.py:201 calls ddr_fit.cfg_for, which emits
# no `linear_num_key_heads` key; ref/scripts/bytes_per_token.py:124 now REQUIRES
# it (the LKD fix).  So `toks_model.fit_layer()` raises KeyError at HEAD.  That
# file is NOT edited — its logs cite it by line — so the same arithmetic is
# restated here over configs that carry the true key-head count, and the result
# is ASSERTED against the committed A and Bv in evidence/qwen_next/feas/toks_model.json.
A_COMMITTED = 2.261123283318704e-06
BV_COMMITTED = 1.2744815668202769e-05


def layer_work2(cfg):
    """toks_model.layer_work's formula, over a config with TRUE key heads."""
    d = B.geometry({**cfg, "intermediate_size": cfg["intermediate_size"] or 0})
    H, FFN, L = d["H"], d["FFN"], d["NL"]
    LNVH = d["LNH"]
    LDV = d["LVD"] // LNVH
    LDK_TRUE = 128
    ndn = sum(1 for t in d["TYPES"] if t == "linear_attention")
    inv = ndn * (LNVH * LDK_TRUE * LDV) + ndn * d["CONV_DIM"] * 4
    var = L * 2 * FFN + L * 2 * H + H + L * 2 * H
    return inv, var


def fit_layer2():
    c08 = F.cfg_dense(1024, 3584, 24, 8, 2, 256, 16, 16, 128, 128, 248320)
    c2b = F.cfg_dense(2048, 6144, 24, 8, 2, 256, 16, 16, 128, 128, 248320)
    i0, v0 = layer_work2(c08)
    i1, v1 = layer_work2(c2b)
    t0 = TM.MEAS["0.8B_W4"]["layer"]
    t1 = TM.MEAS["2B_W8"]["layer"]
    assert i0 == i1, "the two calibration points must share the invariant work"
    Bv = (t1 - t0) / (v1 - v0)
    A = (t0 - Bv * v0) / i0
    return A, Bv, (i0, v0, t0), (i1, v1, t1)


def counters_sub(cfg, plan, inv, nl_sub, nl_all, moe_k=None, moe_e=None):
    """toks_model.counters' arithmetic over an arbitrary image SUBSET.

    Reproduces toks_model.counters EXACTLY when handed the full inventory —
    asserted in section A before anything new is computed.

    For a MoE `routed` image only k of E experts stream, and they are k
    SEPARATE row ranges, so the record count is k x (the per-range record
    count) while MOVX still broadcasts x once per channel (the k gathers share
    one x).  Both are stated assumptions.
    """
    d = B.geometry({**cfg, "intermediate_size": cfg["intermediate_size"] or 0})
    movx_elem = movx_rec = 0
    movy_i16_rows = movy_p32_rows = 0
    movy_i16_rec = movy_p32_rec = 0
    mvgo_rec = mvgo_rows = 0
    chan_bytes = [0] * NCH
    for im in inv:
        stride = B.image_bytes(1, im["k"], plan[im["cls"]])
        movx_elem += NCH * im["k"]
        movx_rec += NCH
        routed = (moe_k is not None and im.get("tag") == "routed")
        nrows = im["nrows"] * moe_k // moe_e if routed else im["nrows"]
        pieces = (B.ilv_chunks(nrows, NCH) if (im["amax"] and NCH > 1)
                  else [(c, r0, n) for c, (r0, n)
                        in enumerate(B.split_rows(nrows, NCH))])
        p32 = im["cls"] in TM.P32_CLASSES
        for (c, _r0, n) in pieces:
            if not n:
                continue
            chan_bytes[c] += n * stride
            if routed:
                per = n // moe_k
                nrec = moe_k * max(1, -(-per // CHUNK_ROWS))
            else:
                nrec = -(-n // CHUNK_ROWS)
            mvgo_rec += nrec
            mvgo_rows += n
            if p32:
                movy_p32_rows += n
                movy_p32_rec += nrec
            else:
                movy_i16_rows += n
                movy_i16_rec += nrec
    H = d["H"]
    ldc_words = 2 * nl_sub * H + int(round(8032 * nl_sub / nl_all))
    ldc_rec = 5 * nl_sub + (1 if nl_sub == nl_all else 0)
    scale = len(inv) / 187.0
    return dict(images=len(inv), movx_elem=movx_elem, movx_rec=movx_rec,
                movy_i16_rows=movy_i16_rows, movy_p32_rows=movy_p32_rows,
                movy_i16_rec=movy_i16_rec, movy_p32_rec=movy_p32_rec,
                mvgo_rec=mvgo_rec, mvgo_rows=mvgo_rows,
                ldc_rec=ldc_rec, ldc_words=ldc_words,
                csrwr=int(round(TM.GOLD_08B_NCH4["csrwr"] * scale)),
                cmd=int(round(TM.GOLD_08B_NCH4["cmd"] * scale)),
                chan_bytes=chan_bytes, busiest_bytes=max(chan_bytes),
                busiest_beats=max(chan_bytes) // 64,
                total_bytes=sum(chan_bytes))


def layer_ms_for(name, A, Bv, nl_frac=1.0):
    cfg = F.CFG[name]
    cfg = {**cfg, "intermediate_size": cfg["intermediate_size"] or 0}
    inv, var = layer_work2(cfg)
    return (A * inv + Bv * var) * nl_frac


def moe_layer_work(name):
    """The MoE's VAR bucket is the ACTIVE FFN width, not `intermediate_size`.

    layer_work's `var` counts `L*2*FFN` for the SwiGLU pair.  The 35B-A3B's
    per-token FFN width is (k + 1) shared/routed experts x moe_intermediate,
    i.e. 9 x 512 = 4,608 — the elementwise work the vec_alu actually does.
    """
    cfg = F.CFG[name]
    k = cfg["num_experts_per_tok"]
    return (k + 1) * cfg["moe_intermediate_size"]


def hdr(s):
    print()
    print("=" * 78)
    print(s)
    print("=" * 78)


def link_ms(nbytes, ntransfers, rate, lat_us):
    return ntransfers * lat_us / 1e3 + nbytes / (rate * 1e6)


if __name__ == "__main__":
    A, Bv, p0, p1 = fit_layer2()
    hdr("A. THE COMMITTED MODEL, SCORED AGAINST THE 9B THAT HAS SINCE SHIPPED")
    print(f"  layer fit restated at HEAD: A={A:.12e}  Bv={Bv:.12e}")
    print(f"     committed (feas/toks_model.json): A={A_COMMITTED:.12e}  "
          f"Bv={BV_COMMITTED:.12e}")
    okab = abs(A - A_COMMITTED) < 1e-18 and abs(Bv - BV_COMMITTED) < 1e-18
    print(f"     reproduces the committed fit: {'OK' if okab else '*** MISMATCH ***'}")
    assert okab
    lay9_committed = 47.00
    l9 = layer_ms_for("9B", A, Bv)
    print(f"     and the committed 9B layer term 47.00 ms: {l9:.2f} "
          f"{'OK' if abs(l9 - lay9_committed) < 0.02 else '*** MISMATCH ***'}")
    assert abs(l9 - lay9_committed) < 0.02
    print(f"  calibration points: 0.8B {p0[2]:.3f} ms, 2B {p1[2]:.3f} ms "
          "(RD_GATE 3)")
    # reproduce counters on the full 9B inventory through BOTH paths
    plan = F.plan_for("all:w4g128")
    inv9 = F.inv_for("9B")
    cA = counters_sub(F.CFG["9B"], plan, inv9, 32, 32)
    B.inventory_saved = B.inventory
    cB = TM.counters(F.CFG["9B"], plan)
    same = all(cA[k] == cB[k] for k in cB if k != "images")
    print(f"  counters_sub reproduces toks_model.counters on the full 9B "
          f"inventory: {'OK' if same else '*** MISMATCH ***'}")
    assert same
    r, m = 1.1037, 0.9117          # toks_model's solve, quoted not re-fitted
    mv = TM.matvec_ms(cA, r)
    mo = TM.movers_ms(cA) * m
    lay_pred = layer_ms_for("9B", A, Bv)
    print(f"  9B W4 g128, the COMMITTED terms: matvec {mv:.2f} + movers "
          f"{mo:.2f} + layer(extrapolated) {lay_pred:.2f} = "
          f"{mv+mo+lay_pred:.2f} ms")
    print(f"     vs MEASURED {MEAS9B['step_steady']:.4f} ms "
          f"({100*((mv+mo+lay_pred)/MEAS9B['step_steady']-1):+.2f} %)"
          "  -- the study's own 138.61 row, and it lands within 1.1 %")
    print(f"  the SAME terms with the MEASURED layer lane {MEAS9B['layer']:.3f}:"
          f" {mv+mo+MEAS9B['layer']:.2f} ms "
          f"({100*((mv+mo+MEAS9B['layer'])/MEAS9B['step_steady']-1):+.2f} %)")
    print()
    print("  HONESTY CHECK.  Those two lines are the whole story of this model's")
    print("  accuracy at the 9B and they must be read TOGETHER: the layer term")
    print(f"  was extrapolated {100*(lay_pred/MEAS9B['layer']-1):+.1f} % HOT")
    print("  (47.00 modelled against a measured 41.588), and the rest of the")
    print("  model is correspondingly LOW.  The 1.1 % agreement at the step is")
    print("  two errors of opposite sign, not one small error.  Every 27B /")
    print("  35B-A3B figure below inherits that, and it is why the band, not")
    print("  the point, is the answer.")
    print()
    print("  NOTE the 9B is a DIFFERENT DESIGN from the two calibration points:")
    print("  post state-spill, its layer state streams from DDR behind URAM")
    print("  caches, and its DMA lane measured 5.125 ms/token (RD9 10.2) which")
    print("  OVERLAPS the compute lane and is not additive.  A and Bv are NOT")
    print("  re-fitted on it.")

    hdr("B. LAYER TERM at the new geometries")
    print(f"{'model':9s} {'n_DN':>5s} {'LNVH':>5s} {'DNST/tok':>9s} "
          f"{'inv work':>12s} {'var work':>12s} {'layer ms':>9s} "
          f"{'x9B meas':>9s} {'corrected':>10s}")
    corr = MEAS9B["layer"] / layer_ms_for("9B", A, Bv)
    lay = {}
    for name in ("9B", "27B", "35B-A3B"):
        cfg = dict(F.CFG[name])
        if F.IS_MOE[name]:
            cfg["intermediate_size"] = moe_layer_work(name)
        else:
            cfg["intermediate_size"] = cfg["intermediate_size"] or 0
        d = B.geometry(cfg)
        ndn = d["TYPES"].count("linear_attention")
        i, v = layer_work2(cfg)
        L = A * i + Bv * v
        lay[name] = (L, L * corr)
        print(f"{name:9s} {ndn:5d} {d['LNH']:5d} {ndn*d['LNH']:9d} "
              f"{i:12,d} {v:12,d} {L:9.2f} {L/MEAS9B['layer']:9.2f} "
              f"{L*corr:10.2f}")
    print()
    print(f"  'corrected' rescales every row by the ONE measured correction the")
    print(f"  9B provides: {MEAS9B['layer']:.3f} / {layer_ms_for('9B',A,Bv):.2f}"
          f" = {corr:.4f}.  It is ONE point on ONE bitstream and it is applied")
    print("  as a constant, which assumes the error is multiplicative in the")
    print("  whole term rather than in one bucket.  That assumption is not")
    print("  tested anywhere.  Both columns are carried below as a BAND.")
    print("  For the MoE the var bucket uses the ACTIVE FFN width "
          f"{moe_layer_work('35B-A3B')} = (8+1) x 512, not a dense FFN.")

    hdr("C. ONE BOARD, if capacity were not a limit (it is — see f05/f07)")
    print(f"{'model':9s} {'map':10s} {'MiB/tok':>9s} {'busiest':>9s} "
          f"{'matvec':>8s} {'movers':>8s} {'layer':>8s} {'step ms':>9s} "
          f"{'tok/s':>7s} {'tok/s corr':>10s}")
    one = {}
    for name in ("9B", "27B", "35B-A3B"):
        for mp in ("all:w4g128", "all:w8g128"):
            plan = F.plan_for(mp)
            inv = F.inv_for(name)
            cfg = F.CFG[name]
            kk = (cfg["num_experts_per_tok"], cfg["num_experts"]) \
                if F.IS_MOE[name] else (None, None)
            c = counters_sub(cfg, plan, inv, cfg["num_hidden_layers"],
                             cfg["num_hidden_layers"], *kk)
            mv, mo = TM.matvec_ms(c, r), TM.movers_ms(c) * m
            st = mv + mo + lay[name][0]
            stc = mv + mo + lay[name][1]
            one[(name, mp)] = (mv, mo, c)
            print(f"{name:9s} {mp:10s} {c['total_bytes']/MIB:9.1f} "
                  f"{c['busiest_bytes']/MIB:9.1f} {mv:8.2f} {mo:8.2f} "
                  f"{lay[name][0]:8.2f} {st:9.2f} {1000/st:7.2f} "
                  f"{1000/stc:10.2f}")

    hdr("D. TWO BOARDS — per-board terms and the link")
    print("Per-board matvec/movers come from that board's OWN image share; the")
    print("layer term is split by the layers it holds.  The link term is E.")
    print()
    print(f"assumed link payload rates (GB/s): " +
          ", ".join(f"{k} {v:.2f}" for k, v in LINK_RATES.items()))
    print(f"assumed one-way latency bracket (us): {LINK_LAT_US}")
    print(f"activation {ACT_BYTES_PER_H} B/element (int16 residual), "
          f"reduce partial {RED_BYTES_PER_H} B/element")

    def board_terms(name, plan, ims, nl_sub, nl_all, layfrac):
        cfg = F.CFG[name]
        kk = (cfg["num_experts_per_tok"], cfg["num_experts"]) \
            if F.IS_MOE[name] else (None, None)
        c = counters_sub(cfg, plan, ims, nl_sub, nl_all, *kk)
        return (TM.matvec_ms(c, r), TM.movers_ms(c) * m,
                lay[name][0] * layfrac, lay[name][1] * layfrac, c)

    out = {}
    for name in ("27B", "35B-A3B"):
        cfg = F.CFG[name]
        NL, H = cfg["num_hidden_layers"], cfg["hidden_size"]
        cut = NL // 2
        for mp in ("all:w4g128",):
            plan = F.plan_for(mp)
            head = [im for im in F.inv_for(name) if im["cls"] == "lm_head"]
            fa = F.B and [im for im in F.inv_for(name)
                          if im["name"].startswith("layers.")
                          and int(im["name"].split(".")[1]) < cut]
            fb = [im for im in F.inv_for(name)
                  if im["name"].startswith("layers.")
                  and int(im["name"].split(".")[1]) >= cut]
            print(f"\n### {name}  {mp}   H={H}  L={NL}, cut at {cut}")

            # ---------- PIPELINE ----------
            aA = board_terms(name, plan, fa, cut, NL, cut / NL)
            aB = board_terms(name, plan, fb + head, NL - cut, NL,
                             (NL - cut) / NL)
            for tag, (A_, B_) in (("A holds layers 0..%d, B the rest + head"
                                   % (cut - 1), (aA, aB)),):
                sA = A_[0] + A_[1] + A_[2]
                sB = B_[0] + B_[1] + B_[2]
                sAc = A_[0] + A_[1] + A_[3]
                sBc = B_[0] + B_[1] + B_[4 - 1]
                sBc = B_[0] + B_[1] + B_[3]
                print(f"  PIPELINE  {tag}")
                print(f"    board A  matvec {A_[0]:7.2f}  movers {A_[1]:6.2f}"
                      f"  layer {A_[2]:6.2f}  = {sA:7.2f} ms   "
                      f"(corrected layer {A_[3]:6.2f} -> {sAc:7.2f})")
                print(f"    board B  matvec {B_[0]:7.2f}  movers {B_[1]:6.2f}"
                      f"  layer {B_[2]:6.2f}  = {sB:7.2f} ms   "
                      f"(corrected layer {B_[3]:6.2f} -> {sBc:7.2f})")
                for rname, rate in LINK_RATES.items():
                    for lat in LINK_LAT_US:
                        lk = link_ms(ACT_BYTES_PER_H * H + 4, 2, rate, lat)
                        ser = sA + sB + lk
                        serc = sAc + sBc + lk
                        # TWO STREAMS IN FLIGHT: each board is busy all the
                        # time, but a TOKEN still needs BOTH boards, so the
                        # completion rate is ONE token per max(sA, sB) — not
                        # two.  (An earlier revision of this script wrote
                        # 2000/max(...) and doubled the answer.)
                        agg = 1000.0 / (max(sA, sB) + lk)
                        aggc = 1000.0 / (max(sAc, sBc) + lk)
                        print(f"      link {rname:18s} lat {lat:4.1f} us  "
                              f"link/tok {lk:6.3f} ms | 1-stream "
                              f"{1000/ser:6.3f} tok/s ({1000/serc:6.3f} corr)"
                              f" | 2-stream aggregate {agg:6.3f} "
                              f"({aggc:6.3f} corr)")
                        pass
            # ---------- TENSOR-PARALLEL (dense) / EXPERT-PARALLEL (MoE) ----
            if not F.IS_MOE[name]:
                allim = F.inv_for(name)
                tA = board_terms(name, plan, allim, NL, NL, 1.0)
                # every image split by output rows -> half the beats, half the
                # mover rows, the same x broadcast, the same layer element work
                mvh, moh = tA[0] / 2.0, tA[1] / 2.0
                # the layer term splits UNEVENLY: the head-indexed bucket
                # (the DeltaNet recurrence and the conv) halves with the heads,
                # the width bucket (RMSNorm, SwiGLU, residual) is REPLICATED on
                # both boards because both hold the full residual vector.
                _cfgT = dict(F.CFG[name])
                _cfgT["intermediate_size"] = _cfgT["intermediate_size"] or 0
                _iT, _vT = layer_work2(_cfgT)
                lyh = A * _iT / 2.0 + Bv * _vT
                lyhc = lyh * corr
                sT = mvh + moh + lyh
                sTc = mvh + moh + lyhc
                nred = 2 * NL + 1
                print(f"  TENSOR-PARALLEL  every matrix split by output rows")
                print(f"    per board  matvec {mvh:7.2f}  movers {moh:6.2f}"
                      f"  layer {lyh:6.2f} (head bucket halved, width")
                print(f"               bucket replicated) = "
                      f"{sT:7.2f} ms  (corrected {sTc:7.2f})")
                for rname, rate in LINK_RATES.items():
                    for lat in LINK_LAT_US:
                        lk = link_ms(RED_BYTES_PER_H * H * nred, nred, rate, lat)
                        print(f"      link {rname:18s} lat {lat:4.1f} us  "
                              f"{nred} reduces, link/tok {lk:7.3f} ms  -> "
                              f"{1000/(sT+lk):6.3f} tok/s "
                              f"({1000/(sTc+lk):6.3f} corr)")
            else:
                routed = [im for im in F.inv_for(name)
                          if im.get("tag") == "routed"]
                rest = [im for im in F.inv_for(name)
                        if im.get("tag") != "routed" and im["cls"] != "lm_head"]
                E, k = cfg["num_experts"], cfg["num_experts_per_tok"]
                tR = board_terms(name, plan, routed, NL, NL, 0.0)
                tX = board_terms(name, plan, rest, NL, NL, 1.0)
                tH = board_terms(name, plan, head, 0, NL, 0.0)
                print(f"  EXPERT-PARALLEL  {E} experts split {E//2}/{E//2}, "
                      f"mixers REPLICATED, head on B")
                print(f"    routed experts, WHOLE model : matvec {tR[0]:7.2f} "
                      f"movers {tR[1]:6.2f}")
                print(f"    mixers+shared+router        : matvec {tX[0]:7.2f} "
                      f"movers {tX[1]:6.2f}  layer {tX[2]:6.2f}"
                      f" (corrected {tX[3]:6.2f})")
                print(f"    lm_head                     : matvec {tH[0]:7.2f} "
                      f"movers {tH[1]:6.2f}")
                for case, frac in (("router BALANCED (k/2 each)", 0.5),
                                   ("router WORST (all k on one board)", 1.0)):
                    sA_ = tR[0] * frac + tR[1] * frac + tX[0] + tX[1] + tX[2]
                    sB_ = sA_ + tH[0] + tH[1]
                    sAc_ = tR[0] * frac + tR[1] * frac + tX[0] + tX[1] + tX[3]
                    sBc_ = sAc_ + tH[0] + tH[1]
                    nex = NL + 1
                    for rname, rate in LINK_RATES.items():
                        for lat in LINK_LAT_US:
                            lk = link_ms(RED_BYTES_PER_H * H * nex, nex,
                                         rate, lat)
                            st_ = max(sA_, sB_) + lk
                            stc_ = max(sAc_, sBc_) + lk
                            print(f"    {case:36s} {rname:18s} lat {lat:4.1f} "
                                  f"us  A {sA_:7.2f} B {sB_:7.2f} link "
                                  f"{lk:6.3f} -> {1000/st_:6.3f} tok/s "
                                  f"({1000/stc_:6.3f} corr)")

    hdr("E. PREFILL — decode-rate, as today")
    print("  There is no batched prefill in this design (RD9_GATE 16 item 5;")
    print("  ARCHITECTURE.md 'weight-stationary batched prefill' is listed as")
    print("  orthogonal and untouched).  A P-token prompt therefore costs P x")
    print("  the decode step above, minus the LM head, on whichever board(s)")
    print("  hold the layers.  A weight-stationary batched prefill would make")
    print("  the matvec term amortise over the batch and leave the layer and")
    print("  link terms per token — label E, unquantified here, and WORTH MORE")
    print("  at these step times than it was at 2B, for the same reason the")
    print("  4B/9B study gave (its section 6 item 7).")
