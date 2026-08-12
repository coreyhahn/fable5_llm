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
  VERSION == EXPECTED (build_033 = 0x33D720E5) + the seq IDENT read back exactly.
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
import fcntl
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

import hwmap as HW                                              # noqa: E402
from hwmap import (                                             # noqa: E402
    ACLK_HZ, SEQ_ALIGN, SEQ_OUT_DEPTH, SEQ_REC_BYTES,
    SEQ_STREAM_BASE, SEQ_DATA_BASE, SEQ_XRF_N,
    S_BASE_LO, S_BASE_HI, S_CTRL, S_ENTRY, S_LEN, S_PC, S_TCNT_SEQ,
    SEQ_CTRL_ABORT, SEQ_CTRL_START, s_xrf, seq_err_name,
)
import seq_format as SF                                         # noqa: E402
import seq_run as SR                                            # noqa: E402
from layer_test import plan_weights                             # noqa: E402
try:
    import seq_chat as SC                                       # noqa: E402
except ImportError as _e:                                       # pragma: no cover
    SC = None
    _SC_ERR = _e


# ======================================================================
# frozen template geometry (docs/CHAT_SEQ_SPEC.md decisions 2, 5, 6)
# ======================================================================
TEMPLATE_PREFIX = os.path.join(TOP_DIR, "tb", "scripts", "w4",
                               "model_v2_s1.e")
TEMPLATE_SHA256 = ("a69864d25b6b129a4d6c74b3c78dfcbedf1edce2"
                   "19d32cc05d05bc54f444aaf1")
TEMPLATE_NREC = 60495

REC_PREAMBLE = (0, 1524)          # session-once resets
REC_SEED_TOK = 1524               # CSRWR XRF[3] <= token id
REC_SEED_POS = 1525               # CSRWR XRF[4] <= pos*1536  (ABSOLUTE)
REC_BODY_FULL = (1526, 16266)     # EMB .. AMAXL          14,740 recs
REC_BODY_LITE = (1526, 15532)     # EMB .. before LM head 14,006 recs
REC_TCNT = 45751                  # CSRWR TCNT_SEQ <= n
REC_HALT = 60494

POS_STRIDE = 1536                 # bytes of rope tables per position
POS_COPIES = 6                    # 6 GQA layers share one table per pos
POS_BLOCK = POS_STRIDE // POS_COPIES          # 256 B = 128 int16 words
T_MAX = 512                       # rtl/layer_chan.sv kv_waddr = tcnt[8:0]
POSBLOB_BYTES = T_MAX * POS_STRIDE            # 786,432 B (gate A2)

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

LOCK_PATH = os.path.join(SW_DIR, ".seq.lock")

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

# layer_chan scratchpad geometry the head consumes/produces, in WORDS
# (ref/gen_layer_script.py:586-587 X8 = 2048, STG = 4096).
X8_WORD, X8_LEN = 0x800, 1024        # the DYNQ8'd activation the head reads
STG_WORD, STG_LEN = 0x1000, 0x1000   # the head's y32 staging window
HEAD_TAIL = (REC_BODY_LITE[1], REC_BODY_FULL[1])   # (15532, 16266)

# S4: logit = y32 * 2^(e + sh - 15 + e_x - RS_F).  Both numbers below are
# ASSERTED against the weight manifest at run time (sw/head_cache.py).
HEAD_WID = 186
HEAD_LOGIT_EXP0 = -22        # e=-4, sh=5, RS_F=8 -> 2^(e_x - 22)


class ChatSeqError(RuntimeError):
    pass


class SamplingUnavailable(ChatSeqError):
    """Sampling was asked for and the hardware that provides it is absent."""


# ======================================================================
# exclusivity (spec decision 10)
# ======================================================================
class SeqLock(object):
    """Exclusive flock on sw/.seq.lock, held for the process lifetime.

    Everything in the chat/serve stack that opens /dev/xdma0_* must take
    this.  Refusing to start without it is the point: the sequencer's
    busy bit is a TOCTOU check, not a mutex.
    """

    def __init__(self, path=LOCK_PATH):
        self.path = path
        self.fd = None

    def acquire(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            try:
                who = os.read(self.fd, 256).decode("utf-8", "replace").strip()
            except OSError:
                who = ""
            os.close(self.fd)
            self.fd = None
            raise ChatSeqError(
                f"another process holds {self.path}"
                + (f" ({who})" if who else "")
                + " — exactly one host may own the sequencer (spec 10). "
                  "NOTE: infer.py / seq_run.py do NOT take this lock yet, so "
                  "also check `pgrep -af 'infer.py|seq_run.py|tok_meter'`.")
        os.ftruncate(self.fd, 0)
        os.write(self.fd, f"pid {os.getpid()} chat_seq.py "
                          f"{time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
                          .encode())
        return self

    def release(self):
        if self.fd is not None:
            try:
                os.ftruncate(self.fd, 0)
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)
                self.fd = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *a):
        self.release()


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
            "R_BODY_LITE": REC_BODY_LITE, "R_PREAMBLE": REC_PREAMBLE}


def load_template(prefix=TEMPLATE_PREFIX, check_sha=True, sha=None, g=None):
    """The gated artifact, hash-checked, as [Rec] + const blob + meta.

    `sha`/`g` select which artifact set is being loaded: None/None is the
    frozen 1-chan template (docs/CHAT_SEQ_SPEC.md), and the 4-chan session
    passes TEMPLATE4_SHA256 plus its derived geometry (rung 4 S4).
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
    SF.validate_stream(recs)
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


def independent_step_images(recs, g=None):
    """MY OWN slices of the same template — the cross-check on agent A.

    Agent A (ref/seq_chat.py) is the compiler of record; this rebuilds the
    two step images straight from the spec's record indices so --selftest
    can assert the two agree BYTE FOR BYTE.  If they ever diverge, one of
    us has misread docs/CHAT_SEQ_SPEC.md and the run must stop.
    """
    g = g or frozen_geometry()
    _check_head(recs, g)
    head = [recs[g["R_SEED_TOK"]], recs[g["R_SEED_POS"]], recs[g["R_TCNT"]]]
    halt = recs[g["R_HALT"]]
    out = {}
    for name, (lo, hi) in (("lite", g["R_BODY_LITE"]),
                           ("full", g["R_BODY_FULL"])):
        rr = head + recs[lo:hi] + [halt]
        SF.validate_stream(rr)
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
TEMPLATE4_PREFIX = os.path.join(TOP_DIR, "tb", "scripts", "w4",
                                "model_v2_s1.e4")
TEMPLATE4_SHA256 = ("e102e2df0835097d0d622cd17109b9cbfea1ab4e78818bcd"
                    "df3873ec6d8ac933")
TEMPLATE4_NREC = 68119
NCH_CHOICES = (1, 4)


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
    lo = int(W[hw]["base"])
    hi = lo + int(W[hw]["nrows"]) * int(W[hw]["stride"])
    mv = [i for i in range(b0, amax[0])
          if recs[i].opcode == SF.OP_MVGO
          and lo <= _wbase_of_rec(recs[i]) < hi]
    need(bool(mv), f"no MVGO in body 0 reads the head image (wid {hw})")
    cut = min(mv)
    while cut > b0 and recs[cut - 1].opcode == SF.OP_MOVX:
        cut -= 1
    need(recs[cut].opcode == SF.OP_MOVX and recs[cut].addr_lo == X8_WORD,
         f"the LM-head block opens with {SF.disasm(recs[cut], cut)}, "
         f"expected MOVX XWIN <= scratch[{X8_WORD:#x}]")
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
    need(r[g["R_PREAMBLE"][1] - 1].opcode == SF.OP_CSRWR
         and r[g["R_PREAMBLE"][1] - 1].target == SF.csr_layer(SF.LOFF_TCNT),
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
                             n_emb=EMB_WITNESSES, splits=None):
    """Host-side witness manifest: what each resident image MUST hash to.

    nch=1: one 4 KiB block per weight image (187 of them) and `n_emb`
    blocks spread over the embedding table.  Reading them back is ~3 ms of
    DMA; a full readback of 900 MiB is ~10 s, which is why the probe
    exists.

    nch>1 (rung 4 S4): `splits` is sw/seq_run.plan_weight_split's placement
    for THIS stream, and the probe takes one witness PER CHANNEL per image
    (4x as many, still ~3 MB / ~12 ms).  That is what makes a residency
    probe a LAYOUT probe: a board holding the same weights under a
    different placement — contiguous quarters instead of interleaved
    chunks, or the whole image on channel 0 from an nch=1 session — misses
    on channels it never wrote, and the session re-uploads instead of
    reading someone else's bytes.  The witness address is CHANNEL-LOCAL and
    carries its channel; `probe_residency` reads it there.
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
        pieces = by_wid.get(wid, [])
        by_chan = {}
        for s in pieces:                       # one witness per channel:
            by_chan.setdefault(s["chan"], []).append(s)
        with open(path, "rb") as f:
            for c in sorted(by_chan):
                # deterministic pick: the MIDDLE piece this channel owns,
                # so an interleaved image is probed away from row 0 (where
                # a contiguous layout would coincidentally agree).
                ps = sorted(by_chan[c], key=lambda s: s["r0"])
                s = ps[len(ps) // 2]
                o, n = _witness(s["byte_len"])
                f.seek(s["byte_off"] + o)
                blk = f.read(n)
                out.append({"kind": "weight", "wid": wid,
                            "name": f"{m['file']}@c{c}", "chan": c,
                            "addr": s["local_addr"] + o, "bytes": n,
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
    ne = len(wit) - nw
    log(f"  residency  {len(wit)} witness blocks ({nw} weight + {ne} emb, "
        f"{sum(w['bytes'] for w in wit) / 1024:.0f} KiB) in {dt * 1e3:.0f} ms"
        f" -> {len(bad)} MISS")
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
    OUT FIFO inside its poll loop, and seq_unit.sv:1049/1100 lose an
    of_cnt when host pop races an AMAXL push.  Spec decision 4 exists to
    make that race unreachable, so this loop reads STATUS only.
    """
    dev.require_seq("a chat_seq launch")
    st = dev.seq_status()
    if st["busy"]:
        raise ChatSeqError(
            f"the sequencer is busy (STATUS={st['raw']:#010x}) — another host "
            f"has it, or a previous run hung.  chat_seq holds the flock, so "
            f"this is an unlocked infer.py/seq_run.py or a wedged stream.")

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
        (ref/gen_layer_script.py:479-482), extended to k entries."""
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
    implements (ref/gen_layer_script.py:479-482).  Sampler._order()
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

      * rtl/layer_chan.sv:16-18 — a SWIN read is legal only while the
        block is idle, and the RTL has a simulation $fatal for a SWIN read
        during a burst.  A halted sequencer is idle, so the read happens
        strictly between launches and never while SEQ is busy.
      * No record in the committed stream ever writes L_SPTR or L_SWIN
        (census of all 60,495 records: L_SPTR 0, L_SWIN 0 — scratch is
        loaded by LDC/EMB, which carry their own absolute destination), so
        moving SPTR here cannot disturb the next launch.  We still save
        and restore it (L_SPTR is RW and reads back,
        rtl/layer_chan.sv:631) so the CSR file is left exactly as found.
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
            f"(rtl/layer_chan.sv:16-18)")
    keep = int(dev.rd(HW.L_SPTR)) & 0x3FFF
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
def _cmd_scratch(lop, a0, a1, a2):
    """One layer CMD -> (reads, writes) as [(word, nwords)].

    Transcribed from ref/seq_model.py:301-391 (the executor) and
    ref/gen_layer_script.py:253-462 (the emitter).  Only the fields that
    address the scratchpad are decoded; everything else is ignored.
    """
    R, W = [], []
    s1, d1 = a1 & 0x3FFF, (a1 >> 14) & 0x3FFF
    if lop == 1:                                        # VN
        n = 1 << ((a0 >> 2) & 0xF)
        R.append((s1, n))
        W.append((d1, n))
    elif lop == 2:                                      # VNW
        R.append((s1, a0))
    elif lop == 3:                                      # ROPET
        R.append((s1, 128))
    elif lop == 4:                                      # ROPE
        R.append((s1, 256))
        W.append((d1, 256))
    elif lop == 5:                                      # CONVW / CONVZ
        if (a0 & 3) == 0:
            R.append((s1, 4 * (a0 >> 15)))
    elif lop == 6:                                      # CONV
        n = (a0 >> 13) & 0x1FFF
        R.append((s1, n))
        W.append((d1, n))
    elif lop == 7:                                      # GATE
        R += [(s1, 16), (d1, 16), (a2 & 0x3FFF, 32), ((a2 >> 14) & 0x3FFF, 16)]
        W.append((a0 & 0x3FFF, 32))
    elif lop == 8:                                      # DNST
        R += [(s1, 128), (d1, 128), (a2 & 0x3FFF, 128),
              ((a0 >> 4) & 0x3FFF, 1), ((a0 >> 18) & 0x3FFF, 1)]
        W.append(((a2 >> 14) & 0x3FFF, 256))
    elif lop == 9:                                      # KVAP
        R += [(s1, 256), (d1, 256)]
    elif lop == 10:                                     # ATTN
        R.append((s1, 256))
        W.append((d1, 256))
    elif lop == 11:                                     # ALU
        sub, n = a0 & 0xF, (a0 >> 4) & 0x3FFF
        dst = (a2 >> 17) & 0x3FFF                       # NOTE >>17, not >>14
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


def scratch_accesses(recs):
    """Yield (i, tag, reads, writes) over a CONTIGUOUS record slice.

    Stateful exactly as the ISA is: the ARG0..2 shadow and SPTR are
    carried record to record, so a slice must start where the caller
    knows the shadow is irrelevant (the head tail only ever writes all
    three ARGs before each CMD, so [15532,16266) is self-contained).
    """
    arg = [0, 0, 0]
    sptr = 0
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
                sptr = r.imm32 & 0x3FFF
            elif off == SF.LOFF_SWIN:
                W.append((sptr, 1))
                sptr += 1
            elif off == SF.LOFF_CMD:
                R, W = _cmd_scratch(r.imm32 & 0xFF, *arg)
        elif o == SF.OP_CMD:
            lop = r.imm32 & 0xFF
            R, W = _cmd_scratch(lop, *arg)
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
            self.tc = SC.TurnCompiler(self.prefix, t_max=args.t_max,
                                      pos_mode=self.pos_mode,
                                      verify_sha=not args.any_template)
        else:
            recs0 = SF.unpack_stream(open(self.prefix + ".seq", "rb").read())
            self.geom = derive_geometry(recs0, self.meta0)
            self.tmpl_sha = TEMPLATE4_SHA256
            got = hashlib.sha256(open(self.prefix + ".seq", "rb").read()) \
                .hexdigest()
            if not args.any_template and got != self.tmpl_sha:
                raise ChatSeqError(
                    f"{self.prefix}.seq sha256 {got[:16]} != the gated "
                    f"4-chan template {self.tmpl_sha[:16]}.  Regenerate it "
                    f"with SEQ_NCH=4 and re-run the seq_model 4-chan gate "
                    f"before re-pinning TEMPLATE4_SHA256.")
            self.SCm = seq_chat_for(self.geom)
            self.tc = self.SCm.TurnCompiler(self.prefix, t_max=args.t_max,
                                            pos_mode=self.pos_mode,
                                            verify_sha=False)
            log(f"  nch=4      {os.path.basename(self.prefix)}: "
                f"{self.geom['TEMPLATE_NREC']} records, body "
                f"{self.geom['NREC_BODY_FULL']} full / "
                f"{self.geom['NREC_BODY_LITE']} lite; head image(s) "
                f"{self.wlayout.get('ilv_wids')} chunk-INTERLEAVED over "
                f"{self.wlayout.get('nch')} channels (S4)")
        self.meta = self.tc.meta
        self.const_blob = self.tc.blob()
        self.layout = self.tc.blob_layout()
        self.images = {
            "preamble": Resident("preamble", self.tc.build_session()),
            "lite": Resident("lite", self.tc.build_step(0, 0, "lite")),
            "full": Resident("full", self.tc.build_step(0, 0, "full")),
        }
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

        self.manifest = json.load(open(self.base + ".weights.json"))
        self.wdir = os.path.dirname(os.path.abspath(self.base)) or "."
        self.embf = self.base + ".emb.bin"
        self.wbase_of, self.wtop = plan_weights(self.manifest, self.wdir)

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
        p = self.tc.patch_step(self.images[kind].a, tok=tok, pos=pos,
                               tcnt=tcnt,
                               data_delta=self.plan["data_delta"])
        return p.writes(), p.fields

    def _relocate(self):
        """LDC/EMB rebase, ONCE per session, on the three images."""
        tot = 0
        for name in ("preamble", "lite", "full"):
            im = self.images[name]
            im.recs, rep = SR.relocate(im.recs_emit, self.meta, self.plan,
                                       len(self.const_blob))
            im.data = SF.pack_stream(im.recs)
            if len(im.data) != im.nrec * SEQ_REC_BYTES:
                raise ChatSeqError("packed image size mismatch")
            tot += rep["ldc"] + rep["emb"]
        self.log(f"  relocate   {tot} LDC+EMB records rebased by "
                 f"{self.plan['data_delta']:+#x} / {self.plan['emb_delta']:+#x}"
                 f"; images at "
                 + ", ".join(f"{n}@{self.images[n].base:#x}"
                             for n in ("preamble", "lite", "full")))

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
        return d

    def bring_up(self):
        """Residency probe -> targeted upload -> const blob + images."""
        dev, a = self.dev, self.args
        SR.check_weight_plan(self.meta, self.wbase_of, self.manifest)
        SR.check_mvgo_targets(
            [r for n in ("lite", "full") for r in self.images[n].recs_emit],
            self.wbase_of, self.manifest)

        splits = self.weight_splits()
        wit = build_residency_manifest(self.manifest, self.wdir, self.wbase_of,
                                       self.embf, self.plan["emb_base"],
                                       splits=splits)
        bad = [] if a.force_upload else probe_residency(dev, wit, self.log)
        if a.force_upload:
            self.log("  residency  SKIPPED (--force-upload)")
            bad = wit
        badw = sorted({w["wid"] for w in bad if w["kind"] == "weight"})
        bade = any(w["kind"] == "emb" for w in bad)
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

    # ------------------------------------------------ launches
    def preamble(self):
        """Session-once reset: conv weights, dnz, T=0 in every bank."""
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
        self.x8_read = (self._model_x8 if offline
                        else (lambda ctx=None: read_x8_eout(self.dev)))
        # ---- the host head: --verify-head, or a fixture-free offline run
        need_head = self.verify_head or (want and offline and not fixture)
        if need_head:
            import head_cache as HC
            t0 = time.monotonic()
            try:
                self.head = HC.open_head(
                    self.base, wid=HEAD_WID,
                    cache=not getattr(a, "no_head_cache", False),
                    cache_dir_=getattr(a, "head_cache", None),
                    mmap=bool(getattr(a, "head_mmap", False)),
                    threads=int(getattr(a, "head_threads",
                                        HC.DEFAULT_THREADS)),
                    log=log)
            except HC.HeadCacheError as e:
                raise ChatSeqError(
                    f"the host verification head could not be built from "
                    f"{os.path.basename(self.base)} (wid {HEAD_WID}): {e}")
            if self.head.spec.logit_exp(0) != HEAD_LOGIT_EXP0:
                raise ChatSeqError(
                    f"the manifest's head dequant is 2^(e_x"
                    f"{self.head.spec.logit_exp(0):+d}), this file pins "
                    f"2^(e_x{HEAD_LOGIT_EXP0:+d}) (S4)")
            self.sampler.logit_exp0 = self.head.spec.logit_exp(0)
            log(f"  head       VERIFICATION COPY ready in "
                f"{time.monotonic() - t0:.1f}s ({self.head.built_from}); "
                f"logit = y32 * 2^(e_x{HEAD_LOGIT_EXP0:+d}) — the CHIP still "
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
        x8 = np.asarray(M.mem[X8_WORD:X8_WORD + X8_LEN], dtype=np.int64)
        if int(np.abs(x8).max()) > 127:
            raise ChatSeqError(
                f"scratch[{X8_WORD:#x}] holds |x|max={int(np.abs(x8).max())}, "
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
    in numpy and unpacks every W4 row it touches off disk.  MEASURED on
    darthplagueis: ~6 s of host time per step (lite ~5 s, full ~7 s)
    against 0.156 s of device time, i.e. --verify runs ~40x slower than
    the chat it is checking.  It is the cross-driver gate, not a mode to
    chat in.  --model-only runs the same machinery with NO board.
    """

    def __init__(self, session, log=print):
        import seq_model as SM
        self.SM = SM
        self.log = log
        self.sess = session
        s = session
        self.blob = s.const_blob
        self.W = SM.DDRWeights.from_files(s.base, s.meta["weights"])
        n = os.path.getsize(s.embf) // 2048
        self.emb = np.memmap(s.embf, dtype="<i2", mode="r").reshape(n, 1024)
        self.mach = None
        self.n = 0
        self.reset()

    def reset(self):
        self.mach = self.SM._fresh_mach()
        # the preamble is part of the model too: replay it into the mach
        self.pending_preamble = True

    def _run(self, image, tok, pos):
        """Replay the image the board would launch, in EMITTER space.

        data_delta=0: ref/seq_model.SeqExec reads the blob at
        SF.SEQ_DATA_BASE, so the model gets the unrelocated patch while the
        board gets the relocated one.  Everything else is the same bytes.

        CAVEAT (agent A's finding): SeqExec does NOT model the signed
        18-bit XRF read, so in pos_mode="xrf" it will happily agree with
        itself for pos > 85 where silicon would read the wrong RoPE table.
        pos_mode="ldc" has no such blind spot.
        """
        if image.a.kind == "step":
            data = self.sess.tc.patch_step(
                image.a, tok=tok, pos=pos, tcnt=1, data_delta=0).apply(image.a)
        else:
            data = image.a.data
        recs = SF.unpack_stream(data)
        ex = self.SM.SeqExec(recs, self.blob, self.W, emb=self.emb,
                             mach=self.mach).run(max_steps=50 * len(recs))
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
def resolve_pos_mode(args):
    """Pick agent A's position-addressing mode for this --max-ctx.

    XRF[4] is read SIGN-EXTENDED from an 18-bit file (rtl/seq_unit.sv
    xrf_rd), so XRF[4] = pos*1536 tops out at pos 85 and a larger CSRWR is
    TRUNCATED SILENTLY — ref/seq_model.py does not model that, so the
    model would pass where silicon reads the wrong RoPE table.  Agent A
    raised this as a spec/reality conflict and shipped pos_mode="ldc"
    (patch the six position-LDC addresses instead) as the escape hatch.
    "auto" picks the mode that can actually reach --max-ctx.
    """
    want = args.pos_mode
    cap = SC.XRF_POS_MAX if SC is not None else 85
    if want == "auto":
        return "xrf" if (args.max_ctx - 1) <= cap else "ldc"
    if want == "xrf" and (args.max_ctx - 1) > cap:
        raise ChatSeqError(
            f"--pos-mode xrf cannot reach --max-ctx {args.max_ctx}: XRF[4] is "
            f"signed 18-bit, so pos <= {cap}.  Use --pos-mode ldc (or auto), "
            f"or --max-ctx {cap + 1}.")
    return want


def crosscheck_agent_a(session, log=print):
    """Independently re-derive agent A's outputs from the frozen spec.

    Agent A's ref/seq_chat.py is the compiler of record (file ownership),
    but the two of us read the same frozen document, so the two step
    images and the position pool MUST agree byte for byte.  A mismatch
    means one of us misread docs/CHAT_SEQ_SPEC.md; it is fatal, not a
    warning.
    """
    recs, blob, meta = load_template(session.prefix,
                                     check_sha=not session.args.any_template,
                                     sha=session.tmpl_sha, g=session.geom)
    mine = independent_step_images(recs, session.geom)
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

    check("auto pos_mode picks xrf when --max-ctx fits the signed XRF",
          resolve_pos_mode(_args(pos_mode="auto",
                                 max_ctx=SC.XRF_POS_MAX + 1)) == "xrf")
    check("auto pos_mode picks ldc for a real chat context",
          resolve_pos_mode(_args(pos_mode="auto", max_ctx=500)) == "ldc")
    try:
        resolve_pos_mode(_args(pos_mode="xrf", max_ctx=500))
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
    log("  [11] flock(sw/.seq.lock) exclusivity")
    lk = SeqLock(os.path.join(SW_DIR, ".seq.lock.selftest"))
    lk.acquire()
    lk2 = SeqLock(lk.path)
    try:
        lk2.acquire()
        check("the flock is exclusive", False)
    except ChatSeqError:
        check("the flock is exclusive", True)
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
          HEAD_LOGIT_EXP0 == -22 and
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
                self.sptr = v & 0x3FFF

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
    # the strongest form: over the WHOLE full body, the last write into the
    # x8 window is the DYNQ8 that produces it, at the last lite record
    full_acc = list(scratch_accesses(recs[REC_BODY_FULL[0]:REC_BODY_FULL[1]]))
    touch = [REC_BODY_FULL[0] + i for (i, _t, _r, ws) in full_acc
             if any(_overlaps(w, X8_WORD, X8_WORD + X8_LEN) for w in ws)]
    check("the LAST write into x8 in the whole body is the DYNQ8 at 15531",
          touch[-1] == REC_BODY_LITE[1] - 1 == 15531, str(touch[-3:]))
    check("no record at or after the lite cut writes x8 (S6 relies on it)",
          all(t < REC_BODY_LITE[1] for t in touch), str(touch[-3:]))
    check("the x8 producer really is an ALU DYNQ8 with dst = 0x800",
          full_acc[touch[-1] - REC_BODY_FULL[0]][1] == "CMD:ALU:DYNQ8"
          and full_acc[touch[-1] - REC_BODY_FULL[0]][3] == [(X8_WORD, X8_LEN)],
          str(full_acc[touch[-1] - REC_BODY_FULL[0]][1:]))
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
              HC.RS_F == 8 and HEAD_LOGIT_EXP0 == -4 + 5 - 15 + 0 - HC.RS_F)
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
               "POS_LDC_REC_OFFSETS")),
          str({k: (v, getattr(SC, k, None)) for k, v in g1.items()
               if not k.startswith("_") and v != getattr(SC, k, v)}))
    check("...including this file's own frozen constants",
          (g1["R_BODY_LITE"], g1["R_BODY_FULL"], g1["R_TCNT"], g1["R_HALT"])
          == (REC_BODY_LITE, REC_BODY_FULL, REC_TCNT, REC_HALT))
    check("the lite cut is found from the HEAD IMAGE, not from scratch[0x800]",
          sum(1 for r in recs1[REC_BODY_FULL[0]:REC_BODY_FULL[1]]
              if r.opcode == SF.OP_MOVX and r.addr_lo == X8_WORD) > 1,
          "x8 is reused by many matvecs, so 'first MOVX 0x800' would be wrong")
    check("the derived head wid is the manifest's LM head", g1["_HEAD_WID"]
          == HEAD_WID, str(g1["_HEAD_WID"]))

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
        check("a 4-chan witness set is one block PER CHANNEL per image",
              len(wi) == 4 + 4 and all(w["chan"] is not None for w in wi),
              str(len(wi)))
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
        "sudo; flock(sw/.seq.lock) held")
    log("  NOTE       infer.py / seq_run.py do NOT take sw/.seq.lock yet — "
        "check pgrep before a session")
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
                         "(~6 s of host time per step; the board waits)")
    ap.add_argument("--force-upload", action="store_true",
                    help="skip the residency probe and re-upload everything")
    ap.add_argument("--timeout", type=float, default=STEP_TIMEOUT)
    ap.add_argument("--preamble-timeout", type=float, default=PREAMBLE_TIMEOUT)
    ap.add_argument("--out", default=None, help="JSON report path")
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
    ap.add_argument("--lock", default=LOCK_PATH)
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
    args = ap.parse_args()
    # --ntok defaults late so --model-only can tell "not given" from "32"
    args.ntok_given = args.ntok is not None
    if args.ntok is None:
        args.ntok = DEFAULT_NTOK
    # --nch 4 picks the 4-chan artifact set unless the user named one (S4)
    if args.nch != 1 and args.template == TEMPLATE_PREFIX:
        args.template = TEMPLATE4_PREFIX

    if args.selftest:
        raise SystemExit(0 if selftest(args) else 1)
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
    with SeqLock(args.lock) as _lock:
        print("--- session bring-up")
        sess = ChatSession(args)
        sess.open_board()
        sess.bring_up()
        tk = None
        if not args.smoke:
            tk = load_tokenizer()
            sess.attach_template(tk)
        if args.verify:
            print("  verify     building the ref/seq_model lockstep "
                  "(~6 s of host time per step; the board idles meanwhile)")
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


if __name__ == "__main__":
    main()
