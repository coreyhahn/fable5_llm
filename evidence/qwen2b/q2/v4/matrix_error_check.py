#!/usr/bin/env python3
"""Per-matrix OUTPUT error of the four W4 rules, on the real 2B checkpoint.

PPL says what the model does; this says what the QUANTIZER does, matrix by
matrix, in the units the quantizers are actually optimising:

    output error   ||(W - Wq) X^T||_F / sqrt(T) = sqrt( tr( D H D^T ) )
                   with D = Wq - W and H = E[x x^T] (T-normalised), i.e. the
                   per-token RMS of the error this matrix injects downstream
    weight error   ||W - Wq||_F

with H = E[x x^T] from `ref/calib_stats_2b_h.npz` (the same file every V4 PPL
run used).  Four rules, all the SAME wire format:

    V2   quant_linear_mse                       (unweighted MSE scale search)
    V3   quant_linear_mse(salience=mean|x|)     (Track Q task 8)
    V4h  quant_linear_mse(salience=sqrt(E[x^2]))(exact objective diagonal)
    V4   quant_linear_gptq(hess=H)              (V4h's scales + error feedback)

Run on snoke:  /home/cah/.venv/bin/python evidence/qwen2b/q2/v4/matrix_error_check.py
"""
import os
import socket
import sys
import time

REF = "/home/cah/r2d2/code/fpga/fable5_llm/ref"
sys.path.insert(0, REF)
os.environ.setdefault("FABLE5_MODEL", "2b")

import numpy as np                                              # noqa: E402
import calib_stats as CS                                        # noqa: E402
import gptq as GQ                                               # noqa: E402
import layer_fixed as LF                                        # noqa: E402
import perplexity_eval as PE                                    # noqa: E402

NPZ = os.path.join(REF, "calib_stats_2b_h.npz")
HEAD_ROWS = 8192          # the tied head is 248320 rows; rows are independent
                          # (both rules are row-separable), so a row slice is
                          # an exact sample of it, not an approximation


def out_err(D, H):
    """||D X^T||_F / sqrt(T) = sqrt(tr(D H D^T)) with H = X^T X / T.

    H is T-NORMALISED, so this is the per-token RMS of the output error, not
    the raw Frobenius norm over the calibration set (the two differ by
    sqrt(T) = sqrt(32768)).  float64, chunked over rows.
    """
    tot = 0.0
    for r0 in range(0, D.shape[0], 2048):
        d = D[r0:r0 + 2048]
        tot += float(np.einsum("nk,nk->", d @ H, d))
    return float(np.sqrt(max(tot, 0.0)))


def main():
    print(f"host {socket.gethostname()}  npz {NPZ}")
    print(f"npz sha256 {PE.sha256_file(NPZ)}")
    src = PE.CkptSource(None)
    sal = CS.load(NPZ)
    st = CS.HessStore(NPZ)
    keys = ["layers.0.linear_attn.in_proj_qkv", "layers.0.linear_attn.out_proj",
            "layers.12.mlp.gate_proj", "layers.12.mlp.down_proj",
            "layers.19.self_attn.q_proj", "layers.19.self_attn.o_proj",
            "lm_head"]
    print(f"\n{'matrix':<34s} {'shape':>13s} | output error "
          f"||(W-Wq)X^T||_F/sqrt(T) (V4 vs V3) | weight error ||W-Wq||_F")
    rows = []
    for key in keys:
        name = ("embed_tokens.weight" if key == "lm_head" else key + ".weight")
        W = np.asarray(src.get(name), dtype=np.float32)
        if key == "lm_head":
            W = W[:HEAD_ROWS]
        t0 = time.time()
        H = st.raw(CS.hess_key(key))
        f = GQ.factor(H, name=key)
        qs = {
            "V2": LF.quant_linear_mse(W, g=64),
            "V3": LF.quant_linear_mse(W, g=64, salience=sal[key]),
            "V4h": LF.quant_linear_mse(W, g=64, salience=np.sqrt(f.diag)),
            "V4": GQ.quant_linear_gptq(W, g=64, hess=f),
        }
        e, w = {}, {}
        for tag, q in qs.items():
            D = GQ._deq(q) - W.astype(np.float64)
            e[tag] = out_err(D, H)
            w[tag] = float(np.linalg.norm(D))
        assert np.array_equal(qs["V4h"]["m"], qs["V4"]["m"]) and \
            qs["V4h"]["e"] == qs["V4"]["e"], "GPTQ moved a group scale"
        # how far apart ARE the two diagonals?  V3 weights by (mean|x|)^2,
        # V4h by E[x^2]; Jensen says the second is the larger, and the gap
        # grows with the tail.  d95 = the 95th percentile of the per-channel
        # ratio E[x^2] / (mean|x|)^2, i.e. how much heavier the tail channels
        # get weighted; scales = the share of group scales that actually moved.
        r = f.diag / np.maximum(sal[key].astype(np.float64) ** 2, 1e-300)
        diag_ratio = (float(np.median(r)), float(np.percentile(r, 95)),
                      float(r.max()))
        moved_m = float((qs["V3"]["m"] != qs["V4h"]["m"]).mean())
        rows.append((key, W.shape, e, w, diag_ratio, moved_m))
        print(f"{key:<34s} {str(W.shape):>13s} | "
              f"V2 {e['V2']:8.2f}  V3 {e['V3']:8.2f}  V4h {e['V4h']:8.2f}  "
              f"V4 {e['V4']:8.2f}  ({100 * (1 - e['V4'] / e['V3']):+6.1f}%) | "
              f"{w['V3']:7.3f} -> {w['V4']:7.3f}  [{time.time() - t0:.0f}s]",
              flush=True)
        print(f"{'':34s} {'':>13s} | E[x^2]/(mean|x|)^2 per channel: median "
              f"{diag_ratio[0]:.2f}  p95 {diag_ratio[1]:.2f}  max "
              f"{diag_ratio[2]:.1f};  V3->V4h moves {100 * moved_m:.1f}% of "
              "the group scales", flush=True)
    st.close()
    print()
    for a, b in (("V3", "V2"), ("V4h", "V3"), ("V4", "V4h"), ("V4", "V3")):
        r = [100 * (1 - x[2][a] / x[2][b]) for x in rows]
        print(f"  {a} vs {b}: output error {np.mean(r):+.1f}% mean "
              f"({min(r):+.1f}% .. {max(r):+.1f}%), better on "
              f"{sum(1 for v in r if v > 0)}/{len(r)} matrices")
    print(f"  the two diagonals: median ratio "
          f"{np.mean([x[4][0] for x in rows]):.2f}, p95 "
          f"{np.mean([x[4][1] for x in rows]):.2f}, max "
          f"{max(x[4][2] for x in rows):.1f} (mean over the 7); V3->V4h moves "
          f"{100 * np.mean([x[5] for x in rows]):.1f}% of the group scales")
    return 0


if __name__ == "__main__":
    sys.exit(main())
