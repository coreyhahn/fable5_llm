// seq_unit: the on-chip command sequencer (rung 1, docs/SEQUENCER_PLAN.md).
//
// It executes the binary SEQ record stream frozen in docs/SEQ_ISA.md v1.2 /
// ref/seq_format.py directly from DDR, replaying — instruction for
// instruction — the CSR sequence sw/infer.py issues from the host today.
// Nothing about the arithmetic changes: the same ARG0..2 + CMD writes hit
// the same layer_chan, the same WBASE/BEATS/SHAPE + doorbell hit the same
// matvec_chan, so the whole verification ladder carries.
//
//   fetch      AXI4 read master (128-bit) -> record prefetch FIFO
//   decode     ISA v1.2 with ref/seq_format.validate semantics; anything
//              the validator rejects raises err and halts
//   issue      AXI-Lite MASTER through the EXISTING interconnect
//   movers     seq_movers (MOVX / MVGO / MOVY / FENCE drain)
//   bulk       LDC + EMB: DDR read -> layer scratch burst write
//   burst      AXI4 32-bit READ_WRITE master m_axib (rung 3, S3) owned by
//              seq_movers: the MOVX/MOVY/LDC/EMB DATA streams, on a private
//              map (mvchan_c at (c+1)<<16, 64 KiB each; layer_0 at 6<<16,
//              128 KiB since R-b) through the new burst_smc SmartConnect.  CSR/poll/doorbell
//              traffic did NOT move — it is still AXI-Lite, bit-identical.
//   CSR        its own AXI-Lite slave = the ISA's 0x2nn sequencer space
//
// ---------------------------------------------------------------------
// AXI-Lite slave map (SEQ CSR block, 4 KB window; ISA 0x2nn space)
// ---------------------------------------------------------------------
//   0x00 CTRL     W  bit0 START, bit1 ABORT   R {29'b0, halted, err, busy}
//   0x04 STATUS   R  {err_code[31:24], of_ovf[23], out_cnt[22:16],
//                     13'b0, halted[2], err[1], busy[0]}       (S6)
//   0x08 BASE_LO  RW record-list DDR byte address [31:0]
//   0x0C BASE_HI  RW record-list DDR byte address [33:32]
//   0x10 LEN      RW records in the stream
//   0x14 PC       R  current record index
//   0x18 OUT_FIFO R  {valid, 13'b0, token[17:0]} — read-drains one entry
//   0x1C OUT_CNT  R  {25'b0, entries[6:0]} in the OUT FIFO (depth 64, S6)
//   0x20 TCNT_SEQ RW token counter consumed by JMP flags 0x1  (ISA SOFF)
//   0x24 ENTRY    RW record index START jumps to
//   0x28 IDENT    R  0xFAB1E5E0
//   0x2C PERF_CYC R  cycles busy since START
//   0x30 PERF_REC R  records retired since START
//   0x34 PERF_AXW R  AXI-Lite writes issued
//   0x38 PERF_AXR R  AXI-Lite reads issued
//   0x3C PERF_FST R  cycles the issue FSM waited on an empty fetch FIFO
//   0x40 + 4*i    RW XRF[i], i = 0..7 (18-bit; [3] unsigned, rest signed)
//   0x60 EMBLOG2  RW log2 of the EMB row size in bytes, reset 13 (8192 B).
//                 HOST-ONLY (not reachable from the ISA's 0x2nn CSRWR
//                 space); legal 8..13, a write outside that range is
//                 rejected and $error'd.  R-b: one bitstream serves H=1024
//                 (11) and H=2048 (12).
//   0x64 SEQ_CAPS R  {24'hFAB1CA, 5'b0, r3, r2, r1} (docs/SEQ_ISA.md v2.3
//                 B17.0): the capabilities this RTL implements — r1 = 1
//                 (the FENCE channel mask, B17.1), r2 = 1 (SR12: the XWIN
//                 start word, the RES start row and the SHAPE bank bits,
//                 B17.2), r3 = 1 (R3-8: the MOVX broadcast, B17.3).  HOST-ONLY, read-only;
//                 writes fall through (no write decode).  The literal is
//                 tied to sw/hwmap.py's seq_caps_word by tb_seq_unit.
//   0x100..0x1FC  R  BM1 idle counters (docs/SEQ_ISA.md B16, v2.2): 0x100
//                 BM_IDENT 0xFAB1B301, 0x104..0x128 and 0x130/0x134 the
//                 counters, the rest read 0.  Host-read-only; cleared by
//                 START, counted while busy, frozen at HALT.  See the
//                 "BM1 idle counters" block below.
//
// ---------------------------------------------------------------------
// err_code (STATUS[31:24])
// ---------------------------------------------------------------------
//   0x01 unknown opcode              0x02 bad indirection code
//   0x03 XRF index out of range      0x04 illegal flags for the opcode
//   0x05 engine channel >= 4         0x06 reserved field non-zero
//   0x07 unknown CSR space           0x08 JMP target outside the stream
//   0x09 pc outside the stream       0x0A illegal XOP sign code
//   0x0B unaligned LDC/EMB address   0x0C host ABORT
//   0x0D command envelope (S9): MVGO SHAPE ng outside 1..96
//   0x10 layer_chan err_op           0x11 layer CMD watchdog
//   0x12 AXI-Lite SLVERR/DECERR
//   0x20 matvec err_rresp            0x21 matvec done watchdog
//   0x22 XWIN fifo overflow          0x23 mover stream watchdog
//
// ---------------------------------------------------------------------
// XRF: where it lives, and why (the wave-2 ruling)
// ---------------------------------------------------------------------
// The MASTER copy of the XRF lives HERE, not in layer_chan, because every
// record with indirection needs it combinationally at decode: a fabric
// round trip per indirection (1656 indirected records per model_v2 token,
// ~10-20 cycles each through the SmartConnect + register slices) would be
// pure added latency on the critical issue path.
//
// The ISA makes the XRF WRITES a side effect of a command retiring
// ("DYNQ8 retires -> XRF[0]; DYNQ16 retires -> XRF[1]/XRF[2]"), which is a
// few hundred events per token, not one per record.  seq_unit therefore
// REFRESHES its mirror with a single AXI-Lite read after exactly those
// commands — it knows which ones because it issued ARG0/ARG1/ARG2 itself:
//
//   ALU sub-op 0  (DYNQ8)  -> read layer EOUT   0x1C   -> XRF[0]   (e_x)
//   ALU sub-op 12 (DYNQ16) -> read layer XRFRD_BASE + 4*(arg2[0] ? 2 : 1)
//                                                      -> XRF[1]/XRF[2]
//
// The DYNQ8 path needs NOTHING new: EOUT is a shipped, silicon-proven CSR.
// Only the DYNQ16 path needs an agent-C interface, and the assumption is
// deliberately the cheapest possible one:
//
//   RECONCILED against agent C's landed layer_chan (commit 9785771, ISA
//   v1.3): the XRF lives there behind an INDEX/DATA window —
//     0x38 XRFI  RW {29'b0, idx[2:0]}
//     0x3C XRFD  RW XRF[XRFI], read {14'b0, raw18}, write raw18 = d[17:0]
//   so a refresh is write(XRFI) -> drain -> read(XRFD), and DYNQ8 keeps
//   using the cheaper single EOUT read.  Offsets are parameters.
//
// USE_XRF_SIDEBAND=1 instead takes the value from a direct port
// (xrf_sb_we/idx/data) driven by layer_chan and skips the read entirely.
// Both are implemented; tb_seq_unit measures both.  The AXI-Lite mirror is
// the DEFAULT because it needs no new top-level wiring and the measured
// cost is ~0.05 ms/token — 0.3% of the sequencer's fabric time.
//
// COHERENCE THE OTHER WAY.  layer_chan's XRF is not write-only from the
// engine's point of view: vecnorm EPS-NORM reads k from xrf[arg2[3:1]].
// So every XRF write the SEQ makes from a record (CSRWR to the 0x2nn XRF
// space, XOP, AMAXL) is ALSO written through to layer_chan's XRFI/XRFD
// window (XRF_WRITE_THROUGH, default on).  It costs 2 AXI-Lite writes on
// ~11 records per token, and it means the two copies can never disagree.
//
// XRF WRITERS the SEQ must sniff, from the ARG shadow it issued itself
// (layer_chan header + ISA v1.3):
//   ALU sub-op 0  DYNQ8            -> XRF[0]                 (read EOUT)
//   ALU sub-op 12 DYNQ16           -> XRF[arg2[0] ? 2 : 1]   (XRFI/XRFD)
//   ALU sub-op 8  EMUL32 + p0[6]   -> XRF[2]  (op-8 k_a probe, ISA v1.3)
//
// ---------------------------------------------------------------------
// Ordering rule used throughout (AXI has NO ordering between the read and
// write channels): whenever a read must observe the effect of a write —
// CMD then STATUS poll, SPTR then SWIN read, doorbell then STATUS — the
// writes are DRAINED first (wr_idle).  Writes to one slave stay ordered
// among themselves, so ARG0..2 -> CMD and WBASE.. -> CTRL need no drain.
//
// RUNG 3 EXTENDS THAT RULE ACROSS PORTS.  m_axil and m_axib are two
// independent masters into the same slaves, so nothing orders a burst
// against a CSR access.  Every crossing point drains: XPTR (AXI-Lite) is
// drained before the XWIN burst starts, and each burst WRITE stream is
// drained to its last B response before the record retires (X_END, Y_END,
// I_BULKEND) so the next record's CSR traffic can never overtake it.

`timescale 1ns/1ps
`default_nettype none

module seq_unit #(
    parameter int ADDR_W        = 34,     // AXI4 read master address width
    parameter int FETCH_DEPTH   = 64,     // record prefetch FIFO (records)
    parameter int FETCH_BURST   = 16,     // beats per fetch burst (16 B each)
    parameter int FETCH_OUT     = 4,      // outstanding fetch bursts
    parameter int BULK_BURST    = 4,      // beats per LDC/EMB burst
    parameter int BULK_DEPTH    = 64,     // LDC/EMB word FIFO
    parameter int AXIL_OUT      = 12,     // outstanding AXI-Lite per channel
    /* verilator lint_off UNUSEDPARAM */
    // RETIRED by rung 3 (RUNG3_SPEC S8): the MOVY RES read is a burst on
    // m_axib and the shim honours READ_LATENCY_B=2, so there is no pacer
    // left to configure.  The parameter is kept so existing testbench
    // instantiations still elaborate; it has no effect.
    parameter int RES_GAP       = 3,
    /* verilator lint_on UNUSEDPARAM */
    parameter int MVGO_GUARD    = 64,     // see seq_movers C2
    parameter int TIMEOUT_LOG2  = 26,
    parameter bit USE_XRF_SIDEBAND = 1'b0,
    parameter bit XRF_WRITE_THROUGH = 1'b1,
    parameter logic [11:0] XRFI_OFF   = 12'h038,   // layer_chan XRF index
    parameter logic [11:0] XRFD_OFF   = 12'h03C,   // layer_chan XRF data
    parameter logic [31:0] LAYER_BASE = 32'h0000_5000,
    parameter logic [31:0] MV_BASE    = 32'h0000_1000,
    parameter logic [31:0] MV_STRIDE  = 32'h0000_1000,
    // m_axib burst map (RUNG3 S4 + R-b + G3.1): mvchan_c at (c+1)<<16,
    // 64 KiB each; layer_0 at 8<<16, 256 KiB (65536 scratch words).
    // 5<<16 .. 7<<16 is a decode HOLE — an AXI segment must be
    // range-aligned and 0x6_0000 (R-b's base) is not 256 KiB-aligned.
    // Private to this master — nothing else sees it.
    parameter logic [31:0] MVB_BASE   = 32'h0001_0000,
    parameter logic [31:0] MVB_STRIDE = 32'h0001_0000,
    parameter logic [31:0] LAYB_BASE  = 32'h0008_0000
) (
    input  wire         aclk,
    input  wire         aresetn,

    // ---------------- AXI-Lite slave: the SEQ CSR block ----------------
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

    // ---------------- AXI-Lite master: the issue port ------------------
    output logic [31:0] m_axil_awaddr,
    output logic        m_axil_awvalid,
    input  wire         m_axil_awready,
    output logic [31:0] m_axil_wdata,
    output logic [3:0]  m_axil_wstrb,
    output logic        m_axil_wvalid,
    input  wire         m_axil_wready,
    input  wire [1:0]   m_axil_bresp,
    input  wire         m_axil_bvalid,
    output logic        m_axil_bready,
    output logic [31:0] m_axil_araddr,
    output logic        m_axil_arvalid,
    input  wire         m_axil_arready,
    input  wire [31:0]  m_axil_rdata,
    input  wire [1:0]   m_axil_rresp,
    input  wire         m_axil_rvalid,
    output logic        m_axil_rready,

    // ---------------- AXI4 read-only master: fetch + LDC + EMB ---------
    output logic [ADDR_W-1:0] m_axi_araddr,
    output logic [7:0]  m_axi_arlen,
    output logic [2:0]  m_axi_arsize,
    output logic [1:0]  m_axi_arburst,
    output logic        m_axi_arvalid,
    input  wire         m_axi_arready,
    input  wire [127:0] m_axi_rdata,
    input  wire [1:0]   m_axi_rresp,
    input  wire         m_axi_rlast,
    input  wire         m_axi_rvalid,
    output logic        m_axi_rready,

    // ---------------- AXI4 burst master: the mover data path (S3) ------
    // 32-bit data / 32-bit address, READ_WRITE, ID width 1.  Owned by
    // seq_movers; reaches mvchan_0..3 and layer_0 through burst_smc.
    output logic        m_axib_awid,
    output logic [31:0] m_axib_awaddr,
    output logic  [7:0] m_axib_awlen,
    output logic  [2:0] m_axib_awsize,
    output logic  [1:0] m_axib_awburst,
    output logic        m_axib_awvalid,
    input  wire         m_axib_awready,
    output logic [31:0] m_axib_wdata,
    output logic  [3:0] m_axib_wstrb,
    output logic        m_axib_wlast,
    output logic        m_axib_wvalid,
    input  wire         m_axib_wready,
    input  wire         m_axib_bid,
    input  wire   [1:0] m_axib_bresp,
    input  wire         m_axib_bvalid,
    output logic        m_axib_bready,
    output logic        m_axib_arid,
    output logic [31:0] m_axib_araddr,
    output logic  [7:0] m_axib_arlen,
    output logic  [2:0] m_axib_arsize,
    output logic  [1:0] m_axib_arburst,
    output logic        m_axib_arvalid,
    input  wire         m_axib_arready,
    input  wire         m_axib_rid,
    input  wire  [31:0] m_axib_rdata,
    input  wire   [1:0] m_axib_rresp,
    input  wire         m_axib_rlast,
    input  wire         m_axib_rvalid,
    output logic        m_axib_rready,

    // ---------------- optional XRF sideband from layer_chan ------------
    input  wire         xrf_sb_we,
    input  wire [2:0]   xrf_sb_idx,
    input  wire [17:0]  xrf_sb_data,

    // ---------------- BM1: matvec engine busy, one bit per channel ------
    // matvec_chan c's mv_busy_bm (its STATUS busy bit, on aclk, behind
    // one source flop).  Counted only (the idle counters, SEQ 0x100..);
    // no control depends on it.  Unbuilt channels tie 0.
    input  wire [3:0]   mv_busy_bm,  output logic [3:0] xpush_valid, output logic [47:0] xpush_idx, output logic [127:0] xpush_data, input wire [3:0] xpush_room, input wire [3:0] xpush_busy,  // R3-8 x-push bus (B17.3; seq_movers' R3 block)

    output logic        seq_busy,
    output logic        seq_halted,
    output logic        seq_err
);

    // ==================================================================
    // constants
    // ==================================================================
    localparam logic [7:0] OP_CSRWR = 8'h01, OP_CMD  = 8'h02, OP_MOVX = 8'h03,
                           OP_MOVY  = 8'h04, OP_MVGO = 8'h05, OP_EMB  = 8'h06,
                           OP_AMAXL = 8'h07, OP_JMP  = 8'h08, OP_FENCE= 8'h09,
                           OP_HALT  = 8'h0A, OP_LDC  = 8'h0B, OP_XOP  = 8'h0C;

    localparam logic [3:0] IND_NONE = 4'h0, IND_ADD = 4'h1, IND_SUB = 4'h2;

    localparam logic [11:0] L_STAT = 12'h004;
    localparam logic [11:0] L_ARG0 = 12'h008, L_ARG1 = 12'h00C,
                            L_ARG2 = 12'h010;
    // L_SWIN (0x018) is deliberately absent: no seq_unit path streams the
    // scratch window through AXI-Lite any more (rung 3 moved LDC/EMB onto
    // m_axib).  The register itself is untouched for the host ladder.
    localparam logic [11:0] L_SPTR = 12'h014,
                            L_EOUT = 12'h01C, L_AMAXI= 12'h028;

    localparam logic [7:0] E_OPCODE = 8'h01, E_IND    = 8'h02, E_XRFIDX = 8'h03,
                           E_FLAGS  = 8'h04, E_CHAN   = 8'h05, E_RSVD   = 8'h06,
                           E_CSRSP  = 8'h07, E_JMP    = 8'h08, E_PC     = 8'h09,
                           E_XOPSGN = 8'h0A, E_ALIGN  = 8'h0B, E_ABORT  = 8'h0C,
                           E_ENV    = 8'h0D,
                           E_LAYEROP= 8'h10, E_CMDTMO = 8'h11, E_AXI    = 8'h12;
    // S9 (spec 5.4): the MVGO SHAPE ENVELOPE, and it is the SECOND of two
    // lines of defence, not the only one.
    //   EMIT side   sw/hwmap.shape_word refuses ng outside 1..MAX_NG per
    //               layout (G3.3), which covers every host that packs a
    //               SHAPE word or writes the CSR directly.
    //   RUN side    THIS check, which covers a stream the sequencer is
    //               handed -- the case no host packer sees.
    // It has to live here because `cfg_ng` is decoded in
    // rtl/matvec_engine.sv, whose own 1..MAX_NG guard is `ifndef SYNTHESIS
    // and whose file is closed to G3.4 (Tasks 8/9): on silicon an
    // out-of-envelope SHAPE wrapped `n_scale_beats` and streamed a wrong
    // row instead of reporting.  MVGO's imm32 IS the SHAPE word, so the
    // validator can see it; the record is refused with E_ENV before the
    // doorbell, on the existing err_op/STATUS mechanism.
    // MAX_NG is stated in FOUR places -- rtl/matvec_engine.sv (the
    // authority), here, sw/hwmap.py's SHAPE_MAX_NG[2] and
    // ref/seq_format.py -- because RTL cannot consume another module's
    // parameter without a package, and matvec_engine is closed (G3.3).
    // The four are TIED BY evidence/qwen9b/g3/isa_bits.py, which PARSES
    // all four out of their own source, requires them equal and carries a
    // perturbation control; they are not "consumed" here and this comment
    // does not claim they are.  The reference twin
    // ref/seq_format.validate carries the identical clause -- a validator
    // stricter than its golden is the encoder/decoder mismatch G3's
    // mechanization exists to prevent.
    // SEQ_ISA v2.0 / G3.3 layout: {spare[31:29], ng[28:22], nrows[21:6],
    // sh[5:0]}.
    localparam int MVGO_MAX_NG = 96;

    localparam logic [31:0] IDENT = 32'hFAB1_E5E0;
    // SR3 (SEQ_ISA v2.3 B17.0): the capabilities word at SEQ 0x64.  The RTL's
    // copy of sw/hwmap.py's seq_caps_word({"R1", "R2", "R3"}) = 0xFAB1CA07 since
    // R3-8 (R1 alone 0xFAB1CA01, R1+R2 0xFAB1CA03); the unit TB reads it back against the
    // hwmap-derived <vec>.caps.hex.
    localparam logic [31:0] SEQ_CAPS = {24'hFAB1CA, 5'd0,
                                        1'b1 /*r3*/, 1'b1 /*r2*/, 1'b1 /*r1*/};
    // SR12 (SEQ_ISA v2.3 B17.2): the two windows the R2 range rules bound —
    // the XWIN in 32-bit words (x_mem, 96 lines x 32 words, K <= 12288) and
    // the RES in rows.  Twins of ref/seq_format XWIN_WORDS / RES_ROWS, tied
    // by evidence/qwen9b/g3/isa_bits.py (section 7).
    localparam int R2_XWIN_WORDS = 3072;
    localparam int R2_RES_ROWS   = 4096;
    // R-b: the EMB row size is RUNTIME (CSR 0x60 EMBLOG2), not a localparam.
    // Reset 11 = 2048 B = the 0.8B H=1024 row, so a host that never writes
    // the CSR sees the pre-R-b behaviour bit for bit.
    // S8 (spec 5.3): the reset moved 11 -> 13 at G3.4.  The CSR STAYS
    // RUNTIME (MIN 8 / MAX 13) — keeping it costs a 5-bit register and a
    // shift, and making it constant would delete the R-b infrastructure
    // the TB set exercises.  The RESET is the 9B win: 13 is 8192 B =
    // H 4096 x 2 B, the 9B row, so a site that never learned to program
    // EMBLOG2 from the artifact is now RIGHT BY DEFAULT instead of
    // silently addressing the wrong row.  Host mirror: sw/hwmap.py
    // SEQ_EMBLOG2_RST (and EMB_ROW_BYTES_DEFAULT, derived from it).
    localparam logic [4:0] EMBLOG2_RST = 5'd13;
    localparam logic [4:0] EMBLOG2_MIN = 5'd8, EMBLOG2_MAX = 5'd13;

    wire rstn = aresetn;

    // ==================================================================
    // XRF, TCNT_SEQ, OUT FIFO, CSR registers
    // ==================================================================
    logic [17:0] xrf [8];
    logic        xrf_ovf;                  // sticky: an XOP result truncated
    logic  [4:0] emb_row_log2;             // R-b: EMBLOG2, log2(EMB row B)
    logic [31:0] tcnt_seq;
    logic [33:0] seq_base;
    logic [31:0] seq_len, seq_entry, pc;
    logic        busy_r, halted_r, err_r;
    logic  [7:0] err_code;

    // ---- OUT FIFO (rung 4 S6, docs/RUNG4_SPEC.md) --------------------
    // DEPTH 64 (was 16: a >16-token launch used to drop tokens silently),
    // and of_cnt is DERIVED from of_wp - of_rp instead of being a third
    // register.  That removes the race class outright: the push (I_AMAXW)
    // and the pop (csr_of_pop) live in the same always_ff and used to
    // BOTH assign of_cnt, so a host pop landing on an AMAXL push lost the
    // push's increment (the hazard sw/chat_seq.py:93 works around).  With
    // two independent pointers there is nothing to lose; wp/rp carry the
    // extra MSB that makes full and empty distinguishable, exactly as the
    // neighbouring fetch/mover FIFOs do.
    // of_ovf is sticky until RESET, exactly like xrf_ovf next to it (a
    // START does not clear it, and the OUT FIFO's contents likewise
    // survive a START — the host drains, see sw/chat_seq.py:_launch).
    localparam int OF_DEPTH = 64;
    logic [17:0] out_fifo [OF_DEPTH];
    logic  [6:0] of_wp, of_rp;
    logic        of_ovf;                   // sticky: a push found it full
    wire   [6:0] of_cnt = of_wp - of_rp;   // 0..64

    logic [31:0] perf_cyc, perf_rec, perf_axw, perf_axr, perf_fst;

    // AXI-Lite SLAVE decode handoff.  Declared HERE, ahead of the issue FSM
    // that consumes them, because the LRM requires declaration before use —
    // the slave block that DRIVES them is at the bottom of the file.
    logic  [9:0] csr_waddr;
    logic [31:0] csr_wdata;
    logic        csr_we, csr_of_pop;

    // XRF read with the A11 rule: [3] is an unsigned token id, the rest
    // are signed 18-bit exponents.
    function automatic logic signed [31:0] xrf_rd(input logic [2:0] i,
                                                  input logic [17:0] v);
        xrf_rd = (i == 3'd3) ? signed'({14'd0, v})
                             : signed'({{14{v[17]}}, v});
    endfunction

    // ==================================================================
    // AXI-Lite MASTER — two independent, pipelined channels.
    //   write: axw_valid/axw_ready + axw_addr/axw_data, drained via wr_idle
    //   read : axr_valid/axr_ready + axr_addr, in-order data on rrsp_*
    // ==================================================================
    logic        axw_valid, axw_ready;
    logic [31:0] axw_addr, axw_data;
    logic        axr_valid, axr_ready;
    logic [31:0] axr_addr;
    wire         rrsp_valid = m_axil_rvalid;
    wire  [31:0] rrsp_data  = m_axil_rdata;

    logic        wq_valid, aw_sent, w_sent;
    logic [31:0] wq_addr, wq_data;
    logic  [4:0] w_out, r_out;
    logic        rq_valid;
    logic [31:0] rq_addr;
    logic        ax_err;

    assign m_axil_awvalid = wq_valid && !aw_sent;
    assign m_axil_wvalid  = wq_valid && !w_sent;
    assign m_axil_awaddr  = wq_addr;
    assign m_axil_wdata   = wq_data;
    assign m_axil_wstrb   = 4'hF;
    assign m_axil_bready  = 1'b1;
    assign m_axil_arvalid = rq_valid;
    assign m_axil_araddr  = rq_addr;
    assign m_axil_rready  = 1'b1;

    wire aw_ok = aw_sent || (m_axil_awvalid && m_axil_awready);
    wire w_ok  = w_sent  || (m_axil_wvalid  && m_axil_wready);
    wire wbeat_done = wq_valid && aw_ok && w_ok;

    assign axw_ready = (!wq_valid || wbeat_done) && (w_out < 5'(AXIL_OUT));
    assign axr_ready = (!rq_valid || m_axil_arready) && (r_out < 5'(AXIL_OUT));

    wire wr_idle = (w_out == 5'd0) && !wq_valid;
    wire rd_idle = (r_out == 5'd0) && !rq_valid;

    always_ff @(posedge aclk) begin
        if (!rstn) begin
            wq_valid <= 1'b0; aw_sent <= 1'b0; w_sent <= 1'b0;
            rq_valid <= 1'b0; w_out <= '0; r_out <= '0; ax_err <= 1'b0;
            wq_addr <= '0; wq_data <= '0; rq_addr <= '0;
        end else begin
            // ---- write channel ----
            if (wq_valid) begin
                if (m_axil_awvalid && m_axil_awready) aw_sent <= 1'b1;
                if (m_axil_wvalid  && m_axil_wready)  w_sent  <= 1'b1;
            end
            if (wbeat_done) begin
                wq_valid <= 1'b0; aw_sent <= 1'b0; w_sent <= 1'b0;
            end
            if (axw_valid && axw_ready) begin
                wq_valid <= 1'b1; wq_addr <= axw_addr; wq_data <= axw_data;
                aw_sent  <= 1'b0; w_sent <= 1'b0;
            end
            case ({wbeat_done, m_axil_bvalid})
                2'b10:   w_out <= w_out + 5'd1;
                2'b01:   w_out <= w_out - 5'd1;
                default: ;
            endcase
            if (m_axil_bvalid && (m_axil_bresp != 2'b00)) ax_err <= 1'b1;

            // ---- read channel ----
            if (rq_valid && m_axil_arready) rq_valid <= 1'b0;
            if (axr_valid && axr_ready) begin
                rq_valid <= 1'b1; rq_addr <= axr_addr;
            end
            case ({(rq_valid && m_axil_arready), m_axil_rvalid})
                2'b10:   r_out <= r_out + 5'd1;
                2'b01:   r_out <= r_out - 5'd1;
                default: ;
            endcase
            if (m_axil_rvalid && (m_axil_rresp != 2'b00)) ax_err <= 1'b1;
            // a DDR read error (fetch / LDC / EMB) is fatal too
            if (m_axi_rvalid && m_axi_rready && (m_axi_rresp != 2'b00))
                ax_err <= 1'b1;
        end
    end

    // ==================================================================
    // AXI4 read master: record fetch + LDC/EMB bulk, arbitrated
    // ==================================================================
    // ---- record prefetch FIFO ----
    logic [127:0] fq_mem [FETCH_DEPTH];
    logic [15:0]  fq_wp, fq_rp, fq_cnt;
    logic         fq_push, fq_pop;
    wire  [127:0] fq_dout = fq_mem[fq_rp[$clog2(FETCH_DEPTH)-1:0]];

    // fetch-address generation, pipelined.  fa_addr / fa_left are the former
    // combinational fetch_addr / f_left, now maintained INCREMENTALLY (on
    // burst issue / flush) so the 34-bit address add and 32-bit records-left
    // subtract leave the per-cycle AR path.  fa_beats is the burst_beats
    // result REGISTERED one cycle (the added stage); it is consumed only
    // while fa_valid, so it always matches the fa_addr it is issued with.
    // The prefetch FIFO (FETCH_DEPTH) absorbs the 1-cycle issue bubble.
    logic [ADDR_W-1:0] fa_addr;           // next fetch burst DDR address
    logic [31:0]  fa_left;                // records not yet requested
    logic  [8:0]  fa_beats;               // registered burst length
    logic         fa_valid;               // fa_beats matches fa_addr/fa_left
    logic [15:0]  f_pend;                 // beats requested, not yet returned
    logic [15:0]  f_drop;                 // beats to discard after a flush
    logic  [3:0]  f_bursts;               // outstanding fetch bursts
    logic         flush;
    logic [31:0]  flush_pc;

    // ---- LDC / EMB bulk reader ----
    logic         bulk_go, bulk_active, bulk_rd_done;
    logic [ADDR_W-1:0] bulk_addr;
    logic [23:0]  bulk_words;
    logic [2:0]   bulk_woff;
    logic [23:0]  b_words_left;
    logic [ADDR_W-1:0] b_addr;
    logic [23:0]  b_beats_left;
    logic  [3:0]  b_bursts;
    logic [127:0] b_beat;
    logic         b_have;
    logic  [3:0]  b_widx;
    logic         b_first;

    logic [15:0]  bq_mem [BULK_DEPTH];
    logic [15:0]  bq_wp, bq_rp, bq_cnt;
    logic         bq_push, bq_pop;
    logic [15:0]  bq_din;
    wire  [15:0]  bq_dout = bq_mem[bq_rp[$clog2(BULK_DEPTH)-1:0]];

    typedef enum logic [1:0] {RD_FETCH, RD_SWITCH, RD_BULK} rdown_e;
    rdown_e rd_own;

    // beats a fetch burst may take without crossing a 4 KB boundary
    function automatic logic [8:0] burst_beats(input logic [11:0] a12,
                                               input logic [31:0] left,
                                               input int cap);
        logic [8:0] to_bound, want;
        begin
            to_bound = 9'((13'h1000 - {1'b0, a12}) >> 4);
            want     = (left > 32'(cap)) ? 9'(cap) : 9'(left);
            burst_beats = (want > to_bound) ? to_bound : want;
        end
    endfunction

    // combinational next-burst length; registered into fa_beats each cycle
    wire  [8:0] fa_beats_c = burst_beats(fa_addr[11:0], fa_left, FETCH_BURST);
    wire [15:0] f_space = 16'(FETCH_DEPTH) - fq_cnt;
    wire  [8:0] b_beats = burst_beats(b_addr[11:0], {8'd0, b_beats_left},
                                      BULK_BURST);

    wire f_can_ar = (rd_own == RD_FETCH) && !flush && (f_drop == 16'd0)
                    && fa_valid && (fa_beats != 9'd0)
                    && (f_bursts < 4'(FETCH_OUT))
                    && ({7'd0, fa_beats} <= (f_space - f_pend));
    wire b_can_ar = (rd_own == RD_BULK) && (b_beats != 9'd0)
                    && (b_bursts < 4'd2);

    // a fetch burst is accepted this cycle (f_can_ar already implies !flush)
    wire fetch_issue = m_axi_arvalid && m_axi_arready && f_can_ar && !flush;

    assign m_axi_arsize  = 3'b100;                 // 16 B
    assign m_axi_arburst = 2'b01;                  // INCR
    assign m_axi_arvalid = f_can_ar || b_can_ar;
    assign m_axi_araddr  = f_can_ar ? {fa_addr[ADDR_W-1:4], 4'd0}
                                    : {b_addr[ADDR_W-1:4], 4'd0};
    assign m_axi_arlen   = f_can_ar ? 8'(fa_beats - 9'd1) : 8'(b_beats - 9'd1);
    // fetch pushes straight into the record FIFO; bulk holds one beat while
    // it is unpacked into 16-bit words, so it backpressures R.
    assign m_axi_rready  = (rd_own == RD_BULK) ? !b_have : 1'b1;

    assign fq_push = (rd_own != RD_BULK) && m_axi_rvalid && m_axi_rready
                     && (f_drop == 16'd0);

    always_ff @(posedge aclk) begin
        if (!rstn) begin
            fq_wp <= '0; fq_rp <= '0; fq_cnt <= '0;
            fa_addr <= '0; fa_left <= '0; fa_beats <= '0; fa_valid <= 1'b0;
            f_pend <= '0; f_drop <= '0; f_bursts <= '0;
            rd_own <= RD_FETCH;
            bulk_active <= 1'b0; bulk_rd_done <= 1'b0;
            b_addr <= '0; b_beats_left <= '0; b_words_left <= '0;
            b_bursts <= '0; b_beat <= '0; b_have <= 1'b0; b_widx <= '0;
            b_first <= 1'b0;
            bq_wp <= '0; bq_rp <= '0; bq_cnt <= '0;
        end else begin
            // ---------------- fetch ----------------
            if (flush) begin
                fq_wp <= '0; fq_rp <= '0; fq_cnt <= '0;
                // a beat landing in the same cycle is consumed but not
                // pushed, so it must not also be counted as one to drop
                f_drop <= f_pend
                          - (((rd_own != RD_BULK) && m_axi_rvalid
                              && m_axi_rready) ? 16'd1 : 16'd0);
            end else begin
                if (fq_push) begin
                    fq_mem[fq_wp[$clog2(FETCH_DEPTH)-1:0]] <= m_axi_rdata;
                    fq_wp <= fq_wp + 16'd1;
                end
                if (fq_pop) fq_rp <= fq_rp + 16'd1;
                case ({fq_push, fq_pop})
                    2'b10:   fq_cnt <= fq_cnt + 16'd1;
                    2'b01:   fq_cnt <= fq_cnt - 16'd1;
                    default: ;
                endcase
                if ((rd_own != RD_BULK) && m_axi_rvalid && m_axi_rready
                    && (f_drop != 16'd0))
                    f_drop <= f_drop - 16'd1;
            end

            // fetch-address generation stage: register the burst length and
            // advance the (incremental) address / records-left on issue.
            // fa_valid drops for one cycle after any fa_addr/fa_left move so
            // the now-stale fa_beats is never issued (the added pipeline
            // stage; the prefetch FIFO covers its 1-cycle bubble).
            fa_beats <= fa_beats_c;
            if (flush) begin
                fa_addr  <= ADDR_W'(seq_base) + (ADDR_W'(flush_pc) << 4);
                fa_left  <= (seq_len > flush_pc) ? (seq_len - flush_pc) : 32'd0;
                fa_valid <= 1'b0;
            end else if (fetch_issue) begin
                fa_addr  <= fa_addr + (ADDR_W'(fa_beats) << 4);
                fa_left  <= fa_left - 32'({23'd0, fa_beats});
                fa_valid <= 1'b0;
            end else
                fa_valid <= 1'b1;

            if (fetch_issue) begin
                f_pend   <= f_pend + 16'({7'd0, fa_beats});
                f_bursts <= f_bursts + 4'd1;
            end
            if ((rd_own != RD_BULK) && m_axi_rvalid && m_axi_rready) begin
                f_pend <= f_pend - 16'd1
                          + (fetch_issue ? 16'({7'd0, fa_beats}) : 16'd0);
                if (m_axi_rlast) f_bursts <= f_bursts - 4'd1
                                             + (fetch_issue ? 4'd1 : 4'd0);
            end

            // ---------------- read-master arbitration ----------------
            case (rd_own)
                RD_FETCH: if (bulk_go) rd_own <= RD_SWITCH;
                RD_SWITCH: if ((f_pend == 16'd0) && (f_bursts == 4'd0)) begin
                    rd_own <= RD_BULK;
                end
                default: if (bulk_rd_done && (b_bursts == 4'd0))
                    rd_own <= RD_FETCH;
            endcase

            // ---------------- bulk read ----------------
            if (bulk_go) begin
                bulk_active  <= 1'b1;
                bulk_rd_done <= 1'b0;
                b_addr       <= {bulk_addr[ADDR_W-1:4], 4'd0};
                b_words_left <= bulk_words;
                b_beats_left <= 24'((32'({8'd0, bulk_words})
                                     + 32'({29'd0, bulk_woff})
                                     + 32'd7) >> 3);
                b_widx       <= {1'b0, bulk_woff};
                b_first      <= 1'b1;
                b_have       <= 1'b0;
                b_bursts     <= '0;
                bq_wp <= '0; bq_rp <= '0; bq_cnt <= '0;
            end else if (bulk_active) begin
                if (m_axi_arvalid && m_axi_arready && b_can_ar) begin
                    b_addr       <= b_addr + (ADDR_W'({7'd0, b_beats}) << 4);
                    b_beats_left <= b_beats_left - 24'({15'd0, b_beats});
                    b_bursts     <= b_bursts + 4'd1;
                end
                if ((rd_own == RD_BULK) && m_axi_rvalid && m_axi_rready) begin
                    b_beat  <= m_axi_rdata;
                    b_have  <= 1'b1;
                    b_widx  <= b_first ? {1'b0, bulk_woff} : 4'd0;
                    b_first <= 1'b0;
                    if (m_axi_rlast) b_bursts <= b_bursts - 4'd1;
                end
                if (bq_push) begin
                    b_widx       <= b_widx + 4'd1;
                    b_words_left <= b_words_left - 24'd1;
                    if ((b_widx == 4'd7) || (b_words_left == 24'd1))
                        b_have <= 1'b0;
                    if (b_words_left == 24'd1) bulk_rd_done <= 1'b1;
                end
                if (bulk_rd_done && (b_bursts == 4'd0)) bulk_active <= 1'b0;
            end

            // ---------------- bulk word FIFO ----------------
            if (bq_push) begin
                bq_mem[bq_wp[$clog2(BULK_DEPTH)-1:0]] <= bq_din;
                bq_wp <= bq_wp + 16'd1;
            end
            if (bq_pop) bq_rp <= bq_rp + 16'd1;
            if (!bulk_go) begin
                case ({bq_push, bq_pop})
                    2'b10:   bq_cnt <= bq_cnt + 16'd1;
                    2'b01:   bq_cnt <= bq_cnt - 16'd1;
                    default: ;
                endcase
            end
        end
    end

    assign bq_push = bulk_active && b_have && (b_words_left != 24'd0)
                     && (bq_cnt < 16'(BULK_DEPTH));
    assign bq_din  = b_beat[16 * b_widx[2:0] +: 16];

    // ==================================================================
    // record decode
    // ==================================================================
    logic [127:0] rec;
    logic         rec_valid;
    wire  [7:0]  r_op    = rec[7:0];
    wire  [7:0]  r_flags = rec[15:8];
    wire [15:0]  r_tgt   = rec[31:16];
    wire [31:0]  r_imm   = rec[63:32];
    wire [31:0]  r_lo    = rec[95:64];
    wire [31:0]  r_hi    = rec[127:96];

    wire [3:0]  r_ind  = r_flags[3:0];
    wire [3:0]  r_xrf4 = r_flags[7:4];                    // general rule
    wire [2:0]  r_xrfy = r_flags[7:5];                    // MOVY (A1)
    wire [3:0]  r_chan = r_flags[7:4];                    // MOVX/MVGO (A1)
    wire [2:0]  xsel   = (r_op == OP_MOVY) ? r_xrfy : r_xrf4[2:0];

    wire signed [31:0] xv = xrf_rd(xsel, xrf[xsel]);
    logic signed [31:0] imm_res;
    always_comb begin
        case (r_ind)
            IND_ADD: imm_res = signed'(r_imm) + xv;
            IND_SUB: imm_res = signed'(r_imm) - xv;
            default: imm_res = signed'(r_imm);
        endcase
    end

    // XOP (ISA v1.2 0x0C): XRF[target[2:0]] =
    //   s1*XRF[imm[2:0]] + s2*XRF[imm[6:4]] + simm18(imm[31:14])
    // sign codes: 00 = 0, 01 = +1, 10 = -1, 11 = illegal (ruling D-1).
    wire [2:0] xop_a = r_imm[2:0];
    wire [2:0] xop_b = r_imm[6:4];
    wire [1:0] xop_s1 = r_imm[9:8];
    wire [1:0] xop_s2 = r_imm[11:10];
    wire signed [17:0] xop_simm = signed'(r_imm[31:14]);
    wire signed [31:0] xop_va = xrf_rd(xop_a, xrf[xop_a]);
    wire signed [31:0] xop_vb = xrf_rd(xop_b, xrf[xop_b]);
    logic signed [31:0] xop_ta, xop_tb;
    always_comb begin
        case (xop_s1)
            2'b01:   xop_ta =  xop_va;
            2'b10:   xop_ta = -xop_va;
            default: xop_ta = 32'sd0;
        endcase
        case (xop_s2)
            2'b01:   xop_tb =  xop_vb;
            2'b10:   xop_tb = -xop_vb;
            default: xop_tb = 32'sd0;
        endcase
    end
    wire signed [31:0] xop_res = xop_ta + xop_tb + 32'(xop_simm);

    // ---- validation (ref/seq_format.validate, executed in one cycle) ----
    logic        v_bad;
    logic  [7:0] v_code;
    // SR12 (SEQ_ISA v2.3 B17.2) range rules, err 0x06.  Written as ROOM
    // compares so no adder sits on the 24-bit length:
    //   MOVX  start + ceil(len/4) <= 3072  <=>  len <= 4 * (3072 - start)
    //         (for start <= 3071, checked separately); 14-bit room
    //   MOVY  start row + len <= 4096      <=>  len <= 4096 - start row
    wire [13:0] v_xroom = 14'(4 * R2_XWIN_WORDS) - {r_tgt[11:0], 2'b00};
    wire [12:0] v_yroom = 13'(R2_RES_ROWS) - {1'b0, r_tgt[15:4]};
    wire        v_movx_rsvd = (r_tgt[15:12] != 4'd0)
                              || (r_tgt[11:0] >= 12'(R2_XWIN_WORDS))
                              || (r_hi[23:0] > {10'd0, v_xroom});
    wire        v_movy_rsvd = (r_hi[23:0] > {11'd0, v_yroom});
    always_comb begin
        v_bad  = 1'b0;
        v_code = 8'd0;
        case (r_op)
            OP_CSRWR, OP_LDC: begin
                if ((r_ind != IND_NONE) && (r_ind != IND_ADD)
                    && (r_ind != IND_SUB))       begin v_bad=1; v_code=E_IND; end
                else if ((r_ind == IND_NONE) && (r_xrf4 != 4'd0))
                                                 begin v_bad=1; v_code=E_IND; end
                else if (r_xrf4 >= 4'd8)         begin v_bad=1; v_code=E_XRFIDX; end
                else if ((r_op == OP_CSRWR)
                         && (r_tgt[15:12] > 4'h2)) begin v_bad=1; v_code=E_CSRSP; end
                else if ((r_op == OP_CSRWR) && (r_tgt[15:12] == 4'h1)
                         && (r_tgt[11:8] >= 4'd4)) begin v_bad=1; v_code=E_CHAN; end
            end
            OP_CMD: begin
                if (r_flags != 8'd0)             begin v_bad=1; v_code=E_FLAGS; end
                else if (r_tgt[15:12] != 4'd0)   begin v_bad=1; v_code=E_CSRSP; end
            end
            OP_MOVX, OP_MVGO: begin
                if (r_ind != IND_NONE)           begin v_bad=1; v_code=E_IND; end
                else if ((r_chan >= 4'd4) && !((r_op == OP_MOVX) && (r_chan == 4'hF))) begin v_bad=1; v_code=E_CHAN; end   // R3-8: MOVX 0xF = broadcast (B17.3)
                // S9: ng outside 1..96 is refused HERE, before the doorbell
                else if ((r_op == OP_MVGO)
                         && ((r_imm[28:22] == 7'd0)
                             || (r_imm[28:22] > 7'(MVGO_MAX_NG))))
                                                 begin v_bad=1; v_code=E_ENV; end
                // SR12 (B17.2): MOVX target[11:0] = the XWIN start word,
                // target[15:12] reserved, the window must fit the XWIN.
                // (MVGO SHAPE bits 29/30 need no decode here — the mover
                // writes SHAPE whole; bank LEGALITY is validator-side only.)
                else if ((r_op == OP_MOVX) && v_movx_rsvd)
                                                 begin v_bad=1; v_code=E_RSVD; end
            end
            OP_MOVY: begin
                if ((r_ind != IND_NONE) && (r_ind != IND_ADD)
                    && (r_ind != IND_SUB))       begin v_bad=1; v_code=E_IND; end
                else if ((r_ind == IND_NONE) && (r_xrfy != 3'd0))
                                                 begin v_bad=1; v_code=E_IND; end
                else if (r_tgt[3:0] >= 4'd4)     begin v_bad=1; v_code=E_CHAN; end
                // SR12 (B17.2): target[15:4] is the RES start row (it was
                // reserved, err 0x06); start row + len <= 4096 (err 0x06)
                else if (v_movy_rsvd)            begin v_bad=1; v_code=E_RSVD; end
            end
            OP_EMB: if (r_flags != 8'd0)         begin v_bad=1; v_code=E_FLAGS; end
            OP_AMAXL: if ((r_flags != 8'd0) || (r_tgt != 16'd0)
                          || (r_imm != 32'd0) || (r_lo != 32'd0)
                          || (r_hi != 32'd0))    begin v_bad=1; v_code=E_RSVD; end
            OP_JMP: begin
                if ((r_flags != 8'd0) && (r_flags != 8'd1))
                                                 begin v_bad=1; v_code=E_FLAGS; end
                else if (r_imm >= seq_len)       begin v_bad=1; v_code=E_JMP; end
            end
            // SR3 (SEQ_ISA v2.3 B17.1): FENCE target[3:0] is the channel
            // mask (0 = all four); every other field must be zero.
            OP_FENCE:
                if ((r_flags != 8'd0) || (r_tgt[15:4] != 12'd0)
                    || (r_imm != 32'd0) || (r_lo != 32'd0) || (r_hi != 32'd0))
                                                 begin v_bad=1; v_code=E_RSVD; end
            OP_HALT:
                if ((r_flags != 8'd0) || (r_tgt != 16'd0) || (r_imm != 32'd0)
                    || (r_lo != 32'd0) || (r_hi != 32'd0))
                                                 begin v_bad=1; v_code=E_RSVD; end
            OP_XOP: begin
                if (r_flags != 8'd0)             begin v_bad=1; v_code=E_FLAGS; end
                else if (r_tgt >= 16'd8)         begin v_bad=1; v_code=E_XRFIDX; end
                else if ((xop_s1 == 2'b11) || (xop_s2 == 2'b11))
                                                 begin v_bad=1; v_code=E_XOPSGN; end
            end
            default: begin v_bad = 1'b1; v_code = E_OPCODE; end
        endcase
    end

    // ==================================================================
    // issue FSM
    // ==================================================================
    typedef enum logic [4:0] {
        I_IDLE, I_SYNC, I_SYNCW, I_FETCH, I_EXEC,
        I_WR, I_CMDW, I_CMDDRAIN, I_CMDPOLL, I_CMDPOLLW,
        I_XRFSEL, I_XRFSELD, I_XRFRD, I_XRFRDW, I_XRFSB,
        I_WTI, I_WTD,
        I_MOVER, I_AMAX, I_AMAXW,
        I_BULKSPTR, I_BULKRUN, I_BULKEND,
        I_FENCE, I_HALT, I_ERR
    } istate_e;
    istate_e ist;

    logic [31:0] arg0_sh, arg1_sh, arg2_sh;    // ARG shadow (XRF-writer sniff)
    logic [15:0] cmd_cnt_exp;
    logic [31:0] wr_addr_r, wr_data_r;
    logic [TIMEOUT_LOG2-1:0] cmd_tmo;
    logic        abort_req, start_req;
    logic [2:0]  xrf_dst;
    logic [2:0]  wt_idx;
    logic [17:0] wt_val;
    logic [23:0] bulk_left;
    logic [15:0] bulk_dst;
    logic        do_xrfrd;

    // LDC/EMB scratch-write side, moved onto seq_movers' burst master
    // (RUNG3 S8).  The DDR read side (m_axi, 128-bit) is untouched.
    logic        bulk_bgo;
    logic [31:0] bulk_baddr;
    logic [23:0] bulk_bbeats;
    wire         bulk_wvalid = (ist == I_BULKRUN) && (bq_cnt != 16'd0);
    wire         bulk_wready, bulk_bidle, axib_err;

    // mover command wires
    logic        mv_cmd_valid;
    wire         mv_cmd_ready, mv_done, mv_err, mv_busy;
    wire  [7:0]  mv_err_code;
    logic [1:0]  mv_op, mv_chan;
    logic [3:0]  mv_fmask;           // SR3: FENCE channel mask (B17.1)
    logic [11:0] mv_xword;  logic mv_bcast;   // SR12: MOVX XWIN start word (B17.2); R3-8: MOVX broadcast (B17.3)
    logic [11:0] mv_row;             // SR12: MOVY RES start row (B17.2)
    logic [15:0] mv_saddr;
    logic [23:0] mv_len;
    logic        mv_i16, mv_nowait;
    logic signed [31:0] mv_shift;
    logic [31:0] mv_shape;
    logic [39:0] mv_wbase;
    logic [23:0] mv_beats;

    wire mv_wr_valid, mv_rd_valid;
    wire [31:0] mv_wr_addr, mv_wr_data, mv_rd_addr;

    // bus ownership: exactly one requester is ever active
    wire mv_owns = mv_busy;
    logic fsm_wr_valid, fsm_rd_valid;
    logic [31:0] fsm_wr_addr, fsm_wr_data, fsm_rd_addr;

    assign axw_valid = mv_owns ? mv_wr_valid : fsm_wr_valid;
    assign axw_addr  = mv_owns ? mv_wr_addr  : fsm_wr_addr;
    assign axw_data  = mv_owns ? mv_wr_data  : fsm_wr_data;
    assign axr_valid = mv_owns ? mv_rd_valid : fsm_rd_valid;
    assign axr_addr  = mv_owns ? mv_rd_addr  : fsm_rd_addr;

    wire fsm_wr_fire = fsm_wr_valid && axw_ready && !mv_owns;
    wire fsm_rd_fire = fsm_rd_valid && axr_ready && !mv_owns;

    // layer CMD sniffing: which XRF entry does this command retire into?
    wire       cmd_is_alu   = (wr_data_r[7:0] == 8'd11);
    wire [3:0] alu_sub      = arg0_sh[3:0];
    wire       cmd_wr_dynq8 = cmd_is_alu && (alu_sub == 4'd0);
    wire       cmd_wr_dq16  = cmd_is_alu && (alu_sub == 4'd12);
    // ISA v1.3: ALU op 8 with cfg_p0[6] is the attn k_a probe -> XRF[2]
    wire       cmd_wr_probe = cmd_is_alu && (alu_sub == 4'd8) && arg2_sh[6];

    // --------------------------- CSRWR target -> AXI-Lite address ------
    function automatic logic [31:0] csr_addr(input logic [15:0] t);
        case (t[15:12])
            4'h1: csr_addr = MV_BASE + (MV_STRIDE * {28'd0, t[11:8]})
                             + {24'd0, t[7:0]};
            default: csr_addr = LAYER_BASE + {24'd0, t[7:0]};
        endcase
    endfunction

    wire is_seq_space = (r_tgt[15:12] == 4'h2);
    wire is_seq_xrf   = is_seq_space && (r_tgt[7:0] >= 8'h40)
                        && (r_tgt[7:0] < 8'h60);
    wire is_seq_tcnt  = is_seq_space && (r_tgt[7:0] == 8'h20);

    // EMB / LDC address.  R-b: the row stride is 2**EMBLOG2 (a power of two
    // by construction — 2048 B at H=1024, 4096 B at H=2048), so the old
    // `* EMB_ROW_BYTES` multiply is a shift by the CSR.
    wire [ADDR_W-1:0] emb_a = ADDR_W'({r_tgt, r_imm})
                              + (ADDR_W'(xrf[3]) << emb_row_log2);
    wire signed [63:0] ldc_base = signed'({r_hi, r_lo});
    wire signed [63:0] ldc_a = (r_ind == IND_ADD) ? (ldc_base + 64'(xv))
                             : (r_ind == IND_SUB) ? (ldc_base - 64'(xv))
                                                  : ldc_base;

    // NB `!flush`: on the cycle a JMP/START flush is applied the FIFO still
    // holds the records fetched down the NOT-taken path — popping one there
    // would execute a stale record (found by tb_seq_unit's pc check).
    assign fq_pop = (ist == I_FETCH) && !flush && (fq_cnt != 16'd0) && busy_r
                    && !abort_req && (pc < seq_len);

    always_ff @(posedge aclk) begin
        if (!rstn) begin
            ist <= I_IDLE;
            for (int i = 0; i < 8; i++) xrf[i] <= 18'd0;
            xrf_ovf <= 1'b0; tcnt_seq <= '0;
            emb_row_log2 <= EMBLOG2_RST;   // 8192 B row until told else
            seq_base <= '0; seq_len <= '0; seq_entry <= '0; pc <= '0;
            busy_r <= 1'b0; halted_r <= 1'b0; err_r <= 1'b0; err_code <= '0;
            of_wp <= '0; of_rp <= '0; of_ovf <= 1'b0;
            perf_cyc <= '0; perf_rec <= '0; perf_axw <= '0; perf_axr <= '0;
            perf_fst <= '0;
            arg0_sh <= '0; arg1_sh <= '0; arg2_sh <= '0; cmd_cnt_exp <= '0;
            wr_addr_r <= '0; wr_data_r <= '0;
            cmd_tmo <= '0; abort_req <= 1'b0; start_req <= 1'b0;
            xrf_dst <= '0; bulk_left <= '0; bulk_dst <= '0; do_xrfrd <= 1'b0;
            wt_idx <= '0; wt_val <= '0;
            rec <= '0; rec_valid <= 1'b0; flush <= 1'b0; flush_pc <= '0;
            bulk_go <= 1'b0; bulk_addr <= '0; bulk_words <= '0; bulk_woff <= '0;
            mv_cmd_valid <= 1'b0;
            mv_op <= '0; mv_chan <= '0; mv_saddr <= '0; mv_len <= '0;
            mv_fmask <= '0; mv_xword <= '0; mv_row <= '0; mv_bcast <= 1'b0;
            mv_i16 <= 1'b0; mv_nowait <= 1'b0; mv_shift <= '0;
            mv_shape <= '0; mv_wbase <= '0; mv_beats <= '0;
        end else begin
            flush    <= 1'b0;
            bulk_go  <= 1'b0;
            bulk_bgo <= 1'b0;
            if (mv_cmd_valid && mv_cmd_ready) mv_cmd_valid <= 1'b0;

            // ---- perf ----
            if (busy_r) perf_cyc <= perf_cyc + 32'd1;
            if (fsm_wr_fire || (mv_owns && axw_valid && axw_ready))
                perf_axw <= perf_axw + 32'd1;
            if (fsm_rd_fire || (mv_owns && axr_valid && axr_ready))
                perf_axr <= perf_axr + 32'd1;
            if ((ist == I_FETCH) && (fq_cnt == 16'd0) && busy_r)
                perf_fst <= perf_fst + 32'd1;

            // ---- optional XRF sideband ----
            if (USE_XRF_SIDEBAND && xrf_sb_we) xrf[xrf_sb_idx] <= xrf_sb_data;

            // ---- AXI-Lite / burst-master error is fatal wherever it happens
            // (axib_err is sticky until the next burst descriptor starts, so
            // it is still standing on the cycles this check can win) ----
            if ((ax_err || axib_err) && busy_r && (ist != I_ERR)) begin
                err_code <= E_AXI;
                ist <= I_ERR;
            end

            case (ist)
            // --------------------------------------------------------
            I_IDLE: if (start_req) begin
                start_req <= 1'b0;
                busy_r <= 1'b1; halted_r <= 1'b0; err_r <= 1'b0;
                err_code <= 8'd0; abort_req <= 1'b0;
                pc <= seq_entry;
                perf_cyc <= '0; perf_rec <= '0; perf_axw <= '0;
                perf_axr <= '0; perf_fst <= '0;
                flush <= 1'b1; flush_pc <= seq_entry;
                ist <= I_SYNC;
            end

            // resync the cmd_cnt shadow with layer_chan before issuing
            I_SYNC: if (fsm_rd_fire) ist <= I_SYNCW;
            I_SYNCW: if (rrsp_valid) begin
                cmd_cnt_exp <= rrsp_data[31:16];
                ist <= I_FETCH;
            end

            // --------------------------------------------------------
            I_FETCH: begin
                if (abort_req) begin
                    err_code <= E_ABORT;
                    ist <= I_ERR;
                end else if (pc >= seq_len) begin
                    err_code <= E_PC;
                    ist <= I_ERR;
                end else if (!flush && (fq_cnt != 16'd0)) begin
                    rec <= fq_dout;
                    rec_valid <= 1'b1;
                    ist <= I_EXEC;
                end
            end

            // --------------------------------------------------------
            I_EXEC: begin
                rec_valid <= 1'b0;
                if (v_bad) begin
                    err_code <= v_code;
                    ist <= I_ERR;
                end else begin
                    perf_rec <= perf_rec + 32'd1;
                    case (r_op)
                    OP_CSRWR: begin
                        if (is_seq_space) begin
                            if (is_seq_xrf) begin
                                xrf[r_tgt[4:2]] <= imm_res[17:0];
                                wt_idx <= r_tgt[4:2];
                                wt_val <= imm_res[17:0];
                                ist <= XRF_WRITE_THROUGH ? I_WTI : I_FETCH;
                                if (!XRF_WRITE_THROUGH) pc <= pc + 32'd1;
                            end else if (is_seq_tcnt) begin
                                tcnt_seq <= imm_res;
                                pc  <= pc + 32'd1;
                                ist <= I_FETCH;
                            end else begin
                                err_code <= E_CSRSP;
                                ist <= I_ERR;
                            end
                        end else begin
                            if (r_tgt[15:12] == 4'h0) begin
                                if (r_tgt[7:0] == L_ARG0[7:0]) arg0_sh <= imm_res;
                                if (r_tgt[7:0] == L_ARG1[7:0]) arg1_sh <= imm_res;
                                if (r_tgt[7:0] == L_ARG2[7:0]) arg2_sh <= imm_res;
                            end
                            wr_addr_r <= csr_addr(r_tgt);
                            wr_data_r <= imm_res;
                            ist <= I_WR;
                        end
                    end
                    OP_CMD: begin
                        wr_addr_r <= LAYER_BASE + {24'd0, r_tgt[7:0]};
                        wr_data_r <= imm_res;
                        ist <= I_CMDW;
                    end
                    OP_MOVX: begin
                        // 16-bit scratch addressing (SEQ_ISA v2.0): addr_lo
                        // is a full 32-bit field, so widening the pointer
                        // costs nothing in the record — only in the width
                        // of what latches it.
                        mv_op <= 2'd0; mv_chan <= r_chan[1:0]; mv_bcast <= (r_chan == 4'hF);   // R3-8: B17.3
                        mv_saddr <= r_lo[15:0]; mv_len <= r_hi[23:0];
                        mv_xword <= r_tgt[11:0];  // SR12: B17.2 start word
                        mv_cmd_valid <= 1'b1;
                        ist <= I_MOVER;
                    end
                    OP_MVGO: begin
                        mv_op <= 2'd1; mv_chan <= r_chan[1:0];
                        mv_shape <= r_imm;
                        mv_wbase <= {r_hi[7:0], r_lo};
                        mv_beats <= r_hi[31:8];
                        mv_nowait <= r_tgt[0];
                        mv_cmd_valid <= 1'b1;
                        ist <= I_MOVER;
                    end
                    OP_MOVY: begin
                        mv_op <= 2'd2; mv_chan <= r_tgt[1:0];
                        mv_saddr <= r_lo[15:0]; mv_len <= r_hi[23:0];
                        mv_row <= r_tgt[15:4];    // SR12: B17.2 start row
                        mv_i16 <= r_flags[4];
                        mv_shift <= imm_res;
                        mv_cmd_valid <= 1'b1;
                        ist <= I_MOVER;
                    end
                    OP_FENCE: begin
                        mv_op <= 2'd3;
                        mv_fmask <= r_tgt[3:0];   // SR3: B17.1, 0 = all
                        mv_cmd_valid <= 1'b1;
                        ist <= I_MOVER;
                    end
                    OP_EMB: begin
                        if (emb_a[0]) begin
                            err_code <= E_ALIGN;
                            ist <= I_ERR;
                        end else begin
                            bulk_addr <= emb_a;
                            bulk_woff <= emb_a[3:1];
                            bulk_words <= r_hi[23:0];
                            bulk_left <= r_hi[23:0];
                            bulk_dst <= r_lo[15:0];
                            bulk_go <= (r_hi[23:0] != 24'd0);
                            ist <= (r_hi[23:0] == 24'd0) ? I_FETCH : I_BULKSPTR;
                            if (r_hi[23:0] == 24'd0) pc <= pc + 32'd1;
                        end
                    end
                    OP_LDC: begin
                        if (ldc_a[0]) begin
                            err_code <= E_ALIGN;
                            ist <= I_ERR;
                        end else begin
                            bulk_addr <= ldc_a[ADDR_W-1:0];
                            bulk_woff <= ldc_a[3:1];
                            bulk_words <= r_imm[23:0];
                            bulk_left <= r_imm[23:0];
                            bulk_dst <= r_tgt[15:0];
                            bulk_go <= (r_imm[23:0] != 24'd0);
                            ist <= (r_imm[23:0] == 24'd0) ? I_FETCH : I_BULKSPTR;
                            if (r_imm[23:0] == 24'd0) pc <= pc + 32'd1;
                        end
                    end
                    OP_AMAXL: ist <= I_AMAX;
                    OP_JMP: begin
                        if (r_flags[0]) begin
                            tcnt_seq <= tcnt_seq - 32'd1;
                            pc <= (tcnt_seq != 32'd1) ? r_imm : (pc + 32'd1);
                            if (tcnt_seq != 32'd1) begin
                                flush <= 1'b1; flush_pc <= r_imm;
                            end
                        end else begin
                            pc <= r_imm;
                            flush <= 1'b1; flush_pc <= r_imm;
                        end
                        ist <= I_FETCH;
                    end
                    OP_XOP: begin
                        xrf[r_tgt[2:0]] <= xop_res[17:0];
                        if ((xop_res > 32'sd262143) || (xop_res < -32'sd131072))
                            xrf_ovf <= 1'b1;
                        wt_idx <= r_tgt[2:0];
                        wt_val <= xop_res[17:0];
                        ist <= XRF_WRITE_THROUGH ? I_WTI : I_FETCH;
                        if (!XRF_WRITE_THROUGH) pc <= pc + 32'd1;
                    end
                    default: begin           // OP_HALT
                        ist <= I_HALT;
                    end
                    endcase
                end
            end

            // --------------------------------------------------------
            I_WR: if (fsm_wr_fire) begin
                pc  <= pc + 32'd1;
                ist <= I_FETCH;
            end

            I_CMDW: if (fsm_wr_fire) begin
                cmd_cnt_exp <= cmd_cnt_exp + 16'd1;
                cmd_tmo <= '0;
                ist <= I_CMDDRAIN;
            end
            // AXI gives no read/write ordering: the CMD write must LAND
            // before the STATUS poll can mean anything.
            I_CMDDRAIN: if (wr_idle) ist <= I_CMDPOLL;
            I_CMDPOLL: begin
                cmd_tmo <= cmd_tmo + 1'b1;
                if (&cmd_tmo) begin
                    err_code <= E_CMDTMO;
                    ist <= I_ERR;
                end else if (fsm_rd_fire) ist <= I_CMDPOLLW;
            end
            I_CMDPOLLW: if (rrsp_valid) begin
                if (rrsp_data[31:16] == cmd_cnt_exp) begin
                    if (rrsp_data[1]) begin              // err_op
                        err_code <= E_LAYEROP;
                        ist <= I_ERR;
                    end else if (cmd_wr_dynq8 || cmd_wr_dq16
                                 || cmd_wr_probe) begin
                        xrf_dst  <= cmd_wr_dynq8 ? 3'd0
                                  : cmd_wr_probe ? 3'd2
                                  : (arg2_sh[0] ? 3'd2 : 3'd1);
                        do_xrfrd <= 1'b1;
                        ist <= USE_XRF_SIDEBAND ? I_XRFSB
                             : cmd_wr_dynq8     ? I_XRFRD    // EOUT, 1 read
                                                : I_XRFSEL;  // XRFI -> XRFD
                    end else begin
                        pc  <= pc + 32'd1;
                        ist <= I_FETCH;
                    end
                end else ist <= I_CMDPOLL;
            end

            // XRF mirror refresh.  DYNQ8 reads EOUT directly; DYNQ16 and
            // the op-8 probe go through layer_chan's XRFI/XRFD window, so
            // the index write must LAND before the data read (drain).
            I_XRFSEL:  if (fsm_wr_fire) ist <= I_XRFSELD;
            I_XRFSELD: if (wr_idle) ist <= I_XRFRD;
            I_XRFRD: if (fsm_rd_fire) ist <= I_XRFRDW;
            I_XRFRDW: if (rrsp_valid) begin
                xrf[xrf_dst] <= (xrf_dst == 3'd0) ? {14'd0, rrsp_data[3:0]}
                                                  : rrsp_data[17:0];
                do_xrfrd <= 1'b0;
                pc  <= pc + 32'd1;
                ist <= I_FETCH;
            end
            // sideband variant: layer_chan already pushed the value
            I_XRFSB: begin
                do_xrfrd <= 1'b0;
                pc  <= pc + 32'd1;
                ist <= I_FETCH;
            end

            // write-through of a SEQ-side XRF update into layer_chan, so
            // the engine (vecnorm EPS-NORM reads k from its XRF) can never
            // see a stale copy.  Two ordered writes to one slave: no drain.
            I_WTI: if (fsm_wr_fire) ist <= I_WTD;
            I_WTD: if (fsm_wr_fire) begin
                pc  <= pc + 32'd1;
                ist <= I_FETCH;
            end

            // --------------------------------------------------------
            I_MOVER: if (mv_done || mv_err) begin
                if (mv_err) begin
                    err_code <= mv_err_code;
                    ist <= I_ERR;
                end else begin
                    pc  <= pc + 32'd1;
                    ist <= I_FETCH;
                end
            end

            // --------------------------------------------------------
            I_AMAX: if (fsm_rd_fire) ist <= I_AMAXW;
            I_AMAXW: if (rrsp_valid) begin
                xrf[3] <= rrsp_data[17:0];
                wt_idx <= 3'd3;
                wt_val <= rrsp_data[17:0];
                // full is judged on the PRE-pop count: a push that races a
                // host pop on a full FIFO is dropped (and flagged) rather
                // than squeezed into the slot the pop is freeing.
                if (of_cnt != 7'(OF_DEPTH)) begin
                    out_fifo[of_wp[5:0]] <= rrsp_data[17:0];
                    of_wp <= of_wp + 7'd1;
                end else of_ovf <= 1'b1;
                ist <= XRF_WRITE_THROUGH ? I_WTI : I_FETCH;
                if (!XRF_WRITE_THROUGH) pc <= pc + 32'd1;
            end

            // --------------------------------------------------------
            // LDC / EMB: DDR -> layer scratch.  The SPTR write stays on
            // AXI-Lite (slave state kept identical to the shipped design);
            // the word stream is now one INCR burst descriptor on m_axib
            // into the layer burst window (RUNG3 S6/S8).
            // --------------------------------------------------------
            I_BULKSPTR: if (fsm_wr_fire) begin
                bulk_bgo    <= 1'b1;
                bulk_baddr  <= LAYB_BASE + {14'd0, bulk_dst, 2'b00};
                bulk_bbeats <= bulk_words;
`ifndef SYNTHESIS
                if ((32'({8'd0, bulk_words}) + 32'({16'd0, bulk_dst}))
                    > 32'd65536)                      // G3.1: 64K words
                    $error("seq_unit LDC/EMB: scratch window overflow (dst %0d + %0d words)",
                           bulk_dst, bulk_words);
`endif
                ist <= I_BULKRUN;
            end
            I_BULKRUN: begin
                if (bulk_wvalid && bulk_wready) begin
                    bulk_left <= bulk_left - 24'd1;
                    if (bulk_left == 24'd1) ist <= I_BULKEND;
                end
            end
            // the scratch writes must be committed (all B collected) before
            // the record retires — the next record's CSR traffic reaches
            // layer_chan on the OTHER master port and would race them.
            I_BULKEND: if (wr_idle && bulk_bidle && !bulk_active) begin
                pc  <= pc + 32'd1;
                ist <= I_FETCH;
            end

            // --------------------------------------------------------
            I_HALT: begin
                busy_r <= 1'b0; halted_r <= 1'b1;
                ist <= I_IDLE;
            end
            I_ERR: begin
                busy_r <= 1'b0; halted_r <= 1'b1; err_r <= 1'b1;
                ist <= I_IDLE;
            end
            default: ist <= I_IDLE;
            endcase

            // ---- CSR slave side effects (see the slave block below) ----
            if (csr_we) begin
                case (csr_waddr)
                    10'h000: begin
                        if (csr_wdata[0] && !busy_r) start_req <= 1'b1;
                        if (csr_wdata[1]) abort_req <= 1'b1;
                    end
                    10'h002: seq_base[31:0]  <= csr_wdata;
                    10'h003: seq_base[33:32] <= csr_wdata[1:0];
                    10'h004: seq_len   <= csr_wdata;
                    10'h008: tcnt_seq  <= csr_wdata;
                    10'h009: seq_entry <= csr_wdata;
                    10'h018: begin                             // 0x60 EMBLOG2
                        // Host misuse, not a stream error: an out-of-range
                        // row size would silently corrupt every embedding
                        // fetch, so it is loud in sim and the register keeps
                        // its old value on hardware (no err_code exists for
                        // a host CSR write, and inventing one would change
                        // the frozen err map).
                        if (csr_wdata[4:0] < EMBLOG2_MIN
                                || csr_wdata[4:0] > EMBLOG2_MAX) begin
`ifndef SYNTHESIS
                            $error("seq_unit EMBLOG2: %0d outside [%0d,%0d] (host misuse), register unchanged",
                                   csr_wdata[4:0], EMBLOG2_MIN, EMBLOG2_MAX);
`endif
                        end
                        else emb_row_log2 <= csr_wdata[4:0];
                    end
                    default: if (csr_waddr[9:3] == 7'h02)      // 0x40..0x5C
                        xrf[csr_waddr[2:0]] <= csr_wdata[17:0];
                endcase
            end
            if (csr_of_pop) of_rp <= of_rp + 7'd1;
        end
    end

    // ==================================================================
    // BM1 idle counters — SEQ 0x100..0x1FC, host-read-only (docs/SEQ_ISA.md
    // B16, v2.2; spec docs/superpowers/specs/2026-09-24-board-idle-
    // counters-design.md §1.2-§1.3 + OV1's MOVX/MOVY split).
    //
    //   one WINDOW  the PERF_CYC window: counted only while busy_r
    //   one CLEAR   the START that clears the PERF_* registers (below,
    //               the same I_IDLE && start_req condition); no host write
    //               clears them (the block has no write decode), nor ABORT
    //   one READ    after HALT, over the existing AXI-Lite slave
    //
    // ALIGNMENT.  mv_busy_bm[c] is matvec_chan c's cdc_sync_stat[0] (the
    // STATUS busy bit, already on aclk) behind ONE source flop in
    // matvec_chan, then two flops here (bm_mvb_q1/q2; the net may cross an
    // SLR, so it is flop -> route -> flop with no logic between).  Every
    // LOCAL term is delayed by the SAME three cycles (bm_loc_d1..d3), so
    // each counter evaluates the values of ONE cycle: the set of cycles a
    // counter counts is exactly the set the census's negedge sampler
    // classed the same way (tb/seq_timeline.svh).  START clears while the
    // delayed busy_r is still low and a host read comes long after the
    // delayed window has closed, so the delay changes no count.
    //
    // Single clock domain: every input here is on aclk (spec §1.0).
    // ==================================================================
    localparam logic [31:0] BM_IDENT = 32'hFAB1_B301;

    // the local terms, packed so one shift register delays them together
    //   [0] busy_r  [1] mv_busy  [2] FENCE  [3] MOVX  [4] MOVY
    //   [5] ist == I_MOVER  [6] an OP_EMB record dispatched (I_EXEC, valid)
    wire [6:0] bm_loc = {
        (ist == I_EXEC) && !v_bad && (r_op == OP_EMB),
        (ist == I_MOVER),
        (mv_op == 2'd2),
        (mv_op == 2'd0),
        (mv_op == 2'd3),
        mv_busy,
        busy_r };
    logic [6:0] bm_loc_d1, bm_loc_d2, bm_loc_d3;
    logic [3:0] bm_mvb_q1, bm_mvb_q2;

    wire       bm_b    = bm_loc_d3[0];
    wire       bm_mb   = bm_loc_d3[1];
    wire       bm_fen  = bm_loc_d3[2];
    wire       bm_movx = bm_loc_d3[3];
    wire       bm_movy = bm_loc_d3[4];
    wire       bm_imov = bm_loc_d3[5];
    wire       bm_emb  = bm_loc_d3[6];
    wire       bm_any  = |bm_mvb_q2;
    wire       bm_clr  = (ist == I_IDLE) && start_req;   // == the PERF clear

    logic [31:0] bm_mvany, bm_fence, bm_mvwork, bm_mvwork_any, bm_imover,
                 bm_steps, bm_movx_c, bm_movy_c;
    logic [31:0] bm_mv [4];

    always_ff @(posedge aclk) begin
        if (!rstn) begin
            bm_loc_d1 <= '0; bm_loc_d2 <= '0; bm_loc_d3 <= '0;
            bm_mvb_q1 <= '0; bm_mvb_q2 <= '0;
            bm_mvany <= '0; bm_fence <= '0; bm_mvwork <= '0;
            bm_mvwork_any <= '0; bm_imover <= '0; bm_steps <= '0;
            bm_movx_c <= '0; bm_movy_c <= '0;
            for (int c = 0; c < 4; c++) bm_mv[c] <= '0;
        end else begin
            bm_loc_d1 <= bm_loc;
            bm_loc_d2 <= bm_loc_d1;
            bm_loc_d3 <= bm_loc_d2;
            bm_mvb_q1 <= mv_busy_bm;
            bm_mvb_q2 <= bm_mvb_q1;
            if (bm_clr) begin
                bm_mvany <= '0; bm_fence <= '0; bm_mvwork <= '0;
                bm_mvwork_any <= '0; bm_imover <= '0; bm_steps <= '0;
                bm_movx_c <= '0; bm_movy_c <= '0;
                for (int c = 0; c < 4; c++) bm_mv[c] <= '0;
            end else if (bm_b) begin
                if (bm_any)                       bm_mvany      <= bm_mvany + 32'd1;
                for (int c = 0; c < 4; c++)
                    if (bm_mvb_q2[c])             bm_mv[c]      <= bm_mv[c] + 32'd1;
                if (bm_mb && bm_fen)              bm_fence      <= bm_fence + 32'd1;
                if (bm_mb && !bm_fen)             bm_mvwork     <= bm_mvwork + 32'd1;
                if (bm_mb && !bm_fen && bm_any)   bm_mvwork_any <= bm_mvwork_any + 32'd1;
                if (bm_mb && bm_movx)             bm_movx_c     <= bm_movx_c + 32'd1;
                if (bm_mb && bm_movy)             bm_movy_c     <= bm_movy_c + 32'd1;
                if (bm_imov)                      bm_imover     <= bm_imover + 32'd1;
                if (bm_emb)                       bm_steps      <= bm_steps + 32'd1;
            end
        end
    end

    // read side: word index = araddr[7:2] inside the 0x100..0x1FC block.
    // 0x12C and 0x138..0x1FC are reserved and read 0.
    logic [31:0] bm_rdata;
    always_comb begin
        case (s_axil_araddr[7:2])
            6'h00:   bm_rdata = BM_IDENT;        // 0x100
            6'h01:   bm_rdata = bm_mvany;        // 0x104
            6'h02:   bm_rdata = bm_mv[0];        // 0x108
            6'h03:   bm_rdata = bm_mv[1];        // 0x10C
            6'h04:   bm_rdata = bm_mv[2];        // 0x110
            6'h05:   bm_rdata = bm_mv[3];        // 0x114
            6'h06:   bm_rdata = bm_fence;        // 0x118
            6'h07:   bm_rdata = bm_mvwork;       // 0x11C
            6'h08:   bm_rdata = bm_mvwork_any;   // 0x120
            6'h09:   bm_rdata = bm_imover;       // 0x124
            6'h0A:   bm_rdata = bm_steps;        // 0x128
            6'h0C:   bm_rdata = bm_movx_c;       // 0x130 (OV1's split)
            6'h0D:   bm_rdata = bm_movy_c;       // 0x134 (OV1's split)
            default: bm_rdata = 32'd0;           // 0x12C, 0x138..0x1FC
        endcase
    end

    // ---- FSM request generation ----
    always_comb begin
        fsm_wr_valid = 1'b0;
        fsm_wr_addr  = 32'd0;
        fsm_wr_data  = 32'd0;
        fsm_rd_valid = 1'b0;
        fsm_rd_addr  = 32'd0;
        case (ist)
            I_SYNC: begin fsm_rd_valid = 1'b1;
                          fsm_rd_addr  = LAYER_BASE + {20'd0, L_STAT}; end
            I_WR, I_CMDW: begin fsm_wr_valid = 1'b1;
                                fsm_wr_addr  = wr_addr_r;
                                fsm_wr_data  = wr_data_r; end
            I_CMDPOLL: begin fsm_rd_valid = 1'b1;
                             fsm_rd_addr  = LAYER_BASE + {20'd0, L_STAT}; end
            I_XRFSEL: begin fsm_wr_valid = 1'b1;
                            fsm_wr_addr  = LAYER_BASE + {20'd0, XRFI_OFF};
                            fsm_wr_data  = {29'd0, xrf_dst}; end
            I_XRFRD: begin
                fsm_rd_valid = 1'b1;
                fsm_rd_addr  = (xrf_dst == 3'd0)
                               ? (LAYER_BASE + {20'd0, L_EOUT})
                               : (LAYER_BASE + {20'd0, XRFD_OFF});
            end
            I_WTI: begin fsm_wr_valid = 1'b1;
                         fsm_wr_addr  = LAYER_BASE + {20'd0, XRFI_OFF};
                         fsm_wr_data  = {29'd0, wt_idx}; end
            I_WTD: begin fsm_wr_valid = 1'b1;
                         fsm_wr_addr  = LAYER_BASE + {20'd0, XRFD_OFF};
                         fsm_wr_data  = {14'd0, wt_val}; end
            I_AMAX: begin fsm_rd_valid = 1'b1;
                          fsm_rd_addr  = LAYER_BASE + {20'd0, L_AMAXI}; end
            I_BULKSPTR: begin fsm_wr_valid = 1'b1;
                              fsm_wr_addr  = LAYER_BASE + {20'd0, L_SPTR};
                              fsm_wr_data  = {16'd0, bulk_dst}; end
            default: ;
        endcase
    end
    assign bq_pop = bulk_wvalid && bulk_wready;

    // ==================================================================
    // seq_movers
    // ==================================================================
    seq_movers #(
        .MVGO_GUARD(MVGO_GUARD),
        .TIMEOUT_LOG2(TIMEOUT_LOG2),
        .LAYER_BASE(LAYER_BASE), .MV_BASE(MV_BASE), .MV_STRIDE(MV_STRIDE),
        .MVB_BASE(MVB_BASE), .MVB_STRIDE(MVB_STRIDE), .LAYB_BASE(LAYB_BASE)
    ) u_mov (
        .clk(aclk), .rstn(rstn),
        .cmd_valid(mv_cmd_valid), .cmd_ready(mv_cmd_ready),
        .cmd_op(mv_op), .cmd_chan(mv_chan), .cmd_saddr(mv_saddr),
        .cmd_len(mv_len), .cmd_movy_i16(mv_i16), .cmd_shift(mv_shift),
        .cmd_shape(mv_shape), .cmd_wbase(mv_wbase), .cmd_beats(mv_beats),
        .cmd_nowait(mv_nowait), .cmd_fmask(mv_fmask),
        .cmd_xword(mv_xword), .cmd_row(mv_row), .cmd_bcast(mv_bcast),   // SR12: B17.2; R3-8: B17.3
        .done(mv_done), .err(mv_err), .err_code(mv_err_code), .busy(mv_busy),
        .wr_valid(mv_wr_valid), .wr_addr(mv_wr_addr), .wr_data(mv_wr_data),
        .wr_ready(axw_ready && mv_owns), .wr_idle(wr_idle),
        .rd_valid(mv_rd_valid), .rd_addr(mv_rd_addr),
        .rd_ready(axr_ready && mv_owns),
        // response ownership: the mover must only ever see the read
        // responses IT asked for, never the issue FSM's polls
        .rd_rsp_valid(rrsp_valid && mv_owns), .rd_rsp_data(rrsp_data),
        // LDC/EMB borrow the burst WRITE engine while the mover is idle
        .ext_go(bulk_bgo), .ext_addr(bulk_baddr), .ext_beats(bulk_bbeats),
        .ext_wvalid(bulk_wvalid), .ext_wdata({16'd0, bq_dout}),
        .ext_wready(bulk_wready), .ext_idle(bulk_bidle),
        .axib_err(axib_err),
        .m_axib_awid(m_axib_awid), .m_axib_awaddr(m_axib_awaddr),
        .m_axib_awlen(m_axib_awlen), .m_axib_awsize(m_axib_awsize),
        .m_axib_awburst(m_axib_awburst), .m_axib_awvalid(m_axib_awvalid),
        .m_axib_awready(m_axib_awready),
        .m_axib_wdata(m_axib_wdata), .m_axib_wstrb(m_axib_wstrb),
        .m_axib_wlast(m_axib_wlast), .m_axib_wvalid(m_axib_wvalid),
        .m_axib_wready(m_axib_wready),
        .m_axib_bid(m_axib_bid), .m_axib_bresp(m_axib_bresp),
        .m_axib_bvalid(m_axib_bvalid), .m_axib_bready(m_axib_bready),
        .m_axib_arid(m_axib_arid), .m_axib_araddr(m_axib_araddr),
        .m_axib_arlen(m_axib_arlen), .m_axib_arsize(m_axib_arsize),
        .m_axib_arburst(m_axib_arburst), .m_axib_arvalid(m_axib_arvalid),
        .m_axib_arready(m_axib_arready),
        .m_axib_rid(m_axib_rid), .m_axib_rdata(m_axib_rdata),
        .m_axib_rresp(m_axib_rresp), .m_axib_rlast(m_axib_rlast),
        .m_axib_rvalid(m_axib_rvalid), .m_axib_rready(m_axib_rready), .xpush_valid(xpush_valid), .xpush_idx(xpush_idx), .xpush_data(xpush_data), .xpush_room(xpush_room), .xpush_busy(xpush_busy)   // R3-8
    );

    // ==================================================================
    // AXI-Lite SLAVE: the SEQ CSR block (single outstanding, always responds)
    // ==================================================================
    logic        aw_got, sw_got;
    // csr_waddr / csr_wdata / csr_we / csr_of_pop are declared with the CSR
    // registers near the top (the issue FSM reads them before this point)
    /* verilator lint_off UNUSEDSIGNAL */
    wire  [1:0]  unused_lsbs = s_axil_awaddr[1:0] | s_axil_araddr[1:0];
    wire  [3:0]  unused_bulk_lo = bulk_addr[3:0];
    wire [29:0]  unused_ldc_hi  = ldc_a[63:34];
    wire [27:0]  unused_arg0    = arg0_sh[31:4];
    wire [30:0]  unused_arg2    = arg2_sh[31:1];
    wire  [3:0]  unused_wstrb = s_axil_wstrb;
    wire         unused_rec_valid = rec_valid;
    wire         unused_rd_idle = rd_idle;
    wire         unused_do_xrfrd = do_xrfrd;
    wire  [31:0] unused_arg1 = arg1_sh;
    wire  [17:0] unused_sb = USE_XRF_SIDEBAND ? 18'd0 : xrf_sb_data;
    wire   [2:0] unused_sbi = USE_XRF_SIDEBAND ? 3'd0 : xrf_sb_idx;
    wire         unused_sbw = USE_XRF_SIDEBAND ? 1'b0 : xrf_sb_we;
    /* verilator lint_on UNUSEDSIGNAL */

    assign s_axil_awready = !aw_got  && !s_axil_bvalid;
    assign s_axil_wready  = !sw_got  && !s_axil_bvalid;
    assign s_axil_arready = !s_axil_rvalid;

    wire [17:0] of_head = out_fifo[of_rp[5:0]];

    always_ff @(posedge aclk) begin
        if (!rstn) begin
            aw_got <= 1'b0; sw_got <= 1'b0;
            s_axil_bvalid <= 1'b0; s_axil_bresp <= 2'b00;
            s_axil_rvalid <= 1'b0; s_axil_rresp <= 2'b00;
            s_axil_rdata <= '0;
            csr_we <= 1'b0; csr_of_pop <= 1'b0;
            csr_waddr <= '0; csr_wdata <= '0;
        end else begin
            csr_we     <= 1'b0;
            csr_of_pop <= 1'b0;

            if (s_axil_awvalid && s_axil_awready) begin
                aw_got <= 1'b1; csr_waddr <= s_axil_awaddr[11:2];
            end
            if (s_axil_wvalid && s_axil_wready) begin
                sw_got <= 1'b1; csr_wdata <= s_axil_wdata;
            end
            if (aw_got && sw_got && !s_axil_bvalid) begin
                csr_we <= 1'b1;
                s_axil_bvalid <= 1'b1; s_axil_bresp <= 2'b00;
                aw_got <= 1'b0; sw_got <= 1'b0;
            end
            if (s_axil_bvalid && s_axil_bready) s_axil_bvalid <= 1'b0;

            if (s_axil_arvalid && s_axil_arready) begin
                s_axil_rvalid <= 1'b1; s_axil_rresp <= 2'b00;
                case (s_axil_araddr[11:2])
                    10'h000: s_axil_rdata <= {29'd0, halted_r, err_r, busy_r};
                    10'h001: s_axil_rdata <= {err_code, of_ovf, of_cnt,
                                              13'd0, halted_r, err_r, busy_r};
                    10'h002: s_axil_rdata <= seq_base[31:0];
                    10'h003: s_axil_rdata <= {30'd0, seq_base[33:32]};
                    10'h004: s_axil_rdata <= seq_len;
                    10'h005: s_axil_rdata <= pc;
                    10'h006: begin
                        s_axil_rdata <= {(of_cnt != 7'd0), 13'd0, of_head};
                        // rung-4 S6 pop-race fix (tb_seq_unit +ofrace): pop
                        // ONLY if this read is actually delivering a token.
                        // With an unconditional strobe, a read that reported
                        // EMPTY at its accept edge still popped one cycle
                        // later if an AMAXL push landed on that same edge —
                        // the entry was consumed by nobody (token loss).
                        csr_of_pop   <= (of_cnt != 7'd0);
                    end
                    10'h007: s_axil_rdata <= {25'd0, of_cnt};
                    10'h008: s_axil_rdata <= tcnt_seq;
                    10'h009: s_axil_rdata <= seq_entry;
                    10'h00A: s_axil_rdata <= IDENT;
                    10'h00B: s_axil_rdata <= perf_cyc;
                    10'h00C: s_axil_rdata <= perf_rec;
                    10'h00D: s_axil_rdata <= perf_axw;
                    10'h00E: s_axil_rdata <= perf_axr;
                    10'h00F: s_axil_rdata <= {perf_fst[31:1], xrf_ovf};
                    10'h018: s_axil_rdata <= {27'd0, emb_row_log2}; // EMBLOG2
                    10'h019: s_axil_rdata <= SEQ_CAPS;       // SR3: B17.0
                    default: if (s_axil_araddr[11:5] == 7'h02)
                        s_axil_rdata <= {14'd0, xrf[s_axil_araddr[4:2]]};
                    else if (s_axil_araddr[11:8] == 4'h1)       // BM1 0x100..0x1FC
                        s_axil_rdata <= bm_rdata;
                    else s_axil_rdata <= 32'hDEAD_C0DE;
                endcase
            end else if (s_axil_rvalid && s_axil_rready)
                s_axil_rvalid <= 1'b0;
        end
    end

    assign seq_busy   = busy_r;
    assign seq_halted = halted_r;
    assign seq_err    = err_r;


    // ==================================================================
    // R3-8 (docs/SEQ_ISA.md v2.3 B17.3): the MOVX BROADCAST.  Appended
    // below every cited line (zero drift); the edits above are one line
    // each:
    //   * the validator (the OP_MOVX/OP_MVGO arm): MOVX flags[7:4] = 0xF is
    //     ADMITTED and falls through to the B17.2 start-word rule
    //     (v_movx_rsvd, err 0x06) on its ONE window; MOVX 4..14 and every
    //     MVGO >= 4 (0xF included) keep E_CHAN (0x05); MOVY is untouched
    //     (target[3:0] >= 4 is still 0x05: there is no broadcast MOVY).
    //     The admission here is the RTL's; the device-keyed host validator
    //     (ref/seq_format, caps {R1,R2,R3} from SEQ_CAPS) refuses first;
    //   * the MOVX dispatch sets mv_bcast = (flags[7:4] == 0xF), reset with
    //     the other mv_* (seq_movers qualifies it with MOP_MOVX, so a stale
    //     1 under a later MVGO/MOVY/FENCE is inert);
    //   * u_mov gains .cmd_bcast and the four-channel x-push ports, which
    //     leave this module as xpush_valid[3:0] / xpush_idx[47:0] /
    //     xpush_data[127:0] (channel c at [c], [12c +: 12], [32c +: 32]) and
    //     come back as xpush_room[3:0] / xpush_busy[3:0] — FLOPS at both
    //     ends inside seq_movers (its R3 block), plain wires here;
    //     rtl/seq_unit_ipi.v splits them into per-channel scalar pins for
    //     the block design (synth/scripts/create_project.tcl);
    //   * SEQ_CAPS = 0xFAB1CA07 = sw/hwmap.py's seq_caps_word({"R1", "R2",
    //     "R3"}), read back by tb_seq_unit against <vec>.caps.hex.
    // ==================================================================

endmodule

`default_nettype wire
