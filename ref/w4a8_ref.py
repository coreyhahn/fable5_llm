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
group modes (W4 ONLY — see the W8 section below, where `ng` still means
K//128 but a row streams 2*ng weight beats).  See sw/hwmap.py:SHAPE_G64.

======================================================================
W8 — the 8-bit weight twin (Track Q V5; gate D picked it, RTL exists)
======================================================================
`quantize_weights8` / `row_beats8` / `pack_ddr_rows8` / `matvec_y32_w8` are
the 8-bit mirror of the four functions above.  They were written so the
Track Q study could price a W8 variant with the SAME production arithmetic
and the SAME wire law the W4 path uses, instead of an idealized
bits/weight rate; gate D then picked V5 (W8 everywhere), so they are now
also the LAW the engine is built to.  `rtl/matvec_engine.sv`'s `cfg_w8`
mode (SHAPE bit 29) consumes exactly this format, and tb_matvec's W8
goldens come from `matvec_y32_w8` + `pack_ddr_rows8`
(evidence/qwen2b/q2/v4_v5/W8_SKETCH.md is the engine's costing basis).

Everything that is not the weight width is UNCHANGED — the scale encoding
(uint16 mantissa per group + one shared exponent, value m*2^(e-15)), the
final shift `sh`, `matvec_y32`, `rshift_round`, the 64-byte beat, the
[weights | scales] row order and the zero-padded stride.  Only two things
move, and both follow from "a weight is a byte, not a nibble":

  weight beats = K // 64   (was K // 128; `K_PER_WBEAT8`)
  scale beats  = ceil((K/g) / 32), IDENTICAL to W4 — the scales did not
      change, so a W8 g128 row has exactly the scale cadence of a W4 g128
      row of the same K.

  row stride8 = (K//64 + ceil((K/g)/32)) * 64 bytes.

`sh` DOES move: the per-group product bound grows with the weight range
(p_bound = NG*65535*(g*127*127) against W4's NG*65535*(g*8*127)), i.e. ~4
more bits, which `quantize_weights8` computes with the same rule.
"""
import numpy as np

G = 128                 # default / legacy group size (quant_spec.md)
G_WIRE = (128, 64)      # group sizes with a defined DDR wire format
K_PER_WBEAT = 128       # weights per 64-byte weight beat (both modes)
K_PER_WBEAT8 = 64       # weights per 64-byte weight beat, W8 (1 byte each)
SCALES_PER_BEAT = 32    # uint16 group mantissas per 64-byte scale beat
W4_QMAX = 7             # quantize_weights scales to +-7 (rail -8 is reachable)
W8_QMAX = 127           # quantize_weights8: symmetric, -128 never emitted


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


def row_beats8(K, g=G):
    """(weight_beats, scale_beats) of one W8 row — see the W8 module header.

    Same contract as `row_beats`, one substitution: a 64-byte beat carries 64
    weights instead of 128 because a W8 weight is a whole byte.  The scale
    beats are IDENTICAL to W4's for the same (K, g).

    K keeps W4's legality rule (a multiple of 128).  That is not arithmetic —
    64 would divide evenly — it is so the SHAPE CSR's 6-bit `ng` field can go
    on meaning K//128 in W8 mode too (weight beats = 2*ng), which is the only
    encoding that fits the model's K=6144 rows without widening a field.
    See W8_SKETCH.md.
    """
    assert g in G_WIRE, f"group size {g} has no defined wire format"
    assert K % K_PER_WBEAT == 0, f"K={K} must be a multiple of {K_PER_WBEAT}"
    wb = K // K_PER_WBEAT8
    sb = (K // g + SCALES_PER_BEAT - 1) // SCALES_PER_BEAT
    return wb, sb


def row_stride8(K, g=G):
    """Byte stride between rows of a W8 DDR weight image."""
    wb, sb = row_beats8(K, g)
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


def quantize_weights8(W, g=G, rowchunk=None):
    """FP weight matrix (N,K) -> (w8 (N,K) int8 in [-127,127], m uint16, e, sh).

    The 8-bit twin of `quantize_weights`, line for line: per-group symmetric,
    scale_g = max|W_group| / 127, stored as m_g * 2^(e-15) with one shared
    exponent per matrix.  Because the (m, e) encoding is byte-for-byte the W4
    one, the reconstruction is the SAME formula the whole chain already
    verifies (`perplexity_eval.dequant_from_q`, arbitrated against
    `matvec_y32` in that file's selftest A):  W_hat = w8 * m * 2^(e-15).

    The range is [-127, 127], NOT int8's full [-128, 127]: a symmetric range
    keeps `-w` representable for every representable `w`, and -128 would buy
    one code at the cost of that property (and of a special case in every
    consumer).  It costs 1/128 of the dynamic range, i.e. 0.007 bits.

    `sh` is INDEPENDENT of g exactly as in W4 (p_bound = K*65535*16129), but
    it is NOT the W4 value: the weight range is 127 rather than 8, so the
    product bound grows by ~4 bits and so does the final shift.

    Two deliberate differences from `quantize_weights`, both aligning this
    function with the PRODUCTION W4 path rather than with the legacy one:

    * the arithmetic is float64 regardless of the input dtype, which is what
      `layer_fixed.quant_linear_mse` / `gen_model_script.quant_linear_big`
      already do (the frozen `quantize_weights` inherits its input's dtype);
    * `rowchunk` evaluates the matrix in row blocks, exactly as
      `quant_linear_big` does and for the same reason — a one-shot call on
      the 248320x2048 tied head needs a 4 GiB float64 temporary.  Chunking
      is bit-identical by construction (`e` is the only matrix-wide term and
      it is computed from the per-group maxima before any block is
      quantized); `_selftest_w8` asserts that identity rather than assuming
      it.  `None` (default) = one shot.
    """
    W = np.asarray(W)
    N, K = W.shape
    assert K % g == 0, f"K={K} not divisible by group size {g}"
    NG = K // g
    rc = int(rowchunk) if rowchunk else N

    def _blk(r0, r1):
        return np.asarray(W[r0:r1], dtype=np.float64).reshape(r1 - r0, NG, g)

    smax = np.empty((N, NG), dtype=np.float64)
    for r0 in range(0, N, rc):
        r1 = min(r0 + rc, N)
        smax[r0:r1] = np.abs(_blk(r0, r1)).max(axis=2)
    smax = np.maximum(smax, 1e-12)
    scale = smax / float(W8_QMAX)
    # shared exponent: m = scale * 2^(15-e) must fit uint16
    e = int(np.ceil(np.log2(scale.max()))) + 1   # scale_max * 2^(15-e) < 2^16
    m = np.round(scale * np.exp2(15 - e)).astype(np.uint32)
    m = np.clip(m, 1, 65535).astype(np.uint16)   # (N, NG)
    eff_scale = m.astype(np.float64) * np.exp2(e - 15)
    w8 = np.empty((N, K), dtype=np.int8)
    for r0 in range(0, N, rc):
        r1 = min(r0 + rc, N)
        w8[r0:r1] = np.clip(np.round(_blk(r0, r1) / eff_scale[r0:r1, :, None]),
                            -W8_QMAX, W8_QMAX).astype(np.int8).reshape(r1 - r0, K)
    # final shift: smallest sh with worst-case |p| * 2^-sh < 2^31
    p_bound = NG * 65535 * (g * W8_QMAX * 127)
    sh = max(0, p_bound.bit_length() - 31)
    return w8, m, e, sh


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


def matvec_y32_w8(w8, m, sh, x8, g=None):
    """`matvec_y32` for a W8 image — the SAME arithmetic, named for the W8 law.

    W8 is a WIRE change, not an arithmetic one.  The scale encoding
    (`m * 2^(e-15)` with one shared exponent), the group accumulation order
    (`p = SUM_gi m[gi] * SUM_k w[k]*x8[k]`) and the SINGLE final
    `rshift_round(p, sh)` are byte-for-byte `matvec_y32`'s — only the code
    range of `w` moved from [-8,7] to [-127,127], which `matvec_y32` already
    handles because every intermediate there is an exact int64.

    So this function DELEGATES rather than restating the formula.  That is
    deliberate: the reviews have twice punished a re-derived scale/shift path
    drifting from the frozen one, and a copy cannot drift if there is no
    copy.  What it adds on top is the W8 CODE-RANGE contract that
    `quantize_weights8` / `pack_w8` promise and that the RTL's 21-bit
    per-beat accumulator is sized against (`W8_SKETCH.md:126`,
    `evidence/qwen2b/q2/v4_v5/selftest_w4a8_w8.log:20`): a byte outside
    [-127,127] is not a legal W8 code, and letting one through here would
    silently move the engine's width envelope.

    `g` behaves exactly as in `matvec_y32` (defaults to K // m.shape[1]).
    The wire law puts W8 at g=128 cadence only — that restriction lives in
    the SHAPE word (`sw/hwmap.shape_word(w8=True)` asserts it) and in the
    engine, NOT here: the arithmetic is group-size agnostic and the selftest
    exercises both g to prove it.
    """
    a = np.asarray(w8)
    assert a.dtype == np.int8, f"W8 weights must be int8, got {a.dtype}"
    assert a.min() >= -W8_QMAX and a.max() <= W8_QMAX, \
        f"W8 code out of range: [{a.min()}, {a.max()}] not in +-{W8_QMAX}"
    return matvec_y32(a, m, sh, x8, g=g)


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


def pack_w8(w8):
    """(N,K) int8 in [-127,127] -> (N,K) uint8, two's complement, k ascending.

    The W8 twin of `pack_w4`.  There is no packing to do — one weight IS one
    byte — but the function exists so the byte order of a W8 weight beat has
    a single named definition, the way `pack_w4` owns the nibble order.
    """
    a = np.ascontiguousarray(w8, dtype=np.int8)
    assert a.min() >= -W8_QMAX, "-128 is not a legal W8 code (symmetric range)"
    return a.view(np.uint8)


def unpack_w8(packed, K):
    """Inverse of pack_w8 -> (N,K) int8 in [-127,127]."""
    a = np.ascontiguousarray(packed, dtype=np.uint8).view(np.int8)
    assert a.shape[1] == K, f"{a.shape[1]} weight bytes, expected K={K}"
    return a


def pack_ddr_rows8(w8, m, g=None):
    """`pack_ddr_rows` for W8: per row [weight beats | scale beats], 64B rows.

    Identical in structure to the W4 packer — same order, same 64-byte beat,
    same zeroed tail, same `row_stride8` arithmetic — with `pack_w8` in place
    of `pack_w4`.  Returns (image_bytes, row_stride).
    """
    N, K = w8.shape
    g = group_size_of(w8, m, g)
    wb, sb = row_beats8(K, g)
    pw = pack_w8(w8)                                  # (N, K)
    assert pw.shape[1] == wb * 64, "weight bytes are not a whole beat count"
    mb = m.astype('<u2').view(np.uint8).reshape(N, -1)
    assert mb.shape[1] <= sb * 64, "scale bytes overflow the scale beats"
    row = np.concatenate([pw, mb], axis=1)
    stride = (wb + sb) * 64
    assert stride == row_stride8(K, g)
    img = np.zeros((N, stride), dtype=np.uint8)       # tail zeroed
    img[:, :row.shape[1]] = row
    return img.tobytes(), stride


def unpack_ddr_rows8(img, nrows, K, g=G):
    """Inverse of `pack_ddr_rows8` — a W8 engine's view of a DDR image."""
    wb, sb = row_beats8(K, g)
    stride = (wb + sb) * 64
    a = np.frombuffer(img, dtype=np.uint8)
    assert a.size == nrows * stride, \
        f"image is {a.size}B, expected {nrows}*{stride}={nrows * stride}"
    a = a.reshape(nrows, stride)
    w8 = unpack_w8(a[:, :wb * 64].copy(), K)
    NG = K // g
    mb = a[:, wb * 64:wb * 64 + 2 * NG].copy()
    m = mb.view('<u2').reshape(nrows, NG)
    return w8, m


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
    _selftest_w8()
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


def _selftest_w8():
    """W8 (Track Q V4mix/V5): 8 bits must behave like 8 bits, and the row
    format must be the W4 law with one substitution.

    Three things are checked, in order of what a reviewer would doubt:

    1. ACCURACY.  The round-trip weight error of `quantize_weights8` must
       beat `quantize_weights`' on the SAME matrix by more than 4x.  The
       expectation is ~18x (the code range grows 7 -> 127), so 4x is a
       floor that only a real bug can break, not a tuned threshold.
    2. WIRE.  pack -> bytes -> unpack -> `matvec_y32` reproduces the
       in-memory pair exactly, the tail is zeroed, the stride is
       `row_stride8`, and the integer result equals an independent dense
       (non-grouped) accumulation written out the long way.
    3. ENVELOPE.  The numbers `W8_SKETCH.md` costs the engine with, derived
       here rather than asserted there: the per-group product bound, the
       resulting `sh`, and the widths a W8 datapath needs against the ones
       the W4 engine already has (`rtl/matvec_engine.sv`: 18-bit half-beat
       accumulators, 48-bit p, 6-bit sh, 6-bit ng = K//128).
    """
    print("--- W8 row format (Track Q V5; RTL: matvec_engine cfg_w8) ---")
    worst_ratio = np.inf
    worst_lsb = 0.0
    for seed in (1, 2, 3, 4):
        rng = np.random.default_rng(seed)
        for (N, K) in [(64, 1024), (37, 3584), (256, 2048), (5, 128),
                       (17, 6144)]:
            W = rng.normal(0, 0.02, (N, K))
            x = rng.normal(0, 1.0, K)
            x8, xs = quantize_acts(x)
            row = {}
            for g in (128, 64):
                NG = K // g
                w8, m, e, sh = quantize_weights8(W, g=g)
                assert m.shape == (N, NG)
                assert w8.min() >= -W8_QMAX and w8.max() <= W8_QMAX
                # row chunking is bit-identical (the head path uses it), and
                # so is a float32 input matrix (what the PPL harness passes)
                for rc in (1, 7, N):
                    c = quantize_weights8(W, g=g, rowchunk=rc)
                    assert np.array_equal(c[0], w8) and np.array_equal(c[1], m)
                    assert c[2] == e and c[3] == sh, (N, K, g, rc)
                f32 = quantize_weights8(W.astype(np.float32), g=g, rowchunk=7)
                assert f32[2] == e and f32[3] == sh
                # --- wire arithmetic ---
                wb, sb = row_beats8(K, g)
                assert wb == K // 64
                assert sb == -(-(K // g) // 32) == row_beats(K, g)[1]
                img, stride = pack_ddr_rows8(w8, m)
                assert stride == (wb + sb) * 64 == row_stride8(K, g)
                assert len(img) == N * stride
                a = np.frombuffer(img, np.uint8).reshape(N, stride)
                assert (a[:, :wb * 64] == pack_w8(w8)).all()
                assert (a[:, wb * 64 + 2 * NG:] == 0).all(), "tail not zeroed"
                # --- pack -> wire -> unpack -> matvec ---
                # This IS the TB's golden path: tb/scripts/gen_matvec_v2_
                # vectors.py packs with pack_ddr_rows8 and takes y32 from
                # matvec_y32_w8, so the engine is compared against exactly
                # the bytes+numerics arbitrated here.
                w8b, mb = unpack_ddr_rows8(img, N, K, g)
                assert (w8b == w8).all() and (mb == m).all()
                y = matvec_y32_w8(w8b, mb, sh, x8)
                assert (y == matvec_y32_w8(w8, m, sh, x8, g=g)).all()
                # the named W8 entry point must stay the W4 arithmetic: same
                # scale application, same single rshift_round, wider codes
                assert (y == matvec_y32(w8, m, sh, x8, g=g)).all()
                # independent dense integer reference (python ints, no numpy
                # overflow risk), the engine's group order written out long
                p = np.zeros(N, dtype=object)
                for gi in range(NG):
                    s = (w8[:, gi * g:(gi + 1) * g].astype(np.int64)
                         * x8[gi * g:(gi + 1) * g].astype(np.int64)).sum(axis=1)
                    p = p + m[:, gi].astype(np.int64) * s
                y_dense = rshift_round(np.array([int(v) for v in p],
                                                dtype=np.int64), sh)
                assert (y == y_dense).all(), (N, K, g, seed)
                # --- accuracy: W8 vs W4 on the SAME matrix ---
                eff = m.astype(np.float64) * np.exp2(e - 15)
                deq8 = (w8.reshape(N, NG, g).astype(np.float64)
                        * eff[:, :, None]).reshape(N, K)
                rel8 = float(np.linalg.norm(deq8 - W) / np.linalg.norm(W))
                # --- pipeline exactness vs DEQUANTIZED float math, i.e. the
                # arbitration `_selftest` (and perplexity_eval --selftest
                # section A) runs on the W4 path, run here on the W8 one:
                # matvec_y32_w8's integer result must equal
                # (w8 * m*2^(e-15)) @ x8 * 2^(15-e-sh) to the ONE final
                # rounding (<= 0.5 lsb by construction; 0.51 for fp64 slop).
                # This is what makes matvec_y32_w8 an arbiter of the
                # m*2^(e-15) law rather than an unchecked alias.
                ref_q = (deq8 @ x8.astype(np.float64)) * np.exp2(15 - e - sh)
                abs_q = float(np.abs(y.astype(np.float64) - ref_q).max())
                assert abs_q <= 0.51, (N, K, g, seed, abs_q)
                worst_lsb = max(worst_lsb, abs_q)
                w4, m4, e4, sh4 = quantize_weights(W, g=g)
                eff4 = m4.astype(np.float64) * np.exp2(e4 - 15)
                deq4 = (w4.reshape(N, NG, g).astype(np.float64)
                        * eff4[:, :, None]).reshape(N, K)
                rel4 = float(np.linalg.norm(deq4 - W) / np.linalg.norm(W))
                y_hat = y.astype(np.float64) * xs * np.exp2(e - 15 + sh)
                rel_fp = float(np.linalg.norm(y_hat - W @ x)
                               / np.linalg.norm(W @ x))
                assert rel4 / rel8 > 4.0, (N, K, g, seed, rel4, rel8)
                worst_ratio = min(worst_ratio, rel4 / rel8)
                row[g] = (stride, wb, sb, rel_fp, rel8, rel4, sh, sh4)
            if seed == 1:
                v = row[128]
                print(f"  N={N:4d} K={K:5d}  g128: {v[1]}w+{v[2]}s beats "
                      f"stride={v[0]:5d}B rel_fp={v[3]:.3%} "
                      f"rel_W={v[4]:.3%} (W4 {v[5]:.3%} = {v[5] / v[4]:.1f}x) "
                      f"sh={v[6]} (W4 {v[7]})")
    print(f"  W8 weight error beats W4's by >= {worst_ratio:.1f}x on every "
          f"shape/seed/g (floor 4x; codes {W4_QMAX} -> {W8_QMAX})")
    print(f"  matvec_y32_w8 == matvec_y32 on every pair above, and agrees "
          f"with dequantized float math to {worst_lsb:.2f} lsb (bound 0.51) "
          f"— the m*2^(e-15) law is the W4 one, unchanged")
    # matvec_y32_w8 owns the CODE-RANGE contract (pack_w8 owns the byte
    # order): -128 is not a legal W8 code, and letting one through would
    # silently move the engine's 21-bit per-beat accumulator envelope.
    caught = ""
    try:
        matvec_y32_w8(np.full((1, 128), -128, dtype=np.int8),
                      np.ones((1, 1), dtype=np.uint16), 0,
                      np.zeros(128, dtype=np.int8))
    except AssertionError as ex:
        caught = str(ex)
    assert "out of range" in caught, \
        f"matvec_y32_w8 accepted the illegal code -128 ({caught!r})"
    print(f"  illegal code -128 rejected: {caught}")
    # explicit contract arithmetic for the shapes the two models actually use
    want = {(1024, 128): (16, 1), (1024, 64): (16, 1),
            (2048, 128): (32, 1), (2048, 64): (32, 1),
            (3584, 128): (56, 1), (3584, 64): (56, 2),
            (6144, 128): (96, 2), (6144, 64): (96, 3)}
    for (K, g), exp in sorted(want.items()):
        assert row_beats8(K, g) == exp, (K, g, row_beats8(K, g), exp)
        # the scale side is EXACTLY W4's; only the weight side doubled
        assert row_beats8(K, g)[1] == row_beats(K, g)[1]
        assert row_beats8(K, g)[0] == 2 * row_beats(K, g)[0]
    print("  contract beat counts OK: " + ", ".join(
        f"K={K} g{g} -> {w}w+{s}s ({(w + s) * 64}B)"
        for (K, g), (w, s) in sorted(want.items()) if g == 128))
    # --- envelope for W8_SKETCH.md (derived here, quoted there) ----------
    for K in (2048, 6144):
        for g in (128, 64):
            NG = K // g
            pb = NG * 65535 * (g * W8_QMAX * 127)          # sh's own bound
            sh = max(0, pb.bit_length() - 31)
            assert quantize_weights8(np.random.default_rng(0)
                                     .normal(0, .02, (2, K)), g=g)[3] == sh
            # engine envelope uses the REAL activation rail (-128), not the
            # 127 the frozen sh rule carries
            p_max = NG * 65535 * (g * W8_QMAX * 128)
            half = 32 * W8_QMAX * 128        # one 32-lane half of a W8 beat
            half4 = 64 * 8 * 128             # W4's 64-lane half (RTL: 18b)
            beat = 64 * W8_QMAX * 128        # one whole 64-weight W8 beat
            sw = (lambda v: v.bit_length() + 1)          # signed width
            assert sw(half4) == 18, "W4 half-beat width moved"
            sh4 = quantize_weights(np.random.default_rng(1)
                                   .normal(0, .02, (2, K)), g=g)[3]
            print(f"  envelope K={K:5d} g{g:3d}: sh={sh:2d} (W4 {sh4:2d})  "
                  f"signed widths: p {sw(p_max)}b (RTL has 48)  "
                  f"32-lane half {sw(half)}b (W4 {sw(half4)}b)  "
                  f"64-lane beat {sw(beat)}b")


if __name__ == "__main__":
    _selftest()
