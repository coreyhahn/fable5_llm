#!/usr/bin/env python3
"""Generate bit-exact matvec_engine TB vectors, parameterized by shape.

Companion to ref/gen_matvec_vectors.py, which is FROZEN at its four
stage-2 shapes; this one takes (N, K) on the command line so the Makefile
can drive shape sweeps from a single list.  Both emit the SAME 5-field
params.txt, and the numerics of both come from ref/w4a8_ref.py.

  <out>/params.txt : K NG SH NROWS BEATS_PER_ROW   (decimal, one line)
                     NG = cfg_ng = K//128 = the WEIGHT beat count.
                     BEATS_PER_ROW = NG + ceil(NG/32) scale beats
  <out>/x8.hex     : activation vector as 32-bit LE words, one hex/line
  <out>/beats.hex  : weight image, one 512-bit beat per line (hex, LE)
  <out>/y32.hex    : golden outputs, one 32-bit hex (two's complement)/line

ALL numerics come from ref/w4a8_ref.py — this script only formats them.

G3.3 (spec §5.1 S5, §5.2 S6) DELETED the two modes this generator used to
carry, and with them the 6th/7th params fields:

  * `g` on the command line and `G64` in params.txt — the W4 G=64 "v2" row
    format.  At NG = 96 its ceil(2*NG/32) scale-beat count needs 6 bits and
    overflows matvec_engine's 2-bit n_scale_beats, so g64 is unrepresentable
    at the 9B row geometry, not merely unused.
  * `w8` on the command line and `W8` in params.txt, together with the
    `maxmag` / `maxmag128` DIRECTED kinds, which existed to sit exactly on
    the W8 lane array's envelope (per-lane 15 b, 2/8/32/64-lane sums
    16/18/20/21 b) and to prove the generator refuses the illegal code -128.
    The W8 engine mode is gone from this bitstream, so those vectors have no
    DUT to drive.  The HOST-side W8 law is untouched (spec §3.3):
    ref/w4a8_ref.py's quantize_weights8 / pack_ddr_rows8 / matvec_y32_w8
    still serve build_034 / build_035 and are still self-tested there.

Usage: gen_matvec_v2_vectors.py <out_dir> <seed> <N> <K>
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "ref"))
from w4a8_ref import (K_PER_WBEAT, matvec_y32, pack_ddr_rows,  # noqa: E402
                      quantize_acts, quantize_weights, row_beats)

G = 128          # the one group size this engine has


def main():
    out, seed = sys.argv[1], int(sys.argv[2])
    N, K = int(sys.argv[3]), int(sys.argv[4])
    assert K % G == 0, f"K={K} is not a multiple of the group size {G}"
    os.makedirs(out, exist_ok=True)
    rng = np.random.default_rng(seed)
    W = rng.normal(0, 0.02, (N, K))
    x = rng.normal(0, 1.0, K)

    x8, _xs = quantize_acts(x)
    wq, m, e, sh = quantize_weights(W, g=G)
    y32 = matvec_y32(wq, m, sh, x8)
    img, stride = pack_ddr_rows(wq, m)
    wb, sb = row_beats(K, G)
    assert wb == K // K_PER_WBEAT
    assert stride == (wb + sb) * 64
    bpr = wb + sb
    ng = K // K_PER_WBEAT          # cfg_ng: one group per weight beat

    with open(f"{out}/params.txt", "w") as f:
        f.write(f"{K} {ng} {sh} {N} {bpr}\n")
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
    print(f"vectors: seed={seed} N={N} K={K} g={G} ng={ng} "
          f"wbeats={wb} sbeats={sb} sh={sh} e={e} beats={len(img) // 64}")


if __name__ == "__main__":
    main()
