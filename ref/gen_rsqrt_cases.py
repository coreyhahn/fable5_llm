#!/usr/bin/env python3
"""Bit-exact test cases for fx_rsqrt: lines of v(48b) p(6b) r(32b) e(8b) hex."""
import sys
import numpy as np
import fixedpoint as fp

out, seed, n = sys.argv[1], int(sys.argv[2]), 500
rng = np.random.default_rng(seed)
with open(out, "w") as f:
    for i in range(n):
        bits = int(rng.integers(1, 48))
        v = int(rng.integers(1, 1 << bits))
        P = int(rng.integers(0, 48))
        r, e = fp.rsqrt_q(v, P)
        f.write(f"{v:012x} {P:02x} {r:08x} {e & 0xFF:02x}\n")
print(f"rsqrt cases: {out}")
