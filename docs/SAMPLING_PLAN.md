# Sampling (top-k / temperature) — plan (2026-08-11)

Goal: kill greedy's repetition loops in chat. Zero RTL. Greedy stays
the DEFAULT (all existing gates remain bit-exact); sampling is opt-in
(--temp/--top-k in chat_seq, request fields in serve).

## Architecture (exploits launch-per-step)

A sampled decode step = T_BODY_LITE launch (everything except the LM
head + AMAX) -> host drives the LM head over the existing matvec CSR
path (weights already resident on chan 0; the machinery exists in
infer.py/tok_meter) -> c2h readback of the 248,320 y32 logits (~1 MB,
~4 ms at measured c2h rate) -> host dequant + temperature/top-k/top-p
sample (numpy, seeded RNG) -> sampled token feeds the next launch via
the normal 48/72-byte patch.

Cost estimate: lite launch 45 ms + head matvec ~15 ms (1-chan v1;
4-chan later halves-ish it) + readback ~4 ms + host math ~2 ms
=> ~66-70 ms/token sampled (~14 tok/s) vs 63 ms greedy. Acceptable.

## Phase 0 investigation must pin (Opus, read-only + board CSR reads ok)

1. At the end of a T_BODY_LITE launch: exactly where the head's inputs
   live (x8 scratch address/window, e_x source — EOUT CSR or XRF —
   and whether they're readable post-halt without disturbing state).
2. The head matvec recipe host-side: wid(s), WBASE/BEATS/SHAPE per
   chunk, dequant shift math (MOVY immediates equivalent) — reusable
   code in infer.py (HwMach), tok_meter.py, matvec_test.py; what the
   y32 -> logits dequant needs (per-chunk e/sh from the manifest).
3. c2h logits readback: where y32 lands (RES window read via burst?
   No — host reads RES_DATA CSR (slow, 248K reads!) vs DMA: does any
   path put head y32 in DDR/host-readable bulk? If RES_DATA CSR-only,
   measure realistic readback cost (rung-1's 278 MB/s was c2h DMA from
   DDR; RES readback is MMIO — 248K reads x 1.7 us = 0.42 s! SHOW-
   STOPPER? Mitigations: read only top-k candidates? can't — need all.
   OPTION: host matvec per chunk + RES readback per chunk overlapped?
   still MMIO-bound. REAL option: the burst window! mvchan RES window
   0x0000-0x3FFF is now AXI4-readable by seq_movers ONLY (private
   address space) — host can't reach it. INVESTIGATE: xdma h2c/c2h
   reaches DDR only; RES readback path and its true cost is THE
   go/no-go question — maybe a tiny SEQ stream MOVYs head y32 chunks
   to scratch (proven path!) and host SWIN-reads scratch 4096 rows at
   a time... scratch is 16K words; y32 pairs = 8K words/chunk; MMIO
   SWIN reads are 1.7 us too. OR: sample from a TRUNCATED candidate
   set the chip provides: run AMAX per chunk (61 on-chip argmaxes =
   61 candidates + values, readable via CSR cheaply) and sample among
   the 61 chunk-winners — an approximation of top-k (k<=61, one
   candidate per 4096-vocab chunk) that needs NO bulk readback and
   ~zero extra time. Investigation weighs exact-vs-approx.
4. Reproducibility plumbing: seeded numpy RNG; seed in stats/evidence.

## Verification

- Selftests: sampling math (temperature/top-k/top-p) against numpy
  reference distributions; seed determinism; greedy path byte-
  identical when no flag given.
- HW gate: sampled 2-run determinism with fixed seed; greedy
  regression unchanged (canned gate); qualitative transcripts
  (repetition-loop prompt greedy vs sampled).

## Then: project #2 (matvec rung — planned AFTER sampling ships)

Row-bubble fix + argmax-combine/4-chan per docs/SPEEDUP_LADDER.md.
