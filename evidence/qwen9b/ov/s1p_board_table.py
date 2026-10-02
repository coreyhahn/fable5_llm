#!/usr/bin/env python3
"""s1p_board_table.py — Task S1P deliverable 3: form B on silicon against the
T4 sessions, from the committed JSONs only (no device).  Run ON SNOKE.

    python evidence/qwen9b/ov/s1p_board_table.py [n95 json]

  n68  build_041, shipped order        evidence/qwen9b/bm/n68_T4_control_041_chat511.json
  n74  BM1 roll, S1 form A (template)  evidence/qwen9b/bm/n74_T4_bm1_chat511_reordA.json
  n95  build_041, S1 form B (images)   evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.json

Step time = the per-launch S_PERF_CYC (perf.cyc) at 250 MHz, as T4 took it.
Speed-ups are PAIRED by (image, position) — the lite step grows with the KV
depth, so only same-position pairs compare like with like.  Exits 1 if n95's
tokens differ from the pinned reference.
"""
import json
import os
import statistics as st
import sys

R = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
F = 250e6
REF = [760, 20438, 18253, 5134, 421, 279, 3177, 314, 11751]
RUNS = (("n68 041 shipped", "evidence/qwen9b/bm/n68_T4_control_041_chat511.json"),
        ("n74 BM1 form A", "evidence/qwen9b/bm/n74_T4_bm1_chat511_reordA.json"),
        ("n95 041 form B", "evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.json"))


def load(p):
    j = json.load(open(os.path.join(R, p)))
    per = {(r["image"], r["pos"]): r["perf"]["cyc"] for r in j["launches"]
           if r["image"] in ("lite", "full")}
    toks = [t for r in j["launches"] for t in (r["tokens"] or [])]
    return per, toks


def main():
    runs = list(RUNS)
    if len(sys.argv) > 1:
        runs[2] = (runs[2][0], sys.argv[1])
    D = {}
    for tag, p in runs:
        per, toks = load(p)
        D[tag] = per
        print(f"{tag}: {len(per)} launches; tokens {toks} "
              f"{'== REF' if toks == REF else '!= REF'}")
        if tag.startswith("n95") and toks != REF:
            print("TOKENS DIFFER — STOP")
            raise SystemExit(1)
    keys = set(D[runs[0][0]])
    assert all(set(D[t]) == keys for t, _ in runs), "launch sets differ"
    print("\n| run | kind | n | mean PERF_CYC | mean ms |")
    print("|---|---|---|---|---|")
    mean = {}
    for tag, _ in runs:
        for kind in ("lite", "full"):
            v = [D[tag][k] for k in keys if k[0] == kind]
            mean[(tag, kind)] = st.mean(v)
            print(f"| {tag} | {kind} | {len(v)} | {st.mean(v):,.1f} | "
                  f"{st.mean(v) / F * 1e3:.4f} |")
    b, s, a = runs[2][0], runs[0][0], runs[1][0]
    for kind in ("lite", "full"):
        ks = sorted(k for k in keys if k[0] == kind)
        for ref in (s, a):
            r = [D[ref][k] / D[b][k] for k in ks]
            print(f"{kind}: form B vs {ref}: means x"
                  f"{mean[(ref, kind)] / mean[(b, kind)]:.4f}; paired over "
                  f"{len(ks)} positions mean x{st.mean(r):.4f} sd "
                  f"{st.pstdev(r):.4f} range x{min(r):.4f}..x{max(r):.4f}")
    print("S1P_BOARD_TABLE: DONE")


if __name__ == "__main__":
    main()
