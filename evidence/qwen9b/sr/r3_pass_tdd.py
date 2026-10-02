#!/usr/bin/env python3
"""r3_pass_tdd.py — Task R3-5 (the R3 campaign, MOVX broadcast form (a)):
the pass's `--rtl r3`, test first.  R3 = SEQ_ISA v2.3 §B17.3: a MOVX with
flags[7:4] = 0xF reads its scratch source ONCE and writes the same x into the
XWIN of channels 0..3 at the ONE start word (so the same bank on all four).
The model (ref/seq_model.py, R3-3) has NO bank-forcing logic and will NOT
name a disagreeing consumer, so the PASS must force the bank and assert the
consumers' XBANK itself (task-R3-3-review.md carry-forward).

    FABLE5_MODEL=9b FABLE5_RS_F=7 /home/cah/.venv/bin/python \
        evidence/qwen9b/sr/r3_pass_tdd.py

Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.  A NEW file, not a group
on sr11b_pass_tdd.py: that file's cases are r2-specific throughout (its
synthetics are two-channel, its (d)/(e)/(f) pin the r2 cost correction and
its base commit is 99c13ce), while R3 needs a four-channel segment, a base
of its own and model runs at {R1,R2,R3}; it is IMPORTED here for its
two-channel synthetic and its stub engine (flags, not copies).

Cases (the plan's Task R3-5 step 1, plus the controller's addendum):
  (a) at r3 each matvec with four live MOVX emits ONE broadcast (flags[7:4]
      = 0xF), its target the bank's start word (0 / 1536); the replay
      makespan is <= r2's; a one-channel stream (_synthetic) emits none and
      is byte-identical to its r2 output;
  (b) the merged node's done- and stream-edges are the UNION of the four
      siblings' (latest-of-four, OV1_DEPENDENCY_CENSUS.md:771-773), with
      the siblings redirected onto it; it waits on the latest reader;
  (c) disagreeing banks (channel 3 carries one extra unicast matvec): the
      broadcast takes channel 0's bank, the node is counted FORCED, the
      edge from channel 3's last reader of the forced bank is present, the
      forced channel's later rotation follows (the next broadcast is not
      forced again), and the model gate (caps {R1,R2,R3}) runs the output to
      the r0 output's final state;
  (d) a group whose siblings differ in source stays four unicast MOVX and is
      counted (unicast-left);
  (e) the hazard assert refuses a hand-mutated order that broadcasts over a
      pending range on channel 3 (and accepts a broadcast into the free
      bank); R3-2's M1 row (a waiting MVGO right after a no-wait one, then a
      broadcast) is refused;
  (f) the output validates at {R1,R2,R3} and is REFUSED at {R1,R2} (the first
      refusal a broadcast record), at {R1} and at {};
  (g) r0 / r1 / r2 outputs (stream, checkpoints, manifest bytes) equal the
      pass at the base commit on every synthetic and both forms; the real s1
      stream at r0/r1/r2 (CSV, form B) regenerates SV1's / SR4's / SR11b's
      pins; the r3 manifest records seq_isa 2.3, caps [R1,R2,R3], shape_isa
      and the broadcast / forced / unicast-left counts;
  (h) the channel-keyed paths meet chan 0xF by name, never by an index
      error or a silent skip: the hazard assert (reorder_e4.py:243-245 today
      files a broadcast under channel 15 and checks nothing), a MVGO with
      chan 0xF, the pass's INPUT (the census's per-channel elision key,
      ov_census.py:669-674, would KeyError on channel 15 — refused first),
      replay() / predict() on an order containing a broadcast;
  (i) the forced case's consumer: channel 3's MVGO XBANK equals the forced
      bank; the pass's consumer assert names a mutated consumer.
"""
import hashlib
import json
import os
import shutil
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
import reorder_e4 as RE                      # noqa: E402
import ov_census as OC                       # noqa: E402
import hwmap as HW                           # noqa: E402
import sr11b_pass_tdd as T11                 # noqa: E402  (synthetic_r2, _StubW)

BASE = "a65f87c"            # R3-0's last commit; reorder_e4.py as SR11b left it
R1 = frozenset({"R1"})
R12 = frozenset({"R1", "R2"})
R123 = frozenset({"R1", "R2", "R3"})
NONE = frozenset()
RESULTS = []
PINS = {                    # model_9b_s1 form B, CSV windows
    "r0": "57ec3051a0d6e68ee689859bc020b44001bcce6323b8d5c78415055853bee4da",
    "r1": "4e11a2ae6872970ecb61e2bb37524b7bd863815e47df1fb9c3af2fbb3218cb28",
    "r2": "117ed8b061d5662517d67f905ff1b5900520ba39eff680548e8af9a7efc17d19",
}   # n32_reorder_s1_B.log:54, n410_reorder_s1_B_r1.log:51, n1161:58


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


def has_r3():
    return "r3" in getattr(RE, "RTLS", ())


# ======================================================================
# a four-channel synthetic segment
# ======================================================================
SRC = {"A": 0x100, "B": 0x800, "C": 0xC00, "D": 0x900, "E": 0xD00,
       "E2": 0xE00}
S_OF = {0: 1000, 1: 1500, 2: 2000, 3: 3000}   # stream cycles per channel


def movx(c, src, ln=128, w0=0):
    return SF.Rec(SF.OP_MOVX, flags=(c << SF.CHAN_SHIFT), target=w0,
                  addr_lo=src, len_or_addr_hi=ln)


def mvgo(c, nrows=4, ng=1, xb=0, rb=0, wait=False):
    return SF.Rec(SF.OP_MVGO, flags=(c << SF.CHAN_SHIFT),
                  target=0 if wait else SF.MVGO_NOWAIT,
                  imm32=(HW.shape_word(nrows, 0, ng)
                         | (SF.SHAPE_XBANK if xb else 0)
                         | (SF.SHAPE_RBANK if rb else 0)),
                  addr_lo=HW.W_BASE & 0xFFFFFFFF,
                  len_or_addr_hi=(nrows << 8))


def movy(c, dst, nrows=4):
    return SF.Rec(SF.OP_MOVY, flags=SF.MOVY_MODE_BIT, target=c,
                  addr_lo=dst, len_or_addr_hi=nrows)


def bcast(src, ln=128, w0=0):
    return SF.Rec(SF.OP_MOVX, flags=(SF.MOVX_BCAST << SF.CHAN_SHIFT),
                  target=w0, addr_lo=src, len_or_addr_hi=ln)


def synthetic_r3(variant="plain"):
    """Matvecs, each MOVX x4 (one per channel) + MVGO x4 + FENCE + MOVY x4:
    A (src 0x100, the EMB), B (0x800), C (0xC00: back in A's bank, so each
    of its MOVX waits on A's stream on ITS channel — 1000/1500/2000/3000
    cycles: the latest-of-four case).  variant "forced": a unicast matvec D
    on channel 3 only between A and B (channel 3's banks then disagree at
    B).  variant "differ": a matvec E after C whose channel-2 MOVX reads
    another source.  Hand-timed rows as sr11b_pass_tdd.synthetic_r2()."""
    recs = [SF.Rec(SF.OP_CSRWR, target=SF.CSR_SEQ_TCNT, imm32=2),
            SF.Rec(SF.OP_EMB, addr_lo=SRC["A"], len_or_addr_hi=128)]
    dst = [0x400]

    def matvec(srcs, chans=(0, 1, 2, 3)):
        for c in chans:
            recs.append(movx(c, srcs[c] if isinstance(srcs, dict) else srcs))
        for c in chans:
            recs.append(mvgo(c))
        recs.append(SF.Rec(SF.OP_FENCE))
        for c in chans:
            recs.append(movy(c, dst[0] + 4 * c))
        dst[0] += 0x40
    matvec(SRC["A"])
    if variant == "forced":
        matvec(SRC["D"], chans=(3,))
    matvec(SRC["B"])
    matvec(SRC["C"])
    if variant == "differ":
        matvec({0: SRC["E"], 1: SRC["E"], 2: SRC["E2"], 3: SRC["E"]})
    recs.append(SF.Rec(SF.OP_JMP, flags=SF.JMP_TCNT, imm32=1))
    recs.append(SF.Rec(SF.OP_HALT))
    dur = {SF.OP_EMB: 200, SF.OP_MOVX: 100, SF.OP_MVGO: 10,
           SF.OP_MOVY: 50, SF.OP_CSRWR: 5, SF.OP_JMP: 3}
    rows, t, ends = {}, 0, []
    for pc in range(1, len(recs) - 1):
        r = recs[pc]
        o = r.opcode
        cls = [0] * 16
        if o == SF.OP_MVGO:
            cls[OC.BSY0 + r.chan] = S_OF[r.chan]
            ends.append(t + dur[o] + S_OF[r.chan])
        if o == SF.OP_FENCE:
            d = max(ends) + 40 - t
            ends = []
        else:
            d = dur[o]
        rows[pc] = (o, t, d, cls)
        t += d
    return recs, rows, []


def mk_r3(variant):
    return lambda: synthetic_r3(variant)


SYNTHS = (("_synthetic", RE._synthetic), ("synthetic_r2", T11.synthetic_r2),
          ("synthetic_r3", mk_r3("plain")),
          ("synthetic_r3 forced", mk_r3("forced")),
          ("synthetic_r3 differ", mk_r3("differ")))


def reorder_at(mk, form, rtl, mod=None):
    mod = mod or RE
    recs, rows, cps = mk()
    return mod.reorder(recs, lambda k, lo, hi: rows, form, cps, rtl=rtl)


def seg_S(mk, form, rtl):
    recs, rows, _cps = mk()
    lo, hi = 1, len(recs) - 2
    return RE.schedule_segment(recs, lo, hi, rows, form, rtl), recs


def run_model(recs, caps):
    """sr11b_pass_tdd.run_model with every synthetic source filled."""
    M = SM._fresh_mach()
    rng = np.random.RandomState(11)
    for a in list(SRC.values()) + [0x1000]:
        n = 12288 if a == 0x1000 else 0x80
        if a != SRC["A"]:
            M.mem[a:a + n] = rng.randint(-100, 100, n)
    emb = rng.randint(-100, 100, (1, 4096))
    real = SM.SeqExec._layer_cmd
    SM.SeqExec._layer_cmd = lambda self, op: None
    try:
        ex = SM.SeqExec(list(recs), b"", T11._StubW(), emb=emb, mach=M,
                        caps=caps)
        ex.run()
    finally:
        SM.SeqExec._layer_cmd = real
    return SM.snapshot(ex.M), ex


def validate_at(recs, caps):
    try:
        SF.validate_stream(recs, caps=caps)
        return "VALID"
    except SF.SeqValidationError as e:
        return f"REFUSED: {e}"


def bcasts(recs):
    return [(i, r) for i, r in enumerate(recs)
            if r.opcode == SF.OP_MOVX and r.chan == SF.MOVX_BCAST]


def unicast_movx(recs):
    return [(i, r) for i, r in enumerate(recs)
            if r.opcode == SF.OP_MOVX and r.chan != SF.MOVX_BCAST]


# ======================================================================
# (a) one broadcast per four-channel matvec
# ======================================================================
def case_a():
    print("=== (a) one broadcast per matvec with four live MOVX")
    for form in ("A", "B"):
        def f(form=form):
            n2, _c2, r2 = reorder_at(mk_r3("plain"), form, "r2")
            n3, _c3, r3 = reorder_at(mk_r3("plain"), form, "r3")
            bc = bcasts(n3)
            tg = [r.target for _i, r in bc]
            src = [r.addr_lo for _i, r in bc]
            s2, s3 = r2["segments"][0], r3["segments"][0]
            ok = (len(bc) == 3 and not unicast_movx(n3)
                  and src == [SRC["A"], SRC["B"], SRC["C"]]
                  and tg == [SF.XBANK_WORD, 0, SF.XBANK_WORD]
                  and s3["replay_mk"] <= s2["replay_mk"])
            return ok, (f"broadcasts {len(bc)} (sources "
                        f"{[hex(s) for s in src]}, targets {tg}); unicast "
                        f"MOVX left {len(unicast_movx(n3))}; replay r3 "
                        f"{s3['replay_mk']} <= r2 {s2['replay_mk']}")
        guarded("a", f"synthetic_r3 form {form}: 3 matvecs -> 3 broadcasts at "
                     "1536 / 0 / 1536, no unicast MOVX, replay <= r2", f)

    def one_chan():
        n2, _c, _r = reorder_at(RE._synthetic, "B", "r2")
        n3, _c, r3 = reorder_at(RE._synthetic, "B", "r3")
        s = r3["segments"][0]
        ok = (SF.pack_stream(n2) == SF.pack_stream(n3) and not bcasts(n3)
              and s.get("bcast") == 0 and s.get("unicast_left_groups") == 1)
        return ok, (f"r3 stream == r2 stream "
                    f"{SF.pack_stream(n2) == SF.pack_stream(n3)}; broadcasts "
                    f"{s.get('bcast')}, unicast-left groups "
                    f"{s.get('unicast_left_groups')}")
    guarded("a", "_synthetic (one channel): no broadcast, counted "
                 "unicast-left, r3 stream byte-identical to r2's", one_chan)


# ======================================================================
# (b) latest-of-four
# ======================================================================
def edges_pc(nodes, i, mapto=None):
    mapto = mapto or {}
    n = nodes[i]
    pr = {nodes[mapto.get(p, p)].pc for p in n.preds}
    sd = {nodes[mapto.get(m, m)].pc for m in n.sdeps}
    return pr, sd


def case_b():
    print("=== (b) the merged node: the union of the four siblings' edges")
    for form in ("A", "B"):
        def f(form=form):
            S2, recs = seg_S(mk_r3("plain"), form, "r2")
            S3, _ = seg_S(mk_r3("plain"), form, "r3")
            n2, n3 = S2["nodes"], S3["nodes"]
            bc = S3["bcast"]
            out = []
            ok = len(bc["carriers"]) == 3
            to = {m: car for car, mem in bc["carriers"].items() for m in mem}
            for car, mem in sorted(bc["carriers"].items()):
                up, us = set(), set()
                for m in mem:
                    p, s = edges_pc(n2, m, to)
                    up |= p
                    us |= s
                up.discard(n3[car].pc)
                p3, s3 = edges_pc(n3, car)
                sib_dead = all(not S3["live"][m] for m in mem if m != car)
                ok &= (p3 == up and s3 == us and sib_dead
                       and n3[car].dur == n2[car].dur)
                out.append(f"carrier pc {n3[car].pc}: preds {sorted(p3)} "
                           f"(union {sorted(up)}), sdeps {sorted(s3)} (union "
                           f"{sorted(us)})")
            dangling = [(n3[i].pc, n3[p].pc) for i in range(len(n3))
                        if S3["live"][i]
                        for p in list(n3[i].preds) + list(n3[i].sdeps)
                        if p in bc["merged"]]
            ok &= not dangling
            return ok, "; ".join(out) + f"; edges onto a merged sibling " \
                                        f"{dangling}"
        guarded("b", f"synthetic_r3 form {form}: every carrier's preds/sdeps "
                     "== the union of its four siblings' (r2 edges), siblings "
                     "dead, no live edge onto a sibling", f)

    def latest():
        S3, _ = seg_S(mk_r3("plain"), "B", "r3")
        n3 = S3["nodes"]
        order = RE.order_and_fences(S3, "r3")
        _mk, _post, st = RE.replay(S3, order)
        car = sorted(S3["bcast"]["carriers"])[2]          # matvec C
        tau = [S3["groups"][n.grp]["tau"] if n.kind == "mvgo" else 0
               for n in n3]
        rd = sorted(n3[car].sdeps)                          # A's MVGOs
        send = {n3[m].chan: st[m] + n3[m].dur + n3[m].S + tau[m] for m in rd}
        lat = max(send.values())
        ok = sorted(send) == [0, 1, 2, 3] and st[car] >= lat
        return ok, (f"C's broadcast waits on A's streams on channels "
                    f"{sorted(send)}; starts at {st[car]} >= the latest "
                    f"stream end + tail {lat} (per channel {send})")
    guarded("b", "synthetic_r3 form B: C's broadcast starts after the LATEST "
                 "of the four channels' readers (channel 3's 3000-cycle "
                 "stream)", latest)


# ======================================================================
# (c) / (i) forced bank
# ======================================================================
def xbank_of(recs):
    return [(i, r.chan, (r.imm32 >> 29) & 1) for i, r in enumerate(recs)
            if r.opcode == SF.OP_MVGO]


def xwalk(recs):
    """An INDEPENDENT walk of an emitted order (not the pass's bookkeeping):
    per channel, the last writer of each XWIN window (start word; a MOVX
    over 6144 elements writes both banks' windows); a broadcast writes the
    window on all four channels.  -> {writer index: [(MVGO index, chan,
    XBANK)]} — each MVGO read the writer of its XBANK window on its
    channel."""
    last, readers = {}, {}
    for i, r in enumerate(recs):
        if r.opcode == SF.OP_MOVX:
            chans = range(4) if r.chan == SF.MOVX_BCAST else [r.chan]
            ws = ([r.target & SF.MOVX_WORD_MASK]
                  if (r.len_or_addr_hi & 0xFFFFFF) <= 6144
                  else [0, SF.XBANK_WORD])
            for c in chans:
                for w in ws:
                    last[(c, w)] = i
        elif r.opcode == SF.OP_MVGO:
            xb = (r.imm32 >> 29) & 1
            w = last.get((r.chan, SF.XBANK_WORD * xb))
            readers.setdefault(w, []).append((i, r.chan, xb))
    return readers


def consumers_of(recs):
    """[(broadcast index, [(MVGO index, chan, XBANK)])] by xwalk()."""
    rd = xwalk(recs)
    return [(j, rd.get(j, [])) for j, _r in bcasts(recs)]


def intent_mismatch(out, src):
    """Every MVGO of the emitted order `out` must read the x its program-
    order twin read: the k-th MVGO on channel c (the pass keeps per-channel
    MVGO order: one stream per engine) reads, in `src`, the source of the
    last MOVX on c before it; in `out`, the source of its XBANK window's
    writer (xwalk).  -> [(out index, chan, got source, want source)]."""
    want, last, k = {}, {}, {}
    for r in src:
        if r.opcode == SF.OP_MOVX:
            last[r.chan] = r.addr_lo
        elif r.opcode == SF.OP_MVGO:
            want[(r.chan, k.get(r.chan, 0))] = last.get(r.chan)
            k[r.chan] = k.get(r.chan, 0) + 1
    rd = xwalk(out)
    got = {}
    for w, lst in rd.items():
        for (i, c, _xb) in lst:
            got[i] = (c, None if w is None else out[w].addr_lo)
    bad, k = [], {}
    for i, r in enumerate(out):
        if r.opcode == SF.OP_MVGO:
            c = r.chan
            wv = want.get((c, k.get(c, 0)))
            k[c] = k.get(c, 0) + 1
            if got[i][1] != wv:
                bad.append((i, c, got[i][1], wv))
    return bad


def case_c():
    print("=== (c) / (i) disagreeing banks: FORCED onto channel 0's bank")
    for form in ("A", "B"):
        def f(form=form):
            S2, _ = seg_S(mk_r3("forced"), form, "r2")
            S3, _ = seg_S(mk_r3("forced"), form, "r3")
            n2, n3 = S2["nodes"], S3["nodes"]
            fo = S3["bcast"]["forced"]
            # matvec D's MVGO on channel 3 = the last reader of bank 0 there
            recs, _rows, _c = synthetic_r3("forced")
            dx = [i for i, r in enumerate(recs) if r.opcode == SF.OP_MOVX
                  and r.addr_lo == SRC["D"]][0]
            d_pc = [i for i in range(dx, len(recs))
                    if recs[i].opcode == SF.OP_MVGO][0]
            d_mvgo = [i for i, n in enumerate(n3) if n.pc == d_pc]
            ok = len(fo) == 1
            det = f"forced {fo}"
            if ok:
                car, ch, frm, to, added = fo[0]
                ok &= (ch == 3 and to == 0 and frm == 1 and d_mvgo
                       and d_mvgo[0] in n3[car].sdeps
                       and d_mvgo[0] in added
                       and d_mvgo[0] not in {m for m in n2[car].sdeps})
                det += (f"; D's ch3 MVGO (pc {n3[d_mvgo[0]].pc if d_mvgo else '?'})"
                        f" in the carrier's sdeps "
                        f"{bool(d_mvgo) and d_mvgo[0] in n3[car].sdeps}, not in "
                        f"r2's {bool(d_mvgo) and d_mvgo[0] not in n2[car].sdeps}")
            return ok, det
        guarded("c", f"synthetic_r3 forced form {form}: ONE forced node (B, "
                     "channel 3, bank 1 -> 0) with the edge from D's channel-3 "
                     "MVGO (the last reader of bank 0 there) added", f)

        def g(form=form):
            n3, _c, r3 = reorder_at(mk_r3("forced"), form, "r3")
            n0, _c, _r = reorder_at(mk_r3("forced"), form, "r0")
            s = r3["segments"][0]
            cons = consumers_of(n3)
            src, _rows, _cps = synthetic_r3("forced")
            bad = intent_mismatch(n3, src)
            agree = not bad and all(xb * SF.XBANK_WORD == n3[j].target
                                    for j, got in cons for (_i, _c, xb) in got)
            full = all(sorted(c for (_i, c, _x) in got) == [0, 1, 2, 3]
                       for _j, got in cons)
            st0, _e0 = run_model(n0, NONE)
            st3, e3 = run_model(n3, R123)
            d = SM.diff_state(st0, st3)
            ok = (s.get("forced") == 1 and s.get("bcast") == 3 and agree
                  and full and not d)
            return ok, (f"counts bcast {s.get('bcast')} forced "
                        f"{s.get('forced')}; consumers (bcast idx -> [(mvgo, "
                        f"chan, XBANK)]) {cons}; every MVGO reads its program-order x "
                        f"(mismatches {bad}) and XBANK agrees {agree}; model "
                        f"at {{R1,R2,R3}} ran {e3.stats['MOVX']} MOVX; final "
                        f"state vs the r0 stream: {d or 'IDENTICAL'}")
        guarded("c", f"synthetic_r3 forced form {form}: counts 3 broadcasts / "
                     "1 forced; every consumer's XBANK = its broadcast's "
                     "window; the model runs it to the r0 output's state", g)

        def i_(form=form):
            n3, _c, _r = reorder_at(mk_r3("forced"), form, "r3")
            cons = {n3[j].addr_lo: (j, got) for j, got in consumers_of(n3)}
            jb, gb = cons[SRC["B"]]
            jc, gc = cons[SRC["C"]]
            ch3 = [xb for (_i, c, xb) in gb if c == 3]
            nxt = [xb for (_i, c, xb) in gc if c == 3]
            ok = (n3[jb].target == 0 and ch3 == [0] and nxt == [1]
                  and n3[jc].target == SF.XBANK_WORD)
            return ok, (f"B's broadcast word {n3[jb].target}, its channel-3 "
                        f"consumer XBANK {ch3}; C's word {n3[jc].target}, "
                        f"channel-3 XBANK {nxt} (the rotation followed the "
                        f"forced bank)")
        guarded("i", f"synthetic_r3 forced form {form}: the forced channel's "
                     "MVGO XBANK = the forced bank (0), and its later rotation "
                     "follows (C: bank 1 on all four, not forced)", i_)

    def mut():
        n3, _c, r3 = reorder_at(mk_r3("forced"), "B", "r3")
        pairs = r3.get("bcast_consumers")
        cons = {n3[j].addr_lo: (j, got) for j, got in consumers_of(n3)}
        j, got = cons[SRC["B"]]
        k = [i for (i, c, _x) in got if c == 3][0]
        bad = list(n3)
        r = bad[k]
        bad[k] = SF.Rec(r.opcode, flags=r.flags, target=r.target,
                        imm32=r.imm32 ^ SF.SHAPE_XBANK, addr_lo=r.addr_lo,
                        len_or_addr_hi=r.len_or_addr_hi)
        RE.assert_bcast_consumers(n3, pairs, "r3 OUTPUT")
        try:
            RE.assert_bcast_consumers(bad, pairs, "MUTATED")
            return False, "the mutated consumer passed"
        except RE.HazardError as e:
            return (f"record {k}" in str(e) and f"{j}" in str(e),
                    f"pairs {len(pairs)}; HazardError: {e}")
    guarded("i", "the pass's consumer assert passes the output and names a "
                 "consumer MVGO whose XBANK was flipped", mut)


# ======================================================================
# (d) differing sources stay unicast
# ======================================================================
def case_d():
    print("=== (d) a group whose siblings differ in source stays unicast")
    for form in ("A", "B"):
        def f(form=form):
            n3, _c, r3 = reorder_at(mk_r3("differ"), form, "r3")
            s = r3["segments"][0]
            um = unicast_movx(n3)
            srcs = sorted((r.chan, r.addr_lo) for _i, r in um)
            want = sorted([(0, SRC["E"]), (1, SRC["E"]), (2, SRC["E2"]),
                           (3, SRC["E"])])
            ok = (len(bcasts(n3)) == 3 and srcs == want
                  and s.get("unicast_left_groups") == 2
                  and s.get("unicast_left_movx") == 4)
            return ok, (f"broadcasts {len(bcasts(n3))}; unicast MOVX "
                        f"{[(c, hex(a)) for c, a in srcs]}; counted groups "
                        f"{s.get('unicast_left_groups')} / MOVX "
                        f"{s.get('unicast_left_movx')}")
        guarded("d", f"synthetic_r3 differ form {form}: E stays four unicast "
                     "MOVX, counted (two key groups, 4 MOVX)", f)

        def m(form=form):
            n3, _c, _r = reorder_at(mk_r3("differ"), form, "r3")
            n0, _c, _r = reorder_at(mk_r3("differ"), form, "r0")
            d = SM.diff_state(run_model(n0, NONE)[0], run_model(n3, R123)[0])
            return not d, f"final state vs the r0 stream: {d or 'IDENTICAL'}"
        guarded("d", f"synthetic_r3 differ form {form}: the model runs the "
                     "mixed output to the r0 output's state", m)


# ======================================================================
# (e) the hazard assert, per destination
# ======================================================================
def case_e():
    print("=== (e) the hazard assert refuses a broadcast over a pending "
          "range on channel 3")
    HALT = SF.Rec(SF.OP_HALT)

    def fence(m=0):
        return SF.Rec(SF.OP_FENCE, target=m)

    def e(recs, want, needle=""):
        try:
            RE.assert_no_pending_hazard(recs, "R3-5")
            return (not want), "no HazardError"
        except RE.HazardError as x:
            return (want and needle in str(x)), f"HazardError: {x}"
    cases = [
        ("ch3 bank-0 stream pending: broadcast into bank 0 -> HazardError "
         "naming mv3", [movx(3, 0x900), mvgo(3), bcast(0x800), fence(8),
                        HALT], True, "mv3"),
        ("ch3 bank-0 stream pending: broadcast into bank 1 (word 1536) -> "
         "legal", [movx(3, 0x900), mvgo(3), bcast(0x800, w0=1536), fence(8),
                   HALT], False, ""),
        ("ch3 bank-1 stream pending: broadcast at word 1540 -> HazardError",
         [movx(3, 0x900, w0=1536), mvgo(3, xb=1), bcast(0x800, w0=1540),
          fence(8), HALT], True, "mv3"),
        ("ch0 drained by FENCE 0b0001, ch3 still pending -> HazardError "
         "naming mv3", [movx(0, 0x900), mvgo(0), movx(3, 0x900), mvgo(3),
                        fence(1), bcast(0x800), fence(8), HALT], True, "mv3"),
        ("every channel drained (FENCE 0) -> legal",
         [movx(3, 0x900), mvgo(3), fence(0), bcast(0x800), HALT], False, ""),
        ("R3-2's M1 row: MVGO no-wait, MVGO wait, then a broadcast -> "
         "refused (MVGO on a pending channel)",
         [movx(0, 0x900), mvgo(0), mvgo(0, wait=True), bcast(0x800),
          fence(0), HALT], True, "mv0"),
    ]
    for name, recs, want, needle in cases:
        guarded("e", name, lambda recs=recs, want=want, needle=needle:
                e(recs, want, needle))

    def mutated():
        n3, _c, _r = reorder_at(mk_r3("plain"), "B", "r3")
        RE.assert_no_pending_hazard(n3, "r3 OUTPUT")
        done = []
        for j, r in bcasts(n3):
            w0 = r.target
            for m in range(j - 1, -1, -1):
                q = n3[m]
                if (q.opcode == SF.OP_MVGO and q.chan == 3
                        and ((q.imm32 >> 29) & 1) * SF.XBANK_WORD == w0):
                    fences = [k for k in range(m + 1, j)
                              if n3[k].opcode == SF.OP_FENCE
                              and (n3[k].target == 0 or n3[k].target & 8)]
                    if fences:
                        bad = n3[:m + 1] + [r] + [x for k, x in
                                                  enumerate(n3[m + 1:], m + 1)
                                                  if k != j]
                        try:
                            RE.assert_no_pending_hazard(bad, "MUTATED")
                            done.append((j, m, "NOT REFUSED"))
                        except RE.HazardError as x:
                            done.append((j, m, "mv3" in str(x)))
                    break
        ok = bool(done) and all(v is True for (_j, _m, v) in done)
        return ok, f"(broadcast, hoisted above ch3's FENCE after MVGO, " \
                   f"refused naming mv3) {done}"
    guarded("e", "synthetic_r3 form B output: every broadcast hand-hoisted "
                 "above the FENCE that drains channel 3's same-bank stream is "
                 "refused naming mv3", mutated)


# ======================================================================
# (f) admission
# ======================================================================
def case_f():
    print("=== (f) valid at {R1,R2,R3} only")
    for label in ("plain", "forced", "differ"):
        def f(label=label):
            n3, _c, r3 = reorder_at(mk_r3(label), "B", "r3")
            v = {k: validate_at(n3, c) for k, c in
                 (("R1R2R3", R123), ("R1R2", R12), ("R1", R1), ("", NONE))}
            first = v["R1R2"]
            ok = (v["R1R2R3"] == "VALID" and first.startswith("REFUSED")
                  and "BROADCAST" in first and v["R1"].startswith("REFUSED")
                  and v[""].startswith("REFUSED")
                  and r3.get("refused_at_r1r2") is True
                  and r3.get("caps") == ["R1", "R2", "R3"])
            return ok, " | ".join(f"{{{k}}}: {x[:110]}" for k, x in v.items())
        guarded("f", f"synthetic_r3 {label} form B: VALID at {{R1,R2,R3}}; "
                     "REFUSED at {R1,R2} (first refusal the broadcast), {R1}, "
                     "{}; rep caps / refused_at_r1r2", f)


# ======================================================================
# (g) r0 / r1 / r2 unchanged; the r3 manifest
# ======================================================================
def write_both(base, a, b, mk):
    tmp = tempfile.mkdtemp(prefix="r3_5_man_")
    try:
        recs, _rows, _cps = mk()
        src = os.path.join(tmp, "src.e4")
        stream = SF.pack_stream(recs)
        open(src + ".seq", "wb").write(stream)
        open(src + ".seqdata.bin", "wb").write(b"\0" * 64)
        json.dump({"stream_sha256": hashlib.sha256(stream).hexdigest(),
                   "nrec": len(recs), "shape_isa": HW.SHAPE_ISA},
                  open(src + ".seq.json", "w"))
        ma = mb = None
        if a is not None:
            base.write_out(os.path.join(tmp, "a.e4"), src, a[0], a[1], a[2])
            ma = open(os.path.join(tmp, "a.e4.seq.json"), "rb").read()
        RE.write_out(os.path.join(tmp, "b.e4"), src, b[0], b[1], b[2])
        mb = open(os.path.join(tmp, "b.e4.seq.json"), "rb").read()
        return ma, mb
    finally:
        shutil.rmtree(tmp)


def load_base():
    import importlib.util
    import subprocess
    src = subprocess.check_output(["git", "-C", REPO, "show",
                                   f"{BASE}:ref/scripts/reorder_e4.py"])
    d = tempfile.mkdtemp(prefix="r3_5_base_")
    f = os.path.join(d, "reorder_e4_base_r3_5.py")
    open(f, "wb").write(src)
    spec = importlib.util.spec_from_file_location("reorder_e4_base_r3_5", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def case_g():
    print(f"=== (g) r0 / r1 / r2 byte-identical to the pass at {BASE}")
    base = load_base()
    for label, mk in SYNTHS:
        for form in ("A", "B"):
            for rtl in ("r0", "r1", "r2"):
                def f(mk=mk, form=form, rtl=rtl):
                    a = reorder_at(mk, form, rtl, base)
                    b = reorder_at(mk, form, rtl)
                    ss = SF.pack_stream(a[0]) == SF.pack_stream(b[0])
                    sc = a[1] == b[1]
                    ma, mb = write_both(base, a, b, mk)
                    return (ss and sc and ma == mb,
                            f"stream {ss}, checkpoints {sc}, manifest "
                            f"{ma == mb}")
                guarded("g", f"{label} form {form} {rtl}: == the base pass", f)

    def real(rtl):
        def f():
            src = os.path.join(REPO, "tb", "scripts", "w9", "model_9b_s1.e4")
            stream = open(src + ".seq", "rb").read()
            meta = json.load(open(src + ".seq.json"))
            recs = SF.unpack_stream(stream)
            new, _c, _rep = RE.reorder(recs, RE.rows_provider("csv", recs),
                                       "B", meta.get("checkpoints", []),
                                       rtl=rtl)
            got = hashlib.sha256(SF.pack_stream(new)).hexdigest()
            return got == PINS[rtl], f"regenerated {got}, pin {PINS[rtl]}"
        return f
    for rtl in ("r0", "r1", "r2"):
        guarded("g", f"model_9b_s1 form B CSV {rtl} == its pin (FULL sha256)",
                real(rtl))

    def man():
        mk = mk_r3("forced")
        b = reorder_at(mk, "B", "r3")
        _ma, mb = write_both(None, None, b, mk)
        m = json.loads(mb)
        sv = m["sv1_reorder"]
        got = (m.get("seq_isa"), m.get("caps"), sv.get("rtl"),
               m.get("shape_isa"), sv.get("broadcasts"), sv.get("forced"),
               sv.get("unicast_left_movx"), sv.get("refused_at_r1r2"))
        want = ("2.3", ["R1", "R2", "R3"], "r3", HW.SHAPE_ISA, 3, 1, 1, True)
        return got == want, f"manifest {got} (want {want})"
    guarded("g", "write_out at r3: seq_isa 2.3, caps [R1,R2,R3], rtl r3, "
                 "shape_isa kept, broadcasts / forced / unicast-left counts, "
                 "refused_at_r1r2", man)


# ======================================================================
# (h) chan 0xF on every channel-keyed path
# ======================================================================
def case_h():
    print("=== (h) the channel-keyed paths meet chan 0xF by name")
    HALT = SF.Rec(SF.OP_HALT)

    def h1():
        recs = [movx(3, 0x900), mvgo(3), bcast(0x800), SF.Rec(SF.OP_FENCE),
                HALT]
        try:
            RE.assert_no_pending_hazard(recs, "h1")
            return False, ("a broadcast over channel 3's pending range "
                           "passed (filed under channel 15, nothing checked)")
        except RE.HazardError as e:
            return "mv3" in str(e) and "broadcast" in str(e).lower(), \
                f"HazardError: {e}"
    guarded("h", "hazard assert: a broadcast is checked against every "
                 "channel, not filed under channel 15", h1)

    def h2():
        r = mvgo(0)
        bad = SF.Rec(SF.OP_MVGO, flags=(0xF << SF.CHAN_SHIFT),
                     target=r.target, imm32=r.imm32, addr_lo=r.addr_lo,
                     len_or_addr_hi=r.len_or_addr_hi)
        try:
            RE.assert_no_pending_hazard([bad, SF.Rec(SF.OP_FENCE), HALT], "h2")
            return False, "a MVGO with chan 0xF passed"
        except RE.HazardError as e:
            return "0xf" in str(e).lower(), f"HazardError: {e}"
        except Exception as e:                    # noqa: BLE001
            return False, f"{type(e).__name__} (not by name): {e}"
    guarded("h", "hazard assert: a MVGO with chan 0xF is refused BY NAME", h2)

    def h3():
        recs, rows, cps = synthetic_r3("plain")
        k = [i for i, r in enumerate(recs) if r.opcode == SF.OP_MOVX][0]
        recs = recs[:k] + [bcast(recs[k].addr_lo)] + recs[k + 4:]
        rows2 = {p: rows[p if p <= k else p + 3] for p in range(1, len(recs) - 1)}
        try:
            RE.reorder(recs, lambda kk, lo, hi: rows2, "B", cps,
                       rtl="r3" if has_r3() else "r2")
            return False, "the pass reordered an input carrying a broadcast"
        except RE.ReorderError as e:
            return "broadcast" in str(e).lower(), f"ReorderError: {e}"
        except Exception as e:                    # noqa: BLE001
            return False, f"{type(e).__name__} (not by name): {e}"
    guarded("h", "the pass refuses an INPUT carrying a broadcast by name "
                 "(before the census's per-channel elision key)", h3)

    def h4():
        S3, _ = seg_S(mk_r3("forced"), "B", "r3")
        order = RE.order_and_fences(S3, "r3")
        mk, post, _st = RE.replay(S3, order)
        pmk, info = RE.predict(S3, order)
        n3, _c, r3 = reorder_at(mk_r3("forced"), "B", "r3")
        s = r3["segments"][0]
        ok = (mk == s["replay_mk"] and pmk == s.get("pred_mk")
              and isinstance(pmk, int) and post[0] > 0
              and len(S3["bcast"]["carriers"]) == 3)
        return ok, (f"replay {mk} (report {s['replay_mk']}), POSTCHECK "
                    f"{post}; predict {pmk} (report {s.get('pred_mk')}), "
                    f"fence windows {len(info['fence_windows'])}")
    guarded("h", "replay() / predict() on an order containing broadcasts: "
                 "handled (the carrier node), equal to the report", h4)

    def h5():
        # the census's own build over an emitted broadcast (chan 15) would
        # KeyError at ov_census.py:669-674; the pass never feeds it one —
        # assert the refusal happens in the pass, before OC.build_edges
        seen = []
        real = OC.build_edges

        def spy(nodes, *a, **k):
            seen.append(any(n.kind == "movx" and n.chan == SF.MOVX_BCAST
                            for n in nodes))
            return real(nodes, *a, **k)
        OC.build_edges = spy
        try:
            n3, _c, _r = reorder_at(mk_r3("plain"), "B",
                                    "r3" if has_r3() else "r2")
        finally:
            OC.build_edges = real
        return (seen and not any(seen) and has_r3() and bcasts(n3) != []), \
            f"build_edges calls {len(seen)}, any with a chan-15 MOVX {any(seen)}"
    guarded("h", "the census (build_edges) never sees a chan-15 MOVX node on "
                 "an r3 run that emits broadcasts", h5)


def main():
    print(f"=== r3_pass_tdd.py  FABLE5_MODEL={os.environ.get('FABLE5_MODEL')}"
          f" FABLE5_RS_F={os.environ.get('FABLE5_RS_F')}  base {BASE}")
    print(f"    reorder_e4.RTLS {getattr(RE, 'RTLS', None)}; r3 "
          f"{'PRESENT' if has_r3() else 'ABSENT'}")
    case_a()
    case_b()
    case_c()
    case_d()
    case_e()
    case_f()
    case_g()
    case_h()
    by = {}
    for tag, ok in RESULTS:
        by.setdefault(tag, []).append(ok)
    print("=== per case: " + "  ".join(
        f"({t}) {sum(v)}/{len(v)}" for t, v in sorted(by.items())))
    failed = sorted(t for t, v in by.items() if not all(v))
    npass = sum(ok for _t, ok in RESULTS)
    print(f"=== {npass} passed, {len(RESULTS) - npass} failed; failing cases: "
          f"{failed or 'none'}")
    print("R3-5 PASS TDD: " + ("PASS" if not failed else "FAIL"))
    raise SystemExit(0 if not failed else 1)


if __name__ == "__main__":
    main()
