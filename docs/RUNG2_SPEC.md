# Rung 2 — FROZEN SPEC (2026-08-09): pipeline vec_alu + vecnorm to II=1

Supersedes the numbers in docs/RUNG2_PLAN.md (its baseline was the
host-driven model_s1 workload; the shipped build_030 SEQ stream fuses
op-1/op-9 dequant into MOVY). All findings below are investigation-
verified with file:line evidence (agent report, 2026-08-09).

## Corrected baseline + targets (build_030 SEQ stream, per token)

| unit | today | target | how |
|---|---|---|---|
| vec_alu | 42.72 ms (986,624 elem @ 10.82 cyc) | ~5.4 ms (≤1.4 cyc/elem) | II=1 pipeline |
| vecnorm | 11.17 ms (15.85 cyc/elem: 4 are the layer_chan FEED loop) | ~1.6 ms (≤2.3 cyc/elem) | II=1 OUT + 1/cyc feed |
| device/token | 203.4 ms | ~156 ms | |
| tok/s | 4.91 | **~6.4 (1.30x)** — honest; 35-45 needs rungs 3 + argmax-combine stacked | |

Residual after rung 2: DYNQ8 27.6% + AMAX32 18.4% + op8 16.4% of the
remaining 5.4 ms. Bottleneck moves to matvec+movers (~150 ms/token).

## Interface contracts — FROZEN, bit-for-bit

Module ports of vec_alu and vecnorm_unit DO NOT CHANGE. Internals only.

vec_alu preservation list (violating any = silent corruption in
tb_layer_chan even if a diff TB passes):
1. `done` = 1-cycle pulse, no earlier than the cycle of the last w_en
   (layer_chan A_RUN :1118 level-samples it; DONE_S->IDLE can retrigger).
2. `k_we`/`k_out`: DYNQ16 pulses MID-command (between pass 1 and pass 2);
   op-8 probe pulses WITH done. layer_chan latches xrf[alu_k_idx] on the
   k_we edge (:465). Exactly one pulse per such command.
3. `e_out` valid before done (layer_chan latches at alu_done, :463/:1119),
   not reset between commands.
4. `amax_idx/amax_val/maxp_out` CSR-readable WHILE BUSY (:568-576, no
   busy gate; seq AMAXL reads L_AMAXI): running state must be a valid
   monotonic prefix mid-scan; final by done. `maxp` cleared only at
   dispatch of a probe command. `am_g` global across chained
   invocations; reset only by op-10 cfg_p0[0].
5. op 9 write order: lo word (WR) then hi word (WR2), addresses
   dst+2i, dst+2i+1.
6. All cfg_* latched at the 1-cycle `start` pulse (they may change after).
7. Undecoded ops (11/13/14): preserve today's fall-through behavior.
8. busy is unused by layer_chan; only done matters — keep busy honest
   anyway (LCYC unaffected; it counts layer_chan busy).

vecnorm preservation list:
1. s_valid/s_ready stream handshake — unit must accept 1/cycle AND
   tolerate arbitrary s_valid gaps (feed FSM changes, unit can't assume).
2. m_valid/m_ready with arbitrary backpressure (random m_ready in TB).
3. EPS-NORM (cfg_eps, mode 2) bit-exact incl. rsqrt nominal-binary-point
   trick; cfg_eps==0 leaves modes 0/1/2 bit-identical to shipped.
4. w_we/wbuf preload path unchanged.

## Initiation intervals (single lane ONLY — AMAX32 first-occurrence-wins
forbids lanes; see rung-1b gate doc)

| op | II | port schedule |
|---|---|---|
| 0 DYNQ8 | 2 passes, II=1 each + Q_E search bubble (per-vector, keep iterative) |
| 1 SHIFT32 | 1 | lo via port a, hi via port b (srcb unused) |
| 2,3,4,5,7 | 1 | a (+b for 3/4) |
| 6 SILU32 | 1 | pair via a+b (srcb unused) |
| 8 EMUL32 | 2 | pair via a (2 cyc) + b16 via b; probe compare rides the product stage |
| 9 SHIFT32W | 2 | write-port bound (2 words out/elem) |
| 10 AMAX32 | 1 | pair via a+b; no write |
| 12 DYNQ16 | pass1 II=1 (pair a+b), K_E, pass2 = op-1 pipe II=1 |
| 15 (internal DYNQ8 pass 2) | 1 | |

Reductions (AMAX32 / DYNQ8 maxabs / DYNQ16 mx32 33-bit-abs / op-8 probe
maxp) are loop-carried compare+select recurrences closing in II cycles —
same cone depth as today, single comparator, arrival order = index order.

## Overlap invariant (audit: every generator call site classified; zero
shifted overlaps exist)

Legal classes: disjoint; exact in-place (dst==srca, same stride);
op-8 narrowing (dst base == srca base, read stride 2, write stride 1 —
write cursor i < read cursor 2(i+D) for all i>=0, D>=1); op-9 pair
in-place (2:2). Two-pass ops (0/12) are all disjoint in practice.
REQUIRED: sim-only assertion (`ifndef SYNTHESIS`) in vec_alu — when
w_en, w_addr != a_addr and w_addr != b_addr in the same cycle. The
scratch's read-first collision mode stays unexercised.

## Timing rules (vec_alu is TIED FOR WNS -0.141 today — sig_q PWL cone;
vecnorm at -0.140 — eps_e EPSC shifter; no MCP relief exists for either)

- Register a_q/b_q (and xbuf/wbuf douts) in a capture stage BEFORE any
  arithmetic — breaks the BRAM-DOUT->arith cones at the source. Effective
  read latency addr->operand = 2 cycles; the pipeline absorbs it.
- sg_rom becomes a registered-read ROM; PWL interpolation (S_INT cone)
  split over >=2 registered stages.
- EPSC eps_e 64-bit shifter: pipeline over >=2 registered per-vector
  stages (it has a whole vector of slack).
- New multipliers (2nd vec_alu site so E_MUL/S_MUL paths coexist; 2nd
  vecnorm mul so O_M1/O_M2 overlap) keep the existing 2-stage
  mul_p0/mul_p idiom minimum (DSP MREG+PREG); 3 stages fine.
- Per-command decode (shift fields ps_*/q_*, sh_*, sc_*) stays OUTSIDE
  the element loop — never a 64-bit variable shifter in one stage.
- No new logic into dn_step/attn_core cones. DSP add ~12 total (0.18%).
  SLR1 is at 70% — no large new BRAM.

## layer_chan.sv grant (Agent B ONLY, nothing else in the file)

The VN feed loop F_A/F_W/F_P/F_H (:780-804, hard 4 cyc/elem) may be
rewritten to stream 1 elem/cycle (sa_addr increments every cycle,
vn_svalid pipelined behind the 1-cycle sa_q latency). C_RD drain is
already 1/cycle — leave it. ALL other layer_chan logic frozen.

## Verification gates (in order; evidence -> evidence/rung2/)

1. NEW differential TBs (Agent C): tb/tb_vecalu_diff.sv +
   tb/tb_vecnorm_diff.sv vs legacy copies tb/legacy/{vec_alu_legacy,
   vecnorm_legacy}.sv (already created from HEAD). Same command stream
   to both, independent scratch models; compare per command: full
   scratch image, e_out/k_out/amax_idx/amax_val/maxp_out, k_we pulse
   count, done-after-last-write. Random ops x lens x LEGAL overlap
   classes x extremes (x=-2^31 pairs, maxabs 0xFFFF k_fix boundary,
   len=1, chained AMAX32 with/without fresh-scan, eps on/off, random
   m_ready/s_valid gaps). 4 seeds, $fatal(1) on fail.
2. Existing unit TBs unmodified: make -C tb tb_vec_alu tb_vecnorm.
3. Full regression unmodified: tb_layer_chan (layer_s1..4, token_s1..4,
   chain_s1..4, token24_s1..4), tb_model_v2*, tb_seq_chip. Bit-exact.
4. Verilator -Wall clean; 4 seeds everywhere.
5. build_031 (launch_build.sh, snoke) + reroll campaign; honest WNS.
6. HW gate: safe reprogram; seq_run.py model_v2 + token24 hostgates,
   4 seeds x 2 runs no reprogram, tokens bit-exact; LCYC/PERF census
   before/after; evidence/rung2/RUNG2_GATE.md; ladder updated; commit.

## File ownership (frozen-contract multi-agent)

- Agent A: rtl/vec_alu.sv ONLY.
- Agent B: rtl/vecnorm_unit.sv + the F_* feed region of rtl/layer_chan.sv.
- Agent C: tb/tb_vecalu_diff.sv, tb/tb_vecnorm_diff.sv,
  tb/scripts/gen_ru2_diff_cfg.py (if needed), tb/Makefile targets
  tb_vecalu_diff/tb_vecnorm_diff with obj_dir_tb_vecalu_diff /
  obj_dir_tb_vecnorm_diff. Nothing else.
- Integrator (main session): regression, build, reroll, HW, evidence.
