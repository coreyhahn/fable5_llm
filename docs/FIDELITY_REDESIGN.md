# Datapath precision redesign — scope (2026-07-26)

Problem (evidence: commit 7998f33, evidence/stage5/fidelity_*.log):
fixed-point decode is bit-exact but linguistically degenerate. Ablation:
exact-weights 24/24 -> W4-dequant 12/24 -> fixed-point 0/24. Dominant
identified mechanism: DN output leaves dnst at ~5.7 LSB rms (int32,
Q.S_F), the fixed >>5 alignment squeezes it to 0.17 LSB rms in int16,
and the gated RMSNorm renormalizes that quantization noise to full
scale. Loss is distributed; no single frozen-format relaxation recovers
it (diag sweep max 2/24).

## Phase 0 — decision data (harness only, NO RTL, ~hours)

0a. **Establish the achievable ceiling.** Free-run the W4-dequant FLOAT
    model (fidelity_check ablation config) on all 4 prompts and read its
    TEXT. The fixed-point pipeline can never beat this. If 0a text is
    also degenerate, the real problem is W4 quantization strategy
    (group size, per-channel scales) — script-side scope, no RTL — and
    the datapath redesign is NOT the binding fix.
0b. **Prototype block-floating DN output** in layer_fixed/fidelity_check:
    per-head per-token k_h = f(max|o32|) replacing the fixed DN_O_SHIFT=5.
    Zero RTL: the ALU shift is already a per-head command immediate
    (gen_layer_script.py:565), the generator knows o at emit time, HW
    computes the identical o (bit-exact) so the immediate stays
    consistent, and the gated norm's scale-invariance eats the shift —
    no downstream compensation. Same trick evaluated for the attn output
    path (l2norm probe error 2.04%).
0c. **Combination sweep in the harness** (only if 0b < ceiling):
    block-floating + S_F width + requant variants, scored by the
    fidelity table. RTL candidates are chosen from measured winners,
    never from intuition.

Decision gate: compare 0b (+0c) top-1/rank/text against 0a's ceiling.

## Phase 1A — generator-side fix (if 0b suffices): NO RTL, NO REBUILD

layer_fixed dynamic k_h + gen_layer_script dn_token (attn_token if 0b
says so) + gen_model_script regeneration. Gates: byte-identical
regeneration proof N/A (dn_token changes for ALL scripts — synthetic
chain/token24 must be REGENERATED and re-gated sim+HW; stage-3/4
committed scripts stay frozen as the LAYER=0 back-compat set — verify
they still pass UNMODIFIED, which they must since nothing RTL changed).
Full ladder: sim 4 seeds (chain, token24, model) + HW gates on the
CURRENT bitstream. Effort: ~half day. Risk: low; script size +0.

## Phase 1B — small-RTL menu (only with Phase-0 evidence)

- DYNQ16 vec_alu op (scan-max + shift + exponent CSR) or 32b-input mode
  for the gated norm: removes generation-time data dependence (needed
  eventually for a sequencer). Small units, low timing risk. Cost: full
  build + reroll spread + complete re-gate ladder (~1 day wall).
- S_F Q2.13 -> Q3.12 (same 16b): reference constant + RTL v-alignment
  change (layer_chan.sv:773 {sa_q,5'b0}); only in combination per diag.
- WIDER S state (>16b rows): dn_mem width grows — URAM 348 -> ~522,
  SLR pressure and timing closure regress materially. Last resort;
  needs its own feasibility pass.

## Phase 2 — timing re-closure + gates (only if 1B)

Proven flow: launch_build -> launch_reroll spread (MCP XDC in-flow),
census-driven iteration, HW ladder, honest WNS. Budget one day wall
clock, mostly machine time.

## Risks

- W4 ceiling (0a) may cap quality regardless of datapath work — that
  redirects scope to quantization strategy (still script-side).
- 12/24 top-1 vs bf16 does not necessarily mean bad text (disagreements
  can be benign); 0a settles this empirically.
- Any RTL change re-opens timing at WNS -0.142 baseline.
