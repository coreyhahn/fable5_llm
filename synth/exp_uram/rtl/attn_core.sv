// ============================================================
// EXPERIMENT COPY — NOT MIGRATION RTL.  Track P (URAM placement
// experiment), qwen-next de-risking, docs/QWEN35_NEXT_FEASIBILITY.md
// section 6 item 3 / section 8 D3.  Source of truth stays rtl/attn_core.sv;
// main/rtl is UNTOUCHED by this directory.  These files exist only to
// answer "does the 4B/9B-widened layer_chan synthesize to 928 URAM,
// and does it PLACE on the VU9P".  No testbench campaign was run
// against them and they are NOT functionally verified.
// Copied from rtl/attn_core.sv @ git aa9c1efa
// ============================================================
// attn_core: softmax attention over a quantized KV memory for ONE q-head —
// bit-exact mirror of the inner loop of layer_fixed.attn_decode_fx:
//
//   per t: dot   = sum_d qn[d]*k8[t][d]
//          s_    = rshr(dot * SC_Q15, 15)        SC = round(2^15/sqrt(HD))
//          sc[t] = shift s_ by (QKV_F - ke[t] - 16)   (Q16, either direction)
//   mx = max(sc); es[t] = exp_neg(min(sc[t]-mx,0))    (Q30, exp2 PWL ROM)
//   (r,re) = recip(sum es, P=30)
//   p[t] = clip(rshr(es[t]*r, 30-re+15), 0, 2^15)
//   acc[v] += rshr(p[t]*v8[t][v], 15 - ve[t] - QKV_F)
//
// KV memory external: addr {bank,t} bank0=K bank1=V, 2048b row + signed
// 8b exponent, 2-cycle latency. T <= 512.

`timescale 1ns/1ps
`default_nettype none

module attn_core #(
    parameter int HD = 256,
    parameter string EXP2_ROM = "exp2_pair_rom.hex",
    parameter string RECIP_ROM = "recip_rom.hex"
) (
    input  wire                clk,
    input  wire                rstn,
    input  wire                start,
    output logic               busy,
    output logic               done,

    input  wire [9:0]          cfg_t,        // cache length T

    // q preload (Q8 int16)
    input  wire                q_we,
    input  wire [7:0]          q_waddr,
    input  wire signed [15:0]  q_wdata,

    // KV memory
    output logic [9:0]         kv_addr,      // {bank, t[8:0]}
    input  wire [HD*8-1:0]     kv_data,      // valid 1 cycle after addr
    input  wire signed [7:0]   kv_exp,

    // result stream: HD x 32-bit
    output logic               m_valid,
    input  wire                m_ready,
    output logic signed [31:0] m_data,
    output logic [7:0]         m_idx
);
    import fx_pkg::*;

    localparam logic signed [16:0] SC_Q15 = 17'sd2048;   // 2^15/16

    // input-registered q preload: keeps the scratch-BRAM-to-lane-array
    // haul off the write decode (the source register lands near the array)
    logic               qwe_q;
    logic [7:0]         qwaddr_q;
    logic signed [15:0] qwdata_q;
    logic signed [15:0] qv [HD];
    always_ff @(posedge clk) begin
        qwe_q    <= q_we;
        qwaddr_q <= q_waddr;
        qwdata_q <= q_wdata;
        if (qwe_q) qv[qwaddr_q] <= qwdata_q;
    end

    // exp2 pair ROM (256 x 36)
    logic [35:0] erom [256];
    initial $readmemh(EXP2_ROM, erom);

    // scratch BRAMs
    logic signed [31:0] sc_mem [512];
    logic [30:0]        es_mem [512];

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

    // recip engine
    logic        rc_start, rc_done;
    logic [31:0] rc_r;
    logic signed [7:0] rc_e;
    logic [47:0] rc_v;
    fx_recip #(.ROM_FILE(RECIP_ROM)) u_recip (
        .clk, .rstn, .start(rc_start), .v(rc_v), .p_in(6'd30),
        .done(rc_done), .r_out(rc_r), .e_out(rc_e)
    );

    typedef enum logic [5:0] {IDLE,
                              K_RD, K_W, K_W2, K_P, K_T1, K_T1B, K_T2A, K_T2,
                              K_SC1, K_SC2, K_SC3, K_SC4, K_SC5, K_SC6,
                              E_RD, E_M1, E_NF, E_ROM,
                              E_I1, E_I2, E_I3, E_I4, E_I5,
                              R_GO, R_WT,
                              P_RD, P_M1, P_P, P_PC1, P_PC2, P_VW, P_VW2, P_MUL,
                              P_SH, P_SH2, P_SH3, P_ACC,
                              O_EMIT, O_EMITA, O_EMIT2} st_e;
    st_e st;

    logic [9:0] t, T;
    logic signed [31:0] mx;
    logic signed [39:0] denom;
    logic signed [7:0]  ke_q, ve_q;

    // lanes (score phase: 4-deep adder stages so each fits 250 MHz).
    // UNPACKED arrays: element selects of signed PACKED arrays are
    // UNSIGNED per LRM (Vivado) but signed in simulation — the DNST
    // sim/synth mismatch family found on hardware. Unpacked elements
    // keep signedness in both tools.
    logic signed [23:0] prod [HD];          // q*k8 products
    logic signed [39:0] acc [HD];
    logic signed [26:0] psum4 [64];         // 64 sums-of-4
    logic signed [31:0] psum [16];          // 16 partials
    logic signed [33:0] psum16 [4];         // 4 sums-of-4 partials
    logic signed [35:0] dot;
    // p*v pipeline
    logic signed [25:0] pv_p [HD];          // p_t * v8
    logic [25:0]        pv_abs [HD];        // |pv_p| + round constant
    logic [HD-1:0]      pv_neg;
    logic [21:0]        pv_c [HD];          // coarse-shifted (by 4/8/12)
    logic signed [17:0] pv_s [HD];          // shifted terms

    // score pipeline (K_SC1..K_SC6): rshr64(dot*SC,15) then rshr64s by
    // (8-16-ke) decomposed into abs -> const-mult -> +2^14>>15 ->
    // rnd-add/coarse -> coarse/fine -> fine+sign+max. Shift fields are
    // registered from ke_q two states ahead of first use.
    logic signed [8:0]  ks_s;      // -8 - ke_q
    logic        ks_left, ks_big;
    logic [3:0]  ks_c4;
    logic [1:0]  ks_f2;
    logic [63:0] ks_rnd;
    logic        dsgn;
    logic [35:0] adot;
    logic [52:0] adm;              // |dot| * SC_Q15
    logic [37:0] smag;             // (adm + 2^14) >> 15
    logic [63:0] mag2, m2c;
    logic [31:0] lc64, lc2;        // left path: only [31:0] survive 32'()

    // exp pipeline temps
    logic signed [31:0] sc_t;
    logic signed [47:0] tq;
    logic [5:0]  en_n;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [16:0] ef;   // bit 16 zero by construction (f in [0,2^16))
    /* verilator lint_on UNUSEDSIGNAL */
    logic [35:0] epair;
    logic [17:0] ea;               // interp endpoint a, registered
    logic [18:0] ed;               // 19'(b - a), 19-bit wrap preserved
    logic [18:0] epm;              // 19-bit wrap product ed * ef[7:0]
    logic [30:0] e16q;
    logic        ez, el;           // en_n >= 31 / <= 14, registered
    logic [4:0]  esh;              // |14 - en_n|, registered
    logic [30:0] esv_q;
    logic [30:0] es_t;
    logic [16:0] p_t;
    /* verilator lint_off UNUSEDSIGNAL */
    logic signed [39:0] o_sel;     // registered acc mux ([31:0] emitted)
    logic signed [39:0] o_g4 [4];  // first mux level: 4x 64:1, registered
    /* verilator lint_on UNUSEDSIGNAL */
    logic [8:0]  oi;
    logic [3:0]  shamt_q;          // 15-ve-8, registered (range [6,15])
    logic [14:0] vadd_q;           // 1 << (shamt_q-1), registered
    logic [5:0]  psh_q;            // 30-rc_e+15, registered (range [15,62])
    logic [63:0] padd_q;           // its round constant
    logic [63:0] pvsum;            // mul_p + round constant
    logic [63:0] pvc64;            // pvsum >> coarse(psh_q)

    // 4x keep-replicas of the lane-broadcast controls (64 lanes each):
    // a single register driving 256 spread lanes was route-limited.
    (* keep = "true" *) logic [16:0] p_t_r   [4];
    (* keep = "true" *) logic [3:0]  shamt_r [4];
    (* keep = "true" *) logic [14:0] vadd_r  [4];
    (* keep = "true" *) logic        acc_en_r [4];
    (* keep = "true" *) logic        aclr_r   [4];

    localparam logic signed [32:0] LOG2E_Q16 = 33'sd94548;

    // free-running lane pipeline: each stage's inputs are stable from one
    // cycle before its consumer state, so no state-decoded enables (the
    // 256-lane enable fanout was a timing killer). Accumulators gate on a
    // single registered enable. One generate block per lane (constant
    // indices: unpacked-array NBA inside procedural loops is unsupported
    // by the simulator).
    always_ff @(posedge clk) begin
        for (int g = 0; g < 4; g++) begin
            p_t_r[g]    <= p_t;
            shamt_r[g]  <= shamt_q;
            vadd_r[g]   <= vadd_q;
            acc_en_r[g] <= (st == P_SH3);
            aclr_r[g]   <= (st == IDLE) && start;
        end
    end
    // shift split: (|x|+add)>>s == ((|x|+add)>>coarse)>>fine, exact;
    // coarse = {s[3:2],2'b0} in {4,8,12}, fine = s[1:0] (s in [6,15]).
    // Keeps the per-stage select fanout to 2 bits across 256 lanes.
    for (genvar d = 0; d < HD; d++) begin : g_lane
        always_ff @(posedge clk) begin
            prod[d] <= 24'(32'(qv[d]) * 32'(signed'(kv_data[d*8 +: 8])));
            pv_p[d] <= 26'(33'(p_t_r[d/64]) * 33'(signed'(kv_data[d*8 +: 8])));
            pv_neg[d] <= (pv_p[d] < 0);
            pv_abs[d] <= 26'((pv_p[d] < 0) ? unsigned'(27'(-pv_p[d]))
                                           : unsigned'(27'(pv_p[d])))
                         + 26'(vadd_r[d/64]);
            pv_c[d]   <= 22'(pv_abs[d] >> {shamt_r[d/64][3:2], 2'b00});
            pv_s[d]   <= pv_neg[d] ? -18'(pv_c[d] >> shamt_r[d/64][1:0])
                                   :  18'(pv_c[d] >> shamt_r[d/64][1:0]);
            if (aclr_r[d/64])
                acc[d] <= 40'd0;
            else if (acc_en_r[d/64])
                acc[d] <= 40'(acc[d] + 40'(pv_s[d]));
        end
    end
    for (genvar i = 0; i < 64; i++) begin : g_ps4
        always_ff @(posedge clk)
            psum4[i] <= 27'(prod[i*4 + 0]) + 27'(prod[i*4 + 1])
                      + 27'(prod[i*4 + 2]) + 27'(prod[i*4 + 3]);
    end
    for (genvar i = 0; i < 16; i++) begin : g_ps16
        always_ff @(posedge clk)
            psum[i] <= 32'(psum4[i*4 + 0]) + 32'(psum4[i*4 + 1])
                     + 32'(psum4[i*4 + 2]) + 32'(psum4[i*4 + 3]);
    end
    for (genvar i = 0; i < 4; i++) begin : g_ps64
        always_ff @(posedge clk)
            psum16[i] <= 34'(psum[i*4 + 0]) + 34'(psum[i*4 + 1])
                       + 34'(psum[i*4 + 2]) + 34'(psum[i*4 + 3]);
    end

    always_ff @(posedge clk) begin
        if (!rstn) begin
            st <= IDLE;
            busy <= 1'b0;
            done <= 1'b0;
            m_valid <= 1'b0;
            rc_start <= 1'b0;
        end else begin
            done <= 1'b0;
            rc_start <= 1'b0;
            if (st inside {E_M1, P_M1}) wcnt <= wcnt + 1'b1;
            case (st)
                IDLE: if (start) begin
                    t <= '0;
                    T <= cfg_t;
                    mx <= -32'sd2147483648;
                    denom <= '0;
                    busy <= 1'b1;
                    kv_addr <= 10'b0;             // bank0, t0
                    st <= K_RD;
                end
                // ---------- scores ----------
                K_RD: st <= K_W;                  // addr presented; wait
                K_W: st <= K_W2;                  // 2-cycle memory latency
                K_W2: st <= K_P;
                K_P: begin                        // kv_data now valid
                    ke_q <= kv_exp;
                    st <= K_T1;                   // prod latches this edge
                end
                K_T1: begin                       // psum4 latches
                    ks_s <= 9'sd8 - 9'sd16 - 9'(ke_q);
                    st <= K_T1B;
                end
                K_T1B: begin                      // psum latches
                    logic [5:0] amag;
                    amag = (ks_s >= 0) ? 6'(ks_s) : 6'(-ks_s);
                    ks_left <= (ks_s < 0);
                    ks_big  <= (ks_s >= 9'sd64) || (ks_s <= -9'sd64);
                    ks_c4   <= amag[5:2];
                    ks_f2   <= amag[1:0];
                    ks_rnd  <= (ks_s > 0 && ks_s < 9'sd64)
                               ? (64'd1 << 6'(ks_s - 9'sd1)) : 64'd0;
                    st <= K_T2A;
                end
                K_T2A: st <= K_T2;                // psum16 latches
                K_T2: begin
                    dot <= 36'(signed'(psum16[0])) + 36'(signed'(psum16[1]))
                         + 36'(signed'(psum16[2])) + 36'(signed'(psum16[3]));
                    st <= K_SC1;
                end
                // rshr64(dot*SC,15) then rshr64s(.., ks_s), decomposed:
                // sign strips off first (|dot|*SC + 2^14) >> 15 = smag, and
                // both shifts act on smag with the sign restored at the end.
                K_SC1: begin
                    adot <= (dot < 0) ? unsigned'(36'(-dot)) : unsigned'(dot);
                    dsgn <= (dot < 0);
                    st <= K_SC2;
                end
                K_SC2: begin
                    adm <= 53'(adot * 53'(unsigned'(SC_Q15)));
                    st <= K_SC3;
                end
                K_SC3: begin
                    smag <= 38'((adm + 53'd16384) >> 15);
                    st <= K_SC4;
                end
                K_SC4: begin
                    mag2 <= 64'(smag) + ks_rnd;
                    lc64 <= 32'(64'(smag) << {ks_c4, 2'b00});
                    st <= K_SC5;
                end
                K_SC5: begin
                    m2c <= mag2 >> {ks_c4, 2'b00};
                    lc2 <= lc64 << ks_f2;       // mod 2^32: exact under 32'()
                    st <= K_SC6;
                end
                K_SC6: begin
                    logic [31:0] fin;
                    logic signed [31:0] scv;
                    fin = ks_big  ? 32'd0
                        : ks_left ? lc2 : 32'(m2c >> ks_f2);
                    scv = dsgn ? -signed'(fin) : signed'(fin);
                    sc_mem[t[8:0]] <= scv;
                    if (scv > mx) mx <= scv;
                    if (t + 1'b1 == T) begin
                        t <= '0;
                        st <= E_RD;
                    end else begin
                        t <= t + 1'b1;
                        kv_addr <= {1'b0, t[8:0] + 9'd1};
                        st <= K_RD;
                    end
                end
                // ---------- exp ----------
                E_RD: begin
                    sc_t <= sc_mem[t[8:0]];
                    st <= E_M1;
                    wcnt <= '0;
                end
                E_M1: begin
                    logic signed [32:0] xd;
                    xd = 33'(sc_t) - 33'(mx);
                    if (xd > 0) xd = '0;
                    mul_a <= xd;
                    mul_b <= LOG2E_Q16;
                    if (wcnt == 2'd3) begin
                        tq <= 48'(mul_p >>> 16);        // floor
                        st <= E_NF;
                    end
                end
                E_NF: begin
                    logic [47:0] nn;
                    nn = 48'((-tq + 48'sh FFFF) >> 16);
                    en_n <= (nn > 48'd62) ? 6'd62 : 6'(nn);
                    ef <= 17'(tq + 48'(48'((-tq + 48'sh FFFF) >> 16) << 16));
                    st <= E_ROM;
                end
                E_ROM: begin
                    epair <= erom[ef[15:8]];
                    ez  <= (en_n >= 6'd31);
                    el  <= (en_n <= 6'd14);
                    esh <= (en_n <= 6'd14) ? 5'(6'd14 - en_n)
                                           : 5'(en_n - 6'd14);
                    st <= E_I1;
                end
                // PWL interp + 2^-n scale, one small step per cycle
                // (19-bit wrap arithmetic of the original preserved)
                E_I1: begin
                    ea <= epair[17:0];
                    ed <= 19'(epair[35:18] - epair[17:0]);
                    st <= E_I2;
                end
                E_I2: begin
                    epm <= 19'(ed * 19'({11'b0, ef[7:0]}));
                    st <= E_I3;
                end
                E_I3: begin
                    e16q <= 31'({13'b0, ea} + 31'(18'((epm + 19'd128) >> 8)));
                    st <= E_I4;
                end
                E_I4: begin
                    esv_q <= ez ? '0 : (el ? (e16q << esh) : (e16q >> esh));
                    st <= E_I5;
                end
                E_I5: begin
                    es_mem[t[8:0]] <= esv_q;
                    denom <= denom + 40'(esv_q);
                    if (t + 1'b1 == T) begin
                        t <= '0;
                        st <= R_GO;
                    end else begin
                        t <= t + 1'b1;
                        st <= E_RD;
                    end
                end
                // ---------- recip ----------
                R_GO: begin
                    rc_v <= (denom == 0) ? 48'd1 : 48'(denom);
                    rc_start <= 1'b1;
                    st <= R_WT;
                end
                R_WT: if (rc_done) begin
                    psh_q <= 6'(8'sd45 - rc_e);          // in [15,62]
                    padd_q <= 64'd1 << (6'(8'sd45 - rc_e) - 6'd1);
                    kv_addr <= {1'b1, 9'd0};
                    st <= P_RD;
                end
                // ---------- p*v ----------
                P_RD: begin
                    es_t <= es_mem[t[8:0]];
                    st <= P_M1;
                    wcnt <= '0;
                end
                P_M1: begin
                    mul_a <= 33'({2'b0, es_t});
                    mul_b <= 33'(rc_r);
                    if (wcnt == 2'd3) st <= P_P;
                end
                P_P: begin
                    // mul_p = es*r >= 0 always: rshr64 == (x+add)>>sh here
                    pvsum <= 64'(mul_p) + padd_q;
                    st <= P_PC1;
                end
                P_PC1: begin                      // coarse then fine: exact
                    pvc64 <= pvsum >> {psh_q[5:2], 2'b00};
                    st <= P_PC2;
                end
                P_PC2: begin
                    logic [63:0] pv;
                    pv = pvc64 >> psh_q[1:0];
                    p_t <= (pv > 64'd32768) ? 17'd32768 : 17'(pv);
                    ve_q <= kv_exp;
                    st <= P_VW;
                end
                P_VW: begin
                    shamt_q <= 4'(8'sd15 - ve_q - 8'sd8);   // in [6,15]
                    vadd_q <= 15'(16'd1 << (4'(8'sd15 - ve_q - 8'sd8) - 4'd1));
                    st <= P_VW2;          // (kv_data settled since P_RD)
                end
                // P_VW2: broadcast settle. p_t_r/shamt_r/vadd_r update at
                // the end of this cycle's predecessor; the extra state
                // moves every aligned downstream consume one cycle later,
                // so the replica->lane hops get 2 full cycles and their
                // intermediate free-running captures are dead (overwritten
                // before the state-gated consume). This is what makes the
                // MCP2 exceptions on p_t_r/shamt_r/vadd_r in
                // synth/constraints/layer_mcp.xdc legal — do not remove
                // one without the other.
                P_VW2: st <= P_MUL;
                P_MUL: st <= P_SH;
                P_SH:  st <= P_SH2;
                P_SH2: st <= P_SH3;
                P_SH3: st <= P_ACC;
                P_ACC: begin
                    if (t + 1'b1 == T) begin
                        oi <= '0;
                        st <= O_EMIT;
                    end else begin
                        t <= t + 1'b1;
                        kv_addr <= {1'b1, t[8:0] + 9'd1};
                        st <= P_RD;
                    end
                end
                // ---------- output ----------
                O_EMIT: begin
                    if (!m_valid) begin
                        for (int g = 0; g < 4; g++)       // 4x 64:1 first
                            o_g4[g] <= signed'(acc[{2'(g), oi[5:0]}]);
                        st <= O_EMITA;
                    end else if (m_ready) begin
                        m_valid <= 1'b0;
                        if (oi == 9'(HD - 1)) begin
                            busy <= 1'b0;
                            done <= 1'b1;
                            st <= IDLE;
                        end else
                            oi <= oi + 1'b1;
                    end
                end
                O_EMITA: begin
                    o_sel <= o_g4[oi[7:6]];               // 4:1 second level
                    st <= O_EMIT2;
                end
                O_EMIT2: begin
                    m_data <= 32'(o_sel);
                    m_idx <= oi[7:0];
                    m_valid <= 1'b1;
                    st <= O_EMIT;
                end
                default: st <= IDLE;
            endcase
        end
    end

endmodule

`default_nettype wire
