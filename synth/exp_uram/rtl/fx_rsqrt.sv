// ============================================================
// EXPERIMENT COPY — NOT MIGRATION RTL.  Track P (URAM placement
// experiment), qwen-next de-risking, docs/QWEN35_NEXT_FEASIBILITY.md
// section 6 item 3 / section 8 D3.  Source of truth stays rtl/fx_rsqrt.sv;
// main/rtl is UNTOUCHED by this directory.  These files exist only to
// answer "does the 4B/9B-widened layer_chan synthesize to 928 URAM,
// and does it PLACE on the VU9P".  No testbench campaign was run
// against them and they are NOT functionally verified.
// Copied from rtl/fx_rsqrt.sv @ git aa9c1efa
// ============================================================
// fx_rsqrt: serial 1/sqrt engine — bit-exact mirror of fixedpoint.rsqrt_q.
//   input  value = v * 2^-P  (v 48-bit unsigned nonzero, P 0..63)
//   output 1/sqrt(value) = r * 2^-30 * 2^e   (r Q30, e signed)
// 512-entry bit-slice LUT seed + 2 Newton iterations on one shared
// multiplier (2-stage registered for timing). Latency ~26 cycles.

`timescale 1ns/1ps
`default_nettype none

module fx_rsqrt #(
    parameter string ROM_FILE = "rsqrt_rom.hex"
) (
    input  wire               clk,
    input  wire               rstn,
    input  wire               start,
    input  wire [47:0]        v,
    input  wire [5:0]         p_in,
    output logic              done,        // 1-cycle pulse, r_out/e_out valid
    output logic [31:0]       r_out,       // Q30
    output logic signed [7:0] e_out
);

    logic [15:0] rom [512];
    initial $readmemh(ROM_FILE, rom);
    logic [8:0]  rom_addr;
    logic [15:0] rom_q;
    always_ff @(posedge clk) rom_q <= rom[rom_addr];

    // shared multiplier: 33x33 signed, 2-stage output register
    logic signed [32:0] mul_a, mul_b;
    logic signed [65:0] mul_p0, mul_p;
    always_ff @(posedge clk) begin
        mul_p0 <= mul_a * mul_b;
        mul_p  <= mul_p0;
    end

    typedef enum logic [3:0] {IDLE, NORM, LUTRD, LUTW, SEED,
                              M_R2, M_MR, M_RT, FIN} st_e;
    st_e st;
    logic [1:0] wcnt;                // multiplier wait counter
    logic [0:0] iter;

    logic [47:0] v_q;
    logic [5:0]  p_q;
    logic [31:0] m;                  // Q30 in [1,4)
    logic signed [9:0] e_full;       // E (even)
    logic [31:0] r;                  // Q30

    function automatic logic signed [9:0] bitlen48(input logic [47:0] x);
        for (int i = 47; i >= 0; i--)
            if (x[i]) return 10'(i + 1);
        return 10'd0;
    endfunction

    // operands set at edge T -> mul_a valid T+1 -> mul_p0 valid edge T+2 ->
    // mul_p valid edge T+3 -> safe to READ during cycle (T+3,T+4], i.e. the
    // transition edge T+4. wcnt counts edges T+1.. so read when wcnt==3.
    wire mul_ready = (wcnt == 2'd3);

    always_ff @(posedge clk) begin
        if (!rstn) begin
            st <= IDLE;
            done <= 1'b0;
        end else begin
            done <= 1'b0;
            if (st inside {M_R2, M_MR, M_RT}) wcnt <= wcnt + 1'b1;
            case (st)
                IDLE: if (start) begin
                    v_q <= v;
                    p_q <= p_in;
                    st <= NORM;
                end
                NORM: begin
                    logic signed [9:0] s;
                    /* verilator lint_off UNUSEDSIGNAL */
                    logic [47:0] sh;   // [47:32] zero by normalization
                    /* verilator lint_on UNUSEDSIGNAL */
                    s = bitlen48(v_q) - 10'sd32;
                    if (((s - 10'(p_q)) & 10'sd1) != 0) s = s + 10'sd1;
                    if (s >= 0) sh = v_q >> s[5:0];
                    else        sh = v_q << ((-s) & 10'sd63);
                    m <= sh[31:0];
                    e_full <= s - 10'(p_q) + 10'sd30;
                    st <= LUTRD;
                end
                LUTRD: begin
                    rom_addr <= m[31] ? {1'b1, m[30:23]} : {1'b0, m[29:22]};
                    st <= LUTW;
                end
                LUTW: st <= SEED;        // rom_q registers this cycle
                SEED: begin
                    r <= {1'b0, rom_q, 15'b0};
                    iter <= 1'b0;
                    st <= M_R2;
                    wcnt <= '0;
                    mul_a <= {2'b0, rom_q, 15'b0};
                    mul_b <= {2'b0, rom_q, 15'b0};
                end
                M_R2: if (mul_ready) begin       // mul_p = r*r
                    mul_a <= 33'(m);
                    mul_b <= 33'(mul_p >>> 30);  // r2 Q30
                    st <= M_MR;
                    wcnt <= '0;
                end
                M_MR: if (mul_ready) begin       // mul_p = m*r2
                    mul_a <= 33'(r);
                    mul_b <= 33'((34'sd3 <<< 30) - 34'(mul_p >>> 30));
                    st <= M_RT;
                    wcnt <= '0;
                end
                M_RT: if (mul_ready) begin       // mul_p = r*(3-mr2)
                    st <= FIN;
                end
                FIN: begin
                    r <= 32'(mul_p >>> 31);
                    if (!iter) begin
                        iter <= 1'b1;
                        mul_a <= 33'(mul_p >>> 31);
                        mul_b <= 33'(mul_p >>> 31);
                        st <= M_R2;
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
    assign e_out = 8'(-(e_full >>> 1));

endmodule

`default_nettype wire
