#!/usr/bin/env python3
"""geom2_report.py — the TWO-BOARD study's geometry tables.

A minimal extension of evidence/qwen_next/feas/geom_report.py (which is left
untouched, because the committed 4B/9B study's logs cite it by line).  What is
added here and nowhere there:

  * the MoE config keys (num_experts, num_experts_per_tok, moe_intermediate_size,
    shared_expert_intermediate_size, decoder_sparse_step, mlp_only_layers,
    norm_topk_prob / router scoring) — read from each checkpoint's OWN
    config.json, downloaded by huggingface_hub's cache (config only, NO weights);
  * which layers carry `mlp.experts` tensors, counted from the safetensors
    header names rather than inferred from `decoder_sparse_step`;
  * the per-token ACTIVE parameter count DERIVED FROM THE TENSOR SHAPES, not
    from the model card's "A3B".

The 9B is carried in every table as the reproduction anchor: its rows must
match evidence/qwen_next/feas/f02_geom_report.log.
"""
import json
import os
import sys

from huggingface_hub import hf_hub_download

ROOT = "/home/cah/r2d2/code/fpga/fable5_llm"
RAW = sys.argv[1] if len(sys.argv) > 1 else \
    os.path.join(ROOT, "evidence/qwen_next/feas2/geometry2_raw.json")

with open(RAW) as fh:
    data = json.load(fh)

ORDER = ["Qwen/Qwen3.5-9B", "Qwen/Qwen3.5-27B", "Qwen/Qwen3.5-35B-A3B"]
SHORT = {m: m.split("Qwen3.5-")[-1] for m in ORDER}


def numel(shape):
    n = 1
    for d in shape:
        n *= d
    return n


print("=" * 78)
print("CONFIG GEOMETRY (from each checkpoint's own config.json)")
print("=" * 78)
keys = ["hidden_size", "intermediate_size", "num_hidden_layers", "vocab_size",
        "head_dim", "num_attention_heads", "num_key_value_heads",
        "linear_num_key_heads", "linear_num_value_heads",
        "linear_key_head_dim", "linear_value_head_dim",
        "linear_conv_kernel_dim", "full_attention_interval",
        "tie_word_embeddings", "mtp_num_hidden_layers",
        "max_position_embeddings"]
print(f"{'field':30s}" + "".join(f"{SHORT[m]:>14s}" for m in ORDER if m in data))
for k in keys:
    row = f"{k:30s}"
    for m in ORDER:
        if m in data:
            row += f"{str(data[m]['config'].get(k)):>14s}"
    print(row)
row = f"{'layer_types (DN/full)':30s}"
for m in ORDER:
    if m in data:
        lt = data[m]["config"]["layer_types_counts"]
        row += f"{str(lt.get('linear_attention', 0)) + '/' + str(lt.get('full_attention', 0)):>14s}"
print(row)
for label, path in (("rope partial_rotary", "partial_rotary_factor"),
                    ("rope theta", "rope_theta"),
                    ("rope type", "rope_type")):
    row = f"{label:30s}"
    for m in ORDER:
        if m in data:
            rp = (data[m]["config"].get("rope_parameters") or {}).get(path)
            row += f"{str(rp):>14s}"
    print(row)

print()
print("=" * 78)
print("MoE / FFN CONFIG — the RAW text_config keys, printed by PRESENCE")
print("(a key that is ABSENT prints <absent>; a key that is present and null")
print(" prints None.  The 4B/9B study learned that distinction the hard way:")
print(" docs/QWEN35_NEXT_FEASIBILITY.md 1.2.)")
print("=" * 78)
MOE_KEYS = ["intermediate_size", "num_experts", "num_experts_per_tok",
            "moe_intermediate_size", "shared_expert_intermediate_size",
            "num_shared_experts", "decoder_sparse_step", "mlp_only_layers",
            "norm_topk_prob", "router_aux_loss_coef", "scoring_func",
            "topk_method", "n_group", "topk_group", "routed_scaling_factor",
            "first_k_dense_replace", "moe_layer_freq"]
cfgs = {}
for m in ORDER:
    if m not in data:
        continue
    raw = json.load(open(hf_hub_download(m, "config.json")))
    tc = raw.get("text_config", raw)
    cfgs[m] = (raw, tc)
print(f"{'key':32s}" + "".join(f"{SHORT[m]:>18s}" for m in ORDER if m in cfgs))
for k in MOE_KEYS:
    row = f"{k:32s}"
    for m in ORDER:
        if m in cfgs:
            tc = cfgs[m][1]
            row += f"{(str(tc[k]) if k in tc else '<absent>'):>18s}"
    print(row)
print()
print("tie_word_embeddings, by PRESENCE (top level / text_config):")
for m in ORDER:
    if m in cfgs:
        raw, tc = cfgs[m]
        t = f"present={raw['tie_word_embeddings']!r}" if "tie_word_embeddings" in raw else "ABSENT"
        s = f"present={tc['tie_word_embeddings']!r}" if "tie_word_embeddings" in tc else "ABSENT"
        print(f"  {SHORT[m]:14s} top-level: {t:22s}   text_config: {s}")
        print(f"  {'':14s} lm_head tensor in checkpoint: {data[m]['lm_head_present']}")

print()
print("=" * 78)
print("CHECKPOINT CENSUS (safetensors headers — ranged reads, no weights)")
print("=" * 78)
for m in ORDER:
    if m not in data:
        continue
    d = data[m]
    print(f"\n### {m}   shards={d['n_shards']}  tensors={d['n_tensors']}  "
          f"{d['total_params']:,} params  {d['total_bytes']/2**30:.2f} GiB on disk")
    for p, v in sorted(d["by_prefix"].items()):
        print(f"    prefix {p:24s} {v['tensors']:5d} tensors "
              f"{v['params']:>15,} params  {v['bytes']/2**20:10.1f} MiB")
    print("    per-class (text tower + head + mtp):")
    for c, v in sorted(d["by_class"].items(), key=lambda kv: -kv[1]["params"]):
        print(f"      {c:12s} {v['tensors']:5d} t  {v['params']:>15,} p  "
              f"{v['bytes']/2**20:10.1f} MiB")

print()
print("=" * 78)
print("REPRESENTATIVE TENSOR SHAPES  (L0 = DeltaNet, L3 = full attention)")
print("the `mtp.` per-expert tensors are COUNTED below, not listed")
print("=" * 78)
for m in ORDER:
    if m not in data:
        continue
    print(f"\n### {m}")
    reps = data[m]["representative_tensors"]
    for tname in sorted(reps):
        if tname.startswith("mtp"):
            continue
        t = reps[tname]
        short = tname.replace("model.language_model.", "LM.")
        print(f"    {short:62s} {str(t['shape']):>24s}  {t['dtype']}")
    nmtp = sum(1 for t in reps if t.startswith("mtp"))
    print(f"    [{nmtp} mtp.* tensors elided]")

print()
print("=" * 78)
print("PER-TOKEN ACTIVE PARAMETERS — DERIVED FROM THE TENSOR SHAPES")
print("(not from the model card; the '-A3B' in a name is not evidence)")
print("=" * 78)
for m in ORDER:
    if m not in data:
        continue
    d = data[m]
    raw, tc = cfgs[m]
    reps = d["representative_tensors"]
    H = tc["hidden_size"]
    NL = tc["num_hidden_layers"]
    nfull = d["config"]["layer_types_counts"].get("full_attention", 0)
    ndn = d["config"]["layer_types_counts"].get("linear_attention", 0)
    print(f"\n### {SHORT[m]}   H={H}  L={NL} ({ndn} DN + {nfull} full)")

    def rep(suffix, layer):
        k = f"model.language_model.layers.{layer}.{suffix}"
        return reps[k]["shape"] if k in reps else None

    # --- attention / DN block, per layer kind ---
    dn_names = ["linear_attn.in_proj_qkv.weight", "linear_attn.in_proj_z.weight",
                "linear_attn.in_proj_a.weight", "linear_attn.in_proj_b.weight",
                "linear_attn.conv1d.weight", "linear_attn.out_proj.weight"]
    at_names = ["self_attn.q_proj.weight", "self_attn.k_proj.weight",
                "self_attn.v_proj.weight", "self_attn.o_proj.weight"]
    dn_p = sum(numel(rep(n, 0)) for n in dn_names if rep(n, 0))
    at_p = sum(numel(rep(n, 3)) for n in at_names if rep(n, 3))
    print(f"    DN mixer / layer      {dn_p:>15,}")
    print(f"    GQA mixer / layer     {at_p:>15,}")

    # --- FFN, dense or MoE ---
    gu = rep("mlp.experts.gate_up_proj", 0) or rep("mlp.experts.gate_up_proj", 3)
    if gu is None:
        ff = tc["intermediate_size"]
        ffn_tot = 3 * H * ff
        ffn_act = ffn_tot
        print(f"    dense FFN / layer     {ffn_tot:>15,}   (3 x {H} x {ff})")
    else:
        dp = rep("mlp.experts.down_proj", 0) or rep("mlp.experts.down_proj", 3)
        ne = gu[0]
        mff = gu[1] // 2
        k = tc["num_experts_per_tok"]
        sh = [rep(f"mlp.shared_expert.{n}.weight", 0) for n in
              ("gate_proj", "up_proj", "down_proj")]
        sh_p = sum(numel(s) for s in sh if s)
        shg = rep("mlp.shared_expert_gate.weight", 0)
        rtr = rep("mlp.gate.weight", 0)
        per_exp = numel(gu) // ne + numel(dp) // ne
        ffn_tot = numel(gu) + numel(dp) + sh_p + (numel(shg) if shg else 0) + \
            (numel(rtr) if rtr else 0)
        ffn_act = k * per_exp + sh_p + (numel(shg) if shg else 0) + \
            (numel(rtr) if rtr else 0)
        print(f"    MoE experts           {ne} experts, moe_intermediate {mff}, "
              f"top-k {k}")
        print(f"      router  gate.weight {str(rtr):>22s}  {numel(rtr):>15,}")
        print(f"      experts gate_up     {str(gu):>22s}  {numel(gu):>15,}")
        print(f"      experts down        {str(dp):>22s}  {numel(dp):>15,}")
        print(f"      shared expert (3 t) {'':>22s}  {sh_p:>15,}"
              f"   shared_expert_gate {str(shg)}")
        print(f"      per-expert params   {per_exp:>15,}")
        print(f"    MoE FFN / layer TOTAL {ffn_tot:>15,}")
        print(f"    MoE FFN / layer ACTIVE{ffn_act:>15,}   "
              f"= {k} x {per_exp:,} + shared {sh_p:,} + gates")

    emb = numel(reps["model.language_model.embed_tokens.weight"]["shape"])
    head = numel(reps["lm_head.weight"]["shape"]) if "lm_head.weight" in reps else emb
    tot_mixer = ndn * dn_p + nfull * at_p
    tot_ffn = NL * ffn_tot
    act_ffn = NL * ffn_act
    print(f"    ---")
    print(f"    all mixers            {tot_mixer:>15,}")
    print(f"    all FFN (total)       {tot_ffn:>15,}")
    print(f"    all FFN (active/tok)  {act_ffn:>15,}")
    print(f"    embedding             {emb:>15,}   (1 row read per token, not streamed)")
    print(f"    lm_head               {head:>15,}")
    print(f"    TEXT TOWER total      {tot_mixer + tot_ffn + emb:>15,}"
          f"   (+ head {head:,})")
    print(f"    STREAMED PER TOKEN    {tot_mixer + act_ffn + head:>15,}"
          f"   = mixers + active FFN + head  (no embedding table)")
    census = d["by_prefix"]["model.language_model"]["params"]
    print(f"    census model.language_model = {census:,}  "
          f"(this derivation accounts for {100.0*(tot_mixer+tot_ffn+emb)/census:.2f} %"
          f" of it; the rest is norms/biases/A_log)")
