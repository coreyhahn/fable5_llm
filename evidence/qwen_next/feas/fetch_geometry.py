#!/usr/bin/env python3
"""fetch_geometry.py — EXACT checkpoint geometry from the real safetensors headers.

Downloads NO weights. Uses huggingface_hub.get_safetensors_metadata(), which
issues ranged HTTP reads of each shard's JSON header only (the 8-byte length
prefix + the header itself), plus config.json.

The 2B campaign's lesson: config.json is not the checkpoint. The 2B carries a
vision tower and an MTP head that config.json does not make obvious, and the
loader filters on `model.language_model.` (evidence/qwen2b/q0/checkpoint_verify.md).
So this script reports the FULL per-prefix tensor census, not just the text tower.

Usage:  python3 fetch_geometry.py <repo_id> [<repo_id> ...]
Emits JSON on stdout and a human summary on stderr.
"""
import json
import sys
from collections import defaultdict

from huggingface_hub import get_safetensors_metadata, hf_hub_download

DTYPE_BYTES = {
    "BF16": 2, "F16": 2, "F32": 4, "F64": 8,
    "I8": 1, "U8": 1, "I16": 2, "I32": 4, "I64": 8, "BOOL": 1,
    "F8_E4M3": 1, "F8_E5M2": 1,
}


def numel(shape):
    n = 1
    for d in shape:
        n *= d
    return n


def prefix_of(name):
    """Top-level grouping used by ref/load_qwen35.py's filter."""
    if name.startswith("model.language_model."):
        return "model.language_model"
    if name.startswith("model.visual.") or name.startswith("visual."):
        return "vision"
    if name.startswith("model.mtp") or ".mtp" in name:
        return "mtp"
    if name.startswith("lm_head"):
        return "lm_head"
    return name.split(".")[0] if "." in name else name


def classify(name):
    """Bucket a language-model tensor by the project's weight-class names."""
    if "mtp" in name:
        return "mtp"
    if "embed_tokens" in name:
        return "emb"
    if name.startswith("lm_head"):
        return "lm_head"
    if "gate_up_proj" in name or "gate_proj" in name or "up_proj" in name:
        return "gate_up"
    if "down_proj" in name:
        return "down"
    if "linear_attn.in_proj" in name or "in_proj_qkvz" in name or "in_proj_ba" in name:
        return "dn_in"
    if "linear_attn.out_proj" in name:
        return "dn_out"
    if "linear_attn.conv1d" in name:
        return "dn_conv"
    if "self_attn.o_proj" in name:
        return "o_proj"
    if "self_attn" in name and ("q_proj" in name or "k_proj" in name or "v_proj" in name):
        return "qkv"
    if "norm" in name or name.endswith(".bias") or "dt_bias" in name or "A_log" in name:
        return "norm/gate"
    return "other"


def run(repo_id):
    cfg_path = hf_hub_download(repo_id, "config.json")
    with open(cfg_path) as fh:
        cfg = json.load(fh)
    tc = cfg.get("text_config", cfg)

    meta = get_safetensors_metadata(repo_id)

    tensors = {}
    for fname, fmeta in meta.files_metadata.items():
        for tname, tinfo in fmeta.tensors.items():
            tensors[tname] = {
                "shape": list(tinfo.shape),
                "dtype": tinfo.dtype,
                "shard": fname,
                "bytes": numel(tinfo.shape) * DTYPE_BYTES.get(tinfo.dtype, 0),
            }

    by_prefix = defaultdict(lambda: {"tensors": 0, "params": 0, "bytes": 0})
    by_class = defaultdict(lambda: {"tensors": 0, "params": 0, "bytes": 0})
    for tname, t in tensors.items():
        p = prefix_of(tname)
        by_prefix[p]["tensors"] += 1
        by_prefix[p]["params"] += numel(t["shape"])
        by_prefix[p]["bytes"] += t["bytes"]
        if p in ("model.language_model", "lm_head", "mtp"):
            c = classify(tname)
            by_class[c]["tensors"] += 1
            by_class[c]["params"] += numel(t["shape"])
            by_class[c]["bytes"] += t["bytes"]

    shards = {f: {"tensors": len(m.tensors)} for f, m in meta.files_metadata.items()}

    # One representative tensor per distinct shape-role, layer 0 and one full-attn layer.
    reps = {}
    for tname in sorted(tensors):
        if tname.startswith("model.language_model.layers.0.") or \
           tname.startswith("model.language_model.layers.3.") or \
           "embed_tokens" in tname or tname.startswith("lm_head") or \
           tname == "model.language_model.norm.weight" or "mtp" in tname:
            reps[tname] = tensors[tname]

    out = {
        "repo_id": repo_id,
        "config": {
            "hidden_size": tc.get("hidden_size"),
            "intermediate_size": tc.get("intermediate_size"),
            "num_hidden_layers": tc.get("num_hidden_layers"),
            "vocab_size": tc.get("vocab_size"),
            "head_dim": tc.get("head_dim"),
            "num_attention_heads": tc.get("num_attention_heads"),
            "num_key_value_heads": tc.get("num_key_value_heads"),
            "linear_num_key_heads": tc.get("linear_num_key_heads"),
            "linear_num_value_heads": tc.get("linear_num_value_heads"),
            "linear_key_head_dim": tc.get("linear_key_head_dim"),
            "linear_value_head_dim": tc.get("linear_value_head_dim"),
            "linear_conv_kernel_dim": tc.get("linear_conv_kernel_dim"),
            "full_attention_interval": tc.get("full_attention_interval"),
            "tie_word_embeddings": tc.get("tie_word_embeddings"),
            "mtp_num_hidden_layers": tc.get("mtp_num_hidden_layers"),
            "rms_norm_eps": tc.get("rms_norm_eps"),
            "max_position_embeddings": tc.get("max_position_embeddings"),
            "rope_parameters": tc.get("rope_parameters"),
            "layer_types_counts": {
                k: tc.get("layer_types", []).count(k)
                for k in set(tc.get("layer_types", []))
            },
            "layer_types": tc.get("layer_types"),
        },
        "vision_config_present": "vision_config" in cfg,
        "n_shards": len(shards),
        "shards": shards,
        "n_tensors": len(tensors),
        "total_params": sum(numel(t["shape"]) for t in tensors.values()),
        "total_bytes": sum(t["bytes"] for t in tensors.values()),
        "by_prefix": dict(by_prefix),
        "by_class": dict(by_class),
        "lm_head_present": any(t.startswith("lm_head") for t in tensors),
        "representative_tensors": reps,
        "all_tensor_names_sample": sorted(tensors)[:5] + ["..."] + sorted(tensors)[-5:],
    }
    return out


if __name__ == "__main__":
    results = {}
    for repo in sys.argv[1:]:
        print(f"--- {repo} ---", file=sys.stderr)
        r = run(repo)
        results[repo] = r
        c = r["config"]
        print(f"  hidden={c['hidden_size']} ffn={c['intermediate_size']} "
              f"layers={c['num_hidden_layers']} vocab={c['vocab_size']} "
              f"tied={c['tie_word_embeddings']} head_dim={c['head_dim']} "
              f"kv={c['num_key_value_heads']}", file=sys.stderr)
        print(f"  layer_types: {c['layer_types_counts']}", file=sys.stderr)
        print(f"  shards={r['n_shards']} tensors={r['n_tensors']} "
              f"params={r['total_params']:,} bytes={r['total_bytes']:,} "
              f"({r['total_bytes']/2**30:.2f} GiB)", file=sys.stderr)
        print(f"  lm_head tensor present in checkpoint: {r['lm_head_present']}",
              file=sys.stderr)
        for p, v in sorted(r["by_prefix"].items()):
            print(f"    prefix {p:28s} {v['tensors']:5d} tensors "
                  f"{v['params']:>15,} params {v['bytes']/2**20:10.1f} MiB",
                  file=sys.stderr)
    json.dump(results, sys.stdout, indent=1, sort_keys=True)
