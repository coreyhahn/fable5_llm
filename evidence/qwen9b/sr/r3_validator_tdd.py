#!/usr/bin/env python3
"""r3_validator_tdd.py — Task R3-2 of the R3 campaign (MOVX broadcast, form
(a)): the VALIDATOR's device-keyed admission of a broadcast MOVX, test first.
The contract is docs/SEQ_ISA.md §B17.3 (Task R3-1):

  MOVX flags[7:4] = 0xF   BROADCAST to channels 0..3, admitted ONLY when
                          {"R1","R2","R3"} ⊆ caps (the DEVICE's caps); the
                          refusal names every missing capability
  MOVX flags[7:4] 4..14   reserved, err 0x05 (E_CHAN), as today, every caps
  MVGO flags[7:4] = 0xF   err 0x05 at every caps (a broadcast is a MOVX only)
  MOVX flags[3:0] != 0    indirection refused (E_IND), as today
  MOVX target[11:0]       the ONE XWIN start word for all four channels,
                          B17.2's range rule (start + ceil(len/4) <= 3072)
  MOVX target[15:12]      0 (err 0x06, B17.2)
  running rule            every destination channel's pending x range free
                          (B17.2's rule applied per destination)

WHY A NEW FILE (plan "flags, not copies"): the existing validator TDDs are
per-task mixes of model, pass and doc checks whose content is R1's
(sr4_r1_tdd.py) or R2's (sr11a_r2_tdd.py); none differs from what R3 needs
only by a caps set or a level — every case here is new.  The plan names this
file (Task R3-2, Files).

WHERE THE RUNNING RULE IS CHECKED.  validate() (per record) stays stateless,
as B17.3 says; the per-destination running check lives in validate_stream(),
which already carries stream state (the ARG0..2 envelope).  It fires ONLY on
a broadcast record, so no existing stream's verdict can move; the unicast
running rule stays the model gate's (RunningChannelError) — Task R3-3 adds
the per-destination check to the model as well.

    FABLE5_MODEL=9b /home/cah/.venv/bin/python evidence/qwen9b/sr/r3_validator_tdd.py

Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.  The BASE validator (the
tree before R3-2, BASE_COMMIT) is loaded from git so every "unchanged" claim
is a byte-identical comparison of verdict strings, never a restatement.
Cases:
  (a) admission matrix over all 8 subsets of {R1,R2,R3}: a broadcast is
      admitted by validate() and validate_stream() only at {R1,R2,R3}; the
      refusal names the record index, the channel field 0xf and every missing
      capability ({R3} alone names R1 and R2); the caps set decoded by hwmap
      from 0xFAB1CA07 admits it, from 0xFAB1CA03 / 0xFAB1CA01 / 0xDEADC0DE
      refuses it; ref/seq_format.py types no SEQ_CAPS literal;
  (b) the B17.2 window rule on the one start word, at {R1,R2,R3};
  (c) reserved encodings refused at every caps with today's message:
      MOVX flags[7:4] 4..14, MVGO flags[7:4] 0xF, broadcast + indirection;
  (d) a unicast MOVX's verdict is the base's at every caps and layout;
  (e) the running rule per destination (validate_stream, {R1,R2,R3}):
      refused when ANY one of the four channels has an overlapping pending
      x range; admitted into the other bank, after a FENCE covering the
      channel, after a waiting MVGO; a masked FENCE skipping the channel
      leaves it refused; a K = 12288 pending stream spans both banks; a
      zero-length broadcast on a running channel is refused (the model's
      conservative _overlap); unicast verdicts stay the base's;
  (f) disasm prints "MOVX chan=ALL" for a broadcast; unicast disasm is the
      base's byte for byte;
  (g) randomized records: every verdict string is the base's except on a
      broadcast MOVX (flags[7:4] = 0xF, flags[3:0] = 0), and there: REFUSED
      by both at every caps set that lacks one of R1/R2/R3 (the refusal is
      kept; only its message now names the missing caps);
  (h) every stream under tb/scripts/w9/*.e4.seq (the shipped s1..s4, the r1
      and r2 reorders, the SR5b/SR11b/SR13a images): the validate_stream
      verdict is the base's at {}, {R1}, {R1,R2}, {R1,R2,R3}, with the
      layout unstated and stated 9B;
  (k) the named constants MOVX_BCAST = 0xF and MOVX_BCAST_CAPS (names checked
      by hwmap.seq_caps_check).
"""
import glob
import hashlib
import importlib.util
import itertools
import os
import random
import subprocess
import sys
import tempfile
import traceback
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for p in (os.path.join(REPO, "ref"), os.path.join(REPO, "sw")):
    if p not in sys.path:
        sys.path.insert(0, p)

import seq_format as SF                      # noqa: E402
import hwmap as HW                           # noqa: E402

BASE_COMMIT = "76a0c2d"      # the tree R3-2 started from (pre-R3 validator)
NAMES = ("R1", "R2", "R3")
R123 = frozenset(NAMES)
CAPSETS = [frozenset(c) for k in range(4)
           for c in itertools.combinations(NAMES, k)]
NO_R3 = [c for c in CAPSETS if "R3" not in c]
STREAM_CAPS = [frozenset(), frozenset({"R1"}), frozenset({"R1", "R2"}), R123]
BCAST = 0xF                  # literal on purpose: SF.MOVX_BCAST is under test
XBANK = 1 << 29
RESULTS = []


def cs(c):
    return "{" + ",".join(sorted(c)) + "}"


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


_BASE = None


def base():
    """ref/seq_format.py at BASE_COMMIT, loaded as its own module."""
    global _BASE
    if _BASE is None:
        src = subprocess.check_output(
            ["git", "-C", REPO, "show", f"{BASE_COMMIT}:ref/seq_format.py"])
        d = tempfile.mkdtemp(prefix="r3v_base_")
        p = os.path.join(d, "seq_format_base.py")
        open(p, "wb").write(src)
        spec = importlib.util.spec_from_file_location("seq_format_base", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _BASE = m
    return _BASE


# ---------------------------------------------------------------- records
def movx(c, n=128, src=0, word=0, ind=0):
    return SF.Rec(SF.OP_MOVX, flags=(c << SF.CHAN_SHIFT) | ind, target=word,
                  addr_lo=src, len_or_addr_hi=n)


def bcast(n=128, src=0, word=0, ind=0):
    return movx(BCAST, n=n, src=src, word=word, ind=ind)


def mvgo(c, nrows=4, ng=1, nowait=True, xb=0):
    shape = HW.shape_word(nrows, 0, ng) | (XBANK if xb else 0)
    return SF.Rec(SF.OP_MVGO, flags=(c << SF.CHAN_SHIFT),
                  target=(SF.MVGO_NOWAIT if nowait else 0), imm32=shape,
                  addr_lo=HW.W_BASE & 0xFFFFFFFF,
                  len_or_addr_hi=((nrows << 8) | ((HW.W_BASE >> 32) & 0xFF)))


def fence(mask=0):
    return SF.Rec(SF.OP_FENCE, target=mask)


HALT = SF.Rec(SF.OP_HALT)


def as_mod(mod, r):
    return mod.Rec(r.opcode, r.flags, r.target, r.imm32, r.addr_lo,
                   r.len_or_addr_hi)


def verdict(mod, r, caps, **kw):
    try:
        mod.validate(as_mod(mod, r), caps=caps, **kw)
        return "OK"
    except mod.SeqValidationError as e:
        return f"REFUSED: {e}"


def sverdict(mod, recs, caps, **kw):
    try:
        return f"OK {mod.validate_stream([as_mod(mod, r) for r in recs], caps=caps, **kw)}"
    except mod.SeqValidationError as e:
        return f"REFUSED: {e}"


# ======================================================================
def admission_cases():
    print("=== (a) admission matrix: a broadcast only at {R1,R2,R3}")
    for caps in CAPSETS:
        want = R123 <= caps
        miss = sorted(R123 - caps)

        def one(caps=caps, want=want, miss=miss):
            vs = [verdict(SF, bcast(), caps),
                  verdict(SF, bcast(), caps, shape_isa=SF.SHAPE_ISA_9B)]
            ss = sverdict(SF, [bcast(), HALT], caps)
            got = [v == "OK" for v in vs] + [ss.startswith("OK")]
            if want:
                return all(got), f"validate {vs[0]}; stream {ss[:40]}"
            named = all(m in ss for m in miss) and "rec 0" in ss \
                and "field 0xf" in ss
            return (not any(got)) and named, \
                f"missing {miss}; stream: {ss[:150]}"
        guarded("a", f"broadcast at {cs(caps)}: "
                + ("ADMITTED" if want else f"REFUSED naming {miss}"), one)

    def word_path():
        w = HW.seq_caps_word(R123)
        out = {f"{x:#010x}": verdict(SF, bcast(), HW.seq_caps_set(x)) == "OK"
               for x in (0xFAB1CA07, 0xFAB1CA03, 0xFAB1CA01, 0xDEADC0DE)}
        ok = (w == 0xFAB1CA07 and HW.seq_caps_set(w) == R123
              and out == {"0xfab1ca07": True, "0xfab1ca03": False,
                          "0xfab1ca01": False, "0xdeadc0de": False})
        return ok, f"hwmap word {w:#010x}; admitted by word {out}"
    guarded("a", "the caps set decoded by hwmap: 0xFAB1CA07 admits, "
            "0xFAB1CA03/0xFAB1CA01/0xDEADC0DE refuse", word_path)

    def no_literal():
        src = open(os.path.join(REPO, "ref", "seq_format.py")).read().lower()
        hits = [t for t in ("fab1ca", "0xfab1", "seq_caps_word(")
                if t in src]
        return not hits, f"literal tokens in ref/seq_format.py: {hits}"
    guarded("a", "ref/seq_format.py types no SEQ_CAPS word (hwmap is the ONE "
            "definition)", no_literal)


def range_cases():
    print("=== (b) the B17.2 window on the one start word, caps {R1,R2,R3}")
    rows = [
        ("start 3000 + 256 words (len 1024) refused", bcast(1024, word=3000),
         False),
        ("start 2048 + 1024 words (len 4096) admitted",
         bcast(4096, word=2048), True),
        ("start 1536 + 1536 words (bank 1 full) admitted",
         bcast(6144, word=1536), True),
        ("start 1537 + 1536 words refused", bcast(6144, word=1537), False),
        ("start 0 + 3072 words (K 12288) admitted", bcast(12288), True),
        ("start 3071 + ceil(5/4)=2 words refused (ragged tail)",
         bcast(5, word=3071), False),
        ("start 3071 + 1 word admitted", bcast(4, word=3071), True),
        ("target[15:12] != 0 refused", bcast(word=0x1000), False),
        ("target 0x8000 refused", bcast(word=0x8000), False),
    ]
    for name, r, want in rows:
        guarded("b", name, lambda r=r, want=want: (
            (verdict(SF, r, R123) == "OK") == want
            and (verdict(SF, r, R123, shape_isa=SF.SHAPE_ISA_9B) == "OK")
            == want, verdict(SF, r, R123)[:120]))


def reserved_cases():
    print("=== (c) reserved encodings refused at every caps, today's message")
    B = base()

    def chans():
        bad = []
        for c in range(4, 15):
            for caps in CAPSETS:
                v = verdict(SF, movx(c), caps)
                if v == "OK" or f"engine channel {c} >= 4" not in v \
                        or v != verdict(B, movx(c), caps):
                    bad.append((c, cs(caps), v[:60]))
        return not bad, f"{11 * len(CAPSETS)} cases; bad {bad[:3]}"
    guarded("c", "MOVX flags[7:4] 4..14 refused at all 8 caps sets with the "
            "base's message (err 0x05's 'engine channel N >= 4')", chans)

    def mvgo_f():
        bad = []
        for caps in CAPSETS:
            for isa in (None, SF.SHAPE_ISA_9B):
                r = mvgo(BCAST)
                v = verdict(SF, r, caps, shape_isa=isa)
                if v == "OK" or v != verdict(B, r, caps, shape_isa=isa):
                    bad.append((cs(caps), isa, v[:60]))
        return not bad, f"16 cases; bad {bad[:3]}"
    guarded("c", "MVGO flags[7:4] 0xF refused at all 8 caps sets (message "
            "the base's)", mvgo_f)

    def ind():
        bad = []
        for i in (SF.IND_ADD, SF.IND_SUB, 0x3, 0xF):
            for caps in CAPSETS:
                r = bcast(ind=i)
                v = verdict(SF, r, caps)
                if v == "OK" or "indirection" not in v \
                        or v != verdict(B, r, caps):
                    bad.append((i, cs(caps), v[:60]))
        return not bad, f"{4 * len(CAPSETS)} cases; bad {bad[:3]}"
    guarded("c", "broadcast with flags[3:0] != 0 refused at all 8 caps sets "
            "(indirection, the base's message)", ind)


def unicast_cases():
    print("=== (d) a unicast MOVX: the base's verdict at every caps/layout")
    B = base()

    def uni():
        n = diff = 0
        ex = []
        for c in range(4):
            for word in (0, 1536, 3000, 3071, 0x1000):
                for ln in (0, 5, 128, 1024, 4096, 12288):
                    for caps in CAPSETS:
                        for isa in (None, SF.SHAPE_ISA_9B):
                            r = movx(c, n=ln, word=word)
                            a = verdict(SF, r, caps, shape_isa=isa)
                            b = verdict(B, r, caps, shape_isa=isa)
                            n += 1
                            if a != b:
                                diff += 1
                                ex.append((c, word, ln, cs(caps)))
        return diff == 0, f"{n} cases, {diff} differ {ex[:3]}"
    guarded("d", "unicast MOVX chans 0..3 x 5 words x 6 lens x 8 caps x 2 "
            "layouts: verdict strings identical to the base", uni)


def running_cases():
    print("=== (e) the running rule per destination, validate_stream at "
          "{R1,R2,R3}")

    def refused(recs, needle=None):
        v = sverdict(SF, recs + [HALT], R123)
        ok = v.startswith("REFUSED") and (needle is None or needle in v)
        return ok, v[:150]

    def admitted(recs):
        v = sverdict(SF, recs + [HALT], R123)
        return v.startswith("OK"), v[:150]

    for c in range(4):
        guarded("e", f"broadcast while mv{c} runs (NO-WAIT, bank 0) -> "
                "refused naming the channel and the record",
                lambda c=c: refused([bcast(), mvgo(c), bcast(), fence()],
                                    needle="rec 2"))
        guarded("e", f"... and the refusal names mv{c}",
                lambda c=c: refused([mvgo(c), bcast()], needle=f"mv{c}"))
        guarded("e", f"broadcast into bank 1 while mv{c} reads bank 0 -> "
                "admitted", lambda c=c: admitted([mvgo(c),
                                                   bcast(word=1536)]))
        guarded("e", f"K = 12288 pending on mv{c} spans both banks -> a "
                "bank-1 broadcast refused",
                lambda c=c: refused([mvgo(c, ng=96), bcast(word=1536)]))
        guarded("e", f"after a FENCE (all) -> admitted",
                lambda c=c: admitted([mvgo(c), fence(), bcast()]))
        guarded("e", f"after a FENCE mask covering mv{c} (R1) -> admitted",
                lambda c=c: admitted([mvgo(c), fence(1 << c), bcast()]))
        guarded("e", f"a FENCE mask SKIPPING mv{c} leaves it running -> "
                "refused", lambda c=c: refused(
                    [mvgo(c), fence(0xF & ~(1 << c)), bcast()]))
        guarded("e", f"after a WAITING MVGO on mv{c} -> admitted",
                lambda c=c: admitted([mvgo(c, nowait=False), bcast()]))
        guarded("e", f"mv{c} running XBANK: bank-0 broadcast admitted, "
                "bank-1 refused", lambda c=c: (
                    admitted([mvgo(c, xb=1), bcast()])[0]
                    and refused([mvgo(c, xb=1), bcast(word=1536)])[0],
                    "xb pending [1536,1568)"))
    guarded("e", "one of four running: mv0,mv1,mv2 bank 1 and mv3 bank 0 -> "
            "a bank-0 broadcast refused naming mv3",
            lambda: refused([mvgo(0, xb=1), mvgo(1, xb=1), mvgo(2, xb=1),
                             mvgo(3), bcast()], needle="mv3"))
    guarded("e", "a ZERO-length broadcast on a running channel refused "
            "(the model's conservative empty-range overlap)",
            lambda: refused([mvgo(2, xb=1), bcast(n=0, word=0)]))
    guarded("e", "a running range that ends before the window -> admitted "
            "(ng 1 = words [0,32), broadcast at word 32)",
            lambda: admitted([mvgo(1), bcast(word=32)]))
    guarded("e", "... and one word into it -> refused",
            lambda: refused([mvgo(1), bcast(word=31)]))

    B = base()

    def uni():
        rows = [[mvgo(0), movx(0), fence()],
                [mvgo(0), movx(1), fence()],
                [mvgo(0), movx(0, word=1536), fence()],
                [mvgo(3, ng=96), movx(3, word=1536)]]
        bad = []
        for recs in rows:
            for caps in CAPSETS:
                a = sverdict(SF, recs + [HALT], caps)
                b = sverdict(B, recs + [HALT], caps)
                if a != b:
                    bad.append((cs(caps), a[:40], b[:40]))
        return not bad, f"{len(rows) * len(CAPSETS)} streams; bad {bad[:2]}"
    guarded("e", "unicast MOVX over a pending range: validate_stream's "
            "verdict is the base's at every caps (the unicast running rule "
            "stays the model gate's)", uni)


def disasm_cases():
    print("=== (f) disasm")
    guarded("f", "disasm(broadcast) prints 'MOVX' and 'chan=ALL'",
            lambda: (("MOVX" in SF.disasm(bcast(word=1536))
                      and "chan=ALL" in SF.disasm(bcast(word=1536))),
                     SF.disasm(bcast(word=1536))))
    B = base()

    def uni():
        bad = []
        for c in range(4):
            for w in (0, 1536):
                r = movx(c, word=w)
                if SF.disasm(r, 7) != B.disasm(as_mod(B, r), 7):
                    bad.append(c)
        return not bad, f"bad {bad}; e.g. {SF.disasm(movx(2), 7)!r}"
    guarded("f", "unicast disasm identical to the base", uni)


def _rand_rec(rng):
    op = rng.choice(sorted(SF.ALL_OPS) + [0x00, 0x0D, 0xFF])
    # bias flags toward the channel nibble's interesting values
    hi = rng.choice([0, 1, 2, 3, 4, 7, 14, 15, rng.randrange(16)])
    lo = rng.choice([0, 0, 0, 1, 2, rng.randrange(16)])
    tgt = rng.choice([0, 1, 5, 0xF, 32, 1536, 3000, 3071, 3072, 0x1000,
                      0x8001, rng.randrange(1 << 16)])
    imm = rng.choice([0, 1 << 29, 1 << 30, 1 << 31, (48 << 22) | (16 << 6),
                      (96 << 22) | (16 << 6) | (1 << 29),
                      rng.randrange(1 << 32)])
    lo32 = rng.choice([0, rng.randrange(1 << 32)])
    ln = rng.choice([0, 4, 5, 128, 1024, 4096, 6144, 12288,
                     rng.randrange(1 << 32)])
    return SF.Rec(op, (hi << 4) | lo, tgt, imm, lo32, ln)


def random_cases():
    print("=== (g) randomized records vs the base validator")
    B = base()
    rng = random.Random(0xB17_3)
    recs = [_rand_rec(rng) for _ in range(12000)]

    def run():
        n = same = bc_msg = bc_adm = other = 0
        ex = []
        for r in recs:
            is_b = r.opcode == SF.OP_MOVX and r.flags == (BCAST << 4)
            for caps in CAPSETS:
                for isa in (None, SF.SHAPE_ISA_9B, HW.SHAPE_ISA_PRE_G3):
                    a = verdict(SF, r, caps, shape_isa=isa)
                    b = verdict(B, r, caps, shape_isa=isa)
                    n += 1
                    if a == b:
                        same += 1
                    elif is_b and not R123 <= caps and a != "OK" \
                            and b != "OK":
                        bc_msg += 1          # refused by both, new message
                    elif is_b and R123 <= caps:
                        bc_adm += 1          # the one new admission
                    else:
                        other += 1
                        ex.append((f"{r.opcode:#x}", f"{r.flags:#x}",
                                   cs(caps), isa, a[:50], b[:50]))
        return other == 0 and bc_msg > 0 and bc_adm > 0, \
            (f"{len(recs)} records x 8 caps x 3 layouts = {n}; identical "
             f"{same}; broadcast refused by both (message names caps) "
             f"{bc_msg}; broadcast at {{R1,R2,R3}} {bc_adm}; any other "
             f"difference {other} {ex[:3]}")
    guarded("g", "every verdict is the base's except a broadcast MOVX; a "
            "broadcast is refused by both below {R1,R2,R3}", run)


def _stream_job(path):
    data = open(path, "rb").read()
    B = base()
    recs = SF.unpack_stream(data)
    rows = []
    for caps in STREAM_CAPS:
        for isa in (None, SF.SHAPE_ISA_9B):
            a = sverdict(SF, recs, caps, shape_isa=isa)
            b = sverdict(B, recs, caps, shape_isa=isa)
            rows.append((cs(caps), isa, a, b))
    return (os.path.relpath(path, REPO), hashlib.sha256(data).hexdigest(),
            len(recs), rows)


def stream_cases():
    print("=== (h) every tb/scripts/w9/*.e4.seq: validate_stream verdict == "
          "base at {}, {R1}, {R1,R2}, {R1,R2,R3} x layout {none, 9B}")
    paths = sorted(glob.glob(os.path.join(REPO, "tb", "scripts", "w9",
                                          "*.e4.seq")))
    with Pool(min(16, len(paths) or 1)) as pool:
        out = pool.map(_stream_job, paths)
    for rel, sha, n, rows in out:
        same = all(a == b for _c, _i, a, b in rows)
        summ = " ".join(f"{c}{'' if i is None else '/9B'}:"
                        f"{'OK' if a.startswith('OK') else 'REF'}"
                        for c, i, a, _b in rows)
        check("h", f"{os.path.basename(rel)} ({n} recs, sha256 {sha[:16]})",
              same, summ)
    check("h", "streams examined", len(out) > 0, f"{len(out)} files")


def const_cases():
    print("=== (k) named constants")
    guarded("k", "SF.MOVX_BCAST == 0xF",
            lambda: (getattr(SF, "MOVX_BCAST", None) == 0xF,
                     repr(getattr(SF, "MOVX_BCAST", None))))
    guarded("k", "SF.MOVX_BCAST_CAPS == {R1,R2,R3}, names valid in hwmap",
            lambda: (getattr(SF, "MOVX_BCAST_CAPS", None) == R123
                     and HW.seq_caps_check(SF.MOVX_BCAST_CAPS) == R123,
                     repr(getattr(SF, "MOVX_BCAST_CAPS", None))))


def main():
    print(f"=== r3_validator_tdd.py  FABLE5_MODEL="
          f"{os.environ.get('FABLE5_MODEL')}  base {BASE_COMMIT}")
    for fn in (admission_cases, range_cases, reserved_cases, unicast_cases,
               running_cases, disasm_cases, random_cases, stream_cases,
               const_cases):
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
    print("R3-2 VALIDATOR TDD: " + ("PASS" if not failed else "FAIL"))
    raise SystemExit(0 if not failed else 1)


if __name__ == "__main__":
    main()
