// vecnorm_unit: RMSNorm / L2-norm — bit-exact mirror of layer_fixed.py
// rmsnorm_fx (modes 0/1) and l2norm_fx (mode 2).
//
//   mode 0: y = clip16(rshr( rshr(x*r, 30-e) * (w + 2^14), 14))   (1+w)
//   mode 1: same with plain w
//   mode 2: y = clip16(rshr(x*r, in_f + 30 - e - out_f))          no weight
// where (r,e) = rsqrt_q(sum(x^2), 2*in_f + (mode!=2 ? n_log2 : 0)).
//
// Serial: FILL (1 elem/cycle, accumulates sum of squares) -> RSQ ->
// OUT (~6 cycles/elem). N = 2^n_log2 <= 1024.
//
// ---- EPS-NORM (sequencer gated mode, docs/SEQ_ISA.md) ----------------
// cfg_eps (= layer_chan ARG2[0]) with cfg_mode == 2 selects the integer
// gated RMSNorm — bit-exact mirror of layer_fixed.eps_norm_scale /
// eps_norm_fx.  cfg_k is the DYNQ16 block-float shift, read out of the XRF
// by layer_chan (ARG2[3:1] picks the entry).  cfg_eps == 0 leaves modes
// 0/1/2 BIT-IDENTICAL to what shipped, which is the back-compat invariant.
//
//   eps_sh = (EPS_Q - 2*in_f - n_log2) + 2*k            EPS_Q = 40
//   E      = rshr64(EPS_M, eps_sh)     EPS_M = round(1e-6 * 2^40)
//   v      = ss + E                    (43 bits worst case; 48b port)
//   r, e   = rsqrt_q(v, 2*in_f + n_log2)      UNCHANGED ROM/Newton path,
//            declared at the NOMINAL binary point P0: rsqrt_q(v, P+2k) has
//            the same mantissa as rsqrt_q(v, P) and exponent e+k, so all of
//            k's effect is carried by the eps addend (the whole trick).
//   scale  = clip(rshr64(r, in_f - out_f + 15 - e), 0, 65535)
//   y      = clip16(rshr64(x * scale, 15))      constant >>15 per element
// The 16-bit scale clamp is provably inert on any non-zero block (DYNQ16
// floors |x|max at 16384 -> scale <= 46341); it fires only on all-zero
// blocks, whose output is zero for any scale.

`timescale 1ns/1ps
`default_nettype none

module vecnorm_legacy #(
    parameter string RSQRT_ROM = "rsqrt_rom.hex"
) (
    input  wire               clk,
    input  wire               rstn,

    input  wire [1:0]         cfg_mode,
    input  wire [3:0]         cfg_nlog2,
    input  wire [3:0]         cfg_inf,
    input  wire [3:0]         cfg_outf,
    input  wire               cfg_eps,      // ARG2[0]: EPS-NORM (mode 2 only)
    input  wire signed [5:0]  cfg_k,        // DYNQ16 k from the XRF
    input  wire               start,        // begin accepting N elements
    output logic              busy,

    // weight preload (static; modes 0/1)
    input  wire               w_we,
    input  wire [9:0]         w_waddr,
    input  wire [15:0]        w_wdata,

    input  wire               s_valid,
    output logic              s_ready,
    input  wire signed [15:0] s_data,

    output logic              m_valid,
    input  wire               m_ready,
    output logic signed [15:0] m_data
);
    import fx_pkg::*;

    logic signed [15:0] xbuf [1024];
    logic signed [15:0] wbuf [1024];
    always_ff @(posedge clk) if (w_we) wbuf[w_waddr] <= signed'(w_wdata);

    typedef enum logic [4:0] {IDLE, FILL, EPSC, RSQ, RSQW, O_PREP,
                              O_RD, O_M1, O_ABS, O_MAG, O_SHC, O_SHV,
                              O_SH, O_M2, O_EMIT, O_SC, O_SC2, O_SC3, O_SC4,
                              O_SCW} st_e;
    st_e st;

    // ---- EPS-NORM constants + state ----
    localparam logic [63:0] EPS_M = 64'd1099512;   // round(1e-6 * 2^40)
    localparam int          EPS_Q = 40;
    wire eps_on = cfg_eps && (cfg_mode == 2'd2);
    int  eps_sh;                    // (EPS_Q - 2*in_f - n_log2) + 2*k
    always_comb eps_sh = EPS_Q - 2 * int'(cfg_inf) - int'(cfg_nlog2)
                         + 2 * int'(cfg_k);
    // the integer eps addend E; only [47:0] reaches the 48-bit rsqrt port,
    // the top half is the out-of-envelope guard band
    /* verilator lint_off UNUSEDSIGNAL */
    logic [63:0] eps_e;
    /* verilator lint_on UNUSEDSIGNAL */
    logic [15:0] scale_q;           // Q15 multiplier (16-bit clamp)
    // EPS-NORM scale pipeline (O_SC..O_SC4): the clip(rshr64(rs_r, sh1))
    // chain broken into registered stages so the 64-bit variable shift +
    // round + clip never resolves in one cycle.  sh1 and rs_r are stable
    // for the whole vector, so this is pure retiming — bit-identical to the
    // former single-cycle O_SC (eps path only; modes 0/1/2 never enter it).
    logic        sc_left, sc_big;   // sh1<=0 (left) / sh1>=64 (result 0)
    logic [5:0]  sc_amt;            // capped shift magnitude
    logic [63:0] sc_rnd;            // right-shift round const 1<<(sh1-1)
    logic [63:0] sc_sum;            // {32'b0,rs_r} + sc_rnd  (right numerator)
    logic [63:0] sc_lsh, sc_rsh;    // left / right shifted results

    logic [10:0] cnt, n_total;
    logic [47:0] ss_acc;
    logic [10:0] oidx;

    // rsqrt engine
    logic        rs_start, rs_done;
    logic [31:0] rs_r;
    logic signed [7:0] rs_e;
    logic [47:0] rs_v;
    logic [5:0]  rs_p;
    fx_rsqrt #(.ROM_FILE(RSQRT_ROM)) u_rsqrt (
        .clk, .rstn, .start(rs_start), .v(rs_v), .p_in(rs_p),
        .done(rs_done), .r_out(rs_r), .e_out(rs_e)
    );

    // shared serial multiplier, 2-stage (read 3 cycles after operand set —
    // here each O_M state waits via sub-counter)
    logic signed [32:0] mul_a, mul_b;
    /* verilator lint_off UNUSEDSIGNAL */
    logic signed [65:0] mul_p0, mul_p;   // [65:64] unused: operands <= 48b
    /* verilator lint_on UNUSEDSIGNAL */
    always_ff @(posedge clk) begin
        mul_p0 <= mul_a * mul_b;
        mul_p  <= mul_p0;
    end
    logic [1:0] wcnt;

    logic signed [15:0] x_q;
    logic signed [63:0] ssh;       // registered shifted product
    int sh1;

    // rshr64s(v, sh1) decomposed: abs -> +round -> coarse shift -> fine
    // shift + sign restore. Per-vector shift fields registered at O_PREP
    // so the element loop never sees a full variable shifter in one stage.
    logic        sh_r;             // sh1 > 0 (rounding right shift)
    logic        sh_big;           // |sh1| >= 64: result is 0 either way
    logic [3:0]  sh_c4;            // |sh1| coarse (multiples of 4)
    logic [1:0]  sh_f2;            // |sh1| fine
    logic [63:0] rnd_q;            // 1 << (sh1-1), right-shift round const
    logic        p_sgn;
    logic [63:0] p_abs, p_mag, p_c;
    logic signed [63:0] p_raw, l_c;

    assign s_ready = (st == FILL);

    always_ff @(posedge clk) begin
        if (!rstn) begin
            st <= IDLE;
            busy <= 1'b0;
            m_valid <= 1'b0;
        end else begin
            case (st)
                IDLE: if (start) begin
                    cnt <= '0;
                    ss_acc <= '0;
                    n_total <= 11'd1 << cfg_nlog2;
                    busy <= 1'b1;
                    st <= FILL;
                end
                FILL: if (s_valid) begin
                    xbuf[cnt[9:0]] <= s_data;
                    ss_acc <= ss_acc + 48'(32'(s_data) * 32'(s_data));
                    cnt <= cnt + 1'b1;
                    if (cnt + 1'b1 == n_total) st <= eps_on ? EPSC : RSQ;
                end
                // E = rshr64(EPS_M, eps_sh) — ONE 64-bit shifter, once per
                // vector, outside the element loop.  EPS_M > 0 so the
                // round-half-away reduces to +(1 << (sh-1)).
                EPSC: begin
                    if (eps_sh <= 0)
                        eps_e <= (eps_sh <= -64) ? 64'd0
                                                 : (EPS_M << (-eps_sh));
                    else if (eps_sh >= 64) eps_e <= 64'd0;
                    else eps_e <= (EPS_M + (64'd1 << (eps_sh - 1))) >> eps_sh;
                    st <= RSQ;
                end
                RSQ: begin
                    logic [47:0] v;
                    v = eps_on ? (ss_acc + eps_e[47:0]) : ss_acc;
                    rs_v <= (v == 0) ? 48'd1 : v;
                    // EPS-NORM declares the NOMINAL binary point, i.e. the
                    // bit-identical mode-0/1 wiring: k is carried by E only.
                    rs_p <= 6'(2 * cfg_inf) +
                            (((cfg_mode != 2'd2) || eps_on) ? 6'(cfg_nlog2)
                                                            : 6'd0);
                    rs_start <= 1'b1;
                    st <= RSQW;
                end
                RSQW: begin
                    rs_start <= 1'b0;
                    if (rs_done) begin
                        sh1 <= eps_on
                               ? (int'(cfg_inf) - int'(cfg_outf) + 15
                                  - int'(rs_e))
                               : (cfg_mode == 2'd2)
                               ? (int'(cfg_inf) + 30 - int'(rs_e) - int'(cfg_outf))
                               : (30 - int'(rs_e));
                        oidx <= '0;
                        st <= eps_on ? O_SC : O_PREP;
                    end
                end
                // scale = clip(rshr64(rs_r, sh1), 0, 65535).  rs_r is Q30 in
                // (2^29, 2^30], so any LEFT shift already exceeds the clamp;
                // capping the shift at 32 keeps the 64-bit intermediate from
                // wrapping without changing the clamped result.
                // scale = clip(rshr64(rs_r, sh1), 0, 65535), pipelined over
                // four cycles (sh1, rs_r constant for the vector).  The
                // decode of sh1 -> (left/big, capped amount, round const) is
                // done ONCE here, off the per-shift critical path.
                //   O_SC  : decode shift control
                //   O_SC2 : right numerator (rs_r+round) + left shift
                //   O_SC3 : right shift
                //   O_SC4 : select + 16-bit clamp
                // Bit-identical to the former single-cycle O_SC.
                O_SC: begin         // decode
                    sc_left <= (sh1 <= 0);
                    sc_big  <= (sh1 >= 64);
                    sc_amt  <= (sh1 <= 0) ? (((-sh1) > 32) ? 6'd32
                                                           : 6'((-sh1)))
                                          : sh1[5:0];
                    sc_rnd  <= ((sh1 > 0) && (sh1 < 64))
                               ? (64'd1 << (sh1 - 1)) : 64'd0;
                    st <= O_SC2;
                end
                O_SC2: begin        // rounded right numerator, left result
                    sc_sum <= {32'b0, rs_r} + sc_rnd;
                    sc_lsh <= {32'b0, rs_r} << sc_amt;
                    st <= O_SC3;
                end
                O_SC3: begin        // right-shift
                    sc_rsh <= sc_sum >> sc_amt;
                    st <= O_SC4;
                end
                O_SC4: begin        // select + clamp
                    logic [63:0] sr;
                    sr = sc_left ? sc_lsh : (sc_big ? 64'd0 : sc_rsh);
                    scale_q <= (sr > 64'd65535) ? 16'hFFFF : sr[15:0];
                    st <= O_RD;
                end
                O_PREP: begin       // decode per-vector shift fields once
                    logic [5:0] amag;
                    amag = (sh1 > 0) ? 6'(sh1) : 6'(-sh1);
                    sh_r   <= (sh1 > 0);
                    sh_big <= (sh1 >= 64) || (sh1 <= -64);
                    sh_c4  <= amag[5:2];
                    sh_f2  <= amag[1:0];
                    rnd_q  <= (sh1 > 0 && sh1 < 64) ? (64'd1 << (sh1 - 1))
                                                    : 64'd0;
                    st <= O_RD;
                end
                O_RD: begin
                    x_q <= xbuf[oidx[9:0]];
                    st <= O_M1;
                    wcnt <= '0;
                end
                O_M1: begin
                    mul_a <= 33'(x_q);
                    mul_b <= eps_on ? 33'({17'b0, scale_q}) : 33'(rs_r);
                    wcnt <= wcnt + 1'b1;
                    if (wcnt == 2'd3) begin
                        p_raw <= 64'(mul_p);
                        st <= eps_on ? O_SCW : O_ABS;
                    end
                end
                // EPS-NORM output: constant >>15 round-half-away + clip16
                // (the vec_alu op-2 SCALE datapath, no variable shifter).
                O_SCW: begin
                    m_data <= clip16(rshr64(p_raw, 15));
                    m_valid <= 1'b1;
                    st <= O_EMIT;
                end
                // rshr64s(p_raw, sh1), one small step per cycle
                O_ABS: begin
                    p_sgn <= (p_raw < 0);
                    p_abs <= (p_raw < 0) ? unsigned'(-p_raw)
                                         : unsigned'(p_raw);
                    st <= O_MAG;
                end
                O_MAG: begin
                    p_mag <= p_abs + rnd_q;
                    st <= O_SHC;
                end
                O_SHC: begin
                    p_c <= p_mag >> {sh_c4, 2'b00};
                    l_c <= p_raw <<< {sh_c4, 2'b00};
                    st <= O_SHV;
                end
                O_SHV: begin
                    logic [63:0] p_f;
                    p_f = p_c >> sh_f2;
                    ssh <= sh_big ? 64'sd0
                         : sh_r   ? (p_sgn ? -signed'(p_f) : signed'(p_f))
                                  : (l_c <<< sh_f2);
                    st <= O_SH;
                end
                O_SH: begin
                    if (cfg_mode == 2'd2) begin
                        m_data <= clip16(ssh);
                        m_valid <= 1'b1;
                        st <= O_EMIT;
                    end else begin
                        // 33-bit intermediate: spec constraint, mirrored
                        // by the clip in layer_fixed.rmsnorm_fx
                        mul_a <= 33'(ssh);
                        mul_b <= 33'(32'(wbuf[oidx[9:0]])
                                 + ((cfg_mode == 2'd0) ? 33'sd16384 : 33'sd0));
                        wcnt <= '0;
                        st <= O_M2;
                    end
                end
                O_M2: begin
                    wcnt <= wcnt + 1'b1;
                    if (wcnt == 2'd3) begin
                        m_data <= clip16(rshr64(64'(mul_p), 14));
                        m_valid <= 1'b1;
                        st <= O_EMIT;
                    end
                end
                O_EMIT: if (m_ready) begin
                    m_valid <= 1'b0;
                    oidx <= oidx + 1'b1;
                    if (oidx + 1'b1 == n_total) begin
                        busy <= 1'b0;
                        st <= IDLE;
                    end else
                        st <= O_RD;
                end
                default: st <= IDLE;
            endcase
        end
    end

endmodule

`default_nettype wire
