#!/usr/bin/env python3
"""sd1_fix1_shares.py — Task SD1 fix round 1: two pieces of arithmetic the
memo needs, over numbers already printed in committed logs (parsed here).

  python evidence/qwen9b/sd/sd1_fix1_shares.py

1. Review Important 2: the size of the round-0 FITTED terms against the
   board gap — the 192 SHIFT32W x 10 cycles, and the whole inferred .txt-only
   fixed overhead (003_sizing_fix2.log:91), each in cycles, ms and % of
   board - like (005_board_decomposition.log:16).
2. The per-rewrite grouping (a)-(d) of the E1-priced list difference, from
   the key lines of 014_e1_analysis.log section 2.
Stdout only.
"""
import os
import re

R = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", "..", ".."))
S3 = f"{R}/evidence/qwen9b/sd/003_sizing_fix2.log"
S5 = f"{R}/evidence/qwen9b/sd/005_board_decomposition.log"
S14 = f"{R}/evidence/qwen9b/sd/014_e1_analysis.log"
MS = 250000.0


def find(path, rx):
    for line in open(path):
        m = re.search(rx, line)
        if m:
            return m
    raise KeyError(rx)


gap = float(find(S5, r"board - comparand\s+([-+\d.]+) cyc").group(1))
ovh = float(find(S3, r"residual - II\*n = ([\d.]+)").group(1))
m = find(S3, r"= ([\d.]+) for (\d+) SHIFT32W -> ([\d.]+) cyc each")
w = float(m.group(1))
print(f"board - like = {gap:+.2f} cyc = {gap / MS:+.4f} ms")
for name, v in (("fitted SHIFT32W overhead (192 x 10)", w),
                ("whole inferred .txt-only fixed overhead", ovh)):
    print(f"  {name:42s} {v:10.1f} cyc = {v / MS:.5f} ms = "
          f"{100 * v / abs(gap):.3f} % of |board - like|")

grp = {"a": 0.0, "b": 0.0, "c": 0.0, "d": 0.0}
rx = re.compile(r"^  (ALU|VN)\|(\S+)\s+dn\s+[-+]\d+ x\s+[\d.]+ =\s+([-+\d.]+)")
seen = 0
for line in open(S14):
    mm = rx.match(line)
    if not mm:
        continue
    seen += 1
    k, v = mm.group(2), float(mm.group(3))
    if k.startswith("SHIFT32W") or k in ("SHIFT32|2048", "SHIFT32|1024",
                                         "SHIFT32|32"):
        grp["a"] += v
    elif k.startswith("SILU32"):
        grp["b"] += v
    elif k in ("DYNQ16|128", "SHIFT32|128", "SCALE|128", "EPS-NORM|128"):
        grp["c"] += v
    elif k.startswith("EMUL32"):
        grp["d"] += v
    else:
        raise SystemExit(f"unassigned key {k}")
assert seen == 13, seen
names = {"a": "(a) fused dequants removed", "b": "(b) SILU32 re-chunk",
         "c": "(c) DN block-float pair", "d": "(d) attention probe + real"}
for g in "abcd":
    print(f"  {names[g]:30s} {grp[g]:+14.2f} cyc = {grp[g] / MS:+.4f} ms")
print(f"  {'sum':30s} {sum(grp.values()):+14.2f} cyc")
