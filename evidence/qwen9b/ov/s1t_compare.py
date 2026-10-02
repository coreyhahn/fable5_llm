#!/usr/bin/env python3
"""s1t_compare.py — Task S1T: judge the chip-TB runs of the chat images.

    python evidence/qwen9b/ov/s1t_compare.py c1 c2 c3 c4

For every scenario tag it reads the two seed logs the runner wrote,
evidence/qwen9b/ov/seedlogs_s1t/s1t_<tag>_{ship,B}_control.log, and
requires:
  * both runs `TB_SEQ_CHIP PASS` (every launch's end state == its golden);
  * the same number of launches, of the same kinds, in the same order;
  * the chip's OUT tokens IDENTICAL, launch by launch, form B vs shipped.
It prints the per-launch cycle counts and the form-B speed-up per launch
kind, and sets them beside SV1's form-B TEMPLATE per-token figure
(171,731,320 cyc / 6 tokens, evidence/qwen9b/ov/SV1_S1_VERIFY.md §3) and
the shipped template's (196,706,821 / 6, the same table).  Run ON SNOKE
through evidence/qwen9b/ov/ov_run.sh.
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
LOGDIR = os.path.join(ROOT, "evidence", "qwen9b", "ov", "seedlogs_s1t")
SV1_B_TOK = 171_731_320 / 6          # T: SV1_S1_VERIFY.md §3, s1 form B
SHIP_TOK = 196_706_821 / 6           # T: SV1_S1_VERIFY.md §3 / S4_REPLAY:398
RX_TOK = re.compile(r"^\s*TOK\[(\d+)\] = [0-9a-f]+ \((\d+)\) == golden OK")
RX_L = re.compile(r"^SEQ-CHIP \S+ launch (\d+) \[(\w+)\]: (\d+) records, "
                  r"(\d+) cycles")
RX_P = re.compile(r"^TB_SEQ_CHIP PASS: \S+ \(launches (\d+), (\d+) cycles")


def parse(path):
    launches, toks, passed = [], [], None
    for ln in open(path, errors="replace"):
        m = RX_TOK.match(ln)
        if m:
            toks.append(int(m.group(2)))
            continue
        m = RX_L.match(ln)
        if m:
            launches.append({"i": int(m.group(1)), "kind": m.group(2),
                             "nrec": int(m.group(3)),
                             "cyc": int(m.group(4)), "tok": toks})
            toks = []
            continue
        m = RX_P.match(ln)
        if m:
            passed = (int(m.group(1)), int(m.group(2)))
    return launches, passed


def main():
    tags = sys.argv[1:]
    assert tags, "usage: s1t_compare.py <tag>..."
    ok = True
    agg = {}
    for tag in tags:
        side = {}
        for s in ("ship", "B"):
            p = os.path.join(LOGDIR, f"s1t_{tag}_{s}_control.log")
            side[s] = parse(p)
            L, P = side[s]
            print(f"  {tag} {s:4s}: {os.path.relpath(p, ROOT)}  "
                  f"{'PASS ' + str(P) if P else 'NO PASS LINE'}")
            ok &= P is not None and P[0] == len(L)
        (Ls, Ps), (Lb, Pb) = side["ship"], side["B"]
        if len(Ls) != len(Lb) or [x["kind"] for x in Ls] != [
                y["kind"] for y in Lb]:
            print(f"  {tag}: LAUNCH SEQUENCES DIFFER — FAIL")
            ok = False
            continue
        for x, y in zip(Ls, Lb):
            same = x["tok"] == y["tok"]
            # fix round 1: a full launch must emit a token on BOTH sides —
            # a golden regenerated with zero TOK lines must FAIL here, not
            # compare [] == [] as identical
            if x["kind"] == "full" and not (x["tok"] and y["tok"]):
                print(f"    launch {x['i']} full: EMPTY token list "
                      f"(ship {x['tok']}, B {y['tok']}) — FAIL")
                same = False
            ok &= same
            r = x["cyc"] / y["cyc"]
            agg.setdefault(x["kind"], []).append((x["cyc"], y["cyc"]))
            print(f"    launch {x['i']} {x['kind']:8s} records "
                  f"{x['nrec']:6d} -> {y['nrec']:6d}  cycles "
                  f"{x['cyc']:11,d} -> {y['cyc']:11,d}  x{r:.4f}  tokens "
                  f"{x['tok']} vs {y['tok']} "
                  f"{'IDENTICAL' if same else 'DIFFER'}")
        if Ps and Pb:
            print(f"    total cycles {Ps[1]:,d} -> {Pb[1]:,d}  "
                  f"x{Ps[1] / Pb[1]:.4f}")
    print("--- per launch kind, over all scenarios (shipped -> form B)")
    for k, v in agg.items():
        rs = [a / b for a, b in v]
        print(f"  {k:8s} n={len(v)}  shipped {min(a for a, _ in v):,d}.."
              f"{max(a for a, _ in v):,d}  B {min(b for _, b in v):,d}.."
              f"{max(b for _, b in v):,d}  x{min(rs):.4f}..x{max(rs):.4f}")
        # fix round 1: the spread each side's range implies
        sa = max(a for a, _ in v) - min(a for a, _ in v)
        sb = max(b for _, b in v) - min(b for _, b in v)
        print(f"  {k:8s} spread: shipped {sa:,d} cyc "
              f"({sa / min(a for a, _ in v):.5%}), B {sb:,d} cyc "
              f"({sb / min(b for _, b in v):.5%})")
    print(f"  SV1 template per token (T): shipped {SHIP_TOK:,.0f}, form B "
          f"{SV1_B_TOK:,.0f}, x{SHIP_TOK / SV1_B_TOK:.4f}")
    if "full" in agg:
        fb = [b for _, b in agg["full"]]
        print(f"  form-B full image vs SV1 form-B template token: "
              + ", ".join(f"{b / SV1_B_TOK - 1:+.3%}" for b in fb))
    print(f"S1T_COMPARE: {'PASS' if ok else 'FAIL'} — {len(tags)} scenario(s)"
          f", tokens {'IDENTICAL' if ok else 'NOT all identical / runs failed'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
