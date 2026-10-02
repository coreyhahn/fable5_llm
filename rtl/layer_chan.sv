// layer_chan: stage-3 layer-orchestration engine. A 64Kx16 scratchpad +
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
//   0x14 SPTR    RW scratch word pointer [15:0]
//   0x18 SWIN    W  scratch[SPTR]=d[15:0]; SPTR++
//                R  scratch[SPTR]; SPTR++   (idle only)
//   0x1C EOUT    R  last ALU DYNQ8 exponent [3:0]
//   0x20 TCNT    RW {3'b0, T1[12:0], 3'b0, T0[12:0]} KV append counters
//                   (kvheads 0/1; kvheads 2/3 are at 0x60 TCNT2 — G3.4).
//                   S2: 13 bits, indexed by LAYER.kv_layer (B15.2).
//   0x24 IDENT   R  0xFAB1E5A0
//   0x28 AMAXI   R  ALU AMAX32 running argmax index [17:0]
//   0x2C AMAXV   R  ALU AMAX32 running max value (int32)
//   0x30 LAYER   RW {18'b0, cv_slot[13:12], 1'b0, kv_layer[10:8], 3'b0,
//                    kv_slot[4:3], 1'b0, dn_slot[1:0]}   CACHE-slot select
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
//
// ---- G3.1 (SEQ_ISA v2.0): the DeltaNet scalar-pointer base pair --------
//   0x5C DNSB      RW {a_dec_base[31:16], a_beta_base[15:0]}
// DNST's two SCALAR pointers used to fill ARG0; v2.0 takes them from here
// as a_beta = a_beta_base + head and a_dec = a_dec_base + head (two 16-bit
// adds with a 5-bit addend, in the DNST decode, off the lane datapath).
// Written ONCE PER LAYER BODY by one CSRWR, not once per command, because
// both pointers are affine in the head with stride 1 from a per-body base
// (spec 4.3 S3).  Host mirror: sw/hwmap.py L_DNSB.
// ---- S2 (SEQ_ISA v2.1 B15.3): the state-DMA CSRs ---------------------
//   0x64 SB_DN     RW DN region base >> 16   (18 bits used)
//   0x68 SB_KV     RW KV region base >> 16
//   0x6C SB_CV     RW conv region base >> 16
//   0x70 SDMA      RW R: {busy_dma[31], queued[30:28], last_kind[27:26],
//                         last_slot[25], 17'b0, err[7:0]}
//                     W: any write clears err (and err_op if it was set by
//                        E_DMA_AXI)
//   0x74 SDMA_CYC  R  cycles while busy_dma; ANY write clears it (LCYC's
//                     twin for the DMA lane)
// STATUS (0x04) bit 0 is busy_any = busy_cmp | busy_dma; the CMD accept
// gate is busy_cmp ALONE; cmd_cnt increments when an SLD/SST is ENQUEUED;
// LCYC counts busy_cmp cycles only (spec A1.4).
//
// B15.4 error codes — STATUS.err_op is set and SDMA.err carries the code
// (a different namespace from seq_unit's err_code: these are the LAYER's):
//   0x01 E_ENV        a compute command's field envelope refused (cmd_env_bad)
//   0x02 E_LAYER      a LAYER slot field above 1 at a compute dispatch
//   0x10 E_DMA_BASE   SB_<kind> is 0 at dispatch of an SLD/SST
//   0x11 E_DMA_RANGE  kind 3; layer/head outside the kind's range; DN or CV
//                     head != 0; arg1/arg2 != 0; a KV TCNT above 4096; a
//                     KVAP/ATTN kvhead that differs from the slot's tag;
//                     CONVW sel 0/1 (retired — conv blocks arrive by SLD)
//   0x12 E_DMA_AXI    any SLVERR/DECERR on the transfer — raised at
//                     completion, STICKY with err_op until the host writes
//                     SDMA (the next compute dispatch does NOT clear it)
//   0x13 E_DMA_COLD   a compute command names a slot with no completed load
//                     (or DNZ/CONVZ) since the slot's last SST, or reset
//
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
// LAYER STATE IN DDR (S2, spec 2026-09-04 state-spill §3-§5).  G3.4's
// banking — 24 DN banks, 8 KV banks, 24 conv banks, 928 of 960 URAM —
// is RETIRED: the model's state now lives in DDR and this engine keeps a
// TWO-SLOT cache per kind (DN 2 x 29 URAM, KV 2 x 58 + two exponent
// memories, conv 2 x 4), filled and drained by the SLD/SST commands on a
// second, in-order DMA lane.  LAYER selects a CACHE SLOT per kind, never a
// physical layer; the layer identity lives only in SLD/SST.  Each KV slot
// carries a hardware TAG {layer[2:0], kvhead[1:0]} latched by the SLD that
// filled it, and KVAP/ATTN index tcnt_bank[8][4] through that tag (spec
// A1.3); host TCNT/TCNT2 access is indexed by LAYER.kv_layer.
// Two fences, in hardware (spec §5.4):
//   F1  a compute command whose slot has an SLD queued or in flight — or
//       ANY transfer in flight — stalls at dispatch; a slot with no
//       completed load since its last SST is refused E_DMA_COLD.
//   F2  a transfer at the head of the DMA queue waits while a compute
//       command holds its slot.
// The `-G SDMA_NOFENCE=1` build parameter bypasses F1.  It is a TESTBENCH
// KNOB (tb/Makefile's tb_layer_sdma_nofence, the RED control that proves
// the fence); 0 IS WHAT SHIPS and layer_chan_ipi.v never overrides it.
//
// ---- 16-bit scratch addressing (G3.1, SEQ_ISA v2.0) ------------------
// The scratchpad is 64K words and every scratch address field below is 16
// bits.  THERE ARE NO SCATTERED BITS ANYWHERE:
//
//   ARG1 on EVERY command carries the pair {hi[31:16], lo[15:0]}.
//   ARG2 on GATE and DNST uses that SAME pair layout.
//   ARG2 on ALU is {dst[31:16], p0[15:0]}; cfg_p0 is SEVENTEEN bits, so
//        its top bit is the ONE relocation in the whole re-encoding and
//        lives at arg0[18], above the count.
//   ARG0 on GATE is just dst, arg0[15:0].
//   ARG0 on DNST is {spare[31:5], head[4:0]} — its two scalar pointers
//        moved to the DNSB CSR (0x5C) as base + head.  69 of 96 bits.
//
// R-b's {hi[27:14], lo[13:0]} + lo[14]@28 + hi[14]@29 scatter existed for
// exactly one reason: to keep every frozen pre-R-b stream (all addresses
// < 16384) replaying bit-identically.  The 9B geometry has no frozen
// stream to preserve and DNST had no 16th spare bit to borrow — it used 94
// of its 96 arg bits.  build_034/build_035 still run SEQ_ISA v1.7 from
// their own pre-G3 checkout; THIS RTL decodes v2.0 only.
//
// Commands (opcode, args):
//   1 VN    arg0={outf[13:10],inf[9:6],nlog2[5:2],mode[1:0]}
//           arg1={dst[31:16],src[15:0]}        n=1<<nlog2 in/out
//           arg2={xrf_k[3:1],eps[0]}           eps=1 + mode==2 selects
//           EPS-NORM (SEQ gated RMSNorm); k = XRF[arg2[3:1]][5:0].
//           arg2==0 is the legacy behaviour.
//   2 VNW   arg0=len[12:0]; arg1=src           vecnorm wbuf load
//           (v2.0: 13 bits hold 4096 DIRECTLY, so there is NO
//            0-encodes-the-top escape any more and 0 means 0.  G3.2 widened
//            the DATAPATH to match: the wbuf is 4096 deep and vn_waddr is
//            12 bits, so the field and the hardware now agree at 4096.)
//   3 ROPET arg1=src                         rope table: 64 cos + 64 sin
//   4 ROPE  arg1={dst,src}                    256 elems
//   5 CONVW arg0={nch[29:16],first[15:2],sel[1:0]}; arg1=src
//           sel 0: weights (4 words/ch)  1: state (3 words/ch)  2: zero state
//   6 CONV  arg0={nch[27:14],first[13:0]}; arg1={dst,src}
//           (v2.0 widened both channel fields 13 -> 14 bits so a whole-block
//            CONV_DIM=8192 command could be ENCODED; G3.4 grew the conv
//            BANKS to 24 x 8192, so it is EXECUTABLE now too.  nch = 0 and
//            first+nch past 8192 are REFUSED in hardware.)
//   7 GATE  arg0=dst[15:0]; arg1={src_a,src_b}; arg2={src_dt,src_A}
//           A as {lo,hi} pairs; out: beta[0..LNH-1], decay[0..LNH-1] at dst
//   8 DNST  arg0={spare[31:5], head[4:0]}
//           arg1={src_k,src_q}; arg2={dst,src_v}
//           a_beta = DNSB[15:0] + head, a_dec = DNSB[31:16] + head
//           out: 128 x int32 {lo,hi} pairs at dst
//   9 KVAP  arg0={expbias[8:4],kvhead[1:0]}; arg1={src_v,src_k}
//           dyn-quant k,v (256 each) -> int8 rows + exps at T; T++
//  10 ATTN  arg0=kvhead[1:0]; arg1={dst,src_q}
//           (v2.0 widened the kvhead FIELD to 2 bits for NKV=4 and G3.4
//            widened the BANKING to match: 8 KV banks, tcnt_bank[8][4],
//            so all four kvheads are independent caches)
//           out: 256 x int32 {lo,hi} pairs at dst (T = TCNT[kvhead])
//  11 ALU   arg0={spare[31:19],p0[16]@18,len[17:4],aop[3:0]}; arg1={srcb,srca}
//           (R-c took len from 12 to 13 bits because the Qwen3.5-2B MLP
//            DYNQ8s its whole FFN=6144 intermediate in ONE command and a
//            DYNQ8 cannot be chunked -- one shared exponent over the whole
//            vector, reported on EOUT.  G3.1 takes it to 14, so the 9B
//            FFN=12288 also fits one command.  Max length is now 16383.)
//           arg2={dst[31:16],p0[15:0]}  vec_alu ops 0..10, 12
//           (aop 10 AMAX32: p0[0]=fresh; winner on AMAXI/AMAXV CSRs)
//           (aop 12 DYNQ16: p0[0]=k dst (0->XRF[1], 1->XRF[2]),
//            p0[1]=clamp k at 0; k retires into the XRF)
//           (aop 8 EMUL32: p0[6]=probe -> max|prod| on MAXPL/MAXPH and
//            k_a into XRF[2]; p0[5:0] is still the shift)
//  12 DNZ   arg0=head[4:0]                     zero DN state for head
//
// ---- S6 burst window (docs/RUNG3_SPEC.md, rung 3) --------------------
// A second slave, s_axib (AXI4, 32-bit data, 18-bit address, ID width 1,
// same aclk — ZERO new CDC), maps the scratchpad directly:
//     scratch word w at byte 4w,  w = 0..65535   (256 KiB window, G3.1)
// The 16-bit datum lives in the LOW half of each 32-bit beat, upper half
// ignored — bit-identical to what the SWIN CSR takes today (wdata[15:0])
// and to what seq_movers pushes on MOVY ({16'd0, y_val[15:0]} /
// {16'd0, y_val[31:16]}, rtl/seq_movers.sv:603).  WSTRB[1:0] must be 00
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
    // ==== S2 (spec 2026-09-04 state-spill §8.2) — THE FENCE BYPASS ======
    // 1 removes F1 (the load-before-use stall AND the E_DMA_COLD refusal).
    // It exists so the fence has a NEGATIVE CONTROL: tb_layer_sdma built
    // with -GSDMA_NOFENCE=1 must read the pre-load slot and FAIL its golden
    // compare.  It is a TESTBENCH knob and nothing else — 0 IS WHAT SHIPS,
    // and rtl/layer_chan_ipi.v does not override it.
    parameter int SDMA_NOFENCE = 0
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

    // ---- S6 burst window: AXI4 slave, 32b data / 18b addr, ID width 1.
    // No LOCK/CACHE/PROT/QOS/REGION/USER (RUNG3_SPEC interface contract:
    // tie constants at the fabric).
    input  wire [0:0]   s_axib_awid,
    input  wire [17:0]  s_axib_awaddr,
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
    input  wire [17:0]  s_axib_araddr,
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
    input  wire         s_axib_rready,

    // ---- S2: the state-DMA master (spec §4).  AXI4, 512-bit data, 34-bit
    // address, on the SAME aclk (zero new CDC).  AWSIZE/ARSIZE (3'b110),
    // AWBURST/ARBURST (2'b01) and AWID/ARID (0) are TIED CONSTANT in
    // rtl/layer_chan_ipi.v, so they are not ports here.
    output wire [33:0]  m_axis_awaddr,
    output wire [7:0]   m_axis_awlen,
    output wire         m_axis_awvalid,
    input  wire         m_axis_awready,
    output wire [511:0] m_axis_wdata,
    output wire [63:0]  m_axis_wstrb,
    output wire         m_axis_wlast,
    output wire         m_axis_wvalid,
    input  wire         m_axis_wready,
    input  wire [1:0]   m_axis_bresp,
    input  wire         m_axis_bvalid,
    output wire         m_axis_bready,
    output wire [33:0]  m_axis_araddr,
    output wire [7:0]   m_axis_arlen,
    output wire         m_axis_arvalid,
    input  wire         m_axis_arready,
    input  wire [511:0] m_axis_rdata,
    input  wire [1:0]   m_axis_rresp,
    input  wire         m_axis_rlast,
    input  wire         m_axis_rvalid,
    output wire         m_axis_rready
);
    import fx_pkg::*;

    // ==================================================================
    // G3.4 — THE 9B GEOMETRY (spec 4.1 W1', 4.6 W6; U4: ONE geometry).
    // These are localparams, not parameters: U4 retired the multi-model
    // contract, so this bitstream serves Qwen3.5-9B and nothing else and
    // there is no legacy configuration to admit.
    //
    // S2 WITHDREW the claim that stood here — that these names and the
    // derived expressions below are IDENTICAL to Track P's placed
    // experiment, so that G5a re-runs the structure that ships.  Track P's
    // vehicle is a FROZEN copy of the 928-URAM banked arrays; the state
    // this file keeps is now two cache slots per kind and DDR (spec
    // 2026-09-04 state-spill §0).  S5 re-measures on the shipping rtl/,
    // which is what synth/exp_uram/scripts/exp_ooc.tcl:75 already points
    // at, and the copy under synth/exp_uram/rtl/ stays as Task 13 left it
    // (the plan's standing hazard: refreshing it was reverted as UNSAFE
    // for citation drift).
    //
    //  N_DN and N_KV survive as the LAYER-COUNT envelope of the SLD/SST
    //  range check (24 DeltaNet layers, 8 GQA layers); NKVH is the kvheads
    //  per attention layer and sizes tcnt_bank; CVD is the conv slot depth.
    //                          as built | THIS BUILD (9B)
    //  LNH   DN value heads       16    |    32
    //  N_DN  DeltaNet layers      18    |    24
    //  N_KV  GQA layers            6    |     8
    //  NKVH  kv heads per layer    2    |     4
    //  CVD   conv slot depth    6144    |  8192
    //
    // URAM arithmetic AS OF S2 (spec state-spill §3; label S, MEASURED by
    // S5's OOC run): banking retired, two slots per kind -- DN 2 x 29 = 58,
    // KV 2 x 58 = 116, conv 2 x 4 = 8 (the ram_style below; S5 read 174 without it) -> 182 URAM
    // where G3.4 needed 928.  N_DN / N_KV survive ONLY as the LAYER-COUNT
    // envelope the SLD/SST range check reads; they no longer size a bank.
    localparam int LNH   = 32;
    localparam int N_DN  = 24;
    localparam int N_KV  = 8;
    localparam int NKVH  = 4;
    localparam int CVD   = 8192;

    // ---- the cache geometry (spec §3, A1.2) --------------------------
    // Each kind keeps N_SLOT slots and NOTHING is banked any more, so
    // there is no linear address to cut and no bank select on any path:
    //   DN   slot = 4096 rows x 2048 b, addressed {head[4:0], row[6:0]}
    //   KV   slot = 8192 rows x 2048 b, addressed {kv, t[11:0]},
    //        plus an exponent memory of the same depth x 8 b
    //   conv slot = 8192 x 64 b weights + 8192 x 48 b state (two memories,
    //        so CONV/CONVZ's state-only writes stay exactly as they are)
    //
    // RETIRED HERE (S2): DN_AW / DN_ROWS / DN_NB / DN_BW / DN_GRP / DN_GW /
    // DN_SDEL / DN_RLAT / DN_P2WAIT / LDB / KVB / KV_AW / KV_NB / KV_BW.
    // They described G3.4's 928-URAM banked arrays; the state that needed
    // them is in DDR now (spec §0 "What this supersedes").  dn_step's FSM
    // is UNCHANGED — only its instantiation goes back to (RLAT 2,
    // P2_WAIT 0), the legal pair at latency 2 (rtl/dn_step.sv:41-43).
    localparam int N_SLOT = 2;                    // cache slots per kind
    localparam int HB     = $clog2(LNH);          // 5  dn_head width
    localparam int KHB    = $clog2(NKVH);         // 2  kvhead width
    localparam int KV_AW  = 13;                   // {kv, t[11:0]}
    localparam int CV_AW  = $clog2(CVD);          // 13
    localparam int GIW    = $clog2(2 * LNH);      // 6  GATE store counter

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
    // S2 — THE SEQ_ISA v2.1 CONSTANTS.  Every line below carries a
    // `// SDMA_BITS: <name>` marker: evidence/qwen9b/s1/sdma_bits.py reads
    // these values OUT OF THIS FILE and requires them equal to
    // ref/seq_format.py, sw/hwmap.py and docs/SEQ_ISA.md B15.  The marker
    // text is what its grab() regex matches, so the lines are copied
    // VERBATIM from S1's contract fixture
    // (evidence/qwen9b/s1/s2_contract_stub.sv) — do not reformat them.
    // ==================================================================

    // ---- B15.1 the two layer commands ------------------------------
    localparam logic [3:0] OP_SLD = 4'd13;                // SDMA_BITS: OP_SLD
    localparam logic [3:0] OP_SST = 4'd14;                // SDMA_BITS: OP_SST

    // ---- B15.3 the five CSRs, by WORD offset ------------------------
    localparam logic [9:0] SB_DN_W    = 10'h019;          // SDMA_BITS: CSR_SB_DN
    localparam logic [9:0] SB_KV_W    = 10'h01A;          // SDMA_BITS: CSR_SB_KV
    localparam logic [9:0] SB_CV_W    = 10'h01B;          // SDMA_BITS: CSR_SB_CV
    localparam logic [9:0] SDMA_W     = 10'h01C;          // SDMA_BITS: CSR_SDMA
    localparam logic [9:0] SDMA_CYC_W = 10'h01D;          // SDMA_BITS: CSR_SDMA_CYC

    // ---- B15.4 the layer's error codes ------------------------------
    localparam logic [7:0] E_ENV       = 8'h01;           // SDMA_BITS: ERR_E_ENV
    localparam logic [7:0] E_LAYER     = 8'h02;           // SDMA_BITS: ERR_E_LAYER
    localparam logic [7:0] E_DMA_BASE  = 8'h10;           // SDMA_BITS: ERR_E_DMA_BASE
    localparam logic [7:0] E_DMA_RANGE = 8'h11;           // SDMA_BITS: ERR_E_DMA_RANGE
    localparam logic [7:0] E_DMA_AXI   = 8'h12;           // SDMA_BITS: ERR_E_DMA_AXI
    localparam logic [7:0] E_DMA_COLD  = 8'h13;           // SDMA_BITS: ERR_E_DMA_COLD

    // ---- B15.1 the three address shifts the adder applies ------------
    localparam int SDMA_SHIFT_DN = 20;                    // SDMA_BITS: SHIFT_DN
    localparam int SDMA_SHIFT_KV = 21;                    // SDMA_BITS: SHIFT_KV
    localparam int SDMA_SHIFT_CV = 17;                    // SDMA_BITS: SHIFT_CV

    // ---- B15.1 the ARG0 concat, B15.2 the LAYER word -----------------
    //   arg0 = {kind[12:11], slot[10], layer[9:5], head[4:0]}  // SDMA_BITS: ARG0_FIELDS
    // 10'h00C LAYER decode  // SDMA_BITS: LAYER_FIELDS {cv_slot[13:12], kv_layer[10:8], kv_slot[4:3], dn_slot[1:0]}

    // the SLD/SST kind field, as B15.1 numbers it
    localparam logic [1:0] K_DN = 2'd0, K_KV = 2'd1, K_CV = 2'd2;

    // ==================================================================
    // CSR registers
    // ==================================================================
    logic [3:0]  cmd_op;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [31:0] arg0, arg1, arg2;   // per-command packing; some bits spare
    /* verilator lint_on UNUSEDSIGNAL */
    logic [15:0] sptr;
    logic [15:0] cmd_cnt;
    // spec A1.4: busy_cmp is the COMPUTE lane's busy — the CMD accept gate
    // and LCYC's source.  STATUS bit 0 reports busy_any = busy_cmp |
    // busy_dma; the DMA lane never blocks a CMD write.
    logic        busy_cmp, err_op;
    logic [7:0]  sdma_err;               // B15.4's code, reported in SDMA.err
    logic        cmd_pend;               // a compute command stalled on F1
    logic [3:0]  eout_q;
    // G3.4: [8][4] — one counter per (kv_slot, kvhead) at N_KV=8, NKVH=4.
    // The host reaches kvheads 2/3 through the TCNT2 CSR (0x60); see the
    // header.  The reference model's twin is ref/gen_layer_script.py's
    // self.T, sized [_KV_SLOTS][_KVH] = [8][4] since Task 3.
    // S2 (spec A1.3): [attention layer][kvhead], 13 bits for T <= 4096.
    // The HOST indexes it with LAYER.kv_layer; KVAP/ATTN index it through
    // the TAG of the KV slot LAYER.kv_slot names.
    logic [12:0] tcnt_bank [N_KV][NKVH]; // [kv_layer][kvhead] KV append counters
    logic [1:0]  layer_dn;               // live LAYER.dn_slot (0/1)
    logic [1:0]  layer_kv;               // live LAYER.kv_slot (0/1)
    logic [1:0]  layer_cv;               // live LAYER.cv_slot (0/1)
    logic [2:0]  layer_kvl;              // live LAYER.kv_layer (0..7)
    // B15.3: the three region bases, in 64 KiB units
    logic [17:0] sb_dn, sb_kv, sb_cv;
    logic [31:0] sdma_cyc;               // busy_dma cycles (SDMA_CYC CSR)
    logic        sdma_clr;               // registered pulse: a write to SDMA
    logic [31:0] lcyc;                   // busy-cycle counter (LCYC CSR)
    logic        cmd_go;                 // pulse into dispatcher
    logic        hw_we;                  // host scratch write (registered)
    logic [15:0] hw_addr;
    logic [15:0] hw_data;
    // G3.1 DNSB (CSR 0x5C): the DeltaNet scalar-pointer BASE PAIR.  DNST's
    // a_beta/a_dec are affine in the head with stride 1, so the ARG words
    // carry only the head and the two bases live here, written once per
    // layer body.  Two 16-bit adds with a 5-bit addend, in the DNST decode.
    logic [15:0] dnsb_beta;              // a_beta_base = DNSB[15:0]
    logic [15:0] dnsb_dec;               // a_dec_base  = DNSB[31:16]
    logic        tcnt_inc;               // from dispatcher (KVAP): +1 the
                                         // counter the running command's KV
                                         // slot TAG names (spec A1.3)

    // ---- XRF (see the header) ----
    logic signed [17:0] xrf [8];
    logic [2:0]  xrfi;                   // XRFI index register
    logic        xrf_we;                 // external (CSR / future SEQ) write
    logic [2:0]  xrf_widx;
    logic signed [17:0] xrf_wdat;

    // ==================================================================
    // scratchpad: 64K x 16, replicated for two read ports (G3.1, spec 4.3
    // S4: fully backed, no MLP chunking, no unbacked hole).  This comment
    // said "16K x 16" while the arrays were 32768 deep -- the D-CITE class,
    // now the number matches the declaration below.
    // ==================================================================
    (* cascade_height = 2 *) logic signed [15:0] smem_a [65536];
    (* cascade_height = 2 *) logic signed [15:0] smem_b [65536];
    logic [15:0] sa_addr, sb_addr;
    logic signed [15:0] sa_q, sb_q;
    logic [15:0] sw_addr;
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
    logic [11:0] vn_waddr;          // 4096 vecnorm weights (n_log2 = 12)
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
    // G3.4 (spec 4.6 wall 10): NH is OVERRIDDEN here.  It used to be
    // instantiated with no override, so gate_unit's parameter DEFAULT was
    // load-bearing; both moved to 32 and the override makes the coupling
    // explicit at the instance.
    gate_unit #(.NH(LNH),
                .SIGMOID_ROM(SIGMOID_ROM), .SOFTPLUS_ROM(SOFTPLUS_ROM),
                .EXP2_ROM(EXP2_ROM)) u_gate (
        .clk(aclk), .rstn(rstn_i), .start(gt_start), .busy(gt_busy),
        .done(gt_done), .w_we(gt_wwe), .w_sel(gt_wsel), .w_addr(gt_waddr),
        .w_data(gt_wdata), .beta_o(gt_beta), .decay_o(gt_decay));

    // --- dn_step + state URAM (32 heads x 128 rows x 2048b per slot) ---
    logic        dn_start, dn_vwe;
    /* verilator lint_off UNUSEDSIGNAL */
    logic        dn_done;   // collection is count-based; done pulse unused
    /* verilator lint_on UNUSEDSIGNAL */
    logic [1:0]  dn_vsel;
    logic [6:0]  dn_vaddr;
    logic signed [20:0] dn_vdata;
    logic [15:0] dn_decay, dn_beta;
    logic [6:0]  dn_rda, dn_wra;
    logic [2047:0] dn_rdq, dn_wrd;
    logic        dn_wren;
    logic        dn_mvalid, dn_mready;
    logic signed [31:0] dn_mdata;
    logic [6:0]  dn_midx;
    /* verilator lint_off UNUSEDSIGNAL */
    logic dn_busy;
    /* verilator lint_on UNUSEDSIGNAL */
    // RLAT is the DN state read latency this instance's cache presents,
    // and dn_step leads its address by exactly that much.  With the 24-bank
    // array retired (S2) the DN slot is one URAM row deep plus layer_chan's
    // output register, so RLAT is back to 2 and P2_WAIT must be 0 — the
    // legal pair at latency 2 (rtl/dn_step.sv:41-43).  dn_step's FSM is
    // NOT edited: only these two overrides move.
    dn_step #(.RLAT(2), .P2_WAIT(0)) u_dn (
        .clk(aclk), .rstn(rstn_i), .start(dn_start), .busy(dn_busy),
        .done(dn_done), .cfg_decay(dn_decay), .cfg_beta(dn_beta),
        .vec_we(dn_vwe), .vec_sel(dn_vsel), .vec_addr(dn_vaddr),
        .vec_data(dn_vdata),
        .s_rdaddr(dn_rda), .s_rddata(dn_rdq),
        .s_wraddr(dn_wra), .s_wrdata(dn_wrd), .s_wren(dn_wren),
        .m_valid(dn_mvalid), .m_ready(dn_mready), .m_data(dn_mdata),
        .m_idx(dn_midx));

    // ==================================================================
    // S2 — THE DMA LANE AND ITS ENGINE (spec §4, §5.4; B15.1, B15.5)
    //
    // Declared here because the slot memories below read the engine's port
    // bundle through their ownership muxes; the lane's own FSM is at the
    // bottom of the file, after the dispatcher that feeds it.
    // ==================================================================
    // the latched cache slots of the RUNNING compute command
    logic        dn_slot_r;               // latched LAYER.dn_slot (0/1)
    logic        kv_slot_r;               // latched LAYER.kv_slot (0/1)
    logic        cv_slot_r;               // latched LAYER.cv_slot (0/1)
    logic [4:0]  kvt_r;                   // that KV slot's TAG {layer, kvhead}

    // the DMA lane's queue (depth 4, in order) and the transfer in flight
    localparam int DQD = 4;
    logic        dq_store [DQD];
    logic [1:0]  dq_kind  [DQD];
    logic        dq_slot  [DQD];
    logic [4:0]  dq_layer [DQD];
    // only three bits: the dispatcher REFUSES head > 7 (E_DMA_RANGE) before
    // anything is enqueued, so bits [4:3] can never reach the queue.
    logic [2:0]  dq_head  [DQD];
    logic [2:0]  dq_wp, dq_rp;
    wire  [2:0]  dq_cnt   = dq_wp - dq_rp;
    wire         dq_full  = (dq_cnt == 3'd4);
    wire         dq_empty = (dq_wp == dq_rp);

    // enqueue strobe, from the dispatcher's DMA-lane branch
    logic        enq_v, enq_store, enq_slot;
    logic [1:0]  enq_kind;
    logic [4:0]  enq_layer;
    logic [2:0]  enq_head;

    // per-kind, per-slot lane state (spec §5.4, A1.3)
    logic        warm     [3][N_SLOT];    // a completed load since the last SST
    logic [4:0]  kv_tag   [N_SLOT];       // {layer[2:0], kvhead[1:0]}
    logic [2:0]  sld_pend [3][N_SLOT];    // queued + in-flight LOADS per slot
    logic        warm_set_v, warm_set_slot;   // DNZ / CONVZ warm their slot
    logic [1:0]  warm_set_kind;

    // the transfer in flight
    logic        dma_act;                 // a transfer owns its slot
    logic        dma_store;
    logic [1:0]  dma_kind;
    logic        dma_slot;
    logic        dma_kvbit;               // the KV block's k/v half
    logic [4:0]  dma_tag;                 // {layer[2:0], kvhead[1:0]} in flight
    logic [1:0]  last_kind;               // SDMA[27:26]
    logic        last_slot;               // SDMA[25]
    logic        dma_err_p;               // pulse: E_DMA_AXI at completion
    wire         busy_dma;                // the lane is not idle (A1.4)

    // the engine's own port bundle
    logic        sd_go, sd_store;
    logic [1:0]  sd_kind;
    logic [33:0] sd_addr34;
    logic [13:0] sd_rows;
    /* verilator lint_off UNUSEDSIGNAL */
    wire         sd_busy;                 // dma_act is the lane's own copy
    /* verilator lint_on UNUSEDSIGNAL */
    wire         sd_done, sd_err;
    wire [12:0]  sd_addr;
    wire [2047:0] sd_wdata;
    wire [7:0]   sd_wexp;
    wire         sd_we, sd_wexp_we;
    wire [2047:0] sd_rdata;               // driven below, off the slot muxes
    wire [7:0]   sd_rexp;

    state_dma u_dma (
        .aclk(aclk), .aresetn(rstn_i),
        .xfer_go(sd_go), .xfer_store(sd_store), .xfer_kind(sd_kind),
        .xfer_addr(sd_addr34), .xfer_rows(sd_rows),
        .xfer_busy(sd_busy), .xfer_done(sd_done), .xfer_err(sd_err),
        .slot_addr(sd_addr), .slot_wdata(sd_wdata), .slot_wexp(sd_wexp),
        .slot_we(sd_we), .slot_wexp_we(sd_wexp_we),
        .slot_rdata(sd_rdata), .slot_rexp(sd_rexp),
        .m_axis_awaddr(m_axis_awaddr), .m_axis_awlen(m_axis_awlen),
        .m_axis_awvalid(m_axis_awvalid), .m_axis_awready(m_axis_awready),
        .m_axis_wdata(m_axis_wdata), .m_axis_wstrb(m_axis_wstrb),
        .m_axis_wlast(m_axis_wlast), .m_axis_wvalid(m_axis_wvalid),
        .m_axis_wready(m_axis_wready),
        .m_axis_bresp(m_axis_bresp), .m_axis_bvalid(m_axis_bvalid),
        .m_axis_bready(m_axis_bready),
        .m_axis_araddr(m_axis_araddr), .m_axis_arlen(m_axis_arlen),
        .m_axis_arvalid(m_axis_arvalid), .m_axis_arready(m_axis_arready),
        .m_axis_rdata(m_axis_rdata), .m_axis_rresp(m_axis_rresp),
        .m_axis_rlast(m_axis_rlast), .m_axis_rvalid(m_axis_rvalid),
        .m_axis_rready(m_axis_rready));

    // OWNERSHIP (spec A1.2, §5.4).  The select is PER (kind, SLOT), not per
    // kind: B15.5 lets a transfer on one slot of a kind be in flight while a
    // compute command holds the OTHER slot of that kind, so a per-kind mux
    // would hijack the idle slot's ports and corrupt the running command.
    // The COMPUTE leg of every mux below is EXACTLY the signal that drove
    // the memory before S2; the DMA sits on the other input.  The DMA's read
    // RETURN is its own output register per kind, so nothing the DMA does
    // reaches the compute unit's read path at all.
    wire dn_dma_own = dma_act && (dma_kind == K_DN);
    wire kv_dma_own = dma_act && (dma_kind == K_KV);
    wire cv_dma_own = dma_act && (dma_kind == K_CV);

    // ==================================================================
    // DeltaNet state: N_SLOT slots of 4096 x 2048 b (29 URAM each), the
    // whole 32-head layer that an SLD/SST moves in one transfer (A1.1).
    // The address is {head[4:0], row[6:0]} — no bank, no linear cut, no
    // pipelined SLR crossing: G3.4's DN_PIPE fan-out/return structure is
    // RETIRED with the 24-bank array it was built to span (spec §0).
    // ==================================================================
    logic [HB-1:0]  dn_head;              // latched at dispatch (ISA field)
    // The KVAP/ATTN kvhead ARG field, latched at dispatch beside the slot's
    // tag.  `cmd_range_bad` REFUSES the command (E_DMA_RANGE) unless this
    // field equals the tag's kvhead, so `kvhead_r` and `kvt_r[1:0]` are the
    // same value for every command that runs — and the append counters are
    // indexed through it, which is what keeps the two tied (spec A1.3).
    logic [KHB-1:0] kvhead_r;
    logic        dnz_we;
    logic [6:0]  dnz_addr;
    // single muxed write port (a second conditional write makes URAM
    // infeasible -> 150K-LUT distributed-RAM fallback; DNST and DNZ are
    // never active in the same command).
    wire           dn_w    = dn_wren | dnz_we;
    wire [HB+6:0]  dn_wa   = dn_wren ? {dn_head, dn_wra} : {dn_head, dnz_addr};
    wire [2047:0]  dn_wd   = dn_wren ? dn_wrd : '0;
    wire [11:0]    dn_ra_f = {dn_head, dn_rda};     // compute read address
    wire [11:0]    dn_wa_f = dn_wa;                 // compute write address
    logic [2047:0] dn_rdq_b [N_SLOT];
    logic [2047:0] dn_dmaq;                // the DMA's own read return
    genvar gd;
    generate for (gd = 0; gd < N_SLOT; gd++) begin : g_dnslot
        // the four ownership muxes, for THIS slot
        wire           own = dn_dma_own && (dma_slot == 1'(gd));
        wire [11:0]    ra  = own ? sd_addr[11:0] : dn_ra_f;
        wire [11:0]    wa  = own ? sd_addr[11:0] : dn_wa_f;
        wire [2047:0]  wd  = own ? sd_wdata      : dn_wd;
        wire           we  = own ? sd_we : (dn_w && (dn_slot_r == 1'(gd)));
        (* ram_style = "ultra" *) logic [2047:0] mem [4096];
        always_ff @(posedge aclk) begin
            dn_rdq_b[gd] <= mem[ra];
            if (we) mem[wa] <= wd;
        end
    end endgenerate
    // fabric OREGs: the URAM CQ stays off both paths, and dn_step therefore
    // sees RLAT = 2 (the instantiation above).
    always_ff @(posedge aclk) begin
        dn_rdq  <= dn_rdq_b[dn_slot_r];
        dn_dmaq <= dn_rdq_b[dma_slot];
    end

    // --- attn_core + the KV cache (2 slots x 8192 rows x 2048b, S2) ---
    logic        at_start, at_qwe;
    /* verilator lint_off UNUSEDSIGNAL */
    logic        at_done;   // collection is count-based; done pulse unused
    /* verilator lint_on UNUSEDSIGNAL */
    logic [7:0]  at_qaddr;
    logic signed [15:0] at_qdata;
    logic [12:0] at_kvaddr;               // {bank, t[11:0]} (S2: 13 bits)
    wire [2047:0] at_kvdata;
    wire signed [7:0] at_kvexp;
    logic        at_mvalid, at_mready;
    logic signed [31:0] at_mdata;
    logic [7:0]  at_midx;
    logic [12:0] at_cfg_t;                // T <= 4096 (spec A1.5)
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

    // ==================================================================
    // KV cache: N_SLOT slots of 8192 x 2048 b (58 URAM each) addressed
    // {kv, t[11:0]} at T <= 4096, plus ONE exponent memory per slot
    // (8192 x 8 b, block RAM — `emem` deliberately carries no ram_style).
    // The 8-bank array and its {kv_slot, kvhead, k/v, t[8:0]} linear cut
    // are RETIRED: a slot now holds K and V for ONE (layer, kvhead), and
    // WHICH one is the slot's TAG, not an address field (spec A1.3).
    // ==================================================================
    logic          kv_we, kvx_we;
    logic [KV_AW-1:0] kv_waddr;            // {kv, t[11:0]}
    logic [2047:0] kv_wrow;
    logic [7:0]    kv_wexp;
    // the DMA's slot address: state_dma counts rows 0..TCNT-1 and layer_chan
    // supplies the k/v half of the block the transfer names.
    wire [KV_AW-1:0] kv_dma_a = {dma_kvbit, sd_addr[11:0]};
    logic [2047:0] kv_rdq_b  [N_SLOT];     // per-slot URAM CQ (row)
    logic [7:0]    kvx_rdq_b [N_SLOT];     // per-slot read (exp)
    genvar gk;
    generate for (gk = 0; gk < N_SLOT; gk++) begin : g_kvslot
        wire             own = kv_dma_own && (dma_slot == 1'(gk));
        wire [KV_AW-1:0] ra  = own ? kv_dma_a : at_kvaddr;
        wire [KV_AW-1:0] wa  = own ? kv_dma_a : kv_waddr;
        wire [2047:0]    wd  = own ? sd_wdata : kv_wrow;
        wire [7:0]       wx  = own ? sd_wexp  : kv_wexp;
        wire             we  = own ? sd_we      : (kv_we  && (kv_slot_r == 1'(gk)));
        wire             wxe = own ? sd_wexp_we : (kvx_we && (kv_slot_r == 1'(gk)));
        (* ram_style = "ultra" *) logic [2047:0] mem  [8192];
        logic [7:0]                              emem [8192];
        always_ff @(posedge aclk) begin
            kv_rdq_b[gk]  <= mem[ra];
            kvx_rdq_b[gk] <= emem[ra];
            if (we)  mem [wa] <= wd;
            if (wxe) emem[wa] <= wx;
        end
    end endgenerate
    // fabric OREGs (2-cycle read): attn_core's, and the DMA's own
    logic [2047:0] kv_rdq,  kv_dmaq;
    logic [7:0]    kv_rexp, kv_dmaqx;
    always_ff @(posedge aclk) begin
        kv_rdq   <= kv_rdq_b[kv_slot_r];
        kv_rexp  <= kvx_rdq_b[kv_slot_r];
        kv_dmaq  <= kv_rdq_b[dma_slot];
        kv_dmaqx <= kvx_rdq_b[dma_slot];
    end
    assign at_kvdata = kv_rdq;
    assign at_kvexp  = signed'(kv_rexp);

    // ==================================================================
    // conv weight/state memories: N_SLOT slots, each TWO memories —
    // wm 8192 x 64 b (weights) and sm 8192 x 48 b (state).  They stay
    // SEPARATE (spec A1.2) so CONV's and CONVZ's state-only writes are
    // exactly what they were; the DMA assembles and splits the 16-B DDR
    // row across the pair.  The 24-bank array (one per dn slot) is
    // RETIRED with the rest of the on-chip layer state.
    // Each slot keeps the original 1-cycle registered read + REGISTERED
    // output mux (build_024 census: the combinational bank mux out of
    // spread BRAM into u_conv's DSPs was the worst path family at -1.59ns),
    // and the second per-slot stage build_027 added; the CONV FSM's
    // CV_W/CV_W2/CV_W3 waits match that 3-cycle read unchanged.
    // ==================================================================
    logic [CV_AW-1:0] cw_ra, cs_ra, cw_wa, cs_wa;
    logic [63:0] cw_wd;
    logic [47:0] cs_wd;
    logic        cw_we, cs_we;
    // the ownership muxes, per slot; the DMA's 16-B row is
    // {16'b0, state[47:0], weights[63:0]} and is split across the pair here.
    logic [63:0] cw_q_b [N_SLOT];         // per-slot BRAM read register
    logic [47:0] cs_q_b [N_SLOT];
    (* dont_touch = "true" *) logic [63:0] cw_q_p [N_SLOT];
    (* dont_touch = "true" *) logic [47:0] cs_q_p [N_SLOT];
    genvar gc;
    generate for (gc = 0; gc < N_SLOT; gc++) begin : g_cvslot
        wire             own = cv_dma_own && (dma_slot == 1'(gc));
        wire [CV_AW-1:0] wra = own ? sd_addr : cw_ra;
        wire [CV_AW-1:0] sra = own ? sd_addr : cs_ra;
        wire [CV_AW-1:0] wwa = own ? sd_addr : cw_wa;
        wire [CV_AW-1:0] swa = own ? sd_addr : cs_wa;
        wire [63:0]      wwd = own ? sd_wdata[63:0]   : cw_wd;
        wire [47:0]      swd = own ? sd_wdata[111:64] : cs_wd;
        wire             wwe = own ? sd_we : (cw_we && (cv_slot_r == 1'(gc)));
        wire             swe = own ? sd_we : (cs_we && (cv_slot_r == 1'(gc)));
        (* ram_style = "ultra" *) logic [63:0] wm [CVD];
        (* ram_style = "ultra" *) logic [47:0] sm [CVD];
        always_ff @(posedge aclk) begin
            cw_q_b[gc] <= wm[wra];
            cs_q_b[gc] <= sm[sra];
            cw_q_p[gc] <= cw_q_b[gc];
            cs_q_p[gc] <= cs_q_b[gc];
            if (wwe) wm[wwa] <= wwd;
            if (swe) sm[swa] <= swd;
        end
    end endgenerate
    // dont_touch: build_025 showed synthesis retimes these into u_conv's
    // DSP input registers, recreating the BRAM->mux->DSP monster path the
    // register exists to break.
    (* dont_touch = "true" *) logic [63:0] cw_q;  // registered slot mux
    (* dont_touch = "true" *) logic [47:0] cs_q;
    always_ff @(posedge aclk) begin
        cw_q <= cw_q_p[cv_slot_r];
        cs_q <= cs_q_p[cv_slot_r];
    end

    // ==================================================================
    // the slot read return the DMA sees on a STORE.  Its select is stable
    // for the whole transfer (one transfer at a time, exclusive ownership),
    // and it is OFF the compute path: nothing here feeds a compute unit.
    // Conv reads at the 2-cycle stage, because state_dma's contract is a
    // 2-cycle slot read while the CONV FSM waits three.
    // ==================================================================
    assign sd_rdata = (dma_kind == K_DN) ? dn_dmaq
                    : (dma_kind == K_KV) ? kv_dmaq
                    : {1936'b0, cs_q_p[dma_slot], cw_q_p[dma_slot]};
    assign sd_rexp  = kv_dmaqx;

    // --- vec_alu ---
    logic        alu_start, alu_done;
    logic [3:0]  alu_eout;
    logic [15:0] alu_aa, alu_ba, alu_wa;
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
        .cfg_op(arg0[3:0]), .cfg_len(arg0[17:4]),   // G3.1: 14-bit len
        .cfg_p0(signed'({arg0[18], arg2[15:0]})),   // p0[16] relocated
        .cfg_srca(arg1[15:0]),
        .cfg_srcb(arg1[31:16]),
        .cfg_dst(arg2[31:16]), .e_out(alu_eout),
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
    wire tk_amax  = busy_cmp && (cmd_op == OP_ALU) && (arg0[3:0] == 4'd10);

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
            for (int i = 0; i < N_KV; i++)
                for (int kh = 0; kh < NKVH; kh++) tcnt_bank[i][kh] <= '0;
            layer_dn <= '0; layer_kv <= '0; layer_cv <= '0; layer_kvl <= '0;
            lcyc <= '0;
            dnsb_beta <= '0; dnsb_dec <= '0;   // G3.1
            sb_dn <= '0; sb_kv <= '0; sb_cv <= '0;   // S2: 0 == E_DMA_BASE
            sdma_cyc <= '0; sdma_clr <= 1'b0;
        end else begin
            cmd_go <= 1'b0;
            hw_we  <= 1'b0;
            xrf_we <= 1'b0;
            sdma_clr <= 1'b0;
            // spec A1.4: LCYC counts the COMPUTE lane only, so the layer-term
            // census keeps its meaning; SDMA_CYC is the DMA lane's twin.
            if (busy_cmp) lcyc <= lcyc + 1'b1;      // write-clear below wins
            if (busy_dma) sdma_cyc <= sdma_cyc + 1'b1;

            if (s_axil_awvalid && s_axil_awready) begin
                aw_got <= 1'b1; awaddr_q <= s_axil_awaddr[11:2];
            end
            if (s_axil_wvalid && s_axil_wready) begin
                w_got <= 1'b1; wdata_q <= s_axil_wdata; wstrb_q <= s_axil_wstrb;
            end

            if (aw_got && w_got && !s_axil_bvalid) begin
                case (awaddr_q)
                    // spec A1.4: the accept gate is busy_cmp ALONE — an
                    // SLD/SST enqueued on the DMA lane must never block the
                    // next record, and busy_dma must never drop a CMD.
                    10'h000: if (!busy_cmp) begin                // CMD
                        cmd_op <= wdata_q[3:0];
                        cmd_go <= 1'b1;
                    end
                    10'h002: arg0 <= wdata_q;                    // ARG0
                    10'h003: arg1 <= wdata_q;                    // ARG1
                    10'h004: arg2 <= wdata_q;                    // ARG2
                    10'h005: sptr <= wdata_q[15:0];              // SPTR
                    10'h006: begin                               // SWIN
                        hw_we   <= 1'b1;
                        hw_addr <= sptr;
                        hw_data <= wdata_q[15:0];
                        sptr    <= sptr + 1'b1;
                    end
                    10'h008: begin                               // TCNT
                        // S2 (B15.2): indexed by LAYER.kv_layer, 13 bits
                        tcnt_bank[layer_kvl][0] <= wdata_q[12:0];
                        tcnt_bank[layer_kvl][1] <= wdata_q[28:16];
                    end
                    10'h018: begin                               // TCNT2
                        // G3.4 (spec 4.6 wall 9): NKVH = 4 needs four
                        // 10-bit counters per kv_slot and a 32-bit CSR
                        // word holds two.  The counters for kvheads 2/3
                        // get their OWN offset with the IDENTICAL layout
                        // rather than aliasing onto 0/1 — an aliased reset
                        // is exactly the silent divergence wall 9 is
                        // about.  Host mirror: sw/hwmap.py L_TCNT2.
                        tcnt_bank[layer_kvl][2] <= wdata_q[12:0];
                        tcnt_bank[layer_kvl][3] <= wdata_q[28:16];
                    end
                    10'h00C: begin                               // LAYER
                        // The field homes are B15.2's and are read out of
                        // this file by evidence/qwen9b/s1/sdma_bits.py off
                        // the LAYER_FIELDS anchor above.  Each slot field is
                        // TWO bits so a value of 2 or 3 is REPRESENTABLE and
                        // can be refused (E_LAYER) at the next compute
                        // command, which is the whole point of the width.
                        layer_dn  <= wdata_q[1:0];
                        layer_kv  <= wdata_q[4:3];
                        layer_kvl <= wdata_q[10:8];
                        layer_cv  <= wdata_q[13:12];
                    end
                    SB_DN_W:    sb_dn <= wdata_q[17:0];          // 0x64
                    SB_KV_W:    sb_kv <= wdata_q[17:0];          // 0x68
                    SB_CV_W:    sb_cv <= wdata_q[17:0];          // 0x6C
                    SDMA_W:     sdma_clr <= 1'b1;                // 0x70 W
                    SDMA_CYC_W: sdma_cyc <= '0;                  // 0x74 W
                    10'h00D: lcyc <= '0;                          // LCYC clear
                    10'h00E: xrfi <= wdata_q[2:0];                // XRFI
                    10'h017: begin                                // DNSB
                        dnsb_beta <= wdata_q[15:0];   // a_beta_base
                        dnsb_dec  <= wdata_q[31:16];  // a_dec_base
                    end
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

            // KVAP appends at {kv, TCNT} and increments TCNT — through the
            // TAG of the slot the command named, not through LAYER (A1.3).
            if (tcnt_inc)
                tcnt_bank[kvt_r[4:2]][kvhead_r]
                    <= tcnt_bank[kvt_r[4:2]][kvhead_r] + 1'b1;

            // reads
            if (s_axil_arvalid && s_axil_arready) begin
                s_axil_rvalid <= 1'b1; s_axil_rresp <= 2'b00;
                case (s_axil_araddr[11:2])
                    10'h001: s_axil_rdata <= {cmd_cnt, 14'b0, err_op,
                                              busy_cmp | busy_dma};
                    10'h002: s_axil_rdata <= arg0;
                    10'h003: s_axil_rdata <= arg1;
                    10'h004: s_axil_rdata <= arg2;
                    10'h005: s_axil_rdata <= {16'b0, sptr};
                    10'h006: begin                               // SWIN
                        s_axil_rdata <= {16'b0, unsigned'(sa_q)};
                        sptr <= sptr + 1'b1;
                    end
                    10'h007: s_axil_rdata <= {28'b0, eout_q};
                    10'h008: s_axil_rdata <= {3'b0, tcnt_bank[layer_kvl][1],
                                              3'b0, tcnt_bank[layer_kvl][0]};
                    10'h009: s_axil_rdata <= 32'hFAB1E5A0;
                    10'h00A: s_axil_rdata <= {14'b0, alu_amax_idx};
                    10'h00B: s_axil_rdata <= unsigned'(alu_amax_val);
                    10'h018: s_axil_rdata <= {3'b0, tcnt_bank[layer_kvl][3],
                                              3'b0, tcnt_bank[layer_kvl][2]};
                    10'h00C: s_axil_rdata <= {18'b0, layer_cv, 1'b0,
                                              layer_kvl, 3'b0, layer_kv,
                                              1'b0, layer_dn};
                    SB_DN_W: s_axil_rdata <= {14'b0, sb_dn};
                    SB_KV_W: s_axil_rdata <= {14'b0, sb_kv};
                    SB_CV_W: s_axil_rdata <= {14'b0, sb_cv};
                    // B15.3's status word for the host and the TB
                    SDMA_W:  s_axil_rdata <= {busy_dma, dq_cnt, last_kind,
                                              last_slot, 17'b0, sdma_err};
                    SDMA_CYC_W: s_axil_rdata <= sdma_cyc;
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
                    10'h017: s_axil_rdata <= {dnsb_dec, dnsb_beta}; // DNSB
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

    logic [15:0] eng_sa;                  // dispatcher scratch read addr
    logic [15:0] eng_swa;                 // dispatcher scratch write port
    logic signed [15:0] eng_swd;
    logic        eng_swe;

    logic [15:0] fi, ci;                  // feed / collect counters
    // VN/ROPE feed pipeline (F_A/F_W), 1 element/cycle
    logic [15:0] f_ai;                    // addresses issued
    logic        f_q1;                    // sa_q holds a feed element now
    logic        f_skv;                   // 1-deep skid occupied
    logic signed [15:0] f_skd;            // ... and its datum
    logic [15:0] n_elems;                 // VN/ROPE element count
    logic [3:0]  ld_tgt;
    logic [12:0] ld_i, ld_n;
    logic [15:0] ld_src;
    logic [15:0] tmp16;
    logic        rnd;                     // KVAP round: 0=k, 1=v
    logic [8:0]  ki;
    logic [3:0]  eq;
    logic [15:0] kmax;
    logic [2047:0] krow;
    logic signed [15:0] s16q;             // registered scratch word (BRAM CQ)
    logic [7:0]  kbyte;                   // quantized byte
    logic [8:0]  kb_i;                    // its row index
    logic [13:0] wi;                      // CONVW channel counter
    logic [1:0]  wk;                      // CONVW word-in-channel
    /* verilator lint_off UNUSEDSIGNAL */
    logic [63:0] tmp64;                   // [63:48] never read back
    /* verilator lint_on UNUSEDSIGNAL */
    logic [13:0] cvi, cvj;                // CONV feed/collect counters
    logic [GIW:0] gi;                     // GATE store counter (2*LNH)
    logic [6:0]  zi;                      // DNZ counter
    logic [9:0]  rcvd, n_col;             // 32b collect
    logic [15:0] m_hi;                    // captured hi half
    logic [15:0] dst_r, src2_r;           // latched dst / second src
    logic        gate_done_q;

    // decoded args (stable while busy: host must not rewrite ARGs mid-cmd)
    // 16-bit scratch addressing (SEQ_ISA v2.0, G3.1).  ARG1 carries an
    // address PAIR as {hi[31:16], lo[15:0]} — NO SCATTERED BITS.  ARG2 uses
    // the same layout on GATE and DNST; the ALU's ARG2 is {dst[31:16],
    // p0[15:0]}, with p0's 17th bit relocated to arg0[18] (see the vec_alu
    // instance above).  R-b's lo[14]@28 / hi[14]@29 scatter is DELETED, not
    // extended: it existed only to keep frozen pre-R-b streams replaying
    // bit-identically, and G3.1 is where that byte-lock is spent.
    wire [15:0] a1_src = arg1[15:0];
    wire [15:0] a1_dst = arg1[31:16];
    wire [15:0] a2_src = arg2[15:0];
    wire [15:0] a2_dst = arg2[31:16];
    wire [4:0]  kv_expbias = arg0[8:4];

    // ==================================================================
    // S9 (spec 5.4) — THE SYNTHESIZABLE COMMAND ENVELOPE.
    //
    // The standing hazard the feasibility study names (spec 2.10) is that
    // almost every envelope guard in this file was `ifndef SYNTHESIS, so
    // on silicon an out-of-envelope command wrapped, aliased or hung — it
    // did not report.  U4 is what makes a hard check cheap: with ONE
    // geometry there is exactly ONE legal envelope, so these comparators
    // cannot false-fire on a legacy configuration the way they would have
    // had to under the multi-model contract.
    //
    // Cost: a handful of comparators OFF the datapath — they are read only
    // at cmd_go, in the dispatcher's IDLE arm, beside the existing
    // unknown-opcode refusal.
    //
    // Reporting uses the EXISTING err_op/STATUS mechanism unchanged: the
    // command is refused (no state is touched, cmd_cnt still advances so a
    // polling host is not hung), STATUS[1] reads err_op, and seq_unit
    // halts the whole program on it with err_code 0x10.  err_op is latched
    // until the NEXT command dispatch, which is what "sticky" means here —
    // G3.4 did not change its lifetime, because seq_unit's contract and
    // every TB in the set are written against the existing one.
    wire [14:0] env_conv_end  = {1'b0, arg0[13:0]} + {1'b0, arg0[27:14]};
    wire [14:0] env_convw_end = {1'b0, arg0[15:2]} + {1'b0, arg0[29:16]};
    wire cmd_env_bad =
        // VN: n = 1 << nlog2 and the 9B envelope tops out at 4096.
           ((cmd_op == OP_VN)    && (arg0[5:2] > 4'd12))
        // VNW: the vecnorm wbuf is 4096 deep (G3.2) and 0 MEANS 0 — the
        // 0-encodes-the-top escape was retired with the width that needed
        // it, and ld_n = 0 would otherwise run a full 8192 wrap.
        || ((cmd_op == OP_VNW)   && ((arg0[12:0] > 13'd4096)
                                     || (arg0[12:0] == 13'd0)))
        // CONV / CONVW: first + nch must land inside the CVD-deep conv
        // bank, and nch = 0 is refused for the same reason — spec 4.6
        // wall 11's "an escape encoding that the width no longer needs is
        // a trap".  The emitter's twin is _conv_fields()'s 1 <= nch assert.
        || ((cmd_op == OP_CONV)  && ((env_conv_end  > 15'(CVD))
                                     || (arg0[27:14] == 14'd0)))
        || ((cmd_op == OP_CONVW) && ((env_convw_end > 15'(CVD))
                                     || (arg0[29:16] == 14'd0)))
        ;
        // S2: the `layer_dn > N_DN-1` term is DEAD — LAYER carries a
        // one-bit cache slot now, not a 0..23 bank index.  Its replacement
        // is the E_LAYER check below, which refuses ANY slot field above 1
        // at a compute command's dispatch (B15.2, B15.4).

    // ==================================================================
    // S2 — the dispatch-time checks the DMA lane and the fences add.
    // ==================================================================
    // B15.2: a slot field above 1 names a slot that does not exist.
    wire cmd_layer_bad = (layer_dn > 2'd1) || (layer_kv > 2'd1)
                         || (layer_cv > 2'd1);

    // which cache slot does the command in ARG/CMD use?
    wire cmd_uses_dn = (cmd_op == OP_DNST) || (cmd_op == OP_DNZ);
    wire cmd_uses_kv = (cmd_op == OP_KVAP) || (cmd_op == OP_ATTN);
    wire cmd_uses_cv = (cmd_op == OP_CONV) || (cmd_op == OP_CONVW);
    wire cmd_is_dma  = (cmd_op == OP_SLD)  || (cmd_op == OP_SST);
    // DNZ and CONVW sel 2 (CONVZ) WRITE the slot and warm it, so they are
    // legal on a cold slot (spec §5.5).
    wire cmd_warms   = (cmd_op == OP_DNZ)
                       || ((cmd_op == OP_CONVW) && (arg0[1:0] == 2'd2));

    // F1 (spec §5.4): a compute command whose slot has an SLD queued or in
    // flight waits — and so does one whose slot has ANY transfer IN FLIGHT,
    // because ownership is exclusive and a store would tear otherwise.
    // A queued STORE does not stall compute; F2 holds that store instead,
    // which is what keeps the second fence load-bearing.
    wire f1_dn = (sld_pend[0][layer_dn[0]] != 3'd0)
                 || (dma_act && (dma_kind == K_DN) && (dma_slot == layer_dn[0]));
    wire f1_kv = (sld_pend[1][layer_kv[0]] != 3'd0)
                 || (dma_act && (dma_kind == K_KV) && (dma_slot == layer_kv[0]));
    wire f1_cv = (sld_pend[2][layer_cv[0]] != 3'd0)
                 || (dma_act && (dma_kind == K_CV) && (dma_slot == layer_cv[0]));
    wire cmd_f1_stall = (SDMA_NOFENCE == 0)
                        && ((cmd_uses_dn && f1_dn) || (cmd_uses_kv && f1_kv)
                            || (cmd_uses_cv && f1_cv));
    wire cmd_cold = (SDMA_NOFENCE == 0) && !cmd_warms
                    && ((cmd_uses_dn && !warm[0][layer_dn[0]])
                        || (cmd_uses_kv && !warm[1][layer_kv[0]])
                        || (cmd_uses_cv && !warm[2][layer_cv[0]]));

    // B15.4's other E_DMA_RANGE causes on a COMPUTE command: CONVW sel 0/1
    // is retired (conv blocks arrive by SLD, spec §5.5), and KVAP/ATTN must
    // name the kvhead the slot's tag carries (A1.3).
    wire cmd_range_bad =
           ((cmd_op == OP_CONVW) && (arg0[1:0] != 2'd2))
        || (cmd_uses_kv && (arg0[1:0] != kv_tag[layer_kv[0]][1:0]));

    // B15.1's envelope on an SLD/SST, read straight off ARG0's fields.
    wire [1:0] sd_kind_a  = arg0[12:11];
    wire       sd_slot_a  = arg0[10];
    wire [4:0] sd_layer_a = arg0[9:5];
    wire [4:0] sd_head_a  = arg0[4:0];
    wire sdma_range_bad =
           (sd_kind_a == 2'd3)                       // kind 3 is reserved
        || (arg1 != 32'd0) || (arg2 != 32'd0)        // reserved for a row range
        || ((sd_kind_a == K_DN) && ((sd_layer_a > 5'(N_DN - 1))
                                    || (sd_head_a != 5'd0)))
        || ((sd_kind_a == K_CV) && ((sd_layer_a > 5'(N_DN - 1))
                                    || (sd_head_a != 5'd0)))
        || ((sd_kind_a == K_KV) && ((sd_layer_a > 5'(N_KV - 1))
                                    || (sd_head_a > 5'd7)
                                    || (tcnt_bank[sd_layer_a[2:0]]
                                                 [sd_head_a[2:1]] > 13'd4096)));
    wire sdma_base_bad = (sd_kind_a == K_DN) ? (sb_dn == 18'd0)
                       : (sd_kind_a == K_KV) ? (sb_kv == 18'd0)
                                             : (sb_cv == 18'd0);

    always_ff @(posedge aclk) begin
        if (!rstn_i) begin
            st <= IDLE;
            busy_cmp <= 1'b0; err_op <= 1'b0;
            sdma_err <= 8'h00; cmd_pend <= 1'b0;
            enq_v <= 1'b0; warm_set_v <= 1'b0;
            dn_slot_r <= 1'b0; kv_slot_r <= 1'b0; cv_slot_r <= 1'b0;
            kvt_r <= 5'd0;
            cmd_cnt <= '0;
            eout_q <= '0;
            vn_start <= 1'b0; rp_start <= 1'b0; gt_start <= 1'b0;
            dn_start <= 1'b0; at_start <= 1'b0; alu_start <= 1'b0;
            vn_wwe <= 1'b0; rp_twe <= 1'b0; gt_wwe <= 1'b0;
            dn_vwe <= 1'b0; at_qwe <= 1'b0;
            cv_ivalid <= 1'b0; cw_we <= 1'b0; cs_we <= 1'b0;
            kv_we <= 1'b0; kvx_we <= 1'b0; dnz_we <= 1'b0;
            vn_svalid <= 1'b0; rp_svalid <= 1'b0;
            vn_mready <= 1'b0; rp_mready <= 1'b0;
            dn_mready <= 1'b0; at_mready <= 1'b0;
            eng_swe <= 1'b0;
            tcnt_inc <= 1'b0;
        end else begin
            enq_v <= 1'b0; warm_set_v <= 1'b0;
            // one-cycle defaults
            vn_start <= 1'b0; rp_start <= 1'b0; gt_start <= 1'b0;
            dn_start <= 1'b0; at_start <= 1'b0; alu_start <= 1'b0;
            vn_wwe <= 1'b0; rp_twe <= 1'b0; gt_wwe <= 1'b0;
            dn_vwe <= 1'b0; at_qwe <= 1'b0;
            cv_ivalid <= 1'b0; cw_we <= 1'b0; cs_we <= 1'b0;
            kv_we <= 1'b0; kvx_we <= 1'b0; dnz_we <= 1'b0;
            eng_swe <= 1'b0;
            tcnt_inc <= 1'b0;
            if (gt_done) gate_done_q <= 1'b1;

            // CONV output collector (no backpressure; <=1 write per cycle)
            if (st inside {CV_A, CV_W, CV_W2, CV_W3, CV_P, CV_D}
                && cv_ovalid) begin
                eng_swa <= dst_r + 16'(cvj);
                eng_swd <= cv_oy;
                eng_swe <= 1'b1;
                cvj <= cvj + 1'b1;
            end

            case (st)
                // ----------------------------------------------------
                // ----------------------------------------------------
                // S2: three arms — the DMA lane (never sets busy_cmp), the
                // F1 stall (busy_cmp high, st still IDLE, so the command
                // does NOT hold its slot and F2 cannot deadlock against
                // it), and the compute dispatch this file always had.
                IDLE: if (cmd_is_dma && (cmd_go || cmd_pend)) begin
                    if (dq_full && !sdma_range_bad && !sdma_base_bad) begin
                        // The queue is FOUR deep (spec §5.4) and the accept
                        // gate is busy_cmp, so five SLD/SST records issued
                        // faster than one transfer completes would otherwise
                        // be SILENTLY DROPPED.  Hold the record instead — it
                        // has not been enqueued, so it has not retired.
                        // cmd_pend keeps cmp_holds low, so F2 still lets the
                        // queue drain and the hold cannot deadlock.
                        busy_cmp <= 1'b1;
                        cmd_pend <= 1'b1;
                    end else begin
                        // B15.3: cmd_cnt increments when an SLD/SST is
                        // ENQUEUED, refused or not, so a polling host is
                        // never hung.  The DMA lane never sets busy_cmp.
                        busy_cmp <= 1'b0;
                        cmd_pend <= 1'b0;
                        cmd_cnt  <= cmd_cnt + 1'b1;
                        if (sdma_err != E_DMA_AXI) begin
                            err_op <= 1'b0; sdma_err <= 8'h00;
                        end
                        // B15.4: E_DMA_AXI is sticky until the host writes
                        // SDMA, so a LATER refusal must not overwrite the
                        // code (fix round 1, I4) — err_op still sets.
                        if (sdma_range_bad) begin
                            err_op <= 1'b1;
                            if (sdma_err != E_DMA_AXI) sdma_err <= E_DMA_RANGE;
                        end else if (sdma_base_bad) begin
                            err_op <= 1'b1;
                            if (sdma_err != E_DMA_AXI) sdma_err <= E_DMA_BASE;
                        end else begin
                            enq_v     <= 1'b1;
                            enq_store <= (cmd_op == OP_SST);
                            enq_kind  <= sd_kind_a;
                            enq_slot  <= sd_slot_a;
                            enq_layer <= sd_layer_a;
                            enq_head  <= sd_head_a[2:0];
                        end
                    end
                end else if ((cmd_go || cmd_pend) && cmd_f1_stall) begin
                    // F1: hold the command at dispatch.  busy_cmp closes the
                    // accept gate and LCYC counts the stall, so any fence
                    // cost is visible in the layer-term census (spec §8.5).
                    busy_cmp <= 1'b1;
                    cmd_pend <= 1'b1;
                end else if (cmd_go || cmd_pend) begin
                    busy_cmp <= 1'b1;
                    cmd_pend <= 1'b0;
                    // spec A1.4: E_DMA_AXI is STICKY across a dispatch —
                    // the program must halt, not sail on.
                    if (sdma_err != E_DMA_AXI) begin
                        err_op <= 1'b0; sdma_err <= 8'h00;
                    end
                    fi <= '0; ci <= '0; ld_i <= '0;
                    rnd <= 1'b0; ki <= '0; eq <= '0; kmax <= '0;
                    wi <= '0; wk <= '0; cvi <= '0; cvj <= '0;
                    gi <= '0; zi <= '0; rcvd <= '0;
                    gate_done_q <= 1'b0;
                    // The ARG FIELD widths are the ISA's (SEQ_ISA v2.0:
                    // head = arg0[4:0], kvhead = arg0[1:0]) and are written
                    // as LITERAL slices on purpose -- they are what
                    // evidence/qwen9b/g3/isa_bits.py reads out of this file
                    // to prove encoder and decoder agree.  At this geometry
                    // HB = 5 and KHB = 2, so field and datapath are the same
                    // width; a mismatch is a lint WIDTHTRUNC here, not a
                    // silent truncation.
                    dn_head <= arg0[4:0];
                    kvhead_r <= arg0[1:0];
                    // S2: the CACHE slots, latched for the command's
                    // duration, plus the KV slot's tag (spec A1.3).
                    dn_slot_r <= layer_dn[0];
                    kv_slot_r <= layer_kv[0];
                    cv_slot_r <= layer_cv[0];
                    kvt_r     <= kv_tag[layer_kv[0]];
                    // S9 + B15.4: refuse an out-of-envelope command the way
                    // an unknown opcode is refused (err_op + DONE_S), BEFORE
                    // any unit is started or any slot address is formed, and
                    // report WHICH refusal in SDMA.err.
                    // Each refusal sets err_op and its own code — except
                    // while E_DMA_AXI is standing, which B15.4 makes sticky
                    // until the host writes SDMA (fix round 1, I4).
                    if (cmd_layer_bad) begin
                        err_op <= 1'b1;
                        if (sdma_err != E_DMA_AXI) sdma_err <= E_LAYER;
                        st <= DONE_S;
                    end else if (cmd_env_bad) begin
                        err_op <= 1'b1;
                        if (sdma_err != E_DMA_AXI) sdma_err <= E_ENV;
                        st <= DONE_S;
                    end else if (cmd_range_bad) begin
                        err_op <= 1'b1;
                        if (sdma_err != E_DMA_AXI) sdma_err <= E_DMA_RANGE;
                        st <= DONE_S;
                    end else if (cmd_cold) begin
                        err_op <= 1'b1;
                        if (sdma_err != E_DMA_AXI) sdma_err <= E_DMA_COLD;
                        st <= DONE_S;
                    end else begin
                        if (cmd_warms) begin
                            warm_set_v    <= 1'b1;
                            warm_set_kind <= (cmd_op == OP_DNZ) ? K_DN : K_CV;
                            warm_set_slot <= (cmd_op == OP_DNZ) ? layer_dn[0]
                                                                : layer_cv[0];
                        end
                        case (cmd_op)
                        OP_VN: begin
                            n_elems <= 16'd1 << arg0[5:2];
                            dst_r <= a1_dst;
                            vn_start <= 1'b1;
                            eng_sa <= a1_src;
                            st <= F_A;
                        end
                        OP_ROPE: begin
                            n_elems <= 16'd256;
                            dst_r <= a1_dst;
                            rp_start <= 1'b1;
                            eng_sa <= a1_src;
                            st <= F_A;
                        end
                        OP_VNW: begin
                            // G3.1: ld_n/ld_i are 13 bits and the field
                            // is arg0[12:0], so 4096 is carried DIRECTLY
                            // and there is NO 0-encodes-2048 escape any
                            // more -- ld_n = 0 would run the full 8192
                            // wrap, which the emitter refuses.  G3.2 made
                            // the wbuf 4096 deep (vn_waddr[11:0]), so the
                            // FIELD and the DATAPATH now agree at 4096.
                            ld_tgt <= LT_VNW; ld_n <= arg0[12:0];
                            ld_src <= a1_src; eng_sa <= a1_src;
                            st <= L_A;
                        end
                        OP_ROPET: begin
                            ld_tgt <= LT_ROPET; ld_n <= 13'd128;
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
                            ld_tgt <= LT_GB; ld_n <= 13'(LNH);
                            ld_src <= a1_src; eng_sa <= a1_src;
                            dst_r <= arg0[15:0];
                            st <= L_A;
                        end
                        OP_DNST: begin
                            ld_tgt <= LT_DDEC; ld_n <= 13'd1;
                            // SEQ_ISA v2.0: a_dec = DNSB[31:16] + head.
                            // arg0[4:0] is the head and the whole of the
                            // rest of ARG0 is spare.
                            ld_src <= dnsb_dec + 16'(arg0[4:0]);
                            eng_sa <= dnsb_dec + 16'(arg0[4:0]);
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
                            ld_tgt <= LT_AQ; ld_n <= 13'd256;
                            ld_src <= a1_src; eng_sa <= a1_src;
                            dst_r <= a1_dst;
                            n_col <= 10'd256;
                            // spec A1.3: T comes from the TAG of the slot
                            // LAYER names, not from a layer field.  kvt_r
                            // latches this same cycle, so read kv_tag live.
                            at_cfg_t <=
                                tcnt_bank[kv_tag[layer_kv[0]][4:2]]
                                         [kv_tag[layer_kv[0]][1:0]];
                            st <= L_A;
                        end
                        OP_ALU: begin
                            alu_start <= 1'b1;
                            st <= A_RUN;
                        end
                        OP_DNZ: st <= Z_W;
                        default: begin
                            err_op <= 1'b1;
                            if (sdma_err != E_DMA_AXI) sdma_err <= E_ENV;
                            st <= DONE_S;
                        end
                        endcase
                    end
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
                    eng_sa <= eng_sa + 16'd1;
                    f_ai   <= 16'd1;
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
                        eng_sa <= eng_sa + 16'd1;
                        f_ai   <= f_ai + 16'd1;
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
                        eng_swa <= dst_r + 16'(ci);
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
                            vn_wwe <= 1'b1; vn_waddr <= ld_i[11:0];
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
                                ld_tgt <= LT_GA; ld_n <= 13'(LNH);
                                ld_src <= a1_dst; eng_sa <= a1_dst;
                                st <= L_A;
                            end
                            LT_GA: begin
                                ld_tgt <= LT_GAA; ld_n <= 13'(2*LNH);
                                ld_src <= a2_src; eng_sa <= a2_src;
                                st <= L_A;
                            end
                            LT_GAA: begin
                                ld_tgt <= LT_GDT; ld_n <= 13'(LNH);
                                ld_src <= a2_dst; eng_sa <= a2_dst;
                                st <= L_A;
                            end
                            LT_GDT: begin
                                gt_start <= 1'b1;
                                st <= RUN_W;
                            end
                            LT_DDEC: begin
                                // SEQ_ISA v2.0: a_beta = DNSB[15:0] + head
                                ld_tgt <= LT_DBET; ld_n <= 13'd1;
                                ld_src <= dnsb_beta + 16'(dn_head);
                                eng_sa <= dnsb_beta + 16'(dn_head);
                                st <= L_A;
                            end
                            LT_DBET: begin
                                ld_tgt <= LT_DK; ld_n <= 13'd128;
                                ld_src <= a1_dst; eng_sa <= a1_dst;
                                st <= L_A;
                            end
                            LT_DK: begin
                                ld_tgt <= LT_DQ; ld_n <= 13'd128;
                                ld_src <= a1_src; eng_sa <= a1_src;
                                st <= L_A;
                            end
                            LT_DQ: begin
                                ld_tgt <= LT_DV; ld_n <= 13'd128;
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
                        eng_sa <= ld_src + 16'(ld_i) + 16'd1;
                        st <= L_A;
                    end
                end

                // ---------- gate run + store ----------
                RUN_W: if (gate_done_q || gt_done) st <= G_ST;
                G_ST: begin
                    eng_swa <= dst_r + 16'(gi);
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
                        logic [15:0] off;
                        md  = (cmd_op == OP_DNST) ? dn_mdata : at_mdata;
                        off = (cmd_op == OP_DNST) ? 16'(dn_midx)
                                                  : 16'(at_midx);
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
                    eng_swa <= eng_swa + 16'd1;
                    eng_swd <= signed'(m_hi);
                    eng_swe <= 1'b1;
                    if (rcvd == n_col) st <= DONE_S;
                    else st <= D_RDY;
                end

                // ---------- conv run ----------
                CV_A: begin
                    if (cvi == arg0[27:14]) st <= CV_D;
                    else begin
                        eng_sa <= a1_src + 16'(cvi);
                        cw_ra <= 13'(arg0[13:0] + cvi);
                        cs_ra <= 13'(arg0[13:0] + cvi);
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
                    cs_wa <= 13'(arg0[13:0] + cvi);
                    cs_wd <= {unsigned'(sa_q), cs_q[47:16]};
                    cs_we <= 1'b1;
                    cvi <= cvi + 1'b1;
                    st <= CV_A;
                end
                CV_D: if (cvj == arg0[27:14]) st <= DONE_S;

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
                            cw_wa <= 13'(arg0[15:2] + wi);
                            cw_wd <= {unsigned'(sa_q), tmp64[47:0]};
                        end else begin
                            cs_we <= 1'b1;
                            cs_wa <= 13'(arg0[15:2] + wi);
                            cs_wd <= {unsigned'(sa_q), tmp64[31:0]};
                        end
                        if (wi + 1'b1 == arg0[29:16]) st <= DONE_S;
                        else begin
                            wi <= wi + 1'b1;
                            eng_sa <= eng_sa + 16'd1;
                            st <= CW_A;
                        end
                    end else begin
                        wk <= wk + 1'b1;
                        eng_sa <= eng_sa + 16'd1;
                        st <= CW_A;
                    end
                end
                CZ_W: begin
                    cs_we <= 1'b1;
                    cs_wa <= 13'(arg0[15:2] + wi);
                    cs_wd <= '0;
                    if (wi + 1'b1 == arg0[29:16]) st <= DONE_S;
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
                                  + 16'(ki) + 16'd1;
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
                                  + 16'(ki) + 16'd1;
                        st <= K2_A;
                    end
                end
                K_WR: begin
                    kv_we  <= 1'b1;
                    kvx_we <= 1'b1;
                    // S2: the slot holds K and V for ONE (layer, kvhead), so
                    // the address is {kv, t[11:0]} and the kvhead is the
                    // slot's tag, not an address field (spec A1.3).
                    kv_waddr <= {rnd, tcnt_bank[kvt_r[4:2]][kvhead_r][11:0]};
                    kv_wrow <= krow;
                    kv_wexp <= 8'(signed'({4'b0, eq}) - signed'({3'b0, kv_expbias}));
                    if (!rnd) begin
                        rnd <= 1'b1;
                        ki <= '0; eq <= '0; kmax <= '0;
                        eng_sa <= a1_dst;
                        st <= KQ_A;
                    end else begin
                        tcnt_inc <= 1'b1;  // CSR: +1 tcnt_bank[tag]
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
                    busy_cmp <= 1'b0;
                    cmd_cnt <= cmd_cnt + 1'b1;
                    st <= IDLE;
                end
                default: st <= IDLE;
            endcase

            // B15.3: a write to SDMA clears err (and err_op if it was set
            // by E_DMA_AXI); the completion of an errored transfer sets
            // both.  Both are LAST in this block so they win over the
            // clear-at-dispatch above.
            if (sdma_clr) begin
                if (sdma_err == E_DMA_AXI) err_op <= 1'b0;
                sdma_err <= 8'h00;
            end
            if (dma_err_p) begin
                err_op   <= 1'b1;
                sdma_err <= E_DMA_AXI;
            end
        end
    end

    // ==================================================================
    // S2 — THE DMA LANE (spec §5.4, §4; SEQ_ISA v2.1 B15.5)
    //
    // An in-order queue of four {store, kind, slot, layer, head} records,
    // one transfer in flight, and the two fences.  F1 lives in the
    // dispatcher (a compute command stalls or is refused there); F2 lives
    // HERE, at the head of the queue.
    //
    // Why the two cannot deadlock: an F1-stalled command sits in IDLE with
    // `cmd_pend` set and therefore does NOT hold its slot, so a transfer
    // waiting on F2 is never waiting on a command waiting on it.
    // ==================================================================
    // A command that is RUNNING holds the slot its dispatch latched.
    wire cmp_holds = busy_cmp && !cmd_pend;
    // ...and a command that DISPATCHES THIS CYCLE claims one too.  Without
    // this term F2 has a one-cycle hole (fix round 1, C1): `cmp_holds` and
    // the F1 stall condition are registered in different always_ff blocks,
    // so on the cycle F1 RELEASES a stalled command the DMA lane still sees
    // `cmd_pend = 1`, concludes that nothing holds the slot, and starts the
    // queued transfer on that very slot — the dispatcher's third arm and the
    // pop fire together and the DMA owns a slot the command is using.
    // The wire is the third arm's own condition, and its slot comes from the
    // LIVE LAYER fields because `*_slot_r` has not latched yet.  It cannot
    // deadlock: it is high only in the cycle a command dispatches, and a
    // dispatched command always terminates.
    wire cmp_claim = (st == IDLE) && !cmd_is_dma && (cmd_go || cmd_pend)
                     && !cmd_f1_stall;
    wire [1:0] hd_kind  = dq_kind [dq_rp[1:0]];
    wire       hd_slot  = dq_slot [dq_rp[1:0]];
    wire       hd_store = dq_store[dq_rp[1:0]];
    wire [4:0] hd_layer = dq_layer[dq_rp[1:0]];
    wire [2:0] hd_head  = dq_head [dq_rp[1:0]];
    wire hd_f2 =
        ((hd_kind == K_DN) && cmd_uses_dn
          && ((cmp_holds && (dn_slot_r   == hd_slot))
           || (cmp_claim && (layer_dn[0] == hd_slot))))
     || ((hd_kind == K_KV) && cmd_uses_kv
          && ((cmp_holds && (kv_slot_r   == hd_slot))
           || (cmp_claim && (layer_kv[0] == hd_slot))))
     || ((hd_kind == K_CV) && cmd_uses_cv
          && ((cmp_holds && (cv_slot_r   == hd_slot))
           || (cmp_claim && (layer_cv[0] == hd_slot))));

    // B15.1's address adder, and the transfer length.  The three shifts are
    // the SDMA_BITS: SHIFT_* localparams, so what the hardware applies is
    // what evidence/qwen9b/s1/sdma_bits.py reads.
    wire [17:0] hd_sb  = (hd_kind == K_DN) ? sb_dn
                       : (hd_kind == K_KV) ? sb_kv : sb_cv;
    wire [33:0] hd_off = (hd_kind == K_DN)
                       ? (34'(hd_layer) << SDMA_SHIFT_DN)
                       : (hd_kind == K_KV)
                       ? (34'({hd_layer[2:0], hd_head}) << SDMA_SHIFT_KV)
                       : (34'(hd_layer) << SDMA_SHIFT_CV);
    wire [33:0] hd_addr = {hd_sb, 16'b0} + hd_off;
    wire [13:0] hd_rows = (hd_kind == K_DN) ? 14'd4096
                        : (hd_kind == K_CV) ? 14'd8192
                        : 14'(tcnt_bank[hd_layer[2:0]][hd_head[2:1]]);

    assign busy_dma = dma_act | ~dq_empty;

    always_ff @(posedge aclk) begin
        if (!rstn_i) begin
            dq_wp <= '0; dq_rp <= '0;
            dma_act <= 1'b0; sd_go <= 1'b0; dma_err_p <= 1'b0;
            dma_store <= 1'b0; dma_kind <= 2'd0; dma_slot <= 1'b0;
            dma_kvbit <= 1'b0; dma_tag <= 5'd0;
            sd_store <= 1'b0; sd_kind <= 2'd0; sd_addr34 <= '0; sd_rows <= '0;
            last_kind <= 2'd0; last_slot <= 1'b0;
            for (int k = 0; k < 3; k++)
                for (int sl = 0; sl < N_SLOT; sl++) begin
                    warm[k][sl]     <= 1'b0;   // every slot comes out cold
                    sld_pend[k][sl] <= 3'd0;
                end
            for (int sl = 0; sl < N_SLOT; sl++) kv_tag[sl] <= 5'd0;
        end else begin
            logic ld_enq, ld_ret, same_slot;
            sd_go     <= 1'b0;
            dma_err_p <= 1'b0;
            ld_enq = enq_v && !enq_store;
            ld_ret = dma_act && sd_done && !dma_store;
            same_slot = ld_enq && ld_ret && (enq_kind == dma_kind)
                        && (enq_slot == dma_slot);

            // ---- enqueue (the dispatcher already refused the illegal) ----
            if (enq_v) begin
                dq_store[dq_wp[1:0]] <= enq_store;
                dq_kind [dq_wp[1:0]] <= enq_kind;
                dq_slot [dq_wp[1:0]] <= enq_slot;
                dq_layer[dq_wp[1:0]] <= enq_layer;
                dq_head [dq_wp[1:0]] <= enq_head;
                dq_wp <= dq_wp + 1'b1;
            end

            // ---- DNZ / CONVZ warm the slot they write (spec §5.5) ----
            if (warm_set_v) warm[warm_set_kind][warm_set_slot] <= 1'b1;

            // ---- F2, then start ONE transfer ----
            if (!dma_act && !dq_empty && !hd_f2) begin
                dma_act   <= 1'b1;
                dma_store <= hd_store;
                dma_kind  <= hd_kind;
                dma_slot  <= hd_slot;
                dma_kvbit <= hd_head[0];      // the KV block's K/V half
                dma_tag   <= {hd_layer[2:0], hd_head[2:1]};
                last_kind <= hd_kind;
                last_slot <= hd_slot;
                sd_go     <= 1'b1;
                sd_store  <= hd_store;
                sd_kind   <= hd_kind;
                sd_addr34 <= hd_addr;
                sd_rows   <= hd_rows;
                dq_rp     <= dq_rp + 1'b1;
            end

            // ---- completion ----
            if (dma_act && sd_done) begin
                dma_act <= 1'b0;
                // spec §5.4: a store makes the slot COLD (the lost-update
                // guard); a load warms it and, for KV, sets its tag (A1.3).
                if (dma_store) warm[dma_kind][dma_slot] <= 1'b0;
                else begin
                    warm[dma_kind][dma_slot] <= 1'b1;
                    if (dma_kind == K_KV) kv_tag[dma_slot] <= dma_tag;
                end
                if (sd_err) dma_err_p <= 1'b1;
            end

            // ---- the F1 pending-LOAD counters, one update per slot ----
            if (!same_slot) begin
                if (ld_enq)
                    sld_pend[enq_kind][enq_slot]
                        <= sld_pend[enq_kind][enq_slot] + 3'd1;
                if (ld_ret)
                    sld_pend[dma_kind][dma_slot]
                        <= sld_pend[dma_kind][dma_slot] - 3'd1;
            end
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
    wire [15:0] bw_addr, br_addr;
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
        .core_busy(busy_cmp), .core_hw_we(hw_we),
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
    // S2: the priority bit is busy_CMP.  The DMA lane never touches the
    // scratchpad, so busy_any would only make the burst window answer
    // SLVERR for no reason.
    wire cmd_is_alu = (cmd_op == OP_ALU);
    wire alu_owns   = busy_cmp && cmd_is_alu;
    wire bw_grant   = bw_we && !hw_we;
    wire sa_sub     = busy_cmp ? cmd_is_alu : br_en;
    wire sw_sub     = busy_cmp ? cmd_is_alu : bw_grant;

    assign sa_addr = busy_cmp ? (sa_sub ? alu_aa : eng_sa)
                              : (sa_sub ? br_addr : sptr);
    assign sb_addr = alu_owns ? alu_ba : '0;
    assign sw_en   = busy_cmp ? (sw_sub ? alu_we : eng_swe)
                              : (sw_sub ? 1'b1 : hw_we);
    assign sw_addr = busy_cmp ? (sw_sub ? alu_wa : eng_swa)
                              : (sw_sub ? bw_addr : hw_addr);
    assign sw_data = busy_cmp ? (sw_sub ? alu_wd : eng_swd)
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

    // Fix round 1, I1: `cmd_range_bad` refuses a KVAP/ATTN whose kvhead
    // differs from the slot's tag, so the latched ARG field and the tag's
    // kvhead — the two the append-counter index is formed from — cannot
    // disagree for a command that actually runs.  Check it rather than
    // assert it in prose.
    // Checked where the two are actually USED, not at dispatch: a REFUSED
    // KVAP/ATTN latches both and then goes straight to DONE_S, and the whole
    // point of the refusal is that they disagreed.
    always_ff @(posedge aclk) begin
        if (rstn_i && (at_start || kv_we) && (kvhead_r !== kvt_r[1:0]))
            $fatal(1, "layer_chan: kvhead_r %0d != slot tag kvhead %0d",
                   kvhead_r, kvt_r[1:0]);
    end

    // G3.4 RETIRED the G3.1 DATAPATH-ENVELOPE $fatal block that stood
    // here.  Every guard it carried was a SIM-ONLY `ifndef SYNTHESIS
    // check standing in for a datapath that had not been widened yet:
    //   * DNST/DNZ head >= 16   -- the DN banking is 32 heads now
    //   * KVAP/ATTN kvhead >= 2 -- the KV banking is 4 heads now
    //   * CONV/CONVW past 6144  -- the conv banks are CVD = 8192 now
    //   * VNW len > 4096        -- unchanged in VALUE but no longer
    //                              sim-only: it moved into the
    //                              SYNTHESIZABLE envelope above, with the
    //                              conv reach and the VN n_log2, because
    //                              spec 5.4 S9's whole point is that a
    //                              sim-only guard protects nothing on
    //                              silicon.  U4 is what makes the hard
    //                              check cheap: with ONE geometry there is
    //                              exactly one legal envelope and it
    //                              cannot false-fire on a legacy config.
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
    input  wire [17:0]  s_axib_awaddr,
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
    input  wire [17:0]  s_axib_araddr,
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
    output wire [15:0]  bw_addr,
    output wire [15:0]  bw_data,
    output wire         br_en,
    output wire [15:0]  br_addr,
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
    (* keep = "true" *) logic [15:0] bw_addr_r;
    (* keep = "true" *) logic [15:0] bw_data_r;
    (* keep = "true" *) logic        br_en_r;
    (* keep = "true" *) logic [15:0] br_addr_r;
    assign bw_we   = bw_we_r;
    assign bw_addr = bw_addr_r;
    assign bw_data = bw_data_r;
    assign br_en   = br_en_r;
    assign br_addr = br_addr_r;

    // ==================================================================
    // write channel
    // ==================================================================
    wire [25:0] aw_m;                   // {win_bad, awid, awaddr[17:2], awlen}
    wire        aw_mv;
    wire        aw_mr;
    layer_axib_skid #(.W(26)) u_aw (
        .clk(aclk), .rstn(rstn),
        .s_data({aw_win_bad, s_axib_awid, s_axib_awaddr[17:2], s_axib_awlen}),
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

    // S9 (spec 5.4): an out-of-window burst answers SLVERR, the way
    // matvec_chan already answers an out-of-XWIN write.  The 18-bit
    // address makes the START word structurally in-window (65536 words =
    // 256 KiB = 2**18 B exactly), so the case that is NOT structural is a
    // burst that RUNS OFF THE END: wa_ptr wraps to 0 and the tail of the
    // burst silently overwrites scratch words 0..n.  This was an
    // `ifndef SYNTHESIS $fatal only; G3.4 made it a HARDWARE refusal and
    // RETIRED the two $fatals, because a condition the hardware now
    // answers correctly must be observable in sim, not fatal in it.
    wire aw_win_bad = ({1'b0, s_axib_awaddr[17:2]} + 17'(s_axib_awlen))
                      > 17'd65535;
    wire ar_win_bad = ({1'b0, s_axib_araddr[17:2]} + 17'(s_axib_arlen))
                      > 17'd65535;

    logic [1:0]  wst;
    logic [15:0] wa_ptr;                // running scratch word address
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
                    wa_ptr <= aw_m[23:8];
                    wbeats <= 9'(aw_m[7:0]) + 9'd1;
                    s_axib_bid <= aw_m[24];
                    // S9: an off-the-end burst is BLOCKED (no beat is
                    // written) and answered SLVERR, exactly as a burst
                    // that arrives while the engine owns the port is.
                    wblk <= core_busy || aw_m[25];
                    werr <= core_busy || aw_m[25];
                    wst  <= W_DATA;
                end
                W_DATA: if (w_take) begin
                    wa_ptr <= wa_ptr + 16'd1;
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
    wire [25:0] ar_m;                   // {win_bad, arid, araddr[17:2], arlen}
    wire        ar_mv;
    wire        ar_mr;
    layer_axib_skid #(.W(26)) u_ar (
        .clk(aclk), .rstn(rstn),
        .s_data({ar_win_bad, s_axib_arid, s_axib_araddr[17:2], s_axib_arlen}),
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
                if (br_en_r) br_addr_r <= br_addr_r + 16'd1;
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
                    s_axib_rid <= ar_m[24];
                    rblk      <= core_busy || ar_m[25];
                    br_en_r   <= !core_busy && !ar_m[25];
                    br_addr_r <= ar_m[23:8];
                end
            end else if (rpop && s_axib_rlast) begin
                rd_busy <= 1'b0;
            end
        end
    end

`ifndef SYNTHESIS
    // window / burst-shape contract (RUNG3_SPEC S6, S7).  The 18-bit
    // address makes the START word structurally in-window; what is not
    // structural is 4-byte alignment, the beat size and INCR.  The
    // off-the-end case moved OUT of this block at G3.4 and into the
    // synthesizable window check above (spec 5.4 S9).
    always_ff @(posedge aclk) if (rstn) begin
        if (s_axib_awvalid && s_axib_awready) begin
            if (s_axib_awaddr[1:0] != 2'b00)
                $fatal(1, "s_axib: unaligned AWADDR %04h", s_axib_awaddr);
            if (s_axib_awsize != 3'd2)
                $fatal(1, "s_axib: AWSIZE %0d, only 4-byte beats", s_axib_awsize);
            if (s_axib_awburst != 2'b01)
                $fatal(1, "s_axib: AWBURST %0d, only INCR", s_axib_awburst);
        end
        if (s_axib_arvalid && s_axib_arready) begin
            if (s_axib_araddr[1:0] != 2'b00)
                $fatal(1, "s_axib: unaligned ARADDR %04h", s_axib_araddr);
            if (s_axib_arsize != 3'd2)
                $fatal(1, "s_axib: ARSIZE %0d, only 4-byte beats", s_axib_arsize);
            if (s_axib_arburst != 2'b01)
                $fatal(1, "s_axib: ARBURST %0d, only INCR", s_axib_arburst);
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
