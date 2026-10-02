#!/usr/bin/env python3
"""G4b Step 2 (EXTENDED) — the gate-port clamp DECISION PACKAGE, part (b).

Joins the two INDEPENDENT committed measurements of the same 61 (layer,
head) pairs and prints one table with the excess over each port and which
parameter carries it:

  * `evidence/qwen9b/g1/11_gate_port_probe_9b.log` — G1(d) axis 2, Track Q's
    committed `gate_port_probe.py` run at 9B.  WEIGHTS ONLY: it reads
    `dt_bias` and `A_log` off the checkpoint and applies
    `ref/layer_fixed.py:805-806`'s two clamps.  Its own cross-check compares
    the expressions with the PRODUCTION `quant_deltanet`'s `qd["gate_sat"]`
    on DN layer 0 and reports IDENTICAL.
  * `evidence/qwen9b/g4/003_emit_9b_s1.log` — G4a's runtime range audit,
    inside the emitter, at the RUNTIME `a` values of this prompt.

The two sets are checked to be identical here; if they are not, that is the
finding and this script says so rather than joining silently.

This file MEASURES NOTHING NEW.  It reads two committed logs and tabulates
them, so the decision package is a document a reader can re-derive.

Usage:  python3 evidence/qwen9b/g4/g4b_gate_clamp_package.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
G1LOG = os.path.join(ROOT, "evidence/qwen9b/g1/11_gate_port_probe_9b.log")
G4LOG = os.path.join(ROOT, "evidence/qwen9b/g4/003_emit_9b_s1.log")

# rtl/gate_unit.sv:49-52 — the ports as BUILT
DT_MIN, DT_MAX = -32768, 32767          # dtv[15:0] signed,   Q3.12
A_MAX = (1 << 18) - 1                   # Av[17:0]  unsigned, Q3.15

G1_RE = re.compile(
    r"^\s*L(\d+)\s+h(\d+)\s*\|\s*([-\d.]+)\s+(-?\d+)\s*\|"
    r"\s*([-\d.]+)\s+(-?\d+)\s*\|\s*(\d+)\s*->\s*(\d+)\s*\|\s*(\d+)")
G4_RE = re.compile(
    r"^\s*L(\d+)h(\d+):\s*worst \|decay_clamp - decay_spec\| = (\d+)\s*/32768"
    r"\s*\(([\d.]+)% FS\) at a=([-+]?[\d.]+)\s*\(spec (\d+) -> clamped (\d+)\);"
    r"\s*(\d+) evaluations")


def main():
    g1 = {}
    for line in open(G1LOG):
        m = G1_RE.match(line)
        if m:
            L, h = int(m.group(1)), int(m.group(2))
            g1[(L, h)] = dict(A=float(m.group(3)), A_q15=int(m.group(4)),
                              dt=float(m.group(5)), dt_q12=int(m.group(6)),
                              decay_spec=int(m.group(7)),
                              decay_prod=int(m.group(8)),
                              decay_wrap=int(m.group(9)))
    g4 = {}
    for line in open(G4LOG):
        m = G4_RE.match(line)
        if m:
            L, h = int(m.group(1)), int(m.group(2))
            g4[(L, h)] = dict(err=int(m.group(3)), fs=float(m.group(4)),
                              a=float(m.group(5)), spec=int(m.group(6)),
                              clamped=int(m.group(7)), nev=int(m.group(8)))

    print(f"GATECLAMP g1 pairs (weights-only, G1 log 11) : {len(g1)}")
    print(f"GATECLAMP g4 pairs (runtime, G4a log 003)    : {len(g4)}")
    only1 = sorted(set(g1) - set(g4))
    only4 = sorted(set(g4) - set(g1))
    if only1 or only4:
        print(f"GATECLAMP SETS DIFFER: only in G1 {only1}; only in G4a {only4}")
    else:
        print("GATECLAMP SETS IDENTICAL — the same (layer, head) pairs from "
              "two independent measurements")

    rows = []
    for k in sorted(set(g1) & set(g4)):
        a, b = g1[k], g4[k]
        # which port is over, and by how much (ratio of the SPEC value to the
        # port ceiling; 1.0 = exactly at the rail)
        a_over = a["A_q15"] > A_MAX
        dt_over = not (DT_MIN <= a["dt_q12"] <= DT_MAX)
        who = ("A+dt" if (a_over and dt_over)
               else "A" if a_over else "dt" if dt_over else "-")
        a_x = a["A_q15"] / A_MAX
        dt_x = abs(a["dt_q12"]) / (DT_MAX if a["dt_q12"] >= 0 else -DT_MIN)
        rows.append((k, who, a, b, a_x, dt_x))

    print()
    print("GATECLAMP the 61 pairs — port excess and the runtime decay cost")
    print("GATECLAMP  L   h  port  A(spec)   A_q15(spec)  xA    dt(spec)  "
          "dt_q12(spec)  xdt   runtime |dLdecay|  %FS   a")
    for (L, h), who, a, b, a_x, dt_x in rows:
        print(f"GATECLAMP {L:3d} {h:3d}  {who:4s} {a['A']:9.4f} "
              f"{a['A_q15']:12d} {a_x:5.2f} {a['dt']:9.3f} "
              f"{a['dt_q12']:12d} {dt_x:5.2f} {b['err']:14d} "
              f"{b['fs']:6.2f} {b['a']:8.3f}")

    n_a = sum(1 for r in rows if r[1] == "A")
    n_dt = sum(1 for r in rows if r[1] == "dt")
    n_both = sum(1 for r in rows if r[1] == "A+dt")
    worst = max(rows, key=lambda r: r[3]["fs"])
    max_ax = max(rows, key=lambda r: r[4])
    max_dtx = max(rows, key=lambda r: r[5])
    print()
    print(f"GATECLAMP carried by A only : {n_a}")
    print(f"GATECLAMP carried by dt only: {n_dt}")
    print(f"GATECLAMP carried by both   : {n_both}")
    print(f"GATECLAMP total             : {len(rows)}")
    print(f"GATECLAMP worst runtime cost: L{worst[0][0]}h{worst[0][1]} "
          f"{worst[3]['err']}/32768 = {worst[3]['fs']:.2f}% FS "
          f"(spec {worst[3]['spec']} -> clamped {worst[3]['clamped']}), "
          f"carried by {worst[1]}")
    print(f"GATECLAMP largest A excess  : L{max_ax[0][0]}h{max_ax[0][1]} "
          f"A_q15 {max_ax[2]['A_q15']} vs the 18-bit ceiling {A_MAX} "
          f"= {max_ax[4]:.2f}x  (A = {max_ax[2]['A']:.4f} vs the port's 8.0)")
    print(f"GATECLAMP largest dt excess : L{max_dtx[0][0]}h{max_dtx[0][1]} "
          f"dt_q12 {max_dtx[2]['dt_q12']} vs the int16 rail "
          f"[{DT_MIN},{DT_MAX}] = {max_dtx[5]:.2f}x  "
          f"(dt = {max_dtx[2]['dt']:.3f} vs the port's +/-8.0)")
    # what the WRAP the ports as built would do costs, for contrast
    wmax = max(rows, key=lambda r: abs(r[2]["decay_wrap"] - r[2]["decay_spec"]))
    print(f"GATECLAMP wrap (no clamp)   : worst |decay_wrap - decay_spec| = "
          f"{abs(wmax[2]['decay_wrap'] - wmax[2]['decay_spec'])}/32768 at "
          f"L{wmax[0][0]}h{wmax[0][1]} — what SATURATION buys")
    return 0 if not (only1 or only4) else 1


if __name__ == "__main__":
    sys.exit(main())
