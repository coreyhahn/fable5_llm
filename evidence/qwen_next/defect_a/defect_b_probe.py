#!/usr/bin/env python3
"""Defect B (`sw/infer.py:798-802`) — verify the study's LOUD claim.

Track F does NOT fix defect B (it is a migration work item on the ledger).
This probe only checks the claim that decides its severity, namely that at
H != 1024 the online `step()` CRASHES rather than silently corrupting:

    sw/infer.py:798   M.vnw_(STG, 1024)
    sw/infer.py:799   M.vn(1, 1024, RS_F, RS_F, X0, XN)
    sw/infer.py:800   M.alu(0, 1024, 0, XN, 0, X8)
    sw/infer.py:802   y32, _ = M.matvec(self.qw_head, X8, 1024, rowchunk=ROWCHUNK)

`M.matvec` (ref/gen_layer_script.py:947-1001) slices `n_in` words of scratch
and hands them to `w4a8_ref.matvec_y32{,_w8}`, whose first act is

    w4.reshape(N, NG, g) * x8.reshape(1, NG, g)          (w4a8_ref.py:283-284)

with `NG = K // g` taken from the WEIGHT, not from `n_in`.  At the 2B head
K = H = 2048, so a 1024-word `x8` cannot be reshaped and numpy raises.

Nothing under sw/ is imported, called or modified here: the probe drives the
same ref/ functions sw/infer.py imports (its lines 86-88), at 2B geometry.

Run under FABLE5_MODEL=2b.
"""
import os
import sys

import numpy as np

R = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(R, "ref"))

import layer_ref as LR                                          # noqa: E402
from model_select import TAG                                    # noqa: E402
from w4a8_ref import matvec_y32, matvec_y32_w8                  # noqa: E402


def main():
    if TAG != "2b":
        raise SystemExit(f"run me under FABLE5_MODEL=2b (got {TAG!r})")
    H, g, N = LR.H, 128, 8               # N rows is enough; K is what matters
    print(f"FABLE5_MODEL={TAG}  H={H}   LM-head K = H = {H}, group g = {g}")
    rng = np.random.default_rng(0)
    ok = True

    for name, mv, w in (("W4", matvec_y32,
                         rng.integers(-8, 8, (N, H)).astype(np.int8)),
                        ("W8", matvec_y32_w8,
                         rng.integers(-127, 128, (N, H)).astype(np.int8))):
        m = rng.integers(1, 100, (N, H // g)).astype(np.int64)
        x_right = rng.integers(-127, 128, H).astype(np.int8)
        x_wrong = x_right[:1024]         # what sw/infer.py:802 would pass

        y = mv(w, m, 0, x_right, g=g)
        print(f"  {name}: n_in = H = {H:5d}  -> y32 {y.shape}, ok")

        try:
            mv(w, m, 0, x_wrong, g=g)
            print(f"  {name}: n_in = 1024        -> RETURNED A RESULT — "
                  f"the defect would be SILENT, not loud")
            ok = False
        except Exception as e:
            print(f"  {name}: n_in = 1024        -> {type(e).__name__}: {e}")

    # and the three lines before it: those DO truncate silently
    print(f"\n  the vnw_/vn/alu triple at n=1024 touches {1024}/{H} words "
          f"({100.0 * 1024 / H:.0f}% of the residual) with no error — the "
          f"corruption starts silently and the matvec is where it stops")
    print(f"\nDEFECT B: {'LOUD as documented (crashes at H != 1024)' if ok else 'NOT LOUD — study claim WRONG'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
