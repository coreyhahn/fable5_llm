#!/usr/bin/env python3
"""sr8_board_table.py — Task SR8: the board table for SR8_R1_BOARD.md, from
the committed JSONs only (no device).  Run ON SNOKE via sr_run.sh.  A copy of
evidence/qwen9b/bm/bm1_board_table.py's method (per-launch means, paired
per-position ratios, token identity asserted — exit 1 on any difference),
retargeted to this session's logs.

E = this session (n802 build_041 form B; n805 R1 lockstep; n806 R1 bitstream
r0 form B; n807 R1 bitstream r1; n808/n809 stream census r1 / r0-B; n812 the
restore sanity).  T = n95 (S1P, build_041 form B), n68 (BM1-T4, build_041
shipped order), n72 (BM1-T4 stream census, shipped order, build_042_bm1).
"""
import json
import os
import statistics as st
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SR = "evidence/qwen9b/sr/"
F = 250e6
REF = [760, 20438, 18253, 5134, 421, 279, 3177, 314, 11751]   # 083 first 9
G4A = {1: [2614, 314, 279, 369, 11751, 13], 2: [279, 264, 854, 11, 303, 264],
       3: [313, 430, 2510, 198, 1445, 27180], 4: [11, 0, 271, 803, 369, 498]}
N77 = [760, 6511, 314, 9338, 369, 2972, 57590, 159034, 271, 2064, 369, 279,
       3046, 579, 1379, 91188, 3177, 321, 264, 3478, 3521, 3990, 364, 16519]
BMK = ("mvany", "fence", "mvwork", "imover")
# the predictions, exactly as n815 printed them (committed before any R1 run)
PRED = {"lite": {"P1": 109.1968, "P2": 111.4490, "P3": 111.7953},
        "full": {"P1": 124.5213, "P2": 124.6159, "P3": 125.4614}}
MODEL_TOKS = 8.811
BAD = []


def J(p):
    return json.load(open(os.path.join(ROOT, p)))


def band(x):
    a = abs(x)
    return "HELD" if a <= 0.5 else ("HELD LOOSELY" if a <= 2.0 else "MISSED")


def pst(xs):
    return st.mean(xs), st.pstdev(xs), min(xs), max(xs)


# ---------------------------------------------------------------- lockstep
print("== A. RD9 §7 lockstep on R1 (n805): model_9b_s1..s4, shipped order")
print("| seed | tokens | G4A §4.1a | verdict | err_code | .chip golden | device ms | SEQ_CAPS |")
print("|---|---|---|---|---|---|---|---|")
for s in (1, 2, 3, 4):
    j = J(SR + f"n805_sr8_r1_model_9b_s{s}.json")
    t = j["run"]["tokens"]
    ok = (t == G4A[s] == j["meta"]["expect_tokens"]) and j["pass"] \
        and j["run"]["status"]["err_code"] == 0
    if not ok:
        BAD.append(f"n805 s{s}")
    g = j.get("golden") or {}
    gok = bool(g.get("pass")) and not g.get("mismatches")
    if not gok:
        BAD.append(f"n805 s{s} golden")
    gtxt = f"{g.get('checks', '?')} checks, " + ("ALL MATCH" if gok else "MISMATCH")
    print(f"| s{s} | {t} | {G4A[s]} | {'IDENTICAL' if ok else 'MISMATCH'} | "
          f"{j['run']['status']['err_code']:#04x} | {gtxt} | "
          f"{j['run']['device_ms']:.3f} | {j['ident']['seq_caps']} |")
j1 = J(SR + "n805_sr8_r1_model_9b_s1.json")
p = j1["run"]["perf"]
print(f"s1 on R1, shipped order, per token: {p['cyc'] / 6:,.0f} cyc = "
      f"{p['cyc'] / 6 / F * 1e3:.4f} ms; " + ", ".join(
          f"{k} {p['bm'][k] / p['cyc'] * 100:.2f} %" for k in BMK))
n72 = J("evidence/qwen9b/bm/n72_T4_bm1_stream_model_9b_s1.json")
q = n72["perf"]
print(f"n72 (T, build_042_bm1, shipped order, bm1_census): {q['cyc'] / 6:,.0f} "
      f"cyc/token = {q['cyc'] / 6 / F * 1e3:.4f} ms; " + ", ".join(
          f"{k} {q['bm'][k] / q['cyc'] * 100:.2f} %" for k in BMK)
      + f"; R1-bitstream/n72 cyc = {p['cyc'] / q['cyc']:.6f}")


# ---------------------------------------------------------------- chat
def chat(path):
    j = J(path)
    L = j["launches"]
    ids = [t for r in L for t in (r["tokens"] or [])]
    out = {"ids": ids, "rc": j["rc"], "env": j.get("env"), "argv": j["argv"]}
    for kind in ("lite", "full"):
        K = [r for r in L if r["image"] == kind]
        d = {"n": len(K), "cyc": st.mean(r["perf"]["cyc"] for r in K),
             "min": min(r["perf"]["cyc"] for r in K),
             "max": max(r["perf"]["cyc"] for r in K),
             "l_lcyc": st.mean(r["l_lcyc"] for r in K),
             "l_sdma": st.mean(r["l_sdma_cyc"] for r in K),
             "pos": {r["pos"]: r["perf"]["cyc"] for r in K}}
        if all("bm" in r["perf"] for r in K):
            for k in BMK + ("movx", "movy"):
                d[k] = st.mean(r["perf"]["bm"][k] for r in K)
        out[kind] = d
    return out


RUNS = [("n68", "T build_041 shipped order", "evidence/qwen9b/bm/n68_T4_control_041_chat511.json"),
        ("n95", "T build_041 form B", "evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.json"),
        ("n802", "E build_041 form B (control)", SR + "n802_sr8_control_041_chat511.json"),
        ("n806", "E R1 bitstream, r0 form B", SR + "n806_sr8_r1bit_r0B_chat511.json"),
        ("n807", "E R1 bitstream, r1", SR + "n807_sr8_r1_chat511.json")]
C = {}
print("\n== B. chat511 sessions (context 511, --ntok 9), per-launch means")
print("| run | what | kind | n | PERF_CYC | ms | tok/s | min..max cyc | L_LCYC % | L_SDMA % | MVANY % | FENCE % | MVWORK % | IMOVER % |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for key, what, path in RUNS:
    c = chat(path)
    C[key] = c
    for kind in ("lite", "full"):
        d = c[kind]
        f = (lambda k: f"{d[k] / d['cyc'] * 100:.2f}" if k in d else "—")
        ms = d["cyc"] / F * 1e3
        print(f"| {key} | {what} | {kind} | {d['n']} | {d['cyc']:,.1f} | "
              f"{ms:.4f} | {1e3 / ms:.3f} | {d['min']:,}..{d['max']:,} | "
              f"{d['l_lcyc'] / d['cyc'] * 100:.2f} | "
              f"{d['l_sdma'] / d['cyc'] * 100:.2f} | {f('mvany')} | "
              f"{f('fence')} | {f('mvwork')} | {f('imover')} |")
for key, what, _ in RUNS:
    ok = C[key]["ids"] == REF and C[key]["rc"] == 0
    if not ok:
        BAD.append(key)
    print(f"  {key} ids {C[key]['ids']} rc {C[key]['rc']} env "
          f"{C[key]['env']} -> {'IDENTICAL' if ok else 'MISMATCH'} vs REF")
for key in ("n806", "n807"):
    for kind in ("lite", "full"):
        d = C[key][kind]
        print(f"  {key} {kind}: MOVX {d['movx']:,.0f} MOVY {d['movy']:,.0f} "
              f"cyc per launch")

print("\n== C. paired by position (same image, same pos) — mean, sd, range, |mean|/SE")
PAIRS = [("n802", "n95", "day repeat, build_041 form B"),
         ("n806", "n802", "bitstream alone: R1 bitstream vs build_041, both r0 form B"),
         ("n807", "n806", "R1 vs S1-B, SAME bitstream"),
         ("n807", "n802", "R1 vs build_041 form B"),
         ("n807", "n68", "R1 vs build_041 shipped order")]
for a, b, what in PAIRS:
    for kind in ("lite", "full"):
        A, B = C[a][kind]["pos"], C[b][kind]["pos"]
        if set(A) != set(B):
            BAD.append(f"positions {a}/{b}")
            print(f"  {a} vs {b} {kind}: POSITIONS DIFFER")
            continue
        ks = sorted(A)
        d = [(A[k] - B[k]) / B[k] * 100 for k in ks]
        r = [B[k] / A[k] for k in ks]
        m, sd, lo, hi = pst(d)
        mr, sdr, lor, hir = pst(r)
        se = sd / len(ks) ** 0.5 if sd else 0.0
        print(f"  {a} vs {b} ({what}) {kind} n={len(ks)}: delta mean {m:+.4f} % "
              f"sd {sd:.4f} % range {lo:+.4f}..{hi:+.4f} %"
              + (f" |mean|/SE {abs(m) / se:.1f}" if se else "")
              + f"; speed-up {b}/{a} mean x{mr:.4f} sd {sdr:.4f} range "
              f"x{lor:.4f}..x{hir:.4f}; means ratio "
              f"x{C[b][kind]['cyc'] / C[a][kind]['cyc']:.4f}")

print("\n== D. the predictions (n815, committed before any R1 run) against n807")
for kind in ("lite", "full"):
    ms = C["n807"][kind]["cyc"] / F * 1e3
    for tag, pv in PRED[kind].items():
        x = (ms / pv - 1) * 100
        print(f"  {kind} {tag}: predicted {pv:.4f} ms, measured {ms:.4f} ms "
              f"({1e3 / ms:.3f} tok/s vs {1e3 / pv:.3f}), {x:+.3f} % -> {band(x)}")
for key in ("n802", "n806"):
    for kind in ("lite", "full"):
        ms = C[key][kind]["cyc"] / F * 1e3
        b = C["n95"][kind]["cyc"] / F * 1e3
        x = (ms / b - 1) * 100
        print(f"  control {key} {kind}: vs n95 {b:.4f} ms: {ms:.4f} ms "
              f"{x:+.4f} % -> {band(x)}")
for kind in ("lite", "full"):
    s802 = C["n802"][kind]["cyc"] - C["n807"][kind]["cyc"]
    s806 = C["n806"][kind]["cyc"] - C["n807"][kind]["cyc"]
    print(f"  {kind}: R1 absolute saving vs n806 {s806 / F * 1e3:.4f} ms, vs "
          f"n802 {s802 / F * 1e3:.4f} ms per launch")


# ---------------------------------------------------------------- stream
def stream(path):
    j = J(path)
    d = {"cyc": j["perf"]["cyc"], "l_lcyc": j["l_lcyc"],
         "l_sdma": j["l_sdma_cyc"], "ntok": j["ntok"], "tokens": j["tokens"],
         "want": j["want"], "err": j["err_code"], "version": j["version"]}
    d.update(j["perf"].get("bm") or {})
    return d


print("\n== E. the 6-token stream census (model_9b_s1 form B), per token")
print("| run | what | cyc/token | ms/token | tok/s | MVANY % | FENCE (C5) % | MVWORK % | IMOVER % | L_LCYC % | tokens |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
S = {}
for key, what, path in (("n72", "T build_042_bm1 shipped order", "evidence/qwen9b/bm/n72_T4_bm1_stream_model_9b_s1.json"),
                        ("n809", "E R1 bitstream, r0 form B", SR + "n809_sr8_census_r0B.json"),
                        ("n808", "E R1 bitstream, r1", SR + "n808_sr8_census_r1.json")):
    d = stream(path)
    S[key] = d
    ok = d["tokens"] == d["want"] and not d["err"]
    if not ok:
        BAD.append(key)
    ms = d["cyc"] / d["ntok"] / F * 1e3
    print(f"| {key} | {what} | {d['cyc'] / d['ntok']:,.0f} | {ms:.4f} | "
          f"{1e3 / ms:.3f} | " + " | ".join(
              f"{d[k] / d['cyc'] * 100:.2f}" for k in BMK)
          + f" | {d['l_lcyc'] / d['cyc'] * 100:.2f} | "
          f"{'IDENTICAL' if ok else 'MISMATCH'} {d['tokens']} |")
r1ms = S["n808"]["cyc"] / S["n808"]["ntok"] / F * 1e3
print(f"stream r1 vs its r0-B control (same bitstream): "
      f"x{S['n809']['cyc'] / S['n808']['cyc']:.4f} (chip TB x1.0538, n570:21); "
      f"r1 vs n72 shipped order: x{S['n72']['cyc'] / S['n808']['cyc']:.4f} "
      f"(chip TB x1.2070)")
print(f"stream r1 tok/s {1e3 / r1ms:.3f} vs the model's {MODEL_TOKS} "
      f"(spec §3.1): measured/model {1e3 / r1ms / MODEL_TOKS:.4f} "
      f"({(1e3 / r1ms / MODEL_TOKS - 1) * 100:+.3f} % -> "
      f"{band((MODEL_TOKS * r1ms / 1e3 - 1) * 100)} on ms/token)")
print(f"C5 FENCE-wait share: n72 {S['n72']['fence'] / S['n72']['cyc'] * 100:.2f} % "
      f"(shipped) -> n809 {S['n809']['fence'] / S['n809']['cyc'] * 100:.2f} % "
      f"(S1-B) -> n808 {S['n808']['fence'] / S['n808']['cyc'] * 100:.2f} % (R1); "
      f"FENCE cycles per token {S['n72']['fence'] / 6:,.0f} -> "
      f"{S['n809']['fence'] / 6:,.0f} -> {S['n808']['fence'] / 6:,.0f}")

# ---------------------------------------------------------------- restore
print("\n== F. the restore sanity (n812, build_041, variable unset)")
c = J(SR + "n812_sr8_restore_chat_sanity.json")
ids = [t for r in c["launches"] for t in (r["tokens"] or [])]
ok = ids == N77 and c["rc"] == 0
if not ok:
    BAD.append("n812")
print(f"  ids {ids} rc {c['rc']} env {c.get('env')} -> "
      f"{'IDENTICAL' if ok else 'MISMATCH'} vs n77's 24 ids")

print("\nTOKENS on every run: " + ("IDENTICAL" if not BAD else f"MISMATCH in {BAD}"))
print("SR8_BOARD_TABLE: " + ("DONE" if not BAD else "FAIL"))
sys.exit(1 if BAD else 0)
