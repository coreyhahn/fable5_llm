# Rung-3 decision census — where the 150.2 ms decode step goes (2026-08-10)

Two instruments, both on silicon (build_031, 4d71adcc):
1. census_step.json — per-launch counter deltas over the canned 6-step
   run (sw/cycle_census.py): S_PERF_CYC/AXW/AXR + L_LCYC per step.
2. mover_bench.json — per-record-class costs from micro-streams built
   by REPLICATING real records out of the gated stream
   (sw/mover_bench.py), donors decoded in the json.

## Measured, per full decode step (150.2 ms = 37.55M aclk)

| instrument | value |
|---|---|
| seq total (S_PERF_CYC) | 37,547,-ish k cyc = 150.19-150.23 ms (6/6 steps) |
| layer busy (dLCYC) | 3.53M cyc = 14.12-14.16 ms (9.4%) |
| AXIL traffic (S_PERF_AXW/AXR) | 1,213,414 writes + 1,850,511 reads |
| issue/decode floor (tcnt_csrwr) | 2.06 cyc/record |
| one AXIL write (ext_csrwr) | ~15-17 cyc |
| XRF CSRWR (write-through x2 AXIL) | 34.0 cyc |
| MOVX 1024w (scratch->XWIN) | 15,469 cyc = 1024 AXIL rd + 258 wr (12.1 cyc/op) |
| MOVY 1024r dequant (Y->scratch) | 34,877 cyc = 2048 rd + 2050 wr (8.5 cyc/op) |
| MOVY LM-head form (2 wr/row) | 69,693 cyc = 2048 rd + 4098 wr (11.3 cyc/op) |
| MVGO 4096x16-beat chunk | 30,887 cyc; its 2,044 DONE-poll AXIL reads OVERLAP the engine (poll*15.1 = the whole wait) |
| LDC 1024w (DDR->scratch) | 17,550 cyc = AXI4 burst read + 1025 AXIL scratch writes |

## The budget (assembled; per-class shares derived from the measured
class costs x the step's record mix, cross-checked against the measured
AXW/AXR totals — sums to within ~4% of the step)

| bucket | ms/step | share | note |
|---|---|---|---|
| **MOVY result drain** | **~65-70** | **~45%** | AXIL word-at-a-time: 2 reads/row + 1-2 writes/row; the 248K-row LM head dominates |
| **matvec engine (DDR)** | **~36** | **~24%** | incl. ~14 ms of 8.94-cyc/row bubbles; HIDDEN under MOVY/poll traffic today |
| layer compute (LCYC) | 14.1 | 9.4% | rung 2 already minimized this |
| MOVX x-broadcast | ~11.6 | ~8% | scratch->XWIN, AXIL word loop |
| CMD/CSRWR issue + args | ~10-14 | ~8% | ext CSR writes at ~17 cyc |
| LDC const loads | ~2 | 1.3% | AXIL scratch-write bound, small |
| fetch/decode/slack | remainder | ~4% | issue floor is 2 cyc/rec — a non-problem |

## Verdict — rung 3 is THE MOVER PATH, not the row bubble

The decode step is ~60% single-beat AXI-Lite traffic. Every matvec
result row crosses the fabric as individual 32-bit AXIL beats twice
(engine Y read, scratch write), every activation broadcast crosses
word-by-word, and every MVGO spams ~2K status reads into the same
fabric. The seq_movers block already masters AXI4 for DDR — the engine
X/Y windows and scratch are the only AXIL-locked endpoints left.

RTL levers, by payoff:
1. **Burst mover path (new rung 3)**: expose engine Y/X windows (and/or
   the scratch write port) to a burst-capable port so MOVY/MOVX move
   64B+ per beat. Removes ~75-85 ms/step -> step ~65-70 ms ->
   **~15 tok/s** on its own.
2. MVGO DONE via wire/IRQ to seq (kill the poll spam): free fabric,
   needed anyway once movers overlap engines.
3. THEN the old rung 3 (row bubble, ~14 ms) + argmax-combine/4-chan
   (matvec 36 -> ~10 ms): step -> ~40 ms -> **~25 tok/s**, at which
   point DDR bandwidth and layer compute co-dominate.

The old ladder's "rung 3 = row bubble first" is REFUTED by measurement
— the bubble is #3 on the list, hidden under mover traffic it cannot
help until the movers are fixed.

Artifacts: census_step.json, mover_bench.json (donor record shapes
included), sw/cycle_census.py, sw/mover_bench.py. Note: the bench
clobbers the chat-resident stream images (next chat session re-uploads
2 MiB automatically); ext_csrwr's first run errored E_CSRSP against a
guessed target — rerun uses a real donor record; matvec PERF CSRs
reset per engine start, so step-delta reads cancel (why cycle_census
shows matvec 0 — its time is inside REST by construction).
