#!/usr/bin/env python3
"""infer.py — chat with the FPGA.

An interactive REPL that runs REAL, LIVE inference of the real
Qwen3.5-0.8B checkpoint through the 24-layer banked engine on the
BCU-1525.  Nothing about the answer is precomputed: the host tokenizes
the prompt, drives the layer_chan/matvec_chan CSRs command by command,
and the next token is the ON-CHIP argmax (AMAXI) read back out of the
accelerator.

------------------------------------------------------------------
The generator IS the schedule
------------------------------------------------------------------
ref/gen_model_script.py + ref/gen_layer_script.py already contain the
exact command sequence of a forward step -- they emit it into a text
script while maintaining a bit-exact scratchpad MODEL.  This tool keeps
BOTH halves and swaps the sink: `HwMach` subclasses `gen_layer_script.
Mach` and overrides only the record emitters (W/R/E/C/T/L/M/V/A) so
that they hit the real CSRs.  `dn_token`, `attn_token` and `mlp_block`
are imported from ref/ UNCHANGED and drive the board directly.

Every data-dependent immediate is taken from CHIP READBACK, not from
the model:
  * DYNQ8 exponent e_x                     -> EOUT CSR              (E)
  * matvec activations x8                  -> SWIN read             (R)
  * matvec accumulators y32                -> real engine, RES_DATA (V)
  * DeltaNet head output o32 (k_h, m_q15)  -> SWIN read after DNST
  * gated attention o32/sigmoid (k_a)      -> SWIN read after ATTN/ALU7
  * next token                             -> AMAXI CSR             (A)
so the model is a CHECKER, never a source.  Every one of those reads is
compared against the reference model as it happens (that comparison is
unconditional, --verify only adds the two EXPENSIVE references: the
host-side W4A8 matvec of every matrix, and ref/layer_fixed.py's
layer_decode_fx golden residual per layer).

------------------------------------------------------------------
Board safety
------------------------------------------------------------------
This tool NEVER programs the FPGA, never touches flash, never calls
pcie_helper/program_fpga and never runs sudo.  It refuses to touch DMA
until MAGIC / VERSION / CALIB / layer IDENT / all four matvec IDENTs
read back exactly right, and it only ever DMAs inside the documented
map of sw/hwmap.py (weight images from W_BASE, embedding table at
EMB_BASE, channel `--chan`).

Usage (on snoke; the board must already hold the expected netlist):
    cd sw
    ./.venv/bin/python infer.py                       # REPL
    ./.venv/bin/python infer.py --skip-upload         # weights resident
    ./.venv/bin/python infer.py --verify \
        --prompt "The capital of France" --ntok 3     # scripted gate
"""
import argparse
import json
import os
import re
import signal
import sys
import time
import unicodedata

import numpy as np

SW_DIR = os.path.dirname(os.path.abspath(__file__))
REF_DIR = os.path.join(os.path.dirname(SW_DIR), "ref")
sys.path.insert(0, SW_DIR)
sys.path.insert(0, REF_DIR)

from hwmap import (                                             # noqa: E402
    R_MAGIC, R_VERSION, R_CALIB, MAGIC, CALIB_ALL,
    R_CTRL, R_STATUS, R_WBASE_LO, R_WBASE_HI, R_WBEATS, R_SHAPE, shape_word,
    R_XWIN, R_XPTR, R_RES_PTR, R_RES_DATA, R_IDENT, MV_IDENT0, mv_base,
    MV_ST_DONE, MV_ST_ERR_RRESP, MV_ST_XOVFL,
    L_CMD, L_STAT, L_ARG0, L_ARG1, L_ARG2, L_SPTR, L_SWIN, L_EOUT,
    L_TCNT, L_IDENT, L_AMAXI, L_AMAXV, L_LAYER, LAYER_IDENT,
    L_ST_BUSY, L_ST_ERR_OP, SCRATCH_WORDS,
    CH_STRIDE, W_BASE, RES_DEPTH, EMB_BASE,
)
from layer_test import plan_weights                             # noqa: E402

import layer_ref as LR                                          # noqa: E402
import layer_fixed as LF                                        # noqa: E402
import load_qwen35 as LQ                                        # noqa: E402
from layer_fixed import RS_F                                    # noqa: E402
from w4a8_ref import matvec_y32, pack_ddr_rows, G               # noqa: E402
from gen_layer_script import (Mach, dn_token, attn_token,       # noqa: E402
                              X0, XN, X8, STG, I64)
from gen_token_script import slot_plan                          # noqa: E402
from gen_model_script import (quant_linear_big, ROWCHUNK, Tok,  # noqa: E402
                              PROMPTS, _tokenizer_path, _bytes_to_unicode)

# The netlist this tool was gated against (build_028_rr_SSI_HighUtilSLRs).
EXPECT_VERSION = 0x33D720E5  # build_033 (rung4 zero-bubble + TOPK)
KV_DEPTH = 512            # rtl/layer_chan.sv: kv_waddr uses tcnt[8:0]
DEFAULT_MODEL = os.path.join(os.path.dirname(SW_DIR), "tb", "scripts",
                             "model_v2_s1")


class Mismatch(RuntimeError):
    """A chip readback disagreed with the bit-exact reference."""


# ======================================================================
# device
# ======================================================================
class Dev:
    """XDMA AXI-Lite CSR + DMA access, with the board-safety gate."""

    def __init__(self, path="/dev/xdma0", chan=0, expect_version=EXPECT_VERSION):
        self.chan = chan
        self.n_mmio_rd = 0
        self.n_mmio_wr = 0
        self.user = os.open(f"{path}_user", os.O_RDWR)
        self.ident = self._safety_check(expect_version)
        # DMA fds are opened only AFTER the identity gate passes
        self.h2c = os.open(f"{path}_h2c_0", os.O_WRONLY)
        self.c2h = os.open(f"{path}_c2h_0", os.O_RDONLY)
        self.mb = mv_base(chan)

    # ---------------- raw MMIO ----------------
    def rd(self, a):
        self.n_mmio_rd += 1
        return int.from_bytes(os.pread(self.user, 4, a), "little")

    def wr(self, a, v):
        self.n_mmio_wr += 1
        os.pwrite(self.user, int(v).to_bytes(4, "little"), a)

    def _safety_check(self, expect_version):
        rd = self.rd
        magic, ver, calib = rd(R_MAGIC), rd(R_VERSION), rd(R_CALIB)
        li = rd(L_IDENT)
        mvi = [rd(mv_base(c) + R_IDENT) for c in range(4)]
        bad = []
        if magic != MAGIC:
            bad.append(f"MAGIC={magic:#010x} want {MAGIC:#010x}")
        if expect_version is not None and ver != expect_version:
            bad.append(f"VERSION={ver:#010x} want {expect_version:#010x}")
        if calib != CALIB_ALL:
            bad.append(f"CALIB={calib:#x} want {CALIB_ALL:#x}")
        if li != LAYER_IDENT:
            bad.append(f"layer IDENT={li:#010x} want {LAYER_IDENT:#010x}")
        for c, v in enumerate(mvi):
            if v != MV_IDENT0 + c:
                bad.append(f"matvec{c} IDENT={v:#010x} want {MV_IDENT0 + c:#010x}")
        if bad:
            os.close(self.user)
            raise SystemExit("REFUSING TO TOUCH THE BOARD — identity gate "
                             "failed:\n  " + "\n  ".join(bad)
                             + "\n(this tool never programs the FPGA; fix the "
                               "resident bitstream out of band)")
        return {"magic": magic, "version": ver, "calib": calib,
                "layer_ident": li, "mv_ident": mvi}

    # ---------------- layer_chan scratch window ----------------
    def read_raw(self, addr, n):
        """n scratch words at addr as RAW uint16 bit patterns."""
        self.wr(L_SPTR, addr)
        pr, u, a = os.pread, self.user, L_SWIN
        buf = b"".join([pr(u, 4, a) for _ in range(n)])
        self.n_mmio_rd += n
        return np.frombuffer(buf, dtype="<u4").astype(np.int64) & 0xFFFF

    def read_scratch(self, addr, n):
        """n scratch words at addr, sign-extended int16 (as int64)."""
        v = self.read_raw(addr, n)
        return np.where(v >= 32768, v - 65536, v)

    def read_pairs(self, addr, n):
        """n int32 {lo,hi} scratch pairs at addr (Mach.pairs semantics)."""
        raw = self.read_raw(addr, 2 * n)
        v = raw[0::2] | (raw[1::2] << 16)
        return np.where(v >= (1 << 31), v - (1 << 32), v)

    def write_scratch(self, addr, vals):
        """Write int16 words (any int dtype; masked to 16 bits) at addr."""
        v = (np.asarray(vals, dtype=np.int64) & 0xFFFF).astype("<u4")
        self.wr(L_SPTR, addr)
        buf = memoryview(v.tobytes())
        pw, u, a = os.pwrite, self.user, L_SWIN
        for i in range(0, len(buf), 4):
            pw(u, buf[i:i + 4], a)
        self.n_mmio_wr += len(v)

    # ---------------- layer_chan command ----------------
    def cmd(self, op, a0, a1, a2, timeout=10.0):
        self.wr(L_ARG0, a0)
        self.wr(L_ARG1, a1)
        self.wr(L_ARG2, a2)
        cnt0 = self.rd(L_STAT) >> 16
        self.wr(L_CMD, op)
        t0 = time.monotonic()
        while True:
            st = self.rd(L_STAT)
            if (st >> 16) == ((cnt0 + 1) & 0xFFFF) and not (st & L_ST_BUSY):
                break
            if time.monotonic() - t0 > timeout:
                raise RuntimeError(f"layer_chan op {op} timeout STATUS={st:08x}")
        if st & L_ST_ERR_OP:
            raise RuntimeError(f"layer_chan op {op}: err_op")

    # ---------------- matvec engine ----------------
    def run_matvec(self, man, wbase_of, wid, x8_words):
        """Run weight image `wid` on the real engine; chunk rows > RES_DEPTH.

        Deliberately identical to sw/layer_test.py's V-record handler; that
        one is a closure inside main() and cannot be imported, so it is
        reproduced here (same CSR order, same chunking, same status checks).
        """
        m = man[str(wid)] if str(wid) in man else man[wid]
        nrows, ng, sh, stride = m["nrows"], m["ng"], m["sh"], m["stride"]
        g = int(m.get("g", 128))
        xb = bytes((int(w) & 0xFF) for w in x8_words)
        xb += b"\x00" * (-len(xb) % 4)
        mb = self.mb
        out = np.zeros(nrows, dtype=np.int64)
        r0 = 0
        while r0 < nrows:
            rc = min(RES_DEPTH, nrows - r0)
            wbase = wbase_of[int(wid)] + r0 * stride
            self.wr(mb + R_WBASE_LO, wbase & 0xFFFFFFFF)
            self.wr(mb + R_WBASE_HI, wbase >> 32)
            self.wr(mb + R_WBEATS, rc * stride // 64)
            self.wr(mb + R_SHAPE, shape_word(rc, sh, ng, g))
            self.wr(mb + R_XPTR, 0)
            pw, u, xa = os.pwrite, self.user, mb + R_XWIN
            mv = memoryview(xb)
            for i in range(0, len(xb), 4):
                pw(u, mv[i:i + 4], xa)
            self.n_mmio_wr += len(xb) // 4
            t0 = time.monotonic()
            self.wr(mb + R_CTRL, 1)
            while True:
                st = self.rd(mb + R_STATUS)
                if st & MV_ST_DONE:
                    break
                if time.monotonic() - t0 > 10:
                    raise RuntimeError(f"matvec wid={wid} timeout "
                                       f"STATUS={st:x}")
            if st & (MV_ST_ERR_RRESP | MV_ST_XOVFL):
                raise RuntimeError(f"matvec wid={wid} STATUS={st:x}")
            self.wr(mb + R_RES_PTR, 0)
            pr, ra = os.pread, mb + R_RES_DATA
            buf = b"".join([pr(u, 4, ra) for _ in range(rc)])
            self.n_mmio_rd += rc
            v = np.frombuffer(buf, dtype="<u4").astype(np.int64)
            out[r0:r0 + rc] = np.where(v >= (1 << 31), v - (1 << 32), v)
            r0 += rc
        return out

    # ---------------- DDR ----------------
    def dma_write(self, addr, data):
        n = os.pwrite(self.h2c, data, self.chan * CH_STRIDE + addr)
        assert n == len(data), f"short DMA write {n}/{len(data)} @ {addr:#x}"

    def read_emb(self, tokid, n):
        """Embedding row `tokid` (n int16) straight out of device DDR."""
        row = os.pread(self.c2h, n * 2,
                       self.chan * CH_STRIDE + EMB_BASE + tokid * n * 2)
        assert len(row) == n * 2
        return np.frombuffer(row, dtype="<i2").astype(np.int64)


# ======================================================================
# tokenizer: byte-level BPE encode + the ref decoder
# ======================================================================
_UNI_CACHE = {}


def _uni_ranges(first_cat, maxcp=0x110000):
    """Character-class ranges for a Unicode general-category initial.

    Python's `re` has no \\p{...}; the ranges are derived from
    unicodedata.category so the classes are EXACTLY \\p{L}/\\p{M}/\\p{N}
    over the whole code space (no `regex` dependency — this venv, like
    ref/load_qwen35.py, is numpy-only).
    """
    hit = _UNI_CACHE.get(first_cat)
    if hit is not None:
        return hit
    out, start, cat = [], None, unicodedata.category
    for cp in range(maxcp):
        if cat(chr(cp))[0] == first_cat:
            if start is None:
                start = cp
        elif start is not None:
            out.append((start, cp - 1))
            start = None
    if start is not None:
        out.append((start, maxcp - 1))
    _UNI_CACHE[first_cat] = out
    return out


def _cls(*cats):
    """Body of a regex character class covering the given categories."""
    s = []
    for c in cats:
        for a, b in _uni_ranges(c):
            s.append("\\U%08x" % a if a == b
                     else "\\U%08x-\\U%08x" % (a, b))
    return "".join(s)


class BpeTok(Tok):
    """Full byte-level BPE tokenizer over the checkpoint's tokenizer.json.

    `Tok` (ref/gen_model_script.py) already provides the id<->piece view and
    the decoder; this adds the ENCODER, which the REPL needs because the
    prompt is free text.  The pre-tokenizer regex, the byte-level alphabet
    and the merge ranks are read out of tokenizer.json, so the encoder is
    the checkpoint's, not a guess.  `self_test()` re-derives the four
    hard-coded gen_model_script PROMPTS and refuses to run if any differs.
    """

    def __init__(self, path):
        super().__init__(path)
        tk = json.load(open(path))
        mdl = tk["model"]
        assert mdl["type"] == "BPE" and not mdl.get("ignore_merges", False)
        assert not mdl.get("byte_fallback", False)
        self.ranks = {}
        for i, mg in enumerate(mdl["merges"]):
            a, b = mg if isinstance(mg, (list, tuple)) else mg.split(" ")
            self.ranks[(a, b)] = i
        self.b2u = _bytes_to_unicode()
        # tokenizer.json pre_tokenizer: NFC, then this Split (Isolated),
        # then ByteLevel(add_prefix_space=false, use_regex=false).
        L, M, N = _cls("L"), _cls("M"), _cls("N")
        self.pat = re.compile(
            "(?i:'s|'t|'re|'ve|'m|'ll|'d)"
            "|[^\\r\\n" + L + N + "]?[" + L + M + "]+"
            "|[" + N + "]"
            "| ?[^\\s" + L + M + N + "]+[\\r\\n]*"
            "|\\s*[\\r\\n]+"
            "|\\s+(?!\\S)"
            "|\\s+")
        self._cache = {}

    def _bpe(self, tok):
        hit = self._cache.get(tok)
        if hit is not None:
            return hit
        word = list(tok)
        while len(word) > 1:
            best, bi = None, -1
            for i in range(len(word) - 1):
                r = self.ranks.get((word[i], word[i + 1]))
                if r is not None and (best is None or r < best):
                    best, bi = r, i
            if bi < 0:
                break
            word[bi:bi + 2] = [word[bi] + word[bi + 1]]
        self._cache[tok] = word
        return word

    def encode(self, text):
        ids = []
        for piece in self.pat.findall(unicodedata.normalize("NFC", text)):
            if not piece:
                continue
            s = "".join(self.b2u[b] for b in piece.encode("utf-8"))
            for sub in self._bpe(s):
                tid = self.vocab.get(sub)
                if tid is None:
                    raise ValueError(f"BPE produced out-of-vocab piece {sub!r}")
                ids.append(tid)
        return ids

    def self_test(self):
        for k in sorted(PROMPTS):
            text, _pieces, ids = PROMPTS[k]
            got = self.encode(text)
            if got != list(ids):
                raise SystemExit(
                    f"tokenizer self-test FAILED on prompt {k} {text!r}: "
                    f"encode -> {got}, gen_model_script hardcodes {ids}")
        return len(PROMPTS)


# ======================================================================
# the live machine: gen_layer_script.Mach with the CSRs as its sink
# ======================================================================
# ======================================================================
# chat template (docs/INSTRUCT_SPEC.md) — IMPORTED, never restated here
# ======================================================================
# sw/chat_seq.py owns the one wrapper builder and the one stop-id set.
# infer.py is the legacy per-MMIO reference path; it borrows both rather
# than growing a second copy that can drift.  The import is lazy so a
# tokenizer-only run (--tok-test) never pays for chat_seq's module graph.
def _chat_seq():
    import chat_seq as CS                                       # noqa: N806
    return CS


def chat_stop_ids():
    """docs/INSTRUCT_SPEC.md T6: {<|endoftext|>, <|im_end|>}."""
    try:
        return frozenset(_chat_seq().CHAT_STOP_IDS)
    except Exception as e:                                      # noqa: BLE001
        raise SystemExit(f"sw/chat_seq.py is required for the frozen chat "
                         f"stop ids (docs/INSTRUCT_SPEC.md T6): {e}")


def chat_template(tk):
    """chat_seq.ChatTemplate over this tokenizer (--chat)."""
    return _chat_seq().ChatTemplate(tk)


class _NoEmit:
    def write(self, s):
        raise RuntimeError("HwMach: un-overridden script emitter reached: "
                           + repr(s[:60]))


class HwMach(Mach):
    """Mach whose record emitters drive the board, and whose data-dependent
    values come from chip readback.  Everything else (command encodings,
    scratch map, the scratchpad model) is inherited unchanged."""

    # attn_token's own AO32 / OG scratch buffers, reused for the k_a peek
    # pass (both are dead scratch at that point in the token; see the
    # attn_peek/sigm_peek overrides).
    PEEK_AO32 = STG
    PEEK_OG = STG + 512

    def __init__(self, dev, man, wbase_of, wid_order, verify):
        super().__init__(_NoEmit())
        self.dev = dev
        self.man = man
        self.wbase_of = wbase_of
        self.verify = verify
        self.nchk = 0
        self.nmv = 0
        self.hw_amax = (0, 0)
        # wid assignment is FIXED up front from the emission order and
        # cross-checked against the manifest, instead of emerging from
        # first-use like the script generator's.
        for i, qw in enumerate(wid_order):
            self.wids[id(qw)] = (i, qw)
            self._check_manifest(i, qw)

    # ---------------- checking ----------------
    def _chk(self, tag, got, want):
        g = np.atleast_1d(np.asarray(got, dtype=I64))
        w = np.atleast_1d(np.asarray(want, dtype=I64))
        self.nchk += int(g.size)
        if g.shape != w.shape:
            raise Mismatch(f"{tag}: shape {g.shape} vs {w.shape}")
        if not np.array_equal(g, w):
            d = np.nonzero(np.ravel(g != w))[0]
            i = int(d[0])
            raise Mismatch(f"{tag}: {d.size}/{g.size} words differ "
                           f"(first at {i}: chip {int(np.ravel(g)[i])} != "
                           f"ref {int(np.ravel(w)[i])})")

    def _check_manifest(self, wid, qw):
        m = self.man[str(wid)]
        n, k = qw["w4"].shape
        bad = [f"{f}: manifest {m[f]} != model {v}"
               for f, v in (("nrows", n), ("k", k),
                            ("e", int(qw["e"])), ("sh", int(qw["sh"])))
               if int(m[f]) != int(v)]
        if int(m.get("g", 128)) != int(qw.get("g", 128)):
            bad.append(f"g: manifest {m.get('g', 128)} != model {qw.get('g')}")
        if bad:
            raise SystemExit(f"weight image wid={wid} ({m['file']}) does not "
                             "match this quantization: " + "; ".join(bad))

    # ---------------- record emitters -> hardware ----------------
    def W(self, addr, vals):
        vals = np.asarray(vals, dtype=I64)
        assert np.all(vals >= -32768) and np.all(vals <= 32767), "W range"
        assert addr + len(vals) <= SCRATCH_WORDS
        self.mem[addr:addr + len(vals)] = vals
        self.dev.write_scratch(addr, vals)
        self.nw += len(vals)

    def R(self, addr, n):
        got = self.dev.read_scratch(addr, n)
        self._chk(f"R[{addr:#x}+{n}]", got & 0xFFFF,
                  self.mem[addr:addr + n] & 0xFFFF)
        return got

    def E(self):
        got = self.dev.rd(L_EOUT) & 0xF
        self._chk("EOUT", got, self.eout)
        self.eout = int(got)          # the LIVE exponent drives shift_for

    def C(self, op, a0, a1, a2):
        assert 0 <= a0 < (1 << 32) and 0 <= a1 < (1 << 32) and 0 <= a2 < (1 << 32)
        self.dev.cmd(op, a0, a1, a2)
        self.ncmd += 1

    def Treset(self):
        self.T[self.kv_slot] = [0, 0]
        self.dev.wr(L_TCNT, 0)

    def layer(self, dn_slot, kv_slot):
        assert 0 <= dn_slot < 18 and 0 <= kv_slot < 6
        self.dn_slot, self.kv_slot = dn_slot, kv_slot
        self.dev.wr(L_LAYER, (kv_slot << 8) | dn_slot)

    def embed(self, tokid, dst, n):
        row = self.dev.read_emb(tokid, n)          # M record: DDR -> host
        if self.emb is not None:
            self._chk(f"emb[{tokid}]", row,
                      np.asarray(self.emb[tokid][:n], dtype=I64))
        self.mem[dst:dst + n] = row
        self.dev.write_scratch(dst, row)
        self.nw += n

    def A(self):
        gi = self.dev.rd(L_AMAXI) & 0x3FFFF
        gv = self.dev.rd(L_AMAXV)
        self._chk("AMAXI", gi, self.am_idx)
        self._chk("AMAXV", gv, int(self.am_val) & 0xFFFFFFFF)
        self.hw_amax = (int(gi), int(gv))

    # ---------------- data-dependent readback points ----------------
    def matvec(self, qw, x8_addr, n_in, rowchunk=None):
        """V record, executed for real: assert the on-chip x8/e_x, run the
        weight image on the matvec engine, return the hardware y32."""
        ent = self.wids.get(id(qw))
        if ent is None:
            raise RuntimeError("matvec on a matrix outside the planned "
                               "wid order — emission order drifted")
        wid = ent[0]
        x8 = self.R(x8_addr, n_in)                 # chip activations
        self.E()                                   # chip exponent
        y32 = self.dev.run_matvec(self.man, self.wbase_of, wid,
                                  (x8 & 0xFF).tolist())
        if self.verify:
            self._chk(f"y32 wid={wid}", y32,
                      self._ref_matvec(qw, x8.astype(np.int8), rowchunk))
        self.nmv += 1
        return y32, self.eout

    @staticmethod
    def _ref_matvec(qw, x8, rowchunk):
        """gen_layer_script.Mach.matvec's host reference, verbatim."""
        nrows = qw["w4"].shape[0]
        g = int(qw.get("g", 128))
        if rowchunk is None or rowchunk >= nrows:
            return np.asarray(matvec_y32(qw["w4"], qw["m"], qw["sh"], x8, g=g),
                              dtype=I64)
        parts = []
        for r0 in range(0, nrows, rowchunk):
            r1 = min(r0 + rowchunk, nrows)
            parts.append(np.asarray(
                matvec_y32(qw["w4"][r0:r1], qw["m"][r0:r1], qw["sh"], x8, g=g),
                dtype=I64))
        return np.concatenate(parts)

    def dnst(self, head, src_q, src_k, src_v, a_dec, a_beta, dst):
        super().dnst(head, src_q, src_k, src_v, a_dec, a_beta, dst)
        got = self.dev.read_pairs(dst, 128)        # the o32 k_h/m_q15 read
        self._chk(f"o32 DNST h={head}", got, self.pairs(dst, 128))
        self.set_pairs(dst, got)

    def attn(self, kvh, src_q, dst):
        super().attn(kvh, src_q, dst)
        got = self.dev.read_pairs(dst, 256)
        self._chk(f"o32 ATTN kvh={kvh}", got, self.pairs(dst, 256))
        self.set_pairs(dst, got)

    def attn_peek(self, kvh, src_q):
        """attn_token peeks every head to pick the shared k_a.  There is no
        peek on silicon: run the REAL ATTN command into attn_token's own
        AO32 buffer (idempotent — ATTN reads the KV cache and mutates
        nothing) and read the o32 back."""
        self.attn(kvh, src_q, self.PEEK_AO32)
        return self.pairs(self.PEEK_AO32, 256)

    def sigm_peek(self, n, p0, srca):
        """Same idea for the output gate: run the real ALU op-7 into
        attn_token's OG buffer and read it back."""
        ref = super().sigm_peek(n, p0, srca)
        self.alu(7, n, p0, srca, 0, self.PEEK_OG)
        got = self.dev.read_scratch(self.PEEK_OG, n)
        self._chk("SIGM peek", got, self.mem[self.PEEK_OG:self.PEEK_OG + n])
        self._chk("SIGM peek(ref)", got, ref)
        return got


# ======================================================================
# the model
# ======================================================================
def wid_order_of(layers, qw_head):
    """Matrices in the exact order gen_model_script first matvecs them.

    dn_token : in_qkv, in_z, in_b, in_a, out, then mlp gate/up/down
    attn_token: q_proj, k_proj, v_proj, o_proj, then mlp gate/up/down
    then the LM head, once, after the last layer of step 0.
    """
    order = []
    for (lt, qw, _cache, _dn, _kv) in layers:
        if lt == "full_attention":
            a = qw["attn"]
            order += [a["q_proj"], a["k_proj"], a["v_proj"], a["o_proj"]]
        else:
            d = qw["dn"]
            order += [d["in_qkv"], d["in_z"], d["in_b"], d["in_a"], d["out"]]
        m = qw["mlp"]
        order += [m["gate"], m["up"], m["down"]]
    order.append(qw_head)
    return order


class FpgaModel:
    def __init__(self, dev, args, log=print):
        self.dev, self.args, self.log = dev, args, log
        self.verify = args.verify
        self.pos = 0                 # forward steps consumed == KV depth
        self.next_in = None          # token to feed first on the next turn
        self.tok_times = []
        # docs/INSTRUCT_SPEC.md T6: generation stops on {endoftext, im_end}.
        # The set is IMPORTED, never restated — sw/chat_seq.py owns it.
        self.stop_ids = chat_stop_ids()
        self.tmpl_turns = 0          # templated turns since the last reset

        prefix = args.model
        self.man = json.load(open(f"{prefix}.weights.json"))
        self.wdir = os.path.dirname(os.path.abspath(prefix))
        self.wbase_of, wtop = plan_weights(self.man, self.wdir)
        self.log(f"  weight plan: {len(self.man)} images, "
                 f"{wtop - W_BASE} bytes packed {W_BASE:#x}..{wtop:#x}")

        t0 = time.monotonic()
        self._load_and_quantize()
        self.log(f"  quantization done in {time.monotonic() - t0:.1f}s")

        if not args.skip_upload:
            self._upload(prefix)
        else:
            self.log("  --skip-upload: assuming the weight images and the "
                     "embedding table are already resident in DDR")

        self.M = HwMach(dev, self.man, self.wbase_of,
                        wid_order_of(self.layers, self.qw_head), self.verify)
        self.M.emb = self.emb_q
        self.reset()

    # ---------------- weights ----------------
    def _load_and_quantize(self):
        a = self.args
        md = LQ.load_model()
        cfg, types = md["config"], md["layer_types"]
        self.vocab = int(cfg["vocab_size"])
        assert self.vocab <= (1 << 18), "vocab exceeds the 18-bit AMAXI port"
        self.ckpt = md["path"]
        self.ckpt_sha = md["header_sha256"]
        self.log(f"  checkpoint {os.path.basename(md['path'])}\n"
                 f"    header sha256 {md['header_sha256']}\n"
                 f"    {len(types)} layers, H={LR.H}, vocab={self.vocab}, "
                 f"res_scale={a.res_scale} w4_group={a.w4_group} "
                 f"DN_NORM_F={LF.DN_NORM_F} M_Q15_MAX={LF.M_Q15_MAX}")
        slots = slot_plan(types)
        self.layers = []
        for i, (lt, dn_slot, kv_slot) in enumerate(slots):
            wf = md["layers"][i]
            assert wf["type"] == lt
            qw = LF.quant_layer(wf, res_scale=a.res_scale, g=a.w4_group)
            md["layers"][i] = None
            self.layers.append((lt, qw, LF.new_cache_fx(lt), dn_slot, kv_slot))
        ndn = sum(1 for l in self.layers if l[0] != "full_attention")
        self.log(f"    quantized {len(self.layers)} layers "
                 f"({ndn} DeltaNet / {len(self.layers) - ndn} GQA)")

        # final RMSNorm folded to (1+w) Q3.12, run through vecnorm mode 1
        self.ln_f_q12 = np.round((1.0 + np.asarray(md["ln_f"], dtype=np.float64))
                                 * (1 << 12)).astype(I64)
        assert int((np.abs(self.ln_f_q12) > 32767).sum()) == 0

        emb_f = md["emb"]
        self.qw_head = quant_linear_big(emb_f, g=a.w4_group)
        emb_q = np.empty((self.vocab, LR.H), dtype="<i2")
        for r0 in range(0, self.vocab, ROWCHUNK):
            r1 = min(r0 + ROWCHUNK, self.vocab)
            emb_q[r0:r1] = np.clip(
                np.round(np.asarray(emb_f[r0:r1], dtype=np.float64)
                         * np.float64(a.res_scale) * (1 << RS_F)),
                -32768, 32767).astype("<i2")
        md["emb"] = emb_f = None
        assert int((np.abs(emb_q) >= 32767).sum()) == 0
        self.emb_q = emb_q
        self.log(f"    LM head {self.qw_head['w4'].shape} e={self.qw_head['e']} "
                 f"sh={self.qw_head['sh']}; emb |q|max "
                 f"{int(np.abs(emb_q).max())} of 32767")

        # the embedding IMAGE on the board must be exactly this table
        embf = f"{self.args.model}.emb.bin"
        ref = np.memmap(embf, dtype="<i2", mode="r").reshape(self.vocab, LR.H)
        if not np.array_equal(np.asarray(ref), emb_q):
            raise SystemExit(f"{embf} does not match this quantization "
                             f"(res_scale={a.res_scale})")
        self.log(f"    {os.path.basename(embf)} matches the freshly "
                 f"quantized embedding table (248320x1024, bit-exact)")

    def _upload(self, prefix):
        dev, man = self.dev, self.man
        order = wid_order_of(self.layers, self.qw_head)
        t0 = time.monotonic()
        nby = 0
        for wid, m in sorted(man.items(), key=lambda kv: int(kv[0])):
            img = open(os.path.join(self.wdir, m["file"]), "rb").read()
            if self.args.check_images:
                qw = order[int(wid)]
                mine, stride = pack_ddr_rows(qw["w4"], qw["m"],
                                             g=int(qw.get("g", 128)))
                if stride != int(m["stride"]) or mine != img:
                    raise SystemExit(f"weight image {m['file']} differs from "
                                     "the freshly quantized matrix")
            dev.dma_write(self.wbase_of[int(wid)], img)
            nby += len(img)
        embf = f"{prefix}.emb.bin"
        emb = open(embf, "rb").read()
        dev.dma_write(EMB_BASE, emb)
        nby += len(emb)
        chk = " (byte-compared vs the live quantization)" if \
            self.args.check_images else ""
        self.log(f"  uploaded {len(man)} weight images + the embedding table"
                 f"{chk}: {nby / 2**20:.0f} MiB in "
                 f"{time.monotonic() - t0:.1f}s")

    # ---------------- session ----------------
    def reset(self):
        """Session preamble: prime every layer's banked state (conv weights,
        zeroed conv state, zeroed DeltaNet state, T=0)."""
        M = self.M
        t0 = time.monotonic()
        for (lt, qw, cache, dn_slot, kv_slot) in self.layers:
            M.layer(dn_slot, kv_slot)
            if lt == "full_attention":
                M.Treset()
                M.kc[kv_slot] = [[], []]
                M.vc[kv_slot] = [[], []]
            else:
                qd = qw["dn"]
                for c in range(0, LR.CONV_DIM, 2048):
                    M.W(STG, qd["conv_w"][c:c + 2048].reshape(-1))
                    M.convw(c, 2048, STG)
                M.convz(0, LR.CONV_DIM)
                for h in range(LR.LNH):
                    M.dnz(h)
            if self.verify:
                cache.clear()
                cache.update(LF.new_cache_fx(lt))
        self.pos = 0
        self.next_in = None
        self.tok_times = []
        self.tmpl_turns = 0
        self.log(f"  session preamble: 24 layer banks primed in "
                 f"{time.monotonic() - t0:.1f}s")

    # ---------------- one forward step ----------------
    def step(self, tok, pos):
        M = self.M
        M.embed(tok, X0, LR.H)
        x = np.asarray(self.emb_q[tok], dtype=I64) if self.verify else None
        for (lt, qw, cache, dn_slot, kv_slot) in self.layers:
            M.layer(dn_slot, kv_slot)
            # verify: the independent layer_fixed golden residual.
            # live:   a VIEW of the on-chip residual, so ref/'s own
            #         self-check degenerates to a tautology and the
            #         readback comparisons above carry the proof.
            gold = (LF.layer_decode_fx(x, qw, cache, pos) if self.verify
                    else M.mem[X0:X0 + LR.H])
            if lt == "full_attention":
                attn_token(M, qw["attn"], qw["ln1"], qw["ln2"], qw["mlp"],
                           pos, gold)
            else:
                dn_token(M, qw["dn"], qw["ln1"], qw["ln2"], qw["mlp"], gold)
            if self.verify:
                x = gold
        # final RMSNorm (plain-w mode 1, pre-folded (1+w) Q3.12) + DYNQ8
        M.W(STG, self.ln_f_q12)
        M.vnw_(STG, 1024)
        M.vn(1, 1024, RS_F, RS_F, X0, XN)
        M.alu(0, 1024, 0, XN, 0, X8)
        # full-vocab LM head + chunked on-chip argmax
        y32, _ = M.matvec(self.qw_head, X8, 1024, rowchunk=ROWCHUNK)
        for c in range(0, self.vocab, 2048):
            n = min(2048, self.vocab - c)
            M.W32(STG, y32[c:c + n])
            M.amax(n, STG, fresh=(c == 0))
        M.A()                                    # <- the next token, on-chip
        if self.verify:
            host = int(np.argmax(np.asarray(y32)))
            if host != M.hw_amax[0]:
                raise Mismatch(f"on-chip argmax {M.hw_amax[0]} != host argmax "
                               f"{host}")
        return M.hw_amax[0]

    # ---------------- generation ----------------
    def generate(self, feed_ids, ntok, on_prefill=None, on_token=None,
                 stop=lambda: False):
        """Prefill `feed_ids`, then decode up to `ntok` tokens.

        docs/INSTRUCT_SPEC.md T6: generation now STOPS on the chat stop
        ids (<|endoftext|>, <|im_end|>).  Before this it had no stop
        condition at all and ran straight past <|im_end|> into whatever
        the model said next — which, with the template on, is the start
        of a hallucinated user turn.
        """
        nsteps = len(feed_ids) + ntok - 1
        if self.pos + nsteps > self.args.max_ctx:
            raise ValueError(
                f"context would reach {self.pos + nsteps} forward steps; the "
                f"KV cache banks hold {KV_DEPTH} (limit here {self.args.max_ctx})"
                " — use /reset to start a fresh conversation")
        out = []
        self.stopped = None
        tok = feed_ids[0]
        for i in range(nsteps):
            t0 = time.monotonic()
            nxt = self.step(tok, self.pos)
            dt = time.monotonic() - t0
            self.pos += 1
            if i < len(feed_ids) - 1:
                if on_prefill:
                    on_prefill(tok, dt)
            else:
                out.append(nxt)
                self.tok_times.append(dt)
                if on_token:
                    on_token(nxt, dt)
                if int(nxt) in self.stop_ids:          # T6
                    self.stopped = "EOS"
                    break
            tok = feed_ids[i + 1] if i + 1 < len(feed_ids) else nxt
            if stop():
                break
        if out:
            self.next_in = out[-1]
        return out


# ======================================================================
# banner
# ======================================================================
POSTURE = """\
POSTURE — read this before believing the text
  This model runs at its KNOWN SATURATION posture: ref/gen_model_script.py
  refuses to bless a script for these weights without --allow-clip, because
  two frozen fixed-point formats saturate on the real checkpoint —
    * the DeltaNet state S_F=13 (int16 Q2.13) — |S| reaches ~5.5 where the
      format stops at 4.0 (28 saturating writes per 4-prompt soak), and
    * 3 of 288 DeltaNet heads clamp dt_bias / A at the gate_unit ports.
  The RTL and ref/layer_fixed.py clip IDENTICALLY, so everything this tool
  reports is still BIT-EXACT; what saturation costs is numerical fidelity to
  the bf16 model, not correctness.  Measured quality: 16/24 top-1 vs bf16
  (evidence/stage5/fidelity_mq15_prod.log).  Expect plausible English, not
  bf16-class answers.
  Sampling is pure greedy argmax, computed ON CHIP (layer_chan AMAXI).\
"""


def banner(dev, mdl, log=print):
    i = dev.ident
    log("=" * 72)
    log("fable5_llm — live LLM inference on the BCU-1525")
    log("=" * 72)
    log(f"board   /dev/xdma0 chan {dev.chan}: MAGIC {i['magic']:#010x}  "
        f"VERSION {i['version']:#010x}  CALIB {i['calib']:#x}")
    log(f"        layer_chan IDENT {i['layer_ident']:#010x}  matvec IDENTs "
        + " ".join(f"{v:#010x}" for v in i["mv_ident"]))
    log(f"model   Qwen3.5-0.8B, 24 layers (18 DeltaNet / 6 GQA), "
        f"vocab {mdl.vocab}")
    log(f"        W4A8 g={mdl.args.w4_group}, res_scale={mdl.args.res_scale}, "
        f"DN_NORM_F={LF.DN_NORM_F}, S_F={LF.S_F}, M_Q15_MAX={LF.M_Q15_MAX}")
    log(f"        images {os.path.basename(mdl.args.model)}.*  "
        f"checkpoint sha256 {mdl.ckpt_sha[:16]}...")
    if mdl.verify:
        v = ("FULL LOCKSTEP — every chip readback (x8, EOUT, o32, y32 rows, "
             "argmax)\n        plus the host W4A8 matvec of every matrix and "
             "layer_fixed.layer_decode_fx\n        per layer, all required "
             "bit-exact")
    else:
        v = ("readback — every x8 / EOUT / o32 / gated-o32 / AMAXI still "
             "compared\n        bit-exactly against the scratchpad model; "
             "--verify adds the host W4A8\n        matvec and the "
             "layer_decode_fx golden residual")
    log(f"verify  {v}")
    log(POSTURE)
    log("-" * 72)


# ======================================================================
# CLI / REPL
# ======================================================================
def fmt_ids(ids):
    return "[" + ", ".join(str(int(i)) for i in ids) + "]"


def run_turn(mdl, tk, text, ntok, log=print, tmpl=None):
    """One user turn: tokenize -> prefill -> stream generated tokens.

    With `tmpl` (a chat_seq.ChatTemplate, from --chat) the prompt is
    wrapped exactly as sw/chat_seq.py wraps it — the same T3
    incremental-with-carry form, with mdl.next_in playing the carry.
    """
    if tmpl is None:
        ids = tk.encode(text)
        wrap = 0
    else:
        first = (mdl.tmpl_turns == 0)
        ids = tmpl.turn_ids(text, system=(mdl.args.system if first else None),
                            first=first, carry=mdl.next_in)
        wrap = len(ids) - len(tmpl.body(text)) - (
            len(tmpl.body(mdl.args.system)) if (first and mdl.args.system)
            else 0)
    if not ids:
        log("  (empty prompt)")
        return []
    feed = ([mdl.next_in] if mdl.next_in is not None else []) + ids
    log(f"  tokens  {fmt_ids(ids)}  ({len(ids)} ids"
        + (f", {wrap} of them the chat wrapper" if tmpl is not None else "")
        + (f", continuing from {mdl.next_in}" if mdl.next_in is not None else "")
        + f"; context {mdl.pos} -> {mdl.pos + len(feed) + ntok - 1} of "
          f"{mdl.args.max_ctx})")

    interrupted = {"v": False}

    def on_sigint(sig, frm):
        interrupted["v"] = True
        sys.stdout.write("\n  [Ctrl-C: finishing the current token…]\n")
        sys.stdout.flush()

    prev = signal.signal(signal.SIGINT, on_sigint)
    got = []
    t_start = time.monotonic()
    try:
        pre = [0]

        def on_prefill(tok, dt):
            pre[0] += 1
            sys.stdout.write(f"\r  prefill {pre[0]}/{len(feed) - 1} "
                             f"({dt:.1f}s/tok)   ")
            sys.stdout.flush()

        def show(g):
            return tk.decode(tmpl.visible(g) if tmpl is not None else g)

        def on_token(tid, dt):
            prev_txt = show(got)
            got.append(tid)
            piece = show(got)[len(prev_txt):]
            sys.stdout.write(f"\r{' ' * 46}\r  [{len(got):2d}] {dt:6.1f}s  "
                             f"{tid:6d}  {piece!r}\n")
            sys.stdout.flush()

        mdl.generate(feed, ntok, on_prefill=on_prefill, on_token=on_token,
                     stop=lambda: interrupted["v"])
    finally:
        signal.signal(signal.SIGINT, prev)
    dt = time.monotonic() - t_start
    if tmpl is not None:
        mdl.tmpl_turns += 1
    log(f"  --> {show(got)!r}")
    log(f"      ids {fmt_ids(got)}   {len(got)} tok in {dt:.1f}s "
        f"({dt / max(len(got), 1):.1f} s/tok incl. prefill)"
        + (f"  [stop: {mdl.stopped}]" if getattr(mdl, "stopped", None)
           else ""))
    return got


def stats(mdl, log=print):
    tt = mdl.tok_times
    log(f"  context      {mdl.pos} forward steps of {mdl.args.max_ctx} "
        f"(KV bank depth {KV_DEPTH})")
    log(f"  generated    {len(tt)} tokens this session")
    if tt:
        log(f"  per token    mean {sum(tt) / len(tt):.1f}s  "
            f"min {min(tt):.1f}s  max {max(tt):.1f}s  "
            f"({len(tt) / sum(tt):.3f} tok/s)")
    log("  --- process totals (all turns since start, incl. every preamble) ---")
    log(f"  hw commands  {mdl.M.ncmd}   matvecs {mdl.M.nmv}   "
        f"host words written {mdl.M.nw}")
    log(f"  checks       {mdl.M.nchk} chip words compared bit-exactly "
        f"(a mismatch aborts, so reaching here means 0)")
    log(f"  MMIO         {mdl.dev.n_mmio_rd} reads / {mdl.dev.n_mmio_wr} writes")


def repl(mdl, tk, tmpl=None):
    print("Commands: /reset  /stats  /quit   (Ctrl-C stops generation)")
    while True:
        try:
            line = input("\nprompt> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        line = line.strip()
        if not line:
            continue
        if line in ("/quit", "/q", "/exit"):
            return
        if line == "/reset":
            mdl.reset()
            print("  conversation reset (DN state zeroed, conv state zeroed, "
                  "T=0, context 0)")
            continue
        if line == "/stats":
            stats(mdl)
            continue
        if line.startswith("/"):
            print(f"  unknown command {line!r}")
            continue
        try:
            run_turn(mdl, tk, line, mdl.args.ntok, tmpl=tmpl)
        except ValueError as e:
            print(f"  {e}")
        except Mismatch as e:
            print(f"  *** BIT-EXACTNESS FAILURE: {e}")
            return


def main():
    ap = argparse.ArgumentParser(
        description="Interactive live LLM inference on the fable5_llm FPGA.")
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--chan", type=int, default=0)
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help="artifact prefix (<p>.weights.json, <p>_w*.bin, "
                         "<p>.emb.bin)")
    ap.add_argument("--res-scale", type=int, default=8)
    ap.add_argument("--w4-group", type=int, default=G, choices=(128, 64))
    ap.add_argument("--skip-upload", action="store_true",
                    help="weights already resident in DDR")
    ap.add_argument("--check-images", action="store_true",
                    help="byte-compare every DDR image against the live "
                         "quantization before uploading it")
    ap.add_argument("--verify", action="store_true",
                    help="full lockstep: also recompute every W4A8 matvec and "
                         "every layer's residual (layer_fixed.layer_decode_fx) "
                         "on the host and require bit-exact agreement")
    ap.add_argument("--prompt", action="append", default=[],
                    help="non-interactive turn (repeatable)")
    ap.add_argument("--ntok", default="8",
                    help="tokens to generate; a comma-separated list pairs "
                         "positionally with --prompt (last value repeats)")
    ap.add_argument("--continue-context", action="store_true",
                    help="keep the KV/DN state across --prompt turns "
                         "(default: /reset between them)")
    ap.add_argument("--max-ctx", type=int, default=500)
    ap.add_argument("--chat", action="store_true",
                    help="wrap every prompt in the chat template "
                         "(docs/INSTRUCT_SPEC.md), using sw/chat_seq.py's "
                         "builder.  OFF by default here: infer.py is the "
                         "legacy per-MMIO reference path and its committed "
                         "gates feed raw prompts.  sw/chat_seq.py is the "
                         "chat tool and templates by DEFAULT.")
    ap.add_argument("--system", default=None,
                    help="--chat: system message, fed once at session start "
                         "(docs/INSTRUCT_SPEC.md T5)")
    ap.add_argument("--expect-version", default=hex(EXPECT_VERSION))
    ap.add_argument("--tok-test", action="store_true",
                    help="run the tokenizer self-test and exit (no board)")
    args = ap.parse_args()
    if args.max_ctx > KV_DEPTH:
        ap.error(f"--max-ctx must be <= the KV bank depth {KV_DEPTH}")
    try:
        args.ntoks = [int(x) for x in str(args.ntok).split(",") if x.strip()]
        assert args.ntoks and all(n > 0 for n in args.ntoks)
    except (ValueError, AssertionError):
        ap.error("--ntok must be a positive int or a comma-separated list")
    args.ntok = args.ntoks[0]

    tp = _tokenizer_path()
    if tp is None:
        raise SystemExit("tokenizer.json not found in the HF cache")
    t0 = time.monotonic()
    tk = BpeTok(tp)
    n = tk.self_test()
    print(f"tokenizer: {tp}\n  byte-level BPE, {len(tk.ranks)} merges; "
          f"self-test reproduces all {n} gen_model_script PROMPTS exactly "
          f"({time.monotonic() - t0:.1f}s)")
    if args.tok_test:
        for k in sorted(PROMPTS):
            txt = PROMPTS[k][0]
            print(f"  {txt!r} -> {fmt_ids(tk.encode(txt))} -> "
                  f"{tk.decode(tk.encode(txt))!r}")
        return

    tmpl = None
    if args.chat:
        tmpl = chat_template(tk)
        print(f"chat template: ON (docs/INSTRUCT_SPEC.md) — id-spliced "
              f"wrapper, {tmpl.per_message}*messages+{tmpl.gen_overhead} ids, "
              f"closed-empty think block"
              + (f", system {args.system!r}" if args.system else ""))
    elif args.system:
        ap.error("--system needs --chat")

    dev = Dev(args.dev, args.chan, int(args.expect_version, 0))
    print("board identity gate PASSED — DMA enabled")
    mdl = FpgaModel(dev, args)
    banner(dev, mdl)
    print(f"stop ids: {sorted(mdl.stop_ids)} (docs/INSTRUCT_SPEC.md T6 — "
          f"generate() stops here instead of running past <|im_end|>)")

    rc = 0
    try:
        if args.prompt:
            for i, p in enumerate(args.prompt):
                if i and not args.continue_context:
                    mdl.reset()
                n = args.ntoks[min(i, len(args.ntoks) - 1)]
                print(f"\nprompt> {p}")
                try:
                    run_turn(mdl, tk, p, n, tmpl=tmpl)
                except ValueError as e:
                    print(f"  {e}")
                    rc = 1
            print()
            stats(mdl)
        else:
            repl(mdl, tk, tmpl=tmpl)
    except Mismatch as e:
        print(f"\n*** BIT-EXACTNESS FAILURE: {e}")
        rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
