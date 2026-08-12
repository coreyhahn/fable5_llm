#!/usr/bin/env python3
"""Real Qwen3.5-0.8B checkpoint loader -> ref/layer_fixed.py weight dicts.

Reads the bf16 safetensors shard straight out of the local HuggingFace
cache with numpy only (no torch, no safetensors package): a safetensors
file is

    [u64 LE header_len][header_len bytes of JSON][raw tensor bytes]

and every tensor's byte range is given by header[name]["data_offsets"]
relative to the end of the header.  BF16 is the top 16 bits of an IEEE
float32, so decoding is `(u16.astype(u32) << 16).view(f32)` — exact, no
rounding, no dependency.

Key mapping follows ref/validate_vs_torch.py:50-85 exactly (same field
names, same `conv1d.weight[:, 0, :]` slice, no transposes: HF nn.Linear
weights are already (out, in) and layer_ref does `W @ x`).  The only
difference is the checkpoint prefix: the released repo is the multimodal
`Qwen3_5ForConditionalGeneration`, so text-model keys live under
`model.language_model.` while validate_vs_torch instantiated a bare
`Qwen3_5TextModel` (keys `layers.N.…`).  `model.visual.*` and `mtp.*`
are deliberately ignored — vision tower and the multi-token-prediction
head are not part of the accelerator's dataflow.

Norm conventions (vendor/modeling_qwen3_5.py, verified):
  Qwen3_5RMSNorm      (ln1, ln2, q_norm, k_norm, model.norm) — weight is
                      ZERO-centered, scale = (1 + w).  layer_ref.rmsnorm1p /
                      layer_fixed.rmsnorm_fx(..., one_plus=True).
  Qwen3_5RMSNormGated (linear_attn.norm)                     — weight is
                      ONE-centered, used as-is.  layer_ref.rmsnorm /
                      layer_fixed.rmsnorm_fx(..., one_plus=False).

API
    load_model()                -> {"layers": [wf_0..wf_23], "ln_f", "emb", ...}
    load_model(layer_idxs=[3])  -> only those layers materialised
    load_layer(st, i)           -> one layer's wf dict
    python3 load_qwen35.py      -> smoke test (shapes + checksums)

`emb` is the tied embedding matrix, float32 (vocab, H).  It is used twice
downstream: as the int16 Q7.8 embedding table and, via
layer_fixed.quant_linear, as the LM head (`tie_word_embeddings: true`,
and the checkpoint indeed carries no separate lm_head.weight).
"""
import glob
import hashlib
import json
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layer_ref as LR                                          # noqa: E402

REPO_DIR = "models--Qwen--Qwen3.5-0.8B"
TEXT_PREFIX = "model.language_model."
f32 = np.float32


# ----------------------------------------------------------------------
# locating the checkpoint
# ----------------------------------------------------------------------
def _hf_cache_roots():
    env = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    roots = [env] if env else []
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        roots.append(os.path.join(hf_home, "hub"))
    roots.append(os.path.expanduser("~/.cache/huggingface/hub"))
    return [r for r in roots if r]


def find_checkpoint(path=None):
    """Absolute path of the Qwen3.5-0.8B safetensors shard (single file)."""
    if path:
        if not os.path.exists(path):
            raise FileNotFoundError(f"explicit checkpoint path not found: {path}")
        return os.path.abspath(path)
    tried = []
    for root in _hf_cache_roots():
        pat = os.path.join(root, REPO_DIR, "snapshots", "*", "*.safetensors")
        tried.append(pat)
        hits = sorted(glob.glob(pat))
        if hits:
            if len(hits) > 1:
                raise RuntimeError(
                    "expected ONE safetensors shard, found %d — sharded "
                    "checkpoints are not supported by this loader:\n  %s"
                    % (len(hits), "\n  ".join(hits)))
            return os.path.abspath(hits[0])
    raise FileNotFoundError(
        "Qwen3.5-0.8B safetensors not found in the HuggingFace cache.\n"
        "Looked for:\n  " + "\n  ".join(tried) + "\n"
        "Fetch it with:  huggingface-cli download Qwen/Qwen3.5-0.8B")


# ----------------------------------------------------------------------
# minimal numpy-only safetensors reader
# ----------------------------------------------------------------------
_DECODE = {
    "F32": (np.dtype("<f4"), 4),
    "F16": (np.dtype("<f2"), 2),
    "BF16": (np.dtype("<u2"), 2),
    "F64": (np.dtype("<f8"), 8),
}


def bf16_to_f32(u16):
    """Exact bf16 -> float32 (bf16 IS the high half of a float32)."""
    return (np.asarray(u16, dtype=np.uint16).astype(np.uint32) << 16).view(np.float32)


class SafeTensors:
    """Read-only mmap view of a .safetensors file (numpy only)."""

    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            (hlen,) = struct.unpack("<Q", f.read(8))
            raw = f.read(hlen)
        self.header_sha = hashlib.sha256(raw).hexdigest()
        hdr = json.loads(raw)
        self.metadata = hdr.pop("__metadata__", None)
        self.header = hdr
        self.data_start = 8 + hlen
        self._mm = np.memmap(path, dtype=np.uint8, mode="r")

    def __contains__(self, name):
        return name in self.header

    def keys(self):
        return self.header.keys()

    def shape(self, name):
        return tuple(self.header[name]["shape"])

    def raw_bytes(self, name):
        ent = self.header[name]
        b0, b1 = ent["data_offsets"]
        return self._mm[self.data_start + b0:self.data_start + b1]

    def get(self, name, dtype=f32):
        """Tensor as `dtype` (default float32), always a fresh writable copy."""
        if name not in self.header:
            raise KeyError(f"{name!r} not in {os.path.basename(self.path)}")
        ent = self.header[name]
        if ent["dtype"] not in _DECODE:
            raise NotImplementedError(f"dtype {ent['dtype']} for {name}")
        np_dt, esz = _DECODE[ent["dtype"]]
        shape = tuple(ent["shape"])
        n = int(np.prod(shape)) if shape else 1
        b0, b1 = ent["data_offsets"]
        assert b1 - b0 == n * esz, f"{name}: bad data_offsets"
        buf = self._mm[self.data_start + b0:self.data_start + b1].view(np_dt)
        arr = bf16_to_f32(buf) if ent["dtype"] == "BF16" else np.asarray(buf)
        return np.ascontiguousarray(arr.reshape(shape), dtype=dtype)


# ----------------------------------------------------------------------
# config
# ----------------------------------------------------------------------
def load_config():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "qwen3_5_0.8b_config.json")
    return json.load(open(p))["text_config"]


# ----------------------------------------------------------------------
# per-layer weight extraction (mirrors validate_vs_torch.py:50-85)
# ----------------------------------------------------------------------
def _dn_weights(st, p):
    return {
        "in_qkv":  st.get(f"{p}.linear_attn.in_proj_qkv.weight"),
        "in_z":    st.get(f"{p}.linear_attn.in_proj_z.weight"),
        "in_b":    st.get(f"{p}.linear_attn.in_proj_b.weight"),
        "in_a":    st.get(f"{p}.linear_attn.in_proj_a.weight"),
        "conv_w":  st.get(f"{p}.linear_attn.conv1d.weight")[:, 0, :],
        "dt_bias": st.get(f"{p}.linear_attn.dt_bias"),
        "A_log":   st.get(f"{p}.linear_attn.A_log"),
        "norm_w":  st.get(f"{p}.linear_attn.norm.weight"),
        "out":     st.get(f"{p}.linear_attn.out_proj.weight"),
    }


def _attn_weights(st, p):
    return {
        "q_proj": st.get(f"{p}.self_attn.q_proj.weight"),
        "k_proj": st.get(f"{p}.self_attn.k_proj.weight"),
        "v_proj": st.get(f"{p}.self_attn.v_proj.weight"),
        "o_proj": st.get(f"{p}.self_attn.o_proj.weight"),
        "q_norm": st.get(f"{p}.self_attn.q_norm.weight"),
        "k_norm": st.get(f"{p}.self_attn.k_norm.weight"),
    }


_EXPECT_COMMON = {
    "ln1": (LR.H,), "ln2": (LR.H,),
}
_EXPECT_MLP = {"gate": (LR.FFN, LR.H), "up": (LR.FFN, LR.H),
               "down": (LR.H, LR.FFN)}
_EXPECT_DN = {
    "in_qkv": (LR.CONV_DIM, LR.H), "in_z": (LR.LVD, LR.H),
    "in_b": (LR.LNH, LR.H), "in_a": (LR.LNH, LR.H),
    "conv_w": (LR.CONV_DIM, LR.CONV_K), "dt_bias": (LR.LNH,),
    "A_log": (LR.LNH,), "norm_w": (LR.LDV,), "out": (LR.H, LR.LVD),
}
_EXPECT_ATTN = {
    "q_proj": (2 * LR.NQ * LR.HD, LR.H), "k_proj": (LR.NKV * LR.HD, LR.H),
    "v_proj": (LR.NKV * LR.HD, LR.H), "o_proj": (LR.H, LR.NQ * LR.HD),
    "q_norm": (LR.HD,), "k_norm": (LR.HD,),
}


def _check(where, d, expect):
    for k, sh in expect.items():
        got = tuple(np.shape(d[k]))
        if got != sh:
            raise ValueError(f"{where}.{k}: shape {got}, expected {sh} "
                             f"(layer_ref constants)")


def load_layer(st, i, layer_type=None, prefix=TEXT_PREFIX):
    """One decoder layer as the dict layer_fixed.quant_layer expects."""
    types = load_config()["layer_types"]
    if layer_type is None:
        layer_type = types[i]
    p = f"{prefix}layers.{i}"
    has_dn = f"{p}.linear_attn.A_log" in st
    has_at = f"{p}.self_attn.q_proj.weight" in st
    want_dn = layer_type == "linear_attention"
    if want_dn != has_dn or want_dn == has_at:
        raise ValueError(
            f"layer {i}: config says {layer_type} but checkpoint has "
            f"linear_attn={has_dn} self_attn={has_at}")
    w = {
        "ln1": st.get(f"{p}.input_layernorm.weight"),
        "ln2": st.get(f"{p}.post_attention_layernorm.weight"),
        "mlp": {"gate": st.get(f"{p}.mlp.gate_proj.weight"),
                "up":   st.get(f"{p}.mlp.up_proj.weight"),
                "down": st.get(f"{p}.mlp.down_proj.weight")},
        "type": layer_type,
    }
    if want_dn:
        w["dn"] = _dn_weights(st, p)
        _check(f"layer{i}.dn", w["dn"], _EXPECT_DN)
    else:
        w["attn"] = _attn_weights(st, p)
        _check(f"layer{i}.attn", w["attn"], _EXPECT_ATTN)
    _check(f"layer{i}", w, _EXPECT_COMMON)
    _check(f"layer{i}.mlp", w["mlp"], _EXPECT_MLP)
    return w


def load_model(path=None, layer_idxs=None, with_emb=True, prefix=TEXT_PREFIX):
    """Full model in layer_fixed form.

    Returns {"layers": [...], "ln_f": (H,) f32, "emb": (vocab,H) f32 or None,
             "layer_types": [...], "path": str, "header_sha256": str,
             "config": dict}.

    layer_idxs limits which layers are materialised (memory: the full
    24-layer float32 model is ~2.0 GiB, the embedding another ~1.0 GiB);
    "layers" is then a dict {idx: wf} instead of a list.
    """
    cp = find_checkpoint(path)
    st = SafeTensors(cp)
    cfg = load_config()
    types = cfg["layer_types"]
    nl = cfg["num_hidden_layers"]
    assert len(types) == nl, "config layer_types/num_hidden_layers mismatch"

    if layer_idxs is None:
        layers = [load_layer(st, i, types[i], prefix) for i in range(nl)]
    else:
        layers = {i: load_layer(st, i, types[i], prefix) for i in layer_idxs}

    emb = None
    if with_emb:
        emb = st.get(f"{prefix}embed_tokens.weight")
        if emb.shape != (cfg["vocab_size"], LR.H):
            raise ValueError(f"embed_tokens shape {emb.shape} != "
                             f"{(cfg['vocab_size'], LR.H)}")
        if not cfg.get("tie_word_embeddings", True):
            raise ValueError("config says untied embeddings but this loader "
                             "returns the tied matrix as the LM head")
        for k in ("lm_head.weight", f"{prefix}lm_head.weight"):
            if k in st:
                raise ValueError(f"checkpoint carries {k}: embeddings are NOT "
                                 "tied, LM head must be loaded separately")

    return {"layers": layers,
            "ln_f": st.get(f"{prefix}norm.weight"),
            "emb": emb,
            "layer_types": list(types),
            "path": cp,
            "header_sha256": st.header_sha,
            "config": cfg}


# ----------------------------------------------------------------------
# smoke test
# ----------------------------------------------------------------------
def _fmt(a):
    a = np.asarray(a, dtype=np.float64)
    return (f"shape={str(tuple(a.shape)):<16s} |max|={np.abs(a).max():9.4f} "
            f"rms={np.sqrt((a * a).mean()):9.5f}")


def _smoke():
    cp = find_checkpoint()
    print(f"checkpoint: {cp}")
    print(f"            {os.path.getsize(os.path.realpath(cp)) / 2**20:.1f} MiB")
    st = SafeTensors(cp)
    print(f"header sha256: {st.header_sha}")
    nlm = sum(1 for k in st.keys() if k.startswith(TEXT_PREFIX))
    print(f"tensors: {len(st.header)} total, {nlm} under {TEXT_PREFIX!r} "
          f"(visual/mtp ignored)")

    cfg = load_config()
    types = cfg["layer_types"]
    dn_i = types.index("linear_attention")
    at_i = types.index("full_attention")

    for i in (dn_i, at_i):
        wf = load_layer(st, i)
        print(f"\n--- layer {i} ({wf['type']}) ---")
        print(f"  ln1        {_fmt(wf['ln1'])}")
        print(f"  ln2        {_fmt(wf['ln2'])}")
        for k in ("gate", "up", "down"):
            print(f"  mlp.{k:<6s} {_fmt(wf['mlp'][k])}")
        sub = "dn" if wf["type"] == "linear_attention" else "attn"
        for k in sorted(wf[sub]):
            print(f"  {sub}.{k:<7s} {_fmt(wf[sub][k])}")

    ln_f = st.get(f"{TEXT_PREFIX}norm.weight")
    print(f"\n  ln_f       {_fmt(ln_f)}")
    emb = st.get(f"{TEXT_PREFIX}embed_tokens.weight")
    print(f"  emb        {_fmt(emb)}  (tied: LM head == emb)")

    # checksums: raw-byte digest (bit-exact identity of the tensors we use)
    h = hashlib.sha256()
    h.update(bytes(st.raw_bytes(f"{TEXT_PREFIX}embed_tokens.weight")))
    print(f"\n  emb raw-bytes sha256   {h.hexdigest()}")
    h = hashlib.sha256()
    for i in range(cfg["num_hidden_layers"]):
        for k in sorted(st.keys()):
            if k.startswith(f"{TEXT_PREFIX}layers.{i}."):
                h.update(bytes(st.raw_bytes(k)))
    print(f"  24-layer raw-bytes sha256 {h.hexdigest()}")
    print(f"  float64 sum(|emb|)     {np.abs(emb.astype(np.float64)).sum():.6e}")

    # structural cross-checks
    assert len(types) == 24 and types.count("linear_attention") == 18 \
        and types.count("full_attention") == 6
    for i in range(24):
        p = f"{TEXT_PREFIX}layers.{i}"
        assert (f"{p}.linear_attn.A_log" in st) == (types[i] == "linear_attention")
    print("\nLOAD_QWEN35 SMOKE PASS (24 layers = 18 DeltaNet + 6 GQA, "
          "shapes match layer_ref constants)")


if __name__ == "__main__":
    _smoke()
