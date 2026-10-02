#!/usr/bin/env python3
"""rung1_table.py — Task NV1 rung 1: the 2B ranking table (Ruling C6).

Reads the committed n##_ jsons of rung 1 and the re-used 2B bf16 anchor,
ASSERTS they share one scoring setup, and prints every number that
`NVFP4_RUNG1.md` quotes, each with the `path:line` of the json field it came
from.  Nothing is scored here; the arithmetic is subtraction and ratios.
Runs on snoke through `nvfp4_run.sh` (no numeric work on darthplagueis).

    evidence/qwen_next/nvfp4/nvfp4_run.sh n##_rung1_table.log \
        /home/cah/.venv/bin/python evidence/qwen_next/nvfp4/rung1_table.py

Cost model (D): the shipped 9B token is bandwidth-bound in its weight path
for 54.408 ms of a 131.138 ms testbench token (`evidence/qwen9b/bn/
BN_CENSUS.md:41`, :18) and 137.121 ms on the board (:19).  A weight format
that scales every image's busiest-channel bytes by r adds 54.408 * (r - 1)
ms to the token, all else equal — the streaming term only; the activation
side of NVFP4 is hardware work that is priced in words, not modelled here.
"""
import json
import os
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "ref"))
sys.path.insert(0, os.path.join(ROOT, "ref", "scripts"))
sys.path.insert(0, os.path.join(ROOT, "sw"))

import nvfp4 as NV                                              # noqa: E402
import w4a8_ref as W                                            # noqa: E402
import bytes_per_token as BPT                                   # noqa: E402

D = "evidence/qwen_next/nvfp4"
ANCHOR = ("bf16", "bf16 anchor (re-used)",
          "evidence/qwen2b/q1/ppl_2b_bf16_snoke.json")
# key, label, json — rung 1 in the brief's order.  RHT = H16 diag(D)/4
# (rht_form present in the json); "plain H" = the inert diag(D) H16 rows run
# before the correction (44a105c), which are a plain block-16 Hadamard.
ROWS = [
    ANCHOR,
    ("SHIP", "W4 g128 + A8 (THE SHIPPED POINT)",
     f"{D}/n11_ppl_2b_w4g128_a8.json"),
    ("W4", "W4 g128, weights only", f"{D}/n12_ppl_2b_w4g128.json"),
    ("GPTQ", "W4 g64 GPTQ + A8", f"{D}/n13_ppl_2b_w4g64gptq_a8.json"),
    ("NV", "NVFP4, weights only", f"{D}/n14_ppl_2b_nvfp4.json"),
    ("NVH", "NVFP4 + RHT, weights only", f"{D}/n27_ppl_2b_nvfp4h_hd.json"),
    ("NV_A8", "NVFP4 + A8", f"{D}/n16_ppl_2b_nvfp4_a8.json"),
    ("NVH_A8", "NVFP4 + RHT + A8", f"{D}/n28_ppl_2b_nvfp4h_hd_a8.json"),
    ("NV_DYN", "full NVFP4, dynamic act scale",
     f"{D}/n18_ppl_2b_nvfp4_actdyn.json"),
    ("NVH_DYN", "full NVFP4 + RHT, dynamic act scale",
     f"{D}/n29_ppl_2b_nvfp4h_hd_actdyn.json"),
    ("NVH_ST", "full NVFP4 + RHT, static act scale",
     f"{D}/n30_ppl_2b_nvfp4h_hd_actstatic.json"),
    ("A8", "bf16 weights + A8", f"{D}/n21_ppl_2b_bf16_a8.json"),
    ("ADYN", "bf16 weights + NVFP4 act (dyn)",
     f"{D}/n22_ppl_2b_bf16_actnvfp4dyn.json"),
    ("PH", "plain-H NVFP4, weights only (superseded)",
     f"{D}/n15_ppl_2b_nvfp4h.json"),
    ("PH_A8", "plain-H NVFP4 + A8 (superseded)",
     f"{D}/n17_ppl_2b_nvfp4h_a8.json"),
    ("PH_DYN", "plain-H full NVFP4, dyn (superseded)",
     f"{D}/n19_ppl_2b_nvfp4h_actdyn.json"),
    ("PH_ST", "plain-H full NVFP4, static (superseded)",
     f"{D}/n20_ppl_2b_nvfp4h_actstatic.json"),
]
PLAIN_H = ("PH", "PH_A8", "PH_DYN", "PH_ST")
# the inert order: seed 1 must reproduce seed 0 BIT FOR BIT
PLAIN_H_SEED1 = f"{D}/n23_ppl_2b_nvfp4h_actdyn_seed1.json"
# RHT seeds of the two full-NVFP4 + RHT rows (seed 0 = the row itself)
SEED_SETS = OrderedDict([
    ("dynamic act scale", [
        (0, "NVH_DYN", None),
        (1, "NVH_DYN_S1", f"{D}/n31_ppl_2b_nvfp4h_hd_actdyn_seed1.json"),
        (2, "NVH_DYN_S2", f"{D}/n32_ppl_2b_nvfp4h_hd_actdyn_seed2.json")]),
    ("static act scale", [
        (0, "NVH_ST", None),
        (1, "NVH_ST_S1", f"{D}/n33_ppl_2b_nvfp4h_hd_actstatic_seed1.json"),
        (2, "NVH_ST_S2", f"{D}/n34_ppl_2b_nvfp4h_hd_actstatic_seed2.json")]),
])
SEEDS = [s for v in SEED_SETS.values() for s in v]

P40 = f"{D}/n09_ppl_2b_bf16_cuda.json"
# fp16 noise tolerance: 0.001 PPL, about 1/16 of 0.016537 — the smallest PPL
# gap the 2B study ranked on (docs/QWEN2B_QUANT_STUDY.md:308-309)
P40_TOL = 0.001
BN = "evidence/qwen9b/bn/BN_CENSUS.md"
STREAM_MS = 54.408          # BN_CENSUS.md:41 — weight streaming, any channel
TB_MS = 131.138             # BN_CENSUS.md:18 — the testbench token
BOARD_MS = 137.121          # BN_CENSUS.md:19 — the silicon token


def cite(path, key):
    """path:line of the first `"key":` in a json written with indent=1."""
    with open(os.path.join(ROOT, path)) as f:
        for i, line in enumerate(f, 1):
            if line.startswith(f' "{key}":'):
                return f"{path}:{i}"
    raise SystemExit(f"{path}: no top-level {key!r}")


def check_text(path, line, needle):
    with open(os.path.join(ROOT, path)) as f:
        text = f.read().splitlines()[line - 1]
    assert needle in text, (path, line, needle, text)


def load(path):
    with open(os.path.join(ROOT, path)) as f:
        return json.load(f)


def matvec_bytes(rec):
    """Packed matvec bytes/token: the NV1 json field, or (the pre-NV1 bf16
    anchor) the same sum over its `classes` block."""
    if "bytes_per_token_matvec" in rec:
        return rec["bytes_per_token_matvec"]
    return sum(rec["classes"][c]["total_bits"] for c in BPT.W4_CLASSES) / 8.0


def weight_format(rec):
    q = set(rec["inject_resolved"].values())
    assert len(q) <= 1, q
    return q.pop() if q else None


def bytes_9b(fmt):
    """(bytes/token, busiest-channel bytes at nch=4, per-image stride ratio
    set vs w4g128) of the 9B inventory in a uniform weight format.  NVFP4
    totals include each image's 4-byte FP32 s_t; the channel split leaves it
    out (4 B against ~10^8 per channel)."""
    cfg = BPT.load_cfg("9b")

    def stride(k):
        if fmt in ("nvfp4", "nvfp4h"):
            return NV.row_stride(k)
        return BPT.image_bytes(1, k, fmt)
    tot, chans, ratios = 0, [0] * 4, set()
    for im in BPT.inventory(cfg):
        s = stride(im["k"])
        ratios.add(s / W.row_stride(im["k"], 128))
        tot += im["nrows"] * s + (NV.TENSOR_SCALE_BITS // 8 if fmt in
                                  ("nvfp4", "nvfp4h") else 0)
        pieces = (BPT.ilv_chunks(im["nrows"], 4) if im["amax"] else
                  [(c, r0, n) for c, (r0, n)
                   in enumerate(BPT.split_rows(im["nrows"], 4))])
        for (c, _r0, n) in pieces:
            chans[c] += n * s
    return tot, max(chans), ratios


def main():
    for line, needle in ((41, "54.408"), (18, "131.138"), (19, "137.121")):
        check_text(BN, line, needle)
    recs = {}
    for key, label, path in ROWS + [(k, None, p) for _s, k, p in SEEDS if p]:
        recs[key] = (label, path, load(path))
    a = recs["bf16"][2]
    for key, (label, path, r) in recs.items():
        for f in ("corpus_sha256", "n_positions", "checkpoint_header_sha256",
                  "window", "batch", "model_tag", "host"):
            assert r[f] == a[f], (key, f, r[f], a[f])
        assert r.get("device", "cpu") == "cpu", key
        rot = weight_format(r) == "nvfp4h"
        assert (r.get("rht_form") is not None) == (rot and key not in PLAIN_H), key
    print(f"PROVENANCE: {len(recs)} rows share corpus {a['corpus_sha256'][:16]}"
          f"…, checkpoint {a['checkpoint_header_sha256'][:16]}…, window "
          f"{a['window']}, batch {a['batch']}, {a['n_positions']} positions, "
          f"host {a['host']}, device cpu, model {a['model_tag']}")
    ph1 = load(PLAIN_H_SEED1)
    ph0 = recs["PH_DYN"][2]
    assert ph1["rht_seed"] == 1 and ph0["rht_seed"] == 0
    for f in ("nll_sum", "ppl"):
        assert ph1[f] == ph0[f], (f, ph1[f], ph0[f])
    print(f"INERT-ORDER PROOF: plain-H seed 1 == seed 0 bit for bit, nll_sum "
          f"{ph1['nll_sum']!r} ({cite(PLAIN_H_SEED1, 'nll_sum')} == "
          f"{cite(recs['PH_DYN'][1], 'nll_sum')})")

    p0 = a["ppl"]
    ship = recs["SHIP"][2]["ppl"]
    gap = ship - p0
    print("\nPANEL A — quality (PPL cited to the json field)")
    print("key | row | PPL | dPPL vs bf16 | d% | % of shipped gap left | "
          "act | weights | cite")
    for key, (label, path, r) in recs.items():
        if label is None:
            continue
        d = r["ppl"] - p0
        print(f"{key} | {label} | {r['ppl']:.6f} | {d:+.6f} | "
              f"{100 * d / p0:+.2f}% | {100 * d / gap:.2f}% | "
              f"{r.get('act')} | {r['inject'] or 'bf16'} | "
              f"{cite(path, 'ppl')}")
    ranked = sorted((r["ppl"], k) for k, (lab, _p, r) in recs.items()
                    if lab is not None and k not in PLAIN_H)
    print("  RANKING (current rows, best first): " + " < ".join(
        f"{k} {p:.6f}" for p, k in ranked))
    full = [(p, k) for p, k in ranked if k in ("NV_DYN", "NVH_DYN", "NVH_ST")]
    print(f"  best FULL-NVFP4 row: {full[0][1]} {full[0][0]:.6f} = "
          f"{ship - full[0][0]:+.6f} PPL better than the shipped point")

    print("\nPANEL B — cost")
    cfg2 = BPT.load_cfg("2b")
    ship_bpt = BPT.budget(cfg2, {c: "w4g128" for c in BPT.W4_CLASSES})
    assert recs["SHIP"][2]["bytes_per_token_matvec"] == \
        ship_bpt["bytes_per_token"] == 996282368, \
        (recs["SHIP"][2]["bytes_per_token_matvec"], ship_bpt["bytes_per_token"])
    print(f"  cross-check: the shipped row's bytes_per_token_matvec == "
          f"bytes_per_token.py's 2B all:w4g128 == 996,282,368 "
          f"({cite(recs['SHIP'][1], 'bytes_per_token_matvec')})")
    b9_ship, c9_ship, _ = bytes_9b("w4g128")
    b9 = {}
    for fmt in ("w4g128", "w4g64gptq", "nvfp4"):
        b9[fmt] = bytes_9b(fmt)
        tot, busy, ratios = b9[fmt]
        print(f"  9B {fmt:<9s}: {tot:,} B/token, busiest channel {busy:,} B, "
              f"x{busy / c9_ship:.6f} of shipped, per-image stride ratios "
              f"{sorted(round(x, 6) for x in ratios)}")
    print("key | packed b/w (matvec) | bytes/token 2B | x shipped | "
          "9B modelled d ms/token | 9B modelled ms/token (board) | tok/s | cite")
    for key, (label, path, r) in recs.items():
        if label is None:
            continue
        nw = sum(r["classes"][c]["n_weights"] for c in BPT.W4_CLASSES)
        bpt = matvec_bytes(r)
        fmt = weight_format(r)
        if fmt is None:
            print(f"{key} | 16.000 (bf16) | {bpt:,.0f} | "
                  f"{bpt / recs['SHIP'][2]['bytes_per_token_matvec']:.4f} | "
                  f"n/a (bf16 reference) | n/a | n/a | "
                  f"{cite(path, 'classes')}")
            continue
        f9 = "nvfp4" if fmt in ("nvfp4", "nvfp4h") else fmt
        rb = b9[f9][1] / c9_ship
        dms = STREAM_MS * (rb - 1.0)
        print(f"{key} | {8 * bpt / nw:.4f} | {bpt:,.0f} | "
              f"{bpt / recs['SHIP'][2]['bytes_per_token_matvec']:.4f} | "
              f"{dms:+.3f} | {BOARD_MS + dms:.3f} | "
              f"{1e3 / (BOARD_MS + dms):.3f} | "
              f"{cite(path, 'bytes_per_token_matvec')}")

    def d(k):
        return recs[k][2]["ppl"] - p0
    print("\nDECOMPOSITION (dPPL vs bf16; interaction = combined - weight - act)")
    for name, wk, ak, ck in (
            ("W4 g128 x A8", "W4", "A8", "SHIP"),
            ("NVFP4 x A8", "NV", "A8", "NV_A8"),
            ("NVFP4 x NVFP4-act(dyn)", "NV", "ADYN", "NV_DYN")):
        print(f"  {name}: weight {d(wk):+.6f}, act {d(ak):+.6f}, combined "
              f"{d(ck):+.6f}, interaction {d(ck) - d(wk) - d(ak):+.6f}")

    def dp(k1, k0):
        return recs[k1][2]["ppl"] - recs[k0][2]["ppl"]
    print("  RHT effect (RHT row - no-RHT row, same act) | plain-H row - no-RHT:")
    for name, k0, k1, kp in (("weights only", "NV", "NVH", "PH"),
                             ("+ A8", "NV_A8", "NVH_A8", "PH_A8"),
                             ("+ NVFP4 act dyn", "NV_DYN", "NVH_DYN", "PH_DYN")):
        print(f"    {name}: RHT {dp(k1, k0):+.6f} PPL | plain H "
              f"{dp(kp, k0):+.6f} PPL")
    print(f"  static - dynamic act scale: RHT {dp('NVH_ST', 'NVH_DYN'):+.6f}"
          f" PPL | plain H {dp('PH_ST', 'PH_DYN'):+.6f} PPL")

    print("\nRHT SEED SENSITIVITY (full NVFP4 + RHT, H16 diag(D)/4)")
    means, spreads = {}, {}
    for name, seeds in SEED_SETS.items():
        vals = []
        for seed, key, _p in seeds:
            label, path, r = recs[key]
            assert r["rht_seed"] == seed, (key, r["rht_seed"])
            vals.append(r["ppl"])
            print(f"  {name}, seed {seed}: PPL {r['ppl']:.6f}  "
                  f"({cite(path, 'ppl')}, {cite(path, 'rht_seed')})")
        means[name] = sum(vals) / len(vals)
        spreads[name] = max(vals) - min(vals)
        print(f"  {name}: mean {means[name]:.6f}, spread max-min "
              f"{max(vals) - min(vals):.6f} PPL = "
              f"{100 * (max(vals) - min(vals)) / gap:.2f}% of the shipped gap; "
              f"best seed {min(vals):.6f} vs no-RHT row "
              f"{recs['NV_DYN'][2]['ppl']:.6f}")
    a_, b_ = list(means)
    print(f"  mean over seeds, {b_} - {a_}: {means[b_] - means[a_]:+.6f} PPL")

    print("\nP40 CHECK (rung 0, Ruling C2): 2B bf16 anchor, cuda fp16 vs CPU fp32")
    g = load(P40)
    assert g["device"] == "cuda" and g["model_dtype"] == "float16"
    for f in ("corpus_sha256", "n_positions", "checkpoint_header_sha256",
              "window", "batch"):
        assert g[f] == a[f], f
    dg = g["ppl"] - p0
    print(f"  PPL cuda {g['ppl']:.6f} ({cite(P40, 'ppl')}) vs cpu {p0:.6f}: "
          f"{dg:+.6f} ({dg / p0:+.2e} relative; nll/pos "
          f"{(g['nll_sum'] - a['nll_sum']) / a['n_positions']:+.2e})")
    print(f"  tolerance {P40_TOL} PPL -> "
          f"{'WITHIN' if abs(dg) < P40_TOL else 'OUTSIDE'}; the shipped "
          f"gap is {gap / abs(dg):,.0f}x the fp16 delta and the smallest RHT "
          f"seed spread above is {min(spreads.values()) / abs(dg):,.0f}x it")
    print(f"  eval {g['seconds_eval']:.1f} s ({cite(P40, 'seconds_eval')}) vs "
          f"{a['seconds_eval']:.1f} s ({cite(ANCHOR[2], 'seconds_eval')}): "
          f"{a['seconds_eval'] / g['seconds_eval']:.1f}x; torch {g['torch']}")


if __name__ == "__main__":
    main()
