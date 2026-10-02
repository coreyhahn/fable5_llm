#!/usr/bin/env python3
"""sd1_size.py — Task SD1 deliverable 3: size the lane delta from EXISTING logs.

  FABLE5_MODEL=9b python evidence/qwen9b/sd/sd1_size.py

No simulation.  Inputs, all already on disk:
  * evidence/qwen9b/bn/bn_timeline_model_9b_s1.csv — BN1's per-RECORD chip
    timeline of the .e4 stream (untracked for size; its sha256 is committed
    beside it and is CHECKED here before a row is read);
  * evidence/qwen9b/s4/census_t14a.txt — the layer census (.txt, DRAINING,
    Task 14-A netlist) per-opcode LCYC totals over 6 steps;
  * evidence/qwen9b/s4/census_s4shipped.txt — the same, pre-14A;
  * evidence/qwen9b/s4/075_census_nodrain_lat40.log — the NON-draining
    layer census (holds charged) totals;
  * the two command lists (sd1_common).

What it prints:
  A. the .e4 per-COMMAND lane cost.  A CMD record's window runs until the
     layer command's busy clears (docs/SEQ_ISA.md: CMD = "CSRWR to layer CMD
     + WAIT busy-clear"), so every busy_cmp cycle of a command falls in its
     own CMD row; the lane cycles found OUTSIDE CMD rows are printed.
  B. the per-opcode accounting identity, .e4 lane vs each layer census.
  C. the .txt VN list costed at the .e4's per-key VN costs, against the
     census's measured VN total — the per-command-cost test.
  D. the .txt ALU list costed at the .e4's per-key costs where the key
     exists in both lists; the residual that the .txt-ONLY keys must carry,
     and what that implies per command, against the vec_alu II rule.
  E. the per-substitution sizing (a)-(d), in cycles/token.
Read-only; stdout only.
"""
import collections
import re
import sys

import sd1_common as C
from sd1_common import SF, LR

REPO = C.REPO
CSV = f"{REPO}/evidence/qwen9b/bn/bn_timeline_model_9b_s1.csv"
CSV_SHA = f"{REPO}/evidence/qwen9b/bn/bn_timeline_model_9b_s1.csv.sha256"
T14A = f"{REPO}/evidence/qwen9b/s4/census_t14a.txt"
S4 = f"{REPO}/evidence/qwen9b/s4/census_s4shipped.txt"
ND40 = f"{REPO}/evidence/qwen9b/s4/075_census_nodrain_lat40.log"
NTOK = 6
MS = 250000.0
# vec_alu initiation interval per sub-op (rtl/vec_alu.sv:83-86): 2 for op 8
# (EMUL32) and op 9 (SHIFT32W), 1 for every other op.
II = {"EMUL32": 2, "SHIFT32W": 2}


def ms(c):
    return c / MS


# ---------------------------------------------------------------- inputs
want = open(CSV_SHA).read().split()[0]
got = C.sha256(CSV)
print(f"=== inputs\n  timeline csv sha256 {got}\n  committed .sha256    {want}  "
      f"{'MATCH' if got == want else 'MISMATCH'}")
assert got == want


def census_ops(path):
    """{op name: total LCYC over the 6 steps} from a LAYER_CENSUS table."""
    out = {}
    rx = re.compile(r"^LAYER_CENSUS\s+(\d+)\s+([A-Z][A-Z0-9]*)\s+(\d+)\s+(\d+)\s+(\d+)")
    for line in open(path):
        m = rx.match(line)
        if m and m.group(2) not in out:
            out[m.group(2)] = (int(m.group(3)), int(m.group(4)))
    return out


def grab(path, key):
    for line in open(path):
        if key in line:
            return int(line.split(key)[1].split()[0])
    raise KeyError(key)


t14a = census_ops(T14A)
s4 = census_ops(S4)
t14a_total = grab(T14A, "TOTAL_BUSY_CYCLES")
s4_total = grab(S4, "TOTAL_BUSY_CYCLES")
nd_total = grab(ND40, "TOTAL_BUSY_CYCLES")
nd_f2 = grab(ND40, "TOTAL_F2_HOLD_CYCLES")
print(f"  census_t14a TOTAL_BUSY {t14a_total}  census_s4shipped TOTAL_BUSY "
      f"{s4_total}  nodrain LAT40 TOTAL_BUSY {nd_total} F2_HOLD {nd_f2}")

# ---------------------------------------------------------------- A
recs = C.seq_records()
key_at = {}
for (b, i, op, a0, a1, a2) in C.seq_cmds(recs):
    key_at[i] = C.key_of(op, a0, a1, a2)
cost = collections.defaultdict(list)          # key -> [L_CMP per command]
lane_by_lop = collections.Counter()
lane_cmd_rows = 0
lane_other_rows = collections.Counter()
for line in open(CSV):
    if not line.startswith("R,"):
        continue
    f = [int(x) for x in line.rstrip("\n").split(",")[1:]]
    tok, pc, op, lop, lcmp = f[1], f[2], f[3], f[6], f[9]
    if tok == 0:
        continue
    lane_by_lop[lop] += lcmp
    if op == SF.OP_CMD:
        cost[key_at[pc]].append(lcmp)
        lane_cmd_rows += lcmp
    else:
        lane_other_rows[op] += lcmp
lane_tot = sum(lane_by_lop.values())
print("\n=== A. the .e4 per-command lane cost (tokens 1..6, per token)")
print(f"  lane total {lane_tot / NTOK:.1f} cyc/token = {ms(lane_tot / NTOK):.3f} "
      f"ms; inside CMD rows {lane_cmd_rows / NTOK:.1f}; outside CMD rows "
      f"{sum(lane_other_rows.values()) / NTOK:.1f} "
      f"(by record opcode: {dict(lane_other_rows)})")
print(f"  {'key':40s} {'cmds/tok':>9s} {'min':>6s} {'max':>6s} {'mean':>9s} "
      f"{'cyc/tok':>11s} {'mean-II*n':>9s}")
e_mean = {}
e_cnt = {}
for k in sorted(cost, key=lambda k: -sum(cost[k])):
    v = cost[k]
    e_mean[k] = sum(v) / len(v)
    e_cnt[k] = len(v) / NTOK
    over = ""
    if k[0] in ("ALU", "VN"):
        over = f"{e_mean[k] - II.get(k[1], 1) * k[2]:9.1f}"
    print(f"  {str(k):40s} {len(v) / NTOK:9.1f} {min(v):6d} {max(v):6d} "
          f"{e_mean[k]:9.1f} {sum(v) / NTOK:11.1f} {over}")
e_op = collections.Counter()
for k, v in cost.items():
    e_op[k[0]] += sum(v) / NTOK

# ---------------------------------------------------------------- B
print("\n=== B. accounting identity, per opcode, cyc/token")
print("  (.e4 = this timeline's CMD rows; t14a/s4 = layer census, DRAINING, "
      "holds NOT in LCYC)")
print(f"  {'op':6s} {'.e4':>12s} {'t14a':>12s} {'e4-t14a':>12s} {'s4':>12s} "
      f"{'e4-s4':>12s}")
names = sorted(set(e_op) | set(t14a), key=lambda o: -e_op.get(o, 0))
sd = sd4 = 0.0
for o in names:
    e = e_op.get(o, 0.0)
    a = t14a.get(o, (0, 0))[1] / NTOK
    b = s4.get(o, (0, 0))[1] / NTOK
    sd += e - a
    sd4 += e - b
    print(f"  {o:6s} {e:12.1f} {a:12.1f} {e - a:+12.1f} {b:12.1f} {e - b:+12.1f}")
print(f"  {'TOTAL':6s} {sum(e_op.values()):12.1f} {t14a_total / NTOK:12.1f} "
      f"{sd:+12.1f} {s4_total / NTOK:12.1f} {sd4:+12.1f}")
e_tot = sum(e_op.values())
alu_d = e_op["ALU"] - t14a["ALU"][1] / NTOK
vn_d = e_op["VN"] - t14a["VN"][1] / NTOK
sld = e_op.get("SLD", 0.0)
print(f"  gap vs t14a (holds subtracted) = {e_tot - t14a_total / NTOK:+.1f} cyc "
      f"= {ms(e_tot - t14a_total / NTOK):+.3f} ms")
print(f"    = ALU {alu_d:+.1f} + VN {vn_d:+.1f} + SLD (the .e4's F2 queue-full "
      f"hold, charged in its lane) {sld:+.1f} + rest "
      f"{e_tot - t14a_total / NTOK - alu_d - vn_d - sld:+.1f}")
hold_nd = nd_f2 / NTOK
like = t14a_total / NTOK + hold_nd
print(f"  like-for-like comparand (t14a + the nodrain F2 hold {hold_nd:.1f}) = "
      f"{like:.1f} cyc = {ms(like):.3f} ms")
print(f"    gap = {e_tot - like:+.1f} cyc = {ms(e_tot - like):+.3f} ms;  ALU+VN "
      f"= {alu_d + vn_d:+.1f} = {100 * (alu_d + vn_d) / (e_tot - like):.2f} % "
      f"of it; remainder {e_tot - like - alu_d - vn_d:+.1f} cyc = the hold "
      f"difference {sld - hold_nd:+.1f}")
print(f"  (the census's 112 %: ALU+VN {ms(alu_d + vn_d):+.3f} ms against the "
      f"4.064 ms gap to 45.674 — that comparand has the holds SUBTRACTED while "
      f"the .e4 lane carries SLD {ms(sld):.3f} ms, and is pre-14A)")

# ---------------------------------------------------------------- C, D
txt = collections.Counter()
for (st, ln, op, a0, a1, a2) in C.txt_steps():
    if st == 1:
        txt[C.key_of(op, a0, a1, a2)] += 1
print("\n=== C. the .txt VN list at the .e4's per-key VN costs")
pred_vn = 0.0
for k, n in sorted(txt.items(), key=str):
    if k[0] != "VN":
        continue
    assert k in e_mean, f"{k} has no .e4 cost"
    pred_vn += n * e_mean[k]
    print(f"  {str(k):40s} {n:6d} x {e_mean[k]:8.1f} = {n * e_mean[k]:12.1f}")
meas_vn = t14a["VN"][1] / NTOK
print(f"  predicted .txt VN {pred_vn:.1f}   measured (census_t14a) {meas_vn:.1f}"
      f"   difference {pred_vn - meas_vn:+.1f} cyc/token")
eps = e_mean[("VN", "EPS-NORM", LR.LDV)] * e_cnt[("VN", "EPS-NORM", LR.LDV)]
print(f"  .e4 VN - .txt VN = {e_op['VN'] - meas_vn:+.1f}; the 768 EPS-NORMs "
      f"cost {eps:.1f}")

print("\n=== D. the .txt ALU list: common keys at .e4 costs, .txt-only keys "
      "as the residual")
common = only = 0.0
only_keys = []
for k, n in sorted(txt.items(), key=str):
    if k[0] != "ALU":
        continue
    if k in e_mean:
        common += n * e_mean[k]
    else:
        only_keys.append((k, n))
meas_alu = t14a["ALU"][1] / NTOK
resid = meas_alu - common
n_only = sum(n for _k, n in only_keys)
iin = sum(n * II.get(k[1], 1) * k[2] for k, n in only_keys)
print(f"  measured .txt ALU {meas_alu:.1f}; common keys at .e4 costs {common:.1f}"
      f"; residual for the .txt-only keys {resid:.1f}")
for k, n in only_keys:
    print(f"    .txt-only {str(k):36s} {n:5d} cmds, II*n = "
          f"{II.get(k[1], 1) * k[2]}")
print(f"  .txt-only: {n_only} commands, sum II*n = {iin}; residual - II*n = "
      f"{resid - iin:.1f} -> {(resid - iin) / n_only:.2f} cyc of fixed "
      f"overhead per command")
alu_like = [(k, e_mean[k] - II.get(k[1], 1) * k[2]) for k in e_mean
            if k[0] == "ALU"]
print("  for comparison, the .e4's measured (mean - II*n) per ALU key:")
for k, o in sorted(alu_like, key=lambda x: str(x[0])):
    print(f"    {str(k):40s} {o:8.1f}")
# D2 (fix 1): the per-key fit.  Two of the three .txt-only sub-ops have an
# overhead on record: SHIFT32 from the census's OWN ALU minimum (42 cycles;
# the only ALU with n = 32 in the .txt list is SHIFT32 over in_b/in_a), and
# EMUL32 from the .e4's measured EMUL32 at every size.  Whatever is left is
# what the 192 SHIFT32W must carry.
alu_min = min(int(line.split()[6]) for line in open(T14A)
              if re.match(r"^LAYER_CENSUS\s+11\s+ALU\s", line))
small = sorted({k for k in txt if k[0] == "ALU" and k[2] <= 32})
o1 = alu_min - 32
o8 = {e_mean[k] - 2 * k[2] for k in e_mean if k[:2] == ("ALU", "EMUL32")
      and len(k) == 3}
print(f"  D2. per-key fit: census ALU min = {alu_min} cyc; .txt ALU keys with "
      f"n <= 32: {small} -> SHIFT32 overhead {o1}")
print(f"      .e4 EMUL32 (non-probe) overheads measured: {sorted(o8)}")
assert len(o8) == 1
o8 = o8.pop()
n1 = sum(n for k, n in only_keys if k[1] == "SHIFT32")
n9 = sum(n for k, n in only_keys if k[1] == "SHIFT32W")
n8 = sum(n for k, n in only_keys if k[1] == "EMUL32")
left = (resid - iin) - n1 * o1 - n8 * o8
print(f"      residual overhead {resid - iin:.1f} - {n1} SHIFT32 x {o1} - {n8} "
      f"EMUL32 x {o8:.0f} = {left:.1f} for {n9} SHIFT32W -> {left / n9:.3f} "
      f"cyc each")
fit = common + iin + n1 * o1 + n8 * o8 + n9 * round(left / n9)
print(f"      with SHIFT32 = n+{o1}, EMUL32 = 2n+{o8:.0f}, SHIFT32W = "
      f"2n+{round(left / n9)}: predicted .txt ALU {fit:.1f} vs measured "
      f"{meas_alu:.1f} -> {'EXACT' if fit == meas_alu else 'OFF by %+.1f' % (fit - meas_alu)}")

# ---------------------------------------------------------------- E
print("\n=== E. per-substitution sizing, cyc/token (+ = the .e4 costs more)")
LDV, NQ, HD = LR.LDV, LR.NQ, LR.HD
OVK = {"SHIFT32": o1, "EMUL32": o8, "SHIFT32W": round(left / n9)}
for label, ovf in (("uniform overhead %.2f" % ((resid - iin) / n_only),
                    lambda k: (resid - iin) / n_only),
                   ("D2 per-key fit %s" % OVK, lambda k: OVK[k[1]])):
    def txt_only_cost(k, n):
        return n * (II.get(k[1], 1) * k[2] + ovf(k))
    print(f"  -- .txt-only costs at the {label}")
    fused = [(k, n) for k, n in only_keys
             if k[1] in ("SHIFT32", "SHIFT32W") and k[2] != LDV]
    a = -sum(txt_only_cost(k, n) for k, n in fused)
    bk = [k for k in e_mean if k[:2] == ("ALU", "SILU32")]
    b = (sum(e_cnt[k] * e_mean[k] for k in bk)
         - sum(n * e_mean[k] for k, n in txt.items()
               if k[:2] == ("ALU", "SILU32")))
    c_e4 = (e_cnt[("ALU", "DYNQ16", LDV)] * e_mean[("ALU", "DYNQ16", LDV)]
            + eps)
    c_txt = (txt_only_cost(("ALU", "SHIFT32", LDV),
                           txt[("ALU", "SHIFT32", LDV)])
             + (txt[("ALU", "SCALE", LDV)] - e_cnt[("ALU", "SCALE", LDV)])
             * e_mean[("ALU", "SCALE", LDV)])
    c = c_e4 - c_txt
    d_e4 = sum(e_cnt[k] * e_mean[k] for k in e_mean
               if k[:2] == ("ALU", "EMUL32") and k[2] == NQ * HD)
    d_txt = txt_only_cost(("ALU", "EMUL32", HD), txt[("ALU", "EMUL32", HD)])
    d = d_e4 - d_txt
    print(f"  (a) 560 fused dequants removed (MOVY does the shift)   "
          f"{a:+12.1f} = {ms(a):+.3f} ms")
    print(f"  (b) SILU32 re-chunked 192 -> 256 commands              "
          f"{b:+12.1f} = {ms(b):+.3f} ms")
    print(f"  (c) DN block-float: .e4 DYNQ16+EPS-NORM {c_e4:.1f} vs .txt "
          f"SHIFT32+SCALE {c_txt:.1f}  {c:+12.1f} = {ms(c):+.3f} ms")
    print(f"  (d) attention EMUL32: .e4 probe+real {d_e4:.1f} vs .txt 16x256 "
          f"{d_txt:.1f}  {d:+12.1f} = {ms(d):+.3f} ms")
    tot = a + b + c + d
    print(f"  SUM {tot:+.1f} cyc/token = {ms(tot):+.3f} ms   against ALU+VN "
          f"{alu_d + vn_d:+.1f}")
print(f"  census comparand of the 76 % estimate: -1376 x 910 + 768 x 620 = "
      f"{-1376 * 910 + 768 * 620} cyc — at MEAN costs, which the removed "
      f"commands are not")
print("\nSD1_SIZE: DONE")
