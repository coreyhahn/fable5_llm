// vecnorm_unit: RMSNorm / L2-norm — bit-exact mirror of layer_fixed.py
// rmsnorm_fx (modes 0/1) and l2norm_fx (mode 2).
//
//   mode 0: y = clip16(rshr( rshr(x*r, 30-e) * (w + 2^14), 14))   (1+w)
//   mode 1: same with plain w
//   mode 2: y = clip16(rshr(x*r, in_f + 30 - e - out_f))          no weight
// where (r,e) = rsqrt_q(sum(x^2), 2*in_f + (mode!=2 ? n_log2 : 0)).
//
// Structure: FILL (1 elem/cycle, accumulates sum of squares) -> RSQ (needs
// the whole sum: inherently two-phase) -> OUT, a fully pipelined II=1
// element loop (rung 2).  N = 2^n_log2 <= 1024.
//
// ---- OUT pipeline (one element issued per cycle) ---------------------
// Slot numbering: element i is in slot k during the cycle T+k, where T is
// the cycle its address is presented to xbuf/wbuf.  `pv[k]` is the valid
// bit of slot k.
//
//   0  address (oidx) -> xbuf/wbuf
//   1  xq/wq        BRAM dout registers
//   2  xc/wc        CAPTURE stage (no arithmetic on a BRAM dout cone)
//   3  m1a/m1b      multiplier operand registers  (w enters wdl[0..7])
//   4  m1p0         DSP MREG                       \  O_M1: x*rs_r (modes
//   5  m1p          DSP PREG                       /  0/1/2) or x*scale (eps)
//   6  p_raw        product capture           <--- EPS-NORM tail tap
//   7  p_sgn/p_abs  rshr64s: sign + magnitude       (O_ABS)
//   8  p_mag        + round constant               (O_MAG)
//   9  p_c/l_c      coarse shift (multiples of 4)  (O_SHC)
//  10  ssh          fine shift + sign restore <--- mode 2 tail tap (O_SHV)
//  11  m2a/m2b      second multiplier operands     (O_SH: ssh*(w+bias))
//  12  m2p0         DSP MREG                       \  O_M2 — the SECOND
//  13  m2p          DSP PREG                       /  multiplier instance,
//                                                     so O_M1 and O_M2
//                                                     overlap in the pipe
//  13  tail         clip16(rshr(m2p,14))      <--- mode 0/1 tail tap
//
// The three tails are mode-selected (a mode is constant for a whole
// vector), so the tail register m_data/m_valid is loaded from the tap that
// belongs to the running mode; the other taps are don't-care.
// Backpressure: `pipe_adv` (== !(m_valid && !m_ready)) is the clock enable
// of EVERY pipeline register, including the BRAM dout registers and the two
// DSP MREG/PREG pairs, so m_ready low freezes the whole pipe in place — no
// element can be lost and no skid buffer is needed.  s_valid gaps are
// absorbed by FILL, which is a plain accept-when-valid state.
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

module vecnorm_unit #(
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

    typedef enum logic [3:0] {IDLE, FILL,
                              EPSC, EPSC2, EPSC3, EPSC4, EPSC5,
                              RSQ, RSQW,
                              O_PREP, O_SC, O_SC2, O_SC3, O_SC4,
                              O_RUN} st_e;
    st_e st;

    // ---- EPS-NORM constants + state ----
    localparam logic [63:0] EPS_M = 64'd1099512;   // round(1e-6 * 2^40)
    localparam int          EPS_Q = 40;
    wire eps_on = cfg_eps && (cfg_mode == 2'd2);
    // [31:10] is pure sign extension: the term is in [-69, +102]
    /* verilator lint_off UNUSEDSIGNAL */
    int  eps_sh;                    // (EPS_Q - 2*in_f - n_log2) + 2*k
    /* verilator lint_on UNUSEDSIGNAL */
    always_comb eps_sh = EPS_Q - 2 * int'(cfg_inf) - int'(cfg_nlog2)
                         + 2 * int'(cfg_k);
    // E = rshr64(EPS_M, eps_sh).  ONE 64-bit shifter per vector was still a
    // top-10 violated path (cfg -> eps_sh adder -> compare -> 64b variable
    // shift -> reg), so it is now split over five registered PER-VECTOR
    // stages, each holding at most one shifter with registered operands:
    //   EPSC  : register the shift amount        (the int adder)
    //   EPSC2 : decode left/big/|amount|
    //   EPSC3 : left result, rounded right numerator (parallel, reg->reg)
    //   EPSC4 : right shift
    //   EPSC5 : select
    // Bit-identical to the former single-cycle EPSC; five cycles per vector.
    logic signed [9:0] ee_sh;       // registered eps_sh  (range -69..+102)
    logic        ee_left, ee_big;   // sh<=0 (left) / |sh|>=64 (result 0)
    logic [5:0]  ee_amt;            // capped shift magnitude
    logic [63:0] ee_sum;            // EPS_M + (1 << (amt-1))
    logic [63:0] ee_lsh, ee_rsh;    // left / right shifted results
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
    logic [10:0] oidx;              // OUT issue cursor (addresses presented)
    logic [10:0] ecnt;              // OUT retire cursor (elements handshaked)

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

    int sh1;

    // rshr64s(v, sh1) decomposed: abs -> +round -> coarse shift -> fine
    // shift + sign restore. Per-vector shift fields registered at O_PREP
    // so the element loop never sees a full variable shifter in one stage.
    logic        sh_r;             // sh1 > 0 (rounding right shift)
    logic        sh_big;           // |sh1| >= 64: result is 0 either way
    logic [3:0]  sh_c4;            // |sh1| coarse (multiples of 4)
    logic [1:0]  sh_f2;            // |sh1| fine
    logic [63:0] rnd_q;            // 1 << (sh1-1), right-shift round const

    // ==================================================================
    // OUT element pipeline (see the header for the slot map)
    // ==================================================================
    logic [13:1] pv;                       // per-slot valid bits
    logic signed [15:0] xq, xc;            // xbuf dout + capture
    logic signed [15:0] wq, wc;            // wbuf dout + capture
    logic signed [15:0] wdl [8];           // w delayed to the O_M2 slot
    logic signed [32:0] m1a, m1b;          // O_M1 operand registers
    logic signed [32:0] m2a, m2b;          // O_M2 operand registers
    /* verilator lint_off UNUSEDSIGNAL */
    logic signed [65:0] m1p0, m1p;         // [65:64] unused: operands <= 48b
    logic signed [65:0] m2p0, m2p;
    /* verilator lint_on UNUSEDSIGNAL */
    logic signed [63:0] p_raw, pr1, pr2;   // product + its 2-slot delay
    logic        p_sgn, sgn1, sgn2;        // its sign + 2-slot delay
    logic [63:0] p_abs, p_mag, p_c;
    logic signed [63:0] l_c, ssh;

    assign s_ready = (st == FILL);

    // clock enable of the whole OUT pipeline: freeze in place while the
    // consumer holds m_ready low (nothing advances, nothing is lost)
    wire pipe_adv = (st == O_RUN) && (!m_valid || m_ready);
    wire issue    = (oidx != n_total);      // still addresses to present
    // mode-selected tail tap (mode/eps are constant for a whole vector)
    wire pv_out = eps_on             ? pv[6]
                : (cfg_mode == 2'd2) ? pv[10]
                                     : pv[13];
    wire signed [15:0] m_data_n =
                  eps_on             ? clip16(rshr64(p_raw, 15))
                : (cfg_mode == 2'd2) ? clip16(ssh)
                                     : clip16(rshr64(64'(m2p), 14));

    // ---- pipeline datapath: pure registers, advanced by pipe_adv ----
    always_ff @(posedge clk) if (pipe_adv) begin
        logic [63:0] p_f;
        // slot 0 -> 1 : BRAM dout registers
        xq <= xbuf[oidx[9:0]];
        wq <= wbuf[oidx[9:0]];
        // slot 1 -> 2 : capture stage (BRAM dout never feeds arithmetic)
        xc <= xq;
        wc <= wq;
        // slot 2 -> 3 : O_M1 operand registers + the w delay line
        m1a <= 33'(xc);
        m1b <= eps_on ? 33'({17'b0, scale_q}) : 33'(rs_r);
        wdl[0] <= wc;
        for (int i = 1; i < 8; i++) wdl[i] <= wdl[i-1];
        // slot 3 -> 5 : O_M1 DSP (MREG, PREG)
        m1p0 <= m1a * m1b;
        m1p  <= m1p0;
        // slot 5 -> 6 : product capture
        p_raw <= 64'(m1p);
        // slot 6 -> 7 : O_ABS
        p_sgn <= (p_raw < 0);
        p_abs <= (p_raw < 0) ? unsigned'(-p_raw) : unsigned'(p_raw);
        pr1   <= p_raw;
        // slot 7 -> 8 : O_MAG
        p_mag <= p_abs + rnd_q;
        pr2   <= pr1;
        sgn1  <= p_sgn;
        // slot 8 -> 9 : O_SHC (coarse shift)
        p_c  <= p_mag >> {sh_c4, 2'b00};
        l_c  <= pr2 <<< {sh_c4, 2'b00};
        sgn2 <= sgn1;
        // slot 9 -> 10 : O_SHV (fine shift + sign restore)
        p_f = p_c >> sh_f2;
        ssh <= sh_big ? 64'sd0
             : sh_r   ? (sgn2 ? -signed'(p_f) : signed'(p_f))
                      : (l_c <<< sh_f2);
        // slot 10 -> 11 : O_SH — O_M2 operand registers.
        // 33-bit intermediate: spec constraint, mirrored by the clip in
        // layer_fixed.rmsnorm_fx
        m2a <= 33'(ssh);
        m2b <= 33'(32'(wdl[7])
               + ((cfg_mode == 2'd0) ? 33'sd16384 : 33'sd0));
        // slot 11 -> 13 : O_M2 DSP (MREG, PREG)
        m2p0 <= m2a * m2b;
        m2p  <= m2p0;
    end

    always_ff @(posedge clk) begin
        if (!rstn) begin
            st <= IDLE;
            busy <= 1'b0;
            m_valid <= 1'b0;
            pv <= '0;
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
                // E = rshr64(EPS_M, eps_sh) over five per-vector stages.
                // EPS_M > 0 so the round-half-away reduces to +(1<<(sh-1)).
                EPSC: begin
                    ee_sh <= 10'(eps_sh);
                    st <= EPSC2;
                end
                EPSC2: begin
                    logic signed [9:0] amag;
                    amag = (ee_sh < 0) ? -ee_sh : ee_sh;
                    ee_left <= (ee_sh <= 0);
                    ee_big  <= (amag >= 64);
                    ee_amt  <= (amag > 63) ? 6'd63 : 6'(amag);
                    st <= EPSC3;
                end
                EPSC3: begin
                    // left result and the rounded right numerator; the
                    // (amt-1) wrap in the amt==0 case only ever feeds the
                    // right leg, which ee_left then discards.
                    ee_lsh <= EPS_M << ee_amt;
                    ee_sum <= EPS_M + (64'd1 << (ee_amt - 6'd1));
                    st <= EPSC4;
                end
                EPSC4: begin
                    ee_rsh <= ee_sum >> ee_amt;
                    st <= EPSC5;
                end
                EPSC5: begin
                    eps_e <= ee_big ? 64'd0 : (ee_left ? ee_lsh : ee_rsh);
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
                        ecnt <= '0;
                        pv   <= '0;
                        st <= eps_on ? O_SC : O_PREP;
                    end
                end
                // scale = clip(rshr64(rs_r, sh1), 0, 65535).  rs_r is Q30 in
                // (2^29, 2^30], so any LEFT shift already exceeds the clamp;
                // capping the shift at 32 keeps the 64-bit intermediate from
                // wrapping without changing the clamped result.
                // Pipelined over four cycles (sh1, rs_r constant for the
                // vector).  The decode of sh1 -> (left/big, capped amount,
                // round const) is done ONCE here, off the per-shift path.
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
                    st <= O_RUN;
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
                    st <= O_RUN;
                end
                // II=1 element loop: one address issued per cycle, one
                // result retired per cycle, the whole pipe frozen by
                // pipe_adv whenever the consumer stalls.
                O_RUN: begin
                    if (pipe_adv) begin
                        pv <= {pv[12:1], issue};
                        if (issue) oidx <= oidx + 1'b1;
                        m_valid <= pv_out;
                        m_data  <= m_data_n;
                    end
                    if (m_valid && m_ready) begin
                        ecnt <= ecnt + 1'b1;
                        if (ecnt + 1'b1 == n_total) begin
                            busy <= 1'b0;
                            st <= IDLE;
                        end
                    end
                end
                default: st <= IDLE;
            endcase
        end
    end

endmodule

`default_nettype wire
