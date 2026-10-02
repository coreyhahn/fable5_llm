#!/usr/bin/env python3
"""Run ref/fidelity_check.py with a RETRY+CENSUS shim around w4a8_ref.matvec_y32.

Why this exists
---------------
`evidence/qwen2b/q2/v1_v2/DECOMP.md` section 3.1 documents an impossible
assertion trip on darthplagueis: `ref/w4a8_ref.py:161`,
`assert np.abs(acc).max() < (1 << 31)`, on a reduction whose result cannot
reach 2^31.  The bound is a DTYPE property, not a data property:

    acc = (w4 * x8).sum over g terms,  w4 and x8 are int8 arrays

so |acc| <= g * 128 * 128 = 1048576 at g=64 (2048x below the guard) for ANY
int8 content whatsoever — arbitrary garbage in either operand still cannot
trip it.  Task 8 hit the same trip three times in one session (once in
ref/scripts/regen_gate.sh on the 0.8B with the salience plumb OFF, twice on
this 2B config, at two DIFFERENT call sites), which is why the scored run is
driven through this shim.

What it does, precisely
-----------------------
It monkeypatches `matvec_y32` in `w4a8_ref` and in `layer_fixed` (which binds
the name at import).  No repo source file is modified.  On each call it
delegates to the UNMODIFIED production function.  If — and only if — that
function raises AssertionError:

  1. the operands are audited in place (dtype, min, max, and the arithmetic
     bound above) and the audit is recorded;
  2. the identical call is retried, up to RETRIES times;
  3. the value finally returned is one the PRODUCTION guard accepted, and it
     is additionally cross-checked against an INDEPENDENT re-reduction of the
     same operands (float64-free, plain int64, different expression order).

Nothing is weakened: no assertion is removed, no tolerance is widened, and a
result that never satisfies the production guard still aborts the run.

READ THE EVENT COUNT BEFORE READING THE NUMBERS.  When `events=0` the shim is
a pure pass-through — every call went through the unmodified function on its
first attempt — so the run's outputs are bit-identical to an unwrapped run.
A run with events>0 is a run on a host that produced at least one wrong
reduction, and its numbers are labelled as such in V3.md.

    FABLE5_MODEL=2b FABLE5_CALIB_STATS=ref/calib_stats_2b.npz \
        python3 evidence/qwen2b/q2/v3/guarded_matvec_wrapper.py \
        --cache tb/scripts_scratch/golden_bf16_2b.npz --res-scale 4 ...
"""
import os
import sys
import time
import traceback

REF = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "..", "..", "..", "ref")
sys.path.insert(0, os.path.abspath(REF))

import numpy as np                                              # noqa: E402
import w4a8_ref as W                                            # noqa: E402
import layer_fixed as LF                                        # noqa: E402

RETRIES = 8
_orig = W.matvec_y32
EVENTS = []


def _audit(w4, m, sh, x8, g):
    w4 = np.asarray(w4)
    x8 = np.asarray(x8)
    m = np.asarray(m)
    gg = w4.shape[1] // m.shape[1]
    return {
        "shape": tuple(w4.shape), "g_arg": g, "g_inferred": int(gg),
        "sh": int(sh),
        "w4": f"{w4.dtype} [{int(w4.min())},{int(w4.max())}]",
        "x8": f"{x8.dtype} [{int(x8.min())},{int(x8.max())}]",
        "m": f"{m.dtype} [{int(m.min())},{int(m.max())}]",
        # the arithmetic ceiling for these operands, evaluated from the data
        "acc_bound": int(gg) * int(np.abs(w4).max()) * int(np.abs(x8).max()),
        "guard": 1 << 31,
    }


def guarded(*a, **kw):
    for attempt in range(RETRIES):
        try:
            y = _orig(*a, **kw)
        except AssertionError:
            w4, m, sh, x8 = a[0], a[1], a[2], a[3]
            ev = {"attempt": attempt, "t": time.strftime("%H:%M:%S"),
                  "audit": _audit(w4, m, sh, x8, kw.get("g")),
                  "tb": traceback.format_exc().strip().splitlines()[-3:]}
            EVENTS.append(ev)
            print(f"\n!! GUARD TRIP #{len(EVENTS)} (attempt {attempt}) "
                  f"{ev['audit']}", file=sys.stderr, flush=True)
            continue
        if EVENTS and EVENTS[-1].get("attempt") == attempt - 1 \
                and "verified" not in EVENTS[-1]:
            # independent re-reduction of the SAME operands, different order
            w4, m, sh, x8 = a[0], a[1], a[2], a[3]
            gg = np.asarray(w4).shape[1] // np.asarray(m).shape[1]
            N, K = np.asarray(w4).shape
            acc2 = np.einsum("ijk,jk->ij",
                             np.asarray(w4, dtype=np.int64).reshape(N, K // gg, gg),
                             np.asarray(x8, dtype=np.int64).reshape(K // gg, gg))
            p2 = (np.asarray(m, dtype=np.int64) * acc2).sum(axis=1)
            y2 = W.rshift_round(p2, sh).astype(np.int32)
            EVENTS[-1]["verified"] = bool(np.array_equal(y, y2))
            EVENTS[-1]["acc2_max"] = int(np.abs(acc2).max())
            print(f"   retry OK; independent re-reduction agrees="
                  f"{EVENTS[-1]['verified']} |acc|max={EVENTS[-1]['acc2_max']}",
                  file=sys.stderr, flush=True)
            if not EVENTS[-1]["verified"]:
                raise SystemExit("retry disagreed with an independent "
                                 "re-reduction — do not trust this host")
        return y
    raise SystemExit(f"matvec_y32 failed the production guard {RETRIES} times "
                     "in a row — this is no longer a transient")


W.matvec_y32 = guarded
LF.matvec_y32 = guarded

import fidelity_check as FC                                     # noqa: E402
FC.matvec_y32 = guarded

if __name__ == "__main__":
    sys.argv[0] = "fidelity_check.py"
    try:
        FC.main()
    finally:
        print(f"\nGUARD-TRIP CENSUS: {len(EVENTS)} event(s)", flush=True)
        for e in EVENTS:
            print(f"  {e['t']} attempt={e['attempt']} "
                  f"verified={e.get('verified')} {e['audit']}", flush=True)
        if not EVENTS:
            print("  events=0 -> pure pass-through: every matvec_y32 call "
                  "returned from the UNMODIFIED production function on its "
                  "first attempt, so this run is bit-identical to an "
                  "unwrapped one.", flush=True)
