// seq_fabric_model — simulation-only latency model of the sequencer control
// plane: a 1-master -> NSLV-slave AXI-Lite interconnect standing in for the
// Vivado AXI SmartConnect + register-slice chain that the real design will
// run through. It exists so testbenches can see the DUT's CSR traffic pay a
// realistic round-trip latency and can measure achievable throughput.
//
// NOT synthesized (it lives in tb/), but written as plain synthesizable RTL
// (always_ff / always_comb, no delays, no `--timing` constructs) so it lints
// clean under:  verilator --lint-only -Wall --timing tb/seq_fabric_model.sv
//
// Model
// -----
//  * Decode: 4 KB slots. slave index = addr[12 +: SIDW] with
//    SIDW = $clog2(NSLV); for the default NSLV=8 that is exactly addr[14:12]
//    (slots at 0x0000, 0x1000, ... 0x7000). addr[11:0] is forwarded to the
//    slave. Address bits above the decode field are IGNORED — such addresses
//    are still accepted and decoded on the select field. There is
//    deliberately no decode-error path (the TB never issues one).
//  * Latency: every request is delayed exactly LAT cycles on its way to the
//    slave, and every response exactly LAT cycles on its way back. The delay
//    lines are non-stallable shift registers feeding depth-MAXOUT FIFOs.
//  * Pipelining is the point: up to MAXOUT (16) writes and 16 reads may be
//    outstanding simultaneously and independently. Nothing is serialised.
//    LAT = 0 is legal (the shift registers vanish). Note LAT is *added*
//    latency: the model's own request/response FIFO stages cost ~2 cycles
//    each way even at LAT = 0, and the path stays fully pipelined there.
//  * Ordering: AXI-Lite has no IDs, so responses must return in request
//    order. Enforced structurally per direction by allowing only one target
//    slave to be outstanding at a time: a request aimed at a different slave
//    stalls upstream until that direction's outstanding count reaches 0.
//    Applied to writes as well as reads (simpler, and close enough to
//    SmartConnect).
//  * BRESP/RRESP are passed through from the slave unchanged.
//  * Every m_* output is driven for every slave; slaves that are never
//    addressed see all-zero request signals.
//
// Instrumentation: n_wr / n_rd count completed transactions; busy_wr /
// busy_rd count cycles with at least one outstanding write / read. Divide
// busy_* by n_* for average concurrency, or count total cycles externally.

`timescale 1ns/1ps
`default_nettype none

module seq_fabric_model #(
    parameter int LAT  = 4,
    parameter int NSLV = 8
) (
    input  wire                    aclk,
    input  wire                    aresetn,

    // ---------------- AXI-Lite SLAVE side (from the DUT master) ----------
    /* verilator lint_off UNUSEDSIGNAL */
    // Only [12 +: SIDW] (slave select) and [11:0] (offset) are consumed;
    // the upper address bits are deliberately ignored — see header.
    input  wire [31:0]             s_awaddr,
    /* verilator lint_on UNUSEDSIGNAL */
    input  wire                    s_awvalid,
    output logic                   s_awready,

    input  wire [31:0]             s_wdata,
    input  wire [3:0]              s_wstrb,
    input  wire                    s_wvalid,
    output logic                   s_wready,

    output logic [1:0]             s_bresp,
    output logic                   s_bvalid,
    input  wire                    s_bready,

    /* verilator lint_off UNUSEDSIGNAL */
    input  wire [31:0]             s_araddr,
    /* verilator lint_on UNUSEDSIGNAL */
    input  wire                    s_arvalid,
    output logic                   s_arready,

    output logic [31:0]            s_rdata,
    output logic [1:0]             s_rresp,
    output logic                   s_rvalid,
    input  wire                    s_rready,

    // ---------------- NSLV AXI-Lite MASTER ports (12-bit address) --------
    output logic [NSLV-1:0][11:0]  m_awaddr,
    output logic [NSLV-1:0]        m_awvalid,
    input  wire  [NSLV-1:0]        m_awready,

    output logic [NSLV-1:0][31:0]  m_wdata,
    output logic [NSLV-1:0][3:0]   m_wstrb,
    output logic [NSLV-1:0]        m_wvalid,
    input  wire  [NSLV-1:0]        m_wready,

    input  wire  [NSLV-1:0][1:0]   m_bresp,
    input  wire  [NSLV-1:0]        m_bvalid,
    output logic [NSLV-1:0]        m_bready,

    output logic [NSLV-1:0][11:0]  m_araddr,
    output logic [NSLV-1:0]        m_arvalid,
    input  wire  [NSLV-1:0]        m_arready,

    input  wire  [NSLV-1:0][31:0]  m_rdata,
    input  wire  [NSLV-1:0][1:0]   m_rresp,
    input  wire  [NSLV-1:0]        m_rvalid,
    output logic [NSLV-1:0]        m_rready,

    // ---------------- instrumentation ------------------------------------
    output logic [31:0]            n_wr,      // completed write transactions
    output logic [31:0]            n_rd,      // completed read transactions
    output logic [31:0]            busy_wr,   // cycles with >=1 write outstanding
    output logic [31:0]            busy_rd    // cycles with >=1 read outstanding
);

    // ---------------------------------------------------------------------
    // sizes
    // ---------------------------------------------------------------------
    localparam int MAXOUT = 16;                          // max outstanding / direction
    localparam int SIDW   = (NSLV <= 1) ? 1 : $clog2(NSLV);
    localparam int CNTW   = $clog2(MAXOUT + 1);          // 5 bits, holds 0..16
    localparam int WREQ_W = SIDW + 12 + 32 + 4;          // {slv, addr, wdata, wstrb}
    localparam int RREQ_W = SIDW + 12;                   // {slv, addr}

    // ---------------------------------------------------------------------
    // decode + upstream accept / ordering
    // ---------------------------------------------------------------------
    logic [SIDW-1:0] wr_slv, rd_slv;
    assign wr_slv = s_awaddr[12 +: SIDW];
    assign rd_slv = s_araddr[12 +: SIDW];

    logic [CNTW-1:0] wr_outst, rd_outst;   // accepted but not yet responded
    logic [SIDW-1:0] cur_wr_slv, cur_rd_slv;

    logic wr_can, rd_can, wr_accept, rd_accept;

    // room left, and (ordering) either nothing outstanding or same target
    assign wr_can = (wr_outst < CNTW'(MAXOUT)) &&
                    ((wr_outst == '0) || (wr_slv == cur_wr_slv));
    assign rd_can = (rd_outst < CNTW'(MAXOUT)) &&
                    ((rd_outst == '0) || (rd_slv == cur_rd_slv));

    // AW and W are accepted only together, in the same cycle
    assign wr_accept = s_awvalid && s_wvalid && wr_can;
    assign rd_accept = s_arvalid && rd_can;

    assign s_awready = wr_accept;
    assign s_wready  = wr_accept;
    assign s_arready = rd_can;

    // ---------------------------------------------------------------------
    // request delay lines (LAT deep, non-stallable). Index 0 is the
    // combinational input, index LAT is the output, so LAT = 0 degenerates
    // to a wire.
    // ---------------------------------------------------------------------
    logic              wq_v [LAT+1];
    logic [WREQ_W-1:0] wq_d [LAT+1];
    logic              rq_v [LAT+1];
    logic [RREQ_W-1:0] rq_d [LAT+1];

    assign wq_v[0] = wr_accept;
    assign wq_d[0] = {wr_slv, s_awaddr[11:0], s_wdata, s_wstrb};
    assign rq_v[0] = rd_accept;
    assign rq_d[0] = {rd_slv, s_araddr[11:0]};

    genvar gi;
    generate
        for (gi = 1; gi <= LAT; gi = gi + 1) begin : g_req_delay
            always_ff @(posedge aclk) begin
                if (!aresetn) begin
                    wq_v[gi] <= 1'b0;
                    rq_v[gi] <= 1'b0;
                end else begin
                    wq_v[gi] <= wq_v[gi-1];
                    rq_v[gi] <= rq_v[gi-1];
                end
            end
            always_ff @(posedge aclk) begin
                wq_d[gi] <= wq_d[gi-1];
                rq_d[gi] <= rq_d[gi-1];
            end
        end
    endgenerate

    // ---------------------------------------------------------------------
    // request FIFOs -> slave ports
    //   Depth MAXOUT can never overflow: every entry anywhere in the model
    //   counts against wr_outst / rd_outst, which are capped at MAXOUT.
    // ---------------------------------------------------------------------
    logic              wf_empty, wf_pop;
    logic [WREQ_W-1:0] wf_dout;
    seq_fab_fifo #(.W(WREQ_W), .DEPTH(MAXOUT)) u_wreq (
        .aclk    (aclk),
        .aresetn (aresetn),
        .push    (wq_v[LAT]),
        .din     (wq_d[LAT]),
        .pop     (wf_pop),
        .empty   (wf_empty),
        .dout    (wf_dout)
    );

    logic              rf_empty, rf_pop;
    logic [RREQ_W-1:0] rf_dout;
    seq_fab_fifo #(.W(RREQ_W), .DEPTH(MAXOUT)) u_rreq (
        .aclk    (aclk),
        .aresetn (aresetn),
        .push    (rq_v[LAT]),
        .din     (rq_d[LAT]),
        .pop     (rf_pop),
        .empty   (rf_empty),
        .dout    (rf_dout)
    );

    logic [SIDW-1:0] wf_slv;
    logic [11:0]     wf_addr;
    logic [31:0]     wf_data;
    logic [3:0]      wf_strb;
    assign {wf_slv, wf_addr, wf_data, wf_strb} = wf_dout;

    logic [SIDW-1:0] rf_slv;
    logic [11:0]     rf_addr;
    assign {rf_slv, rf_addr} = rf_dout;

    // AW / W are presented together and each held until its own handshake;
    // the sticky flags mean we do not assume the slave takes both at once.
    logic wf_awdone, wf_wdone, aw_hs, w_hs;
    assign aw_hs  = !wf_empty && !wf_awdone && m_awready[wf_slv];
    assign w_hs   = !wf_empty && !wf_wdone  && m_wready[wf_slv];
    assign wf_pop = !wf_empty && (wf_awdone || aw_hs) && (wf_wdone || w_hs);

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            wf_awdone <= 1'b0;
            wf_wdone  <= 1'b0;
        end else if (wf_pop) begin
            wf_awdone <= 1'b0;
            wf_wdone  <= 1'b0;
        end else begin
            if (aw_hs) wf_awdone <= 1'b1;
            if (w_hs)  wf_wdone  <= 1'b1;
        end
    end

    assign rf_pop = !rf_empty && m_arready[rf_slv];

    // ---------------------------------------------------------------------
    // master-port drive (every slave driven; unaddressed ones see 0)
    // ---------------------------------------------------------------------
    always_comb begin
        m_awaddr  = '0;
        m_awvalid = '0;
        m_wdata   = '0;
        m_wstrb   = '0;
        m_wvalid  = '0;
        m_araddr  = '0;
        m_arvalid = '0;
        m_bready  = '0;
        m_rready  = '0;

        if (!wf_empty) begin
            m_awaddr[wf_slv]  = wf_addr;
            m_wdata[wf_slv]   = wf_data;
            m_wstrb[wf_slv]   = wf_strb;
            m_awvalid[wf_slv] = !wf_awdone;
            m_wvalid[wf_slv]  = !wf_wdone;
        end
        if (!rf_empty) begin
            m_araddr[rf_slv]  = rf_addr;
            m_arvalid[rf_slv] = 1'b1;
        end

        // Responses can only ever come from the currently-outstanding target
        // (ordering rule above), and the response path can never back up
        // (its FIFO is MAXOUT deep), so we are unconditionally ready there.
        if (wr_outst != '0) m_bready[cur_wr_slv] = 1'b1;
        if (rd_outst != '0) m_rready[cur_rd_slv] = 1'b1;
    end

    // ---------------------------------------------------------------------
    // response delay lines (LAT deep) -> response FIFOs -> upstream
    // ---------------------------------------------------------------------
    logic       b_in_v;
    logic [1:0] b_in_d;
    assign b_in_v = (wr_outst != '0) && m_bvalid[cur_wr_slv];
    assign b_in_d = m_bresp[cur_wr_slv];

    logic        r_in_v;
    logic [33:0] r_in_d;
    assign r_in_v = (rd_outst != '0) && m_rvalid[cur_rd_slv];
    assign r_in_d = {m_rdata[cur_rd_slv], m_rresp[cur_rd_slv]};

    logic        bp_v [LAT+1];
    logic [1:0]  bp_d [LAT+1];
    logic        rp_v [LAT+1];
    logic [33:0] rp_d [LAT+1];

    assign bp_v[0] = b_in_v;
    assign bp_d[0] = b_in_d;
    assign rp_v[0] = r_in_v;
    assign rp_d[0] = r_in_d;

    generate
        for (gi = 1; gi <= LAT; gi = gi + 1) begin : g_rsp_delay
            always_ff @(posedge aclk) begin
                if (!aresetn) begin
                    bp_v[gi] <= 1'b0;
                    rp_v[gi] <= 1'b0;
                end else begin
                    bp_v[gi] <= bp_v[gi-1];
                    rp_v[gi] <= rp_v[gi-1];
                end
            end
            always_ff @(posedge aclk) begin
                bp_d[gi] <= bp_d[gi-1];
                rp_d[gi] <= rp_d[gi-1];
            end
        end
    endgenerate

    logic       bf_empty, bf_pop;
    logic [1:0] bf_dout;
    seq_fab_fifo #(.W(2), .DEPTH(MAXOUT)) u_brsp (
        .aclk    (aclk),
        .aresetn (aresetn),
        .push    (bp_v[LAT]),
        .din     (bp_d[LAT]),
        .pop     (bf_pop),
        .empty   (bf_empty),
        .dout    (bf_dout)
    );

    logic        rrf_empty, rrf_pop;
    logic [33:0] rrf_dout;
    seq_fab_fifo #(.W(34), .DEPTH(MAXOUT)) u_rrsp (
        .aclk    (aclk),
        .aresetn (aresetn),
        .push    (rp_v[LAT]),
        .din     (rp_d[LAT]),
        .pop     (rrf_pop),
        .empty   (rrf_empty),
        .dout    (rrf_dout)
    );

    assign s_bvalid = !bf_empty;
    assign s_bresp  = bf_dout;
    assign bf_pop   = s_bvalid && s_bready;

    assign s_rvalid           = !rrf_empty;
    assign {s_rdata, s_rresp} = rrf_dout;
    assign rrf_pop            = s_rvalid && s_rready;

    // ---------------------------------------------------------------------
    // outstanding counters + instrumentation
    // ---------------------------------------------------------------------
    logic wr_done, rd_done;
    assign wr_done = s_bvalid && s_bready;
    assign rd_done = s_rvalid && s_rready;

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            wr_outst   <= '0;
            rd_outst   <= '0;
            cur_wr_slv <= '0;
            cur_rd_slv <= '0;
            n_wr       <= '0;
            n_rd       <= '0;
            busy_wr    <= '0;
            busy_rd    <= '0;
        end else begin
            if (wr_accept) cur_wr_slv <= wr_slv;
            if (rd_accept) cur_rd_slv <= rd_slv;

            case ({wr_accept, wr_done})
                2'b10:   wr_outst <= wr_outst + CNTW'(1);
                2'b01:   wr_outst <= wr_outst - CNTW'(1);
                default: /* no change */ ;
            endcase
            case ({rd_accept, rd_done})
                2'b10:   rd_outst <= rd_outst + CNTW'(1);
                2'b01:   rd_outst <= rd_outst - CNTW'(1);
                default: /* no change */ ;
            endcase

            if (wr_done)        n_wr    <= n_wr    + 32'd1;
            if (rd_done)        n_rd    <= n_rd    + 32'd1;
            if (wr_outst != '0) busy_wr <= busy_wr + 32'd1;
            if (rd_outst != '0) busy_rd <= busy_rd + 32'd1;
        end
    end

endmodule


// ---------------------------------------------------------------------------
// seq_fab_fifo — plain synchronous FIFO used internally by seq_fabric_model.
// Combinational read of the head (dout valid whenever !empty), registered
// write. Overflow / underflow are simulation errors, not silent wraps.
// ---------------------------------------------------------------------------
/* verilator lint_off DECLFILENAME */
module seq_fab_fifo #(
    parameter int W     = 8,
    parameter int DEPTH = 16
) (
    input  wire          aclk,
    input  wire          aresetn,
    input  wire          push,
    input  wire [W-1:0]  din,
    input  wire          pop,
    output logic         empty,
    output logic [W-1:0] dout
);
/* verilator lint_on DECLFILENAME */

    localparam int PW = $clog2(DEPTH);
    localparam int CW = $clog2(DEPTH + 1);

    logic [W-1:0]  mem [DEPTH];
    logic [PW-1:0] wptr, rptr;
    logic [CW-1:0] cnt;

    assign empty = (cnt == '0);
    assign dout  = mem[rptr];

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            wptr <= '0;
            rptr <= '0;
            cnt  <= '0;
        end else begin
            if (push) begin
                if ((cnt == CW'(DEPTH)) && !pop)
                    $fatal(1, "seq_fab_fifo: overflow (DEPTH=%0d)", DEPTH);
                mem[wptr] <= din;
                wptr      <= wptr + PW'(1);
            end
            if (pop) begin
                if (cnt == '0)
                    $fatal(1, "seq_fab_fifo: underflow");
                rptr <= rptr + PW'(1);
            end
            case ({push, pop})
                2'b10:   cnt <= cnt + CW'(1);
                2'b01:   cnt <= cnt - CW'(1);
                default: /* no change */ ;
            endcase
        end
    end

endmodule

`default_nettype wire
