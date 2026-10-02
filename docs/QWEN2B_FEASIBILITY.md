# Qwen3.5-2B feasibility study (2026-08-12) — VERDICT: FITS-WITH-TRADEOFFS

> **SUPERSEDED on perf and fidelity numbers by `docs/QWEN2B_QUANT_STUDY.md`**
> (Track Q, measured): the mover band, the tok/s figures and the whole fidelity
> outlook below are replaced there. The three walls and the plan shape stand.

Phase-0 record. First draft contained unverified reconstructions; this
is the CORRECTED version — claims below are either (V) re-verified
against RTL/evidence or (U) explicitly unverified. The study agent
self-audited and published the wrong/right ledger; integrator
cross-checked the mover figures against committed silicon data.

## The finding (V throughout unless marked)

2B is a PURE WIDTH SCALE-UP of the 0.8B: identical layer pattern
(18 DN + 6 GQA, same positions), identical DeltaNet geometry (16 heads,
dk=dv=128 -> dn URAM state UNCHANGED at 261), identical GQA (8/2,
head_dim 256 -> kv banks + KV depth 512 unchanged), identical conv
(CONV_DIM 6144), SAME vocab 248,320, byte-identical tokenizer + chat
template, single-file 4.55 GB checkpoint (loader-compatible). Only
hidden 1024->2048 and FFN 3584->6144 move. 187-image weight structure
preserved (mv_by_shape cross-check).

## The three walls

1. SCRATCH 16K -> 32K words (~+14 RAMB36). Scratch map verified: DN
   body tiles to exactly 16,384 today; at H=2048 DN needs 19,424,
   MLP 24,576. The ISA addr_lo has spare bits -> widening is
   backward-compatible; EVERY frozen 0.8B stream replays bit-exact on
   widened hardware = the correctness gate. (+14 BRAM lands in SLR1 @
   70.2% — timing risk, not capacity risk.)
2. VECNORM N 1024 -> 2048 (mandatory; rmsnorm sums whole vectors).
   BONUS BUG (V): n_total <= 11'd1 << cfg_nlog2 overflows to 0 at
   nlog2=11. MEASURED mechanism (evidence/qwen2b/rb/, R-b): FILL DOES
   terminate — cnt+1 wraps in 11 bits too — so the unit swallows all
   2048 elements and then hangs in OUT, where issue = (oidx != n_total)
   = (0 != 0) is false forever: no address is ever presented, m_valid
   never rises, busy sticks high. FIXED in R-b (12-bit counters, 2048-
   deep xbuf/wbuf, 11-bit w_waddr, $fatal guard at cfg_nlog2 >= 12).
3. K=6144 down_proj: MAX_NG=32 (K<=4096) blocks it (V, matvec_engine
   :99/:143). Fix: MAX_NG->48 (preferred; cfg_ng[5:0] already holds
   48) or emitter 2x3072 split (numerics change — avoid).

## Performance (revised, honest bands)

Bytes/token W4 g128: 996,282,368 (2.387x; arithmetic self-validated
against the 0.8B's 417,435,648). DDR fit: 950 MiB weights in the
1,280 MiB window, emb 970 MiB in a 1.55-GiB-spare region (hwmap
constants only). Bandwidth ceiling 140.6 -> 58.9 tok/s.
Decode: matvec ~23.9 + layer ~17.4 (44% of today's layer bucket is
geometry-invariant, measured) + movers 11-14 (U band; per-record
costs exist in evidence/rung3/mover_bench_build032.json but per-row
normalization needs re-doing) = 52-55 ms/token ~= 18-19 tok/s.
Prefill ~40 ms/prompt-token -> batched prefill becomes worth its rung.

## Fidelity outlook

Public data (arXiv 2505.02214): W4 g128 degradation shrinks
monotonically with size; 2B starts ~2x higher (MMLU-Pro 66.5 vs 42.3).
Counterweights: our quantizer is data-free MSE (not AWQ/GPTQ), and
w4a8 pre-shift costs +1 bit at K=2048, +2 at K=6144. g64 is +0.32%
bytes at 2B — recommend as the 2B default. audit_ranges must re-run
(the three documented saturations are per-weight facts).

## Plan shape (if GO): 3-4 rungs, 5-7 build cycles, IN-PLACE ON A BRANCH

R-a config-parameterize generators + re-derive scratch map (no board);
R-b RTL widening (scratch/vecnorm/MAX_NG/EMB_ROW_BYTES->runtime so ONE
bitstream serves both models), gate = frozen 0.8B replay bit-exact;
R-c 2B artifact chain + torch golden + audit + fidelity g128/g64;
R-d HW bring-up + gates + census. Risks ranked: timing (WNS +0.009
today, changes land on the closed paths) > scratch blast radius >
scratch-map re-derivation > K=6144 route choice > fidelity.

## Unverified items to close at R-a kickoff (U)

Resident reroll's own utilization report (study read the base build's);
post-rung-3 mover per-ROW costs (re-normalize mover_bench donors);
dn bank address expression (conclusion safe via URAM invariance);
a real file-by-file change inventory (the study's S/M/L table is
directional, line numbers not trusted).
