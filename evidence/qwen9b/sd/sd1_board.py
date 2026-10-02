#!/usr/bin/env python3
"""sd1_board.py — Task SD1 §3: decompose RD9 §10.2a's board-vs-census 9.9 %.

  python evidence/qwen9b/sd/sd1_board.py

Arithmetic ONLY, over numbers already printed in committed logs (each is
parsed from its log here, not retyped):
  * evidence/qwen9b/g6/020_perf_census_two_lanes.log  the board's L_LCYC
  * evidence/qwen9b/sd/003_sizing_fix2.log            the .e4 chip lane,
    the like-for-like comparand, ALU+VN, the hold difference
Stdout only.
"""
import os
import re

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", ".."))
B = f"{REPO}/evidence/qwen9b/g6/020_perf_census_two_lanes.log"
S = f"{REPO}/evidence/qwen9b/sd/003_sizing_fix2.log"
NTOK = 6
MS = 250000.0


def find(path, rx):
    for line in open(path):
        m = re.search(rx, line)
        if m:
            return m
    raise KeyError(rx)


board = int(find(B, r"L_LCYC\s+(\d+) cycles").group(1)) / NTOK
e4 = float(find(S, r"lane total ([\d.]+) cyc/token").group(1))
like = float(find(S, r"like-for-like comparand .* = ([\d.]+) cyc").group(1))
m = find(S, r"ALU\+VN = ([-+\d.]+) = .*remainder ([-+\d.]+) cyc")
aluvn, hold = float(m.group(1)), float(m.group(2))
print(f"board L_LCYC per token      {board:14.2f} cyc = {board / MS:.3f} ms")
print(f".e4 chip lane per token     {e4:14.2f} cyc = {e4 / MS:.3f} ms")
print(f"like-for-like comparand     {like:14.2f} cyc = {like / MS:.3f} ms")
gap = board - like
print(f"board - comparand           {gap:+14.2f} cyc = {gap / MS:+.3f} ms = "
      f"{100 * gap / like:+.3f} % (RD9 §10.2a's -9.91 %)")
parts = [("schedule: ALU + VN rows (the command-list difference)", aluvn),
         ("hold difference (.e4 SLD hold - census F2 hold)", hold),
         ("board vs chip TB on the same .e4 stream", board - e4)]
for name, v in parts:
    print(f"  {name:55s} {v:+14.2f} cyc = {v / MS:+.4f} ms = "
          f"{100 * v / gap:7.3f} % of the gap = {100 * v / like:+.3f} pp")
s = sum(v for _n, v in parts)
print(f"  {'SUM':55s} {s:+14.2f}   residual {gap - s:+.2f} cyc")
