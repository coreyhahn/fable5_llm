#!/usr/bin/env python3
"""sr16_decision_table.py — Task SR16: every derived number of
SR16_R3_DECISION.md, from committed JSONs and transcribed constants only
(no device, no model run).  Run ON SNOKE via sr_run.sh.

MEASURED inputs (read from the committed JSONs): the stream censuses n72
(build_042_bm1, shipped order), n1511 / n1510 / n1509 (R2 bitstream r0-B / r1
/ r2) and SR8's n809 / n808; the chat511 sessions n68, n1506, n1507, n1508.
TRANSCRIBED constants, each with its source line:
  TB whole runs (6 tokens, s1): shipped 196,706,821 (n1310_sr13a_chip_s1_shipped.log:32),
    S1-B 171,731,320 (n570_sr5_derive.log:12), R1 162,967,117 (n570_sr5_derive.log:21),
    R2 157,010,908 (n1349g_sr13a_derive.log:24).
  Chat full-image TB/static savings: R1 5.784 ms (n815_sr8_predictions.log:13),
    R2 4.0173 ms (n1515_sr15_predictions.log:10).
  Model rows (board-scaled, uniform, form B): n120_sr0_clock_sens.log:34-39.
  R3 model (n1600_sr16_r3_census.log): TB live MOVX 3,237,088; siblings
    2,427,816; R2 lane idle on stream 8,982,101; R3 / R3buf lane work removed
    2,427,816 / 1,820,814, lane idle rise 383,656 / 254,014; R2 / R3 / R3buf
    makespans 26,146,927 / 24,102,767 / 24,580,127.
  Floors: dependency critical path 21,683,350 cyc (n06_all_final.log:832).
"""
import json
import os
import statistics as st

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SR = "evidence/qwen9b/sr/"
F = 250e6
TBF = 137.121 / 131.138                  # OV1's uniform board factor (spec §0)
TB_RUN = {"shipped": 196706821, "S1-B": 171731320, "R1": 162967117,
          "R2": 157010908}
# ms per full launch.  STALE (SR16 fix round 1): R2's 4.0173 is n1351's
# UNCORRECTED static saving; SR13b's corrected one is 3.8692 ms (n901_sr9_derive.log:12),
# retention 1.0069 (n1650).  It feeds only the printed chat retention, never a band.
CHAT_TB_SAVE = {"R1": 5.784, "R2": 4.0173}
MODEL = {"shipped": 7.292, "S1-B": 8.356, "R1": 8.811, "R2": 9.144,
         "R3(a)": 9.920, "R3(b)": 9.727}
MK = {"R2": 26146927, "R3(a)": 24102767, "R3(b)": 24580127}
LIVE_MOVX_TB = 3237088
SIB_TB = 2427816
IDLE_R2_TB = 8982101
LANE_RM = {"R3(a)": 2427816, "R3(b)": 1820814}
IDLE_UP = {"R3(a)": 383656, "R3(b)": 254014}
CRIT_TB = 21683350


def J(p):
    return json.load(open(os.path.join(ROOT, p)))


def msc(c):
    return c / F * 1e3


def stream(p):
    j = J(p)
    d = {"cyc": j["perf"]["cyc"] / j["ntok"], "l_lcyc": j["l_lcyc"] / j["ntok"],
         "l_sdma": j["l_sdma_cyc"] / j["ntok"], "ok": j["tokens"] == j["want"]
         and not j["err_code"]}
    for k, v in (j["perf"].get("bm") or {}).items():
        d[k] = v / j["ntok"]
    return d


def chat(p, kind="full"):
    j = J(p)
    K = [r for r in j["launches"] if r["image"] == kind]
    d = {"cyc": st.mean(r["perf"]["cyc"] for r in K),
         "l_lcyc": st.mean(r["l_lcyc"] for r in K),
         "l_sdma": st.mean(r["l_sdma_cyc"] for r in K), "n": len(K)}
    if all("bm" in r["perf"] for r in K):
        for k in K[0]["perf"]["bm"]:
            d[k] = st.mean(r["perf"]["bm"][k] for r in K)
    return d


S = {"shipped": stream("evidence/qwen9b/bm/n72_T4_bm1_stream_model_9b_s1.json"),
     "S1-B": stream(SR + "n1511_sr15_census_r0B.json"),
     "R1": stream(SR + "n1510_sr15_census_r1.json"),
     "R2": stream(SR + "n1509_sr15_census_r2.json"),
     "S1-B (n809)": stream(SR + "n809_sr8_census_r0B.json"),
     "R1 (n808)": stream(SR + "n808_sr8_census_r1.json")}
C = {"shipped": chat("evidence/qwen9b/bm/n68_T4_control_041_chat511.json"),
     "S1-B": chat(SR + "n1506_sr15_r2bit_r0B_chat511.json"),
     "R1": chat(SR + "n1507_sr15_r2bit_r1_chat511.json"),
     "R2": chat(SR + "n1508_sr15_r2_chat511.json")}
CL = {k: chat(p, "lite") for k, p in (
      ("S1-B", SR + "n1506_sr15_r2bit_r0B_chat511.json"),
      ("R1", SR + "n1507_sr15_r2bit_r1_chat511.json"),
      ("R2", SR + "n1508_sr15_r2_chat511.json"))}
RUNGS = ("shipped", "S1-B", "R1", "R2")
assert all(S[k]["ok"] for k in S), "stream tokens"

print("== A. the ladder, MEASURED (tok/s) beside the MODEL (spec §3.1, form B)")
print("| rung | chat511 full ms | chat full tok/s | stream ms/token | stream tok/s | MODEL tok/s | stream / MODEL |")
print("|---|---|---|---|---|---|---|")
for k in RUNGS:
    cm, sm = msc(C[k]["cyc"]), msc(S[k]["cyc"])
    print(f"| {k} | {cm:.4f} | {1e3 / cm:.3f} | {sm:.4f} | {1e3 / sm:.3f} | {MODEL[k]:.3f} | {1e3 / sm / MODEL[k]:.4f} |")
for a, b in (("shipped", "S1-B"), ("S1-B", "R1"), ("R1", "R2")):
    print(f"  step {a} -> {b}: chat full x{C[a]['cyc'] / C[b]['cyc']:.4f}, stream x{S[a]['cyc'] / S[b]['cyc']:.4f}, "
          f"MODEL x{MODEL[b] / MODEL[a]:.4f}")

print("\n== B. where the step goes, per token (stream census) and per full chat launch; % of PERF_CYC (ms)")
KEYS = (("MVANY (C0, weight path busy)", lambda d: d["mvany"]),
        ("weight path idle (PERF - C0)", lambda d: d["cyc"] - d["mvany"]),
        ("FENCE wait (C5)", lambda d: d["fence"]),
        ("mover work (C6)", lambda d: d["mvwork"]),
        ("  MOVX (C6 split)", lambda d: d["movx"]),
        ("  MOVY (C6 split)", lambda d: d["movy"]),
        ("  MVGO issue (C6 - MOVX - MOVY)", lambda d: d["mvwork"] - d["movx"] - d["movy"]),
        ("mover work, no engine busy (C6 - C7)", lambda d: d["mvwork"] - d["mvwork_any"]),
        ("mover busy (C5 + C6)", lambda d: d["fence"] + d["mvwork"]),
        ("issue FSM in I_MOVER (C8)", lambda d: d["imover"]),
        ("layer lane L_LCYC", lambda d: d["l_lcyc"]),
        ("state DMA L_SDMA", lambda d: d["l_sdma"]))
for tag, D in (("stream", S), ("chat full", C)):
    ks = [k for k in RUNGS if "fence" in D[k]]
    print(f"-- {tag}")
    print("| counter | " + " | ".join(ks) + " |")
    print("|---|" + "---|" * len(ks))
    print("| step ms | " + " | ".join(f"{msc(D[k]['cyc']):.3f}" for k in ks) + " |")
    for name, fn in KEYS:
        print(f"| {name} | " + " | ".join(
            f"{100 * fn(D[k]) / D[k]['cyc']:.2f} % ({msc(fn(D[k])):.3f})" for k in ks) + " |")
for k in ("R1", "S1-B"):
    a, b = S[k], S[f"{k} (n{'808' if k == 'R1' else '809'})"]
    print(f"  control {k}: n15xx vs SR8 FENCE {100 * a['fence'] / a['cyc']:.2f} % vs {100 * b['fence'] / b['cyc']:.2f} %, "
          f"MOVX {100 * a['movx'] / a['cyc']:.2f} % vs {100 * b['movx'] / b['cyc']:.2f} %")
print("  per-rung change, stream, ms/token (FENCE, MOVX, MOVY, MVGO issue, L_LCYC, step):")
for a, b in (("shipped", "S1-B"), ("S1-B", "R1"), ("R1", "R2")):
    x, y = S[a], S[b]
    print(f"    {a} -> {b}: FENCE {msc(y['fence'] - x['fence']):+.3f}, MOVX {msc(y['movx'] - x['movx']):+.3f}, "
          f"MOVY {msc(y['movy'] - x['movy']):+.3f}, MVGO {msc((y['mvwork'] - y['movx'] - y['movy']) - (x['mvwork'] - x['movx'] - x['movy'])):+.3f}, "
          f"L_LCYC {msc(y['l_lcyc'] - x['l_lcyc']):+.3f}, step {msc(y['cyc'] - x['cyc']):+.3f}")

print("\n== C. each rung's saving, board vs chip TB (per token, whole 6-token run / 6)")
ret = {}
gret = {}
for a, b in (("shipped", "S1-B"), ("S1-B", "R1"), ("R1", "R2")):
    bs = S[a]["cyc"] - S[b]["cyc"]
    ts = (TB_RUN[a] - TB_RUN[b]) / 6
    ret[("stream", b)] = bs / ts
    gret[b] = (S[a]["cyc"] / S[b]["cyc"] - 1) / (TB_RUN[a] / TB_RUN[b] - 1)
    print(f"  {a} -> {b}: board {bs:,.0f} cyc = {msc(bs):.4f} ms; TB {ts:,.0f} cyc = {msc(ts):.4f} ms; "
          f"board/TB {bs / ts:.4f}; board ratio x{S[a]['cyc'] / S[b]['cyc']:.4f} vs TB x{TB_RUN[a] / TB_RUN[b]:.4f}")
for k in ("S1-B", "R1", "R2"):
    print(f"  board step / TB step at {k}: {S[k]['cyc'] / (TB_RUN[k] / 6):.4f} "
          f"(board - TB = {msc(S[k]['cyc'] - TB_RUN[k] / 6):.3f} ms/token)")
for k, a in (("R1", "S1-B"), ("R2", "R1")):
    bs = msc(C[a]["cyc"] - C[k]["cyc"])
    ret[("chat", k)] = bs / CHAT_TB_SAVE[k]
    print(f"  chat full {a} -> {k}: board {bs:.4f} ms vs TB/static {CHAT_TB_SAVE[k]:.4f} ms: board/TB {bs / CHAT_TB_SAVE[k]:.4f}")
lo_ret = min(ret.values())
print(f"  lowest absolute retention on any rung, either workload: {lo_ret:.4f}")

print("\n== D. R3 expected, three ways (MODEL-derived; base = the MEASURED R2 row)")
movx_r = S["R2"]["movx"] / LIVE_MOVX_TB
fen_r = S["R2"]["fence"] / IDLE_R2_TB
print(f"  board/TB: MOVX {S['R2']['movx']:,.0f} / {LIVE_MOVX_TB:,} = {movx_r:.4f}; "
      f"FENCE {S['R2']['fence']:,.0f} / model lane idle on stream {IDLE_R2_TB:,} = {fen_r:.4f}")
print(f"  board sibling MOVX (3/4 of MOVX; every live matvec has 4, n1600) = {0.75 * S['R2']['movx']:,.0f} cyc = "
      f"{msc(0.75 * S['R2']['movx']):.3f} ms/token (the hard ceiling on R3's saving)")
bases = (("stream", msc(S["R2"]["cyc"])), ("chat full", msc(C["R2"]["cyc"])),
         ("chat lite", msc(CL["R2"]["cyc"])))
BAND = {}
for form in ("R3(a)", "R3(b)"):
    save_tb = msc(MK["R2"] - MK[form])
    rat = MK["R2"] / MK[form]
    comp = msc(LANE_RM[form] * movx_r - IDLE_UP[form] * fen_r)
    print(f"-- {form}: MODEL saving {save_tb:.4f} ms TB/token, MODEL ratio x{rat:.4f} "
          f"(board-scaled MODEL {MODEL['R2']:.3f} -> {MODEL[form]:.3f})")
    print(f"   component-scaled saving (lane removed x MOVX board/TB - idle rise x FENCE board/TB) = {comp:.4f} ms")
    for name, base in bases:
        movx_scale = (C["R2"]["movx"] if name == "chat full" else
                      CL["R2"]["movx"] if name == "chat lite" else S["R2"]["movx"]) / S["R2"]["movx"]
        i_rat = 1e3 / (base / rat)
        i_ret = 1e3 / (base / (1 + (rat - 1) * gret["R2"]))
        ii = 1e3 / (base - save_tb * movx_scale)
        ii_lo = 1e3 / (base - save_tb * movx_scale * lo_ret)
        iii = 1e3 / (base - comp * movx_scale)
        print(f"   {name:9s} base {base:.4f} ms = {1e3 / base:.3f} tok/s | (i) ratio {i_rat:.3f} "
              f"(x R2's kept gain {gret["R2"]:.4f}: {i_ret:.3f}) | (ii) absolute {ii:.3f} "
              f"(at the lowest retention {lo_ret:.4f}: {ii_lo:.3f}) | (iii) census-share {iii:.3f} | "
              f"MOVX scale {movx_scale:.4f}")
        BAND[(form, name)] = (ii_lo, iii, max(i_rat, ii, iii))
    r2 = S["R2"]
    fence_after = r2["fence"] + IDLE_UP[form] * fen_r
    step_after = r2["cyc"] - LANE_RM[form] * movx_r + IDLE_UP[form] * fen_r
    movx_after = r2["movx"] - LANE_RM[form] * movx_r
    print(f"   stream shares after {form} (census-share form): FENCE {100 * r2['fence'] / r2['cyc']:.2f} % -> "
          f"{100 * fence_after / step_after:.2f} % ({msc(fence_after):.3f} ms); MOVX {100 * r2['movx'] / r2['cyc']:.2f} % -> "
          f"{100 * movx_after / step_after:.2f} % ({msc(movx_after):.3f} ms); step {msc(step_after):.3f} ms")
print("-- the band (low = absolute at the lowest retention; mid = census-share; high = max of the three forms)")
for (form, name), (lo, mid, hi) in BAND.items():
    base = dict(bases)[name]
    print(f"   BAND {form} {name:9s}: {lo:.3f} .. {mid:.3f} .. {hi:.3f} tok/s  = x{lo * base / 1e3:.4f} .. "
          f"x{mid * base / 1e3:.4f} .. x{hi * base / 1e3:.4f} over R2 measured")

print("\n== E. ceilings (what is left after R2)")
for name, D in (("stream", S["R2"]), ("chat full", C["R2"])):
    free = D["cyc"] - D["fence"]
    print(f"  {name}: if EVERY FENCE wait vanished and nothing else moved: {msc(D['cyc']):.3f} - {msc(D['fence']):.3f} "
          f"= {msc(free):.3f} ms = {1e3 / msc(free):.3f} tok/s (x{D['cyc'] / free:.4f})")
crit = msc(CRIT_TB)
print(f"  MODEL dependency critical path (unlimited lanes, R2 buffers, elision; n06:832): {crit:.3f} ms TB "
      f"= {crit * TBF:.3f} ms board-scaled = {1e3 / (crit * TBF):.3f} tok/s; R3(a) MODEL makespan "
      f"{msc(MK['R3(a)']):.3f} ms TB is {100 * CRIT_TB / MK['R3(a)']:.1f} % of the way (floor/makespan)")
print(f"  MODEL R2 -> floor: {msc(MK['R2'] - CRIT_TB):.3f} ms TB/token; R3(a) takes {msc(MK['R2'] - MK['R3(a)']):.3f} of it "
      f"({100 * (MK['R2'] - MK['R3(a)']) / (MK['R2'] - CRIT_TB):.1f} %)")
print("SR16_DECISION_TABLE: DONE")
