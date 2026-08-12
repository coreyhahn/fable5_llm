#!/usr/bin/env python3
"""Generate bit-exact test vectors for the matvec_engine Verilator TB.

For a given (seed, N, K): random fp weights+activations -> quantize per
quant_spec.md -> DDR row image (pack_ddr_rows) -> emit:
  <out>/params.txt   : K NG SH NROWS BEATS_PER_ROW (decimal, one line)
  <out>/x8.hex       : activation vector as 32-bit LE words, one hex/line
  <out>/beats.hex    : weight image, one 512-bit beat per line (hex, LE)
  <out>/y32.hex      : golden outputs, one 32-bit hex (two's complement)/line

Usage: gen_matvec_vectors.py <out_dir> <seed> <N> <K>
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from w4a8_ref import G, quantize_weights, quantize_acts, matvec_y32, pack_ddr_rows


def main():
    out, seed, N, K = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
    os.makedirs(out, exist_ok=True)
    rng = np.random.default_rng(seed)
    W = rng.normal(0, 0.02, (N, K))
    x = rng.normal(0, 1.0, K)

    w4, m, e, sh = quantize_weights(W)
    x8, _xs = quantize_acts(x)
    y32 = matvec_y32(w4, m, sh, x8)
    img, stride = pack_ddr_rows(w4, m)
    NG = K // G
    assert stride % 64 == 0
    bpr = stride // 64
    assert bpr == NG + 1, f"beats/row {bpr} != NG+1 (layout assumption)"

    with open(f"{out}/params.txt", "w") as f:
        f.write(f"{K} {NG} {sh} {N} {bpr}\n")
    with open(f"{out}/x8.hex", "w") as f:
        xb = x8.astype(np.int8).tobytes()
        xb += b"\x00" * (-len(xb) % 4)
        for i in range(0, len(xb), 4):
            f.write(f"{int.from_bytes(xb[i:i+4], 'little'):08x}\n")
    with open(f"{out}/beats.hex", "w") as f:
        for i in range(0, len(img), 64):
            f.write(f"{int.from_bytes(img[i:i+64], 'little'):0128x}\n")
    with open(f"{out}/y32.hex", "w") as f:
        for v in y32:
            f.write(f"{int(v) & 0xFFFFFFFF:08x}\n")
    print(f"vectors: seed={seed} N={N} K={K} NG={NG} sh={sh} beats={len(img)//64}")


if __name__ == "__main__":
    main()
