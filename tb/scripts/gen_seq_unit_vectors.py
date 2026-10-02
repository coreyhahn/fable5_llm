#!/usr/bin/env python3
"""gen_seq_unit_vectors.py — golden vectors for tb/tb_seq_unit.sv.

(The name in this docstring said `gen_seq_vectors.py` until 2026-08-31 —
a stale self-reference left by a rename.  That other file was a dead
near-copy and G2a deleted it, so the name now points at nothing; see
`docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md` D-DEAD.)

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
    <prefix>.fpolls    SR3 (SEQ_ISA v2.3 B17.1): per FENCE record index, the
                       set of channels it MAY poll and the set it MUST poll
                       at least once ("FENCE <idx> <may> <must>", 4-bit hex
                       masks).  The .rtr excludes STATUS polls, so a FENCE's
                       channel mask is invisible to it; the TB counts polls
                       per channel, bucketed by the DUT's record index.
    <prefix>.caps.hex  SR3: the SEQ_CAPS word (SEQ 0x64) the RTL under test
                       must read back = HW.seq_caps_word(BUILD_CAPS) — the
                       ONE definition in sw/hwmap.py, never re-typed here.
    <prefix>.xwa       SR12 (SEQ_ISA v2.3 B17.2): the mvchan WINDOW ADDRESS of
                       every MOVX / MOVY that moves data, in issue order:
                       "X <chan> <start word> <words>" per MOVX, "Y <chan>
                       <start row> <rows>" per MOVY.  The .wtr/.rtr
                       canonicalise each burst beat to one CSR address, so
                       the XWIN start word and the RES start row are
                       invisible to them; the TB checks the address of every
                       XWIN write beat and every RES read beat against this.
    <prefix>.dis      disassembly (debug only)

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

Usage:  gen_seq_unit_vectors.py <outdir> <seed>
"""
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_REF = os.path.normpath(os.path.join(_HERE, "..", "..", "ref"))
_SW = os.path.normpath(os.path.join(_HERE, "..", "..", "sw"))
for _p in (_REF, _SW):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import gen_layer_script as GLS                                # noqa: E402
import seq_format as SF                                       # noqa: E402
import seq_model as SM                                        # noqa: E402
import hwmap as HW                                            # noqa: E402

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
# R-b: the EMB row size is a RUNTIME CSR (seq_unit's EMBLOG2 at SEQ 0x60),
# not a localparam.  G3.4 (spec 5.3 S8) moved the RESET to 13 = 8192 B =
# H 4096, the 9B row, and this generator moves with it: the feasibility
# census called this site out as the live one that "never learned to program
# EMBLOG2 from the artifact", so the TB set only ever proved EMBLOG2 11.
# It now proves the value the hardware actually resets to, and the vectors'
# EMB address math is derived from this constant rather than assuming it.
# (`tb_seq_unit.sv`'s exp_emblog2 default and the CSR write mirror it, and
# `tb_seq_guard`'s +emblog2bad= cases bracket the SAME [8,13] range.)
EMB_ROW_LOG2  = 13
EMB_ROW_BYTES = 1 << EMB_ROW_LOG2

# G3.4 fix round 1 (spec 5.4 S9): every MVGO SHAPE immediate below is
# packed by `HW.shape_word(..., isa=HW.SHAPE_ISA_9B)` instead of being a
# hand-written hex constant.  The constants were isa=1 (build_034/035)
# words -- `{w8, g64, nrows[27:12], sh[11:6], ng[5:0]}` -- and under the
# v2.0 layout this RTL decodes, `{ng[28:22], nrows[21:6], sh[5:0]}`, all
# seven of them decoded to ng = 0.  That was invisible while nothing
# checked it; `seq_unit`'s S9 envelope check refuses ng = 0, so the words
# now have to say what they mean.  The (nrows, sh, ng) triples below are
# exactly the ones the old constants encoded, so these are the same
# streams with a SHAPE word that is true.
def _shape(nrows, sh, ng):
    return HW.shape_word(nrows, sh, ng, isa=HW.SHAPE_ISA_9B)



# G2a: IMPORTED, not duplicated.  `sw/hwmap.py` is the canonical definition
# of the scratchpad depth; this file used to carry its own copy of the
# literal, and a copy of a constant is a constant that will disagree.  This
# generator only uses it to size its behavioural scratchpad model, so a
# larger value is inert: the stream's addresses come from `ref/seq_format.py`
# and no vector here names a word above the 15-bit ISA range.
SCRATCH_WORDS = HW.SCRATCH_WORDS

# SR3 (SEQ_ISA v2.3 B17.0/B17.1): the capability set of the RTL these
# vectors are golden for.  The R1 RTL (rtl/seq_unit.sv SEQ_CAPS) has
# exactly {"R1"}; the vectors are validated with it (a masked FENCE is
# legal) and the TB's expected SEQ_CAPS word is derived from it through
# hwmap (<prefix>.caps.hex).  A later round that builds R2/R3 widens THIS
# set and nothing else in this file.
# SR12 (B17.2) widened it: the R2 RTL decodes MOVX target[11:0] (the XWIN
# start word) and MOVY target[15:4] (the RES start row) and passes MVGO
# SHAPE bits 29/30 to the mvchan, so the set is {"R1", "R2"}; the vectors
# validate with it (the range and bank-legality rules apply) and caps.hex
# becomes HW.seq_caps_word({"R1", "R2"}).
BUILD_CAPS = frozenset({"R1", "R2", "R3"})   # R3-8: + "R3", B17.3 broadcast

# SR12: the R2 window geometry, from ref/seq_format (itself derived from
# MVGO_MAX_NG and hwmap.RES_DEPTH) — never re-typed here.
XWIN_WORDS = SF.XWIN_WORDS            # 3072
RES_ROWS = SF.RES_ROWS                # 4096


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
    def __init__(self, blob, emb, emb_log2=EMB_ROW_LOG2):
        self.blob = blob                     # bytes at BLOB_BASE
        self.emb = emb                       # np.int16 [rows, 1 << (log2-1)]
        self.emb_log2 = int(emb_log2)        # R-b: EMBLOG2 CSR value
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
        # no-wait MVGO channels.  SR12 (B17.2): None, or the pending
        # stream's RUNNING RANGES (x word lo, hi, RES row lo, hi) — the
        # twin of ref/seq_model.SeqExec.running.
        self.pend = [None] * 4
        self.xwa = []                        # SR12: (kind, chan, start, n)
        # SR3: per FENCE record index -> [may, must] 4-bit channel masks
        # (accumulated over every execution of that record, so a FENCE in
        # a JMP loop is covered too).  may == must in this model: a
        # channel is polled iff it is pending AND in the mask — kept as
        # two sets so the TB's check reads as the contract does.
        self.fpolls = {}
        self.caps = BUILD_CAPS
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
                        self.sptr = val & 0xFFFF        # G3.1: SPTR is 16 b
                    elif off == L_SWIN:
                        self.swrite(self.sptr, val)
                        self.sptr = (self.sptr + 1) & 0xFFFF
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
                self.movx_r3(r)      # R3-8: a broadcast, else movx(r)
            elif o == SF.OP_MVGO:
                self.mvgo_r3(r)      # R3-8: mvgo(r) + the stub xsum reset
            elif o == SF.OP_MOVY:
                self.movy(r)
            elif o == SF.OP_FENCE:
                # SEQ_ISA v2.3 B17.1: target[3:0] is the channel mask, 0 =
                # all four.  Only the pending channels IN the mask are
                # polled and cleared; an unmasked pending channel stays
                # pending (no RTL interlock).  Polls only -> no logged
                # traffic; the poll sets go to <prefix>.fpolls.
                mask = (r.target & 0xF) or 0xF
                hit = 0
                for c in range(4):
                    if self.pend[c] is not None and (mask >> c) & 1:
                        hit |= 1 << c
                        self.pend[c] = None
                fp = self.fpolls.setdefault(pc, [0, 0])
                fp[0] |= hit
                fp[1] |= hit
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
            if hi >= 4 and not _bcast_ok(self, o, hi):  # R3-8: B17.3
                return 0x05
            # G3.4 (spec 5.4 S9): the MVGO SHAPE envelope, mirrored from
            # rtl/seq_unit.sv's E_ENV clause.  Layout is SEQ_ISA v2.0 /
            # G3.3 {spare[31:29], ng[28:22], nrows[21:6], sh[5:0]}, and
            # the bound is matvec_engine's MAX_NG, taken from the ONE
            # place ref/ keeps it.
            if o == SF.OP_MVGO:
                ng = (r.imm32 >> 22) & 0x7F
                if not (1 <= ng <= SF.MVGO_MAX_NG):
                    return 0x0D
            # SR12 (SEQ_ISA v2.3 B17.2, R2): MOVX target[11:0] is the XWIN
            # start word; target[15:12] reserved; start word <= 3071 and
            # start + ceil(len/4) <= 3072, all err 0x06 (E_RSVD).  Without
            # R2 the pre-round RTL IGNORED MOVX target (no check at all).
            # The length is the RTL's 24-bit field.
            if o == SF.OP_MOVX and "R2" in self.caps:
                w0 = tgt & SF.MOVX_WORD_MASK
                nw = SF.movx_words(r.len_or_addr_hi & 0xFFFFFF)
                if (tgt >> 12) or w0 >= XWIN_WORDS or w0 + nw > XWIN_WORDS:
                    return 0x06
        elif o == SF.OP_MOVY:
            if ind not in (0, 1, 2):
                return 0x02
            if ind == 0 and (fl >> 5):
                return 0x02
            if (tgt & 0xF) >= 4:
                return 0x05
            # SR12 (B17.2, R2): target[15:4] is the RES start row, and
            # start row + len <= 4096 (err 0x06).  Without R2 the pre-round
            # rule: target[15:4] reserved (err 0x06).
            if "R2" in self.caps:
                if (tgt >> 4) + (r.len_or_addr_hi & 0xFFFFFF) > RES_ROWS:
                    return 0x06
            elif tgt >> 4:
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
        elif o == SF.OP_FENCE:
            # SEQ_ISA v2.3 B17.1: with R1, target[3:0] is the channel mask
            # and only target[15:4] must be zero; without it, the pre-round
            # all-zero rule (ref/seq_format.validate's twin clause).
            tmask = 0xFFF0 if "R1" in self.caps else 0xFFFF
            if fl or (tgt & tmask) or r.imm32 or r.addr_lo \
                    or r.len_or_addr_hi:
                return 0x06
        elif o == SF.OP_HALT:
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
        # G3.1: scratch addresses are 16 bits, so `addr_lo` is masked to
        # its full 16-bit width (SEQ_ISA v2.0; it was 15 at R-b)
        c, src, n = r.chan, r.addr_lo & 0xFFFF, r.len_or_addr_hi
        # SR12 (B17.2): the XWIN start word.  The XPTR write below stays 0
        # (the burst path carries the word in its address and never reads
        # xptr — rtl/matvec_chan.sv's shim), so the .wtr is unchanged; the
        # address goes to <prefix>.xwa.
        w0 = r.target & SF.MOVX_WORD_MASK
        nw = SF.movx_words(n)
        self.running(c, "MOVX", xr=(w0, w0 + nw))
        if n:
            self.xwa.append(("X", c, w0, nw))
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
        self.sptr = (src + n) & 0xFFFF
        # the trailing STATUS read (xfifo_ovfl check) is a poll -> filtered

    def running(self, c, what, xr=None, rr=None):
        """SR3: the twin of ref/seq_model's RunningChannelError gate.  The
        RTL has NO interlock (SEQ_ISA v2.3 B17.1), so a stream that touches
        a still-pending channel is refused HERE, before a vector exists.

        SR12 (B17.2): RUNNING RANGES, as ref/seq_model.SeqExec keeps them —
        a MVGO is refused on any pending stream (one engine per channel), a
        MOVX only if its XWIN word range `xr` overlaps the pending x range,
        a MOVY only if its RES row range `rr` overlaps the pending RES
        range.  An EMPTY range counts as overlapping (ref/seq_model
        _overlap), so a zero-length access is refused exactly as before."""
        p = self.pend[c]
        if p is None:
            return
        if xr is not None:
            hit = SM._overlap(xr[0], xr[1], p[0], p[1])
        elif rr is not None:
            hit = SM._overlap(rr[0], rr[1], p[2], p[3])
        else:
            hit = True
        if hit:
            raise SM.RunningChannelError(
                f"{what} on channel {c} while its no-wait MVGO is pending "
                f"(no FENCE covering it yet; running ranges {p})")

    def mvgo(self, r):
        c = r.chan
        self.running(c, "MVGO")
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
            # SR12 (B17.2): what the pending stream still reads (x words
            # 1536*XBANK .. +32*ng) and writes (RES rows 2048*RBANK ..
            # +nrows) — ref/seq_model's `running` tuple.  The stub keeps
            # SHAPE opaque (bits 29/30 only reach its result seed), so the
            # banks matter here only to the hazard twin.
            ng = (r.imm32 >> 22) & 0x7F
            nrows = (r.imm32 >> 6) & 0xFFFF
            xw0 = SF.XBANK_WORD * ((r.imm32 >> 29) & 1)
            row0 = SF.RBANK_ROW * ((r.imm32 >> 30) & 1)
            self.pend[c] = (xw0, xw0 + SF.XWIN_LINE_WORDS * max(ng, 1),
                            row0, row0 + max(nrows, 1))

    def movy(self, r):
        c, dst, n = r.chan, r.addr_lo & 0xFFFF, r.len_or_addr_hi
        # SR12 (B17.2): the RES start row.  seq_movers writes it to RES_PTR
        # (AXI-Lite, as the row-0 write always was) and carries it in the
        # burst read address; the stub's RES word is a function of the ROW
        # ADDRESS, so a wrong start row moves every value MOVY writes.
        row0 = r.target >> 4
        self.running(c, "MOVY", rr=(row0, row0 + n))
        if n:
            self.xwa.append(("Y", c, row0, n))
        sh = SF.resolve_imm(r, self.xlist())
        self.W(MV(c) + MV_RESPTR, row0)
        self.W(LAYER + L_SPTR, dst)
        self.sptr = dst
        for i in range(n):
            self.R(MV(c) + MV_RESDAT)
            y = s32(self.res_word(c, row0 + i))
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
        self._bulk(r.target & 0xFFFF, w)     # G3.1: LDC target[15:0]

    def bulk_emb(self, r):
        base = (r.target << 32) | r.imm32
        tok = self.xv(3)
        a = base + (tok << self.emb_log2)    # R-b: shift by the EMBLOG2 CSR
        assert a == EMB_BASE + tok * (1 << self.emb_log2)
        n = r.len_or_addr_hi
        self._bulk(r.addr_lo & 0xFFFF, self.emb[tok][:n])


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
    """CSRWR ARG0/1/2 + CMD(11), the C-record macro the generators emit.

    G3.1: this packer was 14-BIT with no bit-14 scatter at all — it never
    learned R-b's 15th address bit, so the live seq_unit vectors never
    exercised a high-half ALU address (spec 7.6 C).  At SEQ_ISA v2.0 it does
    not merely need widening: it encoded a layout that no longer exists, so
    it is REWRITTEN onto the canonical helpers rather than patched, and
    `alu_hi_case` below closes the gap it left instead of moving it."""
    a0 = GLS.enc_alu_a0(sub, n, p0)
    a1 = GLS.enc_a1(srca, srcb)
    a2 = GLS.enc_alu_a2(p0, dst)
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
    emb = rng.integers(-2000, 2000,
                       size=(8, EMB_ROW_BYTES // 2)).astype("<i2")

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

    # --- G3.1 DIRECTED HIGH-HALF CASE.  The packer above was 14-bit with no
    #     bit-14 scatter at all, so the live seq_unit vectors NEVER named a
    #     scratch word above 16383 and the address path went unexercised
    #     (spec 7.6 C).  At SEQ_ISA v2.0 the gap is CLOSED rather than moved:
    #     srca LOW / dst HIGH, so a dropped top half cannot pass by folding
    #     both operands together, and the length uses the 14th count bit.
    R += alu_cmd(2, 12288, 0x0100, 0, 0, 0xF800)
    #     ...and an LDC whose DESTINATION is in the top half, which is what
    #     drives seq_unit's `bulk_dst` and seq_movers' `scrbaddr`.
    R.append(rec(SF.EXT_LDC, target=0xF000, imm32=32, addr_lo=BLOB_BASE + 64))

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
        R.append(rec(SF.OP_MVGO, flags=(c << 4), imm32=_shape(24, 0, 8),
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
    R.append(rec(SF.OP_MVGO, flags=(lc << 4), imm32=_shape(4, 0, 4),
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
    # G3.4 (spec 5.4 S9): the MVGO SHAPE envelope.  ng = 0 and ng = 97 are
    # the two sides of `1 <= ng <= 96`, and each is paired with its LEGAL
    # NEIGHBOUR in the SAME stream -- a legal MVGO runs first, so a stream
    # that halted for any other reason cannot be mistaken for the refusal.
    # 97 is packed by hand because HW.shape_word refuses it on the EMIT
    # side, which is the first of the two lines of defence and is exactly
    # what this vector must get past to test the second.
    out["env0"] = ([rec(SF.OP_MOVX, flags=0, addr_lo=0x0000, hi=64),
                    rec(SF.OP_MVGO, flags=0, imm32=_shape(24, 0, 8),
                        addr_lo=0x0002_0000, hi=(24 << 8) | 0),
                    rec(SF.OP_MVGO, flags=0, imm32=(24 << 6),  # ng = 0
                        addr_lo=0x0002_0000, hi=(24 << 8) | 0),
                    rec(SF.OP_HALT)], 0x0D)
    out["env97"] = ([rec(SF.OP_MOVX, flags=0, addr_lo=0x0000, hi=64),
                     rec(SF.OP_MVGO, flags=0, imm32=_shape(24, 0, 96),
                         addr_lo=0x0002_0000, hi=(24 << 8) | 0),
                     rec(SF.OP_MVGO, flags=0, imm32=(97 << 22) | (24 << 6),
                         addr_lo=0x0002_0000, hi=(24 << 8) | 0),
                     rec(SF.OP_HALT)], 0x0D)
    # SR3 (SEQ_ISA v2.3 B17.1): the FENCE mask admits target[3:0] ONLY.
    # Each refusal follows LEGAL records (a no-wait MVGO drained by a
    # mask-0 FENCE) so it cannot be an early halt; the TB checks the
    # faulting PC as well as the code.  fmrsvd: target[15:4] != 0.
    # fmimm: a legal mask WITH a non-zero imm32 (the other fields stay
    # checked under a mask).  haltmask: HALT keeps the all-zero rule — a
    # "mask" on HALT is refused.
    legal = [rec(SF.OP_MOVX, flags=0, addr_lo=0x0000, hi=64),
             rec(SF.OP_MVGO, flags=0, target=1, imm32=_shape(24, 0, 8),
                 addr_lo=0x0002_0000, hi=(24 << 8) | 0),
             rec(SF.OP_FENCE)]
    out["fmrsvd"] = (legal + [rec(SF.OP_FENCE, target=0x0010),
                              rec(SF.OP_HALT)], 0x06)
    out["fmimm"] = (legal + [rec(SF.OP_FENCE, target=0x0001, imm32=1),
                             rec(SF.OP_HALT)], 0x06)
    out["haltmask"] = (legal + [rec(SF.OP_HALT, target=0x0001),
                                rec(SF.OP_HALT)], 0x06)
    # SR12 (SEQ_ISA v2.3 B17.2): the two R2 range rules and MOVX's reserved
    # nibble, all err 0x06, each after LEGAL records — and where the rule
    # has an edge, the LEGAL edge runs first in the same stream, so the
    # refusal is proved to sit exactly one past it.  mxrsvd: MOVX
    # target[15:12] != 0.  mxstart: start word 3072 (> 3071) with len 0 —
    # the start rule alone.  mxrange: 3000 + 72 words = 3072 runs, 3000 +
    # 73 (a ragged 289 B) is refused.  myrange: a RBANK result (rows
    # 2048..4095), MOVY 4000 + 96 = 4096 runs, 4000 + 97 is refused.
    out["mxrsvd"] = (legal + [rec(SF.OP_MOVX, flags=0, target=0x1000,
                                  addr_lo=0x0000, hi=64),
                              rec(SF.OP_HALT)], 0x06)
    out["mxstart"] = (legal + [rec(SF.OP_MOVX, flags=0, target=XWIN_WORDS,
                                   addr_lo=0x0000, hi=0),
                               rec(SF.OP_HALT)], 0x06)
    out["mxrange"] = (legal + [rec(SF.OP_MOVX, flags=0, target=3000,
                                   addr_lo=0x0000, hi=288),
                               rec(SF.OP_MOVX, flags=0, target=3000,
                                   addr_lo=0x0000, hi=289),
                               rec(SF.OP_HALT)], 0x06)
    out["myrange"] = (legal + [rec(SF.OP_MVGO, flags=0,
                                   imm32=_shape(2048, 0, 8) | SF.SHAPE_RBANK,
                                   addr_lo=0x0002_0000, hi=(24 << 8) | 0),
                               rec(SF.OP_MOVY, flags=(SF.MOVY_INT16 << 4),
                                   target=(4000 << 4) | 0, imm32=3,
                                   addr_lo=0x1000, hi=96),
                               rec(SF.OP_MOVY, flags=(SF.MOVY_INT16 << 4),
                                   target=(4000 << 4) | 0, imm32=3,
                                   addr_lo=0x1000, hi=97),
                               rec(SF.OP_HALT)], 0x06)
    return out


def build_banks(rng, perm=(0, 1, 2, 3)):
    """SR12 directed case: the R2 bank fields (SEQ_ISA v2.3 B17.2).

    What seq_unit does with them is PLUMBING — MOVX target[11:0] becomes
    the XWIN burst's start word, MOVY target[15:4] the RES burst's start
    row (and the RES_PTR write), SHAPE bits 29/30 ride to the mvchan in
    the SHAPE write.  The bank SEMANTICS (x from line 48, rows at 2048) are
    the engine's and are proved in tb_matvec / tb_matvec_chan.  Checked
    here: every XWIN / RES beat address against <prefix>.xwa, every value
    through the stub's row-addressed RES words, SHAPE through the .wtr.

    Channel roles (renamed per seed by `perm`, like build_fmask):
      a  the overlap R2 exists for: a bank-0 x feeding a RBANK result, a
         bank-1 x feeding a NO-WAIT XBANK stream into RES bank 0 — and,
         WHILE it runs, a MOVY of the other RES half and a MOVX into the
         other XWIN bank (legal: the running ranges do not overlap), then
         a masked FENCE and drains of both halves (one at an odd row)
      b  the edges: bank 1 filled exactly (word 1536 + 1536 words = 3072),
         an XBANK MVGO at ng 48 (x lines 48..95) with RBANK nrows 2048
         (rows 2048..4095), a MOVY of the LAST row and one ending at 4096
      c  start words the banks never use: an odd word with a ragged tail,
         a run across the 4 KiB page at word 1024 (the burst splitter),
         the last word 3071; then an ordinary bank-0 MVGO / MOVY at row 7
    """
    blob = rng.integers(-32768, 32767, size=8192).astype("<i2").tobytes()
    emb = rng.integers(-2000, 2000,
                       size=(8, EMB_ROW_BYTES // 2)).astype("<i2")
    XB, RB = SF.SHAPE_XBANK, SF.SHAPE_RBANK
    W1, R1 = SF.XBANK_WORD, SF.RBANK_ROW
    a, b, c = perm[0], perm[1], perm[2]

    def movx(ch, w0, src, n):
        return rec(SF.OP_MOVX, flags=(ch << 4), target=w0, addr_lo=src, hi=n)

    def mvgo(ch, shape, nowait=0):
        return rec(SF.OP_MVGO, flags=(ch << 4), target=nowait, imm32=shape,
                   addr_lo=0x0002_0000 + 0x1000 * ch, hi=(24 << 8) | 0)

    def movy(ch, row0, dst, n, mode=SF.MOVY_INT16, sh=3):
        return rec(SF.OP_MOVY, flags=(mode << 4), target=(row0 << 4) | ch,
                   imm32=sh, addr_lo=dst, hi=n)

    # 6144 words, so channel b's 6144-element MOVX reads LDC'd data only
    R = [rec(SF.EXT_LDC, target=0x0000, imm32=6144, addr_lo=BLOB_BASE)]
    # --- a: bank-0 x -> RES bank 1 (waits); bank-1 x -> no-wait XBANK
    R += [movx(a, 0, 0x000, 256), mvgo(a, _shape(24, 0, 2) | RB)]
    R += [movx(a, W1, 0x100, 256), mvgo(a, _shape(24, 0, 2) | XB, nowait=1)]
    #     ...while it runs: the OTHER RES half and the OTHER XWIN bank
    R += [movy(a, R1, 0x2000, 24), movx(a, 0, 0x200, 256)]
    R += [rec(SF.OP_FENCE, target=1 << a),
          movy(a, 0, 0x2100, 24, mode=SF.MOVY_PAIRS32),
          movy(a, R1 + 2, 0x2200, 5)]
    # --- b: the edges
    R += [movx(b, W1, 0x000, 6144),
          mvgo(b, _shape(2048, 0, 48) | XB | RB),
          movy(b, R1 + 2047, 0x3000, 1),
          movy(b, R1 + 1000, 0x3100, 1048)]
    # --- c: odd start words
    R += [movx(c, 5, 0x400, 13), movx(c, 1020, 0x400, 40),
          movx(c, XWIN_WORDS - 1, 0x400, 4),
          movx(c, 0, 0x000, 128), mvgo(c, _shape(8, 0, 1)),
          movy(c, 7, 0x3800, 1)]
    R.append(rec(SF.OP_FENCE))
    R.append(rec(SF.OP_HALT))
    return R, blob, emb


def build_fmask(rng, perm=(0, 1, 2, 3)):
    """SR3 directed case: the FENCE channel mask (SEQ_ISA v2.3 B17.1).

    No-wait MVGOs leave channels pending; each masked FENCE must poll
    EXACTLY the pending channels in its mask (the TB counts polls per
    channel per record against <prefix>.fpolls) and leave the others
    pending.  Covered: a single-channel mask, a two-channel mask, mask 0 =
    all four, a mask naming a channel that is NOT pending (no poll, no
    hang), and a mask that SKIPS a pending channel which a later mask-0
    FENCE must then poll.  Every MOVY/MOVX/MVGO touches only a drained
    channel — the Model's RunningChannelError twin refuses anything else.

    `perm` renames the channels (logical channel k -> physical perm[k], the
    masks renamed with them), so the four seeds put every mask bit in every
    role: seed 1 is the identity (the plan's case), seeds 2..4 permute."""
    blob = rng.integers(-32768, 32767, size=4096).astype("<i2").tobytes()
    emb = rng.integers(-2000, 2000,
                       size=(8, EMB_ROW_BYTES // 2)).astype("<i2")

    def pm(m):
        return sum(1 << perm[k] for k in range(4) if (m >> k) & 1)

    def go(c, xoff):
        c = perm[c]
        return [rec(SF.OP_MOVX, flags=(c << 4), addr_lo=xoff, hi=64),
                rec(SF.OP_MVGO, flags=(c << 4), target=1,       # no-wait
                    imm32=_shape(24, 0, 8),
                    addr_lo=0x0002_0000 + 0x1000 * c, hi=(24 << 8) | 0)]

    def movy(c, dst):
        c = perm[c]
        return rec(SF.OP_MOVY, flags=(SF.MOVY_INT16 << 4), target=c,
                   imm32=3, addr_lo=dst, hi=12)

    R = [rec(SF.EXT_LDC, target=0x0000, imm32=1024, addr_lo=BLOB_BASE)]
    R += go(0, 0x000) + go(1, 0x040) + go(2, 0x080)
    R.append(rec(SF.OP_FENCE, target=pm(0b0010)))        # drains 1 only
    R.append(movy(1, 0x1000))                        # legal: 1 drained
    R.append(rec(SF.OP_FENCE, target=pm(0b0101)))        # drains 0 and 2
    R.append(movy(0, 0x1100))
    R.append(movy(2, 0x1200))
    R += go(3, 0x0C0)
    R.append(rec(SF.OP_FENCE))                       # mask 0: all -> 3
    R.append(movy(3, 0x1300))
    R += go(1, 0x100)
    R.append(rec(SF.OP_FENCE, target=pm(0b1000)))        # 3 NOT pending, 1
    #                                                  pending but unmasked
    R += go(2, 0x140)
    R.append(rec(SF.OP_FENCE, target=pm(0b0100)))        # drains 2, skips 1
    R.append(movy(2, 0x1400))
    R.append(rec(SF.OP_FENCE))                       # mask 0 -> must poll 1
    R.append(movy(1, 0x1500))
    R.append(rec(SF.OP_HALT))
    return R, blob, emb


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


def emit(prefix, recs, blob, emb, expect_err=None, emb_log2=EMB_ROW_LOG2):
    stream = SF.pack_stream(recs)
    if expect_err is None:
        # G3.4: these are v2.0 streams, which is what lets the MVGO
        # SHAPE envelope be checked at all -- see ref/seq_format's
        # SHAPE_ISA_9B note.
        # SR3: validated against the capability set of the RTL under test
        # (BUILD_CAPS, {"R1"} at SR3, {"R1", "R2"} since SR12): a masked
        # FENCE and the B17.2 bank fields are legal under their range and
        # bank-legality rules, anything else outside today's rules is
        # still refused.
        SF.validate_stream(recs, shape_isa=SF.SHAPE_ISA_9B, caps=BUILD_CAPS)
    # the DDR image is a flat dump of `emb`, so a row must be exactly the
    # EMBLOG2 row size or the golden addresses would not line up
    assert emb.shape[1] == (1 << (emb_log2 - 1)), \
        f"{prefix}: emb rows are {emb.shape[1]} words, EMBLOG2 {emb_log2} " \
        f"wants {1 << (emb_log2 - 1)}"
    m = Model(blob, emb, emb_log2=emb_log2)
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
        # R-b: what the TB must write into the EMBLOG2 CSR before START
        f.write(f"EMBLOG2 {emb_log2}\n")
        for i in range(8):
            f.write(f"XRF {i} {m.xrf[i] & 0x3FFFF:05x}\n")
        for t in m.out:
            f.write(f"TOK {t:05x}\n")
        for a in sorted(m.wrote):
            f.write(f"MEM {a:04x} {m.wrote[a]:04x}\n")
        f.write("END\n")
    # SR3: per-FENCE poll sets (the .rtr cannot see polls) and the SEQ_CAPS
    # word the RTL must read back — from hwmap, the one definition.
    with open(prefix + ".fpolls", "w") as f:
        for idx in sorted(m.fpolls):
            may, must = m.fpolls[idx]
            f.write(f"FENCE {idx} {may:x} {must:x}\n")
        f.write("END\n")
    with open(prefix + ".caps.hex", "w") as f:
        f.write(f"{HW.seq_caps_word(BUILD_CAPS):08x}\n")
    # SR12 (B17.2): the XWIN start word / RES start row of every MOVX /
    # MOVY that moved data, in issue order (a NEW side file: every existing
    # golden above is byte-identical to the pre-SR12 generator's).
    with open(prefix + ".xwa", "w") as f:
        for kind, c, s0, n in m.xwa:
            f.write(f"{kind} {c} {s0} {n}\n")
        f.write("END\n")
    with open(prefix + ".dis", "w") as f:
        SF.disasm_stream(recs, out=f)
    return m


def build_micro(rng, kind):
    """Single-op micro-benchmarks: they isolate the per-operation cost that
    the rung-1 wall-clock projection multiplies by the model_v2 census."""
    blob = rng.integers(-32768, 32767, size=4096).astype("<i2").tobytes()
    emb = rng.integers(-2000, 2000,
                       size=(8, EMB_ROW_BYTES // 2)).astype("<i2")
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
        R.append(rec(SF.OP_MVGO, flags=0, imm32=_shape(2056, 0, 32),
                     addr_lo=0x0002_0000, hi=(2048 << 8) | 0))
        R.append(rec(SF.OP_MOVY, flags=(SF.MOVY_INT16 << 4), target=0,
                     imm32=6, addr_lo=0x0000, hi=2048))
    elif kind == "movy32":
        R.append(rec(SF.OP_MOVX, flags=0, addr_lo=0x0000, hi=64))
        R.append(rec(SF.OP_MVGO, flags=0, imm32=_shape(2056, 0, 32),
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


def build_hiaddr(rng):
    """R-b directed case: the SEQ half of the 15-bit widening.

    Nothing in build_core/build_micro ever sets `addr_lo[14]` or
    `target[14]`, so seq_unit's `mv_saddr`/`bulk_dst`/`r_tgt[14:0]` slices
    and seq_movers' `cmd_saddr[14:0]` had no directed vector at all.  This
    stream drives EVERY one of them above word 16383 and golden-checks the
    scratch round trip:

      LDC   target[14] set          -> const blob into scratch 16384+
      EMB   addr_lo[14] set         -> embedding row into scratch 24576+
      MOVX  addr_lo[14] set, 6144   -> scratch 16384+ read out as int8
      MOVY  addr_lo[14] set         -> RES rows back into scratch 20480+

    The MOVX length is deliberately 6144 int8 elements = 1536 XWIN words,
    which is ALSO the R4 follow-on this task inherited: it is the first
    vector anywhere to push XWIN words >= 1024, so it is the one that
    actually exercises the mvchan XWIN window past its old 4 KiB (the stub
    decode in tb/seq_stub_mvchan.sv and the burst-AW bound in
    tb/tb_seq_unit.sv).  It also forces the m_axib splitter to break the
    6144-byte write across the 4 KiB boundary at 0x5000."""
    # 6144 words of constants so the LDC below can fill the MOVX source
    blob_words = rng.integers(-32768, 32767, size=8192).astype("<i2")
    blob = blob_words.tobytes()
    emb = rng.integers(-2000, 2000,
                       size=(8, EMB_ROW_BYTES // 2)).astype("<i2")

    HI_LDC = 16384          # LDC dst  — target[14] = 1
    HI_MVY = 20480          # MOVY dst — addr_lo[14] = 1
    HI_EMB = 24576          # EMB dst  — addr_lo[14] = 1
    R = []

    # --- LDC straight into the high half (target[14] = 1) ---------------
    R.append(rec(SF.EXT_LDC, target=HI_LDC, imm32=6144, addr_lo=BLOB_BASE))
    # ... and a second one with XRF indirection on the DDR side, so the
    # high target survives the indirection path too
    R.append(rec(SF.OP_CSRWR, target=SF.csr_seq_xrf(4), imm32=128))
    R.append(rec(SF.EXT_LDC, flags=(SF.IND_ADD | (4 << 4)),
                 target=HI_LDC + 6144, imm32=64, addr_lo=BLOB_BASE))

    # --- EMB into the high half (addr_lo[14] = 1) -----------------------
    R.append(rec(SF.OP_CSRWR, target=SF.csr_seq_xrf(3), imm32=5))
    R.append(rec(SF.OP_EMB, target=EMB_BASE >> 32, imm32=EMB_BASE & 0xFFFFFFFF,
                 addr_lo=HI_EMB, hi=1024))

    # --- MOVX out of the high half, 6144 elements = 1536 XWIN words -----
    #     (the R4 XWIN follow-on: the first vector past word 1023)
    R.append(rec(SF.OP_MOVX, flags=(0 << 4), addr_lo=HI_LDC, hi=6144))
    R.append(rec(SF.OP_MVGO, flags=(0 << 4), imm32=_shape(24, 0, 48),
                 addr_lo=0x0002_0000, hi=(96 << 8) | 0))
    # --- MOVY back into the high half, both modes -----------------------
    R.append(rec(SF.OP_MOVY, flags=(SF.MOVY_INT16 << 4), target=0,
                 imm32=5, addr_lo=HI_MVY, hi=1024))
    R.append(rec(SF.OP_MOVX, flags=(1 << 4), addr_lo=HI_LDC + 1024, hi=4096))
    R.append(rec(SF.OP_MVGO, flags=(1 << 4), imm32=_shape(24, 0, 48),
                 addr_lo=0x0002_1000, hi=(96 << 8) | 0))
    R.append(rec(SF.OP_MOVY, flags=0, target=1,          # pairs32
                 imm32=4, addr_lo=HI_MVY + 2048, hi=512))

    # --- and one LOW-half MOVX/MOVY in the same stream, so a decode that
    #     force-sets bit 14 (rather than reading it) also fails ----------
    R.append(rec(SF.OP_MOVX, flags=(2 << 4), addr_lo=0x0100, hi=256))
    R.append(rec(SF.OP_MVGO, flags=(2 << 4), imm32=_shape(24, 0, 8),
                 addr_lo=0x0002_2000, hi=(64 << 8) | 0))
    R.append(rec(SF.OP_MOVY, flags=(SF.MOVY_INT16 << 4), target=2,
                 imm32=3, addr_lo=0x0200, hi=128))

    R.append(rec(SF.OP_FENCE))
    R.append(rec(SF.OP_HALT))
    return R, blob, emb


# One repack configuration per seed (see build_repack): nch, the ILV chunk
# size, the image shapes (rows, K) and which wids carry the interleave.  K
# 1024 at W8 is a 1088 B row, so a four-row imbalance already exceeds
# WID_ALIGN and the per-channel cursors visibly diverge.
REPACK_VARIANTS = [
    dict(nch=2, depth=16, shapes=[(48, 1024), (24, 128)], ilv=(0,)),
    dict(nch=4, depth=16, shapes=[(96, 1024), (48, 128), (20, 256)],
         ilv=(0, 2)),
    dict(nch=3, depth=32, shapes=[(100, 1024), (37, 256)], ilv=(0,)),
    dict(nch=4, depth=8, shapes=[(70, 256), (70, 1024), (13, 128)], ilv=(1,)),
]


def build_repack(rng, seed=1):
    """R-c directed case: PER-CHANNEL weight bases on the wire.

    Every MVGO vector before this one addresses the nch-INDEPENDENT pack,
    where an image occupies ONE span that every channel reserves and the
    WBASE is `base + GLOBAL row * stride` — so channel 0 and channel 1
    reading different rows of the same image read addresses that differ only
    by the row.  The R-c repack gives each channel its own base over only
    the rows it owns, which is what makes the 1.85 GiB V5 W8 pack fit the
    1,280 MiB window (evidence/qwen2b/q2/v4_v5/V4_V5.md §5).

    W8 images across nch channels, planned by the REAL allocator
    (`seq_format.plan_weights_from_wids(repack=True)` -> `hwmap.plan_weights`):

      LAYOUT_ILV     `depth`-row chunks, chunk j on channel j % nch — the LM
                     head's placement, so a channel's rows are STRIDED
                     through the image while its BYTES are contiguous from
                     its own base.  This is the case an affine rebase cannot
                     express.
      LAYOUT_CONTIG  one contiguous row-slice per channel.

    Each piece is issued as MOVX / MVGO / MOVY, so the exact WBASE_LO/HI
    pair reaches the right matvec_chan; the stub also seeds its RES from the
    WBASE, so a mangled address moves the MOVY'd scratch words too and the
    .exp catches what the .wtr would.

    ONE VARIANT PER SEED (`REPACK_VARIANTS`): nch 2/4/3/4, different chunk
    sizes and a different image carrying the interleave, because the thing
    that can break is the BOOKKEEPING across channels and images, not the
    record encoding.  Every variant is checked below to actually diverge —
    a per-channel cursor whose divergence is smaller than one WID_ALIGN
    (4096 B) would be rounded away and the vector would prove nothing.
    """
    import numpy as _np
    v = REPACK_VARIANTS[(seed - 1) % len(REPACK_VARIANTS)]
    nch, depth, shapes = v["nch"], v["depth"], v["shapes"]
    g, sh = 128, 5
    wids = {}
    for wid, (N, K) in enumerate(shapes):
        wids[f"w{wid}"] = (wid, {"w8": _np.zeros((N, K), dtype=_np.int8),
                                 "m": _np.zeros((N, K // g), dtype=_np.int8),
                                 "sh": sh, "g": g})
    lay = {w: (SF.LAYOUT_ILV if w in v["ilv"] else SF.LAYOUT_CONTIG)
           for w in range(len(shapes))}
    plan = SF.plan_weights_from_wids(wids, nch=nch, repack=True,
                                     layout_of=lay, chunk_rows=depth)
    flat = SF.plan_weights_from_wids(wids)          # the one-span pack
    blob = rng.integers(-32768, 32767, size=1024).astype("<i2").tobytes()
    emb = rng.integers(-2000, 2000,
                       size=(8, EMB_ROW_BYTES // 2)).astype("<i2")

    R = [rec(SF.EXT_LDC, target=0x0000, imm32=1024, addr_lo=BLOB_BASE)]
    dst, seen = 0x0400, {}
    rows_of = {}
    for wid in range(len(shapes)):
        p = plan[wid]
        N, K, stride = p["nrows"], p["k"], p["stride"]
        rows_of[wid] = SF.chan_rows(N, nch, lay[wid], depth)
        for (i, r0, n, off) in SF.weight_pieces_at(N, nch, lay[wid], depth,
                                                   repack=True):
            wb = p["base"][i] + off * stride
            # the address really is per-channel: row-aligned inside THIS
            # channel's slice, which holds only the rows this channel owns
            assert p["base"][i] <= wb < p["base"][i] + rows_of[wid][i] * stride
            assert (wb - p["base"][i]) % stride == 0
            seen.setdefault(i, []).append(wb)
            beats = n * stride // 64
            R.append(rec(SF.OP_MOVX, flags=(i << 4), addr_lo=0, hi=K))
            R.append(rec(SF.OP_MVGO, flags=(i << 4),
                         # G3.3 stripped the W8 engine mode, and with it
                         # `shape_word`'s w8 encoding at isa=2 — this call
                         # still passed `w8=True` and REFUSED, so the whole
                         # seq_unit vector set could not be generated at
                         # 8138d66.  It is dropped here (G3.4): this vector
                         # exercises the REPACK ADDRESS BOOKKEEPING and the
                         # SHAPE word is an opaque payload to the mover —
                         # nothing in this TB's DUT decodes the mode.
                         imm32=HW.shape_word(n, sh, K // 128, g=g),
                         addr_lo=wb & 0xFFFFFFFF,
                         hi=(beats << 8) | ((wb >> 32) & 0xFF)))
            R.append(rec(SF.OP_MOVY, flags=(SF.MOVY_INT16 << 4), target=i,
                         imm32=3, addr_lo=dst, hi=n))
            dst += n
    # the point of the exercise, asserted in the vector generator so a broken
    # repack cannot silently emit a VALID-looking stream:
    #  - both channels are addressed, and they do NOT share their bases
    assert len(seen) == nch and all(seen.values())
    # image 0 starts at W_BASE on EVERY channel (every cursor does); the
    # channels diverge at a LATER image precisely because an uneven split
    # gave them different row counts — that divergence IS the repack, and a
    # one-span pack would put every image at one address on every channel.
    assert all(b == HW.W_BASE for b in plan[0]["base"])
    div = [w for w in plan if len(set(plan[w]["base"])) > 1]
    assert div, "no image's bases differ between channels — vacuous vector"
    for w in div:
        assert flat[w]["base"] > max(plan[w]["base"])
    #  - an ILV image's chunks are contiguous BYTES on each channel
    for w in v["ilv"]:
        for i in range(nch):
            b0, st = plan[w]["base"][i], plan[w]["stride"]
            mine = sorted(x for x in seen[i]
                          if b0 <= x < b0 + rows_of[w][i] * st)
            assert mine == [b0 + j * depth * st
                            for j in range(len(mine))], mine
    #  - and every channel's pack really is shorter than the one span
    one = max(q["base"] + q["nrows"] * q["stride"] for q in flat.values())
    for i in range(nch):
        assert max(plan[w]["base"][i] + rows_of[w][i] * plan[w]["stride"]
                   for w in plan) < one
    R.append(rec(SF.OP_FENCE))
    R.append(rec(SF.OP_HALT))
    return R, blob, emb


def build_embrow(rng, emb_log2=12):
    """R-b directed case: the EMB row size is a RUNTIME CSR (EMBLOG2).

    Before R-b the row stride was `localparam int EMB_ROW_BYTES = 2048`, so
    a 2B model (H=2048 -> 4096 B rows) needed its own bitstream.  This stream
    runs with EMBLOG2 = 12 (4096 B rows, the Qwen3.5-2B geometry): the TB
    writes the CSR before START (`EMBLOG2` in the .exp), and the golden
    scratch image is `emb[tok]` of a table whose rows really are 4096 B.

    On the pre-R-b RTL the CSR write is ignored and the fetch lands at
    EMB_BASE + tok*2048 — half a row off — so the FIRST embedding word the
    mover writes into scratch already mismatches the golden trace.  Token 5
    and token 3 are both odd multiples of the half row, which is exactly the
    case a constant 2048 gets wrong; token 0 is included because it is the
    one token a wrong shift still gets right (a stride bug must not hide
    behind the origin)."""
    row_words = 1 << (emb_log2 - 1)
    blob = rng.integers(-32768, 32767, size=64).astype("<i2").tobytes()
    emb = rng.integers(-2000, 2000,
                       size=(8, row_words)).astype("<i2")
    R = []
    for tok, dst, n in ((5, 0x0000, row_words), (3, 0x2000, row_words // 2),
                        (0, 0x3000, 64)):
        R.append(rec(SF.OP_CSRWR, target=SF.csr_seq_xrf(3), imm32=tok))
        R.append(rec(SF.OP_EMB, target=EMB_BASE >> 32,
                     imm32=EMB_BASE & 0xFFFFFFFF, addr_lo=dst, hi=n))
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
    emb = rng.integers(-2000, 2000,
                       size=(8, EMB_ROW_BYTES // 2)).astype("<i2")
    R = []
    for i in range(ntok):
        # len 8 keeps the stub command short; p0[0]=1 (fresh) on the first
        R += alu_cmd(10, 8, 0x0000, 0, 1 if i == 0 else 0, 0x0700)
        R.append(rec(SF.OP_AMAXL))
    R.append(rec(SF.OP_HALT))
    return R, blob, emb


OFIFO_N = (24, 64, 80)

# SR3: build_fmask's channel permutation per seed (logical -> physical).
# Across the four, each physical channel is the skipped-then-drained
# channel, the not-pending masked channel and a single-bit drain at least
# once.
FMASK_PERMS = [(0, 1, 2, 3), (3, 2, 1, 0), (2, 3, 0, 1), (1, 0, 3, 2)]

MICROS = ("csrwr", "cmd", "movx", "movy16", "movy32", "ldc")


def main():
    if len(sys.argv) < 3:
        sys.exit("usage: gen_seq_unit_vectors.py <outdir> <seed>")
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
        # R-b: the 15-bit SEQ-record directed case (scratch > 16383 on
        # LDC/EMB/MOVX/MOVY) + the R4 XWIN follow-on (1536 XWIN words)
        hr, hb, he = build_hiaddr(np.random.default_rng(9100))
        hm = emit(os.path.join(outdir, "seq_h_hiaddr"), hr, hb, he)
        nhi = sum(1 for a in hm.wrote if a >= 16384)
        print(f"seq_h_hiaddr: {len(hr)} records, {len(hm.wrote)} scratch "
              f"words ({nhi} above word 16383)")
        assert nhi > 0, "seq_h_hiaddr wrote nothing above word 16383"
        # R-b: the runtime EMB row size (EMBLOG2 = 12 -> 4096 B rows)
        er, eb, ee = build_embrow(np.random.default_rng(9200))
        em = emit(os.path.join(outdir, "seq_h_embrow"), er, eb, ee,
                  emb_log2=12)
        print(f"seq_h_embrow: {len(er)} records, {len(em.wrote)} scratch "
              f"words at EMBLOG2=12 (4096 B rows)")
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

    # SR3: the FENCE channel mask (SEQ_ISA v2.3 B17.1), one channel
    # permutation per seed; seed 1 is the identity and keeps the plan's name
    # seq_h_fmask, seeds 2..4 are seq_h_fmask<seed>.
    kperm = FMASK_PERMS[(seed - 1) % len(FMASK_PERMS)]
    kname = "seq_h_fmask" if seed == 1 else f"seq_h_fmask{seed}"
    kr, kb, ke = build_fmask(np.random.default_rng(9400 + seed), kperm)
    km = emit(os.path.join(outdir, kname), kr, kb, ke)
    nmask = sum(1 for r in kr if r.opcode == SF.OP_FENCE)
    print(f"{kname}: {len(kr)} records, {nmask} FENCEs, perm {list(kperm)}, "
          f"poll sets " + " ".join(f"{i}:{km.fpolls[i][1]:x}"
                                   for i in sorted(km.fpolls)))

    # SR12: the R2 bank fields (SEQ_ISA v2.3 B17.2), one channel
    # permutation per seed (FMASK_PERMS); seed 1 is seq_h_bank, seeds 2..4
    # seq_h_bank<seed>.
    bperm = FMASK_PERMS[(seed - 1) % len(FMASK_PERMS)]
    bname = "seq_h_bank" if seed == 1 else f"seq_h_bank{seed}"
    br, bb, be = build_banks(np.random.default_rng(9500 + seed), bperm)
    bm = emit(os.path.join(outdir, bname), br, bb, be)
    print(f"{bname}: {len(br)} records, perm {list(bperm)}, "
          f"{sum(1 for k in bm.xwa if k[0] == 'X')} MOVX / "
          f"{sum(1 for k in bm.xwa if k[0] == 'Y')} MOVY windows, "
          f"non-zero starts " + " ".join(f"{k[0]}{k[1]}@{k[2]}"
                                         for k in bm.xwa if k[2]))

    # R-c: PER-CHANNEL weight bases (the V5 repack) on the wire.  One
    # configuration per seed, so the four TB runs cover nch 2/3/4 and both
    # layouts rather than repeating one address map.
    rr, rb, re_ = build_repack(np.random.default_rng(9300 + seed), seed)
    rm = emit(os.path.join(outdir, f"seq_h_repack{seed}"), rr, rb, re_)
    nmv = sum(1 for r in rr if r.opcode == SF.OP_MVGO)
    v = REPACK_VARIANTS[(seed - 1) % len(REPACK_VARIANTS)]
    print(f"seq_h_repack{seed}: {len(rr)} records, {nmv} MVGOs at "
          f"per-channel bases (nch={v['nch']} depth={v['depth']} "
          f"ilv={list(v['ilv'])}), {len(rm.wrote)} scratch words")



# ======================================================================
# SEQ_ISA B17.3 (R3): the MOVX BROADCAST -- Task R3-8 of the R3 campaign
# (docs/superpowers/plans/2026-09-29-r3-broadcast.md).  Everything R3 adds to
# this generator lives HERE, after every line other documents cite, so no
# citation moves (the SR14 §7 zero-drift rule, R3-2/R3-3's layout); the
# Model reaches it through three rewritten lines (BUILD_CAPS, run()'s MOVX
# and MVGO dispatch, validate()'s channel clause).  Python resolves the
# names at call time, so defining them after their callers is ordinary.
#
# THE TWIN.  validate()'s channel clause mirrors ref/seq_format's
# _movx_bcast_admitted (a MOVX whose flags[7:4] = SF.MOVX_BCAST is admitted
# when SF.MOVX_BCAST_CAPS <= caps; MOVX 4..14 and MVGO >= 4, 0xF included,
# keep err 0x05) and then B17.2's window rule on the ONE start word, as a
# unicast.  The executor mirrors ref/seq_model's _movx_bcast: the running
# check on EVERY destination before any write, one scratch read, the same
# words into channels 0..3 at the same start word, NO XPTR write (so the
# AXI-Lite trace has the SPTR write and no XPTR write), and the stub's xsum
# of each channel grows by every word (the stub's xsum is reset by an XPTR
# write or a doorbell -- mvgo_r3 below mirrors the doorbell reset, which
# the pre-R3 Model never needed because every MVGO followed a MOVX).
# Evidence/qwen9b/sr/r3_8_twin.py (Step 5b) compares this executor's XWIN
# images with ref/seq_model's, word for word.
#
# THE TRACE.  A broadcast's words leave seq_movers on the x-push bus, not
# m_axib; tb/tb_seq_unit.sv canonicalises each push (all four valid bits
# together) to four "MV(c) + XWIN <- word" writes, c = 0..3, which is the
# order written below.  <prefix>.xwa gains "B 15 <start word> <words>" per
# broadcast (its own list in the TB: the push beats, not the burst beats,
# consume it).
# ======================================================================
def _bcast_ok(model, o, hi):
    """validate()'s channel clause: True iff a MOVX broadcast is admitted
    at the Model's caps (the RTL under test implements BUILD_CAPS)."""
    return (o == SF.OP_MOVX and hi == SF.MOVX_BCAST
            and SF.MOVX_BCAST_CAPS <= model.caps)


def _xwords(mem, src, n):
    """The packed XWIN words a MOVX of n int8 from scratch `src` writes
    (the RTL's packer: little-endian bytes, the ragged tail zero-padded)."""
    out, acc, idx = [], 0, 0
    for i in range(n):
        acc |= (int(mem[(src + i) & 0xFFFF]) & 0xFF) << (8 * idx)
        idx += 1
        if idx == 4 or i == n - 1:
            out.append(acc)
            acc, idx = 0, 0
    return out


def _xwin_img(model):
    """Per-channel XWIN word images (3072 words, None = never written),
    created on first use so Model.__init__ keeps its cited lines."""
    if not hasattr(model, "xwin_img"):
        model.xwin_img = [[None] * XWIN_WORDS for _ in range(4)]
    return model.xwin_img


def _movx_r3(self, r):
    """run()'s MOVX dispatch (R3-8): a broadcast here, a unicast by movx()."""
    img = _xwin_img(self)
    if r.chan != SF.MOVX_BCAST:
        self.movx(r)
        w0 = r.target & SF.MOVX_WORD_MASK
        for k, w in enumerate(_xwords(self.mem, r.addr_lo & 0xFFFF,
                                      r.len_or_addr_hi)):
            img[r.chan][w0 + k] = w
        return
    src, n = r.addr_lo & 0xFFFF, r.len_or_addr_hi
    w0 = r.target & SF.MOVX_WORD_MASK
    nw = SF.movx_words(n)
    for c in range(4):                     # every destination, before any write
        self.running(c, "broadcast MOVX", xr=(w0, w0 + nw))
    if n == 0:
        return                             # seq_movers: len 0 -> S_DONE, no traffic
    self.xwa.append(("B", SF.MOVX_BCAST, w0, nw))
    self.W(LAYER + L_SPTR, src)            # X_SPTR as the unicast; NO XPTR write
    self.sptr = src
    words = _xwords(self.mem, src, n)
    for i in range(n):
        self.R(LAYER + L_SWIN)             # ONE scratch read per int8
    for k, w in enumerate(words):
        for c in range(4):
            self.W(MV(c) + MV_XWIN, w)
            self.mv[c]["xsum"] = (self.mv[c]["xsum"] + w) & 0xFFFFFFFF
            img[c][w0 + k] = w
    self.sptr = (src + n) & 0xFFFF


def _mvgo_r3(self, r):
    """run()'s MVGO dispatch (R3-8): movx()'s twin needs the stub's doorbell
    reset of xsum (tb/seq_stub_mvchan.sv), because a broadcast has no XPTR
    write to reset it.  The seed is computed first, exactly as before."""
    self.mvgo(r)
    self.mv[r.chan]["xsum"] = 0


Model.movx_r3 = _movx_r3
Model.mvgo_r3 = _mvgo_r3


def build_bcast(rng, seed=1):
    """R3-8 directed case: the MOVX broadcast (SEQ_ISA v2.3 B17.3).

    Covered, all MOVX sources in the LDC'd region (so Step 5b can replay
    them through ref/seq_model): a broadcast into bank 0 and MVGOs on all
    four channels; a broadcast into bank 1 WHILE no-wait bank-0 streams run
    on all four (legal: every destination's running range is words
    [0, 32*ng)); a mask-0 FENCE; MOVYs of every channel; XBANK MVGOs on the
    bank-1 x; a broadcast then a UNICAST over the same window on one
    channel (the unicast's burst must land after every pushed word); a
    broadcast with a RAGGED tail at an odd start word; and a zero-length
    broadcast (no traffic).  Every MVGO's stub seed folds in its channel's
    xsum, so a word pushed to the wrong channel (or not at all) moves every
    value the following MOVY writes."""
    blob = rng.integers(-32768, 32767, size=8192).astype("<i2").tobytes()
    emb = rng.integers(-2000, 2000,
                       size=(8, EMB_ROW_BYTES // 2)).astype("<i2")
    XB, W1 = SF.SHAPE_XBANK, SF.XBANK_WORD
    B = SF.MOVX_BCAST
    uc = int(rng.integers(0, 4))                   # the unicast's channel
    l0 = int(rng.choice([256, 512, 1024]))         # bank-0 broadcast, int8
    l1 = int(rng.choice([257, 301, 1022]))         # bank-1, ragged
    lr = int(rng.choice([13, 23, 37]))             # the odd-start ragged one

    def movx(ch, w0, src, n):
        return rec(SF.OP_MOVX, flags=(ch << 4), target=w0, addr_lo=src, hi=n)

    def mvgo(ch, shape, nowait=0):
        return rec(SF.OP_MVGO, flags=(ch << 4), target=nowait, imm32=shape,
                   addr_lo=0x0002_0000 + 0x1000 * ch, hi=(24 << 8) | 0)

    def movy(ch, dst, n, mode=SF.MOVY_INT16, sh=3):
        return rec(SF.OP_MOVY, flags=(mode << 4), target=ch,
                   imm32=sh, addr_lo=dst, hi=n)

    R = [rec(SF.EXT_LDC, target=0x0000, imm32=8192, addr_lo=BLOB_BASE)]
    # bank 0 on all four, then the four channels read it (waiting)
    R.append(movx(B, 0, 0x0000, l0))
    R += [mvgo(c, _shape(8 + c, 0, max(1, l0 // 128))) for c in range(4)]
    R += [movy(c, 0x3000 + 0x40 * c, 8 + c) for c in range(4)]
    # bank 0 again, no-wait streams on all four, and WHILE they run the
    # bank-1 broadcast (ng 2: the running range is words [0, 64))
    R.append(movx(B, 0, 0x0800, 256))
    R += [mvgo(c, _shape(12, 0, 2), nowait=1) for c in range(4)]
    R.append(movx(B, W1, 0x1000, l1))
    R.append(rec(SF.OP_FENCE))
    R += [movy(c, 0x3200 + 0x40 * c, 12, mode=SF.MOVY_PAIRS32)
          for c in range(4)]
    R += [mvgo(c, _shape(10, 0, 2) | XB) for c in range(4)]
    R += [movy(c, 0x3400 + 0x40 * c, 10) for c in range(4)]
    # a broadcast then a unicast over the same window on channel uc
    R.append(movx(B, 0, 0x1800, 128))
    R.append(movx(uc, 0, 0x1C00, 128))
    R += [mvgo(c, _shape(6, 0, 1)) for c in range(4)]
    R += [movy(c, 0x3600 + 0x40 * c, 6) for c in range(4)]
    # the ragged, odd-start broadcast, a zero-length one, and a last read
    R.append(movx(B, 5, 0x0400, lr))
    R.append(movx(B, 7, 0x0400, 0))
    R += [mvgo(c, _shape(4, 0, 1)) for c in range(4)]
    R += [movy(c, 0x3800 + 0x40 * c, 4) for c in range(4)]
    R.append(rec(SF.OP_HALT))
    return R, blob, emb


def build_errs_r3():
    """R3-8 error vectors (B17.3), each AFTER legal records incl. a legal
    broadcast, so a refusal cannot be an early halt; the TB checks the PC.
      bcast_mvgo   MVGO flags[7:4] = 0xF -> 0x05 (a broadcast is MOVX only)
      movx_chan5   MOVX flags[7:4] = 5   -> 0x05 (4..14 stay reserved)
      bcast_range  broadcast at start word 3000: 288 int8 (72 words, ends at
                   3072) runs, 1024 int8 (256 words) -> 0x06 (B17.2's rule
                   on the ONE window)"""
    B = SF.MOVX_BCAST
    legal = [rec(SF.OP_MOVX, flags=(B << 4), addr_lo=0x0000, hi=64),
             rec(SF.OP_MVGO, flags=(2 << 4), imm32=_shape(24, 0, 1),
                 addr_lo=0x0002_0000, hi=(24 << 8) | 0)]
    out = {}
    out["bcast_mvgo"] = (legal + [rec(SF.OP_MVGO, flags=(B << 4),
                                      imm32=_shape(24, 0, 8),
                                      addr_lo=0x0002_0000, hi=(24 << 8) | 0),
                                  rec(SF.OP_HALT)], 0x05)
    out["movx_chan5"] = (legal + [rec(SF.OP_MOVX, flags=(5 << 4),
                                      addr_lo=0x0000, hi=64),
                                  rec(SF.OP_HALT)], 0x05)
    out["bcast_range"] = (legal + [rec(SF.OP_MOVX, flags=(B << 4), target=3000,
                                       addr_lo=0x0000, hi=288),
                                   rec(SF.OP_MOVX, flags=(B << 4), target=3000,
                                       addr_lo=0x0000, hi=1024),
                                   rec(SF.OP_HALT)], 0x06)
    return out


def main_r3():
    """R3-8's vectors, after main()'s (none of main()'s files changes but
    caps.hex, which moves fab1ca03 -> fab1ca07 with BUILD_CAPS)."""
    outdir, seed = sys.argv[1], int(sys.argv[2])
    name = "seq_h_bcast" if seed == 1 else f"seq_h_bcast{seed}"
    br, bb, be = build_bcast(np.random.default_rng(9600 + seed), seed)
    bm = emit(os.path.join(outdir, name), br, bb, be)
    nb = sum(1 for k in bm.xwa if k[0] == "B")
    print(f"{name}: {len(br)} records, {nb} broadcast windows "
          + " ".join(f"B@{k[2]}+{k[3]}" for k in bm.xwa if k[0] == "B")
          + f", {len(bm.wrote)} scratch words")
    if seed == 1:
        _b, eb, ee = build_bcast(np.random.default_rng(9601), 1)
        for nm, (er, code) in build_errs_r3().items():
            emit(os.path.join(outdir, f"seq_e_{nm}"), er, eb, ee,
                 expect_err=code)
            print(f"seq_e_{nm}: expects err_code {code:#04x}")


if __name__ == "__main__":
    main()
    main_r3()
