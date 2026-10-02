#!/usr/bin/env python3
"""sr11b_pass_tdd.py — Task SR11b (sequencer RTL round): the R2 PASS, test
first.  R2 = XWIN/RES double banking (docs/SEQ_ISA.md v2.3 §B17.2: MOVX
target[11:0] = XWIN start word, bank 1 = word 1536; MVGO SHAPE bit 29 =
XBANK, bit 30 = RBANK; MOVY target[15:4] = RES start row, bank 1 = row
2048).  NO RTL interlock: the model's running ranges (RunningChannelError)
and this pass's hazard assert are the guard.

    FABLE5_MODEL=9b FABLE5_RS_F=7 /home/cah/.venv/bin/python \
        evidence/qwen9b/sr/sr11b_pass_tdd.py

Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.  Cases (the plan's Task
SR11b step 1, plus the controller's addendum — the cost-model correction):
  (a) the census node records its bank PER MOVY (the RES bank of the MVGO
      it drains; -1 when that MVGO spans both banks; 0 at depth 1), and the
      MOVX / MVGO banks are what they were;
  (b) at r2 on reorder_e4._synthetic() (forms A and B): banks emitted (MOVX
      target 0/1536, SHAPE bits 29/30, MOVY target[15:4] 0/2048) exactly as
      the census assigned them; the elided MOVX's MVGO names the bank the
      surviving copy sits in; replay makespan <= r1's; the hazard assert
      passes; valid at caps {R1,R2}, REFUSED at {R1} and at {}; SR11a's
      model (caps {R1,R2}) runs it with every running-range and
      unwritten-read refusal armed, and its final state equals the r0
      stream's (an x-dependent stub engine, so a wrong bank shows);
  (b2) the same on a two-channel synthetic with a SPANNING K = 12288 MOVX
      and a 4096-row MVGO (they must stay at word 0 / RBANK 0), and there
      r2's replay is STRICTLY below r1's (the next x loads into the other
      bank while the stream runs);
  (c) the hazard assert is bank-aware (range-aware, the model's rule) and
      still mask-aware;
  (d) r0 and r1 unchanged: on both synthetics and both forms the output
      (stream bytes, checkpoints, manifest bytes) equals the pass at the
      base commit 99c13ce; the s1 stream at r0 (CSV, form B) regenerates
      SV1's pin and at r1 SR4's pin (n410);
  (e) ref/seq_cost.py carries the correction: FENCE_REC = 23 per FENCE
      record, a per-class single-channel tail, the inherited CMD residual;
      reorder_e4.predict() prices a zero-wait FENCE at 23 and a waiting one
      at max(t, stream end + tail) + 23; the SCHEDULING rows are unchanged
      (seq_cost.cost_of_segment equals the base commit's), so no schedule
      moves;
  (f) SPLIT in fix round 1 (review I1):
      (f1) GATE — the ADDITIVE form, the model every r2 prediction uses,
      re-predicts R1's measured s1 token-4 window (27,163,998 cyc,
      n570:39) within +-0.5 % with the FENCE record charged (its zero-wait
      FENCEs exact); SR4's convention (record cost 0) fails the same test;
      (f2) DIAGNOSTIC, not a gate — the attribution (FENCE class within
      5,000, every drained class within 2,500) of the PLACED form, which is
      IN-SAMPLE on the 19,308 CMD part, printed beside the ADDITIVE form's;
      sign convention model - measured;
  (g) the pass refuses an r2 INPUT (one that already carries bank fields);
  (h) write_out at r2 records seq_isa 2.3 + caps [R1, R2].
"""
import hashlib
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for p in (os.path.join(REPO, "ref"), os.path.join(REPO, "ref", "scripts"),
          os.path.join(REPO, "sw"), HERE,
          os.path.join(REPO, "evidence", "qwen9b", "ov")):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np                           # noqa: E402
import seq_format as SF                      # noqa: E402
import seq_model as SM                       # noqa: E402
import seq_cost as SC                        # noqa: E402
import reorder_e4 as RE                      # noqa: E402
import ov_census as OC                        # noqa: E402
import hwmap as HW                           # noqa: E402

BASE = "99c13ce"
R1 = frozenset({"R1"})
R12 = frozenset({"R1", "R2"})
NONE = frozenset()
RESULTS = []
SV1_S1_B_SHA = ("57ec3051a0d6e68ee689859bc020b440"
                "01bcce6323b8d5c78415055853bee4da")   # n32_reorder_s1_B.log:54
SR4_S1_R1_SHA = ("4e11a2ae6872970ecb61e2bb37524b7b"
                 "d863815e47df1fb9c3af2fbb3218cb28")  # n410_reorder_s1_B_r1.log:58


def check(tag, name, cond, detail=""):
    RESULTS.append((tag, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] ({tag}) {name}"
          + (f"  -- {detail}" if detail else ""))


def guarded(tag, name, fn):
    """Run fn() -> (cond, detail); an unexpected exception is a FAIL."""
    try:
        cond, detail = fn()
    except Exception as e:                   # noqa: BLE001
        cond, detail = False, f"{type(e).__name__}: {e}"
        traceback.print_exc(limit=4)
    check(tag, name, cond, detail)


def has_r2():
    return "r2" in getattr(RE, "RTLS", ())


# ======================================================================
# the base commit's pass and cost module, loaded from git (read-only)
# ======================================================================
_BASE = {}


def load_base(path, name):
    if name in _BASE:
        return _BASE[name]
    src = subprocess.check_output(["git", "-C", REPO, "show",
                                   f"{BASE}:{path}"])
    d = tempfile.mkdtemp(prefix="sr11b_base_")
    f = os.path.join(d, name + ".py")
    open(f, "wb").write(src)
    spec = importlib.util.spec_from_file_location(name, f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _BASE[name] = mod
    return mod


# ======================================================================
# synthetic streams
# ======================================================================
def synthetic_r2():
    """Two channels, four matvecs: A (K 128, 4 rows, ch0+ch1), B (a second
    source, ch0+ch1 — its MOVX can load the other bank while A streams),
    C (K = 12288 on ch0, 4096 rows: SPANS both XWIN and both RES banks),
    D (ch1 re-reads B's source: REDUNDANT MOVX, elided — its MVGO must name
    the bank B's ch1 copy sits in).  Hand-timed rows as _synthetic()'s."""
    def movx(c, src, ln):
        return SF.Rec(SF.OP_MOVX, flags=(c << SF.CHAN_SHIFT), addr_lo=src,
                      len_or_addr_hi=ln)

    def mvgo(c, nrows, ng):
        return SF.Rec(SF.OP_MVGO, flags=(c << SF.CHAN_SHIFT),
                      target=SF.MVGO_NOWAIT,
                      imm32=HW.shape_word(nrows, 0, ng),
                      addr_lo=HW.W_BASE & 0xFFFFFFFF,
                      len_or_addr_hi=(nrows << 8))

    def movy(c, dst, nrows):
        return SF.Rec(SF.OP_MOVY, flags=SF.MOVY_MODE_BIT, target=c,
                      addr_lo=dst, len_or_addr_hi=nrows)
    recs = [
        SF.Rec(SF.OP_CSRWR, target=SF.CSR_SEQ_TCNT, imm32=2),   # 0
        SF.Rec(SF.OP_EMB, addr_lo=0x100, len_or_addr_hi=128),   # 1
        movx(0, 0x100, 128), movx(1, 0x100, 128),               # 2 3  A
        mvgo(0, 4, 1), mvgo(1, 4, 1),                           # 4 5
        SF.Rec(SF.OP_FENCE),                                    # 6
        movy(0, 0x400, 4), movy(1, 0x404, 4),                   # 7 8
        movx(0, 0x800, 128), movx(1, 0x800, 128),               # 9 10 B
        mvgo(0, 4, 1), mvgo(1, 4, 1),                           # 11 12
        SF.Rec(SF.OP_FENCE),                                    # 13
        movy(0, 0x500, 4), movy(1, 0x504, 4),                   # 14 15
        movx(0, 0x1000, 12288),                                 # 16 C span
        mvgo(0, 4096, 96),                                      # 17
        SF.Rec(SF.OP_FENCE),                                    # 18
        movy(0, 0x5000, 4096),                                  # 19
        movx(1, 0x800, 128),                                    # 20 D REDUNDANT
        mvgo(1, 4, 1),                                          # 21
        SF.Rec(SF.OP_FENCE),                                    # 22
        movy(1, 0x508, 4),                                      # 23
        SF.Rec(SF.OP_JMP, flags=SF.JMP_TCNT, imm32=1),          # 24
        SF.Rec(SF.OP_HALT),                                     # 25
    ]
    S = {4: 1000, 5: 1000, 11: 1000, 12: 1000, 17: 5000, 21: 1000}
    dur = {SF.OP_EMB: 200, SF.OP_MOVX: 100, SF.OP_MVGO: 10,
           SF.OP_MOVY: 50, SF.OP_CSRWR: 5, SF.OP_JMP: 3}
    rows, t, ends = {}, 0, []
    for pc in range(1, 25):
        r = recs[pc]
        o = r.opcode
        cls = [0] * 16
        if o == SF.OP_MVGO:
            cls[OC.BSY0 + r.chan] = S[pc]
            ends.append(t + dur[o] + S[pc])
        if o == SF.OP_FENCE:
            d = max(ends) + 40 - t
            ends = []
        else:
            d = dur[o]
        rows[pc] = (o, t, d, cls)
        t += d
    return recs, rows, []


def synth_r0():
    recs, rows, cps = RE._synthetic()
    return recs, rows, cps


def reorder_at(mk, form, rtl, mod=None):
    mod = mod or RE
    recs, rows, cps = mk()
    return mod.reorder(recs, lambda k, lo, hi: rows, form, cps, rtl=rtl)


# ======================================================================
# the model, with layer commands stubbed and an x-dependent engine
# ======================================================================
class _StubW(object):
    """y depends on x (and the channel), so a MVGO that read the wrong bank
    produces a different y — and so a different final scratch."""
    def matvec(self, wbase, nrows, sh, ng, g, x8, w8=False, chan=None):
        x = np.asarray(x8, dtype=np.int64)
        h = int((x * (np.arange(len(x)) % 13 + 1)).sum()) % 1009
        return (np.arange(nrows, dtype=np.int64) * (h + 1)
                + 7 * (chan or 0) + h) % 30011

    def _lookup(self, wbase, chan=None):
        return 0, 0, {"stride": 64}, 0


def run_model(recs, caps):
    """-> the final Mach snapshot of SeqExec at `caps` (layer commands are
    no-ops here: the movers, running ranges and unwritten-read refusals are
    the model's own code)."""
    M = SM._fresh_mach()
    rng = np.random.RandomState(11)
    M.mem[0x800:0x880] = rng.randint(-100, 100, 0x80)
    M.mem[0x1000:0x1000 + 12288] = rng.randint(-100, 100, 12288)
    emb = rng.randint(-100, 100, (1, 4096))
    real = SM.SeqExec._layer_cmd
    SM.SeqExec._layer_cmd = lambda self, op: None
    try:
        ex = SM.SeqExec(list(recs), b"", _StubW(), emb=emb, mach=M,
                        caps=caps)
        ex.run()
    finally:
        SM.SeqExec._layer_cmd = real
    return SM.snapshot(ex.M), ex


def refused_at(recs, caps):
    try:
        SF.validate_stream(recs, caps=caps)
        return False
    except SF.SeqValidationError:
        return True


# ======================================================================
# (a) the census node records the bank per MOVY
# ======================================================================
def census_cases():
    print("=== (a) the census (evidence/qwen9b/ov/ov_census.py): bank per MOVY")

    def a(depth):
        recs, rows, _ = synthetic_r2()
        nodes = OC.build_nodes(recs, 1, 24, rows)
        OC.stream_durations(nodes, rows)
        OC.build_edges(nodes, True, depth, depth, "free")
        got, want = [], []
        for i, n in enumerate(nodes):
            if n.kind != "movy":
                continue
            w = next(iter(n.sdeps))
            wb = nodes[w].bank[1]
            got.append(n.bank)
            want.append(wb)
        return got, want, nodes
    guarded("a", "depth 2: every MOVY node's bank == the RES bank of the MVGO "
                 "it drains (-1 for the 4096-row span)",
            lambda: (lambda g: (g[0] == g[1] and -1 in g[0] and 1 in g[0]
                                and 0 in g[0],
                                f"MOVY banks {g[0]}, writers' RES banks "
                                f"{g[1]}"))(a(2)))
    guarded("a", "depth 1: every MOVY node's bank is 0",
            lambda: (lambda g: (g[0] and all(b == 0 for b in g[0]),
                                f"MOVY banks {g[0]}"))(a(1)))

    def a3():
        _g, _w, nodes = a(2)
        mx = [(n.pc, n.bank) for n in nodes
              if n.kind == "movx" and not n.redundant]
        mg = [(n.pc, n.bank) for n in nodes if n.kind == "mvgo"]
        want_mx = [(2, 1), (3, 1), (9, 0), (10, 0), (16, -1)]
        want_mg = [(4, (1, 1)), (5, (1, 1)), (11, (0, 0)), (12, (0, 0)),
                   (17, (-1, -1)), (21, (0, 1))]
        return (mx == want_mx and mg == want_mg,
                f"MOVX {mx}; MVGO {mg}")
    guarded("a", "depth 2: MOVX/MVGO banks as the census assigns them "
                 "(alternation from bank 1; spans -1; the elided MOVX's "
                 "MVGO reads bank 0 where ch1's surviving copy sits)", a3)


# ======================================================================
# (b) / (b2) the pass at r2
# ======================================================================
def emitted_fields(recs):
    """-> [(index, opcode name, chan, field)] of the bank fields."""
    out = []
    for i, r in enumerate(recs):
        o = r.opcode
        if o == SF.OP_MOVX:
            out.append((i, "MOVX", r.chan, r.target))
        elif o == SF.OP_MVGO:
            out.append((i, "MVGO", r.chan, ((r.imm32 >> 29) & 1,
                                            (r.imm32 >> 30) & 1)))
        elif o == SF.OP_MOVY:
            out.append((i, "MOVY", r.chan, r.target >> 4))
    return out


def bank_walk(recs):
    """An independent walk of the emitted order: every XBANK MVGO reads the
    bank the channel's last MOVX (in EMITTED order) of that bank wrote;
    every MOVY reads the RES bank of the channel's last MVGO before it that
    wrote that bank.  -> (ok, detail)."""
    last_x = {}                   # (chan, word) -> index of the MOVX
    last_r = {}                   # (chan, row) -> index of the MVGO
    bad = []
    for i, r in enumerate(recs):
        o = r.opcode
        if o == SF.OP_MOVX:
            w0 = r.target & 0xFFF
            nw = SF.movx_words(r.len_or_addr_hi)
            for k in list(last_x):
                if k[0] == r.chan and k[1] < w0 + nw and w0 < k[1] + 1536:
                    del last_x[k]
            last_x[(r.chan, w0)] = i
        elif o == SF.OP_MVGO:
            xb = (r.imm32 >> 29) & 1
            if (r.chan, 1536 * xb) not in last_x:
                bad.append(("x", i))
            last_r[(r.chan, 2048 * ((r.imm32 >> 30) & 1))] = i
        elif o == SF.OP_MOVY:
            if (r.chan, r.target >> 4) not in last_r:
                bad.append(("y", i))
    return not bad, f"unbacked reads {bad[:4]}"


def r2_pass_cases(label, mk, strict):
    for form in ("A", "B"):
        def f(form=form):
            n1, _c1, r1 = reorder_at(mk, form, "r1")
            n2, _c2, r2 = reorder_at(mk, form, "r2")
            s1, s2 = r1["segments"][0], r2["segments"][0]
            fl = emitted_fields(n2)
            nb1 = sum(1 for (_i, o, _c, v) in fl
                      if (o == "MOVX" and v == SF.XBANK_WORD)
                      or (o == "MVGO" and 1 in v)
                      or (o == "MOVY" and v == SF.RBANK_ROW))
            legal = all((o != "MOVX" or v in (0, SF.XBANK_WORD))
                        and (o != "MOVY" or v in (0, SF.RBANK_ROW))
                        for (_i, o, _c, v) in fl)
            bw, bdet = bank_walk(n2)
            le = s2["replay_mk"] <= s1["replay_mk"]
            lt = s2["replay_mk"] < s1["replay_mk"]
            RE.assert_no_pending_hazard(n2, "r2 OUTPUT")
            SF.validate_stream(n2, caps=R12)
            ref1, ref0 = refused_at(n2, R1), refused_at(n2, NONE)
            ok = (nb1 > 0 and legal and bw and le and ref1 and ref0
                  and (lt or not strict))
            return ok, (f"bank-1 fields {nb1}, legal {legal}, walk {bw} "
                        f"({bdet}); replay r2 {s2['replay_mk']} vs r1 "
                        f"{s1['replay_mk']} (<= {le}, < {lt}); refused at "
                        f"{{R1}} {ref1}, at {{}} {ref0} | "
                        + " ".join(f"{o}{c}:{v}" for (_i, o, c, v) in fl))
        guarded("b" if label == "_synthetic" else "b2",
                f"{label} form {form}: banks emitted, <= r1"
                + (" (strictly)" if strict else "")
                + ", hazard assert, {R1,R2}-only valid", f)

        def m(form=form):
            n0, _c0, _r0 = reorder_at(mk, form, "r0")
            n2, _c2, _r2 = reorder_at(mk, form, "r2")
            st0, _e0 = run_model(n0, NONE)
            st2, e2 = run_model(n2, R12)
            d = SM.diff_state(st0, st2)
            try:
                run_model(n2, R1)
                rR1 = False
            except SF.SeqValidationError:
                rR1 = True
            return (not d and rR1,
                    f"model at {{R1,R2}} ran {e2.stats['MOVX']} MOVX / "
                    f"{e2.stats['MVGO']} MVGO / {e2.stats['MOVY']} MOVY; final "
                    f"state vs the r0 stream: {d or 'IDENTICAL'}; model at "
                    f"{{R1}} refuses it: {rR1}")
        guarded("b" if label == "_synthetic" else "b2",
                f"{label} form {form}: SR11a's model runs the r2 output "
                "(ranges armed) to the r0 output's final state", m)


def elision_cases():
    def b_el():
        n2, _c, rep = reorder_at(synth_r0, "B", "r2")
        s = rep["segments"][0]
        fl = [x for x in emitted_fields(n2) if x[1] in ("MOVX", "MVGO")]
        movx = [v for (_i, o, _c, v) in fl if o == "MOVX"]
        mvgo = [v for (_i, o, _c, v) in fl if o == "MVGO"]
        ok = (s["movx_elided"] == 1 and len(movx) == 1
              and len(mvgo) == 2 and mvgo[1][0] == movx[0] // SF.XBANK_WORD)
        return ok, (f"elided {s['movx_elided']}; MOVX words {movx}; MVGO "
                    f"(XBANK, RBANK) {mvgo}")
    guarded("b", "_synthetic: the elided MOVX's MVGO names the bank of the "
                 "surviving copy", b_el)

    def b2_el():
        n2, _c, rep = reorder_at(synthetic_r2, "B", "r2")
        s = rep["segments"][0]
        # ch1: B's copy is the last MOVX on ch1; D's MVGO must read its bank
        ch1x = [r.target for r in n2 if r.opcode == SF.OP_MOVX and r.chan == 1]
        ch1g = [(r.imm32 >> 29) & 1 for r in n2
                if r.opcode == SF.OP_MVGO and r.chan == 1]
        span = [(r.target, r.len_or_addr_hi) for r in n2
                if r.opcode == SF.OP_MOVX and r.len_or_addr_hi == 12288]
        big = [((r.imm32 >> 29) & 3) for r in n2
               if r.opcode == SF.OP_MVGO and (r.imm32 >> 6) & 0xFFFF == 4096]
        ok = (s["movx_elided"] == 1 and len(ch1x) == 2
              and ch1g[-1] == ch1x[-1] // SF.XBANK_WORD
              and span == [(0, 12288)] and big == [0])
        return ok, (f"elided {s['movx_elided']}; ch1 MOVX words {ch1x}, ch1 "
                    f"MVGO XBANK {ch1g}; span MOVX {span}; 4096-row MVGO "
                    f"bank bits {big}")
    guarded("b2", "synthetic_r2: elision keyed by bank; the K 12288 MOVX at "
                  "word 0 and the 4096-row MVGO at bank bits 0", b2_el)


# ======================================================================
# (c) the hazard assert, bank-aware and mask-aware
# ======================================================================
def hazard_cases():
    print("=== (c) reorder_e4.assert_no_pending_hazard: range-aware at R2")

    def movx(c, w0=0, ln=128):
        return SF.Rec(SF.OP_MOVX, flags=(c << SF.CHAN_SHIFT), target=w0,
                      addr_lo=0, len_or_addr_hi=ln)

    def mvgo(c, xb=0, rb=0, ng=1, nrows=4):
        return SF.Rec(SF.OP_MVGO, flags=(c << SF.CHAN_SHIFT),
                      target=SF.MVGO_NOWAIT,
                      imm32=(HW.shape_word(nrows, 0, ng)
                             | (SF.SHAPE_XBANK if xb else 0)
                             | (SF.SHAPE_RBANK if rb else 0)),
                      addr_lo=0, len_or_addr_hi=(nrows << 8))

    def movy(c, row0=0, n=4):
        return SF.Rec(SF.OP_MOVY, target=c | (row0 << 4), addr_lo=0x400,
                      len_or_addr_hi=n)

    def fence(m=0):
        return SF.Rec(SF.OP_FENCE, target=m)
    HALT = SF.Rec(SF.OP_HALT)

    def e(recs, want):
        try:
            RE.assert_no_pending_hazard(recs, "SR11b")
            return (not want), "no HazardError"
        except RE.HazardError as x:
            return want, f"HazardError: {x}"
    cases = [
        ("bank-0 stream pending: MOVX into bank 1 (word 1536) -> legal",
         [movx(0), mvgo(0), movx(0, 1536), fence(1), HALT], False),
        ("bank-0 stream pending: MOVX into bank 0 -> HazardError",
         [movx(0), mvgo(0), movx(0, 0), fence(1), HALT], True),
        ("bank-1 stream pending: MOVX at word 1540 (inside) -> HazardError",
         [movx(0, 1536), mvgo(0, xb=1), movx(0, 1540), fence(1), HALT], True),
        ("spanning stream (ng 96) pending: MOVX at 1536 -> HazardError",
         [movx(0, 0, 12288), mvgo(0, ng=96), movx(0, 1536), fence(1), HALT],
         True),
        ("RBANK-1 stream pending: MOVY of rows 0.. -> legal",
         [movx(0), mvgo(0), fence(1), movx(0, 1536),
          mvgo(0, xb=1, rb=1), movy(0, 0), fence(1), HALT], False),
        ("RBANK-1 stream pending: MOVY of rows 2048.. -> HazardError",
         [movx(0, 1536), mvgo(0, xb=1, rb=1), movy(0, 2048), fence(1), HALT],
         True),
        ("a pending stream in ANY bank: MVGO on the channel -> HazardError",
         [movx(0), mvgo(0), movx(0, 1536), mvgo(0, xb=1, rb=1), fence(1),
          HALT], True),
        ("zero banks: the per-channel rule (MOVX ch0 while ch0 pends)",
         [movx(0), mvgo(0), movx(1), mvgo(1), fence(0b0010), movx(0),
          fence(0), HALT], True),
        ("mask-aware: FENCE 0b0001 drains ch0, MOVX ch0 bank 0 -> legal",
         [movx(0), mvgo(0), movx(1), mvgo(1), fence(0b0001), movx(0),
          fence(0b0010), HALT], False),
        ("a stream still pending at HALT -> HazardError",
         [movx(0), mvgo(0), movx(0, 1536), HALT], True),
    ]
    for name, recs, want in cases:
        guarded("c", name, lambda recs=recs, want=want: e(recs, want))


# ======================================================================
# (d) r0 / r1 unchanged
# ======================================================================
def r0r1_cases():
    print(f"=== (d) r0 / r1 byte-identical to the pass at {BASE}")
    base = load_base("ref/scripts/reorder_e4.py", "reorder_e4_base")

    def cmp(label, mk, form, rtl):
        def f():
            a = reorder_at(mk, form, rtl, base)
            b = reorder_at(mk, form, rtl)
            same_stream = SF.pack_stream(a[0]) == SF.pack_stream(b[0])
            same_cps = a[1] == b[1]
            tmp = tempfile.mkdtemp(prefix="sr11b_man_")
            try:
                recs, _rows, _cps = mk()
                src = os.path.join(tmp, "src.e4")
                stream = SF.pack_stream(recs)
                open(src + ".seq", "wb").write(stream)
                open(src + ".seqdata.bin", "wb").write(b"\0" * 64)
                json.dump({"stream_sha256": hashlib.sha256(stream).hexdigest(),
                           "nrec": len(recs)}, open(src + ".seq.json", "w"))
                base.write_out(os.path.join(tmp, "a.e4"), src, a[0], a[1], a[2])
                RE.write_out(os.path.join(tmp, "b.e4"), src, b[0], b[1], b[2])
                ma = open(os.path.join(tmp, "a.e4.seq.json"), "rb").read()
                mb = open(os.path.join(tmp, "b.e4.seq.json"), "rb").read()
            finally:
                shutil.rmtree(tmp)
            ok = same_stream and same_cps and ma == mb
            return ok, (f"stream {same_stream}, checkpoints {same_cps}, "
                        f"manifest {ma == mb}")
        guarded("d", f"{label} form {form} {rtl}: == the base pass", f)
    for label, mk in (("_synthetic", synth_r0), ("synthetic_r2", synthetic_r2)):
        for form in ("A", "B"):
            for rtl in ("r0", "r1"):
                cmp(label, mk, form, rtl)

    def real(rtl, want):
        def f():
            src = os.path.join(REPO, "tb", "scripts", "w9", "model_9b_s1.e4")
            stream = open(src + ".seq", "rb").read()
            meta = json.load(open(src + ".seq.json"))
            recs = SF.unpack_stream(stream)
            new, _c, _rep = RE.reorder(recs, RE.rows_provider("csv", recs),
                                       "B", meta.get("checkpoints", []),
                                       rtl=rtl)
            got = hashlib.sha256(SF.pack_stream(new)).hexdigest()
            return got == want, f"regenerated {got[:16]}, pin {want[:16]}"
        return f
    guarded("d", "model_9b_s1 form B CSV r0 == SV1's pin (n32)",
            real("r0", SV1_S1_B_SHA))
    guarded("d", "model_9b_s1 form B CSV r1 == SR4's pin (n410)",
            real("r1", SR4_S1_R1_SHA))


# ======================================================================
# (e) the cost-model correction
# ======================================================================
def cost_cases():
    print("=== (e) ref/seq_cost.py: the FENCE correction (predictions only)")
    guarded("e", "FENCE_REC = 23 cycles per FENCE record (n570:80)",
            lambda: (getattr(SC, "FENCE_REC", None) == 23,
                     f"FENCE_REC {getattr(SC, 'FENCE_REC', None)}"))

    def e2():
        t1 = getattr(SC, "TAIL1", None)
        ft = getattr(SC, "fence_tail", None)
        ok = (isinstance(t1, dict) and ("DN", "dn_out") in t1 and ft
              and ft(("DN", "dn_out")) == t1[("DN", "dn_out")]
              and ft(("??", "nothing")) == SC.TAIL1_DEFAULT
              and ft(None) == SC.TAIL1_DEFAULT
              and t1[("DN", "dn_out")] != t1.get(("DN", "mlp_gate")))
        return ok, (f"TAIL1 {t1}; default "
                    f"{getattr(SC, 'TAIL1_DEFAULT', None)}")
    guarded("e", "a per-CLASS single-channel tail (dn_out apart from the "
                 "others), a default for an unknown class", e2)

    def e3():
        f = getattr(SC, "CMD_RESID_FRAC", None)
        want = 19308 / 10710770            # n570:67
        return (f is not None and abs(f - want) < 1e-9,
                f"CMD_RESID_FRAC {f} (want {want:.9f} = +19,308 / 10,710,770)")
    guarded("e", "the inherited CMD residual (n570:67) as a fraction of CMD "
                 "work", e3)

    def e4():
        pred = getattr(RE, "predict", None)
        recs, rows, cps = RE._synthetic()
        S = RE.schedule_segment(recs, 1, 14, rows, "B", "r1")
        order = RE.order_and_fences(S, "r1")
        pmk, info = pred(S, order)
        # hand walk: FENCE end = max(t, stream end + tail) + 23
        nodes = S["nodes"]
        t, pend, send, wins = 0, [], {}, []
        tail = SC.TAIL1_DEFAULT
        for x in order:
            if RE.is_fence(x):
                fm = RE.fence_mask(x)
                sel = [m for m in pend if fm == 0 or (fm >> nodes[m].chan) & 1]
                t0 = t
                t = max([t] + [send[m] + tail for m in sel]) + SC.FENCE_REC
                pend = [m for m in pend if m not in sel]
                wins.append(t - t0)
                continue
            t += nodes[x].dur
            if nodes[x].kind == "mvgo":
                send[x] = t + nodes[x].S
                pend.append(x)
        cmd = sum(n.dur for i, n in enumerate(nodes)
                  if S["live"][i] and n.op == SF.OP_CMD)
        want = t + int(round(SC.CMD_RESID_FRAC * cmd))
        return (pmk == want and info["fence_windows"] == wins,
                f"predict {pmk} (hand walk {want}); FENCE windows "
                f"{info['fence_windows']} (hand {wins})")
    guarded("e", "reorder_e4.predict: zero-wait FENCE = 23, waiting FENCE = "
                 "max(t, end + tail) + 23, + the CMD residual", e4)

    def e5():
        bsc = load_base("ref/seq_cost.py", "seq_cost_base")
        a_recs = SC._synthetic()
        s_recs, _cps = RE._synthetic_static()
        outs = []
        for recs in (a_recs, s_recs):
            n = len(recs)
            outs.append(SC.cost_of_segment(recs, 1, n - 2, 3)
                        == bsc.cost_of_segment(recs, 1, n - 2, 3))
        return all(outs), f"cost_of_segment == base on both synthetics: {outs}"
    guarded("e", "the SCHEDULING rows are the base commit's (no schedule "
                 "moves)", e5)


# ======================================================================
# (f) the R1 re-prediction
# ======================================================================
def reprediction_cases():
    print("=== (f) the corrected model re-predicts R1's measured window")

    # SR11b fix round 1 (review I1).  (f1) is the GATE: the ADDITIVE form —
    # the SAME model every r2 prediction uses — reproduces R1's measured
    # window within +-0.5 % and charges the FENCE record (its zero-wait
    # FENCEs exact); SR4's convention (replay(), record cost 0) must FAIL
    # the same test (negative control).  (f2) is the PLACED form's
    # attribution, IN-SAMPLE on the 19,308 CMD part (token 4's own CMD
    # windows): printed as a DIAGNOSTIC, not a gate.  Sign convention
    # everywhere: model - measured.
    meas = 27163998                            # n570:39
    st = {}

    def get():
        if "r" not in st:
            import sr11b_model_correction as MC
            st["r"] = MC.reprediction()
        return st["r"]

    def f1_test(pred, zw):
        dp = 100.0 * (pred - meas) / meas
        return abs(dp) <= 0.5 and zw[0] > 0 and zw[1] == zw[2], dp

    def f1():
        r = get()
        a = r["additive"]
        ok, dp = f1_test(a["pred"], a["zero_wait"])
        b = r["before"]
        okb, dpb = f1_test(b["pred"], b["zero_wait"])
        return (ok and not okb and r["meas"] == meas,
                f"ADDITIVE {a['pred']} vs measured {meas}: model - measured "
                f"{a['pred'] - meas:+d} = {dp:+.3f} %; zero-wait "
                f"(n, model, measured) {a['zero_wait']} | negative control "
                f"BEFORE {b['pred']} ({dpb:+.3f} %), zero-wait "
                f"{b['zero_wait']} -> {'passes (BAD)' if okb else 'FAILS'}")
    guarded("f1", "GATE: the ADDITIVE form (the r2 prediction model) within "
                  "+-0.5 % of 27,163,998 with the FENCE record charged "
                  "(zero-wait exact); SR4's convention fails it", f1)

    def f2():
        try:
            r = get()
        except Exception as e:                 # noqa: BLE001
            print(f"  [DIAG] (f2) not computed: {type(e).__name__}: {e}")
            return
        for name, x in (("PLACED (IN-SAMPLE on the 19,308 CMD part)", r),
                        ("ADDITIVE", r["additive"])):
            fd = x["fence_pred"] - x["fence_meas"]
            worst = max(x["by_class"].items(),
                        key=lambda kv: abs(kv[1][1] - kv[1][2]))
            wd = worst[1][1] - worst[1][2]
            dn = x["by_class"].get(("DN", "dn_out"), (0, 0, 0))
            within = abs(fd) <= 5000 and abs(wd) <= 2500
            print(f"  [DIAG] (f2) {name}: predicted {x['pred']}, model - "
                  f"measured {x['pred'] - meas:+d}; FENCE class {fd:+d} "
                  f"(diag threshold 5,000); worst class {worst[0]} {wd:+d} "
                  f"(diag threshold 2,500); DN dn_out {dn[1] - dn[2]:+d} "
                  f"(BEFORE +9,524) -> "
                  f"{'within' if within else 'OUTSIDE'} the diagnostic "
                  f"thresholds (not a gate)")
    f2()


# ======================================================================
# (g) (h)
# ======================================================================
def misc_cases():
    print("=== (g) r2 input refused; (h) the r2 manifest")

    def g():
        recs, rows, cps = synthetic_r2()
        recs[2] = SF.Rec(SF.OP_MOVX, flags=recs[2].flags, target=1536,
                         addr_lo=recs[2].addr_lo,
                         len_or_addr_hi=recs[2].len_or_addr_hi)
        try:
            RE.reorder(recs, lambda k, lo, hi: rows, "B", cps, rtl="r2")
            return False, "reordered a stream that already carries a bank"
        except RE.ReorderError as e:
            return True, f"ReorderError: {e}"
    guarded("g", "the pass refuses an input that already carries bank "
                 "fields (the census assigns banks from program order)", g)

    def h():
        recs, rows, cps = RE._synthetic()
        tmp = tempfile.mkdtemp(prefix="sr11b_tdd_")
        try:
            src = os.path.join(tmp, "src.e4")
            stream = SF.pack_stream(recs)
            open(src + ".seq", "wb").write(stream)
            open(src + ".seqdata.bin", "wb").write(b"\0" * 64)
            json.dump({"stream_sha256": hashlib.sha256(stream).hexdigest(),
                       "nrec": len(recs)}, open(src + ".seq.json", "w"))
            new, ncps, rep = RE.reorder(recs, lambda k, lo, hi: rows, "B",
                                        cps, rtl="r2")
            out = os.path.join(tmp, "out.e4")
            RE.write_out(out, src, new, ncps, rep)
            m = json.load(open(out + ".seq.json"))
            got = (m.get("seq_isa"), m.get("caps"),
                   m["sv1_reorder"].get("rtl"))
            return got == ("2.3", ["R1", "R2"], "r2"), f"manifest {got}"
        finally:
            shutil.rmtree(tmp)
    guarded("h", "write_out at r2: seq_isa 2.3, caps [R1, R2], rtl r2", h)


def main():
    print(f"=== sr11b_pass_tdd.py  FABLE5_MODEL={os.environ.get('FABLE5_MODEL')}"
          f" FABLE5_RS_F={os.environ.get('FABLE5_RS_F')}  base {BASE}")
    print(f"    reorder_e4.RTLS {getattr(RE, 'RTLS', None)}; r2 "
          f"{'PRESENT' if has_r2() else 'ABSENT'}; predict "
          f"{'PRESENT' if hasattr(RE, 'predict') else 'ABSENT'}")
    census_cases()
    print("=== (b) / (b2) the pass at r2")
    r2_pass_cases("_synthetic", synth_r0, strict=False)
    r2_pass_cases("synthetic_r2", synthetic_r2, strict=True)
    elision_cases()
    hazard_cases()
    r0r1_cases()
    cost_cases()
    reprediction_cases()
    misc_cases()
    by = {}
    for tag, ok in RESULTS:
        by.setdefault(tag, []).append(ok)
    print("=== per case: " + "  ".join(
        f"({t}) {sum(v)}/{len(v)}" for t, v in sorted(by.items())))
    failed = sorted(t for t, v in by.items() if not all(v))
    npass = sum(ok for _t, ok in RESULTS)
    print(f"=== {npass} passed, {len(RESULTS) - npass} failed; failing cases: "
          f"{failed or 'none'}")
    print("SR11B PASS TDD: " + ("PASS" if not failed else "FAIL"))
    raise SystemExit(0 if not failed else 1)


if __name__ == "__main__":
    main()
