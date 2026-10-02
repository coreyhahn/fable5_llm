#!/usr/bin/env python3
"""Golden vectors for the sequencer rung-1 COMPUTE ops (docs/SEQ_ISA.md).

Feeds tb/tb_vec_alu.sv and tb/tb_vecnorm.sv (+seqdir=).  Distinct from
gen_seq_unit_vectors.py, which belongs to the SEQ-unit workstream and
generates record streams for tb/tb_seq_unit.sv — different consumers, files,
no shared state.  (Also named tb/scripts/gen_seq_vectors.py, DELETED b2f1223.)

Everything here comes out of ref/layer_fixed.py — this script only formats.
It NEVER writes into tb/vectors/ (the frozen unit-vector set); its output
lives in its own tree so the existing unit TB cases stay byte-identical.

  <out>/dynq16_cases.txt   vec_alu op 12 DYNQ16 (both clamp0 modes),
                           the whole _dynq16_cases edge set + live DN heads
  <out>/probe8_cases.txt   vec_alu op 8 EMUL32 probe (max|prod| + k_a)
  <out>/epsnorm_cases.txt  vecnorm EPS-NORM, 20 magnitude decades
  <out>/rms2048_{x16,w14,y16}.hex   vecnorm mode 0, N=2048 (n_log2 = 11)
  <out>/l2n2048_{x16,y16}.hex       vecnorm mode 2, N=2048 (n_log2 = 11)
  <out>/rms4096_{x16,w14,y16}.hex   vecnorm mode 0, N=4096 (n_log2 = 12)
  <out>/l2n4096_{x16,y16}.hex       vecnorm mode 2, N=4096 (n_log2 = 12)

File formats (whitespace separated, `%h` unless noted):

  dynq16_cases.txt : NCASES, then per case
                     LEN(dec) CLAMP0(dec) K(dec, signed)
                     LEN x32 words   then   LEN y16 words
  probe8_cases.txt : NCASES, then per case
                     LEN(dec) SHIFT(dec) KA(dec, signed) MAXP(hex, 48b)
                     LEN a32 words, LEN b16 words, LEN y16 words
  epsnorm_cases.txt: NCASES, then per case
                     N(dec) NLOG2(dec) INF(dec) OUTF(dec) K(dec, signed)
                     SCALE(dec)
                     N x16 words   then   N y16 words

Usage: gen_seq_c_vectors.py <out_dir> <seed>
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "ref"))

import fixedpoint as fp            # noqa: E402
import layer_fixed as LF           # noqa: E402

# G3.4 (spec 0b A2.1): the rmsnorm VECTOR fraction is PINNED, and it is a
# TB CONTRACT rather than the model's RS_F.  `tb/tb_vecnorm.sv` drives
# `cfg_inf`/`cfg_outf` as the literal 4'd8 on every rmsnorm case, so a
# vector generated at `LF.RS_F` silently stopped matching its own TB the
# moment A2.1 moved RS_F to 7 -- the trap Task 8 declared and A2.1 made
# live.  Pinning it here closes that at the root and costs NOTHING in
# coverage: vecnorm normalizes, so the fraction is a shift, not a shape.
# The value is 8 = what the TB drives, so this is BYTE-IDENTICAL to every
# vector generated before it at the default RS_F.
RMS_VEC_F = 8
import layer_ref as LR             # noqa: E402
from w4a8_ref import rshift_round as rshr   # noqa: E402

I64 = np.int64


def hx(v, bits):
    return f"{int(v) & ((1 << bits) - 1):0{(bits + 3) // 4}x}"


# ----------------------------------------------------------------------
# op 12 DYNQ16
# ----------------------------------------------------------------------
def dynq16_cases(rng, maxlen=128):
    """Every documented edge of the exponent path + a live DN-head sample.

    Mirrors ref/layer_fixed._dynq16_cases (bitlen sweep, the (32767.5,32768)
    rounding fixup family, zero blocks, int32 min/max, the tiny values) and
    adds the same blocks in clamp0 mode, which is the op-8 attention
    immediate (layer_fixed.attn_o_shift).
    """
    cases = []
    I32MIN, I32MAX = -(1 << 31), (1 << 31) - 1
    for L in range(1, 33):                      # every possible bitlen
        hi = min((1 << L) - 1, 1 << 31)
        lo = min(1 << (L - 1), 1 << 31)
        x = np.clip(rng.integers(-hi, hi + 1, 32, dtype=np.int64),
                    I32MIN, I32MAX)
        x[int(rng.integers(0, 32))] = int(
            np.clip(rng.choice([lo, -lo, hi, -hi]), I32MIN, I32MAX))
        cases.append(x)
    for k in range(1, 18):                      # the +1 rounding fixup
        base = 1 << (15 + k)
        for j in (1, 2, (1 << (k - 1)) if k > 1 else 1,
                  (1 << (k - 1)) + 1 if k > 1 else 2, 1 << k):
            m = base - j
            if 0 < m <= (1 << 31):
                cases.append(np.array([m, -m, 0, 1], dtype=I64))
                cases.append(np.array([-m, m // 3, 0, 0], dtype=I64))
    cases.append(np.zeros(maxlen, dtype=I64))               # all-zero block
    cases.append(np.zeros(1, dtype=I64))
    cases.append(np.full(8, -(1 << 31), dtype=I64))         # the |x| trap
    cases.append(np.full(8, (1 << 31) - 1, dtype=I64))
    cases.append(np.array([-(1 << 31), (1 << 31) - 1, 0, 1], dtype=I64))
    for v in (1, -1, 2, 16383, 16384, 32767, 32768, 32769, 65535, 65536):
        cases.append(np.array([v, -v, v // 2, 0], dtype=I64))
    # a few live DeltaNet head outputs (the real distribution)
    rngw = np.random.default_rng(int(rng.integers(1, 1 << 30)))
    wf = LR.init_layer_weights(rngw, "linear_attention")
    qd = LF.quant_layer(wf)["dn"]
    st = LF.new_cache_fx("linear_attention")
    live = []
    orig = LF.dn_o_shift

    def _rec(o32, note=True):
        live.append(np.asarray(o32, dtype=I64).copy())
        return orig(o32, note=note)

    LF.dn_o_shift = _rec
    try:
        for _ in range(2):
            xn = np.round(rngw.normal(0, 1, LR.H) * (1 << LF.RS_F)).astype(I64)
            LF.deltanet_decode_fx(LF.clip16(xn), qd, st)
    finally:
        LF.dn_o_shift = orig
    LF.bf_reset()
    cases.extend(live[:16])
    out = []
    for x in cases:
        x = np.asarray(x, dtype=I64)[:maxlen]
        for clamp0 in (False, True):
            y, k = LF.dynq16_fx(x, clamp0=clamp0)
            out.append((x, y, k, clamp0))
    return out


def write_dynq16(path, cases):
    with open(path, "w") as f:
        f.write(f"{len(cases)}\n")
        for x, y, k, clamp0 in cases:
            f.write(f"{len(x)} {int(clamp0)} {k}\n")
            f.write(" ".join(hx(v, 32) for v in x) + "\n")
            f.write(" ".join(hx(v, 16) for v in y) + "\n")


# ----------------------------------------------------------------------
# op 8 EMUL32 probe
# ----------------------------------------------------------------------
def probe8_cases(rng, ncase=24, n=48):
    """max|a32*b16| pre-shift + the k_a attn_o_shift derives from it."""
    out = []
    for c in range(ncase):
        amp = 2.0 ** int(rng.integers(0, 28))
        a = np.clip(np.round(rng.normal(0, amp, n)), -(1 << 31),
                    (1 << 31) - 1).astype(I64)
        b = np.clip(np.round(rng.normal(0, 8000, n)), -32768,
                    32767).astype(I64)
        if c == 0:                       # the |x| trap on both operands
            a[0], b[0] = -(1 << 31), -32768
        if c == 1:
            a[:] = 0
        if c == 2:                       # exact fixup family
            a[0], b[0] = (1 << 30) - 1, 2
        prod = a * b
        maxp = int(np.abs(prod).max())
        ka = LF.attn_o_shift(maxp, note=False)
        sh = int(rng.integers(0, 40)) if c > 2 else ka
        y = LF.clip16(rshr(prod, sh))
        out.append((a, b, y, sh, ka, maxp))
    LF.bf_reset()
    return out


def write_probe8(path, cases):
    with open(path, "w") as f:
        f.write(f"{len(cases)}\n")
        for a, b, y, sh, ka, maxp in cases:
            f.write(f"{len(a)} {sh} {ka} {hx(maxp, 48)}\n")
            f.write(" ".join(hx(v, 32) for v in a) + "\n")
            f.write(" ".join(hx(v, 16) for v in b) + "\n")
            f.write(" ".join(hx(v, 16) for v in y) + "\n")


# ----------------------------------------------------------------------
# vecnorm EPS-NORM
# ----------------------------------------------------------------------
def epsnorm_cases(rng, per_decade=3):
    """20 magnitude decades of DeltaNet head outputs, DN geometry.

    x16/k come out of DYNQ16 exactly as the on-chip schedule produces them,
    so this is the two ops chained the way the sequencer runs them.
    """
    n = LR.LDV                       # 128, n_log2 = 7
    nlog2 = int(np.log2(n))
    inf, outf = LF.S_F, LF.DN_NORM_F
    out = []
    for dec in range(-10, 10):
        amp = 2.0 ** dec
        for _ in range(per_decade):
            o = np.clip(np.round(rng.normal(0, amp, n) * (1 << LF.S_F)),
                        -(1 << 31), (1 << 31) - 1).astype(I64)
            o16, k = LF.dynq16_fx(o)
            scale = LF.eps_norm_scale(o16, k, note=False)
            y = LF.eps_norm_fx(o16, k, note=False)
            out.append((o16, y, k, scale, n, nlog2, inf, outf))
    # explicit edges: all-zero block over the whole k range (the only case
    # where the 16-bit scale clamp fires) and the tightest non-zero block
    for kz in (-14, 0, 8, 17):
        z = np.zeros(n, dtype=I64)
        out.append((z, LF.eps_norm_fx(z, kz, note=False), kz,
                    LF.eps_norm_scale(z, kz, note=False), n, nlog2, inf, outf))
        t = np.zeros(n, dtype=I64)
        t[0] = 16384
        out.append((t, LF.eps_norm_fx(t, kz, note=False), kz,
                    LF.eps_norm_scale(t, kz, note=False), n, nlog2, inf, outf))
    LF.bf_reset()
    return out


def write_epsnorm(path, cases):
    with open(path, "w") as f:
        f.write(f"{len(cases)}\n")
        for x, y, k, scale, n, nlog2, inf, outf in cases:
            f.write(f"{n} {nlog2} {inf} {outf} {k} {scale}\n")
            f.write(" ".join(hx(v, 16) for v in x) + "\n")
            f.write(" ".join(hx(v, 16) for v in y) + "\n")


# ----------------------------------------------------------------------
# vecnorm at the two SHIPPED hidden sizes — N = 2048 (Qwen3.5-2B, the
# n_log2 = 11 geometry) and N = 4096 (Qwen3.5-9B, n_log2 = 12).
# ----------------------------------------------------------------------
def wr_hex(path, vals, bits):
    with open(path, "w") as f:
        for v in np.asarray(vals).reshape(-1):
            f.write(hx(v, bits) + "\n")


def vecnorm_n_vectors(rng, out, n):
    """rmsnorm (mode 0, 1+w) and l2norm (mode 2) over `n` elements.

    N is HARD-CODED by the caller, not LR.H: these are UNIT vectors for
    rtl/vecnorm_unit.sv's n_log2 geometries and must not move with
    FABLE5_MODEL.  Same recipes as ref/gen_layer_vectors.py's N=1024
    rmsnorm / N=128 l2norm cases, so the only variable is the length.

    ONE set per call; `main` calls it TWICE and the ORDER IS LOAD-BEARING.
    N=2048 goes first, so the 2B regression G3.2 must not disturb keeps
    drawing from the same rng position it always did; N=4096 — the 9B
    geometry G3.2 widened rtl/vecnorm_unit.sv to carry — is appended after
    it.  The file names carry the length, so the two sets never collide.
    """
    # G3.4 (spec 0b A2.1): PINNED, not LF.RS_F -- see RMS_VEC_F above.
    x = np.round(rng.normal(0, 2, n) * (1 << RMS_VEC_F)).astype(I64)
    w = np.round(rng.normal(0, 0.1, n) * (1 << 14)).astype(I64)
    y = LF.rmsnorm_fx(x, w, RMS_VEC_F, True)
    wr_hex(f"{out}/rms{n}_x16.hex", x, 16)
    wr_hex(f"{out}/rms{n}_w14.hex", w, 16)
    wr_hex(f"{out}/rms{n}_y16.hex", y, 16)
    xl = np.round(rng.normal(0, 1.5, n) * (1 << LF.QKV_F)).astype(I64)
    wr_hex(f"{out}/l2n{n}_x16.hex", xl, 16)
    wr_hex(f"{out}/l2n{n}_y16.hex",
           LF.l2norm_fx(xl, LF.QKV_F, LF.NRM_F), 16)
    assert np.abs(x).max() < (1 << 15) and np.abs(xl).max() < (1 << 15)
    return n




def main():
    out, seed = sys.argv[1], int(sys.argv[2])
    os.makedirs(out, exist_ok=True)
    rng = np.random.default_rng(seed)
    dq = dynq16_cases(rng)
    write_dynq16(f"{out}/dynq16_cases.txt", dq)
    pr = probe8_cases(rng)
    write_probe8(f"{out}/probe8_cases.txt", pr)
    en = epsnorm_cases(rng)
    write_epsnorm(f"{out}/epsnorm_cases.txt", en)
    # LAST on purpose: appending here leaves every case above byte-identical
    # (one shared rng, consumed in order).  N=2048 stays FIRST for the same
    # reason: the 4096 set is appended after it, so the committed 2B
    # regression vectors are unchanged by G3.2.
    n2k = vecnorm_n_vectors(rng, out, 2048)
    n4k = vecnorm_n_vectors(rng, out, 4096)
    ks = sorted({k for _, _, k, _ in dq})
    print(f"seq vectors: seed={seed} -> {out}  "
          f"dynq16={len(dq)} (k {ks[0]}..{ks[-1]}), probe8={len(pr)}, "
          f"epsnorm={len(en)}, vecnorm N={n2k}+{n4k} (rmsnorm + l2norm)")
    _ = fp   # imported for parity with the other generators


if __name__ == "__main__":
    main()
