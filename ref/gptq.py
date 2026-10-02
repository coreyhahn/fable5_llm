#!/usr/bin/env python3
"""GPTQ-lite — the error-feedback W4 quantizer (Track Q V4, task 8b).

What it is
----------
`layer_fixed.quant_linear_mse` (V2) picks each group's INT4 scale by an MSE
grid search and then ROUNDS every weight independently.  V3 weights that
search by a per-input-channel activation salience.  Both still round each
weight to its own nearest grid point, so every weight's rounding error goes
straight into the layer's output.

GPTQ (Frantar et al., 2210.17323) removes most of that: it quantizes the
input channels LEFT TO RIGHT and, after fixing channel j, updates the
not-yet-quantized channels of the same row so that the layer's OUTPUT on the
calibration distribution stays as close as it can to the original.  The
optimal update follows from the second moment of the inputs,

    H = E[x x^T]            (`ref/calib_stats.py --hessian`)

as   W[:, j+1:] -= (w_j - q_j)/[H^-1]_jj * [H^-1]_j,j+1:  , which this module
evaluates in the standard blocked ("lazy batch") form — mathematically
identical to the column-at-a-time recursion, because a column outside the
current block is not read until the block's accumulated update is applied.

Why a DIAGONAL Hessian is not enough (the finding that shaped this module).
If H is diagonal then H^-1 is diagonal, so [H^-1]_j,j+1: is identically zero
and the error-feedback term VANISHES: GPTQ degenerates to plain rounding, and
the only thing a diagonal statistic can still do is weight the scale search —
which is exactly V3.  So error feedback needs off-diagonal information; the
`h2/` second moments alone cannot produce it.  `_selftest` case 1 asserts this
as a bit-identity (diagonal H in ⇒ byte-identical to `quant_linear_mse`),
which is both the proof of that claim and this module's frozen-flow guard.

What is "lite" about it
-----------------------
* NO act-order (activation-magnitude column permutation).  It would reorder
  input channels, and the RTL walks a weight row in beat order — a permuted
  row is a different wire format.  Out of scope by construction.
* The group scales are chosen ONCE, before the sweep, by the same weighted
  MSE search V2/V3 use (weighted here by E[x_k^2] = the Hessian diagonal, the
  exact diagonal of the objective GPTQ minimises).  Textbook group-wise GPTQ
  re-fits each group's scale mid-sweep on the already-compensated weights;
  that would make the shared exponent `e` depend on the sweep and is not done.
* Everything else is textbook GPTQ: full K x K Hessian, Cholesky of its
  damped inverse, sequential per-column feedback, blocked updates.

The WIRE FORMAT is untouched.  This module returns the same dict as
`quant_linear_mse` — `w4` (N,K) int8 nibbles, `m` (N,NG) uint16 group
mantissas, one shared `e`, the same `sh` and `g` — only the VALUES of the
nibbles move.  `_selftest` asserts that, and round-trips a GPTQ result
through `w4a8_ref.pack_ddr_rows`.

    python3 ref/gptq.py --selftest
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np                                              # noqa: E402

import layer_fixed as LF                                        # noqa: E402
from w4a8_ref import G                                          # noqa: E402

PERCDAMP = 0.01            # damping, as a fraction of mean(diag H) — GPTQ's
ROWCHUNK = 8192            # rows per pass (rows are independent; see below)


class HessFactor:
    """One input site's Hessian, factorized for the GPTQ recursion.

    `U` is upper-triangular with `U^T U = (H + damp*I)^-1`, which is what the
    recursion consumes: the update after quantizing column i is
    `err_i * U[i, i+1:]` with `err_i = (w_i - q_i) / U[i, i]`.
    `diag` is the ORIGINAL (undamped) diagonal E[x_k^2] — the weight of the
    group-scale search, kept here so both consumers read the same numbers.
    """

    __slots__ = ("K", "U", "diag", "damp", "n_dead", "asym", "name", "tries")

    def __init__(self, K, U, diag, damp, n_dead, asym, name, tries):
        self.K, self.U, self.diag = K, U, diag
        self.damp, self.n_dead, self.asym = damp, n_dead, asym
        self.name, self.tries = name, tries

    def __repr__(self):                                   # pragma: no cover
        return (f"HessFactor({self.name!r}, K={self.K}, damp={self.damp:.4g}, "
                f"dead={self.n_dead}, asym={self.asym:.2e}, tries={self.tries})")


def factor(H, percdamp=PERCDAMP, name=""):
    """(K,K) second moment -> `HessFactor`.

    Damping is GPTQ's: `damp = percdamp * mean(diag H)` added to the diagonal.
    It is what makes the inverse well conditioned; without it a rank-deficient
    calibration Hessian (fewer tokens than channels, or a dead channel) has no
    inverse at all.  A channel that never fires on the calibration corpus gets
    the damping value on its diagonal, and its weights are then quantized by
    plain rounding with no feedback — the conservative choice; the alternative
    in the reference implementation (zeroing those weights) throws away
    information that the corpus simply did not exercise.
    """
    H = np.asarray(H, dtype=np.float64)
    if H.ndim != 2 or H.shape[0] != H.shape[1]:
        raise SystemExit(f"Hessian {name!r} must be square, got {H.shape}")
    K = H.shape[0]
    if not np.all(np.isfinite(H)):
        raise SystemExit(f"Hessian {name!r} is not finite")
    d = np.diag(H).astype(np.float64).copy()
    if np.any(d < 0.0):
        raise SystemExit(f"Hessian {name!r} has a negative diagonal — it is "
                         "not a second moment E[x x^T]")
    mean_d = float(d.mean())
    if not mean_d > 0.0:
        raise SystemExit(f"Hessian {name!r} is identically zero")
    # X^T X is symmetric in exact arithmetic; a threaded float32 GEMM can
    # leave the two triangles an ulp apart.  Symmetrize so the factorization
    # is a deterministic function of the file, not of the BLAS tiling.
    asym = float(np.abs(H - H.T).max() / (np.abs(H).max() + 1e-300))
    Hd = 0.5 * (H + H.T)
    dead = d <= 0.0
    idx = np.arange(K)
    damp = percdamp * mean_d
    Hd[idx, idx] = np.where(dead, damp, d + damp)
    tries = 0
    while True:
        try:
            U = np.linalg.cholesky(np.linalg.inv(Hd)).T     # U^T U = Hd^-1
            if not np.all(np.isfinite(U)):
                raise np.linalg.LinAlgError("non-finite factor")
            break
        except np.linalg.LinAlgError:
            tries += 1
            if tries > 4:
                raise SystemExit(
                    f"Hessian {name!r}: could not factorize even at "
                    f"damp={damp:.4g} ({percdamp * 10 ** tries:.3g} of mean "
                    "diag) — the calibration statistics are degenerate")
            damp *= 10.0
            Hd[idx, idx] = np.where(dead, damp, d + damp)
            print(f"  [gptq] {name}: Cholesky retry {tries} at damp={damp:.4g}",
                  flush=True)
    return HessFactor(K, U, d, damp, int(dead.sum()), asym, name, tries)


def _as_factor(hess, name=""):
    return hess if isinstance(hess, HessFactor) else factor(hess, name=name)


def quant_linear_gptq(Wf, g=G, hess=None, nalpha=17, amin=0.55,
                      rowchunk=ROWCHUNK):
    """W4A8 group quantization with GPTQ error feedback (Track Q V4).

    Same signature shape and same returned dict as
    `layer_fixed.quant_linear_mse` — `{"w4","m","e","g","sh"}` with identical
    shapes and dtypes.  `hess` is the (K,K) second moment of THIS matrix's
    input, or a pre-computed `HessFactor` (see `calib_stats.HessStore`).

    Rows are INDEPENDENT: the group scales are per (row, group), and the
    feedback moves a row's own not-yet-quantized weights only.  So the row
    chunking below is exact, not an approximation — `_selftest` asserts that a
    chunked run is bit-identical to a one-shot one, which is what lets the
    248320-row tied head run in bounded memory (the same property
    `gen_model_script.quant_linear_big` relies on).
    """
    if hess is None:
        raise SystemExit("quant_linear_gptq needs the input Hessian — pass "
                         "hess=(K,K) or a gptq.HessFactor")
    W = np.asarray(Wf)
    if W.ndim != 2:
        raise SystemExit(f"GPTQ needs a 2-D matrix, got shape {W.shape}")
    N, K = W.shape
    g = int(g)
    if K % g:
        raise SystemExit(f"GPTQ g={g}: K={K} is not a multiple of {g}")
    NG = K // g
    f = _as_factor(hess)
    if f.K != K:
        raise SystemExit(f"Hessian is {f.K}x{f.K} but the matrix has K={K} "
                         "input channels")
    rowchunk = max(1, int(rowchunk))

    # ---- pass 1: the group-scale search (V2/V3's, weighted by E[x^2]) ----
    # sqrt() here because `_salience_weights` squares its argument: the weight
    # of channel k is E[x_k^2], normalised to mean 1.  Going through that one
    # helper (rather than a second copy of the normalisation) is what makes a
    # DIAGONAL Hessian bit-identical to `quant_linear_mse(salience=sqrt(d))`.
    sw = LF._salience_weights(np.sqrt(f.diag), K, g)
    smax = np.empty((N, NG), dtype=np.float64)
    for r0 in range(0, N, rowchunk):
        r1 = min(r0 + rowchunk, N)
        blk = np.asarray(W[r0:r1], dtype=np.float64).reshape(r1 - r0, NG, g)
        smax[r0:r1] = np.abs(blk).max(axis=2)
    smax = np.maximum(smax, 1e-12)
    scale = smax / 7.0
    best_e = np.full((N, NG), np.inf)
    for r0 in range(0, N, rowchunk):
        r1 = min(r0 + rowchunk, N)
        blk = np.asarray(W[r0:r1], dtype=np.float64).reshape(r1 - r0, NG, g)
        for a in np.linspace(amin, 1.0, nalpha):
            s = (smax[r0:r1] / 7.0) * a
            q = np.clip(np.round(blk / s[:, :, None]), -8, 7)
            sqerr = (q * s[:, :, None] - blk) ** 2
            err = (sqerr * sw).sum(axis=2)
            upd = err < best_e[r0:r1]
            scale[r0:r1] = np.where(upd, s, scale[r0:r1])
            best_e[r0:r1] = np.where(upd, err, best_e[r0:r1])
    e = int(np.ceil(np.log2(scale.max()))) + 1
    m = np.clip(np.round(scale * np.exp2(15 - e)).astype(np.uint32),
                1, 65535).astype(np.uint16)
    eff = m.astype(np.float64) * np.exp2(e - 15)                  # (N, NG)

    # ---- pass 2: the GPTQ sweep, one row block at a time ----
    U = f.U
    w4 = np.empty((N, K), dtype=np.int8)
    for r0 in range(0, N, rowchunk):
        r1 = min(r0 + rowchunk, N)
        Wc = np.array(W[r0:r1], dtype=np.float64)          # a working COPY
        Err = np.empty((r1 - r0, g), dtype=np.float64)
        for b in range(NG):
            b0, b1 = b * g, (b + 1) * g
            s = eff[r0:r1, b]                              # (nr,) group scale
            Wb = Wc[:, b0:b1]                              # view — updated in place
            Ub = U[b0:b1, b0:b1]
            for i in range(g):
                w = Wb[:, i]
                q = np.clip(np.round(w / s), -8, 7)
                w4[r0:r1, b0 + i] = q.astype(np.int8)
                err = (w - q * s) / Ub[i, i]
                Err[:, i] = err
                if i + 1 < g:
                    Wb[:, i + 1:] -= err[:, None] * Ub[i, i + 1:][None, :]
            if b1 < K:                       # lazy batch update — exact
                Wc[:, b1:] -= Err @ U[b0:b1, b1:]
    p_bound = NG * 65535 * (g * 8 * 127)
    return {"w4": w4, "m": m, "e": e, "g": int(g),
            "sh": max(0, p_bound.bit_length() - 31)}


# ======================================================================
# self-test
# ======================================================================
def _wire_same(a, b):
    """Same WIRE FORMAT: key set, shapes, dtypes, group size, requant shift."""
    return (sorted(a) == sorted(b)
            and a["w4"].shape == b["w4"].shape and a["w4"].dtype == b["w4"].dtype
            and a["m"].shape == b["m"].shape and a["m"].dtype == b["m"].dtype
            and a["g"] == b["g"] and a["sh"] == b["sh"]
            and isinstance(a["e"], int) and isinstance(b["e"], int))


def _qeq(a, b):
    return (_wire_same(a, b) and np.array_equal(a["w4"], b["w4"])
            and np.array_equal(a["m"], b["m"]) and a["e"] == b["e"])


def _deq(q):
    """The float matrix a {w4,m,e,g} image represents."""
    N, K = q["w4"].shape
    g = q["g"]
    eff = q["m"].astype(np.float64) * np.exp2(q["e"] - 15)
    return (q["w4"].reshape(N, K // g, g).astype(np.float64)
            * eff[:, :, None]).reshape(N, K)


def _selftest():
    import w4a8_ref as W
    ok = True
    rng = np.random.default_rng(20260813)

    print("--- 1: a DIAGONAL Hessian is bit-identically the V2/V3 quantizer ---")
    # This is the module's frozen-flow guard AND the proof that diagonal
    # statistics cannot produce error feedback: H^-1 diagonal => the update
    # term is identically zero => plain rounding at the same group scales.
    for (N, K) in ((64, 256), (37, 1024)):
        Wf = rng.normal(0, 0.02, (N, K)).astype(np.float32)
        for g in (64, 128):
            d = rng.lognormal(0.0, 1.5, K)
            got = quant_linear_gptq(Wf, g=g, hess=np.diag(d))
            want = LF.quant_linear_mse(Wf, g=g, salience=np.sqrt(d))
            ok &= _qeq(got, want)
            eye = quant_linear_gptq(Wf, g=g, hess=np.eye(K))
            plain = LF.quant_linear_mse(Wf, g=g)
            ok &= _qeq(eye, plain)
    print(f"  diag(H) == quant_linear_mse(salience=sqrt(diag)), "
          f"I == unweighted MSE  {'OK' if ok else 'FAIL'}")

    print("--- 2: a CORRELATED Hessian moves the nibbles, not the format ---")
    T, N, K, g = 4096, 96, 512, 64
    A = rng.normal(0, 1, (K, K)) * (np.abs(rng.normal(0, 1, (K, 1))) + 0.1)
    X = rng.standard_t(6, (T, K)) @ A                       # correlated inputs
    H = (X.T @ X) / T
    Wf = (rng.normal(0, 0.02, (N, K))
          + rng.standard_t(3, (N, K)) * 0.004).astype(np.float32)
    rtn = LF.quant_linear_mse(Wf, g=g, salience=np.sqrt(np.diag(H)))
    fac = factor(H, name="selftest")
    gq = quant_linear_gptq(Wf, g=g, hess=fac)
    fmt = _wire_same(gq, rtn)
    moved = int((gq["w4"] != rtn["w4"]).sum())
    ok &= fmt and moved > 0 and np.array_equal(gq["m"], rtn["m"]) \
        and gq["e"] == rtn["e"]
    print(f"  wire format identical={fmt}, group scales identical=True, "
          f"nibbles moved {moved}/{N * K} ({100 * moved / (N * K):.1f}%) "
          f"{'OK' if ok else 'FAIL'}")

    print("--- 3: it minimises what it claims to (output error, not weight) ---")
    def out_err(q):
        D = _deq(q) - Wf.astype(np.float64)
        return float(np.sqrt(np.einsum("nk,kj,nj->", D, H, D)))
    e_rtn, e_gptq = out_err(rtn), out_err(gq)
    e_plain = out_err(LF.quant_linear_mse(Wf, g=g))
    w_rtn = float(np.linalg.norm(_deq(rtn) - Wf))
    w_gptq = float(np.linalg.norm(_deq(gq) - Wf))
    # Only the GPTQ inequalities are asserted.  Diagonal weighting is NOT
    # guaranteed to beat unweighted MSE on the true objective — it minimises
    # a diagonal surrogate of it — and on this synthetic case it does not;
    # that is a property of the surrogate, not a failure of this module.
    better = e_gptq < e_rtn and e_gptq < e_plain
    ok &= better
    print(f"  ||(W-Wq)X^T||_F : unweighted {e_plain:.5g} / V3-style "
          f"{e_rtn:.5g} -> GPTQ {e_gptq:.5g} "
          f"({100 * (1 - e_gptq / e_rtn):.1f}% better than the V3-style "
          f"diagonal) {'OK' if better else 'FAIL'}")
    print(f"  (||W-Wq||_F rises {w_rtn:.4g} -> {w_gptq:.4g}: GPTQ trades "
          "weight fidelity for output fidelity, as designed)")

    print("--- 4: row chunking is exact ---")
    a = quant_linear_gptq(Wf, g=g, hess=fac, rowchunk=1 << 30)
    b = quant_linear_gptq(Wf, g=g, hess=fac, rowchunk=7)
    ok &= _qeq(a, b) and _qeq(a, gq)
    print(f"  rowchunk 7 == one-shot == default, bit-identical "
          f"{'OK' if _qeq(a, b) else 'FAIL'}")

    print("--- 5: the image packs and round-trips through the DDR row format ---")
    img, stride = W.pack_ddr_rows(gq["w4"], gq["m"], g)
    w4b, mb = W.unpack_ddr_rows(img, N, K, g)
    rt = (np.array_equal(w4b, gq["w4"]) and np.array_equal(mb, gq["m"])
          and stride == W.row_stride(K, g))
    ok &= rt
    print(f"  {N}x{K} g={g}: {stride} B/row, unpack == pack "
          f"{'OK' if rt else 'FAIL'}")

    print("--- 6: bad inputs are loud ---")
    bad = 0
    for kwargs, exc in (({"hess": None}, SystemExit),
                        ({"hess": np.eye(K + 8)}, SystemExit),
                        ({"hess": np.eye(K) * -1.0}, SystemExit),
                        ({"hess": np.full((K, K), np.nan)}, SystemExit),
                        ({"hess": np.zeros((K, K))}, SystemExit)):
        try:
            quant_linear_gptq(Wf, g=g, **kwargs)
        except exc:
            bad += 1
        except Exception as ex:                              # pragma: no cover
            print(f"  wrong exception for {kwargs}: {ex!r}")
    ok &= bad == 5
    print(f"  {bad}/5 rejected (missing / wrong K / negative / NaN / zero) "
          f"{'OK' if bad == 5 else 'FAIL'}")

    print("--- 7: a dead input channel is survivable ---")
    Hd = H.copy()
    Hd[3, :] = 0.0
    Hd[:, 3] = 0.0
    q = quant_linear_gptq(Wf, g=g, hess=Hd)
    fd = factor(Hd, name="dead")
    ok &= (fd.n_dead == 1 and _wire_same(q, rtn)
           and np.all(np.isfinite(_deq(q))))
    print(f"  1 dead channel: damp={fd.damp:.4g}, format unchanged, image "
          f"finite {'OK' if fd.n_dead == 1 else 'FAIL'}")

    print("\nGPTQ SELFTEST " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    print(__doc__)
