// tb_streamer_engine: integration sim for stage 2 —
//   behavioral AXI4 read slave (preloaded with the reference DDR image)
//   -> ddr_rd_streamer -> matvec_engine -> compare y32 vs golden.
//
// The AXI slave models DDR latency/jitter: random arready, random rvalid
// gaps, in-order single-ID bursts. Same vectors/flags as tb_matvec
// (+vecdir=...; --seed varies all randomization).
//
// PASS prints TB_STREAMER_ENGINE PASS; failures exit nonzero.

`timescale 1ns/1ps

module tb_streamer_engine;

    localparam int MAXB = 1 << 16;
    localparam int MAXR = 1 << 12;
    localparam int MAXX = 1024;
    localparam int BASE_BEAT = 64;       // weight image starts at 4 KiB

    logic clk = 0;
    /* verilator lint_off BLKSEQ */
    always #1.667 clk = ~clk;
    /* verilator lint_on BLKSEQ */
    logic rstn = 0;

    // ---- DUTs ----
    logic [33:0]  cfg_base;
    logic [31:0]  cfg_beats;
    logic         st_start = 0, st_busy, st_done, err_rresp;
    logic [47:0]  perf_cycles;
    logic [31:0]  perf_beats;

    logic [33:0]  araddr;
    logic [7:0]   arlen;
    logic [2:0]   arsize;
    logic [1:0]   arburst;
    logic         arvalid, arready;
    logic [511:0] rdata;
    logic [1:0]   rresp;
    logic         rlast, rvalid, rready;

    logic         b_valid, b_ready;
    logic [511:0] b_data;

    ddr_rd_streamer u_streamer (
        .clk, .rstn,
        .cfg_base, .cfg_beats, .start(st_start), .busy(st_busy), .done(st_done),
        .perf_cycles, .perf_beats,
        .m_araddr(araddr), .m_arlen(arlen), .m_arsize(arsize),
        .m_arburst(arburst), .m_arvalid(arvalid), .m_arready(arready),
        .m_rdata(rdata), .m_rresp(rresp), .m_rlast(rlast),
        .m_rvalid(rvalid), .m_rready(rready), .err_rresp(err_rresp),
        .s_valid(b_valid), .s_ready(b_ready), .s_data(b_data)
    );

    logic [5:0]   cfg_ng, cfg_sh;
    logic [15:0]  cfg_nrows;
    logic         en_start = 0, en_busy, en_done;
    logic         x_we = 0;
    logic [9:0]   x_waddr = 0;
    logic [31:0]  x_wdata = 0;
    logic         m_valid, m_ready = 0;
    logic [31:0]  m_y32;
    logic [15:0]  m_row;

    matvec_engine u_engine (
        .clk, .rstn, .cfg_ng, .cfg_sh, .cfg_g64(1'b0), .cfg_nrows,
        .start(en_start), .busy(en_busy), .done(en_done),
        .x_we, .x_waddr, .x_wdata,
        .s_valid(b_valid), .s_ready(b_ready), .s_data(b_data),
        .m_valid, .m_ready, .m_y32, .m_row
    );

    /* verilator lint_off UNUSEDSIGNAL */
    wire unused_ok = st_busy ^ en_busy ^ st_done ^ (^arsize) ^ (^arburst);
    /* verilator lint_on UNUSEDSIGNAL */

    // ---- behavioral AXI read slave ----
    logic [511:0] mem [MAXB];
    // AR queue (in-order, single ID)
    logic [33:0] q_addr [16];
    logic [7:0]  q_len  [16];
    logic [4:0]  q_wr = 0, q_rd = 0;
    logic [7:0]  beat_idx = 0;
    logic rready_seen = 0;

    initial begin
        arready = 0; rvalid = 0; rresp = 2'b00; rlast = 0; rdata = '0;
        forever begin
            @(negedge clk);
            // AR side: random ready when queue has space
            arready = (5'(q_wr - q_rd) < 5'd14) && ($urandom_range(0, 9) < 7);
            if (arvalid && arready) begin
                q_addr[q_wr[3:0]] = araddr;
                q_len[q_wr[3:0]]  = arlen;
                q_wr = q_wr + 1'b1;
            end
            // R side: serve head burst with random gaps
            // A pop happened at the posedge just crossed iff rvalid was
            // presented AND rready was high in that window — rready must be
            // sampled at the PREVIOUS negedge (rready_seen), not now: the
            // FIFO-full flag can toggle exactly at the posedge.
            if (rvalid && rready_seen) begin
                if (rlast) begin
                    q_rd = q_rd + 1'b1;
                    beat_idx = 0;
                end else
                    beat_idx = beat_idx + 1'b1;
                rvalid = 0;
            end
            if (!rvalid && q_wr != q_rd && ($urandom_range(0, 9) < 8)) begin
                rdata  = mem[32'(q_addr[q_rd[3:0]] >> 6) + 32'(beat_idx)];
                rlast  = (beat_idx == q_len[q_rd[3:0]]);
                rvalid = 1;
            end
            rready_seen = rready;   // value the NEXT posedge will use
        end
    end

    // ---- golden compare ----
    logic [31:0] golden [MAXR];
    logic [31:0] xwords [MAXX];
    logic [511:0] beats_raw [MAXB];

    /* verilator lint_off UNUSEDSIGNAL */
    int K, NG, SH, NROWS, BPR, NBEATS;   // upper bits of NG/SH unused by design
    /* verilator lint_on UNUSEDSIGNAL */
    int errors = 0, rx_count = 0;

    task automatic check(input bit cond, input string msg);
        if (!cond) begin errors++; $display("[%0t] FAIL: %s", $time, msg); end
    endtask

    // stream integrity: every beat the engine accepts must equal the image
    int beat_count = 0;
    initial begin
        forever begin
            @(negedge clk);
            if (b_valid && b_ready) begin
                if (beat_count < NBEATS && b_data != beats_raw[beat_count]) begin
                    check(0, $sformatf("beat %0d corrupt (row %0d, pos %0d)",
                                       beat_count, beat_count / BPR, beat_count % BPR));
                end
                beat_count++;
            end
        end
    end

    initial begin
        forever begin
            @(negedge clk);
            m_ready = ($urandom_range(0, 9) < 8);
            if (m_valid && m_ready) begin
                check(32'(m_row) == rx_count,
                      $sformatf("row order: got %0d want %0d", m_row, rx_count));
                if (32'(m_row) < NROWS)
                    check(m_y32 == golden[m_row[11:0]],
                          $sformatf("row %0d: y32=%h golden=%h", m_row, m_y32, golden[m_row[11:0]]));
                rx_count++;
            end
        end
    end

    string vecdir;
    initial begin
        if (!$value$plusargs("vecdir=%s", vecdir)) $fatal(1, "need +vecdir=");
        begin
            int fd, n;
            fd = $fopen({vecdir, "/params.txt"}, "r");
            if (fd == 0) $fatal(1, "cannot open params.txt");
            n = $fscanf(fd, "%d %d %d %d %d", K, NG, SH, NROWS, BPR);
            if (n != 5) $fatal(1, "bad params.txt");
            $fclose(fd);
        end
        NBEATS = NROWS * BPR;
        $readmemh({vecdir, "/beats.hex"}, beats_raw);
        $readmemh({vecdir, "/y32.hex"},  golden);
        $readmemh({vecdir, "/x8.hex"},   xwords);
        // place image at BASE_BEAT in slave memory
        for (int i = 0; i < NBEATS; i++) mem[BASE_BEAT + i] = beats_raw[i];

        cfg_ng    = 6'(NG[5:0]);
        cfg_sh    = 6'(SH[5:0]);
        cfg_nrows = 16'(NROWS);
        cfg_base  = 34'(BASE_BEAT) << 6;
        cfg_beats = 32'(NBEATS);

        repeat (5) @(negedge clk);
        rstn = 1;
        repeat (3) @(negedge clk);
        for (int i = 0; i < (K + 3) / 4; i++) begin
            x_we = 1; x_waddr = 10'(i); x_wdata = xwords[i];
            @(negedge clk);
        end
        x_we = 0;
        @(negedge clk);
        en_start = 1; st_start = 1; @(negedge clk); en_start = 0; st_start = 0;

        begin
            int guard = 0;
            while (!(en_done && rx_count == NROWS)) begin
                @(negedge clk);
                guard++;
                if (guard > 500000) begin
                    check(0, $sformatf("timeout: rx=%0d/%0d en_done=%0d st_done=%0d",
                                       rx_count, NROWS, en_done, st_done));
                    break;
                end
            end
        end
        check(rx_count == NROWS, $sformatf("row count %0d != %0d", rx_count, NROWS));
        check(!err_rresp, "RRESP error flagged");
        check(perf_beats == 32'(NBEATS), $sformatf("perf_beats=%0d != %0d", perf_beats, NBEATS));
        $display("perf: %0d beats in %0d cycles (%.1f%% bus util)",
                 perf_beats, perf_cycles, 100.0 * real'(perf_beats) / real'(perf_cycles));

        if (errors == 0) begin
            $display("TB_STREAMER_ENGINE PASS: %0d rows bit-exact (K=%0d)", NROWS, K);
            $finish;
        end else
            $fatal(1, "TB_STREAMER_ENGINE FAIL: %0d errors", errors);
    end

    initial begin
        #100ms;
        $fatal(1, "TB_STREAMER_ENGINE FAIL: global watchdog");
    end

endmodule
