# DMA hang debug — 2026-06-11 (~05:00-05:40)

Symptom: after JTAG-programming build_005 (remove -> program -> rescan),
PCIe link Gen3 x8 up, BAR0 + AXI-Lite CSR fully working (MAGIC/VERSION/
CALIB=0xF/uptime@250.2MHz), but EVERY DMA (H2C and C2H, any address incl.
unmapped) times out after 10 s with errno 512.

Evidence chain:
1. Engine regs live-sampled during 4KB H2C: status=0x1 (BUSY) entire 10 s,
   completed_desc=0, no error bits. Engine wedges on its FIRST operation.
2. C2H identical -> common first step = descriptor fetch (upstream MRd).
3. DMA to UNMAPPED AXI address (0x4_0000_0000) also hangs 10 s (no fast
   DECERR) -> transactions never reach SmartConnect; stall is on the PCIe
   side, not AXI/MIG.
4. intel_iommu=off, 0 iommu groups -> no DMAR blocking. pci=noaer -> AER
   reporting disabled (errors invisible).
5. EP and root-port command regs: MEM+ BUSMASTER+ both. ACS all disabled.
6. **XDMA config block 0x3004 (captured Bus/Device) = 0x0000** after both
   the original rescan and a second remove/rescan cycle. Upstream MRd with
   RequesterID 00:00.0 -> completions cannot route back -> engine waits
   forever. Fully consistent with 1-5 (MSI/posted writes unaffected).
7. Root port + EP have sticky FatalErr; root port UESta shows SDES+
   (Surprise Down, latched at JTAG reprogram, masked by noaer).

Hypothesis: EP PCIe block never (re-)captured its bus number after the
reconfiguration; possibly stuck error/link state from the surprise-down.
Next step: Secondary Bus Reset on root port 80:02.0 (hot reset of EP,
full retrain + fresh enumeration). VERIFIED blast radius: secondary=
subordinate=bus 82, which contains ONLY the BCU-1525. NVMe (83:) and
10GbE (84:) are behind different root ports.
STATUS: awaiting user approval for SBR (auto-mode classifier denial).

## Update (~06:00) — corrections and narrowing
- SBR (user-approved) executed: did NOT fix; EP re-enumerated, DMA still
  times out, "BUSDEV" reg still 0.
- Direct setpci config write (cfgkick): capture register unchanged.
- CORRECTION: dma_ip_drivers libxdma.h declares config-block offsets
  0x04-0x10 as reserved_1[4] — "0x3004 = captured BusDev" may not be
  implemented in this IP revision, so that register reading is WEAK
  evidence. What remains solid: EP UESta CmpltTO+ (requests issued,
  completions never return), engines wedge on first descriptor fetch,
  link error counters clean, host config clean.
- Journal history: current boot up since May 26; the PREVIOUS design
  (also 10ee:9038, BAR0-only: "1 BARs: config 0, user -1, bypass -1")
  went through multiple remove/program/rescan cycles on Jun 2 within
  THIS boot — flow is proven on this host. ("12 timeouts" earlier was a
  miscount: pattern matched the driver banner "timeout: h2c 10 c2h 10".)
- CONCLUSION: fault is in build_005's XDMA configuration (not host, not
  flow, not board). Control builds out_ctl_A (stock VCU1525 x8 preset +
  BRAM) and out_ctl_B (A + axi_data_width/axisten_freq/axilite_master_en/
  xdma_pcie_64bit_en) bisect the config space. Note: enabling
  axilite_master_en auto-moved pf0_msix BIRs to BAR_3:2 (param diff) —
  MSI-X capability pointing at a BAR that may not exist; kernel fell back
  to MSI. Suspect list for B: that MSI-X BIR motion; xdma_pcie_64bit_en.

## Control-build bisection (~06:30)
- ctl_A (pure official VCU1525 x8 preset, auto-derived width/freq) + BRAM:
  driver probe FAILS — "Failed to detect XDMA config BAR". Root peek of
  BAR0 shows the register map ADDRESS-SCRAMBLED (cfg-block id at +0x0000,
  H2C id at +0x0004, C2H at +0x2000, IRQ at +0x3000). The auto-derived
  axisten width/freq combination produces a broken core. Conclusion:
  explicit 256_bit/250MHz (as in build_005) is CORRECT and A is a separate
  pathology — not a useful "known good".
- ctl_B (= build_005's exact XDMA config) + BRAM only: BAR map correct,
  link 8GT/s x8, but DMA fails identically to build_005 (10s timeout).
  => Bug reproduces WITHOUT DDR4/SmartConnect/CSR. It is in the XDMA
  config set or something shared by all our builds (refclk wiring/XDC).
- In flight: ctl_C (preset + width/freq only), ctl_D (C + pcie_64bit_en),
  ctl_E (C + axilite_master_en).

## ROOT CAUSE (~07:00) — unconstrained PCIe clock tree
ctl_C's routed timing summary: only 564 total endpoints for a 23k-LUT
design; Clock Summary contains ONLY the GT cal-block monitor clocks — no
pcie_refclk, no userclk/coreclk, no 250MHz axi clock. build_005's Clock
Summary likewise has dimm refclks + MIG-derived clocks but NO pcie/XDMA
clocks: its 231k endpoints are all DDR-domain. Diagnosis:

  The community BCU1525 XDC contains only pin LOCs. Nothing created the
  100 MHz pcie_refclk clock, and the BD did not auto-emit it, so the
  XDMA's ENTIRE derived clock tree (userclk/axi_aclk @250MHz: DMA engines,
  descriptor logic, BAR decode, SmartConnect S-port, csr) was timed
  against NOTHING. P&R results in that domain are silicon luck, varying
  per build: 005/ctl_B = BAR OK + DMA engines broken (CmpltTO from
  mis-sampled completions); ctl_A = scrambled BAR decode; ctl_C = dead BAR.
  DDR4 was immune because FREQ_HZ=300MHz was set explicitly on those ports
  (and DDR4 calibrated/ran perfectly every time). The community reference
  presumably "worked" at x1/62.5MHz where unconstrained logic passes by
  margin.

Fix (commit "ROOT CAUSE FIX"): synth/constraints/fable5_pcie_clk.xdc
(create_clock 10ns on pcie_refclk_clk_p) + CONFIG.FREQ_HZ on the BD port;
build.tcl now FAILS if no 250MHz clock exists post-route and reports
no_clock register pins. Validation: ctl_H (=ctl_B config + fix) on
hardware, then build_006 (full stage-1 + fix).

## VALIDATED (~07:20)
ctl_H (= build_005's exact XDMA config + create_clock fix, BRAM target):
- timing: WNS +0.343, 80,374 constrained endpoints (vs 564 unconstrained
  before the fix)
- hardware: link 8GT/s x8, DMA H2C 4KB instant, C2H readback bit-exact ->
  CTL_DMA_PASS
- closure: config-block 0x3004 reads 0 on the WORKING design too — that
  register is unimplemented in this IP revision; the requester-ID theory
  was a red herring. The CmpltTO+ latch was a side effect of broken
  (unconstrained) completion-stream logic.
ROOT CAUSE CONFIRMED. Fix is in build_006 (full stage-1 design, in flight).
