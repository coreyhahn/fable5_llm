#!/usr/bin/env python3
"""sr15_board_table.py — Task SR15: the board table for SR15_R2_BOARD.md, from
the committed JSONs only (no device).  Run ON SNOKE via sr_run.sh.  A copy of
evidence/qwen9b/sr/sr8_board_table.py (per-launch means, paired per-position
ratios, token identity asserted — exit 1 on any difference), retargeted to
this session's logs; the method is unchanged.

E = this session (n1502 build_041 form B; n1505 R2 lockstep; n1506 R2
bitstream r0 form B; n1507 R2 bitstream r1; n1508 R2 bitstream r2;
n1509/n1510/n1511 stream census r2 / r1 / r0-B; n1514 the restore sanity).
T = SR8 (n802, n805, n806, n807, n808, n809; the R1 bitstream), n95 (S1P,
build_041 form B), n68 (BM1-T4, build_041 shipped order), n72 (BM1-T4 stream
census, shipped order, build_042_bm1).
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
# the predictions, exactly as n1515 printed them (committed at 23c9f58,
# before any R2 run)
PRED = {"lite": {"P1'": 108.6569, "P2'": 107.9782},
        "full": {"P1'": 122.0975, "P2'": 121.5097}}
P3C = 110.2036              # n1515: P3' census ms/token
MODEL_TOKS = 9.144          # spec §3.1 R1+R2 form B (MODEL)
TB_R2_R1 = 1.0379           # n1349g_sr13a_derive.log:24 (whole run); token-4 x1.0379
BAD = []


def J(p):
    return json.load(open(os.path.join(ROOT, p)))


def band(x):
    a = abs(x)
    return "HELD" if a <= 0.5 else ("HELD LOOSELY" if a <= 2.0 else "MISSED")


def pst(xs):
    return st.mean(xs), st.pstdev(xs), min(xs), max(xs)


# ---------------------------------------------------------------- lockstep
print("== A. RD9 §7 lockstep on R2 (n1505): model_9b_s1..s4, shipped order")
print("| seed | tokens | G4A §4.1a | verdict | err_code | .chip golden | device ms | n805 (R1 bit) ms | delta % | SEQ_CAPS |")
print("|---|---|---|---|---|---|---|---|---|---|")
for s in (1, 2, 3, 4):
    j = J(SR + f"n1505_sr15_r2_model_9b_s{s}.json")
    k = J(SR + f"n805_sr8_r1_model_9b_s{s}.json")
    t = j["run"]["tokens"]
    ok = (t == G4A[s] == j["meta"]["expect_tokens"]) and j["pass"] \
        and j["run"]["status"]["err_code"] == 0
    if not ok:
        BAD.append(f"n1505 s{s}")
    g = j.get("golden") or {}
    gok = bool(g.get("pass")) and not g.get("mismatches")
    if not gok:
        BAD.append(f"n1505 s{s} golden")
    gtxt = f"{g.get('checks', '?')} checks, " + ("ALL MATCH" if gok else "MISMATCH")
    dm, km = j["run"]["device_ms"], k["run"]["device_ms"]
    print(f"| s{s} | {t} | {G4A[s]} | {'IDENTICAL' if ok else 'MISMATCH'} | "
          f"{j['run']['status']['err_code']:#04x} | {gtxt} | {dm:.3f} | "
          f"{km:.3f} | {(dm / km - 1) * 100:+.4f} ({band((dm / km - 1) * 100)}) | "
          f"{j['ident']['seq_caps']} |")
j1 = J(SR + "n1505_sr15_r2_model_9b_s1.json")
k1 = J(SR + "n805_sr8_r1_model_9b_s1.json")
p, q = j1["run"]["perf"], k1["run"]["perf"]
print(f"s1 on R2, shipped order, per token: {p['cyc'] / 6:,.0f} cyc = "
      f"{p['cyc'] / 6 / F * 1e3:.4f} ms; " + ", ".join(
          f"{k} {p['bm'][k] / p['cyc'] * 100:.2f} %" for k in BMK)
      + f"; R2-bitstream / R1-bitstream (n805) cyc = {p['cyc'] / q['cyc']:.6f}")


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
        ("n802", "T build_041 form B (SR8)", SR + "n802_sr8_control_041_chat511.json"),
        ("n806", "T R1 bitstream, r0 form B (SR8)", SR + "n806_sr8_r1bit_r0B_chat511.json"),
        ("n807", "T R1 bitstream, r1 (SR8)", SR + "n807_sr8_r1_chat511.json"),
        ("n1502", "E build_041 form B (control)", SR + "n1502_sr15_control_041_chat511.json"),
        ("n1506", "E R2 bitstream, r0 form B", SR + "n1506_sr15_r2bit_r0B_chat511.json"),
        ("n1507", "E R2 bitstream, r1", SR + "n1507_sr15_r2bit_r1_chat511.json"),
        ("n1508", "E R2 bitstream, r2", SR + "n1508_sr15_r2_chat511.json")]
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
for key in ("n1506", "n1507", "n1508"):
    for kind in ("lite", "full"):
        d = C[key][kind]
        print(f"  {key} {kind}: MOVX {d['movx']:,.0f} MOVY {d['movy']:,.0f} "
              f"cyc per launch")

print("\n== C. paired by position (same image, same pos) — mean, sd, range, |mean|/SE")
PAIRS = [("n1502", "n802", "day repeat, build_041 form B"),
         ("n1506", "n1502", "bitstream alone: R2 bitstream vs build_041, both r0 form B"),
         ("n1506", "n806", "R2 bitstream vs R1 bitstream, both r0 form B"),
         ("n1507", "n807", "R2 bitstream vs R1 bitstream, both r1 (R2 must not move R1)"),
         ("n1508", "n1507", "r2 vs r1, SAME (R2) bitstream"),
         ("n1508", "n1506", "r2 vs S1-B (r0 form B), SAME bitstream"),
         ("n1508", "n807", "r2 vs SR8's r1 on the R1 bitstream"),
         ("n1508", "n1502", "r2 vs build_041 form B (the shipped default)"),
         ("n1508", "n68", "r2 vs build_041 shipped order")]
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

print("\n== D. the predictions (n1515, committed at 23c9f58 before any R2 run) against n1508")
for kind in ("lite", "full"):
    ms = C["n1508"][kind]["cyc"] / F * 1e3
    for tag, pv in PRED[kind].items():
        x = (ms / pv - 1) * 100
        print(f"  {kind} {tag}: predicted {pv:.4f} ms, measured {ms:.4f} ms "
              f"({1e3 / ms:.3f} tok/s vs {1e3 / pv:.3f}), {x:+.3f} % -> {band(x)}")
for key, ref in (("n1502", "n802"), ("n1506", "n806"), ("n1507", "n807")):
    for kind in ("lite", "full"):
        ms = C[key][kind]["cyc"] / F * 1e3
        b = C[ref][kind]["cyc"] / F * 1e3
        x = (ms / b - 1) * 100
        print(f"  control {key} {kind}: vs {ref} {b:.4f} ms: {ms:.4f} ms "
              f"{x:+.4f} % -> {band(x)}")
for kind in ("lite", "full"):
    s1 = C["n1507"][kind]["cyc"] - C["n1508"][kind]["cyc"]
    s0 = C["n1506"][kind]["cyc"] - C["n1508"][kind]["cyc"]
    s8 = C["n807"][kind]["cyc"] - C["n1508"][kind]["cyc"]
    print(f"  {kind}: r2 absolute saving vs r1 (n1507) {s1 / F * 1e3:.4f} ms, vs "
          f"SR8's r1 (n807) {s8 / F * 1e3:.4f} ms, vs r0-B (n1506) "
          f"{s0 / F * 1e3:.4f} ms per launch")


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
                        ("n809", "T R1 bitstream, r0 form B (SR8)", SR + "n809_sr8_census_r0B.json"),
                        ("n808", "T R1 bitstream, r1 (SR8)", SR + "n808_sr8_census_r1.json"),
                        ("n1511", "E R2 bitstream, r0 form B", SR + "n1511_sr15_census_r0B.json"),
                        ("n1510", "E R2 bitstream, r1", SR + "n1510_sr15_census_r1.json"),
                        ("n1509", "E R2 bitstream, r2", SR + "n1509_sr15_census_r2.json")):
    d = stream(path)
    S[key] = d
    ok = d["tokens"] == d["want"] == G4A[1] and not d["err"]
    if not ok:
        BAD.append(key)
    ms = d["cyc"] / d["ntok"] / F * 1e3
    print(f"| {key} | {what} | {d['cyc'] / d['ntok']:,.0f} | {ms:.4f} | "
          f"{1e3 / ms:.3f} | " + " | ".join(
              f"{d[k] / d['cyc'] * 100:.2f}" for k in BMK)
          + f" | {d['l_lcyc'] / d['cyc'] * 100:.2f} | "
          f"{'IDENTICAL' if ok else 'MISMATCH'} {d['tokens']} |")
msk = {k: S[k]["cyc"] / S[k]["ntok"] / F * 1e3 for k in S}
print(f"stream r2 vs r1 (same bitstream): x{S['n1510']['cyc'] / S['n1509']['cyc']:.4f} "
      f"(chip TB x{TB_R2_R1}); r2 vs r0-B: x{S['n1511']['cyc'] / S['n1509']['cyc']:.4f}; "
      f"r2 vs n72 shipped order: x{S['n72']['cyc'] / S['n1509']['cyc']:.4f} (chip TB x1.2528)")
for key, ref in (("n1510", "n808"), ("n1511", "n809")):
    x = (msk[key] / msk[ref] - 1) * 100
    print(f"  census control {key} vs {ref}: {msk[key]:.4f} vs {msk[ref]:.4f} "
          f"ms/token {x:+.4f} % -> {band(x)}")
x = (msk["n1509"] / P3C - 1) * 100
print(f"  P3' census: predicted {P3C:.4f} ms/token, measured {msk['n1509']:.4f} "
      f"({1e3 / msk['n1509']:.3f} tok/s vs {1e3 / P3C:.3f}), {x:+.3f} % -> {band(x)}")
x = (MODEL_TOKS * msk["n1509"] / 1e3 - 1) * 100
print(f"stream r2 tok/s {1e3 / msk['n1509']:.3f} vs the model's {MODEL_TOKS} "
      f"(spec §3.1): measured/model {1e3 / msk['n1509'] / MODEL_TOKS:.4f} "
      f"({(1e3 / msk['n1509'] / MODEL_TOKS - 1) * 100:+.3f} % -> {band(x)} on ms/token)")
print(f"C5 FENCE-wait share: n72 {S['n72']['fence'] / S['n72']['cyc'] * 100:.2f} % "
      f"(shipped) -> n1511 {S['n1511']['fence'] / S['n1511']['cyc'] * 100:.2f} % "
      f"(S1-B) -> n1510 {S['n1510']['fence'] / S['n1510']['cyc'] * 100:.2f} % (R1) "
      f"-> n1509 {S['n1509']['fence'] / S['n1509']['cyc'] * 100:.2f} % (R2); "
      f"FENCE cycles per token {S['n72']['fence'] / 6:,.0f} -> "
      f"{S['n1511']['fence'] / 6:,.0f} -> {S['n1510']['fence'] / 6:,.0f} -> "
      f"{S['n1509']['fence'] / 6:,.0f}")

# ---------------------------------------------------------------- restore
print("\n== F. the restore sanity (n1514, build_041, variable unset)")
c = J(SR + "n1514_sr15_restore_chat_sanity.json")
ids = [t for r in c["launches"] for t in (r["tokens"] or [])]
ok = ids == N77 and c["rc"] == 0
if not ok:
    BAD.append("n1514")
print(f"  ids {ids} rc {c['rc']} env {c.get('env')} -> "
      f"{'IDENTICAL' if ok else 'MISMATCH'} vs n77's 24 ids")

print("\nTOKENS on every run: " + ("IDENTICAL" if not BAD else f"MISMATCH in {BAD}"))
print("SR15_BOARD_TABLE: " + ("DONE" if not BAD else "FAIL"))
sys.exit(1 if BAD else 0)
