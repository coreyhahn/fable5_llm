#!/usr/bin/env python3
"""Real Qwen3.5 checkpoint loader -> ref/layer_fixed.py weight dicts.

Which checkpoint is loaded follows ref/model_select.py (FABLE5_MODEL;
default 0.8b) — REPO_DIR and the config JSON both come from there.

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
from model_select import CONFIG_JSON, REPO_DIR, TAG             # noqa: E402

# "models--Qwen--Qwen3.5-0.8B" -> "Qwen/Qwen3.5-0.8B" (the huggingface-cli id)
REPO_ID = REPO_DIR[len("models--"):].replace("--", "/")
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


def find_checkpoints(path=None):
    """Absolute paths of the selected model's safetensors shards, in order.

    0.8B and 2B ship ONE shard; 4B ships 2 and 9B ships 4
    (`docs/QWEN35_NEXT_FEASIBILITY.md` §1).  The published names sort into
    shard order lexicographically (`…-00001-of-00004.safetensors`), and that
    order is what `SafeTensors` uses for its combined header digest, so it
    must stay deterministic — `sorted()`, never the glob's directory order.
    """
    if path:
        paths = [path] if isinstance(path, str) else list(path)
        for p in paths:
            if not os.path.exists(p):
                raise FileNotFoundError(f"explicit checkpoint path not found: {p}")
        return [os.path.abspath(p) for p in paths]
    tried = []
    for root in _hf_cache_roots():
        pat = os.path.join(root, REPO_DIR, "snapshots", "*", "*.safetensors")
        tried.append(pat)
        hits = sorted(glob.glob(pat))
        if hits:
            return [os.path.abspath(h) for h in hits]
    raise FileNotFoundError(
        f"{REPO_ID} safetensors not found in the HuggingFace cache "
        f"(FABLE5_MODEL={TAG}).\n"
        "Looked for:\n  " + "\n  ".join(tried) + "\n"
        f"Fetch it with:  huggingface-cli download {REPO_ID}")


def find_checkpoint(path=None):
    """First (or only) shard.  Callers that want the snapshot DIRECTORY — the
    tokenizer lives beside the weights — should keep using this; callers that
    read tensors want `find_checkpoints` / `SafeTensors`, which take the whole
    shard list."""
    return find_checkpoints(path)[0]


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


class _Shard:
    """Read-only mmap view of ONE .safetensors file (numpy only)."""

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

    def raw_bytes(self, name):
        ent = self.header[name]
        b0, b1 = ent["data_offsets"]
        return self._mm[self.data_start + b0:self.data_start + b1]

    def get(self, name, dtype=f32):
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


class SafeTensors:
    """Read-only mmap view of a checkpoint: ONE shard or a sharded set.

    Accepts a path or a list of paths.  A single-shard checkpoint behaves
    EXACTLY as before, `header_sha` included — 0.8B's and 2B's committed
    header digests are unchanged, which is what lets every existing json keep
    its provenance field.

    For a sharded checkpoint (4B: 2 shards, 9B: 4) `header_sha` is the sha256
    of the per-shard header digests joined by newlines, in shard order.  It is
    a DIFFERENT KIND of number from the single-shard one and is labelled as
    such wherever it is published; `shard_shas` carries the per-file digests so
    nothing is lost.
    """

    def __init__(self, path):
        paths = [path] if isinstance(path, str) else list(path)
        if not paths:
            raise ValueError("SafeTensors: no checkpoint path given")
        self.shards = [_Shard(p) for p in paths]
        self.paths = [s.path for s in self.shards]
        self.path = self.paths[0]
        self.shard_shas = [s.header_sha for s in self.shards]
        self.n_shards = len(self.shards)
        if self.n_shards == 1:
            self.header_sha = self.shard_shas[0]
        else:
            self.header_sha = hashlib.sha256(
                "\n".join(self.shard_shas).encode()).hexdigest()
        self.metadata = self.shards[0].metadata
        self.header = {}
        self._owner = {}
        for sh in self.shards:
            for k, ent in sh.header.items():
                if k in self._owner:
                    raise ValueError(
                        f"tensor {k!r} appears in two shards: "
                        f"{self._owner[k].path} and {sh.path}")
                self._owner[k] = sh
                self.header[k] = ent

    def __contains__(self, name):
        return name in self.header

    def keys(self):
        return self.header.keys()

    def shape(self, name):
        return tuple(self.header[name]["shape"])

    def raw_bytes(self, name):
        return self._owner[name].raw_bytes(name)

    def get(self, name, dtype=f32):
        """Tensor as `dtype` (default float32), always a fresh writable copy."""
        if name not in self._owner:
            raise KeyError(f"{name!r} not in "
                           f"{[os.path.basename(p) for p in self.paths]}")
        return self._owner[name].get(name, dtype)


# ----------------------------------------------------------------------
# config
# ----------------------------------------------------------------------
def load_config_full():
    """The whole config.json (the multimodal wrapper), not just text_config."""
    return json.load(open(CONFIG_JSON))


def load_config():
    return load_config_full()["text_config"]


HEAD_KEYS = ("lm_head.weight", TEXT_PREFIX + "lm_head.weight")


def config_says_tied():
    """`tie_word_embeddings` as the CONFIG states it — top level first.

    Reading only `text_config` is a trap: the 9B carries the flag `false` at
    the TOP level and OMITS it from `text_config`
    (`docs/QWEN35_NEXT_FEASIBILITY.md` §1.2), so a `text_config`-only lookup
    silently defaults to True on the one checkpoint where it is False.  The
    tensor is still the ground truth — `checkpoint_is_tied` cross-checks the
    two and refuses a disagreement.
    """
    full = load_config_full()
    if "tie_word_embeddings" in full:
        return bool(full["tie_word_embeddings"])
    return bool(full["text_config"].get("tie_word_embeddings", True))


def checkpoint_is_tied(st):
    """Ground truth: is there a separate LM head tensor?  Raises if the config
    flag and the checkpoint disagree — either direction is a real defect and
    neither should be papered over."""
    present = [k for k in HEAD_KEYS if k in st]
    tied = not present
    if tied != config_says_tied():
        raise ValueError(
            f"tie_word_embeddings disagreement: config says "
            f"tied={config_says_tied()} but the checkpoint carries "
            f"{present or 'no lm_head tensor'} (FABLE5_MODEL={TAG})")
    return tied, (present[0] if present else None)


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
             "head": (vocab,H) f32 or None, "tied": bool,
             "layer_types": [...], "path": str, "paths": [str],
             "header_sha256": str, "shard_sha256": [str], "config": dict}.

    layer_idxs limits which layers are materialised (memory: the full
    float32 model is ~2.0 GiB at 0.8B's 24 layers and ~16 GiB at 9B's 32,
    the embedding another ~1.0 / ~4.1 GiB); "layers" is then a dict
    {idx: wf} instead of a list.

    `head` is the LM head.  At 0.8B/2B/4B (`tie_word_embeddings: true`) it is
    a SEPARATE float copy of the embedding matrix — the hardware emits two
    independent images of it and every harness here keeps them apart.  At 9B
    it is the checkpoint's own top-level `lm_head.weight`.
    """
    cps = find_checkpoints(path)
    st = SafeTensors(cps)
    cfg = load_config()
    types = cfg["layer_types"]
    nl = cfg["num_hidden_layers"]
    assert len(types) == nl, "config layer_types/num_hidden_layers mismatch"

    if layer_idxs is None:
        layers = [load_layer(st, i, types[i], prefix) for i in range(nl)]
    else:
        layers = {i: load_layer(st, i, types[i], prefix) for i in layer_idxs}

    emb = head = None
    tied, head_key = checkpoint_is_tied(st)
    if with_emb:
        emb = st.get(f"{prefix}embed_tokens.weight")
        if emb.shape != (cfg["vocab_size"], LR.H):
            raise ValueError(f"embed_tokens shape {emb.shape} != "
                             f"{(cfg['vocab_size'], LR.H)}")
        # NOTE (Track L review, finding N7, 2026-08-26) — NOT fixed here, on
        # purpose.  `st.get` already returns "a fresh writable copy" (:220),
        # so `.copy()` makes a SECOND full float32 table whenever the head is
        # tied: vocab_size * H * 4 bytes = 0.95 GiB at 0.8B, **2.03 GB
        # (1.89 GiB) at 2B**, 2.54 GB at 4B.  (9B is untied, so it pays
        # nothing.)  That defeats the deliberate frees downstream —
        # `ref/gen_model_script.py:525` and `ref/seq_chat.py:1375` both set
        # `md["emb"] = None` to release the table, and `md["head"]` quietly
        # holds an identical one.  These are shipped paths.
        #
        # The obvious fix is `head = emb` (alias, no copy).  It is NOT taken
        # here because it is only safe if no consumer mutates either array in
        # place, and that is an audit of every load_model caller in ref/, sw/
        # and tb/scripts/ — migration work, not review work, and this track
        # does not own those callers.  Aliasing without that audit would turn
        # a memory cost into a silent correctness bug, which is the wrong
        # trade.  Recorded with its price so the migration can decide.
        head = emb.copy() if tied else st.get(head_key)
        if head.shape != (cfg["vocab_size"], LR.H):
            raise ValueError(f"{head_key or 'tied head'} shape {head.shape} != "
                             f"{(cfg['vocab_size'], LR.H)}")

    return {"layers": layers,
            "ln_f": st.get(f"{prefix}norm.weight"),
            "emb": emb,
            "head": head,
            "tied": tied,
            "head_key": head_key,
            "layer_types": list(types),
            "path": cps[0],
            "paths": cps,
            "header_sha256": st.header_sha,
            "shard_sha256": list(st.shard_shas),
            "config": cfg}


# ----------------------------------------------------------------------
# smoke test
# ----------------------------------------------------------------------
def _fmt(a):
    a = np.asarray(a, dtype=np.float64)
    return (f"shape={str(tuple(a.shape)):<16s} |max|={np.abs(a).max():9.4f} "
            f"rms={np.sqrt((a * a).mean()):9.5f}")


def _smoke():
    cps = find_checkpoints()
    st = SafeTensors(cps)
    tot = 0
    for i, cp in enumerate(cps):
        sz = os.path.getsize(os.path.realpath(cp))
        tot += sz
        print(f"checkpoint[{i}]: {cp}\n              {sz / 2**20:.1f} MiB  "
              f"header sha256 {st.shard_shas[i]}")
    print(f"{len(cps)} shard(s), {tot / 2**30:.2f} GiB")
    print(f"header sha256: {st.header_sha}"
          + ("" if st.n_shards == 1 else "   (combined over shards)"))
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
    tied, head_key = checkpoint_is_tied(st)
    print(f"  emb        {_fmt(emb)}  "
          + ("(tied: LM head == emb)" if tied else f"(UNTIED: head is {head_key})"))
    if not tied:
        print(f"  lm_head    {_fmt(st.get(head_key))}")

    # checksums: raw-byte digest (bit-exact identity of the tensors we use)
    h = hashlib.sha256()
    h.update(bytes(st.raw_bytes(f"{TEXT_PREFIX}embed_tokens.weight")))
    print(f"\n  emb raw-bytes sha256   {h.hexdigest()}")
    nl = cfg["num_hidden_layers"]
    h = hashlib.sha256()
    for i in range(nl):
        for k in sorted(st.keys()):
            if k.startswith(f"{TEXT_PREFIX}layers.{i}."):
                h.update(bytes(st.raw_bytes(k)))
    print(f"  {nl}-layer raw-bytes sha256 {h.hexdigest()}")
    print(f"  float64 sum(|emb|)     {np.abs(emb.astype(np.float64)).sum():.6e}")

    # structural cross-checks — against the CONFIG, not against 0.8B's numbers
    ndn = types.count("linear_attention")
    nfa = types.count("full_attention")
    assert len(types) == nl and ndn + nfa == nl
    for i in range(nl):
        p = f"{TEXT_PREFIX}layers.{i}"
        assert (f"{p}.linear_attn.A_log" in st) == (types[i] == "linear_attention")
    print(f"\nLOAD_QWEN35 SMOKE PASS ({nl} layers = {ndn} DeltaNet + {nfa} GQA, "
          f"H={LR.H} CONV_DIM={LR.CONV_DIM} LNH={LR.LNH}/LNKH={LR.LNKH}, "
          "shapes match layer_ref constants)")


if __name__ == "__main__":
    _smoke()
