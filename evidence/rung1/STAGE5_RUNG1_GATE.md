# Stage 5 rung 1: on-chip sequencer — PASSED (chip runs its own decode loop)

Date: 2026-08-09. Board: BCU-1525 on snoke. Bitstream: build_030_rr_
AltSpreadLogic_medium (netlist 9e1e0bae, VERSION CSR verified), JTAG
volatile, WNS -0.141 (== build_026's shipped/HW-gated level, axi_aclk).

## What was proven ON SILICON

The full 24-layer real Qwen3.5-0.8B decode loop executed BY THE ON-CHIP
SEQUENCER: the host uploads the record stream + weights + embedding,
writes SEQ_BASE/LEN, presses START, and drains generated tokens — the
chip fetches and executes all 60,495 records itself (embed, 24 layers,
LM head, argmax, token feedback, loop), with NO per-command host MMIO.

seq_run.py --prefix model_v2_s1.e, 2 runs, repeatable to the microsecond
(evidence/rung1/seqrun_model_v2_build030.log):
- halted pc=60494/60495, STATUS err=False, err_code=0x00
- tokens [561,314,279,369,279,6511] IDENTICAL to the golden (.seq.json)
- 7,188 post-halt state checks (scratch/XRF/banked/FIFO) ALL MATCH
- perf: 305,008,161 cyc; 89,979 records executed; fetch_starved 95 cyc
  (0.00003% — prefetch never a bottleneck); xrf_ovf False

Preceded by the host-driven HW ladder on the SAME bitstream (proves the
pipelined build_030 core is transparent on silicon): frozen layer_s1-4
+ token_s1-4 8/8; chain 8/8; token24 8/8; model_v2 2/2; all 0 errors
(evidence/rung1/hostgate_*.json).

## The speedup (rung 1 of docs/SPEEDUP_LADDER.md)

Same model_v2_s1 stream (6 forward passes = 3-token prompt prefill + 3
autoregressive decode):
- host-driven (layer_test.py):   ~30.8 s wall  = 0.195 tok/s  (MMIO-bound)
- sequencer-driven (seq_run.py):  1.222 s wall  = 4.91 tok/s
=> 25x wall-clock speedup. Device time 1220.03 ms ~= wall 1222 ms
   (99.97%): the host-orchestration overhead is ELIMINATED, exactly the
   rung-1 goal. Sequencer wall is now device-limited.

Note vs the ~12 tok/s ladder target: this stream drives 1 matvec channel
(all MVGO on chan 0). The 4-channel weight-split path (tok_meter proved
4.03x matvec scaling, 12.23 device tok/s) is a pure GENERATOR option, no
RTL — the natural rung-1b. The RTL rung (sequencer) is done.

## How it was built (waves, all bit-exact in sim first)

ISA frozen v1.5 (docs/SEQ_ISA.md). Reference numerics (DYNQ16 + integer
eps-norm, zero fidelity delta), binary stream format + python executor,
vec_alu/vecnorm/layer_chan compute ops + XRF, seq_unit + seq_movers,
full-chip tb_seq_chip (SEQ-driven == golden incl. full model_v2). First
hardware build (build_029) raw WNS -1.543 from 3 deep new paths (MOVY
dequant, EPS-NORM scale, SEQ fetch); pipelined by retiming (build_030)
-> -0.188 -> directive spread -0.141. No RTL bug found in any wave.
