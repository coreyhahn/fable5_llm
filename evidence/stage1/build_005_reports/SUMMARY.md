# build_005 — stage-1 bitstream (program-ready) — 2026-06-11 01:00
- git: see commit; CSR VERSION reg carries the build's git short hash
- BUILD_OK; bitstream synth/out_build_005/proj/stage1.runs/impl_1/bd_wrapper.bit (33MB, 01:00 Jun 11)
- Timing: WNS=+0.231 ns, WHS=+0.010 ns (fresh report in this dir)
- PCIe hard block: PCIE40E4_X1Y2; GT lanes GTYE4_CHANNEL_X1Y28..35 =
  quads 226+227 = board lanes 7..0 (matches VCU1525 part0_pins)
- Zero "Common 17-55" (unmatched XDC constraint) in impl log — all board
  pin constraints applied
- Includes the tFAW 13ns->21ns CSV fix (DDR4 sim run 2: 0 violations)
- DO-NOT-PROGRAM list: build_004 and earlier (pre-tFAW-fix / failed)
