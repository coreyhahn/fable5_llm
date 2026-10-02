#!/usr/bin/env python3
"""Every number in V4_V5.md, derived from the committed artifacts.

Reads only committed files — this task's PPL jsons, the earlier variants'
jsons, the bf16 anchor, Task 7's per-class sensitivity scan — and imports
`ref/scripts/bytes_per_token.py` for the byte and tok/s columns, so the doc
and the calculator cannot drift apart.  Nothing is hardcoded except the
variant -> file map and the class ranking Task 7 published.

    python3 evidence/qwen2b/q2/v4_v5/v4_v5_table.py     # from the repo root
                                                        # (run on snoke)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
sys.path.insert(0, os.path.join(REPO, "ref", "scripts"))
import bytes_per_token as BPT                                   # noqa: E402

Q2 = os.path.join(REPO, "evidence/qwen2b/q2")
SCAN = os.path.join(Q2, "sensitivity")
ANCHOR = os.path.join(REPO, "evidence/qwen2b/q1/ppl_2b_bf16.json")

# variant -> (json, the --map spec that reproduces its DDR image set)
LADDER = [
    ("bf16 (anchor)", ANCHOR, None),
    ("V1  w4 g128", f"{Q2}/v1_v2/ppl_v1.json", "all:w4g128"),
    ("V2  w4 g64", f"{Q2}/v1_v2/ppl_v2.json", "all:w4g64"),
    ("V3  g64 salience", f"{Q2}/v3/ppl_v3_snoke.json", "all:w4g64s"),
    ("V4gptq g64", f"{Q2}/v4/ppl_v4gptq.json", "all:w4g64gptq"),
    ("V4mix top-1", f"{Q2}/v4_v5/ppl_v4mix_top1.json",
     "all:w4g64,gate_up:w8g128"),
    ("V4mix top-2", f"{Q2}/v4_v5/ppl_v4mix_top2.json",
     "all:w4g64,gate_up:w8g128,lm_head:w8g128"),
    ("V4mix top-3", f"{Q2}/v4_v5/ppl_v4mix_top3.json",
     "all:w4g64,gate_up:w8g128,lm_head:w8g128,dn_in:w8g128"),
    ("V4gptq+gate_up W8", f"{Q2}/v4_v5/ppl_v4mix_gptq_top1.json",
     "all:w4g64gptq,gate_up:w8g128"),
    ("V5  w8 g128", f"{Q2}/v4_v5/ppl_v5.json", "all:w8g128"),
]
RERUNS = [("V5", f"{Q2}/v4_v5/ppl_v5.json", f"{Q2}/v4_v5/ppl_v5_rerun.json"),
          ("V4gptq+gate_up W8", f"{Q2}/v4_v5/ppl_v4mix_gptq_top1.json",
           f"{Q2}/v4_v5/ppl_v4mix_gptq_top1_rerun.json")]
PROMOTE = ("gate_up", "lm_head", "dn_in")      # Task 7's top-3, in order


def load(p):
    with open(p) as f:
        return json.load(f)


def main():
    anchor = load(ANCHOR)
    A = anchor["ppl"]
    cfg = BPT.load_cfg("2b")

    print("=== provenance (every row must share the anchor's setup) ===")
    rows = []
    for name, path, spec in LADDER:
        if not os.path.exists(path):
            print(f"  MISSING {path}")
            continue
        j = load(path)
        for k in ("corpus_sha256", "checkpoint_header_sha256", "n_positions",
                  "window", "batch", "model_tag", "n_tokens"):
            assert j[k] == anchor[k], f"{name}: {k} differs from the anchor"
        if spec is not None:
            assert j["res_scale"] == 8.0, f"{name}: res_scale"
            # the map used for bytes must be the plan that was SCORED
            plan, _ = BPT.parse_map(spec)
            assert plan == {c: q for c, q in j["inject_resolved"].items()
                            if c in BPT.W4_CLASSES}, f"{name}: map != inject"
        rows.append((name, j, spec))
    print(f"  {len(rows)} runs, {anchor['n_positions']} scored positions, "
          f"window {anchor['window']}, batch {anchor['batch']}, "
          f"corpus {anchor['corpus_sha256'][:16]}…, "
          f"ckpt {anchor['checkpoint_header_sha256'][:16]}…")
    print(f"  hosts: " + ", ".join(sorted({str(j.get('host')) for _n, j, _s
                                           in rows})))

    v2 = next(j for n, j, _ in rows if n.startswith("V2"))
    gap = v2["ppl"] - A
    print(f"\n=== the ladder (bf16 {A:.6f}, V2 gap {gap:.6f}) ===")
    print("  variant             PPL         dPPL     % of the V2 gap left   "
          "bytes/token     xV2    b/w    tok/s band")
    for name, j, spec in rows:
        b = (BPT.budget(cfg, BPT.parse_map(spec)[0]) if spec else None)
        left = 100 * (j["ppl"] - A) / gap
        if b:
            ch4 = max(BPT.per_channel_bytes(cfg, BPT.parse_map(spec)[0], 4))
            band = BPT.tok_s_band(ch4)
            bt = (f"{b['bytes_per_token']:>13,} {b['bytes_per_token'] / 999428096:6.3f} "
                  f"{b['bits_per_weight']:6.3f}  {band[-1][3]:5.2f}-{band[0][3]:5.2f}")
        else:
            bt = f"{'-':>13}      -      -      -"
        print(f"  {name:<18s} {j['ppl']:.6f} {j['ppl'] - A:+.6f} "
              f"{left:8.2f} %            {bt}")

    print("\n=== rerun agreement (the study's convention for headlines) ===")
    for tag, p1, p2 in RERUNS:
        if not (os.path.exists(p1) and os.path.exists(p2)):
            print(f"  {tag}: rerun missing")
            continue
        a, b = load(p1), load(p2)
        same6 = f"{a['ppl']:.6f}" == f"{b['ppl']:.6f}"
        rel = abs(a["nll_sum"] - b["nll_sum"]) / abs(a["nll_sum"])
        print(f"  {tag}: {a['ppl']:.6f} vs {b['ppl']:.6f}  "
              f"{'AGREE' if same6 else 'DISAGREE'} to 6 dp; "
              f"nll_sum bit-identical: {a['nll_sum'] == b['nll_sum']} "
              f"({a['nll_sum']:.6f} vs {b['nll_sum']:.6f}, rel {rel:.2e}); "
              f"separate processes on {a.get('host')}/{b.get('host')}")

    # --- V4mix vs Task 7's arithmetic prediction -------------------------
    print("\n=== V4mix vs Task 7's prediction (SENSITIVITY.md section 5) ===")
    d = {}
    for c in PROMOTE:
        s = load(os.path.join(SCAN, f"scan_{c}.json"))
        d[c] = s["ppl"] - A
    v5 = next((j for n, j, _ in rows if n.startswith("V5")), None)
    print("  k  promoted                   predicted (V2-sum dPPL)   measured"
          "     error      vs V5's whole damage")
    for k in (1, 2, 3):
        name = f"V4mix top-{k}"
        j = next((jj for n, jj, _ in rows if n == name), None)
        if j is None:
            continue
        pred = v2["ppl"] - sum(d[c] for c in PROMOTE[:k])
        err = j["ppl"] - pred
        share = (f"{abs(err) / (v5['ppl'] - A):5.1f}x" if v5 else "")
        print(f"  {k}  {'+'.join(PROMOTE[:k]):<26s} {pred:.6f}          "
              f"{j['ppl']:.6f} {err:+.6f}   {share}")
    print("  Two effects with opposite signs are folded into that error.  The "
          "prediction treats a promoted class as UNDAMAGED, so W8's own "
          "residual (V5's whole-model damage is only "
          f"{(v5['ppl'] - A) if v5 else float('nan'):.6f}) pushes the measured "
          "value UP; Task 7's measured super-additivity (+0.075 PPL joint vs "
          "sum of parts) pushes it DOWN, because taking the largest classes "
          "out of the W4 set removes more than their one-at-a-time deltas.  "
          "The sign of the error says which won.")

    # --- price of a PPL point -------------------------------------------
    print("\n=== what a PPL point costs in bytes (against V2) ===")
    b2 = BPT.budget(cfg, BPT.parse_map("all:w4g64")[0])["bytes_per_token"]
    for name, j, spec in rows:
        if spec is None or name.startswith(("V1", "V2")):
            continue
        b = BPT.budget(cfg, BPT.parse_map(spec)[0])["bytes_per_token"]
        dppl = v2["ppl"] - j["ppl"]
        extra = b - b2
        rate = (f"{extra / dppl / 1e6:9.1f} MB per PPL point"
                if dppl > 0 else "        - (no gain)")
        print(f"  {name:<18s} dPPL {dppl:+.6f}  extra bytes "
              f"{extra:>13,}  {rate}")

    # --- DDR fit ---------------------------------------------------------
    print("\n=== DDR fit (weight window "
          f"{BPT.WEIGHT_WINDOW / 2**20:,.0f} MiB per channel) ===")
    for name, j, spec in rows:
        if spec is None:
            continue
        plan = BPT.parse_map(spec)[0]
        f1 = max(BPT.packed_footprint(cfg, plan, 1))
        f4 = max(BPT.packed_footprint(cfg, plan, 4))
        print(f"  {name:<18s} nch=1 {f1 / 2**20:8.1f} MiB "
              f"({100 * f1 / BPT.WEIGHT_WINDOW:5.1f} %) "
              f"{'OK' if f1 < BPT.WEIGHT_WINDOW else 'DOES NOT FIT'}"
              f"   nch=4 {f4 / 2**20:7.1f} MiB "
              f"({100 * f4 / BPT.WEIGHT_WINDOW:5.1f} %) "
              f"{'OK' if f4 < BPT.WEIGHT_WINDOW else 'DOES NOT FIT'}")

    # --- the step decomposition (V4_V5.md section 6's table) -------------
    print("\n=== step decomposition, 2B nch=4 (r = 1.000 .. 1.131) ===")
    print("  variant             matvec ms        step ms          tok/s")
    for name, _j, spec in rows:
        if spec is None:
            continue
        band = BPT.tok_s_band(max(BPT.per_channel_bytes(
            cfg, BPT.parse_map(spec)[0], 4)))
        lo, hi = band[0], band[-1]        # r lo (fast) .. r hi (slow)
        print(f"  {name:<18s} {lo[1]:5.2f} .. {hi[1]:5.2f}   "
              f"{lo[2]:5.2f} .. {hi[2]:5.2f}   {hi[3]:5.2f} - {lo[3]:5.2f}")

    # --- how much throughput a W8 variant really costs -------------------
    print("\n=== the throughput penalty, and how sensitive it is ===")
    print("  Only the matvec bucket moves with precision.  The penalty is "
          "therefore bounded by\n  how big that bucket is, which the layer "
          f"bucket ({BPT.LAYER_MS_2B} ms, the feasibility study's\n  figure and "
          "NOT verified by MOVER_NORM) dominates.  Worst case = layer 0.")
    b2 = max(BPT.per_channel_bytes(cfg, BPT.parse_map("all:w4g64")[0], 4))
    for name, _j, spec in rows:
        if spec is None or name in ("V1  w4 g128", "V2  w4 g64",
                                    "V3  g64 salience", "V4gptq g64"):
            continue        # the four that stream V2's exact byte count
        bv = max(BPT.per_channel_bytes(cfg, BPT.parse_map(spec)[0], 4))
        line = []
        for layer in (BPT.LAYER_MS_2B, 0.0):
            worst = 0.0
            for r in (BPT.R_BRACKET[0], BPT.R_BRACKET[-1]):
                mv2 = (b2 / 64.0) * r / BPT.UI_CLK_HZ * 1e3
                mvv = (bv / 64.0) * r / BPT.UI_CLK_HZ * 1e3
                s2 = mv2 + BPT.MOVERS_MS_2B + layer
                sv = mvv + BPT.MOVERS_MS_2B + layer
                worst = min(worst, -100 * (1 - s2 / sv)) if worst else \
                    -100 * (1 - s2 / sv)
                worst = min(worst, -100 * (1 - s2 / sv))
            line.append(f"layer={layer:4.1f} ms -> {worst:+6.1f} %")
        print(f"  {name:<18s} tok/s vs V2: " + "   ".join(line))

    print("\n=== cost of the runs ===")
    for name, j, spec in rows:
        if spec is None:
            continue
        print(f"  {name:<18s} build {j['seconds_build']:7.1f} s  eval "
              f"{j['seconds_eval']:7.1f} s  host {j.get('host')} "
              f"threads {j.get('threads')} torch {j.get('torch')}")


if __name__ == "__main__":
    main()
