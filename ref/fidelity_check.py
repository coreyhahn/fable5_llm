#!/usr/bin/env python3
"""ref/fidelity_check.py — how CLOSE is the fixed-point pipeline to the model?

Stage-5 fidelity workstream.  Bit-exactness (RTL == reference) is already
proven by the sim/HW gates; this file measures the OTHER axis: how far the
frozen fixed-point formats move the model away from its bf16 self.

    golden   : the real Qwen3.5-0.8B run through transformers
               (Qwen3_5TextModel, weights = the checkpoint's bf16 upcast
               EXACTLY to float32, math in float32) -- phase `--golden`,
               needs torch; result is cached so the rest runs with numpy
               only.
    fixed    : ref/layer_fixed.py, the production quantizer + decode path,
               exactly what gen_model_script.py emits into the script
               (embedding lookup -> 24 layers -> ln_f at Q3.12 via vecnorm
               mode 1 -> DYNQ8 -> full-vocab W4 LM head -> argmax).

Both are run on the four committed prompts of gen_model_script.PROMPTS for
P prefill + (ntok-1) generated steps.  The fixed-point run is TEACHER-FORCED
onto the golden token sequence so that step i of both models sees the same
prefix and the comparison is well defined; a second, FREE-RUNNING pass
reproduces what the generator actually emits (the decoded text).

Metrics per prompt/step
    top1      fixed-point argmax == golden argmax
    rank      rank of the golden token inside the fixed-point logits (0 = top)
    top5      |top5(fixed) & top5(golden)|

Knobs under test (see the stage-5 fidelity report)
    --res-scale S   multiply the EMBEDDING TABLE and every residual-adding
                    projection (attn.o_proj / dn.out / mlp.down, all 24
                    layers) by S before quantizing.  Under RMSNorm this
                    scales the whole residual stream and is EXACTLY
                    invariant in float (every norm input and the final
                    argmax are unchanged); in fixed point it buys log2(S)
                    bits of residual resolution at the cost of int16
                    headroom.  Accepts a comma list to sweep.
    --qfix 0,1      opt-in W4 group-scale exponent tightening (see
                    layer_fixed.quant_linear(tighten_e=True)); only defined
                    for the max-rule quantizer, so it needs --mse 0.
    --mse 0,1       MSE-optimal W4 group scale (layer_fixed.quant_linear_mse).
                    DEFAULT 1 = the production quantizer since Phase 1A; 0
                    is the historical max|W_g|/7 rule.
    --w8            V5 (gate D): quantize every matvec weight — all 24
                    layers plus the full-vocab LM head — to the 8-bit wire
                    format (w4a8_ref.quantize_weights8 / row_stride8, SHAPE
                    bit 29) instead of W4.  WIRE-EXACT like --wire-group:
                    the real quantizer and the real fixed-point datapath, so
                    the score is what a W8 DDR image gets on hardware.  The
                    embedding table (int16) and the conv window (Q13) are
                    not matvec weights and do not move.  W8 is g128-cadence
                    only and has one group-scale rule, so it refuses
                    --wire-group 64, --mse 0, --qfix 1 and the W4-only
                    attribution modes rather than ignoring them.
                        fidelity_check.py --w8 --res-scale 4
    --wire-group    128 (default, the shipped format) and/or 64 = the v2 row
        128,64      format (w4a8_ref module header: same weight beats, one
                    uint16 scale per 64 weights, ceil((K/64)/32) scale beats,
                    SHAPE bit 28).  This is WIRE-EXACT: the real quantizer
                    and the real fixed-point datapath, so the score is what a
                    g=64 DDR image gets on hardware.  Do not confuse it with
                    --w4-group, which is a FLOAT-ONLY dequant probe usable
                    only under --ablate (it can model g=32, which has no
                    wire format).

The production configuration since Phase 1A of docs/FIDELITY_REDESIGN.md is
simply the default one at --res-scale 8:
    fidelity_check.py --res-scale 8 --free-ntok 12
i.e. no --diag, no flags: layer_fixed's own defaults (block-floating DN
output, script-side gated norm with the reference eps, DN_NORM_F = 11) plus
the mse W4 rule.  That measures 15/24 top-1, rank median 0.

Attribution modes (these answer "what is actually broken", and they are the
reason this file exists rather than a one-off script)
    --ablate        float-only decomposition: layer_ref with the EXACT
                    checkpoint weights, then with the W4-dequantized ones.
                    Separates model/anchor error from W4 weight error from
                    fixed-point datapath error.
    --trace         per-layer relative RMS error of the residual, fixed-point
                    vs float-with-W4-weights, on the same tokens.
    --blocks N      per-block probe of layer N with the SAME input and the
                    SAME (dequantized) weights on both sides — pure datapath
                    loss, block by block, plus a grid over the two SCRIPT-SIDE
                    DeltaNet output-alignment immediates.
    --diag k1,k2    re-run the end-to-end metric with one frozen fixed-point
                    limit RELAXED (DIAGS below): gate ports, S_F, the DeltaNet
                    output alignment.  Not RTL-legal — it says which RTL change
                    would be worth un-freezing.  ONE exception:
                    --diag base,seqnorm scores the SEQUENCER datapath
                    (docs/SEQ_ISA.md) — the DeltaNet gated-norm scale computed
                    on chip by the integer vecnorm EPS-NORM mode instead of by
                    the host in float64 — against the identical baseline in
                    the same process.  That IS the RTL spec, so its number is
                    the fidelity cost of moving the norm on chip.

Usage
    # once, needs torch+transformers (system python3 on darthplagueis):
    python3 fidelity_check.py --golden
    # then, numpy only (.venv on darthplagueis, /home/cah/venvs/fable5_np
    # on snoke — both give bit-identical results):
    .venv/bin/python fidelity_check.py --res-scale 1,4,8,16
    .venv/bin/python fidelity_check.py --ablate
"""
import argparse
import hashlib
import json
import os
import socket
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REF = os.path.dirname(os.path.abspath(__file__))
DEF_CACHE = os.path.join(REF, "..", "tb", "scripts_scratch", "golden_bf16.npz")
TOPK = 64                      # golden top-k retained in the cache


# ======================================================================
# G1 — the QUANTIZED-WEIGHT CACHE, and why it exists
# ======================================================================
# A 9B W4+GPTQ point spends 10,180.9 s quantizing 32 layers and 1,309.5 s on
# the LM head before it takes a single step (`evidence/qwen_next/ladder/
# fixed_9b_w4g128gptq.log:12`, `:15`).  G1 sweeps a DeltaNet STATE law, which
# is a decode-time container: it cannot reach the quantizer.  Paying 3.2 h per
# setting to re-derive the same bytes is the cost the spec's G1 "Cost"
# paragraph tells this gate to remove FIRST, before spending a full point.
#
# The cache is keyed by EVERYTHING the quantized artifacts depend on, and the
# state law and the residual binary point are deliberately NOT in the key —
# that is the claim.  It is not left as a claim: `--wq-cache-verify <i>`
# re-quantizes layer <i> live under the new setting and requires it to be
# BYTE-IDENTICAL to the cached one.
#
# Two properties on purpose:
#  * the key includes a sha256 over the ref/ sources that DEFINE the
#    quantizer, so a numeric-path change (e.g. a concurrent task editing
#    layer_fixed.py) MISSES the cache loudly instead of silently mixing two
#    numeric paths inside one comparison;
#  * `fidelity_check.py` itself is NOT in that source list.  Its contribution
#    to the quantized bytes is the ARGUMENTS, and those are all in the key
#    explicitly; hashing it would invalidate an 3.2 h artifact every time a
#    print statement moved.
_WQ_SOURCES = ("layer_fixed.py", "w4a8_ref.py", "gptq.py", "fixedpoint.py",
               "calib_stats.py", "gen_model_script.py", "load_qwen35.py",
               "model_select.py", "layer_ref.py")
_WQ_STATE = {"quantized": 0, "hits": 0, "misses": 0, "verified": None,
             "src_sha": None}


def _wq_source_sha():
    """sha256 of the quantizer sources, computed ONCE and memoized.

    Once, deliberately: the key has to describe the code THIS PROCESS
    imported.  Re-reading the files later would let a concurrent edit relabel
    a cache entry with a source it was not produced from — the one failure
    mode that would silently mix two numeric paths inside one comparison.
    """
    if _WQ_STATE.get("src_sha") is None:
        h = hashlib.sha256()
        for f in _WQ_SOURCES:
            p = os.path.join(REF, f)
            h.update(f.encode())
            with open(p, "rb") as fh:
                h.update(fh.read())
        _WQ_STATE["src_sha"] = h.hexdigest()
    return _WQ_STATE["src_sha"]


def _wq_key(kind, md, res_scale, tighten_e, mse_scale, g, w8):
    """Everything the quantized artifacts depend on.  NOT the state law."""
    import layer_fixed as LF
    import model_select as MS
    k = {"kind": kind, "model": MS.TAG,
         "checkpoint": md["header_sha256"],
         "w8": bool(w8), "g": int(g), "mse_scale": bool(mse_scale),
         "tighten_e": bool(tighten_e),
         "calib_stats": LF.CALIB_STATS or None,
         "calib_mode": LF.CALIB_MODE if LF.CALIB_STATS else None,
         "calib_sha256": (_sha256_file(LF.CALIB_STATS)
                          if LF.CALIB_STATS else None),
         "src_sha256": _wq_source_sha()}
    if kind == "layers":
        # the LM head does not see res_scale; the DN `out` matrix does
        # (`layer_fixed.res_scaled`), so only the layers key carries it
        k["res_scale"] = float(res_scale)
    return k


def _wq_path(cachedir, key):
    digest = hashlib.sha256(
        json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]
    return os.path.join(cachedir, f"wq_{key['kind']}_{key['model']}_"
                                  f"{digest}.pkl")


def _wq_load(cachedir, key, what):
    """Return the cached payload, or None (and say why) on a miss."""
    import pickle
    if not cachedir:
        return None
    p = _wq_path(cachedir, key)
    if not os.path.exists(p):
        _WQ_STATE["misses"] += 1
        print(f"    wq-cache MISS  {what}: no {os.path.basename(p)}",
              flush=True)
        return None
    t0 = time.time()
    with open(p, "rb") as f:
        blob = pickle.load(f)
    if blob.get("key") != key:
        # cannot happen through the path digest, but a digest is not a proof
        _WQ_STATE["misses"] += 1
        print(f"    wq-cache MISS  {what}: key mismatch in {p}", flush=True)
        return None
    _WQ_STATE["hits"] += 1
    print(f"    wq-cache HIT   {what}: {os.path.basename(p)} "
          f"({os.path.getsize(p) / 2**30:.2f} GiB, {time.time() - t0:.1f}s)",
          flush=True)
    return blob["payload"]


def _wq_save(cachedir, key, payload, what):
    import pickle
    if not cachedir:
        return
    os.makedirs(cachedir, exist_ok=True)
    p = _wq_path(cachedir, key)
    st = os.statvfs(cachedir)
    free = st.f_bavail * st.f_frsize / 2**30
    if free < 20.0:
        print(f"    wq-cache SKIP save ({what}): only {free:.1f} GiB free in "
              f"{cachedir}", flush=True)
        return
    t0 = time.time()
    tmp = p + f".tmp{os.getpid()}"
    with open(tmp, "wb") as f:
        pickle.dump({"key": key, "payload": payload}, f, protocol=5)
    os.replace(tmp, p)
    print(f"    wq-cache SAVE  {what}: {os.path.basename(p)} "
          f"({os.path.getsize(p) / 2**30:.2f} GiB, {time.time() - t0:.1f}s)",
          flush=True)


def _wq_same(a, b, path="q"):
    """Byte-equality of two quantized artifacts (nested dicts of arrays)."""
    if isinstance(a, dict) and isinstance(b, dict):
        if sorted(a) != sorted(b):
            return False, f"{path}: keys {sorted(a)} != {sorted(b)}"
        for k in sorted(a):
            ok, why = _wq_same(a[k], b[k], f"{path}.{k}")
            if not ok:
                return False, why
        return True, ""
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return False, f"{path}: len {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            ok, why = _wq_same(x, y, f"{path}[{i}]")
            if not ok:
                return False, why
        return True, ""
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        a_, b_ = np.asarray(a), np.asarray(b)
        if a_.dtype != b_.dtype or a_.shape != b_.shape:
            return False, (f"{path}: {a_.dtype}{a_.shape} != "
                           f"{b_.dtype}{b_.shape}")
        if not np.array_equal(a_, b_):
            n = int((a_ != b_).sum())
            return False, f"{path}: {n}/{a_.size} elements differ"
        return True, ""
    return (a == b), ("" if a == b else f"{path}: {a!r} != {b!r}")


# ======================================================================
# phase 1 — bf16 golden (torch)
# ======================================================================
def build_golden(prompt_ids, ntok, out_path):
    import torch
    from transformers.models.qwen3_5 import Qwen3_5TextConfig, Qwen3_5TextModel
    import load_qwen35 as LQ

    torch.set_grad_enabled(False)
    cps = LQ.find_checkpoints()
    cp = cps[0]
    st = LQ.SafeTensors(cps)
    cfgd = dict(LQ.load_config())
    allowed = Qwen3_5TextConfig().to_dict()
    cfg = Qwen3_5TextConfig(**{k: v for k, v in cfgd.items()
                               if k in allowed or k == "rope_parameters"})
    cfg._attn_implementation = "eager"
    cfg.dtype = "float32"
    print(f"golden: {cp}" + (f"  (+{len(cps) - 1} more shards)" if len(cps) > 1 else "")
          + f"\n  header sha256 {st.header_sha}\n"
          f"  {cfg.num_hidden_layers} layers vocab={cfg.vocab_size} "
          f"torch={torch.__version__}", flush=True)

    t0 = time.time()
    try:
        from transformers.modeling_utils import no_init_weights
        with no_init_weights():
            model = Qwen3_5TextModel(cfg)
    except Exception:                                     # pragma: no cover
        model = Qwen3_5TextModel(cfg)
    model = model.eval().float()
    pref = LQ.TEXT_PREFIX
    sd = {k[len(pref):]: torch.from_numpy(st.get(k))
          for k in st.keys() if k.startswith(pref)}
    missing, unexpected = model.load_state_dict(sd, strict=False)
    missing = [m for m in missing if "inv_freq" not in m]
    if missing or unexpected:
        raise SystemExit(f"state_dict mismatch: missing={missing[:8]} "
                         f"unexpected={unexpected[:8]}")
    # the LM head: the tied embedding matrix at 0.8B/2B/4B, the checkpoint's
    # own top-level lm_head.weight at 9B (which lives OUTSIDE the text prefix
    # and so is not in `sd` at all)
    tied, head_key = LQ.checkpoint_is_tied(st)
    emb_w = sd["embed_tokens.weight"] if tied \
        else torch.from_numpy(st.get(head_key))
    print(f"  lm_head: {'tied (== embed_tokens)' if tied else head_key}")
    print(f"  model built + loaded in {time.time() - t0:.1f}s", flush=True)

    out = {}
    for pseed, ids in sorted(prompt_ids.items()):
        nsteps = len(ids) + ntok - 1
        seq = list(ids)
        argmax, topk_i, topk_v = [], [], []
        for t in range(nsteps):
            inp = torch.tensor([seq[:t + 1]], dtype=torch.long)
            hs = model(input_ids=inp, use_cache=False).last_hidden_state
            logits = (hs[0, -1] @ emb_w.T).float()
            v, i = torch.topk(logits, TOPK)
            am = int(i[0])
            argmax.append(am)
            topk_i.append(i.numpy().astype(np.int64))
            topk_v.append(v.numpy().astype(np.float32))
            if t + 1 >= len(ids):
                seq.append(am)
            print(f"  p{pseed} step {t}: in={seq[t]:6d} argmax={am:6d} "
                  f"logit={float(v[0]):+.4f}", flush=True)
        out[f"p{pseed}_argmax"] = np.array(argmax, dtype=np.int64)
        out[f"p{pseed}_seq"] = np.array(seq[:nsteps], dtype=np.int64)
        out[f"p{pseed}_topk_i"] = np.stack(topk_i)
        out[f"p{pseed}_topk_v"] = np.stack(topk_v)
    out["meta"] = np.array([ntok, TOPK], dtype=np.int64)
    out["header_sha256"] = np.array(st.header_sha)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    np.savez(out_path, **out)
    print(f"golden cache -> {out_path}")
    return out


# ======================================================================
# phase 2 — fixed-point pipeline
# ======================================================================
def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def quantize_model(md, res_scale=1.0, tighten_e=False, mse_scale=False,
                   verbose=True, g=128, w8=False):
    """The production quantizer, layer by layer, freeing floats as we go.

    `g` is the W4 WIRE group size (128 legacy / 64 = the v2 row format).
    This is the real quantizer, so a g=64 run here is bit-exactly what a
    g=64 DDR image holds — unlike `w4_roundtrip`, which is a float-only probe.

    `w8` (V5) puts every matvec matrix of every layer in the 8-bit weight
    format (`layer_fixed.quant_linear_w8` -> `w4a8_ref.quantize_weights8`).
    Same statement as above: it is the real quantizer and the real
    fixed-point datapath, so the score is what a W8 DDR image gets on
    hardware.  The embedding table (int16) and the conv window (Q13) are
    NOT matvec weights and are untouched.

    `layer_idx` is handed to `quant_layer` so that, when FABLE5_CALIB_STATS
    is set, each matrix gets its own activation salience (Track Q V3).  With
    the env var unset it is ignored and this call is byte-identical to before.
    """
    import layer_fixed as LF
    layers = []
    t0 = time.time()
    # G1: the weight-quantization STAGE entry counter.  The cost argument the
    # gate rests on is "this happens once per process"; that is asserted, not
    # assumed (see main()'s summary line and the json's `_wq`).
    _WQ_STATE["quantized"] += 1
    for i, lt in enumerate(md["layer_types"]):
        wf = md["layers"][i]
        layers.append(LF.quant_layer(wf, res_scale=res_scale,
                                     tighten_e=tighten_e,
                                     mse_scale=mse_scale, g=g, layer_idx=i,
                                     w8=w8))
    if verbose:
        print(f"    quantized {len(layers)} layers in {time.time() - t0:.1f}s",
              flush=True)
    return layers


class FxRunner:
    """Full-model fixed-point decode, mirroring gen_model_script.main()."""

    def __init__(self, layers_q, layer_types, emb_q, head, ln_f_q12):
        import layer_fixed as LF
        self.LF = LF
        self.layers_q = layers_q
        self.types = layer_types
        self.emb_q = emb_q
        self.head = head
        self.ln_f_q12 = ln_f_q12
        self.reset()

    def reset(self):
        LF = self.LF
        self.caches = [LF.new_cache_fx(t) for t in self.types]
        self.resid_max = 0
        self.resid_clip = 0

    def step(self, tok, t):
        import fixedpoint as fp
        from w4a8_ref import matvec_y32, matvec_y32_w8
        LF = self.LF
        I64 = np.int64
        x = self.emb_q[tok].astype(I64)
        for i, qw in enumerate(self.layers_q):
            x = LF.layer_decode_fx(x, qw, self.caches[i], t)
            self.resid_max = max(self.resid_max, int(np.abs(x).max()))
            self.resid_clip += int(((x >= 32767) | (x <= -32768)).sum())
        # ln_f: pre-folded (1+w) at Q3.12, vecnorm mode 1 (plain multiplier)
        xn = LF.rmsnorm_fx(x, self.ln_f_q12, LF.RS_F, False)
        x8, _e = fp.dyn_quant_i8(xn)
        h = self.head
        # the LM head is a matvec weight like any other: W4 nibbles or, at
        # V5, W8 bytes.  `qw_codes` is the ONE place that knows which key
        # carries which, so this row loop has no format knowledge of its own.
        hw, h_w8 = LF.qw_codes(h)
        mv = matvec_y32_w8 if h_w8 else matvec_y32
        rows = hw.shape[0]
        parts = []
        for r0 in range(0, rows, 8192):
            r1 = min(r0 + 8192, rows)
            parts.append(mv(hw[r0:r1], h["m"][r0:r1], h["sh"],
                            x8, g=h.get("g", 128)).astype(np.int64))
        return np.concatenate(parts)          # y32; argmax-equivalent logits


def dequant_w4(q):
    """The float matrix the W4 image actually represents (any group size)."""
    N, K = q["w4"].shape
    NG = q["m"].shape[1]              # = K // g; g travels in q["g"]
    g = K // NG
    assert g * NG == K and g == int(q.get("g", g))
    eff = q["m"].astype(np.float64) * np.exp2(q["e"] - 15)
    return (q["w4"].reshape(N, NG, g).astype(np.float64)
            * eff[:, :, None]).reshape(N, K).astype(np.float32)


def w4_roundtrip(Wf, group=128, rule="max", nalpha=17, amin=0.55):
    """FLOAT-ONLY W4 round-trip: what a 4-bit image of `Wf` represents.

    Phase-0c quantization-STRATEGY probe (fidelity_check-local on purpose —
    changing it does not touch the frozen wire format in w4a8_ref).
      group : quantization group along K (128 = shipped).
      rule  : "max" = scale max|W_g|/7 (shipped `quantize_weights`)
              "mse" = per-group grid search minimising reconstruction MSE
                      (= layer_fixed.quant_linear_mse's scale choice)
    The uint16-mantissa/shared-exponent storage of the scale is applied too,
    so this is a faithful image of what a real (re-grouped) DDR image holds,
    not an idealised fp16-scale quantizer.
    """
    N, K = Wf.shape
    assert K % group == 0, f"K={K} not divisible by group {group}"
    NG, RC = K // group, 8192          # row-chunked like quant_linear_big:
    scale = np.empty((N, NG))          # ONE matrix-wide exponent, as shipped
    for r0 in range(0, N, RC):
        r1 = min(r0 + RC, N)
        blk = np.asarray(Wf[r0:r1], dtype=np.float64).reshape(r1 - r0, NG, group)
        smax = np.maximum(np.abs(blk).max(axis=2), 1e-12)
        if rule == "mse":
            best_s, best_e = smax / 7.0, np.full(smax.shape, np.inf)
            for a in np.linspace(amin, 1.0, nalpha):
                s = (smax / 7.0) * a
                q = np.clip(np.round(blk / s[:, :, None]), -8, 7)
                err = ((q * s[:, :, None] - blk) ** 2).sum(axis=2)
                upd = err < best_e
                best_s = np.where(upd, s, best_s)
                best_e = np.where(upd, err, best_e)
            scale[r0:r1] = best_s
        else:
            scale[r0:r1] = smax / 7.0
    e = int(np.ceil(np.log2(scale.max()))) + 1
    m = np.clip(np.round(scale * np.exp2(15 - e)).astype(np.uint32),
                1, 65535).astype(np.uint16)
    eff = m.astype(np.float64) * np.exp2(e - 15)
    out = np.empty((N, K), dtype=np.float32)
    for r0 in range(0, N, RC):
        r1 = min(r0 + RC, N)
        blk = np.asarray(Wf[r0:r1], dtype=np.float64).reshape(r1 - r0, NG, group)
        w4 = np.clip(np.round(blk / eff[r0:r1, :, None]), -8, 7)
        out[r0:r1] = (w4 * eff[r0:r1, :, None]).reshape(r1 - r0, K)
    return out


def ablate(md, golden, prompts, ntok, mse_scale=False, tok=None,
           free_ntok=None, w4_groups=(128,), w4_rules=("max",)):
    """Three-way decomposition of the fidelity loss.

    (A) layer_ref (numpy float32) with the EXACT checkpoint weights — checks
        the float anchor itself against the torch golden on the REAL model
        (validate_vs_torch only ever did this on a random 2-layer toy).
    (B) layer_ref with every matvec matrix replaced by the float matrix its
        W4 image represents — the W4 WEIGHT error alone, no fixed-point
        datapath anywhere.
    The fixed-point runs elsewhere in this file then add the datapath on top
    of (B), so (golden -> A -> B -> fixed) attributes the loss.
    """
    import layer_ref as LR
    import layer_fixed as LF
    from gen_model_script import quant_linear_big
    if LF.CALIB_STATS:
        raise SystemExit(
            "--ablate is not calibration-wired (it calls quant_linear per "
            "matrix with no tensor identity), so running it with "
            "FABLE5_CALIB_STATS set would mix a salience/GPTQ-quantized body "
            "with an unweighted head. "
            "Unset FABLE5_CALIB_STATS for --ablate runs.")
    MV = {"attn": ("q_proj", "k_proj", "v_proj", "o_proj"),
          "dn": ("in_qkv", "in_z", "in_b", "in_a", "out"),
          "mlp": ("gate", "up", "down")}
    free_ntok = ntok if free_ntok is None else free_ntok
    # tag -> (group, rule); "exact" keeps the checkpoint weights
    cfgs = [("exact", None, None)]
    for g in w4_groups:
        for r in w4_rules:
            cfgs.append((f"w4deq" if (g == 128 and r == "max")
                         else f"w4_g{g}_{r}", g, r))
    out = {}
    for tag, grp, rule in cfgs:
        t0 = time.time()
        if tag == "exact":
            wfs, head_w = md["layers"], np.asarray(md["head"], dtype=np.float32)
        elif grp == 128 and rule == "max":
            # the production path, through the real quantizer.  `mse_scale`
            # selects which group-scale rule that quantizer uses (Phase 1A:
            # mse is production), so this branch always IS the shipped W4
            # image; w4_roundtrip below is only for off-production groups.
            wfs = []
            for wf in md["layers"]:
                w2 = {k: v for k, v in wf.items()}
                w2["mlp"] = {k: (dequant_w4(LF.quant_linear(wf["mlp"][k],
                                                            mse_scale=mse_scale))
                                 if k in MV["mlp"] else wf["mlp"][k])
                             for k in wf["mlp"]}
                sub = "attn" if wf["type"] == "full_attention" else "dn"
                w2[sub] = {k: (dequant_w4(LF.quant_linear(wf[sub][k],
                                                          mse_scale=mse_scale))
                               if k in MV[sub] else wf[sub][k])
                           for k in wf[sub]}
                wfs.append(w2)
            head_w = dequant_w4(quant_linear_big(md["head"],
                                                 mse_scale=mse_scale))
        else:
            wfs = []
            for wf in md["layers"]:
                w2 = {k: v for k, v in wf.items()}
                w2["mlp"] = {k: (w4_roundtrip(wf["mlp"][k], grp, rule)
                                 if k in MV["mlp"] else wf["mlp"][k])
                             for k in wf["mlp"]}
                sub = "attn" if wf["type"] == "full_attention" else "dn"
                w2[sub] = {k: (w4_roundtrip(wf[sub][k], grp, rule)
                               if k in MV[sub] else wf[sub][k])
                           for k in wf[sub]}
                wfs.append(w2)
            head_w = w4_roundtrip(md["head"], grp, rule)
        emb_lookup = np.asarray(md["emb"], dtype=np.float32)
        ln_f = np.asarray(md["ln_f"], dtype=np.float32)
        res = {}
        for pseed in prompts:
            ids = list(PROMPTS[pseed][2])
            nsteps = len(ids) + ntok - 1
            g_seq, g_am = golden[f"p{pseed}_seq"], golden[f"p{pseed}_argmax"]
            caches = [LR.new_cache(t) for t in md["layer_types"]]
            am, rk = [], []
            for t in range(nsteps):                       # TEACHER-FORCED
                x = emb_lookup[int(g_seq[t])].copy()
                for li, wf in enumerate(wfs):
                    x = LR.layer_decode(x, wf, caches[li], t)
                lg = head_w @ LR.rmsnorm1p(x, ln_f)
                am.append(int(np.argmax(lg)))
                rk.append(int((lg > lg[int(g_am[t])]).sum()))
            e = {"argmax": am, "rank": rk,
                 "top1": [int(a == int(b)) for a, b in zip(am, g_am)]}
            # FREE-RUNNING (this is the text the model would actually emit)
            caches = [LR.new_cache(t) for t in md["layer_types"]]
            cur, gen = int(ids[0]), []
            for t in range(len(ids) + free_ntok - 1):
                x = emb_lookup[cur].copy()
                for li, wf in enumerate(wfs):
                    x = LR.layer_decode(x, wf, caches[li], t)
                lg = head_w @ LR.rmsnorm1p(x, ln_f)
                a = int(np.argmax(lg))
                if t >= len(ids) - 1:
                    gen.append(a)
                cur = ids[t + 1] if t + 1 < len(ids) else a
            e["free_gen"] = gen
            e["free_text"] = tok.decode(gen) if tok else None
            res[pseed] = e
        out[tag] = res
        n = sum(sum(res[p]["top1"]) for p in prompts)
        tot = sum(len(res[p]["top1"]) for p in prompts)
        print(f"  ABLATION {tag:<12} top1={n}/{tot}  "
              f"rank med={np.median([v for p in prompts for v in res[p]['rank']]):.1f} "
              f"({time.time() - t0:.0f}s)", flush=True)
        for p in prompts:
            print(f"    p{p} {PROMPTS[p][0]!r}")
            print(f"       argmax={res[p]['argmax']} rank={res[p]['rank']}")
            print(f"       FREE gen={res[p]['free_gen']}")
            print(f"       FREE text={res[p]['free_text']!r}", flush=True)
        del wfs, head_w
    return out


def trace(md, golden, prompts, ntok, res_scale=1, mse_scale=False):
    """Where does the fixed-point pipeline lose the model?

    Runs the FLOAT decode with the W4-dequantized weights (= ablation
    `w4deq`, which still tracks the golden well) and the FIXED-POINT decode
    side by side on the same tokens, and reports the relative RMS error of
    the residual after every layer.  A steady growth means accumulated
    rounding; a jump at one layer names the block to fix.
    """
    import layer_ref as LR
    import layer_fixed as LF
    from layer_fixed import RS_F
    from gen_model_script import quant_linear_big
    MV = {"attn": ("q_proj", "k_proj", "v_proj", "o_proj"),
          "dn": ("in_qkv", "in_z", "in_b", "in_a", "out"),
          "mlp": ("gate", "up", "down")}
    qlayers, flayers = [], []
    for li_, wf in enumerate(md["layers"]):
        q = LF.quant_layer(wf, res_scale=res_scale, mse_scale=mse_scale,
                           layer_idx=li_)
        qlayers.append(q)
        w2 = {k: v for k, v in wf.items()}
        # NOTE the float side keeps the res_scale'd weights AS QUANTIZED and
        # seeds with emb*S, so BOTH sides carry an S-times residual: the
        # comparison stays apples-to-apples (dividing the residual-adding
        # weights back down while seeding with emb*S would be inconsistent).
        w2["mlp"] = {k: (dequant_w4(q["mlp"][k]) if k in MV["mlp"]
                         else wf["mlp"][k]) for k in wf["mlp"]}
        sub = "attn" if wf["type"] == "full_attention" else "dn"
        w2[sub] = {k: (dequant_w4(q[sub][k]) if k in MV[sub]
                       else wf[sub][k]) for k in wf[sub]}
        flayers.append(w2)
    emb_f = np.asarray(md["emb"], dtype=np.float32)
    emb_q = np.clip(np.round(np.asarray(md["emb"], dtype=np.float64)
                             * res_scale * (1 << RS_F)), -32768,
                    32767).astype(np.int64)
    ln_f = np.asarray(md["ln_f"], dtype=np.float32)
    ln_f_q12 = np.round((1.0 + np.asarray(md["ln_f"], dtype=np.float64))
                        * (1 << 12)).astype(np.int64)
    head_f = dequant_w4(quant_linear_big(md["head"], mse_scale=mse_scale,
                                         salience=LF.calib_salience("lm_head"),
                                         hess=LF.calib_hess("lm_head")))
    for pseed in prompts:
        ids = list(PROMPTS[pseed][2])
        nsteps = len(ids) + ntok - 1
        g_seq = golden[f"p{pseed}_seq"]
        cf = [LR.new_cache(t) for t in md["layer_types"]]
        cq = [LF.new_cache_fx(t) for t in md["layer_types"]]
        print(f"\n  prompt {pseed}: per-layer relative RMS error "
              f"(fixed vs float-with-W4-weights), res_scale={res_scale}")
        for t in range(nsteps):
            xf = emb_f[int(g_seq[t])].astype(np.float64) * res_scale
            xq = emb_q[int(g_seq[t])].copy()
            row = []
            for li in range(len(qlayers)):
                xf = LR.layer_decode(xf.astype(np.float32), flayers[li],
                                     cf[li], t).astype(np.float64)
                xq = LF.layer_decode_fx(xq, qlayers[li], cq[li], t)
                e = (np.sqrt(np.mean((xq / (1 << RS_F) - xf) ** 2))
                     / (np.sqrt(np.mean(xf ** 2)) + 1e-30))
                row.append(e)
            lg_f = head_f @ LR.rmsnorm1p(xf.astype(np.float32), ln_f)
            xn = LF.rmsnorm_fx(xq, ln_f_q12, RS_F, False)
            print(f"    step {t}: " + " ".join(f"{v:5.1%}" for v in row)
                  + f"   |x|max={int(np.abs(xq).max())} "
                    f"float_argmax={int(np.argmax(lg_f))}")


def blockprobe(md, golden, prompts, ntok, res_scale=1, layer=0):
    """Per-BLOCK error of the fixed-point layer against the float layer.

    Both sides get the SAME input residual and the SAME (W4-dequantized)
    weights, so every number below is pure fixed-point datapath loss with
    the weight-quantization error divided out.  Blocks are evaluated in the
    order layer_fixed.deltanet_decode_fx / mlp_fx run them.
    """
    import layer_ref as LR
    import layer_fixed as LF
    import fixedpoint as fp
    from layer_fixed import RS_F, QKV_F, NRM_F, S_F, GAT_F
    from w4a8_ref import rshift_round as rshr
    I64 = np.int64

    def rel(fx, fl, f):
        fx = np.asarray(fx, dtype=np.float64) / (1 << f)
        fl = np.asarray(fl, dtype=np.float64)
        return (np.sqrt(np.mean((fx - fl) ** 2))
                / (np.sqrt(np.mean(fl ** 2)) + 1e-30))

    wf = md["layers"][layer]
    assert wf["type"] == "linear_attention", "probe written for DeltaNet"
    q = LF.quant_layer(wf, res_scale=res_scale)
    qd = q["dn"]
    wd = {k: (dequant_w4(qd[k]) if k in ("in_qkv", "in_z", "in_b", "in_a")
              else dequant_w4(qd["out"]) / res_scale if k == "out"
              else wf["dn"][k]) for k in wf["dn"]}
    # float weights that EXACTLY match the fixed-point constants
    wd["conv_w"] = (qd["conv_w"] / (1 << LF.CW_F)).astype(np.float32)
    wd["norm_w"] = (qd["norm_w_q14"] / (1 << 14)).astype(np.float32)
    wd["dt_bias"] = (qd["dt_bias_q12"] / (1 << 12)).astype(np.float32)
    wd["A_log"] = np.log(np.maximum(qd["A_q15"] / (1 << 15), 1e-30)).astype(np.float32)
    ln1 = (q["ln1"] / (1 << 14)).astype(np.float32)

    pseed = prompts[0]
    tok = int(golden[f"p{pseed}_seq"][0])
    x16 = np.clip(np.round(np.asarray(md["emb"][tok], dtype=np.float64)
                           * res_scale * (1 << RS_F)), -32768, 32767).astype(I64)
    xf = x16.astype(np.float64) / (1 << RS_F)          # identical input

    xn16 = LF.rmsnorm_fx(x16, q["ln1"], RS_F, True)
    xnf = LR.rmsnorm1p(xf.astype(np.float32), ln1)
    print(f"  layer {layer} ({wf['type']}), token {tok}, res_scale={res_scale}")
    print(f"    x  |max|={int(np.abs(x16).max())} LSB   rms="
          f"{np.sqrt(np.mean(x16.astype(float)**2)):.1f} LSB")
    print(f"    ln1 out            rel={rel(xn16, xnf, RS_F):.2%}   "
          f"|max|={int(np.abs(xn16).max())}")

    qkv16 = LF.clip16(LF.matvec_to(qd["in_qkv"], xn16, RS_F, RS_F))
    qkvf = wd["in_qkv"] @ xnf
    print(f"    in_qkv matvec      rel={rel(qkv16, qkvf, RS_F):.2%}   "
          f"|max|={int(np.abs(qkv16).max())} rms="
          f"{np.sqrt(np.mean(qkv16.astype(float)**2)):.1f} LSB")

    z16 = LF.clip16(LF.matvec_to(qd["in_z"], xn16, RS_F, QKV_F))
    zf = wd["in_z"] @ xnf
    print(f"    in_z matvec        rel={rel(z16, zf, QKV_F):.2%}   "
          f"|max|={int(np.abs(z16).max())}")
    b12 = LF.clip16(LF.matvec_to(qd["in_b"], xn16, RS_F, 12))
    a12 = LF.clip16(LF.matvec_to(qd["in_a"], xn16, RS_F, 12))
    print(f"    in_b/in_a          rel={rel(b12, wd['in_b'] @ xnf, 12):.2%}"
          f" / {rel(a12, wd['in_a'] @ xnf, 12):.2%}   "
          f"|b|max={int(np.abs(b12).max())} |a|max={int(np.abs(a12).max())}")

    st = LF.new_cache_fx("linear_attention")
    win = np.concatenate([st["conv"], qkv16[:, None]], axis=1)
    acc = (win.astype(I64) * qd["conv_w"]).sum(axis=1)
    pre = np.clip(rshr(acc, RS_F + LF.CW_F - 12), -(1 << 20), (1 << 20) - 1)
    conv16 = LF.clip16(np.array([fp.silu_q(int(v)) for v in pre], dtype=I64))
    convf = LR.silu(np.sum(np.concatenate(
        [np.zeros((LR.CONV_DIM, 3)), qkvf[:, None]], axis=1) * wd["conv_w"],
        axis=1))
    print(f"    conv4+silu (Q12)   rel={rel(conv16, convf, 12):.2%}   "
          f"|max|={int(np.abs(conv16).max())} rms="
          f"{np.sqrt(np.mean(conv16.astype(float)**2)):.1f} LSB  "
          f"(rail hits {int((np.abs(conv16) >= 32767).sum())})")
    qkv8 = rshr(conv16, 12 - QKV_F)
    print(f"    -> q/k/v at Q{QKV_F} rel={rel(qkv8, convf, QKV_F):.2%}   "
          f"|max|={int(np.abs(qkv8).max())} rms="
          f"{np.sqrt(np.mean(qkv8.astype(float)**2)):.2f} LSB")
    # LNH = VALUE heads, LNKH = KEY heads (16 vs 32 at 4B/9B).  q and k are
    # LR.LKD = LNKH*LDK wide; only v is LNH*LDV.  Using LNH*LDK here would
    # slice q into q|k and leave v empty — see layer_fixed.deltanet_decode_fx.
    LNH, LDK, LDV = LR.LNH, LR.LDK, LR.LDV
    LNKH, LKD, VREP = LR.LNKH, LR.LKD, LR.VREP
    v_fx = qkv8[2 * LKD:].reshape(LNH, LDV)
    v_fl = convf[2 * LKD:].reshape(LNH, LDV)
    print(f"    -> v only          rel={rel(v_fx, v_fl, QKV_F):.2%}   "
          f"rms={np.sqrt(np.mean(v_fx.astype(float)**2)):.2f} LSB")
    qn_fx = np.stack([LF.l2norm_fx(qkv8[:LKD].reshape(LNKH, LDK)[h],
                                   QKV_F, NRM_F) for h in range(LNKH)])
    qn_fl = LR.l2norm(convf[:LKD].reshape(LNKH, LDK))
    print(f"    -> l2norm(q)       rel={rel(qn_fx, qn_fl, NRM_F):.2%}")

    # ---- the recurrence and, crucially, the SCRIPT-SIDE alignment of the
    # per-head output before the gated RMSNorm (gen_layer_script.dn_token:
    #   M.alu(1, 128, S_F - QKV_F, DO32, 0, OH); M.vn(1,128,QKV_F,QKV_F,...)
    # both the shift and the vecnorm in_f are command ARGUMENTS, not RTL) ----
    k_fx = np.stack([LF.l2norm_fx(qkv8[LKD:2 * LKD]
                                  .reshape(LNKH, LDK)[h], QKV_F, NRM_F)
                     for h in range(LNKH)])
    k_fl = LR.l2norm(convf[LKD:2 * LKD].reshape(LNKH, LDK))
    qs_fx = rshr(qn_fx * I64(int(round((1 << 15) / np.sqrt(LDK)))), 15)
    qs_fl = qn_fl / np.sqrt(LDK)
    beta_fx = np.array([fp.sigmoid_q(int(b)) for b in b12], dtype=I64)
    beta_fl = LR.sigmoid(np.asarray(wd["in_b"] @ xnf, dtype=np.float64))
    o_fx = np.zeros((LNH, LDV), dtype=I64)
    o_fl = np.zeros((LNH, LDV))
    for h in range(LNH):
        kh = h // VREP                      # the KEY head this value head reads
        v_s = v_fx[h] << (S_F - QKV_F)
        delta = rshr(v_s * I64(int(beta_fx[h])), GAT_F)
        Sh = rshr(k_fx[kh][:, None] * delta[None, :], NRM_F)    # zero state
        o_fx[h] = rshr((Sh * qs_fx[kh][:, None]).sum(axis=0), NRM_F)
        Sf = np.outer(k_fl[kh], v_fl[h] * beta_fl[h])
        o_fl[h] = Sf.T @ qs_fl[kh]
    print(f"    dnst o (Q{S_F})     rel={rel(o_fx, o_fl, S_F):.2%}   "
          f"|max|={int(np.abs(o_fx).max())} rms="
          f"{np.sqrt(np.mean(o_fx.astype(float)**2)):.2f} LSB")
    nf = LR.rmsnorm(o_fl.astype(np.float32),
                    (qd["norm_w_q14"] / (1 << 14)).astype(np.float32))
    print("      DNST->int16 shift x vecnorm in_f grid (gated-norm rel err;"
          " shift 5 / in_f 8 is what ships today):")
    print("        " + "".join(f"in_f={f:<9d}" for f in (8, 10, 11, 12, 13)))
    for sh_out in (5, 2, 0, -2, -4, -6):
        o16 = LF.clip16(rshr(o_fx, sh_out) if sh_out >= 0
                        else o_fx << (-sh_out))
        cells = []
        for f_out in (8, 10, 11, 12, 13):
            nh = np.stack([LF.rmsnorm_fx(o16[h], qd["norm_w_q14"], f_out,
                                         False) for h in range(LNH)])
            clp = int((np.abs(nh) >= 32767).sum())
            cells.append(f"{rel(nh, nf, f_out):7.2%}{'*' if clp else ' '}  ")
        print(f"  sh={sh_out:>3d} (o16 rms {np.sqrt(np.mean(o16.astype(float)**2)):7.1f}, "
              f"|max| {int(np.abs(o16).max()):6d}) " + "".join(cells))


DIAGS = {
    # name -> layer_fixed module attributes to override.  Each entry RELAXES
    # one frozen fixed-point limit so the run is no longer RTL-legal; the
    # point is to attribute the fidelity loss to a specific format, i.e. to
    # say which RTL change would be worth un-freezing.
    # "base" is now the PRODUCTION datapath (Phase 1A): block-floating DN
    # output + script-side gated norm + DN_NORM_F=11, all unconditional in
    # layer_fixed.  The Phase-0 toggles (DN_O_BF / ATTN_O_BF /
    # DN_SCRIPT_NORM / DN_BF_KMIN / DN_O_SHIFT) no longer exist — the losing
    # arms of that sweep are in git history at 229c033 with their logs in
    # evidence/stage5/fidelity_phase0_*.log.  What remains here is what is
    # still a live question: the frozen RTL formats (Phase 1B menu).
    "base": {},
    # SEQUENCER RUNG 1 (docs/SEQ_ISA.md): the DeltaNet gated-norm scale is
    # computed ON CHIP by the vecnorm EPS-NORM mode (integer rsqrt ROM path,
    # ss from the DYNQ16 int16 output, eps added in the ss domain with the
    # k-scaled integer constant) instead of by the host in float64.  This is
    # RTL-legal by construction — it IS the RTL spec — and it is the only
    # entry here that measures an op we are about to BUILD rather than a
    # limit we might relax.  DYNQ16 needs no entry: it is bit-identical to
    # the shipped bf_shift + op-1 path (proved in layer_fixed._dynq16_soak).
    "seqnorm": {"SEQ_NORM": True},
    "gateport": {"DT_Q12_MIN": -(1 << 30), "DT_Q12_MAX": (1 << 30),
                 "A_Q15_MAX": (1 << 30)},
    "S_F12": {"S_F": 12},
    "S_F11": {"S_F": 11},
    "S_F14": {"S_F": 14},
    # DN_NORM_F / BF_GUARD are SCRIPT-side (command immediates), so these
    # stay RTL-legal: they say whether 11 / 0 are still the right choices.
    "n10": {"DN_NORM_F": 10},
    "n12": {"DN_NORM_F": 12},
    "guard1": {"BF_GUARD": 1},
    "S12_n11_gate": {"S_F": 12, "DT_Q12_MIN": -(1 << 30),
                     "DT_Q12_MAX": (1 << 30), "A_Q15_MAX": (1 << 30)},
    "all": {"DT_Q12_MIN": -(1 << 30), "DT_Q12_MAX": (1 << 30),
            "A_Q15_MAX": (1 << 30), "S_F": 12},
}


def rank_of(logits, tok):
    v = int(logits[tok])
    return int((logits > v).sum())


def run_config(md, golden, prompts, ntok, res_scale, tighten_e, head, emb_f,
               freerun=True, tok=None, mse_scale=False, free_ntok=None,
               wire_group=128, w8=False, wq_cache=None, wq_verify=None,
               dn_probe=False):
    """Quantize at (res_scale, tighten_e, wire_group) and score every prompt.

    `free_ntok` (default = ntok) sets the FREE-RUNNING horizon independently
    of the teacher-forced one: the teacher-forced metric is pinned to the
    golden cache's ntok, while readable text needs more generated tokens.

    `wire_group` is the W4 group size of the WIRE FORMAT (128 legacy / 64 =
    the v2 row format).  This is the shipped quantizer + the shipped
    fixed-point datapath, so the number it produces is what a g=64 DDR image
    would actually score on hardware — the `--w4-group` knob of --ablate is
    a float-only probe by comparison.  `head` must be quantized at the SAME
    group size (main() does that).

    `w8` (V5) is the same statement one weight width up: every matvec
    matrix INCLUDING the LM head is an 8-bit image.  `head` must already be
    W8 (main() does that too, and the assert below refuses the mismatch).
    """
    import layer_fixed as LF
    from layer_fixed import RS_F
    I64 = np.int64
    free_ntok = ntok if free_ntok is None else free_ntok
    LF.bf_reset()

    k = int(round(np.log2(res_scale)))
    assert (1 << k) == int(res_scale) or res_scale == 1, "S must be a power of 2"
    assert int(head.get("g", 128)) == int(wire_group), \
        f"LM head is g={head.get('g', 128)}, config asks for g={wire_group}"
    assert LF.qw_codes(head)[1] == bool(w8), \
        f"LM head is {'W8' if LF.qw_codes(head)[1] else 'W4'}, config asks " \
        f"for {'W8' if w8 else 'W4'}"
    wq_key = _wq_key("layers", md, res_scale, tighten_e, mse_scale,
                     wire_group, w8)
    layers_q = _wq_load(wq_cache, wq_key, "layers")
    if layers_q is None:
        layers_q = quantize_model(md, res_scale=res_scale,
                                  tighten_e=tighten_e, mse_scale=mse_scale,
                                  g=wire_group, w8=w8)
        _wq_save(wq_cache, wq_key, layers_q, "layers")
    elif wq_verify is not None:
        # The cache's whole premise is that the DeltaNet state law and RS_F
        # cannot reach the quantizer.  Prove it on the setting actually in
        # force: re-quantize ONE layer live and require byte-equality.
        import layer_fixed as LFv
        t0 = time.time()
        i = int(wq_verify)
        fresh = LFv.quant_layer(md["layers"][i], res_scale=res_scale,
                                tighten_e=tighten_e, mse_scale=mse_scale,
                                g=wire_group, layer_idx=i, w8=w8)
        same, why = _wq_same(fresh, layers_q[i], f"layer{i}")
        _WQ_STATE["verified"] = {"layer": i, "same": bool(same),
                                 "why": why, "secs": time.time() - t0,
                                 "dn_state": LFv.DN_STATE, "rs_f": LFv.RS_F}
        print(f"    wq-cache VERIFY layer {i} ({md['layer_types'][i]}) "
              f"re-quantized live under FABLE5_DN_STATE={LFv.DN_STATE} "
              f"RS_F={LFv.RS_F}: "
              f"{'BYTE-IDENTICAL to the cache' if same else 'DIFFERS ' + why} "
              f"({time.time() - t0:.1f}s)", flush=True)
        if not same:
            raise SystemExit("wq-cache verify FAILED: the cached quantized "
                             "weights are not what this setting produces — "
                             f"{why}")

    # embedding table at S*2^RS_F (one extra k bits of resolution)
    t0 = time.time()
    vocab = emb_f.shape[0]
    emb_q = np.empty(emb_f.shape, dtype="<i2")
    for r0 in range(0, vocab, 8192):
        r1 = min(r0 + 8192, vocab)
        emb_q[r0:r1] = np.clip(np.round(np.asarray(emb_f[r0:r1],
                                                   dtype=np.float64)
                                        * float(res_scale) * (1 << RS_F)),
                               -32768, 32767).astype("<i2")
    emb_absmax = int(np.abs(emb_q).max())
    print(f"    emb table |q|max {emb_absmax} of 32767 "
          f"({time.time() - t0:.1f}s)", flush=True)

    ln_f_q12 = np.round((1.0 + np.asarray(md["ln_f"], dtype=np.float64))
                        * (1 << 12)).astype(I64)

    # --- probe every matvec output BEFORE the caller's clip16 ---
    stats = {"mv": {}}
    orig_mv = LF.matvec_to

    def probed(qw, x16, in_f, out_f):
        y = orig_mv(qw, x16, in_f, out_f)
        w, _is8 = LF.qw_codes(qw)          # W4 nibbles or W8 bytes (V5)
        tag = f"{w.shape[0]}x{w.shape[1]}"
        st = stats["mv"].setdefault(tag, [0, 0, 0])
        st[0] = max(st[0], int(np.abs(y).max()))
        st[1] += int(((y > 32767) | (y < -32768)).sum())
        st[2] += int(y.size)
        return y
    LF.matvec_to = probed

    # --- G1: the DeltaNet state's own DISTRIBUTION, not just its max ---
    # Wrapped here rather than instrumented inside layer_fixed on purpose:
    # the quantized-weight cache is keyed by a sha256 over the ref/ sources
    # that define the quantizer, and layer_fixed is one of them — adding a
    # counter there would invalidate a 3.2 h artifact and, worse, split one
    # comparison across two source digests.  fidelity_check is deliberately
    # NOT in that list, and it already wraps `matvec_to` the same way.
    # What it measures is the PRE-narrowing accumulator, per element:
    # rms, absmax, the zero count and a log2-magnitude histogram.  That is
    # the number that decides whether a container's problem is RANGE or
    # RESOLUTION, which is exactly the question the k sweep asks.
    #
    # --- and the EXPONENT-GRANULARITY probe (G1 review F3) ---
    # The `int8:<k>` law's `k` is GLOBAL — `dn_state_pack` returns
    # `np.full(1, k)` — so the sweep priced exactly one point of an axis that
    # has more than one.  Between a global k and `int8e`'s per-ROW exponent sit
    # per-LAYER and per-HEAD, both cheaper RTL and the same L-family idea.
    # This measures what each granularity would buy, on the same six steps,
    # WITHOUT implementing any of them: for every state write it computes the
    # exponent a container of that granularity would pick — `bitlen(group max)
    # - 7`, the same priority encode `dn_state_pack` uses — and then scores the
    # state in units of THAT container's LSB.  The statistic is
    #   codes_per_rms = sqrt(mean over elements of (S / 2^max(e_g - 7, 0))^2)
    # i.e. how many container codes one rms of state is worth.  Below 1 the
    # state is mostly quantized to zero, which is the failure the k sweep hit.
    # A wrapper, not an implementation, and not a decision.
    orig_narrow = LF.dn_state_narrow
    dn_hist = {"n": 0, "zero": 0, "sumsq": 0.0, "absmax": 0, "log2": {},
               "e_head": {}, "e_row": {},
               "sq_head": 0.0, "sq_row": 0.0, "n_head": 0, "n_row": 0}
    if dn_probe:
        def _egran(amax):
            """The exponent a 7-bit-magnitude container picks for this group."""
            return np.maximum(
                np.array([int(v).bit_length() for v in np.atleast_1d(amax)],
                         dtype=I64) - 7, 0)

        def narrow_probed(S16):
            A = np.abs(np.asarray(S16, dtype=I64))
            dn_hist["n"] += int(A.size)
            dn_hist["sumsq"] += float(np.square(A, dtype=np.float64).sum())
            dn_hist["absmax"] = max(dn_hist["absmax"], int(A.max()))
            nzm = A[A > 0]
            dn_hist["zero"] += int(A.size - nzm.size)
            if nzm.size:
                b = np.bincount(
                    (np.log2(nzm.astype(np.float64))).astype(np.int64),
                    minlength=18)
                for i, c in enumerate(b):
                    if c:
                        dn_hist["log2"][i] = dn_hist["log2"].get(i, 0) + int(c)
            # `dn_state_narrow` is called once per HEAD, with that head's whole
            # (LDK, LDV) state, so this call IS the per-head group and its rows
            # are the per-row groups (the 1024-bit half-rows of spec 4.1's map).
            if A.ndim >= 2:
                Af = A.astype(np.float64)
                eh = int(_egran(A.max())[0])
                dn_hist["e_head"][eh] = dn_hist["e_head"].get(eh, 0) + 1
                dn_hist["sq_head"] += float(
                    np.square(Af / float(1 << eh)).sum())
                dn_hist["n_head"] += int(A.size)
                er = _egran(A.max(axis=-1))
                for v in er:
                    dn_hist["e_row"][int(v)] = \
                        dn_hist["e_row"].get(int(v), 0) + 1
                dn_hist["sq_row"] += float(np.square(
                    Af / np.exp2(er.astype(np.float64))[:, None]).sum())
                dn_hist["n_row"] += int(A.size)
            return orig_narrow(S16)
        LF.dn_state_narrow = narrow_probed
    try:
        res = {}
        for pseed in prompts:
            ids = list(PROMPTS[pseed][2])
            nsteps = len(ids) + ntok - 1
            g_seq = golden[f"p{pseed}_seq"]
            g_am = golden[f"p{pseed}_argmax"]
            g_topk = golden[f"p{pseed}_topk_i"]

            R = FxRunner(layers_q, md["layer_types"], emb_q, head, ln_f_q12)
            top1, ranks, ov5, fx_am = [], [], [], []
            for t in range(nsteps):                       # TEACHER-FORCED
                y = R.step(int(g_seq[t]), t)
                am = int(np.argmax(y))
                fx_am.append(am)
                top1.append(int(am == int(g_am[t])))
                ranks.append(rank_of(y, int(g_am[t])))
                fx5 = set(np.argsort(-y, kind="stable")[:5].tolist())
                ov5.append(len(fx5 & set(g_topk[t][:5].tolist())))
            sat = sum(int(c.get("sat", 0)) for c in R.caches
                      if isinstance(c, dict) and "sat" in c)
            entry = {"fx_argmax": fx_am, "top1": top1, "rank": ranks,
                     "top5": ov5, "resid_max": R.resid_max,
                     "resid_clip": R.resid_clip, "s_sat": sat,
                     "golden_argmax": [int(v) for v in g_am]}

            if freerun:
                R.reset()
                cur, gen = int(ids[0]), []
                for t in range(len(ids) + free_ntok - 1):
                    y = R.step(cur, t)
                    am = int(np.argmax(y))
                    if t >= len(ids) - 1:
                        gen.append(am)
                    cur = ids[t + 1] if t + 1 < len(ids) else am
                entry["free_gen"] = gen
                entry["free_text"] = tok.decode(gen) if tok else None
                entry["resid_max"] = max(entry["resid_max"], R.resid_max)
                entry["resid_clip"] += R.resid_clip
            res[pseed] = entry
    finally:
        LF.matvec_to = orig_mv
        LF.dn_state_narrow = orig_narrow
    res["_mv"] = stats["mv"]
    res["_emb_absmax"] = emb_absmax
    res["_wire_group"] = int(wire_group)
    res["_w8"] = bool(w8)
    # host is RECORDED, not inferred (see perplexity_eval's note)
    res["_host"] = socket.gethostname()
    res["_calib_stats"] = LF.CALIB_STATS or None
    res["_calib_mode"] = LF.CALIB_MODE if LF.CALIB_STATS else None
    res["_calib_stats_sha256"] = (_sha256_file(LF.CALIB_STATS)
                                  if LF.CALIB_STATS else None)
    res["_bf_k"] = {k: dict(sorted(v.items()))
                    for k, v in LF.BF_K_HIST.items() if v}
    res["_bf_clip"] = dict(LF.BF_CLIP)
    # G1: the state container's configuration AND its measured occupancy,
    # in the same record, so a row can never be read without its law.
    res["_dn"] = dict(LF.DN_STATS,
                      law=LF.DN_STATE, law_kind=LF.DN_STATE_LAW,
                      k=LF.DN_STATE_K, s_f=LF.S_F, rs_f=LF.RS_F,
                      ceiling_lsb=(LF.S8_MAX << LF.DN_STATE_K
                                   if LF.DN_STATE_LAW in ("int8", "int8t")
                                   else 32767))
    res["_wq"] = dict(_WQ_STATE)
    if dn_probe and dn_hist["n"]:
        n = dn_hist["n"]
        rms = (dn_hist["sumsq"] / n) ** 0.5
        res["_dn_dist"] = dict(dn_hist, rms_lsb=rms,
                               rms=rms / (1 << LF.S_F),
                               absmax_val=dn_hist["absmax"] / (1 << LF.S_F),
                               zero_frac=dn_hist["zero"] / n,
                               log2=dict(sorted(dn_hist["log2"].items())))
        print(f"    DN state distribution over {n} pre-narrowing writes: "
              f"rms {rms:.2f} LSB ({rms / (1 << LF.S_F):.6f}), "
              f"|S|max {dn_hist['absmax']} LSB "
              f"({dn_hist['absmax'] / (1 << LF.S_F):.4f}), "
              f"{100.0 * dn_hist['zero'] / n:.2f}% exactly zero, "
              f"dynamic range |S|max/rms = {dn_hist['absmax'] / max(rms, 1e-9):.1f}"
              f" -> {int(np.ceil(np.log2(max(dn_hist['absmax'] / max(rms, 1e-9), 1))))}"
              f" bits above the rms, before any headroom", flush=True)
        print(f"    log2|S| histogram (bucket i = |S| in [2^i, 2^(i+1)) LSB): "
              f"{dict(sorted(dn_hist['log2'].items()))}", flush=True)
        if dn_hist["n_head"]:
            eg = max(int(dn_hist["absmax"]).bit_length() - 7, 0)
            cpr_g = rms / float(1 << eg)
            cpr_h = (dn_hist["sq_head"] / dn_hist["n_head"]) ** 0.5
            cpr_r = (dn_hist["sq_row"] / dn_hist["n_row"]) ** 0.5
            res["_dn_dist"].update(
                e_global=eg, codes_per_rms_global=cpr_g,
                codes_per_rms_head=cpr_h, codes_per_rms_row=cpr_r,
                e_head=dict(sorted(dn_hist["e_head"].items())),
                e_row=dict(sorted(dn_hist["e_row"].items())))
            print(f"    exponent granularity (7-bit magnitude field, "
                  f"codes per rms of state; < 1 means the state is mostly "
                  f"quantized away):\n"
                  f"      GLOBAL   e={eg:<3d} LSB={1 << eg:<6d} "
                  f"codes/rms = {cpr_g:.3f}\n"
                  f"      PER-HEAD e in {sorted(dn_hist['e_head'])}   "
                  f"codes/rms = {cpr_h:.3f}   "
                  f"({cpr_h / max(cpr_g, 1e-9):.2f}x global)\n"
                  f"      PER-ROW  e in {sorted(dn_hist['e_row'])}   "
                  f"codes/rms = {cpr_r:.3f}   "
                  f"({cpr_r / max(cpr_g, 1e-9):.2f}x global)", flush=True)
            print(f"      e_head histogram {dict(sorted(dn_hist['e_head'].items()))}",
                  flush=True)
            print(f"      e_row  histogram {dict(sorted(dn_hist['e_row'].items()))}",
                  flush=True)
    res["_seq"] = dict(LF.SEQ_STATS) if LF.SEQ_NORM else None
    del layers_q, emb_q
    return res


# ======================================================================
def check_w8_flags(args):
    """--w8 refuses every W4-only knob rather than ignoring it.

    A summary row labelled "g64" or "mse" that was actually plain W8 is a
    number nobody could interpret afterwards — the discipline the
    FABLE5_CALIB_MODE guard and layer_fixed._quant_matvec already apply.
    Called before ANY mode dispatches, so --ablate/--trace/--blocks are
    caught too (they return early in main()).
    """
    if not args.w8:
        return
    if [int(s) for s in args.wire_group.split(",")] != [128]:
        raise SystemExit("--w8 needs --wire-group 128: the W8 row format is "
                         "defined at g128 cadence only (its scale beats ARE "
                         "a W4 g128 row's) — sw/hwmap.shape_word and "
                         "rtl/matvec_engine.sv both refuse w8+g64")
    if [int(s) for s in args.mse.split(",")] != [1]:
        raise SystemExit("--w8 has ONE group-scale rule (max|W_g|/127, "
                         "w4a8_ref.quantize_weights8); --mse selects between "
                         "the two W4 rules and does not apply")
    if args.qfix != "0":
        raise SystemExit("--qfix is the W4 shared-exponent tightening "
                         "(layer_fixed.quant_linear); W8 has no such knob")
    for on, nm in ((args.golden, "--golden"), (args.ablate, "--ablate"),
                   (args.trace, "--trace"), (args.blocks >= 0, "--blocks"),
                   (args.diag, "--diag")):
        if on:
            raise SystemExit(f"{nm} has no W8 path: it is either a bf16 "
                             f"golden (weight format irrelevant) or a W4 "
                             f"attribution probe that dequantizes W4 images")
    import layer_fixed as LF
    if LF.CALIB_STATS:
        raise SystemExit("FABLE5_CALIB_STATS is set and --w8 is on: the "
                         "calibrated quantizers are W4-only (V5 is plain W8; "
                         "Track Q ruled GPTQ-on-W8 out of scope), so this "
                         "would score W8 weights with the plumb silently "
                         "ignored. Unset it, or drop --w8.")


def check_norm_geometry(args):
    """Refuse a hidden size the fixed-point normalizer cannot express — NOW,
    not after half an hour of quantization.

    `layer_fixed.rmsnorm_fx` folds 1/N into the rsqrt binary point as a shift,
    exactly as `rtl/vecnorm_unit.sv` does (`:285`, `:331-333`), so N must be a
    power of two.  Every geometry shipped or studied so far is
    (H = 1024 / 2048 / 4096) — **Qwen3.5-4B's H = 2560 is not**, and that is
    feasibility-study wall 2 (§2.3) reaching the host reference model.  The
    golden phase is pure torch and is unaffected, so it is allowed through:
    the cache is useful the moment a normalizer exists.
    """
    if args.golden:
        return
    import layer_ref as LR
    from model_select import TAG
    n = LR.H
    if (1 << int(np.log2(n))) != n:
        raise SystemExit(
            f"REFUSING: FABLE5_MODEL={TAG} has H={n}, which is NOT a power of "
            "two.\n"
            "  The fixed-point normalizer (layer_fixed.rmsnorm_fx, mirroring\n"
            "  rtl/vecnorm_unit.sv:285,331-333) produces N only by shifting\n"
            "  `cfg_nlog2` and folds 1/N into the rsqrt binary point, so there\n"
            f"  is no representation for N={n}.\n"
            "  This is docs/QWEN35_NEXT_FEASIBILITY.md §2.3 (wall 2): "
            "supporting it\n"
            "  needs a reciprocal multiply in the normalizer datapath — an RTL\n"
            "  decision on the layer critical path, not a host patch.\n"
            "  Scoring it by normalizing over 2048 or 4096 instead would "
            "measure a\n"
            "  machine nobody has proposed, so this harness refuses rather "
            "than guesses.\n"
            "  (The float PPL ladder, ref/perplexity_eval.py, is unaffected: "
            "it uses\n"
            "   the torch model's own normalizer and scores WEIGHT damage "
            "only.)")


def main():
    global PROMPTS
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", action="store_true",
                    help="compute the torch golden and cache it, then exit")
    ap.add_argument("--cache", default=DEF_CACHE)
    ap.add_argument("--prompts", default="1,2,3,4")
    ap.add_argument("--ntok", type=int, default=3,
                    help="teacher-forced steps (bounded by the golden cache)")
    ap.add_argument("--free-ntok", type=int, default=None,
                    help="free-running generated tokens (default = --ntok); "
                         "needs no golden, so it can run much longer")
    ap.add_argument("--w4-group", default="128",
                    help="--ablate only: comma list of W4 group sizes to "
                         "evaluate in the FLOAT dequant model")
    ap.add_argument("--w4-rule", default="max",
                    help="--ablate only: comma list of group-scale rules "
                         "(max|mse)")
    ap.add_argument("--wire-group", default="128",
                    help="comma list of W4 WIRE group sizes (128|64) for the "
                         "end-to-end fixed-point run: the real quantizer, the "
                         "real datapath, i.e. exactly what a g=64 DDR image "
                         "scores.  128 is the shipped format")
    ap.add_argument("--w8", action="store_true",
                    help="V5: quantize EVERY matvec weight (all 24 layers "
                         "plus the LM head) to the 8-bit wire format "
                         "(w4a8_ref.quantize_weights8, SHAPE bit 29) instead "
                         "of W4.  The embedding table and the conv window "
                         "are not matvec weights and are unchanged.  W8 is "
                         "defined at g128 cadence only, and it has ONE "
                         "group-scale rule, so --wire-group must be 128 and "
                         "--mse/--qfix must keep their defaults")
    ap.add_argument("--res-scale", default="1")
    ap.add_argument("--qfix", default="0",
                    help="comma list of 0/1: W4 exponent tightening (only "
                         "implemented for the pre-Phase-1A max-rule "
                         "quantizer, i.e. needs --mse 0)")
    ap.add_argument("--mse", default="1",
                    help="comma list of 0/1: MSE-optimal W4 group scale. 1 is "
                         "the PRODUCTION quantizer since Phase 1A; 0 selects "
                         "the historical max|W_g|/7 rule")
    ap.add_argument("--no-freerun", action="store_true")
    ap.add_argument("--ablate", action="store_true",
                    help="float-only decomposition: exact vs W4-dequantized")
    ap.add_argument("--diag", default=None,
                    help="comma list of DIAGS keys: relax one frozen format")
    ap.add_argument("--trace", action="store_true",
                    help="per-layer residual error, fixed vs float(W4) decode")
    ap.add_argument("--blocks", type=int, default=-1,
                    help="per-block probe of layer N (DeltaNet)")
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--wq-cache", default=None,
                    help="G1: directory for the QUANTIZED-WEIGHT cache. The "
                         "quantized artifacts do not depend on the DeltaNet "
                         "state law or on RS_F, so a sweep over those can "
                         "reuse one 3.2 h quantization pass. Off by default; "
                         "the key is described at the top of this file")
    ap.add_argument("--wq-cache-verify", type=int, default=None,
                    help="G1: on a cache HIT, re-quantize this layer index "
                         "live and require it to be byte-identical to the "
                         "cached one — the mechanical proof that the cache "
                         "key is complete. ~320 s at 9B")
    ap.add_argument("--dn-probe", action="store_true",
                    help="G1: measure the DeltaNet state's rms, zero fraction "
                         "and log2-magnitude histogram at every PRE-narrowing "
                         "write. This is what says whether a container's "
                         "problem is RANGE or RESOLUTION")
    args = ap.parse_args()
    check_w8_flags(args)
    check_norm_geometry(args)
    if args.diag and args.wq_cache:
        # DIAGS relaxes FROZEN FORMAT CONSTANTS, and three of them
        # (DT_Q12_MIN / DT_Q12_MAX / A_Q15_MAX) are read by
        # `layer_fixed.quant_deltanet` — i.e. they change the quantized
        # artifacts.  Rather than widen the cache key with a knob nobody will
        # remember to keep in sync, the two are simply exclusive: a diag run
        # quantizes for itself.  Silently serving it a base-diag cache would
        # be a wrong number wearing a right label.
        raise SystemExit("--diag and --wq-cache are exclusive: DIAGS moves "
                         "DT_Q12_MIN/DT_Q12_MAX/A_Q15_MAX, which "
                         "quant_deltanet reads, so the cached artifacts are "
                         "not the ones this run means")
    # pin the quantizer-source digest NOW, before anything can edit ref/, and
    # print it: it is the mechanical statement that two runs of this harness
    # ran the same numeric path
    import layer_fixed as _LFS
    print(f"quantizer sources sha256 {_wq_source_sha()}  "
          f"(FABLE5_DN_STATE={_LFS.DN_STATE} RS_F={_LFS.RS_F})", flush=True)

    from gen_model_script import PROMPTS as P, _tokenizer_path, Tok
    PROMPTS = P
    prompts = [int(s) for s in args.prompts.split(",")]
    ids_by_seed = {p: list(PROMPTS[p][2]) for p in prompts}

    if args.golden:
        build_golden(ids_by_seed, args.ntok, args.cache)
        return

    if not os.path.exists(args.cache):
        raise SystemExit(f"no golden cache at {args.cache}; run with --golden "
                         f"under a torch-capable python first")
    golden = np.load(args.cache, allow_pickle=False)
    tp = _tokenizer_path()
    tok = Tok(tp) if tp else None

    import load_qwen35 as LQ
    from gen_model_script import quant_linear_big
    t0 = time.time()
    md = LQ.load_model()
    print(f"host: {socket.gethostname()}", flush=True)
    print(f"checkpoint: {md['path']}\n  header sha256 {md['header_sha256']} "
          f"(golden {str(golden['header_sha256'])})\n"
          f"  loaded in {time.time() - t0:.1f}s", flush=True)
    assert str(golden["header_sha256"]) == md["header_sha256"], \
        "golden cache was built from a different checkpoint"

    if args.diag and (args.trace or args.blocks >= 0):
        # let the attribution modes see a relaxed/prototyped format too
        import layer_fixed as _LF0
        dg0 = args.diag.split(",")[0]
        for k, v in DIAGS[dg0].items():
            setattr(_LF0, k, v)
        print(f"  (diag {dg0} applied: {DIAGS[dg0]})")

    if args.ablate:
        ablate(md, golden, prompts, args.ntok,
               mse_scale=bool(int(args.mse.split(",")[0])), tok=tok,
               free_ntok=args.free_ntok,
               w4_groups=tuple(int(s) for s in args.w4_group.split(",")),
               w4_rules=tuple(args.w4_rule.split(",")))
        return
    if args.blocks >= 0:
        blockprobe(md, golden, prompts, args.ntok,
                   res_scale=int(args.res_scale.split(",")[0]),
                   layer=args.blocks)
        return
    if args.trace:
        trace(md, golden, prompts, args.ntok,
              res_scale=int(args.res_scale.split(",")[0]),
              mse_scale=bool(int(args.mse.split(",")[0])))
        return

    # `emb_f` is the LOOKUP table (the int16 Q7.8 residual seed); `head_f` is
    # the LM head that gets quantized to W4/W8.  They are the same matrix at
    # 0.8B/2B/4B and DIFFERENT tensors at 9B, so they must not be conflated —
    # the hardware has always emitted them as two independent images.
    emb_f = md["emb"]
    head_f = md["head"]
    t0 = time.time()
    mses = [bool(int(s)) for s in args.mse.split(",")]
    wgroups = [int(s) for s in args.wire_group.split(",")]
    for wg in wgroups:
        if wg not in (128, 64):
            raise SystemExit("--wire-group must be 128 and/or 64")
    heads = {}
    import layer_fixed as _LFH
    head_sal = _LFH.calib_salience("lm_head")        # None unless the plumb is on
    head_hess = _LFH.calib_hess("lm_head")           # None unless mode=gptq
    if _LFH.CALIB_STATS:
        import calib_stats as _CS
        _m = _CS.meta(_LFH.CALIB_STATS)
        print(f"  CALIBRATED quantizer active, mode={_LFH.CALIB_MODE} "
              f"(V3 salience / V4 h2 / V4 gptq)\n"
              f"    FABLE5_CALIB_STATS = {_LFH.CALIB_STATS}\n"
              f"    sha256 {_sha256_file(_LFH.CALIB_STATS)}\n"
              f"    model_tag={_m.get('model_tag')} "
              f"corpus={_m.get('corpus')} "
              f"tokens={_m.get('n_tokens_hooked')} "
              f"tensors={_m.get('n_tensors')}", flush=True)
        if _m.get("checkpoint_header_sha256") not in (None, md["header_sha256"]):
            raise SystemExit("FABLE5_CALIB_STATS was collected on a different "
                             "checkpoint than the one being scored")
    for ms in sorted(set(mses)):
        for wg in sorted(set(wgroups)):
            t0 = time.time()
            if (head_sal is not None or head_hess is not None) and not ms:
                raise SystemExit("salience/GPTQ weighting needs --mse 1")
            hkey = _wq_key("head", md, 1.0, False, ms, wg, args.w8)
            cached_head = _wq_load(args.wq_cache, hkey, "LM head")
            if cached_head is not None:
                heads[(ms, wg)] = cached_head
                print(f"  LM head from cache ({'W8' if args.w8 else 'W4'} "
                      f"g={wg}) e={cached_head['e']} sh={cached_head['sh']}",
                      flush=True)
                continue
            if args.w8:
                # the head is a matvec weight like any other (V5).  Same
                # row-chunking reason as quant_linear_big's: a one-shot
                # float64 temporary on the tied head is multiple GiB.
                from gen_model_script import ROWCHUNK
                heads[(ms, wg)] = _LFH.quant_linear_w8(head_f, g=wg,
                                                       rowchunk=ROWCHUNK)
            else:
                heads[(ms, wg)] = quant_linear_big(head_f, mse_scale=ms, g=wg,
                                                   salience=head_sal,
                                                   hess=head_hess)
            print(f"  LM head quantized ({'W8' if args.w8 else 'W4'} "
                  + ("rule=max|W_g|/127 " if args.w8 else f"mse={ms} ")
                  + f"g={wg}) "
                  f"e={heads[(ms, wg)]['e']} sh={heads[(ms, wg)]['sh']} "
                  f"({time.time() - t0:.1f}s)", flush=True)
            _wq_save(args.wq_cache, hkey, heads[(ms, wg)], "LM head")

    scales = [int(s) for s in args.res_scale.split(",")]
    qfixes = [bool(int(s)) for s in args.qfix.split(",")]
    import layer_fixed as _LF
    diags = (args.diag or "base").split(",")
    allres = {}
    for dg in diags:
     for k in set().union(*[set(d) for d in DIAGS.values()]):
        if not hasattr(_LF, "_orig_" + k):
            setattr(_LF, "_orig_" + k, getattr(_LF, k))
        setattr(_LF, k, DIAGS[dg].get(k, getattr(_LF, "_orig_" + k)))
     for ms in mses:
      for qf in qfixes:
       for wg in wgroups:
        for S in scales:
            # R-c (T2 carry): "mse" names the W4 group-scale RULE, and W8 has
            # only one rule (max|W_g|/127).  check_w8_flags already pins
            # --mse to its default under --w8, so `ms` is True there for a
            # reason that has nothing to do with the image being scored —
            # printing it would be exactly the mislabel that check forbids.
            # G1: the state law and the residual binary point go in the ROW
            # LABEL, for the same reason --w8 does — a summary row that does
            # not say which container produced it is a number nobody can
            # interpret afterwards.  Both are silent at their defaults, so
            # every committed row keeps the label it already has.
            name = (f"S={S}" + (" qfix" if qf else "")
                    + (" mse" if ms and not args.w8 else "")
                    + ("" if wg == 128 else " g64")
                    + (" w8" if args.w8 else "")
                    + (f" {_LFH.CALIB_MODE}" if _LFH.CALIB_STATS else "")
                    + ("" if _LF.DN_STATE == "int16" else f" {_LF.DN_STATE}")
                    + ("" if _LF.RS_F == 8 else f" rsf{_LF.RS_F}")
                    + ("" if dg == "base" else f" {dg}"))
            print(f"\n=== config {name} ===", flush=True)
            t0 = time.time()
            r = run_config(md, golden, prompts, args.ntok, S, qf,
                           heads[(ms, wg)], emb_f,
                           freerun=not args.no_freerun, tok=tok, mse_scale=ms,
                           free_ntok=args.free_ntok, wire_group=wg,
                           w8=args.w8, wq_cache=args.wq_cache,
                           wq_verify=args.wq_cache_verify,
                           dn_probe=args.dn_probe)
            print(f"    config done in {time.time() - t0:.1f}s", flush=True)
            allres[name] = r
            report_one(name, r, prompts, tok)

    print("\n" + "=" * 78)
    print("SUMMARY  (teacher-forced on the golden trajectory)")
    print("=" * 78)
    # The seven columns the ladder's committed rows carry, PLUS the two G1
    # adds: the state container's own rail count and the state range that
    # centres it.  The seven are printed first and unchanged, so a row here is
    # still directly comparable with `LADDER.md` §4's.
    hdr = (f"{'config':<26}{'top1':>10}{'rank med':>10}{'rank max':>10}"
           f"{'top5 ovl':>10}{'|x|max':>9}{'clip':>7}{'S_F sat':>9}"
           f"{'S8 sat':>9}{'|S|max':>9}")
    print(hdr)
    for name, r in allres.items():
        t1 = [v for p in prompts for v in r[p]["top1"]]
        rk = [v for p in prompts for v in r[p]["rank"]]
        o5 = [v for p in prompts for v in r[p]["top5"]]
        xm = max(r[p]["resid_max"] for p in prompts)
        cl = sum(r[p]["resid_clip"] for p in prompts)
        ss = sum(r[p]["s_sat"] for p in prompts)
        dn = r.get("_dn", {})
        print(f"{name:<26}{sum(t1)}/{len(t1):<8}{np.median(rk):>10.1f}"
              f"{max(rk):>10d}{np.mean(o5):>10.2f}{xm:>9d}{cl:>7d}{ss:>9d}"
              f"{dn.get('sat8', 0):>9d}{dn.get('absmax', 0):>9d}")
    dn_name, dn0 = next(((n, r["_dn"]) for n, r in allres.items()
                         if r.get("_dn")), (None, {}))
    if dn0:
        print(f"\nstate container [{dn_name}]: FABLE5_DN_STATE={dn0['law']} "
              f"(law={dn0['law_kind']} k={dn0['k']}), RS_F={dn0['rs_f']}; "
              f"{dn0['writes']} state writes, |S|max {dn0['absmax']} LSB = "
              f"{dn0['absmax'] / (1 << dn0['s_f']):.4f} at Q2.{dn0['s_f']}, "
              f"int16 rail {dn0['sat16']}, container rail {dn0['sat8']}"
              + (f", per-row exponent e in [{dn0['e_min']},{dn0['e_max']}]"
                 if dn0['law_kind'] == 'int8e' else ""))
    print(f"weight quantization: {_WQ_STATE['quantized']} pass(es) this "
          f"process, {_WQ_STATE['hits']} cache hit(s), "
          f"{_WQ_STATE['misses']} miss(es)"
          + (f"; verify layer {_WQ_STATE['verified']['layer']} "
             f"{'BYTE-IDENTICAL' if _WQ_STATE['verified']['same'] else 'DIFFERS'}"
             if _WQ_STATE["verified"] else ""))
    # The G1 cost argument is about the CACHE: with one on, a process must
    # quantize at most once, and ideally not at all.  Without one, a process
    # legitimately quantizes once per config it scores (a --diag sweep is two
    # different quantizers by construction), so that is the bound there.
    _cap = 1 if args.wq_cache else len(allres)
    assert _WQ_STATE["quantized"] <= _cap, (
        f"the weight-quantization stage was entered {_WQ_STATE['quantized']} "
        f"times in one process for {len(allres)} config(s)"
        + (" WITH a --wq-cache, which is the cost the cache exists to remove"
           if args.wq_cache else ""))

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump({k: {str(kk): vv for kk, vv in v.items()}
                       for k, v in allres.items()}, f, indent=1, default=str)
        print(f"\n-> {args.json_out}")


def report_one(name, r, prompts, tok):
    print(f"  --- {name} ---")
    for p in prompts:
        e = r[p]
        print(f"  prompt {p} {PROMPTS[p][0]!r}")
        print(f"    golden argmax {e['golden_argmax']}"
              + (f"  text={tok.decode(e['golden_argmax'][len(PROMPTS[p][2]) - 1:])!r}"
                 if tok else ""))
        print(f"    fixed  argmax {e['fx_argmax']}   top1={sum(e['top1'])}"
              f"/{len(e['top1'])}  rank={e['rank']}  top5ovl={e['top5']}")
        if "free_gen" in e:
            print(f"    free-running gen={e['free_gen']} "
                  f"text={e['free_text']!r}")
    if r.get("_bf_k"):
        for k, v in r["_bf_k"].items():
            print(f"    block-float k histogram [{k}]: {v}")
    if r.get("_bf_clip"):
        c = r["_bf_clip"]
        print(f"    block-float saturation: m_q15 max raw {c['m_max']}, "
              f"clipped {c['m_q15']} ({c['m_q15_nonzero']} on non-zero "
              f"heads); attn k_a clamped to 0 {c['attn_k']} times")
    if r.get("_seq"):
        s = r["_seq"]
        n = max(int(s["n"]), 1)
        print(f"    SEQ eps-norm (on-chip integer scale vs the host float "
              f"m_q15): {s['n']} head norms, {s['exact']} bit-identical "
              f"({100.0 * s['exact'] / n:.1f}%), max |delta| {s['d_max']} "
              f"LSB (rel {s['rel_max']:.2e})")
        print(f"    SEQ eps-norm RTL envelope: k in [{s['k_min']},"
              f"{s['k_max']}], rsqrt p_in {s['p_min']}..{s['p_max']}, "
              f"v_max {s['v_max']}, out shift {s['sh_min']}..{s['sh_max']}, "
              f"scale max {s['scale_max']}, clamped {s['clip']}x")
    mv = r["_mv"]
    worst = sorted(mv.items(), key=lambda kv: -kv[1][1])[:4]
    print("    matvec int16-dequant headroom (|y| pre-clip16, clips):")
    for tag, (mx, nclip, ntot) in sorted(mv.items()):
        print(f"      {tag:<14} |y|max={mx:<8d} clips={nclip}/{ntot}")


if __name__ == "__main__":
    main()
