// tb_gate_unit: gate vectors replay (NH heads), bit-exact beta+decay.
//
// G3.4 (spec 4.6 wall 10): NH is a PARAMETER here rather than the ten bare
// literals it used to be -- including a 4-bit `w_addr` that would have
// failed SILENTLY at LNH = 32 (a truncated head index writes the wrong
// entry; it does not run off an array bound).  The vectors are still the
// 16-head set, so the default stays 16 and the DUT is instantiated at the
// vector's width; the 32-head width is exercised on the real gate_unit
// through layer_chan (tb_layer_dnbank's GATE case).
`timescale 1ns/1ps
module tb_gate_unit #(
    parameter int NH = 16
);
    localparam int HB = $clog2(NH);
    logic clk = 0;
    /* verilator lint_off BLKSEQ */
    always #2 clk = ~clk;
    /* verilator lint_on BLKSEQ */
    logic rstn = 0, start = 0, busy, done;
    /* verilator lint_off UNUSEDSIGNAL */
    wire bu = busy;
    /* verilator lint_on UNUSEDSIGNAL */
    logic w_we = 0;
    logic [1:0] w_sel = 0;
    logic [HB-1:0] w_addr = 0;
    logic signed [17:0] w_data = 0;
    logic [15:0] beta_o [NH];
    logic [15:0] decay_o [NH];

    gate_unit #(
        .NH(NH),
        .SIGMOID_ROM("../rtl/roms/sigmoid_pair_rom.hex"),
        .SOFTPLUS_ROM("../rtl/roms/softplus_pair_rom.hex"),
        .EXP2_ROM("../rtl/roms/exp2_pair_rom.hex")
    ) dut (.clk, .rstn, .start, .busy, .done,
           .w_we, .w_sel, .w_addr, .w_data, .beta_o, .decay_o);

    logic [15:0] bf [NH];
    logic [15:0] af [NH];
    logic [17:0] Af [NH];
    logic [15:0] dtf [NH];
    logic [15:0] gbeta [NH];
    logic [15:0] gdecay [NH];
    int errors = 0;

    string vecdir;
    initial begin
        int i;
        if (!$value$plusargs("vecdir=%s", vecdir)) $fatal(1, "need +vecdir=");
        $readmemh({vecdir, "/gate_b.hex"}, bf);
        $readmemh({vecdir, "/gate_a.hex"}, af);
        $readmemh({vecdir, "/gate_A.hex"}, Af);
        $readmemh({vecdir, "/gate_dt.hex"}, dtf);
        $readmemh({vecdir, "/gate_beta.hex"}, gbeta);
        $readmemh({vecdir, "/gate_decay.hex"}, gdecay);
        repeat (5) @(negedge clk);
        rstn = 1;
        repeat (2) @(negedge clk);
        for (i = 0; i < NH; i++) begin
            @(negedge clk); w_we = 1; w_sel = 0; w_addr = HB'(i);
            w_data = 18'(signed'(bf[i]));
        end
        for (i = 0; i < NH; i++) begin
            @(negedge clk); w_sel = 1; w_addr = HB'(i);
            w_data = 18'(signed'(af[i]));
        end
        for (i = 0; i < NH; i++) begin
            @(negedge clk); w_sel = 2; w_addr = HB'(i);
            w_data = signed'(Af[i]);          // full 18-bit A
        end
        for (i = 0; i < NH; i++) begin
            @(negedge clk); w_sel = 3; w_addr = HB'(i);
            w_data = 18'(signed'(dtf[i]));
        end
        @(negedge clk); w_we = 0;
        start = 1; @(negedge clk); start = 0;
        begin
            int guard = 0;
            while (!done) begin
                @(negedge clk); guard++;
                if (guard > 10000) begin errors++; $display("timeout"); break; end
            end
        end
        @(negedge clk);
        for (i = 0; i < NH; i++) begin
            if (beta_o[i] !== gbeta[i]) begin
                errors++;
                $display("FAIL beta[%0d]: got %h want %h", i, beta_o[i], gbeta[i]);
            end
            if (decay_o[i] !== gdecay[i]) begin
                errors++;
                $display("FAIL decay[%0d]: got %h want %h", i, decay_o[i], gdecay[i]);
            end
        end
        if (errors == 0) begin
            $display("TB_GATE_UNIT PASS: %0d heads beta+decay bit-exact", NH);
            $finish;
        end else $fatal(1, "TB_GATE_UNIT FAIL: %0d", errors);
    end
    initial begin #5ms; $fatal(1, "watchdog"); end
endmodule
