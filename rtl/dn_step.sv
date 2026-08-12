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

module dn_step #(
    parameter int LDK = 128,
    parameter int LDV = 128
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

    typedef enum logic [4:0] {IDLE,
                              P1_RD, P1_W, P1_DECM, P1_DEC, P1_KM, P1_KW,
                              DLT_K, DLT_S, DLT_M, DLT_D, DLT_B,
                              P2_RD, P2_M, P2_OUT, P2_QM, P2_QW,
                              O_EMIT, O_EMIT2} st_e;
    st_e st;
    logic [7:0] row;
    logic signed [39:0] o_sel;     // registered acc mux for O_EMIT

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
                    st <= P1_RD;
                end
                // ---------------- pass 1 ----------------
                P1_RD: begin
                    kn_dk <= kn[row[6:0]];
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
                        s_rdaddr <= row[6:0] + 1'b1;
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
                    st <= P2_M;
                end
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
                        st <= O_EMIT;
                    end else begin
                        row <= row + 1'b1;
                        s_rdaddr <= row[6:0] + 1'b1;
                        st <= P2_RD;
                    end
                end
                // ---------------- output ----------------
                O_EMIT: begin
                    if (!m_valid) begin
                        o_sel <= signed'(o_acc[oi[6:0]]);  // 128:1 mux stage
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
                    st <= O_EMIT;
                end
                default: st <= IDLE;
            endcase
        end
    end

endmodule

`default_nettype wire
