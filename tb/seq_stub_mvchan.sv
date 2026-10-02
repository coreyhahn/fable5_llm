// seq_stub_mvchan: a BEHAVIOURAL stand-in for rtl/matvec_chan.sv's AXI-Lite
// CSR map, for the seq_unit unit TB.  It does NOT model W4A8 arithmetic
// (that is ref/w4a8_ref.py + tb_matvec / tb_matvec_chan); it models every
// property of the shipped slave the movers depend on:
//
//   * the register map and byte offsets (rtl/matvec_chan.sv header)
//   * RES_DATA returns the port-B output of a READ_LATENCY_B=2 BRAM
//     addressed by res_ptr, and increments res_ptr in the same cycle — so
//     RES_DATA reads accepted less than 3 cycles apart return STALE data,
//     exactly as on silicon.  This is what verifies seq_movers' C1 pacing.
//   * STATUS.done is STICKY UNTIL THE NEXT START and only drops ENG_LAG
//     cycles after the doorbell (modelling the toggle+2FF doorbell CDC and
//     the busy 2FF back).  A mover that polls done straight after the
//     doorbell will see the PREVIOUS run's done and finish early — this is
//     what verifies seq_movers' C2 guard.
//   * XWIN pushes at xptr and increments it; XPTR writes reset the pointer.
//   * STATUS bit3 xfifo_ovfl is modelled as constant 0: the AXI-Lite write
//     rate (>=2 cycles/word) can never outrun matvec_chan's ui_clk drain
//     (1 word/cycle at 300 MHz), so the real bit cannot set either.  MOVX
//     checks it anyway; this stub verifies that the check reads bit 3 of
//     the right register.
//
// Result contents are a deterministic function the python golden mirrors:
//     res[i] = (i * 32'h9E3779B1) ^ shape ^ wbase_lo ^ xsum
// latched into the result array at the doorbell, where xsum is the 32-bit
// sum of every XWIN word pushed since the last XPTR write OR the last
// doorbell (whichever came later — the doorbell reset is what makes the
// AXI-Lite and the burst MOVX paths produce the SAME seed, because a burst
// MOVX has no XPTR write to reset on: rtl/matvec_chan.sv carries the x
// index in the address and leaves xptr untouched).
//
// RUNG 3 / S5 — s_axib burst window (mirrors rtl/matvec_chan.sv's shim):
//   READ  0x0000-0x3FFF : RES row r at byte 4r, r = araddr[13:2], all 4096
//                         rows, start row address-carried (S12).  res_ptr is
//                         NOT touched.  A 2-cycle bubble at burst start
//                         models READ_LATENCY_B = 2; beats then stream at
//                         1 word/cycle.
//   WRITE 0x4000-0x6FFF : XWIN word w at byte 4w, 3072 words (K <= 12288,
//                         matvec_engine MAX_NG = 96).  0x7000-0x7FFF is
//                         NOT the window, exactly as in rtl/matvec_chan.sv
//                         (the decode is `rtl/matvec_chan.sv:587-588`).
//                         Pushes exactly like an AXI-Lite XWIN write
//                         (xsum += data) but leaves xptr untouched (the
//                         index is address-carried).
//   anything else       : SLVERR, with the full beat count still
//                         returned / consumed (never a silent drop).
//
// SR12 — the R2 banks (docs/SEQ_ISA.md B17.2).  x_mem and RES are halved
// into banks by ADDRESS alone, and this stub is already address-carried on
// both windows, so it needs no bank state of its own:
//   * RES start row (MOVY target[15:4]): the burst READ starts at rb_addr =
//     the row from araddr[13:2], and every RES word is a function of its
//     ROW, so a MOVY from row 2048 returns rows 2048.. — a mover that
//     dropped the start row moves every value the golden checks.
//   * XWIN start word (MOVX target[11:0]): xsum is address-blind, so the
//     WORD is checked by tb/tb_seq_unit.sv beat by beat against
//     <prefix>.xwa (the golden's window list), not here.
//   * SHAPE bits 29 (XBANK) / 30 (RBANK): SHAPE stays OPAQUE — stored whole
//     and XOR'd into the result seed, so the bits' passage through the
//     SHAPE write is checked (the .wtr data AND the seed), while what they
//     MEAN (x from line 48, rows at 2048) is the engine's, proved by
//     tb/tb_matvec.sv and tb/tb_matvec_chan.sv.  Keeping SHAPE undecoded is
//     also what evidence/qwen9b/g3/isa_bits.py's SHAPE round trip requires
//     of this file.
//
// R-b (task R5): the stub's XWIN pointer and burst decode match
// rtl/matvec_chan.sv's real map.  The sibling bound check in
// tb/tb_seq_unit.sv was widened in the same change.
// G3.3: that map is now 3072 words / 0x4000-0x6FFF and xptr is 12 bits
// (spec 4.5 W5).  The stub is one of the SIX places the mvchan register
// map is written down independently; the others are rtl/matvec_chan.sv,
// sw/hwmap.py, ref/seq_format.py, ref/seq_model.py and tb/tb_matvec_chan.sv.

`timescale 1ns/1ps
`default_nettype none

module seq_stub_mvchan #(
    parameter logic [3:0] CHAN_ID = 4'd0,
    parameter int ENG_CYC = 40,        // doorbell -> done
    parameter int ENG_LAG = 6          // doorbell -> done drops (CDC model)
) (
    input  wire         aclk,
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

    // ---- RUNG3 S5: AXI4 burst window (32b data / 16b addr, ID width 1) ----
    input  wire [0:0]   s_axib_awid,
    input  wire [15:0]  s_axib_awaddr,
    input  wire [7:0]   s_axib_awlen,
    input  wire [2:0]   s_axib_awsize,
    input  wire [1:0]   s_axib_awburst,
    input  wire         s_axib_awvalid,
    output logic        s_axib_awready,
    input  wire [31:0]  s_axib_wdata,
    input  wire [3:0]   s_axib_wstrb,
    input  wire         s_axib_wlast,
    input  wire         s_axib_wvalid,
    output logic        s_axib_wready,
    output logic [0:0]  s_axib_bid,
    output logic [1:0]  s_axib_bresp,
    output logic        s_axib_bvalid,
    input  wire         s_axib_bready,
    input  wire [0:0]   s_axib_arid,
    input  wire [15:0]  s_axib_araddr,
    input  wire [7:0]   s_axib_arlen,
    input  wire [2:0]   s_axib_arsize,
    input  wire [1:0]   s_axib_arburst,
    input  wire         s_axib_arvalid,
    output logic        s_axib_arready,
    output logic [0:0]  s_axib_rid,
    output logic [31:0] s_axib_rdata,
    output logic [1:0]  s_axib_rresp,
    output logic        s_axib_rlast,
    output logic        s_axib_rvalid,
    input  wire         s_axib_rready,

    output logic [31:0] n_run,                // completed engine runs
    input wire xpush_valid, input wire [11:0] xpush_idx, input wire [31:0] xpush_data, output logic xpush_room, output logic xpush_busy, input wire xp_hold, output logic [31:0] n_push);  // R3-8: the x-push port (B17.3), see the end

    // results are generated, not stored: res[i] = (i*0x9E3779B1) ^ res_seed
    logic [31:0] res_seed;
    logic [31:0] res_q1, res_q2;              // READ_LATENCY_B = 2
    logic [11:0] res_ptr;
    logic [11:0] xptr;
    logic [31:0] xsum;
    logic [33:0] wbase;
    logic [31:0] wbeats, shape;
    logic        busy, done, err_rresp, xovfl;
    logic [31:0] eng_left, runs;

    logic        aw_got, w_got;
    logic  [9:0] awaddr_q;
    logic [31:0] wdata_q;
    /* verilator lint_off UNUSEDSIGNAL */
    wire  [1:0]  unused_lsb = s_axil_awaddr[1:0] | s_axil_araddr[1:0];
    wire  [3:0]  unused_wstrb = s_axil_wstrb;
    wire  [31:0] unused_wbeats = wbeats;
    wire         unused_axib = ^{s_axib_awsize, s_axib_awburst, s_axib_awlen,
                                 s_axib_arsize, s_axib_arburst, s_axib_wstrb,
                                 s_axib_awaddr[11:0], s_axib_araddr[1:0]};
    /* verilator lint_on UNUSEDSIGNAL */

    // ---- S5 burst window state (see the header) ----
    localparam logic [1:0] RB_IDLE = 2'd0, RB_WAIT = 2'd1, RB_DATA = 2'd2;
    localparam logic [1:0] WB_IDLE = 2'd0, WB_DATA = 2'd1, WB_RESP = 2'd2;

    logic  [1:0] rb_st, wb_st;
    logic [11:0] rb_addr;
    logic  [8:0] rb_left;
    logic  [1:0] rb_wait;
    logic        rb_win, wb_win;

    assign s_axib_arready = (rb_st == RB_IDLE);
    assign s_axib_rvalid  = (rb_st == RB_DATA);
    assign s_axib_rdata   = rb_win ? ((32'd2654435761 * {20'd0, rb_addr})
                                      ^ res_seed)
                                   : 32'hDEAD_C0DE;
    assign s_axib_rresp   = rb_win ? 2'b00 : 2'b10;      // SLVERR out of window
    assign s_axib_rlast   = (rb_left == 9'd1);

    assign s_axib_awready = (wb_st == WB_IDLE);
    assign s_axib_wready  = (wb_st == WB_DATA);

    assign s_axil_awready = !aw_got && !s_axil_bvalid;
    assign s_axil_wready  = !w_got  && !s_axil_bvalid;
    assign s_axil_arready = !s_axil_rvalid;
    assign n_run = runs;

    always_ff @(posedge aclk) begin
        res_q1 <= (32'd2654435761 * {20'd0, res_ptr}) ^ res_seed;
        res_q2 <= res_q1;
    end

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            aw_got <= 1'b0; w_got <= 1'b0;
            s_axil_bvalid <= 1'b0; s_axil_bresp <= 2'b00;
            s_axil_rvalid <= 1'b0; s_axil_rresp <= 2'b00; s_axil_rdata <= '0;
            res_ptr <= '0; xptr <= '0; xsum <= '0;
            wbase <= '0; wbeats <= '0; shape <= '0;
            busy <= 1'b0; done <= 1'b0; err_rresp <= 1'b0; xovfl <= 1'b0;
            eng_left <= '0; runs <= '0; res_seed <= '0;
            rb_st <= RB_IDLE; wb_st <= WB_IDLE;
            rb_addr <= '0; rb_left <= '0; rb_wait <= '0;
            rb_win <= 1'b0; wb_win <= 1'b0;
            s_axib_bvalid <= 1'b0; s_axib_bresp <= 2'b00;
            s_axib_bid <= 1'b0; s_axib_rid <= 1'b0;
        end else begin
            if (xpush_valid) xsum <= xsum + xpush_data;   // R3-8: a push (B17.3); ---- engine ----
            if (busy) begin
                // done only DROPS after the doorbell CDC has propagated
                if (eng_left == 32'(ENG_CYC - ENG_LAG)) done <= 1'b0;
                if (eng_left == 32'd1) begin
                    busy <= 1'b0;
                    done <= 1'b1;
                    runs <= runs + 32'd1;
                end
                eng_left <= eng_left - 32'd1;
            end

            // ---- writes ----
            if (s_axil_awvalid && s_axil_awready) begin
                aw_got <= 1'b1; awaddr_q <= s_axil_awaddr[11:2];
            end
            if (s_axil_wvalid && s_axil_wready) begin
                w_got <= 1'b1; wdata_q <= s_axil_wdata;
            end
            if (aw_got && w_got && !s_axil_bvalid) begin
                case (awaddr_q)
                    10'h000: if (wdata_q[0]) begin              // CTRL doorbell
                        if (busy) $fatal(1, "seq_stub_mvchan: doorbell while busy");
                        busy <= 1'b1;
                        eng_left <= 32'(ENG_CYC);
                        res_seed <= shape ^ wbase[31:0] ^ xsum;
                        xsum <= '0;    // the engine consumed this x window
                    end
                    10'h002: wbase[31:0]  <= {wdata_q[31:6], 6'd0};
                    10'h003: wbase[33:32] <= wdata_q[1:0];
                    10'h004: wbeats <= wdata_q;
                    10'h005: shape  <= wdata_q;
                    10'h009: begin                              // XWIN
                        xsum <= xsum + wdata_q;
                        xptr <= xptr + 12'd1;
                    end
                    10'h00A: begin xptr <= wdata_q[11:0]; xsum <= '0; end
                    10'h00B: res_ptr <= wdata_q[11:0];
                    default: ;
                endcase
                s_axil_bvalid <= 1'b1; s_axil_bresp <= 2'b00;
                aw_got <= 1'b0; w_got <= 1'b0;
            end
            if (s_axil_bvalid && s_axil_bready) s_axil_bvalid <= 1'b0;

            // ---- reads ----
            if (s_axil_arvalid && s_axil_arready) begin
                s_axil_rvalid <= 1'b1; s_axil_rresp <= 2'b00;
                case (s_axil_araddr[11:2])
                    10'h001: s_axil_rdata <= {28'd0, xovfl, err_rresp,
                                              done, busy};
                    10'h002: s_axil_rdata <= wbase[31:0];
                    10'h003: s_axil_rdata <= {30'd0, wbase[33:32]};
                    10'h004: s_axil_rdata <= wbeats;
                    10'h005: s_axil_rdata <= shape;
                    10'h00A: s_axil_rdata <= {20'd0, xptr};
                    10'h00B: s_axil_rdata <= {20'd0, res_ptr};
                    10'h00C: begin                              // RES_DATA
                        s_axil_rdata <= res_q2;                 // 2-cycle BRAM
                        res_ptr <= res_ptr + 12'd1;
                    end
                    10'h00D: s_axil_rdata <= {28'hFAB1C4A, CHAN_ID};
                    default: s_axil_rdata <= 32'hDEAD_C0DE;
                endcase
            end else if (s_axil_rvalid && s_axil_rready)
                s_axil_rvalid <= 1'b0;

            // ---- S5 burst READ window ----
            case (rb_st)
                RB_IDLE: if (s_axib_arvalid) begin
                    s_axib_rid <= s_axib_arid;
                    rb_win  <= (s_axib_araddr[15:14] == 2'b00);
                    rb_addr <= s_axib_araddr[13:2];        // S12: full 12 bits
                    rb_left <= {1'b0, s_axib_arlen} + 9'd1;
                    rb_wait <= 2'd2;                       // READ_LATENCY_B=2
                    rb_st   <= RB_WAIT;
                end
                RB_WAIT: if (rb_wait == 2'd0) rb_st <= RB_DATA;
                         else rb_wait <= rb_wait - 2'd1;
                RB_DATA: if (s_axib_rready) begin
                    rb_addr <= rb_addr + 12'd1;
                    rb_left <= rb_left - 9'd1;
                    if (rb_left == 9'd1) rb_st <= RB_IDLE;
                end
                default: rb_st <= RB_IDLE;
            endcase

            // ---- S5 burst WRITE window (XWIN push) ----
            case (wb_st)
                WB_IDLE: if (s_axib_awvalid) begin
                    s_axib_bid <= s_axib_awid;
                    wb_win     <= (s_axib_awaddr[15:14] == 2'b01)
                                  && (s_axib_awaddr[13:12] != 2'b11);
                    wb_st      <= WB_DATA;
                end
                WB_DATA: if (s_axib_wvalid) begin
                    if (wb_win) xsum <= xsum + s_axib_wdata;
                    if (s_axib_wlast) begin
                        s_axib_bvalid <= 1'b1;
                        s_axib_bresp  <= wb_win ? 2'b00 : 2'b10;
                        wb_st         <= WB_RESP;
                    end
                end
                WB_RESP: if (s_axib_bready) begin
                    s_axib_bvalid <= 1'b0;
                    wb_st         <= WB_IDLE;
                end
                default: wb_st <= WB_IDLE;
            endcase
        end
    end

    // A burst XWIN push must never race an AXI-Lite xsum update (doorbell /
    // XWIN / XPTR): the stub would silently pick one and diverge from the
    // python golden.  The movers never do both, so make it loud.
    /* verilator lint_off BLKSEQ */
    always @(posedge aclk) if (aresetn) begin
        if ((wb_st == WB_DATA) && s_axib_wvalid && wb_win
            && aw_got && w_got && !s_axil_bvalid
            && ((awaddr_q == 10'h000) || (awaddr_q == 10'h009)
                || (awaddr_q == 10'h00A)))
            $fatal(1, "seq_stub_mvchan: burst XWIN push collides with an AXI-Lite xsum update");
    end
    /* verilator lint_on BLKSEQ */


    // ==================================================================
    // R3-8 (docs/SEQ_ISA.md v2.3 B17.3) — the x-push port, the stub's side
    // of rtl/matvec_chan.sv's push leg.  Appended below every cited line;
    // the ports ride on the `);` line and the xsum update on the first line
    // of the regfile block (line 206).
    //   * a push (xpush_valid, from seq_unit's output flops) is taken in the
    //     cycle it arrives: xsum += word, exactly as an XWIN write, and
    //     xptr is NOT touched (the push carries its word index; B17.3 XPTR);
    //   * xpush_room is a FLOP of !xp_hold (xp_hold: the TB's +xp_lowroom
    //     lockstep case), xpush_busy a flop of the arriving valid — the
    //     real channel's input register, one stage;
    //   * the return path is two flops (this room flop + seq_unit's input
    //     flop), so after room drops at most TWO pushes may still arrive
    //     (those fired before seq_unit saw the drop).  A third is a
    //     lockstep / back-pressure violation and fails here;
    //   * a push beyond the 3072-word XWIN, or coinciding with an AXI-Lite
    //     xsum update (doorbell / XWIN / XPTR) or a burst XWIN beat — the
    //     single-threaded mover never does either, and the stub would
    //     silently keep one of the two — fails.
    // ==================================================================
    logic [1:0]  xp_lo_age;
    logic [31:0] xp_n;
    assign n_push = xp_n;
    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            xpush_room <= 1'b0; xpush_busy <= 1'b0;
            xp_lo_age <= 2'd0; xp_n <= '0;
        end else begin
            xpush_room <= !xp_hold;
            xpush_busy <= xpush_valid;
            if (xpush_room) xp_lo_age <= 2'd0;
            else if (xp_lo_age != 2'd3) xp_lo_age <= xp_lo_age + 2'd1;
            if (xpush_valid) xp_n <= xp_n + 32'd1;
        end
    end

    always @(posedge aclk) if (aresetn && xpush_valid) begin
        if (!xpush_room && (xp_lo_age >= 2'd2))
            $fatal(1, "seq_stub_mvchan %0d: x-push word %0d arrived %0d cycles after room dropped (the return path is 2 flops)",
                   CHAN_ID, xpush_idx, xp_lo_age);
        if (32'(xpush_idx) >= 32'd3072)
            $fatal(1, "seq_stub_mvchan %0d: x-push word %0d outside the 3072-word XWIN",
                   CHAN_ID, xpush_idx);
        if (aw_got && w_got && !s_axil_bvalid
            && ((awaddr_q == 10'h000) || (awaddr_q == 10'h009)
                || (awaddr_q == 10'h00A)))
            $fatal(1, "seq_stub_mvchan %0d: x-push collides with an AXI-Lite xsum update",
                   CHAN_ID);
        if ((wb_st == WB_DATA) && s_axib_wvalid && wb_win)
            $fatal(1, "seq_stub_mvchan %0d: x-push collides with a burst XWIN beat",
                   CHAN_ID);
    end

endmodule

`default_nettype wire
