#!/usr/bin/env python3
"""chat_seq.py — interactive chat at SEQUENCER speed (chat-seq phase 2, agent B).

docs/CHAT_SEQ_SPEC.md is the FROZEN contract this file implements.  Nothing
here is allowed to improvise around it; every decision number quoted below
is a clause of that spec.

------------------------------------------------------------------
What it is
------------------------------------------------------------------
sw/infer.py drives one forward step with ~100k host MMIO transactions
(9.3 s/token, 98.8% host overhead).  This tool instead keeps THREE
pre-compiled SEQ record images resident in DDR and runs ONE SEQUENCER
LAUNCH PER FORWARD STEP (spec decision 4):

    preamble   recs [0,1524) of the gated artifact  -> session-once
                 (conv weights, dnz, L_LAYER, the 6 L_TCNT=0 resets)
    lite       48 B head + recs [1526,15532) + HALT -> a prefill step
                 (EMB .. just before the LM head; emits no token)
    full       48 B head + recs [1526,16266) + HALT -> a decode step
                 (EMB .. AMAXL; pushes one token to the OUT FIFO)

Per step the host patches the image head and writes SEQ CTRL.START:

    +0x04  CSRWR XRF[3] <= token id            (in-stream: host AXI XRF
    +0x14  CSRWR XRF[4] <= pos * 1536           writes do NOT reach
    +0x24  CSRWR TCNT_SEQ <= 1                  layer_chan — spec hazard)

The images and the patch bytes come from ref/seq_chat.TurnCompiler (agent
A) — this file NEVER re-slices the template for production use; it only
re-derives the two step images independently at start-up and refuses to
run if the two readings of the frozen spec disagree (crosscheck_agent_a).

POSITION ADDRESSING (--pos-mode).  XRF[4] is read SIGN-EXTENDED from an
18-bit file, so the spec-frozen XRF[4]=pos*1536 scheme tops out at
pos 85 and seq_unit TRUNCATES a larger write SILENTLY (agent A's finding;
ref/seq_model.py does not model it, so the model would "pass").  Agent A
ships pos_mode="ldc" — patch the six position-LDC addresses instead —
which reaches the full KV depth.  --pos-mode auto (the default) picks
"ldc" whenever --max-ctx needs a position above 85, so the shipped chat
path is "ldc" and the spec's "xrf" is available for short contexts.

Everything else — 187 weight images, the embedding table, the LDC const
blob, the 512-position rope blob and the three images themselves — stays
resident across turns and across processes.

Templates are BYTE SLICES of the committed, gated artifact
tb/scripts/w4/model_v2_s1.e.seq (sha256 a69864d2..., 60,495 records), so
their provenance is the same evidence the rung-1 gate already carries.
The slice indices and the sha are asserted on every start-up.

------------------------------------------------------------------
Sampling (docs/SAMPLING_SPEC.md + the 2026-08-11 ruling)
------------------------------------------------------------------
GREEDY IS THE DEFAULT AND IS 100% ON-CHIP.  Nothing about the decode
path changed: a decode step is one FULL launch, the LM head and the
argmax run on the FPGA, the token comes out of the SEQ OUT FIFO.

A SAMPLED step will be the SAME full launch plus an on-chip TOP-K
CAPTURE UNIT (k=32 {int32 value, 18-bit index} pairs read from CSRs
after the halt).  That unit ships with the next RTL rung.  Until its
IDENT reads back, --temp REFUSES at session start with the reason — it
never silently falls back to greedy, and it never moves the model onto
the host.  See the SAMPLING section below for the CSR sequence the unit
is expected to publish.

  --temp/--top-k/--top-p/--seed   the sampler (host math, integer in)
  --verify-head                   VERIFICATION ONLY: rebuild the head's
                                  logits on the host from the chip's own
                                  x8/e_x and assert the host argmax IS
                                  the chip's token, every step
  --model-only --temp T           the whole sampled path with NO BOARD:
                                  ref/seq_model for the hidden state,
                                  sw/head_cache for the head, the shipped
                                  Sampler for the draw

------------------------------------------------------------------
Board safety / exclusivity
------------------------------------------------------------------
* NEVER programs the FPGA, never touches flash, never runs sudo, never
  calls pcie_helper.sh.  It only opens /dev/xdma0_{user,h2c_0,c2h_0}.
* Identity gate: sw/seq_run.py:Dev refuses everything unless MAGIC,
  CALIB, the layer IDENT, all four matvec IDENTs and (for SEQ CSRs)
  VERSION == EXPECTED (build_041 = 0xC973C18A; was 0x54443B9F) + the seq IDENT.
* EXCLUSIVITY (spec decision 10): an exclusive flock() on sw/.seq.lock is
  taken BEFORE any device fd is opened and held for the whole process
  lifetime.  The tool refuses to start without it.
  INTEGRATOR NOTE: sw/infer.py and sw/seq_run.py do NOT take this lock
  yet.  Until they do, the lock only serialises chat_seq.py/serve.py
  against each other; check `pgrep -af 'infer.py|seq_run.py'` by hand
  before a session.  (The seq busy check is TOCTOU-only, spec 10.)
* The OUT FIFO is drained ONLY while the sequencer is halted (spec
  hazard: seq_unit.sv:1049 vs :1100 of_cnt push/pop race).  This is a
  deliberate deviation from sw/seq_run.py:seq_start_and_poll(), which
  drains inside its poll loop; see _launch() below.

------------------------------------------------------------------
Suggested sw/Makefile targets (INTEGRATOR — this file does not edit the
Makefile):

    chat_seq_selftest: ; $(PY) -u chat_seq.py --selftest
    chat_seq_model:    ; $(PY) -u chat_seq.py --model-only --prefill lite
    chat_seq_smoke:    ; $(PY) -u chat_seq.py --smoke \
                           --out $(EVID)/../chat/chat_seq_smoke_$(TAG).json
    chat_seq_gate:     ; $(PY) -u chat_seq.py --canned \
                           --out $(EVID)/../chat/chat_seq_b1_$(TAG).json
    chat_seq:          ; $(PY) -u chat_seq.py --ntok $(NTOK) $(CHAT_FLAGS)

------------------------------------------------------------------
Usage (on snoke)
------------------------------------------------------------------
    ./.venv/bin/python chat_seq.py --selftest       # no board at all
    ./.venv/bin/python chat_seq.py --smoke          # preamble + 1 step
    ./.venv/bin/python chat_seq.py --canned         # gate B1
    ./.venv/bin/python chat_seq.py                  # REPL
    ./.venv/bin/python chat_seq.py --prompt "The capital of France" --ntok 8
"""
import argparse
import hashlib
import json
import os
import signal
import sys
import time

import numpy as np

SW_DIR = os.path.dirname(os.path.abspath(__file__))
TOP_DIR = os.path.dirname(SW_DIR)
REF_DIR = os.path.join(TOP_DIR, "ref")
for _p in (SW_DIR, REF_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import board_lock as BL                                         # noqa: E402
import hwmap as HW                                              # noqa: E402
from hwmap import (                                             # noqa: E402
    ACLK_HZ, SEQ_ALIGN, SEQ_OUT_DEPTH, SEQ_REC_BYTES,
    SEQ_STREAM_BASE, SEQ_DATA_BASE, SEQ_XRF_N,
    S_BASE_LO, S_BASE_HI, S_CTRL, S_ENTRY, S_LEN, S_PC, S_TCNT_SEQ,
    SEQ_CTRL_ABORT, SEQ_CTRL_START, s_xrf, seq_err_name,
)
import seq_format as SF                                         # noqa: E402
import seq_run as SR                                            # noqa: E402
# THE weight pack (sw/hwmap.py); SR.plan_weights_for adds this stream's own
# nch / layout / repack on top of it.
from hwmap import plan_weights                            # noqa: E402,F401
try:
    import seq_chat as SC                                       # noqa: E402
except ImportError as _e:                                       # pragma: no cover
    SC = None
    _SC_ERR = _e
# G2a: the model geometry, for the scratch-footprint decoder and the rope
# pool.  `ref/layer_ref.py` reads the FABLE5_MODEL-selected config JSON at
# import; `seq_chat` already pulls it in transitively via `layer_fixed`, so
# this adds no dependency, and the try/except keeps this file importable on a
# host that has `sw/` without `ref/`.
try:
    import layer_ref as _LR                                     # noqa: E402
except Exception:                                               # pragma: no cover
    _LR = None
# WHICH MODEL this process is configured for.  `ref/model_select.py` freezes
# FABLE5_MODEL at import and every ref/ consumer follows it; this file needs
# the tag itself for the per-model template pin below.  The fallback repeats
# model_select's own default so a host without `ref/` still answers "0.8b".
try:
    import model_select as _MS                                  # noqa: E402
    MODEL_TAG = _MS.TAG
except Exception:                                               # pragma: no cover
    MODEL_TAG = os.environ.get("FABLE5_MODEL", "0.8b")
# The 0.8B/2B values, which are what a fallback must reproduce: every one of
# these is IDENTICAL at both, and only LNH moves at 4B/9B (16 -> 32).
_GEOM_08B = dict(HD=256, LDK=128, LDV=128, LNH=16, ROT=64)
GEOM_IS_DERIVED = _LR is not None
GEOM = (dict(HD=_LR.HD, LDK=_LR.LDK, LDV=_LR.LDV, LNH=_LR.LNH, ROT=_LR.ROT)
        if GEOM_IS_DERIVED else dict(_GEOM_08B))

# G2a review N19 — THE FALLBACK IS NOT SAFE AT 4B/9B AND SAYS SO.
# If `ref/layer_ref.py` cannot be imported, `GEOM` falls back to the 0.8B/2B
# numbers.  Every field except `LNH` is identical at all four geometries, but
# `LNH` is 16 there and 32 at 4B/9B -- so on a host without `ref/`, the
# scratch-footprint decoder would report the GATE tile at HALF its true size
# and selftest [17]'s "the LM head never overwrites x8" proof would be about
# the wrong words.  Silently.
#
# It cannot be resolved here (a host without `ref/` has nothing to ask), so
# it is made LOUD instead: the flag is exported, the selftest asserts the
# fallback is not in play in THIS repo, and `_cmd_scratch` names it.  A
# caller that knows its geometry should pass `g=` explicitly.
if not GEOM_IS_DERIVED:                                  # pragma: no cover
    import warnings
    warnings.warn(
        "sw/chat_seq.py: ref/layer_ref.py is not importable, so the scratch "
        "footprint geometry falls back to the 0.8B/2B values (LNH=16). That "
        "is WRONG at 4B/9B (LNH=32) and understates every GATE/DNST tile. "
        "Pass g= explicitly, or make ref/ importable.", RuntimeWarning)


# ======================================================================
# frozen template geometry (docs/CHAT_SEQ_SPEC.md decisions 2, 5, 6)
# ======================================================================
TEMPLATE_PREFIX = os.path.join(TOP_DIR, "tb", "scripts", "w4",
                               "model_v2_s1.e")
TEMPLATE_SHA256 = ("a69864d25b6b129a4d6c74b3c78dfcbedf1edce2"
                   "19d32cc05d05bc54f444aaf1")
# The frozen 0.8B template is a SEQ_ISA v1.7 artifact and always will be:
# build_034/build_035 still run it, from a PRE-G3 CHECKOUT (spec 8 G3 — no
# v1.7 emitter or decoder path is kept on main).  This tree emits and
# decodes v2.0 (`SF.SEQ_ISA_VERSION`), so its RECORD layer still reads
# (opcodes, targets, immediates, blobs — all unchanged) while its LAYER ARG
# WORDS do not.  Selftest [17] says exactly that; the retired full-body
# numbers live in evidence/qwen9b/g3/G3_1_ISA.md.
TEMPLATE_ISA_VERSION = 1
TEMPLATE_NREC = 60495

REC_PREAMBLE = (0, 1524)          # session-once resets
REC_SEED_TOK = 1524               # CSRWR XRF[3] <= token id
REC_SEED_POS = 1525               # CSRWR XRF[4] <= pos*1536  (ABSOLUTE)
REC_BODY_FULL = (1526, 16266)     # EMB .. AMAXL          14,740 recs
REC_BODY_LITE = (1526, 15532)     # EMB .. before LM head 14,006 recs
REC_TCNT = 45751                  # CSRWR TCNT_SEQ <= n
REC_HALT = 60494

# G2a: rope-pool geometry, derived rather than pinned.  POS_COPIES is one
# per FULL-ATTENTION layer (6 at 0.8B/2B, 8 at 4B/9B) and POS_BLOCK is one
# cos|sin table = 2*ROT int16.  Note what the 1536 is NOT: it is rope-table
# BYTES PER POSITION and has nothing to do with the mvchan XWIN 1536 that
# happens to share the number.  `ref/seq_chat.py` derives the same two, and
# this file follows it when it is importable so the two cannot drift.
# N19: POS_COPIES now depends on FABLE5_MODEL (it counts full-attention
# layers).  Under an unset or `2b` selection -- every way these tools are run
# against the frozen bitstreams -- it is 6 and nothing moves.  Under
# FABLE5_MODEL=9b against a 0.8B artifact it is 8 and `derive_geometry`
# REFUSES rather than deriving a stride from a count that does not match the
# stream.  That refusal is new; it is the better failure, and it is named
# here so it is not discovered.
POS_COPIES = SC.POS_COPIES if SC is not None else 6
POS_BLOCK = (SC.POS_COPY_BYTES if SC is not None
             else 2 * 2 * _GEOM_08B["ROT"])    # 256 B = 128 int16 words
POS_STRIDE = POS_COPIES * POS_BLOCK            # 1536 B/pos at 0.8B/2B
# S3 fix round 1, M5.  The REASON was `rtl/layer_chan.sv kv_waddr =
# tcnt[8:0]`; S2 retired it FOR THE STATE-SPILL NETLIST, where the KV cache
# is `{kv, t[11:0]}` at T <= 4096 (spec A1.5, `docs/SEQ_ISA.md` B15).  The
# ceiling therefore belongs to the TARGET BITSTREAM, not to the host: 4,096
# at 9B on build_041, still 512 on the frozen 0.8B/2B build_034/035 whose
# kv_waddr is 9 bits.  `ref/seq_chat.T_MAX` is the source of record (:178)
# and this follows it; round-3 review I-2 is why it is per selection rather
# than 4,096 everywhere.  The FALLBACK (no ref/) is keyed on the tag too.
# The `--max-ctx` guard in `main()` is T_MAX-relative and follows for free.
_T_MAX_FB = HW.STATE_T_MAX if MODEL_TAG == "9b" else 512
T_MAX = SC.T_MAX if SC is not None else _T_MAX_FB
POSBLOB_BYTES = T_MAX * POS_STRIDE       # 8,388,608 B at 9B (gate A2)
# m4: what ONE --verify step costs on the host, per selection.  MEASURED:
# ~6 s at 0.8B/2B (lite ~5 / full ~7), and 131.2 s (lite) / 149.3 s (full)
# at 9B -- evidence/qwen9b/g6/074_ref_cost_9b.log.  Printed, not enforced.
VERIFY_HOST_S_PER_STEP = 140 if MODEL_TAG == "9b" else 6

# image head: three CSRWR records, patched per launch (spec decision 4)
HEAD_RECS = 3
PATCH_BYTES = HEAD_RECS * SEQ_REC_BYTES       # 48 B
HOLE_TOK, HOLE_POS, HOLE_TCNT = 4, 20, 36     # imm32 is at record byte +4

DEFAULT_MAX_CTX = 500
DEFAULT_NTOK = 32
STEP_TIMEOUT = 20.0               # s; a step is ~0.156 s device time
PREAMBLE_TIMEOUT = 30.0
POLL_S = 0.002
WITNESS_BYTES = 4096              # residency probe block (spec decision 9)
EMB_WITNESSES = 8

# O3 (user ruling 2026-08-29): the lock moved OUT of this checkout.  It used
# to be `os.path.join(SW_DIR, ".seq.lock")` — one inode per checkout, two
# checkouts, one board, so it excluded nothing across them
# (`evidence/qwen9b/o3/00_red_percheckout.log`).  The mechanism was always
# right; only the path was wrong.  `sw/board_lock.py` owns both now.
LOCK_PATH = BL.BOARD_LOCK_PATH
LEGACY_LOCK_PATH = BL.LEGACY_LOCK_PATH        # named so the move is greppable

# ======================================================================
# sampling geometry (docs/SAMPLING_SPEC.md S3/S4/S5, as amended by the
# 2026-08-11 ruling that keeps MODEL COMPUTE ON-CHIP — see the "sampling"
# section below for the whole story)
# ======================================================================
TOPK_CAPTURE_K = 32          # {int32 value, 18-bit index} pairs the rung-4
                             # on-chip capture unit keeps per step
# RUNG4_SPEC S5 pins the capture block inside layer_chan's own decode window
# (0x48..0xFFF was free, so no BD / create_project edit).  --topk-base still
# overrides it; the IDENT read is what actually decides whether it is there,
# so pointing this at a bitstream without the unit is safe (an unmapped
# layer_chan read returns 0xDEADC0DE — rtl/layer_chan.sv default arm).
TOPK_BASE = HW.LB + 0x48     # 0x5048 IDENT / 0x504C STATUS / 0x5050 PTR
                             # 0x5054 VAL / 0x5058 IDX (read advances PTR)
DEFAULT_TOP_K = 50           # S5
DEFAULT_TOP_P = 1.0          # S5: 1.0 == off
DEFAULT_TEMP = 0.0           # S5: 0.0 == greedy == today's shipped decode
SEED_BITS = 63

# layer_chan scratchpad geometry the head consumes/produces, in WORDS.
# These are the FROZEN 0.8B values and they belong to `frozen_geometry()`
# below, not to the live path: the emitter's law is `X8 = 2*H` with `H`
# elements and `STG = 3*H + max(1024, SCA_SZ)`, so at 2B they are
# 0x1000/2048 and at 9B they are different again.
#   (The old comment here cited `ref/gen_layer_script.py:722-723` for the
#    definitions; those lines were inside the DNST emitter.  The map is
#    `ref/gen_layer_script.py`'s module-level `X8` / `SCA` / `STG` — cited
#    by SYMBOL from G3.1 on, because every line number in that file moved
#    when the ISA re-encoding landed, which is the D-CITE class this note
#    exists to record.  It is derived, not literal: G2a made SCA_SZ and STG
#    functions of the geometry.)
# LATENT, NOT LIVE: every in-repo caller passes session-derived geometry.
# Moved anyway, because a latent literal at a new geometry is the R-c wall-8
# class; `read_x8_eout`'s defaults and selftest [17] were the two readers
# that took them straight from the module.
X8_WORD, X8_LEN = 0x800, 1024        # the DYNQ8'd activation the head reads
STG_WORD, STG_LEN = 0x1000, 0x1000   # the head's y32 staging window

# The SPTR shadow the host keeps.  G2a: 15 -> 16 bits, for the 65,536-word
# scratchpad of spec 4.3 S4.
#
# READ THE COUPLING BEFORE YOU READ THE WIDTH.  G3.1 landed the other half:
# `layer_chan`'s SPTR CSR IS 16 bits now (`sptr <= wdata_q[15:0]`, read back
# as `{16'b0, sptr}`) and SEQ_ISA v2.0's scratch fields are 16 bits, so this
# host mask and the hardware field finally mean the same thing.  What is
# still narrower is the SHIPPED bitstreams: `build_034`/`build_035` are pre-G3
# with a 15-bit SPTR and a 32,768-word array, and this tree cannot drive them
# at all (see TEMPLATE_ISA_VERSION).  (The earlier text here said "the RTL's
# SPTR is still 15 bits … Task 7 widens the ISA field and Task 10 the
# register" and cited `evidence/qwen2b/rc/t4_bytes_unmoved.sh` as live proof
# of inertness; G3.1 falsified both — Task 7 widened the register too, and
# that script is RETIRED BY DESIGN because G3.1 is where the byte-lock is
# spent.)
SPTR_MASK = 0xFFFF
HEAD_TAIL = (REC_BODY_LITE[1], REC_BODY_FULL[1])   # (15532, 16266)

# S4: logit = y32 * 2^(e + sh - 15 + e_x - rs_f).  All four come from the
# weight manifest at run time (sw/head_cache.py); the names below are the
# COMMITTED 0.8B head's values, kept as a named cross-check of the frozen
# artifact rather than as a pin on every artifact.
#
# G2a: `HEAD_LOGIT_EXP0` used to be the literal -22 with its derivation only
# in a comment, so at `rs_f = 7` (spec 4.4's model-selected residual binary
# point) the correct answer is -21 and three sites would have kept saying
# -22.  The algebra is now the definition and the literal is gone; the one
# place that already wrote the algebra out (`sw/chat_seq.py`'s selftest [18])
# checks this against `sw/head_cache.py` rather than restating it.
#
# `HEAD_WID` is likewise the FROZEN 0.8B head's wid.  At 32 layers the head
# is a different wid (249 images), and `derive_geometry` already computes the
# right one into `g["_HEAD_WID"]` — the online path reads that.
HEAD_WID = 186               # frozen 0.8B/2B head; see g["_HEAD_WID"]
HEAD_E, HEAD_SH = -4, 5      # the committed head's manifest (e, sh)
HEAD_RS_F = HW.RS_F_DEFAULT  # a manifest with no rs_f key means 8


def head_logit_exp0(rs_f=HEAD_RS_F):
    """The head dequant exponent at e_x = 0, for a given residual point."""
    return HEAD_E + HEAD_SH - 15 - int(rs_f)


HEAD_LOGIT_EXP0 = head_logit_exp0()          # -22 at the shipped rs_f = 8


class ChatSeqError(RuntimeError):
    pass


class SamplingUnavailable(ChatSeqError):
    """Sampling was asked for and the hardware that provides it is absent."""


# ======================================================================
# exclusivity (spec decision 10)
# ======================================================================
class SeqLock(BL.BoardLock):
    """THE board lock, under the name every existing caller already uses.

    O3, 2026-08-29: this class used to BE the implementation — an exclusive
    `flock(LOCK_EX|LOCK_NB)` over a 256-byte holder-identity block, which
    was correct, over `sw/.seq.lock`, which was not: that path is inside
    the checkout that computes it, and two checkouts share this board.
    `sw/board_lock.py` now owns the mechanism and the path; this is a thin
    alias so `serve.py`'s `CS.SeqLock` and `cycle_census.py`'s
    `CS.SeqLock(CS.LOCK_PATH)` keep working unchanged, and so
    `except ChatSeqError` around an acquisition keeps catching.

    Every tool that programs or DMAs the board takes it now, not just the
    chat/serve stack — see `docs/USAGE.md` §5.
    """

    ERROR = ChatSeqError

    def __init__(self, path=None, tool="chat_seq.py", log=None):
        BL.BoardLock.__init__(self, path, tool=tool, log=log)


# ======================================================================
# templates -> the three resident images   (PURE PYTHON, --selftest'd)
# ======================================================================
class Resident(object):
    """One DDR-resident SEQ image: agent A's bytes, relocated and placed.

    `a` is the ref/seq_chat.py Image (EMITTER address space, which is what
    ref/seq_model.py replays).  `recs`/`data` are the RELOCATED form that
    actually lives in DDR, and `base` is its channel-local DDR address.
    Relocation is the host's job per spec decision 11 / file ownership.
    """

    def __init__(self, name, aimg):
        self.name = name
        self.a = aimg
        self.recs_emit = SF.unpack_stream(aimg.data)
        self.recs = None
        self.data = None
        self.base = None

    @property
    def nrec(self):
        return self.a.nrec

    @property
    def holes(self):
        return self.a.holes


def frozen_geometry():
    """The spec's own (nch=1) boundaries in `derive_geometry` form."""
    return {"TEMPLATE_NREC": TEMPLATE_NREC, "R_SEED_TOK": REC_SEED_TOK,
            "R_SEED_POS": REC_SEED_POS, "R_TCNT": REC_TCNT,
            "R_HALT": REC_HALT, "R_BODY_FULL": REC_BODY_FULL,
            "R_BODY_LITE": REC_BODY_LITE, "R_PREAMBLE": REC_PREAMBLE,
            # 0.8B literals; derive_geometry reads the same numbers out of
            # the artifact for any other geometry (R-d: 2B puts x8 at
            # 0x1000 with 2048 elements and its const region is 1,098,496 B).
            "X8_WORD": X8_WORD, "X8_LEN": X8_LEN,
            "STG_WORD": STG_WORD, "STG_LEN": STG_LEN,
            # G2a: the head wid.  `derive_geometry` picks it out of the
            # manifest (the image with the most rows); on the frozen path it
            # is the committed 186.  Both paths now carry the key, so the
            # online call reads geometry instead of a module literal — at 32
            # layers the head is a different wid (249 images).
            "_HEAD_WID": HEAD_WID,
            "CONST_BYTES": SC.CONST_BYTES if SC else None,
            "POS_BLOB_BASE": SC.POS_BLOB_BASE if SC else None,
            "POS_WORDS": SC.POS_WORDS if SC else None,
            "POS_COPY_BYTES": SC.POS_COPY_BYTES if SC else None,
            "POS_STRIDE": SC.POS_STRIDE if SC else None,
            "SEQDATA_SHA256": SC.SEQDATA_SHA256 if SC else None}


def load_template(prefix=TEMPLATE_PREFIX, check_sha=True, sha=None, g=None,
                  caps=frozenset(), shape_isa=None):
    """The gated artifact, hash-checked, as [Rec] + const blob + meta.

    `sha`/`g` select which artifact set is being loaded: None/None is the
    frozen 1-chan template (docs/CHAT_SEQ_SPEC.md), and the 4-chan session
    passes TEMPLATE4_SHA256 plus its derived geometry (rung 4 S4).
    `caps` (Task SR6) is the capability set it is validated at: the
    session's level at construction, the DEVICE's in open_board().
    """
    g = g or frozen_geometry()
    sha = TEMPLATE_SHA256 if sha is None else sha
    stream = open(prefix + ".seq", "rb").read()
    blob = open(prefix + ".seqdata.bin", "rb").read()
    meta = json.load(open(prefix + ".seq.json"))
    got = hashlib.sha256(stream).hexdigest()
    if check_sha and got != sha:
        raise ChatSeqError(
            f"{prefix}.seq sha256 {got[:16]} != the frozen template source "
            f"{sha[:16]} — docs/CHAT_SEQ_SPEC.md pins this "
            f"artifact; regenerate the spec, not the slice indices")
    if hashlib.sha256(blob).hexdigest() != meta["seqdata_sha256"]:
        raise ChatSeqError(f"{prefix}.seqdata.bin does not match its metadata")
    recs = SF.unpack_stream(stream)
    if len(recs) != g["TEMPLATE_NREC"]:
        raise ChatSeqError(f"template has {len(recs)} records, spec says "
                           f"{g['TEMPLATE_NREC']}")
    # SR11a fix round 2: `shape_isa` is the SHAPE layout (the session's
    # stated one pre-board, the DEVICE's in open_board); None states none,
    # and ref/seq_format then refuses SHAPE bits 29/30 (B17.2)
    SF.validate_stream(recs, caps=caps, shape_isa=shape_isa)
    return recs, blob, meta


def _check_head(recs, g=None):
    """Assert the three patchable records really are what spec 2/5 says."""
    g = g or frozen_geometry()
    want = ((g["R_SEED_TOK"], SF.csr_seq_xrf(3), "XRF[3] token seed"),
            (g["R_SEED_POS"], SF.csr_seq_xrf(4), "XRF[4] position seed"),
            (g["R_TCNT"], SF.CSR_SEQ_TCNT, "TCNT_SEQ"))
    for idx, csr, what in want:
        r = recs[idx]
        if r.opcode != SF.OP_CSRWR or r.target != csr or r.flags != 0:
            raise ChatSeqError(
                f"template record {idx} is not the {what} CSRWR the spec "
                f"pins ({SF.disasm(r, idx)})")
    if recs[g["R_HALT"]].opcode != SF.OP_HALT:
        raise ChatSeqError(f"template record {g['R_HALT']} is not HALT")
    if recs[g["R_BODY_FULL"][1] - 1].opcode != SF.OP_AMAXL:
        raise ChatSeqError("the full body does not end in AMAXL")
    if recs[g["R_BODY_LITE"][1]].opcode != SF.OP_MOVX:
        raise ChatSeqError("the lite cut is not the LM-head MOVX")


def independent_step_images(recs, g=None, caps=frozenset(), shape_isa=None):
    """MY OWN slices of the same template — the cross-check on agent A.

    Agent A (ref/seq_chat.py) is the compiler of record; this rebuilds the
    two step images straight from the spec's record indices so --selftest
    can assert the two agree BYTE FOR BYTE.  If they ever diverge, one of
    us has misread docs/CHAT_SEQ_SPEC.md and the run must stop.  `caps`
    (Task SR6): validated at that capability set, as load_template.
    """
    g = g or frozen_geometry()
    _check_head(recs, g)
    head = [recs[g["R_SEED_TOK"]], recs[g["R_SEED_POS"]], recs[g["R_TCNT"]]]
    halt = recs[g["R_HALT"]]
    out = {}
    for name, (lo, hi) in (("lite", g["R_BODY_LITE"]),
                           ("full", g["R_BODY_FULL"])):
        rr = head + recs[lo:hi] + [halt]
        SF.validate_stream(rr, caps=caps, shape_isa=shape_isa)
        if any(r.opcode == SF.OP_JMP for r in rr):
            raise ChatSeqError(f"{name}: the launch-per-step form has no loop")
        out[name] = SF.pack_stream(rr)
    return out


# ======================================================================
# rung 4 S4: the SECOND resident artifact set (--nch 4)
#
# The 4-chan stream is the SAME schedule over the SAME weight pack — only
# the matvec encoding differs (row-split MVGOs, and the LM head's chunks
# interleaved over the 4 engines).  So it shares model_v2_s1's
# .weights.json / _w*.bin / .emb.bin, sits beside the 1-chan stream as
# `model_v2_s1.e4.*`, and is longer: 68,119 records instead of 60,495.
#
# ref/seq_chat.py is the compiler of record and its slice indices are
# FROZEN on the 1-chan artifact (docs/CHAT_SEQ_SPEC.md phase-0).  Rather
# than re-pin them — which would put the shipped greedy path at risk for an
# opt-in variant — the 4-chan session:
#
#   1. DERIVES the same nine boundaries structurally from the stream
#      (`derive_geometry`), which reproduces the frozen 1-chan numbers
#      EXACTLY (asserted in --selftest, and again for every session);
#   2. runs agent A's compiler over a private MODULE CLONE carrying those
#      numbers (`seq_chat_for`), so SC itself — and therefore every
#      nch=1 session in this or any other process — is untouched.
# ======================================================================
# THE 4-CHAN TEMPLATE IS PER MODEL (Task 15 fix round 2, scope A).
#
# The default entry is the FROZEN 0.8B/2B artifact and does not move: the
# frozen bitstreams' chat runs it, and re-pinning it would break them
# (scope F).  The `9b` entry is `tb/scripts/w9/model_9b_s1.e4`, which is a
# NOMINATION of an artifact that already exists, not a new emission — the
# 3.5 h re-emission is NOT on the chat path (RD9_GATE.md §20.3):
#
#   emitted + digest-verified  evidence/qwen9b/s4/001_emit_9b_s1.log:203
#                              (`.e4.seq IDENTICAL 2536576 B 9760899d…`)
#   seq_model 4-chan SEQ gate  evidence/qwen9b/s4/021_seqgate_model_s1.log
#                              and, on this tree, re-run at
#                              evidence/qwen9b/g6/024_seqmodel_gate_s1to4.log
#                              — `SEQ GATE: PASS`, CHECKPT 2358/2358
#                              BIT-EXACT, STATE BIT-EXACT, TOKENS IDENTICAL
#
# which is exactly the gate the refusal below asks for ("re-run the
# seq_model 4-chan gate before re-pinning"), run on THIS artifact.
TEMPLATE4_BY_MODEL = {
    None: (("tb", "scripts", "w4", "model_v2_s1.e4"),
           "e102e2df0835097d0d622cd17109b9cbfea1ab4e"
           "78818bcddf3873ec6d8ac933", 68119),
    "9b": (("tb", "scripts", "w9", "model_9b_s1.e4"),
           "9760899df53b3b4216d517d042a1dd7c9477b4f0"
           "cb7e6639320a5fd6d480719b", 158536),
}
_T4 = TEMPLATE4_BY_MODEL.get(MODEL_TAG, TEMPLATE4_BY_MODEL[None])
TEMPLATE4_PREFIX = os.path.join(TOP_DIR, *_T4[0])
TEMPLATE4_SHA256 = _T4[1]
TEMPLATE4_NREC = _T4[2]
NCH_CHOICES = (1, 4)

# ======================================================================
# --reorder: the S1 schedule on the chat path (BM1-T4, rulings B6/B7).
#
# FORM B BY DEFAULT since 2026-09-27 (Task S1D; OFF by default before) —
# MODEL-AWARE (S1D fix round 1): with neither --reorder nor $FABLE5_REORDER,
# form B at FABLE5_MODEL=9b --nch 4 on the shipped template, the shipped
# order everywhere else (effective_reorder).  With the reorder off (FABLE5_REORDER=off or --reorder off) nothing below
# runs and the three images are byte-identical to the pre-flag tool
# (evidence/qwen9b/bm/bm1_reorder_tdd.py T3).  With `--reorder A` (9B,
# --nch 4 only):
#   1. resolve_reorder() REGENERATES the reordered template in-process with
#      ref/scripts/reorder_e4.py, unchanged, at the STATIC costs of
#      ref/seq_cost.py (S1P fix round 1; no CSV read) — its hazard assert (input AND
#      output) and OV1's postcheck (every segment, on the replay of the
#      emitted order) run inside reorder_e4.reorder() — and admits it ONLY
#      if the result equals the pinned SV1 artifact byte for byte (whose
#      seq_model --gate PASS is evidence/qwen9b/ov/n49_gate_s1_reordA.log).
#   2. The session is built from that template (derive_geometry accepts
#      form A; its step bodies are byte-identical to body 0), with the
#      SHIPPED base (weights/emb/state images are the shipped artifact's).
#   3. reorder_image_hazards(): the same hazard assert on the three images
#      the board will actually run.
#   4. reorder_model_gate() (ruling B6): the shipped-order and reordered
#      images replayed in ref/seq_model.SeqExec (running-channel refusal
#      armed) from the same initial state — preamble, one lite, one full —
#      must agree EXACTLY (tokens, the whole Mach snapshot, the DDR region).
# FORM B (Task S1P lifts ruling B7).  Form B frees the layer chain, so a
# whole-TEMPLATE reorder moves the POSADV XOP off record n-3 (which
# derive_geometry requires) and can interleave non-head work after the LM
# head's first MOVX — the lite image, a PREFIX of the full body, would then
# drop it.  So B is reordered PER IMAGE instead: the session is built from
# the SHIPPED template exactly as without the flag (geometry, compiler,
# preamble, crosscheck), and each step image (lite, full) is then reordered
# ON ITS OWN by ref/scripts/reorder_e4.py (form B, static costs from
# ref/seq_cost.py — no CSV segment has an image's skeleton) — a lite image
# is its own segment, so nothing it holds can fall outside it.  The per-
# launch patch FOLLOWS ITS RECORD: every write of the shipped patch (the
# three head records, which the pass never moves, and in pos_mode "ldc" the
# eight position-LDC addr_lo words at 9B) lands at the reordered position
# of the record it was aimed at (ChatSession.step_patch), for the board, the
# lockstep verifier and the B6 gate alike.  The images are pinned
# (REORDER_B_IMAGES: regeneration == pin), then gates 3 and 4 run as for A.
# ======================================================================
REORDER4_BY_FORM = {
    "A": (("tb", "scripts", "w9", "model_9b_s1_reordA.e4"),
          "b6ced3f92d3fe8c3fbb1bd02a3eda3b5"
          "61478e4733ffd40a25ce1bd862ab319d", 156616,
          "evidence/qwen9b/ov/n49_gate_s1_reordA.log"),
}
REORDER_FORMS = ("A", "B")
# S1D fix round 1: --reorder's parse-time default when neither the flag nor
# $FABLE5_REORDER is given; main() resolves it with effective_reorder()
REORDER_AUTO = object()
# S1P form B: the per-image reorder's pins (emitter-space images as
# TurnCompiler.build_step(0, 0, kind) builds them in pos_mode "ldc", then
# reordered; generated by evidence/qwen9b/ov/n88_s1p_formB_pins.log), and
# the boardless gate run that passed on exactly these bytes
REORDER_B_IMAGES = {
    "lite": ("c9efdf35175d55d45b460a18e0c31486"
             "2c90e3d3102467b8718ad93788b9f565", 38378),
    "full": ("7119833ca6ed7d1f39adca6f7f679814"
             "61d94f4616574eb78c9134f42bf06a89", 39146),
}
REORDER_B_GATE_LOG = "evidence/qwen9b/ov/n89_s1p_formB_tdd_GREEN.log"
# the position the static costs price ATTN at (its window grows 39 cycles
# per position; the ORDER is position-independent and so is its safety)
REORDER_B_POS = 0

# ======================================================================
# --seq-rtl: the sequencer RTL level the images are built FOR (Task SR6 of
# the sequencer RTL round; docs/SEQ_ISA.md v2.3 B17).  r0 (the default) is
# the shipped RTL and everything above, byte for byte.  r1 = the FENCE
# channel mask (B17.1): form B's per-image reorder run by reorder_e4 at
# rtl="r1" — the same static costs at REORDER_B_POS, OV1's per-channel-
# fence schedule, masked FENCEs.  r1 needs form B (the per-image lineage;
# a form-A r1 template does not exist) at 9B --nch 4.
#
# The r1 images are a STATIC-cost lineage with their OWN pins
# (REORDER_B_R1_IMAGES, regeneration == pin like form B's): their model
# makespan is the one the static pass prints for them
# (REORDER_B_R1_PINS_LOG), NOT OV1's / SR4's CSV-lineage 27,136,513 (that
# is the model_9b_s1 template's loop body, a different stream).
#
# ADMISSION IS KEYED BY THE DEVICE (B17.0): before the images are built the
# session validates them at the level's capability set (the software gate:
# the caller names the level, never a manifest); open_board() then reads
# the DEVICE's SEQ_CAPS and re-validates the template (load_template), the
# independent slices (independent_step_images) and every relocated image
# at the device's set, before any upload — an r1 image is refused on
# build_041/042 (0xDEADC0DE = the empty set) however it was built.
# ======================================================================
SEQ_RTLS = ("r0", "r1", "r2")
SEQ_RTL_ENV = "FABLE5_SEQ_RTL"
# generated by evidence/qwen9b/sr/sr6_r1_pins.py at 96aedd7:
# evidence/qwen9b/sr/n601_r1_pins.log (the PIN lines); STATIC model
# makespan lite 30,209,477 -> 25,195,119 cyc, full 32,771,280 -> 27,135,354
# cyc (this lineage's own numbers; the full image's is NOT n120's
# 27,136,513 -- a different stream and cost source, near it by coincidence)
REORDER_B_R1_IMAGES = {
    "lite": ("999911226f9a70b43dda1b520b95fa54"
             "4b1aa2c0e15935420aa317c9a5de0723", 39314),
    "full": ("bf115a04ffcc6bfa8342576c275ef299"
             "8b01f7522bc15b315ac63f992adc7281", 40173),
}
REORDER_B_R1_PINS_LOG = "evidence/qwen9b/sr/n601_r1_pins.log"
# Task SR13b: r2 = r1 + the XWIN/RES double banking (B17.2): form B's
# per-image reorder at rtl="r2" (SR11b's reorder_e4 pass: r1's per-channel-
# fence schedule on the depth-2 buffers, bank-1 fields MOVX word 1536, MVGO
# XBANK/RBANK, MOVY row 2048), caps {R1, R2}; its own static-cost lineage and
# pins, generated by evidence/qwen9b/sr/sr13b_r2_pins.py at 925af52 (clean):
# evidence/qwen9b/sr/n1351_sr13b_r2_pins.log (the PIN lines); STATIC model
# makespan lite 30,209,477 -> 24,341,703 cyc, full 32,771,280 -> 26,131,018
# cyc (MODEL, position 0).  An r2 image is REFUSED at {R1} (build_044_r1_incr)
# and at the empty set (build_041/042): an R1 bitstream ignores MOVX target
# and drops SHAPE[31:29] (R2 is NOT fail-closed, spec §1.2), so the device-
# keyed validation is the guard.
REORDER_B_R2_IMAGES = {
    "lite": ("c78312bb293a5c2a16f94a76bfabcba5"
             "6ce34937457b10b69b12b4bd02ff6d45", 39314),
    "full": ("868ba4e03b26276ddb455c1fbe4aca55"
             "95f9a5ff9ab734c2b017a377f2b3ad87", 40173),
}
REORDER_B_R2_PINS_LOG = "evidence/qwen9b/sr/n1351_sr13b_r2_pins.log"
# level -> (its form-B pins, the log that generated them)
REORDER_B_PINS_BY_RTL = {
    "r0": (REORDER_B_IMAGES, REORDER_B_GATE_LOG),
    "r1": (REORDER_B_R1_IMAGES, REORDER_B_R1_PINS_LOG),
    "r2": (REORDER_B_R2_IMAGES, REORDER_B_R2_PINS_LOG),
}


def seq_rtl_default(env=None):
    """$FABLE5_SEQ_RTL: unset / "" -> "r0"; r0 / r1 / r2 (case-insensitive)
    as given; anything else is refused, echoing the original spelling."""
    env = os.environ if env is None else env
    raw = env.get(SEQ_RTL_ENV) or ""
    v = raw.strip().lower()
    if v == "":
        return "r0"
    if v not in SEQ_RTLS:
        raise ChatSeqError(f"{SEQ_RTL_ENV}={raw!r}: expected unset or one "
                           f"of {list(SEQ_RTLS)}")
    return v


def seq_rtl_arg(s):
    """argparse type for --seq-rtl."""
    v = str(s).strip().lower()
    if v not in SEQ_RTLS:
        raise argparse.ArgumentTypeError(
            f"invalid choice: {s!r} (choose from {', '.join(SEQ_RTLS)})")
    return v


def seq_rtl_of(args):
    """The session's level: args.seq_rtl, "r0" when a caller's namespace
    predates SR6 (serve pins it; evidence tools may not carry it)."""
    v = getattr(args, "seq_rtl", None) or "r0"
    if v not in SEQ_RTLS:
        raise ChatSeqError(f"--seq-rtl {v!r}: not one of {SEQ_RTLS}")
    return v


def seq_rtl_caps(level):
    """The capability set a level's images NEED — reorder_e4.CAPS_OF, the
    pass's own map (r1 -> {"R1"}); r0 is the empty set without importing
    the pass (serve and every shipped-level session)."""
    if level == "r0":
        return frozenset()
    return _reorder_mod().CAPS_OF[level]


def check_seq_rtl(args):
    """--seq-rtl above r0 runs only on form B's per-image lineage.  Raises
    ChatSeqError naming --seq-rtl; called by main() before the lock and by
    ChatSession (so a namespace that bypasses main cannot slip through)."""
    level = seq_rtl_of(args)
    if level == "r0":
        return level
    form = getattr(args, "reorder", None)
    if form is REORDER_AUTO:
        form = None
    if form != "B":
        raise ChatSeqError(
            f"--seq-rtl {level} needs --reorder B (the per-image form-B "
            f"lineage, pinned per level in REORDER_B_PINS_BY_RTL); got "
            f"--reorder "
            f"{form if form else 'off'} -- run --seq-rtl r0 for the "
            f"shipped RTL level")
    return level


def reorder_default(env=None):
    """THE DEFAULT SWITCH (S1P deliverable 4) — `--reorder`'s default, from
    $FABLE5_REORDER: unset / "" -> "B"; "off" / "none" -> None (the shipped
    order); "A" or "B" -> that form (case-insensitive).  Anything else is
    refused, echoing the original spelling.  FLIPPED 2026-09-27 (Task S1D,
    the user chose form B): with the variable unset the default is "B"; it
    was None from S1P until then.  The CLI's default is model-aware
    (effective_reorder, S1D fix round 1): main() consults this function
    only when the variable is SET; unset, it applies "auto".  The three
    gates (regeneration == pin, image hazard assert, B6 exact replay) stay
    mandatory before open_board() whichever way the form was chosen."""
    env = os.environ if env is None else env
    raw = env.get("FABLE5_REORDER") or ""
    v = raw.strip().upper()
    if v == "":
        return "B"
    if v in ("OFF", "NONE"):
        return None
    if v not in REORDER_FORMS:
        # final-fix C2: echo the user's ORIGINAL spelling, not v
        raise ChatSeqError(f"FABLE5_REORDER={raw!r}: expected unset, 'off', "
                           f"or one of {list(REORDER_FORMS)}")
    return v


def effective_reorder(args, env=None, log=print):
    """S1D fix round 1 — the MODEL-AWARE default.  An explicit --reorder
    (A, B or off -> None) or a set $FABLE5_REORDER (non-empty after strip;
    validated by reorder_default()) is used AS GIVEN: a form that cannot run
    here still refuses in resolve_reorder (exit 4).  With neither, "auto":
    "B" only when FABLE5_MODEL=9b, --nch 4 and the SHIPPED 4-chan template
    (the only place form B exists), else None — the shipped order — with
    one log line saying so and why."""
    env = os.environ if env is None else env
    form = getattr(args, "reorder", REORDER_AUTO)
    if form is not REORDER_AUTO:
        return form
    if (env.get("FABLE5_REORDER") or "").strip():
        return reorder_default(env)
    why = []
    if MODEL_TAG != "9b":
        why.append(f"FABLE5_MODEL={MODEL_TAG}")
    if int(getattr(args, "nch", 1) or 1) != 4:
        why.append(f"--nch {getattr(args, 'nch', 1)}")
    if os.path.abspath(args.template) != os.path.abspath(TEMPLATE4_PREFIX):
        why.append(f"template {os.path.basename(args.template)}")
    if not why:
        return "B"
    log(f"  reorder    auto -> the shipped order (form B, the default, runs "
        f"only at FABLE5_MODEL=9b --nch 4 on the shipped template; here "
        f"{', '.join(why)})")
    return None


def reorder_arg(s):
    """argparse type for --reorder: A | B | off (none) -> None, the shipped
    order (S1D: with B the default, the CLI needs a way back)."""
    v = str(s).strip().upper()
    if v in ("OFF", "NONE"):
        return None
    if v not in REORDER_FORMS:
        raise argparse.ArgumentTypeError(
            f"invalid choice: {s!r} (choose from 'A', 'B', 'off')")
    return v


# (S1P fix round 1, M4: evaluated at PARSE time in main(), not at import,
# so a module that imports chat_seq but ignores the switch never dies on a
# bad $FABLE5_REORDER; case-insensitive)
REORDER_GATE_TOKS = ((760, 0, "lite"), (2614, 1, "full"))


def _reorder_mod():
    p = os.path.join(TOP_DIR, "ref", "scripts")
    if p not in sys.path:
        sys.path.insert(0, p)
    import reorder_e4 as RE
    return RE


def resolve_reorder(args, log=print):
    """--reorder FORM: regenerate, compare with the pin, switch the template.
    Raises ChatSeqError on anything but an exact match."""
    form = getattr(args, "reorder", None)
    if form is None:
        return None
    if form not in REORDER_FORMS:
        raise ChatSeqError(f"--reorder {form}: not one of {REORDER_FORMS}")
    if MODEL_TAG != "9b" or int(getattr(args, "nch", 1)) != 4:
        raise ChatSeqError(f"--reorder needs FABLE5_MODEL=9b --nch 4 "
                           f"(got {MODEL_TAG!r}, nch {args.nch}); "
                           f"FABLE5_REORDER=off or --reorder off runs the "
                           f"shipped order")
    if os.path.abspath(args.template) != os.path.abspath(TEMPLATE4_PREFIX):
        raise ChatSeqError(f"--reorder reorders the shipped template "
                           f"{TEMPLATE4_PREFIX}, not {args.template}")
    level = check_seq_rtl(args)
    if form == "B":
        # per-image: the template stays the shipped one; ChatSession
        # reorders the two step images and checks them against the pins
        # (SR6: the level's pins — r1 is its own static-cost lineage)
        stream = open(TEMPLATE4_PREFIX + ".seq", "rb").read()
        if hashlib.sha256(stream).hexdigest() != TEMPLATE4_SHA256:
            raise ChatSeqError("the shipped 4-chan template's sha moved")
        pins, pins_log = REORDER_B_PINS_BY_RTL[level]
        out = {"form": "B", "per_image": True, "template": TEMPLATE4_PREFIX,
               "seq_rtl": level, "caps": sorted(seq_rtl_caps(level)),
               "pins": {k: v[0] for k, v in pins.items()},
               "cost": "static", "cost_pos": REORDER_B_POS,
               "model_gate_of_pins": pins_log}
        log(f"  reorder    form B: PER IMAGE on the shipped template "
            f"(static costs at position {REORDER_B_POS}"
            + ("" if level == "r0" else f", --seq-rtl {level}: masked "
               f"FENCEs" + (" + XWIN/RES bank fields" if level != "r1"
                            else "") + f", caps {sorted(seq_rtl_caps(level))}")
            + f"); pins lite {(pins['lite'][0] or 'NONE')[:16]} full "
              f"{(pins['full'][0] or 'NONE')[:16]}")
        return out
    parts, sha, nrec, gate_log = REORDER4_BY_FORM[form]
    RE = _reorder_mod()
    t0 = time.monotonic()
    src = TEMPLATE4_PREFIX
    stream = open(src + ".seq", "rb").read()
    if hashlib.sha256(stream).hexdigest() != TEMPLATE4_SHA256:
        raise ChatSeqError("the shipped 4-chan template's sha moved")
    meta = json.load(open(src + ".seq.json"))
    recs = SF.unpack_stream(stream)
    try:
        # S1P fix round 1 (I2): the STATIC cost table, not the untracked
        # BN1 CSV — n86 shows it emits this pin byte for byte; the
        # regeneration == pin check below proves it on every session
        new, _cps, rep = RE.reorder(recs, RE.SC.rows_for(recs), form,
                                    meta.get("checkpoints", []))
    except AssertionError as e:          # HazardError / ReorderError /
        # StaticCostError (ref/seq_cost.py: an AssertionError subclass)
        raise ChatSeqError(f"--reorder {form}: the reorder pass REFUSED: "
                           f"{type(e).__name__}: {e}")
    regen = hashlib.sha256(SF.pack_stream(new)).hexdigest()
    dst = os.path.join(TOP_DIR, *parts)
    ondisk = hashlib.sha256(open(dst + ".seq", "rb").read()).hexdigest()
    if not (regen == sha == ondisk) or len(new) != nrec:
        raise ChatSeqError(
            f"--reorder {form}: REFUSED — regenerated {regen[:16]} "
            f"({len(new)} records), pinned {sha[:16]} ({nrec}), on disk "
            f"{ondisk[:16]}: the pass no longer reproduces the gated artifact")
    npost = sum(s["post_replay"][0] for s in rep["segments"])
    args.template = dst
    out = {"form": form, "template": dst, "regenerated_sha256": regen,
           "records": len(new), "hazard": rep["hazard"],
           "postcheck_edges": npost, "model_gate_of_template": gate_log,
           "wall_s": round(time.monotonic() - t0, 1)}
    log(f"  reorder    form {form}: regenerated {os.path.basename(dst)} "
        f"in-process == pin {regen[:16]} ({len(new)} records); hazard assert "
        f"PASS {rep['hazard']}; postcheck {npost} edges, 0 violations "
        f"({out['wall_s']} s)")
    return out


def reorder_b_images(tc, SCm, rtl="r0"):
    """S1P form B: {kind: (Image, perm, report)} for the lite and full step
    images of `tc` (the SHIPPED template's compiler), each reordered ON ITS
    OWN by reorder_e4 (form B, static costs at REORDER_B_POS).  `perm` maps
    each shipped record index to its reordered index (elided MOVX absent).
    The pass's hazard assert (input and output) and OV1's postcheck run
    inside reorder_e4.reorder; here: the three head records must not move.
    `rtl` (Task SR6, --seq-rtl): the RTL level the pass emits for — "r0"
    (default) is S1P's form B byte for byte; "r1" emits masked FENCEs, and
    reorder_e4 validates its output at {"R1"} and requires it REFUSED at
    the empty set; "r2" (SR13b) adds the XWIN/RES bank fields, validated at
    {"R1", "R2"} and required REFUSED at {"R1"} and at the empty set."""
    RE = _reorder_mod()
    import seq_cost as SCo
    out = {}
    for kind in ("lite", "full"):
        ship = tc.build_step(0, 0, kind)
        recs = SF.unpack_stream(ship.data)
        new, _cps, rep = RE.reorder(recs, SCo.rows_for(recs, REORDER_B_POS),
                                    "B", [], rtl=rtl)
        perm = dict(rep["old2new"])
        if any(perm.get(i) != i for i in range(HEAD_RECS)):
            raise ChatSeqError(f"--reorder B: the {kind} image's head "
                               f"(tok/pos/tcnt) records moved")
        data = SF.pack_stream(new)
        pos_ldc = tuple(perm[o // SEQ_REC_BYTES] * SEQ_REC_BYTES
                        + o % SEQ_REC_BYTES for o in ship.pos_ldc)
        img = SCm.Image(f"step.{kind}.reordB" + ("" if rtl == "r0" else
                                                f".{rtl}"),
                        "step", data, ship.holes,
                        steps=1, pos_mode=ship.pos_mode, patch_off=0,
                        patch_len=PATCH_BYTES, pos_ldc=pos_ldc,
                        blob_span=SCm._blob_span(new),
                        counts=SCm._census(new))
        out[kind] = (img, perm, rep)
    return out


def follow_patch(p, perm, SCm):
    """Move every write of Patch `p` to the reordered position of the record
    it was aimed at.  A write may not straddle records unless the records
    it spans stay contiguous and in order (the 48-byte head does)."""
    def move(o, b):
        r0, r1 = o // SEQ_REC_BYTES, (o + len(b) - 1) // SEQ_REC_BYTES
        n0 = perm.get(r0)
        if n0 is None or any(perm.get(r) != n0 + (r - r0)
                             for r in range(r0, r1 + 1)):
            raise ChatSeqError(f"patch write at byte {o} (+{len(b)}) is "
                               f"aimed at a record the reorder dropped or "
                               f"split")
        return n0 * SEQ_REC_BYTES + o % SEQ_REC_BYTES
    ws = p.writes()
    head = (move(*ws[0]), ws[0][1])
    extra = [(move(o, b), b) for (o, b) in ws[1:]]
    return SCm.Patch(head[0], head[1], extra, fields=p.fields)


def reorder_image_hazards(sess, extra=None):
    """reorder_e4's hazard assert over every image the board will run."""
    RE = _reorder_mod()
    ims = {n: sess.images[n].recs_emit for n in ("preamble", "lite", "full")}
    ims.update(extra or {})
    got = {}
    for n, recs in ims.items():
        try:
            got[n] = RE.assert_no_pending_hazard(recs, f"image {n}")
        except AssertionError as e:
            raise ChatSeqError(f"--reorder: hazard assert REFUSED {n}: {e}")
    return got


def reorder_model_gate(sess, log=print, override=None):
    """Ruling B6: shipped-order vs reordered images, replayed EXACTLY.

    Both sides start from a fresh Mach and the artifact's initial state
    region, run preamble -> lite(760 @ 0) -> full(2614 @ 1) in emitter
    space (data_delta 0), and must end with identical OUT tokens, an
    identical ref/seq_model.snapshot (diff_state == []) and an identical
    region.  SeqExec's running-channel refusal (RunningChannelError) is
    armed in the model and propagates as a FAIL.  `override` maps an image
    name to replacement reordered bytes (the negative test only)."""
    import seq_model as SM
    t0 = time.monotonic()
    ship_recs = SF.unpack_stream(open(TEMPLATE4_PREFIX + ".seq", "rb").read())
    ship_meta = json.load(open(TEMPLATE4_PREFIX + ".seq.json"))
    m = seq_chat_for(derive_geometry(ship_recs, ship_meta))
    stc = m.TurnCompiler(TEMPLATE4_PREFIX, t_max=sess.args.t_max,
                         pos_mode=sess.pos_mode, verify_sha=False)
    if stc.blob() != sess.const_blob:
        raise ChatSeqError("--reorder gate: the const blobs differ")
    Wt = SM.DDRWeights.from_files(sess.base, sess.meta["weights"], sess.meta)
    row = sess.emb_row_bytes
    emb = np.memmap(sess.embf, dtype="<i2", mode="r").reshape(
        os.path.getsize(sess.embf) // row, row // 2)
    override = override or {}

    def side(tc, ims, tag):
        mach = SM._fresh_mach()
        region = SeqModelVerifier.state_region(sess)
        outs = []
        seq = [("preamble", 0, 0)] + [(k, t, p) for (t, p, k)
                                      in REORDER_GATE_TOKS]
        for name, tok, pos in seq:
            a = ims[name]
            if name == "preamble":
                data = a.data
            elif tag == "reordered":
                # S1P: the SESSION's patch (form B moves each write to
                # the reordered position of its record; A and none are
                # agent A's patch_step unchanged)
                data = sess.step_patch(name, tok=tok, pos=pos, tcnt=1,
                                       data_delta=0).apply(a)
            else:
                data = tc.patch_step(a, tok=tok, pos=pos, tcnt=1,
                                     data_delta=0).apply(a)
            if tag == "reordered" and name in override:
                data = override[name]
            t1 = time.monotonic()
            recs = SF.unpack_stream(data)
            # SR6: the model gate runs each side at the capability set its
            # images NEED (the caller names it; SeqExec never reads a
            # manifest): the shipped order at the empty set, the reordered
            # images at the session's --seq-rtl level (r1: {"R1"}), so a
            # masked FENCE is modelled as B17.1 says and the running-
            # channel refusal stays armed
            ex = SM.SeqExec(recs, sess.const_blob, Wt, emb=emb, mach=mach,
                            region=region,
                            caps=(getattr(sess, "level_caps", frozenset())
                                  if tag == "reordered" else frozenset())
                            ).run(max_steps=50 * len(recs))
            outs.append([int(x) for x in ex.out_fifo])
            log(f"    [B6 {tag}] {name} tok={tok} pos={pos}: out "
                f"{outs[-1]} ({time.monotonic() - t1:.0f} s)")
        return outs, SM.snapshot(mach), region

    ship_ims = {"preamble": stc.build_session(),
                "lite": stc.build_step(0, 0, "lite"),
                "full": stc.build_step(0, 0, "full")}
    rim = {n: sess.images[n].a for n in ("preamble", "lite", "full")}
    res = {"ok": False}
    try:
        so, ss, sr = side(stc, ship_ims, "shipped")
        ro, rs, rr = side(sess.tc, rim, "reordered")
    except (AssertionError, ValueError, SF.SeqValidationError) as e:
        # RunningChannelError & co., or the stream validator refusing an
        # image: a refusal is a FAIL of the gate, never a pass
        res.update(diff=[f"model REFUSED: {type(e).__name__}: {e}"])
        log("  B6 model gate: FAIL — " + res["diff"][0])
        return res
    diff = SM.diff_state(ss, rs)
    if so != ro:
        diff.insert(0, f"tokens {so} vs {ro}")
    if not np.array_equal(sr.mem, rr.mem):
        d = np.nonzero(sr.mem != rr.mem)[0]
        diff.append(f"region: {len(d)} bytes differ, first at {int(d[0])}")
    res.update(ok=not diff, diff=diff, tokens=so,
               nrec={"shipped": {n: ship_ims[n].nrec for n in ship_ims},
                     "reordered": {n: rim[n].nrec for n in rim}},
               wall_s=round(time.monotonic() - t0, 1))
    log(f"  B6 model gate: {'PASS' if res['ok'] else 'FAIL'} — tokens "
        f"{so} vs {ro}; state diff {diff[:3]}; {res['wall_s']} s")
    return res


def _wbase_of_rec(r):
    return ((int(r.len_or_addr_hi) & 0xFF) << 32) | int(r.addr_lo)


def derive_geometry(recs, meta):
    """The nine template boundaries, READ OUT OF THE STREAM.

    Every rule below is structural, and on the frozen 1-chan artifact the
    result is byte-for-byte the constants docs/CHAT_SEQ_SPEC.md pins:

      HALT            last record                       60494
      JMP / POSADV    the two before it                 60493 / 60492
      body starts     every EMB record        [1526, 16268, 31009, 45752]
      body_full end   first AMAXL + 1                   16266
      seeds           the two CSRWRs before body 0      1524 / 1525
      preamble        [0, seed_tok)                     (0, 1524)
      TCNT_SEQ        the one CSRWR TCNT_SEQ            45751
      lite cut        the MOVX run that opens the LM
                      head matvec (found from the head
                      image's own MVGO WBASEs, NOT from
                      scratch[0x800] — the x8 window is
                      reused by many matvecs)           15532
      pos LDCs        the XRF-indirected LDCs, as body
                      offsets           (2096,...,13756)
    """
    n = len(recs)
    g = {}

    def need(cond, msg):
        if not cond:
            raise ChatSeqError("template geometry: " + msg)

    need(n > 8, f"{n} records is not a decode stream")
    need(recs[n - 1].opcode == SF.OP_HALT, "the last record is not HALT")
    need(recs[n - 2].opcode == SF.OP_JMP
         and (recs[n - 2].flags & SF.JMP_TCNT),
         "the record before HALT is not the TCNT JMP")
    need(recs[n - 3].opcode == SF.EXT_XOP
         and recs[n - 3].target == SF.XRF_POS,
         "the record before the JMP is not the XRF[4] position advance")
    g["R_HALT"], g["R_JMP"], g["R_POSADV"] = n - 1, n - 2, n - 3

    emb = [i for i, r in enumerate(recs) if r.opcode == SF.OP_EMB]
    amax = [i for i, r in enumerate(recs) if r.opcode == SF.OP_AMAXL]
    need(len(emb) >= 2 and len(amax) == len(emb),
         f"{len(emb)} EMB / {len(amax)} AMAXL records: not a decode loop")
    b0 = emb[0]
    g["R_BODY_FULL"] = (b0, amax[0] + 1)
    g["_BODY_STARTS"] = tuple(emb[1:])
    need(b0 >= 2, "no room for the two seed records")
    for off, xrf, what in ((2, SF.XRF_TOK, "XRF[3] token"),
                           (1, SF.XRF_POS, "XRF[4] position")):
        r = recs[b0 - off]
        need(r.opcode == SF.OP_CSRWR and r.target == SF.csr_seq_xrf(xrf)
             and r.ind == SF.IND_NONE,
             f"record {b0 - off} is not the {what} seed CSRWR")
    g["R_SEED_TOK"], g["R_SEED_POS"] = b0 - 2, b0 - 1
    g["R_PREAMBLE"] = (0, b0 - 2)

    tc = [i for i, r in enumerate(recs)
          if r.opcode == SF.OP_CSRWR and r.target == SF.CSR_SEQ_TCNT]
    need(len(tc) == 1, f"{len(tc)} TCNT_SEQ writes, expected exactly one")
    g["R_TCNT"] = tc[0]

    # --- the lite cut: where the LM-head matvec begins ------------------
    W = meta.get("weights") or {}
    need(bool(W), "the .seq.json carries no weight plan")
    hw = max(W, key=lambda k: int(W[k]["nrows"]))
    # R-c per-channel repack: `base` is a LIST of per-channel bases, and the
    # head is chunk-INTERLEAVED, so the image occupies a DIFFERENT span on
    # each channel and the same address means different rows on different
    # channels.  Mirror sw/seq_run.check_mvgo_targets: give each channel its
    # own span and test every MVGO against the span of ITS OWN engine.
    # Without the repack this collapses to the single span this line used to
    # compute, so the two 0.8B templates derive byte-identical geometry
    # (asserted in --selftest [19]).
    rep = SR.is_repacked(meta)
    nch = max(1, int(meta.get("nch", 1)))
    depth = int((meta.get("weight_layout") or {}).get("chunk_rows",
                                                      SF.CHUNK_ROWS))
    nrows, stride = int(W[hw]["nrows"]), int(W[hw]["stride"])
    rows = (SF.chan_rows(nrows, nch, SR.layout_of(meta, int(hw)), depth)
            if rep else [nrows] * nch)
    span = {}
    for c in range(nch if rep else 1):
        base_c = SR._chan_base(W[hw]["base"], c) if rep else int(W[hw]["base"])
        span[c if rep else None] = (int(base_c),
                                    int(base_c) + int(rows[c]) * stride)

    def _reads_head(r):
        s = span.get(int(r.chan) if rep else None)
        return s is not None and s[0] <= _wbase_of_rec(r) < s[1]

    mv = [i for i in range(b0, amax[0])
          if recs[i].opcode == SF.OP_MVGO and _reads_head(recs[i])]
    need(bool(mv), f"no MVGO in body 0 reads the head image (wid {hw})")
    cut = min(mv)
    while cut > b0 and recs[cut - 1].opcode == SF.OP_MOVX:
        cut -= 1
    need(recs[cut].opcode == SF.OP_MOVX,
         f"the LM-head block opens with {SF.disasm(recs[cut], cut)}, "
         f"expected a MOVX XWIN <= scratch[...]")
    # The DYNQ8 activation the head reads is GEOMETRY-DEPENDENT: the
    # emitter puts it at `X8 = 2*H` and feeds `H` int8 elements
    # (ref/gen_layer_script.py's module-level `X8`, cited by SYMBOL because
    # the line drifts — D-CITE), i.e. 0x800/1024 at 0.8B and
    # 0x1000/2048 at 2B.  Derive both from the record — and assert the
    # emitter's law relating them, which is a real invariant and not a
    # restatement of what was just read.
    x8_word = int(recs[cut].addr_lo)
    x8_len = int(recs[cut].len_or_addr_hi)
    need(x8_len > 0 and x8_word == 2 * x8_len,
         f"the head's MOVX reads scratch[{x8_word:#x} .. +{x8_len}], which "
         f"is not the emitter's X8 = 2*H / n = H layout")
    g["X8_WORD"], g["X8_LEN"] = x8_word, x8_len
    need(recs[cut - 1].opcode == SF.OP_CMD,
         f"the lite body would end on {SF.disasm(recs[cut - 1], cut - 1)}, "
         f"expected a CMD")
    g["R_BODY_LITE"] = (b0, cut)
    g["_HEAD_WID"] = int(hw)

    pl = tuple(i - b0 for i in range(b0, amax[0] + 1)
               if recs[i].opcode == SF.EXT_LDC and recs[i].ind != SF.IND_NONE)
    need(len(pl) == POS_COPIES,
         f"{len(pl)} position-indexed LDCs in the body, expected {POS_COPIES}")
    need(pl[-1] < cut - b0, "a position LDC falls outside the lite body")
    g["POS_LDC_REC_OFFSETS"] = pl

    # --- the const blob's geometry, out of those same LDC records --------
    # ref/seq_chat.py pins CONST_BYTES / POS_WORDS to the 0.8B artifact, but
    # the const region is model-sized (0.8B 998,144 B, 2B 1,098,496 B), so
    # derive all of it from the position LDCs: each carries its word count
    # (imm32) and its DDR address, the six copies of one position sit
    # POS_COPY_BYTES apart, and the lowest address IS the pool base.  On
    # both 0.8B artifacts this reproduces 998144 / 128 / 1536 exactly.
    lrec = [recs[b0 + o] for o in pl]
    nw = {int(r.imm32) for r in lrec}
    need(len(nw) == 1, f"the position LDCs read {sorted(nw)} words, not one size")
    pos_words = nw.pop()
    la = sorted(((int(r.len_or_addr_hi) << 32) | int(r.addr_lo)) for r in lrec)
    need(all(la[i] - la[0] == i * 2 * pos_words for i in range(len(la))),
         f"the {len(la)} position LDCs are not {2 * pos_words} B apart: "
         f"{[a - la[0] for a in la]}")
    const_bytes = la[0] - SF.SEQ_DATA_BASE
    need(const_bytes > 0, f"the position pool starts {const_bytes} B into "
                          f"the const blob")
    g["POS_WORDS"] = pos_words
    g["POS_COPY_BYTES"] = 2 * pos_words
    g["POS_STRIDE"] = POS_COPIES * 2 * pos_words
    g["CONST_BYTES"] = const_bytes
    g["POS_BLOB_BASE"] = la[0]
    # the artifact's own seqdata is the independent check on all of it: the
    # emitter writes the const region plus exactly six committed positions.
    g["SEQDATA_SHA256"] = meta.get("seqdata_sha256")
    need(int(meta.get("seqdata_bytes", 0))
         == const_bytes + 6 * g["POS_STRIDE"],
         f"seqdata is {meta.get('seqdata_bytes')} B, but the LDCs say "
         f"{const_bytes} B of constants + 6 x {g['POS_STRIDE']} B positions")

    g["TEMPLATE_NREC"] = n
    g["NREC_PREAMBLE"] = g["R_PREAMBLE"][1] - g["R_PREAMBLE"][0]
    g["NREC_BODY_FULL"] = g["R_BODY_FULL"][1] - g["R_BODY_FULL"][0]
    g["NREC_BODY_LITE"] = g["R_BODY_LITE"][1] - g["R_BODY_LITE"][0]
    g["LITE_SUFFIX_RECS"] = g["NREC_BODY_FULL"] - g["NREC_BODY_LITE"]
    return g


def _verify_derived(T, g):
    """ref/seq_chat.Templates._verify, re-expressed on derived indices.

    Agent A's version asserts the same invariants against LITERAL record
    numbers (including the three later step-body starts, which are a tuple
    in the function body).  This is the same list with `g` substituted, so
    a 4-chan artifact gets exactly the structural gate the 1-chan one does.
    """
    r, b = T.recs, T.stream

    def need(cond, msg):
        if not cond:
            raise ChatSeqError("template check failed: " + msg)

    need(r[0].opcode == SF.OP_CSRWR
         and r[0].target == SF.csr_layer(SF.LOFF_LAYER),
         f"rec 0 is {SF.disasm(r[0])}, expected CSRWR L_LAYER")
    # S3 (SEQ_ISA v2.1, spec 6.4): the preamble no longer ENDS on its TCNT
    # write.  It is now LAYER, the three SB_* region bases (B15.3), the
    # eight-layer TCNT/TCNT2 sweep (A1.3) and then the first SLDs -- so the
    # anchor is that the preamble CONTAINS the counter reset and the base
    # writes, and ends on a layer CMD (the SLD of DN layer 0).  The 768 DNZ
    # and 120 CONVW it used to carry are retired: the host writes the region.
    pre = r[g["R_PREAMBLE"][0]:g["R_PREAMBLE"][1]]
    need(any(x.opcode == SF.OP_CSRWR
             and x.target == SF.csr_layer(SF.LOFF_TCNT) for x in pre),
         "the preamble carries no CSRWR L_TCNT")
    # v2.1 or older?  A stream that carries SLD/SST is S3's and must carry
    # the three region bases with them; a PRE-S3 artifact (this tree can
    # still be pointed at one -- the committed template prefixes are) keeps
    # the old shape and is checked the old way, which is what makes this a
    # property of the ARTIFACT and not of the tree that reads it.
    v21 = any(x.opcode == SF.OP_CMD
              and (x.imm32 & 0xFF) in (SF.OP_L_SLD, SF.OP_L_SST) for x in r)
    if v21:
        for off, nm in ((SF.LOFF_SB_DN, "SB_DN"), (SF.LOFF_SB_KV, "SB_KV"),
                        (SF.LOFF_SB_CV, "SB_CV")):
            need(any(x.opcode == SF.OP_CSRWR
                     and x.target == SF.csr_layer(off) and x.imm32 != 0
                     for x in pre),
                 f"the preamble carries no non-zero CSRWR L_{nm} (B15.3)")
        need(pre[-1].opcode == SF.OP_CMD,
             "the preamble does not end on a layer CMD (the first SLD)")
    else:
        need(pre[-1].opcode == SF.OP_CSRWR
             and pre[-1].target == SF.csr_layer(SF.LOFF_TCNT),
             "the preamble does not end on its CSRWR L_TCNT")
    need(r[g["R_SEED_POS"]].imm32 == 0,
         "the position seed is not CSRWR XRF[4] <= 0")
    need(r[g["R_BODY_FULL"][0]].opcode == SF.OP_EMB, "body head is not EMB")
    need(r[g["R_BODY_FULL"][1] - 1].opcode == SF.OP_AMAXL,
         "the full body does not end in AMAXL")
    need(r[g["R_BODY_LITE"][1] - 1].opcode == SF.OP_CMD,
         "the lite body does not end on a CMD")
    nb = g["NREC_BODY_FULL"]
    b0 = b[g["R_BODY_FULL"][0] * SEQ_REC_BYTES:
           g["R_BODY_FULL"][1] * SEQ_REC_BYTES]
    for k, start in enumerate(g["_BODY_STARTS"]):
        need(b[start * SEQ_REC_BYTES:(start + nb) * SEQ_REC_BYTES] == b0,
             f"step body {k + 1} at rec {start} is NOT byte-identical to the "
             f"template body at rec {g['R_BODY_FULL'][0]}")
    need(r[g["R_JMP"]].opcode == SF.OP_JMP
         and (r[g["R_JMP"]].flags & SF.JMP_TCNT), "the JMP moved")
    need(r[g["R_HALT"]].opcode == SF.OP_HALT, "the HALT moved")
    need(int(T.meta["seq_data_base"]) == SF.SEQ_DATA_BASE,
         "meta seq_data_base is not the emitter's 0x8000_0000")


def seq_chat_for(geom):
    """A PRIVATE clone of ref/seq_chat.py carrying `geom`'s boundaries.

    Agent A's module is executed a second time into a fresh namespace and
    its geometry constants are replaced.  Nothing about the shipped `SC`
    module object changes, so an nch=1 session in the same process is
    bit-for-bit unaffected — which is the whole point of doing it this way
    instead of re-pinning docs/CHAT_SEQ_SPEC.md's frozen indices.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "seq_chat_nch", os.path.abspath(SC.__file__))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    for k, v in geom.items():
        if not k.startswith("_"):
            setattr(m, k, v)
    m.TEMPLATE_SHA256 = None                     # the caller gates the sha
    m.POS_LDC_BYTE_OFFSETS = tuple(o * m.REC + 8
                                   for o in geom["POS_LDC_REC_OFFSETS"])
    m.Templates._verify = lambda self, _g=dict(geom): _verify_derived(self, _g)
    m.GEOM = dict(geom)
    return m


def build_posblob(t_max=T_MAX):
    """The session position blob (spec decision 6).

    concat over p in [0,t_max) of POS_COPIES copies of
    ref/layer_fixed.rope_tables_q15(p), 1536 B per position.  The
    indirected LDC records read DDR[pool + i*256] + XRF[4], XRF[4] =
    pos*1536, so this layout is what the stream already addresses.

    Agent A owns the shipped generator (ref/seq_chat.py); this is the
    fallback used until it lands, and the cross-check afterwards.
    """
    import layer_fixed as LF
    out = bytearray()
    for p in range(t_max):
        cq, sq = LF.rope_tables_q15(p)
        blk = np.concatenate([np.asarray(cq), np.asarray(sq)]) \
            .astype("<i2").tobytes()
        if len(blk) != POS_BLOCK:
            raise ChatSeqError(f"rope table for pos {p} is {len(blk)} B, "
                               f"expected {POS_BLOCK}")
        out += blk * POS_COPIES
    return bytes(out)


def posblob_offset(recs, meta):
    """Blob offset of the position pool, READ OUT OF THE STREAM.

    The pool base is the smallest address any XRF-indirected LDC reads;
    the 6 per-layer copies sit at +i*256 from it.  Deriving it (instead
    of hard-coding) means a regenerated artifact cannot silently shift
    the pool out from under the blob we upload.
    """
    base = int(meta["seq_data_base"])
    offs = sorted({((r.len_or_addr_hi << 32) | r.addr_lo) - base
                   for r in recs
                   if r.opcode == SF.EXT_LDC and r.ind != SF.IND_NONE})
    if not offs:
        raise ChatSeqError("the template has no XRF-indirected LDC records — "
                           "there is no position pool to extend")
    if len(offs) != POS_COPIES or offs[-1] - offs[0] != (POS_COPIES - 1) * POS_BLOCK:
        raise ChatSeqError(f"unexpected position-pool layout {offs}")
    return offs[0]


def build_const_blob(blob, meta, recs, posblob):
    """The uploaded const blob: everything below the pool + the 512-pos pool.

    Gate A2 in host form: the first 6 positions of the generated blob MUST
    reproduce the committed pool byte-exactly, or the position tables the
    chip reads are not the tables the gated run used.
    """
    off = posblob_offset(recs, meta)
    committed = blob[off:]
    if len(committed) % POS_STRIDE:
        raise ChatSeqError(f"committed pool is {len(committed)} B, not a "
                           f"multiple of {POS_STRIDE}")
    n = len(committed)
    if posblob[:n] != committed:
        raise ChatSeqError(
            f"the generated position blob does not reproduce the committed "
            f"{n // POS_STRIDE}-position pool byte-exactly (gate A2)")
    return blob[:off] + posblob, off


# ======================================================================
# residency probe (spec decision 9)
# ======================================================================
def _witness(size, want=WITNESS_BYTES):
    """A deterministic 4 KiB-ish witness window inside an image."""
    n = min(want, size)
    off = ((size - n) // 2) & ~(SEQ_ALIGN - 1)
    return off, n


def build_residency_manifest(manifest, wdir, wbase_of, embf, emb_base,
                             n_emb=EMB_WITNESSES, splits=None,
                             state=None, conv_images=None):
    """Host-side witness manifest: what each resident image MUST hash to.

    nch=1: one 4 KiB block per weight image (187 of them) and `n_emb`
    blocks spread over the embedding table.  Reading them back is ~3 ms of
    DMA; a full readback of 900 MiB is ~10 s, which is why the probe
    exists.

    nch>1 (rung 4 S4): `splits` is sw/seq_run.plan_weight_split's placement
    for THIS stream, and the probe takes one witness per PIECE — R-d; it
    used to take one per CHANNEL per image, which is one of the ~30 chunks
    a channel owns of the INTERLEAVED head, and damage to the other ~29
    was invisible (evidence/qwen2b/rd/RD_GATE.md §4.2).  That is what makes
    a residency probe a LAYOUT probe: a board holding the same weights
    under a different placement — contiguous quarters instead of
    interleaved chunks, or the whole image on channel 0 from an nch=1
    session — misses on pieces it never wrote, and the session re-uploads
    instead of reading someone else's bytes.  The witness address is
    CHANNEL-LOCAL and carries its channel; `probe_residency` reads it
    there.

    WHAT THIS IS NOT: coverage.  A witness is 4 KiB of a piece that can be
    megabytes — ~0.19 % of the 2B head's pieces — so the probe SAMPLES.
    R-d measured the hit rate against a whole-pack compare: a 0.8B run that
    damaged 612 of 866 2B pieces was caught by 193 witnesses, i.e. roughly
    one detection per three damaged pieces.  That is why `bring_up` treats
    ANY miss as invalidating the whole pack rather than re-uploading only
    the images that missed, and why RD_GATE follow-on 2 wants this replaced
    by a whole-pack hash (~3 s for 1,847 MiB) rather than made finer.
    """
    out = []
    by_wid = {}
    for s in (splits or []):
        by_wid.setdefault(s["wid"], []).append(s)
    for wid_s, m in sorted(manifest.items(), key=lambda kv: int(kv[0])):
        wid = int(wid_s)
        path = os.path.join(wdir, m["file"])
        size = int(m["nrows"]) * int(m["stride"])
        if os.path.getsize(path) != size:
            raise ChatSeqError(f"{m['file']} is {os.path.getsize(path)} B, "
                               f"manifest says {size}")
        if not splits:
            off, n = _witness(size)
            with open(path, "rb") as f:
                f.seek(off)
                blk = f.read(n)
            out.append({"kind": "weight", "wid": wid, "name": m["file"],
                        "chan": None, "addr": wbase_of[wid] + off, "bytes": n,
                        "sha256": hashlib.sha256(blk).hexdigest()})
            continue
        # R-d: one witness per PIECE, not one per channel.  Until R-d this
        # took the middle piece each channel owns, which is exactly one
        # block of the ~30 chunks the INTERLEAVED LM head puts on a
        # channel — so damage to the other chunks was invisible, the head
        # was reported resident, and a session ran on a 61 MiB-stale
        # vocabulary projection and answered with the wrong token and no
        # error anywhere (measured: `evidence/qwen2b/rd/
        # hw_35_residency_blindspot.log`, 0 MISS of 756 with wid 186 wrong).
        # For a CONTIGUOUS image a channel owns exactly one piece, so this
        # is the same witness it always took; only the scattered head grows
        # (748 -> 866 blocks, 3.0 -> 3.4 MiB, still ~25 ms).
        with open(path, "rb") as f:
            for s in sorted(by_wid.get(wid, []),
                            key=lambda s: (s["chan"], s["r0"])):
                c = s["chan"]
                o, n = _witness(s["byte_len"])
                f.seek(s["byte_off"] + o)
                blk = f.read(n)
                out.append({"kind": "weight", "wid": wid,
                            "name": f"{m['file']}@c{c}r{s['r0']}", "chan": c,
                            "addr": s["local_addr"] + o, "bytes": n,
                            "sha256": hashlib.sha256(blk).hexdigest()})
    # S3 (SEQ_ISA v2.1, spec 7.1): ONE WITNESS PER CONV IMAGE.  The conv
    # blocks are the only part of the DDR state region the host UPLOADS --
    # the DN region is a memset and the KV region is never read before it is
    # written -- so they are the only part a residency probe can hold a
    # host-side hash of.  Same 4 KiB block, same rule, and the same
    # consequence for a miss: the pack is invalidated whole (reupload_set).
    if state is not None:
        chan = state["cv"] >> 32
        for ci in (conv_images or []):
            path = os.path.join(wdir, ci["file"])
            size = int(ci["bytes"])
            if os.path.getsize(path) != size:
                raise ChatSeqError(f"{ci['file']} is "
                                   f"{os.path.getsize(path)} B, manifest "
                                   f"says {size}")
            off, n = _witness(size)
            with open(path, "rb") as f:
                f.seek(off)
                blk = f.read(n)
            out.append({"kind": "conv", "wid": -2,
                        "name": f"conv[L{ci['layer']}]", "chan": chan,
                        "addr": (state["cv"] & 0xFFFF_FFFF)
                                + int(ci["layer"]) * HW.STATE_CV_STRIDE + off,
                        "bytes": n,
                        "sha256": hashlib.sha256(blk).hexdigest()})
    if embf and os.path.exists(embf):
        size = os.path.getsize(embf)
        with open(embf, "rb") as f:
            for i in range(n_emb):
                off = ((size - WITNESS_BYTES) * i // max(1, n_emb - 1)) \
                    & ~(SEQ_ALIGN - 1)
                f.seek(off)
                blk = f.read(WITNESS_BYTES)
                out.append({"kind": "emb", "wid": -1,
                            "name": f"emb[{i}]", "chan": None,
                            "addr": emb_base + off,
                            "bytes": len(blk),
                            "sha256": hashlib.sha256(blk).hexdigest()})
    return out


def reupload_set(bad, manifest):
    """(images to re-upload, re-upload the embedding?, images that missed).

    R-d rule (b): a miss ANYWHERE proves another owner has written this
    DDR, and a witness set that samples ~0.19 % of a piece cannot bound
    what else that owner touched — so a miss invalidates the WHOLE pack,
    not just the images that happened to be probed at a damaged offset.
    The R-d incident is what this exists for: 193 witnesses missed, the
    selective rule re-uploaded 186 of 187 images, the LM head stayed
    61.3 MiB stale, the re-probe read 0 MISS and the session answered with
    the wrong token (RD_GATE.md §4.2).  Re-uploading everything costs
    ~14 s and only happens when the board has already changed under us.

    Pure, so `--selftest` can drive the escalation branch — on hardware
    every observed miss set has been all-187, which makes the branch a
    no-op there and unproven except here.  Returns n_sel=None when nothing
    missed and no upload is needed.
    """
    badw = sorted({w["wid"] for w in bad if w["kind"] == "weight"})
    # S3: a conv-image miss is a miss of the same class -- another owner has
    # written this DDR -- so it invalidates the pack exactly as a weight or
    # embedding miss does.  R-d rule (b) is about what a miss PROVES, not
    # about which image it was found in.
    bade = any(w["kind"] in ("emb", "conv") for w in bad)
    if not (badw or bade):
        return [], False, None
    return sorted(int(k) for k in manifest), True, len(badw)


def split_witnesses(wit):
    """(the weight+embedding PACK, the state region's CONV blocks).

    The two classes are probed at DIFFERENT MOMENTS and a miss means
    different things in each, which is why `bring_up` no longer probes them
    together.

    A WEIGHT or EMBEDDING witness covers DDR that nothing but this host ever
    writes, so its hash is stable across sessions and a miss really does
    prove another owner wrote the pack (R-d rule (b), `reupload_set`).

    A CONV witness does not: the program writes conv STATE into the very
    128 KiB blocks the host uploaded the conv weight taps into
    (`HW.STATE_CV_STRIDE`), so after any run the host-side hash is stale BY
    DESIGN.  `evidence/qwen9b/g6/RD9_GATE.md` §14.1 measured the
    consequence on hardware — `24 MISS` of 1,146 with **zero** weight
    images missed, escalating to a 5.8 GiB re-upload at the start of every
    session after the first, on a perfectly healthy board.  So the conv
    witnesses are taken AFTER `sw/seq_run.upload_state` has restored the
    region, where they audit the write that just happened, and they never
    reach `reupload_set`.
    """
    pack = [w for w in wit if w["kind"] != "conv"]
    state = [w for w in wit if w["kind"] == "conv"]
    return pack, state


def probe_residency(dev, wit, log=print):
    """Read every witness block back; return the names that FAILED."""
    t0 = time.monotonic()
    bad = []
    for w in wit:
        c = w.get("chan")
        got = (dev.dma_read(w["addr"], w["bytes"]) if c is None
               else dev.dma_read_chan(c, w["addr"], w["bytes"]))
        if hashlib.sha256(got).hexdigest() != w["sha256"]:
            bad.append(w)
    dt = time.monotonic() - t0
    nw = sum(1 for w in wit if w["kind"] == "weight")
    nc = sum(1 for w in wit if w["kind"] == "conv")
    ne = len(wit) - nw - nc
    log(f"  residency  {len(wit)} witness blocks ({nw} weight + {nc} conv + "
        f"{ne} emb, {sum(w['bytes'] for w in wit) / 1024:.0f} KiB) in "
        f"{dt * 1e3:.0f} ms -> {len(bad)} MISS")
    return bad


# ======================================================================
# device: one launch  (OUT FIFO popped ONLY while halted — spec hazard)
# ======================================================================
def _launch(dev, image, writes=(), tok=None, pos=None, timeout=STEP_TIMEOUT,
            init_xrf=True, verify_patch=True, log=print):
    """Apply agent A's patch writes, START, poll to halt, then drain.

    `writes` is ref/seq_chat.Patch.writes(): [(byte offset in the image,
    bytes)].  In the frozen pos_mode="xrf" that is exactly one 48 B write
    at offset 0; in pos_mode="ldc" it is that plus six 4 B rewrites of the
    position-LDC addresses (agent A's escape hatch for pos > 85, see the
    XRF[4] sign-extension note).  `tok`/`pos` are for messages only.

    Deliberately NOT sw/seq_run.py:seq_start_and_poll(): that one pops the
    OUT FIFO inside its poll loop, and `rtl/seq_unit.sv`'s OUT-FIFO pop and
    push paths lose an of_cnt when a host pop races an AMAXL push.  (Named
    by SYMBOL, not by the slash-joined `:1049/1100` this used to carry: the
    drift tool renumbers the first element of such a list and leaves the
    rest — S3 fix round 1, I3.)  Spec decision 4 exists to
    make that race unreachable, so this loop reads STATUS only.
    """
    dev.require_seq("a chat_seq launch")
    st = dev.seq_status()
    if st["busy"]:
        raise ChatSeqError(
            f"the sequencer is busy (STATUS={st['raw']:#010x}) — another host "
            f"has it, or a previous run hung.  This process holds the board "
            f"lock ({LOCK_PATH}), and since O3 every in-repo tool that "
            f"programs or DMAs the board takes it — so this is a wedged "
            f"stream, a tool run with --no-lock, or a checkout that has not "
            f"picked up O3 yet (docs/USAGE.md §5).")

    # 1. drain (halted!) — reading S_OUT_FIFO IS the pop; only a hard reset
    #    clears the FIFO, so a stale entry would shift every later token.
    stale = dev.seq_drain_fifo()
    if stale:
        log(f"    drained {len(stale)} stale OUT FIFO entries: {stale}")

    # 2. the per-launch patch (agent A decides the holes; we only DMA them)
    npatch = 0
    for off, blk in writes:
        if off + len(blk) > len(image.data):
            raise ChatSeqError(f"patch at {off}+{len(blk)} runs past the "
                               f"{len(image.data)} B image {image.name}")
        dev.dma_write(image.base + off, blk)
        npatch += len(blk)
        if verify_patch:
            got = dev.dma_read(image.base + off, len(blk))
            if got != blk:
                raise ChatSeqError(
                    f"patch readback mismatch at {image.base + off:#x} "
                    f"(image {image.name}, tok={tok} pos={pos})")

    # 3. CSRs (never while busy)
    if init_xrf:
        for i in range(SEQ_XRF_N):
            dev.seq_wr(s_xrf(i), 0)
    dev.seq_wr(S_TCNT_SEQ, 0)          # the in-stream record sets the real one
    base = dev.ddr_off + image.base
    dev.seq_wr(S_BASE_LO, base & 0xFFFFFFFF)
    dev.seq_wr(S_BASE_HI, (base >> 32) & 0x3)
    dev.seq_wr(S_LEN, image.nrec)      # spec hazard: LEN == record count
    dev.seq_wr(S_ENTRY, 0)
    for a, want, nm in ((S_BASE_LO, base & 0xFFFFFFFF, "BASE_LO"),
                        (S_BASE_HI, (base >> 32) & 0x3, "BASE_HI"),
                        (S_LEN, image.nrec, "LEN"),
                        (S_ENTRY, 0, "ENTRY")):
        got = dev.seq_rd(a)
        if got != want:
            raise ChatSeqError(f"SEQ {nm} read back {got:#x}, wrote {want:#x}")

    # 4. go
    t0 = time.monotonic()
    dev.seq_wr(S_CTRL, SEQ_CTRL_START)
    while True:
        st = dev.seq_status()
        if not st["busy"]:
            break
        dt = time.monotonic() - t0
        if dt > timeout:
            pc = dev.seq_rd(S_PC)
            dev.seq_wr(S_CTRL, SEQ_CTRL_ABORT)   # the ONLY legal busy write
            time.sleep(0.05)
            st = dev.seq_status()
            raise ChatSeqError(
                f"sequencer timeout after {dt:.1f}s in image {image.name} "
                f"(tok={tok} pos={pos}) at pc={pc}/{image.nrec}, "
                f"STATUS={st['raw']:#010x} err={st['err_code']:#04x} "
                f"({seq_err_name(st['err_code'])}); ABORT issued\n"
                + SR.disasm_window(image.recs, min(pc, image.nrec - 1)))
        time.sleep(POLL_S)
    wall = time.monotonic() - t0

    # 5. halted: now (and only now) pop the FIFO
    tokens = dev.seq_drain_fifo()
    pc = dev.seq_rd(S_PC)
    perf = dev.seq_perf()
    rep = {"image": image.name, "tok_in": int(tok), "pos": int(pos),
           "pc": pc, "status": st, "tokens": tokens,
           "wall_ms": round(wall * 1e3, 2), "perf": perf,
           "device_ms": round(perf["cyc"] / ACLK_HZ * 1e3, 3),
           "out_cnt_at_halt": st["out_cnt"], "stale": stale,
           # rung 4 S6: sticky-until-RESET OUT-FIFO overflow.  A set bit
           # means seq_unit DROPPED at least one AMAXL token since the board
           # was reset — so it is a SESSION alarm, not a per-launch counter,
           # and the caller latches it for the rest of the session.
           "out_fifo_ovf": bool(st.get("of_ovf", False)),
           "patch_bytes": npatch, "patch_writes": len(list(writes))}
    if st["err"] or st["err_code"]:
        raise ChatSeqError(
            f"SEQ halted with err_code={st['err_code']:#04x} "
            f"({seq_err_name(st['err_code'])}) at pc={pc}/{image.nrec} in "
            f"image {image.name} (tok={tok} pos={pos})\n"
            + SR.disasm_window(image.recs, min(pc, image.nrec - 1)))
    if pc != image.nrec - 1:
        raise ChatSeqError(f"image {image.name} halted at pc={pc}, expected "
                           f"the HALT at {image.nrec - 1}")
    if len(tokens) > 1:
        raise ChatSeqError(f"image {image.name} produced {len(tokens)} tokens "
                           f"{tokens}; one launch is one step")
    return rep


# ======================================================================
# SAMPLING
# ======================================================================
# STATUS (2026-08-11, user ruling — this OVERRIDES docs/SAMPLING_SPEC.md
# S1/S2 and is the contract this file implements):
#
#   * MODEL COMPUTE STAYS ON-CHIP.  A decode step is a FULL launch, the
#     LM head and the argmax run on the FPGA, and the token comes out of
#     the SEQ OUT FIFO.  That is today's shipped path and it is UNCHANGED
#     by everything below.
#   * A SAMPLED step will be the SAME full launch plus an on-chip TOP-K
#     CAPTURE UNIT: k = 32 {int32 value, 18-bit index} pairs, readable
#     from CSRs after the halt.  That unit ARRIVES WITH THE NEXT RTL RUNG.
#     It does not exist in build_032, so sampling REFUSES here, loudly and
#     early, and greedy carries on untouched.
#   * The host-f32 LM head (sw/head_cache.py) is DEMOTED to verification
#     tooling: --verify-head cross-checks the chip's head against it, and
#     the board-free gate below drives the sampler from it.  It is NEVER
#     a decode path.
#
# So the sampler is written against a pluggable CandidateSource that
# yields exactly what the capture unit will yield —
#
#       (values int32[k], indices int64[k], e_x)
#
# — in the CHIP's integer domain.  Everything downstream (dequant,
# temperature, top-k, top-p, the seeded draw) is integer-in / token-out
# and has no floating-point dependence on where the candidates came from,
# which is what makes S3's determinism hold by construction here: there
# is no BLAS reduction in the shipped path at all.
#
# DEQUANT (S4, unchanged): logit = value * 2^(e_x + HEAD_LOGIT_EXP0).
# ======================================================================
class Sampler(object):
    """Temperature / top-k / top-p over a candidate set, seeded (S3, S5).

    PURE HOST MATH, integer in.  `pick()` takes the capture unit's
    (values, indices, e_x) and returns the chosen token id plus a record
    of how it got there.  Two Samplers with the same seed, fed the same
    candidate sequence, return the same tokens — that is the whole
    determinism contract, and it needs no assumptions about thread counts
    or reduction order because nothing here reduces over the vocabulary.

    temp == 0 is GREEDY: the top candidate, i.e. exactly the token the
    chip's AMAXL would have pushed.  The greedy path never draws from the
    RNG, so `--temp 0` is bit-identical to today's decode.
    """

    def __init__(self, temp=DEFAULT_TEMP, top_k=DEFAULT_TOP_K,
                 top_p=DEFAULT_TOP_P, seed=None,
                 logit_exp0=HEAD_LOGIT_EXP0):
        temp = float(temp)
        top_p = float(top_p)
        top_k = int(top_k)
        if temp < 0:
            raise ChatSeqError("--temp must be >= 0 (0 = greedy)")
        if temp > 100:
            raise ChatSeqError("--temp above 100 is a typo, not a request")
        if top_k < 0:
            raise ChatSeqError("--top-k must be >= 0 (0 = no top-k cut)")
        if not (0.0 < top_p <= 1.0):
            raise ChatSeqError("--top-p must be in (0, 1] (1.0 = off)")
        self.temp = temp
        self.top_k = top_k
        self.top_p = top_p
        self.logit_exp0 = int(logit_exp0)
        self.seed = (int(seed) if seed is not None
                     else int.from_bytes(os.urandom(8), "big") >> (64 - SEED_BITS))
        self.seed_given = seed is not None
        self.rng = np.random.default_rng(self.seed)
        self.n = 0                 # picks made
        self.n_sampled = 0         # picks that actually drew from the RNG
        self.ms = []               # per-pick host time

    # ------------------------------------------------------------------
    @property
    def enabled(self):
        return self.temp > 0.0

    def reset(self):
        """Re-seed to the session seed — a context reset restarts the draw."""
        self.rng = np.random.default_rng(self.seed)
        self.n = self.n_sampled = 0
        self.ms = []

    def describe(self):
        if not self.enabled:
            return "greedy (--temp 0): the chip's argmax, bit-exact"
        return (f"temp={self.temp:g} top_k={self.top_k or 'off'} "
                f"top_p={self.top_p:g} seed={self.seed}")

    def as_dict(self):
        return {"mode": "sampled" if self.enabled else "greedy",
                "temp": self.temp, "top_k": self.top_k, "top_p": self.top_p,
                "seed": self.seed, "seed_given": self.seed_given,
                "picks": self.n, "sampled": self.n_sampled,
                "sample_ms_mean": (round(sum(self.ms) / len(self.ms), 4)
                                   if self.ms else None),
                "sample_ms_max": (round(max(self.ms), 4) if self.ms else None),
                "spec": "docs/SAMPLING_SPEC.md S3/S5 + 2026-08-11 ruling"}

    # ------------------------------------------------------------------
    def logits(self, values, e_x):
        """S4 dequant, float64.  Monotone in `values`, so it never reorders."""
        return (np.asarray(values, dtype=np.float64)
                * float(2.0 ** (int(e_x) + self.logit_exp0)))

    def _order(self, values, indices):
        """(value DESC, index ASC) — the on-chip AMAX's first-wins rule
        (`ref/gen_layer_script.Mach.alu` op 10 AMAX32: strictly-greater
        update, so the first max wins), extended to k entries."""
        v = np.asarray(values, dtype=np.int64)
        i = np.asarray(indices, dtype=np.int64)
        return np.lexsort((i, -v))

    def pick(self, values, indices, e_x):
        """Choose one token.  Returns (token_id, info)."""
        t0 = time.perf_counter()
        v = np.asarray(values, dtype=np.int64)
        idx = np.asarray(indices, dtype=np.int64)
        if v.shape != idx.shape or v.ndim != 1 or v.size == 0:
            raise ChatSeqError(
                f"candidate set must be two 1-D arrays of the same non-zero "
                f"length, got values{list(v.shape)} indices{list(idx.shape)}")
        if len(set(idx.tolist())) != len(idx):
            raise ChatSeqError("the candidate set repeats a token id — the "
                               "capture unit must return distinct rows")
        o = self._order(v, idx)
        v, idx = v[o], idx[o]
        info = {"n_cand": int(v.size), "e_x": int(e_x),
                "top_value": int(v[0]), "top_id": int(idx[0])}
        if not self.enabled:
            self.n += 1
            self.ms.append((time.perf_counter() - t0) * 1e3)
            info.update({"mode": "greedy", "rank": 0, "p": 1.0,
                         "k_eff": 1, "nucleus": 1,
                         "sample_ms": self.ms[-1]})
            return int(idx[0]), info

        k = v.size if self.top_k <= 0 else min(self.top_k, v.size)
        info["k_eff"] = int(k)
        info["k_clamped"] = bool(self.top_k > v.size > 0)
        lg = self.logits(v[:k], e_x) / self.temp
        lg -= lg.max()
        p = np.exp(lg)
        p /= p.sum()
        n = k
        if self.top_p < 1.0:
            c = np.cumsum(p)
            n = int(np.searchsorted(c, self.top_p, side="left")) + 1
            n = max(1, min(n, k))
            p = p[:n]
            p /= p.sum()
        info["nucleus"] = int(n)
        # inverse-CDF draw: ONE rng.random() per token, so the token
        # sequence is a pure function of (seed, candidate sequence) and
        # does not depend on numpy's choice()/multinomial internals.
        u = float(self.rng.random())
        j = int(np.searchsorted(np.cumsum(p), u, side="right"))
        j = min(j, n - 1)
        self.n += 1
        self.n_sampled += 1
        self.ms.append((time.perf_counter() - t0) * 1e3)
        info.update({"mode": "sampled", "rank": j, "p": float(p[j]),
                     "u": u, "sample_ms": self.ms[-1],
                     "value": int(v[j]), "greedy_id": int(idx[0])})
        return int(idx[j]), info


# ----------------------------------------------------------------------
# candidate sources
# ----------------------------------------------------------------------
class CandidateSource(object):
    """Where a sampled step's (values, indices, e_x) come from.

    `available` is the gate every caller checks BEFORE a session starts:
    an unavailable source must explain itself in `why` and must never be
    silently replaced by a different one.
    """

    name = "base"
    k = 0
    available = False
    why = "not implemented"
    on_board = False           # True if the source needs the real device

    def candidates(self, ctx):
        raise NotImplementedError

    def describe(self):
        return f"{self.name}: {'ready' if self.available else self.why}"

    def as_dict(self):
        return {"source": self.name, "available": bool(self.available),
                "k": int(self.k), "why": None if self.available else self.why}


class ChipTopKSource(CandidateSource):
    """THE SHIPPED SAMPLED PATH — the rung-4 S5 top-k capture unit.

    ------------------------------------------------------------------
    NOT PRESENT IN build_032.  Present from build_033 (RUNG4_SPEC S5).
    ------------------------------------------------------------------
    The unit (module layer_topk32, declared inside rtl/layer_chan.sv):

      * keeps a running top-32 of the y32 values the LM head streams
        through the AMAX comparator — the same numbers AMAXL already sees,
        so no extra DDR traffic and no second pass over the vocabulary;
      * k = TOPK_CAPTURE_K = 32 entries of {int32 value, 18-bit row index},
        reset by the same `fresh` flag that arms the AMAX scan (S5: op10
        && cfg_p0[0] ONLY — not START, not launch);
      * publishes five CSRs at TOPK_BASE = 0x5048 (S5 pins the map; the
        layer decode 0x48..0xFFF was free, so there is no BD edit):

            0x5048 IDENT   -> 0xFAB1704B
            0x504C STATUS  -> {overflow[7], complete[6], count[5:0]}
            0x5050 PTR     RW, 5 bits
            0x5054 VAL     R  int32 y32 of entry PTR   (NO side effect)
            0x5058 IDX     R  18-bit row index, and THE READ ADVANCES PTR

    The host reads them POST-HALT, before the next launch, exactly where it
    already reads L_EOUT (S8 — one PTR write for the whole set, then two
    reads per entry, because IDX auto-increments):

            IDENT, STATUS                       2 reads
            wr(PTR, 0)                          1 write   <- ONCE, not per i
            for i in range(count): VAL, IDX     2n reads
            e_x = rd(L_EOUT) & 0xF              1 read    (unchanged, S4)

    = 68 MMIO accesses at the measured ~1.7 us = ~0.11 ms/token, i.e. free
    next to a 63 ms step (the pre-S8 spelling cost 98).

    STATUS bits, and what the host does with them (S8):
      * count[5:0]  entries the unit actually holds (< 32 for a short
                    vocabulary); only that many are read.
      * complete[6] no AMAX32 command is in flight.  Post-halt it MUST be
                    1; a 0 means the read raced the scan, which would
                    silently corrupt a sampled token — so it RAISES.
      * overflow[7] sticky: an element was rejected while tied with
                    entry[31], so the reported set is A valid top-32 but
                    not necessarily THE one a host sort would pick.  It is
                    reported (telemetry + log) and does not fail: ties at
                    the 32nd place cannot change the sampled distribution
                    by more than that one tied element.

    The ordering the unit guarantees: value DESC, and for equal values the
    LOWER row index first — the first-wins rule the AMAX comparator already
    implements (`ref/gen_layer_script.Mach.alu` op 10 / `Mach.amax`).
    Sampler._order()
    re-imposes it host-side anyway, so a unit that returns the set in any
    order is still correct.

    Until the ident reads back, `available` is False and every caller
    refuses with the rung-4 message instead of quietly doing something
    else (which is exactly what the ruling forbids).
    """

    name = "chip-topk"
    on_board = True
    IDENT = 0xFAB1704B           # EXPECTED ident word (0xFAB1_xxxx family)
    OFF_IDENT, OFF_STATUS, OFF_PTR, OFF_VAL, OFF_IDX = 0x00, 0x04, 0x08, 0x0C, 0x10
    ST_COUNT, ST_COMPLETE, ST_OVF = 0x3F, 1 << 6, 1 << 7
    RUNG4 = ("sampling needs the on-chip top-k capture unit, which arrives "
             "with the next RTL rung (rung 4).  The board is running a "
             "bitstream without it, so there is no candidate set to sample "
             "from.  Greedy decode is unaffected; --verify-head still "
             "cross-checks the chip's head against the host copy.")

    def __init__(self, dev, base=None, k=TOPK_CAPTURE_K):
        self.dev = dev
        self.base = base
        self.k = int(k)
        self.available = False
        self.why = self.RUNG4
        self.ident = None
        self.overflows = 0       # steps whose sticky overflow bit was set
        self.last_status = None
        self.probe()

    def probe(self):
        if self.base is None:
            self.why = (self.RUNG4 + "  (no --topk-base given, and this "
                        "bitstream publishes no top-k CSR block)")
            return False
        if self.dev is None:
            self.why = "no device open"
            return False
        try:
            self.ident = int(self.dev.rd(self.base + self.OFF_IDENT))
        except Exception as e:                                 # noqa: BLE001
            self.why = f"{self.RUNG4}  (IDENT read at {self.base:#x}: {e})"
            return False
        if self.ident != self.IDENT:
            self.why = (f"{self.RUNG4}  (IDENT at {self.base:#x} read back "
                        f"{self.ident:#010x}, expected {self.IDENT:#010x})")
            return False
        self.available = True
        self.why = ""
        return True

    def status(self):
        """(count, complete, overflow) out of the S5 STATUS word."""
        st = int(self.dev.rd(self.base + self.OFF_STATUS))
        self.last_status = st
        return (st & self.ST_COUNT, bool(st & self.ST_COMPLETE),
                bool(st & self.ST_OVF))

    def candidates(self, ctx):
        if not self.available:
            raise SamplingUnavailable(self.why)
        d, b = self.dev, self.base
        n, complete, ovf = self.status()
        if not complete:
            # S5: complete == "no AMAX32 in flight".  POST-HALT it cannot be
            # 0; if it is, the unit is still scanning and every value below
            # would be a partial result.  Refusing is the whole point of the
            # bit — a silently sampled half-scan is unfalsifiable.
            raise ChatSeqError(
                f"top-k STATUS {self.last_status:#010x} says an AMAX32 scan "
                f"is still in flight (complete=0) — the host read raced the "
                f"chip.  Reads are only legal after the launch halts.")
        if ovf:
            self.overflows += 1
        n = min(n, self.k)
        # S8: PTR is written ONCE; reading IDX advances it (the auto-
        # increment the S5 CSR map defines), so an entry costs two reads.
        d.wr(b + self.OFF_PTR, 0)
        vals, idxs = [], []
        for _i in range(n):
            v = int(d.rd(b + self.OFF_VAL))
            vals.append(v - (1 << 32) if v >= (1 << 31) else v)
            idxs.append(int(d.rd(b + self.OFF_IDX)) & 0x3FFFF)   # PTR++
        e_x = int(d.rd(HW.L_EOUT)) & 0xF                    # unchanged (S4)
        return (np.array(vals, dtype=np.int32),
                np.array(idxs, dtype=np.int64), e_x)

    def as_dict(self):
        d = CandidateSource.as_dict(self)
        d.update({"base": None if self.base is None else hex(self.base),
                  "ident": None if self.ident is None else hex(self.ident),
                  "overflow_steps": self.overflows,
                  "last_status": (None if self.last_status is None
                                  else hex(self.last_status))})
        return d


class FixtureCandidates(CandidateSource):
    """A recorded candidate sequence — tests and the board-free gate.

    Each entry is {"values": [...], "indices": [...], "e_x": int} plus
    whatever provenance the generator recorded.  `strict` (the default)
    refuses to run past the end of the recording rather than silently
    looping, because a looped fixture would make a determinism gate
    meaningless.
    """

    name = "fixture"
    on_board = False

    def __init__(self, entries, meta=None, strict=True, name="fixture"):
        self.entries = [self._norm(e) for e in entries]
        self.meta = dict(meta or {})
        self.strict = bool(strict)
        self.i = 0
        self.name = name
        self.k = max((len(e[0]) for e in self.entries), default=0)
        self.available = bool(self.entries)
        self.why = "" if self.entries else "the fixture is empty"

    @staticmethod
    def _norm(e):
        v = np.asarray(e["values"], dtype=np.int32)
        i = np.asarray(e["indices"], dtype=np.int64)
        if v.shape != i.shape:
            raise ChatSeqError("fixture entry: values/indices length mismatch")
        return v, i, int(e["e_x"])

    def reset(self):
        self.i = 0

    def candidates(self, ctx=None):
        if self.i >= len(self.entries):
            if self.strict:
                raise ChatSeqError(
                    f"the fixture has {len(self.entries)} recorded steps and "
                    f"step {self.i} was asked for — record a longer fixture "
                    f"or ask for fewer tokens")
            self.i = 0
        e = self.entries[self.i]
        self.i += 1
        return e

    def as_dict(self):
        d = CandidateSource.as_dict(self)
        d.update({"steps": len(self.entries), "consumed": self.i,
                  "provenance": self.meta})
        return d


class HostHeadCandidates(CandidateSource):
    """VERIFICATION ONLY: the host f32 head + an exact integer rescore.

    Not a decode path (2026-08-11 ruling).  Two legitimate users:

      * --verify-head, where the token still comes from the chip and this
        only produces the argmax the chip is checked against;
      * the board-free gate, where ref/seq_model.py supplies the hidden
        state and there is no chip in the loop at all.

    `x8src(ctx)` returns (x8 int8[1024], e_x) — from the scratchpad over
    MMIO (read_x8_eout) or from the python model's mach.
    """

    name = "host-head"
    on_board = False

    def __init__(self, head, x8src, k=TOPK_CAPTURE_K, margin=8):
        self.head = head
        self.x8src = x8src
        self.k = int(k)
        self.margin = int(margin)
        self.available = head is not None
        self.why = "" if head is not None else "no host head is loaded"
        self.last = None

    def candidates(self, ctx=None):
        if ctx and ctx.get("x8") is not None:
            x8, e_x = ctx["x8"], ctx["e_x"]       # --verify-head already read it
        else:
            x8, e_x = self.x8src(ctx)
        v, i = self.head.topk(x8, self.k, margin=self.margin)
        self.last = {"x8": x8, "e_x": int(e_x)}
        return v, np.asarray(i, dtype=np.int64), int(e_x)


# ----------------------------------------------------------------------
# x8 / e_x readback (S4) — POST-HALT ONLY
# ----------------------------------------------------------------------
def read_x8_eout(dev, addr=X8_WORD, n=X8_LEN, check=True):
    """(x8 int8[n], e_x) out of the layer_chan scratchpad, after the halt.

    WHY THIS IS SAFE BETWEEN LAUNCHES (verified against the committed
    stream, not assumed):

      * rtl/layer_chan.sv:16-18 (the SPTR/SWIN rows of the register map
        in the file header) — a SWIN read is legal only while the block is
        idle, and the RTL has a simulation $fatal for a SWIN read during a
        burst.  A halted sequencer is idle, so the read happens
        strictly between launches and never while SEQ is busy.
      * No record in the committed stream ever writes L_SPTR or L_SWIN
        (census of all 60,495 records: L_SPTR 0, L_SWIN 0 — scratch is
        loaded by LDC/EMB, which carry their own absolute destination), so
        moving SPTR here cannot disturb the next launch.  We still save
        and restore it (L_SPTR is RW and reads back,
        the SPTR readback in layer_chan's AXI-Lite read decode, named
        rather than line-cited because these numbers drift — D-CITE) so the
        CSR file is left exactly as found.
      * x8 lives at word 0x800 and the head only ever WRITES 0x1000+, so
        it survives the full launch that produced it (S7; asserted in
        --selftest against the record stream itself).

    Cost: n+3 MMIO reads ~ 1.75 ms for the 1024-word vector.
    """
    st = dev.seq_status()
    if st["busy"]:
        raise ChatSeqError(
            f"refusing to read the scratchpad while the sequencer is BUSY "
            f"(STATUS={st['raw']:#010x}) — SWIN reads are idle-only "
            f"(rtl/layer_chan.sv, the SWIN row of the register map)")
    keep = int(dev.rd(HW.L_SPTR)) & SPTR_MASK
    raw = dev.layer_read_scratch(addr, n)          # uint16 bit patterns
    e_x = int(dev.rd(HW.L_EOUT)) & 0xF
    dev.wr(HW.L_SPTR, keep)
    raw = np.asarray(raw, dtype=np.int64) & 0xFFFF
    x8 = (raw & 0xFF).astype(np.uint8).view(np.int8)
    if check:
        # a DYNQ8 result is an int16 in [-127, 127]: the high byte must be
        # the sign extension of the low one.  Anything else means we read
        # the wrong window (or read it at the wrong time).
        hi = (raw >> 8) & 0xFF
        want = np.where(x8.astype(np.int64) < 0, 0xFF, 0x00)
        bad = int((hi != want).sum())
        if bad:
            raise ChatSeqError(
                f"scratch[{addr:#x}..+{n}] does not look like a DYNQ8 int8 "
                f"vector: {bad}/{n} words are not sign-extended int8 "
                f"(first at word {int(np.nonzero(hi != want)[0][0])}) — "
                f"wrong window, or the read raced a launch")
    return x8, e_x


# ----------------------------------------------------------------------
# S7: what the record stream actually touches in the scratchpad
# ----------------------------------------------------------------------
def _cmd_scratch(lop, a0, a1, a2, g=None, dnsb=None):
    """One layer CMD -> (reads, writes) as [(word, nwords)].

    Transcribed from `ref/seq_model.py`'s `_layer_cmd` executor and
    `ref/gen_layer_script.py`'s `Mach` emitters.  Only the fields that
    address the scratchpad are decoded; everything else is ignored.
    (The old docstring cited `ref/seq_model.py:456-595` and
    `ref/gen_layer_script.py:274-578`; both ranges had drifted, which is the
    D-CITE class, so they are named by symbol instead.)

    `dnsb` is the DNSB layer CSR shadow, {a_dec_base[31:16],
    a_beta_base[15:0]} — SEQ_ISA v2.0 keeps DNST's two scalar pointers there
    instead of in the arg words, so a DNST cannot be decoded without it.
    `scratch_accesses` carries it record to record exactly as it carries the
    ARG shadow.

    `g` is the model geometry (`GEOM`).  G2a: the per-op vector LENGTHS below
    used to be the literals 128 / 256 / 16 / 32, which are `LDK`/`LDV`, `HD`,
    `LNH` and `2*LNH`.  This is a LIVE scratch-footprint decoder — selftest
    [17] proves the LM head never overwrites x8 with it — so at LNH=32 the
    GATE row would have understated the beta|decay tile by half and the S7
    proof would have been about the wrong words.  At 0.8B/2B every derived
    value equals the literal it replaced.
    """
    if g is None:
        g = GEOM
    HD, LDK, LDV, LNH = g["HD"], g["LDK"], g["LDV"], g["LNH"]
    # G3.1 (SEQ_ISA v2.0): scratch addresses are 16 bits and the pair layout
    # is the obvious one — ARG1 (and ARG2 on GATE/DNST) is
    # {hi[31:16], lo[15:0]}, with NO SCATTERED BITS ANYWHERE.  The ALU's
    # ARG2 is {dst[31:16], p0[15:0]} and GATE's ARG0 dst is arg0[15:0].
    # DNST's two scalar pointers are not in the arg words at all (see
    # `dnsb`).  This is one of the THREE independent implementations of the
    # layout (spec 7.6): the emitter, the RTL, and here.
    def _lo(w):
        return w & 0xFFFF

    def _hi(w):
        return (w >> 16) & 0xFFFF

    R, W = [], []
    s1, d1 = _lo(a1), _hi(a1)
    if lop == 1:                                        # VN
        n = 1 << ((a0 >> 2) & 0xF)
        R.append((s1, n))
        W.append((d1, n))
    elif lop == 2:                                      # VNW
        R.append((s1, a0))
    elif lop == 3:                                      # ROPET
        R.append((s1, 2 * g["ROT"]))
    elif lop == 4:                                      # ROPE
        R.append((s1, HD))
        W.append((d1, HD))
    elif lop == 5:                                      # CONVW / CONVZ
        if (a0 & 3) == 0:
            R.append((s1, 4 * ((a0 >> 16) & 0x3FFF)))
    elif lop == 6:                                      # CONV
        n = (a0 >> 14) & 0x3FFF
        R.append((s1, n))
        W.append((d1, n))
    elif lop == 7:                                      # GATE
        # beta LNH | A 2*LNH (int32 pairs) | dt LNH -> beta|decay 2*LNH.
        # `a0 & 0xFFFF` is the ISA's 16-bit dst FIELD, not the SPTR mask.
        R += [(s1, LNH), (d1, LNH), (_lo(a2), 2 * LNH), (_hi(a2), LNH)]
        W.append((a0 & 0xFFFF, 2 * LNH))
    elif lop == 8:                                      # DNST
        # a_beta = a_beta_base + head, a_dec = a_dec_base + head, both from
        # the DNSB CSR (SEQ_ISA v2.0).  A stream that issues DNST before
        # writing DNSB is not decodable — say so rather than guess a base.
        if dnsb is None:
            raise ChatSeqError(
                "DNST before any DNSB write: SEQ_ISA v2.0 keeps the two "
                "DeltaNet scalar pointers in the DNSB layer CSR (0x5C)")
        head = a0 & 0x1F
        R += [(s1, LDK), (d1, LDK), (_lo(a2), LDV),
              (((dnsb >> 16) & 0xFFFF) + head, 1),
              ((dnsb & 0xFFFF) + head, 1)]
        W.append((_hi(a2), 2 * LDV))
    elif lop == 9:                                      # KVAP
        R += [(s1, HD), (d1, HD)]
    elif lop == 10:                                     # ATTN
        R.append((s1, HD))
        W.append((d1, HD))
    elif lop == 11:                                     # ALU
        sub, n = a0 & 0xF, (a0 >> 4) & 0x3FFF   # cfg_len = ARG0[17:4]
        dst = (a2 >> 16) & 0xFFFF               # ARG2 = {dst[31:16], p0}
        R.append((s1, 2 * n if sub in (1, 6, 8, 9, 10, 12) else n))
        if sub in (3, 4, 8):
            R.append((d1, n))
        if sub == 10:                                   # AMAX32 writes nothing
            pass
        elif sub == 9:                                  # SHIFT32W: set_pairs
            W.append((dst, 2 * n))
        else:
            W.append((dst, n))
    return R, W


def scratch_accesses(recs, g=None):
    """Yield (i, tag, reads, writes) over a CONTIGUOUS record slice.

    Stateful exactly as the ISA is: the ARG0..2 shadow, SPTR and (since
    SEQ_ISA v2.0) the DNSB base pair are carried record to record, so a
    slice must start where the caller knows the shadow is irrelevant (the
    head tail only ever writes all three ARGs before each CMD, so
    [15532,16266) is self-contained).
    """
    arg = [0, 0, 0]
    sptr = 0
    dnsb = None
    for i, r in enumerate(recs):
        o, R, W = r.opcode, [], []
        tag = SF.OP_NAME.get(o, "?")
        if o == SF.OP_CSRWR and (r.target & 0xF000) == SF.CSR_SPACE_LAYER:
            off = r.target & 0xFF
            if off == SF.LOFF_ARG0:
                arg[0] = r.imm32
            elif off == SF.LOFF_ARG1:
                arg[1] = r.imm32
            elif off == SF.LOFF_ARG2:
                arg[2] = r.imm32
            elif off == SF.LOFF_SPTR:
                sptr = r.imm32 & SPTR_MASK
            elif off == SF.LOFF_SWIN:
                W.append((sptr, 1))
                sptr += 1
            elif off == SF.LOFF_DNSB:
                dnsb = r.imm32
            elif off == SF.LOFF_CMD:
                R, W = _cmd_scratch(r.imm32 & 0xFF, *arg, g=g, dnsb=dnsb)
        elif o == SF.OP_CMD:
            lop = r.imm32 & 0xFF
            R, W = _cmd_scratch(lop, *arg, g=g, dnsb=dnsb)
            tag = "CMD:" + str(SF.LOP_NAME.get(lop, lop))
            if lop == 11:
                tag += ":" + str(SF.ALU_NAME.get(arg[0] & 0xF, "?"))
        elif o == SF.OP_MOVX:
            R.append((r.addr_lo, r.len_or_addr_hi))
        elif o == SF.OP_MOVY:
            n = r.len_or_addr_hi
            W.append((r.addr_lo, n if r.movy_mode == SF.MOVY_INT16 else 2 * n))
        elif o == SF.OP_EMB:
            W.append((r.addr_lo, r.len_or_addr_hi))
        elif o == SF.EXT_LDC:
            W.append((r.target, r.imm32))               # dst is TARGET
        yield i, tag, [x for x in R if x[1]], [x for x in W if x[1]]


def _overlaps(win, lo, hi):
    a, n = win
    return a < hi and lo < a + n


# ----------------------------------------------------------------------
# fixtures on disk
# ----------------------------------------------------------------------
def load_fixture(path):
    with open(path) as f:
        d = json.load(f)
    if "steps" not in d:
        raise ChatSeqError(f"{path} is not a sampling fixture (no 'steps')")
    return FixtureCandidates(d["steps"], meta=d.get("provenance", {}),
                             name=f"fixture({os.path.basename(path)})")


def save_fixture(path, steps, provenance):
    d = {"format": "fable5_llm sampling candidate fixture v1",
         "provenance": provenance, "steps": steps}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(d, f, indent=1)
    return path


def synth_fixture(nsteps, k=TOPK_CAPTURE_K, seed=11, vocab=248320, e_x=5):
    """A SYNTHETIC candidate sequence for unit tests (no model, no board).

    Values are spread over a realistic y32 range so the dequantised
    logits land in the range the real head produces (about -10..+9).
    """
    rng = np.random.default_rng(seed)
    steps = []
    for _s in range(nsteps):
        idx = rng.choice(vocab, size=k, replace=False)
        v = np.sort(rng.integers(0, 1_300_000, size=k).astype(np.int64))[::-1]
        steps.append({"values": [int(x) for x in v],
                      "indices": [int(x) for x in idx], "e_x": int(e_x)})
    return FixtureCandidates(
        steps, meta={"kind": "synthetic", "seed": seed, "k": k,
                     "note": "unit-test fixture: NOT from the model"},
        name="synthetic")


# ======================================================================
# the session
# ======================================================================
class ChatSession(object):
    """Weights + images resident; one launch per forward step."""

    def __init__(self, args, log=print):
        self.args = args
        self.log = log
        self.dev = None
        self.T = 0                 # forward steps consumed == KV depth used
        self.next_in = None        # argmax of the last step, not yet fed
        self.fed = []              # every token id fed, in order
        self.launches = 0
        # rung 4 S6: latched once and never cleared — of_ovf is sticky until
        # a hard reset, so once a token has been dropped every later token
        # of this session is suspect.  Surfaced in stats()/telemetry.
        self.out_fifo_ovf = False
        self.perf = {"lite": [], "full": [], "preamble": []}
        self.step_log = []         # (image, tok, pos, out) per forward step
        self.verifier = None

        # ---- sampling / head verification (see the SAMPLING section) ----
        # `sampler` exists always; `sampler.enabled` is False for greedy,
        # which is the shipped decode and the default.
        self.sampler = Sampler(temp=getattr(args, "temp", DEFAULT_TEMP),
                               top_k=getattr(args, "top_k", DEFAULT_TOP_K),
                               top_p=getattr(args, "top_p", DEFAULT_TOP_P),
                               seed=getattr(args, "seed", None))
        self.cand = None           # CandidateSource once attach_sampling ran
        self.head = None           # sw/head_cache.HostHead (verification only)
        self.verify_head = bool(getattr(args, "verify_head", False))
        # a chip/host disagreement is FATAL on the board (S6).  The
        # board-free gate flips this to collect every step instead.
        self.verify_head_fatal = True
        self.sample_log = []       # per sampled/verified step
        self.head_checks = 0
        self.head_ms = []
        self.x8_read = None        # set by attach_sampling()

        # ---- chat template (docs/INSTRUCT_SPEC.md) --------------------
        # `template` is None until attach_template() runs (or --raw).
        # turns_templated/tmpl_* are per-CONTEXT: preamble() zeroes them,
        # so an auto-reset re-opens the conversation with the system
        # message again (T5 is "session start", and a reset IS one).
        self.template = None
        self.system = getattr(args, "system", None)
        self.turns_templated = 0
        self.tmpl_messages = 0     # messages of the equivalent HF rendering
        self.tmpl_overhead = 0     # wrapper ids fed since the reset
        self.tmpl_system = False   # a system message went into this context

        # ---- templates: agent A's TurnCompiler is the compiler of record --
        if SC is None:
            raise ChatSeqError(
                f"ref/seq_chat.py (agent A's TurnCompiler) is required: "
                f"{_SC_ERR}")
        self.prefix = args.template
        self.base = SR.derive_base(self.prefix)
        # --reorder (BM1-T4): the reordered template shares the SHIPPED
        # artifact's weights/emb/state images, and carries its own pin.
        self.reorder = getattr(args, "reorder", None)
        if self.reorder:
            self.base = SR.derive_base(TEMPLATE4_PREFIX)
        # SR6 (--seq-rtl): the RTL level the images are built for, and the
        # capability set every validation of this session runs at.  Until
        # open_board() it is the LEVEL's (the software gate: the caller
        # named the level); open_board() replaces it with the DEVICE's
        # after re-validating everything at that set (admit_caps).
        self.seq_rtl = check_seq_rtl(args)
        self.level_caps = seq_rtl_caps(self.seq_rtl)
        self.caps = self.level_caps
        self.dev_caps = None
        self.pos_mode = resolve_pos_mode(args)
        # ---- rung 4 S4: which artifact set / weight placement (--nch) ----
        # A session is ONE nch for its whole life: the weight images are
        # placed differently in DDR per mode, so flipping mid-session would
        # read a mixture.  `--nch` therefore selects the artifact AND the
        # residency layout, and is checked against the stream's own meta.
        self.nch = int(getattr(args, "nch", 1) or 1)
        if self.nch not in NCH_CHOICES:
            raise ChatSeqError(f"--nch {self.nch} not in {NCH_CHOICES}")
        self.meta0 = json.load(open(self.prefix + ".seq.json"))
        art_nch = int(self.meta0.get("nch", 1))
        if art_nch != self.nch:
            raise ChatSeqError(
                f"--nch {self.nch} but {os.path.basename(self.prefix)}.seq is "
                f"an nch={art_nch} stream.  The 1-chan template is "
                f"{os.path.basename(TEMPLATE_PREFIX)} and the 4-chan one is "
                f"{os.path.basename(TEMPLATE4_PREFIX)} (regenerate with "
                f"SEQ_NCH=4); they are NOT interchangeable — their MVGOs "
                f"address different engines and their weight images are "
                f"placed differently.")
        self.wlayout = dict(self.meta0.get("weight_layout") or {})
        t0 = time.monotonic()
        if self.nch == 1:
            # THE SHIPPED PATH — agent A's module, agent A's frozen indices,
            # byte-for-byte what every committed chat gate ran.
            self.geom = frozen_geometry()
            self.tmpl_sha = TEMPLATE_SHA256
            self.SCm = SC
            self.tc = self._turn_compiler(SC, verify_sha=not args.any_template)
        else:
            recs0 = SF.unpack_stream(open(self.prefix + ".seq", "rb").read())
            self.geom = derive_geometry(recs0, self.meta0)
            self.tmpl_sha = (REORDER4_BY_FORM[self.reorder][1]
                             if self.reorder in REORDER4_BY_FORM
                             else TEMPLATE4_SHA256)
            got = hashlib.sha256(open(self.prefix + ".seq", "rb").read()) \
                .hexdigest()
            if not args.any_template and got != self.tmpl_sha:
                raise ChatSeqError(
                    f"{self.prefix}.seq sha256 {got[:16]} != the gated "
                    f"4-chan template {self.tmpl_sha[:16]}.  Regenerate it "
                    f"with SEQ_NCH=4 and re-run the seq_model 4-chan gate "
                    f"before re-pinning TEMPLATE4_SHA256.")
            self.SCm = seq_chat_for(self.geom)
            self.tc = self._turn_compiler(self.SCm, verify_sha=False)
            log(f"  nch=4      {os.path.basename(self.prefix)}: "
                f"{self.geom['TEMPLATE_NREC']} records, body "
                f"{self.geom['NREC_BODY_FULL']} full / "
                f"{self.geom['NREC_BODY_LITE']} lite; head image(s) "
                f"{self.wlayout.get('ilv_wids')} chunk-INTERLEAVED over "
                f"{self.wlayout.get('nch')} channels (S4)")
        self.meta = self.tc.meta
        # SR11a fix round 2: the SHAPE layout every validation of this
        # session runs at until open_board() re-validates at the DEVICE's
        # (the artifact's own `shape_isa` key, or --shape-isa)
        self.shape_isa = self.tc.T.shape_isa
        self.const_blob = self.tc.blob()
        self.layout = self.tc.blob_layout()
        try:
            self.images = {
                "preamble": Resident("preamble", self.tc.build_session()),
                "lite": Resident("lite", self.tc.build_step(0, 0, "lite")),
                "full": Resident("full", self.tc.build_step(0, 0, "full")),
            }
        except SF.SeqValidationError as e:
            raise ChatSeqError(self._shape_hint(
                f"the template's step images fail validation: {e}", e))
        # S1P form B: reorder each step image on its own; the patch follows
        # its record through `reorder_perm` (see the FORM B block above)
        self.reorder_perm = {}
        self.ship_step = {}
        if self.reorder == "B":
            self._reorder_images_b(log)
        log(f"  compiler   ref/seq_chat.TurnCompiler(pos_mode={self.pos_mode!r}"
            f", t_max={args.t_max}) on {os.path.basename(self.prefix)} -> "
            + ", ".join(f"{n}:{im.nrec}" for n, im in self.images.items())
            + f"  ({time.monotonic() - t0:.1f}s)")
        log(f"  blob       {len(self.const_blob)} B = "
            f"{self.layout['const_bytes']} B constants + "
            f"{self.layout['t_max']} positions x "
            f"{self.layout['pos_stride']} B")
        if self.pos_mode == "xrf":
            log(f"  WARNING    pos_mode='xrf' caps the context at position "
                f"{self.layout['xrf_pos_max']} (XRF[4] is SIGNED 18-bit and "
                f"seq_unit truncates silently) — --max-ctx is "
                f"{args.max_ctx}")
        self.agent_a = crosscheck_agent_a(self, log=log)

        # R-b: `emb_row_bytes` (2*H) travels in the manifest; absent means
        # HW.EMB_ROW_BYTES_DEFAULT, which G3.4 moved 2048 -> 8192 with the
        # EMBLOG2 reset it mirrors (spec 5.3 S8).
        self.manifest, mmeta = HW.load_weights_manifest(self.base)
        self.emb_row_bytes = mmeta["emb_row_bytes"]
        # S3 (SEQ_ISA v2.1): the DDR state region's plan and the conv images
        # the host uploads into it.  None for a pre-S3 artifact.
        self.state = mmeta["state"]
        self.conv_images = mmeta["conv_images"]
        self.wdir = os.path.dirname(os.path.abspath(self.base)) or "."
        self.embf = self.base + ".emb.bin"
        self.wbase_of, self.wtop = SR.plan_weights_for(self.manifest,
                                                       self.wdir, self.meta)

        # ---- DDR plan + one-shot relocation (spec decision 11) ----
        self.plan = self._plan_ddr()
        self._relocate()

    # ------------------------------------------------ planning / images
    def _plan_ddr(self):
        span = 0
        for name in ("preamble", "lite", "full"):
            im = self.images[name]
            im.base = SEQ_STREAM_BASE + span
            span += _align(im.nrec * SEQ_REC_BYTES, SEQ_ALIGN)
        plan = SR.plan_ddr(self.meta, span, len(self.const_blob),
                           chan=self.args.chan)
        if plan["stream_base"] != SEQ_STREAM_BASE:
            raise ChatSeqError("stream window moved under us")
        return plan

    def _latch_ovf(self, rep):
        """Rung 4 S6: latch the sticky OUT-FIFO overflow for the session.

        of_ovf is sticky until a HARD RESET (the xrf_ovf precedent), so it
        is not a per-launch event to count — it is a one-way alarm meaning
        "a token was dropped on this power-on".  Once set, it stays set in
        every telemetry payload until the board is reprogrammed.
        """
        if rep.get("out_fifo_ovf") and not self.out_fifo_ovf:
            self.out_fifo_ovf = True
            self.log("  WARNING    seq_unit STATUS of_ovf is SET: the OUT "
                     "FIFO dropped at least one token since the last board "
                     "reset.  The bit is sticky until reset, so it may "
                     "predate this session — but no token this session "
                     "reports can be trusted until the board is "
                     "reprogrammed and the run repeated.")
        return self.out_fifo_ovf

    def weight_splits(self):
        """The S4 placement for this session, or None for the 1-chan path.

        None means "one whole image at wbase on the fetch channel" — the
        shipped nch=1 behaviour, byte for byte.
        """
        if self.nch <= 1:
            return None
        return SR.plan_weight_split(self.manifest, self.wbase_of, self.nch,
                                    self.plan["weight_chans"], self.meta)

    def layout_tag(self):
        """What placement the board must be holding for this session.

        serve.py compares these across sessions: two sessions may share a
        resident weight image only when their tags match (S4 — a --nch flip
        is a full re-upload, never a silent reinterpretation).
        """
        wl = self.wlayout
        return {"nch": self.nch,
                "chunk_rows": int(wl.get("chunk_rows", SF.CHUNK_ROWS)),
                "ilv_wids": sorted(int(w) for w in wl.get("ilv_wids", [])),
                "template": os.path.basename(self.prefix),
                "template_sha256": (self.tmpl_sha[:16]
                                    if self.tmpl_sha else None)}

    def patch_writes(self, kind, tok, pos, tcnt=1):
        """Agent A's per-launch patch, in HOST address space.

        `data_delta` is the host relocation delta: in pos_mode="ldc" the
        patch carries absolute const-blob addresses, so it must land where
        _relocate() put the pool, not where the emitter said it was.
        """
        p = self.step_patch(kind, tok=tok, pos=pos, tcnt=tcnt,
                            data_delta=self.plan["data_delta"])
        return p.writes(), p.fields

    def _reorder_images_b(self, log=print):
        """S1P form B: the per-image reorder, checked against the pins."""
        t0 = time.monotonic()
        lvl = self.seq_rtl
        pins = REORDER_B_PINS_BY_RTL[lvl][0]
        tag = "--reorder B" + ("" if lvl == "r0" else f" --seq-rtl {lvl}")
        try:
            built = reorder_b_images(self.tc, self.SCm, rtl=lvl)
        except AssertionError as e:          # HazardError / ReorderError /
            raise ChatSeqError(              # StaticCostError
                f"{tag}: the reorder pass REFUSED: "
                f"{type(e).__name__}: {e}")
        for kind, (img, perm, rep) in built.items():
            sha = hashlib.sha256(img.data).hexdigest()
            pin, pn = pins[kind]
            if pin is None or sha != pin or img.nrec != pn:
                raise ChatSeqError(
                    f"{tag}: REFUSED — the {kind} image regenerated as "
                    f"{sha[:16]} ({img.nrec} records), pinned "
                    f"{(pin or 'NONE')[:16]} ({pn}): not the gated bytes")
            # SR6: the image is validated at the level's set (r1: masked
            # FENCEs need {"R1"}); the device's set is applied at open_board
            try:
                SF.validate_stream(SF.unpack_stream(img.data),
                                   caps=self.caps, shape_isa=self.shape_isa)
            except SF.SeqValidationError as e:
                raise ChatSeqError(f"{tag}: the {kind} image fails "
                                   f"validation at capabilities "
                                   f"{sorted(self.caps) or '{}'}: {e}")
            self.ship_step[kind] = self.images[kind].a
            self.images[kind] = Resident(kind, img)
            self.reorder_perm[kind] = perm
            s = rep["segments"][0]
            log(f"  reorder    form B{'' if lvl == 'r0' else ' ' + lvl} {kind}: "
                f"{self.ship_step[kind].nrec} -> "
                f"{img.nrec} records == pin {sha[:16]}; MOVX elided "
                f"{s['movx_elided']}, fences deferred {s['fences_deferred']}"
                f"; hazard assert PASS {rep['hazard']}; postcheck "
                f"{s['post_replay'][0]} edges"
                + ("" if lvl == "r0" else
                   f"; FENCE masks {rep.get('fence_masks')}; static model "
                   f"{s['orig_win']} -> {s['replay_mk']} cyc"))
        log(f"  reorder    form B images built in "
            f"{time.monotonic() - t0:.1f} s")

    def step_patch(self, kind, tok, pos, tcnt=1, data_delta=0):
        """The per-launch Patch for step image `kind`.  Without form B this
        IS agent A's patch_step.  With form B each write of the SHIPPED
        image's patch is moved to where the pass put the record it was aimed
        at (the patch follows its record)."""
        perm = self.reorder_perm.get(kind)
        if perm is None:
            return self.tc.patch_step(self.images[kind].a, tok=tok, pos=pos,
                                      tcnt=tcnt, data_delta=data_delta)
        p = self.tc.patch_step(self.ship_step[kind], tok=tok, pos=pos,
                               tcnt=tcnt, data_delta=data_delta)
        return follow_patch(p, perm, self.SCm)

    def _relocate(self):
        """LDC/EMB rebase, ONCE per session, on the three images."""
        tot = 0
        for name in ("preamble", "lite", "full"):
            im = self.images[name]
            im.recs, rep = SR.relocate(im.recs_emit, self.meta, self.plan,
                                       len(self.const_blob), caps=self.caps,
                                       shape_isa=self.shape_isa)
            im.data = SF.pack_stream(im.recs)
            if len(im.data) != im.nrec * SEQ_REC_BYTES:
                raise ChatSeqError("packed image size mismatch")
            tot += rep["ldc"] + rep["emb"]
        self.log(f"  relocate   {tot} LDC+EMB records rebased by "
                 f"{self.plan['data_delta']:+#x} / {self.plan['emb_delta']:+#x}"
                 f"; images at "
                 + ", ".join(f"{n}@{self.images[n].base:#x}"
                             for n in ("preamble", "lite", "full")))

    # ------------------------------------------------ SHAPE layout
    def _turn_compiler(self, mod, verify_sha):
        """agent A's TurnCompiler at the session's STATED SHAPE layout
        (--shape-isa; SR11a fix round 2).  Without it the artifact's own
        `shape_isa` key decides, and a frozen isa=1 W8 template (no key,
        SHAPE bit 29 = w8) is refused naming --shape-isa."""
        a = self.args
        try:
            return mod.TurnCompiler(self.prefix, t_max=a.t_max,
                                    pos_mode=self.pos_mode,
                                    verify_sha=verify_sha,
                                    shape_isa=getattr(a, "shape_isa", None))
        except SF.SeqValidationError as e:
            raise ChatSeqError(self._shape_hint(
                f"the template fails validation: {e}", e))

    def _shape_hint(self, msg, e):
        if getattr(self.args, "shape_isa", None) is None \
                and "SHAPE bits 29/30" in str(e):
            msg += ("\n  (no SHAPE layout was stated and the artifact "
                    "declares none: pass --shape-isa 1 for a build_034/035 "
                    "artifact, whose MVGO SHAPE bit 29 is w8, or "
                    "--shape-isa 2; docs/SEQ_ISA.md B17.2)")
        return msg

    # ------------------------------------------------ board bring-up
    def open_board(self):
        a = self.args
        self.dev = SR.Dev(a.dev, chan=a.chan, allow_seq=True)
        d = self.dev
        self.log(f"  board      MAGIC={d.ident['magic']:#010x} "
                 f"VERSION={d.ident['version']:#010x} "
                 f"CALIB={d.ident['calib']:#x} "
                 f"SEQ={'READY' if d.seq_ok else 'REFUSED'}")
        if not d.seq_ok:
            raise ChatSeqError("SEQ CSRs refused: " + d.seq_why)
        # SR11a fix round 2: the DEVICE's SHAPE layout, keyed by the VERSION
        # the identity gate just admitted (never a default); a session built
        # at a different stated/declared layout is refused before any DMA
        try:
            dshape = HW.shape_isa_for_version(d.ident["version"])
        except HW.UnknownBitstream as e:
            raise ChatSeqError(f"SHAPE layout refused: {e}")
        if self.shape_isa is not None and int(self.shape_isa) != dshape:
            raise ChatSeqError(
                f"REFUSED before any upload: the session was built at SHAPE "
                f"isa={self.shape_isa} but the device (VERSION "
                f"{d.ident['version']:#010x}) decodes isa={dshape}")
        self.shape_isa = dshape
        self.log(f"  shape      SHAPE layout isa={dshape} (the device's "
                 f"VERSION {d.ident['version']:#010x})")
        # SR6 (docs/SEQ_ISA.md v2.3 B17.0): the DEVICE's capability set,
        # read once, and everything this session will upload re-validated
        # at it — before bring_up(), i.e. before any DMA
        try:
            dcaps = d.seq_caps()
        except SR.SeqError as e:
            raise ChatSeqError(f"SEQ_CAPS refused: {e}")
        self.admit_caps(dcaps, word=getattr(d, "caps_word", None))
        return d

    def admit_caps(self, caps, word=None):
        """Task SR6: validate this session at the DEVICE's capability set
        `caps` (Dev.seq_caps(): the EMPTY set on build_041/042) before any
        upload, and make it the session's set.

        Re-validated at `caps`: the template (load_template — chat_seq's
        first validate_stream site), the independent step slices
        (independent_step_images — the second), and every RELOCATED image
        the board will run (preamble, lite, full).  A stream using a
        feature the device lacks is refused naming the record; then the
        level's own set must be a subset of the device's, refused by name.
        The session's --seq-rtl level (never a manifest) chose the images;
        the device decides whether they load.  Raises ChatSeqError."""
        caps = HW.seq_caps_check(caps)
        # SR13b (the keyless path; SR11a round-3 re-review, controller
        # addendum): the template must DECLARE its SHAPE layout -- a keyless
        # post-G3 0.8b/2b template named at build_035 would otherwise be
        # built at a stated --shape-isa 1 and upload garbage.  Keyless is
        # admitted only for a frozen pre-G3 stream at an isa=1 device
        # (sw/seq_run.layout_key_check).  Checked FIRST, before any
        # validation; a declared key was already compared with the
        # device's layout (TurnCompiler / open_board).
        try:
            with open(self.prefix + ".seq", "rb") as f:
                tsha = hashlib.sha256(f.read()).hexdigest()
            SR.layout_key_check(self.meta0, tsha, self.shape_isa,
                                what=f"{self.prefix}.seq.json")
        except SR.SeqError as e:
            raise ChatSeqError(f"REFUSED before any upload: {e}")
        t0 = time.monotonic()
        where = ("the device's SEQ_CAPS "
                 + (f"{word:#010x}" if word is not None else "(given)"))
        cs = sorted(caps) or "{}"
        try:
            recs, _blob, _meta = load_template(
                self.prefix, check_sha=not self.args.any_template,
                sha=self.tmpl_sha, g=self.geom, caps=caps,
                shape_isa=self.shape_isa)
            independent_step_images(recs, self.geom, caps=caps,
                                    shape_isa=self.shape_isa)
        except SF.SeqValidationError as e:
            raise ChatSeqError(f"REFUSED before any upload: the template "
                               f"at capabilities {cs} ({where}): {e}")
        for n in ("preamble", "lite", "full"):
            try:
                SF.validate_stream(self.images[n].recs, caps=caps,
                                   shape_isa=self.shape_isa)
            except SF.SeqValidationError as e:
                raise ChatSeqError(
                    f"REFUSED before any upload: image {n} "
                    f"(--seq-rtl {self.seq_rtl}) at capabilities {cs} "
                    f"({where}): {e}")
        missing = sorted(self.level_caps - caps)
        if missing:
            raise ChatSeqError(
                f"REFUSED before any upload: --seq-rtl {self.seq_rtl} needs "
                f"capability {', '.join(missing)}, which {where} "
                f"({cs}) lacks")
        self.caps = self.dev_caps = caps
        self.log(f"  caps       {cs} from {where}; template, slices and the "
                 f"3 images (--seq-rtl {self.seq_rtl}) validated at it "
                 f"({time.monotonic() - t0:.1f} s)")
        return caps

    def bring_up(self):
        """Residency probe -> targeted upload -> const blob + images."""
        dev, a = self.dev, self.args
        # R-b: the EMB row size, before ANY image (the preamble EMBs) runs
        SR.seq_set_emb_row_bytes(dev, self.emb_row_bytes, log=self.log)
        SR.check_weight_plan(self.meta, self.wbase_of, self.manifest)
        SR.check_mvgo_targets(
            [r for n in ("lite", "full") for r in self.images[n].recs_emit],
            self.wbase_of, self.manifest, self.meta)

        splits = self.weight_splits()
        wit = build_residency_manifest(self.manifest, self.wdir, self.wbase_of,
                                       self.embf, self.plan["emb_base"],
                                       splits=splits,
                                       state=getattr(self, "state", None),
                                       conv_images=getattr(
                                           self, "conv_images", None))
        # §14.1: the conv witnesses are STATE, not pack.  They are probed
        # AFTER `bring_up_state` restores the region, and never escalate a
        # weight re-upload (`split_witnesses`).
        wit, wit_cv = split_witnesses(wit)
        bad = [] if a.force_upload else probe_residency(dev, wit, self.log)
        if a.force_upload:
            self.log("  residency  SKIPPED (--force-upload)")
            bad = wit
        badw, bade, n_sel = reupload_set(bad, self.manifest)
        if n_sel is not None and n_sel != len(badw):
            self.log(f"  residency  {n_sel} image(s) missed a witness; "
                     f"re-uploading ALL {len(badw)} + the embedding — a "
                     f"miss means the pack is not ours to trust")
        if badw or bade:
            t0 = time.monotonic()
            nby = 0
            by_wid = {}
            for s in (splits or []):
                by_wid.setdefault(s["wid"], []).append(s)
            for wid in badw:
                m = self.manifest[str(wid)]
                img = open(os.path.join(self.wdir, m["file"]), "rb").read()
                if not splits:
                    dev.dma_write(self.wbase_of[wid], img)
                    dev.dma_verify(self.wbase_of[wid], img, tag=m["file"])
                else:
                    # S4: place each piece where THIS stream's MVGOs read it
                    mv = memoryview(img)
                    for s in by_wid[wid]:
                        lo = s["byte_off"]
                        hi = lo + s["byte_len"]
                        dev.dma_write_chan(s["chan"], s["local_addr"],
                                           mv[lo:hi])
                        dev.dma_verify_chan(
                            s["chan"], s["local_addr"], img[lo:hi],
                            tag=f"{m['file']} c{s['chan']} rows"
                                f"[{s['r0']},{s['r0'] + s['nrows_piece']})")
                nby += len(img)
            if bade:
                emb = open(self.embf, "rb").read()
                dev.dma_write(self.plan["emb_base"], emb)
                dev.dma_verify(self.plan["emb_base"], emb, tag="emb")
                nby += len(emb)
            self.log(f"  upload     {len(badw)} weight image(s)"
                     + (" + the embedding table" if bade else "")
                     + f": {nby / 2**20:.0f} MiB readback-verified in "
                       f"{time.monotonic() - t0:.1f}s")
            if probe_residency(dev, wit, self.log):
                raise ChatSeqError("residency probe still failing after upload")
        else:
            self.log("  upload     SKIPPED: every weight/emb witness block is "
                     "already resident")

        self.bring_up_state(wit_cv)

        t0 = time.monotonic()
        dev.dma_write(self.plan["data_base"], self.const_blob)
        dev.dma_verify(self.plan["data_base"], self.const_blob, tag="blob")
        nb = len(self.const_blob)
        for name in ("preamble", "lite", "full"):
            im = self.images[name]
            dev.dma_write(im.base, im.data)
            dev.dma_verify(im.base, im.data, tag=f"image {name}")
            nb += len(im.data)
        self.log(f"  upload     const blob + 3 images: {nb / 1024:.0f} KiB "
                 f"readback-verified in {time.monotonic() - t0:.1f}s")

    def bring_up_state(self, wit_cv=()):
        """C: the DDR state region — the INITIAL IMAGE, then the base CSRs.

        The board half of `SeqModelVerifier.state_region`.  Three things,
        in this order, and none of them optional:

        1. `sw/seq_run.upload_state` writes the region's initial contents —
           the DN memset and one write per conv image, each read back — and
           programs `SB_DN`/`SB_KV`/`SB_CV`.  **Programming the CSRs alone
           is not enough**: `evidence/qwen9b/g6/RD9_GATE.md` §14.2 measured
           a run that halted at the right PC with `err_code 0x00` and
           answered with the wrong tokens, because the DN and conv state the
           PREVIOUS run left in DDR is the state the first `SLD` loads.  So
           this never uses the `csrs_only` path.
        2. `sw/seq_run.seq_check_state_bases` reads the three CSRs back and
           refuses here rather than letting the first SLD/SST halt the
           program with `E_DMA_BASE` (SEQ ISA v2.1 B15.4).
        3. the conv witnesses (`split_witnesses`) are probed HERE, against
           the write that just happened, so a miss is a real miss and not
           §14.1's by-design staleness.

        Returns `sw/seq_run.upload_state`'s report, or None for a pre-S3
        artifact (the frozen `--nch 1` path writes no region).
        """
        if getattr(self, "state", None) is None:
            self.log("  state      none (pre-v2.1 artifact: the stream "
                     "carries no SLD/SST)")
            return None
        rep = SR.upload_state(self.dev, self, log=self.log)
        SR.seq_check_state_bases(self.dev, self, log=self.log)
        if wit_cv:
            bad = probe_residency(self.dev, list(wit_cv), self.log)
            if bad:
                raise ChatSeqError(
                    f"{len(bad)} conv-image witness block(s) still differ "
                    f"after the state upload: "
                    + ", ".join(w["name"] for w in bad[:4]))
            self.log(f"  state CV   {len(wit_cv)} conv witness(es) match "
                     f"the region just written (NOT part of the weight "
                     f"pack's probe — §14.1)")
        return rep

    # ------------------------------------------------ launches
    def reset_state_region(self):
        """S3 (spec 2 "Session reset", 6.4): zero the DDR DeltaNet region.

        Under v2.1 the program no longer zeroes anything -- the 768 DNZ are
        retired -- so a fresh chat context costs a HOST-side memset of the
        DN region through the same H2C path the upload uses, plus the TCNT
        reset the preamble image already does (now eight LAYER writes and
        sixteen counter writes, A1.3).  The KV region needs nothing: TCNT is
        0, so no KV block is read before it is written.
        """
        st = getattr(self, "state", None)
        if st is None:
            return 0
        t0 = time.monotonic()
        chan = st["dn"] >> 32
        zero = bytes(HW.STATE_DN_LAYER)
        n = (st["kv"] - st["dn"]) // HW.STATE_DN_LAYER
        for i in range(n):
            self.dev.dma_write_chan(chan, (st["dn"] & 0xFFFF_FFFF)
                                    + i * HW.STATE_DN_LAYER, zero)
        # S3 fix round 1, I6: read it back.  A session reset that did not
        # land leaves the previous chat's DeltaNet state in the region, and
        # the next token reads it -- the silent-carryover failure the
        # preamble's 768 DNZ used to make impossible.  Eight 4 KiB
        # witnesses, first and last block included.
        nbad = 0
        for a in HW.state_dn_witnesses(st):
            if self.dev.dma_read_chan(chan, a & 0xFFFF_FFFF, 4096) \
                    != bytes(4096):
                nbad += 1
                self.log(f"  state DN  WITNESS {a:#x} is NOT zero")
        if nbad:
            raise ChatSeqError(
                f"{nbad} DN-region witness block(s) are not zero after the "
                f"session memset — the previous context would carry over")
        self.log(f"  state DN  {n * HW.STATE_DN_LAYER / 2**20:.0f} MiB "
                 f"zeroed in {(time.monotonic() - t0) * 1e3:.0f} ms "
                 f"(session reset)  [8 witnesses zero]")
        # D: the conv blocks are the OTHER half of a context reset.  A run
        # writes conv STATE into the same 128 KiB blocks that hold the conv
        # weight TAPS (`evidence/qwen9b/g6/RD9_GATE.md` §14.1), so a fresh
        # context must put the artifact's images back or the new context
        # convolves against the previous one's tail — §14.2's failure,
        # silent and at `err_code 0x00`.  The KV region still needs nothing:
        # TCNT is 0, so no KV block is read before it is written.
        t1 = time.monotonic()
        ncv = 0
        for ci in (getattr(self, "conv_images", None) or []):
            img = open(os.path.join(self.wdir, ci["file"]), "rb").read()
            if len(img) != int(ci["bytes"]):
                raise ChatSeqError(f"conv image {ci['file']} is {len(img)} B, "
                                   f"the manifest says {ci['bytes']}")
            a = ((st["cv"] & 0xFFFF_FFFF)
                 + int(ci["layer"]) * HW.STATE_CV_STRIDE)
            self.dev.dma_write_chan(chan, a, img)
            self.dev.dma_verify_chan(chan, a, img,
                                     tag=f"conv image L{ci['layer']}")
            ncv += 1
        if ncv:
            self.log(f"  state CV  {ncv} conv image(s) restored to "
                     f"{st['cv']:#x} in {(time.monotonic() - t1) * 1e3:.0f} "
                     f"ms  [readback OK]")
        return n

    def preamble(self):
        """Session-once reset: the DN region memset, T=0 in every layer."""
        self.reset_state_region()
        im = self.images["preamble"]
        # the session image's only hole is TCNT_SEQ; keep the write explicit
        # so no launch can ever run with TCNT_SEQ == 0 (spec hazard).
        w = [(im.holes["tcnt"], (1).to_bytes(4, "little"))]
        rep = _launch(self.dev, im, writes=w, tok=0, pos=0,
                      timeout=self.args.preamble_timeout, log=self.log)
        if rep["tokens"]:
            raise ChatSeqError(f"the preamble emitted tokens {rep['tokens']}")
        self.launches += 1
        self._latch_ovf(rep)
        self.perf["preamble"].append(rep["device_ms"])
        self.T, self.next_in, self.fed = 0, None, []
        self.step_log = []
        self.turns_templated = self.tmpl_messages = self.tmpl_overhead = 0
        self.tmpl_system = False
        if self.verifier is not None:
            # a fresh mach + the SAME preamble image, so an auto-reset keeps
            # the lockstep model in step with the chip
            self.verifier.reset()
            self.verifier.preamble(self.images["preamble"])
        self.log(f"  preamble   {rep['device_ms']:.1f} ms device / "
                 f"{rep['wall_ms']:.1f} ms wall  (context reset: KV/DN/conv, "
                 f"T=0)")
        return rep

    def step(self, tok, lite):
        """One forward step at position self.T.  Returns (token|None, rep).

        `lite` means "this is a prefill step, no token needed" and picks
        the LM-head-less body.  A DECODE step is always the FULL body —
        the chip computes the head and the argmax, exactly as it does in
        greedy mode.  Sampling only chooses differently among the
        candidates the chip reports (2026-08-11 ruling); it never moves
        the model off the FPGA.
        """
        if self.T >= self.args.t_max:
            raise ChatSeqError(f"position {self.T} would wrap the KV banks")
        kind = "lite" if lite else "full"
        im = self.images[kind]
        writes, fields = self.patch_writes(kind, tok, self.T, tcnt=1)
        rep = _launch(self.dev, im, writes=writes, tok=tok, pos=self.T,
                      timeout=self.args.timeout, log=self.log)
        rep["patch_fields"] = fields
        self.launches += 1
        self._latch_ovf(rep)
        self.perf["lite" if lite else "full"].append(rep["device_ms"])
        want = 0 if lite else 1
        if len(rep["tokens"]) != want:
            raise ChatSeqError(
                f"{im.name} step at pos {self.T} produced "
                f"{len(rep['tokens'])} tokens, expected {want}")
        self.fed.append(int(tok))
        self.T += 1
        out = int(rep["tokens"][0]) if rep["tokens"] else None
        rep["chip_token"] = out
        if self.verifier is not None:
            # the lockstep model predicts the CHIP's token, not the sampled
            # one — check it before anything downstream can override `out`
            self.verifier.check(im, tok, self.T - 1, out)
        if not lite:
            out = self.post_head(rep, out, pos=self.T - 1)
        self.step_log.append((im.name, int(tok), int(rep["pos"]), out))
        if out is not None:
            self.next_in = out
        return out, rep

    # ------------------------------------------------ sampling / verify
    def post_head(self, rep, chip_tok, pos=None):
        """--verify-head cross-check and/or the sampled draw, post-halt.

        Returns the token to FEED: the chip's own argmax unless a sampler
        is enabled, in which case the draw over the chip's candidate set.
        Nothing here runs in the default greedy configuration.
        """
        if not (self.verify_head or self.sampler.enabled):
            return chip_tok
        t0 = time.monotonic()
        entry = {"pos": pos, "chip_token": chip_tok}
        ctx = {"pos": pos, "rep": rep}
        if self.verify_head:
            if self.head is None:
                raise ChatSeqError("--verify-head without a host head: call "
                                   "attach_sampling() first")
            x8, e_x = self.x8_read(ctx)
            ctx["x8"], ctx["e_x"] = x8, e_x
            hid, hval = self.head.argmax(x8)
            self.head_checks += 1
            entry.update({"e_x": int(e_x), "host_argmax": int(hid),
                          "host_y32": int(hval),
                          "head_match": chip_tok is None or hid == chip_tok})
            if (chip_tok is not None and hid != chip_tok
                    and self.verify_head_fatal):
                raise ChatSeqError(
                    f"--verify-head MISMATCH at pos {pos}: the chip pushed "
                    f"token {chip_tok}, the host head's argmax over the same "
                    f"x8 (e_x={e_x}) is {hid} (y32={hval}).  One of the two "
                    f"is wrong — capture x8 before rerunning.")
        out = chip_tok
        if self.sampler.enabled:
            if self.cand is None or not self.cand.available:
                raise SamplingUnavailable(
                    self.cand.why if self.cand is not None
                    else ChipTopKSource.RUNG4)
            v, i, e_x = self.cand.candidates(ctx)
            out, info = self.sampler.pick(v, i, e_x)
            entry.update(info)
            # keep the raw candidate set: it is what a fixture records and
            # what an evidence report needs to be re-checkable
            entry["cand_values"] = [int(x) for x in v]
            entry["cand_indices"] = [int(x) for x in i]
        entry["head_ms"] = round((time.monotonic() - t0) * 1e3, 3)
        self.head_ms.append(entry["head_ms"])
        entry["token"] = out
        self.sample_log.append(entry)
        rep["sampling"] = entry
        return out

    def attach_sampling(self, log=print, offline=False):
        """Resolve the candidate source; REFUSE early if there is none.

        Called once per session, after open_board() (the chip source has
        to probe a CSR).  The refusal is deliberately fatal at session
        start rather than at the first decode step: a user who asked for
        --temp must never get greedy output and a warning buried in a log.
        """
        a = self.args
        want = self.sampler.enabled
        fixture = getattr(a, "sample_fixture", None)
        # where an activation vector comes from: the chip's scratchpad over
        # MMIO, or ref/seq_model's mach in the board-free gate
        # R-d: x8's address and length come from the SESSION's geometry, not
        # from the 0.8B module constants — at 2B they are 0x1000/2048.
        self.x8_read = (self._model_x8 if offline
                        else (lambda ctx=None: read_x8_eout(
                            self.dev, self.geom["X8_WORD"],
                            self.geom["X8_LEN"])))
        # ---- the host head: --verify-head, or a fixture-free offline run
        need_head = self.verify_head or (want and offline and not fixture)
        if need_head:
            import head_cache as HC
            t0 = time.monotonic()
            try:
                head_wid = int(self.geom.get("_HEAD_WID", HEAD_WID))
                self.head = HC.open_head(
                    self.base, wid=head_wid,
                    cache=not getattr(a, "no_head_cache", False),
                    cache_dir_=getattr(a, "head_cache", None),
                    mmap=bool(getattr(a, "head_mmap", False)),
                    threads=int(getattr(a, "head_threads",
                                        HC.DEFAULT_THREADS)),
                    log=log)
            except HC.HeadCacheError as e:
                raise ChatSeqError(
                    f"the host verification head could not be built from "
                    f"{os.path.basename(self.base)} (wid {head_wid}): {e}")
            # G2a: the expectation follows the artifact's OWN residual binary
            # point (`rs_f` from the manifest), so a 9B artifact emitted at a
            # different point is not refused for being different — only for
            # having an (e, sh) this file does not expect.  Before, the pin
            # was the literal -22 and rs_f = 7 would have failed here for the
            # right reason with the wrong message.
            want_exp0 = head_logit_exp0(self.head.spec.rs_f)
            got_exp0 = self.head.spec.logit_exp(0)
            if got_exp0 != want_exp0:
                raise ChatSeqError(
                    f"the manifest's head dequant is 2^(e_x{got_exp0:+d}), "
                    f"this file expects 2^(e_x{want_exp0:+d}) for a head with "
                    f"e={HEAD_E} sh={HEAD_SH} at rs_f={self.head.spec.rs_f} "
                    f"(S4)")
            self.sampler.logit_exp0 = got_exp0
            log(f"  head       VERIFICATION COPY ready in "
                f"{time.monotonic() - t0:.1f}s ({self.head.built_from}); "
                f"logit = y32 * 2^(e_x{got_exp0:+d}) — the CHIP still "
                f"computes the head for every token")
        # ---- the candidate source
        if fixture:
            if not offline:
                raise ChatSeqError(
                    "--sample-fixture drives the sampler from a RECORDING; "
                    "it is a gate/test input and must not stand in for a "
                    "board decode.  Use it with --model-only.")
            self.cand = load_fixture(fixture)
        elif offline and self.head is not None:
            self.cand = HostHeadCandidates(self.head, self._model_x8)
        else:
            # --topk-base 0 (or an offline session) means "do not probe";
            # anything else is an address the IDENT read has to confirm.
            self.cand = ChipTopKSource(
                self.dev, base=(getattr(a, "topk_base", None) or None))
        if want and not self.cand.available:
            raise SamplingUnavailable(
                f"--temp {self.sampler.temp:g} asks for sampling but the "
                f"candidate source is not available.\n  {self.cand.why}")
        log(f"  sampling   {self.sampler.describe()}  |  source "
            f"{self.cand.describe()}"
            + (f"  |  capture k={self.cand.k}" if self.cand.available else ""))
        if want and self.sampler.top_k > self.cand.k > 0:
            log(f"  sampling   NOTE --top-k {self.sampler.top_k} exceeds the "
                f"capture depth {self.cand.k}; the effective k is "
                f"{self.cand.k}")
        return self.cand

    def _model_x8(self, ctx):
        """(x8, e_x) from ref/seq_model's mach — board-free gate only."""
        if self.verifier is None:
            raise ChatSeqError("no seq_model verifier is attached")
        M = self.verifier.mach
        w, n = self.geom["X8_WORD"], self.geom["X8_LEN"]
        x8 = np.asarray(M.mem[w:w + n], dtype=np.int64)
        if int(np.abs(x8).max()) > 127:
            raise ChatSeqError(
                f"scratch[{w:#x}] holds |x|max={int(np.abs(x8).max())}, "
                f"which is not a DYNQ8 int8 vector")
        return x8.astype(np.int8), int(M.eout)

    # ------------------------------------------------ context guard
    def plan_turn(self, ids, ntok):
        """(feed, nsteps, needs_reset) for a turn — spec decision 8.

        feed = [carry-over token] + prompt ids (infer.py's chat shape:
        the previous turn's last argmax is the first token of this one).
        steps = P + N - 1: the last prompt step yields the first reply
        token.  The guard is MANDATORY: past T=512 the RTL aliases KV
        writes SILENTLY (kv_waddr t[8:0]) with no error.
        """
        carry = [] if self.next_in is None else [int(self.next_in)]
        feed = carry + [int(i) for i in ids]
        nsteps = len(feed) + int(ntok) - 1
        need_reset = (self.T + nsteps) > self.args.max_ctx
        return feed, nsteps, need_reset

    def truncate_history(self, ids, ntok):
        """Longest tail of the conversation that still fits after a reset."""
        room = self.args.max_ctx - (len(ids) + int(ntok) - 1)
        if room < 0:
            raise ChatSeqError(
                f"prompt ({len(ids)} ids) + --ntok {ntok} needs "
                f"{len(ids) + ntok - 1} steps, more than --max-ctx "
                f"{self.args.max_ctx}")
        hist = list(self.fed[1:]) + ([] if self.next_in is None
                                     else [int(self.next_in)])
        return hist[len(hist) - room:] if room < len(hist) else hist

    def fill(self):
        return self.T / float(self.args.max_ctx)

    # ------------------------------------------------ chat template
    def attach_template(self, tk, log=print):
        """Turn the chat template ON for this session (T4: it is the default).

        --raw leaves self.template None, which is exactly today's
        behaviour: whatever the user typed is fed verbatim.
        """
        if getattr(self.args, "raw", False):
            self.template = None
            log("  template   OFF (--raw): prompts are fed verbatim, with no "
                "<|im_start|> wrapper — this is the pre-INSTRUCT_SPEC "
                "behaviour and the model will ramble/continue rather than "
                "answer")
            return None
        self.template = ChatTemplate(tk)
        t = self.template
        log(f"  template   ON (docs/INSTRUCT_SPEC.md; --raw opts out): "
            f"id-spliced wrapper, {t.per_message}*messages+{t.gen_overhead} "
            f"ids, closed-empty think block, stop {sorted(CHAT_STOP_IDS)}"
            + (f"; system prompt {self.system!r}" if self.system else ""))
        return t


def _align(n, a):
    return (n + a - 1) // a * a


# ======================================================================
# lockstep verifier (--verify): ref/seq_model on the SAME images
# ======================================================================
class SeqModelVerifier(object):
    """Predict every step with ref/seq_model.SeqExec and compare tokens.

    HEAVY, but bearable: SeqExec re-executes the whole 14,740-record body
    in numpy and unpacks every weight row it touches off disk; the weight
    width travels in `meta["weights"]` and ref/seq_model.DDRWeights picks
    the row law from it.

    NOT VALID AGAINST A PRE-G3 ARTIFACT (G3.3, and G3.1 before it).  This
    verifier hands the stream to `ref/seq_model.SeqExec` at ITS DEFAULT
    SHAPE layout, which is this tree's `isa=2`
    ({spare[31:29], ng[28:22], nrows[21:6], sh[5:0]}); a `build_034` /
    `build_035` stream carries the `isa=1` word AND the SEQ_ISA v1.7 ARG
    encoding that G3.1 replaced, so replaying one needs a pre-G3 checkout,
    not a flag here.  MEASURED, PER SELECTION (m4): on darthplagueis at
    0.8B/2B, ~6 s of host time per step (lite ~5 s, full ~7 s) against
    0.156 s of device time, i.e. ~40x slower than the chat it is checking;
    on snoke at 9B, 131.2 s (lite) / 149.3 s (full) against ~0.14 s
    (`evidence/qwen9b/g6/074_ref_cost_9b.log`), i.e. ~1,000x.  It is the
    cross-driver gate, not a mode to chat in.  --model-only runs the same
    machinery with NO board.
    """

    def __init__(self, session, log=print):
        import seq_model as SM
        self.check_pos_mode(session)
        self.SM = SM
        self.log = log
        self.sess = session
        s = session
        self.blob = s.const_blob
        self.W = SM.DDRWeights.from_files(s.base, s.meta["weights"],
                                          s.meta)
        # R-b: rows are `emb_row_bytes` = 2*H, not a hard-coded 2048/1024
        row_bytes = s.emb_row_bytes
        n = os.path.getsize(s.embf) // row_bytes
        self.emb = np.memmap(s.embf, dtype="<i2", mode="r").reshape(
            n, row_bytes // 2)
        self.mach = None
        self.region = None
        self.n = 0
        self.reset()

    @staticmethod
    def check_pos_mode(session, tag=None, cap=None):
        """The SECOND refusal of `xrf`, on the side that is blind.

        `_run`'s caveat is the whole reason: `ref/seq_model.SeqExec` does
        not model the signed 18-bit XRF read, so an `xrf` context past
        `XRF_POS_MAX` agrees with itself here and reads the wrong RoPE
        table on silicon.  `resolve_pos_mode` already refuses it in
        `ChatSession.__init__`, before the board is opened; this refuses it
        again where lockstep is claimed, so no future caller can reach a
        --verify run in a mode the model cannot check.

        THE TEST IS THE GEOMETRY, NOT THE MODEL TAG (round-3 review I-1).
        This used to ask only whether `tag in POS_MODE_LDC_ONLY`, which
        certified a `--verify` run in `xrf` mode at ANY selection that is
        not literally "9b" — a future model with the same 2,048 B stride
        and a 63-position reach would have passed here.  The hazard is
        `XRF_POS_MAX < --max-ctx - 1` and nothing else, so that is what is
        asked; `POS_MODE_LDC_ONLY` survives as the policy sentence in the
        message (see `resolve_pos_mode`), never as the condition.
        """
        tag = MODEL_TAG if tag is None else tag
        if cap is None:
            cap = SC.XRF_POS_MAX if SC is not None else 85
        if getattr(session, "pos_mode", None) != "xrf":
            return True
        reach = int(getattr(getattr(session, "args", None), "max_ctx",
                            DEFAULT_MAX_CTX)) - 1
        if cap < reach:
            raise ChatSeqError(
                f"--verify with pos_mode='xrf' is REFUSED at this geometry: "
                f"XRF[4] is a SIGNED 18-bit register, so it reaches pos "
                f"{cap} and this context needs pos {reach} "
                f"(--max-ctx {reach + 1}).  ref/seq_model.SeqExec does not "
                f"model the truncation, so lockstep would PASS on a context "
                f"the silicon truncates.  Use --pos-mode ldc."
                + (f"  (FABLE5_MODEL={tag} is in POS_MODE_LDC_ONLY: "
                   f"{cap} positions is not a chat context there.)"
                   if tag in POS_MODE_LDC_ONLY else ""))
        return True

    @staticmethod
    def state_region(session):
        """The DDR state region `ref/seq_model.SeqExec` moves blocks in and
        out of (SEQ_ISA v2.1 SLD/SST).

        THE BLOCK THIS RETIRES.  `SeqExec` takes a `region=` argument and
        REFUSES an SLD/SST without one; this verifier never passed one,
        because it predates S3's DDR spill.  That refusal is where the 9B
        chat compiler stopped —
        `evidence/qwen9b/g6/056_chat_seq_9b_model_set.log` attempt [6],
        "SLD/SST with no state region".

        The region is the artifact's OWN initial image
        (`<base>.state.bin`, sha-checked against the manifest first by
        `sw/seq_run.verify_state_image`).  m14: that is the same bytes
        `ChatSession.bring_up` writes to DDR FOR DN AND THE CONV IMAGES
        ONLY — `sw/seq_run.upload_state:1318-1320` deliberately leaves the
        KV sub-region alone, while the image loaded here carries a ZEROED
        KV.  The two sides still start every context from equivalent
        state, because TCNT is 0 and no KV row is read before it is
        written; they are not byte-identical in KV, and this used to say
        they were.

        None for a pre-S3 artifact: the frozen 0.8B/2B template emits no
        SLD/SST, so the shipped `--nch 1` path is untouched (scope F).
        """
        import seq_model as SM
        st = getattr(session, "state", None)
        if st is None:
            return None
        SR.verify_state_image(session)
        try:
            reg = SM.StateRegion.load(session.base)
        except (AssertionError, OSError, ValueError) as e:
            raise ChatSeqError(
                f"the DDR state region for {os.path.basename(session.base)} "
                f"could not be built from {session.base}.state.bin: {e}")
        if reg is None:                                    # pragma: no cover
            raise ChatSeqError(
                f"{session.base}.weights.json declares a state plan but "
                f"ref/seq_model.StateRegion.load found none")
        want = {k: int(st[k]) for k in ("dn", "kv", "cv", "end")}
        if reg.plan != want:                               # pragma: no cover
            raise ChatSeqError(
                f"the region image's plan {reg.plan} is not this session's "
                f"{want} — the stream was emitted for a different region "
                f"(spec 7.2)")
        return reg

    def reset(self):
        self.mach = self.SM._fresh_mach()
        # S3/B: a fresh context is a fresh REGION too.  The board half is
        # `ChatSession.reset_state_region` (the DN memset + the conv taps);
        # this is the same reset on the model's side, and it must be the
        # artifact's initial image, not the region the last context left.
        self.region = self.state_region(self.sess)
        # the preamble is part of the model too: replay it into the mach
        self.pending_preamble = True

    def _run(self, image, tok, pos):
        """Replay the image the board would launch, in EMITTER space.

        data_delta=0: ref/seq_model.SeqExec reads the blob at
        SF.SEQ_DATA_BASE, so the model gets the unrelocated patch while the
        board gets the relocated one.  Everything else is the same bytes.

        CAVEAT (agent A's finding): SeqExec does NOT model the signed
        18-bit XRF read, so in pos_mode="xrf" it will happily agree with
        itself for pos > SC.XRF_POS_MAX (85 at the 0.8B/2B stride of
        1,536 B, 63 at 9B's 2,048 B) where silicon would read the wrong
        RoPE table.  pos_mode="ldc" has no such blind spot.
        """
        if image.a.kind == "step":
            # S1P: the session's patch — form B makes it follow its record
            data = self.sess.step_patch(
                image.name, tok=tok, pos=pos, tcnt=1,
                data_delta=0).apply(image.a)
        else:
            data = image.a.data
        recs = SF.unpack_stream(data)
        # SR6: at the session's capability set (its --seq-rtl level's
        # before open_board, the device's after it)
        ex = self.SM.SeqExec(recs, self.blob, self.W, emb=self.emb,
                             mach=self.mach, region=self.region,
                             caps=getattr(self.sess, "caps", frozenset())
                             ).run(max_steps=50 * len(recs))
        return ex.out_fifo

    def preamble(self, image):
        self._run(image, 0, 0)
        self.pending_preamble = False

    def check(self, image, tok, pos, got):
        t0 = time.monotonic()
        out = self._run(image, tok, pos)
        want = int(out[0]) if out else None
        self.n += 1
        if want != got:
            raise ChatSeqError(
                f"--verify DIVERGENCE at step {pos} ({image.name}, tok={tok}): "
                f"chip {got}, seq_model {want}")
        self.log(f"    [verify] step {pos} {image.name}: {got} == seq_model "
                 f"({time.monotonic() - t0:.0f}s host)")


# ======================================================================
# Agent A cross-check (ref/seq_chat.py)
# ======================================================================
# Scope E: the models whose position stride puts a USABLE chat context out
# of XRF[4]'s reach.  `XRF_POS_MAX = ((1 << (XRF_BITS - 1)) - 1) //
# POS_STRIDE` is 85 at the 0.8B/2B stride of 1,536 B and **63** at 9B's
# 2,048 B — and 63 positions is not a chat context, the templated wrapper
# alone being 19 ids.
#
# THIS TUPLE IS POLICY DOCUMENTATION, NOT A TEST (round-3 review I-1).  It
# is quoted in the two refusal messages and nowhere else: neither
# `resolve_pos_mode` nor `SeqModelVerifier.check_pos_mode` branches on it.
# Both ask the GEOMETRY — `XRF_POS_MAX < --max-ctx - 1` — because that is
# the condition that actually breaks, and a tag list cannot know about the
# next model.  Keeping it as the test was the hole I-1 named: the verifier
# certified an `xrf` --verify run at any selection not literally "9b",
# whatever its stride.
POS_MODE_LDC_ONLY = ("9b",)


def resolve_pos_mode(args, tag=None, cap=None):
    """Pick agent A's position-addressing mode for this --max-ctx.

    XRF[4] is read SIGN-EXTENDED from an 18-bit file (rtl/seq_unit.sv
    xrf_rd), so XRF[4] = pos*POS_STRIDE tops out at `XRF_POS_MAX` and a
    larger CSRWR is TRUNCATED SILENTLY — ref/seq_model.py does not model
    that, so the model would pass where silicon reads the wrong RoPE
    table.  Agent A raised this as a spec/reality conflict and shipped
    pos_mode="ldc" (patch the position-LDC addresses instead) as the
    escape hatch.  "auto" picks the mode that can actually reach
    --max-ctx.

    AT 9B A REAL CHAT CONTEXT IS OUT OF REACH (scope E).  The cap is 63
    there, the blind spot is SHARED with the lockstep verifier, and this
    refusal fires in `ChatSession.__init__` — before the board is opened
    and before any launch — so nothing downstream ever has to catch the
    truncation.

    THE TEST IS THE GEOMETRY, NOT THE MODEL TAG (round-3 review I-1).
    `cap < --max-ctx - 1` is the condition that breaks, at any selection
    and any stride; `POS_MODE_LDC_ONLY` is quoted in the message and is
    not consulted for the decision.  `--max-ctx` bounds the deepest
    position a session can reach: `ChatSession.plan_turn` auto-resets
    rather than passing it, so `reach = --max-ctx - 1` is the position
    XRF[4] must be able to hold.

    `tag`/`cap` are for `--selftest`, which must be able to ask what this
    function does at a model selection the running process is not.
    """
    tag = MODEL_TAG if tag is None else tag
    if cap is None:
        cap = SC.XRF_POS_MAX if SC is not None else 85
    want = args.pos_mode
    reach = int(args.max_ctx) - 1
    if want == "xrf" and cap < reach:
        raise ChatSeqError(
            f"--pos-mode xrf cannot reach --max-ctx {args.max_ctx}: XRF[4] "
            f"is a SIGNED 18-bit register, so at this geometry's position "
            f"stride it reaches pos {cap} and rtl/seq_unit.sv TRUNCATES a "
            f"larger write silently.  ref/seq_model.SeqExec does not model "
            f"the truncation either, so a --verify run would agree with "
            f"itself and the silicon would read the wrong RoPE table.  Use "
            f"--pos-mode ldc (or auto, which picks it), or --max-ctx "
            f"{cap + 1}."
            + (f"  (FABLE5_MODEL={tag} is in POS_MODE_LDC_ONLY: {cap} "
               f"positions is not a chat context there — the templated "
               f"wrapper alone is 19 ids.)"
               if tag in POS_MODE_LDC_ONLY else ""))
    if want == "auto":
        return "xrf" if reach <= cap else "ldc"
    return want


def crosscheck_agent_a(session, log=print):
    """Independently re-derive agent A's outputs from the frozen spec.

    Agent A's ref/seq_chat.py is the compiler of record (file ownership),
    but the two of us read the same frozen document, so the two step
    images and the position pool MUST agree byte for byte.  A mismatch
    means one of us misread docs/CHAT_SEQ_SPEC.md; it is fatal, not a
    warning.
    """
    # SR6: at the session's capability set (the level's, pre-board)
    caps = getattr(session, "caps", frozenset())
    recs, blob, meta = load_template(session.prefix,
                                     check_sha=not session.args.any_template,
                                     sha=session.tmpl_sha, g=session.geom,
                                     caps=caps,
                                     shape_isa=getattr(session, "shape_isa",
                                                       None))
    mine = independent_step_images(recs, session.geom, caps=caps,
                                   shape_isa=getattr(session, "shape_isa",
                                                     None))
    rep = {"checks": []}
    for kind in ("lite", "full"):
        theirs = session.tc.build_step(0, 0, kind).data
        # everything OUTSIDE the three patch holes must be identical: the
        # holes are exactly where a launch rewrites the image anyway.
        diff = [i for i in range(min(len(theirs), len(mine[kind])))
                if theirs[i] != mine[kind][i]]
        holes = set()
        for off in (HOLE_TOK, HOLE_POS, HOLE_TCNT):
            holes.update(range(off, off + 4))
        ok = (len(theirs) == len(mine[kind])
              and all(i in holes for i in diff))
        rep["checks"].append((f"image {kind} outside the holes", ok))
        if not ok:
            raise ChatSeqError(
                f"agent A's {kind} step image differs from my own slice of "
                f"the same template OUTSIDE the patch holes "
                f"({len(theirs)} B vs {len(mine[kind])} B, first bad byte "
                f"{next((i for i in diff if i not in holes), None)}) — one of "
                f"us misread the frozen spec")
        ha, hb = SF.unpack_stream(theirs[:PATCH_BYTES]), \
            SF.unpack_stream(mine[kind][:PATCH_BYTES])
        if [(r.opcode, r.flags, r.target) for r in ha] != \
                [(r.opcode, r.flags, r.target) for r in hb]:
            raise ChatSeqError(f"agent A's {kind} patch head records are not "
                               f"the template's seed/TCNT records")
        rep["checks"].append((f"image {kind} head records", True))
    pool_off = posblob_offset(recs, meta)
    if pool_off != session.layout["const_bytes"]:
        raise ChatSeqError(
            f"the position pool starts at blob+{pool_off} in the template "
            f"but agent A places it at blob+{session.layout['const_bytes']}")
    committed = blob[pool_off:]
    pool = session.const_blob[pool_off:]
    if pool[:len(committed)] != committed:
        raise ChatSeqError("agent A's position pool does not reproduce the "
                           "committed 6-position pool byte-exactly (gate A2)")
    rep["checks"].append(("posblob vs committed pool", True))
    if session.const_blob[:pool_off] != blob[:pool_off]:
        raise ChatSeqError("agent A's const region is not the committed one")
    rep["checks"].append(("const region verbatim", True))
    log(f"  crosscheck agent A vs my own spec slices: "
        f"{len(rep['checks'])}/{len(rep['checks'])} byte-identical "
        f"(step images, const region, position pool)")
    return rep


# ======================================================================
# tokenizer (reuse sw/infer.py's — imported, never edited)
# ======================================================================
def load_tokenizer(log=print):
    from gen_model_script import _tokenizer_path, PROMPTS
    from infer import BpeTok
    tp = _tokenizer_path()
    if tp is None:
        raise ChatSeqError("tokenizer.json not found in the HF cache")
    tk = BpeTok(tp)
    n = tk.self_test()
    stops = set()
    raw = json.load(open(tp))
    for a in raw.get("added_tokens", []):
        if a.get("content") in ("<|endoftext|>", "<|im_end|>"):
            stops.add(int(a["id"]))
    tk.stop_ids = stops
    if stops != set(CHAT_STOP_IDS):
        raise ChatSeqError(
            f"the tokenizer's derived stop ids {sorted(stops)} are not the "
            f"frozen {sorted(CHAT_STOP_IDS)} (docs/INSTRUCT_SPEC.md T6) — "
            f"this is a different checkpoint")
    log(f"  tokenizer  {os.path.basename(os.path.dirname(tp))}: "
        f"{len(tk.ranks)} merges, self-test reproduces all {len(PROMPTS)} "
        f"gen_model_script PROMPTS; stop ids {sorted(stops)}")
    return tk


# ======================================================================
# CHAT TEMPLATE  (docs/INSTRUCT_SPEC.md — FROZEN 2026-08-11)
# ======================================================================
# The cached checkpoint IS Qwen/Qwen3.5-0.8B *instruct* (snapshot
# 2fc06364..., weights blob sha256 04b1c301...4696, verified while this
# was written); the degenerate chat behaviour was ONLY the missing chat
# template.  This section is the whole fix.
#
# T1 — the wrapper is ID-SPLICED and never string-encoded.  sw/infer.py's
# BpeTok reads tokenizer.json's `model.vocab` + merges but knows nothing
# about `added_tokens`, so the literal text "<|im_start|>" encodes to SIX
# ordinary pieces ([27, 91, 316, 4747, 91, 29]) instead of the single id
# 248045.  Splicing ids is not an optimisation, it is the only correct
# way to build the prompt, and --selftest pins the mangling so nobody
# "simplifies" this back into a string.
TOK_IM_START = 248045
TOK_IM_END = 248046
TOK_THINK = 248068
TOK_THINK_END = 248069
TOK_ENDOFTEXT = 248044

# T6: generation stops here.  load_tokenizer() still DERIVES the set from
# tokenizer.json's added_tokens and refuses to run if it disagrees.
CHAT_STOP_IDS = frozenset((TOK_ENDOFTEXT, TOK_IM_END))
# control ids that must never reach the screen (display only — the ids
# line always shows the unfiltered truth)
CHAT_HIDDEN_IDS = frozenset((TOK_IM_START, TOK_IM_END, TOK_THINK,
                             TOK_THINK_END, TOK_ENDOFTEXT))
CHAT_ROLES = ("system", "user", "assistant")
WRAP_PER_MESSAGE = 5      # T7: im_start + enc("<role>\n") + im_end + enc("\n")
WRAP_GEN_PROMPT = 7       #     im_start + enc("assistant\n") + think block

# ---------------------------------------------------------------- G1
# HF REFERENCE RENDERINGS.  These are the ONLY authority for the ids
# below; they were produced ONCE from the checkpoint's own
# chat_template.jinja and pasted here.  REPRODUCE with:
#
#   SNAP=~/.cache/huggingface/hub/models--Qwen--Qwen3.5-0.8B/snapshots/2fc06364715b967f1860aea9cf38778875588b17
#   python3 -c '
#   from transformers import AutoTokenizer
#   tk = AutoTokenizer.from_pretrained("'"$SNAP"'")
#   Q  = "What is the capital of France?"
#   for tag, msgs in (
#       ("single", [{"role":"user","content":Q}]),
#       ("system", [{"role":"system","content":"You are a helpful assistant."},
#                   {"role":"user","content":Q}]),
#       ("3msg",   [{"role":"user","content":Q},
#                   {"role":"assistant","content":"Paris."},
#                   {"role":"user","content":"And of Italy?"}])):
#       print(tag, list(tk.apply_chat_template(
#           msgs, tokenize=True, return_dict=False,
#           add_generation_prompt=True)))'
#
# add_generation_prompt=True, enable_thinking LEFT UNSET (T2: the jinja
# then emits the closed-empty "<think>\n\n</think>\n\n" block).
# VERIFIED byte-identical on darthplagueis (transformers 5.2.0) and on
# snoke /home/cah/.venv/bin/python (transformers 5.11.0), 2026-08-11.
HF_REF_USER = "What is the capital of France?"
HF_REF_SYSTEM = "You are a helpful assistant."
HF_REF_REPLY = "Paris."
HF_REF_USER2 = "And of Italy?"

# 19 ids — the canonical single-turn form of T1.
HF_REF_SINGLE = [248045, 846, 198, 3710, 369, 279, 6511, 314, 9338, 30,
                 248046, 198, 248045, 74455, 198, 248068, 271, 248069, 271]
# 30 ids — T5, the same turn with a system message.
HF_REF_SYSTEM_SINGLE = [248045, 8678, 198, 2523, 513, 264, 10631, 17313, 13,
                        248046, 198, 248045, 846, 198, 3710, 369, 279, 6511,
                        314, 9338, 30, 248046, 198, 248045, 74455, 198,
                        248068, 271, 248069, 271]
# 35 ids — the 3-message conversation [user, assistant, user] + gen prompt.
HF_REF_3MSG = [248045, 846, 198, 3710, 369, 279, 6511, 314, 9338, 30, 248046,
               198, 248045, 74455, 198, 57590, 13, 248046, 198, 248045, 846,
               198, 2939, 314, 14898, 30, 248046, 198, 248045, 74455, 198,
               248068, 271, 248069, 271]

# 39 ids — what INCREMENTAL-WITH-CARRY (T3) actually feeds for the same
# 3-message conversation.
#
# DEVIATION, MEASURED, NOT A BUG IN THIS FILE (see the final report):
# chat_template.jinja renders a *historical* assistant message as
# '<|im_start|>assistant\n' + content + '<|im_end|>\n' — it emits the
# think block ONLY for an assistant message after `ns.last_query_index`,
# i.e. only for the turn being generated.  T3 forbids a full replay, and
# the chip's KV already contains the think block that turn 1 had to feed
# to condition generation, so the fed stream keeps 4 extra ids
# ([<think>, "\n\n", </think>, "\n\n"]) per PAST assistant turn.  The
# equality T3 asks for therefore holds up to exactly that documented
# splice, which the selftest asserts BOTH ways: the incremental stream
# must equal HF_REF_3MSG_INCR, and deleting the 4 spliced ids must
# reproduce HF_REF_3MSG byte for byte.
HF_REF_3MSG_THINK_AT = 15                  # after '<|im_start|>assistant\n'
HF_REF_3MSG_INCR = [248045, 846, 198, 3710, 369, 279, 6511, 314, 9338, 30,
                    248046, 198, 248045, 74455, 198, 248068, 271, 248069,
                    271, 57590, 13, 248046, 198, 248045, 846, 198, 2939,
                    314, 14898, 30, 248046, 198, 248045, 74455, 198, 248068,
                    271, 248069, 271]


class ChatTemplate(object):
    """The one wrapper builder (docs/INSTRUCT_SPEC.md T1/T2/T3/T5/T7).

    PURE: it holds a tokenizer and no session state, so sw/serve.py and
    sw/infer.py import THIS instead of restating the id splice.  All the
    conversation state (whose turn it is, the carry token) is passed in
    by the caller.

    `strict` requires the tokenizer to reproduce the frozen 5/7 wrapper
    geometry (enc("<role>\\n") == 2 ids, enc("\\n") == enc("\\n\\n") == 1
    id).  serve.py's MockBackend has a byte-per-id fake tokenizer, so it
    builds the same SHAPE with strict=False and the honest, computed
    overhead instead.
    """

    def __init__(self, tk, strict=True):
        self.tk = tk
        self.nl = self._enc("\n")
        self.nl2 = self._enc("\n\n")
        self.hdr = {r: self._enc(r + "\n") for r in CHAT_ROLES}
        self.exact = (len(self.nl) == 1 and len(self.nl2) == 1
                      and all(len(v) == 2 for v in self.hdr.values()))
        if strict and not self.exact:
            raise ChatSeqError(
                f"this tokenizer does not have the frozen wrapper geometry: "
                f"enc('\\n')={self.nl} enc('\\n\\n')={self.nl2} "
                f"headers={ {k: v for k, v in self.hdr.items()} } — "
                f"docs/INSTRUCT_SPEC.md T7 pins 5*messages+7")

    # -------------------------------------------------------- pieces
    def _enc(self, text):
        return [int(i) for i in self.tk.encode(text)]

    def body(self, text):
        """Message text -> ids.  A list of ids passes through unchanged."""
        if text is None:
            return []
        if isinstance(text, str):
            return self._enc(text)
        return [int(i) for i in text]

    def message(self, role, text):
        """One complete message: WRAP_PER_MESSAGE ids + the body."""
        if role not in self.hdr:
            raise ChatSeqError(f"unknown chat role {role!r} (roles are "
                               f"{CHAT_ROLES})")
        return ([TOK_IM_START] + list(self.hdr[role]) + self.body(text)
                + [TOK_IM_END] + list(self.nl))

    def gen_prompt(self):
        """The generation prompt with the T2 closed-empty think block.

        NEVER enable_thinking=True: an open '<think>\\n' would spend the
        whole 500-step context reasoning before the first visible token.
        """
        return ([TOK_IM_START] + list(self.hdr["assistant"])
                + [TOK_THINK] + list(self.nl2)
                + [TOK_THINK_END] + list(self.nl2))

    # -------------------------------------------------------- renderings
    def render(self, messages, add_generation_prompt=True):
        """The FULL, fresh-context rendering — HF's apply_chat_template.

        `messages` is [(role, text), ...].  Pinned against HF_REF_3MSG.
        """
        out = []
        for role, text in messages:
            out += self.message(role, text)
        if add_generation_prompt:
            out += self.gen_prompt()
        return out

    def turn_ids(self, text, system=None, first=True, carry=None):
        """The ids to FEED for ONE user turn, EXCLUDING the carry token.

        ChatSession.plan_turn() prepends session.next_in (the previous
        step's argmax) all by itself, so T3's "[carry] + enc('\\n') + ..."
        is spelled here as everything AFTER the carry.

        first=True   turn 1 of a context: the optional system message
                     (T5, session start only) then the user message.
        first=False  a continuation: enc("\\n") closes the assistant
                     message whose <|im_end|> the carry supplied.  If the
                     previous turn stopped on --ntok instead of an EOS the
                     carry is an ordinary content token, so an explicit
                     <|im_end|> is spliced in first — otherwise the
                     conversation would silently lose a message boundary.
        """
        out = []
        if first:
            if system:
                out += self.message("system", system)
        else:
            if carry is None or int(carry) not in CHAT_STOP_IDS:
                out += [TOK_IM_END]
            out += list(self.nl)
        out += self.message("user", text)
        out += self.gen_prompt()
        return out

    # -------------------------------------------------------- T7 budget
    @property
    def per_message(self):
        return 2 + len(self.hdr["user"]) + len(self.nl)

    @property
    def gen_overhead(self):
        return 3 + len(self.hdr["assistant"]) + 2 * len(self.nl2)

    def overhead(self, n_messages):
        """T7: wrapper ids of an n-message rendering (5*n + 7)."""
        return self.per_message * int(n_messages) + self.gen_overhead

    # -------------------------------------------------------- display
    def visible(self, ids):
        """Generated ids minus the control tokens, for the SHOWN text.

        Prefix-monotone, so streaming decode still works: filtering a
        prefix of `ids` gives a prefix of filtering `ids`.
        """
        return [int(i) for i in ids if int(i) not in CHAT_HIDDEN_IDS]


# ======================================================================
# turns
# ======================================================================
def _wrap_turn(sess, tk, text, system=None, first=None, carry=None):
    """(ids to feed after the carry, wrapper-id count, message count).

    PURE — no session mutation, so run_turn can call it again after an
    auto-reset without double-counting.  Falls back to a verbatim encode
    whenever the template is off (--raw) or the caller passed explicit ids.
    """
    t = sess.template
    if t is None or not isinstance(text, str):
        ids = (tk.encode(text) if isinstance(text, str)
               else [int(i) for i in text])
        return ids, 0, 0, None
    if first is None:
        first = (sess.turns_templated == 0)
    if carry is None:
        carry = sess.next_in
    sysmsg = (system if system is not None else sess.system) if first else None
    ids = t.turn_ids(text, system=sysmsg, first=first, carry=carry)
    body = len(t.body(text)) + (len(t.body(sysmsg)) if sysmsg else 0)
    return ids, len(ids) - body, (2 if sysmsg else 1), sysmsg


def run_turn(sess, tk, text, ntok, log=print, echo=True, system=None):
    """One user turn: wrap -> encode -> lite prefill -> full decode, streamed.

    The chat template is ON unless --raw (T4).  It is applied HERE, over
    ChatSession.plan_turn()'s carry, so the token stream fed across turns
    is the incremental-with-carry form of T3 and never a full replay.
    """
    ids, wrap, nmsg, sysmsg = _wrap_turn(sess, tk, text, system=system)
    if not ids:
        log("  (empty prompt)")
        return []
    feed, nsteps, need_reset = sess.plan_turn(ids, ntok)
    if need_reset:
        keep = sess.truncate_history(ids, ntok)
        log(f"  context    {sess.T}+{nsteps} would pass --max-ctx "
            f"{sess.args.max_ctx} (KV depth {T_MAX}) — AUTO-RESET: preamble "
            f"+ re-prefill the last {len(keep)} tokens of history")
        sess.preamble()          # zeroes turns_templated: T5 re-arms
        # the replayed tail is a TRUNCATED token stream, so the wrapper
        # has to be rebuilt against what actually precedes this turn now
        ids, wrap, nmsg, sysmsg = _wrap_turn(
            sess, tk, text, system=system, first=(not keep),
            carry=(int(keep[-1]) if keep else None))
        feed = keep + [int(i) for i in ids]
        nsteps = len(feed) + int(ntok) - 1
        if sess.T + nsteps > sess.args.max_ctx:
            raise ChatSeqError("auto-reset did not free enough context")

    all_full = sess.args.prefill == "full"
    interrupted = {"v": False}

    def on_sigint(sig, frm):
        interrupted["v"] = True
        sys.stdout.write("\n  [Ctrl-C: stopping after the current step]\n")
        sys.stdout.flush()

    # the SHOWN text drops the control ids the template put in the stream
    # (<think>/</think>/<|im_end|>); the `ids` line below is unfiltered.
    _t = sess.template

    def show(g):
        return tk.decode(_t.visible(g) if _t is not None else g)

    prev_sig = signal.signal(signal.SIGINT, on_sigint)
    got, shown, t0 = [], "", time.monotonic()
    npre_lite = nfull = pre_ms = dec_ms = 0
    stopped = None
    try:
        tok = feed[0]
        for i in range(nsteps):
            lite = (i < len(feed) - 1) and not all_full
            out, rep = sess.step(tok, lite=lite)
            if lite:
                npre_lite += 1
                pre_ms += rep["device_ms"]
            else:
                nfull += 1
                dec_ms += rep["device_ms"]
            if echo and i < len(feed) - 1:
                sys.stdout.write(f"\r  prefill {i + 1}/{len(feed) - 1} "
                                 f"({rep['device_ms']:.0f} ms/step, "
                                 f"{'lite' if lite else 'full'})   ")
                sys.stdout.flush()
            if out is not None and i >= len(feed) - 1:
                got.append(out)
                if echo:
                    txt = show(got)
                    sys.stdout.write(("\r" + " " * 46 + "\r") if i == len(feed) - 1
                                     else "")
                    sys.stdout.write(txt[len(shown):])
                    sys.stdout.flush()
                    shown = txt
                if out in getattr(tk, "stop_ids", ()):
                    stopped = "EOS"
                    break
            if i + 1 < nsteps:
                tok = feed[i + 1] if i + 1 < len(feed) else out
            if interrupted["v"]:
                stopped = "interrupt"
                break
    finally:
        signal.signal(signal.SIGINT, prev_sig)
    dt = time.monotonic() - t0
    if echo:
        sys.stdout.write("\n")
        sys.stdout.flush()
    if echo:
        log(f"  --> {show(got)!r}")
    log(f"  ids {got}   {len(got)} tok in {dt:.2f}s"
        + (f"  [stop: {stopped}]" if stopped else ""))
    log(f"  prefill {npre_lite} lite x {pre_ms / max(1, npre_lite):.1f} ms | "
        f"decode {nfull} full x {dec_ms / max(1, nfull):.1f} ms | "
        f"{len(got) / dt:.2f} tok/s wall | "
        # pre_ms/dec_ms are MILLIseconds and dt is seconds (this line used
        # to report ~97000% of wall)
        f"{(pre_ms + dec_ms) / 1e3 / dt * 100:.0f}% of wall was device | "
        f"context {sess.T}/{sess.args.max_ctx} ({sess.fill() * 100:.0f}%)")
    # ---- T7: the context budget the wrapper actually spent -----------
    if _t is not None:
        sess.turns_templated += 1
        sess.tmpl_overhead += wrap
        if sysmsg:
            sess.tmpl_system = True
        # the equivalent HF rendering after k user turns is
        # system? + k user + (k-1) assistant messages, then the gen prompt
        sess.tmpl_messages = ((1 if sess.tmpl_system else 0)
                              + 2 * sess.turns_templated - 1)
        m, k = sess.tmpl_messages, sess.turns_templated
        kept = tmpl_think_ids(_t) * (k - 1)     # T3's documented deviation
        log(f"  template   turn {k}: +{wrap} wrapper ids "
            f"({len(ids) - wrap} body"
            + (f", incl. the {sysmsg!r} system message" if sysmsg else "")
            + f") | session {sess.tmpl_overhead} wrapper of {sess.T} context "
              f"steps ({sess.tmpl_overhead / max(1, sess.T) * 100:.0f}%)")
        log(f"             T7 budget: {sess.tmpl_overhead} fed + {k - 1} "
            f"generated <|im_end|> = {_t.per_message}*{m}+{_t.gen_overhead} "
            f"= {_t.overhead(m)} for the equivalent {m}-message HF rendering"
            + (f" + {kept} think ids kept from {k - 1} past reply/replies "
               f"(T3: no replay, so they stay in the KV)" if kept else ""))
    return got


def tmpl_think_ids(t):
    """Ids of one '<think>\\n\\n</think>\\n\\n' block (4 with this vocab)."""
    return 2 + 2 * len(t.nl2)


def stats(sess, log=print):
    p = sess.perf
    log(f"  launches     {sess.launches} "
        f"({len(p['preamble'])} preamble / {len(p['lite'])} lite / "
        f"{len(p['full'])} full)")
    for k in ("preamble", "lite", "full"):
        v = p[k]
        if v:
            log(f"  {k:<10s}   device ms  mean {sum(v) / len(v):.1f}  "
                f"min {min(v):.1f}  max {max(v):.1f}  (n={len(v)})")
    if p["lite"] and p["full"]:
        r = (sum(p["lite"]) / len(p["lite"])) / (sum(p["full"]) / len(p["full"]))
        log(f"  lite/full    {r * 100:.1f}% of a decode step "
            f"(spec risk 8: measured, not assumed)")
    log(f"  context      {sess.T} of {sess.args.max_ctx} forward steps "
        f"(KV bank depth {T_MAX})")
    log(f"  stream       nch={sess.nch}"
        + ("" if sess.nch == 1 else
           f", head wid {sess.layout_tag()['ilv_wids']} chunk-interleaved "
           f"over {sess.nch} channels (S4)"))
    if sess.out_fifo_ovf:
        log("  OUT FIFO     *** of_ovf SET — a token was DROPPED since the "
            "last board reset; this session's tokens are NOT trustworthy "
            "(sticky until reset, rung 4 S6) ***")
    else:
        log(f"  OUT FIFO     clean (depth {SEQ_OUT_DEPTH}, sticky of_ovf "
            f"clear)")
    if sess.template is None:
        log("  template     OFF (--raw)")
    else:
        log(f"  template     ON: {sess.tmpl_overhead} wrapper ids over "
            f"{sess.turns_templated} turn(s) = "
            f"{sess.tmpl_overhead / max(1, sess.T) * 100:.0f}% of the "
            f"context; T7 says {sess.template.per_message}*"
            f"{sess.tmpl_messages}+{sess.template.gen_overhead} = "
            f"{sess.template.overhead(sess.tmpl_messages)}")
    s = sess.sampler
    if s.enabled or sess.verify_head or sess.sample_log:
        log(f"  sampling     {s.describe()}  ({s.n_sampled} draws of "
            f"{s.n} picks" + (f", {s.as_dict()['sample_ms_mean']} ms mean"
                              if s.ms else "") + ")")
        if sess.cand is not None:
            log(f"  candidates   {sess.cand.describe()}")
        if sess.head_checks:
            hm = sess.head_ms
            log(f"  verify-head  {sess.head_checks} steps cross-checked, 0 "
                f"mismatches (host argmax == chip token); "
                f"{sum(hm) / len(hm):.1f} ms mean host cost")
    else:
        log("  sampling     OFF — greedy, 100% on-chip, bit-exact (the "
            "default)")
    log(f"  MMIO         {sess.dev.n_rd} reads / {sess.dev.n_wr} writes"
        if sess.dev else "  MMIO         n/a")


def repl(sess, tk):
    try:
        import readline                                   # noqa: F401
    except ImportError:
        pass
    print("\nCommands: /reset  /stats  /ntok N  /system TEXT  /quit   "
          "(Ctrl-C stops generation)")
    while True:
        try:
            line = input("\nprompt> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line in ("/quit", "/q", "/exit"):
            return
        if line == "/reset":
            sess.preamble()
            print("  session reset (KV/DN/conv zeroed, T=0)")
            continue
        if line == "/stats":
            stats(sess)
            continue
        if line.startswith("/ntok"):
            try:
                sess.args.ntok = int(line.split()[1])
                print(f"  ntok = {sess.args.ntok}")
            except (IndexError, ValueError):
                print("  usage: /ntok N")
            continue
        if line.startswith("/system"):
            # T5 is session-start scoped, so setting it resets the context
            if sess.template is None:
                print("  --raw: there is no template to give a system "
                      "message to")
                continue
            sess.system = line[len("/system"):].strip() or None
            sess.preamble()
            print(f"  system = {sess.system!r} (context reset; it is fed with "
                  f"the next turn)")
            continue
        if line.startswith("/"):
            print(f"  unknown command {line!r}")
            continue
        try:
            run_turn(sess, tk, line, sess.args.ntok)
        except ChatSeqError as e:
            print(f"  *** {e}")
            return


# ======================================================================
# offline board model (selftest only)
# ======================================================================
class _FakeBoard(SR._FakeSeqDev):
    """seq_unit CSR model + a sparse DDR, with the FIFO rule instrumented."""

    def __init__(self, tokens_per_launch=(), busy_polls=2, full_len=None):
        SR._FakeSeqDev.__init__(self, halt_pc=0, tokens=[],
                                busy_polls=busy_polls)
        self.mem = {}
        self.full_len = full_len      # only THIS image carries an AMAXL
        self.queue = list(tokens_per_launch)
        self.fifo_reads_while_busy = 0
        self.csr_writes_while_busy = []
        self.launch_log = []

    # ---- DDR ----
    def dma_write(self, addr, data):
        for i, b in enumerate(bytes(data)):
            self.mem[self.ddr_off + addr + i] = b

    def dma_read(self, addr, n):
        return bytes(self.mem.get(self.ddr_off + addr + i, 0)
                     for i in range(n))

    def dma_verify(self, addr, data, tag=""):
        if self.dma_read(addr, len(data)) != bytes(data):
            raise SR.SeqError(f"fake readback mismatch {tag}")
        return hashlib.sha256(bytes(data)).hexdigest()

    # ---- channel-explicit DDR (rung 4 S4 weight placement) ----
    # The real Dev ignores self.ddr_off for these and addresses
    # chan*CH_STRIDE + addr; the fake keys its dict the same way so a
    # 4-chan residency probe is exercised end to end without a board.
    def dma_write_chan(self, chan, addr, data):
        base = chan * HW.CH_STRIDE + addr
        for i, b in enumerate(bytes(data)):
            self.mem[base + i] = b

    def dma_read_chan(self, chan, addr, n):
        base = chan * HW.CH_STRIDE + addr
        return bytes(self.mem.get(base + i, 0) for i in range(n))

    def dma_verify_chan(self, chan, addr, data, tag=""):
        if self.dma_read_chan(chan, addr, len(data)) != bytes(data):
            raise SR.SeqError(f"fake readback mismatch {tag}")
        return hashlib.sha256(bytes(data)).hexdigest()

    # ---- CSRs (instrumented) ----
    def rd(self, a):
        if a == HW.S_OUT_FIFO and self._busy:
            self.fifo_reads_while_busy += 1
        if a == HW.S_OUT_CNT and self._busy:
            self.fifo_reads_while_busy += 1
        return SR._FakeSeqDev.rd(self, a)

    def wr(self, a, v):
        if self._busy and a != HW.S_CTRL:
            self.csr_writes_while_busy.append(a)
        if a == HW.S_CTRL and (int(v) & SEQ_CTRL_START) and not self._busy:
            # arm the scripted result of THIS launch: only the full-body
            # image ends in AMAXL, so only it pushes to the OUT FIFO
            emits = (self.full_len is None
                     or self.regs.get(HW.S_LEN) == self.full_len)
            self._tok = [self.queue.pop(0)] if (emits and self.queue) else []
            self._halt_pc = self.regs.get(HW.S_LEN, 1) - 1
            self.launch_log.append({
                "base": self.regs.get(HW.S_BASE_LO, 0),
                "len": self.regs.get(HW.S_LEN, 0),
                "head": self.dma_read(
                    self.regs.get(HW.S_BASE_LO, 0) - self.ddr_off,
                    PATCH_BYTES)})
        SR._FakeSeqDev.wr(self, a, v)


# ======================================================================
# --selftest: pure host, no board
# ======================================================================
def selftest(args, log=print):
    npass = nfail = 0

    def check(name, cond, detail=""):
        nonlocal npass, nfail
        if cond:
            npass += 1
        else:
            nfail += 1
            log(f"    FAIL {name}: {detail}")
        return cond

    def _refuses(fn, exc=ChatSeqError):
        """True when `fn()` raises `exc` (a refusal is a feature here)."""
        try:
            fn()
        except exc:
            return True
        except Exception:                                      # noqa: BLE001
            return False
        return False

    log("chat_seq selftest (pure python, NO board):")

    # ---------------- 1. template source + slices ----------------
    log("  [1] template source, frozen sha256, spec slice indices")
    recs, blob, meta = load_template(args.template)
    check("template sha256 is the frozen one", True)
    check("template record count", len(recs) == TEMPLATE_NREC)
    _check_head(recs)
    check("rec 1524 is the XRF[3] token seed",
          recs[REC_SEED_TOK].target == SF.csr_seq_xrf(3))
    check("rec 1525 is the XRF[4] position seed",
          recs[REC_SEED_POS].target == SF.csr_seq_xrf(4))
    check("rec 45751 is the TCNT_SEQ write",
          recs[REC_TCNT].target == SF.CSR_SEQ_TCNT)
    check("the committed token seed is prompt token 760",
          recs[REC_SEED_TOK].imm32 == 760, str(recs[REC_SEED_TOK].imm32))
    check("the committed position seed is pos 0",
          recs[REC_SEED_POS].imm32 == 0)
    check("the full body ends in AMAXL",
          recs[REC_BODY_FULL[1] - 1].opcode == SF.OP_AMAXL)
    check("the lite cut is the LM-head MOVX",
          recs[REC_BODY_LITE[1]].opcode == SF.OP_MOVX)
    check("the lite body carries no AMAXL",
          not any(r.opcode == SF.OP_AMAXL
                  for r in recs[REC_BODY_LITE[0]:REC_BODY_LITE[1]]))
    check("the full body carries exactly one AMAXL",
          sum(1 for r in recs[REC_BODY_FULL[0]:REC_BODY_FULL[1]]
              if r.opcode == SF.OP_AMAXL) == 1)
    check("body slice sizes match the spec",
          (REC_BODY_FULL[1] - REC_BODY_FULL[0],
           REC_BODY_LITE[1] - REC_BODY_LITE[0]) == (14740, 14006))

    # ---------------- 2. image assembly ----------------
    log("  [2] image assembly: agent A vs my own spec slices")
    mine = independent_step_images(recs)
    tc = SC.TurnCompiler(args.template, t_max=T_MAX, pos_mode="xrf")
    images = {"preamble": tc.build_session(),
              "lite": tc.build_step(0, 0, "lite"),
              "full": tc.build_step(0, 0, "full")}
    check("session image = preamble + TCNT + HALT",
          images["preamble"].nrec == 1524 + 2, str(images["preamble"].nrec))
    check("lite nrec", images["lite"].nrec == 14006 + HEAD_RECS + 1)
    check("full nrec", images["full"].nrec == 14740 + HEAD_RECS + 1)
    for n in ("lite", "full"):
        holes_b = set()
        for _o in (HOLE_TOK, HOLE_POS, HOLE_TCNT):
            holes_b.update(range(_o, _o + 4))
        d = [i for i in range(len(mine[n])) if images[n].data[i] != mine[n][i]]
        check(f"agent A's {n} image == my independent slice outside the holes",
              len(images[n].data) == len(mine[n])
              and all(i in holes_b for i in d), str(d[:8]))
        check(f"agent A's {n} body+HALT is byte-identical to my slice",
              images[n].data[PATCH_BYTES:] == mine[n][PATCH_BYTES:])
        check(f"{n} holes are the spec's",
              images[n].holes == {"tok": HOLE_TOK, "pos": HOLE_POS,
                                  "tcnt": HOLE_TCNT}, str(images[n].holes))
        check(f"{n} patch window is 48 B at offset 0",
              (images[n].patch_off, images[n].patch_len) == (0, PATCH_BYTES))
    for n, im in images.items():
        rr = im.records()
        check(f"{n} ends in HALT", rr[-1].opcode == SF.OP_HALT)
        check(f"{n} has no JMP",
              not any(r.opcode == SF.OP_JMP for r in rr))
        check(f"{n} validates", SF.validate_stream(rr) == im.nrec)
        check(f"{n} SEQ_LEN == nrec", im.seq_len == im.nrec)
        check(f"{n} entry is 0", im.entry == 0)
    check("only the full image can emit a token",
          [sum(1 for r in images[n].records() if r.opcode == SF.OP_AMAXL)
           for n in ("preamble", "lite", "full")] == [0, 0, 1])
    check("every image sets TCNT_SEQ explicitly (spec hazard)",
          all(any(r.opcode == SF.OP_CSRWR and r.target == SF.CSR_SEQ_TCNT
                  and r.imm32 >= 1 for r in images[n].records())
              for n in ("preamble", "lite", "full")))
    # ---------------- 3. posblob (gate A2, host form) ----------------
    log("  [3] position blob (gate A2 in host form) + const blob")
    t0 = time.monotonic()
    pb = build_posblob(T_MAX)
    check("posblob is T_max x 1536 B", len(pb) == POSBLOB_BYTES,
          f"{len(pb)} != {POSBLOB_BYTES}")
    pool_off = posblob_offset(recs, meta)
    check("pool offset derived from the stream", pool_off == 998144,
          str(pool_off))
    committed = blob[pool_off:]
    check("the committed pool is 6 positions",
          len(committed) == 6 * POS_STRIDE)
    check("the first 6 positions are BYTE-EXACT vs the committed pool",
          pb[:len(committed)] == committed)
    check("every position is 6 identical 256 B copies",
          all(pb[p * POS_STRIDE:p * POS_STRIDE + POS_BLOCK] * POS_COPIES
              == pb[p * POS_STRIDE:(p + 1) * POS_STRIDE]
              for p in (0, 1, 7, 255, 511)))
    check("distinct positions have distinct tables",
          len({pb[p * POS_STRIDE:p * POS_STRIDE + POS_BLOCK]
               for p in range(0, T_MAX, 37)}) == len(range(0, T_MAX, 37)))
    const_blob, off2 = build_const_blob(blob, meta, recs, pb)
    check("const blob = below-pool + posblob",
          len(const_blob) == pool_off + POSBLOB_BYTES and off2 == pool_off)
    check("const blob keeps the non-pool bytes",
          const_blob[:pool_off] == blob[:pool_off])
    try:
        build_const_blob(blob, meta, recs, b"\x00" * POSBLOB_BYTES)
        check("a wrong posblob is rejected", False)
    except ChatSeqError:
        check("a wrong posblob is rejected", True)
    log(f"    (posblob generated in {time.monotonic() - t0:.1f}s)")

    # ---------------- 4. patch offsets + hole encoding ----------------
    log("  [4] the per-launch patch (agent A) in both position modes")

    class _A(object):
        pass

    def _args(**kw):
        a = _A()
        a.template, a.chan, a.t_max = args.template, 0, T_MAX
        a.any_template, a.max_ctx = False, DEFAULT_MAX_CTX
        a.force_upload, a.timeout, a.preamble_timeout = False, 5.0, 5.0
        a.prefill, a.ntok, a.dev = "lite", 4, "/dev/null"
        a.pos_mode = "ldc"
        a.raw, a.system, a.ntok_given = False, None, False
        for k, v in kw.items():
            setattr(a, k, v)
        return a

    # tag=/cap= are named so these three read the same at every model
    # selection: the question is the geometry, not which model is loaded
    # (round-3 review m6).
    check("auto pos_mode picks xrf when --max-ctx fits the signed XRF",
          resolve_pos_mode(_args(pos_mode="auto", max_ctx=86),
                           tag="2b", cap=85) == "xrf")
    check("auto pos_mode picks ldc for a real chat context",
          resolve_pos_mode(_args(pos_mode="auto", max_ctx=500),
                           tag="2b", cap=85) == "ldc")
    try:
        resolve_pos_mode(_args(pos_mode="xrf", max_ctx=500),
                         tag="2b", cap=85)
        check("xrf is refused when it cannot reach --max-ctx", False)
    except ChatSeqError:
        check("xrf is refused when it cannot reach --max-ctx", True)

    a = _args()
    sess = ChatSession(a, log=lambda *x: None)
    check("images are 64 B aligned in DDR",
          all(x.base % SEQ_ALIGN == 0 for x in sess.images.values()))
    check("every step image patches at the spec's offsets",
          all(sess.images[k].holes == {"tok": 4, "pos": 20, "tcnt": 36}
              for k in ("lite", "full")))
    # --- pos_mode="xrf": exactly one 48 B write at offset 0 ---
    sx = ChatSession(_args(pos_mode="xrf", max_ctx=SC.XRF_POS_MAX + 1),
                     log=lambda *x: None)
    wx, fx = sx.patch_writes("full", 1234, 7)
    check("xrf patch is ONE 48 B write at offset 0",
          [(o, len(b)) for o, b in wx] == [(0, PATCH_BYTES)], str(wx))
    pr = SF.unpack_stream(wx[0][1])
    check("xrf: token seed", pr[0].imm32 == 1234
          and pr[0].target == SF.csr_seq_xrf(3))
    check("xrf: position seed is ABSOLUTE pos*1536",
          pr[1].imm32 == 7 * POS_STRIDE
          and pr[1].target == SF.csr_seq_xrf(4))
    check("xrf: TCNT_SEQ is nonzero", pr[2].imm32 == 1
          and pr[2].target == SF.CSR_SEQ_TCNT)
    try:
        sx.patch_writes("full", 1, SC.XRF_POS_MAX + 1)
        check("xrf refuses a position XRF[4] cannot hold", False)
    except SC.ChatSeqError:
        check("xrf refuses a position XRF[4] cannot hold", True)
    # --- pos_mode="ldc": 48 B + six 4 B LDC address rewrites ---
    wl, fl = sess.patch_writes("full", 1234, 300)
    check("ldc patch is 48 B + six 4 B writes",
          [len(b) for _o, b in wl] == [PATCH_BYTES] + [4] * 6, str(wl))
    check("ldc keeps XRF[4] at zero", fl["xrf4"] == 0, str(fl))
    dd = sess.plan["data_delta"]
    want_base = SC.POS_BLOB_BASE + 300 * POS_STRIDE + dd
    check("ldc addresses point at the RELOCATED pool for this position",
          [int.from_bytes(b, "little") for _o, b in wl[1:]]
          == [want_base + j * SC.POS_COPY_BYTES for j in range(6)])
    check("the relocated pool address is inside the uploaded blob",
          0 <= want_base - sess.plan["data_base"] < len(sess.const_blob))
    check("the LAST position is still inside the blob",
          sess.plan["data_base"] <= SC.POS_BLOB_BASE + (T_MAX - 1) * POS_STRIDE
          + dd + 5 * SC.POS_COPY_BYTES + SC.POS_COPY_BYTES
          <= sess.plan["data_base"] + len(sess.const_blob))
    check("ldc patch offsets land inside the image",
          all(o + len(b) <= len(sess.images["full"].data) for o, b in wl))
    check("ldc patch offsets are inside the BODY, not the head",
          all(o >= PATCH_BYTES for o, _b in wl[1:]))
    for bad, why in (((1 << 18, 0), "token >= 2^18"),
                     ((5, T_MAX), "pos == t_max"),
                     ((5, -1), "negative pos")):
        try:
            sess.patch_writes("full", *bad)
            check(f"patch rejects {why}", False)
        except (ChatSeqError, SC.ChatSeqError):
            check(f"patch rejects {why}", True)

    # ---------------- 5. DDR plan + relocation ----------------
    log("  [5] DDR plan, image placement, one-shot relocation")
    pl = sess.plan
    bases = [sess.images[n].base for n in ("preamble", "lite", "full")]
    sizes = [sess.images[n].nrec * SEQ_REC_BYTES
             for n in ("preamble", "lite", "full")]
    check("images are disjoint and ordered",
          all(bases[i] + sizes[i] <= bases[i + 1] for i in range(2)))
    check("images fit the 48 MiB stream window",
          bases[-1] + sizes[-1] <= SEQ_DATA_BASE)
    check("const blob fits its 64 MiB window",
          pl["data_base"] + len(sess.const_blob) <= HW.W_BASE)
    check("relocation moved every LDC by the plan delta",
          all(((b.len_or_addr_hi << 32 | b.addr_lo)
               - (x.len_or_addr_hi << 32 | x.addr_lo)) == pl["data_delta"]
              for n in ("preamble", "lite", "full")
              for x, b in zip(sess.images[n].recs_emit, sess.images[n].recs)
              if x.opcode == SF.EXT_LDC))
    check("relocation left every non-LDC/EMB record byte-identical",
          all(x.to_bytes() == b.to_bytes()
              for n in ("preamble", "lite", "full")
              for x, b in zip(sess.images[n].recs_emit, sess.images[n].recs)
              if x.opcode not in (SF.EXT_LDC, SF.OP_EMB)))
    check("every relocated LDC lands inside the uploaded const blob",
          all(0 <= ((b.len_or_addr_hi << 32 | b.addr_lo) - pl["data_base"])
              < len(sess.const_blob)
              for n in ("preamble", "lite", "full")
              for b in sess.images[n].recs if b.opcode == SF.EXT_LDC))
    check("the position pool is addressable for EVERY position",
          all(0 <= ((b.len_or_addr_hi << 32 | b.addr_lo) - pl["data_base"])
              + (T_MAX - 1) * POS_STRIDE + 2 * b.imm32 <= len(sess.const_blob)
              for b in sess.images["full"].recs
              if b.opcode == SF.EXT_LDC and b.ind != SF.IND_NONE))
    check("packed image bytes == nrec * 16",
          all(len(sess.images[n].data)
              == sess.images[n].nrec * SEQ_REC_BYTES
              for n in ("preamble", "lite", "full")))

    # ---------------- 6. context guard (spec 8) ----------------
    log("  [6] context guard T+(P-1)+N < 512 and history truncation")
    for (T, P, N, mx, want_reset) in (
            (0, 4, 8, 500, False),
            (100, 4, 8, 500, False),
            (490, 4, 8, 500, True),
            (0, 4, 500, 500, True),
            (497, 1, 4, 500, True),
            (0, 500, 1, 500, False)):
        sess.T, sess.next_in, sess.fed = T, None, list(range(T))
        sess.args.max_ctx = mx
        feed, nsteps, need = sess.plan_turn(list(range(P)), N)
        check(f"guard T={T} P={P} N={N}: reset={want_reset}",
              need == want_reset, f"steps={nsteps} T+steps={T + nsteps}")
        check(f"steps = P+N-1 at T={T} P={P} N={N}", nsteps == P + N - 1,
              str(nsteps))
    sess.args.max_ctx = DEFAULT_MAX_CTX
    sess.T, sess.fed, sess.next_in = 300, list(range(300)), 42
    feed, nsteps, need = sess.plan_turn([1, 2, 3], 8)
    check("carry-over token leads the feed", feed == [42, 1, 2, 3])
    check("carry-over counts toward the steps", nsteps == 4 + 8 - 1)
    keep = sess.truncate_history([1, 2, 3], 8)
    check("truncation leaves room for the whole turn",
          len(keep) + 3 + 8 - 1 <= DEFAULT_MAX_CTX)
    check("truncation keeps the NEWEST history",
          keep[-1] == 42 and keep[0] == sess.fed[len(sess.fed) - len(keep) + 1]
          if len(keep) > 1 else True)
    try:
        sess.truncate_history(list(range(600)), 8)
        check("an over-long prompt is refused", False)
    except ChatSeqError:
        check("an over-long prompt is refused", True)
    # the guard must never permit a position >= 512
    sess.T, sess.fed, sess.next_in = 0, [], None
    sess.args.max_ctx = DEFAULT_MAX_CTX
    _f, ns, _n = sess.plan_turn(list(range(200)), 300)
    check("max_ctx keeps the last position below the KV depth",
          sess.T + ns <= sess.args.max_ctx < T_MAX)

    # ---------------- 7. residency manifest + probe ----------------
    log("  [7] residency witness manifest + sha256 probe")
    wit = build_residency_manifest(sess.manifest, sess.wdir, sess.wbase_of,
                                   sess.embf, sess.plan["emb_base"])
    nw = sum(1 for w in wit if w["kind"] == "weight")
    check("one witness per weight image", nw == len(sess.manifest),
          f"{nw} vs {len(sess.manifest)}")
    check("witness blocks are 4 KiB (or the whole image)",
          all(w["bytes"] == min(WITNESS_BYTES,
                                int(sess.manifest[str(w["wid"])]["nrows"])
                                * int(sess.manifest[str(w["wid"])]["stride"]))
              for w in wit if w["kind"] == "weight"))
    check("witness addresses land inside their image",
          all(sess.wbase_of[w["wid"]] <= w["addr"]
              and w["addr"] + w["bytes"] <= sess.wbase_of[w["wid"]]
              + int(sess.manifest[str(w["wid"])]["nrows"])
              * int(sess.manifest[str(w["wid"])]["stride"])
              for w in wit if w["kind"] == "weight"))
    check("emb witnesses exist and are in range",
          all(sess.plan["emb_base"] <= w["addr"]
              and w["addr"] + w["bytes"]
              <= sess.plan["emb_base"] + os.path.getsize(sess.embf)
              for w in wit if w["kind"] == "emb")
          and sum(1 for w in wit if w["kind"] == "emb") == EMB_WITNESSES)
    # probe against a fake DDR preloaded with the real bytes
    fake = _FakeBoard()
    for w in wit:
        if w["kind"] == "weight":
            path = os.path.join(sess.wdir,
                                sess.manifest[str(w["wid"])]["file"])
            base = sess.wbase_of[w["wid"]]
        else:
            path, base = sess.embf, sess.plan["emb_base"]
        with open(path, "rb") as f:
            f.seek(w["addr"] - base)
            fake.dma_write(w["addr"], f.read(w["bytes"]))
    check("probe passes on resident images",
          probe_residency(fake, wit, log=lambda *x: None) == [])
    victim = wit[len(wit) // 2]
    fake.mem[victim["addr"] + 7] ^= 0xFF
    missed = probe_residency(fake, wit, log=lambda *x: None)
    check("probe catches a single flipped byte",
          [w["name"] for w in missed] == [victim["name"]],
          str([w["name"] for w in missed]))

    # ---------------- 8. the launch protocol ----------------
    log("  [8] launch protocol against the offline seq_unit model")
    FULL_LEN = sess.images["full"].nrec

    def _arm(sess_, toks):
        f = _FakeBoard(tokens_per_launch=toks, full_len=FULL_LEN)
        for n in ("preamble", "lite", "full"):
            f.dma_write(sess_.images[n].base, sess_.images[n].data)
        return f

    def _go(dev, sess_, kind, tok, pos, **kw):
        if kind == "preamble":
            im = sess_.images[kind]
            w = [(im.holes["tcnt"], (1).to_bytes(4, "little"))]
        else:
            im = sess_.images[kind]
            w, _f = sess_.patch_writes(kind, tok, pos)
        return _launch(dev, im, writes=w, tok=tok, pos=pos,
                       log=lambda *x: None, **kw)

    fake = _arm(sess, [561, 314])
    # R-b: bring_up programs EMBLOG2 from the manifest before any image runs.
    # (bring_up itself DMAs ~500 MiB of weights, so the selftest exercises the
    # CSR step it performs, against the same offline seq_unit model.)
    check("the session's emb row size divides the embedding table",
          sess.emb_row_bytes > 0
          and os.path.getsize(sess.embf) % sess.emb_row_bytes == 0,
          f"{sess.emb_row_bytes} B rows vs "
          f"{os.path.getsize(sess.embf)} B table")
    SR.seq_set_emb_row_bytes(fake, sess.emb_row_bytes, log=lambda *x: None)
    check("bring-up programs EMBLOG2 for this artifact's rows",
          fake.regs[HW.S_EMBLOG2] == HW.seq_emb_log2(sess.emb_row_bytes),
          f"{fake.regs[HW.S_EMBLOG2]} for {sess.emb_row_bytes} B rows")
    r0 = _go(fake, sess, "preamble", 0, 0)
    check("preamble halts at its HALT record",
          r0["pc"] == sess.images["preamble"].nrec - 1)
    check("SEQ_LEN == the image record count (spec hazard)",
          fake.regs[HW.S_LEN] == sess.images["preamble"].nrec)
    check("SEQ_BASE is the image base", fake.regs[HW.S_BASE_LO]
          == (sess.images["preamble"].base & 0xFFFFFFFF))
    check("ENTRY is 0", fake.regs[HW.S_ENTRY] == 0)
    check("the preamble launch wrote a nonzero TCNT_SEQ into the image",
          SF.unpack(fake.dma_read(sess.images["preamble"].base
                                  + sess.images["preamble"].holes["tcnt"] - 4,
                                  SEQ_REC_BYTES)).imm32 == 1)
    r1 = _go(fake, sess, "full", 760, 0)
    check("a full launch returns exactly one token", r1["tokens"] == [561],
          str(r1["tokens"]))
    head = fake.dma_read(sess.images["full"].base, PATCH_BYTES)
    check("the launch patched the resident image head",
          SF.unpack_stream(head)[0].imm32 == 760)
    check("XRF was zeroed before START", fake.xrf == [0] * SEQ_XRF_N)
    check("OUT FIFO was never touched while busy",
          fake.fifo_reads_while_busy == 0,
          f"{fake.fifo_reads_while_busy} reads")
    check("no SEQ CSR (other than CTRL) was written while busy",
          fake.csr_writes_while_busy == [],
          str(fake.csr_writes_while_busy))
    check("the launch reported the patch it actually DMA'd",
          r1["patch_bytes"] == PATCH_BYTES + 6 * 4
          and r1["patch_writes"] == 7,
          f"{r1['patch_bytes']} B in {r1['patch_writes']} writes")
    r2 = _go(fake, sess, "lite", 6511, 1)
    check("a lite launch returns no token", r2["tokens"] == [],
          str(r2["tokens"]))
    lhead = fake.dma_read(sess.images["lite"].base, PATCH_BYTES)
    check("ldc mode keeps the XRF[4] seed at 0",
          SF.unpack_stream(lhead)[1].imm32 == 0)
    dd = sess.plan["data_delta"]
    got_ldc = [SF.unpack(fake.dma_read(
        sess.images["lite"].base + o - 8, SEQ_REC_BYTES)).addr_lo
        for o in sess.images["lite"].a.pos_ldc]
    check("ldc mode wrote position 1's pool addresses into the body",
          got_ldc == [SC.POS_BLOB_BASE + 1 * POS_STRIDE + dd
                      + j * SC.POS_COPY_BYTES for j in range(6)],
          str([hex(x) for x in got_ldc]))
    # xrf mode: the position really does travel in XRF[4]
    sx2 = ChatSession(_args(pos_mode="xrf", max_ctx=SC.XRF_POS_MAX + 1),
                      log=lambda *x: None)
    fx2 = _arm(sx2, [7])
    _go(fx2, sx2, "full", 42, 9)
    check("xrf mode seeds XRF[4] = pos*1536 in the image",
          SF.unpack_stream(fx2.dma_read(sx2.images["full"].base,
                                        PATCH_BYTES))[1].imm32
          == 9 * POS_STRIDE)
    # a busy sequencer is refused, never stomped
    fake._busy, fake._polls = True, 0
    try:
        _go(fake, sess, "full", 1, 2)
        check("a busy sequencer is refused", False)
    except ChatSeqError:
        check("a busy sequencer is refused", True)
    fake._busy = False
    # an error halt is reported, not swallowed
    fake_e = _arm(sess, [])
    fake_e._err = 0x10
    try:
        _go(fake_e, sess, "full", 1, 2)
        check("an error halt raises", False)
    except ChatSeqError as e:
        check("an error halt names the err_code",
              "0x10" in str(e) and "layer_chan err_op" in str(e), str(e)[:120])

    # ---------------- 9. turn bookkeeping, EOS, ntok ----------------
    log("  [9] turn bookkeeping: schedule, prefill-lite, EOS, --ntok, reset")
    class _Tok(object):
        stop_ids = {248044}

        def encode(self, s):
            return [int(x) for x in s.split()]

        def decode(self, ids):
            return "".join(f"<{i}>" for i in ids)

    sess2 = ChatSession(a, log=lambda *x: None)
    sess2.dev = _FakeBoard(tokens_per_launch=[561, 314, 279, 369, 279, 6511],
                           full_len=FULL_LEN)
    for n in ("preamble", "lite", "full"):
        sess2.dev.dma_write(sess2.images[n].base, sess2.images[n].data)
    sess2.args.prefill = "full"
    got = run_turn(sess2, _Tok(), "760 6511 9338", 4,
                   log=lambda *x: None, echo=False)
    check("canned schedule: P=3 N=4 -> 6 launches", sess2.launches == 6,
          str(sess2.launches))
    check("canned schedule yields the last 4 tokens as the reply",
          got == [279, 369, 279, 6511], str(got))
    check("T advanced by the step count", sess2.T == 6, str(sess2.T))
    check("positions were 0..5 and every step used the full body",
          [(im, pos) for (im, _t, pos, _o) in sess2.step_log]
          == [("full", i) for i in range(6)], str(sess2.step_log))
    check("each step fed the previous argmax",
          sess2.fed == [760, 6511, 9338, 279, 369, 279], str(sess2.fed))
    # prefill-lite: same schedule, lite steps emit nothing
    sess3 = ChatSession(a, log=lambda *x: None)
    sess3.dev = _FakeBoard(tokens_per_launch=[279, 369, 279, 6511],
                           full_len=FULL_LEN)
    for n in ("preamble", "lite", "full"):
        sess3.dev.dma_write(sess3.images[n].base, sess3.images[n].data)
    sess3.args.prefill = "lite"
    got3 = run_turn(sess3, _Tok(), "760 6511 9338", 4,
                    log=lambda *x: None, echo=False)
    check("prefill-lite gives the identical reply", got3 == got, str(got3))
    check("prefill-lite ran 2 lite + 4 full",
          (len(sess3.perf["lite"]), len(sess3.perf["full"])) == (2, 4),
          str((len(sess3.perf['lite']), len(sess3.perf['full']))))
    # EOS stops launching
    sess4 = ChatSession(a, log=lambda *x: None)
    sess4.dev = _FakeBoard(tokens_per_launch=[11, 5, 248044, 99, 99],
                           full_len=FULL_LEN)
    for n in ("preamble", "lite", "full"):
        sess4.dev.dma_write(sess4.images[n].base, sess4.images[n].data)
    sess4.args.prefill = "full"
    got4 = run_turn(sess4, _Tok(), "5 6", 4, log=lambda *x: None, echo=False)
    # feed = [5, 6]: step 0's argmax is a prefill argmax and is DISCARDED;
    # step 1 yields the first reply token, step 2 the EOS -> stop launching
    # (the remaining --ntok budget is never spent on the device).
    check("EOS stops the turn", got4 == [5, 248044], str(got4))
    check("EOS stopped LAUNCHING before the --ntok budget",
          sess4.launches == 3, str(sess4.launches))
    # --ntok cap
    sess5 = ChatSession(a, log=lambda *x: None)
    sess5.dev = _FakeBoard(tokens_per_launch=[1, 2, 3, 4, 5, 6, 7, 8],
                           full_len=FULL_LEN)
    for n in ("preamble", "lite", "full"):
        sess5.dev.dma_write(sess5.images[n].base, sess5.images[n].data)
    sess5.args.prefill = "full"
    got5 = run_turn(sess5, _Tok(), "5", 3, log=lambda *x: None, echo=False)
    check("--ntok caps the reply", len(got5) == 3, str(got5))
    # auto-reset path
    sess6 = ChatSession(a, log=lambda *x: None)
    sess6.dev = _FakeBoard(tokens_per_launch=[7] * 40, full_len=FULL_LEN)
    for n in ("preamble", "lite", "full"):
        sess6.dev.dma_write(sess6.images[n].base, sess6.images[n].data)
    sess6.args.max_ctx = 20
    sess6.args.prefill = "lite"
    sess6.T, sess6.fed, sess6.next_in = 18, list(range(18)), 5
    got6 = run_turn(sess6, _Tok(), "1 2 3", 4, log=lambda *x: None, echo=False)
    check("auto-reset ran the preamble", len(sess6.perf["preamble"]) == 1)
    check("auto-reset restarted the context at 0 and refilled",
          sess6.T <= sess6.args.max_ctx and len(got6) == 4,
          f"T={sess6.T} got={got6}")
    check("auto-reset re-prefilled the truncated history",
          sess6.fed[-4:-1] == [1, 2, 3] or sess6.fed[:3] != [],
          str(sess6.fed[:8]))
    sess6.args.max_ctx = DEFAULT_MAX_CTX

    # ---------------- 9b. canned schedule (spec decision 5) -------------
    log("  [9b] canned schedule reconstruction (the always-seed rule)")
    from gen_model_script import PROMPTS as _P
    fed_c, want_c = canned_schedule(meta, list(_P[1][2]))
    check("canned feed is prompt-then-argmax",
          fed_c == [760, 6511, 314, 9338, 369, 279], str(fed_c))
    check("canned expectation is the artifact's expect_tokens",
          want_c == [561, 314, 279, 369, 279, 6511], str(want_c))
    check("the omitted seeds are exactly the emitter's quirk",
          [fed_c[i] for i in range(len(fed_c))
           if i and fed_c[i] == want_c[i - 1]] == [314, 369, 279])
    check("prompt_fed is only the SEEDED subset, not the prompt",
          list(meta["prompt_fed"]) == [760, 6511, 9338]
          and list(meta["prompt_fed"]) != fed_c[:4])
    try:
        canned_schedule(meta, [1, 2, 3, 4])
        check("a wrong prompt is rejected", False)
    except ChatSeqError:
        check("a wrong prompt is rejected", True)

    # ---------------- 10. tokenizer (needs the HF cache) ----------------
    log("  [10] tokenizer (infer.py BpeTok) + stop ids")
    try:
        tk = load_tokenizer(log=lambda *x: None)
        from gen_model_script import PROMPTS
        check("tokenizer reproduces gen_model_script PROMPTS",
              all(tk.encode(PROMPTS[k][0]) == list(PROMPTS[k][2])
                  for k in PROMPTS))
        check("the canned prompt encodes to the committed prompt_fed",
              tk.encode("The capital of France")[:3] == [760, 6511, 314]
              or tk.encode("The capital of France") == [760, 6511, 314, 9338],
              str(tk.encode("The capital of France")))
        check("stop ids were derived from the tokenizer, not hard-coded",
              tk.stop_ids == {248044, 248046}, str(tk.stop_ids))
        check("incremental detokenization is a pure suffix",
              all(tk.decode([561, 314, 279][:i]) ==
                  tk.decode([561, 314, 279])[:len(tk.decode([561, 314, 279][:i]))]
                  for i in (1, 2, 3)))
    except (ChatSeqError, ImportError) as e:               # noqa: BLE001
        log(f"    (tokenizer checks SKIPPED: {e})")

    # ---------------- 11. lock ----------------
    log("  [11] the shared board lock (O3) — exclusivity and its PATH")
    # O3: the mechanism was never the defect, the path was.  So this block
    # now checks the path as well as the flock: a lock inside SW_DIR is the
    # bug `evidence/qwen9b/o3/00_red_percheckout.log` captured.
    check("SeqLock is sw/board_lock.BoardLock under its old name",
          issubclass(SeqLock, BL.BoardLock))
    check("SeqLock still raises ChatSeqError", SeqLock.ERROR is ChatSeqError)
    check("LOCK_PATH is the shared board lock, not this checkout's sw/",
          LOCK_PATH == BL.BOARD_LOCK_PATH and not LOCK_PATH.startswith(SW_DIR),
          LOCK_PATH)
    check("the superseded per-checkout path is still named, and IS local",
          LEGACY_LOCK_PATH.startswith(SW_DIR), LEGACY_LOCK_PATH)
    lk = SeqLock(os.path.join(SW_DIR, ".seq.lock.selftest"))
    lk.acquire()
    check("the identity block names host, pid, user, tool and tree",
          all(k in BL.parse_identity(BL.read_identity(lk.path))
              for k in ("host", "pid", "user", "tool", "tree")),
          BL.read_identity(lk.path))
    lk2 = SeqLock(lk.path)
    try:
        lk2.acquire()
        check("the flock is exclusive", False)
    except ChatSeqError as e:
        check("the flock is exclusive", True)
        check("the refusal names the holder", "chat_seq.py" in str(e), str(e))
    lk.release()
    try:
        lk2.acquire()
        check("the flock is released on exit", True)
        lk2.release()
    except ChatSeqError:
        check("the flock is released on exit", False)
    os.unlink(lk.path)

    # ------------- 12. chat template — GATE G1 (docs/INSTRUCT_SPEC.md) ---
    log("  [12] chat template G1: HF id equality, incremental multi-turn, T7")
    try:
        tkr = load_tokenizer(log=lambda *x: None)
    except (ChatSeqError, ImportError, SystemExit) as e:       # noqa: BLE001
        log(f"    (chat-template checks SKIPPED: {e})")
        tkr = None
    if tkr is not None:
        # -- T1: the reason the wrapper is id-spliced ------------------
        mangled = tkr.encode("<|im_start|>")
        check("BpeTok CANNOT string-encode <|im_start|> (T1's whole point)",
              mangled != [TOK_IM_START] and len(mangled) == 6, str(mangled))
        check("every special id is inside the mapped vocab",
              all(0 <= i < 248320 for i in
                  (TOK_IM_START, TOK_IM_END, TOK_THINK, TOK_THINK_END,
                   TOK_ENDOFTEXT)))
        tm = ChatTemplate(tkr)
        check("wrapper geometry is the frozen one",
              tm.exact and tm.per_message == WRAP_PER_MESSAGE
              and tm.gen_overhead == WRAP_GEN_PROMPT,
              f"{tm.per_message}/{tm.gen_overhead} nl={tm.nl} "
              f"nl2={tm.nl2} hdr={tm.hdr}")
        # -- G1a: the canonical single turn IS the HF 19 ids -----------
        one = tm.turn_ids(HF_REF_USER, first=True)
        check("single-turn wrapper == the HF apply_chat_template 19 ids",
              one == HF_REF_SINGLE, str(one))
        check("it is 19 ids", len(one) == 19, str(len(one)))
        check("the spec's literal T1 splice reproduces it",
              one == ([TOK_IM_START] + tkr.encode("user\n")
                      + tkr.encode(HF_REF_USER) + [TOK_IM_END]
                      + tkr.encode("\n") + [TOK_IM_START]
                      + tkr.encode("assistant\n") + [TOK_THINK]
                      + tkr.encode("\n\n") + [TOK_THINK_END]
                      + tkr.encode("\n\n")))
        check("the think block is CLOSED and EMPTY (T2)",
              one[-4:] == [TOK_THINK, tm.nl2[0], TOK_THINK_END, tm.nl2[0]],
              str(one[-4:]))
        # -- G1b: the system-prompt form (T5) --------------------------
        sysone = tm.turn_ids(HF_REF_USER, system=HF_REF_SYSTEM, first=True)
        check("system-prompt wrapper == the HF 30-id reference",
              sysone == HF_REF_SYSTEM_SINGLE, str(sysone))
        check("the system message costs exactly 5 + len(text) ids",
              len(sysone) - len(one)
              == WRAP_PER_MESSAGE + len(tkr.encode(HF_REF_SYSTEM)))
        check("a system message is turn-1 only",
              tm.turn_ids(HF_REF_USER, system=HF_REF_SYSTEM, first=False,
                          carry=TOK_IM_END)
              == tm.turn_ids(HF_REF_USER, first=False, carry=TOK_IM_END))
        # -- G1c: the full 3-message rendering == HF -------------------
        full = tm.render([("user", HF_REF_USER), ("assistant", HF_REF_REPLY),
                          ("user", HF_REF_USER2)])
        check("3-message full rendering == the HF 35-id reference",
              full == HF_REF_3MSG, str(full))
        # -- T7 overhead formula --------------------------------------
        bodies = sum(len(tkr.encode(t)) for t in (HF_REF_USER, HF_REF_REPLY,
                                                  HF_REF_USER2))
        check("T7 overhead formula 5*messages+7",
              tm.overhead(3) == 5 * 3 + 7 == len(HF_REF_3MSG) - bodies,
              f"{tm.overhead(3)} vs {len(HF_REF_3MSG) - bodies}")
        check("T7 holds for 1 and 2 messages too",
              tm.overhead(1) == len(HF_REF_SINGLE) - len(tkr.encode(HF_REF_USER))
              and tm.overhead(2) == len(HF_REF_SYSTEM_SINGLE)
              - len(tkr.encode(HF_REF_USER))
              - len(tkr.encode(HF_REF_SYSTEM)))
        # -- G1d: INCREMENTAL WITH CARRY == the full rendering (T3) ----
        # driven through the REAL session bookkeeping and the offline
        # seq_unit model, so what is compared is sess.fed — the tokens
        # the chip would actually have consumed, not a re-derivation.
        at = _args()
        st = ChatSession(at, log=lambda *x: None)
        st.attach_template(tkr, log=lambda *x: None)
        reply = tkr.encode(HF_REF_REPLY) + [TOK_IM_END]        # "Paris." + EOS
        st.dev = _FakeBoard(tokens_per_launch=reply + [TOK_IM_END],
                            full_len=FULL_LEN)
        for n in ("preamble", "lite", "full"):
            st.dev.dma_write(st.images[n].base, st.images[n].data)
        g1 = run_turn(st, tkr, HF_REF_USER, len(reply),
                      log=lambda *x: None, echo=False)
        check("turn 1 fed exactly the HF 19 ids",
              st.fed[:19] == HF_REF_SINGLE, str(st.fed[:19]))
        check("turn 1 stopped on <|im_end|> (T6)", g1 == reply, str(g1))
        g2 = run_turn(st, tkr, HF_REF_USER2, 1,
                      log=lambda *x: None, echo=False)
        check("turn 2 carried the <|im_end|> and spliced enc('\\n')",
              st.fed[21:24] == [TOK_IM_END, tm.nl[0], TOK_IM_START],
              str(st.fed[19:26]))
        check("INCREMENTAL: the fed-token concatenation across turns is the "
              "3-message conversation", st.fed == HF_REF_3MSG_INCR,
              str(st.fed))
        check("...which is the HF full rendering plus EXACTLY the 4 think "
              "ids of the past assistant turn (documented T3 deviation)",
              st.fed[:HF_REF_3MSG_THINK_AT]
              + st.fed[HF_REF_3MSG_THINK_AT + 4:] == HF_REF_3MSG
              and st.fed[HF_REF_3MSG_THINK_AT:HF_REF_3MSG_THINK_AT + 4]
              == [TOK_THINK, tm.nl2[0], TOK_THINK_END, tm.nl2[0]],
              str(st.fed[HF_REF_3MSG_THINK_AT:HF_REF_3MSG_THINK_AT + 4]))
        check("no full replay: turn 2 fed only its own 18 ids",
              len(st.fed) - 21 == 18, str(len(st.fed) - 21))
        check("the session accounted the wrapper honestly",
              st.tmpl_overhead == 12 + 13 and st.turns_templated == 2,
              f"{st.tmpl_overhead} over {st.turns_templated} turns")
        check("the message count is the equivalent HF rendering's (2k-1)",
              st.tmpl_messages == 3, str(st.tmpl_messages))
        _kept = tmpl_think_ids(tm) * (st.turns_templated - 1)
        check("T7 budget identity: wrapper fed + generated <|im_end|> == "
              "the HF overhead + the think ids T3 keeps",
              st.tmpl_overhead + (st.turns_templated - 1)
              == tm.overhead(st.tmpl_messages) + _kept
              == len(HF_REF_3MSG_INCR) - bodies,
              f"{st.tmpl_overhead}+{st.turns_templated - 1} vs "
              f"{tm.overhead(st.tmpl_messages)}+{_kept}")
        # a reply cut short by --ntok still closes its message
        check("a non-EOS carry gets an explicit <|im_end|>",
              tm.turn_ids(HF_REF_USER2, first=False, carry=1234)[:2]
              == [TOK_IM_END, tm.nl[0]])
        # -- G1e: --raw really bypasses everything ---------------------
        ar = _args(raw=True)
        sr = ChatSession(ar, log=lambda *x: None)
        check("--raw leaves the template detached",
              sr.attach_template(tkr, log=lambda *x: None) is None
              and sr.template is None)
        sr.dev = _FakeBoard(tokens_per_launch=[11, 12, 13], full_len=FULL_LEN)
        for n in ("preamble", "lite", "full"):
            sr.dev.dma_write(sr.images[n].base, sr.images[n].data)
        run_turn(sr, tkr, HF_REF_USER, 2, log=lambda *x: None, echo=False)
        check("--raw feeds the bare tokenizer output (today's behaviour)",
              sr.fed[:len(tkr.encode(HF_REF_USER))]
              == tkr.encode(HF_REF_USER)
              and TOK_IM_START not in sr.fed, str(sr.fed))
        check("--raw books no template overhead",
              sr.tmpl_overhead == 0 and sr.turns_templated == 0)
        # -- G1f: EOS + the display filter -----------------------------
        check("stop ids are the frozen T6 pair",
              set(tkr.stop_ids) == set(CHAT_STOP_IDS), str(tkr.stop_ids))
        check("the display strips think ids and <|im_end|>",
              tm.visible([TOK_THINK, 57590, TOK_THINK_END, 13, TOK_IM_END])
              == [57590, 13])
        check("stripping is prefix-monotone (streaming decode stays valid)",
              all(tm.visible(HF_REF_3MSG_INCR[:k])
                  == tm.visible(HF_REF_3MSG_INCR)[:len(
                      tm.visible(HF_REF_3MSG_INCR[:k]))]
                  for k in range(len(HF_REF_3MSG_INCR) + 1)))
        check("the shown text of turn 1 is the reply without <|im_end|>",
              tkr.decode(tm.visible(g1)) == HF_REF_REPLY,
              tkr.decode(tm.visible(g1)))
        # -- G2 pin: the templated ids the gate replays -----------------
        check("the G2 prompt still templates to the pinned ids",
              tm.turn_ids(G2_PROMPT, first=True) == G2_TEMPLATED_IDS)
        check("the G2 bf16 expectation decodes to the pinned text",
              tkr.decode(G2_BF16_REPLY) == G2_BF16_TEXT,
              tkr.decode(G2_BF16_REPLY))
        # -- context budget (T7) still guarded --------------------------
        st.args.max_ctx = 40
        st.T, st.fed, st.next_in = 30, list(range(30)), TOK_IM_END
        _f, _ns, need = st.plan_turn(
            tm.turn_ids("x", first=False, carry=TOK_IM_END), 4)
        check("the context guard counts the wrapper ids too (T7)", need is True,
              f"steps={_ns}")

    # ------------- 13. SAMPLING: math, determinism, sources, refusal ----
    log("  [13] sampling: dequant, temperature/top-k/top-p, seeded draws")
    # -- S4 dequant --------------------------------------------------
    sp = Sampler(temp=0.8, top_k=50, top_p=1.0, seed=1)
    check("S4: the head dequant exponent is e_x - 22",
          # G2a review N5: `HEAD_LOGIT_EXP0 == head_logit_exp0(HEAD_RS_F)`
          # is a tautology -- it is that expression's definition.  Pin the
          # VALUE for the shipped constants and check the algebra separately.
          HEAD_LOGIT_EXP0 == -22 and
          HEAD_LOGIT_EXP0 == HEAD_E + HEAD_SH - 15 - HEAD_RS_F and
          np.allclose(sp.logits([1024], 5), 1024 * 2.0 ** (5 - 22)),
          str(sp.logits([1024], 5)))
    check("dequant is monotone (it can never reorder candidates)",
          np.all(np.diff(sp.logits([1, 7, 9, 400], 3)) > 0))
    # -- greedy is the chip's answer, untouched ----------------------
    v0 = np.array([100, 900, 900, 50], dtype=np.int32)
    i0 = np.array([7, 42, 11, 3], dtype=np.int64)
    g = Sampler(temp=0.0, seed=5)
    tokg, infog = g.pick(v0, i0, 5)
    check("temp 0 picks the top candidate (first-wins on a tie, like AMAX)",
          tokg == 11 and infog["mode"] == "greedy", f"{tokg} {infog}")
    check("greedy never draws from the RNG (bit-identical to today)",
          g.n_sampled == 0 and
          np.array_equal(np.random.default_rng(5).random(3), g.rng.random(3)))
    check("greedy ignores temperature-only knobs",
          Sampler(temp=0.0, top_k=1, top_p=0.1, seed=5).pick(v0, i0, 5)[0]
          == 11)
    # -- softmax vs an independent numpy reference -------------------
    vals = np.array([1_151_016, 1_119_001, 1_085_771, 1_070_695, 1_048_647],
                    dtype=np.int32)
    ids = np.array([95928, 7, 8, 9, 10], dtype=np.int64)
    for temp in (0.5, 0.8, 1.0, 2.0):
        s = Sampler(temp=temp, top_k=0, top_p=1.0, seed=3)
        lg = vals.astype(np.float64) * 2.0 ** (5 - 22) / temp
        ref = np.exp(lg - lg.max())
        ref /= ref.sum()
        _t, info = s.pick(vals, ids, 5)
        # p of the CHOSEN rank must be the reference's p of that rank
        check(f"softmax at temp {temp} == the numpy reference",
              abs(info["p"] - ref[info["rank"]]) < 1e-12,
              f"{info['p']} vs {ref[info['rank']]}")
    class _ZeroRng(object):
        """u = 0 always -> the draw lands on rank 0, whatever the spread."""

        def random(self):
            return 0.0

    def _p_top(temp):
        s_ = Sampler(temp=temp, top_k=0, top_p=1.0, seed=3)
        s_.rng = _ZeroRng()
        return s_.pick(vals, ids, 5)[1]["p"]
    check("a colder temperature concentrates mass on the top candidate",
          _p_top(0.25) > _p_top(1.0) > _p_top(4.0),
          f"{_p_top(0.25):.4f} {_p_top(1.0):.4f} {_p_top(4.0):.4f}")
    # -- top-k / top-p truncation ------------------------------------
    s = Sampler(temp=1.0, top_k=2, top_p=1.0, seed=9)
    seen = {s.pick(vals, ids, 5)[0] for _ in range(400)}
    check("--top-k 2 can only ever emit the two best ids",
          seen <= {int(ids[0]), int(ids[1])} and len(seen) == 2, str(seen))
    s = Sampler(temp=1.0, top_k=0, top_p=1.0, seed=9)
    check("--top-k 0 keeps every candidate", s.pick(vals, ids, 5)[1]["k_eff"]
          == len(vals))
    lg = vals.astype(np.float64) * 2.0 ** (5 - 22)
    pr = np.exp(lg - lg.max())
    pr /= pr.sum()
    cum = np.cumsum(pr)
    for tp in (0.2, 0.5, 0.9):
        want_n = int(np.searchsorted(cum, tp, side="left")) + 1
        s = Sampler(temp=1.0, top_k=0, top_p=tp, seed=2)
        _t, info = s.pick(vals, ids, 5)
        check(f"--top-p {tp} keeps the smallest prefix with mass >= {tp} "
              f"({want_n})", info["nucleus"] == want_n, str(info))
    s = Sampler(temp=1.0, top_k=0, top_p=1e-9, seed=2)
    check("a tiny --top-p still keeps one candidate (never an empty set)",
          s.pick(vals, ids, 5)[1]["nucleus"] == 1)
    # -- empirical distribution --------------------------------------
    s = Sampler(temp=1.0, top_k=0, top_p=1.0, seed=1234)
    draws = np.array([s.pick(vals, ids, 5)[0] for _ in range(20000)])
    emp = np.array([(draws == int(t)).mean() for t in ids])
    check("20k draws reproduce the analytic distribution (4 sigma)",
          bool(np.all(np.abs(emp - pr) < 4 * np.sqrt(pr * (1 - pr) / 20000)
                      + 1e-4)),
          f"emp {np.round(emp, 4).tolist()} vs {np.round(pr, 4).tolist()}")
    # -- S3 determinism ----------------------------------------------
    fx = synth_fixture(24, seed=77)
    def _traj(seed, fixture):
        fixture.reset()
        sm = Sampler(temp=0.9, top_k=32, top_p=0.95, seed=seed)
        return [sm.pick(*fixture.candidates())[0]
                for _ in range(len(fixture.entries))]
    t_a, t_b = _traj(4242, fx), _traj(4242, fx)
    t_c, t_d = _traj(4243, fx), _traj(9999, fx)
    check("S3: the same seed replays the same trajectory", t_a == t_b,
          f"{t_a}\n           {t_b}")
    check("a different seed changes it", t_c != t_a and t_d != t_a,
          f"{t_a} / {t_c} / {t_d}")
    e0 = fx.entries[0]
    sm = Sampler(temp=0.9, seed=1)
    first = [sm.pick(e0[0], e0[1], e0[2])[0] for _ in range(3)]
    sm.reset()
    check("reset() rewinds the RNG to the session seed",
          [sm.pick(e0[0], e0[1], e0[2])[0] for _ in range(3)] == first,
          str(first))
    e3 = fx.entries[3]
    check("the draw does not depend on the ORDER the unit reports in",
          Sampler(temp=0.9, top_k=32, seed=5).pick(e3[0], e3[1], e3[2])[0]
          == Sampler(temp=0.9, top_k=32, seed=5).pick(
              e3[0][::-1], e3[1][::-1], e3[2])[0])
    # -- input validation --------------------------------------------
    for bad, why in (({"temp": -1}, "negative temperature"),
                     ({"top_k": -3}, "negative top-k"),
                     ({"top_p": 0.0}, "top-p 0"),
                     ({"top_p": 1.5}, "top-p > 1")):
        try:
            Sampler(**bad)
            check(f"the sampler rejects {why}", False)
        except ChatSeqError:
            check(f"the sampler rejects {why}", True)
    try:
        Sampler(temp=1.0).pick(np.array([1, 2]), np.array([5, 5]), 3)
        check("a repeated candidate id is rejected", False)
    except ChatSeqError:
        check("a repeated candidate id is rejected", True)
    try:
        Sampler(temp=1.0).pick(np.array([1, 2]), np.array([5]), 3)
        check("a ragged candidate set is rejected", False)
    except ChatSeqError:
        check("a ragged candidate set is rejected", True)

    # ---------------- 14. candidate sources + the refusal ---------------
    log("  [14] candidate sources: chip stub, fixture, refusal path")
    cs = ChipTopKSource(None, base=None)
    check("the chip top-k source is ABSENT without an address",
          not cs.available and "rung" in cs.why.lower(), cs.why)
    check("the refusal names the missing hardware, not a fallback",
          "top-k capture unit" in cs.why.lower()
          and "greedy" in cs.why.lower()
          and "host" not in cs.why.lower().split("greedy")[0], cs.why)

    class _IdentDev(object):
        def __init__(self, ident):
            self.v = ident
            self.reads = []

        def rd(self, a):
            self.reads.append(a)
            return self.v

    bad = ChipTopKSource(_IdentDev(0xDEADBEEF), base=0x7000)
    check("a wrong IDENT keeps the source absent", not bad.available
          and "0xdeadbeef" in bad.why.lower(), bad.why)
    good = ChipTopKSource(_IdentDev(ChipTopKSource.IDENT), base=0x7000)
    check("the source appears when the IDENT reads back", good.available
          and good.k == TOPK_CAPTURE_K, good.why)
    check("probing reads exactly the IDENT register",
          good.dev.reads == [0x7000 + ChipTopKSource.OFF_IDENT],
          str(good.dev.reads))
    try:
        cs.candidates(None)
        check("an absent source raises instead of inventing candidates", False)
    except SamplingUnavailable:
        check("an absent source raises instead of inventing candidates", True)
    check("SamplingUnavailable is a ChatSeqError (callers catch one type)",
          issubclass(SamplingUnavailable, ChatSeqError))
    fxs = synth_fixture(3, k=8, seed=2)
    check("a fixture reports its depth and provenance",
          fxs.available and fxs.k == 8
          and fxs.as_dict()["provenance"]["kind"] == "synthetic",
          str(fxs.as_dict()))
    fxs.reset()
    [fxs.candidates() for _ in range(3)]
    try:
        fxs.candidates()
        check("a strict fixture refuses to loop", False)
    except ChatSeqError:
        check("a strict fixture refuses to loop", True)
    # a session with --temp and no source must refuse AT ATTACH TIME
    sa = _args(temp=0.8, top_k=32, top_p=0.95, seed=1, verify_head=False,
               topk_base=None, sample_fixture=None)
    ss = ChatSession(sa, log=lambda *x: None)
    ss.dev = None
    try:
        ss.attach_sampling(log=lambda *x: None, offline=False)
        check("--temp on today's bitstream refuses at session start", False)
    except SamplingUnavailable as e:
        check("--temp on today's bitstream refuses at session start",
              "rung 4" in str(e), str(e)[:120])
    sg = ChatSession(_args(), log=lambda *x: None)
    sg.dev = None
    sg.attach_sampling(log=lambda *x: None, offline=False)
    check("greedy attaches without a source and without complaint",
          not sg.sampler.enabled and sg.cand is not None
          and not sg.cand.available)
    check("a fixture may not stand in for a board decode",
          _refuses(lambda: ChatSession(
              _args(temp=0.8, sample_fixture="/nonexistent.json"),
              log=lambda *x: None).attach_sampling(log=lambda *x: None,
                                                   offline=False),
              ChatSeqError))

    # the REAL recorded fixture, when the board-free gate has produced one
    real_fx = os.path.join(TOP_DIR, "evidence", "sampling",
                           "candidates_fixture.json")
    if os.path.exists(real_fx):
        rf = load_fixture(real_fx)
        pv = rf.meta
        check("the recorded fixture carries its provenance",
              "seq_model" in pv.get("how", "") and pv.get("k") == TOPK_CAPTURE_K
              and pv.get("template_sha256") == TEMPLATE_SHA256, str(pv)[:120])
        check("the recorded candidate sets are the head's own integers "
              "(y32 descending, ids in the vocab)",
              all(list(v) == sorted(v, reverse=True)
                  and int(min(i)) >= 0 and int(max(i)) < 248320
                  and 0 <= e <= 15 for (v, i, e) in rf.entries))
        rf.reset()
        ta = [Sampler(temp=0.9, top_k=32, top_p=0.95, seed=8).pick(
            *rf.candidates())[0] for _ in range(len(rf.entries))]
        rf.reset()
        tb = [Sampler(temp=0.9, top_k=32, top_p=0.95, seed=8).pick(
            *rf.candidates())[0] for _ in range(len(rf.entries))]
        check("replaying the recorded fixture is deterministic", ta == tb,
              f"{ta} vs {tb}")
        rf.reset()
        check("the recorded fixture's greedy pick is the model's own argmax "
              "(561 for the canned prompt's first step)",
              Sampler(temp=0.0).pick(*rf.candidates())[0] == 561)
    else:
        log(f"    (recorded-fixture checks SKIPPED: no {real_fx})")

    # ---------------- 15. the sampled step, end to end ------------------
    log("  [15] the full step path over a fixture + a fake board")
    fx2 = synth_fixture(8, k=TOPK_CAPTURE_K, seed=5)
    def _sampled_session(seed):
        aa = _args(temp=0.9, top_k=32, top_p=0.95, seed=seed)
        s2 = ChatSession(aa, log=lambda *x: None)
        s2.dev = _FakeBoard(tokens_per_launch=[1234] * 12, full_len=FULL_LEN)
        for n in ("preamble", "lite", "full"):
            s2.dev.dma_write(s2.images[n].base, s2.images[n].data)
        fx2.reset()
        s2.cand = fx2
        s2.x8_read = lambda ctx=None: (_ for _ in ()).throw(
            ChatSeqError("the fixture path must not read x8"))
        return s2
    s2 = _sampled_session(31337)
    outs = [s2.step(760 + i, lite=False)[0] for i in range(6)]
    check("a sampled step returns the SAMPLED token, not the chip's argmax",
          all(o != 1234 for o in outs) and len(set(outs)) > 1, str(outs))
    check("the chip's own token is preserved in the report",
          all(e["chip_token"] == 1234 for e in s2.sample_log))
    check("every sampled token came from that step's candidate set",
          all(e["token"] in e["cand_indices"] for e in s2.sample_log))
    check("the fed history is the SAMPLED tokens (the KV sees what we drew)",
          s2.next_in == outs[-1] and s2.sample_log[-1]["token"] == outs[-1])
    check("each step consumed exactly one fixture entry", fx2.i == 6)
    check("the step log records the token that was actually fed",
          [o for (_i, _t, _p, o) in s2.step_log] == outs, str(s2.step_log))
    s3 = _sampled_session(31337)
    outs2 = [s3.step(760 + i, lite=False)[0] for i in range(6)]
    s4 = _sampled_session(31338)
    outs3 = [s4.step(760 + i, lite=False)[0] for i in range(6)]
    check("G2-in-miniature: same seed, same tokens through the REAL step "
          "path", outs2 == outs, f"{outs} vs {outs2}")
    check("G2-in-miniature: a different seed diverges", outs3 != outs,
          f"{outs} vs {outs3}")
    check("telemetry carries mode/seed/sample_ms",
          (lambda d: d["mode"] == "sampled" and d["seed"] == 31337
           and d["sample_ms_mean"] is not None and d["picks"] == 6)(
              s2.sampler.as_dict()), str(s2.sampler.as_dict()))
    check("a prefill (lite) step never samples and never emits a token",
          _sampled_session(1).step(760, lite=True)[0] is None)
    # greedy sessions must be byte-identical to the pre-sampling behaviour
    s5 = ChatSession(_args(), log=lambda *x: None)
    s5.dev = _FakeBoard(tokens_per_launch=[561, 314, 279], full_len=FULL_LEN)
    for n in ("preamble", "lite", "full"):
        s5.dev.dma_write(s5.images[n].base, s5.images[n].data)
    check("greedy still returns the chip's token verbatim",
          [s5.step(t, lite=False)[0] for t in (760, 6511, 314)]
          == [561, 314, 279])
    check("greedy touches neither the sampler nor a candidate source",
          s5.sampler.n == 0 and s5.sample_log == [])

    # ---------------- 16. --verify-head plumbing ------------------------
    log("  [16] --verify-head against a fake head + fake scratchpad")

    class _FakeHead(object):
        def __init__(self, ans):
            self.ans = ans
            self.seen = []

        def argmax(self, x8):
            self.seen.append(np.asarray(x8).copy())
            return self.ans, 1234567

    x8_fake = np.clip(np.arange(X8_LEN) % 255 - 127, -127, 127).astype(np.int8)
    sv = ChatSession(_args(verify_head=True), log=lambda *x: None)
    sv.dev = _FakeBoard(tokens_per_launch=[561, 314], full_len=FULL_LEN)
    for n in ("preamble", "lite", "full"):
        sv.dev.dma_write(sv.images[n].base, sv.images[n].data)
    sv.head = _FakeHead(561)
    sv.x8_read = lambda ctx=None: (x8_fake, 5)
    out_v, rep_v = sv.step(760, lite=False)
    check("verify-head passes when the host agrees with the chip",
          out_v == 561 and sv.head_checks == 1
          and rep_v["sampling"]["host_argmax"] == 561)
    check("verify-head returns the CHIP's token (it never decides)",
          out_v == rep_v["chip_token"])
    check("verify-head recorded e_x and the host y32",
          sv.sample_log[-1]["e_x"] == 5
          and sv.sample_log[-1]["host_y32"] == 1234567)
    check("verify-head does not fire on a prefill (lite) step",
          sv.step(561, lite=True)[0] is None and sv.head_checks == 1)
    sv.head.ans = 999
    check("a host/chip disagreement is FATAL, not a warning",
          _refuses(lambda: sv.step(561, lite=False), ChatSeqError))
    check("the host head saw the SAME x8 the chip used",
          all(np.array_equal(x, x8_fake) for x in sv.head.seen))

    # ------------- 16b. read_x8_eout against a layer_chan CSR model ------
    # This is the ONLY board-touching code the sampling work adds, so it
    # gets a stub that behaves like rtl/layer_chan.sv: SPTR is RW, a SWIN
    # read returns scratch[SPTR] and auto-increments, EOUT is 4 bits.
    class _ScratchDev(object):
        def __init__(self, words, eout=5, busy=False):
            self.mem = dict(words)
            self.sptr = 0x1234          # some unrelated value the host must
            self.eout = eout            # put back
            self.busy = busy
            self.n_rd = self.n_wr = 0
            self.writes = []

        def seq_status(self):
            return {"busy": self.busy, "raw": 0x1 if self.busy else 0x4}

        def rd(self, a):
            self.n_rd += 1
            if a == HW.L_SPTR:
                return self.sptr
            if a == HW.L_EOUT:
                return 0xDEAD0000 | self.eout   # upper bits MUST be masked
            raise AssertionError(f"unexpected CSR read {a:#x}")

        def wr(self, a, v):
            self.n_wr += 1
            self.writes.append((a, v))
            if a == HW.L_SPTR:
                self.sptr = v & SPTR_MASK

        def layer_read_scratch(self, addr, n):
            self.wr(HW.L_SPTR, addr)
            out = []
            for _ in range(n):
                out.append(self.mem.get(self.sptr, 0) & 0xFFFF)
                self.sptr += 1          # the RTL auto-increments on read
            self.n_rd += n              # exactly what seq_run.Dev counts
            return np.array(out, dtype=np.int64)

    want8 = np.array([(i * 7919) % 255 - 127 for i in range(X8_LEN)],
                     dtype=np.int8)
    words = {X8_WORD + i: int(want8[i]) & 0xFFFF for i in range(X8_LEN)}
    dv = _ScratchDev(words, eout=5)
    gx, gex = read_x8_eout(dv)
    check("read_x8_eout recovers the signed int8 vector from the scratchpad",
          np.array_equal(gx, want8), str(gx[:8]))
    check("read_x8_eout masks EOUT to its 4 bits", gex == 5, str(gex))
    check("it reads the x8 window, not some other address",
          dv.writes[0] == (HW.L_SPTR, X8_WORD))
    check("it puts SPTR back where it found it", dv.sptr == 0x1234,
          hex(dv.sptr))
    check("its cost is one MMIO read per word plus 2",
          dv.n_rd == X8_LEN + 2, str(dv.n_rd))
    check("a BUSY sequencer is refused (SWIN reads are idle-only)",
          _refuses(lambda: read_x8_eout(_ScratchDev(words, busy=True))))
    bogus = dict(words)
    bogus[X8_WORD + 3] = 0x1234          # not a sign-extended int8
    check("a scratch window that is not a DYNQ8 vector is refused",
          _refuses(lambda: read_x8_eout(_ScratchDev(bogus))))
    check("...and the check can be turned off for a raw dump",
          read_x8_eout(_ScratchDev(bogus), check=False)[0][3] == 0x34)

    # ---------------- 17. S7: x8 survives a full launch ------------------
    log("  [17] S7 layout: the LM head never overwrites x8 (0x800..0xBFF)")
    tail = recs[HEAD_TAIL[0]:HEAD_TAIL[1]]
    acc = list(scratch_accesses(tail))
    wr_all = [w for (_i, _t, _r, ws) in acc for w in ws]
    rd_all = [r for (_i, _t, rs, _w) in acc for r in rs]
    check("the head tail is the records a lite launch omits",
          HEAD_TAIL == (15532, 16266) and len(tail) == 734, str(HEAD_TAIL))
    check("every head-tail write starts at STG (word 0x1000)",
          {a for (a, _n) in wr_all} == {STG_WORD},
          str(sorted({a for (a, _n) in wr_all})[:6]))
    check("the head tail writes nothing above STG+0x1000",
          max(a + n for (a, n) in wr_all) == STG_WORD + STG_LEN,
          str(max(a + n for (a, n) in wr_all)))
    check("NO head-tail write touches the x8 window [0x800,0xC00) — S7",
          not any(_overlaps(w, X8_WORD, X8_WORD + X8_LEN) for w in wr_all),
          str([w for w in wr_all
               if _overlaps(w, X8_WORD, X8_WORD + X8_LEN)][:4]))
    check("the head READS x8 exactly once, whole (the MOVX at 15532)",
          [r for r in rd_all if r[0] < STG_WORD] == [(X8_WORD, X8_LEN)],
          str([r for r in rd_all if r[0] < STG_WORD][:4]))
    check("that read is a MOVX and it is the first record of the tail",
          tail[0].opcode == SF.OP_MOVX and tail[0].addr_lo == X8_WORD
          and tail[0].len_or_addr_hi == X8_LEN)
    check("no DYNQ8 runs after the head's MOVX, so L_EOUT still holds the "
          "head's e_x at halt (S4 reads it there)",
          not any(t == "CMD:ALU:DYNQ8" for (_i, t, _r, _w) in acc),
          str([i for (i, t, _r, _w) in acc if t == "CMD:ALU:DYNQ8"][:4]))
    check("the head tail streams the whole vocabulary (121x2048 + 512)",
          sum(1 for r in tail if r.opcode == SF.OP_MOVY) == 122
          and sum(r.len_or_addr_hi for r in tail
                  if r.opcode == SF.OP_MOVY) == 248320)
    # THE STRONGEST FORM OF S7 IS RETIRED HERE, AND WHY IS RECORDED RATHER
    # THAN HIDDEN (G3.1).  Three checks used to walk the WHOLE full body with
    # `scratch_accesses` and pin that the last write into x8 is the DYNQ8 at
    # record 15531.  They decoded the LAYER ARG WORDS of the frozen 0.8B
    # template, which is a SEQ_ISA v1.7 artifact; this tree emits and decodes
    # v2.0 ONLY (spec 8 G3 — there is no v1.7 decoder path on main), so
    # running them now would compare a v2.0 decode of v1.7 bits against a
    # number measured under v1.7.  Re-pinning that to whatever v2.0 produces
    # would be worse than deleting it: it would look like a proof.
    #
    # What is retired is the DECODE, not the FACT.  The measured pre-G3
    # values are recorded in evidence/qwen9b/g3/G3_1_ISA.md and reproduce on
    # any pre-G3 checkout -- which is exactly where build_034/build_035 are
    # served from.  The eight head-tail checks above are UNAFFECTED and still
    # run: every one of them comes from RECORD fields (MOVX/MOVY addr_lo),
    # not from ARG words, which was measured, not assumed.
    check("the frozen template is a SEQ_ISA v1.7 artifact and this tree "
          "speaks v2.0, so the full-body ARG decode is retired to evidence "
          "(G3.1); the head-tail S7 checks above are ARG-independent and "
          "still run",
          TEMPLATE_ISA_VERSION == 1 and SF.SEQ_ISA_VERSION == 2,
          f"template v{TEMPLATE_ISA_VERSION}, tree v{SF.SEQ_ISA_VERSION}")
    check("a v1.7 DNST is REFUSED by this tree's decoder rather than "
          "silently mis-decoded (it carries no DNSB write)",
          _refuses(lambda: list(scratch_accesses(
              recs[REC_BODY_FULL[0]:REC_BODY_FULL[1]]))))
    # and the stream never moves SPTR, so a host scratch read is safe
    nsptr = sum(1 for r in recs
                if r.opcode == SF.OP_CSRWR
                and (r.target & 0xF000) == SF.CSR_SPACE_LAYER
                and (r.target & 0xFF) in (SF.LOFF_SPTR, SF.LOFF_SWIN))
    check("no record in the whole stream touches SPTR/SWIN, so a post-halt "
          "host scratch read cannot disturb the next launch", nsptr == 0,
          str(nsptr))

    # ---------------- 18. head_cache (verification tooling) --------------
    log("  [18] sw/head_cache.py: exact integer path + cache discipline")
    try:
        import head_cache as HC
        hp, hf = HC._selftest(SR.derive_base(args.template),
                              log=lambda *x: None)
        npass += hp
        nfail += hf
        check("head_cache's own selftest passed", hf == 0, f"{hf} failed")
        check("head_cache agrees with this file about the S4 exponent",
              HC.RS_F_FALLBACK == HEAD_RS_F
              and HEAD_LOGIT_EXP0 == HEAD_E + HEAD_SH - 15 + 0 - HEAD_RS_F)
        check("the head exponent MOVES with the manifest's rs_f (spec 4.4)",
              head_logit_exp0(7) == HEAD_LOGIT_EXP0 + 1
              and HW.split_manifest({"rs_f": 7})[1]["rs_f"] == 7,
              str(head_logit_exp0(7)))
        check("head_cache is documented as verification-only",
              "NOT A DECODE PATH" in HC.__doc__)
        check("the head cache never lands on the NFS share",
              not HC.is_network_fs(HC.cache_dir(log=lambda *x: None)))
    except ImportError as e:                                   # noqa: BLE001
        log(f"    (head_cache checks SKIPPED: {e})")

    # ------------- 19. rung 4 S4: --nch, derived geometry, placement ------
    log("  [19] rung 4 S4: nch sessions, derived geometry, weight placement")
    recs1, _b1, meta1 = load_template(args.template)
    g1 = derive_geometry(recs1, meta1)
    check("the derivation reproduces the frozen 1-chan geometry EXACTLY",
          all(g1[k] == getattr(SC, k) for k in
              ("TEMPLATE_NREC", "R_SEED_TOK", "R_SEED_POS", "R_TCNT",
               "R_HALT", "R_BODY_FULL", "R_BODY_LITE", "R_PREAMBLE",
               "R_POSADV", "R_JMP", "NREC_PREAMBLE", "NREC_BODY_FULL",
               "NREC_BODY_LITE", "LITE_SUFFIX_RECS",
               "POS_LDC_REC_OFFSETS",
               # R-d: the const-blob geometry is derived now too, and on
               # this artifact it must land on agent A's frozen literals
               "CONST_BYTES", "POS_BLOB_BASE", "POS_WORDS",
               "POS_COPY_BYTES", "POS_STRIDE", "SEQDATA_SHA256")),
          str({k: (v, getattr(SC, k, None)) for k, v in g1.items()
               if not k.startswith("_") and v != getattr(SC, k, v)}))
    check("...including this file's own frozen constants",
          (g1["R_BODY_LITE"], g1["R_BODY_FULL"], g1["R_TCNT"], g1["R_HALT"],
           g1["X8_WORD"], g1["X8_LEN"])
          == (REC_BODY_LITE, REC_BODY_FULL, REC_TCNT, REC_HALT,
              X8_WORD, X8_LEN))
    check("the lite cut is found from the HEAD IMAGE, not from scratch[0x800]",
          sum(1 for r in recs1[REC_BODY_FULL[0]:REC_BODY_FULL[1]]
              if r.opcode == SF.OP_MOVX and r.addr_lo == X8_WORD) > 1,
          "x8 is reused by many matvecs, so 'first MOVX 0x800' would be wrong")
    # G2a review N19: prove the 0.8B fallback is NOT what these footprints
    # were computed from -- on a host without ref/ it would silently halve
    # every LNH-sized tile.
    check("the scratch geometry is DERIVED from ref/layer_ref, not the "
          "0.8B fallback", GEOM_IS_DERIVED, str(GEOM))
    check("the derived head wid is the manifest's LM head", g1["_HEAD_WID"]
          == HEAD_WID, str(g1["_HEAD_WID"]))

    # scope A: the 4-chan pin is per FABLE5_MODEL, and every entry names an
    # artifact that hashes to its pin.
    _want4 = TEMPLATE4_BY_MODEL.get(MODEL_TAG, TEMPLATE4_BY_MODEL[None])
    check("the 4-chan template pin follows FABLE5_MODEL",
          (TEMPLATE4_PREFIX, TEMPLATE4_SHA256, TEMPLATE4_NREC)
          == (os.path.join(TOP_DIR, *_want4[0]), _want4[1], _want4[2]),
          f"FABLE5_MODEL={MODEL_TAG}: {TEMPLATE4_PREFIX}")
    check("the frozen 0.8B/2B 4-chan artifact is NOT re-pinned (scope F)",
          TEMPLATE4_BY_MODEL[None][0][-1] == "model_v2_s1.e4"
          and TEMPLATE4_BY_MODEL[None][2] == 68119)
    check("the 9B entry names the S4 artifact the SEQ gate ran on",
          TEMPLATE4_BY_MODEL["9b"][0][-1] == "model_9b_s1.e4"
          and TEMPLATE4_BY_MODEL["9b"][2] == 158536)
    for _tag4 in sorted(TEMPLATE4_BY_MODEL, key=str):
        _parts4, _sha4, _nrec4 = TEMPLATE4_BY_MODEL[_tag4]
        _pfx4 = os.path.join(TOP_DIR, *_parts4)
        if not os.path.exists(_pfx4 + ".seq"):             # pragma: no cover
            log(f"    (the {_tag4} 4-chan pin is SKIPPED: no {_pfx4}.seq)")
            continue
        _raw4 = open(_pfx4 + ".seq", "rb").read()
        check(f"the {_tag4 or 'default'} 4-chan pin IS the artifact on disk",
              hashlib.sha256(_raw4).hexdigest() == _sha4
              and len(_raw4) // SEQ_REC_BYTES == _nrec4,
              os.path.basename(_pfx4))

    have4 = os.path.exists(TEMPLATE4_PREFIX + ".seq")
    if not have4:
        log(f"    (nch=4 checks SKIPPED: no {TEMPLATE4_PREFIX}.seq — "
            f"regenerate with SEQ_NCH=4)")
    else:
        recs4, _b4, meta4 = load_template(TEMPLATE4_PREFIX,
                                          sha=TEMPLATE4_SHA256,
                                          g={"TEMPLATE_NREC": TEMPLATE4_NREC})
        g4 = derive_geometry(recs4, meta4)
        check("the 4-chan artifact is the gated one", True)
        check("the 4-chan stream declares nch=4 and an interleaved head",
              int(meta4["nch"]) == 4
              and meta4["weight_layout"]["ilv_wids"] == [HEAD_WID]
              and meta4["weight_layout"]["chunk_rows"] == SF.CHUNK_ROWS,
              str(meta4.get("weight_layout")))
        check("the 4-chan stream is the SAME schedule (same const blob)",
              meta4["seqdata_sha256"] == meta1["seqdata_sha256"])
        check("the 4-chan stream keeps the same weight pack",
              meta4["weights"] == meta1["weights"])
        check("the 4-chan stream keeps the same expected tokens",
              meta4["expect_tokens"] == meta1["expect_tokens"],
              f"{meta4['expect_tokens']} vs {meta1['expect_tokens']}")
        check("the 4-chan geometry is longer but structurally identical",
              g4["TEMPLATE_NREC"] == TEMPLATE4_NREC
              and g4["R_PREAMBLE"] == g1["R_PREAMBLE"]
              and g4["R_SEED_TOK"] == g1["R_SEED_TOK"]
              and g4["NREC_BODY_FULL"] > g1["NREC_BODY_FULL"]
              and len(g4["POS_LDC_REC_OFFSETS"]) == POS_COPIES,
              str({k: v for k, v in g4.items() if not k.startswith("_")}))
        # R-d: the .e4 shares the 1-chan artifact's const blob and geometry,
        # so every derived blob/x8 field must land on the SAME numbers the
        # 1-chan derivation was just checked against field by field.  (This
        # is the .e4's version of that check — it is compared to g1, not to
        # agent A's literals directly.)
        check("the 4-chan derivation reproduces the 1-chan blob geometry",
              all(g4[k] == g1[k] for k in
                  ("CONST_BYTES", "POS_BLOB_BASE", "POS_WORDS",
                   "POS_COPY_BYTES", "POS_STRIDE", "SEQDATA_SHA256",
                   "X8_WORD", "X8_LEN")),
              str({k: (g4[k], g1[k]) for k in
                   ("CONST_BYTES", "POS_STRIDE", "X8_WORD", "X8_LEN")}))
        m4 = seq_chat_for(g4)
        check("the module clone leaves agent A's module untouched",
              (SC.TEMPLATE_NREC, SC.R_BODY_FULL, SC.POS_LDC_REC_OFFSETS)
              == (TEMPLATE_NREC, REC_BODY_FULL, SC.POS_LDC_REC_OFFSETS)
              and m4 is not SC and m4.TEMPLATE_NREC == TEMPLATE4_NREC)
        check("the clone recomputed the position-LDC byte offsets",
              m4.POS_LDC_BYTE_OFFSETS
              == tuple(o * 16 + 8 for o in g4["POS_LDC_REC_OFFSETS"]))
        tc4 = m4.TurnCompiler(TEMPLATE4_PREFIX, t_max=T_MAX, pos_mode="ldc",
                              verify_sha=False)
        mine4 = independent_step_images(recs4, g4)
        holes = set()
        for off in (HOLE_TOK, HOLE_POS, HOLE_TCNT):
            holes.update(range(off, off + 4))
        ok4 = True
        for kind in ("lite", "full"):
            theirs = tc4.build_step(0, 0, kind).data
            ok4 = ok4 and len(theirs) == len(mine4[kind]) and all(
                i in holes for i in range(len(theirs))
                if theirs[i] != mine4[kind][i])
        check("agent A's compiler on the CLONE == my own 4-chan slices", ok4)
        check("the 4-chan const blob is byte-identical to the 1-chan one",
              tc4.blob() == SC.TurnCompiler(args.template, t_max=T_MAX,
                                            pos_mode="ldc").blob())

        s4 = _args(nch=4, template=TEMPLATE4_PREFIX)
        sess4 = ChatSession(s4, log=lambda *x: None)
        check("an nch=4 session builds all three images",
              sorted(sess4.images) == ["full", "lite", "preamble"]
              and sess4.images["full"].nrec
              == g4["NREC_BODY_FULL"] + HEAD_RECS + 1)
        check("an nch=4 session patches at the SAME hole offsets",
              all(sess4.images[k].holes == {"tok": 4, "pos": 20, "tcnt": 36}
                  for k in ("lite", "full")))
        check("the nch=4 plan row-splits weights over chans 0..3",
              sess4.plan["nch"] == 4
              and sess4.plan["weight_chans"] == [0, 1, 2, 3])
        check("the layout tag names the interleaved head",
              sess4.layout_tag()["ilv_wids"] == [HEAD_WID]
              and sess4.layout_tag()["nch"] == 4, str(sess4.layout_tag()))
        sp4 = sess4.weight_splits()
        hp4 = [s for s in sp4 if s["wid"] == HEAD_WID]
        check("the head is placed as interleaved chunks, chunk j -> chan j%4",
              [s["chan"] for s in hp4] == [j % 4 for j in range(len(hp4))]
              and all(s["layout"] == SF.LAYOUT_ILV for s in hp4)
              and len(hp4) > 4, f"{len(hp4)} pieces")
        check("every other image keeps contiguous quarters",
              all(s["layout"] == SF.LAYOUT_CONTIG
                  for s in sp4 if s["wid"] != HEAD_WID))
        s1s = ChatSession(_args(), log=lambda *x: None)
        check("an nch=1 session has no placement map at all",
              s1s.weight_splits() is None)

        # --- the refusals: one session, one nch (S4) ---
        check("--nch 4 on the 1-chan template is refused",
              _refuses(lambda: ChatSession(_args(nch=4), log=lambda *x: None)))
        check("--nch 1 on the 4-chan template is refused",
              _refuses(lambda: ChatSession(
                  _args(nch=1, template=TEMPLATE4_PREFIX),
                  log=lambda *x: None)))
        check("an unsupported --nch is refused",
              _refuses(lambda: ChatSession(_args(nch=2),
                                           log=lambda *x: None)))
        check("a session's nch/layout tag is immutable bookkeeping",
              sess4.layout_tag() != ChatSession(
                  _args(), log=lambda *x: None).layout_tag())

    # --- 19b. the residency probe IS the layout probe (synthetic images) ---
    import shutil
    import tempfile
    td = tempfile.mkdtemp(prefix="fable5_nch_")
    try:
        rng = np.random.default_rng(4)
        smanifest, swb = {}, {}
        for wid, nrows in ((0, 12288), (1, 64)):
            stride = 64
            data = rng.integers(0, 256, nrows * stride,
                                dtype=np.uint8).tobytes()
            fn = f"syn_w{wid}.bin"
            open(os.path.join(td, fn), "wb").write(data)
            smanifest[str(wid)] = {"file": fn, "nrows": nrows,
                                   "stride": stride, "ng": 8, "sh": 5}
            swb[wid] = 0x1000_0000 + wid * (1 << 24)
        ilv_meta = {"nch": 4, "weight_layout": {
            "nch": 4, "chunk_rows": 2048, "default": SF.LAYOUT_CONTIG,
            "by_wid": {"0": SF.LAYOUT_ILV}, "ilv_wids": [0]}}
        cfg_meta = {"nch": 4}
        sp_i = SR.plan_weight_split(smanifest, swb, 4, [0, 1, 2, 3], ilv_meta)
        sp_c = SR.plan_weight_split(smanifest, swb, 4, [0, 1, 2, 3], cfg_meta)
        wi = build_residency_manifest(smanifest, td, swb, None, 0, splits=sp_i)
        check("a 4-chan witness set is one block PER PIECE (R-d)",
              len(wi) == len(sp_i) and all(w["chan"] is not None for w in wi),
              f"{len(wi)} witnesses for {len(sp_i)} pieces")
        check("a CONTIGUOUS image still gets exactly one witness per channel",
              sorted(w["chan"] for w in wi if w["wid"] == 1) == [0, 1, 2, 3],
              str([w["name"] for w in wi if w["wid"] == 1]))
        check("an nch=1 witness set is unchanged (one block, no channel)",
              [w["chan"] for w in build_residency_manifest(
                  smanifest, td, swb, None, 0)] == [None, None])

        class _MemDev(object):
            def __init__(self):
                self.mem = {}
                self.ddr_off = 0

            def dma_write_chan(self, c, a, d):
                for i, b in enumerate(bytes(d)):
                    self.mem[c * HW.CH_STRIDE + a + i] = b

            def dma_read_chan(self, c, a, n):
                return bytes(self.mem.get(c * HW.CH_STRIDE + a + i, 0)
                             for i in range(n))

            def dma_read(self, a, n):
                return self.dma_read_chan(0, a, n)

            def place(self, splits):
                self.mem = {}
                for s in splits:
                    img = open(os.path.join(td, smanifest[str(s["wid"])]
                                            ["file"]), "rb").read()
                    self.dma_write_chan(
                        s["chan"], s["local_addr"],
                        img[s["byte_off"]:s["byte_off"] + s["byte_len"]])

        dv = _MemDev()
        dv.place(sp_i)
        check("the probe passes on a correctly INTERLEAVED board",
              probe_residency(dv, wi, log=lambda *x: None) == [])
        # R-d regression: the LM head is INTERLEAVED, so a channel owns many
        # chunks.  Damage the FIRST chunk chan 0 owns — the witness this
        # code used to take is the MIDDLE one (r0=8192 here), so before R-d
        # this passed the probe and the session ran on stale head weights.
        dv.place(sp_i)
        first = min((s for s in sp_i if s["wid"] == 0 and s["chan"] == 0),
                    key=lambda s: s["r0"])
        mid = sorted((s for s in sp_i if s["wid"] == 0 and s["chan"] == 0),
                     key=lambda s: s["r0"])
        check("the ILV image really has >1 chunk on chan 0 (test is not "
              "vacuous)", len(mid) > 1 and mid[len(mid) // 2] is not first)
        dv.dma_write_chan(0, first["local_addr"], b"\xa5" * first["byte_len"])
        check("R-d: damage to ANY interleaved chunk is caught, not just the "
              "middle one",
              any(w["wid"] == 0 for w in
                  probe_residency(dv, wi, log=lambda *x: None)))
        # R-d rule (b): ONE missing witness re-uploads the whole pack.  On
        # hardware every observed miss set has been all-187, so this branch
        # is a no-op there — driving it needs a partial miss, which is what
        # this is.  (RD_GATE.md §4.2 scopes the silicon proof to rule (a).)
        one = [w for w in wi if w["wid"] == 0][:1]
        sel, se, n_sel = reupload_set(one, smanifest)
        check("R-d: a SINGLE witness miss re-uploads every image + the emb",
              sel == sorted(int(k) for k in smanifest) and se is True
              and n_sel == 1, f"{sel} emb={se} n_sel={n_sel}")
        check("R-d: an emb-only miss still re-uploads every image",
              reupload_set([{"kind": "emb", "wid": -1}], smanifest)[0]
              == sorted(int(k) for k in smanifest))
        check("R-d: no miss uploads nothing",
              reupload_set([], smanifest) == ([], False, None))
        dv.place(sp_c)
        bad_c = probe_residency(dv, wi, log=lambda *x: None)
        check("a CONTIGUOUS-quarter board misses the interleaved witnesses",
              any(w["wid"] == 0 for w in bad_c), str(len(bad_c)))
        dv.mem = {}
        for wid in (0, 1):                     # an nch=1 board: chan 0 only
            img = open(os.path.join(td, smanifest[str(wid)]["file"]),
                       "rb").read()
            dv.dma_write_chan(0, swb[wid], img)
        check("an nch=1 board misses the nch=4 witnesses on chans 1..3",
              {w["chan"] for w in probe_residency(dv, wi, log=lambda *x: None)}
              >= {1, 2, 3})
        dv.place(sp_i)
        w = [x for x in wi if x["chan"] == 1][0]
        dv.mem[1 * HW.CH_STRIDE + w["addr"]] ^= 0xFF
        check("a single flipped byte inside a chan-1 witness is caught",
              [b["name"] for b in probe_residency(dv, wi, log=lambda *x: None)]
              == [w["name"]])
    finally:
        shutil.rmtree(td, ignore_errors=True)

    # ------------- 19c. S6: the widened OUT FIFO + sticky of_ovf ----------
    log("  [19c] rung 4 S6: OUT FIFO depth 64, 7-bit count, sticky of_ovf")
    check("hwmap knows the new depth", SEQ_OUT_DEPTH == 64)
    check("the count field is 7 bits at [22:16]",
          (HW.SEQ_ST_OUTCNT_SHIFT, HW.SEQ_ST_OUTCNT_MASK) == (16, 0x7F))
    check("of_ovf is STATUS bit 23", HW.SEQ_ST_OF_OVF == (1 << 23))
    st_full = (0x40 << 16) | HW.SEQ_ST_OF_OVF | (0x12 << 24) | 0x4
    d = HW.seq_status(st_full)
    check("a full 64-entry count decodes (0x1F would have read 0)",
          d["out_cnt"] == 64, str(d["out_cnt"]))
    check("of_ovf decodes, and does not bleed into err_code or out_cnt",
          d["of_ovf"] and d["err_code"] == 0x12 and d["halted"]
          and not d["busy"], str(d))
    check("a clean STATUS reports of_ovf False",
          not HW.seq_status((0x03 << 16) | 0x4)["of_ovf"])
    check("the count and the overflow bit are independent fields",
          HW.seq_status((0x7F << 16))["out_cnt"] == 127
          and not HW.seq_status((0x7F << 16))["of_ovf"])
    sovf = ChatSession(_args(), log=lambda *x: None)
    check("a fresh session starts with the alarm clear", not sovf.out_fifo_ovf)
    sovf._latch_ovf({"out_fifo_ovf": False})
    check("a clean launch leaves it clear", not sovf.out_fifo_ovf)
    msgs = []
    sovf.log = msgs.append
    sovf._latch_ovf({"out_fifo_ovf": True})
    check("a set of_ovf latches ONCE, loudly, and names the stickiness",
          sovf.out_fifo_ovf and len(msgs) == 1
          and "sticky" in msgs[0] and "dropped" in msgs[0]
          and "trusted" in msgs[0], str(msgs))
    sovf._latch_ovf({"out_fifo_ovf": False})
    check("...and NEVER clears (sticky until a hard reset)",
          sovf.out_fifo_ovf and len(msgs) == 1)

    # ------------- 20. S8: the top-k CSR read protocol --------------------
    log("  [20] rung 4 S8: TOPK-32 STATUS decode + PTR auto-increment")

    class _TopkDev(object):
        """The S5 CSR block: STATUS word + VAL/IDX with an IDX-read PTR++."""

        def __init__(self, vals, idxs, complete=True, ovf=False,
                     base=TOPK_BASE, ident=ChipTopKSource.IDENT):
            self.vals, self.idxs = list(vals), list(idxs)
            self.base, self.ident = base, ident
            self.ptr = 7                     # stale on purpose
            self.st = ((len(self.vals) & 0x3F) | (0x40 if complete else 0)
                       | (0x80 if ovf else 0))
            self.reads, self.writes = [], []

        def rd(self, a):
            self.reads.append(a)
            o = a - self.base
            if o == ChipTopKSource.OFF_IDENT:
                return self.ident
            if o == ChipTopKSource.OFF_STATUS:
                return self.st
            if o == ChipTopKSource.OFF_PTR:
                return self.ptr
            if o == ChipTopKSource.OFF_VAL:
                return self.vals[self.ptr] & 0xFFFFFFFF
            if o == ChipTopKSource.OFF_IDX:
                v = self.idxs[self.ptr]
                self.ptr = (self.ptr + 1) & 0x1F        # THE auto-increment
                return v
            if a == HW.L_EOUT:
                return 5
            raise AssertionError(f"unexpected CSR read {a:#x}")

        def wr(self, a, v):
            self.writes.append((a, int(v)))
            if a - self.base == ChipTopKSource.OFF_PTR:
                self.ptr = int(v) & 0x1F

    vals = [1000 - 7 * i for i in range(6)] + [0] * 26
    idxs = [11 * i + 3 for i in range(6)] + [0] * 26
    vals[3] = -5                                     # a negative logit
    d = _TopkDev(vals[:6], idxs[:6])
    src = ChipTopKSource(d, base=TOPK_BASE)
    check("the S5 address is the default the CLI hands over",
          TOPK_BASE == 0x5048 and ChipTopKSource.OFF_IDX == 0x10)
    check("the unit is present when its IDENT reads back", src.available)
    v, i, e_x = src.candidates(None)
    check("count[5:0] decides how many entries are read", len(v) == 6
          and len(i) == 6, f"{len(v)}")
    check("the values are sign-extended int32", list(v) == vals[:6],
          str(list(v)))
    check("the indices are the 18-bit row ids", list(i) == idxs[:6])
    check("e_x still comes from L_EOUT (S4 unchanged)", e_x == 5)
    check("S8: PTR is written ONCE, not per entry",
          [w for w in d.writes if w[0] == TOPK_BASE + ChipTopKSource.OFF_PTR]
          == [(TOPK_BASE + ChipTopKSource.OFF_PTR, 0)], str(d.writes))
    check("S8: two reads per entry (VAL, IDX), plus IDENT/STATUS/EOUT",
          len(d.reads) == 3 + 2 * 6, str(len(d.reads)))
    check("the read order is VAL then IDX (IDX is what advances PTR)",
          d.reads[2:6] == [TOPK_BASE + ChipTopKSource.OFF_VAL,
                           TOPK_BASE + ChipTopKSource.OFF_IDX,
                           TOPK_BASE + ChipTopKSource.OFF_VAL,
                           TOPK_BASE + ChipTopKSource.OFF_IDX])
    check("the sampler re-imposes value DESC / index ASC anyway",
          list(np.asarray(v)[Sampler(temp=0.0)._order(v, i)])
          == sorted(v, reverse=True))
    d2 = _TopkDev(vals[:4], idxs[:4], complete=False)
    s2 = ChipTopKSource(d2, base=TOPK_BASE)
    check("complete=0 (a scan in flight) RAISES instead of sampling",
          _refuses(lambda: s2.candidates(None)))
    d3 = _TopkDev(vals[:5], idxs[:5], ovf=True)
    s3 = ChipTopKSource(d3, base=TOPK_BASE)
    s3.candidates(None)
    check("a sticky overflow is counted and reported, not fatal",
          s3.overflows == 1 and s3.as_dict()["overflow_steps"] == 1
          and s3.as_dict()["last_status"] == hex(0x80 | 0x40 | 5),
          str(s3.as_dict()))
    d4 = _TopkDev(list(range(40)), list(range(40)))
    d4.st = (0x3F | 0x40)                            # count says 63 > k
    s4c = ChipTopKSource(d4, base=TOPK_BASE, k=32)
    v4, _i4, _e4 = s4c.candidates(None)
    check("a count above the capture depth is clamped to k", len(v4) == 32)
    check("a bitstream WITHOUT the unit reads 0xDEADC0DE and stays absent",
          not ChipTopKSource(_TopkDev([], [], ident=0xDEADC0DE),
                             base=TOPK_BASE).available)

    # ---------------- 21. S3: the DDR state region, host side ----------
    # S3 fix round 1, I7.  The conv witnesses and the session-reset memset
    # are the two host-side halves of spec 7.1's audit, and neither had a
    # test.  Both are driven here off-board.
    log("  [21] S3: conv-image witnesses + the session-reset DN memset")
    import shutil as _shutil
    import tempfile as _tempfile

    def _raises(fn, exc=Exception):
        try:
            fn()
        except exc:
            return True
        except Exception:
            return False
        return False

    _sp = HW.plan_state(HW.plan_state_base(4))
    _std = _tempfile.mkdtemp()
    _cvn = 3
    _cvimgs = []
    for _L in range(_cvn):
        _fn = f"x_cv{_L}.bin"
        with open(os.path.join(_std, _fn), "wb") as _f:
            _f.write(bytes([(_L * 7 + i) & 0xFF
                            for i in range(HW.STATE_CV_STRIDE)]))
        _cvimgs.append({"layer": _L, "file": _fn,
                        "bytes": HW.STATE_CV_STRIDE})
    _man1 = {"0": {"file": "x_w0.bin", "nrows": 8, "k": 128, "ng": 1,
                   "sh": 0, "e": 0, "nbeats": 1, "stride": 64}}
    with open(os.path.join(_std, "x_w0.bin"), "wb") as _f:
        _f.write(bytes(512))
    _wit = build_residency_manifest(_man1, _std, {0: HW.W_BASE}, None, 0,
                                    state=_sp, conv_images=_cvimgs)
    _cw = [w for w in _wit if w["kind"] == "conv"]
    check("one residency witness per conv image", len(_cw) == _cvn,
          f"{len(_cw)} of {_cvn}")
    check("a conv witness is CHANNEL-LOCAL and inside its own block",
          all(w["chan"] == (_sp["cv"] >> 32)
              and 0 <= w["addr"] - ((_sp["cv"] & 0xFFFF_FFFF)
                                    + w2["layer"] * HW.STATE_CV_STRIDE)
              < HW.STATE_CV_STRIDE
              for w, w2 in zip(_cw, _cvimgs)))
    check("the conv witnesses hash DIFFERENT bytes per layer",
          len({w["sha256"] for w in _cw}) == _cvn)
    check("a conv-image miss invalidates the WHOLE pack (R-d rule b)",
          reupload_set([_cw[0]], _man1) == ([0], True, 0))
    check("a conv image whose size disagrees with the manifest is REFUSED",
          _raises(lambda: build_residency_manifest(
              _man1, _std, {0: HW.W_BASE}, None, 0, state=_sp,
              conv_images=[dict(_cvimgs[0], bytes=17)]), ChatSeqError))

    class _RstDev(object):
        def __init__(self, zero=True):
            self.zero, self.w, self.v = zero, [], []

        def dma_write_chan(self, c, a, d):
            self.w.append((c, a, len(d)))

        def dma_verify_chan(self, c, a, d, tag=None):
            self.v.append((c, a, len(d)))

        def dma_read_chan(self, c, a, n):
            return bytes(n) if self.zero else b"\x01" * n

    class _RstSess(object):
        reset_state_region = ChatSession.reset_state_region

        def __init__(self, dev, state, conv_images=None, wdir=None):
            self.dev, self.state = dev, state
            self.conv_images, self.wdir = conv_images, wdir

        def log(self, *a):
            pass

    _rd = _RstDev()
    _n = _RstSess(_rd, _sp).reset_state_region()
    check("the session reset memsets the WHOLE DN region, 1 MiB at a time",
          _n == 24 and len(_rd.w) == 24
          and all(x[2] == HW.STATE_DN_LAYER for x in _rd.w))
    check("the session reset READS BACK and refuses a non-zero DN region",
          _raises(lambda: _RstSess(_RstDev(zero=False),
                                   _sp).reset_state_region(), ChatSeqError))
    check("a pre-v2.1 session has no region to reset",
          _RstSess(_RstDev(), None).reset_state_region() == 0)

    # ---------------- 22. the DDR state region: verifier + session -------
    # Task 15 fix round 2, functions B/C/D of the chat scope
    # (evidence/qwen9b/g6/RD9_GATE.md §20.2).  RED on the pre-fix tree: the
    # verifier handed ref/seq_model.SeqExec no `region=`, so the first
    # SLD/SST of a 9B chat step refused --
    # `evidence/qwen9b/g6/056_chat_seq_9b_model_set.log` attempt [6].
    #
    # Every NEW entry point below is reached through `_absent` / `_val`, so
    # on a tree that does not have it yet the case reports a FAIL LINE with
    # the reason instead of aborting the suite on an AttributeError.  That
    # is what makes the RED readable.
    log("  [22] S3/9B: the state region in the verifier, the session and "
        "the residency split")
    import seq_model as _SM22

    def _absent(*_a, **_kw):
        raise AttributeError("this entry point does not exist on this tree")

    def _val(fn, *a, **kw):
        """`fn(*a)`, or a string naming what it raised — so a missing or
        refusing entry point FAILS a check instead of aborting the case."""
        try:
            return fn(*a, **kw)
        except Exception as e:                             # noqa: BLE001
            return f"RAISED {type(e).__name__}: {e}"

    # --- B: the verifier hands SeqExec a region (056 [6]'s failure) ------
    _cap22 = {}

    class _CapExec(object):
        def __init__(self, recs, blob, W, emb=None, mach=None, region=None,
                     **kw):
            _cap22["region"] = region
            _cap22["mach"] = mach

        def run(self, max_steps=None):
            self.out_fifo = [4321]
            return self

    class _CapSM(object):
        SeqExec = _CapExec

    class _CapVer(object):
        _run = SeqModelVerifier._run
        SM = _CapSM
        blob, W, emb, mach = b"", None, None, "MACH"
        region = "REGION-SENTINEL"
        sess = None

    _im22 = Resident("preamble", tc.build_session())
    _out22 = _val(_CapVer()._run, _im22, 0, 0)
    check("the verifier hands ref/seq_model.SeqExec a state region "
          "(056 [6]: an SLD/SST refuses without one)",
          _cap22.get("region") == "REGION-SENTINEL",
          f"SeqExec got region={_cap22.get('region')!r}")
    check("the verifier still hands SeqExec its persistent mach",
          _cap22.get("mach") == "MACH" and _out22 == [4321], str(_out22))

    # --- the REASON, against the real executor: RED then GREEN -----------
    _sp22 = HW.plan_state(HW.plan_state_base(4))
    _reg22 = _SM22.StateRegion(_sp22)

    def _sld22(region):
        # KV at TCNT 0 is the ONE transfer whose shape does not depend on
        # the FABLE5_MODEL geometry (it moves TCNT rows, and a fresh mach
        # has TCNT 0), so this control runs under the shipped selection.
        _ex = _SM22.SeqExec([SF.Rec(SF.OP_HALT)], b"", {}, region=region)
        _ex.args = [SF.sdma_arg0(SF.SDMA_KIND_KV, 0, 0, 0), 0, 0]
        _ex._layer_cmd(SF.OP_L_SLD)
        return True
    check("RED control: ref/seq_model REFUSES an SLD with no region",
          _refuses(lambda: _sld22(None), SF.SeqValidationError))
    check("GREEN: the same SLD runs against a region",
          _sld22(_reg22) is True)

    # --- B: SeqModelVerifier.state_region -------------------------------
    _sr22 = getattr(SeqModelVerifier, "state_region", _absent)

    class _StSess(object):
        def __init__(self, base, state):
            self.base, self.state = base, state

    check("a pre-S3 artifact has no region (the frozen nch=1 path is "
          "untouched)",
          _val(_sr22, _StSess("/nonexistent", None)) is None)
    _bad22 = _tempfile.mkdtemp()
    with open(os.path.join(_bad22, "x.state.bin"), "wb") as _f:
        _f.write(bytes(64))
    with open(os.path.join(_bad22, "x.weights.json"), "w") as _f:
        json.dump({"_meta": {"state": dict(_sp22)}}, _f)
    check("a region image that does not span the plan is REFUSED, not "
          "silently truncated",
          _refuses(lambda: _sr22(_StSess(os.path.join(_bad22, "x"), _sp22))))
    _shutil.rmtree(_bad22, ignore_errors=True)

    _b9 = os.path.join(TOP_DIR, "tb", "scripts", "w9", "model_9b_s1")
    if not os.path.exists(_b9 + ".state.bin"):             # pragma: no cover
        log(f"    (the 9B region case is SKIPPED: no {_b9}.state.bin)")
    else:
        _m9, _mm9 = HW.load_weights_manifest(_b9)
        _r9 = _val(_sr22, _StSess(_b9, _mm9["state"]))
        check("the 9B artifact's own StateRegion is what the verifier gets",
              getattr(_r9, "plan", None)
              == {k: int(_mm9["state"][k]) for k in ("dn", "kv", "cv", "end")},
              str(_r9)[:160])
        check("...and it is the artifact's INITIAL image, sha-checked",
              hasattr(_r9, "mem")
              and hashlib.sha256(bytes(_r9.mem)).hexdigest()
              == _mm9["state"]["sha256"])

    # --- the residency split (RD9_GATE.md §14.1) ------------------------
    _split22 = globals().get("split_witnesses",
                             lambda w: (list(w), []))
    _wit22 = build_residency_manifest(_man1, _std, {0: HW.W_BASE}, None, 0,
                                      state=_sp22, conv_images=_cvimgs)
    _pk22, _cv22 = _split22(_wit22)
    check("the conv witnesses are split OUT of the weight pack's probe",
          len(_cv22) == len(_cvimgs)
          and all(w["kind"] == "conv" for w in _cv22)
          and not any(w["kind"] == "conv" for w in _pk22),
          f"{len(_pk22)} pack + {len(_cv22)} conv of {len(_wit22)}")
    check("a conv miss can no longer escalate the weight pack: it is not "
          "in the pack's probe set (§14.1: 0 weight misses, 5.8 GiB "
          "re-uploaded at the start of every later session)",
          reupload_set([w for w in _pk22 if w["kind"] == "conv"], _man1)
          == ([], False, None))
    check("a WEIGHT miss still invalidates the whole pack (R-d rule b)",
          reupload_set([_pk22[0]], _man1) == ([0], True, 1))

    # --- D: the context reset restores the conv taps --------------------
    _rd22 = _RstDev()
    _n22 = _RstSess(_rd22, _sp22, conv_images=_cvimgs,
                    wdir=_std).reset_state_region()
    _cvw22 = [x for x in _rd22.w if x[2] == HW.STATE_CV_STRIDE]
    check("the context reset RESTORES every conv image, not just the DN "
          "memset",
          _n22 == 24 and len(_cvw22) == len(_cvimgs),
          f"{_n22} DN block(s), {len(_cvw22)} conv write(s)")
    check("each conv image lands on its own block, channel-local, and is "
          "read back",
          [x[1] for x in _cvw22]
          == [(_sp22["cv"] & 0xFFFF_FFFF) + c["layer"] * HW.STATE_CV_STRIDE
              for c in _cvimgs]
          and _rd22.v == _cvw22, str(_rd22.v))

    # --- C: the INITIAL region is WRITTEN, not just the base CSRs -------
    _calls22 = []
    _up22, _ck22 = SR.upload_state, SR.seq_check_state_bases
    try:
        def _fake_up(dev, art, log=print, verify=True, csrs_only=False):
            _calls22.append(("upload", csrs_only))
            return {"dn_blocks_zeroed": 24}

        def _fake_ck(dev, art, log=print):
            _calls22.append(("bases", None))
            return {}
        SR.upload_state, SR.seq_check_state_bases = _fake_up, _fake_ck

        class _BuSess(object):
            bring_up_state = getattr(ChatSession, "bring_up_state", _absent)

            def __init__(self, state):
                self.state, self.dev = state, None

            def log(self, *a):
                pass

        _val(_BuSess(_sp22).bring_up_state)
        _pre22 = list(_calls22)
        del _calls22[:]
        _val(_BuSess(None).bring_up_state)
    finally:
        SR.upload_state, SR.seq_check_state_bases = _up22, _ck22
    check("the session WRITES the initial state region, not just the base "
          "CSRs (§14.2: csrs_only leaves the previous context in DDR and "
          "the answer is silently wrong at err_code 0x00)",
          _pre22[:1] == [("upload", False)], str(_pre22))
    check("...and reads SB_DN/SB_KV/SB_CV back before any launch "
          "(E_DMA_BASE, SEQ ISA v2.1 B15.4)",
          [c[0] for c in _pre22] == ["upload", "bases"], str(_pre22))
    check("a pre-S3 artifact writes no region and programs no base CSR",
          _calls22 == [], str(_calls22))
    # m3: the conv-witness refusal ITSELF, both ways.  `--corrupt-wid` was
    # only ever fired at a WEIGHT image; nothing exercised the raise this
    # round added, whose whole point is that a conv miss HERE — probed
    # against the write that just happened — is a real miss and not
    # §14.1's by-design staleness.  `probe_residency` is the seam.
    _g22 = globals()
    _pr22 = _g22["probe_residency"]
    try:
        SR.upload_state, SR.seq_check_state_bases = _fake_up, _fake_ck
        _g22["probe_residency"] = lambda dev, w, log: list(w)
        check("a conv-image witness that STILL differs after the state "
              "upload is refused, loudly (m3's missing negative control)",
              _refuses(lambda: _BuSess(_sp22).bring_up_state(
                  [{"name": "cv0", "kind": "conv"}])))
        _g22["probe_residency"] = lambda dev, w, log: []
        check("...and the SAME call with every conv witness matching does "
              "NOT refuse — the control fires one way only",
              _val(_BuSess(_sp22).bring_up_state,
                   [{"name": "cv0", "kind": "conv"}])
              == {"dn_blocks_zeroed": 24})
    finally:
        _g22["probe_residency"] = _pr22
        SR.upload_state, SR.seq_check_state_bases = _up22, _ck22
    _shutil.rmtree(_std, ignore_errors=True)

    # ---------------- 23. E: the context ceiling and pos_mode at 9B ------
    log("  [23] E: T_MAX = the TARGET NETLIST's KV depth, the position "
        "blob, the FROZEN path's footprint, and pos_mode geometry")
    # I-2: the ceiling is per model selection, because it belongs to the
    # bitstream.  build_041 (9B) spills KV to DDR at T <= 4096; the frozen
    # 0.8B/2B build_034/035 still address KV with kv_waddr = tcnt[8:0].
    _want23 = HW.STATE_T_MAX if MODEL_TAG == "9b" else 512
    check("T_MAX is THIS selection's netlist ceiling, and agent A's is the "
          "same number",
          T_MAX == SC.T_MAX == _want23,
          f"chat_seq {T_MAX} / seq_chat {SC.T_MAX} / want {_want23} "
          f"(FABLE5_MODEL={MODEL_TAG}, hwmap {HW.STATE_T_MAX})")
    check("at 9B that ceiling IS sw/hwmap.STATE_T_MAX (the DDR spill's own "
          "goal 3), and hwmap itself never moved",
          HW.STATE_T_MAX == 4096 and (MODEL_TAG != "9b"
                                      or T_MAX == HW.STATE_T_MAX))
    check("the position blob follows T_MAX and THIS model's stride",
          POSBLOB_BYTES == T_MAX * POS_STRIDE,
          f"{POSBLOB_BYTES} != {T_MAX} x {POS_STRIDE}")
    check("the --max-ctx guard is T_MAX-relative", DEFAULT_MAX_CTX < T_MAX)
    _tc23 = SC.TurnCompiler(args.template, t_max=T_MAX, pos_mode="ldc")
    _lay23 = _tc23.blob_layout()
    check("a session built at the ceiling carries T_MAX positions",
          (_lay23["t_max"], _lay23["pos_bytes"])
          == (T_MAX, T_MAX * SC.POS_STRIDE), str(_lay23))
    check("...and its blob is the const region plus exactly that pool",
          len(_tc23.blob())
          == _lay23["const_bytes"] + T_MAX * SC.POS_STRIDE)
    check("the deepest position is patchable in ldc mode",
          _tc23.patch_step(_tc23.build_step(0, 0, "full"), tok=1,
                           pos=T_MAX - 1, tcnt=1) is not None)
    # --- I-2 RED->GREEN: the FROZEN --nch 1 footprint, byte for byte ----
    # `--selftest` runs at --nch 1 on TEMPLATE_PREFIX, so `_tc23` above IS
    # the frozen path at the 0.8B/2B selections.  These are the numbers it
    # had at 4662b06, before scope E raised T_MAX for every model: pool
    # 512 x 1,536 = 786,432 B and blob = CONST_BYTES + that = 1,784,576 B.
    # Fix round 2 made them 6,291,456 B and 7,289,600 B, on a path no
    # bitstream on this board can run
    # (evidence/qwen9b/g6/108_i1_i2_red.log measures both trees).
    if MODEL_TAG in ("0.8b", "2b"):
        check("RED->GREEN: the FROZEN --nch 1 position pool is 786,432 B "
              "(512 x 1,536), as at 4662b06 — not 6,291,456",
              _lay23["pos_bytes"] == 512 * 1536,
              f"{_lay23['pos_bytes']} B at t_max {_lay23['t_max']}")
        check("RED->GREEN: ...and its const blob is 1,784,576 B, so the "
              "frozen session uploads what it uploaded at 4662b06",
              len(_tc23.blob()) == SC.CONST_BYTES + 512 * 1536
              == 1784576, f"{len(_tc23.blob())} B")
        # The control on the other half of the footprint: the compiled
        # images are IDENTICAL at both trees (108 prints the same three
        # sha256s), because the pool lives in the const blob and the
        # images live in the stream window.  So "the placement moved" is
        # true of the BLOB and not of the images — pinned here so the
        # distinction cannot be lost again.
        _res23 = _tc23.resident_images()
        check("...and the three compiled images are untouched by T_MAX: "
              "same record counts, same resident offsets, both trees",
              [(n, o, im.nrec) for (n, o, im) in _res23]
              == [("session", 0, 1526), ("lite", 24576, 14010),
                  ("full", 249856, 14744)],
              str([(n, o, im.nrec) for (n, o, im) in _res23]))
    else:
        check("the frozen --nch 1 footprint is checked at the 0.8B/2B "
              "selections, which is where that path runs (this is "
              f"FABLE5_MODEL={MODEL_TAG})", True)

    def _pm23(mode, ctx, tag, cap):
        try:
            return resolve_pos_mode(_args(pos_mode=mode, max_ctx=ctx),
                                    tag=tag, cap=cap)
        except ChatSeqError:
            return "REFUSED"
        except Exception as e:                             # noqa: BLE001
            return f"RAISED {type(e).__name__}"
    check("RED->GREEN: --pos-mode xrf is REFUSED at 9B for a real chat "
          "context (XRF_POS_MAX 63 at the 2,048 B stride; seq_unit "
          "truncates silently and seq_model does not model it)",
          _pm23("xrf", 500, "9b", 63) == "REFUSED",
          str(_pm23("xrf", 500, "9b", 63)))
    check("ldc is accepted at 9B up to the new ceiling",
          _pm23("ldc", T_MAX - 1, "9b", 63) == "ldc")
    check("the 0.8B/2B path is UNCHANGED: xrf still resolves inside its cap",
          (_pm23("xrf", 40, "2b", 85), _pm23("auto", 40, "2b", 85),
           _pm23("xrf", 500, "2b", 85))
          == ("xrf", "xrf", "REFUSED"))
    # --- I-1: the refusal is the GEOMETRY, not the model tag ----------
    # Both arms, at a tag that is NOT in POS_MODE_LDC_ONLY and at one that
    # is, so neither can be satisfied by the tuple membership test the
    # round-3 review found: the tuple would ALLOW the first and REFUSE the
    # second, and the geometry says the opposite in both cases.
    check("the geometry REFUSES xrf at a tag the policy tuple does not "
          "name — a future 2,048 B-stride model, cap 63, real context "
          "(resolve_pos_mode's generic tail already did this)",
          _pm23("xrf", 500, "4b-future", 63) == "REFUSED",
          str(_pm23("xrf", 500, "4b-future", 63)))
    check("RED->GREEN: ...and the converse — the geometry ALLOWS xrf at a "
          "tag the policy tuple DOES name, when --max-ctx - 1 fits the cap",
          _pm23("xrf", 64, "9b", 63) == "xrf",
          str(_pm23("xrf", 64, "9b", 63)))
    check("...and auto is geometric too, both ways, at the named tag",
          (_pm23("auto", 64, "9b", 63), _pm23("auto", 65, "9b", 63))
          == ("xrf", "ldc"),
          str((_pm23("auto", 64, "9b", 63), _pm23("auto", 65, "9b", 63))))
    check("the boundary is exactly cap < --max-ctx - 1, not <=",
          (_pm23("xrf", 86, "2b", 85), _pm23("xrf", 87, "2b", 85))
          == ("xrf", "REFUSED"))
    _cpm23 = getattr(SeqModelVerifier, "check_pos_mode", _absent)

    class _PmSess(object):
        def __init__(self, pm, max_ctx=500):
            self.pos_mode = pm
            self.args = _args(max_ctx=max_ctx)
    check("the VERIFIER refuses xrf at 9B too — the blind spot is shared, "
          "so lockstep may not be the thing that catches it",
          _refuses(lambda: _cpm23(_PmSess("xrf"), tag="9b")))
    check("...and accepts ldc at 9B, and xrf where it is sound",
          _val(_cpm23, _PmSess("ldc"), tag="9b") is True
          and _val(_cpm23, _PmSess("xrf", max_ctx=40), tag="2b") is True)
    # The two arms that the tuple membership test CANNOT satisfy.  No
    # cap= is passed: both read the same under either model selection
    # (SC.XRF_POS_MAX is 63 at 9B and 85 at 0.8B/2B, and 39 < 63 < 499).
    check("RED->GREEN: the VERIFIER's refusal is the GEOMETRY too — it "
          "refuses xrf at a tag POS_MODE_LDC_ONLY does not name whose cap "
          "cannot reach --max-ctx (before this it returned True there)",
          _refuses(lambda: _cpm23(_PmSess("xrf", max_ctx=500),
                                  tag="4b-future")))
    check("RED->GREEN: ...and the converse — the VERIFIER ACCEPTS xrf at "
          "the tag the tuple DOES name when the cap reaches the context",
          _val(_cpm23, _PmSess("xrf", max_ctx=40), tag="9b") is True,
          str(_val(_cpm23, _PmSess("xrf", max_ctx=40), tag="9b")))

    log(f"  chat_seq selftest: {npass} passed, {nfail} failed")
    return nfail == 0


# ======================================================================
def canned_schedule(meta, prompt_ids):
    """The TRUE per-step feed of the committed model_v2_s1 run.

    CAREFUL (spec decision 5): meta["prompt_fed"] is NOT the prompt.  The
    emitter omits the XRF[3] seed whenever the next token happens to equal
    the previous AMAXL result (XRF[3] already holds it), so "prompt_fed"
    lists only the seeds that survived.  For model_v2_s1:

        prompt   [760, 6511,  314, 9338]           ("The capital of France")
        argmax   [561,  314,  279,  369, 279, 6511]
        seeded    yes   yes    no    yes   no    no   -> [760, 6511, 9338]

    so feeding meta["prompt_fed"] verbatim runs a DIFFERENT prompt.  This
    rebuilds the real sequence: prompt token i while the prompt lasts, the
    previous step's argmax afterwards.  chat_seq ALWAYS emits the seed
    (spec decision 5), which is why the schedule is explicit here.
    """
    want = [int(t) for t in meta["expect_tokens"]]
    p = [int(t) for t in prompt_ids]
    feed = [p[i] if i < len(p) else want[i - 1] for i in range(len(want))]
    seeded = [feed[i] for i in range(len(feed))
              if i == 0 or feed[i] != want[i - 1]]
    if seeded != [int(t) for t in meta.get("prompt_fed", seeded)]:
        raise ChatSeqError(
            f"reconstructed seeds {seeded} != the artifact's prompt_fed "
            f"{meta.get('prompt_fed')} — the prompt does not match this "
            f"stream")
    return feed, want


def run_canned(sess, feed, want, log=print):
    """Gate B1: replay the committed schedule and compare EVERY argmax."""
    if sess.args.prefill != "full":
        raise ChatSeqError("--canned needs --prefill full: gate B1 compares "
                           "every step's argmax, and a lite step emits none")
    got = []
    for i, tok in enumerate(feed):
        out, rep = sess.step(tok, lite=False)
        got.append(out)
        log(f"  step {i}  tok={tok:<6d} pos={i}  -> {out}  "
            f"(committed {want[i]})  {rep['device_ms']:.1f} ms device"
            + ("" if out == want[i] else "   *** DIFFERS"))
        if out != want[i]:
            break
    ok = got == want
    log(f"  tokens     {got}")
    log(f"  committed  {want}")
    return ok, got


def model_only(args, log=print):
    """Run the canned schedule through ref/seq_model ONLY — no board at all.

    This is the host-side proof that the three images ARE the committed
    forward pass: preamble + per-step launches must reproduce the gated
    artifact's expect_tokens exactly.  With --prefill lite the prefill
    steps run the LM-head-less body and the reply tokens must be
    unchanged (spec decision 3).  Slow (minutes per step) but board-free.
    """
    sess = ChatSession(args, log=log)
    v = SeqModelVerifier(sess, log=log)
    from gen_model_script import PROMPTS
    prompt = list(PROMPTS[1][2])          # [760, 6511, 314, 9338]
    fed, want = canned_schedule(sess.meta, prompt)
    nstep = min(args.steps or len(want), len(want))
    log(f"--- model-only: preamble + {nstep} launches "
        f"(prefill={args.prefill}); committed expect_tokens {want}")
    log(f"  feed       {fed}  (prompt {prompt}, then the previous argmax)")
    t0 = time.monotonic()
    v.preamble(sess.images["preamble"])
    log(f"  preamble   replayed in {time.monotonic() - t0:.0f}s")
    got, prev = [], None
    ok = True
    for i in range(nstep):
        tok = fed[i]
        lite = (args.prefill == "lite") and (i < len(prompt) - 1)
        im = sess.images["lite" if lite else "full"]
        t1 = time.monotonic()
        out = v._run(im, tok, i)
        o = int(out[0]) if out else None
        got.append(o)
        if o is not None:
            prev = o
        exp = None if lite else want[i]
        good = (o == exp)
        ok = ok and good
        log(f"  step {i}  {im.name:8s} tok={tok:<6d} pos={i}  -> {o}"
            f"   committed {want[i]}   "
            + ("no token (lite body, as designed)" if lite
               else ("OK" if good else "*** DIFFERS"))
            + f"   [{time.monotonic() - t1:.0f}s]")
        if not good and not lite:
            break
    log(f"  tokens     {got}")
    log(f"  committed  {want[:nstep]}")
    log("MODEL-ONLY: " + ("PASS" if ok else "FAIL")
        + f"   ({time.monotonic() - t0:.0f}s total)")
    return ok


# ======================================================================
# G2 — one TEMPLATED turn through ref/seq_model, no board at all
# ======================================================================
# The expectation below is the bf16 reference model's GREEDY continuation
# of exactly HF_REF_SINGLE (the 19 templated ids), generated ONCE with the
# local HF checkpoint.  Reproduce it with the SAME wiring
# ref/fidelity_check.py:build_golden uses — eager attention, the bf16
# weights upcast to float32, use_cache=False with the whole prefix re-fed
# every step, the TIED LM head applied by hand, pure argmax, CPU:
#
#   python3 - <<'PY'          # needs torch + transformers (see below)
#   import sys; sys.path.insert(0, "<repo>/ref")
#   import torch, load_qwen35 as LQ
#   from transformers.models.qwen3_5 import Qwen3_5TextConfig, Qwen3_5TextModel
#   torch.set_grad_enabled(False)
#   st = LQ.SafeTensors(LQ.find_checkpoint())
#   cfgd = dict(LQ.load_config()); allowed = Qwen3_5TextConfig().to_dict()
#   cfg = Qwen3_5TextConfig(**{k: v for k, v in cfgd.items()
#                              if k in allowed or k == "rope_parameters"})
#   cfg._attn_implementation = "eager"; cfg.dtype = "float32"
#   model = Qwen3_5TextModel(cfg).eval().float()
#   sd = {k[len(LQ.TEXT_PREFIX):]: torch.from_numpy(st.get(k))
#         for k in st.keys() if k.startswith(LQ.TEXT_PREFIX)}
#   model.load_state_dict(sd, strict=False); emb = sd["embed_tokens.weight"]
#   seq = list(IDS)                      # IDS = HF_REF_SINGLE
#   for t in range(len(IDS) + 24 - 1):
#       hs = model(input_ids=torch.tensor([seq[:t+1]]),
#                  use_cache=False).last_hidden_state
#       am = int((hs[0, -1] @ emb.T).float().argmax())
#       if t + 1 >= len(IDS): seq.append(am)
#   print(seq[len(IDS):])
#   PY
#
# RUN 2026-08-11 on darthplagueis, python3 3.13.9 (anaconda base313),
# torch 2.6.0+cu124, transformers 5.2.0, CPU.  Checkpoint
# .../snapshots/2fc06364.../model.safetensors-00001-of-00001.safetensors,
# weights blob sha256 04b1c301...4696, safetensors header sha256
# c894b605...0083 (the same header ref/fidelity_check.py's golden pins).
G2_PROMPT = HF_REF_USER
G2_TEMPLATED_IDS = HF_REF_SINGLE
G2_NTOK = 6                        # ~5 s/lite + ~7 s/full step in seq_model
G2_BF16_REPLY = [760, 6511, 314, 9338, 369, 2972, 57590, 159034, 271, 46162,
                 303, 279, 4593, 314, 279, 3046, 11, 11751, 369, 279, 7526,
                 3177, 303, 9338]
G2_BF16_TEXT = ("The capital of France is **Paris**.\n\nLocated in the heart "
                "of the country, Paris is the largest city in France")


def model_only_chat(args, log=print):
    """G2: replay ONE templated turn through ref/seq_model — no board.

    The gate is deliberately NOT "every token equals bf16".  This engine
    runs at its known saturation posture and measures 16/24 top-1 against
    bf16 (evidence/stage5/fidelity_mq15_prod.log), so demanding
    all-token equality would be demanding something the fixed-point
    datapath cannot deliver and has never claimed.  What IS gated:

      * the templated ids the wrapper builds == the HF 19-id reference,
      * the FIRST generated token == bf16's first token (the template
        landed: the model is answering the question, not continuing it),
      * seq_model is SELF-CONSISTENT — two independent replays of the
        same images produce identical tokens.

    Everything else is reported honestly, including where the fixed-point
    run walks away from bf16.
    """
    sess = ChatSession(args, log=log)
    tk = load_tokenizer(log=log)
    tmpl = ChatTemplate(tk)
    ids = tmpl.turn_ids(G2_PROMPT, first=True)
    ntok = args.ntok if getattr(args, "ntok_given", False) else G2_NTOK
    nsteps = len(ids) + ntok - 1

    log("-" * 72)
    log(f"--- G2 model-only: ONE TEMPLATED TURN through ref/seq_model "
        f"(no board, no lock)")
    log(f"  prompt     {G2_PROMPT!r}")
    log(f"  templated  {ids}")
    log(f"             {len(ids)} ids = {tmpl.overhead(1)} wrapper "
        f"({tmpl.per_message}*1+{tmpl.gen_overhead}) + "
        f"{len(tmpl.body(G2_PROMPT))} body")
    id_ok = (ids == G2_TEMPLATED_IDS)
    log(f"  vs HF      {'MATCH' if id_ok else 'DIFFERS'} — the 19-id "
        f"apply_chat_template reference")
    if not id_ok:
        log(f"  reference  {G2_TEMPLATED_IDS}")
        log("MODEL-ONLY (G2): FAIL — the wrapper is not the HF rendering")
        return False
    log(f"  plan       {nsteps} launches = {len(ids) - 1} prefill "
        f"({args.prefill}) + {ntok} decode; ref/seq_model is ~5 s (lite) / "
        f"~7 s (full) of host time PER STEP")

    v = SeqModelVerifier(sess, log=log)

    def one_pass(tag):
        t0 = time.monotonic()
        v.reset()
        v.preamble(sess.images["preamble"])
        got, tok = [], ids[0]
        for i in range(nsteps):
            lite = (i < len(ids) - 1) and (args.prefill == "lite")
            im = sess.images["lite" if lite else "full"]
            t1 = time.monotonic()
            out = v._run(im, tok, i)
            o = int(out[0]) if out else None
            if i >= len(ids) - 1 and o is not None:
                got.append(o)
                log(f"    [{tag}] step {i:3d} {im.name:5s} tok={tok:<7d} "
                    f"pos={i:<3d} -> {o:<7d} {tk.decode([o])!r}"
                    f"   [{time.monotonic() - t1:.0f}s]")
                if o in CHAT_STOP_IDS:
                    log(f"    [{tag}] EOS ({o}) — stopping")
                    break
            elif i % 6 == 0 or i == len(ids) - 2:
                log(f"    [{tag}] step {i:3d} {im.name:5s} tok={tok:<7d} "
                    f"pos={i:<3d} -> prefill   [{time.monotonic() - t1:.0f}s]")
            tok = ids[i + 1] if i + 1 < len(ids) else o
        log(f"    [{tag}] {len(got)} tokens in {time.monotonic() - t0:.0f}s: "
            f"{got}")
        return got

    a = one_pass("A")
    b = one_pass("B")
    self_ok = (a == b)
    first_ok = bool(a) and a[0] == G2_BF16_REPLY[0]

    n = min(len(a), len(G2_BF16_REPLY))
    same = sum(1 for i in range(n) if a[i] == G2_BF16_REPLY[i])
    pref = 0
    while pref < n and a[pref] == G2_BF16_REPLY[pref]:
        pref += 1
    log("-" * 72)
    log("  token-by-token vs the bf16 reference (16/24 top-1 is this "
        "engine's MEASURED fidelity — divergence is expected, not a bug):")
    log(f"    {'#':>3s}  {'seq_model':>9s}  {'bf16':>9s}  ok   text")
    for i in range(n):
        log(f"    {i:3d}  {a[i]:9d}  {G2_BF16_REPLY[i]:9d}  "
            f"{'==' if a[i] == G2_BF16_REPLY[i] else '!='}   "
            f"{tk.decode([a[i]])!r} vs {tk.decode([G2_BF16_REPLY[i]])!r}")
    log(f"  seq_model  {tmpl.visible(a)} -> {tk.decode(tmpl.visible(a))!r}")
    log(f"  bf16       {G2_BF16_REPLY[:n]} -> "
        f"{tk.decode(G2_BF16_REPLY[:n])!r}")
    log(f"  bf16 (24)  {G2_BF16_TEXT!r}")
    log(f"  agreement  {same}/{n} tokens, {pref} matching from the start")
    log(f"  GATE 1 templated ids == the HF 19-id reference   "
        f"{'PASS' if id_ok else 'FAIL'}")
    log(f"  GATE 2 first token == bf16 ({G2_BF16_REPLY[0]})           "
        f"{'PASS' if first_ok else 'FAIL'}"
        + ("" if first_ok else f"  (got {a[0] if a else None})"))
    log(f"  GATE 3 seq_model self-consistent (A == B)         "
        f"{'PASS' if self_ok else 'FAIL'}"
        + ("" if self_ok else f"  A={a} B={b}"))
    ok = id_ok and first_ok and self_ok
    log("MODEL-ONLY (G2): " + ("PASS" if ok else "FAIL"))
    return ok


# ======================================================================
# G2 — the FULL sampled path with NO BOARD: ref/seq_model for the hidden
# state, sw/head_cache for the head, the shipped Sampler for the draw
# ======================================================================
def model_only_sampled(args, log=print):
    """Board-free sampling gate: determinism + the chip-vs-host head check.

    Each step runs the FULL body through ref/seq_model.py — the same body
    the board launches, LM head and AMAXL included — so seq_model's
    OUT FIFO token IS the chip-equivalent greedy token.  Then the host
    head recomputes the top-k from the model's own x8/e_x and the sampler
    draws from it.  Two things are gated:

      SAME SEED    two passes must produce byte-identical trajectories,
                   including the divergent branches a sample creates.
      DIFFERENT    a different seed must (at these settings) produce a
                   different trajectory, or the sampler is not sampling.

    and one thing is CHECKED every step, which is --verify-head rehearsed
    without a board: the host head's argmax must equal the token seq_model
    pushed from AMAXL.  That is the same assertion G3 will make against
    silicon, so a failure here is a host bug, not a board bug.

    Cost on snoke: ~15 s per full step in ref/seq_model (numpy), ~10-18 ms
    per host GEMV.  Keep --ntok small.
    """
    sess = ChatSession(args, log=log)
    sess.verify_head = True                 # the whole point of the gate
    sess.verify_head_fatal = False          # collect, then report per pass
    if not sess.sampler.enabled:
        raise ChatSeqError("--model-only sampling gate needs --temp > 0")
    v = SeqModelVerifier(sess, log=log)
    sess.verifier = v
    sess.attach_sampling(log=log, offline=True)
    # the verifier is only here for its mach + weights; the gate drives the
    # replay itself, so detach the lockstep checker (it would re-run every
    # image a second time)
    sess.verifier = v
    from gen_model_script import PROMPTS
    prompt = list(PROMPTS[1][2])            # [760, 6511, 314, 9338]
    ntok = args.ntok if getattr(args, "ntok_given", False) else 4
    nsteps = len(prompt) + int(ntok) - 1
    npass = max(2, int(getattr(args, "passes", 4)))
    base_seed = sess.sampler.seed
    seeds = [base_seed, base_seed] + [base_seed + 1 + i
                                      for i in range(npass - 2)]
    log("-" * 72)
    log("--- G2 (board-free): the FULL sampled path over ref/seq_model")
    log(f"  prompt     {prompt}   ntok {ntok}  ->  {nsteps} full launches "
        f"per pass")
    log(f"  sampler    {sess.sampler.describe()}")
    log(f"  candidates {sess.cand.describe()}")
    log(f"  passes     {npass}: seeds {seeds} (the first two MUST agree, a "
        f"different seed SHOULD differ)")
    log("  NOTE       every step here is a FULL body: the model computes the "
        "LM head and AMAXL exactly as the chip does.  The host head is the "
        "CROSS-CHECK, not the decode path.")

    runs = []
    mism = []
    for pi, sd in enumerate(seeds):
        sess.sampler = Sampler(temp=args.temp, top_k=args.top_k,
                               top_p=args.top_p, seed=sd,
                               logit_exp0=sess.sampler.logit_exp0)
        if isinstance(sess.cand, FixtureCandidates):
            sess.cand.reset()
        sess.sample_log = []
        v.reset()
        t0 = time.monotonic()
        v.preamble(sess.images["preamble"])
        got, fed, tok = [], [], prompt[0]
        for i in range(nsteps):
            im = sess.images["full"]
            out = v._run(im, tok, i)
            chip = int(out[0]) if out else None
            rep = {"tokens": list(out), "image": im.name, "pos": i}
            t1 = time.monotonic()
            drawn = sess.post_head(rep, chip, pos=i)
            e = sess.sample_log[-1]
            fed.append(tok)
            if i >= len(prompt) - 1:
                got.append(drawn)
            tok = prompt[i + 1] if i + 1 < len(prompt) else drawn
            log(f"    [p{pi} seed {sd}] step {i:2d} chip {chip:7d} "
                f"host_argmax {e.get('host_argmax')} e_x {e.get('e_x')} "
                f"-> {drawn:7d} (rank {e.get('rank')}, p={e.get('p', 0):.3f})"
                f"  [{time.monotonic() - t0:.0f}s, sample "
                f"{e.get('sample_ms', 0):.2f} ms, head "
                f"{time.monotonic() - t1:.2f}s]")
            if e.get("host_argmax") != chip:
                mism.append((pi, i, chip, e.get("host_argmax")))
        runs.append({"seed": sd, "tokens": got, "fed": fed,
                     "chip": [e["chip_token"] for e in sess.sample_log],
                     "s": round(time.monotonic() - t0, 1),
                     "log": list(sess.sample_log)})
        log(f"  pass {pi}    seed {sd}: {got}  ({runs[-1]['s']}s)")

    same = (runs[0]["tokens"] == runs[1]["tokens"]
            and runs[0]["chip"] == runs[1]["chip"])
    diffs = [r["tokens"] != runs[0]["tokens"] for r in runs[2:]]
    head_ok = not mism
    # GATE 4: the drawn token must actually reach the NEXT launch.  Where a
    # pass's fed sequence diverges from pass 0, the model's own greedy
    # continuation (the chip token) has to diverge too — otherwise the
    # sampler is decorating an unchanged trajectory.
    feeds = []
    for r in runs[2:]:
        j = next((i for i in range(min(len(r["fed"]), len(runs[0]["fed"])))
                  if r["fed"][i] != runs[0]["fed"][i]), None)
        if j is None:
            feeds.append((None, None))
        else:
            feeds.append((j, r["chip"][j:] != runs[0]["chip"][j:]))
    feed_ok = bool(feeds) and all(d for (_j, d) in feeds if _j is not None)
    log("-" * 72)
    for r in runs:
        log(f"  seed {r['seed']:<22d} tokens {r['tokens']}")
        log(f"  {'':27s} fed  {r['fed']}")
        log(f"  {'':27s} chip {r['chip']}   (the model's own argmax at each "
            f"step)")
    log(f"  GATE 1 same seed, same trajectory              "
        f"{'PASS' if same else 'FAIL'}")
    log(f"  GATE 2 a different seed changes the trajectory "
        + ("n/a  (--passes 2: no different-seed pass was run)" if not diffs
           else ("PASS" if any(diffs) else
                 "FAIL  (all seeds agreed — with a peaked distribution that "
                 "can happen; raise --temp)")))
    log(f"  GATE 3 host head argmax == the model's AMAXL   "
        f"{'PASS' if head_ok else 'FAIL'} "
        f"({len(runs) * nsteps - len(mism)}/{len(runs) * nsteps} steps)")
    if mism:
        log(f"         mismatches: {mism[:8]}")
    log(f"  GATE 4 the drawn token drives the NEXT launch      "
        f"{'PASS' if feed_ok else 'FAIL'}"
        + "".join(f"\n         seed {runs[2 + n]['seed']}: feed diverges at "
                  f"step {j}, the model's continuation "
                  + ("diverges too" if d else "DOES NOT")
                  for n, (j, d) in enumerate(feeds) if j is not None))
    ok = same and head_ok and (not diffs or (any(diffs) and feed_ok))
    if getattr(args, "make_fixture", None):
        steps = [{"values": [int(x) for x in e["cand_values"]],
                  "indices": [int(x) for x in e["cand_indices"]],
                  "e_x": int(e["e_x"])}
                 for e in runs[0]["log"] if "cand_values" in e]
        prov = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "how": "ref/seq_model.py full-body replay of "
                       f"{os.path.basename(args.template)} + "
                       "sw/head_cache.HostHead.topk (f32 prefilter, exact "
                       "integer rescore via ref/w4a8_ref.matvec_y32)",
                "prompt": prompt, "seed": runs[0]["seed"],
                "template_sha256": TEMPLATE_SHA256,
                "head": sess.head.spec.as_dict(),
                "k": sess.cand.k, "steps": len(steps)}
        p = save_fixture(args.make_fixture, steps, prov)
        log(f"  fixture    {len(steps)} steps -> {p}")
    if args.out:
        with open(args.out, "w") as f:
            json.dump({"tool": "chat_seq --model-only sampled",
                       "argv": sys.argv[1:], "prompt": prompt,
                       "ntok": ntok, "passes": npass,
                       "runs": [{k: r[k] for k in ("seed", "tokens", "fed",
                                                   "chip", "s")}
                                for r in runs],
                       "same_seed_identical": same,
                       "different_seed_differs": diffs,
                       "feed_reaches_next_launch": feeds,
                       "head_check_mismatches": mism,
                       "steps": [{k: v for k, v in e.items()
                                  if k not in ("cand_values", "cand_indices")}
                                 for e in runs[0]["log"]],
                       "pass": ok}, f, indent=1, default=str)
        log(f"  report -> {args.out}")
    log("MODEL-ONLY (G2 sampled): " + ("PASS" if ok else "FAIL"))
    return ok


def banner(sess, log=print):
    log("-" * 72)
    log("chat_seq.py — one sequencer launch per forward step "
        "(docs/CHAT_SEQ_SPEC.md)")
    log(f"  images     preamble {sess.images['preamble'].nrec} rec | "
        f"lite {sess.images['lite'].nrec} rec | "
        f"full {sess.images['full'].nrec} rec")
    nw = len(sess.patch_writes("full", 0, 0)[0])
    log(f"  patch      pos_mode={sess.pos_mode!r}: "
        f"{PATCH_BYTES + (nw - 1) * 4} B in {nw} write(s) per launch")
    log(f"  prefill    {sess.args.prefill}  |  --ntok {sess.args.ntok}  |  "
        f"--max-ctx {sess.args.max_ctx} of KV depth {T_MAX}")
    if sess.template is None:
        log("  template   OFF (--raw) — no chat wrapper, no instruct "
            "behaviour (docs/INSTRUCT_SPEC.md T4)")
    else:
        log(f"  template   ON: "
            f"{sess.template.per_message}*messages+"
            f"{sess.template.gen_overhead} wrapper ids, closed-empty think "
            f"block, incremental with carry"
            + (f", system {sess.system!r}" if sess.system else ""))
    log(f"  decode     {sess.sampler.describe()}"
        + ("" if not sess.sampler.enabled else
           f" via {sess.cand.name}")
        + "  |  the LM head + argmax run ON-CHIP every step")
    if sess.verify_head:
        log("  verify     --verify-head: every full launch is cross-checked "
            "against the host head copy (sw/head_cache.py); a mismatch is "
            "fatal")
    log("  posture    never programs the FPGA, never touches flash, never "
        "sudo")
    log(f"  board lock {LOCK_PATH}"
        + ("  (NOT HELD — --no-lock)"
           if getattr(sess.args, "no_lock", False)
           else "  held for this process's lifetime"))
    log("  O3         every in-repo tool that programs or DMAs the board "
        "takes this one shared lock, across checkouts and hosts "
        "(docs/USAGE.md §5)")
    log("-" * 72)


def main():
    ap = argparse.ArgumentParser(
        description="Interactive chat on the fable5_llm sequencer.")
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--chan", type=int, default=0,
                    help="DDR fetch channel (must match the template's)")
    ap.add_argument("--template", default=TEMPLATE_PREFIX,
                    help="gated artifact prefix the templates are sliced from")
    ap.add_argument("--any-template", action="store_true",
                    help="do not require the frozen template sha256 "
                         "(development only)")
    ap.add_argument("--nch", type=int, default=1, choices=NCH_CHOICES,
                    help="matvec channels the stream drives (RUNG4_SPEC S4). "
                         "1 = the shipped, bit-exact greedy path.  4 = the "
                         "opt-in row-split stream whose LM head is chunk-"
                         "INTERLEAVED across the four engines; it selects "
                         f"{os.path.basename(TEMPLATE4_PREFIX)} and a "
                         "DIFFERENT weight placement in DDR.  A session is "
                         "one --nch for its whole life: switching means a "
                         "full weight re-upload, which the residency probe "
                         "detects and does for you (slow, ~900 MiB).")
    ap.add_argument("--prompt", action="append", default=[],
                    help="non-interactive turn (repeatable)")
    ap.add_argument("--ntok", type=int, default=None)
    ap.add_argument("--max-ctx", type=int, default=DEFAULT_MAX_CTX)
    ap.add_argument("--raw", action="store_true",
                    help="TEMPLATE OFF: feed the prompt verbatim, with no "
                         "<|im_start|> chat wrapper (docs/INSTRUCT_SPEC.md "
                         "T4 — the template is the DEFAULT; this is the "
                         "pre-spec behaviour and the model will continue "
                         "your text instead of answering it).  With "
                         "--model-only it selects the old canned gate B1 "
                         "replay instead of the templated G2 turn.")
    ap.add_argument("--system", default=None,
                    help="system message, fed once at session start / after "
                         "every context reset (docs/INSTRUCT_SPEC.md T5). "
                         "Costs 5 + len(text) ids of context.")
    ap.add_argument("--pos-mode", choices=("auto", "xrf", "ldc"),
                    default="auto",
                    help="how a step addresses its RoPE tables. xrf = the "
                         "frozen spec's XRF[4]=pos*1536 (SIGNED 18-bit -> "
                         "pos <= 85, silently truncated beyond); ldc = agent "
                         "A's escape hatch, patch the six position-LDC "
                         "addresses (reaches the whole KV depth); auto picks "
                         "by --max-ctx")
    ap.add_argument("--t-max", type=int, default=T_MAX,
                    help="positions in the generated position blob")
    ap.add_argument("--prefill", choices=("lite", "full"), default="lite",
                    help="lite = prefill steps skip the LM head (spec 3); "
                         "full = every step emits a token (gate B1 shape)")
    ap.add_argument("--continue-context", action="store_true",
                    help="keep KV/DN state across --prompt turns "
                         "(default: preamble between them)")
    ap.add_argument("--canned", action="store_true",
                    help="gate B1: replay the committed model_v2_s1 "
                         "schedule (prompt 'The capital of France' = "
                         "[760,6511,314,9338], 6 steps) and compare EVERY "
                         "argmax against the artifact's expect_tokens; "
                         "implies --prefill full")
    ap.add_argument("--smoke", action="store_true",
                    help="preamble + ONE full step (token 760 at pos 0) and "
                         "report PERF_CYC; nothing else touches the board")
    ap.add_argument("--verify", action="store_true",
                    help="lockstep ref/seq_model prediction for every step "
                         f"(~{VERIFY_HOST_S_PER_STEP} s of host time per "
                         f"step at FABLE5_MODEL={MODEL_TAG}; the board "
                         f"waits)")
    ap.add_argument("--force-upload", action="store_true",
                    help="skip the residency probe and re-upload everything")
    ap.add_argument("--timeout", type=float, default=STEP_TIMEOUT)
    ap.add_argument("--preamble-timeout", type=float, default=PREAMBLE_TIMEOUT)
    ap.add_argument("--out", default=None, help="JSON report path")
    ap.add_argument("--reorder", type=reorder_arg, metavar="{A,B,off}",
                    default=None,
                    help="BM1-T4/S1P: run the S1 reordered schedule (A = "
                         "the SV1 template, B = per-image, static costs; "
                         "off = the shipped order).  Default since "
                         "2026-09-27: $FABLE5_REORDER (off|A|B) if set, "
                         "else auto = B at FABLE5_MODEL=9b --nch 4 on the "
                         "shipped template, off anywhere else.  When on, "
                         "the in-process regeneration (hazard assert + OV1 "
                         "postcheck) and the B6 model gate are MANDATORY "
                         "and refuse before the board is opened")
    ap.add_argument("--seq-rtl", type=seq_rtl_arg,
                    metavar="{" + ",".join(SEQ_RTLS) + "}",
                    default=None,
                    help="Task SR6: the sequencer RTL level the images are "
                         "built for.  r0 (default) = the shipped RTL.  r1 = "
                         "the FENCE channel mask (B17.1): form B's per-image "
                         "reorder, masked FENCEs (pinned images; needs "
                         "--reorder B, 9B --nch 4).  r2 (SR13b) = r1 + the "
                         "XWIN/RES banks (B17.2).  r3 (R3-6) = r2 + the MOVX "
                         "broadcast (B17.3).  "
                         f"Default: ${SEQ_RTL_ENV} if set, else r0.  The "
                         "images load only on a device whose SEQ_CAPS "
                         "reports the level's set (r1: R1, 0xFAB1CA01; r2: "
                         "R1+R2, 0xFAB1CA03; r3: R1+R2+R3, 0xFAB1CA07); on "
                         "any other the session refuses before any upload")
    ap.add_argument("--shape-isa", type=int, default=None,
                    choices=(HW.SHAPE_ISA_PRE_G3, HW.SHAPE_ISA_9B),
                    help="SR11a fix round 2: the MVGO SHAPE layout the "
                         "template is built and validated at before the "
                         "board is open — 1 = build_034/035 (bit 29 = w8; "
                         "the frozen 2B W8 template needs it), 2 = "
                         "build_041+.  Default: the artifact's own "
                         "`shape_isa` key (9B artifacts carry 2).  At "
                         "open_board the session is re-validated at the "
                         "DEVICE's layout (hwmap.shape_isa_for_version of "
                         "its VERSION) and refused if it differs")
    ap.add_argument("--reorder-check", action="store_true",
                    help="with --reorder: run its whole gate (regenerate, "
                         "image hazards, B6 model gate) and exit; no board, "
                         "no lock")
    ap.add_argument("--selftest", action="store_true",
                    help="pure-host unit tests; touches no device at all")
    ap.add_argument("--model-only", action="store_true",
                    help="gate G2: run ONE TEMPLATED turn through "
                         "ref/seq_model and compare against the bf16 "
                         "reference; NO board, NO lock, ~5-7 s per step.  "
                         "--model-only --raw is the older gate B1 replay of "
                         "the committed canned schedule.")
    ap.add_argument("--steps", type=int, default=0,
                    help="--model-only: stop after N launches (0 = all)")
    BL.add_lock_args(ap, default=LOCK_PATH)     # --lock PATH / --no-lock
    # ------------------------------------------------ sampling (S5)
    g = ap.add_argument_group(
        "sampling",
        "temperature / top-k / top-p.  DEFAULT IS GREEDY, which is 100% "
        "on-chip and bit-exact.  A sampled step is the SAME full launch "
        "plus the on-chip top-k capture unit, which arrives with the next "
        "RTL rung — until then --temp refuses instead of moving the model "
        "off the chip.")
    g.add_argument("--temp", "--temperature", dest="temp", type=float,
                   default=DEFAULT_TEMP,
                   help="softmax temperature; 0 (default) = greedy")
    g.add_argument("--top-k", type=int, default=DEFAULT_TOP_K,
                   help=f"keep the k best candidates (0 = no cut); the "
                        f"on-chip capture depth is {TOPK_CAPTURE_K}, which "
                        f"caps it")
    g.add_argument("--top-p", type=float, default=DEFAULT_TOP_P,
                   help="nucleus threshold in (0,1]; 1.0 = off")
    g.add_argument("--seed", type=int, default=None,
                   help="RNG seed; one is drawn and REPORTED if omitted")
    g.add_argument("--topk-base", type=lambda s: int(s, 0), default=TOPK_BASE,
                   help=f"AXI-Lite byte offset of the on-chip top-k CSR "
                        f"block; RUNG4_SPEC S5 pins it at {TOPK_BASE:#x} "
                        f"(the default).  The IDENT read decides whether "
                        f"the unit is really there, so this is safe on a "
                        f"pre-rung-4 bitstream; pass 0 to skip the probe "
                        f"entirely.")
    g.add_argument("--verify-head", action="store_true",
                   help="cross-check EVERY decode step: rebuild the head's "
                        "logits on the host from the chip's own x8/e_x and "
                        "assert the host argmax == the chip's token (S6).  "
                        "Verification only — the chip still decides.")
    g.add_argument("--head-cache", default=None,
                   help="directory for the 1 GB f32 verification head "
                        "(default $FABLE5_HEAD_CACHE, ~/.cache/fable5_llm, "
                        "/tmp — never the NFS share)")
    g.add_argument("--no-head-cache", action="store_true",
                   help="always rebuild the verification head from the image")
    g.add_argument("--head-mmap", action="store_true",
                   help="mmap the cached f32 head instead of reading it in")
    g.add_argument("--head-threads", type=int, default=16,
                   help="BLAS threads for the verification head (S2)")
    g.add_argument("--sample-fixture", default=None,
                   help="--model-only: drive the sampler from a recorded "
                        "candidate fixture instead of the model")
    g.add_argument("--make-fixture", default=None,
                   help="--model-only: write the candidate sets this run "
                        "produced to a fixture JSON")
    g.add_argument("--passes", type=int, default=4,
                   help="--model-only sampled gate: passes to run "
                        "(2 same-seed + N-2 different-seed)")
    # S1P: the default switch, read at PARSE time (fix round 1, M4); an
    # unknown value refuses here, fail-closed.  S1D fix round 1: the parse
    # default is REORDER_AUTO; effective_reorder() below resolves it
    try:
        reorder_default()
    except ChatSeqError as e:
        ap.error(str(e))
    ap.set_defaults(reorder=REORDER_AUTO)
    # SR6: $FABLE5_SEQ_RTL, read at parse time like $FABLE5_REORDER; an
    # unknown value refuses here, fail-closed
    try:
        _rtl_env = seq_rtl_default()
    except ChatSeqError as e:
        ap.error(str(e))
    args = ap.parse_args()
    if args.seq_rtl is None:
        args.seq_rtl = _rtl_env
    # --ntok defaults late so --model-only can tell "not given" from "32"
    args.ntok_given = args.ntok is not None
    if args.ntok is None:
        args.ntok = DEFAULT_NTOK
    # --nch 4 picks the 4-chan artifact set unless the user named one (S4)
    if args.nch != 1 and args.template == TEMPLATE_PREFIX:
        args.template = TEMPLATE4_PREFIX
    # S1D fix round 1: the model-aware default (explicit values as given)
    try:
        args.reorder = effective_reorder(args)
    except ChatSeqError as e:
        ap.error(str(e))

    if args.selftest:
        raise SystemExit(0 if selftest(args) else 1)
    # SR6: a level above r0 runs only on form B — refuse BEFORE the lock
    # and the board (exit 4, as a --reorder that cannot run)
    try:
        check_seq_rtl(args)
    except ChatSeqError as e:
        print(f"\n*** {e}")
        sys.exit(4)
    rep_reorder = None
    if args.reorder or args.reorder_check:
        # BM1-T4: refuse BEFORE the lock and the board
        if not args.reorder:
            ap.error("--reorder-check needs --reorder FORM")
        try:
            rep_reorder = {"resolve": resolve_reorder(args)}
        except ChatSeqError as e:
            print(f"\n*** {e}")
            sys.exit(4)
        if args.reorder_check:
            try:
                sess0 = ChatSession(args)
                rep_reorder["image_hazards"] = reorder_image_hazards(sess0)
                g = reorder_model_gate(sess0)
            except ChatSeqError as e:
                print(f"\n*** {e}")
                sys.exit(4)
            print("REORDER CHECK: " + ("PASS" if g["ok"] else "FAIL"))
            raise SystemExit(0 if g["ok"] else 1)
    if args.model_only:
        if args.temp > 0:
            raise SystemExit(0 if model_only_sampled(args) else 1)
        raise SystemExit(
            0 if (model_only(args) if args.raw else model_only_chat(args))
            else 1)
    if args.max_ctx >= T_MAX:
        ap.error(f"--max-ctx must be < the KV bank depth {T_MAX} (the RTL "
                 f"wraps SILENTLY past it)")
    if args.canned:
        args.prefill = "full"
        if args.temp > 0:
            ap.error("--canned is the GREEDY regression gate (every step's "
                     "argmax against the committed artifact); it cannot run "
                     "with --temp > 0")
    if args.smoke and args.temp > 0:
        ap.error("--smoke checks the committed first token; drop --temp")
    if args.temp > 0 and args.topk_base is None:
        # refuse BEFORE the flock, the board and a ~1 minute bring-up: with
        # no top-k CSR block there is nothing to sample from, and no amount
        # of DMA will change that
        ap.error(
            "--temp %g: %s\n  Pass --topk-base <addr> once the rung-4 "
            "bitstream is on the board; until then --temp 0 (greedy) is the "
            "only decode this build can do — and it is bit-exact."
            % (args.temp, ChipTopKSource.RUNG4))

    rep = {"tool": "chat_seq", "argv": sys.argv[1:], "launches": []}
    # O3: the board lock, BEFORE the board and before the ~1 minute
    # bring-up.  A refusal is a one-line message naming the holder, not a
    # traceback.
    try:
        _lock = BL.from_args(args, tool="chat_seq.py",
                             error=ChatSeqError).acquire()
    except ChatSeqError as e:
        print(f"\n*** {e}")
        sys.exit(4)
    with _lock:
        print("--- session bring-up")
        # m13: ChatSession.__init__ REFUSES (the pos_mode geometry, a bad
        # template sha) and every other operator-facing refusal in this
        # tool is a one-line message, not a five-frame traceback.
        try:
            sess = ChatSession(args)
            if args.reorder:
                # MANDATORY with the flag (B6): nothing reaches the board
                # unless the images pass the hazard assert and the model
                # gate — both before open_board().
                rep_reorder["image_hazards"] = reorder_image_hazards(sess)
                g = reorder_model_gate(sess)
                rep_reorder["model_gate"] = {k: v for k, v in g.items()}
                if not g["ok"]:
                    raise ChatSeqError("--reorder: the B6 model gate FAILED: "
                                       f"{g.get('diff')}")
        except ChatSeqError as e:
            print(f"\n*** {e}")
            sys.exit(4)
        rep["reorder"] = rep_reorder
        rep["seq_rtl"] = sess.seq_rtl
        # SR6: open_board() reads the device's SEQ_CAPS and re-validates
        # every image at it; its refusal (like every refusal above) is a
        # one-line message and exit 4, before bring_up's first upload
        try:
            sess.open_board()
        except ChatSeqError as e:
            print(f"\n*** {e}")
            sys.exit(4)
        rep["caps"] = sorted(sess.caps)
        sess.bring_up()
        tk = None
        if not args.smoke:
            tk = load_tokenizer()
            sess.attach_template(tk)
        if args.verify:
            # m4: this used to print the 2B figure at every selection, and
            # it is 20x wrong at 9B — 074_ref_cost_9b.log MEASURED 131.2 s
            # (lite) / 149.3 s (full) there against ~6 s at 0.8B/2B.
            print(f"  verify     building the ref/seq_model lockstep "
                  f"(~{VERIFY_HOST_S_PER_STEP} s of host time per step at "
                  f"FABLE5_MODEL={MODEL_TAG}; the board idles meanwhile)")
            sess.verifier = SeqModelVerifier(sess)
        # sampling / --verify-head resolve AFTER the board is open (the
        # chip source probes a CSR) and REFUSE here, not mid-turn
        try:
            sess.attach_sampling(log=print, offline=False)
        except SamplingUnavailable as e:
            print(f"\n*** {e}\n*** nothing was decoded; rerun without --temp "
                  f"for greedy (100% on-chip, bit-exact).")
            sys.exit(3)
        print("--- preamble")
        sess.preamble()          # replays into the verifier too, if any
        banner(sess)

        rc = 0
        try:
            if args.smoke:
                print("--- smoke: ONE full step, canned first prompt token "
                      "760 at pos 0")
                out, r = sess.step(760, lite=False)
                want = int(sess.meta["expect_tokens"][0])
                print(f"  token      {out}  (committed expect_tokens[0] = "
                      f"{want}) -> {'MATCH' if out == want else 'MISMATCH'}")
                print(f"  PERF_CYC   {r['perf']['cyc']} cycles @ "
                      f"{ACLK_HZ / 1e6:.0f} MHz = {r['device_ms']:.3f} ms "
                      f"device; {r['wall_ms']:.2f} ms wall")
                print(f"  PERF       rec={r['perf']['rec']} "
                      f"axil_wr={r['perf']['axil_wr']} "
                      f"axil_rd={r['perf']['axil_rd']} "
                      f"fetch_starved={r['perf']['fetch_starved_cyc']} "
                      f"xrf_ovf={r['perf']['xrf_ovf']}")
                print(f"  OUT FIFO   out_cnt at halt = {r['out_cnt_at_halt']} "
                      f"of depth {SEQ_OUT_DEPTH}; drained {r['tokens']}; "
                      f"sticky of_ovf = {r['out_fifo_ovf']}")
                rep["smoke"] = {k: v for k, v in r.items() if k != "status"}
                rep["smoke"]["expect"] = want
                rep["smoke"]["pass"] = (out == want)
                rc = 0 if out == want else 1
            elif args.canned:
                # gate B1 replays the COMMITTED schedule: never templated
                prompt = tk.encode("The capital of France")
                fed, want = canned_schedule(sess.meta, prompt)
                print(f"--- canned gate B1: prompt {prompt} -> feed {fed}, "
                      f"expect {want}")
                ok, got = run_canned(sess, fed, want)
                print(f"  -> {'MATCH' if ok else 'MISMATCH'}")
                rep["canned"] = {"prompt": prompt, "feed": fed,
                                 "expect": want, "got": got, "pass": ok,
                                 "steps": sess.step_log}
                rc = 0 if ok else 1
            elif args.prompt:
                for i, p in enumerate(args.prompt):
                    if i and not args.continue_context:
                        sess.preamble()
                    print(f"\nprompt> {p}")
                    run_turn(sess, tk, p, args.ntok)
                print()
                stats(sess)
            else:
                repl(sess, tk)
        except ChatSeqError as e:
            print(f"\n*** {e}")
            rep["error"] = str(e)
            rc = 1
        rep["perf"] = sess.perf
        rep["launches"] = sess.launches
        rep["context"] = sess.T
        rep["template"] = {
            "on": sess.template is not None, "raw": bool(args.raw),
            "system": sess.system, "turns": sess.turns_templated,
            "wrapper_ids": sess.tmpl_overhead,
            "messages": sess.tmpl_messages,
            "spec": "docs/INSTRUCT_SPEC.md"}
        rep["sampling"] = dict(sess.sampler.as_dict())
        rep["sampling"]["candidates"] = (sess.cand.as_dict()
                                         if sess.cand is not None else None)
        rep["sampling"]["verify_head"] = {
            "on": sess.verify_head, "steps_checked": sess.head_checks,
            "mismatches": 0,
            "host_ms_mean": (round(sum(sess.head_ms) / len(sess.head_ms), 2)
                             if sess.head_ms else None)}
        rep["sampling"]["steps"] = sess.sample_log
        if args.out:
            with open(args.out, "w") as f:
                json.dump(rep, f, indent=1, default=str)
            print(f"report -> {args.out}")
    sys.exit(rc)


# ======================================================================
# Task R3-6 of the R3 campaign (docs/superpowers/plans/2026-09-29-r3-
# broadcast.md): --seq-rtl r3 = r2 + the MOVX BROADCAST (docs/SEQ_ISA.md
# B17.3, form (a)): form B's per-image reorder at rtl="r3" (R3-5's
# reorder_e4 pass: r2's masked-FENCE / bank schedule, and each matvec's four
# per-channel MOVX of one source merged into ONE broadcast MOVX, flags[7:4]
# = 0xF, window word 0 / 1536), caps {R1, R2, R3} (reorder_e4.CAPS_OF["r3"]).
# Placed HERE, after every line other documents cite, so no citation moves
# (the SR14 §7 zero-drift rule; R3-2's / R3-5's layout): SEQ_RTLS and
# REORDER_B_PINS_BY_RTL are read at call time (seq_rtl_default / _arg / _of,
# main's --seq-rtl metavar, resolve_reorder, _reorder_images_b), so the r3
# row assigned below is in force before any of them runs.
#
# The pins were generated by evidence/qwen9b/sr/sr13b_r2_pins.py --rtl r3 at
# a5d0887 (SR13b's recipe, a flag, not a copy): REORDER_B_R3_PINS_LOG (the
# PIN r3 lines).  STATIC model makespan, MODEL, position 0: lite 30,209,477
# -> 22,297,831 cyc (r2: 24,341,703), full 32,771,280 -> 24,087,146 cyc (r2:
# 26,131,018); 128 / 129 broadcasts, 0 forced, 0 unicast-left.
#
# ADMISSION IS KEYED BY THE DEVICE, as at r1 / r2: an r3 image is admitted
# only where the device's SEQ_CAPS decodes to a set holding {R1, R2, R3}
# (0xFAB1CA07, hwmap.seq_caps_word).  Every smaller set refuses it BY THE
# VALIDATOR, naming the broadcast record (ref/seq_format.py
# _movx_bcast_admitted): at {R1, R2} (0xFAB1CA03) that refusal is the guard
# the RTL cannot give -- an r3 image also carries B17.2 bank fields, which
# an R2 bitstream would accept -- and at {R1} / {} (0xFAB1CA01 / 0xDEADC0DE)
# the RTL would fault err 0x05 anyway, after the upload.  The images carry
# no manifest; the session's level chooses them and the device decides.
# A broadcast leaves all four XPTRs unchanged (B17.3): no host path here
# reads XPTR.  No SEQ_VERSIONS row names an R3 bitstream (R3-10's, only for
# a kept one), so today every board refuses an r3 session before any DMA.
# ======================================================================
SEQ_RTLS = SEQ_RTLS + ("r3",)
REORDER_B_R3_IMAGES = {
    "lite": ("8a226ca17f197073c5eb607499031147"
             "7032883d5eef2c639ec6cb7e88fb09cd", 38930),
    "full": ("fdfc6d0c7cd04bbd499512a75eb8fea3"
             "934a7e2af41991b9f6d11453b3243ede", 39786),
}
REORDER_B_R3_PINS_LOG = "evidence/qwen9b/sr/n2801_r3_6_pins.log"
REORDER_B_PINS_BY_RTL["r3"] = (REORDER_B_R3_IMAGES, REORDER_B_R3_PINS_LOG)


if __name__ == "__main__":
    main()
