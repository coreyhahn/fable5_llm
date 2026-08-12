# RUNG 4 — FROZEN SPEC (2026-08-11): row-bubble pipeline + 4-chan head
# (emitter-only) + TOPK-32 + OUT FIFO fixes

Investigation-verified (agent report 2026-08-11; mover-tax inputs
confirmed by mover_bench_build032.json). Projection: 62.83 -> ~31.7
ms/step, 15.9 -> ~31.5 tok/s (2.0x), on-chip sampling at zero step
cost. Baseline evidence: RUNG3_GATE.md. Timing is THE risk: build_032
shipped at 0.000 flat on every clock; the row-bubble fix rewrites the
cones owning ui_clk WNS (+0.001 scales mux, +0.026 15-level rshr).

## Scope: (a)+(b-emitter)+(c)+(d). CUT: vec_alu amax_base + order-
## independent comparator, AMAX-in-mover (rung 5), MVGO guard removal
## (S10 defer), MOVX dual-port, RES write-side row base.

S1 (a) matvec_engine drain FSM -> TAGGED RETIRE PIPELINE (design R2):
   1-deep pending row descriptor pushed at last scale beat; retire
   sequencer walks d_g back-to-back across rows (start >= max(S+1,
   S+7-NG), tree-flush constraint); tags {first,last,row} ride M1/M2/
   M3; p_acc <= (p_acc & {48{~first}}) + 48'(ps_q) (AND-mask folds
   into CARRY8 propagate — zero added levels); emit on last. Residual
   0-1 cyc/row. Accumulator ping-pong stays 2-deep.
S2 SINGLE scale bank (ping-pong FORBIDDEN — the 64:1 scales mux is a
   +0.001 cone); small-NG (<=4) scale-beat stall guard 1-2 cyc.
S3 Split rshr into add-then-shift over TWO stages (latency now free;
   retires the deepest 300 MHz cone). Timing rules: DSP internal regs
   kept; no new logic into d_g->scales or p_acc->ofifo beyond spec.
S4 (b) 4-chan LM head = EMITTER ONLY: _emit_amax_matvec assigns global
   AMAX chunk j to channel j mod 4 (INTERLEAVED, never contiguous
   quarters) using the existing parallel pattern (MVGO-all no-wait ->
   one FENCE -> MOVY-per-chan in ascending chunk order) so am_g
   free-runs bit-exactly. SEQ_NCH=4 artifact = opt-in variant; nch=1
   streams byte-identical (hash-gated). Head weight image gets the
   interleaved chunk->channel placement map; manifest gains a layout
   tag; session --nch refuses mid-session flips (mode flip = full
   re-upload via the residency probe, safe but slow, documented).
S5 (c) TOPK-32: sibling block in layer_chan at base 0x5048 (NO BD/
   create_project edit; layer decode is free 0x48..0xFFF). Fed by ONE
   registered 51-bit bundle exported from vec_alu: {we = t_cp[0] &&
   op_q==10, val = cp_v32, idx = am_g}. 32-entry sorted insertion
   list (parallel compares, recurrence = 1 cmp + 1 mux), II=1, aclk.
   Reset = the AMAX fresh flag (op10 && cfg_p0[0]) ONLY — not START,
   not launch. CSRs: 0x5048 IDENT=0xFAB1704B; 0x504C STATUS
   {overflow[7], complete[6], count[5:0]} (complete = no AMAX32 in
   flight; overflow = a rejected element tied entry[31], sticky);
   0x5050 PTR RW; 0x5054 VAL (no side effect); 0x5058 IDX (PTR++ on
   read). ~1.8K LUT budget; self-contained placement (SLR1 is tight).
S6 (d) seq_unit OUT FIFO: of_cnt DERIVED from of_wp - of_rp (removes
   the race class; the neighbour yf_cnt case({push,pop}) pattern is
   the fallback); depth 16 -> 64; sticky of_ovf exposed in STATUS.
S7 Stream posture: greedy nch=1 replays bit-exact UNCHANGED (the
   whole committed library is the regression); 4-chan and sampling
   are opt-in. Relabel matvec_engine.sv:6-8 stage-2 cycle-identity
   comment (now false).
S8 sw follow-up (small, rides Agent C): ChipTopKSource decodes STATUS
   bits 6/7 and drops per-entry PTR writes (IDX auto-increment).

## File ownership

- Agent A: rtl/matvec_engine.sv ONLY (S1/S2/S3 + comment relabel).
- Agent B: rtl/layer_chan.sv (TOPK sibling + CSRs) + rtl/vec_alu.sv
  (the 51-bit export bundle ONLY) + rtl/seq_unit.sv (S6 ONLY).
- Agent C: ref/seq_format.py (S4 interleave) + sw/chat_seq.py +
  sw/serve.py (nch session support, S8, TOPK source finalization
  vs the S5 CSR map) + head image placement tooling as needed.
- Agent D: tb/tb_matvec.sv gating (+nogap +maxstall=1, NG 1..4
  cases, relabel), NEW tb/tb_topk.sv (numpy-ref randomized: ties,
  rails, <32 and >2^18 elements, protocol incl. auto-increment),
  tb_vec_alu/vecalu_diff TOPK-vs-AMAX equality on chained chunks,
  OUT FIFO directed race + >16-token loop tests, seq_model 4-chan
  gate + tb_seq_chip CHIP_NMV=4, full chip/frozen regressions.
- Integrator: build_033 (census -> 4-6-way reroll -> phys_opt
  playbook; WNS >= 0 to ship), HW gates (seq_run nch=1 = also the
  raw single-channel DDR measurement; --four-chan tokens identical;
  cycle_census + mover_bench after; chat canned; TOPK cross-check vs
  head_cache top-32 SET and ORDER per step; sampled 2-run fixed-seed
  determinism per SAMPLING_SPEC G3), evidence/rung4/, commits.

## Gates (order): unit TBs -> chip gates (model_v2 bit-exact nch=1 +
## nch=4 tokens identical + frozen 16/16 + host ladder) -> build_033
## closure -> HW ladder -> SAMPLING_SPEC G3 items 5 (the sampled chat
## finale) -> RUNG4_GATE.md + ladder + NEXT_SESSION.
