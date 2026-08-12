# Decode tok/s speedup ladder (written 2026-08-08)

All numbers trace to committed evidence: evidence/stage5/TOKS.md +
tokmeter JSONs (device/bandwidth), infer.py acceptance logs (wall/MMIO).
Board baseline: build_028_rr_SSI_HighUtilSLRs (67a943bd), 250 MHz layer
domain, 300 MHz engines, 4x DDR4-2400 (58.7 GB/s measured aggregate).

## Measured baseline — one decode token

| level | time | notes |
|---|---|---|
| wall (sw/infer.py live) | ~9,300 ms | 98.8% host<->board MMIO: ~1.16M reads @1.71us + ~1.9M writes @1.19us ~= 4.2 s syscalls + Python |
| device busy | 112.5 ms (1-chan) / 81.7 ms (4-chan weights) | tok_meter, LCYC + PERF counters |
| bandwidth floor | ~7.1 ms | 0.417 GB/token / 58.7 GB/s = 140.6 tok/s ceiling |

Device split: matvec 40.9 ms 1-chan (-> 10.2 ms 4-chan, 4.03x proven) +
layer_chan 71.6 ms = vec_alu 52.3 (73%, 1.25M serial element-ops @10.4
cyc) + vecnorm 12.3 (17%) + other 6.9.

Prefill: no batching — each prompt token is a full forward pass minus
the LM head (136 of 417 MB), so ~same wall cost per prompt token.

## The ladder

| rung | change | type | est. decode tok/s | mechanism |
|---|---|---|---|---|
| 0 | today | — | 0.11 | MMIO-bound |
| 1 | ON-CHIP SEQUENCER (+ data movers; absorbs the matvec<->scratch DMA path) | medium RTL | 12.2 | wall collapses to device time; see docs/SEQUENCER_PLAN.md |
| 2 | parallelize vec_alu + vecnorm (8-16 lanes; they are 90% of layer_chan busy) | medium RTL | ~35-45 | 71.6 -> ~15 ms; matvec becomes the larger term |
| 3 | matvec row-bubble fix (8.94 cyc/row -> ~0; K=1024 rows run 50.2% beat efficiency) + overlap layer compute with weight streaming | small-medium RTL | ~70-100 | approaches bandwidth-bound |
| 4 | bandwidth ceiling | physics | 140 | 0.417 GB/token over 4x DDR4-2400 |
| 5 | 2-board tensor parallel over QSFP28 (charter stretch, untouched) | large | ~280 ceiling | doubles aggregate bandwidth |

Prefill (orthogonal): weight-stationary batched prefill — stream each
weight tile once, apply to all prompt positions; prompt cost drops from
N full passes to ~1 pass of DDR traffic. Attn batches trivially; DN
recurrence serializes only its state update, not its matvecs.

Recommended order: 1 -> 2 -> 3. Rung 1 makes every later gain
user-visible; rungs 1-3 together ~= 350x over today's CLI.

## Rung 1b result (2026-08-09): 4-chan does NOT help the sequencer
Measured: 4-chan 1404ms device vs 1-chan 1220ms = 15% SLOWER (functional
PASS, tokens bit-exact, evidence/rung1/STAGE5_RUNG1B_GATE.md). Cause:
matvec is only 36% of device time; the dominant LM-head matvec can't
parallelize under on-chip sequential AMAX32 argmax; 4x MOVX broadcast +
13% record overhead dominate. => Skip to RUNG 2 (layer ALU/VN = 64%).
Retain 4-chan (default off); it needs an RTL argmax-combine to pay off.

## Rung 4 result (2026-08-12): PASSED — 15.56 -> 30.4 tok/s (1.95x) +
## ON-CHIP SAMPLED CHAT
Zero-bubble matvec (9 -> 0.00 cyc/row), 4-chan interleaved head
(rung-1b avenged: emitter-order fix, zero argmax RTL), TOPK-32 live
(seeded sampled poetry on silicon, LM head + argmax on-chip, seed-
deterministic), both OUT FIFO races dead. build_033 WNS +0.009 on the
raw spread. nch=1 21.5 / nch=4 30.4 tok/s vs 45.2/31.7 projected.
evidence/rung4/RUNG4_GATE.md. NEW #1: layer compute 14.1 ms (43%).

## Rung 3 result (2026-08-11): PASSED — 6.40 -> 15.56 tok/s (2.43x)
Burst mover path measured on silicon (build_032, WNS 0.000 via the
first-ever phys_opt pass): 156.23 -> 64.29 ms/token, AXIL writes
-98.6%, tokens bit-exact, chat/API 2.4x faster for free.
evidence/rung3/RUNG3_GATE.md. New split: matvec 65% (14 ms of it is
the row bubble), layer 22%, movers+polls 11%. => next: row bubble +
argmax-combine/4-chan (~25-29 tok/s), then layer compute.

## Rung-3 census result (2026-08-10): the ladder's rung 3 is REFUTED —
## the movers are the bottleneck, not the row bubble
Measured on silicon (evidence/rung3/CENSUS.md): a 150.2 ms decode step
is ~45% MOVY result-drain (AXIL word-at-a-time, ~15 cyc/op), ~24%
matvec DDR (incl the 14 ms row bubble, HIDDEN under mover traffic),
9.4% layer compute, ~8% MOVX broadcast, ~8% issue/args. Issue floor is
2.06 cyc/rec — the sequencer itself is fine; the AXI-LITE single-beat
fabric is the wall. NEW RUNG 3 = burst mover path (engine X/Y windows +
scratch on a burst port, MVGO done-wire): -> ~15 tok/s alone; then row
bubble + argmax-combine/4-chan -> ~25 tok/s.

## Rung 2 result (2026-08-09): PASSED — 4.91 -> 6.40 tok/s (1.30x)
vec_alu 10.82 -> 1.30 cyc/elem (II=1 pipeline), vecnorm OUT exactly
II=1 + 1-cyc feed. Measured on silicon (build_031, WNS +0.006 — first
fully-closed bitstream since build_023): 1220.03 -> 937.38 ms device
per 6 tokens, tokens bit-exact, repeatable to 188 cycles.
evidence/rung2/RUNG2_GATE.md. NOTE the est column above assumed the
old 4-chan matvec numbers; the SEQ-profile reality: element work was
53.9 ms/token (not 64.6 — op1/op9 dequant lives in MOVY now), removed
47.1 ms/token of it. Residual 156.2 ms/token: matvec+movers ~73 ms
(47%), element ~7 ms, OTHER ~76 ms (non-ALU layer cmds + issue +
movers — CENSUS THIS before picking the next rung). Levers, in
expected order: fresh device census -> rung 3 (matvec row bubble,
~8.9 cyc/row) + argmax-combine RTL (makes 1b's 4-chan pay) -> overlap.
