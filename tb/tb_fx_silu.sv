// tb_fx_silu: pipelined replay of silu cases, bit-exact.
`timescale 1ns/1ps
module tb_fx_silu;
    logic clk = 0;
    /* verilator lint_off BLKSEQ */
    always #2 clk = ~clk;
    /* verilator lint_on BLKSEQ */
    logic rstn = 0, in_valid = 0, out_valid;
    logic signed [20:0] in_x = 0;
    logic signed [15:0] out_y;

    fx_silu #(.ROM_FILE("../rtl/roms/sigmoid_pair_rom.hex")) dut
        (.clk, .rstn, .in_valid, .in_x, .out_valid, .out_y);

    int errors = 0, sent = 0, rcvd = 0, ncases = 0;
    logic [20:0] cx [1024];
    logic [15:0] cy [1024];

    initial begin
        forever begin
            @(negedge clk);
            if (out_valid) begin
                if (out_y !== signed'(cy[rcvd])) begin
                    errors++;
                    if (errors < 8)
                        $display("FAIL [%0d]: x=%h got %h want %h",
                                 rcvd, cx[rcvd], out_y, cy[rcvd]);
                end
                rcvd++;
            end
        end
    end

    string casefile;
    initial begin
        int fd, n;
        logic [20:0] x;
        logic [15:0] y;
        if (!$value$plusargs("cases=%s", casefile)) $fatal(1, "need +cases=");
        fd = $fopen(casefile, "r");
        if (fd == 0) $fatal(1, "open fail");
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h", x, y);
            if (n != 2) break;
            cx[ncases] = x; cy[ncases] = y; ncases++;
        end
        $fclose(fd);
        repeat (5) @(negedge clk);
        rstn = 1;
        repeat (2) @(negedge clk);
        // stream one per cycle (pipeline test)
        for (sent = 0; sent < ncases; sent++) begin
            @(negedge clk);
            in_x = signed'(cx[sent]); in_valid = 1;
        end
        @(negedge clk);
        in_valid = 0;
        repeat (20) @(negedge clk);
        if (rcvd != ncases) begin
            errors++;
            $display("FAIL: rcvd %0d != %0d", rcvd, ncases);
        end
        if (errors == 0) begin
            $display("TB_FX_SILU PASS: %0d cases bit-exact (pipelined)", ncases);
            $finish;
        end else $fatal(1, "TB_FX_SILU FAIL: %0d", errors);
    end
    initial begin #5ms; $fatal(1, "watchdog"); end
endmodule
