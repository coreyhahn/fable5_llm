#!/usr/bin/env python3
"""gen_model_script.py <outfile> <prompt_seed> [ntok]

Stage-5 increment (3): the REAL Qwen3.5-0.8B, end to end, as a layer_chan
command script — real checkpoint weights for all 24 decoder layers, the
real embedding table, and the FULL 248,320-row LM head.  G2c: the head is
read from `load_qwen35.load_model()["head"]`, which is an independent COPY
of the embedding table where `tie_word_embeddings` is true (0.8B / 2B / 4B)
and the checkpoint's own `lm_head.weight` where it is false (9B).

    embedding lookup -> 24 banked decoder layers (18 DeltaNet + 6 GQA)
      -> final RMSNorm -> LM head over the whole vocabulary -> on-chip argmax

Same programming model as gen_token_script.py (which this file deliberately
mirrors): an L record selects the banked layer state before every use, the
generator keeps an exact scratchpad MODEL, and every layer's residual is
SELF-CHECKED against layer_fixed.layer_decode_fx before anything reaches
simulation.  What is new here is (a) real weights instead of Gaussian
draws, (b) the full vocabulary, and (c) a RUNTIME RANGE AUDIT that closes
the deferred, activation-dependent rows of ref/audit_ranges_report.md
section 5 and ABORTS generation if any format saturates.

------------------------------------------------------------------------
The three audit blockers, and how each is resolved (RTL is FROZEN)
------------------------------------------------------------------------
1. `model.norm` (final RMSNorm, 1+w convention): 976/1024 weights exceed
   int16 Q1.14 (max 1+w = 6.3125).  RESOLVED EXACTLY, no clamping: the
   VN command carries the norm MODE at runtime, and vecnorm mode 1 uses
   the wbuf value as a PLAIN multiplier (no +2^14 fold-in).  So we store
   the already-folded scale (1+w) at Q3.12 — |q|max 25856, 0/1024 out of
   range — and run mode 1 instead of mode 0.  The RTL multiply/shift pair
   is untouched (`rshr(y*w, 14)`), so the vecnorm output simply carries
   RS_F-2 = 6 fraction bits instead of 8.  That is harmless here: the only
   consumer is the DYNQ8 that feeds the LM head, and DYNQ8 renormalises by
   a power of two anyway (it just picks an exponent 2 smaller); the LM head
   result is used ONLY for argmax, which is invariant to a positive scale.
   Cost is one extra rounding of the int16 intermediate.

2. `dt_bias` (2/288 heads, max |dt| = 13.06 > 8.0 = the int16 Q3.12 rail of
   gate_unit dtv) and
3. `A = exp(A_log)` (1/288 heads, max A = 10.58 > 8.0 = the uint18 Q3.15
   rail of gate_unit Av): RESOLVED BY SATURATION (clamp) in
   layer_fixed.quant_deltanet.  Neither value can be rehomed into Q4.11 /
   Q4.14 without new ROM hex — the softplus PWL abscissa is hardwired to
   Q12 and `g = -rshr(A*sp, 11)` is hardwired to produce Q16 for the exp2
   ROM (full argument in the layer_fixed.py comment).  Clamping saturates
   where the ports as built WRAP: measured on the real weights, the worst
   affected head sees |decay_clamp - decay_spec| <= 2942/32768 across the
   whole `a` rail, against 32609/32768 when it wraps (0.0086 -> 0.9997, a
   fast-forgetting head turned into a never-forgetting one).  This script
   re-measures the same error at the ACTUAL runtime `a` values and reports
   it.  Widening dtv/Av + regenerating the softplus/exp2 ROMs is the
   documented future work.

------------------------------------------------------------------------
Runtime range audit (closes audit_ranges_report.md section 5)
------------------------------------------------------------------------
Mach.audit_on() makes the scratchpad model count, for every command that
writes int16 scratch, how many written words sit AT the int16 rail — a
true clip is always a rail hit, so "0 rail hits" PROVES no saturation
anywhere in the run.  DNST additionally counts true |S| > 32767 (the
layer_fixed.py S_F note), matvec records y32 occupancy and the DYNQ8
exponent histogram, and the residual peak is tracked per layer.  Any
violation ABORTS generation with the full report.

MEASURED on the real model (prompt_seed 1, 6 forward steps): S_F=13
saturates — |S| reaches 5.46 where int16 Q2.13 stops at 4.0, on 7 of
28.3M state writes.  S_F is NOT script-side: layer_chan.sv:773 hardwires
the v alignment as `{sa_q, 5'b0}` (<<(S_F-QKV_F)=<<5) and dn_step keeps
the state in 16-bit rows, so moving to Q3.12 is an RTL change and is out
of scope while the RTL is frozen.  Because the reference models exactly
the same clip the hardware performs, a saturating script is still
BIT-EXACT and still gates the engine; what it loses is numerical fidelity
to the float model.  `--allow-clip` accepts that trade explicitly and
prints a banner; without it the generator refuses to bless the script.

------------------------------------------------------------------------
Fidelity (Phase 1A of docs/FIDELITY_REDESIGN.md)
------------------------------------------------------------------------
The PRODUCTION datapath is layer_fixed's, and layer_fixed is now the one
truth: per-head block-floating of the DeltaNet output, the script-side
gated RMSNorm (with the reference eps), DN_NORM_F = 11 and the MSE-optimal
W4 group scale are all unconditional there and are simply what this script
emits.  The measured end-to-end result of that combination against the bf16
model is 15/24 top-1, rank median 0 (evidence/stage5/fidelity_phase1a_*.log
and the Phase-0 sweep it was selected from).  The `--mse-scale` and `--qfix`
flags of the pre-Phase-1A generator are GONE: mse is the production
quantizer, and the exponent-tightening variant is not implemented for it
(layer_fixed.quant_linear asserts).  The remaining fidelity knobs are:

--res-scale=S   (S a power of two)  Multiply the EMBEDDING TABLE and every
   residual-adding projection (attn.o_proj / dn.out / mlp.down, all 24
   layers) by S before quantizing.  RMSNorm is invariant to a positive
   scale of its input, so in FLOAT this is exactly a no-op: the residual
   stream, and only the residual stream, is S times bigger, while every
   norm output, every matvec input, the ln_f output and the final argmax
   are unchanged.  In fixed point it buys log2(S) bits of resolution
   exactly where the audit found the model starves — the embedding uses
   0.18% of int16 Q7.8 (audit section 4) — and spends int16 headroom:
   the measured residual peak is 2208/32767 (6.7%) on the worst of the
   four prompts, so S=8 lands at 53.9% of the rail (1.85x margin) and
   S=16 overflows.  Nothing else in the datapath moves: conv, the gate
   ports, DYNQ8 and the LM head all consume POST-NORM vectors.
   S=8 is the production setting (`make -C tb model_v2_script_s1`).

--w4-group=G    (128 | 64, default 128)  W4 quantization group size for
   EVERY matvec matrix including the LM head.  128 is the legacy wire
   format: with this flag absent (or =128) the emitted script, weight
   images and manifest are BYTE-IDENTICAL to the pre-v2 generator.  64 is
   the v2 row format: same nibble-packed weight beats, one uint16 scale per
   64 weights instead of per 128, so the row grows by one 64-byte scale
   beat once K > 2048 (only mlp.down, K=3584, does).  The manifest then
   carries "g": 64 per wid and the host sets SHAPE bit 28; ng (= K//128 =
   the WEIGHT-beat count — W4 ONLY, see ref/w4a8_ref.py's W8 section, where
   ng counts UNITS and a row is 2*ng weight beats) and nbeats/stride keep
   their meaning.  Measured
   worth: g=64 + the mse rule scores 18/24 top-1 vs bf16 where g=128 scores
   16/24 (evidence/stage5/fidelity_phase0_0c_w4strategy.log).  Requires the
   dual-mode matvec_engine to be on the board.

--wq=w4|w8      (default w4)  WEIGHT WIDTH of EVERY matvec matrix, the 24
   layers and the tied LM head alike.  `w8` is V5, the gate-D operating
   point (docs/QWEN2B_QUANT_STUDY.md): `layer_fixed.quant_linear_w8` ->
   `w4a8_ref.quantize_weights8`, int8 codes in [-127,127], the SAME
   (m, e, sh) encoding W4 uses, packed by `pack_ddr_rows8` and flagged
   `"w8": true` per wid in the manifest / `SHAPE` bit 29 in the stream.
   NOTHING else moves: the embedding table stays int16 Q7.8, the conv
   window stays Q2.13, every norm / gate / DYNQ8 immediate is unchanged
   (`layer_fixed._w8_invariance` asserts exactly that), so a W8 run is the
   same script with different weight images and one SHAPE bit.
   Constraints, all refused rather than ignored: g must be 128 (the W8 wire
   format has no g64 cadence), and the calibrated quantizers
   (FABLE5_CALIB_STATS: V3 salience / V4 h2 / gptq) are W4-only.
   The 2B W8 pack is 1,847 MiB nch-independent, which does NOT fit the
   1,280 MiB window — a W8 2B artifact set is emitted with `SEQ_NCH=4
   SEQ_REPACK=1` (docs/USAGE.md), where the busiest channel holds 465 MiB.

------------------------------------------------------------------------
Prompt
------------------------------------------------------------------------
`prompt_seed` selects one of four FIXED short token sequences (below).
Each is spelled out as byte-level-BPE pieces AND as literal ids; when the
checkpoint's tokenizer.json is present the ids are re-verified against it
at generation time, so the prompt can never silently drift.  The engine
decodes one token per forward step, so a P-token prompt is prefilled one
step at a time through exactly the same path used for generation; the
argmax after the last prompt token is generated token #1.  Total forward
steps = P + ntok - 1, and RoPE position / KV-cache depth = the step index.

Emits alongside the script: <prefix>_w*.bin + <prefix>.weights.json
(187 matvec images incl. the 248,320-row LM head at 24 layers; 249 at the
32-layer geometries) and <prefix>.emb.bin (the int16 Q7.8 embedding table,
248320 x H = 485 MiB at H=1024, 1,940.0 MiB at H=4096).
Geometry follows FABLE5_MODEL (ref/model_select.py): H=1024/FFN=3584 for
0.8B, H=2048/FFN=6144 for 2B.  The scratch map is derived from it in
gen_layer_script (docs/QWEN2B_SCRATCH_MAP.md).

G2c (2026-08-31): this generator CANNOT run at FABLE5_MODEL=9b, and the
refusal is in the SCRIPT emission, not in the weights.  A 9B layer body
needs scratch addresses above `Mach.ISA_SADDR_MAX`, a 4096-word `vnw`
above `Mach.VNW_ISA_MAX`, DNST heads above `Mach.ARG0_HEAD_BITS`, an FFN
`alu` length above `Mach.ALU_LEN_MAX` and a whole-block `convz` above
`Mach.CONV_FIELD_MAX` — five SEQ_ISA v1.7 ARG fields that Tasks 7/8/9/10
widen.  Since `Mach.dump_weights` packs only the wids `Mach.matvec`
registered, no 9B weight image can come out of this file until then;
`evidence/qwen9b/g2/G2C_CHAIN.md` records the demonstration and the
weight-side workaround it used instead.
"""
import glob
import json
import os
import sys

import numpy as np

import gen_layer_script as GLS
from gen_layer_script import (Mach, dn_token, attn_token,
                              X0, XN, X8, STG, H, I64, BYTELOCKED_TAGS)
from gen_token_script import slot_plan
import model_select as MS
import fixedpoint as fp
import layer_ref as LR
import layer_fixed as LF
import load_qwen35 as LQ
from layer_fixed import RS_F
from w4a8_ref import G, rshift_round as rshr

# ----------------------------------------------------------------------
# prompts: (text, BPE pieces, token ids)
# ----------------------------------------------------------------------
PROMPTS = {
    1: ("The capital of France",
        ["The", "Ġcapital", "Ġof", "ĠFrance"],
        [760, 6511, 314, 9338]),
    2: ("Once upon a time",
        ["Once", "Ġupon", "Ġa", "Ġtime"],
        [12162, 5028, 264, 854]),
    3: ("import numpy as np",
        ["import", "Ġnumpy", "Ġas", "Ġnp"],
        [464, 8328, 430, 2510]),
    4: ("Hello world! My",
        ["Hello", "Ġworld", "!", "ĠMy"],
        [9419, 1814, 0, 2921]),
}

ROWCHUNK = 8192            # row block for the memory-lean LM-head paths


# ----------------------------------------------------------------------
# tokenizer (documentation + verification only; never load-bearing)
# ----------------------------------------------------------------------
def _tokenizer_path():
    hits = sorted(glob.glob(os.path.join(
        os.path.expanduser("~/.cache/huggingface/hub"), LQ.REPO_DIR,
        "snapshots", "*", "tokenizer.json")))
    return hits[0] if hits else None


def _bytes_to_unicode():
    """The byte-level-BPE printable-byte map (GPT-2 / Qwen convention)."""
    bs = (list(range(ord("!"), ord("~") + 1))
          + list(range(ord("¡"), ord("¬") + 1))
          + list(range(ord("®"), ord("ÿ") + 1)))
    cs, n = list(bs), 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, [chr(c) for c in cs]))


class Tok:
    """Minimal id<->piece view over tokenizer.json (no BPE merging)."""

    def __init__(self, path):
        tk = json.load(open(path))
        self.vocab = tk["model"]["vocab"]
        self.id2piece = {i: s for s, i in self.vocab.items()}
        for a in tk.get("added_tokens", []):
            self.id2piece[a["id"]] = a["content"]
        self.u2b = {u: b for b, u in _bytes_to_unicode().items()}

    def decode(self, ids):
        out = bytearray()
        for i in ids:
            p = self.id2piece.get(int(i))
            if p is None:
                out += b"<unk:%d>" % int(i)
                continue
            try:
                out += bytes(self.u2b[c] for c in p)
            except KeyError:                     # added/special token
                out += p.encode("utf-8")
        return out.decode("utf-8", errors="replace")


def resolve_prompt(pseed):
    """(text, ids) for prompt_seed, verified against tokenizer.json if any."""
    if pseed not in PROMPTS:
        raise SystemExit(f"prompt_seed must be one of {sorted(PROMPTS)}")
    text, pieces, ids = PROMPTS[pseed]
    tp = _tokenizer_path()
    if tp:
        tk = Tok(tp)
        for piece, tid in zip(pieces, ids):
            got = tk.vocab.get(piece)
            if got != tid:
                raise SystemExit(
                    f"prompt {pseed}: tokenizer.json maps {piece!r} -> {got}, "
                    f"but this script hardcodes {tid}. Refusing to guess.")
    return text, list(ids)


# ----------------------------------------------------------------------
# memory-lean W4 quantization for the full-vocab LM head
# ----------------------------------------------------------------------
def quant_linear_big(Wf, rowchunk=ROWCHUNK, tighten_e=False, mse_scale=True,
                     g=G, salience=None, hess=None):
    """Bit-identical to layer_fixed.quant_linear, evaluated in row blocks.

    w4a8_ref.quantize_weights is row-separable ONCE the matrix-wide
    exponent `e` is known, and `e` depends only on max(group scale). A
    one-shot call on the 248320x1024 tied head needs a 2 GiB float64
    temporary; this needs 64 MiB. Verified bit-identical by _selfcheck().

    `g` = W4 group size (128 legacy / 64 = the v2 row format).

    `salience` (OPT-IN, default None) is layer_fixed.quant_linear_mse's
    per-input-channel activation weighting (Track Q V3).  Row chunking is
    orthogonal to it — the weights are per COLUMN and every chunk sees the
    same (1, NG, g) array — so the bit-identity with quant_linear holds with
    salience on too (_selfcheck covers both).

    `hess` (OPT-IN, default None) selects the Track Q V4 GPTQ quantizer,
    which row-chunks internally for the same reason (rows are independent),
    so this just forwards to it — there is one implementation, not two.
    """
    if hess is not None:
        if salience is not None or tighten_e or not mse_scale:
            raise SystemExit("GPTQ takes the MSE rule and its own weights "
                             "(mse_scale=True, tighten_e=False, salience=None)")
        import gptq
        return gptq.quant_linear_gptq(Wf, g=g, hess=hess, rowchunk=rowchunk)
    N, K = Wf.shape
    assert K % g == 0
    NG = K // g
    sw = LF._salience_weights(salience, K, g)      # None, or (1, NG, g)
    if sw is not None and not mse_scale:
        raise SystemExit("salience weighting needs the MSE group-scale rule")
    smax = np.empty((N, NG), dtype=np.float64)
    for r0 in range(0, N, rowchunk):
        r1 = min(r0 + rowchunk, N)
        blk = np.asarray(Wf[r0:r1], dtype=np.float64).reshape(r1 - r0, NG, g)
        smax[r0:r1] = np.abs(blk).max(axis=2)
    smax = np.maximum(smax, 1e-12)
    scale = smax / 7.0
    if mse_scale:               # mirrors layer_fixed.quant_linear_mse
        best_e = np.full((N, NG), np.inf)
        for r0 in range(0, N, rowchunk):
            r1 = min(r0 + rowchunk, N)
            blk = np.asarray(Wf[r0:r1], dtype=np.float64).reshape(r1 - r0, NG, g)
            for a in np.linspace(0.55, 1.0, 17):
                s = (smax[r0:r1] / 7.0) * a
                q = np.clip(np.round(blk / s[:, :, None]), -8, 7)
                sqerr = (q * s[:, :, None] - blk) ** 2
                err = (sqerr if sw is None else sqerr * sw).sum(axis=2)
                upd = err < best_e[r0:r1]
                scale[r0:r1] = np.where(upd, s, scale[r0:r1])
                best_e[r0:r1] = np.where(upd, err, best_e[r0:r1])
    e = int(np.ceil(np.log2(scale.max()))) + 1
    if tighten_e:                       # mirrors layer_fixed.quant_linear
        d = 0
        while d < 15 and np.round(scale.max() * np.exp2(15 - (e - d - 1))) <= 65535:
            d += 1
        e -= d
    m = np.round(scale * np.exp2(15 - e)).astype(np.uint32)
    m = np.clip(m, 1, 65535).astype(np.uint16)
    eff = m.astype(np.float64) * np.exp2(e - 15)
    w4 = np.empty((N, K), dtype=np.int8)
    for r0 in range(0, N, rowchunk):
        r1 = min(r0 + rowchunk, N)
        blk = np.asarray(Wf[r0:r1], dtype=np.float64).reshape(r1 - r0, NG, g)
        w4[r0:r1] = np.clip(np.round(blk / eff[r0:r1, :, None]),
                            -8, 7).astype(np.int8).reshape(r1 - r0, K)
    p_bound = NG * 65535 * (g * 8 * 127)
    return {"w4": w4, "m": m, "e": e, "g": int(g),
            "sh": max(0, p_bound.bit_length() - 31)}


def _rand_hess(rs, K):
    """A random correlated second moment E[x x^T] for the V4 row-chunk check."""
    A = rs.normal(0, 1, (K + 16, K)) * rs.lognormal(0, 0.5, K)[None, :]
    return (A.T @ A) / A.shape[0]


def _selfcheck():
    """quant_linear_big == layer_fixed.quant_linear, bit for bit."""
    rng = np.random.default_rng(5)
    for (N, K) in [(300, 1024), (1024, 256)]:
        W = rng.normal(0, 0.03, (N, K)).astype(np.float32)
        # {} is the production (mse) path; the other two are the historical
        # max-rule quantizer and its exponent-tightening variant.  g=64 is
        # the v2 row format on the production rule.
        # the last two entries are Track Q V3: the salience-weighted MSE rule
        # must stay row-chunk-invariant too (uniform salience is a no-op by
        # construction, a non-uniform one exercises the weighted objective).
        rs = np.random.default_rng(77)
        for kw in ({}, {"mse_scale": False},
                   {"mse_scale": False, "tighten_e": True},
                   {"g": 64}, {"mse_scale": False, "g": 64},
                   {"g": 64, "salience": np.ones(K, dtype=np.float32)},
                   {"g": 64, "salience": rs.lognormal(0, 1.5, K)},
                   # Track Q V4: the GPTQ path forwards to ref/gptq.py, which
                   # row-chunks internally — check the two entry points still
                   # produce the same image with error feedback ON.
                   {"g": 64, "hess": _rand_hess(rs, K)}):
            a = LF.quant_linear(W, **kw)
            b = quant_linear_big(W, rowchunk=97, **kw)
            assert a["e"] == b["e"] and a["sh"] == b["sh"], kw
            assert a["g"] == b["g"] == kw.get("g", G), kw
            assert (a["m"] == b["m"]).all() and (a["w4"] == b["w4"]).all(), kw
        # a power-of-two weight scale is EXACT in this quantizer: it shifts
        # the shared exponent by log2(S) and leaves w4/m/sh bit-identical.
        # That is what makes --res-scale semantics-preserving.  (Checked on
        # the production mse rule: alpha is chosen from |W|-relative grids,
        # so it is scale-invariant too.)
        for S in (4, 8, 16):
            a = LF.quant_linear(W)
            b = LF.quant_linear(LF.res_scaled(W, S))
            k = int(round(np.log2(S)))
            assert b["e"] == a["e"] + k and b["sh"] == a["sh"]
            assert (a["m"] == b["m"]).all() and (a["w4"] == b["w4"]).all()
    return True


# ----------------------------------------------------------------------
# gate chain with UNBOUNDED ports — the spec value the clamp is measured
# against (mirrors gate_unit.sv / Mach.gate exactly, minus the port widths)
# ----------------------------------------------------------------------
def decay_spec(A_q15, dt_q12, a_q12):
    sp = fp.softplus_q(int(a_q12) + int(dt_q12))
    g = -rshr(I64(int(A_q15)) * sp, 11)
    return int(min(rshr(I64(fp.exp_neg_q(int(min(g, 0)))), 15), I64(32767)))


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    allow_clip = "--allow-clip" in flags
    # --res-scale=S : global residual scale-up (see the header + quant_layer)
    # --w4-group=G : W4 quantization group size, 128 (default, legacy wire
    #                format) or 64 (the v2 row format — SHAPE bit 28, one
    #                extra scale beat on K>2048 rows).  See the w4a8_ref
    #                module header for the row layout.
    # --wq=w4|w8 : WEIGHT WIDTH of every matvec matrix (V5, gate D).  See
    #              the "--wq" section of the module header.
    res_scale = 1
    w4_group = G
    wq = "w4"
    for fl in list(flags):
        if fl.startswith("--res-scale="):
            res_scale = int(fl.split("=", 1)[1])
            flags.discard(fl)
        elif fl.startswith("--w4-group="):
            w4_group = int(fl.split("=", 1)[1])
            flags.discard(fl)
        elif fl.startswith("--wq="):
            wq = fl.split("=", 1)[1]
            flags.discard(fl)
    if w4_group not in (128, 64):
        raise SystemExit("--w4-group must be 128 (legacy) or 64 (v2 format)")
    if wq not in ("w4", "w8"):
        raise SystemExit("--wq must be w4 (default, legacy) or w8 (V5)")
    w8 = (wq == "w8")
    if w8 and w4_group != 128:
        raise SystemExit(
            "--wq=w8 needs the g=128 cadence: the W8 row format is defined "
            "at g128 only (sw/hwmap.shape_word and rtl/matvec_engine.sv both "
            "refuse w8+g64). Drop --w4-group=64.")
    if w8 and os.environ.get("FABLE5_CALIB_STATS"):
        raise SystemExit(
            "FABLE5_CALIB_STATS is set and --wq=w8 is on: the calibrated "
            "quantizers (V3 salience / V4 h2 / gptq) are W4-only — V5 is "
            "plain W8 and the Track Q study ruled GPTQ-on-W8 out of scope. "
            "The body would refuse it (layer_fixed._quant_matvec) and the LM "
            "head would silently ignore it, so this refuses BOTH here. Unset "
            "the variable, or drop --wq=w8.")
    known = {"--allow-clip"}
    dead = {"--qfix", "--mse-scale"}
    if flags & dead:
        raise SystemExit(
            f"{sorted(flags & dead)}: dead since Phase 1A. The MSE-optimal "
            "W4 group scale is the production quantizer (layer_fixed."
            "quant_linear defaults to it) and exponent tightening is not "
            "implemented for it. Drop the flag.")
    if flags - known:
        raise SystemExit(f"unknown flags: {sorted(flags - known)}")
    if res_scale < 1 or (res_scale & (res_scale - 1)):
        raise SystemExit("--res-scale must be a power of two >= 1")
    outfile, pseed = argv[0], int(argv[1])
    ntok = int(argv[2]) if len(argv) > 2 else 3
    assert _selfcheck()
    text, prompt_ids = resolve_prompt(pseed)

    # ---------------- real checkpoint ----------------
    md = LQ.load_model()
    cfg, types = md["config"], md["layer_types"]
    vocab = int(cfg["vocab_size"])
    slots = slot_plan(types)
    print(f"checkpoint: {md['path']}\n  header sha256 {md['header_sha256']}\n"
          f"  {len(types)} layers, H={LR.H}, vocab={vocab}\n"
          f"  res_scale={res_scale} DN_NORM_F={LF.DN_NORM_F} "
          f"BF_GUARD={LF.BF_GUARD} "
          + ("group_rule=max|W_g|/127 (W8 has one rule) "
             if w8 else "mse_scale=True (production) ")
          + f"wq={wq} w4_group={w4_group}"
          + ("" if w4_group == 128 else "  [v2 row format: SHAPE bit 28]")
          + ("  [V5 W8 row format: SHAPE bit 29]" if w8 else ""),
          flush=True)

    # quantize layer by layer, freeing each layer's float weights as we go
    layers, gate_sat = [], {}
    for i, (lt, dn_slot, kv_slot) in enumerate(slots):
        wf = md["layers"][i]
        assert wf["type"] == lt, f"layer {i}: {wf['type']} != {lt}"
        # layer_idx is used for ONE thing: per-tensor calibration lookup when
        # FABLE5_CALIB_STATS is set (Track Q V3/V4).  With it unset — the
        # default and every frozen artifact — quant_layer ignores it entirely,
        # which ref/scripts/regen_gate.sh re-proves on every run.
        qw = LF.quant_layer(wf, res_scale=res_scale, g=w4_group, layer_idx=i,
                            w8=w8)
        md["layers"][i] = None
        if lt != "full_attention" and qw["dn"]["gate_sat"]:
            gate_sat[dn_slot] = (i, qw["dn"]["gate_sat"])
        layers.append((lt, qw, LF.new_cache_fx(lt), dn_slot, kv_slot))
    print(f"  quantized {len(layers)} layers "
          f"({sum(1 for l in layers if l[0] != 'full_attention')} DN / "
          f"{sum(1 for l in layers if l[0] == 'full_attention')} GQA)",
          flush=True)

    # final RMSNorm: fold (1+w) and run vecnorm mode 1 at Q3.12 (see header)
    ln_f_q12 = np.round((1.0 + np.asarray(md["ln_f"], dtype=np.float64))
                        * (1 << 12)).astype(I64)
    over = int((np.abs(ln_f_q12) > 32767).sum())
    assert over == 0, (f"model.norm: {over}/{len(ln_f_q12)} values of (1+w) "
                       f"exceed int16 even at Q3.12 (|q|max "
                       f"{int(np.abs(ln_f_q12).max())})")
    print(f"  ln_f folded to (1+w) Q3.12: |q|max "
          f"{int(np.abs(ln_f_q12).max())} of 32767, 0 out of range", flush=True)

    # LM head (W4) + the int16 Q7.8 embedding lookup table.
    # NOTE the LM head is NOT res_scaled: it consumes the POST-ln_f vector,
    # which the residual scale-up leaves invariant.  The embedding TABLE is,
    # because it seeds the residual stream (that is the whole point).
    #
    # G2c (spec 7.2, "Two big images, and they are separate objects"): the two
    # are read from SEPARATE keys.  `load_qwen35.load_model` already decides
    # which is which — at 0.8B/2B/4B (`tie_word_embeddings: true`) `md["head"]`
    # is an independent float COPY of `md["emb"]`, so this is byte-identical to
    # the frozen generator; at 9B it is the checkpoint's own top-level
    # `lm_head.weight`, a different tensor of 1,017,118,720 parameters.  Taking
    # the head from `md["emb"]`, as this file did before, would have quantized
    # the EMBEDDING TABLE as the head at 9B and produced a silently wrong
    # image — the untied-head class of feasibility 2.9.
    emb_f = md["emb"]
    head_f = md["head"]
    # the head's input channels are the FINAL NORM's output — the synthetic
    # 'lm_head' key of ref/calib_stats.py.  Both lookups are None (and this
    # call is byte-identical to the frozen one) unless FABLE5_CALIB_STATS is
    # set; wiring them here is what makes a calibrated DDR image possible at
    # all, since a body quantized with calibration and an unweighted head
    # would be a mixed image nobody could interpret.
    # V5: the head is a matvec weight like any other, so --wq applies to it
    # too — `quant_linear_w8` row-chunks for exactly the reason
    # `quant_linear_big` does (the one-shot float64 temporary on the
    # 248,320-row head is multiple GiB).  The calibration lookups are W4-only
    # and are refused above rather than passed and ignored.
    if w8:
        qw_head = LF.quant_linear_w8(head_f, g=w4_group, rowchunk=ROWCHUNK)
    else:
        qw_head = quant_linear_big(head_f, g=w4_group,
                                   salience=LF.calib_salience("lm_head"),
                                   hess=LF.calib_hess("lm_head"))
    md["head"] = head_f = None
    emb_q = np.empty((vocab, LR.H), dtype="<i2")
    for r0 in range(0, vocab, ROWCHUNK):
        r1 = min(r0 + ROWCHUNK, vocab)
        emb_q[r0:r1] = np.clip(
            np.round(np.asarray(emb_f[r0:r1], dtype=np.float64)
                     * np.float64(res_scale) * (1 << RS_F)),
            -32768, 32767).astype("<i2")
    md["emb"] = emb_f = None
    emb_clip = int((np.abs(emb_q) >= 32767).sum())
    assert emb_clip == 0, (f"--res-scale={res_scale} clips {emb_clip} "
                           f"embedding words at the int16 rail")
    print(f"  LM head {LF.qw_codes(qw_head)[0].shape} "
          f"[{'W8' if w8 else 'W4'}] "
          f"{'tied (a copy of embed_tokens)' if md['tied'] else md['head_key']}"
          f" e={qw_head['e']} "
          f"sh={qw_head['sh']}; emb table |q|max "
          f"{int(np.abs(emb_q).max())} of 32767", flush=True)

    # AMAX index port: layer_chan AMAXI is [17:0]
    assert vocab <= (1 << 18), f"vocab {vocab} exceeds the 18-bit AMAXI port"

    # ---------------- emit ----------------
    # S3: the SLD/SST schedule's two inputs -- how many DeltaNet layers the
    # stack has, and which position must prefetch which attention layer.
    n_dn = sum(1 for t in types if t != "full_attention")
    kv_pf = GLS.sched_kv_prefetch(types)
    resid_max, step_toks = 0, []
    clampdiff = []            # (layer, head, a_q12, decay_spec, decay_clamped)
    # block-float instrumentation: layer_decode_fx (the golden) records; the
    # scratchpad model calls the same helpers with note=False, so every
    # immediate below is counted exactly once.
    LF.bf_reset()
    with open(outfile, "w") as f:
        M = Mach(f)
        M.emb = emb_q
        M.audit_on()

        def probe(dn_slot, a, dt, A, decay):
            for (h, dt_s, _dt_q, A_s, _A_q) in gate_sat.get(dn_slot, (0, []))[1]:
                clampdiff.append((gate_sat[dn_slot][0], h, int(a[h]),
                                  decay_spec(A_s, dt_s, int(a[h])),
                                  int(decay[h])))
        M.gate_probe = probe

        # ---- S3: the DDR state image, and the 6.4 preamble ----
        # The 768 DNZ and the 120 CONVW of the pre-S3 preamble are RETIRED
        # (spec 6.4; 2,655,096 cycles at the first close,
        # evidence/qwen9b/g4/G4B_STRUCT.md 5.1).  The host writes zeros to
        # the DN region and these same conv taps to the conv region during
        # upload, which is what `seed_conv` records and what
        # `evidence/qwen9b/s3/preamble_equiv.py` proves byte for byte.
        for (lt, qw, cache, dn_l, kv_l) in layers:
            if lt != "full_attention":
                M.seed_conv(dn_l, qw["dn"]["conv_w"])
        GLS.sched_preamble(M, types)

        # ---- prefill + autoregressive decode ----
        nsteps = len(prompt_ids) + ntok - 1
        tok, toks_out = prompt_ids[0], []
        for t in range(nsteps):
            M.embed(tok, X0, LR.H)
            x = M.emb[tok].astype(I64)

            # spec 6.1-6.3, per layer: the SST/SLD pair, then the body.
            for i, (lt, qw, cache, dn_l, kv_l) in enumerate(layers):
                if lt == "full_attention":
                    M.layer(dn_l % 2, 0, dn_l % 2, kv_l)
                    gold = LF.layer_decode_fx(x, qw, cache, t)
                    attn_token(M, qw["attn"], qw["ln1"], qw["ln2"],
                               qw["mlp"], t, gold)
                else:
                    GLS.sched_dn_pair(M, dn_l, n_dn, kv_pf[i])
                    GLS.sched_cv_pair(M, dn_l, n_dn)
                    M.layer(dn_l % 2, 0, dn_l % 2, kv_l)
                    gold = LF.layer_decode_fx(x, qw, cache, t)
                    dn_token(M, qw["dn"], qw["ln1"], qw["ln2"],
                             qw["mlp"], gold)
                x = gold
                resid_max = max(resid_max, int(np.abs(x).max()))
            GLS.sched_token_end(M, n_dn)

            # final RMSNorm: PLAIN-w mode 1 with the pre-folded (1+w) Q3.12
            M.W(STG, ln_f_q12)
            M.vnw_(STG, H)
            M.vn(1, H, RS_F, RS_F, X0, XN)
            M.alu(0, H, 0, XN, 0, X8)

            # full-vocab LM head + chunked on-chip argmax
            y32, _ = M.matvec(qw_head, X8, H, rowchunk=ROWCHUNK)
            for c in range(0, vocab, 2048):
                n = min(2048, vocab - c)
                M.W32(STG, y32[c:c + n])
                M.amax(n, STG, fresh=(c == 0))
            M.A()

            gold_tok = int(np.argmax(y32))
            assert M.am_idx == gold_tok, \
                f"step {t}: model amax {M.am_idx} != np.argmax {gold_tok}"
            step_toks.append(gold_tok)
            if t >= len(prompt_ids) - 1:
                toks_out.append(gold_tok)
            kind = "prefill" if t < len(prompt_ids) - 1 else "generate"
            print(f"  step {t:2d} ({kind:8s}) in_tok={tok:6d} "
                  f"argmax={gold_tok:6d} |resid|max={resid_max}", flush=True)
            tok = (prompt_ids[t + 1] if t + 1 < len(prompt_ids) else gold_tok)

        print("Q", file=f)

    prefix = outfile.rsplit(".", 1)[0]
    # R-b: the embedding row stride travels WITH the artifact (2*H bytes), so
    # the host can program seq_unit's EMBLOG2 CSR instead of assuming 2048.
    #
    # G2a: `rs_f` rides the same caller-gated path (spec 4.4 makes RS_F
    # MODEL-SELECTED rather than global).  It is passed only for a geometry
    # whose artifacts are NOT byte-locked: 0.8B and 2B are pinned by G2b and
    # consumed by frozen bitstreams, and an unconditional key would move
    # every one of their manifest bytes — `evidence/qwen2b/rc/t4_bytes_unmoved.sh`
    # byte-compares the weights manifest, and the gold 2B manifest carries no
    # non-wid key at all.  A1.8: the shipped value is still 8.
    nW = M.dump_weights(prefix, emb_row_bytes=2 * LR.H,
                        rs_f=None if MS.TAG in BYTELOCKED_TAGS else RS_F)
    emb_q.tofile(f"{prefix}.emb.bin")

    # ---------------- runtime range audit (hard gate) ----------------
    rep, ok = M.audit_report()
    print("\n" + rep, end="")
    s_sat_gold = sum(int(c.get("sat", 0)) for (_lt, _q, c, _d, _k) in layers
                     if isinstance(c, dict) and "S" in c)
    print(f"S_F soak cross-check (layer_fixed cache['sat'], independent of "
          f"the scratchpad model): {s_sat_gold} saturations\n"
          f"residual stream |x|max = {resid_max} of 32767 "
          f"({100.0 * resid_max / 32767:.1f}% of the int16 Q7.8 rail)")
    ok &= (s_sat_gold == 0)
    ok &= (resid_max <= 32767)

    # ---- block-float immediates actually emitted (Phase 1A) ----
    print("\n--- block-float immediates emitted (Phase 1A datapath) ---")
    print(f"  DN SHIFT32 k_h histogram (op 1, signed): "
          f"{dict(sorted(LF.BF_K_HIST['dn'].items()))}")
    print(f"  ATTN EMUL32 k_a histogram (op 8, unsigned): "
          f"{dict(sorted(LF.BF_K_HIST['attn'].items()))}")
    print(f"  DN SCALE m_q15 (op 2): max raw {LF.BF_CLIP['m_max']}, "
          f"clipped at 32767 {LF.BF_CLIP['m_q15']} times "
          f"({LF.BF_CLIP['m_q15_nonzero']} of them on a NON-ZERO head)")
    print(f"  ATTN k_a clamped up to 0: {LF.BF_CLIP['attn_k']} times")
    if LF.BF_CLIP["m_q15_nonzero"]:
        print("  NOTE: m_q15 saturated the signed-17-bit SCALE immediate on a "
              "non-zero head; that head's gated norm is under-scaled (the "
              "script is still bit-exact — reference and RTL clip alike).")

    print("\n--- gate port saturation, measured at the RUNTIME a values ---")
    if not clampdiff:
        print("  none: every dt_bias/A fits its gate_unit port")
    else:
        worst = {}
        for (li, h, aq, ds, dc) in clampdiff:
            k = (li, h)
            w = worst.setdefault(k, [0, 0, 0, 0])
            if abs(dc - ds) >= w[0]:
                worst[k] = [abs(dc - ds), aq, ds, dc]
        for (li, h), (err, aq, ds, dc) in sorted(worst.items()):
            print(f"  L{li}h{h}: worst |decay_clamp - decay_spec| = {err} "
                  f"/32768 ({100.0 * err / 32768:.2f}% FS) at a={aq / 4096:+.3f}"
                  f"  (spec {ds} -> clamped {dc}); {sum(1 for c in clampdiff if (c[0], c[1]) == (li, h))} evaluations")

    if not ok:
        msg = ("RANGE AUDIT FAILED: a frozen fixed-point format SATURATES on "
               "the real weights (details above).")
        if not allow_clip:
            raise SystemExit(
                msg + "\nThe script and its artifacts were still written and "
                "are BIT-EXACT against the RTL — the reference models exactly "
                "the same clip the hardware performs, so a sim/HW gate on them "
                "still proves the engine correct; what saturation costs is "
                "NUMERICAL FIDELITY to the float model, not correctness.\n"
                "Re-run with --allow-clip to accept that trade deliberately.")
        print("\n*** " + msg + "\n*** PROCEEDING ANYWAY (--allow-clip). The "
              "script is bit-exact but NOT numerically faithful at the "
              "saturating sites; every gate run on it must cite this. ***")

    tp = _tokenizer_path()
    dec = Tok(tp).decode(toks_out) if tp else None
    print(f"\nmodel script: prompt_seed={pseed} prompt={text!r} "
          f"res_scale={res_scale} wq={wq} w4_group={w4_group} "
          f"DN_NORM_F={LF.DN_NORM_F} "
          f"ids={prompt_ids} steps={nsteps} ntok={ntok} vocab={vocab} "
          f"nlayers={len(layers)} cmds={M.ncmd} hostwords={M.nw} "
          f"weights={nW}\n  argmax per step={step_toks}\n"
          f"  generated={toks_out}"
          + (f" decoded={dec!r}" if dec is not None else "")
          + f"\n  -> {outfile}")


if __name__ == "__main__":
    main()
