# STAGE 5 RUNG 4 GATE — zero-bubble matvec + 4-chan head + on-chip
# sampled chat (2026-08-12)

Spec: docs/RUNG4_SPEC.md (frozen). Board: build_033_rr_AltSpreadLogic_
medium, netlist 33d720e5 (VERSION CSR verified), WNS +0.009 / TNS 0.000
(0 failing of 1,174,653), WHS +0.010 — closed on the raw 5-way spread,
no phys_opt needed (spread: ASM +0.009, ETO -0.013, END_low -0.125,
Explore -0.213, SSI_HUS -0.417 — last build's winner placed worst;
the lottery is real). TOPK_IDENT reads 0xFAB1704B on silicon.

## Headline (measured, model_v2 6 tokens, tokens bit-exact everywhere)

| | rung 3 | rung 4 nch=1 | rung 4 nch=4 |
|---|---|---|---|
| device / 6 tok | 385.72 ms | 278.78 ms | **197.64 ms** |
| ms/token | 64.29 | 46.46 | **32.94** |
| decode tok/s | 15.56 | 21.5 | **30.4** |
| vs rung 3 | 1.00x | 1.38x | **1.95x** |

Projections were 45.2 (1ch central) / 31.7 (4ch) ms/token — measured
46.5 / 32.9. Ladder to date: 0.11 -> 4.91 -> 6.40 -> 15.56 -> 30.4
tok/s = **276x** over the original host CLI.

## SAMPLED CHAT ON-CHIP (the sampling project's G3, closed here)

chip-topk source, k=32, temp 0.8, "Write a haiku about winter.":
- seed 4242 x2: IDENTICAL 24-token trajectories ("the golden frost
  hangs upon the windows like ice draped...") — determinism PASS.
- seed 4243: entirely different poem ("cold fingers reach across...")
  — seed sensitivity PASS.
- Banner: "the LM head + argmax run ON-CHIP every step" — the user
  ruling honored; host contribution = one RNG draw over 32 chip
  scores. Greedy --canned MATCH on the same bitstream/layout.
- Qualitative: sampled output is varied, non-looping language vs
  greedy's repetition ("The frost is heavy, heavy, And").

## Gates

Sim (commit 33d720e): retire pipeline 0.00 cyc/row on all production
shapes (5-NG law gated for NG<=4); tb_topk 19 cases x4 seeds vs numpy
(545,631 elements incl. am_g wrap) + 288 AMAX-equality checks; export
contract 268,273 pulses exact; OUT FIFO depth-64 + sticky ovf + BOTH
races gated (the pop-strobe token-loss bug D found was PRE-EXISTING
since rung 1 — 2-line fix + standing tb_seq_offifo gate); chip ladder
model_v2 nch=1 66.1M cyc / nch=4 46.9M (2.022x vs rung-3 sim), nch=4
chip state byte-identical to nch=1; nch=1 emitter regeneration
BYTE-IDENTICAL (sha); frozen 16/16.

HW (this doc): seq_run nch=1 278.78 ms + nch=4 197.64 ms (interleaved
head confirmed in upload log, "wid [186] chunk-INTERLEAVED"), tokens
IDENTICAL both; chat --nch 4 --canned MATCH; sampled determinism as
above. axil_rd fell again (5.65M -> 3.87M nch=1: faster commands =
fewer polls).

## After rung 4 — where the next token goes (nch=4, 32.9 ms)

matvec ~10 ms (DDR-bound, ~10.4 GB/s/chan derived from 417 MB over 4 chans in ~10 ms; stage-2 measured 14.67 sustained; floor ~7),
layer compute 14.1 ms (NOW #1, 43%), movers+polls ~9. Next levers:
layer engine ops (dn_step/attn element paths), mover overlap (MOVY
during next MVGO — the S12 door), MVGO guard removal (0.9 ms at
nch=4). Bandwidth ceiling ~140 tok/s remains the physics.

Follow-ons: am_g 18-bit wraps at 262,144 = only 5.6% vocab headroom
(policy undecided); TOPK overflow = literal reading (rejected-arrival
tie) — host cross-check assumes it; TK_PTR wraps at 32; seq_chat
geometry constants vs C's derive_geometry cleanup.
