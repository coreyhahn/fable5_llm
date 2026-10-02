#!/usr/bin/env python3
"""Reproduce the res_scale=16 abort in w4a8_ref.matvec_y32 WITH diagnostics.

Repo files are untouched: we monkeypatch layer_fixed.matvec_y32 (which holds
its own reference to the w4a8_ref function) with a wrapper that catches the
guard trip and dumps the exact state that produced it.
"""
import os
import sys

import numpy as np

REF = "/home/cah/r2d2/code/fpga/fable5_llm/ref"
sys.path.insert(0, REF)

import w4a8_ref as W  # noqa: E402
import layer_fixed as LF  # noqa: E402

_orig = W.matvec_y32


def dump(w4, m, sh, x8, g):
    N, K = w4.shape
    gg = W.group_size_of(w4, m, g)
    NG = K // gg
    acc = (w4.reshape(N, NG, gg).astype(np.int64)
           * x8.astype(np.int64).reshape(1, NG, gg)).sum(axis=2)
    p = (m.astype(np.int64) * acc).sum(axis=1)
    y = W.rshift_round(p, sh)
    print("\n===== W4A8 GUARD TRIP =====", flush=True)
    print(f"  w4 {w4.shape} {w4.dtype}  min {int(w4.min())} max {int(w4.max())}")
    print(f"  x8 {np.shape(x8)} {np.asarray(x8).dtype}  "
          f"min {int(np.min(x8))} max {int(np.max(x8))}")
    print(f"  m {m.shape} {m.dtype}  min {int(m.min())} max {int(m.max())}")
    print(f"  sh={sh}  g={gg}  NG={NG}")
    print(f"  |acc|max = {int(np.abs(acc).max())}   guard 2**31 = {1 << 31}"
          f"   naive bound g*8*127 = {gg * 8 * 127}")
    print(f"  |p|max   = {int(np.abs(p).max())}   (int64)")
    print(f"  |y|max   = {int(np.abs(y).max())}   guard 2**31 = {1 << 31}"
          f"   -> y guard {'TRIPS' if np.abs(y).max() >= (1 << 31) else 'ok'}")
    print("=" * 27, flush=True)


def instrumented(w4, m, sh, x8, g=None):
    try:
        return _orig(w4, m, sh, x8, g=g)
    except AssertionError:
        import traceback
        print("\n===== CAUGHT =====", flush=True)
        traceback.print_exc()
        dump(w4, m, sh, x8, g)
        try:
            _orig(w4, m, sh, x8, g=g)
            print("  RETRY of the identical call SUCCEEDED", flush=True)
        except AssertionError:
            print("  RETRY of the identical call FAILED AGAIN", flush=True)
        sys.exit(3)


LF.matvec_y32 = instrumented

import fidelity_check as FC  # noqa: E402

sys.argv = ["fidelity_check.py",
            "--cache", "/home/cah/r2d2/code/fpga/fable5_llm/tb/scripts_scratch/golden_bf16_2b.npz",
            "--res-scale", "16", "--ntok", "1", "--free-ntok", "2",
            "--wire-group", "128"]
os.chdir("/home/cah/r2d2/code/fpga/fable5_llm")
FC.main()
