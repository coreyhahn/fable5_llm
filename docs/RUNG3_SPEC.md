# RUNG 3 — FROZEN SPEC (2026-08-10): burst mover path, 32-bit, single-clock

Motivation: evidence/rung3/CENSUS.md + investigation (numbers close to
0.05% vs silicon). A decode step is 62.9% AXI-Lite single-beat traffic;
MOVY alone is 88.1% of every AXIL write in the machine. Target:
150.19 -> 62.8 ms/step, 6.40 -> 15.7 tok/s (2.46x). Scope = option (c):
burst MOVY + MOVX + LDC; polls unchanged; NO done-wire (worth +0.4%,
declined). ZERO new CDC (every endpoint is already aclk 250 MHz), ZERO
ISA/stream/numerics change — every committed artifact replays bit-exact.

## Census corrections (supersede CENSUS.md's assembled table)

Exact per-step (14,742-record loop body): MOVY 398 rec / 648,256 rows ->
1,068,608 scratch words (pairs32 420,352 rows @34.03 cyc = 57.20 ms +
int16 227,904 @17.03 = 15.52 ms); MOVX 187 rec / 277,504 words = 16.77
ms; LDC 3.92; issue/CSRWR+CMD = 0.93 ms (NOT 10-14 — a non-problem);
matvec busy 41.70 ms (poll-derived, 1.6% from shape model); layer 14.12.
MOVY is 1 read + 1-2 writes per row. AXIL write closure exact: 1,213,414.

## Frozen decisions S1-S13

S1  Bus width 32 bit. Every endpoint is 1 word/cycle (scratch 16b port,
    RES BRAM portB 32b READ_LATENCY_B=2, XWIN FIFO 1 w/cyc, dequant
    II=1). The win is BURSTING (kill the ~15-17 cyc/op AXIL round trip),
    not width. No memory restructuring of any kind.
S2  New BD IP: burst_smc = smartconnect:1.0, NUM_SI=1 NUM_MI=5
    NUM_CLKS=1, clk = xdma_0/axi_aclk (NO clock conversion, NO CDC).
    Plus 5 axi_register_slice on the MIs (house convention,
    create_project.tcl:249-263 pattern). MI order mvchan_0..3, layer_0.
S3  New master port seq_0/m_axib (AXI4, 32b data / 32b addr,
    READ_WRITE), owned by seq_movers. The existing 128b READ_ONLY m_axi
    (address space 100% full) is untouched.
S4  Private address space, 64 KiB stride: mvchan_c at (c+1)<<16,
    layer_0 at 5<<16.
    SUPERSEDED 2026-08-13 by track R task R-b: the layer scratchpad is
    32768 words, so layer_0's window is 128 KiB and MOVED to 6<<16 (an AXI
    segment must be range-aligned; 5<<16 is not).  5<<16 is now a decode
    hole.  This file is a frozen historical spec — docs/SEQ_ISA.md B12.3
    is the current truth.
S5  mvchan burst window: READ 0x0000-0x3FFF = RES row r at byte 4r,
    r=0..4095 (addrb muxed with res_ptr; shim honours READ_LATENCY_B=2;
    RES_GAP retired on this path). WRITE 0x4000-0x4FFF = XWIN word w at
    byte 4w, pushing the EXISTING unmodified xpm_fifo_async at <=1
    word/cycle. All AXIL regs (XWIN/XPTR/RES_PTR/RES_DATA/STATUS) kept
    bit-identical — the host-driven ladder must keep passing.
S6  layer burst window: scratch word w at byte 4w, w=0..16383. READ
    consumes sa_q EXACTLY as the SWIN read does and registers it
    immediately (R3 hard rule: ZERO added logic on sa_q/sb_q). WRITE =
    a 4th leg on the sw_en/sw_addr/sw_data mux (3:1 -> 4:1, one
    LUT6/bit, zero added levels; source the leg from a (*keep*)
    register adjacent to the BRAM — R4). Both gated on !busy; access
    while busy returns SLVERR (never silent drop — R8).
S7  AXI4 INCR bursts <=256 beats, never crossing 4 KiB (master splits).
S8  seq_movers FSM shape + 4-stage II=1 dequant UNCHANGED; only the
    request/response plumbing moves off AXIL. yf elastic 16 -> 32;
    outstanding-count throttle replaced by plain RREADY backpressure.
    MOVX packer and LDC reuse the same burst master.
S9  MVGO polling + MVGO_GUARD unchanged (no done-wire in v1 — CDC
    FLAG-2 declined). Poll traffic no longer contends once movers
    leave AXIL.
S10 MOVX uses the single sa read port only (dual-port opt worth 0.55 ms
    — out of scope).
S11 NO ISA change, NO stream regeneration, NO numerics change. ISA note
    A6 (MOVY/MVGO 1:1) stays. Every committed .seq/.txt replays
    bit-exact — the full committed regression IS the functional gate.
S12 Overlap-proofing (v2 door): burst RES read start row is a full
    12-bit field carried in the AXI address, never hardwired 0; slave
    window covers all 4096 rows. RES_PTR/RES_DATA intact.
S13 Ship gate: WNS >= +0.000 after a 4-6 way reroll spread (+ the
    unused post-route phys_opt_design lever if needed).

## Hard timing rules (build_031 closed at +0.006; 4/5 directives failed)

- R2: layer shim is a SHALLOW wrapper handing one registered
  (addr,data,we) bundle to the scratch mux; no shim state inside the
  dense core; nothing added to u_dn/u_attn/u_alu/u_vn cones.
- R3: NOTHING on sa_q/sb_q outputs (top-10 path #7 is smem_a->at_qdata
  at LL=0, +0.027).
- R6: mvchan shim is 100% aclk; only the addrb mux and xf_din/xf_push
  mux are touched; ui_clk logic untouched.
- New-logic budget ~5.4-7.4K LUT / ~9-12K FF, 0 BRAM/URAM/DSP.

## File ownership (frozen-contract multi-agent)

- Agent A: rtl/seq_movers.sv, rtl/seq_unit.sv, seq_unit_ipi wrapper,
  synth/scripts/create_project.tcl (S2/S3/S4 BD edits ONLY; watch the
  M0${i} string-format trap at :237, must{} wrapper style).
- Agent B: rtl/matvec_chan.sv + its ipi wrapper (S5 shim).
- Agent C: rtl/layer_chan.sv + its ipi wrapper (S6 shim; R2/R3/R4).
- Agent D: tb/seq_burst_fabric.sv (new AXI4 1x5 latency model
  mirroring seq_fabric_model.sv), TB stub updates, tb_seq_unit +
  tb_seq_chip integration; own obj_dirs; NEGEDGE discipline; $fatal.
- Integrator: sim ladder, build_032 + reroll campaign, HW gate +
  census re-run, evidence/rung3/, commits.

## Interface contracts between agents (frozen so A-D run in parallel)

- Module port names: mvchan adds s_axib_* (AXI4 slave, 32b, aclk);
  layer_chan adds s_axib_*; seq_unit adds m_axib_* wired through to
  seq_movers. Standard full-AXI4 signal set, ID width 1, no
  USER/QOS/REGION/LOCK/CACHE semantics (tie constants).
- Error: SLVERR on layer window while busy; DECERR never (SmartConnect
  handles holes); mover raising E_AXI (0x12) on any RRESP/BRESP != OK.
- Address math: exactly S4/S5/S6; agents assert window bounds in
  `ifndef SYNTHESIS checks.

## Verification gates (in order)

1. Unit: tb_seq_unit with seq_burst_fabric at LAT 0/4/8, 4 seeds +
   error paths (SLVERR-while-busy, window-bounds).
2. THE gate: tb_seq_chip model_v2_s1.e — all 60,495 records, 6 tokens,
   7,168 scratch words bit-exact on real RTL (all four agents' code
   together), plus tok2 + the chat_i1 multi-launch gate re-run.
3. Committed-script regression UNMODIFIED (host-driven paths must
   still pass: layer/token/chain/token24/model_v2 via AXIL untouched).
4. -Wall + slang clean; 4 seeds everywhere.
5. build_032 (launch_build.sh) + reroll spread 4-6 directives; census
   the winner; WNS >= 0 to ship (S13).
6. HW: safe reprogram; seq_run + chat gates re-run; cycle_census +
   mover_bench AFTER numbers vs the 62.8 ms projection; evidence ->
   evidence/rung3/RUNG3_GATE.md.
