# HISTORY — NEXT_SESSION archive (newest first)

Session entries moved out of NEXT_SESSION.md on 2026-08-12, so the
cold-resume file stays short. Everything below is VERBATIM as it was
written at the time: this is a LOG, not maintained truth. Board state,
bitstream names, blockers and "NEXT options" in these entries are almost
all superseded — for current state read NEXT_SESSION.md, for the as-built
ISA/CSR truth read docs/SEQ_ISA.md (v1.6), for what each rung delivered
read evidence/<rung>/*_GATE.md, and for the throughput arc read
docs/SPEEDUP_LADDER.md.

The two newest entries (2026-08-12 rung 4, 2026-08-11 chat template)
stayed in NEXT_SESSION.md and are NOT duplicated here.

---

## ✅ 2026-08-11: RUNG 3 PASSED — 15.56 tok/s (2.43x), timing 0.000 via first phys_opt
- Burst mover path (32b single-clock AXI4, zero CDC, zero ISA change):
  seq_run model_v2 385.72 ms /6 tok (was 937.38), tokens bit-exact x2,
  AXIL writes -98.6%. Board holds build_032 postopt bitstream
  (out_build_032_rr_SSI_HighUtilSLRs/postopt/bd_wrapper_postopt.bit,
  VERSION 0x0C991953 = EXPECTED in seq_run.py + infer.py). Closure:
  first roll -0.354 -> spread best -0.091 -> phys_opt pass 1 = 0.000
  flat, 0 failing of 1.167M. NEW PLAYBOOK STEP: census -> reroll
  spread -> post-route phys_opt_design (postopt_032.tcl pattern).
- Chat CLI + serve.py API run 2.4x faster with zero software change
  (chat canned gate golden on build_032; ~63 ms/step -> ~15 tok/s
  streaming). evidence/rung3/RUNG3_GATE.md.
- NEXT options (pick with user):
  * matvec row-bubble fix + RTL argmax-combine/4-chan -> ~25-29 tok/s
    (DDR floor 7.1 ms/token; matvec is 65% of the step now).
  * Qwen3.5-0.8B-INSTRUCT checkpoint swap (zero RTL): same arch as the
    Base model on the board; re-quantize via load_qwen35 + fidelity
    harness + chat template -> real assistant behavior at 15 tok/s.
  * layer compute (22%) after matvec.
  * follow-ons: flock retrofit into infer/seq_run/tok_meter; $urandom
    --seed sweep audit (B's finding); serve.py session persistence.

## ✅ 2026-08-10: CHAT-SEQ SHIPPED — 6.66 tok/s streamed chat + API on silicon
- ALL gates green (evidence/chat/CHAT_SEQ_GATE.md): smoke, B1 x2 canned
  golden, B2 8/8 fresh prompts == reference, B3a 18/18 lockstep-verified
  2-turn continuity, B3b overflow auto-reset, C1 API (SSE golden tokens,
  2-client FIFO, warm restart 2.67 s). Zero RTL — board stays 4d71adcc.
- Measured: full step 150.2 ms, prefill-lite 100.3 ms (-33%), preamble
  36.1 ms, ~570 MMIO reads/turn (was ~3M/token), device_frac 0.988.
- snoke: OS disk failed 2026-08-10, user fixed hardware; rebuild
  checklist at docs/SNOKE_REBUILD.md; board re-programmed via safe
  flow, seq_run regression 937.381 ms (4 us of pre-incident).
- serve.py left RUNNING on snoke:8137 (--prefill full, holds
  sw/.seq.lock). NEVER run infer.py/seq_run/tok_meter while it's up
  (they don't take the lock). kill <pid from /v1/health> to free it.
- NEXT options: census the ~76 ms/token non-matvec remainder -> pick
  rung 3 vs argmax-combine; flock retrofit; weight-stationary batched
  prefill; QSFP28 2-board (charter stretch).

## ▶ 2026-08-10 (resolved): CHAT-SEQ HW gates BLOCKED — snoke sshd wedged (again)
- Chat-seq rung is CODE-COMPLETE, all sim gates green, committed:
  ref/seq_chat.py (2eabe5e, gates A1/A2/A3), sw/chat_seq.py (2eabe5e,
  selftest 142/142 + model-only bit-exact), sw/serve.py + chat_client
  (1b47605, mock 24/24), tb_seq_chip multi-launch gate I1 PASS on real
  RTL (68dd689: START preserves banks; pos-86 ldc RoPE address witness).
  Spec: docs/CHAT_SEQ_SPEC.md incl. phase-1 amendments (ldc default).
- REMAINING (task: HW gates, then evidence/chat/CHAT_SEQ_GATE.md):
  1. smoke: sw/.venv/bin/python chat_seq.py --smoke --out ../evidence/chat/chat_seq_smoke.json
  2. B1: --canned x2 (expect [561,314,279,369,279,6511])
  3. B2: 4 fresh prompts x2 runs vs --model-only predictions
  4. B3: 2-turn continuity + forced --max-ctx overflow reset
  5. C1: serve.py --prefill full + chat_client canned; restart = warm
     residency skip; 2-client FIFO
- BLOCKER: snoke pings but sshd kex-resets (same signature as 08-08,
  NVIDIA-wedge incident; correlated with the user's infer.py session
  ending ~08-10 00:xx). Board held build_031 (4d71adcc, CALIB 0xF)
  before the wedge. If snoke rebooted: xdma needs pcie_helper.sh load
  (rebuild xdma.ko first if kernel bumped); if power was cut, JTAG
  reprogram build_031_rr_AltSpreadLogic_medium via the safe flow.

## ✅ 2026-08-09: RUNG 2 PASSED — 6.40 tok/s, first closed-timing bitstream since 023
- vec_alu + vecnorm are II=1 pipelines (single lane; AMAX32 ordering
  forbids lanes); layer_chan VN feed 4->1 cyc/elem. NO ISA/script/
  numerics change — everything committed replays bit-exact.
- Board holds build_031_rr_AltSpreadLogic_medium, netlist 4d71adcc
  (= VERSION CSR; seq_run.py EXPECTED_SEQ_VERSION updated), **WNS +0.006
  / WHS +0.010, 0 failing endpoints**. DSP +2, LUT -422 vs build_030.
- Measured (seq_run model_v2_s1.e x2, no reprogram): 937.38 ms device
  /6 tok = 156.23 ms/token = **6.40 tok/s** (rung-1: 1220.03 ms, 4.91).
  1.302x, repeatable to 188 cyc. Tokens bit-exact; 7,188 state checks.
  Host ladder same bitstream: frozen 8/8, chain 8/8, token24 8/8,
  model_v2 2/2, 0 errors. evidence/rung2/RUNG2_GATE.md.
- Workflow that delivered it (reuse): investigation agent -> frozen
  docs/RUNG2_SPEC.md -> 3 Opus agents (A vec_alu / B vecnorm+feed /
  C differential TBs vs tb/legacy/ frozen copies) -> integrate ->
  sim ladder -> build+reroll -> HW. Diff-TB pattern (legacy-vs-new,
  sabotage self-tests) is the template for future RTL rungs.
- USER RULE (now in CLAUDE.md): heavy Verilator sims run ON SNOKE
  (seeds in parallel); obj_dirs are NFS-shared — one machine at a time.
- NEXT (open, pick with user):
  * FRESH DEVICE CENSUS first: 156.2 ms/token = matvec+movers ~73 ms
    (47%) + element ~7 + OTHER ~76 (non-ALU layer cmds, seq issue,
    movers). The ~76 ms is unattributed — measure before choosing.
  * RUNG 3 (RTL): matvec row-bubble (~8.9 cyc/row) -> t_matvec ~2x.
  * ARGMAX-COMBINE (RTL): sticky index-base + 4-way combine makes
    rung-1b's 4-chan pay off on the LM head.
  * infer.py: point CLI at build_031 (it still speaks host-driven MMIO;
    a --seq mode would give the user 6.4 tok/s chat).
  * QSFP28 2-board (charter stretch, untouched).

## 2026-08-09: RUNG 1b done — 4-chan sequencer FUNCTIONAL, but 15% SLOWER (bacaac3)
- 4-chan weight-split works on silicon (build_030, no rebuild): sequencer
  drives all 4 matvec_chans concurrently, tokens bit-exact, gated 3 ways
  (seq_model, tb_seq_chip CHIP_NMV=4, HW). nch=1 default byte-identical.
- BUT measured 15% SLOWER (1404 vs 1220 ms device). Root cause: matvec is
  only 36% of device time; the dominant 248k LM head can't parallelize
  under on-chip sequential AMAX32 argmax; 4x MOVX + 13% record overhead
  dominate. evidence/rung1/STAGE5_RUNG1B_GATE.md. 4-chan retained,
  default off.
- REDIRECT: the real decode lever is RUNG 2 = parallelize layer_chan
  vec_alu + vecnorm element ops (they are ~64% of device time; the
  earlier tok_meter analysis put vec_alu at 73% / vecnorm 17% of
  layer_chan busy). That is an RTL rung (build cycle). Also possible:
  RTL "sticky argmax index-base + 4-way combine" to make the LM head
  parallelize -> would finally let rung 1b's 4-chan pay off.
- Board holds build_030 (rung-1 sequencer, VERSION 9e1e0bae, xdma loaded).

## ✅ 2026-08-09: STAGE 5 RUNG 1 PASSED — sequencer runs its own loop (9a53ba5)
- On-chip sequencer executes the full 24-layer real-Qwen3.5 decode loop
  on silicon: seq_run.py --prefix model_v2_s1.e, all 60,495 records,
  tokens bit-identical to golden, 7188 state checks match, repeatable.
  Board: build_030_rr_AltSpreadLogic_medium (9e1e0bae, WNS -0.141,
  EXPECTED_SEQ_VERSION already set). Host-driven ladder 26/26 on same
  bitstream. evidence/rung1/STAGE5_RUNG1_GATE.md.
- Speedup: 1.222s wall vs 30.8s host-driven (25x); device 1220ms ~= wall
  (MMIO overhead eliminated) = 4.91 tok/s (1-chan) vs rung-0 0.195.
- Reboot recovery now self-service: pcie_helper.sh gained a `load`
  subcommand (insmod xdma, NOPASSWD). If a reboot bumps the kernel,
  rebuild xdma.ko first: make in references/dma_ip_drivers/.../xdma.
- NEXT (open, pick with user):
  * RUNG 1b (no RTL): 4-chan weight-split stream option in the generator
    -> ~12 tok/s (tok_meter proved 4.03x matvec scaling). Small.
  * RUNG 2 (RTL): parallelize vec_alu/vecnorm element ops -> toward the
    140 tok/s bandwidth ceiling (see docs/SPEEDUP_LADDER.md).
  * QSFP28 2-board (charter stretch, untouched).

## ▶ 2026-08-09 ~04:30: RUNG-1 BITSTREAM READY — HW gate blocked on XDMA load
- Infra incident RESOLVED (snoke rebooted; cause was an NVIDIA driver
  update not rebooted into — see the 08-08 section). License fixed.
- SEQUENCER BUILT + TIMING-CLOSED. build_030 = pipelined netlist
  (9e1e0bae): the 3 deep combinational paths from build_029 census
  (MOVY dequant, EPS-NORM scale, SEQ fetch) pipelined by retiming
  (commit 9e1e0ba, all sim gates green). Raw -0.188 -> directive spread
  best -0.141 (out_build_030_rr_AltSpreadLogic_medium). ACCEPTED: ==
  build_026's shipped -0.142, same axi_aclk domain, bit-exact at 250MHz
  precedent. Census: diffuse layer_0 congestion, only 3/999 in seq_0.
  THIS IS THE RUNG-1 BITSTREAM:
  synth/out_build_030_rr_AltSpreadLogic_medium/proj/stage1.runs/impl_1/bd_wrapper.bit
  VERSION CSR = 0x9E1E0BAE (== EXPECTED_SEQ_VERSION in sw/seq_run.py).
- BLOCKED ON USER: (1) board not enumerating (power-cycle wiped the
  volatile bitstream — needs JTAG reprogram); (2) XDMA driver NOT loaded
  after reboot, no /dev/xdma0_*, no systemd unit, and Claude cannot
  sudo modprobe (only pcie_helper.sh is NOPASSWD). USER must load the
  xdma module the usual way (from dma_ip_drivers build dir /
  insmod xdma.ko). Then Claude does the rest autonomously:
    a. safe reprogram: sudo -n pcie_helper.sh remove (if enumerated) ->
       program_fpga.sh <the .bit above> -> sudo -n pcie_helper.sh rescan
    b. CSR sanity: MAGIC 0xFAB1E001, VERSION 0x9E1E0BAE, CALIB 0xF,
       layer IDENT 0xFAB1E5A0, matvec IDENTs, seq IDENT 0xFAB1E5E0
    c. HW ladder DUAL-DRIVEN: host-driven frozen regression
       (layer_test.py layer_s1-4/token_s1-4) + chain/token24/model_v2
       THEN sw/seq_run.py --prefix .../model_v2_s1.e (chip runs its own
       60,495-record decode loop) — the rung-1 payoff
    d. tok_meter re-measure vs ~12 tok/s rung-1 target; gate doc + commit
- HEAD 6e525bf. All rung-1 code/sim committed. Sim proved the whole
  sequencer bit-exact incl. full model_v2 (tb_seq_chip). This is the
  first hardware run of the chip executing its own decode loop.

## ⚠ 2026-08-08 ~16:45: LAB INFRA INCIDENT — build_029 blocked, not our code
- RUNG 1 (on-chip sequencer) is CODE-COMPLETE and committed through
  606c452: ref numerics, seq binary format+executor, all RTL (vec_alu
  DYNQ16/op-8 probe/EPS-NORM/XRF, seq_unit+seq_movers), full-chip sim
  (tb_seq_chip 10/10 incl. FULL model_v2_s1 = 181.3M cyc/120.9ms per
  step, matching the 10.1 tok/s projection), host runner sw/seq_run.py
  (version-gated to build_029). ISA frozen at v1.5. NO RTL BUG found in
  any wave. See docs/SEQ_ISA.md, docs/SEQUENCER_PLAN.md, evidence/rung1/.
- BLOCKER: build_029 FAILED 11:03 on a VIVADO LICENSE error (Common
  17-345, no xcvu9p Synthesis license) — fired before synth touched our
  RTL; 66 GB free, so not resources. Then snoke sshd went to
  kex-reset (host pings, TCP 22 opens, resets before banner) and iDRAC
  became unreachable.
- SCOPE (pinged 16:45 from darthplagueis): snoke UP-but-degraded,
  darthvader DOWN, fn2187 DOWN, kyloren UP, r2d2 UP (NFS server fine
  — repo safe). Multi-machine => physical event (power/PDU/thermal).
  HYPOTHESIS: Vivado license server may be darthvader or fn2187 (both
  dark) — would explain the 11:03 license failure directly.
- RESUME once the rack is healthy: (1) confirm snoke sshd + license
  server back; (2) rm -rf synth/out_build_029 (license-failed, no
  artifacts); (3) ssh snoke, nohup ./launch_build.sh build_029 detached;
  (4) watch BUILD_OK + WNS (029 is the largest netlist — +AXI4 read
  master +2 AXIL masters — allow ~4-5h); (5) timing spread if needed;
  (6) safe reprogram; (7) HW ladder DUAL-DRIVEN: host-driven frozen
  regression THEN sw/seq_run.py --prefix model_v2_s1.e (chip runs its
  own 60,495-record decode loop); (8) tok_meter re-measure vs the
  ~12 tok/s rung-1 target; gate doc + commit. EXPECTED_SEQ_VERSION in
  seq_run.py is already 0x123518A6 (build_029 netlist).

## ✅ 2026-08-08: sw/infer.py — interactive live inference (5806c04)
- "Chat with the FPGA": live 24-layer orchestration, chip-computed
  argmax fed back, 9.3 s/tok (21.3 with --verify lockstep). Acceptance:
  reproduced model_v2_s1's recorded tokens exactly on silicon; 39.97M
  readback words bit-exact across 38 forward steps. make chat /
  chat_verify / infer_gate in sw/. Strongest motivation yet for the
  Phase-1B on-chip sequencer (would take ~9 s/tok toward the measured
  81.7 ms/tok device time).

## ✅ 2026-08-06: g64 GATE PASSED (165565a) — dual-mode engine on silicon
- Board holds build_028_rr_SSI_HighUtilSLRs (netlist 67a943bd): WNS
  -0.106 / WHS +0.007, best banked-netlist timing to date. HW 34/34
  runs 0 errors incl. the first mode-1 (g64) real-model runs.
- Default stays g128 (44-sample: 30/44 vs 27/44); g64 per-script via
  --w4-group=64 (better free-run text 3/4 prompts, rank-max 75 vs 845).
- Timing recipe that worked: census -> targeted read-pipeline stage
  (iter5 CV_W3) -> SSI_HighUtilSLRs. Invalid directives (Vivado 2024.2
  placer): SpreadLogic_high, SSI_ExtraTimingOpt.
- Fidelity ladder to date: 0/24 -> 15/24 (dnsn+attnbf+mse) -> 16/24
  (m_q15=65535). Next fidelity levers: g64+datapath interplay,
  Phase-1B sequencer RTL (DYNQ16 + eps vecnorm). Throughput levers:
  ALU/VN parallelization (13.97 tok/s RTL ceiling -> 140 bandwidth
  ceiling). QSFP28 2-board still untouched.

## ✅ 2026-07-27: FIDELITY FIX SHIPPED (07e2d89) — fixed point at W4 ceiling
- 0/24 -> 15/24 top-1 vs bf16 (= the exact W4-mse quantization ceiling);
  free-run text is real language. ZERO RTL — generator/reference only;
  bitstream unchanged (07ffc7b9). Sim 20/20, HW 32/32, 0 errors.
  Record: evidence/stage5/STAGE5_FIDELITY_GATE.md, scope+phase log in
  docs/FIDELITY_REDESIGN.md.
- Cheap follow-ons logged, not done: m_q15 ceiling 65535 (zero-RTL,
  ~3% of heads under-scaled 2x); W4 g=64/32 sweep said 18-20/24 possible
  but changes the DDR beat format (matvec_engine assumes G=128/beat).
- Still open from stage-5 wrap: throughput RTL (ALU/VN parallelization
  toward 140 tok/s), Phase-1B sequencer RTL (DYNQ16 + eps vecnorm),
  QSFP28 2-board stretch.

## ✅ 2026-07-26: STAGE 5 increments ①②③④ ALL GATED ON HARDWARE
- ①+② (53a3eec): 24-layer banked engine, chain + token24 + regression,
  24/24 runs bit-exact on build_026_rr_AltSpreadLogic_medium (07ffc7b9),
  honest WNS -0.142. ③ (24e6192): REAL Qwen3.5-0.8B, full 248,320
  vocab, 4 seeds x 2 runs x 5.79M checks, 0 errors; numerics ledger in
  STAGE5_INC3_GATE.md (S_F sat, dt/A clamp, degenerate text = fidelity
  follow-on). ④ (16c0649): measured tok/s = 12.23 device (4-chan) /
  0.19 wall vs recomputed 140.6 ceiling; bottleneck is layer_chan
  serial ALU/VN (13.97 tok/s RTL ceiling), NOT bandwidth (TOKS.md).
- Board holds build_026_rr_ASM (07ffc7b9). Spread #2 rerolls
  (SSI_*/AltSpread_high/low) may still be finishing in
  synth/out_build_026_rr_*/ — a WNS>=0 roll can swap in (re-gate after).
- Charter stage-5 remaining stretch: 2-board QSFP28 tensor parallelism
  (untouched). Highest-leverage next work, pick with user:
  (a) throughput: parallelize vec_alu/vecnorm element ops (73%/17% of
      layer busy) toward the 140 tok/s bandwidth ceiling;
  (b) fidelity: embedding scale-up via RMSNorm invariance + S_F Q3.12
      (RTL) to fix degenerate text;
  (c) on-chip command sequencer (67x wall, needed for real serving);
  (d) QSFP28 2-board.

## ▶ 2026-07-25: STAGE 5 increment ① — SIM GATES PASSED, build_024 pending
- Plan: ~/.claude/plans/plan-out-the-next-swift-tiger.md (approved; 4 increments).
- d91ef34 committed: layer-banked RTL (LAYER CSR 0x30 {kv_slot[10:8],dn_slot[4:0]},
  LCYC 0x34, dn 9x4096 URAM banks, kv 3x4096, conv 18x6144, tcnt_bank[6][2]),
  gen_chain_script.py, L record in TB+host, chain make targets.
- SIM GATES GREEN: backward compat 8/8 committed stage-3/4 scripts bit-exact
  on banked RTL; 8-layer chain 4 seeds x 3390 cmds / 315,642 checks
  (evidence/stage5/sim_backcompat.log, sim_chain.log).
- build_024 (netlist d91ef34) IS RUNNING on snoke (verified 2026-07-25:
  the ssh-client kill did NOT HUP it — it orphaned and kept going; synth
  done, impl_1 in progress). Do NOT relaunch. Results land in
  synth/out_build_024/ (build.log BUILD_OK marker).
- After BUILD_OK: check WNS (grep "Design Timing Summary" -A12 in
  out_build_024/reports/timing_summary.rpt). Reroll via launch_reroll.sh
  build_024 Explore ExtraTimingOpt ... if negative. Watch: 348 URAM
  (SLR crossing), 9:1x2048b dn read mux, ~540 BRAM.
- Then HW gate (task #2): safe reprogram (autonomous, sudo -n pcie_helper),
  CSR check VERSION=d91ef34?, chain_s1..4 x2 runs via sw/layer_test.py,
  stage-3 layer + stage-4 token scripts x1 as regression, gate doc + commit.
  Chain scripts/bins are gitignored but live in tb/scripts/ (regen:
  ref/.venv/bin/python ref/gen_chain_script.py out seed 3 8 — ref/.venv
  python only works on darthplagueis; sha256 in evidence/stage5/).
- Then increments ② (24-layer token, packed DDR map), ③ (real Qwen3.5 +
  full vocab, audit_ranges first), ④ (tok/s via device counters — user
  chose NO on-chip sequencer). Board still holds build_023_rr_Explore.

## ✅ 2026-07-22: STAGE 4 GATE PASSED (sim + hardware, timing MET)
- Full token path autoregressive on-chip, bit-exact, 4 seeds x 2 runs,
  0 errors: evidence/stage4/STAGE4_GATE.md + token_hw_build023.json.
  Stage-3 layer scripts re-ran clean on the same bitstream
  (layer_hw_build023_regression.json).
- Board holds build_023_rr_Explore (netlist b1ef323a, VERSION CSR
  0xb1ef323a): TIMING FULLY MET — axi_aclk WNS +0.003 (Fmax 250.2 MHz),
  0 failing setup endpoints in the whole design, WHS +0.010, all ui_clk
  met. First outright timing closure of the project.
- Reroll flow that got there: synth/scripts/launch_reroll.sh <build>
  <directive>... (project copy per directive, synth reused, ~3h).
  On this netlist: Explore +0.003, ExtraTimingOpt +0.003,
  ExtraNetDelay_low -0.142, AltSpreadLogic_medium -0.339.
- NEW: pcie_helper.sh is NOPASSWD sudo on snoke (verified sudo -n -l).
  Claude can run the full safe reprogram autonomously. Exact form:
  ssh snoke 'sudo -n /home/cah/r2d2/code/fpga/fable5_llm/sw/pcie_helper.sh remove|rescan'
  (allow rules for both are in .claude/settings.local.json).
- Log-grep gotcha: anchor with "^TIMING:" / "^FATAL" — Vivado echoes
  script text (including the FATAL branch) into logs with "# " prefixes.

## Next: Stage 5 (charter stretch goals — pick with the user)
Charter list: (a) multiple layers chained, (b) real quantized model
weights, (c) measured tok/s vs prediction, (d) 2-board tensor
parallelism over QSFP28. Natural first step: (a) chain N layers by
extending the script generator (scratch/URAM budget check first:
KV cache + DN state per layer), then (c) measure tok/s on the chained
pipeline vs a paper model. Full-vocab LM head (248,320 rows = 61 chunks
of 4096) needs no RTL change — script generation + 61 weight images.
