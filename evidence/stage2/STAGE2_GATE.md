# STAGE 2 GATE — PASSED 2026-06-12 01:36 (build_010, git cab6e9d9)

## Acceptance evidence (charter requirements)
- (a) Reference model: ref/w4a8_ref.py (all-integer W4A8 pipeline,
  quant_spec.md frozen; self-tested exact to 0.5 lsb of final rounding).
- (b) Simulation before hardware, three tiers, all bit-exact vs reference
  across 4 seeds x K={256,1024,2048,3584}:
  - tb_matvec (engine unit, randomized gaps/backpressure)
  - tb_streamer_engine (AXI memory model -> streamer -> engine,
    + permanent stream-integrity check)
  - tb_matvec_chan (full channel: AXI-Lite cfg/XWIN/doorbell/poll/RES_DATA
    over truly async 250/300 MHz clocks, XPM CDC)
  Logs: tb_all_rerun_restaged.log (12/12 PASS on final RTL).
- (c) Hardware: 4 seeds x 2 runs x 4 channels, N=4096 x K=3584 each
  (4096 results per run-combination, 32 combinations), single programming
  (build_010), ZERO errors — matvec_test_20260612_013559.json +
  stage2_hw_run.log. Stage-1 quick regression also PASS on this bitstream
  (ddr_test_20260612_013536.json).
- (d) Timing, fresh reports: WNS=+0.033 WHS=+0.010, CLOCK_GATE_OK —
  build_010_reports/.

## Charter deliverable: sustained DDR4 read bandwidth
14.66-14.68 GB/s per channel (on-chip counters: 118,784 beats x 64B over
cycles @ 300.12 MHz), uniform across all 4 channels and all 32 runs.
= 76% of 19.2 GB/s pin-rate peak; aggregate ~58.7 GB/s -> matches the
PLAN.md prediction band (55-60 GB/s). Updated decode ceiling at ~0.3 GB
INT4 weights/token: ~195 tok/s.

## Iterations
Two full builds for this stage (009: WNS -0.68 in engine tree -> re-staged
pipeline; 010: clean). One BD create failure (axil address collision,
fixed two-pass). TB infrastructure bugs found & fixed during re-verify
(documented in commit log).
