#!/usr/bin/env python3
"""sr11a_r2_tdd.py — Task SR11a (sequencer RTL round): R2's CONTRACT, the
validator's device-keyed admission and the reference model's RUNNING RANGES,
test first.  R2 = the XWIN / RES bank bits (docs/SEQ_ISA.md v2.3 §B17.2;
spec docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md §1.2):

  MOVX target[11:0]   XWIN start WORD 0..3071 (bank 1 = word 1536)
  MVGO SHAPE bit 29   XBANK: x read from x_mem line 48 (legal only K <= 6144)
  MVGO SHAPE bit 30   RBANK: rows written at 2048 + r (legal only nrows <= 2048)
  MOVY target[15:4]   RES start row (12 bits)
  range rules         start word + words <= 3072; start row + rows <= 4096

R2 is NOT fail-closed on build_041/042 (they ignore MOVX target and drop
SHAPE[31:29]), so admission is by the DEVICE's caps: every R2 field is
refused unless "R2" is in the caps the validator is called at.

    FABLE5_MODEL=9b /home/cah/.venv/bin/python evidence/qwen9b/sr/sr11a_r2_tdd.py

Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.  Cases (plan Task SR11a
step 1, spec §4.1 rung 2's synthetic hazards):
  (a) running ranges in the model at caps {R1,R2}: a bank-1 MOVX over a
      pending bank-1 read -> RunningChannelError; a bank-1 MOVX while a
      bank-0 stream runs -> admitted, and the next XBANK MVGO computes on
      the bank-1 x; a mlp_down-sized (K = 12288) pending stream spans both
      banks, so a bank-1 MOVX is refused; MVGO on a channel with ANY pending
      stream is refused (one engine);
  (b) MOVY over the pending RES range -> refused (whole and partial
      overlap); MOVY on the other half -> admitted and reads the earlier
      stream's rows;
  (c) the validator at {R1,R2}: XBANK with K = 12288 refused, K = 6144
      admitted; RBANK with nrows 2049 refused, 2048 admitted; the MOVX and
      MOVY range rules at their edges; SHAPE bit 31 refused under every caps;
  (d) caps-keyed refusal: each R2 record (XBANK MVGO, RBANK MVGO, MOVX start
      word 1536, MOVY start row 2048) is REFUSED at caps {R1} and at empty
      caps, with and without shape_isa stated; admitted at {R1,R2}; the
      model run at caps {R1} refuses an R2 stream by SeqValidationError;
      a frozen isa=1 W8 word (bit 29 = w8) still validates when the caller
      states shape_isa=1;
  (e) with every bank bit and start word zero the model is exactly
      today's: the same synthetic stream on the model at the base commit
      e3c2ff1 (loaded from git) and on this tree, at caps {} and {R1,R2},
      gives bit-identical machine state, stats, running set, XWIN and RES
      views, and the same refusals;
  (f) the model's SHAPE-spare assert admits bits 29/30 only under R2 (a
      direct _mvgo call, bypassing the validator), bit 31 never;
  (g) the refusals are explicit `raise RunningChannelError` (survive -O),
      and the model's own refusal selftest carries r2_ cases and passes;
  (h) docs/SEQ_ISA.md §B17.2 states the encoding, the two range rules, the
      bank-legality rule, err 0x06 and "NOT fail-closed";
  (i) the shipped s1 stream validates unchanged (every record) at {},
      {R1} and {R1,R2}.
"""
import hashlib
import importlib.util
import inspect
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

BASE_COMMIT = "e3c2ff1"      # the tree SR11a started from (pre-R2 model)
R12 = frozenset({"R1", "R2"})
R1 = frozenset({"R1"})
NONE = frozenset()
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
        cond, detail = False, f"{type(e).__name__}: {e}"
        traceback.print_exc(limit=3)
    check(tag, name, cond, detail)


# ======================================================================
# synthetic streams on a stub engine whose y depends on the x it is given
# ======================================================================
class _StubW(object):
    """y[i] = sum(x8 * ((i % 7) - 3)) + 11*chan + i — so a wrong x (wrong
    bank, stale bytes) shows up in the RES rows."""
    def matvec(self, wbase, nrows, sh, ng, g, x8, w8=False, chan=None):
        x = np.asarray(x8, dtype=np.int64)
        i = np.arange(nrows, dtype=np.int64)
        return (i % 7 - 3) * int(x.sum()) + 11 * int(chan or 0) + i

    def _lookup(self, wbase, chan=None):
        return 0, 0, {"stride": 64}, 0


def movx(c, n=128, src=0, word=0):
    return SF.Rec(SF.OP_MOVX, flags=(c << SF.CHAN_SHIFT), target=word,
                  addr_lo=src, len_or_addr_hi=n)


def mvgo(c, nrows=4, ng=1, nowait=True, xb=0, rb=0, bit31=0):
    shape = HW.shape_word(nrows, 0, ng) | (XBANK if xb else 0) \
        | (RBANK if rb else 0) | (bit31 << 31)
    return SF.Rec(SF.OP_MVGO, flags=(c << SF.CHAN_SHIFT),
                  target=(SF.MVGO_NOWAIT if nowait else 0), imm32=shape,
                  addr_lo=HW.W_BASE & 0xFFFFFFFF,
                  len_or_addr_hi=((nrows << 8) | ((HW.W_BASE >> 32) & 0xFF)))


def movy(c, n=4, dst=20000, row=0, int16=False):
    return SF.Rec(SF.OP_MOVY, flags=(SF.MOVY_MODE_BIT if int16 else 0),
                  target=(row << 4) | c, addr_lo=dst, len_or_addr_hi=n)


def fence(mask=0):
    return SF.Rec(SF.OP_FENCE, target=mask)


HALT = SF.Rec(SF.OP_HALT)


def fresh_mach(mod=SM, seed=3):
    M = mod._fresh_mach()
    rng = np.random.default_rng(seed)
    M.mem[0:16384] = rng.integers(-128, 128, 16384)
    return M


def run(recs, caps, mod=SM):
    return mod.SeqExec(list(recs), b"", _StubW(), mach=fresh_mach(mod),
                       caps=caps).run()


def refused(recs, caps=R12):
    try:
        run(recs, caps)
        return False, "ACCEPTED"
    except SM.RunningChannelError as e:
        return True, f"RunningChannelError: {str(e)[:110]}"


def accepted(recs, caps=R12):
    ex = run(recs, caps)
    return True, f"accepted; running after = {sorted(ex.running)}"


def mem_at(ex, a, n):
    return [int(v) for v in ex.M.mem[a:a + n]]


# ======================================================================
def model_cases():
    print("=== (a)/(b) running ranges in the model, caps {R1,R2}")
    # (a) x ranges
    guarded("a", "bank-1 MOVX over a PENDING bank-1 read -> refused",
            lambda: refused([movx(0, word=1536), mvgo(0, xb=1),
                             movx(0, word=1536, src=512), fence(), HALT]))
    guarded("a", "partial overlap: MOVX word 1520..1551 over pending bank 1 "
            "-> refused",
            lambda: refused([movx(0, word=1536), mvgo(0, xb=1),
                             movx(0, word=1520, src=512), fence(), HALT]))

    def a_ok():
        # bank-0 stream runs; x for the next stream lands in bank 1; the
        # XBANK MVGO after the FENCE must compute on THAT x
        recs = [movx(0, src=0), mvgo(0, xb=0), movx(0, word=1536, src=640),
                fence(), mvgo(0, nowait=False, xb=1, rb=1),
                movy(0, row=2048, dst=8192, int16=True), HALT]
        ex = run(recs, R12)
        ref = _StubW().matvec(0, 4, 0, 1, 128, ex.M.mem[640:768], chan=0)
        got = mem_at(ex, 8192, 4)
        want = [int(v) for v in np.clip(ref, -32768, 32767)]
        return got == want, f"MOVY row 2048.. = {got}, want (bank-1 x) {want}"
    guarded("a", "bank-1 MOVX while a bank-0 stream runs -> admitted; the "
            "XBANK MVGO computes on the bank-1 x", a_ok)
    guarded("a", "K = 12288 (ng 96, both banks) pending: bank-1 MOVX -> "
            "refused",
            lambda: refused([movx(0, n=12288), mvgo(0, ng=96),
                             movx(0, word=1536, src=512), fence(), HALT]))
    guarded("a", "MVGO on a channel with a pending stream in the OTHER banks "
            "-> refused (one engine)",
            lambda: refused([movx(0), mvgo(0), movx(0, word=1536),
                             mvgo(0, xb=1, rb=1), fence(), HALT]))
    guarded("a", "other channel unaffected: MOVX/MVGO ch1 while ch0 pending "
            "-> admitted",
            lambda: accepted([movx(0), mvgo(0), movx(1), mvgo(1), fence(),
                              HALT]))

    # (b) RES ranges
    guarded("b", "MOVY over the pending RES range (row 2048) -> refused",
            lambda: refused([movx(0), mvgo(0, rb=1), movy(0, row=2048),
                             fence(), HALT]))
    guarded("b", "partial: MOVY rows 2046..2049 over pending 2048.. -> "
            "refused",
            lambda: refused([movx(0), mvgo(0, rb=1), movy(0, row=2046),
                             fence(), HALT]))
    guarded("b", "MOVY row 0 over a pending RBANK=0 stream -> refused",
            lambda: refused([movx(0), mvgo(0), movy(0), fence(), HALT]))

    def b_ok():
        # stream A (wait) -> rows 0..3; stream B (no-wait, RBANK) -> rows
        # 2048..; MOVY of A's rows while B runs is legal and reads A's y
        recs = [movx(0, src=0), mvgo(0, nowait=False),
                movx(0, word=1536, src=1024), mvgo(0, xb=1, rb=1),
                movy(0, row=0, dst=9000, int16=True), fence(),
                movy(0, row=2048, dst=9100, int16=True), HALT]
        ex = run(recs, R12)
        ya = np.clip(_StubW().matvec(0, 4, 0, 1, 128, ex.M.mem[0:128], chan=0),
                     -32768, 32767)
        yb = np.clip(_StubW().matvec(0, 4, 0, 1, 128, ex.M.mem[1024:1152],
                                     chan=0), -32768, 32767)
        ga, gb = mem_at(ex, 9000, 4), mem_at(ex, 9100, 4)
        ok = ga == [int(v) for v in ya] and gb == [int(v) for v in yb]
        return ok, f"bank0 {ga} (want {list(map(int, ya))}), bank1 {gb} " \
                   f"(want {list(map(int, yb))})"
    guarded("b", "MOVY on the other half while the RBANK stream runs -> "
            "admitted, reads the earlier stream's rows", b_ok)

    def b_stale():
        # a MOVY must lie inside ONE live MVGO segment: rows never written
        # (bank 1 before any RBANK MVGO) are refused, as today's
        # "reads N rows, only M valid"
        try:
            run([movx(0), mvgo(0, nowait=False), movy(0, row=2048), HALT], R12)
            return False, "ACCEPTED a MOVY of never-written rows"
        except SM.RunningChannelError as e:
            return False, f"wrong refusal: {e}"
        except AssertionError as e:
            # fix round 1 (M1): an explicit UnwrittenReadError, not a bare
            # assert (survives python -O)
            ok = type(e).__name__ == "UnwrittenReadError"
            return ok, f"{type(e).__name__}: {str(e)[:100]}"
    guarded("b", "MOVY of never-written RES rows -> refused "
            "(UnwrittenReadError)", b_stale)


# ======================================================================
def validator_cases():
    print("=== (c) the validator at caps {R1,R2}: ranges and bank legality")

    def ok_at(r, caps=R12, **kw):
        try:
            SF.validate(r, caps=caps, **kw)
            return True
        except SF.SeqValidationError:
            return False

    rows = [
        ("XBANK K=12288 (ng 96) refused", mvgo(0, ng=96, xb=1), False),
        ("XBANK K=6144 (ng 48) admitted", mvgo(0, ng=48, xb=1), True),
        ("XBANK ng 49 refused", mvgo(0, ng=49, xb=1), False),
        ("RBANK nrows 2049 refused", mvgo(0, nrows=2049, rb=1), False),
        ("RBANK nrows 2048 admitted", mvgo(0, nrows=2048, rb=1), True),
        ("no bank, nrows 4096 admitted", mvgo(0, nrows=4096), True),
        ("SHAPE bit 31 refused", mvgo(0, bit31=1), False),
        ("MOVX word 1536 + 1536 words admitted",
         movx(0, n=6144, word=1536), True),
        ("MOVX word 1537 + 1536 words refused",
         movx(0, n=6144, word=1537), False),
        ("MOVX word 3071 + 1 word (len 4) admitted",
         movx(0, n=4, word=3071), True),
        ("MOVX word 3071 + ceil(5/4)=2 words refused (ragged tail counts)",
         movx(0, n=5, word=3071), False),
        ("MOVX word 0 + 3072 words (K 12288) admitted", movx(0, n=12288), True),
        ("MOVX word 3072 len 0 refused (start > 3071)",
         movx(0, n=0, word=3072), False),
        ("MOVX target[15:12] set refused", movx(0, word=0x1000), False),
        ("MOVY row 2048 + 2048 rows admitted", movy(0, n=2048, row=2048), True),
        ("MOVY row 2049 + 2048 rows refused", movy(0, n=2048, row=2049), False),
        ("MOVY row 4095 + 1 row admitted", movy(0, n=1, row=4095), True),
        ("MOVY row 0 + 4097 rows refused", movy(0, n=4097), False),
    ]
    for name, r, want in rows:
        guarded("c", name, lambda r=r, want=want: (
            ok_at(r) == want and ok_at(r, shape_isa=SF.SHAPE_ISA_9B) == want,
            f"admitted={ok_at(r)}"))
    guarded("c", "SHAPE bit 31 refused at empty caps too",
            lambda: (not ok_at(mvgo(0, bit31=1), NONE), ""))

    print("=== (d) caps-keyed refusal (device caps, never the manifest)")
    r2recs = [("XBANK MVGO", mvgo(0, ng=48, xb=1)),
              ("RBANK MVGO", mvgo(0, nrows=16, rb=1)),
              ("MOVX start word 1536", movx(0, word=1536)),
              ("MOVY start row 2048", movy(0, row=2048))]
    for name, r in r2recs:
        guarded("d", f"{name}: refused at {{R1}} and at {{}}, admitted at "
                "{R1,R2} and {R2}", lambda r=r: (
                    not ok_at(r, R1) and not ok_at(r, NONE)
                    and not ok_at(r, R1, shape_isa=SF.SHAPE_ISA_9B)
                    and not ok_at(r, NONE, shape_isa=SF.SHAPE_ISA_9B)
                    and ok_at(r, R12) and ok_at(r, frozenset({"R2"})),
                    f"{{}}:{ok_at(r, NONE)} {{R1}}:{ok_at(r, R1)} "
                    f"{{R1,R2}}:{ok_at(r, R12)}"))

    def d_stream():
        recs = [movx(0, word=1536), mvgo(0, nowait=False, xb=1), HALT]
        out = []
        for caps in (NONE, R1):
            try:
                SF.validate_stream(recs, caps=caps)
                out.append(False)
            except SF.SeqValidationError:
                out.append(True)
        SF.validate_stream(recs, caps=R12)
        return all(out), f"validate_stream refused at {{}}, {{R1}}: {out}; " \
                         "admitted at {R1,R2}"
    guarded("d", "validate_stream of an R2 stream keyed by caps", d_stream)

    def d_model():
        try:
            run([movx(0, word=1536), mvgo(0, nowait=False, xb=1), HALT], R1)
            return False, "the model EXECUTED an R2 stream at caps {R1}"
        except SF.SeqValidationError as e:
            return True, f"SeqValidationError: {str(e)[:90]}"
    guarded("d", "the model at caps {R1} refuses an R2 stream before "
            "executing it", d_model)

    def d_isa1():
        w = HW.shape_word(2048, 10, 16, g=128, w8=True,
                          isa=HW.SHAPE_ISA_PRE_G3)
        r = SF.Rec(SF.OP_MVGO, 0, 0, w, 0, 0)
        ok1 = ok_at(r, NONE, shape_isa=HW.SHAPE_ISA_PRE_G3)
        return ok1 and bool(w & XBANK), \
            f"isa=1 W8 word {w:#010x} admitted at shape_isa=1: {ok1}"
    guarded("d", "a frozen isa=1 W8 word (bit 29 = w8) still validates when "
            "shape_isa=1 is stated", d_isa1)


# ======================================================================
def _base_model():
    """ref/seq_model.py at BASE_COMMIT, loaded as its own module."""
    src = subprocess.run(["git", "-C", REPO, "show",
                          f"{BASE_COMMIT}:ref/seq_model.py"],
                         check=True, capture_output=True).stdout
    d = tempfile.mkdtemp(prefix="sr11a_base_")
    path = os.path.join(d, "seq_model_base.py")
    with open(path, "wb") as f:
        f.write(src)
    spec = importlib.util.spec_from_file_location("seq_model_base", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, hashlib.sha256(src).hexdigest()[:16]


def _state(ex):
    return (sorted(ex.running), dict(ex.stats), SM.snapshot(ex.M),
            {c: np.asarray(v).tolist() for c, v in sorted(ex.xwin.items())},
            {c: np.asarray(v).tolist() for c, v in sorted(ex.res.items())})


def _outcome(mod, recs, caps):
    try:
        ex = mod.SeqExec(list(recs), b"", _StubW(), mach=fresh_mach(mod),
                         caps=caps).run()
        return "ok", _state(ex)
    except AssertionError as e:          # RunningChannelError included
        # fix round 1 (M1): the new model raises UnwrittenReadError where
        # the base model had a bare assert for the same stream — the same
        # refusal, so it compares as "AssertionError"
        name = type(e).__name__
        return ("AssertionError" if name == "UnwrittenReadError" else name,
                None)


def zero_bank_cases():
    print("=== (e) zero banks == today's model (base commit "
          f"{BASE_COMMIT})")
    base, sha = _base_model()
    print(f"  base model sha256 {sha}")
    streams = {
        "mixed": [movx(0, n=256), mvgo(0, nrows=8, ng=2, nowait=False),
                  movy(0, n=8, dst=20000), movx(1, n=128, src=300),
                  mvgo(1, nrows=5), movx(2, n=384, src=700),
                  mvgo(2, nrows=6, ng=3), fence(),
                  movy(1, n=5, dst=20100), movy(2, n=3, dst=20200, int16=True),
                  movx(0, n=128, src=900), mvgo(0, nrows=4, nowait=False),
                  movy(0, n=4, dst=20300), movx(3, n=12288, src=1000),
                  mvgo(3, nrows=7, ng=96), fence(0b1000),
                  movy(3, n=7, dst=20400), HALT],
        "movx_on_running": [movx(0), mvgo(0), movx(0, src=64), fence(), HALT],
        "movy_on_running": [movx(0), mvgo(0), movy(0), fence(), HALT],
        "mvgo_on_running": [movx(0), mvgo(0), mvgo(0), fence(), HALT],
        "movy_past_rows": [movx(0), mvgo(0, nrows=8, nowait=False),
                           movx(0, src=64), mvgo(0, nrows=4, nowait=False),
                           movy(0, n=8), HALT],
        "short_x_reuse": [movx(0, n=256), movx(0, n=128, src=64),
                          mvgo(0, nowait=False), movy(0), HALT],
    }
    for name, recs in streams.items():
        for caps in (NONE, R12) if name != "mixed" else (R1, R12):
            bcaps = caps & R1       # the base model knows no R2
            def z(recs=recs, caps=caps, bcaps=bcaps):
                a = _outcome(base, recs, bcaps)
                b = _outcome(SM, recs, caps)
                if a[0] != b[0]:
                    return False, f"base {a[0]} vs new {b[0]}"
                if name in ("mixed", "short_x_reuse") and a[0] != "ok":
                    # a legal stream must RUN, or the compare is vacuous
                    return False, f"legal stream did not run: {a[0]}"
                if a[1] is None:
                    return True, f"both {a[0]}"
                d = SM.diff_state(a[1][2], b[1][2])
                same = (a[1][0] == b[1][0] and a[1][1] == b[1][1] and not d
                        and a[1][3] == b[1][3] and a[1][4] == b[1][4])
                return same, (f"state diff {d or 'none'}; stats "
                              f"{'==' if a[1][1] == b[1][1] else '!='}; "
                              f"xwin {'==' if a[1][3] == b[1][3] else '!='}; "
                              f"res {'==' if a[1][4] == b[1][4] else '!='}")
            guarded("e", f"{name} at caps {sorted(caps) or '{}'}", z)


# ======================================================================
def spare_and_refusal_cases():
    print("=== (f) the model's SHAPE-spare assert")

    def direct(caps, bits):
        ex = SM.SeqExec([HALT], b"", _StubW(), mach=fresh_mach(), caps=caps)
        ex._movx(movx(0, n=128))
        ex._movx(movx(0, n=128, word=1536, src=128))
        r = mvgo(0, nowait=False)
        r.imm32 |= bits
        try:
            ex._mvgo(r)
            return True
        except SM.RunningChannelError:
            raise
        except AssertionError:
            return False
    guarded("f", "bits 29/30 refused by the model's assert without R2",
            lambda: (not direct(R1, XBANK) and not direct(R1, RBANK), ""))
    guarded("f", "bits 29/30 admitted under R2",
            lambda: (direct(R12, XBANK) and direct(R12, RBANK)
                     and direct(R12, XBANK | RBANK), ""))
    guarded("f", "bit 31 refused under every caps",
            lambda: (not direct(R12, 1 << 31) and not direct(NONE, 1 << 31),
                     ""))

    print("=== (g) explicit refusals and the model's own refusal selftest")

    def g0():
        miss = [f for f in ("_movx", "_mvgo", "_movy")
                if "raise RunningChannelError"
                not in inspect.getsource(getattr(SM.SeqExec, f))]
        return not miss, f"missing explicit raise in {miss or 'none'}"
    guarded("g", "_movx/_mvgo/_movy raise RunningChannelError explicitly", g0)

    def g1():
        q = SM.selftest_running_refusal()
        r2 = sorted(n for n in q["cases"] if n.startswith("r2_"))
        return q["ok"] and len(r2) >= 4, \
            f"ok={q['ok']} {q['refused']}/{q['hazards']} refused; r2 cases {r2}"
    guarded("g", "selftest_running_refusal passes and carries r2_ cases", g1)


# ======================================================================
def doc_cases():
    print("=== (h) docs/SEQ_ISA.md §B17.2")
    txt = open(os.path.join(REPO, "docs", "SEQ_ISA.md")).read()
    a = txt.find("### B17.2")
    b = txt.find("### B17.3")
    sec = txt[a:b] if a >= 0 and b > a else ""
    need = ["MOVX target[11:0]", "1536", "bit 29", "XBANK", "bit 30", "RBANK",
            "MOVY target[15:4]", "3072", "4096", "6144", "2048", "0x06",
            "NOT fail-closed", "RunningChannelError", "caps"]
    miss = [n for n in need if n not in sec]
    check("h", "B17.2 states the encoding, ranges, legality, err 0x06, "
          "NOT fail-closed, the caps rule", not miss,
          f"missing {miss or 'none'}")
    check("h", "B17.2 is no longer the placeholder",
          "Written by Task SR11a." not in sec, "")


def shipped_cases():
    print("=== (i) the shipped s1 stream validates unchanged")
    p = os.path.join(REPO, "tb", "scripts", "w9", "model_9b_s1.e4.seq")
    data = open(p, "rb").read()
    print(f"  {p} sha256 {hashlib.sha256(data).hexdigest()}")
    recs = SF.unpack_stream(data)
    for caps in (NONE, R1, R12):
        guarded("i", f"validate_stream at {sorted(caps) or '{}'}",
                lambda caps=caps: (SF.validate_stream(recs, caps=caps)
                                   == len(recs), f"{len(recs)} records"))


def main():
    print(f"=== sr11a_r2_tdd.py  FABLE5_MODEL={os.environ.get('FABLE5_MODEL')}")
    for fn in (model_cases, validator_cases, zero_bank_cases,
               spare_and_refusal_cases, doc_cases, shipped_cases):
        try:
            fn()
        except Exception as e:               # noqa: BLE001
            check(fn.__name__, "section aborted", False,
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
    print("SR11a R2 TDD: " + ("PASS" if not failed else "FAIL"))
    raise SystemExit(0 if not failed else 1)


if __name__ == "__main__":
    main()
