#!/usr/bin/env python3
"""Float reference for one Qwen3.5-0.8B decoder layer, batch-1 decode.

Mirrors ref/vendor/modeling_qwen3_5.py exactly (numpy float32):
  - full_attention: per-head q/k RMSNorm, partial RoPE (64 of 256 dims,
    theta 1e7), GQA 8Q/2KV, softmax over cache, output gate sigmoid.
  - linear_attention (GatedDeltaNet): depthwise causal conv4 + silu,
    per-head q/k L2 norm, gated delta-rule recurrence (fp32 state
    16 x 128 x 128), RMSNormGated with silu(z).
  - MLP SwiGLU; RMSNorm; residuals.

This file is the STAGE-3 float anchor. The fixed-point spec quantizes
against it; validate_vs_torch.py checks it against transformers once on
snoke (evidence captured).
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_select import CONFIG_JSON                             # noqa: E402

CFG = json.load(open(CONFIG_JSON))["text_config"]

H = CFG["hidden_size"]                    # 1024
NQ = CFG["num_attention_heads"]           # 8
NKV = CFG["num_key_value_heads"]          # 2
HD = CFG["head_dim"]                      # 256
ROT = int(HD * CFG["rope_parameters"]["partial_rotary_factor"])   # 64
THETA = CFG["rope_parameters"]["rope_theta"]                      # 1e7
FFN = CFG["intermediate_size"]            # 3584
EPS = CFG["rms_norm_eps"]                 # 1e-6
LNH = CFG["linear_num_value_heads"]       # 16  (0.8B/2B) — 32 at 4B/9B
LNKH = CFG["linear_num_key_heads"]        # 16  at every released geometry
LDK = CFG["linear_key_head_dim"]          # 128
LDV = CFG["linear_value_head_dim"]        # 128
# KEY heads and VALUE heads are NOT the same count at 4B/9B: 16 key heads feed
# 32 value heads (GQA-style, `repeat_interleave(LNH // LNKH)` in
# vendor/modeling_qwen3_5.py:519-521).  `LKD` is the q/k slice width and must
# follow the KEY head count; `LVD` follows the VALUE head count.  At 0.8B/2B
# LNKH == LNH so both are 2048 and every existing number is unchanged.
VREP = LNH // LNKH                        # value heads per key head (1 or 2)
assert LNH % LNKH == 0, "value heads must be a whole multiple of key heads"
LKD = LNKH * LDK                          # 2048 everywhere so far
LVD = LNH * LDV                           # 2048 (0.8B/2B) — 4096 at 4B/9B
CONV_K = CFG["linear_conv_kernel_dim"]    # 4
CONV_DIM = 2 * LKD + LVD                  # 6144 (0.8B/2B) — 8192 at 4B/9B

f32 = np.float32


def rmsnorm(x, w, eps=EPS):
    """Plain RMSNorm (weight used as-is): Qwen3_5RMSNormGated convention."""
    x = x.astype(f32)
    v = np.mean(x * x, axis=-1, keepdims=True)
    return (x * (1.0 / np.sqrt(v + eps))) * w


def rmsnorm1p(x, w, eps=EPS):
    """Qwen3_5RMSNorm convention: ZERO-initialized weight, scale = (1 + w).
    Applies to ln1/ln2/q_norm/k_norm/final norm — real checkpoints store w
    zero-centered, so forgetting the +1 silently corrupts everything."""
    return rmsnorm(x, (1.0 + np.asarray(w, dtype=f32)), eps)


def silu(x):
    return x / (1.0 + np.exp(-x))


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def softplus(x):
    return np.log1p(np.exp(x))


def l2norm(x, eps=1e-6):
    return x * (1.0 / np.sqrt(np.sum(x * x, axis=-1, keepdims=True) + eps))


def rope_cos_sin(pos):
    """Standard RoPE over ROT dims (text-only mRoPE degenerates: all three
    position streams equal, so the interleaved sections all see `pos`)."""
    inv = 1.0 / (THETA ** (np.arange(0, ROT, 2, dtype=np.float64) / ROT))
    f = pos * inv                                    # (ROT/2,)
    emb = np.concatenate([f, f])                     # (ROT,)
    return np.cos(emb).astype(f32), np.sin(emb).astype(f32)


def rotate_half(x):
    h = x.shape[-1] // 2
    return np.concatenate([-x[..., h:], x[..., :h]], axis=-1)


def apply_rope(x, cos, sin):
    """x: (..., HD); rotate first ROT dims only."""
    xr, xp = x[..., :ROT], x[..., ROT:]
    return np.concatenate([xr * cos + rotate_half(xr) * sin, xp], axis=-1)


# ----------------------------------------------------------------------
# weights containers (random init for testing; real checkpoint in stage 5)
# ----------------------------------------------------------------------
def init_attn_weights(rng):
    s = 0.02
    return {
        "q_proj": rng.normal(0, s, (NQ * HD * 2, H)).astype(f32),
        "k_proj": rng.normal(0, s, (NKV * HD, H)).astype(f32),
        "v_proj": rng.normal(0, s, (NKV * HD, H)).astype(f32),
        "o_proj": rng.normal(0, s, (H, NQ * HD)).astype(f32),
        "q_norm": rng.normal(0, 0.1, HD).astype(f32),   # zero-centered (1+w)
        "k_norm": rng.normal(0, 0.1, HD).astype(f32),
    }


def init_deltanet_weights(rng):
    s = 0.02
    return {
        "in_qkv": rng.normal(0, s, (CONV_DIM, H)).astype(f32),
        "in_z":   rng.normal(0, s, (LVD, H)).astype(f32),
        "in_b":   rng.normal(0, s, (LNH, H)).astype(f32),
        "in_a":   rng.normal(0, s, (LNH, H)).astype(f32),
        "conv_w": rng.normal(0, 0.3, (CONV_DIM, CONV_K)).astype(f32),
        "dt_bias": np.ones(LNH, dtype=f32),
        "A_log":  np.log(rng.uniform(0.5, 8, LNH)).astype(f32),
        "norm_w": (1 + rng.normal(0, 0.1, LDV)).astype(f32),
        "out":    rng.normal(0, s, (H, LVD)).astype(f32),
    }


def init_mlp_weights(rng):
    s = 0.02
    return {
        "gate": rng.normal(0, s, (FFN, H)).astype(f32),
        "up":   rng.normal(0, s, (FFN, H)).astype(f32),
        "down": rng.normal(0, s, (H, FFN)).astype(f32),
    }


def init_layer_weights(rng, layer_type, out_scale=1.0):
    # out_scale: multiplies the residual-adding projections (mlp down,
    # attn o_proj, dn out) AFTER drawing, so the RNG stream is unchanged
    # (out_scale=1.0 keeps legacy outputs byte-identical). Deep synthetic
    # chains need 1/sqrt(2*nlayers) (GPT-2-style) or the residual grows
    # until the fixed-point matvec y32 range overflows (found generating
    # token24 seed 2, 2026-07-25). Real trained weights don't need this.
    w = {
        "ln1": rng.normal(0, 0.1, H).astype(f32),       # zero-centered (1+w)
        "ln2": rng.normal(0, 0.1, H).astype(f32),
        "mlp": init_mlp_weights(rng),
        "type": layer_type,
    }
    if layer_type == "full_attention":
        w["attn"] = init_attn_weights(rng)
    else:
        w["dn"] = init_deltanet_weights(rng)
    if out_scale != 1.0:
        w["mlp"]["down"] = (w["mlp"]["down"] * out_scale).astype(f32)
        if layer_type == "full_attention":
            w["attn"]["o_proj"] = (w["attn"]["o_proj"] * out_scale).astype(f32)
        else:
            w["dn"]["out"] = (w["dn"]["out"] * out_scale).astype(f32)
    return w


# ----------------------------------------------------------------------
# decode-step blocks
# ----------------------------------------------------------------------
def attn_decode(xn, w, cache, pos):
    """xn: (H,) normed. cache: dict with k,v lists ((T,NKV,HD))."""
    qg = (w["q_proj"] @ xn).reshape(NQ, 2 * HD)
    q, gate = qg[:, :HD], qg[:, HD:]                    # (NQ,HD) each
    k = (w["k_proj"] @ xn).reshape(NKV, HD)
    v = (w["v_proj"] @ xn).reshape(NKV, HD)

    q = rmsnorm1p(q, w["q_norm"])
    k = rmsnorm1p(k, w["k_norm"])
    cos, sin = rope_cos_sin(pos)
    q = apply_rope(q, cos, sin)
    k = apply_rope(k, cos, sin)

    cache["k"].append(k)
    cache["v"].append(v)
    K = np.stack(cache["k"])                            # (T,NKV,HD)
    V = np.stack(cache["v"])

    group = NQ // NKV
    out = np.zeros((NQ, HD), dtype=f32)
    for h in range(NQ):
        kv = h // group
        scores = (K[:, kv, :] @ q[h]) * f32(1.0 / np.sqrt(HD))   # (T,)
        scores = scores - scores.max()
        e = np.exp(scores.astype(f32))
        p = e / e.sum()
        out[h] = p @ V[:, kv, :]
    out = out.reshape(NQ * HD) * sigmoid(gate.reshape(NQ * HD))
    return w["o_proj"] @ out


def deltanet_decode(xn, w, state):
    """state: dict conv (CONV_DIM, CONV_K-1) and S (LNH, LDK, LDV) fp32."""
    qkv = w["in_qkv"] @ xn                              # (6144,)
    z = (w["in_z"] @ xn).reshape(LNH, LDV)
    b = w["in_b"] @ xn
    a = w["in_a"] @ xn

    # depthwise causal conv over time (kernel 4): state holds last 3 inputs
    win = np.concatenate([state["conv"], qkv[:, None]], axis=1)   # (C,4)
    state["conv"] = win[:, 1:]
    qkv = silu(np.sum(win * w["conv_w"], axis=1))

    # q/k carry LNKH KEY heads, v carries LNH VALUE heads.  When they differ
    # (4B/9B: 16 key heads, 32 value heads) the vendor repeat_interleaves q and
    # k so value head h reads key head h // VREP
    # (vendor/modeling_qwen3_5.py:519-521).  VREP == 1 at 0.8B/2B, where this
    # is `.reshape(LNH, LDK)` exactly as before.
    q = qkv[:LKD].reshape(LNKH, LDK)
    k = qkv[LKD:2 * LKD].reshape(LNKH, LDK)
    v = qkv[2 * LKD:].reshape(LNH, LDV)
    if VREP > 1:
        q = np.repeat(q, VREP, axis=0)
        k = np.repeat(k, VREP, axis=0)

    beta = sigmoid(b)                                   # (LNH,)
    g = -np.exp(w["A_log"]) * softplus(a + w["dt_bias"])

    q = l2norm(q) * f32(1.0 / np.sqrt(LDK))
    k = l2norm(k)

    S = state["S"]                                      # (LNH, LDK, LDV)
    o = np.zeros((LNH, LDV), dtype=f32)
    for h in range(LNH):
        Sh = S[h] * np.exp(g[h])
        kv_mem = Sh.T @ k[h]                            # (LDV,)
        delta = (v[h] - kv_mem) * beta[h]
        Sh = Sh + np.outer(k[h], delta)
        o[h] = Sh.T @ q[h]
        S[h] = Sh

    # RMSNormGated per head: norm -> *w -> *silu(z)
    on = rmsnorm(o, w["norm_w"]) * silu(z)
    return w["out"] @ on.reshape(LVD)


def mlp(xn, w):
    return w["down"] @ (silu(w["gate"] @ xn) * (w["up"] @ xn))


def layer_decode(x, w, cache, pos):
    """One decoder layer, one token. x: (H,). Returns new x."""
    xn = rmsnorm1p(x, w["ln1"])
    if w["type"] == "full_attention":
        h = attn_decode(xn, w["attn"], cache, pos)
    else:
        h = deltanet_decode(xn, w["dn"], cache)
    x = x + h
    xn = rmsnorm1p(x, w["ln2"])
    return x + mlp(xn, w["mlp"])


def new_cache(layer_type):
    if layer_type == "full_attention":
        return {"k": [], "v": []}
    return {"conv": np.zeros((CONV_DIM, CONV_K - 1), dtype=f32),
            "S": np.zeros((LNH, LDK, LDV), dtype=f32)}


def _selftest():
    rng = np.random.default_rng(11)
    for lt in ["full_attention", "linear_attention"]:
        w = init_layer_weights(rng, lt)
        cache = new_cache(lt)
        x = rng.normal(0, 1, H).astype(f32)
        outs = []
        for t in range(8):
            x = layer_decode(x, w, cache, t)
            outs.append(x.copy())
            assert np.isfinite(x).all()
        # determinism + state dependence sanity
        cache2 = new_cache(lt)
        x2 = rng.normal(0, 1, H).astype(f32)  # different start
        for t in range(8):
            x2 = layer_decode(x2, w, cache2, t)
        assert not np.allclose(outs[-1], x2)
        print(f"{lt}: 8 decode steps, |x|_rms={np.sqrt(np.mean(outs[-1]**2)):.3f}")
    print("LAYER_REF SELFTEST PASS (float anchor; torch cross-check separate)")


if __name__ == "__main__":
    _selftest()
