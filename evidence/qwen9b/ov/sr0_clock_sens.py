#!/usr/bin/env python3
"""sr0_clock_sens.py — Task SR0: the "small clock hit" quantified, on OV1's
own model.

    FABLE5_MODEL=9b evidence/qwen9b/ov/ov_run.sh <log> \
        /home/cah/.venv/bin/python evidence/qwen9b/ov/sr0_clock_sens.py

WHAT IT DOES.  It imports evidence/qwen9b/ov/ov_census.py UNCHANGED (the
read/write sets, the edges, the list scheduler, the post-check and the
shipped-order replay are OV1's own functions, exactly as
ref/scripts/reorder_e4.py imports them) and re-runs OV1's schedule
variants — shipped order, S1, R1, R1+R2 and R1+R2+R3 — with the per-record
windows SCALED to model a slower clock.  Nothing under rtl/ ref/ tb/ is
read for writing; stdout only.

WHICH WINDOW IS IN WHICH CLOCK (the whole point of the exercise):
  * every LANE window — the layer CMD (busy_cmp on aclk, rtl/layer_chan.sv),
    MOVX / MOVY (seq_movers' burst master and the matvec_chan burst shim,
    aclk), the MVGO issue window (AXI-Lite config writes + doorbell, aclk),
    CSRWR / XOP / AMAXL / JMP (seq_unit, aclk), LDC / EMB (seq_unit bulk
    path, aclk side of the central SmartConnect) — and the FENCE poll tail
    tau (AXI-Lite STATUS polls, aclk) are counted in cycles of the 250 MHz
    xdma_0/axi_aclk.  They scale as 1/(1-r) when THAT clock is cut by r.
    (LDC / EMB and the CMD windows' DMA holds also contain DDR latency on
    the MIG side; scaling them with aclk OVERSTATES the hit — conservative.)
  * every STREAM S — the engine-busy cycles of a matvec_chan (the
    streamer + engine, rtl/matvec_chan.sv ui_clk domain, fed by DDR4 at
    the MIG UI clock) — does NOT scale with aclk.  It scales as 1/(1-r)
    only when the MIG UI clock is cut, which on this design is the DDR4
    data rate itself (synth/scripts/create_project.tcl, DDR4_TimePeriod).

TWO SCENARIOS:
  K  aclk cut by r: lane and tau x 1/(1-r), streams unchanged.
  U  MIG UI clock (= DDR4 rate) cut by r: streams x 1/(1-r), lane unchanged.

TWO BOARD CONVENTIONS:
  uni    OV1's: board ms = TB ms x 137.121/131.138 (a uniform-scaling
         ASSUMPTION; OV1_DEPENDENCY_CENSUS.md §0).
  split  BM1-calibrated: each window class x its measured board/TB ratio
         (evidence/qwen9b/bm/n84_T4fix1_board_table.log:14): streams x
         mvany 1.0622, CMD x l_lcyc 0.9995, MOVX x 1.0072, MOVY x 1.0171,
         everything else x 1.0.  Checked against the board's own step times
         (n72 shipped 137.1195, n73 S1 form A 123.5655 ms/token,
         evidence/qwen9b/bm/n84_T4fix1_board_table.log:10-12) before use.

BREAK-EVEN: for each RTL option, the cut r* at which its tok/s equals S1's
at r = 0 (same form, same scenario, same convention), by bisection.

R3 is carried twice: 'R3' is OV1's (the three sibling MOVXs of a matvec cost
0, OV1 §9 item 6: optimistic), 'R3buf' prices a staging-buffer broadcast in
which each sibling still pays its XWIN write side — a quarter of its window,
because MOVX reads one int8 per scratch beat and writes one packed word per
four (rtl/seq_movers.sv:547, X_RUN).  That quarter is an APPROXIMATION.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ov_census as OC            # noqa: E402  (OV1's model, unchanged)

SF = OC.SF
TBF = OC.BOARD_MS / OC.TB_MS       # 137.121 / 131.138 (OV1's convention)
# BM1 board/TB per counter (evidence/qwen9b/bm/n84_T4fix1_board_table.log:14)
SPLIT = {"stream": 1.0622, "chain": 0.9995, "movx": 1.0072, "movy": 1.0171}
BOARD_N72 = 137.1195               # n84:11 (shipped order, board)
BOARD_N73 = 123.5655               # n84:12 (S1 form A, board)
ALU_PER_TOKEN = 4843               # .e4 ALU commands/token (BN_CENSUS §13)
RS = (0.0, 0.05, 0.10, 0.15, 0.20)
DDR4_GRADES = ((2400, 833), (2133, 938), (1866, 1071))   # MT/s, tCK ps


def ms(c):
    return c / OC.ACLK_HZ * 1e3


class Model:
    def __init__(self):
        recs, _man = OC.load_stream()
        lo, hi = OC.body_range(recs)
        rows = OC.load_csv()
        r4 = rows[4]
        self.nodes = OC.build_nodes(recs, lo, hi, r4)
        self.groups, _leak = OC.stream_durations(self.nodes, r4)
        self.mvs, _lt = OC.segment_matvecs(self.nodes, self.groups)
        self.body = sum(n.dur for n in self.nodes)
        self.dur0 = [n.dur for n in self.nodes]
        self.S0 = [n.S for n in self.nodes]
        self.tau0 = [g["tau"] for g in self.groups]
        print(f"=== body window sum (token 4): {self.body} cyc = "
              f"{ms(self.body):.3f} ms  (OV1 n15: 131.147 ms)")

    def apply(self, lane=1.0, stream=1.0, tau=1.0, split=False):
        for i, n in enumerate(self.nodes):
            f = lane
            if split:
                f *= SPLIT.get(n.kind, 1.0)
            n.dur = int(round(self.dur0[i] * f))
            s = stream * (SPLIT["stream"] if split else 1.0)
            n.S = int(round(self.S0[i] * s))
        for g, t0 in zip(self.groups, self.tau0):
            g["tau"] = int(round(t0 * tau))

    def restore(self):
        self.apply()

    def today(self):
        return OC.today_replay(self.nodes, self.groups, "measured")[0]

    def variant(self, tag, form):
        chain = "order" if form == "A" else "free"
        if tag == "S1":
            OC.build_edges(self.nodes, True, 1, 1, chain)
            return OC.best_schedule(self.nodes, self.groups, 1, "global", True)
        xd = 2 if tag in ("R2", "R3", "R3buf") else 1
        OC.build_edges(self.nodes, True, xd, xd, chain)
        saved = None
        if tag in ("R3", "R3buf"):
            saved = [n.dur for n in self.nodes]
            for i, n in enumerate(self.nodes):
                if n.kind == "movx" and not n.redundant:
                    live = [x for x in self.mvs[n.mv]["movx"]
                            if not self.nodes[x].redundant]
                    if live and i != live[0]:
                        n.dur = 0 if tag == "R3" else int(round(n.dur / 4))
        mk = OC.best_schedule(self.nodes, self.groups, 1, "perchan", True)
        if saved is not None:
            for n, d in zip(self.nodes, saved):
                n.dur = d
        return mk

    def run(self, scen, r, tag, form, split):
        k = 1.0 / (1.0 - r)
        if scen == "K":
            self.apply(lane=k, stream=1.0, tau=k, split=split)
        else:
            self.apply(lane=1.0, stream=k, tau=1.0, split=split)
        mk = self.today() if tag == "shipped" else self.variant(tag, form)
        self.restore()
        return mk


def board_ms(mk, split):
    return ms(mk) if split else ms(mk) * TBF


def main():
    M = Model()
    tags = ("shipped", "S1", "R1", "R2", "R3", "R3buf")
    names = {"shipped": "shipped", "S1": "S1", "R1": "R1", "R2": "R1+R2",
             "R3": "R1+R2+R3", "R3buf": "R1+R2+R3(buf)"}

    # ---- the r = 0 reproduction of OV1 (n15) and the split calibration ----
    print("\n=== r = 0: reproduce OV1 (TB cyc, both forms)")
    for form in ("B", "A"):
        for t in tags:
            mk = M.run("K", 0.0, t, form, False)
            print(f"  REPRO {form}:{names[t]:14s} {mk:9d} cyc = "
                  f"{ms(mk):8.3f} ms TB")
    print("\n=== split convention calibration against the board (n84)")
    t0 = M.run("K", 0.0, "shipped", "A", True)
    s1a = M.run("K", 0.0, "S1", "A", True)
    print(f"  CALIB shipped split {ms(t0):.4f} ms vs board n72 {BOARD_N72} "
          f"({100.0 * (ms(t0) / BOARD_N72 - 1):+.3f} %); uniform "
          f"{ms(M.run('K', 0.0, 'shipped', 'A', False)) * TBF:.4f}")
    print(f"  CALIB S1-A    split {ms(s1a):.4f} ms vs board n73 {BOARD_N73} "
          f"({100.0 * (ms(s1a) / BOARD_N73 - 1):+.3f} %); uniform "
          f"{ms(M.run('K', 0.0, 'S1', 'A', False)) * TBF:.4f}")

    # ---- the grid ----
    res = {}
    for scen in ("K", "U"):
        for split in (False, True):
            conv = "split" if split else "uni"
            for form in ("B", "A"):
                print(f"\n=== GRID scenario {scen} "
                      f"({'aclk' if scen == 'K' else 'MIG UI / DDR4'} cut), "
                      f"board convention {conv}, form {form}: board tok/s")
                print("  option          " + "".join(
                    f"  r={int(r * 100):2d}%  " for r in RS))
                for t in tags:
                    row = []
                    for r in RS:
                        mk = M.run(scen, r, t, form, split)
                        v = 1000.0 / board_ms(mk, split)
                        res[(scen, conv, form, t, r)] = v
                        row.append(v)
                    print(f"  GRID {scen} {conv:5s} {form} {names[t]:14s}"
                          + "".join(f" {v:8.3f}" for v in row))

    # ---- break-even: option(r*) == S1(0) ----
    print("\n=== BREAK-EVEN r* (option at r* == S1 at r = 0; same scenario, "
          "convention, form), bisection to 1e-4")
    for scen in ("K", "U"):
        for split in (False, True):
            conv = "split" if split else "uni"
            for form in ("B", "A"):
                target = res[(scen, conv, form, "S1", 0.0)]
                for t in ("R1", "R2", "R3", "R3buf"):
                    lo, hi = 0.0, 0.6
                    f_hi = 1000.0 / board_ms(M.run(scen, hi, t, form, split),
                                             split)
                    if f_hi > target:
                        print(f"  BREAKEVEN {scen} {conv:5s} {form} "
                              f"{names[t]:14s} > {hi:.2f}")
                        continue
                    for _ in range(14):
                        mid = 0.5 * (lo + hi)
                        f = 1000.0 / board_ms(M.run(scen, mid, t, form,
                                                    split), split)
                        if f >= target:
                            lo = mid
                        else:
                            hi = mid
                    rstar = 0.5 * (lo + hi)
                    print(f"  BREAKEVEN {scen} {conv:5s} {form} "
                          f"{names[t]:14s} r* = {100.0 * rstar:6.2f} %  "
                          f"(clock {250.0 * (1 - rstar) if scen == 'K' else 300.0 * (1 - rstar):7.2f} MHz; "
                          f"S1@0 = {target:.3f} tok/s)")

    # ---- the discrete DDR4 grades (scenario U at the MIG's own steps) ----
    print("\n=== scenario U at the DDR4 speed grades (UI clock = data rate/8)")
    for mts, tck in DDR4_GRADES:
        r = 1.0 - mts / 2400.0
        cells = []
        for t in ("S1", "R1", "R2", "R3"):
            mk = M.run("U", r, t, "B", False)
            cells.append(f"{names[t]} {1000.0 / board_ms(mk, False):.3f}")
        print(f"  DDR4-{mts} tCK {tck} ps UI {mts / 8.0:.2f} MHz r={100 * r:.2f} %"
              f" (form B, uni): " + ", ".join(cells))

    # ---- the clock each measured WNS would need (period + |WNS|) ----
    print("\n=== the clock a roll's WNS would need: f = 1/(T + |WNS|)")
    for clk, T, wns, src in (
            ("aclk", 4.000, -0.124, "BM1 best roll, u_attn gather"),
            ("aclk", 4.000, -0.384, "BM1 END_high aclk worst, u_alu"),
            ("aclk", 4.000, -0.370, "BM1 ASL_low aclk worst, u_alu"),
            ("aclk", 4.000, -0.507, "BM1 EBP, u_dn lane DSP"),
            ("ui", 3.332, -0.010, "BM1 best roll, mvchan_0 streamer"),
            ("ui", 3.332, -0.408, "BM1 ASL_low, mvchan_3 scales_q CE"),
            ("ui", 3.332, -0.554, "BM1 END_high, mvchan_3 xline_q0")):
        f = 1000.0 / (T - wns)
        r = 1.0 - T / (T - wns)
        print(f"  NEED {clk:4s} T={T:.3f} WNS={wns:+.3f} -> {f:7.2f} MHz "
              f"(cut {100 * r:5.2f} %)  [{src}]")

    # ---- the ALU op-stage pipeline's throughput cost ----
    print(f"\n=== ALU op-stage: +1 aclk cycle per ALU command x "
          f"{ALU_PER_TOKEN}/token = {ALU_PER_TOKEN} cyc = "
          f"{ms(ALU_PER_TOKEN):.4f} ms/token = "
          f"{100.0 * ALU_PER_TOKEN / M.body:.4f} % of the shipped token")
    print("SR0_CLOCK_SENS: DONE")


if __name__ == "__main__":
    main()
