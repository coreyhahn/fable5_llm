// tb_mvshim_b: standalone unit TB for the RUNG3 / S5 burst shim (agent B).
//
// DUT = the REAL rtl/matvec_chan.sv, with mvshim_b_stubs.sv standing in for
// matvec_engine / ddr_rd_streamer (see that file for how the stub makes the
// RES image and the activation writes observable).  Nothing else is faked:
// the xpm_fifo_async, the xpm_memory_tdpram (READ_LATENCY_B = 2), the CDC
// and the shipped AXI-Lite register file are all the production instances.
//
// What is proven here
//   T1  every shipped AXI-Lite register still reads/writes bit-identically
//   T3  RES burst readback == RES_DATA (AXI-Lite) readback == the known RES
//       image, for row bases 0, 4095, 1024, 3840 and random bases (S12:
//       the start row is the full 12-bit address field, never hardwired 0)
//   T4  arbitration: AXI-Lite RES_DATA reads issued CONCURRENTLY with a
//       256-beat burst read still return correct data (the ARREADY
//       interlock that covers READ_LATENCY_B = 2)
//   T5/T6 XWIN burst pushes land in the engine's x port identically to
//       AXI-Lite XWIN pushes - same index, same data, bit for bit - and
//       leave XPTR untouched.  NX = 3072 words: the FULL x window (K =
//       12288), so the 12-bit index and the 0x4000-0x6FFF aperture are both
//       swept end to end.
//   T7  partial burst write at a non-zero word offset touches exactly the
//       addressed words
//   T8  SLVERR + window behaviour on both channels, with full beat counts
//       and RLAST still correct, and no lockup afterwards
//   T9  RREADY / WVALID throttling; with +slowui the XWIN fifo genuinely
//       goes full, so WREADY backpressure is exercised and no word is lost
//   T10 W beats presented before AW
//
// NEGEDGE discipline throughout (drive and sample only at negedge aclk).
// Failures call $fatal(1, ...).  4 seeds via +seed=N (--seed alone does NOT
// reseed $urandom under Verilator 5.020 - verified, see the initial block).
// +slowui  : ui_clk at 50 MHz (< aclk) to force xpm_fifo_async full
// +sabotage: corrupt one expected value - the TB must then FAIL (self-test)

`timescale 1ns/1ps

module tb_mvshim_b;

    import mvshim_b_pkg::fillpat;

    localparam int NROW = 4096;
    localparam int NX   = 3072;          // XWIN words (K <= 12288)

    // ------------------------------------------------------------------
    // clocks / reset
    // ------------------------------------------------------------------
    logic aclk   = 1'b0;
    logic ui_clk = 1'b0;
    real  ui_half;
    /* verilator lint_off BLKSEQ */
    always #2.000 aclk = ~aclk;          // 250 MHz
    initial begin
        ui_half = $test$plusargs("slowui") ? 10.000 : 1.667;
        forever #(ui_half) ui_clk = ~ui_clk;
    end
    /* verilator lint_on BLKSEQ */

    logic aresetn = 1'b0, ui_rstn = 1'b0;

    // ------------------------------------------------------------------
    // AXI-Lite (shipped CSR port)
    // ------------------------------------------------------------------
    logic [11:0] l_awaddr;  logic l_awvalid; logic l_awready;
    logic [31:0] l_wdata;   logic [3:0] l_wstrb; logic l_wvalid; logic l_wready;
    logic [1:0]  l_bresp;   logic l_bvalid; logic l_bready;
    logic [11:0] l_araddr;  logic l_arvalid; logic l_arready;
    logic [31:0] l_rdata;   logic [1:0] l_rresp; logic l_rvalid; logic l_rready;

    // ------------------------------------------------------------------
    // s_axib (the burst window under test)
    // ------------------------------------------------------------------
    logic [0:0]  b_awid;   logic [15:0] b_awaddr; logic [7:0] b_awlen;
    logic [2:0]  b_awsize; logic [1:0]  b_awburst;
    logic        b_awvalid, b_awready;
    logic [31:0] b_wdata;  logic [3:0]  b_wstrb; logic b_wlast;
    logic        b_wvalid, b_wready;
    logic [0:0]  b_bid;    logic [1:0]  b_bresp; logic b_bvalid, b_bready;
    logic [0:0]  b_arid;   logic [15:0] b_araddr; logic [7:0] b_arlen;
    logic [2:0]  b_arsize; logic [1:0]  b_arburst;
    logic        b_arvalid, b_arready;
    logic [0:0]  b_rid;    logic [31:0] b_rdata; logic [1:0] b_rresp;
    logic        b_rlast,  b_rvalid, b_rready;

    // engine-side AXI4 (stub streamer never drives it)
    /* verilator lint_off UNUSEDSIGNAL */
    logic [33:0]  m_araddr;
    logic [7:0]   m_arlen;
    logic [2:0]   m_arsize;
    logic [1:0]   m_arburst;
    logic         m_arvalid;
    logic         m_rready;
    /* verilator lint_on UNUSEDSIGNAL */

    matvec_chan #(.CHAN_ID(4'd2), .ADDR_W(34)) dut (
        .aclk, .aresetn,
        .s_axil_awaddr(l_awaddr), .s_axil_awvalid(l_awvalid), .s_axil_awready(l_awready),
        .s_axil_wdata(l_wdata), .s_axil_wstrb(l_wstrb), .s_axil_wvalid(l_wvalid),
        .s_axil_wready(l_wready), .s_axil_bresp(l_bresp), .s_axil_bvalid(l_bvalid),
        .s_axil_bready(l_bready), .s_axil_araddr(l_araddr), .s_axil_arvalid(l_arvalid),
        .s_axil_arready(l_arready), .s_axil_rdata(l_rdata), .s_axil_rresp(l_rresp),
        .s_axil_rvalid(l_rvalid), .s_axil_rready(l_rready),

        .s_axib_awid(b_awid), .s_axib_awaddr(b_awaddr), .s_axib_awlen(b_awlen),
        .s_axib_awsize(b_awsize), .s_axib_awburst(b_awburst),
        .s_axib_awvalid(b_awvalid), .s_axib_awready(b_awready),
        .s_axib_wdata(b_wdata), .s_axib_wstrb(b_wstrb), .s_axib_wlast(b_wlast),
        .s_axib_wvalid(b_wvalid), .s_axib_wready(b_wready),
        .s_axib_bid(b_bid), .s_axib_bresp(b_bresp), .s_axib_bvalid(b_bvalid),
        .s_axib_bready(b_bready),
        .s_axib_arid(b_arid), .s_axib_araddr(b_araddr), .s_axib_arlen(b_arlen),
        .s_axib_arsize(b_arsize), .s_axib_arburst(b_arburst),
        .s_axib_arvalid(b_arvalid), .s_axib_arready(b_arready),
        .s_axib_rid(b_rid), .s_axib_rdata(b_rdata), .s_axib_rresp(b_rresp),
        .s_axib_rlast(b_rlast), .s_axib_rvalid(b_rvalid), .s_axib_rready(b_rready),
        // BM1 (SEQ_ISA B16): the engine-busy output is not observed here
        /* verilator lint_off PINCONNECTEMPTY */
        .mv_busy_bm(), .xpush_room(), .xpush_busy(),   // R3-8: the x-push leg is idle here (tb_matvec_chan +push covers it)
        /* verilator lint_on PINCONNECTEMPTY */
        .xpush_valid(1'b0), .xpush_idx(12'd0), .xpush_data(32'd0),   // R3-8
        .ui_clk, .ui_rstn,
        .m_axi_araddr(m_araddr), .m_axi_arlen(m_arlen), .m_axi_arsize(m_arsize),
        .m_axi_arburst(m_arburst), .m_axi_arvalid(m_arvalid), .m_axi_arready(1'b0),
        .m_axi_rdata(512'd0), .m_axi_rresp(2'b00), .m_axi_rlast(1'b0),
        .m_axi_rvalid(1'b0), .m_axi_rready(m_rready)
    );

    // ------------------------------------------------------------------
    // scoreboard state
    // ------------------------------------------------------------------
    int          errors = 0;
    int          gen    = 0;                 // doorbell count == fill gen
    logic [31:0] res_exp [NROW];             // exact RES image
    logic [31:0] burst_buf [256];
    logic [1:0]  burst_rsp [256];
    logic        burst_lst [256];
    logic [31:0] wr_buf   [256];
    logic [31:0] xw       [NX];              // words pushed into XWIN
    logic [31:0] xback_a  [NX];              // read back after AXI-Lite push
    logic [31:0] xback_b  [NX];              // read back after burst push

    // ------------------------------------------------------------------
    // coverage monitors - they turn "backpressure / arbitration were
    // exercised" from an assumption into an observation
    // ------------------------------------------------------------------
    int wstall_cnt = 0;      // s_axib WVALID held with WREADY low
    int wbeat_cnt  = 0;      // s_axib W beats accepted
    int lstall_cnt = 0;      // AXI-Lite ARVALID held off (burst owns addrb)
    always @(negedge aclk) if (aresetn) begin
        if (b_wvalid && !b_wready) wstall_cnt <= wstall_cnt + 1;
        if (b_wvalid &&  b_wready) wbeat_cnt  <= wbeat_cnt  + 1;
        if (l_arvalid && !l_arready) lstall_cnt <= lstall_cnt + 1;
    end

    task automatic check(input bit cond, input string msg);
        if (!cond) begin
            errors++;
            $display("[%0t] FAIL: %s", $time, msg);
        end
    endtask

    task automatic chk32(input logic [31:0] got, input logic [31:0] exp,
                         input string msg);
        if (got !== exp) begin
            errors++;
            $display("[%0t] FAIL: %s (got %08h exp %08h)", $time, msg, got, exp);
        end
    endtask

    // ------------------------------------------------------------------
    // AXI-Lite master (negedge discipline, same shape as tb_matvec_chan)
    // ------------------------------------------------------------------
    task automatic wr32(input logic [11:0] addr, input logic [31:0] data);
        int g;
        @(negedge aclk);
        l_awaddr = addr; l_awvalid = 1'b1;
        l_wdata  = data; l_wstrb = 4'hF; l_wvalid = 1'b1;
        g = 0;
        while (!(l_awready && l_wready)) begin
            @(negedge aclk); g++;
            if (g > 100000) $fatal(1, "wr32 aw/w timeout addr=%03h", addr);
        end
        @(negedge aclk);
        l_awvalid = 1'b0; l_wvalid = 1'b0;
        g = 0;
        while (!l_bvalid) begin
            @(negedge aclk); g++;
            if (g > 100000) $fatal(1, "wr32 b timeout addr=%03h", addr);
        end
        l_bready = 1'b1;
        @(negedge aclk);
        l_bready = 1'b0;
    endtask

    task automatic rd32(input logic [11:0] addr, output logic [31:0] data);
        int g;
        @(negedge aclk);
        l_araddr = addr; l_arvalid = 1'b1;
        g = 0;
        while (!l_arready) begin
            @(negedge aclk); g++;
            if (g > 100000) $fatal(1, "rd32 ar timeout addr=%03h", addr);
        end
        @(negedge aclk);
        l_arvalid = 1'b0;
        g = 0;
        while (!l_rvalid) begin
            @(negedge aclk); g++;
            if (g > 100000) $fatal(1, "rd32 r timeout addr=%03h", addr);
        end
        data = l_rdata;
        l_rready = 1'b1;
        @(negedge aclk);
        l_rready = 1'b0;
    endtask

    // ------------------------------------------------------------------
    // s_axib master
    // ------------------------------------------------------------------
    // burst read -> burst_buf / burst_rsp / burst_lst
    task automatic axib_rd(input logic [15:0] addr, input int nbeats,
                           input bit throttle);
        int i, g;
        @(negedge aclk);
        b_arid = 1'b0; b_araddr = addr; b_arlen = 8'(nbeats - 1);
        b_arsize = 3'b010; b_arburst = 2'b01; b_arvalid = 1'b1;
        g = 0;
        while (!b_arready) begin
            @(negedge aclk); g++;
            if (g > 200000) $fatal(1, "axib_rd AR timeout addr=%04h", addr);
        end
        @(negedge aclk);
        b_arvalid = 1'b0;
        i = 0; g = 0;
        while (i < nbeats) begin
            @(negedge aclk);
            b_rready = throttle ? ($urandom_range(0, 9) < 6) : 1'b1;
            if (b_rvalid && b_rready) begin
                burst_buf[i] = b_rdata;
                burst_rsp[i] = b_rresp;
                burst_lst[i] = b_rlast;
                check(b_rid === 1'b0, "axib_rd: RID mismatch");
                i++;
            end
            g++;
            if (g > 200000) $fatal(1, "axib_rd R timeout addr=%04h beat=%0d", addr, i);
        end
        @(negedge aclk);
        b_rready = 1'b0;
        for (int k = 0; k < nbeats; k++)
            check(burst_lst[k] == (k == nbeats - 1),
                  $sformatf("axib_rd: RLAST wrong on beat %0d of %0d", k, nbeats));
    endtask

    // burst write from wr_buf; returns BRESP
    task automatic axib_wr(input logic [15:0] addr, input int nbeats,
                           input bit throttle, output logic [1:0] resp);
        int i, g;
        @(negedge aclk);
        b_awid = 1'b0; b_awaddr = addr; b_awlen = 8'(nbeats - 1);
        b_awsize = 3'b010; b_awburst = 2'b01; b_awvalid = 1'b1;
        g = 0;
        while (!b_awready) begin
            @(negedge aclk); g++;
            if (g > 200000) $fatal(1, "axib_wr AW timeout addr=%04h", addr);
        end
        @(negedge aclk);
        b_awvalid = 1'b0;
        i = 0; g = 0;
        while (i < nbeats) begin
            @(negedge aclk);
            b_wvalid = throttle ? ($urandom_range(0, 9) < 7) : 1'b1;
            b_wdata  = wr_buf[i];
            b_wstrb  = 4'hF;
            b_wlast  = (i == nbeats - 1);
            if (b_wvalid && b_wready) i++;
            g++;
            if (g > 400000) $fatal(1, "axib_wr W timeout addr=%04h beat=%0d", addr, i);
        end
        @(negedge aclk);
        b_wvalid = 1'b0; b_wlast = 1'b0;
        b_bready = 1'b1;
        g = 0;
        while (!b_bvalid) begin
            @(negedge aclk); g++;
            if (g > 200000) $fatal(1, "axib_wr B timeout addr=%04h", addr);
        end
        resp = b_bresp;
        check(b_bid === 1'b0, "axib_wr: BID mismatch");
        @(negedge aclk);
        b_bready = 1'b0;
    endtask

    // ------------------------------------------------------------------
    // helpers
    // ------------------------------------------------------------------
    task automatic do_fill();
        logic [31:0] st;
        int g;
        gen++;
        wr32(12'h000, 32'h1);                    // CTRL doorbell
        // STATUS.done is STICKY until the next start and the doorbell
        // crosses through toggle+2FF (seq_movers note C2): wait out the
        // guard, observe BUSY for the NEW run, and only then poll DONE.
        repeat (64) @(negedge aclk);
        g = 0;
        forever begin
            rd32(12'h004, st);                   // STATUS
            if (st[0]) break;                    // busy
            g++;
            if (g > 20000) $fatal(1, "fill: engine busy timeout (gen %0d)", gen);
        end
        g = 0;
        forever begin
            rd32(12'h004, st);                   // STATUS
            if (st[1]) break;                    // done
            g++;
            if (g > 20000) $fatal(1, "fill: engine done timeout (gen %0d)", gen);
        end
        repeat (20) @(negedge aclk);
        for (int r = 0; r < NROW; r++)
            res_exp[r] = fillpat(32'(r), 32'(gen));
    endtask

    // AXI-Lite RES_DATA readback of `n` rows starting at `base`
    task automatic axil_res_read(input int base, input int n,
                                 ref logic [31:0] dst [256]);
        logic [31:0] d;
        wr32(12'h02C, 32'(base));                // RES_PTR
        for (int k = 0; k < n; k++) begin
            rd32(12'h030, d);                    // RES_DATA (res_ptr++)
            dst[k] = d;
        end
    endtask

    task automatic wait_x_drain(input int nwords);
        int cyc;
        cyc = $test$plusargs("slowui") ? (nwords * 6 + 400) : (nwords * 2 + 400);
        repeat (cyc) @(negedge aclk);
    endtask

    // push nwords from xw[] through the AXI-Lite XWIN register.
    // The shipped XWIN register has NO backpressure (it sets xfifo_ovfl and
    // drops), so with +slowui - where a TB AXI-Lite write is faster than the
    // 50 MHz fifo drain - the pushes must be paced, exactly as the real host
    // is paced by its ~1.7 us MMIO round trip.  The BURST window needs no
    // such pacing: that is the point of T6.
    task automatic push_xwin_axil(input int nwords);
        wr32(12'h028, 32'd0);                    // XPTR = 0
        for (int k = 0; k < nwords; k++) begin
            wr32(12'h024, xw[k]);
            if ($test$plusargs("slowui")) repeat (8) @(negedge aclk);
        end
        wait_x_drain(nwords);
    endtask

    // push nwords from xw[] through the s_axib write window (256-beat bursts)
    task automatic push_xwin_burst(input int nwords, input bit throttle);
        logic [1:0] rsp;
        int off, n;
        off = 0;
        while (off < nwords) begin
            n = (nwords - off > 256) ? 256 : (nwords - off);
            for (int k = 0; k < n; k++) wr_buf[k] = xw[off + k];
            axib_wr(16'h4000 + 16'(4 * off), n, throttle, rsp);
            chk32({30'b0, rsp}, 32'd0,
                  $sformatf("XWIN burst write BRESP at word %0d", off));
            off += n;
        end
        wait_x_drain(nwords);
    endtask

    // read n rows starting at base through s_axib into dst
    task automatic burst_res_read(input int base, input int n, input bit throttle,
                                  ref logic [31:0] dst [NX]);
        int off, k;
        off = 0;
        while (off < n) begin
            k = (n - off > 256) ? 256 : (n - off);
            axib_rd(16'(4 * (base + off)), k, throttle);
            for (int j = 0; j < k; j++) begin
                dst[off + j] = burst_buf[j];
                chk32({30'b0, burst_rsp[j]}, 32'd0,
                      $sformatf("RES burst RRESP row %0d", base + off + j));
            end
            off += k;
        end
    endtask

    // ------------------------------------------------------------------
    // main
    // ------------------------------------------------------------------
    logic [31:0] tmp, tmp2;
    logic [1:0]  rsp;
    int          base, len;
    int          wstall_mark, wbeat_mark, lstall_mark;
    int          seed_arg;

    initial begin
        // NOTE: the simulator's --seed switch does NOT reseed $urandom in
        // 5.020 (verified: an identical stream comes out for every --seed),
        // so the seed arrives as a plusarg and is applied explicitly here.
        // Whiten it and warm the RNG up - raw seeding leaves the top bits
        // nearly constant.
        seed_arg = 1;
        void'($value$plusargs("seed=%d", seed_arg));
        void'($urandom(32'(seed_arg) * 32'h9E37_79B1 ^ 32'hA5A5_1234));
        repeat (16) void'($urandom());

        l_awaddr = '0; l_awvalid = 0; l_wdata = '0; l_wstrb = 4'hF; l_wvalid = 0;
        l_bready = 0; l_araddr = '0; l_arvalid = 0; l_rready = 0;
        b_awid = '0; b_awaddr = '0; b_awlen = '0; b_awsize = 3'b010;
        b_awburst = 2'b01; b_awvalid = 0;
        b_wdata = '0; b_wstrb = 4'hF; b_wlast = 0; b_wvalid = 0; b_bready = 0;
        b_arid = '0; b_araddr = '0; b_arlen = '0; b_arsize = 3'b010;
        b_arburst = 2'b01; b_arvalid = 0; b_rready = 0;

        repeat (10) @(negedge aclk);
        aresetn = 1'b1; ui_rstn = 1'b1;
        repeat (20) @(negedge aclk);

        // ---------------- T1: shipped AXI-Lite regs unchanged ----------
        rd32(12'h034, tmp);
        chk32(tmp, 32'hFAB1C4A2, "T1 IDENT");
        // SHAPE implements [28:0] after G3.3: bit 29 (w8) went with the
        // engine mode, bit 28 (g64) went with its mode AND was immediately
        // taken back by ng as its seventh bit, so [31:29] are the three
        // spare bits and read back 0.  The test value sets every bit so the
        // round-trip covers the whole field AND the spares.
        wr32(12'h014, 32'hFFAB_C123);                       // SHAPE
        rd32(12'h014, tmp);
        chk32(tmp, 32'hFFAB_C123 & 32'h1FFF_FFFF, "T1 SHAPE round-trip");
        wr32(12'h028, 32'h0000_02A5);                       // XPTR
        rd32(12'h028, tmp);
        chk32(tmp, 32'h0000_02A5, "T1 XPTR round-trip");
        wr32(12'h02C, 32'h0000_0ABC);                       // RES_PTR
        rd32(12'h02C, tmp);
        chk32(tmp, 32'h0000_0ABC, "T1 RES_PTR round-trip");
        wr32(12'h008, 32'h1234_5680);                       // WBASE_LO
        rd32(12'h008, tmp);
        chk32(tmp, 32'h1234_5680, "T1 WBASE_LO round-trip");
        wr32(12'h010, 32'h0000_ABCD);                       // WBEATS
        rd32(12'h010, tmp);
        chk32(tmp, 32'h0000_ABCD, "T1 WBEATS round-trip");
        rd32(12'h004, tmp);
        check(tmp[3] == 1'b0, "T1 STATUS xfifo_ovfl must be clear");

        // ---------------- T2: fill the RES image -----------------------
        do_fill();
        if ($test$plusargs("sabotage")) res_exp[7] = res_exp[7] ^ 32'h0000_0100;

        // ---------------- T3: burst RES == AXI-Lite RES == image -------
        for (int c = 0; c < 13; c++) begin
            case (c)
                0: begin base = 0;    len = 1;   end
                1: begin base = 0;    len = 256; end
                2: begin base = 4095; len = 1;   end   // top row
                3: begin base = 1024; len = 256; end   // base != 0 (S12)
                4: begin base = 3840; len = 256; end   // last 4 KiB page
                5: begin base = 7;    len = 3;   end
                6: begin base = 1023; len = 1;   end
                7: begin base = 2048; len = 64;  end
                default: begin
                    // random, 4 KiB-respecting: 1024 rows per 4 KiB page
                    base = $urandom_range(0, 4095);
                    len  = $urandom_range(1, 256);
                    if (base % 1024 + len > 1024) len = 1024 - (base % 1024);
                    if (base + len > 4096)        len = 4096 - base;
                end
            endcase

            axib_rd(16'(4 * base), len, 1'b0);
            for (int k = 0; k < len; k++) begin
                chk32(burst_buf[k], res_exp[base + k],
                      $sformatf("T3 burst RES row %0d (case %0d base %0d len %0d)",
                                base + k, c, base, len));
                chk32({30'b0, burst_rsp[k]}, 32'd0,
                      $sformatf("T3 burst RRESP row %0d", base + k));
            end

            // the shipped AXI-Lite path must return exactly the same words
            axil_res_read(base, len, burst_buf);
            for (int k = 0; k < len; k++)
                chk32(burst_buf[k], res_exp[base + k],
                      $sformatf("T3 AXIL RES_DATA row %0d (case %0d)", base + k, c));
        end

        // ---------------- T4: concurrent AXI-Lite + burst --------------
        lstall_mark = lstall_cnt;
        for (int c = 0; c < 3; c++) begin
            int abase, bbase;
            abase = 32 + c * 517;
            bbase = 1024 + c * 700;
            fork
                begin : burst_side
                    axib_rd(16'(4 * bbase), 256, 1'b1);
                    for (int k = 0; k < 256; k++)
                        chk32(burst_buf[k], res_exp[bbase + k],
                              $sformatf("T4 burst row %0d (case %0d)", bbase + k, c));
                end
                begin : axil_side
                    logic [31:0] d;
                    wr32(12'h02C, 32'(abase));
                    for (int k = 0; k < 40; k++) begin
                        rd32(12'h030, d);
                        chk32(d, res_exp[abase + k],
                              $sformatf("T4 AXIL row %0d (case %0d)", abase + k, c));
                    end
                end
            join
        end
        @(negedge aclk);
        check(lstall_cnt > lstall_mark,
              "T4 coverage: AXI-Lite ARVALID never held off by a burst - addrb interlock not exercised");

        // ---------------- T5: XWIN through AXI-Lite --------------------
        do_fill();
        for (int k = 0; k < NX; k++) xw[k] = $urandom;
        push_xwin_axil(NX);
        rd32(12'h028, tmp);
        chk32(tmp, 32'(NX),
              $sformatf("T5 XPTR after %0d XWIN writes (12-bit counter, no wrap)", NX));
        rd32(12'h004, tmp);
        check(tmp[3] == 1'b0, "T5 xfifo_ovfl must stay clear");
        burst_res_read(0, NX, 1'b0, xback_a);
        for (int k = 0; k < NX; k++)
            chk32(xback_a[k], xw[k],
                  $sformatf("T5 AXIL XWIN word %0d reached x_mem", k));

        // ---------------- T6: XWIN through the burst window ------------
        do_fill();
        wr32(12'h028, 32'h0000_02A5);            // XPTR sentinel
        wstall_mark = wstall_cnt;
        wbeat_mark  = wbeat_cnt;
        push_xwin_burst(NX, 1'b1);               // same xw[], W throttled
        @(negedge aclk);
        check(wbeat_cnt - wbeat_mark == NX,
              $sformatf("T6 exactly %0d W beats accepted (got %0d)",
                        NX, wbeat_cnt - wbeat_mark));
        // with +slowui the 32-deep xpm_fifo_async cannot keep up with a
        // 250 MHz burst, so WREADY MUST have gone low on a full fifo
        if ($test$plusargs("slowui"))
            check(wstall_cnt - wstall_mark > 0,
                  "T6 coverage: WREADY never went low under +slowui - xf_full backpressure not exercised");
        rd32(12'h028, tmp);
        chk32(tmp, 32'h0000_02A5,
              "T6 XPTR untouched by burst writes (index is address-carried)");
        rd32(12'h004, tmp);
        check(tmp[3] == 1'b0, "T6 xfifo_ovfl must stay clear (no drops)");
        burst_res_read(0, NX, 1'b1, xback_b);
        for (int k = 0; k < NX; k++) begin
            chk32(xback_b[k], xw[k],
                  $sformatf("T6 burst XWIN word %0d reached x_mem", k));
            chk32(xback_b[k], xback_a[k],
                  $sformatf("T6 burst XWIN word %0d == AXIL XWIN word", k));
        end

        // ---------------- T7: partial burst write at a word offset -----
        do_fill();
        for (int k = 0; k < 100; k++) wr_buf[k] = $urandom;
        axib_wr(16'h4000 + 16'(4 * 613), 100, 1'b0, rsp);
        chk32({30'b0, rsp}, 32'd0, "T7 BRESP");
        wait_x_drain(100);
        for (int k = 0; k < 100; k++) res_exp[613 + k] = wr_buf[k];
        burst_res_read(0, NX, 1'b0, xback_b);
        for (int k = 0; k < NX; k++)
            chk32(xback_b[k], res_exp[k],
                  $sformatf("T7 row %0d after offset burst write", k));

        // ---------------- T8: SLVERR / window behaviour ----------------
        // read in the WRITE window
        axib_rd(16'h4000, 4, 1'b0);
        for (int k = 0; k < 4; k++)
            chk32({30'b0, burst_rsp[k]}, 32'd2,
                  $sformatf("T8 read@0x4000 beat %0d must be SLVERR", k));
        // read above the aperture
        axib_rd(16'h8000, 8, 1'b0);
        for (int k = 0; k < 8; k++)
            chk32({30'b0, burst_rsp[k]}, 32'd2,
                  $sformatf("T8 read@0x8000 beat %0d must be SLVERR", k));
        axib_rd(16'hF000, 1, 1'b0);
        chk32({30'b0, burst_rsp[0]}, 32'd2, "T8 read@0xF000 must be SLVERR");
        // a good read still works right after
        axib_rd(16'(4 * 2000), 16, 1'b0);
        for (int k = 0; k < 16; k++)
            chk32(burst_buf[k], res_exp[2000 + k],
                  $sformatf("T8 recovery read row %0d", 2000 + k));

        // write in the READ window -> SLVERR, and RES must not change
        for (int k = 0; k < 4; k++) wr_buf[k] = 32'hBADD_0000 + 32'(k);
        axib_wr(16'h0000, 4, 1'b0, rsp);
        chk32({30'b0, rsp}, 32'd2, "T8 write@0x0000 must be SLVERR");
        axib_wr(16'h8000, 4, 1'b0, rsp);
        chk32({30'b0, rsp}, 32'd2, "T8 write@0x8000 must be SLVERR");
        // 0x4000-0x6FFF IS the XWIN window now (3072 words, G3.3); 0x7000
        // is the first word past it, so that boundary is where SLVERR must
        // resume.
        axib_wr(16'h7000, 4, 1'b0, rsp);
        chk32({30'b0, rsp}, 32'd2, "T8 write@0x7000 (first word past XWIN) must be SLVERR");
        axib_wr(16'h7800, 4, 1'b0, rsp);
        chk32({30'b0, rsp}, 32'd2, "T8 write@0x7800 must be SLVERR");
        wait_x_drain(8);
        axib_rd(16'h0000, 8, 1'b0);
        for (int k = 0; k < 8; k++)
            chk32(burst_buf[k], res_exp[k],
                  $sformatf("T8 row %0d unchanged by rejected writes", k));
        // The OTHER half of the moved boundary: 0x5800 and 0x6000 were the
        // first two rejected addresses under the 6 KiB window and are now
        // INSIDE it, and 0x6FF0 is its last four words.  A boundary test
        // that only ever moves outward proves nothing about the bits that
        // moved, so all three must now be ACCEPTED and must land.
        for (int c = 0; c < 3; c++) begin
            int a16, w0;
            a16 = (c == 0) ? 16'h5800 : (c == 1) ? 16'h6000 : 16'h6FF0;
            w0  = (a16 - 16'h4000) / 4;
            for (int k = 0; k < 4; k++) wr_buf[k] = $urandom;
            axib_wr(16'(a16), 4, 1'b0, rsp);
            chk32({30'b0, rsp}, 32'd0,
                  $sformatf("T8 write@%h (inside the 12 KiB XWIN) must be OK", a16));
            wait_x_drain(4);
            for (int k = 0; k < 4; k++) res_exp[w0 + k] = wr_buf[k];
            axib_rd(16'(4 * w0), 4, 1'b0);
            for (int k = 0; k < 4; k++)
                chk32(burst_buf[k], res_exp[w0 + k],
                      $sformatf("T8 XWIN word %0d (addr %h) landed", w0 + k, a16));
        end
        // a good write still works right after
        for (int k = 0; k < 4; k++) wr_buf[k] = $urandom;
        axib_wr(16'h4000 + 16'(4 * 900), 4, 1'b0, rsp);
        chk32({30'b0, rsp}, 32'd0, "T8 recovery write BRESP");
        wait_x_drain(4);
        for (int k = 0; k < 4; k++) res_exp[900 + k] = wr_buf[k];
        axib_rd(16'(4 * 900), 4, 1'b0);
        for (int k = 0; k < 4; k++)
            chk32(burst_buf[k], res_exp[900 + k],
                  $sformatf("T8 recovery write row %0d", 900 + k));

        // ---------------- T9: throttled 256-beat read ------------------
        axib_rd(16'(4 * 1500), 256, 1'b1);
        for (int k = 0; k < 256; k++)
            chk32(burst_buf[k], res_exp[1500 + k],
                  $sformatf("T9 throttled read row %0d", 1500 + k));

        // ---------------- T10: W beats presented before AW -------------
        for (int k = 0; k < 8; k++) wr_buf[k] = $urandom;
        fork
            begin : t10_w
                int i, g;
                i = 0; g = 0;
                while (i < 8) begin
                    @(negedge aclk);
                    b_wvalid = 1'b1;
                    b_wdata  = wr_buf[i];
                    b_wstrb  = 4'hF;
                    b_wlast  = (i == 7);
                    if (b_wvalid && b_wready) i++;
                    g++;
                    if (g > 100000) $fatal(1, "T10 W timeout");
                end
                @(negedge aclk);
                b_wvalid = 1'b0; b_wlast = 1'b0;
            end
            begin : t10_aw
                int g;
                repeat (12) @(negedge aclk);     // AW deliberately late
                @(negedge aclk);
                b_awid = 1'b0; b_awaddr = 16'h4000 + 16'(4 * 300);
                b_awlen = 8'd7; b_awsize = 3'b010; b_awburst = 2'b01;
                b_awvalid = 1'b1;
                g = 0;
                while (!b_awready) begin
                    @(negedge aclk); g++;
                    if (g > 100000) $fatal(1, "T10 AW timeout");
                end
                @(negedge aclk);
                b_awvalid = 1'b0;
            end
        join
        b_bready = 1'b1;
        begin
            int g;
            g = 0;
            while (!b_bvalid) begin
                @(negedge aclk); g++;
                if (g > 100000) $fatal(1, "T10 B timeout");
            end
        end
        chk32({30'b0, b_bresp}, 32'd0, "T10 BRESP");
        @(negedge aclk);
        b_bready = 1'b0;
        wait_x_drain(8);
        for (int k = 0; k < 8; k++) res_exp[300 + k] = wr_buf[k];
        axib_rd(16'(4 * 300), 8, 1'b0);
        for (int k = 0; k < 8; k++)
            chk32(burst_buf[k], res_exp[300 + k],
                  $sformatf("T10 W-before-AW row %0d", 300 + k));

        // ---------------- final AXI-Lite sanity ------------------------
        rd32(12'h034, tmp);
        chk32(tmp, 32'hFAB1C4A2, "final IDENT");
        rd32(12'h004, tmp2);
        check(tmp2[3] == 1'b0, "final xfifo_ovfl clear");

        if (errors != 0)
            $fatal(1, "tb_mvshim_b: %0d ERRORS", errors);
        $display("tb_mvshim_b: PASS seed=%0d, 0 errors, gen=%0d, ui_clk=%s, s_axib W beats=%0d, WREADY-stall cyc=%0d, AXIL-AR-held-off cyc=%0d",
                 seed_arg, gen, $test$plusargs("slowui") ? "slow50M" : "fast300M",
                 wbeat_cnt, wstall_cnt, lstall_cnt);
        $finish;
    end

    // global watchdog
    initial begin
        #40_000_000;
        $fatal(1, "tb_mvshim_b: global timeout");
    end

endmodule
