#!/usr/bin/env python3
"""Track L gate 0 — verify the 4B and 9B checkpoints against the feasibility
study's predictions.  RUN FROM SNOKE.

    FABLE5_MODEL=4b uv run ... evidence/qwen_next/ladder/checkpoint_verify.py

Same shape as `evidence/qwen2b/q0/checkpoint_verify.md`'s Q0: shard identity,
a whole-file parameter census by top-level prefix, the per-tensor geometry
against `docs/QWEN35_NEXT_FEASIBILITY.md` §1 (which predicts EVERY shape — any
deviation is printed as a DEVIATION line and makes the script exit non-zero),
the tie/untie ground truth, and the tokenizer identity.

Nothing here quantizes or scores; it only reads headers and a few tensors.
"""
import hashlib
import json
import os
import sys

import numpy as np

REF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "ref")
sys.path.insert(0, os.path.abspath(REF))

import layer_ref as LR                                          # noqa: E402
import load_qwen35 as LQ                                        # noqa: E402
from model_select import TAG, REPO_DIR                          # noqa: E402

FAIL = []


def check(label, got, want):
    ok = got == want
    print(f"  {'OK      ' if ok else 'DEVIATION'} {label:<44s} "
          f"got={got!r}" + ("" if ok else f"  PREDICTED={want!r}"))
    if not ok:
        FAIL.append(f"{label}: got {got!r}, study predicts {want!r}")
    return ok


# ---------------------------------------------------------------- §1 table
# docs/QWEN35_NEXT_FEASIBILITY.md §1 / §1.1 / §1.3, verbatim.
PREDICT = {
    "4b": dict(hidden_size=2560, intermediate_size=9216, num_hidden_layers=32,
               n_dn=24, n_fa=8, vocab_size=248320, head_dim=256,
               num_attention_heads=16, num_key_value_heads=4,
               linear_num_key_heads=16, linear_num_value_heads=32,
               linear_key_head_dim=128, linear_value_head_dim=128,
               linear_conv_kernel_dim=4, shards=2, tied=True,
               text_tensors=426, text_params=4205751296,
               mtp_tensors=15, mtp_params=120599552,
               vis_tensors=297, vis_params=333514240,
               head_tensors=0, head_params=0,
               dn_shapes={"in_qkv": (8192, 2560), "in_z": (4096, 2560),
                          "in_a": (32, 2560), "in_b": (32, 2560),
                          "A_log": (32,), "dt_bias": (32,),
                          "conv_w": (8192, 4), "norm_w": (128,),
                          "out": (2560, 4096)},
               at_shapes={"q_proj": (8192, 2560), "k_proj": (1024, 2560),
                          "v_proj": (1024, 2560), "o_proj": (2560, 4096),
                          "q_norm": (256,), "k_norm": (256,)}),
    "9b": dict(hidden_size=4096, intermediate_size=12288, num_hidden_layers=32,
               n_dn=24, n_fa=8, vocab_size=248320, head_dim=256,
               num_attention_heads=16, num_key_value_heads=4,
               linear_num_key_heads=16, linear_num_value_heads=32,
               linear_key_head_dim=128, linear_value_head_dim=128,
               linear_conv_kernel_dim=4, shards=4, tied=False,
               text_tensors=426, text_params=7936684544,
               mtp_tensors=15, mtp_params=243290624,
               vis_tensors=333, vis_params=456010480,
               head_tensors=1, head_params=1017118720,
               dn_shapes={"in_qkv": (8192, 4096), "in_z": (4096, 4096),
                          "in_a": (32, 4096), "in_b": (32, 4096),
                          "A_log": (32,), "dt_bias": (32,),
                          "conv_w": (8192, 4), "norm_w": (128,),
                          "out": (4096, 4096)},
               at_shapes={"q_proj": (8192, 4096), "k_proj": (1024, 4096),
                          "v_proj": (1024, 4096), "o_proj": (4096, 4096),
                          "q_norm": (256,), "k_norm": (256,)}),
}


def main():
    if TAG not in PREDICT:
        raise SystemExit(f"checkpoint_verify covers 4b/9b, not {TAG!r}")
    P = PREDICT[TAG]
    cps = LQ.find_checkpoints()
    st = LQ.SafeTensors(cps)
    cfg_full = LQ.load_config_full()
    cfg = cfg_full["text_config"]
    types = cfg["layer_types"]

    print(f"=== Qwen3.5-{TAG.upper()} checkpoint verification "
          f"(FABLE5_MODEL={TAG}) ===\n")

    print("## 1. shards")
    tot = 0
    for i, cp in enumerate(cps):
        sz = os.path.getsize(os.path.realpath(cp))
        tot += sz
        print(f"  [{i}] {os.path.basename(cp)}\n"
              f"      {sz:,} bytes ({sz / 2**20:.1f} MiB)\n"
              f"      header sha256 {st.shard_shas[i]}")
    print(f"  snapshot {os.path.dirname(cps[0])}")
    print(f"  total {tot:,} bytes = {tot / 2**30:.3f} GiB")
    print(f"  COMBINED header sha256 {st.header_sha}"
          + ("" if st.n_shards == 1 else "   (sha256 of the per-shard digests, "
             "newline-joined, in shard order)"))
    check("shard count", st.n_shards, P["shards"])
    print()

    print("## 2. whole-file parameter census by top-level prefix")
    groups = {"model.language_model.": [0, 0], "model.visual.": [0, 0],
              "mtp.": [0, 0], "lm_head.": [0, 0], "OTHER": [0, 0]}
    for k in st.keys():
        n = int(np.prod(st.shape(k))) if st.shape(k) else 1
        for g in groups:
            if g != "OTHER" and k.startswith(g):
                groups[g][0] += 1
                groups[g][1] += n
                break
        else:
            groups["OTHER"][0] += 1
            groups["OTHER"][1] += n
    ttot = ptot = 0
    for g, (nt, np_) in groups.items():
        if nt:
            print(f"  {g:<24s} {nt:4d} tensors  {np_:>15,} params")
        ttot += nt
        ptot += np_
    print(f"  {'TOTAL':<24s} {ttot:4d} tensors  {ptot:>15,} params")
    check("text tensors", groups["model.language_model."][0], P["text_tensors"])
    check("text params", groups["model.language_model."][1], P["text_params"])
    check("mtp tensors", groups["mtp."][0], P["mtp_tensors"])
    check("mtp params", groups["mtp."][1], P["mtp_params"])
    check("vision tensors", groups["model.visual."][0], P["vis_tensors"])
    check("vision params", groups["model.visual."][1], P["vis_params"])
    check("top-level lm_head tensors", groups["lm_head."][0], P["head_tensors"])
    check("top-level lm_head params", groups["lm_head."][1], P["head_params"])
    check("nothing outside the four prefixes", groups["OTHER"][0], 0)
    print()

    print("## 3. text_config geometry")
    for f in ("hidden_size", "intermediate_size", "num_hidden_layers",
              "vocab_size", "head_dim", "num_attention_heads",
              "num_key_value_heads", "linear_num_key_heads",
              "linear_num_value_heads", "linear_key_head_dim",
              "linear_value_head_dim", "linear_conv_kernel_dim"):
        check(f, cfg[f], P[f])
    check("layer_types linear_attention", types.count("linear_attention"), P["n_dn"])
    check("layer_types full_attention", types.count("full_attention"), P["n_fa"])
    check("len(layer_types)", len(types), P["num_hidden_layers"])
    print("  derived layer_ref constants:")
    check("LR.H", LR.H, P["hidden_size"])
    check("LR.LNH (value heads)", LR.LNH, P["linear_num_value_heads"])
    check("LR.LNKH (key heads)", LR.LNKH, P["linear_num_key_heads"])
    check("LR.LKD (= LNKH*LDK)", LR.LKD,
          P["linear_num_key_heads"] * P["linear_key_head_dim"])
    check("LR.LVD (= LNH*LDV)", LR.LVD,
          P["linear_num_value_heads"] * P["linear_value_head_dim"])
    check("LR.CONV_DIM (= 2*LKD + LVD)", LR.CONV_DIM,
          2 * P["linear_num_key_heads"] * P["linear_key_head_dim"]
          + P["linear_num_value_heads"] * P["linear_value_head_dim"])
    print()

    print("## 4. per-tensor shapes vs §1.1 (layer 0 = DeltaNet, "
          "first full_attention layer)")
    dn_i = types.index("linear_attention")
    at_i = types.index("full_attention")
    wdn = LQ.load_layer(st, dn_i)
    wat = LQ.load_layer(st, at_i)
    for k, want in sorted(P["dn_shapes"].items()):
        check(f"L{dn_i}.dn.{k}", tuple(np.shape(wdn["dn"][k])), want)
    for k, want in sorted(P["at_shapes"].items()):
        check(f"L{at_i}.attn.{k}", tuple(np.shape(wat["attn"][k])), want)
    for w, li in ((wdn, dn_i), (wat, at_i)):
        check(f"L{li}.mlp.gate", tuple(np.shape(w["mlp"]["gate"])),
              (P["intermediate_size"], P["hidden_size"]))
        check(f"L{li}.mlp.down", tuple(np.shape(w["mlp"]["down"])),
              (P["hidden_size"], P["intermediate_size"]))
    print("  8192 = 2*(16*128) + 32*128 — 16 KEY heads, 32 VALUE heads:")
    check("2*LKD + LVD == in_qkv rows", 2 * LR.LKD + LR.LVD,
          int(np.shape(wdn["dn"]["in_qkv"])[0]))
    print()

    print("## 5. LM head: tie ground truth (study §1.2)")
    top = cfg_full.get("tie_word_embeddings", "<ABSENT>")
    txt = cfg.get("tie_word_embeddings", "<ABSENT>")
    print(f"  config.json  top-level tie_word_embeddings = {top!r}")
    print(f"  text_config  tie_word_embeddings           = {txt!r}")
    tied, head_key = LQ.checkpoint_is_tied(st)
    print(f"  checkpoint carries lm_head tensor          = {head_key!r}")
    check("tied (tensor ground truth)", tied, P["tied"])
    emb = st.get(LQ.TEXT_PREFIX + "embed_tokens.weight")
    check("embed_tokens shape", tuple(emb.shape),
          (P["vocab_size"], P["hidden_size"]))
    if not tied:
        head = st.get(head_key)
        check("lm_head shape", tuple(head.shape),
              (P["vocab_size"], P["hidden_size"]))
        same = bool(np.array_equal(emb, head))
        check("lm_head is a DISTINCT matrix (not a copy of emb)", same, False)
        print(f"  emb     rms={float(np.sqrt((emb.astype(np.float64)**2).mean())):.6f}"
              f"  |max|={float(np.abs(emb).max()):.4f}")
        print(f"  lm_head rms={float(np.sqrt((head.astype(np.float64)**2).mean())):.6f}"
              f"  |max|={float(np.abs(head).max()):.4f}")
        print("  raw-byte sha256:")
        for nm, key in (("emb    ", LQ.TEXT_PREFIX + "embed_tokens.weight"),
                        ("lm_head", head_key)):
            h = hashlib.sha256()
            h.update(bytes(st.raw_bytes(key)))
            print(f"    {nm}  {h.hexdigest()}")
    print()

    print("## 6. committed config JSON == the snapshot's config.json")
    hub_cfg = os.path.join(os.path.dirname(cps[0]), "config.json")
    from model_select import CONFIG_JSON
    same = open(CONFIG_JSON, "rb").read() == open(hub_cfg, "rb").read()
    check("ref/%s byte-identical to the hub file"
          % os.path.basename(CONFIG_JSON), same, True)
    print(f"  {hashlib.sha256(open(CONFIG_JSON,'rb').read()).hexdigest()}  "
          f"{os.path.basename(CONFIG_JSON)}")
    print()

    print("## 7. tokenizer identity vs 0.8B/2B (study §1.4)")
    root = os.path.dirname(os.path.dirname(os.path.dirname(cps[0])))
    root = os.path.dirname(root)                    # .../hub
    ref_repo = "models--Qwen--Qwen3.5-2B"
    import glob
    for f in ("tokenizer.json", "vocab.json", "merges.txt",
              "chat_template.jinja", "tokenizer_config.json"):
        a = glob.glob(os.path.join(root, REPO_DIR, "snapshots", "*", f))
        b = glob.glob(os.path.join(root, ref_repo, "snapshots", "*", f))
        if not a or not b:
            print(f"  {f:<22s} MISSING ({bool(a)}/{bool(b)})")
            continue
        sa = hashlib.sha256(open(a[0], "rb").read()).hexdigest()
        sb = hashlib.sha256(open(b[0], "rb").read()).hexdigest()
        print(f"  {f:<22s} {'IDENTICAL' if sa == sb else 'DIFFERS  '} "
              f"{TAG}={sa[:16]}…  2b={sb[:16]}…")
    print("  (§1.4 predicts: tokenizer.json / vocab.json / merges.txt "
          "IDENTICAL; chat_template.jinja and tokenizer_config.json DIFFER)")
    print()

    if FAIL:
        print(f"CHECKPOINT_VERIFY FAIL — {len(FAIL)} deviation(s):")
        for f in FAIL:
            print(f"  - {f}")
        return 1
    print(f"CHECKPOINT_VERIFY PASS ({TAG}): every shape, count and parameter "
          "total the feasibility study §1 predicts is confirmed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
