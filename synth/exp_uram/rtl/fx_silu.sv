// ============================================================
// EXPERIMENT COPY — NOT MIGRATION RTL.  Track P (URAM placement
// experiment), qwen-next de-risking, docs/QWEN35_NEXT_FEASIBILITY.md
// section 6 item 3 / section 8 D3.  Source of truth stays rtl/fx_silu.sv;
// main/rtl is UNTOUCHED by this directory.  These files exist only to
// answer "does the 4B/9B-widened layer_chan synthesize to 928 URAM,
// and does it PLACE on the VU9P".  No testbench campaign was run
// against them and they are NOT functionally verified.
// Copied from rtl/fx_silu.sv @ git aa9c1efa
// ============================================================
// fx_silu: pipelined silu(x) = x * sigmoid(x) — bit-exact mirror of
// fixedpoint.silu_q. Q12 in -> Q12 out. Fixed 6-cycle latency, accepts one
// input per cycle (no internal stall; consumer paces via in_valid).
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
    output logic               out_valid, // 6 cycles after in_valid
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

    // s2: interpolate sigmoid (Q15)
    logic               v2;
    logic signed [20:0] x2;
    logic [15:0]        sig2;
    always_ff @(posedge clk) begin
        logic signed [16:0] a, b;
        /* verilator lint_off UNUSEDSIGNAL */
        logic signed [26:0] d; // upper bits sign copies
        /* verilator lint_on UNUSEDSIGNAL */
        v2 <= v1;
        x2 <= x1;
        a = {1'b0, pq[15:0]};
        b = {1'b0, pq[31:16]};
        d = (27'(17'(b - a)) * 27'(lo1) + 27'sd256) >>> 9;
        sig2 <= 16'(a + 17'(d));
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
