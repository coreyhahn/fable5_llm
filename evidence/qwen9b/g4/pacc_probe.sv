// pacc_probe — G4b Step 2, the SIM half of the p_acc headroom measurement.
//
// A passive monitor BOUND into every rtl/matvec_engine instance.  It drives
// nothing and reads one register, so the design under test is bit-identical
// with and without it; the only reason it is a separate file under
// evidence/ rather than an edit to tb/ is that this task does not touch the
// testbenches.
//
// It samples `p_acc` (rtl/matvec_engine.sv:561, the signed 48-bit row
// accumulator) on EVERY clock, not only when it is written, so the reported
// maximum is the largest magnitude the CONTAINER ever holds -- intermediate
// group sums included, which is what "does it fit 48 bits" actually asks.
//
// `final` prints one line per engine instance; the runner greps PACC_SIM.
`timescale 1ns/1ps
`default_nettype none

module pacc_probe (
    input wire               clk,
    input wire               rstn,
    input wire signed [47:0] p_acc
);
    longint unsigned nsamp;
    longint unsigned mx_abs;

    initial begin
        nsamp = 0; mx_abs = 0;
    end

    always @(posedge clk) begin
        if (rstn) begin
            longint unsigned a;
            // |p_acc| as an unsigned magnitude.  p_acc is 48 bits so the
            // negation cannot overflow the 64-bit accumulator.
            a = p_acc[47] ? longint'(unsigned'(-p_acc)) & 64'hFFFF_FFFF_FFFF
                          : longint'(unsigned'(p_acc));
            nsamp = nsamp + 1;
            if (a > mx_abs) mx_abs = a;
        end
    end

    final begin
        $display("PACC_SIM %m samples=%0d max_abs_p_acc=%0d", nsamp, mx_abs);
    end
endmodule

// Bind one into every matvec_engine.  `bind` keeps the RTL untouched.
bind matvec_engine pacc_probe u_pacc_probe (
    .clk(clk), .rstn(rstn), .p_acc(p_acc)
);

`default_nettype wire
