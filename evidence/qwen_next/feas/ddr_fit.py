#!/usr/bin/env python3
"""ddr_fit.py — DDR fit at 4B / 9B through the REAL allocator.

Runs the shipped `sw/hwmap.py:plan_weights` (the one the emitter and the host
both go through) via `ref/scripts/bytes_per_token.py`'s `fit()`, on synthetic
manifests built for the 4B and 9B geometries.

TWO things make this trustworthy rather than a re-derivation:

 1. `bytes_per_token.load_cfg` is the ONLY function monkeypatched — it accepts
    only the `0.8b`/`2b` tags today (`ref/model_select.py:5-8`).  Everything
    downstream, including `HW.plan_weights`, is the shipped code.

 2. Every image the inventory produces is CROSS-CHECKED against the real
    checkpoint: for each weight class, sum(nrows*k) over the inventory must
    equal the parameter count the safetensors headers report for that class
    (evidence/qwen_next/feas/geometry_raw.json).  If the image list does not
    describe the actual checkpoint, this script fails.

ONE geometry encoding needs stating, because it looks like a fudge and is not:
`ref/scripts/bytes_per_token.py:110-111` computes `LKD = linear_num_value_heads
* linear_key_head_dim`, i.e. it assumes key heads == value heads.  True at
0.8B/2B (16/16), FALSE at 4B/9B (16 key heads, 32 value heads).  The tool only
ever uses LKD as a TOTAL key width, so passing `linear_key_head_dim = 64` with
`linear_num_value_heads = 32` reproduces the checkpoint's true total key width
2048 and therefore the true CONV_DIM 8192.  The cross-check in (2) is what
proves that encoding right rather than merely convenient.
"""
import json
import os
import sys

ROOT = "/home/cah/r2d2/code/fpga/fable5_llm"
sys.path.insert(0, os.path.join(ROOT, "sw"))
sys.path.insert(0, os.path.join(ROOT, "ref"))
sys.path.insert(0, os.path.join(ROOT, "ref", "scripts"))
os.environ.setdefault("FABLE5_MODEL", "2b")

import bytes_per_token as B                                    # noqa: E402
import hwmap as HW                                             # noqa: E402

GEOM = json.load(open(os.path.join(ROOT, "evidence/qwen_next/feas/geometry_raw.json")))


def cfg_for(hidden, ffn, nlayers, nq, nkv, hd, lnvh, lnkh, ldk, ldv, vocab):
    """A text_config for bytes_per_token, with the LKD encoding noted above."""
    types = ["full_attention" if (i % 4) == 3 else "linear_attention"
             for i in range(nlayers)]
    return {
        "hidden_size": hidden, "intermediate_size": ffn,
        "num_hidden_layers": nlayers, "layer_types": types,
        "num_attention_heads": nq, "num_key_value_heads": nkv, "head_dim": hd,
        "linear_num_value_heads": lnvh,
        # total key width = lnvh * ldk_encoded == lnkh * ldk_true
        "linear_key_head_dim": (lnkh * ldk) // lnvh,
        "linear_value_head_dim": ldv,
        "vocab_size": vocab,
    }


#                H     FFN  NL  NQ NKV  HD LNVH LNKH LDK LDV  VOCAB
MODELS = {
    "2B":   (2048,  6144, 24,  8,  2, 256, 16, 16, 128, 128, 248320),
    "4B":   (2560,  9216, 32, 16,  4, 256, 32, 16, 128, 128, 248320),
    "9B":   (4096, 12288, 32, 16,  4, 256, 32, 16, 128, 128, 248320),
}
REPO = {"2B": "Qwen/Qwen3.5-2B", "4B": "Qwen/Qwen3.5-4B", "9B": "Qwen/Qwen3.5-9B"}

# Class names differ between the checkpoint census (fetch_geometry.classify)
# and the inventory; the head is `lm_head` in both, and for a TIED checkpoint
# the head shares the emb tensor so the census reports it under `emb`.
CENSUS_ALIAS = {"gate_up": "gate_up", "down": "down", "dn_in": "dn_in",
                "dn_out": "dn_out", "qkv": "qkv", "o_proj": "o_proj"}


def crosscheck(name):
    """inventory(cfg) must describe the actual checkpoint, class by class."""
    cfg = cfg_for(*MODELS[name])
    inv = B.inventory(cfg)
    got = {}
    for im in inv:
        got[im["cls"]] = got.get(im["cls"], 0) + im["nrows"] * im["k"]
    census = GEOM[REPO[name]]["by_class"]
    tied = GEOM[REPO[name]]["config"]["tie_word_embeddings"] is True
    print(f"  --- {name}: {len(inv)} images, cross-check vs the safetensors headers")
    ok = True
    for cls, alias in sorted(CENSUS_ALIAS.items()):
        want = census.get(alias, {}).get("params", 0)
        match = got.get(cls, 0) == want
        ok &= match
        print(f"      {cls:9s} inventory {got.get(cls,0):>15,}  checkpoint "
              f"{want:>15,}  {'OK' if match else '*** MISMATCH ***'}")
    # the head: untied -> its own tensor; tied -> the emb tensor serves it
    head_want = census.get("lm_head", {}).get("params") or \
        census.get("emb", {}).get("params", 0)
    match = got.get("lm_head", 0) == head_want
    ok &= match
    print(f"      {'lm_head':9s} inventory {got.get('lm_head',0):>15,}  checkpoint "
          f"{head_want:>15,}  {'OK' if match else '*** MISMATCH ***'}"
          f"   (tie_word_embeddings={tied})")
    assert ok, f"{name}: the image inventory does not match the checkpoint"
    return cfg, inv


def run(name, cfg, mapspec, nch=4):
    plan = B.parse_map(mapspec)[0] if isinstance(B.parse_map(mapspec), tuple) \
        else B.parse_map(mapspec)
    bud = B.budget(cfg, plan)
    f4 = B.fit(cfg, plan, nch=nch, repack=True)
    f1 = B.fit(cfg, plan, nch=1, repack=False)
    return bud, f1, f4


MAPS = ["all:w8g128", "all:w4g128", "all:w4g64"]

if __name__ == "__main__":
    print("=" * 78)
    print("CROSS-CHECK: the synthetic image inventory vs the real checkpoints")
    print("=" * 78)
    cfgs = {}
    for name in ("2B", "4B", "9B"):
        cfgs[name] = crosscheck(name)[0]

    print()
    print("=" * 78)
    print(f"DDR FIT — weight window {B.WEIGHT_WINDOW/2**20:.0f} MiB/chan "
          f"(EMB_BASE 0x{HW.EMB_BASE:x} - W_BASE 0x{HW.W_BASE:x}), "
          f"channel span {HW.CH_STRIDE/2**30:.0f} GiB")
    print("=" * 78)
    out = {}
    for mapspec in MAPS:
        print(f"\n### map = {mapspec}")
        print(f"    {'model':6s} {'imgs':>5s} {'bytes/token':>15s} {'MiB':>9s} "
              f"{'b/w':>6s} {'nch=1':>9s} {'busiest ch (nch=4)':>20s} "
              f"{'% window':>9s}  verdict")
        for name in ("2B", "4B", "9B"):
            cfg = cfgs[name]
            bud, f1, f4 = run(name, cfg, mapspec)
            busiest = max(f4["used"])
            pct1 = 100.0 * max(f1["used"]) / B.WEIGHT_WINDOW
            pct4 = 100.0 * busiest / B.WEIGHT_WINDOW
            verdict = "FIT PASS" if f4["fits"] else "FIT FAIL"
            print(f"    {name:6s} {f4['images']:5d} {bud['bytes_per_token']:>15,} "
                  f"{bud['bytes_per_token']/2**20:9.1f} "
                  f"{bud['bits_per_weight']:6.3f} {pct1:8.1f}% "
                  f"{busiest/2**20:17.1f} MiB {pct4:8.1f}%  {verdict}"
                  + (f"   [{f4['refused']}]" if f4["refused"] else ""))
            out[f"{name}/{mapspec}"] = {
                "bytes_per_token": bud["bytes_per_token"],
                "bits_per_weight": bud["bits_per_weight"],
                "images": f4["images"],
                "used_nch4": f4["used"], "used_nch1": f1["used"],
                "pct_window_nch4": pct4, "pct_window_nch1": pct1,
                "fits_nch4": f4["fits"], "refused": f4["refused"],
                "agrees_with_reimpl": f4["agrees"],
            }
            if f4["agrees"] is False:
                print("        *** independent re-implementation DISAGREES ***")

    print()
    print("=" * 78)
    print("PER-CHANNEL DETAIL at all:w8g128 and all:w4g128, nch=4")
    print("=" * 78)
    for mapspec in ("all:w8g128", "all:w4g128"):
        for name in ("2B", "4B", "9B"):
            k = f"{name}/{mapspec}"
            u = out[k]["used_nch4"]
            print(f"    {name:4s} {mapspec:11s} " +
                  "  ".join(f"ch{c} {v/2**20:8.1f} MiB" for c, v in enumerate(u))
                  + f"   spread {(max(u)-min(u))/2**20:.1f} MiB"
                  + f"   xcheck={out[k]['agrees_with_reimpl']}")

    print()
    print("=" * 78)
    print("EMBEDDING TABLE — sw/hwmap.py:356-365 seq_emb_log2 rejects non-pow2")
    print("=" * 78)
    print(f"    EMB_BASE 0x{HW.EMB_BASE:x} on channel 0 only; channel span "
          f"{HW.CH_STRIDE/2**30:.0f} GiB; EMBLOG2 range "
          f"[{HW.SEQ_EMBLOG2_MIN}, {HW.SEQ_EMBLOG2_MAX}]")
    for name in ("2B", "4B", "9B"):
        cfg = cfgs[name]
        H, V = cfg["hidden_size"], cfg["vocab_size"]
        packed = 2 * H
        pad = 1 << (packed - 1).bit_length()
        for rb, label in ((packed, "packed 2*H"), (pad, "padded to pow2")):
            try:
                lg = HW.seq_emb_log2(rb)
                ok = "OK  EMBLOG2=%d" % lg
            except Exception as ex:
                ok = "REJECTED: %s" % ex
            tbl = V * rb
            top = HW.EMB_BASE + tbl
            print(f"    {name:4s} {label:16s} row {rb:6d} B  table "
                  f"{tbl/2**20:9.1f} MiB  ends 0x{top:x} "
                  f"({'inside' if top <= HW.CH_STRIDE else 'PAST'} the 4 GiB "
                  f"channel)  {ok}")
            if packed == pad:
                break
        if packed != pad:
            print(f"         -> padding waste {V*(pad-packed)/2**20:.1f} MiB "
                  f"({100.0*(pad-packed)/packed:.0f} % of the table)")

    json.dump(out, open(sys.argv[1], "w") if len(sys.argv) > 1 else sys.stderr,
              indent=1, sort_keys=True)
