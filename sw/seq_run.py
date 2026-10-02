#!/usr/bin/env python3
"""seq_run.py — host-side runner for the on-chip command sequencer (rung 1).

    uv run python seq_run.py --prefix ../tb/scripts/w4/model_v2_s1.e --dry-run
    uv run python seq_run.py --prefix ../tb/scripts/w4/model_v2_s1.e

What it does, in order:

  0. IDENTITY  the board's identity gate (Dev), and — on a SEQ run — the
               DEVICE's capability set, read once from SEQ_CAPS (SEQ 0x64,
               docs/SEQ_ISA.md v2.3 B17.0; hwmap.seq_caps_set; the EMPTY set
               on every pre-round bitstream, which reads 0xDEADC0DE there).
               --dry-run never touches the SEQ window: its set is --caps
               (default empty); a non-empty --caps validates + relocates
               ONLY and uploads nothing.  NEVER the manifest's.
  1. LOAD      <prefix>.seq / .seqdata.bin / .seq.json, check both sha256s
               against the metadata and run ref/seq_format.validate_stream
               AT THAT CAPABILITY SET (Task SR6): a stream using a feature
               the device lacks (an R1 masked FENCE on build_041) is refused
               here, before any DMA, whatever its manifest says; a manifest
               `caps` list that is not a subset of the set is refused by
               name.  relocate() re-validates the relocated stream at the
               same set.  Both validations also run at the DEVICE's MVGO
               SHAPE layout, hwmap.shape_isa_for_version(VERSION) (SR11a
               fix round 2: bit 29 is w8 on build_034/035, XBANK on
               build_041+); --dry-run states --shape-isa or none, and with
               none a SHAPE word with bit 29/30 set is refused.  A SEQ
               run also REQUIRES the manifest's `shape_isa` key (SR13b;
               layout_key_check): keyless only for the frozen pre-G3
               streams (FROZEN_PRE_G3_STREAMS) at an isa=1 device.  An r2
               stream (B17.2 bank fields) loads only where the device's
               set has R2 (0xFAB1CA03), whatever its manifest claims.
  2. PLAN     pack the weight images with sw/hwmap.py:plan_weights (the
               SAME layout the emitter's MVGO records were built against, and
               the plan is ASSERTED equal to meta["weights"]), and place the
               stream + the LDC constant blob at hwmap.SEQ_STREAM_BASE /
               hwmap.SEQ_DATA_BASE.
  3. RELOCATE  the emitter bakes ABSOLUTE chan-0 addresses (ref/seq_format.py
               _Blob.base = SEQ_DATA_BASE = 0x8000_0000, on_embed =
               HW.EMB_BASE, on_matvec = plan_weights_from_wids ->
               HW.W_BASE), so every LDC
               (and EMB, if it ever moves) record is rebased by the difference
               between where the emitter said the blob lives and where this
               runner actually puts it.  MVGO WBASEs are ASSERTED, never
               patched: if the host pack and the stream disagree the stream is
               simply wrong for these weights.
  4. UPLOAD    weights + embedding + blob + relocated stream over h2c, each
               range READ BACK over c2h and compared (sha256 per range).
  5. RUN       BASE/LEN/ENTRY -> START -> poll STATUS -> drain OUT_FIFO.
               While SEQ_STATUS.busy the host touches NOTHING but the SEQ's own
               CSR block (docs/SEQ_ISA.md "Arbitration + clocks").
  6. VERIFY    generated tokens vs <prefix>.seq.json "expect_tokens", with a
               first-divergence report; optionally the whole post-halt
               architectural state against a <prefix>.chip golden
               (tb/scripts/gen_seq_chip_vectors.py), read through the layer
               CSRs AFTER the sequencer has halted.

BOARD SAFETY
  * This tool NEVER programs the FPGA, never touches flash, never runs sudo
    and never calls pcie_helper.sh.
  * The identity gate refuses to touch anything unless MAGIC / CALIB / the
    layer IDENT / all four matvec IDENTs read back exactly.
  * SEQ CSRs (0x6000) DO NOT EXIST before build_029.  Every access to them is
    gated on VERSION == EXPECTED_SEQ_VERSION (or the SEQ_VERSIONS row a
    caller NAMES with --expect-version / $FABLE5_SEQ_EXPECT_VERSION) *and*
    the seq IDENT, and
    --dry-run performs ZERO accesses to that window — so --dry-run is the
    mode that is safe on the currently resident bitstream.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np

SW_DIR = os.path.dirname(os.path.abspath(__file__))
REF_DIR = os.path.join(os.path.dirname(SW_DIR), "ref")
for _p in (SW_DIR, REF_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import board_lock as BL                                        # noqa: E402
import hwmap as HW                                             # noqa: E402
from hwmap import (                                            # noqa: E402
    R_MAGIC, R_VERSION, R_CALIB, MAGIC, CALIB_ALL,
    R_IDENT, MV_IDENT0, mv_base,
    L_STAT, L_SPTR, L_SWIN, L_EOUT, L_TCNT, L_IDENT, L_AMAXI, L_AMAXV,
    L_LAYER, L_XRFI, L_XRFD, LAYER_IDENT, SCRATCH_WORDS, SCRATCH_WORDS_BUILT,
    L_SB_DN, L_SB_KV, L_SB_CV, STATE_BASE_UNIT, STATE_DN_LAYER,
    STATE_CV_STRIDE, state_dn_witnesses,
    S_CTRL, S_STATUS, S_BASE_LO, S_BASE_HI, S_LEN, S_PC, S_OUT_FIFO,
    S_OUT_CNT, S_TCNT_SEQ, S_ENTRY, S_IDENT, S_PERF_CYC, S_PERF_REC,
    S_PERF_AXW, S_PERF_AXR, S_PERF_FST, S_XRF0, s_xrf, S_EMBLOG2,
    SEQ_EMBLOG2_RST, SEQ_CSR_UNMAPPED, EMB_ROW_BYTES_DEFAULT, seq_emb_log2,
    SEQ_IDENT, SEQ_XRF_N, SEQ_OUT_DEPTH, SEQ_CTRL_START, SEQ_CTRL_ABORT,
    SEQ_ST_BUSY, SEQ_OUT_VALID, SEQ_OUT_TOK_MASK, SEQ_PERF_XRF_OVF,
    SEQ_ST_OUTCNT_MASK, SEQ_ST_OF_OVF,
    seq_status, seq_err_name,
    CH_STRIDE, W_BASE, EMB_BASE, SEQ_STREAM_BASE, SEQ_DATA_BASE,
    SEQ_STREAM_MAX, SEQ_DATA_MAX, SEQ_REC_BYTES, SEQ_ALIGN, ACLK_HZ,
)
import seq_format as SF                                        # noqa: E402
from hwmap import plan_weights                                  # noqa: E402
from tok_meter import split_rows                               # noqa: E402
# split_rows is the PROVEN 4-chan row partition (tok_meter.py:81-95, measured
# 12.23 tok/s): contiguous rows across nch channels, the first nrows%nch
# channels taking one extra row.  Importing it (rather than re-deriving it)
# guarantees the host upload lands each engine's rows at the SAME channel-
# local byte offset the emitter's MVGO WBASEs point at.


# ======================================================================
# >>>>>>>>>>>>>>>>>  UPDATE ON EVERY NEW RESIDENT NETLIST  <<<<<<<<<<<<<
# ======================================================================
# The csr_0 VERSION word of the netlist that must be resident on the board.
# It is the low 32 bits of that netlist's git hash, exactly as
# synth/scripts/create_project.tcl stamps it into csr_block.  Keep it in
# lockstep with sw/infer.py:EXPECT_VERSION and with docs/USAGE.md §1.
# History: 0x67A943BD build_028 (pre-seq_0), 0x33D720E5 build_033,
# 0x4F908DF2 build_034 (R-b, shipped under a -0.025 waiver).
#
# Set it to None only for a bitstream with no sequencer:
#   * --dry-run keeps working (DDR uploads + readback verify only, and it
#     performs no access whatsoever to the 0x6000 window), and
#   * any attempt to touch a SEQ CSR aborts with an explicit message.
EXPECTED_SEQ_VERSION = 0xC973C18A  # build_041_ckr2_AltSpreadLogic_high (9B state
#   spill), READ BACK off the board at evidence/qwen9b/g6/003_identity_9b.log.
# ======================================================================

# Bitstreams WITHOUT a sequencer (pre-build_029, e.g. build_028).  They have
# no sequencer; it is listed only so --dry-run can say "yes, I know what this
# is, and I am deliberately not touching 0x6000".
KNOWN_NO_SEQ_VERSIONS = {
    0x67A943BD: "build_028_rr_SSI_HighUtilSLRs (no seq_0)",
}

# Every sequencer bitstream a tool may be TOLD to expect -> (SHAPE ISA, what
# it is).  This is seq_run's counterpart of sw/hwmap.SHAPE_ISA_BY_VERSION for
# the sequencer path (which never packs a SHAPE word itself: the emitter did).
# Only EXPECTED_SEQ_VERSION is ever a default; every other row is admitted
# ONLY when the caller names it -- `--expect-version <hash>` on this tool, or
# FABLE5_SEQ_EXPECT_VERSION=<hash> in the environment of a tool that builds
# Dev() itself (sw/chat_seq.py, evidence/qwen9b/g6/g6_census.py and its
# copies).  An unlisted hash is refused at parse time (a typo guard), and the
# gate refuses a programmatic expect_version outside this table.
# BM1-T4prep (2026-09-24): build_042_bm1 is the idle-counter bitstream
# (docs/superpowers/specs/2026-09-24-board-idle-counters-design.md §2.2
# item 2); its VERSION is the build tree's hash, stamped by create_project
# at evidence/qwen9b/bm/n24_T3_launch_build_042_bm1.log ("9b588e78").  Its
# SHAPE decode is build_041's (the BM1 RTL adds registers only).
# Task SR7 (controller addendum; SR6 judgment call 9, review M-2): every row
# also carries the SEQ_CAPS word (SEQ 0x64, docs/SEQ_ISA.md v2.3 B17.0) the
# bitstream is EXPECTED to read, and the identity gate compares the device's
# word against it exactly as it compares VERSION: a mismatch closes the SEQ
# gate, so nothing is uploaded.  Pre-round bitstreams read the unmapped value
# there (HW.SEQ_CSR_UNMAPPED, the read mux default); the words are taken from
# sw/hwmap.py, never re-typed.
SEQ_VERSIONS = {
    0xC973C18A: (HW.SHAPE_ISA_9B,
                 "build_041_ckr2_AltSpreadLogic_high (shipped 9B; default)",
                 HW.SEQ_CSR_UNMAPPED),
    0x9B588E78: (HW.SHAPE_ISA_9B,
                 "build_042_bm1 (BM1 idle counters; admitted only when named)",
                 HW.SEQ_CSR_UNMAPPED),
    # Task SR7 (evidence/qwen9b/sr/SR7_R1_BUILD.md): the R1 build, VERSION =
    # the launch tree's hash (evidence/qwen9b/sr/n701_SR7_launch_build_044_r1.log),
    # signed off on build_044_r1_incr; SHAPE decode unchanged by R1 (the FENCE
    # mask only).  build_044_r1_incr_bm1ref shares this VERSION (same netlist)
    # and is told apart by its bitstream sha256 only.
    0xE3C2FF1E: (HW.SHAPE_ISA_9B,
                 "build_044_r1_incr (R1 FENCE mask + BM1 counters; admitted "
                 "only when named)",
                 HW.seq_caps_word({"R1"})),
    # SR11a fix round 2: the FROZEN 2B W8 bitstream (evidence/qwen2b/rd/
    # RD_GATE.md T4's seq_run4, evidence/qwen2b/rd/rd_chat2b.sh), whose
    # SHAPE word is the pre-G3 layout (bit 29 = w8).  Its SEQ 0x64 is an
    # unmapped read: the pre-round read mux answers 32'hDEAD_C0DE
    # (rtl/seq_unit.sv at 54443b9, the s_axil_rdata default).
    0x54443B9F: (HW.SHAPE_ISA_PRE_G3,
                 "build_035_fp2a_exc_po (frozen 2B W8, isa=1 SHAPE; admitted "
                 "only when named)",
                 HW.SEQ_CSR_UNMAPPED),
}   # + build_045_r2_incr (SR14), assigned at the end of this module
assert EXPECTED_SEQ_VERSION in SEQ_VERSIONS

# SR13b (the SR11a round-3 re-review's keyless path; controller addendum):
# the ONLY artifacts a board run admits WITHOUT a manifest `shape_isa` key.
# ref/seq_format.py writes the key for every stream it emits except the
# BYTELOCKED tags (0.8b / 2b, gen_layer_script.BYTELOCKED_TAGS), so a
# post-G3 (isa=2) 0.8b/2b artifact is keyless too -- and named as build_035
# (isa=1) it would validate at isa=1 and upload words that decode as
# garbage.  So a SEQ run requires the key, except for these three FROZEN
# pre-G3 (isa=1) streams, admitted keyless and only at an isa=1 device, by
# their stream sha256 (each is the stream that ran on build_035 in
# evidence/qwen2b/rd/: seq_run_build035.json, seq_run4_build035.json,
# seq_run4_2b_build035.json).
FROZEN_PRE_G3_STREAMS = {
    "a69864d25b6b129a4d6c74b3c78dfcbedf1edce219d32cc05d05bc54f444aaf1":
        "tb/scripts/w4/model_v2_s1.e (0.8B 1-chan; chat_seq TEMPLATE_SHA256)",
    "e102e2df0835097d0d622cd17109b9cbfea1ab4e78818bcddf3873ec6d8ac933":
        "tb/scripts/w4/model_v2_s1.e4 (0.8B 4-chan; RD seq_run4)",
    "fa8d9349cf1d0aa618ab79e0a2565dd89adbb147b665cb49b582d83c95b05bcb":
        "tb/scripts/w5/model_w8_2b_s1.e (2B W8; RD_GATE T4, rd_chat2b.sh)",
}
EXPECT_VERSION_ENV = "FABLE5_SEQ_EXPECT_VERSION"
EXPECT_DEFAULT = object()     # Dev(expect_version=...) was not given


def parse_expect_version(text):
    """`--expect-version` / FABLE5_SEQ_EXPECT_VERSION -> int.  Takes the
    8-hex git hash with or without 0x; refuses any hash not in SEQ_VERSIONS."""
    t = str(text).strip()
    h = t[2:] if t[:2].lower() == "0x" else t
    # strict: exactly 1..8 hex digits -- a longer string is REFUSED, never
    # masked (ffffffff9b588e78 must not parse as BM1; fix round 1)
    if not (1 <= len(h) <= 8
            and all(c in "0123456789abcdefABCDEF" for c in h)):
        raise ValueError(f"expect-version {text!r} is not a VERSION "
                         f"(1..8 hex digits, optional 0x)")
    v = int(h, 16)
    if v not in SEQ_VERSIONS:
        raise ValueError(
            f"expect-version {v:#010x} is not a known sequencer bitstream "
            f"(known: " + ", ".join(f"{k:#010x} {r[1]}" for k, r
                                    in sorted(SEQ_VERSIONS.items()))
            + ") -- add its row to sw/seq_run.SEQ_VERSIONS, do not guess")
    return v


def resolve_expect_version(expect_version=EXPECT_DEFAULT, env=None):
    """An explicit argument wins; else FABLE5_SEQ_EXPECT_VERSION if set and
    non-empty; else the shipped EXPECTED_SEQ_VERSION."""
    if expect_version is not EXPECT_DEFAULT:
        return expect_version
    env = os.environ if env is None else env
    txt = env.get(EXPECT_VERSION_ENV, "").strip()
    if txt:
        return parse_expect_version(txt)
    return EXPECTED_SEQ_VERSION


# BM1 idle counters — docs/SEQ_ISA.md B16 (v2.2), rtl/seq_unit.sv's 0x100
# block.  Host-read-only; cleared by START with the PERF_* registers, counted
# while busy_r, frozen at HALT; read by Dev.seq_bm() after HALT.  Offsets are
# relative to S_BM_IDENT (SEQ 0x100).  0x12C and 0x138..0x1FC read 0.
S_BM_IDENT = HW.SB + 0x100
SEQ_BM_IDENT = 0xFAB1B301
SEQ_BM_REGS = (
    ("mvany", 0x04),       # 0x104 any matvec engine busy
    ("mv0", 0x08),         # 0x108 matvec chan 0 engine busy
    ("mv1", 0x0C),         # 0x10C
    ("mv2", 0x10),         # 0x110
    ("mv3", 0x14),         # 0x114
    ("fence", 0x18),       # 0x118 mover busy on a FENCE (drain wait)
    ("mvwork", 0x1C),      # 0x11C mover busy on MOVX/MVGO/MOVY
    ("mvwork_any", 0x20),  # 0x120 mover work while any engine busy
    ("imover", 0x24),      # 0x124 issue FSM in I_MOVER
    ("steps", 0x28),       # 0x128 OP_EMB records dispatched (events)
    ("movx", 0x30),        # 0x130 mover busy on MOVX (OV1's split)
    ("movy", 0x34),        # 0x134 mover busy on MOVY (OV1's split)
)

DEFAULT_TIMEOUT = 120.0          # s; model_v2_s1.e is ~0.73 s of device time
POLL_S = 0.002
DMA_CHUNK = 64 << 20


class SeqError(RuntimeError):
    pass


# ======================================================================
# artifacts + planning  (PURE PYTHON — unit-tested by --selftest)
# ======================================================================
def derive_base(prefix):
    """Generator-artifact prefix for a SEQ prefix.

    The emitter writes `<base>.<variant>.seq` (SEQ_EMIT=.../model_v2_s1.e)
    beside the generator's `<base>.txt` / `<base>.weights.json` /
    `<base>_w*.bin` / `<base>.emb.bin`: the base is the SEQ prefix minus its
    last dotted
    component — unless the SEQ prefix already carries the artifacts itself.
    """
    if os.path.exists(prefix + ".weights.json"):
        return prefix
    d, name = os.path.split(prefix)
    head, dot, _tail = name.rpartition(".")
    if not dot:
        return prefix
    return os.path.join(d, head)


def manifest_caps_check(meta, caps, what="stream"):
    """SR6 (SEQ_ISA v2.3 B17.0 ADMISSION): a manifest's `caps` list is
    INFORMATIONAL — admission is keyed by the device's set — but it must be
    a SUBSET of that set; a claim the device does not back is refused BY
    NAME (SeqError).  A manifest without the key claims nothing."""
    if "caps" not in meta:
        return frozenset()
    try:
        claim = HW.seq_caps_check(meta["caps"])
    except ValueError as e:
        raise SeqError(f"{what}: manifest caps {meta['caps']!r}: {e}")
    extra = sorted(claim - frozenset(caps))
    if extra:
        raise SeqError(
            f"{what}: its manifest claims capability "
            f"{', '.join(extra)} which the device's set "
            f"{sorted(caps) or '{}'} lacks (docs/SEQ_ISA.md B17.0 "
            f"ADMISSION: the manifest's caps must be a subset of the "
            f"device's)")
    return claim


def layout_key_check(meta, stream_sha, shape_isa, what="stream"):
    """SR13b (the keyless path; SR11a round-3 re-review, controller
    addendum): on a BOARD admission the artifact must DECLARE its SHAPE
    layout (meta["shape_isa"]); a declared layout is compared with the
    device's by the caller (Artifacts, ref/seq_chat.Templates).  The one
    exemption is a FROZEN pre-G3 stream (FROZEN_PRE_G3_STREAMS, by its
    stream sha256) at an isa=1 device (build_034/035).  A keyless artifact
    anywhere else is refused BY NAME (SeqError) -- a post-G3 0.8b/2b
    artifact is written without the key (ref/seq_format.py, BYTELOCKED
    tags) and its layout cannot be told from its records.  Returns
    "declared" or the frozen stream's description."""
    if "shape_isa" in meta:
        return "declared"
    frozen = FROZEN_PRE_G3_STREAMS.get(stream_sha)
    if frozen is not None and shape_isa is not None \
            and int(shape_isa) == HW.SHAPE_ISA_PRE_G3:
        return frozen
    dev = "unstated" if shape_isa is None else f"isa={int(shape_isa)}"
    raise SeqError(
        f"{what}: the manifest has no `shape_isa` key (the SHAPE layout the "
        f"stream is encoded in), required on a board run: the device decodes "
        f"{dev} and a keyless artifact's layout cannot be told from its "
        f"records (a post-G3 0.8b/2b artifact is written without the key; "
        f"only the frozen pre-G3 streams in sw/seq_run.FROZEN_PRE_G3_STREAMS"
        f" are admitted keyless, at an isa=1 device) -- re-emit it, or add "
        f"the key only if you KNOW its layout (docs/SEQ_ISA.md B17.2)")


class Artifacts(object):
    """<prefix>.seq + .seqdata.bin + .seq.json, hash-checked and validated.

    `caps` (Task SR6) is the capability set the stream is validated AT: the
    DEVICE's (Dev.seq_caps()) when a board will run it, else the caller's
    explicit board-free set; the default, the empty set, is today's rules
    (every pre-SR6 caller).  Never the manifest's: its `caps` list is only
    checked to be a subset (manifest_caps_check).

    `shape_isa` (SR11a fix round 2) is the SHAPE layout the stream is
    validated at: the DEVICE's, HW.shape_isa_for_version(VERSION), on a
    board run, else the caller's explicit --shape-isa.  None states no
    layout, and ref/seq_format then refuses MVGO SHAPE bits 29/30 (bit 29
    is w8 on build_034/035 but XBANK on build_041+; docs/SEQ_ISA.md
    B17.2), so a frozen isa=1 W8 artifact needs the layout stated."""

    def __init__(self, prefix, base=None, caps=frozenset(), shape_isa=None,
                 require_layout_key=False):
        self.prefix = prefix
        self.caps = HW.seq_caps_check(caps)
        self.shape_isa = shape_isa
        self.base = derive_base(prefix) if base is None else base
        self.meta = json.load(open(prefix + ".seq.json"))
        self.stream = open(prefix + ".seq", "rb").read()
        self.blob = open(prefix + ".seqdata.bin", "rb").read()
        m = self.meta
        got = hashlib.sha256(self.stream).hexdigest()
        if got != m["stream_sha256"]:
            raise SeqError(f"{prefix}.seq sha256 {got[:16]} != metadata "
                           f"{m['stream_sha256'][:16]}")
        got = hashlib.sha256(self.blob).hexdigest()
        if got != m["seqdata_sha256"]:
            raise SeqError(f"{prefix}.seqdata.bin sha256 {got[:16]} != "
                           f"metadata {m['seqdata_sha256'][:16]}")
        if len(self.stream) != m["stream_bytes"] or \
                len(self.stream) != m["nrec"] * SEQ_REC_BYTES:
            raise SeqError(f"{prefix}.seq is {len(self.stream)} B, metadata "
                           f"says {m['nrec']} records "
                           f"({m['nrec'] * SEQ_REC_BYTES} B)")
        self.recs = SF.unpack_stream(self.stream)
        # SR11a fix round 3 (I2; the mirror of ref/seq_chat.Templates): an
        # artifact that DECLARES its SHAPE layout must agree with the one it
        # is validated at (the device's on a SEQ run, --shape-isa on a
        # dry-run) — a 9B artifact named at build_035 would otherwise
        # validate at isa=1 and upload words that decode as garbage.
        # Refused before any DMA.  SR13b: on a BOARD run
        # (require_layout_key, the SEQ-run path of main) an artifact with no
        # key is refused unless it is a frozen pre-G3 stream at an isa=1
        # device (layout_key_check); elsewhere (--dry-run, the evidence
        # tools) it is validated at the stated layout alone.
        if require_layout_key:
            layout_key_check(m, hashlib.sha256(self.stream).hexdigest(),
                             self.shape_isa,
                             what=f"{prefix}.seq.json")
        if self.shape_isa is not None and "shape_isa" in m \
                and int(m["shape_isa"]) != int(self.shape_isa):
            raise SeqError(
                f"{prefix}.seq.json declares SHAPE isa={int(m['shape_isa'])} "
                f"but it is being validated at isa={int(self.shape_isa)} (the "
                f"device's / --shape-isa layout): wrong bitstream for this "
                f"artifact (docs/SEQ_ISA.md B17.2)")
        # the VALIDATOR first (it is the guard: its refusal names the record
        # the device cannot run), then the manifest's claim (a subset check)
        SF.validate_stream(self.recs, caps=self.caps,
                           shape_isa=self.shape_isa)
        manifest_caps_check(m, self.caps, what=f"{prefix}.seq.json")
        # R-b: the manifest carries the embedding row stride (2*H) when the
        # generator wrote one; an older artifact has no key and means 2048.
        self.manifest, mmeta = HW.load_weights_manifest(self.base)
        self.emb_row_bytes = mmeta["emb_row_bytes"]
        # S3 (SEQ_ISA v2.1): the DDR state region's plan and the conv
        # images the host uploads into it.  Both are None for a pre-S3
        # artifact, which emits no SLD/SST for a region to serve.
        self.state = mmeta["state"]
        self.conv_images = mmeta["conv_images"]
        self.wdir = os.path.dirname(os.path.abspath(self.base)) or "."
        self.embf = self.base + ".emb.bin"
        if not os.path.exists(self.embf):
            self.embf = None

    @property
    def nrec(self):
        return len(self.recs)

    def halt_pc(self):
        """Record index of the LAST HALT — what a cleanly halted PC reads."""
        pcs = [i for i, r in enumerate(self.recs) if r.opcode == SF.OP_HALT]
        if not pcs:
            raise SeqError("stream has no HALT record")
        return pcs[-1]


def expected_tokens(meta):
    """The token ids the OUT FIFO must produce, in order.

    The emitter appends one entry per AMAXL at EMISSION time (before
    `_try_loop` collapses identical trailing bodies), so this list is the
    DYNAMIC expectation — `len(expect_tokens)` is steps, not the number of
    AMAXL records left in the stream.
    """
    return [int(t) for t in meta.get("expect_tokens", [])]


def plan_ddr(meta, stream_bytes, blob_bytes, chan=0,
             stream_base=SEQ_STREAM_BASE, data_base=SEQ_DATA_BASE,
             emb_base=EMB_BASE):
    """Where every SEQ artifact goes, and by how much the stream moves.

    Channel-local addresses plus `ddr_off = chan * CH_STRIDE`, because
    seq_0/m_axi has the SAME 16 GiB four-channel view XDMA M_AXI has
    (synth/scripts/create_project.tcl), while mvchan_c/m_axi sees its own
    channel at 0 — so MVGO WBASEs stay channel-local and the fetch / LDC /
    EMB addresses do not.

    `chan` is the FETCH channel: the single channel seq_0/m_axi reads the
    record stream, the LDC const blob and the embedding table from.

    Weight placement depends on meta["nch"] (default 1):
      * nch == 1 — the classic single-channel stream.  Its MVGO records
        address matvec_chan `meta["chan"]`, whose DDR is channel
        `meta["chan"]`, so the weight image and the fetch path share that
        one channel and --chan must select it.
      * nch  > 1 — a row-split stream (rung 1b).  Its MVGO records address
        matvec_chan 0..nch-1, each of which reads its OWN DDR channel at
        offset 0, so every weight image is ROW-SPLIT across channels
        0..nch-1 (split_rows) while the fetch path stays on the single
        channel `meta["chan"]`.  WBASEs are still channel-local; only the
        host DMA adds `c * CH_STRIDE` per weight quarter (done in upload()).
    """
    if chan not in (0, 1, 2, 3):
        raise SeqError(f"DDR fetch channel {chan} out of range")
    nch = int(meta.get("nch", 1))
    if nch not in (1, 2, 3, 4):
        raise SeqError(f"meta nch={nch} out of range (1..4)")
    mchan = int(meta.get("chan", 0))
    if nch == 1:
        if mchan != chan:
            raise SeqError(
                f"the stream was emitted for engine channel {mchan} "
                f"but --chan is {chan}: MVGO records address matvec_chan "
                f"{mchan}, whose DDR is channel {mchan}")
        weight_chans = [chan]
    else:
        # A row-split stream fetches from the emitter's single `chan` while
        # its weights live on channels 0..nch-1.  --chan selects the fetch
        # channel and must match the emitter's.
        if mchan != chan:
            raise SeqError(
                f"the {nch}-channel stream fetches from channel {mchan} "
                f"(the emitter's chan) but --chan is {chan}; pass "
                f"--chan {mchan}")
        weight_chans = list(range(nch))
    for name, b in (("stream", stream_base), ("blob", data_base)):
        if b % SEQ_ALIGN:
            raise SeqError(f"SEQ {name} base {b:#x} is not {SEQ_ALIGN}B "
                           f"aligned")
    if stream_bytes > SEQ_STREAM_MAX:
        raise SeqError(f"stream is {stream_bytes} B, window at "
                       f"{stream_base:#x} is {SEQ_STREAM_MAX} B")
    if blob_bytes > SEQ_DATA_MAX:
        raise SeqError(f"const blob is {blob_bytes} B, window at "
                       f"{data_base:#x} is {SEQ_DATA_MAX} B")
    regions = [("stream", stream_base, stream_bytes),
               ("seqdata", data_base, blob_bytes)]
    for i, (na, a, la) in enumerate(regions):
        for (nb, b, lb) in regions[i + 1:]:
            if la and lb and a < b + lb and b < a + la:
                raise SeqError(f"SEQ {na} [{a:#x},{a + la:#x}) overlaps "
                               f"{nb} [{b:#x},{b + lb:#x})")
    ddr_off = chan * CH_STRIDE
    return {
        "chan": chan,                               # the FETCH channel
        "nch": nch,                                 # weight row-split width
        "weight_chans": weight_chans,               # channels weights land on
        # rung 4 S4: {} for every pre-rung-4 / nch==1 stream (all contiguous)
        "weight_layout": dict(meta.get("weight_layout") or {}),
        "ddr_off": ddr_off,
        "stream_base": stream_base,
        "data_base": data_base,
        "emb_base": emb_base,
        "seq_base": ddr_off + stream_base,          # what SEQ_BASE_LO/HI get
        "data_delta": (ddr_off + data_base) - int(meta["seq_data_base"]),
        "emb_delta": (ddr_off + emb_base) - int(meta["emb_base"]),
        "stream_bytes": stream_bytes,
        "blob_bytes": blob_bytes,
    }


def layout_of(meta, wid):
    """The placement rung 4 S4 recorded for one weight image.

    Streams older than rung 4 (and every nch==1 stream) carry no
    "weight_layout" key at all -> LAYOUT_CONTIG, i.e. rung 1b's behaviour,
    bit-for-bit.
    """
    wl = (meta or {}).get("weight_layout") or {}
    by = wl.get("by_wid") or {}
    return by.get(str(wid), wl.get("default", SF.LAYOUT_CONTIG))


def is_repacked(meta):
    """True when the stream's MVGO WBASEs are PER-CHANNEL (R-c).

    Absent == false == the nch-independent pack every artifact frozen before
    R-c encodes (at nch=1 AND at nch=4): one full-image span per wid that
    every channel reserves, addressed by GLOBAL row.
    """
    return bool((meta or {}).get("weight_repack", False))


def plan_weights_for(manifest, wdir, meta=None):
    """The weight pack THIS stream's MVGO WBASEs encode.

    Delegates to hwmap.plan_weights — the one authority — after reading the
    stream's own placement out of `meta`: nch, per-wid layout and the repack
    flag.  Returns what plan_weights returns: `({wid: base}, top)` with int
    bases for the nch-independent pack, `({wid: [base per chan]}, (top per
    chan))` for the repacked one.
    """
    nch = int((meta or {}).get("nch", 1))
    if not is_repacked(meta):
        return plan_weights(manifest, wdir)
    depth = int(((meta or {}).get("weight_layout") or {})
                .get("chunk_rows", SF.CHUNK_ROWS))

    def rows_of(wid, nrows):
        return SF.chan_rows(nrows, nch, layout_of(meta, wid), depth)

    return plan_weights(manifest, wdir, nch=nch, rows_of=rows_of)


def _chan_base(base, i):
    """Channel i's base of one image — `base` is per-channel (repack) or the
    single span every channel shares (the nch-independent pack)."""
    return base[i] if isinstance(base, (list, tuple)) else base


def fmt_top(top):
    """`top` printed: one address, or one per channel when repacked."""
    if isinstance(top, (list, tuple)):
        return "/".join(f"{t:#x}" for t in top)
    return f"{top:#x}"


def plan_weight_split(manifest, wbase_of, nch, weight_chans, meta=None):
    """The per-channel uploads for every weight image (PURE).

    For image `wid` (nrows, stride), `seq_format.weight_pieces` returns the
    (channel index, r0, nrows) pieces the EMITTER's MVGO WBASEs imply, so
    the host cannot drift from the stream:

      * LAYOUT_CONTIG (rung 1b, and every non-head matvec): one contiguous
        row-quarter per channel — split_rows, tok_meter.py:308-320 exactly.
      * LAYOUT_ILV (rung 4 S4, the LM head): one piece per 2048-row engine
        chunk, chunk j on channel j % nch, so a channel's rows are STRIDED
        through the image instead of contiguous.

    Either way a piece is the file slice [r0*stride, (r0+n)*stride) and
    lands at

        abs_addr = chan * CH_STRIDE + local_addr
        local_addr = <that channel's base for wid> + row_off*stride

    `local_addr` is exactly what that channel's MVGO WBASE points at
    (channel-local, row-aligned inside the packed image), so the bytes each
    engine reads are the bytes the host wrote.  Zero-row channels
    (nrows < nch) are dropped.  Returns a list of dicts, one per write.

    R-c: under the PER-CHANNEL REPACK (`wbase_of[wid]` is a list of bases,
    one per channel, and meta carries "weight_repack") each channel packs
    only the rows it owns, so `row_off` is the packed per-channel row rather
    than the global r0 — `seq_format.weight_pieces_at` returns both, and the
    FILE slice (`byte_off`) is unchanged: the same rows, a different address.
    """
    out = []
    rep = is_repacked(meta)
    for wid_s, m in sorted(manifest.items(), key=lambda kv: int(kv[0])):
        wid = int(wid_s)
        nrows, stride = int(m["nrows"]), int(m["stride"])
        lay = layout_of(meta, wid)
        depth = int(((meta or {}).get("weight_layout") or {})
                    .get("chunk_rows", SF.CHUNK_ROWS))
        base = wbase_of[wid]
        if isinstance(base, (list, tuple)) != rep:
            raise SeqError(
                f"wid {wid}: the weight pack is "
                f"{'per-channel' if not rep else 'nch-independent'} but the "
                f"stream says weight_repack={rep} — plan the pack with "
                f"plan_weights_for(manifest, wdir, meta)")
        for (i, r0, n, off) in SF.weight_pieces_at(nrows, nch, lay, depth,
                                                   repack=rep):
            c = weight_chans[i]
            byte_off = r0 * stride
            local = _chan_base(base, i) + off * stride
            out.append({"wid": wid, "chan": c, "r0": r0, "nrows_piece": n,
                        "stride": stride, "byte_off": byte_off,
                        "byte_len": n * stride, "local_addr": local,
                        "abs_addr": c * CH_STRIDE + local, "layout": lay,
                        "row_off": off})
    return out


def _disjoint(ranges):
    """True when sorted [(addr, len)] pairs do not overlap."""
    return all(ranges[i][0] + ranges[i][1] <= ranges[i + 1][0]
               for i in range(len(ranges) - 1))


def _rec_addr64(r):
    return (int(r.len_or_addr_hi) << 32) | int(r.addr_lo)


def relocate(recs, meta, plan, blob_bytes, caps=frozenset(), shape_isa=None):
    """Rebase the stream's baked absolute DDR addresses onto `plan`.

    Returns (new_recs, report).  LDC/EMB are PATCHED; MVGO is only checked
    against the caller's weight plan (see `check_weight_plan`).  The
    relocated stream is re-validated at `caps` (Task SR6: the device's
    capability set, or the caller's board-free one; default empty) and at
    `shape_isa` (SR11a fix round 2: the device's SHAPE layout; None states
    none — see Artifacts).
    """
    old_data = int(meta["seq_data_base"])
    d_data, d_emb = plan["data_delta"], plan["emb_delta"]
    out, n_ldc, n_ldc_ind, n_emb = [], 0, 0, 0
    lo_off, hi_off = None, None
    for i, r in enumerate(recs):
        if r.opcode == SF.EXT_LDC:
            a = _rec_addr64(r)
            off = a - old_data
            if not (0 <= off < max(1, blob_bytes)):
                raise SeqError(
                    f"rec {i}: LDC reads {a:#x}, outside the emitter's "
                    f"{blob_bytes} B blob at {old_data:#x}  [{SF.disasm(r)}]")
            n_words = int(r.imm32)
            if r.ind == SF.IND_NONE and off + 2 * n_words > blob_bytes:
                raise SeqError(
                    f"rec {i}: LDC {a:#x}+{2 * n_words}B runs past the end of "
                    f"the {blob_bytes} B blob  [{SF.disasm(r)}]")
            if r.ind != SF.IND_NONE:
                # A10 position cursor: addr_lo is the FIRST step's table and
                # XRF[4] strides it.  Only the base can be checked statically.
                n_ldc_ind += 1
            na = a + d_data
            if na & 1:
                raise SeqError(f"rec {i}: relocated LDC address {na:#x} is "
                               f"odd (seq_unit raises err 0x0B)")
            if na >> 34:
                raise SeqError(f"rec {i}: relocated LDC address {na:#x} does "
                               f"not fit the 34-bit AXI4 master")
            lo_off = off if lo_off is None else min(lo_off, off)
            hi_off = (off + 2 * n_words if hi_off is None
                      else max(hi_off, off + 2 * n_words))
            out.append(SF.Rec(SF.EXT_LDC, flags=r.flags, target=r.target,
                              imm32=r.imm32, addr_lo=na & 0xFFFFFFFF,
                              len_or_addr_hi=na >> 32))
            n_ldc += 1
        elif r.opcode == SF.OP_EMB:
            base = (int(r.target) << 32) | int(r.imm32)
            if base != int(meta["emb_base"]):
                raise SeqError(
                    f"rec {i}: EMB base {base:#x} != the metadata's "
                    f"{int(meta['emb_base']):#x}  [{SF.disasm(r)}]")
            nb = base + d_emb
            if nb >> 34 or (nb & 1):
                raise SeqError(f"rec {i}: relocated EMB base {nb:#x} is "
                               f"unusable")
            out.append(SF.Rec(SF.OP_EMB, flags=r.flags,
                              target=nb >> 32, imm32=nb & 0xFFFFFFFF,
                              addr_lo=r.addr_lo,
                              len_or_addr_hi=r.len_or_addr_hi))
            n_emb += 1
        else:
            out.append(r)
    SF.validate_stream(out, caps=caps, shape_isa=shape_isa)
    return out, {"ldc": n_ldc, "ldc_indirected": n_ldc_ind, "emb": n_emb,
                 "data_delta": d_data, "emb_delta": d_emb,
                 "blob_span": None if lo_off is None else (lo_off, hi_off)}


def _bases(b):
    """One image's base(s) as a tuple — an int span or the repack's per-chan
    list, normalized so a stream plan and a host plan compare as data."""
    return tuple(int(x) for x in b) if isinstance(b, (list, tuple)) \
        else (int(b),)


def _hexb(b):
    return "/".join(f"{x:#x}" for x in _bases(b))


def _tops(top):
    """A pack's top(s) as a tuple — one address, or one per channel."""
    return tuple(int(t) for t in top) if isinstance(top, (list, tuple)) \
        else (int(top),)


def _shift_bases(b, delta):
    """One image's base(s) moved by `delta`, keeping the pack's shape.  Used
    by the selftest to build a plan that MUST be rejected."""
    return [int(x) + delta for x in b] if isinstance(b, (list, tuple)) \
        else int(b) + delta


def merge_ranges(rs):
    """[(lo, hi)] sorted and coalesced (touching ranges join)."""
    out = []
    for (a, b) in sorted(tuple(r) for r in rs):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def audit_weight_ranges(recs, manifest, wbase_of, nch, weight_chans,
                        meta=None):
    """PER CHANNEL, the bytes the HOST writes must be EXACTLY the bytes the
    ENGINES read.  Returns a report; `ok` is the verdict.

    CONTAINMENT IS NOT ENOUGH, and this check used to be containment ("every
    MVGO lands inside something the host wrote to its channel").  A stream
    that reads ONE chunk of an interleaved image over and over is contained
    in what the host wrote and never touches the other chunks — which is
    exactly what a broken per-channel rebasing produces, and exactly what a
    replay can hide (the LM head's y32 lives in excluded staging and AMAX32
    is strictly-greater, so duplicated rows tie rather than diverge).
    Comparing the MERGED range sets for EQUALITY catches it from both sides:
    an engine range the host never wrote, AND a host range no engine reads.

    `rows` additionally resolves every MVGO to the GLOBAL image row it reads,
    through the host's own piece list — the mapping `ref/seq_model.py`
    does — so callers can check the ILV interleave in global-row terms.
    """
    splits = plan_weight_split(manifest, wbase_of, nch, weight_chans, meta)
    host, pieces = {}, {}
    for s in splits:
        host.setdefault(s["chan"], []).append(
            (s["local_addr"], s["local_addr"] + s["byte_len"]))
        pieces.setdefault(s["chan"], []).append(s)
    eng, rows, orphan = {}, [], []
    for i, r in enumerate(recs):
        if r.opcode != SF.OP_MVGO:
            continue
        wb = ((int(r.len_or_addr_hi) & 0xFF) << 32) | int(r.addr_lo)
        end = wb + (int(r.len_or_addr_hi) >> 8) * 64
        eng.setdefault(int(r.chan), []).append((wb, end))
        hit = [s for s in pieces.get(int(r.chan), ())
               if s["local_addr"] <= wb
               and end <= s["local_addr"] + s["byte_len"]]
        if not hit:
            orphan.append((i, int(r.chan), wb, end))
            continue
        s = hit[0]
        rows.append({"rec": i, "chan": int(r.chan), "wid": s["wid"],
                     "row": s["r0"] + (wb - s["local_addr"]) // s["stride"],
                     "nrows": (end - wb) // s["stride"]})
    bad = []
    for c in sorted(set(host) | set(eng)):
        h, e = merge_ranges(host.get(c, ())), merge_ranges(eng.get(c, ()))
        if h != e:
            only_h = [x for x in h if x not in e]
            only_e = [x for x in e if x not in h]
            bad.append({"chan": c, "host_only": only_h[:4],
                        "engine_only": only_e[:4],
                        "n_host": len(h), "n_engine": len(e)})
    return {"ok": not bad and not orphan, "mismatch": bad, "orphan": orphan,
            "mvgo": sum(1 for r in recs if r.opcode == SF.OP_MVGO),
            "rows": rows, "chans": sorted(set(host) | set(eng)),
            "host_bytes": {c: sum(b - a for a, b in merge_ranges(v))
                           for c, v in sorted(host.items())}}


def write_synth_repack_artifact(d, nch=4, chunk_rows=64, prefix="rp.e",
                                emb_h=1024, rs_f=None, caps=frozenset()):
    """Write a tiny REPACKED artifact (.seq/.seqdata.bin/.seq.json +
    .weights.json + weight images) into directory `d`; return its prefix.

    `emb_h` is the hidden size the fixture claims (the EMB record's word
    count and `emb_row_bytes = 2*emb_h` move together — G2a made them one
    parameter because they were two literals that had to agree and nothing
    said so).  `rs_f` is emitted only when passed, exactly as
    `ref/gen_layer_script.py`'s `dump_weights` gates it.

    R-c review C1: every repack check the selftest had synthesized a
    per-channel PLAN from a NON-repacked artifact, so no repacked artifact
    ever went through the artifact loop — and four lines in that loop (a
    tuple top, an int(base) on a list, two plan_weight_split calls without
    the meta) raised TypeError/SeqError the moment one did.  That is the gate
    Task 4 and Task 6 run FIRST on their new artifact, so the loop now
    carries one of its own: three images (one W8, one chunk-INTERLEAVED with
    an uneven split), real MVGO/MOVX/MOVY records built from the real
    allocator, at nch=4.

    Deliberately small (~150 KB of zero-filled images): nothing reads the
    weight BYTES here — this artifact exists to exercise ADDRESSES.
    """
    from w4a8_ref import row_stride, row_stride8
    imgs = [                                   # (nrows, K, w8, ILV)
        (512, 256, False, False),              # a plain contiguous image
        (40, 128, True, False),                # W8: a different row law
        (200, 256, False, True),               # the "head": uneven interleave
    ]
    man, lay, wids = {}, {}, {}
    for wid, (n, K, w8, ilv) in enumerate(imgs):
        stride = row_stride8(K, 128) if w8 else row_stride(K, 128)
        fn = f"rp_w{wid}.bin"
        with open(os.path.join(d, fn), "wb") as f:
            f.truncate(n * stride)
        man[str(wid)] = {"file": fn, "nrows": n, "k": K, "ng": K // 128,
                         "sh": 5, "e": -4, "stride": stride,
                         "nbeats": n * stride // 64}
        if w8:
            man[str(wid)]["w8"] = True
        lay[wid] = SF.LAYOUT_ILV if ilv else SF.LAYOUT_CONTIG
        zc = np.zeros((n, K), dtype=np.int8)
        wids[f"w{wid}"] = (wid, {"w8" if w8 else "w4": zc,
                                 "m": np.zeros((n, K // 128), dtype=np.int8),
                                 "sh": 5, "g": 128})
    man["emb_row_bytes"] = 2 * emb_h
    if rs_f is not None:
        man["rs_f"] = int(rs_f)
    with open(os.path.join(d, "rp.weights.json"), "w") as f:
        json.dump(man, f)
    plan = SF.plan_weights_from_wids(wids, nch=nch, repack=True,
                                     layout_of=lay, chunk_rows=chunk_rows)
    blob = bytes(range(256)) * 8               # 2048 B of LDC constants
    recs = [SF.Rec(SF.OP_CSRWR, target=SF.csr_seq_xrf(SF.XRF_TOK), imm32=11),
            SF.Rec(SF.EXT_LDC, target=0x100, imm32=256,
                   addr_lo=SF.SEQ_DATA_BASE & 0xFFFFFFFF,
                   len_or_addr_hi=SF.SEQ_DATA_BASE >> 32),
            SF.Rec(SF.OP_EMB, target=EMB_BASE >> 32,
                   imm32=EMB_BASE & 0xFFFFFFFF, addr_lo=0x200,
                   len_or_addr_hi=emb_h)]
    dst = 0x600
    for wid, (n, K, w8, _ilv) in enumerate(imgs):
        p = plan[wid]
        for (i, r0, npc, off) in SF.weight_pieces_at(n, nch, lay[wid],
                                                     chunk_rows, repack=True):
            wb = p["base"][i] + off * p["stride"]
            beats = npc * p["stride"] // 64
            recs += [
                SF.Rec(SF.OP_MOVX, flags=(i << SF.CHAN_SHIFT), addr_lo=0x200,
                       len_or_addr_hi=K),
                SF.Rec(SF.OP_MVGO, flags=(i << SF.CHAN_SHIFT),
                       target=SF.MVGO_NOWAIT,
                       # G3.3: this tree's SHAPE word (isa=2) has NO w8
                       # bit -- the engine mode is gone.  The fixture's W8
                       # image is here for its ROW LAW (row_stride8 and the
                       # per-channel addresses), which is what this artifact
                       # exercises, so `w8` stays in the MANIFEST and out of
                       # the SHAPE word.  See sw/hwmap.py's R_SHAPE block.
                       imm32=HW.shape_word(npc, 5, K // 128, g=128),
                       addr_lo=wb & 0xFFFFFFFF,
                       len_or_addr_hi=((beats << 8) | ((wb >> 32) & 0xFF))),
                SF.Rec(SF.OP_FENCE),
                SF.Rec(SF.OP_MOVY, flags=SF.MOVY_MODE_BIT, target=i, imm32=3,
                       addr_lo=dst, len_or_addr_hi=npc)]
            dst += npc
    recs += [SF.Rec(SF.OP_AMAXL), SF.Rec(SF.OP_HALT)]
    stream = SF.pack_stream(recs)
    # SR6: a fixture WRITER, not a load for a board — validated at the set
    # its caller names (default empty: it writes only mask-0 FENCEs); every
    # LOAD of it (Artifacts, relocate) validates at the device's set
    SF.validate_stream(recs, caps=caps)
    meta = {
        "format": "FAB5SEQ", "format_version": SF.FORMAT_VERSION,
        "profile": "epsnorm", "chan": 0, "nch": nch,
        "chans": list(range(nch)), "nrec": len(recs),
        "stream_bytes": len(stream),
        "stream_sha256": hashlib.sha256(stream).hexdigest(),
        "seqdata_bytes": len(blob),
        "seqdata_sha256": hashlib.sha256(blob).hexdigest(),
        "seq_data_base": SF.SEQ_DATA_BASE,
        "seq_stream_base": SF.SEQ_STREAM_BASE,
        "emb_base": EMB_BASE,
        "weights": {str(k): v for k, v in sorted(plan.items())},
        "weight_repack": True,
        "weight_layout": {"nch": nch, "chunk_rows": chunk_rows,
                          "default": SF.LAYOUT_CONTIG,
                          "by_wid": {str(k): v
                                     for k, v in sorted(lay.items())},
                          "ilv_wids": sorted(k for k, v in lay.items()
                                             if v == SF.LAYOUT_ILV)},
        "expect_tokens": [11], "steps": 1, "prompt_fed": [],
        "loop_steps": 0, "loop_note": "synthetic", "staging_words": [],
        "checkpoints": [], "notes": ["synthetic R-c repack artifact"],
    }
    # SR13b: the fixture declares the SHAPE layout its MVGO words are built
    # in (HW.shape_word at this tree's layout), as ref/seq_format.py does
    # for every non-BYTELOCKED stream; a board run requires the key
    meta["shape_isa"] = HW.SHAPE_ISA
    with open(os.path.join(d, prefix + ".seq"), "wb") as f:
        f.write(stream)
    with open(os.path.join(d, prefix + ".seqdata.bin"), "wb") as f:
        f.write(blob)
    with open(os.path.join(d, prefix + ".seq.json"), "w") as f:
        json.dump(meta, f, indent=1)
    return os.path.join(d, prefix)


# ---- address mutations: a check that kills nothing proves nothing --------
# `audit_weight_ranges` is only worth its runtime if it FAILS on a stream
# whose weight addressing is wrong, so the mutations it must kill live here,
# next to it, and are run both by --selftest and by the committed audit
# evidence (evidence/qwen2b/rc/t3_audit.py).  Each returns a mutated record
# list, or None when the mutation does not apply to that stream.
def _rewrite_mvgo(recs, fn):
    out, hit = [], False
    for r in recs:
        if r.opcode == SF.OP_MVGO:
            wb = ((int(r.len_or_addr_hi) & 0xFF) << 32) | int(r.addr_lo)
            nw = fn(r, wb)
            if nw is not None and nw != wb:
                hit = True
                r = SF.Rec(SF.OP_MVGO, flags=r.flags, target=r.target,
                           imm32=r.imm32, addr_lo=nw & 0xFFFFFFFF,
                           len_or_addr_hi=(((int(r.len_or_addr_hi) >> 8) << 8)
                                           | ((nw >> 32) & 0xFF)))
        out.append(r)
    return out if hit else None


def _piece_map(manifest, wbase_of, nch, wchans, meta):
    by = {}
    for s in plan_weight_split(manifest, wbase_of, nch, wchans, meta):
        by.setdefault(s["chan"], []).append(s)
    return by


def _mut_shift(recs, manifest, wbase_of, nch, wchans, meta=None, delta=32768):
    """Every MVGO moved by a constant — the coarsest possible placement bug,
    and one a replay does NOT catch (it reads consistent garbage)."""
    return _rewrite_mvgo(recs, lambda r, wb: wb + delta)


def _mut_ilv_zero(recs, manifest, wbase_of, nch, wchans, meta=None):
    """Every chunk of an interleaved image re-pointed at its channel's packed
    row 0 — what a MISSING per-chunk rebasing produces.  Contained in what
    the host wrote, so containment cannot see it."""
    ilv = set(((meta or {}).get("weight_layout") or {}).get("ilv_wids", []))
    if not ilv:
        return None
    by = _piece_map(manifest, wbase_of, nch, wchans, meta)

    def f(r, wb):
        for s in by.get(int(r.chan), ()):
            if s["wid"] in ilv and \
                    s["local_addr"] <= wb < s["local_addr"] + s["byte_len"]:
                return _chan_base(wbase_of[s["wid"]],
                                  wchans.index(s["chan"]))
        return None
    return _rewrite_mvgo(recs, f)


def _mut_global_row(recs, manifest, wbase_of, nch, wchans, meta=None):
    """A repacked image addressed by its GLOBAL row — i.e. the pre-R-c
    formula applied to a per-channel base.  Only applies to a repacked
    stream; on channel 0's first piece it is the identity, which is exactly
    why the audit has to look at every channel."""
    if not is_repacked(meta):
        return None
    by = _piece_map(manifest, wbase_of, nch, wchans, meta)

    def f(r, wb):
        for s in by.get(int(r.chan), ()):
            if s["local_addr"] <= wb < s["local_addr"] + s["byte_len"]:
                i = wchans.index(s["chan"])
                g = s["r0"] + (wb - s["local_addr"]) // s["stride"]
                return _chan_base(wbase_of[s["wid"]], i) + g * s["stride"]
        return None
    return _rewrite_mvgo(recs, f)


def check_weight_plan(meta, wbase_of, manifest):
    """MVGO WBASEs are ASSERTED against the host's own pack, never patched."""
    mplan = {int(k): v for k, v in meta.get("weights", {}).items()}
    if not mplan:
        return {"images": 0, "note": "stream carries no weight plan"}
    bad = []
    for wid, p in sorted(mplan.items()):
        host = wbase_of.get(wid)
        if host is None:
            bad.append(f"wid {wid}: in the stream plan, absent from "
                       f"{len(wbase_of)} packed manifest images")
        elif _bases(p["base"]) != _bases(host):
            bad.append(f"wid {wid}: stream WBASE {_hexb(p['base'])} != host "
                       f"pack {_hexb(host)}")
        else:
            m = manifest[str(wid)] if str(wid) in manifest else manifest[wid]
            for k in ("nrows", "ng", "sh", "stride"):
                if int(p[k]) != int(m[k]):
                    bad.append(f"wid {wid}: stream {k}={p[k]} != manifest "
                               f"{m[k]}")
            if int(p.get("g", 128)) != int(m.get("g", 128)):
                bad.append(f"wid {wid}: stream g={p.get('g', 128)} != "
                           f"manifest g={m.get('g', 128)}")
            # V5 weight width, carried the way "g" is: ABSENT == W4.  The
            # stream's MVGO SHAPE bit 29 comes from the stream plan, the
            # bytes on the wire come from the manifest's image, so a
            # disagreement here is an engine that would parse int8 weight
            # bytes as nibbles (or the reverse) — checked, never inferred.
            if bool(p.get("w8", False)) != bool(m.get("w8", False)):
                bad.append(f"wid {wid}: stream w8={bool(p.get('w8', False))} "
                           f"!= manifest w8={bool(m.get('w8', False))}")
    if bad:
        raise SeqError("the SEQ stream and the weight pack disagree "
                       "(regenerate one of them):\n  " + "\n  ".join(bad[:12]))
    return {"images": len(mplan)}


def check_mvgo_targets(recs, wbase_of, manifest, meta=None):
    """Every MVGO WBASE must be a row-aligned offset inside a packed image.

    Under the R-c repack the spans are PER CHANNEL — the same address means
    different rows on different channels — so the record's engine channel
    selects which channel's span list it is checked against.  That makes this
    strictly stronger than the nch-independent check it replaces, which
    ignored the channel because every channel held the same span.
    """
    rep = is_repacked(meta)
    nch = int((meta or {}).get("nch", 1))
    depth = int(((meta or {}).get("weight_layout") or {})
                .get("chunk_rows", SF.CHUNK_ROWS))
    imgs = {}                      # channel index -> [(lo, hi, stride, wid)]
    for wid, base in sorted(wbase_of.items()):
        m = manifest[str(wid)] if str(wid) in manifest else manifest[wid]
        nrows, stride = int(m["nrows"]), int(m["stride"])
        rows = (SF.chan_rows(nrows, nch, layout_of(meta, wid), depth) if rep
                else [nrows] * max(1, nch))
        for c in range(max(1, nch) if rep else 1):
            lo = _chan_base(base, c)
            imgs.setdefault(c if rep else None, []).append(
                (int(lo), int(lo) + rows[c] * stride, stride, int(wid)))
    n = 0
    for i, r in enumerate(recs):
        if r.opcode != SF.OP_MVGO:
            continue
        wb = ((int(r.len_or_addr_hi) & 0xFF) << 32) | int(r.addr_lo)
        where = imgs.get(int(r.chan) if rep else None, [])
        hit = [t for t in where if t[0] <= wb < t[1]]
        if not hit:
            raise SeqError(f"rec {i}: MVGO WBASE {wb:#x} is outside every "
                           f"packed weight image"
                           + (f" on channel {r.chan}" if rep else "")
                           + f"  [{SF.disasm(r)}]")
        lo, _hi, stride, wid = hit[0]
        if (wb - lo) % stride:
            raise SeqError(f"rec {i}: MVGO WBASE {wb:#x} is not row-aligned "
                           f"in wid {wid} (stride {stride})  [{SF.disasm(r)}]")
        n += 1
    return n


def first_divergence(got, want, a_name="chip", b_name="expected"):
    """Human-readable first difference between two token sequences."""
    got, want = list(got), list(want)
    if got == want:
        return None
    n = min(len(got), len(want))
    for i in range(n):
        if got[i] != want[i]:
            lo = max(0, i - 3)
            return (f"first divergence at token {i}: {a_name}={got[i]} "
                    f"{b_name}={want[i]}\n"
                    f"    {a_name}[{lo}:{i + 4}] = {got[lo:i + 4]}\n"
                    f"    {b_name}[{lo}:{i + 4}] = {want[lo:i + 4]}")
    return (f"{a_name} produced {len(got)} tokens, {b_name} has {len(want)} "
            f"(common prefix of {n} identical)\n"
            f"    {a_name}  = {got}\n    {b_name} = {want}")


def disasm_window(recs, pc, n_before=12, n_after=1):
    """Disassemble [pc-n_before, pc+n_after] with the ARG0..2 shadow.

    The shadow is rebuilt by a STATIC scan from record 0, so after a taken
    JMP it is the shadow of the fall-through path, not of the execution
    trace — good enough to read the failing record, flagged in the output.
    """
    lo = max(0, pc - n_before)
    hi = min(len(recs), pc + 1 + n_after)
    ctx = {}
    for r in recs[:lo]:
        if r.opcode == SF.OP_CSRWR:
            if r.target == SF.CSR_L_ARG0:
                ctx["arg0"] = r.imm32
            elif r.target == SF.CSR_L_ARG1:
                ctx["arg1"] = r.imm32
            elif r.target == SF.CSR_L_ARG2:
                ctx["arg2"] = r.imm32
    lines = []
    for i in range(lo, hi):
        r = recs[i]
        mark = "  <<< PC" if i == pc else ""
        lines.append(SF.disasm(r, i, ctx) + mark)
        if r.opcode == SF.OP_CSRWR:
            if r.target == SF.CSR_L_ARG0:
                ctx["arg0"] = r.imm32
            elif r.target == SF.CSR_L_ARG1:
                ctx["arg1"] = r.imm32
            elif r.target == SF.CSR_L_ARG2:
                ctx["arg2"] = r.imm32
    return "\n".join(lines)


def parse_chip_golden(path):
    """Read a tb/scripts/gen_seq_chip_vectors.py <prefix>.chip golden."""
    g = {"xrf": {}, "tok": [], "tcnt": {}, "mem": {}}
    with open(path) as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            k = p[0]
            if k == "NREC":
                g["nrec"] = int(p[1])
            elif k == "PC":
                g["pc"] = int(p[1])
            elif k == "BASES":
                g["bases"] = [int(x, 16) for x in p[1:]]
            elif k == "XRF":
                g["xrf"][int(p[1])] = int(p[2], 16)
            elif k == "TOK":
                g["tok"].append(int(p[1], 16))
            elif k == "TCNT":
                g["tcnt"][int(p[1])] = (int(p[2]), int(p[3]))
            elif k == "EOUT":
                g["eout"] = int(p[1], 16)
            elif k == "AMAX":
                g["amax"] = (int(p[1], 16), int(p[2], 16))
            elif k == "MEM":
                g["mem"][int(p[1], 16)] = int(p[2], 16)
            elif k == "END":
                g["end"] = True
    if not g.get("end"):
        raise SeqError(f"{path}: no END line — truncated golden")
    return g


# ======================================================================
# device
# ======================================================================
class Dev(object):
    """XDMA AXI-Lite CSR + DMA access with the board-safety gate.

    `seq_ok` is False until the identity gate has SEEN the build_029 VERSION
    and the seq_unit IDENT; every SEQ CSR accessor refuses while it is False,
    which is what makes --dry-run safe on a bitstream that has no seq_0.
    """

    def __init__(self, path="/dev/xdma0", chan=0, allow_seq=True,
                 expect_version=EXPECT_DEFAULT, log=print):
        self.chan = chan
        self.log = log
        self.n_rd = self.n_wr = 0
        expect_version = resolve_expect_version(expect_version)
        if expect_version != EXPECTED_SEQ_VERSION:
            log(f"  identity gate: expecting VERSION {expect_version:#010x} "
                f"({SEQ_VERSIONS.get(expect_version, (0, '?'))[1]}), NOT the "
                f"shipped {EXPECTED_SEQ_VERSION:#010x} -- named by "
                f"--expect-version or {EXPECT_VERSION_ENV}")
        self.user = os.open(f"{path}_user", os.O_RDWR)
        self.ident, self.seq_ok, self.seq_why = self._gate(expect_version,
                                                           allow_seq)
        self.h2c = os.open(f"{path}_h2c_0", os.O_WRONLY)
        self.c2h = os.open(f"{path}_c2h_0", os.O_RDONLY)
        self.ddr_off = chan * CH_STRIDE

    # ---------------- raw MMIO ----------------
    def rd(self, a):
        self.n_rd += 1
        return int.from_bytes(os.pread(self.user, 4, a), "little")

    def wr(self, a, v):
        self.n_wr += 1
        os.pwrite(self.user, int(v).to_bytes(4, "little"), a)

    # ---------------- identity ----------------
    def _gate(self, expect_version, allow_seq):
        rd = self.rd
        magic, ver, calib = rd(R_MAGIC), rd(R_VERSION), rd(R_CALIB)
        li = rd(L_IDENT)
        mvi = [rd(mv_base(c) + R_IDENT) for c in range(4)]
        bad = []
        if magic != MAGIC:
            bad.append(f"MAGIC={magic:#010x} want {MAGIC:#010x}")
        if calib != CALIB_ALL:
            bad.append(f"CALIB={calib:#x} want {CALIB_ALL:#x}")
        if li != LAYER_IDENT:
            bad.append(f"layer IDENT={li:#010x} want {LAYER_IDENT:#010x}")
        for c, v in enumerate(mvi):
            if v != MV_IDENT0 + c:
                bad.append(f"matvec{c} IDENT={v:#010x} want "
                           f"{MV_IDENT0 + c:#010x}")
        if bad:
            os.close(self.user)
            raise SystemExit(
                "REFUSING TO TOUCH THE BOARD — identity gate failed:\n  "
                + "\n  ".join(bad)
                + "\n(this tool never programs the FPGA; fix the resident "
                  "bitstream out of band)")
        ident = {"magic": magic, "version": ver, "calib": calib,
                 "layer_ident": li, "mv_ident": mvi}
        # ---- the SEQ half of the gate: 0x6000 does not exist before 029 ----
        if not allow_seq:
            return ident, False, "--dry-run: the SEQ CSR window is not touched"
        if expect_version is None:
            return ident, False, (
                "EXPECTED_SEQ_VERSION is still the None placeholder in "
                "sw/seq_run.py — fill it with the build_029 netlist hash")
        if expect_version not in SEQ_VERSIONS:
            return ident, False, (
                f"expected VERSION {expect_version:#010x} is not in "
                f"sw/seq_run.SEQ_VERSIONS -- refusing an unknown bitstream")
        if ver != expect_version:
            known = (KNOWN_NO_SEQ_VERSIONS.get(ver)
                     or SEQ_VERSIONS.get(ver, (0, None))[1])
            return ident, False, (
                f"VERSION={ver:#010x}"
                + (f" ({known})" if known else "")
                + f" != expected {expect_version:#010x} "
                  f"({'EXPECTED_SEQ_VERSION' if expect_version == EXPECTED_SEQ_VERSION else 'named by --expect-version / ' + EXPECT_VERSION_ENV}): "
                  f"this bitstream has no sequencer (or is the wrong one)"
                + ("; to drive it, name it: --expect-version "
                   f"{ver:08x} or {EXPECT_VERSION_ENV}={ver:08x}"
                   if ver in SEQ_VERSIONS else ""))
        sid = rd(S_IDENT)
        if sid != SEQ_IDENT:
            return ident, False, (f"seq IDENT={sid:#010x} want "
                                  f"{SEQ_IDENT:#010x}")
        ident["seq_ident"] = sid
        # Task SR7: the row's EXPECTED SEQ_CAPS word, compared like VERSION
        # (a raw word compare: an unknown capability bit, a missing R1 or an
        # R1 word on a pre-round VERSION all refuse here, before any DMA).
        caps_w = rd(HW.S_SEQ_CAPS)
        ident["seq_caps"] = caps_w
        want_caps = SEQ_VERSIONS[expect_version][2]
        if caps_w != want_caps:
            return ident, False, (
                f"SEQ_CAPS={caps_w:#010x} != expected {want_caps:#010x} for "
                f"VERSION {ver:#010x} ({SEQ_VERSIONS[expect_version][1]}): "
                f"the bitstream's capabilities are not the ones its "
                f"SEQ_VERSIONS row names")
        return ident, True, "ok"

    def require_seq(self, what):
        if not self.seq_ok:
            raise SystemExit(f"REFUSING {what}: {self.seq_why}")

    # ---------------- DDR ----------------
    def dma_write(self, addr, data):
        n = os.pwrite(self.h2c, data, self.ddr_off + addr)
        if n != len(data):
            raise SeqError(f"short DMA write {n}/{len(data)} @ {addr:#x}")

    def dma_read(self, addr, nbytes):
        b = os.pread(self.c2h, nbytes, self.ddr_off + addr)
        if len(b) != nbytes:
            raise SeqError(f"short DMA read {len(b)}/{nbytes} @ {addr:#x}")
        return b

    def dma_verify(self, addr, data, tag=""):
        """Read `len(data)` bytes back and compare, in DMA_CHUNK pieces."""
        off = 0
        while off < len(data):
            n = min(DMA_CHUNK, len(data) - off)
            got = self.dma_read(addr + off, n)
            if got != data[off:off + n]:
                a = np.frombuffer(got, dtype=np.uint8)
                b = np.frombuffer(data[off:off + n], dtype=np.uint8)
                i = int(np.nonzero(a != b)[0][0])
                raise SeqError(
                    f"DDR readback mismatch {tag} @ {addr + off + i:#x}: "
                    f"got {int(a[i]):#04x} want {int(b[i]):#04x} "
                    f"({int((a != b).sum())} bad bytes in this {n} B chunk)")
            off += n
        return hashlib.sha256(data).hexdigest()

    # ---- channel-explicit DDR (weights row-split across channels) ----
    # dma_write/read above add `self.ddr_off` (the FETCH channel) so the
    # stream/blob/emb follow the sequencer's fetch view.  A row-split weight
    # image instead lands on channels 0..nch-1 at ABSOLUTE `c*CH_STRIDE +
    # local_addr`, so these variants take the channel explicitly and ignore
    # self.ddr_off.  (nch==1 -> chan == the fetch channel, so the abs address
    # is identical to what dma_write produced before this change.)
    def dma_write_chan(self, chan, addr, data):
        base = chan * CH_STRIDE + addr
        n = os.pwrite(self.h2c, data, base)
        if n != len(data):
            raise SeqError(f"short DMA write {n}/{len(data)} @ ch{chan} "
                           f"{addr:#x}")

    def dma_read_chan(self, chan, addr, nbytes):
        """Raw read at the ABSOLUTE ch*CH_STRIDE+addr (residency probes)."""
        got = os.pread(self.c2h, nbytes, chan * CH_STRIDE + addr)
        self.n_rd += 1
        if len(got) != nbytes:
            raise SeqError(f"short DMA read {len(got)}/{nbytes} @ ch{chan} "
                           f"{addr:#x}")
        return got

    def dma_verify_chan(self, chan, addr, data, tag=""):
        """Read back and compare against the ABSOLUTE ch*CH_STRIDE+addr.

        Independent of self.ddr_off (the fetch channel), so a weight quarter
        on any channel is verified where dma_write_chan actually put it.
        """
        base = chan * CH_STRIDE + addr
        off = 0
        while off < len(data):
            n = min(DMA_CHUNK, len(data) - off)
            got = os.pread(self.c2h, n, base + off)
            self.n_rd += 1
            if len(got) != n:
                raise SeqError(f"short DMA read {len(got)}/{n} @ ch{chan} "
                               f"{addr + off:#x}")
            if got != data[off:off + n]:
                a = np.frombuffer(got, dtype=np.uint8)
                b = np.frombuffer(data[off:off + n], dtype=np.uint8)
                i = int(np.nonzero(a != b)[0][0])
                raise SeqError(
                    f"DDR readback mismatch {tag} @ ch{chan} "
                    f"{addr + off + i:#x}: got {int(a[i]):#04x} want "
                    f"{int(b[i]):#04x} ({int((a != b).sum())} bad bytes in "
                    f"this {n} B chunk)")
            off += n
        return hashlib.sha256(data).hexdigest()

    # ---------------- SEQ CSRs ----------------
    def seq_rd(self, a):
        self.require_seq(f"a SEQ CSR read at {a:#x}")
        return self.rd(a)

    def seq_wr(self, a, v):
        self.require_seq(f"a SEQ CSR write at {a:#x}")
        self.wr(a, v)

    def seq_status(self):
        return seq_status(self.seq_rd(S_STATUS))

    def seq_drain_fifo(self, limit=None):
        """Pop every OUT FIFO entry.  Reading S_OUT_FIFO IS the pop."""
        out = []
        # rung 4 S6: OUT FIFO depth 16 -> 64, so the count is 7 bits.
        n = self.seq_rd(S_OUT_CNT) & SEQ_ST_OUTCNT_MASK
        if limit is not None:
            n = min(n, limit)
        for _ in range(n):
            w = self.seq_rd(S_OUT_FIFO)
            if not (w & SEQ_OUT_VALID):
                break
            out.append(w & SEQ_OUT_TOK_MASK)
        return out

    def seq_perf(self):
        fst = self.seq_rd(S_PERF_FST)
        perf = {"cyc": self.seq_rd(S_PERF_CYC), "rec": self.seq_rd(S_PERF_REC),
                "axil_wr": self.seq_rd(S_PERF_AXW),
                "axil_rd": self.seq_rd(S_PERF_AXR),
                "fetch_starved_cyc": fst >> 1,
                "xrf_ovf": bool(fst & SEQ_PERF_XRF_OVF)}
        bm = self.seq_bm()
        if bm is not None:
            perf["bm"] = bm
        return perf

    def seq_bm(self):
        """BM1 idle counters (docs/SEQ_ISA.md B16, v2.2): the SEQ 0x100
        block, read AFTER HALT like the PERF_* registers beside it.

        FEATURE DETECTION, not a VERSION table: BM_IDENT is read first and
        only the exact magic makes the block count.  On build_041 (and every
        bitstream before BM1) 0x100 is outside the SEQ map and reads
        0xDEADC0DE, so this returns None and the caller's report has no
        "bm" key -- the same tool runs on both bitstreams.
        """
        if self.seq_rd(S_BM_IDENT) != SEQ_BM_IDENT:
            return None
        return {name: self.seq_rd(S_BM_IDENT + off)
                for name, off in SEQ_BM_REGS}

    def seq_caps(self):
        """Task SR6 (docs/SEQ_ISA.md v2.3 B17.0): the DEVICE's capability
        set — SEQ_CAPS (SEQ 0x64) decoded by hwmap.seq_caps_set, the one
        definition.  FEATURE DETECTION like seq_bm(): every pre-round
        bitstream (build_041/042) reads 0xDEADC0DE there (the read mux
        default), which decodes as the EMPTY set, so the same host refuses
        an r1 stream on those and admits it on an R1 bitstream.

        Read through seq_rd(), so it happens only behind an OPEN SEQ gate —
        a VERSION the caller named (SEQ_VERSIONS / --expect-version) and
        the seq IDENT; a closed gate (or --dry-run) refuses instead of
        reading.  A capability bit this host does not know is refused
        (SeqError naming the bit), never guessed at.  The raw word is kept
        in `self.caps_word` for the report."""
        w = self.seq_rd(HW.S_SEQ_CAPS)
        try:
            caps = HW.seq_caps_set(w)
        except ValueError as e:
            raise SeqError(str(e))
        self.caps_word = w
        return caps

    def seq_xrf(self):
        return [self.seq_rd(s_xrf(i)) & 0x3FFFF for i in range(SEQ_XRF_N)]

    # ---------------- layer_chan (POST-HALT ONLY) ----------------
    def layer_read_scratch(self, addr, n=SCRATCH_WORDS_BUILT):
        self.wr(L_SPTR, addr)
        buf = b"".join([os.pread(self.user, 4, L_SWIN) for _ in range(n)])
        self.n_rd += n
        return np.frombuffer(buf, dtype="<u4").astype(np.int64) & 0xFFFF

    def layer_zero_scratch(self, n=SCRATCH_WORDS_BUILT):
        """Write zeros over the whole layer_chan scratchpad (IDLE ONLY).

        R-d: the FPGA's scratchpad is NOT cleared between runs, but the
        `.chip` golden is generated from `ref/seq_model`, whose memory IS
        zero-initialised.  Every non-staging word the golden lists is
        therefore asserted to be zero unless the stream writes it — which
        holds trivially for as long as one model owns the board, and stops
        holding the moment two geometries alternate: 0.8B leaves y32 values
        in 0x1810..0x1bff, which is live scratch the 2B stream never writes,
        so the 2B golden reports them as mismatches (and vice versa, at
        0x0c10..0x0fff).  Proven residue rather than arithmetic in
        `evidence/qwen2b/rd/hw_22_scratch_residue_proof.log`.

        Clearing the pad before a run removes the ambiguity: then every
        checked word is either written by this run or provably zero.
        `rtl/layer_chan.sv:1078-1083` — SWIN writes scratch[SPTR] and
        post-increments SPTR (SPTR itself is `:677`); the port is idle-only
        (`:1433-1434` muxes it away while `busy`), so this must run BEFORE
        the sequencer starts.  It is a host-side write to the same port
        `layer_read_scratch` reads through.
        """
        self.wr(L_SPTR, 0)
        for _ in range(n):
            self.wr(L_SWIN, 0)      # self.wr() counts each one in n_wr

    def layer_xrf(self, i):
        self.wr(L_XRFI, i)
        return self.rd(L_XRFD) & 0x3FFFF

    def layer_tcnt(self, kv_slot):
        keep = self.rd(L_LAYER)
        self.wr(L_LAYER, (kv_slot << 8) | (keep & 0x1F))
        v = self.rd(L_TCNT)
        self.wr(L_LAYER, keep)
        return (v & 0x3FF, (v >> 16) & 0x3FF)


# ======================================================================
# the run
# ======================================================================
def upload(dev, art, plan, recs, do_weights=True, verify=True, log=print):
    """Weights + embedding + blob + stream -> DDR, readback-checked."""
    rep = {"ranges": [], "bytes": 0, "verified_bytes": 0}
    t0 = time.monotonic()
    wbase_of, wtop = plan_weights_for(art.manifest, art.wdir, art.meta)

    def put(name, addr, data):
        dev.dma_write(addr, data)
        rep["bytes"] += len(data)
        h = None
        if verify:
            h = dev.dma_verify(addr, data, tag=name)
            rep["verified_bytes"] += len(data)
        rep["ranges"].append({"name": name, "addr": hex(addr),
                              "bytes": len(data),
                              "sha256": (h or "")[:16] or None})
        return h

    nch = plan["nch"]
    wchans = plan["weight_chans"]
    if do_weights:
        # Each weight image is row-split across `wchans` (nch==1 -> the one
        # fetch channel, byte-identical to the old whole-image write; nch>1 ->
        # channels 0..nch-1, tok_meter.py:308-320).  Placement is a pure
        # function (plan_weight_split) so --selftest can prove the addressing
        # off-board; here we just read each file once and DMA its quarters.
        splits = plan_weight_split(art.manifest, wbase_of, nch, wchans,
                                   art.meta)
        by_wid = {}
        for s in splits:
            by_wid.setdefault(s["wid"], []).append(s)
        nby = 0
        for wid, m in sorted(art.manifest.items(), key=lambda kv: int(kv[0])):
            img = open(os.path.join(art.wdir, m["file"]), "rb").read()
            mv = memoryview(img)
            for s in by_wid[int(wid)]:
                lo, hi = s["byte_off"], s["byte_off"] + s["byte_len"]
                dev.dma_write_chan(s["chan"], s["local_addr"], mv[lo:hi])
                nby += s["byte_len"]
        rep["bytes"] += nby
        if verify:
            h = hashlib.sha256()
            for wid, m in sorted(art.manifest.items(),
                                 key=lambda kv: int(kv[0])):
                img = open(os.path.join(art.wdir, m["file"]), "rb").read()
                for s in by_wid[int(wid)]:
                    lo, hi = s["byte_off"], s["byte_off"] + s["byte_len"]
                    dev.dma_verify_chan(
                        s["chan"], s["local_addr"], img[lo:hi],
                        tag=f"weight {m['file']} ch{s['chan']} "
                            f"rows[{s['r0']},{s['r0'] + s['nrows_piece']})")
                    rep["verified_bytes"] += s["byte_len"]
                h.update(img)                    # full image, wid order
            rep["weights_sha256"] = h.hexdigest()[:16]
        rep["ranges"].append({"name": f"{len(art.manifest)} weight images "
                              f"x {nch} chan" + ("s" if nch > 1 else ""),
                              "addr": hex(W_BASE), "bytes": nby,
                              "sha256": rep.get("weights_sha256"),
                              "chans": list(wchans)})
        ilv = sorted({s["wid"] for s in splits
                      if s.get("layout") == SF.LAYOUT_ILV})
        cs = "chan " + str(wchans[0]) if nch == 1 else \
            f"row-split over chans {wchans}" + (
                f", wid {ilv} chunk-INTERLEAVED (rung 4 S4)" if ilv else "")
        rep["ilv_wids"] = ilv
        rep["weight_writes"] = len(splits)
        log(f"  weights   {len(art.manifest)} images, {nby / 2**20:.0f} MiB "
            f"-> {W_BASE:#x}..{fmt_top(wtop)} ({cs})"
            + ("  [readback OK]" if verify else ""))
        if art.embf:
            emb = open(art.embf, "rb").read()
            put("embedding", plan["emb_base"], emb)
            log(f"  embedding {len(emb) / 2**20:.0f} MiB -> "
                f"{plan['emb_base']:#x}"
                + ("  [readback OK]" if verify else ""))
    else:
        log("  weights   SKIPPED (--skip-weights: assumed resident)")

    blob = art.blob
    if blob:
        put("seqdata", plan["data_base"], blob)
    stream = SF.pack_stream(recs)
    put("stream", plan["stream_base"], stream)
    log(f"  seqdata   {len(blob)} B -> {plan['data_base']:#x}"
        + ("  [readback OK]" if verify else ""))
    log(f"  stream    {len(stream)} B ({len(recs)} records) -> "
        f"{plan['stream_base']:#x}"
        + ("  [readback OK]" if verify else ""))
    # S3 (spec 7.1): the DDR state region's initial contents, and the three
    # base CSRs.  It rides on the same H2C path as the weights and is
    # skipped with them (`--skip-weights` means "assumed resident").
    rep["state"] = upload_state(dev, art, log=log, verify=verify,
                                csrs_only=not do_weights)
    rep["seconds"] = round(time.monotonic() - t0, 1)
    rep["stream_sha256_relocated"] = hashlib.sha256(stream).hexdigest()
    rep["wbase_of"] = {str(k): _hexb(v) for k, v in sorted(wbase_of.items())}
    rep["weight_top"] = fmt_top(wtop)
    return rep, wbase_of, stream


# ---------------------------------------------------------------------
# S3 (SEQ_ISA v2.1 B15.3, spec 7.1): the DDR state region
# ---------------------------------------------------------------------
def verify_state_image(art):
    """Spec 7.2: the manifest carries the region's sha — CHECK it.

    `<base>.state.bin` is the region's initial image and `state["sha256"]`
    is the sha256 of ITS BYTES (S3 fix round 1, M6 made it so).  A stream
    replayed against a re-planned or re-emitted region is exactly what spec
    7.2 forbids, and this is where the host can see it: before it writes a
    byte.  Returns the digest, or None when the artifact declares no region.

    A MANIFEST THAT DECLARES A REGION AND NO DIGEST IS REFUSED (#156, triage
    (b)10).  `if want and got != want` used to let it through: an artifact
    with `state` but no `state["sha256"]` computed the digest, compared it
    with nothing, and returned it — so `upload_state` wrote 24 MiB into the
    board's DDR with the ONE check that this image belongs to this stream
    silently skipped, and the caller could not tell that from a pass.  An
    absent digest is not a waiver; it is a manifest this host cannot verify,
    and the only artifacts that carry one are pre-v2.1 ones, which declare no
    `state` at all and return None above.
    """
    st = getattr(art, "state", None)
    if st is None:
        return None
    path = art.base + ".state.bin"
    want = st.get("sha256")
    if not want:
        raise SeqError(
            f"{path}: the manifest declares a state region "
            f"(dn={st.get('dn')!r} end={st.get('end')!r}) but carries no "
            f"state['sha256'] — this host cannot verify that the region "
            f"image belongs to this stream, and spec 7.2 makes that check "
            f"the precondition of the upload.  Re-emit the artifact with an "
            f"emitter that writes the digest (#156)")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    got = h.hexdigest()
    if got != want:
        raise SeqError(
            f"{path} sha256 {got[:16]} but the manifest's state plan says "
            f"{want[:16]} — this artifact's region image and its manifest "
            f"are from different emissions (spec 7.2)")
    return got


def upload_state(dev, art, log=print, verify=True, csrs_only=False):
    """Write the region's INITIAL contents and program the three base CSRs.

    Spec 2 "Initial contents": DN blocks zero, conv blocks the artifact's
    weight taps with the state words zero, KV blocks never read before they
    are written (TCNT = 0 after a session reset).  So the upload is a memset
    of the DN region plus one write per conv image; the KV region is left
    alone, which is 128 MiB of DMA this host does not do.

    The addresses are the manifest's (`sw/hwmap.plan_state`), and they are
    34-bit GLOBAL addresses: bits [33:32] are the channel, exactly as the
    layer's `m_axis` master sees them through the SmartConnect.
    """
    st = art.state
    if st is None:
        log("  state     none (pre-v2.1 artifact: no SLD/SST in the stream)")
        return None
    rep = {"dn": hex(st["dn"]), "kv": hex(st["kv"]), "cv": hex(st["cv"]),
           "end": hex(st["end"]), "sha256": st.get("sha256", "")[:16]}
    t0 = time.monotonic()
    chan = st["dn"] >> 32
    rep["image_sha256"] = (verify_state_image(art) or "")[:16]
    if csrs_only:
        # `--skip-weights` means the DATA is assumed resident; the three
        # base CSRs are NOT, because a reprogram clears them and
        # `seq_check_state_bases` would then refuse a perfectly good
        # region.  Programming them costs three AXI-Lite writes.
        for csr, key in ((L_SB_DN, "dn"), (L_SB_KV, "kv"), (L_SB_CV, "cv")):
            dev.wr(csr, st[key] // STATE_BASE_UNIT)
        log(f"  state     CSRs only (--skip-weights): SB_* <- "
            f"{st['dn'] // STATE_BASE_UNIT:#x}/"
            f"{st['kv'] // STATE_BASE_UNIT:#x}/"
            f"{st['cv'] // STATE_BASE_UNIT:#x}")
        rep["csrs_only"] = True
        return rep
    zero = bytes(STATE_DN_LAYER)
    ndn = (st["kv"] - st["dn"]) // STATE_DN_LAYER
    for i in range(ndn):
        dev.dma_write_chan(chan, (st["dn"] & 0xFFFF_FFFF)
                           + i * STATE_DN_LAYER, zero)
    # S3 fix round 1, I6: spec 7.1 audits the region like it audits the
    # weights, and a memset nobody reads back is not an audit.  Eight 4 KiB
    # witnesses spread over the DN region, first and last included, must all
    # read zero.
    nbad = 0
    if verify:
        for a in state_dn_witnesses(st):
            blk = dev.dma_read_chan(chan, a & 0xFFFF_FFFF, 4096)
            if blk != bytes(4096):
                nbad += 1
                log(f"  state DN  WITNESS {a:#x} is NOT zero")
        if nbad:
            raise SeqError(f"{nbad} DN-region witness block(s) are not zero "
                           f"after the memset (spec 2 'Initial contents')")
    log(f"  state DN  {ndn * STATE_DN_LAYER / 2**20:.0f} MiB zeroed -> "
        f"{st['dn']:#x} (chan {chan})"
        + ("  [8 witnesses zero]" if verify else ""))
    ncv = 0
    for ci in (art.conv_images or []):
        img = open(os.path.join(art.wdir, ci["file"]), "rb").read()
        if len(img) != int(ci["bytes"]):
            raise SeqError(f"conv image {ci['file']} is {len(img)} B, "
                           f"manifest says {ci['bytes']}")
        a = (st["cv"] & 0xFFFF_FFFF) + int(ci["layer"]) * STATE_CV_STRIDE
        dev.dma_write_chan(chan, a, img)
        if verify:
            dev.dma_verify_chan(chan, a, img,
                                tag=f"conv image L{ci['layer']}")
        ncv += 1
    log(f"  state CV  {ncv} conv image(s) -> {st['cv']:#x}"
        + ("  [readback OK]" if verify and ncv else ""))
    for csr, key, nm in ((L_SB_DN, "dn", "SB_DN"), (L_SB_KV, "kv", "SB_KV"),
                         (L_SB_CV, "cv", "SB_CV")):
        dev.wr(csr, st[key] // STATE_BASE_UNIT)
    rep["dn_blocks_zeroed"] = ndn
    rep["conv_images"] = ncv
    rep["seconds"] = round(time.monotonic() - t0, 1)
    return rep


def seq_check_state_bases(dev, art, log=print):
    """Spec 7.2's first "never": launch a program whose base CSRs are zero.

    The RTL answers E_DMA_BASE at the first SLD/SST and the program halts,
    which is correct but late and opaque.  This reads the three CSRs back
    and refuses HERE, naming the one that is zero.
    """
    st = art.state
    if st is None:
        return {}
    got = {}
    for csr, key, nm in ((L_SB_DN, "dn", "SB_DN"), (L_SB_KV, "kv", "SB_KV"),
                         (L_SB_CV, "cv", "SB_CV")):
        v = dev.rd(csr)
        got[nm] = v
        want = st[key] // STATE_BASE_UNIT
        if v == 0:
            raise SeqError(
                f"{nm} reads 0: the DDR state region was never programmed, "
                f"and the first SLD/SST would halt the program with "
                f"E_DMA_BASE (SEQ_ISA v2.1 B15.4). Run the upload first.")
        if v != want:
            raise SeqError(
                f"{nm} reads {v:#x}, the artifact's plan says {want:#x} — "
                f"this stream was emitted for a different region (spec 7.2)")
    log(f"  state CSR SB_DN={got['SB_DN']:#x} SB_KV={got['SB_KV']:#x} "
        f"SB_CV={got['SB_CV']:#x}  [readback OK]")
    return got


def seq_set_emb_row_bytes(dev, row_bytes, log=print):
    """Program EMBLOG2 (R-b) before any EMB record runs.

    `row_bytes` comes from the artifact manifest (2*H).  The write is
    unconditional — EMBLOG2 is not cleared by START, but it IS cleared by a
    reprogram, and a stale value from another model would silently fetch the
    wrong embedding row — and it is verified by readback.

    Back-compat: a pre-R-b bitstream has no such CSR, so the write is dropped
    and the offset reads 0xDEADC0DE.  That is only fatal when the model
    actually needs a non-default row size; at the reset value
    (1 << SEQ_EMBLOG2_RST B — G3.4 moved it to 8192 B, H 4096) the old
    bitstream is already correct and the run continues.
    """
    want = seq_emb_log2(row_bytes)
    dev.seq_wr(S_EMBLOG2, want)
    got = dev.seq_rd(S_EMBLOG2)
    if got == SEQ_CSR_UNMAPPED:
        if want != SEQ_EMBLOG2_RST:
            raise SeqError(
                f"this bitstream has no EMBLOG2 CSR (SEQ {S_EMBLOG2:#x} reads "
                f"{got:#010x}), but the artifact needs {row_bytes} B embedding "
                f"rows — it can only run the {1 << SEQ_EMBLOG2_RST} B geometry")
        log(f"  EMBLOG2    absent (pre-R-b bitstream); its fixed "
            f"{1 << SEQ_EMBLOG2_RST} B row matches this artifact")
        return None
    if (got & 0x1F) != want:
        raise SeqError(f"SEQ EMBLOG2 read back {got:#x}, wrote {want}")
    log(f"  EMBLOG2    {want} ({row_bytes} B embedding rows)")
    return want


def seq_start_and_poll(dev, art, plan, timeout=DEFAULT_TIMEOUT, entry=0,
                       init_xrf=True, log=print):
    """START, poll STATUS while draining OUT_FIFO, return the run report."""
    dev.require_seq("a sequencer run")
    st = dev.seq_status()
    if st["busy"]:
        raise SeqError(f"the sequencer is already busy (STATUS={st['raw']:#x})"
                       " — another host has it, or a previous run hung")
    stale = dev.seq_drain_fifo()
    if stale:
        log(f"  drained {len(stale)} stale OUT FIFO entries: {stale}")
    if init_xrf:
        for i in range(SEQ_XRF_N):
            dev.seq_wr(s_xrf(i), 0)
    dev.seq_wr(S_TCNT_SEQ, 0)
    # R-b: the EMB row size, before any EMB record can fetch with it
    seq_set_emb_row_bytes(dev, getattr(art, "emb_row_bytes",
                                       EMB_ROW_BYTES_DEFAULT), log=log)
    # S3 (spec 7.2): the DDR state region's three base CSRs must be
    # programmed and must agree with the artifact, or the first SLD/SST
    # halts the program with E_DMA_BASE.
    seq_check_state_bases(dev, art, log=log)
    base = plan["seq_base"]
    dev.seq_wr(S_BASE_LO, base & 0xFFFFFFFF)
    dev.seq_wr(S_BASE_HI, (base >> 32) & 0x3)
    dev.seq_wr(S_LEN, art.nrec)
    dev.seq_wr(S_ENTRY, entry)
    for a, want, nm in ((S_BASE_LO, base & 0xFFFFFFFF, "BASE_LO"),
                        (S_BASE_HI, (base >> 32) & 0x3, "BASE_HI"),
                        (S_LEN, art.nrec, "LEN"),
                        (S_ENTRY, entry, "ENTRY")):
        got = dev.seq_rd(a)
        if got != want:
            raise SeqError(f"SEQ {nm} read back {got:#x}, wrote {want:#x}")
    log(f"  SEQ_BASE={base:#x} LEN={art.nrec} ENTRY={entry} -> START")

    tokens, t0, last_pc, of_hwm, of_ovf = [], time.monotonic(), -1, 0, False
    dev.seq_wr(S_CTRL, SEQ_CTRL_START)
    while True:
        st = dev.seq_status()
        of_hwm = max(of_hwm, st["out_cnt"])
        of_ovf = of_ovf or st.get("of_ovf", False)
        if st["out_cnt"]:
            tokens += dev.seq_drain_fifo()
        if not st["busy"]:
            break
        dt = time.monotonic() - t0
        if dt > timeout:
            pc = dev.seq_rd(S_PC)
            dev.seq_wr(S_CTRL, SEQ_CTRL_ABORT)
            time.sleep(0.05)
            st = dev.seq_status()
            raise SeqError(
                f"sequencer timeout after {dt:.1f}s at pc={pc} "
                f"(STATUS={st['raw']:#010x}, err_code={st['err_code']:#04x} "
                f"{seq_err_name(st['err_code'])}); ABORT was issued\n"
                + disasm_window(art.recs, min(pc, art.nrec - 1)))
        time.sleep(POLL_S)
        pc = dev.seq_rd(S_PC)
        if pc // 4096 != last_pc // 4096:
            last_pc = pc
            log(f"    pc {pc}/{art.nrec}  ({dt:.1f}s)")
    wall = time.monotonic() - t0
    tokens += dev.seq_drain_fifo()
    pc = dev.seq_rd(S_PC)
    perf = dev.seq_perf()
    ctrl = dev.seq_rd(S_CTRL)
    of_ovf = of_ovf or st.get("of_ovf", False)
    run = {"pc": pc, "status": st, "ctrl": ctrl, "tokens": tokens,
           "wall_s": round(wall, 3), "perf": perf,
           "out_fifo_high_water": of_hwm, "out_fifo_ovf": bool(of_ovf),
           "device_ms": round(perf["cyc"] / ACLK_HZ * 1e3, 3)}
    if of_ovf:
        # rung 4 S6: of_ovf is STICKY UNTIL RESET (the xrf_ovf precedent),
        # so this is an alarm about the whole power-on, not this launch: a
        # push found the 64-deep FIFO full and the token was DROPPED.  Every
        # token list read since then is suspect, including this one.
        run["warn_fifo_ovf"] = (
            f"STATUS of_ovf is SET (STATUS={st['raw']:#010x}): the OUT FIFO "
            f"dropped at least one token since the last RESET.  The bit is "
            f"sticky until reset, so it may predate this run — but the token "
            f"stream cannot be trusted until the board is reprogrammed/reset "
            f"and the run repeated.")
        log("  WARNING  " + run["warn_fifo_ovf"])
    elif of_hwm >= SEQ_OUT_DEPTH:
        run["warn_fifo_full"] = (
            f"OUT FIFO reached {of_hwm}/{SEQ_OUT_DEPTH} entries — seq_unit "
            f"DROPS pushes past {SEQ_OUT_DEPTH}, so a token may be missing")
    return run


def failure_report(art, run, n_last=12):
    st = run["status"]
    pc = run["pc"]
    out = [f"SEQ HALTED WITH err_code={st['err_code']:#04x} "
           f"({seq_err_name(st['err_code'])})",
           f"  STATUS={st['raw']:#010x} busy={st['busy']} err={st['err']} "
           f"halted={st['halted']} out_cnt={st['out_cnt']}",
           f"  PC={pc} of {art.nrec} records"]
    if pc < art.nrec:
        out.append(f"  failing record: {SF.disasm(art.recs[pc], pc)}")
        out.append(f"  last {n_last} records issued before it "
                   f"(static ARG shadow — approximate after a taken JMP):")
        out.append(disasm_window(art.recs, pc, n_before=n_last, n_after=1))
    else:
        out.append("  PC is outside the stream (err 0x09): SEQ_LEN or a JMP "
                   "target is wrong")
    out.append(f"  perf: {run['perf']}")
    return "\n".join(out)


def verify_chip_golden(dev, art, run, golden, log=print, mem_limit=None):
    """Post-halt architectural state vs a gen_seq_chip_vectors .chip golden.

    Only called AFTER the sequencer has halted: reading layer_chan CSRs while
    SEQ_STATUS.busy would violate the ISA's arbitration rule.
    """
    bad, checked = [], 0
    if golden.get("nrec") != art.nrec:
        bad.append(f"golden NREC {golden.get('nrec')} != stream {art.nrec}")
    if run["pc"] != golden.get("pc"):
        bad.append(f"PC {run['pc']} != golden {golden.get('pc')}")
    checked += 2
    for i, want in sorted(golden["xrf"].items()):
        got = dev.seq_rd(s_xrf(i)) & 0x3FFFF
        checked += 1
        if got != want:
            bad.append(f"SEQ XRF[{i}] = {got:#07x} want {want:#07x}")
    # layer_chan's XRF is a MIRROR, and only a partial one: seq_unit writes
    # through the entries a RECORD sets (CSRWR to the 0x2nn space, XOP,
    # AMAXL) but NOT the ones it refreshes by reading layer_chan
    # (rtl/seq_unit.sv I_XRFRDW: DYNQ8 -> XRF[0] from EOUT).  So XRF[0] is
    # expected to disagree and the mirror is reported, never gated on.
    mirror = {}
    for i in sorted(golden["xrf"]):
        mirror[i] = dev.layer_xrf(i)
    mism = [i for i, v in mirror.items() if v != golden["xrf"][i]]
    if mism:
        log(f"  mirror    layer_chan XRF differs from the SEQ copy at "
            f"{mism} (informational: index 0 is a read-refresh, not a "
            f"write-through)")
    d = first_divergence(run["tokens"], golden["tok"], "chip", "golden")
    checked += 1
    if d:
        bad.append("OUT FIFO vs golden: " + d)
    for s, (a, b) in sorted(golden["tcnt"].items()):
        got = dev.layer_tcnt(s)
        checked += 1
        if got != (a, b):
            bad.append(f"TCNT[{s}] = {got} want {(a, b)}")
    got = dev.rd(L_EOUT) & 0xF
    checked += 1
    if got != golden.get("eout"):
        bad.append(f"EOUT = {got} want {golden.get('eout')}")
    gi, gv = dev.rd(L_AMAXI) & 0x3FFFF, dev.rd(L_AMAXV)
    checked += 2
    if (gi, gv) != tuple(golden.get("amax", (None, None))):
        bad.append(f"AMAX = ({gi}, {gv:#010x}) want {golden.get('amax')}")
    addrs = sorted(golden["mem"])
    if mem_limit is not None:
        addrs = addrs[:mem_limit]
    if addrs:
        scr = dev.layer_read_scratch(0, SCRATCH_WORDS_BUILT)
        nbad = 0
        for a in addrs:
            checked += 1
            if int(scr[a]) != golden["mem"][a]:
                nbad += 1
                if nbad <= 8:
                    bad.append(f"scratch[{a:#06x}] = {int(scr[a]):#06x} want "
                               f"{golden['mem'][a]:#06x}")
        if nbad > 8:
            bad.append(f"... {nbad - 8} further scratch mismatches "
                       f"({nbad}/{len(addrs)} checked words differ)")
    log(f"  golden    {checked} state checks, "
        + ("ALL MATCH" if not bad else f"{len(bad)} MISMATCH"))
    return (not bad), bad, checked, mirror


# ======================================================================
# offline model of the seq_unit CSR slave — exercises the RUN protocol
# (START / poll / read-drain / error halt) with no board attached.
# ======================================================================
class _FakeSeqDev(Dev):
    """rtl/seq_unit.sv's AXI-Lite slave, in python, plus a scripted "run".

    Register semantics are the RTL's: START is ignored while busy, OUT_FIFO
    reads pop, STATUS packs {err_code, out_cnt, halted, err, busy}.  The run
    itself is scripted (halt pc, err_code, token list) so the host protocol —
    not the sequencer — is what gets tested.
    """

    def __init__(self, halt_pc, tokens, err_code=0, golden=None,
                 busy_polls=2, has_emblog2=True, bm=None):
        self.seq_ok, self.seq_why = True, "offline seq_unit model"
        # BM1 (SEQ_ISA B16): bm=None models build_041 and older -- the 0x100
        # block is outside the map and reads 0xDEADC0DE; a dict {offset from
        # S_BM_IDENT: value} models a BM1 bitstream (unlisted words read 0).
        self.bm = bm
        # has_emblog2=False models a PRE-R-b bitstream: the CSR is outside the
        # map, so writes are dropped and reads return 0xDEADC0DE
        self.has_emblog2 = has_emblog2
        self.chan, self.ddr_off, self.n_rd, self.n_wr = 0, 0, 0, 0
        self.log = lambda *a, **k: None
        self.ident = {"version": EXPECTED_SEQ_VERSION}
        self.regs = {S_BASE_LO: 0, S_BASE_HI: 0, S_LEN: 0, S_ENTRY: 0,
                     S_TCNT_SEQ: 0, L_SPTR: 0, L_XRFI: 0, L_LAYER: 0,
                     S_EMBLOG2: SEQ_EMBLOG2_RST}
        self.xrf = [0] * SEQ_XRF_N
        self.g = golden or {}
        self._halt_pc, self._tok, self._err = halt_pc, list(tokens), err_code
        self._busy, self._halted, self._pc, self._fifo = False, False, 0, []
        self._of_ovf = False           # rung 4 S6: sticky until "reset"
        self._scratch_zeroed = False   # R-d: --zero-scratch was applied
        self._polls, self._busy_polls = 0, busy_polls

    # ---- the scripted run ----
    def _tick(self):
        if not self._busy:
            return
        self._polls += 1
        if self._polls >= self._busy_polls:
            self._busy, self._halted = False, True
            self._pc = self._halt_pc
            room = SEQ_OUT_DEPTH - len(self._fifo)
            if len(self._tok) > room:          # S6: pushes past 64 are DROPPED
                self._of_ovf = True
            self._fifo += self._tok[:max(0, room)]

    def rd(self, a):
        self.n_rd += 1
        if a == S_STATUS:
            self._tick()
            # rung 4 S6: out_cnt is 7 bits at [22:16] and of_ovf is bit 23
            return ((self._err << 24)
                    | (SEQ_ST_OF_OVF if self._of_ovf else 0)
                    | ((len(self._fifo) & SEQ_ST_OUTCNT_MASK) << 16)
                    | (0x4 if self._halted else 0) | (0x2 if self._err else 0)
                    | (0x1 if self._busy else 0))
        if a == S_CTRL:
            return ((0x4 if self._halted else 0) | (0x2 if self._err else 0)
                    | (0x1 if self._busy else 0))
        if a == S_PC:
            return self._pc
        if a == S_OUT_CNT:
            return len(self._fifo) & 0x7F
        if a == S_OUT_FIFO:
            if not self._fifo:
                return 0
            return SEQ_OUT_VALID | (self._fifo.pop(0) & SEQ_OUT_TOK_MASK)
        if a == S_IDENT:
            return SEQ_IDENT
        if S_BM_IDENT <= a < S_BM_IDENT + 0x100:
            if self.bm is None:
                return SEQ_CSR_UNMAPPED
            return self.bm.get(a - S_BM_IDENT, 0)
        if a in (S_PERF_CYC, S_PERF_REC, S_PERF_AXW, S_PERF_AXR, S_PERF_FST):
            return {S_PERF_CYC: 181310224, S_PERF_REC: 60495,
                    S_PERF_AXW: 7724372, S_PERF_AXR: 17502428,
                    S_PERF_FST: 0}[a]
        if a == S_EMBLOG2 and not self.has_emblog2:
            return SEQ_CSR_UNMAPPED
        if S_XRF0 <= a < S_XRF0 + 4 * SEQ_XRF_N:
            i = (a - S_XRF0) // 4
            return self.g.get("xrf", {}).get(i, self.xrf[i])
        if a == L_EOUT:
            return self.g.get("eout", 0)
        if a == L_AMAXI:
            return self.g.get("amax", (0, 0))[0]
        if a == L_AMAXV:
            return self.g.get("amax", (0, 0))[1]
        if a == L_TCNT:
            s = (self.regs[L_LAYER] >> 8) & 0x7
            lo, hi = self.g.get("tcnt", {}).get(s, (0, 0))
            return (hi << 16) | lo
        if a == L_XRFD:
            return self.g.get("xrf", {}).get(self.regs[L_XRFI], 0)
        return self.regs.get(a, 0)

    def wr(self, a, v):
        self.n_wr += 1
        v = int(v) & 0xFFFFFFFF
        if a == S_CTRL:
            if (v & SEQ_CTRL_START) and not self._busy:
                self._busy, self._halted, self._polls = True, False, 0
                self._pc = self.regs[S_ENTRY]
            if v & SEQ_CTRL_ABORT:
                self._busy, self._halted, self._err = False, True, 0x0C
            return
        if S_XRF0 <= a < S_XRF0 + 4 * SEQ_XRF_N:
            self.xrf[(a - S_XRF0) // 4] = v & 0x3FFFF
            return
        if a == S_EMBLOG2:
            # the RTL keeps 5 bits and REJECTS anything outside [8,13]
            if not self.has_emblog2:
                return
            if HW.SEQ_EMBLOG2_MIN <= (v & 0x1F) <= HW.SEQ_EMBLOG2_MAX:
                self.regs[a] = v & 0x1F
            return
        self.regs[a] = v

    def layer_read_scratch(self, addr, n=SCRATCH_WORDS_BUILT):
        # Before the run the pad holds whatever the last owner left (or
        # zeros once --zero-scratch has cleared it); after the halt it holds
        # the golden state this fake is built from.  Modelling the two
        # phases is what lets the selftest exercise the R-d clear.
        mem = ({} if self._scratch_zeroed and not self._halted
               else self.g.get("mem", {}))
        return np.array([mem.get(addr + i, 0) for i in range(n)],
                        dtype=np.int64)

    def layer_zero_scratch(self, n=SCRATCH_WORDS_BUILT):
        self.wr(L_SPTR, 0)
        for _ in range(n):
            self.wr(L_SWIN, 0)
        self._scratch_zeroed = True


# ======================================================================
# self-test (pure python; no board)
# ======================================================================
def _selftest(prefixes=None, log=print):
    """Unit-test the pure-python pieces against real gate artifacts."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cand = prefixes or [
        os.path.join(here, "tb", "scripts", "w3", "lay_s1.e"),
        os.path.join(here, "tb", "scripts", "w3", "tok2_s1.e"),
        os.path.join(here, "tb", "scripts", "w4", "model_v2_s1.e"),
        # rung 4 S4: the opt-in 4-chan stream, when it has been emitted
        os.path.join(here, "tb", "scripts", "w4", "model_v2_s1.e4"),
    ]
    cand = [p for p in cand if os.path.exists(p + ".seq.json")]
    if not cand:
        raise SystemExit("selftest: no .seq artifacts found — emit some with "
                         "SEQ_EMIT=<prefix> (tb/Makefile seq_chip_scripts)")
    # R-c: a REPACKED artifact goes through the SAME loop, because that loop
    # is the gate Task 4/6 run first on their new artifact and every line of
    # it has to survive a per-channel pack.  Built here rather than committed
    # so it tracks the emitter (it is produced by the real allocator).
    _tmp = None
    if prefixes is None:
        _tmp = tempfile.mkdtemp(prefix="fable5_rp_")
        cand.append(write_synth_repack_artifact(_tmp))
    npass = nfail = 0

    def check(name, cond, detail=""):
        nonlocal npass, nfail
        if cond:
            npass += 1
        else:
            nfail += 1
            log(f"    FAIL {name}: {detail}")
        return cond

    def _raises(fn, exc=Exception):
        """True when `fn()` refuses — a guard that never fires proves
        nothing."""
        try:
            fn()
        except exc:
            return True
        return False

    # ---- derive_base ----
    for p in cand:
        b = derive_base(p)
        check(f"derive_base({os.path.basename(p)})",
              os.path.exists(b + ".weights.json"),
              f"{b}.weights.json missing")

    for p in cand:
        log(f"  --- {p}")
        art = Artifacts(p)
        meta = art.meta
        # ---- 1. artifacts: hashes + validator + record count ----
        check("nrec == len(recs)", art.nrec == meta["nrec"])
        check("stream is 16B records",
              len(art.stream) == art.nrec * SEQ_REC_BYTES)
        check("halt_pc is the last record",
              art.halt_pc() == art.nrec - 1,
              f"halt_pc={art.halt_pc()} nrec={art.nrec}")

        # ---- 2. expected-token extraction ----
        toks = expected_tokens(meta)
        check("expect_tokens == metadata", toks == meta["expect_tokens"])
        check("one expected token per decode step",
              len(toks) == meta["steps"] - len(meta.get("prompt_fed", []))
              or len(toks) == meta["steps"],
              f"{len(toks)} tokens vs {meta['steps']} steps")
        # first_divergence contract
        check("first_divergence(equal) is None",
              first_divergence(toks, list(toks)) is None)
        if toks:
            m = list(toks)
            m[0] = m[0] + 1
            d = first_divergence(m, toks)
            check("first_divergence finds index 0",
                  d is not None and "token 0" in d, repr(d))
            d = first_divergence(toks[:-1], toks)
            check("first_divergence reports a short run",
                  d is not None and "common prefix" in d, repr(d))

        # ---- 3. address planning ----
        plan = plan_ddr(meta, len(art.stream), len(art.blob), chan=0)
        check("stream base is the hwmap one",
              plan["stream_base"] == SEQ_STREAM_BASE)
        check("data delta rebases the emitter blob",
              plan["data_delta"] == SEQ_DATA_BASE - meta["seq_data_base"])
        check("emb delta is 0 (emitter reads hwmap.EMB_BASE)",
              plan["emb_delta"] == 0, f"{plan['emb_delta']}")
        check("stream fits its window", len(art.stream) <= SEQ_STREAM_MAX)
        check("blob fits its window", len(art.blob) <= SEQ_DATA_MAX)
        check("stream/blob/weights/emb are disjoint",
              SEQ_STREAM_BASE + len(art.stream) <= SEQ_DATA_BASE
              and SEQ_DATA_BASE + len(art.blob) <= W_BASE)
        for c in (1, 2, 3):
            pc_ = plan_ddr(meta, len(art.stream), len(art.blob), chan=c) \
                if int(meta.get("chan", 0)) == c else None
            if pc_ is not None:
                check(f"chan {c} adds CH_STRIDE",
                      pc_["seq_base"] == c * CH_STRIDE + SEQ_STREAM_BASE)
        try:
            plan_ddr(meta, SEQ_STREAM_MAX + 1, len(art.blob), chan=0)
            check("oversized stream is rejected", False)
        except SeqError:
            check("oversized stream is rejected", True)
        try:
            plan_ddr(meta, len(art.stream), SEQ_DATA_MAX + 1, chan=0)
            check("oversized blob is rejected", False)
        except SeqError:
            check("oversized blob is rejected", True)

        # ---- 4. relocation ----
        recs2, rrep = relocate(art.recs, meta, plan, len(art.blob))
        check("relocation preserves the record count",
              len(recs2) == len(art.recs))
        nldc = sum(1 for r in art.recs if r.opcode == SF.EXT_LDC)
        nemb = sum(1 for r in art.recs if r.opcode == SF.OP_EMB)
        check("every LDC relocated", rrep["ldc"] == nldc,
              f"{rrep['ldc']} != {nldc}")
        check("every EMB visited", rrep["emb"] == nemb)
        moved = [(a, b) for a, b in zip(art.recs, recs2)
                 if a.to_bytes() != b.to_bytes()]
        check("only LDC/EMB records changed",
              all(a.opcode in (SF.EXT_LDC, SF.OP_EMB) for a, _b in moved))
        check("non-LDC/EMB records are byte-identical",
              all(a.to_bytes() == b.to_bytes()
                  for a, b in zip(art.recs, recs2)
                  if a.opcode not in (SF.EXT_LDC, SF.OP_EMB)))
        for a, b in zip(art.recs, recs2):
            if a.opcode == SF.EXT_LDC:
                if not check("LDC delta is exact",
                             _rec_addr64(b) - _rec_addr64(a)
                             == plan["data_delta"]):
                    break
                if not check("LDC flags/target/imm survive",
                             (a.flags, a.target, a.imm32)
                             == (b.flags, b.target, b.imm32)):
                    break
        offs = [_rec_addr64(r) - plan["data_base"]
                for r in recs2 if r.opcode == SF.EXT_LDC]
        check("every relocated LDC lands inside the uploaded blob",
              all(0 <= o < len(art.blob) for o in offs),
              f"min={min(offs) if offs else None} "
              f"max={max(offs) if offs else None} blob={len(art.blob)}")
        check("relocation is idempotent under a zero delta",
              relocate(recs2, dict(meta, seq_data_base=plan["data_base"],
                                   emb_base=plan["emb_base"]),
                       dict(plan, data_delta=0, emb_delta=0),
                       len(art.blob))[0][0].to_bytes()
              == recs2[0].to_bytes())
        # a corrupt blob address must be caught
        badrec = [SF.Rec(SF.EXT_LDC, imm32=8,
                         addr_lo=(meta["seq_data_base"] - 64) & 0xFFFFFFFF,
                         len_or_addr_hi=(meta["seq_data_base"] - 64) >> 32)]
        try:
            relocate(badrec, meta, plan, len(art.blob))
            check("out-of-blob LDC is rejected", False)
        except SeqError:
            check("out-of-blob LDC is rejected", True)

        # ---- 5. weight plan == sw/hwmap.py:plan_weights ----
        # TWO plans, and the difference matters: `wbase_of` is THIS STREAM's
        # pack (per-channel when the stream says weight_repack), while
        # `flat_*` is the nch-INDEPENDENT pack that blocks 5b-5e explore
        # synthetically at nch=4.  Mixing them is how the repacked path
        # crashed the selftest before R-c's review.
        wbase_of, wtop = plan_weights_for(art.manifest, art.wdir, meta)
        flat_base, flat_top = plan_weights(art.manifest, art.wdir)
        check_weight_plan(meta, wbase_of, art.manifest)
        check("weight pack ends below EMB_BASE on every channel",
              all(t < EMB_BASE for t in _tops(wtop)),
              fmt_top(wtop))
        nmv = check_mvgo_targets(art.recs, wbase_of, art.manifest, meta)
        check("every MVGO WBASE is row-aligned inside an image",
              nmv == sum(1 for r in art.recs if r.opcode == SF.OP_MVGO))
        try:
            check_weight_plan(dict(meta, weights=dict(
                (k, dict(v, base=_shift_bases(v["base"], 64)))
                for k, v in meta["weights"].items())), wbase_of, art.manifest)
            check("a shifted weight plan is rejected", False)
        except SeqError:
            check("a shifted weight plan is rejected", True)
        # V5: the weight WIDTH must agree too.  A stream whose MVGO SHAPE
        # words say W8 over a W4 image (or the reverse) would have the
        # engine read int8 weight bytes as nibbles — silently wrong y32,
        # not an error, so it is checked here rather than inferred.
        try:
            check_weight_plan(dict(meta, weights=dict(
                (k, dict(v, w8=True)) for k, v in meta["weights"].items())),
                wbase_of, art.manifest)
            check("a W8 plan over W4 images is rejected", False)
        except SeqError:
            check("a W8 plan over W4 images is rejected", True)

        # ---- 5b. rung-1b 4-channel weight-split planning + addressing ----
        # Build a synthetic 4-chan meta from the real one; the fetch path
        # (stream/blob/emb) must be untouched and the weight images must be
        # row-split across chans 0..3 exactly as tok_meter.py:308-320 does.
        # `meta1` is a 1-chan view of this artifact's metadata: for a
        # committed 1-chan stream it IS the metadata, and for the rung-4
        # e4 stream it is the single-channel control case.
        # The synthetic explorations below (5b-5e) are about the
        # nch-INDEPENDENT pack, so they must not inherit a repacked artifact's
        # weight_repack flag — `flat_base` is the plan they go with.
        meta1 = dict(meta, nch=1, chan=0)
        meta1.pop("weight_repack", None)
        meta1.pop("weight_layout", None)
        p1 = plan_ddr(meta1, len(art.stream), len(art.blob), chan=0)
        meta4 = dict(meta, nch=4, chan=0)
        meta4.pop("weight_repack", None)
        p4 = plan_ddr(meta4, len(art.stream), len(art.blob), chan=0)
        check("4-chan plan reports nch=4", p4["nch"] == 4)
        check("4-chan weight_chans are 0..3",
              p4["weight_chans"] == [0, 1, 2, 3])
        check("1-chan weight_chans is [fetch]", p1["weight_chans"] == [0])
        fetch_keys = ("seq_base", "data_base", "stream_base", "data_delta",
                      "emb_delta", "emb_base", "ddr_off")
        check("row-split leaves the FETCH path identical",
              all(p4[k] == p1[k] for k in fetch_keys),
              f"{[(k, p4[k], p1[k]) for k in fetch_keys if p4[k] != p1[k]]}")
        # a --chan that is not the emitter's fetch chan is rejected
        try:
            plan_ddr(meta4, len(art.stream), len(art.blob), chan=1)
            check("4-chan rejects a mismatched fetch --chan", False)
        except SeqError:
            check("4-chan rejects a mismatched fetch --chan", True)

        splits = plan_weight_split(art.manifest, flat_base, 4, [0, 1, 2, 3])
        # (a) every image's quarters PARTITION its rows [0, nrows) once,
        #     land at the tok_meter address, and are row-aligned MVGO targets
        per_img = {}
        for s in splits:
            per_img.setdefault(s["wid"], []).append(s)
        cover_ok = addr_ok = align_ok = tok_ok = drop_ok = True
        for wid_s, mm in art.manifest.items():
            wid = int(wid_s)
            nrows, stride = int(mm["nrows"]), int(mm["stride"])
            wb = flat_base[wid]
            pieces = sorted(per_img.get(wid, []), key=lambda s: s["r0"])
            # rows covered contiguously from 0 to nrows, each channel once
            row = 0
            for s in pieces:
                if s["r0"] != row or s["nrows_piece"] <= 0:
                    cover_ok = False
                row += s["nrows_piece"]
                if s["local_addr"] != wb + s["r0"] * stride:
                    addr_ok = False
                if (s["local_addr"] - wb) % stride:
                    align_ok = False
                # tok_meter.py:313-318 formula, recomputed independently
                r0_t, n_t = split_rows(nrows, 4)[s["chan"]]
                tok_abs = s["chan"] * CH_STRIDE + wb + r0_t * stride
                if s["abs_addr"] != tok_abs \
                        or (r0_t, n_t) != (s["r0"], s["nrows_piece"]):
                    tok_ok = False
                # local_addr must be a legal MVGO WBASE for this image
                if not (wb <= s["local_addr"] < wb + nrows * stride):
                    addr_ok = False
            if row != nrows:
                cover_ok = False
            # zero-row channels are dropped (nrows < 4 -> fewer than 4 pieces)
            if nrows < 4 and len(pieces) != nrows:
                drop_ok = False
            if nrows >= 4 and len(pieces) != 4:
                drop_ok = False
        check("4-chan split covers every row exactly once", cover_ok)
        check("4-chan quarters land at wbase+r0*stride", addr_ok)
        check("4-chan quarters are row-aligned MVGO targets", align_ok)
        check("4-chan addressing matches tok_meter:308-320", tok_ok)
        check("zero-row channels are dropped", drop_ok)
        # (b) total bytes == sum of full images; per-channel ranges disjoint
        tot = sum(s["byte_len"] for s in splits)
        full = sum(int(mm["nrows"]) * int(mm["stride"])
                   for mm in art.manifest.values())
        check("4-chan quarters sum to the whole weight footprint", tot == full,
              f"{tot} != {full}")
        for c in range(4):
            ranges = sorted((s["local_addr"], s["byte_len"])
                            for s in splits if s["chan"] == c)
            disj = all(ranges[i][0] + ranges[i][1] <= ranges[i + 1][0]
                       for i in range(len(ranges) - 1))
            check(f"chan {c} quarters are mutually disjoint", disj)
        check("weight pack fits inside one channel (bands disjoint)",
              max(_tops(flat_top)) <= CH_STRIDE)
        # (c) nch=1 is byte-identical to the pre-1b whole-image write
        s1 = plan_weight_split(art.manifest, flat_base, 1, [0])
        check("nch=1 gives one whole-image piece per image",
              len(s1) == len(art.manifest)
              and all(s["r0"] == 0 and s["byte_off"] == 0
                      and s["abs_addr"] == flat_base[s["wid"]] for s in s1))
        # (d) synthetic edge cases: indivisible and nrows<nch
        synth = {"7": {"nrows": 5, "stride": 64},
                 "8": {"nrows": 3, "stride": 64}}
        sb = {7: 0x1000_0000, 8: 0x2000_0000}
        e5 = [s for s in plan_weight_split(synth, sb, 4, [0, 1, 2, 3])
              if s["wid"] == 7]
        check("nrows=5/4 -> row counts 2,1,1,1",
              [s["nrows_piece"] for s in e5] == [2, 1, 1, 1]
              and [s["r0"] for s in e5] == [0, 2, 3, 4])
        e3 = [s for s in plan_weight_split(synth, sb, 4, [0, 1, 2, 3])
              if s["wid"] == 8]
        check("nrows=3/4 -> only 3 channels used, chan 3 dropped",
              [s["chan"] for s in e3] == [0, 1, 2])

        # ---- 5c. rung-4 S4: the INTERLEAVED head placement ----------------
        # The emitter hands chunk j of the LM head to channel j % 4, so the
        # host must place that chunk (not a contiguous quarter) on that
        # channel.  Everything below is recomputed from seq_format so a
        # divergence between emitter and uploader is a FAILURE here, not a
        # wrong token on silicon.
        # G2a review N7: this named an invariant it did not establish.
        # `split_rows` here IS `tok_meter.split_rows` -- line 83 imports it --
        # so the right-hand side is not an independent second implementation
        # and "seq_format == tok_meter" was really "seq_format == the thing
        # seq_format is being compared against".  The import is deliberate
        # (it is what guarantees uploader and emitter agree), so the honest
        # check is the one that has two implementations in it: seq_format's
        # own derivation against the imported partition, named for what it is.
        _sr_same = (split_rows is not SF.split_rows)
        check("tok_meter.split_rows is the IMPORTED partition, not a copy",
              split_rows.__module__ == "tok_meter", split_rows.__module__)
        check("seq_format.split_rows agrees with it over the row/chan grid "
              "(two implementations, one law)",
              _sr_same and all(SF.split_rows(n, k) == split_rows(n, k)
                               for n in (0, 1, 3, 5, 4096, 248320)
                               for k in (1, 2, 3, 4)),
              f"distinct functions: {_sr_same}")
        head_wid = max(int(k) for k in art.manifest)
        m4 = dict(meta4, weight_layout={
            "nch": 4, "chunk_rows": SF.CHUNK_ROWS, "default": SF.LAYOUT_CONTIG,
            "by_wid": {str(head_wid): SF.LAYOUT_ILV},
            "ilv_wids": [head_wid]})
        si = plan_weight_split(art.manifest, flat_base, 4, [0, 1, 2, 3], m4)
        hp = [s for s in si if s["wid"] == head_wid]
        others = [s for s in si if s["wid"] != head_wid]
        oc = [s for s in splits if s["wid"] != head_wid]
        check("S4 leaves every non-head image on the contiguous layout",
              others == oc)
        hrows = int(art.manifest[str(head_wid)]["nrows"])
        hstr = int(art.manifest[str(head_wid)]["stride"])
        check("the head is cut into <=CHUNK_ROWS chunks",
              len(hp) == -(-hrows // SF.CHUNK_ROWS)
              and all(s["nrows_piece"] <= SF.CHUNK_ROWS for s in hp),
              f"{len(hp)} pieces of {hrows} rows")
        check("chunk j lands on channel j % 4 (INTERLEAVED, not quarters)",
              [s["chan"] for s in hp] == [j % 4 for j in range(len(hp))],
              str([s["chan"] for s in hp][:8]))
        check("the interleaved chunks cover every head row exactly once",
              [s["r0"] for s in hp]
              == [j * SF.CHUNK_ROWS for j in range(len(hp))]
              and sum(s["nrows_piece"] for s in hp) == hrows)
        check("every interleaved chunk is a row-aligned MVGO WBASE",
              all(s["local_addr"] == flat_base[head_wid] + s["r0"] * hstr
                  and (s["local_addr"] - flat_base[head_wid]) % hstr == 0
                  for s in hp))
        check("interleaved pieces are disjoint per channel",
              all(_disjoint(sorted((s["local_addr"], s["byte_len"])
                                   for s in hp if s["chan"] == c))
                  for c in range(4)))
        check("S4 writes the whole head, no byte twice",
              sum(s["byte_len"] for s in hp) == hrows * hstr)
        check("the interleaved head is BALANCED across the 4 channels",
              max(sum(s["nrows_piece"] for s in hp if s["chan"] == c)
                  for c in range(4))
              - min(sum(s["nrows_piece"] for s in hp if s["chan"] == c)
                    for c in range(4)) <= SF.CHUNK_ROWS)
        check("a pre-rung-4 meta (no weight_layout) is still contiguous",
              plan_weight_split(art.manifest, flat_base, 4, [0, 1, 2, 3],
                                meta1) == splits)
        check("layout_of defaults to contig for an unknown wid",
              layout_of(m4, 999) == SF.LAYOUT_CONTIG
              and layout_of(m4, head_wid) == SF.LAYOUT_ILV
              and layout_of({}, head_wid) == SF.LAYOUT_CONTIG)
        # the emitter's own map, recomputed: nch=1 never interleaves
        check("nch=1 collapses the interleave to one whole-image piece",
              SF.weight_pieces(hrows, 1, SF.LAYOUT_ILV) == [(0, 0, hrows)])

        # ---- 5d. THE property: every MVGO reads bytes the host wrote ------
        # For a real multi-channel stream, walk the ACTUAL records: each
        # MVGO names an engine channel and a [WBASE, WBASE+beats*64) span,
        # and that span must lie inside a piece plan_weight_split put on
        # THAT channel.  This is what makes the S4 interleave safe; it would
        # fail loudly if emitter and uploader ever disagreed by one chunk.
        # EQUALITY, not containment (R-c review I1): the bytes the host
        # writes to a channel must be exactly the bytes that channel's engine
        # reads.  A containment test passes a stream that reads one chunk of
        # an interleaved image four times and never touches the other three
        # — the exact shape of a broken per-channel rebasing — so this is the
        # check that makes a repacked artifact's placement provable rather
        # than merely plausible.  It runs on EVERY artifact, at every nch.
        nch_a = int(meta.get("nch", 1))
        wchans = (list(range(nch_a)) if nch_a > 1
                  else [int(meta.get("chan", 0))])
        aud = audit_weight_ranges(art.recs, art.manifest, wbase_of,
                                  nch_a, wchans, meta)
        check(f"host-written spans == engine-read spans on all {nch_a} "
              f"channel(s)", aud["ok"],
              f"{len(aud['orphan'])} orphan MVGOs, mismatch {aud['mismatch']}")
        check("the audit is not vacuous (it resolved every MVGO)",
              len(aud["rows"]) == aud["mvgo"] and aud["mvgo"] > 0,
              f"{len(aud['rows'])} of {aud['mvgo']}")
        # ...and it must FAIL when the stream is wrong.  Three mutations, one
        # per way the repack can break: a systematic base shift, the legacy
        # (global-row) address for a repacked image, and every ILV chunk
        # collapsed onto packed row 0.
        killed = []
        for name, mut in (("+32 KiB base shift", _mut_shift),
                          ("ILV chunks collapsed to row 0", _mut_ilv_zero),
                          ("legacy global-row addressing", _mut_global_row)):
            bad_recs = mut(art.recs, art.manifest, wbase_of, nch_a, wchans,
                           meta)
            if bad_recs is None:
                continue                       # not applicable to this stream
            killed.append((name, not audit_weight_ranges(
                bad_recs, art.manifest, wbase_of, nch_a, wchans,
                meta)["ok"]))
        check("the span audit KILLS every address mutation",
              killed and all(k for _n, k in killed),
              str([n for n, k in killed if not k]))
        if nch_a > 1:
            check("...and the stream really does drive all nch engines",
                  len({r.chan for r in art.recs
                       if r.opcode == SF.OP_MVGO}) == nch_a)
            ilv_wids = set((meta.get("weight_layout") or {})
                           .get("ilv_wids", []))
            depth = int((meta.get("weight_layout") or {})
                        .get("chunk_rows", SF.CHUNK_ROWS))
            for w in sorted(ilv_wids):
                # GLOBAL rows, recovered through the host's piece list — the
                # raw `(wbase - base) // stride` this used to compute is the
                # PACKED row under a repack, which is not the same number.
                hs = sorted({(h["chan"], h["row"]) for h in aud["rows"]
                             if h["wid"] == w})
                check(f"wid {w}: the head's chunks are INTERLEAVED "
                      f"(row/chunk_rows mod nch == channel)",
                      hs and all(c == (row // depth) % nch_a
                                 for (c, row) in hs),
                      str(hs[:6]))
                check(f"wid {w}: the head's rows are covered exactly once",
                      sorted(row for (_c, row) in hs)
                      == [j * depth for j in range(len(hs))],
                      f"{len(hs)} distinct chunks")

        # ---- 5e. R-c: the PER-CHANNEL REPACK ------------------------------
        # The same 187 images, planned the other way: each channel packs only
        # the rows it owns (the head chunk-interleaved), which is what makes
        # a 1.85 GiB W8 pack fit a 1,280 MiB window.  Checked against the
        # nch-independent pack above, which must be untouched by all of it.
        rp_meta = dict(m4, weight_repack=True)
        rp_base, rp_top = plan_weights_for(art.manifest, art.wdir, rp_meta)
        check("the repacked plan gives every image a base PER CHANNEL",
              all(isinstance(b, (list, tuple)) and len(b) == 4
                  for b in rp_base.values())
              and isinstance(rp_top, tuple) and len(rp_top) == 4)
        check("a meta WITHOUT weight_repack still plans the one-span pack",
              plan_weights_for(art.manifest, art.wdir, m4)
              == (flat_base, flat_top)
              and plan_weights_for(art.manifest, art.wdir, None)
              == (flat_base, flat_top))
        check("every channel's repacked top is well under the one-span top",
              all(W_BASE < t < flat_top for t in rp_top),
              f"{[hex(t) for t in rp_top]} vs one span {flat_top:#x}")
        check("the repacked pack still ends below EMB_BASE on every channel",
              all(t < EMB_BASE for t in rp_top))
        rs = plan_weight_split(art.manifest, rp_base, 4, [0, 1, 2, 3], rp_meta)
        check("the repack moves ADDRESSES, not which rows a channel gets",
              [(s["wid"], s["chan"], s["r0"], s["nrows_piece"],
                s["byte_off"], s["byte_len"]) for s in rs]
              == [(s["wid"], s["chan"], s["r0"], s["nrows_piece"],
                   s["byte_off"], s["byte_len"]) for s in si])
        rok = aok = pok = True
        for c in range(4):
            mine = [s for s in rs if s["chan"] == c]
            if not _disjoint(sorted((s["local_addr"], s["byte_len"])
                                    for s in mine)):
                rok = False
            for s in mine:
                b = rp_base[s["wid"]][c]
                if s["local_addr"] != b + s["row_off"] * s["stride"]:
                    aok = False
            # per image, this channel's pieces pack back to back from its base
            per = {}
            for s in mine:
                per.setdefault(s["wid"], []).append(s)
            for wid, ps in per.items():
                ps.sort(key=lambda s: s["r0"])
                want = rp_base[wid][c]
                for s in ps:
                    if s["local_addr"] != want:
                        pok = False
                    want += s["byte_len"]
        check("repacked pieces are disjoint on every channel", rok)
        check("every repacked address is chan_base + packed row * stride", aok)
        check("a channel's rows of an image are CONTIGUOUS from its own base",
              pok)
        head_rows = {c: sum(s["nrows_piece"] for s in rs
                            if s["chan"] == c and s["wid"] == head_wid)
                     for c in range(4)}
        check("the ILV head is repacked per channel (strided rows, packed "
              "bytes)",
              sum(head_rows.values()) == hrows
              and all(rp_base[head_wid][c] + head_rows[c] * hstr
                      <= rp_top[c] for c in range(4)),
              str(head_rows))
        check("a repacked plan with a non-repack meta is REFUSED",
              _raises(lambda: plan_weight_split(art.manifest, rp_base, 4,
                                                [0, 1, 2, 3], m4), SeqError))
        check("a one-span plan with a repack meta is REFUSED",
              _raises(lambda: plan_weight_split(art.manifest, flat_base, 4,
                                                [0, 1, 2, 3], rp_meta),
                      SeqError))
        check("check_weight_plan compares per-channel bases as data",
              check_weight_plan(
                  dict(rp_meta, weights={
                      str(k): dict(art.manifest[str(k)], base=list(v))
                      for k, v in rp_base.items()}),
                  rp_base, art.manifest)["images"] == len(rp_base))
        check("...and a repacked base that is off on ONE channel is caught",
              _raises(lambda: check_weight_plan(
                  dict(rp_meta, weights={
                      str(k): dict(art.manifest[str(k)],
                                   base=[v[0], v[1] + 64, v[2], v[3]])
                      for k, v in rp_base.items()}),
                  rp_base, art.manifest), SeqError))

        # ---- 6. disasm window ----
        w = disasm_window(art.recs, art.halt_pc(), n_before=4)
        check("disasm_window marks the PC", "<<< PC" in w)

        # ---- 7. .chip golden parser, when one exists ----
        gp = p + ".chip"
        if os.path.exists(gp):
            g = parse_chip_golden(gp)
            check("golden NREC matches", g["nrec"] == art.nrec)
            check("golden PC is the HALT record", g["pc"] == art.halt_pc())
            check("golden tokens == expect_tokens", g["tok"] == toks,
                  f"{g['tok']} vs {toks}")
            check("golden BASES are the emitter's",
                  g["bases"][:3] == [meta["seq_stream_base"],
                                     meta["seq_data_base"], meta["emb_base"]])
            # R-b: a golden built for a 0.8B image legitimately covers only
            # the 16384 words its own emitter modelled, a 2B one 32768, a 9B
            # one 65536.  The comment here has always said "a WHOLE power-of-
            # two scratchpad that fits in the hardware" — G2a makes the check
            # say it too.  The old form was the hard pair
            # `cover in (16384, SCRATCH_WORDS)`, which fails a legitimate
            # third size EVEN WHEN CORRECT, and which silently stopped
            # accepting 32768 the moment SCRATCH_WORDS moved to 65536.
            cover = (len(g["mem"])
                     + sum(b - a for a, b in meta.get("staging_words", [])))
            pow2 = cover > 0 and (cover & (cover - 1)) == 0
            check("golden covers the scratchpad minus staging",
                  pow2 and 16384 <= cover <= SCRATCH_WORDS,
                  f"{len(g['mem'])} words + staging = {cover} "
                  f"(want a power of two in [16384, {SCRATCH_WORDS}])")
        # ---- 8. the RUN protocol, against an offline seq_unit CSR model ----
        golden = parse_chip_golden(gp) if os.path.exists(gp) else None
        fake = _FakeSeqDev(art.halt_pc(), toks, golden=golden)
        run = seq_start_and_poll(fake, art, plan, timeout=5.0,
                                 log=lambda *a: None)
        check("run halts at the HALT record", run["pc"] == art.halt_pc())
        check("run reports no error", run["status"]["err_code"] == 0)
        check("OUT FIFO drained in order", run["tokens"] == toks,
              f"{run['tokens']} vs {toks}")
        check("BASE_LO was written with the planned base",
              fake.regs[S_BASE_LO] == (plan["seq_base"] & 0xFFFFFFFF))
        check("LEN was written with nrec", fake.regs[S_LEN] == art.nrec)
        check("XRF was zeroed before START", fake.xrf == [0] * SEQ_XRF_N)
        # ---- R-b: EMBLOG2 is programmed from the manifest before START ----
        check("EMBLOG2 was written before START",
              fake.regs[S_EMBLOG2] == seq_emb_log2(art.emb_row_bytes),
              f"{fake.regs[S_EMBLOG2]} for {art.emb_row_bytes} B rows")
        check("tokens match the metadata",
              first_divergence(run["tokens"], toks) is None)
        if golden:
            gok, gbad, gchk, _mir = verify_chip_golden(
                fake, art, run, golden, log=lambda *a: None)
            check("golden state check passes on matching state", gok,
                  "; ".join(gbad[:4]))
            check("golden state check is not vacuous",
                  gchk > len(golden["mem"]))
            g2 = dict(golden, eout=(golden["eout"] + 1) & 0xF)
            gok2, _b, _c, _m = verify_chip_golden(
                _FakeSeqDev(art.halt_pc(), toks, golden=golden), art, run, g2,
                log=lambda *a: None)
            check("golden state check catches a bad EOUT", not gok2)
        # ---- R-d: --zero-scratch clears the pad through SPTR/SWIN ---------
        # The pad is not cleared by the FPGA between runs and the golden's
        # zeros come from ref/seq_model's zero-initialised memory, so a word
        # THIS stream never writes shows the previous model's leftovers.
        # Two geometries alternating is what exposed it (0.8B leaves y32
        # values in 0x1810..0x1bff, live scratch for the 2B stream).
        fake_z = _FakeSeqDev(art.halt_pc(), toks, golden=golden)
        pre_wr = fake_z.n_wr
        dirty = fake_z.layer_read_scratch(0, 64)
        fake_z.layer_zero_scratch()
        check("--zero-scratch issues SPTR + one SWIN write per word",
              fake_z.n_wr - pre_wr == SCRATCH_WORDS_BUILT + 1,
              f"{fake_z.n_wr - pre_wr} writes for {SCRATCH_WORDS_BUILT} words")
        check("--zero-scratch leaves the pre-run pad all zero",
              not np.any(fake_z.layer_read_scratch(0, SCRATCH_WORDS_BUILT)))
        check("the pre-run pad was NOT already zero (the check is not vacuous)",
              bool(np.any(dirty)) or not golden)
        # error halt: the failure report must name the code and mark the PC
        bad_pc = min(len(art.recs) - 1, max(0, art.halt_pc() // 2))
        fake_e = _FakeSeqDev(bad_pc, [], err_code=0x10)
        run_e = seq_start_and_poll(fake_e, art, plan, timeout=5.0,
                                   log=lambda *a: None)
        fr = failure_report(art, run_e)
        check("failure report names the err_code",
              "layer_chan err_op" in fr and "0x10" in fr, fr[:200])
        check("failure report marks the failing record", "<<< PC" in fr)
        check("failure report shows the last records issued",
              fr.count("\n") >= 14, f"{fr.count(chr(10))} lines")
        # token divergence path
        if toks:
            fake_t = _FakeSeqDev(art.halt_pc(), toks[:-1] + [toks[-1] + 1])
            run_t = seq_start_and_poll(fake_t, art, plan, timeout=5.0,
                                       log=lambda *a: None)
            check("a wrong last token is detected",
                  first_divergence(run_t["tokens"], toks) is not None)
        # a busy sequencer is refused, not stomped on
        fake_b = _FakeSeqDev(art.halt_pc(), toks)
        fake_b._busy = True
        try:
            seq_start_and_poll(fake_b, art, plan, timeout=5.0,
                               log=lambda *a: None)
            check("a busy sequencer is refused", False)
        except SeqError:
            check("a busy sequencer is refused", True)
        # and the SEQ CSRs are refused outright when the gate said no
        blocked = _FakeSeqDev(art.halt_pc(), toks)
        blocked.seq_ok, blocked.seq_why = False, "no build_029"
        try:
            blocked.seq_rd(S_STATUS)
            check("a closed SEQ gate blocks CSR access", False)
        except SystemExit:
            check("a closed SEQ gate blocks CSR access", True)

        log(f"      {art.nrec} records, {len(art.blob)} B blob, "
            f"{rrep['ldc']} LDC ({rrep['ldc_indirected']} indirected), "
            f"{nmv} MVGO, {len(toks)} expected tokens")

    # ---- R-b: the manifest meta key + the EMBLOG2 bring-up, both ways ----
    # ---- R-c: the emitter's placement-ORDER guard actually fires --------
    # Under the repack an image is placed at its FIRST MVGO, so the pack is
    # only stable if wids are first USED in ascending order.  `_replan`
    # asserts that; a guard that never fires proves nothing, so drive it.
    log("  --- R-c: the emitter's placement-order guard")
    def _mk_em():
        class _M(object):
            pass
        m = _M()
        m.wids = {"a": (0, {"w4": np.zeros((512, 256), dtype=np.int8),
                            "m": np.zeros((512, 2), dtype=np.int8),
                            "sh": 5, "g": 128}),
                  "b": (1, {"w4": np.zeros((4096, 256), dtype=np.int8),
                            "m": np.zeros((4096, 2), dtype=np.int8),
                            "sh": 5, "g": 128}),
                  "c": (2, {"w4": np.zeros((200, 256), dtype=np.int8),
                            "m": np.zeros((200, 2), dtype=np.int8),
                            "sh": 5, "g": 128})}
        e = SF.SeqEmitter.__new__(SF.SeqEmitter)
        e.M, e.nch, e.repack = m, 4, True
        e.wlayout, e.wplan, e.CHUNK_ROWS = {}, None, 64
        return e

    def _place(e, order):
        for w in order:
            e.wlayout[w] = SF.LAYOUT_CONTIG
            e._replan()
        return e

    eo = _place(_mk_em(), (0, 1, 2))
    check("in wid order, every base is stable as images are placed",
          all(isinstance(p["base"], list) and len(p["base"]) == 4
              for p in eo.wplan.values()) and len(eo.wplan) == 3)
    check("a wid first USED out of order is caught (bases would move)",
          _raises(lambda: _place(_mk_em(), (0, 2, 1)), AssertionError))
    log("  --- R-b: emb_row_bytes manifest key + EMBLOG2 CSR")
    old_man = {"0": {"file": "x_w0.bin", "nrows": 8, "k": 128, "ng": 1,
                     "sh": 0, "e": 0, "nbeats": 1, "stride": 64}}
    new_man = dict(old_man, emb_row_bytes=4096)
    wo, mo = HW.split_manifest(old_man)
    wn, mn = HW.split_manifest(new_man)
    # G3.4: EMB_ROW_BYTES_DEFAULT follows the RTL reset (11 -> 13), so this
    # check is written against the constant, not against a literal 2048.
    check("an old manifest defaults to the CSR reset row size",
          wo == old_man and mo["emb_row_bytes"] == EMB_ROW_BYTES_DEFAULT)
    check("a new manifest keeps ONLY wid entries in the wid map",
          wn == old_man and list(wn) == ["0"])
    check("a new manifest carries the row size", mn["emb_row_bytes"] == 4096)
    # G2a (spec 4.4): `rs_f` is the SECOND non-wid key.  Same split, same
    # default-when-absent contract as `emb_row_bytes` — and the same trap if
    # only half of it lands: a top-level key that is not in
    # MANIFEST_META_KEYS is handed to every wid-iterating consumer as if it
    # were an image record.
    wr, mr = HW.split_manifest(dict(old_man, rs_f=7))
    check("an old manifest defaults to rs_f 8",
          mo["rs_f"] == HW.RS_F_DEFAULT == 8, str(mo["rs_f"]))
    check("a new manifest carries rs_f and keeps it OUT of the wid map",
          mr["rs_f"] == 7 and wr == old_man and list(wr) == ["0"])
    # S3 (SEQ_ISA v2.1) adds TWO NON-SCALAR meta keys, `state` and
    # `conv_images`, which cannot live in `_META_DEFAULTS` (its values go
    # through `int()`).  The property this check exists for is unchanged and
    # is what the line below states: EVERY meta key is answered by
    # `split_manifest`, so no consumer has to know which manifest generation
    # it is reading -- a pre-S3 manifest answers None for the two new ones.
    check("every MANIFEST_META_KEY has a default",
          set(HW.MANIFEST_META_KEYS)
          == set(HW._META_DEFAULTS) | set(HW.MANIFEST_STATE_KEYS)
          == set(HW.split_manifest({})[1])
          and HW.split_manifest({})[1]["state"] is None,
          str(HW.MANIFEST_META_KEYS))
    check("emb row bytes -> EMBLOG2", seq_emb_log2(2048) == 11
          and seq_emb_log2(4096) == 12
          # G2a: 9B is 2*H = 8192 B rows, which is EMBLOG2 13 and the TOP of
          # the CSR's legal range (SEQ_EMBLOG2_MAX).  It was never covered
          # here; the geometry this campaign migrates to is the one row of
          # this mapping nothing tested.
          and seq_emb_log2(8192) == 13 == HW.SEQ_EMBLOG2_MAX)
    for bad in (2047, 128, 1 << 20):
        try:
            seq_emb_log2(bad)
            check(f"emb row {bad} B is rejected", False)
        except ValueError:
            check(f"emb row {bad} B is rejected", True)
    f_new = _FakeSeqDev(0, [])
    seq_set_emb_row_bytes(f_new, 4096, log=lambda *a: None)
    check("EMBLOG2 takes a 4096 B row", f_new.regs[S_EMBLOG2] == 12)
    seq_set_emb_row_bytes(f_new, 1 << SEQ_EMBLOG2_RST, log=lambda *a: None)
    check("EMBLOG2 goes back to the reset row size",
          f_new.regs[S_EMBLOG2] == SEQ_EMBLOG2_RST)
    seq_set_emb_row_bytes(f_new, 2048, log=lambda *a: None)
    check("EMBLOG2 still takes the 2048 B row (the CSR stays RUNTIME)",
          f_new.regs[S_EMBLOG2] == 11)
    f_old = _FakeSeqDev(0, [], has_emblog2=False)
    seq_set_emb_row_bytes(f_old, 1 << SEQ_EMBLOG2_RST, log=lambda *a: None)
    check("a pre-R-b bitstream still runs its fixed reset geometry",
          f_old.seq_rd(S_EMBLOG2) == SEQ_CSR_UNMAPPED)
    try:
        seq_set_emb_row_bytes(f_old, 4096, log=lambda *a: None)
        check("a pre-R-b bitstream refuses a 4096 B row", False)
    except SeqError:
        check("a pre-R-b bitstream refuses a 4096 B row", True)

    # ---------------- BM1: the idle-counter block (SEQ_ISA B16) ----------
    log("  --- BM1: the SEQ 0x100 idle-counter block is feature-detected")
    check("BM offsets are the B16 map (0x104..0x128, then 0x130/0x134)",
          [o for _, o in SEQ_BM_REGS]
          == list(range(0x04, 0x2C, 4)) + [0x30, 0x34]
          and S_BM_IDENT == HW.SB + 0x100)
    f_041 = _FakeSeqDev(0, [])
    check("build_041 (no BM block): seq_perf carries no 'bm' key",
          "bm" not in f_041.seq_perf() and f_041.seq_bm() is None)
    _bmv = {0: SEQ_BM_IDENT}
    _bmv.update({o: 1000 + o for _, o in SEQ_BM_REGS})
    f_bm = _FakeSeqDev(0, [], bm=_bmv)
    _got = f_bm.seq_perf().get("bm")
    check("a BM1 bitstream: seq_perf()['bm'] reads every B16 register",
          _got == {n: 1000 + o for n, o in SEQ_BM_REGS})
    f_bad = _FakeSeqDev(0, [], bm={0: SEQ_BM_IDENT ^ 1, 0x04: 7})
    check("a wrong BM_IDENT is NOT trusted (no 'bm' key)",
          "bm" not in f_bad.seq_perf())

    # ---------------- BM1-T4prep: the explicit VERSION admission ---------
    # The identity gate admits the BM1 bitstream (build_042_bm1, VERSION
    # 0x9b588e78) ONLY when a caller names it (--expect-version, or
    # FABLE5_SEQ_EXPECT_VERSION for tools that build Dev() themselves); the
    # shipped build_041 stays the default.  Driven through the REAL
    # Dev._gate with a scripted CSR read, so the gate itself is what's tested.
    log("  --- BM1-T4prep: --expect-version admits a NAMED sequencer bitstream")
    try:
        _BM1V, _041V = 0x9B588E78, 0xC973C18A

        def _gate_on(board_ver, expect):
            regs = {R_MAGIC: MAGIC, R_VERSION: board_ver, R_CALIB: CALIB_ALL,
                    L_IDENT: LAYER_IDENT, S_IDENT: SEQ_IDENT}
            regs.update({mv_base(c) + R_IDENT: MV_IDENT0 + c
                         for c in range(4)})
            d = object.__new__(Dev)
            d.rd = lambda a: regs.get(a, 0xDEADC0DE)
            _ident, ok, why = d._gate(expect, True)
            return ok, why

        check("the shipped default is unchanged (EXPECTED_SEQ_VERSION)",
              EXPECTED_SEQ_VERSION == _041V
              and resolve_expect_version(EXPECT_DEFAULT, env={}) == _041V)
        check("both admissible rows decode SHAPE_ISA_9B (= this tree's)",
              SEQ_VERSIONS[_041V][0] == HW.SHAPE_ISA_9B == HW.SHAPE_ISA
              and SEQ_VERSIONS[_BM1V][0] == HW.SHAPE_ISA_9B)
        # SR11a fix round 3 (I1): the SHAPE layout is keyed by VERSION through
        # hwmap.shape_isa_for_version, so every admissible sequencer
        # bitstream needs an hwmap row, and the two tables must agree
        _tab = sorted((v, r[0], HW.SHAPE_ISA_BY_VERSION.get(v))
                      for v, r in SEQ_VERSIONS.items())
        check("every SEQ_VERSIONS key has an hwmap.SHAPE_ISA_BY_VERSION row "
              "with the same SHAPE layout",
              all(h is not None and h == s for (_v, s, h) in _tab),
              ", ".join(f"{v:#010x} {s}/{h}" for (v, s, h) in _tab
                        if h != s))
        # SR13b (the keyless path): a board run requires the manifest's
        # shape_isa key, except a frozen pre-G3 stream at an isa=1 device
        _P1, _P2 = HW.SHAPE_ISA_PRE_G3, HW.SHAPE_ISA_9B
        _fz = sorted(FROZEN_PRE_G3_STREAMS)
        check("layout_key_check: a declared key passes at either layout",
              layout_key_check({"shape_isa": 2}, "0" * 64, _P2) ==
              layout_key_check({"shape_isa": 1}, "0" * 64, _P1) ==
              "declared")
        check("layout_key_check: each frozen pre-G3 stream (3) is admitted "
              "keyless at isa=1 only",
              len(_fz) == 3
              and all(len(s) == 64 and int(s, 16) >= 0 for s in _fz)
              and all(layout_key_check({}, s, _P1) for s in _fz)
              and all(_raises(lambda s=s: layout_key_check({}, s, _P2),
                              SeqError) for s in _fz)
              and all(_raises(lambda s=s: layout_key_check({}, s, None),
                              SeqError) for s in _fz))
        _msg = ""
        try:
            layout_key_check({}, "0" * 64, _P1)
        except SeqError as e:
            _msg = str(e)
        check("layout_key_check: any other keyless stream is refused at "
              "isa=1 and isa=2, naming the shape_isa key",
              "`shape_isa` key" in _msg
              and _raises(lambda: layout_key_check({}, "0" * 64, _P2),
                          SeqError), _msg[:120])
        check("parse_expect_version takes the bare git-hash form",
              parse_expect_version("9b588e78") == _BM1V
              and parse_expect_version("0x9B588E78") == _BM1V)
        check("an unknown hash is refused at parse (typo guard)",
              _raises(lambda: parse_expect_version("9b588e79"))
              and _raises(lambda: parse_expect_version("zz")))
        check("the env admission resolves to the named row",
              resolve_expect_version(
                  EXPECT_DEFAULT, env={EXPECT_VERSION_ENV: "9b588e78"})
              == _BM1V)
        check("an unknown hash in the env is refused",
              _raises(lambda: resolve_expect_version(
                  EXPECT_DEFAULT, env={EXPECT_VERSION_ENV: "deadbeef"})))
        check("an explicit argument beats the env",
              resolve_expect_version(
                  _041V, env={EXPECT_VERSION_ENV: "9b588e78"}) == _041V)
        check("gate: shipped board + default -> SEQ READY",
              _gate_on(_041V, resolve_expect_version(EXPECT_DEFAULT,
                                                     env={}))[0])
        check("gate: BM1 board + default -> REFUSED (nothing defaults to it)",
              not _gate_on(_BM1V, resolve_expect_version(EXPECT_DEFAULT,
                                                         env={}))[0])
        check("gate: BM1 board + --expect-version 9b588e78 -> SEQ READY",
              _gate_on(_BM1V, parse_expect_version("9b588e78"))[0])
        _ok, _why = _gate_on(_041V, parse_expect_version("9b588e78"))
        check("gate: shipped board + BM1 named -> REFUSED (wrong hash)",
              not _ok and "0x9b588e78" in _why and "0xc973c18a" in _why, _why)
        check("gate: unknown board + BM1 named -> REFUSED",
              not _gate_on(0xDEADBEEF, _BM1V)[0])
        check("gate: a programmatic expect outside SEQ_VERSIONS -> REFUSED",
              not _gate_on(0x12345678, 0x12345678)[0])
        # SR7 fix round 1 (M-4): the SEQ_CAPS half of the gate, in the
        # standing selftest (evidence/qwen9b/sr/sr7_host_tdd.py has the rest)
        def _gate_caps(board_ver, expect, caps_word):
            regs = {R_MAGIC: MAGIC, R_VERSION: board_ver, R_CALIB: CALIB_ALL,
                    L_IDENT: LAYER_IDENT, S_IDENT: SEQ_IDENT,
                    HW.S_SEQ_CAPS: caps_word}
            regs.update({mv_base(c) + R_IDENT: MV_IDENT0 + c
                         for c in range(4)})
            d = object.__new__(Dev)
            d.rd = lambda a: regs.get(a, HW.SEQ_CSR_UNMAPPED)
            return d._gate(expect, True)[1:]
        _ok, _why = _gate_caps(_041V, _041V, HW.seq_caps_word({"R1"}))
        check("gate: shipped VERSION reporting the R1 SEQ_CAPS word -> "
              "REFUSED (SEQ_CAPS != the row's)",
              not _ok and "SEQ_CAPS" in _why, _why)
        _ok, _why = _gate_caps(0xE3C2FF1E, 0xE3C2FF1E, HW.SEQ_CSR_UNMAPPED)
        check("gate: R1 VERSION (named) reporting 0xDEADC0DE -> REFUSED",
              not _ok and "SEQ_CAPS" in _why, _why)
        _ap = _argparser()
        check("CLI: --expect-version defaults to None (= resolve at Dev)",
              _ap.parse_args([]).expect_version is None)
        check("CLI: --expect-version 9b588e78 parses to the BM1 row",
              _ap.parse_args(["--expect-version", "9b588e78"]).expect_version
              == _BM1V)
        check("CLI: a wrong --expect-version is an argparse error",
              _raises(lambda: _ap.parse_args(["--expect-version",
                                              "9b588e79"]), SystemExit))
    except Exception as _e:              # RED: the admission does not exist
        check("BM1-T4prep admission block runs", False, repr(_e))

    # ---------------- BM1-T4prep fix 1: strict parse + refuse-before-DMA --
    log("  --- BM1-T4prep fix 1: strict hash parse; main refuses before DMA")
    try:
        check("a >8-hex-digit hash is refused, not masked "
              "(ffffffff9b588e78 is not BM1)",
              _raises(lambda: parse_expect_version("ffffffff9b588e78"))
              and _raises(lambda: parse_expect_version("0x09b588e78"))
              and _raises(lambda: parse_expect_version("-9b588e78")))

        # B3 (ruling B3): main() must refuse a closed SEQ gate BEFORE any
        # DDR traffic.  main() is driven for real on a committed artifact
        # with a scripted Dev (seq_ok False) and upload()/Dev.dma_write
        # replaced by tripwires; a temp lock file keeps the board lock out.
        class _Tripped(Exception):
            pass

        _entered = []

        class _ClosedGateDev(object):
            def __init__(self, *a, **k):
                self.ident = {"magic": MAGIC, "version": 0xC973C18A,
                              "calib": CALIB_ALL}
                self.seq_ok = False
                self.seq_why = "scripted: VERSION mismatch"

            def __getattr__(self, name):          # any DMA / CSR access
                _entered.append(name)
                raise _Tripped(name)

        def _trip_upload(*a, **k):
            _entered.append("upload")
            raise _Tripped("upload")

        _g = globals()
        _saved = {k: _g[k] for k in ("Dev", "upload")}
        _saved_argv = sys.argv
        _ltmp = tempfile.mkdtemp(prefix="fable5_b3_")
        _outcome = {}
        try:
            _g["Dev"], _g["upload"] = _ClosedGateDev, _trip_upload
            for _mode, _extra in (("run", ["--zero-scratch"]),
                                  ("dry", ["--dry-run"])):
                del _entered[:]
                sys.argv = (["seq_run.py", "--prefix", cand[0], "--lock",
                             os.path.join(_ltmp, "lock_" + _mode)]
                            + _extra)   # one lock per mode: the lock is
                #                         per-process and main() holds it
                try:
                    main()
                    _outcome[_mode] = ("returned", list(_entered))
                except SystemExit as _se:
                    _outcome[_mode] = (f"exit {_se.code!r}", list(_entered))
                except _Tripped as _t:
                    _outcome[_mode] = (f"tripped {_t}", list(_entered))
        finally:
            _g.update(_saved)
            sys.argv = _saved_argv
            shutil.rmtree(_ltmp, ignore_errors=True)
        _r = _outcome.get("run", ("?", ["?"]))
        check("B3: a closed SEQ gate exits BEFORE upload / any DMA",
              _r[0].startswith("exit") and _r[0] not in ("exit 0",
                                                         "exit None")
              and _r[1] == [], str(_r))
        _d = _outcome.get("dry", ("?", []))
        check("B3: --dry-run still reaches the upload (behaviour kept)",
              _d[0] == "tripped upload" and _d[1] == ["upload"], str(_d))
    except Exception as _e:
        check("BM1-T4prep fix-1 block runs", False, repr(_e))

    # ---------------- SR6: the device's capability set (SEQ_CAPS) --------
    # docs/SEQ_ISA.md v2.3 B17.0.  The end-to-end refusals (main() on mock
    # SEQ windows, chat_seq included) are evidence/qwen9b/sr/sr6_host_tdd.py;
    # these pin the pieces.
    log("  --- SR6: Dev.seq_caps / manifest_caps_check / --caps")
    try:
        def _caps_dev(word, seq_ok=True):
            d = object.__new__(Dev)
            d.seq_ok, d.seq_why = seq_ok, "scripted: closed"
            d.rd = lambda a: word if a == HW.S_SEQ_CAPS else 0xDEADC0DE
            return d
        _R1W = HW.seq_caps_word({"R1"})
        check("SR6: a pre-round bitstream (0xDEADC0DE) has the EMPTY set",
              _caps_dev(HW.SEQ_CSR_UNMAPPED).seq_caps() == frozenset())
        check("SR6: the R1 word decodes to {R1}",
              _caps_dev(_R1W).seq_caps() == frozenset({"R1"}))
        check("SR6: an unknown capability bit is refused (SeqError)",
              _raises(lambda: _caps_dev(_R1W | 0x08).seq_caps(), SeqError))
        check("SR6: a closed SEQ gate refuses to read SEQ_CAPS",
              _raises(lambda: _caps_dev(_R1W, False).seq_caps(),
                      SystemExit))
        check("SR6: a manifest without `caps` claims nothing",
              manifest_caps_check({}, frozenset()) == frozenset())
        check("SR6: a manifest's caps within the device's set are admitted",
              manifest_caps_check({"caps": ["R1"]}, {"R1", "R2"})
              == frozenset({"R1"}))
        try:
            manifest_caps_check({"caps": ["R2"]}, {"R1"})
            _msg = ""
        except SeqError as _e2:
            _msg = str(_e2)
        check("SR6: a manifest claim the device lacks is refused BY NAME",
              "R2" in _msg and "lacks" in _msg, _msg[:80])
        check("SR6: parse_caps: '' / 'none' -> {}, 'R1,R2' -> {R1,R2}",
              parse_caps("") == parse_caps("none") == frozenset()
              and parse_caps("R1,R2") == frozenset({"R1", "R2"}))
        check("SR6: parse_caps refuses an unknown name",
              _raises(lambda: parse_caps("R9"), ValueError))
        check("SR6: --caps defaults to None (board-free = the empty set)",
              _argparser().parse_args([]).caps is None)
    except Exception as _e:
        check("SR6 block runs", False, repr(_e))

    # ---------------- S3: the DDR state region (SEQ_ISA v2.1) -----------
    # S3 fix round 1, I7.  The plan, the witnesses and the bytes-per-token
    # law are PURE, so they belong in this block; the CSR and DMA paths are
    # driven by the fake device below.  The boardfree count MOVES UP because
    # of these -- it is pinned to catch a BROKEN frozen path, not to forbid
    # new tests.
    log("  --- S3: the DDR state region (plan, witnesses, bytes/token)")
    _p4 = HW.plan_state(HW.plan_state_base(4))
    check("the state plan is 24 + 128 + 3 MiB, in B15.1 order",
          (_p4["kv"] - _p4["dn"], _p4["cv"] - _p4["kv"],
           _p4["end"] - _p4["cv"]) == (24 << 20, 128 << 20, 3 << 20),
          str({k: hex(v) for k, v in _p4.items()}))
    check("every region base is 64 KiB aligned",
          all(_p4[k] % HW.STATE_BASE_UNIT == 0 for k in ("dn", "kv", "cv")))
    check("nch=4 puts the region on channel 3 at STATE_MIN_BASE",
          _p4["dn"] == 3 * HW.CH_STRIDE + HW.STATE_MIN_BASE,
          hex(_p4["dn"]))
    # I4: the embedding table is CHECKED, not assumed
    check("nch=1 is REFUSED when the embedding table would reach the region",
          _raises(lambda: HW.plan_state_base(1), AssertionError))
    check("nch=1 is ALLOWED when the table provably ends below it",
          HW.plan_state_base(1, vocab=8192, emb_row_bytes=2048)
          == HW.STATE_MIN_BASE)
    check("nch=1 is REFUSED at H=4096 with the real vocabulary",
          _raises(lambda: HW.plan_state_base(1, vocab=248320,
                                             emb_row_bytes=2 * 4096),
                  AssertionError))
    check("a channel above 3 has no address",
          _raises(lambda: HW.plan_state_base(5), AssertionError))
    # I6: the DN witnesses
    _w = HW.state_dn_witnesses(_p4)
    check("the DN witnesses include the first and the last block",
          _w[0] == _p4["dn"] and _w[-1] + 4096 <= _p4["kv"]
          and _w[-1] >= _p4["kv"] - (2 << 20), str([hex(x) for x in _w]))
    check("the DN witnesses are 4 KiB aligned and inside the DN region",
          all(a % 4096 == 0 and _p4["dn"] <= a < _p4["kv"] for a in _w))
    check("the DN witness count follows its argument",
          len(HW.state_dn_witnesses(_p4, n=16)) == 16)
    # the manifest's two non-scalar keys
    check("a manifest with no state plan answers None for both keys",
          HW.split_manifest({})[1]["state"] is None
          and HW.split_manifest({})[1]["conv_images"] is None)
    check("a state plan stays OUT of the wid map",
          HW.split_manifest(dict(old_man, state=_p4))[0] == old_man)
    # sw/tok_meter's label-D law, checked against the spec's own arithmetic
    try:
        import tok_meter as _TM
        _d512 = _TM.state_bytes_per_token(512)
        _d4k = _TM.state_bytes_per_token(4096)
        check("state bytes/token at T=512 is DN 48 + conv 6 + KV 16.1 MiB",
              (_d512["dn"], _d512["cv"]) == (2 * 24 << 20, 2 * 24 << 17)
              and _d512["kv"] == 2 * 8 * 4 * 2 * (512 * 256 + 64 * 8),
              str(_d512))
        check("state bytes/token is ~70 MiB at T=512 and ~182 at T=4096",
              69 < _d512["total"] / 2**20 < 71
              and 181 < _d4k["total"] / 2**20 < 184,
              f"{_d512['total'] / 2**20:.1f} / {_d4k['total'] / 2**20:.1f}")
        check("only the KV term grows with T",
              _d512["dn"] == _d4k["dn"] and _d512["cv"] == _d4k["cv"]
              and _d4k["kv"] > _d512["kv"])
    except ImportError:
        check("sw/tok_meter.py importable for the bytes/token law", False,
              "import failed")

    # the CSR and image checks, against a fake device
    class _FakeStateDev(object):
        def __init__(self, csr=None, mem_zero=True):
            self.csr = dict(csr or {})
            self.mem_zero = mem_zero
            self.writes = []

        def wr(self, a, v):
            self.csr[a] = v

        def rd(self, a):
            return self.csr.get(a, 0)

        def dma_write_chan(self, c, a, d):
            self.writes.append((c, a, len(d)))

        def dma_read_chan(self, c, a, n):
            return bytes(n) if self.mem_zero else b"\xff" * n

        def dma_verify_chan(self, c, a, d, tag=""):
            return None

    class _FakeArt(object):
        def __init__(self, base, state, conv=()):
            self.base = base
            self.state = state
            self.conv_images = list(conv)
            self.wdir = os.path.dirname(base) or "."

    _sd = os.path.join(_tmp or tempfile.mkdtemp(), "st")
    os.makedirs(_sd, exist_ok=True)
    _sbin = os.path.join(_sd, "a.state.bin")
    with open(_sbin, "wb") as _f:
        _f.truncate(_p4["end"] - _p4["dn"])
    _ssha = hashlib.sha256(open(_sbin, "rb").read()).hexdigest()
    _art_ok = _FakeArt(os.path.join(_sd, "a"), dict(_p4, sha256=_ssha))
    _art_bad = _FakeArt(os.path.join(_sd, "a"), dict(_p4, sha256="0" * 64))
    check("the state image's sha is verified against the manifest",
          verify_state_image(_art_ok) == _ssha)
    check("a manifest sha that disagrees with the image is REFUSED",
          _raises(lambda: verify_state_image(_art_bad), SeqError))
    check("an artifact with no state plan verifies to None",
          verify_state_image(_FakeArt(os.path.join(_sd, "a"), None)) is None)
    # #156 (triage (b)10): a manifest that DECLARES a region and carries no
    # digest.  Both shapes an emitter can produce it in — the key absent and
    # the key empty — because `st.get("sha256")` returns a falsy value for
    # each and the old `if want and ...` guard swallowed both.
    _art_nosha = _FakeArt(os.path.join(_sd, "a"), dict(_p4))
    _art_emptysha = _FakeArt(os.path.join(_sd, "a"), dict(_p4, sha256=""))
    check("a state manifest with NO sha256 key is REFUSED (#156)",
          _raises(lambda: verify_state_image(_art_nosha), SeqError))
    check("a state manifest with an EMPTY sha256 is REFUSED (#156)",
          _raises(lambda: verify_state_image(_art_emptysha), SeqError))
    _dev = _FakeStateDev()
    _rep = upload_state(_dev, _art_ok, log=lambda *a: None)
    check("upload_state zeroes 24 DN blocks of 1 MiB",
          _rep["dn_blocks_zeroed"] == 24
          and all(n == HW.STATE_DN_LAYER for _c, _a, n in _dev.writes))
    check("upload_state programs the three base CSRs",
          [_dev.rd(a) for a in (L_SB_DN, L_SB_KV, L_SB_CV)]
          == [_p4[k] // HW.STATE_BASE_UNIT for k in ("dn", "kv", "cv")])
    check("a DN witness that is NOT zero after the memset is REFUSED",
          _raises(lambda: upload_state(_FakeStateDev(mem_zero=False),
                                       _art_ok, log=lambda *a: None),
                  SeqError))
    check("--skip-weights still programs the base CSRs",
          upload_state(_FakeStateDev(), _art_ok, log=lambda *a: None,
                       csrs_only=True)["csrs_only"] is True)
    check("the launch refuses a ZERO SB_* readback (spec 7.2)",
          _raises(lambda: seq_check_state_bases(_FakeStateDev(), _art_ok,
                                                log=lambda *a: None),
                  SeqError))
    check("the launch refuses an SB_* that disagrees with the artifact",
          _raises(lambda: seq_check_state_bases(
              _FakeStateDev({L_SB_DN: 1, L_SB_KV: 2, L_SB_CV: 3}), _art_ok,
              log=lambda *a: None), SeqError))
    _devp = _FakeStateDev()
    upload_state(_devp, _art_ok, log=lambda *a: None)
    check("the launch ACCEPTS the CSRs upload_state just wrote",
          seq_check_state_bases(_devp, _art_ok, log=lambda *a: None)
          ["SB_DN"] == _p4["dn"] // HW.STATE_BASE_UNIT)
    check("a pre-v2.1 artifact needs no state CSRs at all",
          seq_check_state_bases(_FakeStateDev(),
                                _FakeArt(os.path.join(_sd, "a"), None),
                                log=lambda *a: None) == {})
    _selftest_sr14(check, _raises, log)   # SR14: defined after _emit
    if _tmp:
        shutil.rmtree(_tmp, ignore_errors=True)
    log(f"  seq_run selftest: {npass} passed, {nfail} failed")
    return nfail == 0


# ======================================================================
def _argparse_expect_version(text):
    try:
        return parse_expect_version(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))


def parse_caps(text):
    """`--caps R1[,R2...]` (or "" / "none" = the empty set) -> frozenset,
    every name checked by hwmap.seq_caps_check (unknown -> ValueError)."""
    t = str(text).strip()
    if t.lower() in ("", "none", "{}"):
        return frozenset()
    return HW.seq_caps_check([n.strip() for n in t.split(",") if n.strip()])


def _argparse_caps(text):
    try:
        return parse_caps(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))


def _argparser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prefix", help="<prefix>.seq / .seqdata.bin / .seq.json")
    ap.add_argument("--base", default=None,
                    help="generator-artifact prefix (.weights.json, _w*.bin, "
                         ".emb.bin); default = --prefix minus its last "
                         "dotted component")
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--chan", type=int, default=0,
                    help="DDR FETCH channel (stream/blob/emb); must match the "
                         "emitter's chan")
    ap.add_argument("--four-chan", action="store_true",
                    help="require a row-split (meta nch>1) stream: weights "
                         "are split across DDR channels 0..nch-1 and each "
                         "quarter is readback-verified where its matvec_chan "
                         "reads it.  The mode is otherwise auto-detected from "
                         "meta['nch']; this flag just asserts it.")
    ap.add_argument("--dry-run", action="store_true",
                    help="plan + relocate + upload + readback-verify, and "
                         "NOTHING ELSE — no access at all to the SEQ CSR "
                         "window, so this is the mode that is safe on a "
                         "bitstream without seq_0")
    ap.add_argument("--skip-weights", action="store_true",
                    help="weights + embedding are already resident")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the DDR readback comparison")
    ap.add_argument("--zero-scratch", action="store_true",
                    help="write zeros over the 32K layer_chan scratchpad "
                         "(SPTR/SWIN, idle-only) before starting, and read "
                         "it back to prove it cleared.  The FPGA never "
                         "clears the pad between runs while ref/seq_model's "
                         "memory is zero-initialised, so a word this stream "
                         "does not write shows the PREVIOUS model's "
                         "leftovers and the .chip golden calls it a "
                         "mismatch.  Harmless while one geometry owns the "
                         "board; required when 0.8B and 2B alternate "
                         "(evidence/qwen2b/rd/hw_22_scratch_residue_proof.log)")
    ap.add_argument("--no-xrf-init", action="store_true",
                    help="do not zero XRF[0..7] before START")
    ap.add_argument("--entry", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    ap.add_argument("--chip", default=None,
                    help="post-halt golden from tb/scripts/"
                         "gen_seq_chip_vectors.py (default <prefix>.chip)")
    ap.add_argument("--no-chip", action="store_true")
    ap.add_argument("--dump-scratch", default=None,
                    help="save the post-halt 16K scratchpad to a .npy")
    ap.add_argument("--out", default=None, help="JSON report path")
    ap.add_argument("--selftest", action="store_true",
                    help="unit-test the pure-python pieces (no board)")
    ap.add_argument("--expect-version", type=_argparse_expect_version,
                    default=None, metavar="HASH",
                    help="the resident sequencer bitstream's VERSION (8-hex "
                         "git hash), when it is NOT the shipped "
                         f"{EXPECTED_SEQ_VERSION:08x}: e.g. 9b588e78 for "
                         "build_042_bm1.  Must be a row of SEQ_VERSIONS.  "
                         f"Default: ${EXPECT_VERSION_ENV} if set, else "
                         "EXPECTED_SEQ_VERSION")
    ap.add_argument("--caps", type=_argparse_caps, default=None,
                    metavar="R1[,R2..]",
                    help="--dry-run ONLY: the capability set the stream is "
                         "validated at when the SEQ window is not read "
                         "(docs/SEQ_ISA.md B17.0).  Default: the EMPTY set.  "
                         "A non-empty set VALIDATES + RELOCATES ONLY and "
                         "uploads nothing (no device read backs it).  "
                         "A SEQ run takes the DEVICE's set from SEQ_CAPS "
                         "and refuses this flag; the manifest's `caps` is "
                         "never the key")
    ap.add_argument("--shape-isa", type=int, default=None,
                    choices=(HW.SHAPE_ISA_PRE_G3, HW.SHAPE_ISA_9B),
                    help="--dry-run ONLY (SR11a fix round 2): the MVGO SHAPE "
                         "layout the stream is validated at when no SEQ run "
                         "keys it — 1 = build_034/035 (bit 29 = w8), 2 = "
                         "build_041+ (bit 29 = XBANK).  Default: none "
                         "stated, and a SHAPE word with bit 29/30 set is "
                         "refused (docs/SEQ_ISA.md B17.2).  A SEQ run takes "
                         "the DEVICE's layout, hwmap.shape_isa_for_version"
                         "(VERSION), and refuses this flag")
    BL.add_lock_args(ap)                        # O3: --lock PATH / --no-lock
    return ap


def main():
    ap = _argparser()
    args = ap.parse_args()

    if args.selftest:
        # board-free by construction, so it takes no lock
        print("seq_run selftest (pure python, no board):")
        raise SystemExit(0 if _selftest() else 1)
    if not args.prefix:
        ap.error("--prefix is required (or --selftest)")

    # O3 (user ruling 2026-08-29): THE shared board lock, taken here —
    # before the artifacts are even opened, so a refusal costs nothing and
    # cannot happen half way through an upload.  --dry-run needs it too: it
    # DMAs ~900 MiB of weight images into DDR, which is exactly the traffic
    # that corrupts somebody else's resident model.
    try:
        _lock = BL.from_args(args, tool="seq_run.py").acquire()
    except BL.BoardLockError as e:
        print("*** %s" % e)
        raise SystemExit(4)

    rep = {
        "test": "seq_run",
        "prefix": args.prefix,
        "dry_run": bool(args.dry_run),
        "git": subprocess.run(["git", "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              cwd=SW_DIR).stdout.strip(),
        "pass": True,
    }

    # ---------------- board identity (SR6: FIRST) ----------------
    # Task SR6: every validation of the stream below runs at the DEVICE's
    # capability set, so the identity gate — CSR reads only, no DMA — now
    # comes before the artifacts are opened.  A closed SEQ gate still
    # refuses here, before any DMA (ruling B3).
    dev = Dev(args.dev, chan=args.chan, allow_seq=not args.dry_run,
              expect_version=(EXPECT_DEFAULT if args.expect_version is None
                              else args.expect_version))
    print(f"--- board: MAGIC={dev.ident['magic']:#010x} "
          f"VERSION={dev.ident['version']:#010x} "
          f"CALIB={dev.ident['calib']:#x}  "
          f"SEQ={'READY' if dev.seq_ok else 'REFUSED'}")
    if not dev.seq_ok:
        print(f"  SEQ CSRs untouched: {dev.seq_why}")
    rep["ident"] = {k: (hex(v) if isinstance(v, int) else v)
                    for k, v in dev.ident.items()}
    rep["seq_ok"], rep["seq_why"] = dev.seq_ok, dev.seq_why
    # Ruling B3 (BM1-T4prep fix 1): a closed SEQ gate refuses HERE, before
    # any DMA -- the stream/blob/weight upload and --zero-scratch's layer
    # CSR writes all come after this line, and require_seq() would only have
    # refused at START.  --dry-run keeps its behaviour: it never touches the
    # SEQ window, so it may upload with the gate closed.
    if not args.dry_run and not dev.seq_ok:
        raise SystemExit(
            f"REFUSING before any DMA: the SEQ gate is closed "
            f"({dev.seq_why}) -- VERSION mismatch or no sequencer; nothing "
            f"was uploaded or written")

    # ---------------- capabilities (SR6, SEQ_ISA v2.3 B17.0) ------------
    if args.dry_run:
        caps = args.caps if args.caps is not None else frozenset()
        caps_src = ("--caps" if args.caps is not None else "default") + \
            " (board-free: --dry-run never reads the SEQ window)"
    else:
        if args.caps is not None:
            raise SystemExit(
                "REFUSING before any DMA: --caps is for --dry-run only; a "
                "SEQ run validates the stream at the DEVICE's capability "
                "set, read from SEQ_CAPS (docs/SEQ_ISA.md B17.0)")
        try:
            caps = dev.seq_caps()
        except SeqError as e:
            raise SystemExit(f"REFUSING before any DMA: SEQ_CAPS: {e}")
        caps_src = f"the device's SEQ_CAPS {dev.caps_word:#010x}"
    print(f"  capabilities     {sorted(caps) or '{}'}  ({caps_src})")
    rep["caps"] = sorted(caps)

    # ---------------- SHAPE layout (SR11a fix round 2) ------------------
    # Keyed by the DEVICE, like caps: MVGO SHAPE bit 29 is w8 on
    # build_034/035 (isa=1) and XBANK on build_041+ (isa=2), and
    # ref/seq_format refuses bits 29/30 when no layout is stated
    # (docs/SEQ_ISA.md B17.2).  A SEQ run states the layout of the VERSION
    # its identity gate just admitted; --dry-run states --shape-isa or none.
    if args.dry_run:
        shape_isa = args.shape_isa
        shape_src = ("--shape-isa" if shape_isa is not None else
                     "none stated (--dry-run: pass --shape-isa 1|2)")
    else:
        if args.shape_isa is not None:
            raise SystemExit(
                "REFUSING before any DMA: --shape-isa is for --dry-run only; "
                "a SEQ run validates the stream at the DEVICE's SHAPE layout, "
                "hwmap.shape_isa_for_version(VERSION) (docs/SEQ_ISA.md B17.2)")
        try:
            shape_isa = HW.shape_isa_for_version(dev.ident["version"])
        except HW.UnknownBitstream as e:
            raise SystemExit(f"REFUSING before any DMA: {e}")
        # an open SEQ gate means VERSION is a SEQ_VERSIONS key (fix round
        # 3, m6: the dead `row is not None` guard is a hard assert now)
        row = SEQ_VERSIONS.get(dev.ident["version"])
        assert row is not None, (
            f"SEQ gate open on VERSION {dev.ident['version']:#010x}, which is "
            f"not in SEQ_VERSIONS")
        if row[0] != shape_isa:
            raise SystemExit(
                f"REFUSING before any DMA: SEQ_VERSIONS says SHAPE isa="
                f"{row[0]} for VERSION {dev.ident['version']:#010x} but "
                f"hwmap.SHAPE_ISA_BY_VERSION says isa={shape_isa}")
        shape_src = f"the device's VERSION {dev.ident['version']:#010x}"
    print(f"  SHAPE layout     "
          f"{'isa=%d' % shape_isa if shape_isa is not None else 'unstated'}"
          f"  ({shape_src})")
    rep["shape_isa"] = shape_isa

    # ---------------- artifacts ----------------
    try:
        # SR13b: a SEQ run is a board admission -- the artifact must declare
        # its SHAPE layout (or be a frozen pre-G3 stream at an isa=1 device)
        art = Artifacts(args.prefix, base=args.base, caps=caps,
                        shape_isa=shape_isa,
                        require_layout_key=not args.dry_run)
    except (SF.SeqValidationError, SeqError) as e:
        hint = ""
        if shape_isa is None and "SHAPE bits 29/30" in str(e):
            hint = ("\n  (no SHAPE layout was stated: on --dry-run pass "
                    "--shape-isa 1 for a build_034/035 artifact, whose bit "
                    "29 is w8, or --shape-isa 2; docs/SEQ_ISA.md B17.2)")
        raise SystemExit(f"REFUSING before any DMA: {args.prefix} at "
                         f"capabilities {sorted(caps) or '{}'}: {e}{hint}")
    m = art.meta
    print(f"--- SEQ stream: {args.prefix}")
    print(f"  artifacts base   {art.base}")
    print(f"  stream           {art.nrec} records, {len(art.stream)} B "
          f"(sha256 {m['stream_sha256'][:16]}) VALIDATED at capabilities "
          f"{sorted(caps) or '{}'}"
          + (f" (manifest claims {m['caps']}, a subset)" if "caps" in m
             else ""))
    print(f"  seqdata          {len(art.blob)} B "
          f"(sha256 {m['seqdata_sha256'][:16]})")
    loop_note = ("structurally safe" if m.get("loop_structurally_safe")
                 else m["loop_note"])
    print(f"  profile          {m['profile']}  dyn_ka={m.get('dyn_ka')}  "
          f"loop {m['loop_steps']} steps ({loop_note})")
    print(f"  opcodes          {m['opcode_histogram']}")
    print(f"  expected tokens  {expected_tokens(m)}")
    rep["meta"] = {k: m[k] for k in ("nrec", "stream_bytes", "stream_sha256",
                                     "seqdata_bytes", "seqdata_sha256",
                                     "profile", "steps", "loop_steps",
                                     "loop_structurally_safe",
                                     "expect_tokens")}

    # ---------------- mode (1-chan vs row-split) ----------------
    nch = int(m.get("nch", 1))
    if args.four_chan and nch <= 1:
        ap.error(f"--four-chan given but the stream is single-channel "
                 f"(meta nch={nch}); regenerate with the 4-chan emitter "
                 f"(ref/seq_format SEQ_NCH=4)")
    if nch > 1:
        print(f"  mode             {nch}-CHANNEL row-split "
              f"(weights over DDR chans {list(range(nch))}, fetch on "
              f"chan {m.get('chan', 0)})"
              + ("" if args.four_chan else "  [auto-detected from meta nch]"))
    else:
        print(f"  mode             single-channel (engine chan "
              f"{m.get('chan', 0)})")

    # ---------------- plan + relocate ----------------
    plan = plan_ddr(m, len(art.stream), len(art.blob), chan=args.chan)
    try:
        recs, rrep = relocate(art.recs, m, plan, len(art.blob), caps=caps,
                              shape_isa=shape_isa)
    except SF.SeqValidationError as e:
        raise SystemExit(f"REFUSING before any DMA: the relocated stream at "
                         f"capabilities {sorted(caps) or '{}'}: {e}")
    print(f"--- DDR plan (fetch channel {args.chan}, host offset "
          f"{plan['ddr_off']:#x}, nch={plan['nch']})")
    print(f"  stream    {plan['stream_base']:#x} .. "
          f"{plan['stream_base'] + len(art.stream):#x}  "
          f"(window {SEQ_STREAM_MAX >> 20} MiB)")
    print(f"  seqdata   {plan['data_base']:#x} .. "
          f"{plan['data_base'] + len(art.blob):#x}  "
          f"(window {SEQ_DATA_MAX >> 20} MiB)")
    print(f"  weights   {W_BASE:#x} ..            (plan_weights, "
          f"{len(art.manifest)} images, chans {plan['weight_chans']})")
    print(f"  embedding {plan['emb_base']:#x}  (fetch chan {args.chan})")
    print(f"  RELOCATION: {rrep['ldc']} LDC records "
          f"({rrep['ldc_indirected']} XRF-indirected) rebased by "
          f"{rrep['data_delta']:+#x} "
          f"(emitter {int(m['seq_data_base']):#x} -> "
          f"{plan['data_base']:#x}); {rrep['emb']} EMB records checked, "
          f"delta {rrep['emb_delta']:+#x}")
    rep["plan"] = {k: (hex(v) if isinstance(v, int) else v)
                   for k, v in plan.items()}
    rep["relocation"] = rrep

    # SR6 fix round 1 (I-1, controller ruling): NO path uploads a stream
    # validated at a capability set the DEVICE did not report.  --dry-run
    # never reads SEQ_CAPS, so a --dry-run with a non-empty --caps stops
    # HERE — validated and relocated at the typed set, nothing uploaded, no
    # DMA of any kind (stream, blob, weights, embedding).  A dry-run at the
    # empty set (the default) keeps its upload + readback behaviour.
    if args.dry_run and caps:
        print(f"--- DRY RUN at --caps {sorted(caps)}: validated only, nothing "
              f"uploaded — the stream validated and relocated at the typed "
              f"capability set, which no device read backs, so no DMA of any "
              f"kind was issued (a SEQ run validates at the device's "
              f"SEQ_CAPS instead)")
        rep["pass"] = True
        rep["validated_only"] = True
        _emit(rep, args.out)
        raise SystemExit(0)

    wbase_of, _wtop = plan_weights_for(art.manifest, art.wdir, m)
    check_weight_plan(m, wbase_of, art.manifest)
    nmv = check_mvgo_targets(art.recs, wbase_of, art.manifest, m)
    print(f"  weight plan: {len(wbase_of)} images match the stream's MVGO "
          f"plan; {nmv} MVGO WBASEs row-aligned inside them")

    # ---------------- upload ----------------
    print("--- upload")
    urep, wbase_of, _stream = upload(dev, art, plan, recs,
                                     do_weights=not args.skip_weights,
                                     verify=not args.no_verify)
    print(f"  {urep['bytes'] / 2**20:.0f} MiB written, "
          f"{urep['verified_bytes'] / 2**20:.0f} MiB read back and compared, "
          f"{urep['seconds']}s")
    rep["upload"] = urep

    if args.dry_run:
        print("--- DRY RUN COMPLETE: DDR images uploaded and readback-"
              "verified; the SEQ CSR window was never accessed.")
        rep["pass"] = True
        _emit(rep, args.out)
        raise SystemExit(0)

    # ---------------- run ----------------
    print("--- run")
    if args.zero_scratch:
        t0 = time.time()
        dev.layer_zero_scratch()
        chk = dev.layer_read_scratch(0, SCRATCH_WORDS_BUILT)
        nz = int(np.count_nonzero(chk))
        print(f"  scratch   {SCRATCH_WORDS_BUILT} words zeroed via SPTR/SWIN and "
              f"read back: {nz} non-zero ({time.time() - t0:.1f}s)")
        rep["scratch_zeroed"] = {"words": SCRATCH_WORDS_BUILT, "nonzero_after": nz}
        if nz:
            raise SeqError(f"scratch did not clear: {nz} non-zero words")
    run = seq_start_and_poll(dev, art, plan, timeout=args.timeout,
                             entry=args.entry,
                             init_xrf=not args.no_xrf_init)
    st = run["status"]
    print(f"  halted at pc={run['pc']}/{art.nrec} in {run['wall_s']}s wall / "
          f"{run['device_ms']} ms device")
    print(f"  STATUS={st['raw']:#010x} err={st['err']} "
          f"err_code={st['err_code']:#04x} ({seq_err_name(st['err_code'])})")
    print(f"  perf: {run['perf']}")
    print(f"  tokens: {run['tokens']}")
    rep["run"] = {k: v for k, v in run.items() if k != "status"}
    rep["run"]["status"] = {k: v for k, v in st.items()}
    if run.get("warn_fifo_full"):
        print("  WARNING: " + run["warn_fifo_full"])

    ok = True
    if st["err"] or st["err_code"]:
        print(failure_report(art, run))
        rep["failure"] = failure_report(art, run)
        ok = False
    elif run["pc"] != art.halt_pc():
        print(f"  PC {run['pc']} is not the HALT record {art.halt_pc()}")
        rep["failure"] = f"pc {run['pc']} != halt {art.halt_pc()}"
        ok = False

    # ---------------- verify ----------------
    want = expected_tokens(m)
    d = first_divergence(run["tokens"], want)
    if d is None:
        print(f"  TOKENS   IDENTICAL to the .seq.json ({len(want)} tokens)")
    else:
        print("  TOKENS   MISMATCH\n    " + d.replace("\n", "\n    "))
        rep["token_divergence"] = d
        ok = False
    rep["tokens_ok"] = d is None

    gp = args.chip or (art.prefix + ".chip")
    if not args.no_chip and os.path.exists(gp) and st["halted"]:
        print(f"--- post-halt state vs {gp}")
        gok, bad, nchk, mirror = verify_chip_golden(dev, art, run,
                                                    parse_chip_golden(gp))
        for line in bad[:12]:
            print("    ! " + line)
        rep["golden"] = {"path": gp, "checks": nchk, "pass": gok,
                         "mismatches": bad[:32],
                         "layer_xrf_mirror": {str(k): hex(v)
                                              for k, v in mirror.items()}}
        ok = ok and gok

    if args.dump_scratch:
        scr = dev.layer_read_scratch(0, SCRATCH_WORDS_BUILT).astype(np.uint16)
        np.save(args.dump_scratch, scr)
        print(f"  scratch dump -> {args.dump_scratch}")

    rep["pass"] = ok
    print("SEQ RUN: " + ("PASS" if ok else "FAIL"))
    _emit(rep, args.out)
    raise SystemExit(0 if ok else 1)


def _emit(rep, path):
    if path:
        with open(path, "w") as f:
            json.dump(rep, f, indent=1, default=str)
        print(f"report -> {path}")

# SR14 (evidence/qwen9b/sr/SR14_R2_BUILD.md): the R2 bitstream, signed off
# on build_045_r2_incr (VERSION = the launch tree 266e3ae, stamped 266e3ae7:
# evidence/qwen9b/sr/n1401_SR14_launch_build_045_r2.log), admitted only when
# named; it reports SEQ_CAPS {R1, R2} = 0xFAB1CA03 and BM_IDENT 0xFAB1B301,
# and its SHAPE decode is isa=2 (bits 29/30 = XBANK/RBANK, docs/SEQ_ISA.md
# B17.2).  Assigned here, not inside SEQ_VERSIONS, so no cited line moves
# (the dict's closing line says so); hwmap carries the agreeing rows.
SEQ_VERSIONS[0x266E3AE7] = (
    HW.SHAPE_ISA_9B,
    "build_045_r2_incr (R2 XWIN/RES banks + R1 + BM1 counters; admitted "
    "only when named)",
    HW.seq_caps_word({"R1", "R2"}))


def _selftest_sr14(check, _raises, log):
    """SR14's selftest cases, called from _selftest (on what was its blank
    line before the cleanup, so no cited line moved): the R2 row through the
    real Dev._gate, and the SR13b review's parked minors m2 / m4."""
    log("  --- SR14: the R2 row; the frozen-stream pins (SR13b m2 / m4)")
    _R2V, _R1V = 0x266E3AE7, 0xE3C2FF1E
    _R2W = HW.seq_caps_word({"R1", "R2"})

    def _gate_caps(board_ver, expect, caps_word):
        regs = {R_MAGIC: MAGIC, R_VERSION: board_ver, R_CALIB: CALIB_ALL,
                L_IDENT: LAYER_IDENT, S_IDENT: SEQ_IDENT,
                HW.S_SEQ_CAPS: caps_word}
        regs.update({mv_base(c) + R_IDENT: MV_IDENT0 + c for c in range(4)})
        d = object.__new__(Dev)
        d.rd = lambda a: regs.get(a, HW.SEQ_CSR_UNMAPPED)
        return d._gate(expect, True)[1:]
    try:
        check("SR14: the R2 row exists with SEQ_CAPS {R1,R2} = 0xFAB1CA03, "
              "isa=2, and agreeing hwmap SHAPE / BM_IDENT rows",
              _R2V in SEQ_VERSIONS and SEQ_VERSIONS[_R2V][2] == _R2W
              == 0xFAB1CA03 and SEQ_VERSIONS[_R2V][0] == HW.SHAPE_ISA_9B
              and HW.SHAPE_ISA_BY_VERSION.get(_R2V) == HW.SHAPE_ISA_9B
              and HW.shape_isa_for_version(_R2V) == HW.SHAPE_ISA_9B
              and HW.SEQ_BM_IDENT_BY_VERSION.get(_R2V) == HW.SEQ_BM_IDENT)
        # seq-rtl round final fix round (final review minor 2): EVERY
        # SEQ_VERSIONS row needs its hwmap.SEQ_BM_IDENT_BY_VERSION row, as
        # every row needs its SHAPE row (_selftest's SR11a-fix-3 I1 check),
        # so a row added without its BM1 expectation fails HERE, not on the
        # board (bm1_ident would expect UNMAPPED and fail closed there).  The
        # two columns agree: a row that expects a real SEQ_CAPS word (not the
        # unmapped read) is an R1+ netlist, which carries the BM1 block.
        _bm, _U = HW.SEQ_BM_IDENT_BY_VERSION, HW.SEQ_CSR_UNMAPPED
        _miss = sorted(v for v in SEQ_VERSIONS if v not in _bm)
        check(f"every SEQ_VERSIONS key ({len(SEQ_VERSIONS)}) has an "
              "hwmap.SEQ_BM_IDENT_BY_VERSION row", not _miss,
              "missing " + ", ".join(f"{v:#010x}" for v in _miss))
        _odd = sorted((v, _bm[v]) for v in SEQ_VERSIONS
                      if v in _bm and _bm[v] not in (_U, HW.SEQ_BM_IDENT))
        check("each row's BM_IDENT is the unmapped read or 0xFAB1B301 "
              "(hwmap.SEQ_BM_IDENT == seq_run.SEQ_BM_IDENT)",
              not _odd and HW.SEQ_BM_IDENT == SEQ_BM_IDENT == 0xFAB1B301,
              ", ".join(f"{v:#010x}->{b:#010x}" for v, b in _odd))
        _inc = sorted((v, r[2], _bm.get(v)) for v, r in SEQ_VERSIONS.items()
                      if r[2] != _U and _bm.get(v) != HW.SEQ_BM_IDENT)
        check("a row expecting a SEQ_CAPS word != 0xDEADC0DE expects "
              "BM_IDENT 0xFAB1B301", not _inc,
              ", ".join(f"{v:#010x} caps {c:#010x} bm {b}" for v, c, b in _inc))
        _pin = {0x4F908DF2: _U, 0x54443B9F: _U, 0xC973C18A: _U,
                0x9B588E78: 0xFAB1B301, 0xE3C2FF1E: 0xFAB1B301,
                0x266E3AE7: 0xFAB1B301}
        check("BM_IDENT pins: 034/035/041 unmapped; 042/e3c2ff1e/266e3ae7 "
              "0xFAB1B301", all(_bm.get(v) == b for v, b in _pin.items()),
              ", ".join(f"{v:#010x}->{_bm.get(v)}" for v, b in _pin.items()
                        if _bm.get(v) != b))
        check("SR14: parse_expect_version('266e3ae7') names the R2 row",
              parse_expect_version("266e3ae7") == _R2V
              and parse_expect_version("0x266E3AE7") == _R2V)
        _ok, _why = _gate_caps(_R2V, _R2V, _R2W)
        check("gate: R2 VERSION (named) reporting 0xFAB1CA03 -> SEQ READY",
              _ok, _why)
        _ok, _why = _gate_caps(_R2V, _R2V, HW.seq_caps_word({"R1"}))
        check("gate: R2 VERSION (named) reporting the R1 word -> REFUSED",
              not _ok and "SEQ_CAPS" in _why, _why)
        _ok, _why = _gate_caps(_R2V, _R2V, HW.SEQ_CSR_UNMAPPED)
        check("gate: R2 VERSION (named) reporting 0xDEADC0DE -> REFUSED",
              not _ok and "SEQ_CAPS" in _why, _why)
        _ok, _why = _gate_caps(_R2V, resolve_expect_version(EXPECT_DEFAULT,
                                                            env={}), _R2W)
        check("gate: R2 board + default -> REFUSED (nothing defaults to it)",
              not _ok, _why)
        _ok, _why = _gate_caps(_R1V, _R1V, _R2W)
        check("gate: R1 VERSION (named) reporting the R2 word -> REFUSED",
              not _ok and "SEQ_CAPS" in _why, _why)
    except Exception as _e:              # RED: the R2 row does not exist
        check("SR14 R2-row block runs", False, repr(_e))
    try:
        # m4 -- the frozen shas are the ones chat_seq pins, and the files
        _here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        import chat_seq as _CS
        _pins = {_CS.TEMPLATE_SHA256, _CS.TEMPLATE4_BY_MODEL[None][1]}
        _disk = {}
        for _s, _d in FROZEN_PRE_G3_STREAMS.items():
            _f = os.path.join(_here, _d.split(" ")[0] + ".seq")
            _disk[_s] = (hashlib.sha256(open(_f, "rb").read()).hexdigest()
                         if os.path.exists(_f) else None)
        check("SR14 (SR13b m4): FROZEN_PRE_G3_STREAMS holds chat_seq's "
              "TEMPLATE_SHA256 and TEMPLATE4_BY_MODEL[None] shas",
              len(_pins) == 2 and _pins <= set(FROZEN_PRE_G3_STREAMS),
              ", ".join(p[:16] for p in _pins - set(FROZEN_PRE_G3_STREAMS)))
        check("SR14 (SR13b m4): each frozen stream's on-disk .seq hashes to "
              "its FROZEN_PRE_G3_STREAMS key (3 files)",
              len(_disk) == 3 and all(_disk[k] == k for k in _disk),
              ", ".join(f"{k[:12]}->{(v or 'MISSING')[:12]}"
                        for k, v in _disk.items() if v != k))
        # m2 -- a MUTATED frozen stream with a rewritten keyless manifest
        # (its sha updated, so the hash check passes) is refused by the key
        # rule through the real Artifacts path at an isa=1 device
        _P1 = HW.SHAPE_ISA_PRE_G3
        _w8 = os.path.join(_here, "tb", "scripts", "w5", "model_w8_2b_s1.e")
        _mt = tempfile.mkdtemp(prefix="fable5_sr14_mut_")
        try:
            _st = bytearray(open(_w8 + ".seq", "rb").read())
            _st[-1] ^= 0x01            # the last record's top byte
            _mm = json.load(open(_w8 + ".seq.json"))
            _keyless = "shape_isa" not in _mm
            _mm.pop("shape_isa", None)
            _mm["stream_sha256"] = hashlib.sha256(bytes(_st)).hexdigest()
            _mp = os.path.join(_mt, "mut.e")
            with open(_mp + ".seq", "wb") as f:
                f.write(bytes(_st))
            shutil.copyfile(_w8 + ".seqdata.bin", _mp + ".seqdata.bin")
            with open(_mp + ".seq.json", "w") as f:
                json.dump(_mm, f)
            _emsg = ""
            try:
                Artifacts(_mp, base=derive_base(_w8), shape_isa=_P1,
                          require_layout_key=True)
            except SeqError as e:
                _emsg = str(e)
            _orig = hashlib.sha256(open(_w8 + ".seq", "rb").read()
                                   ).hexdigest()
            check("SR14 (SR13b m2): a mutated frozen stream (rewritten "
                  "keyless manifest) is REFUSED at isa=1 by the key rule; "
                  "the unmutated one is admitted keyless",
                  _keyless and "`shape_isa` key" in _emsg
                  and _mm["stream_sha256"] not in FROZEN_PRE_G3_STREAMS
                  and layout_key_check({}, _orig, _P1).startswith(
                      "tb/scripts/w5/model_w8_2b_s1.e"), _emsg[:120])
        finally:
            shutil.rmtree(_mt, ignore_errors=True)
    except Exception as _e:
        check("SR14 frozen-stream block runs", False, repr(_e))

    _selftest_r3(check, _raises, log)    # R3-6: defined below


def _selftest_r3(check, _raises, log):
    """Task R3-6's gate cases (the R3 campaign; called at the end of
    _selftest_sr14, after every cited line, so no citation moves).  No R3
    bitstream exists and its SEQ_VERSIONS row is R3-10's, written only for
    a kept one: the cases run the REAL Dev._gate against a MOCK VERSION
    0x3B3B3B3B whose three rows (SEQ_VERSIONS, hwmap SHAPE and BM_IDENT)
    are injected here and removed after (SR13b's convention).  The device
    word is hwmap.seq_caps_word({"R1","R2","R3"}) = 0xFAB1CA07."""
    log("  --- R3-6: the R3 word through the gate (an injected mock row)")
    _R2V, _R1V, _MV = 0x266E3AE7, 0xE3C2FF1E, 0x3B3B3B3B
    _W7 = HW.seq_caps_word({"R1", "R2", "R3"})
    _U = HW.SEQ_CSR_UNMAPPED
    _before = (dict(SEQ_VERSIONS), dict(HW.SHAPE_ISA_BY_VERSION),
               dict(HW.SEQ_BM_IDENT_BY_VERSION))

    def _gate_caps(board_ver, expect, caps_word):
        regs = {R_MAGIC: MAGIC, R_VERSION: board_ver, R_CALIB: CALIB_ALL,
                L_IDENT: LAYER_IDENT, S_IDENT: SEQ_IDENT,
                HW.S_SEQ_CAPS: caps_word}
        regs.update({mv_base(c) + R_IDENT: MV_IDENT0 + c for c in range(4)})
        d = object.__new__(Dev)
        d.rd = lambda a: regs.get(a, _U)
        return d._gate(expect, True)[1:]
    check("R3-6: seq_caps_word({R1,R2,R3}) is 0xFAB1CA07 and no SEQ_VERSIONS "
          "row but R3-10's 0x2E874592 expects it (R3-10 amended this check)",
          _W7 == 0xFAB1CA07 and HW.seq_caps_set(_W7) == {"R1", "R2", "R3"}
          and not any(r[2] == _W7 for v, r in SEQ_VERSIONS.items() if v != 0x2E874592))
    try:
        SEQ_VERSIONS[_MV] = (HW.SHAPE_ISA_9B, "MOCK R1+R2+R3 (R3-6 selftest "
                             "only)", _W7)
        HW.SHAPE_ISA_BY_VERSION[_MV] = HW.SHAPE_ISA_9B
        HW.SEQ_BM_IDENT_BY_VERSION[_MV] = HW.SEQ_BM_IDENT
        _ok, _why = _gate_caps(_MV, _MV, _W7)
        check("gate: the R3 mock VERSION (named) reporting 0xFAB1CA07 -> "
              "SEQ READY", _ok, _why)
        for _w in (HW.seq_caps_word({"R1", "R2"}), HW.seq_caps_word({"R1"}),
                   _U):
            _ok, _why = _gate_caps(_MV, _MV, _w)
            check(f"gate: the R3 mock VERSION (named) reporting {_w:#010x} "
                  f"-> REFUSED", not _ok and "SEQ_CAPS" in _why, _why)
        _ok, _why = _gate_caps(EXPECTED_SEQ_VERSION, resolve_expect_version(
            EXPECT_DEFAULT, env={}), _W7)
        check("gate: the shipped VERSION (the default) reporting 0xFAB1CA07 "
              "-> REFUSED", not _ok and "SEQ_CAPS" in _why, _why)
        for _v, _n in ((_R2V, "R2"), (_R1V, "R1")):
            _ok, _why = _gate_caps(_v, _v, _W7)
            check(f"gate: the {_n} VERSION (named) reporting 0xFAB1CA07 -> "
                  f"REFUSED", not _ok and "SEQ_CAPS" in _why, _why)
        _ok, _why = _gate_caps(_MV, resolve_expect_version(EXPECT_DEFAULT,
                                                           env={}), _W7)
        check("gate: the R3 mock board + the default -> REFUSED (nothing "
              "defaults to it)", not _ok, _why)
    except Exception as _e:
        check("R3-6 gate block runs", False, repr(_e))
    finally:
        SEQ_VERSIONS.pop(_MV, None)
        HW.SHAPE_ISA_BY_VERSION.pop(_MV, None)
        HW.SEQ_BM_IDENT_BY_VERSION.pop(_MV, None)
    check("R3-6: the injected mock rows are gone (all three tables as before)",
          (dict(SEQ_VERSIONS), dict(HW.SHAPE_ISA_BY_VERSION),
           dict(HW.SEQ_BM_IDENT_BY_VERSION)) == _before)
    _selftest_r3_10(check, _raises, log)  # R3-10: defined below


# R3-10 (evidence/qwen9b/sr/R3_10_BUILD.md): the R3 bitstream (MOVX broadcast,
# form (a)), signed off on build_046_r3_incr (VERSION = the launch tree
# 2e87459, stamped 2e874592: evidence/qwen9b/sr/n3201_launch_build_046_r3.log),
# admitted only when named; it reports SEQ_CAPS {R1, R2, R3} = 0xFAB1CA07 and
# BM_IDENT 0xFAB1B301, SHAPE isa=2.  Assigned here, after every cited line, so
# no citation moves; hwmap carries the agreeing rows.
SEQ_VERSIONS[0x2E874592] = (
    HW.SHAPE_ISA_9B,
    "build_046_r3_incr (R3 MOVX broadcast + R2 + R1 + BM1 counters; "
    "admitted only when named)",
    HW.seq_caps_word({"R1", "R2", "R3"}))


def _selftest_r3_10(check, _raises, log):
    """Task R3-10's cases (evidence/qwen9b/sr/R3_10_BUILD.md; called at the
    end of _selftest_r3, after every cited line): the R3 bitstream
    build_046_r3_incr, VERSION 0x2E874592, is a SEQ_VERSIONS key with its
    agreeing hwmap SHAPE (isa=2) and BM_IDENT rows, and the REAL Dev._gate
    naming it with SEQ_CAPS 0xFAB1CA07 reads SEQ READY.  With the rows
    withheld the existing every-key agreement checks are vacuous for it, so
    these two carry the RED (plan review m10)."""
    log("  --- R3-10: the R3 row (build_046_r3_incr, 2e874592)")
    _R3V, _R2V = 0x2E874592, 0x266E3AE7
    _W7 = HW.seq_caps_word({"R1", "R2", "R3"})

    def _gate_caps(board_ver, expect, caps_word):
        regs = {R_MAGIC: MAGIC, R_VERSION: board_ver, R_CALIB: CALIB_ALL,
                L_IDENT: LAYER_IDENT, S_IDENT: SEQ_IDENT,
                HW.S_SEQ_CAPS: caps_word}
        regs.update({mv_base(c) + R_IDENT: MV_IDENT0 + c for c in range(4)})
        d = object.__new__(Dev)
        d.rd = lambda a: regs.get(a, HW.SEQ_CSR_UNMAPPED)
        return d._gate(expect, True)[1:]
    check("R3-10: the R3 VERSION 0x2E874592 is a SEQ_VERSIONS key expecting "
          "SEQ_CAPS 0xFAB1CA07 at isa=2, with agreeing hwmap SHAPE / BM_IDENT "
          "rows",
          _R3V in SEQ_VERSIONS and SEQ_VERSIONS[_R3V][2] == _W7 == 0xFAB1CA07
          and SEQ_VERSIONS[_R3V][0] == HW.SHAPE_ISA_9B
          and HW.SHAPE_ISA_BY_VERSION.get(_R3V) == HW.SHAPE_ISA_9B
          and HW.SEQ_BM_IDENT_BY_VERSION.get(_R3V) == HW.SEQ_BM_IDENT)
    try:
        _ok, _why = _gate_caps(_R3V, _R3V, _W7)
    except Exception as _e:              # RED: the R3 row does not exist
        _ok, _why = False, repr(_e)
    check("gate: R3 VERSION 2e874592 (named) reporting 0xFAB1CA07 -> "
          "SEQ READY", _ok, _why)
    try:
        check("R3-10: parse_expect_version('2e874592') names the R3 row",
              parse_expect_version("2e874592") == _R3V
              and parse_expect_version("0x2E874592") == _R3V)
        for _w in (HW.seq_caps_word({"R1", "R2"}), HW.seq_caps_word({"R1"}),
                   HW.SEQ_CSR_UNMAPPED):
            _ok, _why = _gate_caps(_R3V, _R3V, _w)
            check(f"gate: R3 VERSION (named) reporting {_w:#010x} -> REFUSED",
                  not _ok and "SEQ_CAPS" in _why, _why)
        _ok, _why = _gate_caps(_R3V, resolve_expect_version(EXPECT_DEFAULT,
                                                            env={}), _W7)
        check("gate: R3 board + default -> REFUSED (nothing defaults to it)",
              not _ok, _why)
        _ok, _why = _gate_caps(_R2V, _R2V, _W7)
        check("gate: R2 VERSION (named) reporting the R3 word -> REFUSED",
              not _ok and "SEQ_CAPS" in _why, _why)
    except Exception as _e:              # RED: the R3 row does not exist
        check("R3-10 R3-row block runs", False, repr(_e))


if __name__ == "__main__":
    main()
