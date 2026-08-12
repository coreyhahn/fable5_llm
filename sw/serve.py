#!/usr/bin/env python3
"""serve.py — localhost HTTP/SSE front end for sw/chat_seq.py (chat-seq
phase 3, agent C).

docs/CHAT_SEQ_SPEC.md is the frozen contract; docs/CHAT_SEQ_PLAN.md phase 3
is the assignment.  This file OWNS NO INFERENCE LOGIC: sw/chat_seq.py (agent
B) is the backend and is imported as a library, never edited, never shelled
out to.

------------------------------------------------------------------
Dependencies: NONE (python stdlib only)
------------------------------------------------------------------
http.server.ThreadingHTTPServer + a hand-written Server-Sent-Events writer.
No fastapi/uvicorn/sse-starlette, so serve.py runs in the SAME sw/.venv that
already runs chat_seq.py (python 3.12 + numpy) with zero new packages and no
second venv to keep in sync with the board tooling.  SSE is four lines of
framing; a web framework would have been more venv than server.

------------------------------------------------------------------
Endpoints (all JSON in / JSON out; SSE where noted)
------------------------------------------------------------------
POST /v1/generate  {"prompt": str, "max_tokens"?: int, "session_id"?: str,
                    "raw"?: bool (default false — the chat template is
                    applied; docs/INSTRUCT_SPEC.md T4/T8),
                    "system"?: str (T5: used on the session's first
                    templated turn only)}
    -> 200 text/event-stream:
         event: queue    {position, queued, running_session, eta_s}   (0+)
         event: start    {job_id, session_id, prompt_tokens, replayed,
                          reset, steps, context_before, max_tokens}
         event: prefill  {index, total, device_ms, lite}              (0+)
         event: token    {index, id, text, device_ms}                 (0+)
         event: stats    {...}                    (exactly one, LAST)
         event: error    {error, type}            (instead of stats)
       429 if the queue is full, 400 on a malformed request, 503 if the
       backend failed to come up.
GET  /v1/health   -> CSR sanity (cached ident + idle heartbeat), VERSION,
                     board free/busy, queue depth.  NEVER takes a turn and
                     NEVER touches the device from the HTTP thread.
GET  /v1/metrics  -> cumulative turns/tokens/mean tok/s/uptime/device ms.
GET  /v1/sessions -> the named histories the server is holding.
POST /v1/reset    {"session_id"?: str} -> drop that history (lazy: the KV
                     banks are cleared by the preamble the next turn runs).

------------------------------------------------------------------
The board is ONE context
------------------------------------------------------------------
* ONE worker thread owns the device; HTTP threads never call the backend.
* Requests are served strictly FIFO from a bounded queue; waiting clients
  get honest `queue` events every time their position changes.
* Sessions are named histories.  The board holds exactly one of them at a
  time; serving a different session = preamble (context reset) + replay of
  that session's truncated history as prefill steps.  THAT COSTS ONE
  PREFILL STEP PER REPLAYED TOKEN (~139 ms measured-lite / 156 ms full) —
  a 200-token history costs ~28 s before the first new token.  Chat from
  one session_id and this never happens; ping-pong between two long
  sessions and it happens on every turn.  The `start` event reports
  `replayed` so the client can see exactly what it paid for.
* A crashed/timed-out/disconnected request never wedges the queue: the
  worker catches everything, drops the board's session ownership (so the
  next turn re-preambles into a known state) and moves on.

------------------------------------------------------------------
Safety
------------------------------------------------------------------
* Binds 127.0.0.1 by default and REFUSES a non-loopback bind without
  --i-know-what-im-doing.  There is no auth: this is a lab tool, reach it
  over an ssh tunnel.
* Real mode takes the chat_seq flock (sw/.seq.lock, spec decision 10)
  before any device fd is opened and holds it for the process lifetime;
  SIGTERM/SIGINT release it cleanly.
* --mock runs the whole server (queue, sessions, SSE, metrics) against a
  deterministic fake backend: no board, no flock, no chat_seq import.
* Never programs the FPGA, never touches flash, never runs sudo.

------------------------------------------------------------------
Suggested sw/Makefile targets (INTEGRATOR — this file edits no Makefile):

    serve_mock:  ; $(PY) -u serve.py --mock --port 8137
    serve:       ; $(PY) -u serve.py --port 8137 $(SERVE_FLAGS)
    serve_test:  ; $(PY) -u serve.py --selftest
    chat_client: ; $(PY) -u chat_client.py --port 8137
------------------------------------------------------------------
"""
import argparse
import collections
import errno
import json
import os
import queue
import signal
import socket
import sys
import threading
import time
import types
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SW_DIR = os.path.dirname(os.path.abspath(__file__))
if SW_DIR not in sys.path:
    sys.path.insert(0, SW_DIR)

VERSION = "serve.py/1 (chat-seq phase 3)"

DEFAULT_PORT = 8137
DEFAULT_QUEUE_CAP = 8
DEFAULT_MAX_TOKENS = 32
DEFAULT_MAX_TOKENS_CAP = 256
DEFAULT_REQUEST_TIMEOUT = 300.0      # s, INCLUDING the wait in the queue
DEFAULT_MAX_CTX = 500                # chat_seq.DEFAULT_MAX_CTX (KV depth 512)
MAX_BODY = 1 << 20
# ---- sampling (docs/SAMPLING_SPEC.md S5, as amended 2026-08-11) -------
# The DEFAULT IS GREEDY and greedy is 100% on-chip.  A sampled step is the
# same full launch plus the on-chip top-k capture unit, which arrives with
# the next RTL rung; until then every sampled request is REFUSED with the
# reason, never quietly served greedy.  See sw/chat_seq.py's SAMPLING
# section for the whole contract.
DEFAULT_TEMP = 0.0
DEFAULT_TOP_K = 50
DEFAULT_TOP_P = 1.0
MAX_TEMP = 5.0
SAMPLE_FIELDS = ("temperature", "top_k", "top_p", "seed")
PREFILL_MS_NOMINAL = 138.8           # spec decision 12 (derived, phase-2 measured)
KEEPALIVE_S = 10.0
HEARTBEAT_S = 5.0
EVENT_CAP = 4096
LOOPBACK = ("127.0.0.1", "::1", "localhost")
SESSION_CHARS = set("abcdefghijklmnopqrstuvwxyz"
                    "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-")


class ServeError(RuntimeError):
    """A request-level failure (reported to the client, never fatal)."""


class QueueFull(ServeError):
    pass


class NotReady(ServeError):
    pass


# ======================================================================
# SSE framing
# ======================================================================
def sse(name, obj):
    """One Server-Sent Event.  data: is a single line of compact JSON."""
    return ("event: %s\ndata: %s\n\n"
            % (name, json.dumps(obj, separators=(",", ":"), default=str))
            ).encode("utf-8")


# ======================================================================
# backends
# ======================================================================
class BackendBase(object):
    """The primitives Engine needs from a chat backend.

    Deliberately narrow so the mock is a real test double for the whole
    server, not a stub around one method.  Every one of these maps onto
    something sw/chat_seq.py already exposes (see BoardBackend).
    """

    name = "base"
    mock = True

    def start(self):
        raise NotImplementedError

    def stop(self):
        pass

    # --- tokenizer + chat template (docs/INSTRUCT_SPEC.md T8) ---
    def encode(self, text, raw=False, first=True, carry=None, system=None):
        """Prompt -> the ids to FEED, chat wrapper included.

        THE TEMPLATE LIVES HERE, not in the worker loop: serve.py
        reimplements chat_seq's turn schedule (it cannot call run_turn,
        which owns stdout and SIGINT), so `encode` is the single place a
        served prompt becomes tokens.  `first`/`carry` are the T3
        incremental-with-carry state the Engine tracks per session;
        `raw=True` is the /v1/generate opt-out.
        """
        raise NotImplementedError

    def decode(self, ids):
        raise NotImplementedError

    def visible(self, ids):
        """Generated ids minus the chat control tokens, for shown text."""
        return [int(i) for i in ids]

    @property
    def template_on(self):
        return False

    @property
    def stop_ids(self):
        return ()

    # --- context bookkeeping (mirrors chat_seq.ChatSession) ---
    @property
    def T(self):
        raise NotImplementedError

    @property
    def fed(self):
        raise NotImplementedError

    @property
    def next_in(self):
        raise NotImplementedError

    @property
    def max_ctx(self):
        raise NotImplementedError

    def plan_turn(self, ids, ntok):
        raise NotImplementedError

    def truncate_for(self, fed, next_in, ids, ntok):
        raise NotImplementedError

    # --- sampling (S5) ---
    @property
    def sampling(self):
        """What this backend can offer: {available, why, k, source}.

        `available` False is the normal state today: the on-chip top-k
        capture unit is a next-rung RTL feature, so a request that asks
        for temperature must be told no.
        """
        return {"available": False, "why": "this backend cannot sample",
                "k": 0, "source": None}

    def set_sampling(self, temp, top_k, top_p, seed):
        """Arm (or disarm) sampling for the NEXT turn.

        Returns the mode dict that goes into the `start`/`stats` events.
        Raises ServeError when sampling was asked for and cannot be
        delivered — the request fails loudly instead of being served
        greedy behind the caller's back.
        """
        if float(temp) > 0:
            raise ServeError(self.sampling["why"])
        return {"mode": "greedy", "temp": 0.0, "top_k": None, "top_p": None,
                "seed": None}

    def sample_telemetry(self):
        """Per-turn sampling counters for the stats event (or None)."""
        return None

    # --- device ---
    def preamble(self):
        raise NotImplementedError

    def step(self, tok, lite):
        raise NotImplementedError

    def heartbeat(self):
        return {}

    def health(self):
        return {}


class MockBackend(BackendBase):
    """Deterministic fake board: no device, no flock, no chat_seq import.

    Same arithmetic as chat_seq.ChatSession for plan_turn/truncate_history
    (the two are asserted equal by hand in the docstrings of those methods
    — the mock exists to exercise serve.py's queue/session/SSE machinery,
    not to re-validate agent B).

    Token ids: 1000+byte for prompt text, 2000+k for generated words,
    2999 = EOS.  The reply is a pure function of (previous token, step), so
    the same prompt in the same context always streams the same text.
    """

    name = "mock"
    mock = True
    WORDS = ("the", "sequencer", "streams", "one", "launch", "per", "step",
             "and", "the", "host", "patches", "seventy", "two", "bytes",
             "before", "every", "start", "which", "is", "free", "next",
             "to", "a", "hundred", "fifty", "six", "millisecond", "pass")
    WORD_BASE = 2000
    CHAR_BASE = 1000
    EOS = 2999
    LITE_MS = 138.8          # SIMULATED (spec decision 12 derived value)
    FULL_MS = 156.2          # SIMULATED (spec decision 12 measured value)

    def __init__(self, max_ctx=DEFAULT_MAX_CTX, step_ms=3.0, eos_after=0,
                 realtime=False, fail_on=None, log=print, raw=False,
                 system=None):
        self._max_ctx = int(max_ctx)
        self.raw = bool(raw)
        self.system = system
        self.template = None                  # built in start()
        self.realtime = bool(realtime)        # sleep the real 139/156 ms
        self.step_ms = float(step_ms)
        self.eos_after = int(eos_after)       # 0 = never emit EOS
        self.fail_on = fail_on                # token id that raises (tests)
        self.log = log
        self._T = 0
        self._fed = []
        self._next_in = None
        self.launches = {"preamble": 0, "lite": 0, "full": 0}
        self._reply_n = 0
        # sampling: the mock SIMULATES the on-chip top-k capture unit so the
        # server's request fields, refusal path and telemetry can be tested
        # without a board.  The numbers are fake; the code path is the real
        # chat_seq.Sampler.
        self.sampler = None
        self.CS = None
        self._sample_ms = []
        self._sample_info = None

    def start(self):
        self.log("  mock       deterministic fake backend: no board, no "
                 "flock (%s)"
                 % ("realtime: steps sleep the real %.1f/%.1f ms"
                    % (self.LITE_MS, self.FULL_MS) if self.realtime
                    else "fast: %.1f ms/step, and the device ms it reports "
                         "ARE that sleep" % self.step_ms))
        self._build_template()
        self.preamble()

    def _build_template(self):
        """The REAL chat_seq wrapper builder over this fake tokenizer.

        The template is one implementation (docs/INSTRUCT_SPEC.md file
        ownership: serve.py imports it, never restates it), so mock mode
        exercises the shipped splice.  strict=False because the mock's
        byte-per-id tokenizer cannot have the 2-id role headers the
        5*messages+7 formula assumes — the SHAPE is what mock mode tests;
        the exact ids are gated in chat_seq --selftest against HF.
        If chat_seq will not import (no numpy / no artifacts) the mock
        degrades to raw and says so, because --mock must never need a
        board machine.
        """
        if self.raw:
            self.log("  mock       template OFF (--raw)")
            return
        try:
            import chat_seq as CS                              # noqa: N806
            # the shim is the RAW encoder: ChatTemplate.body() must not
            # recurse back into the templating encode() below
            self.template = CS.ChatTemplate(
                types.SimpleNamespace(encode=self._enc), strict=False)
            self.log("  mock       template ON via chat_seq.ChatTemplate "
                     "(strict=False: the mock tokenizer is 1 id per byte, so "
                     "the wrapper is %d*messages+%d here, not 5*M+7)"
                     % (self.template.per_message,
                        self.template.gen_overhead))
        except Exception as e:                                 # noqa: BLE001
            self.log("  mock       template OFF: chat_seq will not import "
                     "here (%s: %s)" % (type(e).__name__, e))

    def _ms(self, lite):
        """What the mock is allowed to CALL device time: exactly what it
        slept.  A fake backend that reported 156 ms while sleeping 4 ms
        would put a number in the stats event that nothing measured."""
        if self.realtime:
            return self.LITE_MS if lite else self.FULL_MS
        return self.step_ms

    # --- tokenizer ---
    def encode(self, text, raw=False, first=True, carry=None, system=None):
        if raw or self.template is None:
            return self._enc(text)
        return self.template.turn_ids(
            text, system=(system if system is not None else self.system),
            first=first, carry=carry)

    def _enc(self, text):
        return [self.CHAR_BASE + b for b in text.encode("utf-8")]

    def visible(self, ids):
        if self.template is None:
            return [int(i) for i in ids]
        return self.template.visible(ids)

    @property
    def template_on(self):
        return self.template is not None

    def decode(self, ids):
        out = []
        for i in ids:
            i = int(i)
            if i == self.EOS:
                continue
            if i >= self.WORD_BASE:
                out.append(" " + self.WORDS[(i - self.WORD_BASE)
                                            % len(self.WORDS)])
            elif self.CHAR_BASE <= i < self.CHAR_BASE + 256:
                out.append(chr(i - self.CHAR_BASE))
        return "".join(out)

    @property
    def stop_ids(self):
        return (self.EOS,)

    # --- context ---
    @property
    def T(self):
        return self._T

    @property
    def fed(self):
        return list(self._fed)

    @property
    def next_in(self):
        return self._next_in

    @property
    def max_ctx(self):
        return self._max_ctx

    def plan_turn(self, ids, ntok):
        """chat_seq.ChatSession.plan_turn, verbatim semantics."""
        carry = [] if self._next_in is None else [int(self._next_in)]
        feed = carry + [int(i) for i in ids]
        nsteps = len(feed) + int(ntok) - 1
        return feed, nsteps, (self._T + nsteps) > self._max_ctx

    def truncate_for(self, fed, next_in, ids, ntok):
        """chat_seq.ChatSession.truncate_history, verbatim semantics."""
        room = self._max_ctx - (len(ids) + int(ntok) - 1)
        if room < 0:
            raise ServeError(
                "prompt (%d ids) + max_tokens %d needs %d steps, more than "
                "the %d-step context" % (len(ids), ntok,
                                         len(ids) + ntok - 1, self._max_ctx))
        hist = list(fed[1:]) + ([] if next_in is None else [int(next_in)])
        return hist[len(hist) - room:] if room < len(hist) else hist

    # --- sampling (simulated capture unit) ---
    @property
    def sampling(self):
        if self.CS is None:
            try:
                import chat_seq as CS                          # noqa: N806
                self.CS = CS
            except Exception as e:                             # noqa: BLE001
                return {"available": False, "k": 0, "source": None,
                        "why": "mock sampling needs chat_seq to import "
                               "here (%s: %s)" % (type(e).__name__, e)}
        return {"available": True, "k": self.CS.TOPK_CAPTURE_K,
                "source": "mock-topk",
                "why": "SIMULATED candidate sets — no board, no model"}

    def set_sampling(self, temp, top_k, top_p, seed):
        self._sample_ms = []
        self._sample_info = None
        if float(temp) <= 0:
            self.sampler = None
            return {"mode": "greedy", "temp": 0.0, "top_k": None,
                    "top_p": None, "seed": None, "source": None}
        s = self.sampling
        if not s["available"]:
            raise ServeError(s["why"])
        try:
            self.sampler = self.CS.Sampler(temp=temp, top_k=top_k,
                                           top_p=top_p, seed=seed)
        except self.CS.ChatSeqError as e:
            raise ServeError(str(e))
        return {"mode": "sampled", "temp": self.sampler.temp,
                "top_k": self.sampler.top_k, "top_p": self.sampler.top_p,
                "seed": self.sampler.seed, "source": s["source"],
                "simulated": True}

    def sample_telemetry(self):
        if self.sampler is None:
            return None
        d = self.sampler.as_dict()
        d["source"] = "mock-topk"
        d["simulated"] = True
        return d

    def _candidates(self, h):
        """A fake capture-unit read: k distinct ids with descending y32."""
        k = self.CS.TOPK_CAPTURE_K
        ids, vals, x = [], [], h
        for i in range(k):
            x = (x * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
            ids.append(self.WORD_BASE + ((x >> 29) % len(self.WORDS)) + i * 31)
            vals.append(1_300_000 - i * 9000 - ((x >> 17) % 4000))
        return (self.CS.np.array(vals, dtype=self.CS.np.int32),
                self.CS.np.array(ids, dtype=self.CS.np.int64), 5)

    # --- device ---
    def preamble(self):
        ms = self._ms(False)
        time.sleep(ms / 1e3)
        self._T, self._fed, self._next_in = 0, [], None
        self.launches["preamble"] += 1
        return ms

    def step(self, tok, lite):
        if self._T >= self._max_ctx:
            raise ServeError("position %d would wrap the KV banks" % self._T)
        if self.fail_on is not None and int(tok) == int(self.fail_on):
            raise ServeError("mock backend: injected failure on token %s"
                             % tok)
        ms = self._ms(lite)
        time.sleep(ms / 1e3)
        self.launches["lite" if lite else "full"] += 1
        self._fed.append(int(tok))
        self._T += 1
        if lite:
            return None, ms
        h = (int(tok) * 6364136223846793005 + self._T * 1442695040888963407
             + 1) & ((1 << 64) - 1)
        self._reply_n += 1
        if self.eos_after and (self._reply_n % self.eos_after == 0):
            out = self.EOS
        else:
            out = self.WORD_BASE + ((h >> 33) % len(self.WORDS))
        if self.sampler is not None and out != self.EOS:
            # the "chip" produced `out`; the simulated capture unit offers a
            # candidate set and the REAL sampler picks from it
            v, i, e_x = self._candidates(h)
            out, info = self.sampler.pick(v, i, e_x)
            self._sample_info = info
            self._sample_ms.append(info["sample_ms"])
        self._next_in = out
        return out, ms

    def health(self):
        return {"backend": "mock", "board": None, "version": None,
                "sampling": self.sampling,
                "note": "MOCK BACKEND — no board was touched; 'device ms' is "
                        "this process sleeping (%s)"
                        % ("realtime: %.1f lite / %.1f full"
                           % (self.LITE_MS, self.FULL_MS) if self.realtime
                           else "%.1f ms/step" % self.step_ms),
                "launches": dict(self.launches)}


class BoardBackend(BackendBase):
    """Thin adapter over sw/chat_seq.py — the ONLY place serve.py knows the
    board exists.

    Everything here is a call into agent B's committed module; serve.py adds
    no inference logic of its own:

        chat_seq.ChatSession(args, log=)      session + resident images
        ChatSession.open_board()              identity gate (seq_run.Dev)
        ChatSession.bring_up()                residency probe + upload
        ChatSession.preamble()                context reset launch
        ChatSession.step(tok, lite=)          ONE forward step -> (tok, rep)
        ChatSession.plan_turn(ids, ntok)      feed/steps/need_reset
        ChatSession.truncate_history(...)     history that still fits
        chat_seq.load_tokenizer()             infer.py BpeTok + stop ids
        chat_seq.SeqLock                      flock (taken in main(), not here)

    NOT used: chat_seq.run_turn().  It is the right loop but it writes the
    stream to stdout and installs a SIGINT handler (illegal off the main
    thread), so serve.py runs the same schedule with a per-token callback.
    See the WISHLIST note at the bottom of this file.
    """

    name = "board"
    mock = False

    def __init__(self, opts, log=print):
        self.log = log
        self.opts = opts
        self.CS = None
        self.sess = None
        self.tk = None
        self.template = None
        self._ident = {}
        self._hb = {"at": 0.0, "busy": None, "err_code": None, "raw": None}

    # ---- args namespace chat_seq.ChatSession reads (argparse-compatible)
    def _args(self):
        o = self.opts
        import chat_seq as CS
        nch = int(getattr(o, "nch", 1) or 1)
        return types.SimpleNamespace(
            dev=o.dev, chan=o.chan, nch=nch,
            template=(o.template
                      or (CS.TEMPLATE4_PREFIX if nch != 1
                          else CS.TEMPLATE_PREFIX)),
            any_template=o.any_template,
            t_max=CS.T_MAX, max_ctx=o.max_ctx, pos_mode=o.pos_mode,
            prefill=o.prefill, ntok=o.max_tokens_default,
            force_upload=o.force_upload,
            timeout=o.step_timeout, preamble_timeout=o.preamble_timeout,
            lock=o.lock, verify=False, out=None,
            raw=o.raw, system=o.system,
            # chat_seq's CLI-only knobs, defaulted so no code path in
            # ChatSession/run_turn can AttributeError on a served request
            prompt=[], canned=False, smoke=False, selftest=False,
            model_only=False, continue_context=False, steps=0,
            ntok_given=True,
            # sampling (S5): per-request fields override these per turn
            temp=o.temp, top_k=o.top_k, top_p=o.top_p, seed=o.seed,
            verify_head=o.verify_head, topk_base=o.topk_base,
            head_cache=o.head_cache, no_head_cache=o.no_head_cache,
            head_mmap=o.head_mmap, head_threads=o.head_threads,
            sample_fixture=None, make_fixture=None, passes=4)

    def start(self):
        import chat_seq as CS                                    # noqa: N806
        self.CS = CS
        if self.opts.max_ctx >= CS.T_MAX:
            raise ServeError("--max-ctx must be < the KV bank depth %d (the "
                             "RTL wraps SILENTLY past it)" % CS.T_MAX)
        self.sess = CS.ChatSession(self._args(), log=self.log)
        self.sess.open_board()
        self.sess.bring_up()
        self.tk = CS.load_tokenizer(log=self.log)
        # T8: the chat template is applied in THIS encode path.  serve.py
        # does not call chat_seq.run_turn (that owns stdout and SIGINT),
        # so it attaches the same builder to its own loop.
        self.template = self.sess.attach_template(self.tk, log=self.log)
        # S5: resolve the candidate source ONCE, with the board open.  A
        # server started with --temp > 0 and no capture unit dies here, at
        # start-up, instead of failing every request later.
        self.sess.attach_sampling(log=self.log, offline=False)
        d = self.sess.dev
        self._ident = {"magic": "%#010x" % d.ident["magic"],
                       "version": "%#010x" % d.ident["version"],
                       "calib": "%#x" % d.ident["calib"],
                       "layer_ident": "%#010x" % d.ident["layer_ident"],
                       "seq_ok": bool(d.seq_ok),
                       "seq_why": None if d.seq_ok else d.seq_why,
                       "pos_mode": self.sess.pos_mode,
                       "prefill": self.opts.prefill,
                       # S4: what placement the board is holding right now.
                       # A client can read this before deciding whether its
                       # nch assertion will be accepted.
                       "nch": self.sess.nch,
                       "weight_layout": self.sess.layout_tag(),
                       "template": (None if self.template is None else {
                           "spec": "docs/INSTRUCT_SPEC.md",
                           "overhead": "%d*messages+%d"
                                       % (self.template.per_message,
                                          self.template.gen_overhead),
                           "system": self.opts.system,
                           "stop_ids": sorted(self.stop_ids)}),
                       "images": {k: v.nrec
                                  for k, v in self.sess.images.items()}}
        self.sess.preamble()
        self.heartbeat()

    def stop(self):
        # seq_run.Dev has no close(); process exit closes the fds.  Nothing
        # here may abort a running launch — that is the worker's job.
        pass

    # --- tokenizer + chat template ---
    def encode(self, text, raw=False, first=True, carry=None, system=None):
        if raw or self.template is None:
            return list(self.tk.encode(text))
        return self.template.turn_ids(
            text, system=(system if system is not None else self.opts.system),
            first=first, carry=carry)

    def decode(self, ids):
        return self.tk.decode([int(i) for i in ids])

    def visible(self, ids):
        if self.template is None:
            return [int(i) for i in ids]
        return self.template.visible(ids)

    @property
    def template_on(self):
        return self.template is not None

    @property
    def stop_ids(self):
        return tuple(getattr(self.tk, "stop_ids", ()) or ())

    # --- context ---
    @property
    def T(self):
        return self.sess.T

    @property
    def fed(self):
        return list(self.sess.fed)

    @property
    def next_in(self):
        return self.sess.next_in

    @property
    def max_ctx(self):
        return self.sess.args.max_ctx

    def plan_turn(self, ids, ntok):
        return self.sess.plan_turn(ids, ntok)

    def truncate_for(self, fed, next_in, ids, ntok):
        """chat_seq.ChatSession.truncate_history against a SAVED history.

        The board holds one context; a session that is not resident still
        has a history that has to be truncated by exactly the same rule.
        Rather than restate the rule, call agent B's method unbound over a
        shim carrying that session's (fed, next_in) — same code, other data.
        """
        shim = types.SimpleNamespace(args=self.sess.args, fed=list(fed),
                                     next_in=next_in)
        try:
            return self.CS.ChatSession.truncate_history(shim, ids, ntok)
        except self.CS.ChatSeqError as e:
            raise ServeError(str(e))

    # --- sampling (S5) ---
    @property
    def sampling(self):
        c = getattr(self.sess, "cand", None) if self.sess else None
        if c is None:
            return {"available": False, "k": 0, "source": None,
                    "why": "the session has not resolved a candidate source "
                           "yet"}
        return {"available": bool(c.available), "k": int(c.k),
                "source": c.name,
                "why": "" if c.available else c.why}

    def set_sampling(self, temp, top_k, top_p, seed):
        """Re-arm chat_seq's Sampler for the next turn.

        The candidate SOURCE is fixed for the session (it is a property of
        the bitstream); only the knobs are per request.
        """
        s = self.sampling
        if float(temp) > 0 and not s["available"]:
            raise ServeError(s["why"])
        try:
            self.sess.sampler = self.CS.Sampler(temp=temp, top_k=top_k,
                                                top_p=top_p, seed=seed)
        except self.CS.ChatSeqError as e:
            raise ServeError(str(e))
        self.sess.sample_log = []
        sm = self.sess.sampler
        if not sm.enabled:
            return {"mode": "greedy", "temp": 0.0, "top_k": None,
                    "top_p": None, "seed": None, "source": None}
        return {"mode": "sampled", "temp": sm.temp, "top_k": sm.top_k,
                "top_p": sm.top_p, "seed": sm.seed, "source": s["source"],
                "capture_k": s["k"]}

    def sample_telemetry(self):
        sm = getattr(self.sess, "sampler", None)
        if sm is None or not (sm.enabled or self.sess.verify_head):
            return None
        d = sm.as_dict()
        d["source"] = self.sess.cand.name if self.sess.cand else None
        if self.sess.verify_head:
            d["verify_head"] = {"steps": self.sess.head_checks,
                                "mismatches": 0}
        return d

    # --- device ---
    def preamble(self):
        rep = self.sess.preamble()
        return float(rep["device_ms"])

    def step(self, tok, lite):
        out, rep = self.sess.step(int(tok), lite=bool(lite))
        return (None if out is None else int(out)), float(rep["device_ms"])

    def heartbeat(self):
        """Cheap CSR read for /v1/health.  WORKER THREAD ONLY, and only
        while no launch is in flight (STATUS is safe to read any time, but
        this keeps every device access on one thread)."""
        st = self.sess.dev.seq_status()
        self._hb = {"at": time.time(), "busy": bool(st["busy"]),
                    "err_code": int(st["err_code"]), "raw": "%#010x" % st["raw"],
                    "out_cnt": int(st["out_cnt"]),
                    "of_ovf": bool(st.get("of_ovf", False))}
        if self._hb["of_ovf"]:
            self.sess.out_fifo_ovf = True       # S6: sticky, one-way
        return self._hb

    def health(self):
        d = dict(self._ident)
        d["backend"] = "board"
        d["sampling"] = self.sampling
        d["heartbeat"] = dict(self._hb)
        if self._hb.get("at"):
            d["heartbeat"]["age_s"] = round(time.time() - self._hb["at"], 2)
        if self.sess is not None:
            d["launches"] = self.sess.launches
            d["nch"] = self.sess.nch
            # rung 4 S6: sticky-until-reset OUT-FIFO overflow.  Reported as
            # a one-way SESSION alarm, not a counter — once a token has been
            # dropped, nothing this server has emitted since the last board
            # reset can be trusted.
            d["out_fifo_ovf"] = bool(self.sess.out_fifo_ovf)
            d["mmio"] = {"reads": self.sess.dev.n_rd,
                         "writes": self.sess.dev.n_wr} if self.sess.dev else {}
            p = self.sess.perf
            for k in ("preamble", "lite", "full"):
                if p[k]:
                    d.setdefault("device_ms", {})[k] = {
                        "mean": round(sum(p[k]) / len(p[k]), 2),
                        "min": round(min(p[k]), 2), "max": round(max(p[k]), 2),
                        "n": len(p[k])}
        return d


# ======================================================================
# jobs, sessions
# ======================================================================
class Job(object):
    """One /v1/generate request: an event mailbox plus its cancel flag."""

    def __init__(self, session_id, prompt, max_tokens, timeout, raw=False,
                 system=None, sample=None):
        self.id = uuid.uuid4().hex[:12]
        self.session_id = session_id
        self.prompt = prompt
        self.max_tokens = int(max_tokens)
        self.raw = bool(raw)              # /v1/generate "raw" (T4/T8)
        self.system = system              # /v1/generate "system" (T5)
        # S5: {"temperature","top_k","top_p","seed"} for THIS turn, already
        # merged with the server defaults by the handler
        self.sample = dict(sample or {})
        self.created = time.monotonic()
        self.deadline = self.created + float(timeout)
        self.events = queue.Queue(maxsize=EVENT_CAP)
        self.cancelled = False
        self.started = None
        self.finished = False
        self.last_pos = None

    def emit(self, name, obj):
        try:
            self.events.put_nowait((name, obj))
        except queue.Full:                                   # pragma: no cover
            pass

    def close(self):
        self.finished = True
        try:
            self.events.put_nowait(None)
        except queue.Full:                                   # pragma: no cover
            pass

    def cancel(self):
        self.cancelled = True


class SessionState(object):
    """A named history.  `fed`/`next_in` mirror chat_seq.ChatSession's own
    bookkeeping so they can be handed straight back to truncate_for()."""

    def __init__(self, sid):
        self.id = sid
        self.fed = []
        self.next_in = None
        self.ctx = 0
        self.turns = 0
        self.tokens = 0
        self.tmpl_turns = 0        # templated turns in the CURRENT context
        self.tmpl_wrapper = 0      # wrapper ids this session has fed
        self.created = time.time()
        self.last_used = time.time()

    def as_dict(self):
        return {"session_id": self.id, "context_tokens": self.ctx,
                "history_tokens": len(self.fed) + (self.next_in is not None),
                "turns": self.turns, "tokens": self.tokens,
                "templated_turns": self.tmpl_turns,
                "wrapper_tokens": self.tmpl_wrapper,
                "created": round(self.created, 3),
                "last_used": round(self.last_used, 3)}


# ======================================================================
# engine: one worker, FIFO queue, named sessions
# ======================================================================
class Engine(object):
    def __init__(self, backend, opts, log=print):
        self.b = backend
        self.opts = opts
        self.log = log
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.pending = collections.deque()
        self.current = None
        self.sessions = {}
        self.owner = None            # session_id resident on the board
        self.state = "starting"      # starting | ready | error | stopped
        self.error = None
        self.stopping = False
        self.started_at = time.time()
        self.ready_at = None
        self.consecutive_errors = 0
        self.m = {"turns": 0, "tokens": 0, "prompt_tokens": 0,
                  "replayed_tokens": 0, "resets": 0, "errors": 0,
                  "rejected": 0, "timeouts": 0, "cancelled": 0,
                  "steps_lite": 0, "steps_full": 0,
                  "device_ms": 0.0, "turn_wall_s": 0.0,
                  "queue_wait_s": 0.0, "max_queue_depth": 0}
        self.worker = threading.Thread(target=self._worker, name="board",
                                       daemon=True)

    # ---------------------------------------------------- lifecycle
    def start(self):
        self.worker.start()

    def stop(self, grace=10.0):
        with self.cv:
            self.stopping = True
            pend, self.pending = list(self.pending), collections.deque()
            cur = self.current
            self.cv.notify_all()
        for j in pend:
            j.emit("error", {"error": "server is shutting down",
                             "type": "shutdown"})
            j.close()
        if cur is not None:
            cur.cancel()
        self.worker.join(timeout=grace)
        with self.lock:
            self.state = "stopped"

    def wait_ready(self, timeout=None):
        t0 = time.monotonic()
        while True:
            with self.lock:
                if self.state in ("ready", "error", "stopped"):
                    return self.state
            if timeout is not None and time.monotonic() - t0 > timeout:
                return "starting"
            time.sleep(0.02)

    # ---------------------------------------------------- submission
    def submit(self, session_id, prompt, max_tokens, raw=False, system=None,
               sample=None):
        with self.cv:
            if self.state == "error":
                self.m["rejected"] += 1
                raise NotReady("backend failed to start: %s" % self.error)
            if self.stopping or self.state == "stopped":
                self.m["rejected"] += 1
                raise NotReady("server is shutting down")
            if len(self.pending) >= self.opts.queue_cap:
                self.m["rejected"] += 1
                raise QueueFull("queue is full (%d waiting, cap %d); the "
                                "board is ONE context and serves strictly "
                                "FIFO" % (len(self.pending),
                                          self.opts.queue_cap))
            job = Job(session_id, prompt, max_tokens,
                      self.opts.request_timeout, raw=raw, system=system,
                      sample=sample)
            self.pending.append(job)
            self.m["max_queue_depth"] = max(self.m["max_queue_depth"],
                                            len(self.pending))
            self.cv.notify_all()
            self._broadcast_locked()
        return job

    def _position_locked(self, job):
        """Turns ahead of `job`: 0 == running now."""
        try:
            idx = list(self.pending).index(job)
        except ValueError:
            return 0
        return idx + (1 if self.current is not None else 0)

    def _eta_locked(self, pos):
        if not self.m["turns"]:
            return None
        return round(pos * (self.m["turn_wall_s"] / self.m["turns"]), 2)

    def _broadcast_locked(self):
        """Tell every waiting client its (changed) position.  Honest: it is
        recomputed from the actual deque, not guessed."""
        for j in self.pending:
            pos = self._position_locked(j)
            if pos != j.last_pos:
                j.last_pos = pos
                j.emit("queue", {"position": pos,
                                 "queued": len(self.pending),
                                 "running_session": (self.current.session_id
                                                     if self.current else None),
                                 "eta_s": self._eta_locked(pos)})

    # ---------------------------------------------------- worker
    def _worker(self):
        try:
            self.b.start()
        except BaseException as e:                             # noqa: BLE001
            with self.cv:
                self.state, self.error = "error", "%s: %s" % (
                    type(e).__name__, e)
                pend, self.pending = list(self.pending), collections.deque()
                self.cv.notify_all()
            self.log("*** backend start FAILED: %s" % self.error)
            for j in pend:
                j.emit("error", {"error": self.error, "type": "backend"})
                j.close()
            return
        with self.cv:
            self.state = "ready"
            self.ready_at = time.time()
            self.cv.notify_all()
        self.log("  serve      backend ready (%s); queue cap %d, request "
                 "timeout %.0fs" % (self.b.name, self.opts.queue_cap,
                                    self.opts.request_timeout))
        last_hb = 0.0
        while True:
            job = None
            with self.cv:
                while not self.pending and not self.stopping:
                    self.cv.wait(timeout=HEARTBEAT_S)
                    if not self.pending:
                        break
                if self.stopping and not self.pending:
                    break
                if self.pending:
                    job = self.pending.popleft()
                    self.current = job
                    job.started = time.monotonic()
                    self._broadcast_locked()
            if job is None:
                if time.monotonic() - last_hb > HEARTBEAT_S:
                    last_hb = time.monotonic()
                    try:
                        self.b.heartbeat()
                    except Exception as e:                     # noqa: BLE001
                        self.log("  heartbeat  FAILED: %s" % e)
                continue
            with self.lock:
                self.m["queue_wait_s"] += max(0.0, job.started - job.created)
            try:
                self._run_job(job)
            except ServeError as e:
                self._job_failed(job, e, "request")
            except Exception as e:                             # noqa: BLE001
                # A backend/device fault must never take the worker down.
                self._job_failed(job, e, "backend")
            finally:
                job.close()
                with self.cv:
                    self.current = None
                    self._broadcast_locked()
                    self.cv.notify_all()
                last_hb = 0.0
        with self.cv:
            self.state = "stopped"
        try:
            self.b.stop()
        except Exception:                                      # noqa: BLE001
            pass

    def _job_failed(self, job, exc, kind):
        detail = "%s: %s" % (type(exc).__name__, exc)
        with self.lock:
            self.m["errors"] += 1
            self.consecutive_errors += 1
            if kind == "backend":
                # the chip's context is now unknown -> force a preamble on
                # the next turn instead of continuing into a corrupt KV bank
                self.owner = None
        self.log("  job %s FAILED (%s): %s" % (job.id, kind, detail))
        job.emit("error", {"error": str(exc), "type": kind,
                           "job_id": job.id, "session_id": job.session_id})

    # ---------------------------------------------------- one turn
    def _session(self, sid):
        with self.lock:
            s = self.sessions.get(sid)
            if s is None:
                s = self.sessions[sid] = SessionState(sid)
            return s

    def _save_owner(self):
        """Snapshot the live board bookkeeping into the resident session."""
        with self.lock:
            sid = self.owner
            s = self.sessions.get(sid) if sid else None
        if s is not None:
            s.fed, s.next_in, s.ctx = self.b.fed, self.b.next_in, self.b.T

    def _run_job(self, job):
        b = self.b
        if job.cancelled:
            with self.lock:
                self.m["cancelled"] += 1
            return
        if time.monotonic() > job.deadline:
            with self.lock:
                self.m["timeouts"] += 1
            raise ServeError("request timed out in the queue after %.1fs "
                             "(--request-timeout %gs)"
                             % (time.monotonic() - job.created,
                                self.opts.request_timeout))
        # wall time starts HERE, before any preamble/replay: that is the
        # latency the caller actually waits, and it keeps device_frac <= 1
        t0 = time.monotonic()
        s = self._session(job.session_id)
        # ---- the chat template lives in the encode path (T8) ----------
        # `first` and `carry` are the T3 incremental-with-carry state:
        # turn 1 of a context renders the optional system message, every
        # later turn only closes the previous assistant message and opens
        # the next one.  A context reset re-arms turn 1 unless history is
        # replayed into the fresh KV banks, in which case the last
        # replayed token IS the carry.
        templated = b.template_on and not job.raw
        sysmsg = job.system if job.system is not None else self.opts.system
        # ---- S5: arm sampling for THIS turn ---------------------------
        # A request that asks for temperature and cannot get it fails here,
        # before a single launch, with the reason (the on-chip top-k capture
        # unit is a next-rung RTL feature).  It is NEVER served greedy.
        sm = job.sample
        mode = b.set_sampling(sm.get("temperature", self.opts.temp),
                              sm.get("top_k", self.opts.top_k),
                              sm.get("top_p", self.opts.top_p),
                              sm.get("seed", self.opts.seed))

        def _encode(first, carry):
            return b.encode(job.prompt, raw=job.raw, first=first,
                            carry=carry, system=sysmsg)

        ids = _encode(first=(s.tmpl_turns == 0), carry=b.next_in)
        if not ids:
            raise ServeError("prompt encodes to zero tokens")
        ntok = job.max_tokens
        reset = False
        replay = []
        pre_ms = 0.0
        ctx_before = b.T
        body_ids = len(b.encode(job.prompt, raw=True))

        if self.owner != job.session_id:
            # session switch: the board holds someone else's KV banks
            self._save_owner()
            replay = b.truncate_for(s.fed, s.next_in, ids, ntok)
            pre_ms = b.preamble()
            reset = True
            with self.lock:
                self.owner = job.session_id
                self.m["resets"] += 1
            ids = _encode(first=(not replay and s.tmpl_turns == 0),
                          carry=(int(replay[-1]) if replay else None))
            feed = replay + [int(i) for i in ids]
        else:
            feed, _nsteps, need_reset = b.plan_turn(ids, ntok)
            if need_reset:
                # context overflow: chat_seq's own auto-reset rule
                replay = b.truncate_for(b.fed, b.next_in, ids, ntok)
                pre_ms = b.preamble()
                reset = True
                with self.lock:
                    self.m["resets"] += 1
                if not replay:
                    s.tmpl_turns = 0          # fresh context, turn 1 again
                ids = _encode(first=(not replay),
                              carry=(int(replay[-1]) if replay else None))
                feed = replay + [int(i) for i in ids]
        wrapper = len(ids) - body_ids if templated else 0
        nsteps = len(feed) + ntok - 1
        if b.T + nsteps > b.max_ctx:
            raise ServeError(
                "turn needs %d steps but only %d of %d context steps remain "
                "(reset did not free enough: shorten the prompt or "
                "max_tokens)" % (nsteps, b.max_ctx - b.T, b.max_ctx))

        job.emit("start", {"job_id": job.id, "session_id": job.session_id,
                           "prompt_tokens": len(ids),
                           "body_tokens": body_ids,
                           # wrapper ids + any rendered system message
                           "template_tokens": wrapper,
                           "template": templated,
                           "template_turn": (s.tmpl_turns + 1 if templated
                                             else None),
                           "system": sysmsg if (templated and not s.tmpl_turns
                                                and not replay) else None,
                           "replayed": len(replay), "reset": reset,
                           "steps": nsteps, "context_before": ctx_before,
                           "max_tokens": ntok,
                           "prefill": self.opts.prefill,
                           "sampling": mode,
                           "queue_wait_s": round(job.started - job.created, 3),
                           "mock": b.mock})
        if replay:
            self.log("  job %s session %r: context reset + replay of %d "
                     "history tokens = %d extra prefill steps (~%.0f ms each "
                     "on the board)"
                     % (job.id, job.session_id, len(replay), len(replay),
                        PREFILL_MS_NOMINAL))

        all_full = (self.opts.prefill == "full")
        gen, shown = [], ""
        lite_ms, full_ms = [], []
        stop = None
        tok = feed[0]
        for i in range(nsteps):
            if job.cancelled:
                stop = "cancelled"
                with self.lock:
                    self.m["cancelled"] += 1
                break
            if time.monotonic() > job.deadline:
                stop = "timeout"
                with self.lock:
                    self.m["timeouts"] += 1
                raise ServeError(
                    "request exceeded --request-timeout %gs after %d/%d "
                    "steps" % (self.opts.request_timeout, i, nsteps))
            lite = (i < len(feed) - 1) and not all_full
            out, ms = b.step(tok, lite)
            if lite:
                lite_ms.append(ms)
            else:
                full_ms.append(ms)
            if i < len(feed) - 1:
                job.emit("prefill", {"index": i + 1, "total": len(feed) - 1,
                                     "device_ms": round(ms, 2), "lite": lite})
            if out is not None and i >= len(feed) - 1:
                gen.append(int(out))
                # SHOWN text drops the chat control ids; `id` below and
                # `token_ids` in stats stay unfiltered
                text = b.decode(b.visible(gen))
                delta, shown = text[len(shown):], text
                job.emit("token", {"index": len(gen) - 1, "id": int(out),
                                   "text": delta, "device_ms": round(ms, 2)})
                if int(out) in tuple(b.stop_ids):
                    stop = "eos"
                    break
            if i + 1 < nsteps:
                tok = feed[i + 1] if i + 1 < len(feed) else out
        wall = time.monotonic() - t0

        self._save_owner()
        s.turns += 1
        s.tokens += len(gen)
        if templated:
            s.tmpl_turns += 1
            s.tmpl_wrapper += wrapper
        s.last_used = time.time()
        dev_ms = pre_ms + sum(lite_ms) + sum(full_ms)
        tel = b.sample_telemetry()
        with self.lock:
            self.consecutive_errors = 0
            self.m["turns"] += 1
            self.m["tokens"] += len(gen)
            self.m["prompt_tokens"] += len(ids)
            self.m["replayed_tokens"] += len(replay)
            self.m["steps_lite"] += len(lite_ms)
            self.m["steps_full"] += len(full_ms)
            self.m["device_ms"] += dev_ms
            self.m["turn_wall_s"] += wall
        st = {"job_id": job.id, "session_id": job.session_id,
              "tokens": len(gen), "token_ids": gen,
              "text": b.decode(b.visible(gen)),
              "template": templated, "template_tokens": wrapper,
              "template_turn": s.tmpl_turns if templated else None,
              "stop": stop or "max_tokens",
              "steps": len(lite_ms) + len(full_ms),
              "prefill_steps": len(lite_ms), "decode_steps": len(full_ms),
              "prefill_ms_mean": (round(sum(lite_ms) / len(lite_ms), 2)
                                  if lite_ms else None),
              "decode_ms_mean": (round(sum(full_ms) / len(full_ms), 2)
                                 if full_ms else None),
              "preamble_ms": round(pre_ms, 2) if reset else None,
              "device_ms_total": round(dev_ms, 2),
              "wall_s": round(wall, 3),
              "tok_per_s": round(len(gen) / wall, 3) if wall > 0 else None,
              "device_frac": round(dev_ms / 1e3 / wall, 3) if wall > 0 else None,
              "replayed": len(replay), "reset": reset,
              # S5 telemetry: the mode this turn ran in, the seed it used
              # and what the draw cost.  `sampling.mode == "greedy"` means
              # the chip's own argmax, bit for bit.
              "mode": mode["mode"], "seed": mode.get("seed"),
              "sampling": dict(mode, telemetry=tel),
              "sample_ms": (tel or {}).get("sample_ms_mean"),
              "context_used": b.T, "context_max": b.max_ctx,
              "context_fill": round(b.T / float(b.max_ctx), 4),
              "queue_wait_s": round(job.started - job.created, 3),
              "mock": b.mock}
        job.emit("stats", st)

    # ---------------------------------------------------- introspection
    def reset_session(self, sid):
        """Drop a named history.

        LAZY BY DESIGN: the KV banks are cleared by the preamble that the
        next turn runs anyway (a turn for a non-resident session always
        preambles).  Resetting eagerly would spend a board launch — and a
        queue slot — on an idle client.
        """
        with self.lock:
            existed = sid in self.sessions
            self.sessions.pop(sid, None)
            was_owner = (self.owner == sid)
            if was_owner:
                self.owner = None
        return {"session_id": sid, "existed": existed,
                "was_resident": was_owner,
                "board_reset": "deferred to the next turn's preamble"
                               if was_owner else "not needed"}

    def health(self):
        with self.lock:
            depth = len(self.pending)
            cur = self.current
            st = self.state
            err = self.error
            owner = self.owner
            nses = len(self.sessions)
            cerr = self.consecutive_errors
        h = {"status": st, "error": err, "mock": self.b.mock,
             "serve_version": VERSION, "pid": os.getpid(),
             "board": ("busy" if cur is not None else "free"),
             "running": ({"job_id": cur.id, "session_id": cur.session_id,
                          "elapsed_s": round(time.monotonic() - cur.started, 2)}
                         if cur is not None and cur.started else None),
             "queue_depth": depth, "queue_cap": self.opts.queue_cap,
             "resident_session": owner, "sessions": nses,
             "consecutive_errors": cerr,
             "uptime_s": round(time.time() - self.started_at, 2),
             "ready_after_s": (round(self.ready_at - self.started_at, 2)
                               if self.ready_at else None),
             "lock": (None if self.b.mock else self.opts.lock)}
        if st == "ready":
            try:
                h["context"] = {"used": self.b.T, "max": self.b.max_ctx,
                                "fill": round(self.b.T / float(self.b.max_ctx),
                                              4)}
            except Exception:                                  # noqa: BLE001
                pass
        try:
            h["backend"] = self.b.health()
        except Exception as e:                                 # noqa: BLE001
            h["backend"] = {"error": str(e)}
        return h

    def metrics(self):
        with self.lock:
            m = dict(self.m)
            depth = len(self.pending)
            sess = [s.as_dict() for s in self.sessions.values()]
        up = time.time() - self.started_at
        m["uptime_s"] = round(up, 2)
        m["queue_depth"] = depth
        m["mean_tok_per_s"] = (round(m["tokens"] / m["turn_wall_s"], 3)
                               if m["turn_wall_s"] > 0 else None)
        m["mean_turn_s"] = (round(m["turn_wall_s"] / m["turns"], 3)
                            if m["turns"] else None)
        m["mean_queue_wait_s"] = (round(m["queue_wait_s"] / m["turns"], 3)
                                  if m["turns"] else None)
        m["device_ms"] = round(m["device_ms"], 2)
        m["turn_wall_s"] = round(m["turn_wall_s"], 3)
        m["queue_wait_s"] = round(m["queue_wait_s"], 3)
        m["device_frac"] = (round(m["device_ms"] / 1e3 / m["turn_wall_s"], 3)
                            if m["turn_wall_s"] > 0 else None)
        m["mock"] = self.b.mock
        m["sessions"] = sess
        return m

    def sessions_view(self):
        with self.lock:
            return {"resident": self.owner,
                    "sessions": [s.as_dict()
                                 for s in self.sessions.values()]}


# ======================================================================
# HTTP
# ======================================================================
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "fable5-serve/1"
    sys_version = ""
    timeout = 30.0          # socket timeout: a half-sent body or a client
                            # that stops reading an SSE stream cannot pin a
                            # thread (the SSE writer keepalives every 10 s)

    # -------------------------------------------------- helpers
    @property
    def engine(self):
        return self.server.engine

    def log_message(self, fmt, *a):
        if getattr(self.server, "verbose", False):
            sys.stderr.write("  http       %s - %s\n"
                             % (self.address_string(), fmt % a))

    def _json(self, code, obj):
        body = json.dumps(obj, indent=1, default=str).encode() + b"\n"
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _err(self, code, msg, **kw):
        d = {"error": msg, "status": code}
        d.update(kw)
        self._json(code, d)

    def _body(self):
        n = self.headers.get("Content-Length")
        if n is None:
            return {}
        try:
            n = int(n)
        except ValueError:
            raise ServeError("Content-Length is not an integer")
        if n < 0 or n > MAX_BODY:
            raise ServeError("body too large (%s B, cap %d)" % (n, MAX_BODY))
        raw = self.rfile.read(n) if n else b""
        if not raw.strip():
            return {}
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise ServeError("body is not valid JSON: %s" % e)
        if not isinstance(obj, dict):
            raise ServeError("body must be a JSON object")
        return obj

    # -------------------------------------------------- routes
    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/v1/health":
            return self._json(200, self.engine.health())
        if path == "/v1/metrics":
            return self._json(200, self.engine.metrics())
        if path == "/v1/sessions":
            return self._json(200, self.engine.sessions_view())
        if path in ("/v1/generate", "/v1/reset"):
            return self._err(405, "%s is POST-only" % path)
        if path in ("/", "/v1"):
            return self._json(200, {
                "service": VERSION,
                "endpoints": ["POST /v1/generate (SSE)", "GET /v1/health",
                              "GET /v1/metrics", "GET /v1/sessions",
                              "POST /v1/reset"],
                "note": "the board is ONE context: requests are served "
                        "strictly FIFO by a single worker"})
        return self._err(404, "no such endpoint: %s" % path)

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        try:
            body = self._body()
        except ServeError as e:
            return self._err(400, str(e))
        if path == "/v1/reset":
            sid = body.get("session_id", "default")
            try:
                sid = self._session_id(sid)
            except ServeError as e:
                return self._err(400, str(e))
            return self._json(200, self.engine.reset_session(sid))
        if path == "/v1/generate":
            return self._generate(body)
        return self._err(404, "no such endpoint: %s" % path)

    def do_PUT(self):
        self._err(405, "method not allowed")

    do_DELETE = do_PUT
    do_PATCH = do_PUT

    # -------------------------------------------------- validation
    def _session_id(self, sid):
        if not isinstance(sid, str):
            raise ServeError("session_id must be a string")
        if not sid or len(sid) > 64:
            raise ServeError("session_id must be 1..64 characters")
        bad = set(sid) - SESSION_CHARS
        if bad:
            raise ServeError("session_id may only contain [A-Za-z0-9_.:-] "
                             "(bad: %s)" % "".join(sorted(bad)))
        return sid

    def _validate(self, body):
        if "prompt" not in body:
            raise ServeError("missing required field 'prompt'")
        p = body["prompt"]
        if not isinstance(p, str):
            raise ServeError("prompt must be a string")
        if not p.strip():
            raise ServeError("prompt is empty")
        if len(p) > MAX_BODY // 2:
            raise ServeError("prompt is too long")
        n = body.get("max_tokens", self.server.opts.max_tokens_default)
        if isinstance(n, bool) or not isinstance(n, int):
            raise ServeError("max_tokens must be an integer")
        cap = self.server.opts.max_tokens_cap
        if n < 1 or n > cap:
            raise ServeError("max_tokens must be 1..%d" % cap)
        sid = self._session_id(body.get("session_id", "default"))
        # docs/INSTRUCT_SPEC.md T8: "raw" opts out of the chat template,
        # DEFAULT FALSE (i.e. templated).  T5: an optional per-request
        # system message, used only on a session's first templated turn.
        raw = body.get("raw", False)
        if not isinstance(raw, bool):
            raise ServeError("raw must be a boolean (default false = the "
                             "chat template is applied)")
        sysmsg = body.get("system", None)
        if sysmsg is not None:
            if not isinstance(sysmsg, str):
                raise ServeError("system must be a string or null")
            if len(sysmsg) > MAX_BODY // 4:
                raise ServeError("system message is too long")
        # docs/SAMPLING_SPEC.md S5: temperature/top_k/top_p/seed.  Omitted
        # fields fall back to the server defaults (greedy unless the
        # operator changed them).  A request that asks for temperature on a
        # bitstream without the on-chip top-k capture unit is REFUSED by
        # the backend with the reason — never silently served greedy.
        sample = {}
        t = body.get("temperature", None)
        if t is not None:
            if isinstance(t, bool) or not isinstance(t, (int, float)):
                raise ServeError("temperature must be a number")
            if not (0.0 <= float(t) <= MAX_TEMP):
                raise ServeError("temperature must be 0..%g (0 = greedy)"
                                 % MAX_TEMP)
            sample["temperature"] = float(t)
        k = body.get("top_k", None)
        if k is not None:
            if isinstance(k, bool) or not isinstance(k, int):
                raise ServeError("top_k must be an integer (0 = no cut)")
            if k < 0 or k > 100000:
                raise ServeError("top_k must be 0..100000")
            sample["top_k"] = int(k)
        tp = body.get("top_p", None)
        if tp is not None:
            if isinstance(tp, bool) or not isinstance(tp, (int, float)):
                raise ServeError("top_p must be a number")
            if not (0.0 < float(tp) <= 1.0):
                raise ServeError("top_p must be in (0, 1] (1.0 = off)")
            sample["top_p"] = float(tp)
        sd = body.get("seed", None)
        if sd is not None:
            if isinstance(sd, bool) or not isinstance(sd, int):
                raise ServeError("seed must be an integer")
            if not (0 <= sd < (1 << 63)):
                raise ServeError("seed must be 0..2^63-1")
            sample["seed"] = int(sd)
        # RUNG4_SPEC S4: a request MAY assert which stream it expects, and a
        # mismatch is a 400 — never a silent switch.  The server's --nch
        # decided the weight PLACEMENT in DDR at start-up; honouring a
        # per-request flip would mean re-uploading ~900 MiB mid-queue and
        # invalidating every other session's resident context.
        nch = body.get("nch", None)
        if nch is not None:
            have = self.server.opts.nch
            if isinstance(nch, bool) or not isinstance(nch, int):
                raise ServeError("nch must be an integer")
            if int(nch) != int(have):
                raise ServeError(
                    "this server is running nch=%d and cannot switch to "
                    "nch=%d: the two modes place the weight images "
                    "differently in DDR (RUNG4_SPEC S4), so a flip is a full "
                    "re-upload.  Start a second server with --nch %d."
                    % (have, int(nch), int(nch)))
        extra = set(body) - {"prompt", "max_tokens", "session_id", "raw",
                             "system", "nch"} - set(SAMPLE_FIELDS)
        if extra:
            raise ServeError("unknown field(s): %s" % ", ".join(sorted(extra)))
        return sid, p, n, raw, sysmsg, sample

    # -------------------------------------------------- SSE
    def _generate(self, body):
        try:
            sid, prompt, ntok, raw, sysmsg, sample = self._validate(body)
        except ServeError as e:
            return self._err(400, str(e))
        try:
            job = self.engine.submit(sid, prompt, ntok, raw=raw,
                                     system=sysmsg, sample=sample)
        except QueueFull as e:
            self.send_response(429)
            b = json.dumps({"error": str(e), "status": 429,
                            "queue_cap": self.server.opts.queue_cap}).encode()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Retry-After", "2")
            self.end_headers()
            self.wfile.write(b)
            return
        except NotReady as e:
            return self._err(503, str(e))
        self._stream(job)

    def _stream(self, job):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        last = time.monotonic()
        try:
            while True:
                try:
                    item = job.events.get(timeout=1.0)
                except queue.Empty:
                    if time.monotonic() - last > KEEPALIVE_S:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        last = time.monotonic()
                    continue
                if item is None:
                    break
                self.wfile.write(sse(item[0], item[1]))
                self.wfile.flush()
                last = time.monotonic()
        except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError):
            # client hung up -> stop the turn, free the board, keep serving
            job.cancel()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ======================================================================
# selftest (no board, no sockets beyond loopback)
# ======================================================================
def selftest(opts, log=print):
    """Unit-level checks of the pieces the mock end-to-end run cannot see."""
    npass = nfail = 0

    def check(name, cond, detail=""):
        nonlocal npass, nfail
        if cond:
            npass += 1
        else:
            nfail += 1
            log("    FAIL %s: %s" % (name, detail))

    log("serve.py selftest (no board):")
    b = MockBackend(max_ctx=20, step_ms=0.0, raw=True)
    b.start()
    check("mock encode/decode round-trips text",
          b.decode(b.encode("hi there")) == "hi there")
    check("plan_turn steps = P + N - 1", b.plan_turn([1, 2, 3], 8)[1] == 10)
    b._T, b._fed, b._next_in = 18, list(range(18)), 5
    feed, ns, need = b.plan_turn([1, 2, 3], 4)
    check("carry-over token leads the feed", feed[0] == 5, str(feed))
    check("context guard fires", need is True, "%d+%d vs 20" % (b.T, ns))
    keep = b.truncate_for(b.fed, b.next_in, [1, 2, 3], 4)
    check("truncation leaves room for the whole turn",
          len(keep) + 3 + 4 - 1 <= 20, str(len(keep)))
    try:
        b.truncate_for([], None, list(range(30)), 4)
        check("an over-long prompt is refused", False)
    except ServeError:
        check("an over-long prompt is refused", True)

    # ---- chat template in the encode path (docs/INSTRUCT_SPEC.md T8) ----
    log("  chat template (T4/T5/T8) in BoardBackend/MockBackend.encode:")
    tb = MockBackend(max_ctx=500, step_ms=0.0, log=lambda *a: None)
    tb.start()
    if tb.template is None:
        log("    (template checks SKIPPED: chat_seq did not import here)")
    else:
        import chat_seq as CS                                  # noqa: N806
        t = tb.template
        check("the template is ON by default (T4)", tb.template_on is True)
        one = tb.encode("hi", first=True)
        think = [CS.TOK_THINK] + t.nl2 + [CS.TOK_THINK_END] + t.nl2
        check("turn 1 is <|im_start|>user ... + the generation prompt",
              one[0] == CS.TOK_IM_START and one[-len(think):] == think,
              str(one))
        check("turn 1 wrapper size is the computed 1-message overhead",
              len(one) - len(tb._enc("hi")) == t.overhead(1),
              "%d vs %d" % (len(one) - len(tb._enc("hi")), t.overhead(1)))
        cont = tb.encode("hi", first=False, carry=CS.TOK_IM_END)
        check("a continuation opens with enc('\\n') (the carry supplied "
              "<|im_end|>) — T3", cont[:len(t.nl)] == t.nl, str(cont[:3]))
        check("a continuation does NOT replay turn 1",
              len(cont) < len(one) + len(t.nl) + 2 and CS.TOK_IM_START in cont)
        cut = tb.encode("hi", first=False, carry=4242)
        check("a reply cut short by max_tokens gets an explicit <|im_end|>",
              cut[0] == CS.TOK_IM_END and cut[1:] == cont, str(cut[:3]))
        sysone = tb.encode("hi", first=True, system="be brief")
        # the mock's role headers are byte-length, so spell the one
        # message out; with the real tokenizer this is per_message + body
        check("a system message is 1 extra message of overhead (T5)",
              len(sysone) - len(one) == 2 + len(t.hdr["system"]) + len(t.nl)
              + len(tb._enc("be brief")),
              "%d" % (len(sysone) - len(one)))
        check("the system message is turn-1 only (T5)",
              tb.encode("hi", first=False, carry=CS.TOK_IM_END,
                        system="be brief") == cont)
        check("raw=True bypasses the wrapper entirely (T4)",
              tb.encode("hi", raw=True) == tb._enc("hi"))
        check("the display filter drops the chat control ids",
              tb.visible([CS.TOK_THINK, 2001, CS.TOK_IM_END]) == [2001])
        # a --raw backend never templates, whatever the request says
        rb = MockBackend(step_ms=0.0, raw=True, log=lambda *a: None)
        rb.start()
        check("--raw serves every request untemplated",
              rb.template_on is False and rb.encode("hi") == rb._enc("hi"))
        # the REAL tokenizer, if this machine has the HF cache: the ids
        # serve.py would feed must be the HF 19-id reference
        try:
            rtk = CS.load_tokenizer(log=lambda *a: None)
            rt = CS.ChatTemplate(rtk)
            check("serve's encode path reproduces the HF 19-id reference",
                  rt.turn_ids(CS.HF_REF_USER, first=True) == CS.HF_REF_SINGLE)
            check("...and the 3-message incremental concatenation",
                  rt.turn_ids(CS.HF_REF_USER, first=True)
                  + rtk.encode(CS.HF_REF_REPLY) + [CS.TOK_IM_END]
                  + rt.turn_ids(CS.HF_REF_USER2, first=False,
                                carry=CS.TOK_IM_END) == CS.HF_REF_3MSG_INCR)
        except Exception as _e:                                # noqa: BLE001
            log("    (HF id equality SKIPPED: %s: %s)"
                % (type(_e).__name__, _e))

    # ---- request validation of the new fields --------------------------
    class _V(object):
        _session_id = Handler._session_id
        _validate = Handler._validate

    v = _V()
    v.server = types.SimpleNamespace(opts=opts)
    check("raw defaults to FALSE (the template is the default, T4)",
          v._validate({"prompt": "hi"})[3] is False)
    check("raw:true is accepted and carried",
          v._validate({"prompt": "hi", "raw": True})[3] is True)
    check("system is accepted and carried",
          v._validate({"prompt": "hi", "system": "be brief"})[4] == "be brief")
    for bad, why in (({"prompt": "hi", "raw": "yes"}, "raw must be a bool"),
                     ({"prompt": "hi", "system": 7}, "system must be a str"),
                     ({"prompt": "hi", "nope": 1}, "unknown fields")):
        try:
            v._validate(bad)
            check("_validate rejects: %s" % why, False)
        except ServeError:
            check("_validate rejects: %s" % why, True)

    # ---- S4: the nch assertion ------------------------------------------
    log("  rung 4 S4: the per-request nch assertion")
    have = int(getattr(opts, "nch", 1) or 1)
    check("a request may assert the server's own nch",
          v._validate({"prompt": "hi", "nch": have})[0] is not None)
    check("nch is optional (omitting it means 'whatever the server runs')",
          v._validate({"prompt": "hi"})[0] is not None)
    for bad, why in (({"prompt": "x", "nch": have + 3}, "a different nch"),
                     ({"prompt": "x", "nch": "four"}, "a non-integer nch"),
                     ({"prompt": "x", "nch": True}, "a boolean nch")):
        try:
            v._validate(bad)
            check("_validate rejects: %s" % why, False)
        except ServeError as e:
            check("_validate rejects: %s" % why, True)
            if "different" in why:
                check("...and the refusal explains the re-upload",
                      "re-upload" in str(e) and "S4" in str(e), str(e))
    ba = BoardBackend(types.SimpleNamespace(**dict(
        vars(opts), nch=4, template=None)), log=lambda *a: None)._args()
    check("--nch 4 selects the 4-chan template by default",
          ba.nch == 4 and ba.template.endswith("model_v2_s1.e4"), ba.template)
    b1 = BoardBackend(types.SimpleNamespace(**dict(
        vars(opts), nch=1, template=None)), log=lambda *a: None)._args()
    check("--nch 1 keeps the shipped 1-chan template",
          b1.nch == 1 and b1.template.endswith("model_v2_s1.e"), b1.template)

    # ---- S5: the sampling request fields -------------------------------
    log("  sampling request fields, refusal path and telemetry (S5)")
    check("no sampling fields -> an empty override (the server default "
          "decides)", v._validate({"prompt": "hi"})[5] == {})
    got = v._validate({"prompt": "hi", "temperature": 0.8, "top_k": 32,
                       "top_p": 0.95, "seed": 7})[5]
    check("all four sampling fields are carried",
          got == {"temperature": 0.8, "top_k": 32, "top_p": 0.95, "seed": 7},
          str(got))
    check("temperature 0 is accepted and means greedy",
          v._validate({"prompt": "hi", "temperature": 0})[5]
          == {"temperature": 0.0})
    for bad, why in (({"prompt": "x", "temperature": "hot"}, "temperature str"),
                     ({"prompt": "x", "temperature": -1}, "temperature < 0"),
                     ({"prompt": "x", "temperature": 99}, "temperature > cap"),
                     ({"prompt": "x", "temperature": True}, "temperature bool"),
                     ({"prompt": "x", "top_k": -1}, "top_k < 0"),
                     ({"prompt": "x", "top_k": 1.5}, "top_k float"),
                     ({"prompt": "x", "top_p": 0}, "top_p 0"),
                     ({"prompt": "x", "top_p": 1.2}, "top_p > 1"),
                     ({"prompt": "x", "seed": -5}, "negative seed"),
                     ({"prompt": "x", "seed": "abc"}, "seed str")):
        try:
            v._validate(bad)
            check("_validate rejects: %s" % why, False)
        except ServeError:
            check("_validate rejects: %s" % why, True)
    # a backend that cannot sample must REFUSE, never serve greedy silently
    nb = BackendBase()
    check("the base backend cannot sample", not nb.sampling["available"])
    check("temperature 0 is fine on a backend that cannot sample",
          nb.set_sampling(0.0, 50, 1.0, None)["mode"] == "greedy")
    try:
        nb.set_sampling(0.8, 50, 1.0, 1)
        check("a sampled request is REFUSED, not downgraded to greedy", False)
    except ServeError as _e:
        check("a sampled request is REFUSED, not downgraded to greedy", True)
    try:
        import chat_seq as _CS
        bb = BoardBackend(opts)
        bb.sess = types.SimpleNamespace(
            cand=_CS.ChipTopKSource(None, base=None), sampler=None,
            sample_log=[], verify_head=False)
        bb.CS = _CS
        check("the board backend reports the capture unit as ABSENT",
              not bb.sampling["available"]
              and "rung" in bb.sampling["why"].lower(), bb.sampling["why"])
        try:
            bb.set_sampling(0.8, 32, 0.95, 1)
            check("the board backend refuses a sampled turn today", False)
        except ServeError as _e:
            check("the board backend refuses a sampled turn today",
                  "top-k capture unit" in str(_e), str(_e)[:90])
        check("the board backend still arms greedy",
              bb.set_sampling(0.0, 32, 0.95, 1)["mode"] == "greedy")
    except ImportError as _e:                                  # noqa: BLE001
        log("    (board-backend refusal SKIPPED: %s)" % _e)
    # the mock simulates a capture unit, so the whole path is testable
    mb = MockBackend(step_ms=0.0)
    if mb.sampling["available"]:
        m1 = mb.set_sampling(0.9, 32, 0.95, 4242)
        check("the mock arms sampling and reports mode/seed",
              m1["mode"] == "sampled" and m1["seed"] == 4242, str(m1))
        mb.start()
        run1 = [mb.step(700 + i, False)[0] for i in range(6)]
        mb.set_sampling(0.9, 32, 0.95, 4242)
        mb.preamble()
        run2 = [mb.step(700 + i, False)[0] for i in range(6)]
        mb.set_sampling(0.9, 32, 0.95, 99)
        mb.preamble()
        run3 = [mb.step(700 + i, False)[0] for i in range(6)]
        check("same seed -> identical tokens through the serve path",
              run1 == run2, f"{run1} vs {run2}")
        check("a different seed -> different tokens", run1 != run3,
              f"{run1} vs {run3}")
        tel = mb.sample_telemetry()
        check("telemetry has mode/seed/sample_ms",
              tel["mode"] == "sampled" and tel["seed"] == 99
              and tel["sample_ms_mean"] is not None, str(tel))
        mb.set_sampling(0.0, 32, 0.95, None)
        check("disarming returns the mock to its deterministic greedy reply",
              mb.sample_telemetry() is None)
    else:
        log("    (mock sampling SKIPPED: %s)" % mb.sampling["why"])

    # ---- a sampled request on a backend without the capture unit -------
    class _NoSample(MockBackend):
        """Exactly today's board: everything works EXCEPT sampling."""

        @property
        def sampling(self):
            return {"available": False, "k": 0, "source": None,
                    "why": "sampling needs the on-chip top-k capture unit, "
                           "which needs the rung-4 bitstream (build_033+, TOPK IDENT probe)."}

    en = Engine(_NoSample(step_ms=0.0), opts, log=lambda *a: None)
    en.start()
    en.wait_ready(10)
    jn = en.submit("s", "hi", 3, sample={"temperature": 0.9})
    evn = _drain(jn)
    errs = [d for n, d in evn if n == "error"]
    check("a sampled request is REFUSED end to end, with the reason",
          len(errs) == 1 and "rung 4" in errs[0]["error"], str(evn[:2]))
    check("the refusal produces NO tokens and NO stats (never silently "
          "greedy)", not [n for n, _ in evn if n in ("token", "stats")],
          str([n for n, _ in evn]))
    jg = en.submit("s", "hi", 2)
    evg = _drain(jg)
    check("the same server still serves greedy right after a refusal",
          [n for n, _ in evg].count("stats") == 1
          and [d for n, d in evg if n == "stats"][0]["mode"] == "greedy",
          str([n for n, _ in evg]))
    en.stop(grace=5.0)

    e = Engine(MockBackend(step_ms=0.0), opts, log=lambda *a: None)
    e.start()
    check("engine reaches ready", e.wait_ready(10) == "ready")
    j = e.submit("s1", "hello", 3)
    ev = _drain(j)
    check("a turn ends in exactly one stats event",
          [n for n, _ in ev].count("stats") == 1, str([n for n, _ in ev]))
    names = [n for n, _ in ev]
    check("stats is the LAST event", names[-1] == "stats", str(names))
    toks = [d for n, d in ev if n == "token"]
    check("max_tokens is honoured", len(toks) == 3, str(len(toks)))
    check("token deltas concatenate to the stats text",
          "".join(t["text"] for t in toks)
          == [d for n, d in ev if n == "stats"][0]["text"])
    j2 = e.submit("s1", "hello", 3)
    ev2 = _drain(j2)
    check("same session, same prompt -> deterministic ids",
          [d["id"] for n, d in ev2 if n == "token"]
          != [], "mock produced no tokens")
    check("continuing a session does NOT reset",
          [d for n, d in ev2 if n == "start"][0]["reset"] is False)
    j3 = e.submit("s2", "hello", 2)
    ev3 = _drain(j3)
    st3 = [d for n, d in ev3 if n == "start"][0]
    check("switching sessions resets and replays", st3["reset"] is True
          and st3["replayed"] == 0, str(st3))
    j4 = e.submit("s1", "hello", 2)
    st4 = [d for n, d in _drain(j4) if n == "start"][0]
    check("switching BACK replays the saved history",
          st4["reset"] is True and st4["replayed"] > 0, str(st4))
    r = e.reset_session("s1")
    check("reset drops the history", r["existed"] is True, str(r))
    check("metrics count the turns", e.metrics()["turns"] == 4,
          str(e.metrics()["turns"]))
    check("health works without taking a turn",
          e.health()["board"] == "free" and e.health()["status"] == "ready")
    # a backend fault must not wedge the worker
    e.b.fail_on = e.b.encode("x")[0]
    jf = e.submit("s3", "x", 2)
    evf = _drain(jf)
    check("an injected backend fault becomes an error event",
          [n for n, _ in evf][-1] == "error", str([n for n, _ in evf]))
    e.b.fail_on = None
    jg = e.submit("s4", "after the fault", 2)
    check("the queue keeps serving after a fault",
          [n for n, _ in _drain(jg)][-1] == "stats")
    e.stop()

    # ---- per-session incremental multi-turn, end to end (T3/T8) --------
    et = Engine(MockBackend(step_ms=0.0), opts, log=lambda *a: None)
    et.start()
    et.wait_ready(10)
    if not et.b.template_on:
        log("    (engine template checks SKIPPED: no chat_seq here)")
    else:
        import chat_seq as CS                                  # noqa: N806
        s1 = [d for n, d in _drain(et.submit("t1", "hello", 2))
              if n == "start"][0]
        fed1 = list(et.b.fed)
        check("a served turn reports the template it applied",
              s1["template"] is True and s1["template_turn"] == 1
              and s1["template_tokens"] == s1["prompt_tokens"]
              - s1["body_tokens"], str(s1))
        check("turn 1 fed the wrapper, starting at <|im_start|>",
              fed1[0] == CS.TOK_IM_START, str(fed1[:3]))
        s2 = [d for n, d in _drain(et.submit("t1", "again", 2))
              if n == "start"][0]
        fed2 = list(et.b.fed)
        check("turn 2 of the SAME session is incremental, not a replay",
              s2["template_turn"] == 2 and s2["reset"] is False
              and s2["replayed"] == 0 and fed2[:len(fed1)] == fed1, str(s2))
        check("turn 2 spliced a message boundary onto the carry (T3)",
              CS.TOK_IM_END in fed2[len(fed1):len(fed1) + 3]
              and CS.TOK_IM_START in fed2[len(fed1):], str(fed2[len(fed1):]))
        s3 = [d for n, d in _drain(et.submit("t1", "bare", 2, raw=True))
              if n == "start"][0]
        fed3 = list(et.b.fed)
        check("a raw:true request bypasses the template for that turn only",
              s3["template"] is False and s3["template_tokens"] == 0
              and fed3[len(fed2):len(fed2) + 1] != [CS.TOK_IM_START], str(s3))
        s4 = [d for n, d in _drain(et.submit("t2", "hi", 2,
                                             system="be brief"))
              if n == "start"][0]
        check("a new session's first turn renders the system message",
              s4["template_turn"] == 1 and s4["system"] == "be brief"
              and s4["template_tokens"]
              > et.b.template.overhead(1), str(s4))
        check("sessions report their template bookkeeping",
              et.sessions_view()["sessions"][0]["templated_turns"] >= 1,
              str(et.sessions_view()["sessions"][0]))
    et.stop()

    # a backend that cannot come up at all -> 503, never a hang
    class _DeadBackend(MockBackend):
        def start(self):
            raise ServeError("simulated bring-up failure (no board)")

    e2 = Engine(_DeadBackend(step_ms=0.0), opts, log=lambda *a: None)
    e2.start()
    check("a failed bring-up lands in state 'error'",
          e2.wait_ready(10) == "error", e2.state)
    try:
        e2.submit("s", "hi", 1)
        check("submit after a failed bring-up is refused (503)", False)
    except NotReady:
        check("submit after a failed bring-up is refused (503)", True)
    h = e2.health()
    check("health reports the bring-up error without touching the device",
          h["status"] == "error" and "simulated" in (h["error"] or ""), str(h))
    e2.stop()

    # the real backend's call surface, if chat_seq imports here (no device)
    try:
        check("chat_seq API is what BoardBackend calls",
              check_backend_api(opts, log=log))
    except Exception as e:                                     # noqa: BLE001
        log("    (backend API check SKIPPED: %s: %s)" % (type(e).__name__, e))
    log("  serve selftest: %d passed, %d failed" % (npass, nfail))
    return nfail == 0


def check_backend_api(opts, log=print):
    """Import sw/chat_seq.py and verify EVERY name BoardBackend calls.

    NO DEVICE IS TOUCHED: this only imports the module and looks at
    signatures, so it runs on a machine with no board and catches an
    agent-B refactor before a board session does.
    """
    ok = True

    def need(cond, what):
        nonlocal ok
        log("    %-58s %s" % (what, "ok" if cond else "MISSING"))
        ok = ok and bool(cond)

    import inspect
    import chat_seq as CS                                       # noqa: N806
    log("  chat_seq API the adapter depends on (%s):" % CS.__file__)
    for n in ("ChatSession", "SeqLock", "ChatSeqError", "load_tokenizer",
              "TEMPLATE_PREFIX", "T_MAX",
              # docs/INSTRUCT_SPEC.md: the ONE wrapper builder lives in
              # chat_seq and serve.py imports it, never restates it
              "ChatTemplate", "CHAT_STOP_IDS", "TOK_IM_START", "TOK_IM_END",
              "TOK_THINK", "TOK_THINK_END", "HF_REF_SINGLE",
              "HF_REF_3MSG_INCR"):
        need(hasattr(CS, n), "chat_seq.%s" % n)
    for n, sig in (("turn_ids",
                    "(self, text, system=None, first=True, carry=None)"),
                   ("render", "(self, messages, add_generation_prompt=True)"),
                   ("visible", "(self, ids)")):
        f = getattr(CS.ChatTemplate, n, None)
        got = str(inspect.signature(f)) if f else "-"
        need(f is not None and got == sig,
             "ChatTemplate.%s%s" % (n, sig if f is None else got))
    for n, sig in (("open_board", "(self)"), ("bring_up", "(self)"),
                   ("preamble", "(self)"), ("step", "(self, tok, lite)"),
                   ("plan_turn", "(self, ids, ntok)"),
                   ("attach_template", "(self, tk, log=<built-in function "
                                       "print>)"),
                   ("truncate_history", "(self, ids, ntok)")):
        f = getattr(CS.ChatSession, n, None)
        got = str(inspect.signature(f)) if f else "-"
        need(f is not None and got == sig,
             "ChatSession.%s%s" % (n, sig if f is None else got))
    for n in ("acquire", "release"):
        need(hasattr(CS.SeqLock, n), "SeqLock.%s()" % n)
    # the args namespace ChatSession reads must be fully populated
    import re
    reads = set(re.findall(r"\bargs\.([a-z_]+)", inspect.getsource(CS)))
    for meth in ("open_board", "bring_up"):
        # these alias `a = self.args` before reading it
        reads |= set(re.findall(r"\ba\.([a-z_]+)",
                                inspect.getsource(getattr(CS.ChatSession,
                                                          meth))))
    have = set(vars(BoardBackend(opts)._args()))
    missing = sorted(n for n in reads - have if not n.startswith("_"))
    need(not missing, "args namespace covers chat_seq's args.* reads"
                      + (" (missing: %s)" % ", ".join(missing) if missing
                         else ""))
    log("  backend API check: %s" % ("PASS" if ok else "FAIL"))
    return ok


def _drain(job, timeout=30.0):
    out, t0 = [], time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            item = job.events.get(timeout=timeout)
        except queue.Empty:
            break
        if item is None:
            break
        out.append(item)
    return out


# ======================================================================
def main():
    ap = argparse.ArgumentParser(
        description="localhost HTTP/SSE front end for sw/chat_seq.py "
                    "(stdlib only; the board is ONE context).")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (loopback only unless "
                         "--i-know-what-im-doing)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--i-know-what-im-doing", action="store_true",
                    dest="insecure",
                    help="permit a non-loopback bind: there is NO AUTH, so "
                         "this exposes the board to the network")
    ap.add_argument("--mock", action="store_true",
                    help="deterministic fake backend: no board, no flock, "
                         "no chat_seq import (tests)")
    ap.add_argument("--mock-step-ms", type=float, default=3.0,
                    help="--mock: wall time per simulated forward step")
    ap.add_argument("--mock-eos-after", type=int, default=0,
                    help="--mock: emit the fake EOS every N reply tokens")
    ap.add_argument("--mock-realtime", action="store_true",
                    help="--mock: sleep the real %.1f/%.1f ms per step "
                         "instead of --mock-step-ms"
                         % (MockBackend.LITE_MS, MockBackend.FULL_MS))
    ap.add_argument("--queue-cap", type=int, default=DEFAULT_QUEUE_CAP,
                    help="waiting requests before 429")
    ap.add_argument("--request-timeout", type=float,
                    default=DEFAULT_REQUEST_TIMEOUT,
                    help="s, measured from arrival (queue wait included)")
    ap.add_argument("--max-tokens-default", type=int,
                    default=DEFAULT_MAX_TOKENS)
    ap.add_argument("--max-tokens-cap", type=int, default=DEFAULT_MAX_TOKENS_CAP)
    ap.add_argument("--max-ctx", type=int, default=DEFAULT_MAX_CTX,
                    help="forward steps per context (KV bank depth is 512; "
                         "chat_seq refuses >= it)")
    ap.add_argument("--prefill", choices=("lite", "full"), default="lite",
                    help="lite = prefill steps skip the LM head (spec 3)")
    ap.add_argument("--raw", action="store_true",
                    help="serve every request WITHOUT the chat template "
                         "(docs/INSTRUCT_SPEC.md T4: the template is the "
                         "default).  A request may still opt out per turn "
                         "with {\"raw\": true}.")
    ap.add_argument("--system", default=None,
                    help="default system message for every session's first "
                         "templated turn (T5); a request may override it "
                         "with {\"system\": \"...\"}")
    ap.add_argument("--pos-mode", choices=("auto", "xrf", "ldc"),
                    default="auto")
    # ---------------------------------------------------- sampling (S5)
    g = ap.add_argument_group(
        "sampling",
        "server-wide defaults; a request may override any of them with "
        "temperature/top_k/top_p/seed.  THE DEFAULT IS GREEDY, which is "
        "100%% on-chip and bit-exact.  Sampling needs the on-chip top-k "
        "capture unit (next RTL rung); until it exists a sampled request "
        "is refused with the reason, never served greedy.")
    g.add_argument("--temp", "--temperature", dest="temp", type=float,
                   default=DEFAULT_TEMP,
                   help="default temperature (0 = greedy)")
    g.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    g.add_argument("--top-p", type=float, default=DEFAULT_TOP_P)
    g.add_argument("--seed", type=int, default=None,
                   help="default seed (one is drawn per turn if omitted)")
    g.add_argument("--topk-base", type=lambda s: int(s, 0), default=None,
                   help="AXI-Lite byte offset of the on-chip top-k CSR "
                        "block (the RTL spec owns this address)")
    g.add_argument("--verify-head", action="store_true",
                   help="cross-check every decode step against the host "
                        "head copy (verification only; +host GEMV per step)")
    g.add_argument("--head-cache", default=None)
    g.add_argument("--no-head-cache", action="store_true")
    g.add_argument("--head-mmap", action="store_true")
    g.add_argument("--head-threads", type=int, default=16)
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--chan", type=int, default=0)
    ap.add_argument("--nch", type=int, default=1, choices=(1, 4),
                    help="matvec channels the resident stream drives "
                         "(RUNG4_SPEC S4).  1 = the shipped bit-exact path; "
                         "4 = the opt-in row-split stream with the chunk-"
                         "INTERLEAVED LM head, which also selects the 4-chan "
                         "template and a different weight placement in DDR.  "
                         "A SERVER is one nch for its lifetime; a request "
                         "may assert {\"nch\": n} and gets a 400 if it "
                         "disagrees.")
    ap.add_argument("--template", default=None,
                    help="gated artifact prefix (default: chat_seq's)")
    ap.add_argument("--any-template", action="store_true")
    ap.add_argument("--force-upload", action="store_true")
    ap.add_argument("--step-timeout", type=float, default=20.0,
                    help="chat_seq per-launch device timeout")
    ap.add_argument("--preamble-timeout", type=float, default=30.0)
    ap.add_argument("--lock", default=os.path.join(SW_DIR, ".seq.lock"))
    ap.add_argument("--verbose", action="store_true",
                    help="log every HTTP request")
    ap.add_argument("--selftest", action="store_true",
                    help="unit tests, no board and no listening socket")
    ap.add_argument("--check-backend-api", action="store_true",
                    help="import chat_seq and verify every name the adapter "
                         "calls; touches NO device")
    opts = ap.parse_args()

    if opts.selftest:
        raise SystemExit(0 if selftest(opts) else 1)
    if opts.check_backend_api:
        raise SystemExit(0 if check_backend_api(opts) else 1)

    if opts.temp > 0 and opts.topk_base is None and not opts.mock:
        # S5: refuse before the flock and the bring-up.  A server-wide
        # --temp with no capture unit would fail every single request.
        ap.error("--temp %g needs the on-chip top-k capture unit (next RTL "
                 "rung).  Start greedy (the default, 100%% on-chip) or pass "
                 "--topk-base <addr> once that bitstream is loaded."
                 % opts.temp)
    if opts.host not in LOOPBACK and not opts.insecure:
        ap.error("refusing to bind %s: serve.py has NO AUTH and drives the "
                 "board.  Use 127.0.0.1 and an ssh tunnel, or pass "
                 "--i-know-what-im-doing." % opts.host)
    if opts.host not in LOOPBACK:
        print("*** WARNING: binding %s with NO AUTHENTICATION — anyone who "
              "can reach this port owns the sequencer." % opts.host)

    print("--- serve.py bring-up (%s)" % ("MOCK" if opts.mock else "board"))
    lock = None
    if not opts.mock:
        import chat_seq as CS                                   # noqa: N806
        try:
            lock = CS.SeqLock(opts.lock).acquire()
        except CS.ChatSeqError as e:
            print("*** %s" % e)
            raise SystemExit(2)
        print("  lock       held: %s (spec decision 10)" % opts.lock)
        backend = BoardBackend(opts, log=print)
    else:
        backend = MockBackend(max_ctx=opts.max_ctx, step_ms=opts.mock_step_ms,
                              eos_after=opts.mock_eos_after,
                              realtime=opts.mock_realtime, log=print,
                              raw=opts.raw, system=opts.system)

    engine = Engine(backend, opts, log=print)
    engine.start()

    try:
        httpd = Server((opts.host, opts.port), Handler)
    except OSError as e:
        engine.stop(grace=2.0)
        if lock is not None:
            lock.release()
        if e.errno == errno.EADDRINUSE:
            print("*** port %d is already in use (another serve.py?)"
                  % opts.port)
            raise SystemExit(2)
        raise
    httpd.engine = engine
    httpd.opts = opts
    httpd.verbose = opts.verbose
    print("  listening  http://%s:%d   (loopback only; no auth)"
          % (opts.host, opts.port))
    print("  endpoints  POST /v1/generate (SSE) | GET /v1/health | "
          "GET /v1/metrics | GET /v1/sessions | POST /v1/reset")

    stop_ev = threading.Event()

    def on_signal(sig, _frm):
        print("\n  signal     %s -> draining the queue and releasing the lock"
              % signal.Signals(sig).name)
        stop_ev.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    t = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2},
                         name="http", daemon=True)
    t.start()
    try:
        while not stop_ev.is_set():
            stop_ev.wait(0.5)
    finally:
        httpd.shutdown()
        httpd.server_close()
        engine.stop()
        if lock is not None:
            lock.release()
            print("  lock       released")
        print("  bye        turns=%d tokens=%d uptime=%.0fs"
              % (engine.m["turns"], engine.m["tokens"],
                 time.time() - engine.started_at))


# ======================================================================
# INTEGRATOR WISHLIST (things I would change in files I do not own)
# ----------------------------------------------------------------------
# 1. chat_seq.run_turn(): add `on_token=None` (and `on_prefill=None`)
#    callbacks and return the stats dict instead of printing them.  serve.py
#    then calls run_turn() directly and the turn schedule (feed, lite mask,
#    EOS break, P+N-1) lives in exactly one place.  Today serve.py restates
#    that loop because run_turn writes to stdout and installs a SIGINT
#    handler, which is illegal off the main thread.
# 2. chat_seq.ChatSession.set_history(fed, next_in): today serve.py calls
#    ChatSession.truncate_history unbound over a shim namespace to truncate
#    a NON-resident session's history.  A tiny setter (or making
#    truncate_history a @staticmethod taking (fed, next_in, max_ctx)) would
#    make multi-session serving first-class.
# 3. chat_seq.ChatSession could expose `device_ms` on preamble()/step()
#    directly (it already returns rep) — fine as is, noted only because
#    serve.py depends on rep["device_ms"] being present.
# 4. seq_run.Dev has no close(); a Dev.close() would let serve.py drop the
#    device fds on SIGTERM before releasing the flock.
# ======================================================================
if __name__ == "__main__":
    main()
