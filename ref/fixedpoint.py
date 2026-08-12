#!/usr/bin/env python3
"""Integer/fixed-point primitives for the stage-3 layer (single source of
truth: ref/layer_fixed.py uses these, and the RTL ROM init files are
GENERATED from the same tables — RTL must match these bit-for-bit).

Conventions:
  - all functions are exact integer algorithms (numpy int64 internally);
  - rounding is round-half-away-from-zero (rshr), matching quant_spec.md;
  - "QmDn" = signed fixed point, m integer bits, n fraction bits.

Self-test: python3 fixedpoint.py — checks every primitive against float
with documented error bounds.
"""
import numpy as np

from w4a8_ref import rshift_round as rshr  # round-half-away-from-zero

I64 = np.int64


# ----------------------------------------------------------------------
# dynamic power-of-2 quantization (activations into the W4A8 engines)
# ----------------------------------------------------------------------
def dyn_quant_i8(x16):
    """int16 vector -> (int8 vector, right-shift e >= 0), shift-only requant:
    x8 = rshr(x16, e), e minimal with max|x8| <= 127. Exact integer op."""
    x16 = np.asarray(x16, dtype=I64)
    m = int(np.abs(x16).max())
    e = 0
    while (m + (1 << e >> 1)) >> e > 127:
        e += 1
    x8 = np.clip(rshr(x16, e) if e else x16, -127, 127).astype(np.int8)
    return x8, e


# ----------------------------------------------------------------------
# rsqrt: 1/sqrt(v * 2^-P)  ->  (mantissa Q2.30 in [0.5,1.42), exponent)
# value = mant * 2^-30 * 2^exp
# ----------------------------------------------------------------------
_RSQRT_LUT = None

def _rsqrt_lut():
    """512-entry seed, RTL-friendly bit-slice indexing (no divide):
    entries [0..255]:   m in [1,2), midpoint 1 + (i+0.5)/256
    entries [256..511]: m in [2,4), midpoint 2 + (i+0.5)/128
    Q1.15 values in (0.5, 1]."""
    global _RSQRT_LUT
    if _RSQRT_LUT is None:
        lo = 1.0 + (np.arange(256) + 0.5) / 256.0
        hi = 2.0 + 2.0 * (np.arange(256) + 0.5) / 256.0
        _RSQRT_LUT = np.round((1.0 / np.sqrt(np.concatenate([lo, hi])))
                              * (1 << 15)).astype(I64)
    return _RSQRT_LUT


def rsqrt_q(v, P):
    """v: positive int (value = v * 2^-P). Returns (r, e) with
    1/sqrt(value) = r * 2^-30 * 2^e and r in Q30, r in (0.5, 1] * 2^30.
    Accuracy ~2^-26 relative (8b LUT seed + 2 Newton iterations)."""
    v = int(v)
    assert v > 0
    # normalize v = m * 2^s with m in [1,4) Q30 and (s - P) even
    s = v.bit_length() - 32          # m = v*2^-s in [2,4) Q30
    if (s - P) % 2 != 0:
        s += 1                       # m in [1,2) Q30
    m = (v >> s) if s >= 0 else (v << -s)        # [2^30, 2^32)
    E = s - P + 30                   # value = (m*2^-30) * 2^E, E even
    # bit-slice index: m in [1,2) -> bits[29:22]; m in [2,4) -> 256+bits[30:23]
    idx = ((m >> 22) & 0xFF) if m < (1 << 31) else (256 | ((m >> 23) & 0xFF))
    r = int(_rsqrt_lut()[idx]) << 15             # seed Q30
    for _ in range(2):               # Newton: r' = r*(3 - m*r^2)/2
        r2 = (r * r) >> 30
        mr2 = (m * r2) >> 30
        r = (r * ((3 << 30) - mr2)) >> 31
    return r, -E // 2


def rsqrt_apply(x, r_mant, r_exp, out_frac):
    """y = x * rsqrt -> integer with out_frac fraction bits relative to x's
    scale: y = rshr(x * r_mant, 30 - r_exp*?  ) — helper for vector scale."""
    x = np.asarray(x, dtype=I64)
    sh = 30 - out_frac - r_exp
    return rshr(x * r_mant, sh) if sh >= 0 else (x * r_mant) << (-sh)


# ----------------------------------------------------------------------
# exp2 fraction LUT: 2^f for f in [0,1), Q16 in/out, PWL-interpolated
# ----------------------------------------------------------------------
_EXP2_LUT = None

def _exp2_lut():
    global _EXP2_LUT
    if _EXP2_LUT is None:
        f = np.arange(257) / 256.0
        _EXP2_LUT = np.round((2.0 ** f) * (1 << 16)).astype(I64)  # Q16, [65536..131072]
    return _EXP2_LUT


def exp2_frac_q16(f):
    """2^(f*2^-16) for f in [0, 2^16): Q16 result, PWL on 256 segments."""
    f = int(f)
    assert 0 <= f < (1 << 16)
    lut = _exp2_lut()
    i, lo = f >> 8, f & 0xFF
    a, b = int(lut[i]), int(lut[i + 1])
    return a + (((b - a) * lo + 128) >> 8)


def exp_neg_q(x_q16):
    """exp(x) for x <= 0 given as NEGATIVE Q16 int. Returns Q30 in [0,1].
    exp(x) = 2^(x*log2e): t = x*LOG2E (Q16), n=floor(-t), f = t+n."""
    x_q16 = int(x_q16)
    assert x_q16 <= 0
    LOG2E_Q16 = 94548                       # round(log2(e)*65536)
    t = (x_q16 * LOG2E_Q16) >> 16           # Q16, <= 0 (floor shift ok: see RTL)
    n = (-t + 0xFFFF) >> 16                 # ceil(-t / 2^16)
    f = t + (n << 16)                       # in [0, 2^16)
    if n >= 31:
        return 0
    return exp2_frac_q16(f) << (14 - n) if n <= 14 else exp2_frac_q16(f) >> (n - 14)
    # Q16<<14 = Q30


# ----------------------------------------------------------------------
# PWL tables over [-16, 16): sigmoid, softplus (silu = x*sigmoid(x))
# input Q12, 256 segments of width 1/8 (tails below table resolution)
# ----------------------------------------------------------------------
def _pwl_tables(fn):
    xs = -16.0 + 32.0 * np.arange(257) / 256.0
    return np.round(fn(xs) * (1 << 15)).astype(I64)   # Q15

_SIGMOID_TAB = None
_SOFTPLUS_TAB = None

def sigmoid_q(x_q12):
    """sigmoid for x in Q12. Result Q15 in [0, 32767]: the table saturates
    at 32767 (not 32768) so Q15 gate values fit int16 transport/storage —
    a 3e-5 flatness at the rail, consistently in spec AND RTL (same ROM)."""
    global _SIGMOID_TAB
    if _SIGMOID_TAB is None:
        _SIGMOID_TAB = np.minimum(
            _pwl_tables(lambda v: 1.0 / (1.0 + np.exp(-v))), 32767)
    x = int(np.clip(x_q12, -16 << 12, (16 << 12) - 1))
    u = x + (16 << 12)                      # [0, 2^17)
    i, lo = u >> 9, u & 0x1FF
    a, b = int(_SIGMOID_TAB[i]), int(_SIGMOID_TAB[i + 1])
    return a + (((b - a) * lo + 256) >> 9)


def softplus_q(x_q12):
    """softplus(x) Q12 in -> Q12 out (range [0, ~16])."""
    global _SOFTPLUS_TAB
    if _SOFTPLUS_TAB is None:
        _SOFTPLUS_TAB = np.round(
            np.log1p(np.exp(-16.0 + 32.0 * np.arange(257) / 256.0)) * (1 << 12)
        ).astype(I64)                       # Q12
    x = int(x_q12)
    if x >= (16 << 12):                     # softplus(x) ~ x for x >= 16
        return x
    if x < (-16 << 12):
        return 0
    u = x + (16 << 12)
    i, lo = u >> 9, u & 0x1FF
    a, b = int(_SOFTPLUS_TAB[i]), int(_SOFTPLUS_TAB[i + 1])
    return a + (((b - a) * lo + 256) >> 9)


def silu_q(x_q12):
    """silu(x) = x * sigmoid(x). Q12 in -> Q12 out."""
    s = sigmoid_q(x_q12)                    # Q15
    return rshr(I64(int(x_q12)) * s, 15)


# ----------------------------------------------------------------------
# reciprocal: 1/v for v>0 (softmax denominator). (mant Q30, exp)
# ----------------------------------------------------------------------
_RECIP_LUT = None

def recip_q(v, P):
    """v>0 int, value = v*2^-P. Returns (r Q30, e): 1/value = r*2^-30*2^e.
    ~2^-26 relative accuracy."""
    global _RECIP_LUT
    if _RECIP_LUT is None:
        m = 1.0 + (np.arange(256) + 0.5) / 256.0
        _RECIP_LUT = np.round((1.0 / m) * (1 << 15)).astype(I64)
    v = int(v)
    assert v > 0
    n = v.bit_length()
    sh = n - 31
    m = (v >> sh) if sh >= 0 else (v << -sh)   # [2^30, 2^31) = [1,2) Q30
    idx = (m - (1 << 30)) >> 22                # 256 segments over [1,2)
    r = int(_RECIP_LUT[min(int(idx), 255)]) << 15
    for _ in range(2):
        mr = (m * r) >> 30
        r = (r * ((2 << 30) - mr)) >> 30
    # 1/(m*2^-30 * 2^(sh+ ... )): value = m*2^-30 * 2^(sh - P + 30 - 30)...
    # v*2^-P = (m*2^-30) * 2^(sh + 30 - P)
    return r, -(sh + 30 - P)


# ----------------------------------------------------------------------
# self-test
# ----------------------------------------------------------------------
def _selftest():
    rng = np.random.default_rng(3)

    # dyn_quant_i8
    for _ in range(200):
        x = rng.integers(-30000, 30000, 64).astype(I64)
        x8, e = dyn_quant_i8(x)
        assert np.abs(x8).max() <= 127
        err = np.abs(x8.astype(I64) - x / (1 << e)).max() if e else 0
        assert err <= 0.5 + 1e-9, err
    print("dyn_quant_i8 OK")

    # rsqrt_q
    worst = 0.0
    for _ in range(2000):
        P = int(rng.integers(0, 40))
        v = int(rng.integers(1, 1 << 48))
        r, ex = rsqrt_q(v, P)
        got = r * 2.0**(-30 + ex)
        ref = 1.0 / np.sqrt(v * 2.0**-P)
        worst = max(worst, abs(got - ref) / ref)
    print(f"rsqrt_q OK (max rel err {worst:.2e})")
    assert worst < 1e-6

    # exp_neg_q
    worst = 0.0
    for x in np.linspace(-20, 0, 4001):
        q = int(round(x * (1 << 16)))
        got = exp_neg_q(min(q, 0)) / (1 << 30)
        ref = float(np.exp(x))
        worst = max(worst, abs(got - ref))
    print(f"exp_neg_q OK (max abs err {worst:.2e})")
    assert worst < 1e-4

    # sigmoid / softplus / silu
    for name, fq, ff, scale_in, scale_out, bound in [
        ("sigmoid", sigmoid_q, lambda v: 1/(1+np.exp(-v)), 12, 15, 3e-4),
        ("softplus", softplus_q, lambda v: np.log1p(np.exp(v)), 12, 12, 1e-3),
        ("silu", silu_q, lambda v: v/(1+np.exp(-v)), 12, 12, 2.5e-3),
    ]:
        worst = 0.0
        for x in np.linspace(-12, 12, 4001):
            q = int(round(x * (1 << scale_in)))
            got = fq(q) / (1 << scale_out)
            worst = max(worst, abs(got - ff(x)))
        print(f"{name}_q OK (max abs err {worst:.2e})")
        assert worst < bound, (name, worst)

    # recip_q
    worst = 0.0
    for _ in range(2000):
        P = int(rng.integers(0, 40))
        v = int(rng.integers(1, 1 << 48))
        r, ex = recip_q(v, P)
        got = r * 2.0**(-30 + ex)
        ref = 1.0 / (v * 2.0**-P)
        worst = max(worst, abs(got - ref) / ref)
    print(f"recip_q OK (max rel err {worst:.2e})")
    assert worst < 1e-6

    print("FIXEDPOINT SELFTEST PASS")


if __name__ == "__main__":
    _selftest()
