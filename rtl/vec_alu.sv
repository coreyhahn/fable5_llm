// vec_alu: vector glue math over the external scratchpad ports — bit-exact
// mirrors of layer_fixed.py call sites.  Matvec/attn/dn 32-bit values live
// in scratch as {lo,hi} int16 pairs (little-endian words).
//
// RUNG 2 (docs/RUNG2_SPEC.md): the per-element FSM walk (E_RD..WR, ~10.8
// cyc/elem) is now an INITIATION-INTERVAL-1 element pipeline.  The stage
// decomposition is unchanged -- the old states became pipe stages -- so the
// arithmetic is bit-identical; only the control is different.  A single
// lane, always: AMAX32 first-occurrence-wins and the DYNQ8/DYNQ16/probe
// reductions are loop-carried compare+select recurrences that need
// arrival order == index order (see docs/RUNG1B gate).
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
//                        RUNG 4 S5: every compared element also leaves on
//                        the registered topk_bun export (see the port).
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
//
// ======================================================================
// PIPELINE MAP (one element per II cycles, in index order, never stalls)
//
//   t_ad  a_addr/b_addr hold the element's LAST address
//   t_rd  a_q/b_q on the scratch DOUT bus
//   t_cp  CAPTURE regs cp_a16/cp_b16/cp_v32  <- the BRAM-DOUT cut
//   t_ex  EX: operand select; reductions (DYNQ8 maxabs / AMAX32 /
//         DYNQ16 mx32) close HERE, one comparator, II cycles
//   t_m0/t_m1   multiplier site 1 (ops 2/3/8): mul1_p0 -> mul1_p
//   t_sa/t_sm/t_sc/t_sf   rshr64/rshr64s split over SH_A/SH_M/SH_C/SH_F
//         (op-8 probe maxp compare rides t_sm, on the pre-shift |product|)
//   t_su  silu/sigmoid input clip + PWL index
//   t_rm  REGISTERED-read sigmoid ROM
//   t_n1/t_n2/t_n3  PWL interpolation split over three registered stages
//   t_a2/t_q0/t_q1  multiplier site 2 (ops 5/6): mul2_p0 -> mul2_p
//   t_rs  r_res -- the single pre-write register every path funnels into
//   (+1)  w_addr/w_data/w_en
//
// II: 1 for ops 0,1,2,3,4,5,6,7,10,12,15 (and the undecoded 11/13/14);
//     2 for op 8 (3 words/elem over 2 read ports) and op 9 (2 words/elem
//     out of 1 write port).  Pair ops whose srcb is unused (1/6/9/10/12)
//     fetch lo via port a AND hi via port b in the same cycle.
// Two-pass ops keep their per-vector bubbles: the pipe FULLY DRAINS
// before Q_E (DYNQ8, iterative e search) / K_E (block-float exponent).
// ======================================================================

`timescale 1ns/1ps
`default_nettype none

module vec_alu #(
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

    // ---- rung 4 S5: TOPK-32 export bundle (docs/RUNG4_SPEC.md) --------
    // ONE registered 51-bit word, sampled AT the AMAX32 compare site:
    //   [50]    we   = t_cp[0] && op_q == 10  (this element is being
    //                  compared into the running argmax THIS cycle)
    //   [49:18] val  = cp_v32   (the same int32 the comparator sees)
    //   [17:0]  idx  = am_g     (its GLOBAL index, pre-increment)
    // Registered here so the consumer (layer_topk32) starts from a
    // flip-flop: nothing combinational may hang off the AMAX compare.
    output logic [50:0]        topk_bun,

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

    // ==================================================================
    // per-command latched configuration (contract: everything is sampled
    // on the 1-cycle `start` pulse; cfg_* may change afterwards)
    // ==================================================================
    logic [3:0]         op_q;     // internal ops 15 (DYNQ8 pass 2) / 1 (DYNQ16 pass 2)
    logic [11:0]        len_q;
    logic signed [16:0] p0_q;
    logic [13:0]        srca_q, dst_q;   // srcb never survives pass 1
    logic [13:0]        park_q;   // read-port parking address during drain
    logic               probe_q;  // op-8 probe mode
    logic               kclamp_q; // clamp k at 0 (cfg_p0[1] / attn semantics)

    typedef enum logic [1:0] {C_IDLE, C_RUN, C_QE, C_KE} ctl_e;
    ctl_e st;

    // ---- per-command op classes (op_q is constant for a whole pass, so
    // every mux below is effectively static during the element loop) ----
    wire op_pr2  = (op_q == 4'd1) || (op_q == 4'd6) || (op_q == 4'd9)
                || (op_q == 4'd10) || (op_q == 4'd12);   // pair via a+b, II=1
    wire op_e32  = (op_q == 4'd8);                        // pair via a, II=2
    wire op_scn  = (op_q == 4'd0) || (op_q == 4'd10) || (op_q == 4'd12);
    wire op_ml1  = (op_q == 4'd2) || (op_q == 4'd3) || (op_q == 4'd8);
    wire op_shp  = (op_q == 4'd1) || (op_q == 4'd5) || (op_q == 4'd6)
                || (op_q == 4'd7) || (op_q == 4'd9) || (op_q == 4'd15);
    wire op_sil  = (op_q == 4'd5) || (op_q == 4'd6) || (op_q == 4'd7);
    wire op_sml  = (op_q == 4'd5) || (op_q == 4'd6);
    wire op_sgm  = (op_q == 4'd7);
    wire op_w2   = (op_q == 4'd9);
    wire op_add  = (op_q == 4'd4) || (op_q == 4'd11) || (op_q == 4'd13)
                || (op_q == 4'd14);       // EX -> pre-write directly
    wire op_str2 = op_pr2 || op_e32;      // port-a stride 2

    // ==================================================================
    // address generator: one element per II cycles, index order
    // ==================================================================
    logic [13:0] aa_r, ba_r;   // next port-a / port-b address to issue
    logic [13:0] wa_r;         // next write address
    logic [12:0] ag_i;         // element index being issued
    logic        ag_run;       // still issuing
    logic        ag_ph;        // op8: 2nd address phase / op9: II=2 gap
    wire         ag_last = ((ag_i + 13'd1) == 13'(len_q));

    // ==================================================================
    // pipeline tokens: [0] = valid, [1] = last element of the pass
    // ==================================================================
    logic [1:0] t_ad, t_rd, t_cp, t_ex, t_m0, t_m1,
                t_sa, t_sm, t_sc, t_sf,
                t_su, t_rm, t_n1, t_n2, t_n3, t_a2, t_q0, t_q1, t_rs;

    // capture stage (the BRAM-DOUT -> arithmetic cut)
    logic signed [15:0] pre_lo;             // op-8 lo word, 1 cycle ahead
    logic signed [15:0] cp_a16, cp_b16;
    logic signed [31:0] cp_v32;

    // EX stage
    logic signed [63:0] x_p;

    // multiplier site 1 (E_MUL position: ops 2/3/8)
    logic signed [32:0] mul_a, mul_b;
    /* verilator lint_off UNUSEDSIGNAL */
    logic signed [65:0] mul1_p0, mul1_p;
    /* verilator lint_on UNUSEDSIGNAL */
    // multiplier site 2 (S_MUL position: ops 5/6)
    logic signed [32:0] mul2_a, mul2_b;
    /* verilator lint_off UNUSEDSIGNAL */
    logic signed [65:0] mul2_p0, mul2_p;
    /* verilator lint_on UNUSEDSIGNAL */

    // rshr64 / rshr64s stages
    logic               sa_sgn, sm_sgn, sc_sgn;
    logic        [63:0] sa_abs, sm_mag, sc_pc;
    logic signed [63:0] sa_lin, sm_lin, sc_lc;

    // silu / sigmoid stages
    logic signed [20:0] x_sil, xs_d0, xs_d1, xs_d2, xs_d3, xs_d4;
    logic        [16:0] u_q;
    logic        [31:0] rom_d;
    logic        [8:0]  rom_f;
    logic        [16:0] i1_a, i1_d;
    logic        [8:0]  i1_f;
    /* verilator lint_off UNUSEDSIGNAL */
    logic        [27:0] i2_pp;      // only [25:9] survive the >>9 / 17' cast
    /* verilator lint_on UNUSEDSIGNAL */
    logic        [16:0] i2_a;
    logic        [15:0] sig_q;

    // pre-write register: EVERY path funnels here (op 4/11/13/14 from EX,
    // ops 1/2/3/8/9/15 from SH_F, op 7 from the PWL, ops 5/6 from mul2)
    logic signed [63:0] r_res;
    logic signed [15:0] w2_dat;    // op 9 hi word
    logic               w2_pend, w2_lst;

    // reduction state
    logic        am_first;         // no element seen since fresh scan
    logic [17:0] am_g;             // global element index across chunks
    logic [15:0] maxabs;           // DYNQ8 pass-1 max|a|
    logic [3:0]  eq;               // DYNQ8 exponent search
    logic [31:0] mx32;             // DYNQ16 pass-1 running max |x|, UNSIGNED
    logic [47:0] maxp;             // op-8 probe running max |prod|, pre-shift

    // ---- shared exponent unit, evaluated ONCE per vector in C_KE ----
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

    // shifter input: multiplier product for ops 2/3/8, the EX operand
    // otherwise.  op_ml1 is a per-command constant -> a static mux.
    wire signed [63:0] sh_in  = op_ml1 ? 64'(mul1_p) : x_p;
    wire [1:0]         t_sain = op_ml1 ? t_m1 : (op_shp ? t_ex : 2'b00);

    always_ff @(posedge clk) begin
        if (!rstn) begin
            st       <= C_IDLE;
            busy     <= 1'b0;
            done     <= 1'b0;
            w_en     <= 1'b0;
            amax_idx <= '0;
            amax_val <= '0;
            am_first <= 1'b1;
            am_g     <= '0;
            k_out    <= '0;
            k_we     <= 1'b0;
            maxp     <= '0;
            topk_bun <= '0;
            probe_q  <= 1'b0;
            ag_run   <= 1'b0;
            ag_ph    <= 1'b0;
            w2_pend  <= 1'b0;
            {t_ad, t_rd, t_cp, t_ex, t_m0, t_m1}   <= '0;
            {t_sa, t_sm, t_sc, t_sf}               <= '0;
            {t_su, t_rm, t_n1, t_n2, t_n3}         <= '0;
            {t_a2, t_q0, t_q1, t_rs}               <= '0;
        end else begin
            done <= 1'b0;
            w_en <= 1'b0;
            k_we <= 1'b0;

            // ==========================================================
            // address generator (drives t_ad = "last address on the bus")
            // ==========================================================
            if (ag_run) begin
                if (op_e32) begin
                    // op 8: 3 words/elem -> pair over port a in 2 cycles,
                    // b16 held on port b for both.  II = 2.
                    a_addr <= aa_r;
                    aa_r   <= aa_r + 14'd1;
                    if (!ag_ph) begin
                        b_addr <= ba_r;
                        ag_ph  <= 1'b1;
                        t_ad   <= 2'b00;          // lo word: not the element yet
                    end else begin
                        ba_r  <= ba_r + 14'd1;
                        ag_ph <= 1'b0;
                        t_ad  <= {ag_last, 1'b1};
                        if (ag_last) ag_run <= 1'b0;
                        else         ag_i   <= ag_i + 13'd1;
                    end
                end else if (op_w2 && ag_ph) begin
                    ag_ph <= 1'b0;                // op 9: write-port bound gap
                    t_ad  <= 2'b00;
                end else begin
                    a_addr <= aa_r;
                    b_addr <= ba_r;
                    aa_r   <= aa_r + (op_str2 ? 14'd2 : 14'd1);
                    ba_r   <= ba_r + (op_pr2  ? 14'd2 : 14'd1);
                    ag_ph  <= op_w2;
                    t_ad   <= {ag_last, 1'b1};
                    if (ag_last) ag_run <= 1'b0;
                    else         ag_i   <= ag_i + 13'd1;
                end
            end else begin
                // park both read ports past the end of the write region so
                // the write-behind can never alias a live read address
                a_addr <= park_q;
                b_addr <= park_q;
                t_ad   <= 2'b00;
            end

            // ==========================================================
            // read -> capture (registers the BRAM DOUT before ANY arith)
            // ==========================================================
            t_rd   <= t_ad;
            pre_lo <= a_q;
            t_cp   <= t_rd;
            if (t_rd[0]) begin
                cp_a16 <= a_q;
                cp_b16 <= b_q;
                cp_v32 <= op_e32 ? signed'({unsigned'(a_q), unsigned'(pre_lo)})
                                 : signed'({unsigned'(b_q), unsigned'(a_q)});
            end

            // ==========================================================
            // EX stage: operand select + the loop-carried reductions
            // ==========================================================
            t_ex <= t_cp;
            if (t_cp[0]) begin
                case (op_q)
                    4'd15, 4'd5, 4'd7: x_p <= 64'(cp_a16);
                    4'd1, 4'd6, 4'd9:  x_p <= 64'(cp_v32);
                    4'd4: r_res <= 64'(cp_a16) + 64'(cp_b16);      // ADD
                    4'd2: begin mul_a <= 33'(cp_a16); mul_b <= 33'(p0_q);  end
                    4'd3: begin mul_a <= 33'(cp_a16); mul_b <= 33'(cp_b16); end
                    4'd8: begin mul_a <= 33'(cp_v32); mul_b <= 33'(cp_b16); end
                    4'd0: begin                                    // DYNQ8 scan
                        logic [15:0] av;
                        av = (cp_a16 < 0) ? 16'(-cp_a16) : 16'(cp_a16);
                        if (av > maxabs) maxabs <= av;
                    end
                    4'd10: begin                                   // AMAX32
                        if (am_first || (cp_v32 > amax_val)) begin
                            amax_val <= cp_v32;
                            amax_idx <= am_g;
                        end
                        am_first <= 1'b0;
                        am_g     <= am_g + 18'd1;
                    end
                    4'd12: begin                                   // DYNQ16 scan
                        logic signed [32:0] vv;
                        /* verilator lint_off UNUSEDSIGNAL */
                        logic [32:0] av;   // [32] always 0: |x| <= 2^31
                        /* verilator lint_on UNUSEDSIGNAL */
                        // 33 bits on purpose: |-2^31| = 2^31 does NOT fit a
                        // signed 32-bit register (the one width trap here)
                        vv = 33'(cp_v32);
                        av = (vv < 0) ? unsigned'(-vv) : unsigned'(vv);
                        if (av[31:0] > mx32) mx32 <= av[31:0];
                    end
                    default: ;   // 11/13/14: undecoded fall-through
                endcase
            end

            // ---- rung 4 S5: TOPK-32 export (the ONLY thing this file
            // gains).  Exactly the operands the AMAX32 arm above uses,
            // in the same cycle, into one register.  cp_v32/am_g are the
            // pre-edge values, i.e. bit-for-bit what the comparator saw;
            // am_g is the element's own index because its increment is
            // non-blocking.  we is 0 for every other op and every idle
            // cycle, so the export is inert unless op 10 is running.
            topk_bun <= {(t_cp[0] && (op_q == 4'd10)),
                         unsigned'(cp_v32), am_g};

            // ---- multiplier site 1 (E_MUL position) ----
            t_m0    <= op_ml1 ? t_ex : 2'b00;
            t_m1    <= t_m0;
            mul1_p0 <= mul_a * mul_b;
            mul1_p  <= mul1_p0;

            // ==========================================================
            // rshr64 / rshr64s: SH_A / SH_M / SH_C / SH_F
            // ==========================================================
            t_sa <= t_sain;
            if (t_sain[0]) begin
                sa_sgn <= (sh_in < 0);
                sa_abs <= (sh_in < 0) ? unsigned'(-sh_in) : unsigned'(sh_in);
                sa_lin <= sh_in;
            end

            t_sm <= t_sa;
            if (t_sa[0]) begin
                sm_mag <= sa_abs + e_rnd;
                sm_sgn <= sa_sgn;
                sm_lin <= sa_lin;
                // op-8 probe: sa_abs is |pair(a)*b| PRE-shift (SH_A took the
                // magnitude of the raw product), so the running max costs one
                // compare on a state that already exists.
                if (probe_q && (sa_abs[47:0] > maxp)) maxp <= sa_abs[47:0];
            end

            t_sc <= t_sm;
            if (t_sm[0]) begin
                sc_pc  <= sm_mag >> {e_c4, 2'b00};
                sc_lc  <= sm_lin <<< {e_c4, 2'b00};
                sc_sgn <= sm_sgn;
            end

            t_sf <= op_sil ? t_sc : 2'b00;
            if (t_sc[0]) begin
                logic signed [63:0] fin;
                logic [63:0] p_f;
                p_f = sc_pc >> e_f2;
                fin = e_big   ? 64'sd0
                    : e_right ? (sc_sgn ? -signed'(p_f) : signed'(p_f))
                              : (sc_lc <<< e_f2);
                case (op_q)
                    4'd5, 4'd7: x_sil <= 21'(fin);
                    4'd6: begin
                        if (fin > 64'sd1048575)       x_sil <= 21'sd1048575;
                        else if (fin < -64'sd1048576) x_sil <= -21'sd1048576;
                        else                          x_sil <= 21'(fin);
                    end
                    4'd15: begin                   // DYNQ8: clamp +-127
                        r_res <= (fin > 64'sd127)  ? 64'sd127
                               : (fin < -64'sd127) ? -64'sd127 : fin;
                    end
                    default: r_res <= fin;         // 1, 9, 2, 3, 8
                endcase
            end

            // ==========================================================
            // silu / sigmoid: input clip, REGISTERED ROM read, PWL over
            // three registered stages, then multiplier site 2
            // ==========================================================
            t_su <= t_sf;
            if (t_sf[0]) begin
                logic signed [20:0] xc;
                if (x_sil > 21'sd65535)        xc = 21'sd65535;
                else if (x_sil < -21'sd65536)  xc = -21'sd65536;
                else                           xc = x_sil;
                u_q   <= 17'(18'(xc + 21'sd65536));
                xs_d0 <= x_sil;
            end

            t_rm <= t_su;
            if (t_su[0]) begin
                rom_d <= sg_rom[u_q[16:9]];
                rom_f <= u_q[8:0];
                xs_d1 <= xs_d0;
            end

            t_n1 <= t_rm;
            if (t_rm[0]) begin
                logic [16:0] a17, b17;
                a17   = {1'b0, rom_d[15:0]};
                b17   = {1'b0, rom_d[31:16]};
                i1_a  <= a17;
                i1_d  <= 17'(b17 - a17);
                i1_f  <= rom_f;
                xs_d2 <= xs_d1;
            end

            t_n2 <= t_n1;
            if (t_n1[0]) begin
                i2_pp <= 28'(i1_d) * 28'({19'b0, i1_f}) + 28'd256;
                i2_a  <= i1_a;
                xs_d3 <= xs_d2;
            end

            t_n3 <= op_sml ? t_n2 : 2'b00;
            if (t_n2[0]) begin
                logic [15:0] sig_v;
                sig_v = 16'(i2_a + 17'(i2_pp >> 9));
                sig_q <= sig_v;
                xs_d4 <= xs_d3;
                if (op_sgm) r_res <= 64'({48'b0, sig_v});   // SIGM16: Q15 out
            end

            t_a2 <= t_n3;
            if (t_n3[0]) begin
                mul2_a <= 33'(xs_d4);
                mul2_b <= {17'b0, sig_q};
            end
            t_q0    <= t_a2;
            t_q1    <= t_q0;
            mul2_p0 <= mul2_a * mul2_b;
            mul2_p  <= mul2_p0;
            if (t_q1[0]) r_res <= rshr64(64'(38'(mul2_p)), 15);

            // ==========================================================
            // pre-write token: whichever path this op uses
            // ==========================================================
            t_rs <= op_add ? t_cp
                  : op_sgm ? t_n2
                  : op_sml ? t_q1
                  : op_scn ? 2'b00
                           : t_sc;

            // ==========================================================
            // write stage (+ op-9 second word) and end-of-pass retire
            // ==========================================================
            if (t_rs[0]) begin
                w_addr <= wa_r;
                wa_r   <= wa_r + 14'd1;
                w_en   <= 1'b1;
                if (op_w2) begin                   // SHIFT32W: clip32, lo then hi
                    logic signed [63:0] r;
                    r = r_res;
                    if (r > 64'sd2147483647)  r = 64'sd2147483647;
                    if (r < -64'sd2147483648) r = -64'sd2147483648;
                    w_data  <= signed'(r[15:0]);
                    w2_dat  <= signed'(r[31:16]);
                    w2_pend <= 1'b1;
                    w2_lst  <= t_rs[1];
                end else begin
                    w_data <= clip16(r_res);
                    if (t_rs[1]) begin
                        if (probe_q) st <= C_KE;   // op-8 probe: latch k_a
                        else begin
                            busy <= 1'b0;
                            done <= 1'b1;
                            st   <= C_IDLE;
                        end
                    end
                end
            end else if (w2_pend) begin
                w_addr  <= wa_r;
                wa_r    <= wa_r + 14'd1;
                w_data  <= w2_dat;
                w_en    <= 1'b1;
                w2_pend <= 1'b0;
                if (w2_lst) begin
                    busy <= 1'b0;
                    done <= 1'b1;
                    st   <= C_IDLE;
                end
            end

            // scan-only ops retire when the last element clears EX; nothing
            // is downstream of the compare, so the pipe is fully drained.
            if (t_cp[0] && t_cp[1] && op_scn) begin
                if (op_q == 4'd0)       st <= C_QE;
                else if (op_q == 4'd12) st <= C_KE;
                else begin
                    busy <= 1'b0;
                    done <= 1'b1;
                    st   <= C_IDLE;
                end
            end

            // ==========================================================
            // control
            // ==========================================================
            case (st)
                C_IDLE: if (start) begin
                    logic [5:0] amag;
                    logic signed [16:0] p0_e;
                    logic pr8, nw_pr2, nw_e32, nw_bb;
                    logic [13:0] fb, na, nb;
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
                    len_q  <= cfg_len;
                    op_q   <= cfg_op;
                    p0_q   <= cfg_p0;
                    srca_q <= cfg_srca;
                    dst_q  <= cfg_dst;
                    park_q <= cfg_dst + ((cfg_op == 4'd9) ? 14'({cfg_len, 1'b0})
                                                          : 14'(cfg_len));
                    maxabs <= '0;
                    eq     <= '0;
                    busy   <= 1'b1;
                    st     <= C_RUN;

                    // ---- issue element 0 (op 8 issues only its lo word) ----
                    nw_pr2 = (cfg_op == 4'd1) || (cfg_op == 4'd6)
                          || (cfg_op == 4'd9) || (cfg_op == 4'd10)
                          || (cfg_op == 4'd12);
                    nw_e32 = (cfg_op == 4'd8);
                    nw_bb  = (cfg_op == 4'd3) || (cfg_op == 4'd4);
                    if (nw_pr2) begin
                        fb = cfg_srca + 14'd1;
                        na = cfg_srca + 14'd2;  nb = cfg_srca + 14'd3;
                    end else if (nw_e32) begin
                        fb = cfg_srcb;
                        na = cfg_srca + 14'd1;  nb = cfg_srcb;
                    end else if (nw_bb) begin
                        fb = cfg_srcb;
                        na = cfg_srca + 14'd1;  nb = cfg_srcb + 14'd1;
                    end else begin              // ops 0/2/5/7/11/13/14: b unused
                        fb = cfg_srca;
                        na = cfg_srca + 14'd1;  nb = cfg_srca + 14'd1;
                    end
                    a_addr <= cfg_srca;
                    b_addr <= fb;
                    aa_r   <= na;
                    ba_r   <= nb;
                    wa_r   <= cfg_dst;
                    ag_ph  <= nw_e32 || (cfg_op == 4'd9);
                    ag_i   <= nw_e32 ? 13'd0 : 13'd1;
                    ag_run <= nw_e32 ? 1'b1 : (cfg_len != 12'd1);
                    t_ad   <= nw_e32 ? 2'b00 : {(cfg_len == 12'd1), 1'b1};

                    // a start pulse always begins with an empty pipe
                    {t_rd, t_cp, t_ex, t_m0, t_m1}  <= '0;
                    {t_sa, t_sm, t_sc, t_sf}        <= '0;
                    {t_su, t_rm, t_n1, t_n2, t_n3}  <= '0;
                    {t_a2, t_q0, t_q1, t_rs}        <= '0;
                    w2_pend <= 1'b0;
                end

                C_RUN: ;   // the pipeline above does the work

                // ---------- DYNQ8: minimal e with rshr(maxabs,e) <= 127 ----
                C_QE: begin
                    logic [15:0] r;
                    r = 16'((32'(maxabs) + (32'd1 << eq >> 1)) >> eq);
                    if (r > 16'd127) begin
                        eq <= eq + 4'd1;
                    end else begin
                        e_out <= eq;
                        q_c4x <= {2'b00, eq[3:2]};
                        q_f2  <= eq[1:0];
                        q_rnd <= (eq == 4'd0) ? 64'd0
                                              : 64'(64'd1 << (eq - 4'd1));
                        op_q  <= 4'd15;        // internal: quant write pass
                        // pass 2 is a stride-1, port-b-unused stream
                        a_addr <= srca_q;
                        b_addr <= srca_q;
                        aa_r   <= srca_q + 14'd1;
                        ba_r   <= srca_q + 14'd1;
                        wa_r   <= dst_q;
                        ag_i   <= 13'd1;
                        ag_ph  <= 1'b0;
                        ag_run <= (len_q != 12'd1);
                        t_ad   <= {(len_q == 12'd1), 1'b1};
                        st     <= C_RUN;
                    end
                end

                // ---------- block-float exponent (pass-1 exit / probe) ----
                C_KE: begin
                    k_out <= k_val;
                    k_we  <= 1'b1;
                    if (op_q == 4'd12) begin
                        // decode the rshr64s fields ONCE, exactly as cfg_p0
                        // is decoded at dispatch, then rerun the op-1 pipe
                        ps_r   <= (k_val > 0);
                        ps_big <= 1'b0;             // |k| <= 33 always
                        ps_c4  <= k_mag[5:2];
                        ps_f2  <= k_mag[1:0];
                        ps_rnd <= (k_val > 0) ? (64'd1 << (k_mag - 6'd1))
                                              : 64'd0;
                        op_q   <= 4'd1;             // internal: SHIFT32 pass
                        a_addr <= srca_q;
                        b_addr <= srca_q + 14'd1;
                        aa_r   <= srca_q + 14'd2;
                        ba_r   <= srca_q + 14'd3;
                        wa_r   <= dst_q;
                        ag_i   <= 13'd1;
                        ag_ph  <= 1'b0;
                        ag_run <= (len_q != 12'd1);
                        t_ad   <= {(len_q == 12'd1), 1'b1};
                        st     <= C_RUN;
                    end else begin                  // op-8 probe: done
                        busy <= 1'b0;
                        done <= 1'b1;
                        st   <= C_IDLE;
                    end
                end
                default: st <= C_IDLE;
            endcase
        end
    end

    assign maxp_out = maxp;

    // ==================================================================
    // Overlap invariant (docs/RUNG2_SPEC.md): the pipelined write trails
    // the read cursor, so a write must NEVER alias a live read address in
    // the same cycle -- that is the only way the scratch's read-first
    // collision mode could become observable.  The generator-call-site
    // audit says this can not happen on legal streams; assert it.
    // ==================================================================
`ifndef SYNTHESIS
    always_ff @(posedge clk) begin
        if (rstn && w_en) begin
            if (w_addr == a_addr)
                $fatal(1, "vec_alu: w/a scratch port collision @ %0h (op %0d)",
                       w_addr, op_q);
            if (w_addr == b_addr)
                $fatal(1, "vec_alu: w/b scratch port collision @ %0h (op %0d)",
                       w_addr, op_q);
        end
    end
`endif

endmodule

`default_nettype wire
