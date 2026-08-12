// tb_burst_fabric — conformance TB for tb/seq_burst_fabric.sv and for the
// S5/S6 BURST-WINDOW CONTRACT the rung-3 slave shims must implement.
//
// It is deliberately independent of rtl/seq_movers.sv: a synthetic AXI4
// master drives the fabric directly, so the fabric, the address map and the
// window semantics can be gated before (and independently of) the mover.
// The five MIs carry the behavioural stubs (tb/seq_stub_mvchan.sv x4,
// tb/seq_stub_layer.sv), whose burst windows are the reference the real
// shims (rtl/matvec_chan.sv S5, rtl/layer_chan.sv S6) are written against.
//
//   master m_axib -> seq_burst_fabric -> MI0..3 = mvchan @ 0x1_0000..0x4_0000
//                                     -> MI4    = layer  @ 0x5_0000
//   each stub's AXI-Lite port <- a TB-side AXI-Lite BFM (doorbells, CMD,
//   SPTR/SWIN), so the burst window and the CSR window can be cross-checked
//   against each other on the SAME memory.
//
// Cases (docs/RUNG3_SPEC.md gate 1 "error paths" + the fabric's own gate):
//   T1  routing + data: XWIN burst push -> doorbell -> RES burst read, per
//       channel, and no crosstalk between channels
//   T2  layer scratch: burst write -> burst read AND -> AXI-Lite SPTR/SWIN
//       read (the two windows must address the same memory)
//   T3  DECERR: any address outside the five 64 KiB windows, read and write,
//       with the full beat count still returned / consumed
//   T4  SLVERR: mvchan out-of-window read/write, layer window while busy
//   T5  burst geometry: 1 / 16 / 256 beats, 4 KiB-boundary respected
//   T6  pipelining: 4 read bursts issued back to back
//   T7  latency report at the +blat setting
//
// Run: obj_dir_tb_bfab/tb_bfab +seed=1 [+blat=0|4|8] [+quiet]

`timescale 1ns/1ps
`default_nettype none

module tb_burst_fabric #(
    parameter int LAT  = 4,
    parameter int NSLV = 5
);
    localparam int NMV = 4;

    logic clk = 1'b0;
    logic rstn = 1'b0;
    /* verilator lint_off BLKSEQ */
    always #2 clk = ~clk;                        // 250 MHz
    /* verilator lint_on BLKSEQ */

    // ---------------- master (BFM) -> fabric ----------------
    logic [0:0]  s_awid, s_arid;
    logic [31:0] s_awaddr, s_araddr, s_wdata, s_rdata;
    logic [7:0]  s_awlen, s_arlen;
    logic [2:0]  s_awsize, s_arsize;
    logic [1:0]  s_awburst, s_arburst, s_bresp, s_rresp;
    logic [3:0]  s_wstrb;
    logic        s_awvalid, s_awready, s_wvalid, s_wready, s_wlast;
    logic        s_bvalid, s_bready, s_arvalid, s_arready;
    logic        s_rvalid, s_rready, s_rlast;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [0:0]  s_bid, s_rid;
    logic [31:0] fb_nwr, fb_nwbeat, fb_nrd, fb_nrbeat, fb_bwr, fb_brd;
    logic [31:0] fb_ndec, fb_nslv, fb_nidm;
    /* verilator lint_on UNUSEDSIGNAL */

    // ---------------- fabric -> slaves ----------------
    logic [NSLV-1:0][0:0]  b_awid, b_arid, b_bid, b_rid;
    logic [NSLV-1:0][15:0] b_awaddr, b_araddr;
    logic [NSLV-1:0][7:0]  b_awlen, b_arlen;
    logic [NSLV-1:0][2:0]  b_awsize, b_arsize;
    logic [NSLV-1:0][1:0]  b_awburst, b_arburst, b_bresp, b_rresp;
    logic [NSLV-1:0][31:0] b_wdata, b_rdata;
    logic [NSLV-1:0][3:0]  b_wstrb;
    logic [NSLV-1:0]       b_awvalid, b_awready, b_wvalid, b_wready, b_wlast;
    logic [NSLV-1:0]       b_bvalid, b_bready, b_arvalid, b_arready;
    logic [NSLV-1:0]       b_rvalid, b_rready, b_rlast;

    seq_burst_fabric #(.LAT(LAT), .NSLV(NSLV)) u_fab (
        .aclk(clk), .aresetn(rstn),
        .s_awid(s_awid), .s_awaddr(s_awaddr), .s_awlen(s_awlen),
        .s_awsize(s_awsize), .s_awburst(s_awburst), .s_awvalid(s_awvalid),
        .s_awready(s_awready),
        .s_wdata(s_wdata), .s_wstrb(s_wstrb), .s_wlast(s_wlast),
        .s_wvalid(s_wvalid), .s_wready(s_wready),
        .s_bid(s_bid), .s_bresp(s_bresp), .s_bvalid(s_bvalid),
        .s_bready(s_bready),
        .s_arid(s_arid), .s_araddr(s_araddr), .s_arlen(s_arlen),
        .s_arsize(s_arsize), .s_arburst(s_arburst), .s_arvalid(s_arvalid),
        .s_arready(s_arready),
        .s_rid(s_rid), .s_rdata(s_rdata), .s_rresp(s_rresp),
        .s_rlast(s_rlast), .s_rvalid(s_rvalid), .s_rready(s_rready),

        .m_awid(b_awid), .m_awaddr(b_awaddr), .m_awlen(b_awlen),
        .m_awsize(b_awsize), .m_awburst(b_awburst), .m_awvalid(b_awvalid),
        .m_awready(b_awready),
        .m_wdata(b_wdata), .m_wstrb(b_wstrb), .m_wlast(b_wlast),
        .m_wvalid(b_wvalid), .m_wready(b_wready),
        .m_bid(b_bid), .m_bresp(b_bresp), .m_bvalid(b_bvalid),
        .m_bready(b_bready),
        .m_arid(b_arid), .m_araddr(b_araddr), .m_arlen(b_arlen),
        .m_arsize(b_arsize), .m_arburst(b_arburst), .m_arvalid(b_arvalid),
        .m_arready(b_arready),
        .m_rid(b_rid), .m_rdata(b_rdata), .m_rresp(b_rresp),
        .m_rlast(b_rlast), .m_rvalid(b_rvalid), .m_rready(b_rready),

        .n_wr(fb_nwr), .n_wbeat(fb_nwbeat), .n_rd(fb_nrd),
        .n_rbeat(fb_nrbeat), .busy_wr(fb_bwr), .busy_rd(fb_brd),
        .n_dec(fb_ndec), .n_slverr(fb_nslv), .n_idmis(fb_nidm)
    );

    // ---------------- AXI-Lite BFM -> the stubs' CSR ports ----------------
    logic [2:0]  a_sel;
    logic [11:0] a_awaddr, a_araddr;
    logic [31:0] a_wdata;
    logic        a_awvalid, a_wvalid, a_bready, a_arvalid, a_rready;

    logic [NSLV-1:0]       l_awvalid, l_awready, l_wvalid, l_wready;
    logic [NSLV-1:0]       l_bvalid, l_bready, l_arvalid, l_arready;
    logic [NSLV-1:0]       l_rvalid, l_rready;
    logic [NSLV-1:0][31:0] l_rdata;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [NSLV-1:0][1:0]  l_bresp, l_rresp;
    /* verilator lint_on UNUSEDSIGNAL */

    for (genvar g = 0; g < NSLV; g++) begin : g_axil_mux
        assign l_awvalid[g] = a_awvalid && (a_sel == 3'(g));
        assign l_wvalid[g]  = a_wvalid  && (a_sel == 3'(g));
        assign l_bready[g]  = a_bready  && (a_sel == 3'(g));
        assign l_arvalid[g] = a_arvalid && (a_sel == 3'(g));
        assign l_rready[g]  = a_rready  && (a_sel == 3'(g));
    end
    wire        a_awready = l_awready[a_sel];
    wire        a_wready  = l_wready[a_sel];
    wire        a_bvalid  = l_bvalid[a_sel];
    wire        a_arready = l_arready[a_sel];
    wire        a_rvalid  = l_rvalid[a_sel];
    wire [31:0] a_rdata   = l_rdata[a_sel];

    /* verilator lint_off UNUSEDSIGNAL */
    logic [31:0] mv_nrun [NMV];
    logic [31:0] layer_ncmd;
    logic        sb_we;
    logic [2:0]  sb_idx;
    logic [17:0] sb_data;
    /* verilator lint_on UNUSEDSIGNAL */

    for (genvar c = 0; c < NMV; c++) begin : g_mv
        seq_stub_mvchan #(.CHAN_ID(4'(c))) u_mv (
            .aclk(clk), .aresetn(rstn),
            .s_axil_awaddr(a_awaddr), .s_axil_awvalid(l_awvalid[c]),
            .s_axil_awready(l_awready[c]), .s_axil_wdata(a_wdata),
            .s_axil_wstrb(4'hF), .s_axil_wvalid(l_wvalid[c]),
            .s_axil_wready(l_wready[c]), .s_axil_bresp(l_bresp[c]),
            .s_axil_bvalid(l_bvalid[c]), .s_axil_bready(l_bready[c]),
            .s_axil_araddr(a_araddr), .s_axil_arvalid(l_arvalid[c]),
            .s_axil_arready(l_arready[c]), .s_axil_rdata(l_rdata[c]),
            .s_axil_rresp(l_rresp[c]), .s_axil_rvalid(l_rvalid[c]),
            .s_axil_rready(l_rready[c]),
            .s_axib_awid(b_awid[c]), .s_axib_awaddr(b_awaddr[c]),
            .s_axib_awlen(b_awlen[c]), .s_axib_awsize(b_awsize[c]),
            .s_axib_awburst(b_awburst[c]), .s_axib_awvalid(b_awvalid[c]),
            .s_axib_awready(b_awready[c]), .s_axib_wdata(b_wdata[c]),
            .s_axib_wstrb(b_wstrb[c]), .s_axib_wlast(b_wlast[c]),
            .s_axib_wvalid(b_wvalid[c]), .s_axib_wready(b_wready[c]),
            .s_axib_bid(b_bid[c]), .s_axib_bresp(b_bresp[c]),
            .s_axib_bvalid(b_bvalid[c]), .s_axib_bready(b_bready[c]),
            .s_axib_arid(b_arid[c]), .s_axib_araddr(b_araddr[c]),
            .s_axib_arlen(b_arlen[c]), .s_axib_arsize(b_arsize[c]),
            .s_axib_arburst(b_arburst[c]), .s_axib_arvalid(b_arvalid[c]),
            .s_axib_arready(b_arready[c]), .s_axib_rid(b_rid[c]),
            .s_axib_rdata(b_rdata[c]), .s_axib_rresp(b_rresp[c]),
            .s_axib_rlast(b_rlast[c]), .s_axib_rvalid(b_rvalid[c]),
            .s_axib_rready(b_rready[c]),
            .n_run(mv_nrun[c])
        );
    end

    // CMD_CYC_MIN is stretched so the SLVERR-while-busy case (T4) is
    // reachable through the fabric's latency; the AXI-Lite semantics the
    // stub models are unchanged.
    seq_stub_layer #(.CMD_CYC_MIN(200), .CMD_CYC_MOD(1)) u_layer (
        .aclk(clk), .aresetn(rstn),
        .s_axil_awaddr(a_awaddr), .s_axil_awvalid(l_awvalid[4]),
        .s_axil_awready(l_awready[4]), .s_axil_wdata(a_wdata),
        .s_axil_wstrb(4'hF), .s_axil_wvalid(l_wvalid[4]),
        .s_axil_wready(l_wready[4]), .s_axil_bresp(l_bresp[4]),
        .s_axil_bvalid(l_bvalid[4]), .s_axil_bready(l_bready[4]),
        .s_axil_araddr(a_araddr), .s_axil_arvalid(l_arvalid[4]),
        .s_axil_arready(l_arready[4]), .s_axil_rdata(l_rdata[4]),
        .s_axil_rresp(l_rresp[4]), .s_axil_rvalid(l_rvalid[4]),
        .s_axil_rready(l_rready[4]),
        .s_axib_awid(b_awid[4]), .s_axib_awaddr(b_awaddr[4]),
        .s_axib_awlen(b_awlen[4]), .s_axib_awsize(b_awsize[4]),
        .s_axib_awburst(b_awburst[4]), .s_axib_awvalid(b_awvalid[4]),
        .s_axib_awready(b_awready[4]), .s_axib_wdata(b_wdata[4]),
        .s_axib_wstrb(b_wstrb[4]), .s_axib_wlast(b_wlast[4]),
        .s_axib_wvalid(b_wvalid[4]), .s_axib_wready(b_wready[4]),
        .s_axib_bid(b_bid[4]), .s_axib_bresp(b_bresp[4]),
        .s_axib_bvalid(b_bvalid[4]), .s_axib_bready(b_bready[4]),
        .s_axib_arid(b_arid[4]), .s_axib_araddr(b_araddr[4]),
        .s_axib_arlen(b_arlen[4]), .s_axib_arsize(b_arsize[4]),
        .s_axib_arburst(b_arburst[4]), .s_axib_arvalid(b_arvalid[4]),
        .s_axib_arready(b_arready[4]), .s_axib_rid(b_rid[4]),
        .s_axib_rdata(b_rdata[4]), .s_axib_rresp(b_rresp[4]),
        .s_axib_rlast(b_rlast[4]), .s_axib_rvalid(b_rvalid[4]),
        .s_axib_rready(b_rready[4]),
        .n_cmd(layer_ncmd),
        .xrf_sb_we(sb_we), .xrf_sb_idx(sb_idx), .xrf_sb_data(sb_data)
    );

    // ==================================================================
    // BFMs — drive and sample at NEGEDGE only (TB discipline).  Inputs are
    // driven with BLOCKING assignments and READY is sampled after a #0.1
    // settle, so the value read at negedge N is the one the DUT uses at
    // posedge N+1 (seq_burst_fabric's AWREADY/ARREADY depend on the address
    // through the decoder, so the settle delay is required).
    // ==================================================================
    localparam int MAXB = 300;
    int unsigned rdbuf [MAXB];
    int unsigned nerr;

    task automatic bwr(input int unsigned addr, input int unsigned nbeat,
                       input int unsigned d0, input int unsigned dstep,
                       output logic [1:0] resp);
        begin
            @(negedge clk);
            s_awid = 1'b0; s_awaddr = addr; s_awlen = 8'(nbeat - 1);
            s_awsize = 3'b010; s_awburst = 2'b01; s_awvalid = 1'b1;
            #0.1;
            while (!s_awready) begin @(negedge clk); #0.1; end
            @(negedge clk);
            s_awvalid = 1'b0;
            for (int i = 0; i < int'(nbeat); i++) begin
                s_wdata = d0 + dstep * unsigned'(i);
                s_wstrb = 4'hF;
                s_wlast = (i == int'(nbeat) - 1);
                s_wvalid = 1'b1;
                #0.1;
                while (!s_wready) begin @(negedge clk); #0.1; end
                @(negedge clk);
            end
            s_wvalid = 1'b0; s_wlast = 1'b0;
            s_bready = 1'b1;
            #0.1;
            while (!s_bvalid) begin @(negedge clk); #0.1; end
            resp = s_bresp;
            @(negedge clk);
            s_bready = 1'b0;
        end
    endtask

    // reads nbeat words into rdbuf[]; resp = the WORST response seen
    task automatic brd(input int unsigned addr, input int unsigned nbeat,
                       output logic [1:0] resp);
        begin
            if (nbeat > MAXB) $fatal(1, "brd: nbeat %0d > MAXB", nbeat);
            @(negedge clk);
            s_arid = 1'b0; s_araddr = addr; s_arlen = 8'(nbeat - 1);
            s_arsize = 3'b010; s_arburst = 2'b01; s_arvalid = 1'b1;
            s_rready = 1'b1;
            #0.1;
            while (!s_arready) begin @(negedge clk); #0.1; end
            @(negedge clk);
            s_arvalid = 1'b0;
            resp = 2'b00;
            for (int i = 0; i < int'(nbeat); i++) begin
                #0.1;
                while (!s_rvalid) begin @(negedge clk); #0.1; end
                rdbuf[i] = s_rdata;
                if (s_rresp != 2'b00) resp = s_rresp;
                if (s_rlast !== (i == int'(nbeat) - 1))
                    $fatal(1, "brd: RLAST=%b on beat %0d of %0d", s_rlast, i,
                           nbeat);
                @(negedge clk);
            end
            s_rready = 1'b0;
        end
    endtask

    /* verilator lint_off UNUSEDSIGNAL */
    task automatic awr(input int unsigned sel, input int unsigned addr,
                       input int unsigned data);
        begin
            @(negedge clk);
            a_sel = 3'(sel); a_awaddr = addr[11:0]; a_wdata = data;
            a_awvalid = 1'b1; a_wvalid = 1'b1; a_bready = 1'b1;
            #0.1;
            while (!(a_awready && a_wready)) begin @(negedge clk); #0.1; end
            @(negedge clk);
            a_awvalid = 1'b0; a_wvalid = 1'b0;
            #0.1;
            while (!a_bvalid) begin @(negedge clk); #0.1; end
            @(negedge clk);
            a_bready = 1'b0;
        end
    endtask

    task automatic ard(input int unsigned sel, input int unsigned addr,
                       output int unsigned data);
        begin
            @(negedge clk);
            a_sel = 3'(sel); a_araddr = addr[11:0];
            a_arvalid = 1'b1; a_rready = 1'b1;
            #0.1;
            while (!a_arready) begin @(negedge clk); #0.1; end
            @(negedge clk);
            a_arvalid = 1'b0;
            #0.1;
            while (!a_rvalid) begin @(negedge clk); #0.1; end
            data = a_rdata;
            @(negedge clk);
            a_rready = 1'b0;
        end
    endtask
    /* verilator lint_on UNUSEDSIGNAL */

    // ------------------------------------------------------------------
    function automatic int unsigned mvbase(input int unsigned c);
        mvbase = (c + 1) << 16;
    endfunction
    localparam int unsigned LAYBASE = 5 << 16;

    function automatic int unsigned res_word(input int unsigned r,
                                             input int unsigned seed);
        res_word = (32'd2654435761 * r) ^ seed;
    endfunction

    task automatic chk(input int unsigned got, input int unsigned want,
                       input string what);
        begin
            if (got !== want) begin
                $display("MISMATCH %s: got %08h want %08h", what, got, want);
                nerr++;
                if (nerr > 20) $fatal(1, "too many mismatches");
            end
        end
    endtask

    // ==================================================================
    int unsigned seed;
    int          blat;

    initial begin
        int unsigned v, xsum, expseed, shape, wblo, t0, t1;
        logic [1:0]  resp;

        s_awid = 0; s_awaddr = 0; s_awlen = 0; s_awsize = 0; s_awburst = 0;
        s_awvalid = 0; s_wdata = 0; s_wstrb = 0; s_wlast = 0; s_wvalid = 0;
        s_bready = 0; s_arid = 0; s_araddr = 0; s_arlen = 0; s_arsize = 0;
        s_arburst = 0; s_arvalid = 0; s_rready = 0;
        a_sel = 0; a_awaddr = 0; a_araddr = 0; a_wdata = 0; a_awvalid = 0;
        a_wvalid = 0; a_bready = 0; a_arvalid = 0; a_rready = 0;
        nerr = 0;

        if (!$value$plusargs("seed=%d", seed)) seed = 1;
        blat = LAT;
        void'($value$plusargs("blat=%d", blat));

        repeat (16) @(negedge clk);
        rstn = 1'b1;
        repeat (8) @(negedge clk);

        // ==============================================================
        // T1 — routing + data, per channel, no crosstalk
        // ==============================================================
        for (int c = 0; c < NMV; c++) begin
            shape = 32'h0001_0000 + seed * 32'h37 + unsigned'(c);
            wblo  = (32'h2000_0000 + (unsigned'(c) << 12)) & 32'hFFFF_FFC0;
            awr(unsigned'(c), 32'h14, shape);           // SHAPE
            awr(unsigned'(c), 32'h08, wblo);            // WBASE_LO
            // burst-push 64 x words into the XWIN window (0x4000 + 4w)
            xsum = 0;
            for (int i = 0; i < 64; i++)
                xsum = xsum + (32'h1000_0000 + seed * 32'd7 + unsigned'(i)
                               + (unsigned'(c) << 8));
            bwr(mvbase(unsigned'(c)) + 32'h4000, 64,
                32'h1000_0000 + seed * 32'd7 + (unsigned'(c) << 8), 32'd1,
                resp);
            chk({30'd0, resp}, 32'd0, "T1 XWIN burst BRESP");
            awr(unsigned'(c), 32'h00, 32'd1);           // doorbell
            do begin ard(unsigned'(c), 32'h04, v); end while (v[0]);
            expseed = shape ^ wblo ^ xsum;

            // read RES rows 0..63 and rows 4032..4095 (S12: full 12-bit start)
            brd(mvbase(unsigned'(c)) + 32'h0000, 64, resp);
            chk({30'd0, resp}, 32'd0, "T1 RES burst RRESP");
            for (int i = 0; i < 64; i++)
                chk(rdbuf[i], res_word(unsigned'(i), expseed), "T1 RES row");
            brd(mvbase(unsigned'(c)) + 32'd16128, 64, resp);
            for (int i = 0; i < 64; i++)
                chk(rdbuf[i], res_word(unsigned'(4032 + i), expseed),
                    "T1 RES high row");
        end
        $display("T1 PASS: 4 channels, XWIN burst push -> doorbell -> RES burst read (rows 0..63 and 4032..4095)");

        // ==============================================================
        // T2 — layer scratch: burst write, burst read, AXI-Lite cross-check
        // ==============================================================
        bwr(LAYBASE + 32'd1024, 128, 32'h0000_1000 + seed, 32'd3, resp);
        chk({30'd0, resp}, 32'd0, "T2 scratch burst BRESP");
        brd(LAYBASE + 32'd1024, 128, resp);
        chk({30'd0, resp}, 32'd0, "T2 scratch burst RRESP");
        for (int i = 0; i < 128; i++)
            chk(rdbuf[i],
                (32'h0000_1000 + seed + 32'd3 * unsigned'(i)) & 32'hFFFF,
                "T2 scratch burst readback");
        awr(4, 32'h14, 32'h100);                        // SPTR = 0x100
        for (int i = 0; i < 8; i++) begin
            ard(4, 32'h18, v);                          // SWIN read
            chk(v, (32'h0000_1000 + seed + 32'd3 * unsigned'(i)) & 32'hFFFF,
                "T2 AXI-Lite SWIN sees the burst-written word");
        end
        // and the other way round: AXI-Lite write, burst read
        awr(4, 32'h14, 32'h800);
        for (int i = 0; i < 8; i++) awr(4, 32'h18, 32'hAB00 + unsigned'(i));
        brd(LAYBASE + 32'd8192, 8, resp);
        for (int i = 0; i < 8; i++)
            chk(rdbuf[i], 32'hAB00 + unsigned'(i),
                "T2 burst read sees the AXI-Lite-written word");
        // the very top scratch word (w = 16383) must be reachable
        bwr(LAYBASE + 32'd65532, 1, 32'h0000_5A5A, 32'd0, resp);
        chk({30'd0, resp}, 32'd0, "T2 top scratch word BRESP");
        brd(LAYBASE + 32'd65532, 1, resp);
        chk(rdbuf[0], 32'h0000_5A5A, "T2 top scratch word");
        $display("T2 PASS: layer scratch window == the AXI-Lite SWIN window (both directions), w=16383 reachable");

        // ==============================================================
        // T3 — DECERR on every decode hole
        // ==============================================================
        begin
            int unsigned holes [3];
            holes[0] = 32'h0000_0000;                   // slot 0
            holes[1] = 32'h0006_0000;                   // slot 6
            holes[2] = 32'h0080_0000;                   // above the aperture
            for (int h = 0; h < 3; h++) begin
                brd(holes[h], 4, resp);
                chk({30'd0, resp}, 32'd3, "T3 read DECERR");
                bwr(holes[h], 4, 32'hDEAD, 32'd1, resp);
                chk({30'd0, resp}, 32'd3, "T3 write DECERR");
            end
        end
        if (fb_ndec != 32'd6) begin
            $display("T3: fabric counted %0d decode holes, expected 6", fb_ndec);
            nerr++;
        end
        $display("T3 PASS: 3 decode holes x {read,write} -> DECERR, all beats returned/consumed (n_dec=%0d)", fb_ndec);

        // ==============================================================
        // T4 — SLVERR paths
        // ==============================================================
        brd(mvbase(0) + 32'h4000, 4, resp);             // read in the WRITE window
        chk({30'd0, resp}, 32'd2, "T4 mvchan read out of window");
        bwr(mvbase(0) + 32'h0000, 4, 32'd1, 32'd1, resp); // write in READ window
        chk({30'd0, resp}, 32'd2, "T4 mvchan write out of window");
        bwr(mvbase(0) + 32'hF000, 4, 32'd1, 32'd1, resp); // unmapped in-slot
        chk({30'd0, resp}, 32'd2, "T4 mvchan write unmapped offset");

        // layer window while BUSY: fire a CMD, then touch the window
        awr(4, 32'h08, 32'd0);                          // ARG0
        awr(4, 32'h00, 32'd11);                         // CMD (ALU) -> busy
        bwr(LAYBASE + 32'h0000, 4, 32'd1, 32'd1, resp);
        chk({30'd0, resp}, 32'd2, "T4 layer burst write while busy -> SLVERR");
        brd(LAYBASE + 32'h0000, 4, resp);
        chk({30'd0, resp}, 32'd2, "T4 layer burst read while busy -> SLVERR");
        // ... and the scratch must be UNCHANGED by the rejected write
        do begin ard(4, 32'h04, v); end while (v[0]);   // wait !busy
        brd(LAYBASE + 32'h0000, 4, resp);
        chk({30'd0, resp}, 32'd0, "T4 layer burst read after busy -> OK");
        for (int i = 0; i < 4; i++)
            chk(rdbuf[i], 32'd0, "T4 rejected burst write left scratch alone");
        $display("T4 PASS: mvchan out-of-window (r/w/unmapped) and layer-while-busy answer SLVERR, with no side effects");

        // ==============================================================
        // T5 — burst geometry: 1 / 16 / 256 beats, 4 KiB respected
        // ==============================================================
        begin
            int unsigned lens [3];
            lens[0] = 1; lens[1] = 16; lens[2] = 256;
            for (int k = 0; k < 3; k++) begin
                // 256 beats x 4 B = 1 KiB, placed so it never crosses 4 KiB
                bwr(LAYBASE + 32'h2000, lens[k], 32'h0000_2200 + seed, 32'd1,
                    resp);
                chk({30'd0, resp}, 32'd0, "T5 BRESP");
                brd(LAYBASE + 32'h2000, lens[k], resp);
                chk({30'd0, resp}, 32'd0, "T5 RRESP");
                for (int i = 0; i < int'(lens[k]); i++)
                    chk(rdbuf[i],
                        (32'h0000_2200 + seed + unsigned'(i)) & 32'hFFFF,
                        "T5 data");
            end
        end
        $display("T5 PASS: 1 / 16 / 256-beat bursts, INCR, 4 KiB-safe");

        // ==============================================================
        // T6 — back-to-back reads (the fabric must pipeline, not serialise)
        // ==============================================================
        t0 = int'($time / 4);
        for (int k = 0; k < 4; k++) begin
            brd(LAYBASE + 32'h2000, 64, resp);
            chk({30'd0, resp}, 32'd0, "T6 RRESP");
        end
        t1 = int'($time / 4);
        $display("T6 PASS: 4 x 64-beat reads in %0d cycles (%0.2f cyc/beat, blat=%0d)",
                 t1 - t0, real'(t1 - t0) / 256.0, blat);

        // ==============================================================
        if (nerr != 0) $fatal(1, "%0d comparison failures", nerr);
        if (fb_nidm != 32'd0) $fatal(1, "%0d id-echo mismatches", fb_nidm);
        $display("  fabric: %0d write bursts (%0d beats), %0d read bursts (%0d beats), busy_wr %0d busy_rd %0d, decerr %0d, non-OK responses %0d",
                 fb_nwr, fb_nwbeat, fb_nrd, fb_nrbeat, fb_bwr, fb_brd,
                 fb_ndec, fb_nslv);
        $display("TB_BURST_FABRIC PASS: seed %0d, blat %0d, LAT param %0d",
                 seed, blat, LAT);
        $finish;
    end

    initial begin
        #20_000_000;
        $fatal(1, "tb_burst_fabric: global timeout");
    end

endmodule

`default_nettype wire
