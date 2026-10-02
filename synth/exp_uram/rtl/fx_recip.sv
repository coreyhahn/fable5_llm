// ============================================================
// EXPERIMENT COPY — NOT MIGRATION RTL.  Track P (URAM placement
// experiment), qwen-next de-risking, docs/QWEN35_NEXT_FEASIBILITY.md
// section 6 item 3 / section 8 D3.  Source of truth stays rtl/fx_recip.sv;
// main/rtl is UNTOUCHED by this directory.  These files exist only to
// answer "does the 4B/9B-widened layer_chan synthesize to 928 URAM,
// and does it PLACE on the VU9P".  No testbench campaign was run
// against them and they are NOT functionally verified.
// Copied from rtl/fx_recip.sv @ git aa9c1efa
// ============================================================
// fx_recip: serial 1/x engine — bit-exact mirror of fixedpoint.recip_q.
//   input  value = v * 2^-P (v 48-bit unsigned nonzero)
//   output 1/value = r * 2^-30 * 2^e   (r Q30, e signed)
// 256-entry LUT seed (m in [1,2)) + 2 Newton iterations: r' = r*(2 - m*r).

`timescale 1ns/1ps
`default_nettype none

module fx_recip #(
    parameter string ROM_FILE = "recip_rom.hex"
) (
    input  wire               clk,
    input  wire               rstn,
    input  wire               start,
    input  wire [47:0]        v,
    input  wire [5:0]         p_in,
    output logic              done,
    output logic [31:0]       r_out,       // Q30
    output logic signed [7:0] e_out
);
    logic [15:0] rom [256];
    initial $readmemh(ROM_FILE, rom);
    logic [7:0]  rom_addr;
    logic [15:0] rom_q;
    always_ff @(posedge clk) rom_q <= rom[rom_addr];

    logic signed [32:0] mul_a, mul_b;
    logic signed [65:0] mul_p0, mul_p;
    always_ff @(posedge clk) begin
        mul_p0 <= mul_a * mul_b;
        mul_p  <= mul_p0;
    end

    typedef enum logic [2:0] {IDLE, NORM, LUTW, SEED, M_MR, M_RT, FIN} st_e;
    st_e st;
    logic [1:0] wcnt;
    logic [0:0] iter;

    logic [47:0] v_q;
    logic [5:0]  p_q;
    logic [31:0] m;                  // Q30 in [1,2)
    logic signed [9:0] sh_q;
    logic [31:0] r;

    function automatic logic signed [9:0] bitlen48(input logic [47:0] x);
        for (int i = 47; i >= 0; i--)
            if (x[i]) return 10'(i + 1);
        return 10'd0;
    endfunction

    wire mul_ready = (wcnt == 2'd3);

    always_ff @(posedge clk) begin
        if (!rstn) begin
            st <= IDLE;
            done <= 1'b0;
        end else begin
            done <= 1'b0;
            if (st inside {M_MR, M_RT}) wcnt <= wcnt + 1'b1;
            case (st)
                IDLE: if (start) begin
                    v_q <= v;
                    p_q <= p_in;
                    st <= NORM;
                end
                NORM: begin
                    logic signed [9:0] s;
                    /* verilator lint_off UNUSEDSIGNAL */
                    logic [47:0] sh;   // [47:32] zero after normalize
                    /* verilator lint_on UNUSEDSIGNAL */
                    s = bitlen48(v_q) - 10'sd31;
                    if (s >= 0) sh = v_q >> s[5:0];
                    else        sh = v_q << ((-s) & 10'sd63);
                    m <= sh[31:0];
                    sh_q <= s;
                    rom_addr <= sh[29:22];           // (m - 2^30) >> 22
                    st <= LUTW;
                end
                LUTW: st <= SEED;
                SEED: begin
                    r <= {1'b0, rom_q, 15'b0};
                    iter <= 1'b0;
                    mul_a <= 33'(m);
                    mul_b <= {2'b0, rom_q, 15'b0};
                    st <= M_MR;
                    wcnt <= '0;
                end
                M_MR: if (mul_ready) begin           // mul_p = m*r
                    mul_a <= 33'(r);
                    mul_b <= 33'((34'sd2 <<< 30) - 34'(mul_p >>> 30));
                    st <= M_RT;
                    wcnt <= '0;
                end
                M_RT: if (mul_ready) begin           // mul_p = r*(2-mr)
                    st <= FIN;
                end
                FIN: begin
                    r <= 32'(mul_p >>> 30);
                    if (!iter) begin
                        iter <= 1'b1;
                        mul_a <= 33'(m);
                        mul_b <= 33'(mul_p >>> 30);
                        st <= M_MR;
                        wcnt <= '0;
                    end else begin
                        done <= 1'b1;
                        st <= IDLE;
                    end
                end
                default: st <= IDLE;
            endcase
        end
    end

    assign r_out = r;
    assign e_out = 8'(-(sh_q + 10'sd30 - 10'(p_q)));

endmodule

`default_nettype wire
