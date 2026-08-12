// tb_seq_unit — unit TB for rtl/seq_unit.sv + rtl/seq_movers.sv.
//
// The DUT is wired exactly the way create_project.tcl wires it on the
// board, with simulation models standing in for the pieces that are not
// under test:
//
//   seq_unit.m_axil -> seq_fabric_model (LAT cycles each way, pipelined,
//                      in-order) -> seq_stub_mvchan x4 @0x1000..0x4000
//                                -> seq_stub_layer     @0x5000
//   seq_unit.m_axib -> seq_burst_fabric (BLAT cycles each way, AXI4 1x5,
//                      RUNG3 S4 map) -> the SAME four stubs' s_axib
//                      windows @0x1_0000..0x4_0000 and the layer's
//                      @0x5_0000
//   seq_unit.m_axi  -> seq_ddr_model (record stream + LDC blob + embeddings)
//   seq_unit.s_axil <- the TB acting as the host (START / STATUS / OUT FIFO)
//
// RUNG 3 AND THE GOLDEN TRACES.  rtl/seq_movers.sv moved the MOVX / MOVY /
// LDC / EMB DATA STREAMS off AXI-Lite onto m_axib; the setup CSR writes
// (MOVX SPTR+XPTR, MVGO WBASE/BEATS/SHAPE/doorbell, MOVY RES_PTR+SPTR) and
// every poll stayed exactly where they were.  The .wtr / .rtr goldens are
// therefore still valid AS AN ORDERED PER-DIRECTION LIST once each burst
// BEAT is CANONICALISED back to the AXI-Lite transaction it replaced:
//
//   burst write, slot 5      -> LAYER + SWIN   (the scratch word)
//   burst write, slot 1..4   -> MV(c) + XWIN   (the packed x word)
//   burst read,  slot 5      -> LAYER + SWIN   (the scratch word)
//   burst read,  slot 1..4   -> MV(c) + RES_DATA
//
// and merged with the AXI-Lite stream in issue order.  That merge is exact
// because seq_movers drains its burst write engine before the next record's
// CSR traffic (seq_movers C3), so the two channels never interleave within
// a record.  This keeps the golden generator (tb/scripts/gen_seq_unit_
// vectors.py) UNCHANGED and makes the check TRANSPORT-AGNOSTIC: it pins the
// architectural effect (which word, which value, in which order) without
// pinning the mover's burst segmentation, which S7 leaves free.
//
// The stubs mirror the SHIPPED CSR semantics of layer_chan / matvec_chan,
// including the two timing hazards seq_movers guards against (RES_DATA
// 2-cycle BRAM latency; sticky STATUS.done across the doorbell CDC), so a
// sequencer that talks to them too fast fails here rather than on silicon.
//
// GOLDEN.  tb/scripts/gen_seq_unit_vectors.py builds each stream with
// ref/seq_format.py (the wire truth: pack/validate/resolve_imm, and for the
// pure-ISA subset it is cross-checked against ref/seq_model.py's executor)
// and emits, for the same stream, the EXACT AXI-Lite transaction lists the
// sequencer must produce plus the final architectural state.  This TB
// checks, on the fly:
//
//   * every AXI-Lite WRITE (address + data), in order
//   * every AXI-Lite READ (address), in order, excluding the STATUS polls
//     (0x?004), whose count depends on timing
//   * the layer scratchpad contents, the XRF, the OUT FIFO token list,
//     the halt/err status and err_code, and the final PC
//
// and reports the issue rate (records/s, AXI-Lite ops/record, cycles/record)
// that feeds the rung-1 wall-clock projection.
//
// Run: obj_dir_tb_seq/tb_seq +vec=scripts/seq_u_s1 [+maxcyc=N] [+quiet]

`timescale 1ns/1ps
`default_nettype none

module tb_seq_unit #(
    parameter int LAT      = 4,       // AXI-Lite fabric latency each way
    parameter int BLAT     = 4,       // burst fabric latency each way
    parameter int DDRLAT   = 32,      // DDR first-word latency
    parameter bit SIDEBAND = 1'b0,    // XRF refresh: 0 = AXI-Lite, 1 = port
    parameter int RESGAP   = 3        // retired by rung 3 (kept for compat)
);
    localparam int NSLV = 8;
    localparam int NBSLV = 5;         // burst fabric MIs (RUNG3 S2)
    localparam int MAXTR = 400000;

    logic clk = 1'b0;
    logic rstn = 1'b0;
    /* verilator lint_off BLKSEQ */
    always #2 clk = ~clk;                       // 250 MHz
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

    // ---------------- DUT <-> DDR ----------------
    logic [33:0]  d_araddr;
    logic [7:0]   d_arlen;
    logic [2:0]   d_arsize;
    logic [1:0]   d_arburst, d_rresp;
    logic         d_arvalid, d_arready, d_rlast, d_rvalid, d_rready;
    logic [127:0] d_rdata;
    logic [31:0]  d_nbeats;

    // ---------------- host (s_axil) ----------------
    logic [11:0] h_awaddr, h_araddr;
    logic [31:0] h_wdata, h_rdata;
    logic        h_awvalid, h_awready, h_wvalid, h_wready, h_bvalid, h_bready;
    logic        h_arvalid, h_arready, h_rvalid, h_rready;
    logic [1:0]  h_bresp, h_rresp;

    logic        sb_we;
    logic [2:0]  sb_idx;
    logic [17:0] sb_data;
    logic [31:0] layer_ncmd;
    logic [31:0] mv_nrun [4];

    logic seq_busy, seq_halted, seq_err;
    /* verilator lint_on UNUSEDSIGNAL */

    // ==================================================================
    seq_unit #(
        .ADDR_W(34), .RES_GAP(RESGAP), .USE_XRF_SIDEBAND(SIDEBAND),
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

        .xrf_sb_we(sb_we), .xrf_sb_idx(sb_idx), .xrf_sb_data(sb_data),
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

    seq_ddr_model #(.ADDR_W(34), .LAT(DDRLAT), .MEM_WORDS(65536)) u_ddr (
        .aclk(clk), .aresetn(rstn),
        .araddr(d_araddr), .arlen(d_arlen), .arsize(d_arsize),
        .arburst(d_arburst), .arvalid(d_arvalid), .arready(d_arready),
        .rdata(d_rdata), .rresp(d_rresp), .rlast(d_rlast), .rvalid(d_rvalid),
        .rready(d_rready), .n_beats(d_nbeats)
    );

    // slave 0 (csr_block) and 6/7: always-ready sinks (never addressed)
    for (genvar g = 0; g < NSLV; g++) begin : g_tie
        if ((g == 0) || (g >= 6)) begin : g_sink
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

    for (genvar c = 0; c < 4; c++) begin : g_mv
        seq_stub_mvchan #(.CHAN_ID(4'(c))) u_mv (
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
            .n_run(mv_nrun[c])
        );
    end

    seq_stub_layer #(.XRFI_OFF(12'h038), .XRFD_OFF(12'h03C)) u_layer (
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
        .s_axib_rready(g_rready[4]),
        .n_cmd(layer_ncmd),
        .xrf_sb_we(sb_we), .xrf_sb_idx(sb_idx), .xrf_sb_data(sb_data)
    );

    // ==================================================================
    // expected traces
    // ==================================================================
    int unsigned exp_waddr [MAXTR];
    int unsigned exp_wdata [MAXTR];
    int unsigned exp_raddr [MAXTR];
    int unsigned n_exp_w, n_exp_r;
    int unsigned got_w, got_r;
    int unsigned n_poll;

    int unsigned exp_mem_a [MAXTR];
    int unsigned exp_mem_v [MAXTR];
    int unsigned n_exp_mem;
    int unsigned exp_xrf [8];
    int unsigned exp_tok [1024];
    int unsigned n_exp_tok;
    int unsigned exp_err, exp_pc, exp_nrec;

    string vec;
    int    maxcyc;

    // the AXI-Lite CSR offsets the burst canonicaliser maps back to
    // (tb/scripts/gen_seq_unit_vectors.py: LAYER / MV(c) / L_SWIN / XWIN)
    localparam int unsigned LAYER_BASE_TB = 32'h0000_5000;
    localparam int unsigned L_SWIN_TB     = 32'h0000_0018;
    localparam int unsigned MV_XWIN_TB    = 32'h0000_0024;
    localparam int unsigned MV_RESDAT_TB  = 32'h0000_0030;

    function automatic bit is_poll(input int unsigned a);
        is_poll = ((a & 32'hFFFF_0FFF) == 32'h0000_0004)
                  && ((a >> 12) >= 32'd1) && ((a >> 12) <= 32'd5);
    endfunction

    task automatic load_vectors(input string base);
        int fd, r;
        int unsigned a, d;
        string key;
        begin
            n_exp_w = 0; n_exp_r = 0; n_exp_mem = 0; n_exp_tok = 0;
            exp_err = 0; exp_pc = 0; exp_nrec = 0;
            for (int i = 0; i < 8; i++) exp_xrf[i] = 0;

            fd = $fopen(SIDEBAND ? {base, ".sb.wtr"} : {base, ".wtr"},
                        "r");
            if (fd == 0) $fatal(1, "cannot open %s .wtr", base);
            forever begin
                r = $fscanf(fd, "%h %h\n", a, d);
                if (r != 2) break;
                exp_waddr[n_exp_w] = a; exp_wdata[n_exp_w] = d;
                n_exp_w++;
            end
            $fclose(fd);

            fd = $fopen(SIDEBAND ? {base, ".sb.rtr"} : {base, ".rtr"},
                        "r");
            if (fd == 0) $fatal(1, "cannot open %s .rtr", base);
            forever begin
                r = $fscanf(fd, "%h\n", a);
                if (r != 1) break;
                exp_raddr[n_exp_r] = a;
                n_exp_r++;
            end
            $fclose(fd);

            fd = $fopen({base, ".exp"}, "r");
            if (fd == 0) $fatal(1, "cannot open %s.exp", base);
            forever begin
                r = $fscanf(fd, "%s", key);
                if (r != 1) break;
                if (key == "END") break;
                else if (key == "NREC") begin
                    r = $fscanf(fd, "%d", exp_nrec);
                end else if (key == "ERR") begin
                    r = $fscanf(fd, "%d", exp_err);
                end else if (key == "PC") begin
                    r = $fscanf(fd, "%d", exp_pc);
                end else if (key == "XRF") begin
                    r = $fscanf(fd, "%d %h", a, d);
                    exp_xrf[a[2:0]] = d;
                end else if (key == "TOK") begin
                    r = $fscanf(fd, "%h", d);
                    exp_tok[n_exp_tok] = d; n_exp_tok++;
                end else if (key == "MEM") begin
                    r = $fscanf(fd, "%h %h", a, d);
                    exp_mem_a[n_exp_mem] = a; exp_mem_v[n_exp_mem] = d;
                    n_exp_mem++;
                end else $fatal(1, "bad key '%s' in %s.exp", key, base);
            end
            $fclose(fd);
        end
    endtask

    // ==================================================================
    // on-the-fly trace comparison — AXI-Lite transactions and CANONICALISED
    // m_axib burst beats, merged in issue order (see the header).
    // ==================================================================
    // burst descriptor queues: AXI orders W beats by AW order and R beats by
    // AR order, so a plain FIFO of (address, beats) reconstructs the address
    // of every beat.
    localparam int BQD = 32;
    int unsigned bw_qa [BQD], bw_qn [BQD];
    int unsigned br_qa [BQD], br_qn [BQD];
    int unsigned bw_wp, bw_rp, br_wp, br_rp;
    int unsigned bw_addr, bw_left, br_addr, br_left;
    int unsigned n_bw_beat, n_br_beat, n_hi16;

    // canonical AXI-Lite equivalent of a burst address
    function automatic int unsigned canon_w(input int unsigned a);
        int unsigned slot;
        begin
            slot = (a >> 16) & 32'h7;
            if (slot == 32'd5) canon_w = LAYER_BASE_TB + L_SWIN_TB;
            else               canon_w = (slot << 12) + MV_XWIN_TB;
        end
    endfunction

    function automatic int unsigned canon_r(input int unsigned a);
        int unsigned slot;
        begin
            slot = (a >> 16) & 32'h7;
            if (slot == 32'd5) canon_r = LAYER_BASE_TB + L_SWIN_TB;
            else               canon_r = (slot << 12) + MV_RESDAT_TB;
        end
    endfunction

    /* verilator lint_off BLKSEQ */
    task automatic take_w(input int unsigned a, input int unsigned d);
        begin
            if (got_w >= n_exp_w)
                $fatal(1, "WRITE #%0d beyond the expected %0d: %08h <= %08h",
                       got_w, n_exp_w, a, d);
            if (a !== exp_waddr[got_w] || d !== exp_wdata[got_w])
                $fatal(1, "WRITE #%0d mismatch: got %08h <= %08h, want %08h <= %08h",
                       got_w, a, d, exp_waddr[got_w], exp_wdata[got_w]);
            got_w++;
        end
    endtask

    task automatic take_r(input int unsigned a);
        begin
            if (got_r >= n_exp_r)
                $fatal(1, "READ #%0d beyond the expected %0d: %08h",
                       got_r, n_exp_r, a);
            if (a !== exp_raddr[got_r])
                $fatal(1, "READ #%0d mismatch: got %08h, want %08h",
                       got_r, a, exp_raddr[got_r]);
            got_r++;
        end
    endtask

    always @(posedge clk) if (rstn) begin
        // ---- AXI-Lite (setup CSR writes, polls, register reads) ----
        if (m_awvalid && m_awready && m_wvalid && m_wready)
            take_w(m_awaddr, m_wdata);
        if (m_arvalid && m_arready) begin
            if (is_poll(m_araddr)) n_poll++;
            else take_r(m_araddr);
        end

        // ---- m_axib: capture burst descriptors ----
        if (mb_awvalid && mb_awready) begin
            bw_qa[bw_wp % BQD] = mb_awaddr;
            bw_qn[bw_wp % BQD] = {24'd0, mb_awlen} + 32'd1;
            bw_wp++;
            if (((mb_awaddr >> 16) & 32'h7) == 32'd5) begin
                if (mb_awaddr[15:0] > 16'hFFFC)
                    $fatal(1, "burst AW %08h outside the layer scratch window",
                           mb_awaddr);
            end else if ((mb_awaddr[15:12] !== 4'h4))
                $fatal(1, "burst AW %08h outside the mvchan XWIN window",
                       mb_awaddr);
        end
        if (mb_arvalid && mb_arready) begin
            br_qa[br_wp % BQD] = mb_araddr;
            br_qn[br_wp % BQD] = {24'd0, mb_arlen} + 32'd1;
            br_wp++;
            if (((mb_araddr >> 16) & 32'h7) != 32'd5)
                if (mb_araddr[15:14] !== 2'b00)
                    $fatal(1, "burst AR %08h outside the mvchan RES window",
                           mb_araddr);
        end

        // ---- m_axib W beats -> canonical AXI-Lite writes ----
        if (mb_wvalid && mb_wready) begin
            if (bw_left == 0) begin
                if (bw_rp == bw_wp) $fatal(1, "burst W beat with no AW");
                bw_addr = bw_qa[bw_rp % BQD];
                bw_left = bw_qn[bw_rp % BQD];
                bw_rp++;
            end
            // the layer scratch is 16 bits wide; the golden records the
            // 16-bit value, so compare that (and report any set upper bits).
            if (((bw_addr >> 16) & 32'h7) == 32'd5) begin
                if ((mb_wdata >> 16) != 32'd0) n_hi16++;
                take_w(canon_w(bw_addr), mb_wdata & 32'h0000_FFFF);
            end else
                take_w(canon_w(bw_addr), mb_wdata);
            bw_addr = bw_addr + 32'd4;
            bw_left = bw_left - 32'd1;
            n_bw_beat++;
        end

        // ---- m_axib R beats -> canonical AXI-Lite reads ----
        if (mb_rvalid && mb_rready) begin
            if (br_left == 0) begin
                if (br_rp == br_wp) $fatal(1, "burst R beat with no AR");
                br_addr = br_qa[br_rp % BQD];
                br_left = br_qn[br_rp % BQD];
                br_rp++;
            end
            take_r(canon_r(br_addr));
            br_addr = br_addr + 32'd4;
            br_left = br_left - 32'd1;
            n_br_beat++;
        end
    end
    /* verilator lint_on BLKSEQ */

    // ==================================================================
    // host BFM (drive/sample at NEGEDGE only — TB discipline)
    // ==================================================================
    /* verilator lint_off UNUSEDSIGNAL */
    task automatic hwr(input int unsigned addr, input int unsigned data);
        begin
            @(negedge clk);
            h_awaddr  = addr[11:0]; h_awvalid  = 1'b1;
            h_wdata   = data;       h_wvalid   = 1'b1;
            h_bready  = 1'b1;
            // ready is sampled at the negedge BEFORE the capturing posedge
            while (!(h_awready && h_wready)) @(negedge clk);
            @(negedge clk);
            h_awvalid  = 1'b0; h_wvalid  = 1'b0;
            while (!h_bvalid) @(negedge clk);
            @(negedge clk);
            h_bready  = 1'b0;
        end
    endtask

    task automatic hrd(input int unsigned addr, output int unsigned data);
        begin
            @(negedge clk);
            h_araddr  = addr[11:0]; h_arvalid  = 1'b1; h_rready  = 1'b1;
            while (!h_arready) @(negedge clk);
            @(negedge clk);
            h_arvalid  = 1'b0;
            while (!h_rvalid) @(negedge clk);
            data = h_rdata;
            @(negedge clk);
            h_rready  = 1'b0;
        end
    endtask
    /* verilator lint_on UNUSEDSIGNAL */

    // ==================================================================
    // RUNG 4 S6 (docs/RUNG4_SPEC.md) — OUT FIFO: depth 64, of_cnt DERIVED
    // from of_wp - of_rp, sticky of_ovf in STATUS[23].
    //
    // +ofdepth=<n>   the depth this build is expected to have (default 64)
    // +ofrace        pop the OUT FIFO WHILE the stream runs, interleaved
    //                into the STATUS poll loop (same host BFM, so no BFM
    //                race), which is the only way an AMAXL push and a host
    //                pop can land on the same cycle
    // +ofphase=<k>   k idle cycles between the poll and the pop; sweeping
    //                k slides the pop across the push
    //
    // The push/pop coincidence is not left to luck: of_wp and of_rp are
    // sampled every cycle through a hierarchical reference and a cycle in
    // which BOTH move is counted.  A +ofrace run that never coincides is
    // reported as such rather than passed off as a race test.
    // ==================================================================
    int unsigned of_depth = 64;
    int unsigned of_phase = 0;
    bit          ofrace   = 1'b0;
    int unsigned of_race_hits = 0;      // cycles with a push AND a pop
    int unsigned of_push_n = 0, of_pop_n = 0;
    int unsigned race_tok [1024];       // tokens popped DURING the run
    int unsigned n_race_tok = 0;

    logic [6:0] ofwp_q = '0, ofrp_q = '0;
    /* verilator lint_off BLKSEQ */
    always @(posedge clk) begin
        if (rstn) begin
            // sized casts: this monitor also builds against the PRE-rung-4
            // seq_unit, whose pointers are 5 bits wide
            if (7'(dut.of_wp) !== ofwp_q) of_push_n++;
            if (7'(dut.of_rp) !== ofrp_q) of_pop_n++;
            if ((7'(dut.of_wp) !== ofwp_q) && (7'(dut.of_rp) !== ofrp_q))
                of_race_hits++;
        end
        ofwp_q = 7'(dut.of_wp);
        ofrp_q = 7'(dut.of_rp);
    end
    /* verilator lint_on BLKSEQ */

    // ==================================================================
    int unsigned cyc_start, cyc_end;

    initial begin
        /* verilator lint_off UNUSEDSIGNAL */
        int unsigned v, tok, nerr;
        /* verilator lint_on UNUSEDSIGNAL */
        int unsigned t_pc, t_st;
        real cyc, recs;

        h_awaddr = 0; h_awvalid = 0; h_wdata = 0; h_wvalid = 0; h_bready = 0;
        h_araddr = 0; h_arvalid = 0; h_rready = 0;
        got_w = 0; got_r = 0; n_poll = 0; nerr = 0;
        bw_wp = 0; bw_rp = 0; br_wp = 0; br_rp = 0;
        bw_addr = 0; bw_left = 0; br_addr = 0; br_left = 0;
        n_bw_beat = 0; n_br_beat = 0; n_hi16 = 0;

        if (!$value$plusargs("vec=%s", vec)) $fatal(1, "need +vec=<prefix>");
        if (!$value$plusargs("maxcyc=%d", maxcyc)) maxcyc = 20_000_000;
        if (!$value$plusargs("ofdepth=%d", of_depth)) of_depth = 64;
        void'($value$plusargs("ofphase=%d", of_phase));
        ofrace = $test$plusargs("ofrace");

        load_vectors(vec);
        // RUNG3 error path: with +binj_b=<n> / +binj_r=<n> the burst fabric
        // turns the n'th write response / read beat into SLVERR, and the
        // mover must halt with E_AXI.  +experr=<code> tells this TB to expect
        // that instead of the stream's own golden error code.
        if ($value$plusargs("experr=%d", v)) begin
            exp_err = v;
            $display("SEQ %s: expecting err_code %0d (fault injected)", vec,
                     exp_err);
        end
        $readmemh({vec, ".ddr.hex"}, u_ddr.mem);

        repeat (16) @(negedge clk);
        rstn = 1'b1;
        repeat (8) @(negedge clk);

        hrd(32'h28, v);
        if (v !== 32'hFAB1_E5E0) $fatal(1, "SEQ IDENT = %08h", v);

        // program the stream: base 0x9000_1000 (the .ddr.hex layout)
        hwr(32'h08, 32'h9000_1000);
        hwr(32'h0C, 32'h0);
        hwr(32'h10, exp_nrec);
        hwr(32'h24, 32'h0);
        hwr(32'h20, 32'd0);
        // XRF[3] seed (prompt token) — the generator always uses 0 here and
        // encodes any other seed as an explicit CSRWR record.
        hwr(32'h4C, 32'd0);

        cyc_start = int'($time / 4);
        hwr(32'h00, 32'h1);                        // START

        begin
            int unsigned guard;
            guard = 0;
            forever begin
                hrd(32'h04, t_st);
                if (ofrace) begin
                    // S6 race: a host pop issued back-to-back with the poll,
                    // slid by +ofphase, so it can coincide with an AMAXL push
                    repeat (of_phase) @(negedge clk);
                    hrd(32'h18, tok);
                    if (tok[31]) begin
                        if (n_race_tok < 1024) begin
                            race_tok[n_race_tok] = {14'd0, tok[17:0]};
                            n_race_tok++;
                        end
                    end
                end
                if (t_st[2]) break;                // halted
                guard++;
                if (guard > maxcyc) $fatal(1, "SEQ never halted (STATUS %08h)",
                                           t_st);
            end
        end
        cyc_end = int'($time / 4);

        hrd(32'h14, t_pc);

        // ---- status ----
        if ({24'd0, t_st[31:24]} !== exp_err)
            $fatal(1, "err_code %0d, expected %0d (STATUS %08h)",
                   t_st[31:24], exp_err, t_st);
        if (exp_err == 0) begin
            if (t_st[1]) $fatal(1, "unexpected err flag");
            if (t_pc !== exp_pc)
                $fatal(1, "final pc %0d, expected %0d", t_pc, exp_pc);
            if (got_w !== n_exp_w)
                $fatal(1, "issued %0d writes, expected %0d", got_w, n_exp_w);
            if (got_r !== n_exp_r)
                $fatal(1, "issued %0d reads, expected %0d", got_r, n_exp_r);
        end

        // ---- XRF ----
        if (exp_err == 0)
            for (int i = 0; i < 8; i++) begin
                hrd(32'h40 + 4 * i, v);
                if (v[17:0] !== exp_xrf[i][17:0]) begin
                    $display("XRF[%0d] = %05h, expected %05h", i, v[17:0],
                             exp_xrf[i][17:0]);
                    nerr++;
                end
            end

        // ---- OUT FIFO (RUNG 4 S6) ----
        // NOT racing: the FIFO holds the FIRST min(ntok, depth) tokens and
        //             of_ovf is sticky-set iff ntok > depth.
        // Racing:     every token survives (pushes are far slower than the
        //             host's pops), of_ovf must be 0, and the popped-during
        //             + drained-after sequence must be exp_tok EXACTLY —
        //             no loss, no duplication, no reordering.
        if (exp_err == 0) begin
            int unsigned n_keep, n_left, exp_ovf, all_tok [1024], n_all;
            n_keep  = ofrace ? n_exp_tok
                             : ((n_exp_tok > of_depth) ? of_depth : n_exp_tok);
            exp_ovf = (!ofrace && (n_exp_tok > of_depth)) ? 1 : 0;
            n_left  = n_keep - n_race_tok;

            hrd(32'h04, t_st);                       // fresh STATUS
            if ({31'd0, t_st[23]} !== exp_ovf) begin
                $display("STATUS.of_ovf = %0d, expected %0d (ntok %0d, depth %0d, race %0d)",
                         t_st[23], exp_ovf, n_exp_tok, of_depth, ofrace);
                nerr++;
            end
            if ({25'd0, t_st[22:16]} !== n_left) begin
                $display("STATUS.out_cnt = %0d, expected %0d",
                         t_st[22:16], n_left);
                nerr++;
            end
            hrd(32'h1C, v);                          // OUT_CNT, unmasked
            if (v !== n_left) begin
                $display("OUT_CNT = %0d, expected %0d", v, n_left);
                nerr++;
            end

            n_all = 0;
            for (int i = 0; i < int'(n_race_tok); i++) begin
                all_tok[n_all] = race_tok[i]; n_all++;
            end
            // drain whatever is left, then keep reading until the FIFO
            // reports empty — an entry that of_rp consumed but the host
            // never received shows up as (pops > tokens delivered) below.
            for (int i = 0; i < int'(n_left) + 2; i++) begin
                hrd(32'h18, tok);
                if (!tok[31]) begin
                    if (i < int'(n_left)) begin
                        $display("OUT FIFO empty at token %0d of %0d",
                                 i, n_left);
                        nerr++;
                    end
                    break;
                end
                all_tok[n_all] = {14'd0, tok[17:0]}; n_all++;
            end
            // THE S6 INVARIANT: of_rp advances exactly once per token the
            // host actually received.  A pop that fires on a read which
            // reported EMPTY consumes an entry nobody got.
            if (of_pop_n !== n_all) begin
                $display("S6 RACE: of_rp advanced %0d times but the host received %0d tokens (%0d entries consumed with valid=0)",
                         of_pop_n, n_all, of_pop_n - n_all);
                nerr++;
            end
            if (n_all !== n_keep) begin
                $display("collected %0d tokens, expected %0d", n_all, n_keep);
                nerr++;
            end
            for (int i = 0; i < int'(n_keep); i++)
                if (all_tok[i][17:0] !== exp_tok[i][17:0]) begin
                    $display("TOK[%0d] = %05h, expected %05h", i,
                             all_tok[i][17:0], exp_tok[i][17:0]);
                    nerr++;
                end
            // drained: the next read must report empty and the count 0
            hrd(32'h18, tok);
            if (tok[31]) begin
                $display("OUT FIFO still valid after draining %0d", n_keep);
                nerr++;
            end
            hrd(32'h1C, v);
            if (v !== 32'd0) begin
                $display("OUT_CNT = %0d after a full drain", v);
                nerr++;
            end
            if (n_exp_tok > 4 || ofrace)
                $display("  S6 OUT FIFO: ntok=%0d depth=%0d kept=%0d rx=%0d ovf=%0d | pushes=%0d pops=%0d SIMULTANEOUS=%0d",
                         n_exp_tok, of_depth, n_keep, n_all, t_st[23],
                         of_push_n, of_pop_n, of_race_hits);
            if (ofrace && of_race_hits == 0)
                $display("  NOTE: no push/pop coincidence at +ofphase=%0d (this run did not exercise the race)",
                         of_phase);
        end

        // ---- layer scratchpad ----
        if (exp_err == 0)
            for (int i = 0; i < int'(n_exp_mem); i++) begin
                v = {16'd0, u_layer.smem[exp_mem_a[i][13:0]]} & 32'hFFFF;
                if (v !== (exp_mem_v[i] & 32'hFFFF)) begin
                    $display("MEM[%04h] = %04h, expected %04h",
                             exp_mem_a[i], v, exp_mem_v[i] & 32'hFFFF);
                    nerr++;
                    if (nerr > 20) $fatal(1, "too many scratch mismatches");
                end
            end

        if (nerr != 0) $fatal(1, "%0d comparison failures", nerr);

        // ---- issue rate ----
        cyc  = real'(cyc_end - cyc_start);
        recs = real'(exp_nrec);
        hrd(32'h2C, v);
        $display("SEQ %s: %0d records, %0d cycles (%0.2f cyc/rec, %0.3f Mrec/s @250MHz)",
                 vec, exp_nrec, cyc_end - cyc_start, cyc / recs,
                 250.0 * recs / cyc);
        hrd(32'h34, v);
        $display("  axil writes %0d", v);
        hrd(32'h38, v);
        $display("  axil reads  %0d  (of which %0d were status polls)",
                 v, n_poll);
        hrd(32'h3C, v);
        $display("  fetch-empty stall cycles %0d  (ddr beats %0d)",
                 v[31:1], d_nbeats);
        $display("  layer cmds %0d, engine runs %0d/%0d/%0d/%0d, LAT=%0d BLAT=%0d DDRLAT=%0d SIDEBAND=%0d",
                 layer_ncmd, mv_nrun[0], mv_nrun[1], mv_nrun[2], mv_nrun[3],
                 LAT, BLAT, DDRLAT, SIDEBAND);
        $display("  burst: %0d write bursts (%0d beats), %0d read bursts (%0d beats), busy_wr %0d busy_rd %0d, decerr %0d non-OK %0d",
                 bf_nwr, bf_nwbeat, bf_nrd, bf_nrbeat, bf_bwr, bf_brd,
                 bf_ndec, bf_nslv);
        if (bf_ndec != 32'd0)
            $fatal(1, "%0d burst decode holes (the S4 map is wrong)", bf_ndec);
        if (bf_nidm != 32'd0)
            $fatal(1, "%0d burst id-echo mismatches", bf_nidm);
        if (n_hi16 != 0)
            $display("  note: %0d scratch burst beats carried non-zero bits [31:16]",
                     n_hi16);
        $display("SEQ PASS: %s (writes %0d, reads %0d, scratch %0d, tokens %0d)",
                 vec, got_w, got_r, n_exp_mem, n_exp_tok);
        $finish;
    end

    // global watchdog
    initial begin
        #200_000_000;
        $fatal(1, "tb_seq_unit: global timeout");
    end

endmodule

`default_nettype wire
