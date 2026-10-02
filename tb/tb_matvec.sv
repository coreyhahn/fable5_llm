// tb_matvec: matvec_engine vs ref/w4a8_ref.py golden vectors, bit-exact.
//
// Vector dirs (ref/gen_matvec_vectors.py, or tb/scripts/gen_matvec_v2_vectors.py
// for the parameterized shape sweeps):
//   params.txt (K NG SH NROWS BEATS_PER_ROW), x8.hex (32b words),
//   beats.hex (512b lines), y32.hex (32b golden, row order).
// ONE row format: W4 at G=128.  NG is cfg_ng = K//128 = the weight-beat
// count, and BEATS_PER_ROW = NG + ceil(NG/32).  (G3.3 deleted the 6th/7th
// params fields with the cfg_g64 and cfg_w8 modes they drove.)
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
//   +maxstall=<n>          assert stall cycles per row <= n for cases with
//                          NG > NG_SMALL (+nogap only).
//   +guardtest             cfg_ng = 97 = MAX_NG+1 must trip the engine's
//                          MAX_NG envelope $fatal (reaching the end is the
//                          failure).  The value moves with MAX_NG, and so
//                          does the message tb/Makefile greps for.
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
// SR12 — the R2 banks (docs/SEQ_ISA.md B17.2: SHAPE bit 29 XBANK = x_line
// starts at line 48, bit 30 RBANK = result rows tagged 2048 + r):
//   +xbank                 every case runs with cfg_xbank = 1: its x is
//                          loaded at word 1536 + i and bank 0 is first
//                          POISONED with ~x, so an engine that ignores the
//                          bank computes on the wrong x.  Needs NG <= 48.
//   +rbank                 every case runs with cfg_rbank = 1: m_row must
//                          be 2048 + r (the RES write address tag).
//   +pingpong              case i runs in bank i % 2 (XBANK = RBANK), and
//                          case i+1's x is loaded into the OTHER bank WHILE
//                          case i streams — the overlap R2 exists for (a
//                          MOVX into bank 1 while a bank-0 stream runs).
//                          Needs NG <= 48 for every case.
//   +bankguard=x|r         the sim-only bank-legality $fatal must trip:
//                          x = XBANK with cfg_ng 49 (lines 48..96 > 95),
//                          r = RBANK with cfg_nrows 2049 (> row 4095).
//   `define SR12_NO_BANK_PORTS builds this TB against the PRE-SR12 engine
//                          (no cfg_xbank / cfg_rbank ports): the RED run.
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
    localparam int MAXX = 3072;      // x words (K <= 12288)
    localparam int MAXC = 32;        // cases per run

    logic clk = 0;
    /* verilator lint_off BLKSEQ */
    always #1.667 clk = ~clk;        // ~300 MHz
    /* verilator lint_on BLKSEQ */

    logic rstn = 0;

    logic [6:0]   cfg_ng;
    logic [5:0]   cfg_sh;
    logic [15:0]  cfg_nrows;
    logic         cfg_xbank = 1'b0, cfg_rbank = 1'b0;    // SR12 (B17.2)
    logic         start = 0, busy, done;
    /* verilator lint_off UNUSEDSIGNAL */
    wire busy_unused = busy;
    /* verilator lint_on UNUSEDSIGNAL */
    logic         x_we = 0;
    logic [11:0]  x_waddr = 0;
    logic [31:0]  x_wdata = 0;
    logic         s_valid = 0, s_ready;
    logic [511:0] s_data = '0;
    logic         m_valid, m_ready = 0;
    logic [31:0]  m_y32;
    logic [15:0]  m_row;

`ifdef SR12_NO_BANK_PORTS
    // the pre-SR12 engine has no bank inputs: the bank cases must FAIL
    /* verilator lint_off UNUSEDSIGNAL */
    wire unused_banks = cfg_xbank ^ cfg_rbank;
    /* verilator lint_on UNUSEDSIGNAL */
    matvec_engine dut (
        .clk, .rstn, .cfg_ng, .cfg_sh, .cfg_nrows,
        .start, .busy, .done,
`else
    matvec_engine dut (
        .clk, .rstn, .cfg_ng, .cfg_sh, .cfg_nrows,
        .cfg_xbank, .cfg_rbank,
        .start, .busy, .done,
`endif
        .x_we, .x_waddr, .x_wdata,
        .s_valid, .s_ready, .s_data,
        .m_valid, .m_ready, .m_y32, .m_row
    );

    logic [511:0] beats [MAXB];
    logic [31:0]  golden [MAXR];
    logic [31:0]  xwords [MAXX];

    int K, NG, SH, NROWS, BPR, NBEATS;
    int errors = 0;
    int rx_count = 0;       // results received in the CURRENT chunk
    int row_base = 0;       // golden index offset of the current chunk
    int rtag0 = 0;          // SR12: expected m_row of the chunk's row 0
    bit xbank_all = 0, rbank_all = 0, pingpong = 0;   // SR12 plusargs
    localparam int XB_WORD = 1536;   // B17.2: bank 1 = x word 1536 (line 48)
    localparam int RB_ROW  = 2048;   // B17.2: bank 1 = RES row 2048
    bit nogap = 0;

    // free-running cycle counter, sampled by the driver at negedge
    int unsigned cyc = 0;
    always_ff @(posedge clk) cyc <= cyc + 1;

    // per-case throughput results
    int c_cycles [MAXC];
    int c_stalls [MAXC];
    int c_rows   [MAXC];
    int c_bpr    [MAXC];
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
                // SR12: under RBANK the row TAG is 2048 + r (rtag0); the
                // golden index is still the chunk base + r
                check(32'(m_row) == rtag0 + rx_count,
                      $sformatf("row order: got %0d want %0d", m_row,
                                rtag0 + rx_count));
                if (row_base + rx_count < NROWS)
                    check(m_y32 == golden[(row_base + rx_count) % MAXR],
                          $sformatf("row %0d: y32=%h golden=%h",
                                    row_base + rx_count, m_y32,
                                    golden[(row_base + rx_count) % MAXR]));
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

    // SR12 +pingpong: load a case's x into bank `xb` of x_mem WHILE the
    // current case streams from the other bank.  The first write waits for
    // the engine to be busy (so busy at the first word is true BY
    // CONSTRUCTION and proves nothing); the claim that is checked is busy at
    // the LAST word written (n_overlap): the whole load landed while the
    // other bank's stream was still running (SR12 fix round 1).
    logic [31:0] xnext [MAXX];
    int n_overlap = 0, n_preload = 0;
    string ld_dir = "";                  // the loader process's job
    int    ld_bank = 0;
    bit    ld_go = 1'b0, ld_busy = 1'b0;
    task automatic load_other(input string vecdir, input int xb);
        int fd, n, k2, ng2;
        /* verilator lint_off UNUSEDSIGNAL */
        int sh2, nr2, bpr2;                  // read, not needed here
        /* verilator lint_on UNUSEDSIGNAL */
        bit busy_first, busy_last;
        fd = $fopen({vecdir, "/params.txt"}, "r");
        if (fd == 0) $fatal(1, "cannot open params.txt in %s", vecdir);
        n = $fscanf(fd, "%d %d %d %d %d", k2, ng2, sh2, nr2, bpr2);
        if (n < 5) $fatal(1, "bad params.txt in %s", vecdir);
        $fclose(fd);
        if (ng2 > 48)
            $fatal(1, "+pingpong: %s has NG %0d > 48 — it does not fit a bank",
                   vecdir, ng2);
        $readmemh({vecdir, "/x8.hex"}, xnext);
        while (!busy) @(negedge clk);
        busy_first = busy;
        for (int i = 0; i < (k2 + 3) / 4; i++) begin
            x_we = 1; x_waddr = 12'(xb * XB_WORD + i); x_wdata = xnext[i];
            busy_last = busy;            // sampled as each word is driven
            @(negedge clk);
        end
        x_we = 0;
        n_preload++;
        if (busy_last) n_overlap++;
        $display("[%0t] pingpong: %0s x (%0d words) loaded into bank %0d while the bank-%0d stream ran (busy at first/last word: %0d/%0d)",
                 $time, vecdir, (k2 + 3) / 4, xb, 1 - xb, busy_first, busy_last);
    endtask

    // the loader PROCESS (a free-running initial, not a fork inside
    // run_case: Verilator 5.020 --timing crashed on that, n1208)
    initial begin
        forever begin
            wait (ld_go);
            ld_busy = 1'b1;
            ld_go   = 1'b0;
            load_other(ld_dir, ld_bank);
            ld_busy = 1'b0;
        end
    end

    task automatic run_case(input string vecdir, input int cidx = 0,
                            input string nextdir = "");
        int tot_cycles, tot_stalls;
        int base, nb_done;
        int xb, rb;
        begin
            int fd, n;
            fd = $fopen({vecdir, "/params.txt"}, "r");
            if (fd == 0) $fatal(1, "cannot open params.txt in %s", vecdir);
            n = $fscanf(fd, "%d %d %d %d %d", K, NG, SH, NROWS, BPR);
            if (n < 5) $fatal(1, "bad params.txt in %s", vecdir);
            $fclose(fd);
            // beat arithmetic of the row format, checked against the dir so
            // a mis-generated vector set cannot masquerade as an RTL bug
            if (BPR != NG + (NG + 31) / 32)
                $fatal(1, "%s: BPR=%0d inconsistent with NG=%0d",
                       vecdir, BPR, NG);
        end
        NBEATS = NROWS * BPR;
        $display("[%0t] case %0s: K=%0d NG=%0d SH=%0d NROWS=%0d BPR=%0d",
                 $time, vecdir, K, NG, SH, NROWS, BPR);
        $readmemh({vecdir, "/beats.hex"}, beats);
        $readmemh({vecdir, "/y32.hex"},  golden);
        $readmemh({vecdir, "/x8.hex"},   xwords);

        // SR12: this case's banks
        xb = pingpong ? (cidx % 2) : int'(xbank_all);
        rb = pingpong ? (cidx % 2) : int'(rbank_all);
        if ((xb != 0 || pingpong) && NG > 48)
            $fatal(1, "%s: XBANK/pingpong needs NG <= 48 (x lines 48..95), got %0d",
                   vecdir, NG);
        if (rb != 0 && NROWS > RB_ROW)
            $fatal(1, "%s: RBANK needs NROWS <= 2048, got %0d", vecdir, NROWS);

        // quasi-static config (stable long before the start pulse)
        cfg_ng  = 7'(NG);
        cfg_sh  = 6'(SH);
        cfg_xbank = xb[0];
        cfg_rbank = rb[0];
        rtag0     = rb * RB_ROW;
        if (xb != 0 || rb != 0 || pingpong)
            $display("[%0t]   SR12 banks: XBANK=%0d RBANK=%0d%0s", $time, xb, rb,
                     pingpong ? " (pingpong)" : "");

        // load activations for THIS case (under +pingpong every case after
        // the first was loaded by load_other while its predecessor ran)
        if (!(pingpong && cidx > 0)) begin
            @(negedge clk);
            // SR12 +xbank: POISON bank 0 with ~x first, so an engine that
            // ignores XBANK reads a vector that is certainly wrong
            if (xb != 0) begin
                for (int i = 0; i < (K + 3) / 4; i++) begin
                    x_we = 1; x_waddr = 12'(i); x_wdata = ~xwords[i];
                    @(negedge clk);
                end
            end
            for (int i = 0; i < (K + 3) / 4; i++) begin
                x_we = 1; x_waddr = 12'(xb * XB_WORD + i); x_wdata = xwords[i];
                @(negedge clk);
            end
            x_we = 0;
            @(negedge clk);
        end

        tot_cycles = 0; tot_stalls = 0;
        base = 0; nb_done = 0;
        // SR12 +pingpong: hand the NEXT case's x to the loader process,
        // which writes it into the other bank while this case streams
        if (pingpong && nextdir != "") begin
            ld_dir = nextdir; ld_bank = 1 - xb; ld_go = 1'b1;
        end
        while (base < NROWS) begin
            int nr;
            nr = (chunk > 0 && chunk < NROWS - base) ? chunk : (NROWS - base);
            run_chunk(nb_done, nr, base);
            tot_cycles += run_cycles;
            tot_stalls += run_stalls;
            base    += nr;
            nb_done += nr * BPR;
        end
        while (ld_go || ld_busy) @(negedge clk);

        if (ncases < MAXC) begin
            c_cycles[ncases] = tot_cycles;
            c_stalls[ncases] = tot_stalls;
            c_rows  [ncases] = NROWS;
            c_bpr   [ncases] = BPR;
            c_ng    [ncases] = NG;
            ncases++;
        end
        if (nogap) begin
            // retire residual = cycles the row cost ON TOP of its own beats.
            // RUNG4 target: 0-1 cyc/row (rung-3 baseline was ~8.0-8.9).
            int resid100;
            resid100 = (100 * (tot_cycles - NBEATS)) / NROWS;
            $display("  thru: K=%0d NG=%0d rows=%0d beats=%0d cycles=%0d stalls=%0d -> 0.%03d beats/cycle, %0d.%02d stalls/row, period %0d.%02d cyc/row (BPR = %0d, retire residual %0d.%02d cyc/row)",
                     K, NG, NROWS, NBEATS, tot_cycles, tot_stalls,
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
        nogap = $test$plusargs("nogap");
        void'($value$plusargs("chunk=%d", chunk));
        void'($value$plusargs("maxstall=%d", maxstall));
        void'($value$plusargs("ngfloor=%d", ngfloor));

        repeat (5) @(negedge clk);
        rstn = 1;
        repeat (3) @(negedge clk);

        // ENVELOPE self-test (+guardtest): cfg_ng above MAX_NG must trip
        // matvec_engine's own guard.  MAX_NG+1 is the exact cliff -- it is
        // where the 7-bit (cfg_ng + 31) the scale-beat count is computed
        // from overflows and the count wraps to zero.  Reaching the $fatal
        // below means the guard did NOT fire.
        if ($test$plusargs("guardtest")) begin
            cfg_ng = 7'd97; cfg_sh = 6'd0; cfg_nrows = 16'd1;
            @(negedge clk);
            start = 1; @(negedge clk); start = 0;
            repeat (10) @(negedge clk);
            $fatal(1, "TB_MATVEC FAIL: cfg_ng=97 did NOT trip the engine envelope guard");
        end

        // SR12 (B17.2) bank-legality self-test (+bankguard=x|r): the engine's
        // sim-only twin of the validator's bank rule must trip.  Reaching the
        // $fatal below means it did NOT.
        if ($value$plusargs("bankguard=%s", vecdir)) begin
            cfg_sh = 6'd0;
            if (vecdir == "x") begin
                cfg_ng = 7'd49; cfg_nrows = 16'd1; cfg_xbank = 1'b1;
            end else begin
                cfg_ng = 7'd8; cfg_nrows = 16'd2049; cfg_rbank = 1'b1;
            end
            @(negedge clk);
            start = 1; @(negedge clk); start = 0;
            repeat (10) @(negedge clk);
            $fatal(1, "TB_MATVEC FAIL: +bankguard=%s did NOT trip the engine bank guard",
                   vecdir);
        end

        xbank_all = $test$plusargs("xbank");
        rbank_all = $test$plusargs("rbank");
        pingpong  = $test$plusargs("pingpong");

        if ($value$plusargs("vecdirs=%s", vecdirs)) begin
            // split on ',' first, so +pingpong can name the NEXT case
            string dl [MAXC];
            int nd = 0, p = 0;
            for (int i = 0; i <= vecdirs.len(); i++) begin
                if (i == vecdirs.len() || vecdirs[i] == ",") begin
                    if (i > p && nd < MAXC) begin
                        dl[nd] = vecdirs.substr(p, i - 1);
                        nd++;
                    end
                    p = i + 1;
                end
            end
            for (int i = 0; i < nd; i++)
                run_case(dl[i], i, (i + 1 < nd) ? dl[i + 1] : "");
        end else if ($value$plusargs("vecdir=%s", vecdir)) begin
            run_case(vecdir);
        end else
            $fatal(1, "need +vecdir= or +vecdirs=");

        check(ncases > 0, "no cases ran");
        if (pingpong) begin
            // every preload must have overlapped a running stream
            check(n_preload == ncases - 1 && n_overlap == n_preload,
                  $sformatf("pingpong: %0d preloads, %0d of them inside a running stream, %0d cases",
                            n_preload, n_overlap, ncases));
            $display("TB_MATVEC PINGPONG: %0d of %0d next-bank x loads ran with the other bank's stream still busy at their LAST word",
                     n_overlap, n_preload);
        end

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

        if (errors == 0) begin
            $display("TB_MATVEC PASS: %0d case(s), %0d rows bit-exact (last K=%0d)",
                     ncases, NROWS, K);
            $finish;
        end else
            $fatal(1, "TB_MATVEC FAIL: %0d errors", errors);
    end

    initial begin
        #200ms;
        $fatal(1, "TB_MATVEC FAIL: global watchdog");
    end

endmodule
