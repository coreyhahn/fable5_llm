#!/usr/bin/env python3
"""sr13b_host_tdd.py — Task SR13b of the sequencer RTL round: the host's R2
capability (SEQ_ISA v2.3 B17.2), plus the keyless-manifest hardening the
SR11a round-3 re-review asked for (the controller's binding addendum).

    FABLE5_MODEL=9b FABLE5_RS_F=7 /home/cah/.venv/bin/python \
        evidence/qwen9b/sr/sr13b_host_tdd.py

BOARD-FREE, on SR6's mock SEQ window (evidence/qwen9b/sr/sr6_host_tdd.py
make_dev / run_seq: the REAL seq_run.Dev identity gate over a scripted CSR
map, every write / DMA method a tripwire, seq_run.upload and
chat_seq.ChatSession.bring_up tripwires too).  "LOADS" = reached an upload
tripwire (every host check before the first DDR byte passed); "REFUSED
before any DMA" = a non-zero exit with no tripwire touched.

The three SEQ_CAPS words come from sw/hwmap.py (the ONE definition, B17.0):
  0xDEADC0DE  HW.SEQ_CSR_UNMAPPED — build_041 (VERSION 0xC973C18A), the
              empty set;
  0xFAB1CA01  HW.seq_caps_word({"R1"}) — build_044_r1_incr (0xE3C2FF1E),
              R1 only;
  0xFAB1CA03  HW.seq_caps_word({"R1", "R2"}) — NO such bitstream exists
              yet, so its VERSION row (0x2B2B2B2B, SHAPE isa=2) is
              injected into seq_run.SEQ_VERSIONS / hwmap.SHAPE_ISA_BY_VERSION
              by this test only and removed after (SR11a fix 2's (c)
              convention).

The r2 seq_run fixture is SR6's R-c synthetic repacked artifact with its
FENCEs masked (the r1 fixture) and its FIRST group banked: MOVX target =
the XWIN bank-1 word 1536, MVGO SHAPE |= XBANK|RBANK, MOVY target[15:4] =
the RES bank-1 row 2048 (B17.2).  It declares shape_isa 2 (the layout it is
encoded in).  Its manifest comes in four forms: honest (seq_isa 2.3, caps
[R1, R2]); mislabelled caps [R1]; mislabelled seq_isa 2.2 (no caps key);
and NO capability claim at all (neither key).

Cases:
  seq_run (the real main() on the mocks)
  (a) the honest r2 stream LOADS on the 0xFAB1CA03 mock; SEQ_CAPS was read
      before the upload
  (b) REFUSED on the 0xFAB1CA01 mock (R1-only: the not-fail-closed hazard
      of spec §1.2) before any DMA, by the validator (names R2 and the
      first banked record), device-keyed (SEQ_CAPS read)
  (c) REFUSED on the 0xDEADC0DE mock before any DMA, device-keyed
  (d) mislabelled manifests (caps [R1]; seq_isa 2.2) are still REFUSED on
      0xFAB1CA01, and still LOAD on 0xFAB1CA03 (the manifest is not the key)
  (e) no capability claim: REFUSED on 0xFAB1CA01, LOADS on 0xFAB1CA03 —
      the validator decides from the records and the device's caps
  (f) --dry-run: --caps R1 refuses the r2 stream; --caps R1,R2 validates +
      relocates and uploads nothing (SR6 fix 1's rule)
  keyless (the addendum; seq_run SEQ runs and chat_seq's admit path)
  (K1) a keyless isa=2 artifact (the fixture without its shape_isa key)
       named as build_035 (--expect-version 54443b9f, isa=1) is REFUSED
       before any DMA, naming the missing `shape_isa` key
  (K2) the frozen 2B W8 artifact (isa=1, keyless) at build_035 still LOADS
  (K3) a keyless artifact at build_041 (isa=2) is REFUSED naming the key
  (K4) a 9B artifact (declared shape_isa 2) LOADS at build_041, at
       build_044_r1_incr and on the R2 mock
  (K5) chat_seq's admit path: admit_caps REFUSES a keyless non-frozen
       template at a device layout of isa=1 and at isa=2, naming the key,
       before its first validation; the frozen W8 template (keyless) at
       isa=1 passes the key check
  chat_seq (the real main() on the mocks, 9B --nch 4; B6 stubbed — the
  real r2 B6 replay is its own run, --reorder-check)
  (g) `--seq-rtl r2` on the 0xFAB1CA01 mock: exit 4 at open_board, before
      any upload, SEQ_CAPS read, the message names R2
  (h) `--seq-rtl r2` on the 0xDEADC0DE mock: exit 4 likewise
  (i) THE POSITIVE CASE: `--seq-rtl r2` LOADS on the 0xFAB1CA03 mock; the
      device's caps {R1, R2} reach load_template and
      independent_step_images after the SEQ_CAPS read; the lite/full
      images carry bank fields and are REFUSED at {R1} and at {}; they
      equal the r2 pins (REORDER_B_R2_IMAGES); the session's caps are
      {R1, R2}.  These images have NO manifest at all.
  (j) refusals before the board: r2 with --reorder A / off, and
      FABLE5_SEQ_RTL=r2 with FABLE5_REORDER=off (exit 4, naming
      --seq-rtl); FABLE5_SEQ_RTL=r2 alone parses to r2
  (k) the model gates at r2: B6 hands SeqExec the empty set (shipped side)
      and {R1, R2} (reordered side); SeqModelVerifier runs at {R1, R2}
  (h2) serve's namespace still pins seq_rtl = "r0"

RED PREDICTION (written before the first run, against 966cbcf):
  PASS — (a)–(f), all 15 checks: seq_run's admission has been device-keyed
  since SR6 and the validator refuses every bank field without R2 since
  SR11a, so the r2 matrix needs no seq_run change (this RED says so);
  (K2) 1, (K4) 3, (K5)'s frozen-W8 check 1, (h2) 1, setup 2 (the
  0xFAB1CA03 word; chat_seq imported at 9B).
  FAIL — (K1) 1 and (K3) 1 (a keyless artifact loads today), (K5)'s two
  refusal checks, (g) 2, (h) 1, (i) 6, (j) 4 (chat_seq has no r2 level:
  argparse exit 2, the env value is an error), (k) 2.
  Totals: 23 passed / 19 failed of 42.
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sr6_host_tdd as H6                                      # noqa: E402
from sr6_host_tdd import SR, SF, HW                            # noqa: E402

ROOT = H6.ROOT
W5 = os.path.join(ROOT, "tb", "scripts", "w5", "model_w8_2b_s1.e")
V035, V041, V044 = 0x54443B9F, 0xC973C18A, 0xE3C2FF1E
VMOCK_R2 = 0x2B2B2B2B
W_OLD = HW.SEQ_CSR_UNMAPPED
W_R1 = HW.seq_caps_word({"R1"})
W_R12 = HW.seq_caps_word({"R1", "R2"})
R12 = frozenset({"R1", "R2"})
DMA = ("upload", "bring_up", "wr", "dma_write", "dma_write_chan", "dma_read",
       "dma_verify", "dma_read_chan", "dma_verify_chan")
RESULTS = []


def check(case, name, cond, detail=""):
    RESULTS.append((case, bool(cond)))
    print(f"  [{case}] {'PASS' if cond else 'FAIL'} {name}"
          + (f"  -- {detail}" if detail else ""))


def msg(res):
    return res[0] + "\n" + res[2]


def inject_r2_row():
    SR.SEQ_VERSIONS[VMOCK_R2] = (HW.SHAPE_ISA_9B, "MOCK R1+R2 (SR13b test "
                                 "only)", W_R12)
    HW.SHAPE_ISA_BY_VERSION[VMOCK_R2] = HW.SHAPE_ISA_9B


def drop_r2_row():
    SR.SEQ_VERSIONS.pop(VMOCK_R2, None)
    HW.SHAPE_ISA_BY_VERSION.pop(VMOCK_R2, None)


def _rewrite(p, recs=None, meta_fn=None):
    """Rewrite prefix p's stream (recs) and/or manifest (meta_fn(meta))."""
    meta = json.load(open(p + ".seq.json"))
    if recs is not None:
        stream = SF.pack_stream(recs)
        open(p + ".seq", "wb").write(stream)
        meta["stream_sha256"] = hashlib.sha256(stream).hexdigest()
        meta["opcode_histogram"] = H6._hist(recs)
    if meta_fn is not None:
        meta_fn(meta)
    json.dump(meta, open(p + ".seq.json", "w"), indent=1)


def r2_fixture(d, claim):
    """The r1 fixture with its first MOVX/MVGO/FENCE/MOVY group banked.
    claim: "honest" | "r1" | "isa22" | "none"."""
    p, _ = H6.make_fixture(d, mask=True, man_caps=["R1"])
    recs = SF.unpack_stream(open(p + ".seq", "rb").read())
    i = next(k for k, r in enumerate(recs) if r.opcode == SF.OP_MOVX)
    assert [recs[i + j].opcode for j in range(4)] == [
        SF.OP_MOVX, SF.OP_MVGO, SF.OP_FENCE, SF.OP_MOVY]
    x, g, y = recs[i], recs[i + 1], recs[i + 3]
    recs[i] = SF.Rec(x.opcode, x.flags, SF.XBANK_WORD, x.imm32, x.addr_lo,
                     x.len_or_addr_hi)
    recs[i + 1] = SF.Rec(g.opcode, g.flags, g.target,
                         g.imm32 | SF.SHAPE_XBANK | SF.SHAPE_RBANK,
                         g.addr_lo, g.len_or_addr_hi)
    recs[i + 3] = SF.Rec(y.opcode, y.flags,
                         (SF.RBANK_ROW << 4) | (y.target & 0xF), y.imm32,
                         y.addr_lo, y.len_or_addr_hi)

    def mf(m):
        m["shape_isa"] = HW.SHAPE_ISA_9B
        m.pop("caps", None)
        m.pop("seq_isa", None)
        if claim == "honest":
            m["seq_isa"], m["caps"] = "2.3", ["R1", "R2"]
        elif claim == "r1":
            m["seq_isa"], m["caps"] = "2.3", ["R1"]
        elif claim == "isa22":
            m["seq_isa"] = "2.2"
    _rewrite(p, recs, mf)
    return p, i


def keyed_fixture(d, isa):
    """SR6's r0 fixture; isa None = the shape_isa key REMOVED."""
    p, _ = H6.make_fixture(d)

    def mf(m):
        m.pop("shape_isa", None)
        if isa is not None:
            m["shape_isa"] = isa
    _rewrite(p, None, mf)
    return p


# ======================================================================
def seq_cases(tmp, ltmp):
    print("=== seq_run: an r2 stream on mock SEQ windows")
    check("setup", "the R1+R2 SEQ_CAPS word is 0xFAB1CA03",
          W_R12 == 0xFAB1CA03, f"{W_R12:#010x}")
    D041 = H6.make_dev(W_OLD, version=V041)
    D044 = H6.make_dev(W_R1, version=V044, expect=V044)
    DR2 = H6.make_dev(W_R12, version=VMOCK_R2, expect=VMOCK_R2)
    ph, first = r2_fixture(os.path.join(tmp, "r2h"), "honest")
    p1, _ = r2_fixture(os.path.join(tmp, "r2r1"), "r1")
    p22, _ = r2_fixture(os.path.join(tmp, "r2i22"), "isa22")
    pn, _ = r2_fixture(os.path.join(tmp, "r2n"), "none")
    print(f"    r2 fixture: first banked record {first} (MOVX word "
          f"{SF.XBANK_WORD}, MVGO XBANK|RBANK, MOVY row {SF.RBANK_ROW})")

    # (a) loads on CA03
    r = H6.run_seq(["--prefix", ph], DR2, ltmp, "a")
    H6.say("(a) r2 on 0xFAB1CA03", r)
    check("a", "the r2 stream LOADS on the 0xFAB1CA03 mock", H6.loaded(r),
          r[0][:200])
    check("a", "... SEQ_CAPS read before the upload",
          H6.loaded(r) and "seq_caps_read" in r[1]
          and r[1].index("seq_caps_read") < r[1].index("upload"), str(r[1]))

    # (b) refused on CA01
    r = H6.run_seq(["--prefix", ph], D044, ltmp, "b")
    H6.say("(b) r2 on 0xFAB1CA01", r)
    check("b", "REFUSED on the 0xFAB1CA01 (R1-only) mock before any DMA",
          H6.refused_before_dma(r), r[0][:200])
    check("b", f"... by the validator: names R2 and rec {first}",
          "R2" in msg(r) and f"rec {first}" in msg(r), r[0][:200])
    check("b", "... device-keyed (SEQ_CAPS was read)",
          "seq_caps_read" in r[1], str(r[1]))

    # (c) refused on DEADC0DE
    r = H6.run_seq(["--prefix", ph], D041, ltmp, "c")
    H6.say("(c) r2 on 0xDEADC0DE", r)
    check("c", "REFUSED on the 0xDEADC0DE mock before any DMA",
          H6.refused_before_dma(r), r[0][:200])
    check("c", "... device-keyed (SEQ_CAPS was read)",
          "seq_caps_read" in r[1], str(r[1]))

    # (d) mislabelled manifests
    for tag, p in (("caps [R1]", p1), ("seq_isa 2.2", p22)):
        r = H6.run_seq(["--prefix", p], D044, ltmp, "d1" + tag[:4])
        H6.say(f"(d) {tag} on 0xFAB1CA01", r)
        check("d", f"mislabelled manifest ({tag}) still REFUSED on "
                   f"0xFAB1CA01 before any DMA, naming R2",
              H6.refused_before_dma(r) and "R2" in msg(r), r[0][:200])
        r = H6.run_seq(["--prefix", p], DR2, ltmp, "d3" + tag[:4])
        check("d", f"... and ({tag}) still LOADS on 0xFAB1CA03",
              H6.loaded(r), r[0][:200])

    # (e) no capability claim
    r = H6.run_seq(["--prefix", pn], D044, ltmp, "e1")
    H6.say("(e) no claim on 0xFAB1CA01", r)
    check("e", "no capability claim: REFUSED on 0xFAB1CA01 before any DMA",
          H6.refused_before_dma(r) and "R2" in msg(r), r[0][:200])
    r = H6.run_seq(["--prefix", pn], DR2, ltmp, "e3")
    check("e", "no capability claim: LOADS on 0xFAB1CA03", H6.loaded(r),
          r[0][:200])

    # (f) dry-run
    r = H6.run_seq(["--prefix", ph, "--dry-run", "--caps", "R1",
                    "--shape-isa", "2"], DR2, ltmp, "f1")
    check("f", "--dry-run --caps R1 REFUSES the r2 stream",
          H6.refused_before_dma(r) and "R2" in msg(r), r[0][:200])
    r = H6.run_seq(["--prefix", ph, "--dry-run", "--caps", "R1,R2",
                    "--shape-isa", "2"], DR2, ltmp, "f2")
    check("f", "--dry-run --caps R1,R2 validates + relocates, uploads "
               "nothing, never reads SEQ_CAPS",
          r[0] in ("exit 0", "exit None", "returned")
          and not any(e in r[1] for e in DMA)
          and "seq_caps_read" not in r[1]
          and "validated only, nothing uploaded" in r[2],
          r[0] + " " + str(r[1]))


def keyless_cases(tmp, ltmp):
    print("=== keyless manifests (the addendum)")
    D035 = H6.make_dev(W_OLD, version=V035)
    D041 = H6.make_dev(W_OLD, version=V041)
    D044 = H6.make_dev(W_R1, version=V044, expect=V044)
    DR2 = H6.make_dev(W_R12, version=VMOCK_R2, expect=VMOCK_R2)
    pk = keyed_fixture(os.path.join(tmp, "k2"), None)
    p9 = keyed_fixture(os.path.join(tmp, "k9"), HW.SHAPE_ISA_9B)

    r = H6.run_seq(["--prefix", pk, "--expect-version", "54443b9f"], D035,
                   ltmp, "K1")
    H6.say("(K1) keyless isa=2 at build_035", r)
    check("K1", "a keyless isa=2 artifact named as build_035 is REFUSED "
                "before any DMA, naming the missing shape_isa key",
          H6.refused_before_dma(r) and "shape_isa" in r[0]
          and "key" in r[0], r[0][:240])
    r = H6.run_seq(["--prefix", W5, "--four-chan", "--expect-version",
                    "54443b9f"], D035, ltmp, "K2")
    H6.say("(K2) frozen W8 at build_035", r)
    check("K2", "the frozen 2B W8 artifact (isa=1, keyless) at build_035 "
                "still LOADS", H6.loaded(r), r[0][:200])
    r = H6.run_seq(["--prefix", pk], D041, ltmp, "K3")
    H6.say("(K3) keyless at build_041", r)
    check("K3", "a keyless artifact at build_041 (isa=2) is REFUSED before "
                "any DMA, naming the missing shape_isa key",
          H6.refused_before_dma(r) and "shape_isa" in r[0]
          and "key" in r[0], r[0][:240])
    for tag, D, ev in (("build_041", D041, []),
                       ("build_044_r1_incr", D044, []),
                       ("the R2 mock", DR2, [])):
        r = H6.run_seq(["--prefix", p9] + ev, D, ltmp, "K4" + tag[-4:])
        check("K4", f"a 9B artifact (declared shape_isa 2) LOADS at {tag}",
              H6.loaded(r), r[0][:200])

    # (K5) chat_seq's admit path on a stub session
    import chat_seq as CS

    class _Reached(Exception):
        pass

    def stub(prefix, isa):
        s = types.SimpleNamespace(
            args=types.SimpleNamespace(any_template=True),
            prefix=prefix, meta0=json.load(open(prefix + ".seq.json")),
            shape_isa=isa, tmpl_sha=None, geom=None, images={},
            level_caps=frozenset(), seq_rtl="r0", log=lambda *a, **k: None)
        return s

    def admit(s):
        saved = CS.load_template

        def lt(*a, **k):
            raise _Reached("load_template")
        CS.load_template = lt
        try:
            CS.ChatSession.admit_caps(s, frozenset(), word=W_OLD)
            return "returned"
        except _Reached:
            return "reached load_template"
        except CS.ChatSeqError as e:
            return f"ChatSeqError: {e}"
        except Exception as e:                               # noqa: BLE001
            return f"{type(e).__name__}: {e}"
        finally:
            CS.load_template = saved

    for isa in (HW.SHAPE_ISA_PRE_G3, HW.SHAPE_ISA_9B):
        o = admit(stub(pk, isa))
        print(f"    (K5) keyless template at device isa={isa}: {o[:200]}")
        check("K5", f"chat_seq admit_caps REFUSES a keyless non-frozen "
                    f"template at device isa={isa}, naming the key, before "
                    f"its first validation",
              o.startswith("ChatSeqError") and "shape_isa" in o
              and "key" in o, o[:200])
    o = admit(stub(W5, HW.SHAPE_ISA_PRE_G3))
    print(f"    (K5) frozen W8 at isa=1: {o[:200]}")
    check("K5", "... the frozen W8 template (keyless) at isa=1 passes the "
                "key check (reaches load_template)",
          o == "reached load_template", o[:200])


# ======================================================================
def chat_cases(ltmp):
    print("=== chat_seq --seq-rtl r2: main() on mock SEQ windows "
          f"(FABLE5_MODEL={os.environ.get('FABLE5_MODEL')})")
    import chat_seq as CS
    check("setup", "chat_seq imported at FABLE5_MODEL=9b",
          CS.MODEL_TAG == "9b", CS.MODEL_TAG)
    D041 = H6.make_dev(W_OLD, version=V041)
    D044 = H6.make_dev(W_R1, version=V044, expect=V044)
    DR2 = H6.make_dev(W_R12, version=VMOCK_R2, expect=VMOCK_R2)
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
        short = [e if isinstance(e, str) else f"{e[0]}(caps={e[1]!r})"
                 for e in ev]
        tail = [ln for ln in out.splitlines() if ln.strip()][-4:]
        print(f"    {tag}: outcome {outcome[:160]!r} "
              f"({time.monotonic() - t0:.0f} s); events {short}")
        for ln in tail:
            print(f"      | {ln[:220]}")
        return outcome, ev, out

    def no_dma(ev):
        return not any(e in ev for e in DMA)

    base = ["--nch", "4", "--prompt", "hi", "--ntok", "1"]

    # (g) r2 on the R1-only mock
    o, ev, out = run_chat(base + ["--seq-rtl", "r2"], D044, "g")
    check("g", "`chat_seq --seq-rtl r2` on the 0xFAB1CA01 mock REFUSES "
               "(exit 4) at open_board, before any upload",
          o == "exit 4" and "dev" in ev and no_dma(ev), o)
    check("g", "... device-keyed (SEQ_CAPS read) and naming R2",
          "seq_caps_read" in ev and "R2" in out, "")

    # (h) r2 on the empty-set mock
    o, ev, out = run_chat(base + ["--seq-rtl", "r2"], D041, "h")
    check("h", "`chat_seq --seq-rtl r2` on the 0xDEADC0DE mock REFUSES "
               "(exit 4) at open_board, before any upload, SEQ_CAPS read",
          o == "exit 4" and "dev" in ev and no_dma(ev)
          and "seq_caps_read" in ev, o)

    # (i) r2 on the R1+R2 mock — the positive case
    o, ev, out = run_chat(base + ["--seq-rtl", "r2"], DR2, "i")
    check("i", "`chat_seq --seq-rtl r2` LOADS on the 0xFAB1CA03 mock "
               "(reaches bring_up, the first upload)",
          o == "tripped bring_up", o)
    after = ev[ev.index("seq_caps_read") + 1:] if "seq_caps_read" in ev \
        else []
    check("i", "the device's caps {R1, R2} reach load_template and "
               "independent_step_images after open_board read them",
          ("load_template", R12) in after
          and ("independent_step_images", R12) in after, str(after[:4]))
    s2 = CAPT.get("sess")
    if s2 is not None:
        nb, ref1, ref0 = {}, {}, {}
        for k in ("lite", "full"):
            recs = s2.images[k].recs
            nb[k] = sum(1 for r in recs
                        if (r.opcode == SF.OP_MOVX and r.target)
                        or (r.opcode == SF.OP_MOVY and r.target >> 4)
                        or (r.opcode == SF.OP_MVGO and r.imm32
                            & (SF.SHAPE_XBANK | SF.SHAPE_RBANK)))
            for caps, d in (({"R1"}, ref1), (frozenset(), ref0)):
                try:
                    SF.validate_stream(recs, caps=caps,
                                       shape_isa=HW.SHAPE_ISA_9B)
                    d[k] = False
                except SF.SeqValidationError:
                    d[k] = True
        print(f"      bank fields per image {nb}; refused at {{R1}} {ref1};"
              f" at {{}} {ref0}; session caps {getattr(s2, 'caps', None)!r}")
        check("i", "the lite/full images carry bank fields and are REFUSED "
                   "at {R1} and at {}",
              all(nb.values()) and all(ref1.values())
              and all(ref0.values()))
        pins = getattr(CS, "REORDER_B_R2_IMAGES", None) or {}
        check("i", "its lite/full images equal the r2 pins "
                   "(REORDER_B_R2_IMAGES)",
              bool(pins) and all(
                  hashlib.sha256(s2.images[k].a.data).hexdigest()
                  == pins[k][0] for k in ("lite", "full")))
        check("i", "the session's validation caps are the device's {R1, R2}",
              getattr(s2, "caps", None) == R12)
    else:
        for n in ("bank fields", "pins", "session caps"):
            check("i", f"an r2 session was built ({n})", False)
    check("i", "no manifest is involved: chat images carry none (the "
               "session never read a caps claim)",
          s2 is not None and "caps" not in (getattr(s2, "meta0", {}) or {}))

    # (j) refusals before the board
    for tag, extra, env in (
            ("jA", ["--seq-rtl", "r2", "--reorder", "A"], None),
            ("joff", ["--seq-rtl", "r2", "--reorder", "off"], None),
            ("jenv", [], {"FABLE5_SEQ_RTL": "r2", "FABLE5_REORDER": "off"})):
        o, ev, out = run_chat(base + extra, DR2, tag, env=env)
        check("j", f"refused before the board: {extra or env} -> exit 4 "
                   f"naming --seq-rtl",
              o == "exit 4" and "dev" not in ev
              and ("seq-rtl" in out.lower() or "seq_rtl" in out.lower()),
              f"{o}; {out.strip().splitlines()[-1:]}")
    try:
        lv = CS.seq_rtl_default({"FABLE5_SEQ_RTL": "R2"})
    except Exception as e:                                   # noqa: BLE001
        lv = repr(e)
    check("j", "FABLE5_SEQ_RTL=R2 parses to r2", lv == "r2", repr(lv))

    # (k) the model gates at r2
    import seq_model as SM
    seen = []

    class _RecExec(object):
        def __init__(self, recs, *a, **k):
            seen.append(k.get("caps", frozenset()))
            self.out_fifo = []

        def run(self, max_steps=None):
            return self

    if s2 is not None:
        real = SM.SeqExec
        SM.SeqExec = _RecExec
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                CS.reorder_model_gate(s2)
            b6 = list(seen)
            del seen[:]
            with contextlib.redirect_stdout(io.StringIO()):
                v = CS.SeqModelVerifier(s2, log=lambda *x: None)
                v._run(s2.images["lite"], 760, 0)
            ver = list(seen)
        except Exception as e:                               # noqa: BLE001
            b6, ver = [repr(e)], []
        finally:
            SM.SeqExec = real
        print(f"      B6 SeqExec caps (r2 session): {b6}; verifier: {ver}")
        check("k", "B6 at r2: shipped side at the empty set, reordered side "
                   "at {R1, R2}", b6 == [frozenset()] * 3 + [R12] * 3,
              str(b6))
        check("k", "SeqModelVerifier at r2 runs SeqExec at {R1, R2}",
              len(ver) >= 1 and ver == [R12] * len(ver), str(ver))
    else:
        check("k", "an r2 session for the model-gate caps (B6)", False)
        check("k", "an r2 session for the model-gate caps (verifier)", False)


def serve_case():
    print("=== serve: BoardBackend._args() still pins seq_rtl r0")
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
    check("h2", "serve's namespace pins seq_rtl = 'r0'", got == "r0",
          repr(got))


def main():
    t0 = time.monotonic()
    print(f"SR13b host TDD — FABLE5_MODEL={os.environ.get('FABLE5_MODEL')} "
          f"FABLE5_RS_F={os.environ.get('FABLE5_RS_F')}")
    tmp = tempfile.mkdtemp(prefix="sr13b_fx_")
    ltmp = tempfile.mkdtemp(prefix="sr13b_lock_")
    inject_r2_row()
    try:
        for fn, a in ((seq_cases, (tmp, ltmp)), (keyless_cases, (tmp, ltmp)),
                      (serve_case, ()), (chat_cases, (ltmp,))):
            try:
                fn(*a)
            except Exception as e:                           # noqa: BLE001
                traceback.print_exc()
                check(fn.__name__, "block ran to the end", False, repr(e))
    finally:
        drop_r2_row()
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(ltmp, ignore_errors=True)
    by = {}
    for c, ok in RESULTS:
        by.setdefault(c, []).append(ok)
    print("per case: " + "  ".join(f"({c}) {sum(v)}/{len(v)}"
                                   for c, v in by.items()))
    npass = sum(ok for _c, ok in RESULTS)
    print(f"SR13B_HOST_TDD: {npass} passed, {len(RESULTS) - npass} failed "
          f"({time.monotonic() - t0:.0f} s) -> "
          + ("PASS" if npass == len(RESULTS) else "FAIL"))
    return npass == len(RESULTS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
