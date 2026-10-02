#!/usr/bin/env python3
"""seq_chat.py — TurnCompiler: chat streams spliced out of the gated .e.seq.

This is the phase-1 deliverable of docs/CHAT_SEQ_SPEC.md (FROZEN
2026-08-09).  It turns a chat turn into SEQ record images by CONCATENATING
BYTE SLICES of the committed, gated artifact
`tb/scripts/w4/model_v2_s1.e.seq` (60,495 records, sha256 a69864d2...).
Nothing is re-emitted: every record in every image is either a verbatim
template byte or one of the five whitelisted immediate holes.

    template slice        records            what it is
    ------------------------------------------------------------------
    T_PREAMBLE   [0,1524)      1,524   session-once: const LDCs, conv
                                       weights, dnz, L_LAYER, 6x TCNT=0
    T_SEED_TOK   1524              1   CSRWR 0x204C -> XRF[3]  (token id)
    T_SEED_POS   1525              1   CSRWR 0x2050 -> XRF[4]  (pos*1536,
                                       ABSOLUTE)
    T_BODY_FULL  [1526,16266) 14,740   EMB .. AMAXL (one forward step)
    T_BODY_LITE  [1526,15532) 14,006   the same body with the LM head +
                                       AMAXL cut (prefill-lite)
    T_TCNT       45751             1   CSRWR 0x2020 -> TCNT_SEQ
    T_POSADV     60492             1   XOP  XRF[4] += 1536 (loop only)
    T_JMP        60493             1   JMP  flags=1 (dec TCNT, loop)
    T_HALT       60494             1   HALT

All four step bodies in the committed stream are BYTE-IDENTICAL (verified
at load), which is what makes one body template complete.

ADDRESS SPACE.  Everything this module produces is in EMITTER address
space: LDC const blob at 0x8000_0000, embedding table at 0x6000_0000.
The host (sw/chat_seq.py) relocates with sw/seq_run.relocate() using the
meta this module exposes as `TurnCompiler.meta`.

-----------------------------------------------------------------------
API (the contract sw/chat_seq.py builds against)
-----------------------------------------------------------------------
    tc = TurnCompiler()                      # loads + verifies templates

    blob   = tc.blob()                       # const region + position pool
    sess   = tc.build_session()              # Image: preamble + TCNT + HALT
    lite   = tc.build_step(tok, pos, "lite") # Image: resident prefill image
    full   = tc.build_step(tok, pos, "full") # Image: resident decode image
    patch  = tc.patch_step(None, tok, pos)   # Patch: 48 B at offset 0
    turn   = tc.build_turn(prompt_ids, ntok, start_pos)   # single-stream

Every Image carries `.data` (bytes), `.nrec` (== the value SEQ_LEN must
be programmed with, also `.seq_len`), `.holes` (name -> byte offset of the
imm32 field inside `.data`) and `.entry` (0).

LAUNCH-PER-STEP (spec decision 4, the primary flow) uses exactly two
DDR-resident images — one lite, one full — built once per session and
re-launched per forward step after a 48-byte in-place patch:

    img = tc.build_step(0, 0, "full")        # upload once
    ...
    p = tc.patch_step(None, tok, pos)        # per launch
    dev.dma_write(img_ddr_addr + p.offset, p.data)   # 48 B
    seq_start()

The 48 bytes are the FIRST THREE RECORDS of every step image, in this
fixed order, so the patch is one contiguous 48-byte DMA at offset 0:

    byte  0..15   T_SEED_TOK   imm32 at +4   = token id        (XRF[3])
    byte 16..31   T_SEED_POS   imm32 at +4   = pos * 1536      (XRF[4])
    byte 32..47   T_TCNT       imm32 at +4   = TCNT_SEQ

The token seed is ALWAYS emitted (the committed stream skips it when the
prompt token happens to equal the previous argmax — that is an emitter
quirk, spec decision 5, and is deliberately NOT reproduced).  TCNT_SEQ is
set explicitly in EVERY image, including images with no JMP (=1), because
TCNT_SEQ==0 at a JMP wraps to 2^32-1 (spec hazard list).

-----------------------------------------------------------------------
POSITION BLOB
-----------------------------------------------------------------------
The RoPE tables are the only position-dependent data in a step body.  The
body reads them with six LDC records that carry XRF[4] indirection:

    LDC  DDR[0x800F3B00 + 0x100*j + XRF[4]] -> scratch[0x1000], 128 words

so the pool is 6 copies of concat(cos_q15, sin_q15) per position
(6 * 256 B = 1536 B/position) and XRF[4] = pos * 1536.

    blob = committed_seqdata[0 : 998144]        const region, unchanged
         + pos_pool(T_max)                      T_max * 1536 B

    T_max = 512  ->  786,432 B pool, 1,784,576 B total.

*** RANGE CONFLICT (raised to the integrator, see the module notes) ***
XRF entries are 18 bits and XRF[4] is read SIGN-EXTENDED
(rtl/seq_unit.sv:250 xrf_rd), so XRF[4] <= 131,071 and the XRF[4]
mechanism can only reach pos <= 85 (85*1536 = 130,560).  seq_unit
truncates a larger CSRWR silently (seq_unit.sv:841, no xrf_ovf) and
ref/seq_model.py does NOT model the sign extension, so the model would
happily "pass" where silicon reads the wrong RoPE table.  The compiler
therefore hard-refuses pos > 85 in the default `pos_mode="xrf"`.
`pos_mode="ldc"` is the documented escape hatch: XRF[4] stays 0 and the
six LDC addr_lo fields are patched per step instead (6 extra 4-byte holes
in the patch), which reaches the full T_max=512 the KV cache allows.
"""

import argparse
import hashlib
import json
import os
import struct
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import seq_format as SF                                        # noqa: E402
import layer_fixed as LF                                       # noqa: E402

# ======================================================================
# frozen constants (docs/CHAT_SEQ_SPEC.md)
# ======================================================================
REC = 16                                    # bytes per SEQ record

DEFAULT_PREFIX = os.path.join(_ROOT, "tb", "scripts", "w4", "model_v2_s1.e")
DEFAULT_BASE = os.path.join(_ROOT, "tb", "scripts", "w4", "model_v2_s1")

TEMPLATE_NREC = 60495
TEMPLATE_SHA256 = ("a69864d25b6b129a4d6c74b3c78dfcbedf1edce219d32cc05d05b"
                   "c54f444aaf1")
SEQDATA_SHA256 = ("13bc65821b18194b7672c366894b2c2cd4ad6e2e966f12738b6d2f"
                  "aeeafcb6fb")

# record-index boundaries of every template slice
R_PREAMBLE = (0, 1524)
R_SEED_TOK = 1524
R_SEED_POS = 1525
R_BODY_FULL = (1526, 16266)
R_BODY_LITE = (1526, 15532)
R_TCNT = 45751
R_POSADV = 60492
R_JMP = 60493
R_HALT = 60494

NREC_PREAMBLE = R_PREAMBLE[1] - R_PREAMBLE[0]           # 1524
NREC_BODY_FULL = R_BODY_FULL[1] - R_BODY_FULL[0]        # 14740
NREC_BODY_LITE = R_BODY_LITE[1] - R_BODY_LITE[0]        # 14006
LITE_SUFFIX_RECS = NREC_BODY_FULL - NREC_BODY_LITE      # 734 (LM head+AMAXL)

# constant blob geometry.
# CONST_BYTES stays PINNED: it is the byte length of the committed 0.8B const
# region, gated by TEMPLATE_SHA256, not a geometry expression.
#
# G2a: the other three ARE geometry and are derived.  POS_COPIES is the count
# of position-indexed LDC records in one body, which is one per FULL-ATTENTION
# layer — 6 at 0.8B/2B, 8 at 4B/9B — and POS_WORDS is one cos|sin table,
# 2*ROT int16.  Both evaluate to the frozen 6 / 128 at 0.8B and 2B, so no
# emitted byte and no committed offset moves; `sw/chat_seq.py:181-182` carries
# the host twin of the same two numbers.  `layer_fixed` already imports
# `layer_ref`, so this adds no new dependency.
CONST_BYTES = 998144                     # committed const region, unchanged
POS_BLOB_BASE = SF.SEQ_DATA_BASE + CONST_BYTES          # 0x800F3B00
POS_COPIES = sum(1 for _t in (LF.LR.CFG.get("layer_types") or [])
                 if _t == "full_attention")   # LDCs per body = GQA layers
POS_WORDS = 2 * LF.LR.ROT                # int16 per copy (cos ROT | sin ROT)
POS_COPY_BYTES = POS_WORDS * 2           # 256
POS_STRIDE = POS_COPIES * POS_COPY_BYTES  # 1536 B per position at 0.8B/2B
# T_MAX -- the deepest position this compiler will build a pool for, PER
# MODEL SELECTION (Task 15 fix round 3, review I-2).  4,096 is the S2/S3
# state-spill netlist's ceiling: its KV cache is `{kv, t[11:0]}` (spec A1.5,
# `docs/SEQ_ISA.md` B15) and `sw/hwmap.STATE_T_MAX` says 4096.  The FROZEN
# 0.8B/2B path is NOT on that netlist -- build_034/035 still address KV with
# `rtl/layer_chan.sv kv_waddr = tcnt[8:0]` -- so it keeps 512, its 786,432 B
# position pool and every data_base-relative image address it had at 4662b06.
# Fix round 2 raised it for ALL selections, growing that frozen pool 8x and
# moving a placement no board can validate; 4b has no netlist either way.
import model_select as _MS                                     # noqa: E402
T_MAX = 4096 if _MS.TAG == "9b" else 512   # 512 = kv_waddr = tcnt[8:0]

# XRF[4] is a SIGNED 18-bit register (seq_unit.sv xrf_rd) -> the largest
# position the XRF[4] cursor can address.
XRF_POS_MAX = ((1 << (SF.XRF_BITS - 1)) - 1) // POS_STRIDE      # 85

# byte offset (within a body template) of the addr_lo field of each of the
# six position-indexed LDC records; verified against the artifact at load.
POS_LDC_REC_OFFSETS = (2096, 4428, 6760, 9092, 11424, 13756)
POS_LDC_BYTE_OFFSETS = tuple(o * REC + 8 for o in POS_LDC_REC_OFFSETS)

# the 48-byte per-launch patch: three records at the head of every step
PATCH_BYTES = 3 * REC
KINDS = ("lite", "full")


class ChatSeqError(RuntimeError):
    """A template, hole or range invariant of CHAT_SEQ_SPEC.md was broken."""


# ======================================================================
# small containers
# ======================================================================
class Image(object):
    """One DDR-resident SEQ record image, in EMITTER address space.

    Attributes
    ----------
    name      : str            human tag ("session", "step.full", "turn")
    kind      : str            "session" | "step" | "turn"
    data      : bytes          the record image, ready for DMA
    nrec      : int            record count
    seq_len   : int            what SEQ_LEN must be programmed with (==nrec)
    entry     : int            record index the sequencer must start at (0)
    holes     : {name: byte offset of the imm32 field inside `data`}
    patch_off : int | None     byte offset of the per-launch patch window
    patch_len : int | None     its length (48) — step images only
    pos_ldc   : [byte offsets] addr_lo fields of the position LDCs (only
                               populated in pos_mode="ldc")
    blob_span : (lo, hi)       byte range of the const blob this image
                               reads, as offsets from SEQ_DATA_BASE
    counts    : {opcode name: n} record census (LDC/EMB are what the host
                               relocator rewrites)
    steps     : int            forward steps this image executes
    """

    __slots__ = ("name", "kind", "data", "nrec", "entry", "holes",
                 "patch_off", "patch_len", "pos_ldc", "blob_span", "counts",
                 "steps", "pos_mode")

    def __init__(self, name, kind, data, holes, steps, pos_mode,
                 patch_off=None, patch_len=None, pos_ldc=(), blob_span=None,
                 counts=None):
        if len(data) % REC:
            raise ChatSeqError(f"{name}: {len(data)} B is not a whole number "
                               f"of {REC}-byte records")
        self.name = name
        self.kind = kind
        self.data = bytes(data)
        self.nrec = len(data) // REC
        self.entry = 0
        self.holes = dict(holes)
        self.patch_off = patch_off
        self.patch_len = patch_len
        self.pos_ldc = tuple(pos_ldc)
        self.blob_span = blob_span
        self.counts = dict(counts or {})
        self.steps = int(steps)
        self.pos_mode = pos_mode

    @property
    def seq_len(self):
        """SEQ_LEN must equal the record count (spec hazard: else E_JMP/E_PC)."""
        return self.nrec

    @property
    def nbytes(self):
        return len(self.data)

    def records(self):
        """Decode to ref/seq_format.Rec objects (test/debug only)."""
        return SF.unpack_stream(self.data)

    def sha256(self):
        return hashlib.sha256(self.data).hexdigest()

    def __repr__(self):
        return (f"<Image {self.name} {self.nrec} recs / {len(self.data)} B, "
                f"{self.steps} step(s), holes={sorted(self.holes)}>")


class Patch(object):
    """The bytes a host writes into a resident image before a launch.

    `writes()` is the authoritative form: a list of (byte offset within the
    image, bytes) pairs.  For pos_mode="xrf" that is exactly one 48-byte
    write at offset 0.
    """

    __slots__ = ("offset", "data", "extra", "fields")

    def __init__(self, offset, data, extra=(), fields=None):
        self.offset = int(offset)
        self.data = bytes(data)
        self.extra = [(int(o), bytes(b)) for (o, b) in extra]
        self.fields = dict(fields or {})

    def writes(self):
        return [(self.offset, self.data)] + self.extra

    @property
    def nbytes(self):
        return len(self.data) + sum(len(b) for (_o, b) in self.extra)

    def apply(self, image):
        """Return a patched copy of `image` (bytes or Image)."""
        buf = bytearray(image.data if isinstance(image, Image) else image)
        for (o, b) in self.writes():
            if o + len(b) > len(buf):
                raise ChatSeqError(f"patch at {o}+{len(b)} runs past the "
                                   f"{len(buf)} B image")
            buf[o:o + len(b)] = b
        return bytes(buf)

    def __repr__(self):
        return (f"<Patch {self.nbytes} B at {self.offset} "
                f"({len(self.writes())} write(s)) {self.fields}>")


# ======================================================================
# helpers
# ======================================================================
def _u32(v):
    return struct.pack("<I", int(v) & 0xFFFFFFFF)


def _set_imm32(buf, rec_off, val):
    buf[rec_off + 4:rec_off + 8] = _u32(val)


def _set_addr_lo(buf, rec_off, val):
    buf[rec_off + 8:rec_off + 12] = _u32(val)


def _census(recs):
    out = {}
    for r in recs:
        n = SF.OP_NAME.get(r.opcode, f"0x{r.opcode:02x}")
        out[n] = out.get(n, 0) + 1
    return out


def _blob_span(recs):
    """(lo, hi) byte offsets from SEQ_DATA_BASE that these records LDC."""
    lo = hi = None
    for r in recs:
        if r.opcode != SF.EXT_LDC:
            continue
        a = ((int(r.len_or_addr_hi) << 32) | int(r.addr_lo)) - SF.SEQ_DATA_BASE
        b = a + 2 * int(r.imm32)
        lo = a if lo is None else min(lo, a)
        hi = b if hi is None else max(hi, b)
    return None if lo is None else (lo, hi)


# ======================================================================
# template loading + verification
# ======================================================================
class Templates(object):
    """The nine byte slices of the gated .e.seq, verified at load.

    Every slice is checked structurally (first/last record opcode and the
    exact CSR target / flags it must carry) so that a regenerated artifact
    which moved a record boundary FAILS LOUDLY here instead of producing a
    silently wrong stream.
    """

    def __init__(self, prefix=DEFAULT_PREFIX, verify_sha=True, shape_isa=None):
        self.prefix = prefix
        self.stream = open(prefix + ".seq", "rb").read()
        self.meta = json.load(open(prefix + ".seq.json"))
        self._stated_isa = shape_isa
        self.seqdata_path = prefix + ".seqdata.bin"
        self.stream_sha = hashlib.sha256(self.stream).hexdigest()
        if verify_sha and self.stream_sha != TEMPLATE_SHA256:
            raise ChatSeqError(
                f"{prefix}.seq sha256 {self.stream_sha[:16]} != the gated "
                f"{TEMPLATE_SHA256[:16]}: the template source changed, "
                f"re-run the phase-0 boundary analysis before trusting "
                f"docs/CHAT_SEQ_SPEC.md's record indices")
        if self.stream_sha != self.meta["stream_sha256"]:
            raise ChatSeqError(f"{prefix}.seq does not match its own .seq.json")
        # G3.4 fix round 2: the SHAPE LAYOUT of the artifact these
        # templates are sliced out of.  It is a property of the ARTIFACT,
        # not of any call site: this class splices records verbatim out of
        # a gated `.e.seq`, so the MVGO SHAPE words in them are whatever
        # that artifact was emitted for.  Today's gated template is a
        # frozen build_034/build_035 stream whose `ng` lives in bits [5:0]
        # (isa=1), so the key is absent and the envelope check stays OFF --
        # which is correct, and which the board-free gate proved by
        # failing when a first cut hard-coded isa=2 here.  A 9B artifact
        # whose meta declares `shape_isa` turns the check on with no edit.
        self.shape_isa = self.meta.get("shape_isa")
        # SR11a fix round 2 (docs/SEQ_ISA.md v2.3 B17.2): since SR11a an
        # UNSTATED layout refuses MVGO SHAPE bits 29/30 (bit 29 is w8 on
        # build_034/035, XBANK on build_041+), so a frozen isa=1 W8 artifact
        # — whose meta carries no key — validates only when the caller
        # STATES its layout (chat_seq --shape-isa; the device's on a board).
        # A stated layout that contradicts the artifact's own key is refused.
        if self._stated_isa is not None:
            if self.shape_isa is not None \
                    and int(self.shape_isa) != int(self._stated_isa):
                raise ChatSeqError(
                    f"{prefix}.seq.json declares shape_isa {self.shape_isa} "
                    f"but the caller stated {self._stated_isa}")
            self.shape_isa = int(self._stated_isa)
        self.recs = SF.unpack_stream(self.stream)
        if len(self.recs) != TEMPLATE_NREC:
            raise ChatSeqError(f"{prefix}.seq has {len(self.recs)} records, "
                               f"spec pins {TEMPLATE_NREC}")
        self._verify()

        b = self.stream
        self.preamble = b[R_PREAMBLE[0] * REC:R_PREAMBLE[1] * REC]
        self.seed_tok = b[R_SEED_TOK * REC:(R_SEED_TOK + 1) * REC]
        self.seed_pos = b[R_SEED_POS * REC:(R_SEED_POS + 1) * REC]
        self.body_full = b[R_BODY_FULL[0] * REC:R_BODY_FULL[1] * REC]
        self.body_lite = b[R_BODY_LITE[0] * REC:R_BODY_LITE[1] * REC]
        self.tcnt = b[R_TCNT * REC:(R_TCNT + 1) * REC]
        self.posadv = b[R_POSADV * REC:(R_POSADV + 1) * REC]
        self.jmp = b[R_JMP * REC:(R_JMP + 1) * REC]
        self.halt = b[R_HALT * REC:(R_HALT + 1) * REC]

    # ------------------------------------------------------------------
    def body(self, kind):
        if kind not in KINDS:
            raise ChatSeqError(f"body kind {kind!r} not in {KINDS}")
        return self.body_full if kind == "full" else self.body_lite

    def nrec_body(self, kind):
        return NREC_BODY_FULL if kind == "full" else NREC_BODY_LITE

    # ------------------------------------------------------------------
    def _verify(self):
        r = self.recs

        def need(cond, msg):
            if not cond:
                raise ChatSeqError("template check failed: " + msg)

        # --- preamble: session-once resets, ends on L_LAYER / L_TCNT ----
        need(r[0].opcode == SF.OP_CSRWR
             and r[0].target == SF.csr_layer(SF.LOFF_LAYER),
             f"rec 0 is {SF.disasm(r[0])}, expected CSRWR L_LAYER")
        need(r[R_PREAMBLE[1] - 1].opcode == SF.OP_CSRWR
             and r[R_PREAMBLE[1] - 1].target == SF.csr_layer(SF.LOFF_TCNT),
             f"rec {R_PREAMBLE[1] - 1} is {SF.disasm(r[R_PREAMBLE[1] - 1])}, "
             f"expected the preamble's last CSRWR L_TCNT")

        # --- the two seed records --------------------------------------
        need(r[R_SEED_TOK].opcode == SF.OP_CSRWR
             and r[R_SEED_TOK].target == SF.csr_seq_xrf(SF.XRF_TOK)
             and r[R_SEED_TOK].ind == SF.IND_NONE,
             f"rec {R_SEED_TOK} is {SF.disasm(r[R_SEED_TOK])}, expected "
             f"CSRWR XRF[3] (token seed)")
        need(r[R_SEED_POS].opcode == SF.OP_CSRWR
             and r[R_SEED_POS].target == SF.csr_seq_xrf(SF.XRF_POS)
             and r[R_SEED_POS].ind == SF.IND_NONE
             and r[R_SEED_POS].imm32 == 0,
             f"rec {R_SEED_POS} is {SF.disasm(r[R_SEED_POS])}, expected "
             f"CSRWR XRF[4] <= 0 (absolute position seed)")

        # --- body: EMB .. AMAXL, lite cut at a MOVX --------------------
        need(r[R_BODY_FULL[0]].opcode == SF.OP_EMB,
             f"rec {R_BODY_FULL[0]} is {SF.disasm(r[R_BODY_FULL[0]])}, "
             f"expected EMB (body head)")
        need(r[R_BODY_FULL[1] - 1].opcode == SF.OP_AMAXL,
             f"rec {R_BODY_FULL[1] - 1} is "
             f"{SF.disasm(r[R_BODY_FULL[1] - 1])}, expected AMAXL (body tail)")
        need(r[R_BODY_LITE[1] - 1].opcode == SF.OP_CMD,
             f"rec {R_BODY_LITE[1] - 1} is "
             f"{SF.disasm(r[R_BODY_LITE[1] - 1])}, expected CMD (lite tail)")
        need(r[R_BODY_LITE[1]].opcode == SF.OP_MOVX
             and r[R_BODY_LITE[1]].addr_lo == 0x800,
             f"rec {R_BODY_LITE[1]} is {SF.disasm(r[R_BODY_LITE[1]])}, "
             f"expected MOVX XWIN <= scratch[0x800] (LM-head suffix head)")

        # --- all four step bodies byte-identical (the whole premise) ----
        b0 = self.stream[R_BODY_FULL[0] * REC:R_BODY_FULL[1] * REC]
        for k, start in enumerate((16268, 31009, 45752)):
            other = self.stream[start * REC:(start + NREC_BODY_FULL) * REC]
            need(other == b0,
                 f"step body {k + 1} at rec {start} is NOT byte-identical to "
                 f"the template body at rec {R_BODY_FULL[0]}")

        # --- the loop/tail singles -------------------------------------
        need(r[R_TCNT].opcode == SF.OP_CSRWR
             and r[R_TCNT].target == SF.csr_seq(SF.SOFF_TCNT_SEQ),
             f"rec {R_TCNT} is {SF.disasm(r[R_TCNT])}, expected CSRWR "
             f"TCNT_SEQ")
        need(r[R_POSADV].opcode == SF.EXT_XOP
             and r[R_POSADV].target == SF.XRF_POS
             and r[R_POSADV].imm32 == SF.xop_imm(a=SF.XRF_POS,
                                                 s1=SF.XOP_POS,
                                                 simm=POS_STRIDE),
             f"rec {R_POSADV} is {SF.disasm(r[R_POSADV])}, expected "
             f"XOP XRF[4] += {POS_STRIDE}")
        need(r[R_JMP].opcode == SF.OP_JMP and (r[R_JMP].flags & SF.JMP_TCNT),
             f"rec {R_JMP} is {SF.disasm(r[R_JMP])}, expected JMP flags=1")
        need(r[R_HALT].opcode == SF.OP_HALT,
             f"rec {R_HALT} is {SF.disasm(r[R_HALT])}, expected HALT")

        # --- the six position-indexed LDCs, at the pinned offsets ------
        got = [(i - R_BODY_FULL[0], rr)
               for i, rr in enumerate(self.recs[R_BODY_FULL[0]:R_BODY_FULL[1]],
                                      R_BODY_FULL[0])
               if rr.opcode == SF.EXT_LDC and rr.ind != SF.IND_NONE]
        need(tuple(o for (o, _rr) in got) == POS_LDC_REC_OFFSETS,
             f"position-indexed LDCs sit at body offsets "
             f"{tuple(o for (o, _rr) in got)}, spec pins "
             f"{POS_LDC_REC_OFFSETS}")
        for j, (_o, rr) in enumerate(got):
            a = (int(rr.len_or_addr_hi) << 32) | int(rr.addr_lo)
            need(rr.ind == SF.IND_ADD and rr.xrf == SF.XRF_POS
                 and rr.imm32 == POS_WORDS
                 and a == POS_BLOB_BASE + j * POS_COPY_BYTES,
                 f"position LDC {j} is {SF.disasm(rr)}, expected "
                 f"LDC[{POS_BLOB_BASE + j * POS_COPY_BYTES:#x} + XRF[4]] "
                 f"{POS_WORDS} words")
        need(POS_LDC_REC_OFFSETS[-1] < NREC_BODY_LITE,
             "a position LDC falls outside the lite body")

        # --- meta sanity ------------------------------------------------
        need(int(self.meta["seq_data_base"]) == SF.SEQ_DATA_BASE,
             "meta seq_data_base is not the emitter's 0x8000_0000")


# ======================================================================
# the compiler
# ======================================================================
class TurnCompiler(object):
    """Compile chat turns into SEQ record images by splicing templates.

    Parameters
    ----------
    prefix   : template artifact prefix (default the gated model_v2_s1.e)
    t_max    : positions the session's RoPE pool covers (default 512)
    pos_mode : "xrf" (spec-frozen: XRF[4] = pos*1536, pos <= 85) or
               "ldc" (patch the six position LDC addresses instead, which
               reaches pos < t_max — see the module docstring's RANGE
               CONFLICT note; NOT part of the frozen spec)
    verify_sha : refuse a template artifact whose sha256 moved

    Notes
    -----
    * The compiler is PURE: it never touches the board, never reads the
      weight images, and produces bytes in emitter address space only.
    * `meta` is the committed .seq.json with `seqdata_bytes` corrected to
      this session's blob size — it is the real artifact metadata, NOT a
      fabrication, and is what sw/seq_run.plan_ddr()/relocate() consume.
    """

    def __init__(self, prefix=DEFAULT_PREFIX, t_max=T_MAX, pos_mode="xrf",
                 verify_sha=True, shape_isa=None):
        if pos_mode not in ("xrf", "ldc"):
            raise ChatSeqError(f"pos_mode {pos_mode!r} not in ('xrf','ldc')")
        if not (1 <= int(t_max) <= T_MAX):
            raise ChatSeqError(f"t_max {t_max} outside 1..{T_MAX} "
                               f"(KV depth, rtl/layer_chan.sv kv_waddr t[8:0])")
        # shape_isa: SR11a fix round 2 — see Templates.shape_isa
        self.T = Templates(prefix, verify_sha=verify_sha, shape_isa=shape_isa)
        self.t_max = int(t_max)
        self.pos_mode = pos_mode
        self._blob = None
        self.meta = dict(self.T.meta)

    # ------------------------------------------------------------------
    # position blob
    # ------------------------------------------------------------------
    @staticmethod
    def pos_pool(t_max=T_MAX):
        """The position pool: `t_max` x 6 copies of concat(cos_q15,sin_q15).

        Byte-identical (for the first 6 positions) to the tail of the
        committed model_v2_s1.e.seqdata.bin — that equality is gate A2.
        """
        out = np.empty((int(t_max), POS_COPIES, 2 * POS_WORDS // 2),
                       dtype="<i2")
        for p in range(int(t_max)):
            cos, sin = LF.rope_tables_q15(p)
            one = np.concatenate([cos, sin]).astype("<i2")
            if one.size != POS_WORDS:
                raise ChatSeqError(f"rope_tables_q15({p}) is {one.size} words, "
                                   f"the template LDC reads {POS_WORDS}")
            out[p, :, :] = one
        return out.tobytes()

    def const_region(self):
        """The committed const blob, [0, 998144) — unchanged, verbatim."""
        raw = open(self.T.seqdata_path, "rb").read()
        if hashlib.sha256(raw).hexdigest() != SEQDATA_SHA256:
            raise ChatSeqError(f"{self.T.seqdata_path} sha256 moved")
        if len(raw) != CONST_BYTES + 6 * POS_STRIDE:
            raise ChatSeqError(
                f"{self.T.seqdata_path} is {len(raw)} B, expected "
                f"{CONST_BYTES} B of constants + 6 committed positions")
        return raw[:CONST_BYTES]

    def blob(self, t_max=None):
        """The session const blob: const region + `t_max`-position pool.

        Layout, as offsets from SEQ_DATA_BASE (0x8000_0000):
            [0, 998144)                     deduped constants (verbatim)
            [998144, 998144 + t_max*1536)   position pool, 1536 B/position
        """
        tm = self.t_max if t_max is None else int(t_max)
        if self._blob is None or getattr(self, "_blob_tmax", None) != tm:
            self._blob = self.const_region() + self.pos_pool(tm)
            self._blob_tmax = tm
        return self._blob

    def blob_layout(self, t_max=None):
        tm = self.t_max if t_max is None else int(t_max)
        return {
            "const_base": SF.SEQ_DATA_BASE,
            "const_bytes": CONST_BYTES,
            "pos_base": POS_BLOB_BASE,
            "pos_bytes": tm * POS_STRIDE,
            "pos_stride": POS_STRIDE,
            "pos_copies": POS_COPIES,
            "pos_copy_bytes": POS_COPY_BYTES,
            "t_max": tm,
            "total_bytes": CONST_BYTES + tm * POS_STRIDE,
            "xrf_pos_max": XRF_POS_MAX,
        }

    # ------------------------------------------------------------------
    # guards
    # ------------------------------------------------------------------
    def check_pos(self, pos):
        pos = int(pos)
        if pos < 0 or pos >= self.t_max:
            raise ChatSeqError(f"position {pos} outside the session pool "
                               f"[0,{self.t_max})")
        if self.pos_mode == "xrf" and pos > XRF_POS_MAX:
            raise ChatSeqError(
                f"position {pos} needs XRF[4] = {pos * POS_STRIDE}, which does "
                f"not fit the SIGNED 18-bit XRF (max {XRF_POS_MAX}); "
                f"seq_unit.sv truncates silently and ref/seq_model.py does "
                f"not model it. Use pos_mode='ldc' or shorten the context.")
        return pos

    def context_guard(self, start_pos, nprompt, ntok, kv_depth=T_MAX):
        """Spec decision 8: T + (P-1) + N < 512 (RTL wraps SILENTLY).

        Returns the last position the turn will touch.  Raises when the
        turn would wrap the KV cache or run off the session's pool.
        """
        last = int(start_pos) + int(nprompt) + int(ntok) - 2
        if int(nprompt) < 1 or int(ntok) < 1:
            raise ChatSeqError("a turn needs >= 1 prompt token and >= 1 "
                               "generated token")
        if last >= int(kv_depth):
            raise ChatSeqError(
                f"turn would reach position {last} >= KV depth {kv_depth}: "
                f"rtl/layer_chan.sv wraps kv_waddr SILENTLY. Reset the "
                f"session (re-run the preamble) and re-prefill.")
        self.check_pos(last)
        return last

    # ------------------------------------------------------------------
    # record builders (all three holes live in template bytes)
    # ------------------------------------------------------------------
    def _seed_tok_rec(self, tok):
        tok = int(tok)
        if not (0 <= tok < (1 << SF.XRF_BITS)):
            raise ChatSeqError(f"token id {tok} does not fit the unsigned "
                               f"{SF.XRF_BITS}-bit XRF[3] (ISA A11)")
        b = bytearray(self.T.seed_tok)
        _set_imm32(b, 0, tok)
        return bytes(b)

    def _seed_pos_rec(self, pos):
        b = bytearray(self.T.seed_pos)
        _set_imm32(b, 0, 0 if self.pos_mode == "ldc"
                   else self.check_pos(pos) * POS_STRIDE)
        return bytes(b)

    def _tcnt_rec(self, n):
        n = int(n)
        if n <= 0:
            raise ChatSeqError("TCNT_SEQ must be >= 1 (0 at a JMP wraps to "
                               "2^32-1 and hangs — spec hazard list)")
        b = bytearray(self.T.tcnt)
        _set_imm32(b, 0, n)
        return bytes(b)

    def _jmp_rec(self, target):
        b = bytearray(self.T.jmp)
        _set_imm32(b, 0, int(target))
        return bytes(b)

    def _body(self, kind, pos, data_delta=0):
        """A body template, with the position LDCs patched in 'ldc' mode."""
        if self.pos_mode == "xrf":
            return self.T.body(kind)
        b = bytearray(self.T.body(kind))
        base = POS_BLOB_BASE + self.check_pos(pos) * POS_STRIDE + data_delta
        for j, off in enumerate(POS_LDC_REC_OFFSETS):
            _set_addr_lo(b, off * REC, base + j * POS_COPY_BYTES)
        return bytes(b)

    def _pos_ldc_writes(self, body_byte_off, pos, data_delta=0):
        base = POS_BLOB_BASE + self.check_pos(pos) * POS_STRIDE + data_delta
        return [(body_byte_off + o, _u32(base + j * POS_COPY_BYTES))
                for j, o in enumerate(POS_LDC_BYTE_OFFSETS)]

    # ------------------------------------------------------------------
    # image builders
    # ------------------------------------------------------------------
    def build_session(self):
        """The session-once preamble image: T_PREAMBLE + TCNT(1) + HALT.

        Run this ONCE per session (fresh context).  It resets conv windows,
        DeltaNet state, the KV/TCNT banks and L_LAYER.  Everything it
        establishes survives later launches: START clears only pc / err /
        abort / perf (rtl/seq_unit.sv:885-897), not the layer banks.
        """
        parts = [self.T.preamble, self._tcnt_rec(1), self.T.halt]
        data = b"".join(parts)
        holes = {"tcnt": NREC_PREAMBLE * REC + 4}
        recs = SF.unpack_stream(data)
        # G3.4 fix round 2: state the SHAPE layout the TEMPLATE declares,
        # so the MVGO envelope in ref/seq_format.validate applies to a v2.0
        # stream (where rtl/seq_unit.sv checks it unconditionally) and not
        # to a frozen isa=1 one.  See Templates.shape_isa.
        SF.validate_stream(recs, shape_isa=self.T.shape_isa)
        return Image("session", "session", data, holes, steps=0,
                     pos_mode=self.pos_mode, blob_span=_blob_span(recs),
                     counts=_census(recs))

    def build_step(self, tok=0, pos=0, kind="full", tcnt=1, data_delta=0):
        """One forward step as a standalone, relaunchable image.

        Layout (the 48-byte patch window is records 0..2, at offset 0):

            rec 0    T_SEED_TOK   imm32 = tok            hole "tok" @ +4
            rec 1    T_SEED_POS   imm32 = pos*1536       hole "pos" @ +20
            rec 2    T_TCNT       imm32 = tcnt (>=1)     hole "tcnt" @ +36
            rec 3..  body (lite = 14,006 / full = 14,740 records)
            last     T_HALT

        `kind="lite"` cuts the LM head + AMAXL (prefill-lite, spec decision
        3): use it for prompt steps 0..P-2, whose argmax nobody reads.  The
        LAST prompt step and every decode step must be "full" — that is
        where the reply token comes from.

        The returned image is what the host uploads ONCE per session (one
        lite + one full); per launch it rewrites only `patch_step()`.
        """
        if kind not in KINDS:
            raise ChatSeqError(f"kind {kind!r} not in {KINDS}")
        head = (self._seed_tok_rec(tok) + self._seed_pos_rec(pos)
                + self._tcnt_rec(tcnt))
        body = self._body(kind, pos, data_delta=data_delta)
        data = head + body + self.T.halt
        holes = {"tok": 4, "pos": REC + 4, "tcnt": 2 * REC + 4}
        pos_ldc = ([o for (o, _b) in self._pos_ldc_writes(PATCH_BYTES, pos)]
                   if self.pos_mode == "ldc" else ())
        recs = SF.unpack_stream(data)
        # G3.4 fix round 2: state the SHAPE layout the TEMPLATE declares,
        # so the MVGO envelope in ref/seq_format.validate applies to a v2.0
        # stream (where rtl/seq_unit.sv checks it unconditionally) and not
        # to a frozen isa=1 one.  See Templates.shape_isa.
        SF.validate_stream(recs, shape_isa=self.T.shape_isa)
        return Image(f"step.{kind}", "step", data, holes, steps=1,
                     pos_mode=self.pos_mode, patch_off=0,
                     patch_len=PATCH_BYTES, pos_ldc=pos_ldc,
                     blob_span=_blob_span(recs), counts=_census(recs))

    def patch_step(self, image=None, tok=0, pos=0, tcnt=1, data_delta=0):
        """The per-launch patch for a resident step image (spec decision 4).

        Parameters
        ----------
        image : Image | bytes | None
            When given, the patch is validated against it (and `Patch.apply`
            can produce the patched bytes).  None = "just give me the bytes
            and the offsets" — the normal host path, which DMAs them
            straight into DDR.
        tok   : token id      -> XRF[3]  (ALWAYS emitted, never skipped)
        pos   : position      -> XRF[4] = pos*1536, ABSOLUTE
        tcnt  : TCNT_SEQ      -> 1 for a JMP-less step image
        data_delta : host relocation delta (plan["data_delta"] from
            sw/seq_run.plan_ddr) — only used in pos_mode="ldc", where the
            patch carries absolute const-blob addresses.

        Returns a `Patch`; `Patch.writes()` is [(offset, bytes)].  For the
        frozen pos_mode="xrf" that is exactly one 48-byte write at 0.
        """
        data = (self._seed_tok_rec(tok) + self._seed_pos_rec(pos)
                + self._tcnt_rec(tcnt))
        extra = (self._pos_ldc_writes(PATCH_BYTES, pos, data_delta)
                 if self.pos_mode == "ldc" else [])
        p = Patch(0, data, extra,
                  fields={"tok": int(tok), "pos": int(pos),
                          "xrf4": 0 if self.pos_mode == "ldc"
                          else int(pos) * POS_STRIDE,
                          "tcnt": int(tcnt)})
        if image is not None:
            img = image if isinstance(image, Image) else None
            if img is not None:
                if img.kind != "step":
                    raise ChatSeqError(f"patch_step on a {img.kind!r} image")
                if img.patch_off != 0 or img.patch_len != PATCH_BYTES:
                    raise ChatSeqError("image patch window moved")
        return p

    def build_turn(self, prompt_ids, ntok, start_pos=0, prefill="lite",
                   loop=True, with_preamble=False):
        """One whole turn as a SINGLE stream (spec decision 4's fallback).

        steps = len(prompt_ids) + ntok - 1: the argmax after the LAST
        prompt token IS the first reply token.

            prompt step i < P-1 : SEED_TOK, SEED_POS, body(`prefill`)
            prompt step   P-1   : SEED_TOK, SEED_POS, [TCNT(ntok)], body(full)
            decode step         : SEED_POS, body(full)      (token = AMAXL)

        With `loop=True` and ntok >= 2 the decode steps collapse to the
        committed artifact's shape — one body + T_POSADV + T_JMP with
        TCNT_SEQ = ntok — so the image stays ~1 body long regardless of
        reply length.  The loop necessarily uses the RELATIVE position
        advance (XOP +1536), which is the only place this compiler is not
        "absolute only"; `loop=False` unrolls with absolute seeds.

        `with_preamble=True` prepends T_PREAMBLE so the image is a whole
        self-contained session+turn (that is the form gate A1 compares
        against the committed monolithic stream).
        """
        ids = [int(t) for t in prompt_ids]
        ntok = int(ntok)
        P = len(ids)
        self.context_guard(start_pos, P, ntok)
        if prefill not in KINDS:
            raise ChatSeqError(f"prefill {prefill!r} not in {KINDS}")
        use_loop = bool(loop) and ntok >= 2
        if use_loop and self.pos_mode == "ldc":
            raise ChatSeqError("pos_mode='ldc' cannot drive a looped body "
                               "(the LDC addresses are per-step); use "
                               "loop=False or pos_mode='xrf'")

        parts, holes, nrec = [], {}, 0

        def emit(b, tag=None, hole_off=4):
            nonlocal nrec
            parts.append(b)
            if tag:
                holes[tag] = nrec * REC + hole_off
            nrec += len(b) // REC

        if with_preamble:
            emit(self.T.preamble)
        if not use_loop:
            emit(self._tcnt_rec(1), "tcnt")

        for i in range(P):
            last_prompt = (i == P - 1)
            kind = "full" if last_prompt else prefill
            emit(self._seed_tok_rec(ids[i]), f"step{i}.tok")
            emit(self._seed_pos_rec(start_pos + i), f"step{i}.pos")
            if last_prompt and use_loop:
                emit(self._tcnt_rec(ntok), "tcnt")
                loop_head = nrec
                emit(self._body("full", start_pos + i))
                emit(self.T.posadv)
                emit(self._jmp_rec(loop_head), "jmp")
                emit(self.T.halt)
                data = b"".join(parts)
                recs = SF.unpack_stream(data)
                # G3.4 fix round 2: state the SHAPE layout the TEMPLATE declares,
                # so the MVGO envelope in ref/seq_format.validate applies to a v2.0
                # stream (where rtl/seq_unit.sv checks it unconditionally) and not
                # to a frozen isa=1 one.  See Templates.shape_isa.
                SF.validate_stream(recs, shape_isa=self.T.shape_isa)
                # NB: a RECORD index (what the JMP hole must be set to), not
                # a byte offset like every other entry in `holes`.
                holes["loop_head_rec"] = loop_head
                return Image("turn.loop", "turn", data, holes,
                             steps=P + ntok - 1, pos_mode=self.pos_mode,
                             blob_span=_blob_span(recs), counts=_census(recs))
            emit(self._body(kind, start_pos + i))

        for k in range(1, ntok):
            i = P - 1 + k
            emit(self._seed_pos_rec(start_pos + i), f"step{i}.pos")
            emit(self._body("full", start_pos + i))

        emit(self.T.halt)
        data = b"".join(parts)
        recs = SF.unpack_stream(data)
        # G3.4 fix round 2: state the SHAPE layout the TEMPLATE declares,
        # so the MVGO envelope in ref/seq_format.validate applies to a v2.0
        # stream (where rtl/seq_unit.sv checks it unconditionally) and not
        # to a frozen isa=1 one.  See Templates.shape_isa.
        SF.validate_stream(recs, shape_isa=self.T.shape_isa)
        return Image("turn.flat", "turn", data, holes, steps=P + ntok - 1,
                     pos_mode=self.pos_mode, blob_span=_blob_span(recs),
                     counts=_census(recs))

    # ------------------------------------------------------------------
    # host-side helpers (sw/chat_seq.py)
    # ------------------------------------------------------------------
    def resident_images(self, align=4096):
        """The three images a launch-per-step session keeps in DDR.

        Returns [(name, byte offset inside the stream window, Image)] with
        `align`-aligned offsets, so the host can

            recs, _ = seq_run.relocate(SF.unpack_stream(im.data), tc.meta,
                                       plan, len(blob))      # ONCE per image
            dev.dma_write(plan["seq_base"] + off, SF.pack_stream(recs))

        and then launch any of them by writing SEQ_BASE = seq_base + off and
        SEQ_LEN = im.seq_len.  Total ~484 KiB — the 48 MiB stream window is
        never a constraint in this flow (spec decision 4).
        """
        out, off = [], 0
        for name, im in (("session", self.build_session()),
                         ("lite", self.build_step(0, 0, "lite")),
                         ("full", self.build_step(0, 0, "full"))):
            out.append((name, off, im))
            off += (im.nbytes + align - 1) // align * align
        return out

    def host_meta(self):
        """The committed .seq.json, for sw/seq_run.plan_ddr()/relocate().

        It is the REAL artifact metadata (spec decision 11: do not fabricate
        one).  `stream_bytes`/`nrec`/`seqdata_bytes` describe the committed
        monolithic stream, NOT the compiled images — pass the per-image
        sizes to plan_ddr()/relocate() explicitly.
        """
        m = dict(self.meta)
        m["chat_seq"] = {"template_sha256": self.T.stream_sha,
                         "blob_bytes": len(self.blob()),
                         "t_max": self.t_max, "pos_mode": self.pos_mode}
        return m

    def plan_turn(self, prompt_ids, ntok, start_pos=0, prefill="lite"):
        """The launch schedule for a turn, as a list of per-launch dicts.

        Each entry is {"kind","tok","pos","reads_token"}; `tok` is None for
        a decode step, where the host must substitute the token it popped
        from the OUT FIFO of the previous launch.  `reads_token` says
        whether this launch pushes a token to the OUT FIFO (lite does not).
        """
        ids = [int(t) for t in prompt_ids]
        P, ntok = len(ids), int(ntok)
        self.context_guard(start_pos, P, ntok)
        plan = []
        for i in range(P):
            kind = "full" if i == P - 1 else prefill
            plan.append({"kind": kind, "tok": ids[i], "pos": start_pos + i,
                         "reads_token": kind == "full"})
        for k in range(1, ntok):
            plan.append({"kind": "full", "tok": None,
                         "pos": start_pos + P - 1 + k, "reads_token": True})
        return plan


# ======================================================================
# stream surgery used by the split-vs-mono gate
# ======================================================================
def split_stream(stream, cuts, restore=(), shape_isa=None):
    """Cut a record stream into launchable images at record indices `cuts`.

    Every piece gets a HALT appended and its JMP targets rebased; `restore`
    is an optional list, one per piece, of extra records to PREPEND (used
    to re-seed XRF[3]/XRF[4], which the hardware zeroes at every START).
    A JMP that crosses a cut is refused — the caller picked a bad boundary.
    """
    recs = (SF.unpack_stream(stream)
            if isinstance(stream, (bytes, bytearray)) else list(stream))
    bounds = [0] + list(cuts) + [len(recs)]
    out = []
    for k in range(len(bounds) - 1):
        a, b = bounds[k], bounds[k + 1]
        pre = list(restore[k]) if k < len(restore) and restore[k] else []
        piece = []
        for i in range(a, b):
            r = recs[i]
            if r.opcode == SF.OP_JMP:
                t = int(r.imm32)
                if not (a <= t < b):
                    raise ChatSeqError(
                        f"JMP at rec {i} targets {t}, outside its piece "
                        f"[{a},{b}) — bad cut")
                r = SF.Rec(SF.OP_JMP, flags=r.flags, target=r.target,
                           imm32=t - a + len(pre), addr_lo=r.addr_lo,
                           len_or_addr_hi=r.len_or_addr_hi)
            piece.append(r)
        if not piece or piece[-1].opcode != SF.OP_HALT:
            piece.append(SF.Rec(SF.OP_HALT))
        recs_out = pre + piece
        # G3.4 fix round 2: the SHAPE layout is the CALLER's knowledge
        # here -- this function is handed a stream, not a template -- so it
        # is a keyword, defaulting to "not stated" exactly as
        # ref/seq_format.validate does.  A caller splitting a v2.0 stream
        # passes SF.SHAPE_ISA_9B and gets the MVGO envelope; a caller
        # splitting a frozen isa=1 one passes nothing.
        SF.validate_stream(recs_out, shape_isa=shape_isa)
        out.append(SF.pack_stream(recs_out))
    return out


# ======================================================================
# gates
# ======================================================================
EMB_SUFFIX = ".emb.bin"


def emb_base_of(emb_path):
    """Artifact prefix of an `<prefix>.emb.bin` path.

    Deliberately strict.  An earlier revision of this fix wrote

        base = ... if emb_path.endswith(EMB_SUFFIX) else None

    and `base=None` then SKIPPED the manifest and fell back to the selected
    model's geometry with nothing cross-checking it — defect A reproduced
    inside the fix.  There is no such bypass now: the generator only ever
    writes `<prefix>.emb.bin` (`ref/gen_model_script.py:628`), so any other
    name is a caller error, not a licence to guess.
    """
    if not str(emb_path).endswith(EMB_SUFFIX):
        raise ChatSeqError(
            f"{emb_path}: an embedding table must be named "
            f"<prefix>{EMB_SUFFIX} so its `<prefix>.weights.json` can be "
            f"found — this reader will not guess a row stride")
    return str(emb_path)[:-len(EMB_SUFFIX)]


def emb_row_bytes(base):
    """Byte stride of one `<base>.emb.bin` row = 2*H, for THIS artifact.

    It is 2048 B at H=1024 (0.8B) and 4096 B at H=2048 (2B), so it is not a
    constant and must never be spelled as one.  It comes from
    `<base>.weights.json`'s `emb_row_bytes` key, which the generator writes
    beside the table (`ref/gen_layer_script.dump_weights`,
    `ref/gen_model_script.py:627`), read through the one reader,
    `sw/hwmap.load_weights_manifest` — and it is REQUIRED, exactly as
    `ref/seq_model.gate()` requires it at :785.  A pre-R-b manifest with no
    such key answers `sw/hwmap.EMB_ROW_BYTES_DEFAULT`, which G3.4 moved from
    2048 to 8192 with the RTL reset it mirrors (spec 5.3 S8) — so the
    default is now the 9B row, and a pre-R-b artifact needs its manifest
    regenerated, which SEQ_ISA v2.0 requires of it anyway.

    The manifest and the selected model must then agree: an artifact
    generated for one geometry and read under `FABLE5_MODEL` for the other is
    exactly the mix-up this function exists to make loud.

    TWO CAVEATS, both recorded rather than handled:
    * `ref/seq_model.py:1297-1303` is a SECOND, independent reader of the same
      key.  It is correct today and manifest-driven like this one; they are
      not shared code, so a change to the artifact contract has to land in
      both.
    * If a future generator ever PADS the row to the next power of two — the
      4B `2560 -> 8192 B` option of the feasibility study's D4 — this
      equality is the wrong test AND `load_emb`'s `(vocab, H)` contract
      breaks: `layer_fixed_greedy`'s `x = np.asarray(M.emb[tok], ...)` takes
      the row WHOLE (unlike
      `M.embed`, which slices `n=LR.H`), so a padded row would carry its pad
      into the residual.  Padding must arrive as an explicit manifest key,
      with a slice here, not as a silent widening.
    """
    import layer_ref as LR
    import model_select as MS
    import hwmap as HW
    man = base + ".weights.json"
    if not os.path.exists(man):
        raise ChatSeqError(
            f"{man} not found: the embedding row stride travels WITH the "
            f"artifact and this reader will not fall back to a guess "
            f"(ref/seq_model.py:1301 requires the same file)")
    want = 2 * LR.H
    rb = int(HW.load_weights_manifest(base)[1]["emb_row_bytes"])
    if rb != want:
        raise ChatSeqError(
            f"{man} says emb_row_bytes={rb} but the selected model "
            f"(FABLE5_MODEL={MS.TAG}) has H={LR.H} -> {want} B rows: "
            f"wrong artifact for this geometry")
    return rb


def load_emb(base, emb_path=None, expect_vocab=None):
    """(emb memmap (vocab,H) int16, vocab) for an artifact's embedding table.

    THE reader for `<base>.emb.bin` on this module's offline paths.  The row
    stride comes from `emb_row_bytes()` and the row COUNT is then checked
    against the selected config's `vocab_size` (`expect_vocab` overrides it,
    for synthetic tables in the selftest).  Both checks are load-bearing:

    * hard-coding the stride as `size // 2048` + `.reshape(n, 1024)` is NOT
      caught by the reshape.  At the real vocabulary (248,320 = 2^11 x 121.25,
      so V*H is a multiple of 1024 for every even H) it is legal at EVERY
      geometry this project has — 0.8B, 2B, 4B and 9B alike — and simply
      returns a table with 1x/2x/2.5x/4x the rows, each one a 1024-word slice
      of some other token's row (docs/QWEN35_NEXT_FEASIBILITY.md §2.10 /
      §7.2 defect A, whose "2.5x/4x too large" is the arithmetic above).
    * the row count is what catches a table with NO manifest, or one whose
      manifest agrees with the geometry by luck: a 0.8B table read at 2B is a
      whole number of 4096 B rows, just 124,160 of them instead of 248,320.
    """
    import layer_ref as LR
    if emb_path is None:
        emb_path = base + EMB_SUFFIX
    rb = emb_row_bytes(base)
    nby = os.path.getsize(emb_path)
    if nby % rb:
        raise ChatSeqError(f"{emb_path}: {nby} B is not a whole number of "
                           f"{rb} B embedding rows")
    vocab = nby // rb
    want_v = int(LR.CFG["vocab_size"] if expect_vocab is None
                 else expect_vocab)
    if vocab != want_v:
        raise ChatSeqError(
            f"{emb_path}: {nby} B / {rb} B = {vocab} rows, but this model's "
            f"vocab_size is {want_v} — wrong table for this geometry")
    emb = np.memmap(emb_path, dtype="<i2", mode="r").reshape(vocab, rb // 2)
    return emb, vocab


def _artifacts(prefix=DEFAULT_PREFIX, base=DEFAULT_BASE):
    """(meta, committed recs, committed blob, emb memmap, DDRWeights)."""
    import seq_model as SM
    meta = json.load(open(prefix + ".seq.json"))
    recs = SF.unpack_stream(open(prefix + ".seq", "rb").read())
    blob = open(prefix + ".seqdata.bin", "rb").read()
    emb, _vocab = load_emb(base)
    W = SM.DDRWeights.from_files(base, meta["weights"], meta)
    return meta, recs, blob, emb, W


def _run(recs_or_bytes, blob, W, emb, mach, log=None):
    """One LAUNCH: a fresh SeqExec (XRF and TCNT_SEQ zeroed, as START does)
    against a PERSISTENT Mach.  Returns the executor."""
    import seq_model as SM
    ex = SM.SeqExec(recs_or_bytes, blob, W, emb=emb, mach=mach)
    n = len(ex.recs)
    t0 = time.time()
    ex.run(max_steps=50 * n)
    if log:
        log(f"      launch {n:>6d} recs -> tokens {ex.out_fifo} "
            f"({time.time() - t0:.1f}s)")
    return ex


def gate_a1(prefix=DEFAULT_PREFIX, base=DEFAULT_BASE, log=print):
    """A1 — the compiled model_v2_s1 schedule reproduces the golden run.

    (a) compile prompt [760,6511,314,9338] / ntok 3 as (i) a single-stream
        turn (looped AND flat) and (ii) launch-per-step, execute each on
        ref/seq_model.py continuing ONE Mach across launches, and require
        tokens == [561,314,279,369,279,6511] AND diff_state()==[] against
        the committed monolithic stream's final state.
    (b) split-vs-mono: the COMMITTED bytes cut into 2 and 4 launches
        execute identically to the monolithic stream (this is what proves
        "START preserves context").
    """
    import seq_model as SM
    meta, mono_recs, mono_blob, emb, W = _artifacts(prefix, base)
    prompt = [760, 6511, 314, 9338]
    ntok = 3
    want = list(meta["expect_tokens"])
    log(f"--- gate A1: {prefix}")
    log(f"    prompt {prompt} ntok {ntok}  expect {want}")

    tc = TurnCompiler(prefix)
    blob = tc.blob()
    log(f"    blob {len(blob)} B (const {CONST_BYTES} + pool "
        f"{tc.t_max}x{POS_STRIDE})")

    # ---- reference: the committed monolithic stream -------------------
    Mm = SM._fresh_mach()
    log("    [mono] committed 60,495-record stream")
    exm = _run(mono_recs, mono_blob, W, emb, Mm, log)
    mono_tokens, mono_state = list(exm.out_fifo), SM.snapshot(Mm)
    ok = (mono_tokens == want)
    log(f"    mono tokens {mono_tokens} {'OK' if ok else 'MISMATCH'}")

    results = {"mono_tokens": mono_tokens, "expect": want, "cases": {}}

    def case(name, images, steps_note=""):
        nonlocal ok
        M = SM._fresh_mach()
        toks = []
        log(f"    [{name}] {len(images)} launch(es) {steps_note}")
        for im in images:
            ex = _run(im, blob, W, emb, M, log)
            toks += ex.out_fifo
        d = SM.diff_state(mono_state, SM.snapshot(M))
        good = (toks == want) and not d
        ok = ok and good
        log(f"      tokens {toks} {'IDENTICAL' if toks == want else 'MISMATCH'}"
            f"; diff_state {'EMPTY' if not d else d[:6]} -> "
            f"{'PASS' if good else 'FAIL'}")
        results["cases"][name] = {"tokens": toks, "diffs": d, "pass": good}

    sess = tc.build_session()
    log(f"    session image {sess.nrec} recs / {sess.nbytes} B "
        f"(SEQ_LEN {sess.seq_len})")

    # (a-i) single stream, looped, preamble included
    turn_loop = tc.build_turn(prompt, ntok, 0, prefill="full", loop=True,
                              with_preamble=True)
    log(f"    turn.loop  {turn_loop.nrec} recs / {turn_loop.nbytes} B "
        f"holes {sorted(turn_loop.holes)}")
    case("single-stream/loop", [turn_loop.data], "(one image, one START)")

    # (a-i') single stream, flat
    turn_flat = tc.build_turn(prompt, ntok, 0, prefill="full", loop=False,
                              with_preamble=True)
    log(f"    turn.flat  {turn_flat.nrec} recs / {turn_flat.nbytes} B")
    case("single-stream/flat", [turn_flat.data], "(one image, one START)")

    # (a-ii) launch per step, ONE Mach across launches
    plan = tc.plan_turn(prompt, ntok, 0, prefill="full")
    imgs = [sess.data]
    for k, st in enumerate(plan):
        # a decode step feeds the token the PREVIOUS launch pushed to the
        # OUT FIFO — here that is the golden token, on hardware it is the
        # value the host popped from 0x6018.
        t = st["tok"] if st["tok"] is not None else want[k - 1]
        imgs.append(tc.build_step(t, st["pos"], st["kind"]).data)
    log(f"    per-step images: 1 session + {len(plan)} step launches "
        f"({[s['kind'] for s in plan]})")
    case("launch-per-step", imgs, "(session + one launch per forward step)")

    # (a-iii) launch per step, RESIDENT image + 48-byte patch (the real flow)
    res_full = tc.build_step(0, 0, "full")
    imgs = [sess.data]
    for k, st in enumerate(plan):
        t = st["tok"] if st["tok"] is not None else want[k - 1]
        imgs.append(tc.patch_step(res_full, t, st["pos"]).apply(res_full))
    log(f"    resident-image patch flow: 48 B/launch at offset "
        f"{res_full.patch_off}")
    case("resident+48B-patch", imgs, "(one resident full image, patched)")

    # (a-iv) prefill-lite: reply tokens only (spec decision 3)
    plan_l = tc.plan_turn(prompt, ntok, 0, prefill="lite")
    M = SM._fresh_mach()
    _run(sess.data, blob, W, emb, M)
    toks = []
    for k, st in enumerate(plan_l):
        t = st["tok"] if st["tok"] is not None else want[k - 1]
        ex = _run(tc.build_step(t, st["pos"], st["kind"]).data, blob, W, emb, M)
        toks += ex.out_fifo
    want_reply = want[len(prompt) - 1:]
    lite_ok = (toks == want_reply)
    ok = ok and lite_ok
    log(f"    [prefill-lite] {[s['kind'] for s in plan_l]} -> reply tokens "
        f"{toks} vs {want_reply} -> {'PASS' if lite_ok else 'FAIL'}")
    results["cases"]["prefill-lite"] = {"tokens": toks, "expect": want_reply,
                                        "pass": lite_ok}

    # ---- (b) split-vs-mono on the COMMITTED bytes ---------------------
    mono_bytes = SF.pack_stream(mono_recs)
    # cut 1: end of step 0's body.  XRF[4] restarts at 0 and the piece's own
    # XOP +1536 lands on pos 1, XRF[3] is overwritten by its own seed, so no
    # restore records are needed — the purest possible demonstration.
    pieces = split_stream(mono_bytes, [16266])
    case("committed/split-2", pieces, "(committed bytes, cut at rec 16266)")

    # cuts 2+3 land mid-schedule, where XRF[3]/XRF[4] ARE live: re-seed them
    # (absolute) at the head of each piece, exactly as a real relaunch must.
    seed = TurnCompiler(prefix)
    restore = [
        (),
        (SF.unpack_stream(seed._seed_tok_rec(561))
         + SF.unpack_stream(seed._seed_pos_rec(0))),      # pos 0 -> XOP -> 1
        (SF.unpack_stream(seed._seed_tok_rec(314))
         + SF.unpack_stream(seed._seed_pos_rec(1))),      # pos 1 -> XOP -> 2
        (SF.unpack_stream(seed._seed_tok_rec(279))
         + SF.unpack_stream(seed._seed_pos_rec(2))),      # pos 2 -> XOP -> 3
    ]
    pieces = split_stream(mono_bytes, [16266, 31008, 45749], restore=restore)
    case("committed/split-4", pieces,
         "(committed bytes, cuts at 16266/31008/45749 + XRF re-seed)")

    results["pass"] = bool(ok)
    log(f"GATE A1: {'PASS' if ok else 'FAIL'}")
    return ok, results


def gate_a2(prefix=DEFAULT_PREFIX, t_max=T_MAX, log=print):
    """A2 — the generated position pool reproduces the committed one.

    The committed .e.seqdata.bin tail [998144,1007360) is 6 positions of the
    same pool; requiring it byte-identical pins the layout (6 copies x 256 B,
    1536 B stride) AND the Q15 rounding of layer_fixed.rope_tables_q15.
    """
    tc = TurnCompiler(prefix, t_max=t_max)
    raw = open(tc.T.seqdata_path, "rb").read()
    lay = tc.blob_layout()
    log(f"--- gate A2: position blob, T_max={t_max}")
    log(f"    committed seqdata {len(raw)} B = const {CONST_BYTES} + "
        f"{(len(raw) - CONST_BYTES) // POS_STRIDE} positions")
    pool = tc.pos_pool(t_max)
    tail = raw[CONST_BYTES:]
    n_cm = len(tail) // POS_STRIDE
    ok = (pool[:len(tail)] == tail)
    log(f"    first {n_cm} generated positions vs committed tail: "
        f"{'BYTE-IDENTICAL' if ok else 'MISMATCH'}")
    if not ok:
        for p in range(n_cm):
            a = pool[p * POS_STRIDE:(p + 1) * POS_STRIDE]
            b = tail[p * POS_STRIDE:(p + 1) * POS_STRIDE]
            if a != b:
                log(f"      position {p} differs")
    ok = ok and (len(pool) == t_max * POS_STRIDE)
    log(f"    pool {len(pool)} B (= {t_max} x {POS_STRIDE})")

    blob = tc.blob()
    ok = ok and (blob[:CONST_BYTES] == raw[:CONST_BYTES])
    ok = ok and (len(blob) == lay["total_bytes"])
    log(f"    const region [0,{CONST_BYTES}) unchanged: "
        f"{blob[:CONST_BYTES] == raw[:CONST_BYTES]}")
    log(f"    session blob {len(blob)} B  layout {json.dumps(lay)}")
    log(f"    XRF[4] cursor reaches pos <= {XRF_POS_MAX} "
        f"({XRF_POS_MAX * POS_STRIDE} <= 2^17-1); pos_mode='ldc' needed "
        f"beyond that")
    log(f"GATE A2: {'PASS' if ok else 'FAIL'}")
    return ok, {"pool_bytes": len(pool), "blob_bytes": len(blob),
                "layout": lay, "pass": bool(ok)}


# ----------------------------------------------------------------------
# A3: fresh prompts, seq_model tokens == the layer_fixed greedy reference
# ----------------------------------------------------------------------
A3_PROMPTS = ("The capital of Japan",
              "Water boils at",
              "My favorite color is",
              "In the beginning")


def tokenize(texts, log=print):
    """BPE-encode with the checkpoint's own tokenizer (sw/infer.py BpeTok).

    That is the same encoder sw/infer.py drives the board with, and it
    self-tests against gen_model_script.PROMPTS before it is used.
    """
    sw = os.path.join(_ROOT, "sw")
    if sw not in sys.path:
        sys.path.insert(0, sw)
    import infer                                              # noqa: E402
    tp = infer._tokenizer_path()
    if not tp:
        raise ChatSeqError("tokenizer.json not found in the HF cache")
    tk = infer.BpeTok(tp)
    n = tk.self_test()
    log(f"    tokenizer {tp}\n      byte-level BPE, {len(tk.ranks)} merges, "
        f"self-test OK on {n} committed prompts")
    out = []
    for t in texts:
        ids = tk.encode(t)
        log(f"      {t!r} -> {ids} -> {tk.decode(ids)!r}")
        out.append(ids)
    return out, tk


def layer_fixed_greedy(prompt_ids, ntok, res_scale=8, w4_group=None,
                       emb_path=None, log=print, _cache={}):
    """The greedy fixed-point reference: ref/layer_fixed.py, host-side.

    This is gen_model_script.main()'s forward loop with the emission and
    the artifact dumps removed — same quantizer (`LF.quant_layer`,
    `quant_linear_big`), same folded ln_f, same scratchpad model
    (`gen_layer_script.Mach`), so its argmaxes ARE the golden tokens the
    committed .e.seq was generated from.  The checkpoint load + quantize is
    minutes; it is cached in-process across calls.
    """
    import gen_layer_script as GLS
    import gen_token_script as GTS
    import gen_model_script as GMS
    import layer_ref as LR
    import load_qwen35 as LQ
    from w4a8_ref import G

    w4_group = G if w4_group is None else w4_group
    key = (res_scale, w4_group)
    if key not in _cache:
        t0 = time.time()
        md = LQ.load_model()
        log(f"    checkpoint {md['path']} ({time.time() - t0:.0f}s)")
        slots = GTS.slot_plan(md["layer_types"])
        layers = []
        for i, (lt, dn_slot, kv_slot) in enumerate(slots):
            wf = md["layers"][i]
            qw = LF.quant_layer(wf, res_scale=res_scale, g=w4_group,
                                layer_idx=i)          # calibration lookup key
            md["layers"][i] = None
            layers.append((lt, qw, dn_slot, kv_slot))
        ln_f_q12 = np.round((1.0 + np.asarray(md["ln_f"], dtype=np.float64))
                            * (1 << 12)).astype(GLS.I64)
        # G2c: the LM head is `md["head"]`, NOT `md["emb"]`.  Where
        # `tie_word_embeddings` is true (0.8B / 2B / 4B) `load_model` hands
        # back an independent COPY of the embedding table, so this is
        # byte-identical to what this line did before; at 9B it is the
        # checkpoint's own `lm_head.weight` and `md["emb"]` would have been
        # the wrong matrix.  This path never reads the embedding TABLE — the
        # int16 rows come from the .emb.bin artifact via `load_emb` below —
        # so both are released here.
        qw_head = GMS.quant_linear_big(md["head"], g=w4_group,
                                       salience=LF.calib_salience("lm_head"),
                                       hess=LF.calib_hess("lm_head"))
        md["emb"] = md["head"] = None
        log(f"    quantized {len(layers)} layers + LM head "
            f"{qw_head['w4'].shape} ({time.time() - t0:.0f}s)")
        _cache[key] = (layers, ln_f_q12, qw_head, len(slots))
    layers, ln_f_q12, qw_head, _n = _cache[key]

    base = DEFAULT_BASE if emb_path is None else emb_base_of(emb_path)
    emb_q, vocab = load_emb(base, emb_path)

    LF.bf_reset()
    saved = os.environ.pop("SEQ_EMIT", None)          # model only, never emit
    try:
        M = GLS.Mach(open(os.devnull, "w"))
    finally:
        if saved is not None:
            os.environ["SEQ_EMIT"] = saved
    M.emb = emb_q
    caches = [LF.new_cache_fx(lt) for (lt, _q, _d, _k) in layers]

    # S3: the generator's STATIC PREAMBLE at SEQ_ISA v2.1 — the conv taps
    # go into the DDR state image (the host uploads them, spec 7.1) and the
    # preamble emits the TCNT resets and the first SLDs.  This is the
    # host-side twin of T_PREAMBLE and it mirrors gen_model_script.main().
    types = [lt for (lt, _q, _d, _k) in layers]
    n_dn = sum(1 for lt in types if lt != "full_attention")
    kv_pf = GLS.sched_kv_prefetch(types)
    for (lt, qw, dn_l, kv_l) in layers:
        if lt != "full_attention":
            M.seed_conv(dn_l, qw["dn"]["conv_w"])
    GLS.sched_preamble(M, types)

    ids = [int(t) for t in prompt_ids]
    nsteps = len(ids) + int(ntok) - 1
    tok, step_toks = ids[0], []
    for t in range(nsteps):
        M.embed(tok, GLS.X0, LR.H)
        x = np.asarray(M.emb[tok], dtype=GLS.I64)
        for i, (((lt, qw, dn_l, kv_l)), cache) in enumerate(
                zip(layers, caches)):
            if lt == "full_attention":
                M.layer(dn_l % 2, 0, dn_l % 2, kv_l)
                gold = LF.layer_decode_fx(x, qw, cache, t)
                GLS.attn_token(M, qw["attn"], qw["ln1"], qw["ln2"], qw["mlp"],
                               t, gold)
            else:
                GLS.sched_dn_pair(M, dn_l, n_dn, kv_pf[i])
                GLS.sched_cv_pair(M, dn_l, n_dn)
                M.layer(dn_l % 2, 0, dn_l % 2, kv_l)
                gold = LF.layer_decode_fx(x, qw, cache, t)
                GLS.dn_token(M, qw["dn"], qw["ln1"], qw["ln2"], qw["mlp"],
                             gold)
            x = gold
        GLS.sched_token_end(M, n_dn)
        # final RMSNorm + DYNQ8 + full-vocab head, over the WHOLE residual:
        # H words, not 1024.  `ref/gen_model_script.py:589-595` is the
        # parameterized original this loop is a copy of — CLASS B,
        # 2026-09-04 (S3, base 07eea51): that range named the RETIRED CONVW
        # + DNZ preamble as well, and the successor of the copied block is
        # the `M.W(STG, ln_f_q12)` .. `M.alu(0, H, 0, XN, 0, X8)` run in
        # `gen_model_script.main`'s decode loop, which is unmoved in
        # SUBSTANCE and only renumbered.  The four literals
        # that used to be here are §2.10's `ref/seq_chat.py:1320-1323` row —
        # a truncated ln_f load, an RMSNorm denominator over half the vector
        # and a DYNQ8 exponent to match, three lines silently wrong at 2B
        # before `M.matvec` raised on the 2048-wide head.
        M.W(GLS.STG, ln_f_q12)
        M.vnw_(GLS.STG, LR.H)
        M.vn(1, LR.H, LF.RS_F, LF.RS_F, GLS.X0, GLS.XN)
        M.alu(0, LR.H, 0, GLS.XN, 0, GLS.X8)
        y32, _ = M.matvec(qw_head, GLS.X8, LR.H, rowchunk=GMS.ROWCHUNK)
        for c in range(0, vocab, 2048):        # AMAX32 staging chunk, not H
            n = min(2048, vocab - c)
            M.W32(GLS.STG, y32[c:c + n])
            M.amax(n, GLS.STG, fresh=(c == 0))
        M.A()
        gold_tok = int(np.argmax(y32))
        assert M.am_idx == gold_tok, f"step {t}: {M.am_idx} != {gold_tok}"
        step_toks.append(gold_tok)
        tok = ids[t + 1] if t + 1 < len(ids) else gold_tok
    return step_toks


def gate_a3(prompts=A3_PROMPTS, ntok=3, prefix=DEFAULT_PREFIX,
            base=DEFAULT_BASE, log=print):
    """A3 — 4 FRESH prompts: seq_model(compiled) == layer_fixed greedy.

    Both sides are run per prompt: the reference is the host-side
    fixed-point forward (`layer_fixed_greedy`), the device side is the
    launch-per-step schedule this module compiles, executed on
    ref/seq_model.py against the committed packed weight images.
    """
    import seq_model as SM
    log(f"--- gate A3: {len(prompts)} fresh prompts, ntok {ntok}")
    ids_list, _tk = tokenize(prompts, log=log)

    # anchor: the committed schedule must come back out of the reference
    anchor = layer_fixed_greedy([760, 6511, 314, 9338], 3, log=log)
    want = [561, 314, 279, 369, 279, 6511]
    a_ok = (anchor == want)
    log(f"    ANCHOR reference('The capital of France') = {anchor} "
        f"{'== committed golden' if a_ok else '!= ' + str(want)}")

    meta, _mr, _mb, emb, W = _artifacts(prefix, base)
    tc = TurnCompiler(prefix)
    blob = tc.blob()
    ok = a_ok
    rows = []
    for text, ids in zip(prompts, ids_list):
        tc.context_guard(0, len(ids), ntok)
        ref = layer_fixed_greedy(ids, ntok, log=log)
        M = SM._fresh_mach()
        _run(tc.build_session().data, blob, W, emb, M)
        plan = tc.plan_turn(ids, ntok, 0, prefill="full")
        got, last = [], None
        for st in plan:
            t = st["tok"] if st["tok"] is not None else last
            ex = _run(tc.build_step(t, st["pos"], st["kind"]).data,
                      blob, W, emb, M)
            got += ex.out_fifo
            last = ex.out_fifo[-1] if ex.out_fifo else last
        good = (got == ref)
        ok = ok and good
        log(f"    {text!r} ids {ids}\n      reference {ref}\n      seq_model "
            f"{got}  -> {'IDENTICAL' if good else 'MISMATCH'}")
        rows.append({"text": text, "ids": ids, "reference": ref,
                     "seq_model": got, "pass": good})
    log(f"GATE A3: {'PASS' if ok else 'FAIL'}")
    return ok, {"anchor": anchor, "anchor_pass": a_ok, "prompts": rows,
                "pass": bool(ok)}


# ======================================================================
# cheap structural self-test (no weights, no checkpoint — seconds)
# ======================================================================
def emb_geometry_selftest(log=print, guards=True):
    """`load_emb` round-trip at the SELECTED model's geometry (no artifacts).

    Deliberate damage (the R-d lesson): write a synthetic table whose every
    word is its own row's token id, with a `-1` marker in the LAST column,
    then require `load_emb` to hand row `tok` back whole.  The pre-fix reader
    (`size // 2048`, `.reshape(n, 1024)`) passes that at H=1024 and fails it
    at every other H — and fails it SILENTLY, which is the whole point.

    THE SYNTHETIC VOCAB IS EVEN, and that matters (correction, 2026-08-25):
    the first revision of this regression used V=37, and an odd V makes the
    pre-fix reshape ILLEGAL at H=2560 (V*5120//2048 floors), which the
    selftest then reported as "loud at this geometry".  That was an artefact
    of the test, not a property of the defect.  The real vocabulary is
    248,320 — even, and 248,320*H is a multiple of 1024 for every even H — so
    the pre-fix reader reshapes SILENTLY at all four geometries, giving
    1x/2x/2.5x/4x the rows, exactly the "2.5x/4x too large" of the study's
    §2.10.  `real_vocab_is_silent` below pins that arithmetic directly, with
    no 1-2 GiB file involved.

    `ref/model_select.py` freezes FABLE5_MODEL at import, so `selftest()`
    reaches the other geometries by re-running this in a second interpreter.

    `guards=False` drops the REFUSAL checks (a short table, an artifact from
    the other geometry, a table with no manifest).  Those refusals are new
    with the fix, so the pre-fix reader fails them at every geometry;
    dropping them is what lets `evidence/qwen_next/defect_a/damage_test.py`
    show the geometry defect ALONE — pre-fix passes at H=1024 and fails
    everywhere else, nothing else in the way.
    """
    import tempfile
    import layer_ref as LR
    ok = True

    def chk(cond, msg):
        nonlocal ok
        ok = ok and bool(cond)
        log(f"    [{'ok' if cond else 'FAIL'}] {msg}")

    # V EVEN — see the docstring.  An odd V manufactures a ValueError at
    # H=2560 that the real vocabulary does not have.
    H, V = LR.H, 40
    V_REAL = int(LR.CFG["vocab_size"])
    log(f"--- seq_chat emb-geometry selftest: H={H}, row {2 * H} B, "
        f"synthetic vocab {V} (real {V_REAL:,})")

    # (a) the arithmetic of the defect at the REAL vocabulary, no file
    n_old_real = (V_REAL * 2 * H) // 2048
    chk(n_old_real * 1024 == V_REAL * H,
        f"real vocab {V_REAL:,} x H={H}: the pre-fix reshape is LEGAL "
        f"({n_old_real:,} x 1024 == {V_REAL * H:,}) — silent, not loud, "
        f"and {n_old_real / V_REAL:g}x too many rows")

    with tempfile.TemporaryDirectory() as td:
        base = os.path.join(td, "embgeom")
        tab = np.repeat(np.arange(V, dtype=np.int64).reshape(V, 1),
                        H, axis=1).astype("<i2")
        tab[:, -1] = -1                  # end-of-row marker, not just a head
        tab.tofile(base + EMB_SUFFIX)
        with open(base + ".weights.json", "w") as f:
            json.dump({"emb_row_bytes": 2 * H}, f)

        chk(emb_row_bytes(base) == 2 * H,
            f"emb_row_bytes reads {2 * H} B out of the manifest")
        emb, vocab = load_emb(base, expect_vocab=V)
        chk(emb.shape == (V, H) and vocab == V,
            f"load_emb -> shape {emb.shape}, vocab {vocab} "
            f"(want {(V, H)}, {V})")
        bad = [t for t in range(V)
               if not (int(emb[t][0]) == t and int(emb[t][-1]) == -1)]
        chk(not bad, f"every emb[t] is token t's WHOLE row ({len(bad)} wrong)")

        # (b) the pre-fix reader, verbatim, against the same bytes
        n_old = os.path.getsize(base + EMB_SUFFIX) // 2048
        old = np.memmap(base + EMB_SUFFIX, dtype="<i2",
                        mode="r").reshape(n_old, 1024)
        if H == 1024:
            chk(np.array_equal(np.asarray(old), np.asarray(emb)),
                "H=1024: the pre-fix literals coincide with the truth "
                "(this is why the defect hid)")
        else:
            # exactly the flat re-slicing, and nothing token-aware about it:
            # pre-fix row k is the 1024 words at FLAT offset k*1024, which
            # at H=2560 does not even stay inside one token's row.
            flat = np.asarray(emb).reshape(-1)
            bad = [k for k in range(n_old)
                   if not np.array_equal(np.asarray(old[k]),
                                         flat[k * 1024:(k + 1) * 1024])]
            spans = sum(1 for k in range(n_old)
                        if (k * 1024) // H != ((k + 1) * 1024 - 1) // H)
            chk(n_old != V and not bad,
                f"H={H}: the pre-fix literals SILENTLY give {n_old} rows, "
                f"each the flat 1024 words at k*1024 — token "
                f"(k*1024)//{H}'s row, {spans} of them straddling two "
                f"tokens — no exception anywhere "
                f"({len(bad)} rows off that model)")

        if guards:
            with open(base + EMB_SUFFIX, "r+b") as f:
                f.truncate(V * 2 * H - 2)   # lose one word of the last row
            try:
                load_emb(base, expect_vocab=V)
                chk(False, "a partial final row should have raised")
            except ChatSeqError:
                chk(True, "a partial final row is refused (ChatSeqError)")

    if not guards:
        log(f"EMB GEOMETRY SELFTEST: {'PASS' if ok else 'FAIL'}  (H={H})")
        return ok

    # (c) an artifact whose manifest is for a DIFFERENT geometry
    with tempfile.TemporaryDirectory() as td:
        base = os.path.join(td, "wronggeom")
        with open(base + EMB_SUFFIX, "wb") as f:
            f.write(b"\0" * (8 * H))        # 2 rows of the OTHER geometry
        with open(base + ".weights.json", "w") as f:
            json.dump({"emb_row_bytes": 4 * H}, f)
        try:
            load_emb(base, expect_vocab=2)
            chk(False, f"an emb_row_bytes={4 * H} artifact should have raised")
        except ChatSeqError:
            chk(True, f"a {4 * H} B-row artifact is refused at H={H}")

    # (d) NO manifest at all.  The first revision of this fix fell back to
    # 2*LR.H here and reshaped whatever it was given — defect A, inside the
    # fix.  It must refuse instead.
    with tempfile.TemporaryDirectory() as td:
        base = os.path.join(td, "nomanifest")
        with open(base + EMB_SUFFIX, "wb") as f:
            f.write(b"\0" * (V * 2 * H))    # RIGHT size for this geometry
        try:
            load_emb(base, expect_vocab=V)
            chk(False, "a table with no manifest should have raised")
        except ChatSeqError:
            chk(True, "a table with no <base>.weights.json is refused, "
                      "even at the right size (no guessed stride)")

    # (e) and a table whose ROW COUNT is wrong for the model: the 0.8B table
    # (2048 B rows) read at this geometry is still a whole number of rows.
    with tempfile.TemporaryDirectory() as td:
        base = os.path.join(td, "wrongvocab")
        with open(base + EMB_SUFFIX, "wb") as f:
            f.write(b"\0" * (V_REAL * 2048))
        with open(base + ".weights.json", "w") as f:
            json.dump({"emb_row_bytes": 2 * H}, f)
        try:
            load_emb(base)                  # real vocab_size check
            chk(H == 1024, f"a {V_REAL:,}-row 2048 B table is only correct "
                           f"at H=1024 (this is H={H})")
        except ChatSeqError:
            chk(H != 1024, f"the 0.8B table ({V_REAL:,} x 2048 B) is refused "
                           f"at H={H}: {V_REAL * 2048 // (2 * H):,} rows, "
                           f"not {V_REAL:,}")

    # (f) a mis-named table gets no guessed stride either
    try:
        emb_base_of("/tmp/whatever.bin")
        chk(False, "a non-<prefix>.emb.bin path should have raised")
    except ChatSeqError:
        chk(True, "a path that is not <prefix>.emb.bin is refused")

    log(f"EMB GEOMETRY SELFTEST: {'PASS' if ok else 'FAIL'}  (H={H})")
    return ok


def selftest(prefix=DEFAULT_PREFIX, log=print):
    """Template + hole + guard invariants.  Runs in seconds, no board."""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        ok = ok and bool(cond)
        log(f"    [{'ok' if cond else 'FAIL'}] {msg}")

    log(f"--- seq_chat selftest: {prefix}")
    tc = TurnCompiler(prefix)
    chk(len(tc.T.preamble) == NREC_PREAMBLE * REC, "T_PREAMBLE 1524 recs")
    chk(len(tc.T.body_full) == NREC_BODY_FULL * REC, "T_BODY_FULL 14740 recs")
    chk(len(tc.T.body_lite) == NREC_BODY_LITE * REC, "T_BODY_LITE 14006 recs")
    chk(tc.T.body_full.startswith(tc.T.body_lite), "lite is a body prefix")

    s = tc.build_session()
    chk(s.nrec == NREC_PREAMBLE + 2 and s.seq_len == s.nrec,
        f"session image {s.nrec} recs, SEQ_LEN == nrec")
    chk(SF.unpack_stream(s.data)[-1].opcode == SF.OP_HALT, "session ends HALT")
    chk(SF.unpack_stream(s.data)[NREC_PREAMBLE].imm32 == 1,
        "session TCNT_SEQ == 1 (belt and braces)")

    for kind, n in (("lite", NREC_BODY_LITE), ("full", NREC_BODY_FULL)):
        im = tc.build_step(1234, 7, kind)
        r = im.records()
        chk(im.nrec == 3 + n + 1, f"{kind} step image {im.nrec} recs")
        chk(im.patch_off == 0 and im.patch_len == 48,
            f"{kind} patch window 48 B at 0")
        chk(r[0].target == SF.csr_seq_xrf(SF.XRF_TOK) and r[0].imm32 == 1234,
            f"{kind} rec0 seeds XRF[3] = 1234")
        chk(r[1].target == SF.csr_seq_xrf(SF.XRF_POS)
            and r[1].imm32 == 7 * POS_STRIDE,
            f"{kind} rec1 seeds XRF[4] = 7*1536 (absolute)")
        chk(r[2].target == SF.csr_seq(SF.SOFF_TCNT_SEQ) and r[2].imm32 == 1,
            f"{kind} rec2 sets TCNT_SEQ = 1")
        chk(r[-1].opcode == SF.OP_HALT, f"{kind} ends HALT")
        chk(all(rr.opcode != SF.OP_JMP for rr in r), f"{kind} has no JMP")
        p = tc.patch_step(im, 4321, 9)
        chk(p.nbytes == 48 and p.writes()[0][0] == 0, f"{kind} patch is 48 B")
        pr = SF.unpack_stream(p.apply(im))
        chk(pr[0].imm32 == 4321 and pr[1].imm32 == 9 * POS_STRIDE,
            f"{kind} patch rewrites tok/pos")
        chk(p.apply(im)[48:] == im.data[48:],
            f"{kind} patch touches nothing past byte 48")

    lite = tc.build_step(0, 0, "lite")
    full = tc.build_step(0, 0, "full")
    chk(all(rr.opcode != SF.OP_AMAXL for rr in lite.records()),
        "lite image pushes no token (no AMAXL)")
    chk(sum(1 for rr in full.records() if rr.opcode == SF.OP_AMAXL) == 1,
        "full image pushes exactly one token")

    t = tc.build_turn([1, 2, 3], 3, 0, prefill="lite", loop=True)
    r = t.records()
    chk(sum(1 for x in r if x.opcode == SF.OP_JMP) == 1, "looped turn has 1 JMP")
    jmp = [i for i, x in enumerate(r) if x.opcode == SF.OP_JMP][0]
    chk(r[jmp].imm32 == t.holes["loop_head_rec"] and r[r[jmp].imm32].opcode
        == SF.OP_EMB, "JMP target is the loop-head EMB")
    tc_i = [i for i, x in enumerate(r)
            if x.opcode == SF.OP_CSRWR
            and x.target == SF.csr_seq(SF.SOFF_TCNT_SEQ)]
    chk(len(tc_i) == 1 and r[tc_i[0]].imm32 == 3,
        "looped turn sets TCNT_SEQ = ntok exactly once")
    chk(r[-1].opcode == SF.OP_HALT and t.seq_len == t.nrec,
        "looped turn ends HALT, SEQ_LEN == nrec")

    tf = tc.build_turn([1, 2, 3], 3, 0, prefill="lite", loop=False)
    rf = tf.records()
    chk(all(x.opcode != SF.OP_JMP for x in rf), "flat turn has no JMP")
    chk(sum(1 for x in rf if x.opcode == SF.OP_EMB) == 3 + 3 - 1,
        "flat turn has P+N-1 = 5 bodies")
    chk(sum(1 for x in rf if x.opcode == SF.OP_AMAXL) == 3,
        "flat turn: 3 full bodies push tokens (2 lite prefill steps)")

    # always-seed rule: the committed stream skips a seed, we never do
    n_seed = sum(1 for x in rf
                 if x.opcode == SF.OP_CSRWR
                 and x.target == SF.csr_seq_xrf(SF.XRF_TOK))
    chk(n_seed == 3, "flat turn seeds XRF[3] once per PROMPT token (always)")

    # guards
    for bad, why in (((0, 500, 20), "context guard T+(P-1)+N < 512"),
                     ((490, 4, 30), "context guard near the KV wrap")):
        try:
            tc.context_guard(*bad)
            chk(False, why + " should have raised")
        except ChatSeqError:
            chk(True, why)
    try:
        tc.build_step(0, XRF_POS_MAX + 1, "full")
        chk(False, "pos > XRF_POS_MAX should have raised")
    except ChatSeqError:
        chk(True, f"pos > {XRF_POS_MAX} refused in pos_mode='xrf'")
    tl = TurnCompiler(prefix, pos_mode="ldc")
    im = tl.build_step(5, 300, "full")
    rr = im.records()
    a = (int(rr[3 + POS_LDC_REC_OFFSETS[0]].len_or_addr_hi) << 32) \
        | int(rr[3 + POS_LDC_REC_OFFSETS[0]].addr_lo)
    chk(a == POS_BLOB_BASE + 300 * POS_STRIDE and rr[1].imm32 == 0,
        "pos_mode='ldc' patches the LDC base and zeroes XRF[4]")

    # XRF[4] has exactly ONE consumer class in the whole artifact, so
    # rewriting those six addresses is a COMPLETE substitute for it.
    cons = [(SF.OP_NAME.get(x.opcode, hex(x.opcode)))
            for x in tc.T.recs
            if x.opcode in (SF.OP_CSRWR, SF.EXT_LDC, SF.OP_MOVY)
            and x.ind != SF.IND_NONE and x.xrf == SF.XRF_POS]
    chk(set(cons) == {"LDC*"} and len(cons) == 24,
        f"XRF[4] is read by 24 LDCs and nothing else ({set(cons)})")

    # and the two modes address the SAME bytes for any reachable position
    same = True
    for p in (0, 1, 42, XRF_POS_MAX):
        xr = tc.build_step(0, p, "full").records()
        ld = tl.build_step(0, p, "full").records()
        for j, o in enumerate(POS_LDC_REC_OFFSETS):
            a = (int(xr[3 + o].len_or_addr_hi) << 32) | int(xr[3 + o].addr_lo)
            b = (int(ld[3 + o].len_or_addr_hi) << 32) | int(ld[3 + o].addr_lo)
            same = same and (a + p * POS_STRIDE == b)
    chk(same, "pos_mode 'xrf' (base + XRF[4]) and 'ldc' (patched base) "
              "resolve to identical blob addresses")

    lay = tc.blob_layout()
    chk(lay["total_bytes"] == CONST_BYTES + T_MAX * POS_STRIDE,
        f"blob layout {lay['total_bytes']} B")
    res = tc.resident_images()
    tot = sum(im.nbytes for (_n, _o, im) in res)
    chk([n for (n, _o, _i) in res] == ["session", "lite", "full"]
        and all(o % 4096 == 0 for (_n, o, _i) in res),
        f"resident set: session/lite/full, {tot} B, 4 KiB aligned "
        f"({[(n, o, im.nrec) for (n, o, im) in res]})")
    chk("weights" in tc.host_meta() and "chat_seq" in tc.host_meta(),
        "host_meta carries the committed weight manifest for seq_run")

    # embedding row stride, at EVERY geometry ref/ can be pointed at.
    # model_select freezes FABLE5_MODEL at import, so the geometry that is
    # not the current one needs a second interpreter.  This is the §7.2
    # defect-A regression: at H=2048 the pre-fix reader never raised.
    import subprocess
    import model_select as MS
    for tag in MS.MODELS:
        p = subprocess.run([sys.executable, os.path.abspath(__file__),
                            "--emb-geom"],
                           env=dict(os.environ, FABLE5_MODEL=tag),
                           capture_output=True, text=True)
        tail = (p.stdout.strip() or p.stderr.strip()).splitlines()
        chk(p.returncode == 0, f"emb geometry at FABLE5_MODEL={tag} "
                               f"[{tail[-1] if tail else 'no output'}]")

    log(f"SELFTEST: {'PASS' if ok else 'FAIL'}")
    return ok


# ======================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prefix", default=DEFAULT_PREFIX)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--selftest", action="store_true",
                    help="template/hole/guard invariants (seconds)")
    ap.add_argument("--emb-geom", action="store_true",
                    help="embedding row-stride round-trip at the geometry "
                         "FABLE5_MODEL selects (--selftest runs this for "
                         "every model, one interpreter each)")
    ap.add_argument("--a1", action="store_true",
                    help="gate A1: compiled schedule == committed golden")
    ap.add_argument("--a2", action="store_true", help="gate A2: position blob")
    ap.add_argument("--a3", action="store_true",
                    help="gate A3: 4 fresh prompts vs layer_fixed (SLOW)")
    ap.add_argument("--ntok", type=int, default=3)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    if a.emb_geom:                       # the one mode that loads no artifact
        raise SystemExit(0 if emb_geometry_selftest() else 1)
    if not (a.selftest or a.a1 or a.a2 or a.a3):
        a.selftest = True
    rep, ok = {}, True
    if a.selftest:
        ok &= selftest(a.prefix)
    if a.a2:
        g, rep["a2"] = gate_a2(a.prefix)
        ok &= g
    if a.a1:
        g, rep["a1"] = gate_a1(a.prefix, a.base)
        ok &= g
    if a.a3:
        g, rep["a3"] = gate_a3(ntok=a.ntok, prefix=a.prefix, base=a.base)
        ok &= g
    if a.json:
        with open(a.json, "w") as f:
            json.dump(rep, f, indent=1, default=str)
    print("seq_chat: " + ("PASS" if ok else "FAIL"))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
