#!/usr/bin/env python3
"""bm1_board_table.py — BM1-T4: the board table for BM1_BOARD_IDLE.md, from
the committed JSONs only (no device).  Run ON SNOKE via bm_run.sh.

TB comparand: the chip-TB launch totals of model_9b_s1 (6 tokens) as read
from the RTL registers in G1, evidence/qwen9b/bm/BM1_T1_GATE.md §3.2/§3.3
(n10_G1_bmtl_model_9b_s1.log:1103-1117).
"""
import json
import os
import statistics as st

B = os.path.join(os.path.dirname(os.path.abspath(__file__)))
F = 250e6
TB = {"cyc": 196706812, "mvany": 81689902, "mv0": 81492987, "mv1": 81235575,
      "mv2": 81149421, "mv3": 81149554, "fence": 81582408,
      "mvwork": 48822048, "mvwork_any": 181511, "imover": 130453404,
      "steps": 6, "movx": 31540704, "movy": 17050656, "l_lcyc": 62414792}
REF = [760, 20438, 18253, 5134, 421, 279, 3177, 314, 11751]   # 083 first 9
KEYS = ("mvany", "mv0", "mv1", "mv2", "mv3", "fence", "mvwork",
        "mvwork_any", "imover", "movx", "movy")


def J(n):
    return json.load(open(os.path.join(B, n)))


def row(name, d, ntok):
    cyc = d["cyc"]
    print(f"| {name} | {cyc / ntok:,.0f} | {cyc / ntok / F * 1e3:.4f} | "
          + " | ".join(f"{d[k] / cyc * 100:.2f}" for k in
                       ("mvany", "fence", "mvwork", "imover", "l_lcyc"))
          + f" | {max(d[k] for k in ('mv0','mv1','mv2','mv3')) / min(d[k] for k in ('mv0','mv1','mv2','mv3')):.4f} |")


def stream(n):
    j = J(n)
    d = {"cyc": j["perf"]["cyc"], "l_lcyc": j["l_lcyc"],
         "l_sdma": j["l_sdma_cyc"]}
    d.update(j["perf"]["bm"])
    return d, j


def chat(n, kind):
    j = J(n)
    L = [r for r in j["launches"] if r["image"] == kind]
    d = {"cyc": st.mean(r["perf"]["cyc"] for r in L),
         "l_lcyc": st.mean(r["l_lcyc"] for r in L),
         "l_sdma": st.mean(r["l_sdma_cyc"] for r in L), "n": len(L),
         "min": min(r["perf"]["cyc"] for r in L),
         "max": max(r["perf"]["cyc"] for r in L)}
    if "bm" in L[0]["perf"]:
        for k in KEYS:
            d[k] = st.mean(r["perf"]["bm"][k] for r in L)
    toks = [t for r in j["launches"] for t in (r["tokens"] or [])]
    return d, toks


print("== §1 stream census (6 tokens, per token) — fractions of PERF_CYC, %")
print("| run | cyc/token | ms/token | MVANY | FENCE | MVWORK | IMOVER | L_LCYC | MVc max/min |")
print("|---|---|---|---|---|---|---|---|---|")
row("chip TB census (BM1_T1_GATE §3.2)", TB, 6)
s72, j72 = stream("n72_T4_bm1_stream_model_9b_s1.json")
s73, j73 = stream("n73_T4_bm1_stream_reordA.json")
row("board BM1, shipped order (n72)", s72, 6)
row("board BM1, S1 form A (n73)", s73, 6)
print(f"tokens n72 {j72['tokens']} ok={j72['tokens'] == j72['want']}; "
      f"n73 {j73['tokens']} ok={j73['tokens'] == j73['want']}")
print("board/TB per counter (n72 / TB): " + ", ".join(
    f"{k} {s72[k] / TB[k]:.4f}" for k in ("cyc",) + KEYS + ("l_lcyc",)))
print(f"MVWORK - MVWORK_ANY (n72, per token): "
      f"{(s72['mvwork'] - s72['mvwork_any']) / 6:,.0f}")
print(f"stream S1 speed-up n72/n73: {s72['cyc'] / s73['cyc']:.4f}")
print(f"weight path idle (PERF-MVANY)/PERF: TB "
      f"{(TB['cyc'] - TB['mvany']) / TB['cyc'] * 100:.2f} %, n72 "
      f"{(s72['cyc'] - s72['mvany']) / s72['cyc'] * 100:.2f} %, n73 "
      f"{(s73['cyc'] - s73['mvany']) / s73['cyc'] * 100:.2f} %")

print("\n== §2/§3 chat sessions at context 511 (per launch means)")
print("| run | kind | n | PERF_CYC | ms | min..max cyc | L_LCYC % | L_SDMA % | MVANY % | FENCE % | MVWORK % | IMOVER % |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|")
res = {}
for n, tag in (("n68_T4_control_041_chat511.json", "041 control"),
               ("n71_T4_bm1_chat511.json", "BM1 shipped order"),
               ("n74_T4_bm1_chat511_reordA.json", "BM1 S1 form A")):
    for kind in ("lite", "full"):
        d, toks = chat(n, kind)
        res[(tag, kind)] = d
        bm = ("mvany" in d)
        f = (lambda k: f"{d[k] / d['cyc'] * 100:.2f}" if bm else "—")
        print(f"| {tag} | {kind} | {d['n']} | {d['cyc']:,.1f} | "
              f"{d['cyc'] / F * 1e3:.4f} | {d['min']:,}..{d['max']:,} | "
              f"{d['l_lcyc'] / d['cyc'] * 100:.2f} | "
              f"{d['l_sdma'] / d['cyc'] * 100:.2f} | {f('mvany')} | "
              f"{f('fence')} | {f('mvwork')} | {f('imover')} |")
    print(f"  {tag} tokens {toks}")
    res[(tag, "ids")] = toks
bad = [t for t, n in (("041 control", "n68"), ("BM1 shipped order", "n71"),
                      ("BM1 S1 form A", "n74")) if res[(t, "ids")] != REF]
print(f"TOKENS vs the pinned reference {REF}: "
      + ("IDENTICAL for n68, n71, n74" if not bad else f"MISMATCH in {bad}"))
if bad:
    raise SystemExit(1)
for kind in ("lite", "full"):
    c, b, s = (res[("041 control", kind)]["cyc"],
               res[("BM1 shipped order", kind)]["cyc"],
               res[("BM1 S1 form A", kind)]["cyc"])
    print(f"{kind}: BM1/041 = {b / c:.6f} ({(b - c) / c * 100:+.4f} %); "
          f"S1 speed-up (BM1 shipped / S1) = {b / s:.4f}")


# ----------------------------------------------------------------------
# Fix round 1: the run-to-run spread, from PAIRED launches (same image,
# same position) across the three sessions — the lite step time rises with
# the position (KV depth), so only paired deltas measure the noise.
def per_pos(n):
    return {(r["image"], r["pos"]): r["perf"]["cyc"]
            for r in J(n)["launches"] if r["image"] in ("lite", "full")}


def pstats(xs):
    m = st.mean(xs)
    return m, st.pstdev(xs), min(xs), max(xs)


A, Bm, S = (per_pos("n68_T4_control_041_chat511.json"),
            per_pos("n71_T4_bm1_chat511.json"),
            per_pos("n74_T4_bm1_chat511_reordA.json"))
assert set(A) == set(Bm) == set(S), "the three sessions' launches differ"
print("\n== paired spread (fix round 1)")
for kind in ("lite", "full"):
    ks = sorted(k for k in A if k[0] == kind)
    d = [(Bm[k] - A[k]) / A[k] * 100 for k in ks]
    m, sd, lo, hi = pstats(d)
    print(f"{kind}: BM1 vs 041 paired delta over {len(ks)} positions: mean "
          f"{m:+.4f} %, sd {sd:.4f} %, range {lo:+.4f} .. {hi:+.4f} %; "
          f"|mean|/(sd/sqrt(n)) = {abs(m) / (sd / len(ks) ** 0.5) if sd else float('inf'):.2f}")
    r = [Bm[k] / S[k] for k in ks]
    m, sd, lo, hi = pstats(r)
    print(f"{kind}: S1 speed-up paired (n71/n74) over {len(ks)} positions: mean "
          f"x{m:.4f}, sd {sd:.4f}, range x{lo:.4f} .. x{hi:.4f}")
