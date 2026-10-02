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

import fixedpoint as fp            # noqa: E402
import layer_fixed as LF           # noqa: E402
import layer_ref as LR             # noqa: E402
from gen_layer_script import (enc_a1, enc_alu_a0,           # noqa: E402
                              enc_alu_a2, enc_isa_saddr, enc_saddr)
from w4a8_ref import rshift_round as rshr   # noqa: E402

I64 = np.int64

OP_VN, OP_GATE, OP_DNST, OP_ALU, OP_DNZ = 1, 7, 8, 11, 12
AOP_ADD, AOP_EMUL32, AOP_DYNQ16 = 4, 8, 12

# scratch map (the LOW blocks; 64K x 16 scratchpad since G3.1)
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

# ---------------------------------------------------------------------
# G3.1: the TOP QUARTER of the 64K scratchpad (words 57344..65535).  Every
# scratch address field is 16 bits now, so the two bits that did not exist
# before R-b/G3.1 are bit 14 AND bit 15 — this block sets BOTH, and every
# case is ASYMMETRIC (one operand high, its pair-partner low) so a SWAPPED
# half assignment cannot pass; a symmetric high/high case would be blind
# to it.
# Field homes (SEQ_ISA v2.0): ARG1/ARG2 are {hi[31:16], lo[15:0]} on every
# command, GATE ARG0 dst[15:0], ALU ARG2 {dst[31:16], p0[15:0]}, and DNST's
# two scalar pointers are DNSB[15:0] + head / DNSB[31:16] + head.
#
# ALIASING IS THE TRAP THIS BLOCK IS BUILT AROUND.  If a top bit is simply
# DROPPED, every high address folds down — and a buffer whose write AND read
# both fold lands somewhere self-consistent, so a naive high-only round trip
# would still pass.  The high regions live at 0xE000+, which has BOTH top
# bits set, so there are TWO fold-down images (−0x8000 and −0x4000) and both
# hold nothing but a SENTINEL pattern written before the block and read back
# after it:
#   * a folded READ  picks up the sentinel   -> the op's own R fails;
#   * a folded WRITE overwrites the sentinel -> the closing sentinel R fails.
# ---------------------------------------------------------------------
B_LOX   = 0x1000       # 128 int16, LOW  half — the asymmetric partners
B_LOS   = 0x1100       # 128 int16, LOW  half — ADD dst
B_LON   = 0x1200       # 128 int16, LOW  half — VN dst
B_LODEC = 0x1300       # 1 word,    LOW  half — DNST decay
B_LOBET = 0x1301       # 1 word,    LOW  half — DNST beta
B_LOO   = 0x1400       # 256 words, LOW  half — DNST out (128 pairs)
B_LOB   = 0x1600       # 2*LNH words, LOW half — GATE src_b   (G3.4)
B_LODT  = 0x1640       # 2*LNH words, LOW half — GATE src_dt  (G3.4)
B_LOK   = 0x1800       # 128 int16, LOW  half — DNST k
B_LOQ   = 0x1900       # 128 int16, LOW  half — DNST q
B_LOV   = 0x1A00       # 128 int16, LOW  half — DNST v

B_HIX   = 0xE000       # 57344 — ADD srca / VN src
B_HIY   = 0xE080       # 57472 — ADD srcb
B_HIS   = 0xE100       # 57600 — ADD dst
B_HIN   = 0xE180       # 57728 — VN dst
# G3.4 RE-SPACED the hi-half GATE tiles for LNH = 32, which is what the
# assert in emit_hi_block() named as G3.4's: GATE dst is 2*LNH words, src_a
# is LNH and src_A is 2*LNH, so at 32 heads they need 64/32/64 instead of
# 32/16/32.  The DNST tiles below moved up 0x80 to make room.  The spacing
# is a SUPERSET of the LNH=16 one, so this file still emits a valid script
# at the 0.8B/2B geometry, with slack instead of a fit.
B_HIG   = 0xE200       # 57856 — GATE dst   (2*LNH words, 64 at LNH=32)
B_HIA   = 0xE240       # 57920 — GATE src_a (LNH words)
B_HIAC  = 0xE260       # 57952 — GATE src_A (2*LNH words, {lo,hi} pairs)
B_HIDEC = 0xE2A0       # 58016 — DNST decay BASE (head 0)
B_HIBET = 0xE2A1       # 58017 — DNST beta  BASE (head 0)
B_HIQ   = 0xE300       # 58112 — DNST q (128)
B_HIK   = 0xE380       # 58240 — DNST k (128)
B_HIV   = 0xE400       # 58368 — DNST v (128)
B_HIO   = 0xE480       # 58496 — DNST out (256)
B_TOPW  = 0xFFF0       # 65520 — ALU dst, 8 words just under the top
B_TOP   = 0xFFF8       # 65528 — the LAST 8 words of the 64K scratchpad

# fold-down images of everything above, filled with the sentinel pattern.
# 0xE000 has BOTH top bits set, so a dropped bit 15 folds to 0x6000 and a
# dropped bit 14 to 0xA000 — BOTH are covered.
B_SENT_AN = (B_HIO + 256) - B_HIX                              # 1280
B_SENT_A15, B_SENT_A14 = B_HIX - 0x8000, B_HIX - 0x4000        # 0x6000, 0xA000
B_SENT_BN = 16
B_SENT_B15, B_SENT_B14 = B_TOPW - 0x8000, B_TOPW - 0x4000      # 0x7FF0, 0xBFF0


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
    # SEQ_ISA v2.0: ARG0 = {spare[31:19], p0[16]@18, len[17:4], aop[3:0]}
    # and ARG2 = {dst[31:16], p0[15:0]} — p0's top bit is the ONE relocation
    # in the re-encoding, so the two words are packed TOGETHER by the
    # canonical helpers and never by hand here.
    rec_c(f, OP_ALU, enc_alu_a0(aop, length, p0), enc_a1(srca, srcb),
          enc_alu_a2(p0, dst))


def vn(f, mode, nlog2, inf, outf, src, dst, eps=0, xrf=0):
    rec_c(f, OP_VN, (outf << 10) | (inf << 6) | (nlog2 << 2) | mode,
          enc_a1(src, dst), (xrf << 1) | eps)


def gate(f, dst, src_b, src_a, src_A, src_dt):
    rec_c(f, OP_GATE, enc_isa_saddr(dst), enc_a1(src_b, src_a),
          enc_a1(src_A, src_dt))


def dnz(f, head):
    rec_c(f, OP_DNZ, head, 0, 0)


def dnsb(f, a_beta_base, a_dec_base):
    """The DNSB layer CSR record (SEQ_ISA v2.0): the DeltaNet scalar-pointer
    BASE PAIR {a_dec_base[31:16], a_beta_base[15:0]}, one per layer body."""
    a_beta_base = enc_isa_saddr(a_beta_base)
    a_dec_base = enc_isa_saddr(a_dec_base)
    f.write(f"B {(a_dec_base << 16) | a_beta_base:08x}\n")


def dnst(f, head, src_q, src_k, src_v, a_dec, a_beta, dst):
    """ARG0 is {spare[31:5], head[4:0]}: the two scalar pointers are NOT in
    the arg words, they come from DNSB as base + head (SEQ_ISA v2.0).

    `a_dec`/`a_beta` stay in the signature so the caller states what it
    means and this packer can refuse a pointer the DNSB base cannot
    produce — the same check `gen_layer_script.Mach.dnst` makes."""
    a_dec, a_beta = enc_isa_saddr(a_dec), enc_isa_saddr(a_beta)
    assert 0 <= head < 32, f"DNST head {head} does not fit ARG0[4:0]"
    rec_c(f, OP_DNST, head, enc_a1(src_q, src_k), enc_a1(src_v, dst))


def pairs(x32):
    out = []
    for v in np.asarray(x32, dtype=I64):
        out.append(int(v) & 0xFFFF)
        out.append((int(v) >> 16) & 0xFFFF)
    return out


def s16(v):
    """The signed value the scratchpad hands back for a 16-bit pattern."""
    v = np.asarray(v, dtype=I64) & 0xFFFF
    return np.where(v >= 32768, v - 65536, v)


# ------------------------------------------------------- reference models
# These mirror ref/gen_layer_script.py's Mach exactly (which mirrors
# rtl/layer_chan.sv).  They are re-stated rather than imported because the
# hi-address cases drive the units directly, with no Mach scratchpad.
def m_gate(b, a, A18, dt, nh=None):
    """gate_unit: LNH sigmoid betas then LNH exp(-softplus) decays.

    THIS FUNCTION IS THE LAYOUT AUTHORITY for the beta|decay tile — it is
    the WRITER, and DNST's two scalar pointers index what it writes.  It
    hard-coded `np.zeros(32)`, `range(16)` and `out[16 + h]` for LNH=16
    (spec 7.5 family D).  An assert anchored to an un-generalized authority
    would ratify the very layout it is meant to police, so this is
    generalized to LNH FIRST and the negative control runs against the
    generalized version (spec 4.3 S3 / G3.1 step 2)."""
    nh = LR.LNH if nh is None else int(nh)
    assert len(b) == len(a) == len(dt) == len(A18) == nh, (
        f"m_gate: got {len(b)}/{len(a)}/{len(A18)}/{len(dt)} inputs for "
        f"LNH={nh} — the beta|decay tile is nh + nh words, not 16 + 16")
    out = np.zeros(2 * nh, dtype=I64)
    for h in range(nh):
        out[h] = fp.sigmoid_q(int(b[h]))
        sp = fp.softplus_q(int(a[h] + dt[h]))
        g = -rshr(I64(int(A18[h])) * sp, 11)
        out[nh + h] = min(rshr(I64(fp.exp_neg_q(int(min(g, 0)))), 15),
                          I64(32767))
    return out


def m_dnst(S, dec, bet, q, k, v16):
    """dn_step on the CURRENT state; returns (new state, 128 int32 out)."""
    v = np.asarray(v16, dtype=I64) << (LF.S_F - LF.QKV_F)
    q = np.asarray(q, dtype=I64)
    k = np.asarray(k, dtype=I64)
    Sh = rshr(S * I64(int(dec)), LF.GAT_F)
    kvm = rshr((Sh * k[:, None]).sum(axis=0), LF.NRM_F)
    dlt = rshr((v - kvm) * I64(int(bet)), LF.GAT_F)
    Sr = Sh + rshr(k[:, None] * dlt[None, :], LF.NRM_F)
    Sn = np.clip(Sr, -32768, 32767)
    o = rshr((Sn * q[:, None]).sum(axis=0), LF.NRM_F)
    return Sn, o


def emit_hi_block(f, rng):
    """G3.1: the TOP QUARTER of the 64K scratchpad, one asymmetric case per
    address half.

    Every command here has exactly one operand in each half, so the test
    fails BOTH when a top address bit is dropped (the address folds down into
    a sentinel image, wrong data) AND when the two halves of a pair are
    swapped.  The block sits at 0xE000+, which has BOTH bit 15 and bit 14
    set, so there are TWO fold-down images and a drop of EITHER bit is
    caught.  (At R-b this was the >16K half and the bit under test was 14
    alone.)  Returns a summary dict for the generator's stdout line."""
    n = 128
    LDK = LR.LDK

    # ---- data ----
    hix = rng.integers(-12000, 12001, n, dtype=np.int64)
    hiy = rng.integers(-12000, 12001, n, dtype=np.int64)
    lox = rng.integers(-12000, 12001, n, dtype=np.int64)
    top = rng.integers(-30000, 30001, 8, dtype=np.int64)

    # ---- 1. ALU ADD: srca/srcb/dst, one high one low each way ----------
    s_hi = np.clip(hix + lox, -32768, 32767)      # dst HIGH  (ARG2[31] = 1)
    s_lo = np.clip(lox + hiy, -32768, 32767)      # dst LOW   (ARG2[31] = 0)
    s_top = np.clip(hix[:8] + hiy[:8], -32768, 32767)

    # ---- 2. VN mode 2 (l2norm, ARG2 == 0), both directions -------------
    y_hn = LF.l2norm_fx(hix, LF.QKV_F, LF.NRM_F)  # src HIGH -> dst LOW
    y_lh = LF.l2norm_fx(lox, LF.QKV_F, LF.NRM_F)  # src LOW  -> dst HIGH

    # ---- 3. GATE: dst + 4 sources spread across both halves ------------
    # LAYOUT AUTHORITY for the hi-half GATE tiles: their SLOTS are literals
    # in the map above, so assert the USED extent fits, exactly as
    # ref/gen_layer_script.py's SCA map does.  At LNH=32 (4B/9B) this fires
    # and points at the task that owns it.  It lives HERE and not at module
    # scope so this file can still be IMPORTED at a 9B geometry (which
    # evidence/qwen9b/g3/isa_bits.py does) without exploding.
    NH = LR.LNH
    # G3.4 re-spaced these for LNH = 32; the assert stays, because it is
    # the LAYOUT AUTHORITY and the next geometry change must trip it too.
    # The LOW-half GATE tiles are checked here as well — they were 16-word
    # slots and the earlier assert did not cover them.
    assert B_HIG + 2 * NH <= B_HIA and B_HIA + NH <= B_HIAC \
        and B_HIAC + 2 * NH <= B_HIDEC \
        and B_LOB + NH <= B_LODT and B_LODT + NH <= B_LOK, (
            f"the GATE tiles do not fit LNH={NH}; re-space "
            f"B_HIG/B_HIA/B_HIAC (hi) and B_LOB/B_LODT (lo)")
    gb = rng.integers(-8000, 8001, NH, dtype=np.int64)      # LOW  (b)
    ga = rng.integers(-8000, 8001, NH, dtype=np.int64)      # HIGH (a)
    gdt = rng.integers(-4000, 4001, NH, dtype=np.int64)     # LOW  (dt)
    gA = rng.integers(1, 1 << 17, NH, dtype=np.int64)       # HIGH (A, 18b)
    gy = m_gate(gb, ga, gA, gdt)
    gA_words = []
    for v in gA:
        gA_words.append(int(v) & 0xFFFF)
        gA_words.append((int(v) >> 16) & 0x3)

    # ---- 4. DNST: the DNSB base pair, high and low --------------------
    # SEQ_ISA v2.0 takes a_dec/a_beta from the DNSB CSR as base + head, so
    # the thing under test is no longer a scattered bit in ARG1 but the two
    # 16-bit halves of DNSB.  Each probe programs ONE half high and the
    # other low, which is the same asymmetry the R-b block used.
    # a_dec only MATTERS once the DeltaNet state is non-zero, so DNZ is
    # followed by a warm-up step and only then by the two probe steps.
    dec_lo, dec_hi = 21000, 30000
    bet_lo, bet_hi = 9000, 26000
    dq = rng.integers(-2000, 2001, LDK, dtype=np.int64)
    dk = rng.integers(-2000, 2001, LDK, dtype=np.int64)
    dv = rng.integers(-2000, 2001, LDK, dtype=np.int64)
    S0 = np.zeros((LDK, LR.LDV), dtype=I64)
    S1, o_a = m_dnst(S0, dec_lo, bet_lo, dq, dk, dv)        # warm-up
    S2, o_b = m_dnst(S1, dec_hi, bet_lo, dq, dk, dv)        # a_dec  HIGH
    _S3, o_c = m_dnst(S2, dec_lo, bet_hi, dq, dk, dv)       # a_beta HIGH
    # each probe is only worth running if reading the scalar from the OTHER
    # (low) address would change the answer — i.e. the case can actually fail
    _, o_b_bad = m_dnst(S1, dec_lo, bet_lo, dq, dk, dv)
    assert not np.array_equal(o_b, o_b_bad), \
        "DNST a_dec probe is blind: dec_lo and dec_hi give the same output"
    _, o_c_bad = m_dnst(S2, dec_lo, bet_lo, dq, dk, dv)
    assert not np.array_equal(o_c, o_c_bad), \
        "DNST a_beta probe is blind: bet_lo and bet_hi give the same output"

    # ---- 5. the sentinel images of the whole high block -----------------
    # Two images each: one for a dropped bit 15, one for a dropped bit 14.
    # They carry DIFFERENT patterns so a fold that lands in the wrong image
    # is still a mismatch rather than a coincidence.
    sent_a15 = s16(np.array([0x5A00 ^ (i * 7919 & 0x7FFF)
                             for i in range(B_SENT_AN)], dtype=np.int64))
    sent_a14 = s16(np.array([0x2D00 ^ (i * 5147 & 0x7FFF)
                             for i in range(B_SENT_AN)], dtype=np.int64))
    sent_b15 = s16(np.array([0x3C00 ^ (i * 6151 & 0x7FFF)
                             for i in range(B_SENT_BN)], dtype=np.int64))
    sent_b14 = s16(np.array([0x1E00 ^ (i * 4093 & 0x7FFF)
                             for i in range(B_SENT_BN)], dtype=np.int64))

    # ================= records =========================================
    rec_w(f, B_SENT_A15, sent_a15)
    rec_w(f, B_SENT_A14, sent_a14)
    rec_w(f, B_SENT_B15, sent_b15)
    rec_w(f, B_SENT_B14, sent_b14)
    rec_w(f, B_HIX, hix)
    rec_w(f, B_HIY, hiy)
    rec_w(f, B_LOX, lox)
    rec_w(f, B_TOP, top)
    rec_r(f, B_TOP, top)                 # SPTR/SWIN reach the LAST word

    # ALU ADD, three address shapes
    alu(f, AOP_ADD, n, B_HIX, B_LOX, B_HIS, 0)
    rec_r(f, B_HIS, s_hi)
    alu(f, AOP_ADD, n, B_LOX, B_HIY, B_LOS, 0)
    rec_r(f, B_LOS, s_lo)
    alu(f, AOP_ADD, 8, B_HIX, B_HIY, B_TOPW, 0)
    rec_r(f, B_TOPW, s_top)

    # VN mode 2 (legacy l2norm, ARG2 == 0), both directions
    vn(f, 2, 7, LF.QKV_F, LF.NRM_F, B_HIX, B_LON)
    rec_r(f, B_LON, y_hn)
    vn(f, 2, 7, LF.QKV_F, LF.NRM_F, B_LOX, B_HIN)
    rec_r(f, B_HIN, y_lh)

    # GATE
    rec_w(f, B_LOB, gb)
    rec_w(f, B_HIA, ga)
    rec_w(f, B_HIAC, gA_words)
    rec_w(f, B_LODT, gdt)
    gate(f, B_HIG, B_LOB, B_HIA, B_HIAC, B_LODT)
    rec_r(f, B_HIG, gy)

    # DNST
    rec_w(f, B_LODEC, [dec_lo])
    rec_w(f, B_LOBET, [bet_lo])
    rec_w(f, B_HIDEC, [dec_hi])
    rec_w(f, B_HIBET, [bet_hi])
    rec_w(f, B_HIQ, dq)
    rec_w(f, B_LOK, dk)
    rec_w(f, B_HIV, dv)
    dnz(f, 0)
    #   warm-up: q HIGH / k LOW, v HIGH / dst LOW, both DNSB halves LOW
    dnsb(f, B_LOBET, B_LODEC)
    dnst(f, 0, B_HIQ, B_LOK, B_HIV, B_LODEC, B_LOBET, B_LOO)
    rec_r(f, B_LOO, pairs(o_a))
    #   a_dec HIGH (DNSB[31:16] high, [15:0] low), q LOW / k HIGH,
    #   v LOW / dst HIGH
    rec_w(f, B_LOQ, dq)
    rec_w(f, B_HIK, dk)
    rec_w(f, B_LOV, dv)
    dnsb(f, B_LOBET, B_HIDEC)
    dnst(f, 0, B_LOQ, B_HIK, B_LOV, B_HIDEC, B_LOBET, B_HIO)
    rec_r(f, B_HIO, pairs(o_b))
    #   a_beta HIGH (DNSB[15:0] high), everything else back to shape one
    dnsb(f, B_HIBET, B_LODEC)
    dnst(f, 0, B_HIQ, B_LOK, B_HIV, B_LODEC, B_HIBET, B_LOO)
    rec_r(f, B_LOO, pairs(o_c))

    # ---- the sentinels must be untouched: nothing folded down ----------
    rec_r(f, B_SENT_A15, sent_a15)
    rec_r(f, B_SENT_A14, sent_a14)
    rec_r(f, B_SENT_B15, sent_b15)
    rec_r(f, B_SENT_B14, sent_b14)

    return {"dec": (dec_lo, dec_hi), "bet": (bet_lo, bet_hi),
            "sent": 2 * (B_SENT_AN + B_SENT_BN)}


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

        # ---- G3.1: the top quarter (16-bit scratch addressing) ----
        hi = emit_hi_block(f, rng)
        f.write("Q\n")

    print(f"seq layer script: seed={seed} -> {path}  k_t={kt} k_clamp0={ktc} "
          f"k_a={ka} k_b={kb}; goldens distinct: "
          f"y(k_t)!=y(0) {not np.array_equal(y_t, y_0)}, "
          f"y(k_t)!=y(k_a) {not np.array_equal(y_t, y_a)}, "
          f"y(k_t)!=y(k_b) {not np.array_equal(y_t, y_b)}; "
          f"hi-half block: ALU/VN/GATE/DNST across words 57344..65535, "
          f"{hi['sent']} fold-down sentinels (DNST dec {hi['dec']}, "
          f"beta {hi['bet']})")


if __name__ == "__main__":
    main()
