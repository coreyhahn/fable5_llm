#!/usr/bin/env python3
"""g6_ref_cost.py — what does ONE lockstep step cost on the host, at 9B?

Task 15 fix round 2.  Two questions this answers, board-free, in one run:

  1. **Does `sw/chat_seq.py`'s verifier now replay a 9B chat step at all?**
     That is function B of the chat scope (`evidence/qwen9b/g6/RD9_GATE.md`
     §20.2): before it, `ref/seq_model.SeqExec` was handed no `region=` and
     the first SLD/SST refused
     (`evidence/qwen9b/g6/056_chat_seq_9b_model_set.log` attempt [6]).
     This builds the real 9B session and the real verifier and replays the
     preamble, one `lite` step and one `full` step.

  2. **What does a lockstep-verified step COST in host time at 9B?**  The
     scope's budget line for the long-context rung is
     `ref/seq_model.py` at "~5-7 s of host time per step", which is the 2B
     figure `sw/chat_seq.py` prints; nothing has measured the 9B one.  A
     `--verify` chat and the long-context rung are both N times this
     number, so it decides what is affordable.

NO BOARD, NO LOCK: nothing here opens `/dev/xdma0_*`.  Run it on snoke
through `evidence/qwen9b/run.sh`, with `FABLE5_MODEL=9b`.
"""
import os
import sys
import time
import types

TOP = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
for _p in (os.path.join(TOP, "sw"), os.path.join(TOP, "ref")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import chat_seq as C                                            # noqa: E402


def session_args(**kw):
    """The argument namespace `ChatSession` reads, at its CLI defaults.

    `sw/chat_seq.py` builds its parser inside `main()`, so an offline
    driver either re-enters `main()` (which would take the board lock) or
    states the defaults.  Every value below is the parser's own default;
    the ones that matter here are named by the caller.
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


def main():
    print(f"=== FABLE5_MODEL={C.MODEL_TAG}  template="
          f"{os.path.relpath(C.TEMPLATE4_PREFIX, TOP)}  "
          f"nrec={C.TEMPLATE4_NREC}")
    t0 = time.monotonic()
    sess = C.ChatSession(session_args(), log=print)
    print(f"  session    built in {time.monotonic() - t0:.1f}s  "
          f"(pos_mode={sess.pos_mode}, t_max={sess.args.t_max})")
    print(f"  state      {sess.state}")
    t0 = time.monotonic()
    v = C.SeqModelVerifier(sess, log=print)
    print(f"  verifier   built in {time.monotonic() - t0:.1f}s; region "
          f"{'PRESENT' if v.region is not None else 'NONE'}"
          + ("" if v.region is None else f" {v.region.plan}"))
    if v.region is None:
        print("REF COST: FAIL — the verifier has no state region")
        return 1

    rows = []
    t0 = time.monotonic()
    v.preamble(sess.images["preamble"])
    rows.append(("preamble", sess.images["preamble"].nrec,
                 time.monotonic() - t0, None))
    # one prompt token at pos 0 through the LITE body, then the FULL body
    tok = 248045
    for kind, pos in (("lite", 0), ("full", 1)):
        t0 = time.monotonic()
        out = v._run(sess.images[kind], tok, pos)
        rows.append((kind, sess.images[kind].nrec, time.monotonic() - t0,
                     (int(out[0]) if out else None)))
    print("-" * 72)
    print(f"  {'image':9s} {'records':>8s} {'host s':>9s}  token")
    for name, nrec, dt, out in rows:
        print(f"  {name:9s} {nrec:8d} {dt:9.1f}  {out}")
    lite = [r[2] for r in rows if r[0] == "lite"][0]
    full = [r[2] for r in rows if r[0] == "full"][0]
    print(f"  512 lockstep steps at these rates: "
          f"{512 * lite / 3600:.1f} h (all lite) .. "
          f"{512 * full / 3600:.1f} h (all full)")
    print(f"  sdma blocks stored by the two steps: {len(v.region.touched)}")
    print("REF COST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
