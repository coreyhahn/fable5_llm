#!/usr/bin/env python3
"""sr6_host_tdd.py — Task SR6 of the sequencer RTL round: the host side for R1.

    FABLE5_MODEL=9b FABLE5_RS_F=7 /home/cah/.venv/bin/python \
        evidence/qwen9b/sr/sr6_host_tdd.py

BOARD-FREE.  Every device read is a MOCK of the SEQ window: a subclass of the
REAL sw/seq_run.Dev whose constructor runs the real identity gate (_gate)
over a scripted CSR map, whose rd() answers from that map (0xDEADC0DE =
HW.SEQ_CSR_UNMAPPED outside it, as the RTL's read mux default does), and
whose every write / DMA method is an UPLOAD TRIPWIRE (the n35 closed-gate +
upload-tripwire pattern, NEXT_SESSION.md §3; seq_run's own B3 selftest).
seq_run.upload() and chat_seq.ChatSession.bring_up() are tripwires too:
reaching one of them is what "the stream LOADS" means here — every host
check before the first DDR byte passed — and never reaching one is what
"refused before any DMA" means.

The two SEQ_CAPS words are HW.seq_caps_word({"R1"}) (= 0xFAB1CA01) and
HW.SEQ_CSR_UNMAPPED (= 0xDEADC0DE, what every pre-round bitstream reads at
0x64); the test takes both from sw/hwmap.py (ONE definition, B17.0).

Cases (the plan's Task SR6 Step 1, (a)..(g), plus the checks the
implementation needs pinned):
  (a) an r1 stream LOADS through seq_run.main() on a 0xFAB1CA01 mock
  (b) the same stream is REFUSED on a 0xDEADC0DE mock by the validator (the
      message names the first masked FENCE record), upload tripwire
      untouched; (b2) the refusal is device-keyed: SEQ_CAPS was read
  (c) a shipped-form (r0) stream loads on both mocks; (c2) SEQ_CAPS read
  (d) an r1 stream whose manifest claims caps [] still refuses on
      0xDEADC0DE and still loads on 0xFAB1CA01 (the manifest is not the key)
  (e) a manifest claiming caps ["R2"] on a 0xFAB1CA01 device is refused BY
      NAME before any DMA
  (f) `chat_seq --nch 4 --seq-rtl r1` on the 0xDEADC0DE mock refuses at
      open_board, before any upload
  (g) THE POSITIVE CASE: `chat_seq --nch 4 --seq-rtl r1` LOADS on a
      0xFAB1CA01 mock.  ROUTE: the real chat_seq.main() with SR.Dev = the
      mock (the MOCK-DEVICE path) — main -> resolve_reorder -> ChatSession
      (r1 images, pins) -> image hazard assert -> B6 (STUBBED here; the real
      B6 replay of the r1 images is its own run, `--reorder-check`) ->
      open_board (device caps read) -> the device-caps validation, which
      calls chat_seq.load_template (the :477 validate_stream site) and
      chat_seq.independent_step_images (the :518 site) with caps = the
      device's, and every image's relocated records -> bring_up (tripwire).
  (g0) control: the default session (r0, form B) on the 0xDEADC0DE mock
      loads — its images still equal the S1P pins (REORDER_B_IMAGES)
  (h) serve's args namespace pins seq_rtl = "r0"
  (i) chat_seq refusals before the lock/board: --seq-rtl r1 with --reorder
      A / off; an unknown level; a bad $FABLE5_SEQ_RTL
  (k) the model gates run the R1 model at r1: reorder_model_gate hands
      seq_model.SeqExec caps {"R1"} on the reordered side (and none on the
      shipped side); SeqModelVerifier (--verify / --model-only) likewise
  (l) seq_run --caps: the board-free caps for --dry-run only (default the
      empty set), refused on a SEQ run; a dry-run of r1 without it is
      refused; WITH it (fix round 1, I-1) the dry-run validates + relocates
      at the typed set and uploads NOTHING — no path uploads an r1 stream
      without a device read
  (m) Dev.seq_caps(): 0xDEADC0DE -> empty, 0xFAB1CA01 -> {R1}; an unknown
      bit (0xFAB1CA08) is refused before any DMA; a closed SEQ gate never
      reads it

RED PREDICTION (written before the first run, against 7e72126): FAIL on
(a), (b2), (c2), (d)-load, (e), (f), (g), (h), (i) [the A / off / env
refusals and the bad $FABLE5_SEQ_RTL, which today is simply ignored],
(k), (l), (m) — seq_run validates at the empty set wherever it is and reads
no SEQ_CAPS, chat_seq has no --seq-rtl, serve pins no seq_rtl.  PASS on
(b) [today refuses every r1 stream — the safe direction], (c) [r0 loads],
(d)-refuse, (g0) [the control], and (i)'s unknown-level case (argparse
refuses an unknown flag today too, so it passes vacuously in RED).

FIX ROUND 1 RED PREDICTION (against 3b3c727): the flipped l3 case's first two
checks FAIL (41 passed / 2 failed of 43) — today --dry-run --caps R1 reaches the upload tripwire and prints no
"validated only, nothing uploaded"; its "never read SEQ_CAPS" check passes;
every other case passes as in n603.
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                    ".."))
sys.path[:0] = [os.path.join(ROOT, "sw"), os.path.join(ROOT, "ref"),
                os.path.join(ROOT, "ref", "scripts")]
os.environ.pop("FABLE5_SEQ_EXPECT_VERSION", None)
os.environ.pop("FABLE5_REORDER", None)
os.environ.pop("FABLE5_SEQ_RTL", None)

import hwmap as HW                                              # noqa: E402
import seq_format as SF                                         # noqa: E402
import seq_run as SR                                            # noqa: E402

W_R1 = HW.seq_caps_word({"R1"})
W_OLD = HW.SEQ_CSR_UNMAPPED
# SR11a fix 2: build_044_r1_incr (sw/seq_run.py SEQ_VERSIONS, SR7), the
# VERSION whose row expects the R1 SEQ_CAPS word
V_R1 = 0xE3C2FF1E
W_BAD = (HW.SEQ_CAPS_MAGIC << 8) | 0x08       # magic + unknown bit 3

NPASS = NFAIL = 0
RESULTS = []


def check(case, name, cond, detail=""):
    global NPASS, NFAIL
    ok = bool(cond)
    NPASS += ok
    NFAIL += not ok
    RESULTS.append((case, ok))
    print(f"  [{case}] {'PASS' if ok else 'FAIL'} {name}"
          + (f"  -- {detail}" if detail and not ok else "")
          + (f"  ({detail})" if detail and ok else ""))


class _Tripped(Exception):
    pass


EVENTS = []
READS = []


def make_dev(caps_word, version=SR.EXPECTED_SEQ_VERSION, expect=None,
             use_env=False, extra_regs=None):
    """A mock SEQ window: the REAL Dev class, scripted rd(), tripwired I/O.

    SR11a fix round 2 (after SR7: the identity gate now compares the
    device's SEQ_CAPS word against its SEQ_VERSIONS row): `expect` is the
    VERSION the mocked caller NAMES when it passes none itself (as
    `--expect-version` / $FABLE5_SEQ_EXPECT_VERSION would); `use_env`
    resolves an unnamed expectation from the real environment instead of
    the empty one (SR11a fix 2's chat_seq case sets
    FABLE5_SEQ_EXPECT_VERSION)."""
    regs = {HW.R_MAGIC: HW.MAGIC, HW.R_VERSION: version,
            HW.R_CALIB: HW.CALIB_ALL, HW.L_IDENT: HW.LAYER_IDENT,
            HW.S_IDENT: HW.SEQ_IDENT, HW.S_SEQ_CAPS: caps_word}
    regs.update({HW.mv_base(c) + HW.R_IDENT: HW.MV_IDENT0 + c
                 for c in range(4)})
    # SR11a fix round 3: extra scripted words (e.g. BM_IDENT on build_042)
    regs.update(extra_regs or {})

    def trip(name):
        def f(self, *a, **k):
            EVENTS.append(name)
            raise _Tripped(name)
        return f

    class MockDev(SR.Dev):
        def __init__(self, path="/dev/xdma0", chan=0, allow_seq=True,
                     expect_version=SR.EXPECT_DEFAULT, log=print):
            self.chan, self.log = chan, log
            self.n_rd = self.n_wr = 0
            if expect is not None and expect_version is SR.EXPECT_DEFAULT:
                expect_version = expect
            ev = SR.resolve_expect_version(expect_version,
                                           env=None if use_env else {})
            EVENTS.append("dev")
            self.ident, self.seq_ok, self.seq_why = self._gate(ev, allow_seq)
            self.ddr_off = chan * HW.CH_STRIDE

        def rd(self, a):
            self.n_rd += 1
            READS.append(a)
            if a == HW.S_SEQ_CAPS:
                EVENTS.append("seq_caps_read")
            return regs.get(a, HW.SEQ_CSR_UNMAPPED)

        wr = trip("wr")
        dma_write = trip("dma_write")
        dma_read = trip("dma_read")
        dma_verify = trip("dma_verify")
        dma_write_chan = trip("dma_write_chan")
        dma_read_chan = trip("dma_read_chan")
        dma_verify_chan = trip("dma_verify_chan")
    MockDev.__name__ = f"MockDev_{caps_word:08x}"
    return MockDev


# ======================================================================
# seq_run fixtures: the R-c synthetic REPACKED artifact (real MVGO/MOVX/MOVY
# records at nch=4), in four manifests
# ======================================================================
def _hist(recs):
    return {SF.OP_NAME[o]: sum(1 for r in recs if r.opcode == o)
            for o in sorted(SF.ALL_OPS) if any(r.opcode == o for r in recs)}


def make_fixture(d, mask=False, man_caps=None):
    os.makedirs(d)
    p = SR.write_synth_repack_artifact(d)
    meta = json.load(open(p + ".seq.json"))
    recs = SF.unpack_stream(open(p + ".seq", "rb").read())
    first = None
    if mask:
        chan, out = None, []
        for i, r in enumerate(recs):
            if r.opcode == SF.OP_MVGO:
                chan = (r.flags >> SF.CHAN_SHIFT) & 3
            if r.opcode == SF.OP_FENCE:
                assert chan is not None
                r = SF.Rec(SF.OP_FENCE, target=1 << chan)
                first = i if first is None else first
            out.append(r)
        recs = out
    stream = SF.pack_stream(recs)
    with open(p + ".seq", "wb") as f:
        f.write(stream)
    meta["stream_sha256"] = hashlib.sha256(stream).hexdigest()
    meta["opcode_histogram"] = _hist(recs)
    meta.setdefault("loop_structurally_safe", False)   # main() reports it
    if man_caps is not None:
        meta["seq_isa"] = "2.3"
        meta["caps"] = list(man_caps)
    with open(p + ".seq.json", "w") as f:
        json.dump(meta, f, indent=1)
    return p, first


def run_seq(argv, dev_cls, ltmp, tag):
    del EVENTS[:]
    del READS[:]
    saved = (SR.Dev, SR.upload, sys.argv)

    def trip_upload(*a, **k):
        EVENTS.append("upload")
        raise _Tripped("upload")

    SR.Dev, SR.upload = dev_cls, trip_upload
    sys.argv = (["seq_run.py"] + argv
                + ["--lock", os.path.join(ltmp, "lock_" + tag)])
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            SR.main()
        outcome = "returned"
    except SystemExit as e:
        outcome = f"exit {e.code!r}"
    except _Tripped as t:
        outcome = f"tripped {t}"
    except Exception as e:                                   # noqa: BLE001
        outcome = f"raised {type(e).__name__}: {e}"
    finally:
        SR.Dev, SR.upload, sys.argv = saved
    return outcome, list(EVENTS), buf.getvalue()


def loaded(res):
    o, ev, _ = res
    return o == "tripped upload" and ev[-1] == "upload"


def refused_before_dma(res):
    o, ev, _ = res
    return (not o.startswith("tripped") and o not in ("returned", "exit 0",
                                                       "exit None")
            and not any(e in ev for e in ("upload", "wr", "dma_write",
                                          "dma_write_chan", "dma_read",
                                          "dma_verify", "dma_read_chan",
                                          "dma_verify_chan")))


def say(tag, res):
    o, ev, out = res
    tail = [ln for ln in (out + "\n" + o).splitlines() if ln.strip()][-3:]
    print(f"    {tag}: outcome {o[:160]!r}; events {ev}")
    for ln in tail:
        print(f"      | {ln[:200]}")


def seq_run_cases(tmp, ltmp):
    print("=== seq_run: the real load path (main) on mock SEQ windows")
    p_r0, _ = make_fixture(os.path.join(tmp, "r0"))
    p_r1, first = make_fixture(os.path.join(tmp, "r1"), mask=True,
                               man_caps=["R1"])
    p_r1e, _ = make_fixture(os.path.join(tmp, "r1e"), mask=True,
                            man_caps=[])
    p_r2m, _ = make_fixture(os.path.join(tmp, "r2m"), man_caps=["R2"])
    nmask = sum(1 for r in SF.unpack_stream(open(p_r1 + ".seq", "rb").read())
                if r.opcode == SF.OP_FENCE and r.target)
    print(f"    fixtures: r0 / r1 ({nmask} masked FENCEs, first at record "
          f"{first}) / r1 manifest [] / r0 manifest [R2]; SEQ_CAPS words "
          f"R1 {W_R1:#010x}, old {W_OLD:#010x}")
    # SR11a fix 2: after SR7 the gate compares SEQ_CAPS to the VERSION's row,
    # so the R1 word lives on the R1 bitstream's VERSION (V_R1, named)
    D1, D0, DB = (make_dev(W_R1, version=V_R1, expect=V_R1), make_dev(W_OLD),
                  make_dev(W_BAD))

    r = run_seq(["--prefix", p_r1], D1, ltmp, "a")
    say("(a) r1 on R1", r)
    check("a", "an r1 stream LOADS through seq_run.main on a 0xFAB1CA01 mock",
          loaded(r), r[0])
    check("a", "... and SEQ_CAPS was read before the upload",
          "seq_caps_read" in r[1]
          and r[1].index("seq_caps_read") < r[1].index("upload")
          if loaded(r) else False, str(r[1]))

    r = run_seq(["--prefix", p_r1], D0, ltmp, "b")
    say("(b) r1 on old", r)
    check("b", "the r1 stream is REFUSED on a 0xDEADC0DE mock, before any "
               "DMA (upload tripwire untouched)", refused_before_dma(r),
          r[0])
    msg = r[0] + r[2]
    check("b", f"the refusal is the validator's and names the first masked "
               f"FENCE (record {first})",
          "FENCE" in msg and f"rec {first}" in msg, msg[-200:])
    check("b2", "the refusal is DEVICE-keyed: SEQ_CAPS was read first",
          "seq_caps_read" in r[1], str(r[1]))

    for nm, D in (("R1", D1), ("old", D0)):
        r = run_seq(["--prefix", p_r0], D, ltmp, "c" + nm)
        say(f"(c) r0 on {nm}", r)
        check("c", f"a shipped-form (r0) stream loads on the {nm} mock",
              loaded(r), r[0])
        check("c2", f"... with SEQ_CAPS read ({nm})",
              "seq_caps_read" in r[1], str(r[1]))

    r = run_seq(["--prefix", p_r1e], D0, ltmp, "d0")
    say("(d) r1 manifest [] on old", r)
    check("d", "r1 with manifest caps [] still REFUSES on 0xDEADC0DE "
               "(before any DMA)", refused_before_dma(r), r[0])
    r = run_seq(["--prefix", p_r1e], D1, ltmp, "d1")
    say("(d) r1 manifest [] on R1", r)
    check("d", "r1 with manifest caps [] still LOADS on 0xFAB1CA01 (the "
               "manifest is not the key)", loaded(r), r[0])

    r = run_seq(["--prefix", p_r2m], D1, ltmp, "e")
    say("(e) manifest [R2] on R1", r)
    check("e", "a manifest claiming caps [R2] on a 0xFAB1CA01 device is "
               "REFUSED before any DMA", refused_before_dma(r), r[0])
    check("e", "... BY NAME (the message names R2)",
          "R2" in (r[0] + r[2]).split("REFUS", 1)[-1]
          if refused_before_dma(r) else False, (r[0] + r[2])[-200:])

    # (l) --caps: board-free caps for --dry-run only
    ap = SR._argparser()
    try:
        c0 = ap.parse_args(["--prefix", "x"]).caps
        c1 = ap.parse_args(["--prefix", "x", "--caps", "R1"]).caps
        ok = (not c0) and c1 == frozenset({"R1"})
    except Exception as e:                                   # noqa: BLE001
        ok, c0, c1 = False, repr(e), None
    check("l", "--caps defaults to the empty set; --caps R1 parses to {R1}",
          ok, f"{c0!r} / {c1!r}")
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            ap.parse_args(["--prefix", "x", "--caps", "R9"])
        bad = False
    except SystemExit:
        bad = True
    check("l", "--caps R9 (unknown) is an argparse error", bad)
    r = run_seq(["--prefix", p_r1, "--caps", "R1"], D1, ltmp, "l1")
    say("(l) SEQ run with --caps", r)
    check("l", "--caps on a SEQ run (not --dry-run) is refused before any "
               "DMA (a run validates at the DEVICE's caps)",
          refused_before_dma(r) and "--caps" in (r[0] + r[2]), r[0])
    r = run_seq(["--prefix", p_r1, "--dry-run"], D1, ltmp, "l2")
    say("(l) dry-run r1, no --caps", r)
    check("l", "--dry-run of an r1 stream without --caps is refused (the "
               "board-free default is the EMPTY set)",
          refused_before_dma(r) and "FENCE" in (r[0] + r[2]), r[0])
    check("l", "... and the dry-run never read SEQ_CAPS (the SEQ window is "
               "untouched)", "seq_caps_read" not in r[1], str(r[1]))
    r = run_seq(["--prefix", p_r1, "--dry-run", "--caps", "R1"], D1, ltmp,
                "l3")
    say("(l) dry-run r1 --caps R1", r)
    # fix round 1 (I-1, controller ruling): "no path uploads an r1 stream
    # without a device read" is LITERAL -- --dry-run with a non-empty --caps
    # validates + relocates and uploads NOTHING (no upload, no DMA of any
    # kind), exiting 0
    _dma = ("upload", "wr", "dma_write", "dma_write_chan", "dma_read",
            "dma_verify", "dma_read_chan", "dma_verify_chan")
    check("l", "--dry-run --caps R1 uploads NOTHING: no upload / DMA "
               "tripwire fires, exit 0",
          r[0] in ("exit 0", "exit None", "returned")
          and not any(e in r[1] for e in _dma), r[0] + " " + str(r[1]))
    check("l", "... it still VALIDATED at the typed caps {R1} and RELOCATED, "
               "and says so ", "VALIDATED at capabilities ['R1']" in r[2]
          and "RELOCATION:" in r[2]
          and "validated only, nothing uploaded" in r[2], r[2][-300:])
    check("l", "... and never read SEQ_CAPS", "seq_caps_read" not in r[1],
          str(r[1]))

    # (m) Dev.seq_caps() itself
    try:
        got = {}
        for nm, D in (("old", D0), ("R1", D1)):
            del EVENTS[:]
            got[nm] = D().seq_caps()
        ok = got == {"old": frozenset(), "R1": frozenset({"R1"})}
    except Exception as e:                                   # noqa: BLE001
        ok, got = False, repr(e)
    check("m", "Dev.seq_caps(): 0xDEADC0DE -> {}, 0xFAB1CA01 -> {R1}", ok,
          str(got))
    try:
        d = D1(allow_seq=False)
        del EVENTS[:]
        try:
            d.seq_caps()
            ok = False
        except SystemExit:
            ok = "seq_caps_read" not in EVENTS
    except Exception as e:                                   # noqa: BLE001
        ok = False
        print(f"      | {e!r}")
    check("m", "a closed SEQ gate refuses seq_caps() without reading 0x64",
          ok)
    r = run_seq(["--prefix", p_r0], DB, ltmp, "m3")
    say("(m) unknown caps bit", r)
    # SR11a fix 2: since SR7 the identity gate compares the RAW SEQ_CAPS
    # word against the VERSION's row first, so main() refuses 0xFAB1CA08 by
    # WORD before seq_caps() decodes it; the by-bit refusal is the decoder's
    # (hwmap.seq_caps_set), checked directly
    check("m", "an unknown SEQ_CAPS bit (0xFAB1CA08) is refused before any "
               "DMA, by the gate's word compare",
          refused_before_dma(r) and "0xfab1ca08" in (r[0] + r[2]).lower(),
          r[0])
    try:
        HW.seq_caps_set(W_BAD)
        ok, why = False, "decoded"
    except ValueError as e:
        ok, why = "bit 3" in str(e), str(e)
    check("m", "... and the decoder refuses it by bit (bit 3)", ok, why[:120])


# ======================================================================
# chat_seq: main() on mocks (9B, --nch 4)
# ======================================================================
def chat_cases(ltmp):
    print("=== chat_seq: main() on mock SEQ windows (FABLE5_MODEL="
          f"{os.environ.get('FABLE5_MODEL')})")
    import chat_seq as CS
    check("setup", "chat_seq imported at FABLE5_MODEL=9b",
          CS.MODEL_TAG == "9b", CS.MODEL_TAG)
    D1, D0 = make_dev(W_R1, version=V_R1, expect=V_R1), make_dev(W_OLD)
    CAPT = {}

    def run_chat(argv, dev_cls, tag, env=None):
        del EVENTS[:]
        del READS[:]
        CAPT.clear()
        saved = (SR.Dev, CS.reorder_model_gate, CS.ChatSession.bring_up,
                 CS.load_template, CS.independent_step_images, sys.argv)
        lt0, isi0 = CS.load_template, CS.independent_step_images

        def gate_stub(sess, log=print, override=None):
            EVENTS.append("B6-stub")
            return {"ok": True, "stub": True, "diff": []}

        def bring_up_trip(self):
            EVENTS.append("bring_up")
            CAPT["sess"] = self
            raise _Tripped("bring_up")

        def lt_spy(*a, **k):
            EVENTS.append(("load_template", k.get("caps")))
            return lt0(*a, **k)

        def isi_spy(*a, **k):
            EVENTS.append(("independent_step_images", k.get("caps")))
            return isi0(*a, **k)

        SR.Dev = dev_cls
        CS.reorder_model_gate = gate_stub
        CS.ChatSession.bring_up = bring_up_trip
        CS.load_template, CS.independent_step_images = lt_spy, isi_spy
        sys.argv = (["chat_seq.py"] + argv
                    + ["--lock", os.path.join(ltmp, "chat_" + tag)])
        oenv = dict(os.environ)
        os.environ.update(env or {})
        buf = io.StringIO()
        t0 = time.monotonic()
        try:
            with contextlib.redirect_stdout(buf):
                CS.main()
            outcome = "returned"
        except SystemExit as e:
            outcome = f"exit {e.code!r}"
        except _Tripped as t:
            outcome = f"tripped {t}"
        except Exception as e:                               # noqa: BLE001
            outcome = f"raised {type(e).__name__}: {e}"
            buf.write(traceback.format_exc())
        finally:
            (SR.Dev, CS.reorder_model_gate, CS.ChatSession.bring_up,
             CS.load_template, CS.independent_step_images, sys.argv) = saved
            os.environ.clear()
            os.environ.update(oenv)
        ev = list(EVENTS)
        o = outcome
        short = [e if isinstance(e, str) else f"{e[0]}(caps={e[1]!r})"
                 for e in ev]
        tail = [ln for ln in buf.getvalue().splitlines() if ln.strip()][-4:]
        print(f"    {tag}: outcome {o[:160]!r} "
              f"({time.monotonic() - t0:.0f} s); events {short}")
        for ln in tail:
            print(f"      | {ln[:200]}")
        return o, ev, buf.getvalue()

    def no_dma(ev):
        return not any(e in ev for e in ("bring_up", "wr", "dma_write",
                                         "dma_write_chan", "dma_read",
                                         "dma_verify", "dma_read_chan",
                                         "dma_verify_chan"))

    base = ["--nch", "4", "--prompt", "hi", "--ntok", "1"]

    # (g0) the control: the default (r0, form B) session on the old mock
    o, ev, out = run_chat(base, D0, "g0")
    check("g0", "control: the default --nch 4 session (r0, form B) LOADS "
                "on the 0xDEADC0DE mock", o == "tripped bring_up", o)
    s0 = CAPT.get("sess")
    check("g0", "... its form-B images still equal the S1P pins "
                "(REORDER_B_IMAGES)",
          s0 is not None and all(
              hashlib.sha256(s0.images[k].a.data).hexdigest()
              == CS.REORDER_B_IMAGES[k][0] for k in ("lite", "full")))

    # (f) r1 on the old mock
    o, ev, out = run_chat(base + ["--seq-rtl", "r1"], D0, "f")
    check("f", "`chat_seq --seq-rtl r1` on the 0xDEADC0DE mock REFUSES "
               "(exit 4) at open_board, before any upload",
          o == "exit 4" and "dev" in ev and no_dma(ev), o)
    check("f", "... device-keyed (SEQ_CAPS read) and naming the masked "
               "FENCE", "seq_caps_read" in ev and "FENCE" in out, "")

    # (g) r1 on the R1 mock — the positive case, the mock-device route
    o, ev, out = run_chat(base + ["--seq-rtl", "r1"], D1, "g")
    check("g", "`chat_seq --seq-rtl r1` LOADS on the 0xFAB1CA01 mock "
               "(reaches bring_up, the first upload)",
          o == "tripped bring_up", o)
    after = ev[ev.index("seq_caps_read") + 1:] if "seq_caps_read" in ev \
        else []
    R1 = frozenset({"R1"})
    check("g", "the device's caps {R1} reach chat_seq.load_template (the "
               ":477 validate_stream site) after open_board read them",
          ("load_template", R1) in after, str(after[:4]))
    check("g", "... and chat_seq.independent_step_images (the :518 site)",
          ("independent_step_images", R1) in after, str(after[:4]))
    s1 = CAPT.get("sess")
    if s1 is not None:
        nm = {k: sum(1 for r in s1.images[k].recs
                     if r.opcode == SF.OP_FENCE and r.target & 0xF)
              for k in ("preamble", "lite", "full")}
        refused = {}
        for k in ("lite", "full"):
            try:
                SF.validate_stream(s1.images[k].recs)
                refused[k] = False
            except SF.SeqValidationError:
                refused[k] = True
        print(f"      masked FENCEs per image {nm}; refused at the empty "
              f"set {refused}; session caps {getattr(s1, 'caps', None)!r}")
        check("g", "the three images it loads carry masked FENCEs (lite and "
                   "full) and are REFUSED at the empty set",
              nm["lite"] > 0 and nm["full"] > 0 and all(refused.values()))
        check("g", "the session's validation caps are the device's {R1}",
              getattr(s1, "caps", None) == R1)
        check("g", "its lite/full images equal the r1 pins",
              all(hashlib.sha256(s1.images[k].a.data).hexdigest()
                  == CS.REORDER_B_R1_IMAGES[k][0] for k in ("lite", "full")))
    else:
        check("g", "an r1 session was built", False)

    # (i) refusals before the lock / board
    for tag, extra, env, want in (
            ("iA", ["--seq-rtl", "r1", "--reorder", "A"], None, "exit 4"),
            ("ioff", ["--seq-rtl", "r1", "--reorder", "off"], None,
             "exit 4"),
            ("ienv", [], {"FABLE5_SEQ_RTL": "r1", "FABLE5_REORDER": "off"},
             "exit 4"),
            ("ir9", ["--seq-rtl", "r9"], None, "exit 2"),
            ("ibad", [], {"FABLE5_SEQ_RTL": "bogus"}, "exit 2")):
        with contextlib.redirect_stderr(io.StringIO()) as er:
            o, ev, out = run_chat(base + extra, D1, tag, env=env)
        msg = out + er.getvalue()
        good = (o == want and "dev" not in ev
                and (want != "exit 4" or "seq-rtl" in msg.lower()
                     or "seq_rtl" in msg.lower()))
        check("i", f"refused before the board: {extra or env} -> {want}",
              good, f"{o}; {msg.strip().splitlines()[-1:]}")

    # (k) the model gates run the R1 model at r1
    import seq_model as SM
    seen = []

    class _RecExec(object):
        def __init__(self, recs, *a, **k):
            seen.append(k.get("caps", frozenset()))
            self.out_fifo = []

        def run(self, max_steps=None):
            return self

    if s1 is not None and s0 is not None:
        real = SM.SeqExec
        SM.SeqExec = _RecExec
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                CS.reorder_model_gate(s1)
            b6 = list(seen)
            del seen[:]
            with contextlib.redirect_stdout(io.StringIO()):
                v = CS.SeqModelVerifier(s1, log=lambda *x: None)
                v._run(s1.images["lite"], 760, 0)
            ver = list(seen)
            del seen[:]
            with contextlib.redirect_stdout(io.StringIO()):
                CS.reorder_model_gate(s0)
            b6_0 = list(seen)
        except Exception as e:                               # noqa: BLE001
            b6, ver, b6_0 = [repr(e)], [], []
        finally:
            SM.SeqExec = real
        print(f"      B6 SeqExec caps (r1 session): {b6}; verifier: {ver}; "
              f"B6 (r0 session): {b6_0}")
        check("k", "B6 at r1: shipped side at the empty set, reordered side "
                   "at {R1}", b6 == [frozenset()] * 3 + [R1] * 3, str(b6))
        check("k", "SeqModelVerifier at r1 runs SeqExec at {R1}",
              ver == [R1] * len(ver) and len(ver) >= 1, str(ver))
        check("k", "B6 at r0 runs both sides at the empty set",
              b6_0 == [frozenset()] * 6, str(b6_0))
    else:
        check("k", "sessions for the model-gate caps check", False)


def serve_case():
    print("=== serve: BoardBackend._args() pins seq_rtl")
    import serve as SV

    class _Opts(object):
        nch = 4
        template = None

        def __getattr__(self, n):
            return None

    try:
        a = SV.BoardBackend(_Opts())._args()
        got = getattr(a, "seq_rtl", "<absent>")
    except Exception as e:                                   # noqa: BLE001
        got = repr(e)
    check("h", "serve's args namespace pins seq_rtl = 'r0' (serve runs the "
               "shipped level)", got == "r0", repr(got))


def main():
    t0 = time.monotonic()
    print(f"SR6 host TDD — FABLE5_MODEL={os.environ.get('FABLE5_MODEL')} "
          f"FABLE5_RS_F={os.environ.get('FABLE5_RS_F')}")
    tmp = tempfile.mkdtemp(prefix="sr6_fx_")
    ltmp = tempfile.mkdtemp(prefix="sr6_lock_")
    try:
        for fn, a in ((seq_run_cases, (tmp, ltmp)), (serve_case, ()),
                      (chat_cases, (ltmp,))):
            try:
                fn(*a)
            except Exception as e:                           # noqa: BLE001
                traceback.print_exc()
                check(fn.__name__, "block ran to the end", False, repr(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(ltmp, ignore_errors=True)
    cases = {}
    for c, ok in RESULTS:
        p, f = cases.get(c, (0, 0))
        cases[c] = (p + ok, f + (not ok))
    print("per case: " + ", ".join(f"({c}) {p}/{p + f}"
                                   for c, (p, f) in cases.items()))
    print(f"SR6_HOST_TDD: {NPASS} passed, {NFAIL} failed "
          f"({time.monotonic() - t0:.0f} s) -> "
          + ("PASS" if NFAIL == 0 else "FAIL"))
    return NFAIL == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
