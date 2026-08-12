#!/usr/bin/env python3
"""gen_chain_script.py <outfile> <seed> <ntok> <nlayers>

Emit a command script that replays an N-layer decoder stack (the first
<nlayers> layers of the real Qwen3.5 layer_types pattern) for <ntok>
tokens, with each layer's DeltaNet / KV-cache state living in its own
banked slot (the LAYER CSR selects the bank).  Like gen_layer_script /
gen_token_script the generator maintains an exact scratchpad MODEL and
SELF-CHECKS every layer's residual against layer_fixed.layer_decode_fx
via the R records inside dn_token / attn_token; a flawed mapping aborts
here and never reaches simulation.

This is the layer-stack gate only: NO embedding lookup, NO final norm,
NO LM head / argmax (those are gen_token_script's job).  The residual
entering layer 0 for each token is a fresh random Q7.8 vector (an
embedding stand-in), written to X0 before the per-token layer sweep.

Banking:
  dn_slot(layer i) = number of linear_attention layers among 0..i-1
  kv_slot(layer i) = number of full_attention  layers among 0..i-1
Each DeltaNet layer therefore gets a distinct dn_slot (0,1,2,...) and
each full-attention layer a distinct kv_slot (0,1,...).  For the first 8
layers of the real pattern that is 6 DN slots (0..5) and 2 KV slots
(0,1).  The "other" slot in each L record is the running count of the
opposite type (a valid, unused bank for that layer) — it is set only so
the LAYER CSR always holds concrete, in-range slots.

RNG ORDER (reproducible): with np.random.default_rng(seed),
  1. init_layer_weights(rng, type) for layer 0, then 1, ... nlayers-1
     (each draws ln1, ln2, mlp, then attn|dn in layer_ref order),
  2. then the per-token seed residuals x[0], x[1], ... x[ntok-1].
matvec weight-image ids (wid) are assigned in first-use order during the
token loop: layer 0 token 0 first, so wids run layer-by-layer.

Emits alongside the script: <prefix>_w{wid}.bin + <prefix>.weights.json
(same convention as gen_layer_script / gen_token_script — the host
runner and TB depend on it).
"""
import json
import os
import sys

import numpy as np

from gen_layer_script import (Mach, dn_token, attn_token, X0, STG, I64)
import layer_ref as LR
import layer_fixed as LF
from layer_fixed import RS_F


def load_layer_types(nlayers):
    cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "qwen3_5_0.8b_config.json")))
    types = cfg["text_config"]["layer_types"]
    assert nlayers <= len(types), \
        f"nlayers={nlayers} exceeds config layer_types ({len(types)})"
    return types[:nlayers]


def assign_slots(layer_types):
    """Per-layer (type, dn_slot, kv_slot). dn_slot = #linear before i,
    kv_slot = #full before i.  Both are always in range so the L record
    carries concrete slots even for the layer's unused bank."""
    out = []
    n_lin = n_full = 0
    for lt in layer_types:
        out.append((lt, n_lin, n_full))
        if lt == "full_attention":
            n_full += 1
        else:
            n_lin += 1
    return out


def main():
    outfile = sys.argv[1]
    seed = int(sys.argv[2])
    ntok = int(sys.argv[3])
    nlayers = int(sys.argv[4])
    rng = np.random.default_rng(seed)

    layer_types = load_layer_types(nlayers)
    slots = assign_slots(layer_types)

    # ---- weights + caches (RNG consumed in layer order 0..nlayers-1) ----
    layers = []          # (type, qw, cache, dn_slot, kv_slot)
    for (lt, dn_slot, kv_slot) in slots:
        wf = LR.init_layer_weights(rng, lt)
        qw = LF.quant_layer(wf)
        cache = LF.new_cache_fx(lt)
        layers.append((lt, qw, cache, dn_slot, kv_slot))

    # ---- per-token seed residuals (drawn after all weights) ----
    x_seeds = [np.round(rng.normal(0, 1, LR.H) * (1 << RS_F)).astype(I64)
               for _ in range(ntok)]

    with open(outfile, "w") as f:
        M = Mach(f)

        # ---- static preamble: prime each layer's banked state once ----
        for (lt, qw, cache, dn_slot, kv_slot) in layers:
            M.layer(dn_slot, kv_slot)
            if lt == "full_attention":
                M.Treset()                       # zero this kv_slot's TCNT
            else:
                qd = qw["dn"]
                for c in range(0, LR.CONV_DIM, 2048):
                    M.W(STG, qd["conv_w"][c:c + 2048].reshape(-1))
                    M.convw(c, 2048, STG)
                M.convz(0, LR.CONV_DIM)
                for h in range(LR.LNH):
                    M.dnz(h)

        # ---- decode: residual flows layer->layer within each token ----
        for t in range(ntok):
            x = x_seeds[t]
            M.W(X0, x)                           # residual entering layer 0
            for (lt, qw, cache, dn_slot, kv_slot) in layers:
                M.layer(dn_slot, kv_slot)
                gold = LF.layer_decode_fx(x, qw, cache, t)
                if lt == "full_attention":
                    attn_token(M, qw["attn"], qw["ln1"], qw["ln2"],
                               qw["mlp"], t, gold)
                else:
                    dn_token(M, qw["dn"], qw["ln1"], qw["ln2"],
                             qw["mlp"], gold)
                x = gold                         # feeds the next layer

        print("Q", file=f)

    prefix = outfile.rsplit(".", 1)[0]
    nW = M.dump_weights(prefix)
    n_lin = sum(1 for lt, *_ in layers if lt != "full_attention")
    n_full = nlayers - n_lin
    print(f"chain script: seed={seed} ntok={ntok} nlayers={nlayers} "
          f"(DN={n_lin} GQA={n_full}) cmds={M.ncmd} hostwords={M.nw} "
          f"weights={nW} -> {outfile}")


if __name__ == "__main__":
    main()
