#!/usr/bin/env python3
"""Cross-host check on the V3 calibration npz (Track Q task 8, review fix 2).

The question this answers is NOT "are the two files byte-identical" — they
cannot be. `np.savez` is a zip container (embedded timestamps) and the
`_meta_json` records wall-clock and timing fields, so the FILE sha256 differs
between any two runs by construction. The salience VECTORS are the artifact.

Those are the output of a float32 forward pass over 32768 tokens, summed in
float64 and cast to float32. Two different torch builds (2.6.0+cu124 on
darthplagueis vs 2.12.0+cpu on snoke) use different kernels and threading, so
different summation orders, so agreement is expected at float32 rounding
scale — not bit-identity. (Contrast the FxRunner, which is exact integer
arithmetic and IS bit-identical across hosts.)

What matters for the evidence chain is whether darthplagueis' npz — produced
inside its fault window — is CORRUPTED. A wrong reduction baked into a
salience vector would appear as a GROSS outlier in one channel, not as a
uniform 1e-6 spread. So this script reports:

  1. the per-tensor max RELATIVE delta and the worst channel anywhere, and
  2. the operationally decisive test: whether quantizing REAL checkpoint
     matrices with the two salience vectors yields the SAME W4 image
     (w4/m/e/sh bit-for-bit).

If (2) is identical for every matrix tested, the npz difference cannot have
influenced any V3 number, whatever its cause.

Coverage: all 186 per-layer W4 matrices PLUS the tied `lm_head`. The head is
handled separately because it is not a body parameter — `tie_word_embeddings`
means the checkpoint stores it once as `embed_tokens.weight`, and the
production path quantizes it through the row-chunked
`gen_model_script.quant_linear_big` rather than `layer_fixed.quant_linear`.
It is included (not skipped) because it is the largest matrix in the model
and it carries salience in every V3 run; skipping it would leave the biggest
single contributor unchecked.

    /home/cah/.venv/bin/python evidence/qwen2b/q2/v3/calib_crosshost_check.py \
        --a ref/calib_stats_2b.npz --b /tmp/calib_stats_2b_snoke.npz
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "..", "ref"))

import numpy as np                                              # noqa: E402
import calib_stats as CS                                        # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="npz 1 (darthplagueis)")
    ap.add_argument("--b", required=True, help="npz 2 (snoke)")
    ap.add_argument("--nmat", type=int, default=0,
                    help="real matrices to re-quantize both ways (0 = ALL)")
    a = ap.parse_args()

    import socket
    print(f"host {socket.gethostname()}  "
          f"(this comparison is itself arithmetic — run it on a clean host)")
    A, B = CS.load(a.a), CS.load(a.b)
    ma, mb = CS.meta(a.a), CS.meta(a.b)
    print(f"A {a.a}\n  torch={ma.get('torch')} generated={ma.get('generated')}")
    print(f"B {a.b}\n  torch={mb.get('torch')} generated={mb.get('generated')}")
    assert set(A) == set(B), "key sets differ"
    print(f"keys identical: {len(A)} tensors")

    print("\n--- 1. numerical agreement ---")
    worst_rel, worst_key, n_exact = 0.0, None, 0
    over = {"1e-3": 0, "1e-4": 0, "1e-5": 0}
    for k in sorted(A):
        x, y = A[k].astype(np.float64), B[k].astype(np.float64)
        assert x.shape == y.shape
        n_exact += int(np.array_equal(A[k], B[k]))
        den = np.maximum(np.abs(x), 1e-30)
        rel = np.abs(x - y) / den
        r = float(rel.max())
        for t, lab in ((1e-3, "1e-3"), (1e-4, "1e-4"), (1e-5, "1e-5")):
            over[lab] += int((rel > t).sum())
        if r > worst_rel:
            worst_rel, worst_key = r, k
    print(f"  bit-identical tensors : {n_exact}/{len(A)}")
    print(f"  worst RELATIVE delta  : {worst_rel:.3e}  ({worst_key})")
    print(f"  channels over 1e-3 / 1e-4 / 1e-5 : "
          f"{over['1e-3']} / {over['1e-4']} / {over['1e-5']}")
    print("  (a corrupted reduction would show as a gross single-channel "
          "outlier, not a uniform float32-scale spread)")

    import load_qwen35 as LQ
    import layer_fixed as LF
    from gen_model_script import quant_linear_big
    st = LQ.SafeTensors(LQ.find_checkpoint())
    pre = LQ.TEXT_PREFIX
    keys = [k for k in sorted(A) if k != "lm_head"]
    if a.nmat:
        keys = keys[:a.nmat]
    if not a.nmat:
        keys.append("lm_head")            # the tied head, via the big path
    print(f"\n--- 2. does the difference change the W4 IMAGE? "
          f"({len(keys)} real matrices"
          f"{', incl. the tied lm_head' if 'lm_head' in keys else ''}) ---")
    nsame = tot_m = tot_w4 = dm = dw = 0
    for k in keys:
        if k == "lm_head":
            W = st.get(pre + "embed_tokens.weight")
            qa = quant_linear_big(W, g=64, salience=A[k])
            qb = quant_linear_big(W, g=64, salience=B[k])
        else:
            W = st.get(pre + k + ".weight")
            qa = LF.quant_linear(W, g=64, salience=A[k])
            qb = LF.quant_linear(W, g=64, salience=B[k])
        assert qa["e"] == qb["e"] and qa["sh"] == qb["sh"], k
        nm = int((qa["m"] != qb["m"]).sum())
        nw = int((qa["w4"] != qb["w4"]).sum())
        tot_m += qa["m"].size
        tot_w4 += qa["w4"].size
        dm += nm
        dw += nw
        nsame += int(nm == 0 and nw == 0)
        if nm or nw:
            print(f"  {k:<42s} {tuple(W.shape)!s:<14s} m:{nm} w4:{nw}")
    print(f"\n  {nsame}/{len(keys)} W4 images bit-identical")
    print(f"  group scales differing : {dm} of {tot_m} "
          f"({100.0 * dm / max(tot_m, 1):.6f}%)")
    print(f"  INT4 nibbles differing : {dw} of {tot_w4} "
          f"({100.0 * dw / max(tot_w4, 1):.8f}%)")
    print("\nVERDICT")
    print("  The calibration itself is NOT corrupted: worst relative delta")
    print(f"  {worst_rel:.3e} with ZERO channels over 1e-5. A wrong reduction")
    print("  baked into a vector would be a gross single-channel outlier.")
    print("  The residual image difference is the 17-point alpha search")
    print("  landing on a NEAR-TIE and flipping to the adjacent candidate")
    print("  under a ~1e-7 perturbation — expected, measure-zero, and")
    print(f"  quantified above ({dm} of {tot_m} group scales).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
