#!/usr/bin/env python3
"""ov_derive.py — Task OV1: every derived number the memo quotes that is not
already printed by ov_census.py, computed here (on snoke, through ov_run.sh)
so that no arithmetic is done by hand.

    FABLE5_MODEL=9b python evidence/qwen9b/ov/ov_derive.py <n06 log>

It (1) re-reads the list-schedule results from the committed log of
ov_census.py (printing the log line each number came from), (2) converts
them to board scale and to fractions of the census's bounds, (3) ranks the
recovered stream time by class, (4) sizes the double buffers from the RTL
array shapes, and (5) re-reads the stream + timeline (through ov_census's own
loaders, sha-checked) to size the in_qkv / q_proj row-sub-chunk option of
deliverable 3.  Read-only; stdout only.
"""
import collections
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ov_census as OV          # noqa: E402

TB_MS = OV.TB_MS                # 131.138 (BN_CENSUS.md §3)
BOARD_MS = OV.BOARD_MS          # 137.121 (RD9 §10.1)
CEIL_MS = 55.634                # BN_CENSUS.md §9.1 floor (2.36x)
CEIL2_MS = 54.683               # BN_CENSUS.md §9.1 rebalanced floor (2.40x)
SAVE_BOUND_MS = 75.503          # BN_CENSUS.md §9.1 saving bound
T511_BOARD = (147.9, 137.7)     # RD9_GATE.md:1213-1214 (T~520, T~30)


def grab(lines, pat):
    rx = re.compile(pat)
    for k, ln in enumerate(lines, 1):
        m = rx.search(ln)
        if m:
            return m, k
    raise SystemExit(f"pattern not found: {pat}")


def main():
    log = sys.argv[1]
    lines = open(log).read().splitlines()
    base = os.path.basename(log)
    print(f"=== source log {log}")
    # ---- (1)+(2) the variants ----
    m, k = grab(lines, r"today \(body window sum\): (\d+) cyc")
    today = int(m.group(1))
    print(f"  today (token 4) {today} cyc = {OV.ms(today):.3f} ms  [{base}:{k}]")
    board_tok = 1000.0 / BOARD_MS
    print(f"  board today {BOARD_MS} ms = {board_tok:.3f} tok/s; TB/board "
          f"ratio {BOARD_MS / TB_MS:.5f}")
    print(f"  census ceiling {CEIL_MS} ms = x{TB_MS / CEIL_MS:.3f} -> board "
          f"{board_tok * TB_MS / CEIL_MS:.2f} tok/s; rebalanced {CEIL2_MS} ms "
          f"= x{TB_MS / CEIL2_MS:.3f} -> {board_tok * TB_MS / CEIL2_MS:.2f} "
          f"tok/s")
    rows = {}
    for fk in "AB":
        for tag in ("S0", "S1", "R1", "R2", "R3", "B2"):
            for rb in ("", "+rebal"):
                key = f"{fk}:{tag}{rb}"
                m, k = grab(lines, rf"^  {re.escape(key)}\s+(\d+) cyc")
                rows[key] = (int(m.group(1)), k)
    print("\n  variant       ms(TB)   speedup  board-scaled ms  board tok/s  "
          "saving ms  % of census saving bound  [log line]")
    for key, (c, k) in rows.items():
        t = OV.ms(c)
        sp = OV.ms(today) / t
        bms = t * BOARD_MS / TB_MS
        sav = OV.ms(today) - t
        print(f"  {key:11s} {t:8.3f}  x{sp:.4f}  {bms:10.3f}  "
              f"{1000.0 / bms:10.3f}  {sav:8.3f}  "
              f"{100.0 * sav / SAVE_BOUND_MS:6.1f} %   [{base}:{k}]")
    for fk in "AB":
        s0 = OV.ms(rows[f"{fk}:S0"][0])
        s1 = OV.ms(rows[f"{fk}:S1"][0])
        print(f"  form {fk}: software-only saving {OV.ms(today) - s1:.3f} ms ="
              f" overlap alone {OV.ms(today) - s0:.3f} + MOVX elision on top "
              f"{s0 - s1:.3f}")
        for a, b in (("S1", "R1"), ("R1", "R2"), ("R2", "R3"), ("R2", "B2")):
            print(f"  form {fk}: {a} -> {b}: "
                  f"{OV.ms(rows[f'{fk}:{a}'][0]) - OV.ms(rows[f'{fk}:{b}'][0]):+.3f} ms")
        for tag in ("S1", "R2", "R3"):
            d = OV.ms(rows[f"{fk}:{tag}"][0]) - OV.ms(rows[f"{fk}:{tag}+rebal"][0])
            print(f"  form {fk}: rebalancing on {tag}: {d:+.3f} ms")

    # floors
    m, k = grab(lines, r"ONE-LANE FLOOR: .* (\d+) cyc = ([\d.]+) ms \(x[\d.]+\); "
                       r"with redundant-MOVX elision (\d+) cyc")
    print(f"\n  one-lane floor {m.group(2)} ms -> board-scaled "
          f"{float(m.group(2)) * BOARD_MS / TB_MS:.3f} ms "
          f"({1000.0 / (float(m.group(2)) * BOARD_MS / TB_MS):.3f} tok/s) "
          f"[{base}:{k}]")
    e = OV.ms(int(m.group(3)))
    print(f"  one-lane floor with elision {e:.3f} ms -> board-scaled "
          f"{e * BOARD_MS / TB_MS:.3f} ms ({1000.0 / (e * BOARD_MS / TB_MS):.3f}"
          f" tok/s)")
    m, k = grab(lines, r"dependency critical path .*: (\d+) cyc = ([\d.]+) ms")
    cp = float(m.group(2))
    print(f"  dependency critical path {cp} ms -> board-scaled "
          f"{cp * BOARD_MS / TB_MS:.3f} ms ({1000.0 / (cp * BOARD_MS / TB_MS):.3f}"
          f" tok/s); x{OV.ms(today) / cp:.4f}; fraction of the census saving "
          f"bound it allows {100.0 * (OV.ms(today) - cp) / SAVE_BOUND_MS:.1f} % "
          f"[{base}:{k}]")

    # ---- (3) recovered stream time by class, form B, R2 and S1 ----
    for fk in "AB":
        m, k0 = grab(lines, rf"=== D2 sensitivity, form {fk}:")
        hdr = lines[k0].split()
        cols = hdr[2:]                       # today S0 S1 R1 R2 R3 B2
        rec = {}
        for ln in lines[k0 + 1:k0 + 18]:
            p = ln.split()
            if len(p) < 3 or p[0] == "ALL":
                continue
            vals = dict(zip(cols, map(float, p[2:])))
            rec[(p[0], p[1])] = vals
        for tag in ("S1", "R2"):
            ranked = sorted(rec.items(),
                            key=lambda kv: -(kv[1]["today"] - kv[1][tag]))
            tot = sum(v["today"] - v[tag] for _, v in rec.items())
            print(f"\n  form {fk}, {tag}: recovered stream wait by class "
                  f"(today FENCE window - {tag} exposure), total {tot:.3f} ms "
                  f"[{base}:{k0 + 1}-{k0 + 18}]")
            for (lt, cl), v in ranked:
                d = v["today"] - v[tag]
                if d > 0.0005:
                    print(f"    {lt:4s} {cl:9s} {d:7.3f} ms  "
                          f"({100.0 * d / tot:5.1f} %)")
            grp = collections.Counter()
            for (lt, cl), v in rec.items():
                fam = ("MLP" if cl.startswith("mlp") else
                       "HEAD" if lt == "HEAD" else
                       "attn/DN projections")
                grp[fam] += v["today"] - v[tag]
            print("    by family: " + ", ".join(
                f"{f} {x:.3f} ms ({100.0 * x / tot:.1f} %)"
                for f, x in grp.most_common()))

    # ---- T -> 511, board-scaled ----
    print()
    for fk in "AB":
        for tag in ("S1", "R2"):
            m, k = grab(lines, rf"T~511 {fk}:{tag}: today (\d+) cyc .*; "
                               rf"(\d+) cyc =")
            t0, t1 = OV.ms(int(m.group(1))), OV.ms(int(m.group(2)))
            print(f"  T~511 {fk}:{tag}: today {t0:.3f} -> {t1:.3f} ms TB; "
                  f"board-scaled {t0 * BOARD_MS / TB_MS:.3f} -> "
                  f"{t1 * BOARD_MS / TB_MS:.3f} ms = "
                  f"{1000.0 / (t0 * BOARD_MS / TB_MS):.3f} -> "
                  f"{1000.0 / (t1 * BOARD_MS / TB_MS):.3f} tok/s  "
                  f"[{base}:{k}]")
    print(f"  RD9 board at T~520: {T511_BOARD[0]} ms = "
          f"{1000.0 / T511_BOARD[0]:.3f} tok/s; growth "
          f"{T511_BOARD[0] - T511_BOARD[1]:.1f} ms (RD9_GATE.md:1213-1214)")
    for fk in "AB":
        m, k = grab(lines, rf"T~511 {fk}:R2: today \d+ cyc .*; (\d+) cyc =")
        r2_511 = OV.ms(int(m.group(1)))
        r2 = OV.ms(rows[f"{fk}:R2"][0])
        m2, k2 = grab(lines, r"T -> 511 sensitivity: \+(\d+) cyc")
        g = OV.ms(int(m2.group(1)))
        print(f"  form {fk}: R2 grows {r2_511 - r2:.3f} ms for {g:.3f} ms of "
              f"added ATTN work -> {100.0 * (r2_511 - r2) / g:.1f} % of the "
              f"growth lands on the token")

    # ---- (3b) the sums the memo quotes from n06's tables ----
    m, k0 = grab(lines, r"=== D1 table, form B:")
    d1 = {}
    for ln in lines[k0 + 1:k0 + 18]:
        p = ln.split()
        if len(p) >= 9 and p[0] in ("DN", "GQA", "HEAD"):
            d1[(p[0], p[1])] = [float(x) for x in p[3:9]]
    # columns: S_max_sum FENCEwin after pull hoist hideable
    far = [k_ for k_, v in d1.items() if abs(v[2] - v[0]) < 1e-9]
    print(f"\n  D1 form B: classes whose 'after' equals their stream: "
          f"{sorted(far)}; stream sum {sum(d1[k_][0] for k_ in far):.3f} ms "
          f"[{base}:{k0 + 1}-{k0 + 18}]")
    chain = [k_ for k_ in d1 if k_[1] in ("in_qkv", "mlp_gate", "mlp_up",
                                          "mlp_down", "lm_head")]
    tot_s = sum(v[0] for v in d1.values())
    print(f"  D1 form B: in_qkv + all MLP + lm_head stream sum "
          f"{sum(d1[k_][0] for k_ in chain):.3f} ms of {tot_s:.3f} ms")
    for tag in ("S1", "R2", "R3"):
        a_ = OV.ms(rows[f"A:{tag}"][0])
        b_ = OV.ms(rows[f"B:{tag}"][0])
        print(f"  form A - form B at {tag}: {a_ - b_:.3f} ms")
    for t in (5, 6):
        for fk in "AB":
            for tag in ("S1", "R2"):
                m, k = grab(lines, rf"token {t}: today \d+ cyc = [\d.]+ ms; "
                                   rf"{fk}:{tag} \d+ cyc = ([\d.]+) ms")
                print(f"  token {t} {fk}:{tag} minus token 4: "
                      f"{float(m.group(1)) - OV.ms(rows[f'{fk}:{tag}'][0]):+.3f}"
                      f" ms  [{base}:{k}]")
    print(f"  XWIN second half starts at word {3072 // 2} of 3072 "
          f"(rtl/seq_movers.sv XWIN_WORDS)")
    print(f"  12648 cyc hoist / 4216-cyc MOVX window = {12648 / 4216:.3f}")

    # ---- (4) buffer sizing, from the RTL array shapes ----
    xmem_bits = 32 * 96 * 32          # rtl/matvec_engine.sv:219 x_mem[32][MAX_NG=96] x 32b
    res_bits = 4096 * 32              # rtl/matvec_chan.sv:450-456 MEMORY_SIZE(4096*32)
    print(f"\n  x_mem per channel {xmem_bits} bits = {xmem_bits // 8} B; a "
          f"K=4096 vector uses 32 of 96 lines ({100.0 * 32 / 96:.1f} %), so two "
          f"K<=6144 vectors (48 lines each) fit the EXISTING array")
    print(f"  RES per channel {res_bits} bits = {res_bits // 8} B = "
          f"{res_bits / 36864:.2f} BRAM36-equivalents; a 2048-row chunk uses "
          f"{100.0 * 2048 / 4096:.0f} %, so two chunks fit the EXISTING array")
    print(f"  a full second x_mem for K=12288 (mlp_down) would cost {xmem_bits}"
          f" bits more per channel, {4 * xmem_bits} bits over four")

    # ---- (5) the in_qkv / q_proj row-sub-chunk option (deliverable 3) ----
    recs, _man = OV.load_stream()
    lo, hi = OV.body_range(recs)
    rows_csv = OV.load_csv(toks=(4,))
    nodes = OV.build_nodes(recs, lo, hi, rows_csv[4])
    groups, _ = OV.stream_durations(nodes, rows_csv[4])
    mvs, _lt = OV.segment_matvecs(nodes, groups)
    per = collections.defaultdict(list)
    for k_, mv in enumerate(mvs):
        if mv["cls"] not in ("in_qkv", "q_proj"):
            continue
        g = groups[mv["groups"][0]]
        S = max(nodes[m_].S for m_ in g["mvgos"])
        f = g["fence"]
        # the lane work that consumes it: from the FENCE to the MOVX of the
        # layer's output projection (dn_out / o_proj), i.e. conv + scale +
        # gate + the head loop (DN) or the q/k head loop + attention (GQA)
        nxt = next(mm for mm in mvs[k_ + 1:]
                   if mm["cls"] in ("dn_out", "o_proj"))
        end = nxt["movx"][0]
        lane = sum(nodes[j].dur for j in range(f + 1, end)
                   if nodes[j].kind not in ("fence", "arg", "mvgo"))
        per[mv["cls"]].append((S, lane))
    hid4 = {}
    for cls, v in per.items():
        hid4[cls] = OV.ms(sum(x for x, _ in v)) * 0.75
        S = sum(x for x, _ in v)
        L = sum(y for _, y in v)
        print(f"\n  {cls}: {len(v)} layers; stream (max chan) {OV.ms(S):.3f} "
              f"ms/token; lane work from its FENCE to the output projection "
              f"{OV.ms(L):.3f} ms/token; per layer {OV.ms(S) / len(v):.4f} vs "
              f"{OV.ms(L) / len(v):.4f} ms")
        for ksub in (2, 4, 8):
            hid = OV.ms(S) * (1.0 - 1.0 / ksub)
            print(f"    split into {ksub} row sub-chunks: at most "
                  f"{hid:.3f} ms/token of the stream hides behind the lane "
                  f"work of earlier sub-chunks (lane work available "
                  f"{OV.ms(L):.3f} >= {hid:.3f}: "
                  f"{'yes' if OV.ms(L) >= hid else 'NO'})")
    print(f"\n  in_qkv + q_proj, k = 4: at most "
          f"{hid4.get('in_qkv', 0) + hid4.get('q_proj', 0):.3f} ms/token "
          f"together")

    # ---- (6) fix round 1: the finer-grain ceiling and the crude bounds ----
    hid = hid4.get("in_qkv", 0) + hid4.get("q_proj", 0)
    cp2 = cp - hid
    print(f"\n  FIX1 critical path if the k=4 sub-chunk hiding came entirely "
          f"off it (both streams are on it): {cp:.3f} - {hid:.3f} = "
          f"{cp2:.3f} ms TB = x{OV.ms(today) / cp2:.4f}; board-scaled "
          f"{1000.0 / (cp2 * BOARD_MS / TB_MS):.3f} tok/s")
    sdma = 5.125                    # BN_CENSUS.md:831 (board SDMA_CYC)
    for fk in "AB":
        sav = OV.ms(today) - OV.ms(rows[f"{fk}:S1"][0])
        print(f"  FIX1 form {fk}: board state-DMA time {sdma} ms/token = "
              f"{100.0 * sdma / sav:.1f} % of S1's {sav:.3f} ms saving "
              f"(if all of it stalled channel 3's stream)")
    for fk in "AB":
        sav = OV.ms(today) - OV.ms(rows[f"{fk}:S1"][0])
        savb = sav * BOARD_MS / TB_MS
        print(f"  FIX2 form {fk} like-for-like (board scale): {sdma} ms / "
              f"({sav:.3f} x {BOARD_MS / TB_MS:.5f} = {savb:.3f} ms) = "
              f"{100.0 * sdma / savb:.1f} %")
    import math
    bits = 3072 * 32
    print(f"  FIX2 R3 staging buffer 3072 x 32 b = {bits} b = {bits // 8} B "
          f"= {bits / 36864:.2f} BRAM36 of 36,864 b -> "
          f"{math.ceil(bits / 36864)} BRAM36")
    polls = 343 * 44
    print(f"  FIX1 fence polls: 343 x 44 cyc = {polls} cyc = "
          f"{OV.ms(polls):.3f} ms/token")


if __name__ == "__main__":
    main()
