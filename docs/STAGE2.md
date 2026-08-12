# Stage 2 — streamed W4A8 matvec (design draft, refine before RTL)

## Goal (charter)
W4A8 matrix-vector product with weights streamed from DDR4, bit-exact vs
ref/w4a8_ref.py, sustained DDR4 read bandwidth reported from hardware.

## Architecture (one engine per DDR4 channel, x4)

```
DDR4 ch_i (AXI 512b @300MHz ui_clk)
   └─ rd_streamer_i  — AXI RD master, issues max-burst INC reads over the
       row-slice assigned to channel i; elastic FIFO (XPM) into engine clk
   └─ matvec_engine_i — consumes 512b beats:
       row layout per quant_spec.md: [K/2 B packed w4 | NG*2 B scales] pad64
       - 512b beat = 128 nibbles = one full group G=128 per beat!
         (deliberate: G chosen so one AXI beat == one scale group)
       - 128x INT4xINT8 multiplies + adder tree (DSP-packed, 2 mults/DSP48E2)
         -> acc_g int18 -> xm = m_g * acc_g (1 DSP) -> p += xm (int64 acc)
       - row end: y32 = rshift_round(p, sh); push to result FIFO
   └─ x8 activation vector: broadcast-written by host (stage 2) into BRAM
       before kick; double-buffered later
CSR additions: doorbell (start row range), status, beat/cycle counters
   (sustained-BW measurement), result readback via C2H or result BRAM->AXI.
```

Throughput target per channel: 1 beat/cycle @ ~300MHz = 64B*300M = 19.2 GB/s
issue rate; DDR4-2400 sustained sequential ≈ 13-15 GB/s → engine is
DDR-limited as intended. 128 mult-pairs/beat ≈ 38 GMAC/s/channel.

## Bit-exactness invariants (must match ref/w4a8_ref.py exactly)
- group partial acc_g: int (no saturation; bound 2^17)
- p accumulation: int64, sequential group order within row
- y32 = rshift_round(p, sh) — round-half-away-from-zero, sh from quantizer
- nibble order: low nibble = even k (pack_w4)

## Sim plan (before any hardware)
1. matvec_engine TB (Verilator): drive beats from ref-packed image of random
   matrices (ref dumps .hex + golden y32); randomized backpressure; 4 seeds.
2. rd_streamer TB against AXI memory model (verilator_lib XPM ok; simple
   behavioral AXI slave with random latency) — address/burst correctness,
   no 4KB crossing, throughput counter sanity.
3. Integration sim: streamer+engine against behavioral DDR model preloaded
   with ref image; compare y32 stream bit-exact.

## Hardware plan
- Reuse stage-1 BD + add engines & CSR doorbell; weights loaded via XDMA
  into each channel; kick; read y32; compare vs ref on host. 4 seeds x 2.
- BW counters: beats observed / cycles elapsed per channel -> CSR regs;
  report sustained GB/s during a long multi-row stream.

## Open items
- Result return path: CSR-polled BRAM (simple, fine for matvec stage) vs
  C2H writeback (needed by stage 4 anyway?) — decide at RTL time.
- Activation BRAM size: max K = 3584 bytes — trivial.
- Engine clock: run at ui_clk (300MHz) per channel to avoid CDC on the hot
  path; CDC only on x8 broadcast + results (slow paths). Single-clock rule
  (CLAUDE.md) is per-module; cross-channel is inherently multi-clock — keep
  each engine fully in its channel's ui_clk domain.
