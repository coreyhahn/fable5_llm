# Stage 5 fidelity fix (Phase 1A) — PASSED, fixed point at its W4 ceiling

Date: 2026-07-27. Board: BCU-1525 on snoke, bitstream unchanged
(build_026_rr_AltSpreadLogic_medium, netlist 07ffc7b9) — the entire fix
is generator/reference-side; ZERO RTL change, zero rebuild.

## Result

| metric (24 teacher-forced steps vs bf16) | before | after |
|---|---|---|
| top-1 agreement | 0/24 | **15/24** |
| golden-token rank (median) | 52 | **0.0** |
| = W4 quantization ceiling? | no (datapath loss) | **yes, exactly** (mse ceiling 15/24) |

Free-run text (was '  The The' / ' 1 ' class):
  p1 ' is the capital of the United States.\nThe capital of'
  p2 ', the world was a different place.\nOnce upon a'
  p3 '\nimport os\nimport sys\nimport os.path\nimport'
  p4 ' name is "Hello World". I am a "Hello World'
All remaining divergence from bf16 is W4 g=128 weight quantization
itself (proven by the float-dequant ablation: exact 24/24, W4-mse
15/24, fixed point 15/24).

## The fix (Phase 0 evidence -> Phase 1A production)

1. Root cause (commit 7998f33): dnst output squeezed to 0.17 LSB rms by
   the fixed >>5, then renormalized noise. Phase-0 found the subtlety:
   the float model's RMSNorm eps SHRINKS weak heads; naive block
   floating amplifies them (0/24, rank 10536). The production path is a
   generator-computed per-head norm scale honoring the eps
   (script_norm_fx): op1 SHIFT32 k_h -> op2 SCALE m_q15 -> op3 EMUL
   norm_w — existing ISA ops, same op count, DN_NORM_F=11.
2. Attention output: shared per-token block-float k_a, compensated
   exactly via the out-projection in_f (power-of-two invariance).
3. MSE-optimal group scales (same wire format) as quantizer default;
   with block floating it LOWERS S_F saturations (52 -> 29 across the
   4-prompt metric; 30 total across model_v2 scripts vs 53 before).
4. Residual scale S=8 retained.

## Gates (all on the unchanged bitstream, one programming)

Sim 20/20: frozen layer_s1..4 + token_s1..4 UNMODIFIED (back-compat),
regenerated chain_s1..4 / token24_s1..4 / model_v2_s1..4 bit-exact
(sim_phase1a_*.log). Hardware 32/32 runs, 0 errors:
chain 4x2, token24 4x2, model_v2 4x2, frozen regression 8x1
(phase1a_*_hw.json). Artifact hashes: phase1a_*_artifacts.sha256;
regeneration determinism proven cross-machine.

## Posture and follow-ons

- --allow-clip still required: S_F saturations (6-10 per model script,
  RTL-frozen format) — unchanged in kind, reference models the same
  clip, all gates bit-exact.
- Zero-RTL candidate logged: m_q15 ceiling 32767 is reference-side;
  hardware accepts 65535 (layer_chan.sv:391 signed 17-bit immediate) —
  would recover ~3% of live heads under-scaled up to 2x.
- A future on-chip sequencer needs the Phase-1B RTL (DYNQ16 scan +
  eps-aware vecnorm) to replace generation-time immediates; scope in
  docs/FIDELITY_REDESIGN.md.
