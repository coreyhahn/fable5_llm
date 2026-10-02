#!/usr/bin/env python3
"""Is the 108-step fixed-point probe able to resolve V3 vs V4 at all?

Task 8b's review asked for the tail statistics and an exact paired test
alongside the raw top-1 counts, because "85 vs 86" invites a reading the
probe cannot support.  This parses the per-step `rank=[...]` arrays straight
out of the three committed fidelity logs (V2 / V3 / V4, all S=4 g64 mse) and
computes:

  * rank max / sum / mean / p90 — the tail, which top-1 hides entirely;
  * McNemar's exact (binomial) test on the paired per-step outcomes, which is
    the right test here: the same 108 golden steps are scored by both
    quantizers, so the pairs are matched and only the disagreements carry
    information.

    python3 evidence/qwen2b/q2/v4/fixed_significance.py    # from the repo root
"""
import ast
import math
import os
import re
import sys

LOGS = [("V2", "evidence/qwen2b/q2/v1_v2/fixed_g64_S4.log"),
        ("V3", "evidence/qwen2b/q2/v3/fixed_v3_g64_S4.log"),
        ("V4", "evidence/qwen2b/q2/v4/fixed_v4gptq_g64_S4.log")]


def ranks(path):
    """Every step's rank of the golden token, in prompt order."""
    out = []
    for m in re.finditer(r"rank=(\[[^\]]*\])", open(path).read()):
        out += ast.literal_eval(m.group(1))
    return out


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(math.ceil(q / 100.0 * len(v))) - 1)]


def mcnemar(a, b):
    """Exact two-sided binomial test on the discordant pairs (b, c)."""
    nb = sum(1 for x, y in zip(a, b) if x == 0 and y != 0)   # a right, b wrong
    nc = sum(1 for x, y in zip(a, b) if x != 0 and y == 0)   # b right, a wrong
    n = nb + nc
    if n == 0:
        return nb, nc, 1.0
    k = min(nb, nc)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2.0 ** n * 2.0
    return nb, nc, min(1.0, p)


def main():
    r = {}
    for tag, path in LOGS:
        if not os.path.exists(path):
            raise SystemExit(f"missing {path}")
        r[tag] = ranks(path)
        assert len(r[tag]) == 108, (tag, len(r[tag]))
    print(f"{'config':6s} {'top-1':>8s} {'rank max':>9s} {'rank sum':>9s} "
          f"{'mean':>7s} {'p90':>5s}")
    for tag, _ in LOGS:
        v = r[tag]
        print(f"{tag:6s} {sum(1 for x in v if x == 0):5d}/108 {max(v):9d} "
              f"{sum(v):9d} {sum(v) / len(v):7.3f} {pct(v, 90):5d}")
    print("\nMcNemar exact (paired over the same 108 golden steps):")
    for x, y in (("V2", "V3"), ("V3", "V4"), ("V2", "V4")):
        nb, nc, p = mcnemar(r[x], r[y])
        print(f"  {x} vs {y}: b={nb} (only {x} right)  c={nc} (only {y} right)"
              f"  p={p:.3f}"
              + ("   <- not resolvable at p<0.05" if p >= 0.05 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
