#!/usr/bin/env python3
"""gen_seq_vectors.py — golden vectors for tb/tb_seq_unit.sv.

Builds SEQ record streams with ref/seq_format.py (THE wire truth: pack /
validate / resolve_imm) and emits, for each stream, the exact AXI-Lite
transaction lists rtl/seq_unit.sv must produce against the behavioural
layer/matvec stubs, plus the final architectural state.

    <prefix>.ddr.hex   DDR image for tb/seq_ddr_model.sv (records + LDC blob
                       + embedding table), 128-bit words, @word-index sparse
    <prefix>.wtr       expected AXI-Lite writes, in order: "addr data"
    <prefix>.rtr       expected AXI-Lite reads,  in order: "addr"
                       (STATUS polls at 0x?004 are excluded — their count is
                       timing dependent; the TB filters the same way)
    <prefix>.sb.rtr    same, for USE_XRF_SIDEBAND=1 (no XRF refresh reads)
    <prefix>.exp       NREC / ERR / PC / XRF / TOK / MEM lines
    <prefix>.dis       disassembly (debug only)

WHAT IS GOLDEN AND WHAT IS NOT.  The encode/validate/indirection layer is
ref/seq_format.py itself (imported, not reimplemented) and the MOVY dequant
is ref/seq_model.rs_s + clip16 (imported, not reimplemented) — those are the
two places a wire-format or numeric divergence could hide, and they are the
ref-side originals.  What this file DOES model itself is the behaviour of
tb/seq_stub_layer.sv and tb/seq_stub_mvchan.sv, which are stubs, not the
real engines: the values they return for EOUT / XRF / AMAXI / RES are
deterministic pseudo-random functions, chosen so the sequencer's plumbing is
checkable bit-exactly without dragging the whole layer datapath into a unit
TB.  ref/seq_model.py remains the golden for the FULL-CHIP SEQ-driven sim,
which replays the same streams against the real layer_chan.

Usage:  gen_seq_vectors.py <outdir> <seed>
"""
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_REF = os.path.normpath(os.path.join(_HERE, "..", "..", "ref"))
sys.path.insert(0, _REF)

import seq_format as SF                                       # noqa: E402
import seq_model as SM                                        # noqa: E402

# ---------------------------------------------------------------- addresses
LAYER = 0x5000
def MV(c):
    return 0x1000 * (c + 1)

L_CMD, L_STAT, L_ARG0, L_ARG1, L_ARG2 = 0x00, 0x04, 0x08, 0x0C, 0x10
L_SPTR, L_SWIN, L_EOUT, L_AMAXI = 0x14, 0x18, 0x1C, 0x28
# agent C's landed XRF window in layer_chan (ISA v1.3)
L_XRFI, L_XRFD = 0x38, 0x3C
MV_CTRL, MV_STAT, MV_WBLO, MV_WBHI = 0x00, 0x04, 0x08, 0x0C
MV_BEATS, MV_SHAPE, MV_XWIN, MV_XPTR = 0x10, 0x14, 0x24, 0x28
MV_RESPTR, MV_RESDAT = 0x2C, 0x30

# DDR layout — must match tb_seq_unit.sv and stay inside seq_ddr_model's
# 1 MB aliasing window (araddr[19:4]).
STREAM_BASE = 0x9000_1000
BLOB_BASE   = 0x9002_0000
EMB_BASE    = 0x9004_0000
EMB_ROW_BYTES = 2048

SCRATCH_WORDS = 16384


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & (1 << 31) else v


def s16(v):
    v &= 0xFFFF
    return v - (1 << 16) if v & (1 << 15) else v


# ======================================================================
# the model: seq_unit + seq_movers driving seq_stub_layer / seq_stub_mvchan
# ======================================================================
class Model(object):
    def __init__(self, blob, emb):
        self.blob = blob                     # bytes at BLOB_BASE
        self.emb = emb                       # np.int16 [rows, 1024]
        self.mem = np.zeros(SCRATCH_WORDS, dtype=np.int64)
        self.wrote = {}                      # scratch addr -> value
        self.sptr = 0
        self.xrf = [0] * 8                   # raw 18-bit
        self.lxrf = [0] * 8                  # the layer stub's XRF
        self.eout = 0
        self.amax_idx = 0
        self.cmd_cnt = 0
        self.args = [0, 0, 0]
        self.mv = [dict(xsum=0, seed=0, wblo=0, shape=0, resptr=0)
                   for _ in range(4)]
        self.tcnt = 0
        self.out = []
        self.wtr = []                        # (addr, data)
        self.wtr_sb = []                     # (addr, data) sideband variant
        self.rtr = []                        # addr   (XRF refresh included)
        self.rtr_sb = []                     # addr   (sideband variant)
        self.xrfi = 0                        # the layer stub's XRFI
        self.pend = [False] * 4              # no-wait MVGO channels
        self.err = 0
        self.pc = 0

    # ---- helpers ----
    def xv(self, i):
        v = self.xrf[i] & 0x3FFFF
        if i == 3:
            return v
        return v - (1 << 18) if v & (1 << 17) else v

    def xset(self, i, v):
        self.xrf[i] = int(v) & 0x3FFFF

    def xlist(self):
        return [self.xv(i) for i in range(8)]

    def W(self, addr, data, sb=True):
        self.wtr.append((addr & 0xFFFFFFFF, data & 0xFFFFFFFF))
        if sb:
            self.wtr_sb.append((addr & 0xFFFFFFFF, data & 0xFFFFFFFF))

    def R(self, addr, sb=True):
        self.rtr.append(addr & 0xFFFFFFFF)
        if sb:
            self.rtr_sb.append(addr & 0xFFFFFFFF)

    def xrf_refresh(self, idx):
        """seq_unit's mirror refresh after an XRF-writing command."""
        if idx == 0:
            self.R(LAYER + L_EOUT, sb=False)          # DYNQ8: EOUT, 1 read
        else:
            self.W(LAYER + L_XRFI, idx, sb=False)     # XRFI -> drain -> XRFD
            self.R(LAYER + L_XRFD, sb=False)
            self.xrfi = idx
        self.xset(idx, self.lxrf[idx])

    def xrf_writethrough(self, idx, val):
        """seq_unit mirrors its own XRF writes into layer_chan (EPS-NORM
        reads k from THAT copy), XRFI then XRFD."""
        self.xset(idx, val)
        self.lxrf[idx] = int(val) & 0x3FFFF
        self.xrfi = idx
        self.W(LAYER + L_XRFI, idx)
        self.W(LAYER + L_XRFD, int(val) & 0x3FFFF)

    def swrite(self, addr, val):
        self.mem[addr] = s16(val)
        self.wrote[addr] = val & 0xFFFF

    # ---- layer stub: a command retires ----
    def cmd_retire(self, op):
        n = self.cmd_cnt
        a0, _, a2 = self.args
        if op == 11:
            sub = a0 & 0xF
            if sub == 0:
                self.eout = (7 * n + 3) & 0xF
                self.lxrf[0] = self.eout
            if sub == 12:
                k = ((5 * n + 1) % 33) - 16
                self.lxrf[2 if (a2 & 1) else 1] = k & 0x3FFFF
            if sub == 8 and (a2 >> 6) & 1:            # ISA v1.3 k_a probe
                self.lxrf[2] = (((3 * n + 7) % 67) - 33) & 0x3FFFF
            if sub == 10:
                self.amax_idx = (2654435761 * n) & 0x3FFFF
        self.cmd_cnt += 1

    # ---- matvec stub ----
    def res_word(self, c, i):
        return ((2654435761 * i) & 0xFFFFFFFF) ^ self.mv[c]["seed"]

    # ==================================================================
    def run(self, recs, entry=0, max_steps=1 << 20):
        pc = entry
        n = len(recs)
        # the START resync read of layer STATUS is a poll -> filtered out
        steps = 0
        while True:
            steps += 1
            if steps > max_steps:
                raise RuntimeError("runaway stream")
            if pc >= n:
                self.err, self.pc = 0x09, pc
                return
            r = recs[pc]
            bad = self.validate(r, n)
            if bad:
                self.err, self.pc = bad, pc
                return
            nxt = pc + 1
            o = r.opcode
            if o == SF.OP_CSRWR:
                val = SF.resolve_imm(r, self.xlist()) & 0xFFFFFFFF
                sp, off = r.target & 0xF000, r.target & 0xFF
                if sp == SF.CSR_SPACE_SEQ:
                    if off >= 0x40:
                        self.xrf_writethrough((off - 0x40) // 4, val)
                    elif off == 0x20:
                        self.tcnt = val
                    else:
                        self.err, self.pc = 0x07, pc
                        return
                elif sp == SF.CSR_SPACE_LAYER:
                    if off == L_ARG0:
                        self.args[0] = val
                    elif off == L_ARG1:
                        self.args[1] = val
                    elif off == L_ARG2:
                        self.args[2] = val
                    self.W(LAYER + off, val)
                    if off == L_SPTR:
                        self.sptr = val & 0x3FFF
                    elif off == L_SWIN:
                        self.swrite(self.sptr, val)
                        self.sptr = (self.sptr + 1) & 0x3FFF
                else:
                    self.W(MV((r.target >> 8) & 0xF) + off, val)
            elif o == SF.OP_CMD:
                val = SF.resolve_imm(r, self.xlist()) & 0xFFFFFFFF
                self.W(LAYER + (r.target & 0xFF), val)
                op = val & 0xFF
                self.cmd_retire(op)
                a0, _, a2 = self.args
                sub = a0 & 0xF
                if op == 11 and sub == 0:
                    self.xrf_refresh(0)
                elif op == 11 and sub == 12:
                    self.xrf_refresh(2 if (a2 & 1) else 1)
                elif op == 11 and sub == 8 and ((a2 >> 6) & 1):
                    self.xrf_refresh(2)
            elif o == SF.OP_MOVX:
                self.movx(r)
            elif o == SF.OP_MVGO:
                self.mvgo(r)
            elif o == SF.OP_MOVY:
                self.movy(r)
            elif o == SF.OP_FENCE:
                self.pend = [False] * 4      # polls only -> no logged traffic
            elif o == SF.OP_EMB:
                self.bulk_emb(r)
            elif o == SF.EXT_LDC:
                self.bulk_ldc(r)
            elif o == SF.OP_AMAXL:
                self.R(LAYER + L_AMAXI)
                self.out.append(self.amax_idx)
                self.xrf_writethrough(3, self.amax_idx)
            elif o == SF.OP_JMP:
                if r.flags & SF.JMP_TCNT:
                    self.tcnt = (self.tcnt - 1) & 0xFFFFFFFF
                    if self.tcnt != 0:
                        nxt = r.imm32
                else:
                    nxt = r.imm32
            elif o == SF.OP_HALT:
                self.err, self.pc = 0, pc
                return
            elif o == 0x0C:                  # XOP (ISA v1.2/v1.3)
                self.xop(r)
            pc = nxt

    # ------------------------------------------------------------------
    def validate(self, r, nrec):
        """Mirror of seq_unit's one-cycle decode check; returns err_code."""
        o, fl, tgt = r.opcode, r.flags, r.target
        ind, hi = fl & 0xF, fl >> 4
        if o in (SF.OP_CSRWR, SF.EXT_LDC):
            if ind not in (0, 1, 2):
                return 0x02
            if ind == 0 and hi:
                return 0x02
            if hi >= 8:
                return 0x03
            if o == SF.OP_CSRWR:
                if (tgt >> 12) > 2:
                    return 0x07
                if (tgt >> 12) == 1 and ((tgt >> 8) & 0xF) >= 4:
                    return 0x05
        elif o == SF.OP_CMD:
            if fl:
                return 0x04
            if tgt >> 12:
                return 0x07
        elif o in (SF.OP_MOVX, SF.OP_MVGO):
            if ind:
                return 0x02
            if hi >= 4:
                return 0x05
        elif o == SF.OP_MOVY:
            if ind not in (0, 1, 2):
                return 0x02
            if ind == 0 and (fl >> 5):
                return 0x02
            if (tgt & 0xF) >= 4:
                return 0x05
            if tgt >> 4:
                return 0x06
        elif o == SF.OP_EMB:
            if fl:
                return 0x04
        elif o == SF.OP_AMAXL:
            if fl or tgt or r.imm32 or r.addr_lo or r.len_or_addr_hi:
                return 0x06
        elif o == SF.OP_JMP:
            if fl not in (0, 1):
                return 0x04
            if r.imm32 >= nrec:
                return 0x08
        elif o in (SF.OP_FENCE, SF.OP_HALT):
            if fl or tgt or r.imm32 or r.addr_lo or r.len_or_addr_hi:
                return 0x06
        elif o == 0x0C:
            if fl:
                return 0x04
            if tgt >= 8:
                return 0x03
            if ((r.imm32 >> 8) & 3) == 3 or ((r.imm32 >> 10) & 3) == 3:
                return 0x0A
        else:
            return 0x01
        return 0

    # ------------------------------------------------------------------
    def xop(self, r):
        imm = r.imm32
        a, b = imm & 7, (imm >> 4) & 7
        s1, s2 = (imm >> 8) & 3, (imm >> 10) & 3
        simm = (imm >> 14) & 0x3FFFF
        if simm & (1 << 17):
            simm -= (1 << 18)
        t = 0
        if s1 == 1:
            t += self.xv(a)
        elif s1 == 2:
            t -= self.xv(a)
        if s2 == 1:
            t += self.xv(b)
        elif s2 == 2:
            t -= self.xv(b)
        self.xrf_writethrough(r.target & 7, t + simm)

    # ------------------------------------------------------------------
    def movx(self, r):
        c, src, n = r.chan, r.addr_lo & 0x3FFF, r.len_or_addr_hi
        self.W(LAYER + L_SPTR, src)
        self.W(MV(c) + MV_XPTR, 0)
        self.mv[c]["xsum"] = 0
        self.sptr = src
        acc, idx = 0, 0
        for i in range(n):
            self.R(LAYER + L_SWIN)
            byte = int(self.mem[src + i]) & 0xFF
            acc |= byte << (8 * idx)
            idx += 1
            if idx == 4 or i == n - 1:
                self.W(MV(c) + MV_XWIN, acc)
                self.mv[c]["xsum"] = (self.mv[c]["xsum"] + acc) & 0xFFFFFFFF
                acc, idx = 0, 0
        self.sptr = (src + n) & 0x3FFF
        # the trailing STATUS read (xfifo_ovfl check) is a poll -> filtered

    def mvgo(self, r):
        c = r.chan
        wb = ((r.len_or_addr_hi & 0xFF) << 32) | r.addr_lo
        beats = r.len_or_addr_hi >> 8
        self.W(MV(c) + MV_WBLO, wb & 0xFFFFFFFF)
        self.W(MV(c) + MV_WBHI, (wb >> 32) & 0x3)
        self.W(MV(c) + MV_BEATS, beats)
        self.W(MV(c) + MV_SHAPE, r.imm32)
        self.W(MV(c) + MV_CTRL, 1)
        self.mv[c]["wblo"] = wb & 0xFFFFFFC0
        self.mv[c]["shape"] = r.imm32
        self.mv[c]["seed"] = (r.imm32 ^ (wb & 0xFFFFFFC0)
                              ^ self.mv[c]["xsum"]) & 0xFFFFFFFF
        if r.target & 1:
            self.pend[c] = True

    def movy(self, r):
        c, dst, n = r.chan, r.addr_lo & 0x3FFF, r.len_or_addr_hi
        sh = SF.resolve_imm(r, self.xlist())
        self.W(MV(c) + MV_RESPTR, 0)
        self.W(LAYER + L_SPTR, dst)
        self.sptr = dst
        for i in range(n):
            self.R(MV(c) + MV_RESDAT)
            y = s32(self.res_word(c, i))
            v = int(SM.rs_s(np.int64(y), int(sh)))
            if r.movy_mode == SF.MOVY_INT16:
                v = int(SM.clip16(v))
                self.W(LAYER + L_SWIN, v & 0xFFFF)
                self.swrite(self.sptr, v)
                self.sptr += 1
            else:
                v = max(-(1 << 31), min((1 << 31) - 1, v))
                self.W(LAYER + L_SWIN, v & 0xFFFF)
                self.swrite(self.sptr, v & 0xFFFF)
                self.sptr += 1
                self.W(LAYER + L_SWIN, (v >> 16) & 0xFFFF)
                self.swrite(self.sptr, (v >> 16) & 0xFFFF)
                self.sptr += 1

    def _bulk(self, dst, words):
        self.W(LAYER + L_SPTR, dst)
        self.sptr = dst
        for w in words:
            self.W(LAYER + L_SWIN, int(w) & 0xFFFF)
            self.swrite(self.sptr, int(w) & 0xFFFF)
            self.sptr += 1

    def bulk_ldc(self, r):
        a = (r.len_or_addr_hi << 32) | r.addr_lo
        if r.ind == SF.IND_ADD:
            a += self.xv(r.xrf)
        elif r.ind == SF.IND_SUB:
            a -= self.xv(r.xrf)
        off = a - BLOB_BASE
        nw = r.imm32
        w = np.frombuffer(self.blob, dtype="<i2", count=nw, offset=off)
        self._bulk(r.target & 0x3FFF, w)

    def bulk_emb(self, r):
        base = (r.target << 32) | r.imm32
        tok = self.xv(3)
        a = base + tok * EMB_ROW_BYTES
        assert a == EMB_BASE + tok * EMB_ROW_BYTES
        n = r.len_or_addr_hi
        self._bulk(r.addr_lo & 0x3FFF, self.emb[tok][:n])


# ======================================================================
# stream construction
# ======================================================================
def rec(op, flags=0, target=0, imm32=0, addr_lo=0, hi=0):
    return SF.Rec(op, flags, target, imm32, addr_lo, hi)


def csr_layer_w(off, val, ind=0, xi=0):
    return rec(SF.OP_CSRWR, flags=(ind | (xi << 4)),
               target=SF.csr_layer(off), imm32=val & 0xFFFFFFFF)


def xop(dst, a, b, s1, s2, simm):
    imm = (a & 7) | ((b & 7) << 4) | ((s1 & 3) << 8) | ((s2 & 3) << 10) \
          | ((simm & 0x3FFFF) << 14)
    return rec(0x0C, target=dst, imm32=imm)


def alu_cmd(sub, n, srca, srcb, p0, dst):
    """CSRWR ARG0/1/2 + CMD(11), the C-record macro the generators emit."""
    a0 = (sub & 0xF) | ((n & 0x3FFF) << 4)
    a1 = (srca & 0x3FFF) | ((srcb & 0x3FFF) << 14)
    a2 = (p0 & 0x1FFFF) | ((dst & 0x3FFF) << 17)
    return [csr_layer_w(L_ARG0, a0), csr_layer_w(L_ARG1, a1),
            csr_layer_w(L_ARG2, a2), rec(SF.OP_CMD, target=SF.csr_layer(L_CMD),
                                         imm32=11)]


def plain_cmd(op, a0=0, a1=0, a2=0):
    return [csr_layer_w(L_ARG0, a0), csr_layer_w(L_ARG1, a1),
            csr_layer_w(L_ARG2, a2),
            rec(SF.OP_CMD, target=SF.csr_layer(L_CMD), imm32=op)]


def build_core(rng):
    """One stream exercising every opcode, both movers and the loop."""
    blob_words = rng.integers(-32768, 32767, size=4096).astype("<i2")
    blob = blob_words.tobytes()
    emb = rng.integers(-2000, 2000, size=(8, 1024)).astype("<i2")

    R = []
    # --- constants into scratch (LDC), including an XRF-indirected address
    n0 = int(rng.choice([48, 64, 96, 128]))
    R.append(rec(SF.EXT_LDC, target=0x0000, imm32=n0, addr_lo=BLOB_BASE))
    R.append(rec(SF.EXT_LDC, target=0x0040, imm32=int(rng.choice([160, 192,
                 256])), addr_lo=BLOB_BASE + 128))
    # seed XRF[4] with a 64 B-aligned cursor, then use it as an LDC offset
    R.append(rec(SF.OP_CSRWR, target=SF.csr_seq_xrf(4), imm32=128))
    R.append(rec(SF.EXT_LDC, flags=(SF.IND_ADD | (4 << 4)), target=0x0100,
                 imm32=32, addr_lo=BLOB_BASE + 64))

    # --- a DYNQ8 command: retires into XRF[0] = e_x
    R += alu_cmd(0, 256, 0x0000, 0, 3, 0x0400)
    # --- a DYNQ16 command: retires into XRF[1] (cfg_p0[0] = 0)
    R += alu_cmd(12, 128, 0x0000, 0, 0, 0x0600)
    # --- and one into XRF[2] (cfg_p0[0] = 1)
    R += alu_cmd(12, 128, 0x0000, 0, 1, 0x0680)

    # --- the ISA v1.3 attn k_a probe: ALU op 8 with cfg_p0[6] -> XRF[2]
    R += alu_cmd(8, 256, 0x0000, 0, 64 | 9, 0x0500)

    # --- XOP algebra: XRF[5] = XRF[0] - XRF[1] + simm  (the A2/A3 pattern)
    R.append(xop(5, 0, 1, 1, 2, 7))
    R.append(xop(6, 5, 3, 2, 0, -3))

    # --- an indirected CSRWR (imm + XRF[0]) and one with IND_SUB
    R.append(csr_layer_w(L_ARG1, 0x1000, ind=SF.IND_ADD, xi=0))
    R.append(csr_layer_w(L_ARG1, 0x2000, ind=SF.IND_SUB, xi=5))

    # --- a couple of ordinary commands
    R += plain_cmd(1, 0x0000_0345, 0x0011_0022, 0)
    R += plain_cmd(6, 0x0000_1234, 0x0055_0066, 0)

    # --- MOVX / MVGO / MOVY: two channels, both MOVY modes, one with the
    #     A2 "shift = imm - XRF[0]" indirection.  Seed-varied.
    chans = list(rng.permutation(4)[:2])
    for j, c in enumerate(chans):
        c = int(c)
        xlen = int(rng.choice([16, 32, 64, 96, 128]))
        ylen = int(rng.choice([8, 12, 16, 24, 40]))
        mode = SF.MOVY_INT16 if j == 0 else SF.MOVY_PAIRS32
        sh = int(rng.integers(-2, 12))
        R.append(rec(SF.OP_MOVX, flags=(c << 4), addr_lo=0x0000, hi=xlen))
        R.append(rec(SF.OP_MVGO, flags=(c << 4), imm32=0x0001_8008,
                     addr_lo=0x0002_0000 + 0x1000 * c, hi=(64 << 8) | 0))
        fl = mode << 4
        if j == 1:
            fl |= SF.IND_SUB | (0 << 5)      # shift = imm - XRF[0]  (A2)
        R.append(rec(SF.OP_MOVY, flags=fl, target=c, imm32=sh,
                     addr_lo=0x0800 + 0x100 * c, hi=ylen))
    R.append(rec(SF.OP_FENCE))

    # --- AMAX32 command then AMAXL: token -> XRF[3] + OUT FIFO
    R += alu_cmd(10, 512, 0x0000, 0, 1, 0x0700)
    R.append(rec(SF.OP_AMAXL))
    # --- pick a small token id, then EMB that row
    R.append(rec(SF.OP_CSRWR, target=SF.csr_seq_xrf(3), imm32=5))
    R.append(rec(SF.OP_EMB, imm32=EMB_BASE, addr_lo=0x0C00, hi=256))

    # --- decode loop: TCNT_SEQ = 3, body = the next few records
    ntok = int(rng.integers(2, 5))
    R.append(rec(SF.OP_CSRWR, target=SF.CSR_SEQ_TCNT, imm32=ntok))
    body = len(R)
    R += alu_cmd(0, 64, 0x0000, 0, 2, 0x0900)
    R.append(xop(7, 7, 0, 1, 1, 1))
    lc = int(rng.integers(0, 4))
    R.append(rec(SF.OP_MOVX, flags=(lc << 4), addr_lo=0x0040, hi=16))
    R.append(rec(SF.OP_MVGO, flags=(lc << 4), imm32=0x0000_4004,
                 addr_lo=0x0004_0000, hi=(16 << 8) | 0))
    R.append(rec(SF.OP_MOVY, flags=(SF.MOVY_INT16 << 4), target=lc,
                 imm32=int(rng.integers(0, 6)), addr_lo=0x0A00, hi=12))
    R.append(rec(SF.OP_AMAXL))
    R.append(rec(SF.OP_JMP, flags=SF.JMP_TCNT, imm32=body))

    R.append(rec(SF.OP_HALT))
    return R, blob, emb


def build_errs():
    """Tiny streams whose FIRST record is illegal, one per error class."""
    out = {}
    out["op"] = ([rec(0x7F), rec(SF.OP_HALT)], 0x01)
    out["ind"] = ([rec(SF.OP_MOVX, flags=SF.IND_ADD | (1 << 4), hi=4),
                   rec(SF.OP_HALT)], 0x02)
    out["chan"] = ([rec(SF.OP_MVGO, flags=(5 << 4)), rec(SF.OP_HALT)], 0x05)
    out["jmp"] = ([rec(SF.OP_JMP, imm32=99), rec(SF.OP_HALT)], 0x08)
    out["xopsgn"] = ([xop(1, 0, 1, 3, 0, 0), rec(SF.OP_HALT)], 0x0A)
    out["csrsp"] = ([rec(SF.OP_CSRWR, target=0x3000, imm32=1),
                     rec(SF.OP_HALT)], 0x07)
    out["rsvd"] = ([rec(SF.OP_AMAXL, imm32=1), rec(SF.OP_HALT)], 0x06)
    return out


# ======================================================================
# emission
# ======================================================================
def write_ddr_hex(path, regions):
    """regions: [(byte_base, bytes)] -> sparse 128-bit @word-index hex."""
    with open(path, "w") as f:
        for base, data in regions:
            assert base % 16 == 0
            w0 = (base & 0xFFFFF) >> 4
            pad = (-len(data)) % 16
            d = data + b"\x00" * pad
            f.write(f"@{w0:x}\n")
            for i in range(0, len(d), 16):
                chunk = d[i:i + 16]
                f.write("".join(f"{b:02x}" for b in reversed(chunk)) + "\n")


def emit(prefix, recs, blob, emb, expect_err=None):
    stream = SF.pack_stream(recs)
    if expect_err is None:
        SF.validate_stream(recs)            # must be ISA-legal
    m = Model(blob, emb)
    m.run(recs)
    if expect_err is not None:
        assert m.err == expect_err, \
            f"{prefix}: model err {m.err:#04x}, expected {expect_err:#04x}"

    write_ddr_hex(prefix + ".ddr.hex",
                  [(STREAM_BASE, stream), (BLOB_BASE, blob),
                   (EMB_BASE, emb.tobytes())])
    for name, lst in ((".wtr", m.wtr), (".sb.wtr", m.wtr_sb)):
        with open(prefix + name, "w") as f:
            for a, d in lst:
                f.write(f"{a:08x} {d:08x}\n")
    for name, lst in ((".rtr", m.rtr), (".sb.rtr", m.rtr_sb)):
        with open(prefix + name, "w") as f:
            for a in lst:
                f.write(f"{a:08x}\n")
    with open(prefix + ".exp", "w") as f:
        f.write(f"NREC {len(recs)}\n")
        f.write(f"ERR {m.err}\n")
        f.write(f"PC {m.pc}\n")
        for i in range(8):
            f.write(f"XRF {i} {m.xrf[i] & 0x3FFFF:05x}\n")
        for t in m.out:
            f.write(f"TOK {t:05x}\n")
        for a in sorted(m.wrote):
            f.write(f"MEM {a:04x} {m.wrote[a]:04x}\n")
        f.write("END\n")
    with open(prefix + ".dis", "w") as f:
        SF.disasm_stream(recs, out=f)
    return m


def build_micro(rng, kind):
    """Single-op micro-benchmarks: they isolate the per-operation cost that
    the rung-1 wall-clock projection multiplies by the model_v2 census."""
    blob = rng.integers(-32768, 32767, size=4096).astype("<i2").tobytes()
    emb = rng.integers(-2000, 2000, size=(8, 1024)).astype("<i2")
    R = []
    if kind == "csrwr":
        # the ARG0/ARG1/ARG2 run that dominates the real stream (69% CSRWR)
        for i in range(2000):
            R.append(csr_layer_w([L_ARG0, L_ARG1, L_ARG2][i % 3], 0x1000 + i))
    elif kind == "movx":
        R.append(rec(SF.EXT_LDC, target=0x0000, imm32=4096,
                     addr_lo=BLOB_BASE))
        R.append(rec(SF.OP_MOVX, flags=0, addr_lo=0x0000, hi=4096))
    elif kind == "movy16":
        R.append(rec(SF.OP_MOVX, flags=0, addr_lo=0x0000, hi=64))
        R.append(rec(SF.OP_MVGO, flags=0, imm32=0x0080_8020,
                     addr_lo=0x0002_0000, hi=(2048 << 8) | 0))
        R.append(rec(SF.OP_MOVY, flags=(SF.MOVY_INT16 << 4), target=0,
                     imm32=6, addr_lo=0x0000, hi=2048))
    elif kind == "movy32":
        R.append(rec(SF.OP_MOVX, flags=0, addr_lo=0x0000, hi=64))
        R.append(rec(SF.OP_MVGO, flags=0, imm32=0x0080_8020,
                     addr_lo=0x0002_0000, hi=(2048 << 8) | 0))
        R.append(rec(SF.OP_MOVY, flags=0, target=0, imm32=6,
                     addr_lo=0x0000, hi=2048))
    elif kind == "ldc":
        R.append(rec(SF.EXT_LDC, target=0x0000, imm32=4096,
                     addr_lo=BLOB_BASE))
    elif kind == "cmd":
        for i in range(200):
            R += alu_cmd(2, 64, 0x0000, 0, 0, 0x0400)
    else:
        raise ValueError(kind)
    R.append(rec(SF.OP_HALT))
    return R, blob, emb


def build_offifo(rng, ntok):
    """RUNG 4 S6 (docs/RUNG4_SPEC.md): a stream of `ntok` back-to-back
    (AMAX32 command, AMAXL) pairs and nothing else.

    The layer stub derives AMAXI from its retiring command counter, so every
    token is distinct — which is what makes a dropped or duplicated entry
    visible.  Three depths matter:
        24  > the OLD depth of 16   (tokens 17..24 used to be dropped)
        64  == the NEW depth        (fills it exactly, of_ovf must stay 0)
        80  >  the NEW depth        (of_ovf sticky 1, first 64 intact)
    """
    blob = rng.integers(-32768, 32767, size=4096).astype("<i2").tobytes()
    emb = rng.integers(-2000, 2000, size=(8, 1024)).astype("<i2")
    R = []
    for i in range(ntok):
        # len 8 keeps the stub command short; p0[0]=1 (fresh) on the first
        R += alu_cmd(10, 8, 0x0000, 0, 1 if i == 0 else 0, 0x0700)
        R.append(rec(SF.OP_AMAXL))
    R.append(rec(SF.OP_HALT))
    return R, blob, emb


OFIFO_N = (24, 64, 80)

MICROS = ("csrwr", "cmd", "movx", "movy16", "movy32", "ldc")


def main():
    if len(sys.argv) < 3:
        sys.exit("usage: gen_seq_vectors.py <outdir> <seed>")
    outdir, seed = sys.argv[1], int(sys.argv[2])
    os.makedirs(outdir, exist_ok=True)
    rng = np.random.default_rng(1000 + seed)

    recs, blob, emb = build_core(rng)
    m = emit(os.path.join(outdir, f"seq_u_s{seed}"), recs, blob, emb)
    print(f"seq_u_s{seed}: {len(recs)} records, "
          f"{len(m.wtr)} writes, {len(m.rtr)} reads "
          f"({len(m.rtr_sb)} with the XRF sideband), "
          f"{len(m.wrote)} scratch words, {len(m.out)} tokens")

    if seed == 1:
        for k in MICROS:
            mr, mb, me = build_micro(np.random.default_rng(77), k)
            mm = emit(os.path.join(outdir, f"seq_m_{k}"), mr, mb, me)
            print(f"seq_m_{k}: {len(mr)} records, {len(mm.wtr)} writes, "
                  f"{len(mm.rtr)} reads")
        for n in OFIFO_N:
            fr, fb, fe = build_offifo(np.random.default_rng(4200 + n), n)
            fm = emit(os.path.join(outdir, f"seq_f_of{n}"), fr, fb, fe)
            print(f"seq_f_of{n}: {len(fr)} records, {len(fm.out)} tokens")
        for name, (er, code) in build_errs().items():
            emit(os.path.join(outdir, f"seq_e_{name}"), er, blob, emb,
                 expect_err=code)
            print(f"seq_e_{name}: expects err_code {code:#04x}")


if __name__ == "__main__":
    main()
