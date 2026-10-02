#!/usr/bin/env python3
"""seq_model.py — pure-python executor of a binary SEQ stream.

This is the GOLDEN for the RTL sequencer: it fetches 16-byte records
(ref/seq_format.py), issues them against the same scratchpad model the
script generators use (gen_layer_script.Mach), and simulates the XRF, the
two movers and the matvec engine — the engine by reading the REAL packed
DDR weight images and running ref/w4a8_ref.matvec_y32 (or, when the MVGO's
SHAPE word sets bit 29, matvec_y32_w8) on them, so a .seq replay exercises
the whole wire format end to end at either weight width.

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
from w4a8_ref import (matvec_y32, matvec_y32_w8, unpack_ddr_rows,   # noqa
                      unpack_ddr_rows8, rshift_round as rshr)
# the 16-bit scratch address packing (G3.1 / SEQ_ISA v2.0) lives beside the
# emitter that produces it; this module only ever DECODES with it — except
# for DNST's ARG0, which it opens by hand (spec 7.6 B) and which is now just
# a 5-bit head
import gen_layer_script as GLS                              # noqa: E402

# SEQ_ISA v2.1 B15.1's kind codes, named here rather than imported from the
# emitter: `StateRegion` is the SECOND implementation of the byte layouts
# and shares no code with the first (spec 6.5).
HW_K_DN, HW_K_KV, HW_K_CV = 0, 1, 2

I64 = np.int64


def _fresh_mach():
    """A Mach carrying ONLY the model (its script sink is /dev/null and its
    SEQ emitter is forced off)."""
    saved = os.environ.pop("SEQ_EMIT", None)
    try:
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
        # S3: a KV CACHE SLOT holds ONE kvhead's rows (spec A1.3), so these
        # are two flat lists, not [slot][kvhead].  Which kvhead a slot holds
        # is its TAG, and the tag is part of the state a replay reproduces.
        "kc": [[(a.copy(), e) for (a, e) in s] for s in M.kc],
        "vc": [[(a.copy(), e) for (a, e) in s] for s in M.vc],
        "eout": int(M.eout),
        "am": (int(M.am_val), int(M.am_idx), int(M.am_g), bool(M.am_first)),
        "dn_slot": int(M.dn_slot), "kv_slot": int(M.kv_slot),
        "cv_slot": int(M.cv_slot), "kv_layer": int(M.kv_layer),
        "tag": list(M.tag),
        "warm": {k: list(v) for k, v in M.warm.items()},
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
    for k in ("T", "eout", "am", "dn_slot", "kv_slot", "cv_slot",
              "kv_layer", "tag", "warm"):
        if a[k] != b[k]:
            out.append(f"{k}: {a[k]!r} vs {b[k]!r}")
    for k in ("kc", "vc"):
        for s in range(len(a[k])):
            A, B = a[k][s], b[k][s]
            if len(A) != len(B):
                out.append(f"{k}[{s}]: depth {len(A)} vs {len(B)}")
                continue
            for t, ((x, ex), (y, ey)) in enumerate(zip(A, B)):
                if ex != ey or not np.array_equal(x, y):
                    out.append(f"{k}[{s}][{t}] differs")
                    break
    return out


# ======================================================================
# DDR state region (the state DMA's view)
# ======================================================================
class StateRegion(object):
    """The DDR state region SEQ_ISA v2.1's SLD/SST move blocks in and out of.

    THE SECOND OF TWO INDEPENDENT IMPLEMENTATIONS of B15.1's byte layouts.
    The first is `ref/gen_layer_script.StateImage`, which the EMITTER uses;
    this one is the reference EXECUTOR's, and `gate()` compares the image
    the emitter ended with against the region this one ended with.  The two
    were written twice ON PURPOSE (spec 6.5): a shared serialiser would make
    that comparison vacuous, so nothing here imports anything from
    `StateImage` and the address arithmetic below is derived from
    `docs/SEQ_ISA.md` B15.1 and `sw/hwmap.STATE_*`, not from the emitter.

    The representation is deliberately different too: one FLAT byte array
    covering [dn, end), addressed by absolute DDR address, where the
    emitter keeps a dict of per-block arrays.

    `.blocks` renders it back as {(kind, layer, head): uint8 view} so the
    two can be compared block by block, and so `tb/scripts/gen_seq_chip_
    vectors.py` can emit one `SMEM` golden record per block the run touched.
    """

    KINDS = ("dn", "kv", "cv")

    def __init__(self, plan, data=None):
        self.plan = {k: int(plan[k]) for k in ("dn", "kv", "cv", "end")}
        n = self.plan["end"] - self.plan["dn"]
        self.mem = (np.zeros(n, dtype=np.uint8) if data is None
                    else np.frombuffer(bytearray(data), dtype=np.uint8))
        assert len(self.mem) == n, \
            f"state image is {len(self.mem)} B, the plan spans {n} B"
        self.touched = set()          # (kind, layer, head) an SST wrote

    @classmethod
    def load(cls, prefix):
        """`<prefix>.state.bin` + the `state` plan in `<prefix>.weights.json`.
        Returns None when the artifact carries neither (a pre-S3 or frozen
        stream, which emits no SLD/SST for a region to serve)."""
        _wids, meta = HW.load_weights_manifest(prefix)
        plan = meta.get("state")
        if plan is None:
            return None
        with open(prefix + ".state.bin", "rb") as f:
            return cls(plan, f.read())

    # ---- B15.1's address arithmetic, written HERE, from the ISA doc ----
    # B15.1's ranges, mirroring rtl/layer_chan.sv's `sdma_range_bad` and
    # ref/seq_format.validate_stream's clause.  The bounds are HERE and not
    # only in the envelope because a block index out of range lands on the
    # NEXT region's first block, which is a legal address and a wrong
    # answer (S3 fix round 1, found by this class's own selftest).
    N_DN_BLOCKS = HW.STATE_DN_BLOCKS // 32       # 24 layers
    N_KV_LAYERS = HW.STATE_KV_BLOCKS // (4 * 2)  # 8 attention layers

    def _blk(self, kind, layer, head):
        if kind == HW_K_DN:
            assert head == 0, "a DN transfer moves the whole layer (A1.1)"
            assert 0 <= layer < self.N_DN_BLOCKS, (
                f"DN layer {layer} outside 0..{self.N_DN_BLOCKS - 1} (B15.1)")
            a = self.plan["dn"] + layer * HW.STATE_DN_LAYER
            n = HW.STATE_DN_LAYER
        elif kind == HW_K_KV:
            assert 0 <= layer < self.N_KV_LAYERS, (
                f"KV layer {layer} outside 0..{self.N_KV_LAYERS - 1} (B15.1)")
            assert 0 <= head <= 7, f"KV head {head} outside 0..7 (B15.1)"
            i = (layer * 4 + (head >> 1)) * 2 + (head & 1)
            a = self.plan["kv"] + i * HW.STATE_KV_STRIDE
            n = HW.STATE_KV_STRIDE
        elif kind == HW_K_CV:
            assert head == 0, "a CV transfer moves the whole layer block"
            assert 0 <= layer < self.N_DN_BLOCKS, (
                f"CV layer {layer} outside 0..{self.N_DN_BLOCKS - 1} (B15.1)")
            a = self.plan["cv"] + layer * HW.STATE_CV_STRIDE
            n = HW.STATE_CV_STRIDE
        else:
            raise SF.SeqValidationError(f"SDMA kind {kind} is reserved")
        o = a - self.plan["dn"]
        assert 0 <= o and o + n <= len(self.mem), \
            f"block ({kind},{layer},{head}) at {a:#x} is outside the region"
        return o, n

    @property
    def blocks(self):
        out = {}
        for kind, layer, head in sorted(self.touched):
            o, n = self._blk(kind, layer, head)
            out[(kind, layer, head)] = self.mem[o:o + n]
        return out

    def addr_of(self, kind, layer, head):
        o, n = self._blk(kind, layer, head)
        return self.plan["dn"] + o, n

    # ---- the transfers.  `M` is the Mach whose slots they fill/drain ----
    def sld(self, M, kind, slot, layer, head):
        o, _n = self._blk(kind, layer, head)
        if kind == HW_K_DN:
            v = self.mem[o:o + HW.STATE_DN_LAYER].view("<i2")
            M.S[slot] = v.reshape(GLS.LR.LNH, GLS.LR.LDK,
                                  GLS.LR.LDV).astype(np.int64)
        elif kind == HW_K_KV:
            t = int(M.T[layer][head >> 1])
            hd = GLS.LR.HD
            rows = self.mem[o:o + t * hd].view(np.int8).reshape(t, hd)
            ex = self.mem[o + HW.STATE_KV_EXP_OFF:
                          o + HW.STATE_KV_EXP_OFF + t].view(np.int8)
            new = [(rows[i].astype(np.int64), int(ex[i])) for i in range(t)]
            if head & 1:
                M.vc[slot] = new
            else:
                M.kc[slot] = new
        else:
            r = self.mem[o:o + HW.STATE_CV_STRIDE].reshape(GLS.LR.CONV_DIM, 16)
            M.cw[slot] = (r[:, 0:8].copy().view("<i2")
                          .reshape(GLS.LR.CONV_DIM, 4).astype(np.int64))
            M.cs[slot] = (r[:, 8:14].copy().view("<i2")
                          .reshape(GLS.LR.CONV_DIM, 3).astype(np.int64))
        M.warm[kind][slot] = True
        M.slot_id[kind][slot] = ((layer, head >> 1) if kind == HW_K_KV
                                 else (layer, head))
        if kind == HW_K_KV:
            M.tag[slot] = (layer, head >> 1)

    def sst(self, M, kind, slot, layer, head):
        o, _n = self._blk(kind, layer, head)
        if kind == HW_K_DN:
            v = self.mem[o:o + HW.STATE_DN_LAYER].view("<i2")
            v[:] = np.asarray(M.S[slot], dtype="<i2").reshape(-1)
        elif kind == HW_K_KV:
            # B15.1: the length is TCNT as read WHEN THE TRANSFER STARTS,
            # which for this model is the moment the SST record executes.
            t = int(M.T[layer][head >> 1])
            hd = GLS.LR.HD
            src = M.vc[slot] if (head & 1) else M.kc[slot]
            assert len(src) == t, (
                f"SST KV (layer {layer}, kvhead {head >> 1}, kv {head & 1}): "
                f"the slot holds {len(src)} rows, TCNT says {t}")
            rows = self.mem[o:o + t * hd].view(np.int8).reshape(t, hd)
            ex = self.mem[o + HW.STATE_KV_EXP_OFF:
                          o + HW.STATE_KV_EXP_OFF + t].view(np.int8)
            for i in range(t):
                rows[i] = np.asarray(src[i][0], dtype=np.int8)
                ex[i] = np.int8(src[i][1])
        else:
            r = self.mem[o:o + HW.STATE_CV_STRIDE].reshape(GLS.LR.CONV_DIM, 16)
            r[:, 0:8] = (np.asarray(M.cw[slot], dtype="<i2")
                         .view(np.uint8).reshape(GLS.LR.CONV_DIM, 8))
            r[:, 8:14] = (np.asarray(M.cs[slot], dtype="<i2")
                          .view(np.uint8).reshape(GLS.LR.CONV_DIM, 6))
            r[:, 14:16] = 0
        M.warm[kind][slot] = False
        self.touched.add((kind, layer, head))


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

    WEIGHT WIDTH (V5).  A plan entry carries `"w8": True` for an 8-bit
    image, exactly the way it carries `"g"` — ABSENT MEANS W4, so every
    pre-V5 plan and manifest keeps its meaning byte for byte.  W8 rows are
    read with `unpack_ddr_rows8` (K//64 weight beats, the SAME scale
    cadence) and multiplied with `matvec_y32_w8`.
    """

    def __init__(self, plan, meta=None):
        # plan: {wid: {base,nrows,k,ng,sh,g,stride,nbeats[,w8]}}
        self.plan = {int(k): v for k, v in plan.items()}
        self.meta = meta or {}
        # R-c PER-CHANNEL REPACK: "base" is a LIST of nch channel-local
        # addresses instead of the one span every channel shares, and a
        # channel holds only the rows it owns — so a WBASE means DIFFERENT
        # rows on different channels and the lookup needs the MVGO's engine
        # channel.  Detected from the plan's own shape, cross-checked against
        # meta so a plan and a stream cannot disagree silently.
        self.repack = any(isinstance(p["base"], (list, tuple))
                          for p in self.plan.values())
        self.nch = int(self.meta.get("nch", 1))
        self._rows = {}          # wid -> chan -> [(row_off, r0_global, n)]
        if self.repack:
            assert self.meta.get("weight_repack"), (
                "the weight plan carries per-channel bases but the stream "
                "meta does not say weight_repack — pass meta= to DDRWeights")
            wl = self.meta.get("weight_layout") or {}
            depth = int(wl.get("chunk_rows", SF.CHUNK_ROWS))
            byw = wl.get("by_wid") or {}
            for wid, p in self.plan.items():
                lay = byw.get(str(wid), wl.get("default", SF.LAYOUT_CONTIG))
                per = {}
                for (i, r0, n, off) in SF.weight_pieces_at(
                        int(p["nrows"]), self.nch, lay, depth, repack=True):
                    per.setdefault(i, []).append((off, r0, n))
                self._rows[wid] = per
            self.byaddr = {c: sorted((p["base"][c], int(w))
                                     for w, p in self.plan.items())
                           for c in range(self.nch)}
        else:
            self.byaddr = {None: sorted((p["base"], int(w))
                                        for w, p in self.plan.items())}
        self._img = {}
        self._qw = {}

    @classmethod
    def from_files(cls, prefix, plan, meta=None):
        self = cls(plan, meta)
        d = os.path.dirname(os.path.abspath(prefix)) or "."
        man, _ = HW.load_weights_manifest(prefix)   # R-b: drops the meta key
        for wid, m in man.items():
            path = os.path.join(d, m["file"])
            self._img[int(wid)] = path
            p = self.plan.get(int(wid))
            if p is not None:
                # The row LAW is what the plan's SHAPE encodes (W4 nibbles vs
                # W8 bytes); the file is what gets unpacked with it.  A W8
                # image paired with a W4 plan differs only in size, so check
                # the size — otherwise a standalone golden run reads half an
                # image as a whole one and reports a clean, wrong answer.
                want = int(p["nrows"]) * int(p["stride"])
                got = os.path.getsize(path)
                assert got == want, (
                    f"wid {wid}: {m['file']} is {got} B, the plan's "
                    f"{p['nrows']} x {p['stride']} B image is {want} B "
                    f"(w8={int(bool(p.get('w8', False)))})")
        return self

    @classmethod
    def from_wids(cls, wids, plan, meta=None):
        self = cls(plan, meta)
        for (wid, qw) in wids.values():
            self._qw[int(wid)] = qw
        return self

    def _lookup(self, wbase, chan=None):
        """(wid, GLOBAL row, plan entry, rows left in this piece).

        `chan` is the MVGO's engine channel; it is IGNORED by the
        nch-independent pack (every channel holds the same span at the same
        address) and REQUIRED by the repack.
        """
        assert not (self.repack and chan is None), \
            "a repacked weight plan needs the MVGO's channel to resolve WBASE"
        key = int(chan) if self.repack else None
        table = self.byaddr[key]
        lo, hi = 0, len(table) - 1
        wid = None
        while lo <= hi:
            mid = (lo + hi) // 2
            if table[mid][0] <= wbase:
                wid = table[mid][1]
                lo = mid + 1
            else:
                hi = mid - 1
        assert wid is not None, f"WBASE {wbase:#x} below the weight region"
        p = self.plan[wid]
        base = p["base"][key] if self.repack else p["base"]
        off = wbase - base
        if not self.repack:
            assert 0 <= off < p["nrows"] * p["stride"], \
                f"WBASE {wbase:#x} does not land inside wid {wid}"
            assert off % p["stride"] == 0, \
                f"WBASE {wbase:#x} is not row-aligned in wid {wid}"
            r0 = off // p["stride"]
            return wid, r0, p, p["nrows"] - r0
        assert off >= 0 and off % p["stride"] == 0, \
            f"WBASE {wbase:#x} is not row-aligned in wid {wid} on chan {key}"
        loc = off // p["stride"]
        for (lo_off, r0, n) in self._rows[wid].get(key, []):
            if lo_off <= loc < lo_off + n:
                # the packed row maps back to the GLOBAL row the image file
                # (and the live matrix) is indexed by
                return wid, r0 + (loc - lo_off), p, n - (loc - lo_off)
        raise AssertionError(
            f"WBASE {wbase:#x} (packed row {loc} of wid {wid}) is not inside "
            f"any piece channel {key} holds")

    def matvec(self, wbase, nrows, sh, ng, g, x8, w8=False, chan=None):
        wid, r0, p, avail = self._lookup(wbase, chan)
        assert nrows <= avail, "MVGO row chunk overruns the image"
        pw8 = bool(p.get("w8", False))
        assert sh == p["sh"] and g == p["g"] and ng == p["ng"] and w8 == pw8, (
            f"wid {wid}: SHAPE (sh={sh} ng={ng} g={g} w8={int(w8)}) != "
            f"manifest (sh={p['sh']} ng={p['ng']} g={p['g']} w8={int(pw8)})")
        K = p["k"]
        assert len(x8) == K, f"XWIN holds {len(x8)} bytes, K={K}"
        if wid in self._qw:
            qw = self._qw[wid]
            w = qw["w8" if w8 else "w4"][r0:r0 + nrows]
            m = qw["m"][r0:r0 + nrows]
        else:
            stride = p["stride"]
            mm = np.memmap(self._img[wid], dtype=np.uint8, mode="r")
            img = mm[r0 * stride:(r0 + nrows) * stride]
            unpack = unpack_ddr_rows8 if w8 else unpack_ddr_rows
            w, m = unpack(img.tobytes(), nrows, K, g)
        mv = matvec_y32_w8 if w8 else matvec_y32
        return np.asarray(mv(w, m, sh, np.asarray(x8, dtype=np.int8), g=g),
                          dtype=I64)


class RunningChannelError(AssertionError):
    """SV1 fix round 1: a MOVX / MVGO / MOVY on a channel whose no-wait
    stream is still running.  Raised EXPLICITLY (not `assert`), so the
    refusal survives `python -O`; an AssertionError subclass so every
    caller that caught the old assert still catches it."""


class UnwrittenReadError(AssertionError):
    """SR11a fix round 1 (M1): a MVGO or MOVY that reads x_mem / RES the
    model cannot vouch for — no intact MOVX vector starts at the MVGO's x
    word, or the MOVY's rows are not inside one live MVGO result.  Raised
    EXPLICITLY, like RunningChannelError, so it survives `python -O`; an
    AssertionError subclass because the pre-R2 model refused the same
    streams with a bare assert."""


def _overlap(a0, a1, b0, b1):
    """Half-open [a0, a1) and [b0, b1) share an element.  An EMPTY access
    range counts as overlapping (conservative: today's model refused ANY
    MOVX/MOVY on a running channel, zero-length ones included)."""
    return a1 <= a0 or (a0 < b1 and b0 < a1)


class XWinMem(object):
    """SR11a (SEQ_ISA v2.3 B17.2): each channel's x_mem kept as the RTL
    keeps it — 3072 words = 12288 int8 per channel — written by MOVX at its
    start word (the ragged tail zero-padded to the word).

    Which bytes a MVGO may read is STRICTER than the RTL (which reads
    whatever x_mem holds): a MVGO at start byte s reads exactly the vector
    the last MOVX that STARTED at s wrote, and only while no later MOVX has
    overwritten any of it.  With every start word zero that is today's rule
    exactly (one vector per channel, the last MOVX's, whose length the
    matvec checks against K).

    Keeps today's dict face for the callers that use it:
    `xwin[c] = v` is a MOVX of v at word 0; `xwin.get(c)` / `xwin[c]` /
    `items()` read the vector at word 0."""
    NBYTES = SF.XWIN_WORDS * 4

    def __init__(self):
        self.mem = {}          # chan -> np.int8[12288]
        self.vec = {}          # chan -> {start byte: nbytes}

    def write(self, chan, word0, v):
        v = np.asarray(v, dtype=np.int8)
        nb = len(v)
        lo = int(word0) * 4
        hi = lo + SF.movx_words(nb) * 4
        assert hi <= self.NBYTES, (
            f"MOVX writes XWIN bytes [{lo}, {hi}) past the {self.NBYTES}-byte "
            "x_mem (B17.2)")
        m = self.mem.setdefault(chan, np.zeros(self.NBYTES, dtype=np.int8))
        m[lo:lo + nb] = v
        m[lo + nb:hi] = 0
        ents = self.vec.setdefault(chan, {})
        for s in [s for s, n in ents.items()
                  if s < hi and lo < s + SF.movx_words(n) * 4]:
            del ents[s]
        ents[lo] = nb

    def read(self, chan, byte0):
        n = self.vec.get(chan, {}).get(int(byte0))
        if n is None:
            return None
        return self.mem[chan][byte0:byte0 + n].copy()

    # -- today's dict face ---------------------------------------------
    def __setitem__(self, chan, v):
        self.write(chan, 0, v)

    def get(self, chan, default=None):
        v = self.read(chan, 0)
        return default if v is None else v

    def __getitem__(self, chan):
        v = self.read(chan, 0)
        if v is None:
            raise KeyError(chan)
        return v

    def __contains__(self, chan):
        return self.read(chan, 0) is not None

    def items(self):
        return [(c, self.read(c, 0)) for c in sorted(self.vec)
                if 0 in self.vec[c]]


class ResMem(object):
    """SR11a (SEQ_ISA v2.3 B17.2): each channel's RES BRAM, 4096 rows, kept
    as the RTL keeps it.  A MVGO writes its rows at 2048*RBANK; a MOVY reads
    from its start row and must lie inside ONE live MVGO segment (rows a
    later MVGO overwrote are dead) — with every start row zero that is
    today's "MOVY reads N RES rows, only M valid" exactly.

    Today's dict face: `res[c]` / `res.get(c)` / `items()` give the rows of
    the channel's most recent MVGO."""
    def __init__(self):
        self.mem = {}          # chan -> np.int64[4096]
        self.seg = {}          # chan -> [(row0, n)], oldest first

    def write(self, chan, row0, y):
        y = np.asarray(y, dtype=I64)
        n = len(y)
        assert row0 + n <= SF.RES_ROWS, (
            f"MVGO writes RES rows [{row0}, {row0 + n}) past the "
            f"{SF.RES_ROWS}-row RES (B17.2)")
        m = self.mem.setdefault(chan, np.zeros(SF.RES_ROWS, dtype=I64))
        m[row0:row0 + n] = y
        # a zero-row MVGO still kills the segment at its start row (today:
        # res[c] = an empty y)
        hi = row0 + max(n, 1)
        segs = [(s, k) for (s, k) in self.seg.get(chan, [])
                if not (s < hi and row0 < s + max(k, 1))]
        segs.append((row0, n))
        self.seg[chan] = segs

    def written(self, chan):
        return bool(self.seg.get(chan))

    def read(self, chan, row0, n):
        for (s, k) in reversed(self.seg.get(chan, [])):
            if s <= row0 and row0 + n <= s + k:
                return self.mem[chan][row0:row0 + n].copy()
        return None

    def latest(self, chan):
        segs = self.seg.get(chan)
        if not segs:
            return None
        s, k = segs[-1]
        return self.mem[chan][s:s + k].copy()

    def get(self, chan, default=None):
        v = self.latest(chan)
        return default if v is None else v

    def __getitem__(self, chan):
        v = self.latest(chan)
        if v is None:
            raise KeyError(chan)
        return v

    def __contains__(self, chan):
        return self.written(chan)

    def items(self):
        return [(c, self.latest(c)) for c in sorted(self.seg)
                if self.seg[c]]


# ======================================================================
# the executor
# ======================================================================
class SeqExec(object):
    """Fetch/decode/issue a SEQ record stream against the Mach model."""

    def __init__(self, recs, blob, weights, emb=None, mach=None,
                 max_records=None, checkpoints=None, isa=HW.SHAPE_ISA,
                 region=None, caps=frozenset()):
        if isinstance(recs, (bytes, bytearray, memoryview)):
            recs = SF.unpack_stream(recs)
        self.recs = recs
        # {record index: (scratch addr, n)} — sampled BEFORE that record is
        # issued, in firing order, and compared against the .txt R records.
        self.cp_at = {int(i): (int(a), int(n))
                      for (i, a, n) in (checkpoints or [])}
        self.cp_log = []
        self.blob = blob
        # WHICH R_SHAPE LAYOUT the MVGO records in this stream carry
        # (sw/hwmap.py's R_SHAPE block).  Default is THIS TREE's -- a
        # post-G3 stream -- and `isa=1` decodes a build_034/build_035 SHAPE
        # word.  It is a decode-time choice, not a mode: nothing else in the
        # model looks at it.
        #
        # THIS IS NOT A v1.7 STREAM PATH (T7's ruling stands).  `isa=1`
        # selects a SHAPE FIELD LAYOUT, not an ISA: the ARG decode above is
        # SEQ_ISA v2.0 ONLY, so a real pre-G3 `.seq` file still cannot be
        # replayed here whatever `isa` says.  The branch exists for the two
        # W8 goldens IN THIS FILE (`selftest_w8_mvgo`, `selftest_repack`),
        # which build their own v2.0 record streams in memory around an
        # isa=1 SHAPE word so spec 3.3's host-side W8 law stays under test.
        # `ref/seq_format.disasm` needs no such selector because it renders
        # what THIS TREE emits, and this tree has exactly one emitter.
        self.shape_isa = int(isa)
        self.W = weights
        self.emb = emb
        # SEQ_ISA v2.1: the DDR state region ops 13/14 move blocks in and
        # out of.  None means "this artifact declares no state plan", and
        # an SLD/SST then refuses rather than inventing a region.
        self.region = region
        self.M = mach if mach is not None else _fresh_mach()
        self.xrf = [0] * XRF_N
        self.tcnt_seq = 0
        self.args = [0, 0, 0]
        self.sptr = 0
        # SEQ_ISA v2.0: the DNSB layer CSR shadow (None = never written)
        self.dnsb = None
        self.xptr = {}   # B17.3 XPTR (R3-3); SR11a (B17.2): x_mem, RES
        self.xwin = XWinMem()
        self.res = ResMem()
        self.out_fifo = []
        self.issued = 0
        self.max_records = max_records
        self.stats = {k: 0 for k in ("CSRWR", "CMD", "MOVX", "MOVY", "MVGO",
                                     "EMB", "AMAXL", "JMP", "FENCE", "LDC",
                                     "XOP", "PROBE", "MVGO_NOWAIT")}
        # channels a no-wait MVGO left running; only a FENCE drains them, and
        # a MOVX, MVGO or MOVY on a running channel is REFUSED (SV1: the RTL
        # neither blocks nor survives either).  The python model is
        # synchronous, so this only enforces the ORDERING RULE the RTL
        # relies on.
        # SR11a (SEQ_ISA v2.3 B17.2): RUNNING RANGES — chan -> (x word lo,
        # x word hi, RES row lo, RES row hi) of the pending stream (half-
        # open).  A MVGO on a channel with ANY pending stream is refused
        # (one engine); a MOVX only if its XWIN word range overlaps the
        # pending x range; a MOVY only if its row range overlaps the pending
        # RES range.  With every bank bit and start word zero the ranges
        # always overlap, i.e. today's per-channel rule.  The keys are the
        # running channels (`c in running`, `sorted(running)` as before).
        self.running = {}
        # SR4 (SEQ_ISA v2.3 B17.0/B17.1): the capability set every record is
        # validated AT.  The model is a SOFTWARE gate, not a device: its
        # caller names the caps the stream needs (sr4_gate.sh passes {"R1"}
        # for an r1 stream); the default (empty) is today's rules, so a
        # masked FENCE is refused unless "R1" is named.
        self.caps = HW.seq_caps_check(caps)
        self.eps_scale_log = []       # (m_q15_epsnorm,) for the delta report

    # ---------------------------------------------------------- helpers
    def _xrf_set(self, i, v):
        v = int(v)
        lim_s, lim_u = 1 << (SF.XRF_BITS - 1), 1 << SF.XRF_BITS
        assert -lim_s <= v < lim_u, \
            f"XRF[{i}] <= {v} does not fit {SF.XRF_BITS} bits (see A11)"
        self.xrf[i] = v

    def _tcnt_wr(self, first, val):
        """One TCNT CSR word carries TWO 10-bit kvhead append counters.

        `rtl/layer_chan.sv` 0x008 / 0x018 are WORD offsets; `LOFF_TCNT` /
        `LOFF_TCNT2` and every gate doc name the same two CSRs by BYTE, 0x20
        / 0x60.  Each writes two kvheads, `{[25:16], [9:0]}`.  Modelling it
        as `T[slot] = [0, 0]` was right at NKVH = 2 and TRUNCATES the bank
        at 4 -- and a truncated bank is the silent divergence spec 4.6 wall 9
        is about: attention would read a cache longer than its counter says.
        """
        # S2/S3 (B15.2, A1.3): `tcnt_bank` is indexed by ATTENTION LAYER
        # and the counters are THIRTEEN bits (T <= 4096), so the CSR word is
        # {[28:16], [12:0]} and the row is LAYER.kv_layer's, not a bank's.
        T = self.M.T[self.M.kv_layer]
        for j, sh in ((first, 0), (first + 1, 16)):
            if j < len(T):
                T[j] = (int(val) >> sh) & 0x1FFF

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
                self._tcnt_wr(0, val)
            elif off == SF.LOFF_TCNT2:
                assert val == 0, "layer TCNT2 is write-0 (reset) only"
                self._tcnt_wr(2, val)
            elif off == LOFF_LAYER:
                # B15.2: {cv_slot[13:12], kv_layer[10:8], kv_slot[4:3],
                #         dn_slot[1:0]} -- CACHE slots, not banks
                M.dn_slot, M.kv_slot = val & 0x3, (val >> 3) & 0x3
                M.kv_layer, M.cv_slot = (val >> 8) & 0x7, (val >> 12) & 0x3
                M.layer_is_set = True
            elif off in (SF.LOFF_SB_DN, SF.LOFF_SB_KV, SF.LOFF_SB_CV):
                # B15.3, in 64 KiB units.  The model gets its region from
                # the artifact's manifest, so a base the PROGRAM writes is
                # CHECKED against it rather than ignored: a stream replayed
                # against a re-planned region is exactly what spec 7.2
                # forbids, and it would otherwise read the right bytes here
                # and the wrong ones on hardware.
                if self.region is not None:
                    want = {SF.LOFF_SB_DN: "dn", SF.LOFF_SB_KV: "kv",
                            SF.LOFF_SB_CV: "cv"}[off]
                    exp = self.region.plan[want] >> 16
                    if (val & 0x3FFFF) != exp:
                        raise SF.SeqValidationError(
                            f"SB_{want.upper()} = {val:#x} but the artifact's "
                            f"state plan says {exp:#x} (spec 7.2)")
            elif off in (SF.LOFF_SDMA, SF.LOFF_SDMA_CYC):
                pass          # the DMA status/cycle CSRs: host-side, no model
            elif off == LOFF_SPTR:
                self.sptr = val
            elif off == LOFF_SWIN:
                v = val & 0xFFFF
                M.mem[self.sptr] = v - 65536 if v >= 32768 else v
                self.sptr += 1
            elif off == SF.LOFF_DNSB:
                # SEQ_ISA v2.0: {a_dec_base[31:16], a_beta_base[15:0]}
                self.dnsb = val
                M.dnsb_bases = (val & 0xFFFF, (val >> 16) & 0xFFFF)
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
            src, dst = GLS.dec_a1_lo(a1), GLS.dec_a1_hi(a1)
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
            M.vnw_(GLS.dec_a1_lo(a1), a0)
        elif op == 3:
            M.ropet(GLS.dec_a1_lo(a1))
        elif op == 4:
            M.rope(GLS.dec_a1_lo(a1), GLS.dec_a1_hi(a1))
        elif op == 5:
            sub, first, nch = a0 & 0x3, (a0 >> 2) & 0x3FFF, (a0 >> 16) & 0x3FFF
            if sub == 0:
                M.convw(first, nch, GLS.dec_a1_lo(a1))
            elif sub == 2:
                M.convz(first, nch)
            else:
                raise SF.SeqValidationError(f"CONVW sub-op {sub}")
        elif op == 6:
            M.conv(a0 & 0x3FFF, (a0 >> 14) & 0x3FFF,
                   GLS.dec_a1_lo(a1), GLS.dec_a1_hi(a1))
        elif op == 7:
            M.gate(GLS.dec_a1_lo(a1), GLS.dec_a1_hi(a1),
                   GLS.dec_a1_lo(a2), GLS.dec_a1_hi(a2), a0 & 0xFFFF)
        elif op == 8:
            # SEQ_ISA v2.0: ARG0 is {spare[31:5], head[4:0]} and the two
            # scalar pointers come from the DNSB CSR as base + head.  This
            # is the ONE place in this file that opens a DNST ARG word; the
            # pair halves themselves go through the canonical helpers.
            head = a0 & 0x1F
            if self.dnsb is None:
                raise SF.SeqValidationError(
                    "DNST with no DNSB written: SEQ_ISA v2.0 reads "
                    "a_beta/a_dec from the DNSB layer CSR (offset 0x5C)")
            a_beta_base = self.dnsb & 0xFFFF
            a_dec_base = (self.dnsb >> 16) & 0xFFFF
            M.dnst(head, GLS.dec_a1_lo(a1), GLS.dec_a1_hi(a1),
                   GLS.dec_a1_lo(a2),
                   a_dec_base + head, a_beta_base + head,
                   GLS.dec_a1_hi(a2))
        elif op == 9:
            M.kvap(a0 & 0xF, GLS.dec_a1_lo(a1), GLS.dec_a1_hi(a1),
                   (a0 >> 4) & 0x1F)
        elif op == 10:
            M.attn(a0 & 0xF, GLS.dec_a1_lo(a1), GLS.dec_a1_hi(a1))
        elif op == 11:
            self._alu(a0, a1, a2)
        elif op == 12:
            M.dnz(a0 & 0x1F)
        elif op in (SF.OP_L_SLD, SF.OP_L_SST):
            # SEQ_ISA v2.1 B15.1.  The ENVELOPE is validate_stream's
            # (ref/seq_format.py); what is left here is the transfer, and
            # it runs through StateRegion -- the reference's own
            # implementation of the byte layouts.
            kind, slot, layer, head = SF.sdma_fields(a0)
            if a1 != 0 or a2 != 0:
                raise SF.SeqValidationError(
                    f"{'SLD' if op == SF.OP_L_SLD else 'SST'} arg1/arg2 must "
                    f"be 0 (B15.1 reserved)")
            if self.region is None:
                raise SF.SeqValidationError(
                    "SLD/SST with no state region: this artifact's manifest "
                    "carries no `state` plan (sw/hwmap.plan_state)")
            if op == SF.OP_L_SLD:
                self.region.sld(M, kind, slot, layer, head)
            else:
                self.region.sst(M, kind, slot, layer, head)
        else:
            raise SF.SeqValidationError(f"unknown layer_chan opcode {op}")

    def _alu(self, a0, a1, a2):
        M = self.M
        # ARG0[17:4] is the count and `rtl/vec_alu.sv` takes it as a
        # 14-bit `cfg_len` (G3.1; 13 at R-c, 12 before that).  This decode
        # used to mask WIDER than the hardware field — so a stream carrying
        # an over-wide count was modelled the way the generator MEANT it
        # while the RTL ran `count & 0xFFF` (the Qwen3.5-2B MLP DYNQ8 is
        # FFN = 6144, and 6144 & 0xFFF = 2048).  Both python sides agreed
        # with each other and only a full-chip simulation could see it.  The
        # bound MIRRORS THE FIELD EXACTLY: refuse a stream rather than model
        # a length the sequencer cannot ask for.  ARG0[18] is p0[16] and
        # ARG0[31:19] is spare, so the count is read with a MASK, not a
        # bare shift — a bare `a0 >> 4` would now see the relocated p0 bit.
        nfield = GLS.dec_alu_len(a0)
        if (a0 >> 4) > 0x7FFF:
            raise SF.SeqValidationError(
                f"ALU ARG0={a0:#x} has bits above [18:4] set; SEQ_ISA v2.0 "
                f"defines ARG0[31:19] as spare and rtl/vec_alu.sv reads "
                f"cfg_len from [17:4] only.")
        sub, n = a0 & 0xF, nfield
        srca, srcb = GLS.dec_a1_lo(a1), GLS.dec_a1_hi(a1)
        p0 = GLS.dec_alu_p0(a0, a2)
        p0 = p0 - (1 << 17) if p0 >= (1 << 16) else p0
        dst = GLS.dec_alu_dst(a2)
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
        # SV1 (OV1 review I1): the RTL pops the x FIFO into x_mem WHENEVER
        # it pops (rtl/matvec_chan.sv:401-402), and the engine reads x_mem
        # for the whole stream, so a MOVX onto a channel whose no-wait
        # stream is still running corrupts that stream's x — which this
        # model (y computed at MVGO issue) would otherwise replay
        # bit-exactly.  Refused exactly as the MOVY below is.
        # SR11a (B17.2, R2): refused only if its XWIN WORD range overlaps
        # the pending stream's x range (the other bank is R2's overlap).
        if _movx_r3(self, r):       # B17.3 (R3-3): XPTR; a BROADCAST
            return                  # (chan 0xF) is executed there, whole
        n = r.len_or_addr_hi
        w0 = r.target & SF.MOVX_WORD_MASK
        p = self.running.get(r.chan)
        if p is not None and _overlap(w0, w0 + SF.movx_words(n), p[0], p[1]):
            raise RunningChannelError(
                f"MOVX writes mv{r.chan} XWIN words [{w0}, "
                f"{w0 + SF.movx_words(n)}) while a NO-WAIT MVGO still reads "
                f"words [{p[0]}, {p[1]}) — the stream needs a FENCE first")
        v = self.M.mem[r.addr_lo:r.addr_lo + n]
        assert np.all(v >= -128) and np.all(v <= 127), \
            "MOVX source is not int8-packed"
        self.xwin.write(r.chan, w0, v)

    def _mvgo(self, r):
        # SV1 (OV1 review I1): an engine start re-initialises a running
        # matvec unconditionally (rtl/matvec_engine.sv:478-485) and the
        # MVGO path does not look at the pending bit
        # (rtl/seq_movers.sv:721-731): a second MVGO on a running channel
        # is REFUSED, whatever its own wait bit — and whatever its banks
        # (SR11a: one engine per channel).
        if r.chan in self.running:
            raise RunningChannelError(
                f"MVGO starts mv{r.chan} while a NO-WAIT MVGO is still "
                "running on it — the stream needs a FENCE first")
        shape = r.imm32
        xbank = rbank = 0
        if self.shape_isa == HW.SHAPE_ISA_PRE_G3:
            # build_034 / build_035: {2'b0, w8[29], g64[28], nrows[27:12],
            # sh[11:6], ng[5:0]}.  `ng` keeps its meaning in BOTH weight
            # widths — the ng-UNIT count K//128 — so only the beat cadence
            # and the multiply move.  w8+g64 has no defined row format:
            # sw/hwmap.shape_word refuses to BUILD one and the pre-G3
            # matvec_engine $errors on one, so a stream carrying it is
            # corrupt and must not be executed here either.
            nrows = (shape >> 12) & 0xFFFF
            sh = (shape >> 6) & 0x3F
            ng = shape & 0x3F
            g = 64 if (shape & HW.SHAPE_G64) else 128
            w8 = bool(shape & HW.SHAPE_W8)
            assert not (w8 and g == 64), \
                f"MVGO SHAPE {shape:#010x} sets both W8 and g64 (no such format)"
            assert not (shape >> 30), \
                f"MVGO SHAPE {shape:#010x} sets a spare bit [31:30]"
        else:
            # G3.3 / this tree: {spare[31:29], ng[28:22], nrows[21:6],
            # sh[5:0]}.  The W8 and g64 engine modes are GONE, so there is
            # no bit to read them out of and no combination to reject.
            # SR11a (B17.2): bit 29 = XBANK, bit 30 = RBANK — admitted ONLY
            # under R2 (build_041/042 drop them); bit 31 stays spare.
            ng = (shape >> 22) & 0x7F
            nrows = (shape >> 6) & 0xFFFF
            sh = shape & 0x3F
            g, w8 = 128, False
            assert not (shape >> 31), \
                f"MVGO SHAPE {shape:#010x} sets the spare bit 31"
            assert "R2" in self.caps or not (shape >> 29), \
                f"MVGO SHAPE {shape:#010x} sets a spare bit [31:29]"
            xbank = (shape >> 29) & 1
            rbank = (shape >> 30) & 1
        wbase = ((r.len_or_addr_hi & 0xFF) << 32) | r.addr_lo
        beats = r.len_or_addr_hi >> 8
        xw0 = SF.XBANK_WORD * xbank
        x8 = self.xwin.read(r.chan, xw0 * 4)
        if x8 is None:
            raise UnwrittenReadError(
                f"MVGO on mv{r.chan} before any MOVX" if xw0 == 0 else
                f"MVGO XBANK on mv{r.chan}: no intact MOVX vector starts at "
                f"XWIN word {xw0}")
        y = self.W.matvec(wbase, nrows, sh, ng, g, x8, w8=w8, chan=r.chan)
        wid, r0, p, _avail = self.W._lookup(wbase, r.chan)
        assert beats == nrows * p["stride"] // 64, \
            f"MVGO BEATS {beats} != nrows*stride/64"
        assert nrows <= HW.RES_DEPTH, "MVGO chunk exceeds the RES BRAM"
        row0 = SF.RBANK_ROW * rbank
        self.res.write(r.chan, row0, y)
        if r.target & MVGO_NOWAIT:
            # v1.4: start and retire; the engine is still running as far as
            # the rest of the stream is concerned until a FENCE drains it.
            # SR11a: what it is still reading (x lines 48*XBANK .. +ng) and
            # writing (RES rows 2048*RBANK .. +nrows).
            self.running[r.chan] = (
                xw0, xw0 + SF.XWIN_LINE_WORDS * max(ng, 1),
                row0, row0 + max(nrows, 1))
            self.stats["MVGO_NOWAIT"] += 1
        else:
            self.running.pop(r.chan, None)

    def _movy(self, r):
        assert self.res.written(r.chan), f"MOVY on mv{r.chan} before any MVGO"
        n = r.len_or_addr_hi
        row0 = r.target >> 4
        p = self.running.get(r.chan)
        # SR11a (B17.2, R2): refused only if its row range overlaps the
        # pending stream's RES range (the other bank is legal to drain).
        if p is not None and _overlap(row0, row0 + n, p[2], p[3]):
            raise RunningChannelError(
                f"MOVY reads mv{r.chan} RES rows [{row0}, {row0 + n}) while a "
                f"NO-WAIT MVGO is still writing rows [{p[2]}, {p[3]}) — the "
                "stream needs a FENCE first (ISA v1.4)")
        y = self.res.read(r.chan, row0, n)
        if y is None:
            raise UnwrittenReadError(
                f"MOVY reads {n} RES rows from row {row0} on mv{r.chan}, not "
                "inside one live MVGO result")
        sh = SF.resolve_imm(r, self.xrf)
        v = rs_s(y, sh)
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
            # SR11a: the frozen isa=1 layout is STATED to the validator (its
            # bit 29 is w8, not XBANK); every other stream is validated with
            # the layout unstated, as before (so the ng envelope stays off).
            SF.validate(r, nrec=n, idx=pc, caps=self.caps,
                        shape_isa=(HW.SHAPE_ISA_PRE_G3
                                   if self.shape_isa == HW.SHAPE_ISA_PRE_G3
                                   else None))
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
                # SEQ_ISA v2.3 B17.1 (R1): target[3:0] is the channel mask,
                # bit c = channel c; mask 0 = all four (today's meaning).
                # A pending channel OUTSIDE the mask STAYS in `running`, so
                # the next MOVX / MVGO / MOVY on it raises
                # RunningChannelError — the RTL has no interlock (Q8), this
                # refusal and reorder_e4's hazard assert are the guard.  (A
                # non-zero mask reaches here only if validate() admitted it,
                # i.e. with "R1" in self.caps.)
                fmask = r.target & 0xF
                if fmask == 0:
                    self.running.clear()
                else:
                    for c in range(4):
                        if (fmask >> c) & 1:
                            self.running.pop(c, None)
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

    def __init__(self, path, emb=None, region=None):
        self.path = path
        self.region = region
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
            cmd = _TxtCmd(M, region=self.region)
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
                    cmd(op, a0, a1, a2)
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
                    # S3 (A1.3): ONE record, ALL 8 x NKVH counters.  The
                    # SEQ emitter expands it into eight LAYER writes and
                    # sixteen TCNT/TCNT2 writes, and `Mach.Treset` zeroes
                    # the whole array, so this must too.
                    M.T = [[0] * len(r) for r in M.T]
                elif t == "L":
                    # B15.2: {cv_slot[13:12], kv_layer[10:8],
                    #         kv_slot[4:3], dn_slot[1:0]}
                    v = int(it.next(), 16)
                    M.dn_slot, M.kv_slot = v & 0x3, (v >> 3) & 0x3
                    M.kv_layer, M.cv_slot = (v >> 8) & 0x7, (v >> 12) & 0x3
                    M.layer_is_set = True
                elif t == "S":
                    # SEQ_ISA v2.1 B15.3: the three region base CSRs and the
                    # region's size, all in 64 KiB units.  The replay reads
                    # its region from the manifest, so this is a CROSS-CHECK
                    # that the program and the artifact name the same
                    # address -- the exact drift spec 7.2 forbids.
                    sd, sk, sc, su = (int(it.next(), 16) for _ in range(4))
                    if self.region is not None:
                        p, u = self.region.plan, 1 << 16
                        assert (sd, sk, sc, su) == (
                            p["dn"] // u, p["kv"] // u, p["cv"] // u,
                            (p["end"] - p["dn"]) // u), (
                            f"the program's S record ({sd:x} {sk:x} {sc:x} "
                            f"{su:x}) disagrees with the manifest's state "
                            f"plan {p}")
                elif t == "B":
                    # SEQ_ISA v2.0 DNSB: {a_dec_base[31:16], a_beta[15:0]}
                    v = int(it.next(), 16)
                    cmd.set_dnsb(v)
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

    def __init__(self, M, region=None):
        self.x = SeqExec.__new__(SeqExec)
        self.x.M = M
        self.x.xrf = [0] * XRF_N
        self.x.issued = 0
        self.x.eps_scale_log = []
        self.x.dnsb = None
        self.x.region = region

    def set_dnsb(self, val):
        """A .txt B record — the DNSB layer CSR write (SEQ_ISA v2.0)."""
        self.x.dnsb = val & 0xFFFFFFFF
        self.x.M.dnsb_bases = (val & 0xFFFF, (val >> 16) & 0xFFFF)

    def __call__(self, op, a0, a1, a2):
        self.x.args = [a0, a1, a2]
        self.x._layer_cmd(op)


# ======================================================================
# gate
# ======================================================================
def state_verdict(reg_txt, reg_seq, base, _absent_is_ok=False):
    """The STATE line's verdict: (ok, blocks_stored, [reasons]).

    Split out of `gate()` so it can be DRIVEN (S3 fix round 2, I5): the
    round-1 selftest asserted nothing about this, and the property it is
    supposed to hold — that a MISSING emitter image is not a pass — was
    therefore untested.  `_absent_is_ok` reproduces the PRE-FIX behaviour
    and exists only so the selftest's RED half can be run without editing
    this file.

    Two comparisons, and they answer different questions:
      .txt vs .seq   the two replays stored the same bytes
      .seq vs the EMITTER's final image (<base>.state_final.bin, written by
                     ref/gen_layer_script.StateImage) -- the two INDEPENDENT
                     implementations of B15.1's byte layouts agree, which is
                     what spec 6.5 asks for and what makes the SMEM golden
                     worth having.
    """
    lines, n, ok = [], 0, True
    if reg_seq is None:
        return ok, n, lines
    n = len(reg_seq.touched)
    if reg_txt is None or not np.array_equal(reg_txt.mem, reg_seq.mem):
        ok = False
        lines.append(".txt and .seq state regions differ")
    fin = base + ".state_final.bin"
    if os.path.exists(fin):
        with open(fin, "rb") as f:
            emitted = np.frombuffer(f.read(), dtype=np.uint8)
        if len(emitted) != len(reg_seq.mem):
            ok = False
            lines.append(f"emitter image {len(emitted)} B, region "
                         f"{len(reg_seq.mem)} B")
        elif not np.array_equal(emitted, reg_seq.mem):
            bad = int(np.count_nonzero(emitted != reg_seq.mem))
            ok = False
            lines.append(f"emitter StateImage and StateRegion differ in "
                         f"{bad} bytes")
    else:
        # S3 fix round 1, I5.  A MISSING emitter image is not a pass: with
        # no file there is no cross-check to report.
        if not _absent_is_ok:
            ok = False
        lines.append(
            f"{fin} is ABSENT — the emitter's final image was never "
            f"written, so the two independent implementations were NOT "
            f"compared (re-emit the artifact)")
    return ok, n, lines


def gate(prefix, use_files=True, verbose=True, base=None, caps=frozenset()):
    """Replay <base>.txt against <prefix>.seq and assert they agree.

    `base` defaults to `prefix`; giving it separately lets SEVERAL SEQ
    streams (one per profile / emitter option) share ONE set of generator
    artifacts (.txt, .weights.json, the weight images, .emb.bin), which is
    what makes an A/B of the emitter affordable on model_v2.

    `caps` (SR4, SEQ_ISA v2.3 B17.0): the capability set the stream is
    validated and executed at — named by the CALLER (`--caps R1` for an r1
    stream), never read from the manifest; empty = today's rules.
    """
    t0 = time.time()
    caps = HW.seq_caps_check(caps)
    base = prefix if base is None else base
    meta = json.load(open(prefix + ".seq.json"))
    stream = open(prefix + ".seq", "rb").read()
    blob = open(prefix + ".seqdata.bin", "rb").read()
    assert hashlib.sha256(stream).hexdigest() == meta["stream_sha256"]
    assert hashlib.sha256(blob).hexdigest() == meta["seqdata_sha256"]
    recs = SF.unpack_stream(stream)
    # G3.4 fix round 2: state the SHAPE layout THIS ARTIFACT declares.
    # `gate()` can be pointed at a frozen build_034/build_035 prefix as
    # easily as at a 9B one, and the layout is a property of the artifact
    # -- so it comes from the artifact's own meta, absent meaning "not
    # stated" and the MVGO envelope staying off.  Hard-coding isa=2 here
    # would refuse a frozen stream that is perfectly legal for the
    # bitstream it was emitted for.
    SF.validate_stream(recs, shape_isa=meta.get("shape_isa"), caps=caps)

    embf = base + ".emb.bin"
    emb = None
    if os.path.exists(embf):
        # R-b: the row stride comes from the manifest (2*H), not a literal
        rb = HW.load_weights_manifest(base)[1]["emb_row_bytes"]
        n = os.path.getsize(embf) // rb
        emb = np.memmap(embf, dtype="<i2", mode="r").reshape(n, rb // 2)

    if verbose:
        print(f"--- SEQ gate: {prefix}")
        print(f"  stream   {len(recs)} records, {len(stream)} B "
              f"(sha256 {meta['stream_sha256'][:16]})")
        print(f"  seqdata  {len(blob)} B "
              f"(sha256 {meta['seqdata_sha256'][:16]})")
        print(f"  profile  {meta['profile']}   newops from "
              f"{meta['newops_source']}")
        print(f"  opcodes  {meta['opcode_histogram']}")
        print(f"  caps     {sorted(caps) or 'none'} (validated and executed "
              f"at this set; SEQ_ISA v2.3 B17.0)")
        print(f"  loop     {meta['loop_steps']} steps  ({meta['loop_note']})"
              + ("" if not meta.get("loop_steps") else
                 ("  STRUCTURALLY SAFE" if meta.get("loop_structurally_safe")
                  else "  NOT structurally safe: the body still carries "
                       "data-dependent immediates (SEQ_ISA A3) that merely "
                       "coincided on this input")))

    # SEQ_ISA v2.1: two INDEPENDENT state regions, one per replay, both
    # loaded from the artifact's initial image.  `None` for a pre-S3 or
    # frozen artifact, which carries no `state` plan and emits no SLD/SST.
    reg_txt = StateRegion.load(base)
    reg_seq = StateRegion.load(base)
    ref = TxtReplay(base + ".txt", emb=emb, region=reg_txt).run()
    t1 = time.time()
    W = DDRWeights.from_files(base, meta["weights"], meta)
    ex = SeqExec(recs, blob, W, emb=emb,
                 checkpoints=meta.get("checkpoints"),
                 region=reg_seq, caps=caps).run(max_steps=50 * len(recs))
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
    stage = np.zeros(GLS.SCRATCH, dtype=bool)
    for (a, b) in meta.get("staging_words", []):
        stage[a:b] = True
    memdiff = np.nonzero(sa["mem"] != sb["mem"])[0]
    live_bad = [int(i) for i in memdiff if not stage[i]]
    d = [x for x in d if not x.startswith("mem:")]

    # --- 2b. the DDR state region ----------------------------------------
    # TWO comparisons, and they answer different questions.
    #   .txt vs .seq   the two replays stored the same bytes (the same
    #                  lockstep every other check here is)
    #   .seq vs the EMITTER'S final image (<base>.state_final.bin, written
    #                  by ref/gen_layer_script.StateImage)  --  the two
    #                  INDEPENDENT implementations of B15.1's byte layouts
    #                  agree, which is what spec 6.5 asks for and what makes
    #                  the SMEM golden worth having.
    st_ok, st_n, st_lines = state_verdict(reg_txt, reg_seq, base)

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
        print(f"  SCRATCH  {len(memdiff)} of {GLS.SCRATCH} words differ at "
              f"the end; "
              f"{len(live_bad)} outside the declared y32 staging windows "
              f"({int(stage.sum())} words) -> "
              f"{'CLEAN' if not live_bad else 'DIVERGENCE'}")
        print(f"  BANKED   {'BIT-EXACT' if not d else 'MISMATCH'} "
              f"(conv/S/KV/TCNT/EOUT/AMAX)")
        for line in d[:12]:
            print(f"    ! {line}")
        if reg_seq is None:
            print("  STATE    no state plan in the manifest (pre-v2.1 "
                  "artifact) -- not compared")
        else:
            print(f"  STATE    {'BIT-EXACT' if st_ok else 'MISMATCH'} "
                  f"({st_n} block(s) stored; .txt vs .seq vs the emitter's "
                  f"StateImage)")
        for line in st_lines[:6]:
            print(f"    ! {line}")
        print(f"  TOKENS   {'IDENTICAL' if tok_ok else 'MISMATCH'}  "
              f"{ex.out_fifo}")
    ok = cp_ok and (not d) and (not live_bad) and tok_ok and st_ok
    return ok, {"state_blocks": st_n, "state_ok": bool(st_ok),
                "state_diffs": st_lines,
                "nrec": len(recs), "stream_bytes": len(stream),
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


def selftest_w8_mvgo(seed=5):
    """A synthetic W8 MVGO record, decoded and executed end to end (V5).

    This is the SHAPE bit-29 decode of `_mvgo` under test, and the W8 half
    of `DDRWeights.matvec` behind it.  One image is built with the
    production W8 quantizer and offered to the executor BOTH ways the
    engine model can see it:

      * `from_wids` — the generator's live quantized dict (a `{"w8",m,e,
        sh,g}` layer_fixed image), and
      * `from_files` — the packed DDR bytes, i.e. `pack_ddr_rows8` ->
        `unpack_ddr_rows8`, which is what a replay of a real stream reads.

    Both must reproduce `w4a8_ref.matvec_y32_w8` on the same activation,
    bit for bit.  Three negative cases follow, because a SHAPE word that
    is merely IGNORED would pass the positive one:

      * the same image addressed with a W4 SHAPE word must NOT execute
        (the plan/SHAPE cross-check fires) and vice versa;
      * `w8 + g64` has no defined row format and must be refused, exactly
        as `hwmap.shape_word` and `rtl/matvec_engine.sv` refuse it.
    """
    import tempfile
    from w4a8_ref import (matvec_y32_w8, pack_ddr_rows8, quantize_acts,
                          quantize_weights8, row_stride8)
    rng = np.random.default_rng(seed)
    N, K, g, chan = 17, 256, 128, 1
    W = rng.normal(0, 0.02, (N, K))
    w8, m, e, sh = quantize_weights8(W, g=g)
    x8, _xs = quantize_acts(rng.normal(0, 1.0, K))
    y_ref = np.asarray(matvec_y32_w8(w8, m, sh, x8, g=g), dtype=I64)
    img, stride = pack_ddr_rows8(w8, m, g=g)
    assert stride == row_stride8(K, g)
    qw = {"w8": w8, "m": m, "e": int(e), "sh": int(sh), "g": g}
    plan = {0: {"base": HW.W_BASE, "nrows": N, "k": K, "ng": K // 128,
                "sh": int(sh), "g": g, "w8": True, "stride": stride,
                "nbeats": N * stride // 64}}

    def _stream(shape_word):
        beats = N * stride // 64
        return [SF.Rec(OP_MOVX, flags=(chan << SF.CHAN_SHIFT),
                       addr_lo=0, len_or_addr_hi=K),
                SF.Rec(OP_MVGO, flags=(chan << SF.CHAN_SHIFT), target=0,
                       imm32=shape_word, addr_lo=HW.W_BASE & 0xFFFFFFFF,
                       len_or_addr_hi=((beats << 8)
                                       | ((HW.W_BASE >> 32) & 0xFF))),
                SF.Rec(OP_HALT)]

    def _run(weights, shape_word):
        # THE PRE-G3 LAYOUT, deliberately: this selftest is build_035's W8
        # golden (spec 3.3 keeps the host's W8 law), and this tree's own
        # SHAPE word has no W8 bit to set.
        ex = SeqExec(_stream(shape_word), b"", weights, isa=HW.SHAPE_ISA_PRE_G3)
        ex.M.mem[0:K] = np.asarray(x8, dtype=I64)
        ex.run()
        return ex.res[chan]

    good = HW.shape_word(N, int(sh), K // 128, g=g, w8=True, isa=1)
    assert good & HW.SHAPE_W8 and not (good & HW.SHAPE_G64)
    with tempfile.TemporaryDirectory() as td:
        fn = os.path.join(td, "w8_0.bin")
        with open(fn, "wb") as f:
            f.write(img)
        with open(os.path.join(td, "sel.weights.json"), "w") as f:
            json.dump({"0": {"file": "w8_0.bin", "nrows": N, "k": K,
                             "ng": K // 128, "sh": int(sh), "e": int(e),
                             "w8": True, "stride": stride,
                             "nbeats": N * stride // 64}}, f)
        WF = DDRWeights.from_files(os.path.join(td, "sel"), plan)
        WW = DDRWeights.from_wids({"a": (0, qw)}, plan)
        y_bytes = _run(WF, good)
        y_live = _run(WW, good)
    ok = bool(np.array_equal(y_bytes, y_ref) and np.array_equal(y_live, y_ref))
    # --- the SHAPE bit must be LOAD-BEARING, not decorative ---------------
    caught = 0
    for bad in (HW.shape_word(N, int(sh), K // 128, g=g, isa=1),   # W4 word
                good | HW.SHAPE_G64):                              # w8 + g64
        try:
            _run(WW, bad)
        except AssertionError:
            caught += 1
    ok &= (caught == 2)
    return {"nrows": N, "k": K, "stride": stride, "shape": good,
            "y_max": int(np.abs(y_ref).max()), "refused": caught, "ok": ok}


def selftest_repack(seed=7):
    """R-c directed case: the PER-CHANNEL weight repack, addressed end to end.

    Two W8 images across nch=2, image 0 placed with LAYOUT_ILV (the LM head's
    chunk interleave, so a channel's rows are STRIDED through the image) and
    image 1 with LAYOUT_CONTIG.  The three sides that must agree on where a
    row lives are all the REAL ones:

      * the EMITTER's allocator — `seq_format.plan_weights_from_wids(
        repack=True)`, i.e. `hwmap.plan_weights` with per-channel row counts;
      * the HOST's placement — `sw/seq_run.plan_weight_split`, which says
        which file slice it DMAs to which channel-local address;
      * this MODEL — `DDRWeights` resolving that address, on that channel,
        back to the GLOBAL rows of the image.

    Every piece is then executed as a real MVGO and compared against
    `w4a8_ref.matvec_y32_w8` on the rows the piece is supposed to hold, so a
    plausible-but-wrong address (off by a chunk, or the right rows on the
    wrong channel) produces wrong NUMBERS, not just a different map.

    Two negative controls, because a per-channel address that is merely
    IGNORED would pass the positive test: the same stream resolved against
    the nch-INDEPENDENT plan must not reproduce the same rows, and a WBASE
    taken from channel 0 must not resolve on channel 1.
    """
    import tempfile
    from w4a8_ref import (matvec_y32_w8, pack_ddr_rows8, quantize_acts,
                          quantize_weights8, row_stride8)
    here = os.path.dirname(os.path.abspath(__file__))
    sw = os.path.join(os.path.dirname(here), "sw")
    if sw not in sys.path:
        sys.path.insert(0, sw)
    import seq_run as SR                                       # noqa: E402
    rng = np.random.default_rng(seed)
    nch, g, depth = 2, 128, 4        # 4-row chunks: a small image still
    shapes = [(20, 256), (13, 128)]  # interleaves over both channels
    wids, imgs, man = {}, {}, {}
    for wid, (N, K) in enumerate(shapes):
        w8, m, e, sh = quantize_weights8(rng.normal(0, 0.02, (N, K)), g=g)
        wids[f"w{wid}"] = (wid, {"w8": w8, "m": m, "e": int(e),
                                 "sh": int(sh), "g": g})
        img, stride = pack_ddr_rows8(w8, m, g=g)
        assert stride == row_stride8(K, g)
        imgs[wid] = (img, stride, N, K, int(sh), w8, m)
        man[str(wid)] = {"file": f"rp_w{wid}.bin", "nrows": N, "k": K,
                         "ng": K // 128, "sh": int(sh), "e": int(e),
                         "w8": True, "stride": stride,
                         "nbeats": N * stride // 64}
    lay = {0: SF.LAYOUT_ILV, 1: SF.LAYOUT_CONTIG}
    plan = SF.plan_weights_from_wids(wids, nch=nch, repack=True,
                                     layout_of=lay, chunk_rows=depth)
    legacy = SF.plan_weights_from_wids(wids)
    meta = {"nch": nch, "weight_repack": True,
            "weight_layout": {"nch": nch, "chunk_rows": depth,
                              "default": SF.LAYOUT_CONTIG,
                              "by_wid": {str(k): v for k, v in lay.items()},
                              "ilv_wids": [0]}}
    # the pack really is per-channel, and really is smaller than one span.
    # BOTH numbers are TOPS — base + the bytes that base actually holds —
    # not the last base, which is what this reported before the R-c review.
    wb = {w: p["base"] for w, p in plan.items()}
    span = max(int(p["base"]) + p["nrows"] * p["stride"]
               for p in legacy.values()) - HW.W_BASE
    rows_c = {w: SF.chan_rows(plan[w]["nrows"], nch, lay[w], depth)
              for w in plan}
    chan_top = [max(plan[w]["base"][c] + rows_c[w][c] * plan[w]["stride"]
                    for w in plan) - HW.W_BASE for c in range(nch)]
    ok = all(t < span for t in chan_top)
    splits = SR.plan_weight_split(man, wb, nch, list(range(nch)), meta)
    with tempfile.TemporaryDirectory() as td:
        for wid, (img, _s, _N, _K, _sh, _w, _m) in imgs.items():
            with open(os.path.join(td, f"rp_w{wid}.bin"), "wb") as f:
                f.write(img)
        with open(os.path.join(td, "rp.weights.json"), "w") as f:
            json.dump(man, f)
        W = DDRWeights.from_files(os.path.join(td, "rp"), plan, meta)
        Wleg = DDRWeights.from_files(os.path.join(td, "rp"), legacy)
        npiece, nmis = 0, 0
        for s in splits:
            wid, c, r0, n = s["wid"], s["chan"], s["r0"], s["nrows_piece"]
            _img, stride, N, K, sh, w8m, m = imgs[wid]
            x8, _xs = quantize_acts(rng.normal(0, 1.0, K))
            y_ref = np.asarray(matvec_y32_w8(w8m[r0:r0 + n], m[r0:r0 + n],
                                             sh, x8, g=g), dtype=I64)
            beats = n * stride // 64
            addr = s["local_addr"]
            st = [SF.Rec(OP_MOVX, flags=(c << SF.CHAN_SHIFT), addr_lo=0,
                         len_or_addr_hi=K),
                  SF.Rec(OP_MVGO, flags=(c << SF.CHAN_SHIFT), target=0,
                         imm32=HW.shape_word(n, sh, K // 128, g=g, w8=True,
                                             isa=HW.SHAPE_ISA_PRE_G3),
                         addr_lo=addr & 0xFFFFFFFF,
                         len_or_addr_hi=((beats << 8)
                                         | ((addr >> 32) & 0xFF))),
                  SF.Rec(OP_HALT)]
            ex = SeqExec(st, b"", W, isa=HW.SHAPE_ISA_PRE_G3)
            ex.M.mem[0:K] = np.asarray(x8, dtype=I64)
            ex.run()
            ok &= bool(np.array_equal(ex.res[c], y_ref))
            npiece += 1
            # negative 1: the nch-INDEPENDENT plan reads other rows there
            try:
                w2, r2, _p2, _a2 = Wleg._lookup(addr)
                nmis += int((w2, r2) != (wid, r0))
            except AssertionError:
                nmis += 1
            # negative 2: channel 0's address must not resolve on channel 1
            if c == 0 and s["row_off"] != s["r0"]:
                try:
                    w3, r3, _p3, _a3 = W._lookup(addr, 1)
                    nmis += int((w3, r3) != (wid, r0))
                except AssertionError:
                    nmis += 1
    ok &= (nmis > 0)
    return {"nch": nch, "images": len(man), "pieces": npiece,
            "span": span, "chan_top": chan_top, "caught": nmis, "ok": ok}


def _selftest():
    print("dynq16/eps-norm semantics from:", SF.NEWOPS_SOURCE)
    r = selftest_ops()
    print(f"DYNQ16 == op1+dn_o_shift on {r['blocks']}/{r['blocks']} blocks")
    print(f"EPS-NORM vs frozen dn_norm_scale: {r['identical']}/{r['blocks']} "
          f"blocks bit-identical, worst |delta| = {r['worst_abs_delta']} LSB")
    w = selftest_w8_mvgo()
    print(f"W8 MVGO (SHAPE {w['shape']:#010x}, {w['nrows']}x{w['k']}, stride "
          f"{w['stride']}B): packed-DDR and live-dict paths both == "
          f"matvec_y32_w8 (|y|max {w['y_max']}), {w['refused']}/2 wrong "
          f"SHAPE words refused — {'PASS' if w['ok'] else 'FAIL'}")
    if not w["ok"]:
        raise SystemExit("SEQ_MODEL W8 SELFTEST FAIL")
    p = selftest_repack()
    print(f"REPACK (nch={p['nch']}, {p['images']} W8 images, {p['pieces']} "
          f"pieces): every piece's MVGO == matvec_y32_w8 on its global rows; "
          f"per-channel packs {p['chan_top']} B vs one span {p['span']} B; "
          f"{p['caught']} wrong-plan/wrong-channel lookups refused or "
          f"diverted — {'PASS' if p['ok'] else 'FAIL'}")
    if not p["ok"]:
        raise SystemExit("SEQ_MODEL REPACK SELFTEST FAIL")
    t = selftest_state_region()
    print(f"STATE REGION ({t['checks']} checks): the B15.1 block addresses, "
          f"a DN/KV/CV round trip through Mach's slots, the KV length at "
          f"TCNT, the {t['refused']}/3 range refusals, and the STATE "
          f"verdict's {t['red']}/1 RED (a missing emitter image is NOT "
          f"bit-exact) — {'PASS' if t['ok'] else 'FAIL'}")
    if not t["ok"]:
        raise SystemExit("SEQ_MODEL STATE REGION SELFTEST FAIL")
    _selftest_refusal()
    return r


def _selftest_refusal():
    q = selftest_running_refusal()
    print(f"RUNNING-CHANNEL REFUSAL (SV1 + SR4 masked FENCE + SR11a ranges): {q['cases']} — "
          f"{q['refused']}/{q['hazards']} hazards refused, legal orders "
          f"accepted, {q['reads_refused']}/{q['reads']} unwritten reads "
          f"refused — "
          f"{'PASS' if q['ok'] else 'FAIL'}")
    if not q["ok"]:
        raise SystemExit("SEQ_MODEL RUNNING-CHANNEL REFUSAL SELFTEST FAIL")


def selftest_running_refusal():
    """SV1 (OV1 review I1): MOVX and MVGO on a channel whose NO-WAIT stream
    is still running are REFUSED, as MOVY already is.

    On the RTL a MOVX pops into x_mem under the running engine
    (rtl/matvec_chan.sv:401-402) and a second MVGO re-initialises it
    (rtl/matvec_engine.sv:478-485), while this model computes y at MVGO
    issue and so would replay either bit-exactly.  A reorder pass that
    hoists a MOVX/MVGO past its FENCE must therefore fail HERE.

    Seven streams on a stub engine (the refusal sits before any weight is
    touched): the two legal orders pass (channel 0, and channel 1 so a
    mis-encoded channel field cannot pass by accident), and each of MOVX /
    MVGO / MOVY on the running channel is refused (5 hazards); a MOVX on a
    DIFFERENT channel is legal.  SR4 adds four streams at caps {"R1"}: a
    FENCE whose mask SKIPS a pending channel leaves it running, and MOVX /
    MVGO / MOVY on it are refused (3 more hazards); masks that cover every
    channel before its next use are legal.  SR11a adds five streams at caps
    {"R1","R2"} (SEQ_ISA v2.3 B17.2, RUNNING RANGES): a MOVX into the bank
    the pending stream reads, a MOVY of the RES half it writes, and a MVGO
    on its channel in the other banks are refused (3 more hazards); a MOVX
    into the other bank and a MOVY of the other half are legal."""
    class _StubW(object):
        def matvec(self, wbase, nrows, sh, ng, g, x8, w8=False, chan=None):
            return np.zeros(nrows, dtype=I64)

        def _lookup(self, wbase, chan=None):
            return 0, 0, {"stride": 64}, 0

    nrows = 4
    shape = HW.shape_word(nrows, 0, 1)

    def movx(c):
        return SF.Rec(OP_MOVX, flags=(c << SF.CHAN_SHIFT), addr_lo=0,
                      len_or_addr_hi=128)

    def mvgo(c):
        return SF.Rec(OP_MVGO, flags=(c << SF.CHAN_SHIFT),
                      target=MVGO_NOWAIT, imm32=shape,
                      addr_lo=HW.W_BASE & 0xFFFFFFFF,
                      len_or_addr_hi=((nrows << 8)
                                      | ((HW.W_BASE >> 32) & 0xFF)))

    def movy(c):
        # fix round 1 (M-S3): MOVY carries its channel in TARGET
        # (ref/seq_format.py Rec.chan), not in flags
        return SF.Rec(OP_MOVY, target=c, addr_lo=256,
                      len_or_addr_hi=nrows)

    fence, halt = SF.Rec(OP_FENCE), SF.Rec(OP_HALT)

    def movxw(c, word):
        # SR11a: a MOVX at an XWIN start word (B17.2)
        return SF.Rec(OP_MOVX, flags=(c << SF.CHAN_SHIFT), target=word,
                      addr_lo=0, len_or_addr_hi=128)

    def mvgob(c, xb, rb, wait=False):
        # SR11a: a MVGO with the XBANK / RBANK SHAPE bits (B17.2)
        return SF.Rec(OP_MVGO, flags=(c << SF.CHAN_SHIFT),
                      target=(0 if wait else MVGO_NOWAIT),
                      imm32=(shape | (SF.SHAPE_XBANK if xb else 0)
                             | (SF.SHAPE_RBANK if rb else 0)),
                      addr_lo=HW.W_BASE & 0xFFFFFFFF,
                      len_or_addr_hi=((nrows << 8)
                                      | ((HW.W_BASE >> 32) & 0xFF)))

    def movyr(c, row):
        # SR11a: a MOVY from a RES start row (B17.2)
        return SF.Rec(OP_MOVY, target=(row << 4) | c, addr_lo=256,
                      len_or_addr_hi=nrows)

    def fm(mask):
        # SR4: a masked FENCE (SEQ_ISA v2.3 B17.1)
        return SF.Rec(OP_FENCE, target=mask)
    cases = {
        "legal": ([movx(0), mvgo(0), movx(1), fence, movy(0), movx(0),
                   mvgo(0), fence, movy(0), halt], True),
        "movx_on_running": ([movx(0), mvgo(0), movx(0), fence, halt], False),
        "mvgo_on_running": ([movx(0), mvgo(0), mvgo(0), fence, halt], False),
        "movy_on_running": ([movx(0), mvgo(0), movy(0), fence, halt], False),
        # fix round 1 (M-S3): a channel other than 0, so a MOVY whose
        # channel field were mis-encoded could not pass by accident
        "legal_c1": ([movx(1), mvgo(1), fence, movy(1), halt], True),
        "movy_on_running_c1": ([movx(1), mvgo(1), movy(1), fence, halt],
                               False),
        "movx_on_running_c1": ([movx(1), mvgo(1), movx(1), fence, halt],
                               False),
        # SR4 (SEQ_ISA v2.3 B17.1, run at caps {"R1"}): a masked FENCE that
        # FORGETS a pending channel leaves it running, so each of MOVX /
        # MVGO / MOVY on it is still refused; masks that cover it pass
        "r1_legal_masked": ([movx(0), mvgo(0), movx(1), mvgo(1), fm(0b0010),
                             movy(1), fm(0b0001), movy(0), halt], True),
        "r1_movx_mask_skipped": ([movx(0), mvgo(0), movx(1), mvgo(1),
                                  fm(0b0010), movx(0), fence, halt], False),
        "r1_mvgo_mask_skipped": ([movx(0), mvgo(0), movx(1), mvgo(1),
                                  fm(0b0010), mvgo(0), fence, halt], False),
        "r1_movy_mask_skipped": ([movx(0), mvgo(0), movx(1), mvgo(1),
                                  fm(0b0001), movy(1), fence, halt], False),
        # SR11a (SEQ_ISA v2.3 B17.2, run at caps {"R1","R2"}): running
        # RANGES — the other bank is legal, the pending one is refused
        "r2_legal_other_banks": ([movx(0), mvgo(0), movxw(0, 1536), fence,
                                  mvgob(0, 1, 1, wait=True), movyr(0, 2048),
                                  halt], True),
        "r2_legal_drain_bank0": ([movx(0), mvgob(0, 0, 0, wait=True),
                                  movxw(0, 1536), mvgob(0, 1, 1),
                                  movyr(0, 0), fence, halt], True),
        "r2_movx_pending_bank": ([movxw(0, 1536), mvgob(0, 1, 0),
                                  movxw(0, 1536), fence, halt], False),
        "r2_movy_pending_half": ([movx(0), mvgob(0, 0, 1),
                                  movyr(0, 2048), fence, halt], False),
        "r2_mvgo_other_banks": ([movx(0), mvgo(0), movxw(0, 1536),
                                 mvgob(0, 1, 1), fence, halt], False),
    }
    # SR4 fix round 1: a hazard counts as refused ONLY on RunningChannelError
    # -- any other exception (e.g. a SeqValidationError from running an r1_
    # stream at the wrong caps, or a stub failure) is recorded as "error"
    # and fails the selftest, so no case can pass vacuously
    got = {}
    for name, (recs, want_ok) in cases.items():
        try:
            SeqExec(recs, b"", _StubW(),
                    caps=({"R1"} if name.startswith("r1_") else
                          {"R1", "R2"} if name.startswith("r2_")
                          else ())).run()
            got[name] = True
        except RunningChannelError as e:
            got[name] = False
            if want_ok:
                print(f"  refusal selftest: {name} raised: {e}")
        except Exception as e:              # noqa: BLE001
            got[name] = "error"
            print(f"  refusal selftest: {name} raised {type(e).__name__} "
                  f"(not RunningChannelError): {e}")
    ok = all(got[n] is w for n, (_r, w) in cases.items())
    # SR11a fix round 1 (M1): the two STRICTER-READ refusals are explicit
    # raises too — one case each, refused ONLY on UnwrittenReadError
    reads = {
        # a later MOVX at word 16 overwrites part of the word-0 vector, so
        # no intact vector starts where the MVGO reads (needs R2's start word)
        "read_mvgo_no_intact_x": ([movx(0), movxw(0, 16),
                                   mvgob(0, 0, 0, wait=True), halt],
                                  {"R1", "R2"}),
        # the MVGO wrote 4 rows; a MOVY of rows 2048.. reads none of them
        "read_movy_outside_result": ([movx(0), mvgob(0, 0, 0, wait=True),
                                      movyr(0, 2048), halt], {"R1", "R2"}),
    }
    for name, (recs, caps) in reads.items():
        try:
            SeqExec(recs, b"", _StubW(), caps=caps).run()
            got[name] = True
        except UnwrittenReadError:
            got[name] = False
        except Exception as e:              # noqa: BLE001
            got[name] = "error"
            print(f"  refusal selftest: {name} raised {type(e).__name__} "
                  f"(not UnwrittenReadError): {e}")
    rok = all(got[n] is False for n in reads)
    return {"cases": got,
            "refused": sum(1 for n in cases if got[n] is False),
            "hazards": sum(1 for (_r, w) in cases.values() if not w),
            "reads_refused": sum(1 for n in reads if got[n] is False),
            "reads": len(reads), "ok": ok and rok}


def selftest_state_region(seed=11):
    """`StateRegion` on its own: the addresses, a round trip, the refusals.

    S3 fix round 1, I5/I7.  The SEQ gate exercises this class against real
    artifacts; this is the part that can be driven WITHOUT one, so a broken
    address or a lost row shows up in `--selftest` and not only in a
    two-minute replay.  It also pins the property I5 is about: `gate()` may
    not report `STATE BIT-EXACT` when the emitter's image is absent.
    """
    rng = np.random.default_rng(seed)
    plan = HW.plan_state(HW.plan_state_base(4))
    reg = StateRegion(plan)
    n, refused = 0, 0

    # --- B15.1's addresses, against the ISA's own arithmetic -------------
    for (kind, layer, head, want) in (
            (HW_K_DN, 0, 0, plan["dn"]),
            (HW_K_DN, 23, 0, plan["dn"] + 23 * HW.STATE_DN_LAYER),
            (HW_K_CV, 23, 0, plan["cv"] + 23 * HW.STATE_CV_STRIDE),
            (HW_K_KV, 0, 0, plan["kv"]),
            (HW_K_KV, 7, 7, plan["kv"] + ((7 * 4 + 3) * 2 + 1)
             * HW.STATE_KV_STRIDE)):
        a, _ln = reg.addr_of(kind, layer, head)
        assert a == want, (kind, layer, head, hex(a), hex(want))
        n += 1
    for bad in (lambda: reg.addr_of(HW_K_DN, 24, 0),
                lambda: reg.addr_of(HW_K_KV, 8, 0),
                lambda: reg.addr_of(HW_K_DN, 0, 1)):
        try:
            bad()
        except (AssertionError, SF.SeqValidationError):
            refused += 1
    n += refused

    # --- a round trip of every kind, through a real Mach's slots ---------
    M = _fresh_mach()
    M.S[0] = rng.integers(-32768, 32767, M.S[0].shape, dtype=np.int64)
    M.cw[0] = rng.integers(-32768, 32767, M.cw[0].shape, dtype=np.int64)
    M.cs[0] = rng.integers(-32768, 32767, M.cs[0].shape, dtype=np.int64)
    M.slot_id[GLS.K_DN][0] = (5, 0)
    M.slot_id[GLS.K_CV][0] = (5, 0)
    S_ref, cw_ref, cs_ref = M.S[0].copy(), M.cw[0].copy(), M.cs[0].copy()
    reg.sst(M, HW_K_DN, 0, 5, 0)
    reg.sst(M, HW_K_CV, 0, 5, 0)
    M.S[0][:] = 0
    M.cw[0][:] = 0
    M.cs[0][:] = 0
    reg.sld(M, HW_K_DN, 1, 5, 0)
    reg.sld(M, HW_K_CV, 1, 5, 0)
    assert np.array_equal(M.S[1], S_ref), "DN block did not round trip"
    assert np.array_equal(M.cw[1], cw_ref), "conv weights did not round trip"
    assert np.array_equal(M.cs[1], cs_ref), "conv state did not round trip"
    n += 3

    # KV: the length is TCNT, and the exponent side array travels with it
    T = 37
    M.T[3][2] = T
    rows = [(rng.integers(-128, 127, GLS.LR.HD, dtype=np.int64),
             int(rng.integers(-40, 40))) for _ in range(T)]
    M.kc[0] = [(a.copy(), e) for a, e in rows]
    M.vc[0] = [(a.copy(), e) for a, e in rows]
    reg.sst(M, HW_K_KV, 0, 3, (2 << 1))
    reg.sst(M, HW_K_KV, 0, 3, (2 << 1) | 1)
    M.kc[0], M.vc[0] = [], []
    reg.sld(M, HW_K_KV, 1, 3, (2 << 1))
    reg.sld(M, HW_K_KV, 1, 3, (2 << 1) | 1)
    assert len(M.kc[1]) == T and len(M.vc[1]) == T, "KV depth is not TCNT"
    assert all(np.array_equal(a, b[0]) and e == b[1]
               for (a, e), b in zip(rows, M.kc[1])), "KV rows/exponents moved"
    assert M.tag[1] == (3, 2), "the SLD did not set the slot's tag"
    assert M.warm[HW_K_KV][1] and not M.warm[HW_K_KV][0], "warm bits wrong"
    n += 4

    # a KV block of a DIFFERENT (layer, kvhead) must be untouched by all that
    a0, ln = reg.addr_of(HW_K_KV, 4, 0)
    off = a0 - plan["dn"]
    assert not reg.mem[off:off + ln].any(), "an unrelated KV block moved"
    n += 1

    # --- I5: the STATE verdict, RED then GREEN ---------------------------
    # S3 fix round 2.  The round-1 version of this block created a temp dir
    # and asserted a file it had never created was absent, which is not a
    # test of anything.  This one DRIVES the function `gate()` uses.
    import tempfile as _tf
    red_caught = 0
    with _tf.TemporaryDirectory() as td:
        base = os.path.join(td, "none")
        reg2 = StateRegion(plan)
        reg2.mem[:] = reg.mem                       # the two replays agree
        reg2.touched = set(reg.touched)
        assert not os.path.exists(base + ".state_final.bin")

        # RED: the PRE-FIX behaviour — a missing image reported bit-exact
        ok_red, _n_red, why_red = state_verdict(reg, reg2, base,
                                                _absent_is_ok=True)
        assert ok_red and why_red, (
            "the RED control did not reproduce the pre-fix verdict")
        red_caught += 1
        # GREEN: the shipped behaviour — a missing image is NOT bit-exact,
        # and it says why
        ok, _n2, why = state_verdict(reg, reg2, base)
        assert not ok, "a MISSING emitter image was reported bit-exact"
        assert why and "ABSENT" in why[0], why
        n += 2

        # and with the image PRESENT and matching, the same call passes
        with open(base + ".state_final.bin", "wb") as f:
            f.write(reg.mem.tobytes())
        ok2, n2, why2 = state_verdict(reg, reg2, base)
        assert ok2 and not why2, why2
        assert n2 == len(reg.touched)
        n += 1
        # one byte off, and it does not
        with open(base + ".state_final.bin", "r+b") as f:
            f.seek(len(reg.mem) // 2)
            f.write(bytes([reg.mem[len(reg.mem) // 2] ^ 0xFF]))
        ok3, _n3, why3 = state_verdict(reg, reg2, base)
        assert not ok3 and "differ in 1 bytes" in why3[0], why3
        n += 1
        # and a .txt/.seq disagreement is caught on its own
        reg2.mem[0] ^= 0xFF
        ok4, _n4, why4 = state_verdict(reg, reg2, base)
        assert not ok4 and why4[0].startswith(".txt and .seq"), why4
        n += 1
    return {"checks": n, "refused": refused, "red": red_caught,
            "ok": refused == 3 and red_caught == 1}


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
    ap.add_argument("--selftest-refusal", action="store_true",
                    help="SV1: only the running-channel MOVX/MVGO/MOVY "
                         "refusal selftest")
    ap.add_argument("--json", default=None)
    ap.add_argument("--caps", default="",
                    help="SR4: comma-separated SEQ capability names the "
                         "--gate stream is validated and executed at (e.g. "
                         "R1 for an r1 stream); default none = today's "
                         "rules (SEQ_ISA v2.3 B17.0)")
    a = ap.parse_args()
    caps = frozenset(c.strip() for c in a.caps.split(",") if c.strip())
    if a.selftest:
        _selftest()
    if a.selftest_refusal:
        _selftest_refusal()
    if a.disasm:
        recs = SF.unpack_stream(open(a.disasm + ".seq", "rb").read())
        print(SF.disasm_stream(recs, limit=a.limit))
    if a.gate:
        ok, rep = gate(a.gate, base=a.base, caps=caps)
        if a.json:
            with open(a.json, "w") as f:
                json.dump({k: v for k, v in rep.items() if k != "meta"}, f,
                          indent=1, default=str)
        print("SEQ GATE: " + ("PASS" if ok else "FAIL"))
        if not ok:
            raise SystemExit(1)


# ======================================================================
# SEQ_ISA B17.3 (R3): the MOVX BROADCAST -- Task R3-3 of the R3 campaign
# (docs/superpowers/plans/2026-09-29-r3-broadcast.md).  Everything R3 adds to
# the model lives HERE, after every line other documents cite, so no citation
# moves (the SR14 §7 zero-drift rule, R3-2's layout): SeqExec reaches it
# through two rewritten lines in _movx and one in __init__ (self.xptr).
# Names resolve at call time, so defining them after their callers is
# ordinary Python.  The validator's side is R3-2's (ref/seq_format.py's R3
# block: MOVX_BCAST, MOVX_BCAST_CAPS, validate()'s channel clause and
# validate_stream()'s record-order running walk).
# ======================================================================
def _movx_r3(ex, r):
    """SeqExec._movx's R3 hook (called first, before the unicast body).

    A BROADCAST (flags[7:4] = SF.MOVX_BCAST) is executed whole by
    _movx_bcast and returns True (the caller returns).  A unicast MOVX sets
    its channel's XPTR to 0 -- the X_XPTR state that precedes its burst
    (rtl/seq_movers.sv:904-905) -- and returns False, so the unicast body
    runs exactly as before; nothing else about a unicast changes.
    `ex.xptr` holds only the channels a unicast of THIS stream zeroed; an
    absent channel keeps whatever the host left (B17.3 XPTR)."""
    if r.chan == SF.MOVX_BCAST:
        _movx_bcast(ex, r)
        return True
    ex.xptr[r.chan] = 0
    return False


def _movx_bcast(ex, r):
    """B17.3: one scratch read, the same x written into the XWIN of channels
    0..3 at the ONE start word (so the same bank on all four).

    * Admission mirrors the validator's: MOVX_BCAST_CAPS ({R1,R2,R3}, names
      checked by hwmap) must be within ex.caps -- refused by
      SeqValidationError naming every missing capability, as
      seq_format._movx_bcast_admitted does.  run() has already validated the
      record at ex.caps; this is the model's own line for a direct call.
    * The running rule PER DESTINATION (B17.2 applied to each channel): the
      broadcast's word range [w0, w0 + ceil(len/4)) is checked against EVERY
      channel's pending x range before ANY write, and an overlap raises
      RunningChannelError naming that channel (explicit, so it survives
      `python -O`; an empty range counts as overlapping, _overlap).  This is
      the check a hazard carried round a JMP back-edge meets, which
      validate_stream's record-order walk cannot see.
    * XWinMem.write per channel records all four writes (a MVGO at that start
      byte reads the vector on any of the four; a later write over part of
      it kills it on that channel only).
    * XPTR: unchanged on all four (the push carries its word index).
    * Nothing is priced here (the cost model is R3-4's); the stats count ONE
      MOVX (run() does), as the BM1 counters do (B17.3 COUNTERS).
    The bank rule (the pass forces the four consumers' XBANK to agree) needs
    no model state: the record names one window for all four, and a MVGO
    whose XBANK names another window reads THAT window under XWinMem's
    strict-read rule (UnwrittenReadError when nothing intact starts there)."""
    miss = sorted(SF.MOVX_BCAST_CAPS - ex.caps)
    if miss:
        raise SF.SeqValidationError(
            f"broadcast MOVX (channel field {r.chan:#x}, B17.3) needs "
            f"capabilities {', '.join(sorted(SF.MOVX_BCAST_CAPS))}; the "
            f"model's caps {{{', '.join(sorted(ex.caps))}}} lack "
            f"{', '.join(miss)}")
    n = r.len_or_addr_hi
    w0 = r.target & SF.MOVX_WORD_MASK
    w1 = w0 + SF.movx_words(n)
    for c in range(4):
        p = ex.running.get(c)
        if p is not None and _overlap(w0, w1, p[0], p[1]):
            raise RunningChannelError(
                f"broadcast MOVX writes XWIN words [{w0}, {w1}) on every "
                f"channel while a NO-WAIT MVGO on mv{c} still reads words "
                f"[{p[0]}, {p[1]}) — every destination's bank must be free; "
                f"the stream needs a FENCE covering mv{c} first (B17.3)")
    v = ex.M.mem[r.addr_lo:r.addr_lo + n]          # ONE scratch read
    assert np.all(v >= -128) and np.all(v <= 127), \
        "MOVX source is not int8-packed"
    for c in range(4):
        ex.xwin.write(c, w0, v)



if __name__ == "__main__":
    main()
