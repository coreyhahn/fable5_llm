#!/usr/bin/env python3
"""Bisect layer_ref vs transformers divergence: compare every DeltaNet
intermediate for a single token through the actual module's submodules."""
import json
import os
import sys

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layer_ref as LR
from model_select import CONFIG_JSON, TAG

# G2a GENERALIZED WHAT THIS USED TO REFUSE.  Until 2026-08-31 this file
# raised SystemExit at import whenever LNH != LNKH (Track L review, finding
# D7), because the QKV reshape below assumed one value head per key head:
# LKD = LNKH*LDK, so at 4B/9B (LNH 32, LNKH 16) `conv_n[:LKD].reshape(LNH,
# LDK)` put 2048 values into a 4096-element view and raised a bare numpy
# ValueError halfway through a comparison run.
#
# The reshape now follows the checkpoint's own algebra -- q/k are reshaped by
# the KEY head count and repeated VREP times, exactly `ref/layer_ref.py:223-225`
# -- so the assertion below states the algebra rather than refusing it.
assert LR.LNH % LR.LNKH == 0 and LR.VREP == LR.LNH // LR.LNKH, (
    f"FABLE5_MODEL={TAG}: linear_num_value_heads={LR.LNH} is not a whole "
    f"multiple of linear_num_key_heads={LR.LNKH}; the packed QKV block "
    f"[q:{LR.LKD}][k:{LR.LKD}][v:{LR.LVD}] cannot be sliced per value head.")

from transformers.models.qwen3_5 import Qwen3_5TextConfig, Qwen3_5TextModel

torch.manual_seed(7)
cfgd = json.load(open(CONFIG_JSON))["text_config"]
cfgd = dict(cfgd)
cfgd.update(num_hidden_layers=2,
            layer_types=["linear_attention", "full_attention"],
            vocab_size=512, dtype="float32", mtp_num_hidden_layers=0)
cfg = Qwen3_5TextConfig(**{k: v for k, v in cfgd.items()
                           if k in Qwen3_5TextConfig().to_dict() or k == "rope_parameters"})
cfg._attn_implementation = "eager"
print("cfg check: head_dim", cfg.head_dim,
      "rope", getattr(cfg, "rope_parameters", None) or getattr(cfg, "rope_scaling", None),
      "partial", getattr(cfg, "partial_rotary_factor", "n/a"))

model = Qwen3_5TextModel(cfg).eval().float()
dn = model.layers[0].linear_attn

xn = torch.randn(1, 1, cfg.hidden_size) * 0.7
xn_np = xn[0, 0].numpy()

def cmp(name, t, n):
    t = t.detach().numpy().squeeze()
    n = np.asarray(n).squeeze()
    if t.shape != n.shape:
        print(f"{name}: SHAPE {t.shape} vs {n.shape}")
        return
    rel = np.abs(t - n).max() / (np.abs(t).max() + 1e-9)
    print(f"{name}: rel={rel:.3e} {'OK' if rel < 1e-5 else '<<< DIVERGES'}")

with torch.no_grad():
    # torch intermediates (mirror the module's forward, T=1, no cache)
    mixed = dn.in_proj_qkv(xn)                       # (1,1,6144)
    z_t = dn.in_proj_z(xn)
    b_t = dn.in_proj_b(xn)
    a_t = dn.in_proj_a(xn)
    mt = mixed.transpose(1, 2)                       # (1,6144,1)
    conv_out = F.silu(dn.conv1d(mt)[:, :, :1]).transpose(1, 2)  # (1,1,6144)

    q_t, k_t, v_t = torch.split(conv_out, [dn.key_dim, dn.key_dim, dn.value_dim], dim=-1)
    q_t = q_t.reshape(1, 1, -1, dn.head_k_dim)
    k_t = k_t.reshape(1, 1, -1, dn.head_k_dim)
    v_t = v_t.reshape(1, 1, -1, dn.head_v_dim)
    beta_t = b_t.sigmoid()
    g_t = -dn.A_log.float().exp() * F.softplus(a_t.float() + dn.dt_bias)

    from transformers.models.qwen3_5.modeling_qwen3_5 import (
        torch_recurrent_gated_delta_rule)
    core, S_t = torch_recurrent_gated_delta_rule(
        q_t, k_t, v_t, g=g_t, beta=beta_t, initial_state=None,
        output_final_state=True, use_qk_l2norm_in_kernel=True)
    core_flat = core.reshape(-1, dn.head_v_dim)
    z_flat = z_t.reshape(-1, dn.head_v_dim)
    out_norm = dn.norm(core_flat, z_flat)
    out_t = dn.out_proj(out_norm.reshape(1, 1, -1))

# ---- numpy mirror with the same weights ----
sd = {k: v.numpy() for k, v in model.state_dict().items()}
w = {
    "in_qkv": sd["layers.0.linear_attn.in_proj_qkv.weight"],
    "in_z":   sd["layers.0.linear_attn.in_proj_z.weight"],
    "in_b":   sd["layers.0.linear_attn.in_proj_b.weight"],
    "in_a":   sd["layers.0.linear_attn.in_proj_a.weight"],
    "conv_w": sd["layers.0.linear_attn.conv1d.weight"][:, 0, :],
    "dt_bias": sd["layers.0.linear_attn.dt_bias"],
    "A_log":  sd["layers.0.linear_attn.A_log"],
    "norm_w": sd["layers.0.linear_attn.norm.weight"],
    "out":    sd["layers.0.linear_attn.out_proj.weight"],
}

qkv_n = w["in_qkv"] @ xn_np
cmp("in_qkv", mixed, qkv_n)
z_n = (w["in_z"] @ xn_np).reshape(LR.LNH, LR.LDV)
cmp("z", z_t.reshape(-1), z_n.reshape(-1))
b_n = w["in_b"] @ xn_np
a_n = w["in_a"] @ xn_np

win = np.concatenate([np.zeros((LR.CONV_DIM, LR.CONV_K - 1), dtype=np.float32),
                      qkv_n[:, None]], axis=1)
conv_n = LR.silu(np.sum(win * w["conv_w"], axis=1))
cmp("conv+silu", conv_out.reshape(-1), conv_n)

# VREP: q/k are packed per KEY head and each feeds VREP value heads
# (ref/layer_ref.py:220-225).  At 0.8B/2B VREP == 1 and np.repeat is the
# identity, so this is byte-identical to the reshape it replaces.
q_n = np.repeat(conv_n[:LR.LKD].reshape(LR.LNKH, LR.LDK), LR.VREP, axis=0)
k_n = np.repeat(conv_n[LR.LKD:2 * LR.LKD].reshape(LR.LNKH, LR.LDK),
                LR.VREP, axis=0)
v_n = conv_n[2 * LR.LKD:].reshape(LR.LNH, LR.LDV)
beta_n = LR.sigmoid(b_n)
g_n = -np.exp(w["A_log"]) * LR.softplus(a_n + w["dt_bias"])
cmp("beta", beta_t.reshape(-1), beta_n)
cmp("g", g_t.reshape(-1), g_n)

qq = LR.l2norm(q_n) * np.float32(1.0 / np.sqrt(LR.LDK))
kk = LR.l2norm(k_n)
S = np.zeros((LR.LNH, LR.LDK, LR.LDV), dtype=np.float32)
o_n = np.zeros((LR.LNH, LR.LDV), dtype=np.float32)
for h in range(LR.LNH):
    Sh = S[h] * np.exp(g_n[h])
    kv_mem = Sh.T @ kk[h]
    delta = (v_n[h] - kv_mem) * beta_n[h]
    Sh = Sh + np.outer(kk[h], delta)
    o_n[h] = Sh.T @ qq[h]
    S[h] = Sh
cmp("core_out", core_flat, o_n)
cmp("state_S", S_t, S)

on_n = LR.rmsnorm(o_n, w["norm_w"]) * LR.silu(z_n)
cmp("gated_norm", out_norm, on_n)
out_n = w["out"] @ on_n.reshape(LR.LVD)
cmp("dn_out", out_t.reshape(-1), out_n)
