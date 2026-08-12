#!/usr/bin/env python3
"""fx_silu bit-exact cases: x(21b) y(16b) hex per line (incl. extremes)."""
import sys
import numpy as np
import fixedpoint as fp

out, seed = sys.argv[1], int(sys.argv[2])
rng = np.random.default_rng(seed)
xs = list(rng.integers(-(1 << 20), (1 << 20), 400))
xs += [0, 1, -1, (1 << 20) - 1, -(1 << 20), 65535, -65536, 65536, -65537]
with open(out, "w") as f:
    for x in xs:
        y = int(np.clip(fp.silu_q(int(x)), -32768, 32767))
        f.write(f"{int(x) & 0x1FFFFF:06x} {y & 0xFFFF:04x}\n")
print(f"silu cases: {out}")
