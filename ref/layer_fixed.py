#!/usr/bin/env python3
"""Fixed-point (integer-only) Qwen3.5 decoder layer — THE stage-3 RTL spec.

Every operation here is an exact integer algorithm built on ref/fixedpoint.py
and ref/w4a8_ref.py. The RTL must reproduce these results bit-for-bit.
Accuracy vs the float anchor (layer_ref.py) is reported by _selftest and by
state_drift experiments; formats below were frozen from those measurements.

Formats (Q<int>.<frac>, all signed unless noted):
  residual stream   int16 Q7.8        (RS_F = 8)
  matvec input      int8 via dyn_quant_i8 (per-token power-of-2)
  matvec output     int32 -> shift+round to target format (exact)
  pre-conv qkv      int16 Q7.8
  conv weights      int16 Q2.13
  q/k/v post-silu   int16 Q9.6? -> see QKV_F
  l2-normed q,k     int16 Q1.14
  deltanet state S  int16 QS (S_F frac bits; experiment-chosen)
  decay/beta/gates  Q15 (uint16)
  KV cache (attn)   int8 with per-vector power-of-2 exponent
  attn probs        Q15
"""
import numpy as np

import fixedpoint as fp
import layer_ref as LR
from w4a8_ref import (G, quantize_weights, matvec_y32, rshift_round as rshr)

I64 = np.int64

# ---- frozen format constants ----
RS_F = 8        # residual fraction bits (int16 Q7.8)
QKV_F = 8       # conv output / v fraction bits (int16)
NRM_F = 14      # l2-normed q/k fraction bits (int16 Q1.14)
S_F = 13        # deltanet state frac bits (int16 Q2.13): measured float
                # |S|max 0.76, rms 0.009 -> 74 LSB rms, range +/-4
GAT_F = 15      # gates (sigmoid/decay/beta) fraction bits
CW_F = 13       # conv weight fraction bits (int16 Q2.13)
ROPE_F = 15     # cos/sin table fraction bits
KVC_F = 6       # base fraction for KV cache int8 mantissa heuristic

EPS_RMS_Q = 1   # rms eps in the integer domain (see rmsnorm_fx)

# ---- int32 -> int16 alignment: BLOCK FLOATING (SCRIPT-SIDE, not RTL) ----
# PRODUCTION path since Phase 1A of docs/FIDELITY_REDESIGN.md.  These are
# no longer knobs: this is exactly what gen_layer_script.dn_token /
# attn_token emit, and therefore exactly what the (frozen) RTL executes.
# The pre-Phase-1A path — a FIXED `DN_O_SHIFT = S_F - QKV_F = 5` immediate
# plus a vecnorm-mode-1 gated norm — is preserved in git history at 229c033;
# it measured 0/24 top-1 against bf16 (evidence/stage5/fidelity_*.log),
# because the DN head output leaves dnst at ~5.7 LSB rms (int32, Q.S_F), >>5
# squeezes that to 0.17 LSB rms in int16, and the gated RMSNorm renormalises
# the surviving quantization noise to full scale.
#
# DeltaNet output (per HEAD, per token).  dn_step hands the head output `o`
# to the scratchpad as int32 pairs at Q.S_F; the script emits
#   op1 SHIFT32 k_h    = bf_shift(max|o|)   block-float into int16 (k<0 = <<)
#   op2 SCALE   m_q15  = dn_norm_scale(o, k_h) >>15   1/sqrt(mean(o^2)+eps)
#                        folded with 2^(DN_NORM_F - S_F)
#   op3 EMUL    norm_w                      >>14      per-channel gate weight
# i.e. the SAME op count as the old alu+vn pair, and every operand is a
# command immediate the generator computes from the o32 it already models
# bit-exactly (a DYNQ16-style RTL scan would compute the same k_h from the
# same numbers — see bf_shift).  Two independent wins, both measured:
#   * block floating uses the whole int16 for every head instead of ~0.2 LSB;
#   * the SCRIPT-SIDE norm honours the reference eps (rms_norm_eps = 1e-6,
#     added to mean(o^2)).  vecnorm_unit/rmsnorm_fx have NO eps — `ss == 0
#     -> 1` is a divide-by-zero guard — so a head whose o is below the eps
#     floor was renormalised to FULL SCALE.  Phase-0 probe: block floating
#     alone 70-147% gated-norm rel error, block floating + eps 3.6-10%.
#
# Attention output: ONE k_a for the whole token (all query heads).  Not free
# per-head — the heads are concatenated straight into the o_proj matvec, so a
# per-head shift would change their relative weighting and there is no
# per-head compensation lever (o_proj group scales are static weights).  A
# SHARED k_a is compensated EXACTLY by the o_proj input format
# (matvec_to/shift_for in_f = QKV_F + GAT_F - k_a), because dyn_quant_i8 is
# power-of-two invariant.  k_a is clamped at 0: vec_alu op 8 (EMUL32) reads
# its shift with rshr64 (UNSIGNED), so a negative immediate would yield 0.
#
# DN_NORM_F is the OUTPUT binary point of the gated norm (its input is
# renormalised, so the input's real binary point never appears — see the
# derivation in rmsnorm_fx).  11 is the Phase-0c measured optimum; 8 (the
# old value) wasted 3 bits of the int16, 12+ starts clipping the norm output.
# BF_GUARD keeps extra headroom bits below the int16 rail (0 = fill it).
DN_NORM_F = 11
BF_GUARD = 0
M_Q15_MAX = 65535        # vec_alu cfg_p0 signed[16:0] positive limit
# Instrumentation for the reports (histograms of the emitted immediates and
# the two saturation counters).  Purely observational.
BF_K_HIST = {"dn": {}, "attn": {}}
BF_CLIP = {"m_q15": 0, "m_q15_nonzero": 0, "m_max": 0, "attn_k": 0}

# ---- SEQUENCER RUNG 1: the two immediates move ON CHIP (docs/SEQ_ISA.md) ----
# SEQ_NORM selects WHO computes the DeltaNet gated-norm scale:
#   False (default, SHIPPED): the host/generator float64 immediate
#           dn_norm_scale() -> vec_alu op 2 SCALE.  Byte-identical to every
#           committed artifact; the script generators depend on this.
#   True  (opt-in, sequencer): eps_norm_fx() — the integer vecnorm EPS-NORM
#           mode, computed on chip from the DYNQ16 int16 output + the k that
#           DYNQ16 latched into the XRF.  No host round trip, so the whole
#           token loop can run from a static record stream.
# It is a REFERENCE/harness flag only: gen_*_script.py never sets it (they
# emit the op-2 immediate), so flipping it cannot corrupt a generated script.
SEQ_NORM = False
SEQ_STATS = {"n": 0, "exact": 0, "d_max": 0, "rel_max": 0.0, "clip": 0,
             "scale_max": 0, "k_min": 0, "k_max": 0, "p_min": 63, "p_max": 0,
             "v_max": 0, "sh_min": 63, "sh_max": -63}


def bf_reset():
    """Zero the instrumentation counters (per-run reporting)."""
    BF_K_HIST["dn"], BF_K_HIST["attn"] = {}, {}
    for k in BF_CLIP:
        BF_CLIP[k] = 0
    SEQ_STATS.update({"n": 0, "exact": 0, "d_max": 0, "rel_max": 0.0,
                      "clip": 0, "scale_max": 0, "k_min": 0, "k_max": 0,
                      "p_min": 63, "p_max": 0, "v_max": 0, "sh_min": 63,
                      "sh_max": -63})


def bf_shift(absmax, guard=0):
    """Block-floating alignment for an int32 block whose |max| is `absmax`.

    Returns the SMALLEST k (negative = exact left shift) such that every
    element of the block lands inside int16 after rshr(.,k), i.e. the block
    occupies the int16 as fully as possible without clipping:

        k = bitlen(absmax) - 15 + guard          [+1, see below]

    bitlen(absmax)-15 is a plain priority encode of the block max, which is
    what a DYNQ16-style RTL op would compute; the generator computes the same
    number from the o32 it already models bit-exactly, so a script-side
    immediate and a hardware-side scan agree by construction.
    Correctness: absmax < 2^bitlen, so absmax/2^k < 2^15.  The one exception
    is round-half-away pushing absmax/2^k in (32767.5, 32768) up to 32768,
    hence the explicit +1 fixup — with it the "never clips" property is exact,
    not approximate.  absmax == 0 -> k = 0 (all-zero block; the consumer
    RMSNorm emits zeros for any k).
    """
    m = int(absmax)
    if m <= 0:
        return 0
    k = m.bit_length() - 15 + int(guard)
    if k > 0 and int(rshr(I64(m), k)) > 32767:
        k += 1
    return k


def dn_o_shift(o32, note=True):
    """SHIFT32 (vec_alu op 1) immediate for one DeltaNet head output.

    Signed: k < 0 is an exact left shift (cfg_p0 is `signed [16:0]` and ops
    1/5/6/7/9 use rshr64s).  Range on any int32 block is [-14, +17], well
    inside vec_alu's |p0| < 64 fast path.

    `note` records the immediate in BF_K_HIST.  The script generators pass
    note=False: they call this once per head from the scratchpad MODEL and
    once more via layer_decode_fx (the golden), and only one of the two
    should show up in the histogram.
    """
    k = bf_shift(int(np.abs(np.asarray(o32, dtype=I64)).max()), BF_GUARD)
    assert -64 < k < 64, f"SHIFT32 immediate {k} outside the vec_alu range"
    if note:
        BF_K_HIST["dn"][k] = BF_K_HIST["dn"].get(k, 0) + 1
    return int(k)


def attn_o_shift(absmax, note=True):
    """EMUL32 (vec_alu op 8) immediate for the gated attention output.

    ONE shift for the whole token (see the module header).  vec_alu reads
    op-8 shifts with rshr64 (UNSIGNED: `pu_big = (cfg_p0 < 0) || ...`), so a
    negative immediate would return 0 — clamp at 0 and count it.  On the real
    checkpoint the measured range is k_a in [8, 12], so the clamp is inert
    there; it only ever engages on tiny synthetic-weight activations.
    """
    k = bf_shift(int(absmax), BF_GUARD)
    if k < 0:
        k = 0
        if note:
            BF_CLIP["attn_k"] += 1
    assert 0 <= k < 64, f"EMUL32 immediate {k} outside the vec_alu range"
    if note:
        BF_K_HIST["attn"][k] = BF_K_HIST["attn"].get(k, 0) + 1
    return int(k)


def dn_norm_scale(o32, k_h, note=True):
    """SCALE (vec_alu op 2) immediate m_q15 for the gated RMSNorm of `o32`.

        ss    = sum(o32^2)                              exact integer
        s     = 1 / sqrt(ss / (n * 2^(2*S_F)) + rms_norm_eps)     float64
        A     = s * 2^(DN_NORM_F - S_F)
        m_q15 = round(A * 2^(15 + k_h))                 undoes the op-1 k_h

    so that `clip16(rshr(clip16(rshr64s(o32, k_h)) * m_q15, 15))` is the
    unit-RMS head output at Q.DN_NORM_F.  Deterministic across machines:
    integer sum, IEEE sqrt/divide, exact powers of two.

    m_q15 must fit vec_alu's cfg_p0 as a POSITIVE constant; it is clipped at
    32767 and the clip is counted.  The clip is benign on an all-zero head
    (m is then driven by the eps floor alone, but o16 == 0, so the head emits
    zeros for any m) — BF_CLIP["m_q15_nonzero"] counts the cases that are NOT
    benign and every generated script reports it.

    Ceiling M_Q15_MAX = 65535 (raised from the Phase-0 prototype's 32767 on
    2026-07-27): cfg_p0 is `signed [16:0]` and vec_alu's SCALE path is
    `mul_b <= 33'(cfg_p0)` (rtl/vec_alu.sv E_EX, op 2), so +65535 is the
    exact positive limit of the SHIPPED RTL immediate.  At 32767 the clip
    bound on ~3% of live heads (747/23526 head-evals over four prompts,
    fidelity_phase1a_prod.log), under-scaling them by up to 2x.
    """
    x = np.asarray(o32, dtype=I64)
    ss = int((x * x).sum())
    mean = ss / float(1 << (2 * S_F)) / float(len(x))
    s = 1.0 / np.sqrt(mean + LR.EPS)
    A = s * (2.0 ** (DN_NORM_F - S_F))
    m_raw = round(A * (2.0 ** (15 + k_h)))
    if note:
        if m_raw > M_Q15_MAX:
            BF_CLIP["m_q15"] += 1
            if ss != 0:
                BF_CLIP["m_q15_nonzero"] += 1
        BF_CLIP["m_max"] = max(BF_CLIP["m_max"], int(min(m_raw, 1 << 40)))
    return int(np.clip(m_raw, 0, M_Q15_MAX))


# ======================================================================
# ON-CHIP OP 1 — DYNQ16  (vec_alu op 12, docs/SEQ_ISA.md)
# ======================================================================
def dynq16_fx(x32_block, clamp0=False):
    """vec_alu op 12 DYNQ16 — THE frozen integer spec.  Returns (y16, k).

    Semantics (PROVABLY identical to what ships today — _dynq16_soak
    asserts it element-for-element):

        k  = bf_shift(max|x|, guard=0)          [clamped at 0 if clamp0]
        y  = clip16(rshr64s(x, k))              element-wise

    i.e. exactly `dn_o_shift(o32)` + the op-1 SHIFT32 that consumes it
    (clamp0=False), and exactly `attn_o_shift(max|prod|)` + the op-8 EMUL32
    shift (clamp0=True).  The ONLY change is WHO computes k: today the
    generator does it from its scratchpad model and emits it as a command
    immediate; DYNQ16 computes it from the same numbers in a scan pass and
    latches it into the XRF for later records to use as an indirect
    immediate.  Same k, same y, bit for bit.

    ---- RTL (two passes over `len` int32 {lo,hi} scratch pairs) ----
    PASS 1 (scan, 1 element / 4 cycles, the op-0 DYNQ8 Q_RD/Q_S/Q_W shape):
      av[31:0] = |x|  -- UNSIGNED 32 bits: x = -2^31 gives av = 2^31, which
                 does NOT fit a signed 32-bit register (the one width trap
                 in this op).
      maxabs[31:0] <= av when av > maxabs.
    PASS 1 EXIT (one cycle, pure combinational on maxabs):
      L    = bitlen(maxabs)      priority encode, 0..32 (0 <=> all-zero block)
      k    = (L == 0) ? 0 : L - 15                       signed, -14..+17
      fix  = (k > 0) && (maxabs[L-1 -: 16] == 16'hFFFF)  the +1 of bf_shift
      k   += fix                                          -> k in [-14, +17]
      if (clamp0 && k < 0) k = 0                          cfg_p0[1]
      XRF[cfg_p0[0] ? 2 : 1] <= k                         6-bit signed, sext
      NOTE the `fix` test is EXACT, not an approximation: rshr(m,k) > 32767
      <=> m + 2^(k-1) >= 2^(15+k) <=> m >= 2^L - 2^(L-16) <=> the 16 bits
      below and including the leading one are all ones.  Cost: ONE 32-bit
      normalising shift (maxabs >> (L-16)) plus a 16-input AND, evaluated
      once per vector at the pass-1 exit — no 64-bit shifter, no rounding
      adder and no compare against 32767 anywhere in the exponent path.
      (_dynq16_soak asserts fix == (bf_shift's own +1 branch) over the whole
      exponent range and both signs.)
    PASS 2 (write, the existing op-1 datapath):
      y = clip16(rshr64s(x, k)) with the SH_A/SH_M/SH_C/SH_F decomposition
      of vec_alu (abs -> +round -> coarse >>4n -> fine, sign restore; k < 0
      = exact left shift).  The rounding constant 1 << (k-1) and the
      coarse/fine nibbles are decoded ONCE at the pass-1 exit, exactly like
      cfg_p0 is decoded at IDLE today, so the element loop is unchanged.

    Provable properties (asserted in _dynq16_soak, they are what makes the
    op safe to build):
      * clip16 NEVER fires.  k >= 0: |y| <= 32767 by the +1 fixup.  k < 0:
        maxabs < 2^(15+k) so |y| = maxabs << -k < 2^15.  clamp0: k was
        negative, so maxabs < 2^14 and y = x.  The clip stays in the RTL as
        a width guard only.
      * absmax == 0 -> k = 0, y = 0 (the consumer norm emits zeros for any
        k, so the value of k is arbitrary; 0 is what bf_shift returns).
      * k in [-14, +17] for ANY int32 block: 6 bits signed, well inside the
        18-bit XRF and inside vec_alu's |p0| < 64 fast path.
    """
    x = np.asarray(x32_block, dtype=I64)
    absmax = int(np.abs(x).max()) if x.size else 0
    k = bf_shift(absmax, 0)
    if clamp0 and k < 0:
        k = 0
    return clip16(rshr(x, k)), int(k)


# ======================================================================
# ON-CHIP OP 2 — EPS-NORM  (vecnorm gated mode, docs/SEQ_ISA.md)
# ======================================================================
# Derivation of the eps addend (this is the whole design):
#
# The host today computes, in float64 from the int32 head output o32,
#     m_q15 = round( 2^(15+k) * 2^(DN_NORM_F-S_F) / sqrt(ss32/(n*2^(2*S_F))
#                                                        + rms_norm_eps) )
# On chip the norm only ever sees the DYNQ16 OUTPUT o16 = rshr64s(o32,k)
# (int16 scratch is the engine's transport), so it must work from
#     ss = sum(o16^2)              exact integer, <= n * 32767^2
# Reading ss at the binary point P0 = 2*S_F + n_log2 (the SAME wiring as
# the shipped vecnorm modes 0/1: rs_p = 2*cfg_inf + cfg_nlog2) declares the
# value mean(o_real^2) / 2^(2k) -- i.e. the block-float shift is still in
# there.  Adding an integer E to ss before the rsqrt therefore adds
# E*2^(2k-P0) to the real mean, so the eps floor is honoured exactly when
#     E = rms_norm_eps * 2^(P0 - 2k) = rms_norm_eps * 2^(2*(S_F-k)+n_log2)
# and the rsqrt result comes out 2^k too large -- which is PRECISELY the
# 2^(15+k) that m_q15 carries.  The two cancel, so the output shift
#     sh = S_F - DN_NORM_F + 15 - e
# has NO k in it at all.  k enters the hardware in exactly one place: the
# shift that scales the eps constant.  (Formally: rsqrt_q(v, P+2j) returns
# the same mantissa r and exponent e+j as rsqrt_q(v, P) — same parity, same
# normalisation, same Newton iterations — so declaring P0 instead of the
# true P = P0-2k is exact, not an approximation.)
#
# rms_norm_eps = 1e-6 is stored as a 21-bit integer mantissa at a fixed
# binary point EPS_Q, and E is a SHIFT of it (never a multiply):
#     EPS_M = round(1e-6 * 2^40) = 1099512      (rel. error 3.4e-7)
#     E     = rshr64(EPS_M, EPS_Q - P)          P = 2*(S_F-k) + n_log2
#           = rshr64(EPS_M, 7 + 2k)             for S_F=13, n_log2=7
# k in [-14,+17] -> shift in [-21,+41] -> E in [0, 2^41.1].  E is computed
# ONCE per vector, so this is one 64-bit shifter outside the element loop.
EPS_Q = 40
EPS_M = int(round(LR.EPS * (1 << EPS_Q)))        # 1099512 for eps = 1e-6


def eps_ss_addend(k, in_f=None, n_log2=7):
    """The integer eps addend E in the sum-of-squares domain (see above).

    E = rshr64(EPS_M, EPS_Q - (2*(in_f - k) + n_log2)), a pure shift of a
    21-bit constant with round-half-away (negative shift = exact left
    shift, the rshr64s convention).  E is 0 for k >= 8 at the DN geometry —
    correct and harmless: a block with k >= 8 has |o16|max >= 16384, so
    ss >= 2^28, and the true eps contribution there is < 2^-30 of ss.
    """
    in_f = S_F if in_f is None else in_f
    return int(rshr(I64(EPS_M), EPS_Q - (2 * (int(in_f) - int(k)) + n_log2)))


def eps_norm_scale(x16, k, in_f=None, out_f=None, note=True):
    """The Q15 multiplier the on-chip EPS-NORM computes (integer m_q15).

    THE FROZEN SPEC of the vecnorm gated mode's RSQ phase.  `x16` is the
    DYNQ16 output (int16), `k` the shift DYNQ16 latched into the XRF.

        n     = len(x16), n_log2 = log2(n)               (power of two)
        ss    = sum(x16^2)                exact, <= n*32767^2 (2^37 at n=128)
        v     = ss + eps_ss_addend(k)     <= 2^42, the 48-bit ss_acc holds it
        r, e  = rsqrt_q(v, 2*in_f + n_log2)      THE EXISTING fx_rsqrt/ROM
        scale = clip(rshr64(r, in_f - out_f + 15 - e), 0, M_Q15_MAX)

    ---- RTL (vecnorm_unit, one new mode; see the module header note) ----
    * ss_acc[47:0] += 32'(s_data)*32'(s_data) in FILL — unchanged.
    * EPS state (new, 1 cycle + 1 shift): eps_sh = (EPS_Q - 2*cfg_inf -
      cfg_nlog2) + 2*k with k the sign-extended 6-bit XRF field; E =
      rshr64(EPS_M, eps_sh); rs_v = ss_acc + E (43 bits worst case, the
      existing 48-bit port); the `(ss==0) -> 1` guard stays but is dead
      here (E > 0 whenever k <= 7, and k == 0 for an all-zero block).
    * rs_p = 6'(2*cfg_inf) + 6'(cfg_nlog2) — BIT-IDENTICAL to the mode-0/1
      wiring already in the RTL, 33 for the DN geometry (in_f = S_F = 13,
      n_log2 = 7).  p_in stays a 6-bit UNSIGNED port: the k-dependence was
      moved into E, so no signed-P widening of fx_rsqrt is needed.
    * ROM: unchanged.  fx_rsqrt's 512x16 bit-slice seed (rsqrt_rom.hex,
      addr = m[31] ? {1'b1,m[30:23]} : {1'b0,m[29:22]}) + 2 Newton
      iterations on the shared 33x33 multiplier.  Accuracy ~2^-26 relative,
      i.e. ~0.5 LSB of a 16-bit scale — three orders of magnitude below the
      output resolution, which is why no extra interpolation order or guard
      bit is required (measured: _epsnorm_soak, and the fidelity table).
    * SCALE state (new, 1 cycle after rs_done): sh_s = int'(cfg_inf) -
      int'(cfg_outf) + 15 - int'(rs_e); scale <= clip(rshr64(rs_r, sh_s),
      0, 16'hFFFF).  The 16-bit clamp is PROVABLY inert on any non-zero
      block: DYNQ16 guarantees |x16|max >= 16384, so ss >= 2^28,
      mean >= 2^-5 and scale <= 2^(15+out_f-in_f)/sqrt(2^-5) = 46341
      (verified: the tightest possible block, one element at 16384,
      scores 46341 over every k).  It fires only on all-zero heads, whose
      output is zero for ANY scale — the same benign clip the host path
      counts today (m_q15 raw 8192000 -> 65535 on exactly those heads).
    * OUT: one 16x17 multiply + a CONSTANT >>15 round-half-away per element
      (the vec_alu op-2 SCALE datapath) — strictly cheaper than the
      variable shifter modes 0/1 need.

    `note` accumulates SEQ_STATS (integer-vs-float scale agreement) for the
    fidelity report; the generators never call this.
    """
    x = np.asarray(x16, dtype=I64)
    in_f = S_F if in_f is None else in_f
    out_f = DN_NORM_F if out_f is None else out_f
    n = len(x)
    nbits = int(np.log2(n))
    assert (1 << nbits) == n, "n must be power of two"
    ss = int((x * x).sum())
    v = ss + eps_ss_addend(k, in_f, nbits)
    if v <= 0:
        v = 1                                    # RTL: the (ss==0)->1 guard
    p = 2 * int(in_f) + nbits
    assert 0 <= p < 64, f"rsqrt p_in {p} outside the 6-bit port"
    assert v < (1 << 48), f"rsqrt v {v} outside the 48-bit port"
    r, e = fp.rsqrt_q(v, p)
    sh = int(in_f) - int(out_f) + 15 - int(e)
    scale_raw = int(rshr(I64(r), sh))
    scale = int(np.clip(scale_raw, 0, M_Q15_MAX))
    if note:
        SEQ_STATS["n"] += 1
        SEQ_STATS["clip"] += int(scale_raw > M_Q15_MAX)
        SEQ_STATS["scale_max"] = max(SEQ_STATS["scale_max"], scale)
        SEQ_STATS["k_min"] = min(SEQ_STATS["k_min"], int(k))
        SEQ_STATS["k_max"] = max(SEQ_STATS["k_max"], int(k))
        SEQ_STATS["p_min"] = min(SEQ_STATS["p_min"], p)
        SEQ_STATS["p_max"] = max(SEQ_STATS["p_max"], p)
        SEQ_STATS["v_max"] = max(SEQ_STATS["v_max"], v)
        SEQ_STATS["sh_min"] = min(SEQ_STATS["sh_min"], sh)
        SEQ_STATS["sh_max"] = max(SEQ_STATS["sh_max"], sh)
    return scale


def eps_norm_fx(x16, k, in_f=None, out_f=None, note=True):
    """The on-chip gated RMSNorm (vecnorm EPS-NORM mode) — frozen spec.

        out = clip16(rshr64(x16 * eps_norm_scale(x16, k), 15))

    Output binary point Q.out_f (= DN_NORM_F), exactly like the op-2 SCALE
    it replaces, so the per-channel norm weight (op 3 EMUL, >>14) and
    everything downstream are untouched.
    """
    x = np.asarray(x16, dtype=I64)
    scale = eps_norm_scale(x, k, in_f, out_f, note=note)
    return clip16(rshr(clip16(x) * I64(scale), 15))


# ---- gate_unit transport limits (rtl/gate_unit.sv — FROZEN, see below) ----
# dtv[15:0] is signed  -> dt_bias Q3.12 in [-8.0, +7.99976]
# Av[17:0]  is unsigned -> A       Q3.15 in [ 0.0, +7.99997]
# Real Qwen3.5 weights exceed both on 3 of 288 DeltaNet heads
# (ref/audit_ranges_report.md sections 1 and 3).  Neither can be rehomed
# into a wider-headroom format without new ROM hex:
#   * dt at Q4.11 would need `a` at Q11 too (the RTL adds av+dtv with one
#     shared binary point), but the softplus PWL index is hardwired to a
#     Q12 [-16,16) abscissa (gate_unit.pwl_idx_lo + the +/-16<<12 exact
#     branches), so Q11 operands evaluate softplus at HALF the argument.
#   * A at Q4.14 would halve g, because g = -rshr(A*sp, 11) has the shift
#     hardwired to 11 = 15+12-16 and exp_neg consumes g as Q16 (LOG2E_Q16
#     + the exp2 ROM).  sp comes straight out of a ROM and decay goes
#     straight to DNST, so there is no second lever to compensate with.
# The resolution is therefore SATURATION (clamp), not wrapping: the ports
# as built silently truncate (Mach.W_raw masks A to 18 bits) which turns a
# fast-forgetting head into a never-forgetting one.  Clamping keeps the
# decay curve monotone and qualitatively faithful; measured cost is in
# evidence/stage5/ (worst |decay_clamp - decay_spec| = 2942/32768 at the
# a rail, vs 32609/32768 when the same head wraps).
# Widening dtv/Av + regenerating the softplus/exp2 ROMs is future work.
DT_Q12_MIN, DT_Q12_MAX = -32768, 32767
A_Q15_MAX = (1 << 18) - 1


def clip16(x):
    return np.clip(x, -32768, 32767).astype(np.int64)


# ----------------------------------------------------------------------
# weight quantization for ALL matvecs (stage-2 W4A8 path)
# ----------------------------------------------------------------------
def quant_linear_mse(Wf, nalpha=17, amin=0.55, g=G):
    """W4A8 group quantization with an MSE-OPTIMAL group scale.

    Same frozen wire format as `quantize_weights` (INT4 nibbles, one uint16
    mantissa per group of `g`, one shared exponent per matrix, same `sh`) —
    only the CHOICE of each group's scale changes, so nothing in the RTL or
    the DDR image layout moves.  `quantize_weights` uses scale = max|W_g|/7,
    which spends the whole INT4 range on the single largest weight of the
    group; on real (outlier-heavy) checkpoint weights that costs ~12% relative
    Frobenius error per matrix (audit_ranges_report.md section 2), which is
    the dominant fidelity loss of the whole pipeline.  Here each group's scale
    is picked by a small grid search that minimises the true reconstruction
    error, trading a few clipped outliers for resolution on the bulk.

    `g` is the GROUP SIZE (w4a8_ref module header): 128 = the legacy wire
    format and the default; 64 = the v2 row format (SHAPE bit 28).  The math
    is identical, only the groups are finer.  `sh` does not move with g
    (p_bound is g-independent), so a g=64 image reuses the same requant.
    """
    W = np.asarray(Wf, dtype=np.float64)
    N, K = W.shape
    assert K % g == 0
    NG = K // g
    Wg = W.reshape(N, NG, g)
    smax = np.maximum(np.abs(Wg).max(axis=2), 1e-12)
    best_s = smax / 7.0
    best_e = np.full((N, NG), np.inf)
    for a in np.linspace(amin, 1.0, nalpha):
        s = (smax / 7.0) * a
        q = np.clip(np.round(Wg / s[:, :, None]), -8, 7)
        err = ((q * s[:, :, None] - Wg) ** 2).sum(axis=2)
        upd = err < best_e
        best_s = np.where(upd, s, best_s)
        best_e = np.where(upd, err, best_e)
    e = int(np.ceil(np.log2(best_s.max()))) + 1
    m = np.clip(np.round(best_s * np.exp2(15 - e)).astype(np.uint32),
                1, 65535).astype(np.uint16)
    eff = m.astype(np.float64) * np.exp2(e - 15)
    w4 = np.clip(np.round(Wg / eff[:, :, None]), -8, 7).astype(np.int8)
    p_bound = NG * 65535 * (g * 8 * 127)
    return {"w4": w4.reshape(N, K), "m": m, "e": e, "g": int(g),
            "sh": max(0, p_bound.bit_length() - 31)}


def quant_linear(Wf, tighten_e=False, mse_scale=True, g=G):
    """W4A8 group quantization of one matvec matrix.

    `mse_scale` is the PRODUCTION group-scale rule since Phase 1A of
    docs/FIDELITY_REDESIGN.md (see quant_linear_mse): same frozen wire
    format, ~12% less reconstruction error per matrix.  Passing
    mse_scale=False selects the historical max|W_g|/7 rule, which is what
    every artifact committed before Phase 1A was built with.

    `tighten_e` (OPT-IN, default off) reclaims the mantissa headroom the
    shared exponent leaves on the table.  It is only implemented for the
    max-rule quantizer.  `quantize_weights` picks
    e = ceil(log2(max group scale)) + 1,
    which pins max(m) into (2^13, 2^14] even though m is a uint16: two bits
    of the group-scale mantissa are always unused, and every group whose
    scale is more than ~2^15 below the matrix maximum underflows to m == 0
    (clipped up to 1, which quantizes the whole group to INT4 zero).
    Lowering e by the largest delta that still keeps max(m) <= 65535 divides
    the underflow threshold by 2^delta and refines every group scale, at the
    cost of delta bits of the (deliberately conservative) y32 headroom.
    See ref/audit_ranges_report.md section 2 and the stage-5 fidelity report:
    on the real Qwen3.5-0.8B checkpoint NO group needs it (the only 112
    underflowing groups are 14 rows that are literally ~1e-37 in the
    checkpoint), so this stays off by default.

    `g` = quantization group size; 128 (default) is the legacy wire format,
    64 is the v2 row format.  See quant_linear_mse and the w4a8_ref header.
    """
    if mse_scale:
        assert not tighten_e, ("tighten_e is only implemented for the "
                               "max-rule quantizer (see quant_linear_mse)")
        return quant_linear_mse(Wf, g=g)
    w4, m, e, sh = quantize_weights(np.asarray(Wf, dtype=np.float64), g=g)
    if tighten_e:
        W = np.asarray(Wf, dtype=np.float64)
        N, K = W.shape
        NG = K // g
        scale = np.maximum(np.abs(W.reshape(N, NG, g)).max(axis=2), 1e-12) / 7.0
        d = 0
        while d < 15 and np.round(scale.max() * np.exp2(15 - (e - d - 1))) <= 65535:
            d += 1
        if d:
            e -= d
            m = np.clip(np.round(scale * np.exp2(15 - e)).astype(np.uint32),
                        1, 65535).astype(np.uint16)
            eff = m.astype(np.float64) * np.exp2(e - 15)
            w4 = np.clip(np.round(W.reshape(N, NG, g) / eff[:, :, None]),
                         -8, 7).astype(np.int8).reshape(N, K)
    return {"w4": w4, "m": m, "e": int(e), "sh": int(sh), "g": int(g)}


def matvec_fx(qw, x16, out_f):
    """W4A8 matvec: int16 input (RS-scaled by in_f bits implied in caller),
    returns int32 vector with out_f fraction bits relative to the FLOAT
    product W_f @ x_real. Exact: y_real ~= W@x; y_out = round(y_real*2^out_f).
    in_f: fraction bits of x16.

    The group size travels in the quantized dict ("g", absent == 128) and is
    handed to matvec_y32 explicitly; the accumulate order is identical in
    both modes (see the matvec_y32 docstring)."""
    x8, e_x = fp.dyn_quant_i8(x16)
    y32 = matvec_y32(qw["w4"], qw["m"], qw["sh"], x8, g=qw.get("g", G))
    # y32 scale: x8*2^-(in_f - e_x) ... dequant = y32 * 2^(e-15+sh) * 2^(e_x-in_f)
    # caller passes in_f via closure: we standardize x16 always carries in_f
    return y32, e_x


def matvec_to(qw, x16, in_f, out_f):
    """Full path: x16 (in_f frac) -> y int64 with out_f frac bits.
    y_real = y32 * 2^(e-15+sh) * 2^(e_x-in_f); y_out = y_real * 2^out_f
           = y32 >> ((15-e-sh) - e_x + in_f - out_f)."""
    y32, e_x = matvec_fx(qw, x16, out_f)
    sh = (15 - qw["e"] - qw["sh"]) - e_x + in_f - out_f
    if sh >= 0:
        return rshr(y32.astype(I64), sh)
    return y32.astype(I64) << (-sh)


# ----------------------------------------------------------------------
# vector blocks
# ----------------------------------------------------------------------
def rmsnorm_fx(x16, w_q14, in_f, one_plus):
    """RMSNorm: x int (in_f frac), weight Q14 int16 (zero-centered if
    one_plus). Output int16 with in_f frac bits (unit-RMS scaled).

    SCALE INVARIANCE (relied on by the DeltaNet block floating — verified
    here, not assumed).
    Let the input actually carry f fraction bits, x16 = X*2^f, while the
    caller passes in_f = F.  Then
        ss   = sum(x16^2)               = sum(X^2) * 2^(2f)
        rsqrt_q(ss, 2F+n) reads ss as    mean(X^2) * 2^(2f-2F)
        => r*2^(e-30) = 2^(F-f) / rms(X)
        y = rshr(x16*r, 30-e)           = (X/rms(X)) * 2^F
    The 2^f cancels: `in_f` is purely the OUTPUT binary point, the input's
    real binary point never appears.  So shifting x16 by any k (the DN
    block-floating k_h) leaves this function's output format at Q.in_f and
    its value unchanged except for rounding.  The DeltaNet gated norm now
    runs as script_norm_fx (op2 SCALE + op3 EMUL) rather than this vecnorm,
    but the same algebra is what makes dn_norm_scale's 2^(15 + k_h) factor
    exact and keeps the gated-norm output pinned at Q.DN_NORM_F whatever
    k_h is — so nothing downstream of the DeltaNet moves with k_h.
    THIS function is still the ln1/ln2/q_norm/k_norm/ln_f path (vn modes
    0 and 1), which is unchanged.
    """
    x = np.asarray(x16, dtype=I64)
    n = len(x)
    ss = int((x * x).sum())                      # frac 2*in_f
    if ss == 0:
        ss = 1
    # mean = ss/n; rsqrt(mean) — fold n into the binary point when pow2
    nbits = int(np.log2(n))
    assert (1 << nbits) == n, "n must be power of two"
    r, e = fp.rsqrt_q(ss, 2 * in_f + nbits)      # 1/sqrt(mean(x^2))
    y = rshr(x * r, 30 - e)                      # x * rsqrt, frac in_f
    y = np.clip(y, -(1 << 32), (1 << 32) - 1)    # RTL 33-bit intermediate
    w = np.asarray(w_q14, dtype=I64)
    scale = w + (1 << 14) if one_plus else w
    return clip16(rshr(y * scale, 14))


def script_norm_fx(o32, o16, k_h, w_q14, note=True):
    """Gated RMSNorm as a SCRIPT-SIDE per-head scale (the production path).

    The generator already models `o32` (the dnst Q.S_F output) bit-exactly,
    so it computes the head's normalisation factor itself -- INCLUDING the
    reference eps that vecnorm_unit does not have -- and emits it as an ALU
    SCALE immediate.  Hardware then only multiplies:

        m_q15 = dn_norm_scale(o32, k_h)         the op-2 SCALE immediate
        u     = clip16(rshr64s(o32, k_h))       op1 SHIFT32, already emitted
        t     = clip16(rshr(u * m_q15, 15))     op2 SCALE  (>>15 hardwired)
        y     = clip16(rshr(t * w_q14, 14))     op3 EMUL with norm_w

    y is at Q.DN_NORM_F, exactly like the vecnorm it replaces (see the
    SCALE-INVARIANCE note in rmsnorm_fx for why k_h never propagates).

    SEQ_NORM (opt-in, docs/SEQ_ISA.md) swaps the first two lines for the
    on-chip EPS-NORM: the scale comes from eps_norm_fx (integer rsqrt ROM
    path, ss taken from o16 and the eps floor added in the ss domain) so
    the host never sees o32 and the token loop needs no round trip.  o32
    is then used ONLY to score the integer scale against the float one
    (SEQ_STATS, observational).  Default False = the shipped path, so the
    generators and every committed artifact are unaffected.
    """
    if SEQ_NORM:
        t = eps_norm_fx(o16, k_h, note=note)
        if note:                       # observational: integer vs float m_q15
            m_ref = dn_norm_scale(o32, k_h, note=False)
            m_int = eps_norm_scale(np.asarray(o16, dtype=I64), k_h, note=False)
            d = abs(m_int - int(np.clip(m_ref, 0, M_Q15_MAX)))
            SEQ_STATS["exact"] += int(d == 0)
            SEQ_STATS["d_max"] = max(SEQ_STATS["d_max"], d)
            if m_ref > 0:
                SEQ_STATS["rel_max"] = max(SEQ_STATS["rel_max"],
                                           d / float(m_ref))
    else:
        m_q15 = dn_norm_scale(o32, k_h, note=note)
        t = clip16(rshr(clip16(o16) * I64(m_q15), 15))
    return clip16(rshr(t * np.asarray(w_q14, dtype=I64), 14))


def l2norm_fx(x16, in_f, out_f):
    """L2-normalize a head vector -> int16 with out_f frac bits."""
    x = np.asarray(x16, dtype=I64)
    ss = int((x * x).sum())
    if ss == 0:
        ss = 1
    r, e = fp.rsqrt_q(ss, 2 * in_f)              # 1/||x||
    # out = (x*2^-in_f)*(r*2^-30*2^e)*2^out_f  =>  shift = in_f + 30 - e - out_f
    return clip16(rshr(x * r, in_f + 30 - e - out_f))


def rope_tables_q15(pos):
    """Q15 tables clamped to int16 (cos(0)=+1.0 would round to +32768)."""
    cos, sin = LR.rope_cos_sin(pos)
    return (np.clip(np.round(cos * (1 << ROPE_F)), -32767, 32767).astype(I64),
            np.clip(np.round(sin * (1 << ROPE_F)), -32767, 32767).astype(I64))


def rope_fx(x16, cos_q, sin_q):
    """Rotate first ROT dims; int16 in/out, same frac."""
    x = np.asarray(x16, dtype=I64)
    ROT = LR.ROT
    xr, xp = x[:ROT], x[ROT:]
    h = ROT // 2
    rot = np.concatenate([-xr[h:], xr[:h]])
    y = rshr(xr * cos_q + rot * sin_q, ROPE_F)
    return clip16(np.concatenate([y, xp]))


# ----------------------------------------------------------------------
# full attention (decode step)
# ----------------------------------------------------------------------
def res_scaled(W, s):
    """W * s in float64 (s is a power of two, so this is EXACT)."""
    W = np.asarray(W, dtype=np.float64)
    return W if s == 1.0 else W * np.float64(s)


def quant_attn(wf, res_scale=1.0, tighten_e=False, mse_scale=True, g=G):
    return {
        "q_proj": quant_linear(wf["q_proj"], tighten_e, mse_scale, g),
        "k_proj": quant_linear(wf["k_proj"], tighten_e, mse_scale, g),
        "v_proj": quant_linear(wf["v_proj"], tighten_e, mse_scale, g),
        "o_proj": quant_linear(res_scaled(wf["o_proj"], res_scale), tighten_e, mse_scale, g),
        "q_norm": np.round(np.asarray(wf["q_norm"]) * (1 << 14)).astype(I64),
        "k_norm": np.round(np.asarray(wf["k_norm"]) * (1 << 14)).astype(I64),
    }


def kv_quant(v16, in_f):
    """int16 vector -> (int8 mantissas, shared exponent) power-of-2."""
    x8, e = fp.dyn_quant_i8(v16)
    return x8.astype(np.int8), e - in_f          # value = x8 * 2^(e - in_f)


def attn_decode_fx(xn16, qw, cache, pos):
    """xn16: normed residual int16 Q7.8. Returns int16 Q7.8 contribution."""
    NQ, NKV, HD = LR.NQ, LR.NKV, LR.HD
    qg = matvec_to(qw["q_proj"], xn16, RS_F, QKV_F).reshape(NQ, 2 * HD)
    # gate clip16 = RTL int16 scratch transport; output-identical since
    # sigmoid_q saturates for |x| >= 16.0 Q12 i.e. |gate| >= 4096 Q8
    q16, gate = clip16(qg[:, :HD]), clip16(qg[:, HD:])      # Q.QKV_F
    k16 = clip16(matvec_to(qw["k_proj"], xn16, RS_F, QKV_F).reshape(NKV, HD))
    v16 = clip16(matvec_to(qw["v_proj"], xn16, RS_F, QKV_F).reshape(NKV, HD))

    cos_q, sin_q = rope_tables_q15(pos)
    qn = np.stack([rope_fx(rmsnorm_fx(q16[h], qw["q_norm"], QKV_F, True), cos_q, sin_q)
                   for h in range(NQ)])                     # Q.QKV_F unit-RMS
    kn = np.stack([rope_fx(rmsnorm_fx(k16[h], qw["k_norm"], QKV_F, True), cos_q, sin_q)
                   for h in range(NKV)])

    # KV cache: int8 + exponent per (token, head)
    cache["k"].append([kv_quant(kn[h], QKV_F) for h in range(NKV)])
    cache["v"].append([kv_quant(v16[h], QKV_F) for h in range(NKV)])
    T = len(cache["k"])

    group = NQ // NKV
    out = np.zeros((NQ, HD), dtype=I64)                     # Q.QKV_F
    SCALE_Q15 = int(round((1 << 15) / np.sqrt(HD)))
    for h in range(NQ):
        kv = h // group
        # scores in Q16 for exp_neg_q
        sc = np.zeros(T, dtype=I64)
        for t in range(T):
            k8, ke = cache["k"][t][kv]
            dot = int((qn[h].astype(I64) * k8.astype(I64)).sum())   # frac QKV_F - ke... value = dot*2^(ke-QKV_F)
            # score = dot * 2^(ke - QKV_F) / sqrt(HD); to Q16:
            s = rshr(I64(dot) * SCALE_Q15, 15)
            f = QKV_F - ke - 16
            sc[t] = rshr(I64(int(s)), f) if f >= 0 else int(s) << (-f)
        mx = int(sc.max())
        es = np.array([fp.exp_neg_q(int(min(sc[t] - mx, 0))) for t in range(T)],
                      dtype=I64)                            # Q30
        denom = int(es.sum())                               # Q30
        r, re = fp.recip_q(denom, 30)
        # p[t] Q15 = es[t] * recip
        p = rshr(es * r, 30 - re + 15)                      # Q30*Q30->.. to Q15
        p = np.clip(p, 0, 1 << 15)
        # acc_QKV_F = sum_t rshr(p[t]*v8, 15 - ve)
        acc = np.zeros(HD, dtype=I64)
        for t in range(T):
            v8, ve = cache["v"][t][kv]
            # term_real = p*2^-15 * v8*2^ve; acc(frac QKV_F) => >> (15-ve-QKV_F)
            term = I64(int(p[t])) * v8.astype(I64)
            sh = 15 - ve - QKV_F
            acc += rshr(term, sh) if sh >= 0 else term << (-sh)
        out[h] = acc                                        # Q.QKV_F

    # output gate: sigmoid(gate) Q15; gate is Q.QKV_F -> to Q12 for sigmoid_q
    og = np.array([fp.sigmoid_q(rshr(I64(int(g)), QKV_F - 12)) for g in
                   gate.reshape(-1)], dtype=I64)
    prod = out.reshape(-1) * og                             # Q.(QKV_F+GAT_F)
    # int32*Q15 -> int16 alignment, ONE block-float shift for the whole token
    # (gen_layer_script.attn_token: `M.alu(8, 256, k_a, AO32, OG, GATED+...)`).
    k_a = attn_o_shift(int(np.abs(prod).max()))
    gated = rshr(prod, k_a)                                 # k_a >= 0
    cache["attn_o_shift"] = k_a
    # the o_proj input frac bits move with k_a; matvec_to folds them into the
    # requant shift, and dyn_quant_i8 is exactly power-of-two invariant, so
    # this is a pure resolution change with no residual-scale side effect.
    y = matvec_to(qw["o_proj"], clip16(gated), QKV_F + GAT_F - k_a, RS_F)
    return clip16(y)


# ----------------------------------------------------------------------
# DeltaNet (decode step)
# ----------------------------------------------------------------------
def quant_deltanet(wf, res_scale=1.0, tighten_e=False, mse_scale=True, g=G):
    # Spec (unbounded) quantization first, then SATURATE into the frozen
    # gate_unit ports.  Both clamps are no-ops for every synthetic-weight
    # script ever committed, so stage-3/4/5-(1)(2) artifacts are unchanged.
    dt_spec = np.round(np.asarray(wf["dt_bias"]) * (1 << 12)).astype(I64)
    A_spec = np.round(np.exp(wf["A_log"]) * (1 << 15)).astype(I64)
    dt_q = np.clip(dt_spec, DT_Q12_MIN, DT_Q12_MAX)
    A_q = np.clip(A_spec, 0, A_Q15_MAX)
    qd = {
        "in_qkv": quant_linear(wf["in_qkv"], tighten_e, mse_scale, g),
        "in_z": quant_linear(wf["in_z"], tighten_e, mse_scale, g),
        "in_b": quant_linear(wf["in_b"], tighten_e, mse_scale, g),
        "in_a": quant_linear(wf["in_a"], tighten_e, mse_scale, g),
        "out": quant_linear(res_scaled(wf["out"], res_scale), tighten_e, mse_scale, g),
        "conv_w": np.round(np.asarray(wf["conv_w"]) * (1 << CW_F)).astype(I64),
        "dt_bias_q12": dt_q,
        # legacy alias, unreferenced; kept at its historical (positive) value
        "negA_q15": A_q,
        # store A = exp(A_log) Q15 (positive), port-saturated
        "norm_w_q14": np.round(np.asarray(wf["norm_w"]) * (1 << 14)).astype(I64),
    }
    qd["A_q15"] = A_q
    # provenance for the range audit: which heads had to saturate, and by
    # how much (0 entries => this layer is an exact port fit)
    qd["gate_sat"] = [(int(h), int(dt_spec[h]), int(dt_q[h]),
                       int(A_spec[h]), int(A_q[h]))
                      for h in range(len(dt_q))
                      if dt_spec[h] != dt_q[h] or A_spec[h] != A_q[h]]
    return qd


def deltanet_decode_fx(xn16, qd, state):
    LNH, LDK, LDV = LR.LNH, LR.LDK, LR.LDV
    qkv16 = clip16(matvec_to(qd["in_qkv"], xn16, RS_F, RS_F))
    z16 = clip16(matvec_to(qd["in_z"], xn16, RS_F, QKV_F)).reshape(LNH, LDV)
    # int16 transport width (RTL gate_unit port); sigmoid/softplus saturate
    # beyond +/-8.0 so the clip only pins the already-flat tail
    b_q12 = clip16(matvec_to(qd["in_b"], xn16, RS_F, 12))
    a_q12 = clip16(matvec_to(qd["in_a"], xn16, RS_F, 12))

    # depthwise conv4 + silu  (win frac RS_F, weights CW_F)
    win = np.concatenate([state["conv"], qkv16[:, None]], axis=1)   # (C,4)
    state["conv"] = win[:, 1:]
    acc = (win.astype(I64) * qd["conv_w"]).sum(axis=1)              # frac RS_F+CW_F
    pre = rshr(acc, RS_F + CW_F - 12)                               # Q12
    pre = np.clip(pre, -(1 << 20), (1 << 20) - 1)   # RTL 21-bit silu port
    conv_out = clip16(np.array([fp.silu_q(int(v)) for v in pre], dtype=I64))
    # (int16 Q12 — RTL fx_silu output width)
    qkv = rshr(conv_out, 12 - QKV_F)                                # Q.QKV_F

    q = qkv[:LNH * LDK].reshape(LNH, LDK)
    k = qkv[LNH * LDK:2 * LNH * LDK].reshape(LNH, LDK)
    v = qkv[2 * LNH * LDK:].reshape(LNH, LDV)

    # gates per head
    beta = np.array([fp.sigmoid_q(int(b)) for b in b_q12], dtype=I64)      # Q15
    # g = -A * softplus(a + dt_bias); decay = exp(g) Q15
    decay = np.zeros(LNH, dtype=I64)
    for h in range(LNH):
        sp = fp.softplus_q(int(a_q12[h] + qd["dt_bias_q12"][h]))           # Q12
        g_q16 = -rshr(I64(int(qd["A_q15"][h])) * sp, 15 + 12 - 16)         # Q16 <=0
        decay[h] = min(rshr(I64(fp.exp_neg_q(int(min(g_q16, 0)))), 15),
                       I64(32767))      # Q15 saturated to int16 (RTL width)

    INV_SQRT_DK_Q15 = int(round((1 << 15) / np.sqrt(LDK)))
    o16 = np.zeros((LNH, LDV), dtype=I64)
    o32 = np.zeros((LNH, LDV), dtype=I64)      # the Q.S_F dnst output
    S = state["S"]                                                  # int16 Q.S_F
    sat = 0
    k_log = []                       # per-head block-float shifts (op 1 immed)
    for h in range(LNH):
        qn = l2norm_fx(q[h], QKV_F, NRM_F)
        qn = rshr(qn * I64(INV_SQRT_DK_Q15), 15)                    # Q.NRM_F
        kn = l2norm_fx(k[h], QKV_F, NRM_F)

        Sh = S[h].astype(I64)
        Sh = rshr(Sh * I64(int(decay[h])), GAT_F)                   # decay
        kv_mem = rshr((Sh * kn[:, None]).sum(axis=0), NRM_F)        # Q.S_F
        # v is Q.QKV_F; align to S_F
        v_s = rshr(v[h], QKV_F - S_F) if QKV_F >= S_F else v[h] << (S_F - QKV_F)
        delta = rshr((v_s - kv_mem) * I64(int(beta[h])), GAT_F)     # Q.S_F
        Sh = Sh + rshr(kn[:, None] * delta[None, :], NRM_F)         # Q.S_F
        sat += int((np.abs(Sh) > 32767).sum())
        Sh = clip16(Sh)
        o = rshr((Sh * qn[:, None]).sum(axis=0), NRM_F)             # Q.S_F
        o32[h] = o
        # int32 -> int16: per-head, per-token block floating (op 1 SHIFT32)
        k_h = dn_o_shift(o)
        o16[h] = clip16(rshr(o, k_h) if k_h >= 0 else o << (-k_h))
        k_log.append(k_h)
        S[h] = Sh.astype(np.int16)
    state["sat"] = state.get("sat", 0) + sat
    state["dn_o_shift"] = k_log              # what dn_token emits (op 1)

    # gated rmsnorm (script-side scale, op2 SCALE + op3 EMUL) + silu(z)
    on = np.zeros((LNH, LDV), dtype=I64)
    for h in range(LNH):
        nh = script_norm_fx(o32[h], o16[h], k_log[h], qd["norm_w_q14"])
        zg = clip16(np.array([fp.silu_q(rshr(I64(int(zz)), QKV_F - 12))
                              for zz in z16[h]], dtype=I64))        # Q12 int16
        on[h] = rshr(nh * zg, 12)
    y = matvec_to(qd["out"], clip16(on.reshape(-1)), DN_NORM_F, RS_F)
    return clip16(y)


# ----------------------------------------------------------------------
# MLP + layer
# ----------------------------------------------------------------------
def quant_mlp(wf, res_scale=1.0, tighten_e=False, mse_scale=True, g=G):
    q = {k: quant_linear(wf[k], tighten_e, mse_scale, g) for k in ("gate", "up")}
    q["down"] = quant_linear(res_scaled(wf["down"], res_scale), tighten_e,
                             mse_scale, g)
    return q


def mlp_fx(xn16, qm):
    g = matvec_to(qm["gate"], xn16, RS_F, 12)
    u = matvec_to(qm["up"], xn16, RS_F, RS_F)
    sg = clip16(np.array([fp.silu_q(int(np.clip(x, -(1 << 20), (1 << 20) - 1)))
                          for x in g], dtype=I64))                  # Q12 int16
    # (input clip = RTL 21-bit port; output clip16 = RTL output width)
    prod = clip16(rshr(sg * u, 12))                                 # Q.RS_F
    return clip16(matvec_to(qm["down"], prod, RS_F, RS_F))


def quant_layer(wf, res_scale=1.0, tighten_e=False, mse_scale=True, g=G):
    """Quantize one decoder layer.

    `res_scale` S multiplies ONLY the residual-adding projection of each
    sub-block (attn.o_proj / dn.out and mlp.down) before quantization.  Done
    for every layer AND on the embedding table (caller's job), it scales the
    entire residual stream by S: RMSNorm is invariant to a positive scale of
    its input, so every norm output, every matvec input and the final argmax
    are EXACTLY unchanged in float.  In fixed point the residual (int16 Q7.8)
    then carries log2(S) more fraction bits — the embedding seed goes from
    0.18% of the rail to S*0.18% — traded against int16 headroom.
    S must be a power of two so the quantization is exact (a power-of-two
    scale shifts `e` by log2(S) and leaves w4/m/sh bit-identical).
    Default 1.0 reproduces every committed artifact byte for byte.

    `g` = W4 group size for EVERY matvec matrix of this layer (128 legacy /
    64 = v2 row format).  Default 128 keeps every committed artifact
    bit-identical; the flip to 64 is an explicit opt-in from the generators.
    """
    qw = {"ln1": np.round(np.asarray(wf["ln1"]) * (1 << 14)).astype(I64),
          "ln2": np.round(np.asarray(wf["ln2"]) * (1 << 14)).astype(I64),
          "mlp": quant_mlp(wf["mlp"], res_scale, tighten_e, mse_scale, g),
          "type": wf["type"]}
    if wf["type"] == "full_attention":
        qw["attn"] = quant_attn(wf["attn"], res_scale, tighten_e, mse_scale, g)
    else:
        qw["dn"] = quant_deltanet(wf["dn"], res_scale, tighten_e, mse_scale, g)
    return qw


def new_cache_fx(layer_type):
    if layer_type == "full_attention":
        return {"k": [], "v": []}
    return {"conv": np.zeros((LR.CONV_DIM, LR.CONV_K - 1), dtype=I64),
            "S": np.zeros((LR.LNH, LR.LDK, LR.LDV), dtype=np.int16)}


def layer_decode_fx(x16, qw, cache, pos):
    xn = rmsnorm_fx(x16, qw["ln1"], RS_F, True)
    if qw["type"] == "full_attention":
        h = attn_decode_fx(xn, qw["attn"], cache, pos)
    else:
        h = deltanet_decode_fx(xn, qw["dn"], cache)
    x16 = clip16(np.asarray(x16, dtype=I64) + h)
    xn = rmsnorm_fx(x16, qw["ln2"], RS_F, True)
    return clip16(x16 + mlp_fx(xn, qw["mlp"]))


# ----------------------------------------------------------------------
# self-test: matched-input per-block fidelity (the meaningful metric).
# Trajectory comparisons diverge chaotically through caches/states and are
# dominated by inherent W4 weight-quantization noise on random weights —
# they are NOT a fixed-point correctness signal. Instead: feed identical
# inputs/state to fixed and float versions of each VECTOR block and require
# fixed-point-resolution agreement; matvec blocks are checked against the
# documented W4 noise floor separately (see w4a8_ref).
# ----------------------------------------------------------------------
def _blk(name, got, ref, bound):
    got = np.asarray(got, dtype=np.float64)
    ref = np.asarray(ref, dtype=np.float64)
    rel = np.abs(got - ref).max() / (np.abs(ref).max() + 1e-12)
    ok = rel < bound
    print(f"  {name:22s} rel={rel:.3e}  bound={bound:.0e}  {'OK' if ok else 'FAIL'}")
    return ok


def _dynq16_cases(rng):
    """Blocks that exercise every corner of the DYNQ16 exponent path."""
    cases = []
    I32MIN, I32MAX = -(1 << 31), (1 << 31) - 1
    for L in range(1, 33):                      # every possible bitlen(absmax)
        hi = min((1 << L) - 1, 1 << 31)         # |x| <= 2^31 (int32 domain)
        lo = min(1 << (L - 1), 1 << 31)
        for _ in range(6):
            x = np.clip(rng.integers(-hi, hi + 1, 128, dtype=np.int64),
                        I32MIN, I32MAX)
            x[int(rng.integers(0, 128))] = int(
                np.clip(rng.choice([lo, -lo, hi, -hi]), I32MIN, I32MAX))
            cases.append(("rand", x))
    for k in range(1, 18):                      # the (32767.5, 32768) fixup
        base = 1 << (15 + k)
        for j in (1, 2, (1 << (k - 1)) if k > 1 else 1,
                  (1 << (k - 1)) + 1 if k > 1 else 2, 1 << k):
            m = base - j
            if 0 < m <= (1 << 31):
                cases.append(("fixup", np.array([m, -m, 0, 1], dtype=I64)))
                cases.append(("fixup", np.array([-m, m // 3, 0, 0],
                                                dtype=I64)))
    cases.append(("zero", np.zeros(128, dtype=I64)))
    cases.append(("zero1", np.zeros(1, dtype=I64)))
    cases.append(("int32min", np.full(8, -(1 << 31), dtype=I64)))
    cases.append(("int32max", np.full(8, (1 << 31) - 1, dtype=I64)))
    for v in (1, -1, 2, 16383, 16384, 32767, 32768, 32769, 65535, 65536):
        cases.append((f"tiny{v}", np.array([v, -v, v // 2, 0], dtype=I64)))
    return cases


def _dynq16_soak():
    """DYNQ16 (vec_alu op 12) IS the shipped bf_shift + rshr64s path.

    Asserts, element for element and over every exponent decade:
      dynq16_fx(o32)            == (dn_o_shift  + op-1 SHIFT32) on the DN path
      dynq16_fx(prod, clamp0=1) == (attn_o_shift + op-8 EMUL32 shift)
    plus the properties the RTL relies on (no clip16, block fills the int16,
    k in [-14,17], and the "top 16 bits all ones" form of the +1 fixup).
    """
    assert BF_GUARD == 0, "DYNQ16 has no guard input: the spec is guard 0"
    rng = np.random.default_rng(1212)
    cases = _dynq16_cases(rng)
    n_fix = n_neg = n_zero = 0
    kmin, kmax, ymin = 99, -99, 32767
    for tag, x in cases:
        x = np.asarray(x, dtype=I64)
        absmax = int(np.abs(x).max())
        y, k = dynq16_fx(x)
        # (a) k is EXACTLY the immediate the generator emits today
        assert k == dn_o_shift(x, note=False), (tag, absmax, k)
        # (b) y is EXACTLY what vec_alu op 1 writes for that immediate
        ref = clip16(rshr(x, k))
        assert np.array_equal(y, ref), (tag, absmax, k)
        # (c) clip16 is inert -> the RTL never has to reason about clipping
        raw = rshr(x, k)
        assert int(np.abs(raw).max()) <= 32767, (tag, absmax, k)
        # (d) the block fills the int16 (that is the point of the op)
        if absmax:
            assert int(np.abs(y).max()) >= 16384, (tag, absmax, k)
            ymin = min(ymin, int(np.abs(y).max()))
        else:
            assert k == 0 and not y.any()
            n_zero += 1
        # (e) k range / RTL fixup form: fix <=> top 16 bits of maxabs are 1s
        assert -14 <= k <= 17, (tag, k)
        L = absmax.bit_length()
        k0 = 0 if L == 0 else L - 15
        fix = (k0 > 0) and ((absmax >> (L - 16)) == 0xFFFF)
        assert k == k0 + int(fix), (tag, absmax, k, k0, fix)
        n_fix += int(fix)
        n_neg += int(k < 0)
        kmin, kmax = min(kmin, k), max(kmax, k)
        # (f) clamp0 mode == the attention immediate + its shift
        yc, kc = dynq16_fx(x, clamp0=True)
        assert kc == attn_o_shift(absmax, note=False), (tag, absmax, kc)
        assert np.array_equal(yc, clip16(rshr(x, kc))), (tag, absmax, kc)
        assert kc == max(k, 0)
    # (g) the LIVE DN path: intercept every dn_o_shift call inside
    # deltanet_decode_fx and require DYNQ16 to reproduce it on the real o32
    import sys as _sys
    mod = _sys.modules[__name__]
    orig, n_live = mod.dn_o_shift, 0
    def _rec(o32, note=True):
        nonlocal n_live
        k_ref = orig(o32, note=note)
        y, k = dynq16_fx(o32)
        assert k == k_ref
        assert np.array_equal(y, clip16(rshr(np.asarray(o32, dtype=I64),
                                             k_ref)))
        n_live += 1
        return k_ref
    mod.dn_o_shift = _rec
    try:
        rngw = np.random.default_rng(7)
        wf = LR.init_layer_weights(rngw, "linear_attention")
        qd = quant_layer(wf)["dn"]
        st = new_cache_fx("linear_attention")
        for _t in range(3):
            xn = np.round(rngw.normal(0, 1, LR.H) * (1 << RS_F)).astype(I64)
            deltanet_decode_fx(clip16(xn), qd, st)
    finally:
        mod.dn_o_shift = orig
    print(f"  DYNQ16 soak: {n_live} live DN head outputs + {len(cases)} "
          f"synthetic blocks, k in [{kmin},{kmax}], "
          f"{n_fix} fixup / {n_neg} left-shift / {n_zero} zero blocks, "
          f"min filled |y|max={ymin} (>=16384)  OK")
    return True


def _epsnorm_soak():
    """EPS-NORM (vecnorm gated mode) vs the float64 host immediate.

    Sweeps head outputs across 20 decades of magnitude — the eps floor is
    the whole reason this op exists, so the small-magnitude end (where
    dn_norm_scale is dominated by rms_norm_eps) is where the integer design
    has to hold.  Also checks the RTL envelope: p_in, ss/v widths, the
    output shift range and the 16-bit scale clamp.
    """
    rng = np.random.default_rng(99)
    n = LR.LDV
    # the exponent-shift identity the whole design rests on:
    # rsqrt_q(v, P) and rsqrt_q(v, P-2k) share r, and e differs by exactly k
    for _ in range(400):
        v = int(rng.integers(1, 1 << 42))
        k = int(rng.integers(-14, 18))
        P0 = 2 * S_F + 7
        r0, e0 = fp.rsqrt_q(v, P0)
        r1, e1 = fp.rsqrt_q(v, P0 - 2 * k)
        assert r0 == r1 and e0 == e1 + k, (v, k, e0, e1)
    worst_s, worst_o, worst_tag = 0.0, 0, None
    rows = []
    for dec in range(-10, 10):
        amp = 2.0 ** dec
        rel, dout, nclip = 0.0, 0, 0
        for _ in range(60):
            o = np.round(rng.normal(0, amp, n) * (1 << S_F)).astype(I64)
            o = np.clip(o, -(1 << 31), (1 << 31) - 1)
            o16, k = dynq16_fx(o)
            m_ref = dn_norm_scale(o, k, note=False)
            m_int = eps_norm_scale(o16, k, note=True)   # -> SEQ_STATS envelope
            nclip += int(m_ref >= M_Q15_MAX)
            if m_ref:
                rel = max(rel, abs(m_int - m_ref) / m_ref)
            t_ref = clip16(rshr(clip16(o16) * I64(m_ref), 15))
            t_int = eps_norm_fx(o16, k, note=False)
            dout = max(dout, int(np.abs(t_int - t_ref).max()))
            if rel > worst_s:
                worst_s, worst_tag = rel, (dec, k, m_ref, m_int)
            worst_o = max(worst_o, dout)
        rows.append((dec, rel, dout, nclip))
    print("  EPS-NORM soak (per magnitude decade: scale rel err, "
          "max |out| LSB delta, float-clip count)")
    for dec, rel, dout, nclip in rows:
        print(f"    2^{dec:<4d} scale_rel={rel:.2e}  out_dlsb={dout}"
              f"  m_ref_clipped={nclip}")
    print(f"  worst scale rel err {worst_s:.2e} at (decade,k,m_ref,m_int)="
          f"{worst_tag}; worst out delta {worst_o} LSB")
    # end-to-end gated norm INCLUDING the op-3 norm-weight multiply
    w = np.round(rng.normal(1.0, 0.1, n) * (1 << 14)).astype(I64)
    dy, ny = 0, 0
    for _ in range(200):
        amp = 2.0 ** int(rng.integers(-6, 6))
        o = np.clip(np.round(rng.normal(0, amp, n) * (1 << S_F)),
                    -(1 << 31), (1 << 31) - 1).astype(I64)
        o16, k = dynq16_fx(o)
        globals()["SEQ_NORM"] = False
        y0 = script_norm_fx(o, o16, k, w, note=False)
        globals()["SEQ_NORM"] = True
        y1 = script_norm_fx(o, o16, k, w, note=False)
        globals()["SEQ_NORM"] = False
        dy = max(dy, int(np.abs(y1 - y0).max()))
        ny += int(np.array_equal(y0, y1))
    print(f"  gated-norm output (script_norm_fx, incl. norm_w op-3): "
          f"{ny}/200 heads bit-identical, max |delta| {dy} LSB")
    assert dy <= 4, dy
    # zero block -> zeros for any k
    assert not eps_norm_fx(np.zeros(n, dtype=I64), 0, note=False).any()
    for kz in (-14, 0, 17):
        assert not eps_norm_fx(np.zeros(n, dtype=I64), kz, note=False).any()
    # the 16-bit scale clamp is INERT on every non-zero block: DYNQ16 floors
    # |x|max at 16384, and the tightest such block (one element at the floor,
    # eps addend 0) is the global maximum of the scale
    tight = np.zeros(n, dtype=I64)
    tight[0] = 16384
    smax_nz = max(eps_norm_scale(tight, kt, note=False)
                  for kt in range(-14, 18))
    assert smax_nz == 46341 and smax_nz < M_Q15_MAX, smax_nz
    print(f"  scale ceiling on any NON-ZERO block: {smax_nz} < "
          f"{M_Q15_MAX} -> the cfg_p0/16-bit clamp is inert there")
    # RTL envelope (measured over the sweep above)
    s = SEQ_STATS
    vbits = int(max(1, np.ceil(np.log2(max(s["v_max"], 1) + 1))))
    print(f"  RTL envelope over {s['n']} vectors: p_in={s['p_min']}"
          f"..{s['p_max']} (6b port), k in [{s['k_min']},{s['k_max']}], "
          f"v_max={s['v_max']} (<2^{vbits}, 48b port), out shift "
          f"{s['sh_min']}..{s['sh_max']}, scale_max={s['scale_max']} "
          f"(clamped {s['clip']}x at {M_Q15_MAX})")
    print(f"  eps addend E(k): k=-14 -> {eps_ss_addend(-14)}, k=-4 -> "
          f"{eps_ss_addend(-4)}, k=0 -> {eps_ss_addend(0)}, k=4 -> "
          f"{eps_ss_addend(4)}, k=8 -> {eps_ss_addend(8)} "
          f"(EPS_M={EPS_M} at 2^-{EPS_Q})")
    assert s["p_min"] == s["p_max"] == 2 * S_F + 7   # k is NOT in rs_p
    assert s["v_max"] < (1 << 48) and vbits <= 43
    assert worst_s < 1e-3, worst_s
    assert worst_o <= 2, worst_o
    bf_reset()
    return True


def _selftest():
    rng = np.random.default_rng(21)
    ok = True

    # ---- sequencer rung-1 op specs (docs/SEQ_ISA.md) ----
    ok &= _dynq16_soak()
    ok &= _epsnorm_soak()

    # rmsnorm (1+w)
    x = rng.normal(0, 2, LR.H).astype(np.float64)
    w = rng.normal(0, 0.1, LR.H)
    x16 = np.round(x * (1 << RS_F)).astype(I64)
    wq = np.round(w * (1 << 14)).astype(I64)
    got = rmsnorm_fx(x16, wq, RS_F, True) / (1 << RS_F)
    ok &= _blk("rmsnorm1p", got, LR.rmsnorm1p(x, w), 2e-2)

    # rope
    cq, sq = rope_tables_q15(37)
    cf, sf = LR.rope_cos_sin(37)
    h = rng.normal(0, 1, LR.HD)
    h16 = np.round(h * (1 << QKV_F)).astype(I64)
    ok &= _blk("rope", rope_fx(h16, cq, sq) / (1 << QKV_F),
               LR.apply_rope(h.astype(np.float32), cf, sf), 1e-2)

    # l2norm
    v = rng.normal(0, 1.5, LR.LDK)
    v16 = np.round(v * (1 << QKV_F)).astype(I64)
    ok &= _blk("l2norm", l2norm_fx(v16, QKV_F, NRM_F) / (1 << NRM_F),
               LR.l2norm(v), 1e-2)

    # attention core: identical KV content, T=48
    T, HD = 48, LR.HD
    q = rng.normal(0, 1, HD); ks = rng.normal(0, 1, (T, HD)); vs = rng.normal(0, 1.2, (T, HD))
    # float
    sc = (ks @ q) / np.sqrt(HD); e = np.exp(sc - sc.max()); pf = e / e.sum()
    ref = pf @ vs
    # fixed (mirrors attn_decode_fx inner loop)
    qn = np.round(q * (1 << QKV_F)).astype(I64)
    sc_q = np.zeros(T, dtype=I64)
    kcache = [kv_quant(np.round(ks[t] * (1 << QKV_F)).astype(I64), QKV_F) for t in range(T)]
    vcache = [kv_quant(np.round(vs[t] * (1 << QKV_F)).astype(I64), QKV_F) for t in range(T)]
    SC = int(round((1 << 15) / np.sqrt(HD)))
    for t in range(T):
        k8, ke = kcache[t]
        dot = int((qn * k8.astype(I64)).sum())
        sq_ = rshr(I64(dot) * SC, 15)
        f = QKV_F - ke - 16
        sc_q[t] = rshr(I64(int(sq_)), f) if f >= 0 else int(sq_) << (-f)
    mx = int(sc_q.max())
    es = np.array([fp.exp_neg_q(int(min(int(sc_q[t]) - mx, 0))) for t in range(T)], dtype=I64)
    r, re = fp.recip_q(int(es.sum()), 30)
    pq = np.clip(rshr(es * r, 30 - re + 15), 0, 1 << 15)
    acc = np.zeros(HD, dtype=I64)
    for t in range(T):
        v8, ve = vcache[t]
        term = I64(int(pq[t])) * v8.astype(I64)
        sh = 15 - ve - QKV_F
        acc += rshr(term, sh) if sh >= 0 else term << (-sh)
    ok &= _blk("attn softmax+pv", acc / (1 << QKV_F), ref, 3e-2)

    # deltanet recurrence single step from identical NONZERO state
    LDK, LDV = LR.LDK, LR.LDV
    Sf = rng.normal(0, 0.01, (LDK, LDV)).astype(np.float32)
    qv = LR.l2norm(rng.normal(0, 1, LDK)) / np.sqrt(LDK)
    kv_ = LR.l2norm(rng.normal(0, 1, LDK))
    vv = rng.normal(0, 0.8, LDV).astype(np.float32)
    dec, bet = 0.21, 0.83
    Sf2 = Sf * dec
    kvm = Sf2.T @ kv_
    dlt = (vv - kvm) * bet
    Sf2 = Sf2 + np.outer(kv_, dlt)
    of = Sf2.T @ qv
    # fixed
    Sq = np.round(Sf * (1 << S_F)).astype(I64)
    qn16 = np.round(qv * (1 << NRM_F)).astype(I64)
    kn16 = np.round(kv_ * (1 << NRM_F)).astype(I64)
    v16_ = np.round(vv * (1 << S_F)).astype(I64)
    dq, bq = int(round(dec * (1 << GAT_F))), int(round(bet * (1 << GAT_F)))
    Sh = rshr(Sq * dq, GAT_F)
    kvm_q = rshr((Sh * kn16[:, None]).sum(axis=0), NRM_F)
    dlt_q = rshr((v16_ - kvm_q) * bq, GAT_F)
    Sh = Sh + rshr(kn16[:, None] * dlt_q[None, :], NRM_F)
    oq = rshr((Sh * qn16[:, None]).sum(axis=0), NRM_F)
    # bound = S_F=13 resolution at random-weight state rms ~0.01 (82 LSB);
    # o = 128-dim contraction -> ~3% inherent. Revisit w/ real weights (S5).
    ok &= _blk("deltanet step out", oq / (1 << S_F), of, 5e-2)
    ok &= _blk("deltanet step S", Sh / (1 << S_F), Sf2, 2e-2)

    # trajectory soak: only stability/saturation checked (not pointwise err).
    # Run at BOTH wire group sizes: g=128 is the default/legacy path, g=64 is
    # the v2 row format (same math, finer groups) — this proves the group size
    # is plumbed through quant_layer -> quant_* -> matvec_fx end to end.
    for lt in ["linear_attention", "full_attention"]:
        wf = LR.init_layer_weights(rng, lt)
        for g in (G, 64):
            qw = quant_layer(wf, g=g)
            sub = qw["attn"] if lt == "full_attention" else qw["dn"]
            key = "q_proj" if lt == "full_attention" else "in_qkv"
            assert sub[key]["g"] == g and qw["mlp"]["down"]["g"] == g
            assert sub[key]["m"].shape[1] == sub[key]["w4"].shape[1] // g
            cq2 = new_cache_fx(lt)
            xq = np.round(rng.normal(0, 1, LR.H) * (1 << RS_F)).astype(I64)
            for t in range(32):
                xq = layer_decode_fx(xq, qw, cq2, t)
            rms = float(np.sqrt(np.mean((xq / (1 << RS_F)) ** 2)))
            sat = cq2.get("sat", 0)
            good = bool(np.isfinite(rms) and rms < 100 and sat == 0)
            print(f"  soak {lt:18s} g={g:<4d} 32 steps: rms={rms:.2f} "
                  f"sat={sat} {'OK' if good else 'FAIL'}")
            ok &= good

    if ok:
        print("LAYER_FIXED SELFTEST PASS")
    else:
        raise SystemExit("LAYER_FIXED SELFTEST FAIL")


if __name__ == "__main__":
    _selftest()
