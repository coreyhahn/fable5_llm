// tb_rope: rope_unit vs layer_fixed.rope_fx golden vectors, bit-exact.
`timescale 1ns/1ps
module tb_rope;
    logic clk = 0;
    /* verilator lint_off BLKSEQ */
    always #2 clk = ~clk;
    /* verilator lint_on BLKSEQ */
    logic rstn = 0, start = 0, busy;
    /* verilator lint_off UNUSEDSIGNAL */
    wire busy_u = busy;
    /* verilator lint_on UNUSEDSIGNAL */
    logic t_we = 0;
    logic [7:0] t_waddr = 0;
    logic [15:0] t_wdata = 0;
    logic s_valid = 0, s_ready;
    logic signed [15:0] s_data = 0;
    logic m_valid, m_ready = 0;
    logic signed [15:0] m_data;

    rope_unit dut (.clk, .rstn, .start, .busy, .t_we, .t_waddr, .t_wdata,
                   .s_valid, .s_ready, .s_data, .m_valid, .m_ready, .m_data);

    logic [15:0] xv [256];
    logic [15:0] cv [64];
    logic [15:0] sv [64];
    logic [15:0] gv [256];
    int errors = 0;

    string vecdir;
    initial begin
        int i;
        if (!$value$plusargs("vecdir=%s", vecdir)) $fatal(1, "need +vecdir=");
        $readmemh({vecdir, "/rope_x16.hex"}, xv);
        $readmemh({vecdir, "/rope_cos.hex"}, cv);
        $readmemh({vecdir, "/rope_sin.hex"}, sv);
        $readmemh({vecdir, "/rope_y16.hex"}, gv);
        repeat (5) @(negedge clk);
        rstn = 1;
        repeat (2) @(negedge clk);
        for (i = 0; i < 64; i++) begin
            @(negedge clk); t_we = 1; t_waddr = 8'(i); t_wdata = cv[i];
        end
        for (i = 0; i < 64; i++) begin
            @(negedge clk); t_we = 1; t_waddr = 8'(64 + i); t_wdata = sv[i];
        end
        @(negedge clk); t_we = 0;
        start = 1; @(negedge clk); start = 0;
        for (i = 0; i < 256; i++) begin
            @(negedge clk);
            s_data = signed'(xv[i]); s_valid = 1;
            while (!s_ready) @(negedge clk);
        end
        @(negedge clk);
        s_valid = 0;
        i = 0;
        begin
            int guard = 0;
            while (i < 256) begin
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
                if (guard > 100000) begin
                    errors++; $display("timeout at %0d", i); break;
                end
            end
            @(negedge clk);
            m_ready = 0;
        end
        if (errors == 0) begin
            $display("TB_ROPE PASS: 256 elems bit-exact");
            $finish;
        end else $fatal(1, "TB_ROPE FAIL: %0d", errors);
    end
    initial begin #10ms; $fatal(1, "watchdog"); end
endmodule
