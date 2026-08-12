# Constraint / part-data provenance

- `BCU1525_DIMM[0-3].xdc` and `BLS4G4D240FSB.csv` copied verbatim from
  `~/r2d2/code/fpga/references/Custom_Part_Data_Files`
  (github.com/d953i/Custom_Part_Data_Files, GPLv2) — community pin data for
  the SQRL BCU-1525. DIMM0 XDC also carries PCIe refclk (AM11/AM10) and
  PERST# (BD21) and enables bitstream compression.
- PCIe x8 GT placement cross-checked against TWO independent sources
  (evidence/recon/):
  - Official Xilinx VCU1525 board files (XilinxBoardStore 2024.2 branch,
    `vcu1525/1.3/preset.xml`): x8 XDMA preset = mode Advanced,
    en_gt_selection=true, select_quad=GTY_Quad_227, 8.0 GT/s.
    `part0_pins.xml`: refclk AM10/AM11, lanes 0-7 = AF1/AF2 .. AN3/AN4.
  - Vivado 2024.2 device model query (`evidence/recon/query_device.log`):
    AM11 = GTYE4_COMMON_X1Y7 (bank 226); lane0 AF2 = GTYE4_CHANNEL_X1Y35
    (quad 227) .. lane7 AN4 = GTYE4_CHANNEL_X1Y28 (quad 226).
- The board currently enumerates as Xilinx device 0x9038 (= XDMA encoding for
  Gen3 x8) at 82:00.0 on snoke, proving the slot is Gen3 x8 capable.

## Local deviation from upstream (2026-06-11)
- `BLS4G4D240FSB.csv`: tFAW for the -2400 grade corrected 13000 ps -> 21000 ps.
  Upstream used the JEDEC x4 (1/2KB page) tFAW; these DIMMs use 4Gb x8
  components (1KB page) which require 21 ns. Found via DDR4 example-design
  simulation: the Micron model logged 248 cmdACT tFAW violations
  (evidence/stage1/ddr4_ex_sim_tfaw13/). All other fields audited vs JEDEC
  DDR4-2400 4Gb x8: correct or conservative (tRFC=350ns is the 8Gb value).
