// tb_matvec_chan: full-chain stage-2 sim — the exact hardware flow:
//   AXI-Lite: cfg -> x load (XWIN) -> doorbell -> poll done ->
//   read results (RES_DATA) ... vs golden, bit-exact.
// matvec_chan runs with truly asynchronous aclk(250M)/ui_clk(300M);
// the AXI memory model (random AR/R timing) stands in for the MIG.
// 4 seeds via --seed; vectors via +vecdir.

`timescale 1ns/1ps

module tb_matvec_chan;

    localparam int MAXB = 1 << 16;
    localparam int MAXR = 1 << 12;
    localparam int MAXX = 1024;
    localparam int BASE_BEAT = 128;

    logic aclk = 0, ui_clk = 0;
    /* verilator lint_off BLKSEQ */
    always #2.000 aclk = ~aclk;       // 250 MHz
    always #1.667 ui_clk = ~ui_clk;   // ~300 MHz, async to aclk
    /* verilator lint_on BLKSEQ */
    logic aresetn = 0, ui_rstn = 0;

    // AXI-Lite
    logic [11:0] awaddr;  logic awvalid; logic awready;
    logic [31:0] wdata;   logic [3:0] wstrb; logic wvalid; logic wready;
    logic [1:0]  bresp;   logic bvalid; logic bready;
    logic [11:0] araddr;  logic arvalid; logic arready;
    logic [31:0] rdata;   logic [1:0] rresp; logic rvalid; logic rready;

    // AXI4 read
    logic [33:0]  m_araddr;
    logic [7:0]   m_arlen;
    logic [2:0]   m_arsize;
    logic [1:0]   m_arburst;
    logic         m_arvalid, m_arready;
    logic [511:0] m_rdata;
    logic [1:0]   m_rresp;
    logic         m_rlast, m_rvalid, m_rready;

    matvec_chan #(.CHAN_ID(4'd2)) dut (
        .aclk, .aresetn,
        .s_axil_awaddr(awaddr), .s_axil_awvalid(awvalid), .s_axil_awready(awready),
        .s_axil_wdata(wdata), .s_axil_wstrb(wstrb), .s_axil_wvalid(wvalid), .s_axil_wready(wready),
        .s_axil_bresp(bresp), .s_axil_bvalid(bvalid), .s_axil_bready(bready),
        .s_axil_araddr(araddr), .s_axil_arvalid(arvalid), .s_axil_arready(arready),
        .s_axil_rdata(rdata), .s_axil_rresp(rresp), .s_axil_rvalid(rvalid), .s_axil_rready(rready),
        // RUNG3 S5 burst window: idle here on purpose - this frozen stage-2
        // regression must keep passing through the AXI-Lite path alone, which
        // is exactly what it proves once the shim exists.  (Burst-window
        // coverage lives in tb_mvshim_b / tb_seq_chip.)
        .s_axib_awid(1'b0), .s_axib_awaddr(16'd0), .s_axib_awlen(8'd0),
        .s_axib_awsize(3'b010), .s_axib_awburst(2'b01), .s_axib_awvalid(1'b0),
        /* verilator lint_off PINCONNECTEMPTY */
        .s_axib_awready(), .s_axib_wready(), .s_axib_bid(), .s_axib_bresp(),
        .s_axib_bvalid(), .s_axib_arready(), .s_axib_rid(), .s_axib_rdata(),
        .s_axib_rresp(), .s_axib_rlast(), .s_axib_rvalid(),
        /* verilator lint_on PINCONNECTEMPTY */
        .s_axib_wdata(32'd0), .s_axib_wstrb(4'hF), .s_axib_wlast(1'b0),
        .s_axib_wvalid(1'b0), .s_axib_bready(1'b0),
        .s_axib_arid(1'b0), .s_axib_araddr(16'd0), .s_axib_arlen(8'd0),
        .s_axib_arsize(3'b010), .s_axib_arburst(2'b01), .s_axib_arvalid(1'b0),
        .s_axib_rready(1'b0),
        .ui_clk, .ui_rstn,
        .m_axi_araddr(m_araddr), .m_axi_arlen(m_arlen), .m_axi_arsize(m_arsize),
        .m_axi_arburst(m_arburst), .m_axi_arvalid(m_arvalid), .m_axi_arready(m_arready),
        .m_axi_rdata(m_rdata), .m_axi_rresp(m_rresp), .m_axi_rlast(m_rlast),
        .m_axi_rvalid(m_rvalid), .m_axi_rready(m_rready)
    );

    /* verilator lint_off UNUSEDSIGNAL */
    wire unused_ok = (^m_arsize) ^ (^m_arburst);
    /* verilator lint_on UNUSEDSIGNAL */

    // ---- AXI read slave model (ui_clk) ----
    logic [511:0] mem [MAXB];
    logic [33:0] q_addr [16];
    logic [7:0]  q_len  [16];
    logic [4:0]  q_wr = 0, q_rd = 0;
    wire  [4:0]  q_count = q_wr - q_rd;
    logic [7:0]  beat_idx = 0;
    logic rready_seen = 0;

    initial begin
        m_arready = 0; m_rvalid = 0; m_rresp = 2'b00; m_rlast = 0; m_rdata = '0;
        forever begin
            @(negedge ui_clk);
            m_arready = (5'(q_wr - q_rd) < 5'd14) && ($urandom_range(0, 9) < 7);
            if (m_arvalid && m_arready) begin
                q_addr[q_wr[3:0]] = m_araddr;
                q_len[q_wr[3:0]]  = m_arlen;
                q_wr = q_wr + 1'b1;
            end
            if (m_rvalid && rready_seen) begin   // see tb_streamer_engine note
                if (m_rlast) begin
                    q_rd = q_rd + 1'b1; beat_idx = 0;
                end else beat_idx = beat_idx + 1'b1;
                m_rvalid = 0;
            end
            if (!m_rvalid && q_wr != q_rd && ($urandom_range(0, 9) < 8)) begin
                m_rdata  = mem[32'(q_addr[q_rd[3:0]] >> 6) + 32'(beat_idx)];
                m_rlast  = (beat_idx == q_len[q_rd[3:0]]);
                m_rvalid = 1;
            end
            rready_seen = m_rready;
        end
    end

    // ---- AXI-Lite master tasks (negedge discipline, see tb_csr) ----
    int errors = 0;
    task automatic check(input bit cond, input string msg);
        if (!cond) begin errors++; $display("[%0t] FAIL: %s", $time, msg); end
    endtask

    task automatic wr32(input logic [11:0] addr, input logic [31:0] data);
        @(negedge aclk);
        awaddr = addr; awvalid = 1; wdata = data; wstrb = 4'hF; wvalid = 1;
        while (!(awready && wready)) @(negedge aclk);
        @(negedge aclk);
        awvalid = 0; wvalid = 0;
        while (!bvalid) @(negedge aclk);
        bready = 1;
        @(negedge aclk);
        bready = 0;
    endtask

    task automatic rd32(input logic [11:0] addr, output logic [31:0] data);
        @(negedge aclk);
        araddr = addr; arvalid = 1;
        while (!arready) @(negedge aclk);
        @(negedge aclk);
        arvalid = 0;
        while (!rvalid) @(negedge aclk);
        data = rdata;
        rready = 1;
        @(negedge aclk);
        rready = 0;
    endtask

    // ---- golden ----
    logic [31:0] golden [MAXR];
    logic [31:0] xwords [MAXX];
    logic [511:0] beats_raw [MAXB];
    /* verilator lint_off UNUSEDSIGNAL */
    int K, NG, SH, NROWS, BPR, G64, NBEATS;
    /* verilator lint_on UNUSEDSIGNAL */

    string vecdir;
    logic [31:0] rv, st;
    initial begin
        awvalid = 0; wvalid = 0; bready = 0; arvalid = 0; rready = 0;
        awaddr = '0; wdata = '0; wstrb = '0; araddr = '0;
        if (!$value$plusargs("vecdir=%s", vecdir)) $fatal(1, "need +vecdir=");
        begin
            int fd, n;
            G64 = 0;                       // 6th field optional (pre-v2 dirs)
            fd = $fopen({vecdir, "/params.txt"}, "r");
            if (fd == 0) $fatal(1, "cannot open params.txt");
            n = $fscanf(fd, "%d %d %d %d %d %d", K, NG, SH, NROWS, BPR, G64);
            if (n < 5) $fatal(1, "bad params.txt");
            if (n == 5) G64 = 0;
            $fclose(fd);
        end
        NBEATS = NROWS * BPR;
        $readmemh({vecdir, "/beats.hex"}, beats_raw);
        $readmemh({vecdir, "/y32.hex"},  golden);
        $readmemh({vecdir, "/x8.hex"},   xwords);
        for (int i = 0; i < NBEATS; i++) mem[BASE_BEAT + i] = beats_raw[i];

        repeat (8) @(negedge aclk);
        aresetn = 1; ui_rstn = 1;
        repeat (8) @(negedge aclk);

        $display("[%0t] phase: identity", $time);
        rd32(12'h034, rv); check(rv == 32'hFAB1C4A2, $sformatf("IDENT=%h", rv));

        $display("[%0t] phase: configure", $time);
        wr32(12'h008, 32'(BASE_BEAT * 64));     // WBASE_LO
        wr32(12'h00C, 32'h0);                   // WBASE_HI
        wr32(12'h010, 32'(NBEATS));             // WBEATS
        // SHAPE: bit 28 = g64 mode (0 = legacy G=128 rows, 1 = v2 G=64 rows)
        wr32(12'h014, {3'b0, 1'(G64[0]), 16'(NROWS), 6'(SH[5:0]), 6'(NG[5:0])});
        rd32(12'h010, rv); check(rv == 32'(NBEATS), "WBEATS readback");
        // g64 only: the extra CSR read would shift the AXI model's $urandom
        // stream, and the frozen g128 vector runs must stay cycle-reproducible
        // against the committed stage-2 evidence.
        if (G64 != 0) begin
            rd32(12'h014, rv);
            check(rv == {3'b0, 1'b1, 16'(NROWS), 6'(SH[5:0]), 6'(NG[5:0])},
                  $sformatf("SHAPE readback=%h (g64=%0d)", rv, G64));
        end

        $display("[%0t] phase: x load", $time);
        wr32(12'h028, 32'h0);
        for (int i = 0; i < (K + 3) / 4; i++)
            wr32(12'h024, xwords[i]);
        // XPTR is 10 bits and the x window holds exactly 1024 words, so the
        // maximum shape (K=4096) pushes 1024 words and wraps the pointer
        // back to 0 -- expected, not an overflow.
        rd32(12'h028, rv);
        check(rv == 32'(((K + 3) / 4) % 1024),
              $sformatf("XPTR=%0d want %0d (K=%0d)", rv, ((K + 3) / 4) % 1024, K));

        $display("[%0t] phase: doorbell", $time);
        wr32(12'h000, 32'h1);

        $display("[%0t] phase: poll", $time);
        begin
            int polls = 0;
            do begin
                repeat (20) @(negedge aclk);
                rd32(12'h004, st);
                polls++;
                if (polls > 50000) begin
                    check(0, $sformatf("timeout: STATUS=%h", st));
                    break;
                end
            end while (!st[1]);                  // done
        end
        check(!st[2], "err_rresp set");
        check(!st[3], "xfifo overflow");

        $display("[%0t] phase: results", $time);
        wr32(12'h02C, 32'h0);                    // RES_PTR = 0
        for (int r = 0; r < NROWS; r++) begin
            rd32(12'h030, rv);
            check(rv == golden[r[11:0]],
                  $sformatf("row %0d: y32=%h golden=%h", r, rv, golden[r[11:0]]));
        end

        // perf report
        begin
            logic [31:0] pc_lo, pc_hi, pb;
            rd32(12'h018, pc_lo); rd32(12'h01C, pc_hi); rd32(12'h020, pb);
            $display("perf: %0d beats in %0d cycles", pb, {pc_hi[15:0], pc_lo});
            check(pb == 32'(NBEATS), "perf_beats");
        end

        if (errors == 0) begin
            $display("TB_MATVEC_CHAN PASS: %0d rows bit-exact (K=%0d G64=%0d)",
                     NROWS, K, G64);
            $finish;
        end else
            $fatal(1, "TB_MATVEC_CHAN FAIL: %0d errors", errors);
    end

    initial begin
        #200ms;
        $fatal(1, "TB_MATVEC_CHAN FAIL: global watchdog");
    end

endmodule
