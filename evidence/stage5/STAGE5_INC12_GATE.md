# Stage 5 increments ① + ②: layer-banked engine, 24-layer chain — PASSED

Date: 2026-07-26. Board: SQRL BCU-1525 (xcvu9p) on snoke, JTAG volatile.

## What was proven on hardware (one programming, no reprogram between runs)

Bitstream: synth/out_build_026_rr_AltSpreadLogic_medium (netlist git
07ffc7b9, VERSION CSR 0x07ffc7b9), safe-reprogram flow, CALIB=0xF.

| gate | scripts | runs | result |
|---|---|---|---|
| ① 8-layer chain (2 full 3DN+1GQA periods, banked dn/kv/conv/TCNT, L records) | chain_s1..4 (3,390 cmds, 315,642 checks each) | 4 seeds x 2 | 8/8 PASS, 0 errors |
| ② 24-layer autoregressive token (18 DN + 6 GQA, embed->24 layers->RMSNorm->LM head 8192->argmax, 3 tokens, packed 187-wid DDR map) | token24_s1..4 (10,191 cmds, ~950K sim checks) | 4 seeds x 2 | 8/8 PASS, 0 errors |
| regression (LAYER=0 backward compat on silicon) | layer_s1..4 + token_s1..4 | 8 x 1 | 8/8 PASS, 0 errors |

Reports: chain_hw_build026_ASM.json, token24_hw_build026_ASM.json,
regression_hw_build026_ASM.json. Sim gates preceded hardware at every
step (sim_backcompat.log, sim_chain.log, sim_token24_s*.log,
sim_iter4_regate.log).

## Honest timing

- xdma_0_axi_aclk (250 MHz target): WNS = -0.142 ns => achieved Fmax
  241.4 MHz. WHS = +0.004. The empirical gates above ran bit-exact
  24/24 at the full 250 MHz on this silicon; the deficit is reported,
  not hidden. A second directive spread (SSI_*, AltSpread_high/low) was
  still in flight at gate time; a closing impl can replace this
  bitstream without RTL change (re-gate required after any reprogram).

## The hardware-only bug this gate caught (why HW gating matters)

First gate attempt (build_025_rr_mcp2_ExtraTimingOpt, WNS -0.076) FAILED
on all script families including the stage-4 regression. Root cause:
three multicycle exceptions (vdata_q, dn_vdata, conv bank BRAMs) were
justified by SOURCE VALUE CADENCE (3-4 cycles between changes) — but
their consumers capture with enables aligned exactly 1 cycle after
launch. The MCP let the router exceed one period; silicon latched
mid-flight data. Zero-delay simulation is structurally blind to this
class. Rule now encoded in synth/constraints/layer_mcp.xdc: an MCP
requires the VALUE to be constant across every enabled capture that can
influence results — source cadence is never sufficient.

Valid exceptions that remain: dn decay_r/beta_r (command-constant);
attn p_t_r/shamt_r/vadd_r, legal only together with the P_VW2 state
added to attn_core (dead intermediate captures — proof in the RTL
comment). conv bank mux registers are dont_touch-pinned (synthesis had
retimed them into DSPs, recreating the critical path).

## Timing journey (banked netlists, routed axi_aclk WNS at 4 ns)

024 raw -1.586 (comb conv bank mux + URAM-spread placement)
025 iter1 (registered conv mux + CV_W2) raw -1.914
025 + Explore, MCPs silently dropped (foreach illegal in XDC) -1.021
025 + real-but-partially-UNSAFE MCPs: -0.048..-0.157 (HW FAIL)
026 (P_VW2 + dont_touch + safe MCP set) raw -0.902
026 rerolls: AltSpreadLogic_medium -0.142 (this bitstream),
  ExtraTimingOpt -0.282, ExtraNetDelay_low -0.392, Explore -0.622

## Resource cost of 24-layer banking (whole chip)

URAM 348/960 (dn 9x4096 banks = 261 + kv 3x4096 = 87), BRAM ~560/2160
(conv 18-bank w/s + everything else), LUT ~20%, DSP ~27%. All state for
24 layers resident on-chip; scratch residual streams between layers.
