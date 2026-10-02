#!/usr/bin/env python3
"""g6_longctx_lockstep.py — the long-context rung's MISSING per-step lockstep.

Task 15 fix round 3.  `evidence/qwen9b/g6/RD9_GATE.md` §8.7 states what the
T = 526 rung does NOT establish: **the per-step token lockstep**.  The
reviewer's ruling (`task-15-review-round3.md` §3.1) is that the way to
establish it is a **board-free replay of `083`'s own step sequence**, not the
boundary-crossing shortcut (which would seed the reference from the chip and
make steps 0-511 self-referential).  This is that replay.

WHAT IT DOES
  * rebuilds the SAME 9B session `083` step [4] ran — the prompt, `--max-ctx`
    and `--ntok` are read out of `083_longctx_chat.json`'s own committed
    `argv`, not retyped — so the compiled `preamble`/`lite`/`full` step images
    and the 4,096-entry position pool are the same bytes the board launched;
  * replays all 526 forward steps through `ref/seq_model.SeqExec` with the
    artifact's initial DDR state region, exactly as `sw/chat_seq.py`'s
    `--verify` does (`SeqModelVerifier._run`), carrying `mach` and `region`
    from step to step;
  * compares, at every step, the reference's emitted token against the
    chip's.

WHAT "THE CHIP'S TOKEN" IS AT EACH STEP.  `083` prefilled with the **lite**
body, which has no LM head (`sw/chat_seq.py:18`), so the chip emitted NO
token on steps 0-501 and `ChatSession.step` asserts that
(`sw/chat_seq.py:2563-2570`).  The per-step verdict on a prefill step is
therefore "both sides emit no token", which is a weak check on its own — the
load-bearing comparison is the 24 **decode** ids, and those depend on the
whole 502-step prefill trajectory: a single wrong prefill step moves the KV
region and the decode tokens with it.  Both counts are printed, and the final
line names both.

NO BOARD, NO LOCK, NO DMA: nothing here opens `/dev/xdma0_*`.  ~19.3 h at
`074`'s measured 131.2 s (lite) / 149.3 s (full) per step; it cannot be
parallelised (each step depends on the previous `mach` and `region`).  Run it
detached ON SNOKE through `evidence/qwen9b/run.sh`, with `FABLE5_MODEL=9b`.

TASK 15-D EXTENSION (bounded, and this is the whole of it).  `106` collected
the verdict — `FAIL at step 503`, reference 3177 against the chip's 20438 —
and "which side is wrong" is not a verdict a token comparison can give.  So,
for the prompt-length bisect, three things were added HERE and nowhere else
(no RTL, no TB, no `ref/`, no emitter):

  --top5 K    at every DECODE step, the reference's K best logits as
              (id, value), the #1-#2 margin, and THE RANK AND VALUE OF THE
              CHIP'S OWN TOKEN in the reference's logits.  A near-tie and a
              landslide are different findings and the token alone hides
              which one this is.  The values are tapped from `AMAX32`'s own
              candidate stream by wrapping `GLS.Mach.alu` at run time — the
              reference file is not edited, and the tap is READ-ONLY: it
              copies the values the op is about to fold in and calls the
              original.
  --continue  do not stop at the first divergence; replay all the decode
              steps, so a run reports 4 comparisons instead of 1.
  --dump-kv LO-HI   after the last replayed step, dump the REFERENCE
              region's KV rows LO..HI in `g6_kv_rows.py`'s own JSON shape
              (that file's `dump()` is called, not re-implemented), so
              `g6_kv_rows.py --compare` puts the two sides' rows side by
              side.
"""
import argparse
import ast
import json
import os
import re
import sys
import time
import types

TOP = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
for _p in (os.path.join(TOP, "sw"), os.path.join(TOP, "ref")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np                                             # noqa: E402

import chat_seq as C                                            # noqa: E402

G6 = os.path.dirname(os.path.abspath(__file__))
if G6 not in sys.path:
    sys.path.insert(0, G6)
import g6_kv_rows as KR                                         # noqa: E402


# ======================================================================
# the AMAX32 tap (15-D) — READ-ONLY, installed at run time
# ======================================================================
# `ref/seq_model.SeqExec` publishes only `M.am_idx` (the argmax) through
# `out_fifo`; the LOGITS themselves are never materialised as a vector —
# `AMAX32` folds each MVGO chunk in as it arrives (`ref/gen_layer_script.py`
# `Mach.alu` op 10).  The margin between the reference's token and the
# chip's is exactly what a divergence investigation needs, so this wraps
# that one op, copies the values it is about to fold, and calls through.
# NOTHING in ref/ is edited and no arithmetic is duplicated.
_AMAX_LOG = []


def install_amax_tap():
    import gen_layer_script as GLS
    orig = GLS.Mach.alu

    def alu(self, op, n, p0, srca, srcb, dst):
        if op == 10:                                   # AMAX32 (running)
            start = 0 if (p0 & 1) else int(self.am_g)
            _AMAX_LOG.append((start,
                              np.asarray(self.pairs(srca, n)).copy()))
        return orig(self, op, n, p0, srca, srcb, dst)

    GLS.Mach.alu = alu
    return orig


def amax_top(k, chip_tok=None):
    """(top-k [(id, value)], margin, chip rank, chip value) from the tap.

    The chunks arrive in id order and carry their own start index, so the
    vector is reassembled from them rather than assumed contiguous.
    """
    if not _AMAX_LOG:
        return [], None, None, None
    n = max(s + len(v) for s, v in _AMAX_LOG)
    vec = np.full(n, np.iinfo(np.int64).min, dtype=np.int64)
    for s, v in _AMAX_LOG:
        vec[s:s + len(v)] = v
    order = np.argsort(-vec, kind="stable")[:max(k, 2)]
    top = [(int(i), int(vec[i])) for i in order]
    margin = top[0][1] - top[1][1] if len(top) > 1 else None
    rank = val = None
    if chip_tok is not None and 0 <= chip_tok < n:
        val = int(vec[chip_tok])
        rank = int((vec > val).sum()) + 1
    return top[:k], margin, rank, val


def top5_lines(top, margin, chip_tok, rank, val):
    """The two extra lines a decode step prints, in ONE place (like
    `step_line`, so `--selfcheck` can render them before an 18 h run)."""
    out = ["      top%d    %s" % (len(top),
                                  "  ".join(f"{i}:{v}" for i, v in top))]
    if margin is not None and top:
        pct = (100.0 * margin / abs(top[0][1])) if top[0][1] else float("nan")
        out[0] += f"   #1-#2 margin {margin} ({pct:.4f}% of the top logit)"
    if chip_tok is not None:
        out.append(f"      chip's {chip_tok} is rank "
                   f"{'?' if rank is None else rank} in the reference"
                   + ("" if val is None else
                      f", value {val}, {top[0][1] - val} below the top"))
    return out


class RegionSide(object):
    """`g6_kv_rows.dump()`'s reader interface, backed by the REFERENCE's own
    `ref/seq_model.StateRegion` instead of a board or a file.

    `StateRegion.mem` is one flat uint8 array covering [dn, end) addressed by
    absolute DDR address, which is exactly the contract `g6_kv_rows`'s two
    sides already implement — so the dump and its JSON shape are that file's,
    not a second copy of B15.1's arithmetic.
    """

    def __init__(self, region):
        self.region = region
        self.base = int(region.plan["dn"])
        self.ident = None

    def read(self, addr, n):
        o = int(addr) - self.base
        assert 0 <= o and o + n <= len(self.region.mem), (addr, n)
        return bytes(self.region.mem[o:o + n])

    def close(self):
        pass


def chip_run(json_path, log_path):
    """(argv, chip decode ids) of the committed board run being replayed.

    Both come out of the run's own committed artifacts: the JSON carries
    `argv` verbatim (`sw/chat_seq.py:6396`), the log carries the id list
    `run_turn` printed (`sw/chat_seq.py:3566`).  Nothing is retyped here.
    """
    rep = json.load(open(json_path))
    argv = [str(a) for a in rep["argv"]]
    ids = None
    with open(log_path) as fh:
        for line in fh:
            m = re.match(r"^  ids (\[[0-9, ]*\])\s", line)
            if m:
                ids = [int(i) for i in ast.literal_eval(m.group(1))]
                break
    if ids is None:
        raise SystemExit(f"no '  ids [...]' line in {log_path}")
    return rep, argv, ids


def argv_get(argv, flag, cast=str, default=None):
    return cast(argv[argv.index(flag) + 1]) if flag in argv else default


def session_args(**kw):
    """`ChatSession`'s argument namespace at the parser's own defaults.

    Same shape as `evidence/qwen9b/g6/g6_ref_cost.py`'s: `sw/chat_seq.py`
    builds its parser inside `main()`, which would take the board lock, so
    an offline driver states the defaults and the caller names the ones
    that matter.
    """
    a = types.SimpleNamespace(
        template=C.TEMPLATE4_PREFIX, nch=4, chan=0,
        t_max=C.T_MAX, pos_mode="auto", max_ctx=C.DEFAULT_MAX_CTX,
        any_template=False, force_upload=False,
        temp=C.DEFAULT_TEMP, top_k=C.DEFAULT_TOP_K, top_p=C.DEFAULT_TOP_P,
        seed=None, verify_head=False,
        prefill="lite", ntok=C.DEFAULT_NTOK, ntok_given=False,
        raw=False, system=None, dev="/dev/xdma0_user",
        timeout=C.STEP_TIMEOUT, preamble_timeout=C.PREAMBLE_TIMEOUT)
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def step_line(i, kind, tok, o, want, ok, dt, eta, txt):
    """The per-step verdict line, in ONE place.

    Both arms are rendered by `--selfcheck` at the top of every run: a
    19.3 h replay must not discover a formatting bug in its decode arm at
    step 502, eighteen hours in.
    """
    return (f"  step {i:3d} {kind:4s} tok={tok:<7d} pos={i:<3d} "
            f"ref -> {('no token' if o is None else str(o)):>8s}  "
            f"chip -> {'no token' if want is None else want}  "
            f"{'==' if ok else '!! DIVERGENCE'}   "
            f"[{dt:5.1f}s  eta {eta:4.1f}h]   {txt}")


def selfcheck(log=print):
    """Render every line this run can emit, with dummy values."""
    log("  selfcheck  the two per-step arms and the three verdicts, "
        "rendered with dummy values:")
    log(step_line(0, "lite", 760, None, None, True, 131.2, 19.3, ""))
    log(step_line(501, "lite", 13, None, None, False, 131.2, 0.9, ""))
    log(step_line(502, "full", 13, 760, 760, True, 149.3, 0.9, "'The'"))
    for ln in top5_lines([(760, 18446744), (3177, 18446700), (11, 1800)],
                         44, 760, 1, 18446744):
        log(ln)
    log(step_line(525, "full", 11, 12, 11, False, 149.3, 0.0, "','"))
    for ln in top5_lines([(12, 900), (11, 899)], 1, 11, 2, 899):
        log(ln)
    for v in ("LONGCTX_LOCKSTEP: PASS 526/526",
              "LONGCTX_LOCKSTEP: FAIL at step 502",
              "LONGCTX_LOCKSTEP: PARTIAL 1/526 (--limit 1)",
              "LONGCTX_LOCKSTEP: FAIL at step 503 (4 decode steps replayed, "
              "1 agreed)"):
        log(f"             {v}")


def selfcheck_tap(log=print):
    """The 15-D tap, EXERCISED rather than rendered.

    `selfcheck()` draws the lines with dummy values so an 18 h run cannot
    discover a formatting bug at step 502.  The tap needs the other kind of
    check: it must really intercept a real `AMAX32` and really rank it.  So
    this drives a REAL `GLS.Mach` over four known values, asserts the top-k,
    the margin, the chip-token rank AND that the machine's own `am_idx` is
    unchanged by the wrapper — then puts `GLS.Mach.alu` back.
    """
    import gen_layer_script as GLS
    saved = os.environ.pop("SEQ_EMIT", None)
    orig = install_amax_tap()
    try:
        M = GLS.Mach(open(os.devnull, "w"))
        vals = [5, 9, 3, 7]
        M.set_pairs(0, vals)
        del _AMAX_LOG[:]
        M.alu(10, len(vals), 1, 0, 0, 0)          # p0 bit 0 resets am_g
        top, margin, rank, val = amax_top(3, chip_tok=2)
        ok = (top == [(1, 9), (3, 7), (0, 5)] and margin == 2
              and rank == 4 and val == 3 and int(M.am_idx) == 1)
        log(f"  tap check  AMAX32 over {vals}: top3 {top}, margin {margin}, "
            f"id 2 is rank {rank} value {val}, Mach.am_idx "
            f"{int(M.am_idx)} -> {'OK' if ok else 'FAIL'}")
        r = KR.parse_rows("500-525")
        log(f"  tap check  g6_kv_rows.parse_rows('500-525') = {r} -> "
            f"{'OK' if r == (500, 525) else 'FAIL'}")
        ok = ok and r == (500, 525)
    finally:
        GLS.Mach.alu = orig
        del _AMAX_LOG[:]
        if saved is not None:
            os.environ["SEQ_EMIT"] = saved
    if not ok:
        raise SystemExit("the 15-D AMAX32 tap does not work — refusing to "
                         "start a multi-hour replay on it")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat-json",
                    default=os.path.join(G6, "083_longctx_chat.json"))
    ap.add_argument("--chat-log",
                    default=os.path.join(G6, "083_longctx_9b.log"))
    ap.add_argument("--out", default=None,
                    help="JSON verdict alongside the log")
    ap.add_argument("--selfcheck", action="store_true",
                    help="render both per-step arms and the verdicts first")
    ap.add_argument("--limit", type=int, default=0,
                    help="replay only the first N steps (a smoke run; the "
                         "verdict line then says PARTIAL, never PASS)")
    ap.add_argument("--top5", type=int, default=0, metavar="K",
                    help="15-D: at every DECODE step print the reference's K "
                         "best logits, the #1-#2 margin and the chip token's "
                         "rank in them (0 = off)")
    ap.add_argument("--continue", dest="cont", action="store_true",
                    help="15-D: do not stop at the first divergence — replay "
                         "every decode step")
    ap.add_argument("--dump-kv", default=None, metavar="LO-HI",
                    help="15-D: after the last step, dump the REFERENCE "
                         "region's KV rows LO..HI beside --out, in "
                         "g6_kv_rows.py's JSON shape")
    ap.add_argument("--dump-kv-layers", default="0,4,7")
    args = ap.parse_args()

    if args.selfcheck:
        selfcheck()
        selfcheck_tap()
    if args.top5:
        install_amax_tap()
        print(f"  amax tap   INSTALLED (--top5 {args.top5}): "
              f"GLS.Mach.alu op 10 is wrapped read-only; the reference's "
              f"own arithmetic is untouched")
    rep, argv, chip_ids = chip_run(args.chat_json, args.chat_log)
    max_ctx = argv_get(argv, "--max-ctx", int, C.DEFAULT_MAX_CTX)
    ntok = argv_get(argv, "--ntok", int, C.DEFAULT_NTOK)
    nch = argv_get(argv, "--nch", int, 4)
    prompt = argv_get(argv, "--prompt", str, None)
    if prompt is None:
        raise SystemExit("the committed run carries no --prompt")

    print(f"=== the board run being replayed: "
          f"{os.path.relpath(args.chat_json, TOP)}")
    print(f"  argv       --nch {nch} --max-ctx {max_ctx} --ntok {ntok} "
          f"--prompt <{len(prompt)} chars>")
    print(f"  chip       {rep['launches']} launches, context {rep['context']}, "
          f"{rep['sampling']['mode']} decode")
    print(f"  chip ids   {chip_ids}   ({len(chip_ids)} tok)")
    print(f"=== FABLE5_MODEL={C.MODEL_TAG}  template="
          f"{os.path.relpath(C.TEMPLATE4_PREFIX, TOP)}  "
          f"nrec={C.TEMPLATE4_NREC}  T_MAX={C.T_MAX}")

    t0 = time.monotonic()
    sess = C.ChatSession(session_args(nch=nch, max_ctx=max_ctx, ntok=ntok,
                                      ntok_given=True), log=print)
    print(f"  session    built in {time.monotonic() - t0:.1f}s  "
          f"(pos_mode={sess.pos_mode}, t_max={sess.args.t_max})")
    tk = C.load_tokenizer(log=print)
    sess.attach_template(tk)

    ids, wrap, _nmsg, _sys = C._wrap_turn(sess, tk, prompt)
    feed, nsteps, need_reset = sess.plan_turn(ids, ntok)
    print(f"  templated  {len(ids)} ids ({wrap} wrapper + {len(ids) - wrap} "
          f"body); feed {len(feed)}; steps {nsteps} = {len(feed) - 1} prefill "
          f"(lite) + {ntok} decode (full); auto-reset {need_reset}")
    if need_reset:
        raise SystemExit("this replay does not model an auto-reset")

    t0 = time.monotonic()
    v = C.SeqModelVerifier(sess, log=print)
    print(f"  verifier   built in {time.monotonic() - t0:.1f}s; region "
          f"{'PRESENT' if v.region is not None else 'NONE'}"
          + ("" if v.region is None else f" {v.region.plan}"))
    if v.region is None:
        print("LONGCTX_LOCKSTEP: FAIL at step -1 (the verifier has no state "
              "region)")
        return 1

    t_pre = time.monotonic()
    v.preamble(sess.images["preamble"])
    print(f"  preamble   replayed in {time.monotonic() - t_pre:.1f}s")

    last = nsteps if args.limit <= 0 else min(nsteps, args.limit)
    print("-" * 72)
    print(f"  replaying {last} of {nsteps} steps; {len(feed) - 1} prefill "
          f"then {ntok} decode.  A prefill step's verdict is that BOTH sides "
          f"emit no token (the lite body has no LM head); the decode steps "
          f"are the token-for-token comparison.")
    print("-" * 72)

    ref_ids, agree, fail_at, tops = [], 0, None, []
    t_all = time.monotonic()
    tok = feed[0]
    for i in range(last):
        lite = (i < len(feed) - 1)
        im = sess.images["lite" if lite else "full"]
        del _AMAX_LOG[:]
        t1 = time.monotonic()
        out = v._run(im, tok, i)
        o = int(out[0]) if out else None
        dt = time.monotonic() - t1
        el = time.monotonic() - t_all
        eta = (el / (i + 1)) * (last - i - 1) / 3600.0
        if lite:
            ok, want, txt = (o is None), None, ""
        else:
            k = i - (len(feed) - 1)
            want = chip_ids[k] if k < len(chip_ids) else None
            ok = (o is not None and o == want)
            ref_ids.append(o)
            txt = repr(tk.decode([o])) if o is not None else "(no token)"
        print(step_line(i, "lite" if lite else "full", tok, o, want, ok,
                        dt, eta, txt))
        if (not lite) and args.top5:
            top, margin, rank, val = amax_top(args.top5, want)
            for ln in top5_lines(top, margin, want, rank, val):
                print(ln)
            tops.append({"step": i, "pos": i, "ref": o, "chip": want,
                         "top": top, "margin": margin,
                         "chip_rank": rank, "chip_value": val})
        sys.stdout.flush()
        if not ok and fail_at is None:
            fail_at = i
        if not ok and not args.cont:
            break
        if ok:
            agree += 1
        # --continue: the reference keeps running ITS OWN trajectory (the
        # next token it feeds itself is its own `o`, never the chip's) —
        # seeding it from the chip here would make every later step a test
        # of the chip against itself, which is §8.7a's rejected shortcut.
        if i + 1 < nsteps:
            tok = feed[i + 1] if i + 1 < len(feed) else o

    wall = time.monotonic() - t_all
    print("-" * 72)
    print(f"  replayed   {agree} of {nsteps} steps in {wall / 3600:.2f} h "
          f"({wall / max(1, agree):.1f} s/step)")
    print(f"  ref ids    {ref_ids}")
    print(f"  chip ids   {chip_ids}")
    ndec = len(ref_ids)
    nmatch = sum(1 for k, x in enumerate(ref_ids)
                 if k < len(chip_ids) and x == chip_ids[k])
    print(f"  decode     {nmatch}/{len(chip_ids)} of the chip's tokens "
          f"reproduced ({ndec} decode steps replayed)")
    verdict = (f"LONGCTX_LOCKSTEP: FAIL at step {fail_at}"
               + (f" ({len(ref_ids)} decode steps replayed, {nmatch} agreed)"
                  if args.cont else "")
               if fail_at is not None
               else (f"LONGCTX_LOCKSTEP: PASS {agree}/{nsteps}"
                     if agree == nsteps
                     else f"LONGCTX_LOCKSTEP: PARTIAL {agree}/{nsteps} "
                          f"(--limit {args.limit})"))
    kvdump = None
    if args.dump_kv and args.out:
        lo, hi = KR.parse_rows(args.dump_kv)
        layers = [int(x) for x in args.dump_kv_layers.split(",") if x != ""]
        print(f"  dump-kv    the REFERENCE region's rows {lo}..{hi}, "
              f"layers {layers}, through g6_kv_rows.dump()")
        side = RegionSide(v.region)
        kvdump = KR.dump(side, v.region.plan, layers, 0, lo, hi,
                         region_sha=True)
        kvdump["tag"] = "ref-" + os.path.basename(args.out).split(".")[0]
        kvdump["source"] = "ref/seq_model.StateRegion after step %d" % (
            agree + (0 if fail_at is None else 0))
        kvpath = args.out.replace(".json", "") + "_kv.json"
        json.dump(kvdump, open(kvpath, "w"), indent=1)
        print(f"  dump-kv -> {kvpath}")
    if args.out:
        json.dump({"tool": "g6_longctx_lockstep", "argv": sys.argv[1:],
                   "replayed": agree, "steps": nsteps, "fail_at": fail_at,
                   "ref_ids": ref_ids, "chip_ids": chip_ids,
                   "decode_match": nmatch, "top5": tops,
                   "wall_s": round(wall, 1), "verdict": verdict},
                  open(args.out, "w"), indent=1)
    print(verdict)
    # rc reflects the work REQUESTED: with --limit the verdict line says
    # PARTIAL, so a clean short run is rc 0 and not a false green.
    return 0 if (fail_at is None and agree == last) else 1


if __name__ == "__main__":
    sys.exit(main())
