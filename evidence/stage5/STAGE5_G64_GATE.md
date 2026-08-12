# Stage 5 g=64 quantization: dual-mode engine — PASSED

Date: 2026-08-06. Board: BCU-1525 on snoke. Bitstream:
build_028_rr_SSI_HighUtilSLRs (netlist 67a943bd, VERSION CSR verified),
JTAG volatile, safe-reprogram flow.

## What shipped

- matvec_engine is DUAL-MODE: legacy G=128 (mode 0, bit- AND cycle-
  identical — regression-proven in unit TBs) and G=64 (mode 1) selected
  per matvec via SHAPE bit 28. v2 row format: two 64-weight groups per
  beat, ceil(NG64/32) scale beats; +1 DSP/engine; drain retires one
  beat/cycle in both modes (mode-1 utilization measured slightly higher).
  Normative format spec: ref/w4a8_ref.py header.
- Full toolchain g-parameterized (quantizers, packer, manifests with
  per-wid "g", host SHAPE via hwmap.shape_word); committed g128
  manifests untouched (hash-proven).

## Default decision: g128 stays (measured, 44-sample teacher-forced)

g128 30/44 vs g64 27/44 top-1 vs bf16 (fidelity_g64_decision.log;
consistent with 16/24 vs 14/24 at the smaller sample). g64 remains a
per-script capability (--w4-group=64): its measured advantages — rank
max 75 vs 845, top-5 3.02 vs 2.77, better free-run text on 3/4 prompts
incl. the exact-bf16 " is Paris." — are documented for future use; the
finer scales currently give back part of their gain to int16 dequant
pressure in the fixed-point datapath.

## Timing journey (netlists 07ffc7b9 -> b9eaa87 -> 67a943bd)

build_027 (dual-mode engine): raw -0.942; 7 valid directives best
-0.363 (engine ui_clk domains MET — the new drain closes at 300 MHz;
axi_aclk placement noise dominated). Census: worst family = conv state
BRAM DOREG -> 18:1 mux -> cs_q (9 levels). Iter5 (67a943b): second
per-bank fabric read stage + CV_W3 wait state. build_028: raw -0.607
(TNS 3x better), spread: SSI_HighUtilSLRs -0.106 / WHS +0.007 (this
bitstream), ExtraTimingOpt -0.194, ExtraNetDelay_low -0.195,
AltSpreadLogic_medium -0.256. WNS -0.106 = Fmax 243.6 MHz — the best
banked-netlist timing to date (prev gated: -0.142). Note:
SpreadLogic_high and SSI_ExtraTimingOpt are NOT valid placer
directives in this flow (rejected by Vivado 2024.2).

## Hardware gates on this bitstream (one programming)

| gate | runs | checks/run | result |
|---|---|---|---|
| chain_s1..4 (mode 0) | 4x2 | 315,642 | 8/8 PASS |
| token24_s1..4 (mode 0) | 4x2 | 950,007 | 8/8 PASS |
| model_v2_s1..4 (real weights, mode 0) | 4x2 | 5,789,550 | 8/8 PASS |
| frozen layer/token s1..4 (LAYER=0 + mode 0) | 8x1 | -- | 8/8 PASS |
| model_g64_s1 (real weights, MODE 1, 187 g64 images, 61-chunk head) | 1x2 | 5,789,550 | 2/2 PASS |

0 errors everywhere (g64gate_*.json). Sim ladders preceded hardware at
every step (16-script CV_W3 regate + 36 unit-TB runs both modes).
