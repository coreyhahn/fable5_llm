#!/usr/bin/env python3
"""sr11a_fix2_host_tdd.py — SR11a fix round 2 (review I1): the DEVICE-keyed
SHAPE layout at the board-admission call sites.

    FABLE5_MODEL=9b /home/cah/.venv/bin/python \
        evidence/qwen9b/sr/sr11a_fix2_host_tdd.py

BOARD-FREE: every device is SR6's mock SEQ window (the REAL seq_run.Dev
identity gate over a scripted CSR map, every write / DMA / upload a
tripwire — evidence/qwen9b/sr/sr6_host_tdd.py make_dev / run_seq).  "LOADS"
= reached the upload tripwire (every host check before the first DDR byte
passed); "REFUSED" = exited before any DMA.

Why: since SR11a (docs/SEQ_ISA.md v2.3 B17.2) ref/seq_format refuses MVGO
SHAPE bits 29/30 whenever the caller states no layout (the R2 guard).  Bit
29 is AMBIGUOUS without a layout — w8 on build_034/035 (isa=1), XBANK on
build_041+ (isa=2) — so the board callers must state the DEVICE's layout,
hwmap.shape_isa_for_version(VERSION read in the identity block), exactly as
they state the device's caps.

Cases (the brief .superpowers/sdd/2026-09-27-seq-rtl/task-SR11a-fix2-brief.md):
  (a) the frozen 2B W8 artifact tb/scripts/w5/model_w8_2b_s1.e (RD_GATE T4's
      seq_run4 prefix, --four-chan) LOADS on a mock at build_035's VERSION
      0x54443B9F with caps {} (SEQ_CAPS 0xDEADC0DE), named by
      --expect-version 54443b9f;
  (b) an XBANK record (one MVGO with SHAPE bit 29, ng <= 48) is REFUSED at
      build_041's VERSION with caps {} and at build_044_r1_incr's
      (0xE3C2FF1E) with caps {R1}, before any DMA, naming R2;
  (c) the same stream LOADS on a mock reporting caps {R1,R2} (a MOCK-ONLY
      SEQ_VERSIONS / SHAPE_ISA_BY_VERSION row, injected by this test and
      removed after — no such bitstream exists);
  (d) --dry-run of the W8 artifact without --shape-isa is REFUSED before any
      DMA with a message naming --shape-isa; with --shape-isa 1 it proceeds
      (reaches the upload tripwire); --shape-isa on a SEQ run is refused
      (the layout is the device's);
  (e) chat_seq (rd_chat2b.sh's recipe, FABLE5_MODEL=2b, a subprocess of this
      script): the 2B W8 template LOADS on the build_035 mock with
      --shape-isa 1 and FABLE5_SEQ_EXPECT_VERSION=54443b9f (reaches
      bring_up); without --shape-isa it is REFUSED naming --shape-isa;
  (f) the layout is DEVICE-keyed on a SEQ run: seq_run states
      shape_isa_for_version(VERSION) to validate_stream (spy).
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

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
RESULTS = []


def check(case, name, cond, detail=""):
    RESULTS.append((case, bool(cond)))
    print(f"  [{case}] {'PASS' if cond else 'FAIL'} {name}"
          + (f"  -- {detail}" if detail else ""))


def xbank_fixture(d):
    """SR6's synthetic repacked artifact with ONE MVGO carrying SHAPE bit 29
    (XBANK; its ng is 2, legal for a bank)."""
    p, _ = H6.make_fixture(d)
    recs = SF.unpack_stream(open(p + ".seq", "rb").read())
    out, done = [], None
    for i, r in enumerate(recs):
        if done is None and r.opcode == SF.OP_MVGO \
                and ((r.imm32 >> 22) & 0x7F) <= 48:
            r = SF.Rec(r.opcode, r.flags, r.target, r.imm32 | (1 << 29),
                       r.addr_lo, r.len_or_addr_hi)
            done = i
        out.append(r)
    stream = SF.pack_stream(out)
    open(p + ".seq", "wb").write(stream)
    meta = json.load(open(p + ".seq.json"))
    import hashlib
    meta["stream_sha256"] = hashlib.sha256(stream).hexdigest()
    json.dump(meta, open(p + ".seq.json", "w"), indent=1)
    return p, done


def msg(res):
    return res[0] + "\n" + res[2]


def seq_run_cases(tmp, ltmp):
    print("=== seq_run: the board-admission path on mock SEQ windows")
    D035 = H6.make_dev(W_OLD, version=V035)
    D041 = H6.make_dev(W_OLD, version=V041)
    D044 = H6.make_dev(W_R1, version=V044)

    # (a) the frozen 2B W8 path at build_035
    r = H6.run_seq(["--prefix", W5, "--four-chan", "--expect-version",
                    "54443b9f"], D035, ltmp, "a")
    H6.say("(a) W8 2B on build_035", r)
    check("a", "the frozen 2B W8 artifact LOADS at build_035's VERSION with "
               "caps {} (reaches the upload tripwire)", H6.loaded(r), r[0])
    check("a", "... validated at the device's layout (isa=1, printed)",
          "SHAPE layout" in r[2] and "isa=1" in r[2], "")

    # (b) XBANK refused at build_041 {} and build_044 {R1}
    px, i = xbank_fixture(os.path.join(tmp, "xb"))
    r = H6.run_seq(["--prefix", px], D041, ltmp, "b041")
    H6.say("(b) XBANK on build_041", r)
    check("b", f"an XBANK record (rec {i}) is REFUSED at build_041's VERSION "
               "with caps {} before any DMA, naming R2",
          H6.refused_before_dma(r) and "R2" in msg(r)
          and f"rec {i}" in msg(r), r[0][:200])
    r = H6.run_seq(["--prefix", px, "--expect-version", "e3c2ff1e"], D044,
                   ltmp, "b044")
    H6.say("(b) XBANK on build_044_r1", r)
    check("b", "... and at build_044_r1_incr's VERSION with caps {R1}",
          H6.refused_before_dma(r) and "R2" in msg(r), r[0][:200])

    # (c) admitted at a MOCK caps {R1,R2} bitstream
    SR.SEQ_VERSIONS[VMOCK_R2] = (HW.SHAPE_ISA_9B, "MOCK R1+R2 (test only)",
                                 W_R12)
    HW.SHAPE_ISA_BY_VERSION[VMOCK_R2] = HW.SHAPE_ISA_9B
    try:
        DR2 = H6.make_dev(W_R12, version=VMOCK_R2)
        r = H6.run_seq(["--prefix", px, "--expect-version", "2b2b2b2b"], DR2,
                       ltmp, "c")
        H6.say("(c) XBANK on a mock {R1,R2}", r)
        check("c", "the XBANK stream LOADS on a mock reporting caps {R1,R2}",
              H6.loaded(r), r[0][:200])
    finally:
        SR.SEQ_VERSIONS.pop(VMOCK_R2, None)
        HW.SHAPE_ISA_BY_VERSION.pop(VMOCK_R2, None)

    # (d) dry-run: the layout must be STATED
    r = H6.run_seq(["--prefix", W5, "--four-chan", "--dry-run"], D035, ltmp,
                   "d0")
    H6.say("(d) W8 dry-run, no --shape-isa", r)
    check("d", "--dry-run of the W8 artifact without --shape-isa is REFUSED "
               "before any DMA, naming --shape-isa",
          # fix round 3 (m4): the hint must be in the REFUSAL itself (the
          # SystemExit message), not the "SHAPE layout ... pass --shape-isa"
          # status line printed before it
          H6.refused_before_dma(r) and "--shape-isa" in r[0], r[0][:200])
    r = H6.run_seq(["--prefix", W5, "--four-chan", "--dry-run",
                    "--shape-isa", "1"], D035, ltmp, "d1")
    H6.say("(d) W8 dry-run --shape-isa 1", r)
    check("d", "... with --shape-isa 1 it proceeds (reaches the upload "
               "tripwire)", H6.loaded(r), r[0][:200])
    r = H6.run_seq(["--prefix", W5, "--four-chan", "--expect-version",
                    "54443b9f", "--shape-isa", "1"], D035, ltmp, "d2")
    H6.say("(d) --shape-isa on a SEQ run", r)
    check("d", "--shape-isa on a SEQ run is REFUSED before any DMA (the "
               "layout is the device's)",
          H6.refused_before_dma(r) and "--shape-isa" in msg(r), r[0][:200])

    # (f) device-keyed: the validator is handed the VERSION's layout
    seen = []
    real = SF.validate_stream
    # the fixture WRITER validates too (not a board admission): built first
    r0, _ = H6.make_fixture(os.path.join(tmp, "r0"))

    def spy(recs, *a, **k):
        seen.append(k.get("shape_isa", "UNSTATED"))
        return real(recs, *a, **k)
    SF.validate_stream = spy
    try:
        r = H6.run_seq(["--prefix", r0], D041, ltmp, "f")
    finally:
        SF.validate_stream = real
    check("f", "on a SEQ run every seq_run validate_stream call states "
               "shape_isa_for_version(VERSION) (= 2 on build_041)",
          H6.loaded(r) and seen and all(s == HW.SHAPE_ISA_9B for s in seen),
          f"{r[0][:80]} shape_isa seen {seen}")


def chat_2b_child():
    """Run under FABLE5_MODEL=2b: chat_seq main() on the build_035 mock."""
    import chat_seq as CS
    D035 = H6.make_dev(W_OLD, version=V035, use_env=True)
    ltmp = tempfile.mkdtemp(prefix="sr11af2_chat_")
    out = {}
    D041 = H6.make_dev(W_OLD, version=V041, use_env=True)
    for tag, extra, dcls, ever in (
            ("with", ["--shape-isa", "1"], D035, "54443b9f"),
            ("without", [], D035, "54443b9f"),
            # a session built at isa=1 opened on an isa=2 device
            ("mismatch", ["--shape-isa", "1"], D041, "")):
        del H6.EVENTS[:]
        saved = (SR.Dev, CS.ChatSession.bring_up, sys.argv)

        def trip(self):
            H6.EVENTS.append("bring_up")
            raise H6._Tripped("bring_up")
        SR.Dev, CS.ChatSession.bring_up = dcls, trip
        sys.argv = (["chat_seq.py", "--nch", "4", "--template", W5,
                     "--any-template", "--prompt", "hi", "--ntok", "1",
                     "--lock", os.path.join(ltmp, tag)] + extra)
        os.environ["FABLE5_SEQ_EXPECT_VERSION"] = ever
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                CS.main()
            o = "returned"
        except SystemExit as e:
            o = f"exit {e.code!r}"
        except H6._Tripped as t:
            o = f"tripped {t}"
        except Exception as e:                               # noqa: BLE001
            o = f"raised {type(e).__name__}: {e}"
            buf.write(traceback.format_exc())
        finally:
            SR.Dev, CS.ChatSession.bring_up, sys.argv = saved
        dma = [e for e in H6.EVENTS if e in ("wr", "dma_write",
                                             "dma_write_chan", "upload")]
        out[tag] = {"outcome": o, "events": list(H6.EVENTS), "dma": dma,
                    "tail": buf.getvalue()[-1500:]}
    shutil.rmtree(ltmp, ignore_errors=True)
    print("CHAT2B_JSON " + json.dumps(out))


def chat_cases():
    print("=== chat_seq (rd_chat2b.sh's recipe) on the build_035 mock, "
          "FABLE5_MODEL=2b, in a child process")
    env = dict(os.environ, FABLE5_MODEL="2b")
    env.pop("FABLE5_RS_F", None)
    t0 = time.monotonic()
    p = subprocess.run([sys.executable, os.path.abspath(__file__),
                        "--chat2b-child"], env=env, capture_output=True,
                       text=True)
    line = [ln for ln in p.stdout.splitlines()
            if ln.startswith("CHAT2B_JSON ")]
    if not line:
        print(p.stdout[-3000:])
        print(p.stderr[-3000:])
        check("e", "the chat_seq child ran", False, f"rc {p.returncode}")
        return
    res = json.loads(line[-1][len("CHAT2B_JSON "):])
    for tag in ("with", "without", "mismatch"):
        r = res[tag]
        print(f"    ({tag} --shape-isa 1): outcome {r['outcome'][:200]!r} "
              f"events {r['events']} ({time.monotonic() - t0:.0f} s)")
        for ln in [x for x in r["tail"].splitlines() if x.strip()][-3:]:
            print(f"      | {ln[:220]}")
    w, wo = res["with"], res["without"]
    check("e", "chat_seq on the 2B W8 template with --shape-isa 1 LOADS at "
               "build_035 (reaches bring_up)",
          w["outcome"] == "tripped bring_up", w["outcome"][:200])
    check("e", "... without --shape-isa it is REFUSED before any upload, "
               "naming --shape-isa",
          wo["outcome"] not in ("tripped bring_up", "returned")
          and not wo["dma"] and "--shape-isa" in (wo["outcome"] + wo["tail"]),
          wo["outcome"][:200])
    mm = res["mismatch"]
    check("e", "... a session built at --shape-isa 1 is REFUSED at open_board "
               "on an isa=2 device (build_041), before any upload",
          mm["outcome"] not in ("tripped bring_up", "returned")
          and not mm["dma"] and "decodes isa=2" in (mm["outcome"] + mm["tail"]),
          mm["outcome"][:200])


def main():
    if "--chat2b-child" in sys.argv:
        chat_2b_child()
        return True
    t0 = time.monotonic()
    print(f"SR11a fix 2 host TDD — FABLE5_MODEL="
          f"{os.environ.get('FABLE5_MODEL')}")
    tmp = tempfile.mkdtemp(prefix="sr11af2_fx_")
    ltmp = tempfile.mkdtemp(prefix="sr11af2_lock_")
    try:
        for fn, a in ((seq_run_cases, (tmp, ltmp)), (chat_cases, ())):
            try:
                fn(*a)
            except Exception as e:                           # noqa: BLE001
                traceback.print_exc()
                check(fn.__name__, "block ran to the end", False, repr(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(ltmp, ignore_errors=True)
    by = {}
    for c, ok in RESULTS:
        by.setdefault(c, []).append(ok)
    print("per case: " + "  ".join(f"({c}) {sum(v)}/{len(v)}"
                                   for c, v in by.items()))
    npass = sum(ok for _c, ok in RESULTS)
    print(f"SR11A_FIX2_HOST_TDD: {npass} passed, {len(RESULTS) - npass} "
          f"failed ({time.monotonic() - t0:.0f} s) -> "
          + ("PASS" if npass == len(RESULTS) else "FAIL"))
    return npass == len(RESULTS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
