# Stage 1 — bring-up: PCIe + 4× DDR4 + integrity test

## Design
Block design `bd` (synth/scripts/create_project.tcl):
- `xdma_0`: PCIe Gen3 x8 (GTY quad 227), AXI4 256-bit @ 250 MHz, 1 H2C +
  1 C2H DMA channel, AXI-Lite master BAR enabled. No DMA-bypass BAR.
- `ddr4_0..3`: DDR4-2400 UDIMM, custom part BLS4G4D240FSB-2400, 64-bit,
  AXI slave 512-bit @ ui_clk (300 MHz). sys_rst = NOT(PERST#).
- `axi_smc`: SmartConnect 1×SI → 4×MI, 5 clock domains (250 MHz XDMA + 4 ui).
- `csr_0` (rtl/csr_block.sv) on M_AXI_LITE: MAGIC/VERSION/SCRATCH/CALIB/UPTIME.

### Host-hang safety analysis (charter requirement)
The only host-visible MMIO paths are XDMA-internal BAR0 (DMA registers,
terminated inside hard IP) and the AXI-Lite BAR → csr_0, which completes
every transaction in bounded cycles by construction (no external wait
states; verified by TB property). There is NO path from host MMIO to a
DDR4/SmartConnect AXI port, so an uncalibrated/stalled MIG cannot stall a
PCIe read completion → cannot panic the host. A stalled DMA transfer (e.g.,
DMA to uncalibrated DDR) only hangs the DMA channel, recoverable by driver
timeout/reset; ddr_test.py additionally refuses to DMA before CALIB=0b1111.
Reprogram flow: remove from PCI tree → JTAG program → rescan (sw/pcie_helper.sh).

## Reference model
Data integrity reference = deterministic PRNG stream per (seed, channel):
numpy PCG64(seed*16+ch). sw/ddr_test.py regenerates the stream independently
for write and compare (never compares a buffer with itself).

## Evidence checklist
- [x] csr_block Verilator TB, 4 seeds, model-checked soak + bounded-response
      property → evidence/stage1/tb_csr_run.log (PASS 2026-06-10)
- [x] DDR4 IP sim with custom part: example design xsim run shows
      calibration completes + traffic test passes → evidence/stage1/ddr4_ex_sim/
      (sim-before-hardware evidence for the DDR4 config; XDMA path is
      unmodified vendor IP — its datapath is vendor-verified; our custom
      logic (CSR) and the address map are covered by TB + hardware test)
- [x] Build reports (build_007): timing (WNS ≥ 0), utilization, PCIE/GT placement on
      quads 226/227 → synth/out_build_NNN/reports/, copied to evidence/
- [x] PCIe enumerates Gen3 x8 (lspci LnkSta), /dev/xdma0_* present
- [x] CSR sane: MAGIC, VERSION == git hash of build, CALIB == 0xF
- [x] ddr_test.py full: 4 seeds × 2 runs × 4 ch × 4 GiB, zero byte errors,
      run WITHOUT reprogramming between runs → evidence/stage1/ddr_test_*.json
- [x] PCIe DMA throughput numbers logged (4.8/1.5 GB/s raw) (informational; DDR sustained BW
      is a stage-2 deliverable measured on-chip)

## Hardware procedure (needs user for sudo)
1. `ssh snoke` — build done? `synth/out_build_NNN/build.log` says BUILD_OK
2. `sudo sw/pcie_helper.sh remove`
3. `sw/program_fpga.sh synth/out_build_NNN/...bit` (JTAG, volatile)
4. `sudo sw/pcie_helper.sh rescan` (also chmods /dev/xdma0_*)
5. `lspci -s 82:00.0 -vv | grep LnkSta` → expect 8GT/s x8
6. `uv run sw/ddr_test.py --quick` then full run → evidence/
