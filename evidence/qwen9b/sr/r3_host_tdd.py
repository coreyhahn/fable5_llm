#!/usr/bin/env python3
"""r3_host_tdd.py — Task R3-6 of the R3 campaign (MOVX broadcast, form (a);
docs/superpowers/plans/2026-09-29-r3-broadcast.md): the host's r3 level —
`chat_seq --seq-rtl r3`, its pinned images, and the device-keyed refusals.

    FABLE5_MODEL=9b FABLE5_RS_F=7 /home/cah/.venv/bin/python -u \
        evidence/qwen9b/sr/r3_host_tdd.py

BOARD-FREE, on SR6's mock SEQ window (evidence/qwen9b/sr/sr6_host_tdd.py
make_dev / run_seq: the REAL seq_run.Dev identity gate over a scripted CSR
map, every write / DMA method a tripwire, seq_run.upload and
chat_seq.ChatSession.bring_up tripwires too) — SR13b's method
(evidence/qwen9b/sr/sr13b_host_tdd.py) one level up.  "LOADS" = reached an
upload tripwire (every host check before the first DDR byte passed);
"REFUSED before any DMA" = a non-zero exit with no tripwire touched.

WHY A NEW FILE (not a --r3 group on sr13b_host_tdd.py): the fixture is new
(a broadcast MOVX, not bank fields), the device matrix has a fourth word,
the chat runner there is nested inside chat_cases() and not importable, and
SR13b's committed logs must stay reproducible from an unchanged file.  The
shared helpers (make_dev, run_seq, make_fixture, the r2 fixture) are
IMPORTED from sr6_host_tdd / sr13b_host_tdd, not copied.

The four SEQ_CAPS words come from sw/hwmap.py (the ONE definition, B17.0):
  0xDEADC0DE  HW.SEQ_CSR_UNMAPPED — build_041 (VERSION 0xC973C18A), {}
  0xFAB1CA01  seq_caps_word({R1}) — build_044_r1_incr (0xE3C2FF1E)
  0xFAB1CA03  seq_caps_word({R1,R2}) — build_045_r2_incr (0x266E3AE7, the
              REAL SR14 row; BM_IDENT 0xFAB1B301 scripted)
  0xFAB1CA07  seq_caps_word({R1,R2,R3}) — NO R3 bitstream exists (its
              SEQ_VERSIONS row is R3-10's, only for a kept bitstream), so a
              MOCK VERSION 0x3B3B3B3B is injected into seq_run.SEQ_VERSIONS,
              hwmap.SHAPE_ISA_BY_VERSION and hwmap.SEQ_BM_IDENT_BY_VERSION
              (the three rows land together, SR17ff minor 2) by this test
              only and removed after (SR13b's convention).

The seq_run r3 fixture is SR13b's r2 fixture (SR6's synthetic repacked
artifact, FENCEs masked, first group banked) with that first MOVX made a
BROADCAST (flags[7:4] = 0xF, window word 1536): the first broadcast record
is the first banked record.  Manifests: honest (seq_isa 2.3, caps
[R1,R2,R3]); mislabelled caps [R1,R2]; mislabelled seq_isa 2.2 (no caps);
NO capability claim.  All declare shape_isa 2.  The REAL r3 stream is R3-5's
tb/scripts/w9/model_9b_s1_reordB_r3.e4 (gitignored; re-hashed FULL here
against R3_5_PASS.md's table before use), base tb/scripts/w9/model_9b_s1.

Cases:
  setup  the words (0xFAB1CA07 decodes to {R1,R2,R3}); chat_seq at 9B; no
         SEQ_VERSIONS row reports 0xFAB1CA07 before the injection, none
         after the removal; the four r3 streams' FULL sha256 = R3-5's
  (G)    the identity gate (the REAL Dev._gate, scripted maps): the mock R3
         VERSION named, reporting 0xFAB1CA07 -> READY; reporting 0xFAB1CA03 /
         0xFAB1CA01 / 0xDEADC0DE -> REFUSED on SEQ_CAPS; build_041 (the
         shipped VERSION, the default) reporting 0xFAB1CA07 -> REFUSED; the
         R2 VERSION (named) reporting 0xFAB1CA07 -> REFUSED
  seq_run (the real main() on the mocks)
  (a)    the honest r3 fixture LOADS on the 0xFAB1CA07 mock, SEQ_CAPS read
         before the upload
  (b)(c)(d) REFUSED on 0xFAB1CA03 / 0xFAB1CA01 / 0xDEADC0DE before any DMA,
         by the validator NAMING THE BROADCAST (and its record), device-keyed
  (e)    mislabelled (caps [R1,R2]; seq_isa 2.2) and claim-less manifests:
         REFUSED on each of the three lower words naming the broadcast,
         LOAD on 0xFAB1CA07 — the manifest decides nothing
  (f)    --dry-run --caps R1,R2 refuses naming the broadcast; --caps
         R1,R2,R3 validates + relocates, uploads nothing, reads no SEQ_CAPS
  (r)    the REAL r3 stream (s1): LOADS on 0xFAB1CA07; REFUSED on the three
         lower words naming the broadcast, before any DMA
  keyless (the SR13b rule, unchanged at r3)
  (K)    the r3 fixture without its shape_isa key is REFUSED on 0xFAB1CA07
         naming the key; the four r3 manifests carry shape_isa 2; the frozen
         set is still the three build_035 streams (none of them r3)
  chat_seq (the real main() on the mocks, 9B --nch 4; B6 stubbed — the real
  r3 B6 replay is its own run, --reorder-check)
  (g)(h)(i) `--seq-rtl r3` on 0xFAB1CA03 / 0xFAB1CA01 / 0xDEADC0DE: exit 4 at
         open_board, before any upload, SEQ_CAPS read, naming the broadcast
  (j)    THE POSITIVE CASE: `--seq-rtl r3` LOADS on the 0xFAB1CA07 mock; the
         device's {R1,R2,R3} reaches load_template and
         independent_step_images after the SEQ_CAPS read; the images carry
         broadcasts and are REFUSED at {R1,R2}, {R1} and {} (naming the
         broadcast); they equal the r3 pins; session caps {R1,R2,R3}; no
         manifest involved
  (k)    refusals before the board: r3 with --reorder A / off, and
         FABLE5_SEQ_RTL=r3 with FABLE5_REORDER=off (exit 4 naming
         --seq-rtl); FABLE5_SEQ_RTL=R3 parses to r3; the model-aware
         default (auto -> B at 9B --nch 4 on the shipped template)
         satisfies check_seq_rtl at r3 as at r2 (docs/USAGE.md §3)
  (l)    the model gates at r3: B6 hands SeqExec {} (shipped side) and
         {R1,R2,R3} (reordered side); SeqModelVerifier runs at {R1,R2,R3}
  (m)    serve's namespace still pins seq_rtl = "r0"
  (n)    evidence/qwen9b/sr/sr14_ident_expect.py --want-version 3b3b3b3b
         --want-caps R1,R2,R3 (the mock row injected): exit 0, the R3 board
         judged PASS and the R3 VERSION reporting 0xFAB1CA03 judged FAIL;
         bm1_ident.judge() directly: want {R1,R2,R3} PASS on 0xFAB1CA07,
         FAIL on 0xFAB1CA03
  (p)    the pins: chat_seq's REORDER_B_PINS_BY_RTL has r3, from the
         committed pins log (its PIN r3 lines = the table); r0 / r1 / r2
         pins unchanged
  (x)    no SEQ-driving host tool (seq_run, chat_seq, serve) reads or
         expects XPTR (B17.3: a broadcast leaves all four XPTRs unchanged)

RED PREDICTION (written before the first run, against a990b40):
  PASS (characterisations — R3-2's validator names the broadcast at every
  set without all of {R1,R2,R3}, and seq_run's admission has been
  device-keyed since SR6, so the seq_run level needs no change):
    setup 5, (G) 6, (a) 2, (b) 3, (c) 3, (d) 3, (e) 12, (f) 2, (r) 4,
    (K) 3, (k) the r2 auto-default check 1, (m) 1, (n) the two direct
    judge() checks 2, (p) r0/r1/r2 pins unchanged 1, (x) 1  = 49
  FAIL (chat_seq has no r3 level: argparse exit 2, the env value is an
  error; sr14_ident_expect takes no flags; no r3 pins):
    (g) 2, (h) 2, (i) 2, (j) 7, (k) 5 (--reorder A, off, the env pair,
    FABLE5_SEQ_RTL=R3, the r3 auto default), (l) 2, (n) the script run 1,
    (p) 2  = 23
  Totals: 49 passed / 23 failed of 72.
"""
import contextlib
import hashlib
import io
import json
import os
import runpy
import shutil
import sys
import tempfile
import time
import traceback
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sr6_host_tdd as H6                                      # noqa: E402
import sr13b_host_tdd as H13                                   # noqa: E402
from sr6_host_tdd import SR, SF, HW                            # noqa: E402

ROOT = H6.ROOT
V041, V044, V045 = 0xC973C18A, 0xE3C2FF1E, 0x266E3AE7
VMOCK_R3 = 0x3B3B3B3B
W_OLD = HW.SEQ_CSR_UNMAPPED
W_R1 = HW.seq_caps_word({"R1"})
W_R12 = HW.seq_caps_word({"R1", "R2"})
W_R123 = HW.seq_caps_word({"R1", "R2", "R3"})
R123 = frozenset({"R1", "R2", "R3"})
BM = {SR.S_BM_IDENT: SR.SEQ_BM_IDENT}
DMA = ("upload", "bring_up", "wr", "dma_write", "dma_write_chan", "dma_read",
       "dma_verify", "dma_read_chan", "dma_verify_chan")
W9 = os.path.join(ROOT, "tb", "scripts", "w9")
R3_STREAMS = {   # evidence/qwen9b/sr/R3_5_PASS.md §5 table (n2720-n2723)
    "s1": "3e77e57ca39452b987d3acea708c5daf40f6def43a9bf35524caf1d47e51d3ff",
    "s2": "4584810a1f340c9dd8ea2510dd00d5e1767d219a1693fd26bd39cdaa3db03012",
    "s3": "b282ca19b6729e65052f95ea096d5087a18fe99cd2bc8a89291403668f0dd4c8",
    "s4": "735a73882ecaad2cfe183debdd25e971f28d500ba03f9eefb1b58d65450f23f4"}
PRIOR_PINS = {   # the committed pins r0 (n89) / r1 (n601) / r2 (n1351)
    "r0": ("c9efdf35175d55d4", "7119833ca6ed7d1f"),
    "r1": ("999911226f9a70b4", "bf115a04ffcc6bfa"),
    "r2": ("c78312bb293a5c2a", "868ba4e03b26276d")}
PINS_LOG = "evidence/qwen9b/sr/n2801_r3_6_pins.log"
RESULTS = []


def check(case, name, cond, detail=""):
    RESULTS.append((case, bool(cond)))
    print(f"  [{case}] {'PASS' if cond else 'FAIL'} {name}"
          + (f"  -- {detail}" if detail else ""))


def msg(res):
    return res[0] + "\n" + res[2]


def names_bcast(text):
    return "BROADCAST" in text


def inject_r3_row():
    SR.SEQ_VERSIONS[VMOCK_R3] = (HW.SHAPE_ISA_9B, "MOCK R1+R2+R3 (R3-6 test "
                                 "only)", W_R123)
    HW.SHAPE_ISA_BY_VERSION[VMOCK_R3] = HW.SHAPE_ISA_9B
    HW.SEQ_BM_IDENT_BY_VERSION[VMOCK_R3] = HW.SEQ_BM_IDENT


def drop_r3_row():
    SR.SEQ_VERSIONS.pop(VMOCK_R3, None)
    HW.SHAPE_ISA_BY_VERSION.pop(VMOCK_R3, None)
    HW.SEQ_BM_IDENT_BY_VERSION.pop(VMOCK_R3, None)


def rows_reporting(word):
    return sorted(v for v, r in SR.SEQ_VERSIONS.items() if r[2] == word and v != 0x2E874592)  # R3-10: its real R3 row (build_046_r3_incr) is excluded


def r3_fixture(d, claim, keyless=False):
    """SR13b's r2 fixture with its first (banked, word 1536) MOVX made a
    BROADCAST.  claim: "honest" | "r12" | "isa22" | "none"."""
    p, i = H13.r2_fixture(d, "none")
    recs = SF.unpack_stream(open(p + ".seq", "rb").read())
    x = recs[i]
    assert x.opcode == SF.OP_MOVX and x.target == SF.XBANK_WORD
    recs[i] = SF.Rec(x.opcode, (x.flags & 0x0F)
                     | (SF.MOVX_BCAST << SF.CHAN_SHIFT), x.target, x.imm32,
                     x.addr_lo, x.len_or_addr_hi)

    def mf(m):
        m.pop("caps", None)
        m.pop("seq_isa", None)
        if keyless:
            m.pop("shape_isa", None)
        if claim == "honest":
            m["seq_isa"], m["caps"] = "2.3", ["R1", "R2", "R3"]
        elif claim == "r12":
            m["seq_isa"], m["caps"] = "2.3", ["R1", "R2"]
        elif claim == "isa22":
            m["seq_isa"] = "2.2"
    H13._rewrite(p, recs, mf)
    return p, i


def devs():
    return {"CA07": H6.make_dev(W_R123, version=VMOCK_R3, expect=VMOCK_R3,
                                extra_regs=BM),
            "CA03": H6.make_dev(W_R12, version=V045, expect=V045,
                                extra_regs=BM),
            "CA01": H6.make_dev(W_R1, version=V044, expect=V044,
                                extra_regs=BM),
            "C0DE": H6.make_dev(W_OLD, version=V041)}


LOWER = (("CA03", "0xFAB1CA03 (build_045_r2, {R1,R2})"),
         ("CA01", "0xFAB1CA01 (build_044_r1, {R1})"),
         ("C0DE", "0xDEADC0DE (build_041, {})"))


# ======================================================================
def setup_cases():
    print("=== setup: the words, the rows, the r3 streams")
    check("setup", "seq_caps_word({R1,R2,R3}) is 0xFAB1CA07 and decodes back "
                   "to {R1,R2,R3}",
          W_R123 == 0xFAB1CA07 and HW.seq_caps_set(W_R123) == R123,
          f"{W_R123:#010x}")
    check("setup", "no SEQ_VERSIONS row reports 0xFAB1CA07 (the R3 row is "
                   "R3-10's, only for a kept bitstream)",
          not rows_reporting(W_R123),
          str([hex(v) for v in rows_reporting(W_R123)]))
    bad = {}
    for s, want in R3_STREAMS.items():
        p = os.path.join(W9, f"model_9b_{s}_reordB_r3.e4")
        got = hashlib.sha256(open(p + ".seq", "rb").read()).hexdigest()
        man = json.load(open(p + ".seq.json"))
        if got != want or man.get("stream_sha256") != want:
            bad[s] = got[:16]
    check("setup", "the four r3 streams re-hash (FULL sha256) to R3-5's "
                   "table and their manifests", not bad, str(bad))


def gate_cases():
    print("=== (G) the identity gate: the REAL Dev._gate, scripted maps")

    def gate(board_ver, expect, word):
        regs = {HW.R_MAGIC: HW.MAGIC, HW.R_VERSION: board_ver,
                HW.R_CALIB: HW.CALIB_ALL, HW.L_IDENT: HW.LAYER_IDENT,
                HW.S_IDENT: HW.SEQ_IDENT, HW.S_SEQ_CAPS: word}
        regs.update({HW.mv_base(c) + HW.R_IDENT: HW.MV_IDENT0 + c
                     for c in range(4)})
        d = object.__new__(SR.Dev)
        d.rd = lambda a: regs.get(a, HW.SEQ_CSR_UNMAPPED)
        return d._gate(expect, True)[1:]

    ok, why = gate(VMOCK_R3, VMOCK_R3, W_R123)
    check("G", "the R3 VERSION (named) reporting 0xFAB1CA07 -> SEQ READY", ok,
          why)
    for w, n in ((W_R12, "0xFAB1CA03"), (W_R1, "0xFAB1CA01"),
                 (W_OLD, "0xDEADC0DE")):
        ok, why = gate(VMOCK_R3, VMOCK_R3, w)
        check("G", f"the R3 VERSION (named) reporting {n} -> REFUSED on "
                   f"SEQ_CAPS", not ok and "SEQ_CAPS" in why, why[:120])
    ok, why = gate(V041, SR.resolve_expect_version(SR.EXPECT_DEFAULT, env={}),
                   W_R123)
    check("G", "build_041 (the shipped VERSION, the default) reporting "
               "0xFAB1CA07 -> REFUSED", not ok and "SEQ_CAPS" in why,
          why[:120])
    ok, why = gate(V045, V045, W_R123)
    check("G", "the R2 VERSION (named) reporting 0xFAB1CA07 -> REFUSED",
          not ok and "SEQ_CAPS" in why, why[:120])


def seq_cases(tmp, ltmp):
    print("=== seq_run: an r3 stream on mock SEQ windows")
    D = devs()
    ph, first = r3_fixture(os.path.join(tmp, "r3h"), "honest")
    print(f"    r3 fixture: first broadcast record {first} (MOVX chan 0xF, "
          f"window word {SF.XBANK_WORD})")
    r = H6.run_seq(["--prefix", ph], D["CA07"], ltmp, "a")
    H6.say("(a) r3 on 0xFAB1CA07", r)
    check("a", "the r3 fixture LOADS on the 0xFAB1CA07 mock", H6.loaded(r),
          r[0][:200])
    check("a", "... SEQ_CAPS read before the upload",
          H6.loaded(r) and "seq_caps_read" in r[1]
          and r[1].index("seq_caps_read") < r[1].index("upload"), str(r[1]))
    for case, (k, n) in zip("bcd", LOWER):
        r = H6.run_seq(["--prefix", ph], D[k], ltmp, case)
        H6.say(f"({case}) r3 on {n}", r)
        check(case, f"REFUSED on {n} before any DMA",
              H6.refused_before_dma(r), r[0][:200])
        check(case, f"... by the validator, naming the BROADCAST at rec "
                    f"{first}",
              names_bcast(msg(r)) and f"rec {first}" in msg(r), r[0][:200])
        check(case, "... device-keyed (SEQ_CAPS was read)",
              "seq_caps_read" in r[1], str(r[1]))

    for tag, claim in (("caps [R1,R2]", "r12"), ("seq_isa 2.2", "isa22"),
                       ("no claim", "none")):
        p, _ = r3_fixture(os.path.join(tmp, "r3" + claim), claim)
        for k, n in LOWER:
            r = H6.run_seq(["--prefix", p], D[k], ltmp, "e" + claim + k)
            check("e", f"manifest {tag}: REFUSED on {n} before any DMA, "
                       f"naming the broadcast",
                  H6.refused_before_dma(r) and names_bcast(msg(r)),
                  r[0][:160])
        r = H6.run_seq(["--prefix", p], D["CA07"], ltmp, "e" + claim + "7")
        check("e", f"manifest {tag}: LOADS on 0xFAB1CA07", H6.loaded(r),
              r[0][:160])

    r = H6.run_seq(["--prefix", ph, "--dry-run", "--caps", "R1,R2",
                    "--shape-isa", "2"], D["CA07"], ltmp, "f1")
    check("f", "--dry-run --caps R1,R2 REFUSES the r3 fixture naming the "
               "broadcast", H6.refused_before_dma(r) and names_bcast(msg(r)),
          r[0][:200])
    r = H6.run_seq(["--prefix", ph, "--dry-run", "--caps", "R1,R2,R3",
                    "--shape-isa", "2"], D["CA07"], ltmp, "f2")
    check("f", "--dry-run --caps R1,R2,R3 validates + relocates, uploads "
               "nothing, never reads SEQ_CAPS",
          r[0] in ("exit 0", "exit None", "returned")
          and not any(e in r[1] for e in DMA)
          and "seq_caps_read" not in r[1]
          and "validated only, nothing uploaded" in r[2],
          r[0] + " " + str(r[1]))

    # (r) the REAL r3 stream
    pr = os.path.join(W9, "model_9b_s1_reordB_r3.e4")
    base = ["--prefix", pr, "--base", os.path.join(W9, "model_9b_s1")]
    t0 = time.monotonic()
    r = H6.run_seq(base, D["CA07"], ltmp, "r7")
    H6.say(f"(r) model_9b_s1_reordB_r3 on 0xFAB1CA07 "
           f"({time.monotonic() - t0:.0f} s)", r)
    check("r", "the REAL r3 stream (s1) LOADS on the 0xFAB1CA07 mock",
          H6.loaded(r), r[0][:200])
    for k, n in LOWER:
        r = H6.run_seq(base, D[k], ltmp, "r" + k)
        H6.say(f"(r) model_9b_s1_reordB_r3 on {n}", r)
        check("r", f"the REAL r3 stream is REFUSED on {n} before any DMA, "
                   f"naming the broadcast",
              H6.refused_before_dma(r) and names_bcast(msg(r))
              and "seq_caps_read" in r[1], r[0][:200])


def keyless_cases(tmp, ltmp):
    print("=== keyless (SR13b's rule, unchanged at r3)")
    D = devs()
    pk, _ = r3_fixture(os.path.join(tmp, "r3k"), "honest", keyless=True)
    r = H6.run_seq(["--prefix", pk], D["CA07"], ltmp, "K1")
    H6.say("(K) keyless r3 on 0xFAB1CA07", r)
    check("K", "a keyless r3 artifact is REFUSED on 0xFAB1CA07 before any "
               "DMA, naming the missing shape_isa key",
          H6.refused_before_dma(r) and "shape_isa" in r[0] and "key" in r[0],
          r[0][:240])
    isa = {s: json.load(open(os.path.join(
        W9, f"model_9b_{s}_reordB_r3.e4.seq.json"))).get("shape_isa")
        for s in R3_STREAMS}
    check("K", "the four r3 manifests declare shape_isa 2",
          all(v == HW.SHAPE_ISA_9B for v in isa.values()), str(isa))
    fz = set(SR.FROZEN_PRE_G3_STREAMS)
    check("K", "the frozen set is still the three build_035 streams, none "
               "an r3 stream",
          len(fz) == 3 and not fz & set(R3_STREAMS.values()),
          str(sorted(k[:12] for k in fz)))


# ======================================================================
def chat_cases(ltmp):
    print("=== chat_seq --seq-rtl r3: main() on mock SEQ windows "
          f"(FABLE5_MODEL={os.environ.get('FABLE5_MODEL')})")
    import chat_seq as CS
    check("setup", "chat_seq imported at FABLE5_MODEL=9b",
          CS.MODEL_TAG == "9b", CS.MODEL_TAG)
    D = devs()
    CAPT = {}
    EV = H6.EVENTS

    def run_chat(argv, dev_cls, tag, env=None):
        del EV[:]
        CAPT.clear()
        saved = (SR.Dev, CS.reorder_model_gate, CS.ChatSession.bring_up,
                 CS.load_template, CS.independent_step_images, sys.argv)
        lt0, isi0 = CS.load_template, CS.independent_step_images

        def gate_stub(sess, log=print, override=None):
            EV.append("B6-stub")
            return {"ok": True, "stub": True, "diff": []}

        def bring_up_trip(self):
            EV.append("bring_up")
            CAPT["sess"] = self
            raise H6._Tripped("bring_up")

        def lt_spy(*a, **k):
            EV.append(("load_template", k.get("caps")))
            return lt0(*a, **k)

        def isi_spy(*a, **k):
            EV.append(("independent_step_images", k.get("caps")))
            return isi0(*a, **k)

        SR.Dev = dev_cls
        CS.reorder_model_gate = gate_stub
        CS.ChatSession.bring_up = bring_up_trip
        CS.load_template, CS.independent_step_images = lt_spy, isi_spy
        sys.argv = (["chat_seq.py"] + argv
                    + ["--lock", os.path.join(ltmp, "chat_" + tag)])
        oenv = dict(os.environ)
        os.environ.update(env or {})
        buf, ebuf = io.StringIO(), io.StringIO()
        t0 = time.monotonic()
        try:
            with contextlib.redirect_stdout(buf), \
                    contextlib.redirect_stderr(ebuf):
                CS.main()
            outcome = "returned"
        except SystemExit as e:
            outcome = f"exit {e.code!r}"
        except H6._Tripped as t:
            outcome = f"tripped {t}"
        except Exception as e:                               # noqa: BLE001
            outcome = f"raised {type(e).__name__}: {e}"
            buf.write(traceback.format_exc())
        finally:
            (SR.Dev, CS.reorder_model_gate, CS.ChatSession.bring_up,
             CS.load_template, CS.independent_step_images, sys.argv) = saved
            os.environ.clear()
            os.environ.update(oenv)
        ev = list(EV)
        out = buf.getvalue() + ebuf.getvalue()
        short = [e if isinstance(e, str) else f"{e[0]}(caps={sorted(e[1]) if e[1] is not None else None})"
                 for e in ev]
        tail = [ln for ln in out.splitlines() if ln.strip()][-4:]
        print(f"    {tag}: outcome {outcome[:160]!r} "
              f"({time.monotonic() - t0:.0f} s); events {short}")
        for ln in tail:
            print(f"      | {ln[:240]}")
        return outcome, ev, out

    def no_dma(ev):
        return not any(e in ev for e in DMA)

    base = ["--nch", "4", "--prompt", "hi", "--ntok", "1"]

    for case, (k, n) in zip("ghi", LOWER):
        o, ev, out = run_chat(base + ["--seq-rtl", "r3"], D[k], case)
        check(case, f"`chat_seq --seq-rtl r3` on {n} REFUSES (exit 4) at "
                    f"open_board, before any upload",
              o == "exit 4" and "dev" in ev and no_dma(ev), o)
        check(case, "... device-keyed (SEQ_CAPS read) and naming the "
                    "broadcast",
              "seq_caps_read" in ev and names_bcast(out), "")

    o, ev, out = run_chat(base + ["--seq-rtl", "r3"], D["CA07"], "j")
    check("j", "`chat_seq --seq-rtl r3` LOADS on the 0xFAB1CA07 mock "
               "(reaches bring_up, the first upload)",
          o == "tripped bring_up", o)
    after = ev[ev.index("seq_caps_read") + 1:] if "seq_caps_read" in ev \
        else []
    check("j", "the device's caps {R1,R2,R3} reach load_template and "
               "independent_step_images after open_board read them",
          ("load_template", R123) in after
          and ("independent_step_images", R123) in after, str(after[:4]))
    s3 = CAPT.get("sess")
    if s3 is not None:
        nbc, refs = {}, {}
        for kind in ("lite", "full"):
            recs = s3.images[kind].recs
            nbc[kind] = sum(1 for r in recs if r.opcode == SF.OP_MOVX
                            and r.chan == SF.MOVX_BCAST)
            for caps in (frozenset({"R1", "R2"}), frozenset({"R1"}),
                         frozenset()):
                try:
                    SF.validate_stream(recs, caps=caps,
                                       shape_isa=HW.SHAPE_ISA_9B)
                    refs[(kind, tuple(sorted(caps)))] = "ADMITTED"
                except SF.SeqValidationError as e:
                    refs[(kind, tuple(sorted(caps)))] = (
                        "BCAST" if names_bcast(str(e)) else str(e)[:60])
        print(f"      broadcasts per image {nbc}; lower-set verdicts "
              f"{refs}; session caps {sorted(getattr(s3, 'caps', ()) or ())}")
        check("j", "the lite/full images carry broadcasts",
              all(v > 0 for v in nbc.values()), str(nbc))
        check("j", "... and are REFUSED at {R1,R2}, {R1} and {} naming the "
                   "broadcast", all(v == "BCAST" for v in refs.values()),
              str(refs))
        pins = (getattr(CS, "REORDER_B_PINS_BY_RTL", {}).get("r3")
                or ({}, None))[0]
        check("j", "its lite/full images equal the r3 pins",
              bool(pins) and all(
                  hashlib.sha256(s3.images[k].a.data).hexdigest()
                  == pins[k][0] and s3.images[k].a.nrec == pins[k][1]
                  for k in ("lite", "full")))
        check("j", "the session's validation caps are the device's "
                   "{R1,R2,R3}", getattr(s3, "caps", None) == R123)
    else:
        for n in ("broadcasts", "lower-set refusals", "pins", "caps"):
            check("j", f"an r3 session was built ({n})", False)
    check("j", "no manifest is involved: chat images carry none (the "
               "session never read a caps claim)",
          s3 is not None and "caps" not in (getattr(s3, "meta0", {}) or {}))

    for tag, extra, env in (
            ("kA", ["--seq-rtl", "r3", "--reorder", "A"], None),
            ("koff", ["--seq-rtl", "r3", "--reorder", "off"], None),
            ("kenv", [], {"FABLE5_SEQ_RTL": "r3", "FABLE5_REORDER": "off"})):
        o, ev, out = run_chat(base + extra, D["CA07"], tag, env=env)
        check("k", f"refused before the board: {extra or env} -> exit 4 "
                   f"naming --seq-rtl",
              o == "exit 4" and "dev" not in ev
              and ("seq-rtl" in out.lower() or "seq_rtl" in out.lower()),
              f"{o}; {out.strip().splitlines()[-1:]}")
    try:
        lv = CS.seq_rtl_default({"FABLE5_SEQ_RTL": "R3"})
    except Exception as e:                                   # noqa: BLE001
        lv = repr(e)
    check("k", "FABLE5_SEQ_RTL=R3 parses to r3", lv == "r3", repr(lv))
    for lvl in ("r2", "r3"):
        ns = types.SimpleNamespace(reorder=CS.REORDER_AUTO, nch=4,
                                   template=CS.TEMPLATE4_PREFIX, seq_rtl=lvl)
        try:
            form = CS.effective_reorder(ns, env={}, log=lambda *a: None)
            ns.reorder = form
            got = (form, CS.check_seq_rtl(ns))
        except Exception as e:                               # noqa: BLE001
            got = repr(e)
        check("k", f"the model-aware default (auto, 9B --nch 4, shipped "
                   f"template) -> B, and check_seq_rtl passes at {lvl}",
              got == ("B", lvl), repr(got))

    import seq_model as SM
    seen = []

    class _RecExec(object):
        def __init__(self, recs, *a, **k):
            seen.append(k.get("caps", frozenset()))
            self.out_fifo = []

        def run(self, max_steps=None):
            return self

    if s3 is not None:
        real = SM.SeqExec
        SM.SeqExec = _RecExec
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                CS.reorder_model_gate(s3)
            b6 = list(seen)
            del seen[:]
            with contextlib.redirect_stdout(io.StringIO()):
                v = CS.SeqModelVerifier(s3, log=lambda *x: None)
                v._run(s3.images["lite"], 760, 0)
            ver = list(seen)
        except Exception as e:                               # noqa: BLE001
            b6, ver = [repr(e)], []
        finally:
            SM.SeqExec = real
        print(f"      B6 SeqExec caps (r3 session): {b6}; verifier: {ver}")
        check("l", "B6 at r3: shipped side at the empty set, reordered side "
                   "at {R1,R2,R3}", b6 == [frozenset()] * 3 + [R123] * 3,
              str(b6))
        check("l", "SeqModelVerifier at r3 runs SeqExec at {R1,R2,R3}",
              len(ver) >= 1 and ver == [R123] * len(ver), str(ver))
    else:
        check("l", "an r3 session for the model-gate caps (B6)", False)
        check("l", "an r3 session for the model-gate caps (verifier)", False)


def serve_case():
    print("=== (m) serve: BoardBackend._args() still pins seq_rtl r0")
    import serve as SV

    class _Opts(object):
        nch = 4
        template = None

        def __getattr__(self, n):
            return None
    try:
        got = getattr(SV.BoardBackend(_Opts())._args(), "seq_rtl", "<absent>")
    except Exception as e:                                   # noqa: BLE001
        got = repr(e)
    check("m", "serve's namespace pins seq_rtl = 'r0'", got == "r0",
          repr(got))


def ident_cases():
    print("=== (n) the identity expectation at R3 (bm1_ident.judge, scripted)")
    sys.path.insert(0, os.path.join(ROOT, "evidence", "qwen9b", "bm"))
    import bm1_ident as BI
    base = {"MAGIC": 0xFAB1E001, "VERSION": VMOCK_R3, "CALIB": 0xF,
            "LAYER_IDENT": 0xFAB1E5A0, "SEQ_IDENT": 0xFAB1E5E0,
            "TOPK_IDENT": 0xFAB1704B, "BM_IDENT": 0xFAB1B301,
            "SEQ_CAPS": W_R123}
    _l, ok7 = BI.judge(dict(base), VMOCK_R3, BI.parse_caps("R1,R2,R3"))
    _l, ok3 = BI.judge(dict(base, SEQ_CAPS=W_R12), VMOCK_R3,
                       BI.parse_caps("R1,R2,R3"))
    check("n", "judge(): --want-caps R1,R2,R3 PASSES on 0xFAB1CA07", ok7)
    check("n", "judge(): --want-caps R1,R2,R3 FAILS on 0xFAB1CA03", not ok3)
    script = os.path.join(HERE, "sr14_ident_expect.py")
    saved = sys.argv
    sys.argv = [script, "--want-version", f"{VMOCK_R3:08x}", "--want-caps",
                "R1,R2,R3"]
    buf = io.StringIO()
    code = None
    try:
        with contextlib.redirect_stdout(buf):
            runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        code = e.code
    except Exception as e:                                   # noqa: BLE001
        code = repr(e)
    finally:
        sys.argv = saved
    out = buf.getvalue()
    heads = [ln for ln in out.splitlines() if ln[:4] in ("PASS", "FAIL")
             or ln.startswith("SR14_IDENT")]
    for ln in heads:
        print(f"      | {ln[:200]}")
    check("n", "sr14_ident_expect.py --want-version 3b3b3b3b --want-caps "
               "R1,R2,R3: exit 0; the R3 board judged PASS; the R3 VERSION "
               "reporting 0xFAB1CA03 judged FAIL",
          code == 0
          and any(ln.startswith("PASS  R3 board") and "judge -> PASS" in ln
                  for ln in heads)
          and any(ln.startswith("PASS  R3 VERSION reporting the R1+R2 word "
                                "0xFAB1CA03") and "judge -> FAIL" in ln
                  for ln in heads), f"exit {code!r}")


def pins_cases():
    print("=== (p) the pins")
    import chat_seq as CS
    tab = getattr(CS, "REORDER_B_PINS_BY_RTL", {})
    same = all(tab.get(l) and tab[l][0]["lite"][0].startswith(a)
               and tab[l][0]["full"][0].startswith(b)
               for l, (a, b) in PRIOR_PINS.items())
    check("p", "the r0 / r1 / r2 pins are unchanged", same)
    r3 = tab.get("r3")
    check("p", f"REORDER_B_PINS_BY_RTL has r3, from {PINS_LOG}",
          bool(r3) and r3[1] == PINS_LOG and all(
              r3[0][k][0] and len(r3[0][k][0]) == 64 for k in ("lite",
                                                                "full")),
          repr(r3)[:200])
    lines = {}
    lp = os.path.join(ROOT, PINS_LOG)
    if os.path.exists(lp):
        for ln in open(lp):
            f = ln.split()
            if len(f) == 5 and f[:2] == ["PIN", "r3"]:
                lines[f[2]] = (f[3], int(f[4]))
    check("p", "... and its lite / full pins = the log's PIN r3 lines",
          bool(r3) and bool(lines) and all(
              lines.get(k) == tuple(r3[0][k]) for k in ("lite", "full")),
          str(lines))


def xptr_case():
    print("=== (x) XPTR: no SEQ-driving host tool expects it")
    # CODE, not prose: the NAME tokens (R_XPTR, any *XPTR* identifier) --
    # n2802 counted a comment that SAYS no path reads XPTR (fix, recorded)
    import tokenize
    hits = {}
    for f in ("sw/seq_run.py", "sw/chat_seq.py", "sw/serve.py"):
        with open(os.path.join(ROOT, f), "rb") as fh:
            hits[f] = sum(1 for t in tokenize.tokenize(fh.readline)
                          if t.type == tokenize.NAME and "XPTR" in t.string)
    check("x", "seq_run / chat_seq / serve never read or expect XPTR (B17.3: "
               "a broadcast leaves all four unchanged)",
          not any(hits.values()), str(hits))


def main():
    t0 = time.monotonic()
    print(f"R3-6 host TDD — FABLE5_MODEL={os.environ.get('FABLE5_MODEL')} "
          f"FABLE5_RS_F={os.environ.get('FABLE5_RS_F')}")
    tmp = tempfile.mkdtemp(prefix="r3h_fx_")
    ltmp = tempfile.mkdtemp(prefix="r3h_lock_")
    try:
        setup_cases()
    except Exception as e:                                   # noqa: BLE001
        traceback.print_exc()
        check("setup", "block ran to the end", False, repr(e))
    inject_r3_row()
    try:
        for fn, a in ((gate_cases, ()), (seq_cases, (tmp, ltmp)),
                      (keyless_cases, (tmp, ltmp)), (serve_case, ()),
                      (chat_cases, (ltmp,)), (ident_cases, ()),
                      (pins_cases, ()), (xptr_case, ())):
            try:
                fn(*a)
            except Exception as e:                           # noqa: BLE001
                traceback.print_exc()
                check(fn.__name__, "block ran to the end", False, repr(e))
    finally:
        drop_r3_row()
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(ltmp, ignore_errors=True)
    check("setup", "the injected mock row is gone after the run (no "
                   "0xFAB1CA07 row, no 0x3B3B3B3B key in any table)",
          not rows_reporting(W_R123)
          and VMOCK_R3 not in SR.SEQ_VERSIONS
          and VMOCK_R3 not in HW.SHAPE_ISA_BY_VERSION
          and VMOCK_R3 not in HW.SEQ_BM_IDENT_BY_VERSION)
    by = {}
    for c, ok in RESULTS:
        by.setdefault(c, []).append(ok)
    print("per case: " + "  ".join(f"({c}) {sum(v)}/{len(v)}"
                                   for c, v in by.items()))
    npass = sum(ok for _c, ok in RESULTS)
    print(f"R3_HOST_TDD: {npass} passed, {len(RESULTS) - npass} failed "
          f"({time.monotonic() - t0:.0f} s) -> "
          + ("PASS" if npass == len(RESULTS) else "FAIL"))
    return npass == len(RESULTS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
