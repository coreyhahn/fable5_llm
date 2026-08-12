// tb_vecnorm: vecnorm_unit vs layer_fixed golden vectors, bit-exact.
// Replays rmsnorm (mode 0, N=1024, in_f=8) and l2norm (mode 2, N=128,
// in_f=8, out_f=14) from tb/vectors/<seed>/  (cfg_eps == 0 throughout:
// that is the EPS-NORM back-compat invariant), then, with +seqdir=, the
// EPS-NORM cases from tb/scripts/gen_seq_vectors.py — 20 magnitude
// decades of DYNQ16 output plus the zero/tightest-block edges, checking
// BOTH the Q15 scale (eps_norm_scale) and the output (eps_norm_fx).
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
    logic [9:0] w_waddr = 0;
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

    logic [15:0] xv [1024];
    logic [15:0] wv [1024];
    logic [15:0] gv [1024];
    int errors = 0;

    task automatic run_case(input string xf, input string wf, input string gf,
                            input int n, input logic [1:0] mode,
                            input logic [3:0] nlog2, inf, outf);
        int i;
        $readmemh(xf, xv);
        $readmemh(gf, gv);
        if (mode != 2'd2) begin
            $readmemh(wf, wv);
            for (i = 0; i < n; i++) begin
                @(negedge clk);
                w_we = 1; w_waddr = 10'(i); w_wdata = wv[i];
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
    initial begin
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
        end else
            $display("NOTE: no +seqdir= -> EPS-NORM cases SKIPPED");
        if (errors == 0) begin
            if (n_eps > 0)
                $display("  EPS-NORM: %0d cases bit-exact (k %0d..%0d, scale_max %0d)",
                         n_eps, kmin_s, kmax_s, smax_s);
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
