#!/usr/bin/env python3
"""Windowed teacher-forced perplexity of Qwen3.5 under weight-quantization
injection.

The quantizers are the PRODUCTION ones (`layer_fixed.quant_linear` /
`gen_model_script.quant_linear_big` / the `gen_model_script` int16 embedding
rule): each selected weight matrix is quantized and dequantized, and the
DEQUANTIZED float matrix is loaded into the HF reference model.  So this
measures WEIGHT damage only, with float compute.  The fixed-point datapath is
scored separately by `fidelity_check.py`; the ablation ladder ties the two
together (weight damage vs datapath damage).

    FABLE5_MODEL=2b python3 ref/perplexity_eval.py \
        --corpus ref/ppl_corpus_eval.txt [--inject SPEC] [--window 512] \
        [--json-out F]

`--inject SPEC` grammar (binding — Tasks 5-9 drive this):

    SPEC  := ITEM ("," ITEM)*
    ITEM  := CLASS ":" QUANT
    CLASS := all | qkv | o_proj | gate_up | down | dn_in | dn_out | dn_conv
           | lm_head | emb
    QUANT := w4g128 | w4g64 | w4g64s | w8g128 | emb16 | cw13

  * a class not named in the spec stays at the checkpoint's bf16-upcast float
    (i.e. undamaged) — `--inject` absent == the bf16 anchor;
  * `all` expands to the seven W4A8 matvec classes
    (qkv, o_proj, gate_up, down, dn_in, dn_out, lm_head) — everything the
    W4 engine actually covers.  It deliberately does NOT include `emb` (the
    residual-seeding table is int16 Q7.8 in the HW, name it explicitly as
    `emb:emb16`) nor `dn_conv` (K=4, no W4 wire format);
  * items are applied left to right and a later item WINS, so
    `all:w4g128,down:w4g64` is "everything g128 except mlp.down at g64";
  * `w4g64s` is `w4g64` with the SAME wire format (INT4 nibbles, one uint16
    mantissa per group of 64, one shared exponent) and the salience-weighted
    group-scale search of `layer_fixed.quant_linear_mse` (Track Q V3).  It
    requires `--calib-stats FILE` (an `ref/calib_stats.py` npz for THIS
    model); the flag and the env plumb `FABLE5_CALIB_STATS` that
    `fidelity_check` uses feed the SAME production quantizer, there is no
    second implementation.  It is not valid on `emb`: the embedding table is
    a lookup, its "input" is a one-hot, so there is no activation salience;
  * `w8g128` is the 8-bit weight format (`w4a8_ref.quantize_weights8` and
    its `row_stride8` row layout — Track Q V5 "W8 everywhere" and the V4mix
    mixed maps).  Same (m uint16, e) group-scale encoding as W4, so it reuses
    the same verified dequantization; the row carries 64 weights per 64-byte
    beat instead of 128 and the same `ceil((K/g)/32)` scale beats.  It is
    MODELED only: no RTL reads a W8 image (see
    `evidence/qwen2b/q2/v4_v5/W8_SKETCH.md`);
  * `cw13` is the DeltaNet conv-weight format (int16 Q2.13, `layer_fixed.CW_F`)
    and is only valid on `dn_conv`; the default for `dn_conv` and for every
    norm / bias / A_log is FLOAT, matching what W4A8 covers;
  * `nvfp4` / `nvfp4h` (Task NV1, MODELED only) are the NVFP4 format of
    `ref/nvfp4.py` — E2M1 elements, one UE4M3 scale per 16 along K, one FP32
    tensor scale — the second with the weights pre-rotated by the block-16
    random Hadamard transform (`--rht-seed`, one sign vector per INPUT SITE,
    `calib_stats.hess_key`).  Valid on the seven W4 classes only.  An
    `nvfp4h` matrix is injected as Q(W R^T) R, so the float model computes
    Q(W') x' with x' = R x; `--act` hooks rotate the input with the SAME
    signs (asserted per site).

`--act SPEC` (Task NV1) fake-quantizes the INPUT of every matvec — every
`nn.Linear` of the body (a pre-hook; all must classify into the W4 classes)
and the LM head (applied in `compute_ppl`'s head path, the head being outside
the module tree): `a8` (the shipped per-vector power-of-two int8 rule,
`nvfp4.a8_fake_quant`), `nvfp4:dyn|static`, `nvfp4h:dyn|static` (block-16
NVFP4 with a per-token or a calibrated per-site tensor scale; `h` = the site
is RHT-rotated, which requires its weights to be `nvfp4h`).  A rotated site
(nvfp4h weights) is always quantized in the rotated basis, `a8` included.
Absent == float activations, exactly the pre-NV1 harness.

Model / tying.  The body is `Qwen3_5TextModel` loaded straight from the
safetensors shard exactly as `fidelity_check.py --golden` does (only
`model.language_model.*` keys — the `model.visual.*` tower and the top-level
`mtp.*` multi-token-prediction head are not part of the accelerator dataflow
and are never instantiated, so there is no missing/unexpected-key warning to
document).  `tie_word_embeddings: true` means the checkpoint carries ONE
matrix; the HW emits TWO images of it (the int16 Q7.8 lookup table and the W4
LM head), so this harness also keeps two INDEPENDENT float copies: the model's
`embed_tokens.weight` and a separate `head_w` used as `logits = h @ head_w.T`.
`emb:` and `lm_head:` therefore never leak into each other — asserted at build
time (distinct storage) and proven in `--selftest` (inject one, the other's
bytes are unchanged).

Prints `PPL <float>` as the LAST stdout line.

Expected stderr noise, once per run (stdout stays pristine): "The fast path is
not available because one of the required library is not installed. Falling
back to torch implementation." — flash-linear-attention / causal-conv1d are not
installed, so `linear_attn` uses the plain torch reference path.  That is the
SAME path `fidelity_check.py --golden` runs on, i.e. the path the whole 0.8B
and 2B golden flow is already validated against.

Geometry.  Nothing here is 0.8B-shaped: layer count, layer types, H, FFN and
the head counts all come from the selected `config.json`, and the tensor shapes
are cross-checked against `load_qwen35._EXPECT_*` before any weight is
injected.  Two things DO change with the checkpoint and are handled explicitly:
the shard count (0.8B/2B 1, 4B 2, 9B 4 — `CkptSource`) and whether the LM head
is the tied embedding matrix or its own top-level tensor
(`CkptSource.head`, `load_qwen35.checkpoint_is_tied`).
"""
import argparse
import hashlib
import json
import os
import socket
import sys
import time
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np                                              # noqa: E402
import torch                                                    # noqa: E402
from transformers.models.qwen3_5 import (Qwen3_5TextConfig,     # noqa: E402
                                         Qwen3_5TextModel)

import layer_fixed as LF                                        # noqa: E402
import load_qwen35 as LQ                                        # noqa: E402
import w4a8_ref as W                                            # noqa: E402
import gen_model_script as GMS                                  # noqa: E402
import nvfp4 as NV                                              # noqa: E402
from model_select import TAG                                    # noqa: E402

REF = os.path.dirname(os.path.abspath(__file__))
BIG_ROWS = GMS.ROWCHUNK          # above this many rows use the row-chunked
                                 # production quantizer (the tied head)


# ======================================================================
# class table — derived from load_qwen35's _EXPECT_* dicts
# ======================================================================
# loader key (load_qwen35._EXPECT_*)  ->  (injection class | None, HF suffix)
# None = the HW keeps it in a non-W4 format (norms, biases, A_log): float here.
_LOADER_MAP = OrderedDict([
    # _EXPECT_COMMON
    ("ln1",     (None,      "input_layernorm.weight")),
    ("ln2",     (None,      "post_attention_layernorm.weight")),
    # _EXPECT_MLP
    ("gate",    ("gate_up", "mlp.gate_proj.weight")),
    ("up",      ("gate_up", "mlp.up_proj.weight")),
    ("down",    ("down",    "mlp.down_proj.weight")),
    # _EXPECT_ATTN
    ("q_proj",  ("qkv",     "self_attn.q_proj.weight")),
    ("k_proj",  ("qkv",     "self_attn.k_proj.weight")),
    ("v_proj",  ("qkv",     "self_attn.v_proj.weight")),
    ("o_proj",  ("o_proj",  "self_attn.o_proj.weight")),
    ("q_norm",  (None,      "self_attn.q_norm.weight")),
    ("k_norm",  (None,      "self_attn.k_norm.weight")),
    # _EXPECT_DN
    ("in_qkv",  ("dn_in",   "linear_attn.in_proj_qkv.weight")),
    ("in_z",    ("dn_in",   "linear_attn.in_proj_z.weight")),
    ("in_b",    ("dn_in",   "linear_attn.in_proj_b.weight")),
    ("in_a",    ("dn_in",   "linear_attn.in_proj_a.weight")),
    ("out",     ("dn_out",  "linear_attn.out_proj.weight")),
    ("conv_w",  ("dn_conv", "linear_attn.conv1d.weight")),
    ("dt_bias", (None,      "linear_attn.dt_bias")),
    ("A_log",   (None,      "linear_attn.A_log")),
    ("norm_w",  (None,      "linear_attn.norm.weight")),
])

# model-level (not per layer)
_TOP_MAP = {"embed_tokens.weight": "emb", "norm.weight": None}

W4_CLASSES = ("qkv", "o_proj", "gate_up", "down", "dn_in", "dn_out", "lm_head")
ALL_CLASSES = W4_CLASSES + ("dn_conv", "emb")
QUANTS = ("w4g128", "w4g64", "w4g64s", "w4g64h", "w4g64gptq", "w4g128gptq",
          "w8g128", "emb16", "cw13", "nvfp4", "nvfp4h")
# Task NV1: the NVFP4 formats (`ref/nvfp4.py`).  Deliberately NOT in `_G_OF`:
# they have no (m uint16, e) group scale, and `ref/scripts/bytes_per_token.py`
# (E-pre) prices exactly the `_G_OF` quants — it does not price NVFP4.
NVFP4_QUANTS = ("nvfp4", "nvfp4h")
RHT_QUANTS = ("nvfp4h",)             # weights pre-rotated, per input site
# quants whose group-scale search consumes a per-input-channel weight vector
#   w4g64s : V3, mean|x| (`calib_stats.load`)
#   w4g64h : V4 ablation, sqrt(E[x^2]) (`calib_stats.load_h2`) — the exact
#            diagonal of the objective, same quantizer, one variable changed
SALIENT_QUANTS = ("w4g64s", "w4g64h")
# quants that consume the FULL input second moment E[x x^T] (`ref/gptq.py`)
# `w4g128gptq` is the SAME quantizer at the shipped g128 cadence — one group
# scale per 128 weights instead of 64, so it is bit-rate-identical to plain
# w4g128 and needs no wire-format change at all.  Added by Track L because the
# qwen-next ladder asks for GPTQ at the production group size as well as at the
# 2B study's g64.
HESSIAN_QUANTS = ("w4g64gptq", "w4g128gptq")
# everything that needs --calib-stats to mean anything
CALIB_QUANTS = SALIENT_QUANTS + HESSIAN_QUANTS
# in the binding grammar but not yet implementable — rejected at PARSE time so
# a bad spec costs nothing instead of failing after the model build + quantize.
# EMPTY as of Task 9: `w8g128`, the last reserved name, is implemented
# (`w4a8_ref.quantize_weights8` + `row_stride8`).  The mechanism stays because
# the grammar is the place where a future format is declared before it exists.
RESERVED_QUANTS = {}
# which quants each class accepts.  `emb` deliberately has NO salient quant:
# the embedding table is indexed, not multiplied, so no activation salience
# exists for it (see the module docstring).
_OK_QUANT = {c: ("w4g128", "w4g64", "w4g64s", "w4g64h", "w4g64gptq",
                 "w4g128gptq", "w8g128") + NVFP4_QUANTS for c in W4_CLASSES}
_OK_QUANT["emb"] = ("emb16", "w4g128", "w4g64", "w8g128")
_OK_QUANT["dn_conv"] = ("cw13",)

_SUFFIX_CLASS = {suf: cls for cls, suf in _LOADER_MAP.values()}
assert len(_SUFFIX_CLASS) == len(_LOADER_MAP), "duplicate HF suffix"


def _check_loader_map():
    """The class table must cover load_qwen35's expectations exactly.

    If a future loader change adds/renames a tensor, this fails loudly rather
    than silently leaving that tensor out of every quantization sweep.
    """
    keys = set()
    for d in (LQ._EXPECT_COMMON, LQ._EXPECT_MLP, LQ._EXPECT_DN, LQ._EXPECT_ATTN):
        keys |= set(d)
    if keys != set(_LOADER_MAP):
        raise SystemExit(
            "class table out of sync with load_qwen35._EXPECT_*: "
            f"loader-only={sorted(keys - set(_LOADER_MAP))} "
            f"table-only={sorted(set(_LOADER_MAP) - keys)}")


def _expect_shape(loader_key):
    for d in (LQ._EXPECT_COMMON, LQ._EXPECT_MLP, LQ._EXPECT_DN, LQ._EXPECT_ATTN):
        if loader_key in d:
            sh = d[loader_key]
            # the loader slices conv1d.weight[:, 0, :]; the raw param is 3-D
            return (sh[0], 1, sh[1]) if loader_key == "conv_w" else sh
    raise KeyError(loader_key)


def classify(name):
    """HF parameter name (prefix already stripped) -> injection class or None."""
    if name.startswith("layers."):
        rest = name.split(".", 2)[2]
        if rest not in _SUFFIX_CLASS:
            raise SystemExit(f"unknown per-layer tensor {name!r} — the class "
                             "table (derived from load_qwen35) does not cover it")
        return _SUFFIX_CLASS[rest]
    if name not in _TOP_MAP:
        raise SystemExit(f"unknown top-level tensor {name!r}")
    return _TOP_MAP[name]


def loader_key_of(name):
    """Inverse of the HF suffix, for the shape cross-check."""
    if not name.startswith("layers."):
        return None
    rest = name.split(".", 2)[2]
    for k, (_cls, suf) in _LOADER_MAP.items():
        if suf == rest:
            return k
    return None


def input_site(name):
    """HF parameter or module name of a W4-class matvec -> its INPUT SITE
    (`calib_stats.hess_key`: q/k/v share 'layers.i.attn_in', gate/up share
    'layers.i.mlp_in', ...; the head is 'lm_head').  NV1 keys the RHT sign
    vector and the static activation scale by this, because matrices that
    share an input must see ONE rotation and ONE quantization of it."""
    import calib_stats as CS
    return CS.hess_key(salience_key(name))


# ======================================================================
# --inject parsing
# ======================================================================
def parse_inject(spec):
    """'all:w4g128,emb:emb16' -> {class: quant}. Later items win."""
    plan = OrderedDict()
    if not spec:
        return plan
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        if item.count(":") != 1:
            raise SystemExit(f"--inject item {item!r} is not CLASS:QUANT")
        cls, q = (s.strip() for s in item.split(":"))
        if q not in QUANTS:
            raise SystemExit(f"--inject: unknown quant {q!r}, "
                             f"expected one of {', '.join(QUANTS)}")
        if q in RESERVED_QUANTS:            # fail now, not after an 80 s build
            raise SystemExit(RESERVED_QUANTS[q])
        if cls == "all":
            for c in W4_CLASSES:
                if q not in _OK_QUANT[c]:
                    raise SystemExit(f"--inject: quant {q!r} is not valid for "
                                     f"the 'all' expansion (class {c})")
                plan[c] = q
            continue
        if cls not in ALL_CLASSES:
            raise SystemExit(f"--inject: unknown class {cls!r}, expected one of "
                             f"all, {', '.join(ALL_CLASSES)}")
        if q not in _OK_QUANT[cls]:
            raise SystemExit(f"--inject: quant {q!r} is not valid for class "
                             f"{cls!r} (allowed: {', '.join(_OK_QUANT[cls])})")
        plan[cls] = q
    return plan


# ======================================================================
# dequantizers — production quantizer in, float matrix out
# ======================================================================
def _quant_w4(Wf, g, salience=None, hess=None):
    """The production W4 quantizer; row-chunked variant for the tied head.

    `gen_model_script.quant_linear_big` is bit-identical to
    `layer_fixed.quant_linear` (its docstring + `gen_model_script._selfcheck`,
    re-asserted in this file's --selftest); it exists so the 248320-row head
    does not need a multi-GiB float64 temporary.

    `salience` is the Track Q V3 per-input-channel weighting; None (the
    default) is the frozen unweighted MSE rule.  Both entry points take it,
    so `w4g64s` runs the SAME production code the DDR image generator does.

    `hess` is the Track Q V4 input second moment (a `gptq.HessFactor`), which
    selects `gptq.quant_linear_gptq`.  That function row-chunks internally —
    GPTQ's feedback stays inside a row — so it needs no separate big-matrix
    twin: the 248320-row head takes the same entry point as everything else.
    """
    Wf = np.asarray(Wf, dtype=np.float32)
    if Wf.ndim != 2:
        raise SystemExit(f"W4 needs a 2-D matrix, got shape {Wf.shape}")
    if Wf.shape[1] % g:
        raise SystemExit(f"W4 g={g}: K={Wf.shape[1]} is not a multiple of {g}")
    if salience is not None and np.asarray(salience).size != Wf.shape[1]:
        raise SystemExit(f"salience has {np.asarray(salience).size} entries "
                         f"but this matrix has K={Wf.shape[1]}")
    if hess is not None:
        return LF.quant_linear(Wf, mse_scale=True, g=g, hess=hess)
    if Wf.shape[0] > BIG_ROWS:
        return GMS.quant_linear_big(Wf, g=g, salience=salience)  # chunked
    return LF.quant_linear(Wf, mse_scale=True, g=g, salience=salience)


def dequant_from_q(q, rowchunk=BIG_ROWS):
    """{w4,m,e,g} -> the float matrix that image represents.

    Group scale = m * 2**(e-15).  That exponent is NOT a guess: it is what
    `w4a8_ref.quantize_weights` stores and what `matvec_y32` implies (result
    scale xs * 2**(e-15+sh)); `--selftest` re-derives it against matvec_y32 on
    random data before any PPL number is trusted.
    """
    w4, m, e, g = q["w4"], q["m"], q["e"], q["g"]
    N, K = w4.shape
    NG = K // g
    eff = m.astype(np.float64) * np.exp2(e - 15)                     # (N, NG)
    out = np.empty((N, K), dtype=np.float32)
    for r0 in range(0, N, rowchunk):
        r1 = min(r0 + rowchunk, N)
        blk = w4[r0:r1].reshape(r1 - r0, NG, g).astype(np.float64)
        out[r0:r1] = (blk * eff[r0:r1, :, None]).reshape(r1 - r0, K)
    return out


def dequant_w4(Wf, g, salience=None, hess=None):
    return dequant_from_q(_quant_w4(Wf, g, salience, hess))


def dequant_int16(Wf, frac, res_scale=1.0, rowchunk=BIG_ROWS):
    """int16 fixed-point round trip with `frac` fraction bits.

    frac = layer_fixed.RS_F (8, Q7.8)  -> the embedding table
           (gen_model_script.py:419-422)
    frac = layer_fixed.CW_F (13, Q2.13)-> the DeltaNet conv weights
           (layer_fixed.quant_deltanet, `conv_w`)

    `res_scale` S is the production residual scale-up: the HW stores
    round(w * S * 2**frac) and the whole residual stream is then S times
    larger, which RMSNorm makes float-invariant — so the effective weight is
    round(w*S*2**frac) / (S*2**frac), i.e. S extra bits of table resolution.
    S only ever matters HERE: for the W4 classes a power-of-two rescale shifts
    the shared exponent `e` and leaves w4/m/sh bit-identical (asserted in
    --selftest), so the dequantized W4 matrices are unchanged.
    """
    Wf = np.asarray(Wf, dtype=np.float32)
    if res_scale <= 0 or abs(np.log2(res_scale) - round(np.log2(res_scale))) > 0:
        raise SystemExit(f"--res-scale {res_scale} is not a positive power of 2")
    step = float(res_scale) * (1 << frac)
    flat = Wf.reshape(Wf.shape[0], -1)
    out = np.empty(flat.shape, dtype=np.float32)
    n_clip = 0
    for r0 in range(0, flat.shape[0], rowchunk):
        r1 = min(r0 + rowchunk, flat.shape[0])
        q = np.round(np.asarray(flat[r0:r1], dtype=np.float64) * step)
        n_clip += int(((q > 32767) | (q < -32768)).sum())
        out[r0:r1] = np.clip(q, -32768, 32767) / step
    if n_clip:
        raise SystemExit(f"int16 Q.{frac} round trip (res_scale={res_scale}) "
                         f"clipped {n_clip} weights at the int16 rail — the HW "
                         "format does not hold here")
    return out.reshape(Wf.shape)


def _quant_w8(Wf, g):
    """The W8 quantizer, returned in the same dict shape as the W4 path.

    `w4a8_ref.quantize_weights8` IS the W8 production rule — there is no
    second implementation and no separate big-matrix twin: its `rowchunk`
    argument (bit-identical, asserted in that file's `_selftest_w8`) is what
    keeps the 248320-row tied head off a 4 GiB float64 temporary, exactly
    as `quant_linear_big` does for W4.

    Note what is NOT here: the MSE group-scale search that `w4g128`/`w4g64`
    get from `layer_fixed.quant_linear_mse`.  W8 uses the max|W_g|/127 rule,
    so this scoring is a LOWER bound on W8 quality — a search could only
    improve it — which is the conservative direction for a variant whose
    whole case is "nearly lossless".  Quantified in
    `evidence/qwen2b/q2/v4_v5/V4_V5.md`.
    """
    Wf = np.asarray(Wf, dtype=np.float32)
    if Wf.ndim != 2:
        raise SystemExit(f"W8 needs a 2-D matrix, got shape {Wf.shape}")
    if Wf.shape[1] % g:
        raise SystemExit(f"W8 g={g}: K={Wf.shape[1]} is not a multiple of {g}")
    w8, m, e, sh = W.quantize_weights8(Wf, g=g, rowchunk=BIG_ROWS)
    return {"w4": w8, "m": m, "e": e, "sh": sh, "g": int(g)}


def dequant_w8(Wf, g):
    return dequant_from_q(_quant_w8(Wf, g))


def check_res_scale(res_scale, plan):
    """--res-scale must be a positive power of two AND must actually bite.

    Only `emb16` consumes it (a power-of-two rescale leaves every W4 image
    bit-identical), so recording res_scale=8 on a run with no emb16 in the plan
    would be a silently meaningless number in the json.
    """
    if res_scale <= 0 or float(res_scale) != 2.0 ** round(np.log2(res_scale)):
        raise SystemExit(f"--res-scale {res_scale} is not a positive power of 2")
    if res_scale != 1.0 and "emb16" not in plan.values():
        raise SystemExit(
            f"--res-scale {res_scale} has no effect on this --inject spec: only "
            "emb16 consumes it (W4 images are bit-identical under a "
            "power-of-two rescale). Add emb:emb16, or drop --res-scale.")


def check_calib_stats(path, plan):
    """--calib-stats must be present iff the spec asks for a salient quant.

    Same discipline as `check_res_scale`: a knob that does not bite is a
    number nobody can interpret in the json, and a salient quant without a
    salience file would silently be plain MSE under a different name.
    """
    salient = sorted(c for c, q in plan.items() if q in CALIB_QUANTS)
    if salient and not path:
        raise SystemExit(
            f"--inject asks for {plan[salient[0]]} on {', '.join(salient)} "
            "but --calib-stats was not given. Generate one with "
            "`FABLE5_MODEL=... python3 ref/calib_stats.py --corpus "
            "ref/ppl_corpus_calib.txt --out ref/calib_stats_<model>.npz`.")
    if path and not salient:
        raise SystemExit(
            f"--calib-stats {path} has no effect on this --inject spec: only "
            f"{'/'.join(CALIB_QUANTS)} consume calibration statistics. Drop "
            "the flag, or ask for one of those quants.")


def salience_key(name):
    """HF parameter name -> `calib_stats.tensor_key` name ('.weight' off)."""
    return name[:-len(".weight")] if name.endswith(".weight") else name


def calib_vector(quant, key, calib, calib_h2):
    """The per-input-channel weight vector `quant` wants for tensor `key`.

    V3's `w4g64s` reads mean|x| per TENSOR; V4's `w4g64h` reads E[x^2] per
    input SITE (matrices that share an input share the statistic) and hands
    it over as sqrt(), because `quant_linear_mse` squares what it is given.
    Returning None here is not a fall back to plain MSE — `apply_quant`
    rejects it — it is how a missing key becomes a loud error.
    """
    if quant == "w4g64s":
        return (calib or {}).get(key)
    if quant == "w4g64h":
        import calib_stats as CS
        v = (calib_h2 or {}).get(CS.hess_key(key))
        return None if v is None else np.sqrt(v.astype(np.float64))
    return None


def apply_quant(arr, quant, where, res_scale=1.0, salience=None, hess=None,
                rht_signs=None):
    if quant in RHT_QUANTS and rht_signs is None:
        raise SystemExit(f"{where}: {quant} needs its site's RHT sign vector")
    if rht_signs is not None and quant not in RHT_QUANTS:
        raise SystemExit(f"{where}: {quant} does not consume an RHT")
    if quant == "nvfp4":
        return NV.fake_quant_weight(arr, rowchunk=BIG_ROWS)
    if quant == "nvfp4h":
        return NV.fake_quant_weight(arr, rht_signs, rowchunk=BIG_ROWS)
    if quant in SALIENT_QUANTS and salience is None:
        raise SystemExit(f"{where}: {quant} needs a salience vector and the "
                         "calibration file does not carry one for it")
    if salience is not None and quant not in SALIENT_QUANTS:
        raise SystemExit(f"{where}: {quant} does not consume salience")
    if quant in HESSIAN_QUANTS and hess is None:
        raise SystemExit(f"{where}: {quant} needs the input Hessian and the "
                         "calibration file does not carry one for it")
    if hess is not None and quant not in HESSIAN_QUANTS:
        raise SystemExit(f"{where}: {quant} does not consume a Hessian")
    if quant == "w4g128":
        return dequant_w4(arr, 128)
    if quant == "w4g64":
        return dequant_w4(arr, 64)
    if quant in ("w4g64s", "w4g64h"):
        return dequant_w4(arr, 64, salience)
    if quant == "w4g64gptq":
        return dequant_w4(arr, 64, None, hess)
    if quant == "w4g128gptq":
        return dequant_w4(arr, 128, None, hess)
    if quant == "w8g128":
        return dequant_w8(arr, 128)
    if quant == "emb16":
        return dequant_int16(arr, LF.RS_F, res_scale)
    if quant == "cw13":
        return dequant_int16(arr, LF.CW_F)
    raise SystemExit(f"{where}: unhandled quant {quant!r}")


_G_OF = {"w4g128": 128, "w4g64": 64, "w4g64s": 64, "w4g64h": 64,
         "w4g64gptq": 64, "w4g128gptq": 128, "w8g128": 128}


def format_bits_per_weight(quant):
    """IDEAL format rate: the INT4 nibble plus its share of one uint16 group
    scale.  This is NOT the storage footprint — it ignores the 64-byte beat
    padding of the DDR row format.  Use `packed_bits` for footprint."""
    return {None: 16.0,                    # bf16 checkpoint
            "w4g128": 4.0 + 16.0 / 128,
            "w4g64": 4.0 + 16.0 / 64,
            "w4g64s": 4.0 + 16.0 / 64,     # V3 = g64's wire format exactly
            "w4g64h": 4.0 + 16.0 / 64,     # V4 ablation, same wire format
            "w4g64gptq": 4.0 + 16.0 / 64,  # V4 GPTQ, same wire format
            "w4g128gptq": 4.0 + 16.0 / 128,   # GPTQ at the shipped cadence
            "w8g128": 8.0 + 16.0 / 128,
            "emb16": 16.0,
            "cw13": 16.0,
            "nvfp4": NV.IDEAL_BITS_PER_WEIGHT,    # 4 + 8/16 (NV1)
            "nvfp4h": NV.IDEAL_BITS_PER_WEIGHT}[quant]


def packed_bits(shape, quant):
    """Bits this matrix's DDR image ACTUALLY occupies — the production rate.

    For the W4 classes the row format is `w4a8_ref.row_stride(K, g)` bytes per
    row (weight beats + scale beats, 64 B each, tail zero-padded).  A scale
    beat is a WHOLE beat even when it carries only 8 uint16 mantissas, so the
    real rate sits above the ideal 4 + 16/g:

        K=1024 g128 -> 8w+1s beats = 576 B/row = 4.500 b/w  (ideal 4.125, +9%)
        K=2048 g128 -> 16w+1s      = 1088 B/row = 4.250 b/w (ideal 4.125, +3%)

    W8 rows use `w4a8_ref.row_stride8` — the same law with 64 weights per
    weight beat instead of 128 and the SAME scale-beat count:

        K=2048 g128 -> 32w+1s = 2112 B/row = 8.250 b/w (ideal 8.125, +1.5%)
        K=6144 g128 -> 96w+2s = 6272 B/row = 8.167 b/w (ideal 8.125, +0.5%)

    The bytes/token budget (`ref/scripts/bytes_per_token.py`) uses THESE
    numbers, not the ideal ones.
    """
    if quant in ("w4g128", "w4g64", "w4g64s", "w4g64h", "w4g64gptq",
                 "w4g128gptq"):
        N, K = shape
        return float(N * W.row_stride(K, _G_OF[quant]) * 8)
    if quant == "w8g128":
        N, K = shape
        return float(N * W.row_stride8(K, _G_OF[quant]) * 8)
    if quant in NVFP4_QUANTS:        # NV1: `nvfp4.row_stride` + FP32 s_t
        return NV.packed_bits(shape)
    return float(int(np.prod(shape))) * 16.0


# ======================================================================
# model build + injection
# ======================================================================
class CkptSource:
    """float32 tensors of the selected checkpoint, keys without the prefix.

    Sharded checkpoints are handled by `load_qwen35.SafeTensors`, which takes
    the whole shard list (4B: 2 shards, 9B: 4).  `paths` and `shard_shas` are
    carried into the json so a sharded run's provenance is as complete as a
    single-file run's.
    """

    def __init__(self, path=None, prefix=LQ.TEXT_PREFIX):
        self.paths = LQ.find_checkpoints(path)
        self.path = self.paths[0]
        self.st = LQ.SafeTensors(self.paths)
        self.prefix = prefix
        self._keys = sorted(k[len(prefix):] for k in self.st.keys()
                            if k.startswith(prefix))
        self.tied, self.head_key = LQ.checkpoint_is_tied(self.st)

    def keys(self):
        return list(self._keys)

    def get(self, name):
        return self.st.get(self.prefix + name)

    def head(self):
        """The LM head matrix.

        Tied (0.8B / 2B / 4B): a fresh copy of the embedding table — the HW
        emits two independent images of it and this harness keeps two
        independent float copies (module docstring).  Untied (9B): the
        checkpoint's own top-level `lm_head.weight`, which lives OUTSIDE the
        `model.language_model.` prefix and so is invisible to `keys()`.
        """
        if self.tied:
            return self.get("embed_tokens.weight")
        return self.st.get(self.head_key)


class DictSource:
    """In-memory source (used by --selftest's tiny model)."""

    def __init__(self, d, head_key=None):
        self.d = d
        self.path = "<synthetic>"
        self.paths = ["<synthetic>"]
        self.st = None
        self.head_key = head_key
        self.tied = head_key is None

    def keys(self):
        return sorted(k for k in self.d if k != self.head_key)

    def get(self, name):
        return np.array(self.d[name], dtype=np.float32)

    def head(self):
        return np.array(self.d[self.head_key if self.head_key
                               else "embed_tokens.weight"], dtype=np.float32)


def _writable_f32(arr):
    """C-contiguous writable float32 view/copy.

    The 36 F32 tensors of the shard (A_log, linear_attn.norm.weight) come back
    as read-only memmap views; `torch.from_numpy` warns on those even though we
    only ever read them.  Copy just those — the bf16 majority is already a
    fresh writable array out of `bf16_to_f32`, so nothing large is duplicated.
    """
    a = np.ascontiguousarray(arr, dtype=np.float32)
    return a if a.flags.writeable else a.copy()


def text_config(cfgd, attn_impl="eager"):
    """Same recipe as fidelity_check.build_golden (the verified golden path)."""
    allowed = Qwen3_5TextConfig().to_dict()
    cfg = Qwen3_5TextConfig(**{k: v for k, v in cfgd.items()
                               if k in allowed or k == "rope_parameters"})
    cfg._attn_implementation = attn_impl
    cfg.dtype = "float32"
    return cfg


def _rht_for(quant, site, rht_seed, rotations):
    """The RHT sign vector an `nvfp4h` matrix on `site` is rotated with
    (None for every other quant), recorded in `rotations`.  Two matrices of
    one site get the same vector by construction; recording checks it."""
    if quant not in RHT_QUANTS:
        return None
    signs = NV.rht_signs(rht_seed, site)
    if rotations is not None:
        if site in rotations and not np.array_equal(rotations[site], signs):
            raise SystemExit(f"site {site}: two RHT sign vectors")
        rotations[site] = signs
    return signs


def build_model(cfg, source, plan, verbose=True, check_shapes=True,
                res_scale=1.0, calib=None, calib_h2=None, hstore=None,
                rht_seed=0, rotations=None):
    """Instantiate + fill the model, injecting dequantized weights per `plan`.

    Returns (model, head_w, accounting).  `head_w` is the LM head: an
    INDEPENDENT float copy of the tied embedding matrix (see module docstring).

    NV1: an `nvfp4h` matrix is rotated with `nvfp4.rht_signs(rht_seed, site)`
    for its input site; `rotations` (a dict, if given) receives {site: signs}
    for every rotated site so the `--act` hooks can assert they rotate the
    input with the same vector.

    `calib` is the `ref/calib_stats.py` dict {tensor_key: float32[K]} used by
    the salient quants; a tensor whose key is absent from it while its class
    asks for a salient quant is a hard error in `apply_quant`, never a silent
    fall back to unweighted MSE.  `calib_h2` ({site: E[x^2]}) and `hstore`
    (a `calib_stats.HessStore`) are the V4 equivalents for `w4g64h` /
    `w4g64gptq` and are read from the same npz.
    """
    t0 = time.time()
    try:
        from transformers.modeling_utils import no_init_weights
        with no_init_weights():
            model = Qwen3_5TextModel(cfg)
    except Exception:                                       # pragma: no cover
        model = Qwen3_5TextModel(cfg)
    model = model.eval().float()

    params = dict(model.named_parameters())
    have = set(source.keys())
    want = set(params)
    missing = sorted(w for w in want - have if "inv_freq" not in w)
    unexpected = sorted(have - want)
    if missing or unexpected:
        raise SystemExit(f"state_dict mismatch: missing={missing[:8]} "
                         f"unexpected={unexpected[:8]}")

    def _slot(q):
        return {"quant": q, "n_matrices": 0, "n_weights": 0,
                "total_bits": 0.0, "format_bits": 0.0}

    acct = OrderedDict((c, _slot(plan.get(c))) for c in ALL_CLASSES)
    acct["_float"] = _slot(None)

    for name in sorted(want):
        arr = source.get(name)
        if check_shapes:
            lk = loader_key_of(name)
            if lk is not None and tuple(arr.shape) != tuple(_expect_shape(lk)):
                raise SystemExit(
                    f"{name}: shape {tuple(arr.shape)} != "
                    f"{tuple(_expect_shape(lk))} expected by "
                    f"load_qwen35._EXPECT_* ({lk}) — geometry mismatch")
        cls = classify(name)
        q = plan.get(cls) if cls else None
        if q:
            key = salience_key(name)
            sal = calib_vector(q, key, calib, calib_h2)
            hs = hstore.factor(key) if (q in HESSIAN_QUANTS and hstore) else None
            rs = _rht_for(q, input_site(name) if q in RHT_QUANTS else None,
                          rht_seed, rotations)
            arr = apply_quant(arr, q, name, res_scale, sal, hs, rs)
        with torch.no_grad():
            params[name].copy_(torch.from_numpy(_writable_f32(arr)))
        slot = acct[cls] if cls else acct["_float"]
        slot["n_matrices"] += 1
        slot["n_weights"] += int(arr.size)
        slot["total_bits"] += packed_bits(arr.shape, q)
        slot["format_bits"] += arr.size * format_bits_per_weight(q)
        del arr

    # --- the LM head ------------------------------------------------------
    # tied (0.8B/2B/4B): a SEPARATE copy of the embedding matrix.
    # untied (9B): the checkpoint's own top-level lm_head.weight.
    # Either way it is independent storage, asserted below.
    head = source.head()
    qh = plan.get("lm_head")
    if qh:
        # the head's input channels are the FINAL NORM's output — that is what
        # calib_stats hooks for the synthetic 'lm_head' key
        head = apply_quant(head, qh, "lm_head", res_scale,
                           calib_vector(qh, "lm_head", calib, calib_h2),
                           hstore.factor("lm_head")
                           if (qh in HESSIAN_QUANTS and hstore) else None,
                           _rht_for(qh, "lm_head", rht_seed, rotations))
    head_w = torch.from_numpy(_writable_f32(head))
    acct["lm_head"] = dict(_slot(qh), n_matrices=1, n_weights=int(head.size),
                           total_bits=packed_bits(head.shape, qh),
                           format_bits=head.size * format_bits_per_weight(qh))
    del head
    emb_p = model.get_input_embeddings().weight
    assert head_w.data_ptr() != emb_p.data_ptr() and \
        head_w.untyped_storage().data_ptr() != emb_p.untyped_storage().data_ptr(), \
        "LM head and embedding table share storage — tying not broken"

    total_bits = fmt_bits = 0.0
    total_w = total_m = 0
    for c, s in acct.items():
        n = max(s["n_weights"], 1)
        s["bits_per_weight"] = s["total_bits"] / n            # packed (DDR)
        s["format_bits_per_weight"] = s["format_bits"] / n    # ideal
        total_bits += s["total_bits"]
        fmt_bits += s["format_bits"]
        total_w += s["n_weights"]
        total_m += s["n_matrices"]
    acct["_total"] = {"quant": None, "n_matrices": total_m, "n_weights": total_w,
                      "total_bits": total_bits, "format_bits": fmt_bits,
                      "bits_per_weight": total_bits / max(total_w, 1),
                      "format_bits_per_weight": fmt_bits / max(total_w, 1)}
    if verbose:
        print(f"  model built + loaded in {time.time() - t0:.1f}s")
        print("    class    quant    mats   weights   packed  (ideal)   "
              "footprint   [packed = w4a8_ref.row_stride, beat padding included]")
        for c, s in acct.items():
            if s["n_weights"]:
                print(f"    {c:<8s} {str(s['quant'] or 'bf16'):<7s} "
                      f"{s['n_matrices']:4d} mats {s['n_weights'] / 1e6:9.3f} M "
                      f"{s['bits_per_weight']:6.3f} b/w "
                      f"({s['format_bits_per_weight']:6.3f}) "
                      f"{s['total_bits'] / 8 / 2**20:9.1f} MiB")
        sys.stdout.flush()
    return model, head_w, acct


# ======================================================================
# perplexity
# ======================================================================
def compute_ppl(model, head_w, ids, window=512, batch=1, pos_chunk=64,
                verbose=True, head_act=None, device=None):
    """Non-overlapping windowed teacher-forced NLL.

    Each window of W tokens contributes W-1 scored positions (position 0 has
    no in-window context).  Returns (nll_sum, n_positions, ppl).

    NV1: `head_act` (an `ActQuant.head`, or None) fake-quantizes the LM
    head's INPUT — the head matvec is done here, outside the module tree, so
    no module hook can reach it (Ruling C4).  `device` moves the token ids to
    the model's device (`--device cuda`); None leaves the CPU path untouched.
    """
    segs = [ids[i:i + window] for i in range(0, len(ids), window)]
    segs = [s for s in segs if len(s) >= 2]
    nll_sum, npos, t0 = 0.0, 0, time.time()
    i = 0
    while i < len(segs):
        grp = [segs[i]]
        while len(grp) < batch and i + len(grp) < len(segs) \
                and len(segs[i + len(grp)]) == len(grp[0]):
            grp.append(segs[i + len(grp)])
        i += len(grp)
        inp = torch.tensor(np.asarray(grp, dtype=np.int64), dtype=torch.long)
        if device is not None:
            inp = inp.to(device)
        with torch.no_grad():
            hs = model(input_ids=inp, use_cache=False).last_hidden_state
            if head_act is not None:
                hs = head_act(hs)
            B, T, _ = hs.shape
            tgt = inp[:, 1:]
            for c0 in range(0, T - 1, pos_chunk):
                c1 = min(c0 + pos_chunk, T - 1)
                logits = hs[:, c0:c1] @ head_w.T                 # (B, c, V)
                lse = torch.logsumexp(logits.float(), dim=-1)
                pick = logits.float().gather(
                    2, tgt[:, c0:c1, None]).squeeze(2)
                nll_sum += float((lse - pick).double().sum())
                npos += (c1 - c0) * B
        if verbose:
            print(f"  window {i}/{len(segs)}  positions={npos}  "
                  f"running PPL={np.exp(nll_sum / npos):.4f}  "
                  f"{time.time() - t0:.1f}s", flush=True)
    return nll_sum, npos, float(np.exp(nll_sum / npos))


# ======================================================================
# --act: activation fake-quantization (Task NV1)
# ======================================================================
ACT_SPECS = ("a8", "nvfp4:dyn", "nvfp4:static", "nvfp4h:dyn", "nvfp4h:static")
A8_RULE = ("per matvec input vector (= per token): power-of-two scale 2^e, e "
           "the smallest integer with round_half_away(amax/2^e) <= 127; x8 = "
           "clip(round_half_away(x/2^e), -127, 127) -- fixedpoint.dyn_quant_i8 "
           "as layer_fixed.matvec_fx feeds it, in float (no int16 input grid)")


def parse_act(spec):
    """'nvfp4h:static' -> (fmt, h16, mode)."""
    if spec not in ACT_SPECS:
        raise SystemExit(f"--act {spec!r}: expected one of {', '.join(ACT_SPECS)}")
    if spec == "a8":
        return "a8", False, "dyn"
    fmt, mode = spec.split(":")
    return "nvfp4", fmt == "nvfp4h", mode


class _IdentityCache:
    """One-entry cache keyed by tensor IDENTITY: the members of an input site
    (q/k/v, gate/up, the four DeltaNet in_proj_*) are handed the same tensor
    object in one forward (the identity `calib_stats.Collector` verifies), so
    the site's input is rotated and quantized once, not per matrix.  Holding
    the reference keeps the object alive, so `is` cannot alias a new tensor;
    a miss only costs a recompute."""

    def __init__(self):
        self.key = self.val = None

    def get(self, x, site):
        k = self.key
        if k is not None and k[0] is x and k[1] == x._version and k[2] == site:
            return self.val
        return None

    def put(self, x, site, val):
        self.key, self.val = (x, x._version, site), val


def _as_rows(x):
    return x.detach().to(device="cpu", dtype=torch.float64).numpy() \
        .reshape(-1, x.shape[-1])


class ActQuant:
    """Forward pre-hooks that fake-quantize the INPUT of every matvec.

    Hooked: every `nn.Linear` of the body — each must classify into a W4
    class, else this refuses — and the LM head through `head()`, which
    `compute_ppl` applies to the final norm's output.  A site whose weights
    were rotated (`rotations` from `build_model`) is quantized in the rotated
    basis, x -> R^T Q(R x), with the SAME signs (asserted per site against
    `nvfp4.rht_signs(rht_seed, site)`); `nvfp4h:*` requires every site to be
    rotated and `nvfp4:*` requires none to be.  `a8` follows the weights.
    """

    def __init__(self, spec, rotations, rht_seed, static_amax=None):
        self.spec = spec
        self.fmt, self.h16, self.mode = parse_act(spec)
        self.rotations = dict(rotations or {})
        self.rht_seed = rht_seed
        self.static_amax = static_amax
        if self.mode == "static" and not static_amax:
            raise SystemExit(f"--act {spec} needs calibrated per-site amax")
        self.sites = OrderedDict()                  # site -> class
        self.n_modules = OrderedDict()              # class -> hooked Linears
        self.handles = []
        self._cache = _IdentityCache()

    def _signs(self, site):
        signs = self.rotations.get(site)
        if self.fmt == "nvfp4" and self.h16 != (signs is not None):
            raise SystemExit(
                f"--act {self.spec}: site {site!r} weights are "
                f"{'' if signs is not None else 'NOT '}RHT-rotated — "
                f"{'nvfp4h:*' if signs is not None else 'nvfp4:*'} is the "
                "activation format that matches them")
        if signs is not None and not np.array_equal(
                signs, NV.rht_signs(self.rht_seed, site)):
            raise SystemExit(f"site {site!r}: the weight rotation is not "
                             f"rht_signs({self.rht_seed}, site)")
        return signs

    def quant_rows(self, x, site):
        """float64 (rows, K) -> the dequantized input the matvec sees."""
        signs = self._signs(site)
        xr = x if signs is None else NV.rotate(x, signs)
        if self.fmt == "a8":
            q = NV.a8_fake_quant(xr)
        elif self.mode == "dyn":
            q = NV.fake_quant_dynamic_rows(xr)
        else:
            q = NV.fake_quant(xr, NV.tensor_scale(self.static_amax[site]))
        return q if signs is None else NV.unrotate(q, signs)

    def apply(self, x, site):
        hit = self._cache.get(x, site)
        if hit is not None:
            return hit
        q = torch.from_numpy(self.quant_rows(_as_rows(x), site)
                             .reshape(tuple(x.shape))
                             ).to(device=x.device, dtype=x.dtype)
        self._cache.put(x, site, q)
        return q

    def _hook(self, site):
        def hook(mod, inp):
            return (self.apply(inp[0], site),) + tuple(inp[1:])
        return hook

    def attach(self, model):
        """Validate EVERY site first, then register: a refusal leaves the
        model with no hook at all."""
        todo = []
        for name, mod in model.named_modules():
            if not isinstance(mod, torch.nn.Linear):
                continue
            cls = classify(name + ".weight")
            if cls not in W4_CLASSES:
                raise SystemExit(f"--act: nn.Linear {name!r} is class {cls!r}, "
                                 "not a W4 matvec — refusing to guess")
            site = input_site(name)
            self._signs(site)
            if self.sites.setdefault(site, cls) != cls:
                raise SystemExit(f"site {site!r} mixes classes")
            self.n_modules[cls] = self.n_modules.get(cls, 0) + 1
            todo.append((mod, site))
        self._signs("lm_head")
        self.sites["lm_head"] = "lm_head"
        self.n_modules["lm_head"] = 1
        unhooked = sorted(set(self.rotations) - set(self.sites))
        if unhooked:
            raise SystemExit(f"rotated sites with no hook: {unhooked[:4]}")
        for mod, site in todo:
            self.handles.append(mod.register_forward_pre_hook(self._hook(site)))
        return self

    def head(self, hs):
        return self.apply(hs, "lm_head")

    def close(self):
        for h in self.handles:
            h.remove()
        self.handles = []

    def describe(self):
        by_cls = OrderedDict()
        for site, cls in self.sites.items():
            d = by_cls.setdefault(cls, {"sites": 0, "modules": 0})
            d["sites"] += 1
        for cls, n in self.n_modules.items():
            by_cls[cls]["modules"] = n
        return {"spec": self.spec, "format": self.fmt, "rht": self.h16,
                "tensor_scale": None if self.fmt == "a8" else self.mode,
                "rule": A8_RULE if self.fmt == "a8" else
                ("NVFP4 block-16 E2M1 + UE4M3 (RNE, ties to even), FP32 "
                 "tensor scale amax/(6*448) " +
                 ("per token" if self.mode == "dyn" else
                  "per site from the calibration pass")),
                "rotated_sites_quantized_rotated": sorted(
                    s for s in self.sites if s in self.rotations),
                "hooked_by_class": by_cls,
                "hooked_sites": dict(self.sites)}


class AmaxCalibrator:
    """Static tensor scales: per-site amax of the matvec INPUT over a corpus
    (Ruling C3), in the rotated basis where the weights are rotated.  Run on
    the model AS BUILT (weights injected) with FLOAT activations, through
    `calib_stats.run`'s windowing; the head site reads the final norm."""

    def __init__(self, model, rotations):
        self.rotations = dict(rotations or {})
        self.amax = {}
        self.n = 0
        self.handles = []
        self._cache = _IdentityCache()
        for name, mod in model.named_modules():
            if isinstance(mod, torch.nn.Linear):
                self.handles.append(mod.register_forward_pre_hook(
                    self._pre(input_site(name))))
        self.handles.append(model.norm.register_forward_hook(self._post()))

    def _rec(self, x, site):
        if self._cache.get(x, site) is not None:
            return
        r = _as_rows(x)
        if site in self.rotations:
            r = NV.rotate(r, self.rotations[site])
        self.amax[site] = max(self.amax.get(site, 0.0), float(np.abs(r).max()))
        self._cache.put(x, site, True)

    def _pre(self, site):
        def hook(mod, inp):
            self._rec(inp[0], site)
        return hook

    def _post(self):
        def hook(mod, inp, out):
            self._rec(out if not isinstance(out, tuple) else out[0], "lm_head")
        return hook

    def add_tokens(self, n):
        self.n += int(n)

    def close(self):
        for h in self.handles:
            h.remove()
        self.handles = []


def load_corpus_ids(path, tokenizer, max_tokens=None):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    ids = tokenizer(text, add_special_tokens=False)["input_ids"]
    if max_tokens:
        ids = ids[:max_tokens]
    return ids


def get_tokenizer():
    from transformers import AutoTokenizer
    snap = os.path.dirname(LQ.find_checkpoint())
    return AutoTokenizer.from_pretrained(snap), snap


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ======================================================================
# selftest
# ======================================================================
def _tiny_cfg():
    """Smallest Qwen3.5 text config that still has both layer types and a
    W4-legal K (hidden 256 = 2 groups of 128 / 4 groups of 64)."""
    return text_config(dict(
        hidden_size=256, intermediate_size=384, num_hidden_layers=2,
        layer_types=["linear_attention", "full_attention"],
        num_attention_heads=2, num_key_value_heads=1, head_dim=64,
        linear_num_key_heads=2, linear_key_head_dim=64,
        linear_num_value_heads=2, linear_value_head_dim=64,
        linear_conv_kernel_dim=4, attn_output_gate=True,
        vocab_size=512, rms_norm_eps=1e-6, full_attention_interval=2,
        max_position_embeddings=2048, mlp_only_layers=[],
        tie_word_embeddings=True))


def _tiny_source(cfg, seed=3):
    rng = np.random.default_rng(seed)
    H, F, V = cfg.hidden_size, cfg.intermediate_size, cfg.vocab_size
    LKD = cfg.linear_num_key_heads * cfg.linear_key_head_dim
    LVD = cfg.linear_num_value_heads * cfg.linear_value_head_dim
    CD = 2 * LKD + LVD
    d = {"embed_tokens.weight": rng.normal(0, .02, (V, H)),
         "norm.weight": rng.normal(0, .02, (H,))}

    def put(pre, shp):
        d[pre] = rng.normal(0, .02, shp)
    for i, t in enumerate(cfg.layer_types):
        p = f"layers.{i}."
        put(p + "input_layernorm.weight", (H,))
        put(p + "post_attention_layernorm.weight", (H,))
        put(p + "mlp.gate_proj.weight", (F, H))
        put(p + "mlp.up_proj.weight", (F, H))
        put(p + "mlp.down_proj.weight", (H, F))
        if t == "full_attention":
            NQ, NKV, HD = (cfg.num_attention_heads, cfg.num_key_value_heads,
                           cfg.head_dim)
            put(p + "self_attn.q_proj.weight", (2 * NQ * HD, H))
            put(p + "self_attn.k_proj.weight", (NKV * HD, H))
            put(p + "self_attn.v_proj.weight", (NKV * HD, H))
            put(p + "self_attn.o_proj.weight", (H, NQ * HD))
            put(p + "self_attn.q_norm.weight", (HD,))
            put(p + "self_attn.k_norm.weight", (HD,))
        else:
            put(p + "linear_attn.in_proj_qkv.weight", (CD, H))
            put(p + "linear_attn.in_proj_z.weight", (LVD, H))
            put(p + "linear_attn.in_proj_b.weight", (cfg.linear_num_value_heads, H))
            put(p + "linear_attn.in_proj_a.weight", (cfg.linear_num_value_heads, H))
            put(p + "linear_attn.out_proj.weight", (H, LVD))
            put(p + "linear_attn.conv1d.weight", (CD, 1, cfg.linear_conv_kernel_dim))
            put(p + "linear_attn.dt_bias", (cfg.linear_num_value_heads,))
            put(p + "linear_attn.A_log", (cfg.linear_num_value_heads,))
            put(p + "linear_attn.norm.weight", (cfg.linear_value_head_dim,))
    return DictSource(d)


def _refuses(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except SystemExit:
        return True
    return False


def selftest_nvfp4(cfg, src, ids, sites):
    """Section H of --selftest: the NV1 grammar, the weight path, and the
    --act hooks end to end on the tiny model.  `sites` is the tiny model's
    input-site set (section D3's `calib_stats` cross-check)."""
    import calib_stats as CS
    # grammar: the seven W4 classes only, no calibration needed
    assert list(parse_inject("all:nvfp4h").items()) == \
        [(c, "nvfp4h") for c in W4_CLASSES]
    for bad in ("emb:nvfp4", "dn_conv:nvfp4h", "qkv:nvfp4x"):
        assert _refuses(parse_inject, bad), bad
    check_calib_stats(None, parse_inject("all:nvfp4,down:nvfp4h"))
    for spec in ACT_SPECS:
        parse_act(spec)
    for bad in ("a4", "nvfp4", "nvfp4h:mid", "A8"):
        assert _refuses(parse_act, bad), bad
    # the weight path IS ref/nvfp4.py's, chunked or not
    rng = np.random.default_rng(41)
    Wv = rng.normal(0, 0.02, (300, 1024)).astype(np.float32)
    sg = NV.rht_signs(0, "layers.0.mlp_in")
    assert np.array_equal(apply_quant(Wv, "nvfp4", "t"),
                          NV.fake_quant_weight(Wv))
    assert np.array_equal(apply_quant(Wv, "nvfp4h", "t", rht_signs=sg),
                          NV.fake_quant_weight(Wv, sg))
    assert _refuses(apply_quant, Wv, "nvfp4h", "t")
    assert _refuses(apply_quant, Wv, "w4g128", "t", rht_signs=sg)
    assert format_bits_per_weight("nvfp4") == \
        format_bits_per_weight("nvfp4h") == 4.5
    assert packed_bits((7, 2048), "nvfp4h") == 7 * 1152 * 8 + 32
    print("  grammar (W4 classes only, no calib), apply_quant == "
          "nvfp4.fake_quant_weight, 4.5 b/w ideal, K=2048 row 1152 B + s_t")

    # every site rotated with rht_signs(seed, site), the head included
    rot = {}
    mh, hh, _ = build_model(cfg, src, parse_inject("all:nvfp4h"),
                            verbose=False, check_shapes=False, rht_seed=3,
                            rotations=rot)
    assert set(rot) == set(sites), (sorted(set(rot) ^ set(sites)))
    for site, s in rot.items():
        assert np.array_equal(s, NV.rht_signs(3, site))
    # the seed bites on the injected weights (the inert diag(D) H16 order
    # made every seed bit-identical — ref/nvfp4.py module docstring)
    m4, h4, _ = build_model(cfg, src, parse_inject("all:nvfp4h"),
                            verbose=False, check_shapes=False, rht_seed=4)
    assert not np.array_equal(h4.numpy(), hh.numpy())
    del m4, h4
    mods = dict(mh.named_modules())
    n_lin = sum(isinstance(m, torch.nn.Linear) for m in mods.values())
    aq = ActQuant("nvfp4h:dyn", rot, 3).attach(mh)
    assert sum(aq.n_modules.values()) == n_lin + 1 and set(aq.sites) == set(sites)

    # end to end on one hooked matvec: the float model computes Q(W') Q(R x)
    x = torch.from_numpy(np.random.default_rng(42).normal(
        0, 1, (3, 5, cfg.hidden_size)).astype(np.float32))
    for mname, site in (("layers.0.mlp.gate_proj", "layers.0.mlp_in"),
                        ("layers.1.self_attn.k_proj", "layers.1.attn_in")):
        y = mods[mname](x).detach().numpy().astype(np.float64)
        W0 = np.asarray(src.d[mname + ".weight"], dtype=np.float32) \
            .astype(np.float64)
        Wr = NV.rotate(W0, rot[site])
        Wq = NV.fake_quant(Wr, NV.tensor_scale(np.abs(Wr).max()))
        xq = NV.fake_quant_dynamic_rows(NV.rotate(
            x.numpy().astype(np.float64).reshape(-1, cfg.hidden_size),
            rot[site]))
        ref = (xq @ Wq.T).reshape(y.shape)
        err = float(np.abs(y - ref).max() / np.abs(ref).max())
        assert err < 1e-5, (mname, err)
    _n, _p, ppl_h = compute_ppl(mh, hh, ids, window=64, batch=2,
                                verbose=False, head_act=aq.head)
    assert np.isfinite(ppl_h) and aq._cache.key[2] == "lm_head"
    aq.close()
    assert not any(m._forward_pre_hooks for m in mh.modules())
    print(f"  all:nvfp4h rotates all {len(rot)} sites (head included) with "
          f"rht_signs(seed, site); --act hooks {n_lin} Linears + the head; "
          f"a hooked matvec == Q(W')Q(Rx) (rel err < 1e-5); PPL {ppl_h:.4f}")

    # a8 follows the shipped per-token rule on an unrotated build
    m0, h0, _ = build_model(cfg, src, parse_inject(""), verbose=False,
                            check_shapes=False)
    a8 = ActQuant("a8", {}, None).attach(m0)
    mod = dict(m0.named_modules())["layers.1.self_attn.q_proj"]
    y = mod(x).detach().numpy().astype(np.float64)
    W0 = np.asarray(src.d["layers.1.self_attn.q_proj.weight"],
                    dtype=np.float32).astype(np.float64)
    ref = (NV.a8_fake_quant(x.numpy().astype(np.float64)
                            .reshape(-1, cfg.hidden_size)) @ W0.T
           ).reshape(y.shape)
    assert float(np.abs(y - ref).max() / np.abs(ref).max()) < 1e-5
    a8.close()
    # a8 on a ROTATED build quantizes the rotated input (the weights decide)
    a8h = ActQuant("a8", rot, 3).attach(mh)
    assert set(a8h.describe()["rotated_sites_quantized_rotated"]) == set(sites)
    a8h.close()
    print("  a8 hook == nvfp4.a8_fake_quant per token (rel err < 1e-5); on "
          "an nvfp4h build it quantizes every site in the rotated basis")

    # the activation format must match the weight rotation, site by site
    rp = {}
    mp, _, _ = build_model(cfg, src, parse_inject("all:nvfp4"), verbose=False,
                           check_shapes=False, rotations=rp)
    rmix = {}
    mmix, _, _ = build_model(cfg, src, parse_inject("all:nvfp4h,down:nvfp4"),
                             verbose=False, check_shapes=False, rht_seed=3,
                             rotations=rmix)
    assert not rp and len(rmix) == len(sites) - cfg.num_hidden_layers
    for spec, m, r in (("nvfp4h:dyn", mp, rp), ("nvfp4:dyn", mh, rot),
                       ("nvfp4h:dyn", m0, {}), ("nvfp4h:dyn", mmix, rmix),
                       ("nvfp4:dyn", mmix, rmix)):
        assert _refuses(lambda: ActQuant(spec, r, 3).attach(m)), spec
        assert not any(mm._forward_pre_hooks for mm in m.modules()), spec
    # ... and the signs themselves are checked, not just their presence
    bad = {k: -v for k, v in rot.items()}
    assert _refuses(lambda: ActQuant("nvfp4h:dyn", bad, 3).attach(mh))
    print("  refused: nvfp4h acts on unrotated sites, nvfp4 acts on rotated "
          "ones, a mixed map with either, and signs != rht_signs(seed, site)")

    # static scales: per-site amax of the ROTATED input over a corpus
    cal = AmaxCalibrator(mh, rot)
    CS.run(mh, ids, cal, 64, 2, verbose=False)
    cal.close()
    assert set(cal.amax) == set(sites) and min(cal.amax.values()) > 0
    assert cal.n == len(ids)                 # 3 x 64 + a scored tail of 8
    one = AmaxCalibrator(mh, rot)
    inp = torch.tensor(np.asarray([ids[:64]], dtype=np.int64))
    hs = mh(input_ids=inp, use_cache=False).last_hidden_state
    one.close()
    want = float(np.abs(NV.rotate(_as_rows(hs), rot["lm_head"])).max())
    assert one.amax["lm_head"] == want, (one.amax["lm_head"], want)
    st = ActQuant("nvfp4h:static", rot, 3, cal.amax).attach(mh)
    _n, _p, ppl_s = compute_ppl(mh, hh, ids, window=64, batch=2,
                                verbose=False, head_act=st.head)
    st.close()
    assert np.isfinite(ppl_s)
    assert _refuses(lambda: ActQuant("nvfp4h:static", rot, 3, None))
    print(f"  static: {len(cal.amax)} site amax over {cal.n} tokens, the "
          f"head's == max|R hs| exactly; nvfp4h:static PPL {ppl_s:.4f}")


def selftest():
    ok = True
    print("--- A: dequant scale vs the production matvec (the arbiter) ---")
    worst_abs, worst_rel = 0.0, 0.0
    for seed in (1, 2, 3, 4):
        rng = np.random.default_rng(seed)
        for (N, K) in [(64, 256), (37, 3584), (128, 1024), (300, 2048)]:
            Wf = rng.normal(0, 0.02, (N, K)).astype(np.float32)
            x = rng.normal(0, 1.0, K)
            x8, _xs = W.quantize_acts(x)
            for g in (128, 64):
                q = _quant_w4(Wf, g)
                deq = dequant_from_q(q)
                y32 = W.matvec_y32(q["w4"], q["m"], q["sh"], x8, g=g)
                # the dequantized matrix, run through the SAME integer math,
                # must reproduce y32 to the single final rounding of `sh`
                ref = (deq.astype(np.float64) @ x8.astype(np.float64)) \
                    * np.exp2(15 - q["e"] - q["sh"])
                ad = float(np.abs(y32 - ref).max())
                rl = float(np.linalg.norm(y32 - ref) / np.linalg.norm(ref))
                worst_abs, worst_rel = max(worst_abs, ad), max(worst_rel, rl)
                assert ad <= 0.51, (N, K, g, seed, ad)
                assert rl < 1e-4, (N, K, g, seed, rl)
                # the reconstruction is exactly w4 * m * 2**(e-15)
                NG = K // g
                exact = (q["w4"].reshape(N, NG, g).astype(np.float64)
                         * (q["m"].astype(np.float64)
                            * np.exp2(q["e"] - 15))[:, :, None]).reshape(N, K)
                assert np.array_equal(deq, exact.astype(np.float32))
    # and the e-16 variant the brief sketched is off by exactly 2x
    q = _quant_w4(np.random.default_rng(9).normal(0, .02, (64, 256))
                  .astype(np.float32), 128)
    d15 = dequant_from_q(q)
    d16 = (q["w4"].reshape(64, 2, 128).astype(np.float64)
           * (q["m"].astype(np.float64) * np.exp2(q["e"] - 16))[:, :, None]
           ).reshape(64, 256)
    ratio = float(np.abs(d15).sum() / np.abs(d16).sum())
    assert abs(ratio - 2.0) < 1e-6, ratio     # 1e-6: d15 is stored float32
    print(f"  scale = m * 2**(e-15): max |y32-deq| = {worst_abs:.3f} lsb "
          f"(<= 0.51), max rel = {worst_rel:.2e}")
    print(f"  arbiter rejects m * 2**(e-16): it is {ratio:.1f}x too small")

    print("--- B: quant_linear_big == layer_fixed.quant_linear (bit for bit) ---")
    rng = np.random.default_rng(5)
    for (N, K) in [(300, 1024), (1024, 256)]:
        Wf = rng.normal(0, 0.03, (N, K)).astype(np.float32)
        for g in (128, 64):
            a = LF.quant_linear(Wf, mse_scale=True, g=g)
            b = GMS.quant_linear_big(Wf, g=g)
            assert np.array_equal(a["w4"], b["w4"]) and np.array_equal(a["m"], b["m"])
            assert a["e"] == b["e"] and a["sh"] == b["sh"] and a["g"] == b["g"]
    print("  identical for (300,1024) and (1024,256) at g=128 and g=64")

    print("--- C: int16 round trips vs the production formulas ---")
    emb_f = np.random.default_rng(4).normal(0, 0.05, (1000, 64)).astype(np.float32)
    prod = np.clip(np.round(np.asarray(emb_f, dtype=np.float64)
                            * np.float64(1.0) * (1 << LF.RS_F)),
                   -32768, 32767).astype("<i2")            # gen_model_script:419
    assert np.array_equal(dequant_int16(emb_f, LF.RS_F),
                          (prod.astype(np.float64) / (1 << LF.RS_F)).astype(np.float32))
    prod8 = np.clip(np.round(np.asarray(emb_f, dtype=np.float64)
                             * np.float64(8.0) * (1 << LF.RS_F)),
                    -32768, 32767).astype("<i2")
    assert np.array_equal(dequant_int16(emb_f, LF.RS_F, 8.0),
                          (prod8.astype(np.float64) / (8.0 * (1 << LF.RS_F))
                           ).astype(np.float32))
    # ...and res_scale is a no-op for W4: a power-of-two rescale only shifts
    # the shared exponent, so the DEQUANTIZED matrix is exactly S * the
    # unscaled one.  That is why --res-scale touches the emb16 path only.
    Wr = np.random.default_rng(8).normal(0, 0.02, (64, 256)).astype(np.float32)
    for g in (128, 64):
        a = _quant_w4(Wr, g)
        b = _quant_w4((Wr * np.float32(8.0)).astype(np.float32), g)
        assert np.array_equal(a["w4"], b["w4"]) and np.array_equal(a["m"], b["m"])
        assert b["e"] == a["e"] + 3 and b["sh"] == a["sh"]
        assert np.array_equal(dequant_from_q(b),
                              (dequant_from_q(a) * np.float32(8.0)))
    cw = np.random.default_rng(6).normal(0, 0.3, (256, 1, 4)).astype(np.float32)
    prod_cw = np.round(np.asarray(cw[:, 0, :], dtype=np.float64) * (1 << LF.CW_F))
    assert np.array_equal(dequant_int16(cw, LF.CW_F)[:, 0, :],
                          (prod_cw / (1 << LF.CW_F)).astype(np.float32))
    print(f"  emb16 == gen_model_script emb table (Q{15 - LF.RS_F}.{LF.RS_F} at "
          f"res_scale 1, Q{15 - LF.RS_F - 3}.{LF.RS_F + 3} at 8); "
          f"cw13 == quant_deltanet conv_w (Q{15 - LF.CW_F}.{LF.CW_F}); "
          f"W4 invariant to a power-of-2 res_scale (e shifts, w4/m/sh identical)")

    print("--- D: --inject grammar ---")
    assert list(parse_inject("all:w4g128,emb:emb16").items()) == \
        [(c, "w4g128") for c in W4_CLASSES] + [("emb", "emb16")]
    assert parse_inject("all:w4g128,down:w4g64")["down"] == "w4g64"
    assert parse_inject("all:w4g128,down:w4g64")["qkv"] == "w4g128"
    assert parse_inject("") == OrderedDict()
    for bad in ("qkv", "qkv:w2", "nope:w4g128", "dn_conv:w4g128", "emb:cw13",
                "dn_conv:w8g128", "qkv:emb16"):
        try:
            parse_inject(bad)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"parse_inject accepted {bad!r}")
    check_res_scale(1.0, parse_inject(""))
    check_res_scale(8.0, parse_inject("emb:emb16"))
    for rs, spec in ((8.0, "all:w4g128"), (3.0, "emb:emb16"), (0.0, "emb:emb16")):
        try:
            check_res_scale(rs, parse_inject(spec))
        except SystemExit:
            pass
        else:
            raise AssertionError(f"check_res_scale accepted {rs} with {spec!r}")
    assert not RESERVED_QUANTS, "a reserved quant is back; add it to the list"
    print("  expansion, later-wins override, per-class validity, "
          "and --res-scale must bite: all hold")

    print("--- D2: w4g64s (V3) grammar + the salience code path ---")
    assert list(parse_inject("all:w4g64s").items()) == \
        [(c, "w4g64s") for c in W4_CLASSES]
    for bad in ("emb:w4g64s", "dn_conv:w4g64s"):     # no salience exists there
        try:
            parse_inject(bad)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"parse_inject accepted {bad!r}")
    check_calib_stats("x.npz", parse_inject("all:w4g64s"))
    check_calib_stats(None, parse_inject("all:w4g64"))
    for path, spec in ((None, "all:w4g64s"), ("x.npz", "all:w4g64"),
                       ("x.npz", "")):
        try:
            check_calib_stats(path, parse_inject(spec))
        except SystemExit:
            pass
        else:
            raise AssertionError(f"check_calib_stats accepted {path} {spec!r}")
    assert salience_key("layers.3.mlp.gate_proj.weight") == \
        "layers.3.mlp.gate_proj"
    # THE cross-harness check.  This file derives a tensor's salience key from
    # the HF parameter name; fidelity_check's FxRunner derives it from
    # layer_fixed's internal weight names via calib_stats.tensor_key().  Two
    # independent derivations of the same string: if they ever disagreed, one
    # harness would silently weight a matrix by ANOTHER channel's salience and
    # both would still "work".  Require them to agree exactly, both ways.
    import calib_stats as _CS
    _cfg = _tiny_cfg()
    _want = set(_CS.expected_keys(_cfg.num_hidden_layers, _cfg.layer_types))
    _mine = set()
    for _n in _tiny_source(_cfg).keys():
        if classify(_n) in W4_CLASSES:
            _mine.add(salience_key(_n))
    _mine.add("lm_head")                       # the tied head, not in the body
    assert _mine == _want, (sorted(_mine - _want), sorted(_want - _mine))
    print(f"  the {len(_want)} salience keys this harness asks for are EXACTLY "
          "the ones calib_stats/fidelity_check produce (both directions)")
    # w4g64s is w4g64's WIRE FORMAT exactly: same rates, same packed bytes,
    # and a UNIFORM salience reproduces w4g64 bit for bit (the production
    # quantizer's own invariant, re-checked through this harness's entry point)
    assert format_bits_per_weight("w4g64s") == format_bits_per_weight("w4g64")
    assert packed_bits((7, 2048), "w4g64s") == packed_bits((7, 2048), "w4g64")
    rngv = np.random.default_rng(31)
    for (N, K) in ((64, 256), (300, 1024)):
        Wv = rngv.normal(0, 0.02, (N, K)).astype(np.float32)
        plain = apply_quant(Wv, "w4g64", "t")
        uni = apply_quant(Wv, "w4g64s", "t",
                          salience=np.ones(K, dtype=np.float32))
        assert np.array_equal(plain, uni), (N, K)
        skew = apply_quant(Wv, "w4g64s", "t",
                           salience=rngv.lognormal(0, 1.5, K).astype(np.float32))
        assert skew.shape == plain.shape and skew.dtype == plain.dtype
        assert not np.array_equal(skew, plain), "salience did not bite"
    for kw in ({"quant": "w4g64s", "salience": None},
               {"quant": "w4g64", "salience": np.ones(256, dtype=np.float32)}):
        try:
            apply_quant(np.zeros((8, 256), np.float32), kw["quant"], "t",
                        salience=kw["salience"])
        except SystemExit:
            pass
        else:
            raise AssertionError(f"apply_quant accepted {kw['quant']} with "
                                 f"salience={type(kw['salience'])}")
    print("  w4g64s == w4g64 wire format and reproduces it EXACTLY under a "
          "uniform salience; a skewed one changes the image; emb/dn_conv "
          "rejected; --calib-stats must bite")

    print("--- D3: w4g64h / w4g64gptq (V4) grammar + the Hessian code path ---")
    import gptq as _GQ
    assert list(parse_inject("all:w4g64gptq").items()) == \
        [(c, "w4g64gptq") for c in W4_CLASSES]
    assert list(parse_inject("all:w4g64h").items()) == \
        [(c, "w4g64h") for c in W4_CLASSES]
    for bad in ("emb:w4g64gptq", "dn_conv:w4g64h", "emb:w4g64h"):
        try:
            parse_inject(bad)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"parse_inject accepted {bad!r}")
    check_calib_stats("x.npz", parse_inject("all:w4g64gptq"))
    for path, spec in ((None, "all:w4g64gptq"), (None, "all:w4g64h")):
        try:
            check_calib_stats(path, parse_inject(spec))
        except SystemExit:
            pass
        else:
            raise AssertionError(f"check_calib_stats accepted {path} {spec!r}")
    # the SECOND cross-harness key check (see D2): the V4 statistics are per
    # input SITE, so this harness's site names must be exactly the ones
    # calib_stats collects — a mismatch would weight a matrix by ANOTHER
    # block's second moments and both harnesses would still appear to work.
    _sites = {_CS.hess_key(_k) for _k in _want}
    _mine_sites = {_CS.hess_key(_k) for _k in _mine}
    assert _mine_sites == _sites, (sorted(_mine_sites - _sites),
                                   sorted(_sites - _mine_sites))
    print(f"  the {len(_sites)} Hessian SITES this harness asks for are "
          f"EXACTLY calib_stats' (from {len(_want)} tensors, both directions)")
    for (N, K) in ((64, 256), (300, 1024)):
        Wv = rngv.normal(0, 0.02, (N, K)).astype(np.float32)
        d = rngv.lognormal(0, 1.0, K)
        # a DIAGONAL Hessian has no off-diagonal to feed back through, so
        # w4g64gptq must reproduce w4g64h EXACTLY through this entry point
        h2 = apply_quant(Wv, "w4g64h", "t", salience=np.sqrt(d))
        gq = apply_quant(Wv, "w4g64gptq", "t", hess=_GQ.factor(np.diag(d)))
        assert np.array_equal(h2, gq), (N, K)
        # ... and a correlated one must change the image, not its format
        A = rngv.normal(0, 1, (K + 16, K)) * np.sqrt(d)[None, :]
        cor = apply_quant(Wv, "w4g64gptq", "t",
                          hess=_GQ.factor((A.T @ A) / A.shape[0]))
        assert cor.shape == h2.shape and cor.dtype == h2.dtype
        assert not np.array_equal(cor, h2), "the Hessian did not bite"
    for kw in ({"quant": "w4g64gptq"}, {"quant": "w4g64", "hess": 1},
               {"quant": "w4g64h", "salience": None}):
        try:
            apply_quant(np.zeros((8, 256), np.float32), kw.pop("quant"), "t",
                        **kw)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"apply_quant accepted {kw}")
    for _q in ("w4g64h", "w4g64gptq"):
        assert format_bits_per_weight(_q) == format_bits_per_weight("w4g64")
        assert packed_bits((7, 2048), _q) == packed_bits((7, 2048), "w4g64")
    print("  w4g64gptq == w4g64h EXACTLY under a diagonal Hessian (no "
          "off-diagonal = no feedback); a correlated one changes the image; "
          "same wire format and bit rate as w4g64")

    print("--- D3b: w4g128gptq — GPTQ at the SHIPPED g128 cadence (Track L) ---")
    assert list(parse_inject("all:w4g128gptq").items()) == \
        [(c, "w4g128gptq") for c in W4_CLASSES]
    for bad in ("emb:w4g128gptq", "dn_conv:w4g128gptq"):
        try:
            parse_inject(bad)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"parse_inject accepted {bad!r}")
    check_calib_stats("x.npz", parse_inject("all:w4g128gptq"))
    try:
        check_calib_stats(None, parse_inject("all:w4g128gptq"))
    except SystemExit:
        pass
    else:
        raise AssertionError("check_calib_stats accepted w4g128gptq with no npz")
    # it is w4g128's WIRE FORMAT exactly — same ideal rate, same packed bytes —
    # so a g128 GPTQ image costs the board nothing over plain w4g128
    assert format_bits_per_weight("w4g128gptq") == format_bits_per_weight("w4g128")
    for _sh in ((7, 2048), (300, 1024), (11, 9216), (5, 12288)):
        assert packed_bits(_sh, "w4g128gptq") == packed_bits(_sh, "w4g128")
    for (N, K) in ((64, 256), (300, 1024)):
        Wv = rngv.normal(0, 0.02, (N, K)).astype(np.float32)
        d = rngv.lognormal(0, 1.0, K)
        # a DIAGONAL Hessian removes the feedback, so g128 GPTQ must land on
        # the same image as the plain g128 MSE search weighted by sqrt(d) —
        # the same invariant D3 checks at g64, at the shipped group size
        plain = apply_quant(Wv, "w4g128", "t")
        diag = apply_quant(Wv, "w4g128gptq", "t", hess=_GQ.factor(np.diag(d)))
        assert diag.shape == plain.shape and diag.dtype == plain.dtype
        A = rngv.normal(0, 1, (K + 16, K)) * np.sqrt(d)[None, :]
        cor = apply_quant(Wv, "w4g128gptq", "t",
                          hess=_GQ.factor((A.T @ A) / A.shape[0]))
        assert not np.array_equal(cor, diag), "the Hessian did not bite at g128"
        # and it is a DIFFERENT quantizer from the g64 one, not an alias
        g64 = apply_quant(Wv, "w4g64gptq", "t", hess=_GQ.factor(np.diag(d)))
        assert not np.array_equal(diag, g64)
    for kw in ({"quant": "w4g128gptq"},                      # no hess
               {"quant": "w4g128", "hess": 1}):              # hess not consumed
        try:
            apply_quant(np.zeros((8, 256), np.float32), kw.pop("quant"), "t",
                        **kw)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"apply_quant accepted {kw}")
    print("  w4g128gptq parses, needs --calib-stats, is BIT-RATE IDENTICAL to "
          "w4g128 (ideal and packed, K=1024/2048/9216/12288), the Hessian "
          "bites, and it is distinct from w4g64gptq")

    print("--- D4: w8g128 (V4mix / V5) grammar + the W8 code path ---")
    assert list(parse_inject("all:w8g128").items()) == \
        [(c, "w8g128") for c in W4_CLASSES]
    # the V4mix ladder's shape: W4 everywhere, the sensitive classes promoted
    _v4 = parse_inject("all:w4g64,gate_up:w8g128,lm_head:w8g128,emb:emb16")
    assert _v4["gate_up"] == _v4["lm_head"] == "w8g128"
    assert _v4["down"] == _v4["qkv"] == "w4g64" and _v4["emb"] == "emb16"
    for bad in ("dn_conv:w8g128", "qkv:w8g64"):
        try:
            parse_inject(bad)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"parse_inject accepted {bad!r}")
    check_calib_stats(None, parse_inject("all:w8g128"))   # W8 needs no calib
    # THE arbiter, for W8 this time (section A did it for W4): the matrix this
    # harness injects, run through the production integer matvec, must
    # reproduce the engine's y32 to the single final rounding of `sh`.  That is
    # what makes "scale = m * 2**(e-15)" the right reconstruction for W8 too.
    w8_abs = w8_rel = 0.0
    ratios = []
    for seed in (1, 2, 3, 4):
        rng8 = np.random.default_rng(100 + seed)
        for (N, K) in [(64, 256), (37, 3584), (300, 2048)]:
            Wf = rng8.normal(0, 0.02, (N, K)).astype(np.float32)
            x8, _xs = W.quantize_acts(rng8.normal(0, 1.0, K))
            q8 = _quant_w8(Wf, 128)
            deq8 = dequant_from_q(q8)
            y32 = W.matvec_y32(q8["w4"], q8["m"], q8["sh"], x8, g=128)
            ref = (deq8.astype(np.float64) @ x8.astype(np.float64)) \
                * np.exp2(15 - q8["e"] - q8["sh"])
            w8_abs = max(w8_abs, float(np.abs(y32 - ref).max()))
            w8_rel = max(w8_rel, float(np.linalg.norm(y32 - ref)
                                       / np.linalg.norm(ref)))
            assert w8_abs <= 0.51 and w8_rel < 1e-4, (N, K, seed)
            # the injected matrix is EXACTLY w8 * m * 2**(e-15) ...
            NG = K // 128
            exact = (q8["w4"].reshape(N, NG, 128).astype(np.float64)
                     * (q8["m"].astype(np.float64)
                        * np.exp2(q8["e"] - 15))[:, :, None]).reshape(N, K)
            assert np.array_equal(deq8, exact.astype(np.float32))
            # ... it is the w4a8_ref quantizer verbatim (no second rule) ...
            direct = W.quantize_weights8(Wf, g=128)
            assert np.array_equal(direct[0], q8["w4"]) and direct[2] == q8["e"]
            # ... and it beats the production W4 rule on the same matrix
            d4 = apply_quant(Wf, "w4g128", "t")
            r4 = float(np.linalg.norm(d4 - Wf) / np.linalg.norm(Wf))
            r8 = float(np.linalg.norm(deq8 - Wf) / np.linalg.norm(Wf))
            assert r4 / r8 > 4.0, (N, K, seed, r4, r8)
            ratios.append(r4 / r8)
            assert np.array_equal(apply_quant(Wf, "w8g128", "t"), deq8)
    for kw in ({"salience": np.ones(256, dtype=np.float32)}, {"hess": 1}):
        try:
            apply_quant(np.zeros((8, 256), np.float32), "w8g128", "t", **kw)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"apply_quant accepted w8g128 with {kw}")
    print(f"  scale = m * 2**(e-15) holds for W8: max |y32-deq| = {w8_abs:.3f} "
          f"lsb (<= 0.51), max rel = {w8_rel:.2e}")
    print(f"  w8g128 weight error beats the PRODUCTION w4g128 (MSE rule) by "
          f"{min(ratios):.1f}-{max(ratios):.1f}x; mixed V4mix specs parse; "
          "salience/Hessian rejected")

    print("--- E: DDR bit accounting is the PACKED rate, not the ideal one ---")
    assert format_bits_per_weight("w4g128") == 4.125
    assert format_bits_per_weight("w4g64") == 4.25
    for (K, g), exp in sorted({          # = row_stride(K,g)*8/K, beat padding in
            (1024, 128): 4.5, (1024, 64): 4.5,
            (2048, 128): 4.25, (2048, 64): 4.25,
            (3584, 128): 14848 / 3584, (3584, 64): 15360 / 3584,
            (6144, 128): 25600 / 6144, (6144, 64): 26112 / 6144}.items()):
        got = packed_bits((7, K), f"w4g{g}") / (7 * K)
        assert abs(got - exp) < 1e-12, (K, g, got, exp)
        assert abs(got - W.row_stride(K, g) * 8.0 / K) < 1e-12
    assert packed_bits((10, 64), "emb16") == 10 * 64 * 16.0
    assert format_bits_per_weight("w8g128") == 8.125
    for K, exp in sorted({          # = row_stride8(K,128)*8/K, beat padding in
            1024: 8.5, 2048: 8.25, 3584: 8.142857142857142,
            6144: 8.166666666666666}.items()):
        got = packed_bits((7, K), "w8g128") / (7 * K)
        assert abs(got - exp) < 1e-12, (K, got, exp)
        assert abs(got - W.row_stride8(K, 128) * 8.0 / K) < 1e-12
        # a W8 row is TWICE the W4 weight beats and the SAME scale beats
        assert W.row_beats8(K, 128)[0] == 2 * W.row_beats(K, 128)[0]
        assert W.row_beats8(K, 128)[1] == W.row_beats(K, 128)[1]
    print("  K=1024 g128 -> 4.500 b/w (ideal 4.125, +9.1%); "
          "K=2048 -> 4.250 (+3.0%); K=6144 g64 -> 4.250 (ideal 4.250)")
    print("  W8: K=1024 -> 8.500 b/w (ideal 8.125, +4.6%); K=2048 -> 8.250 "
          "(+1.5%); K=6144 -> 8.167 (+0.5%)")

    print("--- F: tied embedding / LM head independence (tiny model) ---")
    _check_loader_map()
    cfg = _tiny_cfg()
    src = _tiny_source(cfg)
    base = np.array(src.d["embed_tokens.weight"], dtype=np.float32)
    m0, h0, _ = build_model(cfg, src, parse_inject(""), verbose=False,
                            check_shapes=False)
    assert np.array_equal(m0.get_input_embeddings().weight.detach().numpy(), base)
    assert np.array_equal(h0.numpy(), base)
    m1, h1, _ = build_model(cfg, src, parse_inject("emb:emb16"), verbose=False,
                            check_shapes=False)
    e1 = m1.get_input_embeddings().weight.detach().numpy()
    assert not np.array_equal(e1, base), "emb:emb16 did not change the table"
    assert np.array_equal(h1.numpy(), base), "emb injection leaked into lm_head"
    m2, h2, _ = build_model(cfg, src, parse_inject("lm_head:w4g128"),
                            verbose=False, check_shapes=False)
    assert np.array_equal(m2.get_input_embeddings().weight.detach().numpy(), base), \
        "lm_head injection leaked into the embedding table"
    assert not np.array_equal(h2.numpy(), base), "lm_head:w4g128 did not change it"
    print("  emb-only injection leaves lm_head byte-identical, and vice versa")

    print("--- G: PPL loop smoke on the tiny model ---")
    ids = list(np.random.default_rng(2).integers(0, cfg.vocab_size, 200))
    nll, npos, ppl = compute_ppl(m0, h0, ids, window=64, batch=2, verbose=False)
    assert npos == 3 * 63 + 7, npos
    assert np.isfinite(ppl) and ppl > 1.0
    nll1, npos1, ppl1 = compute_ppl(m0, h0, ids, window=64, batch=1, verbose=False)
    assert npos1 == npos and abs(ppl1 - ppl) < 1e-3 * ppl, (ppl, ppl1)
    _n, _p, ppl_q = compute_ppl(m2, h2, ids, window=64, batch=1, verbose=False)
    print(f"  random-weight tiny model: {npos} positions, PPL={ppl:.4f} "
          f"(batch 1 vs 2 agree), lm_head:w4g128 -> {ppl_q:.4f}")

    print("--- H: NVFP4 quants + the --act hooks (Task NV1) ---")
    selftest_nvfp4(cfg, src, ids, _sites)

    print("\nPERPLEXITY_EVAL SELFTEST PASS" if ok else "FAIL")
    return 0 if ok else 1


# ======================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", help="pinned text corpus (ref/ppl_corpus_*.txt)")
    ap.add_argument("--expect-corpus-sha256", default=None,
                    help="REFUSE to score unless --corpus hashes to this. "
                         "The sha was recorded-but-never-checked until "
                         "2026-08-26; a campaign that claims a pinned corpus "
                         "should not be able to silently score a different "
                         "one.  Accepts a prefix of >=8 hex chars.")
    ap.add_argument("--inject", default="", help="CLASS:QUANT[,CLASS:QUANT...]")
    ap.add_argument("--window", type=int, default=512)
    ap.add_argument("--batch", type=int, default=4,
                    help="windows per forward (bigger = better CPU GEMMs; "
                         "measured bit-identical to batch=1, 2.2x faster)")
    ap.add_argument("--pos-chunk", type=int, default=64,
                    help="positions per LM-head chunk (memory only)")
    ap.add_argument("--max-tokens", type=int, default=0,
                    help="truncate the corpus (smoke runs only)")
    ap.add_argument("--res-scale", type=float, default=1.0,
                    help="production residual scale-up S (power of 2). Only "
                         "changes the emb16 table resolution; the W4 classes "
                         "are exactly invariant to it. Default 1.0 = Q7.8; "
                         "the 0.8B production build uses 8 (Q4.11).")
    ap.add_argument("--calib-stats",
                    help="ref/calib_stats.py npz of per-input-channel "
                         "activation statistics. Required by (and only by) "
                         f"the calibrated quants {'/'.join(CALIB_QUANTS)} "
                         "(the last two also need `--hessian` statistics); "
                         "it feeds "
                         "the SAME production quantizer that the "
                         "FABLE5_CALIB_STATS env plumb hands the fixed-point "
                         "path in fidelity_check.")
    ap.add_argument("--json-out")
    ap.add_argument("--checkpoint", help="explicit safetensors path")
    ap.add_argument("--attn-impl", default="eager")
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--act", default=None,
                    help=f"NV1: fake-quantize every matvec INPUT: "
                         f"{' | '.join(ACT_SPECS)} (absent = float)")
    ap.add_argument("--act-calib", default=None,
                    help="corpus for the static activation scales "
                         "(ref/ppl_corpus_calib.txt); required by, and only "
                         "by, --act nvfp4[h]:static")
    ap.add_argument("--rht-seed", type=int, default=None,
                    help="seed of the block-16 RHT sign vectors (default 0); "
                         "only meaningful with an nvfp4h quant")
    ap.add_argument("--device", choices=("cpu", "cuda"), default="cpu",
                    help="cuda = the model and head in fp16 on the GPU "
                         "(Ruling C2); cpu = the unchanged float32 path")
    a = ap.parse_args(argv)

    torch.set_grad_enabled(False)
    if a.threads:
        torch.set_num_threads(a.threads)
    _check_loader_map()

    if a.selftest:
        return selftest()
    if not a.corpus:
        ap.error("--corpus is required (or use --selftest)")

    t_start = time.time()
    plan = parse_inject(a.inject)
    check_res_scale(a.res_scale, plan)
    check_calib_stats(a.calib_stats, plan)
    act = parse_act(a.act) if a.act else None
    rotated = any(q in RHT_QUANTS for q in plan.values())
    if a.rht_seed is not None and not rotated:
        raise SystemExit("--rht-seed has no effect: no nvfp4h in --inject")
    rht_seed = (0 if a.rht_seed is None else a.rht_seed) if rotated else None
    static = act is not None and act[2] == "static"
    if static != bool(a.act_calib):
        raise SystemExit("--act-calib is required by, and only by, "
                         "--act nvfp4[h]:static")
    if static and os.path.basename(a.act_calib) == "ppl_corpus_eval.txt":
        raise SystemExit("--act-calib is the EVAL slice; calibrate on "
                         "ref/ppl_corpus_calib.txt")
    if static and a.device != "cpu":
        raise SystemExit("--act *:static calibrates on the CPU path only")
    calib = calib_sha = calib_meta = None
    calib_h2 = hstore = None
    if a.calib_stats:
        import calib_stats as CS
        calib = CS.load(a.calib_stats)
        calib_meta = CS.meta(a.calib_stats)
        calib_sha = sha256_file(a.calib_stats)
        if any(q == "w4g64h" for q in plan.values()):
            calib_h2 = CS.load_h2(a.calib_stats)
            if not calib_h2:
                raise SystemExit(
                    f"--inject asks for w4g64h but {a.calib_stats} carries no "
                    "E[x^2] — regenerate it with `ref/calib_stats.py --hessian`")
        if any(q in HESSIAN_QUANTS for q in plan.values()):
            hstore = CS.HessStore(a.calib_stats)
        if calib_meta.get("model_tag") not in (None, TAG):
            raise SystemExit(
                f"--calib-stats was collected on model "
                f"{calib_meta['model_tag']!r} but FABLE5_MODEL={TAG}")
    src = CkptSource(a.checkpoint)
    cfgd = dict(LQ.load_config())
    cfg = text_config(cfgd, a.attn_impl)
    tok, snap = get_tokenizer()
    corpus_sha = sha256_file(a.corpus)
    if a.expect_corpus_sha256:
        want = a.expect_corpus_sha256.strip().lower().rstrip("…").rstrip(".")
        if len(want) < 8 or not all(c in "0123456789abcdef" for c in want):
            raise SystemExit(
                f"--expect-corpus-sha256 {a.expect_corpus_sha256!r} is not a "
                f"hex prefix of at least 8 characters")
        if not corpus_sha.startswith(want):
            raise SystemExit(
                f"REFUSING: --corpus {a.corpus} hashes to\n"
                f"  {corpus_sha}\n"
                f"but --expect-corpus-sha256 requires it to start with\n"
                f"  {want}\n"
                f"This is the pinned-corpus gate.  Every number in a ladder "
                f"is only comparable to every other number scored on the "
                f"SAME corpus; scoring a different one silently is the "
                f"failure this refuses.")
        print(f"corpus gate PASS: sha256 starts {want} (checked before "
              f"tokenizing)")
    ids = load_corpus_ids(a.corpus, tok, a.max_tokens or None)

    print(f"model      FABLE5_MODEL={TAG}  {cfg.num_hidden_layers} layers  "
          f"H={cfg.hidden_size}  vocab={cfg.vocab_size}")
    print(f"checkpoint {src.path}")
    if len(src.paths) > 1:
        for p, s in zip(src.paths[1:], src.st.shard_shas[1:]):
            print(f"           {p}  ({s[:16]}…)")
    print(f"           header sha256 {src.st.header_sha}"
          + ("" if src.st.n_shards == 1
             else f"   (combined over {src.st.n_shards} shards)"))
    print(f"lm_head    {'tied (a separate copy of embed_tokens)' if src.tied else src.head_key}")
    print(f"tokenizer  {snap}")
    print(f"corpus     {a.corpus}\n           sha256 {corpus_sha}\n"
          f"           {len(ids)} tokens, window={a.window}, batch={a.batch}")
    print(f"inject     {a.inject or '(none — bf16 anchor)'}")
    if a.calib_stats:
        extra = ""
        if calib_h2 or hstore:
            extra = (f"\n           {len(calib_h2 or {})} E[x^2] vectors, "
                     f"{len(hstore.sites) if hstore else 0} Hessian sites "
                     f"(damp {hstore.percdamp if hstore else 0:g} of mean diag)")
        print(f"calib      {a.calib_stats}\n           sha256 {calib_sha}{extra}"
              f"\n           {len(calib)} tensors, "
              f"{calib_meta.get('n_tokens_hooked')} tokens from "
              f"{calib_meta.get('corpus')} "
              f"(sha256 {str(calib_meta.get('corpus_sha256'))[:16]}…)")
        if calib_meta.get("checkpoint_header_sha256") not in (None,
                                                              src.st.header_sha):
            raise SystemExit("--calib-stats was collected on a different "
                             "checkpoint than the one being scored")
    # host is RECORDED, not inferred: Track Q task 8 had to attribute results
    # to machines after the fact and only had torch version strings to go on
    print(f"host       {socket.gethostname()}")
    print(f"torch {torch.__version__}  threads={torch.get_num_threads()}",
          flush=True)

    rotations = {}
    model, head_w, acct = build_model(cfg, src, plan, verbose=not a.quiet,
                                      res_scale=a.res_scale, calib=calib,
                                      calib_h2=calib_h2, hstore=hstore,
                                      rht_seed=rht_seed, rotations=rotations)
    if hstore is not None:
        hstore.close()
    if rotated:
        print(f"rht        seed {rht_seed}: {len(rotations)} input sites "
              f"rotated (block 16, one sign vector per site)")
    t_model = time.time() - t_start

    aq = act_calib_rec = None
    t_act_calib = 0.0
    if act is not None:
        static_amax = None
        if static:
            t0 = time.time()
            import calib_stats as CS
            cal_ids = load_corpus_ids(a.act_calib, tok)
            cal = AmaxCalibrator(model, rotations)
            CS.run(model, cal_ids, cal, a.window, a.batch, verbose=not a.quiet)
            cal.close()
            static_amax = cal.amax
            t_act_calib = time.time() - t0
            act_calib_rec = {
                "corpus": os.path.relpath(a.act_calib, os.path.dirname(REF)),
                "corpus_sha256": sha256_file(a.act_calib),
                "n_tokens": cal.n, "n_sites": len(static_amax),
                "mode": "weights as injected, activations float",
                "site_amax": {k: static_amax[k] for k in sorted(static_amax)}}
            print(f"act calib  {a.act_calib}  sha256 "
                  f"{act_calib_rec['corpus_sha256']}\n           {cal.n} "
                  f"tokens, {len(static_amax)} sites, {t_act_calib:.1f}s")
        aq = ActQuant(a.act, rotations, rht_seed, static_amax).attach(model)
        print(f"act        {a.act}: {len(aq.sites)} input sites hooked "
              f"({sum(aq.n_modules.values())} matvecs incl. the head)")
    device = None
    if a.device == "cuda":
        device = torch.device("cuda")
        model = model.half().to(device)
        head_w = head_w.half().to(device)
        print(f"device     cuda fp16 {torch.cuda.get_device_name(0)}")

    t0 = time.time()
    nll, npos, ppl = compute_ppl(model, head_w, ids, a.window, a.batch,
                                 a.pos_chunk, verbose=not a.quiet,
                                 head_act=aq.head if aq else None,
                                 device=device)
    t_eval = time.time() - t0

    print(f"\nnll_sum {nll:.6f}  positions {npos}  "
          f"nll/pos {nll / npos:.6f}  eval {t_eval:.1f}s "
          f"(build {t_model:.1f}s)")

    if a.json_out:
        rec = {
            "model_tag": TAG, "inject": a.inject,
            "inject_resolved": dict(plan), "res_scale": a.res_scale,
            "calib_stats": a.calib_stats, "calib_stats_sha256": calib_sha,
            "calib_stats_meta": calib_meta,
            "calib_n_h2": len(calib_h2 or {}),
            "calib_n_hessian_sites": len(hstore.sites) if hstore else 0,
            "checkpoint": src.path, "checkpoint_header_sha256": src.st.header_sha,
            "checkpoint_paths": list(src.paths),
            "checkpoint_shard_sha256": list(src.st.shard_shas),
            "lm_head_tied": bool(src.tied), "lm_head_key": src.head_key,
            "geometry": {"n_layers": cfg.num_hidden_layers,
                         "hidden_size": cfg.hidden_size,
                         "intermediate_size": cfg.intermediate_size,
                         "vocab_size": cfg.vocab_size,
                         "n_dn_layers": list(cfg.layer_types).count("linear_attention"),
                         "n_full_attn_layers": list(cfg.layer_types).count("full_attention"),
                         "num_attention_heads": cfg.num_attention_heads,
                         "num_key_value_heads": cfg.num_key_value_heads,
                         "linear_num_key_heads": cfg.linear_num_key_heads,
                         "linear_num_value_heads": cfg.linear_num_value_heads},
            "corpus": os.path.relpath(a.corpus, os.path.dirname(REF)),
            "corpus_sha256": corpus_sha, "n_tokens": len(ids),
            "window": a.window, "batch": a.batch,
            "n_positions": npos, "nll_sum": nll, "nll_per_pos": nll / npos,
            "ppl": ppl,
            "classes": {c: s for c, s in acct.items()},
            "avg_bits_per_weight": acct["_total"]["bits_per_weight"],
            "avg_format_bits_per_weight":
                acct["_total"]["format_bits_per_weight"],
            "total_bits": acct["_total"]["total_bits"],
            "total_format_bits": acct["_total"]["format_bits"],
            "total_weights": acct["_total"]["n_weights"],
            "seconds_build": t_model, "seconds_eval": t_eval,
            "host": socket.gethostname(),
            "torch": torch.__version__,
            "threads": torch.get_num_threads(),
            "tokenizer_snapshot": snap,
            # --- Task NV1 (additive) ---
            "act": a.act, "act_resolved": aq.describe() if aq else None,
            "act_calib": act_calib_rec, "seconds_act_calib": t_act_calib,
            "rht_seed": rht_seed, "rht_n_sites": len(rotations),
            # absent in the rung-1 jsons written before the H.D correction,
            # whose rotation was the inert diag(D) H16 (see ref/nvfp4.py)
            "rht_form": NV.RHT_FORM if rotated else None,
            "device": a.device,
            "model_dtype": "float16" if a.device == "cuda" else "float32",
            # per-token DDR weight traffic = the packed matvec images (the
            # `ref/scripts/bytes_per_token.py` convention: emb excluded)
            "bytes_per_token_matvec":
                sum(acct[c]["total_bits"] for c in W4_CLASSES) / 8.0,
        }
        os.makedirs(os.path.dirname(os.path.abspath(a.json_out)), exist_ok=True)
        with open(a.json_out, "w") as f:
            json.dump(rec, f, indent=1, sort_keys=True)
        print(f"json -> {a.json_out}")

    print(f"PPL {ppl:.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
