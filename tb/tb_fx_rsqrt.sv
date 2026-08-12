// tb_fx_rsqrt: bit-exact replay of fixedpoint.rsqrt_q cases.
`timescale 1ns/1ps
module tb_fx_rsqrt;
    logic clk = 0;
    /* verilator lint_off BLKSEQ */
    always #2 clk = ~clk;
    /* verilator lint_on BLKSEQ */
    logic rstn = 0, start = 0, done;
    logic [47:0] v;
    logic [5:0] p_in;
    logic [31:0] r_out;
    logic signed [7:0] e_out;

    fx_rsqrt #(.ROM_FILE("../rtl/roms/rsqrt_rom.hex")) dut
        (.clk, .rstn, .start, .v, .p_in, .done, .r_out, .e_out);

    int errors = 0;
    string casefile;
    initial begin
        int fd, n, vcount;
        logic [47:0] cv;
        logic [7:0] cp, ce;
        logic [31:0] cr;
        if (!$value$plusargs("cases=%s", casefile)) $fatal(1, "need +cases=");
        fd = $fopen(casefile, "r");
        if (fd == 0) $fatal(1, "cannot open %s", casefile);
        repeat (5) @(negedge clk);
        rstn = 1;
        repeat (2) @(negedge clk);
        vcount = 0;
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h", cv, cp, cr, ce);
            if (n != 4) break;
            v = cv; p_in = cp[5:0];
            start = 1; @(negedge clk); start = 0;
            while (!done) @(negedge clk);
            if (r_out !== cr || e_out !== signed'(ce)) begin
                errors++;
                $display("FAIL case %0d: v=%h P=%0d got (r=%h,e=%0d) want (r=%h,e=%0d)",
                         vcount, cv, cp, r_out, e_out, cr, signed'(ce));
            end
            vcount++;
            @(negedge clk);
        end
        $fclose(fd);
        if (errors == 0) begin
            $display("TB_FX_RSQRT PASS: %0d cases bit-exact", vcount);
            $finish;
        end else $fatal(1, "TB_FX_RSQRT FAIL: %0d/%0d", errors, vcount);
    end
    initial begin #10ms; $fatal(1, "watchdog"); end
endmodule
