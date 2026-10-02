#!/usr/bin/env python3
"""seq_format.py — the binary SEQ record stream (docs/SEQ_ISA.md v1).

Three things live here:

  1. THE WIRE FORMAT.  `pack()` / `unpack()` / `disasm()` / `validate()` for
     the 128-bit little-endian record, plus every opcode / flag / CSR-id /
     XRF constant.  This module is the single source of truth for the
     encoding; ref/seq_model.py executes it and the RTL builds to it.

  2. THE EMITTER.  `SeqEmitter` is an OPT-IN observer of
     gen_layer_script.Mach.  With it attached, the generators write
     `<prefix>.seq` (raw records, DMA-ready), `<prefix>.seqdata.bin` (the
     constant blob the LDC records read) and `<prefix>.seq.json` (metadata:
     record count, weight/const DDR plan, expected tokens, profile) ALONGSIDE
     the .txt script.  With it detached — the default — not a single byte of
     generator output changes (proved by regen-hash, see the module test).

  3. THE NEW COMPUTE-OP REFERENCE SHIMS.  `dynq16_fx` / `eps_norm_fx`.
     Agent A owns these in ref/layer_fixed.py; this module imports them from
     there when present and otherwise provides the documented-signature
     fallback below, so the two can be reconciled by deleting the fallback.

------------------------------------------------------------------------
Record (16 B, little-endian, exactly docs/SEQ_ISA.md)
------------------------------------------------------------------------
    [7:0]     opcode
    [15:8]    flags
    [31:16]   target
    [63:32]   imm32
    [95:64]   addr_lo
    [127:96]  len_or_addr_hi

i.e. four LE uint32 words: {opcode|flags<<8|target<<16}, imm32, addr_lo,
len_or_addr_hi.

------------------------------------------------------------------------
DEVIATIONS / AMBIGUITIES vs the frozen ISA text (all flagged, none silent)
------------------------------------------------------------------------
Every item below is a place where SEQ_ISA.md v1 is not executable as
written.  Each has a `SEQ_ISA_NOTE_*` constant so a re-freeze can grep them.

A1  flags[7:4] is triple-booked: it is the XRF index of the indirection
    mode AND the engine channel of MOVX/MVGO AND (bit 4 only) the MOVY
    output mode.  Resolution used here: MOVX/MVGO keep flags[7:4]=chan and
    are FORBIDDEN from using indirection (validate() enforces it); MOVY
    takes its channel from target[3:0], its mode from flags[4] and its XRF
    index from flags[7:5].  Everything else follows the ISA rule verbatim.

A2  The matvec dequant shift needs `imm32 - XRF[0]`, not `+`: the host
    computes it as `shift_for() = (15-e-sh) - e_x + in_f - out_f`, so the
    e_x term enters NEGATED.  The ISA only defines an add and states
    "XRF[0] = e_x".  Resolution: a second indirection code IND_SUB (0x2)
    meaning `imm32 - XRF[i]`.  The zero-new-logic alternative is to latch
    -e_x into XRF[0], which contradicts the ISA sentence; pick one at the
    re-freeze.  Both are implemented (see `resolve_imm`).

A3  CLOSED by ISA v1.3 + v1.4 (wave 3).  The gated-attention o_proj requant
    shift is `const - e_x - k_a`, i.e. it needs TWO XRF addends and ISA
    indirection carries one.  The emitter now (a) computes k_a on chip with
    the vec_alu op-8 PROBE (cfg_p0[6], -> XRF[2]) after re-ordering the
    gated-attention block so ONE op-8 sees every head's products
    (SeqEmitter._emit_attn_block), and (b) precombines the two addends with
    XOP into the spare XRF[5], which the MOVY then reads with a single
    IND_ADD.  k_a no longer appears anywhere in the record stream, which is
    what lets a stack containing full_attention layers close its decode
    loop.  `dyn_ka=False` (SEQ_DYNKA=0) restores the old constant emission
    for A/B comparison.

A4  "vecnorm mode 2 EPS-NORM" collides with the SHIPPED vecnorm mode 2
    (l2norm, rtl/vecnorm.sv + layer_fixed.l2norm_fx), and the VN arg0 mode
    field is only 2 bits ([1:0], nlog2 sits at [5:2]) so it cannot widen.
    Resolution: keep mode=2 and use the VN command's ARG2 word — which is
    hardwired 0 today, so this is a free, back-compatible extension:
        ARG2[0]   1 = EPS-NORM, 0 = l2norm (the shipped behaviour)
        ARG2[3:1] XRF index supplying k
    ARG2 also has no other consumer, so nothing moves.

A5  RESOLVED BY AGENT A (layer_fixed.eps_norm_scale, landed 2026-08-08).
    The ISA's one-line formula is under-determined: `k` looks like it must
    enter twice (mean denominator AND output binary point).  The frozen
    integer spec instead puts k in exactly ONE place — the shift of the
    integer eps addend E = rshr64(EPS_M, EPS_Q - (2*(in_f-k) + n_log2)) —
    and lets the rsqrt exponent absorb the rest, so the output shift
    sh = in_f - out_f + 15 - e has no k in it.  seq_format/seq_model call
    layer_fixed directly; the float fallback here is dead once A is in.

A6  MOVY reads RES rows [0,len) — there is no RES row offset — so one MVGO
    must produce exactly the rows one MOVY consumes.  Emission therefore
    sizes the engine row-chunk to the consumer chunk (<= RES_DEPTH).  This
    is free (matvec is row-separable) but it is a constraint on the RTL.

A7  MVGO must carry WBASE(40b) + BEATS + SHAPE in {imm32, addr_lo,
    len_or_addr_hi}.  Resolution: imm32 = SHAPE, addr_lo = WBASE[31:0],
    len_or_addr_hi = {beats[23:0], wbase[39:32]}.

A8  csr_id "0x1cn = matvec chan c reg n" cannot address matvec registers
    above 0x0F (R_SHAPE is 0x14, R_IDENT 0x34).  Widened to
    0x1000 | c<<8 | byte_offset; layer stays 0x0nn; 0x2nn is claimed for
    the sequencer's own block (XRF write port, TCNT_SEQ).

A9  There is NO opcode for "DDR -> scratch constant load".  Today the host
    W-records stage conv weights, ln1/ln2, RoPE tables, A/dt_bias, norm_w,
    q_norm/k_norm every token — ~2.2K int16 per DeltaNet layer per token,
    ~50K MMIO words/token over 24 layers, which is the single biggest
    remaining host cost after the command stream.  A sequencer without it
    cannot reach the rung-1 target.  PROPOSED opcode 0x0B LDC is emitted
    here (marked EXT_*), with a CSRWR(SPTR)+n*CSRWR(SWIN) fallback shown in
    `ldc_as_csrwr_cost()` for comparison.

A10 CLOSED (wave 3).  The decode loop body used to differ per step in
    (a) the RoPE table constant (position-dependent — solved by the strided
    position pool + XOP-advanced XRF[4] cursor on an indirected LDC),
    (b) the DN k_h/m_q15 immediates (solved by DYNQ16 + EPS-NORM, i.e. the
    epsnorm profile), and (c) the ATTN op-8 k_a immediate (solved by A3
    above).  With profile="epsnorm" and dyn_ka=True every one of them is
    gone, so stacks CONTAINING full_attention layers now close
    (`loop_structurally_safe` in the .seq.json).  In the "xlat" profile the
    DN pair is still a literal, so those streams still unroll.
"""
import hashlib
import json
import os
import struct
import sys

import numpy as np

# hwmap.py is the device map; it lives under sw/ and is READ-ONLY here.
_SW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sw")
if _SW not in sys.path:
    sys.path.insert(0, _SW)
import hwmap as HW                                        # noqa: E402
# The 16-bit scratch address packing (G3.1 / SEQ_ISA v2.0) is defined ONCE,
# beside the emitter that produces it — never re-derived here.  This file is
# the LARGEST CONSUMER of those helpers (spec 7.6 D: ~35 sites that open an
# ARG word and rebuild it) but it is NOT a fourth implementation of the
# layout, and it must not become one.
import gen_layer_script as _GLS                            # noqa: E402
from gen_layer_script import (dec_a1_lo, dec_a1_hi,        # noqa: E402
                              dec_alu_dst, dec_alu_len, dec_alu_p0,
                              enc_a1, enc_alu_a0, enc_alu_a2)

# ----------------------------------------------------------------------
# record layout
# ----------------------------------------------------------------------
REC_BYTES = 16
_STRUCT = struct.Struct("<4I")

MAGIC = b"FAB5SEQ1"
FORMAT_VERSION = 1

# ----------------------------------------------------------------------
# opcodes (0x01..0x0A are docs/SEQ_ISA.md v1; 0x0B+ are PROPOSED, see A9/A10)
# ----------------------------------------------------------------------
OP_CSRWR = 0x01
OP_CMD   = 0x02
OP_MOVX  = 0x03
OP_MOVY  = 0x04
OP_MVGO  = 0x05
OP_EMB   = 0x06
OP_AMAXL = 0x07
OP_JMP   = 0x08
OP_FENCE = 0x09
OP_HALT  = 0x0A
EXT_LDC  = 0x0B          # ISA v1.1 (A9): DDR const blob -> scratch
EXT_XOP  = 0x0C          # ISA v1.1 (A2/A3): XRF ALU, see xop_imm() below
EXT_XADD = EXT_XOP       # legacy spelling (v1.4 D-1: 0x0C is XOP everywhere)

ISA_V1_OPS = {OP_CSRWR, OP_CMD, OP_MOVX, OP_MOVY, OP_MVGO, OP_EMB,
              OP_AMAXL, OP_JMP, OP_FENCE, OP_HALT}
EXT_OPS = {EXT_LDC, EXT_XOP}
ALL_OPS = ISA_V1_OPS | EXT_OPS

OP_NAME = {OP_CSRWR: "CSRWR", OP_CMD: "CMD", OP_MOVX: "MOVX", OP_MOVY: "MOVY",
           OP_MVGO: "MVGO", OP_EMB: "EMB", OP_AMAXL: "AMAXL", OP_JMP: "JMP",
           OP_FENCE: "FENCE", OP_HALT: "HALT",
           EXT_LDC: "LDC*", EXT_XOP: "XOP*"}
NAME_OP = {v.rstrip("*"): k for k, v in OP_NAME.items()}

# ----------------------------------------------------------------------
# flags
# ----------------------------------------------------------------------
IND_MASK = 0x0F                  # flags[3:0]
IND_NONE = 0x0                   # imm32 as-is
IND_ADD  = 0x1                   # imm32 + XRF[i]      (ISA v1)
IND_SUB  = 0x2                   # imm32 - XRF[i]      (PROPOSED, see A2)
IND_MODES = {IND_NONE, IND_ADD, IND_SUB}
IND_NAME = {IND_NONE: "", IND_ADD: "+xrf", IND_SUB: "-xrf"}

XRF_SHIFT = 4                    # flags[7:4] = XRF index (general rule)
CHAN_SHIFT = 4                   # flags[7:4] = engine channel (MOVX/MVGO)
MOVY_MODE_BIT = 0x10             # flags[4]: 0 = pairs32, 1 = int16   (A1)
MOVY_XRF_SHIFT = 5               # flags[7:5] = XRF index for MOVY    (A1)

JMP_TCNT = 0x1                   # flags 0x1 on JMP: dec TCNT_SEQ, jump if != 0

MOVY_PAIRS32 = 0
MOVY_INT16 = 1

# MVGO target[0] = NO-WAIT variant (ISA v1.4): start the channel and retire
# without polling done; FENCE drains it.  target[15:1] is reserved 0.
MVGO_NOWAIT = 0x1

# ----------------------------------------------------------------------
# XOP (0x0C) field packing — ISA v1.1 opcode text, rtl/seq_unit.sv:602-625
#
#   XRF[target[2:0]] = s1*XRF[imm32[2:0]] + s2*XRF[imm32[6:4]]
#                      + simm18(imm32[31:14])
#   s1 = imm32[9:8], s2 = imm32[11:10];  00 = 0, 01 = +1, 10 = -1,
#   11 = decode error (v1.4 ruling D-1).
#
# XADD (the pre-v1.4 spelling of "XRF[t] += imm") is exactly
#   xop_imm(a=t, s1=XOP_POS, simm=imm)  — same 16 bytes, one opcode.
# ----------------------------------------------------------------------
XOP_ZERO, XOP_POS, XOP_NEG, XOP_BAD = 0, 1, 2, 3
XOP_SGN_NAME = {XOP_ZERO: "0", XOP_POS: "+", XOP_NEG: "-", XOP_BAD: "?"}
XOP_SIMM_SHIFT = 14
XOP_SIMM_BITS = 18


def xop_imm(a=0, s1=XOP_ZERO, b=0, s2=XOP_ZERO, simm=0):
    """Build the imm32 word of an XOP record (see the field map above)."""
    assert 0 <= a < XRF_N and 0 <= b < XRF_N, "XOP source index out of range"
    assert s1 in (XOP_ZERO, XOP_POS, XOP_NEG), f"XOP s1 code {s1} illegal"
    assert s2 in (XOP_ZERO, XOP_POS, XOP_NEG), f"XOP s2 code {s2} illegal"
    lim = 1 << (XOP_SIMM_BITS - 1)
    assert -lim <= int(simm) < lim, \
        f"XOP simm {simm} does not fit signed {XOP_SIMM_BITS}b"
    return ((a & 0x7) | ((b & 0x7) << 4) | ((s1 & 0x3) << 8)
            | ((s2 & 0x3) << 10)
            | ((int(simm) & ((1 << XOP_SIMM_BITS) - 1)) << XOP_SIMM_SHIFT))


def xop_fields(imm32):
    """Decode an XOP imm32 -> (a, s1, b, s2, simm_signed)."""
    imm32 = int(imm32) & 0xFFFFFFFF
    simm = imm32 >> XOP_SIMM_SHIFT
    if simm >= (1 << (XOP_SIMM_BITS - 1)):
        simm -= 1 << XOP_SIMM_BITS
    return (imm32 & 0x7, (imm32 >> 8) & 0x3, (imm32 >> 4) & 0x7,
            (imm32 >> 10) & 0x3, simm)


def xop_eval(imm32, xrf):
    """The XOP result, exactly as rtl/seq_unit.sv computes it."""
    a, s1, b, s2, simm = xop_fields(imm32)
    sgn = {XOP_ZERO: 0, XOP_POS: 1, XOP_NEG: -1}
    if s1 == XOP_BAD or s2 == XOP_BAD:
        raise SeqValidationError("XOP sign code 11 is a decode error (D-1)")
    return sgn[s1] * int(xrf[a]) + sgn[s2] * int(xrf[b]) + simm

# ----------------------------------------------------------------------
# XRF (8 x signed 18 bit)
# ----------------------------------------------------------------------
XRF_N = 8
XRF_BITS = 18
XRF_EX = 0        # DYNQ8 EOUT  (e_x)
XRF_K_DN = 1      # DYNQ16 -> DeltaNet head shift k_h
XRF_K_ATTN = 2    # DYNQ16 -> attention shared shift k_a
XRF_TOK = 3       # current token id (AMAXL writer / host prompt feed)
XRF_POS = 4       # EXT: position-indexed constant cursor (A10)
XRF_OSHIFT = 5    # EXT: XOP scratch holding const - e_x - k_a (A2/A3)
XRF_NAME = {0: "e_x", 1: "k_dn", 2: "k_attn", 3: "tok", 4: "pos",
            5: "oshift"}


def xrf_clip(v):
    """XRF is signed 18b; writers saturate-free wrap is NOT assumed — the
    reference asserts the value fits, so an out-of-range latch is a bug."""
    v = int(v)
    lim = 1 << (XRF_BITS - 1)
    assert -lim <= v < lim, f"XRF value {v} does not fit signed {XRF_BITS}b"
    return v


# ----------------------------------------------------------------------
# CSR id space  (A8)
# ----------------------------------------------------------------------
CSR_SPACE_LAYER = 0x0000
CSR_SPACE_MV = 0x1000
CSR_SPACE_SEQ = 0x2000


def csr_layer(off):
    """csr_id of layer_chan byte offset `off` (0x00..0xFF)."""
    assert 0 <= off <= 0xFF
    return CSR_SPACE_LAYER | off


def csr_mv(chan, off):
    """csr_id of matvec_chan `chan` register byte offset `off`."""
    assert 0 <= chan < 4 and 0 <= off <= 0xFF
    return CSR_SPACE_MV | (chan << 8) | off


def csr_seq(off):
    """csr_id inside the sequencer's own CSR block."""
    assert 0 <= off <= 0xFF
    return CSR_SPACE_SEQ | off


# THE ISA GENERATION THIS TREE EMITS AND DECODES.  One constant, no
# behaviour attached: it exists so a check can SAY which encoding it is
# looking at instead of guessing.  v1 = SEQ_ISA v1.7 (R-b's 15-bit
# bit-scatter, what build_034/build_035 run); v2 = SEQ_ISA v2.0 (G3.1's
# clean 16+16 pairs + the DNSB CSR).  There is deliberately NO v1 path in
# this tree — the 0.8B/2B artifacts are served from a pre-G3 checkout.
SEQ_ISA_VERSION = 2

# layer_chan register offsets, relative to hwmap.LB
LOFF_CMD, LOFF_STAT = 0x00, 0x04
LOFF_ARG0, LOFF_ARG1, LOFF_ARG2 = 0x08, 0x0C, 0x10
LOFF_SPTR, LOFF_SWIN, LOFF_EOUT, LOFF_TCNT = 0x14, 0x18, 0x1C, 0x20
# G3.4: at NKVH = 4 a kv_slot has FOUR 10-bit append counters and a
# 32-bit CSR word holds two, so kvheads 2/3 live at their own offset
# (rtl/layer_chan.sv CSR 0x60, sw/hwmap.py L_TCNT2).  A SEQ program
# that resets T must write BOTH or half the counters keep a stale
# value -- the emitter half of spec 4.6's wall-9 lockstep.
LOFF_TCNT2 = 0x60
LOFF_AMAXI, LOFF_AMAXV, LOFF_LAYER = 0x28, 0x2C, 0x30
# SEQ_ISA v2.0 (G3.1): the DeltaNet scalar-pointer BASE PAIR,
# {a_dec_base[31:16], a_beta_base[15:0]}, written once per layer body.
LOFF_DNSB = 0x5C

CSR_L_CMD = csr_layer(LOFF_CMD)
CSR_L_ARG0, CSR_L_ARG1, CSR_L_ARG2 = (csr_layer(LOFF_ARG0),
                                      csr_layer(LOFF_ARG1),
                                      csr_layer(LOFF_ARG2))
CSR_L_SPTR, CSR_L_SWIN = csr_layer(LOFF_SPTR), csr_layer(LOFF_SWIN)
CSR_L_TCNT, CSR_L_LAYER = csr_layer(LOFF_TCNT), csr_layer(LOFF_LAYER)
CSR_L_TCNT2 = csr_layer(LOFF_TCNT2)
CSR_L_DNSB = csr_layer(LOFF_DNSB)

# ---------------------------------------------------------------------
# v2.1 (B15): layer state in DDR.  docs/SEQ_ISA.md B15 is the contract;
# this block is its reference mirror and sw/hwmap.py is the host's.  The
# three are tied by evidence/qwen9b/s1/sdma_bits.py, which also reads the
# RTL half (RED until Task S2 lands it).
LOFF_SB_DN, LOFF_SB_KV, LOFF_SB_CV, LOFF_SDMA, LOFF_SDMA_CYC = 0x64, 0x68, 0x6C, 0x70, 0x74
CSR_L_SB_DN, CSR_L_SB_KV = csr_layer(LOFF_SB_DN), csr_layer(LOFF_SB_KV)
CSR_L_SB_CV, CSR_L_SDMA, CSR_L_SDMA_CYC = csr_layer(LOFF_SB_CV), csr_layer(LOFF_SDMA), csr_layer(LOFF_SDMA_CYC)
OP_L_SLD, OP_L_SST = 13, 14
SDMA_KIND_DN, SDMA_KIND_KV, SDMA_KIND_CV = 0, 1, 2
ERR_CODE = {0x01: "E_ENV", 0x02: "E_LAYER", 0x10: "E_DMA_BASE", 0x11: "E_DMA_RANGE",
            0x12: "E_DMA_AXI", 0x13: "E_DMA_COLD"}
E_ENV, E_LAYER, E_DMA_BASE, E_DMA_RANGE, E_DMA_AXI, E_DMA_COLD = 0x01, 0x02, 0x10, 0x11, 0x12, 0x13
STATE_T_MAX = 4096


def sdma_arg0(kind, slot, layer, head):
    """B15.1: {kind[12:11], slot[10], layer[9:5], head[4:0]}."""
    assert kind in (SDMA_KIND_DN, SDMA_KIND_KV, SDMA_KIND_CV), kind
    assert slot in (0, 1), slot
    lmax = 7 if kind == SDMA_KIND_KV else 23
    assert 0 <= layer <= lmax, (kind, layer)
    hmax = {SDMA_KIND_DN: 0, SDMA_KIND_KV: 7, SDMA_KIND_CV: 0}[kind]
    assert 0 <= head <= hmax, (kind, head)
    return (kind << 11) | (slot << 10) | (layer << 5) | head


def sdma_fields(arg0):
    return (arg0 >> 11) & 3, (arg0 >> 10) & 1, (arg0 >> 5) & 31, arg0 & 31


def layer_word(dn_slot, kv_slot, cv_slot, kv_layer):
    """B15.2: {cv_slot[13:12], kv_layer[10:8], kv_slot[4:3], dn_slot[1:0]}."""
    assert dn_slot in (0, 1) and kv_slot in (0, 1) and cv_slot in (0, 1) and 0 <= kv_layer <= 7
    return (cv_slot << 12) | (kv_layer << 8) | (kv_slot << 3) | dn_slot


# sequencer block offsets
SOFF_TCNT_SEQ = 0x20             # token counter consumed by JMP flags 0x1
SOFF_XRF0 = 0x40                 # XRF[i] write port at SOFF_XRF0 + 4*i
CSR_SEQ_TCNT = csr_seq(SOFF_TCNT_SEQ)


def csr_seq_xrf(i):
    assert 0 <= i < XRF_N
    return csr_seq(SOFF_XRF0 + 4 * i)


def csr_to_axil(csr_id):
    """csr_id -> AXI-Lite byte address in the csr_0 BAR (the SEQ issue port).

    The sequencer block's own base is not in hwmap yet (it is a stage-6 CSR
    add); SEQ_CSR_BASE below is the placeholder the RTL must adopt or this
    function must be updated with.
    """
    sp = csr_id & 0xF000
    if sp == CSR_SPACE_LAYER:
        return HW.LB + (csr_id & 0xFF)
    if sp == CSR_SPACE_MV:
        return HW.mv_base((csr_id >> 8) & 0xF) + (csr_id & 0xFF)
    if sp == CSR_SPACE_SEQ:
        return SEQ_CSR_BASE + (csr_id & 0xFF)
    raise ValueError(f"csr_id {csr_id:#06x}: unknown space")


SEQ_CSR_BASE = 0x6000            # placeholder; layer_chan is 0x5000

# ----------------------------------------------------------------------
# DDR plan constants used by the emitter's metadata (host-side only)
# ----------------------------------------------------------------------
SEQ_DATA_BASE = 0x8000_0000      # LDC constant blob   (chan 0)
SEQ_STREAM_BASE = 0x9000_0000    # the record list itself
# NO EMB row-size constant lives here any more: since R-b the row stride is
# the RUNTIME EMBLOG2 CSR (SEQ 0x60, docs/SEQ_ISA.md B13), programmed from
# the artifact manifest's "emb_row_bytes" (2*H).  sw/hwmap.py owns both
# (EMB_ROW_BYTES_DEFAULT = the CSR reset value, load_weights_manifest()).


# ======================================================================
# pack / unpack / disassemble / validate
# ======================================================================
class Rec(object):
    """One decoded 128-bit record."""

    __slots__ = ("opcode", "flags", "target", "imm32", "addr_lo",
                 "len_or_addr_hi")

    def __init__(self, opcode, flags=0, target=0, imm32=0, addr_lo=0,
                 len_or_addr_hi=0):
        self.opcode = int(opcode) & 0xFF
        self.flags = int(flags) & 0xFF
        self.target = int(target) & 0xFFFF
        self.imm32 = int(imm32) & 0xFFFFFFFF
        self.addr_lo = int(addr_lo) & 0xFFFFFFFF
        self.len_or_addr_hi = int(len_or_addr_hi) & 0xFFFFFFFF

    # -- derived views -------------------------------------------------
    @property
    def imm_s(self):
        """imm32 read as a signed 32-bit constant."""
        v = self.imm32
        return v - (1 << 32) if v >= (1 << 31) else v

    @property
    def ind(self):
        return self.flags & IND_MASK

    @property
    def xrf(self):
        if self.opcode == OP_MOVY:
            return (self.flags >> MOVY_XRF_SHIFT) & 0x7
        return (self.flags >> XRF_SHIFT) & 0xF

    @property
    def chan(self):
        if self.opcode == OP_MOVY:
            return self.target & 0xF
        return (self.flags >> CHAN_SHIFT) & 0xF

    @property
    def movy_mode(self):
        return MOVY_INT16 if (self.flags & MOVY_MODE_BIT) else MOVY_PAIRS32

    def to_bytes(self):
        return _STRUCT.pack(self.opcode | (self.flags << 8)
                            | (self.target << 16),
                            self.imm32, self.addr_lo, self.len_or_addr_hi)

    def __eq__(self, o):
        return isinstance(o, Rec) and self.to_bytes() == o.to_bytes()

    def __hash__(self):
        return hash(self.to_bytes())

    def __repr__(self):
        return f"<Rec {disasm(self)}>"


def pack(opcode, flags=0, target=0, imm32=0, addr_lo=0, len_or_addr_hi=0):
    """Build one 16-byte record (little-endian)."""
    return Rec(opcode, flags, target, imm32, addr_lo,
               len_or_addr_hi).to_bytes()


def unpack(buf, off=0):
    """Decode the record at byte offset `off` of `buf` -> Rec."""
    w0, imm32, addr_lo, hi = _STRUCT.unpack_from(buf, off)
    return Rec(w0 & 0xFF, (w0 >> 8) & 0xFF, (w0 >> 16) & 0xFFFF,
               imm32, addr_lo, hi)


def unpack_stream(buf):
    """Decode a whole record stream -> [Rec]."""
    assert len(buf) % REC_BYTES == 0, \
        f"stream is {len(buf)} B, not a multiple of {REC_BYTES}"
    return [unpack(buf, o) for o in range(0, len(buf), REC_BYTES)]


def pack_stream(recs):
    return b"".join(r.to_bytes() for r in recs)


# G3.4 (spec 5.4 S9): the matvec engine's group-count envelope, consumed
# from rtl/matvec_engine.sv's MAX_NG rather than re-invented.  It is the
# same number sw/hwmap.SHAPE_MAX_NG[2] enforces on the emit side; `ref/`
# does not import `sw/`, so the two are kept in step by
# evidence/qwen9b/g3/isa_bits.py.
MVGO_MAX_NG = 96
# ...and the SHAPE LAYOUT the bound is expressed in.  `ng` lives in
# bits [28:22] at isa=2 and in bits [5:0] at isa=1, so the envelope can
# only be checked once the caller has SAID which layout the stream is in
# -- exactly the discipline sw/hwmap.shape_word(isa=...) established at
# G3.3.  A frozen build_034/build_035 artifact is a legitimate isa=1
# stream, but SINCE SR11a (SEQ_ISA v2.3 B17.2) it validates ONLY when the
# caller states shape_isa = hwmap.SHAPE_ISA_PRE_G3: with the layout
# unstated, MVGO SHAPE bits 29/30 are refused (the R2 guard -- bit 29 is w8
# on build_034/035 but XBANK on build_041+, and only the stated layout
# tells them apart), so an isa=1 W8 stream (bit 29 = w8) is REFUSED.  The
# board callers (`sw/seq_run.py`, `sw/chat_seq.py`) therefore state the
# DEVICE's layout, hwmap.shape_isa_for_version(VERSION) -- every board
# admission has since SR11a fix round 2 (evidence/qwen9b/sr/SR11a_R2_MODEL.md
# §8), so the frozen 2B W8 board paths are admitted at isa=1.  A freshly
# emitted v2.0 stream -- the only kind THIS tree's RTL decodes -- gets the
# ng envelope check when SHAPE_ISA_9B is stated.  Twin of sw/hwmap.SHAPE_ISA_9B.
SHAPE_ISA_9B = 2

# SEQ_ISA v2.3 B17.2 (R2, the XWIN / RES bank bits; spec
# docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md §1.2).  The
# storage is the RTL's: x_mem = 96 lines x 32 words (MVGO_MAX_NG lines, one
# ng-unit of 128 int8 per line) = 3072 words = 12288 bytes per channel, and
# the RES BRAM = hwmap.RES_DEPTH (4096) rows.  A bank is half of each.
XWIN_LINE_WORDS = 32
XWIN_WORDS = MVGO_MAX_NG * XWIN_LINE_WORDS          # 3072
XBANK_LINE = MVGO_MAX_NG // 2                        # 48
XBANK_WORD = XBANK_LINE * XWIN_LINE_WORDS            # 1536
RES_ROWS = HW.RES_DEPTH                              # 4096
RBANK_ROW = RES_ROWS // 2                            # 2048
SHAPE_XBANK = 1 << 29        # MVGO SHAPE bit 29: x from line 48
SHAPE_RBANK = 1 << 30        # MVGO SHAPE bit 30: rows at 2048 + r
MOVX_WORD_MASK = 0x0FFF      # MOVX target[11:0] = XWIN start word


def movx_words(nbytes):
    """XWIN words a MOVX of `nbytes` int8 pushes (ceil; the ragged tail is
    zero-padded, SEQ_ISA B6 MOVX)."""
    return (int(nbytes) + 3) // 4


class SeqValidationError(ValueError):
    pass


def validate(r, nrec=None, idx=None, shape_isa=None, caps=frozenset()):
    """Reject anything the ISA does not define.  Raises SeqValidationError.

    `nrec` (stream length) enables the JMP target bound check.
    `shape_isa` (G3.4) enables the MVGO SHAPE envelope check, which can
    only be read once the SHAPE LAYOUT is known -- pass SHAPE_ISA_9B for a
    stream this tree's RTL will run, and hwmap.SHAPE_ISA_PRE_G3 for a
    frozen isa=1 artifact.  Since SR11a (B17.2) passing NOTHING for an
    isa=1 W8 artifact REFUSES it (SHAPE bit 29 is refused without R2 unless
    the isa=1 layout is stated); since SR11a fix round 2 the board callers
    state the device's layout (evidence/qwen9b/sr/SR11a_R2_MODEL.md §8).
    `caps` (SEQ_ISA v2.3 B17.0) is the capability set of the DEVICE the
    stream is for -- sw/hwmap.seq_caps_set() of its SEQ_CAPS word, never a
    manifest's claim.  The default (empty) is every pre-round bitstream and
    today's rules, so every existing caller is unchanged.  "R1" admits the
    FENCE channel mask (B17.1); "R2" admits the bank fields (B17.2: MOVX
    target[11:0], MVGO SHAPE bits 29/30, MOVY target[15:4]) under their
    range and bank-legality rules.  A name outside hwmap.SEQ_CAP_BITS raises
    ValueError (a caller bug, not a stream defect).  The constants are
    hwmap's -- this file defines none of its own.
    """
    caps = HW.seq_caps_check(caps)
    def bad(msg):
        where = "" if idx is None else f"rec {idx}: "
        raise SeqValidationError(f"{where}{msg}  [{_disasm_raw(r)}]")

    if r.opcode not in ALL_OPS:
        bad(f"unknown opcode {r.opcode:#04x}")
    ind = r.ind
    hi = r.flags >> 4

    if r.opcode in (OP_CSRWR, EXT_LDC):
        if ind not in IND_MODES:
            bad(f"unknown indirection code {ind:#x}")
        if ind == IND_NONE and hi:
            bad("XRF index set with no indirection mode")
        if hi >= XRF_N:
            bad(f"XRF index {hi} >= {XRF_N}")
    elif r.opcode == OP_CMD:
        if r.flags:
            bad("CMD takes no flags")
        if (r.target & 0xF000) != CSR_SPACE_LAYER:
            bad("CMD target must be a layer_chan csr_id")
    elif r.opcode in (OP_MOVX, OP_MVGO):
        # A1: flags[7:4] is the channel here, so indirection is forbidden
        if ind != IND_NONE:
            bad("MOVX/MVGO cannot use immediate indirection (flags[7:4] "
                "is the engine channel — SEQ_ISA A1)")
        if r.chan >= 4 and not _movx_bcast_admitted(r, caps, bad):
            bad(f"engine channel {r.chan} >= 4")
        # v1.4: MVGO target[0] is the NO-WAIT variant; the rest is reserved.
        if r.opcode == OP_MVGO and (r.target >> 1):
            bad("MVGO target[15:1] is reserved (only target[0] NO-WAIT)")
        if r.opcode == OP_MOVX:
            # SEQ_ISA v2.3 B17.2 (R2): target[11:0] = the XWIN start word,
            # admitted ONLY when the device has R2.  Without it the pre-round
            # rule stands (target reserved 0) -- build_041/042 IGNORE MOVX
            # target, so an R2 MOVX there would silently write word 0: R2 is
            # NOT fail-closed and this refusal is the guard.
            if "R2" not in caps:
                if r.target:
                    bad("MOVX target is reserved (must be 0; the XWIN start "
                        "word needs capability R2, B17.2)")
            else:
                if r.target & ~MOVX_WORD_MASK:
                    bad("MOVX target[15:12] is reserved (must be 0, B17.2)")
                w0 = r.target & MOVX_WORD_MASK
                nw = movx_words(r.len_or_addr_hi & 0xFFFFFF)
                if w0 >= XWIN_WORDS or w0 + nw > XWIN_WORDS:
                    bad(f"MOVX XWIN range: start word {w0} + {nw} words > "
                        f"{XWIN_WORDS} (B17.2, err 0x06)")
        if r.opcode == OP_MVGO and shape_isa != HW.SHAPE_ISA_PRE_G3:
            # SEQ_ISA v2.3 B17.2 (R2): SHAPE bit 29 = XBANK, bit 30 = RBANK,
            # bit 31 spare.  build_041/042 DROP bits 31:29
            # (rtl/matvec_chan.sv SHAPE write), so an XBANK MVGO there
            # computes on the wrong x without faulting -- refused unless the
            # device has R2.  Applied whenever the caller has NOT stated the
            # frozen isa=1 layout (where bit 29 is w8).  Since SR11a fix round
            # 2, sw/seq_run.py and sw/chat_seq.py state the DEVICE's layout at
            # every board admission (evidence/qwen9b/sr/SR11a_R2_MODEL.md §8):
            # isa=2 on build_041+, where this guard binds; isa=1 on the frozen
            # build_035, where an isa=1 W8 stream (bit 29 = w8) is admitted.
            sp = r.imm32 >> 29
            if sp & 0x4:
                bad("MVGO SHAPE bit 31 is spare (must be 0)")
            if sp and "R2" not in caps:
                bad("MVGO SHAPE bits 29/30 (XBANK/RBANK) need capability R2 "
                    "(B17.2); without it they are spare, must be 0")
            if sp & 0x1:
                ngx = (r.imm32 >> 22) & 0x7F
                if ngx > XBANK_LINE:
                    bad(f"MVGO XBANK with ng {ngx} (K = {128 * ngx}): a bank "
                        f"holds {XBANK_LINE} lines, K <= "
                        f"{128 * XBANK_LINE} (B17.2)")
            if sp & 0x2:
                nrx = (r.imm32 >> 6) & 0xFFFF
                if nrx > RBANK_ROW:
                    bad(f"MVGO RBANK with nrows {nrx}: a bank holds "
                        f"{RBANK_ROW} rows (B17.2)")
        # G3.4 (spec 5.4 S9): MVGO's imm32 IS the SHAPE word, and its `ng`
        # field is the only part of it whose out-of-envelope value the
        # ENGINE cannot report -- rtl/matvec_engine.sv's own 1..MAX_NG
        # guard is `ifndef SYNTHESIS.  The RTL twin is seq_unit's
        # validator, which refuses the record with err_code E_ENV before
        # the doorbell; this clause is the reference half of that pair and
        # the two MUST agree, which is what makes the RTL refusal safe to
        # add at all.  Layout: SEQ_ISA v2.0 / G3.3
        # {spare[31:29], ng[28:22], nrows[21:6], sh[5:0]}.
        # ONLY when the caller has stated the v2.0 layout -- see
        # SHAPE_ISA_9B above.  rtl/seq_unit.sv applies it unconditionally
        # because that RTL decodes v2.0 and nothing else.
        if r.opcode == OP_MVGO and shape_isa == SHAPE_ISA_9B:
            ng = (r.imm32 >> 22) & 0x7F
            if not (1 <= ng <= MVGO_MAX_NG):
                bad(f"MVGO SHAPE ng {ng} outside the engine envelope "
                    f"1..{MVGO_MAX_NG} (imm32={r.imm32:#010x}); "
                    f"rtl/matvec_engine.sv MAX_NG")
    elif r.opcode == OP_MOVY:
        if ind not in IND_MODES:
            bad(f"unknown indirection code {ind:#x}")
        if ind == IND_NONE and r.xrf:
            bad("XRF index set with no indirection mode")
        if r.chan >= 4:
            bad(f"engine channel {r.chan} >= 4")
        if "R2" not in caps:
            if r.target >> 4:
                bad("MOVY target[15:4] is reserved (must be 0; the RES "
                    "start row needs capability R2, B17.2)")
        else:
            # SEQ_ISA v2.3 B17.2 (R2): target[15:4] = the RES start row
            row0 = r.target >> 4
            nr = r.len_or_addr_hi & 0xFFFFFF
            if row0 + nr > RES_ROWS:
                bad(f"MOVY RES range: start row {row0} + {nr} rows > "
                    f"{RES_ROWS} (B17.2, err 0x06)")
    elif r.opcode == OP_EMB:
        if r.flags:
            bad("EMB takes no flags (token is implicitly XRF[3])")
    elif r.opcode == OP_AMAXL:
        if r.flags or r.target or r.imm32 or r.addr_lo or r.len_or_addr_hi:
            bad("AMAXL takes no operands")
    elif r.opcode == OP_JMP:
        if r.flags not in (0, JMP_TCNT):
            bad(f"JMP flags {r.flags:#04x} undefined (0 or {JMP_TCNT:#x})")
        # >= not >: the RTL faults E_JMP on target >= SEQ_LEN
        # (seq_unit.sv JMP bound check) — a target of exactly nrec used
        # to pass this validator and die on chip (SEQ_ISA v1.6 B11-1)
        if nrec is not None and r.imm32 >= nrec:
            bad(f"JMP target {r.imm32} outside a {nrec}-record stream")
    elif r.opcode == OP_FENCE:
        # SEQ_ISA v2.3 B17.1 (R1): target[3:0] is the channel mask (0 = all
        # four, today's meaning) -- admitted ONLY when the device has R1.
        # Without R1 the pre-round all-zero rule stands, as build_041/042's
        # RTL enforces it (err 0x06).
        tmask = 0xFFF0 if "R1" in caps else 0xFFFF
        if r.flags or (r.target & tmask) or r.imm32 or r.addr_lo \
                or r.len_or_addr_hi:
            bad("FENCE takes no operands" if "R1" not in caps else
                "FENCE takes only target[3:0] (the channel mask, B17.1)")
    elif r.opcode == OP_HALT:
        if r.flags or r.target or r.imm32 or r.addr_lo or r.len_or_addr_hi:
            bad("HALT takes no operands")
    elif r.opcode == EXT_XOP:
        if r.flags:
            bad("XOP takes no flags")
        if r.target >= XRF_N:
            bad(f"XOP XRF index {r.target} >= {XRF_N}")
        _a, s1, _b, s2, _si = xop_fields(r.imm32)
        if s1 == XOP_BAD or s2 == XOP_BAD:
            bad("XOP sign code 11 is a decode error (v1.4 ruling D-1)")
    return r


def validate_stream(recs, allow_ext=True, shape_isa=None, caps=frozenset()):
    """Validate every record; returns the count.  `allow_ext=False` rejects
    the PROPOSED opcodes so a pure-ISA-v1 stream can be certified.
    `shape_isa` and `caps` (the DEVICE's capability set, SEQ_ISA v2.3
    B17.0) are passed through to validate() -- see there.

    This is also where a LAYER COMMAND's ARG envelope is checked, because
    ARG0..2 arrive as CSRWR records AHEAD of the CMD -- validate() sees one
    record at a time and has no ARGs.
    """
    if isinstance(recs, (bytes, bytearray, memoryview)):
        recs = unpack_stream(recs)
    caps = HW.seq_caps_check(caps)
    n = len(recs)
    a0 = a1 = a2 = 0
    for idx, r in enumerate(recs):
        if not allow_ext and r.opcode in EXT_OPS:
            raise SeqValidationError(
                f"rec {idx}: {OP_NAME[r.opcode]} is a PROPOSED opcode, not "
                f"SEQ ISA v1")
        validate(r, nrec=n, idx=idx, shape_isa=shape_isa, caps=caps)
        if r.opcode == OP_CSRWR:
            if r.target == CSR_L_ARG0:
                a0 = r.imm32
            elif r.target == CSR_L_ARG1:
                a1 = r.imm32
            elif r.target == CSR_L_ARG2:
                a2 = r.imm32
            continue
        if r.opcode != OP_CMD:
            continue
        op = r.imm32 & 0xFF
        # v2.1 (B15.1): the SLD/SST field envelope.  UNCONDITIONAL, unlike
        # the MVGO SHAPE clause above -- v2.1 streams are the only kind this
        # tree's RTL decodes, and the frozen isa=1 artifacts carry no op
        # 13/14 at all, so there is no generation to gate on.
        if op in (OP_L_SLD, OP_L_SST):
            kind, _slot, layer, head = sdma_fields(a0)
            name = "SLD" if op == OP_L_SLD else "SST"
            if kind == 3:
                raise SeqValidationError(f"rec {idx}: {name} kind 3 is reserved (B15.1)")
            lmax = 7 if kind == SDMA_KIND_KV else 23
            hmax = {SDMA_KIND_DN: 0, SDMA_KIND_KV: 7, SDMA_KIND_CV: 0}[kind]
            if layer > lmax or head > hmax:
                raise SeqValidationError(
                    f"rec {idx}: {name} layer {layer}/head {head} outside kind {kind}'s range (B15.1)")
            if a1 != 0 or a2 != 0:
                raise SeqValidationError(f"rec {idx}: {name} arg1/arg2 must be 0 (B15.1 reserved)")
    return _bcast_running(recs, n, shape_isa, caps)


def resolve_imm(r, xrf):
    """The post-indirection immediate of `r` given the XRF file."""
    v = r.imm_s
    ind = r.ind
    if ind == IND_NONE:
        return v
    x = int(xrf[r.xrf])
    if ind == IND_ADD:
        return v + x
    if ind == IND_SUB:
        return v - x
    raise SeqValidationError(f"unknown indirection code {ind:#x}")


# ---------------------------------------------------------------- disasm
def _csr_name(cid):
    sp = cid & 0xF000
    off = cid & 0xFF
    if sp == CSR_SPACE_LAYER:
        return {0x00: "L_CMD", 0x08: "L_ARG0", 0x0C: "L_ARG1",
                0x10: "L_ARG2", 0x14: "L_SPTR", 0x18: "L_SWIN",
                0x20: "L_TCNT", 0x30: "L_LAYER",
                0x5C: "L_DNSB", 0x60: "L_TCNT2",
                0x64: "L_SB_DN", 0x68: "L_SB_KV", 0x6C: "L_SB_CV",
                0x70: "L_SDMA", 0x74: "L_SDMA_CYC",
                }.get(off, f"L+{off:#04x}")
    if sp == CSR_SPACE_MV:
        c = (cid >> 8) & 0xF
        return {0x08: "WBASE_LO", 0x0C: "WBASE_HI", 0x10: "WBEATS",
                0x14: "SHAPE", 0x00: "CTRL", 0x24: "XWIN",
                0x28: "XPTR"}.get(off, f"+{off:#04x}") + f"@mv{c}"
    if sp == CSR_SPACE_SEQ:
        if off >= SOFF_XRF0:
            return f"XRF[{(off - SOFF_XRF0) // 4}]"
        return {SOFF_TCNT_SEQ: "TCNT_SEQ"}.get(off, f"SEQ+{off:#04x}")
    return f"csr{cid:#06x}"


def _ind_str(r):
    if r.ind == IND_NONE:
        return ""
    nm = XRF_NAME.get(r.xrf, str(r.xrf))
    return f" {'+' if r.ind == IND_ADD else '-'}XRF[{r.xrf}:{nm}]"


def _disasm_raw(r):
    return (f"op={r.opcode:#04x} fl={r.flags:#04x} tgt={r.target:#06x} "
            f"imm={r.imm32:#010x} lo={r.addr_lo:#010x} hi={r.len_or_addr_hi:#010x}")


# layer_chan opcode names (hwmap) + vec_alu sub-op names, for CMD disasm
LOP_NAME = {1: "VN", 2: "VNW", 3: "ROPET", 4: "ROPE", 5: "CONVW", 6: "CONV",
            7: "GATE", 8: "DNST", 9: "KVAP", 10: "ATTN", 11: "ALU", 12: "DNZ",
            13: "SLD", 14: "SST"}                 # v2.1 (B15.1)
SDMA_KIND_NAME = {SDMA_KIND_DN: "DN", SDMA_KIND_KV: "KV", SDMA_KIND_CV: "CV",
                  3: "RSVD"}
ALU_NAME = {0: "DYNQ8", 1: "SHIFT32", 2: "SCALE", 3: "EMUL", 4: "ADD",
            5: "SILU16", 6: "SILU32", 7: "SIGM16", 8: "EMUL32",
            9: "SHIFT32W", 10: "AMAX32", 12: "DYNQ16"}
ALU_DYNQ16 = 12
ALU_EMUL32 = 8
# vec_alu op-8 PROBE (ISA v1.3, rtl/vec_alu.sv:39-53): cfg_p0[6] selects
# probe mode and is MASKED OUT of the shift decode, so cfg_p0 in [64,127]
# means "probe, shift p0-64".  The probe latches the FINISHED k_a
# (attn_o_shift semantics, clamp at 0) into XRF[2] and leaves the raw
# max|prod| on the MAXPL/MAXPH CSRs.
ALU_PROBE_BIT = 0x40
ALU_PROBE_SHIFT_MASK = 0x3F
VN_EPSNORM_MODE = 2              # with ARG2[0]=1 (A4)
VN_ARG2_EPS = 0x1
VN_ARG2_XRF_SHIFT = 1


def disasm(r, idx=None, ctx=None):
    """One human-readable line.  `ctx` (a dict) may carry the last ARG0..2
    seen so a CMD can be decoded into its layer_chan operation."""
    pre = "" if idx is None else f"{idx:7d}  "
    name = OP_NAME.get(r.opcode, f"OP{r.opcode:#04x}")
    o = r.opcode
    if o == OP_CSRWR:
        return (f"{pre}{name:<6} {_csr_name(r.target):<12} <= "
                f"{r.imm32:#010x}{_ind_str(r)}")
    if o == OP_CMD:
        lop = r.imm32 & 0xFF
        txt = f"{pre}{name:<6} {LOP_NAME.get(lop, str(lop))}"
        if ctx is not None and lop == 11:
            a0 = ctx.get("arg0", 0)
            sub, n = a0 & 0xF, dec_alu_len(a0)
            a1, a2 = ctx.get("arg1", 0), ctx.get("arg2", 0)
            p0 = dec_alu_p0(a0, a2)
            p0 = p0 - (1 << 17) if p0 >= (1 << 16) else p0
            txt += (f" {ALU_NAME.get(sub, sub)} n={n} p0={p0} "
                    f"srca={dec_a1_lo(a1):#x} srcb={dec_a1_hi(a1):#x} "
                    f"dst={dec_alu_dst(a2):#x}")
        elif ctx is not None and lop == 1:
            a0, a1 = ctx.get("arg0", 0), ctx.get("arg1", 0)
            a2 = ctx.get("arg2", 0)
            mode = a0 & 0x3
            if mode == VN_EPSNORM_MODE and (a2 & VN_ARG2_EPS):
                mode = "EPSNORM"
            txt += (f" mode={mode} n={1 << ((a0 >> 2) & 0xF)} "
                    f"inf={(a0 >> 6) & 0xF} outf={(a0 >> 10) & 0xF} "
                    f"src={dec_a1_lo(a1):#x} dst={dec_a1_hi(a1):#x}")
        elif ctx is not None and lop in (OP_L_SLD, OP_L_SST):
            # v2.1 (B15.1): "SLD k=DN slot=0 L=3", head only where it means
            # something (DN and CV must carry 0).
            kind, slot, layer, head = sdma_fields(ctx.get("arg0", 0))
            txt += (f" k={SDMA_KIND_NAME.get(kind, kind)} slot={slot} "
                    f"L={layer}")
            if kind == SDMA_KIND_KV:
                txt += f" kvhead={head >> 1} kv={'V' if head & 1 else 'K'}"
        return txt
    if o == OP_MOVX:
        return (f"{pre}{name:<6} {_movx_dst(r)} XWIN <= scratch[{r.addr_lo:#x} "
                f".. +{r.len_or_addr_hi}] int8")
    if o == OP_MOVY:
        mode = "int16" if r.movy_mode == MOVY_INT16 else "pairs32"
        return (f"{pre}{name:<6} mv{r.chan} RES[0..{r.len_or_addr_hi}) >> "
                f"{r.imm_s}{_ind_str(r)} -> scratch[{r.addr_lo:#x}] {mode}")
    if o == OP_MVGO:
        beats = r.len_or_addr_hi >> 8
        wb = ((r.len_or_addr_hi & 0xFF) << 32) | r.addr_lo
        sh = r.imm32
        # G3.3 SHAPE (isa=2): {spare[31:29], ng[28:22], nrows[21:6], sh[5:0]}.
        # ONE layout, because this tree emits one -- a pre-G3 stream's
        # isa=1 word needs a pre-G3 checkout to disassemble, exactly as its
        # v1.7 ARG encoding does (sw/hwmap.py's R_SHAPE block).
        return (f"{pre}{name:<6} mv{r.chan} WBASE={wb:#012x} BEATS={beats} "
                f"SHAPE={sh:#010x} (ng={(sh >> 22) & 0x7F} "
                f"nrows={(sh >> 6) & 0xFFFF} sh={sh & 0x3F})"
                + ("  [no-wait]" if r.target & MVGO_NOWAIT else ""))
    if o == OP_EMB:
        base = (r.target << 32) | r.imm32
        return (f"{pre}{name:<6} DDR[{base:#x} + XRF[3]<<EMBLOG2] -> "
                f"scratch[{r.addr_lo:#x}] {r.len_or_addr_hi} words")
    if o == OP_AMAXL:
        return f"{pre}{name:<6} AMAXI -> XRF[3], push OUT_FIFO"
    if o == OP_JMP:
        return (f"{pre}{name:<6} -> {r.imm32}"
                + ("   [dec TCNT_SEQ, jump if != 0]" if r.flags & JMP_TCNT
                   else ""))
    if o == OP_FENCE and r.target:
        # SEQ_ISA v2.3 B17.1: a non-zero target[3:0] is the channel mask
        return f"{pre}{name} mask={r.target:#x}"
    if o in (OP_FENCE, OP_HALT):
        return f"{pre}{name}"
    if o == EXT_LDC:
        a = (r.len_or_addr_hi << 32) | r.addr_lo
        return (f"{pre}{name:<6} DDR[{a:#x}{_ind_str(r)}] -> "
                f"scratch[{r.target:#x}] {r.imm32} words")
    if o == EXT_XOP:
        a, s1, b, s2, simm = xop_fields(r.imm32)
        terms = []
        if s1 != XOP_ZERO:
            terms.append(f"{XOP_SGN_NAME[s1]}XRF[{a}:{XRF_NAME.get(a, '')}]")
        if s2 != XOP_ZERO:
            terms.append(f"{XOP_SGN_NAME[s2]}XRF[{b}:{XRF_NAME.get(b, '')}]")
        terms.append(f"{simm:+d}")
        return (f"{pre}{name:<6} XRF[{r.target}:"
                f"{XRF_NAME.get(r.target, '')}] = " + " ".join(terms))
    return f"{pre}{_disasm_raw(r)}"


def disasm_stream(recs, out=None, limit=None):
    """Disassemble a stream (bytes or [Rec]) -> text."""
    if isinstance(recs, (bytes, bytearray, memoryview)):
        recs = unpack_stream(recs)
    lines, ctx = [], {}
    for i, r in enumerate(recs):
        if limit is not None and i >= limit:
            lines.append(f"... {len(recs) - limit} more records")
            break
        lines.append(disasm(r, i, ctx))
        if r.opcode == OP_CSRWR:
            if r.target == CSR_L_ARG0:
                ctx["arg0"] = r.imm32
            elif r.target == CSR_L_ARG1:
                ctx["arg1"] = r.imm32
            elif r.target == CSR_L_ARG2:
                ctx["arg2"] = r.imm32
    txt = "\n".join(lines)
    if out is not None:
        out.write(txt + "\n")
    return txt


def ldc_as_csrwr_cost(recs):
    """How many records the ISA-v1-only fallback for LDC (A9) would need:
    CSRWR(SPTR) + n*CSRWR(SWIN) per constant load."""
    n = 0
    for r in recs:
        if r.opcode == EXT_LDC:
            n += 1 + r.imm32
    return n


# ======================================================================
# new compute-op reference semantics  (Agent A owns these; shim if absent)
# ======================================================================
def _import_agent_a():
    """Prefer layer_fixed's dynq16_fx/eps_norm_* when Agent A has landed.

    RECONCILED 2026-08-08 against the landed layer_fixed:
      dynq16_fx(x32_block, clamp0=False)          -> (y16, k)      == shim
      eps_norm_scale(x16, k, in_f, out_f, note)   -> int m_q15
      eps_norm_fx(x16, k, in_f, out_f, note)      -> y16   (NOT a tuple)
    Agent A's eps-norm supersedes this module's A5 reading: `k` enters the
    hardware ONLY through the shift of the integer eps addend, and the rsqrt
    exponent absorbs the 2^k the output would otherwise need.  The fallback
    below is the pre-reconciliation float form and is kept only so this
    module still imports against an older layer_fixed.
    """
    try:
        import layer_fixed as _LF
    except Exception:
        return None, None, None, "layer_fixed not importable"
    d = getattr(_LF, "dynq16_fx", None)
    e = getattr(_LF, "eps_norm_fx", None)
    s = getattr(_LF, "eps_norm_scale", None)
    if d is not None and e is not None and s is not None:
        return d, e, s, "layer_fixed (agent A)"
    miss = [n for n, f in (("dynq16_fx", d), ("eps_norm_fx", e),
                           ("eps_norm_scale", s)) if f is None]
    return d, e, s, ("seq_format fallback (layer_fixed missing "
                     + ",".join(miss) + ")")


def _shim_dynq16_fx(x32, clamp0=False, guard=None):
    """vec_alu op 12 DYNQ16 (SEQ_ISA "New compute ops").

        k   = bf_shift(max|x32|, guard)       [+1 fixup, guard, 0 -> 0]
        out = clip16(rshr64s(x32, k))         (the clip is inert by
                                               construction of bf_shift)
    `clamp0` = cfg_p0[1]: clamp k at 0, the attn/op-8 semantics.
    Returns (out_int16, k).  Bit-identical to layer_fixed.dn_o_shift +
    vec_alu op 1 (verified in seq_model._selftest_ops).
    """
    import layer_fixed as _LF
    x = np.asarray(x32, dtype=np.int64)
    g = _LF.BF_GUARD if guard is None else int(guard)
    k = _LF.bf_shift(int(np.abs(x).max()) if x.size else 0, g)
    if clamp0 and k < 0:
        k = 0
    y = _LF.rshr(x, k) if k >= 0 else (x << (-k))
    return _LF.clip16(y).astype(np.int64), int(k)


def _shim_eps_norm_scale(x16, k, in_f=None, out_f=None, note=True):
    """Pre-reconciliation float form; see _import_agent_a."""
    return _shim_eps_norm_fx(x16, k, in_f, out_f)[1]


def _shim_eps_norm_fx(x16, k, in_f=None, out_f=None, eps=None):
    """vecnorm mode 2 + ARG2[0] EPS-NORM (SEQ_ISA "New compute ops", see A5).

        ss    = sum(x16^2)                       exact integer, n int16 in
        mean  = ss / (n * 2^(2*(in_f - k)))      k from XRF (cfg field)
        s     = 1 / sqrt(mean + eps)
        scale = round(s * 2^(out_f - in_f + k) * 2^15)      <- A5: +k
        out   = clip16(rshr(x16 * scale, 15))

    Returns (out_int16, scale).  `scale` is clipped into the vec_alu cfg_p0
    positive range (layer_fixed.M_Q15_MAX) exactly like dn_norm_scale, so
    the two paths differ only in whether ss is summed over the int32 head
    output or over its DYNQ16 int16 image (quantified by seq_model).
    """
    import layer_fixed as _LF
    import layer_ref as _LR
    in_f = _LF.S_F if in_f is None else int(in_f)
    out_f = _LF.DN_NORM_F if out_f is None else int(out_f)
    eps = _LR.EPS if eps is None else float(eps)
    x = np.asarray(x16, dtype=np.int64)
    ss = int((x * x).sum())
    mean = ss / float(1 << (2 * (in_f - int(k)))) / float(len(x))
    s = 1.0 / np.sqrt(mean + eps)
    scale = int(np.clip(round(s * (2.0 ** (out_f - in_f + int(k))) *
                              (2.0 ** 15)), 0, _LF.M_Q15_MAX))
    return _LF.clip16(_LF.rshr(x * scale, 15)).astype(np.int64), scale


dynq16_fx, eps_norm_fx, eps_norm_scale, NEWOPS_SOURCE = _import_agent_a()
if dynq16_fx is None:
    dynq16_fx = _shim_dynq16_fx
if eps_norm_fx is None:
    def eps_norm_fx(x16, k, in_f=None, out_f=None, note=True):
        return _shim_eps_norm_fx(x16, k, in_f, out_f)[0]
if eps_norm_scale is None:
    eps_norm_scale = _shim_eps_norm_scale


# ======================================================================
# emitter
# ======================================================================
class _Blob(object):
    """Content-addressed constant pool -> <prefix>.seqdata.bin (A9)."""

    def __init__(self, base=SEQ_DATA_BASE):
        self.base = base
        self.chunks = []          # [(off, bytes)]
        self.index = {}           # sha256 -> off
        self.size = 0

    def add(self, vals16):
        b = np.asarray(vals16, dtype=np.int64).astype("<i2").tobytes()
        h = hashlib.sha256(b).digest()
        off = self.index.get(h)
        if off is None:
            off = self.size
            self.index[h] = off
            self.chunks.append((off, b))
            self.size += len(b)
            # 64B align so an LDC burst never straddles a partial beat
            pad = -self.size % 64
            if pad:
                self.chunks.append((self.size, b"\x00" * pad))
                self.size += pad
        return off

    def add_at(self, vals16):
        """Like add() but NEVER dedupes — used for position-indexed tables
        that must be contiguous and strided (A10)."""
        b = np.asarray(vals16, dtype=np.int64).astype("<i2").tobytes()
        off = self.size
        self.chunks.append((off, b))
        self.size += len(b)
        pad = -self.size % 64
        if pad:
            self.chunks.append((self.size, b"\x00" * pad))
            self.size += pad
        return off

    def to_bytes(self):
        buf = bytearray(self.size)
        for off, b in self.chunks:
            buf[off:off + len(b)] = b
        return bytes(buf)


def _runs(mask):
    """[(start, stop)] runs of True in a boolean array."""
    m = np.asarray(mask)
    d = np.diff(np.concatenate([[False], m, [False]]).astype(np.int8))
    return list(zip(np.nonzero(d == 1)[0].tolist(),
                    np.nonzero(d == -1)[0].tolist()))


def plan_weights_from_wids(wids, base=None, nch=1, repack=False,
                           layout_of=None, chunk_rows=None):
    """The sw/hwmap.py plan_weights() layout, computed from the generator's
    live `Mach.wids` instead of from files on disk.  The ADDRESSES come from
    `hwmap.plan_weights` itself (R-c: one authority) — this function only
    turns live quantized matrices into the manifest shape it wants.

    Returns {wid: {"base","nrows","k","ng","sh","g","stride","nbeats"}},
    plus `"w8": True` on an 8-bit image (V5).  The W8 key is EMITTED ONLY
    WHEN SET, exactly as `dump_weights` emits "g" only when it is not 128,
    so every W4 plan — and therefore every committed .seq.json — stays
    byte-identical.  Readers use `bool(p.get("w8", False))`; `ng` is the
    ng-UNIT count K//128 in both widths, only `stride` moves
    (`row_stride8` = K//64 weight beats + the SAME scale beats).

    REPACK (R-c, the V5 fit prerequisite).  `repack=False` is the pack every
    frozen artifact encodes: nch-INDEPENDENT, one full-image span per wid,
    `"base"` an int.  With `repack=True` each channel packs only the rows it
    owns, `"base"` is a LIST of nch channel-local addresses, and `layout_of`
    ({wid: LAYOUT_*}) says how each image was split — the row counts differ
    between LAYOUT_CONTIG (split_rows) and LAYOUT_ILV (chunk interleave), so
    the layout must be known before an image can be placed.
    """
    from w4a8_ref import row_stride, row_stride8
    assert base is None or base == HW.W_BASE, \
        f"plan_weights_from_wids base {base:#x} != hwmap.W_BASE"
    depth = CHUNK_ROWS if chunk_rows is None else int(chunk_rows)
    lay = dict(layout_of or {})
    man = {}
    for wid, qw in sorted(wids.values(), key=lambda t: t[0]):
        w8 = "w8" in qw
        nrows, K = qw["w8" if w8 else "w4"].shape
        g = int(qw.get("g", 128))
        stride = row_stride8(K, g) if w8 else row_stride(K, g)
        man[wid] = {"nrows": int(nrows), "k": int(K), "ng": K // 128,
                    "sh": int(qw["sh"]), "g": g, "stride": stride,
                    "nbeats": nrows * stride // 64, "w8": w8}
    rows_of = None
    if repack:
        assert nch > 1, "the per-channel repack needs nch > 1"

        def rows_of(wid, nrows):
            assert wid in lay, (
                f"wid {wid} is placed before its layout is known — the "
                "repack cannot size a channel's slice without it")
            return chan_rows(nrows, nch, lay[wid], depth)

    bases, _top = HW.plan_weights(man, wdir=None, nch=nch, rows_of=rows_of)
    out = {}
    for wid, m in sorted(man.items()):
        b = bases[wid]
        out[wid] = {"base": list(b) if repack else b,
                    "nrows": m["nrows"], "k": m["k"], "ng": m["ng"],
                    "sh": m["sh"], "g": m["g"], "stride": m["stride"],
                    "nbeats": m["nbeats"]}
        if m["w8"]:
            out[wid]["w8"] = True
    return out


def split_rows(nrows, nch):
    """Contiguous row split of a matvec image across nch channels — EXACTLY
    sw/tok_meter.py:split_rows.  The first (nrows % nch) channels take one
    extra row; zero-count entries (nrows < nch) are legal and dropped by the
    caller.  Returns [(row0, count)] * nch."""
    base, rem = divmod(nrows, nch)
    out, r = [], 0
    for c in range(nch):
        n = base + (1 if c < rem else 0)
        out.append((r, n))
        r += n
    assert r == nrows
    return out


def res_chunks(r0, n, depth):
    """Cut a channel's row range into <=depth engine runs — sw/tok_meter.py."""
    out = []
    while n > 0:
        rc = min(depth, n)
        out.append((r0, rc))
        r0 += rc
        n -= rc
    return out


# ----------------------------------------------------------------------
# rung 4 S4: weight-image placement layouts
#
# A multi-channel stream implies a PLACEMENT: which rows of a packed weight
# image the host must DMA into which DDR channel, at which channel-local
# byte offset.  The emitter chooses it, the host (sw/seq_run.py upload,
# sw/chat_seq.py residency) replays it, and `weight_pieces` below is the
# single pure function both sides call so they cannot drift.
#
#   LAYOUT_CONTIG  rung 1b: split_rows(nrows, nch) — channel i owns one
#                  contiguous row-quarter.  Used by every non-AMAX matvec,
#                  where the nch engines run the SAME chunk index
#                  concurrently and row writes are independent.
#   LAYOUT_ILV     rung 4 S4: global chunk j -> channel j % nch.  The LM
#                  head's AMAX32 scan carries a RUNNING row index, so the
#                  AMAX32 commands must retire in ascending GLOBAL row
#                  order; interleaving the chunks lets nch engines prefetch
#                  concurrently while the drain order stays global-ascending
#                  (contiguous quarters cannot: channel 1's first chunk is
#                  row 62,080, which may not be scanned before channel 0's
#                  last).
# ----------------------------------------------------------------------
LAYOUT_CONTIG = "contig"
LAYOUT_ILV = "ilv"
LAYOUTS = (LAYOUT_CONTIG, LAYOUT_ILV)

# STG staging (ALU sub 6/10) holds a 2048-row int32-pair chunk (4096 words) —
# exactly the .txt's inject_dequant chunk size.  The fused sub 1/9 path writes
# straight to dst so it is only bounded by RES_DEPTH, but capping it at the
# same 2048 keeps every MOVY at a proven size (no untested >2048-row RES read
# in the full-chip gate).
CHUNK_ROWS = 2048


def ilv_chunks(nrows, nch, depth=CHUNK_ROWS):
    """The S4 interleave: [(chan_index, r0, nrows)] in ASCENDING row order.

    Chunk j of the GLOBAL res_chunks cut goes to channel j % nch.  Ascending
    order is the AMAX32 retire order; grouping the list nch at a time gives
    the MVGO-all-no-wait / one-FENCE / MOVY-per-chan groups (S4).
    """
    return [(j % nch, r0, n)
            for j, (r0, n) in enumerate(res_chunks(0, nrows, depth))]


def weight_pieces(nrows, nch, layout=LAYOUT_CONTIG, depth=CHUNK_ROWS):
    """[(chan_index, r0, nrows_piece)] — the placement `layout` implies.

    `chan_index` indexes the emitter's channel list (0..nch-1), NOT a DDR
    address: every piece lands at the channel-local byte offset
    `wbase + r0 * stride`, exactly where that channel's MVGO WBASE points.
    Zero-row channels are dropped (nrows < nch).  nch == 1 returns the whole
    image on channel 0 under either layout, so the single-channel host path
    is untouched.
    """
    if layout not in LAYOUTS:
        raise ValueError(f"unknown weight layout {layout!r}")
    if nch <= 1 or layout == LAYOUT_CONTIG:
        return [(i, r0, n) for i, (r0, n) in enumerate(split_rows(nrows, nch))
                if n > 0]
    return ilv_chunks(nrows, nch, depth)


def weight_pieces_at(nrows, nch, layout=LAYOUT_CONTIG, depth=CHUNK_ROWS,
                     repack=False):
    """[(chan_index, r0, nrows_piece, row_off)] — `weight_pieces` plus the
    row index of each piece INSIDE THAT CHANNEL's copy of the image (R-c).

    `row_off` is what the channel-local address is built from:
    `chan_base + row_off * stride`.

      * repack=False (every artifact frozen before R-c): each channel
        reserves the WHOLE image, so a piece sits at its GLOBAL row —
        `row_off == r0`, and this is exactly `weight_pieces` with the third
        field repeated.  Nothing moves.
      * repack=True: a channel packs only the rows it owns, back to back in
        ASCENDING piece order, so `row_off` is the running per-channel row
        count.  Under LAYOUT_CONTIG that is `r0 - split_rows()[i][0]`; under
        LAYOUT_ILV the channel's rows are strided through the image and the
        packed order is the interleave order.
    """
    out, seen = [], [0] * max(1, nch)
    for (i, r0, n) in weight_pieces(nrows, nch, layout, depth):
        out.append((i, r0, n, seen[i] if repack else r0))
        seen[i] += n
    return out


def chan_rows(nrows, nch, layout=LAYOUT_CONTIG, depth=CHUNK_ROWS):
    """[rows channel i holds] under `layout` — `hwmap.plan_weights`' rows_of.

    Sums to nrows by construction (weight_pieces partitions the image), and
    it is LAYOUT DEPENDENT: at nrows=248,320 / nch=4 the contiguous split
    gives 62,080 rows to every channel while the 2048-row interleave gives
    63,488 / 61,952 / 61,440 / 61,440 — which is why an image cannot be
    placed by the repack before its layout is pinned.
    """
    out = [0] * nch
    for (i, _r0, n) in weight_pieces(nrows, nch, layout, depth):
        out[i] += n
    assert sum(out) == nrows
    return out


class SeqEmitter(object):
    """Opt-in observer of gen_layer_script.Mach.  Emits the SEQ stream.

    Attach with `M.seq = SeqEmitter(M, prefix)` — Mach.__init__ does that
    automatically when SEQ_EMIT is set in the environment.  Every hook is
    a no-op when the emitter is absent, so default generator output is
    byte-identical (proved by the regen hashes in the gate log).

    profile:
      "xlat"    (default) transcription of today's schedule.  The DN gated
                norm uses DYNQ16 (proven identical to op1 + the dn_o_shift
                immediate) then the SCALE op with the generator-computed
                m_q15, so the DN block-float immediate is still a literal
                and a DeltaNet body cannot loop.
      "epsnorm" additionally replaces that SCALE with the EPS-NORM vecnorm
                mode, i.e. the full ISA "new compute ops" datapath.  Agent
                A's landed layer_fixed makes this bit-identical to the SCALE
                path (seq_model --selftest: 200/200 blocks, 0 LSB).

    dyn_ka (independent of the profile, default ON) additionally restructures
    the gated-attention block into the ISA v1.3 op-8 probe double pass, which
    removes the LAST data-dependent immediate.  epsnorm + dyn_ka is the only
    combination in which a stack containing full_attention layers can close
    its decode loop.
    """

    PROFILES = ("xlat", "epsnorm")

    def __init__(self, mach, prefix, profile="xlat", chan=0, loop=True,
                 dyn_ka=True, nowait_mvgo=False, nch=1, repack=False):
        assert profile in self.PROFILES, f"unknown SEQ profile {profile!r}"
        self.M = mach
        self.prefix = prefix
        self.profile = profile
        self.chan = int(chan)
        self.want_loop = bool(loop)
        # nch: number of matvec_chans the emitter row-splits every matvec
        # across (rung 1b).  nch==1 is the byte-identical legacy path (the
        # emitter passively mirrors the .txt W32/ALU chunk boundaries through
        # _fuse); nch>1 takes over the row partition itself (split_rows +
        # res_chunks per channel, exactly like sw/tok_meter.py --four-chan)
        # and drives channels 0..nch-1 with no-wait MVGO + one FENCE per
        # chunk-group.  WBASE stays CHANNEL-LOCAL (base+row*stride, NO
        # c*CH_STRIDE) — the host upload places each channel's row-quarter at
        # the same channel-local address, so seq_0/m_axi sees its channel at 0.
        self.nch = max(1, int(nch))
        # the last LAYER word the program selected, so `on_treset` can put
        # it back after its eight-layer sweep (SEQ_ISA v2.1 A1.3)
        self.layer_word_q = 0
        self.chans = list(range(self.nch)) if self.nch > 1 else [self.chan]
        # repack (R-c, SEQ_REPACK=1): PER-CHANNEL weight packing.  OFF by
        # default, and that default is the frozen behaviour — with it off the
        # pack is nch-independent (every channel reserves the whole image,
        # MVGO WBASE = base + GLOBAL row * stride), which is what every
        # artifact frozen before R-c encodes at nch=1 AND at nch=4.  With it
        # on, each channel packs only the rows it owns, so its cursor
        # advances by a quarter of the bytes and the V5 W8 pack (1.85 GiB
        # whole, ~465 MiB on the busiest channel) fits the 1,280 MiB window
        # — see evidence/qwen2b/q2/v4_v5/V4_V5.md §5.  It needs nch>1: there
        # is nothing to repack across one channel.
        self.repack = bool(repack)
        assert not (self.repack and self.nch < 2), \
            "SEQ_REPACK needs SEQ_NCH>1 (a 1-chan pack has no channels to " \
            "repack across)"
        # The repack indexes per-channel bases by the emitter's channel INDEX,
        # and _mvgo_at is handed the DDR channel number; they coincide for
        # every nch>1 stream (chans == range(nch)) and this pins that.
        assert not self.repack or self.chans == list(range(self.nch))
        # dyn_ka: emit the ISA v1.3 attention DOUBLE PASS (op-8 probe -> k_a
        # in XRF[2], real pass with ARG2 indirected on XRF[2], and the
        # o_proj requant shift folded by XOP into XRF[5]) instead of baking
        # the generator-computed k_a in as a constant immediate.  This is
        # what removes the LAST data-dependent immediate from the decode
        # loop body (SEQ_ISA A3), so stacks containing full_attention layers
        # can close.  SEQ_DYNKA=0 restores the v1.2 constant-k_a emission.
        self.dyn_ka = bool(dyn_ka)
        # nowait_mvgo: ISA v1.4 MVGO target[0].  OFF by default — a no-wait
        # MVGO is only sound when the consuming MOVY is fenced or lands on
        # a different channel, which needs the multi-channel scheduler that
        # is not part of this wave.  The flag exists so the encoding is
        # exercised end to end (emitter -> validator -> seq_model -> RTL).
        self.nowait_mvgo = bool(nowait_mvgo)
        self.recs = []
        self.blob = _Blob()
        # position-indexed constants (the RoPE tables) live in their OWN
        # pool, appended after the deduped one, so their offsets are exactly
        # strided by position and an XRF[4]-indexed load can address them.
        self.posblob = _Blob()
        self.wplan = None
        # rung 4 S4: wid -> LAYOUT_* the emitter's MVGO WBASEs imply.  Only
        # populated for nch>1 (a 1-chan stream has no placement choice), and
        # published in meta["weight_layout"] for the host uploader.
        self.wlayout = {}
        self.mv = None                # pending matvec
        self.pend = None              # pending W32 (engine RES chunk)
        self.dnbf = None              # pending DN block-float hint
        self.steps = []               # (first_rec_idx, token_in)
        self.expect_tokens = []       # tokens AMAXL should produce
        self.last_amax_tok = None
        self.notes = []
        self.stats = {"ldc_words": 0, "ldc_unique": 0, "movy_rows": 0,
                      "mvgo": 0, "movx": 0, "cmd": 0, "csrwr": 0,
                      "emb": 0, "amaxl": 0, "ldc": 0, "dynq16": 0,
                      "epsnorm": 0, "fused_movy": 0,
                      "attn_probe": 0, "xop": 0, "mvgo_nowait": 0,
                      "fence": 0}
        self.k_a_hist = {}
        self._step_ka = {}
        # attention double-pass state (dyn_ka)
        self.attn = None              # in-flight gated-attention block
        self.ka_pending = None        # k_a the NEXT fused MOVY must undo
        self.attn_blocks = 0          # gated-attention blocks restructured
        self.finished = False
        self.pos_hint = None          # set by attn_token before the RoPE W
        self._pos_recs = []           # [(rec_idx, blob_off, step_idx)]
        # LIVE-STATE CHECKPOINTS: every .txt R record (the generator's own
        # self-checks) becomes {rec_index: (addr, n)}.  seq_model samples
        # the SEQ scratch there and compares the whole sequence against the
        # .txt values, so the gate proves live equality THROUGHOUT the run,
        # not just at the end.
        self.cp_at = {}
        # STAGING WINDOWS: scratch the host W32 records used to relay matvec
        # y32.  The SEQ stream removes that relay, so these words legitimately
        # hold different leftovers at the end of the run; the gate requires
        # every final-state difference to lie INSIDE this set.
        self.staging = np.zeros(_GLS.SCRATCH, dtype=bool)

    # ------------------------------------------------------------ helpers
    def _emit(self, r):
        self.recs.append(r)
        return len(self.recs) - 1

    def _csrwr(self, csr, val, ind=IND_NONE, xrf=0):
        self.stats["csrwr"] += 1
        return self._emit(Rec(OP_CSRWR, flags=ind | (xrf << XRF_SHIFT),
                              target=csr, imm32=val))

    # rtl/vec_alu.sv `cfg_len` = ARG0[17:4], 14 bits (G3.1; 13 at R-c).
    # This emitter SYNTHESIZES ALU commands of its own — the attention
    # EMUL32 probe pair, the fused matvec dequant, the AMAX32 chunks,
    # DYNQ16 — none of which pass through `gen_layer_script.Mach.alu`, so
    # its assert does not cover them.  The check therefore lives at the ONE
    # choke point every layer command goes through, which also re-covers
    # the pass-through path.
    ALU_LEN_MAX = (1 << 14) - 1

    def _cmd(self, lop, a0, a1, a2, a2_ind=IND_NONE, a2_xrf=0):
        """Emit ARG0..2 + CMD.  `a2_ind`/`a2_xrf` put the ARG2 write under
        XRF indirection — the ALU cfg_p0's low 16 bits live in ARG2[15:0]
        (SEQ_ISA v2.0), so this is how a DATA-DEPENDENT shift (the attention
        k_a) reaches a command without appearing as a literal in the record
        stream.  An indirected ARG2 can therefore only carry a p0 whose bit
        16 is 0: the runtime add lands in ARG2 and CANNOT reach ARG0[18].
        Asserted below rather than assumed — under SEQ_ISA v1.7 the whole
        17-bit p0 lived in ARG2 and the question could not arise."""
        if lop == 11:
            n = dec_alu_len(a0)
            assert a2_ind == IND_NONE or ((a0 >> 18) & 1) == 0, (
                f"ALU ARG0={a0:#x} sets p0[16] (ARG0[18]) on a command whose "
                f"ARG2 is XRF-indirected.  SEQ_ISA v2.0 splits cfg_p0 across "
                f"ARG0[18] and ARG2[15:0]; the runtime add reaches only ARG2, "
                f"so the emitted p0[16] would survive into a shift the host "
                f"never intended.")
            assert 1 <= n <= self.ALU_LEN_MAX, (
                f"ALU record count {n} does not fit ARG0[17:4] (max "
                f"{self.ALU_LEN_MAX}); rtl/vec_alu.sv cfg_len is 14 bits. "
                f"ARG0={a0:#x}, sub-op {a0 & 0xF}. A record the RTL decodes "
                "differently is silent corruption — every python model would "
                "agree with this emitter and only the hardware would differ.")
        self._csrwr(CSR_L_ARG0, a0)
        self._csrwr(CSR_L_ARG1, a1)
        self._csrwr(CSR_L_ARG2, a2, ind=a2_ind, xrf=a2_xrf)
        self.stats["cmd"] += 1
        return self._emit(Rec(OP_CMD, target=CSR_L_CMD, imm32=lop))

    # ------------------------------------------------------------ hooks
    def on_layer(self, dn_slot, kv_slot, cv_slot=0, kv_layer=0):
        """SEQ_ISA v2.1 B15.2: the LAYER CSR carries CACHE SLOTS and the
        attention layer whose TCNT/TCNT2 pair the host addresses.

        While a gated-attention block is open the write is BUFFERED with
        the commands: `_emit_attn_block` replays the block in an order the
        LAYER writes have to travel with (spec 6.2 puts one per kvhead)."""
        w = layer_word(dn_slot, kv_slot, cv_slot, kv_layer)
        self.layer_word_q = w
        if self.attn is not None:
            self.attn["buf"].append(("layer", w))
            return
        self._csrwr(CSR_L_LAYER, w)

    def on_sbase(self, sb_dn, sb_kv, sb_cv):
        """SEQ_ISA v2.1 B15.3: the three state-region base CSRs, in 64 KiB
        units.  The program writes them so a replay is self-contained; the
        host writes the same values from the manifest (spec 7.2)."""
        assert self.attn is None, "SB_* write inside a gated-attention block"
        self._csrwr(CSR_L_SB_DN, int(sb_dn))
        self._csrwr(CSR_L_SB_KV, int(sb_kv))
        self._csrwr(CSR_L_SB_CV, int(sb_cv))

    def on_treset(self):
        """Zero EVERY KV append counter -- all eight attention layers.

        G3.4: TWO CSRWRs per layer, because at NKVH = 4 the four counters do
        not fit one 32-bit word (rtl/layer_chan.sv's TCNT at 0x20 carries
        kvheads 0/1 and TCNT2 at 0x60 carries 2/3).  Writing only TCNT
        would leave kvheads 2 and 3 holding whatever the previous sequence
        left there, and the reference model -- which zeroes all four --
        would not diverge until attention read a cache that was longer than
        it should be.  That is the silent divergence spec 4.6 wall 9 is
        about, so the two writes move together with the banking.

        S3 (spec A1.3): `tcnt_bank` is indexed by ATTENTION LAYER now, and
        the CSR pair addresses the layer LAYER.kv_layer names -- so a
        session reset is EIGHT LAYER writes and SIXTEEN counter writes, and
        this one hook emits all of them.  The LAYER CSR is restored to what
        the program had selected, because the next command reads it.
        """
        assert self.attn is None, "T reset inside a gated-attention block"
        keep = self.layer_word_q
        for a in range(_GLS._KV_LAYERS):
            self._csrwr(CSR_L_LAYER, layer_word(0, 0, 0, a))
            self._csrwr(CSR_L_TCNT, 0)
            self._csrwr(CSR_L_TCNT2, 0)
        self._csrwr(CSR_L_LAYER, keep)

    def on_dnsb(self, a_beta_base, a_dec_base):
        """SEQ_ISA v2.0: one CSRWR per layer BODY carrying the DeltaNet
        scalar-pointer base pair the DNST decode adds `head` to."""
        self._csrwr(CSR_L_DNSB,
                    ((a_dec_base & 0xFFFF) << 16) | (a_beta_base & 0xFFFF))

    def on_w(self, addr, vals):
        """A host W record -> LDC from the constant blob (A9).

        A POSITION-INDEXED constant (the RoPE table, flagged by
        `pos_hint`) goes into a NON-deduped strided region so `_try_loop`
        can rewrite its LDC to `addr_lo + XRF[4]` indirection (A10)."""
        n = len(vals)
        pos = self.pos_hint
        self.pos_hint = None
        self.stats["ldc"] += 1
        self.stats["ldc_words"] += n
        if pos is not None:
            off = self.posblob.add_at(vals)
            a = 0                       # patched by _fix_pos_addrs()
        else:
            off = self.blob.add(vals)
            a = self.blob.base + off
        i = self._emit(Rec(EXT_LDC, target=addr, imm32=n,
                           addr_lo=a & 0xFFFFFFFF, len_or_addr_hi=a >> 32))
        if pos is not None:
            self._pos_recs.append((i, off, max(0, len(self.steps) - 1)))

    def _fix_pos_addrs(self):
        """Resolve the position pool's absolute addresses (it is appended
        after the deduped pool, whose size is only final at the end)."""
        pb = self.blob.base + self.blob.size
        for (i, off, _s) in self._pos_recs:
            r = self.recs[i]
            a = pb + off
            self.recs[i] = Rec(EXT_LDC, target=r.target, imm32=r.imm32,
                               addr_lo=a & 0xFFFFFFFF, len_or_addr_hi=a >> 32)

    def on_w32(self, addr, vals32):
        """W32 only ever injects matvec y32 — mark the RES chunk."""
        assert self.mv is not None, \
            "W32 with no pending matvec: the SEQ emitter's fusion rule broke"
        c = self.mv["consumed"]
        y = self.mv["y32"]
        n = len(vals32)
        assert np.array_equal(np.asarray(vals32, dtype=np.int64),
                              y[c:c + n]), \
            "W32 payload is not the next slice of the pending matvec y32"
        self.pend = {"addr": addr, "n": n, "r0": c}
        self.staging[addr:addr + 2 * n] = True

    def on_r(self, addr, n):
        """A .txt R record: a live-state checkpoint for the SEQ replay."""
        self.cp_at[len(self.recs)] = (int(addr), int(n))

    def on_c(self, op, a0, a1, a2):
        """Every layer_chan command.  Fuses the matvec dequant into MOVY."""
        if self.attn is not None:
            self.attn["buf"].append(("cmd", op, a0, a1, a2))
            if op == 11 and (a0 & 0xF) == ALU_EMUL32:
                self.attn["n_em"] += 1
                if self.attn["n_em"] == self.attn["nq"]:
                    self._emit_attn_block()
            return
        if self.pend is not None:
            if self.nch > 1:
                self._buffer_matvec_chunk(op, a0, a1, a2)
            else:
                self._fuse(op, a0, a1, a2)
            return
        if self.dnbf is not None and op == 11:
            if self._dn_block_float(a0, a1, a2):
                return
        self._cmd(op, a0, a1, a2)

    def on_matvec(self, wid, qw, x8_addr, n_in, y32):
        # wids are assigned in first-use order and the DDR pack only ever
        # APPENDS, so extending the plan as matrices appear gives exactly the
        # layout sw/hwmap.py:plan_weights() computes from the manifest.
        # (Under the repack an image cannot be placed until its LAYOUT is
        # pinned, so `_replan` does it at emission time instead — see
        # `_emit_matvec_4chan`.)
        if not self.repack and (self.wplan is None
                                or len(self.wplan) != len(self.M.wids)):
            self.wplan = plan_weights_from_wids(self.M.wids)
        self.mv = {"wid": wid, "y32": np.asarray(y32, dtype=np.int64),
                   "consumed": 0, "e_x": int(self.M.eout)}
        if self.nch > 1:
            # rung 1b: buffer the WHOLE matvec (x8 + every .txt dequant chunk),
            # then re-partition it across nch channels at completion.  No
            # record is emitted between here and completion, so the block lands
            # exactly where the 1-chan MOVX/MVGO/MOVY would (checkpoints and
            # step boundaries stay put).
            self.mv["x8_addr"] = int(x8_addr)
            self.mv["n_in"] = int(n_in)
            self.mv["chunks"] = []
            return
        self.stats["movx"] += 1
        self._emit(Rec(OP_MOVX, flags=(self.chan << CHAN_SHIFT),
                       addr_lo=x8_addr, len_or_addr_hi=n_in))

    def on_embed(self, tok, dst, n):
        """EMB record; the step boundary of the decode loop."""
        if tok != self.last_amax_tok:
            # host/prompt-fed token (ISA: "host writes XRF[3]")
            self._csrwr(csr_seq_xrf(XRF_TOK), tok)
        self.steps.append({"rec0": len(self.recs), "tok": int(tok),
                           "fed": tok != self.last_amax_tok})
        self.stats["emb"] += 1
        base = HW.EMB_BASE
        self._emit(Rec(OP_EMB, target=base >> 32, imm32=base & 0xFFFFFFFF,
                       addr_lo=dst, len_or_addr_hi=n))

    def on_amaxl(self, idx, val):
        self.stats["amaxl"] += 1
        self.expect_tokens.append(int(idx))
        self.last_amax_tok = int(idx)
        self._emit(Rec(OP_AMAXL))

    def attn_bf(self, k_a, nq=None):
        """Hint from attn_token: the shared gated-attention block-float
        shift, plus the head count of the block that follows.

        dyn_ka=0 (the v1.2 emission): k_a goes out as a CONSTANT immediate
        (op-8 cfg_p0, and folded into the o_proj MOVY shift), because ISA v1
        indirection carries only one XRF addend and the o_proj shift already
        spends it on e_x — see A3.  That leaves ONE data-dependent immediate
        in the decode-loop body, so no stack containing a full_attention
        layer can loop.

        dyn_ka=1 (the default, ISA v1.3): the next 3*nq commands are
        BUFFERED and re-emitted as the double pass — see _emit_attn_block.
        k_a never appears in the stream; it is computed on chip by the op-8
        probe into XRF[2] and consumed by indirection.

        Recorded per step either way so `finish` can say whether a closed
        loop is structurally safe or merely lucky."""
        self.k_a_hist[int(k_a)] = self.k_a_hist.get(int(k_a), 0) + 1
        self._step_ka.setdefault(max(0, len(self.steps) - 1),
                                 []).append(int(k_a))
        if self.dyn_ka:
            assert nq, "dyn_ka needs the head count from attn_token"
            assert self.attn is None, "nested gated-attention blocks"
            # S3: the block is no longer 3*nq ATTN/SIGM16/EMUL32 triples.
            # Spec 6.2 interleaves the KV schedule -- a LAYER write, an
            # SLD/SST pair and a KVAP per kvhead -- among them, so the
            # buffer is MIXED and the block closes on the nq-th EMUL32
            # rather than on a record count.
            self.attn = {"k_a": int(k_a), "nq": int(nq), "buf": [],
                         "n_em": 0}

    # ------------------------------------------------- attention double pass
    def _emit_attn_block(self):
        """Re-emit the buffered gated-attention block as the ISA v1.3
        DOUBLE PASS, with k_a computed on chip.

        The .txt schedule interleaves, per head h:

            ATTN(kvh, QR+h*HD, AO32)          -> HD int32 pairs
            ALU  7 SIGM16 (QG gate half)      -> OG
            ALU  8 EMUL32 p0=k_a  AO32 x OG   -> GATED+h*HD

        AO32/OG are ONE head's buffers, reused every iteration, and k_a is
        the max |o32*g| over ALL heads — which is why the host has to peek
        every head before it can pick the shift (sw/infer.py
        attn_peek/sigm_peek, gen_layer_script.attn_token).

        vec_alu's probe max is per-COMMAND (rtl/vec_alu.sv:234 clears maxp
        at dispatch), so an on-chip k_a needs the whole token's products
        inside ONE op-8.  The block is therefore re-ordered into

            for h: ALU 7                     -> OGALL  + h*HD    (contiguous)
            for h: ATTN                      -> AO32ALL+ h*2HD   (contiguous)
            ALU 8 PROBE p0=0x40, len=NQ*HD, AO32ALL x OGALL -> GATED
            ALU 8 REAL  p0=0+XRF[2] (IND_ADD on ARG2), same operands

        which is arithmetically identical — every op is elementwise, ATTN
        mutates no layer state and never reads a buffer this block writes —
        but carries NO data-dependent immediate.  The op-7 pass runs FIRST
        so the q_proj output region is dead by the time the ATTN outputs
        need NQ*2*HD contiguous words, and the probe's throwaway output goes
        to GATED, which the real pass immediately overwrites.  Both reused
        regions are rewritten by the mlp_block that always follows in the
        same layer, so the restructure needs NO extra scratch and adds NO
        final-state difference (i.e. no new staging window).

        S3 (SEQ_ISA v2.1, spec 6.2).  The .txt schedule now INTERLEAVES the
        KV state schedule with the heads -- per kvhead, an SLD pair for the
        next kvhead, a LAYER write selecting this one's cache slot, a KVAP,
        the kvhead's four query heads, and an SST pair.  Those records are
        replayed HERE, in their original relative order, around the ATTNs
        they belong to; only the SIGM16s are hoisted out (they read the
        q_proj gate halves and touch no layer state, so they may run before
        any of it) and only the EMUL32s are replaced (by the probe/real
        pair).  ATTN dsts are rewritten to the contiguous AO32ALL slots as
        before; nothing else moves, so the KVAP/ATTN ordering the fences
        and the tags depend on is exactly the .txt program's."""
        import gen_layer_script as _GLS
        blk = self.attn
        self.attn = None
        buf, nq = blk["buf"], blk["nq"]

        def _alu_fields(c):
            op, a0, a1, a2 = c
            p0 = dec_alu_p0(a0, a2)
            return {"op": op, "sub": a0 & 0xF, "n": dec_alu_len(a0),
                    "srca": dec_a1_lo(a1), "srcb": dec_a1_hi(a1),
                    "p0": p0 - (1 << 17) if p0 >= (1 << 16) else p0,
                    "dst": dec_alu_dst(a2)}

        at, sg, em, tail, kvsrc = [], [], [], [], []
        for item in buf:
            if item[0] == "layer":
                tail.append(item)
                continue
            c = item[1:]
            if c[0] == 11 and (c[1] & 0xF) == 7:
                sg.append(_alu_fields(c))
            elif c[0] == 11 and (c[1] & 0xF) == ALU_EMUL32:
                em.append(_alu_fields(c))
            else:
                if c[0] == 10:
                    at.append({"kvh": c[1] & 0xF, "src": dec_a1_lo(c[2]),
                               "dst": dec_a1_hi(c[2])})
                    tail.append(("attn", len(at) - 1))
                else:
                    assert c[0] in (9, 13, 14), (
                        f"unexpected op {c[0]} inside a gated-attention "
                        f"block (spec 6.2 allows KVAP / SLD / SST there)")
                    if c[0] == 9:                     # KVAP: its two sources
                        kvsrc.append((dec_a1_lo(c[2]), dec_a1_hi(c[2])))
                    tail.append(("cmd",) + c)
        assert len(at) == nq and len(sg) == nq and len(em) == nq, (
            f"gated-attention block: {len(at)} ATTN / {len(sg)} SIGM16 / "
            f"{len(em)} EMUL32, expected {nq} of each")
        hd = em[0]["n"]
        assert all(x["n"] == hd for x in em) and all(x["n"] == hd for x in sg)
        assert all(e["srca"] == a["dst"] for e, a in zip(em, at)), \
            "EMUL32 does not read the ATTN output of its own head"
        assert all(e["srcb"] == s["dst"] for e, s in zip(em, sg)), \
            "EMUL32 does not read the SIGM16 output of its own head"
        assert all(e["p0"] == blk["k_a"] for e in em), \
            "EMUL32 immediates disagree with the attn_bf k_a hint"
        gated = em[0]["dst"]
        assert [e["dst"] for e in em] == [gated + h * hd for h in range(nq)], \
            "gated outputs are not contiguous"
        assert 0 <= blk["k_a"] <= ALU_PROBE_SHIFT_MASK, \
            f"k_a {blk['k_a']} outside the op-8 shift range"

        # ---- scratch plan (asserted against the observed live regions) ----
        qg_lo = sg[0]["srca"] - hd
        assert [s["srca"] for s in sg] == [qg_lo + hd + h * 2 * hd
                                           for h in range(nq)], \
            "SIGM16 sources are not the strided q_proj gate halves"
        ao_all, ao_n = qg_lo, nq * 2 * hd        # dead q_proj output region
        og_all, og_n = _GLS.XN, nq * hd          # dead XN + X8 pair
        qr_lo, qr_n = at[0]["src"], nq * hd
        assert [a["src"] for a in at] == [qr_lo + h * hd for h in range(nq)], \
            "ATTN q sources are not contiguous"

        def _hit(a0, n0, b0, n1):
            return (n0 > 0) and (n1 > 0) and (a0 < b0 + n1) and (b0 < a0 + n0)
        # S3 fix round 1, M1.  Spec 6.2 puts the KVAPs INSIDE this block, so
        # the two regions they read -- the roped K heads (`KR`) and the
        # v_proj output (`V16`) -- are LIVE across the reordering and belong
        # in the collision check beside QR.  They are read off the buffered
        # KVAP commands rather than named, so the check follows attn_token
        # rather than restating it.  (Before this, only QR/X0/GATED/STG were
        # checked, and AO32ALL lands on the q_proj region which is adjacent
        # to K16/V16 in the same staging block.)
        live = [("X0", 0, _GLS.XN), ("QR", qr_lo, qr_n),
                ("GATED", gated, nq * hd)]
        if kvsrc:
            k_lo = min(k for k, _v in kvsrc)
            k_hi = max(k for k, _v in kvsrc) + hd
            v_lo = min(v for _k, v in kvsrc)
            v_hi = max(v for _k, v in kvsrc) + hd
            live += [("KR (KVAP k)", k_lo, k_hi - k_lo),
                     ("V16 (KVAP v)", v_lo, v_hi - v_lo)]
        for (nm, b0, n1) in live + [("STG", _GLS.STG,
                                     _GLS.SCRATCH - _GLS.STG)]:
            assert not _hit(og_all, og_n, b0, n1), f"OGALL collides with {nm}"
        for (nm, b0, n1) in live + [("OGALL", og_all, og_n)]:
            assert not _hit(ao_all, ao_n, b0, n1), f"AO32ALL collides with {nm}"

        # ---- 1. every output gate (this frees the q_proj region) ----------
        for h, s in enumerate(sg):
            self._cmd(11, enc_alu_a0(7, hd, s["p0"]), enc_a1(s["srca"]),
                      enc_alu_a2(s["p0"], og_all + h * hd))
        # ---- 2. the KV schedule and every attention head, IN PROGRAM ORDER,
        #         with the ATTN outputs landing in contiguous int32 pairs ----
        for item in tail:
            if item[0] == "attn":
                a = at[item[1]]
                self._cmd(10, a["kvh"],
                          enc_a1(a["src"], ao_all + item[1] * 2 * hd), 0)
            elif item[0] == "layer":
                self._csrwr(CSR_L_LAYER, item[1])
            else:
                self._cmd(item[1], item[2], item[3], item[4])
        # ---- 3. PROBE pass: k_a -> XRF[2] (its output is thrown away) -----
        self._cmd(11, enc_alu_a0(ALU_EMUL32, nq * hd, ALU_PROBE_BIT),
                  enc_a1(ao_all, og_all),
                  enc_alu_a2(ALU_PROBE_BIT, gated))
        # ---- 4. REAL pass: cfg_p0 = 0 + XRF[2] ----------------------------
        self._cmd(11, enc_alu_a0(ALU_EMUL32, nq * hd, 0),
                  enc_a1(ao_all, og_all),
                  enc_alu_a2(0, gated), a2_ind=IND_ADD, a2_xrf=XRF_K_ATTN)
        self.stats["attn_probe"] += 1
        self.attn_blocks += 1
        # the o_proj requant shift that follows must now undo a RUNTIME k_a
        self.ka_pending = blk["k_a"]

    def dn_bf(self, k_h, m_q15, n, src, dst):
        """Hint from dn_token: the next two ALU commands are the DeltaNet
        block-float pair (op1 SHIFT32 k_h, then op2 SCALE m_q15)."""
        self.dnbf = {"k": int(k_h), "m": int(m_q15), "n": int(n),
                     "src": int(src), "dst": int(dst), "stage": 0}

    # ------------------------------------------------------------ fusion
    def _fuse(self, op, a0, a1, a2):
        """The command that consumes a pending W32 -> MVGO + MOVY [+ CMD]."""
        p = self.pend
        self.pend = None
        assert op == 11, f"W32 consumed by layer op {op}, expected ALU"
        sub, n = a0 & 0xF, dec_alu_len(a0)
        srca = dec_a1_lo(a1)
        p0 = dec_alu_p0(a0, a2)
        p0 = p0 - (1 << 17) if p0 >= (1 << 16) else p0
        dst = dec_alu_dst(a2)
        assert srca == p["addr"] and n == p["n"], (
            f"ALU op {sub} reads {srca:#x}/{n}, W32 staged "
            f"{p['addr']:#x}/{p['n']}")
        self._mvgo(p["r0"], n)
        e_x = self.mv["e_x"]
        # k_a stays pending across EVERY chunk of the o_proj matvec (today it
        # is a single 1024-row chunk, but inject_dequant splits above 2048).
        ka = self.ka_pending
        if ka is not None:
            assert sub in (1, 9), (
                "the o_proj requant that follows a gated-attention block is "
                f"ALU op {sub}, expected SHIFT32/SHIFT32W")
        if sub in (1, 9):
            # fused dequant: MOVY does the shift AND the store
            mode = MOVY_INT16 if sub == 1 else MOVY_PAIRS32
            self._movy(dst, n, p0, e_x, mode, ka=ka)
            self.stats["fused_movy"] += 1
        elif sub in (6, 10):
            # MOVY lands raw/shifted int32 pairs, the ALU op keeps its job
            imm_p0 = p0 if sub == 6 else 0
            self._movy(p["addr"], n, imm_p0, e_x if sub == 6 else None,
                       MOVY_PAIRS32)
            new_p0 = 0 if sub == 6 else p0
            # SEQ_ISA v2.0: p0 is split across ARG0[18] and ARG2[15:0], so
            # the ARG0 word is re-packed with the new p0 rather than reused.
            self._cmd(11, enc_alu_a0(sub, n, new_p0), a1,
                      enc_alu_a2(new_p0, dst))
        else:
            raise AssertionError(f"unsupported dequant ALU op {sub}")
        self.mv["consumed"] = p["r0"] + n
        if self.mv["consumed"] >= len(self.mv["y32"]):
            self.mv = None
            self.ka_pending = None

    def _mvgo(self, r0, nrows):
        w = self.wplan[self.mv["wid"]]
        wbase = w["base"] + r0 * w["stride"]
        beats = nrows * w["stride"] // 64
        assert beats < (1 << 24), "MVGO beats field overflow (A7)"
        assert nrows <= HW.RES_DEPTH, "MVGO chunk exceeds RES_DEPTH (A6)"
        # isa defaults to this tree's layout; a W8 or g64 plan is REFUSED
        # here rather than silently packed, because the engine modes are
        # gone (G3.3 / spec 5.1 S5, 5.2 S6).
        shape = HW.shape_word(nrows, w["sh"], w["ng"], w["g"],
                              w8=bool(w.get("w8", False)))
        self.stats["mvgo"] += 1
        tgt = 0
        if self.nowait_mvgo:
            tgt = MVGO_NOWAIT
            self.stats["mvgo_nowait"] += 1
        self._emit(Rec(OP_MVGO, flags=(self.chan << CHAN_SHIFT), target=tgt,
                       imm32=shape, addr_lo=wbase & 0xFFFFFFFF,
                       len_or_addr_hi=((beats << 8) | ((wbase >> 32) & 0xFF))))
        if self.nowait_mvgo:
            # v1 exploit guard: a no-wait MVGO returns before the engine has
            # finished, and the MOVY that follows reads RES.  Until the
            # multi-channel scheduler lands, fence it — the encoding is then
            # exercised end to end without changing any result.
            self.stats["fence"] += 1
            self._emit(Rec(OP_FENCE))

    def _movy(self, dst, nrows, p0, e_x, mode, ka=None):
        """MOVY with the e_x part of the shift as XRF[0] indirection (A2).

        `ka` (the gated-attention block-float shift) makes the shift need
        TWO XRF addends, `const - e_x - k_a` (A3).  ISA indirection carries
        one, so XOP precombines them into the spare XRF[5] and the MOVY
        does a single IND_ADD on it — exactly the v1.1 rationale for 0x0C.
        """
        mode_bit = MOVY_MODE_BIT if mode == MOVY_INT16 else 0
        if e_x is None:
            flags, imm = mode_bit, p0
        elif ka is None:
            # shift_for() = const - e_x  =>  imm32 = p0 + e_x, minus XRF[0]
            imm = p0 + e_x
            flags = IND_SUB | (XRF_EX << MOVY_XRF_SHIFT) | mode_bit
        else:
            # shift_for() = const - e_x - k_a; p0 already has BOTH baked in,
            # so const = p0 + e_x + k_a is a pure weight-matrix constant.
            self.stats["xop"] += 1
            self._emit(Rec(EXT_XOP, target=XRF_OSHIFT,
                           imm32=xop_imm(a=XRF_EX, s1=XOP_NEG,
                                         b=XRF_K_ATTN, s2=XOP_NEG,
                                         simm=p0 + e_x + ka)))
            imm = 0
            flags = IND_ADD | (XRF_OSHIFT << MOVY_XRF_SHIFT) | mode_bit
        self.stats["movy_rows"] += nrows
        self._emit(Rec(OP_MOVY, flags=flags, target=self.chan,
                       imm32=imm & 0xFFFFFFFF, addr_lo=dst,
                       len_or_addr_hi=nrows))

    # ================================================================
    # rung 1b: 4-channel weight-split matvec (nch>1)
    #
    # The 1-chan path above passively mirrors the .txt W32/ALU chunk
    # boundaries.  Here the emitter drives its OWN row partition, exactly like
    # sw/tok_meter.py --four-chan: split_rows(nrows, nch) gives each channel a
    # contiguous row-quarter, res_chunks cuts each quarter into <=CHUNK_ROWS
    # engine runs, and each per-matvec dequant recipe (sub/p0/e_x/ka/mode,
    # UNIFORM across the .txt chunks) is re-applied per channel.  WBASE stays
    # channel-local (base+row*stride); each channel's output lands at
    # dst_base+row, reproducing the identical contiguous scratch image the
    # 1-chan flow (and the downstream layer command) reads.
    #
    # RUNG 4 S4 amends ONE case: the AMAX32 (LM head) matvec, which cannot use
    # contiguous quarters — see `_emit_amax_matvec` and LAYOUT_ILV above.
    # ================================================================
    CHUNK_ROWS = globals()["CHUNK_ROWS"]        # module constant, see above

    def _buffer_matvec_chunk(self, op, a0, a1, a2):
        """Collect one .txt dequant chunk of the in-flight matvec (nch>1).
        Emits nothing until the last chunk closes the matvec."""
        p = self.pend
        self.pend = None
        assert op == 11, f"W32 consumed by layer op {op}, expected ALU"
        sub, n = a0 & 0xF, dec_alu_len(a0)
        srca = dec_a1_lo(a1)
        assert srca == p["addr"] and n == p["n"], (
            f"ALU op {sub} reads {srca:#x}/{n}, W32 staged "
            f"{p['addr']:#x}/{p['n']}")
        self.mv["chunks"].append({"r0": p["r0"], "n": p["n"],
                                  "addr": p["addr"],
                                  "a0": a0, "a1": a1, "a2": a2})
        self.mv["consumed"] = p["r0"] + p["n"]
        if self.mv["consumed"] >= len(self.mv["y32"]):
            self._emit_matvec_4chan()

    def _note_layout(self, wid, layout):
        """Record (and pin) the placement this weight image is emitted for."""
        prev = self.wlayout.setdefault(wid, layout)
        assert prev == layout, (
            f"weight image {wid} is addressed as {prev!r} by one matvec and "
            f"{layout!r} by another — one image, one placement")

    def _replan(self):
        """Re-place every image whose layout is already pinned (repack only).

        `_note_layout` runs before the first MVGO of an image, and wids are
        assigned in first-use order, so the set of pinned images grows in wid
        order and re-placing them all is stable: an image's base never moves
        once it has one.  The host reproduces this by walking the manifest in
        the same order with `meta["weight_layout"]`.

        THAT STABILITY IS THE ASSUMPTION, so it is checked HERE, where it can
        actually fail — a generator that used a LOWER wid for the first time
        after a higher one would insert an image into the middle of the pack
        and move bases that emitted MVGO records already encode.  (Checking
        it only at finish, against a plan recomputed the same way, would be
        tautological: this function rebuilds the whole plan every time.)
        """
        known = {k: v for k, v in self.M.wids.items() if v[0] in self.wlayout}
        prev = self.wplan or {}
        self.wplan = plan_weights_from_wids(
            known, nch=self.nch, repack=True, layout_of=self.wlayout,
            chunk_rows=self.CHUNK_ROWS)
        moved = [w for w, p in prev.items()
                 if w in self.wplan and self.wplan[w]["base"] != p["base"]]
        assert not moved, (
            f"placing a new weight image MOVED already-placed image(s) "
            f"{moved[:8]} — their MVGO records already encode the old "
            f"addresses (wids must be first USED in ascending order)")

    def _wbase(self, wid, ci, row_off):
        """The channel-local WBASE of a piece: `base + row * stride`, where
        `base` is the ONE image base under the nch-independent pack and this
        channel's own base under the repack, and `row` is correspondingly the
        GLOBAL row or the packed per-channel row (`weight_pieces_at`)."""
        w = self.wplan[wid]
        base = w["base"][ci] if self.repack else w["base"]
        return base + row_off * w["stride"]

    def _mvgo_at(self, chan, wid, r0, nrows, nowait, row_off=None):
        """MVGO on an explicit channel (channel-local WBASE=base+row*stride).

        `row_off` is the row index inside the channel's copy of the image; it
        defaults to the GLOBAL row r0, which is what the nch-independent pack
        wants (and it is what `weight_pieces_at(repack=False)` returns), so
        the frozen 4-chan stream is untouched.
        """
        w = self.wplan[wid]
        wbase = self._wbase(wid, chan, r0 if row_off is None else row_off)
        beats = nrows * w["stride"] // 64
        assert beats < (1 << 24), "MVGO beats field overflow (A7)"
        assert nrows <= HW.RES_DEPTH, "MVGO chunk exceeds RES_DEPTH (A6)"
        shape = HW.shape_word(nrows, w["sh"], w["ng"], w["g"],
                              w8=bool(w.get("w8", False)))
        self.stats["mvgo"] += 1
        tgt = 0
        if nowait:
            tgt = MVGO_NOWAIT
            self.stats["mvgo_nowait"] += 1
        self._emit(Rec(OP_MVGO, flags=(chan << CHAN_SHIFT), target=tgt,
                       imm32=shape, addr_lo=wbase & 0xFFFFFFFF,
                       len_or_addr_hi=((beats << 8) | ((wbase >> 32) & 0xFF))))

    def _movy_fields(self, p0, e_x, mode, ka_active):
        """(imm32, flags) for a dequant MOVY — identical arithmetic to _movy,
        except the XOP that seeds XRF[5] is hoisted (emitted ONCE per matvec by
        the caller, since const-e_x-k_a is a step- and chunk-independent
        weight-matrix constant)."""
        mode_bit = MOVY_MODE_BIT if mode == MOVY_INT16 else 0
        if e_x is None:                       # raw / already-shifted pairs32
            return p0 & 0xFFFFFFFF, mode_bit
        if not ka_active:                     # shift = const - e_x  (XRF[0])
            return (p0 + e_x) & 0xFFFFFFFF, \
                IND_SUB | (XRF_EX << MOVY_XRF_SHIFT) | mode_bit
        # shift = const - e_x - k_a, folded into XRF[5] by the hoisted XOP
        return 0, IND_ADD | (XRF_OSHIFT << MOVY_XRF_SHIFT) | mode_bit

    def _movy_at(self, chan, dst, nrows, imm, flags):
        self.stats["movy_rows"] += nrows
        self._emit(Rec(OP_MOVY, flags=flags, target=chan,
                       imm32=imm & 0xFFFFFFFF, addr_lo=dst,
                       len_or_addr_hi=nrows))

    def _emit_matvec_4chan(self):
        """Re-emit the buffered matvec across nch channels (row-split)."""
        mv = self.mv
        chunks = mv["chunks"]
        y32, wid = mv["y32"], mv["wid"]
        nrows = len(y32)
        e_x = mv["e_x"]
        ka = self.ka_pending

        # ---- recipe (uniform across the .txt chunks — asserted) ----------
        def _p0s(c):
            p = dec_alu_p0(c["a0"], c["a2"])
            return p - (1 << 17) if p >= (1 << 16) else p
        c0 = chunks[0]
        sub = c0["a0"] & 0xF
        srcb = dec_a1_hi(c0["a1"])
        stage = c0["addr"]
        p0 = _p0s(c0)
        fused = sub in (1, 9)               # MOVY does shift+store to dst
        staged = sub in (6, 10)             # MOVY->STG, ALU op keeps its job
        amax = (sub == 10)                  # AMAX32: running-index scan
        if not (fused or staged):
            raise AssertionError(f"unsupported dequant ALU op {sub} (4-chan)")
        off = 2 if sub == 9 else 1          # dst stride: pairs32 fused = 2/row
        dst_base = 0 if amax else (dec_alu_dst(c0["a2"]) - c0["r0"] * off)
        for ch in chunks:
            assert (ch["a0"] & 0xF) == sub, "non-uniform dequant sub (4-chan)"
            # The stage only matters for sub 6/10 (MOVY->STG->ALU); fused sub
            # 1/9 write straight to dst and never read the stage, so its .txt
            # W32 may legitimately hop staging buffers (mlp `up`: GP then GP+4096).
            if staged:
                assert dec_a1_lo(ch["a1"]) == stage, "non-uniform stage (4-chan)"
            if not amax:
                assert _p0s(ch) == p0, "non-uniform dequant p0 (4-chan)"
                assert dec_alu_dst(ch["a2"]) == dst_base + ch["r0"] * off, \
                    "non-contiguous dequant dst (4-chan)"
        if ka is not None:
            assert sub in (1, 9), (
                "the o_proj requant after a gated-attention block is ALU op "
                f"{sub}, expected SHIFT32/SHIFT32W")

        # ---- row partition (drop zero-count channels) --------------------
        # S4: the AMAX32 head interleaves chunks across channels, everything
        # else keeps rung 1b's contiguous quarters.  `pieces` is the placement
        # the host must reproduce, so it is recorded per weight image.
        layout = LAYOUT_ILV if amax else LAYOUT_CONTIG
        pieces = weight_pieces_at(nrows, self.nch, layout, self.CHUNK_ROWS,
                                  repack=self.repack)
        self._note_layout(wid, layout)
        if self.repack:
            # the image's layout is pinned now, so it can be placed
            self._replan()
        active = [(self.chans[i], r0, n, off) for (i, r0, n, off) in pieces]

        # ---- MOVX the same x8 into every active engine's XWIN ------------
        # One MOVX per DISTINCT channel, in ascending channel order (the
        # interleave hands a channel several chunks; its XWIN is loaded once).
        for c in sorted({c for (c, _r0, _n, _o) in active}):
            self.stats["movx"] += 1
            self._emit(Rec(OP_MOVX, flags=(c << CHAN_SHIFT),
                           addr_lo=mv["x8_addr"], len_or_addr_hi=mv["n_in"]))

        # ---- ka: seed XRF[5] = const - e_x - k_a ONCE for the matvec -----
        if ka is not None:
            self.stats["xop"] += 1
            self._emit(Rec(EXT_XOP, target=XRF_OSHIFT,
                           imm32=xop_imm(a=XRF_EX, s1=XOP_NEG,
                                         b=XRF_K_ATTN, s2=XOP_NEG,
                                         simm=p0 + e_x + ka)))

        if amax:
            self._emit_amax_matvec(active, wid, stage)
        else:
            self._emit_parallel_matvec(active, wid, sub, fused, p0, e_x, ka,
                                       stage, srcb, dst_base, off)

        self.mv = None
        if ka is not None:
            self.ka_pending = None

    def _emit_parallel_matvec(self, active, wid, sub, fused, p0, e_x, ka,
                              stage, srcb, dst_base, off):
        """Fused (sub 1/9) and SILU32 (sub 6): the nch engines run their chunk
        of a given index CONCURRENTLY (no-wait MVGO x active + one FENCE), then
        drain.  Row writes are independent, so chunk-index order is immaterial."""
        mode = MOVY_INT16 if sub == 1 else MOVY_PAIRS32
        ka_active = ka is not None
        # `off - r0` rebases a sub-chunk's GLOBAL row onto the channel's own
        # packed rows (0 under the nch-independent pack, where off == r0).
        cl = [(c, off - r0, res_chunks(r0, n, self.CHUNK_ROWS))
              for (c, r0, n, off) in active]
        for j in range(max(len(x) for _, _d, x in cl)):
            aj = [(c, d, x[j]) for c, d, x in cl if j < len(x)]
            for c, d, (cr0, rc) in aj:
                self._mvgo_at(c, wid, cr0, rc, nowait=True, row_off=cr0 + d)
            self.stats["fence"] += 1
            self._emit(Rec(OP_FENCE))
            for c, _d, (cr0, rc) in aj:
                if fused:
                    imm, flags = self._movy_fields(p0, e_x, mode, ka_active)
                    self._movy_at(c, dst_base + off * cr0, rc, imm, flags)
                    self.stats["fused_movy"] += 1
                else:                          # sub 6 SILU32: MOVY->STG, ALU
                    imm, flags = self._movy_fields(p0, e_x, MOVY_PAIRS32, False)
                    self._movy_at(c, stage, rc, imm, flags)
                    self._cmd(11, enc_alu_a0(sub, rc, 0),
                              enc_a1(stage, srcb),
                              enc_alu_a2(0, dst_base + cr0))

    def _emit_amax_matvec(self, chunks, wid, stage):
        """AMAX32 (sub 10) — RUNG 4 S4, the 4-chan LM head.

        The argmax index is the vec_alu running scan position `am_g`, so the
        y32 rows MUST be presented in GLOBAL ROW ORDER: it is the ORDER OF THE
        AMAX32 COMMANDS that fixes the index, not which engine fetched the
        rows.  Rung 1b honoured that by giving each channel a contiguous
        quarter and draining the channels one after another — correct, but
        strictly serial, which is why the 248,320-row head never parallelised
        (evidence/rung1/STAGE5_RUNG1B_GATE.md root cause 2).

        S4 keeps the order and recovers the concurrency: `chunks` is the
        INTERLEAVED map (global chunk j -> channel j % nch, ascending), so a
        group of nch consecutive chunks lands on nch DISTINCT channels.  Each
        group is the proven parallel pattern —

            MVGO x nch (no-wait, one per channel)   <- 4 DDR reads in flight
            FENCE                                    <- drains all of them
            for each chunk of the group, ASCENDING:  <- am_g free-runs
                MOVY chan -> STG ; CMD AMAX32 STG

        — i.e. the weight FETCH is nch-way parallel while the retire order is
        byte-for-byte the 1-chan scan order (`fresh` only on the very first
        chunk).  The MOVY->STG->AMAX32 triple reuses the single staging window
        inside a group; that is the same MOVY/CMD interlock `_emit_parallel_
        matvec` already uses for SILU32 (sub 6) and that tb_seq_chip
        CHIP_NMV=4 gated on real RTL.
        """
        first = True
        n = self.nch
        for g0 in range(0, len(chunks), n):
            grp = chunks[g0:g0 + n]
            assert len({c for (c, _r0, _rc, _o) in grp}) == len(grp), \
                "S4 interleave put two chunks of one group on one channel"
            for (c, cr0, rc, off) in grp:
                self._mvgo_at(c, wid, cr0, rc, nowait=True, row_off=off)
            self.stats["fence"] += 1
            self._emit(Rec(OP_FENCE))
            for (c, cr0, rc, _off) in grp:    # ASCENDING global chunk order
                # raw y32 pairs32 -> STG (no shift, no indirection)
                self._movy_at(c, stage, rc, 0, 0)
                # AMAX32 over the staged pairs; fresh resets the running scan
                fresh = 1 if first else 0
                self._cmd(11, enc_alu_a0(10, rc, fresh), enc_a1(stage),
                          enc_alu_a2(fresh, 0))
                first = False

    def _dn_block_float(self, a0, a1, a2):
        """dn_token's op1(k_h) + op2(m_q15) pair -> DYNQ16 [+ EPS-NORM]."""
        h = self.dnbf
        sub, n = a0 & 0xF, dec_alu_len(a0)
        p0 = dec_alu_p0(a0, a2)
        p0 = p0 - (1 << 17) if p0 >= (1 << 16) else p0
        dst = dec_alu_dst(a2)
        if h["stage"] == 0:
            assert sub == 1 and n == h["n"] and p0 == h["k"], \
                "dn_bf hint does not match the following SHIFT32"
            # vec_alu op 12 DYNQ16: cfg_p0[0] = XRF dest (0 -> XRF[1]),
            # cfg_p0[1] = clamp k at 0 (off for DeltaNet).
            self.stats["dynq16"] += 1
            self._cmd(11, enc_alu_a0(ALU_DYNQ16, n, 0), a1,
                      enc_alu_a2(0, dst))
            h["stage"] = 1
            return True
        assert sub == 2 and p0 == h["m"], \
            "dn_bf hint does not match the following SCALE"
        if self.profile == "epsnorm":
            # VN mode 2 + ARG2[0]=1 EPS-NORM, k from XRF[1] (A4/A5)
            import layer_fixed as _LF
            nlog2 = int(n).bit_length() - 1
            src = dec_a1_lo(a1)
            self.stats["epsnorm"] += 1
            self._cmd(1, VN_EPSNORM_MODE | (nlog2 << 2) | (_LF.S_F << 6)
                      | (_LF.DN_NORM_F << 10),
                      enc_a1(src, dst),
                      VN_ARG2_EPS | (XRF_K_DN << VN_ARG2_XRF_SHIFT))
        else:
            self._cmd(11, a0, a1, a2)
        self.dnbf = None
        return True

    # ------------------------------------------------------------ finish
    def _rebuild(self, items):
        """Rebuild the record list from [(old_index|None, Rec)], carrying
        the live-state checkpoints and the step boundaries across."""
        new_recs, old2new = [], {}
        for (oi, r) in items:
            if oi is not None:
                old2new[oi] = len(new_recs)
            new_recs.append(r)
        self.cp_at = {old2new[i]: v for i, v in self.cp_at.items()
                      if i in old2new}
        for s in self.steps:
            if s["rec0"] in old2new:
                s["rec0"] = old2new[s["rec0"]]
        self.recs = new_recs
        return old2new

    def _index_pos_loads(self):
        """Rewrite the position-indexed LDCs to XRF[4] indirection (A10).

        Returns the per-step byte stride, or None when the layout is not
        uniformly strided (in which case the loop cannot close on them).
        """
        if not self._pos_recs:
            return 0
        per_step = {}
        for (i, off, s) in self._pos_recs:
            per_step.setdefault(s, []).append((i, off))
        steps = sorted(per_step)
        if len(steps) < 2:
            return None
        n = len(per_step[steps[0]])
        base0 = per_step[steps[0]][0][1]
        deltas = [off - base0 for (i, off) in per_step[steps[0]]]
        stride = per_step[steps[1]][0][1] - base0
        for s in steps:
            grp = per_step[s]
            if len(grp) != n:
                return None
            b = grp[0][1]
            if b != base0 + (s - steps[0]) * stride:
                return None
            if [off - b for (i, off) in grp] != deltas:
                return None
        pb = self.blob.base + self.blob.size
        b0 = base0
        for s in steps:
            for (i, off), d in zip(per_step[s], deltas):
                a = pb + b0 + d
                self.recs[i] = Rec(EXT_LDC,
                                   flags=IND_ADD | (XRF_POS << XRF_SHIFT),
                                   target=self.recs[i].target,
                                   imm32=self.recs[i].imm32,
                                   addr_lo=a & 0xFFFFFFFF,
                                   len_or_addr_hi=a >> 32)
        return stride

    def _try_loop(self):
        """Collapse identical trailing step bodies into one + JMP/TCNT_SEQ.

        Returns (n_looped, reason).  See A10 for why this usually reports 0.
        """
        if not self.want_loop or len(self.steps) < 2:
            return 0, "fewer than two decode steps"
        stride = self._index_pos_loads()
        if stride is None:
            return 0, "position-indexed constants are not uniformly strided"
        if stride:
            # XADD advancing the position cursor closes each body
            bounds = [s["rec0"] for s in self.steps] + [len(self.recs)]
            items = [(i, self.recs[i]) for i in range(bounds[0])]
            items.append((None, Rec(OP_CSRWR, target=csr_seq_xrf(XRF_POS),
                                    imm32=0)))
            for i in range(len(self.steps)):
                items += [(j, self.recs[j])
                          for j in range(bounds[i], bounds[i + 1])]
                # XRF[4] += stride — the v1.4 XOP spelling of the old XADD
                items.append((None, Rec(
                    EXT_XOP, target=XRF_POS,
                    imm32=xop_imm(a=XRF_POS, s1=XOP_POS, simm=stride))))
            self._rebuild(items)
        bounds = [s["rec0"] for s in self.steps] + [len(self.recs)]
        bodies = []
        for i in range(len(self.steps)):
            bodies.append(pack_stream(self.recs[bounds[i]:bounds[i + 1]]))
        # the last (len-1) steps must all be identical to loop
        tail = 1
        while tail < len(bodies) and bodies[-1 - tail] == bodies[-1]:
            tail += 1
        if tail < 2:
            a = unpack_stream(bodies[-2])
            b = unpack_stream(bodies[-1])
            why = "step bodies differ"
            for j in range(min(len(a), len(b))):
                if a[j] != b[j]:
                    why = (f"first divergence at body record {j}: "
                           f"{disasm(a[j])!r} vs {disasm(b[j])!r}")
                    break
            else:
                why = f"body lengths differ ({len(a)} vs {len(b)})"
            return 0, why
        h_end = bounds[len(self.steps) - tail]
        b_end = bounds[len(self.steps) - tail + 1]
        items = [(i, self.recs[i]) for i in range(h_end)]
        items.append((None, Rec(OP_CSRWR, target=CSR_SEQ_TCNT, imm32=tail)))
        base = len(items)
        items += [(i, self.recs[i]) for i in range(h_end, b_end)]
        items.append((None, Rec(OP_JMP, flags=JMP_TCNT, imm32=base)))
        self._rebuild(items)
        return tail, "looped"

    def finish(self):
        if self.finished:
            return
        self.finished = True
        assert self.attn is None, \
            "a gated-attention block was never completed (short cmd stream)"
        assert self.ka_pending is None, \
            "a gated-attention k_a was never consumed by an o_proj MOVY"
        self._fix_pos_addrs()
        nloop, why = self._try_loop()      # BEFORE the HALT: it is not a step
        self._emit(Rec(OP_HALT))
        recs = self.recs
        # G4a: the emitter is a BUILDER, and a builder states the SHAPE
        # LAYOUT it built in.  This class emits SEQ_ISA v2.0 and nothing
        # else, so the MVGO `ng` envelope is checkable here -- the same
        # lockstep `tb/scripts/gen_seq_unit_vectors.py` is in.  It cannot
        # fire in practice (`_mvgo` packs through `shape_word`, whose own
        # assert refuses an out-of-envelope `ng` before a record exists),
        # which is exactly why it belongs: a second, independent reading of
        # the same bound over the finished stream.
        validate_stream(recs, shape_isa=SHAPE_ISA_9B)
        stream = pack_stream(recs)
        with open(self.prefix + ".seq", "wb") as f:
            f.write(stream)
        blob = self.blob.to_bytes() + self.posblob.to_bytes()
        with open(self.prefix + ".seqdata.bin", "wb") as f:
            f.write(blob)
        meta = {
            "format": "FAB5SEQ", "format_version": FORMAT_VERSION,
            "profile": self.profile, "chan": self.chan,
            "nch": self.nch, "chans": list(self.chans),
            "nrec": len(recs), "stream_bytes": len(stream),
            "stream_sha256": hashlib.sha256(stream).hexdigest(),
            "seqdata_bytes": len(blob),
            "seqdata_sha256": hashlib.sha256(blob).hexdigest(),
            "seq_data_base": self.blob.base,
            "seq_stream_base": SEQ_STREAM_BASE,
            "emb_base": HW.EMB_BASE,
            "weights": {str(k): v for k, v in (self.wplan or {}).items()},
            "expect_tokens": self.expect_tokens,
            "steps": len(self.steps),
            "prompt_fed": [s["tok"] for s in self.steps if s["fed"]],
            "loop_steps": nloop, "loop_note": why,
            # A closed loop is only STRUCTURALLY safe when no record in the
            # body still carries a data-dependent immediate.  Two families
            # existed: the DN block-float pair (gone in the epsnorm profile,
            # where DYNQ16 + EPS-NORM compute both on chip) and the
            # attention shared shift k_a (gone with dyn_ka, where the op-8
            # probe computes it into XRF[2] and XOP folds it into the o_proj
            # MOVY shift).  When this is false but loop_steps > 0, the
            # bodies matched only because those immediates coincided on
            # this input.
            "loop_structurally_safe": bool(
                nloop and self.profile == "epsnorm"
                and (self.dyn_ka or not self._step_ka)),
            "dyn_ka": self.dyn_ka,
            "nowait_mvgo": self.nowait_mvgo,
            "attn_blocks": self.attn_blocks,
            "attn_k_a_per_step": {str(k): v
                                  for k, v in sorted(self._step_ka.items())},
            "attn_k_a_histogram": {str(k): v for k, v
                                   in sorted(self.k_a_hist.items())},
            "checkpoints": [[i, a, n] for i, (a, n)
                            in sorted(self.cp_at.items())],
            "staging_words": [[int(a), int(b)] for (a, b)
                              in _runs(self.staging)],
            "newops_source": NEWOPS_SOURCE,
            "stats": dict(self.stats),
            "ldc_csrwr_equiv_records": ldc_as_csrwr_cost(recs),
            "ext_records": sum(1 for r in recs if r.opcode in EXT_OPS),
            "isa_v1_records": sum(1 for r in recs
                                  if r.opcode in ISA_V1_OPS),
            "opcode_histogram": {OP_NAME[o]: sum(1 for r in recs
                                                 if r.opcode == o)
                                 for o in sorted(ALL_OPS)
                                 if any(r.opcode == o for r in recs)},
            "notes": self.notes,
        }
        if _GLS.MS.TAG not in _GLS.BYTELOCKED_TAGS:
            # G4a: the SHAPE LAYOUT this stream is encoded in, so a LOADER
            # can arm the MVGO `ng` envelope without knowing which emitter
            # built the file (`ref/seq_model.gate()`, `ref/seq_chat`'s
            # Templates and `tb/scripts/gen_seq_chip_vectors.py` all read
            # `meta.get("shape_isa")`; absent = not stated = check OFF).
            #
            # Gated on the tag for the SAME reason `rs_f` is
            # (`ref/gen_model_script.py`'s `dump_weights` call, spec A2.5):
            # `evidence/qwen2b/rc/t3_locks.sh` lock B `cmp`s the whole 0.8B
            # `.e4.seq.json`, so an unconditional key would move bytes that
            # gate pins.  `gen_layer_script.BYTELOCKED_TAGS` is the one place
            # the list lives.
            meta["shape_isa"] = SHAPE_ISA_9B
        if self.nch > 1:
            # rung 4 S4: the host must place each weight image the way this
            # stream's MVGO WBASEs read it.  Added ONLY for nch>1 so a 1-chan
            # .seq.json stays byte-identical to every committed artifact.
            meta["weight_layout"] = {
                "nch": self.nch,
                "chunk_rows": self.CHUNK_ROWS,
                "default": LAYOUT_CONTIG,
                "by_wid": {str(k): v for k, v in sorted(self.wlayout.items())},
                "ilv_wids": sorted(k for k, v in self.wlayout.items()
                                   if v == LAYOUT_ILV),
            }
        if self.repack:
            # R-c: PER-CHANNEL pack.  Added ONLY when it is on, so every
            # .seq.json emitted without it stays byte-identical; a reader
            # takes ABSENT as false, and `weights[wid]["base"]` is then an
            # int (one span every channel shares) instead of the nch-long
            # list this mode emits.
            meta["weight_repack"] = True
        with open(self.prefix + ".seq.json", "w") as f:
            json.dump(meta, f, indent=1)
        return meta


def maybe_attach(mach, sink):
    """Called from Mach.__init__ when SEQ_EMIT is set.  `sink` is the .txt
    file object; the SEQ prefix is derived from its name unless SEQ_EMIT
    names one explicitly."""
    v = os.environ.get("SEQ_EMIT", "")
    if not v:
        return None
    name = getattr(sink, "name", None)
    if v in ("1", "auto", "yes", "on") and name:
        prefix = name.rsplit(".", 1)[0]
    else:
        prefix = v
    em = SeqEmitter(mach, prefix,
                    profile=os.environ.get("SEQ_PROFILE", "xlat"),
                    chan=int(os.environ.get("SEQ_CHAN", "0")),
                    loop=os.environ.get("SEQ_LOOP", "1") != "0",
                    dyn_ka=os.environ.get("SEQ_DYNKA", "1") != "0",
                    nowait_mvgo=os.environ.get("SEQ_NOWAIT", "0") != "0",
                    nch=int(os.environ.get("SEQ_NCH", "1")),
                    repack=os.environ.get("SEQ_REPACK", "0") != "0")
    import atexit
    atexit.register(_finalize, mach)
    return em


def _finalize(mach):
    em = getattr(mach, "seq", None)
    if em is None or em.finished:
        return
    # Recompute the WHOLE pack from the final wids and require the plan the
    # MVGOs were actually built from to agree with it, image for image.
    #
    # WHAT THIS CATCHES, AND WHAT IT DOES NOT (R-c review I2).  Under the
    # repack `_replan` rebuilds the plan on every placement, so this
    # comparison cannot see a base that MOVED mid-run: `_replan`'s own assert
    # is what catches that, and it lives where the movement is observable.
    # What this catches is the plan WIDENING at the end — a wid in
    # `mach.wids` that never got an MVGO (so never a layout, so never a place
    # in the pack) appears here and shifts every image after it.  Both are
    # FATAL, not notes: a stream whose records encode addresses the published
    # plan disagrees with must not be written at all.
    try:
        final = plan_weights_from_wids(
            mach.wids, nch=em.nch, repack=em.repack,
            layout_of=em.wlayout if em.repack else None,
            chunk_rows=em.CHUNK_ROWS)
    except Exception as e:                                # pragma: no cover
        if em.repack:
            # A repack plan that cannot even be COMPUTED means the emitted
            # WBASEs have no published counterpart, and the host would plan a
            # pack of its own and upload the weights somewhere else.
            raise RuntimeError(
                f"the per-channel weight plan could not be computed ({e}) — "
                "no .seq is written; the stream's MVGO addresses would have "
                "no plan for the host to reproduce") from e
        em.notes.append(f"weight plan failed: {e}")
    else:
        bad = [k for k, v in (em.wplan or {}).items() if final.get(k) != v]
        if bad:                                           # pragma: no cover
            raise RuntimeError(
                "the incremental weight plan diverged from the final "
                f"packing on wid(s) {bad[:8]} — no .seq is written, because "
                "the MVGO records already encode the OLD addresses")
        em.wplan = final
    meta = em.finish()
    if meta:
        print(f"SEQ: {meta['nrec']} records ({meta['stream_bytes']} B) + "
              f"{meta['seqdata_bytes']} B const blob -> {em.prefix}.seq  "
              f"[profile={meta['profile']} loop_steps={meta['loop_steps']}]",
              file=sys.stderr)


# ======================================================================
# SEQ_ISA B17.3 (R3): the MOVX BROADCAST -- Task R3-2 of the R3 campaign
# (docs/superpowers/plans/2026-09-29-r3-broadcast.md).  Everything R3 adds to
# this file lives HERE, after every line other documents cite, so no citation
# moves (the SR14 §7 zero-drift rule): validate(), validate_stream() and
# disasm() each reach it through ONE rewritten line.  Names resolve at call
# time, so defining them after their callers is ordinary Python.
# ======================================================================
MOVX_BCAST = 0xF        # MOVX flags[7:4] = 0xF: broadcast to channels 0..3
# A broadcast is admitted only when the DEVICE has all three round
# capabilities.  Names only -- the bits and the SEQ_CAPS word are hwmap's
# (SEQ_CAP_BITS, the ONE definition), checked here by hwmap.seq_caps_check.
MOVX_BCAST_CAPS = HW.seq_caps_check({"R1", "R2", "R3"})


def _movx_bcast_admitted(r, caps, bad):
    """validate()'s channel clause for flags[7:4] >= 4 (called only there).

    True for a MOVX broadcast (flags[7:4] = MOVX_BCAST) when MOVX_BCAST_CAPS
    <= caps: validate() then goes on to B17.2's window rule on the ONE start
    word (target[15:12] = 0; start + ceil(len/4) words <= 3072), exactly as
    for a unicast MOVX, since R2 is in caps.  A broadcast at a caps set
    lacking any of the three is refused through `bad` NAMING every missing
    capability: every pre-R3 bitstream faults it err 0x05, and an r3 stream
    also carries B17.2 bank fields, which are NOT fail-closed on an R1/R2
    device, so the refusal must happen here, before upload.  Anything else
    (MOVX 4..14, any MVGO >= 4, MVGO 0xF included) returns False and keeps
    today's "engine channel N >= 4" (err 0x05).  Indirection on a broadcast
    was already refused above (flags[3:0], A1)."""
    if r.opcode != OP_MOVX or r.chan != MOVX_BCAST:
        return False
    miss = sorted(MOVX_BCAST_CAPS - caps)
    if miss:
        bad(f"MOVX channel field {r.chan:#x} is the BROADCAST (B17.3): it "
            f"needs capabilities {', '.join(sorted(MOVX_BCAST_CAPS))}; the "
            f"device's caps {{{', '.join(sorted(caps))}}} lack "
            f"{', '.join(miss)}")
    return True


def _bcast_running(recs, n, shape_isa, caps):
    """validate_stream()'s last step: B17.3's running rule PER DESTINATION.

    A broadcast MOVX is refused when its word range overlaps ANY channel's
    pending x range -- a NO-WAIT MVGO not yet drained by a waiting MVGO on
    that channel or by a FENCE covering it (mask 0 = all four; a non-zero
    mask was admitted only under R1).  Mirrors seq_model.SeqExec: the
    pending range is x words [1536*XBANK, 1536*XBANK + 32*max(ng, 1)), and
    an EMPTY broadcast counts as overlapping (seq_model._overlap).  Called
    after every record passed validate(), so it only ever sees an admitted
    broadcast; below {R1,R2,R3} none can exist and it returns at once, so
    no pre-R3 stream's verdict moves.  The unicast running rule stays the
    model gate's (RunningChannelError); validate() itself stays stateless,
    as B17.3 says.  The walk is in RECORD order: a hazard carried round a
    JMP back-edge is the model gate's to catch.  Returns n."""
    if not MOVX_BCAST_CAPS <= caps:
        return n
    pend = {}
    for idx, r in enumerate(recs):
        if r.opcode == OP_MVGO:
            if r.target & MVGO_NOWAIT:
                if shape_isa == HW.SHAPE_ISA_PRE_G3:
                    ng, xb = r.imm32 & 0x3F, 0
                else:
                    ng, xb = (r.imm32 >> 22) & 0x7F, (r.imm32 >> 29) & 1
                w0 = XBANK_WORD * xb
                pend[r.chan] = (w0, w0 + XWIN_LINE_WORDS * max(ng, 1))
            else:
                pend.pop(r.chan, None)
        elif r.opcode == OP_FENCE:
            fm = r.target & 0xF
            for c in [c for c in pend if fm == 0 or (fm >> c) & 1]:
                del pend[c]
        elif r.opcode == OP_MOVX and r.chan == MOVX_BCAST:
            w0 = r.target & MOVX_WORD_MASK
            w1 = w0 + movx_words(r.len_or_addr_hi & 0xFFFFFF)
            for c in sorted(pend):
                p0, p1 = pend[c]
                if w1 <= w0 or (w0 < p1 and p0 < w1):
                    raise SeqValidationError(
                        f"rec {idx}: broadcast MOVX writes XWIN words [{w0}, "
                        f"{w1}) on every channel while a NO-WAIT MVGO on "
                        f"mv{c} still reads words [{p0}, {p1}) -- every "
                        f"destination's bank must be free; the stream needs "
                        f"a FENCE covering mv{c} first (B17.3, B17.2 running "
                        f"ranges)  [{_disasm_raw(r)}]")
    return n


def _movx_dst(r):
    """disasm()'s MOVX destination: "mv<c>", or "chan=ALL" for a broadcast."""
    return "chan=ALL" if r.chan == MOVX_BCAST else f"mv{r.chan}"


# ======================================================================
if __name__ == "__main__":
    import io
    # round-trip + validation self-test
    r = Rec(OP_MOVY, flags=IND_SUB | (XRF_EX << MOVY_XRF_SHIFT)
            | MOVY_MODE_BIT, target=1, imm32=(-7) & 0xFFFFFFFF,
            addr_lo=0x1234, len_or_addr_hi=1024)
    assert unpack(r.to_bytes()) == r
    assert r.imm_s == -7 and r.chan == 1 and r.xrf == XRF_EX
    assert r.movy_mode == MOVY_INT16
    xrf = [0] * XRF_N
    xrf[XRF_EX] = 5
    assert resolve_imm(r, xrf) == -12
    stream = pack_stream([Rec(OP_CSRWR, target=CSR_L_ARG0, imm32=1),
                          Rec(OP_CMD, target=CSR_L_CMD, imm32=11),
                          r, Rec(OP_HALT)])
    assert validate_stream(stream) == 4
    try:
        validate(Rec(0x7F))
        raise SystemExit("validate accepted an unknown opcode")
    except SeqValidationError:
        pass
    try:
        validate(Rec(OP_JMP, flags=0x3))
        raise SystemExit("validate accepted an unknown JMP flag")
    except SeqValidationError:
        pass
    try:
        validate(Rec(OP_MOVX, flags=IND_ADD))
        raise SystemExit("validate accepted MOVX indirection")
    except SeqValidationError:
        pass
    # --- XOP (v1.4 D-1: 0x0C is XOP everywhere) --------------------------
    xr = [0] * XRF_N
    xr[XRF_EX], xr[XRF_K_ATTN] = 5, 9
    xo = Rec(EXT_XOP, target=XRF_OSHIFT,
             imm32=xop_imm(a=XRF_EX, s1=XOP_NEG, b=XRF_K_ATTN, s2=XOP_NEG,
                           simm=31))
    validate(xo)
    assert xop_fields(xo.imm32) == (XRF_EX, XOP_NEG, XRF_K_ATTN, XOP_NEG, 31)
    assert xop_eval(xo.imm32, xr) == 31 - 5 - 9 == 17
    # XADD is XOP with one +1 term
    xa = Rec(EXT_XOP, target=XRF_POS,
             imm32=xop_imm(a=XRF_POS, s1=XOP_POS, simm=-1536))
    xr[XRF_POS] = 4608
    assert xop_eval(xa.imm32, xr) == 3072
    try:
        validate(Rec(EXT_XOP, target=0, imm32=(0x3 << 8)))
        raise SystemExit("validate accepted XOP sign code 11")
    except SeqValidationError:
        pass
    try:
        validate(Rec(OP_MVGO, target=2))
        raise SystemExit("validate accepted a reserved MVGO target bit")
    except SeqValidationError:
        pass
    validate(Rec(OP_MVGO, target=MVGO_NOWAIT))       # v1.4 no-wait is legal
    buf = io.StringIO()
    disasm_stream(stream, buf)
    print(buf.getvalue(), end="")
    print(f"new-op semantics from: {NEWOPS_SOURCE}")
    print("seq_format selftest: OK")
