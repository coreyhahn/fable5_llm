# STAGE 1 GATE — PASSED 2026-06-11 09:48 (build_007, git 35d95a53)

## Acceptance evidence (charter requirements)
- (a) Reference model: PRNG byte stream per (seed,channel), regenerated
  independently for write and compare — sw/ddr_test.py.
- (b) Simulation before hardware:
  - csr_block: Verilator TB, 4 seeds, model-checked soak + bounded-response
    (evidence/stage1/tb_csr_run.log)
  - DDR4 config: example-design xsim with custom Ballistix part —
    calibration + traffic TEST PASSED, ZERO model violations after local
    tFAW fix 13->21ns (evidence/stage1/ddr4_ex_sim*, the violating run
    archived alongside)
- (c) Hardware: 4 seeds x 2 runs x 4 channels x 4 GiB, single programming,
  zero byte errors — evidence/stage1/ddr_test_20260611_094834.json +
  hw_bringup_20260611_092507.log. Gates passed: PCIe 8GT/s x8 (sysfs),
  CSR MAGIC/VERSION==35d95a53/CALIB=0xF instant/uptime/scratch.
- (d) Timing, fresh reports: WNS=+0.062 WHS=+0.010 with the FULL clock
  tree constrained (CLOCK_GATE_OK: pipe_clk + xdma_0_axi_aclk), PCIe block
  X1Y2, GT quads 226/227 — evidence/stage1/build_007_reports/ (to copy).

## Informational
- Raw PCIe DMA (1 GiB, pre-generated buffers): H2C 4.8 GB/s, C2H 1.3-1.5
  GB/s, readback bit-exact. (ddr_test.py per-chunk rates are Python-bound;
  sustained DDR bandwidth measured on-chip is a stage-2 deliverable.)
- Build iterations consumed: 7 full builds (001-007) + 6 control builds
  (A-E,H). Root causes: 3x scripting (SV module-ref, axilite param name,
  port self-rename), 1x community-data bug (tFAW x4-vs-x8), 1x systemic
  (unconstrained pcie_refclk -> entire XDMA clock domain untimed; full
  narrative in dma_hang_debug/FINDINGS.md), 1x own-RTL constraint (CDC
  false-path for calib synchronizer).
