// conv4_silu: depthwise 4-tap conv + silu — bit-exact mirror of the conv
// front-end in layer_fixed.deltanet_decode_fx:
//   pre = clip21(rshr(sum_j win[j]*w[j], RS_F+CW_F-12))   (Q12)
//   y   = clip16(silu_q(pre))                              (Q12)
// Pipelined, one channel per cycle; latency = 4 + fx_silu(7) = 11.
// Inputs per channel: window win[0..3] (Q8, oldest first) and weights
// w[0..3] (Q2.13) presented in parallel.

`timescale 1ns/1ps
`default_nettype none

module conv4_silu #(
    parameter string SIGMOID_ROM = "sigmoid_pair_rom.hex"
) (
    input  wire                clk,
    input  wire                rstn,
    input  wire                in_valid,
    input  wire signed [15:0]  win0, win1, win2, win3,
    input  wire signed [15:0]  w0, w1, w2, w3,
    output logic               out_valid,
    output logic signed [15:0] out_y       // Q12
);
    import fx_pkg::*;

    // s0: 4 products
    logic               v0;
    logic signed [31:0] p0 [4];
    always_ff @(posedge clk) begin
        v0 <= in_valid;
        p0[0] <= 32'(win0) * 32'(w0);
        p0[1] <= 32'(win1) * 32'(w1);
        p0[2] <= 32'(win2) * 32'(w2);
        p0[3] <= 32'(win3) * 32'(w3);
    end

    // s1: sum
    logic               v1;
    logic signed [33:0] acc1;
    always_ff @(posedge clk) begin
        v1 <= v0;
        acc1 <= 34'(p0[0]) + 34'(p0[1]) + 34'(p0[2]) + 34'(p0[3]);
    end

    // s2: shift + clip to the silu 21-bit port
    logic               v2;
    logic signed [20:0] pre2;
    always_ff @(posedge clk) begin
        logic signed [63:0] pre;
        v2 <= v1;
        // A2.1 (spec 0b): RS_F = 7 is the 9B operating point, so the
        // baked shift is RS_F + CW_F - 12 = 7 + 13 - 12 = 8.  It was 9 at
        // RS_F = 8.  This is the ONE RTL literal on the RS_F axis; the
        // host expression beside it already reads the constant (A2.3).
        pre = rshr64(64'(acc1), 8);          // RS_F + CW_F - 12 = 8
        if (pre > 64'sd1048575)        pre2 <= 21'sd1048575;
        else if (pre < -64'sd1048576)  pre2 <= -21'sd1048576;
        else                           pre2 <= 21'(pre);
    end

    // s3..: silu
    fx_silu #(.ROM_FILE(SIGMOID_ROM)) u_silu (
        .clk, .rstn,
        .in_valid(v2), .in_x(pre2),
        .out_valid(out_valid), .out_y(out_y)
    );

endmodule

`default_nettype wire
