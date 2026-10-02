# Qwen3.5-2B migration — design spec (2026-08-12)

Approved design for moving the accelerator from Qwen3.5-0.8B-instruct to
Qwen3.5-2B, with a first-class quantization tradeoff study comparing
what the current hardware runs (W4A8, 16-bit fixed-point datapath)
against the 2B model at native bf16 resolution.

Builds on `docs/QWEN2B_FEASIBILITY.md` (Phase-0, verdict
FITS-WITH-TRADEOFFS). That document's facts are assumed here and not
restated except where a number drives a decision.

## Decisions already made (with the user, 2026-08-12)

1. **All precision options are on the table** — including quantizer
   algorithm changes and RTL precision changes (W8 weights, wider
   activations). The study exists to expose the tradeoffs, not to
   ratify W4A8.
2. **Quality = fidelity harness + perplexity.** Existing
   `ref/fidelity_check.py` metrics (top-1 agreement, golden rank,
   top-5, free-run text) plus a new perplexity metric vs bf16.
3. **No hard tok/s floor.** The study presents the full
   quality-vs-throughput-vs-resources curve; the user picks the
   operating point.
4. **Plan shape A: study + geometry prep in parallel.** The three
   RTL walls are geometry-driven (H=2048, K=6144), not
   precision-driven, so they proceed concurrently with the study.
   Only precision-dependent RTL (a W8 engine mode, if chosen) waits
   for the study's decision gate.

## Constraint the study must keep visible

FPGA *logic* space is not the binding constraint for weight precision —
**DDR read bandwidth is**. Weights stream from DDR every token:
W4 g128 is 996,282,368 bytes/token (~18-19 tok/s projected end-to-end);
W8 doubles weight bytes and roughly halves that. Secondary constraint:
SLR1 BRAM at 70.2% post-scratch-widening is a timing-risk zone on a
design closed at WNS +0.009.

---

## Track Q — quantization tradeoff study (harness-only, no board)

### Q0 — 2B reference bring-up

- Download Qwen3.5-2B into the HF cache (single ~4.55 GB safetensors
  shard). Not currently present locally (verified: cache has only
  0.6B and 0.8B).
- Parameterize `ref/load_qwen35.py` and add
  `ref/qwen3_5_2b_config.json` beside the existing 0.8B config.
  (This is shared plumbing with R-a — do R-a's config-JSON schema
  first, then Q0 consumes it.)
- Stand up the bf16 torch golden for 2B (`ref/validate_vs_torch.py`
  path).
- **Gate:** bf16 free-run text is sane on the standard prompts, and
  the feasibility study's tokenizer-byte-identity claim is re-verified
  locally against the downloaded checkpoint.

### Q1 — native baseline + perplexity harness

- New perplexity metric over a fixed held-out corpus: a WikiText-2
  validation slice of 16-32K tokens, committed (or pinned by hash) so
  every variant scores on identical data. bf16 2B perplexity is the
  anchor all variants are measured against.
- **Measurement-level split (explicit design choice):**
  - *Perplexity* is computed at the **quantized-weights,
    float-compute** level — vectorized numpy/torch, fast enough to run
    per-variant on CPU. It captures weight-quantization damage.
  - *Fixed-point datapath* damage is measured with the existing
    fidelity harness (top-1/rank/top-5 + free-run text on the standard
    prompts) through the bit-exact Python integer model — running the
    full corpus through the pure-Python integer model is prohibitively
    slow, so datapath scoring stays on the short-prompt harness.
  - The **ablation ladder** ties the levels together (same method as
    `docs/FIDELITY_REDESIGN.md` used on the 0.8B): exact-weights
    fixed-point vs W4-dequant-float vs full fixed-point. This
    decomposes total loss into "weight quantization" vs "16-bit
    datapath" — the fork that decides whether RTL precision changes
    would even help.

### Q2 — variant sweep

Every variant is scored on: perplexity delta vs bf16, fidelity-harness
scores, free-run text verdict, bytes/token, modeled tok/s (bandwidth
model calibrated by the 0.8B's measured 30.4 tok/s numbers and the
re-normalized mover costs from R-a), DDR fit, and an RTL-delta note
with timing risk.

| id | variant | wire format | RTL delta |
|----|---------|-------------|-----------|
| V1 | W4A8 g128, data-free MSE quantizer (today's exact config) | frozen | none |
| V2 | W4A8 g64 (feasibility-recommended 2B default; +0.32% bytes) | existing g64 mode | none |
| V3 | W4A8 g64 + improved quantizer (AWQ/GPTQ-style scale search) | existing g64 mode | none |
| V4 | Mixed precision: W8 on most-sensitive tensor classes, W4 rest | new W8 groups + map | W8 engine mode |
| V5 | W8A8 everywhere (weight-quality ceiling, ~2x bytes/token) | new W8 format | W8 engine mode |

- **V3 calibration data:** a WikiText-2 *train*-side slice, disjoint
  from the Q1 eval slice. The quantizer stays host-side; the wire
  format does not change.
- **V4 sensitivity map:** produced by a per-tensor-class scan —
  quantize one class at a time (q/k/v/o proj, gate/up, down_proj, DN
  projections, embedding/LM head) to W4 with the rest at bf16, rank
  by perplexity delta. The scan output is itself a committed artifact.
- **V4/V5 in the study are Python-modeled only.** The W8 wire format
  is sketched (packing, scale layout, bytes/token, engine-mode
  implications) but W8 RTL is designed and built only if the decision
  gate picks V4/V5.
- `ref/audit_ranges.py` re-runs at 2B for every candidate default (the
  0.8B's three documented saturations are per-weight facts and do not
  transfer).
- **Conditional V6 axis:** only if the ablation ladder shows the
  16-bit datapath (not weight quant) dominates the loss at 2B, model
  the `docs/FIDELITY_REDESIGN.md` Phase-1B menu (S_F width,
  block-floating DN output, wider scratch) in Python and add those
  points to the table.

### Q deliverable

`docs/QWEN2B_QUANT_STUDY.md`: the decision table (variant x quality x
throughput x resources x RTL delta), the ablation decomposition, the
sensitivity ranking, and a recommendation. This is a committed
evidence artifact and the input to decision gate D.

---

## Track R — geometry RTL (parallel with Q)

Everything in R-a/R-b is required for 2B regardless of which precision
variant wins.

### R-a — parameterize (no RTL, no board)

- Model-config-driven generator/host chain: `ref/layer_fixed.py`
  constants, `ref/gen_layer_script.py`, `ref/gen_model_script.py`,
  `sw/hwmap.py` (DDR layout, EMB row geometry), all reading the
  per-model config JSON.
- Re-derive the scratch map at H=2048: DN body needs 19,424 words,
  MLP 24,576 — both must tile into the widened 32K map.
- Close the feasibility doc's four unverified (U) items: resident
  reroll's own utilization report; post-rung-3 per-ROW mover costs
  (re-normalize `evidence/rung3/mover_bench_build032.json` donors —
  this firms up the 18-19 tok/s band); dn bank address expression;
  real file-by-file change inventory.
- **Gate:** 0.8B artifacts regenerate **byte-identical** through the
  parameterized chain. Proof the refactor changed nothing.

### R-b — the three walls, one RTL pass

1. Scratch 16K -> 32K words (~+14 RAMB36, lands in SLR1 @ 70.2% —
   the top timing risk).
2. VECNORM N -> 2048, **including the latent `nlog2=11` overflow
   deadlock fix** (`n_total <= 11'd1 << cfg_nlog2` wraps to 0; exists
   today) plus an assertion.
3. MAX_NG 32 -> 48 in `rtl/matvec_engine.sv` (preferred K=6144 route;
   `cfg_ng[5:0]` already holds 48; no emitter split, no numerics
   change).
4. EMB_ROW_BYTES becomes a runtime CSR so **one bitstream serves both
   models**.

**Gates, in order:** full Verilator TB suite clean; every frozen 0.8B
stream replays **bit-exact** on the widened RTL in sim, 4 seeds; build
+ reroll spread per the timing playbook; full 0.8B HW ladder on the
new bitstream reproducing today's numbers (30.4 tok/s nch=4, lockstep,
sampled chat) **before the 2B ever touches the board**.

### Decision gate D

Track Q's table + Track R's firmed timing/utilization facts on one
page; the user picks the operating point.

- V1/V2/V3 pick -> straight to R-c.
- V4/V5 pick -> W8 engine mode first: wire-format spec written into
  `ref/w4a8_ref.py`'s successor section, engine RTL mode, TB vs the
  extended reference bit-exact, its own build + reroll timing pass,
  0.8B-replay back-compat gate unchanged.

### R-c — 2B artifact chain at the chosen precision

Quantize the 2B checkpoint; generate weight images + SEQ streams;
torch-golden lockstep in sim; `audit_ranges` clean or waivered with
evidence; fidelity gate scoring at the study-predicted numbers.

### R-d — hardware bring-up

DDR upload (fit per the study table; W4 fit already verified in
feasibility: 950 MiB weights + 970 MiB emb), lockstep vs `seq_model`
on the board, chat template + sampled chat, perf census vs modeled
tok/s, gate doc.

---

## Sequencing and logistics

- **Branch:** `qwen2b` off `main`, in-place in this project dir.
  Commit at every green gate; merge to `main` at the R-d gate.
  One-build-per-project-dir and fresh-`out_<build>` rules unchanged.
- **Machine placement:** Vivado builds + heavy Verilator sims on
  snoke; Q's perplexity/quantizer sweeps are CPU torch/numpy and run
  on the other hobby servers (kyloren, fn2187, darthvader) over NFS,
  so Q never competes with R-b builds for snoke.
- **Board stays demo-able:** resident build_033 keeps serving 0.8B
  chat until R-b's widened bitstream passes the full 0.8B HW ladder;
  after that, one bitstream serves both models and switching is a
  weight re-upload, not a reprogram.
- **First moves:** (1) start the 2B checkpoint download in the
  background; (2) R-a config-JSON schema, then Q0 on top of it;
  (3) Q sweep and R-b proceed in parallel.
- **Evidence:** `evidence/qwen2b/<stage>/` per rung, gate docs
  mirroring the RUNG4 pattern, 4 seeds minimum on every TB/HW run.

## Effort estimate

| phase | estimate |
|-------|----------|
| Track Q | 2-4 sessions (V3 quantizer search + sensitivity scan are the long poles) |
| R-a | 1-2 sessions |
| R-b | 1-2 sessions RTL/TB + 2-3 build cycles |
| D | one conversation |
| R-c | 1-2 sessions |
| R-d | 1-2 sessions, +1-2 build cycles only if W8 mode picked |

Consistent with the feasibility band of 5-7 build cycles total.

## Risks (ranked, unchanged from feasibility except the addition)

1. Timing — all RTL lands on paths closed at WNS +0.009.
2. Scratch widening blast radius.
3. Scratch-map re-derivation errors.
4. K=6144 route (MAX_NG=48) interactions.
5. Fidelity — mitigated by this study existing at all.
6. *(new)* Study-level risk: perplexity at the quantized-float level
   may under- or over-state what the fixed-point pipeline delivers;
   mitigated by the ablation ladder cross-check on every candidate
   default.
