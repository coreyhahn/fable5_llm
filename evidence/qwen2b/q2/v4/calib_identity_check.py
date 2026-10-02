#!/usr/bin/env python3
"""Is the V4 calibration change ADDITIVE?  (Track Q task 8b, step 0)

`ref/calib_stats.py` grew an opt-in `--hessian` collector.  Two things must
be true and are checked here against runs of the ACTUAL code:

  1. the V3 salience vectors it writes are bit-identical to HEAD's, and the
     `--hessian` branch does not perturb them either;
  2. the `h2/` second moments really are the diagonals of the stored
     Hessians (both quantizers weight their scale search by them, and the
     "a diagonal Hessian cannot feed back" bit-identity is only meaningful
     if the two really are the same numbers).

The npz FILES cannot be compared directly — `np.savez` is a zip with
embedded timestamps and `_meta_json` carries `generated`/`seconds_*`/`host`
— so this compares the arrays every consumer actually reads.

CONTROL, and it is load-bearing: the collector's output is only reproducible
at a FIXED torch thread count (a threaded GEMM's reduction order depends on
it).  So the code comparison is run at matched threads, and the thread-count
effect is measured separately to show what "not identical" looks like.

    a = HEAD's collector,            threads=16   (/tmp/calib_base16.npz)
    b = this branch, no --hessian,   threads=16   (/tmp/calib_new16.npz)
    c = this branch, --hessian,      threads=16   (ref/calib_stats_2b_h.npz)
    d = HEAD's collector,            threads=10   (/tmp/calib_base_head.npz)

Run on snoke:  /home/cah/.venv/bin/python evidence/qwen2b/q2/v4/calib_identity_check.py
"""
import socket
import sys

sys.path.insert(0, "/home/cah/r2d2/code/fpga/fable5_llm/ref")

import numpy as np                                              # noqa: E402
import calib_stats as CS                                        # noqa: E402

V4 = "/home/cah/r2d2/code/fpga/fable5_llm/ref/calib_stats_2b_h.npz"
RUNS = [("HEAD/16", "/tmp/calib_base16.npz"),
        ("V4/16", "/tmp/calib_new16.npz"),
        ("V4+hess/16", V4),
        ("HEAD/10", "/tmp/calib_base_head.npz")]


def cmp(an, a, bn, b):
    assert set(a) == set(b), "key sets differ"
    nid, worst, wk = 0, 0.0, ""
    for k in sorted(a):
        assert a[k].shape == b[k].shape and a[k].dtype == b[k].dtype, k
        if np.array_equal(a[k], b[k]):
            nid += 1
        else:
            d = float(np.abs(a[k].astype(np.float64) - b[k].astype(np.float64)).max()
                      / (np.abs(a[k]).max() + 1e-300))
            if d > worst:
                worst, wk = d, k
    print(f"{an:11s} vs {bn:11s}: {nid}/{len(a)} salience vectors "
          "BIT-IDENTICAL" + (f"; worst relative delta {worst:.3e} ({wk})"
                             if nid < len(a) else ""))


def main():
    print(f"host {socket.gethostname()}")
    v = {n: CS.load(p) for n, p in RUNS}
    print("\n--- 1. the salience vectors ---")
    cmp("HEAD/16", v["HEAD/16"], "V4/16", v["V4/16"])            # the CODE diff
    cmp("V4/16", v["V4/16"], "V4+hess/16", v["V4+hess/16"])      # the --hessian branch
    cmp("HEAD/16", v["HEAD/16"], "HEAD/10", v["HEAD/10"])        # the CONTROL

    print("\n--- 2. h2 IS the stored Hessian diagonal ---")
    h2 = CS.load_h2(V4)
    st = CS.HessStore(V4)
    ok = sum(int(np.array_equal(h2[s], np.diag(st.raw(s)).astype(np.float32)))
             for s in st.sites)
    print(f"{len(h2)} h2 vectors, {len(st.sites)} Hessian sites, key sets "
          f"match: {sorted(h2) == st.sites};  h2 == diag(hess) on "
          f"{ok}/{len(st.sites)} sites")

    # a channel with zero second moment never fired on the calibration
    # corpus; GPTQ has no information about it (see gptq.factor).  Count them
    # across the whole model, since the quantizer's handling of them is a
    # documented design choice and "how many are there" is the fact behind it.
    dead = {s: int((h2[s] <= 0).sum()) for s in st.sites}
    print(f"dead input channels (E[x^2] == 0) over all {len(dead)} sites: "
          f"{sum(dead.values())} of {sum(v.size for v in h2.values())}"
          + (f"  worst site {max(dead, key=dead.get)}" if sum(dead.values())
             else ""))

    print("\n--- 3. what the GPTQ factorization is handed (3 real sites) ---")
    for s in (st.sites[0], "layers.12.mlp_down_in", "lm_head"):
        H = st.raw(s)
        d = np.diag(H)
        ev = np.linalg.eigvalsh(H)
        damp = 0.01 * d.mean()
        print(f"  {s:28s} K={H.shape[0]:5d} diag mean={d.mean():.4g} "
              f"max/mean={d.max() / d.mean():6.1f}  eig min={ev.min():.3e} "
              f"max={ev.max():.4g}  cond(damped)="
              f"{(ev.max() + damp) / (ev.min() + damp):.3e}")
    st.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
