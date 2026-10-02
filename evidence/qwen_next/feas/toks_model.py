#!/usr/bin/env python3
"""toks_model.py — modelled tok/s at 4B and 9B, re-anchored on R-d's MEASURED terms.

THE MODEL   step_ms = matvec(r) + movers + layer          (nch=4, steady-state)

which is `evidence/qwen2b/ra/MOVER_NORM.md` §3.3's law, unchanged.  What this
script does is (a) drive every counted quantity from the REAL checkpoint
geometry rather than from an emitted stream, (b) re-fit the ONE term MOVER_NORM
could not measure — the layer bucket — against R-d's two silicon points, and
(c) VALIDATE the whole thing against a measurement MOVER_NORM never saw: the
2B W8 step on build_035.

TERM PROVENANCE, stated per term because the study must say what is measured
and what is extrapolated:

  matvec(r)  DERIVED from counted beats x a bracketed DDR rate.
             r in [1.000, 1.131] ui-cyc/beat = [17.0, 19.2] GB/s/chan is
             MOVER_NORM §3.2's calibration-free bracket.  Beats come from the
             per-channel byte split this study computes with the shipped
             allocator (evidence/qwen_next/feas/ddr_fit.py).  The busiest
             channel is what a FENCE exposes (§3.1), so the max is used.

  movers     COUNTED work x MEASURED per-row costs.  The per-row costs are
             MOVER_NORM §1 (silicon donors, build_032).  The work counts are
             re-derived here from geometry and CHECKED against §2's counted
             0.8B stream.  The small CSRWR/CMD/MVGO-config terms are scaled,
             not counted — flagged below.

  layer      MEASURED at two geometries (RD_GATE §3: 0.8B 15.128 ms/token,
             2B 17.960 ms/token, same L_LCYC accumulator, same board, same
             bitstream) and EXTRAPOLATED to 4B/9B by a two-component work
             proxy fitted to exactly those two points.  This is the weakest
             term and the study says so: BOTH calibration points have
             IDENTICAL DeltaNet geometry (16 value heads, dk=dv=128), so the
             coefficient that 4B/9B change most — the per-head recurrent-state
             term — has never been varied in any measurement.  A bracket is
             given instead of a point.

CALIBRATION DATUM carried from the 2B campaign: the feasibility study's
geometry scaling of the layer term projected +23.1 % and silicon measured
+18.7 % (RD_GATE §3), i.e. the projection ran 3.6 % HOT on the ratio.
"""
import json
import os
import sys

ROOT = "/home/cah/r2d2/code/fpga/fable5_llm"
sys.path.insert(0, os.path.join(ROOT, "sw"))
sys.path.insert(0, os.path.join(ROOT, "ref"))
sys.path.insert(0, os.path.join(ROOT, "ref", "scripts"))
os.environ.setdefault("FABLE5_MODEL", "2b")

import bytes_per_token as B                                    # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "evidence/qwen_next/feas"))
from ddr_fit import cfg_for, MODELS                            # noqa: E402

ACLK = 250e6          # rtl aclk, MOVER_NORM §1
UI = 300.12e6         # MIG ui clock, sw/hwmap.UI_CLK_HZ
CHUNK_ROWS = 2048     # ref/seq_format.py:1211 (the definition, not res_chunks)
NCH = 4

# ---- MOVER_NORM.md §1, "Per-ROW summary (the deliverable)" -------------
C_MOVX_PER_INT8 = 1.0
C_MOVX_FIXED = 120.7
C_MOVY_I16_PER_ROW = 1.0
C_MOVY_I16_FIXED = 136.7
C_MOVY_P32_PER_ROW = 2.0
C_MOVY_P32_FIXED = 162.7
C_LDC_PER_WORD = 1.0
C_LDC_FIXED = 594.9
C_CSRWR = 16.99
C_MVGO_CFG = 84.95

# MOVER_NORM §2, the COUNTED 0.8B nch=4 stream — the check for the counters below
GOLD_08B_NCH4 = dict(movx_rec=748, movx_elem=1110016,
                     movy_i16_rows=227904, movy_p32_rows=420352,
                     movy_i16_rec=552, movy_p32_rec=314,
                     mvgo_rec=866, mvgo_rows=648256,
                     ldc_rec=121, ldc_words=57184,
                     csrwr=10371, cmd=3449)

# RD_GATE.md §3 / §1 — the silicon anchors
MEAS = {
    "0.8B_W4": dict(step_steady=31.5023, layer=15.128, note="hw_42 census / hw_08 canned"),
    "2B_W8":   dict(step_steady=60.5145, layer=17.960, note="hw_41 census / hw_44 canned"),
}
# MOVER_NORM §3.1 used 31.495 for the same 0.8B quantity on build_033; R-d's
# build_035 canned mean is 31.5008 and its census 32.9465 gate / 31.5023 steady.

# pairs32 vs int16 on the MOVY side: MOVER_NORM §2's counted split is
# 420,352 pairs32 = gate_up (172,032) + lm_head (248,320) at 0.8B, everything
# else int16.  That rule is asserted against the counts below.
P32_CLASSES = {"gate_up", "lm_head"}


def plan_of(spec):
    """bytes_per_token.parse_map returns (plan, ignored)."""
    p = B.parse_map(spec)
    return p[0] if isinstance(p, tuple) else p


def counters(cfg, plan, nch=NCH):
    """Per-token mover/matvec work, counted from the image inventory."""
    inv = B.inventory(cfg)
    d = B.geometry(cfg)
    movx_elem = movx_rec = 0
    movy_i16_rows = movy_p32_rows = 0
    movy_i16_rec = movy_p32_rec = 0
    mvgo_rec = mvgo_rows = 0
    chan_bytes = [0] * nch
    for im in inv:
        stride = B.image_bytes(1, im["k"], plan[im["cls"]])
        movx_elem += nch * im["k"]        # every channel needs all of x
        movx_rec += nch
        pieces = (B.ilv_chunks(im["nrows"], nch) if (im["amax"] and nch > 1)
                  else [(c, r0, n) for c, (r0, n)
                        in enumerate(B.split_rows(im["nrows"], nch))])
        p32 = im["cls"] in P32_CLASSES
        for (c, _r0, n) in pieces:
            if not n:
                continue
            chan_bytes[c] += n * stride
            # MVGO/MOVY records: each channel's rows cut at CHUNK_ROWS
            nrec = -(-n // CHUNK_ROWS)
            mvgo_rec += nrec
            mvgo_rows += n
            if p32:
                movy_p32_rows += n
                movy_p32_rec += nrec
            else:
                movy_i16_rows += n
                movy_i16_rec += nrec
    L, H = d["NL"], d["H"]
    ldc_words = 2 * L * H + 8032        # 2 rmsnorm weights/layer + a fixed tail
    ldc_rec = 5 * L + 1                 # 121 at L=24 (MOVER_NORM §2)
    scale = len(inv) / 187.0            # the small terms are SCALED, not counted
    return dict(images=len(inv), movx_elem=movx_elem, movx_rec=movx_rec,
                movy_i16_rows=movy_i16_rows, movy_p32_rows=movy_p32_rows,
                movy_i16_rec=movy_i16_rec, movy_p32_rec=movy_p32_rec,
                mvgo_rec=mvgo_rec, mvgo_rows=mvgo_rows,
                ldc_rec=ldc_rec, ldc_words=ldc_words,
                csrwr=int(round(GOLD_08B_NCH4["csrwr"] * scale)),
                cmd=int(round(GOLD_08B_NCH4["cmd"] * scale)),
                chan_bytes=chan_bytes, busiest_bytes=max(chan_bytes),
                busiest_beats=max(chan_bytes) // 64,
                total_bytes=sum(chan_bytes))


def movers_ms(c):
    cyc = (c["movx_elem"] * C_MOVX_PER_INT8 + c["movx_rec"] * C_MOVX_FIXED
           + c["movy_i16_rows"] * C_MOVY_I16_PER_ROW
           + c["movy_i16_rec"] * C_MOVY_I16_FIXED
           + c["movy_p32_rows"] * C_MOVY_P32_PER_ROW
           + c["movy_p32_rec"] * C_MOVY_P32_FIXED
           + c["ldc_words"] * C_LDC_PER_WORD + c["ldc_rec"] * C_LDC_FIXED
           + (c["csrwr"] + c["cmd"]) * C_CSRWR
           + c["mvgo_rec"] * C_MVGO_CFG)
    return 1e3 * cyc / ACLK


def matvec_ms(c, r):
    return 1e3 * c["busiest_beats"] * r / UI


# ======================================================================
# the LAYER term: a two-component work proxy fitted to the two silicon points
# ======================================================================
def layer_work(cfg):
    """(invariant work, H/FFN-proportional work) in 'element' units.

    INVARIANT = the DeltaNet recurrent-state update (per value head a dk x dv
    state, so LNVH*LDK*LDV per DN layer) plus the causal conv (CONV_DIM x 4
    taps).  Both are independent of hidden size — which is exactly why the
    layer term grew only 18.7 % when the 2B doubled H.

    VARIABLE  = everything that rides on H or FFN: two RMSNorms and two
    residual adds per layer, the SwiGLU pair over FFN, and the final norm.

    The RoPE/KV/attention element paths are omitted: at 6 GQA layers x
    (NQH + 2*KVH) they are under 1 % of either bucket at every geometry here,
    and their context-length dependence is not in the calibration data.
    """
    d = B.geometry(cfg)
    H, FFN, L = d["H"], d["FFN"], d["NL"]
    LNVH = d["LNH"]                     # VALUE heads: 16 at 0.8B/2B, 32 at 4B/9B
    LDV = d["LVD"] // LNVH              # per-head value dim = 128 everywhere
    LDK_TRUE = 128                      # per-head KEY dim, from the checkpoint.
    # NOT d["LKD"]//LNVH: ddr_fit.cfg_for folds 16 real key heads into the
    # tool's 32-head field, which halves the encoded per-head key dim.  The
    # PHYSICAL recurrent state is dk x dv per VALUE head, dk = dv = 128.
    ndn = sum(1 for t in d["TYPES"] if t == "linear_attention")
    inv = ndn * (LNVH * LDK_TRUE * LDV) + ndn * d["CONV_DIM"] * 4
    var = L * 2 * FFN + L * 2 * H + H + L * 2 * H
    return inv, var


def fit_layer():
    """Solve the two-component model on RD_GATE's two measured layer terms."""
    c08 = cfg_for(1024, 3584, 24, 8, 2, 256, 16, 16, 128, 128, 248320)
    c2b = cfg_for(*MODELS["2B"])
    i0, v0 = layer_work(c08)
    i1, v1 = layer_work(c2b)
    t0, t1 = MEAS["0.8B_W4"]["layer"], MEAS["2B_W8"]["layer"]
    assert i0 == i1, "the two calibration points must share the invariant work"
    # t = A*inv + Bv*var  ->  Bv from the difference, A from either point
    Bv = (t1 - t0) / (v1 - v0)
    A = (t0 - Bv * v0) / i0
    return A, Bv, (i0, v0, t0), (i1, v1, t1)


def layer_ms(cfg, A, Bv, var_law="mixed"):
    """Central layer term.  `var_law` selects how the H/FFN-proportional work
    is assumed to scale, which is the study's stated sensitivity axis.

    THERE IS NO "LOW" BRACKET ANY MORE, and its removal is the point.  An
    earlier revision offered one built on "the DeltaNet lane array already
    absorbs 32 value heads in the cycles it spends on 16".  The as-built RTL
    refutes that outright:

      rtl/dn_step.sv:1      "one gated-delta-rule recurrence step for ONE head"
      rtl/dn_step.sv:13-14  "128 parallel lanes ... ~1300 cycles/head"
      rtl/layer_chan.sv:627 ONE dn_step instance
      d2d774b:rtl/layer_chan.sv:891 `dn_head <= arg0[3:0];` -- per-COMMAND arg
                            [CLASS B, PINNED to the tree that carries the
                            quotation: 891 is its line at d2d774b (8ef57a8^),
                            and the QUOTATION died at 8ef57a8 (G3.1), which
                            widened the field to five bits.  Task 10 fix
                            round 2 called 891 "the number at 8138d66"; it
                            is not (8138d66:891 is the scratch-addressing
                            comment) -- S3 fix round 3 re-pinned it.
                            Post-G3.4 site
                            rtl/layer_chan.sv:1513 `dn_head <= arg0[4:0];`
                            (2026-09-02, Task 10 fix round 2)]
      ref/gen_layer_script.py:2002  `for h in range(LR.LNH):` emitting
                            vn / alu / vn / dnst PER HEAD  [G3.4 fix round
                            3: :1074-1081 / :1101-1108 were the ALU audit
                            block, never the loop]

    Heads are the OUTER loop, serialized through one 128-lane engine that is
    already fully occupied (128 lanes over LDK=128 rows).  Doubling the value
    heads doubles the loop.  evidence/qwen_next/feas/f16_layer_cmd_census.log
    confirms the count on the real stream: DNST is EXACTLY 288/token at 0.8B
    = 18 DN layers x 16 heads, and would be 768 = 24 x 32 at 4B/9B.
    """
    inv, var = layer_work(cfg)
    if var_law == "H":
        pass
    return A * inv + Bv * var


def var_scaled(cfg, base_cfg, law):
    """VAR ratio new/base under one of three assumed scaling laws."""
    d, b = B.geometry(cfg), B.geometry(base_cfg)
    if law == "H":
        return (d["H"] * d["NL"]) / (b["H"] * b["NL"])
    if law == "FFN":
        return (d["FFN"] * d["NL"]) / (b["FFN"] * b["NL"])
    _, v = layer_work(cfg)
    _, vb = layer_work(base_cfg)
    return v / vb


def layer_band(cfg, A, Bv, c08):
    """(low, central, high) over the three VAR laws + a stated +/-10 % on the
    whole term for the fact that NO measurement has ever varied the DeltaNet
    geometry.  The three laws move it very little; the +/-10 % is the honest
    part."""
    inv, _ = layer_work(cfg)
    i0, v0 = layer_work(c08)
    t0 = MEAS["0.8B_W4"]["layer"]
    vals = []
    for law in ("mixed", "H", "FFN"):
        rv = var_scaled(cfg, c08, law)
        rv0 = var_scaled(cfg_for(*MODELS["2B"]), c08, law)
        bv = (MEAS["2B_W8"]["layer"] - t0) / (v0 * rv0 - v0)
        a = (t0 - bv * v0) / i0
        vals.append(a * inv + bv * v0 * rv)
    return min(vals), sum(vals) / len(vals), max(vals)


# ======================================================================
MAPS = ["all:w8g128", "all:w4g128", "all:w4g64"]
R_LO, R_HI = 1.000, 1.131        # MOVER_NORM §3.2 calibration-free bracket

if __name__ == "__main__":
    print("=" * 78)
    print("A. THE COUNTERS — validated against MOVER_NORM.md section 2's "
          "counted 0.8B nch=4 stream")
    print("=" * 78)
    c08 = cfg_for(1024, 3584, 24, 8, 2, 256, 16, 16, 128, 128, 248320)
    got = counters(c08, plan_of("all:w4g128"))
    ok = True
    for k, want in GOLD_08B_NCH4.items():
        have = got[k]
        good = (have == want)
        if k in ("csrwr", "cmd"):
            good = True          # scaled terms, exact at 0.8B by construction
        ok &= good
        print(f"    {k:16s} model {have:>10,}  counted {want:>10,}  "
              f"{'OK' if have == want else ('scaled' if k in ('csrwr','cmd') else '*** MISMATCH ***')}")
    print(f"    busiest-channel beats  {got['busiest_beats']:,}  "
          f"(MOVER_NORM 3.1 chan0 1,643,280)  "
          f"{'OK' if got['busiest_beats'] == 1643280 else '*** MISMATCH ***'}")
    ok &= got["busiest_beats"] == 1643280
    print(f"    total bytes/token      {got['total_bytes']:,}  "
          f"(RD_GATE 417,435,648)  "
          f"{'OK' if got['total_bytes'] == 417435648 else '*** MISMATCH ***'}")
    ok &= got["total_bytes"] == 417435648
    m = movers_ms(got)
    print(f"    -> movers {m:.3f} ms   (MOVER_NORM 3.3 recompute 11.334, "
          f"measured residual 11.401, bracket [11.17, 11.89])")
    print(f"    COUNTER VALIDATION: {'PASS' if ok else 'FAIL'}")

    print()
    print("=" * 78)
    print("B. THE LAYER FIT — two components, two silicon points")
    print("=" * 78)
    A, Bv, p0, p1 = fit_layer()
    print(f"    0.8B  inv {p0[0]:>12,}  var {p0[1]:>10,}  measured {p0[2]:.3f} ms")
    print(f"    2B    inv {p1[0]:>12,}  var {p1[1]:>10,}  measured {p1[2]:.3f} ms")
    print(f"    A  (invariant, DN state + conv) = {A:.6e} ms/element "
          f"= {A*1e-3*ACLK:.4f} aclk cycles/element")
    print(f"    Bv (H/FFN-proportional)         = {Bv:.6e} ms/element "
          f"= {Bv*1e-3*ACLK:.4f} aclk cycles/element")
    print(f"    split at 0.8B: invariant {A*p0[0]:.3f} ms ({100*A*p0[0]/p0[2]:.1f} %), "
          f"variable {Bv*p0[1]:.3f} ms ({100*Bv*p0[1]/p0[2]:.1f} %)")
    print("    *** READ THE SPLIT AS AN INTERCEPT, NOT A COST. *** Both")
    print("    calibration points share DeltaNet geometry, so `A` is the")
    print("    INTERCEPT of a two-point fit: it is whatever is left after the")
    print("    H/FFN term explains the 0.8B->2B difference. Nothing measured")
    print("    the DeltaNet contribution directly. What IS primary-source is")
    print("    that the work it stands for scales with nDN x LNH:")
    print("    rtl/dn_step.sv:1 and rtl/dn_step.sv:13-14 (one head per")
    print("    invocation, ~1300 cyc/head, 128 lanes), rtl/layer_chan.sv:627")
    print("    (ONE instance), d2d774b:rtl/layer_chan.sv:891 (head is a command")
    print("    arg), ref/gen_layer_script.py:2002 (the per-head emit loop).")
    print(f"    For scale, the DNST commands alone at 1300 cyc/head and 250 MHz:")
    print(f"      0.8B/2B  18 x 16 = 288 cmd/token -> {288*1300/250e6*1e3:.3f} ms"
          f"  ({100*288*1300/250e6*1e3/15.128:.1f} % of the 0.8B layer term)")
    print(f"      4B/9B    24 x 32 = 768 cmd/token -> {768*1300/250e6*1e3:.3f} ms")

    print()
    print("=" * 78)
    print("C. THE STEP MODEL — (r, overlap) solved from the TWO silicon steps")
    print("=" * 78)
    print("    R-d re-measured the layer term UPWARD (MOVER_NORM used build_033's")
    print("    14.130 ms; R-d's L_LCYC census on build_035 reads 15.128).  With")
    print("    that term a SERIAL sum over-predicts the 0.8B step, which is direct")
    print("    evidence for what MOVER_NORM 3.2 flagged as possible but could not")
    print("    resolve: at nch=4 some mover work HIDES under engine time (no-wait")
    print("    MVGO, 217 FENCEs/token).  So the model carries one overlap factor:")
    print()
    print("        step = beats_busiest * r / UI  +  movers_counted * m  +  layer")
    print()
    print("    and (r, m) are solved from the two measured steps.  Nothing else")
    print("    is fitted; both come out physically admissible, which is the test.")
    c08 = cfg_for(1024, 3584, 24, 8, 2, 256, 16, 16, 128, 128, 248320)
    c2b = cfg_for(*MODELS["2B"])
    k0 = counters(c08, plan_of("all:w4g128"))
    k1 = counters(c2b, plan_of("all:w8g128"))
    m0, m1 = movers_ms(k0), movers_ms(k1)
    b0 = matvec_ms(k0, 1.0)          # ms per unit r
    b1 = matvec_ms(k1, 1.0)
    y0 = MEAS["0.8B_W4"]["step_steady"] - MEAS["0.8B_W4"]["layer"]
    y1 = MEAS["2B_W8"]["step_steady"] - MEAS["2B_W8"]["layer"]
    # [b0 m0; b1 m1] [r; m] = [y0; y1]
    det = b0 * m1 - b1 * m0
    r_fit = (y0 * m1 - y1 * m0) / det
    m_fit = (b0 * y1 - b1 * y0) / det
    print()
    print(f"    0.8B W4: matvec {b0:.4f}*r + movers {m0:.3f}*m + layer "
          f"{MEAS['0.8B_W4']['layer']:.3f} = {MEAS['0.8B_W4']['step_steady']:.4f}")
    print(f"    2B   W8: matvec {b1:.4f}*r + movers {m1:.3f}*m + layer "
          f"{MEAS['2B_W8']['layer']:.3f} = {MEAS['2B_W8']['step_steady']:.4f}")
    print(f"    -> r = {r_fit:.4f} ui-cyc/beat  = "
          f"{64*UI/r_fit/1e9:.2f} GB/s/chan  "
          f"({'INSIDE' if R_LO <= r_fit <= R_HI else '*** OUTSIDE ***'} "
          f"MOVER_NORM 3.2's calibration-free bracket [{R_LO}, {R_HI}])")
    print(f"    -> m = {m_fit:.4f}  i.e. {100*(1-m_fit):.1f} % of counted mover "
          f"work overlaps engine time at nch=4")
    print(f"       (MOVER_NORM 3.1's independently derived r was 1.0892; this "
          f"solve lands {100*(r_fit/1.0892-1):+.1f} % from it)")
    print("    Both are admissible: r >= 1.000 is the engine's hard floor and")
    print("    0 <= 1-m <= 1 is required of an overlap.  Neither was constrained.")

    print()
    print("    --- HONESTY CHECK 1: the calibration-free bracket, RE-ANCHORED ---")
    print("    MOVER_NORM 3.2(b) derives r <= 1.131 from")
    print("        45.018 = 14.13 + matvec_1 + movers_1,  movers_1 >= 6.308")
    print("    but 14.13 is build_033's layer term, which R-d SUPERSEDES with")
    print("    15.128 (RD_GATE 3).  Re-running that same inequality:")
    NCH1_BEATS_08B = 6522432          # MOVER_NORM 2, nch=1, 0.8B W4
    MOVERS1_FLOOR = 6.308             # MOVER_NORM 3.2(a), counted work, no fixed costs
    for lay, tag in ((14.130, "MOVER_NORM's 14.130 (build_033)"),
                     (MEAS["0.8B_W4"]["layer"], "R-d's 15.128 (build_035)")):
        mv1_max = 45.018 - lay - MOVERS1_FLOOR
        r_max = mv1_max * 1e-3 * UI / NCH1_BEATS_08B
        print(f"      layer {lay:7.3f}  ({tag})")
        print(f"        matvec_1 <= {mv1_max:6.3f} ms  ->  r <= {r_max:.4f}"
              f"   ({64*UI/r_max/1e9:.2f} GB/s/chan)")
    r_max_now = (45.018 - MEAS["0.8B_W4"]["layer"] - MOVERS1_FLOOR) * 1e-3 * UI / NCH1_BEATS_08B
    print(f"    => the bracket becomes [1.000, {r_max_now:.4f}], and this study's")
    print(f"       r = {r_fit:.4f} is **OUTSIDE it by {100*(r_fit/r_max_now-1):.1f} %**.")
    print("    An earlier revision claimed r landed INSIDE MOVER_NORM's bracket.")
    print("    That was true only against the bracket's SUPERSEDED anchor, and")
    print("    it is withdrawn.  MOVER_NORM:161-165 also states its own point")
    print("    estimate is soft: r rests on a bubble figure of 8.252 where the")
    print("    repo's other figure is 8.94, and 8 % on the bubble moves r 7 %")
    print("    (to 1.013).  So neither r=1.0892 nor the bracket is a hard rail.")

    print()
    print("    --- HONESTY CHECK 2: nch=1, a configuration NOTHING here was fitted to ---")
    k1 = counters(c08, plan_of("all:w4g128"), nch=1)
    print(f"      counted nch=1 busiest beats {k1['busiest_beats']:,} "
          f"(MOVER_NORM 2: 6,522,432)  "
          f"{'OK' if k1['busiest_beats'] == NCH1_BEATS_08B else '*** MISMATCH ***'}")
    mv1 = movers_ms(k1)
    print(f"      counted nch=1 movers {mv1:.3f} ms (MOVER_NORM 3.3: 7.293)")
    for mm, lab in ((1.0, "m = 1.000 (MOVER_NORM: at nch=1 nothing overlaps)"),
                    (m_fit, f"m = {m_fit:.4f} (this study's nch=4 solve)")):
        pred = matvec_ms(k1, r_fit) + mv1 * mm + MEAS["0.8B_W4"]["layer"]
        print(f"      {lab}")
        print(f"        predicted step {pred:6.3f} ms vs MEASURED 45.018  "
              f"-> {100*(pred/45.018-1):+.1f} %")
    print("    The model OVER-predicts nch=1 by 1-3 %.  Reported, not hidden:")
    print("    the (r, m) pair is exactly determined by two nch=4 equations, so")
    print("    it has no residual AT those points and cannot be 'validated' by")
    print("    them; nch=1 is the only out-of-sample test available and it does")
    print("    not close.  Consequence for this study: the ABSOLUTE tok/s carry")
    print("    a few per cent of unmodelled configuration dependence on top of")
    print("    the layer allowance, and the RELATIVE 4B-vs-9B comparison — which")
    print("    shares r, m and the mover law — is much the sounder of the two.")

    print()
    print("=" * 78)
    print("D. PROJECTION — 4B and 9B, nch=4, steady-state convention")
    print("=" * 78)
    print(f"    r = {r_fit:.4f}, m = {m_fit:.4f} (from C).")
    print("    ONE layer figure per target, not a bracket: the LOW bracket an")
    print("    earlier revision carried is refuted by the RTL (see layer_ms).")
    print("    The +/-10 % column is the stated allowance for the fact that no")
    print("    measurement has ever varied the DeltaNet geometry.")
    out = {}
    c08 = cfg_for(1024, 3584, 24, 8, 2, 256, 16, 16, 128, 128, 248320)
    for mapspec in MAPS:
        print(f"\n### map = {mapspec}")
        print(f"    {'model':5s} {'MiB/tok':>9s} {'busiest MiB':>12s} "
              f"{'matvec':>8s} {'movers':>8s} {'layer':>8s} {'law spread':>16s} "
              f"{'step ms':>9s} {'tok/s':>8s} {'tok/s +/-10 % layer':>21s}")
        for name in ("2B", "4B", "9B"):
            cfg = cfg_for(*MODELS[name])
            c = counters(cfg, plan_of(mapspec))
            mv = movers_ms(c) * m_fit
            mvt = matvec_ms(c, r_fit)
            if name == "2B":
                lo = ly = hi = MEAS["2B_W8"]["layer"]
            else:
                lo, ly, hi = layer_band(cfg, A, Bv, c08)
            step = mvt + mv + ly
            s_lo = mvt + mv + ly * 0.9
            s_hi = mvt + mv + ly * 1.1
            print(f"    {name:5s} {c['total_bytes']/2**20:9.1f} "
                  f"{c['busiest_bytes']/2**20:12.1f} {mvt:8.2f} {mv:8.2f} "
                  f"{ly:8.2f} {lo:7.2f}..{hi:6.2f} {step:9.2f} "
                  f"{1000/step:8.2f} {1000/s_hi:10.2f}..{1000/s_lo:8.2f}")
            out[f"{name}/{mapspec}"] = dict(
                bytes_per_token=c["total_bytes"], busiest_bytes=c["busiest_bytes"],
                matvec=mvt, movers=mv, layer=ly, layer_law_lo=lo, layer_law_hi=hi,
                step=step, toks=1000 / step,
                toks_lo=1000 / s_hi, toks_hi=1000 / s_lo)

    print()
    print("=" * 78)
    print("E. WHERE THE TIME GOES (share of the step, central layer term)")
    print("=" * 78)
    for mapspec in ("all:w8g128", "all:w4g128"):
        for name in ("2B", "4B", "9B"):
            o = out[f"{name}/{mapspec}"]
            st = o["step"]
            print(f"    {name:4s} {mapspec:11s} matvec {100*o['matvec']/st:5.1f} %  "
                  f"movers {100*o['movers']/st:5.1f} %  layer {100*o['layer']/st:5.1f} %"
                  f"   (step {st:.1f} ms, {1000/st:.2f} tok/s)")

    print()
    print("=" * 78)
    print("F. SENSITIVITY — r swept over MOVER_NORM 3.2's bracket, m re-solved")
    print("   on the 0.8B point only, and the 2B W8 step used as the CHECK")
    print("=" * 78)
    print(f"    {'r':>7s} {'GB/s/ch':>8s} {'m':>7s} {'2B W8 pred':>11s} "
          f"{'err vs 60.5145':>15s} {'4B W8 tok/s':>12s} {'9B W4 tok/s':>12s}")
    for r in (1.000, 1.050, r_fit, 1.100, 1.131):
        m = (y0 - b0 * r) / m0
        pred2b = b1 * r + m1 * m + MEAS["2B_W8"]["layer"]
        row = []
        for nm, ms in (("4B", "all:w8g128"), ("9B", "all:w4g128")):
            cfg = cfg_for(*MODELS[nm])
            c = counters(cfg, plan_of(ms))
            st = matvec_ms(c, r) + movers_ms(c) * m + layer_ms(cfg, A, Bv)
            row.append(f"{1000/st:11.2f}")
        print(f"    {r:7.4f} {64*UI/r/1e9:8.2f} {m:7.4f} {pred2b:11.3f} "
              f"{100*(pred2b/MEAS['2B_W8']['step_steady']-1):+14.2f} % "
              f"{row[0]:>12s} {row[1]:>12s}")

    print()
    print("=" * 78)
    print("G. CALIBRATION DATUM — the 2B study's own projection error")
    print("=" * 78)
    print("    layer-term ratio 0.8B -> 2B: projected 1.2314 (+23.1 %), "
          "MEASURED 1.1872 (+18.7 %) — RD_GATE 3 states this as -3.6 % on the")
    print("    ratio; 1.2314/1.1872 = 1.0372 is this study's reciprocal of that.")
    print("    This model is FITTED to both points, so it carries no error AT")
    print("    them; the exposure is entirely in the DeltaNet term, whose")
    print("    coefficient is a fit INTERCEPT (section B) even though its")
    print("    SCALING LAW is primary-source (section B's dn_step citations).")

    json.dump(dict(A=A, Bv=Bv, r=r_fit, m=m_fit, results=out),
              open(sys.argv[1], "w") if len(sys.argv) > 1 else sys.stderr,
              indent=1, sort_keys=True)
