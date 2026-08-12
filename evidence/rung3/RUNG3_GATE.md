# STAGE 5 RUNG 3 GATE — burst mover path on silicon (2026-08-11)

Spec: docs/RUNG3_SPEC.md (frozen). Census that motivated it:
evidence/rung3/CENSUS.md + corrections in the spec. Four Opus agents
(A seq master+BD / B mvchan shim / C layer shim / D burst fabric TB)
+ integrator. Zero ISA/stream/numerics change; zero new CDC (whole
path in aclk); +6 BD cells (single-clock SmartConnect + 5 reg slices).

## Headline (measured, seq_run model_v2_s1.e, 6 tokens, x2 no reprogram)

| | rung 2 (build_031) | rung 3 (build_032) | ratio |
|---|---|---|---|
| device / 6 tok | 937.38 ms | **385.72 ms** (96,429,059 cyc) | **2.43x** |
| device / token | 156.23 ms | **64.29 ms** | |
| decode tok/s | 6.40 | **15.56** | +143% |
| AXIL writes / run | 7,724,372 | **104,852** (-98.6%) | |
| AXIL reads / run | 11,203,288 | 5,648,342 (-49.6%; rest = polls) | |
| tokens | golden | IDENTICAL | bit-exact |

Repeatable to ~1,000 cyc (385.716 / 385.720 ms). 7,188 post-halt state
checks ALL MATCH both runs. Projection was 62.8 ms/step; measured
launch-per-step census: **62.83 ms/step** (377.0 ms / 6 launches) —
agreement to 0.05%. Ladder to date: 0.11 (host CLI) -> 4.91 (rung 1)
-> 6.40 (rung 2) -> **15.56 tok/s (rung 3) = 141x**.

## Bitstream — closed by the first-ever phys_opt pass

build_032 netlist 0c991953 (VERSION CSR verified). First roll -0.354
(census: ZERO violators in the new burst logic; u_dn 3,107 + interconn
~550 = the usual placement spread — build_032_firstroll_census.txt).
5-way reroll spread: SSI_HighUtilSLRs -0.091 (best), ExtraNetDelay_low
-0.244, AltSpreadLogic_medium -0.452, ExtraTimingOpt -0.526, Explore
-0.664. Post-route phys_opt_design AggressiveExplore (first use in
this project) closed it in ONE pass: **WNS 0.000 / TNS 0.000 /
0 failing of 1,167,230; WHS 0.000 clean** (postopt_032.tcl;
out_build_032_rr_SSI_HighUtilSLRs/postopt/). Playbook updated: census
-> reroll spread -> phys_opt is the closure sequence.

## Gates (all PASS)

Sim (commits 7a817ad/88b7238): fabric conformance 12/12; tb_seq_unit
53/53 + 4 E_AXI injections; model_v2 60,495 records bit-exact
(94,784,512 cyc, was 110.6M); tok2/lay/chat_i1/i1b bit-exact; frozen
regressions 16/16 + tb_matvec_chan 4/4; latency-insensitive (0.15%
over blat 0..8). One real bug (layer shim AW re-execution on
back-to-back bursts) caught pre-silicon by the fabric's B-vs-AW
accounting and fixed in one line.

HW (this doc, single programming): seq_run x2 headline above;
cycle_census 6 steps 62.83 ms/step (layer 14.13 ms unchanged, as
designed); chat_seq --canned golden tokens (chat/API now ~2.4x faster
with zero software change); frozen host-driven ladder layer_s1-4 +
token_s1-4 PASS (AXIL registers bit-identical per B/C contract).

## After rung 3 — the new Amdahl

| bucket | ms/step | share |
|---|---|---|
| matvec engine (DDR + 8.94 cyc/row bubble ~14 ms) | ~41.7 | 65% |
| layer compute (LCYC) | 14.1 | 22% |
| movers (burst) + MVGO/CMD polls | ~7 | 11% |

Next levers per docs/SPEEDUP_LADDER.md: matvec row-bubble fix +
argmax-combine/4-chan (-> ~25-29 tok/s, DDR floor 7.1 ms/token), then
layer compute becomes #1. Orthogonal: Qwen3.5-0.8B-Instruct checkpoint
swap (zero RTL, chat quality), weight-stationary batched prefill.

Artifacts: seqrun{1,2}_build032.json, census_step_build032.json,
chat_canned_build032.json, hostgate_frozen_build032.json, gate*.log,
build_032_firstroll_census.txt. Spread-#2 rerolls (AltSpreadLogic_low,
AggressiveExplore) were still running at gate time — informational
only; the shipped bitstream is the phys_opt closure.
