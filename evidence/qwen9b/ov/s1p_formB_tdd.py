#!/usr/bin/env python3
"""s1p_formB_tdd.py — Task S1P deliverables 2 and 4: the TDD checks for
`chat_seq --reorder B` (per-image reorder, record-following position patch)
and the default switch.  BOARD-FREE: no lock, no device.

    FABLE5_MODEL=9b python evidence/qwen9b/ov/s1p_formB_tdd.py [--slow] \
        [--base-rev <git rev of the pre-S1P sw/chat_seq.py>]

  T1  --reorder B is admitted: resolve_reorder('B') does not refuse, keeps
      the SHIPPED template (B reorders each step image, not the template).
  T2  the default switch: reorder_default(), evaluated at PARSE time in
      main() (not at import), follows $FABLE5_REORDER (unset / "" -> "B",
      "off" / "none" -> None, "A"/"B" -> that form, anything else REFUSED,
      the refusal echoing the user's original spelling) and is "B" in this
      process (Task S1D, 2026-09-27: the user chose B as the default; it was
      None until then).  The CLI takes `--reorder off` -> None (the shipped
      order).  S1D fix round 1: the CLI default is MODEL-AWARE —
      effective_reorder(args, env): an explicit --reorder or a set
      $FABLE5_REORDER is used as given (a form that cannot run still
      REFUSES, rc 4); with neither, "auto" resolves to "B" only at
      FABLE5_MODEL=9b --nch 4 on the shipped template, else None (the
      shipped order) with one log line saying why.
  T8  (final fix C1) the static cost table refuses an unknown MOVY mode
      with StaticCostError (an AssertionError, so resolve_reorder and
      _reorder_images_b turn it into their refusal), not a raw KeyError.
  T3  byte-identical where B is not asked for: reorder=None and reorder='A'
      sessions equal the pre-S1P chat_seq.py at --base-rev (images emitter
      AND relocated, blob, base, template sha).
  T4  the B session: preamble = the shipped preamble; lite/full = the
      per-image static-cost form-B reorder of the shipped images, equal to
      the pins (regeneration == pin); the 3 head records unmoved; every
      record kept is the shipped record the permutation names; only MOVX
      (elided) and FENCE records differ as multisets.
  T5  the position patch FOLLOWS THE RECORD: for (tok, pos, data_delta) at
      several positions, patching the reordered image at the mapped offsets
      == reordering the shipped image patched at the shipped offsets; every
      mapped LDC write lands on an XRF-indirect LDC; patch_writes (the host
      path) uses the mapped offsets too.
  T6  the image hazard assert passes on the B images; a FENCE-less B lite
      is REFUSED.
  T7  (--slow) the B6 model gate on the B images: PASS; an UNCORRUPTED
      override patched by the real path PASSES (control); the same override
      with one layer-ARG CSRWR corrupted — its only difference — FAILS.
"""
import argparse
import collections
import hashlib
import os
import subprocess
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "sw"), os.path.join(ROOT, "ref"),
                os.path.join(ROOT, "ref", "scripts")]
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
    ap.add_argument("--base-rev", default="06ebccd")
    a = ap.parse_args()
    quiet = lambda *x, **k: None                               # noqa: E731

    print("T1 --reorder B admitted")
    check("T1a B in REORDER_FORMS", "B" in getattr(CS, "REORDER_FORMS", ()))
    args_b = mk_args(reorder="B")
    try:
        rep = CS.resolve_reorder(args_b, log=quiet)
        check("T1b resolve_reorder('B') admits it and keeps the shipped "
              "template", os.path.abspath(args_b.template)
              == os.path.abspath(CS.TEMPLATE4_PREFIX)
              and rep.get("form") == "B", str(rep)[:200])
    except Exception as e:                                      # noqa: BLE001
        check("T1b resolve_reorder('B') admits it and keeps the shipped "
              "template", False, repr(e)[:200])

    print("T2 the default switch (flipped to B, Task S1D 2026-09-27)")
    f = getattr(CS, "reorder_default", None)
    if f is None:
        check("T2 reorder_default exists", False)
    else:
        cases = [({}, "B"), ({"FABLE5_REORDER": ""}, "B"),
                 ({"FABLE5_REORDER": "off"}, None),
                 ({"FABLE5_REORDER": "none"}, None),
                 ({"FABLE5_REORDER": "None"}, None),
                 ({"FABLE5_REORDER": "A"}, "A"),
                 ({"FABLE5_REORDER": "B"}, "B"),
                 ({"FABLE5_REORDER": "b"}, "B"), ({"FABLE5_REORDER": "OFF"}, None)]
        for env, want in cases:
            try:
                got = f(env)
            except Exception as e:                              # noqa: BLE001
                got = repr(e)
            check(f"T2 env {env} -> {want}", got == want, str(got))
        try:
            f({"FABLE5_REORDER": "C"})
            check("T2 env FABLE5_REORDER=C REFUSED", False, "accepted")
        except CS.ChatSeqError as e:
            check("T2 env FABLE5_REORDER=C REFUSED", True, str(e)[:120])
        # final fix C2: the refusal echoes the ORIGINAL spelling
        try:
            f({"FABLE5_REORDER": " bOgUs "})
            check("T2 C2: refusal echoes the original spelling", False,
                  "accepted")
        except CS.ChatSeqError as e:
            check("T2 C2: refusal echoes the original spelling",
                  "' bOgUs '" in str(e) and "BOGUS" not in str(e),
                  str(e)[:120])
        check("T2 the default here is 'B' (S1D: flipped)",
              f() == "B" and "FABLE5_REORDER" not in os.environ, str(f()))
        # S1D: the CLI way back to the shipped order, and the refusal a
        # default-B session gives where B cannot run.  Both refuse BEFORE
        # the lock and the board (argparse / resolve_reorder), so boardless.
        envu = {k: v for k, v in os.environ.items() if k != "FABLE5_REORDER"}
        envu["FABLE5_MODEL"] = "9b"
        cs_py = os.path.join(ROOT, "sw", "chat_seq.py")
        off = subprocess.run([sys.executable, cs_py, "--nch", "4",
                              "--reorder", "off", "--reorder-check"],
                             capture_output=True, text=True, env=envu)
        check("T2 S1D: --reorder off parses to None (--reorder-check then "
              "asks for a FORM, rc 2)", off.returncode == 2
              and "--reorder-check needs --reorder FORM" in off.stderr,
              f"rc {off.returncode} {off.stderr[-160:]!r}")
        # S1D fix round 1: auto is model-aware; explicit values as given
        n1 = subprocess.run([sys.executable, cs_py, "--nch", "1",
                             "--reorder-check"],
                            capture_output=True, text=True, env=envu)
        check("T2 S1D-fix1: auto at --nch 1 resolves to None (the shipped "
              "order; --reorder-check then asks for a FORM, rc 2) and says so",
              n1.returncode == 2
              and "--reorder-check needs --reorder FORM" in n1.stderr
              and "auto" in n1.stdout and "shipped order" in n1.stdout,
              f"rc {n1.returncode} {(n1.stdout + n1.stderr)[-240:]!r}")
        envB = dict(envu, FABLE5_REORDER="B")
        e1 = subprocess.run([sys.executable, cs_py, "--nch", "1",
                             "--reorder-check"],
                            capture_output=True, text=True, env=envB)
        check("T2 S1D-fix1: explicit FABLE5_REORDER=B at --nch 1 REFUSES "
              "(rc 4)", e1.returncode == 4
              and "--reorder needs FABLE5_MODEL=9b --nch 4" in e1.stdout,
              f"rc {e1.returncode} {(e1.stdout + e1.stderr)[-200:]!r}")
        c1 = subprocess.run([sys.executable, cs_py, "--nch", "1",
                             "--reorder", "B", "--reorder-check"],
                            capture_output=True, text=True, env=envu)
        check("T2 S1D-fix1: explicit --reorder B at --nch 1 REFUSES (rc 4)",
              c1.returncode == 4
              and "--reorder needs FABLE5_MODEL=9b --nch 4" in c1.stdout,
              f"rc {c1.returncode} {(c1.stdout + c1.stderr)[-200:]!r}")
        eff = getattr(CS, "effective_reorder", None)
        auto = getattr(CS, "REORDER_AUTO", None)
        if eff is None or auto is None:
            check("T2 S1D-fix1: effective_reorder / REORDER_AUTO exist",
                  False)
        else:
            def ns(**kw):
                return types.SimpleNamespace(**dict(
                    dict(reorder=auto, nch=4,
                         template=CS.TEMPLATE4_PREFIX), **kw))
            got = eff(ns(), {}, log=quiet)
            check("T2 S1D-fix1: auto at 9B --nch 4 shipped template -> 'B'",
                  got == "B" and CS.MODEL_TAG == "9b", str(got))
            got = eff(ns(template="/tmp/custom_prefix"), {}, log=quiet)
            check("T2 S1D-fix1: auto at 9B --nch 4 custom --template -> None",
                  got is None, str(got))
            got = eff(ns(nch=1, template=CS.TEMPLATE_PREFIX), {}, log=quiet)
            check("T2 S1D-fix1: auto at --nch 1 -> None", got is None,
                  str(got))
            saved = CS.MODEL_TAG
            try:
                CS.MODEL_TAG = "2b"
                got = eff(ns(), {}, log=quiet)
            finally:
                CS.MODEL_TAG = saved
            check("T2 S1D-fix1: auto at a non-9B model (--nch 4) -> None",
                  got is None, str(got))
            got = eff(ns(nch=1), {"FABLE5_REORDER": "B"}, log=quiet)
            check("T2 S1D-fix1: a set FABLE5_REORDER is used as given "
                  "('B' even at --nch 1; resolve_reorder refuses it)",
                  got == "B", str(got))
            got = eff(ns(), {"FABLE5_REORDER": "off"}, log=quiet)
            check("T2 S1D-fix1: FABLE5_REORDER=off -> None at 9B --nch 4",
                  got is None, str(got))
            got = eff(ns(reorder="A", nch=1), {}, log=quiet)
            check("T2 S1D-fix1: an explicit --reorder is used as given",
                  got == "A", str(got))
            got = eff(ns(reorder=None), {"FABLE5_REORDER": "B"}, log=quiet)
            check("T2 S1D-fix1: explicit --reorder off beats the env",
                  got is None, str(got))
        # fix round 1 (M4): read at PARSE time, not import time
        envb = dict(os.environ, FABLE5_MODEL="9b", FABLE5_REORDER="bogus")
        imp = subprocess.run([sys.executable, "-c", "import sys; sys.path[:0]"
                              f"=[{os.path.join(ROOT, 'sw')!r}, "
                              f"{os.path.join(ROOT, 'ref')!r}]; import chat_seq"],
                             capture_output=True, text=True, env=envb)
        check("T2 M4: importing chat_seq with FABLE5_REORDER=bogus does not "
              "fail (importers that ignore the switch survive)",
              imp.returncode == 0, imp.stderr[-200:])
        cli = subprocess.run([sys.executable, os.path.join(ROOT, "sw",
                                                           "chat_seq.py"),
                              "--nch", "4", "--selftest"],
                             capture_output=True, text=True, env=envb)
        check("T2 M4: the CLI REFUSES FABLE5_REORDER=bogus at parse time "
              "(rc 2)", cli.returncode == 2 and "FABLE5_REORDER" in cli.stderr,
              f"rc {cli.returncode} {cli.stderr[-160:]!r}")

    print("T8 static cost: unknown MOVY mode REFUSED (final fix C1)")
    import seq_cost as SC8
    bad = types.SimpleNamespace(opcode=SF.OP_MOVY, movy_mode=7,
                                len_or_addr_hi=16)
    try:
        SC8._record_dur(bad)
        check("T8 unknown MOVY mode -> StaticCostError", False, "priced it")
    except SC8.StaticCostError as e:
        check("T8 unknown MOVY mode -> StaticCostError (an AssertionError)",
              isinstance(e, AssertionError), str(e)[:120])
    except Exception as e:                                      # noqa: BLE001
        check("T8 unknown MOVY mode -> StaticCostError", False,
              f"{type(e).__name__}: {e}"[:120])

    print(f"T3 byte-identical to {a.base_rev} where B is not asked for")
    old_m = base_module(a.base_rev)
    for form in (None, "A"):
        na = mk_args(reorder=form)
        oa = mk_args(reorder=form)
        if form:
            CS.resolve_reorder(na, log=quiet)
            old_m.resolve_reorder(oa, log=quiet)
        new = images_digest(CS.ChatSession(na, log=quiet))
        old = images_digest(old_m.ChatSession(oa, log=quiet))
        check(f"T3 reorder={form}: every digest identical to {a.base_rev}",
              new == old, "" if new == old else
              str({k: (new[k], old[k]) for k in new if new[k] != old[k]})[:300])

    print("T4 the B session")
    sess = ship = None
    try:
        CS.resolve_reorder(args_b, log=quiet)
        sess = CS.ChatSession(args_b, log=print)
        ship = CS.ChatSession(mk_args(), log=quiet)
    except Exception as e:                                      # noqa: BLE001
        check("T4 a --reorder B session builds", False, repr(e)[:300])
    if sess is not None:
        check("T4a preamble identical to the shipped preamble",
              sess.images["preamble"].a.data == ship.images["preamble"].a.data)
        pins = getattr(CS, "REORDER_B_IMAGES", {})
        for kind in ("lite", "full"):
            nd = sess.images[kind].a.data
            sd = ship.images[kind].a.data
            sha = hashlib.sha256(nd).hexdigest()
            pin = pins.get(kind)
            check(f"T4b {kind} regenerated == pin",
                  bool(pin) and sha == pin[0] and len(nd) // 16 == pin[1],
                  f"{sha[:16]} ({len(nd) // 16} rec) vs pin {pin}")
            check(f"T4c {kind} is reordered (differs from shipped)", nd != sd)
            nr, sr = SF.unpack_stream(nd), SF.unpack_stream(sd)
            check(f"T4d {kind} head (tok/pos/tcnt records) unmoved",
                  nd[:CS.PATCH_BYTES] == sd[:CS.PATCH_BYTES])
            perm = sess.reorder_perm[kind]
            ok = all(nr[perm[i]] == sr[i] for i in perm)
            check(f"T4e {kind} every kept record is the shipped record the "
                  f"permutation names ({len(perm)} of {len(sr)})", ok)
            cn = collections.Counter(r.to_bytes() for r in nr
                                     if r.opcode not in (SF.OP_MOVX,
                                                         SF.OP_FENCE))
            cs = collections.Counter(r.to_bytes() for r in sr
                                     if r.opcode not in (SF.OP_MOVX,
                                                         SF.OP_FENCE))
            nmx = sum(1 for r in nr if r.opcode == SF.OP_MOVX)
            smx = sum(1 for r in sr if r.opcode == SF.OP_MOVX)
            check(f"T4f {kind} same records except MOVX/FENCE; MOVX "
                  f"{smx} -> {nmx}", cn == cs and nmx < smx)

        print("T5 the position patch follows the record")
        RE = CS._reorder_mod()
        import seq_cost as SCo
        for kind in ("lite", "full"):
            sa = ship.images[kind].a
            for (tok, pos, dd) in ((760, 0, 0), (2614, 1, 0),
                                   (1234, 300, 0x40000), (99, 510, 0)):
                mine = sess.step_patch(kind, tok=tok, pos=pos, tcnt=1,
                                       data_delta=dd).apply(
                                           sess.images[kind].a)
                sp = ship.tc.patch_step(sa, tok=tok, pos=pos, tcnt=1,
                                        data_delta=dd).apply(sa)
                sr = SF.unpack_stream(sp)
                ref, _c, _r = RE.reorder(sr, SCo.rows_for(sr, CS.REORDER_B_POS),
                                         "B", [])
                check(f"T5a {kind} tok {tok} pos {pos} delta {dd:#x}: "
                      f"patch(reorder) == reorder(patch)",
                      mine == SF.pack_stream(ref))
            p = sess.step_patch(kind, tok=5, pos=7, tcnt=1, data_delta=0)
            nr = SF.unpack_stream(sess.images[kind].a.data)
            ldc = [o for (o, b) in p.writes()[1:]]
            ok = ldc and all(nr[o // 16].opcode == SF.EXT_LDC
                             and nr[o // 16].ind != SF.IND_NONE
                             and o % 16 == 8 for o in ldc)
            check(f"T5b {kind}: {len(ldc)} mapped LDC writes, each on an "
                  f"XRF-indirect LDC's addr_lo", bool(ok))
            w, _fl = sess.patch_writes(kind, 5, 7)
            w2 = sess.step_patch(kind, tok=5, pos=7, tcnt=1,
                                 data_delta=sess.plan["data_delta"]).writes()
            check(f"T5c {kind}: patch_writes (host path) = the mapped patch",
                  w == w2)

        print("T6 image hazard assert")
        try:
            n = CS.reorder_image_hazards(sess)
            check("T6a the three B images pass", True, str(n)[:160])
        except Exception as e:                                  # noqa: BLE001
            check("T6a the three B images pass", False, repr(e)[:200])
        bad = [x for x in sess.images["lite"].recs_emit
               if x.opcode != SF.OP_FENCE]
        try:
            CS.reorder_image_hazards(sess, extra={"lite-nofence": bad})
            check("T6b FENCE-less B lite REFUSED", False, "not refused")
        except CS.ChatSeqError as e:
            check("T6b FENCE-less B lite REFUSED", True, str(e)[:160])

        if a.slow:
            print("T7 the B6 model gate on the B images (slow)")
            g = CS.reorder_model_gate(sess, log=print)
            check("T7a shipped-order vs form-B images: EXACT", g["ok"],
                  str(g)[:300])
            # the override replaces the PATCHED bytes the gate replays: build
            # it with the SAME patch the gate's reordered side applies
            (t_l, p_l, _k) = CS.REORDER_GATE_TOKS[0]
            a_l = sess.images["lite"].a
            patched = sess.step_patch("lite", tok=t_l, pos=p_l, tcnt=1,
                                      data_delta=0).apply(a_l)
            g0 = CS.reorder_model_gate(sess, log=print,
                                       override={"lite": patched})
            check("T7b-control an UNCORRUPTED override, patched by the real "
                  "path, PASSES", g0["ok"], str(g0.get("diff"))[:200])
            lite = SF.unpack_stream(patched)

            def feeds_compute(i):
                for y in lite[i + 1:]:
                    if y.opcode == SF.OP_CMD:
                        return (y.imm32 & 0xFF) not in (SF.OP_L_SLD,
                                                        SF.OP_L_SST)
                return False
            k = next(i for i, x in enumerate(lite)
                     if x.opcode == SF.OP_CSRWR and x.target == SF.CSR_L_ARG1
                     and feeds_compute(i))
            x = lite[k]
            lite[k] = SF.Rec(x.opcode, flags=x.flags, target=x.target,
                             imm32=x.imm32 ^ 0x10, addr_lo=x.addr_lo,
                             len_or_addr_hi=x.len_or_addr_hi)
            badb = SF.pack_stream(lite)
            ndiff = sum(1 for u, v in zip(badb, patched) if u != v)
            print(f"    T7c corruption: record {k} (CSRWR L_ARG1) imm32 ^= "
                  f"0x10; {ndiff} byte(s) differ from the control override")
            g2 = CS.reorder_model_gate(sess, log=print, override={"lite": badb})
            check("T7c the corrupted (identically patched) B lite FAILS the "
                  "gate", (not g2["ok"]) and ndiff == 1,
                  str(g2.get("diff"))[:300])

    print(f"S1P_FORMB_TDD: {len(PASS)} passed, {len(FAIL)} failed")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
