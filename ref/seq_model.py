#!/usr/bin/env python3
"""seq_model.py — pure-python executor of a binary SEQ stream.

This is the GOLDEN for the RTL sequencer: it fetches 16-byte records
(ref/seq_format.py), issues them against the same scratchpad model the
script generators use (gen_layer_script.Mach), and simulates the XRF, the
two movers and the matvec engine — the engine by reading the REAL packed
DDR weight images and running ref/w4a8_ref.matvec_y32 on them, so a .seq
replay exercises the whole wire format end to end.

    python seq_model.py --gate tb/scripts/token24_s1        # the gate
    python seq_model.py --disasm tb/scripts/token24_s1 -n 200
    python seq_model.py --selftest

THE GATE.  `--gate <prefix>` replays BOTH representations of the same
schedule against fresh models and asserts they are bit-identical:

  * <prefix>.txt   the host-driven script (the committed artifact).  Its W
                   records carry the host-relayed matvec y32, so this side
                   needs no weight images at all; its R/E/A records are
                   assertions and are checked while replaying.
  * <prefix>.seq   the sequencer stream.  Its MVGO/MOVY records recompute
                   the same y32 from the packed DDR images, so the two
                   sides agree ONLY IF the emitted addressing, shapes,
                   row-chunking, dequant shifts and XRF indirection are all
                   correct.

Compared: the whole 16K int16 scratchpad, every banked layer state
(conv window/weights, DeltaNet S, KV cache, TCNT), the EOUT/AMAX
registers, and the generated token list (.txt A records vs the .seq OUT
FIFO fed by AMAXL).
"""
import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import seq_format as SF                                     # noqa: E402
from seq_format import (Rec, OP_CSRWR, OP_CMD, OP_MOVX, OP_MOVY, OP_MVGO,
                        OP_EMB, OP_AMAXL, OP_JMP, OP_FENCE, OP_HALT,
                        EXT_LDC, EXT_XOP, JMP_TCNT, MOVY_INT16, MVGO_NOWAIT,
                        XRF_N, XRF_EX, XRF_K_DN, XRF_K_ATTN, XRF_TOK,
                        CSR_SPACE_LAYER, CSR_SPACE_MV, CSR_SPACE_SEQ,
                        LOFF_ARG0, LOFF_ARG1, LOFF_ARG2, LOFF_CMD,
                        LOFF_SPTR, LOFF_SWIN, LOFF_TCNT, LOFF_LAYER,
                        SOFF_TCNT_SEQ, SOFF_XRF0, ALU_DYNQ16, ALU_EMUL32,
                        ALU_PROBE_BIT, ALU_PROBE_SHIFT_MASK,
                        VN_EPSNORM_MODE, VN_ARG2_EPS, VN_ARG2_XRF_SHIFT)
import hwmap as HW                                          # noqa: E402
from w4a8_ref import matvec_y32, unpack_ddr_rows, rshift_round as rshr  # noqa

I64 = np.int64


def _fresh_mach():
    """A Mach carrying ONLY the model (its script sink is /dev/null and its
    SEQ emitter is forced off)."""
    saved = os.environ.pop("SEQ_EMIT", None)
    try:
        import gen_layer_script as GLS
        M = GLS.Mach(open(os.devnull, "w"))
    finally:
        if saved is not None:
            os.environ["SEQ_EMIT"] = saved
    return M


def clip16(x):
    return np.clip(np.asarray(x, dtype=I64), -32768, 32767)


def rs_s(v, p):
    """rshr64s: round-half-away right shift; negative p = exact left shift."""
    v = np.asarray(v, dtype=I64)
    return rshr(v, p) if p >= 0 else v << (-p)


# ======================================================================
# state comparison
# ======================================================================
def snapshot(M):
    """The complete architectural state a SEQ replay must reproduce."""
    return {
        "mem": M.mem.copy(),
        "cw": M.cw.copy(), "cs": M.cs.copy(), "S": M.S.copy(),
        "vnw": M.vnw.copy(), "cos": M.cos.copy(), "sin": M.sin.copy(),
        "T": [list(t) for t in M.T],
        "kc": [[[(a.copy(), e) for (a, e) in h] for h in s] for s in M.kc],
        "vc": [[[(a.copy(), e) for (a, e) in h] for h in s] for s in M.vc],
        "eout": int(M.eout),
        "am": (int(M.am_val), int(M.am_idx), int(M.am_g), bool(M.am_first)),
        "dn_slot": int(M.dn_slot), "kv_slot": int(M.kv_slot),
    }


def diff_state(a, b):
    """[] when identical, else a list of human-readable differences."""
    out = []
    for k in ("mem", "cw", "cs", "S", "vnw", "cos", "sin"):
        if not np.array_equal(a[k], b[k]):
            d = np.nonzero(np.asarray(a[k]).ravel()
                           != np.asarray(b[k]).ravel())[0]
            out.append(f"{k}: {len(d)} words differ, first at flat index "
                       f"{int(d[0])} ({int(np.asarray(a[k]).ravel()[d[0]])} "
                       f"vs {int(np.asarray(b[k]).ravel()[d[0]])})")
    for k in ("T", "eout", "am", "dn_slot", "kv_slot"):
        if a[k] != b[k]:
            out.append(f"{k}: {a[k]!r} vs {b[k]!r}")
    for k in ("kc", "vc"):
        for s in range(len(a[k])):
            for h in range(len(a[k][s])):
                A, B = a[k][s][h], b[k][s][h]
                if len(A) != len(B):
                    out.append(f"{k}[{s}][{h}]: depth {len(A)} vs {len(B)}")
                    continue
                for t, ((x, ex), (y, ey)) in enumerate(zip(A, B)):
                    if ex != ey or not np.array_equal(x, y):
                        out.append(f"{k}[{s}][{h}][{t}] differs")
                        break
    return out


# ======================================================================
# DDR weight image provider (the matvec engine's view)
# ======================================================================
class DDRWeights(object):
    """Maps a WBASE address to the rows of a packed weight image.

    `from_files` is the real path: it memory-maps <prefix>_w*.bin and
    unpacks the rows through w4a8_ref.unpack_ddr_rows, so a replay proves
    the packed wire format round-trips.  `from_wids` skips the disk and
    uses the generator's live quantized matrices (used by the in-process
    gate when the images are not being dumped).
    """

    def __init__(self, plan):
        # plan: {wid: {base,nrows,k,ng,sh,g,stride,nbeats}}
        self.plan = {int(k): v for k, v in plan.items()}
        self.byaddr = sorted((v["base"], int(k)) for k, v in self.plan.items())
        self._img = {}
        self._qw = {}

    @classmethod
    def from_files(cls, prefix, plan):
        self = cls(plan)
        d = os.path.dirname(os.path.abspath(prefix)) or "."
        man = json.load(open(prefix + ".weights.json"))
        for wid, m in man.items():
            self._img[int(wid)] = os.path.join(d, m["file"])
        return self

    @classmethod
    def from_wids(cls, wids, plan):
        self = cls(plan)
        for (wid, qw) in wids.values():
            self._qw[int(wid)] = qw
        return self

    def _lookup(self, wbase):
        lo, hi = 0, len(self.byaddr) - 1
        wid = None
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.byaddr[mid][0] <= wbase:
                wid = self.byaddr[mid][1]
                lo = mid + 1
            else:
                hi = mid - 1
        assert wid is not None, f"WBASE {wbase:#x} below the weight region"
        p = self.plan[wid]
        off = wbase - p["base"]
        assert 0 <= off < p["nrows"] * p["stride"], \
            f"WBASE {wbase:#x} does not land inside wid {wid}"
        assert off % p["stride"] == 0, \
            f"WBASE {wbase:#x} is not row-aligned in wid {wid}"
        return wid, off // p["stride"], p

    def matvec(self, wbase, nrows, sh, ng, g, x8):
        wid, r0, p = self._lookup(wbase)
        assert nrows + r0 <= p["nrows"], "MVGO row chunk overruns the image"
        assert sh == p["sh"] and g == p["g"] and ng == p["ng"], (
            f"wid {wid}: SHAPE (sh={sh} ng={ng} g={g}) != manifest "
            f"(sh={p['sh']} ng={p['ng']} g={p['g']})")
        K = p["k"]
        assert len(x8) == K, f"XWIN holds {len(x8)} bytes, K={K}"
        if wid in self._qw:
            qw = self._qw[wid]
            w4 = qw["w4"][r0:r0 + nrows]
            m = qw["m"][r0:r0 + nrows]
        else:
            stride = p["stride"]
            mm = np.memmap(self._img[wid], dtype=np.uint8, mode="r")
            img = mm[r0 * stride:(r0 + nrows) * stride]
            w4, m = unpack_ddr_rows(img.tobytes(), nrows, K, g)
        return np.asarray(matvec_y32(w4, m, sh, np.asarray(x8, dtype=np.int8),
                                     g=g), dtype=I64)


# ======================================================================
# the executor
# ======================================================================
class SeqExec(object):
    """Fetch/decode/issue a SEQ record stream against the Mach model."""

    def __init__(self, recs, blob, weights, emb=None, mach=None,
                 max_records=None, checkpoints=None):
        if isinstance(recs, (bytes, bytearray, memoryview)):
            recs = SF.unpack_stream(recs)
        self.recs = recs
        # {record index: (scratch addr, n)} — sampled BEFORE that record is
        # issued, in firing order, and compared against the .txt R records.
        self.cp_at = {int(i): (int(a), int(n))
                      for (i, a, n) in (checkpoints or [])}
        self.cp_log = []
        self.blob = blob
        self.W = weights
        self.emb = emb
        self.M = mach if mach is not None else _fresh_mach()
        self.xrf = [0] * XRF_N
        self.tcnt_seq = 0
        self.args = [0, 0, 0]
        self.sptr = 0
        self.xwin = {}
        self.res = {}
        self.out_fifo = []
        self.issued = 0
        self.max_records = max_records
        self.stats = {k: 0 for k in ("CSRWR", "CMD", "MOVX", "MOVY", "MVGO",
                                     "EMB", "AMAXL", "JMP", "FENCE", "LDC",
                                     "XOP", "PROBE", "MVGO_NOWAIT")}
        # channels a no-wait MVGO left running; FENCE (or the next MVGO on
        # the same channel) drains them.  The python model is synchronous,
        # so this only enforces the ORDERING RULE the RTL relies on.
        self.running = set()
        self.eps_scale_log = []       # (m_q15_epsnorm,) for the delta report

    # ---------------------------------------------------------- helpers
    def _xrf_set(self, i, v):
        v = int(v)
        lim_s, lim_u = 1 << (SF.XRF_BITS - 1), 1 << SF.XRF_BITS
        assert -lim_s <= v < lim_u, \
            f"XRF[{i}] <= {v} does not fit {SF.XRF_BITS} bits (see A11)"
        self.xrf[i] = v

    def _blob_words(self, addr, n):
        off = addr - SF.SEQ_DATA_BASE
        assert 0 <= off and off + 2 * n <= len(self.blob), \
            f"LDC reads {addr:#x}+{2 * n}B outside the {len(self.blob)}B blob"
        return np.frombuffer(self.blob, dtype="<i2", count=n,
                             offset=off).astype(I64)

    # ---------------------------------------------------------- issue
    def _csrwr(self, r):
        val = SF.resolve_imm(r, self.xrf) & 0xFFFFFFFF
        cid, sp, off = r.target, r.target & 0xF000, r.target & 0xFF
        M = self.M
        if sp == CSR_SPACE_LAYER:
            if off == LOFF_ARG0:
                self.args[0] = val
            elif off == LOFF_ARG1:
                self.args[1] = val
            elif off == LOFF_ARG2:
                self.args[2] = val
            elif off == LOFF_CMD:
                self._layer_cmd(val & 0xFF)
            elif off == LOFF_TCNT:
                assert val == 0, "layer TCNT is write-0 (reset) only"
                M.T[M.kv_slot] = [0, 0]
            elif off == LOFF_LAYER:
                M.dn_slot, M.kv_slot = val & 0x1F, (val >> 8) & 0x7
            elif off == LOFF_SPTR:
                self.sptr = val
            elif off == LOFF_SWIN:
                v = val & 0xFFFF
                M.mem[self.sptr] = v - 65536 if v >= 32768 else v
                self.sptr += 1
            else:
                raise SF.SeqValidationError(
                    f"CSRWR to unmodelled layer offset {off:#04x}")
        elif sp == CSR_SPACE_MV:
            pass          # MVGO carries WBASE/BEATS/SHAPE; direct writes nop
        elif sp == CSR_SPACE_SEQ:
            if off >= SOFF_XRF0:
                i = (off - SOFF_XRF0) // 4
                self._xrf_set(i, val)
            elif off == SOFF_TCNT_SEQ:
                self.tcnt_seq = val
            else:
                raise SF.SeqValidationError(
                    f"CSRWR to unmodelled SEQ offset {off:#04x}")
        else:
            raise SF.SeqValidationError(f"CSRWR to csr space {sp:#06x}")

    # ------------------------------------------------- layer_chan issue
    def _layer_cmd(self, op):
        """Decode ARG0..2 back into the layer_chan operation and run it on
        the scratchpad model.  Ops 1..12 are the SHIPPED set (delegated to
        Mach, which mirrors rtl/layer_chan.sv); ALU op 12 DYNQ16 and the
        EPS-NORM vecnorm mode are the new ISA ops, implemented here."""
        M = self.M
        a0, a1, a2 = self.args
        self.issued += 1
        if op == 1:                                   # VN / EPS-NORM
            mode = a0 & 0x3
            n = 1 << ((a0 >> 2) & 0xF)
            inf, outf = (a0 >> 6) & 0xF, (a0 >> 10) & 0xF
            src, dst = a1 & 0x3FFF, (a1 >> 14) & 0x3FFF
            if mode == VN_EPSNORM_MODE and (a2 & VN_ARG2_EPS):
                k = int(self.xrf[(a2 >> VN_ARG2_XRF_SHIFT) & 0x7])
                x = M.mem[src:src + n]
                scale = SF.eps_norm_scale(x, k, in_f=inf, out_f=outf,
                                          note=False)
                y = SF.eps_norm_fx(x, k, in_f=inf, out_f=outf, note=False)
                M.mem[dst:dst + n] = np.asarray(y, dtype=I64)
                self.eps_scale_log.append(int(scale))
            else:
                M.vn(mode, n, inf, outf, src, dst)
        elif op == 2:
            M.vnw_(a1, a0)
        elif op == 3:
            M.ropet(a1)
        elif op == 4:
            M.rope(a1 & 0x3FFF, (a1 >> 14) & 0x3FFF)
        elif op == 5:
            sub, first, nch = a0 & 0x3, (a0 >> 2) & 0x1FFF, (a0 >> 15)
            if sub == 0:
                M.convw(first, nch, a1)
            elif sub == 2:
                M.convz(first, nch)
            else:
                raise SF.SeqValidationError(f"CONVW sub-op {sub}")
        elif op == 6:
            M.conv(a0 & 0x1FFF, (a0 >> 13) & 0x1FFF,
                   a1 & 0x3FFF, (a1 >> 14) & 0x3FFF)
        elif op == 7:
            M.gate(a1 & 0x3FFF, (a1 >> 14) & 0x3FFF,
                   a2 & 0x3FFF, (a2 >> 14) & 0x3FFF, a0 & 0x3FFF)
        elif op == 8:
            M.dnst(a0 & 0xF, a1 & 0x3FFF, (a1 >> 14) & 0x3FFF,
                   a2 & 0x3FFF, (a0 >> 4) & 0x3FFF, (a0 >> 18) & 0x3FFF,
                   (a2 >> 14) & 0x3FFF)
        elif op == 9:
            M.kvap(a0 & 0xF, a1 & 0x3FFF, (a1 >> 14) & 0x3FFF,
                   (a0 >> 4) & 0x3FFF)
        elif op == 10:
            M.attn(a0 & 0xF, a1 & 0x3FFF, (a1 >> 14) & 0x3FFF)
        elif op == 11:
            self._alu(a0, a1, a2)
        elif op == 12:
            M.dnz(a0 & 0xF)
        else:
            raise SF.SeqValidationError(f"unknown layer_chan opcode {op}")

    def _alu(self, a0, a1, a2):
        M = self.M
        sub, n = a0 & 0xF, (a0 >> 4) & 0x3FFF
        srca, srcb = a1 & 0x3FFF, (a1 >> 14) & 0x3FFF
        p0 = a2 & 0x1FFFF
        p0 = p0 - (1 << 17) if p0 >= (1 << 16) else p0
        dst = (a2 >> 17) & 0x3FFF
        if sub == ALU_DYNQ16:
            x = M.pairs(srca, n)
            y, k = SF.dynq16_fx(x, clamp0=bool(p0 & 0x2))
            M.mem[dst:dst + n] = np.asarray(y, dtype=I64)
            self._xrf_set(XRF_K_ATTN if (p0 & 0x1) else XRF_K_DN, k)
            return
        if sub == ALU_EMUL32 and (p0 & ALU_PROBE_BIT):
            # op-8 PROBE (ISA v1.3, rtl/vec_alu.sv:39-53 + 218-234, 388-407).
            # cfg_p0[6] selects probe and is MASKED OUT of the shift decode,
            # so the write side is an ordinary EMUL32 by p0[5:0]; the running
            # max |pair(a)*b| is taken PRE-shift and the FINISHED k_a
            # (attn_o_shift semantics: bf_shift then clamp at 0) is latched
            # into XRF[2].  maxp is cleared at dispatch, so one command must
            # cover every product that shares the shift.
            import layer_fixed as LF
            sh = p0 & ALU_PROBE_SHIFT_MASK
            prod = M.pairs(srca, n) * M.mem[srcb:srcb + n]
            M.alu(ALU_EMUL32, n, sh, srca, srcb, dst)
            self._xrf_set(XRF_K_ATTN,
                          LF.attn_o_shift(int(np.abs(prod).max()), note=False))
            self.stats["PROBE"] += 1
            return
        M.alu(sub, n, p0, srca, srcb, dst)
        if sub == 0:                       # DYNQ8 retires -> XRF[0] = e_x
            self._xrf_set(XRF_EX, M.eout)

    # ---------------------------------------------------------- movers
    def _movx(self, r):
        n = r.len_or_addr_hi
        v = self.M.mem[r.addr_lo:r.addr_lo + n]
        assert np.all(v >= -128) and np.all(v <= 127), \
            "MOVX source is not int8-packed"
        self.xwin[r.chan] = np.asarray(v, dtype=np.int8)

    def _mvgo(self, r):
        shape = r.imm32
        nrows = (shape >> 12) & 0x1FFF
        sh = (shape >> 6) & 0x3F
        ng = shape & 0x3F
        g = 64 if (shape & HW.SHAPE_G64) else 128
        wbase = ((r.len_or_addr_hi & 0xFF) << 32) | r.addr_lo
        beats = r.len_or_addr_hi >> 8
        x8 = self.xwin.get(r.chan)
        assert x8 is not None, f"MVGO on mv{r.chan} before any MOVX"
        y = self.W.matvec(wbase, nrows, sh, ng, g, x8)
        wid, r0, p = self.W._lookup(wbase)
        assert beats == nrows * p["stride"] // 64, \
            f"MVGO BEATS {beats} != nrows*stride/64"
        assert nrows <= HW.RES_DEPTH, "MVGO chunk exceeds the RES BRAM"
        self.res[r.chan] = y
        if r.target & MVGO_NOWAIT:
            # v1.4: start and retire; the engine is still running as far as
            # the rest of the stream is concerned until a FENCE drains it.
            self.running.add(r.chan)
            self.stats["MVGO_NOWAIT"] += 1
        else:
            self.running.discard(r.chan)

    def _movy(self, r):
        y = self.res.get(r.chan)
        assert y is not None, f"MOVY on mv{r.chan} before any MVGO"
        assert r.chan not in self.running, (
            f"MOVY reads mv{r.chan} RES while a NO-WAIT MVGO is still "
            "running on it — the stream needs a FENCE first (ISA v1.4)")
        n = r.len_or_addr_hi
        assert n <= len(y), f"MOVY reads {n} RES rows, only {len(y)} valid"
        sh = SF.resolve_imm(r, self.xrf)
        v = rs_s(y[:n], sh)
        if r.movy_mode == MOVY_INT16:
            self.M.mem[r.addr_lo:r.addr_lo + n] = clip16(v)
        else:
            self.M.set_pairs(r.addr_lo,
                             np.clip(v, -(1 << 31), (1 << 31) - 1))

    # ---------------------------------------------------------- run
    def run(self, entry=0, max_steps=None):
        pc = entry
        n = len(self.recs)
        steps = 0
        while True:
            assert 0 <= pc < n, f"pc {pc} outside a {n}-record stream"
            r = self.recs[pc]
            SF.validate(r, nrec=n, idx=pc)
            cp = self.cp_at.get(pc)
            if cp is not None:
                self.cp_log.append(
                    (self.M.mem[cp[0]:cp[0] + cp[1]] & 0xFFFF).copy())
            o = r.opcode
            nxt = pc + 1
            if o == OP_CSRWR:
                self.stats["CSRWR"] += 1
                self._csrwr(r)
            elif o == OP_CMD:
                self.stats["CMD"] += 1
                self._layer_cmd(SF.resolve_imm(r, self.xrf) & 0xFF)
            elif o == OP_MOVX:
                self.stats["MOVX"] += 1
                self._movx(r)
            elif o == OP_MOVY:
                self.stats["MOVY"] += 1
                self._movy(r)
            elif o == OP_MVGO:
                self.stats["MVGO"] += 1
                self._mvgo(r)
            elif o == OP_EMB:
                self.stats["EMB"] += 1
                tok = int(self.xrf[XRF_TOK])
                assert self.emb is not None, "EMB with no embedding table"
                self.M.mem[r.addr_lo:r.addr_lo + r.len_or_addr_hi] = \
                    np.asarray(self.emb[tok][:r.len_or_addr_hi], dtype=I64)
            elif o == OP_AMAXL:
                self.stats["AMAXL"] += 1
                self.out_fifo.append(int(self.M.am_idx))
                self._xrf_set(XRF_TOK, self.M.am_idx)
            elif o == OP_JMP:
                self.stats["JMP"] += 1
                if r.flags & JMP_TCNT:
                    self.tcnt_seq -= 1
                    if self.tcnt_seq:
                        nxt = r.imm32
                else:
                    nxt = r.imm32
            elif o == OP_FENCE:
                self.stats["FENCE"] += 1
                self.running.clear()
            elif o == OP_HALT:
                break
            elif o == EXT_LDC:
                self.stats["LDC"] += 1
                a = ((r.len_or_addr_hi << 32) | r.addr_lo)
                if r.ind == SF.IND_ADD:
                    a += int(self.xrf[r.xrf])
                elif r.ind == SF.IND_SUB:
                    a -= int(self.xrf[r.xrf])
                nw = r.imm32
                self.M.mem[r.target:r.target + nw] = self._blob_words(a, nw)
            elif o == EXT_XOP:
                self.stats["XOP"] += 1
                # ISA v1.1 0x0C, v1.4 ruling D-1 (sign code 11 = decode err)
                self._xrf_set(r.target, SF.xop_eval(r.imm32, self.xrf))
            else:
                raise SF.SeqValidationError(f"unhandled opcode {o:#04x}")
            pc = nxt
            steps += 1
            if max_steps is not None and steps > max_steps:
                raise RuntimeError(f"SEQ ran past {max_steps} records "
                                   "(runaway JMP?)")
        return self


# ======================================================================
# .txt script replay (the reference side of the gate)
# ======================================================================
class TxtReplay(object):
    """Replay a host .txt script against a fresh Mach model.

    W / C / M / T / L records mutate the model; R / E / A records are
    ASSERTIONS and are checked (so a decode bug in this file cannot pass
    silently); V records are skipped (the engine is not modelled on this
    side — the .txt already carries the y32 in the following W32)."""

    def __init__(self, path, emb=None):
        self.path = path
        self.M = _fresh_mach()
        self.M.emb = emb
        self.tokens = []
        self.checks = {"R": 0, "E": 0, "A": 0, "V": 0}
        self.ncmd = 0
        self.cp_log = []          # every R record's values, in order
        self.nw = 0               # host-relayed words (the MMIO the SEQ kills)

    def run(self):
        M = self.M
        with open(self.path) as f:
            it = _TokenStream(f)
            for t in it:
                if t == "W":
                    a, n = int(it.next(), 16), int(it.next(), 16)
                    v = np.fromiter((int(it.next(), 16) for _ in range(n)),
                                    dtype=I64, count=n)
                    M.mem[a:a + n] = np.where(v >= 32768, v - 65536, v)
                    self.nw += n
                elif t == "C":
                    op = int(it.next(), 16)
                    a0 = int(it.next(), 16)
                    a1 = int(it.next(), 16)
                    a2 = int(it.next(), 16)
                    _TxtCmd(M)(op, a0, a1, a2)
                    self.ncmd += 1
                elif t == "R":
                    a, n = int(it.next(), 16), int(it.next(), 16)
                    v = np.fromiter((int(it.next(), 16) for _ in range(n)),
                                    dtype=I64, count=n)
                    got = M.mem[a:a + n] & 0xFFFF
                    assert np.array_equal(got, v), \
                        f"{self.path}: R {a:x} {n:x} mismatch"
                    self.cp_log.append(np.asarray(v, dtype=I64))
                    self.checks["R"] += 1
                elif t == "E":
                    e = int(it.next(), 16)
                    assert e == (M.eout & 0xFFFFFFFF), "E record mismatch"
                    self.checks["E"] += 1
                elif t == "T":
                    assert int(it.next(), 16) == 0
                    M.T[M.kv_slot] = [0, 0]
                elif t == "L":
                    v = int(it.next(), 16)
                    M.dn_slot, M.kv_slot = v & 0x1F, (v >> 8) & 0x7
                elif t == "M":
                    tok = int(it.next(), 16)
                    dst = int(it.next(), 16)
                    n = int(it.next(), 16)
                    M.mem[dst:dst + n] = np.asarray(M.emb[tok][:n], dtype=I64)
                elif t == "A":
                    i = int(it.next(), 16)
                    v = int(it.next(), 16)
                    assert i == M.am_idx and v == (int(M.am_val) & 0xFFFFFFFF),\
                        "A record mismatch"
                    self.tokens.append(int(i))
                    self.checks["A"] += 1
                elif t == "V":
                    it.next(), it.next(), it.next()
                    nr = int(it.next(), 16)
                    for _ in range(nr):
                        it.next()
                    self.checks["V"] += 1
                elif t == "Q":
                    break
                else:
                    raise ValueError(f"{self.path}: unknown record {t!r}")
        return self


class _TokenStream(object):
    """Whitespace token iterator over a large script file (streaming)."""

    def __init__(self, f):
        self.f = f
        self.buf = []
        self.i = 0

    def _fill(self):
        while self.i >= len(self.buf):
            chunk = self.f.read(1 << 20)
            if not chunk:
                return False
            # never split a token: pull the rest of the final line
            if not chunk.endswith("\n"):
                chunk += self.f.readline()
            self.buf = chunk.split()
            self.i = 0
        return True

    def next(self):
        if not self._fill():
            raise StopIteration
        v = self.buf[self.i]
        self.i += 1
        return v

    def __iter__(self):
        return self

    def __next__(self):
        return self.next()


class _TxtCmd(object):
    """Apply a .txt C record to a Mach model (shares SeqExec's decoder)."""

    def __init__(self, M):
        self.x = SeqExec.__new__(SeqExec)
        self.x.M = M
        self.x.xrf = [0] * XRF_N
        self.x.issued = 0
        self.x.eps_scale_log = []

    def __call__(self, op, a0, a1, a2):
        self.x.args = [a0, a1, a2]
        self.x._layer_cmd(op)


# ======================================================================
# gate
# ======================================================================
def gate(prefix, use_files=True, verbose=True, base=None):
    """Replay <base>.txt against <prefix>.seq and assert they agree.

    `base` defaults to `prefix`; giving it separately lets SEVERAL SEQ
    streams (one per profile / emitter option) share ONE set of generator
    artifacts (.txt, .weights.json, the weight images, .emb.bin), which is
    what makes an A/B of the emitter affordable on model_v2.
    """
    t0 = time.time()
    base = prefix if base is None else base
    meta = json.load(open(prefix + ".seq.json"))
    stream = open(prefix + ".seq", "rb").read()
    blob = open(prefix + ".seqdata.bin", "rb").read()
    assert hashlib.sha256(stream).hexdigest() == meta["stream_sha256"]
    assert hashlib.sha256(blob).hexdigest() == meta["seqdata_sha256"]
    recs = SF.unpack_stream(stream)
    SF.validate_stream(recs)

    embf = base + ".emb.bin"
    emb = None
    if os.path.exists(embf):
        n = os.path.getsize(embf) // 2048
        emb = np.memmap(embf, dtype="<i2", mode="r").reshape(n, 1024)

    if verbose:
        print(f"--- SEQ gate: {prefix}")
        print(f"  stream   {len(recs)} records, {len(stream)} B "
              f"(sha256 {meta['stream_sha256'][:16]})")
        print(f"  seqdata  {len(blob)} B "
              f"(sha256 {meta['seqdata_sha256'][:16]})")
        print(f"  profile  {meta['profile']}   newops from "
              f"{meta['newops_source']}")
        print(f"  opcodes  {meta['opcode_histogram']}")
        print(f"  loop     {meta['loop_steps']} steps  ({meta['loop_note']})"
              + ("" if not meta.get("loop_steps") else
                 ("  STRUCTURALLY SAFE" if meta.get("loop_structurally_safe")
                  else "  NOT structurally safe: the body still carries "
                       "data-dependent immediates (SEQ_ISA A3) that merely "
                       "coincided on this input")))

    ref = TxtReplay(base + ".txt", emb=emb).run()
    t1 = time.time()
    W = DDRWeights.from_files(base, meta["weights"])
    ex = SeqExec(recs, blob, W, emb=emb,
                 checkpoints=meta.get("checkpoints")).run(
                     max_steps=50 * len(recs))
    t2 = time.time()

    # --- 1. live-state checkpoints (every .txt R record, in order) -------
    cp_n = min(len(ref.cp_log), len(ex.cp_log))
    cp_bad = [i for i in range(cp_n)
              if not np.array_equal(ref.cp_log[i], ex.cp_log[i])]
    cp_ok = (len(ref.cp_log) == len(ex.cp_log)) and not cp_bad

    # --- 2. final architectural state -----------------------------------
    sa, sb = snapshot(ref.M), snapshot(ex.M)
    d = diff_state(sa, sb)
    # scratch differences are only legitimate INSIDE the y32 staging windows
    # the SEQ stream stops relaying through the host.
    stage = np.zeros(16384, dtype=bool)
    for (a, b) in meta.get("staging_words", []):
        stage[a:b] = True
    memdiff = np.nonzero(sa["mem"] != sb["mem"])[0]
    live_bad = [int(i) for i in memdiff if not stage[i]]
    d = [x for x in d if not x.startswith("mem:")]

    # --- 3. tokens -------------------------------------------------------
    tok_ok = (ref.tokens == ex.out_fifo)

    if verbose:
        print(f"  .txt     {ref.ncmd} commands, {ref.nw} host-relayed words, "
              f"checks {ref.checks} ({t1 - t0:.1f}s)")
        print(f"  .seq     {ex.issued} commands issued, movers "
              f"MOVX={ex.stats['MOVX']} MVGO={ex.stats['MVGO']} "
              f"MOVY={ex.stats['MOVY']} LDC={ex.stats['LDC']} "
              f"EMB={ex.stats['EMB']} AMAXL={ex.stats['AMAXL']} "
              f"({t2 - t1:.1f}s)")
        print(f"  CHECKPT  {len(ex.cp_log)}/{len(ref.cp_log)} live-state "
              f"checkpoints sampled, "
              f"{'ALL BIT-EXACT' if cp_ok else f'{len(cp_bad)} MISMATCH'}")
        print(f"  SCRATCH  {len(memdiff)} of 16384 words differ at the end; "
              f"{len(live_bad)} outside the declared y32 staging windows "
              f"({int(stage.sum())} words) -> "
              f"{'CLEAN' if not live_bad else 'DIVERGENCE'}")
        print(f"  BANKED   {'BIT-EXACT' if not d else 'MISMATCH'} "
              f"(conv/S/KV/TCNT/EOUT/AMAX)")
        for line in d[:12]:
            print(f"    ! {line}")
        print(f"  TOKENS   {'IDENTICAL' if tok_ok else 'MISMATCH'}  "
              f"{ex.out_fifo}")
    ok = cp_ok and (not d) and (not live_bad) and tok_ok
    return ok, {"nrec": len(recs), "stream_bytes": len(stream),
                "seqdata_bytes": len(blob), "txt_cmds": ref.ncmd,
                "txt_host_words": ref.nw, "seq_cmds": ex.issued,
                "checkpoints": len(ex.cp_log), "checkpoints_bad": len(cp_bad),
                "scratch_diff_words": int(len(memdiff)),
                "scratch_diff_outside_staging": len(live_bad),
                "tokens": ex.out_fifo, "tokens_ok": tok_ok,
                "diffs": d, "stats": ex.stats, "pass": bool(ok),
                "meta": meta}


# ======================================================================
# self-tests for the NEW ops (independent of any script)
# ======================================================================
def selftest_ops(seed=1):
    """DYNQ16 == (dn_o_shift immediate + vec_alu op 1), on random blocks;
    and EPS-NORM vs the frozen dn_norm_scale SCALE path."""
    import layer_fixed as LF
    rng = np.random.default_rng(seed)
    worst = 0
    nsame = ntot = 0
    for _ in range(200):
        n = 128
        # <= 24 bits: sum(o32^2) over 128 words must not overflow the int64
        # dn_norm_scale sums in (a pre-existing bound of the host path).
        mag = int(rng.integers(1, 24))
        o32 = (rng.integers(-(1 << mag), 1 << mag, n)).astype(I64)
        k_ref = LF.dn_o_shift(o32, note=False)
        y_ref = clip16(rs_s(o32, k_ref))
        y, k = SF.dynq16_fx(o32)
        assert k == k_ref, f"DYNQ16 k {k} != dn_o_shift {k_ref}"
        assert np.array_equal(y, y_ref), "DYNQ16 output != op-1 output"
        # eps-norm vs the frozen path
        m_ref = LF.dn_norm_scale(o32, k_ref, note=False)
        out_ref = clip16(rshr(y_ref * m_ref, 15))
        out = SF.eps_norm_fx(y, k, note=False)
        ntot += 1
        if np.array_equal(out, out_ref):
            nsame += 1
        worst = max(worst, int(np.abs(out - out_ref).max()))
    return {"blocks": ntot, "identical": nsame, "worst_abs_delta": worst}


def _selftest():
    print("dynq16/eps-norm semantics from:", SF.NEWOPS_SOURCE)
    r = selftest_ops()
    print(f"DYNQ16 == op1+dn_o_shift on {r['blocks']}/{r['blocks']} blocks")
    print(f"EPS-NORM vs frozen dn_norm_scale: {r['identical']}/{r['blocks']} "
          f"blocks bit-identical, worst |delta| = {r['worst_abs_delta']} LSB")
    return r


# ======================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gate", metavar="PREFIX",
                    help="replay <PREFIX>.txt and <PREFIX>.seq, assert "
                         "bit-identical final state + tokens")
    ap.add_argument("--base", metavar="PREFIX", default=None,
                    help="prefix of the generator artifacts (.txt, "
                         ".weights.json, .emb.bin) when they do not share "
                         "the .seq prefix; defaults to --gate")
    ap.add_argument("--disasm", metavar="PREFIX")
    ap.add_argument("-n", "--limit", type=int, default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    if a.selftest:
        _selftest()
    if a.disasm:
        recs = SF.unpack_stream(open(a.disasm + ".seq", "rb").read())
        print(SF.disasm_stream(recs, limit=a.limit))
    if a.gate:
        ok, rep = gate(a.gate, base=a.base)
        if a.json:
            with open(a.json, "w") as f:
                json.dump({k: v for k, v in rep.items() if k != "meta"}, f,
                          indent=1, default=str)
        print("SEQ GATE: " + ("PASS" if ok else "FAIL"))
        if not ok:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
