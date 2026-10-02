#!/usr/bin/env python3
"""r3_model_tdd.py — Task R3-3 of the R3 campaign (MOVX broadcast, form (a)):
the REFERENCE MODEL executes a broadcast, test first.  The contract is
docs/SEQ_ISA.md §B17.3 (Task R3-1); the validator's admission is R3-2's
(ref/seq_format.py: validate() admits flags[7:4] = 0xF only at
{R1,R2,R3} ⊆ caps; validate_stream() checks the per-destination running rule
in RECORD order).  What the model owes (plan Task R3-3 + the controller's
addendum and its amendment C1/C2/M1):

  * ONE scratch read, the same x written into the XWIN of channels 0..3 at
    the ONE start word (so the same bank on all four);
  * B17.2's running rule per DESTINATION: an explicit RunningChannelError
    naming the channel whose pending x range the broadcast overlaps (it
    survives `python -O`); the check runs on every destination BEFORE any
    write;
  * the unwritten-read bookkeeping records all four writes;
  * XPTR: a unicast MOVX sets its channel's XPTR to 0, a broadcast leaves all
    four unchanged (B17.3 XPTR);
  * the caps admission mirrors the validator's (MOVX_BCAST_CAPS, names from
    hwmap) — also on a direct _movx call that bypasses validate();
  * every stream without a broadcast behaves exactly as the base model.

C1 (R3-2 review): at {R1,R2,R3} today's validate() ADMITS a broadcast and
today's _movx executes it as a phantom channel 15 with no running check —
the RED cases below show exactly that.  C2: a hazard carried round a JMP
back-edge (which validate_stream's record-order walk cannot see) is the
model's to refuse.  M1: a pending range popped by its channel's waiting MVGO
(or a FENCE covering it) admits the broadcast.

WHY A NEW FILE (plan "flags, not copies"): no model-only TDD exists to take
an --r3 flag — sr4_r1_tdd.py and sr11a_r2_tdd.py are per-task mixes of
contract, validator and model checks whose content is R1's / R2's, and every
case here is new.  The plan names this file (Task R3-3, Files).  The stub
engine and the record builders follow sr11a_r2_tdd.py's.

    FABLE5_MODEL=9b /home/cah/.venv/bin/python evidence/qwen9b/sr/r3_model_tdd.py

Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.  The BASE model (a2fed67,
the tree R3-3 started from) is loaded from git, so every "unchanged" claim is
a bit-identical comparison of machine state, never a restatement.

Cases (plan Task R3-3 step 1 (a)-(f), addendum, amendment):
  (a) a broadcast then MVGOs on all four channels compute from the same x,
      bit-identical (machine state, RES, XWIN) to four unicast MOVX of the
      same source; ragged tail zero-padded on all four; bank-1 window; the
      XWIN bytes of all four channels equal; no phantom channel 15 (C1);
  (b) a no-wait MVGO pending on channel 2 reading bank 0, then a broadcast
      into bank 0 -> RunningChannelError naming mv2, raised before any
      channel's XWIN is written; each channel 0..3 in turn;
  (c) the same broadcast into bank 1 -> admitted, and the XBANK MVGO after
      the FENCE computes on the broadcast x;
  (d) overlap with channel 3's pending range ONLY (the others pending in the
      other bank) -> refused naming mv3; a pending K = 12288 stream spans
      both banks; a zero-length broadcast on a running channel is refused
      (the model's conservative _overlap, as validate_stream);
  (e) a MVGO reading words the broadcast did not write -> UnwrittenReadError
      as today; a later unicast over part of the broadcast kills only that
      channel's vector (the bookkeeping is per channel);
  (f) streams with no broadcast -> state bit-identical to the base model at
      caps {}, {R1}, {R1,R2}, {R1,R2,R3}; the unicast refusals unchanged;
  (g) XPTR: a unicast MOVX sets its channel's XPTR 0; a broadcast leaves all
      four XPTRs as they were (absent stays absent);
  (h) caps: a broadcast stream run at every caps subset below {R1,R2,R3} is
      refused by SeqValidationError before execution (the validator), and a
      DIRECT _movx of a broadcast below {R1,R2,R3} is refused too (the
      model's own mirror, names from MOVX_BCAST_CAPS); a unicast is
      unchanged at every caps subset (base comparison);
  (j) C2 — the JMP back-edge: a broadcast, then a no-wait MVGO on mv1, then
      a JMP back to the broadcast: validate_stream (record order) admits the
      stream, the model refuses the second pass naming mv1; M1 — pending on
      mv2, popped by a FENCE mask covering mv2 (R1) or mask 0, and a FENCE
      then mv2's WAITING MVGO (in the model a waiting MVGO on a pending
      channel is itself refused, one engine, so only a FENCE pops a range),
      then the broadcast is admitted; a FENCE mask skipping mv2 leaves it
      refused;
  (k) the refusal is an explicit `raise RunningChannelError` (inspect) and
      survives `python -O` (subprocess); the model's refusal verdict agrees
      with validate_stream's on every record-order case above.
"""
import hashlib
import importlib.util
import inspect
import itertools
import os
import subprocess
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for p in (os.path.join(REPO, "ref"), os.path.join(REPO, "sw")):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np                           # noqa: E402
import seq_format as SF                      # noqa: E402
import seq_model as SM                       # noqa: E402
import hwmap as HW                           # noqa: E402

BASE_COMMIT = "a2fed67"      # the tree R3-3 started from (pre-R3 model)
BCAST = 0xF                  # B17.3: MOVX flags[7:4] = 0xF
R123 = frozenset({"R1", "R2", "R3"})
R12 = frozenset({"R1", "R2"})
R1 = frozenset({"R1"})
NONE = frozenset()
ALL_CAPS = [frozenset(s) for k in range(4)
            for s in itertools.combinations(("R1", "R2", "R3"), k)]
XBANK, RBANK = 1 << 29, 1 << 30
RESULTS = []


def check(tag, name, cond, detail=""):
    RESULTS.append((tag, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] ({tag}) {name}"
          + (f"  -- {detail}" if detail else ""))


def guarded(tag, name, fn):
    try:
        cond, detail = fn()
    except Exception as e:                   # noqa: BLE001
        cond, detail = False, f"{type(e).__name__}: {str(e)[:160]}"
        traceback.print_exc(limit=3)
    check(tag, name, cond, detail)


# ======================================================================
# synthetic streams on a stub engine whose y depends on the x it is given
# (sr11a_r2_tdd.py's): a wrong x (wrong bank, stale bytes, no x) shows up
# ======================================================================
class _StubW(object):
    def matvec(self, wbase, nrows, sh, ng, g, x8, w8=False, chan=None):
        x = np.asarray(x8, dtype=np.int64)
        i = np.arange(nrows, dtype=np.int64)
        return (i % 7 - 3) * int(x.sum()) + 11 * int(chan or 0) + i

    def _lookup(self, wbase, chan=None):
        return 0, 0, {"stride": 64}, 0


def movx(c, n=128, src=0, word=0):
    return SF.Rec(SF.OP_MOVX, flags=(c << SF.CHAN_SHIFT), target=word,
                  addr_lo=src, len_or_addr_hi=n)


def bcast(n=128, src=0, word=0):
    return movx(BCAST, n=n, src=src, word=word)


def mvgo(c, nrows=4, ng=1, nowait=True, xb=0, rb=0):
    shape = HW.shape_word(nrows, 0, ng) | (XBANK if xb else 0) \
        | (RBANK if rb else 0)
    return SF.Rec(SF.OP_MVGO, flags=(c << SF.CHAN_SHIFT),
                  target=(SF.MVGO_NOWAIT if nowait else 0), imm32=shape,
                  addr_lo=HW.W_BASE & 0xFFFFFFFF,
                  len_or_addr_hi=((nrows << 8) | ((HW.W_BASE >> 32) & 0xFF)))


def movy(c, n=4, dst=20000, row=0, int16=True):
    return SF.Rec(SF.OP_MOVY, flags=(SF.MOVY_MODE_BIT if int16 else 0),
                  target=(row << 4) | c, addr_lo=dst, len_or_addr_hi=n)


def fence(mask=0):
    return SF.Rec(SF.OP_FENCE, target=mask)


def jmp(to):
    return SF.Rec(SF.OP_JMP, imm32=to)


HALT = SF.Rec(SF.OP_HALT)


def fresh_mach(mod=SM, seed=3):
    M = mod._fresh_mach()
    rng = np.random.default_rng(seed)
    M.mem[0:16384] = rng.integers(-128, 128, 16384)
    return M


def run(recs, caps=R123, mod=SM, max_steps=None):
    return mod.SeqExec(list(recs), b"", _StubW(), mach=fresh_mach(mod),
                       caps=caps).run(max_steps=max_steps)


def refused_naming(recs, chan, caps=R123, max_steps=None, must="broadcast"):
    """(ok, detail): the stream is refused by RunningChannelError whose
    message names mv<chan> (and no other channel) and says it is the
    BROADCAST that was refused (so a unicast/MVGO refusal elsewhere in the
    stream cannot pass for it)."""
    try:
        run(recs, caps, max_steps=max_steps)
        return False, "ACCEPTED"
    except SM.RunningChannelError as e:
        msg = str(e)
        others = [c for c in range(16) if c != chan and f"mv{c} " in msg]
        return (f"mv{chan}" in msg and not others
                and must.lower() in msg.lower(),
                f"RunningChannelError: {msg[:150]}")


def accepted(recs, caps=R123):
    ex = run(recs, caps)
    return ex, f"accepted; running after = {sorted(ex.running)}"


def vs_ok(recs, caps=R123):
    """validate_stream's verdict (True = admitted)."""
    try:
        SF.validate_stream(recs, caps=caps)
        return True
    except SF.SeqValidationError:
        return False


def mem_at(ex, a, n):
    return [int(v) for v in ex.M.mem[a:a + n]]


def xbytes(ex, c):
    m = ex.xwin.mem.get(c)
    return None if m is None else np.asarray(m).tobytes()


def xptr_of(ex):
    return dict(getattr(ex, "xptr", {"<no XPTR state>": None}))


# ======================================================================
def a_cases():
    print("=== (a) a broadcast then MVGOs on all four channels, {R1,R2,R3}")
    tail = [mvgo(c, nowait=False) for c in range(4)] + \
        [movy(c, dst=20000 + 16 * c) for c in range(4)] + [HALT]

    def a1():
        eb = run([bcast(n=256, src=512)] + tail)
        eu = run([movx(c, n=256, src=512) for c in range(4)] + tail)
        d = SM.diff_state(SM.snapshot(eb.M), SM.snapshot(eu.M))
        res = all(np.array_equal(eb.res.mem[c], eu.res.mem[c])
                  for c in range(4))
        xw = all(xbytes(eb, c) == xbytes(eu, c) for c in range(4))
        vec = all(eb.xwin.vec.get(c) == eu.xwin.vec.get(c) for c in range(4))
        return (not d and res and xw and vec,
                f"state diff {d or 'none'}; RES {'==' if res else '!='}; "
                f"XWIN bytes {'==' if xw else '!='}; vectors "
                f"{'==' if vec else '!='}; MOVY rows ch0..3 "
                f"{[mem_at(eb, 20000 + 16 * c, 2) for c in range(4)]}")
    guarded("a", "broadcast + 4 MVGO == 4 unicast MOVX + 4 MVGO, "
            "bit-identical (machine state, RES, XWIN, vector map)", a1)

    def a2():
        ex = run([bcast(n=130, src=40), HALT])
        want = np.zeros(SF.XWIN_WORDS * 4, dtype=np.int8)
        want[0:130] = np.asarray(ex.M.mem[40:170], dtype=np.int8)
        same = all(xbytes(ex, c) == want.tobytes() for c in range(4))
        return same, (f"x_mem of ch0..3 == scratch[40..170) + 2 zero bytes: "
                      f"{same}; vec {[ex.xwin.vec.get(c) for c in range(4)]}")
    guarded("a", "ragged tail (len 130) written and zero-padded on all four",
            a2)

    def a3():
        ex = run([bcast(n=128, src=1000, word=1536), HALT])
        ok = all(np.asarray(ex.xwin.read(c, 1536 * 4)).tobytes()
                 == np.asarray(ex.M.mem[1000:1128], dtype=np.int8).tobytes()
                 and ex.xwin.read(c, 0) is None for c in range(4))
        return ok, f"bank-1 vector on all four, bank 0 untouched: {ok}"
    guarded("a", "bank-1 broadcast (word 1536): the same window on all four",
            a3)

    def a4():
        ex = run([bcast(), HALT])
        chans = sorted(ex.xwin.mem)
        return chans == [0, 1, 2, 3], \
            f"XWIN channels written {chans} (a phantom 15 is C1's bug)"
    guarded("a", "C1: no phantom channel 15 — exactly channels 0..3 written",
            a4)

    def a5():
        ex = run([bcast(n=256, src=512)] + tail)
        return ex.stats["MOVX"] == 1, f"stats MOVX {ex.stats['MOVX']} " \
            "(one record, one mover job — B17.3 COUNTERS)"
    guarded("a", "a broadcast counts as ONE MOVX", a5)


# ======================================================================
def b_cases():
    print("=== (b) destination running in the SAME bank -> refused, "
          "naming it")
    for c in range(4):
        recs = [movx(c), mvgo(c), bcast(src=256), fence(), HALT]
        guarded("b", f"pending on mv{c} (bank 0), broadcast bank 0 -> "
                f"RunningChannelError naming mv{c}",
                lambda recs=recs, c=c: refused_naming(recs, c))

    def b_nowrite():
        # the check precedes every write: at the refusal, no channel's XWIN
        # holds the broadcast's bytes
        ex = SM.SeqExec([HALT], b"", _StubW(), mach=fresh_mach(), caps=R123)
        ex._movx(movx(2))
        ex._mvgo(mvgo(2))
        before = {c: xbytes(ex, c) for c in range(4)}
        try:
            ex._movx(bcast(src=256))
            return False, "ACCEPTED"
        except SM.RunningChannelError as e:
            after = {c: xbytes(ex, c) for c in range(4)}
            return before == after, (f"XWIN unchanged on all four at the "
                                     f"refusal: {before == after}; {e}"[:160])
    guarded("b", "the per-destination check runs before ANY write", b_nowrite)


# ======================================================================
def c_cases():
    print("=== (c) the other bank -> admitted")

    def c1():
        recs = [movx(2), mvgo(2), bcast(src=640, word=1536), fence(),
                mvgo(2, nowait=False, xb=1), movy(2, dst=8192), HALT]
        ex, det = accepted(recs)
        ref = np.clip(_StubW().matvec(0, 4, 0, 1, 128, ex.M.mem[640:768],
                                      chan=2), -32768, 32767)
        got, want = mem_at(ex, 8192, 4), [int(v) for v in ref]
        return got == want and vs_ok(recs), \
            f"{det}; XBANK MVGO rows {got}, want (broadcast x) {want}"
    guarded("c", "mv2 pending bank 0, broadcast into bank 1 -> admitted; the "
            "XBANK MVGO computes on the broadcast x", c1)

    def c2():
        recs = [movx(0), mvgo(0), movx(1), mvgo(1), movx(2), mvgo(2),
                movx(3), mvgo(3), bcast(src=64, word=1536), fence(), HALT]
        ex, det = accepted(recs)
        return vs_ok(recs), det
    guarded("c", "all four pending bank 0, broadcast bank 1 -> admitted", c2)


# ======================================================================
def d_cases():
    print("=== (d) overlap on ONE destination only")
    recs = [movx(0, word=1536), mvgo(0, xb=1), movx(1, word=1536),
            mvgo(1, xb=1), movx(2, word=1536), mvgo(2, xb=1), movx(3),
            mvgo(3), bcast(src=128), fence(), HALT]
    guarded("d", "mv0..2 pending bank 1, mv3 pending bank 0, broadcast bank "
            "0 -> refused naming mv3", lambda: refused_naming(recs, 3))
    recs2 = [movx(1, n=12288), mvgo(1, ng=96), bcast(src=0, word=1536),
             fence(), HALT]
    guarded("d", "mv1 pending K = 12288 (both banks), broadcast bank 1 -> "
            "refused naming mv1", lambda: refused_naming(recs2, 1))
    recs3 = [movx(0), mvgo(0), bcast(n=0, word=1536), fence(), HALT]
    guarded("d", "zero-length broadcast on a running channel -> refused "
            "(conservative _overlap, as validate_stream)",
            lambda: refused_naming(recs3, 0))
    recs4 = [movx(3), mvgo(3), bcast(n=4, word=32), fence(), HALT]
    guarded("d", "the word just past mv3's pending range (word 32) -> "
            "admitted", lambda: (accepted(recs4)[0] is not None, ""))
    recs5 = [movx(3), mvgo(3), bcast(n=4, word=31), fence(), HALT]
    guarded("d", "the last word inside it (word 31) -> refused naming mv3",
            lambda: refused_naming(recs5, 3))


# ======================================================================
def e_cases():
    print("=== (e) unwritten reads stay refused")

    def unwritten(recs):
        try:
            run(recs)
            return False, "ACCEPTED"
        except SM.UnwrittenReadError as e:
            return True, f"UnwrittenReadError: {str(e)[:110]}"
    guarded("e", "broadcast bank 0, then an XBANK MVGO on mv1 (bank 1 never "
            "written) -> UnwrittenReadError",
            lambda: unwritten([bcast(), mvgo(1, nowait=False, xb=1), HALT]))

    def e2():
        # a unicast over part of the broadcast on mv0 kills ONLY mv0's
        # vector at word 0; mv1..3 still read the broadcast
        ex = run([bcast(n=256), movx(0, n=4, src=900, word=16),
                  mvgo(1, nowait=False, ng=2), mvgo(2, nowait=False, ng=2),
                  mvgo(3, nowait=False, ng=2), HALT])
        ok13 = all(ex.xwin.read(c, 0) is not None for c in (1, 2, 3))
        try:
            ex._mvgo(mvgo(0, nowait=False, ng=2))
            return False, "mv0 read a vector a later MOVX overwrote"
        except SM.UnwrittenReadError:
            return ok13, f"mv1..3 intact: {ok13}; mv0 refused"
    guarded("e", "the bookkeeping is per channel: a later unicast on mv0 "
            "kills only mv0's broadcast vector", e2)


# ======================================================================
def _base_model():
    src = subprocess.run(["git", "-C", REPO, "show",
                          f"{BASE_COMMIT}:ref/seq_model.py"],
                         check=True, capture_output=True).stdout
    d = tempfile.mkdtemp(prefix="r3_3_base_")
    path = os.path.join(d, "seq_model_base.py")
    with open(path, "wb") as f:
        f.write(src)
    spec = importlib.util.spec_from_file_location("seq_model_base", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, hashlib.sha256(src).hexdigest()


def _state(ex):
    return (sorted(ex.running), dict(ex.stats), SM.snapshot(ex.M),
            {c: np.asarray(v).tolist() for c, v in sorted(ex.xwin.items())},
            {c: np.asarray(v).tolist() for c, v in sorted(ex.res.items())},
            {c: np.asarray(m).tobytes() for c, m in sorted(ex.xwin.mem.items())},
            {c: dict(v) for c, v in sorted(ex.xwin.vec.items())},
            {c: list(v) for c, v in sorted(ex.res.seg.items())})


def _outcome(mod, recs, caps):
    try:
        ex = mod.SeqExec(list(recs), b"", _StubW(), mach=fresh_mach(mod),
                         caps=caps).run()
        return "ok", _state(ex)
    except Exception as e:                    # noqa: BLE001
        return f"{type(e).__name__}: {e}", None


def f_cases(base):
    print("=== (f) streams with NO broadcast == the base model "
          f"({BASE_COMMIT})")
    streams = {
        "mixed_r2": [movx(0, n=256), mvgo(0, nrows=8, ng=2, nowait=False),
                     movy(0, n=8, dst=20000), movx(1, n=128, src=300),
                     mvgo(1, nrows=5), movx(2, n=384, src=700),
                     mvgo(2, nrows=6, ng=3), movx(2, word=1536, src=64),
                     fence(), movy(1, n=5, dst=20100),
                     movy(2, n=3, dst=20200), mvgo(2, xb=1, rb=1,
                                                   nowait=False),
                     movy(2, n=4, row=2048, dst=20250),
                     movx(3, n=12288, src=1000), mvgo(3, nrows=7, ng=96),
                     fence(), movy(3, n=7, dst=20400), HALT],
        "plain": [movx(0), mvgo(0, nowait=False), movy(0), movx(1, src=77),
                  mvgo(1), fence(), movy(1, dst=20500), HALT],
        "masked_fence": [movx(0), mvgo(0), movx(1), mvgo(1), fence(0b0001),
                         movx(0, src=5), mvgo(0, nowait=False), fence(),
                         movy(1), HALT],
        "movx_on_running": [movx(0), mvgo(0), movx(0, src=64), fence(), HALT],
        "mvgo_on_running": [movx(0), mvgo(0), mvgo(0), fence(), HALT],
        "movy_on_running": [movx(0), mvgo(0), movy(0), fence(), HALT],
        "unwritten": [mvgo(1, nowait=False), HALT],
        "bank1_over_pending": [movx(0, word=1536), mvgo(0, xb=1),
                               movx(0, word=1536, src=512), fence(), HALT],
    }
    for name, recs in streams.items():
        for caps in ALL_CAPS:
            def z(recs=recs, caps=caps, name=name):
                a = _outcome(base, recs, caps)
                b = _outcome(SM, recs, caps)
                if a[0] != b[0]:
                    return False, f"base {a[0][:70]} vs new {b[0][:70]}"
                if a[1] is None:
                    return True, f"both {a[0][:70]}"
                d = SM.diff_state(a[1][2], b[1][2])
                same = not d and all(a[1][k] == b[1][k]
                                     for k in (0, 1, 3, 4, 5, 6, 7))
                return same, f"ran; state diff {d or 'none'}; " \
                    f"all views {'==' if same else '!='}"
            guarded("f", f"{name} at {sorted(caps) or '{}'}", z)
    # the refusal matrix must not be vacuous: the legal streams RUN at some
    # caps set, the hazards are refused at every one
    legal = [n for n in ("plain", "mixed_r2", "masked_fence")
             if _outcome(SM, streams[n], R123)[0] == "ok"]
    check("f", "the legal no-broadcast streams RUN at {R1,R2,R3} (the "
          "comparison is not vacuous)", len(legal) == 3, f"ran: {legal}")


# ======================================================================
def g_cases():
    print("=== (g) XPTR (B17.3): unicast writes 0, broadcast leaves all four")

    def g1():
        ex = run([movx(1), movx(3, word=1536), HALT])
        return xptr_of(ex) == {1: 0, 3: 0}, f"XPTR {xptr_of(ex)}"
    guarded("g", "a unicast MOVX sets its channel's XPTR to 0 "
            "(rtl/seq_movers.sv X_XPTR)", g1)

    def g2():
        ex = run([bcast(), bcast(word=1536, src=64), HALT])
        return xptr_of(ex) == {}, f"XPTR {xptr_of(ex)}"
    guarded("g", "a broadcast leaves all four XPTRs unchanged (none set)", g2)

    def g3():
        ex = run([movx(2), bcast(src=64, word=1536), HALT])
        return xptr_of(ex) == {2: 0}, f"XPTR {xptr_of(ex)}"
    guarded("g", "a broadcast after a unicast: only the unicast's XPTR set",
            g3)


# ======================================================================
def h_cases(base):
    print("=== (h) caps: the model's admission mirrors the validator's")
    recs = [bcast(), mvgo(0, nowait=False), HALT]
    for caps in ALL_CAPS:
        if caps == R123:
            continue
        def h1(caps=caps):
            try:
                run(recs, caps)
                return False, "EXECUTED"
            except SF.SeqValidationError as e:
                miss = sorted(R123 - caps)
                named = all(m in str(e) for m in miss)
                return named, f"SeqValidationError naming {miss}: {named}"
        guarded("h", f"broadcast stream at {sorted(caps) or '{}'} -> refused "
                "before execution", h1)

        def h2(caps=caps):
            ex = SM.SeqExec([HALT], b"", _StubW(), mach=fresh_mach(),
                            caps=caps)
            try:
                ex._movx(bcast())
                return False, (f"direct _movx EXECUTED a broadcast; XWIN "
                               f"channels {sorted(ex.xwin.mem)}")
            except SF.SeqValidationError as e:
                miss = sorted(R123 - caps)
                return all(m in str(e) for m in miss), \
                    f"SeqValidationError naming {miss}: {str(e)[:110]}"
        guarded("h", f"direct _movx of a broadcast at "
                f"{sorted(caps) or '{}'} -> refused by the model itself", h2)

    def h3():
        return set(SF.MOVX_BCAST_CAPS) == set(R123) and \
            HW.seq_caps_check(SF.MOVX_BCAST_CAPS) == R123, \
            f"MOVX_BCAST_CAPS {sorted(SF.MOVX_BCAST_CAPS)}"
    guarded("h", "the admission set is the validator's MOVX_BCAST_CAPS "
            "(names checked by hwmap)", h3)

    def h4():
        src = open(os.path.join(REPO, "ref", "seq_model.py")).read()
        bad = [w for w in ("0xFAB1CA07", "0xfab1ca07", "0xFAB1CA", "0xfab1ca")
               if w in src]
        return not bad, f"SEQ_CAPS literals in ref/seq_model.py: {bad or 'none'}"
    guarded("h", "ref/seq_model.py types no SEQ_CAPS literal", h4)

    for c in range(4):
        def h5(c=c):
            recs = [movx(c, n=200, src=31 * c), mvgo(c, nowait=False, ng=2),
                    movy(c, dst=20000), HALT]
            diffs = []
            for caps in ALL_CAPS:
                a = _outcome(base, recs, caps)
                b = _outcome(SM, recs, caps)
                if a[0] != b[0] or (a[1] is not None and (
                        SM.diff_state(a[1][2], b[1][2])
                        or any(a[1][k] != b[1][k] for k in (0, 1, 3, 4, 5)))):
                    diffs.append(sorted(caps))
            return not diffs, f"differs at {diffs or 'no caps set'}"
        guarded("h", f"unicast MOVX on mv{c} == base at every caps subset",
                h5)


# ======================================================================
def j_cases():
    print("=== (j) C2 the JMP back-edge; M1 the pop path")
    # the MVGO on mv1 reads the broadcast's own x, so the loop body has no
    # unicast MOVX that could raise first
    loop = [bcast(src=64), mvgo(1), jmp(0), HALT]

    def j1():
        vs = vs_ok(loop)
        ok, det = refused_naming(loop, 1, max_steps=50)
        return vs and ok, (f"validate_stream (record order) admits: {vs}; "
                           f"model: {det}")
    guarded("j", "C2: broadcast; mv1 no-wait; JMP back -> the second pass "
            "refused naming mv1", j1)

    loop_ok = [movx(1), bcast(src=64, word=1536), fence(), mvgo(1),
               jmp(1), HALT]
    guarded("j", "C2 control: mv1 pending in bank 0 round the back-edge, "
            "the broadcast into bank 1 -> not refused (stops only at "
            "max_steps)", lambda: _runs_to_max(loop_ok))

    # M1.  In the MODEL a waiting MVGO on a channel with a pending stream is
    # itself refused (one engine), so a pending range is popped only by a
    # FENCE covering it; the waiting MVGO's pop (the `running.pop` branch)
    # is exercised after that FENCE and leaves nothing pending.
    popped_wait = [movx(2), mvgo(2), fence(0b0100), movx(2, src=9),
                   mvgo(2, nowait=False), bcast(src=64), HALT]
    popped_wait2 = [movx(2), mvgo(2, nowait=False), bcast(src=64), HALT]
    popped_fence = [movx(2), mvgo(2), fence(0b0100), bcast(src=64), HALT]
    popped_fence0 = [movx(2), mvgo(2), fence(), bcast(src=64), HALT]
    skipped = [movx(2), mvgo(2), fence(0b1011), bcast(src=64), fence(), HALT]
    for name, recs in (("M1: mv2 pending, FENCE 0b0100, then its WAITING "
                        "MVGO", popped_wait),
                       ("M1: a waiting MVGO leaves nothing pending",
                        popped_wait2),
                       ("M1: mv2's range popped by FENCE mask 0b0100 (R1)",
                        popped_fence),
                       ("M1: mv2's range popped by FENCE mask 0 (all)",
                        popped_fence0)):
        def m(recs=recs):
            ex, det = accepted(recs)
            ok = all(xbytes(ex, c) is not None for c in range(4)) \
                and vs_ok(recs)
            return ok, det
        guarded("j", f"{name} -> broadcast admitted", m)
    guarded("j", "M1 control: FENCE mask 0b1011 skips mv2 -> broadcast "
            "refused naming mv2", lambda: refused_naming(skipped, 2))


def _runs_to_max(recs):
    try:
        run(recs, max_steps=40)
        return False, "halted?"
    except SM.RunningChannelError as e:
        return False, f"RunningChannelError: {e}"[:150]
    except RuntimeError as e:
        return "ran past" in str(e), f"RuntimeError: {e}"[:100]


# ======================================================================
def k_cases():
    print("=== (k) explicit raise; python -O; agreement with validate_stream")

    def k1():
        fn = getattr(SM, "_movx_bcast", None)
        if fn is None:
            return False, "no seq_model._movx_bcast"
        s = inspect.getsource(fn)
        return "raise RunningChannelError" in s, \
            "explicit raise in _movx_bcast"
    guarded("k", "the per-destination refusal is an explicit raise", k1)

    def k2():
        code = (
            "import sys; sys.path[:0] = [%r, %r]\n"
            "import seq_format as SF, seq_model as SM, hwmap as HW\n"
            "assert False, 'asserts are ON'\n") % (
                os.path.join(REPO, "ref"), os.path.join(REPO, "sw"))
        probe = subprocess.run([sys.executable, "-O", "-c", code],
                               capture_output=True, text=True)
        if probe.returncode != 0:
            return False, f"-O probe failed: {probe.stderr[-200:]}"
        prog = (
            "import sys; sys.path[:0] = [%r, %r, %r]\n"
            "import r3_model_tdd as T, seq_model as SM\n"
            "ok, det = T.refused_naming([T.movx(2), T.mvgo(2), "
            "T.bcast(src=256), T.fence(), T.HALT], 2)\n"
            "print(det); raise SystemExit(0 if ok else 1)\n") % (
                HERE, os.path.join(REPO, "ref"), os.path.join(REPO, "sw"))
        r = subprocess.run([sys.executable, "-O", "-c", prog],
                           capture_output=True, text=True)
        return r.returncode == 0, (r.stdout.strip() or r.stderr[-200:])[:150]
    guarded("k", "under python -O the broadcast over pending mv2 is still "
            "refused naming mv2", k2)

    def k3():
        cases = {
            "b": [movx(2), mvgo(2), bcast(src=256), fence(), HALT],
            "c": [movx(2), mvgo(2), bcast(src=640, word=1536), fence(), HALT],
            "d": [movx(3), mvgo(3), movx(0, word=1536), mvgo(0, xb=1),
                  bcast(src=128), fence(), HALT],
            "m1": [movx(2), mvgo(2), fence(0b0100), bcast(src=64), HALT],
            "skip": [movx(2), mvgo(2), fence(0b1011), bcast(src=64), fence(),
                     HALT],
            "k12288": [movx(1, n=12288), mvgo(1, ng=96),
                       bcast(word=1536), fence(), HALT],
        }
        dis = []
        for n, recs in cases.items():
            try:
                run(recs)
                mod_ok = True
            except SM.RunningChannelError:
                mod_ok = False
            if mod_ok != vs_ok(recs):
                dis.append(n)
        return not dis, f"model vs validate_stream disagree on {dis or 'none'}"
    guarded("k", "model verdict == validate_stream verdict on every "
            "record-order case", k3)


def main():
    print(f"=== r3_model_tdd.py  FABLE5_MODEL={os.environ.get('FABLE5_MODEL')}")
    base, sha = None, None
    try:
        base, sha = _base_model()
        print(f"  base model {BASE_COMMIT}:ref/seq_model.py sha256 {sha}")
    except Exception as e:                    # noqa: BLE001
        check("base", "load the base model", False, str(e))
    cur = hashlib.sha256(open(os.path.join(REPO, "ref", "seq_model.py"),
                              "rb").read()).hexdigest()
    print(f"  tree model ref/seq_model.py sha256 {cur}")
    for fn, args in ((a_cases, ()), (b_cases, ()), (c_cases, ()),
                     (d_cases, ()), (e_cases, ()), (f_cases, (base,)),
                     (g_cases, ()), (h_cases, (base,)), (j_cases, ()),
                     (k_cases, ())):
        try:
            fn(*args)
        except Exception as e:               # noqa: BLE001
            check(fn.__name__[0], f"{fn.__name__} section aborted", False,
                  f"{type(e).__name__}: {e}")
            traceback.print_exc(limit=4)
    by = {}
    for tag, ok in RESULTS:
        by.setdefault(tag, []).append(ok)
    print("=== per case: " + "  ".join(
        f"({t}) {sum(v)}/{len(v)}" for t, v in sorted(by.items())))
    failed = sorted(t for t, v in by.items() if not all(v))
    npass = sum(ok for _t, ok in RESULTS)
    print(f"=== {npass} passed, {len(RESULTS) - npass} failed; failing cases: "
          f"{failed or 'none'}")
    print("R3-3 MODEL TDD: " + ("PASS" if not failed else "FAIL"))
    raise SystemExit(0 if not failed else 1)


if __name__ == "__main__":
    main()
