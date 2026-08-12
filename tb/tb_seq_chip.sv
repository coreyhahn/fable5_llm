// tb_seq_chip — FULL-CHIP, SEQ-DRIVEN simulation.
//
// tb_seq_unit proves rtl/seq_unit.sv against BEHAVIOURAL stubs of the two
// slaves.  This testbench replaces both stubs with the REAL, silicon-proven
// engines and drives the whole thing from a real emitted record stream, so
// the only thing the host does is load the stream, write START, and drain
// the OUT FIFO:
//
//   seq_unit.m_axil -> seq_fabric_model -> matvec_chan x NMV @0x1000..
//                                       -> layer_chan       @0x5000
//   seq_unit.m_axib -> seq_burst_fabric -> matvec_chan.s_axib @0x1_0000..
//                      (RUNG3 S2/S4)    -> layer_chan.s_axib  @0x5_0000
//   seq_unit.m_axi  -> seq_mem_file 128b: <p>.seq   @ SEQ_STREAM_BASE
//                                         <p>.seqdata.bin @ SEQ_DATA_BASE
//                                         <b>.emb.bin     @ EMB_BASE
//   matvec_chan.m_axi -> seq_mem_file 512b: <b>.wimg.bin  @ W_BASE
//                        (the REAL packed W4 images, ui_clk domain)
//   seq_unit.s_axil <- the TB acting as the host
//
// GOLDEN.  tb/scripts/gen_seq_chip_vectors.py runs ref/seq_model.py over the
// SAME stream and writes <p>.chip: the final PC, the OUT FIFO token list, the
// XRF, every non-staging scratch word, the banked TCNT pairs and the
// EOUT/AMAX registers.  So this is the SEQ-driven half of the dual-driven
// equivalence: the .txt half (tb_layer_chan +script=...) runs the identical
// schedule host-driven against the same layer_chan RTL, and ref/seq_model
// --gate proves the two schedules agree bit-for-bit at the model level.
//
// Run:
//   obj_dir_tb_seq_chip/tb_seq_chip +seq=scripts/w3/tok2_s1.e \
//       +base=scripts/w3/tok2_s1 [+watchdog_ms=N] [+nomem]
//
// MULTI-LAUNCH (docs/CHAT_SEQ_SPEC.md gate I1).  The .chip golden may hold
// MORE THAN ONE launch section, in which case this testbench relaunches the
// SAME, NEVER-RESET DUT once per section:
//
//   BASES ...            (once)
//   NLAUNCH n
//   LAUNCH i <rec offset into the .seq file> <records>
//   KIND <tag>  PC <n>  XRF/TOK/TCNT/EOUT/AMAX/RDWIN/MEM ...
//   ENDL
//   ... END
//
// Between sections the host BFM does exactly what sw/seq_run.py's
// seq_start_and_poll() does on silicon — drain the OUT FIFO, zero the XRF
// and TCNT_SEQ, write BASE/LEN/ENTRY, pulse START — and NOTHING else: rstn
// and ui_rstn stay high (a continuous assertion enforces that), so every
// layer_chan bank (KV, DeltaNet, conv windows, TCNT) carries over.  Each
// section's golden was produced by ref/seq_model.py running the identical
// image sequence against ONE persistent Mach, so a START that clobbered a
// bank shows up as a state mismatch, and the per-launch TCNT + carried-state
// checks say so directly.
//
// RDWIN <lo> <hi> <min> <max> counts the DDR read bursts a launch issues
// into an address window.  Gate I1 uses it to prove WHICH RoPE table a
// pos > 85 launch fetched (the XRF[4] cursor is a signed 18-bit register and
// ref/seq_model.py does not model its sign extension).

`timescale 1ns/1ps
`default_nettype none

module tb_seq_chip #(
    parameter int LAT      = 4,        // AXI-Lite fabric latency each way
    parameter int BLAT     = 4,        // burst fabric latency each way (S2)
    parameter int DDRLAT   = 32,       // record/LDC/EMB first-word latency
    parameter int WLAT     = 40,       // weight-image first-word latency
    parameter int NMV      = 1,        // REAL matvec_chan instances
    parameter int RESGAP   = 3         // retired by rung 3 (kept for compat)
);
    localparam int NSLV  = 8;
    localparam int NBSLV = 5;          // burst fabric MIs (RUNG3 S2)
    localparam int MAXMEM = 16384;

    // DDR plan — ref/seq_format.py + sw/hwmap.py (asserted against the
    // BASES line of the .chip file, so a generator change cannot drift).
    localparam longint SEQ_STREAM_BASE = 64'h0000_0000_9000_0000;
    localparam longint SEQ_DATA_BASE   = 64'h0000_0000_8000_0000;
    localparam longint EMB_BASE        = 64'h0000_0000_6000_0000;
    localparam longint W_BASE          = 64'h0000_0000_1000_0000;

    logic clk = 1'b0;
    logic ui_clk = 1'b0;
    logic rstn = 1'b0;
    logic ui_rstn = 1'b0;
    /* verilator lint_off BLKSEQ */
    always #2     clk    = ~clk;                    // 250 MHz aclk
    always #1.667 ui_clk = ~ui_clk;                 // ~300 MHz ui_clk
    /* verilator lint_on BLKSEQ */

    /* verilator lint_off UNUSEDSIGNAL */
    // ---------------- DUT <-> fabric ----------------
    logic [31:0] m_awaddr, m_wdata, m_araddr, m_rdata;
    logic [3:0]  m_wstrb;
    logic        m_awvalid, m_awready, m_wvalid, m_wready;
    logic        m_bvalid, m_bready, m_arvalid, m_arready, m_rvalid, m_rready;
    logic [1:0]  m_bresp, m_rresp;

    logic [NSLV-1:0][11:0] f_awaddr, f_araddr;
    logic [NSLV-1:0][31:0] f_wdata, f_rdata;
    logic [NSLV-1:0][3:0]  f_wstrb;
    logic [NSLV-1:0]       f_awvalid, f_awready, f_wvalid, f_wready;
    logic [NSLV-1:0]       f_bvalid, f_bready, f_arvalid, f_arready;
    logic [NSLV-1:0]       f_rvalid, f_rready;
    logic [NSLV-1:0][1:0]  f_bresp, f_rresp;
    logic [31:0] fab_nwr, fab_nrd, fab_bwr, fab_brd;

    // ---------------- DUT <-> burst fabric (RUNG3 S3/S4) ----------------
    logic        mb_awid, mb_arid, mb_bid, mb_rid;
    logic [31:0] mb_awaddr, mb_araddr, mb_wdata, mb_rdata;
    logic [7:0]  mb_awlen, mb_arlen;
    logic [2:0]  mb_awsize, mb_arsize;
    logic [1:0]  mb_awburst, mb_arburst, mb_bresp, mb_rresp;
    logic [3:0]  mb_wstrb;
    logic        mb_awvalid, mb_awready, mb_wvalid, mb_wready, mb_wlast;
    logic        mb_bvalid, mb_bready, mb_arvalid, mb_arready;
    logic        mb_rvalid, mb_rready, mb_rlast;

    logic [NBSLV-1:0][0:0]  g_awid, g_arid, g_bid, g_rid;
    logic [NBSLV-1:0][15:0] g_awaddr, g_araddr;
    logic [NBSLV-1:0][7:0]  g_awlen, g_arlen;
    logic [NBSLV-1:0][2:0]  g_awsize, g_arsize;
    logic [NBSLV-1:0][1:0]  g_awburst, g_arburst, g_bresp, g_rresp;
    logic [NBSLV-1:0][31:0] g_wdata, g_rdata;
    logic [NBSLV-1:0][3:0]  g_wstrb;
    logic [NBSLV-1:0]       g_awvalid, g_awready, g_wvalid, g_wready, g_wlast;
    logic [NBSLV-1:0]       g_bvalid, g_bready, g_arvalid, g_arready;
    logic [NBSLV-1:0]       g_rvalid, g_rready, g_rlast;
    logic [31:0] bf_nwr, bf_nwbeat, bf_nrd, bf_nrbeat, bf_bwr, bf_brd;
    logic [31:0] bf_ndec, bf_nslv, bf_nidm;

    // ---------------- DUT <-> record/const/embedding DDR ----------------
    logic [33:0]  d_araddr;
    logic [7:0]   d_arlen;
    logic [2:0]   d_arsize;
    logic [1:0]   d_arburst, d_rresp;
    logic         d_arvalid, d_arready, d_rlast, d_rvalid, d_rready;
    logic [127:0] d_rdata;
    logic [63:0]  d_nbeats, d_nmiss;

    // ---------------- host (s_axil) ----------------
    logic [11:0] h_awaddr, h_araddr;
    logic [31:0] h_wdata, h_rdata;
    logic        h_awvalid, h_awready, h_wvalid, h_wready, h_bvalid, h_bready;
    logic        h_arvalid, h_arready, h_rvalid, h_rready;
    logic [1:0]  h_bresp, h_rresp;

    logic seq_busy, seq_halted, seq_err;
    logic [63:0] w_nbeats [4];
    logic [63:0] w_nmiss  [4];
    /* verilator lint_on UNUSEDSIGNAL */

    // ==================================================================
    seq_unit #(
        .ADDR_W(34), .RES_GAP(RESGAP), .USE_XRF_SIDEBAND(1'b0),
        .XRFI_OFF(12'h038), .XRFD_OFF(12'h03C)
    ) dut (
        .aclk(clk), .aresetn(rstn),
        .s_axil_awaddr(h_awaddr), .s_axil_awvalid(h_awvalid),
        .s_axil_awready(h_awready), .s_axil_wdata(h_wdata),
        .s_axil_wstrb(4'hF), .s_axil_wvalid(h_wvalid), .s_axil_wready(h_wready),
        .s_axil_bresp(h_bresp), .s_axil_bvalid(h_bvalid), .s_axil_bready(h_bready),
        .s_axil_araddr(h_araddr), .s_axil_arvalid(h_arvalid),
        .s_axil_arready(h_arready), .s_axil_rdata(h_rdata),
        .s_axil_rresp(h_rresp), .s_axil_rvalid(h_rvalid), .s_axil_rready(h_rready),

        .m_axil_awaddr(m_awaddr), .m_axil_awvalid(m_awvalid),
        .m_axil_awready(m_awready), .m_axil_wdata(m_wdata),
        .m_axil_wstrb(m_wstrb), .m_axil_wvalid(m_wvalid), .m_axil_wready(m_wready),
        .m_axil_bresp(m_bresp), .m_axil_bvalid(m_bvalid), .m_axil_bready(m_bready),
        .m_axil_araddr(m_araddr), .m_axil_arvalid(m_arvalid),
        .m_axil_arready(m_arready), .m_axil_rdata(m_rdata),
        .m_axil_rresp(m_rresp), .m_axil_rvalid(m_rvalid), .m_axil_rready(m_rready),

        .m_axi_araddr(d_araddr), .m_axi_arlen(d_arlen), .m_axi_arsize(d_arsize),
        .m_axi_arburst(d_arburst), .m_axi_arvalid(d_arvalid),
        .m_axi_arready(d_arready), .m_axi_rdata(d_rdata), .m_axi_rresp(d_rresp),
        .m_axi_rlast(d_rlast), .m_axi_rvalid(d_rvalid), .m_axi_rready(d_rready),

        // layer_chan has no XRF sideband port — the board build ties these
        // off too (synth/scripts/create_project.tcl), so the AXI-Lite
        // XRFI/XRFD mirror is the path under test here.
        .m_axib_awid(mb_awid), .m_axib_awaddr(mb_awaddr),
        .m_axib_awlen(mb_awlen), .m_axib_awsize(mb_awsize),
        .m_axib_awburst(mb_awburst), .m_axib_awvalid(mb_awvalid),
        .m_axib_awready(mb_awready),
        .m_axib_wdata(mb_wdata), .m_axib_wstrb(mb_wstrb),
        .m_axib_wlast(mb_wlast), .m_axib_wvalid(mb_wvalid),
        .m_axib_wready(mb_wready),
        .m_axib_bid(mb_bid), .m_axib_bresp(mb_bresp),
        .m_axib_bvalid(mb_bvalid), .m_axib_bready(mb_bready),
        .m_axib_arid(mb_arid), .m_axib_araddr(mb_araddr),
        .m_axib_arlen(mb_arlen), .m_axib_arsize(mb_arsize),
        .m_axib_arburst(mb_arburst), .m_axib_arvalid(mb_arvalid),
        .m_axib_arready(mb_arready),
        .m_axib_rid(mb_rid), .m_axib_rdata(mb_rdata),
        .m_axib_rresp(mb_rresp), .m_axib_rlast(mb_rlast),
        .m_axib_rvalid(mb_rvalid), .m_axib_rready(mb_rready),

        .xrf_sb_we(1'b0), .xrf_sb_idx(3'd0), .xrf_sb_data(18'd0),
        .seq_busy(seq_busy), .seq_halted(seq_halted), .seq_err(seq_err)
    );

    seq_burst_fabric #(.LAT(BLAT), .NSLV(NBSLV)) u_bfab (
        .aclk(clk), .aresetn(rstn),
        .s_awid(mb_awid), .s_awaddr(mb_awaddr), .s_awlen(mb_awlen),
        .s_awsize(mb_awsize), .s_awburst(mb_awburst),
        .s_awvalid(mb_awvalid), .s_awready(mb_awready),
        .s_wdata(mb_wdata), .s_wstrb(mb_wstrb), .s_wlast(mb_wlast),
        .s_wvalid(mb_wvalid), .s_wready(mb_wready),
        .s_bid(mb_bid), .s_bresp(mb_bresp), .s_bvalid(mb_bvalid),
        .s_bready(mb_bready),
        .s_arid(mb_arid), .s_araddr(mb_araddr), .s_arlen(mb_arlen),
        .s_arsize(mb_arsize), .s_arburst(mb_arburst),
        .s_arvalid(mb_arvalid), .s_arready(mb_arready),
        .s_rid(mb_rid), .s_rdata(mb_rdata), .s_rresp(mb_rresp),
        .s_rlast(mb_rlast), .s_rvalid(mb_rvalid), .s_rready(mb_rready),
        .m_awid(g_awid), .m_awaddr(g_awaddr), .m_awlen(g_awlen),
        .m_awsize(g_awsize), .m_awburst(g_awburst), .m_awvalid(g_awvalid),
        .m_awready(g_awready),
        .m_wdata(g_wdata), .m_wstrb(g_wstrb), .m_wlast(g_wlast),
        .m_wvalid(g_wvalid), .m_wready(g_wready),
        .m_bid(g_bid), .m_bresp(g_bresp), .m_bvalid(g_bvalid),
        .m_bready(g_bready),
        .m_arid(g_arid), .m_araddr(g_araddr), .m_arlen(g_arlen),
        .m_arsize(g_arsize), .m_arburst(g_arburst), .m_arvalid(g_arvalid),
        .m_arready(g_arready),
        .m_rid(g_rid), .m_rdata(g_rdata), .m_rresp(g_rresp),
        .m_rlast(g_rlast), .m_rvalid(g_rvalid), .m_rready(g_rready),
        .n_wr(bf_nwr), .n_wbeat(bf_nwbeat), .n_rd(bf_nrd),
        .n_rbeat(bf_nrbeat), .busy_wr(bf_bwr), .busy_rd(bf_brd),
        .n_dec(bf_ndec), .n_slverr(bf_nslv), .n_idmis(bf_nidm)
    );

    // burst MIs for matvec slots that are not elaborated: error sinks that
    // answer SLVERR, so an unexpected access is loud instead of hanging.
    for (genvar g = NMV; g < 4; g++) begin : g_bsink
        assign g_awready[g] = 1'b1;
        assign g_wready[g]  = 1'b1;
        assign g_bvalid[g]  = g_wvalid[g] && g_wlast[g];
        assign g_bresp[g]   = 2'b10;
        assign g_bid[g]     = 1'b0;
        assign g_arready[g] = 1'b1;
        assign g_rvalid[g]  = g_arvalid[g];
        assign g_rdata[g]   = 32'hDEAD_C0DE;
        assign g_rresp[g]   = 2'b10;
        assign g_rlast[g]   = 1'b1;
        assign g_rid[g]     = 1'b0;
    end

    seq_fabric_model #(.LAT(LAT), .NSLV(NSLV)) u_fab (
        .aclk(clk), .aresetn(rstn),
        .s_awaddr(m_awaddr), .s_awvalid(m_awvalid), .s_awready(m_awready),
        .s_wdata(m_wdata), .s_wstrb(m_wstrb), .s_wvalid(m_wvalid),
        .s_wready(m_wready), .s_bresp(m_bresp), .s_bvalid(m_bvalid),
        .s_bready(m_bready), .s_araddr(m_araddr), .s_arvalid(m_arvalid),
        .s_arready(m_arready), .s_rdata(m_rdata), .s_rresp(m_rresp),
        .s_rvalid(m_rvalid), .s_rready(m_rready),
        .m_awaddr(f_awaddr), .m_awvalid(f_awvalid), .m_awready(f_awready),
        .m_wdata(f_wdata), .m_wstrb(f_wstrb), .m_wvalid(f_wvalid),
        .m_wready(f_wready), .m_bresp(f_bresp), .m_bvalid(f_bvalid),
        .m_bready(f_bready), .m_araddr(f_araddr), .m_arvalid(f_arvalid),
        .m_arready(f_arready), .m_rdata(f_rdata), .m_rresp(f_rresp),
        .m_rvalid(f_rvalid), .m_rready(f_rready),
        .n_wr(fab_nwr), .n_rd(fab_nrd), .busy_wr(fab_bwr), .busy_rd(fab_brd)
    );

    seq_mem_file #(.ADDR_W(34), .DATA_W(128), .LAT(DDRLAT), .NREG(3),
                   .A0("seq"),  .S0(".seq"),         .B0(SEQ_STREAM_BASE),
                   .A1("seq"),  .S1(".seqdata.bin"), .B1(SEQ_DATA_BASE),
                   .A2("base"), .S2(".emb.bin"),     .B2(EMB_BASE),
                   .O2(1'b1)) u_ddr (
        .aclk(clk), .aresetn(rstn),
        .araddr(d_araddr), .arlen(d_arlen), .arsize(d_arsize),
        .arburst(d_arburst), .arvalid(d_arvalid), .arready(d_arready),
        .rdata(d_rdata), .rresp(d_rresp), .rlast(d_rlast), .rvalid(d_rvalid),
        .rready(d_rready), .n_beats(d_nbeats), .n_miss(d_nmiss)
    );

    // slave 0 (csr_block) and 6/7 plus every unbuilt matvec slot: sinks
    for (genvar g = 0; g < NSLV; g++) begin : g_tie
        if ((g == 0) || (g >= 6) || ((g >= 1) && (g <= 4) && (g > NMV))) begin : g_sink
            assign f_awready[g] = 1'b1;
            assign f_wready[g]  = 1'b1;
            assign f_bvalid[g]  = f_awvalid[g] && f_wvalid[g];
            assign f_bresp[g]   = 2'b00;
            assign f_arready[g] = 1'b1;
            assign f_rvalid[g]  = f_arvalid[g];
            assign f_rdata[g]   = 32'hDEAD_C0DE;
            assign f_rresp[g]   = 2'b00;
        end
    end

    // ---------------- REAL matvec channels ----------------
    for (genvar c = 0; c < NMV; c++) begin : g_mv
        logic [33:0]  w_araddr;
        logic [7:0]   w_arlen;
        logic [2:0]   w_arsize;
        logic [1:0]   w_arburst, w_rresp;
        logic         w_arvalid, w_arready, w_rlast, w_rvalid, w_rready;
        logic [511:0] w_rdata;

        matvec_chan #(.CHAN_ID(4'(c)), .ADDR_W(34)) u_mv (
            .aclk(clk), .aresetn(rstn),
            .s_axil_awaddr(f_awaddr[c+1]), .s_axil_awvalid(f_awvalid[c+1]),
            .s_axil_awready(f_awready[c+1]), .s_axil_wdata(f_wdata[c+1]),
            .s_axil_wstrb(f_wstrb[c+1]), .s_axil_wvalid(f_wvalid[c+1]),
            .s_axil_wready(f_wready[c+1]), .s_axil_bresp(f_bresp[c+1]),
            .s_axil_bvalid(f_bvalid[c+1]), .s_axil_bready(f_bready[c+1]),
            .s_axil_araddr(f_araddr[c+1]), .s_axil_arvalid(f_arvalid[c+1]),
            .s_axil_arready(f_arready[c+1]), .s_axil_rdata(f_rdata[c+1]),
            .s_axil_rresp(f_rresp[c+1]), .s_axil_rvalid(f_rvalid[c+1]),
            .s_axil_rready(f_rready[c+1]),
            .s_axib_awid(g_awid[c]), .s_axib_awaddr(g_awaddr[c]),
            .s_axib_awlen(g_awlen[c]), .s_axib_awsize(g_awsize[c]),
            .s_axib_awburst(g_awburst[c]), .s_axib_awvalid(g_awvalid[c]),
            .s_axib_awready(g_awready[c]), .s_axib_wdata(g_wdata[c]),
            .s_axib_wstrb(g_wstrb[c]), .s_axib_wlast(g_wlast[c]),
            .s_axib_wvalid(g_wvalid[c]), .s_axib_wready(g_wready[c]),
            .s_axib_bid(g_bid[c]), .s_axib_bresp(g_bresp[c]),
            .s_axib_bvalid(g_bvalid[c]), .s_axib_bready(g_bready[c]),
            .s_axib_arid(g_arid[c]), .s_axib_araddr(g_araddr[c]),
            .s_axib_arlen(g_arlen[c]), .s_axib_arsize(g_arsize[c]),
            .s_axib_arburst(g_arburst[c]), .s_axib_arvalid(g_arvalid[c]),
            .s_axib_arready(g_arready[c]), .s_axib_rid(g_rid[c]),
            .s_axib_rdata(g_rdata[c]), .s_axib_rresp(g_rresp[c]),
            .s_axib_rlast(g_rlast[c]), .s_axib_rvalid(g_rvalid[c]),
            .s_axib_rready(g_rready[c]),
            .ui_clk(ui_clk), .ui_rstn(ui_rstn),
            .m_axi_araddr(w_araddr), .m_axi_arlen(w_arlen),
            .m_axi_arsize(w_arsize), .m_axi_arburst(w_arburst),
            .m_axi_arvalid(w_arvalid), .m_axi_arready(w_arready),
            .m_axi_rdata(w_rdata), .m_axi_rresp(w_rresp),
            .m_axi_rlast(w_rlast), .m_axi_rvalid(w_rvalid),
            .m_axi_rready(w_rready)
        );

        seq_mem_file #(.ADDR_W(34), .DATA_W(512), .LAT(WLAT), .NREG(1),
                       .QD(4),
                       .A0("base"), .S0(".wimg.bin"), .B0(W_BASE)) u_wmem (
            .aclk(ui_clk), .aresetn(ui_rstn),
            .araddr(w_araddr), .arlen(w_arlen), .arsize(w_arsize),
            .arburst(w_arburst), .arvalid(w_arvalid), .arready(w_arready),
            .rdata(w_rdata), .rresp(w_rresp), .rlast(w_rlast),
            .rvalid(w_rvalid), .rready(w_rready),
            .n_beats(w_nbeats[c]), .n_miss(w_nmiss[c])
        );

    end
    for (genvar c = NMV; c < 4; c++) begin : g_mv_off
        assign w_nbeats[c] = 64'd0;
        assign w_nmiss[c]  = 64'd0;
    end

    // ---------------- the REAL layer engine ----------------
    layer_chan #(
        .RSQRT_ROM("../rtl/roms/rsqrt_rom.hex"),
        .SIGMOID_ROM("../rtl/roms/sigmoid_pair_rom.hex"),
        .SOFTPLUS_ROM("../rtl/roms/softplus_pair_rom.hex"),
        .EXP2_ROM("../rtl/roms/exp2_pair_rom.hex"),
        .RECIP_ROM("../rtl/roms/recip_rom.hex")
    ) u_layer (
        .aclk(clk), .aresetn(rstn),
        .s_axil_awaddr(f_awaddr[5]), .s_axil_awvalid(f_awvalid[5]),
        .s_axil_awready(f_awready[5]), .s_axil_wdata(f_wdata[5]),
        .s_axil_wstrb(f_wstrb[5]), .s_axil_wvalid(f_wvalid[5]),
        .s_axil_wready(f_wready[5]), .s_axil_bresp(f_bresp[5]),
        .s_axil_bvalid(f_bvalid[5]), .s_axil_bready(f_bready[5]),
        .s_axil_araddr(f_araddr[5]), .s_axil_arvalid(f_arvalid[5]),
        .s_axil_arready(f_arready[5]), .s_axil_rdata(f_rdata[5]),
        .s_axil_rresp(f_rresp[5]), .s_axil_rvalid(f_rvalid[5]),
        .s_axil_rready(f_rready[5]),
        .s_axib_awid(g_awid[4]), .s_axib_awaddr(g_awaddr[4]),
        .s_axib_awlen(g_awlen[4]), .s_axib_awsize(g_awsize[4]),
        .s_axib_awburst(g_awburst[4]), .s_axib_awvalid(g_awvalid[4]),
        .s_axib_awready(g_awready[4]), .s_axib_wdata(g_wdata[4]),
        .s_axib_wstrb(g_wstrb[4]), .s_axib_wlast(g_wlast[4]),
        .s_axib_wvalid(g_wvalid[4]), .s_axib_wready(g_wready[4]),
        .s_axib_bid(g_bid[4]), .s_axib_bresp(g_bresp[4]),
        .s_axib_bvalid(g_bvalid[4]), .s_axib_bready(g_bready[4]),
        .s_axib_arid(g_arid[4]), .s_axib_araddr(g_araddr[4]),
        .s_axib_arlen(g_arlen[4]), .s_axib_arsize(g_arsize[4]),
        .s_axib_arburst(g_arburst[4]), .s_axib_arvalid(g_arvalid[4]),
        .s_axib_arready(g_arready[4]), .s_axib_rid(g_rid[4]),
        .s_axib_rdata(g_rdata[4]), .s_axib_rresp(g_rresp[4]),
        .s_axib_rlast(g_rlast[4]), .s_axib_rvalid(g_rvalid[4]),
        .s_axib_rready(g_rready[4])
    );

    // ==================================================================
    // RUNG3: on the full-chip path EVERY burst response must be OKAY.
    // In particular a MOVY burst issued right after a CMD retires must not
    // take a spurious SLVERR from the layer shim's !busy gate (S6/R8) — the
    // model_v2 stream hits that race thousands of times, so make it fail
    // AT THE CYCLE IT HAPPENS rather than as a count at the end.
    // ==================================================================
    /* verilator lint_off BLKSEQ */
    always @(posedge clk) if (rstn) begin
        if (mb_bvalid && mb_bready && (mb_bresp != 2'b00))
            $fatal(1, "burst BRESP=%02b at t=%0t (layer/mvchan window rejected a write burst — CMD->MOVY race or window bounds)",
                   mb_bresp, $time);
        if (mb_rvalid && mb_rready && (mb_rresp != 2'b00))
            $fatal(1, "burst RRESP=%02b at t=%0t (layer/mvchan window rejected a read burst — CMD->MOVX race or window bounds)",
                   mb_rresp, $time);
    end
    /* verilator lint_on BLKSEQ */

    // ==================================================================
    // golden (<prefix>.chip)
    // ==================================================================
    int unsigned exp_mem_a [MAXMEM];
    int unsigned exp_mem_v [MAXMEM];
    int unsigned n_exp_mem;
    int unsigned exp_xrf [8];
    int unsigned exp_tok [4096];
    int unsigned n_exp_tok;
    int unsigned exp_tcnt0 [6];
    int unsigned exp_tcnt1 [6];
    int unsigned n_exp_tcnt;
    int unsigned exp_eout, exp_amaxi, exp_amaxv, exp_pc, exp_nrec;
    int unsigned have_eout, have_amax;

    // previous launch's post-state, re-checked just before the next START
    int unsigned prev_mem_a [MAXMEM];
    int unsigned prev_mem_v [MAXMEM];
    int unsigned n_prev_mem;
    int unsigned prev_tcnt0 [6];
    int unsigned prev_tcnt1 [6];
    int unsigned n_prev_tcnt;

    // per-launch descriptor
    int unsigned cur_off, cur_nrec, cur_idx, n_launch_exp;
    string       cur_kind;

    // RDWIN address-window read witnesses
    localparam int NRW = 4;
    logic [33:0] rw_lo [NRW];
    logic [33:0] rw_hi [NRW];
    int unsigned rw_min [NRW];
    int unsigned rw_max [NRW];
    int unsigned rw_n   [NRW];
    int unsigned n_rw;

    int    chip_fd;
    string seqp, basep;
    int    wdog_ms;

    // ------------------------------------------------------------------
    // read ONE launch section out of the (already open) .chip file.
    // A single-launch .chip has no LAUNCH/ENDL keys at all: it is simply
    // one section terminated by END, with NREC standing in for the
    // record count and offset 0.
    // ------------------------------------------------------------------
    task automatic read_section(output bit got, output bit last);
        int r;
        int unsigned a, b, d, e, nkey;
        string key;
        begin
            n_exp_mem = 0; n_exp_tok = 0; n_exp_tcnt = 0; n_rw = 0;
            exp_pc = 0; exp_eout = 0; exp_amaxi = 0; exp_amaxv = 0;
            have_eout = 0; have_amax = 0;
            for (int i = 0; i < 8; i++) exp_xrf[i] = 0;
            got = 1'b0; last = 1'b0; nkey = 0;
            forever begin
                r = $fscanf(chip_fd, "%s", key);
                if (r != 1) begin last = 1'b1; break; end       // EOF
                if (key == "END")  begin last = 1'b1; break; end
                if (key == "ENDL") break;
                nkey++;
                if (key == "NREC") begin
                    r = $fscanf(chip_fd, "%d", exp_nrec);
                    cur_nrec = exp_nrec; cur_off = 0;
                end else if (key == "NLAUNCH") begin
                    r = $fscanf(chip_fd, "%d", n_launch_exp);
                    nkey--;                     // a file header, not a section
                end else if (key == "LAUNCH") begin
                    r = $fscanf(chip_fd, "%d %d %d", cur_idx, cur_off,
                                cur_nrec);
                    exp_nrec = cur_nrec;
                end else if (key == "KIND") begin
                    r = $fscanf(chip_fd, "%s", cur_kind);
                end else if (key == "PC") begin
                    r = $fscanf(chip_fd, "%d", exp_pc);
                end else if (key == "EOUT") begin
                    r = $fscanf(chip_fd, "%h", exp_eout); have_eout = 1;
                end else if (key == "AMAX") begin
                    r = $fscanf(chip_fd, "%h %h", exp_amaxi, exp_amaxv);
                    have_amax = 1;
                end else if (key == "XRF") begin
                    r = $fscanf(chip_fd, "%d %h", a, d);
                    exp_xrf[a[2:0]] = d;
                end else if (key == "TOK") begin
                    r = $fscanf(chip_fd, "%h", d);
                    exp_tok[n_exp_tok] = d; n_exp_tok++;
                end else if (key == "TCNT") begin
                    r = $fscanf(chip_fd, "%d %d %d", a, b, d);
                    exp_tcnt0[a[2:0]] = b; exp_tcnt1[a[2:0]] = d;
                    if (a >= n_exp_tcnt) n_exp_tcnt = a + 1;
                end else if (key == "RDWIN") begin
                    r = $fscanf(chip_fd, "%h %h %d %d", a, b, d, e);
                    if (n_rw >= NRW) $fatal(1, "too many RDWIN lines");
                    rw_lo[n_rw] = {2'd0, a}; rw_hi[n_rw] = {2'd0, b};
                    rw_min[n_rw] = d; rw_max[n_rw] = e;
                    n_rw++;
                end else if (key == "MEM") begin
                    r = $fscanf(chip_fd, "%h %h", a, d);
                    if (n_exp_mem >= MAXMEM) $fatal(1, "too many MEM lines");
                    exp_mem_a[n_exp_mem] = a; exp_mem_v[n_exp_mem] = d;
                    n_exp_mem++;
                end else if (key == "BASES") begin
                    // stream / blob / emb / weights — checked against the
                    // localparams above so a generator change cannot drift
                    r = $fscanf(chip_fd, "%h %h %h %h", a, b, d, e);
                    if ({32'd0, a} !== SEQ_STREAM_BASE
                        || {32'd0, b} !== SEQ_DATA_BASE
                        || {32'd0, d} !== EMB_BASE
                        || {32'd0, e} !== W_BASE)
                        $fatal(1, "BASES %08h/%08h/%08h/%08h disagree with the TB DDR plan", a, b, d, e);
                    nkey--;                     // a file header, not a section
                end else $fatal(1, "bad key '%s' in the .chip file", key);
            end
            got = (nkey != 0);
        end
    endtask

    // ==================================================================
    // host BFM (drive/sample at NEGEDGE only — TB discipline)
    // ==================================================================
    task automatic hwr(input int unsigned addr, input int unsigned data);
        begin
            @(negedge clk);
            h_awaddr = addr[11:0]; h_awvalid = 1'b1;
            h_wdata  = data;       h_wvalid  = 1'b1;
            h_bready = 1'b1;
            while (!(h_awready && h_wready)) @(negedge clk);
            @(negedge clk);
            h_awvalid = 1'b0; h_wvalid = 1'b0;
            while (!h_bvalid) @(negedge clk);
            @(negedge clk);
            h_bready = 1'b0;
        end
    endtask

    task automatic hrd(input int unsigned addr, output int unsigned data);
        begin
            @(negedge clk);
            h_araddr = addr[11:0]; h_arvalid = 1'b1; h_rready = 1'b1;
            while (!h_arready) @(negedge clk);
            @(negedge clk);
            h_arvalid = 1'b0;
            while (!h_rvalid) @(negedge clk);
            data = h_rdata;
            @(negedge clk);
            h_rready = 1'b0;
        end
    endtask

    // ==================================================================
    // continuous "the DUT was NEVER reset mid-run" assertion.  Gate I1's
    // whole claim is that a second START preserves context, so a reset
    // sneaking in would silently invalidate it.
    // ==================================================================
    logic rst_armed = 1'b0;
    always @(negedge clk) begin
        if (rst_armed && !(rstn && ui_rstn))
            $fatal(1, "DUT reset deasserted mid-run (rstn=%b ui_rstn=%b) — multi-launch continuity claim is void", rstn, ui_rstn);
    end

    // ------------------------------------------------------------------
    // RDWIN witnesses: count seq_unit DDR read BURSTS landing in a window.
    // Sampled at NEGEDGE (TB discipline): the AR handshake values in effect
    // at negedge N are the ones the DUT captures at posedge N+1, so every
    // accepted burst is counted exactly once.
    // ------------------------------------------------------------------
    logic rw_clr = 1'b0;
    always @(negedge clk) begin
        if (rw_clr) begin
            for (int k = 0; k < NRW; k++) rw_n[k] <= 32'd0;
        end else if (rstn && d_arvalid && d_arready) begin
            for (int k = 0; k < NRW; k++) begin
                if ((k < int'(n_rw)) && (d_araddr >= rw_lo[k])
                    && (d_araddr < rw_hi[k]))
                    rw_n[k] <= rw_n[k] + 32'd1;
            end
        end
    end

    // ==================================================================
    int unsigned cyc_start, cyc_end;

    initial begin
        /* verilator lint_off UNUSEDSIGNAL */
        int unsigned v, tok, nerr;
        /* verilator lint_on UNUSEDSIGNAL */
        int unsigned t_pc, t_st;
        int unsigned li, tot_tok, tot_cyc, lcyc;
        bit got, last;
        real cyc, recs;
        logic [63:0] lbase;

        h_awaddr = 0; h_awvalid = 0; h_wdata = 0; h_wvalid = 0; h_bready = 0;
        h_araddr = 0; h_arvalid = 0; h_rready = 0;
        nerr = 0; li = 0; tot_tok = 0; tot_cyc = 0;
        cur_off = 0; cur_nrec = 0; cur_idx = 0; cur_kind = "-";
        n_launch_exp = 1; n_prev_mem = 0; n_prev_tcnt = 0;
        for (int k = 0; k < NRW; k++) begin
            rw_lo[k] = '0; rw_hi[k] = '0;
            rw_min[k] = 0; rw_max[k] = 0;
        end
        n_rw = 0;

        if (!$value$plusargs("seq=%s", seqp)) $fatal(1, "need +seq=<prefix>");
        if (!$value$plusargs("base=%s", basep)) basep = seqp;
        if (!$value$plusargs("watchdog_ms=%d", wdog_ms)) wdog_ms = 600000;

        chip_fd = $fopen({seqp, ".chip"}, "r");
        if (chip_fd == 0) $fatal(1, "cannot open %s.chip", seqp);

        repeat (16) @(negedge clk);
        rstn    = 1'b1;
        ui_rstn = 1'b1;
        repeat (8) @(negedge clk);
        rst_armed = 1'b1;                  // from here on, no reset is legal

        hrd(32'h28, v);
        if (v !== 32'hFAB1_E5E0) $fatal(1, "SEQ IDENT = %08h", v);

        // ==============================================================
        // one iteration per launch section; the DUT is NEVER reset again
        // ==============================================================
        forever begin
            read_section(got, last);
            if (!got) break;

            $display("tb_seq_chip: launch %0d [%s] rec_off %0d, %0d records, %0d tokens, %0d scratch words, NMV=%0d LAT=%0d DDRLAT=%0d WLAT=%0d",
                     li, cur_kind, cur_off, cur_nrec,
                     n_exp_tok, n_exp_mem, NMV, LAT, DDRLAT, WLAT);

            // ---- the previous launch's state must still be there -------
            if (li != 0) begin
                int unsigned ncarry;
                ncarry = 0;
                for (int s = 0; s < int'(n_prev_tcnt); s++) begin
                    if ({22'd0, u_layer.tcnt_bank[s][0]} !== prev_tcnt0[s]
                        || {22'd0, u_layer.tcnt_bank[s][1]} !== prev_tcnt1[s])
                        begin
                        $display("CARRY TCNT[%0d] = %0d/%0d, expected %0d/%0d",
                                 s, u_layer.tcnt_bank[s][0],
                                 u_layer.tcnt_bank[s][1],
                                 prev_tcnt0[s], prev_tcnt1[s]);
                        nerr++;
                    end else ncarry++;
                end
                for (int i = 0; i < int'(n_prev_mem); i++) begin
                    v = {16'd0, u_layer.smem_a[prev_mem_a[i][13:0]]}
                        & 32'hFFFF;
                    if (v !== (prev_mem_v[i] & 32'hFFFF)) begin
                        $display("CARRY MEM[%04h] = %04h, expected %04h",
                                 prev_mem_a[i], v, prev_mem_v[i] & 32'hFFFF);
                        nerr++;
                        if (nerr > 20) $fatal(1, "too many carry mismatches");
                    end else ncarry++;
                end
                if (nerr != 0)
                    $fatal(1, "%0d state word(s) did NOT survive to launch %0d",
                           nerr, li);
                $display("  carried into launch %0d: %0d state words (%0d TCNT banks + %0d scratch) still intact BEFORE START",
                         li, ncarry, n_prev_tcnt, n_prev_mem);
            end

            // ---- drain check + program + START, exactly as the host does
            // (sw/seq_run.seq_start_and_poll: XRF and TCNT_SEQ zeroed, then
            //  BASE/LEN/ENTRY, then CTRL.START) ---------------------------
            hrd(32'h1C, v);
            if (v != 32'd0) begin
                $display("OUT FIFO not drained before launch %0d (%0d)", li, v);
                nerr++;
            end
            lbase = 64'(SEQ_STREAM_BASE) + ({32'd0, cur_off} << 4);
            hwr(32'h08, lbase[31:0]);
            hwr(32'h0C, {30'd0, lbase[33:32]});
            hwr(32'h10, cur_nrec);
            hwr(32'h24, 32'h0);                      // ENTRY
            hwr(32'h20, 32'd0);                      // TCNT_SEQ
            for (int i = 0; i < 8; i++) hwr(32'h40 + 4 * i, 32'd0);

            @(negedge clk); rw_clr = 1'b1;
            @(negedge clk); rw_clr = 1'b0;
            @(negedge clk);
            cyc_start = int'($time / 4);
            hwr(32'h00, 32'h1);                      // START

            begin
                int unsigned guard;
                guard = 0;
                forever begin
                    hrd(32'h04, t_st);
                    if (t_st[2]) break;              // halted
                    if (t_st[1]) begin
                        hrd(32'h14, t_pc);
                        $fatal(1, "SEQ err_code %02h at pc %0d (STATUS %08h)",
                               t_st[31:24], t_pc, t_st);
                    end
                    guard++;
                    if (guard > 100_000_000)
                        $fatal(1, "SEQ never halted (STATUS %08h)", t_st);
                end
            end
            cyc_end = int'($time / 4);
            lcyc = cyc_end - cyc_start;
            tot_cyc = tot_cyc + lcyc;
            hrd(32'h14, t_pc);

            // ---------------- status ----------------
            if (t_st[31:24] != 8'd0)
                $fatal(1, "err_code %02h (STATUS %08h)", t_st[31:24], t_st);
            if (t_st[1]) $fatal(1, "unexpected err flag");
            if (t_pc !== exp_pc)
                $fatal(1, "launch %0d final pc %0d, expected %0d", li, t_pc,
                       exp_pc);

            // ---------------- XRF (SEQ CSR block) ----------------
            for (int i = 0; i < 8; i++) begin
                hrd(32'h40 + 4 * i, v);
                if (v[17:0] !== exp_xrf[i][17:0]) begin
                    $display("XRF[%0d] = %05h, expected %05h", i, v[17:0],
                             exp_xrf[i][17:0]);
                    nerr++;
                end
            end

            // ---------------- OUT FIFO tokens ----------------
            for (int i = 0; i < int'(n_exp_tok); i++) begin
                hrd(32'h18, tok);
                if (!tok[31]) $fatal(1, "OUT FIFO empty at token %0d", i);
                if (tok[17:0] !== exp_tok[i][17:0]) begin
                    $display("TOK[%0d] = %05h, expected %05h", i, tok[17:0],
                             exp_tok[i][17:0]);
                    nerr++;
                end else begin
                    $display("  TOK[%0d] = %05h (%0d) == golden OK", i,
                             tok[17:0], tok[17:0]);
                end
            end
            hrd(32'h1C, v);
            if (v != 32'd0) begin
                $display("OUT FIFO still holds %0d entries", v);
                nerr++;
            end
            tot_tok = tot_tok + n_exp_tok;

            // ---------------- banked layer state ----------------
            // The SEQ CSR block (0x00..0x5C above) is read through the DUT's
            // real AXI-Lite slave, exactly as the host does on silicon.  The
            // LAYER engine's own CSRs are NOT reachable from here: in this
            // testbench layer_chan's only AXI-Lite port is the fabric port
            // the sequencer owns, and the ISA forbids a second master
            // touching it while SEQ is busy.  Its architectural state is
            // therefore compared through hierarchical probes of the SAME
            // registers those CSRs return (0x20 TCNT -> tcnt_bank,
            // 0x1C EOUT -> eout_q, 0x28/0x2C AMAXI/AMAXV ->
            // alu_amax_idx/val).
            for (int s = 0; s < int'(n_exp_tcnt); s++) begin
                if ({22'd0, u_layer.tcnt_bank[s][0]} !== exp_tcnt0[s]
                    || {22'd0, u_layer.tcnt_bank[s][1]} !== exp_tcnt1[s]) begin
                    $display("TCNT[kv %0d] = %0d/%0d, expected %0d/%0d", s,
                             u_layer.tcnt_bank[s][0], u_layer.tcnt_bank[s][1],
                             exp_tcnt0[s], exp_tcnt1[s]);
                    nerr++;
                end
            end
            if (have_eout != 0) begin
                if ({28'd0, u_layer.eout_q} !== exp_eout) begin
                    $display("EOUT = %0d, expected %0d", u_layer.eout_q,
                             exp_eout);
                    nerr++;
                end
            end
            if (have_amax != 0) begin
                if (u_layer.alu_amax_idx !== exp_amaxi[17:0]) begin
                    $display("AMAXI = %05h, expected %05h",
                             u_layer.alu_amax_idx, exp_amaxi[17:0]);
                    nerr++;
                end
                if (unsigned'(u_layer.alu_amax_val) !== exp_amaxv) begin
                    $display("AMAXV = %08h, expected %08h",
                             u_layer.alu_amax_val, exp_amaxv);
                    nerr++;
                end
            end

            // ---------------- final scratchpad ----------------
            for (int i = 0; i < int'(n_exp_mem); i++) begin
                v = {16'd0, u_layer.smem_a[exp_mem_a[i][13:0]]} & 32'hFFFF;
                if (v !== (exp_mem_v[i] & 32'hFFFF)) begin
                    $display("MEM[%04h] = %04h, expected %04h",
                             exp_mem_a[i], v, exp_mem_v[i] & 32'hFFFF);
                    nerr++;
                    if (nerr > 20) $fatal(1, "too many scratch mismatches");
                end
            end

            // ---------------- DDR read-window witnesses ----------------
            for (int k = 0; k < int'(n_rw); k++) begin
                if (rw_n[k] < rw_min[k] || rw_n[k] > rw_max[k]) begin
                    $display("RDWIN[%0d] %08h..%08h saw %0d bursts, expected %0d..%0d",
                             k, rw_lo[k], rw_hi[k], rw_n[k],
                             rw_min[k], rw_max[k]);
                    nerr++;
                end else begin
                    $display("  RDWIN %08h..%08h: %0d burst(s) (want %0d..%0d) OK",
                             rw_lo[k], rw_hi[k], rw_n[k], rw_min[k],
                             rw_max[k]);
                end
            end

            if (nerr != 0) $fatal(1, "launch %0d: %0d comparison failures",
                                  li, nerr);

            // ---------------- keep this launch's state as the carry ----
            n_prev_tcnt = n_exp_tcnt;
            for (int s = 0; s < int'(n_exp_tcnt); s++) begin
                prev_tcnt0[s] = exp_tcnt0[s]; prev_tcnt1[s] = exp_tcnt1[s];
            end
            n_prev_mem = n_exp_mem;
            for (int i = 0; i < int'(n_exp_mem); i++) begin
                prev_mem_a[i] = exp_mem_a[i]; prev_mem_v[i] = exp_mem_v[i];
            end

            // ---------------- performance ----------------
            cyc  = real'(lcyc);
            recs = real'(cur_nrec);
            hrd(32'h2C, v);
            $display("SEQ-CHIP %s launch %0d [%s]: %0d records, %0d cycles (%0.2f cyc/rec, %0.3f ms @250MHz, PERF_CYC %0d)",
                     seqp, li, cur_kind, cur_nrec, lcyc, cyc / recs,
                     cyc / 250000.0, v);
            $display("LAUNCH %0d PASS: [%s] pc %0d, tokens %0d, tcnt %0d, scratch %0d",
                     li, cur_kind, exp_pc, n_exp_tok,
                     n_exp_tcnt, n_exp_mem);
            li++;
            if (last) break;
        end
        $fclose(chip_fd);
        if (li == 0) $fatal(1, "%s.chip held no launch sections", seqp);
        if (li != n_launch_exp && n_launch_exp != 0)
            $fatal(1, "ran %0d launches, .chip declared %0d", li,
                   n_launch_exp);

        if (d_nmiss != 0) begin
            $display("record/const/emb DDR served %0d UNMAPPED beats", d_nmiss);
            nerr++;
        end
        if (nerr != 0) $fatal(1, "%0d comparison failures", nerr);

        hrd(32'h34, v); $display("  axil writes %0d", v);
        hrd(32'h38, v); $display("  axil reads  %0d", v);
        $display("  burst: %0d write bursts (%0d beats), %0d read bursts (%0d beats), busy_wr %0d busy_rd %0d, decerr %0d non-OK %0d, BLAT=%0d",
                 bf_nwr, bf_nwbeat, bf_nrd, bf_nrbeat, bf_bwr, bf_brd,
                 bf_ndec, bf_nslv, BLAT);
        if (bf_ndec != 32'd0)
            $fatal(1, "%0d burst decode holes (the S4 map is wrong)", bf_ndec);
        if (bf_nslv != 32'd0)
            $fatal(1, "%0d non-OK burst responses (SLVERR/DECERR on the data path)",
                   bf_nslv);
        if (bf_nidm != 32'd0)
            $fatal(1, "%0d burst id-echo mismatches", bf_nidm);
        hrd(32'h3C, v); $display("  fetch-empty stall cycles %0d", v[31:1]);
        $display("  ddr beats %0d (miss %0d), weight beats %0d (miss %0d)",
                 d_nbeats, d_nmiss, w_nbeats[0], w_nmiss[0]);
        $display("  DUT held in reset 0 times after t=0 (rst_armed asserted before launch 0, never violated)");
        // n_prev_* hold the LAST launch's checked counts (the exp_* arrays
        // were cleared by the terminating read_section call).
        $display("TB_SEQ_CHIP PASS: %s (launches %0d, %0d cycles total, scratch %0d/launch, tokens %0d, tcnt %0d)",
                 seqp, li, tot_cyc, n_prev_mem, tot_tok, n_prev_tcnt);
        $finish;
    end

    // watchdog (simulated wall-clock, like tb_layer_chan)
    initial begin
        int wd_ms;
        wd_ms = 600000;
        void'($value$plusargs("watchdog_ms=%d", wd_ms));
        #(wd_ms * 1ms);
        $display("WATCHDOG (%0d ms): seq pc probe busy=%0b halted=%0b err=%0b",
                 wd_ms, seq_busy, seq_halted, seq_err);
        $fatal(1, "tb_seq_chip: watchdog");
    end

endmodule

`default_nettype wire
