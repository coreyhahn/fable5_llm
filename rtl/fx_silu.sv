// fx_silu: pipelined silu(x) = x * sigmoid(x) — bit-exact mirror of
// fixedpoint.silu_q. Q12 in -> Q12 out. Fixed 7-cycle latency, accepts one
// input per cycle (no internal stall; consumer paces via in_valid).
//
// Task 14-A stage C (2026-09-06): the latency was 6 until s2 was split
// into s2a/s2b.  The VALUES are unchanged — see the note at s2a — only the
// cycle sig2 lands in.  conv4_silu's latency moves 10 -> 11 with it, and
// CONV's per-command LCYC 40,972 -> 40,973; nothing else in the design
// sees this module's latency.
//
// sigmoid: PWL over [-16,16), 256 segments, pair-packed ROM (one read).

`timescale 1ns/1ps
`default_nettype none

module fx_silu #(
    parameter string ROM_FILE = "sigmoid_pair_rom.hex"
) (
    input  wire                clk,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire                rstn,      // pipeline is self-flushing
    /* verilator lint_on UNUSEDSIGNAL */
    input  wire                in_valid,
    input  wire signed [20:0]  in_x,      // Q12; sigmoid arg clamped inside
    output logic               out_valid, // 7 cycles after in_valid
    output logic signed [15:0] out_y      // Q12
);
    import fx_pkg::*;

    logic [31:0] rom [256];
    initial $readmemh(ROM_FILE, rom);

    // s0: clamp, split index/frac
    logic               v0;
    logic signed [20:0] x0;
    logic [7:0]         idx0;
    logic [8:0]         lo0;
    always_ff @(posedge clk) begin
        logic signed [20:0] xc;
        /* verilator lint_off UNUSEDSIGNAL */
        logic [17:0] u;        // [17] always 0 after clamp
        /* verilator lint_on UNUSEDSIGNAL */
        v0 <= in_valid;
        if (in_x > 21'sd65535)        xc = 21'sd65535;
        else if (in_x < -21'sd65536)  xc = -21'sd65536;
        else                          xc = in_x;
        x0 <= in_x;                      // silu uses UNCLAMPED x (spec)
        u = 18'(xc + 21'sd65536);        // [0, 2^17)
        idx0 <= u[16:9];
        lo0  <= u[8:0];
    end

    // s1: rom read
    logic               v1;
    logic signed [20:0] x1;
    logic [8:0]         lo1;
    logic [31:0]        pq;
    always_ff @(posedge clk) begin
        v1  <= v0;
        x1  <= x0;
        lo1 <= lo0;
        pq  <= rom[idx0];
    end

    // s2a: b - a, the interpolation product and the round constant.
    //
    // TASK 14-A STAGE C.  s2 used to be ONE combinational cone worth
    // 2.29 ns of a 4.000 ns period: a 17-bit subtract, a DSP48E2 traversed
    // with NO internal pipeline register (A_B_DATA 0.192 -> PREADD 0.076 ->
    // MULTIPLIER 0.505 -> M_DATA 0.047 -> ALU 0.585 -> OUTPUT 0.109 =
    // 1.514 ns) and a 17-bit add — 12 logic levels, 59 % of the failing
    // CONV_SILU_M3 path
    // (evidence/qwen9b/g5/063_t14a_po2_xdma_0_axi_aclk_paths.rpt:2086-2172).
    // The split puts a register where the DSP's own P register can absorb it.
    //
    // THE ARITHMETIC IS IDENTICAL, and so is the TYPE of every operand.
    // `27'(lo1)` is UNSIGNED, so the product and the sum were unsigned and
    // the old `>>> 9` was a LOGICAL shift; t2a is therefore declared
    // unsigned and carries the 27-bit pattern the old `d` was computed in,
    // so s2b's `t2a >>> 9` is that `d` bit for bit.  Only the cycle moves.
    logic               v2a;
    logic signed [20:0] x2a;
    logic signed [16:0] a2a;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [26:0]        t2a;   // [8:0] discarded by s2b's >>> 9
    /* verilator lint_on UNUSEDSIGNAL */
    always_ff @(posedge clk) begin
        logic signed [16:0] a, b;
        v2a <= v1;
        x2a <= x1;
        a = {1'b0, pq[15:0]};
        b = {1'b0, pq[31:16]};
        a2a <= a;
        t2a <= 27'(17'(b - a)) * 27'(lo1) + 27'sd256;
    end

    // s2b: the shift and the add — the tail of the old s2, unchanged
    logic               v2;
    logic signed [20:0] x2;
    logic [15:0]        sig2;
    always_ff @(posedge clk) begin
        /* verilator lint_off UNUSEDSIGNAL */
        logic signed [26:0] d; // upper bits sign copies
        /* verilator lint_on UNUSEDSIGNAL */
        v2 <= v2a;
        x2 <= x2a;
        d = 27'(t2a >>> 9);
        sig2 <= 16'(a2a + 17'(d));
    end

    // s3-4: x * sigmoid (2-stage mult)
    logic v3, v4;
    logic signed [37:0] m3, m4;
    always_ff @(posedge clk) begin
        v3 <= v2;
        m3 <= 38'(x2) * 38'({1'b0, sig2});  // 21b x 17b <= 38b
        v4 <= v3;
        m4 <= m3;
    end

    // s5: round
    always_ff @(posedge clk) begin
        out_valid <= v4;
        out_y <= clip16(rshr64(64'(m4), 15));
    end

endmodule

`default_nettype wire
