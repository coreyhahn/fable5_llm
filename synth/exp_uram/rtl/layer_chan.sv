// ============================================================
// EXPERIMENT COPY — NOT MIGRATION RTL.  Track P (URAM placement
// experiment), qwen-next de-risking, docs/QWEN35_NEXT_FEASIBILITY.md
// section 6 item 3 / section 8 D3.  Source of truth stays rtl/layer_chan.sv;
// main/rtl is UNTOUCHED by this directory.  These files exist only to
// answer "does the 4B/9B-widened layer_chan synthesize to 928 URAM,
// and does it PLACE on the VU9P".  No testbench campaign was run
// against them and they are NOT functionally verified.
// Copied from rtl/layer_chan.sv @ git aa9c1efa
// ============================================================
// layer_chan: stage-3 layer-orchestration engine. A 32Kx16 scratchpad +
// command dispatcher + the verified units (vecnorm/rope/conv4/dn_step/
// attn_core/gate_unit/vec_alu) + layer state memories (DeltaNet state,
// KV cache, conv state/weights). The host is scheduler/DMA only: it
// loads/stores scratch through a CSR window and issues commands; ALL
// arithmetic happens on-chip (semantics = ref/layer_fixed.py).
//
// Single clock domain (aclk). Host protocol: read STATUS cmd_cnt, write
// ARG0..2 + CMD, poll STATUS until cmd_cnt increments. SWIN access only
// while idle.
//
// Register map (byte addr, 32-bit):
//   0x00 CMD     W  {opcode[3:0]} - dispatch (idle only)
//   0x04 STATUS  R  {cmd_cnt[15:0], 14'b0, err_op, busy}
//   0x08 ARG0    RW   0x0C ARG1   RW   0x10 ARG2   RW
//   0x14 SPTR    RW scratch word pointer [14:0]
//   0x18 SWIN    W  scratch[SPTR]=d[15:0]; SPTR++
//                R  scratch[SPTR]; SPTR++   (idle only)
//   0x1C EOUT    R  last ALU DYNQ8 exponent [3:0]
//   0x20 TCNT    RW {6'b0, T1[9:0], 6'b0, T0[9:0]} KV append counters
//   0x24 IDENT   R  0xFAB1E5A0
//   0x28 AMAXI   R  ALU AMAX32 running argmax index [17:0]
//   0x2C AMAXV   R  ALU AMAX32 running max value (int32)
//   0x30 LAYER   RW {21'b0, kv_slot[10:8], 3'b0, dn_slot[4:0]} bank select
//   0x34 LCYC    R  cycles elapsed while busy==1; ANY write clears it
//   0x38 XRFI    RW {29'b0, idx[2:0]}  XRF index for the XRFD window
//   0x3C XRFD    RW XRF[XRFI]: read {14'b0, raw18}, write raw18 = d[17:0]
//   0x40 MAXPL   R  vec_alu op-8 probe max|prod| [31:0]
//   0x44 MAXPH   R  {16'b0, max|prod|[47:32]}
//
// ---- rung 4 S5: the TOPK-32 sibling block (docs/RUNG4_SPEC.md) --------
//   0x48 TK_IDENT  R  0xFAB1704B
//   0x4C TK_STATUS R  {24'b0, overflow[7], complete[6], count[5:0]}
//   0x50 TK_PTR    RW {27'b0, ptr[4:0]}   entry cursor
//   0x54 TK_VAL    R  int32 value of entry[ptr]   (NO side effect)
//   0x58 TK_IDX    R  {14'b0, idx[17:0]} of entry[ptr];  ptr++ ON READ
// count = valid entries (0..32); complete = no AMAX32 command in flight;
// overflow = sticky, a rejected element TIED entry[31] (the top-32 SET is
// then not unique by value alone).  The list, ptr, count and overflow are
// reset by the AMAX32 "fresh" flag ONLY (ALU aop 10 with p0[0]=1) — never
// by a command boundary, so a chunked vocabulary scan accumulates.
//
// XRF (docs/SEQ_ISA.md): 8 x 18b, reset 0.  Entries are SIGNED except
// XRF[3] (token id), which is UNSIGNED — the XRFD window is raw/
// zero-extended so both readings are unambiguous.  Map:
//   [0] e_x    <- vec_alu DYNQ8 e_out at command retire (also EOUT CSR)
//   [1] k_dn   <- vec_alu DYNQ16 k     when cfg_p0[0]==0
//   [2] k_attn <- vec_alu DYNQ16 k     when cfg_p0[0]==1,
//                 and vec_alu op-8 PROBE k_a (always [2])
//   [3] token id (host / future AMAXL), [4..7] spare
// Interface exposed for the sequencer block (agent D), all internal to
// this module — no new top-level ports:
//   read  : xrf[i]  (combinational, 8 x signed[17:0])
//   write : xrf_we / xrf_widx[2:0] / xrf_wdat[17:0]  — one-cycle strobe,
//           applied LAST in the XRF always_ff so it wins over the engine
//           latch paths in the same cycle.  Today the only driver is the
//           XRFD CSR window; agent D ORs the SEQ (XOP / AMAXL) writer in.
//
// Layer banking: one engine serves 24 transformer layers (18 DeltaNet
// dn slots 0..17, 6 GQA kv slots 0..5), selected by LAYER (latched at
// command dispatch). Per-command state memories are banked on the
// latched slot:
//   DNST/DNZ/CONV/CONVW use dn_slot;  KVAP/ATTN/TCNT use kv_slot.
// TCNT host read/write use the LIVE LAYER.kv_slot (set LAYER before TCNT).
// dn_slot 18..31 and kv_slot 6..7 are host errors (no RTL guard).
// LAYER=0 reduces every banked address to the original single-bank map.
//
// ---- 15-bit scratch addressing (R-b, SEQ_ISA v1.7) -------------------
// The scratchpad is 32K words, so every scratch address field below is 15
// bits.  No field had room to grow in place, so bit 14 of each rides in a
// bit of the SAME arg word that evidence/qwen2b/rb/spare_bits_report.txt
// proves is NEVER set by any pre-R-b stream — which is exactly what makes
// every frozen 0.8B script replay bit-identically (all its addresses are
// < 16384, so all of these bits are 0):
//
//   ARG1 on EVERY command carries the pair {hi[27:14], lo[13:0]} with
//        lo[14] at bit 28 and hi[14] at bit 29.
//   ARG2 on GATE and DNST uses that SAME pair layout (bits 28/29).
//   ARG2 on ALU is {dst[30:17], p0[16:0]} — bit 31 is its only spare, so
//        ALU dst[14] lives there.  (ARG0 on ALU had spare room above the
//        count, which is what R-c's 13th length bit later took.)
//   ARG0 on GATE is just dst, which widens in place to arg0[14:0].
//   ARG0 on DNST is FULL, so its two scalar pointers borrow ARG1's last
//        two spares: a_dec[14] at bit 30, a_beta[14] at bit 31.
//
// Commands (opcode, args):
//   1 VN    arg0={outf[13:10],inf[9:6],nlog2[5:2],mode[1:0]}
//           arg1={dst[14]@29,src[14]@28,dst[27:14],src[13:0]}
//                                              n=1<<nlog2 in/out
//           arg2={xrf_k[3:1],eps[0]}           eps=1 + mode==2 selects
//           EPS-NORM (SEQ gated RMSNorm); k = XRF[arg2[3:1]][5:0].
//           arg2==0 is the legacy behaviour — every frozen script writes
//           ARG2=0 on VN, which is what keeps this back-compatible.
//   2 VNW   arg0=len[10:0] (0 ENCODES 2048); arg1=src   vecnorm wbuf load
//   3 ROPET arg1=src                         rope table: 64 cos + 64 sin
//   4 ROPE  arg1={dst,src}                    256 elems
//   5 CONVW arg0={nch[27:15],first[14:2],sel[1:0]}; arg1=src
//           sel 0: weights (4 words/ch)  1: state (3 words/ch)  2: zero state
//   6 CONV  arg0={nch[25:13],first[12:0]}; arg1={dst,src}
//   7 GATE  arg0=dst[14:0]; arg1={src_a,src_b}; arg2={src_dt,src_A}
//           A as {lo,hi} pairs; out: beta[0..15], decay[0..15] at dst
//   8 DNST  arg0={a_beta[13:0]@31:18,a_dec[13:0]@17:4,head[3:0]},
//           a_dec[14]=arg1[30], a_beta[14]=arg1[31]
//           arg1={src_k,src_q}; arg2={dst,src_v}
//           out: 128 x int32 {lo,hi} pairs at dst
//   9 KVAP  arg0={expbias[8:4],kvhead[0]}; arg1={src_v,src_k}
//           dyn-quant k,v (256 each) -> int8 rows + exps at T; T++
//  10 ATTN  arg0=kvhead[0]; arg1={dst,src_q}
//           out: 256 x int32 {lo,hi} pairs at dst (T = TCNT[kvhead])
//  11 ALU   arg0={len[16:4],aop[3:0]}; arg1={srcb,srca}
//           (R-c: len was [15:4], 12 bits / max 4095.  The Qwen3.5-2B MLP
//            DYNQ8s its whole FFN=6144 intermediate in ONE command and a
//            DYNQ8 cannot be chunked -- one shared exponent over the whole
//            vector, reported on EOUT -- so the count took arg0[16], a bit
//            ref/scripts/scan_spare_bits.py proves was never set by any
//            frozen stream.  Max length is now 8191.)
//           arg2={dst[14]@31,dst[30:17],p0[16:0]}  vec_alu ops 0..10, 12
//           (aop 10 AMAX32: p0[0]=fresh; winner on AMAXI/AMAXV CSRs)
//           (aop 12 DYNQ16: p0[0]=k dst (0->XRF[1], 1->XRF[2]),
//            p0[1]=clamp k at 0; k retires into the XRF)
//           (aop 8 EMUL32: p0[6]=probe -> max|prod| on MAXPL/MAXPH and
//            k_a into XRF[2]; p0[5:0] is still the shift)
//  12 DNZ   arg0=head[3:0]                     zero DN state for head
//
// ---- S6 burst window (docs/RUNG3_SPEC.md, rung 3) --------------------
// A second slave, s_axib (AXI4, 32-bit data, 17-bit address, ID width 1,
// same aclk — ZERO new CDC), maps the scratchpad directly:
//     scratch word w at byte 4w,  w = 0..32767   (128 KiB window)
// The 16-bit datum lives in the LOW half of each 32-bit beat, upper half
// ignored — bit-identical to what the SWIN CSR takes today (wdata[15:0])
// and to what seq_movers pushes on MOVY ({16'd0, y_val[15:0]} /
// {16'd0, y_val[31:16]}, rtl/seq_movers.sv:588).  WSTRB[1:0] must be 00
// (a no-op beat) or 11; a 16-bit word has no partial write.
// Both directions are gated on !busy STRUCTURALLY: the scratch muxes at
// the bottom of this file give the engine unconditional priority, so a
// burst that arrives mid-command can NOT disturb it.  Such a burst is
// still drained and answered — BRESP/RRESP = SLVERR, never a silent drop
// (RUNG3_SPEC R8).  All AXI-Lite behaviour (SPTR/SWIN included) is
// bit-identical: with no burst in flight the mux legs reduce exactly to
// the old 3:1 muxes.  HOST CONTRACT: AXI-Lite SWIN and the burst window
// are mutually exclusive (SWIN is idle-only and a burst owns the scratch
// port while it is in flight) — asserted in simulation.
//
// COMMIT CONTRACT (a master may fence on B): BVALID is asserted strictly
// AFTER the last beat's scratch cell is written.  The last beat is loaded
// into the mux-leg register in cycle t, the BRAM write happens at the
// t+1 edge, the shim's W_RESP arm waits for that beat to be consumed
// (bw_pend clears at the same t+1 edge) and only then raises BVALID, so
// BVALID is visible at t+3 — at least one full cycle after the data is
// readable.  Empirically: tb_layershim_c T1, burst write -> BRESP ->
// SWIN readback bit-exact, 1-beat bursts included, 4 seeds.
//
// BUSY vs the CMD DONE-poll (mover fencing): DONE_S assigns busy<=0 and
// cmd_cnt<=cmd_cnt+1 on the SAME edge, and the STATUS CSR read latches
// both from that one register bank in the SAME cycle.  A STATUS word can
// therefore NEVER show the incremented cmd_cnt (or busy==0) while busy is
// still high, and the master sees that word one cycle later still.  busy
// does not linger past the observable done: the first burst issued after
// a poll that shows completion can never take a spurious SLVERR
// (tb_layershim_c T8).  The converse is the master's contract: do not
// issue a layer CMD while one of your bursts is still outstanding — busy
// rising mid-burst is exactly the case that answers SLVERR.

`timescale 1ns/1ps
`default_nettype none

module layer_chan #(
    parameter string RSQRT_ROM    = "rsqrt_rom.hex",
    parameter string SIGMOID_ROM  = "sigmoid_pair_rom.hex",
    parameter string SOFTPLUS_ROM = "softplus_pair_rom.hex",
    parameter string EXP2_ROM     = "exp2_pair_rom.hex",
    parameter string RECIP_ROM    = "recip_rom.hex",
    // ==== EXPERIMENT KNOBS (Track P) — see the banner at the top =======
    // Defaults reproduce the AS-BUILT 0.8B/2B geometry exactly, so a
    // default-parameter synth is the control run that must reproduce
    // build_035's measured 348 URAM / 408.5 BRAM / 1838 DSP
    // (evidence/qwen2b/rc/TIMING_035.md:850-851, and the committed OOC
    //  run synth/out_build_035/proj/stage1.runs/bd_layer_0_0_synth_1).
    // The wide set is the Qwen3.5-4B / -9B geometry, which
    // QWEN35_NEXT_FEASIBILITY.md 2.7 shows is IDENTICAL at both targets.
    //
    //                          as built | 4B and 9B | study wall row (2.1)
    //  LNH   DN value heads       16    |    32     | 10  dn_head 4b/NH=16
    //  N_DN  DeltaNet slots       18    |    24     | 6, 16
    //  N_KV  GQA slots             6    |     8     | 7, 16
    //  NKVH  kv heads per layer    2    |     4     | 9   kvhead is ONE bit
    //  CVD   conv bank depth    6144    |  8192     | 8   18x6144 -> 24x8192
    //  DN_EW DN state elem bits   16    |    16     | 2.7 lever 1: int8
    //
    // Study 2.7's row totals, which this experiment exists to test:
    //   as built  DN  9 banks x 29 = 261 + KV 3 x 29 =  87 -> 348 (36.2 %)
    //   4B / 9B   DN 24 banks x 29 = 696 + KV 8 x 29 = 232 -> 928 (96.7 %)
    //   int8 lever (DN_EW=8)                              -> 580 (60.4 %)
    parameter int LNH   = 16,
    parameter int N_DN  = 18,
    parameter int N_KV  = 6,
    parameter int NKVH  = 2,
    parameter int CVD   = 6144,
    parameter int DN_EW = 16,
    // DN_PACK=1 (only meaningful with DN_EW=8) is the form study 2.7's
    // arithmetic actually costs: "At int8 two state rows pack into one
    // 2048-bit URAM row, halving [the DN banks]" — 24 banks -> 12, and the
    // 928 -> 580 total.  It also halves the bank-mux fan-in, at the price
    // of a write-combining register and one extra half-select mux stage
    // between the registered bank mux and dn_step.  DN_PACK=0 with DN_EW=8
    // is the naive form: 24 banks of 4096 x 1024b, ceil(1024/72)=15 URAM
    // each = 360 + 232 = 592, and the mux fan-in stays 24.
    // DN_PACK=2 is the NAIVE packed form: same 12 banks of 2048b, but the
    // write is a 1024-bit PARTIAL write of the row instead of a combined
    // pair.  It exists to MEASURE the "falls out of URAM" claim rather than
    // assert it.  1024 IS byte-aligned (URAM288 BWE is 9 lanes x 8 bits);
    // the obstacle is the 72-bit PRIMITIVE boundary — 1024 is not a multiple
    // of 72, so the half-row boundary lands inside URAM #14 (bits 1008..1079)
    // and no per-primitive BWE pattern can express it.
    parameter int DN_PACK = 0,
    // DN_PIPE: registered-SLR-crossing depth on the DN state path (Track P
    // fix round, review finding 2).  0 = as built.  N > 0 inserts N register
    // stages on the per-group control/address/write-data FAN-OUT and N stages
    // on the read-data RETURN, so both long hauls become flop-to-flop with no
    // logic in the crossing — which is what makes a Laguna TX/RX site usable.
    // Read latency 2 -> 2 + 2*DN_PIPE; write latency +DN_PIPE.
    parameter int DN_PIPE = 0,
    // DN_BPG: banks per pipeline GROUP.  8 groups the 24 wide banks onto the
    // 3 SLRs; 1 gives every bank its own fan-out registers, so a write-control
    // register drives ONE bank's 29 URAM write ports instead of a group's 232.
    // The measured binding path at DN_BPG=8 is exactly that group fan-out
    // (g_grp[0].bs_p_reg -> g_dn[7].mem_reg_uram_17/BWE_B, route 4.747 of
    // 4.972 ns, 1 logic level), which is what this knob exists to test.
    parameter int DN_BPG = 8
) (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axil:s_axib, ASSOCIATED_RESET aresetn" *)
    input  wire         aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire         aresetn,

    input  wire [11:0]  s_axil_awaddr,
    input  wire         s_axil_awvalid,
    output logic        s_axil_awready,
    input  wire [31:0]  s_axil_wdata,
    input  wire [3:0]   s_axil_wstrb,
    input  wire         s_axil_wvalid,
    output logic        s_axil_wready,
    output logic [1:0]  s_axil_bresp,
    output logic        s_axil_bvalid,
    input  wire         s_axil_bready,
    input  wire [11:0]  s_axil_araddr,
    input  wire         s_axil_arvalid,
    output logic        s_axil_arready,
    output logic [31:0] s_axil_rdata,
    output logic [1:0]  s_axil_rresp,
    output logic        s_axil_rvalid,
    input  wire         s_axil_rready,

    // ---- S6 burst window: AXI4 slave, 32b data / 16b addr, ID width 1.
    // No LOCK/CACHE/PROT/QOS/REGION/USER (RUNG3_SPEC interface contract:
    // tie constants at the fabric).
    input  wire [0:0]   s_axib_awid,
    input  wire [16:0]  s_axib_awaddr,
    input  wire [7:0]   s_axib_awlen,
    input  wire [2:0]   s_axib_awsize,
    input  wire [1:0]   s_axib_awburst,
    input  wire         s_axib_awvalid,
    output wire         s_axib_awready,
    input  wire [31:0]  s_axib_wdata,
    input  wire [3:0]   s_axib_wstrb,
    input  wire         s_axib_wlast,
    input  wire         s_axib_wvalid,
    output wire         s_axib_wready,
    output wire [0:0]   s_axib_bid,
    output wire [1:0]   s_axib_bresp,
    output wire         s_axib_bvalid,
    input  wire         s_axib_bready,
    input  wire [0:0]   s_axib_arid,
    input  wire [16:0]  s_axib_araddr,
    input  wire [7:0]   s_axib_arlen,
    input  wire [2:0]   s_axib_arsize,
    input  wire [1:0]   s_axib_arburst,
    input  wire         s_axib_arvalid,
    output wire         s_axib_arready,
    output wire [0:0]   s_axib_rid,
    output wire [31:0]  s_axib_rdata,
    output wire [1:0]   s_axib_rresp,
    output wire         s_axib_rlast,
    output wire         s_axib_rvalid,
    input  wire         s_axib_rready
);
    import fx_pkg::*;

    // ==== EXPERIMENT: derived banking widths ==========================
    // Both memories are addressed as ONE linear array and then split at
    // the 4096-row URAM depth boundary, which is exactly what the
    // as-built RTL does by hand:
    //   DN  linear = {dn_slot, head, row}    bank = linear[.:12]
    //   KV  linear = {kv_slot, kvhead, t}    bank = linear[.:12]
    // At the default parameters these expressions are BIT-IDENTICAL to
    // rtl/layer_chan.sv:449-454 and :498-518.
    localparam int HB     = $clog2(LNH);          // 4 as built, 5 wide
    localparam int LDB    = 5;                    // dn_slot field width (LAYER CSR)
    localparam int KVB    = 3;                    // kv_slot field width (LAYER CSR)
    localparam int KHB    = $clog2(NKVH);         // 1 as built, 2 wide
    // DN_SH = log2(state rows packed into one URAM row): 0 normally,
    // 1 for the packed int8 form of study 2.7 lever 1.
    localparam int DN_SH  = ((DN_EW == 8) && (DN_PACK != 0)) ? 1 : 0;
    localparam int DN_W   = (DN_SH != 0) ? 2048 : 128 * DN_EW; // URAM row width
    localparam int DN_AW  = LDB + HB + 7;         // 16 as built, 17 wide
    localparam int DN_ROWS = N_DN * LNH * 128;    // 36,864 / 98,304
    localparam int DN_NB  = (((DN_ROWS >> DN_SH)) + 4095) / 4096;  // 9/24/12
    localparam int DN_BW  = DN_AW - 12 - DN_SH;   // 4 as built, 5 wide, 4 packed
    localparam int KV_AW  = KVB + KHB + 10;       // 14 as built, 15 wide
    localparam int KV_NB  = (N_KV * NKVH * 1024 + 4095) / 4096; // 3 / 8
    localparam int KV_BW  = KV_AW - 12;           // 2 as built, 3 wide
    localparam int GIW    = $clog2(2 * LNH);      // 5 as built, 6 wide
    // DN bank groups for the pipelined variants: 8 banks per group maps 24
    // banks onto the 3 SLRs the 928-URAM build is forced to span.
    localparam int DN_GRP = (DN_NB + DN_BPG - 1) / DN_BPG;   // 3 at BPG=8
    localparam int DN_GW  = (DN_GRP > 1) ? $clog2(DN_GRP) : 1;
    localparam int DN_SDEL = 2 * DN_PIPE + 1;   // bank-select delay line

    localparam logic [3:0] OP_VN    = 4'd1;
    localparam logic [3:0] OP_VNW   = 4'd2;
    localparam logic [3:0] OP_ROPET = 4'd3;
    localparam logic [3:0] OP_ROPE  = 4'd4;
    localparam logic [3:0] OP_CONVW = 4'd5;
    localparam logic [3:0] OP_CONV  = 4'd6;
    localparam logic [3:0] OP_GATE  = 4'd7;
    localparam logic [3:0] OP_DNST  = 4'd8;
    localparam logic [3:0] OP_KVAP  = 4'd9;
    localparam logic [3:0] OP_ATTN  = 4'd10;
    localparam logic [3:0] OP_ALU   = 4'd11;
    localparam logic [3:0] OP_DNZ   = 4'd12;

    // ==================================================================
    // CSR registers
    // ==================================================================
    logic [3:0]  cmd_op;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [31:0] arg0, arg1, arg2;   // per-command packing; some bits spare
    /* verilator lint_on UNUSEDSIGNAL */
    logic [14:0] sptr;
    logic [15:0] cmd_cnt;
    logic        busy, err_op;
    logic [3:0]  eout_q;
    logic [9:0]  tcnt_bank [N_KV][NKVH]; // [kv_slot][kvhead] KV append counters
    logic [LDB-1:0] layer_dn;            // live LAYER.dn_slot (0..N_DN-1)
    logic [KVB-1:0] layer_kv;            // live LAYER.kv_slot (0..N_KV-1)
    logic [31:0] lcyc;                   // busy-cycle counter (LCYC CSR)
    logic        cmd_go;                 // pulse into dispatcher
    logic        hw_we;                  // host scratch write (registered)
    logic [14:0] hw_addr;
    logic [15:0] hw_data;
    logic        tcnt_inc;               // from dispatcher (KVAP): +1 the
                                         // live-command counter
                                         // tcnt_bank[kv_layer_r][kvhead_r]

    // ---- XRF (see the header) ----
    logic signed [17:0] xrf [8];
    logic [2:0]  xrfi;                   // XRFI index register
    logic        xrf_we;                 // external (CSR / future SEQ) write
    logic [2:0]  xrf_widx;
    logic signed [17:0] xrf_wdat;

    // ==================================================================
    // scratchpad: 16K x 16, replicated for two read ports
    // ==================================================================
    logic signed [15:0] smem_a [32768];
    logic signed [15:0] smem_b [32768];
    logic [14:0] sa_addr, sb_addr;
    logic signed [15:0] sa_q, sb_q;
    logic [14:0] sw_addr;
    logic signed [15:0] sw_data;
    logic        sw_en;
    always_ff @(posedge aclk) begin
        sa_q <= smem_a[sa_addr];
        if (sw_en) smem_a[sw_addr] <= sw_data;
    end
    always_ff @(posedge aclk) begin
        sb_q <= smem_b[sb_addr];
        if (sw_en) smem_b[sw_addr] <= sw_data;
    end

    // ==================================================================
    // local reset pipeline: the XDMA user_reset -> layer_chan haul was a
    // build_020 violated-path family (rstn gates the CE of every
    // non-reset register, so the die-crossing net timed against wide
    // data registers like krow). Reset holds for thousands of cycles
    // before any CSR traffic; +2 cycles of assertion skew is harmless.
    // ==================================================================
    (* keep = "true" *) logic rstn_q, rstn_i;
    always_ff @(posedge aclk) begin
        rstn_q <= aresetn;
        rstn_i <= rstn_q;
    end

    // ==================================================================
    // unit instances + their wiring
    // ==================================================================
    // --- vecnorm ---
    logic        vn_start, vn_wwe;
    logic [10:0] vn_waddr;          // 2048 vecnorm weights (n_log2 = 11)
    logic        vn_svalid, vn_sready, vn_mvalid, vn_mready;
    logic signed [15:0] vn_sdata, vn_mdata;
    /* verilator lint_off UNUSEDSIGNAL */
    logic vn_busy;
    /* verilator lint_on UNUSEDSIGNAL */
    // ARG2 threading (EPS-NORM): eps gate + the XRF entry holding DYNQ16's
    // k.  k is [-14,17] on any int32 block, so the low 6 bits of the 18-bit
    // XRF word ARE the sign-correct value.
    wire signed [5:0] vn_k = xrf[arg2[3:1]][5:0];
    vecnorm_unit #(.RSQRT_ROM(RSQRT_ROM)) u_vn (
        .clk(aclk), .rstn(rstn_i),
        .cfg_mode(arg0[1:0]), .cfg_nlog2(arg0[5:2]),
        .cfg_inf(arg0[9:6]), .cfg_outf(arg0[13:10]),
        .cfg_eps(arg2[0]), .cfg_k(vn_k),
        .start(vn_start), .busy(vn_busy),
        .w_we(vn_wwe), .w_waddr(vn_waddr), .w_wdata(unsigned'(vn_sdata)),
        .s_valid(vn_svalid), .s_ready(vn_sready), .s_data(vn_sdata),
        .m_valid(vn_mvalid), .m_ready(vn_mready), .m_data(vn_mdata));

    // --- rope ---
    logic        rp_start, rp_twe;
    logic [7:0]  rp_taddr;
    logic        rp_svalid, rp_sready, rp_mvalid, rp_mready;
    logic signed [15:0] rp_sdata, rp_mdata;
    /* verilator lint_off UNUSEDSIGNAL */
    logic rp_busy;
    /* verilator lint_on UNUSEDSIGNAL */
    rope_unit u_rope (
        .clk(aclk), .rstn(rstn_i), .start(rp_start), .busy(rp_busy),
        .t_we(rp_twe), .t_waddr(rp_taddr), .t_wdata(unsigned'(rp_sdata)),
        .s_valid(rp_svalid), .s_ready(rp_sready), .s_data(rp_sdata),
        .m_valid(rp_mvalid), .m_ready(rp_mready), .m_data(rp_mdata));

    // --- conv4_silu ---
    logic        cv_ivalid, cv_ovalid;
    logic signed [15:0] cv_win0, cv_win1, cv_win2, cv_win3;
    logic signed [15:0] cv_w0, cv_w1, cv_w2, cv_w3;
    logic signed [15:0] cv_oy;
    conv4_silu #(.SIGMOID_ROM(SIGMOID_ROM)) u_conv (
        .clk(aclk), .rstn(rstn_i), .in_valid(cv_ivalid),
        .win0(cv_win0), .win1(cv_win1), .win2(cv_win2), .win3(cv_win3),
        .w0(cv_w0), .w1(cv_w1), .w2(cv_w2), .w3(cv_w3),
        .out_valid(cv_ovalid), .out_y(cv_oy));

    // --- gate_unit ---
    logic        gt_start, gt_done, gt_wwe;
    logic [1:0]  gt_wsel;
    logic [HB-1:0] gt_waddr;
    logic signed [17:0] gt_wdata;
    logic [15:0] gt_beta [LNH];
    logic [15:0] gt_decay [LNH];
    /* verilator lint_off UNUSEDSIGNAL */
    logic gt_busy;
    /* verilator lint_on UNUSEDSIGNAL */
    gate_unit #(.NH(LNH), .SIGMOID_ROM(SIGMOID_ROM),
                .SOFTPLUS_ROM(SOFTPLUS_ROM),
                .EXP2_ROM(EXP2_ROM)) u_gate (
        .clk(aclk), .rstn(rstn_i), .start(gt_start), .busy(gt_busy),
        .done(gt_done), .w_we(gt_wwe), .w_sel(gt_wsel), .w_addr(gt_waddr),
        .w_data(gt_wdata), .beta_o(gt_beta), .decay_o(gt_decay));

    // --- dn_step + state URAM (16 heads x 128 rows x 2048b) ---
    logic        dn_start, dn_vwe;
    /* verilator lint_off UNUSEDSIGNAL */
    logic        dn_done;   // collection is count-based; done pulse unused
    /* verilator lint_on UNUSEDSIGNAL */
    logic [1:0]  dn_vsel;
    logic [6:0]  dn_vaddr;
    logic signed [20:0] dn_vdata;
    logic [15:0] dn_decay, dn_beta;
    logic [6:0]  dn_rda, dn_wra;
    wire  [2047:0] dn_rdq;      // EXP: driven by the DN_EW widen stage
    logic [2047:0] dn_wrd;
    logic        dn_wren;
    logic        dn_mvalid, dn_mready;
    logic signed [31:0] dn_mdata;
    logic [6:0]  dn_midx;
    /* verilator lint_off UNUSEDSIGNAL */
    logic dn_busy;
    /* verilator lint_on UNUSEDSIGNAL */
    dn_step u_dn (
        .clk(aclk), .rstn(rstn_i), .start(dn_start), .busy(dn_busy),
        .done(dn_done), .cfg_decay(dn_decay), .cfg_beta(dn_beta),
        .vec_we(dn_vwe), .vec_sel(dn_vsel), .vec_addr(dn_vaddr),
        .vec_data(dn_vdata),
        .s_rdaddr(dn_rda), .s_rddata(dn_rdq),
        .s_wraddr(dn_wra), .s_wrdata(dn_wrd), .s_wren(dn_wren),
        .m_valid(dn_mvalid), .m_ready(dn_mready), .m_data(dn_mdata),
        .m_idx(dn_midx));

    // DeltaNet state: DN_NB URAM banks of 4096 x DN_W.  EXPERIMENT: the
    // as-built hand-split ({dn_layer_r[0], head[3:0], row[6:0]} in-bank,
    // dn_layer_r[4:1] as the bank) is rewritten as ONE linear address
    // {dn_slot, head, row} cut at the 4096-row URAM depth — BIT-IDENTICAL
    // at the default parameters, and it generalises.  At the 4B/9B geometry
    // (LNH=32, N_DN=24) HB+7 == 12, so one bank holds exactly ONE layer and
    // DN_NB == 24 — study 2.7's "24 banks / 98,304 rows / 696 URAM".
    // Per-bank read register (the URAM CQ) then a stable-select registered
    // mux (fabric OREG) keeps the 2-cycle read latency dn_step expects.
    // THAT REGISTERED 2048-BIT MUX is the path study section 6 item 3 names.
    // MEASURED (evidence/qwen_next/place_exp/PLACE_EXP.md): at 24 banks the
    // sources span all three SLRs, the placer centres this register in the
    // middle one so any ONE access crosses at most one boundary — and it is
    // still -1.848 ns against 4.000, against +0.211 at the as-built 9 banks.
    logic [LDB-1:0] dn_layer_r;           // latched LAYER.dn_slot (0..N_DN-1)
    logic [HB-1:0]  dn_head;              // latched at dispatch
    logic        dnz_we;
    logic [6:0]  dnz_addr;
    // single muxed write port (a second conditional write makes URAM
    // infeasible -> 150K-LUT distributed-RAM fallback; DNST and DNZ are
    // never active in the same command); only the bank enable is decoded.
    wire           dn_w    = dn_wren | dnz_we;
    wire [HB+6:0]  dn_wa   = dn_wren ? {dn_head, dn_wra} : {dn_head, dnz_addr};
    // at DN_EW=8 the top 8 bits of every int16 element are dropped on the
    // way into the bank (study 2.7 lever 1) — that truncation is the point.
    /* verilator lint_off UNUSEDSIGNAL */
    wire [2047:0]  dn_wd   = dn_wren ? dn_wrd : '0;
    /* verilator lint_on UNUSEDSIGNAL */
    wire [DN_AW-1:0] dn_lin_r = {dn_layer_r, dn_head, dn_rda};   // linear read
    // the write linear address' BANK half is identical to dn_bsel by
    // construction (both are just dn_layer_r), so only its low 12 bits
    // are consumed.
    /* verilator lint_off UNUSEDSIGNAL */
    wire [DN_AW-1:0] dn_lin_w = {dn_layer_r, dn_wa};             // linear write
    /* verilator lint_on UNUSEDSIGNAL */
    // With DN_SH=1 the low linear bit selects the HALF of the URAM row and
    // the URAM row index is the linear address shifted down one.
    wire [11:0]      dn_ra_f  = dn_lin_r[11+DN_SH -: 12];        // in-bank read
    wire [11:0]      dn_wa_f  = dn_lin_w[11+DN_SH -: 12];        // in-bank write
    wire             dn_rhalf = (DN_SH != 0) ? dn_lin_r[0] : 1'b0;
    /* verilator lint_off UNUSEDSIGNAL */   // unused unless DN_SH=1
    wire             dn_whalf = (DN_SH != 0) ? dn_lin_w[0] : 1'b0;
    /* verilator lint_on UNUSEDSIGNAL */
    // the bank bits come only from dn_layer_r in every configuration, so
    // ONE dn_bsel still serves both the read mux and the write decode.
    wire [DN_BW-1:0] dn_bsel  = dn_lin_r[DN_AW-1:12+DN_SH];
    // study 2.7 lever 1: at DN_EW=8 the state element narrows on the way in
    // and sign-extends on the way out, so dn_step's 128 x int16 port and
    // every downstream width stay exactly as built.
    localparam int DN_EL = DN_EW;         // element bits in the bank
    wire  [128*DN_EL-1:0] dn_wd_e;        // one state row, narrowed
    // dn_wd_n is bypassed by the DN_PACK=2 partial-write branch, and
    // dn_rdq_b is replaced by the per-group return path when DN_PIPE > 0.
    /* verilator lint_off UNUSEDSIGNAL */
    wire  [DN_W-1:0] dn_wd_n;             // what actually goes to the URAM
    logic [DN_W-1:0] dn_rdq_b [DN_NB];    // per-bank URAM CQ
    /* verilator lint_on UNUSEDSIGNAL */
    wire             dn_w_n;              // ...and whether it goes this cycle
    logic [DN_W-1:0] dn_rdq_n;
    genvar ge;
    generate
        if (DN_EW == 16) begin : g_dnw_full
            assign dn_wd_e = dn_wd;
        end else begin : g_dnw_narrow
            for (ge = 0; ge < 128; ge++) begin : g_nar
                assign dn_wd_e[ge*DN_EL +: DN_EL] = dn_wd[ge*16 +: DN_EL];
            end
        end
    endgenerate
    // packed form: hold the even half, write the pair on the odd half.  A
    // URAM has no bit-granular write enable at this width (1024 is not a
    // multiple of the 9-bit BWE lane), so a partial-row write would drop the
    // array out of URAM entirely — combining is what makes 580 reachable.
    // dn_step drives s_wraddr strictly ascending (rtl/dn_step.sv:193,:224),
    // so the even row always arrives first.
    generate
        if (DN_SH == 0) begin : g_dnw_direct
            assign dn_wd_n = dn_wd_e;
            assign dn_w_n  = dn_w;
        end else if (DN_PACK == 2) begin : g_dnw_partial
            // no combining: every row write fires, as a 1024-bit partial
            // write of the 2048-bit URAM row (review finding 3).
            assign dn_wd_n = {2{dn_wd_e}};
            assign dn_w_n  = dn_w;
        end else begin : g_dnw_pack
            logic [128*DN_EL-1:0] dn_wcomb;
            always_ff @(posedge aclk) if (dn_w && !dn_whalf) dn_wcomb <= dn_wd_e;
            assign dn_wd_n = {dn_wd_e, dn_wcomb};
            assign dn_w_n  = dn_w && dn_whalf;
        end
    endgenerate
    genvar gd, gg;
    generate
    if (DN_PIPE == 0) begin : g_dnpipe0
        // ---- as built: one flat bank array, combinational 24:1 read mux
        // into a single fabric OREG, and a single write-control fan-out.
        for (gd = 0; gd < DN_NB; gd++) begin : g_dn
            (* ram_style = "ultra" *) logic [DN_W-1:0] mem [4096];
            if (DN_PACK == 2) begin : g_partial
                // naive partial write (measurement variant, review finding 3):
                // half of a 2048-bit row.  Only reachable at DN_EW=8, where
                // dn_wd_e is exactly the 1024-bit half.
                always_ff @(posedge aclk) begin
                    dn_rdq_b[gd] <= mem[dn_ra_f];
                    if (dn_w_n && dn_bsel == DN_BW'(gd)) begin
                        if (dn_whalf) mem[dn_wa_f][2047:1024] <= dn_wd_e;
                        else          mem[dn_wa_f][1023:0]    <= dn_wd_e;
                    end
                end
            end else begin : g_full
                always_ff @(posedge aclk) begin
                    dn_rdq_b[gd] <= mem[dn_ra_f];
                    if (dn_w_n && dn_bsel == DN_BW'(gd)) mem[dn_wa_f] <= dn_wd_n;
                end
            end
        end
        always_ff @(posedge aclk)
            dn_rdq_n <= dn_rdq_b[dn_bsel];  // fabric OREG: URAM CQ off the path
    end else begin : g_dnpipeN
        // ---- registered SLR crossing (review finding 2).
        // Both long hauls are pipelined per bank GROUP, so the wire that
        // actually crosses a boundary runs flop -> flop with no logic in it:
        //   FAN-OUT  {read addr, write addr, write data, write en, bank sel}
        //            gets DN_PIPE dont_touch'd per-group copies.  This is the
        //            path that owns v2wide's ACTUAL worst endpoint
        //            (dnz_we_reg -> mem_reg_uram_19/BWE_B, route 5.477 of
        //            5.682 ns), not the read mux.
        //   RETURN   a local mux over the group's banks, then DN_PIPE
        //            registers, then a small DN_GRP:1 mux into the OREG.
        // dont_touch is mandatory: without it synthesis merges the identical
        // per-group fan-out registers back into one and the point is lost.
        logic [DN_BW-1:0] dn_bsel_d [DN_SDEL];
        always_ff @(posedge aclk) begin
            dn_bsel_d[0] <= dn_bsel;
            for (int i = 1; i < DN_SDEL; i++) dn_bsel_d[i] <= dn_bsel_d[i-1];
        end
        logic [DN_W-1:0] dn_rdq_gq [DN_GRP];      // per-group return, pipelined
        for (gg = 0; gg < DN_GRP; gg++) begin : g_grp
            (* dont_touch = "true" *) logic [11:0]      ra_p [DN_PIPE];
            (* dont_touch = "true" *) logic [11:0]      wa_p [DN_PIPE];
            (* dont_touch = "true" *) logic [DN_W-1:0]  wd_p [DN_PIPE];
            (* dont_touch = "true" *) logic             w_p  [DN_PIPE];
            (* dont_touch = "true" *) logic [DN_BW-1:0] bs_p [DN_PIPE];
            always_ff @(posedge aclk) begin
                ra_p[0] <= dn_ra_f; wa_p[0] <= dn_wa_f;
                wd_p[0] <= dn_wd_n; w_p[0]  <= dn_w_n; bs_p[0] <= dn_bsel;
                for (int i = 1; i < DN_PIPE; i++) begin
                    ra_p[i] <= ra_p[i-1]; wa_p[i] <= wa_p[i-1];
                    wd_p[i] <= wd_p[i-1]; w_p[i]  <= w_p[i-1];
                    bs_p[i] <= bs_p[i-1];
                end
            end
            // this group's banks, addressed from its OWN registered copies
            localparam int LO = gg * DN_BPG;
            localparam int NB = (DN_NB - LO > DN_BPG) ? DN_BPG : (DN_NB - LO);
            logic [DN_W-1:0] rdq_l [NB];
            for (gd = 0; gd < NB; gd++) begin : g_dn
                (* ram_style = "ultra" *) logic [DN_W-1:0] mem [4096];
                always_ff @(posedge aclk) begin
                    rdq_l[gd] <= mem[ra_p[DN_PIPE-1]];
                    if (w_p[DN_PIPE-1] && bs_p[DN_PIPE-1] == DN_BW'(LO + gd))
                        mem[wa_p[DN_PIPE-1]] <= wd_p[DN_PIPE-1];
                end
            end
            // local mux over this group, then DN_PIPE return registers.
            // At DN_BPG=1 there is no local mux at all — the bank's CQ feeds
            // the return pipeline directly.
            (* dont_touch = "true" *) logic [DN_W-1:0] rq_p [DN_PIPE];
            localparam int LW = (NB > 1) ? $clog2(NB) : 1;
            if (NB > 1) begin : g_lmux
                always_ff @(posedge aclk)
                    rq_p[0] <= rdq_l[LW'(dn_bsel_d[DN_PIPE] - DN_BW'(LO))];
            end else begin : g_lmux1
                always_ff @(posedge aclk) rq_p[0] <= rdq_l[0];
            end
            always_ff @(posedge aclk)
                for (int i = 1; i < DN_PIPE; i++) rq_p[i] <= rq_p[i-1];
            assign dn_rdq_gq[gg] = rq_p[DN_PIPE-1];
        end
        // final small DN_GRP:1 mux into the OREG, in the destination SLR
        always_ff @(posedge aclk)
            dn_rdq_n <= dn_rdq_gq[(DN_GRP > 1)
                ? DN_GW'(dn_bsel_d[2*DN_PIPE] / DN_BW'(DN_BPG)) : '0];
    end
    endgenerate
    // read side: pick the half (packed only), then widen the element back to
    // int16 so dn_step's port is untouched.  The half-select rides the same
    // two register stages as the data.
    logic dn_rh_d1, dn_rh_d2;
    always_ff @(posedge aclk) begin
        dn_rh_d1 <= dn_rhalf;
        dn_rh_d2 <= dn_rh_d1;
    end
    /* verilator lint_off UNUSEDSIGNAL */
    wire [128*DN_EL-1:0] dn_rdq_e =
        (DN_SH == 0) ? dn_rdq_n[128*DN_EL-1:0]
                     : (dn_rh_d2 ? dn_rdq_n[DN_W-1 -: 128*DN_EL]
                                 : dn_rdq_n[128*DN_EL-1:0]);
    /* verilator lint_on UNUSEDSIGNAL */
    generate
        if (DN_EW == 16) begin : g_dnr_full
            assign dn_rdq = dn_rdq_e;
        end else begin : g_dnr_wide
            for (ge = 0; ge < 128; ge++) begin : g_wid
                assign dn_rdq[ge*16 +: 16] =
                    {{(16-DN_EL){dn_rdq_e[ge*DN_EL + DN_EL - 1]}},
                     dn_rdq_e[ge*DN_EL +: DN_EL]};
            end
        end
    endgenerate

    // --- attn_core + KV memory (2 kvheads x 2 banks x 512 x 2048b) ---
    logic        at_start, at_qwe;
    /* verilator lint_off UNUSEDSIGNAL */
    logic        at_done;   // collection is count-based; done pulse unused
    /* verilator lint_on UNUSEDSIGNAL */
    logic [7:0]  at_qaddr;
    logic signed [15:0] at_qdata;
    logic [9:0]  at_kvaddr;
    logic [2047:0] at_kvdata;
    logic signed [7:0] at_kvexp;
    logic        at_mvalid, at_mready;
    logic signed [31:0] at_mdata;
    logic [7:0]  at_midx;
    logic [9:0]  at_cfg_t;
    /* verilator lint_off UNUSEDSIGNAL */
    logic at_busy;
    /* verilator lint_on UNUSEDSIGNAL */
    attn_core #(.EXP2_ROM(EXP2_ROM), .RECIP_ROM(RECIP_ROM)) u_attn (
        .clk(aclk), .rstn(rstn_i), .start(at_start), .busy(at_busy),
        .done(at_done), .cfg_t(at_cfg_t),
        .q_we(at_qwe), .q_waddr(at_qaddr), .q_wdata(at_qdata),
        .kv_addr(at_kvaddr), .kv_data(at_kvdata), .kv_exp(at_kvexp),
        .m_valid(at_mvalid), .m_ready(at_mready), .m_data(at_mdata),
        .m_idx(at_midx));

    // KV cache: KV_NB URAM banks of 4096 x 2048b.  EXPERIMENT: same linear
    // rewrite as the DN array — {kv_slot, kvhead, k/v, t[8:0]} cut at the
    // 4096-row URAM depth, BIT-IDENTICAL to the as-built
    // {kv_layer_r[0], kvhead, at_kvaddr} / kv_layer_r[2:1] at the defaults.
    // At NKVH=4 (study wall row 9, "kvhead is ONE bit") the in-bank address
    // is full with {kvhead[1:0], k/v, t[8:0]}, so a bank holds ONE GQA layer
    // and KV_NB == 8 — study 2.7's "8 banks / 32,768 rows / 232 URAM".
    // Per-bank read register + stable-select registered mux keeps the
    // 2-cycle read latency.  kvexp is 8b in a plain logic array (BRAM).
    logic          kv_we;
    logic [KHB+9:0] kv_waddr;              // {kvhead, k/v, t[8:0]} in-bank low
    logic [2047:0] kv_wrow;
    logic [7:0]    kv_wexp;
    logic [KVB-1:0] kv_layer_r;            // latched LAYER.kv_slot (0..N_KV-1)
    logic [KHB-1:0] kvhead_r;              // latched at dispatch
    wire  [KV_AW-1:0] kv_lin_r = {kv_layer_r, kvhead_r, at_kvaddr};
    /* verilator lint_off UNUSEDSIGNAL */   // bank half == kv_bsel
    wire  [KV_AW-1:0] kv_lin_w = {kv_layer_r, kv_waddr};
    /* verilator lint_on UNUSEDSIGNAL */
    wire  [11:0]   kv_ra_f = kv_lin_r[11:0];
    wire  [11:0]   kv_wa_f = kv_lin_w[11:0];
    wire  [KV_BW-1:0] kv_bsel = kv_lin_r[KV_AW-1:12];
    logic [2047:0] kv_rdq_b  [KV_NB];      // per-bank URAM CQ (row)
    logic [7:0]    kvx_rdq_b [KV_NB];      // per-bank read (exp)
    genvar gk;
    generate for (gk = 0; gk < KV_NB; gk++) begin : g_kv
        (* ram_style = "ultra" *) logic [2047:0] mem  [4096];
        logic [7:0]                              emem [4096];
        always_ff @(posedge aclk) begin
            kv_rdq_b[gk]  <= mem[kv_ra_f];
            kvx_rdq_b[gk] <= emem[kv_ra_f];
            if (kv_we && kv_bsel == KV_BW'(gk)) begin
                mem[kv_wa_f]  <= kv_wrow;
                emem[kv_wa_f] <= kv_wexp;
            end
        end
    end endgenerate
    always_ff @(posedge aclk) begin
        at_kvdata <= kv_rdq_b[kv_bsel];   // fabric OREG: URAM CQ off the path
        at_kvexp  <= signed'(kvx_rdq_b[kv_bsel]);
    end

    // --- conv weight/state memories: 18 BRAM banks (one per dn slot) ---
    // Bank = dn_layer_r (0..17). Each bank keeps the original 1-cycle
    // registered read + REGISTERED output mux (build_024 census: the
    // combinational 18:1 mux out of spread BRAM banks into u_conv's DSPs
    // was the worst path family at -1.59ns). The extra register makes the
    // read 2-cycle-visible; the CONV FSM gained a CV_W2 wait state to
    // match. LAYER=0 -> bank 0 = old behavior.
    logic [12:0] cw_ra, cs_ra, cw_wa, cs_wa;
    logic [63:0] cw_wd;
    logic [47:0] cs_wd;
    logic        cw_we, cs_we;
    logic [63:0] cw_q_b [N_DN];           // per-bank BRAM read register
    logic [47:0] cs_q_b [N_DN];
    // Second per-bank stage: build_027 census showed cw/cs_q_b merge into
    // the BRAM DOREG, leaving BRAM->18:1 mux->cw/cs_q as the worst path
    // family (-0.363, 9 levels). These explicit fabric registers put the
    // mux on its own cycle; CONV gained CV_W3 to match the 3-cycle read.
    (* dont_touch = "true" *) logic [63:0] cw_q_p [N_DN];
    (* dont_touch = "true" *) logic [47:0] cs_q_p [N_DN];
    genvar gc;
    // EXPERIMENT: study wall row 8, "conv banks + depth 18 x 6144 ->
    // 24 x 8192".  This is BRAM, not URAM (2.7: "BRAM is not the wall"),
    // but it is carried because it competes for the same SLR floor area.
    generate for (gc = 0; gc < N_DN; gc++) begin : g_cv
        logic [63:0] wm [CVD];
        logic [47:0] sm [CVD];
        always_ff @(posedge aclk) begin
            cw_q_b[gc] <= wm[cw_ra];
            cs_q_b[gc] <= sm[cs_ra];
            cw_q_p[gc] <= cw_q_b[gc];
            cs_q_p[gc] <= cs_q_b[gc];
            if (cw_we && dn_layer_r == LDB'(gc)) wm[cw_wa] <= cw_wd;
            if (cs_we && dn_layer_r == LDB'(gc)) sm[cs_wa] <= cs_wd;
        end
    end endgenerate
    // dont_touch: build_025 showed synthesis retimes these into u_conv's
    // DSP input registers, recreating the BRAM->18:1-mux->DSP monster
    // path the register exists to break.
    (* dont_touch = "true" *) logic [63:0] cw_q;  // registered bank mux
    (* dont_touch = "true" *) logic [47:0] cs_q;
    always_ff @(posedge aclk) begin
        cw_q <= cw_q_p[dn_layer_r];
        cs_q <= cs_q_p[dn_layer_r];
    end

    // --- vec_alu ---
    logic        alu_start, alu_done;
    logic [3:0]  alu_eout;
    logic [14:0] alu_aa, alu_ba, alu_wa;
    logic signed [15:0] alu_wd;
    logic        alu_we;
    /* verilator lint_off UNUSEDSIGNAL */
    logic alu_busy;
    /* verilator lint_on UNUSEDSIGNAL */
    logic [17:0]        alu_amax_idx;
    logic signed [31:0] alu_amax_val;
    logic signed [6:0]  alu_k;
    logic               alu_k_we;
    logic [47:0]        alu_maxp;
    logic [50:0]        alu_topk;     // rung 4 S5 export {we, val, idx}
    vec_alu #(.SIGMOID_ROM(SIGMOID_ROM)) u_alu (
        .clk(aclk), .rstn(rstn_i), .start(alu_start), .busy(alu_busy),
        .done(alu_done),
        .cfg_op(arg0[3:0]), .cfg_len(arg0[16:4]),   // R-c: 13-bit len
        .cfg_p0(signed'(arg2[16:0])),
        .cfg_srca({arg1[28], arg1[13:0]}),
        .cfg_srcb({arg1[29], arg1[27:14]}),
        .cfg_dst({arg2[31], arg2[30:17]}), .e_out(alu_eout),
        .amax_idx(alu_amax_idx), .amax_val(alu_amax_val),
        .k_out(alu_k), .k_we(alu_k_we), .maxp_out(alu_maxp),
        .topk_bun(alu_topk),
        .a_addr(alu_aa), .a_q(sa_q), .b_addr(alu_ba), .b_q(sb_q),
        .w_addr(alu_wa), .w_data(alu_wd), .w_en(alu_we));

    // ==================================================================
    // rung 4 S5: TOPK-32 sibling block.  Self-contained (all of its state
    // is inside the instance), fed by the ONE registered 51-bit bundle
    // above and by two control bits derived from registers this file
    // already has:
    //
    //   tk_fresh = the AMAX32 fresh flag itself — the dispatch pulse for
    //              an ALU command whose aop is 10 and whose p0[0] is 1
    //              (cfg_p0 = arg2[16:0], so p0[0] = arg2[0]).  It leads
    //              the first exported sample by 4 cycles (start -> t_ad ->
    //              t_rd -> t_cp -> export register), so the clear can
    //              never race a sample of its own scan.
    //   tk_amax  = an AMAX32 ALU command is in flight in THIS engine
    //              (busy && cmd_op == ALU && aop == 10).  It is the
    //              "in flight" half of the `complete` derivation; see
    //              layer_topk32.
    //
    // Both are ANDs of existing flip-flops (no new state, no reach into
    // the dispatcher, nothing added to a live path).
    // ==================================================================
    wire tk_fresh = alu_start && (arg0[3:0] == 4'd10) && arg2[0];
    wire tk_amax  = busy && (cmd_op == OP_ALU) && (arg0[3:0] == 4'd10);

    // CSR strobes: EXACTLY the conditions the AXI-Lite slave below uses
    // for a write commit / a read accept, mirrored out here so the shipped
    // slave block itself is untouched.  The PTR-write pair is DRIVEN just
    // after that block (it reads aw_got/w_got/awaddr_q/wdata_q, which the
    // LRM's declaration-before-use rule puts there); it is declared here
    // because the instance below reads it.
    wire        tk_ptr_we;
    wire [4:0]  tk_ptr_wd;
    wire        tk_ptr_adv = s_axil_arvalid && s_axil_arready
                             && (s_axil_araddr[11:2] == 10'h016);
    wire [4:0]  tk_ptr;
    wire [5:0]  tk_cnt;
    wire        tk_complete, tk_ovf;
    wire [31:0] tk_val;
    wire [17:0] tk_idx;

    layer_topk32 u_topk (
        .clk(aclk), .rstn(rstn_i),
        .bun(alu_topk), .fresh(tk_fresh), .amax_busy(tk_amax),
        .ptr_we(tk_ptr_we), .ptr_wd(tk_ptr_wd), .ptr_adv(tk_ptr_adv),
        .ptr(tk_ptr), .cnt(tk_cnt), .complete(tk_complete), .ovf(tk_ovf),
        .sel_val(tk_val), .sel_idx(tk_idx));

    // XRF destination for a retiring block-float exponent: DYNQ16 picks
    // XRF[1]/XRF[2] with cfg_p0[0] (= arg2[0]); the op-8 probe always
    // targets k_attn = XRF[2] (its cfg_p0 low bits are the shift).
    wire [2:0] alu_k_idx = (arg0[3:0] == 4'd12) ? (arg2[0] ? 3'd2 : 3'd1)
                                                : 3'd2;

    // ==================================================================
    // XRF write arbitration (see the header for the agent-D interface)
    // ==================================================================
    always_ff @(posedge aclk) begin
        if (!rstn_i) begin
            for (int x = 0; x < 8; x++) xrf[x] <= '0;
        end else begin
            if (alu_done && (arg0[3:0] == 4'd0))
                xrf[0] <= 18'(signed'({1'b0, alu_eout}));   // e_x, unsigned 4b
            if (alu_k_we) xrf[alu_k_idx] <= 18'(alu_k);
            if (xrf_we)   xrf[xrf_widx]  <= xrf_wdat;       // CSR/SEQ wins
        end
    end

    // ==================================================================
    // AXI-Lite slave (single outstanding, always responds)
    // ==================================================================
    logic        aw_got, w_got;
    logic [9:0]  awaddr_q;
    logic [31:0] wdata_q;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [3:0]  wstrb_q;
    wire  [1:0]  unused_lsbs = s_axil_awaddr[1:0] | s_axil_araddr[1:0];
    /* verilator lint_on UNUSEDSIGNAL */

    assign s_axil_awready = !aw_got && !s_axil_bvalid;
    assign s_axil_wready  = !w_got  && !s_axil_bvalid;
    assign s_axil_arready = !s_axil_rvalid;

    always_ff @(posedge aclk) begin
        if (!rstn_i) begin
            aw_got <= 1'b0; w_got <= 1'b0;
            s_axil_bvalid <= 1'b0; s_axil_bresp <= 2'b00;
            cmd_go <= 1'b0; hw_we <= 1'b0;
            cmd_op <= '0; arg0 <= '0; arg1 <= '0; arg2 <= '0;
            sptr <= '0; xrfi <= '0; xrf_we <= 1'b0;
            for (int i = 0; i < 6; i++) begin
                tcnt_bank[i][0] <= '0; tcnt_bank[i][1] <= '0;
            end
            layer_dn <= '0; layer_kv <= '0; lcyc <= '0;
        end else begin
            cmd_go <= 1'b0;
            hw_we  <= 1'b0;
            xrf_we <= 1'b0;
            if (busy) lcyc <= lcyc + 1'b1;   // write-clear below wins

            if (s_axil_awvalid && s_axil_awready) begin
                aw_got <= 1'b1; awaddr_q <= s_axil_awaddr[11:2];
            end
            if (s_axil_wvalid && s_axil_wready) begin
                w_got <= 1'b1; wdata_q <= s_axil_wdata; wstrb_q <= s_axil_wstrb;
            end

            if (aw_got && w_got && !s_axil_bvalid) begin
                case (awaddr_q)
                    10'h000: if (!busy) begin                    // CMD
                        cmd_op <= wdata_q[3:0];
                        cmd_go <= 1'b1;
                    end
                    10'h002: arg0 <= wdata_q;                    // ARG0
                    10'h003: arg1 <= wdata_q;                    // ARG1
                    10'h004: arg2 <= wdata_q;                    // ARG2
                    10'h005: sptr <= wdata_q[14:0];              // SPTR
                    10'h006: begin                               // SWIN
                        hw_we   <= 1'b1;
                        hw_addr <= sptr;
                        hw_data <= wdata_q[15:0];
                        sptr    <= sptr + 1'b1;
                    end
                    10'h008: begin                               // TCNT
                        // EXP: at NKVH>2 the CSR word has no room for the
                        // extra counters (study wall row 9 is a FIELD wall,
                        // not a capacity one); they alias onto the same two
                        // 10-bit fields so all NKVH stay resettable.
                        for (int kh = 0; kh < NKVH; kh++)
                            tcnt_bank[layer_kv][kh]
                                <= wdata_q[16*(kh % 2) +: 10];
                    end
                    10'h00C: begin                               // LAYER
                        layer_dn <= wdata_q[LDB-1:0];
                        layer_kv <= wdata_q[8 +: KVB];
                    end
                    10'h00D: lcyc <= '0;                          // LCYC clear
                    10'h00E: xrfi <= wdata_q[2:0];                // XRFI
                    10'h00F: begin                                // XRFD
                        xrf_we   <= 1'b1;
                        xrf_widx <= xrfi;
                        xrf_wdat <= signed'(wdata_q[17:0]);
                    end
                    default: ;
                endcase
                s_axil_bvalid <= 1'b1; s_axil_bresp <= 2'b00;
                aw_got <= 1'b0; w_got <= 1'b0;
            end
            if (s_axil_bvalid && s_axil_bready) s_axil_bvalid <= 1'b0;

            if (tcnt_inc)
                tcnt_bank[kv_layer_r][kvhead_r]
                    <= tcnt_bank[kv_layer_r][kvhead_r] + 1'b1;

            // reads
            if (s_axil_arvalid && s_axil_arready) begin
                s_axil_rvalid <= 1'b1; s_axil_rresp <= 2'b00;
                case (s_axil_araddr[11:2])
                    10'h001: s_axil_rdata <= {cmd_cnt, 14'b0, err_op, busy};
                    10'h002: s_axil_rdata <= arg0;
                    10'h003: s_axil_rdata <= arg1;
                    10'h004: s_axil_rdata <= arg2;
                    10'h005: s_axil_rdata <= {17'b0, sptr};
                    10'h006: begin                               // SWIN
                        s_axil_rdata <= {16'b0, unsigned'(sa_q)};
                        sptr <= sptr + 1'b1;
                    end
                    10'h007: s_axil_rdata <= {28'b0, eout_q};
                    10'h008: s_axil_rdata <= {6'b0, tcnt_bank[layer_kv][1],
                                              6'b0, tcnt_bank[layer_kv][0]};
                    10'h009: s_axil_rdata <= 32'hFAB1E5A0;
                    10'h00A: s_axil_rdata <= {14'b0, alu_amax_idx};
                    10'h00B: s_axil_rdata <= unsigned'(alu_amax_val);
                    10'h00C: s_axil_rdata <= {21'b0, layer_kv, 3'b0, layer_dn};
                    10'h00D: s_axil_rdata <= lcyc;
                    10'h00E: s_axil_rdata <= {29'b0, xrfi};       // XRFI
                    10'h00F: s_axil_rdata <= {14'b0,              // XRFD raw
                                              unsigned'(xrf[xrfi])};
                    10'h010: s_axil_rdata <= alu_maxp[31:0];      // MAXPL
                    10'h011: s_axil_rdata <= {16'b0, alu_maxp[47:32]};
                    // ---- rung 4 S5: TOPK-32 (0x48..0x58) ----
                    10'h012: s_axil_rdata <= 32'hFAB1704B;        // TK_IDENT
                    10'h013: s_axil_rdata <= {24'b0, tk_ovf,      // TK_STATUS
                                              tk_complete, tk_cnt};
                    10'h014: s_axil_rdata <= {27'b0, tk_ptr};     // TK_PTR
                    10'h015: s_axil_rdata <= tk_val;              // TK_VAL
                    // TK_IDX: the read itself advances TK_PTR (tk_ptr_adv)
                    10'h016: s_axil_rdata <= {14'b0, tk_idx};
                    default: s_axil_rdata <= 32'hDEADC0DE;
                endcase
            end else if (s_axil_rvalid && s_axil_rready)
                s_axil_rvalid <= 1'b0;
        end
    end

    // rung 4 S5: the TOPK-32 PTR write (declared up at the instance).  A
    // write commits in the same cycle the slave above raises BVALID, so
    // this is that condition, decoded for 0x50 only.
    assign tk_ptr_we = aw_got && w_got && !s_axil_bvalid
                       && (awaddr_q == 10'h014);
    assign tk_ptr_wd = wdata_q[4:0];

    // ==================================================================
    // dispatcher FSM
    // ==================================================================
    typedef enum logic [5:0] {
        IDLE,
        F_A, F_W, F_P, F_H,                 // stream feed (VN/ROPE)
        C_RD,                               // stream collect 16b
        L_A, L_W, L_P,                      // generic preload loops
        RUN_W,                              // wait gate done
        G_ST,                               // gate result store
        CV_A, CV_W, CV_W2, CV_W3, CV_P, CV_D,  // conv feed + drain
        CW_A, CW_W, CW_P, CZ_W,             // conv weight/state load, zero
        KQ_A, KQ_W, KQ_S, KQ_M, KQ_E,       // kvap maxabs scan + exp
        K2_A, K2_W, K2_S, K2_B, K2_Q, K_WR, // kvap quant pass + row write
        D_RDY, D_HI,                        // 32b indexed collect (DN/ATTN)
        A_RUN,                              // vec_alu run
        Z_W,                                // DNZ zero loop
        DONE_S
    } st_e;
    st_e st;

    // loader targets
    localparam logic [3:0] LT_VNW   = 4'd0;
    localparam logic [3:0] LT_ROPET = 4'd1;
    localparam logic [3:0] LT_GB    = 4'd2;
    localparam logic [3:0] LT_GA    = 4'd3;
    localparam logic [3:0] LT_GAA   = 4'd4;
    localparam logic [3:0] LT_GDT   = 4'd5;
    localparam logic [3:0] LT_DK    = 4'd6;
    localparam logic [3:0] LT_DQ    = 4'd7;
    localparam logic [3:0] LT_DV    = 4'd8;
    localparam logic [3:0] LT_AQ    = 4'd9;
    localparam logic [3:0] LT_DDEC  = 4'd10;
    localparam logic [3:0] LT_DBET  = 4'd11;

    logic [14:0] eng_sa;                  // dispatcher scratch read addr
    logic [14:0] eng_swa;                 // dispatcher scratch write port
    logic signed [15:0] eng_swd;
    logic        eng_swe;

    logic [14:0] fi, ci;                  // feed / collect counters
    // VN/ROPE feed pipeline (F_A/F_W), 1 element/cycle
    logic [14:0] f_ai;                    // addresses issued
    logic        f_q1;                    // sa_q holds a feed element now
    logic        f_skv;                   // 1-deep skid occupied
    logic signed [15:0] f_skd;            // ... and its datum
    logic [14:0] n_elems;                 // VN/ROPE element count (<= 16384)
    logic [3:0]  ld_tgt;
    logic [10:0] ld_i, ld_n;
    logic [14:0] ld_src;
    logic [15:0] tmp16;
    logic        rnd;                     // KVAP round: 0=k, 1=v
    logic [8:0]  ki;
    logic [3:0]  eq;
    logic [15:0] kmax;
    logic [2047:0] krow;
    logic signed [15:0] s16q;             // registered scratch word (BRAM CQ)
    logic [7:0]  kbyte;                   // quantized byte
    logic [8:0]  kb_i;                    // its row index
    logic [12:0] wi;                      // CONVW channel counter
    logic [1:0]  wk;                      // CONVW word-in-channel
    /* verilator lint_off UNUSEDSIGNAL */
    logic [63:0] tmp64;                   // [63:48] never read back
    /* verilator lint_on UNUSEDSIGNAL */
    logic [12:0] cvi, cvj;                // CONV feed/collect counters
    logic [GIW:0] gi;                     // GATE store counter (2*LNH)
    logic [6:0]  zi;                      // DNZ counter
    logic [9:0]  rcvd, n_col;             // 32b collect
    logic [15:0] m_hi;                    // captured hi half
    logic [14:0] dst_r, src2_r;           // latched dst / second src
    logic        gate_done_q;

    // decoded args (stable while busy: host must not rewrite ARGs mid-cmd)
    // 15-bit scratch addressing (SEQ_ISA v1.7).  ARG1 carries an address
    // PAIR, and each half's bit 14 rides in an ARG1 bit that
    // evidence/qwen2b/rb/spare_bits_report.txt proves is never set by any
    // pre-R-b stream: lo[14] at 28, hi[14] at 29.  ARG2 uses the same
    // layout on GATE and DNST; the ALU's ARG2 is full, so its dst[14] is
    // bit 31 (its only spare) — see the vec_alu instance above.
    wire [14:0] a1_src = {arg1[28], arg1[13:0]};
    wire [14:0] a1_dst = {arg1[29], arg1[27:14]};
    wire [14:0] a2_src = {arg2[28], arg2[13:0]};
    wire [14:0] a2_dst = {arg2[29], arg2[27:14]};
    wire [4:0]  kv_expbias = arg0[8:4];

    always_ff @(posedge aclk) begin
        if (!rstn_i) begin
            st <= IDLE;
            busy <= 1'b0; err_op <= 1'b0;
            cmd_cnt <= '0;
            eout_q <= '0;
            vn_start <= 1'b0; rp_start <= 1'b0; gt_start <= 1'b0;
            dn_start <= 1'b0; at_start <= 1'b0; alu_start <= 1'b0;
            vn_wwe <= 1'b0; rp_twe <= 1'b0; gt_wwe <= 1'b0;
            dn_vwe <= 1'b0; at_qwe <= 1'b0;
            cv_ivalid <= 1'b0; cw_we <= 1'b0; cs_we <= 1'b0;
            kv_we <= 1'b0; dnz_we <= 1'b0;
            vn_svalid <= 1'b0; rp_svalid <= 1'b0;
            vn_mready <= 1'b0; rp_mready <= 1'b0;
            dn_mready <= 1'b0; at_mready <= 1'b0;
            eng_swe <= 1'b0;
            tcnt_inc <= 1'b0;
        end else begin
            // one-cycle defaults
            vn_start <= 1'b0; rp_start <= 1'b0; gt_start <= 1'b0;
            dn_start <= 1'b0; at_start <= 1'b0; alu_start <= 1'b0;
            vn_wwe <= 1'b0; rp_twe <= 1'b0; gt_wwe <= 1'b0;
            dn_vwe <= 1'b0; at_qwe <= 1'b0;
            cv_ivalid <= 1'b0; cw_we <= 1'b0; cs_we <= 1'b0;
            kv_we <= 1'b0; dnz_we <= 1'b0;
            eng_swe <= 1'b0;
            tcnt_inc <= 1'b0;
            if (gt_done) gate_done_q <= 1'b1;

            // CONV output collector (no backpressure; <=1 write per cycle)
            if (st inside {CV_A, CV_W, CV_W2, CV_W3, CV_P, CV_D}
                && cv_ovalid) begin
                eng_swa <= dst_r + 15'(cvj);
                eng_swd <= cv_oy;
                eng_swe <= 1'b1;
                cvj <= cvj + 1'b1;
            end

            case (st)
                // ----------------------------------------------------
                IDLE: if (cmd_go) begin
                    busy <= 1'b1;
                    err_op <= 1'b0;
                    fi <= '0; ci <= '0; ld_i <= '0;
                    rnd <= 1'b0; ki <= '0; eq <= '0; kmax <= '0;
                    wi <= '0; wk <= '0; cvi <= '0; cvj <= '0;
                    gi <= '0; zi <= '0; rcvd <= '0;
                    gate_done_q <= 1'b0;
                    // EXP: study wall row 10 (dn_head is 4 bits) and row 9
                    // (kvhead is 1 bit) are FIELD walls; the experiment just
                    // takes the extra bit so the banking is the real width.
                    dn_head <= arg0[HB-1:0];
                    kvhead_r <= arg0[KHB-1:0];
                    dn_layer_r <= layer_dn;   // bank state on latched slots
                    kv_layer_r <= layer_kv;
                    case (cmd_op)
                        OP_VN: begin
                            n_elems <= 15'd1 << arg0[5:2];
                            dst_r <= a1_dst;
                            vn_start <= 1'b1;
                            eng_sa <= a1_src;
                            st <= F_A;
                        end
                        OP_ROPE: begin
                            n_elems <= 15'd256;
                            dst_r <= a1_dst;
                            rp_start <= 1'b1;
                            eng_sa <= a1_src;
                            st <= F_A;
                        end
                        OP_VNW: begin
                            // ld_n is 11 bits and the vecnorm wbuf is 2048
                            // deep: ld_n = 0 ENCODES 2048.  ld_i is 11 bits
                            // too, so ld_i+1 == ld_n wraps and fires at
                            // ld_i = 2047, after all 2048 entries are
                            // written.  Documented in docs/SEQ_ISA.md.
                            ld_tgt <= LT_VNW; ld_n <= arg0[10:0];
                            ld_src <= a1_src; eng_sa <= a1_src;
                            st <= L_A;
                        end
                        OP_ROPET: begin
                            ld_tgt <= LT_ROPET; ld_n <= 11'd128;
                            ld_src <= a1_src; eng_sa <= a1_src;
                            st <= L_A;
                        end
                        OP_CONVW: begin
                            ld_src <= a1_src; eng_sa <= a1_src;
                            st <= (arg0[1:0] == 2'd2) ? CZ_W : CW_A;
                        end
                        OP_CONV: begin
                            dst_r <= a1_dst;
                            st <= CV_A;
                        end
                        OP_GATE: begin
                            ld_tgt <= LT_GB; ld_n <= 11'(LNH);
                            ld_src <= a1_src; eng_sa <= a1_src;
                            dst_r <= arg0[14:0];
                            st <= L_A;
                        end
                        OP_DNST: begin
                            ld_tgt <= LT_DDEC; ld_n <= 11'd1;
                            // DNST ARG0 is full, so a_dec[14]/a_beta[14]
                            // ride in ARG1[30]/[31] (SEQ_ISA v1.7)
                            ld_src <= {arg1[30], arg0[17:4]};
                            eng_sa <= {arg1[30], arg0[17:4]};
                            dst_r <= a2_dst;
                            src2_r <= a2_src;
                            n_col <= 10'd128;
                            st <= L_A;
                        end
                        OP_KVAP: begin
                            st <= KQ_A;
                            eng_sa <= a1_src;
                        end
                        OP_ATTN: begin
                            ld_tgt <= LT_AQ; ld_n <= 11'd256;
                            ld_src <= a1_src; eng_sa <= a1_src;
                            dst_r <= a1_dst;
                            n_col <= 10'd256;
                            // live layer_kv: kv_layer_r latches this cycle
                            at_cfg_t <= tcnt_bank[layer_kv][arg0[KHB-1:0]];
                            st <= L_A;
                        end
                        OP_ALU: begin
                            alu_start <= 1'b1;
                            st <= A_RUN;
                        end
                        OP_DNZ: st <= Z_W;
                        default: begin
                            err_op <= 1'b1;
                            st <= DONE_S;
                        end
                    endcase
                end

                // ---------- stream feed (VN/ROPE) ----------
                // 1 element/cycle (was a 4-cycle addr/dead/capture/handshake
                // loop).  eng_sa advances every cycle and the vn/rp handshake
                // registers sit one stage behind the 1-cycle sa_q read
                // latency.  F_A primes the pipe: the first address is already
                // on sa_addr this cycle, so sa_q holds element 0 in the next.
                //   f_ai  addresses issued so far
                //   f_q1  sa_q holds a feed element THIS cycle
                //   f_skv/f_skd  1-deep skid, loaded only when the sink stalls
                //         with a datum already in sa_q.  vn/rp s_ready is high
                //         for the whole of their FILL today, so this is the
                //         safety net for a sink that CAN stall, not a
                //         steady-state path.  Issue is gated on the skid being
                //         empty, which makes (f_skv && f_q1) unreachable.
                //   F_P/F_H are no longer entered (the enum keeps them).
                F_A: begin                 // eng_sa already set at dispatch
                    eng_sa <= eng_sa + 15'd1;
                    f_ai   <= 15'd1;
                    f_q1   <= 1'b1;
                    f_skv  <= 1'b0;
                    st <= F_W;
                end
                F_W: begin
                    logic frdy, fv, ofree, iss, ftake;
                    logic signed [15:0] fdat;
                    fv    = (cmd_op == OP_VN) ? vn_svalid : rp_svalid;
                    frdy  = (cmd_op == OP_VN) ? vn_sready : rp_sready;
                    ofree = !fv || frdy;             // output reg can reload
                    iss   = ofree && !f_skv && (f_ai != n_elems);
                    ftake = f_skv || f_q1;
                    fdat  = f_skv ? f_skd : sa_q;
                    // address stage
                    f_q1 <= iss;
                    if (iss) begin
                        eng_sa <= eng_sa + 15'd1;
                        f_ai   <= f_ai + 15'd1;
                    end
                    // capture -> handshake register (or the skid on a stall)
                    if (ofree) begin
                        if (cmd_op == OP_VN) begin
                            vn_svalid <= ftake;
                            if (ftake) vn_sdata <= fdat;
                        end else begin
                            rp_svalid <= ftake;
                            if (ftake) rp_sdata <= fdat;
                        end
                        f_skv <= 1'b0;
                    end else if (f_q1) begin
                        f_skv <= 1'b1;
                        f_skd <= sa_q;
                    end
                    // retire on the accepted element
                    if (fv && frdy) begin
                        if (fi + 1'b1 == n_elems) begin
                            ci <= '0;
                            st <= C_RD;
                        end else fi <= fi + 1'b1;
                    end
                end
                // ---------- stream collect 16b ----------
                C_RD: begin
                    vn_mready <= (cmd_op == OP_VN);
                    rp_mready <= (cmd_op == OP_ROPE);
                    if ((cmd_op == OP_VN) ? vn_mvalid : rp_mvalid) begin
                        eng_swa <= dst_r + 15'(ci);
                        eng_swd <= (cmd_op == OP_VN) ? vn_mdata : rp_mdata;
                        eng_swe <= 1'b1;
                        if (ci + 1'b1 == n_elems) begin
                            vn_mready <= 1'b0; rp_mready <= 1'b0;
                            st <= DONE_S;
                        end else ci <= ci + 1'b1;
                    end
                end

                // ---------- generic preload loop ----------
                L_A: st <= L_W;
                L_W: st <= L_P;
                L_P: begin
                    case (ld_tgt)
                        LT_VNW: begin
                            vn_wwe <= 1'b1; vn_waddr <= ld_i;
                            vn_sdata <= sa_q;
                        end
                        LT_ROPET: begin
                            rp_twe <= 1'b1; rp_taddr <= ld_i[7:0];
                            rp_sdata <= sa_q;
                        end
                        LT_GB, LT_GA, LT_GDT: begin
                            gt_wwe <= 1'b1;
                            gt_wsel <= (ld_tgt == LT_GB) ? 2'd0 :
                                       (ld_tgt == LT_GA) ? 2'd1 : 2'd3;
                            gt_waddr <= ld_i[HB-1:0];
                            gt_wdata <= 18'(sa_q);
                        end
                        LT_GAA: begin
                            if (!ld_i[0]) begin
                                tmp16 <= unsigned'(sa_q);
                            end else begin
                                gt_wwe <= 1'b1;
                                gt_wsel <= 2'd2;
                                gt_waddr <= ld_i[HB:1];
                                gt_wdata <= {sa_q[1:0], tmp16};
                            end
                        end
                        LT_DK, LT_DQ, LT_DV: begin
                            dn_vwe <= 1'b1;
                            dn_vsel <= (ld_tgt == LT_DK) ? 2'd0 :
                                       (ld_tgt == LT_DQ) ? 2'd1 : 2'd2;
                            dn_vaddr <= ld_i[6:0];
                            // v transports as Q.QKV_F int16; the lossless
                            // <<(S_F-QKV_F)=<<5 to Q.S_F happens here (the
                            // 21-bit vec port exists for exactly this)
                            dn_vdata <= (ld_tgt == LT_DV)
                                        ? {sa_q, 5'b0} : 21'(sa_q);
                        end
                        LT_AQ: begin
                            at_qwe <= 1'b1; at_qaddr <= ld_i[7:0];
                            at_qdata <= sa_q;
                        end
                        LT_DDEC: dn_decay <= unsigned'(sa_q);
                        LT_DBET: dn_beta  <= unsigned'(sa_q);
                        default: ;
                    endcase
                    if (ld_i + 1'b1 == ld_n) begin
                        // phase chaining
                        ld_i <= '0;
                        case (ld_tgt)
                            LT_VNW, LT_ROPET: st <= DONE_S;
                            LT_GB: begin
                                ld_tgt <= LT_GA; ld_n <= 11'(LNH);
                                ld_src <= a1_dst; eng_sa <= a1_dst;
                                st <= L_A;
                            end
                            LT_GA: begin
                                ld_tgt <= LT_GAA; ld_n <= 11'(2*LNH);
                                ld_src <= a2_src; eng_sa <= a2_src;
                                st <= L_A;
                            end
                            LT_GAA: begin
                                ld_tgt <= LT_GDT; ld_n <= 11'(LNH);
                                ld_src <= a2_dst; eng_sa <= a2_dst;
                                st <= L_A;
                            end
                            LT_GDT: begin
                                gt_start <= 1'b1;
                                st <= RUN_W;
                            end
                            LT_DDEC: begin
                                ld_tgt <= LT_DBET; ld_n <= 11'd1;
                                ld_src <= {arg1[31], arg0[31:18]};
                                eng_sa <= {arg1[31], arg0[31:18]};
                                st <= L_A;
                            end
                            LT_DBET: begin
                                ld_tgt <= LT_DK; ld_n <= 11'd128;
                                ld_src <= a1_dst; eng_sa <= a1_dst;
                                st <= L_A;
                            end
                            LT_DK: begin
                                ld_tgt <= LT_DQ; ld_n <= 11'd128;
                                ld_src <= a1_src; eng_sa <= a1_src;
                                st <= L_A;
                            end
                            LT_DQ: begin
                                ld_tgt <= LT_DV; ld_n <= 11'd128;
                                ld_src <= src2_r; eng_sa <= src2_r;
                                st <= L_A;
                            end
                            LT_DV: begin
                                dn_start <= 1'b1;
                                dn_mready <= 1'b0;
                                st <= D_RDY;
                            end
                            LT_AQ: begin
                                at_start <= 1'b1;
                                at_mready <= 1'b0;
                                st <= D_RDY;
                            end
                            default: st <= DONE_S;
                        endcase
                    end else begin
                        ld_i <= ld_i + 1'b1;
                        eng_sa <= ld_src + 15'(ld_i) + 15'd1;
                        st <= L_A;
                    end
                end

                // ---------- gate run + store ----------
                RUN_W: if (gate_done_q || gt_done) st <= G_ST;
                G_ST: begin
                    eng_swa <= dst_r + 15'(gi);
                    eng_swd <= signed'(gi[HB] ? gt_decay[gi[HB-1:0]]
                                              : gt_beta[gi[HB-1:0]]);
                    eng_swe <= 1'b1;
                    if (gi == (GIW+1)'(2*LNH - 1)) st <= DONE_S;
                    else gi <= gi + 1'b1;
                end

                // ---------- 32b indexed collect (DNST/ATTN) ----------
                D_RDY: begin
                    if (cmd_op == OP_DNST) dn_mready <= 1'b1;
                    else                   at_mready <= 1'b1;
                    if ((cmd_op == OP_DNST) ? (dn_mvalid && dn_mready)
                                            : (at_mvalid && at_mready)) begin
                        logic signed [31:0] md;
                        logic [14:0] off;
                        md  = (cmd_op == OP_DNST) ? dn_mdata : at_mdata;
                        off = (cmd_op == OP_DNST) ? 15'(dn_midx)
                                                  : 15'(at_midx);
                        eng_swa <= dst_r + (off << 1);
                        eng_swd <= signed'(md[15:0]);
                        eng_swe <= 1'b1;
                        m_hi <= md[31:16];
                        dn_mready <= 1'b0;
                        at_mready <= 1'b0;
                        rcvd <= rcvd + 1'b1;
                        st <= D_HI;
                    end
                end
                D_HI: begin
                    eng_swa <= eng_swa + 15'd1;
                    eng_swd <= signed'(m_hi);
                    eng_swe <= 1'b1;
                    if (rcvd == n_col) st <= DONE_S;
                    else st <= D_RDY;
                end

                // ---------- conv run ----------
                CV_A: begin
                    if (cvi == arg0[25:13]) st <= CV_D;
                    else begin
                        eng_sa <= a1_src + 15'(cvi);
                        cw_ra <= arg0[12:0] + cvi;
                        cs_ra <= arg0[12:0] + cvi;
                        st <= CV_W;
                    end
                end
                CV_W:  st <= CV_W2;        // BRAM DOREG
                CV_W2: st <= CV_W3;        // per-bank fabric stage (cw/cs_q_p)
                CV_W3: st <= CV_P;         // registered bank mux settles
                CV_P: begin
                    cv_win0 <= signed'(cs_q[15:0]);
                    cv_win1 <= signed'(cs_q[31:16]);
                    cv_win2 <= signed'(cs_q[47:32]);
                    cv_win3 <= sa_q;
                    cv_w0 <= signed'(cw_q[15:0]);
                    cv_w1 <= signed'(cw_q[31:16]);
                    cv_w2 <= signed'(cw_q[47:32]);
                    cv_w3 <= signed'(cw_q[63:48]);
                    cv_ivalid <= 1'b1;
                    cs_wa <= arg0[12:0] + cvi;
                    cs_wd <= {unsigned'(sa_q), cs_q[47:16]};
                    cs_we <= 1'b1;
                    cvi <= cvi + 1'b1;
                    st <= CV_A;
                end
                CV_D: if (cvj == arg0[25:13]) st <= DONE_S;

                // ---------- conv weight/state load ----------
                CW_A: st <= CW_W;
                CW_W: st <= CW_P;
                CW_P: begin
                    logic [1:0] last_k;
                    last_k = (arg0[1:0] == 2'd0) ? 2'd3 : 2'd2;
                    tmp64[16 * wk +: 16] <= unsigned'(sa_q);
                    if (wk == last_k) begin
                        wk <= '0;
                        if (arg0[1:0] == 2'd0) begin
                            cw_we <= 1'b1;
                            cw_wa <= arg0[14:2] + wi;
                            cw_wd <= {unsigned'(sa_q), tmp64[47:0]};
                        end else begin
                            cs_we <= 1'b1;
                            cs_wa <= arg0[14:2] + wi;
                            cs_wd <= {unsigned'(sa_q), tmp64[31:0]};
                        end
                        if (wi + 1'b1 == arg0[27:15]) st <= DONE_S;
                        else begin
                            wi <= wi + 1'b1;
                            eng_sa <= eng_sa + 15'd1;
                            st <= CW_A;
                        end
                    end else begin
                        wk <= wk + 1'b1;
                        eng_sa <= eng_sa + 15'd1;
                        st <= CW_A;
                    end
                end
                CZ_W: begin
                    cs_we <= 1'b1;
                    cs_wa <= arg0[14:2] + wi;
                    cs_wd <= '0;
                    if (wi + 1'b1 == arg0[27:15]) st <= DONE_S;
                    else wi <= wi + 1'b1;
                end

                // ---------- KVAP ----------
                KQ_A: st <= KQ_W;
                KQ_W: st <= KQ_S;
                KQ_S: begin
                    s16q <= sa_q;             // register copy: BRAM CQ leg
                    st <= KQ_M;
                end
                KQ_M: begin
                    logic [15:0] av;
                    av = (s16q < 0) ? 16'(-s16q) : 16'(s16q);
                    if (av > kmax) kmax <= av;
                    if (ki == 9'd255) begin
                        eq <= '0;
                        st <= KQ_E;
                    end else begin
                        ki <= ki + 1'b1;
                        eng_sa <= (rnd ? a1_dst : a1_src)
                                  + 15'(ki) + 15'd1;
                        st <= KQ_A;
                    end
                end
                KQ_E: begin
                    logic [15:0] r;
                    r = 16'((32'(kmax) + (32'd1 << eq >> 1)) >> eq);
                    if (r > 16'd127) eq <= eq + 1'b1;
                    else begin
                        ki <= '0;
                        eng_sa <= rnd ? a1_dst : a1_src;
                        st <= K2_A;
                    end
                end
                K2_A: st <= K2_W;
                K2_W: st <= K2_S;
                K2_S: begin
                    s16q <= sa_q;             // register copy: BRAM CQ leg
                    st <= K2_B;
                end
                K2_B: begin
                    // narrow 16-bit quantize, bit-exact with
                    // clip(rshr64(x,eq), -127, 127) for int16 x, eq in [0,15]
                    logic [15:0] av;
                    logic [15:0] r16;
                    av = (s16q < 0) ? 16'(-s16q) : 16'(s16q);
                    r16 = 16'((32'(av) + (32'd1 << eq >> 1)) >> eq);
                    if (r16 > 16'd127) r16 = 16'd127;
                    kbyte <= (s16q < 0) ? 8'(-9'(r16)) : 8'(r16);
                    kb_i <= ki;
                    st <= K2_Q;
                end
                K2_Q: begin
                    krow[8 * kb_i +: 8] <= kbyte;
                    if (ki == 9'd255) st <= K_WR;
                    else begin
                        ki <= ki + 1'b1;
                        eng_sa <= (rnd ? a1_dst : a1_src)
                                  + 15'(ki) + 15'd1;
                        st <= K2_A;
                    end
                end
                K_WR: begin
                    kv_we <= 1'b1;
                    kv_waddr <= {kvhead_r, rnd,
                                 tcnt_bank[kv_layer_r][kvhead_r][8:0]};
                    kv_wrow <= krow;
                    kv_wexp <= 8'(signed'({4'b0, eq}) - signed'({3'b0, kv_expbias}));
                    if (!rnd) begin
                        rnd <= 1'b1;
                        ki <= '0; eq <= '0; kmax <= '0;
                        eng_sa <= a1_dst;
                        st <= KQ_A;
                    end else begin
                        tcnt_inc <= 1'b1;  // CSR: +1 tcnt_bank[kv_layer_r][kvhead_r]
                        st <= DONE_S;
                    end
                end

                // ---------- vec_alu ----------
                A_RUN: if (alu_done) begin
                    if (arg0[3:0] == 4'd0) eout_q <= alu_eout;
                    st <= DONE_S;
                end

                // ---------- DNZ ----------
                Z_W: begin
                    dnz_we <= 1'b1;
                    dnz_addr <= zi;
                    if (zi == 7'd127) st <= DONE_S;
                    else zi <= zi + 1'b1;
                end

                // ----------------------------------------------------
                DONE_S: begin
                    busy <= 1'b0;
                    cmd_cnt <= cmd_cnt + 1'b1;
                    st <= IDLE;
                end
                default: st <= IDLE;
            endcase
        end
    end

    // ==================================================================
    // S6 burst shim (RUNG3_SPEC R2/R3/R4).  A SHALLOW wrapper — all of
    // its state lives in its own instance, none of it in the dense core —
    // that hands the mux ONE registered write bundle (bw_we/bw_addr/
    // bw_data) and ONE registered read leg (br_en/br_addr), and captures
    // sa_q into a plain flip-flop D input (R3: nothing combinational may
    // hang off sa_q/sb_q).
    // ==================================================================
    wire        bw_we, br_en;
    wire [14:0] bw_addr, br_addr;
    wire [15:0] bw_data;

    layer_axib_shim u_axib (
        .aclk(aclk), .rstn(rstn_i),
        .s_axib_awid(s_axib_awid), .s_axib_awaddr(s_axib_awaddr),
        .s_axib_awlen(s_axib_awlen), .s_axib_awsize(s_axib_awsize),
        .s_axib_awburst(s_axib_awburst), .s_axib_awvalid(s_axib_awvalid),
        .s_axib_awready(s_axib_awready),
        .s_axib_wdata(s_axib_wdata), .s_axib_wstrb(s_axib_wstrb),
        .s_axib_wlast(s_axib_wlast), .s_axib_wvalid(s_axib_wvalid),
        .s_axib_wready(s_axib_wready),
        .s_axib_bid(s_axib_bid), .s_axib_bresp(s_axib_bresp),
        .s_axib_bvalid(s_axib_bvalid), .s_axib_bready(s_axib_bready),
        .s_axib_arid(s_axib_arid), .s_axib_araddr(s_axib_araddr),
        .s_axib_arlen(s_axib_arlen), .s_axib_arsize(s_axib_arsize),
        .s_axib_arburst(s_axib_arburst), .s_axib_arvalid(s_axib_arvalid),
        .s_axib_arready(s_axib_arready),
        .s_axib_rid(s_axib_rid), .s_axib_rdata(s_axib_rdata),
        .s_axib_rresp(s_axib_rresp), .s_axib_rlast(s_axib_rlast),
        .s_axib_rvalid(s_axib_rvalid), .s_axib_rready(s_axib_rready),
        .core_busy(busy), .core_hw_we(hw_we),
        .bw_we(bw_we), .bw_addr(bw_addr), .bw_data(bw_data),
        .br_en(br_en), .br_addr(br_addr), .sa_q(sa_q));

    // ==================================================================
    // scratch port muxes
    //
    // Rung 3 turns the 3:1 read-address mux and the 3:1 write mux into
    // 4:1 muxes with a TWO-bit select {busy, sub} — 4 data + 2 selects =
    // 6 inputs = exactly one LUT6 per muxed bit, no added logic levels
    // (S6).  `busy` is the hard priority bit, which is what makes a burst
    // arriving mid-command structurally harmless.  With br_en/bw_we low
    // (no burst in flight) every arm reduces to the pre-rung-3 mux, so
    // AXI-Lite SPTR/SWIN behaviour is bit-identical.
    //   sub == 1 && busy  -> vec_alu owns the ports
    //   sub == 0 && busy  -> dispatcher owns the ports
    //   sub == 1 && !busy -> burst window
    //   sub == 0 && !busy -> AXI-Lite SWIN
    // bw_grant hands the idle write port to the AXI-Lite SWIN write on
    // the (illegal-by-contract) collision cycle; the shim then holds its
    // registered bundle and retries, so no burst beat is ever lost.
    // ==================================================================
    wire cmd_is_alu = (cmd_op == OP_ALU);
    wire alu_owns   = busy && cmd_is_alu;
    wire bw_grant   = bw_we && !hw_we;
    wire sa_sub     = busy ? cmd_is_alu : br_en;
    wire sw_sub     = busy ? cmd_is_alu : bw_grant;

    assign sa_addr = busy ? (sa_sub ? alu_aa : eng_sa)
                          : (sa_sub ? br_addr : sptr);
    assign sb_addr = alu_owns ? alu_ba : '0;
    assign sw_en   = busy ? (sw_sub ? alu_we : eng_swe)
                          : (sw_sub ? 1'b1 : hw_we);
    assign sw_addr = busy ? (sw_sub ? alu_wa : eng_swa)
                          : (sw_sub ? bw_addr : hw_addr);
    assign sw_data = busy ? (sw_sub ? alu_wd : eng_swd)
                          : (sw_sub ? signed'(bw_data) : signed'(hw_data));

`ifndef SYNTHESIS
    // HOST CONTRACT (see the header): AXI-Lite SWIN and the burst window
    // are mutually exclusive.  A SWIN *read* while a burst read owns
    // sa_addr would return the burst's word, so catch it here rather than
    // debug it on silicon.  SWIN *writes* are arbitrated in hardware
    // (bw_grant above) and are therefore only reported, not fatal.
    always_ff @(posedge aclk) begin
        if (rstn_i && br_en && s_axil_arvalid && s_axil_arready
            && s_axil_araddr[11:2] == 10'h006)
            $fatal(1, "layer_chan: AXIL SWIN read during a burst read");
    end
`endif

endmodule

/* verilator lint_off DECLFILENAME */
// The two modules below are the S6 shim.  They live in this file on
// purpose: rtl/layer_chan.sv is the agent-C ownership boundary for rung 3
// (RUNG3_SPEC "File ownership"), and adding a file would mean editing
// synth/scripts/create_project.tcl, which belongs to agent A.
// ======================================================================
// layer_axib_skid: 1-deep skid buffer.  s_ready is a pure REGISTER
// output, so nothing inside the shim hangs off the SmartConnect's *VALID
// nets and nothing outside it hangs off the shim's *READY nets.
// ======================================================================
module layer_axib_skid #(parameter int W = 8) (
    input  wire          clk,
    input  wire          rstn,
    input  wire  [W-1:0] s_data,
    input  wire          s_valid,
    output wire          s_ready,
    output logic [W-1:0] m_data,
    output logic         m_valid,
    input  wire          m_ready
);
    logic [W-1:0] sk_data;
    logic         sk_valid;

    assign s_ready = !sk_valid;

    always_ff @(posedge clk) begin
        if (!rstn) begin
            m_valid  <= 1'b0;
            sk_valid <= 1'b0;
        end else begin
            // accepted while the output stage is stalled -> park in the skid
            if (s_valid && !sk_valid && m_valid && !m_ready) begin
                sk_data  <= s_data;
                sk_valid <= 1'b1;
            end
            // output stage free -> drain the skid first, else take the input
            if (!m_valid || m_ready) begin
                if (sk_valid) begin
                    m_data   <= sk_data;
                    m_valid  <= 1'b1;
                    sk_valid <= 1'b0;
                end else begin
                    m_data  <= s_data;
                    m_valid <= s_valid;      // s_ready == 1 in this arm
                end
            end
        end
    end
endmodule

// ======================================================================
// layer_axib_shim: the S6 burst window's AXI4 slave (RUNG3_SPEC R2/R3/R4).
//
// SHAPE (R2): skid buffers on AW/W/AR, one write-burst and one read-burst
// in flight, and a single registered handoff to layer_chan's scratch
// muxes — (bw_we, bw_addr, bw_data) for writes, (br_en, br_addr) for
// reads.  Every one of those five is a (* keep *) flip-flop whose only
// consumer is the mux, so the mux leg is register -> LUT6 -> BRAM.
//
// READ (R3): the burst read presents br_addr on the scratch read port
// exactly the way SPTR does for the SWIN CSR read, and captures sa_q into
// a 4-deep register FIFO whose write-data pin IS sa_q — no mux, no gate,
// no arithmetic on sa_q, only a decoded clock enable.  A credit counter
// (occ) never lets more beats be issued than the FIFO can hold, so the
// unstoppable 1-cycle BRAM read is always absorbed; depth 4 covers the
// 3-cycle issue->pop->credit loop, i.e. 1 word/cycle sustained.
//
// WRITE: one 32-bit beat = one 16-bit scratch word, data in the LOW half
// (see the layer_chan header).  The registered bundle is held until the
// mux actually grants it, so an AXI-Lite SWIN write colliding on the same
// cycle costs one cycle of stall, never a lost beat.
//
// ERRORS (R8): busy is sampled when the burst is accepted and again on
// every beat.  A blocked burst is drained at full rate, writes nothing,
// reads nothing (br_en stays low), and answers BRESP/RRESP = SLVERR.
// Nothing about a running command is disturbed either way — the scratch
// muxes give `busy` hard priority.
// ======================================================================
module layer_axib_shim (
    input  wire         aclk,
    input  wire         rstn,

    input  wire [0:0]   s_axib_awid,
    input  wire [16:0]  s_axib_awaddr,
    input  wire [7:0]   s_axib_awlen,
    input  wire [2:0]   s_axib_awsize,
    input  wire [1:0]   s_axib_awburst,
    input  wire         s_axib_awvalid,
    output wire         s_axib_awready,
    input  wire [31:0]  s_axib_wdata,
    input  wire [3:0]   s_axib_wstrb,
    input  wire         s_axib_wlast,
    input  wire         s_axib_wvalid,
    output wire         s_axib_wready,
    output logic [0:0]  s_axib_bid,
    output logic [1:0]  s_axib_bresp,
    output logic        s_axib_bvalid,
    input  wire         s_axib_bready,
    input  wire [0:0]   s_axib_arid,
    input  wire [16:0]  s_axib_araddr,
    input  wire [7:0]   s_axib_arlen,
    input  wire [2:0]   s_axib_arsize,
    input  wire [1:0]   s_axib_arburst,
    input  wire         s_axib_arvalid,
    output wire         s_axib_arready,
    output logic [0:0]  s_axib_rid,
    output wire [31:0]  s_axib_rdata,
    output wire [1:0]   s_axib_rresp,
    output wire         s_axib_rlast,
    output wire         s_axib_rvalid,
    input  wire         s_axib_rready,

    // ---- core handoff: register -> mux, both directions ----
    input  wire         core_busy,     // engine owns the scratch ports
    input  wire         core_hw_we,    // AXI-Lite SWIN write this cycle
    output wire         bw_we,
    output wire [14:0]  bw_addr,
    output wire [15:0]  bw_data,
    output wire         br_en,
    output wire [14:0]  br_addr,
    input  wire signed [15:0] sa_q     // scratch read data (FF capture ONLY)
);
    localparam logic [1:0] W_IDLE = 2'd0, W_DATA = 2'd1, W_RESP = 2'd2;
    localparam logic [1:0] RESP_OK = 2'b00, RESP_SLVERR = 2'b10;
    localparam int RDEPTH = 4;          // read FIFO entries (power of two)

    /* verilator lint_off UNUSEDSIGNAL */
    wire [17:0] unused_axib = {s_axib_wdata[31:16], s_axib_wstrb[3:2]};
    /* verilator lint_on UNUSEDSIGNAL */

    // ------------------------------------------------------------------
    // the five registers the scratch muxes see
    // ------------------------------------------------------------------
    (* keep = "true" *) logic        bw_we_r;
    (* keep = "true" *) logic [14:0] bw_addr_r;
    (* keep = "true" *) logic [15:0] bw_data_r;
    (* keep = "true" *) logic        br_en_r;
    (* keep = "true" *) logic [14:0] br_addr_r;
    assign bw_we   = bw_we_r;
    assign bw_addr = bw_addr_r;
    assign bw_data = bw_data_r;
    assign br_en   = br_en_r;
    assign br_addr = br_addr_r;

    // ==================================================================
    // write channel
    // ==================================================================
    wire [23:0] aw_m;                   // {awid, awaddr[16:2], awlen}
    wire        aw_mv;
    wire        aw_mr;
    layer_axib_skid #(.W(24)) u_aw (
        .clk(aclk), .rstn(rstn),
        .s_data({s_axib_awid, s_axib_awaddr[16:2], s_axib_awlen}),
        .s_valid(s_axib_awvalid), .s_ready(s_axib_awready),
        .m_data(aw_m), .m_valid(aw_mv), .m_ready(aw_mr));

    wire [18:0] w_m;                    // {wlast, wstrb[1:0], wdata[15:0]}
    wire        w_mv;
    wire        w_mr;
    layer_axib_skid #(.W(19)) u_w (
        .clk(aclk), .rstn(rstn),
        .s_data({s_axib_wlast, s_axib_wstrb[1:0], s_axib_wdata[15:0]}),
        .s_valid(s_axib_wvalid), .s_ready(s_axib_wready),
        .m_data(w_m), .m_valid(w_mv), .m_ready(w_mr));

    logic [1:0]  wst;
    logic [14:0] wa_ptr;                // running scratch word address
    logic [8:0]  wbeats;                // beats left in this burst
    logic        wblk;                  // burst arrived while busy
    logic        werr;                  // sticky: a beat did not land
    logic        bw_pend;               // bundle register holds a live beat

    // The mux writes when (!core_busy && bw_we_r && !core_hw_we).  Mirror
    // that EXACTLY: take the beat when it landed, or when core_busy made
    // it impossible (-> SLVERR); hold and retry on a SWIN collision.
    wire bw_take = bw_pend && (core_busy || !core_hw_we);
    wire bw_free = !bw_pend || bw_take;
    assign w_mr  = (wst == W_DATA) && bw_free;
    wire   w_take = w_mv && w_mr;
    assign aw_mr = (wst == W_IDLE) && !s_axib_bvalid;

    always_ff @(posedge aclk) begin
        if (!rstn) begin
            wst <= W_IDLE;
            bw_pend <= 1'b0; bw_we_r <= 1'b0;
            wblk <= 1'b0; werr <= 1'b0;
            s_axib_bvalid <= 1'b0; s_axib_bresp <= RESP_OK;
        end else begin
            // ---- the registered write bundle (R4) ----
            if (bw_free) begin
                bw_pend <= w_take;
                bw_we_r <= w_take && (w_m[17:16] == 2'b11) && !wblk;
                if (w_take) begin       // hold the leg stable between beats
                    bw_addr_r <= wa_ptr;
                    bw_data_r <= w_m[15:0];
                end
            end
            // a beat consumed while the engine owns the port never landed
            if (bw_take && core_busy) werr <= 1'b1;

            case (wst)
                // aw_mr includes !s_axib_bvalid: never latch a new descriptor
                // (incl. bid) while the previous B response is still pending
                // — without it a back-to-back burst re-executes the same AW
                // (found by the burst-fabric B-vs-AW accounting check).
                W_IDLE: if (aw_mv && aw_mr) begin
                    wa_ptr <= aw_m[22:8];
                    wbeats <= 9'(aw_m[7:0]) + 9'd1;
                    s_axib_bid <= aw_m[23];
                    wblk <= core_busy;
                    werr <= core_busy;
                    wst  <= W_DATA;
                end
                W_DATA: if (w_take) begin
                    wa_ptr <= wa_ptr + 15'd1;
                    wbeats <= wbeats - 9'd1;
                    if (wbeats == 9'd1) wst <= W_RESP;
                end
                W_RESP: if (!bw_pend && !s_axib_bvalid) begin
                    s_axib_bvalid <= 1'b1;
                    s_axib_bresp  <= werr ? RESP_SLVERR : RESP_OK;
                    wst <= W_IDLE;
                end
                default: wst <= W_IDLE;
            endcase

            if (s_axib_bvalid && s_axib_bready) s_axib_bvalid <= 1'b0;
        end
    end

    // ==================================================================
    // read channel
    // ==================================================================
    wire [23:0] ar_m;                   // {arid, araddr[16:2], arlen}
    wire        ar_mv;
    wire        ar_mr;
    layer_axib_skid #(.W(24)) u_ar (
        .clk(aclk), .rstn(rstn),
        .s_data({s_axib_arid, s_axib_araddr[16:2], s_axib_arlen}),
        .s_valid(s_axib_arvalid), .s_ready(s_axib_arready),
        .m_data(ar_m), .m_valid(ar_mv), .m_ready(ar_mr));

    logic       rd_busy;                // a read burst is in flight
    logic [8:0] rbeats;                 // addresses still to issue
    logic       rblk;                   // this burst answers SLVERR
    logic       q_v, q_last, q_blk;     // the BRAM-latency stage

    logic signed [15:0] fdat [RDEPTH];  // capture FIFO (D pin == sa_q)
    logic               flast [RDEPTH];
    logic               fblk  [RDEPTH];
    logic [1:0]         fwp, frp;
    logic [2:0]         fcnt;           // entries held
    logic [2:0]         occ;            // issued but not yet handed out

    assign ar_mr = !rd_busy;
    assign s_axib_rvalid = (fcnt != 3'd0);
    assign s_axib_rdata  = {16'b0, unsigned'(fdat[frp])};
    assign s_axib_rlast  = flast[frp];
    assign s_axib_rresp  = fblk[frp] ? RESP_SLVERR : RESP_OK;
    wire   rpop = s_axib_rvalid && s_axib_rready;
    wire   radv = rd_busy && (rbeats != 9'd0) && (occ != 3'(RDEPTH));

    always_ff @(posedge aclk) begin
        if (!rstn) begin
            rd_busy <= 1'b0; rblk <= 1'b0; br_en_r <= 1'b0;
            q_v <= 1'b0;
            fwp <= '0; frp <= '0; fcnt <= '0; occ <= '0;
        end else begin
            // ---- address issue (the registered read leg) ----
            q_v <= radv;
            if (radv) begin
                q_last <= (rbeats == 9'd1);
                q_blk  <= rblk || core_busy;
                rbeats <= rbeats - 9'd1;
                if (br_en_r) br_addr_r <= br_addr_r + 15'd1;
                if (rbeats == 9'd1) br_en_r <= 1'b0;
            end
            // a command starting mid-burst takes the port away: stop
            // driving sa_addr and fail the rest of the burst.
            if (rd_busy && core_busy) begin
                rblk    <= 1'b1;
                br_en_r <= 1'b0;
            end

            // ---- capture FIFO: sa_q -> FF D pin, decoded CE only (R3) ----
            if (q_v) begin
                fdat[fwp]  <= sa_q;
                flast[fwp] <= q_last;
                fblk[fwp]  <= q_blk;
                fwp        <= fwp + 2'd1;
            end
            if (rpop) frp <= frp + 2'd1;

            case ({q_v, rpop})
                2'b10: fcnt <= fcnt + 3'd1;
                2'b01: fcnt <= fcnt - 3'd1;
                default: ;
            endcase
            case ({radv, rpop})
                2'b10: occ <= occ + 3'd1;
                2'b01: occ <= occ - 3'd1;
                default: ;
            endcase

            // ---- burst accept / retire ----
            if (!rd_busy) begin
                if (ar_mv) begin
                    rd_busy   <= 1'b1;
                    rbeats    <= 9'(ar_m[7:0]) + 9'd1;
                    s_axib_rid <= ar_m[23];
                    rblk      <= core_busy;
                    br_en_r   <= !core_busy;
                    br_addr_r <= ar_m[22:8];
                end
            end else if (rpop && s_axib_rlast) begin
                rd_busy <= 1'b0;
            end
        end
    end

`ifndef SYNTHESIS
    // window / burst-shape contract (RUNG3_SPEC S6, S7).  The 17-bit
    // address makes the START word structurally in-window; what is not
    // structural is 4-byte alignment, the beat size, INCR, and a burst
    // running off the end of the 32768-word window.
    always_ff @(posedge aclk) if (rstn) begin
        if (s_axib_awvalid && s_axib_awready) begin
            if (s_axib_awaddr[1:0] != 2'b00)
                $fatal(1, "s_axib: unaligned AWADDR %04h", s_axib_awaddr);
            if (s_axib_awsize != 3'd2)
                $fatal(1, "s_axib: AWSIZE %0d, only 4-byte beats", s_axib_awsize);
            if (s_axib_awburst != 2'b01)
                $fatal(1, "s_axib: AWBURST %0d, only INCR", s_axib_awburst);
            if (({1'b0, s_axib_awaddr[16:2]} + 16'(s_axib_awlen)) > 16'd32767)
                $fatal(1, "s_axib: write burst w=%0d len=%0d runs past the window",
                       s_axib_awaddr[16:2], s_axib_awlen);
        end
        if (s_axib_arvalid && s_axib_arready) begin
            if (s_axib_araddr[1:0] != 2'b00)
                $fatal(1, "s_axib: unaligned ARADDR %04h", s_axib_araddr);
            if (s_axib_arsize != 3'd2)
                $fatal(1, "s_axib: ARSIZE %0d, only 4-byte beats", s_axib_arsize);
            if (s_axib_arburst != 2'b01)
                $fatal(1, "s_axib: ARBURST %0d, only INCR", s_axib_arburst);
            if (({1'b0, s_axib_araddr[16:2]} + 16'(s_axib_arlen)) > 16'd32767)
                $fatal(1, "s_axib: read burst w=%0d len=%0d runs past the window",
                       s_axib_araddr[16:2], s_axib_arlen);
        end
        if (s_axib_wvalid && s_axib_wready
            && s_axib_wstrb[1:0] != 2'b00 && s_axib_wstrb[1:0] != 2'b11)
            $fatal(1, "s_axib: WSTRB %04b - a 16-bit word has no partial write",
                   s_axib_wstrb);
        if (w_take && (w_m[18] != (wbeats == 9'd1)))
            $fatal(1, "s_axib: WLAST disagrees with AWLEN (%0d beats left)",
                   wbeats);
        if (q_v && fcnt == 3'(RDEPTH))
            $fatal(1, "s_axib: read capture FIFO overflow");
    end
`endif

endmodule

// ======================================================================
// layer_topk32 — rung 4 S5 (docs/RUNG4_SPEC.md).  A 32-entry sorted
// insertion list over the elements the AMAX32 comparator sees, so the
// host gets the top-32 candidate set for sampling with ZERO extra DDR
// traffic and ZERO extra passes over the vocabulary.
//
// It lives in this file for the same reason the S6 shim does: adding an
// RTL file would mean editing synth/scripts/create_project.tcl, which is
// not this agent's to touch.  Nothing of it leaks into the dense core —
// every register is inside this instance and its only inputs are one
// registered 51-bit bundle plus four control bits.
//
// FEED.  bun = {we, val[31:0], idx[17:0]} is registered inside vec_alu AT
// the AMAX32 compare site, so this block starts from a flip-flop and adds
// nothing to the ALU's own timing cone.  One element per cycle, II=1, no
// backpressure (there is nothing to stall: the insert is combinational
// into the entry registers).
//
// ORDER.  ent[] is kept sorted value-DESCENDING.  gt[i] = "the arrival
// beats entry i" is STRICTLY greater, so a tie keeps the incumbent; under
// the ascending index scan the incumbent always has the lower index, which
// is exactly np.argmax / ref/gen_layer_script.py first-wins.  Empty slots
// live at the tail and accept anything, so gt[] is monotone
// (gt[i] -> gt[i+1]) and p = min{i : gt[i]} is the unique insertion point.
//
// RECURRENCE (the S5 timing rule: 1 compare + 1 mux).  Per entry:
//     CE   = we & gt[i]                      (comparator -> clock enable)
//     D    = gt[i-1] ? ent[i-1] : new        (ONE 2:1 mux)
// so the register-to-register path is  ent[] -> comparator -> mux -> ent[]
// and NOTHING is chained across entries: gt[i] and gt[i-1] are computed in
// parallel from the same registered arrival.  No priority encoder, no
// prefix chain, no 32-input anything.
//
// STATUS.
//   count     = valid entries, saturating at 32.
//   complete  = registered (!amax_busy && !we): "no AMAX32 command is in
//               flight AND no sample is being presented".  amax_busy is
//               layer_chan's own busy&&ALU&&aop10, which stays high two
//               cycles past the LAST exported sample (vec_alu retires an
//               op-10 at its capture stage, the export register adds one,
//               and DONE_S adds one more), so `complete` can only rise
//               after the final insert has been clocked in.  The !we term
//               makes that self-evident rather than argued.
//   overflow  = sticky, set when an element is REJECTED (!gt[31]) with a
//               value EQUAL to entry[31]: the top-32 set is then not
//               unique by value alone and a host cross-check that breaks
//               ties differently may legitimately differ.  Not an error.
//
// RESET.  The fresh flag (ALU aop 10 with p0[0]=1) clears list, count,
// overflow and ptr — and NOTHING else does, so a vocabulary scanned as N
// chained AMAX32 chunks accumulates into one top-32.  fresh leads the
// first sample of its own scan by 4 cycles, and the previous scan's last
// sample by more than that, so the clear can never race a sample; it wins
// anyway (it is the first arm of the always_ff).
//
// READBACK.  sel is a registered 32:1 mux updated from the NEXT ptr, so it
// is always in step with ptr: after any ptr event (write or the TK_IDX
// auto-increment) both land on the same edge and the AXI-Lite slave, which
// is single-outstanding (arready = !rvalid), cannot present the next read
// before the following cycle.
// ======================================================================
module layer_topk32 (
    input  wire         clk,
    input  wire         rstn,
    input  wire [50:0]  bun,        // {we, val[31:0], idx[17:0]} REGISTERED
    input  wire         fresh,      // AMAX32 fresh flag — the ONLY reset
    input  wire         amax_busy,  // an AMAX32 command is in flight
    input  wire         ptr_we,     // TK_PTR write
    input  wire [4:0]   ptr_wd,
    input  wire         ptr_adv,    // TK_IDX read: ptr++
    output logic [4:0]  ptr,
    output logic [5:0]  cnt,        // 0..32
    output logic        complete,
    output logic        ovf,
    output wire [31:0]  sel_val,    // entry[ptr]
    output wire [17:0]  sel_idx
);
    localparam int K = 32;

    // entry word: {valid, val[31:0], idx[17:0]}
    logic [50:0] ent [K];

    wire               in_we  = bun[50];
    wire signed [31:0] in_val = signed'(bun[49:18]);
    wire [50:0]        in_ent = {1'b1, bun[49:0]};

    logic [K-1:0] gt;
    always_comb
        for (int i = 0; i < K; i++)
            gt[i] = !ent[i][50] || (in_val > signed'(ent[i][49:18]));

    // readback cursor: mux on the NEXT pointer so sel and ptr move together
    wire [4:0] ptr_nxt = ptr_we  ? ptr_wd
                       : ptr_adv ? (ptr + 5'd1)
                                 : ptr;
    logic [49:0] sel;               // {val, idx} of entry[ptr] (no vld: the
    assign sel_val = sel[49:18];    // host loops i < count instead)
    assign sel_idx = sel[17:0];

    always_ff @(posedge clk) begin
        if (!rstn) begin
            for (int i = 0; i < K; i++) ent[i] <= '0;
            cnt      <= '0;
            ovf      <= 1'b0;
            ptr      <= '0;
            sel      <= '0;
            complete <= 1'b1;
        end else begin
            // ---- the list ----
            if (fresh) begin
                for (int i = 0; i < K; i++) ent[i] <= '0;
                cnt <= '0;
                ovf <= 1'b0;
                ptr <= '0;
            end else if (in_we) begin
                if (gt[0]) ent[0] <= in_ent;
                for (int i = 1; i < K; i++)
                    if (gt[i]) ent[i] <= gt[i-1] ? ent[i-1] : in_ent;
                if (cnt != 6'd32) cnt <= cnt + 6'd1;
                // a rejected element that TIED the last entry
                if (!gt[K-1] && (in_val == signed'(ent[K-1][49:18])))
                    ovf <= 1'b1;
            end

            // ---- host cursor (never touched by the datapath) ----
            if (!fresh && (ptr_we || ptr_adv)) ptr <= ptr_nxt;
            sel <= fresh ? 50'd0 : ent[ptr_nxt][49:0];

            // ---- no AMAX32 in flight, nothing being inserted ----
            complete <= !amax_busy && !in_we;
        end
    end
endmodule
/* verilator lint_on DECLFILENAME */

`default_nettype wire
