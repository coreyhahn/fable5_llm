#!/usr/bin/env python3
"""sr13a_cov.py — Task SR13a: the SYNTHETIC R2 coverage artifacts for the
chip TB (the SR12 review's binding coverage list, items (2)-(4)).

    sr13a_cov.py <kind> <stem> [--seed N]

    kind   xbank    (2) XBANK end to end at ng 32 AND ng 48, every channel:
                        bank 0 and bank 1 hold DIFFERENT x (bank 1 loaded
                        first), a bank-1 MVGO, a bank-0 MVGO, and an
                        XBANK|RBANK MVGO read back from row 2048.  ng 48 fills
                        bank 1 to XWIN word 3072 exactly.
           rbank    (3) RBANK at ng 64 (K 8192) and ng 96 (K 12288), every
                        channel: bank 0 = W.xA, bank 1 = W.xB at the full
                        2048 rows, both halves drained, a middle slice of
                        bank 1, a MOVY ending at row 4096, a pairs32 MOVY,
                        and a partial (512-row) RBANK run.
           overlap  (4) the overlap pattern, on (ch0 main, ch1 other, ng 32)
                        and (ch2 main, ch3 other, ng 48): a bank-1 MOVX while
                        a NO-WAIT bank-0 MVGO runs, a MOVY from row 2048
                        drained while that MVGO rewrites RES bank 0, a MASKED
                        FENCE that leaves the other channel running, a bank-0
                        MOVX while a no-wait XBANK|RBANK MVGO runs, a MOVY of
                        RES bank 0 while that one writes bank 1, and a final
                        bank-0 MVGO that proves the rewritten x landed.

           R3-9a (the R3 campaign, Task R3-9a) adds the MOVX BROADCAST kinds
           (SEQ_ISA v2.3 B17.3; run them with --caps R1,R2,R3):
           bcast          broadcasts at ng 32 / 48 into BOTH banks and at ng
                          64 / 96 into bank 0, then MVGOs on all four
                          channels; after a broadcast a UNICAST MOVX of the
                          same length to ONE channel over the same window
                          (ng 32 ch2, ng 48 ch3, ng 96 ch1): that channel
                          computes on the unicast's x, the other three on
                          the broadcast's (and the same-length pair is the
                          one-window measurement).
           bcast_overlap  a bank-1 broadcast while NO-WAIT bank-0 MVGOs run
                          on ALL FOUR channels (2048 rows each), then a
                          same-length unicast into ch0's bank 1 under the
                          same load, a FENCE, the bank-0 results and the
                          XBANK results.
           bcast_bp       the lockstep back-pressure case: a 3072-word
                          broadcast (ng 96), run by the chip TB with
                          +xp_hold on channel 2 (a same-length unicast to
                          ch0 first: the one-window pair).
           bcast_ragged   ragged broadcasts: 1021 elements at word 1024
                          (right after bank 0's vector; the last word holds
                          one byte) and 1019 at the ODD word 1281 (ending at
                          word 1535, right before bank 1's vector), a
                          zero-length broadcast, a same-length unicast;
                          both neighbouring vectors must be intact.
           bcast_late     the BINDING edges R3-5 found never bind on the
                          real streams: a LATE READER (a long NO-WAIT XBANK
                          MVGO on ch3, 2048 rows) holds bank 1 while ch0..2
                          finish; the broadcast into bank 1 (ch0's natural
                          bank, FORCED on ch3) must wait for it (FENCE mask
                          ch3), the consumers on all four read the forced
                          bank, ch3's bank 0 stays intact.
           bcast_late_mut (needs --from <bcast_late stem>) THE LATE-READER
                          MUTANT: the same stream with that FENCE's mask
                          moved to ch0 (idle), paired with the CORRECT
                          stream's golden; the validator and the model must
                          REFUSE it, and the chip TB must FAIL it.

    stem   the artifact prefix, e.g. tb/scripts/w9/sr13a_cov_xbank (the
           chip TB's +seq / +base stems: <stem>.e4.seq etc. and <stem>).

    --caps the capability set the stream is VALIDATED and executed at (R3-9a
           flag, default R1,R2 = every earlier invocation unchanged); it is
           also REFUSED at each smaller set of the chain {R1,R2,R3} > {R1,R2}
           > {R1} > {} (default: {R1} and {}, as before).

Writes, beside <stem>:  <stem>.weights.json, <stem>_w<wid>.bin (W4 g128,
ref/w4a8_ref.pack_ddr_rows), <stem>.state.bin (64 zero bytes: the TB opens
it, the stream issues no SLD/SST so the window stays closed), and the
stream <stem>.e4.seq / .e4.seqdata.bin / .e4.seq.json.  The golden and the
per-channel region files are then built by the campaign's own generator,
`tb/scripts/gen_seq_chip_vectors.py <stem>.e4 --base <stem> --caps R1,R2`,
which replays the stream through ref/seq_model.py (SR11a's R2 model: XWinMem,
ResMem, running ranges, unwritten-read refusals) against the packed images.

This script ALSO checks, before writing anything it reports as done:
  * the stream validates at caps {R1,R2} with the 9B SHAPE layout stated
    (so the ng envelope is on), and is REFUSED at {R1} and at {} (it needs
    R2; the first refusal is printed);
  * ref/seq_model.py runs it to HALT at {R1,R2} against the files just
    written (no RunningChannelError, no UnwrittenReadError), and each
    MOVY'd block equals the value this script computed independently from
    the in-memory w4/m/x (matvec_y32 + the MOVY shift/clip) — so the
    golden's bank semantics are pinned by a second, direct computation;
  * NON-VACUITY: for every MOVY it prints how many of its words would
    differ if the RTL IGNORED the bank fields (x read from bank 0 instead
    of 1, a RES row read from the other half; a sequential approximation
    of the SR12 mutant).  A block a bank-blind RTL would still get right is
    listed with 0 -- it is vacuous ALONE; the claim is that every case
    carries at least one failing block (the mutant chip run is the proof).

Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh with FABLE5_MODEL=9b
FABLE5_RS_F=7 (the model's import-time operating point).
"""
import argparse
import hashlib
import json
import os
import sys

import numpy as np

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "..", ".."))
for p in (os.path.join(ROOT, "ref"), os.path.join(ROOT, "sw")):
    if p not in sys.path:
        sys.path.insert(0, p)

import hwmap as HW                                            # noqa: E402
import seq_format as SF                                       # noqa: E402
import seq_model as SM                                        # noqa: E402
import w4a8_ref as WR                                         # noqa: E402

NCH = 4
CAPS = frozenset({"R1", "R2"})
SCRATCH = 65536
I64 = np.int64


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class Build(object):
    def __init__(self, rng):
        self.rng = rng
        self.recs = []
        self.blob = bytearray()
        self.wid = {}            # wid -> dict(K, nrows, w4, m, sh, ...)
        self.plan = None
        self.xwin = {c: np.zeros(SF.XWIN_WORDS * 4, dtype=I64)
                     for c in range(NCH)}          # the RTL's x_mem, direct
        self.res = {c: np.zeros(SF.RES_ROWS, dtype=I64) for c in range(NCH)}
        self.mem = np.zeros(SCRATCH, dtype=I64)    # the scratch, direct
        self.movys = []          # (scratch addr, nwords, blind value, what)
        self.alt_res = {c: np.zeros(SF.RES_ROWS, dtype=I64)
                        for c in range(NCH)}       # a bank-BLIND RTL's RES
        self.alt_xwin = {c: np.zeros(SF.XWIN_WORDS * 4, dtype=I64)
                         for c in range(NCH)}      # a bank-BLIND RTL's x_mem
        # R3-9a: a second alternative world, the mutant "the broadcast
        # writes channel 0 only" (tracked only by the broadcast kinds)
        self.track2 = False
        self.alt2_xwin = {c: np.zeros(SF.XWIN_WORDS * 4, dtype=I64)
                          for c in range(NCH)}
        self.alt2_res = {c: np.zeros(SF.RES_ROWS, dtype=I64)
                         for c in range(NCH)}
        self.movys2 = []         # (scratch addr, nwords, ch0-only value)
        self.bcasts = []         # (record index, start word, length)
        self.movxs = []          # unicast: (record index, chan, word, length)

    # ---------------------------------------------------------- weights
    def add_weight(self, wid, K, nrows):
        W = self.rng.standard_normal((nrows, K)).astype(np.float64)
        w4, m, e, sh0 = WR.quantize_weights(W, g=128)
        # quantize_weights' worst-case shift: K 4096 -> 7 and K 12288 -> 9,
        # the values tb/scripts/w9's 9B manifests carry
        sh = sh0
        img, stride = WR.pack_ddr_rows(w4, m, g=128)
        self.wid[wid] = dict(K=K, nrows=nrows, w4=w4, m=m, e=e, sh=sh,
                             img=img, stride=stride, ng=K // 128)

    def rows_of(self, wid, chan):
        """(global r0, rows) channel `chan` holds of wid (contig split)."""
        n = self.wid[wid]["nrows"]
        for (i, r0, k, _off) in SF.weight_pieces_at(n, NCH, SF.LAYOUT_CONTIG,
                                                    SF.CHUNK_ROWS,
                                                    repack=True):
            if i == chan:
                return r0, k
        raise AssertionError((wid, chan))

    # ---------------------------------------------------------- records
    def ldc_x(self, dst, K):
        """LDC K random int8-range words into scratch[dst:dst+K]."""
        x = self.rng.integers(-128, 128, size=K).astype(np.int16)
        off = len(self.blob)
        self.blob += x.astype("<i2").tobytes()
        a = SF.SEQ_DATA_BASE + off
        self.recs.append(SF.Rec(SF.EXT_LDC, target=dst, imm32=K,
                                addr_lo=a & 0xFFFFFFFF,
                                len_or_addr_hi=a >> 32))
        self.mem[dst:dst + K] = x
        return x

    def movx(self, c, word, src, K):
        assert SF.movx_words(K) * 4 == K
        self.recs.append(SF.Rec(SF.OP_MOVX, flags=c << SF.CHAN_SHIFT,
                                target=word, addr_lo=src, len_or_addr_hi=K))
        self.xwin[c][4 * word:4 * word + K] = self.mem[src:src + K]
        # a bank-blind RTL (the SR12 mutant) writes every MOVX at word 0
        self.alt_xwin[c][0:K] = self.mem[src:src + K]
        if self.track2:
            self.alt2_xwin[c][4 * word:4 * word + K] = self.mem[src:src + K]
            self.movxs.append((len(self.recs) - 1, c, word, K))

    def mvgo(self, c, wid, row0, nrows, xb, rb, nowait=False):
        p = self.wid[wid]
        cr0, crows = self.rows_of(wid, c)
        assert 0 <= row0 and row0 + nrows <= crows
        base = self.plan[wid]["base"][c]
        wbase = base + row0 * p["stride"]
        beats = nrows * p["stride"] // 64
        shape = HW.shape_word(nrows, p["sh"], p["ng"])
        shape |= (SF.SHAPE_XBANK if xb else 0) | (SF.SHAPE_RBANK if rb else 0)
        self.recs.append(SF.Rec(SF.OP_MVGO, flags=c << SF.CHAN_SHIFT,
                                target=(SF.MVGO_NOWAIT if nowait else 0),
                                imm32=shape, addr_lo=wbase & 0xFFFFFFFF,
                                len_or_addr_hi=(beats << 8) | (wbase >> 32)))
        K = p["K"]
        g0 = cr0 + row0
        w4, m = p["w4"][g0:g0 + nrows], p["m"][g0:g0 + nrows]
        x = self.xwin[c][4 * SF.XBANK_WORD * xb:][:K]
        y = WR.matvec_y32(w4, m, p["sh"], x.astype(np.int8), g=128)
        self.res[c][SF.RBANK_ROW * rb:SF.RBANK_ROW * rb + nrows] = y
        xa = self.alt_xwin[c][:K]
        ya = WR.matvec_y32(w4, m, p["sh"], xa.astype(np.int8), g=128)
        self.alt_res[c][0:nrows] = ya
        if self.track2:
            x2 = self.alt2_xwin[c][4 * SF.XBANK_WORD * xb:][:K]
            y2 = WR.matvec_y32(w4, m, p["sh"], x2.astype(np.int8), g=128)
            self.alt2_res[c][SF.RBANK_ROW * rb:SF.RBANK_ROW * rb + nrows] = y2
        return y

    def movy(self, c, row0, n, dst, what, pairs=False):
        y = self.res[c][row0:row0 + n]
        mx = int(np.abs(y).max()) if n else 0
        sh = 0 if pairs else max(0, mx.bit_length() - 14)
        flags = 0 if pairs else SF.MOVY_MODE_BIT
        self.recs.append(SF.Rec(SF.OP_MOVY, flags=flags,
                                target=(row0 << 4) | c, imm32=sh,
                                addr_lo=dst, len_or_addr_hi=n))

        def xform(v):
            v = SM.rs_s(v, sh)
            if pairs:
                v = np.clip(v, -(1 << 31), (1 << 31) - 1).astype(I64)
                out = np.empty(2 * n, dtype=I64)
                u = v & 0xFFFFFFFF
                lo, hi = u & 0xFFFF, (u >> 16) & 0xFFFF
                out[0::2] = np.where(lo >= 32768, lo - 65536, lo)
                out[1::2] = np.where(hi >= 32768, hi - 65536, hi)
                return out
            return SM.clip16(v)
        good = xform(y)
        # the bank-blind RTL reads its row from RES row 0.. whatever the
        # start row, and its RES holds only the bank-blind results
        blind = xform(self.alt_res[c][0:n])
        nw = len(good)
        self.mem[dst:dst + nw] = good
        self.movys.append((dst, nw, blind, what))
        if self.track2:
            self.movys2.append((dst, nw, xform(self.alt2_res[c][row0:row0 + n])))

    # ---------------------------------------------------------- R3-9a
    def _xw(self, arr, word, v):
        """XWinMem.write's image: v at `word`, the ragged tail zero-padded."""
        lo = 4 * word
        arr[lo:lo + len(v)] = v
        arr[lo + len(v):4 * (word + SF.movx_words(len(v)))] = 0

    def bcast(self, word, src, K):
        """B17.3: ONE record; the same x into all four channels' XWIN."""
        self.recs.append(SF.Rec(SF.OP_MOVX,
                                flags=SF.MOVX_BCAST << SF.CHAN_SHIFT,
                                target=word, addr_lo=src, len_or_addr_hi=K))
        v = self.mem[src:src + K].copy()
        for c in range(NCH):
            self._xw(self.xwin[c], word, v)
            self.alt_xwin[c][0:K] = v
            if c == 0:                     # the ch0-only mutant's world
                self._xw(self.alt2_xwin[c], word, v)
        self.bcasts.append((len(self.recs) - 1, word, K))

    def movxr(self, c, word, src, K):
        """A unicast MOVX of any length (the ragged tail zero-padded)."""
        self.recs.append(SF.Rec(SF.OP_MOVX, flags=c << SF.CHAN_SHIFT,
                                target=word, addr_lo=src, len_or_addr_hi=K))
        v = self.mem[src:src + K].copy()
        self._xw(self.xwin[c], word, v)
        self.alt_xwin[c][0:K] = v
        self._xw(self.alt2_xwin[c], word, v)
        self.movxs.append((len(self.recs) - 1, c, word, K))

    def fence(self, mask=0):
        self.recs.append(SF.Rec(SF.OP_FENCE, target=mask))

    def halt(self):
        self.recs.append(SF.Rec(SF.OP_HALT))


# ---------------------------------------------------------------- kinds
def kind_xbank(b):
    b.add_weight(0, 4096, 4 * 512)          # ng 32
    b.add_weight(1, 6144, 4 * 512)          # ng 48
    return [(0, 0), (1, 1), (2, 1), (3, 0)]  # (chan, wid)


def body_xbank(b, plan):
    y0 = 32768
    for c, wid in plan:
        K = b.wid[wid]["K"]
        ng = b.wid[wid]["ng"]
        xa, xb = 0, 12288                   # scratch sources (re-loaded)
        b.ldc_x(xa, K)
        b.ldc_x(xb, K)
        # bank 1 FIRST, then bank 0: a bank-blind RTL (every MOVX at word
        # 0) is then left holding xA, so the XBANK reads below would see
        # the wrong x -- the bank-1 checks are the non-vacuous ones
        b.movx(c, SF.XBANK_WORD, xb, K)     # bank 1 = xB (ng 48: to 3072)
        b.movx(c, 0, xa, K)                 # bank 0 = xA, bank 1 intact
        n = 512
        b.mvgo(c, wid, 0, n, xb=1, rb=0)    # XBANK: y = W.xB
        b.movy(c, 0, n, y0, f"ch{c} ng{ng} XBANK rows 0..{n} (xB, after the bank-0 MOVX)")
        y0 += n
        b.mvgo(c, wid, 0, n, xb=0, rb=0)    # bank 0 intact: y = W.xA
        b.movy(c, 0, n, y0, f"ch{c} ng{ng} bank-0 MVGO (xA)")
        y0 += n
        b.mvgo(c, wid, 0, 256, xb=1, rb=1)  # XBANK|RBANK: rows 2048..
        b.movy(c, SF.RBANK_ROW, 256, y0,
               f"ch{c} ng{ng} XBANK|RBANK rows 2048..2304")
        y0 += 256
    b.halt()


def kind_rbank(b):
    b.add_weight(0, 8192, 4 * 2048)         # ng 64
    b.add_weight(1, 12288, 4 * 2048)        # ng 96
    return [(0, 0), (1, 1), (2, 0), (3, 1)]


def body_rbank(b, plan):
    y0 = 24576
    for c, wid in plan:
        K = b.wid[wid]["K"]
        ng = b.wid[wid]["ng"]
        xa, xb = 0, 12288
        b.ldc_x(xa, K)
        b.ldc_x(xb, K)
        b.movx(c, 0, xa, K)
        b.mvgo(c, wid, 0, 2048, xb=0, rb=0)       # RES 0..2047 = W.xA
        b.movx(c, 0, xb, K)
        b.mvgo(c, wid, 0, 2048, xb=0, rb=1)       # RES 2048..4095 = W.xB
        if c < 2:
            b.movy(c, 0, 2048, y0, f"ch{c} ng{ng} bank 0 (2048 rows)")
            y0 += 2048
            b.movy(c, SF.RBANK_ROW, 2048, y0,
                   f"ch{c} ng{ng} RBANK bank 1 (2048 rows, ends at 4096)")
            y0 += 2048
        else:
            b.movy(c, 3000, 100, y0, f"ch{c} ng{ng} RBANK rows 3000..3100")
            y0 += 100
            b.movy(c, 4000, 96, y0, f"ch{c} ng{ng} RBANK rows 4000..4096")
            y0 += 96
            b.movy(c, 2048, 64, y0, f"ch{c} ng{ng} RBANK rows 2048.. pairs32",
                   pairs=True)
            y0 += 128
            b.movy(c, 1000, 48, y0, f"ch{c} ng{ng} bank-0 rows 1000..1048")
            y0 += 48
            # a partial RBANK run: 512 rows at 2048 over the old bank 1
            b.mvgo(c, wid, 512, 512, xb=0, rb=1)  # rows 512.. of the piece
            b.movy(c, 2048, 512, y0, f"ch{c} ng{ng} RBANK 512-row run")
            y0 += 512
    assert y0 <= SCRATCH, y0
    b.halt()


def kind_overlap(b):
    b.add_weight(0, 4096, 4 * 512)          # ng 32
    b.add_weight(1, 6144, 4 * 512)          # ng 48
    return [(0, 1, 0), (2, 3, 1)]           # (main, other, wid)


def body_overlap(b, plan):
    y0 = 32768
    n = 512
    for (c, o, wid) in plan:
        K = b.wid[wid]["K"]
        ng = b.wid[wid]["ng"]
        XA, XB, XC, XD = 0, 6144, 12288, 18432
        for s in (XA, XB, XC, XD):
            b.ldc_x(s, K)
        b.movx(c, 0, XA, K)
        b.mvgo(c, wid, 0, n, xb=0, rb=1)                 # RES bank 1 = W.xA
        b.movx(c, 0, XB, K)                              # rewrite XWIN bank 0
        b.mvgo(c, wid, 0, n, xb=0, rb=0, nowait=True)    # runs: x0, RES 0..
        b.movx(c, SF.XBANK_WORD, XC, K)                  # bank-1 MOVX, running
        b.movy(c, SF.RBANK_ROW, n, y0,                   # drain bank 1 while
               f"ch{c} ng{ng} row 2048 drained during a bank-0 run")
        y0 += n                                          # bank 0 is rewritten
        b.movx(o, 0, XD, K)
        b.mvgo(o, wid, 0, n, xb=0, rb=0, nowait=True)    # the other channel
        b.fence(1 << c)                                  # MASKED: o runs on
        b.movy(c, 0, n, y0, f"ch{c} ng{ng} bank 0 after the masked FENCE")
        y0 += n
        b.mvgo(c, wid, 0, n, xb=1, rb=1, nowait=True)    # x bank 1, RES 2048..
        b.movx(c, 0, XA, K)                              # bank-0 MOVX, running
        b.movy(c, 0, n, y0,                              # RES bank 0 while the
               f"ch{c} ng{ng} bank 0 read during an RBANK run")
        y0 += n                                          # run writes bank 1
        b.fence((1 << c) | (1 << o))
        b.movy(c, SF.RBANK_ROW, n, y0, f"ch{c} ng{ng} XBANK|RBANK result")
        y0 += n
        b.movy(o, 0, n, y0, f"ch{o} ng{ng} the other channel's run")
        y0 += n
        b.mvgo(c, wid, 0, n, xb=0, rb=0)                 # the rewritten x0
        b.movy(c, 0, n, y0, f"ch{c} ng{ng} bank 0 = the MOVX made mid-run")
        y0 += n
    assert y0 <= SCRATCH, y0
    b.halt()


# ---------------------------------------------------------------- R3-9a
# The MOVX BROADCAST kinds (B17.3).  Every broadcast is ONE record with
# flags[7:4] = 0xF; MVGO / MOVY stay per channel.  Each kind turns on the
# second alternative world (track2: "the broadcast writes channel 0 only").
XS = (0, 12288, 20480)      # the three x sources (K <= 12288 / 6144 / 12288)


def kind_bcast(b):
    b.track2 = True
    for wid, K in enumerate((4096, 6144, 8192, 12288)):   # ng 32/48/64/96
        b.add_weight(wid, K, 4 * 512)
    return None


def _mv4(b, wid, xb, rb, y0, tag, n=512):
    for c in range(NCH):
        b.mvgo(c, wid, 0, n, xb=xb, rb=rb)
        b.movy(c, SF.RBANK_ROW * rb, n, y0, f"ch{c} {tag}")
        y0 += n
    return y0


def body_bcast(b, _plan):
    y0 = 32768
    xa, xb, xc = XS
    # ng 32: bank 1 then bank 0, then a unicast over ch2's bank-0 window
    K = 4096
    b.ldc_x(xa, K); b.ldc_x(xb, K); b.ldc_x(xc, K)
    b.bcast(SF.XBANK_WORD, xb, K)
    b.bcast(0, xa, K)
    b.movx(2, 0, xc, K)                     # same length, same window
    y0 = _mv4(b, 0, 1, 0, y0, "ng32 XBANK: the bank-1 broadcast (xB)")
    y0 = _mv4(b, 0, 0, 0, y0, "ng32 bank 0: the broadcast xA; ch2 the unicast xC")
    # ng 48: bank 0 then bank 1 (to word 3072), a unicast over ch3's bank 1
    K = 6144
    b.ldc_x(xa, K); b.ldc_x(xb, K); b.ldc_x(xc, K)
    b.bcast(0, xa, K)
    b.bcast(SF.XBANK_WORD, xb, K)
    b.movx(3, SF.XBANK_WORD, xc, K)
    y0 = _mv4(b, 1, 0, 0, y0, "ng48 bank 0: the broadcast xA")
    y0 = _mv4(b, 1, 1, 1, y0, "ng48 XBANK|RBANK: xB; ch3 the unicast xC")
    # ng 64: bank 0 (2048 words)
    K = 8192
    b.ldc_x(xa, K)
    b.bcast(0, xa, K)
    y0 = _mv4(b, 2, 0, 0, y0, "ng64 bank 0: the broadcast")
    # ng 96: the whole XWIN (3072 words), then a unicast over ch1's
    K = 12288
    b.ldc_x(xa, K); b.ldc_x(xc, K)
    b.bcast(0, xa, K)
    b.movx(1, 0, xc, K)
    y0 = _mv4(b, 3, 0, 0, y0, "ng96 bank 0: the broadcast; ch1 the unicast")
    assert y0 <= SCRATCH, y0
    b.halt()


def kind_bcast_overlap(b):
    b.track2 = True
    b.add_weight(0, 6144, 4 * 2048)         # ng 48, 2048 rows per channel
    return None


def body_bcast_overlap(b, _plan):
    K, y0 = 6144, 32768
    xa, xb, xc = XS
    b.ldc_x(xa, K); b.ldc_x(xb, K); b.ldc_x(xc, K)
    b.bcast(0, xa, K)                                   # bank 0 = xA, all
    for c in range(NCH):                                # four NO-WAIT runs
        b.mvgo(c, 0, 0, 2048, xb=0, rb=0, nowait=True)
    b.bcast(SF.XBANK_WORD, xb, K)                       # bank 1 WHILE they run
    b.movx(0, SF.XBANK_WORD, xc, K)                     # same length, loaded
    b.fence(0)
    for c in range(NCH):
        b.movy(c, 0, 2048, y0, f"ch{c} the bank-0 run (xA)")
        y0 += 2048
    y0 = _mv4(b, 0, 1, 1, y0, "XBANK|RBANK: the mid-run broadcast xB; ch0 the unicast xC")
    assert y0 <= SCRATCH, y0
    b.halt()


def kind_bcast_bp(b):
    b.track2 = True
    b.add_weight(0, 12288, 4 * 512)         # ng 96
    return None


def body_bcast_bp(b, _plan):
    K, y0 = 12288, 32768
    xa, _xb, xc = XS
    b.ldc_x(xa, K); b.ldc_x(xc, K)
    b.movx(0, 0, xc, K)                     # the unicast of the same length
    b.bcast(0, xa, K)                       # +xp_hold stalls ch2 inside this
    y0 = _mv4(b, 0, 0, 0, y0, "ng96 the 3072-word broadcast")
    assert y0 <= SCRATCH, y0
    b.halt()


def kind_bcast_ragged(b):
    b.track2 = True
    b.add_weight(0, 4096, 4 * 512)          # ng 32
    return None


def body_bcast_ragged(b, _plan):
    K, y0 = 4096, 32768
    xa, xb, xc = XS
    b.ldc_x(xa, K); b.ldc_x(xb, K); b.ldc_x(xc, 2048)
    b.bcast(0, xa, K)                       # bank 0 = xA: words 0..1023
    b.bcast(SF.XBANK_WORD, xb, K)           # bank 1 = xB: words 1536..2559
    b.bcast(1024, xc, 1021)                 # 256 words, the last 1 byte
    b.bcast(1281, xc + 1, 1019)             # ODD start, 255 words to 1535
    b.bcast(1300, xc, 0)                    # zero length: no traffic
    b.movxr(1, 1024, xc, 1021)              # the same-length unicast
    y0 = _mv4(b, 0, 0, 0, y0, "bank 0 (xA) after the ragged broadcasts")
    y0 = _mv4(b, 0, 1, 1, y0, "bank 1 (xB) after the ragged broadcasts")
    assert y0 <= SCRATCH, y0
    b.halt()


def kind_bcast_late(b):
    b.track2 = True
    b.add_weight(0, 4096, 4 * 512)          # ng 32, the consumers
    b.add_weight(1, 6144, 4 * 2048)         # ng 48, ch3's long late reader
    return None


LATE_FENCE = 1 << 3                         # the late reader's FENCE (ch3)


def body_bcast_late(b, _plan):
    y0 = 32768
    xa, xb, xd = XS
    b.ldc_x(xa, 4096); b.ldc_x(xb, 4096); b.ldc_x(xd, 6144)
    b.bcast(0, xa, 4096)                    # bank 0 = xA on all four
    b.movx(3, SF.XBANK_WORD, xd, 6144)      # ch3's rotation is on bank 1
    b.mvgo(3, 1, 0, 2048, xb=1, rb=1, nowait=True)   # THE LATE READER
    for c in range(3):                      # ch0..2 finish long before it
        b.mvgo(c, 0, 0, 512, xb=0, rb=0)
        b.movy(c, 0, 512, y0, f"ch{c} bank 0 (xA) while ch3 reads bank 1")
        y0 += 512
    b.fence(LATE_FENCE)                     # the broadcast waits for ch3
    b.bcast(SF.XBANK_WORD, xb, 4096)        # bank 1: ch0's, FORCED on ch3
    b.movy(3, SF.RBANK_ROW, 2048, y0, "ch3 the late reader's result (xD)")
    y0 += 2048
    y0 = _mv4(b, 0, 1, 0, y0, "XBANK: the forced-bank consumers (xB)")
    b.mvgo(3, 0, 0, 512, xb=0, rb=0)        # ch3's bank 0 still holds xA
    b.movy(3, 0, 512, y0, "ch3 bank 0 intact (xA)")
    y0 += 512
    assert y0 <= SCRATCH, y0
    b.halt()


KINDS = {"xbank": (kind_xbank, body_xbank),
         "rbank": (kind_rbank, body_rbank),
         "overlap": (kind_overlap, body_overlap),
         "bcast": (kind_bcast, body_bcast),
         "bcast_overlap": (kind_bcast_overlap, body_bcast_overlap),
         "bcast_bp": (kind_bcast_bp, body_bcast_bp),
         "bcast_ragged": (kind_bcast_ragged, body_bcast_ragged),
         "bcast_late": (kind_bcast_late, body_bcast_late)}
SEEDS = {"xbank": 1301, "rbank": 1302, "overlap": 1303,
         "bcast": 1311, "bcast_overlap": 1312, "bcast_bp": 1313,
         "bcast_ragged": 1314, "bcast_late": 1315}
CAPS_CHAIN = ("R1", "R2", "R3")


def main():
    global CAPS
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("kind", choices=sorted(KINDS) + ["bcast_late_mut"])
    ap.add_argument("stem")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--caps", default="R1,R2")
    ap.add_argument("--from", dest="src", default=None)
    a = ap.parse_args()
    CAPS = frozenset(x for x in a.caps.split(",") if x)
    if a.kind == "bcast_late_mut":
        return late_mutant(a)
    if a.kind.startswith("bcast") and "R3" not in CAPS:
        raise SystemExit(f"{a.kind} needs --caps R1,R2,R3 (a broadcast is R3)")
    seed = SEEDS[a.kind] if a.seed is None else a.seed
    for f in (a.stem + ".e4.seq", a.stem + ".weights.json"):
        if os.path.exists(f):
            raise SystemExit(f"REFUSING: {f} exists (never overwrite)")
    print(f"=== sr13a_cov {a.kind} -> {a.stem}  seed {seed}  "
          f"FABLE5_MODEL={os.environ.get('FABLE5_MODEL')}")
    rng = np.random.default_rng(seed)
    b = Build(rng)
    kind, body = KINDS[a.kind]
    plan = kind(b)

    # ---- the manifest, the images, the plan (hwmap.plan_weights) ------
    d = os.path.dirname(os.path.abspath(a.stem))
    stem = os.path.basename(a.stem)
    man = {}
    for wid, p in sorted(b.wid.items()):
        fn = f"{stem}_w{wid}.bin"
        with open(os.path.join(d, fn), "wb") as f:
            f.write(p["img"])
        man[str(wid)] = {"file": fn, "nrows": p["nrows"], "k": p["K"],
                         "ng": p["ng"], "sh": p["sh"], "e": p["e"],
                         "nbeats": p["nrows"] * p["stride"] // 64,
                         "stride": p["stride"]}
    man["rs_f"] = 7
    man["emb_row_bytes"] = HW.EMB_ROW_BYTES_DEFAULT
    with open(a.stem + ".weights.json", "w") as f:
        json.dump(man, f, indent=1)
    with open(a.stem + ".state.bin", "wb") as f:
        f.write(bytes(64))
    wman, _meta = HW.load_weights_manifest(a.stem)

    def rows_of(wid, nrows):
        return SF.chan_rows(nrows, NCH, SF.LAYOUT_CONTIG, SF.CHUNK_ROWS)
    bases, top = HW.plan_weights(wman, wdir=d, nch=NCH, rows_of=rows_of)
    b.plan = {}
    for wid, p in b.wid.items():
        b.plan[wid] = {"base": list(bases[wid]), "nrows": p["nrows"],
                       "k": p["K"], "ng": p["ng"], "sh": p["sh"], "g": 128,
                       "stride": p["stride"],
                       "nbeats": p["nrows"] * p["stride"] // 64}
        print(f"  wid {wid}: K {p['K']} ng {p['ng']} sh {p['sh']} nrows "
              f"{p['nrows']} ({p['nrows'] // NCH}/chan) stride {p['stride']} "
              f"bases {[hex(x) for x in bases[wid]]}")
    print(f"  pack top per channel {[hex(t) for t in top]}")

    body(b, plan)
    recs = b.recs

    # ---- admission: valid at {R1,R2}, refused at {R1} and {} ----------
    SF.validate_stream(recs, shape_isa=HW.SHAPE_ISA, caps=CAPS)
    print(f"  VALID at caps {sorted(CAPS)} (shape_isa {HW.SHAPE_ISA})")
    top = max(i for i, x in enumerate(CAPS_CHAIN) if x in CAPS)
    for caps in [frozenset(CAPS_CHAIN[:i]) for i in range(top, -1, -1)]:
        try:
            SF.validate_stream(recs, shape_isa=HW.SHAPE_ISA, caps=caps)
            raise SystemExit(f"FAIL: the stream validates at {sorted(caps)} "
                             f"— it does not need {CAPS_CHAIN[top]}")
        except SF.SeqValidationError as e:
            print(f"  REFUSED at caps {sorted(caps)}: {str(e)[:150]}")

    # ---- write the stream ----------------------------------------------
    sp = a.stem + ".e4"
    stream = SF.pack_stream(recs)
    with open(sp + ".seq", "wb") as f:
        f.write(stream)
    with open(sp + ".seqdata.bin", "wb") as f:
        f.write(bytes(b.blob))
    hist = {}
    for r in recs:
        k = SF.OP_NAME.get(r.opcode, hex(r.opcode))
        hist[k] = hist.get(k, 0) + 1
    nbank = sum(1 for r in recs
                if (r.opcode == SF.OP_MOVX and r.target)
                or (r.opcode == SF.OP_MVGO and (r.imm32 >> 29))
                or (r.opcode == SF.OP_MOVY and (r.target >> 4)))
    meta = {"format": "FAB5SEQ", "format_version": 1, "profile": "sr13a_cov",
            "kind": a.kind, "seed": seed, "chan": 0, "nch": NCH,
            "chans": list(range(NCH)), "nrec": len(recs),
            "stream_bytes": len(stream),
            "stream_sha256": hashlib.sha256(stream).hexdigest(),
            "seqdata_bytes": len(b.blob),
            "seqdata_sha256": hashlib.sha256(bytes(b.blob)).hexdigest(),
            "seq_data_base": SF.SEQ_DATA_BASE,
            "seq_stream_base": SF.SEQ_STREAM_BASE, "emb_base": HW.EMB_BASE,
            "weights": {str(k): v for k, v in b.plan.items()},
            "staging_words": [], "shape_isa": HW.SHAPE_ISA,
            "seq_isa": "2.3", "caps": sorted(CAPS), "bank_fields": nbank,
            "opcode_histogram": hist,
            "weight_layout": {"nch": NCH, "chunk_rows": SF.CHUNK_ROWS,
                              "default": SF.LAYOUT_CONTIG,
                              "by_wid": {str(w): SF.LAYOUT_CONTIG
                                         for w in b.wid},
                              "ilv_wids": []},
            "weight_repack": True}
    with open(sp + ".seq.json", "w") as f:
        json.dump(meta, f, indent=1)
    print(f"  {len(recs)} records {hist}; {nbank} records carry a bank field")
    print(SF.disasm_stream(recs))

    # ---- the reference model runs it (the golden's executor) ----------
    W = SM.DDRWeights.from_files(a.stem, meta["weights"], meta)
    ex = SM.SeqExec(recs, bytes(b.blob), W, caps=CAPS).run(
        max_steps=10 * len(recs))
    print(f"  ref/seq_model at {sorted(CAPS)}: ran to HALT, stats "
          f"{ {k: v for k, v in ex.stats.items() if v} }, running at HALT "
          f"{sorted(ex.running)}")
    assert not ex.running, "a no-wait stream is still pending at HALT"
    mm = np.asarray(ex.M.mem[:SCRATCH], dtype=I64)
    bad = int(np.count_nonzero(mm != b.mem))
    print(f"  model scratch vs this script's direct computation: "
          f"{bad} of {SCRATCH} words differ")
    assert bad == 0, "the model and the direct computation disagree"

    # ---- non-vacuity -------------------------------------------------------
    tot = 0
    print("  NON-VACUITY (words a bank-BLIND RTL would get wrong, per MOVY):")
    for (dst, nw, blind, what) in b.movys:
        k = int(np.count_nonzero(b.mem[dst:dst + nw] != blind))
        tot += (k > 0)
        print(f"    [{dst:5d}+{nw:4d}] {k:5d} of {nw:4d} differ  {what}")
    print(f"  {tot} of {len(b.movys)} MOVY blocks would fail on a bank-blind "
          "RTL (a block equal under both is listed with 0)")
    if b.track2:
        r3_report(b)
    for f in (sp + ".seq", sp + ".seqdata.bin", sp + ".seq.json",
              a.stem + ".weights.json") + tuple(
                  os.path.join(d, f"{stem}_w{w}.bin") for w in sorted(b.wid)):
        print(f"  sha256 {sha(f)}  {os.path.relpath(f, ROOT)}")
    print(f"SR13A_COV {a.kind}: PASS")


def r3_report(b):
    """R3-9a: the broadcast kinds' extra report — the ch0-only mutant's
    non-vacuity per MOVY, and the MOVX records (broadcast / unicast, start
    word, length, x words) the chip TB's per-channel push count and the
    timeline's one-window pairs are read against."""
    tot = 0
    print("  NON-VACUITY (words a 'broadcast writes channel 0 only' RTL "
          "would get wrong, per MOVY):")
    for (dst, nw, alt) in b.movys2:
        k = int(np.count_nonzero(b.mem[dst:dst + nw] != alt))
        tot += (k > 0)
        print(f"    [{dst:5d}+{nw:4d}] {k:5d} of {nw:4d} differ")
    print(f"  {tot} of {len(b.movys2)} MOVY blocks would fail on a "
          "ch0-only broadcast RTL")
    nw = 0
    for (i, w, K) in b.bcasts:
        nw += SF.movx_words(K)
        print(f"  R3_MOVX pc {i} BCAST word {w} len {K} words {SF.movx_words(K)}")
    for (i, c, w, K) in b.movxs:
        print(f"  R3_MOVX pc {i} UNICAST ch{c} word {w} len {K} "
              f"words {SF.movx_words(K)}")
    print(f"  R3_BCAST_WORDS {len(b.bcasts)} broadcasts, {nw} x words pushed "
          "to each channel")


def late_mutant(a):
    """bcast_late_mut: THE LATE-READER MUTANT of a bcast_late stem.

    Copies the stem's stream with the late reader's FENCE (mask ch3, the
    only FENCE whose mask is LATE_FENCE, immediately before the bank-1
    broadcast) moved to ch0 (idle: a zero wait), so the broadcast no longer
    waits for ch3's running XBANK MVGO.  The validator (B17.3's per-
    destination running rule) and ref/seq_model (RunningChannelError) must
    REFUSE it; the stem is written with the ORIGINAL stream's golden (.e4.chip)
    so the chip TB judges the mutant against what the correct order computes
    — it must FAIL.  Base (weights, regions) = the source stem."""
    src = a.src
    if not src:
        raise SystemExit("bcast_late_mut needs --from <bcast_late stem>")
    for f in (a.stem + ".e4.seq", a.stem + ".e4.chip"):
        if os.path.exists(f):
            raise SystemExit(f"REFUSING: {f} exists (never overwrite)")
    recs = SF.unpack_stream(open(src + ".e4.seq", "rb").read())
    idx = [i for i, r in enumerate(recs) if r.opcode == SF.OP_FENCE
           and (r.target & 0xF) == LATE_FENCE]
    assert len(idx) == 1, idx
    i = idx[0]
    nx = recs[i + 1]
    assert nx.opcode == SF.OP_MOVX and nx.chan == SF.MOVX_BCAST \
        and (nx.target & SF.MOVX_WORD_MASK) == SF.XBANK_WORD, "not the late FENCE"
    print(f"=== bcast_late_mut {a.stem} from {src}: rec {i} FENCE mask "
          f"{recs[i].target & 0xF:#06b} -> {1:#06b} (before the bank-1 "
          f"broadcast, rec {i + 1})")
    recs[i] = SF.Rec(SF.OP_FENCE, target=(recs[i].target & ~0xF) | 1)
    try:
        SF.validate_stream(recs, shape_isa=HW.SHAPE_ISA, caps=CAPS)
        raise SystemExit("FAIL: the validator ADMITS the late-reader mutant")
    except SF.SeqValidationError as e:
        print(f"  REFUSED by the validator at {sorted(CAPS)}: {str(e)[:260]}")
    meta = json.load(open(src + ".e4.seq.json"))
    W = SM.DDRWeights.from_files(src, meta["weights"], meta)
    blob = open(src + ".e4.seqdata.bin", "rb").read()
    try:
        # SeqExec.run validates record by record (stateless), so the hazard
        # reaches the model's own per-destination running check
        SM.SeqExec(recs, blob, W, caps=CAPS).run(max_steps=10 * len(recs))
        raise SystemExit("FAIL: the model ran the late-reader mutant")
    except SM.RunningChannelError as e:
        print(f"  REFUSED by ref/seq_model: RunningChannelError: {str(e)[:220]}")
    stream = SF.pack_stream(recs)
    with open(a.stem + ".e4.seq", "wb") as f:
        f.write(stream)
    import shutil
    for ext in (".e4.seqdata.bin", ".e4.chip"):
        shutil.copyfile(src + ext, a.stem + ext)
    for f in (src + ".e4.seq", a.stem + ".e4.seq", a.stem + ".e4.seqdata.bin",
              src + ".e4.chip", a.stem + ".e4.chip"):
        print(f"  sha256 {sha(f)}  {os.path.relpath(f, ROOT)}")
    print("SR13A_COV bcast_late_mut: WRITTEN (the golden is the CORRECT "
          "stream's; the chip TB must FAIL it)")


if __name__ == "__main__":
    main()
