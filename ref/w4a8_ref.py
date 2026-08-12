#!/usr/bin/env python3
"""Bit-accurate W4A8 matvec reference (see quant_spec.md — spec is frozen).

Pure-integer pipeline. This file is THE definition of correct behavior for
the stage-2 RTL: the Verilator TB compares RTL outputs against these
functions bit for bit.

Also provides: quantizer (fp matrix -> packed W4 + scales + requant consts),
DDR image packing per quant_spec.md layout, and a self-test
(`python3 w4a8_ref.py`) checking quantized-vs-fp accuracy and invariants.

======================================================================
GROUP SIZE g — the v2 row format (g=128 legacy | g=64 opt-in)
======================================================================
`g` is the number of consecutive K-elements that share one uint16 scale
mantissa.  g == 128 (the default, `G`) is the legacy format: every artifact
committed before the v2 upgrade is g=128 and stays BIT-IDENTICAL.  g == 64
is a wire-format option that halves the group size (measured ~+2/24 top-1
against bf16, evidence/stage5/fidelity_phase0_0c_w4strategy.log) at the cost
of one extra 64-byte scale beat on the widest matrices.

Row layout, BOTH modes (K must be a multiple of 128):

  [ weight beats ][ scale beats ]      then zero-pad to the 64B stride

  weight beats = K // 128, ALWAYS — a 64-byte beat always carries 128
      nibble-packed weights, and the nibble packing inside a byte is
      identical in both modes (`pack_w4`: low nibble = even k).
      * g=128: beat i IS group i (128 weights).
      * g=64 : beat i carries TWO consecutive groups —
               group 2i   = bytes  0..31 (k = 128i     .. 128i+63)
               group 2i+1 = bytes 32..63 (k = 128i+64  .. 128i+127)
      The BYTES are the same in both modes; only the scale indexing moves.

  scale beats = ceil(NG / 32) where NG = K // g, i.e. the uint16 group
      mantissas in group order, little-endian, 32 per 64-byte beat, unused
      tail zeroed.  g=128 with K <= 4096 is always exactly 1 scale beat
      (unchanged from the pre-v2 format); g=64 needs 2 once K > 2048.

  row stride = (weight_beats + scale_beats) * 64, 64B aligned by
      construction.  `row_beats()` / `row_stride()` are the single source of
      this arithmetic; the manifest emitters and sw/ hosts derive from them.

The SHAPE CSR carries the mode in bit 28 (0 = g128 legacy, 1 = g64); its
`ng` field keeps its pre-v2 meaning = WEIGHT-beat count = K//128 in both
modes.  See sw/hwmap.py:SHAPE_G64.
"""
import numpy as np

G = 128                 # default / legacy group size (quant_spec.md)
G_WIRE = (128, 64)      # group sizes with a defined DDR wire format
K_PER_WBEAT = 128       # weights per 64-byte weight beat (both modes)
SCALES_PER_BEAT = 32    # uint16 group mantissas per 64-byte scale beat


def rshift_round(v, s):
    """Arithmetic right shift with round-half-away-from-zero. v: int array/scalar.
    Negative s = exact left shift (matches RTL rshr64s)."""
    v = np.asarray(v, dtype=np.int64)
    if s == 0:
        return v
    if s < 0:
        return v << np.int64(-s)
    add = np.int64(1) << np.int64(s - 1)
    return np.where(v >= 0, (v + add) >> np.int64(s), -((-v + add) >> np.int64(s)))


def row_beats(K, g=G):
    """(weight_beats, scale_beats) of one v2 row — see the module header."""
    assert g in G_WIRE, f"group size {g} has no defined wire format"
    assert K % K_PER_WBEAT == 0, f"K={K} must be a multiple of {K_PER_WBEAT}"
    wb = K // K_PER_WBEAT
    sb = (K // g + SCALES_PER_BEAT - 1) // SCALES_PER_BEAT
    return wb, sb


def row_stride(K, g=G):
    """Byte stride between rows of a v2 DDR weight image."""
    wb, sb = row_beats(K, g)
    return (wb + sb) * 64


def group_size_of(w4, m, g=None):
    """Infer (and check) the group size of a quantized matrix pair (w4, m)."""
    K = w4.shape[1]
    ng = m.shape[1]
    assert ng > 0 and K % ng == 0, f"m has {ng} groups, incompatible with K={K}"
    gi = K // ng
    if g is not None:
        assert int(g) == gi, f"declared g={g} but w4/m imply {gi}"
    return gi


def quantize_weights(W, g=G):
    """FP weight matrix (N,K) -> (w4 (N,K) int8 in [-8,7], m (N,NG) uint16, e int).

    Per-group symmetric: scale_g = max|W_group| / 7. Stored as m_g * 2^(e-15)
    with one shared exponent e per matrix chosen so max m fits in uint16.

    `sh` is INDEPENDENT of g: p_bound = (K/g)*65535*(g*8*127) = K*65535*1016,
    so a g=64 image reuses the g=128 final shift exactly.
    """
    N, K = W.shape
    assert K % g == 0, f"K={K} not divisible by group size {g}"
    NG = K // g
    Wg = W.reshape(N, NG, g)
    smax = np.abs(Wg).max(axis=2)            # (N, NG)
    smax = np.maximum(smax, 1e-12)
    scale = smax / 7.0
    # shared exponent: m = scale * 2^(15-e) must fit uint16
    e = int(np.ceil(np.log2(scale.max()))) + 1   # scale_max * 2^(15-e) < 2^16
    m = np.round(scale * np.exp2(15 - e)).astype(np.uint32)
    m = np.clip(m, 1, 65535).astype(np.uint16)   # (N, NG)
    # effective scale actually stored (for accuracy eval / requant consts)
    eff_scale = m.astype(np.float64) * np.exp2(e - 15)
    w4 = np.clip(np.round(Wg / eff_scale[:, :, None]), -8, 7).astype(np.int8)
    # final shift: smallest sh with worst-case |p| * 2^-sh < 2^31
    p_bound = NG * 65535 * (g * 8 * 127)
    sh = max(0, p_bound.bit_length() - 31)
    return w4.reshape(N, K), m, e, sh


def quantize_acts(x):
    """FP vector -> (x8 int8, x_scale float)."""
    s = max(np.abs(x).max() / 127.0, 1e-12)
    x8 = np.clip(np.round(x / s), -128, 127).astype(np.int8)
    return x8, s


def matvec_y32(w4, m, sh, x8, g=None):
    """Steps 1-3 of quant_spec.md. Returns int32 y (N,). Bit-exact reference.

    Dequantization scale of the result is xs * 2^(e-15+sh).

    `g` (group size) defaults to the value implied by w4/m — K // m.shape[1]
    — so a g=64 quantized pair needs no extra plumbing at any call site.

    ACCUMULATE ORDER (the RTL is built to THIS function).
      p = SUM over groups gi of  m[gi] * (SUM over the g weights of w4*x8)
    The engine walks the row one 64-byte beat at a time.  At g=128 a beat is
    exactly one group and it accumulates `p += m[i] * beat_sum`.  At g=64 a
    beat is TWO groups and it accumulates, per beat i,

        p += m[2i] * lo_sum + m[2i+1] * hi_sum

    where lo_sum / hi_sum are the 64-term dot products of bytes 0..31 and
    32..63 of that beat.  Both forms are the same mathematical sum in a
    different order: every term is an exact integer (int64 here, wide fixed
    accumulators in the RTL, no intermediate truncation anywhere before
    `sh`), and integer addition is associative and commutative, so the
    beat-serial hardware order and this file's `.sum(axis=2)` / `.sum(axis=1)`
    order are BIT-IDENTICAL by construction — the grouping is notation, not
    numerics.  The only order-sensitive step is the single
    `rshift_round(p, sh)` at the end, which happens once, on the complete p.
    """
    N, K = w4.shape
    g = group_size_of(w4, m, g)
    NG = K // g
    acc = (w4.reshape(N, NG, g).astype(np.int64)
           * x8.astype(np.int64).reshape(1, NG, g)).sum(axis=2)   # (N,NG) int64
    assert np.abs(acc).max() < (1 << 31)
    p = (m.astype(np.int64) * acc).sum(axis=1)                    # (N,) int64
    y = rshift_round(p, sh)
    assert np.abs(y).max() < (1 << 31), "y32 overflow — sh miscomputed"
    return y.astype(np.int32)


def requant_i8(y32, M, S=31):
    """Step 4: int32 -> int8 with uint32 multiplier M, shift S."""
    v = y32.astype(np.int64) * np.int64(M)
    return np.clip(rshift_round(v, S), -128, 127).astype(np.int8)


def pack_w4(w4):
    """(N,K) int4-valued int8 -> (N, K//2) uint8, low nibble = even k."""
    u = (w4.astype(np.int16) & 0xF).astype(np.uint8)
    return (u[:, 0::2] | (u[:, 1::2] << 4)).astype(np.uint8)


def unpack_w4(packed, K):
    """Inverse of pack_w4 -> (N,K) int8 in [-8,7]."""
    lo = (packed & 0xF).astype(np.int8)
    hi = (packed >> 4).astype(np.int8)
    lo = np.where(lo > 7, lo - 16, lo)
    hi = np.where(hi > 7, hi - 16, hi)
    out = np.empty((packed.shape[0], K), dtype=np.int8)
    out[:, 0::2] = lo
    out[:, 1::2] = hi
    return out


def pack_ddr_rows(w4, m, g=None):
    """Per the module header: per row [weight beats | scale beats], 64B rows.

    g defaults to the value implied by w4/m.  The weight bytes are the SAME
    in both modes (pack_w4); only the number of uint16 mantissas — and hence
    the scale-beat count and the stride — changes.

    Returns (image_bytes, row_stride).
    """
    N, K = w4.shape
    g = group_size_of(w4, m, g)
    wb, sb = row_beats(K, g)
    pw = pack_w4(w4)                                  # (N, K//2)
    assert pw.shape[1] == wb * 64, "weight bytes are not a whole beat count"
    mb = m.astype('<u2').view(np.uint8).reshape(N, -1)
    assert mb.shape[1] <= sb * 64, "scale bytes overflow the scale beats"
    row = np.concatenate([pw, mb], axis=1)
    stride = (wb + sb) * 64
    assert stride == row_stride(K, g)
    img = np.zeros((N, stride), dtype=np.uint8)       # tail zeroed
    img[:, :row.shape[1]] = row
    return img.tobytes(), stride


def unpack_ddr_rows(img, nrows, K, g=G):
    """Inverse of pack_ddr_rows — the ENGINE's view of a DDR weight image.

    Reads the row format back out of raw bytes (weight beats then scale
    beats, tail ignored) and returns (w4 (N,K) int8, m (N,NG) uint16).  Used
    by the self-test to prove pack->wire->unpack->matvec round-trips.
    """
    wb, sb = row_beats(K, g)
    stride = (wb + sb) * 64
    a = np.frombuffer(img, dtype=np.uint8)
    assert a.size == nrows * stride, \
        f"image is {a.size}B, expected {nrows}*{stride}={nrows * stride}"
    a = a.reshape(nrows, stride)
    w4 = unpack_w4(a[:, :wb * 64], K)
    NG = K // g
    mb = a[:, wb * 64:wb * 64 + 2 * NG].copy()
    m = mb.view('<u2').reshape(nrows, NG)
    return w4, m


def _selftest():
    rng = np.random.default_rng(7)
    for (N, K) in [(1024, 1024), (256, 3584), (64, 256)]:
        W = rng.normal(0, 0.02, (N, K))
        x = rng.normal(0, 1.0, K)
        w4, m, e, sh = quantize_weights(W)
        x8, xs = quantize_acts(x)
        y32 = matvec_y32(w4, m, sh, x8)
        y_hat = y32.astype(np.float64) * xs * np.exp2(e - 15 + sh)
        ref = W @ x
        rel = np.linalg.norm(y_hat - ref) / np.linalg.norm(ref)
        # pipeline-exactness check vs dequantized weights (isolates the
        # integer pipeline from inherent INT4 quantization noise):
        NG = K // G
        eff = m.astype(np.float64) * np.exp2(e - 15)          # (N,NG)
        Wq = w4.reshape(N, NG, G).astype(np.float64) * eff[:, :, None]
        ref_q = (Wq.reshape(N, K) @ x8.astype(np.float64)) * np.exp2(15 - e - sh)
        rel_q = np.linalg.norm(y32 - ref_q) / np.linalg.norm(ref_q)
        abs_q = np.abs(y32 - ref_q).max()
        # pack/unpack roundtrip
        assert (unpack_w4(pack_w4(w4), K) == w4).all()
        # rshift_round sanity
        assert rshift_round(5, 1) == 3 and rshift_round(-5, 1) == -3
        assert rshift_round(4, 2) == 1 and rshift_round(-4, 2) == -1
        img, stride = pack_ddr_rows(w4, m)
        assert len(img) == N * stride
        print(f"N={N:5d} K={K:5d}: rel_fp={rel:.3%} (INT4 noise floor) "
              f"rel_pipeline={rel_q:.2e} max_lsb={abs_q:.2f} stride={stride}B e={e} sh={sh}")
        # ~12% is the expected INT4-on-Gaussian noise floor; the integer
        # pipeline must match dequantized math to the final-shift rounding
        # (<= 0.5 lsb by construction; allow 0.51 for fp64 compare slop)
        assert rel < 0.15, "quantization error above INT4 noise floor"
        assert abs_q <= 0.51, "integer pipeline deviates beyond final rounding"
    _selftest_wire()
    print("W4A8_REF SELFTEST PASS")


def _selftest_wire():
    """v2 row format: g=128 invariance + g=64 pack->wire->unpack->matvec.

    K=1024 exercises the 1-scale-beat case, K=3584 the 2-scale-beat case
    (the widest matrix in the model: mlp.down).
    """
    print("--- v2 row format (g=128 legacy | g=64) ---")
    for seed in (1, 2, 3, 4):
        rng = np.random.default_rng(seed)
        for (N, K) in [(64, 1024), (37, 3584), (256, 2048), (5, 128)]:
            W = rng.normal(0, 0.02, (N, K))
            x = rng.normal(0, 1.0, K)
            x8, xs = quantize_acts(x)
            row = {}
            for g in (128, 64):
                w4, m, e, sh = quantize_weights(W, g=g)
                assert m.shape == (N, K // g)
                # --- wire arithmetic matches the frozen contract ---
                wb, sb = row_beats(K, g)
                assert wb == K // 128
                assert sb == -(-(K // g) // 32)
                img, stride = pack_ddr_rows(w4, m)
                assert stride == (wb + sb) * 64 == row_stride(K, g)
                assert len(img) == N * stride
                # weight BYTES are mode-independent (same nibble packing)
                a = np.frombuffer(img, np.uint8).reshape(N, stride)
                assert (a[:, :wb * 64] == pack_w4(w4)).all()
                assert (a[:, wb * 64 + 2 * (K // g):] == 0).all(), "tail not zeroed"
                # --- pack -> wire -> unpack -> matvec, vs a dense reference ---
                w4b, mb = unpack_ddr_rows(img, N, K, g)
                assert (w4b == w4).all() and (mb == m).all()
                y = matvec_y32(w4b, mb, sh, x8)
                y_ref = matvec_y32(w4, m, sh, x8, g=g)
                assert (y == y_ref).all()
                # independent dense (non-grouped) integer reference: the
                # engine's beat-pair order written out the long way
                NG = K // g
                p = np.zeros(N, dtype=object)
                for gi in range(NG):
                    s = (w4[:, gi * g:(gi + 1) * g].astype(np.int64)
                         * x8[gi * g:(gi + 1) * g].astype(np.int64)).sum(axis=1)
                    p = p + m[:, gi].astype(np.int64) * s
                y_dense = rshift_round(np.array([int(v) for v in p],
                                                dtype=np.int64), sh)
                assert (y == y_dense).all(), (N, K, g, seed)
                # float accuracy of this image
                eff = m.astype(np.float64) * np.exp2(e - 15)
                deq = (w4.reshape(N, NG, g).astype(np.float64)
                       * eff[:, :, None]).reshape(N, K)
                y_hat = y.astype(np.float64) * xs * np.exp2(e - 15 + sh)
                rel = (np.linalg.norm(y_hat - W @ x) / np.linalg.norm(W @ x))
                row[g] = (stride, wb, sb, rel,
                          float(np.linalg.norm(deq - W) / np.linalg.norm(W)))
            if seed == 1:
                print(f"  N={N:4d} K={K:5d}  "
                      + "  ".join(
                          f"g{g}: {v[1]}w+{v[2]}s beats stride={v[0]:5d}B "
                          f"rel_fp={v[3]:.3%} rel_W={v[4]:.3%}"
                          for g, v in row.items()))
            # g=64 must not be WORSE on the weight reconstruction
            assert row[64][4] <= row[128][4] + 1e-12
    # explicit contract arithmetic for the shapes the model actually uses
    want = {(1024, 128): (8, 1), (1024, 64): (8, 1),
            (2048, 128): (16, 1), (2048, 64): (16, 1),
            (3584, 128): (28, 1), (3584, 64): (28, 2)}
    for (K, g), exp in sorted(want.items()):
        assert row_beats(K, g) == exp, (K, g, row_beats(K, g), exp)
    print("  contract beat counts OK: " + ", ".join(
        f"K={K} g{g} -> {w}w+{s}s ({(w + s) * 64}B)"
        for (K, g), (w, s) in sorted(want.items())))


if __name__ == "__main__":
    _selftest()
