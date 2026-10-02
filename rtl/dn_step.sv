// dn_step: one gated-delta-rule recurrence step for ONE head — bit-exact
// mirror of the per-head loop in layer_fixed.deltanet_decode_fx:
//
//   pass1 (per row dk):  Sh[dk][v] = rshr(S[dk][v] * decay, 15)   (writeback)
//                        kvm_acc[v] += Sh[dk][v] * kn[dk]
//   delta:               kvm[v]   = rshr(kvm_acc[v], 14)
//                        delta[v] = rshr((v_in[v] - kvm[v]) * beta, 15)
//   pass2 (per row dk):  Sf[dk][v] = clip16(Sh[dk][v] + rshr(kn[dk]*delta[v], 14))
//                        o_acc[v] += Sf[dk][v] * qn[dk]           (writeback Sf)
//   out:                 o[v] = rshr(o_acc[v], 14)        (32-bit, Q13 domain)
//
// State memory is EXTERNAL (2048-bit rows x 128, 2-cycle read latency).
// 128 parallel lanes; lane math is pipelined mult->shift->accumulate so
// every stage fits 250 MHz (~10 cycles/row -> ~1300 cycles/head).

`timescale 1ns/1ps
`default_nettype none

// ---- G3.4 (spec 4.1 W1'(a), A1.2): the state-memory READ LATENCY ----
// The state memory's read latency is a PARAMETER of this module now,
// because layer_chan's DN banking pipelines its SLR crossings
// (DN_PIPE = 2 -> latency 2 + 2*DN_PIPE = 6) and dn_step must lead its
// read address by exactly that much.  Two changes carry it:
//
//   1. `s_rdaddr <= row + 1` MOVED from each loop's TAIL (P1_KW, P2_QW)
//      to each loop's HEAD (P1_RD, P2_RD).  The address is then held for a
//      whole loop period, so the memory samples it RLAT cycles before the
//      consumer state at every RLAT the two loops can serve — which is
//      what makes ONE FSM correct at both 2 and 6 and lets G3.4 measure
//      the price instead of modelling it.
//   2. Pass 1's FIRST read has no previous iteration to lead it: IDLE
//      issues address 0 immediately before P1_RD.  P1_PRE holds RLAT-2
//      cycles so that read is in flight before P1_DECM consumes it.  This
//      is Track P's "only pass 1's first read pays" (PLACE_EXP.md 5).
//
// P2_WAIT is THE DECISION spec 4.1 W1'(a) forbids taking silently:
//   P2_WAIT = 1  option (i), a wait state in pass 2's loop.  +128 cyc/head
//                (plus pass 1's RLAT-2 entry cycles).  THIS IS WHAT SHIPS
//                at RLAT = 6.  It is one cycle of MARGIN on the pass-2
//                lead, not a structural necessity — see the gate doc.
//                P2_WAIT = 1 is ONLY legal at RLAT > 2: at RLAT = 2 the
//                6-state loop overshoots the lead by one and the caller
//                must pass 0 (layer_chan derives it from DN_RLAT).
//   P2_WAIT = 0  option (ii), two reads outstanding with no wait state.
//                NOT TAKEN at G3.4.
// The measurement, the sketch and why (i) was taken are
// evidence/qwen9b/g3/G3_4_LAYER.md section 4.  Do not flip P2_WAIT without
// reading it.
module dn_step #(
    parameter int LDK = 128,
    parameter int LDV = 128,
    parameter int RLAT = 2,        // state-memory read latency in cycles
    parameter int P2_WAIT = 0      // 1 = option (i)'s pass-2 wait state
) (
    input  wire                clk,
    input  wire                rstn,

    input  wire                start,
    output logic               busy,
    output logic               done,        // pulse

    input  wire [15:0]         cfg_decay,   // Q15
    input  wire [15:0]         cfg_beta,    // Q15

    // vector preload: sel 0=kn(Q14) 1=qn(Q14) 2=v(Q13, 21-bit sext)
    input  wire                vec_we,
    input  wire [1:0]          vec_sel,
    input  wire [6:0]          vec_addr,
    input  wire signed [20:0]  vec_data,

    // external state memory (2048b rows)
    output logic [6:0]         s_rdaddr,
    input  wire [LDV*16-1:0]   s_rddata,    // valid 1 cycle after rdaddr
    output logic [6:0]         s_wraddr,
    output logic [LDV*16-1:0]  s_wrdata,
    output logic               s_wren,

    // result stream: 128 x 32-bit (o_acc >> 14)
    output logic               m_valid,
    input  wire                m_ready,
    output logic signed [31:0] m_data,
    output logic [6:0]         m_idx
);
    import fx_pkg::*;

    // input-registered preload (keeps the scratch-BRAM haul off the
    // write decode; the source register lands near the lane arrays)
    logic               vwe_q;
    logic [1:0]         vsel_q;
    logic [6:0]         vaddr_q;
    logic signed [20:0] vdata_q;
    logic signed [15:0] kn  [LDK];
    logic signed [15:0] qn  [LDK];
    logic signed [20:0] vin [LDV];
    always_ff @(posedge clk) begin
        vwe_q   <= vec_we;
        vsel_q  <= vec_sel;
        vaddr_q <= vec_addr;
        vdata_q <= vec_data;
        if (vwe_q) begin
            case (vsel_q)
                2'd0: kn[vaddr_q]  <= vdata_q[15:0];
                2'd1: qn[vaddr_q]  <= vdata_q[15:0];
                2'd2: vin[vaddr_q] <= vdata_q;
                default: ;
            endcase
        end
    end

    // 4x keep-replicas of the lane-broadcast constants and enables
    // (32 lanes each): single registers driving 128 spread lanes were
    // route-limited, and Vivado's DSP input-register absorption otherwise
    // re-exposes the scratch BRAM output net at fanout 128.
    (* keep = "true" *) logic signed [15:0] beta_r  [4];
    (* keep = "true" *) logic signed [15:0] decay_r [4];
    (* keep = "true" *) logic               kvm_en_r  [4];
    (* keep = "true" *) logic               oacc_en_r [4];
    (* keep = "true" *) logic               clr_r     [4];

    typedef enum logic [4:0] {IDLE, P1_PRE,
                              P1_RD, P1_W, P1_DECM, P1_DEC, P1_KM, P1_KW,
                              DLT_K, DLT_S, DLT_M, DLT_D, DLT_B,
                              P2_RD, P2_WT, P2_M, P2_OUT, P2_QM, P2_QW,
                              O_FILL, O_EMIT, O_EMIT2} st_e;
    st_e st;
    logic [7:0] row;
    // pass-1 entry hold: RLAT-2 cycles, 0 at the unpipelined latency
    localparam int PRE_N = (RLAT > 2) ? (RLAT - 2) : 0;
    // WIDTH DERIVED FROM PRE_N, not a loose literal: the counter must be
    // able to hold PRE_N-1 and nothing wider, so a future RLAT cannot
    // silently overflow it.  ($clog2(1) is 0 in Verilator, so the max()
    // keeps the vector at least one bit wide at PRE_N <= 1.)
    localparam int PRE_W = (PRE_N > 1) ? $clog2(PRE_N) : 1;
    logic [PRE_W-1:0] pre_i;
    logic signed [39:0] o_sel;     // second mux level: 16:1, for O_EMIT
    logic signed [39:0] o_g8 [16]; // FIRST mux level: 16x 8:1 (stage D2)
    logic [2:0]         og_i;      // the low index o_g8 is gathering for

    // UNPACKED lane arrays: element selects of signed PACKED arrays are
    // UNSIGNED per LRM (zero-extend in width casts, unsigned compares).
    // (sim treats them as signed, Vivado as unsigned -> the DNST
    // sim/synth mismatch found on hardware, o_acc off by n*2^32).
    // Unpacked elements keep their signedness in both tools.
    logic signed [15:0] sh_row [LDV];      // current decayed row
    logic signed [15:0] sf_row [LDV];      // current final row
    logic signed [39:0] kvm_acc [LDV];
    logic signed [39:0] o_acc [LDV];
    logic signed [23:0] delta [LDV];       // |v - kvm|*beta>>15 <= 5.3e6

    logic signed [15:0] kn_dk, qn_dk;
    logic [7:0] oi;
    logic in_p2;                           // pass-2 phase flag

    // lane pipeline registers (mult results; shifts/adds in later stages)
    logic signed [31:0] dec_p [LDV];       // S*decay
    logic signed [31:0] kw_p [LDV];        // sh_row*kn
    logic signed [26:0] kvm_r [LDV];       // rshr(kvm_acc,14)
    logic signed [26:0] dsub [LDV];        // vin - kvm
    logic signed [42:0] dm_p [LDV];        // dsub*beta
    logic signed [39:0] p2_p [LDV];        // kn*delta
    logic signed [31:0] q_p [LDV];         // sf_row*qn

    // free-running lane pipeline: every stage's inputs are stable from one
    // cycle before its consumer state (state-decoded 128-lane enables were
    // a timing killer). Accumulators gate on single registered enables.
    // One generate block per lane (constant indices: unpacked-array NBA
    // inside procedural loops is unsupported by the simulator).
    always_ff @(posedge clk) begin
        for (int g = 0; g < 4; g++) begin
            beta_r[g]    <= signed'(cfg_beta);
            decay_r[g]   <= signed'(cfg_decay);
            kvm_en_r[g]  <= (st == P1_KM);
            oacc_en_r[g] <= (st == P2_QM);
            clr_r[g]     <= (st == IDLE);
        end
    end
    for (genvar v = 0; v < LDV; v++) begin : g_lane
        always_ff @(posedge clk) begin
            dec_p[v]  <= 32'(signed'(s_rddata[v*16 +: 16]))
                         * 32'(decay_r[v/32]);
            sh_row[v] <= 16'(rshr64(64'(dec_p[v]), 15));
            kw_p[v]   <= 32'(sh_row[v]) * 32'(kn_dk);
            kvm_r[v]  <= 27'(rshr64(64'(kvm_acc[v]), 14));
            dsub[v]   <= 27'(vin[v]) - kvm_r[v];
            dm_p[v]   <= 43'(dsub[v]) * 43'(beta_r[v/32]);
            delta[v]  <= 24'(rshr64(64'(dm_p[v]), 15));
            p2_p[v]   <= 40'(kn_dk) * 40'(delta[v]);
            sf_row[v] <= clip16(64'(signed'(s_rddata[v*16 +: 16]))
                                + rshr64(64'(p2_p[v]), 14));
            q_p[v]    <= 32'(sf_row[v]) * 32'(qn_dk);
            s_wrdata[v*16 +: 16] <= in_p2 ? unsigned'(sf_row[v])
                                          : unsigned'(sh_row[v]);
            if (clr_r[v/32]) begin
                kvm_acc[v] <= '0;
                o_acc[v] <= '0;
            end else begin
                if (kvm_en_r[v/32])
                    kvm_acc[v] <= 40'(kvm_acc[v] + 40'(kw_p[v]));
                if (oacc_en_r[v/32])
                    o_acc[v] <= 40'(o_acc[v] + 40'(q_p[v]));
            end
        end
    end

    // ---- stage D2: the output mux, split ----------------------------
    // `oi -> o_sel` was a 128:1 mux over 128 40-bit accumulators spread
    // across the die: 5 logic levels, 0.476 ns of logic against 3.704 ns of
    // ROUTE (design note section 7.2).  It is now two levels, so each cycle
    // covers half the physical span: 16 x 8:1 over EIGHT ADJACENT lanes
    // here, then the 16:1 into o_sel.  Same index: o_g8[h] is
    // o_acc[h*8 + og_i] and o_sel is o_g8[oi[6:3]] = o_acc[oi[6:0]].
    //
    // og_i LEADS oi by one emit iteration (set in O_EMIT2), so the drain
    // loop keeps its 3-cycle period and the whole change costs exactly ONE
    // cycle per DNST command: O_FILL, which primes this register for
    // oi = 0.  o_acc is stable for the whole drain (oacc_en_r is
    // st == P2_QM, clr_r is IDLE), so the gather needs no enable — the
    // module's own rule, state-decoded lane enables were a timing killer.
    always_ff @(posedge clk) begin
        for (int h = 0; h < 16; h++)
            o_g8[h] <= signed'(o_acc[{4'(h), og_i}]);
    end

    always_ff @(posedge clk) begin
        if (!rstn) begin
            st <= IDLE;
            busy <= 1'b0;
            done <= 1'b0;
            m_valid <= 1'b0;
            s_wren <= 1'b0;
            in_p2 <= 1'b0;
        end else begin
            done <= 1'b0;
            s_wren <= 1'b0;
            case (st)
                IDLE: if (start) begin
                    row <= '0;
                    busy <= 1'b1;
                    in_p2 <= 1'b0;
                    s_rdaddr <= '0;
                    pre_i <= '0;
                    st <= (PRE_N > 0) ? P1_PRE : P1_RD;
                end
                // read-latency entry hold (see the header): the address
                // for row 0 must be in flight PRE_N cycles before P1_RD.
                P1_PRE: begin
                    if (pre_i == PRE_W'((PRE_N > 0) ? PRE_N - 1 : 0))
                        st <= P1_RD;
                    else pre_i <= pre_i + 1'b1;
                end
                // ---------------- pass 1 ----------------
                P1_RD: begin
                    kn_dk <= kn[row[6:0]];
                    // lead the use by a whole loop period (header note 1)
                    s_rdaddr <= row[6:0] + 1'b1;
                    st <= P1_W;
                end
                P1_W: st <= P1_DECM;   // s_rddata valid after 2 cycles
                P1_DECM: st <= P1_DEC;     // dec_p latches this edge
                P1_DEC:  st <= P1_KM;      // sh_row latches
                P1_KM: begin               // kw_p + s_wrdata latch
                    s_wraddr <= row[6:0];
                    s_wren <= 1'b1;
                    st <= P1_KW;
                end
                P1_KW: begin               // kvm_acc accumulates (kvm_en)
                    if (row == 8'(LDK - 1)) begin
                        st <= DLT_K;
                    end else begin
                        row <= row + 1'b1;
                        st <= P1_RD;
                    end
                end
                // -------- delta (kvm_r/dsub/dm_p/delta latch in sequence)
                DLT_K: begin
                    row <= '0;
                    s_rdaddr <= '0;
                    in_p2 <= 1'b1;
                    st <= DLT_S;
                end
                DLT_S: st <= DLT_M;
                DLT_M: st <= DLT_D;
                DLT_D: st <= DLT_B;
                DLT_B: st <= P2_RD;
                // ---------------- pass 2 ----------------
                P2_RD: begin
                    kn_dk <= kn[row[6:0]];
                    qn_dk <= qn[row[6:0]];
                    // lead the use by a whole loop period (header note 1)
                    s_rdaddr <= row[6:0] + 1'b1;
                    st <= (P2_WAIT != 0) ? P2_WT : P2_M;
                end
                P2_WT:  st <= P2_M;        // option (i): the wait state
                P2_M:   st <= P2_OUT;      // p2_p latches
                P2_OUT: st <= P2_QM;       // sf_row latches
                P2_QM: begin               // q_p + s_wrdata latch
                    s_wraddr <= row[6:0];
                    s_wren <= 1'b1;
                    st <= P2_QW;
                end
                P2_QW: begin               // o_acc accumulates (oacc_en)
                    if (row == 8'(LDK - 1)) begin
                        oi <= '0;
                        og_i <= '0;
                        st <= O_FILL;
                    end else begin
                        row <= row + 1'b1;
                        st <= P2_RD;
                    end
                end
                // ---------------- output ----------------
                // O_FILL: one cycle, once per command — o_g8 gathers for
                // oi = 0 (stage D2).  This is the ONE architecturally
                // visible cycle the split costs: DNST's LCYC +1.
                O_FILL: st <= O_EMIT;
                O_EMIT: begin
                    if (!m_valid) begin
                        o_sel <= o_g8[oi[6:3]];            // 16:1 mux stage
                        st <= O_EMIT2;
                    end else if (m_ready) begin
                        m_valid <= 1'b0;
                        if (oi == 8'(LDV - 1)) begin
                            busy <= 1'b0;
                            done <= 1'b1;
                            st <= IDLE;
                        end else
                            oi <= oi + 1'b1;
                    end
                end
                O_EMIT2: begin
                    m_data <= 32'(rshr64(64'(o_sel), 14));
                    m_idx <= oi[6:0];
                    m_valid <= 1'b1;
                    og_i <= oi[2:0] + 3'd1;   // lead the next gather (D2)
                    st <= O_EMIT;
                end
                default: st <= IDLE;
            endcase
        end
    end

endmodule

`default_nettype wire
