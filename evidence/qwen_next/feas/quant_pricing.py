#!/usr/bin/env python3
"""quant_pricing.py — quantization-campaign compute and disk, on SNOKE anchors only.

Review round 2, finding 5: the earlier pricing mixed hosts.  The 0.8B and 2B
bf16 anchors in `evidence/qwen2b/q1/` carry `torch 2.6.0+cu124` and **no host
key** — they are darthplagueis CUDA runs.  The committed snoke twin of the same
2B bf16 point is 2.814x slower.  Since the campaign must run on snoke (the
standing rule after the arithmetic fault), every anchor here is a snoke one.

Anchors, all with `"host": "snoke"` in their own json:
  evidence/qwen2b/q1/ppl_2b_bf16_snoke.json   bf16 anchor  build 45.914 + eval 404.930
  evidence/qwen2b/q2/v4_v5/ppl_v5.json        W8 variant   build 114.605 + eval 462.589
Both at 2B, whose TEXT tower is 1,881,825,088 params
(evidence/qwen2b/q0/checkpoint_verify.md; this study's f02 census agrees).

Scaling is PROPORTIONAL to text-tower parameters from that single snoke point.
Stated as a limitation rather than hidden: one point cannot measure an
intercept, and the darthplagueis pair implies a large one (53 s of the 0.8B's
89 s), which would make the true cost SUB-linear.  Proportional is therefore an
UPPER bound on the marginal cost, and it is the honest direction to err.
"""
import json
import os
import sys

ROOT = "/home/cah/r2d2/code/fpga/fable5_llm"


def load(p):
    return json.load(open(os.path.join(ROOT, p)))


A_BF16 = load("evidence/qwen2b/q1/ppl_2b_bf16_snoke.json")
A_VAR = load("evidence/qwen2b/q2/v4_v5/ppl_v5.json")
A_DP = load("evidence/qwen2b/q1/ppl_2b_bf16.json")

# ---- THE MEASURED 2B 5-POINT LADDER, all five on snoke ------------------
# Re-review N2: anchoring the four variant points on V5 (W8) understated the
# ladder 2.11x, because W8 is the CHEAPEST of the five — its quantizer is a
# straight per-group rescale, while V1/V2 do an MSE grid search and V4gptq
# runs a full-Hessian error-feedback pass.  The ladder is priced from the five
# committed snoke points themselves, not from one of them.
LADDER = [
    ("bf16 anchor", "evidence/qwen2b/q1/ppl_2b_bf16_snoke.json"),
    ("V1  W4 g128", "evidence/qwen2b/q2/v1_v2/ppl_v1_snoke.json"),
    ("V2  W4 g64", "evidence/qwen2b/q2/v1_v2/ppl_v2_snoke.json"),
    ("V4gptq", "evidence/qwen2b/q2/v4/ppl_v4gptq.json"),
    ("V5  W8 g128", "evidence/qwen2b/q2/v4_v5/ppl_v5.json"),
]

P2B = 1_881_825_088
PARAMS = {"2B": P2B, "4B": 4_205_751_296, "9B": 8_953_803_264}
# 9B includes its untied lm_head (1,017,118,720), which the loader must read
# as a separate tensor and which perplexity_eval scores like any other class.

GPTQ_CALIB_S_2B = 241.0        # QWEN2B_QUANT_STUDY 6.3.2
GPTQ_NPZ_GIB_2B = 4.5          # same
IMAGE_BUILD_S_2B = 918.0       # same (uncalibrated); GPTQ makes it 1949

CKPT_GIB = {"4B": 8.68, "9B": 17.98}          # f01, safetensors headers
W8_GIB = {"4B": (4104.2 + 1940.0) / 1024, "9B": (7686.2 + 1940.0) / 1024}
W4_GIB = {"4B": (2099.2 + 1940.0) / 1024, "9B": (3902.2 + 1940.0) / 1024}
SNOKE_FREE_GB = 94.0                          # f07


def hhmm(sec):
    return f"{sec/3600:.2f} h" if sec >= 3600 else f"{sec/60:.1f} min"


if __name__ == "__main__":
    print("=" * 78)
    print("0. THE HOST PROBLEM WITH THE OLD ANCHORS")
    print("=" * 78)
    print(f"    ppl_2b_bf16.json        host={A_DP.get('host','<ABSENT>')!r:10s} "
          f"torch={A_DP['torch']:14s} eval {A_DP['seconds_eval']:8.3f} s")
    print(f"    ppl_2b_bf16_snoke.json  host={A_BF16.get('host')!r:10s} "
          f"torch={A_BF16['torch']:14s} eval {A_BF16['seconds_eval']:8.3f} s")
    print(f"    -> snoke is {A_BF16['seconds_eval']/A_DP['seconds_eval']:.3f}x "
          f"slower on the SAME point.  Every figure below uses the snoke anchor.")
    print(f"    The variant anchor is already snoke: ppl_v5.json host="
          f"{A_VAR.get('host')!r}, threads={A_VAR.get('threads')}.")
    print(f"    (The earlier revision's '18 min/variant' mixed a darthplagueis")
    print(f"     bf16 anchor with this snoke variant anchor — that was the bug.)")

    bf16_2b = A_BF16["seconds_build"] + A_BF16["seconds_eval"]
    var_2b = A_VAR["seconds_build"] + A_VAR["seconds_eval"]

    print()
    print("=" * 78)
    print("0b. THE MEASURED 2B 5-POINT LADDER — all five points, all on snoke")
    print("=" * 78)
    print(f"    {'point':13s} {'build':>10s} {'eval':>10s} {'total':>10s} "
          f"{'threads':>8s}  json")
    tot = 0.0
    per = {}
    for lab, path in LADDER:
        d = load(path)
        t = d["seconds_build"] + d["seconds_eval"]
        tot += t
        per[lab] = t
        print(f"    {lab:13s} {d['seconds_build']:10.3f} {d['seconds_eval']:10.3f} "
              f"{t:10.3f} {str(d.get('threads')):>8s}  {path.split('qwen2b/')[1]}")
    print(f"    {'LADDER TOTAL':13s} {'':10s} {'':10s} {tot:10.3f} s = "
          f"{tot/60:.1f} min")
    vs = [per[l] for l, _ in LADDER[1:]]
    print(f"\n    VARIANT SPREAD: cheapest {min(vs):.3f} s ({min(per, key=lambda k: per[k] if k != 'bf16 anchor' else 9e9)})"
          f"  dearest {max(vs):.3f} s  -> **{max(vs)/min(vs):.2f}x**")
    print(f"    An earlier revision priced all four variants at V5's "
          f"{var_2b:.3f} s, the CHEAPEST of them, and so ran "
          f"{tot/(bf16_2b + 4*var_2b):.2f}x low.")
    print(f"    (V5 is cheapest because W8 g128 is a straight per-group rescale;")
    print(f"     V1/V2 run an MSE grid search and V4gptq a full-Hessian pass.)")
    print(f"    CAVEAT: the five ran at DIFFERENT thread counts (6/6/6/10/8), so")
    print(f"    the ladder total is a real elapsed cost on this machine but not a")
    print(f"    controlled per-point comparison.  The 5,810 s is what it took.")
    LADDER_2B = tot

    print()
    print("=" * 78)
    print("1. COMPUTE — proportional to text-tower params, from the snoke anchors")
    print("=" * 78)
    print(f"    {'target':7s} {'text params':>15s} {'xP vs 2B':>9s} "
          f"{'bf16 anchor':>13s} {'one variant':>13s} {'5-point ladder':>16s}")
    out = {}
    for nm in ("2B", "4B", "9B"):
        k = PARAMS[nm] / P2B
        b, v = bf16_2b * k, var_2b * k
        ladder = LADDER_2B * k          # the MEASURED ladder, scaled
        print(f"    {nm:7s} {PARAMS[nm]:>15,} {k:9.4f} "
              f"{hhmm(b):>13s} {hhmm(v):>13s} {hhmm(ladder):>16s}")
        out[nm] = {"scale": k, "bf16_s": b, "variant_s": v, "ladder_s": ladder,
                   "gptq_calib_s": GPTQ_CALIB_S_2B * k,
                   "image_build_s": IMAGE_BUILD_S_2B * k,
                   "gptq_npz_gib": GPTQ_NPZ_GIB_2B * k}
    print(f"\n    the ladder column scales the MEASURED 5-point total "
          f"({LADDER_2B:.1f} s at 2B), NOT bf16 + 4x one variant")
    print(f"    the 'one variant' column is V5 specifically, kept because the "
          f"W8 point is the one a V5-style pick would re-run alone")
    print(f"    {'target':7s} {'GPTQ calib':>12s} {'GPTQ npz':>10s} "
          f"{'DDR image build':>16s} {'peak RSS f32':>13s}")
    for nm in ("4B", "9B"):
        print(f"    {nm:7s} {hhmm(out[nm]['gptq_calib_s']):>12s} "
              f"{out[nm]['gptq_npz_gib']:9.1f}G {hhmm(out[nm]['image_build_s']):>16s} "
              f"{PARAMS[nm]*4/2**30:12.1f}G")
    print(f"    (snoke has 247 G RAM, 242 G available — f09 — so even the 9B's")
    print(f"     float32 forward is comfortable.)")

    print()
    print("=" * 78)
    print("2. DISK — against the 94 GB free on snoke (f07)")
    print("=" * 78)
    print(f"    {'item':34s} {'4B':>9s} {'9B':>9s}")
    rows = [("bf16 checkpoint", CKPT_GIB["4B"], CKPT_GIB["9B"]),
            ("W8 images + emb", W8_GIB["4B"], W8_GIB["9B"]),
            ("W4 images + emb", W4_GIB["4B"], W4_GIB["9B"]),
            ("GPTQ Hessian npz", out["4B"]["gptq_npz_gib"], out["9B"]["gptq_npz_gib"])]
    for lab, a, b in rows:
        print(f"    {lab:34s} {a:8.1f}G {b:8.1f}G")
    lad = {n: CKPT_GIB[n] for n in ("4B", "9B")}
    lad_img = {n: CKPT_GIB[n] + W8_GIB[n] for n in ("4B", "9B")}
    print(f"    {'fidelity ladder alone (ckpt only)':34s} "
          f"{lad['4B']:8.1f}G {lad['9B']:8.1f}G")
    print(f"    {'ladder + a W8 image set':34s} "
          f"{lad_img['4B']:8.1f}G {lad_img['9B']:8.1f}G")
    both_no_gptq = lad_img["4B"] + lad_img["9B"]
    gptq_both = out["4B"]["gptq_npz_gib"] + out["9B"]["gptq_npz_gib"]
    print(f"\n    BOTH targets, no GPTQ : {both_no_gptq:6.1f} GiB  "
          f"-> {SNOKE_FREE_GB - both_no_gptq:5.1f} GB headroom of {SNOKE_FREE_GB:.0f}")
    print(f"    BOTH targets, + GPTQ  : {both_no_gptq + gptq_both:6.1f} GiB  "
          f"-> {SNOKE_FREE_GB - both_no_gptq - gptq_both:5.1f} GB headroom "
          f"({both_no_gptq:.0f} + {out['4B']['gptq_npz_gib']:.0f} + "
          f"{out['9B']['gptq_npz_gib']:.0f})")
    print(f"    ONE target + GPTQ, 4B : "
          f"{lad_img['4B'] + out['4B']['gptq_npz_gib']:6.1f} GiB")
    print(f"    ONE target + GPTQ, 9B : "
          f"{lad_img['9B'] + out['9B']['gptq_npz_gib']:6.1f} GiB")
    print("    -> both targets with GPTQ leaves ~21 GB on a machine that also")
    print("       runs Vivado.  One target at a time is the disk recommendation.")

    json.dump(out, open(sys.argv[1], "w") if len(sys.argv) > 1 else sys.stderr,
              indent=1, sort_keys=True)
