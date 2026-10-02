// matvec_engine: streamed W4A8 matrix-vector engine
// (quant_spec.md frozen for W4; ref/w4a8_ref.py is the numerics law).
//
// ONE ROW FORMAT: G = 128, INT4 nibbles.
//
//   Per output row: NG weight beats (one beat == one G=128 group: 128
//   packed INT4, low nibble = even k, high nibble = odd k) followed by
//   ceil(NG/32) scale beats (32x uint16 LE per beat, in group order, tail
//   zero) -- ONE for every NG <= 32, TWO for NG 33..64, THREE for NG
//   65..96.  The count is exactly w4a8_ref.row_beats()'s ceil((K/g)/32):
//   the wire format is the reference's, never the RTL's.  Bit-identical to
//   the stage-2 engine (y32 is the law); the CYCLE identity is gone as of
//   rung 4 -- the retire pipeline below is strictly faster (see "Row
//   cadence").
//
// ------------------------------------------------------------------------
// G3.3 DELETED TWO MODES.  Nothing below describes them any more.
// ------------------------------------------------------------------------
//   * cfg_w8 (spec 5.1 / S5) -- INT8 byte weights, a g128-cadence format
//     that streamed 2*cfg_ng weight beats through a lane array widened to
//     the 127*128 envelope.  Measured OUT OF CONTEXT on the real part at
//     +5,826 CLB LUTs and +497 CARRY8 per channel
//     (evidence/qwen2b/rc/TIMING_035.md 8a), which is the whole reason it
//     went: the 9B operating point is W4 and never asks for it.
//   * cfg_g64 (spec 5.2 / S6) -- the G=64 "v2 row format", two 64-weight
//     groups per beat with ceil(2*NG/32) scale beats.  At NG = 96 that
//     count needs 6 bits and overflows the 2-bit n_scale_beats field, so
//     g64 is not merely unused at 9B, it is UNREPRESENTABLE.
//
//   THE HOST KEEPS ITS W8 LAW (spec 3.3).  ref/w4a8_ref.py's W8 section,
//   matvec_y32_w8 and sw/hwmap.py's w8 plumbing still serve build_034 /
//   build_035, which are resident and still run W8.  What is gone is the
//   RTL mode, in THIS bitstream only -- and with it SHAPE bits 28 and 29,
//   which cfg_ng now uses (rtl/matvec_chan.sv's register map).
//
// Activations x8 (INT8) are preloaded into a wide LUTRAM via a 32-bit write
// port (CSR side); a beat always covers 128 consecutive k.
//
// Integer pipeline, bit-exact to ref/w4a8_ref.py:
//   acc_g = sum_{k in group g} w4[k]*x8[k]        (19b signed)
//   p     = sum_g m_g * acc_g                     (48b signed)
//   y32   = rshift_round(p, sh)  (round half away from zero)
//
//   The 128-input adder tree has a natural midpoint (sum4_q[0..1] cover
//   k=0..63, sum4_q[2..3] cover k=64..127) and its last stage emits the two
//   halves rather than their sum.  The retire then drives the two scale
//   operands from the SAME m_g:  m*lo + m*hi == m*(lo+hi) == m*acc_g,
//   exactly.  (The midpoint tap was mode 1's reason for existing; it is
//   kept because the two-DSP retire is built on it and in W4 it is exact.)
//
// ------------------------------------------------------------------------
// WIDTHS -- the W4 law, RE-DERIVED at G3.3 when the W8 envelope was deleted
// ------------------------------------------------------------------------
// A weight is a sign-extended nibble, so |w| <= 8, and |x8| <= 128.  Every
// tree stage is the exact sum of its inputs; nothing rounds before the
// final shift.  Signed width of a magnitude v is v.bit_length() + 1.
//
//   stage      lanes   bound                       width  (W8 had)
//   prod_q       1     8*128      =      1024      12 b   (16 b)
//   sum64_q      2     16*128     =      2048      13 b   (16 b)
//   sum16_q      8     64*128     =      8192      15 b   (18 b)
//   sum4_q      32     256*128    =     32768      17 b   (20 b)
//   acc_{lo,hi} 64     512*128    =     65536      18 b   (21 b)
//   pa_q/pb_q          17 x 18                     35 b   (38 b)   <- still
//                                                    ONE DSP48E2 each: the
//                                                    27x18 signed multiplier
//                                                    takes the 18 b operand
//                                                    on its 27 b port and
//                                                    {1'b0, m} on the 18 b
//                                                    port.
//   ps_q               pa + pb                     36 b   (39 b)
//   p_acc              MAX_NG * 65535 * 131072     48 b   UNCHANGED
//                        = 8.25e11 at MAX_NG = 96, i.e. 41 b used, 7 b
//                        spare.  (Task 12 measures this rather than
//                        arguing it; the arithmetic is here so the next
//                        reader does not have to redo it.)
//   cfg_sh             6 b                                UNCHANGED
//   g_cnt              MAX_NG + ceil(MAX_NG/32) - 1 7 b   (see g_cnt below)
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
// 0..NG-1 (one weight beat per cycle) and hands each index to
// a 4-stage MAC pipe.  Nothing in the MAC pipe is ever stalled; the row
// boundary rides along as TAGS:
//
//   M0  bank + scale read   -> mac_{lo,hi,m}_q       + {first,last,row}
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
// S2 SINGLE SCALE BANK (ping-pong is FORBIDDEN: scales_q is the NSCAL:1
// mux that owns a +0.001 ui_clk cone).  scales_q therefore belongs to
// exactly one row at a time: sc_hold is set by a row's last scale beat and
// cleared by that row's LAST retire issue, and EVERY scale beat of the next
// row waits on it -- all three of them in the 3-beat NG 65..96 case, so the
// count generalizing changes nothing here.  Formally the next row's scale write
// lands at S'+1 and must be > W+NG-1, i.e. S' >= W+NG-1 — which is exactly
// when sc_hold drops.  This transitively protects the accumulator banks
// too: row R+2's first weight beat cannot precede S', so its bank write
// lands >= S'+8 > W+NG-1 >= any read row R makes.  Ping-pong stays 2-deep.
//
// Row cadence (measured, tb_matvec +nogap):
//   NG >= 5 : period = stream length exactly (NG + its scale-beat count)
//             -> ZERO exposed bubble.
//   NG <= 4 : the S2 guard floors the period at 6 cycles, so the exposed
//             bubble is 5-NG (4/3/2/1 for NG=1/2/3/4).  These are K<=512
//             shapes that no shipped layer uses; see RUNG4 notes.
//   Result latency also improved: S+NG+7+pd_wait vs the old S+NG+10.
//
// Lint-clean under -Wall; single clock domain (ui_clk of its DDR channel).

`timescale 1ns/1ps
`default_nettype none

module matvec_engine #(
    parameter int MAX_NG   = 96,    // max groups/row (K <= 12288 = the 9B
                                    // down_proj FFN; spec 4.5 W5)
    parameter int ROW_W    = 16     // row counter width
) (
    input  wire                clk,
    input  wire                rstn,

    // quasi-static config; sample-stable while busy
    input  wire [6:0]          cfg_ng,      // groups/row = K/128 = the WEIGHT
                                            //   BEAT count (1..MAX_NG)
    input  wire [5:0]          cfg_sh,      // final right-shift
    input  wire [ROW_W-1:0]    cfg_nrows,   // rows this engine will process
    // SR12 (SEQ_ISA v2.3 B17.2, R2) — quasi-static like the three above:
    input  wire                cfg_xbank,   // x_line starts at XB_LINE (48)
    input  wire                cfg_rbank,   // row tags start at RB_ROW (2048)
    input  wire                start,       // pulse: begin consuming beats
    output logic               busy,
    output logic               done,        // sticky until next start

    // activation BRAM write port (32-bit words, byte k of x8 at addr k/4)
    input  wire                x_we,
    input  wire [11:0]         x_waddr,
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

    localparam int G      = 128;         // weights per BEAT
    // Scale buffer.  A row carries ceil(MAX_NG/32) scale beats of 32
    // uint16 each, so the buffer is the beat count ROUNDED UP -- not
    // 2*MAX_NG, which was mode 1's 2-scales-per-group cadence (G3.3 / S6).
    localparam int NSCAL  = 32 * ((MAX_NG + 31) / 32);
    localparam int ODEPTH = 4;           // result FIFO depth (see rowq)

    // SR12 (SEQ_ISA v2.3 B17.2, R2): the bank-1 start values.  THE BANK IS
    // A RESET VALUE OF THE BARE REGISTERS, NEVER AN ADDER ON THEIR OUTPUTS
    // (spec 2026-09-27 §1.2, census §6.2 R2b): x_line loads XB_LINE instead
    // of 0 at the start and at every row end (only bits 5:4 of the constant
    // differ, so the x_mem address stays a bare flop and the waived
    // xline_q CE cone is untouched), and row_in loads RB_ROW instead of 0 at
    // the start, so the row TAG carries the bank to the RES write address
    // (rtl/matvec_chan.sv addra = m_row[11:0]) with no logic on that path.
    // XB_LINE = MAX_NG/2 = 48 lines = x word 1536; RB_ROW = half the
    // 4096-row RES.  Twins of ref/seq_format XBANK_LINE / RBANK_ROW, tied by
    // evidence/qwen9b/g3/isa_bits.py (section 7).
    localparam logic [6:0]       XB_LINE = 7'd48;
    localparam logic [ROW_W-1:0] RB_ROW  = ROW_W'(2048);

    // ------------------------------------------------------------------
    // Activation storage: MAX_NG lines x 1024 bits, as 32 LUTRAM banks of
    // 32-bit words. Write: bank = x_waddr[4:0], line = x_waddr[11:5].
    // Read: full 1024-bit line for the current group.
    // Explicit per-bank arrays with a per-bank write-enable compare: the
    // 2-D dynamic-bank write defeated LUTRAM inference (32K flops + a
    // 1024-way CE decode was the build_019 WNS family).
    // ------------------------------------------------------------------
    // UNBACKED HOLE (R4 review): x_waddr[11:5] spans lines 0..127, but only
    // MAX_NG = 96 lines exist — x words 3072..4095 have no storage.  Nothing
    // reaches them on either path: the burst path answers SLVERR outside the
    // 3072-word XWIN (the decode is `rtl/matvec_chan.sv:606-607` and its
    // SLVERR `rtl/matvec_chan.sv:614`), and an AXI-Lite XWIN push past word
    // 3071 lands here as an out-of-range unpacked-array write, which the
    // language discards (no guard is inferred, and none is needed).  The
    // read side stays inside 0..95 via the cfg_ng ENVELOPE assert at
    // `rtl/matvec_engine.sv:626-628`.
    // (D-CITE, re-derived at G3.3: the two pointers this paragraph names
    // moved twice — once when the ISA re-encoding shifted the file and again
    // here — so they are quoted with the file name, not a bare ":747".)
    (* ram_style = "distributed" *) logic [31:0] x_mem [32][MAX_NG];
    always_ff @(posedge clk) begin
        for (int b = 0; b < 32; b++)
            if (x_we && (x_waddr[4:0] == 5'(b)))
                x_mem[b][x_waddr[11:5]] <= x_wdata;
    end

    // ------------------------------------------------------------------
    // Input/control: beat counter walks 0..cfg_ng+NSB-1.
    //   0 .. cfg_ng-1              weight beats
    //   cfg_ng .. cfg_ng+NSB-1     scale beats
    // 7 bits.  RE-DERIVED at G3.3 (the old "2*MAX_NG + 2 = 98 at MAX_NG =
    // 48" was the W8 beat doubling, which is gone): the largest value g_cnt
    // reaches is MAX_NG + ceil(MAX_NG/32) - 1 = 96 + 3 - 1 = 98 at
    // MAX_NG = 96, which fits 7 bits (max 127).  Same NUMBER, different
    // derivation — which is exactly why it had to be re-derived rather than
    // scaled.  7 bits is also what makes cfg_ng = 97 the arithmetic cliff
    // the envelope $fatal below catches.
    // ------------------------------------------------------------------
    logic [6:0]       g_cnt;
    logic [ROW_W-1:0] row_in;        // row currently streaming in
    logic             bank_sel;      // bank being FILLED
    // x_mem line of the beat being accepted: the group index, one per
    // weight beat, PLUS 48 under XBANK (SR12, B17.2 — the bank is its reset
    // VALUE; the accumulator index is g_cnt, see stage 0).  It is a register
    // rather than a slice of g_cnt on purpose — x_mem's address must stay a
    // bare flop output, with no mux in front of the LUTRAM (the waived
    // xline_q cone).
    logic [6:0]       x_line;

    // Scale beats this row needs (NSB).  The wire format is one flat array
    // of cfg_ng uint16 scales in GROUP order, 32 per beat, tail zeroed, so
    // NSB = ceil(cfg_ng/32) == w4a8_ref.row_beats()'s ceil((K/g)/32), which
    // is the law here: 1..3 beats at MAX_NG = 96.  The 9B row shapes are
    // K in {4096, 8192, 12288} -> cfg_ng in {32, 64, 96} -> NSB in {1, 2, 3}
    // and scale_beat_idx in {0, 1, 2}, so BOTH still fit two bits (spec
    // 4.5).  The arithmetic is 7-bit and EXACTLY WIDE ENOUGH: cfg_ng + 31
    // fits for every legal cfg_ng <= 96 (127) and WRAPS at cfg_ng = 97,
    // which is the cliff the envelope $fatal below names.
    // (G3.3 deleted `ng7 = {1'b0, cfg_ng}`: cfg_ng is 7 bits itself now.)
    wire [1:0]  n_scale_beats = 2'((cfg_ng + 7'd31) >> 5);

    wire [6:0]  last_scale_g = cfg_ng + {5'd0, n_scale_beats} - 7'd1;

    wire        is_scale_beat  = (g_cnt >= cfg_ng);
    wire        is_last_scale  = (g_cnt == last_scale_g);
    // which 32-scale slice of the row this beat carries (0, 1 or 2)
    wire [1:0]  scale_beat_idx = 2'(g_cnt - cfg_ng);

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
    wire row_start_blocked = (g_cnt == 7'd0) && (rowq >= 3'(ODEPTH - 1));

    assign s_ready = busy && !row_start_blocked && !scale_blocked;
    wire beat_fire = s_valid && s_ready;
    wire row_push  = beat_fire && is_last_scale;

    // ------------------------------------------------------------------
    // Stage 0: latch beat + read x line (registered for timing)
    // ------------------------------------------------------------------
    logic [511:0] beat_q;
    logic [1023:0] xline_q;
    logic          v0_q;            // weight-beat valid in stage 0
    logic [6:0]    g_q;             // group index of the beat (0..NG-1 <= 95)
    logic          b_q;             // bank select traveling WITH the beat
                                    // (bank_sel flips at the scale beat while
                                    //  this row's last groups are in flight)

    // NOTE (timing): the x_mem address is a bare register (x_line, == g_cnt
    // + 48*XBANK),
    // so the ADDRESS path carries no mux at all.  The CE cone is
    // `beat_fire && !is_scale_beat`, and the compares behind it
    // (is_scale_beat / is_last_scale / row_start_blocked) are 7-bit against
    // csr_static-derived operands that are false-pathed into ui_clk
    // (synth/constraints/fable5_cdc.xdc:14).
    always_ff @(posedge clk) begin
        if (!rstn) begin
            v0_q <= 1'b0;
        end else begin
            v0_q <= beat_fire && !is_scale_beat;
            if (beat_fire && !is_scale_beat) begin
                beat_q <= s_data;
                // SR12: the ACCUMULATOR index is the group count, NOT the x
                // line — under XBANK x_line runs 48.. while the group runs
                // 0..ng-1.  g_cnt equals x_line on every weight beat when
                // XBANK = 0 (both reset at start and row end, both +1 per
                // weight beat), so bank-0 behaviour is unchanged.
                g_q    <= g_cnt;
                b_q    <= bank_sel;
                for (int b = 0; b < 32; b++)
                    xline_q[b*32 +: 32] <= x_mem[b][x_line];
            end
        end
    end

    // ------------------------------------------------------------------
    // Stage 1: 128 products w*x8 (12b signed).  |w| <= 8 (a sign-extended
    // nibble) and |x8| <= 128, so the product is in [-1016, 1024] and 12
    // bits signed (-2048..2047) is exact with a bit to spare.  G3.3 took
    // this back from the 16 b the W8 lane array needed; there is no illegal
    // weight CODE to defend against here, because every 4-bit pattern is a
    // legal nibble.
    // ------------------------------------------------------------------
    logic signed [G-1:0][11:0] prod_q;
    logic               v1_q;
    logic [6:0]         g1_q;
    logic               b1_q;

    always_ff @(posedge clk) begin
        if (!rstn) v1_q <= 1'b0;
        else begin
            v1_q  <= v0_q;
            g1_q  <= g_q;
            b1_q  <= b_q;
            if (v0_q) begin
                for (int k = 0; k < G; k++) begin
                    logic signed [3:0] wn;
                    logic signed [7:0] xv;
                    // low nibble = even k, high nibble = odd k (pack_w4)
                    wn = (k % 2 == 0) ? signed'(beat_q[(k/2)*8 +: 4])
                                      : signed'(beat_q[(k/2)*8+4 +: 4]);
                    xv = signed'(xline_q[k*8 +: 8]);
                    prod_q[k] <= 12'(wn * xv);
                end
            end
        end
    end

    // ------------------------------------------------------------------
    // Stages 2-5: pipelined adder tree, max 2 add-levels per stage
    // (re-staged for 300 MHz timing: build_009 WNS -0.68 was here)
    // 128 -> 64 (13b) -> 16 (15b) -> 4 (17b) -> 1 (18b)
    // Widths are the W4 law (header table): every stage is EXACT, so each
    // is one bit wider than the worst sum it can hold.  G3.3 took all four
    // back from the W8 envelope (16/18/20/21) they carried for build_035.
    // ------------------------------------------------------------------
    logic signed [63:0][12:0] sum64_q;
    logic               v2_q;
    logic [6:0]         g2_q;
    logic               b2_q;
    always_ff @(posedge clk) begin
        if (!rstn) v2_q <= 1'b0;
        else begin
            v2_q  <= v1_q;
            g2_q  <= g1_q;
            b2_q  <= b1_q;
            if (v1_q)
                for (int i = 0; i < 64; i++)
                    sum64_q[i] <= 13'(signed'(prod_q[2*i])) + 13'(signed'(prod_q[2*i+1]));
        end
    end

    logic signed [15:0][14:0] sum16_q;
    logic               v3_q;
    logic [6:0]         g3_q;
    logic               b3_q;
    always_ff @(posedge clk) begin
        if (!rstn) v3_q <= 1'b0;
        else begin
            v3_q  <= v2_q;
            g3_q  <= g2_q;
            b3_q  <= b2_q;
            if (v2_q)
                for (int i = 0; i < 16; i++)
                    sum16_q[i] <= 15'(signed'(sum64_q[4*i]))   + 15'(signed'(sum64_q[4*i+1]))
                                + 15'(signed'(sum64_q[4*i+2])) + 15'(signed'(sum64_q[4*i+3]));
        end
    end

    // sum4_q[i] is a 32-LANE sum: 32 * 8 * 128 = 32768, so 17 b signed.
    logic signed [3:0][16:0] sum4_q;
    logic               v4_q;
    logic [6:0]         g4_q;
    logic               b4_q;
    always_ff @(posedge clk) begin
        if (!rstn) v4_q <= 1'b0;
        else begin
            v4_q  <= v3_q;
            g4_q  <= g3_q;
            b4_q  <= b3_q;
            if (v3_q)
                for (int i = 0; i < 4; i++)
                    sum4_q[i] <= 17'(signed'(sum16_q[4*i]))   + 17'(signed'(sum16_q[4*i+1]))
                               + 17'(signed'(sum16_q[4*i+2])) + 17'(signed'(sum16_q[4*i+3]));
        end
    end

    // Final tree stage, TAPPED AT THE MIDPOINT: sum4_q[0..1] are k=0..63,
    // sum4_q[2..3] are k=64..127.  Same two add-levels as a single-sum
    // final stage, so the stage-5 critical path is unchanged, and the
    // retire recovers the 19 b group sum as m*lo + m*hi (exact, no
    // truncation).  18 b = 64 * 8 * 128 = 65536.
    logic signed [17:0] acc_lo_q, acc_hi_q;
    logic               v5_q;
    logic [6:0]         g5_q;
    logic               b5_q;
    always_ff @(posedge clk) begin
        if (!rstn) v5_q <= 1'b0;
        else begin
            v5_q  <= v4_q;
            g5_q  <= g4_q;
            b5_q  <= b4_q;
            if (v4_q) begin
                acc_lo_q <= 18'(signed'(sum4_q[0])) + 18'(signed'(sum4_q[1]));
                acc_hi_q <= 18'(signed'(sum4_q[2])) + 18'(signed'(sum4_q[3]));
            end
        end
    end

    // ------------------------------------------------------------------
    // Accumulator banks (ping-pong, 2-deep): written by tree output, read
    // by the retire walk.  One entry per group, both 64-wide halves,
    // MAX_NG deep.
    // ------------------------------------------------------------------
    logic signed [17:0] acc_bank_lo [2][MAX_NG];
    logic signed [17:0] acc_bank_hi [2][MAX_NG];
    always_ff @(posedge clk) begin
        if (v5_q) acc_bank_lo[b5_q][g5_q] <= acc_lo_q;
        if (v5_q) acc_bank_hi[b5_q][g5_q] <= acc_hi_q;
    end

    // SINGLE scale bank (S2): entries [0..cfg_ng-1] are read, and the row's
    // 1..ceil(MAX_NG/32) scale beats fill [0..NSCAL-1].  Ownership is
    // serialized by sc_hold, NOT duplicated.
    logic [NSCAL-1:0][15:0] scales_q;

    // ------------------------------------------------------------------
    // Row/bank control
    // ------------------------------------------------------------------
    logic [ROW_W-1:0] rows_done_in;
    always_ff @(posedge clk) begin
        if (!rstn) begin
            g_cnt     <= '0;
            x_line    <= '0;
            row_in    <= '0;
            bank_sel  <= 1'b0;
            busy      <= 1'b0;
            rows_done_in <= '0;
        end else begin
            if (start) begin
                g_cnt    <= '0;
                x_line   <= cfg_xbank ? XB_LINE : 7'd0;   // SR12: B17.2
                row_in   <= cfg_rbank ? RB_ROW : '0;      // SR12: B17.2
                bank_sel <= 1'b0;
                busy     <= 1'b1;
                rows_done_in <= '0;
            end
            if (beat_fire) begin
                if (is_scale_beat) begin
                    // 32 scales/beat, in group order: beat b covers
                    // scales_q[32b .. 32b+31] (b = 0..2 at MAX_NG = 96).
                    for (int i = 0; i < 32; i++)
                        scales_q[{scale_beat_idx, 5'(i)}] <= s_data[i*16 +: 16];
                    if (is_last_scale) begin
                        bank_sel     <= ~bank_sel;
                        g_cnt        <= '0;
                        x_line       <= cfg_xbank ? XB_LINE : 7'd0;   // SR12
                        row_in       <= row_in + 1'b1;
                        rows_done_in <= rows_done_in + 1'b1;
                        if (rows_done_in + 1'b1 == cfg_nrows)
                            busy <= 1'b0;  // stop accepting; retire finishes
                    end else begin
                        g_cnt <= g_cnt + 1'b1;
                    end
                end else begin
                    g_cnt <= g_cnt + 1'b1;
                    // one group per weight beat: x_line = g_cnt + 48*XBANK
                    // on every weight beat (SR12, B17.2), so it equals
                    // g_cnt only at XBANK 0.  It is a separate register to
                    // keep the LUTRAM address a bare flop output.  g_q (the
                    // accumulator index) takes g_cnt — do NOT source it from
                    // x_line: under XBANK that writes accumulator entries
                    // 48.. which the retire walk (0..ng-1) never reads, and
                    // every XBANK y32 comes out 0 (n1210).
                    x_line <= x_line + 7'd1;
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
    logic [6:0]       r_g;
    logic [ROW_W-1:0] r_row;
    logic             r_bank;

    assign r_last = r_active && (r_g + 7'd1 == cfg_ng);
    wire   pd_rdy = pd_valid && (pd_wait == 3'd0);
    // take the descriptor when the walk is idle, or on the very cycle the
    // current row issues its last index (back-to-back rows)
    wire   r_take = pd_rdy && (!r_active || r_last);

    // Scale operand: ONE per group.  p += m*lo + m*hi == m*(lo+hi) ==
    // m*acc_i, exactly -- which is why a single scale read feeds both DSPs.
    // (Until G3.3 this was a cfg_g64-selected PAIR (2i, 2i+1); mode 1 is
    // gone and so is the select.)
    // NOTE (timing): this is the NSCAL:1 scales mux -- r_g feeds it
    // directly, exactly as d_g did.  Do not add logic between them.
    wire [6:0] sc_idx = r_g;

    // M0: registered bank/scale reads feeding the MAC DSPs (timing)
    logic signed [17:0] mac_lo_q, mac_hi_q;
    logic [15:0]        mac_m_q;
    logic               mac_v_q, mac_first_q, mac_last_q;
    logic [ROW_W-1:0]   mac_row_q;
    // M1: the two products (17b signed scale x 18b signed half-sum).  Still
    // ONE DSP48E2 each: the 27x18 signed multiplier takes the 18 b operand
    // on its 27 b port and {1'b0, m} on the 18 b port.
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
                pd_wait  <= (cfg_ng >= 7'd5) ? 3'd0 : 3'(7'd5 - cfg_ng);
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
                r_g <= r_g + 7'd1;
            end

            // ---- M0: bank + scale read, tagged
            mac_v_q <= r_active;
            if (r_active) begin
                mac_lo_q    <= acc_bank_lo[r_bank][r_g];
                mac_hi_q    <= acc_bank_hi[r_bank][r_g];
                mac_m_q     <= scales_q[sc_idx];
                mac_first_q <= (r_g == 7'd0);
                mac_last_q  <= (r_g + 7'd1 == cfg_ng);
                mac_row_q   <= r_row;
            end

            // ---- M1: the two 17x18 products
            pv_q <= mac_v_q;
            if (mac_v_q) begin
                pa_q      <= $signed({1'b0, mac_m_q}) * mac_lo_q;
                pb_q      <= $signed({1'b0, mac_m_q}) * mac_hi_q;
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

`ifndef SYNTHESIS
    // ENVELOPE: cfg_ng must be 1..MAX_NG.  Above MAX_NG the activation
    // lines, the accumulator banks and the scale buffer all run out — and
    // n_scale_beats itself WRAPS TO ZERO one past MAX_NG, because the 7-bit
    // (ng7 + 31) it is computed from overflows at cfg_ng = 97.  A zero count
    // makes last_scale_g == cfg_ng-1, i.e. the row's final WEIGHT beat
    // silently becomes its "last scale beat": the descriptor is pushed with
    // scales that were never written and the beat stream desyncs for good.
    // Same bug class as vecnorm_unit's nlog2 guard; fail loudly instead.
    // (RE-DERIVED at G3.3.  The old cliff was cfg_ng = 49 and it came from
    // mode 1's ceil(cfg_ng/16), which needed a third bit there; mode 1 is
    // gone, so the cliff is now the 7-bit add itself.)
    always_ff @(posedge clk) begin
        if (rstn && start && ((cfg_ng == 7'd0) || (cfg_ng > 7'(MAX_NG))))
            $fatal(1, "matvec_engine: cfg_ng %0d unsupported (must be 1..%0d)",
                   cfg_ng, MAX_NG);
        // SR12 (SEQ_ISA v2.3 B17.2) BANK LEGALITY — the sim-only twin of
        // ref/seq_format.validate's rule (on silicon it is validator-side
        // only): an XBANK stream reads x lines 48 .. 48 + ng - 1, which must
        // stay inside the 96 (ng <= 48, K <= 6144); an RBANK stream tags
        // rows 2048 .. 2048 + nrows - 1, which must stay inside the 4096-row
        // RES (nrows <= 2048) — past it the 12-bit RES address would wrap
        // onto bank 0 silently.
        if (rstn && start && cfg_xbank
            && ((32'(XB_LINE) + 32'(cfg_ng) - 32'd1) > 32'(MAX_NG - 1)))
            $fatal(1, "matvec_engine: XBANK with cfg_ng %0d: x lines %0d..%0d exceed line %0d",
                   cfg_ng, XB_LINE, 32'(XB_LINE) + 32'(cfg_ng) - 32'd1,
                   MAX_NG - 1);
        if (rstn && start && cfg_rbank
            && ((32'(RB_ROW) + 32'(cfg_nrows)) > 32'd4096))
            $fatal(1, "matvec_engine: RBANK with cfg_nrows %0d: rows %0d.. exceed row 4095",
                   cfg_nrows, RB_ROW);
    end
`endif

endmodule

`default_nettype wire
