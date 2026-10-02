#!/usr/bin/env python3
"""bm1_reorder_tdd.py — BM1-T4 step 4: the TDD checks for chat_seq's
`--reorder` emit-path flag (rulings B6/B7).  BOARD-FREE: no lock, no device.

    FABLE5_MODEL=9b python evidence/qwen9b/bm/bm1_reorder_tdd.py [--slow] \
        [--base-rev <git rev of the pre-flag sw/chat_seq.py>]

  T1  the CLI: --reorder is in --help; an unknown form is an argparse error.
  T2  the pins: form A = the SV1 artifact (sha b6ced3f9…, 156,616 records);
      form B is ADMITTED by resolve_reorder (S1P lifted ruling B7).
  T3  OFF IS BYTE-IDENTICAL: with reorder=None (FABLE5_REORDER=off or
      --reorder off; the CLI default is form B since Task S1D, 2026-09-27 —
      this check never read the CLI default), ChatSession's three
      images (emitter AND relocated bytes), const blob, base and template sha
      equal those of the pre-flag chat_seq.py at --base-rev.
  T4  resolve_reorder('A') REGENERATES the reordered template in-process with
      ref/scripts/reorder_e4.py (hazard assert on input/output + OV1's
      postcheck per segment run inside it) and admits it only if it equals
      the pinned artifact byte for byte; a tampered pin is REFUSED.
  T5  the image hazard assert: the three reordered images pass; a lite image
      with its FENCEs dropped is REFUSED.
  T6  (--slow, ~15 min) the B6 model gate: shipped-order vs reordered images
      replayed in ref/seq_model.SeqExec (running-channel refusal armed) from
      the same state — PASS on the real images, FAIL on a lite image whose
      one layer-ARG CSRWR was corrupted.
"""
import argparse
import hashlib
import os
import subprocess
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "sw"), os.path.join(ROOT, "ref")]
import chat_seq as CS                                          # noqa: E402
import seq_format as SF                                        # noqa: E402

PASS, FAIL = [], []


def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))


def mk_args(**kw):
    a = dict(template=CS.TEMPLATE4_PREFIX, any_template=False, nch=4,
             t_max=CS.T_MAX, pos_mode="auto", max_ctx=511, chan=0,
             temp=0.0, top_k=CS.DEFAULT_TOP_K, top_p=CS.DEFAULT_TOP_P,
             seed=None, verify_head=False, system=None, reorder=None)
    a.update(kw)
    return types.SimpleNamespace(**a)


def base_module(rev):
    src = subprocess.check_output(["git", "-C", ROOT, "show",
                                   f"{rev}:sw/chat_seq.py"])
    m = types.ModuleType("chat_seq_base")
    m.__file__ = os.path.join(ROOT, "sw", "chat_seq.py")
    exec(compile(src, "chat_seq_base(%s)" % rev, "exec"), m.__dict__)
    return m


def images_digest(sess):
    out = {}
    for n in ("preamble", "lite", "full"):
        im = sess.images[n]
        out[n] = (hashlib.sha256(im.a.data).hexdigest(),
                  hashlib.sha256(im.data).hexdigest(), im.base)
    out["blob"] = hashlib.sha256(sess.const_blob).hexdigest()
    out["base"] = sess.base
    out["tmpl_sha"] = sess.tmpl_sha
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slow", action="store_true")
    ap.add_argument("--base-rev", default="904b311")
    ap.add_argument("--t6b-only", action="store_true",
                    help="--slow: skip T6a (already green in a kept log)")
    a = ap.parse_args()
    py = sys.executable
    cs = os.path.join(ROOT, "sw", "chat_seq.py")
    env = dict(os.environ, FABLE5_MODEL="9b")

    print("T1 CLI")
    h = subprocess.run([py, cs, "--help"], capture_output=True, text=True,
                       env=env)
    check("T1a --reorder in --help", "--reorder" in h.stdout)
    r = subprocess.run([py, cs, "--nch", "4", "--reorder", "C", "--selftest"],
                       capture_output=True, text=True, env=env)
    check("T1b --reorder C is an argparse error (rc 2)", r.returncode == 2,
          f"rc {r.returncode}")

    print("T2 pins")
    pins = getattr(CS, "REORDER4_BY_FORM", {})
    pa = pins.get("A")
    check("T2a form A pinned to the SV1 artifact",
          bool(pa) and pa[0][-1] == "model_9b_s1_reordA.e4"
          and pa[1].startswith("b6ced3f92d3fe8c3") and pa[2] == 156616)
    # S1P lifted ruling B7 (form B is per-image in chat_seq): inverted in
    # S1P fix round 1 (M5)
    try:
        rb = CS.resolve_reorder(mk_args(reorder="B"))
        check("T2b form B admitted (S1P lifts B7)",
              (rb or {}).get("form") == "B", str(rb)[:160])
    except Exception as e:                                       # noqa: BLE001
        check("T2b form B admitted (S1P lifts B7)", False, repr(e)[:160])

    print("T3 reorder off (None), byte-identical")
    new = images_digest(CS.ChatSession(mk_args(), log=lambda *x: None))
    old_m = base_module(a.base_rev)
    oargs = mk_args()
    del oargs.reorder
    old = images_digest(old_m.ChatSession(oargs, log=lambda *x: None))
    for k in new:
        check(f"T3 {k} identical to {a.base_rev}", new[k] == old[k],
              str(new[k])[:90])

    print("T4 resolve_reorder('A')")
    args = mk_args(reorder="A")
    try:
        rep = CS.resolve_reorder(args)
        ok = (args.template.endswith("model_9b_s1_reordA.e4")
              and rep.get("regenerated_sha256", "").startswith("b6ced3f92d3f"))
        check("T4a regenerated == pinned; template switched", ok, str(rep)[:200])
    except Exception as e:                                       # noqa: BLE001
        check("T4a regenerated == pinned; template switched", False, repr(e)[:200])
    saved = dict(CS.REORDER4_BY_FORM) if pins else {}
    try:
        if pins:
            p = CS.REORDER4_BY_FORM["A"]
            CS.REORDER4_BY_FORM["A"] = (p[0], "0" * 64, p[2], p[3])
        try:
            CS.resolve_reorder(mk_args(reorder="A"))
            check("T4b a tampered pin is REFUSED", False, "not refused")
        except Exception as e:                                   # noqa: BLE001
            check("T4b a tampered pin is REFUSED",
                  isinstance(e, CS.ChatSeqError), repr(e)[:160])
    finally:
        if pins:
            CS.REORDER4_BY_FORM.update(saved)

    print("T5 image hazard assert")
    sess = None
    try:
        sess = CS.ChatSession(args, log=lambda *x: None)
        n = CS.reorder_image_hazards(sess)
        check("T5a the three reordered images pass", True, str(n)[:160])
        lite = sess.images["lite"].recs_emit
        bad = [x for x in lite if x.opcode != SF.OP_FENCE]
        try:
            CS.reorder_image_hazards(sess, extra={"lite-nofence": bad})
            check("T5b FENCE-less lite REFUSED", False, "not refused")
        except CS.ChatSeqError as e:
            check("T5b FENCE-less lite REFUSED", True, str(e)[:160])
    except Exception as e:                                       # noqa: BLE001
        check("T5a the three reordered images pass", False, repr(e)[:200])

    if a.slow and sess is not None:
        print("T6 the B6 model gate (slow)")
        if not a.t6b_only:
            g = CS.reorder_model_gate(sess, log=print)
            check("T6a shipped-order vs reordered: EXACT", g["ok"],
                  str(g)[:300])
        # Fix round 1 (I1): the override replaces the PATCHED bytes the gate
        # would replay, so build it from the SAME patch as the real path
        # (reorder_model_gate's lite step: tok 760 @ pos 0, data_delta 0).
        # The ONLY difference between the two arms below is the corruption.
        (t_l, p_l, _k) = CS.REORDER_GATE_TOKS[0]
        a_l = sess.images["lite"].a
        patched = sess.tc.patch_step(a_l, tok=t_l, pos=p_l, tcnt=1,
                                     data_delta=0).apply(a_l)
        g0 = CS.reorder_model_gate(sess, log=print,
                                   override={"lite": patched})
        check("T6b-control an UNCORRUPTED, identically patched override "
              "PASSES the gate", g0["ok"], str(g0.get("diff"))[:200])
        lite = SF.unpack_stream(patched)

        def feeds_compute(i):
            for y in lite[i + 1:]:
                if y.opcode == SF.OP_CMD:
                    return (y.imm32 & 0xFF) not in (SF.OP_L_SLD, SF.OP_L_SST)
            return False
        k = next(i for i, x in enumerate(lite)
                 if x.opcode == SF.OP_CSRWR and x.target == SF.CSR_L_ARG1
                 and feeds_compute(i))
        x = lite[k]
        lite[k] = SF.Rec(x.opcode, flags=x.flags, target=x.target,
                         imm32=x.imm32 ^ 0x10, addr_lo=x.addr_lo,
                         len_or_addr_hi=x.len_or_addr_hi)
        bad = SF.pack_stream(lite)
        ndiff = sum(1 for u, v in zip(bad, patched) if u != v)
        print(f"    T6b corruption: record {k} (CSRWR L_ARG1) imm32 ^= 0x10; "
              f"{ndiff} byte(s) differ from the control override")
        g2 = CS.reorder_model_gate(sess, log=print, override={"lite": bad})
        check("T6b a corrupted (identically patched) reordered lite image "
              "FAILS the gate", (not g2["ok"]) and ndiff == 1,
              str(g2.get("diff"))[:300])

    print(f"BM1_REORDER_TDD: {len(PASS)} passed, {len(FAIL)} failed")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
