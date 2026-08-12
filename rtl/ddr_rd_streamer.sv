// ddr_rd_streamer: AXI4 read master streaming a contiguous weight image
// from DDR4 into the matvec engine. 512-bit data path, INC bursts of up to
// 64 beats (4 KiB, never crossing a 4 KiB boundary because bursts are
// issued 4KiB-aligned after the first), up to 4 outstanding.
//
// Performance counters (for the charter's sustained-bandwidth report):
// beats received and cycles elapsed between start and last beat.
//
// Lint-clean under -Wall; single clock domain (the DDR channel's ui_clk).

`timescale 1ns/1ps
`default_nettype none

module ddr_rd_streamer #(
    parameter int ADDR_W = 34          // 16 GiB max
) (
    input  wire               clk,
    input  wire               rstn,

    // config (stable while busy) + control
    input  wire [ADDR_W-1:0]  cfg_base,        // 64B-aligned
    input  wire [31:0]        cfg_beats,       // total 64B beats to fetch
    input  wire               start,           // pulse
    output logic              busy,
    output logic              done,

    // perf counters (valid when done)
    output logic [47:0]       perf_cycles,
    output logic [31:0]       perf_beats,

    // AXI4 read address channel
    output logic [ADDR_W-1:0] m_araddr,
    output logic [7:0]        m_arlen,
    output logic [2:0]        m_arsize,
    output logic [1:0]        m_arburst,
    output logic              m_arvalid,
    input  wire               m_arready,

    // AXI4 read data channel
    input  wire [511:0]       m_rdata,
    input  wire [1:0]         m_rresp,
    input  wire               m_rlast,
    input  wire               m_rvalid,
    output logic              m_rready,
    output logic              err_rresp,       // sticky: any non-OKAY rresp

    // beat stream out (through a small skid FIFO)
    output logic              s_valid,
    input  wire               s_ready,
    output logic [511:0]      s_data
);

    localparam int MAX_OUTSTANDING = 4;
    localparam int BURST_BEATS = 64;   // 4 KiB

    assign m_arsize  = 3'b110;         // 64 bytes
    assign m_arburst = 2'b01;          // INCR

    // ------------------------------------------------------------------
    // FIFO: 256 beats deep (BRAM-sized) so MAX_OUTSTANDING full bursts fit.
    // AR issue is credited against FIFO space, so RVALID is never
    // backpressured for long (rready deasserts only when FIFO truly full).
    // ------------------------------------------------------------------
    localparam int FD = 256;           // power of two
    logic [511:0] fifo [FD];
    logic [8:0] f_wr, f_rd;            // one extra bit
    wire  [8:0] f_count = f_wr - f_rd;
    wire f_full  = (f_count == 9'(FD));
    wire f_empty = (f_count == 9'd0);

    assign m_rready = !f_full;
    assign s_valid  = !f_empty;
    assign s_data   = fifo[f_rd[7:0]];

    always_ff @(posedge clk) begin
        if (!rstn) begin
            f_wr <= '0;
            f_rd <= '0;
            err_rresp <= 1'b0;
        end else begin
            if (start) begin
                f_wr <= '0;
                f_rd <= '0;
                err_rresp <= 1'b0;
            end
            if (m_rvalid && m_rready) begin
                fifo[f_wr[7:0]] <= m_rdata;
                f_wr <= f_wr + 1'b1;
                if (m_rresp != 2'b00) err_rresp <= 1'b1;
            end
            if (s_valid && s_ready)
                f_rd <= f_rd + 1'b1;
        end
    end

    // ------------------------------------------------------------------
    // AR issue: credit-based (outstanding bursts + FIFO headroom)
    // ------------------------------------------------------------------
    logic [31:0] beats_to_req;       // beats not yet requested
    logic [31:0] beats_rcvd;
    logic [2:0]  outstanding;        // bursts in flight
    // committed == f_count + beats_inflight (invariant): a push (r_beat)
    // moves a beat from inflight to the FIFO, so the sum only changes on
    // AR issue (+len+1) and FIFO pop (-1). Bounded by FD by construction,
    // so the issue credit check needs one 10-bit add/compare instead of
    // the 32-bit f_count+inflight+len chain (violated-path family, 018).
    logic [9:0]  committed;

    // low 8 bits suffice: mod-256 decrement equals the full-width one
    // truncated, and the tail case only reads it when beats_to_req < 64
    wire [7:0] next_len8 = (beats_to_req >= 32'(BURST_BEATS))
                           ? 8'(BURST_BEATS - 1)
                           : 8'(beats_to_req[7:0] - 8'd1);

    // issue when: work left, outstanding slots free, and FIFO can absorb
    // everything already in flight plus this burst.
    wire can_issue = busy && (beats_to_req != 0)
                     && (outstanding < 3'(MAX_OUTSTANDING))
                     && ((committed + 10'(next_len8) + 10'd1) <= 10'(FD));

    wire ar_issue   = !m_arvalid && can_issue;
    wire ar_done    = m_arvalid && m_arready;
    wire r_beat     = m_rvalid && m_rready;
    wire burst_done = r_beat && m_rlast;

    always_ff @(posedge clk) begin
        if (!rstn) begin
            m_arvalid <= 1'b0;
            busy      <= 1'b0;
            outstanding <= '0;
            committed <= '0;
        end else if (start) begin
            m_araddr     <= cfg_base;
            beats_to_req <= cfg_beats;
            beats_rcvd   <= '0;
            outstanding  <= '0;
            committed    <= '0;
            busy         <= 1'b1;
            m_arvalid    <= 1'b0;
        end else begin
            if (ar_done) begin
                m_arvalid <= 1'b0;
                m_araddr  <= m_araddr + ADDR_W'(34'(m_arlen) + 34'd1) * 64;
                beats_to_req <= beats_to_req - (32'(m_arlen) + 32'd1);
            end else if (ar_issue) begin
                m_arlen   <= next_len8;
                m_arvalid <= 1'b1;
            end

            outstanding <= outstanding + (ar_issue ? 3'd1 : 3'd0)
                                       - (burst_done ? 3'd1 : 3'd0);
            committed <= committed
                         + (ar_issue ? 10'(next_len8) + 10'd1 : 10'd0)
                         - ((s_valid && s_ready) ? 10'd1 : 10'd0);
            if (r_beat) beats_rcvd <= beats_rcvd + 1'b1;

            if (busy && r_beat && (beats_rcvd + 1'b1 == cfg_beats))
                busy <= 1'b0;
        end
    end

    // ------------------------------------------------------------------
    // perf counters: cycles from start until the last beat received
    // ------------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (!rstn) begin
            perf_cycles <= '0;
            perf_beats  <= '0;
        end else begin
            if (start) begin
                perf_cycles <= '0;
                perf_beats  <= '0;
            end else if (busy) begin
                perf_cycles <= perf_cycles + 1'b1;
            end
            if (m_rvalid && m_rready && busy)
                perf_beats <= perf_beats + 1'b1;
        end
    end

    assign done = !busy && (perf_beats != 0) && (perf_beats == cfg_beats);

endmodule

`default_nettype wire
