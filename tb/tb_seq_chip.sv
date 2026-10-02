// tb_seq_chip — FULL-CHIP, SEQ-DRIVEN simulation.
//
// tb_seq_unit proves rtl/seq_unit.sv against BEHAVIOURAL stubs of the two
// slaves.  This testbench replaces both stubs with the REAL, silicon-proven
// engines and drives the whole thing from a real emitted record stream, so
// the only thing the host does is load the stream, write START, and drain
// the OUT FIFO:
//
//   seq_unit.m_axil -> seq_fabric_model -> matvec_chan x NMV @0x1000..
//                                       -> layer_chan       @0x5000
//   seq_unit.m_axib -> seq_burst_fabric -> matvec_chan.s_axib @0x1_0000..
//                      (RUNG3 S2/S4)    -> layer_chan.s_axib  @0x6_0000 (R-b)
//   seq_unit.m_axi  -> seq_mem_file 128b: <p>.seq   @ SEQ_STREAM_BASE
//                                         <p>.seqdata.bin @ SEQ_DATA_BASE
//                                         <b>.emb.bin     @ EMB_BASE
//   matvec_chan.m_axi -> seq_mem_file 512b: <b>.wimg.bin  @ W_BASE
//                        (the REAL packed W4/W8 images, ui_clk domain)
//                        WIMGPC=1: <b>.wimg<c>.bin, one region PER CHANNEL —
//                        a REPACKED stream (SEQ_REPACK=1, R-c) gives each
//                        channel its own address space at W_BASE, so channel
//                        c must not be able to see another channel's bytes.
//   seq_unit.s_axil <- the TB acting as the host
//
// GOLDEN.  tb/scripts/gen_seq_chip_vectors.py runs ref/seq_model.py over the
// SAME stream and writes <p>.chip: the final PC, the OUT FIFO token list, the
// XRF, every non-staging scratch word, the banked TCNT pairs and the
// EOUT/AMAX registers.  So this is the SEQ-driven half of the dual-driven
// equivalence: the .txt half (tb_layer_chan +script=...) runs the identical
// schedule host-driven against the same layer_chan RTL, and ref/seq_model
// --gate proves the two schedules agree bit-for-bit at the model level.
//
// Run:
//   obj_dir_tb_seq_chip/tb_seq_chip +seq=scripts/w3/tok2_s1.e \
//       +base=scripts/w3/tok2_s1 [+watchdog_ms=N] [+nomem]
//
// MULTI-LAUNCH (docs/CHAT_SEQ_SPEC.md gate I1).  The .chip golden may hold
// MORE THAN ONE launch section, in which case this testbench relaunches the
// SAME, NEVER-RESET DUT once per section:
//
//   BASES ...            (once)
//   NLAUNCH n
//   LAUNCH i <rec offset into the .seq file> <records>
//   KIND <tag>  PC <n>  XRF/TOK/TCNT/EOUT/AMAX/RDWIN/MEM ...
//   ENDL
//   ... END
//
// Between sections the host BFM does exactly what sw/seq_run.py's
// seq_start_and_poll() does on silicon — drain the OUT FIFO, zero the XRF
// and TCNT_SEQ, write BASE/LEN/ENTRY, pulse START — and NOTHING else: rstn
// and ui_rstn stay high (a continuous assertion enforces that), so every
// layer_chan bank (KV, DeltaNet, conv windows, TCNT) carries over.  Each
// section's golden was produced by ref/seq_model.py running the identical
// image sequence against ONE persistent Mach, so a START that clobbered a
// bank shows up as a state mismatch, and the per-launch TCNT + carried-state
// checks say so directly.
//
// RDWIN <lo> <hi> <min> <max> counts the DDR read bursts a launch issues
// into an address window.  Gate I1 uses it to prove WHICH RoPE table a
// pos > 85 launch fetched (the XRF[4] cursor is a signed 18-bit register and
// ref/seq_model.py does not model its sign extension).

`timescale 1ns/1ps
`default_nettype none

module tb_seq_chip #(
    parameter int LAT      = 4,        // AXI-Lite fabric latency each way
    parameter int BLAT     = 4,        // burst fabric latency each way (S2)
    parameter int DDRLAT   = 32,       // record/LDC/EMB first-word latency
    parameter int WLAT     = 40,       // weight-image first-word latency
    parameter int NMV      = 1,        // REAL matvec_chan instances
    parameter bit WIMGPC   = 1'b0,     // R-c: one weight region PER CHANNEL
    parameter int RESGAP   = 3         // retired by rung 3 (kept for compat)
);
    localparam int NSLV  = 8;
    localparam int NBSLV = 5;          // burst fabric MIs (RUNG3 S2)
    localparam int MAXMEM = 65536;   // G3.1: 64K-word scratchpad
    // R-c: the width used to INDEX layer_chan's smem_a, derived from MAXMEM
    // rather than written out, because writing it out is exactly how this
    // went wrong: R-b widened the scratchpad 16K -> 32K and set MAXMEM, but
    // the two `smem_a[..._mem_a[i][13:0]]` reads below kept the 16K slice.
    // Every checked address >= 16384 then aliased down by 16K — invisible at
    // 0.8B (whose map IS 16,384 words, so the slice was exact) and, at 2B,
    // landing squarely inside the y32 staging window, i.e. comparing a
    // golden word against one the .seq run is licensed to leave different.
    // See evidence/qwen2b/rc/RC_GATE.md section 5b.
    localparam int MEMAW  = $clog2(MAXMEM);
    // R-c wall 8: seq_unit keeps the EMB row stride in CSR 0x60 EMBLOG2,
    // reset 11 (2048 B rows).  On silicon sw/seq_run.py:1762 programs it
    // before any EMB record runs; this host BFM did not, so a 2B artifact
    // (4096 B rows, EMBLOG2 12) had every embedding fetched from
    // EMB_BASE + tok*2048 and every generated token came out wrong.  The
    // value now travels in the .chip file's EMBLOG2 line, generator-derived
    // like BASES; ABSENT means 11, so every .chip written before this — all
    // of them 0.8B, where 11 is already correct — is unaffected.
    localparam int unsigned EMBLOG2_DEFAULT = 11;
    int unsigned exp_emblog2 = EMBLOG2_DEFAULT;

    // DDR plan — ref/seq_format.py + sw/hwmap.py (asserted against the
    // BASES line of the .chip file, so a generator change cannot drift).
    localparam longint SEQ_STREAM_BASE = 64'h0000_0000_9000_0000;
    localparam longint SEQ_DATA_BASE   = 64'h0000_0000_8000_0000;
    localparam longint EMB_BASE        = 64'h0000_0000_6000_0000;
    localparam longint W_BASE          = 64'h0000_0000_1000_0000;

    logic clk = 1'b0;
    logic ui_clk = 1'b0; logic [3:0] xph_l = 4'd0; wire [3:0] ui_clk_c = {4{ui_clk}} & ~xph_l;   // R3-8: per-channel ui_clk, gated only by +xp_hold (R3 block)
    logic rstn = 1'b0;
    logic ui_rstn = 1'b0;
    /* verilator lint_off BLKSEQ */
    always #2     clk    = ~clk;                    // 250 MHz aclk
    always #1.667 ui_clk = ~ui_clk;                 // ~300 MHz ui_clk
    /* verilator lint_on BLKSEQ */

    /* verilator lint_off UNUSEDSIGNAL */
    // ---------------- DUT <-> fabric ----------------
    logic [31:0] m_awaddr, m_wdata, m_araddr, m_rdata;
    logic [3:0]  m_wstrb;
    logic        m_awvalid, m_awready, m_wvalid, m_wready;
    logic        m_bvalid, m_bready, m_arvalid, m_arready, m_rvalid, m_rready;
    logic [1:0]  m_bresp, m_rresp;

    logic [NSLV-1:0][11:0] f_awaddr, f_araddr;
    logic [NSLV-1:0][31:0] f_wdata, f_rdata;
    logic [NSLV-1:0][3:0]  f_wstrb;
    logic [NSLV-1:0]       f_awvalid, f_awready, f_wvalid, f_wready;
    logic [NSLV-1:0]       f_bvalid, f_bready, f_arvalid, f_arready;
    logic [NSLV-1:0]       f_rvalid, f_rready;
    logic [NSLV-1:0][1:0]  f_bresp, f_rresp;
    logic [31:0] fab_nwr, fab_nrd, fab_bwr, fab_brd;

    // ---------------- DUT <-> burst fabric (RUNG3 S3/S4) ----------------
    logic        mb_awid, mb_arid, mb_bid, mb_rid;
    logic [31:0] mb_awaddr, mb_araddr, mb_wdata, mb_rdata;
    logic [7:0]  mb_awlen, mb_arlen;
    logic [2:0]  mb_awsize, mb_arsize;
    logic [1:0]  mb_awburst, mb_arburst, mb_bresp, mb_rresp;
    logic [3:0]  mb_wstrb;
    logic        mb_awvalid, mb_awready, mb_wvalid, mb_wready, mb_wlast;
    logic        mb_bvalid, mb_bready, mb_arvalid, mb_arready;
    logic        mb_rvalid, mb_rready, mb_rlast;

    logic [NBSLV-1:0][0:0]  g_awid, g_arid, g_bid, g_rid;
    // R-b: MI4 (layer_0) is a 128 KiB window -> 17-bit MI address bus;
    // the four mvchan MIs take its low 16 bits.
    logic [NBSLV-1:0][17:0] g_awaddr, g_araddr;   // G3.1: MAW = 18
    logic [NBSLV-1:0][7:0]  g_awlen, g_arlen;
    logic [NBSLV-1:0][2:0]  g_awsize, g_arsize;
    logic [NBSLV-1:0][1:0]  g_awburst, g_arburst, g_bresp, g_rresp;
    logic [NBSLV-1:0][31:0] g_wdata, g_rdata;
    logic [NBSLV-1:0][3:0]  g_wstrb;
    logic [NBSLV-1:0]       g_awvalid, g_awready, g_wvalid, g_wready, g_wlast;
    logic [NBSLV-1:0]       g_bvalid, g_bready, g_arvalid, g_arready;
    logic [NBSLV-1:0]       g_rvalid, g_rready, g_rlast;
    logic [31:0] bf_nwr, bf_nwbeat, bf_nrd, bf_nrbeat, bf_bwr, bf_brd;
    logic [31:0] bf_ndec, bf_nslv, bf_nidm;

    // ---------------- DUT <-> record/const/embedding DDR ----------------
    logic [33:0]  d_araddr;
    logic [7:0]   d_arlen;
    logic [2:0]   d_arsize;
    logic [1:0]   d_arburst, d_rresp;
    logic         d_arvalid, d_arready, d_rlast, d_rvalid, d_rready;
    logic [127:0] d_rdata;
    logic [63:0]  d_nbeats, d_nmiss;

    // ---------------- host (s_axil) ----------------
    logic [11:0] h_awaddr, h_araddr;
    logic [31:0] h_wdata, h_rdata;
    logic        h_awvalid, h_awready, h_wvalid, h_wready, h_bvalid, h_bready;
    logic        h_arvalid, h_arready, h_rvalid, h_rready;
    logic [1:0]  h_bresp, h_rresp;

    logic seq_busy, seq_halted, seq_err;
    // BM1: matvec_chan c -> seq_unit engine-busy nets, mirroring the block
    // design (synth/scripts/create_project.tcl); unbuilt slots tie 0.
    logic [3:0]  mvb_bm;
    logic [63:0] w_nbeats [4];
    logic [63:0] w_nmiss  [4];
    // S3: the read-only seq_mem_file instances still have to NAME the write
    // channel's outputs (-Wall refuses an empty pin connection).
    /* verilator lint_off UNUSEDSIGNAL */
    wire        nc_dawr, nc_dwr, nc_dbv;
    wire [1:0]  nc_dbresp;
    wire [63:0] nc_dwb;
    wire [3:0]  nc_wawr, nc_wwr, nc_wbv;
    wire [1:0]  nc_wbresp [4];
    wire [63:0] nc_wwb [4];
    /* verilator lint_on UNUSEDSIGNAL */
    /* verilator lint_on UNUSEDSIGNAL */

    // ==================================================================
    seq_unit #(
        .ADDR_W(34), .RES_GAP(RESGAP), .USE_XRF_SIDEBAND(1'b0),
        .XRFI_OFF(12'h038), .XRFD_OFF(12'h03C)
    ) dut (
        .aclk(clk), .aresetn(rstn),
        .s_axil_awaddr(h_awaddr), .s_axil_awvalid(h_awvalid),
        .s_axil_awready(h_awready), .s_axil_wdata(h_wdata),
        .s_axil_wstrb(4'hF), .s_axil_wvalid(h_wvalid), .s_axil_wready(h_wready),
        .s_axil_bresp(h_bresp), .s_axil_bvalid(h_bvalid), .s_axil_bready(h_bready),
        .s_axil_araddr(h_araddr), .s_axil_arvalid(h_arvalid),
        .s_axil_arready(h_arready), .s_axil_rdata(h_rdata),
        .s_axil_rresp(h_rresp), .s_axil_rvalid(h_rvalid), .s_axil_rready(h_rready),

        .m_axil_awaddr(m_awaddr), .m_axil_awvalid(m_awvalid),
        .m_axil_awready(m_awready), .m_axil_wdata(m_wdata),
        .m_axil_wstrb(m_wstrb), .m_axil_wvalid(m_wvalid), .m_axil_wready(m_wready),
        .m_axil_bresp(m_bresp), .m_axil_bvalid(m_bvalid), .m_axil_bready(m_bready),
        .m_axil_araddr(m_araddr), .m_axil_arvalid(m_arvalid),
        .m_axil_arready(m_arready), .m_axil_rdata(m_rdata),
        .m_axil_rresp(m_rresp), .m_axil_rvalid(m_rvalid), .m_axil_rready(m_rready),

        .m_axi_araddr(d_araddr), .m_axi_arlen(d_arlen), .m_axi_arsize(d_arsize),
        .m_axi_arburst(d_arburst), .m_axi_arvalid(d_arvalid),
        .m_axi_arready(d_arready), .m_axi_rdata(d_rdata), .m_axi_rresp(d_rresp),
        .m_axi_rlast(d_rlast), .m_axi_rvalid(d_rvalid), .m_axi_rready(d_rready),

        // layer_chan has no XRF sideband port — the board build ties these
        // off too (synth/scripts/create_project.tcl), so the AXI-Lite
        // XRFI/XRFD mirror is the path under test here.
        .m_axib_awid(mb_awid), .m_axib_awaddr(mb_awaddr),
        .m_axib_awlen(mb_awlen), .m_axib_awsize(mb_awsize),
        .m_axib_awburst(mb_awburst), .m_axib_awvalid(mb_awvalid),
        .m_axib_awready(mb_awready),
        .m_axib_wdata(mb_wdata), .m_axib_wstrb(mb_wstrb),
        .m_axib_wlast(mb_wlast), .m_axib_wvalid(mb_wvalid),
        .m_axib_wready(mb_wready),
        .m_axib_bid(mb_bid), .m_axib_bresp(mb_bresp),
        .m_axib_bvalid(mb_bvalid), .m_axib_bready(mb_bready),
        .m_axib_arid(mb_arid), .m_axib_araddr(mb_araddr),
        .m_axib_arlen(mb_arlen), .m_axib_arsize(mb_arsize),
        .m_axib_arburst(mb_arburst), .m_axib_arvalid(mb_arvalid),
        .m_axib_arready(mb_arready),
        .m_axib_rid(mb_rid), .m_axib_rdata(mb_rdata),
        .m_axib_rresp(mb_rresp), .m_axib_rlast(mb_rlast),
        .m_axib_rvalid(mb_rvalid), .m_axib_rready(mb_rready),

        .xrf_sb_we(1'b0), .xrf_sb_idx(3'd0), .xrf_sb_data(18'd0),
        .mv_busy_bm(mvb_bm), .xpush_valid(xpv), .xpush_idx(xpi), .xpush_data(xpd), .xpush_room(xpr), .xpush_busy(xpb),   // R3-8: the x-push bus
        .seq_busy(seq_busy), .seq_halted(seq_halted), .seq_err(seq_err)
    );

    seq_burst_fabric #(.LAT(BLAT), .NSLV(NBSLV)) u_bfab (
        .aclk(clk), .aresetn(rstn),
        .s_awid(mb_awid), .s_awaddr(mb_awaddr), .s_awlen(mb_awlen),
        .s_awsize(mb_awsize), .s_awburst(mb_awburst),
        .s_awvalid(mb_awvalid), .s_awready(mb_awready),
        .s_wdata(mb_wdata), .s_wstrb(mb_wstrb), .s_wlast(mb_wlast),
        .s_wvalid(mb_wvalid), .s_wready(mb_wready),
        .s_bid(mb_bid), .s_bresp(mb_bresp), .s_bvalid(mb_bvalid),
        .s_bready(mb_bready),
        .s_arid(mb_arid), .s_araddr(mb_araddr), .s_arlen(mb_arlen),
        .s_arsize(mb_arsize), .s_arburst(mb_arburst),
        .s_arvalid(mb_arvalid), .s_arready(mb_arready),
        .s_rid(mb_rid), .s_rdata(mb_rdata), .s_rresp(mb_rresp),
        .s_rlast(mb_rlast), .s_rvalid(mb_rvalid), .s_rready(mb_rready),
        .m_awid(g_awid), .m_awaddr(g_awaddr), .m_awlen(g_awlen),
        .m_awsize(g_awsize), .m_awburst(g_awburst), .m_awvalid(g_awvalid),
        .m_awready(g_awready),
        .m_wdata(g_wdata), .m_wstrb(g_wstrb), .m_wlast(g_wlast),
        .m_wvalid(g_wvalid), .m_wready(g_wready),
        .m_bid(g_bid), .m_bresp(g_bresp), .m_bvalid(g_bvalid),
        .m_bready(g_bready),
        .m_arid(g_arid), .m_araddr(g_araddr), .m_arlen(g_arlen),
        .m_arsize(g_arsize), .m_arburst(g_arburst), .m_arvalid(g_arvalid),
        .m_arready(g_arready),
        .m_rid(g_rid), .m_rdata(g_rdata), .m_rresp(g_rresp),
        .m_rlast(g_rlast), .m_rvalid(g_rvalid), .m_rready(g_rready),
        .n_wr(bf_nwr), .n_wbeat(bf_nwbeat), .n_rd(bf_nrd),
        .n_rbeat(bf_nrbeat), .busy_wr(bf_bwr), .busy_rd(bf_brd),
        .n_dec(bf_ndec), .n_slverr(bf_nslv), .n_idmis(bf_nidm)
    );

    // burst MIs for matvec slots that are not elaborated: error sinks that
    // answer SLVERR, so an unexpected access is loud instead of hanging.
    for (genvar g = NMV; g < 4; g++) begin : g_bsink
        assign g_awready[g] = 1'b1;
        assign g_wready[g]  = 1'b1;
        assign g_bvalid[g]  = g_wvalid[g] && g_wlast[g];
        assign g_bresp[g]   = 2'b10;
        assign g_bid[g]     = 1'b0;
        assign g_arready[g] = 1'b1;
        assign g_rvalid[g]  = g_arvalid[g];
        assign g_rdata[g]   = 32'hDEAD_C0DE;
        assign g_rresp[g]   = 2'b10;
        assign g_rlast[g]   = 1'b1;
        assign g_rid[g]     = 1'b0;
    end

    seq_fabric_model #(.LAT(LAT), .NSLV(NSLV)) u_fab (
        .aclk(clk), .aresetn(rstn),
        .s_awaddr(m_awaddr), .s_awvalid(m_awvalid), .s_awready(m_awready),
        .s_wdata(m_wdata), .s_wstrb(m_wstrb), .s_wvalid(m_wvalid),
        .s_wready(m_wready), .s_bresp(m_bresp), .s_bvalid(m_bvalid),
        .s_bready(m_bready), .s_araddr(m_araddr), .s_arvalid(m_arvalid),
        .s_arready(m_arready), .s_rdata(m_rdata), .s_rresp(m_rresp),
        .s_rvalid(m_rvalid), .s_rready(m_rready),
        .m_awaddr(f_awaddr), .m_awvalid(f_awvalid), .m_awready(f_awready),
        .m_wdata(f_wdata), .m_wstrb(f_wstrb), .m_wvalid(f_wvalid),
        .m_wready(f_wready), .m_bresp(f_bresp), .m_bvalid(f_bvalid),
        .m_bready(f_bready), .m_araddr(f_araddr), .m_arvalid(f_arvalid),
        .m_arready(f_arready), .m_rdata(f_rdata), .m_rresp(f_rresp),
        .m_rvalid(f_rvalid), .m_rready(f_rready),
        .n_wr(fab_nwr), .n_rd(fab_nrd), .busy_wr(fab_bwr), .busy_rd(fab_brd)
    );

    seq_mem_file #(.ADDR_W(34), .DATA_W(128), .LAT(DDRLAT), .NREG(3),
                   .A0("seq"),  .S0(".seq"),         .B0(SEQ_STREAM_BASE),
                   .A1("seq"),  .S1(".seqdata.bin"), .B1(SEQ_DATA_BASE),
                   .A2("base"), .S2(".emb.bin"),     .B2(EMB_BASE),
                   .O2(1'b1)) u_ddr (
        .aclk(clk), .aresetn(rstn),
        .araddr(d_araddr), .arlen(d_arlen), .arsize(d_arsize),
        .arburst(d_arburst), .arvalid(d_arvalid), .arready(d_arready),
        .rdata(d_rdata), .rresp(d_rresp), .rlast(d_rlast), .rvalid(d_rvalid),
        .rready(d_rready), .n_beats(d_nbeats), .n_miss(d_nmiss),
        // S3: read-only instance -- no window, write channel tied idle
        .win_base(34'd0), .win_len(34'd0),
        .awaddr(34'd0), .awlen(8'd0), .awvalid(1'b0), .awready(nc_dawr),
        .wdata(128'd0), .wstrb(16'd0), .wlast(1'b0), .wvalid(1'b0),
        .wready(nc_dwr), .bresp(nc_dbresp), .bvalid(nc_dbv), .bready(1'b0),
        .n_wbeats(nc_dwb)
    );

    // slave 0 (csr_block) and 6/7 plus every unbuilt matvec slot: sinks
    for (genvar g = 0; g < NSLV; g++) begin : g_tie
        if ((g == 0) || (g >= 6) || ((g >= 1) && (g <= 4) && (g > NMV))) begin : g_sink
            assign f_awready[g] = 1'b1;
            assign f_wready[g]  = 1'b1;
            assign f_bvalid[g]  = f_awvalid[g] && f_wvalid[g];
            assign f_bresp[g]   = 2'b00;
            assign f_arready[g] = 1'b1;
            assign f_rvalid[g]  = f_arvalid[g];
            assign f_rdata[g]   = 32'hDEAD_C0DE;
            assign f_rresp[g]   = 2'b00;
        end
    end

    // ---------------- REAL matvec channels ----------------
    // R-c: a repacked stream packs each channel's rows in ITS OWN address
    // space from W_BASE, so each engine gets its own region file.  With
    // WIMGPC=0 (the default, and every artifact frozen before R-c) all NMV
    // engines share <base>.wimg.bin exactly as before.
    function automatic string wimg_sfx(input int ch);
        return WIMGPC ? $sformatf(".wimg%0d.bin", ch) : ".wimg.bin";
    endfunction

    for (genvar c = 0; c < NMV; c++) begin : g_mv
        logic [33:0]  w_araddr;
        logic [7:0]   w_arlen;
        logic [2:0]   w_arsize;
        logic [1:0]   w_arburst, w_rresp;
        logic         w_arvalid, w_arready, w_rlast, w_rvalid, w_rready;
        logic [511:0] w_rdata;

        matvec_chan #(.CHAN_ID(4'(c)), .ADDR_W(34)) u_mv (
            .aclk(clk), .aresetn(rstn),
            .s_axil_awaddr(f_awaddr[c+1]), .s_axil_awvalid(f_awvalid[c+1]),
            .s_axil_awready(f_awready[c+1]), .s_axil_wdata(f_wdata[c+1]),
            .s_axil_wstrb(f_wstrb[c+1]), .s_axil_wvalid(f_wvalid[c+1]),
            .s_axil_wready(f_wready[c+1]), .s_axil_bresp(f_bresp[c+1]),
            .s_axil_bvalid(f_bvalid[c+1]), .s_axil_bready(f_bready[c+1]),
            .s_axil_araddr(f_araddr[c+1]), .s_axil_arvalid(f_arvalid[c+1]),
            .s_axil_arready(f_arready[c+1]), .s_axil_rdata(f_rdata[c+1]),
            .s_axil_rresp(f_rresp[c+1]), .s_axil_rvalid(f_rvalid[c+1]),
            .s_axil_rready(f_rready[c+1]),
            .s_axib_awid(g_awid[c]), .s_axib_awaddr(g_awaddr[c][15:0]),
            .s_axib_awlen(g_awlen[c]), .s_axib_awsize(g_awsize[c]),
            .s_axib_awburst(g_awburst[c]), .s_axib_awvalid(g_awvalid[c]),
            .s_axib_awready(g_awready[c]), .s_axib_wdata(g_wdata[c]),
            .s_axib_wstrb(g_wstrb[c]), .s_axib_wlast(g_wlast[c]),
            .s_axib_wvalid(g_wvalid[c]), .s_axib_wready(g_wready[c]),
            .s_axib_bid(g_bid[c]), .s_axib_bresp(g_bresp[c]),
            .s_axib_bvalid(g_bvalid[c]), .s_axib_bready(g_bready[c]),
            .s_axib_arid(g_arid[c]), .s_axib_araddr(g_araddr[c][15:0]),
            .s_axib_arlen(g_arlen[c]), .s_axib_arsize(g_arsize[c]),
            .s_axib_arburst(g_arburst[c]), .s_axib_arvalid(g_arvalid[c]),
            .s_axib_arready(g_arready[c]), .s_axib_rid(g_rid[c]),
            .s_axib_rdata(g_rdata[c]), .s_axib_rresp(g_rresp[c]),
            .s_axib_rlast(g_rlast[c]), .s_axib_rvalid(g_rvalid[c]),
            .s_axib_rready(g_rready[c]),
            .mv_busy_bm(mvb_bm[c]), .xpush_valid(xpv[c]), .xpush_idx(xpi[12*c +: 12]), .xpush_data(xpd[32*c +: 32]), .xpush_room(xpr[c]), .xpush_busy(xpb[c]),   // R3-8: as create_project.tcl wires it
            .ui_clk(ui_clk_c[c]), .ui_rstn(ui_rstn),
            .m_axi_araddr(w_araddr), .m_axi_arlen(w_arlen),
            .m_axi_arsize(w_arsize), .m_axi_arburst(w_arburst),
            .m_axi_arvalid(w_arvalid), .m_axi_arready(w_arready),
            .m_axi_rdata(w_rdata), .m_axi_rresp(w_rresp),
            .m_axi_rlast(w_rlast), .m_axi_rvalid(w_rvalid),
            .m_axi_rready(w_rready)
        );

        seq_mem_file #(.ADDR_W(34), .DATA_W(512), .LAT(WLAT), .NREG(1),
                       .QD(4),
                       .A0("base"), .S0(wimg_sfx(c)), .B0(W_BASE)) u_wmem (
            .aclk(ui_clk_c[c]), .aresetn(ui_rstn),
            .araddr(w_araddr), .arlen(w_arlen), .arsize(w_arsize),
            .arburst(w_arburst), .arvalid(w_arvalid), .arready(w_arready),
            .rdata(w_rdata), .rresp(w_rresp), .rlast(w_rlast),
            .rvalid(w_rvalid), .rready(w_rready),
            .n_beats(w_nbeats[c]), .n_miss(w_nmiss[c]),
            // S3: the weight images stay READ-ONLY (spec 8.3); the state
            // window is its own instance, u_smem, below.
            .win_base(34'd0), .win_len(34'd0),
            .awaddr(34'd0), .awlen(8'd0), .awvalid(1'b0),
            .awready(nc_wawr[c]),
            .wdata(512'd0), .wstrb(64'd0), .wlast(1'b0), .wvalid(1'b0),
            .wready(nc_wwr[c]), .bresp(nc_wbresp[c]), .bvalid(nc_wbv[c]),
            .bready(1'b0), .n_wbeats(nc_wwb[c])
        );

    end
    for (genvar c = NMV; c < 4; c++) begin : g_mv_off
        assign w_nbeats[c] = 64'd0;
        assign w_nmiss[c]  = 64'd0;
        assign mvb_bm[c]   = 1'b0; assign xpr[c] = 1'b1; assign xpb[c] = 1'b0;   // R3-8: an unbuilt slot has room and is never busy
    end

    // ==================================================================
    // S3: the DDR STATE REGION the layer's own AXI4 master reads and writes
    // ==================================================================
    // `tb/seq_mem_file.sv` was read-only until S3; the write window is its
    // extension, and ONE instance owns it (spec 8.3).  It is a SEPARATE
    // 512-bit instance from the per-channel weight models above, not a
    // shared one, because a single AXI4 slave cannot serve two masters
    // without an arbiter this testbench does not need: the layer never
    // addresses the weight pack (every access outside [win_base, win_base +
    // win_len) is a $fatal in the model) and matvec_chan never addresses
    // the state region (the planner puts it 2 GiB above EMB_BASE on the
    // last channel, sw/hwmap.plan_state_base).  The window's address comes
    // from the artifact, through the .chip golden's SBASE line.
    logic [33:0] sm_araddr, sm_awaddr;
    logic [7:0]  sm_arlen, sm_awlen;
    logic        sm_arvalid, sm_arready, sm_rlast, sm_rvalid, sm_rready;
    logic [1:0]  sm_rresp, sm_bresp;
    logic [511:0] sm_rdata, sm_wdata;
    logic [63:0] sm_wstrb;
    logic        sm_awvalid, sm_awready, sm_wlast, sm_wvalid, sm_wready;
    logic        sm_bvalid, sm_bready;
    logic [63:0] sm_nbeats, sm_nmiss, sm_nwbeats;
    logic [33:0] win_base, win_len;

    seq_mem_file #(.ADDR_W(34), .DATA_W(512), .LAT(WLAT), .NREG(0),
                   .QD(4), .WR(1'b1),
                   .AS("base"), .SS(".state.bin")) u_smem (
        .aclk(clk), .aresetn(rstn),
        .araddr(sm_araddr), .arlen(sm_arlen), .arsize(3'b110),
        .arburst(2'b01), .arvalid(sm_arvalid), .arready(sm_arready),
        .rdata(sm_rdata), .rresp(sm_rresp), .rlast(sm_rlast),
        .rvalid(sm_rvalid), .rready(sm_rready),
        .win_base(win_base), .win_len(win_len),
        .awaddr(sm_awaddr), .awlen(sm_awlen), .awvalid(sm_awvalid),
        .awready(sm_awready),
        .wdata(sm_wdata), .wstrb(sm_wstrb), .wlast(sm_wlast),
        .wvalid(sm_wvalid), .wready(sm_wready),
        .bresp(sm_bresp), .bvalid(sm_bvalid), .bready(sm_bready),
        .n_beats(sm_nbeats), .n_miss(sm_nmiss), .n_wbeats(sm_nwbeats)
    );

    // ---------------- the REAL layer engine ----------------
    layer_chan #(
        .RSQRT_ROM("../rtl/roms/rsqrt_rom.hex"),
        .SIGMOID_ROM("../rtl/roms/sigmoid_pair_rom.hex"),
        .SOFTPLUS_ROM("../rtl/roms/softplus_pair_rom.hex"),
        .EXP2_ROM("../rtl/roms/exp2_pair_rom.hex"),
        .RECIP_ROM("../rtl/roms/recip_rom.hex")
    ) u_layer (
        .aclk(clk), .aresetn(rstn),
        .s_axil_awaddr(f_awaddr[5]), .s_axil_awvalid(f_awvalid[5]),
        .s_axil_awready(f_awready[5]), .s_axil_wdata(f_wdata[5]),
        .s_axil_wstrb(f_wstrb[5]), .s_axil_wvalid(f_wvalid[5]),
        .s_axil_wready(f_wready[5]), .s_axil_bresp(f_bresp[5]),
        .s_axil_bvalid(f_bvalid[5]), .s_axil_bready(f_bready[5]),
        .s_axil_araddr(f_araddr[5]), .s_axil_arvalid(f_arvalid[5]),
        .s_axil_arready(f_arready[5]), .s_axil_rdata(f_rdata[5]),
        .s_axil_rresp(f_rresp[5]), .s_axil_rvalid(f_rvalid[5]),
        .s_axil_rready(f_rready[5]),
        .s_axib_awid(g_awid[4]), .s_axib_awaddr(g_awaddr[4]),
        .s_axib_awlen(g_awlen[4]), .s_axib_awsize(g_awsize[4]),
        .s_axib_awburst(g_awburst[4]), .s_axib_awvalid(g_awvalid[4]),
        .s_axib_awready(g_awready[4]), .s_axib_wdata(g_wdata[4]),
        .s_axib_wstrb(g_wstrb[4]), .s_axib_wlast(g_wlast[4]),
        .s_axib_wvalid(g_wvalid[4]), .s_axib_wready(g_wready[4]),
        .s_axib_bid(g_bid[4]), .s_axib_bresp(g_bresp[4]),
        .s_axib_bvalid(g_bvalid[4]), .s_axib_bready(g_bready[4]),
        .s_axib_arid(g_arid[4]), .s_axib_araddr(g_araddr[4]),
        .s_axib_arlen(g_arlen[4]), .s_axib_arsize(g_arsize[4]),
        .s_axib_arburst(g_arburst[4]), .s_axib_arvalid(g_arvalid[4]),
        .s_axib_arready(g_arready[4]), .s_axib_rid(g_rid[4]),
        .s_axib_rdata(g_rdata[4]), .s_axib_rresp(g_rresp[4]),
        .s_axib_rlast(g_rlast[4]), .s_axib_rvalid(g_rvalid[4]),
        .s_axib_rready(g_rready[4]),
        // S3: the state DMA's 512-bit master (rtl/state_dma.sv).  ARSIZE /
        // ARBURST / the IDs are tied constant in rtl/layer_chan_ipi.v and
        // are therefore not ports here; the model is given the same
        // constants.
        .m_axis_awaddr(sm_awaddr), .m_axis_awlen(sm_awlen),
        .m_axis_awvalid(sm_awvalid), .m_axis_awready(sm_awready),
        .m_axis_wdata(sm_wdata), .m_axis_wstrb(sm_wstrb),
        .m_axis_wlast(sm_wlast), .m_axis_wvalid(sm_wvalid),
        .m_axis_wready(sm_wready),
        .m_axis_bresp(sm_bresp), .m_axis_bvalid(sm_bvalid),
        .m_axis_bready(sm_bready),
        .m_axis_araddr(sm_araddr), .m_axis_arlen(sm_arlen),
        .m_axis_arvalid(sm_arvalid), .m_axis_arready(sm_arready),
        .m_axis_rdata(sm_rdata), .m_axis_rresp(sm_rresp),
        .m_axis_rlast(sm_rlast), .m_axis_rvalid(sm_rvalid),
        .m_axis_rready(sm_rready)
    );

    // ==================================================================
    // RUNG3: on the full-chip path EVERY burst response must be OKAY.
    // In particular a MOVY burst issued right after a CMD retires must not
    // take a spurious SLVERR from the layer shim's !busy gate (S6/R8) — the
    // model_v2 stream hits that race thousands of times, so make it fail
    // AT THE CYCLE IT HAPPENS rather than as a count at the end.
    // ==================================================================
    /* verilator lint_off BLKSEQ */
    always @(posedge clk) if (rstn) begin
        if (mb_bvalid && mb_bready && (mb_bresp != 2'b00))
            $fatal(1, "burst BRESP=%02b at t=%0t (layer/mvchan window rejected a write burst — CMD->MOVY race or window bounds)",
                   mb_bresp, $time);
        if (mb_rvalid && mb_rready && (mb_rresp != 2'b00))
            $fatal(1, "burst RRESP=%02b at t=%0t (layer/mvchan window rejected a read burst — CMD->MOVX race or window bounds)",
                   mb_rresp, $time);
    end
    /* verilator lint_on BLKSEQ */

    // ==================================================================
    // golden (<prefix>.chip)
    // ==================================================================
    int unsigned exp_mem_a [MAXMEM];
    int unsigned exp_mem_v [MAXMEM];
    int unsigned n_exp_mem;
    int unsigned exp_xrf [8];
    int unsigned exp_tok [4096];
    int unsigned n_exp_tok;
    // G4a: the golden holders for the banked KV append counters.  These
    // were `[6]` — the PRE-G3.4 six-bank geometry — while
    // `rtl/layer_chan.sv`'s `tcnt_bank` is `[N_KV][NKVH]` = [8][4] since
    // G3.4, and the `.chip` golden writes one TCNT line per bank.  The
    // parser indexed them with `a[2:0]`, so a 9B artifact's TCNT lines for
    // kv slots 6 and 7 were written OUT OF BOUNDS and dropped while
    // `n_exp_tcnt` still counted them; the compare below then read an
    // out-of-bounds ZERO and reported the RTL's CORRECT 6/6 as
    // "expected 0/0".  Measured on the first full 9B replay,
    // evidence/qwen9b/g4/016_full_model_replay.log — the golden file itself
    // says `TCNT 6 6 6` and `TCNT 7 6 6`, so neither the RTL nor the
    // reference was wrong; the checker could not hold the answer.
    //
    // This is the same class the MEM parser's own comment names below — "a
    // golden the checker cannot index is a broken gate, not a mismatch" —
    // and it gets the same two-part repair: size the holders from the DUT's
    // bank count, and REFUSE a golden line that does not fit instead of
    // truncating its index.
    // G4a fix round 1 (I6): and the SECOND dimension too.  The holders were
    // a pair of 1-D arrays that could only ever carry kvheads 0 and 1, so
    // kvheads 2 and 3 were never in the golden and never compared -- the
    // other half of the same geometry, invisible because the golden did not
    // carry the columns rather than because the checker dropped them.
    localparam int TB_KV_NB = 8;          // == rtl/layer_chan.sv N_KV
    localparam int TB_KVH   = 4;          // == rtl/layer_chan.sv NKVH
    int unsigned exp_tcnt  [TB_KV_NB][TB_KVH];
    int unsigned n_exp_tcnt;
    // S3: the DDR state region's golden.  One SMEM record per block the
    // launch STORED -- `SMEM <hex addr> <hex len> <hex fnv1a64>`, the
    // grammar tb/scripts/gen_seq_chip_vectors.py writes.  FNV-1a 64 is the
    // TRANSPORT (a golden that carried 155 MiB of bytes would be
    // unreadable); byte equality is the check, and `seq_mem_file.win_fnv`
    // computes the hash in the TB exactly as the generator does in Python.
    localparam int NSMEM = 512;
    longint      smem_a [NSMEM];
    longint      smem_n [NSMEM];
    logic [63:0] smem_h [NSMEM];
    int unsigned n_smem;
    int unsigned exp_eout, exp_amaxi, exp_amaxv, exp_pc, exp_nrec;
    int unsigned have_eout, have_amax;

    // previous launch's post-state, re-checked just before the next START
    int unsigned prev_mem_a [MAXMEM];
    int unsigned prev_mem_v [MAXMEM];
    int unsigned n_prev_mem;
    int unsigned prev_tcnt [TB_KV_NB][TB_KVH];
    int unsigned n_prev_tcnt;
    // ...and the mirror is checked against the DUT ITSELF, not tied by a
    // parser: a testbench cannot read another module's localparam, but this
    // file already uses hierarchical references into `u_layer` everywhere,
    // so `$size` on the real array is the strongest form available.  If
    // `layer_chan` ever re-banks, this fires instead of the holders quietly
    // going one geometry stale again.
    // A `{"...", "..."}` CONCATENATION IS NOT A FORMAT STRING.  Verilator
    // takes the concatenation as a packed VALUE and prints it as a decimal,
    // so the refusal arrives as a 200-digit number and the reader learns
    // nothing.  Measured, not reasoned: the round-1 RED control
    // (evidence/qwen9b/g4/042_red_two_column_chip.log) refused correctly and
    // printed exactly that.  Long messages therefore go in a `$display` and
    // `$fatal` carries ONE literal.
    initial begin
        if ($size(u_layer.tcnt_bank) != TB_KV_NB) begin
            $display("tb_seq_chip: a .chip TCNT line for a bank past the end would be DROPPED");
            $fatal(1, "layer_chan has %0d KV banks, TCNT golden holders sized %0d",
                   $size(u_layer.tcnt_bank), TB_KV_NB);
        end
        // ...and BOTH dimensions, because pinning only the first is how
        // kvheads 2/3 went unchecked for a whole geometry (I6).
        if ($size(u_layer.tcnt_bank[0]) != TB_KVH) begin
            $display("tb_seq_chip: the kvheads past the holder would never be compared");
            $fatal(1, "layer_chan has %0d kvheads per bank, TCNT golden holders carry %0d",
                   $size(u_layer.tcnt_bank[0]), TB_KVH);
        end
    end

    // per-launch descriptor
    int unsigned cur_off, cur_nrec, cur_idx, n_launch_exp;
    string       cur_kind;

    // RDWIN address-window read witnesses
    localparam int NRW = 4;
    logic [33:0] rw_lo [NRW];
    logic [33:0] rw_hi [NRW];
    int unsigned rw_min [NRW];
    int unsigned rw_max [NRW];
    int unsigned rw_n   [NRW];
    int unsigned n_rw;

    int    chip_fd;
    string seqp, basep;
    int    wdog_ms;

    // ------------------------------------------------------------------
    // BM1 (spec docs/superpowers/specs/2026-09-24-board-idle-counters-
    // design.md §3): the SEQ 0x100 idle-counter block (docs/SEQ_ISA.md
    // B16), read at HALT through the DUT's real AXI-Lite slave.  GATED by
    // +bm: absent it, none of this reads, prints or checks anything, and
    // the host BFM issues exactly the transactions it always did.
    //   +bm                  read + print the block after every launch, and
    //                        check every counter against the testbench's
    //                        OWN negedge sampler below (exact; $fatal on
    //                        any difference)
    //   +bm_expect=<file>    also check against the census's totals
    //                        ("NAME VALUE" lines, evidence/qwen9b/bm/
    //                        bm1_expect.py); single-launch streams only
    // The sampler is the census's method (tb/seq_timeline.svh): negedge,
    // while dut.busy_r, the same DUT signals.  Its counts are monotone since
    // t=0 (only the sampler advances them); a launch's figure is the
    // difference from the snapshot the host loop takes just before its
    // START, so the host loop never writes a sampler count.
    // ------------------------------------------------------------------
    localparam int BM_NSH = 17;
    localparam int BM_NEXP = 32;
    bit      bm_en = 1'b0;
    int      bm_nexp = 0;
    string   bm_exp_name [BM_NEXP];
    longint  bm_exp_val  [BM_NEXP];
    longint  bm_sh  [BM_NSH];      // written ONLY by the sampler
    longint  bm_sh0 [BM_NSH];      // written ONLY by the host loop

    // ------------------------------------------------------------------
    // read ONE launch section out of the (already open) .chip file.
    // A single-launch .chip has no LAUNCH/ENDL keys at all: it is simply
    // one section terminated by END, with NREC standing in for the
    // record count and offset 0.
    // ------------------------------------------------------------------
    task automatic read_section(output bit got, output bit last);
        int r;
        int unsigned a, b, d, e, nkey;
        string key;
        begin
            n_exp_mem = 0; n_exp_tok = 0; n_exp_tcnt = 0; n_rw = 0;
            n_smem = 0;
            exp_pc = 0; exp_eout = 0; exp_amaxi = 0; exp_amaxv = 0;
            have_eout = 0; have_amax = 0;
            for (int i = 0; i < 8; i++) exp_xrf[i] = 0;
            got = 1'b0; last = 1'b0; nkey = 0;
            forever begin
                r = $fscanf(chip_fd, "%s", key);
                if (r != 1) begin last = 1'b1; break; end       // EOF
                if (key == "END")  begin last = 1'b1; break; end
                if (key == "ENDL") break;
                nkey++;
                if (key == "NREC") begin
                    r = $fscanf(chip_fd, "%d", exp_nrec);
                    cur_nrec = exp_nrec; cur_off = 0;
                end else if (key == "NLAUNCH") begin
                    r = $fscanf(chip_fd, "%d", n_launch_exp);
                    nkey--;                     // a file header, not a section
                end else if (key == "LAUNCH") begin
                    r = $fscanf(chip_fd, "%d %d %d", cur_idx, cur_off,
                                cur_nrec);
                    exp_nrec = cur_nrec;
                end else if (key == "KIND") begin
                    r = $fscanf(chip_fd, "%s", cur_kind);
                end else if (key == "PC") begin
                    r = $fscanf(chip_fd, "%d", exp_pc);
                end else if (key == "EOUT") begin
                    r = $fscanf(chip_fd, "%h", exp_eout); have_eout = 1;
                end else if (key == "AMAX") begin
                    r = $fscanf(chip_fd, "%h %h", exp_amaxi, exp_amaxv);
                    have_amax = 1;
                end else if (key == "XRF") begin
                    r = $fscanf(chip_fd, "%d %h", a, d);
                    exp_xrf[a[2:0]] = d;
                end else if (key == "TOK") begin
                    r = $fscanf(chip_fd, "%h", d);
                    exp_tok[n_exp_tok] = d; n_exp_tok++;
                end else if (key == "TCNT") begin
                    r = $fscanf(chip_fd, "%d", a);
                    // G4a: refuse, do not truncate.  `a[2:0]` silently
                    // aliased a kv slot the holder could not reach.
                    if (a >= TB_KV_NB)
                        $fatal(1, "TCNT kv slot %0d does not fit the %0d-bank golden holder",
                               a, TB_KV_NB);
                    // G4a fix round 1 (I6): read ALL TB_KVH columns, and
                    // REFUSE a golden that carries fewer.  A stale two-column
                    // .chip is a build product from before this change, and
                    // half-checking it silently is exactly the class this
                    // whole block exists to stop -- `make -C tb
                    // seq_chip_vectors*` regenerates it.
                    for (int h = 0; h < TB_KVH; h++) begin
                        r = $fscanf(chip_fd, "%d", b);
                        if (r != 1) begin
                            $display("regenerate the .chip golden: make -C tb seq_chip_vectors*");
                            $fatal(1, "TCNT kv slot %0d carries fewer than %0d counters",
                                   a, TB_KVH);
                        end
                        exp_tcnt[a][h] = b;
                    end
                    if (a >= n_exp_tcnt) n_exp_tcnt = a + 1;
                end else if (key == "RDWIN") begin
                    r = $fscanf(chip_fd, "%h %h %d %d", a, b, d, e);
                    if (n_rw >= NRW) $fatal(1, "too many RDWIN lines");
                    rw_lo[n_rw] = {2'd0, a}; rw_hi[n_rw] = {2'd0, b};
                    rw_min[n_rw] = d; rw_max[n_rw] = e;
                    n_rw++;
                end else if (key == "MEM") begin
                    r = $fscanf(chip_fd, "%h %h", a, d);
                    if (n_exp_mem >= MAXMEM) $fatal(1, "too many MEM lines");
                    // ... and the COUNT was already guarded; the ADDRESS was
                    // not, which is what let a silently-truncated index read
                    // the wrong word for a whole simulation.  A golden the
                    // checker cannot index is a broken gate, not a mismatch.
                    if (a >= MAXMEM)
                        $fatal(1, "MEM address %0h does not fit the %0d-word scratchpad (%0d-bit checker index)",
                               a, MAXMEM, MEMAW);
                    exp_mem_a[n_exp_mem] = a; exp_mem_v[n_exp_mem] = d;
                    n_exp_mem++;
                end else if (key == "SMEM") begin
                    longint sa, sn;
                    logic [63:0] sh;
                    r = $fscanf(chip_fd, "%h %h %h", sa, sn, sh);
                    if (r != 3) $fatal(1, "bad SMEM line");
                    if (n_smem >= NSMEM) $fatal(1, "too many SMEM lines");
                    smem_a[n_smem] = sa; smem_n[n_smem] = sn;
                    smem_h[n_smem] = sh; n_smem++;
                end else if (key == "SBASE") begin
                    // the DDR state region, in 64 KiB units:
                    // SB_DN / SB_KV / SB_CV and the region's length.  The
                    // PROGRAM writes the three CSRs itself (the S record of
                    // the .txt, three CSRWRs in the .seq); this line is what
                    // the TB's DDR model needs to know WHERE the window is.
                    r = $fscanf(chip_fd, "%h %h %h %h", a, b, d, e);
                    if (r != 4) $fatal(1, "bad SBASE line");
                    win_base = {2'd0, a} << 16;
                    win_len  = {2'd0, e} << 16;
                    if (({2'd0, b} << 16) < win_base
                        || ({2'd0, d} << 16) < win_base)
                        $fatal(1, "SBASE: KV/CV below the DN base");
                    nkey--;                     // a file header, not a section
                end else if (key == "EMBLOG2") begin
                    r = $fscanf(chip_fd, "%d", a);
                    if (a < 8 || a > 13)
                        $fatal(1, "EMBLOG2 %0d outside seq_unit's legal 8..13", a);
                    exp_emblog2 = a;
                    nkey--;                     // a file header, not a section
                end else if (key == "BASES") begin
                    // stream / blob / emb / weights — checked against the
                    // localparams above so a generator change cannot drift
                    r = $fscanf(chip_fd, "%h %h %h %h", a, b, d, e);
                    if ({32'd0, a} !== SEQ_STREAM_BASE
                        || {32'd0, b} !== SEQ_DATA_BASE
                        || {32'd0, d} !== EMB_BASE
                        || {32'd0, e} !== W_BASE)
                        $fatal(1, "BASES %08h/%08h/%08h/%08h disagree with the TB DDR plan", a, b, d, e);
                    nkey--;                     // a file header, not a section
                end else $fatal(1, "bad key '%s' in the .chip file", key);
            end
            got = (nkey != 0);
        end
    endtask

    // ==================================================================
    // host BFM (drive/sample at NEGEDGE only — TB discipline)
    // ==================================================================
    task automatic hwr(input int unsigned addr, input int unsigned data);
        begin
            @(negedge clk);
            h_awaddr = addr[11:0]; h_awvalid = 1'b1;
            h_wdata  = data;       h_wvalid  = 1'b1;
            h_bready = 1'b1;
            while (!(h_awready && h_wready)) @(negedge clk);
            @(negedge clk);
            h_awvalid = 1'b0; h_wvalid = 1'b0;
            while (!h_bvalid) @(negedge clk);
            @(negedge clk);
            h_bready = 1'b0;
        end
    endtask

    task automatic hrd(input int unsigned addr, output int unsigned data);
        begin
            @(negedge clk);
            h_araddr = addr[11:0]; h_arvalid = 1'b1; h_rready = 1'b1;
            while (!h_arready) @(negedge clk);
            @(negedge clk);
            h_arvalid = 1'b0;
            while (!h_rvalid) @(negedge clk);
            data = h_rdata;
            @(negedge clk);
            h_rready = 1'b0;
        end
    endtask

    // ==================================================================
    // continuous "the DUT was NEVER reset mid-run" assertion.  Gate I1's
    // whole claim is that a second START preserves context, so a reset
    // sneaking in would silently invalidate it.
    // ==================================================================
    logic rst_armed = 1'b0;
    always @(negedge clk) begin
        if (rst_armed && !(rstn && ui_rstn))
            $fatal(1, "DUT reset deasserted mid-run (rstn=%b ui_rstn=%b) — multi-launch continuity claim is void", rstn, ui_rstn);
    end

    // ------------------------------------------------------------------
    // RDWIN witnesses: count seq_unit DDR read BURSTS landing in a window.
    // Sampled at NEGEDGE (TB discipline): the AR handshake values in effect
    // at negedge N are the ones the DUT captures at posedge N+1, so every
    // accepted burst is counted exactly once.
    // ------------------------------------------------------------------
    logic rw_clr = 1'b0;
    always @(negedge clk) begin
        if (rw_clr) begin
            for (int k = 0; k < NRW; k++) rw_n[k] <= 32'd0;
        end else if (rstn && d_arvalid && d_arready) begin
            for (int k = 0; k < NRW; k++) begin
                if ((k < int'(n_rw)) && (d_araddr >= rw_lo[k])
                    && (d_araddr < rw_hi[k]))
                    rw_n[k] <= rw_n[k] + 32'd1;
            end
        end
    end

    // ==================================================================
    int unsigned cyc_start, cyc_end;

    initial begin
        /* verilator lint_off UNUSEDSIGNAL */
        int unsigned v, tok, nerr;
        /* verilator lint_on UNUSEDSIGNAL */
        int unsigned t_pc, t_st;
        int unsigned li, tot_tok, tot_cyc, lcyc;
        bit got, last;
        real cyc, recs;
        logic [63:0] lbase;

        h_awaddr = 0; h_awvalid = 0; h_wdata = 0; h_wvalid = 0; h_bready = 0;
        h_araddr = 0; h_arvalid = 0; h_rready = 0;
        nerr = 0; li = 0; tot_tok = 0; tot_cyc = 0;
        cur_off = 0; cur_nrec = 0; cur_idx = 0; cur_kind = "-";
        n_launch_exp = 1; n_prev_mem = 0; n_prev_tcnt = 0;
        n_smem = 0; win_base = 34'd0; win_len = 34'd0;
        for (int k = 0; k < NRW; k++) begin
            rw_lo[k] = '0; rw_hi[k] = '0;
            rw_min[k] = 0; rw_max[k] = 0;
        end
        n_rw = 0;

        if (!$value$plusargs("seq=%s", seqp)) $fatal(1, "need +seq=<prefix>");
        if (!$value$plusargs("base=%s", basep)) basep = seqp;
        if (!$value$plusargs("watchdog_ms=%d", wdog_ms)) wdog_ms = 600000;

        chip_fd = $fopen({seqp, ".chip"}, "r");
        if (chip_fd == 0) $fatal(1, "cannot open %s.chip", seqp);

        repeat (16) @(negedge clk);
        rstn    = 1'b1;
        ui_rstn = 1'b1;
        repeat (8) @(negedge clk);
        rst_armed = 1'b1;                  // from here on, no reset is legal

        hrd(32'h28, v);
        if (v !== 32'hFAB1_E5E0) $fatal(1, "SEQ IDENT = %08h", v);

        // ==============================================================
        // one iteration per launch section; the DUT is NEVER reset again
        // ==============================================================
        forever begin
            read_section(got, last);
            if (!got) break;

            $display("tb_seq_chip: launch %0d [%s] rec_off %0d, %0d records, %0d tokens, %0d scratch words, NMV=%0d WIMGPC=%0d LAT=%0d DDRLAT=%0d WLAT=%0d",
                     li, cur_kind, cur_off, cur_nrec,
                     n_exp_tok, n_exp_mem, NMV, WIMGPC, LAT, DDRLAT, WLAT);

            // ---- the previous launch's state must still be there -------
            if (li != 0) begin
                int unsigned ncarry;
                ncarry = 0;
                for (int s = 0; s < int'(n_prev_tcnt); s++) begin
                    bit ok;
                    ok = 1'b1;
                    for (int h = 0; h < TB_KVH; h++)
                        if ({22'd0, u_layer.tcnt_bank[s][h]}
                            !== prev_tcnt[s][h]) begin
                            $display("CARRY TCNT[%0d][kvhead %0d] = %0d, expected %0d",
                                     s, h, u_layer.tcnt_bank[s][h],
                                     prev_tcnt[s][h]);
                            nerr++;
                            ok = 1'b0;
                        end
                    if (ok) ncarry++;
                end
                for (int i = 0; i < int'(n_prev_mem); i++) begin
                    v = {16'd0, u_layer.smem_a[prev_mem_a[i][MEMAW-1:0]]}
                        & 32'hFFFF;
                    if (v !== (prev_mem_v[i] & 32'hFFFF)) begin
                        $display("CARRY MEM[%04h] = %04h, expected %04h",
                                 prev_mem_a[i], v, prev_mem_v[i] & 32'hFFFF);
                        nerr++;
                        if (nerr > 20) $fatal(1, "too many carry mismatches");
                    end else ncarry++;
                end
                if (nerr != 0)
                    $fatal(1, "%0d state word(s) did NOT survive to launch %0d",
                           nerr, li);
                $display("  carried into launch %0d: %0d state words (%0d TCNT banks + %0d scratch) still intact BEFORE START",
                         li, ncarry, n_prev_tcnt, n_prev_mem);
            end

            // ---- drain check + program + START, exactly as the host does
            // (sw/seq_run.seq_start_and_poll: XRF and TCNT_SEQ zeroed, then
            //  BASE/LEN/ENTRY, then CTRL.START) ---------------------------
            hrd(32'h1C, v);
            if (v != 32'd0) begin
                $display("OUT FIFO not drained before launch %0d (%0d)", li, v);
                nerr++;
            end
            lbase = 64'(SEQ_STREAM_BASE) + ({32'd0, cur_off} << 4);
            hwr(32'h08, lbase[31:0]);
            hwr(32'h0C, {30'd0, lbase[33:32]});
            hwr(32'h10, cur_nrec);
            hwr(32'h24, 32'h0);                      // ENTRY
            hwr(32'h20, 32'd0);                      // TCNT_SEQ
            // R-c wall 8: the EMB row stride, mirroring sw/seq_run.py's
            // program_emblog2().  Written unconditionally and read back, so
            // a stream whose geometry the DUT cannot serve fails loudly here
            // instead of silently fetching the wrong embedding row.
            hwr(32'h60, exp_emblog2);
            hrd(32'h60, v);
            if (v !== exp_emblog2)
                $fatal(1, "EMBLOG2 readback %0d != %0d (seq_unit rejected the row stride this artifact needs)",
                       v, exp_emblog2);
            for (int i = 0; i < 8; i++) hwr(32'h40 + 4 * i, 32'd0);

            @(negedge clk); rw_clr = 1'b1;
            @(negedge clk); rw_clr = 1'b0;
            @(negedge clk);
            if (bm_en) bm_snap();            // BM1: the sampler baseline
            cyc_start = int'($time / 4);
            hwr(32'h00, 32'h1);                      // START

            begin
                int unsigned guard;
                guard = 0;
                forever begin
                    hrd(32'h04, t_st);
                    if (t_st[2]) break;              // halted
                    if (t_st[1]) begin
                        hrd(32'h14, t_pc);
                        $fatal(1, "SEQ err_code %02h at pc %0d (STATUS %08h)",
                               t_st[31:24], t_pc, t_st);
                    end
                    guard++;
                    if (guard > 100_000_000)
                        $fatal(1, "SEQ never halted (STATUS %08h)", t_st);
                end
            end
            cyc_end = int'($time / 4);
            lcyc = cyc_end - cyc_start;
            tot_cyc = tot_cyc + lcyc;
            hrd(32'h14, t_pc);

            // ---------------- status ----------------
            if (t_st[31:24] != 8'd0)
                $fatal(1, "err_code %02h (STATUS %08h)", t_st[31:24], t_st);
            if (t_st[1]) $fatal(1, "unexpected err flag");
            if (t_pc !== exp_pc)
                $fatal(1, "launch %0d final pc %0d, expected %0d", li, t_pc,
                       exp_pc);

            // ---------------- XRF (SEQ CSR block) ----------------
            for (int i = 0; i < 8; i++) begin
                hrd(32'h40 + 4 * i, v);
                if (v[17:0] !== exp_xrf[i][17:0]) begin
                    $display("XRF[%0d] = %05h, expected %05h", i, v[17:0],
                             exp_xrf[i][17:0]);
                    nerr++;
                end
            end

            // ---------------- OUT FIFO tokens ----------------
            for (int i = 0; i < int'(n_exp_tok); i++) begin
                hrd(32'h18, tok);
                if (!tok[31]) $fatal(1, "OUT FIFO empty at token %0d", i);
                if (tok[17:0] !== exp_tok[i][17:0]) begin
                    $display("TOK[%0d] = %05h, expected %05h", i, tok[17:0],
                             exp_tok[i][17:0]);
                    nerr++;
                end else begin
                    $display("  TOK[%0d] = %05h (%0d) == golden OK", i,
                             tok[17:0], tok[17:0]);
                end
            end
            hrd(32'h1C, v);
            if (v != 32'd0) begin
                $display("OUT FIFO still holds %0d entries", v);
                nerr++;
            end
            tot_tok = tot_tok + n_exp_tok;

            // ---------------- banked layer state ----------------
            // The SEQ CSR block (0x00..0x5C above) is read through the DUT's
            // real AXI-Lite slave, exactly as the host does on silicon.  The
            // LAYER engine's own CSRs are NOT reachable from here: in this
            // testbench layer_chan's only AXI-Lite port is the fabric port
            // the sequencer owns, and the ISA forbids a second master
            // touching it while SEQ is busy.  Its architectural state is
            // therefore compared through hierarchical probes of the SAME
            // registers those CSRs return (0x20 TCNT -> tcnt_bank,
            // 0x1C EOUT -> eout_q, 0x28/0x2C AMAXI/AMAXV ->
            // alu_amax_idx/val).
            for (int s = 0; s < int'(n_exp_tcnt); s++) begin
                for (int h = 0; h < TB_KVH; h++) begin
                    if ({22'd0, u_layer.tcnt_bank[s][h]} !== exp_tcnt[s][h])
                        begin
                        $display("TCNT[kv %0d][kvhead %0d] = %0d, expected %0d",
                                 s, h, u_layer.tcnt_bank[s][h],
                                 exp_tcnt[s][h]);
                        nerr++;
                    end
                end
            end
            if (have_eout != 0) begin
                if ({28'd0, u_layer.eout_q} !== exp_eout) begin
                    $display("EOUT = %0d, expected %0d", u_layer.eout_q,
                             exp_eout);
                    nerr++;
                end
            end
            if (have_amax != 0) begin
                if (u_layer.alu_amax_idx !== exp_amaxi[17:0]) begin
                    $display("AMAXI = %05h, expected %05h",
                             u_layer.alu_amax_idx, exp_amaxi[17:0]);
                    nerr++;
                end
                if (unsigned'(u_layer.alu_amax_val) !== exp_amaxv) begin
                    $display("AMAXV = %08h, expected %08h",
                             u_layer.alu_amax_val, exp_amaxv);
                    nerr++;
                end
            end

            // ---------------- final scratchpad ----------------
            for (int i = 0; i < int'(n_exp_mem); i++) begin
                v = {16'd0, u_layer.smem_a[exp_mem_a[i][MEMAW-1:0]]} & 32'hFFFF;
                if (v !== (exp_mem_v[i] & 32'hFFFF)) begin
                    $display("MEM[%04h] = %04h, expected %04h",
                             exp_mem_a[i], v, exp_mem_v[i] & 32'hFFFF);
                    nerr++;
                    if (nerr > 20) $fatal(1, "too many scratch mismatches");
                end
            end

            // ---------------- DDR read-window witnesses ----------------
            for (int k = 0; k < int'(n_rw); k++) begin
                if (rw_n[k] < rw_min[k] || rw_n[k] > rw_max[k]) begin
                    $display("RDWIN[%0d] %08h..%08h saw %0d bursts, expected %0d..%0d",
                             k, rw_lo[k], rw_hi[k], rw_n[k],
                             rw_min[k], rw_max[k]);
                    nerr++;
                end else begin
                    $display("  RDWIN %08h..%08h: %0d burst(s) (want %0d..%0d) OK",
                             rw_lo[k], rw_hi[k], rw_n[k], rw_min[k],
                             rw_max[k]);
                end
            end

            if (nerr != 0) $fatal(1, "launch %0d: %0d comparison failures",
                                  li, nerr);

            // ---------------- keep this launch's state as the carry ----
            n_prev_tcnt = n_exp_tcnt;
            for (int s = 0; s < int'(n_exp_tcnt); s++) begin
                for (int h = 0; h < TB_KVH; h++)
                    prev_tcnt[s][h] = exp_tcnt[s][h];
            end
            n_prev_mem = n_exp_mem;
            for (int i = 0; i < int'(n_exp_mem); i++) begin
                prev_mem_a[i] = exp_mem_a[i]; prev_mem_v[i] = exp_mem_v[i];
            end

            // ---------------- the DDR state region ----------------
            // Every block this launch stored, hashed out of the TB's own
            // DDR model and compared with the reference executor's
            // (`ref/seq_model.StateRegion` -> gen_seq_chip_vectors).  A
            // store that never happened, or happened to the wrong block, is
            // caught HERE and not only by the token compare (spec 8.3).
            for (int i = 0; i < int'(n_smem); i++) begin
                logic [63:0] got;
                got = u_smem.win_fnv(smem_a[i], smem_n[i]);
                if (got !== smem_h[i]) begin
                    $display("SMEM %012h+%0h fnv1a64 %016h, expected %016h",
                             smem_a[i], smem_n[i], got, smem_h[i]);
                    nerr++;
                end
            end

            // ---------------- performance ----------------
            cyc  = real'(lcyc);
            recs = real'(cur_nrec);
            hrd(32'h2C, v);
            $display("SEQ-CHIP %s launch %0d [%s]: %0d records, %0d cycles (%0.2f cyc/rec, %0.3f ms @250MHz, PERF_CYC %0d)",
                     seqp, li, cur_kind, cur_nrec, lcyc, cyc / recs,
                     cyc / 250000.0, v);
            if (bm_en) bm_readout(int'(li));   // BM1 (+bm only)
            $display("LAUNCH %0d PASS: [%s] pc %0d, tokens %0d, tcnt %0d, scratch %0d, smem %0d",
                     li, cur_kind, exp_pc, n_exp_tok,
                     n_exp_tcnt, n_exp_mem, n_smem);
            li++;
            if (last) break;
        end
        $fclose(chip_fd);
        if (li == 0) $fatal(1, "%s.chip held no launch sections", seqp);
        if (li != n_launch_exp && n_launch_exp != 0)
            $fatal(1, "ran %0d launches, .chip declared %0d", li,
                   n_launch_exp);

        if (d_nmiss != 0) begin
            $display("record/const/emb DDR served %0d UNMAPPED beats", d_nmiss);
            nerr++;
        end
        // S3: the state region.  A read the window did not cover is an
        // address the layer's DMA computed wrong, and it must not be
        // reported as zeros.
        $display("  state: %0d read beats, %0d write beats, %0d unmapped",
                 sm_nbeats, sm_nwbeats, sm_nmiss);
        if (sm_nmiss != 0) begin
            $display("state DDR served %0d UNMAPPED beats (outside [%h, %h))",
                     sm_nmiss, win_base,
                     {30'd0, win_base} + {30'd0, win_len});
            nerr++;
        end
        if (nerr != 0) $fatal(1, "%0d comparison failures", nerr);

        hrd(32'h34, v); $display("  axil writes %0d", v);
        hrd(32'h38, v); $display("  axil reads  %0d", v);
        // SR13a: the SEQ_CAPS word (docs/SEQ_ISA.md v2.3 B17.0, SEQ 0x64),
        // read AFTER every launch and after the two AXI-Lite counters
        // above, so it cannot move a measured cycle or a printed count.
        // +caps_expect=<hex> makes a different word a failure.
        begin
            int unsigned caps_exp;
            hrd(32'h64, v); $display("  SEQ_CAPS %08h", v);
            if ($value$plusargs("caps_expect=%h", caps_exp)) begin
                if (v !== caps_exp)
                    $fatal(1, "SEQ_CAPS %08h != +caps_expect %08h", v, caps_exp);
                $display("  SEQ_CAPS %08h == +caps_expect %08h", v, caps_exp);
            end
        end
        $display("  burst: %0d write bursts (%0d beats), %0d read bursts (%0d beats), busy_wr %0d busy_rd %0d, decerr %0d non-OK %0d, BLAT=%0d",
                 bf_nwr, bf_nwbeat, bf_nrd, bf_nrbeat, bf_bwr, bf_brd,
                 bf_ndec, bf_nslv, BLAT);
        if (bf_ndec != 32'd0)
            $fatal(1, "%0d burst decode holes (the S4 map is wrong)", bf_ndec);
        if (bf_nslv != 32'd0)
            $fatal(1, "%0d non-OK burst responses (SLVERR/DECERR on the data path)",
                   bf_nslv);
        if (bf_nidm != 32'd0)
            $fatal(1, "%0d burst id-echo mismatches", bf_nidm);
        hrd(32'h3C, v); $display("  fetch-empty stall cycles %0d", v[31:1]);
        // R-c: weight beats are per-CHANNEL counters and this line used to
        // print only channel 0, which reads as a fabric total and is not one.
        // Sum across the elaborated channels and show the split.
        begin
            longint unsigned wb_tot, wm_tot;
            string wb_split;
            wb_tot = 0; wm_tot = 0; wb_split = "";
            for (int c = 0; c < NMV; c++) begin
                wb_tot += w_nbeats[c];
                wm_tot += w_nmiss[c];
                wb_split = {wb_split, $sformatf("%s%0d", (c == 0) ? "" : "/",
                                                w_nbeats[c])};
            end
            $display("  ddr beats %0d (miss %0d), weight beats %0d total across %0d chan (miss %0d) [%s]",
                     d_nbeats, d_nmiss, wb_tot, NMV, wm_tot, wb_split);
        end
        $display("  DUT held in reset 0 times after t=0 (rst_armed asserted before launch 0, never violated)");
        // n_prev_* hold the LAST launch's checked counts (the exp_* arrays
        // were cleared by the terminating read_section call).
        $display("TB_SEQ_CHIP PASS: %s (launches %0d, %0d cycles total, scratch %0d/launch, tokens %0d, tcnt %0d)",
                 seqp, li, tot_cyc, n_prev_mem, tot_tok, n_prev_tcnt);
        $finish;
    end

    // watchdog (simulated wall-clock, like tb_layer_chan)
    initial begin
        int wd_ms;
        wd_ms = 600000;
        void'($value$plusargs("watchdog_ms=%d", wd_ms));
        #(wd_ms * 1ms);
        $display("WATCHDOG (%0d ms): seq pc probe busy=%0b halted=%0b err=%0b",
                 wd_ms, seq_busy, seq_halted, seq_err);
        $fatal(1, "tb_seq_chip: watchdog");
    end

    // ==================================================================
    // BM1: the idle-counter readout and its testbench-side reference.
    // See the declaration block above for the plusargs.  Sampler indices:
    //   0 busy cycles (= PERF_CYC)   1 any engine busy   2..5 engine c busy
    //   6 mover on FENCE   7 mover on MOVX/MVGO/MOVY   8 (7) AND any engine
    //   9 ist == I_MOVER  10 OP_EMB records latched   11 mover on MOVX
    //  12 mover on MOVY   13 mover busy (census MOVER)
    //  14 MOVER & no R beat & any engine   (the census's 013 I-2 quantity)
    //  15 mover on FENCE & any engine & no R beat
    //  16 mover on work & any engine & an R beat
    // (14 = 8 - 16 + 15 exactly: the census's I-2 and the spec's C7 differ
    // by the FENCE cycles with an engine busy but no beat, and the work
    // cycles with a beat — both are counted so the difference is explained,
    // not assumed.)
    // ==================================================================
    localparam logic [31:0] BM_IDENT_EXP = 32'hFAB1_B301;
    logic [3:0]  bm_mvb;
    logic [63:0] bm_wbprev [4];
    for (genvar bc = 0; bc < 4; bc++) begin : g_bm_mvb
        if (bc < NMV) begin : g_on
            assign bm_mvb[bc] = g_mv[bc].u_mv.cdc_sync_stat[0];
        end else begin : g_off
            assign bm_mvb[bc] = 1'b0;
        end
    end

    initial begin
        string path, nm;
        int    fd, r;
        longint val;
        string line;
        for (int k = 0; k < BM_NSH; k++) bm_sh[k] = 64'd0;
        for (int c = 0; c < 4; c++) bm_wbprev[c] = 64'd0;
        if ($test$plusargs("bm")) bm_en = 1'b1;
        if ($value$plusargs("bm_expect=%s", path)) begin
            fd = $fopen(path, "r");
            if (fd == 0) begin
                $display("tb_seq_chip: +bm_expect path was %s", path);
                $fatal(1, "tb_seq_chip: cannot open the BM1 expect file");
            end
            while (!$feof(fd)) begin
                line = "";
                r = $fgets(line, fd);
                if (r == 0 || line.len() == 0 || line.substr(0, 0) == "#")
                    continue;
                r = $sscanf(line, "%s %d", nm, val);
                if (r != 2) continue;
                if (bm_nexp >= BM_NEXP)
                    $fatal(1, "tb_seq_chip: too many BM1 expect lines");
                bm_exp_name[bm_nexp] = nm;
                bm_exp_val[bm_nexp]  = val;
                bm_nexp++;
            end
            $fclose(fd);
            $display("tb_seq_chip: BM1 counters ON, %0d expected values from %s",
                     bm_nexp, path);
        end else if (bm_en) begin
            $display("tb_seq_chip: BM1 counters ON (no expect file)");
        end
    end

    /* verilator lint_off BLKSEQ */
    always @(negedge clk) if (bm_en && rstn && dut.busy_r) begin
        bit str, any, mb, fen;
        str = 1'b0;
        for (int c = 0; c < 4; c++) begin
            if (w_nbeats[c] != bm_wbprev[c]) str = 1'b1;
            bm_wbprev[c] = w_nbeats[c];
        end
        any = |bm_mvb;
        mb  = dut.mv_busy;
        fen = (dut.mv_op == 2'd3);
        bm_sh[0] += 64'd1;
        if (any) bm_sh[1] += 64'd1;
        for (int c = 0; c < 4; c++) if (bm_mvb[c]) bm_sh[2 + c] += 64'd1;
        if (mb && fen)          bm_sh[6] += 64'd1;
        if (mb && !fen)         bm_sh[7] += 64'd1;
        if (mb && !fen && any)  bm_sh[8] += 64'd1;
        if (int'(dut.ist) == 17) bm_sh[9] += 64'd1;
        if (dut.rec_valid && (dut.r_op == 8'h06)) bm_sh[10] += 64'd1;
        if (mb && (dut.mv_op == 2'd0)) bm_sh[11] += 64'd1;
        if (mb && (dut.mv_op == 2'd2)) bm_sh[12] += 64'd1;
        if (mb)                         bm_sh[13] += 64'd1;
        if (mb && !str && any)          bm_sh[14] += 64'd1;
        if (mb && fen && any && !str)   bm_sh[15] += 64'd1;
        if (mb && !fen && any && str)   bm_sh[16] += 64'd1;
    end
    /* verilator lint_on BLKSEQ */

    task automatic bm_snap();
        for (int k = 0; k < BM_NSH; k++) bm_sh0[k] = bm_sh[k];
    endtask

    // one counter: RTL register vs its reference, printed on one line
    task automatic bm_cmp(input int li, input string name,
                          input longint rtl, input longint ref_v,
                          input string what, inout int nbad);
        $display("BM1 L%0d %s rtl %0d %s %0d %s", li, name, rtl, what,
                 ref_v, (rtl == ref_v) ? "OK" : "MISMATCH");
        if (rtl != ref_v) nbad++;
    endtask

    task automatic bm_readout(input int li);
        int unsigned r [14];
        int unsigned pcyc, hi, out;
        longint d [BM_NSH];
        longint rv, xv;
        longint mx, sm;
        int nbad;
        bit found;
        string nm;
        nbad = 0;
        for (int i = 0; i < 14; i++) hrd(32'h100 + 4 * i, r[i]);
        hrd(32'h1FC, hi);
        hrd(32'h200, out);
        hrd(32'h2C, pcyc);
        for (int k = 0; k < BM_NSH; k++) d[k] = bm_sh[k] - bm_sh0[k];
        $display("BM1 L%0d BEGIN  (0x100..0x134 read after HALT; ref = the testbench's negedge sampler)", li);
        bm_cmp(li, "BM_IDENT", longint'(r[0]), longint'(BM_IDENT_EXP), "const", nbad);
        bm_cmp(li, "PERF_CYC", longint'(pcyc), d[0], "ref", nbad);
        bm_cmp(li, "BM_MVANY", longint'(r[1]), d[1], "ref", nbad);
        bm_cmp(li, "BM_MV0", longint'(r[2]), d[2], "ref", nbad);
        bm_cmp(li, "BM_MV1", longint'(r[3]), d[3], "ref", nbad);
        bm_cmp(li, "BM_MV2", longint'(r[4]), d[4], "ref", nbad);
        bm_cmp(li, "BM_MV3", longint'(r[5]), d[5], "ref", nbad);
        bm_cmp(li, "BM_FENCE", longint'(r[6]), d[6], "ref", nbad);
        bm_cmp(li, "BM_MVWORK", longint'(r[7]), d[7], "ref", nbad);
        bm_cmp(li, "BM_MVWORK_ANY", longint'(r[8]), d[8], "ref", nbad);
        bm_cmp(li, "BM_IMOVER", longint'(r[9]), d[9], "ref", nbad);
        bm_cmp(li, "BM_STEPS", longint'(r[10]), d[10], "ref", nbad);
        bm_cmp(li, "RSVD_12C", longint'(r[11]), 64'd0, "const", nbad);
        bm_cmp(li, "BM_MOVX", longint'(r[12]), d[11], "ref", nbad);
        bm_cmp(li, "BM_MOVY", longint'(r[13]), d[12], "ref", nbad);
        bm_cmp(li, "RSVD_1FC", longint'(hi), 64'd0, "const", nbad);
        bm_cmp(li, "OUTSIDE_200", longint'(out), 64'hDEAD_C0DE, "const", nbad);
        $display("BM1 L%0d INFO   MVGO work (MVWORK-MOVX-MOVY) %0d  ref MOVER %0d  ref I2 %0d  ref FENCE&ANY&!STR %0d  ref WORK&ANY&STR %0d  L_LCYC %0d",
                 li, longint'(r[7]) - longint'(r[12]) - longint'(r[13]),
                 d[13], d[14], d[15], d[16], u_layer.lcyc);
        // the spec's §3.3 D identities, on the RTL registers themselves
        mx = 0; sm = 0;
        for (int c = 0; c < 4; c++) begin
            if (longint'(r[2 + c]) > mx) mx = longint'(r[2 + c]);
            sm += longint'(r[2 + c]);
        end
        bm_cmp(li, "ID_FENCE+WORK", longint'(r[6]) + longint'(r[7]), d[13],
               "MOVER", nbad);
        bm_cmp(li, "ID_WORK>=W_ANY", (r[7] >= r[8]) ? 64'd1 : 64'd0, 64'd1, "want", nbad);
        bm_cmp(li, "ID_MAX<=ANY<=S",
               ((mx <= longint'(r[1])) && (longint'(r[1]) <= sm)) ? 64'd1 : 64'd0, 64'd1,
               "want", nbad);
        bm_cmp(li, "ID_MOVX+MOVY<=W",
               (longint'(r[12]) + longint'(r[13]) <= longint'(r[7])) ? 64'd1 : 64'd0, 64'd1,
               "want", nbad);
        bm_cmp(li, "ID_I2=C7-WS+FN", d[14], d[8] - d[16] + d[15], "ref", nbad);
        // the census's own totals, when given
        if (bm_nexp != 0) begin
            if (li != 0)
                $fatal(1, "tb_seq_chip: +bm_expect covers single-launch streams only");
            for (int e = 0; e < bm_nexp; e++) begin
                nm = bm_exp_name[e];
                xv = bm_exp_val[e];
                found = 1'b1;
                case (nm)
                    "PERF_CYC":      rv = longint'(pcyc);
                    "BM_MVANY":      rv = longint'(r[1]);
                    "BM_MV0":        rv = longint'(r[2]);
                    "BM_MV1":        rv = longint'(r[3]);
                    "BM_MV2":        rv = longint'(r[4]);
                    "BM_MV3":        rv = longint'(r[5]);
                    "BM_FENCE":      rv = longint'(r[6]);
                    "BM_MVWORK":     rv = longint'(r[7]);
                    "BM_MVWORK_ANY": rv = longint'(r[8]);
                    "BM_IMOVER":     rv = longint'(r[9]);
                    "BM_STEPS":      rv = longint'(r[10]);
                    "BM_MOVX":       rv = longint'(r[12]);
                    "BM_MOVY":       rv = longint'(r[13]);
                    "L_LCYC":        rv = longint'(u_layer.lcyc);
                    "CENSUS_I2":     rv = d[14];
                    default:         found = 1'b0;
                endcase
                if (!found) begin
                    $display("tb_seq_chip: unknown BM1 expect name %s", nm);
                    $fatal(1, "tb_seq_chip: bad BM1 expect file");
                end
                bm_cmp(li, {"EXP_", nm}, rv, xv, "census", nbad);
            end
        end
        if (nbad != 0) begin
            $display("BM1 L%0d FAIL: %0d check(s) differ", li, nbad);
            $fatal(1, "tb_seq_chip: BM1 counter check FAILED");
        end
        $display("BM1 L%0d PASS: every counter equals its reference%s", li,
                 (bm_nexp != 0) ? " and the census total" : "");
    endtask

    // ==================================================================
    // BN1: the whole-token TIMELINE CENSUS — a READ-ONLY instrument,
    // gated by +timeline=<csv>.  Absent the plusarg it does nothing and
    // this testbench is behaviourally unchanged (that is BN1's control).
    // It drives no DUT signal; it samples at NEGEDGE like everything else
    // here.  See tb/seq_timeline.svh's header for the classification.
    // ==================================================================
`include "seq_timeline.svh"


    // ==================================================================
    // R3-8 (docs/SEQ_ISA.md v2.3 B17.3): THE X-PUSH BUS, wired between
    // seq_unit and the NMV real matvec_chan instances exactly as
    // synth/scripts/create_project.tcl wires seq_0 and mvchan_0..3 (per
    // channel c: valid, idx[12c +: 12], data[32c +: 32] forward; room, busy
    // back); an unbuilt slot ties room = 1 and busy = 0 (line 415).  The
    // first chip-TB TOP change of the round — R3-9a's rung 1 (shipped / r1 /
    // r2 streams cycle-identical on this top) is its STOP gate.  Appended
    // below every cited line; the connections ride on lines 239, 382, 415
    // and the per-channel ui_clk on lines 106, 111, 383, 395.
    //
    // +xp_hold=<chan>:<start>:<cycles> (DEFAULT OFF) — the TB-only
    // per-channel ui_clk hold for R3-9a's back-pressure case: channel
    // <chan>'s ui_clk (its matvec engine, its XWIN FIFO's read side and its
    // weight memory) is held LOW for <cycles> aclk cycles from aclk cycle
    // <start> (counted from reset release), so its XWIN FIFO fills, its
    // skid's room drops and a broadcast must stall all four channels.
    // ui_clk_c[c] = ui_clk & ~xph_l[c] (line 106), the ORIGINAL generator
    // untouched (line 111); xph_l is an ICG-style enable latched on ui_clk's
    // NEGEDGE, so it changes only while ui_clk is low and the gated clock
    // cannot glitch.  With the plusarg absent xph_l stays 0 and every
    // ui_clk_c[c] is ui_clk.  (A first cut toggled a 4-bit clock vector bit
    // by bit in one delay process; its channels never saw the doorbell and
    // the smoke hung, n3030 / n3037 — the single-generator form is the one
    // proven cycle-identical, n3036.)
    //
    // Sim-only checks, end to end (the commit contract across the real
    // flops, BD-equivalent wiring and both modules):
    //   * the ONE parameter set: seq_movers' XP_FWD_STAGES / XP_RET_STAGES
    //     equal every built matvec_chan's (XP_RT and XP_INFLIGHT are derived
    //     from them);
    //   * at every broadcast's retire (seq_movers `done` with bcast_q), each
    //     built channel's push-leg XWIN FIFO writes equal the words the bus
    //     carried to it — every word is in the FIFO when the MOVX retires;
    //   * a push-leg FIFO write AFTER that retire (before the next push) is
    //     a $fatal: no word may land after its broadcast retired.
    // ==================================================================
    /* verilator lint_off UNUSEDSIGNAL */
    logic [3:0]   xpv, xpr, xpb;
    logic [47:0]  xpi;
    logic [127:0] xpd;
    /* verilator lint_on UNUSEDSIGNAL */
    logic [3:0]   xph_on = 4'd0;
    always @(negedge ui_clk) xph_l <= xph_on;   // the gate enable, changed only while ui_clk is low
    int           xph_chan = -1;
    int unsigned  xph_start = 0, xph_len = 0, xph_cyc = 0, xph_held = 0;
    int unsigned  xp_sent [4], xp_land [4];
    bit   [3:0]   xp_closed = 4'hF;
    int unsigned  xp_nretire = 0, xp_nwords = 0;
    // R3-9a (the R3-8 review's I-1): the X_END-exit check's own state
    int unsigned  xp_cyc [4], xp_lastland [4];
    int           xp_minmargin = -1;
    int unsigned  xp_nexit = 0;

    initial begin
        string sa;
        int unsigned a0, a1, a2;
        for (int c = 0; c < 4; c++) begin xp_sent[c] = 0; xp_land[c] = 0; xp_cyc[c] = 0; xp_lastland[c] = 0; end
        if ($value$plusargs("xp_hold=%s", sa)) begin
            if ($sscanf(sa, "%d:%d:%d", a0, a1, a2) != 3 || a0 >= 32'(NMV))
                $fatal(1, "+xp_hold=<built chan>:<start aclk cycle>:<cycles>, got '%s' (NMV=%0d)",
                       sa, NMV);
            xph_chan = int'(a0); xph_start = a1; xph_len = a2;
            $display("tb_seq_chip: +xp_hold: channel %0d ui_clk held low for %0d aclk cycles from cycle %0d",
                     xph_chan, xph_len, xph_start);
        end
        if ((g_mv[0].u_mv.XP_FWD_STAGES != dut.u_mov.XP_FWD_STAGES)
            || (g_mv[0].u_mv.XP_RET_STAGES != dut.u_mov.XP_RET_STAGES))
            $fatal(1, "R3-8: the x-push register stages disagree: seq_movers %0d/%0d, matvec_chan %0d/%0d",
                   dut.u_mov.XP_FWD_STAGES, dut.u_mov.XP_RET_STAGES,
                   g_mv[0].u_mv.XP_FWD_STAGES, g_mv[0].u_mv.XP_RET_STAGES);
    end

    /* verilator lint_off BLKSEQ */
    always @(negedge clk) begin
        if (rstn) begin
            xph_cyc++;
            if ((xph_chan >= 0) && (xph_cyc >= xph_start)
                && (xph_cyc < xph_start + xph_len)) begin
                xph_on = 4'd1 << xph_chan;
                xph_held++;
            end else xph_on = 4'd0;
        end
    end

    // the end-to-end commit contract (sampled at NEGEDGE: xf_push_p is the
    // push leg's combinational FIFO write of this cycle)
    for (genvar c = 0; c < NMV; c++) begin : g_xpchk
        always @(negedge clk) if (rstn) begin
            if (xpv[c]) begin
                xp_sent[c]++;
                xp_closed[c] = 1'b0;
                if (c == 0) xp_nwords++;
            end
            if (g_mv[c].u_mv.xf_push_p) begin
                if (xp_closed[c])
                    $fatal(1, "R3-8 COMMIT: channel %0d: a push-leg word (idx %0d) entered the XWIN FIFO after its broadcast retired",
                           c, g_mv[c].u_mv.xf_din_p[43:32]);
                xp_land[c]++;
                xp_lastland[c] = xp_cyc[c];
            end
            // R3-9a (the R3-8 review's I-1 RULING): landed == sent AT THE
            // X_END EXIT — the cycle seq_movers leaves X_END for X_STAT
            // (rtl/seq_movers.sv, X_END: wr_idle && bw_idle && xp_done), i.e.
            // the cycle the push leg's commit wait (XP_RT, then all four busy
            // inputs low) declares every word committed.  The `done` compare
            // below comes four STATUS round trips later and cannot see an
            // XP_RT that is too short; this one can.  Counted: the words the
            // bus carried to channel c (xpv[c]) and the push-leg XWIN FIFO
            // writes (xf_push_p, this cycle's write included: it commits on
            // the same edge the mover leaves X_END).  The margin is the exit
            // cycle minus the last word's FIFO-write cycle.
            if (dut.u_mov.bcast_q && (dut.u_mov.st == dut.u_mov.X_END)
                && dut.u_mov.wr_idle && dut.u_mov.bw_idle && dut.u_mov.xp_done) begin
                if (xp_land[c] != xp_sent[c])
                    $fatal(1, "R3-9a COMMIT AT X_END EXIT: channel %0d: the mover left X_END with %0d of %0d pushed words in the XWIN FIFO (XP_RT too short)",
                           c, xp_land[c], xp_sent[c]);
                if ((xp_sent[c] != 0) && ((xp_minmargin < 0)
                    || (int'(xp_cyc[c] - xp_lastland[c]) < xp_minmargin)))
                    xp_minmargin = int'(xp_cyc[c] - xp_lastland[c]);
                if (c == 0) xp_nexit++;
            end
            xp_cyc[c]++;
            if (dut.u_mov.done && dut.u_mov.bcast_q) begin
                if (xp_land[c] != xp_sent[c])
                    $fatal(1, "R3-8 COMMIT: channel %0d: the broadcast retired with %0d of %0d pushed words in the XWIN FIFO",
                           c, xp_land[c], xp_sent[c]);
                xp_closed[c] = 1'b1;
                if (c == 0) xp_nretire++;
            end
        end
    end
    /* verilator lint_on BLKSEQ */

    final
        if ((xp_nretire != 0) || (xph_chan >= 0))
            $display("tb_seq_chip R3-8: %0d broadcasts retired, %0d words pushed per channel, every one in its XWIN FIFO at retire%s",
                     xp_nretire, xp_nwords,
                     (xph_chan >= 0) ? $sformatf("; +xp_hold channel %0d held %0d cycles",
                                                 xph_chan, xph_held) : "");
    final
        if (xp_nexit != 0)
            $display("tb_seq_chip R3-9a: %0d broadcast X_END exits checked, landed == sent on every built channel at each; min margin (exit cycle - last push-leg FIFO write) %0d cycles",
                     xp_nexit, xp_minmargin);

endmodule

`default_nettype wire
