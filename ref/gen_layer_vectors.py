#!/usr/bin/env python3
"""Golden vectors + ROM init files for the stage-3 layer-processor RTL.

Per block, per seed: stimulus and bit-exact expected outputs from
ref/layer_fixed.py. The RTL unit TBs replay these. Also emits the LUT ROM
.hex files (rsqrt/recip/exp2/sigmoid/softplus) — generated from the very
tables fixedpoint.py computes with, so ref and RTL share one source.

Usage: gen_layer_vectors.py <out_dir> <seed>
Files (all hex, one value per line, two's complement at stated width):
  rmsnorm_{x16,w14,y16}.hex (N=1024)     rope_{x16,cos,sin,y16}.hex
  l2norm_{x16,y16}.hex                    conv_{win,w,y}.hex (silu out Q12)
  attn_{q,k8,ke,v8,ve,acc}.hex (T=48)     dn_{sin,q,k,v,dec,beta,sout,o}.hex
  roms/{rsqrt,recip,exp2,sigmoid,softplus}_rom.hex
"""
import os
import sys

import numpy as np

import fixedpoint as fp
import layer_fixed as LF
import layer_ref as LR
from w4a8_ref import rshift_round as rshr

I64 = np.int64


def wr(path, vals, width_bits):
    mask = (1 << width_bits) - 1
    with open(path, "w") as f:
        for v in np.asarray(vals).reshape(-1):
            f.write(f"{int(v) & mask:0{(width_bits + 3) // 4}x}\n")


def main():
    out, seed = sys.argv[1], int(sys.argv[2])
    os.makedirs(f"{out}/roms", exist_ok=True)
    rng = np.random.default_rng(seed)

    # ---- ROMs (from fixedpoint's own tables) ----
    wr(f"{out}/roms/rsqrt_rom.hex", fp._rsqrt_lut(), 16)
    fp.recip_q(3, 0)  # touch to build
    wr(f"{out}/roms/recip_rom.hex", fp._RECIP_LUT, 16)
    wr(f"{out}/roms/exp2_rom.hex", fp._exp2_lut(), 18)
    fp.sigmoid_q(0); fp.softplus_q(0)
    wr(f"{out}/roms/sigmoid_rom.hex", fp._SIGMOID_TAB, 16)
    wr(f"{out}/roms/softplus_rom.hex", fp._SOFTPLUS_TAB, 17)

    # ---- rmsnorm (1+w), N=1024 ----
    x = np.round(rng.normal(0, 2, LR.H) * (1 << LF.RS_F)).astype(I64)
    w = np.round(rng.normal(0, 0.1, LR.H) * (1 << 14)).astype(I64)
    y = LF.rmsnorm_fx(x, w, LF.RS_F, True)
    wr(f"{out}/rmsnorm_x16.hex", x, 16)
    wr(f"{out}/rmsnorm_w14.hex", w, 16)
    wr(f"{out}/rmsnorm_y16.hex", y, 16)

    # ---- rope (HD=256, pos random) ----
    pos = int(rng.integers(0, 1 << 16))
    cq, sq = LF.rope_tables_q15(pos)
    xh = np.round(rng.normal(0, 1, LR.HD) * (1 << LF.QKV_F)).astype(I64)
    yh = LF.rope_fx(xh, cq, sq)
    wr(f"{out}/rope_x16.hex", xh, 16)
    wr(f"{out}/rope_cos.hex", cq, 16)
    wr(f"{out}/rope_sin.hex", sq, 16)
    wr(f"{out}/rope_y16.hex", yh, 16)

    # ---- l2norm (128) ----
    xl = np.round(rng.normal(0, 1.5, LR.LDK) * (1 << LF.QKV_F)).astype(I64)
    wr(f"{out}/l2norm_x16.hex", xl, 16)
    wr(f"{out}/l2norm_y16.hex", LF.l2norm_fx(xl, LF.QKV_F, LF.NRM_F), 16)

    # ---- depthwise conv step + silu (one channel batch of 64) ----
    win = np.round(rng.normal(0, 1, (64, 4)) * (1 << LF.RS_F)).astype(I64)
    cw = np.round(rng.normal(0, 0.3, (64, 4)) * (1 << LF.CW_F)).astype(I64)
    acc = (win * cw).sum(axis=1)
    pre = np.clip(rshr(acc, LF.RS_F + LF.CW_F - 12), -(1 << 20), (1 << 20) - 1)
    yco = np.clip(np.array([fp.silu_q(int(v)) for v in pre], dtype=I64),
                  -32768, 32767)
    wr(f"{out}/conv_win.hex", win, 16)
    wr(f"{out}/conv_w.hex", cw, 16)
    wr(f"{out}/conv_y.hex", yco, 16)

    # ---- attention core (T=48) ----
    T, HD = 48, LR.HD
    qn = np.round(rng.normal(0, 1, HD) * (1 << LF.QKV_F)).astype(I64)
    k8s, kes, v8s, ves = [], [], [], []
    for t in range(T):
        k8, ke = LF.kv_quant(np.round(rng.normal(0, 1, HD) * (1 << LF.QKV_F)).astype(I64), LF.QKV_F)
        v8, ve = LF.kv_quant(np.round(rng.normal(0, 1.2, HD) * (1 << LF.QKV_F)).astype(I64), LF.QKV_F)
        k8s.append(k8); kes.append(ke); v8s.append(v8); ves.append(ve)
    SC = int(round((1 << 15) / np.sqrt(HD)))
    sc_q = np.zeros(T, dtype=I64)
    for t in range(T):
        dot = int((qn * k8s[t].astype(I64)).sum())
        s_ = rshr(I64(dot) * SC, 15)
        f = LF.QKV_F - kes[t] - 16
        sc_q[t] = rshr(I64(int(s_)), f) if f >= 0 else int(s_) << (-f)
    mx = int(sc_q.max())
    es = np.array([fp.exp_neg_q(int(min(int(sc_q[t]) - mx, 0))) for t in range(T)], dtype=I64)
    r, re = fp.recip_q(int(es.sum()), 30)
    p = np.clip(rshr(es * r, 30 - re + 15), 0, 1 << 15)
    acc = np.zeros(HD, dtype=I64)
    for t in range(T):
        term = I64(int(p[t])) * v8s[t].astype(I64)
        sh = 15 - ves[t] - LF.QKV_F
        acc += rshr(term, sh) if sh >= 0 else term << (-sh)
    wr(f"{out}/attn_q.hex", qn, 16)
    wr(f"{out}/attn_k8.hex", np.stack(k8s), 8)
    wr(f"{out}/attn_ke.hex", np.array(kes) & 0xFF, 8)
    wr(f"{out}/attn_v8.hex", np.stack(v8s), 8)
    wr(f"{out}/attn_ve.hex", np.array(ves) & 0xFF, 8)
    wr(f"{out}/attn_p.hex", p, 16)
    wr(f"{out}/attn_acc.hex", acc, 32)

    # ---- deltanet recurrence step ----
    LDK, LDV = LR.LDK, LR.LDV
    S = np.round(rng.normal(0, 0.01, (LDK, LDV)) * (1 << LF.S_F)).astype(np.int16)
    qv = np.round(LR.l2norm(rng.normal(0, 1, LDK)) / np.sqrt(LDK) * (1 << LF.NRM_F)).astype(I64)
    kv_ = np.round(LR.l2norm(rng.normal(0, 1, LDK)) * (1 << LF.NRM_F)).astype(I64)
    vv = np.round(rng.normal(0, 0.8, LDV) * (1 << LF.S_F)).astype(I64)
    dec = int(rng.integers(100, 1 << 15))
    bet = int(rng.integers(1 << 13, 1 << 15))
    Sh = rshr(S.astype(I64) * dec, LF.GAT_F)
    kvm = rshr((Sh * kv_[:, None]).sum(axis=0), LF.NRM_F)
    dlt = rshr((vv - kvm) * bet, LF.GAT_F)
    Sh = Sh + rshr(kv_[:, None] * dlt[None, :], LF.NRM_F)
    Sh = np.clip(Sh, -32768, 32767)
    o = rshr((Sh * qv[:, None]).sum(axis=0), LF.NRM_F)
    wr(f"{out}/dn_sin.hex", S, 16)
    wr(f"{out}/dn_q.hex", qv, 16)
    wr(f"{out}/dn_k.hex", kv_, 16)
    wr(f"{out}/dn_v.hex", vv, 16)
    with open(f"{out}/dn_gates.txt", "w") as f:
        f.write(f"{dec} {bet}\n")
    wr(f"{out}/dn_sout.hex", Sh, 16)
    wr(f"{out}/dn_o.hex", o, 32)

    # ---- gate unit (16 heads): beta/decay chain ----
    bq = np.round(rng.normal(0, 3, 16) * (1 << 12)).astype(I64)
    aq = np.round(rng.normal(0, 2, 16) * (1 << 12)).astype(I64)
    bq = np.clip(bq, -32768, 32767)
    aq = np.clip(aq, -32768, 32767)
    Aq = np.round(np.exp(np.log(rng.uniform(0.5, 8, 16))) * (1 << 15)).astype(I64)
    dt = np.round(rng.uniform(0.5, 1.5, 16) * (1 << 12)).astype(I64)
    beta_g = np.array([fp.sigmoid_q(int(b)) for b in bq], dtype=I64)
    dec_g = np.zeros(16, dtype=I64)
    for h in range(16):
        sp = fp.softplus_q(int(aq[h] + dt[h]))
        g16 = -rshr(I64(int(Aq[h])) * sp, 11)
        dec_g[h] = min(rshr(I64(fp.exp_neg_q(int(min(g16, 0)))), 15), I64(32767))
    wr(f"{out}/gate_b.hex", bq, 16)
    wr(f"{out}/gate_a.hex", aq, 16)
    wr(f"{out}/gate_A.hex", Aq, 18)
    wr(f"{out}/gate_dt.hex", dt, 16)
    wr(f"{out}/gate_beta.hex", beta_g, 16)
    wr(f"{out}/gate_decay.hex", dec_g, 16)

    # ---- vec_alu ops (64 elems each) ----
    def clip16v(x):
        return np.clip(x, -32768, 32767).astype(I64)
    ax = np.round(rng.normal(0, 2000, 64)).astype(I64)
    bx = np.round(rng.normal(0, 2000, 64)).astype(I64)
    v32 = rng.integers(-(1 << 24), 1 << 24, 64).astype(I64)
    alu = {}
    x8, e8 = fp.dyn_quant_i8(np.clip(ax * 7, -32768, 32767))
    alu["dynq8_x"] = np.clip(ax * 7, -32768, 32767)
    alu["dynq8_y"] = x8.astype(I64)
    alu["dynq8_e"] = np.array([e8], dtype=I64)
    alu["shift32_v"] = v32
    alu["shift32_y"] = clip16v(rshr(v32, 5))
    INVQ = int(round((1 << 15) / np.sqrt(128)))
    alu["scale_x"] = ax
    alu["scale_y"] = clip16v(rshr(ax * INVQ, 15))
    alu["emul_a"] = ax
    alu["emul_b"] = bx
    alu["emul_y"] = clip16v(rshr(ax * bx, 12))
    alu["add_y"] = clip16v(ax + bx)
    alu["silu16_y"] = clip16v(np.array([fp.silu_q(int(x) << 4) for x in ax]))
    v20 = np.clip(v32, -(1 << 20), (1 << 20) - 1)
    alu["silu32_y"] = clip16v(np.array([fp.silu_q(int(x)) for x in v20]))
    alu["sigm16_y"] = np.array([fp.sigmoid_q(int(x) << 4) for x in ax], dtype=I64)
    alu["emul32_y"] = clip16v(rshr(v32 * bx, 15))
    # SHIFT32W p0=-8: left shift exercises the rshr64s << path and clip32
    alu["shift32w_y"] = np.clip(v32 << 8, -(1 << 31), (1 << 31) - 1)
    for k, v in alu.items():
        wr(f"{out}/alu_{k}.hex", v,
           32 if ("32_v" in k or k == "shift32w_y") else 16)

    print(f"layer vectors: seed={seed} -> {out}")


if __name__ == "__main__":
    main()
