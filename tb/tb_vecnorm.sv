// tb_vecnorm: vecnorm_unit vs layer_fixed golden vectors, bit-exact.
// Replays rmsnorm (mode 0, N=1024, in_f=8) and l2norm (mode 2, N=128,
// in_f=8, out_f=14) from tb/vectors/<seed>/  (cfg_eps == 0 throughout:
// that is the EPS-NORM back-compat invariant), then, with +seqdir=, the
// EPS-NORM cases from tb/scripts/gen_seq_c_vectors.py (this named the
// DELETED gen_seq_vectors.py) — 20 magnitude decades of DYNQ16 output plus
// the zero/tightest-block edges, on BOTH eps_norm_scale and eps_norm_fx.
//
// Cases 5/6 are the Qwen3.5-2B geometry: N=2048, cfg_nlog2 = 11, KEPT as
// the regression G3.2 must not disturb.  Cases 7/8 are the Qwen3.5-9B
// geometry G3.2 widened the datapath to: N=4096, cfg_nlog2 = 12.  Each
// pair runs mode 2 then mode 0, so both the weightless and the weighted
// path run at the full depth.  Every case is wrapped in a per-case CYCLE
// WATCHDOG: a counter exactly as wide as n_log2 wraps n_total to zero,
// which does not stall FILL (cnt+1 wraps too) but leaves OUT's `issue`
// (oidx != n_total) false forever — the unit accepts the whole vector and
// then never emits an element.  R-b hit that at 11 bits / N=2048; the
// 13-bit counters G3.2 installed are what keep N=4096 out of it.  A value
// comparator alone cannot see that; the watchdog can.
//
// plusargs
//   +vecdir=<d>  frozen unit vectors (tb/vectors/<seed>)   [required]
//   +seqdir=<d>  tb/scripts/gen_seq_c_vectors.py output    [optional]
//   +guardtest   POKE ONLY: configure the unsupported cfg_nlog2 = 13 and
//                pulse start.  The DUT's own guard must $fatal; if the
//                run survives, the TB prints GUARDTEST FAIL and exits 0
//                so the Makefile self-test (which expects a NON-zero
//                exit) trips.
`timescale 1ns/1ps
module tb_vecnorm;
    logic clk = 0;
    /* verilator lint_off BLKSEQ */
    always #2 clk = ~clk;
    /* verilator lint_on BLKSEQ */
    logic rstn = 0;

    logic [1:0] cfg_mode;
    logic [3:0] cfg_nlog2, cfg_inf, cfg_outf;
    logic start = 0, busy;
    /* verilator lint_off UNUSEDSIGNAL */
    wire busy_unused = busy;
    /* verilator lint_on UNUSEDSIGNAL */
    logic w_we = 0;
    logic [11:0] w_waddr = 0;
    logic [15:0] w_wdata = 0;
    logic s_valid = 0, s_ready;
    logic signed [15:0] s_data = 0;
    logic m_valid, m_ready = 0;
    logic signed [15:0] m_data;

    logic cfg_eps = 0;
    logic signed [5:0] cfg_k = 0;

    vecnorm_unit #(.RSQRT_ROM("../rtl/roms/rsqrt_rom.hex")) dut (
        .clk, .rstn, .cfg_mode, .cfg_nlog2, .cfg_inf, .cfg_outf,
        .cfg_eps, .cfg_k,
        .start, .busy, .w_we, .w_waddr, .w_wdata,
        .s_valid, .s_ready, .s_data, .m_valid, .m_ready, .m_data
    );

    logic [15:0] xv [4096];
    logic [15:0] wv [4096];
    logic [15:0] gv [4096];
    int errors = 0;

    // ---- per-case cycle watchdog ------------------------------------
    // A vector that never completes must fail at the offending case with
    // the machine state printed, not hang until the global #50ms.  50k
    // cycles is >4x the longest legal case (N=4096 = 4096 weight beats +
    // 4096 feed beats + 4096 drain beats + the rsqrt/prep latency).
    int    wd_cyc = 0;
    bit    wd_on  = 1'b0;
    string wd_tag = "";
    initial forever begin
        @(negedge clk);
        if (!wd_on) wd_cyc = 0;
        else begin
            wd_cyc = wd_cyc + 1;
            if (wd_cyc > 50000) begin
                string why;
                why = $sformatf("dut.st=%0d busy=%0d cnt=%0d n_total=%0d oidx=%0d ecnt=%0d m_valid=%0d s_ready=%0d",
                                dut.st, busy, dut.cnt, dut.n_total, dut.oidx,
                                dut.ecnt, m_valid, s_ready);
                $display("WATCHDOG: %s", why);
                $fatal(1, "tb_vecnorm: %s never completed after %0d cycles (%s)",
                       wd_tag, wd_cyc, why);
            end
        end
    end

    task automatic run_case(input string xf, input string wf, input string gf,
                            input int n, input logic [1:0] mode,
                            input logic [3:0] nlog2, inf, outf);
        int i;
        $readmemh(xf, xv);
        $readmemh(gf, gv);
        wd_tag = $sformatf("n=%0d mode=%0d nlog2=%0d", n, mode, nlog2);
        wd_cyc = 0;
        wd_on  = 1'b1;
        if (mode != 2'd2) begin
            $readmemh(wf, wv);
            for (i = 0; i < n; i++) begin
                @(negedge clk);
                w_we = 1; w_waddr = 12'(i); w_wdata = wv[i];
            end
            @(negedge clk); w_we = 0;
        end
        cfg_mode = mode; cfg_nlog2 = nlog2; cfg_inf = inf; cfg_outf = outf;
        @(negedge clk); start = 1; @(negedge clk); start = 0;
        // feed: present at a negedge; ready at that same negedge means the
        // next posedge accepts (ready is stable across the interval)
        for (i = 0; i < n; i++) begin
            @(negedge clk);
            s_data = signed'(xv[i]); s_valid = 1;
            while (!s_ready) @(negedge clk);
        end
        @(negedge clk);              // let the last accepting posedge pass
        s_valid = 0;
        // collect
        i = 0;
        fork begin
            int guard = 0;
            while (i < n) begin
                @(negedge clk);
                m_ready = 1;
                if (m_valid) begin
                    if (m_data !== signed'(gv[i])) begin
                        errors++;
                        if (errors < 8)
                            $display("FAIL [%0d]: got %h want %h", i, m_data, gv[i]);
                    end
                    i++;
                end
                guard++;
                if (guard > 200000) begin
                    errors++; $display("FAIL: timeout at elem %0d", i);
                    break;
                end
            end
            @(negedge clk);          // let the last handshake posedge pass
            m_ready = 0;
        end join
        @(negedge clk);
        wd_on = 1'b0;
    endtask

    // ==================================================================
    // EPS-NORM (sequencer gated mode) case replay
    // ==================================================================
    int n_eps = 0, kmin_s = 99, kmax_s = -99, smax_s = 0;

    task automatic run_eps(input string path);
        int fd, r, ncase, n, kv, sc, i, guard;
        /* verilator lint_off UNUSEDSIGNAL */
        int nlog2, inf, outf;      // narrowed into the 4-bit cfg ports
        /* verilator lint_on UNUSEDSIGNAL */
        fd = $fopen(path, "r");
        if (fd == 0) $fatal(1, "cannot open %s", path);
        r = $fscanf(fd, " %d", ncase);
        if (r != 1) $fatal(1, "bad header in %s", path);
        for (int c = 0; c < ncase; c++) begin
            r = $fscanf(fd, " %d %d %d %d %d %d", n, nlog2, inf, outf, kv, sc);
            if (r != 6) $fatal(1, "bad case %0d in %s", c, path);
            for (i = 0; i < n; i++) r = $fscanf(fd, " %h", xv[i]);
            for (i = 0; i < n; i++) r = $fscanf(fd, " %h", gv[i]);
            cfg_mode = 2'd2; cfg_nlog2 = 4'(nlog2);
            cfg_inf = 4'(inf); cfg_outf = 4'(outf);
            cfg_eps = 1'b1; cfg_k = 6'(kv);
            wd_tag = $sformatf("eps c%0d n=%0d nlog2=%0d k=%0d",
                               c, n, nlog2, kv);
            wd_cyc = 0;
            wd_on  = 1'b1;
            @(negedge clk); start = 1; @(negedge clk); start = 0;
            for (i = 0; i < n; i++) begin
                @(negedge clk);
                s_data = signed'(xv[i]); s_valid = 1;
                while (!s_ready) @(negedge clk);
            end
            @(negedge clk);
            s_valid = 0;
            i = 0; guard = 0;
            while (i < n) begin
                @(negedge clk);
                m_ready = 1;
                if (m_valid) begin
                    if (m_data !== signed'(gv[i])) begin
                        errors++;
                        if (errors < 8)
                            $display("FAIL eps c%0d k%0d [%0d]: got %h want %h",
                                     c, kv, i, m_data, gv[i]);
                    end
                    i++;
                end
                guard++;
                if (guard > 200000) begin
                    errors++; $display("FAIL eps c%0d: timeout at %0d", c, i);
                    break;
                end
            end
            @(negedge clk);
            m_ready = 0;
            // the Q15 multiplier itself: eps_norm_scale, checked directly
            if (int'(dut.scale_q) !== sc) begin
                errors++;
                if (errors < 8)
                    $display("FAIL eps c%0d k%0d scale: got %0d want %0d",
                             c, kv, dut.scale_q, sc);
            end
            wd_on = 1'b0;
            n_eps++;
            if (kv < kmin_s) kmin_s = kv;
            if (kv > kmax_s) kmax_s = kv;
            if (sc > smax_s) smax_s = sc;
            @(negedge clk);
        end
        $fclose(fd);
        cfg_eps = 1'b0; cfg_k = 6'sd0;
    endtask

    string vecdir, seqdir;
    initial begin : main_seq
        if ($test$plusargs("guardtest")) begin
            // The out-of-range n_log2 poke: the DUT must $fatal on it.
            repeat (5) @(negedge clk);
            rstn = 1;
            repeat (2) @(negedge clk);
            cfg_mode = 2'd2; cfg_nlog2 = 4'd13; cfg_inf = 4'd8;
            cfg_outf = 4'd14; cfg_eps = 1'b0; cfg_k = 6'sd0;
            @(negedge clk); start = 1; @(negedge clk); start = 0;
            repeat (20) @(negedge clk);
            // reached only if the guard did NOT fire: exit 0 so the
            // Makefile self-test (expects non-zero) reports the miss
            $display("GUARDTEST FAIL: cfg_nlog2=13 did NOT trip the DUT guard");
            $finish;
            disable main_seq;   // $finish does not stop THIS process
        end
        if (!$value$plusargs("vecdir=%s", vecdir)) $fatal(1, "need +vecdir=");
        repeat (5) @(negedge clk);
        rstn = 1;
        repeat (2) @(negedge clk);
        $display("case 1: rmsnorm");
        run_case({vecdir, "/rmsnorm_x16.hex"}, {vecdir, "/rmsnorm_w14.hex"},
                 {vecdir, "/rmsnorm_y16.hex"}, 1024, 2'd0, 4'd10, 4'd8, 4'd8);
        $display("case 2: l2norm");
        run_case({vecdir, "/l2norm_x16.hex"}, "",
                 {vecdir, "/l2norm_y16.hex"}, 128, 2'd2, 4'd7, 4'd8, 4'd14);
        if ($value$plusargs("seqdir=%s", seqdir)) begin
            $display("case 3: EPS-NORM");
            run_eps({seqdir, "/epsnorm_cases.txt"});
            // ARG2==0 back-compat: replay l2norm with cfg_eps low again and
            // require the SAME bytes as case 2
            $display("case 4: l2norm again (cfg_eps=0 back-compat)");
            run_case({vecdir, "/l2norm_x16.hex"}, "",
                     {vecdir, "/l2norm_y16.hex"}, 128, 2'd2, 4'd7, 4'd8, 4'd14);
            // ---- Qwen3.5-2B geometry: N=2048, cfg_nlog2 = 11.
            // KEPT as the regression: G3.2 widened the datapath and this
            // pair proves the 2B depth still runs bit-exact on it. ----
            $display("case 5: l2norm N=2048 (nlog2=11, no weights)");
            run_case({seqdir, "/l2n2048_x16.hex"}, "",
                     {seqdir, "/l2n2048_y16.hex"},
                     2048, 2'd2, 4'd11, 4'd8, 4'd14);
            $display("case 6: rmsnorm N=2048 (nlog2=11, 2048 weights)");
            run_case({seqdir, "/rms2048_x16.hex"},
                     {seqdir, "/rms2048_w14.hex"},
                     {seqdir, "/rms2048_y16.hex"},
                     2048, 2'd0, 4'd11, 4'd8, 4'd8);
            // ---- Qwen3.5-9B geometry: N=4096, cfg_nlog2 = 12.  This is
            // the depth G3.2 exists for: 13-bit counters, 4096-deep
            // xbuf/wbuf, 12-bit w_waddr.  Case 8 writes wbuf[4095], the
            // entry an 11-bit w_waddr could not reach. ----
            $display("case 7: l2norm N=4096 (nlog2=12, no weights)");
            run_case({seqdir, "/l2n4096_x16.hex"}, "",
                     {seqdir, "/l2n4096_y16.hex"},
                     4096, 2'd2, 4'd12, 4'd8, 4'd14);
            $display("case 8: rmsnorm N=4096 (nlog2=12, 4096 weights)");
            run_case({seqdir, "/rms4096_x16.hex"},
                     {seqdir, "/rms4096_w14.hex"},
                     {seqdir, "/rms4096_y16.hex"},
                     4096, 2'd0, 4'd12, 4'd8, 4'd8);
        end else
            $display("NOTE: no +seqdir= -> EPS-NORM cases SKIPPED");
        if (errors == 0) begin
            if (n_eps > 0)
                $display("  EPS-NORM: %0d cases bit-exact (k %0d..%0d, scale_max %0d)",
                         n_eps, kmin_s, kmax_s, smax_s);
            if (n_eps > 0) begin
                $display("  N=2048: l2norm + rmsnorm bit-exact (cfg_nlog2 = 11)");
                $display("  N=4096: l2norm + rmsnorm bit-exact (cfg_nlog2 = 12)");
            end
            $display("TB_VECNORM PASS: rmsnorm(1024) + l2norm(128) bit-exact");
            $finish;
        end else $fatal(1, "TB_VECNORM FAIL: %0d errors", errors);
    end
    initial begin
        #50ms;
        $display("WATCHDOG: dut.st=%0d busy=%0d cnt=%0d oidx=%0d m_valid=%0d s_ready=%0d",
                 dut.st, busy, dut.cnt, dut.oidx, m_valid, s_ready);
        $fatal(1, "watchdog");
    end
endmodule
