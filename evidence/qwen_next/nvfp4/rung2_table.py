#!/usr/bin/env python3
"""rung2_table.py — Task NV1 rung 2: the Qwen3.5-9B decision table.

Reads the committed n## jsons of rung 2 (every 9B row, CPU, shipped venv) and
the rung-1 2B jsons it contrasts them with, ASSERTS that each model's rows
share one scoring setup, and prints every number `docs/NVFP4_STUDY.md` quotes,
each with the `path:line` of the json field it came from.  Nothing is scored
here; the arithmetic is subtraction, ratios and the rung-1 cost model.
Runs on snoke through `nvfp4_run.sh` (no numeric work on darthplagueis):

    evidence/qwen_next/nvfp4/nvfp4_run.sh n##_rung2_table.log \
        /home/cah/.venv/bin/python evidence/qwen_next/nvfp4/rung2_table.py

LINE-STABLE BY DESIGN: row n54 (W4 g64 GPTQ + A8) may land after the other
rows.  Every section prints the same number of lines whether its json exists
or not (an ABSENT line stands in), so a re-run after n54 lands moves no other
line and the document's citations survive a re-point to the new log.

Cost model (D) — rung 1's, reused through `rung1_table.bytes_9b`: the shipped
9B token streams weights for 54.408 ms of a 131.138 ms testbench token
(`evidence/qwen9b/bn/BN_CENSUS.md:41`, :18) and takes 137.121 ms on the board
(:19).  A weight format that scales every image's busiest-channel bytes by r
adds 54.408 * (r - 1) ms to the token, all else equal.  Activation formats
move no DDR bytes (activations live on chip), so they are free in this model;
their hardware is priced in the HW section, not in ms.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rung1_table as R1                                         # noqa: E402

NV = R1.NV
W = R1.W
BPT = R1.BPT
ROOT = R1.ROOT
D = R1.D
cite = R1.cite
load = R1.load

# key, label, json, hardware-delta class.  9B rows in the order of Panel A.
HW_NONE = "none (the shipped engine as built)"
HW_G64 = "W4 g64 row format: a mode DELETED at G3.3, restored"
HW_NVW = "new weight datapath (E2M1 + block-16 UE4M3)"
HW_NVW_ROT = "new weight datapath + activation rotation (butterfly ahead of A8)"
HW_NVW_NVA = "new weight + new activation datapath (no rotation)"
HW_REF = "n/a (float reference)"
ROWS9 = [
    ("bf16", "bf16 anchor", f"{D}/n46_ppl_9b_bf16_cpu.json", HW_REF),
    ("SHIP", "W4 g128 + A8 (THE SHIPPED POINT)",
     f"{D}/n47_ppl_9b_w4g128_a8_cpu.json", HW_NONE),
    ("GPTQ", "W4 g64 GPTQ + A8", f"{D}/n54_ppl_9b_w4g64gptq_a8_cpu.json",
     HW_G64),
    ("NV_A8", "NVFP4 + A8", f"{D}/n53_ppl_9b_nvfp4_a8_cpu.json", HW_NVW),
    ("NVH_A8", "NVFP4 + RHT + A8 (seed 0)",
     f"{D}/n52_ppl_9b_nvfp4h_a8_seed0_cpu.json", HW_NVW_ROT),
    ("NVH_A8_S1", "NVFP4 + RHT + A8 (seed 1)",
     f"{D}/n59_ppl_9b_nvfp4h_a8_seed1_cpu.json", HW_NVW_ROT),
    ("NV_DYN", "full NVFP4, dynamic act scale",
     f"{D}/n51_ppl_9b_nvfp4_actdyn_cpu.json", HW_NVW_NVA),
    ("NV", "NVFP4, weights only", f"{D}/n55_ppl_9b_nvfp4_cpu.json", HW_REF),
    ("NVH", "NVFP4 + RHT, weights only (seed 0)",
     f"{D}/n56_ppl_9b_nvfp4h_seed0_cpu.json", HW_REF),
    ("A8", "bf16 weights + A8", f"{D}/n57_ppl_9b_bf16_a8_cpu.json", HW_REF),
    ("ADYN", "bf16 weights + NVFP4 act (dyn)",
     f"{D}/n58_ppl_9b_bf16_actnvfp4dyn_cpu.json", HW_REF),
]
OPTIONAL = {"GPTQ"}
QUEUE = f"{D}/n48_rung2_queue.log"
# the 2B counterparts (rung 1, committed) of the keys the contrast uses
ROWS2 = {
    "bf16": "evidence/qwen2b/q1/ppl_2b_bf16_snoke.json",
    "SHIP": f"{D}/n11_ppl_2b_w4g128_a8.json",
    "GPTQ": f"{D}/n13_ppl_2b_w4g64gptq_a8.json",
    "NV_A8": f"{D}/n16_ppl_2b_nvfp4_a8.json",
    "NVH_A8": f"{D}/n28_ppl_2b_nvfp4h_hd_a8.json",
    "NV_DYN": f"{D}/n18_ppl_2b_nvfp4_actdyn.json",
    "NV": f"{D}/n14_ppl_2b_nvfp4.json",
    "NVH": f"{D}/n27_ppl_2b_nvfp4h_hd.json",
    "A8": f"{D}/n21_ppl_2b_bf16_a8.json",
    "ADYN": f"{D}/n22_ppl_2b_bf16_actnvfp4dyn.json",
}
DEPLOYABLE = ("SHIP", "GPTQ", "NV_A8", "NVH_A8", "NVH_A8_S1", "NV_DYN")
STREAM_MS, BOARD_MS = R1.STREAM_MS, R1.BOARD_MS


def queue_line(tag, word):
    """(line number, text) of the queue log's `<word> <tag>` event."""
    with open(os.path.join(ROOT, QUEUE)) as f:
        for i, line in enumerate(f, 1):
            parts = line.split()
            if len(parts) > 2 and parts[1] == word and parts[2] == tag:
                return i, line.rstrip("\n")
    return None, None


def main():
    for line, needle in ((41, "54.408"), (18, "131.138"), (19, "137.121")):
        R1.check_text(R1.BN, line, needle)
    recs = {}
    for key, label, path, hw in ROWS9:
        if key in OPTIONAL and not os.path.exists(os.path.join(ROOT, path)):
            recs[key] = (label, path, None, hw)
            continue
        recs[key] = (label, path, load(path), hw)
    have = [k for k in recs if recs[k][2] is not None]
    a = recs["bf16"][2]
    for key in have:
        r = recs[key][2]
        for f in ("corpus_sha256", "n_positions", "checkpoint_header_sha256",
                  "window", "batch", "model_tag", "host", "threads"):
            assert r[f] == a[f], (key, f, r[f], a[f])
        assert r["model_tag"] == "9b" and r["device"] == "cpu", key
        assert r["model_dtype"] == "float32", key
        rot = R1.weight_format(r) == "nvfp4h"
        assert (r.get("rht_form") == NV.RHT_FORM) == rot, key
    assert recs["NVH_A8"][2]["rht_seed"] == 0
    assert recs["NVH_A8_S1"][2]["rht_seed"] == 1
    assert recs["NVH"][2]["rht_seed"] == 0
    print(f"PROVENANCE 9B: {len(have)} rows share corpus "
          f"{a['corpus_sha256'][:16]}…, checkpoint "
          f"{a['checkpoint_header_sha256'][:16]}…, window {a['window']}, batch "
          f"{a['batch']}, {a['n_positions']} positions, host {a['host']}, "
          f"device cpu float32, threads {a['threads']}, model {a['model_tag']}")
    absent = [k for k in recs if recs[k][2] is None]
    ln, txt = queue_line("n54", "END")
    kl, ktxt = queue_line("n54", "KILLED")
    sl, stxt = queue_line("n54", "START")
    print(f"n54 (GPTQ) json: {'PRESENT' if 'GPTQ' not in absent else 'ABSENT'}"
          f" | queue START {QUEUE}:{sl} | END "
          f"{f'{QUEUE}:{ln}' if ln else 'none'} | KILLED "
          f"{f'{QUEUE}:{kl}' if kl else 'none'}")
    print(f"  queue n54 events: START={stxt!r} END={txt!r} KILLED={ktxt!r}")

    p0 = a["ppl"]
    ship = recs["SHIP"][2]["ppl"]
    gap = ship - p0

    def ppl(k):
        return recs[k][2]["ppl"]

    def dd(k):
        return ppl(k) - p0

    # ---------------------------------------------------------------- cost
    b9 = {f: R1.bytes_9b(f) for f in ("w4g128", "w4g64gptq", "nvfp4")}
    c9_ship = b9["w4g128"][1]

    def f9(r):
        fmt = R1.weight_format(r)
        if fmt is None:
            return None
        return "nvfp4" if fmt in ("nvfp4", "nvfp4h") else fmt

    def cost(k):
        """(b/w, bytes/token, busiest-channel ratio, d ms, ms, tok/s, d tok/s)"""
        r = recs[k][2]
        nw = sum(r["classes"][c]["n_weights"] for c in BPT.W4_CLASSES)
        bpt = R1.matvec_bytes(r)
        fm = f9(r)
        if fm is None:
            return 8 * bpt / nw, bpt, None, None, None, None, None
        assert bpt == b9[fm][0], (k, bpt, b9[fm][0])
        rb = b9[fm][1] / c9_ship
        dms = STREAM_MS * (rb - 1.0)
        ms = BOARD_MS + dms
        return (8 * bpt / nw, bpt, rb, dms, ms, 1e3 / ms,
                1e3 / ms - 1e3 / BOARD_MS)

    print("\nPANEL A — 9B quality (PPL = the json's ppl field) beside the "
          "modelled 9B throughput")
    print("key | row | PPL | dPPL vs bf16 | d% | % of shipped gap left | "
          "d PPL vs shipped | 9B tok/s (D) | d tok/s vs shipped | cite")
    for key, (label, path, r, hw) in recs.items():
        if r is None:
            busy = b9["w4g64gptq"][1] / c9_ship
            ms_ = BOARD_MS + STREAM_MS * (busy - 1.0)
            dts = 1e3 / ms_ - 1e3 / BOARD_MS
            print(f"{key} | {label} | ABSENT (json not written) | — | — | — "
                  f"| — | {1e3 / ms_:.3f} (modelled) | {dts:+.3f} "
                  f"({100 * dts * BOARD_MS / 1e3:+.2f}%) | {path}")
            continue
        d_ = r["ppl"] - p0
        c = cost(key)
        ts = (f"{c[5]:.3f} | {c[6]:+.3f} ({100 * c[6] * BOARD_MS / 1e3:+.2f}%)"
              if c[5] is not None else "n/a | n/a")
        print(f"{key} | {label} | {r['ppl']:.6f} | {d_:+.6f} | "
              f"{100 * d_ / p0:+.2f}% | {100 * d_ / gap:.2f}% | "
              f"{r['ppl'] - ship:+.6f} | {ts} | {cite(path, 'ppl')}")
    ranked = sorted((ppl(k), k) for k in have)
    print("  RANKING 9B (best first): " + " < ".join(
        f"{k} {p:.6f}" for p, k in ranked))
    dep = sorted((ppl(k), k) for k in have if k in DEPLOYABLE)
    print("  RANKING 9B deployable rows: " + " < ".join(
        f"{k} {p:.6f}" for p, k in dep))

    print("\nPANEL B — 9B cost (bytes = the json's bytes_per_token_matvec; "
          "ms/tok/s = the BN streaming model, D)")
    print(f"  cross-check: n47 bytes_per_token_matvec == bytes_per_token.py 9B "
          f"all:w4g128 == {b9['w4g128'][0]:,} "
          f"({cite(recs['SHIP'][1], 'bytes_per_token_matvec')}); every NVFP4 "
          f"row == rung1_table.bytes_9b('nvfp4') == {b9['nvfp4'][0]:,}")
    dms_of = {fm: STREAM_MS * (b9[fm][1] / c9_ship - 1.0) for fm in b9}
    for fm in ("w4g128", "w4g64gptq", "nvfp4"):
        tot, busy, ratios = b9[fm]
        extra = (f"; d ms {dms_of[fm]:+.3f} = {dms_of[fm] / dms_of['nvfp4']:.3f}"
                 f" of NVFP4's {dms_of['nvfp4']:+.3f}, extra "
                 f"{(tot - b9['w4g128'][0]) / 1e6:+.3f} MB/token"
                 if fm == "w4g64gptq" else "")
        print(f"  9B {fm:<9s}: {tot:,} B/token, busiest channel {busy:,} B, "
              f"x{busy / c9_ship:.6f}, per-image stride ratios "
              f"{sorted(round(x, 6) for x in ratios)}{extra}")
    print("key | packed b/w (matvec) | bytes/token 9B | x shipped bytes | "
          "busiest-channel ratio | d ms/token (D) | ms/token (D) | tok/s (D) "
          "| hardware delta | cite")
    for key, (label, path, r, hw) in recs.items():
        if r is None:
            fm = "w4g64gptq"
            tot, busy, _ = b9[fm]
            rb = busy / c9_ship
            dms = STREAM_MS * (rb - 1.0)
            print(f"{key} | (json ABSENT; modelled from bytes_per_token.py) "
                  f"4.2500 | {tot:,} | {tot / b9['w4g128'][0]:.4f} | "
                  f"{rb:.6f} | {dms:+.3f} | {BOARD_MS + dms:.3f} | "
                  f"{1e3 / (BOARD_MS + dms):.3f} | {hw} | {path}")
            continue
        c = cost(key)
        xs = c[1] / recs["SHIP"][2]["bytes_per_token_matvec"]
        if c[2] is None:
            print(f"{key} | {c[0]:.4f} | {c[1]:,.0f} | {xs:.4f} | n/a | n/a | "
                  f"n/a | n/a | {hw} | "
                  f"{cite(path, 'bytes_per_token_matvec')}")
            continue
        print(f"{key} | {c[0]:.4f} | {c[1]:,.0f} | {xs:.4f} | {c[2]:.6f} | "
              f"{c[3]:+.3f} | {c[4]:.3f} | {c[5]:.3f} | {hw} | "
              f"{cite(path, 'bytes_per_token_matvec')}")

    # ------------------------------------------------------------ frontier
    print("\nFRONTIER — deployable rows vs the shipped point (recovered = "
          "shipped PPL - row PPL)")
    print("key | PPL | recovered PPL | % of shipped gap closed | extra MB/token"
          " | extra ms/token | ms per PPL point recovered | % tok/s lost per "
          "10 pts of gap closed")
    for key in DEPLOYABLE:
        label, path, r, hw = recs[key]
        if r is None:
            print(f"{key} | ABSENT | — | — | — | — | — | —")
            continue
        c = cost(key)
        rec = ship - r["ppl"]
        xmb = (c[1] - recs["SHIP"][2]["bytes_per_token_matvec"]) / 1e6
        if key == "SHIP":
            print(f"{key} | {r['ppl']:.6f} | 0 | 0.00% | 0.000 | +0.000 | — | —")
            continue
        lost = -100 * c[6] * BOARD_MS / 1e3
        print(f"{key} | {r['ppl']:.6f} | {rec:+.6f} | {100 * rec / gap:.2f}% "
              f"| {xmb:+.3f} | {c[3]:+.3f} | {c[3] / rec:.3f} | "
              f"{lost / (10 * rec / gap):.3f}")

    # -------------------------------------------------------- decomposition
    print("\nDECOMPOSITION 9B (dPPL vs bf16; interaction = combined - weight "
          "- act)")
    for name, wk, ak, ck in (("NVFP4 x A8", "NV", "A8", "NV_A8"),
                             ("NVFP4 x NVFP4-act(dyn)", "NV", "ADYN",
                              "NV_DYN")):
        print(f"  {name}: weight {dd(wk):+.6f}, act {dd(ak):+.6f}, combined "
              f"{dd(ck):+.6f}, interaction {dd(ck) - dd(wk) - dd(ak):+.6f}")
    print(f"  W4 g128 x A8 (shipped): combined {dd('SHIP'):+.6f}, act "
          f"{dd('A8'):+.6f}, weight+interaction {dd('SHIP') - dd('A8'):+.6f} "
          f"(no 9B weight-only W4 g128 row: the two are not separable)")
    print(f"  NVFP4+RHT x A8 (rotated): weight {dd('NVH'):+.6f}, combined s0 "
          f"{dd('NVH_A8'):+.6f}, s1 {dd('NVH_A8_S1'):+.6f}; act+interaction "
          f"s0 {dd('NVH_A8') - dd('NVH'):+.6f} (bf16 + ROTATED A8 not run: "
          f"not separable)")

    def dp(k1, k0):
        return ppl(k1) - ppl(k0)
    print("  RHT effect (RHT row - no-RHT row, same activations):")
    print(f"    weights only (seed 0): {dp('NVH', 'NV'):+.6f}")
    print(f"    + A8: seed 0 {dp('NVH_A8', 'NV_A8'):+.6f}, seed 1 "
          f"{dp('NVH_A8_S1', 'NV_A8'):+.6f}, mean "
          f"{(dp('NVH_A8', 'NV_A8') + dp('NVH_A8_S1', 'NV_A8')) / 2:+.6f}")
    print("    + NVFP4 act dyn: NOT RUN at 9B (no nvfp4h + nvfp4h:dyn row)")
    print(f"  activation formats on bf16 weights: NVFP4-dyn - A8 = "
          f"{dp('ADYN', 'A8'):+.6f}; full NVFP4 - bf16+A8 = "
          f"{dp('NV_DYN', 'A8'):+.6f}; full NVFP4 - NVFP4+A8 = "
          f"{dp('NV_DYN', 'NV_A8'):+.6f}")

    # ------------------------------------------------------------ 2B vs 9B
    r2 = {k: (p, load(p)) for k, p in ROWS2.items()}
    a2 = r2["bf16"][1]
    for k, (p, r) in r2.items():
        for f in ("corpus_sha256", "n_positions", "window", "batch",
                  "model_tag", "host"):
            assert r[f] == a2[f], (k, f)
    q2 = r2["bf16"][1]["ppl"]
    gap2 = r2["SHIP"][1]["ppl"] - q2

    def d2(k):
        return r2[k][1]["ppl"] - q2

    print("\n2B vs 9B (2B = rung 1's committed jsons; same corpus, window, "
          "batch, host)")
    print("quantity | 2B | 9B | agree? | 2B cites")
    rows = [
        ("act damage A8 (bf16 wts)", d2("A8"), dd("A8"), ("A8",)),
        ("act damage NVFP4 dyn (bf16 wts)", d2("ADYN"), dd("ADYN"),
         ("ADYN",)),
        ("NVFP4-dyn act - A8 act", d2("ADYN") - d2("A8"),
         dd("ADYN") - dd("A8"), ("ADYN", "A8")),
        ("RHT effect, weights only", d2("NVH") - d2("NV"),
         dd("NVH") - dd("NV"), ("NVH", "NV")),
        ("RHT effect, + A8 (seed 0)", d2("NVH_A8") - d2("NV_A8"),
         dd("NVH_A8") - dd("NV_A8"), ("NVH_A8", "NV_A8")),
        ("full NVFP4 - bf16+A8", d2("NV_DYN") - d2("A8"),
         dd("NV_DYN") - dd("A8"), ("NV_DYN", "A8")),
        ("full NVFP4 - NVFP4+A8", d2("NV_DYN") - d2("NV_A8"),
         dd("NV_DYN") - dd("NV_A8"), ("NV_DYN", "NV_A8")),
        ("NVFP4 weight damage / shipped gap", d2("NV") / gap2,
         dd("NV") / gap, ("NV", "SHIP")),
    ]
    for name, v2, v9, ks in rows:
        agree = "yes" if (v2 > 0) == (v9 > 0) else "NO (sign flips)"
        print(f"{name} | {v2:+.6f} | {v9:+.6f} | {agree} | "
              f"{', '.join(cite(r2[k][0], 'ppl') for k in ks)}")
    print(f"  shipped gap: 2B {gap2:+.6f} ({100 * gap2 / q2:+.2f}%), 9B "
          f"{gap:+.6f} ({100 * gap / p0:+.2f}%)")
    common = [k for k in ROWS2 if k in have and k != "bf16"]
    rk2 = [k for _p, k in sorted((r2[k][1]["ppl"], k) for k in common)]
    rk9 = [k for _p, k in sorted((ppl(k), k) for k in common)]
    print("  2B order of the common rows: " + " < ".join(rk2))
    print("  9B order of the common rows: " + " < ".join(rk9))
    print(f"  best deployable, 2B: {min((r2[k][1]['ppl'], k) for k in DEPLOYABLE if k in r2)[1]}"
          f" | 9B: {dep[0][1]}")

    # --------------------------------------------------------------- seeds
    s0, s1 = ppl("NVH_A8"), ppl("NVH_A8_S1")
    print("\nRHT SEED SENSITIVITY 9B (NVFP4 + RHT + A8)")
    print(f"  seed 0 {s0:.6f} ({cite(recs['NVH_A8'][1], 'ppl')}, "
          f"{cite(recs['NVH_A8'][1], 'rht_seed')})")
    print(f"  seed 1 {s1:.6f} ({cite(recs['NVH_A8_S1'][1], 'ppl')}, "
          f"{cite(recs['NVH_A8_S1'][1], 'rht_seed')})")
    sp = abs(s1 - s0)
    print(f"  mean {(s0 + s1) / 2:.6f}, spread {sp:.6f} PPL = "
          f"{100 * sp / gap:.2f}% of the 9B shipped gap; worst seed vs "
          f"NVFP4+A8 (no RHT) {max(s0, s1) - ppl('NV_A8'):+.6f}, vs full "
          f"NVFP4 {max(s0, s1) - ppl('NV_DYN'):+.6f}")
    sp2 = {}
    for name, keys in R1.SEED_SETS.items():
        r1p = {k_: p_ for k_, _l, p_ in R1.ROWS}
        vals = [load(p_ if p_ else r1p[k_])["ppl"] for _s, k_, p_ in keys]
        sp2[name] = 100 * (max(vals) - min(vals)) / gap2
    sp9 = 100 * sp / gap
    print(f"  the RHT's +A8 benefit is {abs(dp('NVH_A8', 'NV_A8')) / sp:.1f}x "
          f"the seed spread; the rotated-weights-only cost "
          f"{dp('NVH', 'NV'):+.6f} is {abs(dp('NVH', 'NV')) / sp:.1f}x it; "
          f"2B seed spreads (3 seeds, % of the 2B gap): " + ", ".join(
              f"{n} {v:.2f}% = {v / sp9:.1f}x the 9B's" for n, v in sp2.items()))

    # ------------------------------------------------------------ wall time
    print("\nWALL TIMES 9B (json seconds_build + seconds_eval; queue wall)")
    for key, (label, path, r, hw) in recs.items():
        tag = os.path.basename(path)[:3]
        ql, qt = queue_line(tag, "END")
        if r is None:
            print(f"  {key} {tag}: ABSENT | queue END "
                  f"{f'{QUEUE}:{ql}' if ql else 'none'}")
            continue
        wall = r['seconds_build'] + r['seconds_eval']
        vs7 = (f" | the brief's 7 h estimate / this = {7 * 3600 / wall:.1f}x"
               if key == "bf16" else "")
        print(f"  {key} {tag}: build {r['seconds_build']:.0f} s + eval "
              f"{r['seconds_eval']:.0f} s = {wall / 60:.1f} min "
              f"({cite(path, 'seconds_build')}) | queue END "
              f"{f'{QUEUE}:{ql}' if ql else 'n/a (launched by the cpu pair)'}"
              f"{vs7}")

    # ------------------------------------------------------ hooked sites
    rs = recs["NVH_A8"][2]
    hb = rs["act_resolved"]["hooked_by_class"]
    print(f"\nHOOKED SITES 9B: {sum(v['modules'] for v in hb.values())} "
          f"matvecs on {sum(v['sites'] for v in hb.values())} input sites; "
          + ", ".join(f"{c} {v['modules']}/{v['sites']}"
                      for c, v in sorted(hb.items()))
          + f"; rht_n_sites {rs['rht_n_sites']} "
          f"({cite(recs['NVH_A8'][1], 'rht_n_sites')})")

    # ------------------------------------------------------ HW pricing (D)
    print("\nHW PRICING (D, arithmetic only; nothing built)")
    ks = sorted({im["k"] for im in BPT.inventory(BPT.load_cfg("9b"))})
    print(f"  9B matvec K values: {ks}")
    for k in ks:
        swb, ssb = W.row_beats(k, 128)
        nwb, nsb = NV.row_beats(k)
        print(f"  K={k}: shipped {swb} weight + {ssb} scale beats, retire "
              f"{k // 128} group entries/row | NVFP4 {nwb} weight + {nsb} "
              f"scale beats, {k // 16} block entries/row = "
              f"{(k // 16) / (nwb + nsb):.2f} per streamed beat (the shipped "
              f"retire issues 1 per cycle); scale bits/row {(k // 128) * 16}"
              f" -> {(k // 16) * 8} (x{(k // 16) * 8 / ((k // 128) * 16):.2f})")

    def sbits(v):
        return int(v).bit_length() + 1
    q2max = int(2 * NV.E2M1_MAX)             # 12: E2M1 in half units
    x8max = 128                              # the RTL's |x8| bound
    mu_max = 15                              # UE4M3 value = mu * 2^k
    kspan = 14                               # k = e-10 (e>=1), -9 (e=0)
    kmax = max(ks)
    for name, pmax, mus, span in (
            ("shipped W4 x A8 (per 128-group, uint16 m)", 8 * x8max, None,
             None),
            ("NVFP4 weight x A8", q2max * x8max, mu_max, kspan),
            ("NVFP4 weight x NVFP4 act", q2max * q2max, mu_max * mu_max,
             2 * kspan)):
        if mus is None:
            g = 128
            acc = g * pmax
            p = (kmax // g) * 65535 * acc
            print(f"  {name}: product {pmax} ({sbits(pmax)} b), group sum "
                  f"{acc} ({sbits(acc)} b), p bound at K={kmax} {p:.3e} "
                  f"({sbits(p)} b; p_acc is 48 b)")
            continue
        blk = 16 * pmax
        term = blk * mus * 2 ** span
        p = (kmax // 16) * term
        print(f"  {name}: product {pmax} ({sbits(pmax)} b), block-16 sum "
              f"{blk} ({sbits(blk)} b), x mantissa <= {mus} "
              f"({sbits(blk * mus)} b), exponent-shift span {span} -> term "
              f"{term:.3e} ({sbits(term)} b), p bound at K={kmax} {p:.3e} "
              f"({sbits(p)} b)")
    print(f"  RHT butterfly: 16-point FWHT = 4 stages x 16 add/sub = 64 per "
          f"16 elements; K=4096 input: {4096 // 16 * 64:,} add/sub per "
          f"rotated vector; int16 in -> +4 b before the /4 shift (|x'| <= "
          f"4 max|x|, orthonormal)")


if __name__ == "__main__":
    main()
