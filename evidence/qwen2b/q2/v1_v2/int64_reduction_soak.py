"""Hammer the exact reduction that tripped: acc = (w4*x8).sum(axis=2), int64.

Same shape and dtypes as the failing call in w4a8_ref.matvec_y32
(w4 (6144,16,128) int8 in [-8,7], x8 (1,16,128) int8, int64 accumulate).

Each iteration applies three checks:
  * the guard that actually tripped in production,  |acc|max < 2**31;
  * the arithmetic bound for these dtypes,          |acc|max <= g*8*127;
  * an INDEPENDENT re-reduction of the same operands into a freshly
    allocated array, compared ELEMENTWISE against the first one — this is a
    genuine second computation of the product-and-sum, not a second .max()
    over the same buffer.
Any hit on any check is an anomaly. A clean run is a null result: it says the
reduction did not misbehave here, under these conditions.
"""
import sys
import time

import numpy as np

rng = np.random.default_rng(int(sys.argv[1]))
N, NG, g = 6144, 16, 128
w4 = rng.integers(-8, 8, size=(N, NG, g)).astype(np.int8)
bad = 0
it = 0
t0 = time.time()
while time.time() - t0 < 240:
    x8 = rng.integers(-127, 128, size=(1, NG, g)).astype(np.int8)
    acc = (w4.astype(np.int64) * x8.astype(np.int64)).sum(axis=2)
    acc2 = (w4.astype(np.int64) * x8.astype(np.int64)).sum(axis=2)   # independent
    mx = int(np.abs(acc).max())
    if mx >= (1 << 31) or mx > g * 8 * 127 or not np.array_equal(acc, acc2):
        bad += 1
        print(f"ANOMALY it={it} |acc|max={mx} "
              f"elementwise_equal={bool(np.array_equal(acc, acc2))}", flush=True)
    it += 1
print(f"seed {sys.argv[1]}: {it} iterations, {bad} anomalies")
