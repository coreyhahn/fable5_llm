// gate_unit: per-head DeltaNet gates — bit-exact mirror of the gate chain
// in layer_fixed.deltanet_decode_fx (16 heads, serial):
//   beta[h]  = sigmoid_q(b[h])                                  (Q15)
//   sp       = softplus_q(b17'(a[h] + dt[h]))                   (Q12)
//   g        = -rshr(A[h] * sp, 11)                             (Q16, <=0)
//   decay[h] = rshr(exp_neg(g), 15)                             (Q15)
// b/a int16 Q12 (clipped transport per spec); A Q15 (18b), dt Q12.

`timescale 1ns/1ps
`default_nettype none

module gate_unit #(
    parameter int NH = 16,
    parameter string SIGMOID_ROM = "sigmoid_pair_rom.hex",
    parameter string SOFTPLUS_ROM = "softplus_pair_rom.hex",
    parameter string EXP2_ROM = "exp2_pair_rom.hex"
) (
    input  wire                clk,
    input  wire                rstn,
    input  wire                start,
    output logic               busy,
    output logic               done,

    // preload: sel 0=b 1=a 2=A(Q15,18b) 3=dt
    input  wire                w_we,
    input  wire [1:0]          w_sel,
    input  wire [3:0]          w_addr,
    input  wire signed [17:0]  w_data,

    // results readable after done
    output logic [15:0]        beta_o  [NH],
    output logic [15:0]        decay_o [NH]
);
    import fx_pkg::*;

    // input-registered preload (keeps the scratch-BRAM haul off the
    // write decode; see attn_core q port)
    logic               wwe_q;
    logic [1:0]         wsel_q;
    logic [3:0]         waddr_q;
    logic signed [17:0] wdata_q;
    logic signed [15:0] bv [NH];
    logic signed [15:0] av [NH];
    logic [17:0] Av [NH];           // UNSIGNED Q15 (A in (0,8))
    logic signed [15:0] dtv [NH];
    always_ff @(posedge clk) begin
        wwe_q   <= w_we;
        wsel_q  <= w_sel;
        waddr_q <= w_addr;
        wdata_q <= w_data;
        if (wwe_q) begin
            case (wsel_q)
                2'd0: bv[waddr_q]  <= wdata_q[15:0];
                2'd1: av[waddr_q]  <= wdata_q[15:0];
                2'd2: Av[waddr_q]  <= unsigned'(wdata_q);
                2'd3: dtv[waddr_q] <= wdata_q[15:0];
            endcase
        end
    end

    logic [31:0] sg_rom [256];
    logic [33:0] sp_rom [256];
    logic [35:0] ex_rom [256];
    initial $readmemh(SIGMOID_ROM, sg_rom);
    initial $readmemh(SOFTPLUS_ROM, sp_rom);
    initial $readmemh(EXP2_ROM, ex_rom);

    typedef enum logic [4:0] {IDLE, SG_I, SG_O, SG_M, SG_P, SG_W,
                              SP_O, SP_M, SP_P, SP_W,
                              GM_B, EX_NF, EX_ROM,
                              EX_I1, EX_I2, EX_I3, EX_I4, EX_I5, NXT} st_e;
    st_e st;
    logic [4:0] h;

    // PWL interp helper over [-16,16) domain, 256 segs (sigmoid/softplus)
    function automatic logic [17:0] pwl_idx_lo(input logic signed [17:0] x);
        logic signed [17:0] xc;
        if (x > 18'sd65535)        xc = 18'sd65535;
        else if (x < -18'sd65536)  xc = -18'sd65536;
        else                       xc = x;
        return 18'(xc + 18'sd65536);    // {idx[7:0], lo[8:0]} in [0,2^17)
    endfunction

    logic [16:0] u_q;
    logic [31:0] sgp_q;
    logic [33:0] spp_q;
    logic [35:0] exp_q;
    logic signed [17:0] sp_val;
    logic [5:0]  en_n;

    // interp pipeline registers (one small step per cycle; the one-state
    // interp+shift monoliths were the worst path family in build_017)
    logic [16:0] ba, bd;           // sigmoid endpoints: a, b-a
    logic [27:0] bpm;              // bd * u_lo (28-bit wrap of original)
    logic signed [17:0] adt_q;     // av + dtv, 18-bit
    logic        adt_hi, adt_lo;   // >= 2^16 / < -2^16 branch flags
    logic [17:0] sa, sd;           // softplus endpoints
    logic [28:0] spm;
    logic [17:0] ga;               // exp endpoints
    logic [18:0] gd;
    logic [27:0] gpm;
    logic [30:0] e16g;
    logic        ez_g, el_g;       // en_n >= 31 / <= 14
    logic [4:0]  esh_g;            // |14 - en_n|
    logic [30:0] gesv;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [16:0] ef;   // bit 16 zero by construction
    /* verilator lint_on UNUSEDSIGNAL */

    // shared multiplier
    logic signed [32:0] mul_a, mul_b;
    /* verilator lint_off UNUSEDSIGNAL */
    logic signed [65:0] mul_p0, mul_p;
    /* verilator lint_on UNUSEDSIGNAL */
    always_ff @(posedge clk) begin
        mul_p0 <= mul_a * mul_b;
        mul_p  <= mul_p0;
    end
    logic [1:0] wcnt;

    localparam logic signed [32:0] LOG2E_Q16 = 33'sd94548;

    always_ff @(posedge clk) begin
        if (!rstn) begin
            st <= IDLE;
            busy <= 1'b0;
            done <= 1'b0;
        end else begin
            done <= 1'b0;
            if (st == EX_NF) wcnt <= wcnt + 1'b1;
            case (st)
                IDLE: if (start) begin
                    h <= '0;
                    busy <= 1'b1;
                    st <= SG_I;
                end
                // sigmoid(b)
                SG_I: begin
                    u_q <= 17'(pwl_idx_lo(18'(bv[h[3:0]])));
                    st <= SG_O;
                end
                SG_O: begin
                    sgp_q <= sg_rom[u_q[16:9]];
                    st <= SG_M;
                end
                // sigmoid interp, one step per cycle
                SG_M: begin
                    logic [16:0] a16, b16;
                    a16 = {1'b0, sgp_q[15:0]};
                    b16 = {1'b0, sgp_q[31:16]};
                    ba <= a16;
                    bd <= 17'(b16 - a16);
                    st <= SG_P;
                end
                SG_P: begin
                    bpm <= 28'(28'(bd) * 28'({19'b0, u_q[8:0]}));
                    st <= SG_W;
                end
                // beta write — and set up softplus(a + dt) index
                SG_W: begin
                    beta_o[h[3:0]] <= 16'(ba + 17'((bpm + 28'd256) >> 9));
                    u_q <= 17'(pwl_idx_lo(18'(av[h[3:0]]) + 18'(dtv[h[3:0]])));
                    adt_q <= 18'(av[h[3:0]]) + 18'(dtv[h[3:0]]);
                    st <= SP_O;
                end
                SP_O: begin
                    spp_q <= sp_rom[u_q[16:9]];
                    st <= SP_M;
                end
                // softplus interp, one step per cycle
                SP_M: begin
                    logic [17:0] a17, b17;
                    a17 = {1'b0, spp_q[16:0]};
                    b17 = {1'b0, spp_q[33:17]};
                    sa <= a17;
                    sd <= 18'(b17 - a17);
                    // softplus(x)=x for x >= 16: spec branch
                    adt_hi <= (adt_q >= 18'sd65536);
                    adt_lo <= (adt_q < -18'sd65536);
                    st <= SP_P;
                end
                SP_P: begin
                    spm <= 29'(29'(sd) * 29'({20'b0, u_q[8:0]}));
                    st <= SP_W;
                end
                SP_W: begin
                    logic signed [17:0] spx;
                    spx = signed'(18'(sa + 18'((spm + 29'd256) >> 9)));
                    if (adt_hi) spx = adt_q;
                    if (adt_lo) spx = '0;
                    sp_val <= spx;
                    mul_a <= {15'b0, Av[h[3:0]]};   // zero-extend
                    mul_b <= 33'(spx);
                    wcnt <= '0;
                    st <= GM_B;
                end
                GM_B: begin
                    mul_b <= 33'(sp_val);
                    wcnt <= wcnt + 1'b1;
                    if (wcnt == 2'd3) begin
                        // g = -rshr(A*sp, 11) <= 0; start exp arg mult g*log2e
                        mul_a <= 33'(-(rshr64(64'(38'(mul_p)), 11)));
                        mul_b <= LOG2E_Q16;
                        st <= EX_NF;
                        wcnt <= '0;
                    end
                end
                // exp_neg(g): tq = (g*LOG2E)>>16 floor; n; f; rom; interp
                EX_NF: begin
                    if (wcnt == 2'd3) begin
                        logic signed [47:0] tt;
                        logic [47:0] nn;
                        tt = 48'(mul_p >>> 16);
                        nn = 48'((-tt + 48'sh FFFF) >> 16);
                        en_n <= (nn > 48'd62) ? 6'd62 : 6'(nn);
                        ef <= 17'(tt + 48'(48'((-tt + 48'sh FFFF) >> 16) << 16));
                        st <= EX_ROM;
                    end
                end
                EX_ROM: begin
                    exp_q <= ex_rom[ef[15:8]];
                    ez_g  <= (en_n >= 6'd31);
                    el_g  <= (en_n <= 6'd14);
                    esh_g <= (en_n <= 6'd14) ? 5'(6'd14 - en_n)
                                             : 5'(en_n - 6'd14);
                    st <= EX_I1;
                end
                // exp interp + 2^-n scale + rshr15, one step per cycle
                // (28-bit wrap arithmetic of the original preserved)
                EX_I1: begin
                    ga <= exp_q[17:0];
                    gd <= 19'(exp_q[35:18] - exp_q[17:0]);
                    st <= EX_I2;
                end
                EX_I2: begin
                    gpm <= 28'(28'(gd) * 28'({20'b0, ef[7:0]}));
                    st <= EX_I3;
                end
                EX_I3: begin
                    e16g <= 31'({13'b0, ga} + 31'(28'((gpm + 28'd128) >> 8)));
                    st <= EX_I4;
                end
                EX_I4: begin
                    gesv <= ez_g ? '0 : (el_g ? (e16g << esh_g)
                                              : (e16g >> esh_g));
                    st <= EX_I5;
                end
                EX_I5: begin
                    logic [16:0] dv;
                    dv = 17'((32'(gesv) + 32'd16384) >> 15);   // rshr15, v>=0
                    decay_o[h[3:0]] <= (dv > 17'd32767) ? 16'd32767 : 16'(dv);
                    st <= NXT;
                end
                NXT: begin
                    if (h + 1'b1 == 5'(NH)) begin
                        busy <= 1'b0;
                        done <= 1'b1;
                        st <= IDLE;
                    end else begin
                        h <= h + 1'b1;
                        st <= SG_I;
                    end
                end
                default: st <= IDLE;
            endcase
        end
    end

endmodule

`default_nettype wire
