// tb_conv4_silu: conv vectors replay (64 channels), bit-exact, pipelined.
`timescale 1ns/1ps
module tb_conv4_silu;
    logic clk = 0;
    /* verilator lint_off BLKSEQ */
    always #2 clk = ~clk;
    /* verilator lint_on BLKSEQ */
    logic rstn = 0, in_valid = 0, out_valid;
    logic signed [15:0] win0=0, win1=0, win2=0, win3=0, w0=0, w1=0, w2=0, w3=0;
    logic signed [15:0] out_y;

    conv4_silu #(.SIGMOID_ROM("../rtl/roms/sigmoid_pair_rom.hex")) dut (
        .clk, .rstn, .in_valid,
        .win0, .win1, .win2, .win3, .w0, .w1, .w2, .w3,
        .out_valid, .out_y
    );

    logic [15:0] winv [256];   // 64 channels x 4 taps
    logic [15:0] wv   [256];
    logic [15:0] gv   [64];
    int errors = 0, rcvd = 0;

    initial begin
        forever begin
            @(negedge clk);
            if (out_valid) begin
                if (out_y !== signed'(gv[rcvd])) begin
                    errors++;
                    if (errors < 6)
                        $display("FAIL [%0d]: got %h want %h", rcvd, out_y, gv[rcvd]);
                end
                rcvd++;
            end
        end
    end

    string vecdir;
    initial begin
        int i;
        if (!$value$plusargs("vecdir=%s", vecdir)) $fatal(1, "need +vecdir=");
        $readmemh({vecdir, "/conv_win.hex"}, winv);
        $readmemh({vecdir, "/conv_w.hex"},   wv);
        $readmemh({vecdir, "/conv_y.hex"},   gv);
        repeat (5) @(negedge clk);
        rstn = 1;
        repeat (2) @(negedge clk);
        for (i = 0; i < 64; i++) begin
            @(negedge clk);
            win0 = signed'(winv[4*i+0]); win1 = signed'(winv[4*i+1]);
            win2 = signed'(winv[4*i+2]); win3 = signed'(winv[4*i+3]);
            w0 = signed'(wv[4*i+0]); w1 = signed'(wv[4*i+1]);
            w2 = signed'(wv[4*i+2]); w3 = signed'(wv[4*i+3]);
            in_valid = 1;
        end
        @(negedge clk);
        in_valid = 0;
        repeat (24) @(negedge clk);
        if (rcvd != 64) begin errors++; $display("FAIL: rcvd %0d", rcvd); end
        if (errors == 0) begin
            $display("TB_CONV4_SILU PASS: 64 channels bit-exact");
            $finish;
        end else $fatal(1, "TB_CONV4_SILU FAIL: %0d", errors);
    end
    initial begin #5ms; $fatal(1, "watchdog"); end
endmodule
