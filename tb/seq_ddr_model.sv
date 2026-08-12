// seq_ddr_model — simulation-only AXI4 read-only slave model of one DDR4
// channel, 128-bit data. Stands in for the MIG/DDR4 controller so that
// testbenches can exercise the sequencer's outstanding-burst logic against a
// realistic first-word latency without a full memory-controller model.
//
// NOT synthesized (it lives in tb/), but written as plain synthesizable RTL
// (always_ff / always_comb, no delays, no `--timing` constructs) so it lints
// clean under:  verilator --lint-only -Wall --timing tb/seq_ddr_model.sv
//
// Backing store
// -------------
//  MEM_WORDS x 128-bit words indexed by araddr[4 +: $clog2(MEM_WORDS)], i.e.
//  araddr[19:4] at the default MEM_WORDS = 65536. That is a 1 MB window and
//  THE MODEL DELIBERATELY ALIASES EVERYTHING ABOVE BIT 19: address
//  0x0_0010_0000 reads the same word as 0x0. Testbenches that want distinct
//  data at widely-separated addresses must keep them inside the 1 MB window
//  (or raise MEM_WORDS). The word index also wraps within a burst if a burst
//  runs off the top of the window.
//
//  MEMFILE, if non-empty, is loaded with $readmemh at time 0. The file holds
//  one 128-bit value (32 hex digits) per line and may use @address
//  directives for sparse loading; addresses in the file are WORD indices
//  into mem[], i.e. byte address >> 4.
//
// Timing model
// ------------
//  AR is accepted whenever the depth-4 request queue has room, so up to 4
//  bursts can be outstanding while an earlier one drains.
//
//  Each queued burst gets its OWN LAT countdown, started the cycle its AR is
//  accepted, so outstanding bursts genuinely overlap the access latency —
//  the model must never be the fetch bottleneck. Data still returns strictly
//  in order: a burst whose countdown expires early simply waits its turn at
//  the head of the queue, and once at the head it streams immediately with
//  no arbitration bubble. Beats are returned one per cycle whenever RREADY
//  is high, RLAST on the last beat of each burst.
//
//  So with ARs accepted on cycles 0..3, LAT=32 and ARLEN=15, the first beat
//  appears on cycle 33 and all 64 beats then stream back to back.
//
//  Protocol assumptions are checked with $fatal: INCR bursts only
//  (ARBURST == 2'b01), 16-byte beats only (ARSIZE == 3'b100), and no burst
//  may cross a 4 KB boundary.

`timescale 1ns/1ps
`default_nettype none

module seq_ddr_model #(
    parameter int    ADDR_W    = 34,
    parameter int    LAT       = 32,
    parameter int    MEM_WORDS = 65536,
    parameter string MEMFILE   = ""
) (
    input  wire                aclk,
    input  wire                aresetn,

    // ---- AXI4 read address channel ----
    /* verilator lint_off UNUSEDSIGNAL */
    // only araddr[4 +: WIDX] selects a word; araddr[3:0] is the (always
    // zero) intra-beat offset and the bits above the window are aliased
    // away — see header. araddr[11:4] is additionally used by the 4 KB
    // boundary check.
    input  wire [ADDR_W-1:0]   araddr,
    /* verilator lint_on UNUSEDSIGNAL */
    input  wire [7:0]          arlen,
    input  wire [2:0]          arsize,
    input  wire [1:0]          arburst,
    input  wire                arvalid,
    output logic               arready,

    // ---- AXI4 read data channel ----
    output logic [127:0]       rdata,
    output logic [1:0]         rresp,
    output logic               rlast,
    output logic               rvalid,
    input  wire                rready,

    // ---- instrumentation ----
    output logic [31:0]        n_beats    // beats accepted by the master
);

    localparam int WIDX = $clog2(MEM_WORDS);   // 16 at MEM_WORDS = 65536
    localparam int QD   = 4;                   // outstanding bursts

    // ---------------------------------------------------------------------
    // backing store
    // ---------------------------------------------------------------------
    logic [127:0] mem [MEM_WORDS];

    initial begin
        if (MEMFILE != "") $readmemh(MEMFILE, mem);
    end

    // ---------------------------------------------------------------------
    // AR queue (depth QD), returned strictly in order
    // ---------------------------------------------------------------------
    logic [WIDX-1:0] q_word [QD];
    logic [7:0]      q_len  [QD];
    logic [31:0]     q_dn   [QD];   // per-burst latency countdown, 0 = ready
    logic [1:0]      q_wp, q_rp;
    logic [2:0]      q_cnt;                    // 0..QD

    logic q_push, q_pop;

    assign arready = aresetn && (q_cnt != 3'(QD));
    assign q_push  = arvalid && arready;

    // ---------------------------------------------------------------------
    // burst return: the head entry streams as soon as its own countdown
    // (started at AR acceptance) has expired. No arbitration state, so
    // consecutive ready bursts stream back to back with no bubble.
    // ---------------------------------------------------------------------
    logic            head_ready;
    logic [7:0]      cur_beat;
    logic [WIDX-1:0] head_word;

    assign head_ready = (q_cnt != '0) && (q_dn[q_rp] == '0);
    assign head_word  = q_word[q_rp] + WIDX'(cur_beat);

    assign rvalid = head_ready;
    assign rlast  = head_ready && (cur_beat == q_len[q_rp]);
    assign rresp  = 2'b00;                     // OKAY, always
    assign rdata  = mem[head_word];

    assign q_pop  = rvalid && rready && rlast;

    // 4 KB boundary check: araddr[11:4] is the 16-byte word index inside the
    // page, so the last word of the burst must still be <= 255.
    logic [8:0] last_word_in_page;
    assign last_word_in_page = {1'b0, araddr[11:4]} + {1'b0, arlen};

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            q_wp     <= '0;
            q_rp     <= '0;
            q_cnt    <= '0;
            cur_beat <= '0;
            n_beats  <= '0;
            for (int i = 0; i < QD; i++) q_dn[i] <= '0;
        end else begin
            // ---------------- per-burst latency countdowns ----------------
            // Runs before the push below so a freshly-accepted AR gets the
            // full LAT (the later nonblocking assignment wins).
            for (int i = 0; i < QD; i++)
                if (q_dn[i] != '0) q_dn[i] <= q_dn[i] - 32'd1;

            // ---------------- AR acceptance ----------------
            if (q_push) begin
                if (arburst != 2'b01)
                    $fatal(1, "seq_ddr_model: ARBURST=%b, only INCR (01) supported", arburst);
                if (arsize != 3'b100)
                    $fatal(1, "seq_ddr_model: ARSIZE=%b, only 16B (100) supported", arsize);
                if (last_word_in_page > 9'd255)
                    $fatal(1, "seq_ddr_model: burst crosses 4 KB boundary (araddr=%h arlen=%0d)",
                           araddr, arlen);
                q_word[q_wp] <= araddr[4 +: WIDX];
                q_len[q_wp]  <= arlen;
                q_dn[q_wp]   <= 32'(LAT);      // this burst's own countdown
                q_wp         <= q_wp + 2'd1;
            end
            if (q_pop) q_rp <= q_rp + 2'd1;

            case ({q_push, q_pop})
                2'b10:   q_cnt <= q_cnt + 3'd1;
                2'b01:   q_cnt <= q_cnt - 3'd1;
                default: /* no change */ ;
            endcase

            // ---------------- burst return ----------------
            if (rvalid && rready) begin
                n_beats <= n_beats + 32'd1;
                // rlast pops the queue (above); restart the beat counter for
                // the next burst, which may already be ready to stream.
                cur_beat <= rlast ? 8'd0 : (cur_beat + 8'd1);
            end
        end
    end

endmodule

`default_nettype wire
