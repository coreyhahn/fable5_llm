// tb_vecnorm_diff — rung-2 differential harness (docs/RUNG2_SPEC.md gate 1).
//
// ONE stream of x vectors + one wbuf preload drives TWO instances:
//   dut_r = vecnorm_legacy  (tb/legacy/vecnorm_legacy.sv, frozen HEAD copy)
//   dut_n = vecnorm_unit    (rtl/vecnorm_unit.sv, the II=1 rewrite)
// The two handshakes are INDEPENDENT — each DUT gets its own s_valid with
// random 0..5-cycle gaps and its own random m_ready backpressure — so the
// harness never assumes equal cycle counts or equal stall patterns.
//
// Per vector the harness compares
//   (a) the complete output element SEQUENCE (values, in order)
//   (b) the output element COUNT (a short-count shows up as a timeout, an
//       over-count as the post-drain "extra m_valid" check)
//   (c) busy low by the end of the vector, on both DUTs
//   (d) no further m_valid after the vector has drained
//
// Coverage: modes 0/1/2, n_log2 0..10 (n = 1..1024), in_f/out_f over the
// ranges the shipped TB uses (rmsnorm in_f=8; l2norm in_f=8 out_f=14;
// EPS-NORM in_f=S_F=13 out_f=DN_NORM_F=11), cfg_eps on/off with cfg_k over
// the full ISA range [-14,17], all-zero blocks (the only case where the
// 16-bit eps scale clamp fires), saturated blocks, n=1.
//
// plusargs
//   +seed=<n>      PRNG seed (own xorshift32, one state per process, so the
//                  gap/backpressure streams are independent of scheduling)
//   +nvec=<n>      randomized vectors after the directed cases (def 120)
//   +sabotage=<k>  comparator self-test: 1 = corrupt one x element fed to
//                  the new DUT, 2 = flip a bit in one compared output,
//                  3 = drop one output from the new count
//
`timescale 1ns/1ps

module tb_vecnorm_diff;

    logic clk = 0;
    /* verilator lint_off BLKSEQ */
    always #2 clk = ~clk;
    /* verilator lint_on BLKSEQ */
    logic rstn = 0;

    // ---- shared configuration + weight preload ----
    logic [1:0]        cfg_mode  = 2'd0;
    logic [3:0]        cfg_nlog2 = 4'd0, cfg_inf = 4'd8, cfg_outf = 4'd8;
    logic              cfg_eps   = 1'b0;
    logic signed [5:0] cfg_k     = 6'sd0;
    logic              start = 1'b0;
    logic              w_we = 1'b0;
    // 12 bits for rtl/vecnorm_unit.sv (4096 wbuf entries after G3.2); the
    // frozen legacy copy keeps its 10-bit port and is fed the low quarter
    // — this harness only ever runs n_log2 <= 10 (the legacy xbuf/wbuf are
    // 1024 deep and that copy is frozen), so nothing is lost.  The depths
    // ABOVE 1024 are covered by tb_vecnorm cases 5-8 against the golden
    // vectors, not differentially: there is no legacy twin to diff at
    // N=2048 or N=4096.
    logic [11:0]       w_waddr = '0;
    logic [15:0]       w_wdata = '0;

    // ---- per-DUT stream handshakes ----
    logic              sv_r = 1'b0, sr_r, sv_n = 1'b0, sr_n;
    logic signed [15:0] sd_r = '0,  sd_n = '0;
    logic              mv_r, mr_r = 1'b0, mv_n, mr_n = 1'b0;
    logic signed [15:0] md_r, md_n;
    logic              busy_r, busy_n;

    vecnorm_legacy #(.RSQRT_ROM("../rtl/roms/rsqrt_rom.hex")) dut_r (
        .clk, .rstn, .cfg_mode, .cfg_nlog2, .cfg_inf, .cfg_outf,
        .cfg_eps, .cfg_k, .start, .busy(busy_r),
        .w_we, .w_waddr(w_waddr[9:0]), .w_wdata,
        .s_valid(sv_r), .s_ready(sr_r), .s_data(sd_r),
        .m_valid(mv_r), .m_ready(mr_r), .m_data(md_r));

    vecnorm_unit #(.RSQRT_ROM("../rtl/roms/rsqrt_rom.hex")) dut_n (
        .clk, .rstn, .cfg_mode, .cfg_nlog2, .cfg_inf, .cfg_outf,
        .cfg_eps, .cfg_k, .start, .busy(busy_n),
        .w_we, .w_waddr, .w_wdata,
        .s_valid(sv_n), .s_ready(sr_n), .s_data(sd_n),
        .m_valid(mv_n), .m_ready(mr_n), .m_data(md_n));

    // ==================================================================
    // xorshift32 — one state per concurrent process so the feed-gap and
    // backpressure streams do not depend on fork scheduling order.
    // ==================================================================
    localparam int R_MAIN = 0, R_FR = 1, R_FN = 2, R_CR = 3, R_CN = 4;
    int unsigned rsv [5];

    /* verilator lint_off UNUSEDSIGNAL */
    function automatic int unsigned xs(input int idx);
    /* verilator lint_on UNUSEDSIGNAL */
        int unsigned s;
        s = rsv[idx];
        s = s ^ (s << 13);
        s = s ^ (s >> 17);
        s = s ^ (s << 5);
        rsv[idx] = s;
        return s;
    endfunction
    function automatic int mrand(input int m);
        return int'(xs(R_MAIN) % unsigned'(m));
    endfunction

    // ==================================================================
    // stimulus + capture storage
    // ==================================================================
    logic [15:0] xv [1024];
    logic [15:0] wv [1024];
    logic signed [15:0] out_r [1024];
    logic signed [15:0] out_n [1024];
    int cnt_r = 0, cnt_n = 0;

    int  sab = 0;
    int  nvec_done = 0;
    int  mode_cnt [4];
    int  eps_cnt = 0, zero_cnt = 0, nmax_seen = 0;
    int  kmin_s = 99, kmax_s = -99;
    longint unsigned tot_cyc_r = 0, tot_cyc_n = 0;

    // busy-duration monitors (report only; the DUTs may differ)
    int unsigned cyc = 0, startc = 0, endc_r = 0, endc_n = 0;
    logic clr = 1'b0;
    logic bz_r = 1'b0, bz_n = 1'b0;
    always_ff @(posedge clk) begin
        cyc <= cyc + 1;
        if (clr) begin
            startc <= cyc; endc_r <= cyc; endc_n <= cyc;
            bz_r <= 1'b0; bz_n <= 1'b0;
        end else if (rstn) begin
            if (busy_r) begin bz_r <= 1'b1; endc_r <= cyc; end
            if (busy_n) begin bz_n <= 1'b1; endc_n <= cyc; end
        end
    end

    // ==================================================================
    // stream drivers — inputs move at NEGEDGE only
    // ==================================================================
    localparam int GMAX = 400000;

    task automatic feed(input bit which, input int n);
        int i, gap;
        logic signed [15:0] dv;
        @(negedge clk);
        for (i = 0; i < n; i++) begin
            gap = which ? int'(xs(R_FN) % 6) : int'(xs(R_FR) % 6);
            if (gap > 0) begin
                if (which) sv_n = 1'b0; else sv_r = 1'b0;
                repeat (gap) @(negedge clk);
            end
            dv = signed'(xv[i]);
            // comparator self-test: perturb ONE element into the new DUT
            if ((sab == 1) && which && (i == (n > 3 ? 3 : 0))) dv = dv ^ 16'sd1;
            if (which) begin sd_n = dv; sv_n = 1'b1; end
            else       begin sd_r = dv; sv_r = 1'b1; end
            while (!(which ? sr_n : sr_r)) @(negedge clk);
            @(negedge clk);              // past the accepting posedge
        end
        if (which) sv_n = 1'b0; else sv_r = 1'b0;
    endtask

    task automatic collect(input bit which, input int n);
        int i, guard;
        bit rdy;
        i = 0; guard = 0;
        while ((i < n) && (guard < GMAX)) begin
            @(negedge clk);
            rdy = which ? ((xs(R_CN) % 4) != 0) : ((xs(R_CR) % 4) != 0);
            if (which) mr_n = rdy; else mr_r = rdy;
            if (rdy && (which ? mv_n : mv_r)) begin
                if (which) out_n[i] = md_n; else out_r[i] = md_r;
                i++;
            end
            guard++;
        end
        @(negedge clk);
        if (which) begin mr_n = 1'b0; cnt_n = i; end
        else       begin mr_r = 1'b0; cnt_r = i; end
    endtask

    // ==================================================================
    // x / w patterns
    // ==================================================================
    localparam int X_RAND = 0, X_ZERO = 1, X_SAT = 2, X_SMALL = 3,
                   X_ONE = 4, X_SPARSE = 5, X_BF = 6, X_NPAT = 7;

    task automatic fill_x(input int n, input int pat);
        for (int i = 0; i < n; i++) begin
            case (pat)
                X_ZERO  : xv[i] = 16'h0000;
                X_SAT   : xv[i] = (i % 2 == 0) ? 16'h7FFF : 16'h8000;
                X_SMALL : xv[i] = 16'(mrand(9) - 4);
                X_ONE   : xv[i] = (i == 0) ? 16'd16384 : 16'h0000;
                X_SPARSE: xv[i] = (i % 13 == 0) ? ((i % 26 == 0) ? 16'h7FFF
                                                                : 16'h8000)
                                                : 16'h0000;
                // DYNQ16 output envelope: |x|max always >= 16384
                X_BF    : xv[i] = (i == 0) ? 16'd16384
                                           : 16'(mrand(32769) - 16384);
                default : xv[i] = 16'(mrand(65536));
            endcase
        end
    endtask

    task automatic preload_w(input int n, input int pat);
        for (int i = 0; i < n; i++)
            wv[i] = (pat == 0) ? 16'(mrand(65536))
                  : (pat == 1) ? 16'h0000
                  : (pat == 2) ? 16'((mrand(32769)) - 16384)
                               : 16'h4000;
        for (int i = 0; i < n; i++) begin
            @(negedge clk);
            w_we = 1'b1; w_waddr = 12'(i); w_wdata = wv[i];
        end
        @(negedge clk);
        w_we = 1'b0;
    endtask

    // ==================================================================
    // one differential vector
    // ==================================================================
    task automatic run_vec(input logic [1:0] mode, input int nlog2,
                           input int inf, input int outf,
                           input bit eps, input int kv,
                           input int xpat, input int wpat,
                           input string tag);
        int n, nerr, extra;
        n = 1 << nlog2;
        fill_x(n, xpat);
        if (mode != 2'd2) preload_w(n, wpat);

        @(negedge clk);
        cfg_mode  = mode;
        cfg_nlog2 = 4'(nlog2);
        cfg_inf   = 4'(inf);
        cfg_outf  = 4'(outf);
        cfg_eps   = (mode == 2'd2) ? eps : 1'b0;
        cfg_k     = 6'(kv);
        clr = 1'b1;
        @(negedge clk);
        clr = 1'b0;
        start = 1'b1;
        @(negedge clk);
        start = 1'b0;

        cnt_r = -1; cnt_n = -1;
        fork
            feed(1'b0, n);
            feed(1'b1, n);
            collect(1'b0, n);
            collect(1'b1, n);
        join

        // ---- (b) counts ----
        if (cnt_r != n)
            $fatal(1, "LEGACY produced %0d of %0d outputs, vec%0d %s (mode%0d n%0d)",
                   cnt_r, n, nvec_done, tag, mode, n);
        if (sab == 3) cnt_n = cnt_n - 1;         // comparator self-test
        if (cnt_n != n)
            $fatal(1, "NEW produced %0d of %0d outputs, vec%0d %s (mode%0d n%0d inf%0d outf%0d eps%0b k%0d)",
                   cnt_n, n, nvec_done, tag, mode, n, inf, outf, eps, kv);

        // ---- (a) full output sequence ----
        if (sab == 2) out_n[(n > 2) ? 2 : 0] = out_n[(n > 2) ? 2 : 0] ^ 16'sd1;
        nerr = 0;
        for (int i = 0; i < n; i++)
            if (out_r[i] !== out_n[i]) begin
                nerr++;
                if (nerr <= 8)
                    $display("  OUT[%0d]: ref=%h new=%h  (x=%h)",
                             i, out_r[i], out_n[i], xv[i]);
            end
        if (nerr != 0)
            $fatal(1, "OUTPUT MISMATCH vec%0d %s: %0d/%0d elements (mode%0d nlog2%0d inf%0d outf%0d eps%0b k%0d xpat%0d)",
                   nvec_done, tag, nerr, n, mode, nlog2, inf, outf, eps, kv, xpat);

        // ---- (c) busy fallen, (d) nothing else comes out ----
        @(negedge clk);
        mr_r = 1'b1; mr_n = 1'b1;
        extra = 0;
        repeat (48) begin
            @(negedge clk);
            if (mv_r || mv_n) extra++;
        end
        @(negedge clk);
        mr_r = 1'b0; mr_n = 1'b0;
        if (extra != 0)
            $fatal(1, "EXTRA m_valid after the vector drained, vec%0d %s (%0d cycles, r=%0b n=%0b)",
                   nvec_done, tag, extra, mv_r, mv_n);
        if (busy_r)
            $fatal(1, "LEGACY busy still high, vec%0d %s", nvec_done, tag);
        if (busy_n)
            $fatal(1, "NEW busy still high at end of vector, vec%0d %s (mode%0d n%0d)",
                   nvec_done, tag, mode, n);
        if (!bz_r || !bz_n)
            $fatal(1, "busy never rose, vec%0d %s (r=%0b n=%0b)",
                   nvec_done, tag, bz_r, bz_n);

        tot_cyc_r += longint'(endc_r) - longint'(startc);
        tot_cyc_n += longint'(endc_n) - longint'(startc);
        mode_cnt[mode]++;
        if (cfg_eps) begin
            eps_cnt++;
            if (kv < kmin_s) kmin_s = kv;
            if (kv > kmax_s) kmax_s = kv;
        end
        if (xpat == X_ZERO) zero_cnt++;
        if (n > nmax_seen) nmax_seen = n;
        nvec_done++;
    endtask

    // ==================================================================
    int seed_arg = 1, nvec_arg = 120;

    initial begin
        int mo, nl, inf, outf, kv, xp, wp, rsel;
        bit ep;

        if (!$value$plusargs("seed=%d", seed_arg)) seed_arg = 1;
        if (!$value$plusargs("nvec=%d", nvec_arg)) nvec_arg = 120;
        if (!$value$plusargs("sabotage=%d", sab))  sab = 0;
        rsv[R_MAIN] = 32'(seed_arg) * 32'h9E37_79B1 + 32'h1234_5677;
        if (rsv[R_MAIN] == 0) rsv[R_MAIN] = 32'hDEAD_BEEF;
        rsv[R_FR] = rsv[R_MAIN] ^ 32'hA5A5_0001;
        rsv[R_FN] = rsv[R_MAIN] ^ 32'h5A5A_0002;
        rsv[R_CR] = rsv[R_MAIN] ^ 32'hC3C3_0003;
        rsv[R_CN] = rsv[R_MAIN] ^ 32'h3C3C_0004;
        for (int q = 0; q < 4; q++) mode_cnt[q] = 0;

        repeat (5) @(negedge clk);
        rstn = 1'b1;
        repeat (2) @(negedge clk);

        // ============ directed: the shipped geometries ============
        run_vec(2'd0, 10, 8,  8,  1'b0,  0, X_RAND,  0, "rmsnorm-1024");
        run_vec(2'd1, 10, 8,  8,  1'b0,  0, X_RAND,  0, "wnorm-1024");
        run_vec(2'd2,  7, 8,  14, 1'b0,  0, X_RAND,  0, "l2norm-128");
        run_vec(2'd2,  7, 13, 11, 1'b1,  0, X_BF,    0, "epsnorm-128");

        // ============ directed: edges ============
        for (int m = 0; m < 3; m++) begin
            run_vec(2'(m), 0, 8, 8, 1'b0, 0, X_RAND,  0, "n1");
            run_vec(2'(m), 3, 8, 8, 1'b0, 0, X_ZERO,  1, "zero");
            run_vec(2'(m), 4, 8, 8, 1'b0, 0, X_SAT,   0, "sat");
            run_vec(2'(m), 7, 8, 8, 1'b0, 0, X_SMALL, 3, "small");
            run_vec(2'(m), 7, 8, 8, 1'b0, 0, X_ONE,   2, "one");
            run_vec(2'(m), 5, 8, 8, 1'b0, 0, X_SPARSE,0, "sparse");
        end
        // EPS-NORM over the whole ISA k range, incl. the all-zero block
        // (the only case where the 16-bit scale clamp fires) and n=1
        run_vec(2'd2, 7, 13, 11, 1'b1, -14, X_ZERO, 0, "eps-k-14-zero");
        run_vec(2'd2, 7, 13, 11, 1'b1,   0, X_ZERO, 0, "eps-k0-zero");
        run_vec(2'd2, 7, 13, 11, 1'b1,   8, X_ZERO, 0, "eps-k8-zero");
        run_vec(2'd2, 7, 13, 11, 1'b1,  17, X_ZERO, 0, "eps-k17-zero");
        run_vec(2'd2, 7, 13, 11, 1'b1, -14, X_ONE,  0, "eps-k-14-one");
        run_vec(2'd2, 7, 13, 11, 1'b1,  17, X_ONE,  0, "eps-k17-one");
        run_vec(2'd2, 7, 13, 11, 1'b1,  -7, X_BF,   0, "eps-k-7-bf");
        run_vec(2'd2, 7, 13, 11, 1'b1,   9, X_BF,   0, "eps-k9-bf");
        run_vec(2'd2, 0, 13, 11, 1'b1,   3, X_BF,   0, "eps-n1");
        run_vec(2'd2, 10, 13, 11, 1'b1,  5, X_BF,   0, "eps-1024");
        run_vec(2'd2, 4, 4,  14, 1'b1,  17, X_BF,   0, "eps-inf4-k17");
        run_vec(2'd2, 10, 13, 4, 1'b1, -14, X_BF,   0, "eps-inf13-k-14");
        // cfg_eps == 0 back-compat: same geometry, eps low
        run_vec(2'd2, 7, 13, 11, 1'b0,  17, X_BF,   0, "eps-off-backcompat");

        // ============ randomized ============
        while (nvec_done < nvec_arg) begin
            mo   = mrand(3);
            rsel = mrand(12);
            case (rsel)
                0:       nl = 0;
                1:       nl = 1;
                2:       nl = 2;
                3,4:     nl = 3;
                5,6:     nl = 4;
                7:       nl = 5;
                8:       nl = 6;
                9:       nl = 7;
                10:      nl = 8;
                default: nl = 10;
            endcase
            inf  = 4 + mrand(10);          // 4..13
            outf = 4 + mrand(11);          // 4..14
            ep   = (mo == 2) && (mrand(2) == 0);
            kv   = -14 + mrand(32);        // -14..17
            xp   = mrand(X_NPAT);
            wp   = mrand(4);
            run_vec(2'(mo), nl, inf, outf, ep, kv, xp, wp, "rnd");
        end

        $display("  modes: 0:%0d 1:%0d 2:%0d | eps vectors=%0d (k %0d..%0d) | all-zero blocks=%0d | n_max=%0d",
                 mode_cnt[0], mode_cnt[1], mode_cnt[2], eps_cnt,
                 kmin_s, kmax_s, zero_cnt, nmax_seen);
        $display("  busy cycles: legacy=%0d new=%0d (speedup x100 = %0d)",
                 tot_cyc_r, tot_cyc_n,
                 (tot_cyc_n == 0) ? 0 : (tot_cyc_r * 100) / tot_cyc_n);
        $display("TB_VECNORM_DIFF PASS: %0d vectors bit-exact (seed %0d, random s_valid gaps 0..5, random m_ready)",
                 nvec_done, seed_arg);
        $finish;
    end

    initial begin
        #900ms;
        $display("WATCHDOG: vec %0d  busy r=%0b n=%0b  sr r=%0b n=%0b  mv r=%0b n=%0b",
                 nvec_done, busy_r, busy_n, sr_r, sr_n, mv_r, mv_n);
        $fatal(1, "watchdog");
    end

endmodule
