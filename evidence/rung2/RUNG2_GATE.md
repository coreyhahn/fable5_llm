# STAGE 5 RUNG 2 GATE — II=1 vec_alu/vecnorm on silicon (2026-08-09)

Rung 2 of docs/SPEEDUP_LADDER.md: pipeline layer_chan's element engines
(vec_alu, vecnorm + its dispatcher feed) from serial ~10.8/15.9
cyc/elem to initiation-interval-1. Spec: docs/RUNG2_SPEC.md (frozen);
plan: docs/RUNG2_PLAN.md. RTL by two Opus agents (A: vec_alu, B:
vecnorm + layer_chan F_* grant), differential verification by a third
(C), integrated/gated here. No ISA, script, wire-format, or numerics
change: every committed artifact replays bit-exact.

## Headline (measured, sequencer-driven model_v2_s1.e, 6 tokens)

| | rung 1 (build_030) | rung 2 (build_031) | ratio |
|---|---|---|---|
| device / 6 tok | 1220.03 ms (305,008,161 cyc) | **937.38 ms (234,344,151 cyc)** | **1.302x** |
| device / token | 203.34 ms | **156.23 ms** | |
| decode tok/s | 4.91 | **6.40** | +30.2% |
| wall | 1.222 s | 0.938 s (99.9% = device) | |
| tokens | [561,314,279,369,279,6511] | IDENTICAL | bit-exact |

Two runs, no reprogram: 234,344,339 vs 234,344,151 cyc (188-cycle
repeatability, 0.75 us). STATUS err=0; 7,188 post-halt state checks ALL
MATCH; fetch_starved 95/96 cyc; axil_rd fell 15.91M -> 11.20M (commands
finish faster, DONE polls collapse). Logs: seqrun_model_v2_build031.log,
seqrun{1,2}_build031.json.

Element-work removed: 47.11 ms/token measured vs 46.9 projected by the
investigation census (docs/RUNG2_SPEC.md targets: 53.9 -> ~7.0 ms/token)
— agreement within 0.5%. The honest pre-build projection (~6.4 tok/s,
1.30x) landed exactly.

## Bitstream — first fully-closed timing since build_023

build_031 netlist = commit 4d71adcc (VERSION CSR verified 0x4D71ADCC).
Winner: out_build_031_rr_AltSpreadLogic_medium —
**WNS +0.006 / TNS 0.000 (0 failing of 1,140,061 endpoints), WHS +0.010**
at 250 MHz layer / 300 MHz engines. build_030 shipped at -0.141.

- First roll -0.338/-554: census (build_031_firstroll_census.txt) put
  2,783/4,888 endpoints in unchanged u_dn + ~870 in interconnect
  (3-logic-level = placement distance); the REWRITTEN u_alu/u_vn worst
  was **-0.002 ns** — the spec's capture-register/registered-ROM/DSP-reg
  rules removed the old WNS cones (build_030's #1-#4 paths were in
  these two units).
- Reroll spread: AltSpreadLogic_medium **+0.006**, SSI_HighUtilSLRs
  -0.008, ExtraNetDelay_low -0.128, ExtraTimingOpt -0.374.
- Utilization deltas vs build_030: DSP 1,856 -> 1,858 (+2; Vivado
  trimmed the narrow new multipliers), LUT 257,773 -> 257,351 (-422),
  BRAM 543 -> 560.5 (+17.5 tiles, 0.8% of device), URAM 348 (=).

## Gates

Sim (all in commit 4d71adc, logs under evidence/rung2/):
1. Differential TBs vs frozen legacy RTL (tb/legacy/): tb_vecalu_diff
   4 seeds x ~800 cmds + strict modes (+wfirst +coll_fatal +cfgscramble),
   tb_vecnorm_diff 4 seeds x 120 vectors with random s_valid gaps +
   m_ready backpressure; 7 sabotage self-tests prove every comparator
   fires. New vec_alu: ZERO same-cycle write/read-port collisions
   (read-port parking); RTL assertion guards the invariant.
2. Unit TBs unmodified: tb_vec_alu, tb_vecnorm x4 seeds.
3. Committed-script regression unmodified: layer/seqlayer/token/chain
   x4 seeds; token24 x4 (950,007 checks/seed); model_v2_s1 real-weights
   (1,900,014 checks). Bit-exact.
4. tb_seq_chip: tok2_s1.e PASS; model_v2_s1.e all 60,495 records,
   6 tokens, 7,168 scratch words bit-exact (110.6M cyc sim).
5. Verilator -Wall + slang lint: clean.

Hardware (build_031, one programming, no reprogram between runs):
- MAGIC/VERSION/CALIB verified (0xFAB1E001 / 0x4D71ADCC / 0xF) before
  any DMA.
- Host-driven ladder: frozen layer_s1-4 + token_s1-4 8/8; chain 4 seeds
  x 2 runs 8/8; token24 4 seeds x 2 runs 8/8 (2,174,391 checks/run);
  model_v2 2/2 — 0 errors everywhere (hostgate_*_build031.{json,log}).
- Sequencer: seq_run.py model_v2_s1.e x 2 — the headline table above.

## RTL delta (what rung 2 actually is)

- rtl/vec_alu.sv: serial per-element FSM -> in-order single-lane token
  pipeline. II=1 all ops except op 8 (3 words/elem, II=2) and op 9
  (2 writes/elem, II=2); pair ops with unused srcb fetch lo/hi via both
  read ports. Reductions (AMAX32/DYNQ8/DYNQ16/probe) close in II cycles,
  order-preserving (single lane — AMAX32 first-occurrence-wins forbids
  lanes). Measured 1.298 cyc/elem on the real op mix (was 10.55).
  done/k_we/e_out/amax CSR semantics preserved bit-for-bit.
- rtl/vecnorm_unit.sv: OUT loop pipelined to exactly II=1 (1023 cyc for
  1024 elems), 2nd multiplier so O_M1/O_M2 overlap, EPSC 64-bit shifter
  split over 5 per-vector stages (was a chip top-10 violated path).
- rtl/layer_chan.sv (F_* grant only): VN/ROPE feed 4 cyc/elem -> 1
  elem/cycle with a 1-deep skid.

## After rung 2 — where the next token goes

Device 156.2 ms/token: matvec+movers ~73 ms (~47%), residual element
work ~7 ms, remaining ~76 ms = non-ALU layer commands + sequencer
issue + mover overhead (needs a fresh census before picking rung 3
vs argmax-combine vs issue-path work). Bandwidth floor unchanged at
~7 ms/token (140 tok/s).
