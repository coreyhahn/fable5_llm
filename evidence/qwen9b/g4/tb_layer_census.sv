// tb_layer_census — G4b Step 3: the LAYER-TERM CYCLE CENSUS.
//
// The feasibility study says the layer term "has no measurement" and that its
// coefficient is a two-point fit intercept.  This testbench turns it into a
// measured number: it replays a REAL gen_*_script.py command stream against
// the REAL rtl/layer_chan and reads the LCYC CSR (0x34, "cycles elapsed while
// busy==1" — rtl/layer_chan.sv:28, the `lcyc` counter declared at
// rtl/layer_chan.sv:475 and incremented at rtl/layer_chan.sv:1055) after
// EVERY command, so each command's BUSY cycles are the difference between
// two consecutive reads.
// The engine is idle between commands by construction (the TB polls STATUS to
// retire one command before dispatching the next), so the differences
// partition the engine's whole busy time with nothing unattributed.
//
// It is tb_layer_chan's replay loop, unchanged in what it drives and checks —
// every R / E / A record is still compared bit-exactly, so a census run is
// also a correctness run and a census that silently replayed the wrong thing
// cannot pass.  What is ADDED is the LCYC read, the per-opcode accumulators,
// the per-forward-step split (an `M` record starts a step) and +stopm.
// What is REMOVED is tb_layer_chan's two directed modes (+dnbank / +envtest),
// which replay no script and have nothing to census.
//
// P_DN_PIPE WAS the one reason this file existed as a separate top: G4b's
// two runs needed layer_chan's DN_PIPE set per run and Verilator's -G reaches
// the TOP module only.  S2 RETIRED DN_PIPE, DN_RLAT and DN_P2WAIT
// (rtl/layer_chan.sv:377) — the 24-bank DN array they described is in DDR
// now, and `dn_step` is instantiated at the literal pair (RLAT 2, P2_WAIT 0)
// at rtl/layer_chan.sv:627, which is the pair Task 10 measured at 1,798
// cycles/head.  The parameter is KEPT HERE, accepted and ignored, only
// because `run_g4b_census.sh` (Task 12's runner, outside S4's commit block)
// still passes `-GP_DN_PIPE`; the census report says so in as many words, so
// a stale knob can never look live.  G4b's option-(ii) scratch-copy path in
// that runner is likewise dead — the localparam it seds no longer exists —
// and S4 runs the SHIPPING configuration (`p2wait -1`) only.
//
// WHAT S4 ADDS (spec 2026-09-04 state-spill §8.5).  The state the layer used
// to hold in URAM/BRAM is in DDR, moved by SLD/SST (ops 13/14) on a SECOND
// lane.  So this census now measures TWO lanes and says which is which:
//
//   * `LCYC` (0x34) counts `busy_cmp` ONLY (spec A1.4,
//     rtl/layer_chan.sv:1055).  An SLD/SST therefore costs its DISPATCH in
//     this column and nothing more — the transfer is not on this lane.
//   * `SDMA_CYC` (0x74, rtl/layer_chan.sv:1056) counts `busy_dma`.  That is
//     where the transfer lands, and it is read after every command by the
//     same cut, so the two lanes partition the same timeline.
//
// The engine is drained between commands here (the replay polls STATUS until
// `busy_any` — busy_cmp | busy_dma — is low before dispatching the next
// record), which is what makes the LCYC differences attributable at all.  It
// also means THIS TESTBENCH CANNOT OBSERVE AN F1 OR F2 STALL: a
// load-before-use hold needs a compute command to arrive while its SLD is
// still in flight, and nothing here ever overlaps them.  The `excess` column
// (total − count × min) is where such a stall WOULD appear, and the gate doc
// reports it as the bound it is rather than as a stall count.
//
// S4 FIX ROUND 1 (review I4): THE NON-DRAINING MODE, `+nodrain=1`.
// The paragraph above is the reason the brief's "count of F1/F2 stalls
// actually taken" could not be produced: a draining census cannot make one.
// `+nodrain=1` replays the SAME script with the SAME bit-exact checks but
// with the SEQUENCER'S back-pressure rule instead of the census's drain --
// `rtl/seq_unit.sv:1187-1205` (I_CMDPOLLW) proceeds as soon as the layer's
// cmd_cnt has advanced and NEVER looks at STATUS bit 0, and cmd_cnt advances
// for an SLD/SST at ENQUEUE (rtl/layer_chan.sv:1459-1464), so the next
// record is dispatched while the transfer is still moving.  The queue cannot
// be overrun: a fifth SLD/SST against a full queue is HELD at dispatch
// (rtl/layer_chan.sv:1448-1457) and cmd_cnt does not advance until it is
// enqueued, so polling cmd_cnt IS the back-pressure.
//
// In that mode the two fence holds become reachable and are counted per
// cycle, by hierarchical reference to the dispatcher's own arm conditions:
//
//   F1 HOLD    a compute command held at dispatch because its slot has an
//              SLD queued or in flight (rtl/layer_chan.sv:1486-1491).  It
//              raises busy_cmp, so LCYC COUNTS IT -- the report prints both
//              so a reader can subtract.
//   F2 HOLD    an SLD/SST held at dispatch because the four-deep DMA queue
//              is full (rtl/layer_chan.sv:1448-1457).  Also busy_cmp, also
//              inside LCYC.
//   F2 FENCE   the spec's F2 proper: a transfer at the HEAD of the queue
//              waiting because a compute command holds its slot
//              (rtl/layer_chan.sv:2086-2095, gating the start arm at
//              rtl/layer_chan.sv:2151).  This one is on the DMA lane and is
//              NOT in LCYC.
//
// Per-command COST attribution is meaningless once commands overlap the DMA,
// so it is NOT printed in this mode; per-step totals and the per-opcode HOLD
// table are.  The bit-exact R/E/A checks are unchanged, which makes a PASS
// here the first model-scale test of the fences under back-to-back dispatch.
//
//   +script=<file>     the .txt command script (required)
//   +emb=<file.bin>    embedding table for M records
//   +embn=<words>      words per embedding row (default 1024; 9B is 4096)
//   +stopm=<n>         stop just BEFORE the n-th M record, i.e. replay the
//                      preamble plus (n-1) forward steps.  0 = run to Q.
//   +census=<file>     write the census table here as well as to stdout
//   +watchdog_ms=<n>
//
//   +state=<prefix>    the DDR state region's initial image,
//                      <prefix>.state.bin (S4; required by any stream that
//                      carries SLD/SST, i.e. every v2.1 stream)
//   +nodrain=1         (S4 fix round 1) dispatch back to back, as the
//                      sequencer does; per-step totals and fence holds only
//   -GP_LAT=<n>        the modelled read latency of the state window
//                      (tb/seq_mem_file.sv); 8 is the census's own default
//                      and 40 is what tb/tb_seq_chip.sv:436 instantiates
//   -GP_DN_PIPE=<n>    ACCEPTED AND IGNORED (S2 retired layer_chan's
//                      DN_PIPE); run_g4b_census.sh still passes it
`timescale 1ns/1ps
// THE TWO FILES S2/S3 ADDED THAT `run_g4b_census.sh`'s FILE LIST PREDATES.
// That runner is Task 12's and is outside S4's commit block, so the census
// reaches its own dependencies here instead of editing it:
//   rtl/state_dma.sv     the DMA engine layer_chan instantiates (S2)
//   tb/seq_mem_file.sv   the DDR model behind the state-DMA master (S3)
// Both paths are relative to the CURRENT DIRECTORY, which is `tb/` because
// run_g4b_census.sh:77 cd's there before invoking verilator: Verilator
// searches the cwd and -I paths and NEVER the including file's own
// directory (measured on 5.020).  Run from anywhere else the error names
// the missing include — a clear failure, not a wrong number.
`include "../rtl/state_dma.sv"
// The width suppressions around seq_mem_file are the ones tb/Makefile
// already applies to THE SAME FILE: every build there passes `-Wall
// $(XLIB)` (tb/Makefile:226, :719) and that -f file carries
// -Wno-WIDTHEXPAND / -Wno-WIDTHTRUNC.  run_g4b_census.sh does not pass
// XLIB, so the two warning classes are turned off HERE, over the include
// and nothing else -- the census TB's own code stays strict -Wall.
/* verilator lint_off WIDTHEXPAND */
/* verilator lint_off WIDTHTRUNC */
`include "seq_mem_file.sv"
/* verilator lint_on WIDTHTRUNC */
/* verilator lint_on WIDTHEXPAND */
module tb_layer_census #(
    parameter int P_DN_PIPE = 2,
    // S4 fix round 1 (review I4): the modelled read latency of the state
    // window.  8 is what this census has always instantiated; 40 is what
    // tb/tb_seq_chip.sv:436 gives the SAME window (WLAT, tb/tb_seq_chip.sv:69)
    // in the chip replay, so a run at 40 is the like-for-like companion of
    // the chip number.
    parameter int P_LAT     = 8
);
    logic aclk = 0;
    /* verilator lint_off BLKSEQ */
    always #2 aclk = ~aclk;
    /* verilator lint_on BLKSEQ */
    logic aresetn = 0;

    logic [11:0] awaddr;  logic awvalid; logic awready;
    logic [31:0] wdata;   logic [3:0] wstrb; logic wvalid; logic wready;
    logic [1:0]  bresp;   logic bvalid;  logic bready = 0;
    logic [11:0] araddr;  logic arvalid; logic arready;
    logic [31:0] rdata;   logic [1:0] rresp; logic rvalid; logic rready = 0;
    /* verilator lint_off UNUSEDSIGNAL */
    wire [1:0] unused_resp = bresp | rresp;
    /* verilator lint_on UNUSEDSIGNAL */

    /* verilator lint_off UNUSEDSIGNAL */
    wire        nc_awready, nc_wready, nc_bvalid, nc_arready, nc_rvalid,
                nc_rlast;
    wire [0:0]  nc_bid, nc_rid;
    wire [1:0]  nc_bresp, nc_rresp;
    wire [31:0] nc_rdata;
    /* verilator lint_on UNUSEDSIGNAL */

    layer_chan #(
        .RSQRT_ROM("../rtl/roms/rsqrt_rom.hex"),
        .SIGMOID_ROM("../rtl/roms/sigmoid_pair_rom.hex"),
        .SOFTPLUS_ROM("../rtl/roms/softplus_pair_rom.hex"),
        .EXP2_ROM("../rtl/roms/exp2_pair_rom.hex"),
        .RECIP_ROM("../rtl/roms/recip_rom.hex")
    ) dut (
        .aclk, .aresetn,
        .s_axil_awaddr(awaddr), .s_axil_awvalid(awvalid), .s_axil_awready(awready),
        .s_axil_wdata(wdata), .s_axil_wstrb(wstrb), .s_axil_wvalid(wvalid),
        .s_axil_wready(wready),
        .s_axil_bresp(bresp), .s_axil_bvalid(bvalid), .s_axil_bready(bready),
        .s_axil_araddr(araddr), .s_axil_arvalid(arvalid), .s_axil_arready(arready),
        .s_axil_rdata(rdata), .s_axil_rresp(rresp), .s_axil_rvalid(rvalid),
        .s_axil_rready(rready),
        .s_axib_awid(1'b0), .s_axib_awaddr(18'd0), .s_axib_awlen(8'd0),
        .s_axib_awsize(3'd2), .s_axib_awburst(2'b01), .s_axib_awvalid(1'b0),
        .s_axib_awready(nc_awready),
        .s_axib_wdata(32'd0), .s_axib_wstrb(4'd0), .s_axib_wlast(1'b0),
        .s_axib_wvalid(1'b0), .s_axib_wready(nc_wready),
        .s_axib_bid(nc_bid), .s_axib_bresp(nc_bresp),
        .s_axib_bvalid(nc_bvalid), .s_axib_bready(1'b0),
        .s_axib_arid(1'b0), .s_axib_araddr(18'd0), .s_axib_arlen(8'd0),
        .s_axib_arsize(3'd2), .s_axib_arburst(2'b01), .s_axib_arvalid(1'b0),
        .s_axib_arready(nc_arready),
        .s_axib_rid(nc_rid), .s_axib_rdata(nc_rdata),
        .s_axib_rresp(nc_rresp), .s_axib_rlast(nc_rlast),
        .s_axib_rvalid(nc_rvalid), .s_axib_rready(1'b0),
        // S2/S3: the state DMA's 512-bit master.  ARSIZE/ARBURST and the
        // IDs are tied constant in rtl/layer_chan_ipi.v, so the model is
        // given the same constants here (tb/tb_layer_chan.sv does the same).
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
    // S4: THE DDR STATE REGION, behind the layer's own AXI4 master.
    // ==================================================================
    // The same `tb/seq_mem_file.sv` window tb/tb_layer_chan.sv:99-113 and
    // tb/tb_seq_chip.sv use: file-backed reads out of the artifact's own
    // `<prefix>.state.bin` (so the conv taps an SLD brings in are the ones
    // `seed_conv` put in the image, not a zero-filled BFM) plus a RAM
    // overlay for the writes an SST makes.  `win_base`/`win_len` come from
    // the script's own S record (B15.3), so the script and the model
    // cannot name different addresses.  `+state=<prefix>` selects the file.
    //
    // WHY `include` AND NOT THE FILE LIST.  The file list lives in
    // `evidence/qwen9b/g4/run_g4b_census.sh` (Task 12's runner), which is
    // NOT in S4's commit block; the include reaches the model without
    // editing it, and it resolves because that runner runs verilator from
    // `tb/` (run_g4b_census.sh:77) — Verilator searches the CURRENT
    // DIRECTORY and -I paths, never the including file's own directory
    // (measured on 5.020).  Run from anywhere else the error names the
    // missing include, which is a clear failure rather than a wrong number.
    logic [33:0]  sm_araddr, sm_awaddr;
    logic [7:0]   sm_arlen, sm_awlen;
    logic         sm_arvalid, sm_arready, sm_rlast, sm_rvalid, sm_rready;
    logic [1:0]   sm_rresp, sm_bresp;
    logic [511:0] sm_rdata, sm_wdata;
    logic [63:0]  sm_wstrb;
    logic         sm_awvalid, sm_awready, sm_wlast, sm_wvalid, sm_wready;
    logic         sm_bvalid, sm_bready;
    logic [63:0]  sm_nbeats, sm_nmiss, sm_nwbeats;
    logic [33:0]  win_base = 34'd0, win_len = 34'd0;

    seq_mem_file #(.ADDR_W(34), .DATA_W(512), .LAT(P_LAT), .NREG(0), .QD(4),
                   .WR(1'b1), .AS("state"), .SS(".state.bin")) u_smem (
        .aclk(aclk), .aresetn(aresetn),
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

    int errors = 0;

    // ---- AXI-Lite master tasks (negedge discipline, see tb_csr) ----
    task automatic wr32(input logic [11:0] addr, input logic [31:0] data);
        @(negedge aclk);
        awaddr = addr; awvalid = 1; wdata = data; wstrb = 4'hF; wvalid = 1;
        while (!(awready && wready)) @(negedge aclk);
        @(negedge aclk);
        awvalid = 0; wvalid = 0;
        while (!bvalid) @(negedge aclk);
        bready = 1;
        @(negedge aclk);
        bready = 0;
    endtask

    task automatic rd32(input logic [11:0] addr, output logic [31:0] data);
        @(negedge aclk);
        araddr = addr; arvalid = 1;
        while (!arready) @(negedge aclk);
        @(negedge aclk);
        arvalid = 0;
        while (!rvalid) @(negedge aclk);
        data = rdata;
        rready = 1;
        @(negedge aclk);
        rready = 0;
    endtask

    localparam logic [11:0] A_CMD = 12'h00, A_STAT = 12'h04, A_ARG0 = 12'h08,
                            A_ARG1 = 12'h0C, A_ARG2 = 12'h10, A_SPTR = 12'h14,
                            A_SWIN = 12'h18, A_EOUT = 12'h1C, A_TCNT = 12'h20,
                            A_LCYC = 12'h34,
                            A_LAYER = 12'h030, A_DNSB = 12'h05C,
                            A_TCNT2 = 12'h060,
                            // S3 (SEQ_ISA v2.1 B15.3): the three region bases
                            A_SB_DN = 12'h064, A_SB_KV = 12'h068,
                            A_SB_CV = 12'h06C,
                            // S2: the DMA lane's busy counter, LCYC's twin
                            // (rtl/layer_chan.sv:57, word 0x1D at :421)
                            A_SDMACYC = 12'h074;

    // ---- the census accumulators.  Index 0..15 is the CMD opcode field. ----
    longint unsigned op_cyc  [16];   // busy cycles attributed to this opcode
    longint unsigned op_n    [16];   // commands of this opcode
    longint unsigned op_min  [16];
    longint unsigned op_max  [16];
    // S4: the DMA lane.  LCYC counts busy_cmp ONLY (spec A1.4,
    // rtl/layer_chan.sv:1055), so an SLD/SST's LCYC delta is its DISPATCH
    // and nothing else -- the transfer itself runs on the DMA lane and is
    // counted by SDMA_CYC (rtl/layer_chan.sv:1056).  Both are read after
    // every command, so the two lanes are partitioned by the same cut.
    longint unsigned op_dma  [16];   // DMA-lane cycles charged to this opcode
    longint unsigned step_cyc[8];    // busy cycles per forward step (M..M)
    longint unsigned step_n  [8];    // commands per forward step
    longint unsigned step_dn [8];    // DNST commands per forward step
    longint unsigned step_sd [8];    // SLD+SST commands per forward step
    longint unsigned step_dma[8];    // DMA-lane cycles per forward step
    int   nstep = 0;                 // 0 = preamble, 1..N = forward steps
    longint unsigned lcyc_prev = 0;
    longint unsigned lcyc_tot  = 0;
    longint unsigned sdma_prev = 0;
    longint unsigned sdma_tot  = 0;

    // ==================================================================
    // S4 fix round 1 (review I4): +nodrain, and the FENCE HOLD counters.
    // ==================================================================
    int nodrain = 0;                 // +nodrain=1 -> the sequencer's rule
    int pollbk  = 20;                // negedges between STATUS polls
    int guard_max = 200000;          // poll iterations before "timeout"

    // A free-running TB clock counter, so a STEP can be given a WALL time
    // (first dispatch -> engine idle) as well as a busy time.  It is the
    // TB's own count and is never read out of the DUT.
    longint unsigned cyc = 0;
    always_ff @(posedge aclk) cyc <= cyc + 64'd1;

    // The two DISPATCH HOLDS, read as the dispatcher's own arm conditions so
    // the instrument cannot disagree with the RTL.  `IDLE` is the FIRST
    // member of layer_chan's 6-bit state enum (rtl/layer_chan.sv:1205-1206),
    // hence 0; the arms are, in order, rtl/layer_chan.sv:1447 (the DMA arm,
    // whose queue-full branch is rtl/layer_chan.sv:1448-1457) and
    // rtl/layer_chan.sv:1486 (F1).  BOTH raise busy_cmp, so BOTH are inside
    // LCYC and the report prints them beside it rather than instead of it.
    wire f1_hold_now = (dut.st == 6'd0) && !dut.cmd_is_dma
                       && (dut.cmd_go || dut.cmd_pend) && dut.cmd_f1_stall;
    wire f2_hold_now = (dut.st == 6'd0) && dut.cmd_is_dma
                       && (dut.cmd_go || dut.cmd_pend) && dut.dq_full
                       && !dut.sdma_range_bad && !dut.sdma_base_bad;
    // F2 PROPER (spec 2026-09-04 state-spill 5.4): a transfer at the HEAD of
    // the queue waiting because a compute command holds its slot
    // (rtl/layer_chan.sv:2086-2095, gating the start arm at
    // rtl/layer_chan.sv:2151).  This is the DMA lane, not the dispatch: it
    // does NOT raise busy_cmp and is NOT in LCYC, so it is reported
    // separately and never added to the other two.
    wire f2_fence_now = !dut.dma_act && !dut.dq_empty && dut.hd_f2;

    // BUSY_ANY: the cycles the engine was doing ANYTHING on either lane
    // (STATUS bit 0, rtl/layer_chan.sv:1145-1146).  It is what makes the
    // wall column readable: wall - busy_any is the time the engine spent
    // IDLE inside a step, which under +nodrain is almost entirely the
    // census's OWN scratch traffic (every R record is an AXI-Lite read and
    // the sequencer performs none of them).
    wire busy_any_now = dut.busy_cmp | dut.busy_dma;

    longint unsigned f1_cyc = 0, f2_cyc = 0, f2f_cyc = 0, bany_cyc = 0;
    always_ff @(posedge aclk) if (aresetn) begin
        if (f1_hold_now)  f1_cyc   <= f1_cyc   + 64'd1;
        if (f2_hold_now)  f2_cyc   <= f2_cyc   + 64'd1;
        if (f2_fence_now) f2f_cyc  <= f2f_cyc  + 64'd1;
        if (busy_any_now) bany_cyc <= bany_cyc + 64'd1;
    end

    // per-opcode hold attribution, taken as the DIFFERENCE across a command
    // exactly the way LCYC is, so a hold is charged to the command that was
    // held and to nothing else.
    longint unsigned op_f1c[16], op_f2c[16];   // hold cycles, by opcode
    longint unsigned op_f1n[16], op_f2n[16];   // commands that took >= 1
    longint unsigned f1_prev = 0, f2_prev = 0, bany_prev = 0;
    longint unsigned step_wall[8];             // first dispatch -> idle
    longint unsigned step_t0  [8];
    longint unsigned step_f1  [8], step_f2[8], step_bany[8];
    bit              step_closed[8];           // step_close() is idempotent

    string opname [16];
    initial begin
        int z;
        for (z = 0; z < 16; z++) begin
            op_cyc[z] = 0; op_n[z] = 0; op_min[z] = 64'hFFFF_FFFF; op_max[z] = 0;
            op_dma[z] = 0;
            op_f1c[z] = 0; op_f2c[z] = 0; op_f1n[z] = 0; op_f2n[z] = 0;
            opname[z] = "-";
        end
        for (z = 0; z < 8; z++) begin
            step_cyc[z] = 0; step_n[z] = 0; step_dn[z] = 0;
            step_sd[z] = 0; step_dma[z] = 0;
            step_wall[z] = 0; step_t0[z] = 0; step_f1[z] = 0; step_f2[z] = 0;
            step_bany[z] = 0; step_closed[z] = 1'b0;
        end
        opname[1]  = "VN";    opname[2]  = "VNW";  opname[3]  = "ROPET";
        opname[4]  = "ROPE";  opname[5]  = "CONVW"; opname[6] = "CONV";
        opname[7]  = "GATE";  opname[8]  = "DNST"; opname[9]  = "KVAP";
        opname[10] = "ATTN";  opname[11] = "ALU";  opname[12] = "DNZ";
        // S1/B15.1: the two state-DMA commands this amendment adds
        opname[13] = "SLD";   opname[14] = "SST";
    end

    // LCYC is a free-running busy counter cleared by ANY write; this TB never
    // writes it, so consecutive reads differ by exactly the busy cycles that
    // elapsed between them — which, read immediately after a command retires,
    // is that command's own cost.  32 bits wraps at 4.29e9 busy cycles; the
    // whole 6-step model stream is ~2e7, so no wrap is possible here, but the
    // arithmetic is done in longint and a decreasing read is a hard error
    // rather than a silent negative.
    task automatic census_take(input int op);
        logic [31:0] d;
        longint unsigned now, delta, dnow, ddelta, hdelta;
        rd32(A_LCYC, d);
        now = {32'b0, d};
        if (now < lcyc_prev) $fatal(1, "LCYC went backwards: %0d -> %0d",
                                    lcyc_prev, now);
        delta = now - lcyc_prev;
        lcyc_prev = now;
        lcyc_tot += delta;
        op_cyc[op] += delta;
        op_n[op]   += 1;
        if (delta < op_min[op]) op_min[op] = delta;
        if (delta > op_max[op]) op_max[op] = delta;
        step_cyc[nstep] += delta;
        step_n[nstep]   += 1;
        if (op == 8) step_dn[nstep] += 1;
        if (op == 13 || op == 14) step_sd[nstep] += 1;
        // S4: the DMA lane, read the same way and charged to the same
        // command.  Neither counter is ever written by this TB, so both
        // are free-running and consecutive reads differ by exactly the
        // cycles that lane was busy between them.
        rd32(A_SDMACYC, d);
        dnow = {32'b0, d};
        if (dnow < sdma_prev) $fatal(1, "SDMA_CYC went backwards: %0d -> %0d",
                                     sdma_prev, dnow);
        ddelta = dnow - sdma_prev;
        sdma_prev = dnow;
        sdma_tot += ddelta;
        op_dma[op] += ddelta;
        step_dma[nstep] += ddelta;
        // S4 fix round 1 (I4): the fence holds, differenced the same way.
        // These come from the TB's own per-cycle monitors, not from a CSR,
        // so they cost the dispatch nothing and are exact in both modes.
        hdelta = f1_cyc - f1_prev;
        f1_prev = f1_cyc;
        op_f1c[op] += hdelta;
        step_f1[nstep] += hdelta;
        if (hdelta != 0) op_f1n[op] += 1;
        hdelta = f2_cyc - f2_prev;
        f2_prev = f2_cyc;
        op_f2c[op] += hdelta;
        step_f2[nstep] += hdelta;
        if (hdelta != 0) op_f2n[op] += 1;
        step_bany[nstep] += bany_cyc - bany_prev;
        bany_prev = bany_cyc;
    endtask

    // Poll STATUS until the engine is fully idle (busy_any low).  Used at a
    // STEP BOUNDARY in +nodrain mode, so a step's WALL time runs from its
    // first dispatch to the completion of its last transfer -- the drain is
    // at the boundary only and never between two commands of a step.
    task automatic drain_idle();
        // only bit 0 (busy_any) is read here; rd32 needs the full word.
        /* verilator lint_off UNUSEDSIGNAL */
        logic [31:0] d;
        /* verilator lint_on UNUSEDSIGNAL */
        int g;
        g = 0;
        forever begin
            rd32(A_STAT, d);
            if (!d[0]) break;
            repeat (20) @(negedge aclk);
            g++;
            if (g > 200000) $fatal(1, "drain_idle timeout at step %0d", nstep);
        end
    endtask

    // close the step that is running: drain, then stamp its wall time.
    task automatic step_close();
        logic [31:0] d;
        longint unsigned now;
        if (step_n[nstep] != 0 && !step_closed[nstep]) begin
            drain_idle();
            // Fold the step's TAIL into its own totals: the cycles after its
            // last command retired, which under +nodrain are the transfers
            // still finishing.  In the draining mode the engine is already
            // idle here, so every delta below is 0 and nothing moves.
            rd32(A_LCYC, d);
            now = {32'b0, d};
            step_cyc[nstep] += now - lcyc_prev;
            lcyc_tot        += now - lcyc_prev;
            lcyc_prev = now;
            rd32(A_SDMACYC, d);
            now = {32'b0, d};
            step_dma[nstep] += now - sdma_prev;
            sdma_tot        += now - sdma_prev;
            sdma_prev = now;
            step_f1[nstep]   += f1_cyc - f1_prev;    f1_prev   = f1_cyc;
            step_f2[nstep]   += f2_cyc - f2_prev;    f2_prev   = f2_cyc;
            step_bany[nstep] += bany_cyc - bany_prev; bany_prev = bany_cyc;
            step_wall[nstep] = cyc - step_t0[nstep];
            step_closed[nstep] = 1'b1;
        end
    endtask

    localparam int TB_EMBLOG2_MAX = 13;   // == rtl/seq_unit.sv EMBLOG2_MAX
    localparam int EMB_N_MAX = (1 << TB_EMBLOG2_MAX) / 2;   // 4096 w = 8 KiB
    initial begin
        if (2 * EMB_N_MAX != (1 << TB_EMBLOG2_MAX))
            $fatal(1, "tb_layer_census: EMB_N_MAX must stay DERIVED");
    end
    int emb_n = 1024;
    int emb_row_b = 2 * 1024;
    logic [7:0] embrow [2 * EMB_N_MAX];
    int embfd;
    string script, embf, censusf;

    task automatic census_report(input int ncmd, input int nchk);
        int fd, z;
        fd = 0;
        if (censusf != "") begin
            fd = $fopen(censusf, "w");
            if (fd == 0) $fatal(1, "cannot write %s", censusf);
        end
        `define CEN(TXT) begin $display("%s", TXT); if (fd != 0) $fwrite(fd, "%s\n", TXT); end
        `CEN($sformatf("LAYER_CENSUS script=%s", script))
        // S2 RETIRED DN_PIPE / DN_RLAT / DN_P2WAIT from layer_chan
        // (rtl/layer_chan.sv:377): the 24-bank DN array they described is
        // in DDR now, and dn_step is instantiated at the literal pair
        // (RLAT 2, P2_WAIT 0) at rtl/layer_chan.sv:627.  There is nothing
        // left to read out of the DUT, so the census names the LITERALS
        // and says where they come from; `run_g4b_census.sh` still passes
        // -GP_DN_PIPE and it is ACCEPTED AND IGNORED, which this line says
        // rather than letting a stale knob look live.
        `CEN($sformatf("LAYER_CENSUS DN_RLAT=2 DN_P2WAIT=0 (rtl/layer_chan.sv:627 literals; P_DN_PIPE=%0d accepted and IGNORED, S2 retired it)",
                       P_DN_PIPE))
        `CEN($sformatf("LAYER_CENSUS state_region base=%0h len=%0h (S record), ddr beats r=%0d w=%0d miss=%0d, LAT=%0d modelled",
                       win_base, win_len, sm_nbeats, sm_nwbeats, sm_nmiss,
                       P_LAT))
        `CEN($sformatf("LAYER_CENSUS commands=%0d checks=%0d errors=%0d",
                       ncmd, nchk, errors))
        `CEN($sformatf("LAYER_CENSUS steps_replayed=%0d (0 = preamble only)", nstep))
        `CEN($sformatf("LAYER_CENSUS dispatch=%s",
                       (nodrain != 0)
                       ? "NODRAIN (the sequencer's rule: poll cmd_cnt only)"
                       : "DRAINING (poll cmd_cnt AND busy_any low)"))
        // S4 fix round 1 (I4): in +nodrain the per-command LCYC differences
        // no longer partition anything -- a command's read happens while the
        // DMA lane, and possibly the next dispatch's hold, are still running
        // -- so the per-opcode COST tables are suppressed and only the
        // per-step totals and the HOLD tables are printed.  The draining
        // mode's TABLES below are unchanged, column for column and row for
        // row; what the draining report gains is the `dispatch=` line above
        // and the three fence totals at the end, so the committed
        // `evidence/qwen9b/s4/census_s4shipped.txt` differs from what a
        // re-run would print by those four lines and by nothing else.
        if (nodrain != 0) begin
            `CEN("LAYER_CENSUS ---- per forward step (step 0 = the preamble) ----")
            `CEN("LAYER_CENSUS step    commands      wall_cyc      busy_any       busy_cyc       sdma_cyc     f1_hold    f2_hold")
            for (z = 0; z <= nstep; z++)
                `CEN($sformatf("LAYER_CENSUS %4d %11d %13d %13d %14d %14d %11d %10d",
                               z, step_n[z], step_wall[z], step_bany[z],
                               step_cyc[z], step_dma[z], step_f1[z],
                               step_f2[z]))
            `CEN("LAYER_CENSUS ---- per opcode: FENCE HOLD cycles (inside LCYC) ----")
            `CEN("LAYER_CENSUS  op name     count      f1_hold_cyc  f1_cmds      f2_hold_cyc  f2_cmds")
            for (z = 0; z < 16; z++)
                if (op_n[z] != 0)
                    `CEN($sformatf("LAYER_CENSUS %3d %-6s %8d %16d %8d %16d %8d",
                                   z, opname[z], op_n[z],
                                   op_f1c[z], op_f1n[z], op_f2c[z], op_f2n[z]))
            `CEN($sformatf("LAYER_CENSUS TOTAL_BUSY_CYCLES %0d", lcyc_tot))
            `CEN($sformatf("LAYER_CENSUS TOTAL_SDMA_CYCLES %0d", sdma_tot))
        end
        else begin
        `CEN("LAYER_CENSUS ---- per opcode: COMPUTE-lane cycles (LCYC, busy_cmp) ----")
        `CEN("LAYER_CENSUS  op name     count       total_cyc     mean      min      max        excess")
        for (z = 0; z < 16; z++)
            if (op_n[z] != 0)
                // `excess` is total - count*min: the cycles this opcode
                // spent ABOVE its own measured floor.  A command that
                // stalled at dispatch (F1's load-before-use hold, F2's
                // queue-full hold -- rtl/layer_chan.sv:1487-1493, where
                // busy_cmp is held high and LCYC therefore COUNTS the
                // stall) shows up here and nowhere else.  Data-dependent
                // work shows up here too, so a non-zero excess is a
                // CANDIDATE, not a stall; zero excess is conclusive the
                // other way.
                `CEN($sformatf("LAYER_CENSUS %3d %-6s %8d %15d %8d %8d %8d %13d",
                               z, opname[z], op_n[z], op_cyc[z],
                               op_cyc[z] / op_n[z], op_min[z], op_max[z],
                               op_cyc[z] - op_n[z] * op_min[z]))
        `CEN($sformatf("LAYER_CENSUS TOTAL_BUSY_CYCLES %0d", lcyc_tot))
        `CEN("LAYER_CENSUS ---- per opcode: DMA-lane cycles (SDMA_CYC, busy_dma) ----")
        `CEN("LAYER_CENSUS  op name     count       total_dma     mean")
        for (z = 0; z < 16; z++)
            if (op_n[z] != 0 && op_dma[z] != 0)
                `CEN($sformatf("LAYER_CENSUS %3d %-6s %8d %15d %8d",
                               z, opname[z], op_n[z], op_dma[z],
                               op_dma[z] / op_n[z]))
        `CEN($sformatf("LAYER_CENSUS TOTAL_SDMA_CYCLES %0d", sdma_tot))
        `CEN("LAYER_CENSUS ---- per forward step (step 0 = the preamble) ----")
        `CEN("LAYER_CENSUS step    commands       busy_cyc     DNST  SLD+SST       sdma_cyc")
        for (z = 0; z <= nstep; z++)
            `CEN($sformatf("LAYER_CENSUS %4d %11d %14d %8d %8d %14d",
                           z, step_n[z], step_cyc[z], step_dn[z],
                           step_sd[z], step_dma[z]))
        end
        // S4 fix round 1 (I4): the three FENCE totals, in BOTH modes and
        // APPENDED so nothing above them moves.  Printing them in the
        // draining mode is what gives the instrument its negative arm: the
        // drain makes an F1/F2 hold structurally impossible, so a draining
        // run at ANY latency must report 0 here, and a counter that is 0
        // when it must be and non-zero when it must be is a counter that has
        // been seen to work.  F1 and F2 raise busy_cmp and are therefore
        // INSIDE TOTAL_BUSY_CYCLES; F2_FENCE is on the DMA lane and is not.
        `CEN($sformatf("LAYER_CENSUS TOTAL_BUSY_ANY_CYCLES %0d  (either lane busy: STATUS bit 0)", bany_cyc))
        `CEN($sformatf("LAYER_CENSUS TOTAL_F1_HOLD_CYCLES %0d  (dispatch held by F1; inside LCYC)", f1_cyc))
        `CEN($sformatf("LAYER_CENSUS TOTAL_F2_HOLD_CYCLES %0d  (dispatch held by a full DMA queue; inside LCYC)", f2_cyc))
        `CEN($sformatf("LAYER_CENSUS TOTAL_F2_FENCE_CYCLES %0d  (DMA head held by a compute command; DMA lane, NOT in LCYC)", f2f_cyc))
        `undef CEN
        if (fd != 0) $fclose(fd);
    endtask

    initial begin
        int fd, r, n, addr, op, a0, a1, a2, val, val2, i, ncmd, nchk;
        int tokid, stopm, nm;
        longint embn;
        logic [31:0] d;
        /* verilator lint_off UNUSEDSIGNAL */
        logic [31:0] cnt0;
        /* verilator lint_on UNUSEDSIGNAL */
        string tok;

        if (!$value$plusargs("script=%s", script))
            $fatal(1, "need +script=");
        fd = $fopen(script, "r");
        if (fd == 0) $fatal(1, "cannot open %s", script);
        censusf = "";
        void'($value$plusargs("census=%s", censusf));
        stopm = 0;
        void'($value$plusargs("stopm=%d", stopm));
        nm = 0;
        // S4 fix round 1 (I4).  The poll BACKOFF is part of the mode: the
        // draining census keeps its 20 negedges exactly (its numbers are
        // committed), and +nodrain uses 2, which puts the STATUS poll's
        // period at about the AXI-Lite round trip rtl/seq_unit.sv's
        // I_CMDPOLL / I_CMDPOLLW pair takes, so the dispatch is as tight as
        // the sequencer's rather than tighter or looser.
        nodrain = 0;
        void'($value$plusargs("nodrain=%d", nodrain));
        pollbk = (nodrain != 0) ? 2 : 20;
        // The dispatch guard is a HANG detector, and a legitimate hold is
        // much longer under +nodrain than anything the draining mode can
        // produce: at a deliberately slow modelled window a compute command
        // can wait behind several whole transfers.  Measured at LAT 4000 on
        // the 1-layer smoke, one CONV waited past 200,000 poll iterations
        // (~1.4 M cycles) -- a real F1 hold, not a hang -- so the guard is
        // raised with the mode rather than the mode being tuned to the
        // guard.  The watchdog (+watchdog_ms) is still the outer limit.
        guard_max = (nodrain != 0) ? 4000000 : 200000;
        if (nodrain != 0)
            $display("LAYER_CENSUS mode: +nodrain=1 — back-to-back dispatch (the sequencer's rule); per-command cost attribution is SUPPRESSED");

        embfd = 0;
        embn = 0;
        if ($value$plusargs("embn=%d", emb_n)) begin
            if (emb_n <= 0 || emb_n > EMB_N_MAX)
                $fatal(1, "+embn=%0d outside [1,%0d]", emb_n, EMB_N_MAX);
        end
        emb_row_b = 2 * emb_n;
        if ($value$plusargs("emb=%s", embf)) begin
            embfd = $fopen(embf, "rb");
            if (embfd == 0) $fatal(1, "cannot open %s", embf);
            r = $fseek(embfd, 0, 2);
            embn = $ftell(embfd);
            $display("emb table: %0d bytes (%0d rows of %0d) from %s",
                     embn, embn / longint'(emb_row_b), emb_n, embf);
        end

        repeat (5) @(negedge aclk);
        aresetn = 1;
        repeat (4) @(negedge aclk);

        rd32(12'h24, d);
        if (d !== 32'hFAB1E5A0) begin
            errors++; $display("FAIL IDENT: %h", d);
        end
        // baseline the counter AFTER reset so cycle 0 of the census is the
        // engine's first busy cycle and nothing before it is attributed.
        rd32(A_LCYC, d);
        lcyc_prev = {32'b0, d};
        if (lcyc_prev != 0) $fatal(1, "LCYC not 0 out of reset: %0d", lcyc_prev);
        rd32(A_SDMACYC, d);
        sdma_prev = {32'b0, d};
        if (sdma_prev != 0)
            $fatal(1, "SDMA_CYC not 0 out of reset: %0d", sdma_prev);

        ncmd = 0; nchk = 0;
        forever begin
            r = $fscanf(fd, " %s", tok);
            if (r != 1) break;
            case (tok)
                "W": begin
                    r = $fscanf(fd, " %h %h", addr, n);
                    wr32(A_SPTR, 32'(addr));
                    for (i = 0; i < n; i++) begin
                        r = $fscanf(fd, " %h", val);
                        wr32(A_SWIN, 32'(val));
                    end
                end
                "C": begin
                    int guard;
                    r = $fscanf(fd, " %h %h %h %h", op, a0, a1, a2);
                    // the WALL clock of a step starts at its FIRST dispatch
                    if (step_n[nstep] == 0) step_t0[nstep] = cyc;
                    wr32(A_ARG0, 32'(a0));
                    wr32(A_ARG1, 32'(a1));
                    wr32(A_ARG2, 32'(a2));
                    rd32(A_STAT, cnt0);
                    wr32(A_CMD, 32'(op));
                    guard = 0;
                    forever begin
                        rd32(A_STAT, d);
                        // THE BACK-PRESSURE RULE, and it is the whole
                        // difference between the two modes.
                        //   draining  : the command counter has advanced AND
                        //               the engine is idle (busy_any low) --
                        //               which is what makes each LCYC
                        //               difference THAT command's cost, and
                        //               which also makes an F1/F2 hold
                        //               structurally impossible.
                        //   +nodrain  : the command counter has advanced,
                        //               full stop -- rtl/seq_unit.sv:1188's
                        //               I_CMDPOLLW tests exactly that and
                        //               never looks at STATUS bit 0, and
                        //               cmd_cnt advances for an SLD/SST at
                        //               ENQUEUE (rtl/layer_chan.sv:1464), so
                        //               the next record is dispatched while
                        //               the transfer is still moving.  A
                        //               fifth queued transfer is HELD at
                        //               dispatch and does NOT advance
                        //               cmd_cnt (rtl/layer_chan.sv:1448-1457),
                        //               so this poll IS the queue's
                        //               back-pressure and cannot overrun it.
                        if (d[31:16] == 16'(cnt0[31:16] + 16'd1)
                            && (nodrain != 0 || !d[0])) break;
                        repeat (pollbk) @(negedge aclk);
                        guard++;
                        if (guard > guard_max)
                            $fatal(1, "cmd %0d (op %0d) timeout after %0d polls",
                                   ncmd, op, guard);
                    end
                    if (d[1]) begin
                        errors++; $display("FAIL cmd %0d: err_op", ncmd);
                    end
                    census_take(op & 15);
                    ncmd++;
                end
                "R": begin
                    r = $fscanf(fd, " %h %h", addr, n);
                    wr32(A_SPTR, 32'(addr));
                    for (i = 0; i < n; i++) begin
                        r = $fscanf(fd, " %h", val);
                        rd32(A_SWIN, d);
                        if (d[15:0] !== 16'(val)) begin
                            errors++;
                            if (errors < 20)
                                $display("FAIL R[%0h+%0d] after cmd %0d: got %h want %h",
                                         addr, i, ncmd, d[15:0], 16'(val));
                        end
                        nchk++;
                    end
                end
                "E": begin
                    r = $fscanf(fd, " %h", val);
                    rd32(A_EOUT, d);
                    if (d[3:0] !== 4'(val)) begin
                        errors++;
                        $display("FAIL E after cmd %0d: got %0d want %0d",
                                 ncmd, d[3:0], val);
                    end
                    nchk++;
                end
                "T": begin
                    r = $fscanf(fd, " %h", val);
                    wr32(A_TCNT, 32'(val));
                    wr32(A_TCNT2, 32'(val));
                end
                "L": begin
                    r = $fscanf(fd, " %h", val);
                    wr32(A_LAYER, 32'(val));
                end
                "S": begin   // S3 (B15.3): the three state-region base CSRs
                             // and the region's size, all in 64 KiB units.
                             // The same record programs the TB's own DDR
                             // model, so the script and the model cannot
                             // name different addresses.
                    int sdn, skv, scv, sun;
                    r = $fscanf(fd, " %h %h %h %h", sdn, skv, scv, sun);
                    if (r != 4) $fatal(1, "bad S record");
                    wr32(A_SB_DN, 32'(sdn));
                    wr32(A_SB_KV, 32'(skv));
                    wr32(A_SB_CV, 32'(scv));
                    win_base = {2'd0, sdn} << 16;
                    win_len  = {2'd0, sun} << 16;
                    $display("  state region: SB_DN %05h SB_KV %05h SB_CV %05h, %0d MiB",
                             sdn, skv, scv, (sun * 64) / 1024);
                end
                "B": begin
                    r = $fscanf(fd, " %h", val);
                    wr32(A_DNSB, 32'(val));
                end
                "V": begin
                    int nrows;
                    r = $fscanf(fd, " %h %h %h %h", op, addr, n, nrows);
                    for (i = 0; i < nrows; i++) r = $fscanf(fd, " %h", val);
                end
                "M": begin
                    longint off;
                    nm++;
                    // S4 fix round 1 (I4): an M record ENDS the step that was
                    // running, so close it -- drain and stamp its wall time --
                    // before the next one starts.  In the draining mode the
                    // engine is already idle here and the drain is a single
                    // STATUS read.
                    step_close();
                    if (stopm != 0 && nm == stopm) begin
                        $display("LAYER_CENSUS stop: reached M record %0d (+stopm)",
                                 nm);
                        break;
                    end
                    // an M record STARTS a forward step
                    nstep++;
                    if (nstep > 7) $fatal(1, "more forward steps than the census array holds");
                    r = $fscanf(fd, " %h %h %h", tokid, addr, n);
                    if (embfd == 0) $fatal(1, "M record but no +emb= table");
                    if (n != emb_n)
                        $fatal(1, "M record n=%0d, TB row is %0d (+embn=)",
                               n, emb_n);
                    off = longint'(tokid) * longint'(emb_row_b);
                    if (off + longint'(emb_row_b) > embn)
                        $fatal(1, "M record tok %0d past the %0d-byte table",
                               tokid, embn);
                    if ($fseek(embfd, int'(off), 0) != 0)
                        $fatal(1, "emb $fseek(tok %0d) failed", tokid);
                    if ($fread(embrow, embfd) < emb_row_b)
                        $fatal(1, "emb $fread(tok %0d) short", tokid);
                    wr32(A_SPTR, 32'(addr));
                    for (i = 0; i < n; i++)
                        wr32(A_SWIN, {16'b0, embrow[2 * i + 1], embrow[2 * i]});
                end
                "A": begin
                    r = $fscanf(fd, " %h %h", val, val2);
                    rd32(12'h28, d);
                    if (d[17:0] !== 18'(val)) begin
                        errors++;
                        $display("FAIL A idx after cmd %0d: got %0d want %0d",
                                 ncmd, d[17:0], val);
                    end
                    rd32(12'h2C, d);
                    if (d !== 32'(val2)) begin
                        errors++;
                        $display("FAIL A val after cmd %0d: got %h want %h",
                                 ncmd, d, val2);
                    end
                    nchk += 2;
                end
                "Q": break;
                default: $fatal(1, "bad token '%s'", tok);
            endcase
            if (errors >= 20) $fatal(1, "TB_LAYER_CENSUS FAIL: too many errors");
        end
        $fclose(fd);
        if (embfd != 0) $fclose(embfd);
        // the LAST step ends here (Q, EOF or +stopm): close it too, so every
        // step's wall time is measured the same way.
        step_close();

        census_report(ncmd, nchk);
        if (errors == 0) begin
            $display("TB_LAYER_CENSUS PASS: %0d cmds, %0d checks bit-exact (%s)",
                     ncmd, nchk, script);
            $finish;
        end else $fatal(1, "TB_LAYER_CENSUS FAIL: %0d errors", errors);
    end

    initial begin
        int wd_ms;
        wd_ms = 400;
        void'($value$plusargs("watchdog_ms=%d", wd_ms));
        #(wd_ms * 1ms);
        $display("WATCHDOG (%0d ms): dut.st=%0d busy_cmp=%0d busy_dma=%0d",
                 wd_ms, dut.st, dut.busy_cmp, dut.busy_dma);
        $fatal(1, "watchdog");
    end
endmodule
