#!/usr/bin/env python3
"""Per-input-channel ACTIVATION SALIENCE for the V3 salience-weighted W4
quantizer (Track Q, task 8).

What it measures
----------------
For every matvec matrix the W4 engine covers, the mean absolute activation
seen on each of its K input channels:

    salience[k] = (1/T) * sum_t |x_t[k]|

collected with torch forward hooks on the real checkpoint, running the
CALIBRATION corpus (`ref/ppl_corpus_calib.txt`) through the model.  Nothing
about the model is changed: the hooks are read-only and the weights are the
plain bf16-upcast checkpoint (`perplexity_eval.build_model` with an EMPTY
injection plan, i.e. literally the bf16 anchor configuration).

Why: a weight column that multiplies a large activation propagates its
quantization error proportionally, so `layer_fixed.quant_linear_mse` can pick
each group's INT4 scale to minimise `||(W - Wq) diag(salience)||_F` instead of
plain `||W - Wq||_F`.  The wire format does not move — see that function.

    FABLE5_MODEL=2b python3 ref/calib_stats.py \
        --corpus ref/ppl_corpus_calib.txt --out ref/calib_stats_2b.npz

NEVER point --corpus at `ref/ppl_corpus_eval.txt`: that is the scored slice,
and calibrating on it would make every PPL number in Track Q self-referential.
The two files are disjoint by construction; `main()` refuses the eval corpus
by name as a second line of defence.

The .npz is REGENERABLE and is deliberately not committed; its sha256 and the
provenance of the run that made it are recorded in the task evidence.  The
loader below (`load`) is numpy-only, so `layer_fixed` can read the file
without dragging torch into the fixed-point path.

Key naming (`tensor_key`) is the HF module path with the
`model.language_model.` prefix and the trailing `.weight` stripped, e.g.
`layers.7.mlp.gate_proj`, plus the synthetic key `lm_head` for the LM head
(whose input is the final norm's output — see `--selftest` check C).

`lm_head` is synthetic in BOTH tie modes and for the same reason: the head is
not a submodule of the text model at all.  `perplexity_eval.build_model`
returns `(model, head_w, acct)` and computes `hs @ head_w.T` by hand, exactly
as the hardware does, so no forward hook can ever see it — which is why its
input is taken from the final norm's OUTPUT instead.  That is true whether
the head is a copy of `embed_tokens` (0.8B / 2B / 4B) or the checkpoint's own
`lm_head.weight` (9B, `tie_word_embeddings: false`).  The salience and the
Hessian for `lm_head` are therefore statistics of the head's INPUT, which is
the same vector in both modes; the head's own WEIGHTS never enter this file.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np                                              # noqa: E402

# ----------------------------------------------------------------------
# canonical tensor keys — the ONE mapping from layer_fixed's internal weight
# names to the HF module paths that the hooks below are keyed by.
# ----------------------------------------------------------------------
# layer_fixed sub-block -> {weight key: HF module suffix}
SUFFIX = {
    "attn": {"q_proj": "self_attn.q_proj", "k_proj": "self_attn.k_proj",
             "v_proj": "self_attn.v_proj", "o_proj": "self_attn.o_proj"},
    "dn": {"in_qkv": "linear_attn.in_proj_qkv",
           "in_z": "linear_attn.in_proj_z",
           "in_b": "linear_attn.in_proj_b",
           "in_a": "linear_attn.in_proj_a",
           "out": "linear_attn.out_proj"},
    "mlp": {"gate": "mlp.gate_proj", "up": "mlp.up_proj",
            "down": "mlp.down_proj"},
}
HEAD_KEY = "lm_head"

# ----------------------------------------------------------------------
# input SITES — the second-moment statistics of Track Q V4 (GPTQ-lite)
# ----------------------------------------------------------------------
# A per-matrix Hessian E[x x^T] depends only on that matrix's INPUT, and
# several matrices share one input (q/k/v see the attention block's input,
# gate/up see the MLP's, the four DeltaNet in_proj_* see the layer's).  One
# K x K matrix per distinct input site is therefore both smaller and exactly
# equivalent to one per matrix.  The sharing is DECLARED here and VERIFIED at
# collection time by tensor identity (`Collector._hess_acc` errors out if two
# members of a site are ever handed different tensors inside one forward), so
# a wrong entry in this table cannot silently weight a matrix by another
# block's statistics.
SITE_OF_SUFFIX = {
    "self_attn.q_proj": "attn_in",
    "self_attn.k_proj": "attn_in",
    "self_attn.v_proj": "attn_in",
    "self_attn.o_proj": "attn_o_in",
    "linear_attn.in_proj_qkv": "dn_in",
    "linear_attn.in_proj_z": "dn_in",
    "linear_attn.in_proj_b": "dn_in",
    "linear_attn.in_proj_a": "dn_in",
    "linear_attn.out_proj": "dn_out_in",
    "mlp.gate_proj": "mlp_in",
    "mlp.up_proj": "mlp_in",
    "mlp.down_proj": "mlp_down_in",
}
# npz namespaces.  `load()` returns ONLY the bare salience keys, so a file
# carrying these extra arrays is a drop-in for every V3 consumer.
HESS_PREFIX = "hess/"      # site -> float32 (K, K) = (1/T) sum_t x_t x_t^T
H2_PREFIX = "h2/"          # site -> float32 (K,)   = diag of the above


def tensor_key(sub, wkey, layer_idx):
    """('mlp', 'gate', 7) -> 'layers.7.mlp.gate_proj'."""
    try:
        suf = SUFFIX[sub][wkey]
    except KeyError:
        raise KeyError(f"no calibration key for {sub}.{wkey} — the W4 engine "
                       f"covers {sorted(SUFFIX)} and within them "
                       f"{sorted(SUFFIX.get(sub, {}))}") from None
    return f"layers.{int(layer_idx)}.{suf}"


def hess_key(key):
    """Tensor key -> the INPUT SITE whose Hessian that matrix consumes.

    'layers.7.mlp.up_proj' -> 'layers.7.mlp_in';  'lm_head' -> 'lm_head'.
    Matrices that share an input map to the same site (see SITE_OF_SUFFIX).
    """
    if key == HEAD_KEY:
        return HEAD_KEY
    if not key.startswith("layers."):
        raise KeyError(f"not a per-layer tensor key: {key!r}")
    idx, suf = key.split(".", 2)[1], key.split(".", 2)[2]
    try:
        return f"layers.{int(idx)}.{SITE_OF_SUFFIX[suf]}"
    except KeyError:
        raise KeyError(f"no input site for {key!r} — the W4 engine covers "
                       f"{sorted(set(SITE_OF_SUFFIX))}") from None


def load(path):
    """{key: float32[K]} from an .npz written by this module (numpy only).

    Metadata entries (keys starting with '_') and the V4 second-moment
    namespaces (`hess/`, `h2/`) are dropped — this returns exactly the V3
    salience vectors and nothing else, so a V4 file is a drop-in for a V3
    consumer.  Read the others with `meta()` / `load_h2()` / `HessStore`.
    """
    if not os.path.exists(path):
        raise SystemExit(f"FABLE5_CALIB_STATS / --calib-stats: no such file "
                         f"{path!r} — generate it with ref/calib_stats.py")
    with np.load(path, allow_pickle=False) as z:
        out = {k: np.asarray(z[k], dtype=np.float32)
               for k in z.files if not _is_aux(k)}
    if not out:
        raise SystemExit(f"{path}: no salience vectors in this npz")
    return out


def _is_aux(k):
    return (k.startswith("_") or k.startswith(HESS_PREFIX)
            or k.startswith(H2_PREFIX))


def load_h2(path):
    """{site: float32[K]} second moments E[x_k^2], or {} for a V3-only file.

    This is the DIAGONAL of the site's Hessian, stored (not recomputed) so
    that the diagonal-weighted quantizer and the GPTQ quantizer weight their
    scale searches by bit-identical numbers.
    """
    with np.load(path, allow_pickle=False) as z:
        return {k[len(H2_PREFIX):]: np.asarray(z[k], dtype=np.float32)
                for k in z.files if k.startswith(H2_PREFIX)}


class HessStore:
    """Lazy per-site Hessian reader + its GPTQ factorization, LRU(2).

    The full set is several GiB, so nothing is read until a matrix asks for
    it and at most two factorizations are kept alive.  `build_model` /
    `quantize_model` walk the matrices in sorted name order, which puts every
    input-sharing pair (mlp gate/up, the four DeltaNet in_proj_*, q/k/v with
    o_proj between them) inside a window of two — so LRU(2) turns 187 matrix
    lookups into one factorization per site.
    """

    def __init__(self, path, percdamp=0.01, maxcache=2):
        self.path = path
        self.percdamp = float(percdamp)
        self.maxcache = int(maxcache)
        self._z = np.load(path, allow_pickle=False)
        self.sites = sorted(k[len(HESS_PREFIX):] for k in self._z.files
                            if k.startswith(HESS_PREFIX))
        if not self.sites:
            raise SystemExit(
                f"{path} carries no {HESS_PREFIX}* arrays — regenerate it with "
                "`ref/calib_stats.py --hessian` for the GPTQ quantizer")
        self._cache = OrderedDict()

    def raw(self, site):
        """The (K, K) float64 Hessian for one site (never cached)."""
        return np.asarray(self._z[HESS_PREFIX + site], dtype=np.float64)

    def factor(self, key):
        """`gptq.HessFactor` for the matrix named `key` (via `hess_key`)."""
        site = hess_key(key)
        if site in self._cache:
            self._cache.move_to_end(site)
            return self._cache[site]
        if site not in self.sites:
            raise SystemExit(
                f"{self.path} has no Hessian for site {site!r} (needed by "
                f"{key!r}); it carries {len(self.sites)} sites — regenerate "
                "it with `ref/calib_stats.py --hessian` for THIS model")
        import gptq
        f = gptq.factor(self.raw(site), percdamp=self.percdamp, name=site)
        self._cache[site] = f
        while len(self._cache) > self.maxcache:
            self._cache.popitem(last=False)
        return f

    def close(self):
        self._cache.clear()
        self._z.close()


def meta(path):
    """Provenance dict recorded by `save` (model, corpus sha, n_tokens, ...)."""
    with np.load(path, allow_pickle=False) as z:
        if "_meta_json" not in z.files:
            return {}
        return json.loads(str(z["_meta_json"]))


def save(path, sal, metadata, hess=None):
    """Write the salience vectors (+ optional per-site Hessians) to an .npz.

    `hess` is {site: (K,K) float32}; its diagonal is ALSO written as the
    `h2/` second-moment vector so that every consumer of E[x^2] reads the
    same bytes the GPTQ factorization sees.  With `hess=None` the payload is
    exactly what V3 wrote.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    payload = {k: np.asarray(v, dtype=np.float32) for k, v in sal.items()}
    for site, H in (hess or {}).items():
        H = np.asarray(H, dtype=np.float32)
        payload[HESS_PREFIX + site] = H
        payload[H2_PREFIX + site] = np.ascontiguousarray(np.diag(H))
    payload["_meta_json"] = np.array(json.dumps(metadata, sort_keys=True))
    np.savez(path, **payload)


def expected_keys(n_layers, layer_types):
    """Every key the V3 quantizer will ask for, for this geometry."""
    keys = [HEAD_KEY]
    for i in range(n_layers):
        sub = "attn" if layer_types[i] == "full_attention" else "dn"
        for s in (sub, "mlp"):
            keys += [tensor_key(s, w, i) for w in SUFFIX[s]]
    return keys


# ----------------------------------------------------------------------
# collection
# ----------------------------------------------------------------------
class Collector:
    """Read-only forward hooks accumulating sum|x| per input channel.

    With `hessian=True` it ALSO accumulates sum_t x_t x_t^T per input SITE
    (Track Q V4).  That is a K x K matrix per site — several GiB at 2B — so
    it is strictly opt-in and the V3 path is untouched when it is off.
    """

    def __init__(self, model, prefix_strip="", hessian=False):
        import torch
        self.torch = torch
        self.sum = {}            # key -> float64[K]
        self.n = 0               # tokens seen
        self.handles = []
        self.model = model
        self.hess = {} if hessian else None      # site -> torch float32 (K,K)
        self.step = 0            # forward counter, for the identity check
        self._site_seen = {}     # site -> (step, data_ptr, shape)
        for name, mod in model.named_modules():
            if isinstance(mod, torch.nn.Linear):
                key = name[len(prefix_strip):] if prefix_strip else name
                # G2c — the untied-head collision.  `HEAD_KEY` is claimed
                # below by a hook on the final NORM, so an `nn.Linear` that
                # strips to the same key would register a SECOND hook under
                # it, and both would fire on one forward with the same vector
                # (a real `lm_head` Linear's input IS the norm's output).
                #
                # The two accumulators behave DIFFERENTLY under that, and the
                # difference is the reason this guard is here rather than
                # elsewhere:
                #   * the SALIENCE (`self.sum`) is a bare `+=` in `_acc`, so
                #     it comes out DOUBLED, silently, with nothing to notice;
                #   * the HESSIAN is already safe — `_hess_acc` keys on
                #     (step, data_ptr, shape) and RETURNS on the second call
                #     with the same tensor, or raises if the tensors differ.
                # So the exposure is the salience half only.  That is still a
                # silent factor of two on every `lm_head` weight the salient
                # quantizers use, which is enough.  (Corrected 2026-08-31 at
                # the T5 review: an earlier version of this comment claimed
                # the Hessian doubled too.  It does not.)
                #
                # It does not happen with `perplexity_eval.build_model`, which
                # keeps the head outside the module tree in both tie modes
                # (module docstring), and this refuses rather than trusting
                # that to stay true.
                if key == HEAD_KEY:
                    raise ValueError(
                        f"module {name!r} strips to the synthetic key "
                        f"{HEAD_KEY!r}, which this collector reserves for the "
                        f"final norm's OUTPUT.  Two hooks on one key would "
                        f"double every {HEAD_KEY!r} SALIENCE vector silently "
                        f"(the Hessian is deduped by _hess_acc's site guard).  "
                        f"Rename the key or hook the module instead of the "
                        f"norm — do not register both.")
                self.handles.append(
                    mod.register_forward_pre_hook(self._pre(key)))
        # the LM head is NOT a module here, tied or untied (perplexity_eval
        # computes `hs @ head_w.T` by hand, exactly as the HW does), so its
        # input is the final norm's OUTPUT — hook that instead.
        self.handles.append(model.norm.register_forward_hook(self._post(HEAD_KEY)))
        if hessian:
            # fires before every submodule of one forward, so `step` separates
            # forwards and the shared-input identity check below is exact
            self.handles.append(model.register_forward_pre_hook(self._bump))

    def _bump(self, mod, inp):
        self.step += 1

    def _acc(self, key, x):
        t = x.detach().reshape(-1, x.shape[-1])
        s = t.abs().sum(dim=0).double().cpu().numpy()
        cur = self.sum.get(key)
        self.sum[key] = s if cur is None else cur + s
        if self.hess is not None:
            self._hess_acc(key, x, t)

    def _hess_acc(self, key, x, t):
        """sum_t x x^T for `key`'s input site, ONCE per site per forward.

        The site table declares which matrices share an input; this verifies
        it: two members of one site that are handed different tensors inside
        the same forward is a hard error, not a double count.
        """
        try:
            site = hess_key(key)
        except KeyError:
            return                       # a Linear the W4 engine does not cover
        fid = (self.step, x.data_ptr(), tuple(x.shape))
        seen = self._site_seen.get(site)
        if seen is not None and seen[0] == self.step:
            if seen[1:] != fid[1:]:
                raise SystemExit(
                    f"site {site!r}: {key!r} was handed a DIFFERENT tensor "
                    f"{fid[1:]} than the earlier member of the same site "
                    f"{seen[1:]} in one forward — SITE_OF_SUFFIX claims they "
                    "share an input and they do not")
            return                       # already accumulated for this tensor
        self._site_seen[site] = fid
        H = self.hess.get(site)
        if H is None:
            K = t.shape[1]
            H = self.torch.zeros((K, K), dtype=self.torch.float32)
            self.hess[site] = H
        H.addmm_(t.t(), t)               # H += x^T x  (fused, no temporary)

    def _pre(self, key):
        def hook(mod, inp):
            self._acc(key, inp[0])
        return hook

    def _post(self, key):
        def hook(mod, inp, out):
            self._acc(key, out if not isinstance(out, tuple) else out[0])
        return hook

    def add_tokens(self, n):
        self.n += int(n)

    def close(self):
        for h in self.handles:
            h.remove()
        self.handles = []

    def salience(self):
        if self.n <= 0:
            raise SystemExit("collector saw no tokens")
        return {k: (v / self.n).astype(np.float32) for k, v in self.sum.items()}

    def hessians(self):
        """{site: float32 (K,K)} = (1/T) sum_t x_t x_t^T, or {} when off.

        Divided IN PLACE (these are gigabytes; a copy would double the peak),
        so the normalisation happens exactly once however often this is called.
        """
        if self.hess is None:
            return {}
        if self.n <= 0:
            raise SystemExit("collector saw no tokens")
        if not getattr(self, "_hess_normed", False):
            for v in self.hess.values():
                v.div_(self.n)
            self._hess_normed = True
        return {k: v.numpy() for k, v in self.hess.items()}


def run(model, ids, collector, window=512, batch=4, verbose=True):
    """Feed the corpus through the model in the SAME windowing as
    perplexity_eval.compute_ppl, so the activations the salience is measured
    on are the activations the PPL number is measured on."""
    import torch
    segs = [ids[i:i + window] for i in range(0, len(ids), window)]
    segs = [s for s in segs if len(s) >= 2]
    t0, i = time.time(), 0
    while i < len(segs):
        grp = [segs[i]]
        while len(grp) < batch and i + len(grp) < len(segs) \
                and len(segs[i + len(grp)]) == len(grp[0]):
            grp.append(segs[i + len(grp)])
        i += len(grp)
        inp = torch.tensor(np.asarray(grp, dtype=np.int64), dtype=torch.long)
        with torch.no_grad():
            model(input_ids=inp, use_cache=False)
        collector.add_tokens(inp.numel())
        if verbose:
            print(f"  window {i}/{len(segs)}  tokens={collector.n}  "
                  f"{time.time() - t0:.1f}s", flush=True)
    return collector


# ----------------------------------------------------------------------
def selftest():
    """Tiny synthetic model: keys, coverage, shapes and the head hook."""
    import perplexity_eval as PE
    import torch

    print("--- A: tensor_key round trip ---")
    assert tensor_key("mlp", "gate", 7) == "layers.7.mlp.gate_proj"
    assert tensor_key("dn", "in_qkv", 0) == "layers.0.linear_attn.in_proj_qkv"
    assert tensor_key("attn", "o_proj", 3) == "layers.3.self_attn.o_proj"
    for bad in (("mlp", "conv_w", 0), ("nope", "gate", 0)):
        try:
            tensor_key(*bad)
        except KeyError:
            pass
        else:
            raise AssertionError(f"tensor_key accepted {bad}")
    print("  names match the HF module paths; non-W4 keys rejected")

    print("--- B: hooks cover every key the V3 quantizer asks for ---")
    cfg = PE._tiny_cfg()
    src = PE._tiny_source(cfg)
    model, head_w, _ = PE.build_model(cfg, src, PE.parse_inject(""),
                                      verbose=False, check_shapes=False)
    col = Collector(model)
    ids = list(np.random.default_rng(11).integers(0, cfg.vocab_size, 130))
    run(model, ids, col, window=64, batch=2, verbose=False)
    col.close()
    sal = col.salience()
    want = expected_keys(cfg.num_hidden_layers, cfg.layer_types)
    missing = [k for k in want if k not in sal]
    assert not missing, f"hooks missed {missing}"
    print(f"  {len(want)} required keys present "
          f"({len(sal)} hooked in total, tokens={col.n})")

    print("--- C: shapes match K, values are finite and positive ---")
    params = dict(model.named_parameters())
    for k in want:
        if k == HEAD_KEY:
            K = head_w.shape[1]
        else:
            K = params[k + ".weight"].shape[1]
        v = sal[k]
        assert v.shape == (K,), (k, v.shape, K)
        assert np.all(np.isfinite(v)) and float(v.min()) >= 0.0, k
        assert float(v.max()) > 0.0, k
    # the head's salience must be the FINAL NORM's output magnitude
    with torch.no_grad():
        hs = model(input_ids=torch.tensor([ids[:64]], dtype=torch.long),
                   use_cache=False).last_hidden_state
    assert hs.shape[-1] == sal[HEAD_KEY].shape[0]
    print("  every vector is float32[K] of the matrix it belongs to")

    print("--- D: save/load round trip (numpy-only loader) ---")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "tiny.npz")
        save(p, sal, {"model_tag": "tiny", "n_tokens": col.n})
        back = load(p)
        assert set(back) == set(sal)
        for k in sal:
            assert np.array_equal(back[k], sal[k]), k
        assert meta(p)["n_tokens"] == col.n
        assert not any(k.startswith("_") for k in back)
    print("  metadata stays out of the salience dict")

    print("--- E: V4 Hessian — sites, shapes, and the sharing claim ---")
    for k in want:
        hess_key(k)                                   # every key has a site
    assert hess_key("layers.3.self_attn.q_proj") == \
        hess_key("layers.3.self_attn.k_proj") == "layers.3.attn_in"
    assert hess_key("layers.3.mlp.up_proj") == "layers.3.mlp_in"
    assert hess_key(HEAD_KEY) == HEAD_KEY
    for bad in ("layers.0.mlp.conv_w", "nonsense"):
        try:
            hess_key(bad)
        except KeyError:
            pass
        else:
            raise AssertionError(f"hess_key accepted {bad}")

    # collect WITH the Hessian, and independently recompute one site's from
    # raw captured activations — the sharing check inside _hess_acc fires as
    # a hard error if SITE_OF_SUFFIX is wrong, so reaching here is itself a
    # verification that q/k/v (and gate/up, and the four in_proj_*) share.
    model2, head2, _ = PE.build_model(cfg, src, PE.parse_inject(""),
                                      verbose=False, check_shapes=False)
    col2 = Collector(model2, hessian=True)
    probe = "layers.0.mlp.down_proj"
    raw = []
    h_raw = dict(model2.named_modules())[probe].register_forward_pre_hook(
        lambda m, i: raw.append(i[0].detach().reshape(-1, i[0].shape[-1]).clone()))
    run(model2, ids, col2, window=64, batch=2, verbose=False)
    h_raw.remove()
    col2.close()
    hess = col2.hessians()
    sal2 = col2.salience()
    sites = sorted({hess_key(k) for k in want})
    assert sorted(hess) == sites, (sorted(hess), sites)
    for k in want:
        assert hess[hess_key(k)].shape == (sal2[k].shape[0],) * 2, k
    X = torch.cat(raw, dim=0).double().numpy()
    ref_H = (X.T @ X) / col2.n
    got_H = hess[hess_key(probe)].astype(np.float64)
    rel = np.abs(got_H - ref_H).max() / np.abs(ref_H).max()
    assert rel < 1e-5, f"{probe}: Hessian differs from X^T X/T by {rel:.2e}"
    # the salience path must be untouched by the Hessian collection
    assert set(sal2) == set(sal)
    print(f"  {len(sites)} sites from {len(want)} tensors; "
          f"{probe} matches an independent X^T X/T to {rel:.2e}")

    print("--- F: h2 IS the stored diagonal; load()/HessStore split ---")
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "tinyh.npz")
        save(p, sal2, {"model_tag": "tiny", "hessian": True}, hess)
        back = load(p)
        assert set(back) == set(sal2), "load() leaked hess/ or h2/ keys"
        h2 = load_h2(p)
        assert sorted(h2) == sites
        for s in sites:
            assert np.array_equal(h2[s], np.diag(hess[s])), s
        st = HessStore(p)
        assert st.sites == sites
        assert np.array_equal(st.raw(hess_key(probe)).astype(np.float32),
                              hess[hess_key(probe)])
        f1 = st.factor(probe)
        assert st.factor(probe) is f1, "HessStore did not cache the factor"
        assert np.array_equal(f1.diag, np.diag(hess[hess_key(probe)]).astype(np.float64))
        st.close()
    print(f"  {len(h2)} h2 vectors == the stored Hessian diagonals, "
          "load() returns salience only")

    print("\nCALIB_STATS SELFTEST PASS")
    return 0


# ----------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", help="ref/ppl_corpus_calib.txt (the TRAIN slice)")
    ap.add_argument("--out", help="output .npz")
    ap.add_argument("--window", type=int, default=512)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--max-tokens", type=int, default=0, help="smoke runs only")
    ap.add_argument("--checkpoint")
    ap.add_argument("--attn-impl", default="eager")
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--allow-eval-corpus", action="store_true",
                    help="override the eval-corpus refusal (do not use for "
                         "anything that feeds a scored number)")
    ap.add_argument("--hessian", action="store_true",
                    help="ALSO collect the per-input-site second moment "
                         "E[x x^T] that the V4 GPTQ quantizer needs (several "
                         "GiB of npz, ~10x the collection time)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    import torch
    torch.set_grad_enabled(False)
    if a.threads:
        torch.set_num_threads(a.threads)

    if a.selftest:
        return selftest()
    if not (a.corpus and a.out):
        ap.error("--corpus and --out are required (or use --selftest)")
    if os.path.basename(a.corpus) == "ppl_corpus_eval.txt" \
            and not a.allow_eval_corpus:
        raise SystemExit(
            "--corpus is the EVAL slice; calibrating on the scored corpus "
            "would make every Track Q PPL number self-referential. Use "
            "ref/ppl_corpus_calib.txt.")

    import perplexity_eval as PE
    import load_qwen35 as LQ
    from model_select import TAG

    t_start = time.time()
    src = PE.CkptSource(a.checkpoint)
    cfg = PE.text_config(dict(LQ.load_config()), a.attn_impl)
    tok, snap = PE.get_tokenizer()
    corpus_sha = PE.sha256_file(a.corpus)
    ids = PE.load_corpus_ids(a.corpus, tok, a.max_tokens or None)

    print(f"model      FABLE5_MODEL={TAG}  {cfg.num_hidden_layers} layers  "
          f"H={cfg.hidden_size}  vocab={cfg.vocab_size}")
    print(f"checkpoint {src.path}"
          + ("" if src.st.n_shards == 1 else
             f"  ({src.st.n_shards} shards)")
          + f"\n           header sha256 {src.st.header_sha}"
          + ("" if src.st.n_shards == 1 else "  (combined over shards)")
          + f"\n           lm_head "
          + ("tied (a separate copy of embed_tokens)" if src.tied
             else f"UNTIED: {src.head_key}"))
    print(f"corpus     {a.corpus}\n           sha256 {corpus_sha}\n"
          f"           {len(ids)} tokens, window={a.window}, batch={a.batch}")
    print(f"torch {torch.__version__}  threads={torch.get_num_threads()}",
          flush=True)

    # the bf16 anchor configuration — an EMPTY injection plan, i.e. the same
    # float model perplexity_eval scores with --inject absent
    model, head_w, _ = PE.build_model(cfg, src, PE.parse_inject(""),
                                      verbose=True)
    t_model = time.time() - t_start

    col = Collector(model, hessian=a.hessian)
    nmod = len(col.handles) - (2 if a.hessian else 1)
    print(f"  hooked {nmod} nn.Linear + the final norm for {HEAD_KEY}"
          + ("  + the model itself (forward counter for the Hessian "
             "shared-input check)" if a.hessian else ""), flush=True)
    t0 = time.time()
    run(model, ids, col, a.window, a.batch)
    col.close()
    sal = col.salience()
    hess = col.hessians()
    t_run = time.time() - t0

    want = expected_keys(cfg.num_hidden_layers, list(cfg.layer_types))
    missing = [k for k in want if k not in sal]
    if missing:
        raise SystemExit(f"hooks missed {len(missing)} required tensors, "
                         f"e.g. {missing[:4]}")
    params = dict(model.named_parameters())
    for k in want:
        K = head_w.shape[1] if k == HEAD_KEY else params[k + ".weight"].shape[1]
        if sal[k].shape != (K,):
            raise SystemExit(f"{k}: salience {sal[k].shape} != (K={K},)")
        if not (np.all(np.isfinite(sal[k])) and float(sal[k].max()) > 0.0):
            raise SystemExit(f"{k}: salience is not finite/positive")
    if a.hessian:
        want_sites = sorted({hess_key(k) for k in want})
        miss = [s for s in want_sites if s not in hess]
        if miss:
            raise SystemExit(f"Hessian hooks missed {len(miss)} sites: {miss[:4]}")
        for k in want:
            site, K = hess_key(k), sal[k].shape[0]
            if hess[site].shape != (K, K):
                raise SystemExit(f"{k}: Hessian {hess[site].shape} for site "
                                 f"{site} != (K={K}, K)")
            d = np.diag(hess[site])
            if not (np.all(np.isfinite(hess[site])) and float(d.min()) >= 0.0):
                raise SystemExit(f"{site}: Hessian is not finite/PSD-diagonal")
        print(f"  {len(want_sites)} input sites carry a Hessian "
              f"({sum(h.nbytes for h in hess.values()) / 2**30:.2f} GiB)",
              flush=True)

    metadata = {
        "model_tag": TAG, "checkpoint": src.path,
        "checkpoint_header_sha256": src.st.header_sha,
        "corpus": os.path.relpath(a.corpus, os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))),
        "corpus_sha256": corpus_sha, "n_corpus_tokens": len(ids),
        "n_tokens_hooked": col.n, "window": a.window, "batch": a.batch,
        "n_layers": cfg.num_hidden_layers, "hidden_size": cfg.hidden_size,
        "n_tensors": len(sal), "n_required": len(want),
        "tokenizer_snapshot": snap, "torch": torch.__version__,
        "seconds_build": t_model, "seconds_collect": t_run,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "hessian": bool(a.hessian), "n_sites": len(hess),
        "host": __import__("socket").gethostname(),
    }
    save(a.out, sal, metadata, hess or None)
    print(f"\n{len(sal)} salience vectors ({len(want)} required) over "
          f"{col.n} tokens in {t_run:.1f}s")
    # a compact fingerprint of the DYNAMIC RANGE the weighting will act on
    for k in (want[1], want[-1], HEAD_KEY):
        v = sal[k]
        print(f"  {k:<40s} K={v.size:<5d} mean={v.mean():.4g} "
              f"max/mean={v.max() / v.mean():.1f} "
              f"p99/median={np.percentile(v, 99) / np.median(v):.1f}")
    print(f"npz -> {a.out}  ({os.path.getsize(a.out) / 2**20:.1f} MiB)")
    h = hashlib.sha256()
    with open(a.out, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    print(f"sha256 {h.hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
