#!/usr/bin/env python3
"""sd1_e1_analyze.py — Task SD1 fix round 1, E1: §3 on MEASURED per-key costs.

  FABLE5_MODEL=9b python evidence/qwen9b/sd/sd1_e1_analyze.py

No fitted parameter anywhere.  Inputs (each parsed from its log / file here):
  * evidence/qwen9b/sd/013_e1_run.log      per-key census cost, 4 seeds x 4
  * evidence/qwen9b/sd/003_sizing_fix2.log the .e4 chip per-key costs and
    per-opcode lane rows, the like-for-like comparand, SLD and F2 hold
  * evidence/qwen9b/s4/census_t14a.txt     the .txt census ALU / VN totals
  * evidence/qwen9b/g6/020_perf_census_two_lanes.log  the board L_LCYC
  * the two command lists, recounted (sd1_common)
The residuals below are DIFFERENCES OF INDEPENDENT MEASUREMENTS, so they can
be non-zero; none is zero by construction.
"""
import collections
import re

import sd1_common as C

R = C.REPO
E1 = f"{R}/evidence/qwen9b/sd/013_e1_run.log"
S3 = f"{R}/evidence/qwen9b/sd/003_sizing_fix2.log"
T14A = f"{R}/evidence/qwen9b/s4/census_t14a.txt"
BRD = f"{R}/evidence/qwen9b/g6/020_perf_census_two_lanes.log"
NTOK = 6
MS = 250000.0


def kparse(s):
    p = s.split("|")
    return tuple(int(x) if x.isdigit() else x for x in p)


# ---- E1 per-key costs ------------------------------------------------
tot = collections.defaultdict(int)
cnt = collections.defaultdict(int)
per_seed = collections.defaultdict(dict)
mn, mx = {}, {}
rx = re.compile(r"^E1 seed=(\d) key=(\S+) row=\w+ count=(\d+) total=(\d+) "
                r"mean=\d+ min=(\d+) max=(\d+) rc=0 \| TB_LAYER_CENSUS PASS")
for line in open(E1):
    m = rx.match(line)
    if m:
        k = kparse(m.group(2))
        tot[k] += int(m.group(4))
        cnt[k] += int(m.group(3))
        per_seed[k][int(m.group(1))] = int(m.group(4)) / int(m.group(3))
        mn[k] = min(mn.get(k, 1 << 60), int(m.group(5)))
        mx[k] = max(mx.get(k, 0), int(m.group(6)))
cost = {k: tot[k] / cnt[k] for k in tot}
assert len(cost) == 27 and all(len(v) == 4 for v in per_seed.values())

# ---- the .e4 chip per-key costs (003 section A) ------------------------
chip = {}
ra = re.compile(r"^  (\('(?:ALU|VN)'.*?\))\s+([\d.]+)\s+(\d+)\s+(\d+)\s+([\d.]+)")
for line in open(S3):
    m = ra.match(line)
    if m:
        chip[eval(m.group(1))] = (float(m.group(5)), int(m.group(3)),
                                  int(m.group(4)))

print("=== E1 per-key census cost (busy_cmp cycles/command; 4 seeds x 4 "
      "instances) vs the .e4 chip timeline")
print(f"  {'key':34s} {'s1':>9s} {'s2':>9s} {'s3':>9s} {'s4':>9s} "
      f"{'mean':>9s} {'min':>6s} {'max':>6s} {'chip':>9s} {'E1-chip':>8s}")
for k in sorted(cost, key=str):
    c = chip.get(k)
    cs = f"{c[0]:9.1f} {cost[k] - c[0]:+8.2f}" if c else f"{'—':>9s} {'':>8s}"
    print(f"  {'|'.join(map(str, k)):34s} "
          + " ".join(f"{per_seed[k][s]:9.2f}" for s in (1, 2, 3, 4))
          + f" {cost[k]:9.2f} {mn[k]:6d} {mx[k]:6d} {cs}")

# ---- the two lists -----------------------------------------------------
txt = collections.Counter()
for (st, ln, op, a0, a1, a2) in C.txt_steps():
    if st == 1:
        txt[C.key_of(op, a0, a1, a2)] += 1
e4 = collections.Counter()
for (b, i, op, a0, a1, a2) in C.seq_cmds(C.seq_records()):
    if b == 1:
        e4[C.key_of(op, a0, a1, a2)] += 1
for k in set(txt) | set(e4):
    if k[0] in ("ALU", "VN"):
        assert k in cost, f"no E1 cost for {k}"


def price(lst, kind):
    return sum(n * cost[k] for k, n in lst.items() if k[0] == kind)


def grab(path, rxs):
    for line in open(path):
        m = re.search(rxs, line)
        if m:
            return m
    raise KeyError(rxs)


cen = {}
for line in open(T14A):
    m = re.match(r"^LAYER_CENSUS\s+\d+\s+(ALU|VN)\s+\d+\s+(\d+)", line)
    if m and m.group(1) not in cen:
        cen[m.group(1)] = int(m.group(2)) / NTOK
chip_row = {}
for line in open(S3):
    m = re.match(r"^  (ALU|VN)\s+([\d.]+)\s+", line)
    if m and m.group(1) not in chip_row:
        chip_row[m.group(1)] = float(m.group(2))
print("\n=== 1. each list at the E1 costs vs the instrument that ran it "
      "(cyc/token)")
for kind in ("ALU", "VN"):
    pt, pe = price(txt, kind), price(e4, kind)
    print(f"  {kind:3s} .txt list at E1 {pt:12.2f}  census_t14a measured "
          f"{cen[kind]:12.2f}  residual {cen[kind] - pt:+9.2f}")
    print(f"  {kind:3s} .e4  list at E1 {pe:12.2f}  chip timeline measured "
          f"{chip_row[kind]:12.2f}  residual {chip_row[kind] - pe:+9.2f}")

print("\n=== 2. the list difference priced at E1 costs, key by key "
      "(+ = the .e4 costs more)")
sig = 0.0
for k in sorted(set(txt) | set(e4), key=str):
    if k[0] not in ("ALU", "VN") or txt[k] == e4[k]:
        continue
    d = (e4[k] - txt[k]) * cost[k]
    sig += d
    print(f"  {'|'.join(map(str, k)):34s} dn {e4[k] - txt[k]:+6d} x "
          f"{cost[k]:9.2f} = {d:+13.2f}")
print(f"  SIGMA (E1-priced list difference) {sig:+.2f} cyc = "
      f"{sig / MS:+.4f} ms")
meas = (chip_row["ALU"] + chip_row["VN"]) - (cen["ALU"] + cen["VN"])
print(f"  measured ALU+VN row difference (chip .e4 - census .txt) "
      f"{meas:+.2f} cyc;  measured - SIGMA = {meas - sig:+.2f} cyc")

print("\n=== 3. the 9.9 % on measured costs")
board = int(grab(BRD, r"L_LCYC\s+(\d+) cycles").group(1)) / NTOK
lane = float(grab(S3, r"lane total ([\d.]+) cyc/token").group(1))
like = float(grab(S3, r"like-for-like comparand .* = ([\d.]+) cyc").group(1))
f2 = float(grab(S3, r"nodrain F2 hold ([\d.]+)\)").group(1))
sld = float(grab(S3, r"^  SLD\s+([\d.]+)").group(1))
sldt = sld - f2
gap = board - like
res_b = gap - sig - sldt
res_c = (lane - like) - sig - sldt
print(f"  board {board:.2f}  chip lane {lane:.2f}  like-for-like {like:.2f} "
      f"(cyc/token)")
print(f"  board - like = {gap:+.2f} cyc = {gap / MS:+.4f} ms = "
      f"{100 * gap / like:+.3f} %")
print(f"    SIGMA, the E1-priced list difference   {sig:+13.2f} = "
      f"{100 * sig / gap:8.3f} % of the gap")
print(f"    SLD-hold term (.e4 SLD {sld:.1f} - census F2 {f2:.1f})  "
      f"{sldt:+13.2f} = {100 * sldt / gap:8.3f} %")
print(f"    RESIDUAL = board - like - SIGMA - SLD term  {res_b:+13.2f} = "
      f"{100 * res_b / gap:8.3f} % = {res_b / MS:+.4f} ms")
print(f"    of which board - chip lane {board - lane:+.2f}; chip-side "
      f"residual (lane - like - SIGMA - SLD term) {res_c:+.2f}")
print("\nSD1_E1_ANALYZE: DONE")
