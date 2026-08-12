# Rung 2 — pipeline vec_alu + vecnorm to II=1 (plan, 2026-08-09)

Goal: kill the 64% of sequencer device time spent in layer_chan element
ops. Ladder said "8-16 lanes"; reading the RTL says the cheaper truth is
that both units are LATENCY-bound serial loops whose datapaths are
already cut into small registered stages (SH_A/SH_M/SH_C/SH_F etc.) —
each element just walks the stages alone. Convert the walk into an
initiation-interval-1 pipeline. No scratch geometry change, no lane
replication, no central-mux surgery, no ISA/script/numerics change.

## Baseline (build_030, rung-1 gate, committed evidence)

- 4.91 tok/s; 1220.5 ms device / 6 tok = 203.4 ms/token.
- Layer busy (LCYC) 71.58 ms/token: vec_alu 52.30 (73%, 1,251,392
  element-ops @ 10.4 cyc avg), vecnorm 12.34 (17%, 17.5 cyc/elem),
  other 6.94. (evidence/stage5/TOKS.md)
- Scratch: 16K x 16, 2 replicated read ports + 1 write port, 16b/cycle
  each, 250 MHz.

## Mechanism

vec_alu: per-element FSM walk E_RD..WR = ~10.4 cyc. Element ops are
independent (AMAX32/DYNQ8/DYNQ16 reductions are order-preserving
streaming compares — a single comparator at 1 elem/cycle preserves
first-occurrence-wins exactly). Pipeline: address generator issues one
element per cycle; existing stage decomposition becomes the pipe.
Port-bound exceptions (16b ports kept): op 8 EMUL32 reads 3 words -> II=2;
op 9 SHIFT32W writes 2 words -> II=2. Pair ops that don't use srcb
(1/6/9/10/12) fetch lo via port a + hi via port b -> II=1.
Est. avg ~1.3 cyc/elem -> vec_alu 52.30 -> ~6.5 ms.

vecnorm: FILL already 1/cyc; RSQ per-vector; OUT loop ~14 cyc/elem
serial -> pipeline OUT at II=1 (needs 2nd DSP mul so O_M1/O_M2 overlap).
Est. ~2.1 cyc/elem -> 12.34 -> ~1.5 ms.

Layer busy 71.58 -> ~15 ms/token (the ladder's rung-2 target).

## Honest projection

Device/token 203.4 - (64.6 - ~8) => ~147 ms -> **~6.9 tok/s (1.40x)**.
The ladder's "35-45 tok/s" needs rung 2 + rung 3 (matvec row bubble)
+ the RTL argmax-combine (4-chan) TOGETHER; rung 2 alone moves the
bottleneck to matvec+movers (~73 ms/tok, 36%). After rung 2 the next
census decides rung 3 vs argmax-combine.

## Hazards the spec must pin (investigation agent confirms first)

1. Src/dst overlap: pipelined writes trail reads by pipe depth. Exact
   in-place (dst==srca) is safe (write i lands before read i+depth of a
   LATER index). Any shifted overlap breaks. Audit every generator call
   site; encode the allowed relation as a sim-only assertion.
2. Scratch read latency contract (addr -> Q -> registered = 2 cyc) and
   whether the port muxes in layer_chan (:1143) allow back-to-back
   addresses every cycle for vec_alu's two ports simultaneously.
3. vecnorm feed/drain: does layer_chan stream s_valid at 1/cyc and
   accept m_valid at 1/cyc, or is the measured 17.5 partly dispatcher
   stalls?
4. Timing at 250 MHz on an already WNS -0.141 design: reuse the existing
   small-stage structure; per-op controls registered at dispatch (as
   today); watch the new write-port arbitration. DSP adds are trivial
   (a few 33x33).
5. Two-pass ops (DYNQ8/DYNQ16): pass-1 scan pipelines; K_E/Q_E stay
   per-vector; pass 2 is the op-1/15 pipe. k_we/e_out/amax CSR timing
   to layer_chan unchanged.

## Verification (numerics unchanged => goldens are free)

- NEW differential unit TB (tb/tb_vecalu_diff.sv + tb_vecnorm_diff.sv):
  legacy RTL copy as reference vs pipelined RTL, randomized op sweeps
  (all ops x lens x overlap-legal src/dst x extremes), 4 seeds, $fatal.
- Full regression UNMODIFIED: tb_layer_chan on committed stage-3/4/5
  scripts (layer_s1..4, token_s1..4, chain_s1..4, token24_s1..4) +
  tb_seq_chip on tok2/model_v2 streams. Bit-exact or it doesn't ship.
- Verilator -Wall clean; 4 seeds minimum everywhere.

## Build + HW gate

- build_031 via launch_build.sh on snoke; reroll campaign if WNS < 0;
  honest WNS reported before/after.
- Safe reprogram flow; HW gate = seq_run.py model_v2 + token24 hostgates,
  4 seeds x 2 runs no reprogram, tokens bit-exact; LCYC/PERF before/after
  census -> evidence/rung2/, ladder updated, commit at green.

## Execution (Opus agents, frozen-contract workflow)

- Agent I: read-only investigation (hazard list above + op histogram per
  token from a real model_v2 script + DSP/BRAM headroom from build_030
  reports). Then I freeze docs/RUNG2_SPEC.md.
- Agent A: rtl/vec_alu.sv pipelined rewrite (owns that file only).
- Agent B: rtl/vecnorm_unit.sv pipelined OUT (owns that file only;
  layer_chan.sv changes only if the spec grants them).
- Agent C: differential TBs + regression running (owns tb/tb_*_diff.sv,
  new-file namespace assigned in the prompt).
- Me: spec freeze, integration, sim gates, build_031, reroll, HW gate,
  evidence, commits.
