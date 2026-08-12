# Stage 3 gate: full transformer layer, bit-exact end-to-end — PASSED

Date: 2026-07-04. Board: SQRL BCU-1525 (xcvu9p-fsgd2104-2L-e) on snoke,
PCIe 82:00.0, JTAG-programmed volatile bitstream (never flash).

## What was proven

One DeltaNet linear-attention layer + one full-attention layer, 3 decode
tokens each, computed ON-CHIP by the command-dispatched layer engine
(rtl/layer_chan.sv: vecnorm / rope / conv4+silu / gate / dn_step /
kvap+attn_core / vec_alu over a 16K x 16 scratchpad, DN state and KV
cache in URAM), with matvecs run for real on the stage-2 matvec_chan
engine (weights streamed from DDR4), bit-exact against the self-built
reference model (ref/layer_fixed.py via ref/gen_layer_script.py).

## Hardware evidence (charter: 4 seeds x 2 runs, no reprogram between)

Bitstream: synth/out_build_022_rr_Explore (netlist git 017fae3e,
impl reroll with PLACE_DESIGN directive Explore; VERSION CSR reads
0x017fae3e). Programmed once via the safe flow (pcie remove -> JTAG ->
rescan), CALIB=0xF, all IDENTs verified. Then, without reprogramming:

| script (seed) | run | cmds | checks | HW matvecs | errors |
|---|---|---|---|---|---|
| layer_s1 | 0 | 707 | 172,269 | 45 | 0 |
| layer_s1 | 1 | 707 | 172,269 | 45 | 0 |
| layer_s2 | 0 | 707 | 172,269 | 45 | 0 |
| layer_s2 | 1 | 707 | 172,269 | 45 | 0 |
| layer_s3 | 0 | 707 | 172,269 | 45 | 0 |
| layer_s3 | 1 | 707 | 172,269 | 45 | 0 |
| layer_s4 | 0 | 707 | 172,269 | 45 | 0 |
| layer_s4 | 1 | 707 | 172,269 | 45 | 0 |

Report: evidence/stage3/layer_hw_build022_rr_explore.json (raw JSON,
git hash, per-run stats). Runner: sw/layer_test.py — replays the same
scripts the Verilator TB uses; every R/E record checked, every V record
runs a REAL matvec on chan 0 (weights uploaded to DDR at 0x1000_0000 +
wid*16MiB) and compares all rows against the model's expected y32.

## Honest timing (fresh report, bd_wrapper_timing_summary_routed.rpt)

- xdma_0_axi_aclk (250 MHz target, the layer + CSR domain):
  WNS = -0.029 ns setup at slow corner (achieved Fmax 248.2 MHz),
  TNS = -2.547 ns over 230 of 387,350 endpoints, WHS = +0.010 ns.
- All four DDR ui_clk domains (300 MHz): MET (+0.000 .. +0.041).
- The 230 sub-30ps endpoints are route-noise leftovers (output-emit
  muxes / preload decodes inside layer_0). The empirical gate above ran
  bit-exact 8/8 at the full 250 MHz on this silicon; the deficit is
  reported, not hidden. Two further placement rerolls were still in
  flight at gate time; a later closed (WNS >= 0) impl can replace this
  bitstream without RTL change.

## The hardware bug this gate caught (why HW gating matters)

The first gate attempts (build_021 at WNS -0.021 AND its Explore reroll
at WNS 0.000 / 0 failing endpoints) failed IDENTICALLY: deterministic,
placement-independent, diverging exactly at the first DNST command.
Bisection with scratch dumps (layer_test.py --stop-after/--dump/
--zero-scratch vs the generator's GLS_DUMP_AT model dumps) plus
standalone DNST probe scripts isolated it: hardware o_acc came out
~44 * 2^32 too large — negative 32-bit lane products ZERO-extended into
the 40-bit accumulators.

Root cause: element selects of SIGNED PACKED arrays are UNSIGNED per
the LRM. Vivado synthesized 40'(q_p[v]) as zero-extension and
(pv_p[d] < 0) as constant-false; Verilator treats those elements as
signed (verified with a minimal test), so simulation agreed with the
model and could never catch it. matvec_engine survived stage 2 because
it wraps every element select in signed'(). Fix (017fae3e): all signed
lane arrays in dn_step and attn_core converted to UNPACKED arrays (+
per-lane generate blocks); sim re-verified bit-exact, then hardware.

## Timing-closure journey to this netlist (routed WNS at 4 ns)

011 URAM-infeasible fallback; 012 -5.7; 013 -4.6; 014 -3.21; 016 -2.608;
017 -2.218; 018 -0.466 (17-census fix set: pipelined variable rounding
shifts everywhere, x4 keep-replicas, input-registered preloads, axil
register slices); 019 -0.583 (op15+streamer fixed, x_mem flop-inference
exposed); 020 -0.184 (x_mem per-bank LUTRAM, all ui_clk domains met);
021 -0.021 (local reset pipeline, attn emit-mux split); 022 -0.255
(signedness fix netlist) -> Explore reroll -0.029 (this bitstream).
Census method: open the routed DCP, histogram all violated paths by
family, fix every family at once (synth/scripts/census_017.tcl).
