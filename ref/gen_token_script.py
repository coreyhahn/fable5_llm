#!/usr/bin/env python3
"""gen_token_script.py <outfile> <seed> [ntok] [vocab] [nlayers]

End-to-end autoregressive token script: embedding lookup -> <nlayers>
decoder layers (each in its own banked layer slot) -> final RMSNorm ->
LM head over the vocabulary -> on-chip argmax token out.  AUTOREGRESSIVE:
token t+1's embedding lookup uses token t's argmax output.

Layer set:
  nlayers == 2 (the DEFAULT, stage-4 legacy): exactly one DeltaNet layer
    followed by one full-attention layer, both on slot 0, and NO L records
    are emitted (the LAYER CSR stays at its reset value 0 == bank 0).
    This keeps the committed tb/scripts/token_s{1..4}.txt byte-identical.
  otherwise: layer_types[:nlayers] of the real Qwen3.5 config
    (ref/qwen3_5_0.8b_config.json, [3x linear_attention, 1x full_attention]
    repeating, 24 entries) with per-layer banked state selected by an L
    record (LAYER CSR = {kv_slot<<8, dn_slot}) before every use, exactly
    like gen_chain_script.py:
      dn_slot(layer i) = number of linear_attention layers among 0..i-1
      kv_slot(layer i) = number of full_attention  layers among 0..i-1
    24 layers therefore need 18 DN slots (0..17) and 6 KV slots (0..5);
    the layer's unused companion slot is clamped to the last bank (see
    slot_plan) since at 24 layers the running counts run one past it.

Like gen_layer_script / gen_chain_script the generator maintains an exact
scratchpad MODEL and SELF-CHECKS every layer's residual against
layer_fixed.layer_decode_fx via the R records inside dn_token /
attn_token, and the on-chip argmax against np.argmax; a flawed mapping
aborts here and never reaches simulation.

Reduced vocab (default 8192) justification: the RTL/host path is
identical for the full 248,320 vocab — matvec_chan already chunks rows
above RES_DEPTH and AMAX32 keeps a running winner across chained chunk
scans — only the chunk count grows (61 instead of 2). 8192 keeps sim
runtime and DDR images tractable and still exercises multi-chunk argmax.

Argmax semantics: over the RAW y32 LM-head accumulators. The per-matrix
dequant (uniform rshr across all rows) is monotonic, so argmax(y32) ==
argmax(logits); y32 itself is verified bit-exact by the V record on
hardware. np.argmax first-max-wins == AMAX32 strictly-greater update.

RNG ORDER (reproducible): with np.random.default_rng(seed),
  1. init_layer_weights(rng, layer_types[i]) for i = 0, 1, ... nlayers-1
     (each draws ln1, ln2, mlp, then attn|dn in layer_ref order),
  2. the final-norm weight ln_f  (H normals),
  3. the LM head matrix          (vocab x H normals),
  4. the embedding table         (vocab x H normals),
  5. the prompt token            (one integers(0, vocab) draw).
Steps 2-5 are unchanged from stage 4, and step 1 with nlayers==2 draws
exactly the stage-4 (DeltaNet, full-attention) pair — so the default
invocation reproduces the committed token_s*.txt bit for bit.
matvec weight-image ids (wid) are assigned in first-use order during the
token loop (layer 0 first, LM head last): 8 wids per DeltaNet layer, 7
per full-attention layer, +1 for the head (24 layers -> 187).

Emits alongside the script: <prefix>_w*.bin + <prefix>.weights.json
(matvec images, incl. the LM head) and <prefix>.emb.bin (embedding
table, int16 LE, vocab x 1024).
"""
import json
import os
import sys

import numpy as np

from gen_layer_script import (Mach, dn_token, attn_token,
                              X0, XN, X8, STG, I64, clip16)
from gen_chain_script import assign_slots
import layer_ref as LR
import layer_fixed as LF
from layer_fixed import RS_F

# stage-4 legacy pair: one DeltaNet + one full-attention layer, both on
# bank 0, no L records (see module docstring).
LEGACY_TYPES = ["linear_attention", "full_attention"]

# banked state depth in rtl/layer_chan.sv (mirrored by Mach.layer)
DN_SLOTS, KV_SLOTS = 18, 6


def load_layer_types(nlayers):
    """Layer types for an <nlayers>-deep stack.  nlayers==2 is the frozen
    stage-4 pair (NOT config layer_types[:2], which is 2x linear); every
    other depth comes from the real Qwen3.5 config."""
    if nlayers == 2:
        return list(LEGACY_TYPES)
    cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "qwen3_5_0.8b_config.json")))
    types = cfg["text_config"]["layer_types"]
    assert nlayers <= len(types), \
        f"nlayers={nlayers} exceeds config layer_types ({len(types)})"
    return types[:nlayers]


def slot_plan(layer_types):
    """(type, dn_slot, kv_slot) per layer: gen_chain_script's counting rule
    with the layer's UNUSED companion slot clamped into range.  At 24
    layers the running counts reach 18 DN / 6 KV — one past the last bank
    — and the L record must always carry concrete in-range slots.  A layer
    only ever touches the bank of its own kind (a DeltaNet layer issues no
    kvap/attn/T, a full-attention layer no conv/dnst/dnz), so the clamped
    companion slot is inert.  Below 24 layers nothing clamps and this is
    identical to gen_chain_script.assign_slots."""
    out = []
    for (lt, dn, kv) in assign_slots(layer_types):
        used, lim = ((kv, KV_SLOTS) if lt == "full_attention"
                     else (dn, DN_SLOTS))
        assert used < lim, f"{lt} layer wants slot {used} of {lim} banks"
        out.append((lt, min(dn, DN_SLOTS - 1), min(kv, KV_SLOTS - 1)))
    return out


def main():
    outfile, seed = sys.argv[1], int(sys.argv[2])
    ntok = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    vocab = int(sys.argv[4]) if len(sys.argv) > 4 else 8192
    nlayers = int(sys.argv[5]) if len(sys.argv) > 5 else 2
    rng = np.random.default_rng(seed)

    layer_types = load_layer_types(nlayers)
    emit_L = (nlayers != 2)          # legacy pair leaves the LAYER CSR at 0
    slots = slot_plan(layer_types)

    # ---------------- model pieces (RNG order: see docstring) ----------
    # Deep synthetic chains: GPT-2-style residual-projection scaling, or
    # the residual grows until the fixed-point matvec y32 range overflows
    # (post-draw multiply, RNG stream unchanged; legacy nlayers==2 -> 1.0).
    out_scale = 1.0 if nlayers == 2 else 1.0 / np.sqrt(2.0 * nlayers)
    layers = []                      # (type, qw, cache, dn_slot, kv_slot)
    for (lt, dn_slot, kv_slot) in slots:
        wf = LR.init_layer_weights(rng, lt, out_scale=out_scale)
        layers.append((lt, LF.quant_layer(wf), LF.new_cache_fx(lt),
                       dn_slot, kv_slot))
    ln_f = np.round(rng.normal(0, 0.5, LR.H) * (1 << 14)).astype(I64)
    ln_f = np.asarray(clip16(ln_f), dtype=I64)
    qw_head = LF.quant_linear(rng.normal(0, 1.0, (vocab, LR.H))
                              / np.sqrt(LR.H))
    emb = np.asarray(
        clip16(np.round(rng.normal(0, 1, (vocab, LR.H)) * (1 << RS_F))),
        dtype=I64)
    tok = int(rng.integers(0, vocab))          # prompt token

    with open(outfile, "w") as f:
        M = Mach(f)
        M.emb = emb

        # ------- static preamble: prime each layer's banked state -------
        for (lt, qw, cache, dn_slot, kv_slot) in layers:
            if emit_L:
                M.layer(dn_slot, kv_slot)
            if lt == "full_attention":
                M.Treset()                     # zero this kv_slot's TCNT
            else:
                qd = qw["dn"]
                for c in range(0, LR.CONV_DIM, 2048):
                    M.W(STG, qd["conv_w"][c:c + 2048].reshape(-1))
                    M.convw(c, 2048, STG)
                M.convz(0, LR.CONV_DIM)
                for h in range(LR.LNH):
                    M.dnz(h)

        # ---------------- autoregressive decode ----------------
        toks_out = []
        for t in range(ntok):
            # embedding lookup (device DDR on HW; .emb.bin in sim)
            M.embed(tok, X0, LR.H)
            x = M.emb[tok].copy()

            # chained layers (each asserts X0 == gold at its end)
            for (lt, qw, cache, dn_slot, kv_slot) in layers:
                if emit_L:
                    M.layer(dn_slot, kv_slot)
                gold = LF.layer_decode_fx(x, qw, cache, t)
                if lt == "full_attention":
                    attn_token(M, qw["attn"], qw["ln1"], qw["ln2"],
                               qw["mlp"], t, gold)
                else:
                    dn_token(M, qw["dn"], qw["ln1"], qw["ln2"],
                             qw["mlp"], gold)
                x = gold                        # feeds the next layer

            # final RMSNorm (1+w) + dynamic int8 quant
            M.W(STG, ln_f)
            M.vnw_(STG, 1024)
            M.vn(0, 1024, RS_F, RS_F, X0, XN)
            M.alu(0, 1024, 0, XN, 0, X8)

            # LM head matvec over the vocab (real matvec on HW via V)
            y32, _ = M.matvec(qw_head, X8, 1024)

            # on-chip argmax: chunks of 2048 pairs through staging
            for c in range(0, vocab, 2048):
                m = min(2048, vocab - c)
                M.W32(STG, y32[c:c + m])
                M.amax(m, STG, fresh=(c == 0))
            M.A()

            gold_tok = int(np.argmax(y32))
            assert M.am_idx == gold_tok, \
                f"model amax {M.am_idx} != np.argmax {gold_tok}"
            toks_out.append(gold_tok)
            tok = gold_tok                      # autoregressive feed

        print("Q", file=f)

    prefix = outfile.rsplit(".", 1)[0]
    nW = M.dump_weights(prefix)
    M.emb.astype("<i2").tofile(f"{prefix}.emb.bin")
    n_lin = sum(1 for lt, *_ in layers if lt != "full_attention")
    print(f"token script: seed={seed} ntok={ntok} vocab={vocab} "
          f"nlayers={nlayers} (DN={n_lin} GQA={nlayers - n_lin}) "
          f"cmds={M.ncmd} hostwords={M.nw} weights={nW} "
          f"tokens_out={toks_out} -> {outfile}")


if __name__ == "__main__":
    main()
