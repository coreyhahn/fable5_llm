# Stage 3 — full transformer layer (design)

## Ground truth: Qwen3.5-0.8B actual architecture
Extracted 2026-06-12 from HF `Qwen/Qwen3.5-0.8B` config.json (saved at
ref/qwen3_5_0.8b_config.json) and `transformers` modeling_qwen3_5.py
(saved at ref/vendor/). **Discrepancies vs the charter text** (charter
says head_dim 128 / rope theta 1e6; the real model differs — we
parameterize RTL and target the REAL model so stage-5 real weights work):

- hidden 1024, 24 layers (interval-4: 18 linear_attention + 6 full), FFN
  3584 SwiGLU, RMSNorm eps 1e-6, vocab 248320 tied. (matches charter)
- FULL ATTENTION (layers 3,7,11,15,19,23): 8Q/2KV heads, **head_dim 256**;
  q_proj outputs 2x (query+gate): hidden->8*256*2=4096; k,v: ->512 each;
  per-head RMSNorm on q,k (head_dim, eps 1e-6); **partial RoPE: first 64
  dims** (0.25 * 256), interleaved-mRoPE sections [11,11,10] (text-only
  decode => all three position streams equal; cos/sin table on 32 freq
  pairs, theta **1e7**); scaling 1/sqrt(256); softmax over cache; out =
  attn_out * sigmoid(gate); o_proj 2048->1024.
- LINEAR ATTENTION (GatedDeltaNet), per layer:
  - in_proj_qkv: 1024 -> 6144 (q 2048 | k 2048 | v 2048); in_proj_z:
    1024->2048; in_proj_b: 1024->16; in_proj_a: 1024->16. No biases.
  - depthwise causal conv1d over time, kernel 4, channels 6144, no bias,
    SILU activation; decode keeps conv state = last 3 inputs/channel.
  - 16 heads x (dk=128, dv=128). beta = sigmoid(b) per head;
    g = -exp(A_log) * softplus(a + dt_bias) per head (fp32 in ref impl).
  - q,k L2-normalized per head (eps 1e-6); q *= 1/sqrt(128).
  - recurrence per head, state S[128x128] fp32:
      S = S * exp(g)
      kv_mem[dv] = sum_dk S[dk,dv] * k[dk]
      delta[dv]  = (v - kv_mem) * beta
      S         += outer(k, delta)
      o[dv]      = sum_dk S[dk,dv] * q[dk]
  - RMSNormGated per head (dv=128): o = RMSNorm(o)*w * silu(z)
  - out_proj: 2048 -> 1024.
- MLP: down(silu(gate(x)) * up(x)), 1024->3584->1024.
- Layer: x += attn(norm1(x)); x += mlp(norm2(x)).
- (MTP head exists in the checkpoint; out of scope until stage 5+.)

## Stage-3 scope decision
Build BOTH layer types (the charter requires "attention (with a KV
mechanism)" — the 6 GQA layers have the KV cache; DeltaNet's recurrent
state is the other 18 layers' "KV mechanism"). Gate on one full-attention
layer AND one DeltaNet layer, bit-exact end to end vs the reference.

## Fixed-point strategy (to freeze in ref/layer_ref.py before RTL)
- Matvecs (7 per DeltaNet layer incl. z/b/a; 4 per full-attn; 3 in MLP):
  reuse the stage-2 W4A8 engine path unchanged (per-channel row split).
- Residual stream: INT16 (scale fixed per tensor-position, power-of-2) —
  charter requires INT8 *activations into matvecs* (we requantize to INT8
  at each matvec input); residual kept wider for accumulation fidelity.
- RMSNorm: int32 sum of squares -> rsqrt via Newton iteration on a 32-bit
  fixed-point seed (LUT) — exact spec in ref; multiply + per-channel
  weight in INT16.
- Softmax (full attn, decode-time over cache length): fp-free EXP via
  LUT + shift (base-2 decomposition), int32 accumulate, reciprocal via
  Newton. Spec in ref first.
- DeltaNet recurrence: per-head state 128x128. ref uses fp32; candidate
  HW formats: bf16 state with fp32-accumulate semantics, or Q4.20 fixed.
  DECISION DEFERRED to ref experiments measuring drift vs fp32 over long
  sequences (must bound argmax divergence; see ref/experiments).
- exp(g), sigmoid, softplus, silu: LUT-based piecewise (spec in ref).

## Compute placement
Per-layer matvec work streams weights from DDR (stage-2 engines, row-
split across 4 channels). The vector ops (norm/rope/softmax/recurrence/
gating/swiglu, all O(hidden)) run in a single "layer processor" domain @
axi_aclk 250MHz; per-token vector work is ~100k cycles worst case <<
matvec stream time, so it does not bottleneck. KV cache (6 layers x
2 heads x 256 x len) and DeltaNet state (18 x 16 x 128 x 128) in URAM.
DeltaNet state: 18*16*128*128*2B (bf16) = 9.4 MB > URAM (33.75MB? VU9P:
960 URAM x 36KB = 33.75MB) — fits in URAM comfortably; KV cache len 4096:
6*2*2*4096*256*2B = 25MB — TIGHT. Decision: KV cache in DDR4 (streamed
like weights — decode reads it once/token anyway) or cap sim length.
DEFERRED to detailed design.

## Verification ladder (same as stage 2)
1. ref/layer_ref.py float (numpy, mirrors HF exactly; validate vs torch
   transformers on snoke once, capture evidence).
2. ref fixed-point spec frozen; golden vector dumps per sub-block.
3. Unit TBs: rmsnorm, rope, softmax-attn, deltanet-step, swiglu.
4. Layer integration sim (engines modeled or real) bit-exact.
5. Hardware: 4 seeds x 2 runs, bit-exact layer output vs ref.
