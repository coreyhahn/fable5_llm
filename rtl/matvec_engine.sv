// matvec_engine: streamed W4A8 matrix-vector engine (quant_spec.md, frozen).
//
// DUAL MODE (cfg_g64):
//
//   mode 0 (cfg_g64=0) — legacy G=128, the frozen stage-2 format.
//     Per output row: NG weight beats (one beat == one G=128 group: 128
//     packed INT4) followed by ONE scale beat (32x uint16 LE, first NG
//     valid).  Bit-identical to the stage-2 engine (y32 is the law); the
//     CYCLE identity is gone as of rung 4 — the retire pipeline below is
//     strictly faster (see "Row cadence").
//
//   mode 1 (cfg_g64=1) — G=64, "v2 row format".
//     Weight beats: count UNCHANGED = NG (= cfg_ng); each beat carries TWO
//     consecutive 64-weight groups (group 2i = bytes 0..31, group 2i+1 =
//     bytes 32..63; nibble packing unchanged).
//     Scale beats: NG64 = 2*NG scales, uint16 LE in group order, 32/beat,
//     tail zero => ceil(NG64/32) beats: ONE when NG <= 16, TWO when
//     NG in 17..32 (MAX_NG=32).  Row ends on the LAST scale beat.
//
// Activations x8 (INT8) are preloaded into a wide LUTRAM via a 32-bit write
// port (CSR side); a beat always covers 128 consecutive k in both modes, so
// the activation line addressing is mode-independent.
//
// Integer pipeline, bit-exact to ref/w4a8_ref.py:
//   mode 0:  acc_g = sum_{k in group g} w4[k]*x8[k]        (19b signed)
//            p     = sum_g m_g * acc_g                     (48b signed)
//   mode 1:  lo_i  = sum_{k=0..63}   w4[k]*x8[k]  of beat i (18b signed)
//            hi_i  = sum_{k=64..127} w4[k]*x8[k]  of beat i (18b signed)
//            p     = sum_i (m[2i]*lo_i + m[2i+1]*hi_i)     (48b signed)
//   both:    y32   = rshift_round(p, sh)  (round half away from zero)
//
//   The 128-input adder tree has a natural midpoint (sum4_q[0..1] cover
//   k=0..63, sum4_q[2..3] cover k=64..127), so mode 1 costs no second tree:
//   the last tree stage emits the two halves instead of their sum.
//   Mode 0 then falls out of the SAME two-multiplier retire by driving both
//   scale operands with m_g:  m*lo + m*hi == m*(lo+hi) == m*acc_g, exactly.
//
// ------------------------------------------------------------------------
// RUNG 4 / S1: TAGGED RETIRE PIPELINE (the stage-2..3 drain FSM is gone)
// ------------------------------------------------------------------------
// The old D_IDLE/D_FLUSH/D_MAC/D_WAIT/D_EMIT sequencer owned the row from
// its scale beat until its result hit the FIFO, and the input side refused
// the NEXT row's scale beat for that whole window: NG+10 cycles per row
// against NG+1 stream beats, i.e. a fixed 9-cycle bubble every row.
//
// Now: the row's last scale beat pushes a 1-deep pending DESCRIPTOR
// {row, bank, start-delay}.  A free-running retire sequencer walks r_g =
// 0..NG-1 (one weight beat per cycle in BOTH modes) and hands each index to
// a 4-stage MAC pipe.  Nothing in the MAC pipe is ever stalled; the row
// boundary rides along as TAGS:
//
//   M0  bank + scale read   -> mac_{lo,hi,ma,mb}_q  + {first,last,row}
//   M1  two 17x18 products  -> pa_q, pb_q           (2x DSP48E2)
//   M2  product sum         -> ps_q                 (36b)
//   M3  accumulate          -> p_acc <= (p_acc & {48{~first}}) + ps_q
//   R1  |p| + round const   -> rr_mag, rr_neg       (S3 stage 1)
//   R2  arith shift + neg   -> ofifo                (S3 stage 2)
//
// The `first` AND-mask replaces the old explicit "p_acc <= 0" state: it is
// a per-bit AND in front of the adder, which folds into the CARRY8
// propagate LUT and adds ZERO logic levels.  `last` is what emits.
//
// TREE-FLUSH START CONSTRAINT (unchanged in substance from the old D_FLUSH
// comment, now expressed as a per-descriptor delay):
//   A weight beat that fires at cycle B is readable from acc_bank at B+7
//   (stage 0..5 + the bank write).  The row's LAST weight beat fires at
//   L <= S-1 where S is the row's last scale beat, and the walk reads index
//   NG-1 at W+NG-1, so W >= L+8-NG is required and W >= S+7-NG suffices.
//   The descriptor also carries the scales, valid from S+1.  Hence
//       W >= max(S+1, S+7-NG).
//   A push at S lands pd_valid at S+1 and the walk starts one cycle after
//   the descriptor is taken, so W = S+2+pd_wait with
//       pd_wait = max(0, 5-NG).
//
// S2 SINGLE SCALE BANK (ping-pong is FORBIDDEN: scales_q is the 64:1 mux
// that owns a +0.001 ui_clk cone).  scales_q therefore belongs to exactly
// one row at a time: sc_hold is set by a row's last scale beat and cleared
// by that row's LAST retire issue, and every scale beat (both of them in
// the 2-beat v2 case) waits on it.  Formally the next row's scale write
// lands at S'+1 and must be > W+NG-1, i.e. S' >= W+NG-1 — which is exactly
// when sc_hold drops.  This transitively protects the accumulator banks
// too: row R+2's first weight beat cannot precede S', so its bank write
// lands >= S'+8 > W+NG-1 >= any read row R makes.  Ping-pong stays 2-deep.
//
// Row cadence (measured, tb_matvec +nogap):
//   NG >= 5 : period = stream length exactly (NG+1 beats, or NG+2 for the
//             two-scale-beat v2 rows) -> ZERO exposed bubble.
//   NG <= 4 : the S2 guard floors the period at 6 cycles, so the exposed
//             bubble is 5-NG (4/3/2/1 for NG=1/2/3/4).  These are K<=512
//             shapes that no shipped layer uses; see RUNG4 notes.
//   Result latency also improved: S+NG+7+pd_wait vs the old S+NG+10.
//
// Lint-clean under -Wall; single clock domain (ui_clk of its DDR channel).

`timescale 1ns/1ps
`default_nettype none

module matvec_engine #(
    parameter int MAX_NG   = 32,    // max groups/row (K <= 4096)
    parameter int ROW_W    = 16     // row counter width
) (
    input  wire                clk,
    input  wire                rstn,

    // quasi-static config; sample-stable while busy
    input  wire [5:0]          cfg_ng,      // WEIGHT BEATS per row (1..MAX_NG)
    input  wire [5:0]          cfg_sh,      // final right-shift
    input  wire                cfg_g64,     // 0 = G=128 legacy, 1 = G=64 (v2)
    input  wire [ROW_W-1:0]    cfg_nrows,   // rows this engine will process
    input  wire                start,       // pulse: begin consuming beats
    output logic               busy,
    output logic               done,        // sticky until next start

    // activation BRAM write port (32-bit words, byte k of x8 at addr k/4)
    input  wire                x_we,
    input  wire [9:0]          x_waddr,
    input  wire [31:0]         x_wdata,

    // weight beat stream (from DDR reader)
    input  wire                s_valid,
    output logic               s_ready,
    input  wire [511:0]        s_data,

    // result stream
    output logic               m_valid,
    input  wire                m_ready,
    output logic [31:0]        m_y32,
    output logic [ROW_W-1:0]   m_row
);

    localparam int G      = 128;         // weights per BEAT (both modes)
    localparam int NSCAL  = 2 * MAX_NG;  // scale buffer entries (mode 1 max)
    localparam int ODEPTH = 4;           // result FIFO depth (see rowq)

    // ------------------------------------------------------------------
    // Activation storage: MAX_NG lines x 1024 bits, as 32 LUTRAM banks of
    // 32-bit words. Write: bank = x_waddr[4:0], line = x_waddr[9:5].
    // Read: full 1024-bit line for the current group.
    // Explicit per-bank arrays with a per-bank write-enable compare: the
    // 2-D dynamic-bank write defeated LUTRAM inference (32K flops + a
    // 1024-way CE decode was the build_019 WNS family).
    // ------------------------------------------------------------------
    (* ram_style = "distributed" *) logic [31:0] x_mem [32][MAX_NG];
    always_ff @(posedge clk) begin
        for (int b = 0; b < 32; b++)
            if (x_we && (x_waddr[4:0] == 5'(b)))
                x_mem[b][x_waddr[9:5]] <= x_wdata;
    end

    // ------------------------------------------------------------------
    // Input/control: beat counter walks 0..cfg_ng+NSB-1.
    //   0 .. cfg_ng-1              weight beats
    //   cfg_ng .. cfg_ng+NSB-1     scale beats (NSB = 1, or 2 in mode 1
    //                              when 2*cfg_ng > 32)
    // ------------------------------------------------------------------
    logic [5:0]       g_cnt;
    logic [ROW_W-1:0] row_in;        // row currently streaming in
    logic             bank_sel;      // bank being FILLED

    // scale beats this row needs: mode 0 -> 1, mode 1 -> ceil(2*cfg_ng/32)
    wire        two_scale_beats = cfg_g64 && (cfg_ng > 6'd16);
    wire [5:0]  last_scale_g    = cfg_ng + (two_scale_beats ? 6'd1 : 6'd0);

    wire is_scale_beat  = (g_cnt >= cfg_ng);
    wire is_last_scale  = (g_cnt == last_scale_g);
    wire scale_beat_idx = is_scale_beat && (g_cnt != cfg_ng);   // 0 or 1

    // ------------------------------------------------------------------
    // Retire-side handshake signals (declared here, driven below).
    //   sc_hold  : scales_q is owned by a row that has not finished issuing
    //   r_last   : the retire is issuing that row's LAST index THIS cycle
    //   pd_valid : the 1-deep pending descriptor slot is occupied
    //   rowq     : rows pushed but not yet popped out of the result FIFO
    // ------------------------------------------------------------------
    logic       sc_hold;
    logic       r_last;
    logic       pd_valid;
    logic [2:0] rowq;

    wire rowq_full = (rowq == 3'(ODEPTH));

    // A scale beat writes scales_q, so it must wait until the previous row
    // has issued its last scale read (S2).  The LAST scale beat also pushes
    // the descriptor, so it additionally waits for a free descriptor slot
    // and for result-FIFO room (rowq <= ODEPTH keeps ofifo overflow-proof).
    wire scale_blocked = is_scale_beat
                         && ((sc_hold && !r_last)
                             || (is_last_scale && (pd_valid || rowq_full)));
    // soft backpressure at the row boundary, as before
    wire row_start_blocked = (g_cnt == 6'd0) && (rowq >= 3'(ODEPTH - 1));

    assign s_ready = busy && !row_start_blocked && !scale_blocked;
    wire beat_fire = s_valid && s_ready;
    wire row_push  = beat_fire && is_last_scale;

    // ------------------------------------------------------------------
    // Stage 0: latch beat + read x line (registered for timing)
    // ------------------------------------------------------------------
    logic [511:0] beat_q;
    logic [1023:0] xline_q;
    logic          v0_q;            // weight-beat valid in stage 0
    logic [4:0]    g_q;             // weight-beat group index (0..NG-1 <= 31)
    logic          b_q;             // bank select traveling WITH the beat
                                    // (bank_sel flips at the scale beat while
                                    //  this row's last groups are in flight)

    always_ff @(posedge clk) begin
        if (!rstn) begin
            v0_q <= 1'b0;
        end else begin
            v0_q <= beat_fire && !is_scale_beat;
            if (beat_fire && !is_scale_beat) begin
                beat_q <= s_data;
                g_q    <= g_cnt[4:0];
                b_q    <= bank_sel;
                for (int b = 0; b < 32; b++)
                    xline_q[b*32 +: 32] <= x_mem[b][g_cnt[4:0]];
            end
        end
    end

    // ------------------------------------------------------------------
    // Stage 1: 128 products w4*x8 (12b signed)
    // ------------------------------------------------------------------
    logic signed [G-1:0][11:0] prod_q;
    logic               v1_q;
    logic [4:0]         g1_q;
    logic               b1_q;

    always_ff @(posedge clk) begin
        if (!rstn) v1_q <= 1'b0;
        else begin
            v1_q <= v0_q;
            g1_q <= g_q;
            b1_q <= b_q;
            if (v0_q) begin
                for (int k = 0; k < G; k++) begin
                    logic signed [3:0] w;
                    logic signed [7:0] xv;
                    // low nibble = even k, high nibble = odd k (pack_w4)
                    w  = (k % 2 == 0) ? signed'(beat_q[(k/2)*8 +: 4])
                                      : signed'(beat_q[(k/2)*8+4 +: 4]);
                    xv = signed'(xline_q[k*8 +: 8]);
                    prod_q[k] <= w * xv;
                end
            end
        end
    end

    // ------------------------------------------------------------------
    // Stages 2-5: pipelined adder tree, max 2 add-levels per stage
    // (re-staged for 300 MHz timing: build_009 WNS -0.68 was here)
    // 128 -> 64 (13b) -> 16 (15b) -> 4 (17b) -> 1 (19b)
    // ------------------------------------------------------------------
    logic signed [63:0][12:0] sum64_q;
    logic               v2_q;
    logic [4:0]         g2_q;
    logic               b2_q;
    always_ff @(posedge clk) begin
        if (!rstn) v2_q <= 1'b0;
        else begin
            v2_q <= v1_q;
            g2_q <= g1_q;
            b2_q <= b1_q;
            if (v1_q)
                for (int i = 0; i < 64; i++)
                    sum64_q[i] <= 13'(signed'(prod_q[2*i])) + 13'(signed'(prod_q[2*i+1]));
        end
    end

    logic signed [15:0][14:0] sum16_q;
    logic               v3_q;
    logic [4:0]         g3_q;
    logic               b3_q;
    always_ff @(posedge clk) begin
        if (!rstn) v3_q <= 1'b0;
        else begin
            v3_q <= v2_q;
            g3_q <= g2_q;
            b3_q <= b2_q;
            if (v2_q)
                for (int i = 0; i < 16; i++)
                    sum16_q[i] <= 15'(signed'(sum64_q[4*i]))   + 15'(signed'(sum64_q[4*i+1]))
                                + 15'(signed'(sum64_q[4*i+2])) + 15'(signed'(sum64_q[4*i+3]));
        end
    end

    logic signed [3:0][16:0] sum4_q;
    logic               v4_q;
    logic [4:0]         g4_q;
    logic               b4_q;
    always_ff @(posedge clk) begin
        if (!rstn) v4_q <= 1'b0;
        else begin
            v4_q <= v3_q;
            g4_q <= g3_q;
            b4_q <= b3_q;
            if (v3_q)
                for (int i = 0; i < 4; i++)
                    sum4_q[i] <= 17'(signed'(sum16_q[4*i]))   + 17'(signed'(sum16_q[4*i+1]))
                               + 17'(signed'(sum16_q[4*i+2])) + 17'(signed'(sum16_q[4*i+3]));
        end
    end

    // Final tree stage, TAPPED AT THE MIDPOINT: sum4_q[0..1] are k=0..63
    // (v2 group 2i, beat bytes 0..31), sum4_q[2..3] are k=64..127 (group
    // 2i+1, bytes 32..63).  Same two add-levels as the stage-2 single-sum
    // version, so the stage-5 critical path is unchanged.  Mode 0 recovers
    // the 19b group sum in the retire as lo+hi (exact, no truncation).
    logic signed [17:0] acc_lo_q, acc_hi_q;
    logic               v5_q;
    logic [4:0]         g5_q;
    logic               b5_q;
    always_ff @(posedge clk) begin
        if (!rstn) v5_q <= 1'b0;
        else begin
            v5_q <= v4_q;
            g5_q <= g4_q;
            b5_q <= b4_q;
            if (v4_q) begin
                acc_lo_q <= 18'(signed'(sum4_q[0])) + 18'(signed'(sum4_q[1]));
                acc_hi_q <= 18'(signed'(sum4_q[2])) + 18'(signed'(sum4_q[3]));
            end
        end
    end

    // ------------------------------------------------------------------
    // Accumulator banks (ping-pong, 2-deep): written by tree output, read
    // by the retire walk.  One entry per WEIGHT BEAT, both 64-wide halves.
    // ------------------------------------------------------------------
    logic signed [17:0] acc_bank_lo [2][MAX_NG];
    logic signed [17:0] acc_bank_hi [2][MAX_NG];
    always_ff @(posedge clk) begin
        if (v5_q) begin
            acc_bank_lo[b5_q][g5_q] <= acc_lo_q;
            acc_bank_hi[b5_q][g5_q] <= acc_hi_q;
        end
    end

    // SINGLE scale bank (S2): mode 0 uses [0..cfg_ng-1], mode 1 uses
    // [0..2*cfg_ng-1].  Ownership is serialized by sc_hold, NOT duplicated.
    logic [NSCAL-1:0][15:0] scales_q;

    // ------------------------------------------------------------------
    // Row/bank control
    // ------------------------------------------------------------------
    logic [ROW_W-1:0] rows_done_in;
    always_ff @(posedge clk) begin
        if (!rstn) begin
            g_cnt     <= '0;
            row_in    <= '0;
            bank_sel  <= 1'b0;
            busy      <= 1'b0;
            rows_done_in <= '0;
        end else begin
            if (start) begin
                g_cnt    <= '0;
                row_in   <= '0;
                bank_sel <= 1'b0;
                busy     <= 1'b1;
                rows_done_in <= '0;
            end
            if (beat_fire) begin
                if (is_scale_beat) begin
                    // 32 scales/beat; beat 0 -> [0:31], beat 1 -> [32:63]
                    for (int i = 0; i < 32; i++)
                        scales_q[{scale_beat_idx, 5'(i)}] <= s_data[i*16 +: 16];
                    if (is_last_scale) begin
                        bank_sel     <= ~bank_sel;
                        g_cnt        <= '0;
                        row_in       <= row_in + 1'b1;
                        rows_done_in <= rows_done_in + 1'b1;
                        if (rows_done_in + 1'b1 == cfg_nrows)
                            busy <= 1'b0;  // stop accepting; retire finishes
                    end else begin
                        g_cnt <= g_cnt + 1'b1;
                    end
                end else begin
                    g_cnt <= g_cnt + 1'b1;
                end
            end
        end
    end

    // ------------------------------------------------------------------
    // S1: pending row descriptor (1-deep) + free-running retire sequencer
    // ------------------------------------------------------------------
    logic [ROW_W-1:0] pd_row;
    logic             pd_bank;
    logic [2:0]       pd_wait;      // tree-flush start delay, max(0, 5-NG)

    logic             r_active;
    logic [5:0]       r_g;
    logic [ROW_W-1:0] r_row;
    logic             r_bank;

    assign r_last = r_active && (r_g + 6'd1 == cfg_ng);
    wire   pd_rdy = pd_valid && (pd_wait == 3'd0);
    // take the descriptor when the walk is idle, or on the very cycle the
    // current row issues its last index (back-to-back rows)
    wire   r_take = pd_rdy && (!r_active || r_last);

    // scale operand select: mode 1 takes the pair (2i, 2i+1); mode 0 drives
    // BOTH with m_i, so p += m*lo + m*hi == m*(lo+hi) == m*acc_i, exactly.
    // NOTE (timing): this is the 64:1 scales mux -- r_g feeds it directly,
    // exactly as d_g did.  Do not add logic between them.
    wire [5:0] sc_idx_a = cfg_g64 ? {r_g[4:0], 1'b0} : {1'b0, r_g[4:0]};
    wire [5:0] sc_idx_b = cfg_g64 ? {r_g[4:0], 1'b1} : {1'b0, r_g[4:0]};

    // M0: registered bank/scale reads feeding the MAC DSPs (timing)
    logic signed [17:0] mac_lo_q, mac_hi_q;
    logic [15:0]        mac_ma_q, mac_mb_q;
    logic               mac_v_q, mac_first_q, mac_last_q;
    logic [ROW_W-1:0]   mac_row_q;
    // M1: the two products (17b signed scale x 18b signed half-sum)
    logic signed [34:0] pa_q, pb_q;
    logic               pv_q, p_first_q, p_last_q;
    logic [ROW_W-1:0]   p_row_q;
    // M2: product sum
    logic signed [35:0] ps_q;
    logic               sv_q, s_first_q, s_last_q;
    logic [ROW_W-1:0]   s_row_q;
    // M3: the 48b accumulator (first folds into the adder as an AND mask)
    logic signed [47:0] p_acc;
    logic               e_v_q;          // p_acc is FINAL this cycle
    logic [ROW_W-1:0]   e_row_q;

    wire [47:0] acc_keep = p_acc & {48{~s_first_q}};

    // ---- S3: rshift_round split into TWO stages -----------------------
    // R1 (add):   mag = |p| + (1 << (sh-1))   -- ONE carry chain, the
    //             conditional complement rides the adder's input LUTs.
    // R2 (shift): y = neg ? -(mag >>> sh) : (mag >>> sh), truncated to 32b.
    // Bit-identical to the old single-cycle rshr(): for sh == 0 the round
    // constant is 0 and the two complements cancel, returning p exactly.
    // Negating after the 32b truncation is exact (mod 2^32) and keeps the
    // second stage's carry chain 32 bits instead of 48.
    logic               rr_v, rr_neg;
    logic signed [47:0] rr_mag;
    logic [ROW_W-1:0]   rr_row;

    wire [47:0] rnd_c   = (cfg_sh == 6'd0) ? 48'd0 : (48'd1 << (cfg_sh - 6'd1));
    wire        acc_neg = p_acc[47];
    wire [47:0] acc_cc  = p_acc ^ {48{acc_neg}};

    /* verilator lint_off UNUSEDSIGNAL */
    wire signed [47:0] rr_shift = rr_mag >>> cfg_sh;   // [47:32] dropped
    /* verilator lint_on UNUSEDSIGNAL */
    wire [31:0]        rr_trunc = rr_shift[31:0];
    wire [31:0]        rr_y32   = rr_neg ? (-rr_trunc) : rr_trunc;

    // small output FIFO (depth ODEPTH); rowq guarantees it never overflows
    logic [31+ROW_W:0] ofifo [ODEPTH];
    logic [2:0] of_wr, of_rd;
    wire  [2:0] of_count = of_wr - of_rd;
    wire        of_empty = (of_count == 3'd0);

    assign m_valid = !of_empty;
    assign m_y32   = ofifo[of_rd[1:0]][31:0];
    assign m_row   = ofifo[of_rd[1:0]][31+ROW_W:32];

    wire row_pop = m_valid && m_ready;

    always_ff @(posedge clk) begin
        if (!rstn) begin
            pd_valid <= 1'b0;
            pd_wait  <= 3'd0;
            r_active <= 1'b0;
            sc_hold  <= 1'b0;
            rowq     <= 3'd0;
            mac_v_q  <= 1'b0;
            pv_q     <= 1'b0;
            sv_q     <= 1'b0;
            e_v_q    <= 1'b0;
            rr_v     <= 1'b0;
            of_wr    <= '0;
            of_rd    <= '0;
        end else begin
            // ---- pending descriptor (row_push and r_take are mutually
            // exclusive: a push needs pd_valid == 0, r_take needs it set)
            if (row_push) begin
                pd_valid <= 1'b1;
                pd_row   <= row_in;
                pd_bank  <= bank_sel;
                pd_wait  <= (cfg_ng >= 6'd5) ? 3'd0 : 3'(6'd5 - cfg_ng);
            end else begin
                if (r_take) pd_valid <= 1'b0;
                if (pd_valid && pd_wait != 3'd0) pd_wait <= pd_wait - 3'd1;
            end

            // ---- scales_q ownership (S2)
            if (row_push)    sc_hold <= 1'b1;
            else if (r_last) sc_hold <= 1'b0;

            // ---- retire walk
            if (r_take) begin
                r_active <= 1'b1;
                r_g      <= '0;
                r_row    <= pd_row;
                r_bank   <= pd_bank;
            end else if (r_last) begin
                r_active <= 1'b0;
            end else if (r_active) begin
                r_g <= r_g + 6'd1;
            end

            // ---- M0: bank + scale read, tagged
            mac_v_q <= r_active;
            if (r_active) begin
                mac_lo_q    <= acc_bank_lo[r_bank][r_g[4:0]];
                mac_hi_q    <= acc_bank_hi[r_bank][r_g[4:0]];
                mac_ma_q    <= scales_q[sc_idx_a];
                mac_mb_q    <= scales_q[sc_idx_b];
                mac_first_q <= (r_g == 6'd0);
                mac_last_q  <= (r_g + 6'd1 == cfg_ng);
                mac_row_q   <= r_row;
            end

            // ---- M1: the two 17x18 products
            pv_q <= mac_v_q;
            if (mac_v_q) begin
                pa_q      <= $signed({1'b0, mac_ma_q}) * mac_lo_q;
                pb_q      <= $signed({1'b0, mac_mb_q}) * mac_hi_q;
                p_first_q <= mac_first_q;
                p_last_q  <= mac_last_q;
                p_row_q   <= mac_row_q;
            end

            // ---- M2: product sum
            sv_q <= pv_q;
            if (pv_q) begin
                ps_q      <= 36'(pa_q) + 36'(pb_q);
                s_first_q <= p_first_q;
                s_last_q  <= p_last_q;
                s_row_q   <= p_row_q;
            end

            // ---- M3: accumulate; `first` clears via the adder's AND mask
            if (sv_q) p_acc <= $signed(acc_keep) + 48'(ps_q);
            e_v_q <= sv_q && s_last_q;
            if (sv_q && s_last_q) e_row_q <= s_row_q;

            // ---- R1: |p_acc| + rounding constant
            rr_v <= e_v_q;
            if (e_v_q) begin
                rr_mag  <= $signed(acc_cc + rnd_c + {47'd0, acc_neg});
                rr_neg  <= acc_neg;
                rr_row  <= e_row_q;
            end

            // ---- R2: arithmetic shift + conditional negate -> result FIFO
            if (rr_v) begin
                ofifo[of_wr[1:0]] <= {rr_row, rr_y32};
                of_wr <= of_wr + 1'b1;
            end
            if (row_pop) of_rd <= of_rd + 1'b1;

            // ---- rows in flight (push at the descriptor, pop at the FIFO)
            if (row_push && !row_pop)      rowq <= rowq + 3'd1;
            else if (row_pop && !row_push) rowq <= rowq - 3'd1;
        end
    end

    // rowq == 0 means every pushed row has been popped, so nothing is left
    // in the descriptor slot, the walk, the MAC pipe or the FIFO.
    assign done = !busy && (rowq == 3'd0) && (rows_done_in != '0);

endmodule

`default_nettype wire
