// state_dma: the layer's state-transfer engine — one 512-bit AXI4
// read/write master on `aclk` that moves ONE block at a time between DDR
// and a cache slot (spec docs/superpowers/specs/2026-09-04-qwen35-9b-state-
// spill-design.md §4; SEQ_ISA v2.1 B15.1).
//
// ONE RESPONSIBILITY: the transfer.  The caches, the two lanes, the fences
// and the CSRs live in rtl/layer_chan.sv, which owns this instance, muxes
// the owning slot's ports behind `slot_*` and computes `xfer_addr` from
// SB_<kind> and the block index.  Nothing here knows what a slot IS.
//
// THE TRANSFER SHAPE
//   DN   4096 rows x 2048 b   = 4 beats/row, 1 MiB   (a whole layer, A1.1)
//   KV   TCNT rows x 2048 b   = 4 beats/row, then a SECOND phase of
//        ceil(TCNT/64) beats of exponent bytes at +STATE_KV_EXP_OFF (1 MiB).
//        TCNT = 0 moves NOTHING and completes at once (B15.1).
//   CV   8192 rows x 16 B     = 4 rows/beat, 128 KiB.  The 16-B DDR row is
//        {16'b0, state[47:0], weights[63:0]}; layer_chan splits it across
//        the slot's two memories (spec A1.2), so this block only ever
//        presents/consumes slot_wdata[127:0] for kind CV.
//
// ISSUE.  INC bursts of at most 16 beats (1 KiB), at most MAX_OUT in
// flight, read data buffered in a FIFO_D-beat FIFO like ddr_rd_streamer's.
// Every phase base is at least 64 KiB aligned (SB_<kind> is in 64 KiB units
// and every block stride is >= 128 KiB), so a 1 KiB burst can never cross a
// 4 KiB boundary.
//
// COMPLETION.  A LOAD is complete when the last row has been written into
// the slot.  A STORE is complete when every write response has been
// collected — the "bw_idle" discipline seq_movers uses for its burst writes
// (rtl/seq_movers.sv:62-66): AW count == B count, not "the last W beat
// went out".  `xfer_err` latches any SLVERR/DECERR on either channel and
// holds it until the next `xfer_go`; layer_chan turns it into E_DMA_AXI.
//
// SLOT TIMING.  `slot_rdata` is valid 2 cycles after the `slot_addr` PORT
// carries the address (the slot's URAM CQ plus layer_chan's output
// register), so the store side issues addresses 3 edges ahead of the edge
// that consumes them: the address register, then two memory stages.

`timescale 1ns/1ps
`default_nettype none

module state_dma #(
    parameter int MAX_OUT = 8,             // bursts in flight
    parameter int FIFO_D  = 256            // beats, like ddr_rd_streamer
) (
    input  wire         aclk,
    input  wire         aresetn,
    // one transfer at a time, from layer_chan's DMA lane
    input  wire         xfer_go,           // pulse; fields sampled with it
    input  wire         xfer_store,        // 0 = SLD (DDR -> slot), 1 = SST (slot -> DDR)
    input  wire [1:0]   xfer_kind,         // 0 DN, 1 KV, 2 CV
    input  wire [33:0]  xfer_addr,         // block base, computed by layer_chan
    input  wire [13:0]  xfer_rows,         // rows to move: DN 4096, CV 8192, KV TCNT (0..4096)
    output logic        xfer_busy,
    output logic        xfer_done,         // one-cycle pulse, after the last B response on a store
    output logic        xfer_err,          // SLVERR/DECERR seen (E_DMA_AXI); sticky until the next xfer_go
    // the slot side (layer_chan muxes the owning slot's ports behind these)
    output logic [12:0] slot_addr,         // row index within the slot
    output logic [2047:0] slot_wdata,      // DN/KV row; CV: {16'b0, state[47:0], weights[63:0]} in [127:0]
    output logic [7:0]  slot_wexp,         // KV exponent byte for slot_addr (side-array phase)
    output logic        slot_we,
    output logic        slot_wexp_we,
    input  wire [2047:0] slot_rdata,       // valid 2 cycles after slot_addr (the URAM's registered read)
    input  wire [7:0]   slot_rexp,
    // AXI4 master, 512-bit; size/burst/id are tied constant in layer_chan_ipi.v
    output logic [33:0] m_axis_awaddr, output logic [7:0] m_axis_awlen, output logic m_axis_awvalid, input wire m_axis_awready,
    output logic [511:0] m_axis_wdata,  output logic [63:0] m_axis_wstrb, output logic m_axis_wlast, output logic m_axis_wvalid, input wire m_axis_wready,
    input  wire [1:0]   m_axis_bresp,   input  wire m_axis_bvalid, output logic m_axis_bready,
    output logic [33:0] m_axis_araddr, output logic [7:0] m_axis_arlen, output logic m_axis_arvalid, input wire m_axis_arready,
    input  wire [511:0] m_axis_rdata,  input  wire [1:0] m_axis_rresp, input wire m_axis_rlast, input wire m_axis_rvalid, output logic m_axis_rready
);
    localparam logic [1:0]  KIND_CV    = 2'd2;
    // B15.1: the KV exponent side array sits 1 MiB into the 2 MiB block.
    localparam logic [33:0] KV_EXP_OFF = 34'h0_0010_0000;
    localparam int FW = $clog2(FIFO_D);

    // ==================================================================
    // the sampled transfer, and the phase derived from it
    // ==================================================================
    logic        x_store;
    logic [1:0]  x_kind;
    logic [33:0] x_addr;
    logic [13:0] x_rows;
    logic        run;                       // a transfer is in progress
    logic        ph_exp;                    // phase 1 = the KV exponent array
    logic        err_q;

    // 14 bits: a CV transfer is 8192 rows, which a 13-bit counter cannot
    // hold — it worked only because the compare wrapped at exactly CVD
    // (fix round 1, M1).
    logic [13:0] ph_rows;                   // slot rows in this phase

    // beats a phase costs, given the kind and which phase it is
    function automatic logic [15:0] beats_of(input logic [1:0] k,
                                             input logic e,
                                             input logic [13:0] rows);
        logic [15:0] r16;
        r16 = 16'(rows);
        if (e)                    beats_of = (r16 + 16'd63) >> 6;
        else if (k == KIND_CV)    beats_of = (r16 + 16'd3) >> 2;
        else                      beats_of = r16 << 2;
    endfunction

    // ==================================================================
    // burst issue (AR on a load, AW on a store) — one path, two valids
    // ==================================================================
    logic [15:0] a_left;                    // beats not yet addressed
    logic [33:0] a_addr;
    logic [4:0]  a_out;                     // bursts issued but not retired

    wire [15:0] i_burst = (a_left >= 16'd16) ? 16'd16 : a_left;
    wire [7:0]  i_len   = 8'(i_burst - 16'd1);
    wire        i_go    = run && (a_left != 16'd0) && (a_out < 5'(MAX_OUT));

    assign m_axis_araddr  = a_addr;
    assign m_axis_arlen   = i_len;
    assign m_axis_arvalid = i_go && !x_store;
    assign m_axis_awaddr  = a_addr;
    assign m_axis_awlen   = i_len;
    assign m_axis_awvalid = i_go &&  x_store;
    assign m_axis_bready  = 1'b1;

    // ==================================================================
    // the beat FIFO: AXI -> slot on a load, slot -> AXI on a store
    // ==================================================================
    logic [511:0] fmem [FIFO_D];
    logic [FW:0]  f_wp, f_rp;
    wire  [FW:0]  f_cnt   = f_wp - f_rp;
    wire          f_empty = (f_wp == f_rp);
    wire          f_full  = (f_cnt == (FW+1)'(FIFO_D));
    wire [511:0]  f_out   = fmem[f_rp[FW-1:0]];

    assign m_axis_rready = run && !x_store && !f_full;

    // ==================================================================
    // store: W channel.  Bursts are 16 beats aligned to the phase start,
    // so the last beat of a burst is w_sent[3:0] == 15 (or the phase's
    // own last beat) — no burst-length queue is needed.
    // ==================================================================
    logic [15:0] w_left;                    // beats not yet handed to W
    logic [15:0] w_sent;                    // beats handed to W this phase
    assign m_axis_wvalid = run && x_store && (w_left != 16'd0) && !f_empty;
    assign m_axis_wdata  = f_out;
    assign m_axis_wstrb  = '1;
    assign m_axis_wlast  = (w_sent[3:0] == 4'hF) || (w_left == 16'd1);

    // ==================================================================
    // load: row assembly.  DN/KV take four beats into one 2048-bit row;
    // CV takes one beat into four 128-bit rows; the exponent phase takes
    // one beat into 64 bytes.
    // ==================================================================
    logic [1535:0] rowbuf;                  // beats 0..2 of the row in flight
    logic [1:0]    l_sub;                   // beat within the row (DN/KV)
    logic [511:0]  bbuf;                    // the popped beat (CV / exponents)
    logic          bbuf_v;
    logic [5:0]    l_esub;                  // byte within an exponent beat
    logic [1:0]    l_csub;                  // row within a CV beat
    logic [12:0]   srow;                    // rows written (load) into the slot

    // ==================================================================
    // store: slot read pipeline.  `rd_i` counts READ UNITS — beats for
    // DN/KV (each row is read four times, once per beat, which costs
    // nothing and needs no accumulator), rows for CV and for the exponent
    // phase (which accumulate into one beat).
    // ==================================================================
    logic [15:0]  rd_i;
    logic [15:0]  rd_units;                 // read units in this phase
    logic [2:0]   rp_v;                     // 3-deep valid shift
    logic [1:0]   rp_sub [3];
    logic [5:0]   rp_esub [3];
    logic [2:0]   rp_last;                  // last read unit of the phase
    logic [511:0] beat_acc;

    wire is_rowphase = !ph_exp && (x_kind != KIND_CV);
    wire [12:0] rd_row = is_rowphase ? 13'(rd_i >> 2) : 13'(rd_i);

    // ==================================================================
    // the engine
    // ==================================================================
    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            run <= 1'b0; ph_exp <= 1'b0; err_q <= 1'b0;
            xfer_done <= 1'b0;
            a_left <= '0; a_addr <= '0; a_out <= '0;
            w_left <= '0; w_sent <= '0;
            f_wp <= '0; f_rp <= '0;
            slot_we <= 1'b0; slot_wexp_we <= 1'b0;
            slot_addr <= '0; slot_wdata <= '0; slot_wexp <= '0;
            l_sub <= '0; l_esub <= '0; l_csub <= '0; srow <= '0;
            bbuf_v <= 1'b0;
            rd_i <= '0; rp_v <= '0; rp_last <= '0;
            ph_rows <= '0; rd_units <= '0; beat_acc <= '0;
            x_store <= 1'b0; x_kind <= '0; x_addr <= '0; x_rows <= '0;
        end else begin
            logic phase_done;
            logic last_phase;
            slot_we      <= 1'b0;
            slot_wexp_we <= 1'b0;
            xfer_done    <= 1'b0;
            phase_done   = 1'b0;

            // ---------- accept a new transfer ----------
            if (xfer_go && !run) begin
                x_store <= xfer_store;
                x_kind  <= xfer_kind;
                x_addr  <= xfer_addr;
                x_rows  <= xfer_rows;
                err_q   <= 1'b0;
                ph_exp  <= 1'b0;
                ph_rows <= xfer_rows;
                a_left  <= beats_of(xfer_kind, 1'b0, xfer_rows);
                a_addr  <= xfer_addr;
                w_left  <= beats_of(xfer_kind, 1'b0, xfer_rows);
                rd_units <= (xfer_kind == KIND_CV) ? 16'(xfer_rows)
                                                   : beats_of(xfer_kind, 1'b0,
                                                              xfer_rows);
                w_sent  <= '0; a_out <= '0;
                f_wp <= '0; f_rp <= '0;
                l_sub <= '0; l_esub <= '0; l_csub <= '0; srow <= '0;
                bbuf_v <= 1'b0; rd_i <= '0; rp_v <= '0; rp_last <= '0;
                run <= 1'b1;
                // B15.1: a zero-length transfer moves nothing and is
                // complete at once (the first KV SLD of every session).
                if (xfer_rows == 14'd0) begin
                    run       <= 1'b0;
                    xfer_done <= 1'b1;
                end
            end

            // ---------- burst issue and retirement ----------
            // ONE update of a_out: an issue and a retirement can land in the
            // same cycle, and two conditional non-blocking writes would lose
            // the increment.
            if (run) begin
                logic a_inc, a_dec;
                a_inc = i_go && ((!x_store && m_axis_arready)
                                 || (x_store && m_axis_awready));
                a_dec = (!x_store && m_axis_rvalid && m_axis_rready
                         && m_axis_rlast)
                        || (x_store && m_axis_bvalid && m_axis_bready);
                if (a_inc) begin
                    a_left <= a_left - i_burst;
                    a_addr <= a_addr + {18'b0, i_burst} * 34'd64;
                end
                if (a_inc && !a_dec)      a_out <= a_out + 5'd1;
                else if (!a_inc && a_dec) a_out <= a_out - 5'd1;
            end

            // ---------- error capture (both channels) ----------
            if (m_axis_rvalid && m_axis_rready && m_axis_rresp != 2'b00)
                err_q <= 1'b1;
            if (m_axis_bvalid && m_axis_bready && m_axis_bresp != 2'b00)
                err_q <= 1'b1;

            // ---------- LOAD: fill the FIFO, then assemble rows ----------
            if (run && !x_store) begin
                if (m_axis_rvalid && m_axis_rready) begin
                    fmem[f_wp[FW-1:0]] <= m_axis_rdata;
                    f_wp <= f_wp + 1'b1;
                end
                if (is_rowphase) begin
                    // four beats -> one 2048-bit row
                    if (!f_empty) begin
                        f_rp <= f_rp + 1'b1;
                        l_sub <= l_sub + 2'd1;
                        if (l_sub != 2'd3)
                            rowbuf[{l_sub, 9'b0}+:512] <= f_out;
                        else begin
                            slot_addr  <= srow;
                            slot_wdata <= {f_out, rowbuf};
                            slot_we    <= 1'b1;
                            srow       <= srow + 13'd1;
                            if ({1'b0, srow} + 14'd1 == ph_rows) phase_done = 1'b1;
                        end
                    end
                end else if (!bbuf_v) begin
                    if (!f_empty) begin
                        bbuf   <= f_out;
                        bbuf_v <= 1'b1;
                        f_rp   <= f_rp + 1'b1;
                        l_esub <= '0;
                        l_csub <= '0;
                    end
                end else if (ph_exp) begin
                    // one beat -> 64 exponent bytes
                    slot_addr    <= srow;
                    slot_wexp    <= bbuf[{l_esub, 3'b0}+:8];
                    slot_wexp_we <= 1'b1;
                    srow         <= srow + 13'd1;
                    l_esub       <= l_esub + 6'd1;
                    if ({1'b0, srow} + 14'd1 == ph_rows) phase_done = 1'b1;
                    else if (l_esub == 6'd63) bbuf_v <= 1'b0;
                end else begin
                    // CV: one beat -> four 16-B rows
                    slot_addr  <= srow;
                    slot_wdata <= {1920'b0, bbuf[{l_csub, 7'b0}+:128]};
                    slot_we    <= 1'b1;
                    srow       <= srow + 13'd1;
                    l_csub     <= l_csub + 2'd1;
                    if ({1'b0, srow} + 14'd1 == ph_rows) phase_done = 1'b1;
                    else if (l_csub == 2'd3) bbuf_v <= 1'b0;
                end
            end

            // ---------- STORE: read the slot into the FIFO ----------
            if (run && x_store) begin
                logic issue;
                // the address register plus two memory stages: three edges
                // between issuing an address and consuming its data.
                issue = (rd_i != rd_units) && (f_cnt < (FW+1)'(FIFO_D - 8));
                if (issue) begin
                    slot_addr <= rd_row;
                    rd_i      <= rd_i + 16'd1;
                end
                rp_v    <= {rp_v[1:0], issue};
                rp_last <= {rp_last[1:0],
                            issue && (rd_i + 16'd1 == rd_units)};
                rp_sub[0]  <= rd_i[1:0];
                rp_esub[0] <= rd_i[5:0];
                for (int i = 1; i < 3; i++) begin
                    rp_sub[i]  <= rp_sub[i-1];
                    rp_esub[i] <= rp_esub[i-1];
                end
                if (rp_v[2]) begin
                    logic [511:0] nb;
                    nb = beat_acc;
                    if (is_rowphase) begin
                        // one row read four times, one beat per read: no
                        // accumulator, and the slice is the read's own sub
                        fmem[f_wp[FW-1:0]] <= slot_rdata[{rp_sub[2], 9'b0}+:512];
                        f_wp <= f_wp + 1'b1;
                    end else if (ph_exp) begin
                        nb[{rp_esub[2], 3'b0}+:8] = slot_rexp;
                        beat_acc <= nb;
                        if (rp_esub[2] == 6'd63 || rp_last[2]) begin
                            // beat_acc is cleared after every push, so a
                            // partial last beat is zero above the rows the
                            // transfer owns
                            fmem[f_wp[FW-1:0]] <= nb;
                            f_wp     <= f_wp + 1'b1;
                            beat_acc <= '0;
                        end
                    end else begin
                        nb[{rp_sub[2], 7'b0}+:128] = slot_rdata[127:0];
                        beat_acc <= nb;
                        if (rp_sub[2] == 2'd3 || rp_last[2]) begin
                            fmem[f_wp[FW-1:0]] <= nb;
                            f_wp     <= f_wp + 1'b1;
                            beat_acc <= '0;
                        end
                    end
                end
                if (m_axis_wvalid && m_axis_wready) begin
                    f_rp   <= f_rp + 1'b1;
                    w_left <= w_left - 16'd1;
                    w_sent <= w_sent + 16'd1;
                end
                // bw_idle (rtl/seq_movers.sv:62-66): the phase is complete
                // only when every write response has been collected — not
                // when the last W beat went out.
                if ((w_left == 16'd0) && (a_left == 16'd0) && (a_out == 5'd0))
                    phase_done = 1'b1;
            end

            // ---------- phase / transfer completion ----------
            if (phase_done) begin
                // KV moves rows first, then the exponent side array
                last_phase = ph_exp || (x_kind != 2'd1);
                if (last_phase) begin
                    run       <= 1'b0;
                    xfer_done <= 1'b1;
                end else begin
                    ph_exp   <= 1'b1;
                    ph_rows  <= x_rows;
                    a_left   <= beats_of(x_kind, 1'b1, x_rows);
                    a_addr   <= x_addr + KV_EXP_OFF;
                    w_left   <= beats_of(x_kind, 1'b1, x_rows);
                    rd_units <= 16'(x_rows);
                    w_sent   <= '0;
                    f_wp <= '0; f_rp <= '0;
                    l_sub <= '0; l_esub <= '0; l_csub <= '0; srow <= '0;
                    bbuf_v <= 1'b0; rd_i <= '0; rp_v <= '0; rp_last <= '0;
                    beat_acc <= '0;
                end
            end
        end
    end

    assign xfer_busy = run;
    assign xfer_err  = err_q;

endmodule

`default_nettype wire
