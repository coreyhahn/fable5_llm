// seq_burst_fabric — simulation-only latency model of the rung-3 BURST data
// plane (docs/RUNG3_SPEC.md S2/S4): a 1-master -> 5-slave AXI4 interconnect
// standing in for the Vivado SmartConnect (burst_smc, NUM_SI=1 NUM_MI=5,
// NUM_CLKS=1) plus the five axi_register_slice MIs the board build puts in
// front of matvec_chan_0..3 / layer_chan_0.
//
// It is the burst-path twin of tb/seq_fabric_model.sv (the AXI-Lite control
// plane) and deliberately mirrors that file's structure: non-stallable
// request/response delay lines feeding depth-limited FIFOs, one target
// outstanding per direction (structural response ordering), and an
// instrumentation block.  Both models coexist in the same testbench; the
// module names (seq_burst_fabric / seq_bfab_fifo) never collide with
// seq_fabric_model / seq_fab_fifo.
//
// Model
// -----
//  * Decode (S4, 64 KiB stride): target = addr[18:16] - 1, so
//        0x0001_0000 -> MI0 = mvchan_0      0x0004_0000 -> MI3 = mvchan_3
//        0x0002_0000 -> MI1 = mvchan_1      0x0005_0000 -> MI4 = layer_0
//        0x0003_0000 -> MI2 = mvchan_2
//    Everything else (slot 0, slot > NSLV, or any bit set above [18]) is a
//    DECODE HOLE and is answered by an INTERNAL error responder with
//    DECERR — the request never reaches a slave.  This is what SmartConnect
//    does with a hole, and it is how the out-of-window DECERR gate is
//    driven.  Only addr[MAW-1:0] is forwarded to the slave (MI ports are
//    MAW = 16 bits wide = the 64 KiB window), exactly as an IPI MI port
//    connected to a 64 KiB slave sees.
//  * Latency: LAT cycles each way, per channel, on AW/W/AR (request) and
//    B/R (response).  LAT is the PARAMETER default; a run can override it
//    with +blat=<n> (0 <= n <= LATMAX) so one binary covers the 0/4/8
//    sweep.  Latency is *added*: the model's own FIFO stages cost ~2 cycles
//    each way even at LAT = 0.
//  * Pipelining: up to MAXOUT write bursts and MAXOUT read bursts may be
//    outstanding simultaneously and independently.  W beats stream through
//    a WFD-deep FIFO and R beats through an RFD-deep FIFO; both apply
//    backpressure with LAT+2 cycles of slack reserved, so the
//    non-stallable delay lines can never drop a beat.
//  * Ordering: ID width is 1 and the master uses a single ID, so responses
//    must come back in request order.  Enforced structurally per direction
//    by allowing only ONE target to be outstanding at a time: a request
//    aimed at a different target stalls upstream until that direction's
//    outstanding count reaches 0.  B/R IDs are regenerated from the
//    request order (the slave's echoed id is compared, and disagreements
//    are counted in n_idmis rather than fataled — the contract ties IDs).
//  * BRESP/RRESP are passed through from the slave unchanged, so a shim
//    that answers SLVERR (S6: layer window touched while busy) is visible
//    to the master exactly as on silicon.
//  * FAULT INJECTION (for the mover's E_AXI 0x12 path): +binj_b=<n> turns
//    the n'th write response into SLVERR, +binj_r=<n> turns the n'th read
//    data beat into SLVERR.  0 = disabled.  Injection happens at the
//    upstream output stage, so it is deterministic in transaction count and
//    independent of LAT.
//  * PROTOCOL CHECKS (CHECKS=1, S7): every request must be INCR, 4 bytes
//    per beat, 4-byte aligned, <= 256 beats, and must not cross a 4 KiB
//    boundary; W beats must carry WLAST exactly on the last beat of the
//    burst.  Violations are $fatal(1) — this is the master-side burst
//    splitter's gate.
//
// Not synthesized (it lives in tb/), but written as plain RTL apart from
// the plusarg/`$fatal` instrumentation, and lints clean under
// "make -C tb lint_seq_burst" (--lint-only -Wall --timing).

`timescale 1ns/1ps
`default_nettype none

module seq_burst_fabric #(
    parameter int LAT    = 4,      // default added latency each way
    parameter int LATMAX = 16,     // depth of the delay lines (+blat cap)
    parameter int NSLV   = 5,      // 4 mvchan + 1 layer (S2/S4)
    parameter int MAW    = 16,     // MI address width = 64 KiB window
    parameter int IDW    = 1,      // AXI ID width (contract: 1)
    parameter int MAXOUT = 8,      // outstanding bursts per direction
    parameter int WFD    = 512,    // W-beat FIFO depth
    parameter int RFD    = 512,    // R-beat FIFO depth
    parameter bit CHECKS = 1'b1
) (
    input  wire                       aclk,
    input  wire                       aresetn,

    // ---------------- AXI4 SLAVE side (the mover's m_axib) ---------------
    input  wire [IDW-1:0]             s_awid,
    input  wire [31:0]                s_awaddr,
    input  wire [7:0]                 s_awlen,
    input  wire [2:0]                 s_awsize,
    input  wire [1:0]                 s_awburst,
    input  wire                       s_awvalid,
    output logic                      s_awready,

    input  wire [31:0]                s_wdata,
    input  wire [3:0]                 s_wstrb,
    input  wire                       s_wlast,
    input  wire                       s_wvalid,
    output logic                      s_wready,

    output logic [IDW-1:0]            s_bid,
    output logic [1:0]                s_bresp,
    output logic                      s_bvalid,
    input  wire                       s_bready,

    input  wire [IDW-1:0]             s_arid,
    input  wire [31:0]                s_araddr,
    input  wire [7:0]                 s_arlen,
    input  wire [2:0]                 s_arsize,
    input  wire [1:0]                 s_arburst,
    input  wire                       s_arvalid,
    output logic                      s_arready,

    output logic [IDW-1:0]            s_rid,
    output logic [31:0]               s_rdata,
    output logic [1:0]                s_rresp,
    output logic                      s_rlast,
    output logic                      s_rvalid,
    input  wire                       s_rready,

    // ---------------- NSLV AXI4 MASTER ports (MAW-bit address) -----------
    output logic [NSLV-1:0][IDW-1:0]  m_awid,
    output logic [NSLV-1:0][MAW-1:0]  m_awaddr,
    output logic [NSLV-1:0][7:0]      m_awlen,
    output logic [NSLV-1:0][2:0]      m_awsize,
    output logic [NSLV-1:0][1:0]      m_awburst,
    output logic [NSLV-1:0]           m_awvalid,
    input  wire  [NSLV-1:0]           m_awready,

    output logic [NSLV-1:0][31:0]     m_wdata,
    output logic [NSLV-1:0][3:0]      m_wstrb,
    output logic [NSLV-1:0]           m_wlast,
    output logic [NSLV-1:0]           m_wvalid,
    input  wire  [NSLV-1:0]           m_wready,

    input  wire  [NSLV-1:0][IDW-1:0]  m_bid,
    input  wire  [NSLV-1:0][1:0]      m_bresp,
    input  wire  [NSLV-1:0]           m_bvalid,
    output logic [NSLV-1:0]           m_bready,

    output logic [NSLV-1:0][IDW-1:0]  m_arid,
    output logic [NSLV-1:0][MAW-1:0]  m_araddr,
    output logic [NSLV-1:0][7:0]      m_arlen,
    output logic [NSLV-1:0][2:0]      m_arsize,
    output logic [NSLV-1:0][1:0]      m_arburst,
    output logic [NSLV-1:0]           m_arvalid,
    input  wire  [NSLV-1:0]           m_arready,

    input  wire  [NSLV-1:0][IDW-1:0]  m_rid,
    input  wire  [NSLV-1:0][31:0]     m_rdata,
    input  wire  [NSLV-1:0][1:0]      m_rresp,
    input  wire  [NSLV-1:0]           m_rlast,
    input  wire  [NSLV-1:0]           m_rvalid,
    output logic [NSLV-1:0]           m_rready,

    // ---------------- instrumentation ------------------------------------
    output logic [31:0]               n_wr,      // completed write bursts
    output logic [31:0]               n_wbeat,   // accepted W beats
    output logic [31:0]               n_rd,      // completed read bursts
    output logic [31:0]               n_rbeat,   // delivered R beats
    output logic [31:0]               busy_wr,   // cycles >=1 write outstanding
    output logic [31:0]               busy_rd,   // cycles >=1 read outstanding
    output logic [31:0]               n_dec,     // decode-hole bursts
    output logic [31:0]               n_slverr,  // non-OK responses upstream
    output logic [31:0]               n_idmis    // slave id != request id
);

    // ---------------------------------------------------------------------
    // sizes / target space (index NSLV = the internal decode-error target)
    // ---------------------------------------------------------------------
    localparam int NTGT    = NSLV + 1;
    localparam int ERRT    = NSLV;
    localparam int SIDW    = $clog2(NTGT);
    localparam int CNTW    = $clog2(MAXOUT + 1);
    localparam int AREQ_W  = SIDW + IDW + MAW + 8 + 3 + 2;   // {tgt,id,a,len,size,burst}
    localparam int WREQ_W  = 32 + 4 + 1;                     // {data,strb,last}
    localparam int BRSP_W  = IDW + 2;                        // {id,resp}
    localparam int RRSP_W  = IDW + 32 + 2 + 1;               // {id,data,resp,last}
    localparam int WCW     = $clog2(WFD + 1);
    localparam int RCW     = $clog2(RFD + 1);

    // ---------------------------------------------------------------------
    // effective latency: parameter default, overridable per run with +blat=
    // ---------------------------------------------------------------------
    int lat;
    initial begin
        lat = LAT;
        void'($value$plusargs("blat=%d", lat));
        if (lat < 0 || lat > LATMAX)
            $fatal(1, "seq_burst_fabric: +blat=%0d out of range 0..%0d", lat,
                   LATMAX);
        if (LAT > LATMAX)
            $fatal(1, "seq_burst_fabric: LAT=%0d > LATMAX=%0d", LAT, LATMAX);
    end

    // ---------------------------------------------------------------------
    // decode
    // ---------------------------------------------------------------------
    logic [2:0]      aw_slot, ar_slot;
    logic            aw_hole, ar_hole;
    logic [SIDW-1:0] aw_tgt,  ar_tgt;

    assign aw_slot = s_awaddr[18:16];
    assign ar_slot = s_araddr[18:16];
    assign aw_hole = (s_awaddr[31:19] != 13'd0) || (aw_slot == 3'd0)
                     || (aw_slot > 3'(NSLV));
    assign ar_hole = (s_araddr[31:19] != 13'd0) || (ar_slot == 3'd0)
                     || (ar_slot > 3'(NSLV));
    assign aw_tgt  = aw_hole ? SIDW'(ERRT) : SIDW'({1'b0, aw_slot} - 4'd1);
    assign ar_tgt  = ar_hole ? SIDW'(ERRT) : SIDW'({1'b0, ar_slot} - 4'd1);

    // ---------------------------------------------------------------------
    // upstream accept / ordering
    // ---------------------------------------------------------------------
    logic [CNTW-1:0] wr_outst, rd_outst;
    logic [SIDW-1:0] cur_wr_tgt, cur_rd_tgt;
    logic [31:0]     w_owed;               // W beats promised by accepted AWs

    logic [WCW-1:0]  wf_cnt;
    logic [RCW-1:0]  rf_cnt;

    logic aw_accept, w_accept, ar_accept;

    assign s_awready = (wr_outst < CNTW'(MAXOUT))
                       && ((wr_outst == '0) || (aw_tgt == cur_wr_tgt));
    assign aw_accept = s_awvalid && s_awready;

    // W beats are taken only once their AW has been accepted (a legal slave
    // behaviour, and it makes the W routing target unambiguous), and only
    // with LAT+2 cycles of FIFO slack in hand.
    assign s_wready  = (w_owed != 32'd0)
                       && ({{(32-WCW){1'b0}}, wf_cnt} + 32'(lat) + 32'd2
                           < 32'(WFD));
    assign w_accept  = s_wvalid && s_wready;

    assign s_arready = (rd_outst < CNTW'(MAXOUT))
                       && ((rd_outst == '0) || (ar_tgt == cur_rd_tgt));
    assign ar_accept = s_arvalid && s_arready;

    // ---------------------------------------------------------------------
    // protocol checks (S7) — the burst splitter's gate
    // ---------------------------------------------------------------------
    /* verilator lint_off BLKSEQ */
    always @(posedge aclk) if (aresetn && CHECKS) begin
        if (aw_accept) begin
            if (s_awburst !== 2'b01)
                $fatal(1, "seq_burst_fabric: AW burst type %02b (INCR only)",
                       s_awburst);
            if (s_awsize !== 3'b010)
                $fatal(1, "seq_burst_fabric: AW size %03b (4 bytes only)",
                       s_awsize);
            if (s_awaddr[1:0] !== 2'b00)
                $fatal(1, "seq_burst_fabric: AW addr %08h not 4-byte aligned",
                       s_awaddr);
            if (({20'd0, s_awaddr[11:0]} + ((32'({1'b0, s_awlen}) + 32'd1) << 2))
                > 32'd4096)
                $fatal(1, "seq_burst_fabric: AW %08h len %0d crosses a 4 KiB boundary",
                       s_awaddr, s_awlen + 8'd1);
        end
        if (ar_accept) begin
            if (s_arburst !== 2'b01)
                $fatal(1, "seq_burst_fabric: AR burst type %02b (INCR only)",
                       s_arburst);
            if (s_arsize !== 3'b010)
                $fatal(1, "seq_burst_fabric: AR size %03b (4 bytes only)",
                       s_arsize);
            if (s_araddr[1:0] !== 2'b00)
                $fatal(1, "seq_burst_fabric: AR addr %08h not 4-byte aligned",
                       s_araddr);
            if (({20'd0, s_araddr[11:0]} + ((32'({1'b0, s_arlen}) + 32'd1) << 2))
                > 32'd4096)
                $fatal(1, "seq_burst_fabric: AR %08h len %0d crosses a 4 KiB boundary",
                       s_araddr, s_arlen + 8'd1);
        end
    end
    /* verilator lint_on BLKSEQ */

    // WLAST must mark the last beat OF ITS OWN BURST.  w_owed is a global
    // count across every outstanding AW (the master legitimately keeps more
    // than one write burst in flight), so the check needs the per-burst
    // length, taken from a shadow FIFO in AW order.  A W beat can only be
    // accepted the cycle AFTER its AW (s_wready needs a registered w_owed),
    // so the entry is always already there.
    localparam int WPW = $clog2(MAXOUT);
    logic [8:0]     wlen_q [MAXOUT];
    logic [WPW-1:0] wlen_wp, wlen_rp;
    logic [8:0]     wbeats_left;

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            wlen_wp <= '0; wlen_rp <= '0; wbeats_left <= 9'd0;
        end else begin
            if (aw_accept) begin
                wlen_q[wlen_wp] <= 9'({1'b0, s_awlen}) + 9'd1;
                wlen_wp <= (wlen_wp == WPW'(MAXOUT - 1)) ? '0
                           : wlen_wp + WPW'(1);
            end
            if (w_accept) begin
                if (wbeats_left == 9'd0) begin
                    if (CHECKS && (s_wlast !== (wlen_q[wlen_rp] == 9'd1)))
                        $fatal(1, "seq_burst_fabric: WLAST=%b on beat 1 of a %0d-beat burst",
                               s_wlast, wlen_q[wlen_rp]);
                    wbeats_left <= wlen_q[wlen_rp] - 9'd1;
                    if (wlen_q[wlen_rp] == 9'd1)
                        wlen_rp <= (wlen_rp == WPW'(MAXOUT - 1)) ? '0
                                   : wlen_rp + WPW'(1);
                end else begin
                    if (CHECKS && (s_wlast !== (wbeats_left == 9'd1)))
                        $fatal(1, "seq_burst_fabric: WLAST=%b with %0d beat(s) left in the burst",
                               s_wlast, wbeats_left);
                    wbeats_left <= wbeats_left - 9'd1;
                    if (wbeats_left == 9'd1)
                        wlen_rp <= (wlen_rp == WPW'(MAXOUT - 1)) ? '0
                                   : wlen_rp + WPW'(1);
                end
            end
        end
    end

    // ---------------------------------------------------------------------
    // request delay lines (LATMAX deep, non-stallable, tapped at `lat`)
    // ---------------------------------------------------------------------
    logic              awq_v [LATMAX+1];
    logic [AREQ_W-1:0] awq_d [LATMAX+1];
    logic              wq_v  [LATMAX+1];
    logic [WREQ_W-1:0] wq_d  [LATMAX+1];
    logic              arq_v [LATMAX+1];
    logic [AREQ_W-1:0] arq_d [LATMAX+1];

    assign awq_v[0] = aw_accept;
    assign awq_d[0] = {aw_tgt, s_awid, s_awaddr[MAW-1:0], s_awlen, s_awsize,
                       s_awburst};
    assign wq_v[0]  = w_accept;
    assign wq_d[0]  = {s_wdata, s_wstrb, s_wlast};
    assign arq_v[0] = ar_accept;
    assign arq_d[0] = {ar_tgt, s_arid, s_araddr[MAW-1:0], s_arlen, s_arsize,
                       s_arburst};

    genvar gi;
    generate
        for (gi = 1; gi <= LATMAX; gi = gi + 1) begin : g_req_delay
            always_ff @(posedge aclk) begin
                if (!aresetn) begin
                    awq_v[gi] <= 1'b0;
                    wq_v[gi]  <= 1'b0;
                    arq_v[gi] <= 1'b0;
                end else begin
                    awq_v[gi] <= awq_v[gi-1];
                    wq_v[gi]  <= wq_v[gi-1];
                    arq_v[gi] <= arq_v[gi-1];
                end
            end
            always_ff @(posedge aclk) begin
                awq_d[gi] <= awq_d[gi-1];
                wq_d[gi]  <= wq_d[gi-1];
                arq_d[gi] <= arq_d[gi-1];
            end
        end
    endgenerate

    // ---------------------------------------------------------------------
    // request FIFOs -> master ports
    // ---------------------------------------------------------------------
    logic              awf_empty, awf_pop;
    logic [AREQ_W-1:0] awf_dout;
    /* verilator lint_off PINCONNECTEMPTY */
    seq_bfab_fifo #(.W(AREQ_W), .DEPTH(MAXOUT)) u_awreq (
        .aclk(aclk), .aresetn(aresetn),
        .push(awq_v[lat]), .din(awq_d[lat]),
        .pop(awf_pop), .empty(awf_empty), .dout(awf_dout), .cnt()
    );

    logic              arf_empty, arf_pop;
    logic [AREQ_W-1:0] arf_dout;
    seq_bfab_fifo #(.W(AREQ_W), .DEPTH(MAXOUT)) u_arreq (
        .aclk(aclk), .aresetn(aresetn),
        .push(arq_v[lat]), .din(arq_d[lat]),
        .pop(arf_pop), .empty(arf_empty), .dout(arf_dout), .cnt()
    );
    /* verilator lint_on PINCONNECTEMPTY */

    logic              wf_empty, wf_pop;
    logic [WREQ_W-1:0] wf_dout;
    seq_bfab_fifo #(.W(WREQ_W), .DEPTH(WFD)) u_wreq (
        .aclk(aclk), .aresetn(aresetn),
        .push(wq_v[lat]), .din(wq_d[lat]),
        .pop(wf_pop), .empty(wf_empty), .dout(wf_dout), .cnt(wf_cnt)
    );

    logic [SIDW-1:0] awf_tgt, arf_tgt;
    logic [IDW-1:0]  awf_id,  arf_id;
    logic [MAW-1:0]  awf_a,   arf_a;
    logic [7:0]      awf_len, arf_len;
    logic [2:0]      awf_size, arf_size;
    logic [1:0]      awf_burst, arf_burst;
    assign {awf_tgt, awf_id, awf_a, awf_len, awf_size, awf_burst} = awf_dout;
    assign {arf_tgt, arf_id, arf_a, arf_len, arf_size, arf_burst} = arf_dout;

    logic [31:0] wf_data;
    logic [3:0]  wf_strb;
    logic        wf_last;
    assign {wf_data, wf_strb, wf_last} = wf_dout;

    // ---------------------------------------------------------------------
    // the internal decode-error responder (target index ERRT)
    // ---------------------------------------------------------------------
    logic       err_w_active, err_b_pend;
    logic [8:0] err_r_left;
    logic [IDW-1:0] err_bid, err_rid;

    logic err_awready, err_wready, err_bvalid, err_arready, err_rvalid;
    logic err_rlast;

    assign err_awready = !err_w_active && !err_b_pend;
    assign err_wready  = err_w_active;
    assign err_bvalid  = err_b_pend;
    assign err_arready = (err_r_left == 9'd0);
    assign err_rvalid  = (err_r_left != 9'd0);
    assign err_rlast   = (err_r_left == 9'd1);

    // ---------------------------------------------------------------------
    // extended (NTGT-wide) slave-side views, error responder at [ERRT]
    // ---------------------------------------------------------------------
    logic [NTGT-1:0]           x_awready, x_wready, x_bvalid;
    logic [NTGT-1:0]           x_arready, x_rvalid, x_rlast;
    logic [NTGT-1:0][1:0]      x_bresp, x_rresp;
    logic [NTGT-1:0][31:0]     x_rdata;
    logic [NTGT-1:0][IDW-1:0]  x_bid, x_rid;

    always_comb begin
        for (int i = 0; i < NSLV; i++) begin
            x_awready[i] = m_awready[i];
            x_wready[i]  = m_wready[i];
            x_bvalid[i]  = m_bvalid[i];
            x_bresp[i]   = m_bresp[i];
            x_bid[i]     = m_bid[i];
            x_arready[i] = m_arready[i];
            x_rvalid[i]  = m_rvalid[i];
            x_rdata[i]   = m_rdata[i];
            x_rresp[i]   = m_rresp[i];
            x_rlast[i]   = m_rlast[i];
            x_rid[i]     = m_rid[i];
        end
        x_awready[ERRT] = err_awready;
        x_wready[ERRT]  = err_wready;
        x_bvalid[ERRT]  = err_bvalid;
        x_bresp[ERRT]   = 2'b11;                 // DECERR
        x_bid[ERRT]     = err_bid;
        x_arready[ERRT] = err_arready;
        x_rvalid[ERRT]  = err_rvalid;
        x_rdata[ERRT]   = 32'hDECE_DECE;
        x_rresp[ERRT]   = 2'b11;                 // DECERR
        x_rlast[ERRT]   = err_rlast;
        x_rid[ERRT]     = err_rid;
    end

    // ---------------------------------------------------------------------
    // master-port drive (every slave driven; unaddressed ones see 0)
    // ---------------------------------------------------------------------
    logic rf_room;                               // R FIFO can take a beat

    always_comb begin
        m_awid = '0; m_awaddr = '0; m_awlen = '0; m_awsize = '0;
        m_awburst = '0; m_awvalid = '0;
        m_wdata = '0; m_wstrb = '0; m_wlast = '0; m_wvalid = '0;
        m_arid = '0; m_araddr = '0; m_arlen = '0; m_arsize = '0;
        m_arburst = '0; m_arvalid = '0;
        m_bready = '0; m_rready = '0;

        for (int i = 0; i < NSLV; i++) begin
            if (!awf_empty && (awf_tgt == SIDW'(i))) begin
                m_awid[i]    = awf_id;
                m_awaddr[i]  = awf_a;
                m_awlen[i]   = awf_len;
                m_awsize[i]  = awf_size;
                m_awburst[i] = awf_burst;
                m_awvalid[i] = 1'b1;
            end
            if (!wf_empty && (cur_wr_tgt == SIDW'(i))) begin
                m_wdata[i]  = wf_data;
                m_wstrb[i]  = wf_strb;
                m_wlast[i]  = wf_last;
                m_wvalid[i] = 1'b1;
            end
            if (!arf_empty && (arf_tgt == SIDW'(i))) begin
                m_arid[i]    = arf_id;
                m_araddr[i]  = arf_a;
                m_arlen[i]   = arf_len;
                m_arsize[i]  = arf_size;
                m_arburst[i] = arf_burst;
                m_arvalid[i] = 1'b1;
            end
            // responses can only come from the currently-outstanding target
            if ((wr_outst != '0) && (cur_wr_tgt == SIDW'(i)))
                m_bready[i] = 1'b1;
            if ((rd_outst != '0) && (cur_rd_tgt == SIDW'(i)) && rf_room)
                m_rready[i] = 1'b1;
        end
    end

    assign awf_pop = !awf_empty && x_awready[awf_tgt];
    assign arf_pop = !arf_empty && x_arready[arf_tgt];
    assign wf_pop  = !wf_empty  && (wr_outst != '0) && x_wready[cur_wr_tgt];

    // ---------------------------------------------------------------------
    // error responder state
    // ---------------------------------------------------------------------
    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            err_w_active <= 1'b0;
            err_b_pend   <= 1'b0;
            err_r_left   <= 9'd0;
            err_bid      <= '0;
            err_rid      <= '0;
        end else begin
            if (awf_pop && (awf_tgt == SIDW'(ERRT))) begin
                err_w_active <= 1'b1;
                err_bid      <= awf_id;
            end
            if (err_w_active && wf_pop && (cur_wr_tgt == SIDW'(ERRT))
                && wf_last) begin
                err_w_active <= 1'b0;
                err_b_pend   <= 1'b1;
            end
            if (err_b_pend && (wr_outst != '0)
                && (cur_wr_tgt == SIDW'(ERRT))) err_b_pend <= 1'b0;

            if (arf_pop && (arf_tgt == SIDW'(ERRT))) begin
                err_r_left <= 9'({1'b0, arf_len}) + 9'd1;
                err_rid    <= arf_id;
            end else if ((err_r_left != 9'd0) && (rd_outst != '0)
                         && (cur_rd_tgt == SIDW'(ERRT)) && rf_room)
                err_r_left <= err_r_left - 9'd1;
        end
    end

    // ---------------------------------------------------------------------
    // response delay lines -> response FIFOs -> upstream
    // ---------------------------------------------------------------------
    logic              b_in_v;
    logic [BRSP_W-1:0] b_in_d;
    assign b_in_v = (wr_outst != '0) && x_bvalid[cur_wr_tgt];
    assign b_in_d = {x_bid[cur_wr_tgt], x_bresp[cur_wr_tgt]};

    logic              r_in_v;
    logic [RRSP_W-1:0] r_in_d;
    assign r_in_v = (rd_outst != '0) && x_rvalid[cur_rd_tgt] && rf_room;
    assign r_in_d = {x_rid[cur_rd_tgt], x_rdata[cur_rd_tgt],
                     x_rresp[cur_rd_tgt], x_rlast[cur_rd_tgt]};

    logic              bp_v [LATMAX+1];
    logic [BRSP_W-1:0] bp_d [LATMAX+1];
    logic              rp_v [LATMAX+1];
    logic [RRSP_W-1:0] rp_d [LATMAX+1];

    assign bp_v[0] = b_in_v;
    assign bp_d[0] = b_in_d;
    assign rp_v[0] = r_in_v;
    assign rp_d[0] = r_in_d;

    generate
        for (gi = 1; gi <= LATMAX; gi = gi + 1) begin : g_rsp_delay
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

    // diagnostic: a slave that returns more than one B per AW (or holds
    // BVALID across two BREADY cycles) would silently corrupt the
    // outstanding accounting; catch it at the source.
    logic [31:0] dbg_awdlv, dbg_bpush;
    /* verilator lint_off BLKSEQ */
    always @(posedge aclk) begin
        if (!aresetn) begin
            dbg_awdlv = 32'd0; dbg_bpush = 32'd0;
        end else begin
            if (awf_pop) dbg_awdlv = dbg_awdlv + 32'd1;
            if (b_in_v)  dbg_bpush = dbg_bpush + 32'd1;
            if (CHECKS && (dbg_bpush > dbg_awdlv))
                $fatal(1, "seq_burst_fabric: %0d B responses for %0d AW requests delivered (target %0d returned a spurious B)",
                       dbg_bpush, dbg_awdlv, cur_wr_tgt);
        end
    end
    /* verilator lint_on BLKSEQ */

    logic              bf_empty, bf_pop;
    logic [BRSP_W-1:0] bf_dout;
    /* verilator lint_off PINCONNECTEMPTY */
    seq_bfab_fifo #(.W(BRSP_W), .DEPTH(MAXOUT)) u_brsp (
        .aclk(aclk), .aresetn(aresetn),
        .push(bp_v[lat]), .din(bp_d[lat]),
        .pop(bf_pop), .empty(bf_empty), .dout(bf_dout), .cnt()
    );
    /* verilator lint_on PINCONNECTEMPTY */

    logic              rrf_empty, rrf_pop;
    logic [RRSP_W-1:0] rrf_dout;
    seq_bfab_fifo #(.W(RRSP_W), .DEPTH(RFD)) u_rrsp (
        .aclk(aclk), .aresetn(aresetn),
        .push(rp_v[lat]), .din(rp_d[lat]),
        .pop(rrf_pop), .empty(rrf_empty), .dout(rrf_dout), .cnt(rf_cnt)
    );

    // reserve lat+2 cycles of slack for the non-stallable response delay line
    assign rf_room = ({{(32-RCW){1'b0}}, rf_cnt} + 32'(lat) + 32'd2
                      < 32'(RFD));

    // ---------------------------------------------------------------------
    // upstream response drive, with optional fault injection
    // ---------------------------------------------------------------------
    int inj_b, inj_r;
    initial begin
        inj_b = 0;
        inj_r = 0;
        void'($value$plusargs("binj_b=%d", inj_b));
        void'($value$plusargs("binj_r=%d", inj_r));
    end

    logic [IDW-1:0] bf_id;
    logic [1:0]     bf_resp;
    assign {bf_id, bf_resp} = bf_dout;

    logic [IDW-1:0] rf_id;
    logic [31:0]    rf_data;
    logic [1:0]     rf_resp;
    logic           rf_last;
    assign {rf_id, rf_data, rf_resp, rf_last} = rrf_dout;

    logic b_hit, r_hit;
    assign b_hit = (inj_b != 0) && (n_wr    + 32'd1 == 32'(inj_b));
    assign r_hit = (inj_r != 0) && (n_rbeat + 32'd1 == 32'(inj_r));

    assign s_bvalid = !bf_empty;
    assign s_bid    = bf_id;
    assign s_bresp  = b_hit ? 2'b10 : bf_resp;          // SLVERR on injection
    assign bf_pop   = s_bvalid && s_bready;

    assign s_rvalid = !rrf_empty;
    assign s_rid    = rf_id;
    assign s_rdata  = rf_data;
    assign s_rresp  = r_hit ? 2'b10 : rf_resp;
    assign s_rlast  = rf_last;
    assign rrf_pop  = s_rvalid && s_rready;

    // ---------------------------------------------------------------------
    // outstanding counters + instrumentation
    // ---------------------------------------------------------------------
    logic wr_done, rd_beat, rd_done;
    assign wr_done = s_bvalid && s_bready;
    assign rd_beat = s_rvalid && s_rready;
    assign rd_done = rd_beat && s_rlast;

    // id echo: the contract ties IDs to 0, so a slave that returns anything
    // else is a wiring bug.  Counted (not fataled) so a shim that leaves BID
    // undriven is reported rather than aborting a long gate run.
    logic idmis_w, idmis_r;
    assign idmis_w = wr_done && (s_bid !== {IDW{1'b0}});
    assign idmis_r = rd_done && (s_rid !== {IDW{1'b0}});

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            wr_outst   <= '0;
            rd_outst   <= '0;
            cur_wr_tgt <= '0;
            cur_rd_tgt <= '0;
            w_owed     <= '0;
            n_wr       <= '0;
            n_wbeat    <= '0;
            n_rd       <= '0;
            n_rbeat    <= '0;
            busy_wr    <= '0;
            busy_rd    <= '0;
            n_dec      <= '0;
            n_slverr   <= '0;
            n_idmis    <= '0;
        end else begin
            if (aw_accept) begin
                cur_wr_tgt <= aw_tgt;
                if (aw_hole) n_dec <= n_dec + 32'd1;
            end
            if (ar_accept) begin
                cur_rd_tgt <= ar_tgt;
                if (ar_hole) n_dec <= n_dec + 32'd1;
            end

            case ({aw_accept, wr_done})
                2'b10:   wr_outst <= wr_outst + CNTW'(1);
                2'b01:   wr_outst <= wr_outst - CNTW'(1);
                default: /* no change */ ;
            endcase
            case ({ar_accept, rd_done})
                2'b10:   rd_outst <= rd_outst + CNTW'(1);
                2'b01:   rd_outst <= rd_outst - CNTW'(1);
                default: /* no change */ ;
            endcase

            w_owed <= w_owed
                      + (aw_accept ? (32'({1'b0, s_awlen}) + 32'd1) : 32'd0)
                      - (w_accept  ? 32'd1 : 32'd0);

            if (w_accept) n_wbeat <= n_wbeat + 32'd1;
            if (wr_done)  n_wr    <= n_wr    + 32'd1;
            if (rd_beat)  n_rbeat <= n_rbeat + 32'd1;
            if (rd_done)  n_rd    <= n_rd    + 32'd1;
            if ((wr_done && (s_bresp != 2'b00))
                || (rd_beat && (s_rresp != 2'b00)))
                n_slverr <= n_slverr + 32'd1;
            if (idmis_w || idmis_r) n_idmis <= n_idmis + 32'd1;
            if (wr_outst != '0) busy_wr <= busy_wr + 32'd1;
            if (rd_outst != '0) busy_rd <= busy_rd + 32'd1;
        end
    end

    // ---------------------------------------------------------------------
    // R-channel sanity: a burst must deliver exactly len+1 beats.  Track the
    // expected beat count per outstanding read in a small shadow FIFO.
    // ---------------------------------------------------------------------
    localparam int RPW = $clog2(MAXOUT);
    logic [8:0]      rlen_q [MAXOUT];
    logic [RPW-1:0]  rlen_wp, rlen_rp;
    logic [8:0]      rbeats_left;

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            rlen_wp <= '0; rlen_rp <= '0; rbeats_left <= 9'd0;
        end else begin
            if (ar_accept) begin
                rlen_q[rlen_wp] <= 9'({1'b0, s_arlen}) + 9'd1;
                rlen_wp <= (rlen_wp == RPW'(MAXOUT - 1)) ? '0
                           : rlen_wp + RPW'(1);
            end
            if (rd_beat) begin
                if (rbeats_left == 9'd0) begin
                    if (CHECKS && (rlen_q[rlen_rp] == 9'd1) && !s_rlast)
                        $fatal(1, "seq_burst_fabric: RLAST missing on a 1-beat burst");
                    rbeats_left <= rlen_q[rlen_rp] - 9'd1;
                    if (rlen_q[rlen_rp] == 9'd1) begin
                        rlen_rp <= (rlen_rp == RPW'(MAXOUT - 1)) ? '0
                                   : rlen_rp + RPW'(1);
                    end
                end else begin
                    if (CHECKS && (rbeats_left == 9'd1) && !s_rlast)
                        $fatal(1, "seq_burst_fabric: RLAST missing at the end of a burst");
                    if (CHECKS && (rbeats_left != 9'd1) && s_rlast)
                        $fatal(1, "seq_burst_fabric: RLAST early (%0d beat(s) still owed)",
                               rbeats_left);
                    rbeats_left <= rbeats_left - 9'd1;
                    if (rbeats_left == 9'd1)
                        rlen_rp <= (rlen_rp == RPW'(MAXOUT - 1)) ? '0
                                   : rlen_rp + RPW'(1);
                end
            end
        end
    end

endmodule


// ---------------------------------------------------------------------------
// seq_bfab_fifo — plain synchronous FIFO used internally by
// seq_burst_fabric.  Combinational read of the head (dout valid whenever
// !empty), registered write.  Overflow / underflow are simulation errors.
// ---------------------------------------------------------------------------
/* verilator lint_off DECLFILENAME */
module seq_bfab_fifo #(
    parameter int W     = 8,
    parameter int DEPTH = 16
) (
    input  wire          aclk,
    input  wire          aresetn,
    input  wire          push,
    input  wire [W-1:0]  din,
    input  wire          pop,
    output logic         empty,
    output logic [W-1:0] dout,
    output logic [$clog2(DEPTH+1)-1:0] cnt
);
/* verilator lint_on DECLFILENAME */

    localparam int PW = $clog2(DEPTH);
    localparam int CW = $clog2(DEPTH + 1);

    logic [W-1:0]  mem [DEPTH];
    logic [PW-1:0] wptr, rptr;

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
                    $fatal(1, "seq_bfab_fifo: overflow (DEPTH=%0d)", DEPTH);
                mem[wptr] <= din;
                wptr      <= (wptr == PW'(DEPTH - 1)) ? '0 : wptr + PW'(1);
            end
            if (pop) begin
                if (cnt == '0)
                    $fatal(1, "seq_bfab_fifo: underflow");
                rptr <= (rptr == PW'(DEPTH - 1)) ? '0 : rptr + PW'(1);
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
