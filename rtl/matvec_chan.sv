// matvec_chan: one DDR4 channel's complete matvec subsystem.
//
//   axi_aclk domain: AXI4-Lite CSR slave (always-responding, same safety
//     contract as csr_block), x-vector write window, result readback.
//   ui_clk domain:   ddr_rd_streamer -> matvec_engine -> result BRAM.
//   CDC: xpm_fifo_async (x writes), toggle+2FF (doorbell), 2FF (status),
//        xpm_memory_tdpram (results, true dual clock). Quasi-static cfg
//        buses cross unsynchronized by design: host writes cfg, then
//        doorbell; they are stable long before the start pulse lands
//        (declared in synth/constraints/fable5_cdc.xdc).
//
// Register map (byte addr, 32-bit):
//   0x00 CTRL    W  bit0: doorbell (start)
//   0x04 STATUS  R  {..., xfifo_ovfl, err_rresp, done, busy}
//   0x08 WBASE_LO  W  weight image byte address [31:0] (64B aligned)
//   0x0C WBASE_HI  W  [33:32]
//   0x10 WBEATS    W  total 64B beats
//   0x14 SHAPE     W  {3'b0, g64[28], nrows[27:12], sh[11:6], ng[5:0]}
//                     bit 28 g64: 0 = legacy G=128 rows, 1 = G=64 v2 rows
//                     (ng is the WEIGHT-BEAT count per row in both modes;
//                      a v2 row is ng + ceil(2*ng/32) beats, see
//                      matvec_engine header)
//   0x18 PERF_CYC_LO R   0x1C PERF_CYC_HI R (cycles@ui_clk, frozen at done)
//   0x20 PERF_BEATS  R
//   0x24 XWIN      W  push x word at xptr; xptr++
//   0x28 XPTR      RW x word pointer
//   0x2C RES_PTR   RW result read pointer
//   0x30 RES_DATA  R  result[res_ptr]; res_ptr++ (data valid: poll done)
//   0x34 IDENT     R  0xFAB1C4A0 | CHAN_ID
//
// ---------------------------------------------------------------------
// RUNG 3 / S5: s_axib — AXI4 burst window (aclk only, 32b, ID width 1)
// ---------------------------------------------------------------------
// A second slave port on the SAME clock as s_axil (100% aclk, spec R6).
// It exists so the sequencer's data movers can burst instead of paying a
// ~15-17 cycle AXI-Lite round trip per word.  Two windows, 64 KiB
// aperture (S4 stride):
//
//   READ  0x0000-0x3FFF : RES row r at byte 4r, r = araddr[13:2],
//                         ALL 4096 rows, start row = the full 12-bit
//                         field from the address (S12 — never hardwired).
//                         addrb is muxed away from res_ptr for the
//                         duration of the burst; the shim itself absorbs
//                         xpm_memory_tdpram READ_LATENCY_B = 2 in a
//                         credit-limited pipeline, so no RES_GAP pacing
//                         is needed on this path.
//   WRITE 0x4000-0x4FFF : XWIN word w at byte 4w, w = awaddr[11:2].
//                         Pushes the EXISTING, UNMODIFIED xpm_fifo_async
//                         at <= 1 word/cycle through a 2:1 mux on
//                         xf_din/xf_push.  FIFO full backpressures
//                         WREADY — a burst write is NEVER dropped and
//                         never sets xfifo_ovfl.
//
// Anything else in the aperture answers SLVERR (read or write), with the
// full beat count still returned / consumed.  INCR only, <= 256 beats,
// 4 KiB-boundary respected by the master (checked in `ifndef SYNTHESIS).
//
// ARBITRATION (documented choice) — STRICT FIXED PRIORITY TO AXI-LITE,
// on both shared resources; the burst side is the one that yields:
//
//  * BRAM port-B address (addrb).  A burst read owns addrb for the whole
//    R_ACT state (res_bsel).  Because an AXI-Lite RES_DATA read latches
//    doutb at its AR handshake, and doutb then reflects addrb from two
//    edges earlier, s_axil_arready is held LOW for res_bsel and the two
//    cycles after it (res_bsel_d1/_d2).  That is a pure ARREADY delay:
//    zero register-semantics change, and when no burst is running the
//    expression collapses to the shipped `!s_axil_rvalid`.  Conversely a
//    burst AR is only accepted while the AXI-Lite read channel showed no
//    ARVALID in the previous cycle (axil_ar_pend_q), so neither side can
//    starve the other.  No deadlock: a burst read never waits on the
//    AXI-Lite channel, so the held-off AXI-Lite read always drains.
//  * XWIN FIFO push.  xf_push_a (AXI-Lite) wins the mux unconditionally;
//    the burst's skid register simply does not drain that cycle, which
//    shows up as WREADY low for one cycle.  xf_push_a is a one-cycle
//    pulse, so progress is guaranteed.
//
// COMMIT CONTRACT (relied on by seq_movers: the last B response of a
// record is its fence before the next record's CSR traffic).  BVALID is
// registered from the SAME cycle in which the final beat drains, and that
// drain IS the xpm_fifo_async push (xf_push_b is combinational on it).  So
// the fifo captures the last word on exactly the edge that raises BVALID:
// when a master observes BVALID, every word of the burst is already
// architecturally visible in the XWIN fifo, never one cycle early.  (The
// shipped AXI-Lite XWIN path is weaker - it raises BVALID one cycle BEFORE
// its own push - which is why the burst path states this explicitly.)  An
// `ifndef SYNTHESIS check below fails if a burst ever responds without
// having pushed every one of its beats.
//
// xptr is NOT touched by burst writes (the x index is address-carried),
// and res_ptr is NOT touched by burst reads: every AXI-Lite register
// keeps bit-identical behaviour so the host-driven ladder still passes.

`timescale 1ns/1ps
`default_nettype none

module matvec_chan #(
    parameter logic [3:0] CHAN_ID = 4'd0,
    parameter int ADDR_W = 34
) (
    // ---------------- axi_aclk domain ----------------
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

    // ------- RUNG3 S5: AXI4 burst slave, 32b data / 16b addr, aclk -------
    // ID width 1.  No LOCK/CACHE/PROT/QOS/REGION/USER semantics (omitted;
    // SmartConnect drives the defaults).  INCR only, <= 256 beats.
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

    // ---------------- ui_clk domain ----------------
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 ui_clk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF m_axi, ASSOCIATED_RESET ui_rstn" *)
    input  wire         ui_clk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 ui_rstn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire         ui_rstn,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARADDR" *)
    (* X_INTERFACE_PARAMETER = "PROTOCOL AXI4, READ_WRITE_MODE READ_ONLY, DATA_WIDTH 512, ADDR_WIDTH 34" *)
    output logic [ADDR_W-1:0] m_axi_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARLEN" *)
    output logic [7:0]        m_axi_arlen,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARSIZE" *)
    output logic [2:0]        m_axi_arsize,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARBURST" *)
    output logic [1:0]        m_axi_arburst,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARVALID" *)
    output logic              m_axi_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARREADY" *)
    input  wire               m_axi_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RDATA" *)
    input  wire [511:0]       m_axi_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RRESP" *)
    input  wire [1:0]         m_axi_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RLAST" *)
    input  wire               m_axi_rlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RVALID" *)
    input  wire               m_axi_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RREADY" *)
    output logic              m_axi_rready
);

    // ==================================================================
    // axi_aclk domain: CSR regfile
    // ==================================================================
    // quasi-static cfg (named csr_static_* for the CDC false-path rule)
    logic [33:0] csr_static_wbase;
    logic [31:0] csr_static_wbeats;
    logic [5:0]  csr_static_ng, csr_static_sh;
    logic [15:0] csr_static_nrows;
    logic        csr_static_g64;

    logic        start_tgl;          // toggles on doorbell
    logic [9:0]  xptr;
    logic [11:0] res_ptr;
    logic        xfifo_ovfl;

    // status from ui domain (2FF)
    logic ui_busy, ui_done, ui_err;
    (* ASYNC_REG = "TRUE" *) logic [2:0] cdc_meta_stat, cdc_sync_stat;
    always_ff @(posedge aclk) begin
        cdc_meta_stat <= {ui_err, ui_done, ui_busy};
        cdc_sync_stat <= cdc_meta_stat;
    end

    // perf buses from ui domain (frozen when done; false-pathed)
    logic [47:0] perf_cycles;
    logic [31:0] perf_beats;

    // x write fifo (aclk -> ui_clk).  Two push sources, 2:1 mux, AXI-Lite
    // wins (see the arbitration note in the header).
    logic        xf_full;
    logic        xf_push_a;              // AXI-Lite XWIN write (registered)
    logic [41:0] xf_din_a;
    logic        xf_push_b;              // s_axib burst write window
    logic [41:0] xf_din_b;
    wire         xf_push = xf_push_a | xf_push_b;
    wire  [41:0] xf_din  = xf_push_a ? xf_din_a : xf_din_b;
    logic        xf_empty;
    logic [41:0] xf_dout;
    logic        xf_pop;

    xpm_fifo_async #(
        .FIFO_MEMORY_TYPE("distributed"),
        .FIFO_WRITE_DEPTH(32),
        .WRITE_DATA_WIDTH(42),
        .READ_DATA_WIDTH(42),
        .READ_MODE("fwft"),
        .FIFO_READ_LATENCY(0),
        .CDC_SYNC_STAGES(2),
        .USE_ADV_FEATURES("0000")
    ) u_xfifo (
        .rst(!aresetn),
        .wr_clk(aclk), .wr_en(xf_push), .din(xf_din), .full(xf_full),
        .rd_clk(ui_clk), .rd_en(xf_pop), .dout(xf_dout), .empty(xf_empty),
        .sleep(1'b0), .injectsbiterr(1'b0), .injectdbiterr(1'b0),
        /* verilator lint_off PINCONNECTEMPTY */
        .wr_data_count(), .rd_data_count(), .prog_full(), .prog_empty(),
        .almost_full(), .almost_empty(), .overflow(), .underflow(),
        .wr_ack(), .rd_rst_busy(), .wr_rst_busy(), .data_valid(),
        .sbiterr(), .dbiterr()
        /* verilator lint_on PINCONNECTEMPTY */
    );

    // result BRAM read port (B side, aclk): continuous read at res_ptr
    logic [31:0] res_rdata;

    // ---- AXI-Lite slave (single outstanding, always responds) ----
    logic        aw_got, w_got;
    logic [9:0]  awaddr_q;
    logic [31:0] wdata_q;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [3:0]  wstrb_q;     // full-word writes assumed for cfg regs
    wire  [1:0]  unused_lsbs = s_axil_awaddr[1:0] | s_axil_araddr[1:0];
    /* verilator lint_on UNUSEDSIGNAL */

    // Burst-shim forward declarations (all aclk).  res_bsel steals addrb
    // for the duration of a burst RES read; the AXI-Lite read channel is
    // held off for res_bsel + 2 cycles so its RES_DATA capture (doutb from
    // two edges earlier, READ_LATENCY_B = 2) can never see burst data.
    logic        res_bsel, res_bsel_d1, res_bsel_d2;
    logic [11:0] rb_addr;               // burst RES row counter
    wire  [11:0] res_addrb = res_bsel ? rb_addr : res_ptr;

    assign s_axil_awready = !aw_got && !s_axil_bvalid;
    assign s_axil_wready  = !w_got  && !s_axil_bvalid;
    assign s_axil_arready = !s_axil_rvalid
                            && !(res_bsel || res_bsel_d1 || res_bsel_d2);

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            aw_got <= 1'b0; w_got <= 1'b0;
            s_axil_bvalid <= 1'b0; s_axil_bresp <= 2'b00;
            start_tgl <= 1'b0;
            xptr <= '0; res_ptr <= '0;
            xf_push_a <= 1'b0; xfifo_ovfl <= 1'b0;
            csr_static_wbase <= '0; csr_static_wbeats <= '0;
            csr_static_ng <= '0; csr_static_sh <= '0; csr_static_nrows <= '0;
            csr_static_g64 <= 1'b0;
        end else begin
            xf_push_a <= 1'b0;

            if (s_axil_awvalid && s_axil_awready) begin
                aw_got <= 1'b1; awaddr_q <= s_axil_awaddr[11:2];
            end
            if (s_axil_wvalid && s_axil_wready) begin
                w_got <= 1'b1; wdata_q <= s_axil_wdata; wstrb_q <= s_axil_wstrb;
            end

            if (aw_got && w_got && !s_axil_bvalid) begin
                case (awaddr_q)
                    10'h000: if (wdata_q[0]) start_tgl <= ~start_tgl;     // CTRL
                    10'h002: csr_static_wbase[31:0]  <= {wdata_q[31:6], 6'b0}; // WBASE_LO
                    10'h003: csr_static_wbase[33:32] <= wdata_q[1:0];     // WBASE_HI
                    10'h004: csr_static_wbeats <= wdata_q;                // WBEATS
                    10'h005: begin                                        // SHAPE
                        csr_static_ng    <= wdata_q[5:0];
                        csr_static_sh    <= wdata_q[11:6];
                        csr_static_nrows <= wdata_q[27:12];
                        csr_static_g64   <= wdata_q[28];
                    end
                    10'h009: begin                                        // XWIN
                        if (!xf_full) begin
                            xf_din_a  <= {xptr, wdata_q};
                            xf_push_a <= 1'b1;
                        end else xfifo_ovfl <= 1'b1;
                        xptr <= xptr + 1'b1;
                    end
                    10'h00A: xptr <= wdata_q[9:0];                        // XPTR
                    10'h00B: res_ptr <= wdata_q[11:0];                    // RES_PTR
                    default: ;
                endcase
                s_axil_bvalid <= 1'b1; s_axil_bresp <= 2'b00;
                aw_got <= 1'b0; w_got <= 1'b0;
            end
            if (s_axil_bvalid && s_axil_bready) s_axil_bvalid <= 1'b0;

            // reads
            if (s_axil_arvalid && s_axil_arready) begin
                s_axil_rvalid <= 1'b1; s_axil_rresp <= 2'b00;
                case (s_axil_araddr[11:2])
                    10'h001: s_axil_rdata <= {28'b0, xfifo_ovfl, cdc_sync_stat};
                    10'h002: s_axil_rdata <= csr_static_wbase[31:0];
                    10'h003: s_axil_rdata <= {30'b0, csr_static_wbase[33:32]};
                    10'h004: s_axil_rdata <= csr_static_wbeats;
                    10'h005: s_axil_rdata <= {3'b0, csr_static_g64,
                                              csr_static_nrows,
                                              csr_static_sh, csr_static_ng};
                    10'h006: s_axil_rdata <= perf_cycles[31:0];
                    10'h007: s_axil_rdata <= {16'b0, perf_cycles[47:32]};
                    10'h008: s_axil_rdata <= perf_beats;
                    10'h00A: s_axil_rdata <= {22'b0, xptr};
                    10'h00B: s_axil_rdata <= {20'b0, res_ptr};
                    10'h00C: begin                                        // RES_DATA
                        s_axil_rdata <= res_rdata;
                        res_ptr <= res_ptr + 1'b1;
                    end
                    10'h00D: s_axil_rdata <= {28'hFAB1C4A, CHAN_ID};      // IDENT
                    default: s_axil_rdata <= 32'hDEADC0DE;
                endcase
            end else if (s_axil_rvalid && s_axil_rready)
                s_axil_rvalid <= 1'b0;
        end
    end

    // ==================================================================
    // ui_clk domain
    // ==================================================================
    // doorbell: toggle -> 2FF -> edge
    (* ASYNC_REG = "TRUE" *) logic [1:0] cdc_meta_start;
    logic start_sync_q, start_pulse;
    always_ff @(posedge ui_clk) begin
        if (!ui_rstn) begin
            cdc_meta_start <= '0; start_sync_q <= 1'b0;
        end else begin
            cdc_meta_start <= {cdc_meta_start[0], start_tgl};
            start_sync_q   <= cdc_meta_start[1];
        end
    end
    assign start_pulse = cdc_meta_start[1] ^ start_sync_q;

    // x fifo pop -> registered snapshot -> engine x port (the fifo dout ->
    // x_mem write-decode path was the ui_clk WNS once placement got tight)
    assign xf_pop = !xf_empty;
    logic        xq_we;
    logic [41:0] xq_d;
    always_ff @(posedge ui_clk) begin
        if (!ui_rstn) xq_we <= 1'b0;
        else          xq_we <= xf_pop;
        xq_d <= xf_dout;
    end

    // streamer + engine
    logic        b_valid, b_ready;
    logic [511:0] b_data;
    logic        st_busy, st_done, en_busy, en_done, err_rresp;
    logic        m_valid;
    logic [31:0] m_y32;
    logic [15:0] m_row;

    ddr_rd_streamer #(.ADDR_W(ADDR_W)) u_streamer (
        .clk(ui_clk), .rstn(ui_rstn),
        .cfg_base(csr_static_wbase), .cfg_beats(csr_static_wbeats),
        .start(start_pulse), .busy(st_busy), .done(st_done),
        .perf_cycles, .perf_beats,
        .m_araddr(m_axi_araddr), .m_arlen(m_axi_arlen), .m_arsize(m_axi_arsize),
        .m_arburst(m_axi_arburst), .m_arvalid(m_axi_arvalid), .m_arready(m_axi_arready),
        .m_rdata(m_axi_rdata), .m_rresp(m_axi_rresp), .m_rlast(m_axi_rlast),
        .m_rvalid(m_axi_rvalid), .m_rready(m_axi_rready), .err_rresp(err_rresp),
        .s_valid(b_valid), .s_ready(b_ready), .s_data(b_data)
    );

    matvec_engine u_engine (
        .clk(ui_clk), .rstn(ui_rstn),
        .cfg_ng(csr_static_ng), .cfg_sh(csr_static_sh),
        .cfg_g64(csr_static_g64), .cfg_nrows(csr_static_nrows),
        .start(start_pulse), .busy(en_busy), .done(en_done),
        .x_we(xq_we), .x_waddr(xq_d[41:32]), .x_wdata(xq_d[31:0]),
        .s_valid(b_valid), .s_ready(b_ready), .s_data(b_data),
        .m_valid(m_valid), .m_ready(1'b1), .m_y32(m_y32), .m_row(m_row)
    );

    assign ui_busy = st_busy || en_busy;
    assign ui_done = en_done;
    assign ui_err  = err_rresp;

    // result BRAM: port A write (ui_clk, engine), port B read (aclk, CSR)
    xpm_memory_tdpram #(
        .MEMORY_SIZE(4096 * 32),
        .MEMORY_PRIMITIVE("block"),
        .CLOCKING_MODE("independent_clock"),
        .WRITE_DATA_WIDTH_A(32), .READ_DATA_WIDTH_A(32), .ADDR_WIDTH_A(12),
        .WRITE_DATA_WIDTH_B(32), .READ_DATA_WIDTH_B(32), .ADDR_WIDTH_B(12),
        .READ_LATENCY_A(1), .READ_LATENCY_B(2),
        .WRITE_MODE_A("no_change"), .WRITE_MODE_B("no_change"),
        .USE_MEM_INIT(0)
    ) u_resram (
        .clka(ui_clk), .rsta(1'b0), .ena(1'b1),
        .wea(m_valid), .addra(m_row[11:0]), .dina(m_y32),
        /* verilator lint_off PINCONNECTEMPTY */
        .douta(),
        /* verilator lint_on PINCONNECTEMPTY */
        .clkb(aclk), .rstb(!aresetn), .enb(1'b1),
        .web(1'b0), .addrb(res_addrb), .dinb(32'h0),
        .doutb(res_rdata),
        .sleep(1'b0),
        .injectsbiterra(1'b0), .injectdbiterra(1'b0),
        .injectsbiterrb(1'b0), .injectdbiterrb(1'b0),
        /* verilator lint_off PINCONNECTEMPTY */
        .sbiterra(), .dbiterra(), .sbiterrb(), .dbiterrb(),
        .regcea(1'b1), .regceb(1'b1)
        /* verilator lint_on PINCONNECTEMPTY */
    );

    // ==================================================================
    // RUNG 3 / S5 burst shim — 100% aclk (spec R6), nothing on ui_clk
    // ==================================================================
    localparam int RFD = 4;                       // R output fifo depth

    // ---------------- read side (RES window 0x0000-0x3FFF) ------------
    localparam logic R_IDLE = 1'b0, R_ACT = 1'b1;
    logic        rstate;
    logic [8:0]  rb_beats;                        // beats left to ISSUE
    logic        rb_win;                          // AR landed in RES window
    logic [0:0]  rb_id;
    logic [1:0]  rpv;                             // BRAM latency-2 valid pipe
    logic [1:0]  rpl;                             // matching RLAST flag
    logic [2:0]  rcred;                           // free slots not yet claimed
    logic [33:0] rf_mem [RFD];                    // {last, err, data}
    logic [1:0]  rf_wp, rf_rp;
    logic [2:0]  rf_cnt;
    logic        axil_ar_pend_q;                  // registered s_axil_arvalid

    wire  r_islast = (rb_beats == 9'd1);
    wire  r_issue  = (rstate == R_ACT) && (rb_beats != 9'd0) && (rcred != 3'd0);
    wire  r_pmem   = rpv[1];                      // in-window data return
    wire  r_perr   = r_issue && !rb_win;          // out-of-window beat
    wire  rf_push  = r_pmem | r_perr;
    wire  [33:0] rf_din = r_perr ? {r_islast, 1'b1, 32'hDEADC0DE}
                                 : {rpl[1],   1'b0, res_rdata};
    wire  rf_pop   = s_axib_rvalid && s_axib_rready;

    assign res_bsel        = (rstate == R_ACT) && rb_win;
    assign s_axib_arready  = (rstate == R_IDLE) && !axil_ar_pend_q;
    assign s_axib_rvalid   = (rf_cnt != 3'd0);
    assign s_axib_rdata    = rf_mem[rf_rp][31:0];
    assign s_axib_rresp    = rf_mem[rf_rp][32] ? 2'b10 : 2'b00;   // SLVERR
    assign s_axib_rlast    = rf_mem[rf_rp][33];
    assign s_axib_rid      = rb_id;

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            rstate <= R_IDLE; rb_beats <= '0; rb_win <= 1'b0; rb_id <= '0;
            rb_addr <= '0; rpv <= '0; rpl <= '0; rcred <= 3'(RFD);
            rf_wp <= '0; rf_rp <= '0; rf_cnt <= '0;
            res_bsel_d1 <= 1'b0; res_bsel_d2 <= 1'b0; axil_ar_pend_q <= 1'b0;
        end else begin
            axil_ar_pend_q <= s_axil_arvalid;
            res_bsel_d1    <= res_bsel;
            res_bsel_d2    <= res_bsel_d1;

            // BRAM read pipeline: addrb at edge n -> doutb valid in cycle n+2
            rpv[0] <= r_issue && rb_win;
            rpv[1] <= rpv[0];
            rpl[0] <= r_islast;
            rpl[1] <= rpl[0];

            if (r_issue) begin
                rb_addr  <= rb_addr  + 12'd1;
                rb_beats <= rb_beats - 9'd1;
            end

            // R output fifo (register based; also the credit pool)
            if (rf_push) begin
                rf_mem[rf_wp] <= rf_din;
                rf_wp         <= rf_wp + 2'd1;
            end
            if (rf_pop) rf_rp <= rf_rp + 2'd1;
            rf_cnt <= rf_cnt + {2'b0, rf_push}  - {2'b0, rf_pop};
            rcred  <= rcred  - {2'b0, r_issue}  + {2'b0, rf_pop};

            case (rstate)
                R_IDLE:
                    if (s_axib_arvalid && s_axib_arready) begin
                        rb_id    <= s_axib_arid;
                        rb_win   <= (s_axib_araddr[15:14] == 2'b00);
                        rb_addr  <= s_axib_araddr[13:2];      // S12: full 12b
                        rb_beats <= {1'b0, s_axib_arlen} + 9'd1;
                        rstate   <= R_ACT;
                    end
                default:   // R_ACT: release only once fully drained
                    if ((rb_beats == 9'd0) && (rpv == 2'b00) && (rf_cnt == 3'd0))
                        rstate <= R_IDLE;
            endcase
        end
    end

    // ---------------- write side (XWIN window 0x4000-0x4FFF) ----------
    localparam logic [1:0] W_IDLE = 2'd0, W_DATA = 2'd1, W_RESP = 2'd2;
    logic [1:0]  wstate;
    logic [9:0]  wb_ptr;                          // x word index
    logic        wb_win;
    logic [0:0]  wb_id;
    logic        ws_v, ws_last;                   // 1-deep W skid
    logic [31:0] ws_d;

    // AXI-Lite always wins the fifo mux -> a burst beat simply does not
    // drain that cycle (xf_push_a is a 1-cycle pulse, so no starvation).
    // axil_wr_commit is the cycle in which the AXI-Lite side samples
    // xf_full to decide an XWIN push; the burst must not consume the last
    // free slot in that cycle, or the shipped `if (!xf_full)` test would
    // be stale by the time xf_push_a fires and the AXI-Lite word would be
    // dropped into xfifo_ovfl.  Holding the burst for that one cycle
    // keeps the AXI-Lite path bit-identical.
    wire axil_wr_commit = aw_got && w_got && !s_axil_bvalid;
    wire ws_can   = wb_win ? (!xf_full && !xf_push_a && !axil_wr_commit) : 1'b1;
    wire ws_drain = ws_v && (wstate == W_DATA) && ws_can;

    assign s_axib_awready = (wstate == W_IDLE);
    assign s_axib_wready  = (wstate == W_DATA) && (!ws_v || (ws_can && !ws_last));
    assign s_axib_bid     = wb_id;
    assign xf_push_b      = ws_drain && wb_win;
    assign xf_din_b       = {wb_ptr, ws_d};

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            wstate <= W_IDLE; wb_ptr <= '0; wb_win <= 1'b0; wb_id <= '0;
            ws_v <= 1'b0; ws_last <= 1'b0; ws_d <= '0;
            s_axib_bvalid <= 1'b0; s_axib_bresp <= 2'b00;
        end else begin
            if (s_axib_wvalid && s_axib_wready) begin
                ws_v <= 1'b1; ws_d <= s_axib_wdata; ws_last <= s_axib_wlast;
            end else if (ws_drain) ws_v <= 1'b0;

            if (ws_drain) wb_ptr <= wb_ptr + 10'd1;

            case (wstate)
                W_IDLE:
                    if (s_axib_awvalid && s_axib_awready) begin
                        wb_id  <= s_axib_awid;
                        wb_win <= (s_axib_awaddr[15:12] == 4'h4);
                        wb_ptr <= s_axib_awaddr[11:2];
                        wstate <= W_DATA;
                    end
                W_DATA:
                    if (ws_drain && ws_last) begin
                        s_axib_bvalid <= 1'b1;
                        s_axib_bresp  <= wb_win ? 2'b00 : 2'b10;  // SLVERR
                        wstate        <= W_RESP;
                    end
                W_RESP:
                    if (s_axib_bready) begin
                        s_axib_bvalid <= 1'b0;
                        wstate        <= W_IDLE;
                    end
                default: wstate <= W_IDLE;
            endcase
        end
    end

`ifndef SYNTHESIS
    // S7 / S5 request checks — simulation only, never synthesised.
    function automatic bit axib_req_ok(input logic [15:0] a,
                                       input logic [7:0]  l,
                                       input logic [2:0]  sz,
                                       input logic [1:0]  bt);
        int base, bytes;
        base  = int'({20'd0, a[11:0]});
        bytes = (int'({24'd0, l}) + 1) * 4;
        axib_req_ok = (bt == 2'b01) && (sz == 3'b010) && (a[1:0] == 2'b00)
                      && ((base + bytes) <= 4096);
    endfunction

    always_ff @(posedge aclk) if (aresetn) begin
        if (s_axib_arvalid && s_axib_arready
            && !axib_req_ok(s_axib_araddr, s_axib_arlen,
                            s_axib_arsize, s_axib_arburst))
            $fatal(1, "matvec_chan s_axib AR: bad request addr=%h len=%0d size=%b burst=%b (INCR/4B/aligned/no-4KiB-cross required)",
                   s_axib_araddr, s_axib_arlen, s_axib_arsize, s_axib_arburst);
        if (s_axib_arvalid && s_axib_arready && (s_axib_araddr[15:14] == 2'b00)
            && ((int'({20'd0, s_axib_araddr[13:2]}) + int'({24'd0, s_axib_arlen})) > 4095))
            $fatal(1, "matvec_chan s_axib AR: RES burst leaves the 4096-row window (addr=%h len=%0d)",
                   s_axib_araddr, s_axib_arlen);
        if (s_axib_awvalid && s_axib_awready
            && !axib_req_ok(s_axib_awaddr, s_axib_awlen,
                            s_axib_awsize, s_axib_awburst))
            $fatal(1, "matvec_chan s_axib AW: bad request addr=%h len=%0d size=%b burst=%b (INCR/4B/aligned/no-4KiB-cross required)",
                   s_axib_awaddr, s_axib_awlen, s_axib_awsize, s_axib_awburst);
        if (s_axib_awvalid && s_axib_awready && (s_axib_awaddr[15:12] == 4'h4)
            && ((int'({22'd0, s_axib_awaddr[11:2]}) + int'({24'd0, s_axib_awlen})) > 1023))
            $fatal(1, "matvec_chan s_axib AW: XWIN burst leaves the 1024-word window (addr=%h len=%0d)",
                   s_axib_awaddr, s_axib_awlen);
        if (s_axib_wvalid && s_axib_wready && (s_axib_wstrb != 4'hF))
            $fatal(1, "matvec_chan s_axib W: partial WSTRB %b unsupported", s_axib_wstrb);
        if (xf_push_a && xf_push_b)
            $fatal(1, "matvec_chan: XWIN fifo push collision (arbitration broken)");
        if (xf_push && xf_full)
            $fatal(1, "matvec_chan: XWIN fifo push while full");
    end

    // COMMIT CONTRACT check: a burst may not raise BVALID unless every one
    // of its beats has actually been pushed into the XWIN fifo.
    logic [8:0] wb_pushed, wb_explen;
    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            wb_pushed <= '0; wb_explen <= '0;
        end else begin
            if (s_axib_awvalid && s_axib_awready) begin
                wb_pushed <= '0;
                wb_explen <= {1'b0, s_axib_awlen} + 9'd1;
            end else if (xf_push_b) begin
                wb_pushed <= wb_pushed + 9'd1;
            end
            if ((wstate == W_DATA) && ws_drain && ws_last && wb_win
                && ((wb_pushed + 9'd1) != wb_explen))
                $fatal(1, "matvec_chan s_axib: BVALID would commit %0d of %0d XWIN pushes",
                       wb_pushed + 9'd1, wb_explen);
        end
    end
`else
    /* verilator lint_off UNUSEDSIGNAL */
    wire axib_unused = (^s_axib_arsize) ^ (^s_axib_arburst)
                     ^ (^s_axib_awsize) ^ (^s_axib_awburst) ^ (^s_axib_wstrb);
    /* verilator lint_on UNUSEDSIGNAL */
`endif

endmodule

`default_nettype wire
