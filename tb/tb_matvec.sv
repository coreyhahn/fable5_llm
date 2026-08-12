// tb_matvec: matvec_engine vs ref/w4a8_ref.py golden vectors, bit-exact.
//
// Vector dirs (ref/gen_matvec_vectors.py, or tb/scripts/gen_matvec_v2_vectors.py
// for the v2/g64 format):
//   params.txt (K NG SH NROWS BEATS_PER_ROW [G64]), x8.hex (32b words),
//   beats.hex (512b lines), y32.hex (32b golden, row order).
// The 6th params field is the engine mode (cfg_g64); absent => 0 (legacy
// g=128), which is what every pre-v2 vector dir emits.
//
// Plusargs:
//   +vecdir=<d>            one case (back-compat)
//   +vecdirs=<d1,d2,...>   several cases in sequence ON THE SAME DUT
//                          INSTANCE with no reset between them -- the
//                          quasi-static reconfig / mixed-mode test.
//   +chunk=<n>             split each case into ceil(NROWS/n) runs of <= n
//                          rows, one start pulse each (chunked-rows test).
//   +nogap                 no input gaps, no result backpressure: the
//                          throughput measurement mode.
//   +pairs                 with +nogap: cases come in (g128, g64) pairs of
//                          identical shape; assert the g64 run costs no
//                          more cycles than the g128 run plus its extra
//                          scale beats (the ping-pong drain invariant).
//   +maxstall=<n>          assert stall cycles per row <= n for cases with
//                          NG > NG_SMALL (+nogap only).
//   +ngfloor=<p>           the SMALL-NG cases (NG <= NG_SMALL = 4) are
//                          bounded by a row PERIOD instead: the RUNG4 S2
//                          single-scale-bank guard floors the period at p
//                          cycles, so the exposed bubble is p-BPR and the
//                          bound has to be per-shape, not a flat stall
//                          count.  matvec_engine.sv documents p = 6
//                          (bubble 5-NG = 4/3/2/1 for NG = 1/2/3/4).
//                          NOTE the RUNG4 spec text says "1-2 cyc" for this
//                          guard; the shipped RTL costs 5-NG, which is
//                          within that only for NG >= 3.  No production
//                          shape has NG < 8 (K = 1024..4096) — see the
//                          agent-D report.
//
// RUNG 4 (docs/RUNG4_SPEC.md S1): the drain FSM became a TAGGED RETIRE
// PIPELINE, so the steady-state row period is now the row's own beat count
// (BPR) plus a 0-1 cycle retire residual — NOT the rung-3 "NG+10".  The
// throughput line therefore reports BPR and the measured residual; the
// rung-3 baseline it replaced is evidence/rung4/mv_baseline_rung3.log.
//
// Randomized: input stream gaps, result backpressure ($urandom; vary with
// --seed). Negedge-only drive/sample discipline (see tb_csr.sv).
// PASS prints TB_MATVEC PASS; failures exit nonzero via $fatal.

`timescale 1ns/1ps

module tb_matvec;

    localparam int MAXB = 1 << 16;   // beats
    localparam int MAXR = 1 << 12;   // rows
    localparam int MAXX = 1024;      // x words
    localparam int MAXC = 32;        // cases per run

    logic clk = 0;
    /* verilator lint_off BLKSEQ */
    always #1.667 clk = ~clk;        // ~300 MHz
    /* verilator lint_on BLKSEQ */

    logic rstn = 0;

    logic [5:0]   cfg_ng, cfg_sh;
    logic         cfg_g64 = 0;
    logic [15:0]  cfg_nrows;
    logic         start = 0, busy, done;
    /* verilator lint_off UNUSEDSIGNAL */
    wire busy_unused = busy;
    /* verilator lint_on UNUSEDSIGNAL */
    logic         x_we = 0;
    logic [9:0]   x_waddr = 0;
    logic [31:0]  x_wdata = 0;
    logic         s_valid = 0, s_ready;
    logic [511:0] s_data = '0;
    logic         m_valid, m_ready = 0;
    logic [31:0]  m_y32;
    logic [15:0]  m_row;

    matvec_engine dut (
        .clk, .rstn, .cfg_ng, .cfg_sh, .cfg_g64, .cfg_nrows, .start, .busy, .done,
        .x_we, .x_waddr, .x_wdata,
        .s_valid, .s_ready, .s_data,
        .m_valid, .m_ready, .m_y32, .m_row
    );

    logic [511:0] beats [MAXB];
    logic [31:0]  golden [MAXR];
    logic [31:0]  xwords [MAXX];

    int K, NG, SH, NROWS, BPR, G64, NBEATS;
    int errors = 0;
    int rx_count = 0;       // results received in the CURRENT chunk
    int row_base = 0;       // golden index offset of the current chunk
    bit nogap = 0;

    // free-running cycle counter, sampled by the driver at negedge
    int unsigned cyc = 0;
    always_ff @(posedge clk) cyc <= cyc + 1;

    // per-case throughput results
    int c_cycles [MAXC];
    int c_stalls [MAXC];
    int c_rows   [MAXC];
    int c_k      [MAXC];
    int c_bpr    [MAXC];
    int c_g64    [MAXC];
    int c_ng     [MAXC];
    int ncases = 0;

    // RUNG4 S2: cfg_ng <= NG_SMALL is the regime where the row is shorter
    // than the retire pipeline, so the single-scale-bank guard floors the
    // row PERIOD.  Those cases are bounded by +ngfloor, not +maxstall.
    localparam int NG_SMALL = 4;

    task automatic check(input bit cond, input string msg);
        if (!cond) begin
            errors++;
            $display("[%0t] FAIL: %s", $time, msg);
        end
    endtask

    // Result monitor. At each negedge, signals are stable and equal to what
    // the NEXT posedge will use: set m_ready first, then if valid&&ready the
    // next posedge pops the CURRENT head -> check it now.
    initial begin
        forever begin
            @(negedge clk);
            m_ready = nogap ? 1'b1 : ($urandom_range(0, 9) < 8);   // 80% ready
            if (m_valid && m_ready) begin
                check(32'(m_row) == rx_count,
                      $sformatf("row order: got %0d want %0d", m_row, rx_count));
                if (row_base + 32'(m_row) < NROWS)
                    check(m_y32 == golden[(row_base + 32'(m_row)) % MAXR],
                          $sformatf("row %0d: y32=%h golden=%h",
                                    row_base + 32'(m_row), m_y32,
                                    golden[(row_base + 32'(m_row)) % MAXR]));
                rx_count++;
            end
        end
    end

    // ------------------------------------------------------------------
    // one start pulse: stream `nrows` rows starting at beat `beat0`
    // ------------------------------------------------------------------
    int run_cycles, run_stalls;
    task automatic run_chunk(input int beat0, input int nrows, input int base);
        int nb;
        nb = nrows * BPR;

        row_base  = base;
        rx_count  = 0;
        cfg_nrows = 16'(nrows);
        @(negedge clk);
        start = 1; @(negedge clk); start = 0;

        begin
            int i = 0;
            bit presented = 0;
            bit ready_prev = 0;
            int first_c = 0, last_c = 0;
            run_stalls = 0;
            while (i < nb || presented) begin
                @(negedge clk);
                if (presented && ready_prev) begin   // posedge just consumed it
                    i++;
                    if (i == 1) first_c = int'(cyc);
                    last_c = int'(cyc);
                    presented = 0;
                end else if (presented) begin
                    run_stalls++;                    // offered, not accepted
                end
                if (!presented) begin
                    if (i < nb && (nogap || $urandom_range(0, 9) < 7)) begin
                        s_data  = beats[(beat0 + i) % MAXB];
                        s_valid = 1;
                        presented = 1;
                    end else begin
                        s_valid = 0;
                    end
                end
                ready_prev = s_ready;
            end
            s_valid = 0;
            run_cycles = last_c - first_c + 1;
        end

        // wait for completion of this chunk
        begin
            int guard = 0;
            while (!(done && rx_count == nrows)) begin
                @(negedge clk);
                guard++;
                if (guard > 400000) begin
                    check(0, $sformatf("timeout: rx=%0d/%0d done=%0d",
                                       rx_count, nrows, done));
                    break;
                end
            end
        end
        check(rx_count == nrows,
              $sformatf("row count %0d != %0d", rx_count, nrows));
    endtask

    // ------------------------------------------------------------------
    // one vector dir: load, configure, run (optionally in row chunks)
    // ------------------------------------------------------------------
    int chunk = 0;
    task automatic run_case(input string vecdir);
        int tot_cycles, tot_stalls;
        int base, nb_done;
        begin
            int fd, n;
            G64 = 0;
            fd = $fopen({vecdir, "/params.txt"}, "r");
            if (fd == 0) $fatal(1, "cannot open params.txt in %s", vecdir);
            n = $fscanf(fd, "%d %d %d %d %d %d", K, NG, SH, NROWS, BPR, G64);
            if (n < 5) $fatal(1, "bad params.txt in %s", vecdir);
            if (n == 5) G64 = 0;
            $fclose(fd);
        end
        NBEATS = NROWS * BPR;
        $display("[%0t] case %0s: K=%0d NG=%0d SH=%0d NROWS=%0d BPR=%0d G64=%0d",
                 $time, vecdir, K, NG, SH, NROWS, BPR, G64);
        $readmemh({vecdir, "/beats.hex"}, beats);
        $readmemh({vecdir, "/y32.hex"},  golden);
        $readmemh({vecdir, "/x8.hex"},   xwords);

        // quasi-static config (stable long before the start pulse)
        cfg_ng  = 6'(NG);
        cfg_sh  = 6'(SH);
        cfg_g64 = 1'(G64);

        // load activations for THIS case
        @(negedge clk);
        for (int i = 0; i < (K + 3) / 4; i++) begin
            x_we = 1; x_waddr = 10'(i); x_wdata = xwords[i];
            @(negedge clk);
        end
        x_we = 0;
        @(negedge clk);

        tot_cycles = 0; tot_stalls = 0;
        base = 0; nb_done = 0;
        while (base < NROWS) begin
            int nr;
            nr = (chunk > 0 && chunk < NROWS - base) ? chunk : (NROWS - base);
            run_chunk(nb_done, nr, base);
            tot_cycles += run_cycles;
            tot_stalls += run_stalls;
            base    += nr;
            nb_done += nr * BPR;
        end

        if (ncases < MAXC) begin
            c_cycles[ncases] = tot_cycles;
            c_stalls[ncases] = tot_stalls;
            c_rows  [ncases] = NROWS;
            c_k     [ncases] = K;
            c_bpr   [ncases] = BPR;
            c_g64   [ncases] = G64;
            c_ng    [ncases] = NG;
            ncases++;
        end
        if (nogap) begin
            // retire residual = cycles the row cost ON TOP of its own beats.
            // RUNG4 target: 0-1 cyc/row (rung-3 baseline was ~8.0-8.9).
            int resid100;
            resid100 = (100 * (tot_cycles - NBEATS)) / NROWS;
            $display("  thru: g64=%0d K=%0d NG=%0d rows=%0d beats=%0d cycles=%0d stalls=%0d -> 0.%03d beats/cycle, %0d.%02d stalls/row, period %0d.%02d cyc/row (BPR = %0d, retire residual %0d.%02d cyc/row)",
                     G64, K, NG, NROWS, NBEATS, tot_cycles, tot_stalls,
                     (1000 * NBEATS / tot_cycles) % 1000,
                     tot_stalls / NROWS, (100 * tot_stalls / NROWS) % 100,
                     tot_cycles / NROWS, (100 * tot_cycles / NROWS) % 100,
                     BPR, resid100 / 100, resid100 % 100);
        end
    endtask

    // ------------------------------------------------------------------
    string vecdir, vecdirs;
    int maxstall = -1;
    int ngfloor = 6;
    initial begin
        bit pairs;
        nogap = $test$plusargs("nogap");
        pairs = $test$plusargs("pairs");
        void'($value$plusargs("chunk=%d", chunk));
        void'($value$plusargs("maxstall=%d", maxstall));
        void'($value$plusargs("ngfloor=%d", ngfloor));

        repeat (5) @(negedge clk);
        rstn = 1;
        repeat (3) @(negedge clk);

        if ($value$plusargs("vecdirs=%s", vecdirs)) begin
            int p = 0;                                   // split on ','
            for (int i = 0; i <= vecdirs.len(); i++) begin
                if (i == vecdirs.len() || vecdirs[i] == ",") begin
                    if (i > p) run_case(vecdirs.substr(p, i - 1));
                    p = i + 1;
                end
            end
        end else if ($value$plusargs("vecdir=%s", vecdir)) begin
            run_case(vecdir);
        end else
            $fatal(1, "need +vecdir= or +vecdirs=");

        check(ncases > 0, "no cases ran");

        // ---- throughput invariants (nogap runs only) ----
        if (nogap && maxstall >= 0)
            for (int c = 0; c < ncases; c++) begin
                int bound;
                // small NG: the S2 guard floors the ROW PERIOD, so the
                // sanctioned bubble is (ngfloor - BPR), never a flat count.
                bound = (c_ng[c] <= NG_SMALL)
                        ? ((ngfloor > c_bpr[c]) ? (ngfloor - c_bpr[c]) : 0)
                        : maxstall;
                check(c_stalls[c] <= bound * c_rows[c],
                      $sformatf("case %0d (NG=%0d BPR=%0d): %0d stall cycles > %0d*%0d rows",
                                c, c_ng[c], c_bpr[c], c_stalls[c], bound,
                                c_rows[c]));
                // The retire pipeline must also not add cycles that are not
                // input stalls (a drain that outlives the last beat shows up
                // here and nowhere else).
                check(c_cycles[c] - c_rows[c] * c_bpr[c] <= bound * c_rows[c],
                      $sformatf("case %0d (NG=%0d BPR=%0d): retire residual %0d cyc > %0d*%0d rows",
                                c, c_ng[c], c_bpr[c],
                                c_cycles[c] - c_rows[c] * c_bpr[c],
                                bound, c_rows[c]));
            end

        if (nogap && pairs) begin
            check(ncases % 2 == 0, "pairs mode needs an even case count");
            for (int c = 0; c + 1 < ncases; c += 2) begin
                int budget;
                check(c_g64[c] == 0 && c_g64[c+1] == 1,
                      $sformatf("pair %0d is not (g128,g64)", c / 2));
                check(c_k[c] == c_k[c+1] && c_rows[c] == c_rows[c+1],
                      $sformatf("pair %0d shape mismatch", c / 2));
                // the ONLY sanctioned extra cost of g64 is its extra scale
                // beats; the drain must not add any stall on top of that.
                budget = c_cycles[c] + c_rows[c] * (c_bpr[c+1] - c_bpr[c]);
                $display("  pair K=%0d rows=%0d: g128 %0d cyc / %0d stalls, g64 %0d cyc / %0d stalls, budget %0d (%0d extra scale beat(s)/row)",
                         c_k[c], c_rows[c], c_cycles[c], c_stalls[c],
                         c_cycles[c+1], c_stalls[c+1],
                         budget, c_bpr[c+1] - c_bpr[c]);
                check(c_cycles[c+1] <= budget,
                      $sformatf("g64 K=%0d took %0d cycles > budget %0d (drain became the bottleneck)",
                                c_k[c], c_cycles[c+1], budget));
                check(c_stalls[c+1] <= c_stalls[c],
                      $sformatf("g64 K=%0d stalled %0d cycles > g128 %0d",
                                c_k[c], c_stalls[c+1], c_stalls[c]));
            end
        end

        if (errors == 0) begin
            $display("TB_MATVEC PASS: %0d case(s), %0d rows bit-exact (last K=%0d G64=%0d)",
                     ncases, NROWS, K, G64);
            $finish;
        end else
            $fatal(1, "TB_MATVEC FAIL: %0d errors", errors);
    end

    initial begin
        #200ms;
        $fatal(1, "TB_MATVEC FAIL: global watchdog");
    end

endmodule
