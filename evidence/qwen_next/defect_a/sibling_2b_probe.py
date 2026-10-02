#!/usr/bin/env python3
"""The ref/ twin of defect B, in `ref/seq_chat.layer_fixed_greedy` — fixed
in this branch, demonstrated here at real 2B geometry through the real Mach.

Before the fix (`ref/seq_chat.py:1305-1308`, §2.10's second row):

    M.W(GLS.STG, ln_f_q12)
    M.vnw_(GLS.STG, 1024)                 <- ln_f loaded for 1024 of H words
    M.vn(1, 1024, RS_F, RS_F, X0, XN)     <- RMSNorm denominator over half
    M.alu(0, 1024, 0, XN, 0, X8)          <- DYNQ8 exponent to match
    y32, _ = M.matvec(qw_head, X8, 1024, rowchunk=ROWCHUNK)

five lines after :1247 correctly wrote `M.embed(tok, GLS.X0, LR.H)`.

This probe drives `ref/gen_layer_script.Mach` at FABLE5_MODEL=2b (H=2048)
and shows, on the same state:

  1. n=1024 for vnw_/vn/alu SUCCEEDS and produces a DIFFERENT x8 than n=H
     — the corruption is silent, and it is not a truncation of the right
     answer either: the RMSNorm denominator itself changes.
  2. n_in=1024 into `M.matvec` on an H-wide head RAISES (ValueError, from
     w4a8_ref.py:284's reshape) — where sw/infer.py's online step() would
     stop, three silent lines too late.
  3. the post-fix `LR.H` form runs clean and its y32 matches an independent
     `matvec_y32` over the whole residual.

Run under FABLE5_MODEL=2b.
"""
import os
import sys

import numpy as np

R = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(R, "ref"))

import gen_layer_script as GLS                                  # noqa: E402
import layer_fixed as LF                                        # noqa: E402
import layer_ref as LR                                          # noqa: E402
from model_select import TAG                                    # noqa: E402
from w4a8_ref import matvec_y32                                 # noqa: E402


def fresh_mach(resid):
    M = GLS.Mach(open(os.devnull, "w"))
    M.mem[GLS.X0:GLS.X0 + LR.H] = resid
    return M


def norm_to_x8(M, n):
    """The four lines under test, with `n` where the literal 1024 was."""
    ln_f = np.full(LR.H, 1 << 12, dtype=GLS.I64)     # folded (1+w), w == 0
    M.W(GLS.STG, ln_f)
    M.vnw_(GLS.STG, n)
    M.vn(1, n, LF.RS_F, LF.RS_F, GLS.X0, GLS.XN)
    M.alu(0, n, 0, GLS.XN, 0, GLS.X8)
    return np.asarray(M.mem[GLS.X8:GLS.X8 + LR.H]).astype(np.int64), M.eout


def report(name, resid, H):
    """One residual, both ways.  Returns (leading half changed at all?)."""
    x8_H, e_H = norm_to_x8(fresh_mach(resid), H)
    x8_1k, e_1k = norm_to_x8(fresh_mach(resid), 1024)
    d = np.abs(x8_H[:1024] - x8_1k[:1024])
    nz = int((d != 0).sum())
    print(f"   {name}")
    print(f"     half-energy  lo {float(np.mean(resid[:1024].astype(float)**2)):,.0f}"
          f"   hi {float(np.mean(resid[1024:].astype(float)**2)):,.0f}")
    print(f"     DYNQ8 exponent   n=H -> {e_H}   n=1024 -> {e_1k}"
          f"   {'(SHIFTED)' if e_H != e_1k else '(same)'}")
    print(f"     x8[:1024] vs the n=H answer: max|diff| {int(d.max())}, "
          f"mean|diff| {float(d.mean()):.1f}, {nz}/1024 words changed "
          f"({100.0 * nz / 1024:.1f} %)")
    print(f"     x8[1024:] left at {int(np.abs(x8_1k[1024:]).max())} "
          f"(the second half is never written)")
    return int(d.max()) > 0


def main():
    if TAG != "2b":
        raise SystemExit(f"run me under FABLE5_MODEL=2b (got {TAG!r})")
    H, g, N = LR.H, 128, 64
    rng = np.random.default_rng(7)
    print(f"FABLE5_MODEL={TAG}   H={H}   residual at X0={GLS.X0:#x}, "
          f"XN={GLS.XN:#x}, X8={GLS.X8:#x}")

    print(f"\n1) vnw_/vn/alu at n=1024 on an H={H} residual: no exception.")
    print("   RMSNorm's denominator is a mean over the words it is TOLD "
          "about, so how\n   badly the leading half is corrupted depends on "
          "how the residual's energy\n   is split between the halves.  Two "
          "samples, because the first revision of\n   this probe reported "
          "only the flat one and understated the damage\n   (correction, "
          "2026-08-25 — see CORRECTIONS.md):")

    flat = rng.integers(-400, 400, H).astype(np.int64)
    uneven = rng.integers(-400, 400, H).astype(np.int64)
    uneven[1024:] = (uneven[1024:] * 6)           # the half it never sees
    changed = report("(a) i.i.d. uniform, both halves alike:", flat, H)
    changed |= report("(b) uneven halves (hi 6x lo, the realistic case):",
                      uneven, H)
    resid = uneven

    # a small stand-in for the LM head: N rows of K = H
    qw = {"w4": rng.integers(-8, 8, (N, H)).astype(np.int8),
          "m": rng.integers(1, 100, (N, H // g)).astype(np.int64),
          "sh": 5, "e": 0, "g": g}

    M = fresh_mach(resid)
    _x8, _e = norm_to_x8(M, H)
    print("\n2) M.matvec(head, X8, n_in) on the H-wide head:")
    try:
        M.matvec(qw, GLS.X8, 1024, rowchunk=8)
        print("   n_in=1024 -> RETURNED — the defect would be SILENT")
        loud = False
    except Exception as e:
        print(f"   n_in=1024 -> {type(e).__name__}: {e}")
        loud = True

    M = fresh_mach(resid)
    x8, _e = norm_to_x8(M, H)
    y32, _eo = M.matvec(qw, GLS.X8, H, rowchunk=8)
    want = np.asarray(matvec_y32(qw["w4"], qw["m"], qw["sh"],
                                 x8.astype(np.int8), g=g), dtype=np.int64)
    exact = np.array_equal(np.asarray(y32, dtype=np.int64), want)
    print(f"   n_in=H={H} -> y32 {np.asarray(y32).shape}, matches an "
          f"independent matvec_y32 over the whole residual: {exact}")

    ok = changed and loud and exact
    print(f"\n3) verdict: the pre-fix n=1024 form is SILENTLY WRONG for three "
          f"lines\n   — the RMSNorm denominator is a mean over 1024 of {H} "
          f"words, so even the\n   words it does write differ from the truth, "
          f"and the DYNQ8 exponent can\n   shift with them — and only THEN is "
          f"it loud, at the matvec.  How large\n   the silent error is depends "
          f"on the residual: near-zero when the halves\n   carry equal energy, "
          f"large when they do not.  The post-fix LR.H form is\n   exact.")
    print(f"\nSIBLING PROBE: {'PASS' if ok else 'FAIL'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
