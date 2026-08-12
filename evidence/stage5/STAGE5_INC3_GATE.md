# Stage 5 increment ③: real Qwen3.5-0.8B, full vocab — PASSED

Date: 2026-07-26. Board: SQRL BCU-1525 (xcvu9p) on snoke, JTAG volatile.
Bitstream: build_026_rr_AltSpreadLogic_medium (netlist 07ffc7b9, same as
the ①/② gate — no reprogram between any of the stage-5 gates so far).

## What was proven (charter: 4 seeds x 2 runs, no reprogram)

The REAL Qwen3.5-0.8B checkpoint (bf16 safetensors, W4A8 group-128
quantized by ref/layer_fixed.py), all 24 layers, real tied embedding
(485 MB, int16 Q7.8, real c2h DMA reads per token), 4-token prompt
prefill + 3 autoregressive tokens, FULL 248,320-row LM head streamed
from DDR in 61 chunks of 4096, on-chip argmax across all chunks.

| prompt seed | runs | cmds | checks | real matvecs | errors |
|---|---|---|---|---|---|
| s1 ("The capital of France") | 2 | 20,730 | 5,789,550 | 1,122 | 0 |
| s2 ("Once upon a time")      | 2 | 20,730 | 5,789,550 | 1,122 | 0 |
| s3                            | 2 | 20,730 | 5,789,550 | 1,122 | 0 |
| s4                            | 2 | 20,730 | 5,789,550 | 1,122 | 0 |

Sim gates preceded hardware for every seed (sim_model_s1..4.log,
1,900,014 checks each). Reports: model_hw_build026_ASM.json (+_s34).
Artifacts (~967 MiB/seed) regenerable + SHA-256'd; bins gitignored.

## Honest numerics ledger (fidelity vs bit-exactness)

Bit-exactness vs the reference: PERFECT (every check above). Fidelity
of the fixed-point pipeline vs the bf16 model: NOT yet adequate —
greedy decodes are degenerate (s1: "  The The"). Quantified causes:
- S_F=13 DeltaNet state saturates on real weights: 7 of 28.3M state
  writes/run, |S| to 5.46 vs ±4.0 (dn_slot 3, head 5, reproducible).
  Format is RTL-frozen (layer_chan.sv v-alignment, dn_step 16-bit
  rows); reference clips identically, so gates stay bit-exact.
  Accepted via generator --allow-clip (default aborts).
- dt_bias/A gate-port outliers: Q4.11/Q4.14 widening proven impossible
  against frozen softplus/exp2 ROM domains (gate_unit.sv:162, :202);
  saturating clamp replaces silent wrap. Worst decay error 9.3% FS on
  1/288 heads (vs 99.5% FS corruption from wrap).
- ln_f: solved exactly — (1+w) folded at Q3.12, VN mode 1, no clamping,
  cost 1 LSB on 3.7% of LM-head int8 inputs.
- Embedding occupies 0.18% of Q7.8 (audit §4): ~5.7% relative RMS error
  seeding the residual. Candidate fix (out of charter scope): global
  embedding scale-up exploiting RMSNorm scale-invariance; needs a
  residual-headroom study (|x|max was 6.7% of rail this run).

## Runtime range audit (completes audit_ranges_report.md §5)

Rail hits: conv 88/663,552, alu 14; S_F saturations 7 (above); silu
21-bit clips 0; y32 spare 8-13 bits; DYNQ8 exponents 0..7. Full report
in the generation logs (model_gen_s*.log).
