// seq_stub_layer: a BEHAVIOURAL stand-in for rtl/layer_chan.sv's AXI-Lite
// CSR map, for the seq_unit unit TB.  It is NOT a model of the layer
// arithmetic — the golden for that is ref/layer_fixed.py and the existing
// tb_layer_chan integration TB.  What it DOES model, exactly, is every
// property of the real slave the sequencer's correctness depends on:
//
//   * the register map and byte offsets (rtl/layer_chan.sv header)
//   * SWIN/SPTR: write scratch[sptr]/sptr++, read scratch[sptr]/sptr++,
//     INCLUDING the 1-cycle registered-BRAM read latency (sa_q) and the
//     single-outstanding arready = !rvalid handshake, so a mover that reads
//     the scratch window too fast gets the same stale data it would on
//     silicon
//   * CMD is DROPPED while busy (the real RTL does this silently)
//   * cmd_cnt increments when a command retires; err_op is cleared at
//     dispatch and set for an unknown opcode; STATUS packs them exactly
//   * EOUT is updated when an ALU DYNQ8 (sub-op 0) retires
//
// and, mirroring agent C's LANDED XRF interface (rtl/layer_chan.sv,
// commit 9785771 / ISA v1.3):
//
//   * 0x38 XRFI RW {29'b0, idx[2:0]}, 0x3C XRFD RW XRF[XRFI] raw18
//   * XRF[1] or XRF[2] is updated when an ALU DYNQ16 (sub-op 12) retires,
//     selected by arg2[0]; XRF[2] when the ALU op-8 k_a probe (sub-op 8
//     with cfg_p0[6] = arg2[6]) retires; XRF[0] mirrors EOUT on DYNQ8
//
// DIVERGENCE RISK: the values this stub produces for EOUT / XRF / AMAXI are
// deterministic pseudo-random functions of the retire index (below), NOT
// the real arithmetic.  That is deliberate — it makes the XRF plumbing,
// the indirection algebra and the OUT FIFO checkable bit-exactly against
// ref-side python without pulling the whole layer datapath into a unit TB.
// The real values are covered by the full-chip SEQ-driven sim (ladder
// step 3), which replays the SAME streams against the real layer_chan.
//
//   eout(n)  = (7*n + 3) & 0xF
//   k(n)     = ((5*n + 1) % 33) - 16        (signed, -16..16)
//   ka(n)    = ((3*n + 7) % 67) - 33        (signed, -33..33; op-8 probe)
//   amax(n)  = (n * 32'h9E3779B1) & 0x3FFFF
//   busy(n)  = CMD_CYC_MIN + (n % CMD_CYC_MOD) cycles
//
// where n is the number of commands that had already retired.

`timescale 1ns/1ps
`default_nettype none

module seq_stub_layer #(
    parameter int CMD_CYC_MIN = 6,
    parameter int CMD_CYC_MOD = 13,
    parameter logic [11:0] XRFI_OFF = 12'h038,   // asserted below
    parameter logic [11:0] XRFD_OFF = 12'h03C
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

    // ---- RUNG3 S6: AXI4 burst window (32b data / 16b addr, ID width 1) ----
    // scratch word w at byte 4w, w = addr[15:2], w = 0..16383 — the WHOLE
    // 64 KiB aperture is the window, so there is no out-of-window case here.
    // READ consumes the same registered BRAM output the SWIN read does;
    // WRITE is the 4th leg on the scratch write mux.  Both are gated on
    // !busy: an access while busy answers SLVERR (S6/R8 — never a silent
    // drop), with the full beat count still returned / consumed.
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

    output logic [31:0] n_cmd,                // retired commands (TB probe)

    // the OPTIONAL direct XRF sideband (seq_unit USE_XRF_SIDEBAND=1): the
    // same values this stub latches into EOUT / XRF, pushed out the cycle
    // the command retires instead of being read back over AXI-Lite.
    output logic        xrf_sb_we,
    output logic  [2:0] xrf_sb_idx,
    output logic [17:0] xrf_sb_data
);

    logic signed [15:0] smem [16384];
    logic signed [15:0] sa_q;
    logic [13:0] sptr;
    logic [31:0] arg0, arg1, arg2;
    logic [15:0] cmd_cnt;
    logic        busy, err_op;
    logic  [3:0] cmd_op;
    logic  [3:0] eout_q;
    logic [17:0] xrf [8];
    logic  [2:0] xrfi;
    logic [17:0] amax_idx;
    logic [31:0] amax_val, lcyc, tcnt, layer_sel;
    logic [15:0] busy_left;

    logic        aw_got, w_got;
    logic  [9:0] awaddr_q;
    logic [31:0] wdata_q;
    /* verilator lint_off UNUSEDSIGNAL */
    wire  [1:0]  unused_lsb = s_axil_awaddr[1:0] | s_axil_araddr[1:0];
    wire  [3:0]  unused_wstrb = s_axil_wstrb;
    wire         unused_axib = ^{s_axib_awsize, s_axib_awburst, s_axib_awlen,
                                 s_axib_arsize, s_axib_arburst, s_axib_wstrb,
                                 s_axib_awaddr[1:0], s_axib_araddr[1:0],
                                 s_axib_wdata[31:16]};
    /* verilator lint_on UNUSEDSIGNAL */

    // ---- S6 burst window state (see the port comment) ----
    localparam logic [1:0] RB_IDLE = 2'd0, RB_WAIT = 2'd1, RB_DATA = 2'd2;
    localparam logic [1:0] WB_IDLE = 2'd0, WB_DATA = 2'd1, WB_RESP = 2'd2;

    logic  [1:0] rb_st, wb_st;
    logic [13:0] rb_addr, wb_addr;
    logic  [8:0] rb_left;
    logic  [1:0] rb_wait;                      // BRAM latency bubble
    logic        rb_ok, wb_ok;                 // !busy at the AR / AW handshake

    // The shim (C) owns the sa_q latency; a burst read that reaches the
    // window therefore always returns the CURRENT word.  Modelled as a
    // 2-cycle bubble at burst start, then 1 word/cycle.
    assign s_axib_arready = (rb_st == RB_IDLE);
    assign s_axib_rvalid  = (rb_st == RB_DATA);
    assign s_axib_rdata   = rb_ok ? {16'd0, unsigned'(smem[rb_addr])}
                                  : 32'hDEAD_C0DE;
    assign s_axib_rresp   = rb_ok ? 2'b00 : 2'b10;       // SLVERR while busy
    assign s_axib_rlast   = (rb_left == 9'd1);

    assign s_axib_awready = (wb_st == WB_IDLE);
    assign s_axib_wready  = (wb_st == WB_DATA);

    assign s_axil_awready = !aw_got && !s_axil_bvalid;
    assign s_axil_wready  = !w_got  && !s_axil_bvalid;
    assign s_axil_arready = !s_axil_rvalid;
    assign n_cmd = {16'd0, cmd_cnt};

    // the registered scratch read port, exactly as in layer_chan
    always_ff @(posedge aclk) sa_q <= smem[sptr];

    // the XRFI/XRFD decode below is hard-coded at word offsets 0x0E/0x0F;
    // assert the parameters agree so a future move of the window in
    // layer_chan cannot silently desync this stub from the DUT.
    initial begin
        if (XRFI_OFF != 12'h038 || XRFD_OFF != 12'h03C)
            $fatal(1, "seq_stub_layer: XRFI/XRFD offsets moved (%03h/%03h)",
                   XRFI_OFF, XRFD_OFF);
    end

    function automatic logic [17:0] ka_of(input logic [15:0] n);
        logic [31:0] m;
        begin
            m = (32'd3 * {16'd0, n} + 32'd7) % 32'd67;
            ka_of = 18'(signed'(m) - 32'sd33);
        end
    endfunction

    function automatic logic [17:0] k_of(input logic [15:0] n);
        logic [31:0] m;
        begin
            m = (32'd5 * {16'd0, n} + 32'd1) % 32'd33;
            k_of = 18'(signed'(m) - 32'sd16);
        end
    endfunction

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            aw_got <= 1'b0; w_got <= 1'b0;
            s_axil_bvalid <= 1'b0; s_axil_bresp <= 2'b00;
            s_axil_rvalid <= 1'b0; s_axil_rresp <= 2'b00; s_axil_rdata <= '0;
            sptr <= '0; arg0 <= '0; arg1 <= '0; arg2 <= '0;
            cmd_cnt <= '0; busy <= 1'b0; err_op <= 1'b0; cmd_op <= '0;
            eout_q <= '0; amax_idx <= '0; amax_val <= '0;
            lcyc <= '0; tcnt <= '0; layer_sel <= '0; busy_left <= '0;
            xrf_sb_we <= 1'b0; xrf_sb_idx <= '0; xrf_sb_data <= '0;
            xrfi <= '0;
            rb_st <= RB_IDLE; wb_st <= WB_IDLE;
            rb_addr <= '0; wb_addr <= '0; rb_left <= '0; rb_wait <= '0;
            rb_ok <= 1'b0; wb_ok <= 1'b0;
            s_axib_bvalid <= 1'b0; s_axib_bresp <= 2'b00;
            s_axib_bid <= 1'b0; s_axib_rid <= 1'b0;
            for (int i = 0; i < 8; i++) xrf[i] <= '0;
        end else begin
            xrf_sb_we <= 1'b0;
            if (busy) lcyc <= lcyc + 32'd1;

            // ---- command execution ----
            if (busy) begin
                if (busy_left == 16'd1) begin
                    busy <= 1'b0;
                    cmd_cnt <= cmd_cnt + 16'd1;
                    if (cmd_op == 4'd11) begin
                        if (arg0[3:0] == 4'd0) begin
                            eout_q <= 4'((32'd7 * {16'd0, cmd_cnt} + 32'd3)
                                         & 32'hF);
                            xrf_sb_we   <= 1'b1;
                            xrf_sb_idx  <= 3'd0;
                            xrf_sb_data <= {14'd0,
                                4'((32'd7 * {16'd0, cmd_cnt} + 32'd3) & 32'hF)};
                        end
                        if (arg0[3:0] == 4'd12) begin
                            xrf[arg2[0] ? 3'd2 : 3'd1] <= k_of(cmd_cnt);
                            xrf_sb_we   <= 1'b1;
                            xrf_sb_idx  <= arg2[0] ? 3'd2 : 3'd1;
                            xrf_sb_data <= k_of(cmd_cnt);
                        end
                        if ((arg0[3:0] == 4'd8) && arg2[6]) begin
                            xrf[2]      <= ka_of(cmd_cnt);
                            xrf_sb_we   <= 1'b1;
                            xrf_sb_idx  <= 3'd2;
                            xrf_sb_data <= ka_of(cmd_cnt);
                        end
                        if (arg0[3:0] == 4'd10) begin
                            amax_idx <= 18'((32'd2654435761 * {16'd0, cmd_cnt})
                                            & 32'h3FFFF);
                            amax_val <= 32'd1103515245 * {16'd0, cmd_cnt}
                                        + 32'd12345;
                        end
                    end
                end
                busy_left <= busy_left - 16'd1;
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
                    10'h000: if (!busy) begin                    // CMD
                        cmd_op <= wdata_q[3:0];
                        err_op <= (wdata_q[3:0] == 4'd0) || (wdata_q[3:0] > 4'd12);
                        busy   <= 1'b1;
                        busy_left <= 16'(CMD_CYC_MIN)
                                     + 16'({16'd0, cmd_cnt} % CMD_CYC_MOD);
                    end
                    10'h002: arg0 <= wdata_q;
                    10'h003: arg1 <= wdata_q;
                    10'h004: arg2 <= wdata_q;
                    10'h005: sptr <= wdata_q[13:0];
                    10'h006: begin                               // SWIN
                        if (busy) $fatal(1, "seq_stub_layer: SWIN write while busy");
                        smem[sptr] <= signed'(wdata_q[15:0]);
                        sptr <= sptr + 14'd1;
                    end
                    10'h00E: xrfi <= wdata_q[2:0];               // XRFI
                    10'h00F: xrf[xrfi] <= wdata_q[17:0];         // XRFD
                    10'h008: tcnt <= wdata_q;
                    10'h00C: layer_sel <= wdata_q;
                    10'h00D: lcyc <= '0;
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
                    10'h001: s_axil_rdata <= {cmd_cnt, 14'd0, err_op, busy};
                    10'h002: s_axil_rdata <= arg0;
                    10'h003: s_axil_rdata <= arg1;
                    10'h004: s_axil_rdata <= arg2;
                    10'h005: s_axil_rdata <= {18'd0, sptr};
                    10'h006: begin                               // SWIN read
                        if (busy) $fatal(1, "seq_stub_layer: SWIN read while busy");
                        s_axil_rdata <= {16'd0, unsigned'(sa_q)};
                        sptr <= sptr + 14'd1;
                    end
                    10'h007: s_axil_rdata <= {28'd0, eout_q};
                    10'h008: s_axil_rdata <= tcnt;
                    10'h009: s_axil_rdata <= 32'hFAB1_E5A0;
                    10'h00A: s_axil_rdata <= {14'd0, amax_idx};
                    10'h00B: s_axil_rdata <= amax_val;
                    10'h00C: s_axil_rdata <= layer_sel;
                    10'h00D: s_axil_rdata <= lcyc;
                    10'h00E: s_axil_rdata <= {29'd0, xrfi};
                    10'h00F: s_axil_rdata <= {14'd0, xrf[xrfi]};
                    default: s_axil_rdata <= 32'hDEAD_C0DE;
                endcase
            end else if (s_axil_rvalid && s_axil_rready)
                s_axil_rvalid <= 1'b0;

            // ---- S6 burst READ window (scratch word w at byte 4w) ----
            case (rb_st)
                RB_IDLE: if (s_axib_arvalid) begin
                    s_axib_rid <= s_axib_arid;
                    rb_addr    <= s_axib_araddr[15:2];
                    rb_left    <= {1'b0, s_axib_arlen} + 9'd1;
                    rb_ok      <= !busy;            // S6/R8: SLVERR while busy
                    rb_wait    <= 2'd2;
                    rb_st      <= RB_WAIT;
                end
                RB_WAIT: if (rb_wait == 2'd0) rb_st <= RB_DATA;
                         else rb_wait <= rb_wait - 2'd1;
                RB_DATA: if (s_axib_rready) begin
                    rb_addr <= rb_addr + 14'd1;
                    rb_left <= rb_left - 9'd1;
                    if (rb_left == 9'd1) rb_st <= RB_IDLE;
                end
                default: rb_st <= RB_IDLE;
            endcase

            // ---- S6 burst WRITE window (4th leg on the scratch mux) ----
            case (wb_st)
                WB_IDLE: if (s_axib_awvalid) begin
                    s_axib_bid <= s_axib_awid;
                    wb_addr    <= s_axib_awaddr[15:2];
                    wb_ok      <= !busy;
                    wb_st      <= WB_DATA;
                end
                WB_DATA: if (s_axib_wvalid) begin
                    if (wb_ok) smem[wb_addr] <= signed'(s_axib_wdata[15:0]);
                    wb_addr <= wb_addr + 14'd1;
                    if (s_axib_wlast) begin
                        s_axib_bvalid <= 1'b1;
                        s_axib_bresp  <= wb_ok ? 2'b00 : 2'b10;
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

    // A burst scratch write must never collide with an AXI-Lite SWIN write
    // (the stub would pick one and diverge from the python golden).
    /* verilator lint_off BLKSEQ */
    always @(posedge aclk) if (aresetn) begin
        if ((wb_st == WB_DATA) && s_axib_wvalid && wb_ok
            && aw_got && w_got && !s_axil_bvalid && (awaddr_q == 10'h006))
            $fatal(1, "seq_stub_layer: burst scratch write collides with an AXI-Lite SWIN write");
    end
    /* verilator lint_on BLKSEQ */

endmodule

`default_nettype wire
