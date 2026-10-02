#!/usr/bin/env python3
"""NVFP4 fake-quantization for the NV1 simulation study (numpy only).

The format, as coded here (every rule below is asserted in `--selftest`):

* ELEMENT — E2M1, magnitudes {0, 0.5, 1, 1.5, 2, 3, 4, 6}, sign separate.
  Rounding is round-to-nearest on that grid with ties to the EVEN code, i.e.
  to the neighbour whose mantissa bit is 0 (0.25->0, 0.75->1, 1.25->1,
  1.75->2, 2.5->2, 3.5->4, 5->4).  |v| > 6 saturates to 6.  The same code
  table is used to quantize and to dequantize, so the tie rule cannot drift
  between the two.  Codes are carried as `q2 = 2 * value`, an int8 in
  [-12, 12] — the exact-integer form (every NVFP4 value is k * 0.5).
* STAGE-1 SCALE — one UE4M3 per block of 16 consecutive elements along K
  (the last axis): unsigned E4M3, bias 7, 3 mantissa bits, 127 finite codes
  (0x7F is the NaN code and is never produced), max 448 = 1.75 * 2^8.
  Normals (e >= 1): (1 + m/8) * 2^(e-7), smallest 2^-6.  SUBNORMALS ARE
  KEPT (gradual underflow): e = 0 gives m/8 * 2^-6, smallest 2^-9; a ratio
  below 2^-10 rounds to 0 and the block dequantizes to zeros.  Encoding is
  round-to-nearest, ties to even code (= even mantissa), saturating at 448.
  The value encoded is the block ratio  amax(block) / 6 / s_t.
* STAGE-2 SCALE — one FP32 s_t = amax / (6 * 448), rounded to float32, so
  every block ratio lands in [0, 448] (the float32 rounding of s_t can put the
  top block at 448 * (1 + 2^-24), which RNE saturates to 448).  Weights: amax
  of the whole (rotated) matrix.  Activations: amax of each TOKEN's vector
  (dynamic) or a per-site amax from a calibration pass (static).  An all-zero
  tensor has s_t = 0 and quantizes to zeros.
* EFFECTIVE BLOCK SCALE S = ue4m3(code) * s_t (exact in float64: 4 x 24
  significant bits); element code = e2m1_rne(x / S); value = code * S.  The
  float32 cast of `code * S` (the torch model is float32) is the ONE inexact
  step and it is <= 2^-24 relative.
* RHT — per input site, one random sign vector D (16 entries, seed recorded,
  derived from (seed, site name) by `rht_signs`), shared by every K-block of
  every matrix that reads that site: M = H16 diag(D) / 4 (orthonormal, H16 the
  Sylvester Hadamard) — the signs flip FIRST, then the Hadamard mixes.  The
  other order, diag(D) H16 (the brief's literal "(D·H16/4)·x"), is INERT: it only
  flips output signs, every quantizer here is sign-symmetric (Q(Dy) = D Q(y)
  exactly), so D cancels on the way back and every seed is bit-identical —
  measured at rung 1 (n19 seed 0 vs n23 seed 1), corrected here; selftest C
  asserts both facts.  Rotating a K-vector is x'_b = M x_b per block;
  weights rotate their ROWS the same way, W'_b = W_b M^T, so W' x' = W x.
  `rotate` / `unrotate` are the two directions (unrotate = the transpose).
* ACCOUNTING — ideal 4 + 8/16 = 4.5 bits/weight.  DDR row layout (the
  shipped `w4a8_ref.row_stride` law carried over): ceil(K/128) 64-byte
  weight beats (128 nibbles each) + ceil((K/16)/64) scale beats (64 UE4M3
  bytes each), the row padded to whole beats, plus one FP32 s_t per matrix.
  Every K that is a multiple of 1024 is exactly 4.5 bits/weight + 32 bits.
* A8 — the shipped activation rule (`fixedpoint.dyn_quant_i8`, fed by
  `layer_fixed.matvec_fx`): per matvec input VECTOR (= per token), a
  power-of-two scale 2^e with e the smallest integer such that
  round_half_away(amax / 2^e) <= 127; x8 = clip(round_half_away(x/2^e),
  -127, 127).  Float model of that rule: no upstream int16 grid (the int path
  additionally floors e at 0 on its Q.in_f input; not modelled).

Exact-integer property: every value is (q2/2) * (mu * 2^k) * s_t with q2 an
integer in [-12, 12] and mu an integer in [1, 15], so a bit-exact fixed-point
reference is a block-floating-point accumulation with shifts — `--selftest`
section E asserts exactly that decomposition.

    python3 ref/nvfp4.py --selftest
"""
import argparse
import sys
import zlib

import numpy as np

BLOCK = 16
E2M1_GRID = np.array([0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0])
E2M1_MAX = 6.0
E4M3_MAX = 448.0
IDEAL_BITS_PER_WEIGHT = 4.0 + 8.0 / BLOCK
TENSOR_SCALE_BITS = 32          # one FP32 s_t per matrix
K_PER_WBEAT = 128               # nibbles per 64-byte beat
SCALES_PER_BEAT = 64            # UE4M3 bytes per 64-byte beat


def _ue4m3_table():
    """Value of every finite UE4M3 code 0..126, increasing with the code."""
    vals = []
    for code in range(127):
        e, m = code >> 3, code & 7
        vals.append(m / 8.0 * 2.0 ** -6 if e == 0
                    else (1.0 + m / 8.0) * 2.0 ** (e - 7))
    return np.array(vals)


UE4M3_TABLE = _ue4m3_table()


def _rne_index(a, table):
    """Index of the nearest `table` entry to each a >= 0, ties to the EVEN
    index (whose low bit is the mantissa LSB for both code tables here),
    saturating at the last entry.  Midpoints of dyadic neighbours are exact
    in float64, so the tie test is exact."""
    mids = (table[1:] + table[:-1]) / 2.0
    lo = np.searchsorted(mids, a, side="left")     # mids strictly below a
    hi = np.searchsorted(mids, a, side="right")    # mids <= a
    return np.where((hi > lo) & (lo % 2 == 1), hi, lo)


def e2m1_q2(x):
    """float array -> int8 q2 = 2 * nearest E2M1 value (RNE, saturating)."""
    x = np.asarray(x, dtype=np.float64)
    if not np.all(np.isfinite(x)):
        raise ValueError("e2m1: non-finite input")
    idx = _rne_index(np.abs(x), E2M1_GRID)
    q2 = (2.0 * E2M1_GRID[idx]).astype(np.int8)
    return np.where(x < 0, -q2, q2).astype(np.int8)


def ue4m3_encode(v):
    """v >= 0 -> uint8 code 0..126 (RNE, ties to even mantissa, saturating
    at 448, subnormals kept, below 2^-10 -> 0)."""
    v = np.asarray(v, dtype=np.float64)
    if not np.all(np.isfinite(v)) or np.any(v < 0):
        raise ValueError("ue4m3: needs finite, non-negative input")
    return _rne_index(v, UE4M3_TABLE).astype(np.uint8)


def ue4m3_decode(code):
    return UE4M3_TABLE[np.asarray(code, dtype=np.int64)]


# ======================================================================
# stage-2 scale, block quantizer
# ======================================================================
def tensor_scale(amax):
    """FP32 s_t = amax / (6 * 448) (scalar or array)."""
    return np.float32(np.asarray(amax, dtype=np.float64)
                      / (E2M1_MAX * E4M3_MAX))


def _blocks(X):
    X = np.asarray(X, dtype=np.float64)
    K = X.shape[-1]
    if K % BLOCK:
        raise ValueError(f"NVFP4: K={K} is not a multiple of {BLOCK}")
    return X.reshape(X.shape[:-1] + (K // BLOCK, BLOCK))


def quantize(X, s_t):
    """Block-16 NVFP4 along the last axis.

    `s_t` broadcasts against X.shape[:-1] (a scalar for a weight matrix or a
    static activation scale; one value per row for dynamic per-token).
    Returns (q2 int8 X.shape, sc uint8 X.shape[:-1]+(K/16,), S float64 same
    shape as sc = the effective block scale ue4m3(sc) * s_t).
    """
    B = _blocks(X)
    st = np.asarray(s_t, dtype=np.float32).astype(np.float64)
    st = np.broadcast_to(st, B.shape[:-2])[..., None]          # (..., 1)
    amax_b = np.abs(B).max(axis=-1)                            # (..., NB)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(st > 0, amax_b / E2M1_MAX / st, 0.0)
    sc = ue4m3_encode(ratio)
    S = ue4m3_decode(sc) * st
    with np.errstate(divide="ignore", invalid="ignore"):
        y = np.where(S[..., None] > 0, B / S[..., None], 0.0)
    q2 = e2m1_q2(y)
    return q2.reshape(np.shape(X)), sc, S


def dequantize(q2, S):
    """float64 values q2/2 * S (exact)."""
    B = _blocks(q2)
    return (B * 0.5 * S[..., None]).reshape(np.shape(q2))


def fake_quant(X, s_t):
    return dequantize(*quantize(X, s_t)[::2])


def fake_quant_dynamic_rows(X):
    """Per-row (per-token) dynamic s_t, rows = every axis but the last."""
    X = np.asarray(X, dtype=np.float64)
    return fake_quant(X, tensor_scale(np.abs(X).max(axis=-1)))


# ======================================================================
# random Hadamard transform, block 16
# ======================================================================
def hadamard16():
    H = np.array([[1.0]])
    while H.shape[0] < BLOCK:
        H = np.block([[H, H], [H, -H]])
    return H


H16 = hadamard16()


def rht_signs(seed, site):
    """The random +-1 diagonal D for one input site (deterministic)."""
    rng = np.random.default_rng([int(seed), zlib.crc32(site.encode())])
    return rng.integers(0, 2, BLOCK).astype(np.float64) * 2.0 - 1.0


RHT_FORM = "H16 @ diag(D) / 4 (signs first)"


def rht_matrix(signs):
    """M = H16 diag(D) / 4 — see the module docstring for why not diag(D) H16."""
    return H16 @ np.diag(np.asarray(signs, dtype=np.float64)) / 4.0


def rotate(X, signs):
    """x'_b = M x_b for every 16-block of the last axis (rows of W alike)."""
    M = rht_matrix(signs)
    B = _blocks(X)
    return (B @ M.T).reshape(np.shape(X))


def unrotate(X, signs):
    M = rht_matrix(signs)
    B = _blocks(X)
    return (B @ M).reshape(np.shape(X))


# ======================================================================
# weights and activations, as the harness uses them
# ======================================================================
def fake_quant_weight(W, signs=None, rowchunk=None):
    """(N, K) float -> float32 matrix to inject.

    signs=None: Q(W).  With signs: Q(W') rotated back, i.e. Q(W') R, so that
    the float model computes Q(W') R x — the hardware's Q(W') x' for a
    rotated input; the activation hook applies R^T Q(R x) on the same site
    with the same signs.  Tensor scale from the (rotated) matrix's amax.

    `rowchunk` bounds the float64 temporaries (the 248320-row head would
    otherwise need several GiB): the amax pass and the quantize pass walk the
    rows in chunks with ONE tensor scale, which is row-independent, so the
    result is bit-identical to rowchunk=None (asserted in --selftest).
    """
    W = np.asarray(W)
    if W.ndim != 2:
        raise ValueError(f"NVFP4 weight needs a 2-D matrix, got {W.shape}")
    N = W.shape[0]
    step = N if not rowchunk else int(rowchunk)

    def _rot(r0, r1):
        blk = np.asarray(W[r0:r1], dtype=np.float64)
        return blk if signs is None else rotate(blk, signs)

    amax = max(float(np.abs(_rot(r0, min(r0 + step, N))).max())
               for r0 in range(0, N, step))
    st = tensor_scale(amax)
    out = np.empty(W.shape, dtype=np.float32)
    for r0 in range(0, N, step):
        r1 = min(r0 + step, N)
        D = fake_quant(_rot(r0, r1), st)
        out[r0:r1] = D if signs is None else unrotate(D, signs)
    return out


def a8_fake_quant(X):
    """The shipped A8 rule (module docstring), per row of the last axis."""
    X = np.asarray(X, dtype=np.float64)
    amax = np.abs(X).max(axis=-1, keepdims=True)
    nz = amax > 0
    safe = np.where(nz, amax, 127.0)
    e = np.floor(np.log2(safe / 127.5)) + 1.0
    for _ in range(2):          # exact fix-up of the log2 estimate
        e = np.where(safe >= 127.5 * np.exp2(e), e + 1.0, e)
        e = np.where(safe < 127.5 * np.exp2(e - 1.0), e - 1.0, e)
    step = np.exp2(e)
    v = X / step
    x8 = np.clip(np.sign(v) * np.floor(np.abs(v) + 0.5), -127, 127)
    return np.where(nz, x8 * step, 0.0)


def row_beats(K):
    """(weight beats, scale beats) of one NVFP4 DDR row."""
    if K % BLOCK:
        raise ValueError(f"NVFP4: K={K} is not a multiple of {BLOCK}")
    wb = -(-K // K_PER_WBEAT)
    sb = -(-(K // BLOCK) // SCALES_PER_BEAT)
    return wb, sb


def row_stride(K):
    wb, sb = row_beats(K)
    return (wb + sb) * 64


def packed_bits(shape):
    N, K = shape
    return float(N * row_stride(K) * 8 + TENSOR_SCALE_BITS)


# ======================================================================
# selftest
# ======================================================================
def selftest():
    print("--- A: E2M1 grid rounding, hand vectors (ties to even code) ---")
    x = np.array([0.25, 0.75, 1.25, 1.75, 2.5, 3.5, 5.0, 7.0, 100.0,
                  -0.25, -0.75, -5.0, 0.24, 0.26, 0.0, -0.0, 5.01, 4.99,
                  -6.0, 2.75])
    want = np.array([0, 1, 1, 2, 2, 4, 4, 6, 6,
                     0, -1, -4, 0, 0.5, 0, 0, 6, 4,
                     -6, 3])
    got = e2m1_q2(x) / 2.0
    assert np.array_equal(got, want), list(zip(x, got, want))
    # quant and dequant share one table: every grid value is a fixed point
    for v in E2M1_GRID:
        for s in (1, -1):
            assert e2m1_q2(np.array([s * v]))[0] / 2.0 == s * v
    print(f"  {len(x)} hand values incl. all 7 ties: "
          "0.25->0 0.75->1 1.25->1 1.75->2 2.5->2 3.5->4 5->4, >6 saturates")

    print("--- B: UE4M3 encode/decode, hand vectors ---")
    assert UE4M3_TABLE.size == 127 and UE4M3_TABLE[-1] == 448.0
    assert UE4M3_TABLE[1] == 2.0 ** -9 and UE4M3_TABLE[8] == 2.0 ** -6
    assert UE4M3_TABLE[7] == 7 / 8 * 2.0 ** -6
    assert np.all(np.diff(UE4M3_TABLE) > 0)
    cases = [(448.0, 448.0), (460.0, 448.0), (1e6, 448.0),
             (432.0, 448.0),               # tie 416(m=5)|448(m=6) -> even
             (408.0, 416.0),               # nearest, no tie (see below)
             (1.0625, 1.0),                # tie 1.0(m0)|1.125(m1) -> 1.0
             (1.1875, 1.25),               # tie 1.125(m1)|1.25(m2) -> 1.25
             (1.1, 1.125), (0.0, 0.0),
             (2.0 ** -9, 2.0 ** -9),       # smallest subnormal
             (2.0 ** -10, 0.0),            # tie 0|2^-9 -> 0 (even)
             (1.5 * 2.0 ** -10, 2.0 ** -9),
             (3.0 * 2.0 ** -10, 2.0 ** -8),  # tie code1|code2 -> code 2
             (15 / 16 * 2.0 ** -6, 2.0 ** -6),  # sub/normal boundary tie
             (13 / 16 * 2.0 ** -6, 6 / 8 * 2.0 ** -6)]  # tie code6|code7 -> 6
    # 408 lies between 384 (m=4) and 416 (m=5) above their midpoint 400, so
    # it is a plain nearest case; 400 itself is the tie and goes to even m=4.
    for v, w in cases:
        g = float(ue4m3_decode(ue4m3_encode(np.array([v])))[0])
        assert g == w, (v, g, w)
    assert float(ue4m3_decode(ue4m3_encode(np.array([400.0])))[0]) == 384.0
    codes = np.arange(127)
    assert np.array_equal(ue4m3_encode(UE4M3_TABLE), codes)
    print(f"  {len(cases) + 1} hand values: saturation at 448, mantissa ties "
          "to even, subnormals down to 2^-9, 2^-10 -> 0, the 2^-6 boundary")

    print("--- C: RHT round trip, orthogonality, W'x' == Wx ---")
    assert np.array_equal(H16 @ H16.T, 16 * np.eye(16))
    worst = 0.0
    for seed in (0, 1, 2, 3):
        rng = np.random.default_rng(seed)
        s = rht_signs(seed, f"layers.{seed}.mlp_in")
        assert set(np.unique(s)) <= {-1.0, 1.0}
        M = rht_matrix(s)
        assert np.abs(M @ M.T - np.eye(16)).max() < 1e-15
        X = rng.normal(0, 1, (37, 256))
        W = rng.normal(0, 0.02, (29, 256))
        worst = max(worst, float(np.abs(unrotate(rotate(X, s), s) - X).max()))
        y0 = W @ X.T
        y1 = rotate(W, s) @ rotate(X, s).T
        worst = max(worst, float(np.abs(y1 - y0).max()))
    assert worst < 1e-6, worst
    assert not np.array_equal(rht_signs(0, "a"), rht_signs(1, "a"))
    assert not np.array_equal(rht_signs(0, "a"), rht_signs(0, "b"))
    assert np.array_equal(rht_signs(5, "lm_head"), rht_signs(5, "lm_head"))
    assert np.array_equal(rht_matrix(np.ones(16)), H16 / 4.0)
    # THE SEED MUST BITE: the round trip through the quantizer depends on D
    X = np.random.default_rng(9).normal(0, 1, (64, 256))
    s0, s1 = rht_signs(0, "layers.0.mlp_in"), rht_signs(1, "layers.0.mlp_in")
    q0 = unrotate(fake_quant_dynamic_rows(rotate(X, s0)), s0)
    q1 = unrotate(fake_quant_dynamic_rows(rotate(X, s1)), s1)
    assert not np.allclose(q0, q1)
    # ... and WHY the signs must come first: in the other order D only flips
    # output signs, the quantizer is sign-symmetric bit for bit, so D cancels
    # on the way back and every seed gives the SAME matrix (the n19/n23 defect)
    Yb = _blocks(X) @ (H16 / 4.0).T           # Hadamard, no signs
    YD = (Yb * s1).reshape(X.shape)            # diag(D) H16 applied to X
    assert np.array_equal(
        fake_quant_dynamic_rows(YD),
        (_blocks(fake_quant_dynamic_rows(Yb.reshape(X.shape))) * s1)
        .reshape(X.shape))
    print(f"  M M^T = I; unrotate(rotate(X)) and W'x' vs Wx: max err "
          f"{worst:.1e} (< 1e-6); signs deterministic per (seed, site); two "
          "seeds give different quantized results; the diag(D) H16 order is "
          "inert (Q(yD) == Q(y)D exactly)")

    print("--- D: dequant(quant(X)) error bounded by the grid ---")
    half_gap = np.diff(E2M1_GRID) / 2.0
    for seed in (1, 2, 3, 4):
        rng = np.random.default_rng(seed)
        X = rng.standard_t(3, (64, 512)) * 0.05
        X[3, :16] = 0.0                              # an all-zero block
        st = tensor_scale(np.abs(X).max())
        q2, sc, S = quantize(X, st)
        D = dequantize(q2, S)
        assert np.all(D[3, :16] == 0) and S[3, 0] == 0.0
        Bx, BD = _blocks(X), _blocks(D)
        Ss = S[..., None]
        with np.errstate(divide="ignore", invalid="ignore"):
            y = np.abs(np.where(Ss > 0, Bx / Ss, 0.0))
        err = np.abs(Bx - BD)
        inside = y <= E2M1_MAX
        idx = np.clip(np.searchsorted(E2M1_GRID, y, side="right") - 1, 0, 6)
        bound = np.where(inside, half_gap[idx] * Ss,
                         (E2M1_MAX * 1.0625 - E2M1_MAX) * Ss)
        assert np.all(err <= bound * (1 + 1e-12) + 1e-300), float(
            (err - bound).max())
        # the saturated elements are exactly those the rounded-down block
        # scale left above 6, and never by more than the UE4M3 half-ulp
        assert float(y.max()) <= E2M1_MAX * 1.0625
        # every block ratio is inside UE4M3's range
        assert int(sc.max()) <= 126
    # and the per-row dynamic scale reproduces a single-row scalar call
    Xr = np.random.default_rng(7).normal(0, 1, (5, 64))
    Dr = fake_quant_dynamic_rows(Xr)
    for r in range(5):
        assert np.array_equal(
            Dr[r], fake_quant(Xr[r], tensor_scale(np.abs(Xr[r]).max())))
    print("  |x - deq| <= S * half-gap of the E2M1 interval (<= S), "
          "saturation <= S * 0.375; zero block -> zeros; per-row == scalar")

    print("--- E: integer exactness (q2 integers, scales mu * 2^k) ---")
    rng = np.random.default_rng(11)
    X = rng.normal(0, 3, (48, 1024))
    st = tensor_scale(np.abs(X).max())
    q2, sc, S = quantize(X, st)
    assert q2.dtype == np.int8 and set(np.unique(np.abs(q2))) <= \
        {0, 1, 2, 3, 4, 6, 8, 12}
    sv = ue4m3_decode(sc)
    mant, ex = np.frexp(sv)
    mu = mant * 16.0
    assert np.array_equal(mu, np.round(mu)) and mu.max() <= 15
    rebuilt = (_blocks(q2).astype(np.int64) * mu[..., None].astype(np.int64)
               ).astype(np.float64) * np.exp2(ex - 4)[..., None] \
        * np.float64(st) * 0.5
    assert np.array_equal(rebuilt.reshape(X.shape), dequantize(q2, S))
    print("  2*value in {0,1,2,3,4,6,8,12}; every block scale = mu*2^k with "
          "integer mu <= 15; value == (q2*mu) * 2^k * s_t / 2 bit for bit")

    print("--- F: weights (plain + RHT) and the accounting ---")
    rng = np.random.default_rng(21)
    W = rng.normal(0, 0.02, (96, 2048)).astype(np.float32)
    W[:, 5::16] *= 30.0                    # one outlier per 16-block
    # (no direction is asserted for plain vs RHT error: it depends on the
    # matrix — on this one the RHT is WORSE, 2B PPL decides, not this test)
    s = rht_signs(0, "layers.0.mlp_in")
    Dp = fake_quant_weight(W)
    Dh = fake_quant_weight(W, s)
    assert Dp.dtype == np.float32 and Dh.shape == W.shape
    assert np.array_equal(fake_quant_weight(W, rowchunk=7), Dp)
    assert np.array_equal(fake_quant_weight(W, s, rowchunk=7), Dh)
    # Dh is Q(W') R exactly (up to the float32 cast)
    Wr = rotate(W, s)
    Qr = fake_quant(Wr, tensor_scale(np.abs(Wr).max()))
    assert np.abs(rotate(Dh, s) - Qr).max() <= 2e-6 * np.abs(Qr).max()
    ep = float(np.linalg.norm(Dp - W) / np.linalg.norm(W))
    eh = float(np.linalg.norm(Dh - W) / np.linalg.norm(W))
    assert IDEAL_BITS_PER_WEIGHT == 4.5
    for K, exp in ((1024, 9 * 64), (2048, 18 * 64), (6144, 54 * 64),
                   (4096, 36 * 64), (12288, 108 * 64), (3584, 32 * 64),
                   (16, 2 * 64)):
        assert row_stride(K) == exp, (K, row_stride(K), exp)
    assert packed_bits((7, 2048)) == 7 * 18 * 64 * 8 + 32
    assert abs((packed_bits((1000, 4096)) - 32) / (1000 * 4096) - 4.5) < 1e-15
    print(f"  (informational) outlier matrix rel err: plain {ep:.4f}, "
          f"RHT {eh:.4f}; row_stride K=2048 -> 1152 B (4.5 b/w), K=3584 -> 2048 B "
          "(4.571 b/w), +32 bits/matrix for s_t")

    print("--- G: A8 == fixedpoint.dyn_quant_i8 on integer vectors ---")
    import fixedpoint as FP
    rng = np.random.default_rng(31)
    n = 0
    for amp in (128, 200, 255, 256, 1000, 32767):
        for _ in range(25):
            x16 = rng.integers(-amp, amp + 1, 300)
            x16[rng.integers(0, 300)] = amp * (1 if rng.random() < .5 else -1)
            x8, e = FP.dyn_quant_i8(x16)
            got = a8_fake_quant(x16.astype(np.float64)[None, :])[0]
            assert np.array_equal(got, x8.astype(np.float64) * 2.0 ** e), amp
            n += 1
    # round-half-away at an exact tie: amax 255 -> e=1, 255/2 = 127.5 -> 128
    # would exceed 127, so e=2 and the rule never clips a max element
    assert np.array_equal(a8_fake_quant(np.array([[255.0, 2.0, -6.0]])),
                          np.array([[256.0, 4.0, -8.0]]))
    assert np.array_equal(a8_fake_quant(np.zeros((2, 8))), np.zeros((2, 8)))
    print(f"  {n} int16 vectors: float A8 == x8 * 2^e of the shipped "
          "dyn_quant_i8, bit for bit; zero rows stay zero")

    print("\nNVFP4 SELFTEST PASS")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    ap.error("nothing to do (use --selftest)")


if __name__ == "__main__":
    sys.exit(main())
