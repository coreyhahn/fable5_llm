#!/usr/bin/env python3
"""geom_report.py — turn geometry_raw.json into the study's geometry tables.

Reads the ranged-header census produced by fetch_geometry.py and prints, per
model: the full head/DeltaNet geometry from config, the representative tensor
SHAPES (layer 0 = a DeltaNet layer, layer 3 = a full-attention layer), the
tensor-name prefix of the LM head, and the per-class parameter census.
"""
import json
import sys

RAW = sys.argv[1] if len(sys.argv) > 1 else \
    "/home/cah/r2d2/code/fpga/fable5_llm/evidence/qwen_next/feas/geometry_raw.json"

with open(RAW) as fh:
    data = json.load(fh)

ORDER = ["Qwen/Qwen3.5-0.8B", "Qwen/Qwen3.5-2B", "Qwen/Qwen3.5-4B", "Qwen/Qwen3.5-9B"]

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
hdr = f"{'field':28s}" + "".join(f"{m.split('-')[-1]:>12s}" for m in ORDER if m in data)
print(hdr)
for k in keys:
    row = f"{k:28s}"
    for m in ORDER:
        if m not in data:
            continue
        row += f"{str(data[m]['config'].get(k)):>12s}"
    print(row)
row = f"{'layer_types (DN/full)':28s}"
for m in ORDER:
    if m not in data:
        continue
    lt = data[m]["config"]["layer_types_counts"]
    row += f"{str(lt.get('linear_attention', 0)) + '/' + str(lt.get('full_attention', 0)):>12s}"
print(row)
row = f"{'rope partial_rotary':28s}"
for m in ORDER:
    if m not in data:
        continue
    rp = (data[m]["config"].get("rope_parameters") or {}).get("partial_rotary_factor")
    row += f"{str(rp):>12s}"
print(row)
row = f"{'rope theta':28s}"
for m in ORDER:
    if m not in data:
        continue
    rp = (data[m]["config"].get("rope_parameters") or {}).get("rope_theta")
    row += f"{str(rp):>12s}"
print(row)

print()
print("=" * 78)
print("CHECKPOINT CENSUS (from the safetensors headers — ranged reads, no weights)")
print("=" * 78)
for m in ORDER:
    if m not in data:
        continue
    d = data[m]
    print(f"\n### {m}   shards={d['n_shards']}  tensors={d['n_tensors']}  "
          f"{d['total_params']:,} params  {d['total_bytes']/2**30:.2f} GiB on disk")
    for p, v in sorted(d["by_prefix"].items()):
        print(f"    prefix {p:24s} {v['tensors']:5d} tensors "
              f"{v['params']:>15,} params  {v['bytes']/2**20:9.1f} MiB")
    print("    per-class (text tower + head + mtp):")
    for c, v in sorted(d["by_class"].items(), key=lambda kv: -kv[1]["params"]):
        print(f"      {c:12s} {v['tensors']:5d} t  {v['params']:>15,} p  "
              f"{v['bytes']/2**20:9.1f} MiB")

print()
print("=" * 78)
print("REPRESENTATIVE TENSOR SHAPES  (L0 = DeltaNet, L3 = full attention)")
print("=" * 78)
for m in ORDER:
    if m not in data:
        continue
    print(f"\n### {m}")
    reps = data[m]["representative_tensors"]
    for tname in sorted(reps):
        t = reps[tname]
        short = tname.replace("model.language_model.", "LM.")
        print(f"    {short:62s} {str(t['shape']):>22s}  {t['dtype']}")
