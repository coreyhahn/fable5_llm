// tb_vec_alu: all ops vs layer_fixed-derived golden vectors, bit-exact.
//   +vecdir=  the frozen per-seed unit vectors (ops 0..9), UNCHANGED
//   +seqdir=  rung-1 goldens from tb/scripts/gen_seq_c_vectors.py (op 12
//             DYNQ16 both modes, op 8 probe; was gen_seq_vectors.py, DELETED)
//   +amaxlong the >2^18 element chain (512 commands) as well as the short one
//
// RUNG 4 S5 (docs/RUNG4_SPEC.md): vec_alu exports ONE registered 51-bit
// bundle {we = t_cp[0] && op_q==10, val = cp_v32, idx = am_g} for the TOPK-32
// block.  This TB pins that contract AT THE SOURCE, which tb_topk (which sees
// it only through layer_chan's CSRs) cannot:
//   * the bundle fires EXACTLY len times per AMAX32 command and NEVER on any
//     other op, in any order, with any p0
//   * its idx is the running am_g — reset only by p0[0]=1, carried across
//     chained chunks and across intervening non-AMAX commands, and WRAPPED
//     at 2^18 on a long chain
//   * a 32-entry sorted-insertion list fed from the bundle has, after EVERY
//     command, a head identically equal to (amax_val, amax_idx)
`timescale 1ns/1ps
module tb_vec_alu;
    logic clk = 0;
    /* verilator lint_off BLKSEQ */
    always #2 clk = ~clk;
    /* verilator lint_on BLKSEQ */
    logic rstn = 0, start = 0, busy, done;
    /* verilator lint_off UNUSEDSIGNAL */
    wire bu = busy;
    /* verilator lint_on UNUSEDSIGNAL */
    logic [3:0] cfg_op = 0;
    // G3.1: FOURTEEN bits.  This TB's own cfg_len was 13 and capped at
    // 8191, so it BROKE at FFN = 12288 — wall 3's TB twin, which spec 4.6
    // did not name.  A TB that cannot drive the production length cannot
    // gate it.
    logic [13:0] cfg_len = 0;                  // G3.1: 14-bit element count
    logic signed [16:0] cfg_p0 = 0;
    logic [15:0] cfg_srca = 0, cfg_srcb = 0, cfg_dst = 0;   // G3.1: 16 b
    logic [3:0] e_out;
    logic [15:0] a_addr, b_addr, w_addr;
    logic signed [15:0] a_q, b_q, w_data;
    logic w_en;

    /* verilator lint_off UNUSEDSIGNAL */
    logic [17:0]        amax_idx;   // exercised by the token-script TB
    logic signed [31:0] amax_val;
    /* verilator lint_on UNUSEDSIGNAL */
    logic signed [6:0] k_out;
    logic              k_we;
    logic [47:0]       maxp_out;
    logic [50:0]       topk_bun;             // RUNG4 S5 export
    vec_alu #(.SIGMOID_ROM("../rtl/roms/sigmoid_pair_rom.hex")) dut (
        .clk, .rstn, .start, .busy, .done,
        .cfg_op, .cfg_len, .cfg_p0, .cfg_srca, .cfg_srcb, .cfg_dst, .e_out,
        .amax_idx, .amax_val, .k_out, .k_we, .maxp_out, .topk_bun,
        .a_addr, .a_q, .b_addr, .b_q, .w_addr, .w_data, .w_en);

    // ==================================================================
    // RUNG4 S5: the export bundle, mirrored into a TB-side sorted list
    // (the same rule layer_topk32 implements: strictly-greater wins, so a
    // tie keeps the incumbent and the head is the first-occurrence argmax).
    // ==================================================================
    wire               tk_we  = topk_bun[50];
    wire signed [31:0] tk_val = signed'(topk_bun[49:18]);
    wire        [17:0] tk_idx = topk_bun[17:0];

    localparam int TKN = 32;
    logic signed [31:0] tk_lv [TKN];
    logic        [17:0] tk_li [TKN];
    int tk_n = 0;              // entries held
    int tk_seen = 0;           // bundle pulses in the current command
    int tk_pulses = 0;         // bundle pulses ever
    int tk_bad_idx = 0;        // pulses whose idx != the expected am_g
    int tk_bad_op = 0;         // pulses while the live op is NOT AMAX32
    int tk_g = 0;              // expected am_g

    task automatic tk_reset();
        tk_n = 0; tk_g = 0;
    endtask

    /* verilator lint_off BLKSEQ */
    always @(posedge clk) begin
        if (rstn && tk_we) begin
            int pos;
            tk_pulses = tk_pulses + 1;
            tk_seen   = tk_seen + 1;
            if (cfg_op !== 4'd10) tk_bad_op = tk_bad_op + 1;
            if (int'(tk_idx) !== (tk_g & 32'h3FFFF)) tk_bad_idx = tk_bad_idx + 1;
            tk_g = (tk_g + 1) & 32'h3FFFF;
            pos = (tk_n < TKN) ? tk_n : TKN;
            for (int i = ((tk_n < TKN) ? tk_n : TKN) - 1; i >= 0; i--)
                if (tk_lv[i] < tk_val) pos = i;
            if (tk_n < TKN) begin
                for (int i = TKN - 1; i > 0; i--)
                    if (i > pos && i <= tk_n) begin
                        tk_lv[i] = tk_lv[i-1]; tk_li[i] = tk_li[i-1];
                    end
                tk_lv[pos] = tk_val; tk_li[pos] = tk_idx;
                tk_n = tk_n + 1;
            end else if (tk_val > tk_lv[TKN-1]) begin
                for (int i = TKN - 1; i > 0; i--)
                    if (i > pos) begin
                        tk_lv[i] = tk_lv[i-1]; tk_li[i] = tk_li[i-1];
                    end
                tk_lv[pos] = tk_val; tk_li[pos] = tk_idx;
            end
        end
    end
    /* verilator lint_on BLKSEQ */

    // k_we is a 1-cycle strobe (layer_chan latches the XRF off it); the TB
    // samples it independently of k_out's held value.
    int k_pulses = 0;
    always_ff @(posedge clk) if (rstn && k_we) k_pulses <= k_pulses + 1;

    // scratch model
    // G3.1: 64K words — the drain-time parking address (cfg_dst + len)
    // must land in range, and the long-length case below deliberately
    // parks its destination in the TOP half.
    logic signed [15:0] mem [65536];
    always_ff @(posedge clk) begin
        a_q <= mem[a_addr];
        b_q <= mem[b_addr];
        if (w_en) mem[w_addr] <= w_data;
    end

    int errors = 0;

    /* verilator lint_off UNUSEDSIGNAL */
    task automatic run_op(input logic [3:0] op, input int len,
                          input int p0, input int sa, input int sb, input int d);
    /* verilator lint_on UNUSEDSIGNAL */
        cfg_op = op; cfg_len = 14'(len); cfg_p0 = 17'(p0);
        cfg_srca = 16'(sa); cfg_srcb = 16'(sb); cfg_dst = 16'(d);
        @(negedge clk); start = 1; @(negedge clk); start = 0;
        begin
            int guard = 0;
            while (!done) begin
                @(negedge clk); guard++;
                if (guard > 100000) begin errors++; $display("op%0d timeout", op); break; end
            end
        end
        @(negedge clk);
    endtask

    task automatic check_region(input string name, input int d, input int len,
                                input logic [15:0] gold [64]);
        for (int k = 0; k < len; k++)
            if (mem[d + k] !== signed'(gold[k])) begin
                errors++;
                if (errors < 10)
                    $display("FAIL %s[%0d]: got %h want %h", name, k,
                             mem[d + k], gold[k]);
            end
    endtask

    logic [15:0] dq_x [64];  logic [15:0] dq_y [64];  logic [15:0] dq_e [1];
    logic [31:0] s32_v [64]; logic [15:0] s32_y [64];
    logic [15:0] sc_y [64];
    logic [15:0] em_a [64];  logic [15:0] em_b [64];  logic [15:0] em_y [64];
    logic [15:0] ad_y [64];
    logic [15:0] si16_y [64];
    logic [15:0] si32_y [64];
    logic [15:0] sg16_y [64];
    logic [15:0] em32_y [64];
    logic [31:0] s32w_y [64];

    // ==================================================================
    // op 12 DYNQ16 / op 8 probe — file-driven case replay
    // ==================================================================
    string seqdir;
    int n_dq = 0, n_pr = 0, n_clamped = 0, kmin_s = 99, kmax_s = -99;

    // scratch layout for the case replay: a32 pairs @4000, b16 @6000,
    // dst @8000 (and @8400 for the probe/no-probe comparison pass)
    localparam int SA = 4000, SB = 6000, SD = 8000, SD2 = 8400;

    task automatic run_dynq16(input string path);
        int fd, r, ncase, len, clamp0, kexp, dsel, kp0;
        logic [31:0] xw;
        logic [15:0] yw [128];
        fd = $fopen(path, "r");
        if (fd == 0) $fatal(1, "cannot open %s", path);
        r = $fscanf(fd, " %d", ncase);
        if (r != 1) $fatal(1, "bad header in %s", path);
        for (int c = 0; c < ncase; c++) begin
            r = $fscanf(fd, " %d %d %d", len, clamp0, kexp);
            if (r != 3) $fatal(1, "bad case %0d in %s", c, path);
            for (int e = 0; e < len; e++) begin
                r = $fscanf(fd, " %h", xw);
                mem[SA + 2*e]     = signed'(xw[15:0]);
                mem[SA + 2*e + 1] = signed'(xw[31:16]);
            end
            for (int e = 0; e < len; e++) r = $fscanf(fd, " %h", yw[e]);
            // alternate the XRF destination-select bit: p0[0] must not
            // change a single output word, only where layer_chan files k
            dsel = c & 1;
            kp0  = (clamp0 << 1) | dsel;
            run_op(4'd12, len, kp0, SA, 0, SD);
            for (int e = 0; e < len; e++)
                if (mem[SD + e] !== signed'(yw[e])) begin
                    errors++;
                    if (errors < 10)
                        $display("FAIL dynq16 c%0d len%0d clamp%0d [%0d]: got %h want %h",
                                 c, len, clamp0, e, mem[SD + e], yw[e]);
                end
            if (int'(k_out) !== kexp) begin
                errors++;
                if (errors < 10)
                    $display("FAIL dynq16 case %0d k: got %0d want %0d",
                             c, k_out, kexp);
            end
            n_dq++;
            n_clamped += clamp0;
            if (kexp < kmin_s) kmin_s = kexp;
            if (kexp > kmax_s) kmax_s = kexp;
        end
        $fclose(fd);
        if (k_pulses < n_dq) begin
            errors++;
            $display("FAIL dynq16: %0d k_we strobes for %0d cases",
                     k_pulses, n_dq);
        end
    endtask

    task automatic run_probe8(input string path);
        int fd, r, ncase, len, sh, kaexp, k0;
        logic [47:0] mpexp;
        logic [31:0] aw;
        logic [15:0] bw, yw [128];
        fd = $fopen(path, "r");
        if (fd == 0) $fatal(1, "cannot open %s", path);
        r = $fscanf(fd, " %d", ncase);
        if (r != 1) $fatal(1, "bad header in %s", path);
        for (int c = 0; c < ncase; c++) begin
            r = $fscanf(fd, " %d %d %d %h", len, sh, kaexp, mpexp);
            if (r != 4) $fatal(1, "bad case %0d in %s", c, path);
            for (int e = 0; e < len; e++) begin
                r = $fscanf(fd, " %h", aw);
                mem[SA + 2*e]     = signed'(aw[15:0]);
                mem[SA + 2*e + 1] = signed'(aw[31:16]);
            end
            for (int e = 0; e < len; e++) begin
                r = $fscanf(fd, " %h", bw);
                mem[SB + e] = signed'(bw);
            end
            for (int e = 0; e < len; e++) r = $fscanf(fd, " %h", yw[e]);
            k0 = k_pulses;
            // (a) legacy op 8, probe bit clear: must be untouched
            run_op(4'd8, len, sh, SA, SB, SD);
            // (b) same shift with the probe bit set: SAME outputs, plus
            //     max|prod| and the attn_o_shift immediate derived from it
            run_op(4'd8, len, sh | 64, SA, SB, SD2);
            for (int e = 0; e < len; e++) begin
                if (mem[SD + e] !== signed'(yw[e])) begin
                    errors++;
                    if (errors < 10)
                        $display("FAIL emul32 case %0d [%0d]: got %h want %h",
                                 c, e, mem[SD + e], yw[e]);
                end
                if (mem[SD2 + e] !== mem[SD + e]) begin
                    errors++;
                    if (errors < 10)
                        $display("FAIL probe c%0d [%0d]: probe changed the output %h vs %h",
                                 c, e, mem[SD2 + e], mem[SD + e]);
                end
            end
            if (maxp_out !== mpexp) begin
                errors++;
                if (errors < 10)
                    $display("FAIL probe case %0d maxp: got %h want %h",
                             c, maxp_out, mpexp);
            end
            if (int'(k_out) !== kaexp) begin
                errors++;
                if (errors < 10)
                    $display("FAIL probe case %0d k_a: got %0d want %0d",
                             c, k_out, kaexp);
            end
            if (k_pulses != k0 + 1) begin
                errors++;
                $display("FAIL probe case %0d: %0d k_we strobes (want 1)",
                         c, k_pulses - k0);
            end
            n_pr++;
        end
        $fclose(fd);
    endtask
    // ==================================================================
    // RUNG4 S5 gate: chained AMAX32 chunks.  fresh ONLY on chunk 0; other
    // ops run between chunks and must neither export nor reset am_g.
    // ==================================================================
    localparam int AM   = 10000;   // element pairs live here
    localparam int AMD  = 13000;   // ALU dst park (op 10 writes nothing)
    int n_chain_cmd = 0, n_chain_elem = 0;

    task automatic amax_chunk(input int off, input int len, input bit fresh);
        tk_seen = 0;
        if (fresh) tk_reset();
        run_op(4'd10, len, fresh ? 1 : 0, AM + 2*off, 0, AMD);
        if (tk_seen != len) begin
            errors++;
            $display("FAIL S5: %0d bundle pulses for a len-%0d AMAX32", tk_seen, len);
        end
        if (tk_n > 0) begin
            if (tk_lv[0] !== amax_val) begin
                errors++;
                $display("FAIL S5: TOPK head val %h != amax_val %h (cmd %0d)",
                         tk_lv[0], amax_val, n_chain_cmd);
            end
            if (tk_li[0] !== amax_idx) begin
                errors++;
                $display("FAIL S5: TOPK head idx %0d != amax_idx %0d (cmd %0d)",
                         tk_li[0], amax_idx, n_chain_cmd);
            end
        end
        n_chain_cmd++;
        n_chain_elem += len;
    endtask

    task automatic amax_quiet_op(input logic [3:0] op, input int len,
                                 input int p0);
        int p0_before;
        p0_before = tk_pulses;
        run_op(op, len, p0, AM, AM + 1024, AMD);
        if (tk_pulses != p0_before) begin
            errors++;
            $display("FAIL S5: op %0d exported %0d bundle pulses (must be 0)",
                     op, tk_pulses - p0_before);
        end
    endtask

    task automatic fill_amax_region(input int n, input int unsigned sd);
        int unsigned r;
        r = sd;
        for (int e = 0; e < n; e++) begin
            logic [31:0] v;
            r = r ^ (r << 13); r = r ^ (r >> 17); r = r ^ (r << 5);
            case (e % 11)
                0:  v = 32'h7FFF_FFFF;                    // +2^31-1 rail
                1:  v = 32'h8000_0000;                    // -2^31 rail
                2:  v = {24'd0, r[7:0]};                  // tiny alphabet -> ties
                3:  v = 32'h0000_0000;
                default: v = r;
            endcase
            mem[AM + 2*e]     = signed'(v[15:0]);
            mem[AM + 2*e + 1] = signed'(v[31:16]);
        end
    endtask

    string vecdir;
    initial begin
        int i;
        if (!$value$plusargs("vecdir=%s", vecdir)) $fatal(1, "need +vecdir=");
        $readmemh({vecdir, "/alu_dynq8_x.hex"}, dq_x);
        $readmemh({vecdir, "/alu_dynq8_y.hex"}, dq_y);
        $readmemh({vecdir, "/alu_dynq8_e.hex"}, dq_e);
        $readmemh({vecdir, "/alu_shift32_v.hex"}, s32_v);
        $readmemh({vecdir, "/alu_shift32_y.hex"}, s32_y);
        $readmemh({vecdir, "/alu_scale_y.hex"}, sc_y);
        $readmemh({vecdir, "/alu_emul_a.hex"}, em_a);
        $readmemh({vecdir, "/alu_emul_b.hex"}, em_b);
        $readmemh({vecdir, "/alu_emul_y.hex"}, em_y);
        $readmemh({vecdir, "/alu_add_y.hex"}, ad_y);
        $readmemh({vecdir, "/alu_silu16_y.hex"}, si16_y);
        $readmemh({vecdir, "/alu_silu32_y.hex"}, si32_y);
        $readmemh({vecdir, "/alu_sigm16_y.hex"}, sg16_y);
        $readmemh({vecdir, "/alu_emul32_y.hex"}, em32_y);
        $readmemh({vecdir, "/alu_shift32w_y.hex"}, s32w_y);

        repeat (5) @(negedge clk);
        rstn = 1;
        repeat (2) @(negedge clk);

        // layout: dq_x @0, s32 pairs @100, sc/em a @300, b @400, outputs @1000+
        for (i = 0; i < 64; i++) begin
            mem[i]        = signed'(dq_x[i]);
            mem[100+2*i]  = signed'(s32_v[i][15:0]);
            mem[101+2*i]  = signed'(s32_v[i][31:16]);
            mem[300+i]    = signed'(em_a[i]);   // == sc_x == ax
            mem[400+i]    = signed'(em_b[i]);
        end

        run_op(4'd0, 64, 0, 0, 0, 1000);                       // DYNQ8
        check_region("dynq8", 1000, 64, dq_y);
        if (e_out !== 4'(dq_e[0])) begin
            errors++; $display("FAIL dynq8 e: got %0d want %0d", e_out, dq_e[0]);
        end
        run_op(4'd1, 64, 5, 100, 0, 1100);                     // SHIFT32
        check_region("shift32", 1100, 64, s32_y);
        run_op(4'd2, 64, 2896, 300, 0, 1200);                  // SCALE (1/sqrt128)
        check_region("scale", 1200, 64, sc_y);
        run_op(4'd3, 64, 12, 300, 400, 1300);                  // EMUL
        check_region("emul", 1300, 64, em_y);
        run_op(4'd4, 64, 0, 300, 400, 1400);                   // ADD
        check_region("add", 1400, 64, ad_y);
        run_op(4'd5, 64, -4, 300, 0, 1500);                    // SILU16
        check_region("silu16", 1500, 64, si16_y);
        run_op(4'd6, 64, 0, 100, 0, 1600);                     // SILU32
        check_region("silu32", 1600, 64, si32_y);
        run_op(4'd7, 64, -4, 300, 0, 1700);                    // SIGM16
        check_region("sigm16", 1700, 64, sg16_y);
        run_op(4'd8, 64, 15, 100, 400, 1800);                  // EMUL32
        check_region("emul32", 1800, 64, em32_y);
        run_op(4'd9, 64, -8, 100, 0, 2000);                    // SHIFT32W
        for (int k2 = 0; k2 < 64; k2++) begin
            logic [31:0] gotw;
            gotw = {mem[2000 + 2*k2 + 1], mem[2000 + 2*k2]};
            if (gotw !== s32w_y[k2]) begin
                errors++;
                if (errors < 10)
                    $display("FAIL shift32w[%0d]: got %h want %h",
                             k2, gotw, s32w_y[k2]);
            end
        end

        // ---- sequencer rung-1 ops (docs/SEQ_ISA.md) ----
        if ($value$plusargs("seqdir=%s", seqdir)) begin
            run_dynq16({seqdir, "/dynq16_cases.txt"});
            run_probe8({seqdir, "/probe8_cases.txt"});
        end else begin
            $display("NOTE: no +seqdir= -> DYNQ16/probe cases SKIPPED");
        end

        // ---- RUNG4 S5: the export bundle + TOPK-vs-AMAX equality ----
        fill_amax_region(1024, 32'h1234_5678);
        // 8 chained chunks of 128, fresh only on the first, with an
        // unrelated op between every pair (they must stay quiet AND must
        // not disturb the running scan)
        for (int c = 0; c < 8; c++) begin
            amax_chunk(c * 128, 128, c == 0);
            if (c < 7) begin
                amax_quiet_op(4'd4, 64, 0);       // ADD
                amax_quiet_op(4'd0, 64, 0);       // DYNQ8 (the other scan)
                amax_quiet_op(4'd12, 64, 0);      // DYNQ16 (running max)
            end
        end
        // ragged chunk lengths on the SAME running scan
        amax_chunk(0, 1, 1'b0);
        amax_chunk(1, 7, 1'b0);
        amax_chunk(8, 1, 1'b0);
        amax_chunk(9, 999, 1'b0);
        // fresh RESTARTS it: one element, head must be that element at idx 0
        amax_chunk(3, 1, 1'b1);
        if (tk_n != 1) begin
            errors++;
            $display("FAIL S5: fresh did not restart the scan (tk_n=%0d)", tk_n);
        end
        if (tk_li[0] !== 18'd0) begin
            errors++;
            $display("FAIL S5: after fresh the head idx is %0d, want 0", tk_li[0]);
        end
        // >2^18 elements: am_g must WRAP and the bundle must carry the
        // wrapped index (512 x 512 = 262,144 = 2^18, plus 8 more chunks)
        if ($test$plusargs("amaxlong")) begin
            amax_chunk(0, 512, 1'b1);
            for (int c = 1; c < 520; c++) amax_chunk((c * 37) % 512, 512, 1'b0);
            if (tk_g != ((520 * 512) & 32'h3FFFF)) begin
                errors++;
                $display("FAIL S5: am_g mirror %0d after %0d elements",
                         tk_g, 520 * 512);
            end
        end
        if (tk_bad_idx != 0) begin
            errors++;
            $display("FAIL S5: %0d bundle pulses carried the wrong am_g",
                     tk_bad_idx);
        end
        if (tk_bad_op != 0) begin
            errors++;
            $display("FAIL S5: %0d bundle pulses fired outside an AMAX32",
                     tk_bad_op);
        end

        // ==============================================================
        // G3.1: the ALU element count is 14 bits (ARG0[17:4] -> cfg_len).
        //
        // It was 12, and the Qwen3.5-2B MLP quantizes its whole FFN = 6144
        // intermediate in ONE DYNQ8 — a length that CANNOT be chunked,
        // because DYNQ8 picks one shared exponent from max|x| over the
        // vector and reports it on EOUT.  `6144 & 0xFFF` = 2048, so the
        // engine silently ran a third of the vector; nothing downstream
        // could see it, because no python model had a 12-bit field.  R-c
        // took the field to 13 (max 8191).  Qwen3.5-9B's FFN is 12288, so
        // 13 bits break the SAME WAY (`12288 & 0x1FFF` = 4096) and G3.1
        // takes it to 14 — and the case below now runs at 12288, past both
        // old truncation points, with its destination in the TOP HALF of
        // the 64K scratchpad so the 16-bit address is exercised too.
        //
        // Two directed checks at the REAL production length:
        //   (a) ADD over 12288 elements is elementwise-exact end to end —
        //       proves the address generator and the write counter reach
        //       the last element, not just element 4095.
        //   (b) DYNQ8's SCAN sees the whole vector: the max is planted at
        //       index 10000, i.e. beyond both old truncation points, and
        //       the exponent it produces must DIFFER from the one the
        //       first 4096 elements alone imply.  This is the semantic a
        //       truncated length destroys, and it needs no golden
        //       arithmetic to state.
        // ==============================================================
        begin
            localparam int LONG = 12288;        // = FFN at Qwen3.5-9B
            localparam int LA = 0, LB = 16384, LD = 40960;
            logic [3:0] e_long, e_short;
            int nbad_long;

            for (int k = 0; k < LONG; k++) begin
                mem[LA + k] = 16'sd3 + 16'(k % 7);
                mem[LB + k] = 16'sd5 + 16'(k % 11);
                mem[LD + k] = 16'sh5A5A;        // sentinel: must be written
            end
            // (a) ADD, every element
            run_op(4, LONG, 0, LA, LB, LD);
            nbad_long = 0;
            for (int k = 0; k < LONG; k++)
                if (mem[LD + k] !== (16'sd3 + 16'(k % 7)) + (16'sd5 + 16'(k % 11)))
                    nbad_long++;
            if (nbad_long != 0) begin
                errors++;
                $display("FAIL G3.1 ADD len=%0d: %0d of %0d elements wrong (a 13-bit cfg_len runs %0d)",
                         LONG, nbad_long, LONG, LONG & 32'h1FFF);
            end

            // (b) DYNQ8 scan reach: plant the max PAST the old truncation
            for (int k = 0; k < LONG; k++) mem[LA + k] = 16'sd64;
            mem[LA + 10000] = 16'sh4000;        // only visible to a full scan
            run_op(0, LONG, 0, LA, 0, LD);
            e_long = e_out;
            run_op(0, 4096, 0, LA, 0, LD);      // the 13-bit truncated prefix
            e_short = e_out;
            if (e_long === e_short) begin
                errors++;
                $display("FAIL G3.1 DYNQ8 len=%0d: exponent %0d equals the one the first 4096 elements imply: the scan did NOT reach the max planted at index 10000",
                         LONG, e_long);
            end else
                $display("  G3.1 long-length: ADD %0d/%0d exact into the TOP half (dst %0d); DYNQ8 e=%0d over %0d vs e=%0d over 4096 (the scan reaches past the 13-bit truncation point)",
                         LONG - nbad_long, LONG, LD, e_long, LONG, e_short);
        end

        if (errors == 0) begin
            if (n_dq > 0)
                $display("  DYNQ16: %0d cases bit-exact (k %0d..%0d, %0d clamp0) | op8 probe: %0d cases (maxp + k_a + legacy-output regression)",
                         n_dq, kmin_s, kmax_s, n_clamped, n_pr);
            $display("  S5 export: %0d AMAX32 commands, %0d elements, %0d bundle pulses, head==amax every command, 0 stray pulses",
                     n_chain_cmd, n_chain_elem, tk_pulses);
            $display("TB_VEC_ALU PASS: 10 ops bit-exact");
            $finish;
        end else $fatal(1, "TB_VEC_ALU FAIL: %0d", errors);
    end
    initial begin #200ms; $fatal(1, "watchdog"); end

endmodule
