// vec_alu: serial vector glue math over external scratchpad ports —
// bit-exact mirrors of layer_fixed.py call sites. Matvec/attn/dn 32-bit
// values live in scratch as {lo,hi} int16 pairs (little-endian words).
//
// op 0 DYNQ8  (len)      y = clip(rshr(a,e), -127,127), e minimal s.t.
//                        max|y|<=127 (fp.dyn_quant_i8); e -> e_out
// op 1 SHIFT32(len,p0)   y = clip16(rshr64s(pair(a), p0))
// op 2 SCALE  (len,p0)   y = clip16(rshr64(a*p0, 15))      p0 = const Q15
// op 3 EMUL   (len,p0)   y = clip16(rshr64(a*b, p0))
// op 4 ADD    (len)      y = clip16(a + b)
// op 5 SILU16 (len,p0)   y = clip16(silu_q(rshr64s(a, p0)))
// op 6 SILU32 (len,p0)   y = clip16(silu_q(clip20(rshr64s(pair(a), p0))))
// op 7 SIGM16 (len,p0)   y = sigmoid_q(rshr64s(a, p0))           (Q15)
// op 8 EMUL32 (len,p0)   y = clip16(rshr64(pair(a)*b, p0))
// op 9 SHIFT32W(len,p0)  y32 = clip32(rshr64s(pair(a), p0)), written
//                        as {lo,hi} pairs (32-bit requant transport)
// op 10 AMAX32(len,p0)   running argmax over len {lo,hi} pairs; p0[0]=1
//                        resets the running state (fresh scan). Strictly-
//                        greater updates -> first occurrence of the max
//                        wins (np.argmax). Global element index runs
//                        across chained invocations (chunked vocab scan);
//                        winner on amax_idx/amax_val (layer CSRs).
// op 12 DYNQ16(len,p0)   two-pass block-float quantize over len {lo,hi}
//                        int32 pairs -> int16 at dst, EXACTLY
//                        ref/layer_fixed.py dynq16_fx:
//                          k = bf_shift(max|x|, guard 0) [clamp at 0 if
//                              p0[1]];  y = clip16(rshr64s(x, k))
//                        pass 1 scans max|x| (UNSIGNED 32b: x=-2^31 gives
//                        2^31, which does NOT fit signed 32); the exit
//                        state priority-encodes L=bitlen(maxabs), forms
//                        k = L-15 (+1 when the top 16 bits of maxabs are
//                        all ones -- the EXACT form of bf_shift's rounding
//                        fixup, one 16-input AND, no 64-bit compare), then
//                        decodes the rshr64s shift fields ONCE and reruns
//                        the op-1 SHIFT32 datapath as pass 2.
//                        k leaves on k_out/k_we; layer_chan latches it into
//                        XRF[p0[0] ? 2 : 1] (docs/SEQ_ISA.md).
//
// ---- op 8 probe mode (ISA v1.2 "attn k_a" ruling) --------------------
// cfg_p0[6] on an EMUL32 command enables PROBE mode: the pre-shift
// running max |pair(a)*b| is captured in maxp_out, and the exit state
// runs the SAME exponent unit as DYNQ16 over it (clamped at 0, i.e.
// layer_fixed.attn_o_shift semantics) and pulses k_out/k_we so the
// attention shift k_a lands in the XRF directly.
// cfg_p0[6] was chosen after reading the op-8 decode: op 8 consumes cfg_p0
// as an UNSIGNED rshr64 shift, so bits [5:0] are the shift and EVERY bit
// above 5 (including the sign) merely forces the `pu_big` flush-to-zero
// path -- there is no inert bit.  Bit 6 is therefore MASKED OUT of the
// op-8 shift decode (p0_e below): p0 in [0,63] behaves exactly as before
// (all shipped scripts use 8..15), and p0 in [64,127] -- which used to
// return all-zeros -- now means "probe, shift p0-64".
// ISA RECONCILIATION FLAG: docs/SEQ_ISA.md v1.2 says cfg_p0[2]; that bit
// is shift bit 2 for op 8 and cannot be used.

`timescale 1ns/1ps
`default_nettype none

module vec_alu_legacy #(
    parameter string SIGMOID_ROM = "sigmoid_pair_rom.hex"
) (
    input  wire                clk,
    input  wire                rstn,
    input  wire                start,
    output logic               busy,
    output logic               done,

    input  wire [3:0]          cfg_op,
    input  wire [11:0]         cfg_len,
    input  wire signed [16:0]  cfg_p0,
    input  wire [13:0]         cfg_srca,
    input  wire [13:0]         cfg_srcb,
    input  wire [13:0]         cfg_dst,
    output logic [3:0]         e_out,       // DYNQ8 exponent
    output logic [17:0]        amax_idx,    // AMAX32 running winner
    output logic signed [31:0] amax_val,
    // block-float exponent out (DYNQ16 op 12 / EMUL32 op 8 probe).
    // 7 bits: DYNQ16 k is in [-14,17] (the ISA's 6 bits), but the op-8
    // probe runs the same unit over a 48-bit product, where k reaches 33.
    output logic signed [6:0]  k_out,
    output logic               k_we,        // 1-cycle latch strobe
    output logic [47:0]        maxp_out,    // op-8 probe: max |prod| pre-shift

    // scratch ports (1-cycle read latency)
    output logic [13:0]        a_addr,
    input  wire signed [15:0]  a_q,
    output logic [13:0]        b_addr,
    input  wire signed [15:0]  b_q,
    output logic [13:0]        w_addr,
    output logic signed [15:0] w_data,
    output logic               w_en
);
    import fx_pkg::*;

    logic [31:0] sg_rom [256];
    initial $readmemh(SIGMOID_ROM, sg_rom);

    typedef enum logic [4:0] {IDLE,
                              Q_RD, Q_S, Q_W, Q_E,
                              E_RD, E_W, E_LO, E_HI, E_EX, E_MUL,
                              SH_A, SH_M, SH_C, SH_F,
                              S_U, S_ROM, S_INT, S_MUL,
                              WR, WR2, AM_C, Q16_C, K_E} st_e;
    st_e st;

    logic        am_first;         // no element seen since fresh scan
    logic [17:0] am_g;             // global element index across chunks

    logic [12:0] i;
    logic signed [15:0] aq16;     // registered scratch word (BRAM CQ leg)
    logic [11:0] len_q;
    logic [3:0]  op_q;
    logic [15:0] maxabs;
    logic [3:0]  eq;
    logic signed [15:0] a16, b16;
    /* verilator lint_off UNUSEDSIGNAL */
    logic signed [31:0] v32;   // [31:16] only used via local v in E_EX
    /* verilator lint_on UNUSEDSIGNAL */
    logic signed [20:0] x_silu;
    logic [16:0] u_q;
    logic [15:0] sig_q;
    logic signed [63:0] res;

    logic signed [32:0] mul_a, mul_b;
    /* verilator lint_off UNUSEDSIGNAL */
    logic signed [65:0] mul_p0, mul_p;
    /* verilator lint_on UNUSEDSIGNAL */
    always_ff @(posedge clk) begin
        mul_p0 <= mul_a * mul_b;
        mul_p  <= mul_p0;
    end
    logic [1:0] wcnt;

    // ---- block-float exponent state (op 12 DYNQ16 / op 8 probe) ----
    logic [31:0] mx32;      // DYNQ16 pass-1 running max |x|, UNSIGNED 32b
    logic [47:0] maxp;      // op-8 probe running max |prod|, pre-shift
    logic        probe_q;   // op-8 probe mode latched at dispatch
    logic        kclamp_q;  // clamp k at 0 (cfg_p0[1] / attn semantics)

    wire pair_op = (op_q == 4'd1) || (op_q == 4'd6) || (op_q == 4'd8)
                || (op_q == 4'd9) || (op_q == 4'd10) || (op_q == 4'd12);

    // ---- shared exponent unit, evaluated ONCE per vector in K_E ----
    // one priority encode + one normalising shift + a 16-input AND; no
    // 64-bit shifter, no rounding adder, no compare against 32767.
    wire [47:0] m_sel = (op_q == 4'd12) ? {16'b0, mx32} : maxp;
    logic [5:0] m_bl;                         // bitlen(m_sel), 0..48
    always_comb begin
        m_bl = 6'd0;
        for (int b = 0; b < 48; b++) if (m_sel[b]) m_bl = 6'(b + 1);
    end
    /* verilator lint_off UNUSEDSIGNAL */
    wire [47:0] m_norm = (m_bl >= 6'd16) ? (m_sel >> (m_bl - 6'd16)) : 48'd0;
    /* verilator lint_on UNUSEDSIGNAL */
    wire signed [6:0] k_raw = (m_bl == 6'd0) ? 7'sd0
                                             : (signed'({1'b0, m_bl}) - 7'sd15);
    wire        k_fix = (k_raw > 7'sd0) && (m_norm[15:0] == 16'hFFFF);
    wire signed [6:0] k_f1 = k_raw + (k_fix ? 7'sd1 : 7'sd0);
    wire signed [6:0] k_val = (kclamp_q && (k_f1 < 0)) ? 7'sd0 : k_f1;
    wire [5:0]  k_mag = k_val[6] ? 6'(-k_val) : 6'(k_val);

    // rshr64/rshr64s by cfg_p0 decomposed over SH_A/SH_M/SH_C/SH_F —
    // shift fields decoded ONCE at start (cfg_p0 is per-command constant)
    // so the element loop never computes a 64-bit variable shifter plus
    // rounding adders in a single stage.
    logic        ps_r;             // cfg_p0 > 0 (signed-interp right shift)
    logic        ps_big;           // |cfg_p0| >= 64 (signed interp: result 0)
    logic        pu_big;           // unsigned interp (rshr64): p0<0 or >=64
    logic [3:0]  ps_c4;            // |cfg_p0| coarse (multiples of 4)
    logic [1:0]  ps_f2;            // |cfg_p0| fine
    logic [63:0] ps_rnd;           // 1 << (cfg_p0-1)
    logic        p_sgn;
    logic [63:0] p_abs, p_mag, p_c;
    logic signed [63:0] p_q, l_c;

    // DYNQ8 write pass (op 15) shift fields, registered at Q_E exit so the
    // eq -> shifter cone never appears in one stage
    logic [3:0]  q_c4x;            // {eq[3:2], 2'b00} coarse nibble
    logic [1:0]  q_f2;
    logic [63:0] q_rnd;

    // per-op effective fields (op_q stable per command):
    // op 2 SCALE shifts by const 15; ops 3/8 use rshr64 (unsigned s);
    // op 15 shifts by eq (dynamic, always right, < 16);
    // ops 1/5/6/7/9 use rshr64s (signed s, negative = left shift).
    wire u_op = (op_q == 4'd3) || (op_q == 4'd8);
    wire c_op = (op_q == 4'd2);
    wire q_op = (op_q == 4'd15);
    wire        e_right = c_op | u_op | q_op | ps_r;
    wire        e_big   = (c_op | q_op) ? 1'b0 : (u_op ? pu_big : ps_big);
    wire [3:0]  e_c4    = c_op ? 4'd3 : (q_op ? q_c4x : ps_c4);
    wire [1:0]  e_f2    = c_op ? 2'd3 : (q_op ? q_f2 : ps_f2);
    wire [63:0] e_rnd   = c_op ? 64'd16384 : (q_op ? q_rnd : ps_rnd);

    always_ff @(posedge clk) begin
        if (!rstn) begin
            st <= IDLE;
            busy <= 1'b0;
            done <= 1'b0;
            w_en <= 1'b0;
            amax_idx <= '0;
            amax_val <= '0;
            am_first <= 1'b1;
            am_g <= '0;
            k_out <= '0;
            k_we <= 1'b0;
            maxp <= '0;
            probe_q <= 1'b0;
        end else begin
            done <= 1'b0;
            w_en <= 1'b0;
            k_we <= 1'b0;
            if (st inside {E_MUL, S_MUL}) wcnt <= wcnt + 1'b1;
            case (st)
                IDLE: if (start) begin
                    logic [5:0] amag;
                    logic signed [16:0] p0_e;
                    logic pr8;
                    // op-8 probe flag lives in cfg_p0[6] and is MASKED OUT of
                    // the shift decode, so p0 in [0,63] is bit-identical to
                    // the shipped behaviour (see the module header).
                    pr8  = (cfg_op == 4'd8) && cfg_p0[6];
                    p0_e = pr8 ? signed'({cfg_p0[16:7], 1'b0, cfg_p0[5:0]})
                               : cfg_p0;
                    amag = (p0_e > 0) ? 6'(p0_e) : 6'(-p0_e);
                    ps_r   <= (p0_e > 0);
                    ps_big <= (p0_e >= 17'sd64) || (p0_e <= -17'sd64);
                    pu_big <= (p0_e < 0) || (p0_e >= 17'sd64);
                    ps_c4  <= amag[5:2];
                    ps_f2  <= amag[1:0];
                    ps_rnd <= (p0_e > 0 && p0_e < 17'sd64)
                              ? (64'd1 << (p0_e - 1)) : 64'd0;
                    probe_q  <= pr8;
                    kclamp_q <= (cfg_op == 4'd12) ? cfg_p0[1] : 1'b1;
                    if (pr8)               maxp <= '0;
                    if (cfg_op == 4'd12)   mx32 <= '0;
                    if (cfg_op == 4'd10 && cfg_p0[0]) begin
                        am_g <= '0;           // fresh scan
                        am_first <= 1'b1;
                    end
                    i <= '0;
                    len_q <= cfg_len;
                    op_q <= cfg_op;
                    maxabs <= '0;
                    eq <= '0;
                    busy <= 1'b1;
                    if (cfg_op == 4'd0) begin
                        a_addr <= cfg_srca;
                        st <= Q_RD;
                    end else begin
                        a_addr <= ((cfg_op == 4'd1) || (cfg_op == 4'd6)
                                   || (cfg_op == 4'd8))
                                  ? cfg_srca : cfg_srca;
                        b_addr <= cfg_srcb;
                        st <= E_RD;
                    end
                end
                // ---------- DYNQ8 pass 1: maxabs scan ----------
                Q_RD: st <= Q_S;
                Q_S: begin
                    aq16 <= a_q;
                    st <= Q_W;
                end
                Q_W: begin
                    logic [15:0] av;
                    av = (aq16 < 0) ? 16'(-aq16) : 16'(aq16);
                    if (av > maxabs) maxabs <= av;
                    if (i + 1'b1 == 13'(len_q)) begin
                        st <= Q_E;
                    end else begin
                        i <= i + 1'b1;
                        a_addr <= cfg_srca + 14'(i) + 14'd1;
                        st <= Q_RD;
                    end
                end
                Q_E: begin   // find minimal e: rshr(maxabs, e) <= 127
                    logic [15:0] r;
                    r = 16'((32'(maxabs) + (32'd1 << eq >> 1)) >> eq);
                    if (r > 16'd127) begin
                        eq <= eq + 1'b1;
                    end else begin
                        e_out <= eq;
                        q_c4x <= {2'b00, eq[3:2]};
                        q_f2  <= eq[1:0];
                        q_rnd <= (eq == 4'd0) ? 64'd0
                                              : 64'(64'd1 << (eq - 4'd1));
                        i <= '0;
                        a_addr <= cfg_srca;
                        op_q <= 4'd15;        // internal: quant write pass
                        st <= E_RD;
                    end
                end
                // ---------- generic element loop ----------
                E_RD: st <= pair_op ? E_LO : E_W;
                E_LO: begin                   // first word of pair arrived? no:
                    a_addr <= a_addr + 14'd1; // request hi word
                    st <= E_W;
                end
                E_W: begin
                    if (pair_op) begin
                        v32[15:0] <= unsigned'(a_q);   // lo word
                        st <= E_HI;                    // hi arrives next
                    end else begin
                        a16 <= a_q;
                        b16 <= b_q;
                        st <= E_EX;
                    end
                end
                E_HI: begin                            // register hi word:
                    v32[31:16] <= unsigned'(a_q);      // BRAM CQ off the
                    b16 <= b_q;                        // shifter path
                    st <= E_EX;
                end
                E_EX: begin
                    logic signed [31:0] v;
                    v = pair_op ? v32 : 32'(a16);
                    v32 <= v;
                    case (op_q)
                        4'd15: begin                   // DYNQ8 write pass
                            p_q <= 64'(a16);
                            st <= SH_A;
                        end
                        4'd1, 4'd9: begin              // SHIFT32 / SHIFT32W
                            p_q <= 64'(v);
                            st <= SH_A;
                        end
                        4'd4: begin                    // ADD
                            res <= 64'(a16) + 64'(b16);
                            st <= WR;
                        end
                        4'd2: begin                    // SCALE
                            mul_a <= 33'(a16);
                            mul_b <= 33'(cfg_p0);
                            wcnt <= '0;
                            st <= E_MUL;
                        end
                        4'd3: begin                    // EMUL
                            mul_a <= 33'(a16);
                            mul_b <= 33'(b16);
                            wcnt <= '0;
                            st <= E_MUL;
                        end
                        4'd8: begin                    // EMUL32
                            mul_a <= 33'(v);
                            mul_b <= 33'(b_q);
                            wcnt <= '0;
                            st <= E_MUL;
                        end
                        4'd5, 4'd7: begin              // SILU16 / SIGM16
                            p_q <= 64'(a16);
                            st <= SH_A;
                        end
                        4'd6: begin                    // SILU32
                            p_q <= 64'(v);
                            st <= SH_A;
                        end
                        4'd10: begin                   // AMAX32
                            p_q <= 64'(v);
                            st <= AM_C;
                        end
                        4'd12: begin                   // DYNQ16 scan pass
                            p_q <= 64'(v);
                            st <= Q16_C;
                        end
                        default: st <= WR;
                    endcase
                end
                // ---------- DYNQ16 pass 1: max|x| scan ----------
                Q16_C: begin
                    logic signed [32:0] vv;
                    /* verilator lint_off UNUSEDSIGNAL */
                    logic [32:0] av;   // [32] always 0: |x| <= 2^31
                    /* verilator lint_on UNUSEDSIGNAL */
                    // 33 bits on purpose: |-2^31| = 2^31 does NOT fit a
                    // signed 32-bit register (the one width trap in this op)
                    vv = 33'(signed'(p_q[31:0]));
                    av = (vv < 0) ? unsigned'(-vv) : unsigned'(vv);
                    if (av[31:0] > mx32) mx32 <= av[31:0];
                    if (i + 1'b1 == 13'(len_q)) begin
                        i <= '0;
                        a_addr <= cfg_srca;         // rewind for pass 2
                        st <= K_E;
                    end else begin
                        i <= i + 1'b1;
                        a_addr <= cfg_srca + 14'((14'(i) + 14'd1) * 14'd2);
                        st <= E_RD;
                    end
                end
                // ---------- block-float exponent (pass-1 exit / probe) ----
                K_E: begin
                    k_out <= k_val;
                    k_we  <= 1'b1;
                    if (op_q == 4'd12) begin
                        // decode the rshr64s fields ONCE, exactly as cfg_p0
                        // is decoded at IDLE, then rerun the op-1 datapath
                        ps_r   <= (k_val > 0);
                        ps_big <= 1'b0;             // |k| <= 33 always
                        ps_c4  <= k_mag[5:2];
                        ps_f2  <= k_mag[1:0];
                        ps_rnd <= (k_val > 0) ? (64'd1 << (k_mag - 6'd1))
                                              : 64'd0;
                        op_q <= 4'd1;               // internal: SHIFT32 pass
                        st <= E_RD;
                    end else begin                  // op-8 probe: done
                        busy <= 1'b0;
                        done <= 1'b1;
                        st <= IDLE;
                    end
                end
                // ---------- AMAX32 compare/advance ----------
                AM_C: begin
                    if (am_first || (signed'(p_q[31:0]) > amax_val)) begin
                        amax_val <= signed'(p_q[31:0]);
                        amax_idx <= am_g;
                    end
                    am_first <= 1'b0;
                    am_g <= am_g + 1'b1;
                    if (i + 1'b1 == 13'(len_q)) begin
                        busy <= 1'b0;
                        done <= 1'b1;
                        st <= IDLE;
                    end else begin
                        i <= i + 1'b1;
                        a_addr <= cfg_srca + 14'((14'(i) + 14'd1) * 14'd2);
                        st <= E_RD;
                    end
                end
                E_MUL: if (wcnt == 2'd3) begin
                    p_q <= 64'(mul_p);
                    st <= SH_A;
                end
                // ---------- pipelined rshr64/rshr64s by e_* fields ----------
                SH_A: begin
                    p_sgn <= (p_q < 0);
                    p_abs <= (p_q < 0) ? unsigned'(-p_q) : unsigned'(p_q);
                    st <= SH_M;
                end
                SH_M: begin
                    p_mag <= p_abs + e_rnd;
                    // op-8 probe: p_abs is |pair(a)*b| PRE-shift (SH_A took
                    // the magnitude of the raw product), so the running max
                    // costs one compare on a state that already exists.
                    if (probe_q && (p_abs[47:0] > maxp)) maxp <= p_abs[47:0];
                    st <= SH_C;
                end
                SH_C: begin
                    p_c <= p_mag >> {e_c4, 2'b00};
                    l_c <= p_q <<< {e_c4, 2'b00};
                    st <= SH_F;
                end
                SH_F: begin
                    logic signed [63:0] fin;
                    logic [63:0] p_f;
                    p_f = p_c >> e_f2;
                    fin = e_big   ? 64'sd0
                        : e_right ? (p_sgn ? -signed'(p_f) : signed'(p_f))
                                  : (l_c <<< e_f2);
                    case (op_q)
                        4'd5, 4'd7: begin
                            x_silu <= 21'(fin);        // |a16|<<4 max: fits
                            st <= S_U;
                        end
                        4'd6: begin
                            if (fin > 64'sd1048575)       x_silu <= 21'sd1048575;
                            else if (fin < -64'sd1048576) x_silu <= -21'sd1048576;
                            else                          x_silu <= 21'(fin);
                            st <= S_U;
                        end
                        4'd15: begin                   // DYNQ8: clamp +-127
                            res <= (fin > 64'sd127)  ? 64'sd127
                                 : (fin < -64'sd127) ? -64'sd127 : fin;
                            st <= WR;
                        end
                        default: begin                 // 1, 9, 2, 3, 8
                            res <= fin;
                            st <= WR;
                        end
                    endcase
                end
                // ---------- silu/sigmoid (PWL) ----------
                S_U: begin
                    logic signed [20:0] xc;
                    if (x_silu > 21'sd65535)        xc = 21'sd65535;
                    else if (x_silu < -21'sd65536)  xc = -21'sd65536;
                    else                            xc = x_silu;
                    u_q <= 17'(18'(xc + 21'sd65536));
                    st <= S_ROM;
                end
                S_ROM: st <= S_INT;
                S_INT: begin
                    logic [16:0] a17, b17;
                    logic [31:0] pq;
                    pq = sg_rom[u_q[16:9]];
                    a17 = {1'b0, pq[15:0]};
                    b17 = {1'b0, pq[31:16]};
                    sig_q <= 16'(a17 + 17'((28'(17'(b17 - a17))
                             * 28'({19'b0, u_q[8:0]}) + 28'd256) >> 9));
                    st <= S_MUL;
                    wcnt <= '0;
                end
                S_MUL: begin
                    mul_a <= 33'(x_silu);
                    mul_b <= {17'b0, sig_q};
                    if (op_q == 4'd7) begin            // sigmoid only
                        res <= 64'({48'b0, sig_q});
                        st <= WR;
                    end else if (wcnt == 2'd3) begin
                        res <= rshr64(64'(38'(mul_p)), 15);
                        st <= WR;
                    end
                end
                // ---------- write ----------
                WR: begin
                    if (op_q == 4'd9) begin
                        logic signed [63:0] r;
                        r = res;
                        if (r > 64'sd2147483647)  r = 64'sd2147483647;
                        if (r < -64'sd2147483648) r = -64'sd2147483648;
                        res <= r;
                        w_addr <= cfg_dst + 14'(14'(i) * 14'd2);
                        w_data <= signed'(r[15:0]);
                        w_en <= 1'b1;
                        st <= WR2;
                    end else begin
                        w_addr <= cfg_dst + 14'(i);
                        w_data <= clip16(res);
                        w_en <= 1'b1;
                        if (i + 1'b1 == 13'(len_q)) begin
                            if (probe_q) begin      // op-8 probe: latch k_a
                                st <= K_E;
                            end else begin
                                busy <= 1'b0;
                                done <= 1'b1;
                                st <= IDLE;
                            end
                        end else begin
                            i <= i + 1'b1;
                            a_addr <= pair_op ? (cfg_srca + 14'((14'(i) + 14'd1) * 14'd2))
                                              : (cfg_srca + 14'(i) + 14'd1);
                            b_addr <= cfg_srcb + 14'(i) + 14'd1;
                            st <= E_RD;
                        end
                    end
                end
                WR2: begin
                    w_addr <= w_addr + 14'd1;
                    w_data <= signed'(res[31:16]);
                    w_en <= 1'b1;
                    if (i + 1'b1 == 13'(len_q)) begin
                        busy <= 1'b0;
                        done <= 1'b1;
                        st <= IDLE;
                    end else begin
                        i <= i + 1'b1;
                        a_addr <= cfg_srca + 14'((14'(i) + 14'd1) * 14'd2);
                        b_addr <= cfg_srcb + 14'(i) + 14'd1;
                        st <= E_RD;
                    end
                end
                default: st <= IDLE;
            endcase
        end
    end

    assign maxp_out = maxp;

endmodule

`default_nettype wire
