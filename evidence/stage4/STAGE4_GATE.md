# Stage 4 gate: end-to-end token, autoregressive, bit-exact — PASSED

Date: 2026-07-22. Board: SQRL BCU-1525 (xcvu9p-fsgd2104-2L-e) on snoke,
PCIe 82:00.0, JTAG-programmed volatile bitstream (never flash).

## What was proven

The full token path, ON-CHIP and AUTOREGRESSIVE for 3 tokens per seed:
embedding lookup (host c2h reads the embedding table from DDR4 at
0x6000_0000 — the M records are real DMA, not host-side constants) →
DeltaNet layer → full-attention layer → final RMSNorm → LM head over an
8192-entry vocabulary (real 8192-row W4A8 matvec on matvec_chan, streamed
from DDR4, in 2 chunks of 4096 rows) → ON-CHIP argmax (vec_alu op 10
AMAX32; result read from CSRs AMAXI 0x28 / AMAXV 0x2C) → next token fed
back as the next embedding lookup. Bit-exact against the self-built
reference (ref/layer_fixed.py via ref/gen_layer_script.py) at every
checked record.

Reduced vocab justification (charter allows if stated): 8192 covers both
LM-head chunking (>1 chunk) and argmax-across-chunks logic; the compute
path is identical at any vocab size. Path to full vocab (248,320 rows):
the same flow with 61 chunks of 4096 rows — no RTL change, only script
generation; weight upload grows from 2 to 61 x 16 MiB images.

## Simulation gate (passed first, commit 112035c)

Verilator TB (tb/, obj_dir_token): 4 seeds x 728 cmds / 80,022 checks,
autoregressive 3 tokens, argmax CSRs checked per token.
Evidence: evidence/stage4/tb_token.log.

## Hardware evidence (charter: 4 seeds x 2 runs, no reprogram between)

Bitstream: synth/out_build_023_rr_Explore (netlist git b1ef323a, impl
reroll with PLACE_DESIGN directive Explore; VERSION CSR reads
0xb1ef323a). Programmed once via the safe flow (pcie remove → JTAG →
rescan; pcie_helper.sh now NOPASSWD-sudo on snoke), link 8.0 GT/s x8,
CALIB=0xF. Then, without reprogramming:

| script (seed) | run | cmds | checks | HW matvecs | errors |
|---|---|---|---|---|---|
| token_s1 | 0 | 728 | 199,926 | 48 | 0 |
| token_s1 | 1 | 728 | 199,926 | 48 | 0 |
| token_s2 | 0 | 728 | 199,926 | 48 | 0 |
| token_s2 | 1 | 728 | 199,926 | 48 | 0 |
| token_s3 | 0 | 728 | 199,926 | 48 | 0 |
| token_s3 | 1 | 728 | 199,926 | 48 | 0 |
| token_s4 | 0 | 728 | 199,926 | 48 | 0 |
| token_s4 | 1 | 728 | 199,926 | 48 | 0 |

Report: evidence/stage4/token_hw_build023.json. Runner: sw/layer_test.py
(same scripts as the Verilator TB; HW check count is higher than the sim
gate's 80,022 because the runner also compares every row of every real
matvec, including the two 4096-row LM-head chunks).

Stage-3 regression on the SAME bitstream (no reprogram): layer_s1..s4
x 1 run, 707 cmds / 172,269 checks / 45 matvecs each, 0 errors
(evidence/stage4/layer_hw_build023_regression.json).

## Honest timing (fresh report, bd_wrapper_timing_summary_routed.rpt)

TIMING FULLY MET — first netlist of this project to close outright:
- xdma_0_axi_aclk (250 MHz target): WNS = +0.003 ns (Fmax 250.2 MHz).
- Whole design: 0 failing among 1,026,438 setup endpoints, TNS 0.000;
  WHS = +0.010 ns, THS 0.000; pulse width clean. All four DDR ui_clk
  domains (300 MHz) met.
- How: build_023's direct route missed (axi_aclk WNS -0.240). Four
  parallel impl rerolls of the same netlist (synth/scripts/
  launch_reroll.sh, synthesis reused): Explore +0.003 (this bitstream),
  ExtraTimingOpt +0.003, ExtraNetDelay_low -0.142,
  AltSpreadLogic_medium -0.339.

## Delta vs stage 3 netlist

b1ef323a adds only AMAX32: a small serial compare in vec_alu (op 10)
tracking running max value/index during output emit, exposed at CSRs
AMAXI/AMAXV — low timing risk, confirmed by the reroll closing timing.
