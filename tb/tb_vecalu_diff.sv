// tb_vecalu_diff — rung-2 differential harness (docs/RUNG2_SPEC.md gate 1).
//
// ONE randomized command stream is driven into TWO instances:
//   dut_r = vec_alu_legacy   (tb/legacy/vec_alu_legacy.sv, frozen HEAD copy)
//   dut_n = vec_alu          (rtl/vec_alu.sv, the II=1 rewrite)
// each with its OWN 16K x 16 scratch model (two replicated read ports,
// 1-cycle registered read, read-first write).  NOTHING here assumes equal
// cycle counts: every observable is snapshotted at that DUT's own `done`.
//
// Per command the harness compares
//   (a) the FULL 16384-word scratch image
//   (b) e_out / k_out / amax_idx / amax_val / maxp_out, snapshotted at each
//       DUT's own done cycle AND re-checked settled
//   (c) the k_we pulse COUNT inside the command window (must be 0 or 1)
//   (d) per DUT: done cycle >= that DUT's own last w_en cycle  (spec item 1)
//   (e) the spec's overlap invariant on the new DUT: w_en -> w_addr != a_addr
//       and w_addr != b_addr.  Census only by default (the SERIAL design
//       already produces benign trailing-read collisions on the exact
//       in-place class: the element loop leaves a_addr parked on the last
//       source word while the final write retires).  +coll_fatal promotes
//       "live" collisions to $fatal.  The semantic form of the invariant is
//       +wfirst below, which is what actually proves collisions are inert.
//   +   busy low at command end; both DUTs idle.
//
// plusargs
//   +seed=<n>      PRNG seed (own xorshift32 -> reproducible on any sim)
//   +ncmd=<n>      randomized commands after the directed extremes (def 800)
//   +wfirst        new DUT's scratch uses a WRITE-first collision policy.
//                  Any read the design actually consumes that collides with
//                  a same-cycle write then diverges from the read-first
//                  legacy -> the overlap invariant is checked semantically.
//   +coll_fatal    make non-trailing raw address collisions fatal
//   +cfgscramble   scramble the NEW DUT's cfg_* one cycle after start (spec
//                  preservation item 6, "cfg latched at the start pulse").
//                  OFF by default: the SERIAL legacy consumes cfg_srca /
//                  cfg_dst / cfg_p0 live during the command, so this run
//                  only becomes meaningful once the pipeline lands.
//   +sabotage=<k>  comparator self-test (k=1 image, 2 aux outputs,
//                  3 k_we count, 4 done-vs-last-write); +sabat=<i> command
//
`timescale 1ns/1ps

module tb_vecalu_diff;

    localparam int MEMW = 16384;

    // op sets used by the directed pass
    localparam int OPS [12]    = '{0,1,2,3,4,5,6,7,8,9,10,12};
    localparam int WORDOPS [5] = '{2,3,4,5,7};
    localparam int SHIFTS [9]  = '{0,1,-1,15,-15,63,-63,64,-64};

    bit coll_fatal = 1'b0;

    logic clk = 0;
    /* verilator lint_off BLKSEQ */
    always #2 clk = ~clk;
    /* verilator lint_on BLKSEQ */
    logic rstn = 0;
    logic start = 0;

    // ---- command buses: separate copies so +cfgscramble can prove the
    //      "cfg latched at start" contract without disturbing the legacy ----
    logic [3:0]         c_op = '0,  n_op = '0;
    logic [11:0]        c_len = '0, n_len = '0;
    logic signed [16:0] c_p0 = '0,  n_p0 = '0;
    logic [13:0]        c_sa = '0,  n_sa = '0;
    logic [13:0]        c_sb = '0,  n_sb = '0;
    logic [13:0]        c_d  = '0,  n_d  = '0;

    // ---- reference (legacy) instance ----
    logic               busy_r, done_r;
    logic [3:0]         e_r;
    logic [17:0]        ai_r;
    logic signed [31:0] av_r;
    logic signed [6:0]  k_r;
    logic               kwe_r;
    logic [47:0]        mp_r;
    logic [13:0]        aa_r, ba_r, wa_r;
    logic signed [15:0] aq_r, bq_r, wd_r;
    logic               we_r;

    vec_alu_legacy #(.SIGMOID_ROM("../rtl/roms/sigmoid_pair_rom.hex")) dut_r (
        .clk, .rstn, .start, .busy(busy_r), .done(done_r),
        .cfg_op(c_op), .cfg_len(c_len), .cfg_p0(c_p0),
        .cfg_srca(c_sa), .cfg_srcb(c_sb), .cfg_dst(c_d),
        .e_out(e_r), .amax_idx(ai_r), .amax_val(av_r),
        .k_out(k_r), .k_we(kwe_r), .maxp_out(mp_r),
        .a_addr(aa_r), .a_q(aq_r), .b_addr(ba_r), .b_q(bq_r),
        .w_addr(wa_r), .w_data(wd_r), .w_en(we_r));

    // ---- device under test (current rtl/vec_alu.sv) ----
    logic               busy_n, done_n;
    logic [3:0]         e_n;
    logic [17:0]        ai_n;
    logic signed [31:0] av_n;
    logic signed [6:0]  k_n;
    logic               kwe_n;
    logic [47:0]        mp_n;
    logic [13:0]        aa_n, ba_n, wa_n;
    logic signed [15:0] aq_n, bq_n, wd_n;
    logic               we_n;

    // RUNG4 S5: vec_alu gained the 51-bit TOPK export.  The legacy copy in
    // tb/legacy/ has no such port, so it is simply captured here — the
    // differential claim is that adding it changed NOTHING else.
    /* verilator lint_off UNUSEDSIGNAL */
    logic [50:0] topk_bun_n;
    /* verilator lint_on UNUSEDSIGNAL */
    vec_alu #(.SIGMOID_ROM("../rtl/roms/sigmoid_pair_rom.hex")) dut_n (
        .topk_bun(topk_bun_n),
        .clk, .rstn, .start, .busy(busy_n), .done(done_n),
        .cfg_op(n_op), .cfg_len(n_len), .cfg_p0(n_p0),
        .cfg_srca(n_sa), .cfg_srcb(n_sb), .cfg_dst(n_d),
        .e_out(e_n), .amax_idx(ai_n), .amax_val(av_n),
        .k_out(k_n), .k_we(kwe_n), .maxp_out(mp_n),
        .a_addr(aa_n), .a_q(aq_n), .b_addr(ba_n), .b_q(bq_n),
        .w_addr(wa_n), .w_data(wd_n), .w_en(we_n));

    // ==================================================================
    // scratch models — one per DUT, identical contents at command start.
    // read-first write (mirror of tb_vec_alu.sv:43-48); +wfirst flips the
    // NEW model to write-first so a consumed collision would diverge.
    // ==================================================================
    logic signed [15:0] mem_r [MEMW];
    logic signed [15:0] mem_n [MEMW];
    bit wfirst = 1'b0;

    always_ff @(posedge clk) begin
        aq_r <= mem_r[aa_r];
        bq_r <= mem_r[ba_r];
        if (we_r) mem_r[wa_r] <= wd_r;
    end
    always_ff @(posedge clk) begin
        if (wfirst && we_n && (wa_n == aa_n)) aq_n <= wd_n;
        else                                  aq_n <= mem_n[aa_n];
        if (wfirst && we_n && (wa_n == ba_n)) bq_n <= wd_n;
        else                                  bq_n <= mem_n[ba_n];
        if (we_n) mem_n[wa_n] <= wd_n;
    end

    // ==================================================================
    // monitors (posedge — the DUTs' own state region)
    // ==================================================================
    logic clr = 1'b0;
    int   exp_w = 0;                      // writes this command must produce

    int unsigned cyc = 0, startc = 0;
    int unsigned lastw_r = 0, lastw_n = 0, donec_r = 0, donec_n = 0;
    int nw_r = 0, nw_n = 0, nk_r = 0, nk_n = 0;
    bit dseen_r = 1'b0, dseen_n = 1'b0;

    // cumulative overlap-invariant census (not cleared per command)
    int coll_r = 0, coll_n_tail = 0, coll_n_live = 0;
    int wcnt_mismatch = 0;

    logic [3:0]         e_s_r, e_s_n;
    logic [17:0]        ai_s_r, ai_s_n;
    logic signed [31:0] av_s_r, av_s_n;
    logic signed [6:0]  k_s_r, k_s_n;
    logic [47:0]        mp_s_r, mp_s_n;

    always_ff @(posedge clk) begin
        cyc <= cyc + 1;
        if (clr) begin
            startc  <= cyc;
            lastw_r <= 0; lastw_n <= 0;
            donec_r <= 0; donec_n <= 0;
            nw_r <= 0; nw_n <= 0; nk_r <= 0; nk_n <= 0;
            dseen_r <= 1'b0; dseen_n <= 1'b0;
        end else if (rstn) begin
            if (we_r)  begin lastw_r <= cyc; nw_r <= nw_r + 1; end
            if (we_n)  begin lastw_n <= cyc; nw_n <= nw_n + 1; end
            if (kwe_r) nk_r <= nk_r + 1;
            if (kwe_n) nk_n <= nk_n + 1;
            if (done_r) begin
                dseen_r <= 1'b1; donec_r <= cyc;
                e_s_r <= e_r; ai_s_r <= ai_r; av_s_r <= av_r;
                k_s_r <= k_r; mp_s_r <= mp_r;
            end
            if (done_n) begin
                dseen_n <= 1'b1; donec_n <= cyc;
                e_s_n <= e_n; ai_s_n <= ai_n; av_s_n <= av_n;
                k_s_n <= k_n; mp_s_n <= mp_n;
            end
            // (e) overlap invariant
            if (we_r && ((wa_r == aa_r) || (wa_r == ba_r)))
                coll_r <= coll_r + 1;
            if (we_n && ((wa_n == aa_n) || (wa_n == ba_n))) begin
                if (nw_n + 1 == exp_w) coll_n_tail <= coll_n_tail + 1;
                else                   coll_n_live <= coll_n_live + 1;
            end
        end
    end

    // ==================================================================
    // xorshift32 PRNG — reproducible independent of the simulator's $random
    // ==================================================================
    int unsigned rs = 32'h1357_9BDF;
    function automatic int unsigned rnd32();
        rs = rs ^ (rs << 13);
        rs = rs ^ (rs >> 17);
        rs = rs ^ (rs << 5);
        return rs;
    endfunction
    function automatic int rndm(input int m);   // 0 .. m-1
        return int'(rnd32() % unsigned'(m));
    endfunction

    // ==================================================================
    // command-stream helpers
    // ==================================================================
    function automatic bit is_pair(input logic [3:0] op);
        return (op == 4'd1) || (op == 4'd6) || (op == 4'd8)
            || (op == 4'd9) || (op == 4'd10) || (op == 4'd12);
    endfunction

    // source fill patterns (32-bit for pair ops, low half for word ops)
    localparam int P_RAND = 0, P_ZERO = 1, P_SAT = 2, P_MIN32 = 3,
                   P_KF31 = 4, P_KF16 = 5, P_SMALL = 6, P_DUP = 7,
                   P_MIX = 8, P_NEG = 9, P_NPAT = 10;

    function automatic logic [31:0] pat_val(input int pat, input int j);
        logic [31:0] v;
        int sel;
        sel = rndm(8);              // NOT inline in the case: one draw only
        case (pat)
            P_ZERO : v = 32'h0000_0000;
            P_SAT  : v = (j % 2 == 0) ? 32'h7FFF_FFFF : 32'h8000_0000;
            P_MIN32: v = 32'h8000_0000;                 // -2^31 abs trap
            P_KF31 : v = 32'h7FFF_8000;                 // norm top16 = FFFF
            P_KF16 : v = 32'h0000_FFFF;                 // bitlen 16, top16 FFFF
            P_SMALL: v = 32'(signed'(32'(rndm(7)) - 3));
            P_DUP  : v = (j % 7 == 3) ? 32'h7FFF_FFFF
                                      : 32'(signed'(32'(rndm(2001)) - 1000));
            P_NEG  : v = 32'(-32'(rndm(65536)) - 1);
            P_MIX  : case (sel)
                         0: v = rnd32();
                         1: v = 32'h0000_0000;
                         2: v = 32'h7FFF_FFFF;
                         3: v = 32'h8000_0000;
                         4: v = 32'h7FFF_8000;
                         5: v = 32'h0000_FFFF;
                         6: v = 32'hFFFF_FFFF;
                         default: v = 32'(signed'(32'(rndm(65)) - 32));
                     endcase
            default: v = rnd32();
        endcase
        return v;
    endfunction

    /* verilator lint_off UNUSEDSIGNAL */
    task automatic wmem(input int a, input logic [15:0] d);
    /* verilator lint_on UNUSEDSIGNAL */
        mem_r[a] = signed'(d);
        mem_n[a] = signed'(d);
    endtask

    task automatic fill_src(input int base, input int len, input bit pair,
                            input int pat);
        logic [31:0] v;
        for (int j = 0; j < len; j++) begin
            v = pat_val(pat, j);
            if (pair) begin
                wmem(base + 2*j,     v[15:0]);
                wmem(base + 2*j + 1, v[31:16]);
            end else begin
                wmem(base + j, v[15:0]);
            end
        end
    endtask

    task automatic init_mem();
        /* verilator lint_off UNUSEDSIGNAL */
        logic [31:0] v;
        /* verilator lint_on UNUSEDSIGNAL */
        for (int a = 0; a < MEMW; a++) begin
            v = rnd32();
            wmem(a, v[15:0]);
        end
    endtask

    // ==================================================================
    // per-command dispatch + full comparison
    // ==================================================================
    int  ncmd_done = 0;
    int  op_cnt [16];
    int  cls_cnt [4];
    int  len_max = 0;
    longint unsigned tot_cyc_r = 0, tot_cyc_n = 0;
    int  sab = 0, sabat = 2;
    bit  cfgscramble = 1'b0;

    task automatic do_cmd(input logic [3:0] op, input int len, input int p0,
                          input int sa, input int sb, input int d,
                          input int expw, input int cls, input string tag);
        int guard, nerr;
        logic [3:0]         e_c_n;
        logic [17:0]        ai_c_n;
        logic signed [31:0] av_c_n;
        logic signed [6:0]  k_c_n;
        logic [47:0]        mp_c_n;
        int                 nk_c_n;
        int unsigned        donec_c_n;

        // ---- dispatch (all DUT inputs move at NEGEDGE only) ----
        @(negedge clk);
        c_op = op; c_len = 12'(len); c_p0 = 17'(p0);
        c_sa = 14'(sa); c_sb = 14'(sb); c_d = 14'(d);
        n_op = op; n_len = 12'(len); n_p0 = 17'(p0);
        n_sa = 14'(sa); n_sb = 14'(sb); n_d = 14'(d);
        exp_w = expw;
        clr = 1'b1;
        @(negedge clk);
        clr = 1'b0;
        start = 1'b1;
        @(negedge clk);
        start = 1'b0;
        if (cfgscramble) begin       // spec item 6: cfg latched at start
            n_op = 4'(rndm(16)); n_len = 12'(rndm(4096));
            n_p0 = 17'(rndm(131072)); n_sa = 14'(rndm(MEMW));
            n_sb = 14'(rndm(MEMW));  n_d  = 14'(rndm(MEMW));
        end

        // ---- wait for BOTH (cycle counts are allowed to differ) ----
        guard = 0;
        while (!(dseen_r && dseen_n)) begin
            @(negedge clk);
            guard++;
            if (guard > 400000)
                $fatal(1, "TIMEOUT cmd%0d %s op%0d len%0d (done r=%0b n=%0b)",
                       ncmd_done, tag, op, len, dseen_r, dseen_n);
        end
        repeat (4) @(negedge clk);   // let the final writes retire

        // ---- comparator self-test hooks (inert unless +sabotage=) ----
        e_c_n = e_s_n; ai_c_n = ai_s_n; av_c_n = av_s_n;
        k_c_n = k_s_n; mp_c_n = mp_s_n;
        nk_c_n = nk_n; donec_c_n = donec_n;
        if (ncmd_done == sabat) begin
            case (sab)
                2: k_c_n = k_s_n ^ 7'sd1;
                3: nk_c_n = nk_n + 1;
                4: donec_c_n = (lastw_n > 0) ? (lastw_n - 1) : 0;
                default: ;
            endcase
        end

        // ---- (a) full scratch image ----
        nerr = 0;
        for (int a = 0; a < MEMW; a++)
            if (mem_r[a] !== mem_n[a]) begin
                nerr++;
                if (nerr <= 8)
                    $display("  MEM[%0d]: ref=%h new=%h", a, mem_r[a], mem_n[a]);
            end
        if (nerr != 0)
            $fatal(1, "SCRATCH MISMATCH cmd%0d %s op%0d len%0d p0=%0d sa=%0d sb=%0d d=%0d cls=%0d: %0d words",
                   ncmd_done, tag, op, len, p0, sa, sb, d, cls, nerr);

        // ---- (b) aux outputs, snapshotted at each DUT's own done ----
        if (e_s_r  !== e_c_n)
            $fatal(1, "e_out MISMATCH cmd%0d %s op%0d: ref=%0d new=%0d",
                   ncmd_done, tag, op, e_s_r, e_c_n);
        if (k_s_r  !== k_c_n)
            $fatal(1, "k_out MISMATCH cmd%0d %s op%0d p0=%0d: ref=%0d new=%0d",
                   ncmd_done, tag, op, p0, k_s_r, k_c_n);
        if (ai_s_r !== ai_c_n)
            $fatal(1, "amax_idx MISMATCH cmd%0d %s op%0d: ref=%0d new=%0d",
                   ncmd_done, tag, op, ai_s_r, ai_c_n);
        if (av_s_r !== av_c_n)
            $fatal(1, "amax_val MISMATCH cmd%0d %s op%0d: ref=%0d new=%0d",
                   ncmd_done, tag, op, av_s_r, av_c_n);
        if (mp_s_r !== mp_c_n)
            $fatal(1, "maxp_out MISMATCH cmd%0d %s op%0d: ref=%h new=%h",
                   ncmd_done, tag, op, mp_s_r, mp_c_n);
        // settled values (held between commands, spec items 3/4)
        if ((e_r !== e_s_r) || (k_r !== k_s_r) || (ai_r !== ai_s_r)
            || (av_r !== av_s_r) || (mp_r !== mp_s_r))
            $fatal(1, "LEGACY aux output moved after done, cmd%0d %s", ncmd_done, tag);
        if ((e_n !== e_s_n) || (k_n !== k_s_n) || (ai_n !== ai_s_n)
            || (av_n !== av_s_n) || (mp_n !== mp_s_n))
            $fatal(1, "NEW aux output moved after done (must be final AT done), cmd%0d %s op%0d",
                   ncmd_done, tag, op);

        // ---- (c) k_we pulse count ----
        if (nk_r > 1)
            $fatal(1, "LEGACY k_we pulsed %0d times cmd%0d %s op%0d",
                   nk_r, ncmd_done, tag, op);
        if (nk_r !== nk_c_n)
            $fatal(1, "k_we COUNT MISMATCH cmd%0d %s op%0d p0=%0d: ref=%0d new=%0d",
                   ncmd_done, tag, op, p0, nk_r, nk_c_n);

        // ---- (d) done no earlier than that DUT's own last w_en ----
        if (expw > 0) begin
            if (nw_r == 0)
                $fatal(1, "LEGACY issued no write, cmd%0d %s op%0d", ncmd_done, tag, op);
            if (nw_n == 0)
                $fatal(1, "NEW issued no write, cmd%0d %s op%0d", ncmd_done, tag, op);
            if (donec_r < lastw_r)
                $fatal(1, "LEGACY done(%0d) before last w_en(%0d) cmd%0d %s",
                       donec_r, lastw_r, ncmd_done, tag);
            if (donec_c_n < lastw_n)
                $fatal(1, "NEW done(%0d) BEFORE its last w_en(%0d) cmd%0d %s op%0d",
                       donec_c_n, lastw_n, ncmd_done, tag, op);
        end
        if (nw_r != nw_n) wcnt_mismatch++;

        // ---- busy honest ----
        if (busy_r || busy_n)
            $fatal(1, "busy still high after done, cmd%0d %s (r=%0b n=%0b)",
                   ncmd_done, tag, busy_r, busy_n);

        // ---- (e) live overlap-invariant violations ----
        if (coll_fatal && (coll_n_live != 0))
            $fatal(1, "OVERLAP INVARIANT: new DUT drove w_addr == a_addr/b_addr on a non-final write (cmd%0d %s op%0d cls%0d)",
                   ncmd_done, tag, op, cls);

        tot_cyc_r += longint'(donec_r) - longint'(startc);
        tot_cyc_n += longint'(donec_n) - longint'(startc);
        op_cnt[op]++;
        cls_cnt[cls]++;
        if (len > len_max) len_max = len;
        ncmd_done++;
    endtask

    // ---- region allocator: legal overlap classes only ----
    //   cls 0 disjoint | 1 exact in-place (1:1) | 2 narrowing (2:1)
    //   cls 3 pair in-place (2:2, op 9)
    task automatic run_case(input logic [3:0] op, input int len, input int p0,
                            input int cls, input int pat_a, input int pat_b,
                            input string tag);
        int spA, spB, spD, total, base, sa, sb, d, expw;
        bit pr;
        pr  = is_pair(op);
        spA = pr ? 2*len : len;
        spB = len;
        spD = (op == 4'd9) ? 2*len : ((op == 4'd10) ? 0 : len);
        total = (cls == 0) ? (spA + spB + spD) : (spA + spB);
        if (total > MEMW) $fatal(1, "region overflow %s len%0d", tag, len);
        base = rndm(MEMW - total + 1);
        sa = base;
        sb = base + spA;
        d  = (cls == 0) ? (base + spA + spB) : base;
        if (op == 4'd10) d = base;                 // op 10 never writes
        fill_src(sa, len, pr, pat_a);
        fill_src(sb, len, 1'b0, pat_b);
        expw = spD;
        do_cmd(op, len, p0, sa, sb, d, expw, cls, tag);
    endtask

    // per-op random p0 (see the header of tb/legacy/vec_alu_legacy.sv)
    function automatic int gen_p0(input logic [3:0] op);
        int r, sh;
        case (op)
            4'd0, 4'd4: return int'(rnd32() % 131072) - 65536;  // inert: prove it
            4'd2:       return int'(rnd32() % 131072) - 65536;  // Q15 constant
            4'd3: begin                                          // rshr64 (unsigned)
                r = rndm(100);
                if (r < 75)      return rndm(64);
                else if (r < 90) return 64 + rndm(8);            // pu_big
                else             return -1 - rndm(8);            // pu_big
            end
            4'd8: begin              // cfg_p0[6] = probe, MASKED from the shift
                r = rndm(100);
                if (r < 45)      return rndm(64);                // plain
                else if (r < 80) return 64 + rndm(64);           // probe
                else if (r < 90) return 128 + rndm(8);           // pu_big, no probe
                else if (r < 96) return 192 + rndm(8);           // probe + pu_big
                else             return -1 - rndm(8);            // negative
            end
            4'd1, 4'd6, 4'd9: begin                              // rshr64s
                r = rndm(100);
                if (r < 80) return rndm(41) - 20;
                else        return (rndm(2) == 0) ? (60 + rndm(12))
                                                  : -(60 + rndm(12));
            end
            4'd5, 4'd7: begin
                r = rndm(100);
                if (r < 85) return rndm(33) - 16;
                else        return (rndm(2) == 0) ? (60 + rndm(8))
                                                  : -(60 + rndm(8));
            end
            4'd12: begin        // [1]=kclamp, [0]=XRF select; rest inert
                sh = rndm(4);
                if (rndm(4) == 0) sh = sh | (rndm(256) << 2);
                return sh;
            end
            default: return 0;
        endcase
    endfunction

    function automatic int gen_len();
        int sel;
        sel = rndm(19);
        case (sel)
            0,1,2:    return 1;
            3,4:      return 2;
            5,6:      return 3;
            7,8,9,10: return 16;
            11,12,13: return 100;
            14,15,16: return 128;
            17:       return 1024;
            default:  return 2048;
        endcase
    endfunction

    function automatic int gen_cls(input logic [3:0] op);
        if (op inside {4'd0, 4'd10, 4'd12}) return 0;      // 2-pass / no-write
        if (rndm(2) == 0) return 0;
        if (op == 4'd9) return 3;
        if (is_pair(op)) return 2;                          // narrowing (2:1)
        return 1;                                           // exact in-place
    endfunction

    // ==================================================================
    // directed extremes (deterministic per seed, run first)
    // ==================================================================
    task automatic directed();
        // ---- len = 1 on every op, plus a plain pass over every op ----
        for (int o = 0; o < 12; o++) begin
            logic [3:0] op;
            op = 4'(OPS[o]);
            run_case(op, 16, gen_p0(op), 0, P_RAND, P_RAND, "warm");
            run_case(op, 1,  gen_p0(op), 0, P_RAND, P_RAND, "len1");
            run_case(op, 2,  gen_p0(op), 0, P_RAND, P_RAND, "len2");
        end

        // ---- DYNQ8 (op 0): maxabs 0 / 32767 / -32768 ----
        run_case(4'd0, 64,  0, 0, P_ZERO,  P_RAND, "dq8-zero");
        run_case(4'd0, 64,  0, 0, P_SAT,   P_RAND, "dq8-sat");   // 0x7FFF/0x8000
        run_case(4'd0, 1,   0, 0, P_SAT,   P_RAND, "dq8-sat1");
        run_case(4'd0, 128, 0, 0, P_SMALL, P_RAND, "dq8-small");
        run_case(4'd0, 128, 0, 0, P_KF16,  P_RAND, "dq8-ffff");

        // ---- DYNQ16 (op 12): both kclamp modes x the k_fix boundary ----
        for (int kc = 0; kc < 2; kc++) begin
            int p0;
            p0 = (kc << 1);
            run_case(4'd12, 64, p0, 0, P_ZERO,  P_RAND, "dq16-zero");
            run_case(4'd12, 64, p0, 0, P_KF31,  P_RAND, "dq16-kfix31");
            run_case(4'd12, 64, p0, 0, P_KF16,  P_RAND, "dq16-kfix16");
            run_case(4'd12, 64, p0, 0, P_MIN32, P_RAND, "dq16-min32");
            run_case(4'd12, 64, p0, 0, P_SAT,   P_RAND, "dq16-sat");
            run_case(4'd12, 64, p0, 0, P_SMALL, P_RAND, "dq16-small");
            run_case(4'd12, 1,  p0, 0, P_KF31,  P_RAND, "dq16-kfix31-l1");
            run_case(4'd12, 1,  p0, 0, P_MIN32, P_RAND, "dq16-min32-l1");
            run_case(4'd12, 128, p0 | 1, 0, P_MIX, P_RAND, "dq16-mix");
        end

        // ---- AMAX32 (op 10): chained scans, duplicates, fresh resets ----
        run_case(4'd10, 64, 1, 0, P_DUP,   P_RAND, "amax-fresh-dup");
        run_case(4'd10, 64, 0, 0, P_DUP,   P_RAND, "amax-chain-dup");
        run_case(4'd10, 64, 0, 0, P_SMALL, P_RAND, "amax-chain-small");
        run_case(4'd10, 64, 0, 0, P_MIN32, P_RAND, "amax-chain-min32");
        run_case(4'd10, 1,  0, 0, P_SAT,   P_RAND, "amax-chain-l1");
        run_case(4'd10, 64, 1, 0, P_NEG,   P_RAND, "amax-fresh-neg");
        run_case(4'd10, 64, 0, 0, P_NEG,   P_RAND, "amax-chain-neg");
        run_case(4'd10, 64, 1, 0, P_ZERO,  P_RAND, "amax-fresh-zero");
        run_case(4'd10, 64, 0, 0, P_SAT,   P_RAND, "amax-chain-sat");
        run_case(4'd10, 128, 1, 0, P_MIX,  P_RAND, "amax-fresh-mix");
        run_case(4'd10, 128, 0, 0, P_MIX,  P_RAND, "amax-chain-mix");

        // ---- EMUL32 (op 8): probe on/off over the same inputs ----
        for (int sh = 0; sh < 16; sh += 5) begin
            run_case(4'd8, 64, sh,      0, P_MIX,   P_MIX,  "emul32");
            run_case(4'd8, 64, sh | 64, 0, P_MIX,   P_MIX,  "emul32-probe");
            run_case(4'd8, 64, sh | 64, 0, P_KF16,  P_KF16, "probe-kfix16");
            run_case(4'd8, 64, sh | 64, 0, P_KF31,  P_SAT,  "probe-kfix48");
            run_case(4'd8, 64, sh | 64, 0, P_ZERO,  P_RAND, "probe-zero");
            run_case(4'd8, 64, sh | 64, 0, P_MIN32, P_SAT,  "probe-min32");
            run_case(4'd8, 1,  sh | 64, 0, P_KF31,  P_SAT,  "probe-l1");
            run_case(4'd8, 64, sh,      2, P_MIX,   P_MIX,  "emul32-narrow");
            run_case(4'd8, 64, sh | 64, 2, P_MIX,   P_MIX,  "probe-narrow");
        end

        // ---- shift-field extremes on the rshr64s / rshr64 ops ----
        for (int si = 0; si < 9; si++) begin
            int sv;
            sv = SHIFTS[si];
            run_case(4'd1, 64, sv, 0, P_MIX,   P_RAND, "sh32");
            run_case(4'd9, 64, sv, 0, P_MIX,   P_RAND, "sh32w");
            run_case(4'd6, 64, sv, 0, P_MIX,   P_RAND, "silu32");
            run_case(4'd1, 64, sv, 2, P_MIN32, P_RAND, "sh32-narrow-min32");
            run_case(4'd9, 64, sv, 3, P_MIN32, P_RAND, "sh32w-inplace-min32");
        end

        // ---- word ops in-place + saturation ----
        for (int oi = 0; oi < 5; oi++) begin
            logic [3:0] op;
            op = 4'(WORDOPS[oi]);
            run_case(op, 64, gen_p0(op), 1, P_SAT,   P_SAT,   "w-inplace-sat");
            run_case(op, 64, gen_p0(op), 1, P_ZERO,  P_ZERO,  "w-inplace-zero");
            run_case(op, 64, gen_p0(op), 0, P_MIX,   P_MIX,   "w-mix");
            run_case(op, 1,  gen_p0(op), 1, P_SAT,   P_SAT,   "w-inplace-l1");
        end

        // ---- pair in-place / narrowing at a long length ----
        run_case(4'd9, 1024, -8, 3, P_MIX, P_RAND, "sh32w-inplace-1k");
        run_case(4'd1, 1024,  5, 2, P_MIX, P_RAND, "sh32-narrow-1k");
        run_case(4'd8, 2048, 12, 2, P_MIX, P_MIX,  "emul32-narrow-2k");
        run_case(4'd4, 2048,  0, 1, P_MIX, P_MIX,  "add-inplace-2k");
        run_case(4'd0, 2048,  0, 0, P_MIX, P_RAND, "dq8-2k");
        run_case(4'd12, 2048, 0, 0, P_MIX, P_RAND, "dq16-2k");
        run_case(4'd10, 2048, 1, 0, P_MIX, P_RAND, "amax-2k");
    endtask

    // ==================================================================
    int seed_arg = 1, ncmd_arg = 800;
    string mode_s;

    initial begin
        int op_i, cls_i, len_i, p0_i, chain;

        if (!$value$plusargs("seed=%d", seed_arg)) seed_arg = 1;
        if (!$value$plusargs("ncmd=%d", ncmd_arg)) ncmd_arg = 800;
        if (!$value$plusargs("sabotage=%d", sab)) sab = 0;
        if (!$value$plusargs("sabat=%d", sabat)) sabat = 2;
        wfirst      = $test$plusargs("wfirst")      ? 1'b1 : 1'b0;
        coll_fatal  = $test$plusargs("coll_fatal")  ? 1'b1 : 1'b0;
        cfgscramble = $test$plusargs("cfgscramble") ? 1'b1 : 1'b0;
        rs = 32'(seed_arg) * 32'h9E37_79B1 + 32'h1234_5677;
        if (rs == 0) rs = 32'hDEAD_BEEF;
        mode_s = wfirst ? "write-first" : "read-first";
        if (coll_fatal)  mode_s = {mode_s, "+coll_fatal"};
        if (cfgscramble) mode_s = {mode_s, "+cfgscramble"};
        if (sab != 0)    mode_s = {mode_s, "+SABOTAGE"};

        for (int q = 0; q < 16; q++) op_cnt[q] = 0;
        for (int q = 0; q < 4;  q++) cls_cnt[q] = 0;

        repeat (5) @(negedge clk);
        rstn = 1'b1;
        repeat (2) @(negedge clk);

        init_mem();
        if (sab == 1) mem_n[1234] = ~mem_r[1234];   // comparator self-test

        directed();

        // ---- randomized stream, re-seeded scratch every batch ----
        while (ncmd_done < ncmd_arg) begin
            init_mem();
            if (sab == 1) mem_n[1234] = ~mem_r[1234];
            for (int c = 0; c < 20; c++) begin
                op_i  = OPS[rndm(12)];
                len_i = gen_len();
                if (op_i == 10) begin
                    // AMAX32 is a CHAINED scan: one fresh-or-continue head
                    // followed by continuations (cfg_p0[0] == 0).
                    chain = 1 + rndm(4);
                    p0_i  = rndm(2);
                    if (rndm(4) == 0) p0_i = p0_i | (rndm(256) << 1);
                    for (int h = 0; h < chain; h++) begin
                        run_case(4'd10, len_i, p0_i, 0,
                                 rndm(P_NPAT), rndm(P_NPAT), "rnd-amax");
                        p0_i  = (rndm(8) == 0) ? 1 : 0;
                        len_i = gen_len();
                    end
                end else begin
                    cls_i = gen_cls(4'(op_i));
                    p0_i  = gen_p0(4'(op_i));
                    run_case(4'(op_i), len_i, p0_i, cls_i,
                             rndm(P_NPAT), rndm(P_NPAT), "rnd");
                end
                if (ncmd_done >= ncmd_arg) break;
            end
        end

        $display("  ops:  0:%0d 1:%0d 2:%0d 3:%0d 4:%0d 5:%0d 6:%0d 7:%0d 8:%0d 9:%0d 10:%0d 12:%0d",
                 op_cnt[0], op_cnt[1], op_cnt[2], op_cnt[3], op_cnt[4],
                 op_cnt[5], op_cnt[6], op_cnt[7], op_cnt[8], op_cnt[9],
                 op_cnt[10], op_cnt[12]);
        $display("  class: disjoint=%0d inplace1=%0d narrow2to1=%0d pair-inplace=%0d | len_max=%0d",
                 cls_cnt[0], cls_cnt[1], cls_cnt[2], cls_cnt[3], len_max);
        $display("  overlap census: legacy raw collisions=%0d | new tail=%0d live=%0d (write-count deltas=%0d)",
                 coll_r, coll_n_tail, coll_n_live, wcnt_mismatch);
        $display("  cycles: legacy=%0d new=%0d (speedup x100 = %0d)",
                 tot_cyc_r, tot_cyc_n,
                 (tot_cyc_n == 0) ? 0 : (tot_cyc_r * 100) / tot_cyc_n);
        $display("TB_VECALU_DIFF PASS: %0d commands bit-exact (seed %0d, %s)",
                 ncmd_done, seed_arg, mode_s);
        $finish;
    end

    initial begin
        #900ms;
        $fatal(1, "watchdog (cmd %0d)", ncmd_done);
    end

endmodule
