#!/usr/bin/env python3
"""Generate bit-exact matvec_engine TB vectors for the v2 row format.

Companion to ref/gen_matvec_vectors.py (which is frozen at g=128 and emits a
5-field params.txt).  This one takes the group size on the command line and
emits a 6-field params.txt so tb_matvec can drive cfg_g64:

  <out>/params.txt : K NG SH NROWS BEATS_PER_ROW G64   (decimal, one line)
                     NG = WEIGHT beats per row = K//128 (cfg_ng, both modes)
                     BEATS_PER_ROW = weight beats + scale beats
                     G64 = 0 (g=128 legacy) | 1 (g=64)
  <out>/x8.hex     : activation vector as 32-bit LE words, one hex/line
  <out>/beats.hex  : weight image, one 512-bit beat per line (hex, LE)
  <out>/y32.hex    : golden outputs, one 32-bit hex (two's complement)/line

ALL numerics come from ref/w4a8_ref.py — this script only formats them.

Usage: gen_matvec_v2_vectors.py <out_dir> <seed> <N> <K> <g>
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "ref"))
from w4a8_ref import (K_PER_WBEAT, matvec_y32, pack_ddr_rows,  # noqa: E402
                      quantize_acts, quantize_weights, row_beats)


def main():
    out, seed = sys.argv[1], int(sys.argv[2])
    N, K, g = int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
    os.makedirs(out, exist_ok=True)
    rng = np.random.default_rng(seed)
    W = rng.normal(0, 0.02, (N, K))
    x = rng.normal(0, 1.0, K)

    w4, m, e, sh = quantize_weights(W, g=g)
    x8, _xs = quantize_acts(x)
    y32 = matvec_y32(w4, m, sh, x8)
    img, stride = pack_ddr_rows(w4, m)

    wb, sb = row_beats(K, g)
    assert wb == K // K_PER_WBEAT
    assert stride == (wb + sb) * 64
    bpr = wb + sb

    with open(f"{out}/params.txt", "w") as f:
        f.write(f"{K} {wb} {sh} {N} {bpr} {1 if g == 64 else 0}\n")
    with open(f"{out}/x8.hex", "w") as f:
        xb = x8.astype(np.int8).tobytes()
        xb += b"\x00" * (-len(xb) % 4)
        for i in range(0, len(xb), 4):
            f.write(f"{int.from_bytes(xb[i:i + 4], 'little'):08x}\n")
    with open(f"{out}/beats.hex", "w") as f:
        for i in range(0, len(img), 64):
            f.write(f"{int.from_bytes(img[i:i + 64], 'little'):0128x}\n")
    with open(f"{out}/y32.hex", "w") as f:
        for v in y32:
            f.write(f"{int(v) & 0xFFFFFFFF:08x}\n")
    print(f"vectors: seed={seed} N={N} K={K} g={g} wbeats={wb} sbeats={sb} "
          f"NG{g}={K // g} sh={sh} e={e} beats={len(img) // 64}")


if __name__ == "__main__":
    main()
