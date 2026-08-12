#!/usr/bin/env python3
"""Layer-level integration script for the sequencer rung-1 ops.

Replayed by the UNMODIFIED tb_layer_chan (W/C/R records only), so this
proves the layer_chan plumbing end to end without touching the frozen TB:

    DYNQ16 (ALU op 12) -> k into the XRF entry cfg_p0[0] picks
    op-8 EMUL32 PROBE  -> k_a into XRF[2]
    EPS-NORM (VN mode 2 + ARG2[0]=1) reads k back out of XRF[ARG2[3:1]]

The test is only worth running if it can FAIL, and the eps addend
E = rshr64(EPS_M, 7+2k) is negligible against ss for k >~ -8: on an
ordinary head every k gives the SAME output and the script would prove
nothing.  So the norm input is deliberately a tiny block (DYNQ16 k around
-10, i.e. the small-magnitude regime the eps floor exists for), and the
generator ASSERTS that the goldens for the different XRF entries are
pairwise distinct before it writes the file.

Records:
  a  DYNQ16(tiny, clamp0=0, k -> XRF[2])         R: y16 (left-shift path)
  b  EPS-NORM k = XRF[2]                         R: eps_norm_fx(x, k_t)
  c  DYNQ16(tiny, clamp0=1, k -> XRF[1])         R: y16 (clamped, differs)
  d  EPS-NORM k = XRF[1]                         R: eps_norm_fx(x, 0)  != b
  e  op-8 EMUL32 PROBE -> k_a OVERWRITES XRF[2]  R: y16 (unchanged by probe)
  f  EPS-NORM k = XRF[2]                         R: eps_norm_fx(x, k_a) != b
  g  DYNQ16(big, clamp0=0, k -> XRF[1])          R: y16 (k>0 + rounding)
  h  EPS-NORM k = XRF[1]                         R: eps_norm_fx(x, k_b)
  i  VN mode 2 with ARG2 == 0                    R: l2norm_fx (back-compat)

Usage: gen_seq_layer_script.py <out.txt> <seed>
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "ref"))

import layer_fixed as LF           # noqa: E402
import layer_ref as LR             # noqa: E402
from w4a8_ref import rshift_round as rshr   # noqa: E402

I64 = np.int64

OP_VN, OP_ALU = 1, 11
AOP_EMUL32, AOP_DYNQ16 = 8, 12

# scratch map (16K x 16)
A_T32   = 0x0000       # tiny block, 128 int32 {lo,hi} pairs
A_T16   = 0x0200       # DYNQ16 output (k -> XRF[2])
A_NRM_T = 0x0300       # EPS-NORM with k_t
A_T16C  = 0x0400       # DYNQ16 clamp0 output (k -> XRF[1])
A_NRM_0 = 0x0500       # EPS-NORM with the clamped k (= 0)
A_PA    = 0x0600       # probe a, 48 int32 pairs
A_PB    = 0x0700       # probe b, 48 int16
A_PY    = 0x0780       # probe EMUL32 output
A_NRM_A = 0x0800       # EPS-NORM with k_a
A_B32   = 0x0900       # big block, 128 int32 pairs
A_B16   = 0x0B00       # DYNQ16 output (k -> XRF[1])
A_NRM_B = 0x0C00       # EPS-NORM with k_b
A_L2X   = 0x0D00       # legacy l2norm input
A_L2Y   = 0x0E00       # legacy l2norm output


def w16(v):
    return f"{int(v) & 0xFFFF:04x}"


def rec_w(f, addr, vals):
    f.write(f"W {addr:x} {len(vals):x}\n")
    f.write(" ".join(w16(v) for v in vals) + "\n")


def rec_r(f, addr, vals):
    f.write(f"R {addr:x} {len(vals):x}\n")
    f.write(" ".join(w16(v) for v in vals) + "\n")


def rec_c(f, op, a0, a1, a2):
    f.write(f"C {op:x} {a0 & 0xFFFFFFFF:x} {a1 & 0xFFFFFFFF:x} "
            f"{a2 & 0xFFFFFFFF:x}\n")


def alu(f, aop, length, srca, srcb, dst, p0):
    rec_c(f, OP_ALU, (length << 4) | aop, (srcb << 14) | srca,
          (dst << 17) | (p0 & 0x1FFFF))


def vn(f, mode, nlog2, inf, outf, src, dst, eps=0, xrf=0):
    rec_c(f, OP_VN, (outf << 10) | (inf << 6) | (nlog2 << 2) | mode,
          (dst << 14) | src, (xrf << 1) | eps)


def pairs(x32):
    out = []
    for v in np.asarray(x32, dtype=I64):
        out.append(int(v) & 0xFFFF)
        out.append((int(v) >> 16) & 0xFFFF)
    return out


def main():
    path, seed = sys.argv[1], int(sys.argv[2])
    rng = np.random.default_rng(1000 + seed)
    n = LR.LDV                       # 128, n_log2 = 7
    nlog2, inf, outf = 7, LF.S_F, LF.DN_NORM_F

    # ---- tiny block: bitlen(|max|) around 5 -> DYNQ16 k around -10, where
    # the eps addend E dominates ss and the k plumbing is observable ----
    tiny = None
    for _ in range(200):
        L = int(rng.integers(3, 8))
        hi = (1 << L) - 1
        t = rng.integers(-hi, hi + 1, n, dtype=np.int64)
        t[int(rng.integers(0, n))] = hi
        t16, kt = LF.dynq16_fx(t)
        t16c, ktc = LF.dynq16_fx(t, clamp0=True)
        y_t = LF.eps_norm_fx(t16, kt, note=False)
        y_0 = LF.eps_norm_fx(t16, ktc, note=False)
        if kt < 0 and not np.array_equal(y_t, y_0) \
                and not np.array_equal(t16, t16c):
            tiny = (t, t16, kt, t16c, ktc, y_t, y_0)
            break
    assert tiny is not None, "no discriminating tiny block found"
    t32, t16, kt, t16c, ktc, y_t, y_0 = tiny

    # ---- op-8 probe block; its k_a must ALSO be distinguishable ----
    npr, probe = 48, None
    for _ in range(200):
        pa = np.clip(np.round(rng.normal(0, 2.0 ** float(rng.integers(6, 26)),
                                         npr)), -(1 << 31), (1 << 31) - 1
                     ).astype(I64)
        pb = np.clip(np.round(rng.normal(0, 9000, npr)), -32768,
                     32767).astype(I64)
        ka = LF.attn_o_shift(int(np.abs(pa * pb).max()), note=False)
        y_a = LF.eps_norm_fx(t16, ka, note=False)
        if ka > 0 and not np.array_equal(y_a, y_t):
            probe = (pa, pb, ka, y_a)
            break
    assert probe is not None, "no discriminating probe block found"
    pa, pb, ka, y_a = probe
    py = LF.clip16(rshr(pa * pb, ka))

    # ---- big block: k > 0, the rounding-fixup side of the exponent ----
    amp = 2.0 ** float(rng.integers(2, 8))
    b32 = np.clip(np.round(rng.normal(0, amp, n) * (1 << LF.S_F)),
                  -(1 << 31), (1 << 31) - 1).astype(I64)
    b16, kb = LF.dynq16_fx(b32)
    assert kb > 0, kb
    y_b = LF.eps_norm_fx(t16, kb, note=False)

    # ---- legacy l2norm (mode 2, ARG2 = 0): the back-compat invariant ----
    l2x = np.round(rng.normal(0, 1.5, n) * (1 << LF.QKV_F)).astype(I64)
    l2y = LF.l2norm_fx(l2x, LF.QKV_F, LF.NRM_F)
    LF.bf_reset()

    with open(path, "w") as f:
        rec_w(f, A_T32, pairs(t32))
        rec_w(f, A_PA, pairs(pa))
        rec_w(f, A_PB, pb)
        rec_w(f, A_B32, pairs(b32))
        rec_w(f, A_L2X, l2x)

        alu(f, AOP_DYNQ16, n, A_T32, 0, A_T16, 0b01)      # k_t -> XRF[2]
        rec_r(f, A_T16, t16)
        vn(f, 2, nlog2, inf, outf, A_T16, A_NRM_T, eps=1, xrf=2)
        rec_r(f, A_NRM_T, y_t)

        alu(f, AOP_DYNQ16, n, A_T32, 0, A_T16C, 0b10)     # clamp0 -> XRF[1]
        rec_r(f, A_T16C, t16c)
        vn(f, 2, nlog2, inf, outf, A_T16, A_NRM_0, eps=1, xrf=1)
        rec_r(f, A_NRM_0, y_0)

        alu(f, AOP_EMUL32, npr, A_PA, A_PB, A_PY, ka | 64)  # probe -> XRF[2]
        rec_r(f, A_PY, py)
        vn(f, 2, nlog2, inf, outf, A_T16, A_NRM_A, eps=1, xrf=2)
        rec_r(f, A_NRM_A, y_a)

        alu(f, AOP_DYNQ16, n, A_B32, 0, A_B16, 0b00)      # k_b -> XRF[1]
        rec_r(f, A_B16, b16)
        vn(f, 2, nlog2, inf, outf, A_T16, A_NRM_B, eps=1, xrf=1)
        rec_r(f, A_NRM_B, y_b)

        vn(f, 2, nlog2, LF.QKV_F, LF.NRM_F, A_L2X, A_L2Y)  # ARG2 == 0
        rec_r(f, A_L2Y, l2y)
        f.write("Q\n")

    print(f"seq layer script: seed={seed} -> {path}  k_t={kt} k_clamp0={ktc} "
          f"k_a={ka} k_b={kb}; goldens distinct: "
          f"y(k_t)!=y(0) {not np.array_equal(y_t, y_0)}, "
          f"y(k_t)!=y(k_a) {not np.array_equal(y_t, y_a)}, "
          f"y(k_t)!=y(k_b) {not np.array_equal(y_t, y_b)}")


if __name__ == "__main__":
    main()
