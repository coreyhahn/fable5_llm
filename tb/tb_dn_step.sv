// tb_dn_step: dn_step vs layer_fixed deltanet-step golden vectors,
// bit-exact (output stream AND final state memory contents).
//
// G3.4 (spec 4.1 W1'(a)): the state memory's READ LATENCY is a build
// parameter here, because layer_chan's 24-bank DN array pipelines its SLR
// crossings and presents 2 + 2*DN_PIPE = 6 instead of 2.  The TB models
// exactly that -- an RLAT-deep register chain on the read return, with the
// write applied immediately, which reproduces the real array's read/write
// ORDER (both legs traverse the same DN_PIPE stages there, so the order at
// the array is the order at the port).
//
//   RLAT=2 P2W=0   the unpipelined control: the four shipped vector cases
//                  must stay BIT-IDENTICAL through the issue-point move.
//   RLAT=6 P2W=1   WHAT SHIPS -- option (i), the pass-2 wait state.
//   RLAT=6 P2W=0   option (ii), two reads outstanding.  NOT SHIPPED;
//                  built and run only to price the decision.
//
// It also reports DN_CYCLES: start -> done, the per-head cycle cost that
// Step 1's decision section is measured in (label T).
`timescale 1ns/1ps
module tb_dn_step #(
    parameter int RLAT = 2,
    parameter int P2W  = 0
);
    logic clk = 0;
    /* verilator lint_off BLKSEQ */
    always #2 clk = ~clk;
    /* verilator lint_on BLKSEQ */
    logic rstn = 0, start = 0, busy, done;
    /* verilator lint_off UNUSEDSIGNAL */
    wire bu = busy;
    /* verilator lint_on UNUSEDSIGNAL */
    logic [15:0] cfg_decay = 0, cfg_beta = 0;
    logic vec_we = 0;
    logic [1:0] vec_sel = 0;
    logic [6:0] vec_addr = 0;
    logic signed [20:0] vec_data = 0;
    logic [6:0] s_rdaddr, s_wraddr;
    wire  [2047:0] s_rddata;
    logic [2047:0] s_wrdata;
    logic s_wren;
    logic m_valid, m_ready = 0;
    logic signed [31:0] m_data;
    logic [6:0] m_idx;

    dn_step #(.RLAT(RLAT), .P2_WAIT(P2W)) dut (
                 .clk, .rstn, .start, .busy, .done, .cfg_decay, .cfg_beta,
                 .vec_we, .vec_sel, .vec_addr, .vec_data,
                 .s_rdaddr, .s_rddata, .s_wraddr, .s_wrdata, .s_wren,
                 .m_valid, .m_ready, .m_data, .m_idx);

    // state memory model: 128 x 2048b, RLAT-cycle read latency
    // (RLAT=2 is URAM + OREG; RLAT=6 adds layer_chan's DN_PIPE=2 fan-out
    // and return stages).  The write is applied in the same always_ff, so
    // a read issued in the same cycle as a write returns the OLD row --
    // the same order the real array gives.
    logic [2047:0] smem [128];
    logic [2047:0] s_rd_p [RLAT];
    always_ff @(posedge clk) begin
        s_rd_p[0] <= smem[s_rdaddr];
        for (int i = 1; i < RLAT; i++) s_rd_p[i] <= s_rd_p[i-1];
        if (s_wren) smem[s_wraddr] <= s_wrdata;
    end
    assign s_rddata = s_rd_p[RLAT-1];

    // label T: cycles from the start pulse to done, per head.
    int unsigned dn_cycles = 0;
    logic        dn_count = 0;
    always_ff @(posedge clk) begin
        if (start)     dn_count <= 1'b1;
        if (dn_count)  dn_cycles <= dn_cycles + 1;
        if (done)      dn_count <= 1'b0;
    end

    logic [15:0] sin_v [16384];
    logic [15:0] sout_v [16384];
    logic [15:0] qv [128];
    logic [15:0] kv [128];
    logic [15:0] vv [128];
    logic [31:0] ov [128];
    int errors = 0, rcvd = 0;

    initial begin
        forever begin
            @(negedge clk);
            m_ready = 1;
            if (m_valid && m_ready) begin
                if (m_data !== signed'(ov[m_idx])) begin
                    errors++;
                    if (errors < 6)
                        $display("FAIL o[%0d]: got %0d want %0d",
                                 m_idx, m_data, signed'(ov[m_idx]));
                end
                rcvd++;
            end
        end
    end

    string vecdir;
    initial begin
        /* verilator lint_off UNUSEDSIGNAL */
        int i, fd, n, dec, bet;   // dec/bet upper bits unused (Q15 values)
        /* verilator lint_on UNUSEDSIGNAL */
        if (!$value$plusargs("vecdir=%s", vecdir)) $fatal(1, "need +vecdir=");
        $readmemh({vecdir, "/dn_sin.hex"}, sin_v);
        $readmemh({vecdir, "/dn_sout.hex"}, sout_v);
        $readmemh({vecdir, "/dn_q.hex"}, qv);
        $readmemh({vecdir, "/dn_k.hex"}, kv);
        $readmemh({vecdir, "/dn_v.hex"}, vv);
        $readmemh({vecdir, "/dn_o.hex"}, ov);
        fd = $fopen({vecdir, "/dn_gates.txt"}, "r");
        n = $fscanf(fd, "%d %d", dec, bet);
        if (n != 2) $fatal(1, "bad gates");
        $fclose(fd);
        // preload state (row dk = words dk*128 .. dk*128+127)
        for (i = 0; i < 128; i++)
            for (int v = 0; v < 128; v++)
                smem[i][v*16 +: 16] = sin_v[i*128 + v];

        repeat (5) @(negedge clk);
        rstn = 1;
        repeat (2) @(negedge clk);
        cfg_decay = 16'(dec);
        cfg_beta = 16'(bet);
        for (i = 0; i < 128; i++) begin
            @(negedge clk);
            vec_we = 1; vec_sel = 2'd0; vec_addr = 7'(i);
            vec_data = 21'(signed'(kv[i]));
        end
        for (i = 0; i < 128; i++) begin
            @(negedge clk);
            vec_we = 1; vec_sel = 2'd1; vec_addr = 7'(i);
            vec_data = 21'(signed'(qv[i]));
        end
        for (i = 0; i < 128; i++) begin
            @(negedge clk);
            vec_we = 1; vec_sel = 2'd2; vec_addr = 7'(i);
            vec_data = 21'(signed'(vv[i]));
        end
        @(negedge clk); vec_we = 0;
        start = 1; @(negedge clk); start = 0;
        begin
            int guard = 0;
            while (!done) begin
                @(negedge clk);
                guard++;
                if (guard > 50000) begin
                    errors++; $display("FAIL: timeout, rcvd=%0d", rcvd); break;
                end
            end
        end
        repeat (3) @(negedge clk);
        if (rcvd != 128) begin errors++; $display("FAIL rcvd=%0d", rcvd); end
        // final state check
        for (i = 0; i < 128; i++)
            for (int v = 0; v < 128; v++)
                if (smem[i][v*16 +: 16] !== sout_v[i*128 + v]) begin
                    errors++;
                    if (errors < 10)
                        $display("FAIL S[%0d][%0d]: got %h want %h",
                                 i, v, smem[i][v*16 +: 16], sout_v[i*128 + v]);
                end
        $display("DN_CYCLES RLAT=%0d P2W=%0d cycles_per_head=%0d",
                 RLAT, P2W, dn_cycles);
        if (errors == 0) begin
            $display("TB_DN_STEP PASS: 128 outputs + 16384 state entries bit-exact");
            $finish;
        end else $fatal(1, "TB_DN_STEP FAIL: %0d", errors);
    end
    initial begin #20ms; $fatal(1, "watchdog"); end
endmodule
