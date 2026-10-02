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
  otherwise: layer_types[:nlayers] of the real Qwen3.5 config (the
    FABLE5_MODEL-selected config JSON, [3x linear_attention, 1x
    full_attention] repeating, 24 entries) with per-layer banked state
    selected by an L record (LAYER CSR = {kv_slot<<8, dn_slot}) before
    every use, exactly like gen_chain_script.py:
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
table, int16 LE, vocab x H — H = 1024 at 0.8B, 2048 at 2B; the geometry
follows FABLE5_MODEL through ref/model_select.py).
"""
import json
import sys

import numpy as np

from gen_layer_script import (Mach, dn_token, attn_token,
                              X0, XN, X8, STG, H, I64, clip16,
                              _DN_LAYERS, _KV_LAYERS, K_DN, K_KV, K_CV,
                              sched_kv_prefetch, sched_dn_pair, sched_cv_pair,
                              sched_preamble, sched_token_end,
                              RS_F_MANIFEST_DEFAULT)
from gen_chain_script import assign_slots
import layer_ref as LR
import layer_fixed as LF
from layer_fixed import RS_F
from model_select import CONFIG_JSON

# stage-4 legacy pair: one DeltaNet + one full-attention layer, both on
# bank 0, no L records (see module docstring).
LEGACY_TYPES = ["linear_attention", "full_attention"]

# S3 (SEQ_ISA v2.1): what `slot_plan` returns is a LAYER INDEX, not a bank.
# The bound is therefore the DDR state IMAGE's extent (B15.1's 5-bit `layer`
# field), not the two cache slots the LAYER CSR now selects.  Imported from
# gen_layer_script rather than re-declared, so `Mach.layer`'s guard, the
# SLD/SST envelope and this clamp cannot drift apart.
DN_SLOTS, KV_SLOTS = _DN_LAYERS, _KV_LAYERS


def load_layer_types(nlayers):
    """Layer types for an <nlayers>-deep stack.  nlayers==2 is the frozen
    stage-4 pair (NOT config layer_types[:2], which is 2x linear); every
    other depth comes from the real Qwen3.5 config."""
    if nlayers == 2:
        return list(LEGACY_TYPES)
    cfg = json.load(open(CONFIG_JSON))
    types = cfg["text_config"]["layer_types"]
    assert nlayers <= len(types), \
        f"nlayers={nlayers} exceeds config layer_types ({len(types)})"
    return types[:nlayers]


def slot_plan(layer_types):
    """(type, dn_slot, kv_slot) per layer: gen_chain_script's counting rule
    with the layer's UNUSED companion slot clamped into range.  After the
    last layer of a kind the running count is one past that kind's last
    slot, and the L record must always carry concrete in-range slots.  A
    layer only ever touches the bank of its own kind (a DeltaNet layer
    issues no kvap/attn/T, a full-attention layer no conv/dnst/dnz), so the
    clamped companion slot is inert.  Below the full layer count nothing
    clamps and this is identical to gen_chain_script.assign_slots.

    THE CLAMP BOUND IS THIS MODEL'S LAYER COUNT, NOT THE BANK-ARRAY DEPTH,
    and G2a learned the difference from the byte-lock rather than by
    reasoning.  It used to clamp to `DN_SLOTS - 1` / `KV_SLOTS - 1`; when
    those grew 18/6 -> 24/8 for the 32-layer geometry, the 0.8B stream's
    LAST full-attention layer started emitting `L 00000512` instead of the
    frozen `L 00000511` — a byte move at a geometry nothing was supposed to
    touch, caught by `ref/scripts/regen_gate.sh` as `REGEN_GATE_FAIL`.
    Semantically the companion slot is still inert; the EMITTED BYTES are
    not, and this generator's contract is that they do not move.

    Clamping to the count of slots THIS MODEL uses is both the frozen
    behaviour (18 DN at 0.8B/2B -> `min(dn, 17)`, exactly as before) and the
    right rule at any geometry (24 DN at 4B/9B -> `min(dn, 23)`).  The bank
    depth stays the separate, larger bound the assert below checks against.
    """
    n_dn = sum(1 for t in layer_types if t != "full_attention")
    n_kv = sum(1 for t in layer_types if t == "full_attention")
    out = []
    for (lt, dn, kv) in assign_slots(layer_types):
        used, lim = ((kv, KV_SLOTS) if lt == "full_attention"
                     else (dn, DN_SLOTS))
        assert used < lim, f"{lt} layer wants slot {used} of {lim} banks"
        out.append((lt, min(dn, max(0, n_dn - 1)), min(kv, max(0, n_kv - 1))))
    return out


def main():
    # `--wq=w4|w8` (R-c) is the ONLY flag this generator takes.  Positional
    # parsing is unchanged and `--wq=w4` is the default, so every committed
    # artifact regenerates byte-identically.  This generator matters to R-c
    # for one reason: unlike gen_layer_script it emits a HEAD, so its stream
    # carries EMB / AMAXL / JMP — the three opcodes the 1-layer smoke has
    # zero coverage of, and the ones wall 8 lived behind.
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    wq = "w4"
    for fl in list(flags):
        if fl.startswith("--wq="):
            wq = fl.split("=", 1)[1]
            flags.discard(fl)
    if wq not in ("w4", "w8"):
        raise SystemExit("--wq must be w4 (default) or w8")
    if flags:
        raise SystemExit(f"unknown flags: {sorted(flags)}")
    w8 = (wq == "w8")
    outfile, seed = argv[0], int(argv[1])
    ntok = int(argv[2]) if len(argv) > 2 else 3
    vocab = int(argv[3]) if len(argv) > 3 else 8192
    nlayers = int(argv[4]) if len(argv) > 4 else 2
    rng = np.random.default_rng(seed)

    layer_types = load_layer_types(nlayers)
    # S3: the LAYER record is UNCONDITIONAL now.  Under v2.0 the legacy
    # stage-4 pair (nlayers == 2) left the CSR at 0 so its frozen bytes did
    # not move; under v2.1 the word carries cache slots and a kv_layer that
    # every body needs, and at the legacy pair those all happen to be 0, so
    # the emitted word is `L 00000000` either way.
    slots = slot_plan(layer_types)

    # ---------------- model pieces (RNG order: see docstring) ----------
    # Deep synthetic chains: GPT-2-style residual-projection scaling, or
    # the residual grows until the fixed-point matvec y32 range overflows
    # (post-draw multiply, RNG stream unchanged; legacy nlayers==2 -> 1.0).
    out_scale = 1.0 if nlayers == 2 else 1.0 / np.sqrt(2.0 * nlayers)
    layers = []                      # (type, qw, cache, dn_slot, kv_slot)
    for (lt, dn_slot, kv_slot) in slots:
        wf = LR.init_layer_weights(rng, lt, out_scale=out_scale)
        layers.append((lt, LF.quant_layer(wf, w8=w8), LF.new_cache_fx(lt),
                       dn_slot, kv_slot))
    ln_f = np.round(rng.normal(0, 0.5, LR.H) * (1 << 14)).astype(I64)
    ln_f = np.asarray(clip16(ln_f), dtype=I64)
    _hw = rng.normal(0, 1.0, (vocab, LR.H)) / np.sqrt(LR.H)
    qw_head = LF.quant_linear_w8(_hw) if w8 else LF.quant_linear(_hw)
    emb = np.asarray(
        clip16(np.round(rng.normal(0, 1, (vocab, LR.H)) * (1 << RS_F))),
        dtype=I64)
    tok = int(rng.integers(0, vocab))          # prompt token

    n_dn = sum(1 for t in layer_types if t != "full_attention")
    kv_pf = sched_kv_prefetch(layer_types)

    with open(outfile, "w") as f:
        M = Mach(f)
        M.emb = emb

        # ------- S3: the DDR state image, and the 6.4 preamble -------
        # The 768 DNZ and the CONVW loop are RETIRED: the conv taps go into
        # the image (the host uploads them) and the DN region is zero.
        for (lt, qw, cache, dn_l, kv_l) in layers:
            if lt != "full_attention":
                M.seed_conv(dn_l, qw["dn"]["conv_w"])
        sched_preamble(M, layer_types)

        # ---------------- autoregressive decode ----------------
        toks_out = []
        for t in range(ntok):
            # embedding lookup (device DDR on HW; .emb.bin in sim)
            M.embed(tok, X0, LR.H)
            x = M.emb[tok].copy()

            # chained layers (each asserts X0 == gold at its end)
            for i, (lt, qw, cache, dn_l, kv_l) in enumerate(layers):
                if lt == "full_attention":
                    M.layer(dn_l % 2, 0, dn_l % 2, kv_l)
                    gold = LF.layer_decode_fx(x, qw, cache, t)
                    attn_token(M, qw["attn"], qw["ln1"], qw["ln2"],
                               qw["mlp"], t, gold)
                else:
                    sched_dn_pair(M, dn_l, n_dn, kv_pf[i])
                    sched_cv_pair(M, dn_l, n_dn)
                    M.layer(dn_l % 2, 0, dn_l % 2, kv_l)
                    gold = LF.layer_decode_fx(x, qw, cache, t)
                    dn_token(M, qw["dn"], qw["ln1"], qw["ln2"],
                             qw["mlp"], gold)
                x = gold                        # feeds the next layer
            sched_token_end(M, n_dn)

            # final RMSNorm (1+w) + dynamic int8 quant
            M.W(STG, ln_f)
            M.vnw_(STG, H)
            M.vn(0, H, RS_F, RS_F, X0, XN)
            M.alu(0, H, 0, XN, 0, X8)

            # LM head matvec over the vocab (real matvec on HW via V)
            y32, _ = M.matvec(qw_head, X8, H)

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
    # R-b: this generator also emits an .emb.bin (rows of LR.H int16), so the
    # row stride MUST travel with the artifact — otherwise a 2B token script
    # would ship 4096 B rows under a key-absent manifest and every reader
    # would default to 2048 (EMBLOG2=11 -> half-row fetches).
    #
    # G4a: `rs_f` rides the same caller-gated path, VALUE-gated exactly as
    # the sibling generator `ref/gen_layer_script.py:2277` gates it (at the
    # default the key is withheld and every manifest this generator ever
    # wrote stays byte-identical; at any other value it must be written).
    # Without it `dump_weights` REFUSES at `FABLE5_RS_F=7` -- correctly, and
    # loudly: a reader defaults a missing key to 8 and would dequantize
    # every logit by a factor of two.  That refusal is what stopped the 9B
    # token-loop rung, so the fix is to state the value, never to drop the
    # guard.
    nW = M.dump_weights(prefix, emb_row_bytes=2 * LR.H,
                        rs_f=(RS_F if RS_F != RS_F_MANIFEST_DEFAULT
                              else None))
    M.emb.astype("<i2").tofile(f"{prefix}.emb.bin")
    n_lin = sum(1 for lt, *_ in layers if lt != "full_attention")
    print(f"token script: seed={seed} ntok={ntok} wq={wq} vocab={vocab} "
          f"nlayers={nlayers} (DN={n_lin} GQA={nlayers - n_lin}) "
          f"cmds={M.ncmd} hostwords={M.nw} weights={nW} "
          f"tokens_out={toks_out} -> {outfile}")


if __name__ == "__main__":
    main()
