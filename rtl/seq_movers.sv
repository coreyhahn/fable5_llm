// seq_movers: the three SEQ data movers — MOVX, MVGO, MOVY (+ the engine
// side of FENCE).  Instantiated inside seq_unit.
//
// RUNG 3 (docs/RUNG3_SPEC.md, frozen 2026-08-10).  The bulk data streams no
// longer cross the fabric as single-beat AXI-Lite transactions: seq_movers
// now OWNS a 32-bit AXI4 burst master (`m_axib`, S3) that reaches the engine
// RES/XWIN windows and the layer scratchpad through a private 1x5
// SmartConnect (burst_smc, S2) on its own 64 KiB-stride address map (S4):
//
//     mvchan_c   (c+1) << 16    READ  0x0000-0x3FFF  RES row r at byte 4r
//                               WRITE 0x4000-0x6FFF  XWIN word w at byte 4w
//     layer_0        8 << 16    R/W   scratch word w at byte 4w, w<65536
//
// R-b moved the layer window from 5<<16 to 6<<16 and doubled it to 128 KiB
// (32768 words).  G3.1 doubles it AGAIN, to 256 KiB (65536 words), and
// moves it 6<<16 -> 8<<16 for the same reason R-b moved it: an AXI segment
// must be RANGE-ALIGNED, and 0x60000 is not a 256 KiB-aligned address —
// 0x80000 is.  layer_0 now covers 0x80000-0xBFFFF and the decode hole after
// the four 64 KiB mvchan windows grows to 0x50000-0x7FFFF.  Mirrored in
// rtl/seq_unit.sv LAYB_BASE, synth/scripts/create_project.tcl's
// seq_axib_map AND its per-slave range expectation (which `exit 1`s on any
// range it does not expect), tb/tb_burst_fabric.sv LAYBASE, and
// docs/SEQ_ISA.md B12.3.
//
// What still goes out on AXI-Lite (bit-identical to the shipped design, so
// every host-driven ladder keeps passing):
//   * MOVX  SPTR + XPTR setup writes, and the closing STATUS read
//   * MVGO  WBASE/BEATS/SHAPE + doorbell, and the whole poll path (S9)
//   * MOVY  RES_PTR + SPTR setup writes
//   * FENCE the poll path.  SR3 (docs/SEQ_ISA.md v2.3 B17.1): cmd_fmask
//     selects WHICH pending channels a FENCE drains — bit c = chan_pend[c],
//     0 = all four (latched as 4'hF).  F_SCAN still walks channels 0..3 one
//     per cycle, so a mask-0 FENCE takes exactly the pre-SR3 cycles; an
//     unmasked pending channel is left pending (no interlock — the model
//     gate and the pass's assert refuse such streams, not this RTL).
//   SR12 (docs/SEQ_ISA.md v2.3 B17.2, R2): MOVX's XPTR write stays 0 (the
//     burst carries the x word in its address, cmd_xword = the XWIN start
//     word added to the burst base); MOVY's RES_PTR write carries the RES
//     start row (cmd_row), which also starts the RES burst.  SHAPE is still
//     written whole — its bank bits 29/30 are the mvchan's to decode.  Still
//     no interlock: a MOVX/MOVY into the OTHER bank of a pending channel is
//     legal and one into its running range is refused by the model gate.
// What moved to m_axib: the MOVX scratch->XWIN stream, the MOVY RES->scratch
// stream, and (through the ext_* client port below) seq_unit's LDC/EMB
// DDR->scratch stream.
//
// ---------------------------------------------------------------------
// Constraints, and what rung 3 did to them
// ---------------------------------------------------------------------
// C1  RETIRED ON THE BURST PATH.  matvec_chan RES_DATA (0x30) returns the
//     port-B output of a READ_LATENCY_B=2 BRAM addressed by res_ptr and
//     bumps res_ptr in the same cycle, so two AXI-Lite RES_DATA reads closer
//     than 3 cycles returned STALE data and MOVY had to pace them (RES_GAP).
//     The burst window (S5) drives addrb from the AXI address and honours
//     READ_LATENCY_B=2 inside the shim, so the pacer is GONE; the read side
//     is now plain RREADY backpressure (S8).  The AXI-Lite RES_PTR/RES_DATA
//     registers are untouched and still behave exactly as they did.
// C2  UNCHANGED.  matvec_chan STATUS.done is STICKY UNTIL THE NEXT START and
//     the doorbell crosses into ui_clk through a toggle+2FF, so MVGO still
//     waits MVGO_GUARD (default 64) aclk cycles after the doorbell before it
//     polls (S9: no done-wire in v1).
// C3  NEW.  AXI gives no ordering between two different master ports.  Every
//     point where an AXI-Lite access must observe the effect of burst
//     traffic (MOVX's STATUS read after the XWIN pushes) or where the next
//     record's CSR traffic must observe it (MOVY's scratch writes) drains
//     the burst write engine first (bw_idle = every B response collected).
//
// Divergence note: MOVX zero-pads the final XWIN word when the length is
// not a multiple of 4.  Every emitted stream uses K multiples of 4
// (1024/2048/3584), so only the unit TB exercises that path.

`timescale 1ns/1ps
`default_nettype none

module seq_movers #(
    parameter int MVGO_GUARD   = 64,     // doorbell -> first STATUS poll
    parameter int TIMEOUT_LOG2 = 26,     // engine/poll watchdog
    // AXI-Lite CSR map (unchanged)
    parameter logic [31:0] LAYER_BASE = 32'h0000_5000,
    parameter logic [31:0] MV_BASE    = 32'h0000_1000,
    parameter logic [31:0] MV_STRIDE  = 32'h0000_1000,
    // m_axib burst map (RUNG3 S4)
    parameter logic [31:0] MVB_BASE   = 32'h0001_0000,
    parameter logic [31:0] MVB_STRIDE = 32'h0001_0000,
    parameter logic [31:0] LAYB_BASE  = 32'h0008_0000
) (
    input  wire         clk,
    input  wire         rstn,

    // ---------------- command interface (from seq_unit's issue FSM) ----
    input  wire         cmd_valid,      // 1-cycle request, taken when ready
    output logic        cmd_ready,      // idle
    input  wire  [1:0]  cmd_op,         // MOP_*
    input  wire  [1:0]  cmd_chan,
    input  wire [15:0]  cmd_saddr,      // MOVX src / MOVY dst scratch word
    input  wire [23:0]  cmd_len,        // MOVX words, MOVY rows
    input  wire         cmd_movy_i16,   // MOVY: 1 = int16, 0 = int32 pairs
    input  wire signed [31:0] cmd_shift,// MOVY dequant shift (resolved)
    input  wire [31:0]  cmd_shape,      // MVGO SHAPE
    input  wire [39:0]  cmd_wbase,      // MVGO weight base
    input  wire [23:0]  cmd_beats,      // MVGO 64 B beats
    input  wire         cmd_nowait,     // MVGO: return before engine done
    input  wire  [3:0]  cmd_fmask,      // FENCE channel mask, 0 = all (SEQ_ISA B17.1)
    input  wire [11:0]  cmd_xword,      // MOVX XWIN start word (SEQ_ISA B17.2, SR12)
    input  wire [11:0]  cmd_row,  input wire cmd_bcast,  // MOVY RES start row (SEQ_ISA B17.2, SR12); cmd_bcast: MOVX broadcast (B17.3, R3-8)

    output logic        done,           // 1-cycle retire
    output logic        err,            // 1-cycle, with err_code
    output logic  [7:0] err_code,
    output logic        busy,

    // ---------------- seq_unit AXI-Lite request channels ---------------
    output logic        wr_valid,
    output logic [31:0] wr_addr,
    output logic [31:0] wr_data,
    input  wire         wr_ready,
    input  wire         wr_idle,        // no writes outstanding anywhere

    output logic        rd_valid,
    output logic [31:0] rd_addr,
    input  wire         rd_ready,
    input  wire         rd_rsp_valid,
    input  wire  [31:0] rd_rsp_data,

    // ---------------- external burst-WRITE client (seq_unit LDC/EMB) ---
    // Served only while the mover is idle; seq_unit's issue FSM never has a
    // mover op and a bulk op in flight at the same time (I_MOVER vs
    // I_BULKRUN are different states of one single-threaded FSM).
    input  wire         ext_go,         // 1-cycle descriptor start
    input  wire [31:0]  ext_addr,       // byte address in the m_axib map
    input  wire [23:0]  ext_beats,      // beats (= 32-bit words)
    input  wire         ext_wvalid,
    input  wire [31:0]  ext_wdata,
    output logic        ext_wready,
    output logic        ext_idle,       // burst write engine fully drained

    output logic        axib_err,       // sticky RRESP/BRESP != OKAY

    // ---------------- AXI4 burst master (S3): 32b data, 32b addr -------
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
    output logic        m_axib_rready,  output logic [3:0] xpush_valid, output logic [47:0] xpush_idx, output logic [127:0] xpush_data, input wire [3:0] xpush_room, input wire [3:0] xpush_busy  // R3-8 x-push bus (aclk), the R3 block at the end
);

    // ------------------------------------------------------------------
    // op codes on cmd_op, and the CSR offsets we drive
    // ------------------------------------------------------------------
    localparam logic [1:0] MOP_MOVX  = 2'd0;
    localparam logic [1:0] MOP_MVGO  = 2'd1;
    localparam logic [1:0] MOP_MOVY  = 2'd2;
    localparam logic [1:0] MOP_FENCE = 2'd3;

    localparam logic [11:0] L_SPTR    = 12'h014;
    localparam logic [11:0] MV_CTRL   = 12'h000;
    localparam logic [11:0] MV_STATUS = 12'h004;
    localparam logic [11:0] MV_WBLO   = 12'h008;
    localparam logic [11:0] MV_WBHI   = 12'h00C;
    localparam logic [11:0] MV_BEATS  = 12'h010;
    localparam logic [11:0] MV_SHAPE  = 12'h014;
    localparam logic [11:0] MV_XPTR   = 12'h028;
    localparam logic [11:0] MV_RESPTR = 12'h02C;

    // burst-window offsets inside a mvchan (S5)
    localparam logic [31:0] MVB_RES  = 32'h0000_0000;   // 4096 rows  x 4 B
    localparam logic [31:0] MVB_XWIN = 32'h0000_4000;   // 3072 words x 4 B

    // window sizes, in 32-bit words (sim-only bounds checks, S(interface))
    localparam int RES_WORDS   = 4096;
    localparam int XWIN_WORDS  = 3072;   // K <= 12288 (matvec_engine MAX_NG 96).
                                         // THE SECOND COPY: rtl/matvec_chan.sv
                                         // declares its own and the two must
                                         // move together (spec 4.5 W5).
    localparam int SCR_WORDS   = 65536;   // G3.1, spec 4.3 S4

    // error codes (also listed in seq_unit's header + docs/SEQ_ISA notes)
    localparam logic [7:0] E_AXI      = 8'h12;   // m_axib RRESP/BRESP != OK
    localparam logic [7:0] E_MVGO_ENG = 8'h20;   // STATUS.err_rresp
    localparam logic [7:0] E_MVGO_TMO = 8'h21;   // engine never said done
    localparam logic [7:0] E_XFIFO_OVF= 8'h22;   // XWIN fifo overflow
    localparam logic [7:0] E_MOVER_TMO= 8'h23;   // mover stream stalled

    // S8: the elastic buffer grows 16 -> 32 now that a burst can deliver a
    // beat every cycle and the write side is credit-gated, not paced.
    localparam int YF_DEPTH = 32;

    function automatic logic [31:0] mvaddr(input logic [1:0] c,
                                           input logic [11:0] off);
        mvaddr = MV_BASE + (MV_STRIDE * {30'd0, c}) + {20'd0, off};
    endfunction

    function automatic logic [31:0] laddr(input logic [11:0] off);
        laddr = LAYER_BASE + {20'd0, off};
    endfunction

    // burst-space addresses
    function automatic logic [31:0] mvbaddr(input logic [1:0] c,
                                            input logic [31:0] off);
        mvbaddr = MVB_BASE + (MVB_STRIDE * {30'd0, c}) + off;
    endfunction

    function automatic logic [31:0] scrbaddr(input logic [15:0] w);
        scrbaddr = LAYB_BASE + {14'd0, w, 2'b00};
    endfunction

    // ------------------------------------------------------------------
    // latched command
    // ------------------------------------------------------------------
    logic  [1:0] chan_q;
    logic [15:0] saddr_q;
    logic [23:0] len_q;
    logic        i16_q, nowait_q;
    logic signed [31:0] shift_q;
    logic [31:0] shape_q;
    logic [39:0] wbase_q;
    logic [23:0] beats_q;
    // S12 (v2 door): the RES burst read start row is a full 12-bit field
    // carried in the AXI address, never hardwired zero.  v1 always starts a
    // MOVY at row 0 — exactly what the RES_PTR=0 write it still issues means
    // — but the datapath below is already row-addressed, so an overlapped
    // (partial-drain) MOVY only has to load this register differently.
    // SR12 (SEQ_ISA v2.3 B17.2): it does — res_row_q loads the record's
    // target[15:4] (cmd_row), and the RES_PTR write carries the same row.
    logic [11:0] res_row_q;
    // SR12 (B17.2): the MOVX XWIN start word, added to the XWIN burst base
    // (the shim takes the word from the address, rtl/matvec_chan.sv).
    logic [11:0] xword_q;  logic bcast_q, xp_fire, xp_done;  wire cmd_is_bc = cmd_bcast && (cmd_op == MOP_MOVX);  // R3-8 (B17.3), the R3 block

    // per-channel "engine started by a no-wait MVGO, not yet drained"
    logic [3:0]  chan_pend;
    logic [1:0]  fence_chan;
    logic [3:0]  fmask_q;           // SR3: the FENCE's channel mask, 0 -> F
    logic        poll_is_fence;

    // ------------------------------------------------------------------
    // FSM (shape UNCHANGED — S8; only what the states request moved)
    // ------------------------------------------------------------------
    typedef enum logic [4:0] {
        S_IDLE,
        X_SPTR, X_XPTR, X_DRAIN, X_RUN, X_END, X_STAT, X_STATW,
        G_CFG, G_DOOR, G_DRAIN, G_GUARD, G_POLL, G_POLLW,
        Y_RESPTR, Y_SPTR, Y_DRAIN, Y_RUN, Y_END,
        F_SCAN, S_DONE
    } state_e;
    state_e st;

    logic  [2:0] cfg_step;                    // MVGO config-write walker
    logic [23:0] rd_got;                      // burst read beats consumed
    logic [TIMEOUT_LOG2-1:0] tmo;
    logic [31:0] guard_cnt;

    // MOVX byte packer
    logic [31:0] pack_acc;
    logic  [1:0] pack_idx;

    // elastic buffer between the read-response side and the write side.
    // MOVX pushes assembled 32-bit XWIN words; MOVY pushes raw y32 rows.
    logic [31:0] yf_mem [YF_DEPTH];
    logic  [5:0] yf_wp, yf_rp, yf_cnt;
    logic        yf_push, yf_pop;
    logic [31:0] yf_din;
    wire  [31:0] yf_dout = yf_mem[yf_rp[4:0]];

    // MOVY store walker: 0 = int16 word / pairs lo, 1 = pairs hi
    logic        y_half;
    logic [31:0] y_val;
    logic        y_val_valid;

    // MOVY dequant pipeline (Y_RUN): yf pop -> S1 -> S2 -> S3 -> S4(=y_val).
    // The dequant shift is CONSTANT for a transfer, so it is decoded ONCE at
    // Y_DRAIN into dq_left/dq_m/dq_add and never sits on the per-element
    // path.  Each element's y_val is bit-identical to the former
    // clip_out(deq(yf_dout, shift_q), i16_q); only its latency moved, and
    // the elastic FIFO + the write side's own 1/2-cycle drain absorb it.
    logic        dq_left;              // shift_q < 0  (exact left shift)
    logic  [5:0] dq_m;                 // capped shift magnitude (deq's m)
    logic [63:0] dq_add;               // right-shift round const (0 for left)
    logic        s1_valid, s1_sgn;
    logic signed [63:0] s1_v64;
    logic        [63:0] s1_mag;
    logic        s2_valid, s2_sgn;
    logic        [63:0] s2_rsh;
    logic signed [63:0] s2_lsh;
    logic        s3_valid;
    logic signed [63:0] s3_t;

    wire rd_fire = rd_valid && rd_ready;
    wire wr_fire = wr_valid && wr_ready;

    // ==================================================================
    // AXI4 burst master (m_axib).  Two independent descriptor engines —
    // one read, one write — each splitting a (byte address, beat count)
    // request into INCR bursts of <= 256 beats that never cross a 4 KiB
    // boundary (S7).  MOVY runs both at once (RES read + scratch write).
    // ==================================================================
    // beats a burst starting at `a12` may take: min(256, left, to-4K-bound)
    function automatic logic [8:0] bbeats(input logic [11:0] a12,
                                          input logic [23:0] left);
        logic [10:0] to_bound;
        logic  [8:0] want;
        begin
            to_bound = 11'((13'h1000 - {1'b0, a12}) >> 2);
            want     = (left > 24'd256) ? 9'd256 : 9'(left);
            bbeats   = ({2'd0, want} > to_bound) ? 9'(to_bound) : want;
        end
    endfunction

    // ---- descriptor start (mover FSM, or the ext client while idle) ----
    logic        bw_start, br_start;              // registered 1-cycle pulses
    logic [31:0] bw_saddr, br_saddr;
    logic [23:0] bw_sbeats, br_sbeats;

    wire         ext_owns  = !busy;
    wire         bwr_go    = bw_start || (ext_go && ext_owns);
    wire [31:0]  bwr_addr  = bw_start ? bw_saddr  : ext_addr;
    wire [23:0]  bwr_beats = bw_start ? bw_sbeats : ext_beats;

    // ---- write engine: AW walker, W walker, B counter ----
    logic [31:0] aw_addr, w_addr;
    logic [23:0] aw_left, w_left;
    logic  [8:0] w_cnt;            // beats left in the CURRENT W burst
    logic  [1:0] aw_credit;        // AWs issued the W walker has not consumed
    logic  [3:0] b_out;            // write bursts awaiting B

    wire [8:0] aw_len_c = bbeats(aw_addr[11:0], aw_left);
    wire [8:0] w_len_c  = bbeats(w_addr[11:0],  w_left);
    wire [8:0] w_cur    = (w_cnt == 9'd0) ? w_len_c : w_cnt;

    // the burst write DATA source: mover stream, or the ext client
    logic        bwd_valid;
    logic [31:0] bwd_data;

    wire w_gate = (w_left != 24'd0) && (aw_credit != 2'd0);

    assign m_axib_awid    = 1'b0;
    assign m_axib_awaddr  = aw_addr;
    assign m_axib_awlen   = 8'(aw_len_c - 9'd1);
    assign m_axib_awsize  = 3'b010;                     // 4 B
    assign m_axib_awburst = 2'b01;                      // INCR
    assign m_axib_awvalid = (aw_left != 24'd0) && (aw_credit < 2'd2)
                            && (b_out < 4'd8);
    assign m_axib_wdata   = bwd_data;
    assign m_axib_wstrb   = 4'hF;
    assign m_axib_wlast   = (w_cur == 9'd1);
    assign m_axib_wvalid  = w_gate && bwd_valid;
    assign m_axib_bready  = 1'b1;

    wire aw_fire = m_axib_awvalid && m_axib_awready;
    wire bw_fire = m_axib_wvalid  && m_axib_wready;
    wire wl_fire = bw_fire && (w_cur == 9'd1);          // burst's last beat

    wire bw_idle = (aw_left == 24'd0) && (w_left == 24'd0) && (b_out == 4'd0);

    // ---- read engine: AR walker, R counter ----
    logic [31:0] ar_addr;
    logic [23:0] ar_left, r_rem;
    logic  [2:0] ar_out;           // read bursts awaiting RLAST
    logic        brd_ready;

    wire [8:0] ar_len_c = bbeats(ar_addr[11:0], ar_left);

    assign m_axib_arid    = 1'b0;
    assign m_axib_araddr  = ar_addr;
    assign m_axib_arlen   = 8'(ar_len_c - 9'd1);
    assign m_axib_arsize  = 3'b010;
    assign m_axib_arburst = 2'b01;
    assign m_axib_arvalid = (ar_left != 24'd0) && (ar_out < 3'd4);
    assign m_axib_rready  = brd_ready;

    wire ar_fire = m_axib_arvalid && m_axib_arready;
    wire br_fire = m_axib_rvalid  && m_axib_rready;

    // ---- the engines ----
    always_ff @(posedge clk) begin
        if (!rstn) begin
            aw_addr <= '0; aw_left <= '0; w_addr <= '0; w_left <= '0;
            w_cnt <= '0; aw_credit <= '0; b_out <= '0;
            ar_addr <= '0; ar_left <= '0; r_rem <= '0; ar_out <= '0;
            axib_err <= 1'b0;
        end else begin
            // ---------------- write ----------------
            if (bwr_go) begin
                aw_addr <= bwr_addr; aw_left <= bwr_beats;
                w_addr  <= bwr_addr; w_left  <= bwr_beats;
                w_cnt   <= 9'd0;     aw_credit <= 2'd0;
`ifndef SYNTHESIS
                if (b_out != 4'd0)
                    $error("seq_movers: burst write descriptor started with %0d B outstanding",
                           b_out);
`endif
            end else begin
                if (aw_fire) begin
                    aw_addr <= aw_addr + {21'd0, aw_len_c, 2'b00};
                    aw_left <= aw_left - 24'({15'd0, aw_len_c});
                end
                if (bw_fire) begin
                    w_addr <= w_addr + 32'd4;
                    w_left <= w_left - 24'd1;
                    w_cnt  <= (w_cur == 9'd1) ? 9'd0 : (w_cur - 9'd1);
                end
                case ({aw_fire, wl_fire})
                    2'b10:   aw_credit <= aw_credit + 2'd1;
                    2'b01:   aw_credit <= aw_credit - 2'd1;
                    default: ;
                endcase
            end
            case ({aw_fire, m_axib_bvalid})
                2'b10:   b_out <= b_out + 4'd1;
                2'b01:   b_out <= b_out - 4'd1;
                default: ;
            endcase

            // ---------------- read ----------------
            if (br_start) begin
                ar_addr <= br_saddr; ar_left <= br_sbeats; r_rem <= br_sbeats;
                ar_out  <= 3'd0;
            end else begin
                if (ar_fire) begin
                    ar_addr <= ar_addr + {21'd0, ar_len_c, 2'b00};
                    ar_left <= ar_left - 24'({15'd0, ar_len_c});
                end
                if (br_fire && (r_rem != 24'd0)) r_rem <= r_rem - 24'd1;
                case ({ar_fire, (br_fire && m_axib_rlast)})
                    2'b10:   ar_out <= ar_out + 3'd1;
                    2'b01:   ar_out <= ar_out - 3'd1;
                    default: ;
                endcase
            end

            // ---------------- response codes ----------------
            if (bwr_go || br_start) axib_err <= 1'b0;
            else if ((m_axib_bvalid && (m_axib_bresp != 2'b00))
                     || (br_fire && (m_axib_rresp != 2'b00)))
                axib_err <= 1'b1;
        end
    end

    assign ext_idle   = bw_idle;
    assign ext_wready = ext_owns && w_gate && m_axib_wready;

    // ------------------------------------------------------------------
    // dequant: rshr64s(v, shift) + round-half-away, then clip
    // (bit-for-bit ref/w4a8_ref.rshift_round + seq_model.rs_s/clip16)
    //
    // The former single-cycle `deq()` function was a full 64-bit variable
    // shifter; it is now the Y_RUN pipeline (dq_* / S1..S4 above).  The
    // per-transfer shift decode -> (dq_left, dq_m, dq_add) happens once in
    // Y_DRAIN and is the SAME m/add `deq` derived from sh:
    //     sh >= 0 : m = min(sh,63); add = (m==0)?0:(1<<(m-1))    (right, round)
    //     sh <  0 : m = min(-sh,40); add = 0                     (exact left)
    // and the element datapath is
    //     right : sgn ? -((|v|+add) >> m) : ((|v|+add) >> m)
    //     left  : v <<< m
    // followed by clip_out — algebraically identical to `deq` for every v.
    // ------------------------------------------------------------------
    // dequant pipeline stage functions (combinational; bit-exact vs deq)
    //   S1 in : v64 (sign-extended row) and its magnitude av
    //   S3    : apply sign to the shifted magnitude, select left vs right
    wire signed [63:0] dq_v64 = 64'(signed'(yf_dout));      // deq: v = 64'(y)
    wire        [63:0] dq_av  = dq_v64[63] ? unsigned'(-dq_v64)
                                           : unsigned'(dq_v64);
    wire signed [63:0] dq_rres = s2_sgn ? -signed'(s2_rsh) : signed'(s2_rsh);
    wire signed [63:0] dq_t    = dq_left ? signed'(s2_lsh) : dq_rres;
    // advance the pipeline when S4 (y_val) is free or drains this cycle;
    // launch (pop + inject S1) only when advancing AND the FIFO has a row
    wire pipe_adv = (st == Y_RUN)
                    && (!y_val_valid || (bw_fire && (i16_q || y_half)));
    wire launch   = pipe_adv && (yf_cnt != 6'd0);

    function automatic logic [31:0] clip_out(input logic signed [63:0] t,
                                             input logic i16);
        logic signed [31:0] c;
        begin
            if (i16) begin
                if (t > 64'sd32767)            c = 32'sd32767;
                else if (t < -64'sd32768)      c = -32'sd32768;
                else                           c = t[31:0];
            end else begin
                if (t > 64'sd2147483647)       c = 32'sh7FFF_FFFF;
                else if (t < -64'sd2147483648) c = 32'sh8000_0000;
                else                           c = t[31:0];
            end
            clip_out = c;
        end
    endfunction

    // insert one int8 into the packing accumulator at byte `idx`
    function automatic logic [31:0] ins_byte(input logic [31:0] acc,
                                             input logic  [1:0] idx,
                                             input logic  [7:0] b);
        logic [31:0] r;
        begin
            r = acc;
            case (idx)
                2'd0: r[7:0]   = b;
                2'd1: r[15:8]  = b;
                2'd2: r[23:16] = b;
                default: r[31:24] = b;
            endcase
            ins_byte = r;
        end
    endfunction

    // zero the bytes ABOVE `idx` (ragged MOVX tail)
    function automatic logic [31:0] mask_tail(input logic [31:0] acc,
                                              input logic  [1:0] idx);
        logic [31:0] r;
        begin
            r = acc;
            if (idx < 2'd3) r[31:24] = 8'd0;
            if (idx < 2'd2) r[23:16] = 8'd0;
            if (idx < 2'd1) r[15:8]  = 8'd0;
            mask_tail = r;
        end
    endfunction

    wire        x_last_rsp = br_fire && ((rd_got + 24'd1) == len_q);
    wire [31:0] x_word     = mask_tail(ins_byte(pack_acc, pack_idx,
                                                m_axib_rdata[7:0]), pack_idx);

    // MOVX XWIN words for a length of len_q int8 elements
    wire [23:0] x_wwords = 24'((len_q + 24'd3) >> 2);
    // MOVY scratch words for len_q result rows
    wire [23:0] y_wwords = i16_q ? len_q : 24'(len_q << 1);

    // ------------------------------------------------------------------
    // elastic buffer
    // ------------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (!rstn) begin
            yf_wp <= '0; yf_rp <= '0; yf_cnt <= '0;
        end else begin
            if (yf_push) begin
                yf_mem[yf_wp[4:0]] <= yf_din;
                yf_wp <= yf_wp + 6'd1;
            end
            if (yf_pop) yf_rp <= yf_rp + 6'd1;
            case ({yf_push, yf_pop})
                2'b10:   yf_cnt <= yf_cnt + 6'd1;
                2'b01:   yf_cnt <= yf_cnt - 6'd1;
                default: ;
            endcase
        end
    end

    assign yf_din  = (st == X_RUN) ? x_word : m_axib_rdata;
    assign yf_push = br_fire
                     && (((st == X_RUN) && ((pack_idx == 2'd3) || x_last_rsp))
                         || (st == Y_RUN));
    assign yf_pop  = ((st == X_RUN) && (bw_fire || xp_fire)) || launch;   // R3-8: a broadcast pops on a push

    // S8: plain RREADY backpressure replaces the outstanding-count throttle.
    // Outside the streaming states R is accepted and dropped so a watchdog
    // abort can never leave the fabric holding beats.
    always_comb begin
        case (st)
            X_RUN, Y_RUN: brd_ready = (yf_cnt < 6'(YF_DEPTH));
            default:      brd_ready = 1'b1;
        endcase
    end

    // burst-write data source
    always_comb begin
        if (ext_owns) begin
            bwd_valid = ext_wvalid;
            bwd_data  = ext_wdata;
        end else if (st == X_RUN) begin
            bwd_valid = (yf_cnt != 6'd0);
            bwd_data  = yf_dout;
        end else if (st == Y_RUN) begin
            bwd_valid = y_val_valid;
            bwd_data  = y_half ? {16'd0, y_val[31:16]} : {16'd0, y_val[15:0]};
        end else begin
            bwd_valid = 1'b0;
            bwd_data  = 32'd0;
        end
    end

    // ------------------------------------------------------------------
    // main FSM
    // ------------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (!rstn) begin
            st <= S_IDLE;
            chan_q <= '0; saddr_q <= '0; len_q <= '0;
            i16_q <= 1'b0; nowait_q <= 1'b0; shift_q <= '0;
            shape_q <= '0; wbase_q <= '0; beats_q <= '0; res_row_q <= '0;
            xword_q <= '0; bcast_q <= 1'b0;
            chan_pend <= '0; fence_chan <= '0; poll_is_fence <= 1'b0;
            fmask_q <= '0;
            cfg_step <= '0; rd_got <= '0;
            tmo <= '0; guard_cnt <= '0;
            pack_acc <= '0; pack_idx <= '0;
            y_half <= 1'b0; y_val <= '0; y_val_valid <= 1'b0;
            dq_left <= 1'b0; dq_m <= '0; dq_add <= '0;
            s1_valid <= 1'b0; s2_valid <= 1'b0; s3_valid <= 1'b0;
            bw_start <= 1'b0; br_start <= 1'b0;
            bw_saddr <= '0; br_saddr <= '0; bw_sbeats <= '0; br_sbeats <= '0;
            done <= 1'b0; err <= 1'b0; err_code <= '0;
        end else begin
            done     <= 1'b0;
            err      <= 1'b0;
            bw_start <= 1'b0;
            br_start <= 1'b0;

            // ---- shared read bookkeeping ----
            if (br_fire) rd_got <= rd_got + 24'd1;

            case (st)
            // --------------------------------------------------------
            S_IDLE: if (cmd_valid) begin
                chan_q <= cmd_is_bc ? 2'd0 : cmd_chan; saddr_q <= cmd_saddr;   // R3-8: a broadcast walks STATUS from channel 0
                len_q <= cmd_len; i16_q <= cmd_movy_i16;
                shift_q <= cmd_shift; shape_q <= cmd_shape;
                wbase_q <= cmd_wbase; beats_q <= cmd_beats;
                nowait_q <= cmd_nowait;
                fmask_q <= (cmd_fmask == 4'd0) ? 4'hF : cmd_fmask;
                res_row_q <= cmd_row;            // SR12: B17.2 RES start row
                xword_q   <= cmd_xword; bcast_q <= cmd_is_bc;   // SR12: B17.2 XWIN start word; R3-8: B17.3 broadcast
                rd_got <= '0;
                pack_acc <= '0; pack_idx <= '0;
                y_half <= 1'b0; y_val_valid <= 1'b0;
                s1_valid <= 1'b0; s2_valid <= 1'b0; s3_valid <= 1'b0;
                cfg_step <= '0; tmo <= '0; guard_cnt <= '0;
                poll_is_fence <= 1'b0;
                case (cmd_op)
                    MOP_MOVX:  st <= (cmd_len == 24'd0) ? S_DONE : X_SPTR;
                    MOP_MVGO:  st <= G_CFG;
                    MOP_MOVY:  st <= (cmd_len == 24'd0) ? S_DONE : Y_RESPTR;
                    MOP_FENCE: begin fence_chan <= 2'd0; st <= F_SCAN; end
                    default:   st <= S_DONE;
                endcase
            end

            // ========================================================
            // MOVX: scratch[saddr .. +len) int8 -> engine chan XWIN
            // ========================================================
            X_SPTR: if (wr_fire) st <= bcast_q ? X_DRAIN : X_XPTR;   // R3-8: a broadcast skips the XPTR write (B17.3)
            X_XPTR: if (wr_fire) st <= X_DRAIN;
            // XPTR must LAND before the XWIN burst pushes start: the two
            // leave seq_unit on DIFFERENT master ports (AXI-Lite vs m_axib)
            // and nothing orders them but this drain (C3).
            X_DRAIN: if (wr_idle) begin
                tmo <= '0;
                br_start  <= 1'b1;
                br_saddr  <= scrbaddr(saddr_q);
                br_sbeats <= len_q;
                bw_start  <= !bcast_q;           // R3-8: a broadcast's words go out on the x-push bus
                bw_saddr  <= mvbaddr(chan_q, MVB_XWIN + {18'd0, xword_q, 2'b00});
                bw_sbeats <= x_wwords;
`ifndef SYNTHESIS
                if ((32'({8'd0, len_q}) + 32'({16'd0, saddr_q})) > 32'(SCR_WORDS))
                    $error("seq_movers MOVX: scratch read window overflow (saddr %0d + len %0d)",
                           saddr_q, len_q);
                // SR12 (B17.2): the window starts at the XWIN start word
                if ((32'({8'd0, x_wwords}) + 32'({20'd0, xword_q}))
                        > 32'(XWIN_WORDS))
                    $error("seq_movers MOVX: XWIN window overflow (start word %0d + %0d words)",
                           xword_q, x_wwords);
`endif
                st  <= X_RUN;
            end

            X_RUN: begin
                if (br_fire) begin
                    if (pack_idx == 2'd3) pack_acc <= 32'd0;
                    else pack_acc <= ins_byte(pack_acc, pack_idx,
                                              m_axib_rdata[7:0]);
                    pack_idx <= pack_idx + 2'd1;
                end
                tmo <= tmo + 1'b1;
                if (&tmo) begin
                    err <= 1'b1; err_code <= E_MOVER_TMO; st <= S_IDLE;
                end else if ((rd_got == len_q) && (yf_cnt == 6'd0)
                             && !yf_push && !bw_fire) begin
                    st <= X_END;
                end
            end

            // every XWIN push must be COMMITTED before STATUS is read for
            // xfifo_ovfl: drain the burst write engine (all B collected).
            X_END: if (wr_idle && bw_idle && xp_done) begin   // R3-8: + the push leg's commit (XP_RT, busy)
                tmo <= '0;
                st  <= X_STAT;
            end
            X_STAT:  if (rd_fire) st <= X_STATW;
            X_STATW: if (rd_rsp_valid) begin
                if (rd_rsp_data[3]) begin         // xfifo_ovfl
                    err <= 1'b1; err_code <= E_XFIFO_OVF; st <= S_IDLE;
                end else if (bcast_q && (chan_q != 2'd3)) begin chan_q <= chan_q + 2'd1; st <= X_STAT; end else st <= S_DONE;   // R3-8: STATUS of all four
            end

            // ========================================================
            // MVGO: program the channel, ring the doorbell, wait done
            // (S9: entirely unchanged, AXI-Lite as shipped)
            // ========================================================
            G_CFG: if (wr_fire) begin
                cfg_step <= cfg_step + 3'd1;
                if (cfg_step == 3'd3) st <= G_DOOR;
            end
            G_DOOR:  if (wr_fire) st <= G_DRAIN;
            G_DRAIN: if (wr_idle) begin
                if (nowait_q) begin
                    chan_pend[chan_q] <= 1'b1;
                    st <= S_DONE;
                end else begin
                    guard_cnt <= '0;
                    st <= G_GUARD;
                end
            end
            // C2: never poll before the doorbell has certainly propagated.
            G_GUARD: begin
                guard_cnt <= guard_cnt + 32'd1;
                if (guard_cnt == 32'(MVGO_GUARD - 1)) begin
                    tmo <= '0;
                    st  <= G_POLL;
                end
            end
            G_POLL: begin
                tmo <= tmo + 1'b1;
                if (&tmo) begin
                    err <= 1'b1; err_code <= E_MVGO_TMO; st <= S_IDLE;
                end else if (rd_fire) st <= G_POLLW;
            end
            G_POLLW: if (rd_rsp_valid) begin
                if (rd_rsp_data[2]) begin                   // err_rresp
                    err <= 1'b1; err_code <= E_MVGO_ENG; st <= S_IDLE;
                end else if (rd_rsp_data[1] && !rd_rsp_data[0]) begin
                    chan_pend[chan_q] <= 1'b0;
                    st <= poll_is_fence ? F_SCAN : S_DONE;
                end else st <= G_POLL;
            end

            // ========================================================
            // MOVY: engine RES rows -> dequant -> scratch
            // ========================================================
            Y_RESPTR: if (wr_fire) st <= Y_SPTR;
            Y_SPTR:   if (wr_fire) st <= Y_DRAIN;
            // decode the (constant) dequant shift ONCE, exactly as deq did:
            //   sh >= 0 : right shift by mm=min(sh,63), round add 1<<(mm-1)
            //   sh <  0 : exact left shift by mm=min(-sh,40), no add
            Y_DRAIN:  if (wr_idle) begin
                logic signed [31:0] sh;
                logic        [5:0]  mm;
                sh = shift_q;
                if (sh >= 32'sd0) mm = (sh > 32'sd63) ? 6'd63 : sh[5:0];
                else              mm = ((-sh) > 32'sd40) ? 6'd40 : 6'((-sh));
                dq_left <= (sh < 32'sd0);
                dq_m    <= mm;
                dq_add  <= (sh >= 32'sd0)
                           ? ((mm == 6'd0) ? 64'd0 : (64'd1 << (mm - 6'd1)))
                           : 64'd0;
                s1_valid <= 1'b0; s2_valid <= 1'b0; s3_valid <= 1'b0;
                tmo <= '0;
                br_start  <= 1'b1;
                br_saddr  <= mvbaddr(chan_q, MVB_RES + {18'd0, res_row_q, 2'b00});
                br_sbeats <= len_q;
                bw_start  <= 1'b1;
                bw_saddr  <= scrbaddr(saddr_q);
                bw_sbeats <= y_wwords;
`ifndef SYNTHESIS
                if ((32'({8'd0, len_q}) + 32'({20'd0, res_row_q})) > 32'(RES_WORDS))
                    $error("seq_movers MOVY: RES window overflow (row %0d + len %0d)",
                           res_row_q, len_q);
                if ((32'({8'd0, y_wwords}) + 32'({16'd0, saddr_q})) > 32'(SCR_WORDS))
                    $error("seq_movers MOVY: scratch write window overflow (saddr %0d + %0d)",
                           saddr_q, y_wwords);
`endif
                st  <= Y_RUN;
            end

            Y_RUN: begin
                // --- write side drains y_val (S4) over 1 (i16) / 2 (pairs)
                //     writes; UNCHANGED from the pre-pipeline design ---
                if (bw_fire) begin
                    if (i16_q || y_half) y_val_valid <= 1'b0;
                    else                 y_half      <= 1'b1;
                end
                // --- dequant pipeline advance (frozen while y_val is busy
                //     and not draining this cycle).  The pipe_adv block is
                //     LAST so, on a same-cycle drain+load, y_val takes the
                //     next element and its valid/half win over the drain. ---
                if (pipe_adv) begin
                    s1_valid <= launch;                 // S1 <= popped row
                    s1_v64   <= dq_v64;
                    s1_mag   <= dq_av + dq_add;
                    s1_sgn   <= dq_v64[63];
                    s2_valid <= s1_valid;               // S2 <= S1 (shift)
                    s2_rsh   <= s1_mag >> dq_m;
                    s2_lsh   <= s1_v64 <<< dq_m;
                    s2_sgn   <= s1_sgn;
                    s3_valid <= s2_valid;               // S3 <= S2 (sign/sel)
                    s3_t     <= dq_t;
                    y_val       <= clip_out(s3_t, i16_q);   // S4 <= S3 (clip)
                    y_val_valid <= s3_valid;
                    y_half      <= 1'b0;
                end
                tmo <= tmo + 1'b1;
                if (&tmo) begin
                    err <= 1'b1; err_code <= E_MOVER_TMO; st <= S_IDLE;
                end else if ((rd_got == len_q) && (yf_cnt == 6'd0)
                             && !yf_push && !yf_pop && !y_val_valid
                             && !s1_valid && !s2_valid && !s3_valid) begin
                    st <= Y_END;
                end
            end

            // the scratch writes must be COMMITTED before the record retires
            // — the next record's CSR traffic reaches layer_chan on the OTHER
            // master port and would otherwise race them (C3).
            Y_END: if (wr_idle && bw_idle) st <= S_DONE;

            // ========================================================
            // FENCE: drain every channel a no-wait MVGO left running that
            // the FENCE's mask names (SR3, B17.1; mask 0 = all four)
            // ========================================================
            // FENCE also drains the AXI-Lite write pipe: a run of CSRWRs
            // is fire-and-forget, and "drain all movers/engines" must mean
            // the CSR side too.
            F_SCAN: if (wr_idle) begin
                if (chan_pend[fence_chan] && fmask_q[fence_chan]) begin
                    chan_q        <= fence_chan;
                    poll_is_fence <= 1'b1;
                    tmo           <= '0;
                    st            <= G_POLL;     // guard already elapsed
                end else if (fence_chan == 2'd3) begin
                    st <= S_DONE;
                end else begin
                    fence_chan <= fence_chan + 2'd1;
                end
            end

            // ========================================================
            S_DONE: begin
                done <= 1'b1;
                st   <= S_IDLE;
            end
            default: st <= S_IDLE;
            endcase

            // any m_axib SLVERR/DECERR is fatal for the operation in flight.
            // Placed AFTER the case so it wins the state assignment.
            if (axib_err && (st != S_IDLE)) begin
                err      <= 1'b1;
                err_code <= E_AXI;
                st       <= S_IDLE;
            end
        end
    end

    // ------------------------------------------------------------------
    // AXI-Lite request generation (setup / doorbell / poll only — every
    // bulk data beat now leaves on m_axib)
    // ------------------------------------------------------------------
    logic [31:0] mvgo_cfg_data;
    logic [11:0] mvgo_cfg_off;
    always_comb begin
        case (cfg_step)
            3'd0: begin mvgo_cfg_off  = MV_WBLO;
                        mvgo_cfg_data = wbase_q[31:0]; end
            3'd1: begin mvgo_cfg_off  = MV_WBHI;
                        mvgo_cfg_data = {30'd0, wbase_q[33:32]}; end
            3'd2: begin mvgo_cfg_off  = MV_BEATS;
                        mvgo_cfg_data = {8'd0, beats_q}; end
            default: begin mvgo_cfg_off  = MV_SHAPE;
                           mvgo_cfg_data = shape_q; end
        endcase
    end

    always_comb begin
        wr_valid = 1'b0;
        wr_addr  = 32'd0;
        wr_data  = 32'd0;
        rd_valid = 1'b0;
        rd_addr  = 32'd0;
        case (st)
            X_SPTR: begin wr_valid = 1'b1; wr_addr = laddr(L_SPTR);
                          wr_data  = {16'd0, saddr_q}; end
            X_XPTR: begin wr_valid = 1'b1; wr_addr = mvaddr(chan_q, MV_XPTR);
                          wr_data  = 32'd0; end
            X_STAT: begin rd_valid = 1'b1;
                          rd_addr  = mvaddr(chan_q, MV_STATUS); end
            G_CFG:  begin wr_valid = 1'b1;
                          wr_addr  = mvaddr(chan_q, mvgo_cfg_off);
                          wr_data  = mvgo_cfg_data; end
            G_DOOR: begin wr_valid = 1'b1; wr_addr = mvaddr(chan_q, MV_CTRL);
                          wr_data  = 32'd1; end
            G_POLL: begin rd_valid = 1'b1;
                          rd_addr  = mvaddr(chan_q, MV_STATUS); end
            Y_RESPTR: begin wr_valid = 1'b1;
                            wr_addr  = mvaddr(chan_q, MV_RESPTR);
                            wr_data  = {20'd0, res_row_q}; end
            Y_SPTR: begin wr_valid = 1'b1; wr_addr = laddr(L_SPTR);
                          wr_data  = {16'd0, saddr_q}; end
            default: ;
        endcase
    end

    assign cmd_ready = (st == S_IDLE);
    assign busy      = (st != S_IDLE);

    // WBASE is 40 bits in the ISA record; matvec_chan only implements
    // [33:0] (its m_axi is 34-bit), so the top 6 bits are decoded and
    // dropped here rather than silently aliasing.
    /* verilator lint_off UNUSEDSIGNAL */
    wire  [5:0] unused_wbase_hi = wbase_q[39:34];
    wire        unused_axib_id  = m_axib_bid | m_axib_rid;
    // only STATUS bits [3:0] are consumed now that the RES/SWIN data
    // streams left the AXI-Lite read channel
    wire [27:0] unused_rsp_hi   = rd_rsp_data[31:4];
    /* verilator lint_on UNUSEDSIGNAL */


    // ==================================================================
    // R3-8 (docs/SEQ_ISA.md v2.3 B17.3; spec §1.3 (a)): THE MOVX BROADCAST
    // over the direct x-push bus.  Appended below every cited line (zero
    // drift); the FSM reaches it through one-line edits: the latch
    // (bcast_q, chan_q from 0) in S_IDLE, X_SPTR -> X_DRAIN (no XPTR
    // write), X_DRAIN's bw_start, yf_pop, X_END's xp_done and X_STATW's walk
    // over the four STATUS registers.
    //
    // A broadcast MOVX (cmd_bcast with MOP_MOVX; seq_unit sets it for
    // flags[7:4] = 0xF) runs the unicast MOVX states with three differences:
    //   1. NO XPTR write (X_SPTR goes straight to X_DRAIN): the push carries
    //      its word index, and B17.3 leaves all four XPTRs unchanged;
    //   2. the XWIN words go out on the PUSH BUS, not the m_axib burst: the
    //      same packed x_word the unicast pushes into the elastic buffer
    //      (yf), popped here by xp_fire instead of by a W beat; its index is
    //      the start word + the word count (xp_widx).  A word is pushed to
    //      all four ports in the SAME cycle, and only when all four room
    //      inputs are high (LOCKSTEP) — a channel without room stalls the
    //      other three, the elastic buffer fills and RREADY stalls the one
    //      scratch read (which is untouched: one read, four writes);
    //   3. the retire waits (xp_done): XP_RT cycles after the last push
    //      leaves the output flop, THEN all four busy inputs must be low (a
    //      busy sampled earlier can be a stale low while the last word is
    //      still in the output flop, the BD net or the channel's input
    //      register), and then STATUS of ALL FOUR channels is read (X_STAT /
    //      X_STATW from channel 0: any xfifo_ovfl faults E_XFIFO_OVF — the
    //      unicast's error surface, x4).
    // The sim-only XWIN window $error in X_DRAIN covers the broadcast (it
    // tests xword_q + x_wwords, whatever carries the words).
    //
    // Per channel c: xpush_valid[c], xpush_idx[12c +: 12], xpush_data[32c
    // +: 32] from FLOPS (xp_v_q / xp_i_q / xp_d_q, one copy per channel,
    // KEEP so synthesis cannot merge them: each is the start of a
    // point-to-point net to its own mvchan, mvchan_0's across SLR1 -> SLR0),
    // and xpush_room[c] / xpush_busy[c] through ONE input flop each
    // (xp_room_q / xp_busy_q: mvchan_0's two return nets cross SLR0 ->
    // SLR1 and end here).  The register stages are the ONE parameter set
    // rtl/matvec_chan.sv also declares (its R3 block derives XP_INFLIGHT
    // from the same two numbers; the chip TB checks them equal):
    //   XP_FWD_STAGES = 2   this output flop, matvec_chan's input register
    //   XP_RET_STAGES = 2   matvec_chan's room/busy flop, this input flop
    //   XP_RT = XP_FWD_STAGES + XP_RET_STAGES = 4
    // XP_RT counts from the cycle after the last word sat in the output flop;
    // the busy input read then describes the channel two cycles earlier,
    // which is after the last word reached its input register, so busy low
    // => every pushed word is in its XWIN FIFO (the burst leg's commit
    // contract, rtl/matvec_chan.sv's header, restated for the push leg).
    // BM1: a broadcast is one mover job with mv_op 0; nothing here changes
    // the counters (B17.3 COUNTERS).
    // ==================================================================
    localparam int XP_FWD_STAGES = 2;
    localparam int XP_RET_STAGES = 2;
    localparam int XP_RT         = XP_FWD_STAGES + XP_RET_STAGES;

    (* keep = "true" *) logic [3:0]  xp_room_q, xp_busy_q;   // input flops
    (* keep = "true" *) logic [3:0]  xp_v_q;                 // output flops
    (* keep = "true" *) logic [11:0] xp_i_q [4];
    (* keep = "true" *) logic [31:0] xp_d_q [4];
    logic [11:0] xp_widx;
    logic  [2:0] xp_rt;

    assign xp_fire = (st == X_RUN) && bcast_q && (yf_cnt != 6'd0)
                     && (&xp_room_q);
    assign xp_done = !bcast_q
                     || ((xp_v_q == 4'd0) && (xp_rt == 3'd0) && (xp_busy_q == 4'd0));

    always_ff @(posedge clk) begin
        if (!rstn) begin
            xp_room_q <= 4'd0; xp_busy_q <= 4'd0; xp_v_q <= 4'd0;
            xp_widx <= '0; xp_rt <= '0;
        end else begin
            xp_room_q <= xpush_room;
            xp_busy_q <= xpush_busy;
            xp_v_q    <= {4{xp_fire}};
            if (st == X_DRAIN)  xp_widx <= xword_q;
            else if (xp_fire)   xp_widx <= xp_widx + 12'd1;
            if (xp_v_q != 4'd0) xp_rt <= 3'(XP_RT);
            else if (xp_rt != 3'd0) xp_rt <= xp_rt - 3'd1;
        end
    end

    for (genvar c = 0; c < 4; c++) begin : g_xp
        always_ff @(posedge clk)
            if (xp_fire) begin
                xp_i_q[c] <= xp_widx;
                xp_d_q[c] <= yf_dout;
            end
        assign xpush_idx[12*c +: 12]  = xp_i_q[c];
        assign xpush_data[32*c +: 32] = xp_d_q[c];
    end
    assign xpush_valid = xp_v_q;

endmodule

`default_nettype wire
