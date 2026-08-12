#!/usr/bin/env python3
"""Validate ref/layer_ref.py against the actual transformers implementation.

Builds a tiny 2-layer Qwen3.5 text model (one linear_attention + one
full_attention layer, random init, small vocab), runs a T-token PREFILL
through transformers (which uses the chunked delta-rule kernel and fused
attention paths), then replays the same weights through layer_ref.py's
single-token DECODE loop. Per-position hidden states must agree to fp32
tolerance. This is an algorithm-level cross-check: chunked-vs-recurrent
DeltaNet and masked-prefill-vs-cached-decode attention.

Run on snoke (needs torch CPU + transformers). Captures PASS/FAIL.
"""
import json
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layer_ref as LR

from transformers.models.qwen3_5 import Qwen3_5TextConfig, Qwen3_5TextModel

T = 12
torch.manual_seed(7)

cfgd = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "qwen3_5_0.8b_config.json")))["text_config"]
cfgd = dict(cfgd)
cfgd.update(num_hidden_layers=2,
            layer_types=["linear_attention", "full_attention"],
            vocab_size=512, dtype="float32", mtp_num_hidden_layers=0)
cfg = Qwen3_5TextConfig(**{k: v for k, v in cfgd.items()
                           if k in Qwen3_5TextConfig().to_dict() or k == "rope_parameters"})
cfg._attn_implementation = "eager"

model = Qwen3_5TextModel(cfg).eval().float()

x_embeds = torch.randn(1, T, cfg.hidden_size, dtype=torch.float32) * 0.5

with torch.no_grad():
    out = model(inputs_embeds=x_embeds, output_hidden_states=True, use_cache=False)
hs = [h[0].numpy() for h in out.hidden_states]   # [emb, after L0, after L1]

# ---- mirror weights into layer_ref containers ----
sd = {k: v.numpy() for k, v in model.state_dict().items()}

def dn_weights(p):
    return {
        "in_qkv": sd[f"{p}.linear_attn.in_proj_qkv.weight"],
        "in_z":   sd[f"{p}.linear_attn.in_proj_z.weight"],
        "in_b":   sd[f"{p}.linear_attn.in_proj_b.weight"],
        "in_a":   sd[f"{p}.linear_attn.in_proj_a.weight"],
        "conv_w": sd[f"{p}.linear_attn.conv1d.weight"][:, 0, :],
        "dt_bias": sd[f"{p}.linear_attn.dt_bias"],
        "A_log":  sd[f"{p}.linear_attn.A_log"],
        "norm_w": sd[f"{p}.linear_attn.norm.weight"],
        "out":    sd[f"{p}.linear_attn.out_proj.weight"],
    }

def attn_weights(p):
    return {
        "q_proj": sd[f"{p}.self_attn.q_proj.weight"],
        "k_proj": sd[f"{p}.self_attn.k_proj.weight"],
        "v_proj": sd[f"{p}.self_attn.v_proj.weight"],
        "o_proj": sd[f"{p}.self_attn.o_proj.weight"],
        "q_norm": sd[f"{p}.self_attn.q_norm.weight"],
        "k_norm": sd[f"{p}.self_attn.k_norm.weight"],
    }

layers = []
for i, lt in enumerate(cfg.layer_types):
    w = {"ln1": sd[f"layers.{i}.input_layernorm.weight"],
         "ln2": sd[f"layers.{i}.post_attention_layernorm.weight"],
         "mlp": {"gate": sd[f"layers.{i}.mlp.gate_proj.weight"],
                 "up":   sd[f"layers.{i}.mlp.up_proj.weight"],
                 "down": sd[f"layers.{i}.mlp.down_proj.weight"]},
         "type": lt}
    if lt == "full_attention":
        w["attn"] = attn_weights(f"layers.{i}")
    else:
        w["dn"] = dn_weights(f"layers.{i}")
    layers.append(w)

# handle key prefix variants
if not any(k.startswith("layers.") for k in sd):
    sys.exit("FATAL: unexpected state_dict layout: " +
             "\n".join(list(sd.keys())[:10]))

# final norm applies after last layer in hs[-1]? output_hidden_states gives
# hidden states BEFORE final norm for intermediate entries; last entry is
# after final norm in some versions — compare per-layer entries only.

errs = []
caches = [LR.new_cache(lt) for lt in cfg.layer_types]
x_seq = x_embeds[0].numpy().copy()
my_after = [np.zeros((T, cfg.hidden_size), dtype=np.float32) for _ in range(2)]
for t in range(T):
    x = x_seq[t].copy()
    for li, w in enumerate(layers):
        x = LR.layer_decode(x, w, caches[li], t)
        my_after[li][t] = x

final_norm_w = sd["norm.weight"]
for li in range(2):
    ref = hs[li + 1]                       # torch hidden after layer li
    mine = my_after[li]
    if li == 1:                            # hs[-1] is post-final-norm in HF
        mine = np.stack([LR.rmsnorm1p(mine[t], final_norm_w) for t in range(T)])
    per_t = [float(np.abs(mine[t] - ref[t]).max() / (np.abs(ref[t]).max() + 1e-9))
             for t in range(T)]
    rel = max(per_t)
    print(f"layer {li} ({cfg.layer_types[li]}): max_rel_err = {rel:.3e}")
    print("  per-token:", " ".join(f"{e:.1e}" for e in per_t))
    errs.append(rel)

if max(errs) < 2e-4:
    print("VALIDATE_VS_TORCH PASS")
else:
    print("VALIDATE_VS_TORCH FAIL")
    sys.exit(1)
