> **DEPRECATED 2026-08-12 — design history, not current truth.**
>
> This is the ORIGINAL master plan (written 2026-06-10, stage-1 bring-up).
> Its workload analysis and stage sequencing are still the honest record of
> why the architecture looks the way it does, and its bandwidth ceiling
> (~140 tok/s measured, ~180 predicted here) is still the physics we build
> against. Everything about *current state, targets and next actions* has
> been superseded by the ladder / spec / gate chain:
>
> | for | read |
> |---|---|
> | where throughput stands and what the next lever is | `docs/SPEEDUP_LADDER.md` |
> | the frozen contract for a rung before it is built | `docs/RUNG*_SPEC.md`, `docs/SAMPLING_SPEC.md`, `docs/CHAT_SEQ_SPEC.md`, `docs/INSTRUCT_SPEC.md` |
> | what a rung actually delivered, with evidence | `evidence/<stage-or-rung>/*_GATE.md` |
> | the as-built ISA + CSR maps | `docs/SEQ_ISA.md` (v1.6 as-built) |
> | current state + next action on a cold resume | `NEXT_SESSION.md` (older entries: `docs/HISTORY.md`) |
> | the project contract itself | `CHARTER.md` |
>
> Nothing below has been deleted or edited. Where it disagrees with the
> documents above, the documents above win.

# Master plan — Qwen3.5-0.8B decode on BCU-1525

## Workload analysis (drives every design decision)

Batch-1 decode is **weight-bandwidth-bound**. Per token, every weight is read
once. Model ≈ 0.8B params: with vocab 248,320 × 1024 tied embeddings ≈ 254M
of those are the LM head/embedding; per-layer weights:

- DeltaNet layer (×18): QKV+gate+out projections ≈ 4–6 MB INT4 (exact split
  TBD from HF config in stage-2 prep) + FFN 3×(1024×3584) ≈ 5.4 MB INT4
- Full-attention layer (×6): Q 1024×1024, KV 2×1024×256 (GQA 2KV×128),
  O 1024×1024 ≈ 1.3 MB INT4 + FFN 5.4 MB
- LM head: 1024×248320 ≈ 127 MB INT4 (dominates!)

Total streamed per token ≈ 0.5 GB·(4/8 bit) ≈ **~250–300 MB INT4 + scales**.

DDR4-2400 64-bit: 19.2 GB/s peak per channel, ~13–15 GB/s sustained
sequential. 4 channels ≈ **55–60 GB/s** aggregate. Predicted ceiling ≈
55e9 / 0.3e9 ≈ **~180 tok/s**; realistic first target 50–100 tok/s
(weights spread across all 4 channels, compute overlapped).

So: the architecture is a **streaming W4A8 matvec engine fed by all 4 DDR4
channels in parallel**, with attention/normalization/SwiGLU as small on-chip
side pipelines. KV cache for 6 GQA layers is small (2KV×128×2B×len) — BRAM/URAM.

## Stage plan

### Stage 1 — bring-up (IN PROGRESS)
XDMA Gen3 x8 + 4× DDR4-2400 + CSR block. Evidence: CSR TB (done),
DDR4 example-design sim (xsim, custom part), host integrity test
4 seeds × 2 runs × 4 ch × 4 GiB bit-exact vs PRNG reference.

### Stage 2 — streamed W4A8 matvec
- INT4 weights packed in DDR4 (group scales, group size 128 — power of 2,
  divides 1024/3584, amortizes scale fetch; justify vs 64 in ref model).
- RTL: ddr_reader (AXI RD master, 512-bit @300MHz per channel) → unpack4 →
  multiply-accumulate columns against INT8 activation vector in BRAM →
  INT32 accumulators → requantize. One engine per DDR4 channel, 4-way row
  partition. Verilator TB vs Python reference (exact integer model).
- Report sustained DDR4 read BW from hardware counters (CSR).
- Host: load weights via XDMA, trigger matvec via CSR doorbell, read result.

### Stage 3 — full transformer layer
- Add RMSNorm (fixed-point, document rounding), RoPE + GQA attention with
  BRAM KV cache, DeltaNet recurrence (state update — needs careful fixed-point
  spec from reference), SwiGLU, residuals.
- Reference model extended to full layer, bit-exact intermediate dumps for
  debug. Layer sequencer FSM.

### Stage 4 — end-to-end token
- Embedding lookup from DDR4, 1 layer (then all 24 if BRAM/scheduling allows),
  final RMSNorm, LM head streamed over vocab (argmax on the fly — no need to
  store 248k logits), token out. Reduced sim vocab justified for sim only.

### Stage 5 — stretch
24 layers chained, real Qwen3.5 quantized checkpoint, measured tok/s vs
predicted, 2-board QSFP28 tensor parallel.

## Key decisions log
- 2026-06-10: XDMA (not QDMA) — simpler, driver already loaded on snoke.
  1 H2C + 1 C2H channel suffices for stage 1-2.
- 2026-06-10: DDR4 at 2400 (rated speed, custom part CSV from community,
  same as reference design). 2666 possible later via MIG patch — not worth
  risk now.
- 2026-06-10: CSR on AXI-Lite BAR only; NO DMA-bypass BAR → host MMIO can
  only ever touch the always-responding CSR block (host-hang safety).
- 2026-06-10: per-stage evidence layout under evidence/stageN/.

## Open questions (resolve by stage)
- S2: exact Qwen3.5-0.8B-hybrid projection shapes (pull HF config — model is
  public; need DeltaNet head dims, conv kernel, gating) — fetch config.json
  and document in ref/.
- S2: group size 128 vs 64 measurement in ref model (accuracy on real logits).
- S3: DeltaNet fixed-point state precision (fp16-ish accumulator? must pick
  and freeze in reference first).
- S4: full 248,320-row LM head streaming time ≈ 127MB/55GB/s ≈ 2.3 ms/token —
  fine (dominates tok/s as predicted).
