// tb_layer_sdma: the DIRECTED gate on layer_chan's state DMA — the two-slot
// DN/KV/CV caches, `state_dma`, the DMA lane, the F1/F2 fences, the slot
// tags and every E_* code (spec 2026-09-04 state-spill §3-§5, A1.1-A1.5;
// SEQ_ISA v2.1 B15).
//
// It drives the layer DIRECTLY over AXI-Lite — there is no generated
// command stream and no reference model here.  The emitter learns the
// SLD/SST schedule at Task S3, and `tb_layer_chan` / `tb_layer_env` are
// re-run there; S2's gate has to stand on its own, so every check below is
// either a ROUND TRIP (a block written to the DDR model, pulled into a
// slot, pushed back and compared byte for byte) or a COMMITTED GOLDEN (the
// dn_step vector set under tb/vectors/, replayed through the whole
// DDR -> slot -> dn_step -> slot -> DDR path).
//
// The two fences get real controls:
//   * F1  the `-G SDMA_NOFENCE=1` build (tb_layer_sdma_nofence) bypasses
//         the load-before-use stall.  Case 4 must then read the PRE-load
//         slot and FAIL the golden compare — that failure IS the proof
//         that the fence is what makes case 4 pass in the shipped build.
//   * F2  case 6 queues an SST behind a long SLD and starts a DNST on the
//         SST's slot; `u_dma.xfer_go` for the SST must not fire while a
//         compute command holds that slot.
//
// TB DISCIPLINE (repo CLAUDE.md): every DUT input is driven and every DUT
// output sampled at NEGEDGE; failures are `$fatal(1, ...)` because
// `$finish(n)` does not set the exit code; four seeds per run.
//
// +vecdir=<dir>   the dn_step golden set (default vectors/s1)
// +seed=<n>       the BFM's handshake-gap seed and the DDR fill pattern
// +watchdog_ms=<n>

`timescale 1ns/1ps

module tb_layer_sdma #(
    // forwarded to the DUT: `make tb_layer_sdma_nofence` builds this TB with
    // -GSDMA_NOFENCE=1, which removes F1 inside layer_chan.  Case 4 must
    // then FAIL — that failure is the fence's negative control.
    parameter int SDMA_NOFENCE = 0
);

    // ==================================================================
    // 0. the state region, exactly as sw/hwmap.plan_state() lays it out
    //    (STATE_BASE_UNIT = 64 KiB; DN 24 MiB, KV 128 MiB, conv 3 MiB).
    //    The base is 64 KiB rather than 0 because SB_<kind> == 0 IS the
    //    E_DMA_BASE condition, so a region at 0 is unaddressable by
    //    construction.
    // ==================================================================
    localparam longint STATE_BASE = 64 * 1024;
    localparam longint DN_BASE    = STATE_BASE;
    localparam longint KV_BASE    = DN_BASE + 24 * 1024 * 1024;
    localparam longint CV_BASE    = KV_BASE + 128 * 1024 * 1024;
    localparam longint STATE_END  = CV_BASE + 3 * 1024 * 1024;

    localparam int SB_DN_V = int'(DN_BASE >> 16);      // 1
    localparam int SB_KV_V = int'(KV_BASE >> 16);      // 385
    localparam int SB_CV_V = int'(CV_BASE >> 16);      // 2433

    localparam longint DN_STRIDE  = 1 << 20;           // SDMA_SHIFT_DN
    localparam longint KV_STRIDE  = 1 << 21;           // SDMA_SHIFT_KV
    localparam longint CV_STRIDE  = 1 << 17;           // SDMA_SHIFT_CV
    localparam longint KV_EXP_OFF = 1 << 20;

    localparam int BFM_DEPTH = int'(STATE_END / 64);   // 512-bit words

    // ==================================================================
    // 1. clock, reset, the DUT and the DDR model
    // ==================================================================
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

    // burst-window slave: tied idle (this TB drives AXI-Lite only)
    /* verilator lint_off UNUSEDSIGNAL */
    wire        nc_awready, nc_wready, nc_bvalid, nc_arready, nc_rvalid,
                nc_rlast;
    wire [0:0]  nc_bid, nc_rid;
    wire [1:0]  nc_bresp, nc_rresp;
    wire [31:0] nc_rdata;
    /* verilator lint_on UNUSEDSIGNAL */

    // ---- the state-DMA master, layer_chan -> axi_ram_bfm ----
    wire [33:0]  m_awaddr;  wire [7:0] m_awlen;  wire m_awvalid; wire m_awready;
    wire [511:0] m_wdata;   wire [63:0] m_wstrb; wire m_wlast;
    wire         m_wvalid;  wire m_wready;
    wire [1:0]   m_bresp;   wire m_bvalid;  wire m_bready;
    wire [33:0]  m_araddr;  wire [7:0] m_arlen;  wire m_arvalid; wire m_arready;
    wire [511:0] m_rdata;   wire [1:0] m_rresp;  wire m_rlast;
    wire         m_rvalid;  wire m_rready;

    logic        bfm_err_en = 0;
    logic [33:0] bfm_err_addr = 0;
    int unsigned seed_i = 1;

    layer_chan #(
        .RSQRT_ROM("../rtl/roms/rsqrt_rom.hex"),
        .SIGMOID_ROM("../rtl/roms/sigmoid_pair_rom.hex"),
        .SOFTPLUS_ROM("../rtl/roms/softplus_pair_rom.hex"),
        .EXP2_ROM("../rtl/roms/exp2_pair_rom.hex"),
        .RECIP_ROM("../rtl/roms/recip_rom.hex"),
        .SDMA_NOFENCE(SDMA_NOFENCE)
    ) dut (
        .aclk, .aresetn,
        .s_axil_awaddr(awaddr), .s_axil_awvalid(awvalid),
        .s_axil_awready(awready),
        .s_axil_wdata(wdata), .s_axil_wstrb(wstrb), .s_axil_wvalid(wvalid),
        .s_axil_wready(wready),
        .s_axil_bresp(bresp), .s_axil_bvalid(bvalid), .s_axil_bready(bready),
        .s_axil_araddr(araddr), .s_axil_arvalid(arvalid),
        .s_axil_arready(arready),
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
        // ---- S2: the 512-bit state-DMA master ----
        .m_axis_awaddr(m_awaddr), .m_axis_awlen(m_awlen),
        .m_axis_awvalid(m_awvalid), .m_axis_awready(m_awready),
        .m_axis_wdata(m_wdata), .m_axis_wstrb(m_wstrb),
        .m_axis_wlast(m_wlast), .m_axis_wvalid(m_wvalid),
        .m_axis_wready(m_wready),
        .m_axis_bresp(m_bresp), .m_axis_bvalid(m_bvalid),
        .m_axis_bready(m_bready),
        .m_axis_araddr(m_araddr), .m_axis_arlen(m_arlen),
        .m_axis_arvalid(m_arvalid), .m_axis_arready(m_arready),
        .m_axis_rdata(m_rdata), .m_axis_rresp(m_rresp),
        .m_axis_rlast(m_rlast), .m_axis_rvalid(m_rvalid),
        .m_axis_rready(m_rready)
    );

    axi_ram_bfm #(.DEPTH(BFM_DEPTH)) bfm (
        .aclk, .aresetn,
        .err_en(bfm_err_en), .err_addr(bfm_err_addr),
        .awaddr(m_awaddr), .awlen(m_awlen), .awvalid(m_awvalid),
        .awready(m_awready),
        .wdata(m_wdata), .wstrb(m_wstrb), .wlast(m_wlast),
        .wvalid(m_wvalid), .wready(m_wready),
        .bresp(m_bresp), .bvalid(m_bvalid), .bready(m_bready),
        .araddr(m_araddr), .arlen(m_arlen), .arvalid(m_arvalid),
        .arready(m_arready),
        .rdata(m_rdata), .rresp(m_rresp), .rlast(m_rlast),
        .rvalid(m_rvalid), .rready(m_rready)
    );

    // ==================================================================
    // 2. bus monitors.  Everything the tests need to know about the AXI
    //    side is observed HERE, on the wires this file declares, so
    //    axi_ram_bfm stays a pure protocol model.
    // ==================================================================
    int unsigned n_aw = 0, n_ar = 0, n_b = 0, n_w = 0, n_r = 0;
    longint      ad_lo = 0, ad_hi = 0;         // address span since the clear
    int unsigned ord_bad = 0;                  // AR while writes outstanding
    bit          mon_ord = 0;                  // arm the ordering monitor
    // THE OWNERSHIP INVARIANT (fix round 1, C1).  Armed for the WHOLE run,
    // all three kinds: while a compute command is EXECUTING (st != IDLE) the
    // DMA must never own the slot that command holds.  Case 4 armed only the
    // DN half and only inside itself, which is why the F1-stall-release hole
    // went unseen.
    int unsigned own_bad = 0;
    bit          mon_f2 = 0;
    int unsigned f2_bad = 0;                   // xfer_go while compute holds
    int unsigned f2_wait_n = 0;                // cycles F2 actually HELD one
    int unsigned qhold_n = 0;                  // cycles a full DMA queue HELD
                                               // an SLD/SST at dispatch
    int unsigned xgo_n = 0;                    // xfer_go pulses seen
    int unsigned ovl_n = 0;                    // cycles with both lanes busy

    /* verilator lint_off BLKSEQ */   // TB counters, not DUT logic
    always @(posedge aclk) if (aresetn) begin
        if (m_awvalid && m_awready) begin
            n_aw++;
            if (ad_lo == 0 || longint'(m_awaddr) < ad_lo) ad_lo = longint'(m_awaddr);
            if (longint'(m_awaddr) + 64 * (longint'(m_awlen) + 1) > ad_hi)
                ad_hi = longint'(m_awaddr) + 64 * (longint'(m_awlen) + 1);
        end
        if (m_arvalid && m_arready) begin
            n_ar++;
            if (ad_lo == 0 || longint'(m_araddr) < ad_lo) ad_lo = longint'(m_araddr);
            if (longint'(m_araddr) + 64 * (longint'(m_arlen) + 1) > ad_hi)
                ad_hi = longint'(m_araddr) + 64 * (longint'(m_arlen) + 1);
            // F2/order: a read address must never be issued while a write
            // burst of an EARLIER queue entry is still un-responded.
            if (mon_ord && n_aw != n_b) ord_bad++;
        end
        if (m_bvalid && m_bready) n_b++;
        if (m_wvalid && m_wready) n_w++;
        if (m_rvalid && m_rready) n_r++;
        // F1/F2 (spec §5.4): the compute lane must never be EXECUTING while
        // the DMA owns the slot it holds.  Note the fence stalls a command
        // with busy_cmp already HIGH — that is what closes the CMD accept
        // gate and makes LCYC count the stall — so the observable is `st`
        // leaving IDLE, not busy_cmp rising.
        if (dut.st != 0 && dut.dma_act) begin
            if ((dut.dma_kind == 2'd0) && dut.cmd_uses_dn
                && (dut.dma_slot == dut.dn_slot_r)) own_bad++;
            if ((dut.dma_kind == 2'd1) && dut.cmd_uses_kv
                && (dut.dma_slot == dut.kv_slot_r)) own_bad++;
            if ((dut.dma_kind == 2'd2) && dut.cmd_uses_cv
                && (dut.dma_slot == dut.cv_slot_r)) own_bad++;
        end
        // F2: no transfer may START while a compute command holds its slot.
        if (dut.u_dma.xfer_go) begin
            xgo_n++;
            if (mon_f2 && dut.busy_cmp && dut.st != 0) f2_bad++;
        end
        if (dut.busy_cmp && dut.busy_dma) ovl_n++;
        // F2 must be OBSERVED holding a transfer, or case 6 is vacuous
        if (mon_f2 && dut.hd_f2 && !dut.dma_act && !dut.dq_empty) f2_wait_n++;
        // and the queue-full hold must be OBSERVED too
        if (dut.cmd_pend && dut.cmd_is_dma) qhold_n++;
    end
    /* verilator lint_on BLKSEQ */

    task automatic mon_clear();
        n_aw = 0; n_ar = 0; n_b = 0; n_w = 0; n_r = 0;
        ad_lo = 0; ad_hi = 0; ord_bad = 0; xgo_n = 0; ovl_n = 0;
        f2_bad = 0; f2_wait_n = 0;   // own_bad is NEVER cleared: it is the
                                     // whole run's ownership invariant
    endtask

    // ==================================================================
    // 3. AXI-Lite master tasks — copied from tb/tb_layer_chan.sv:118
    //    (`wr32`) and tb/tb_layer_chan.sv:130 (`rd32`).  Written as two
    //    FULL tokens: the slash-joined form the first cut used
    //    (`…:120/:79`) is the one evidence/qwen9b/o3/o3_cite_drift.py's own
    //    header warns about — it renumbers the first element and leaves the
    //    rest, which is how `:79` ended up naming a comment header rather
    //    than `rd32` (S3 fix round 1, I3).
    //    (the TB families never share a file; see tb/Makefile's note on
    //    the frozen back-compat set).
    // ==================================================================
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

    // CSR byte addresses (SEQ_ISA B15.3 for the five new ones)
    localparam logic [11:0] A_CMD   = 12'h000, A_STAT  = 12'h004,
                            A_ARG0  = 12'h008, A_ARG1  = 12'h00C,
                            A_ARG2  = 12'h010, A_SPTR  = 12'h014,
                            A_SWIN  = 12'h018, A_TCNT  = 12'h020,
                            A_LAYER = 12'h030, A_LCYC  = 12'h034,
                            A_DNSB  = 12'h05C, A_TCNT2 = 12'h060,
                            A_SB_DN = 12'h064, A_SB_KV = 12'h068,
                            A_SB_CV = 12'h06C, A_SDMA  = 12'h070,
                            A_SDMACY = 12'h074;

    localparam int OP_CONVW = 5, OP_CONV = 6, OP_DNST = 8, OP_KVAP = 9,
                   OP_ATTN = 10, OP_DNZ = 12, OP_SLD = 13, OP_SST = 14;
    localparam int K_DN = 0, K_KV = 1, K_CV = 2;

    localparam logic [7:0] E_ENV = 8'h01, E_LAYER = 8'h02,
                           E_DMA_BASE = 8'h10, E_DMA_RANGE = 8'h11,
                           E_DMA_AXI = 8'h12, E_DMA_COLD = 8'h13;

    // scratch map
    localparam int SC_DEC = 'h100, SC_BET = 'h140,
                   SC_K   = 'h200, SC_Q   = 'h400,
                   SC_V   = 'h600, SC_DST = 'h800,
                   SC_KVK = 'h1000, SC_KVV = 'h1200,
                   SC_CVS = 'h4000, SC_CVD = 'h6000;   // 8192 words each

    int unsigned checks = 0;

    task automatic chk(input bit ok, input string what);
        checks++;
        if (!ok) $fatal(1, "TB_LAYER_SDMA FAIL: %s", what);
    endtask

    // ---- B15.1's ARG0 and B15.2's LAYER word, packed by the TB ----
    function automatic logic [31:0] sdma_arg0(input int kind, slot, layer, head);
        return 32'((kind << 11) | (slot << 10) | (layer << 5) | head);
    endfunction
    function automatic logic [31:0] layer_word(input int dn, kv, cv, kvl);
        return 32'((cv << 12) | (kvl << 8) | (kv << 3) | dn);
    endfunction

    // ---- dispatch one command; check err_op and SDMA.err ----
    task automatic dcmd(input int op, input logic [31:0] a0, a1, a2,
                        input logic [7:0] want_code, input string what);
        /* verilator lint_off UNUSEDSIGNAL */
        logic [31:0] c0, d, sd;
        /* verilator lint_on UNUSEDSIGNAL */
        int guard;
        wr32(A_ARG0, a0); wr32(A_ARG1, a1); wr32(A_ARG2, a2);
        rd32(A_STAT, c0);
        wr32(A_CMD, 32'(op));
        guard = 0;
        d = '0;
        forever begin
            rd32(A_STAT, d);
            if (d[31:16] == 16'(c0[31:16] + 16'd1)) break;
            repeat (20) @(negedge aclk);
            guard++;
            if (guard > 400000) $fatal(1, "TB_LAYER_SDMA: %s timeout", what);
        end
        rd32(A_SDMA, sd);
        checks++;
        if (d[1] !== (want_code != 8'h00))
            $fatal(1, "TB_LAYER_SDMA FAIL %s: err_op=%0b, wanted code %02h",
                   what, d[1], want_code);
        checks++;
        if (sd[7:0] !== want_code)
            $fatal(1, "TB_LAYER_SDMA FAIL %s: SDMA.err=%02h, wanted %02h",
                   what, sd[7:0], want_code);
    endtask

    // ---- wait for the DMA lane to drain ----
    task automatic dma_wait(input string what);
        /* verilator lint_off UNUSEDSIGNAL */
        logic [31:0] d;
        /* verilator lint_on UNUSEDSIGNAL */
        int guard;
        guard = 0;
        forever begin
            rd32(A_SDMA, d);
            if (!d[31] && d[30:28] == 3'd0) break;
            repeat (50) @(negedge aclk);
            guard++;
            if (guard > 400000) $fatal(1, "TB_LAYER_SDMA: %s DMA timeout", what);
        end
    endtask

    // ---- scratch helpers ----
    task automatic swr1(input int addr, input logic [15:0] v);
        wr32(A_SPTR, 32'(addr));
        wr32(A_SWIN, {16'b0, v});
    endtask
    task automatic swr128(input int addr, ref logic [15:0] src [128]);
        wr32(A_SPTR, 32'(addr));
        for (int i = 0; i < 128; i++) wr32(A_SWIN, {16'b0, src[i]});
    endtask
    task automatic srd(input int addr, input int n, ref logic [15:0] dst[]);
        /* verilator lint_off UNUSEDSIGNAL */
        logic [31:0] d;
        /* verilator lint_on UNUSEDSIGNAL */
        wr32(A_SPTR, 32'(addr));
        for (int i = 0; i < n; i++) begin
            rd32(A_SWIN, d);
            dst[i] = d[15:0];
        end
    endtask

    // ==================================================================
    // 4. the DDR model's contents, addressed in bytes
    // ==================================================================
    function automatic int unsigned widx(input longint ba);
        return int'(ba >> 6);
    endfunction

    task automatic ddr_wrow(input longint ba, input logic [2047:0] row);
        for (int k = 0; k < 4; k++) bfm.mem[widx(ba) + k] = row[512*k +: 512];
    endtask
    function automatic logic [2047:0] ddr_rrow(input longint ba);
        logic [2047:0] r;
        for (int k = 0; k < 4; k++) r[512*k +: 512] = bfm.mem[widx(ba) + k];
        return r;
    endfunction
    task automatic ddr_wword(input longint ba, input logic [511:0] w);
        bfm.mem[widx(ba)] = w;
    endtask
    function automatic logic [511:0] ddr_rword(input longint ba);
        return bfm.mem[widx(ba)];
    endfunction

    function automatic logic [15:0] pat16(input int unsigned s, r, v);
        logic [31:0] h;
        h = 32'(s) * 32'h9E3779B1 + 32'(r) * 32'h85EBCA6B
            + 32'(v) * 32'hC2B2AE35;
        h = h ^ (h >> 15);
        return h[15:0];
    endfunction

    // ==================================================================
    // 5. the dn_step golden set (tb/vectors/s<n>), replayed end to end
    // ==================================================================
    localparam int GOLD_HEAD = 17;             // the head case 1 computes on
    /* verilator lint_off UNUSEDSIGNAL */   // read through `ref` task args
    logic [15:0] sin_v [16384];
    logic [15:0] sout_v [16384];
    logic [15:0] gq [128], gk [128], gv [128];
    logic [31:0] go_ [128];
    // the two DNST results case 1 establishes and case 4's fence RED needs
    logic [31:0] o_loaded [128], o_zero [128], o_dnz [128], o_tmp [128];
    /* verilator lint_on UNUSEDSIGNAL */
    /* verilator lint_off UNUSEDSIGNAL */
    int unsigned g_dec, g_bet;
    /* verilator lint_on UNUSEDSIGNAL */
    string vecdir;

    // one DN layer block: `sin` at GOLD_HEAD, a seeded pattern elsewhere
    task automatic dn_fill(input longint base, input int unsigned s,
                           input bit with_sin);
        logic [2047:0] row;
        for (int r = 0; r < 4096; r++) begin
            if (with_sin && r >= GOLD_HEAD*128 && r < (GOLD_HEAD+1)*128)
                for (int v = 0; v < 128; v++)
                    row[v*16 +: 16] = sin_v[(r - GOLD_HEAD*128)*128 + v];
            else
                for (int v = 0; v < 128; v++) row[v*16 +: 16] = pat16(s, r, v);
            ddr_wrow(base + longint'(r) * 256, row);
        end
    endtask

    task automatic dn_zero(input longint base);
        for (int r = 0; r < 4096; r++) ddr_wrow(base + longint'(r) * 256, '0);
    endtask

    // ==================================================================
    // 6. the cases
    // ==================================================================
    // -- case 1: a DN block round trip, and the DNST on the loaded slot --
    //
    // WHY THIS IS NOT A dn_o.hex COMPARE.  tb/vectors/*/dn_v.hex is in
    // Q.S_F (ref/gen_layer_vectors.py:133 scales by 1 << LF.S_F), while the
    // DNST COMMAND transports v as Q.QKV_F and shifts it left by 5 on the
    // way into dn_step (rtl/layer_chan.sv, LT_DV).  Feeding the dn_step
    // golden through the layer command therefore cannot reproduce
    // dn_o.hex — the two live in different fixed-point domains, and
    // dn_step's own arithmetic is gated bit-exactly by tb_dn_step anyway.
    //
    // What S2 has to prove is that dn_step reads EXACTLY the rows the DMA
    // wrote, and that is proved here without a reference model, the way
    // tb_layer_chan's directed modes do it — two paths that MUST be
    // independent producing identical results from identical inputs:
    //   * a block round trip, byte for byte through the DDR model;
    //   * the same DNST on a slot whose head is zeroed BY THE DMA and on a
    //     slot whose head is zeroed BY DNZ (the compute write path,
    //     untouched since G3.4): identical outputs AND identical stored
    //     state, over the whole 4096-row block;
    //   * and, so "it always reads zeros" cannot pass, the same DNST on the
    //     LOADED state must differ from both.
    // `o_loaded` and `o_zero` are kept for case 4, whose fence RED is
    // exactly "the DNST read o_zero when it should have read o_loaded".
    task automatic dn_stim();
        wr32(A_DNSB, 32'((SC_DEC << 16) | SC_BET));
        swr1(SC_DEC + GOLD_HEAD, 16'(g_dec));
        swr1(SC_BET + GOLD_HEAD, 16'(g_bet));
        swr128(SC_K, gk); swr128(SC_Q, gq); swr128(SC_V, gv);
    endtask

    task automatic dn_run(input int slot, ref logic [31:0] o [128]);
        logic [15:0] obuf [];
        wr32(A_LAYER, layer_word(slot, 0, 0, 0));
        dcmd(OP_DNST, 32'(GOLD_HEAD), 32'((SC_K << 16) | SC_Q),
             32'((SC_DST << 16) | SC_V), 8'h00,
             $sformatf("DNST head %0d on DN slot %0d", GOLD_HEAD, slot));
        obuf = new[256];
        srd(SC_DST, 256, obuf);
        for (int i = 0; i < 128; i++) o[i] = {obuf[2*i+1], obuf[2*i]};
    endtask

    function automatic int dn_blk_cmp(input longint a, input longint b,
                                      input bit head_only, input bit skip_head);
        int bad;
        bad = 0;
        for (int r = 0; r < 4096; r++) begin
            bit inh;
            inh = (r >= GOLD_HEAD*128) && (r < (GOLD_HEAD+1)*128);
            if ((head_only && !inh) || (skip_head && inh)) continue;
            if (ddr_rrow(a + longint'(r)*256) !== ddr_rrow(b + longint'(r)*256))
                bad++;
        end
        return bad;
    endfunction

    task automatic tc_dn_roundtrip();
        int bad, same;
        $display("-- case 1: dn_roundtrip (DDR -> slot -> DDR byte for byte, then the DMA and DNZ write paths compared through dn_step)");
        dn_fill(DN_BASE + 3 * DN_STRIDE, seed_i, 1);   // head 17 = dn_sin
        dn_fill(DN_BASE + 7 * DN_STRIDE, seed_i, 0);   // head 17 = zero
        for (int r = GOLD_HEAD*128; r < (GOLD_HEAD+1)*128; r++)
            ddr_wrow(DN_BASE + 7*DN_STRIDE + longint'(r)*256, '0);
        dn_zero(DN_BASE + 4 * DN_STRIDE);
        dn_zero(DN_BASE + 5 * DN_STRIDE);
        dn_zero(DN_BASE + 8 * DN_STRIDE);
        dn_zero(DN_BASE + 9 * DN_STRIDE);
        wr32(A_SB_DN, 32'(SB_DN_V));
        mon_clear();
        dcmd(OP_SLD, sdma_arg0(K_DN, 0, 3, 0), 0, 0, 8'h00, "SLD DN s0 L3");
        dma_wait("SLD DN s0 L3");
        chk(n_ar == 1024, $sformatf("DN SLD issued %0d AR bursts (want 1024)",
                                    n_ar));
        chk(n_r == 16384, $sformatf("DN SLD took %0d R beats (want 16384)", n_r));
        // store the slot into a DIFFERENT block and compare byte for byte
        dcmd(OP_SST, sdma_arg0(K_DN, 0, 4, 0), 0, 0, 8'h00, "SST DN s0 L4");
        dma_wait("SST DN s0 L4");
        chk(n_aw == 1024, $sformatf("DN SST issued %0d AW bursts (want 1024)",
                                    n_aw));
        chk(n_b == n_aw, "the SST completed with write responses outstanding");
        bad = dn_blk_cmp(DN_BASE + 4*DN_STRIDE, DN_BASE + 3*DN_STRIDE, 0, 0);
        chk(bad == 0, $sformatf("DN round trip: %0d of 4096 rows differ", bad));

        // the SST cleared `warm` (the lost-update guard), so reload
        dcmd(OP_SLD, sdma_arg0(K_DN, 0, 3, 0), 0, 0, 8'h00, "SLD DN s0 L3 (2)");
        dma_wait("SLD DN s0 L3 (2)");
        dn_stim();
        dn_run(0, o_loaded);
        dcmd(OP_SST, sdma_arg0(K_DN, 0, 5, 0), 0, 0, 8'h00, "SST DN s0 L5");
        dma_wait("SST DN s0 L5");
        bad = dn_blk_cmp(DN_BASE + 5*DN_STRIDE, DN_BASE + 3*DN_STRIDE, 0, 1);
        chk(bad == 0, $sformatf("the DNST disturbed %0d rows outside head %0d",
                                bad, GOLD_HEAD));
        bad = dn_blk_cmp(DN_BASE + 5*DN_STRIDE, DN_BASE + 3*DN_STRIDE, 1, 0);
        chk(bad > 0, "the DNST left head 17's state unchanged (it did not read or write the slot at all)");

        // ---- path A: head 17 zeroed BY THE DMA (block L7) ----
        dcmd(OP_SLD, sdma_arg0(K_DN, 1, 7, 0), 0, 0, 8'h00, "SLD DN s1 L7");
        dma_wait("SLD DN s1 L7");
        dn_run(1, o_zero);
        dcmd(OP_SST, sdma_arg0(K_DN, 1, 8, 0), 0, 0, 8'h00, "SST DN s1 L8");
        dma_wait("SST DN s1 L8");

        // ---- path B: the SAME head zeroed BY DNZ, over a loaded L3 ----
        dcmd(OP_SLD, sdma_arg0(K_DN, 1, 3, 0), 0, 0, 8'h00, "SLD DN s1 L3");
        dma_wait("SLD DN s1 L3");
        wr32(A_LAYER, layer_word(1, 0, 0, 0));
        dcmd(OP_DNZ, 32'(GOLD_HEAD), 0, 0, 8'h00, "DNZ head 17 on DN slot 1");
        dn_run(1, o_dnz);
        dcmd(OP_SST, sdma_arg0(K_DN, 1, 9, 0), 0, 0, 8'h00, "SST DN s1 L9");
        dma_wait("SST DN s1 L9");

        same = 0;
        for (int i = 0; i < 128; i++) if (o_zero[i] === o_dnz[i]) same++;
        chk(same == 128, $sformatf("the DMA-zeroed and DNZ-zeroed heads gave %0d of 128 equal DNST outputs", same));
        bad = dn_blk_cmp(DN_BASE + 8*DN_STRIDE, DN_BASE + 9*DN_STRIDE, 0, 0);
        chk(bad == 0, $sformatf("the DMA-zeroed and DNZ-zeroed slots stored back %0d differing rows of 4096", bad));
        same = 0;
        for (int i = 0; i < 128; i++) if (o_loaded[i] === o_zero[i]) same++;
        chk(same < 128, "the DNST gave the SAME result on the LOADED state and on a ZEROED head — it is not reading the slot");
    endtask

    // -- case 2: KV round trips at T = 0, 1, 1023, 4096 ----------------
    task automatic kv_fill(input longint base, input int t,
                           input int unsigned s);
        logic [2047:0] row;
        logic [511:0]  eword;
        /* verilator lint_off UNUSEDSIGNAL */
        logic [15:0]   ev;
        /* verilator lint_on UNUSEDSIGNAL */
        for (int r = 0; r < t; r++) begin
            for (int v = 0; v < 128; v++) row[v*16 +: 16] = pat16(s, r, v);
            ddr_wrow(base + longint'(r) * 256, row);
        end
        for (int w = 0; w < (t + 63) / 64; w++) begin
            eword = '0;
            for (int b = 0; b < 64; b++)
                if (w*64 + b < t) begin
                    ev = pat16(s + 7, w*64 + b, 0);
                    eword[8*b +: 8] = ev[7:0];
                end
            ddr_wword(base + KV_EXP_OFF + longint'(w) * 64, eword);
        end
    endtask

    task automatic tc_kv_roundtrip();
        int tvals [4];
        int t, blk_a, blk_b;
        longint ba, bb;
        int bad;
        /* verilator lint_off UNUSEDSIGNAL */
        logic [31:0] d;
        /* verilator lint_on UNUSEDSIGNAL */
        tvals[0] = 0; tvals[1] = 1; tvals[2] = 1023; tvals[3] = 4096;
        $display("-- case 2: kv_roundtrip at T = 0, 1, 1023, 4096 (rows AND the exponent side array)");
        wr32(A_SB_KV, 32'(SB_KV_V));
        for (int i = 0; i < 4; i++) begin
            t = tvals[i];
            for (int kv = 0; kv < 2; kv++) begin
                // source block (layer 5, kvhead 2), destination (layer 1, kvhead 0)
                blk_a = (5*4 + 2)*2 + kv;
                blk_b = (1*4 + 0)*2 + kv;
                ba = KV_BASE + longint'(blk_a) * KV_STRIDE;
                bb = KV_BASE + longint'(blk_b) * KV_STRIDE;
                kv_fill(ba, t, seed_i + 32'(i) + 32'(kv) * 32'd101);
                for (int r = 0; r < t; r++)
                    ddr_wrow(bb + longint'(r) * 256, '0);
                for (int w = 0; w < (t + 63) / 64; w++)
                    ddr_wword(bb + KV_EXP_OFF + longint'(w) * 64, '0);
                // TCNT for BOTH (layer, kvhead) pairs the transfers name
                wr32(A_LAYER, layer_word(0, 1, 0, 5));
                wr32(A_TCNT2, {3'b0, 13'd0, 3'b0, 13'(t)});   // kvheads 2/3
                wr32(A_LAYER, layer_word(0, 1, 0, 1));
                wr32(A_TCNT, {3'b0, 13'd0, 3'b0, 13'(t)});    // kvheads 0/1
                mon_clear();
                wr32(A_SDMACY, 32'd0);     // measure THIS transfer only
                dcmd(OP_SLD, sdma_arg0(K_KV, 1, 5, 2*2 + kv), 0, 0, 8'h00,
                     $sformatf("SLD KV s1 L5 h2 kv%0d T=%0d", kv, t));
                dma_wait("SLD KV");
                if (t == 0) begin
                    chk(n_ar == 0 && n_aw == 0,
                        $sformatf("T=0 KV SLD moved nothing: %0d AR, %0d AW",
                                  n_ar, n_aw));
                    rd32(A_SDMACY, d);
                    chk(d < 32'd200, $sformatf("T=0 KV SLD SDMA_CYC=%0d (want a handful)", d));
                end else begin
                    chk(n_r == 4*t + (t + 63) / 64,
                        $sformatf("KV SLD T=%0d took %0d R beats (want %0d)",
                                  t, n_r, 4*t + (t + 63)/64));
                end
                // A zero-length SLD moves nothing but must still WARM the
                // slot and set its tag (B15.1).  Prove `warm` by ACCEPTANCE
                // first — a KVAP naming the tag's own kvhead must RUN — and
                // only then the tag refusal, so the tag check cannot mask a
                // cold slot (fix round 1, M8).  It has to happen HERE, before
                // the SST below makes the slot cold again.  KVAP first, then
                // ATTN: ATTN at T = 0 has nothing to iterate over, and the
                // KVAP's append is what takes TCNT to 1.
                if (t == 0 && kv == 1) begin
                    wr32(A_LAYER, layer_word(0, 1, 0, 5));
                    dcmd(OP_KVAP, 32'(2), 32'((SC_KVV << 16) | SC_KVK), 0,
                         8'h00,
                         "KVAP kvhead 2 on the slot a T=0 SLD warmed+tagged");
                    dcmd(OP_ATTN, 32'(2), 32'((SC_DST << 16) | SC_KVK), 0,
                         8'h00, "ATTN kvhead 2 on the same warm slot");
                    dcmd(OP_KVAP, 32'(3), 32'((SC_KVV << 16) | SC_KVK), 0,
                         E_DMA_RANGE,
                         "KVAP kvhead 3 against a slot tagged 2");
                    wr32(A_SDMA, 32'd0);
                    // the KVAP appended one row; put TCNT back for the SST
                    wr32(A_LAYER, layer_word(0, 1, 0, 5));
                    wr32(A_TCNT2, {3'b0, 13'd0, 3'b0, 13'(t)});
                end
                dcmd(OP_SST, sdma_arg0(K_KV, 1, 1, 0*2 + kv), 0, 0, 8'h00,
                     $sformatf("SST KV s1 L1 h0 kv%0d T=%0d", kv, t));
                dma_wait("SST KV");
                bad = 0;
                for (int r = 0; r < t; r++)
                    if (ddr_rrow(bb + longint'(r)*256)
                        !== ddr_rrow(ba + longint'(r)*256)) bad++;
                chk(bad == 0, $sformatf("KV T=%0d kv=%0d: %0d of %0d rows differ", t, kv, bad, t));
                bad = 0;
                for (int w = 0; w < (t + 63) / 64; w++)
                    if (ddr_rword(bb + KV_EXP_OFF + longint'(w)*64)
                        !== ddr_rword(ba + KV_EXP_OFF + longint'(w)*64)) bad++;
                chk(bad == 0, $sformatf("KV T=%0d kv=%0d: %0d exponent words differ", t, kv, bad));
            end
        end
    endtask

    // -- case 3: a conv block round trip through the two memories -------
    task automatic tc_cv_roundtrip();
        logic [511:0] w4;
        int bad;
        $display("-- case 3: cv_roundtrip (16 B rows split across the weight and state memories, spec A1.2)");
        wr32(A_SB_CV, 32'(SB_CV_V));
        for (int b = 0; b < 2048; b++) begin
            for (int k = 0; k < 4; k++) begin
                for (int j = 0; j < 4; j++)
                    w4[128*k + 16*j +: 16] = pat16(seed_i + 3, 4*b + k, j);
                for (int j = 0; j < 3; j++)
                    w4[128*k + 64 + 16*j +: 16] = pat16(seed_i + 9, 4*b + k, j);
                w4[128*k + 112 +: 16] = 16'h0000;    // B15.1: [127:112] = 0
            end
            ddr_wword(CV_BASE + 7 * CV_STRIDE + longint'(b) * 64, w4);
            ddr_wword(CV_BASE + 8 * CV_STRIDE + longint'(b) * 64, '0);
        end
        mon_clear();
        dcmd(OP_SLD, sdma_arg0(K_CV, 0, 7, 0), 0, 0, 8'h00, "SLD CV s0 L7");
        dma_wait("SLD CV s0 L7");
        chk(n_r == 2048, $sformatf("CV SLD took %0d R beats (want 2048)", n_r));
        dcmd(OP_SST, sdma_arg0(K_CV, 0, 8, 0), 0, 0, 8'h00, "SST CV s0 L8");
        dma_wait("SST CV s0 L8");
        bad = 0;
        for (int b = 0; b < 2048; b++)
            if (ddr_rword(CV_BASE + 8*CV_STRIDE + longint'(b)*64)
                !== ddr_rword(CV_BASE + 7*CV_STRIDE + longint'(b)*64)) bad++;
        chk(bad == 0, $sformatf("CV round trip: %0d of 2048 beats differ", bad));
    endtask

    // -- case 4: F1 load-before-use, with the nofence RED as its control -
    task automatic tc_f1_stall();
        int same;
        $display("-- case 4: f1_stall (DNST issued while its slot's SLD is in flight).  -G SDMA_NOFENCE=1 must FAIL this compare.");
        dn_fill(DN_BASE + 3 * DN_STRIDE, seed_i, 1);
        wr32(A_LAYER, layer_word(0, 0, 0, 0));
        // zero head 17 in the slot FIRST, so a fence bypass reads a state
        // whose DNST result case 1 already measured: o_zero.
        dcmd(OP_DNZ, 32'(GOLD_HEAD), 0, 0, 8'h00, "DNZ head 17 (warm + zero)");
        dn_stim();
        mon_clear();
        dcmd(OP_SLD, sdma_arg0(K_DN, 0, 3, 0), 0, 0, 8'h00, "SLD DN s0 L3");
        // NO dma_wait: F1 is what must hold the DNST off
        dn_run(0, o_dnz);
        same = 0;
        for (int i = 0; i < 128; i++) if (o_dnz[i] === o_loaded[i]) same++;
        chk(same == 128,
            $sformatf("F1: the DNST behind an in-flight SLD matched the LOADED result on %0d of 128 outputs — with the fence bypassed it reads the pre-load slot instead (this IS the nofence RED)", same));
        same = 0;
        for (int i = 0; i < 128; i++) if (o_dnz[i] === o_zero[i]) same++;
        chk(same < 128, "case 4 read the ZEROED state even with the fence on");
        chk(own_bad == 0, $sformatf("F1: the compute lane executed on %0d cycles while the DMA owned its slot", own_bad));
        dma_wait("case 4 drain");
    endtask

    // -- case 5: a cold slot is refused before any unit starts ----------
    task automatic tc_f1_cold();
        /* verilator lint_off UNUSEDSIGNAL */
        logic [31:0] st0, st1;
        /* verilator lint_on UNUSEDSIGNAL */
        $display("-- case 5: f1_cold (a compute command on a slot with no completed load since its last SST)");
        // slot 1 has never been loaded in this run
        wr32(A_LAYER, layer_word(1, 0, 0, 0));
        rd32(A_STAT, st0);
        wr32(A_LCYC, 32'd0);              // measure THIS refusal only
        dcmd(OP_DNST, 32'(GOLD_HEAD), 32'((SC_K << 16) | SC_Q),
             32'((SC_DST << 16) | SC_V), E_DMA_COLD, "DNST on cold DN slot 1");
        rd32(A_LCYC, st1);
        chk(st1 < 32'd200, $sformatf("cold refusal cost %0d LCYC cycles (no unit may start)", st1));
        // ...and on the other two kinds (fix round 1, M8).  KV slot 0 and
        // conv slot 1 have never been loaded in this run.  The KV case names
        // kvhead 0, which the reset tag also carries, so the tag check
        // cannot mask the cold refusal.
        wr32(A_LAYER, layer_word(0, 0, 0, 0));
        dcmd(OP_ATTN, 32'(0), 32'((SC_DST << 16) | SC_KVK), 0, E_DMA_COLD,
             "ATTN on cold KV slot 0");
        wr32(A_SDMA, 32'd0);
        wr32(A_LAYER, layer_word(0, 0, 1, 0));
        dcmd(OP_CONV, 32'h0001_0000, 32'((SC_DST << 16) | SC_V), 0,
             E_DMA_COLD, "CONV on cold conv slot 1");
        wr32(A_SDMA, 32'd0);
        wr32(A_LAYER, layer_word(0, 0, 0, 0));
    endtask

    // -- case 6: F2 — a queued transfer waits for the compute lane ------
    //
    // WHY THE SHAPE IS "SST BEHIND A LONG SLD, WITH A LONG CONV RUNNING".
    // A1.4 fixes the CMD accept gate at busy_cmp, and every command's ARG
    // words must stay stable for its whole duration, so an SLD/SST can only
    // be ISSUED while the compute lane is idle — the brief's literal
    // "DNST then SLD on the same slot" is unreachable through the CSR
    // interface.  What IS reachable, and is what F2 exists for, is a
    // transfer that reaches the HEAD of the queue while a compute command
    // is running on its slot: a long DN load ahead of it in the queue, and
    // a 8192-channel CONV (~41k cycles) holding the conv slot the queued
    // SST names.  `f2_wait_n` counts the cycles F2 actually held it, so the
    // case cannot pass vacuously.
    task automatic tc_f2_hold();
        $display("-- case 6: f2_hold (an SST queued behind a long SLD, with a CONV holding the SST's slot)");
        dn_fill(DN_BASE + 6 * DN_STRIDE, seed_i + 5, 0);
        wr32(A_LAYER, layer_word(0, 0, 0, 0));
        dcmd(OP_SLD, sdma_arg0(K_CV, 0, 7, 0), 0, 0, 8'h00, "SLD CV s0 L7");
        dma_wait("SLD CV s0 L7");
        mon_clear();
        mon_f2 = 1;
        // the long DN load goes first and holds the head for ~19k cycles
        dcmd(OP_SLD, sdma_arg0(K_DN, 1, 6, 0), 0, 0, 8'h00, "SLD DN s1 L6");
        // the SST of the CONV's slot queues behind it
        dcmd(OP_SST, sdma_arg0(K_CV, 0, 8, 0), 0, 0, 8'h00, "SST CV s0 L8");
        // ... and the CONV holds conv slot 0 for longer than the load takes
        dcmd(OP_CONV, 32'h0800_0000,                  // nch 8192, first 0
             32'((SC_CVD << 16) | SC_CVS), 0, 8'h00,
             "CONV 8192 channels on conv slot 0");
        dma_wait("case 6 drain");
        mon_f2 = 0;
        chk(f2_bad == 0, $sformatf("F2: %0d transfers started while a compute command held their slot", f2_bad));
        chk(xgo_n == 2, $sformatf("case 6 saw %0d xfer_go pulses (want 2)",
                                  xgo_n));
        chk(f2_wait_n > 0, "F2 never actually held the queued SST — case 6 proved nothing");
        $display("   F2 held the queued SST for %0d cycles", f2_wait_n);
    endtask

    // -- case 12 (fix round 1, C1): F2 at the F1-stall RELEASE ----------
    //
    // THE HOLE THIS CASE EXISTS FOR.  `cmp_holds` and the F1 stall condition
    // are registered in DIFFERENT always_ff blocks, so on the cycle F1
    // releases a stalled compute command the DMA lane still reads
    // `cmd_pend = 1` and concludes that nothing holds the slot — and starts
    // the queued transfer on that very slot in the same cycle the command
    // dispatches.  Queue = [SLD DN s0 (long), SST DN s0]; the DNST on DN s0
    // is F1-stalled by the pending SLD and released the moment the SLD
    // completes, which is exactly when the SST reaches the head.
    //
    // The OTHER form the review names — two CMD writes two cycles apart —
    // this testbench CANNOT drive: an SLD/SST and a compute command need
    // different ARG0 words, and each AXI-Lite write is a full AW/W/B
    // handshake, so `cmd_go` pulses can never be closer than about ten
    // cycles here.  Both forms are the same tie between the same two
    // always_ff blocks, and the combinational claim wire closes both.
    task automatic tc_f2_release();
        int same;
        int unsigned ob0;
        $display("-- case 12: f2_release (F1 releases a stalled DNST in the same cycle the queued SST on its slot reaches the head)");
        dn_fill(DN_BASE + 3 * DN_STRIDE, seed_i, 1);
        dn_zero(DN_BASE + 4 * DN_STRIDE);
        dn_stim();
        ob0 = own_bad;
        dcmd(OP_SLD, sdma_arg0(K_DN, 0, 3, 0), 0, 0, 8'h00, "SLD DN s0 L3");
        dcmd(OP_SST, sdma_arg0(K_DN, 0, 4, 0), 0, 0, 8'h00, "SST DN s0 L4");
        dn_run(0, o_tmp);          // F1-stalled, then released
        chk(own_bad == ob0,
            $sformatf("F2 at the stall release: the DMA owned DN slot 0 on %0d cycles while the released DNST was running", own_bad - ob0));
        same = 0;
        for (int i = 0; i < 128; i++) if (o_tmp[i] === o_loaded[i]) same++;
        chk(same == 128, $sformatf("the released DNST read the wrong state on %0d of 128 outputs", 128 - same));
        dma_wait("case 12 drain");
    endtask

    // -- case 8: the per-slot scope of ownership and of F1/F2 ------------
    task automatic tc_f2_other_slot();
        int same, bad;
        $display("-- case 8: f2_other_slot (a transfer on one slot of a kind in flight while a compute command holds the OTHER)");
        dn_fill(DN_BASE + 3 * DN_STRIDE, seed_i, 1);
        dn_fill(DN_BASE + 6 * DN_STRIDE, seed_i + 5, 0);
        dn_zero(DN_BASE + 10 * DN_STRIDE);
        dcmd(OP_SLD, sdma_arg0(K_DN, 0, 3, 0), 0, 0, 8'h00, "SLD DN s0 L3");
        dma_wait("SLD DN s0 L3");
        dn_stim();
        mon_clear();
        dcmd(OP_SLD, sdma_arg0(K_DN, 1, 6, 0), 0, 0, 8'h00, "SLD DN s1 L6");
        dn_run(0, o_tmp);                 // NOT stalled: the other DN slot
        chk(ovl_n > 0, "the DN slot-1 SLD and the slot-0 DNST never overlapped");
        $display("   the two lanes overlapped for %0d cycles", ovl_n);
        same = 0;
        for (int i = 0; i < 128; i++) if (o_tmp[i] === o_loaded[i]) same++;
        chk(same == 128, $sformatf("the concurrent slot-1 load disturbed the slot-0 DNST on %0d of 128 outputs", 128 - same));
        dma_wait("case 8 drain");
        dcmd(OP_SST, sdma_arg0(K_DN, 1, 10, 0), 0, 0, 8'h00, "SST DN s1 L10");
        dma_wait("SST DN s1 L10");
        bad = dn_blk_cmp(DN_BASE + 10*DN_STRIDE, DN_BASE + 6*DN_STRIDE, 0, 0);
        chk(bad == 0, $sformatf("the concurrent slot-1 load landed wrong in %0d of 4096 rows", bad));
    endtask

    // -- case 7: SST then SLD of one slot, in order --------------------
    task automatic tc_f2_order();
        int bad;
        $display("-- case 7: f2_order (SST then SLD of the same slot: every write response collected before the first read address)");
        dn_fill(DN_BASE + 3 * DN_STRIDE, seed_i + 11, 0);
        dcmd(OP_SLD, sdma_arg0(K_DN, 0, 3, 0), 0, 0, 8'h00, "SLD DN s0 L3");
        dma_wait("SLD DN s0 L3");
        dn_zero(DN_BASE + 4 * DN_STRIDE);
        mon_clear();
        mon_ord = 1;
        dcmd(OP_SST, sdma_arg0(K_DN, 0, 4, 0), 0, 0, 8'h00, "SST DN s0 L4");
        dcmd(OP_SLD, sdma_arg0(K_DN, 0, 4, 0), 0, 0, 8'h00, "SLD DN s0 L4");
        dma_wait("case 7 drain");
        mon_ord = 0;
        chk(ord_bad == 0, $sformatf("order: %0d read addresses issued with write responses outstanding", ord_bad));
        // and the slot round-tripped through the store it queued ahead
        dcmd(OP_SST, sdma_arg0(K_DN, 0, 5, 0), 0, 0, 8'h00, "SST DN s0 L5");
        dma_wait("case 7 verify");
        bad = 0;
        for (int r = 0; r < 4096; r++)
            if (ddr_rrow(DN_BASE + 5*DN_STRIDE + longint'(r)*256)
                !== ddr_rrow(DN_BASE + 3*DN_STRIDE + longint'(r)*256)) bad++;
        chk(bad == 0, $sformatf("SST->SLD->SST of one slot: %0d rows differ",
                                bad));
    endtask

    // -- case 9: the top edge of the address arithmetic -----------------
    task automatic tc_last_blocks();
        longint want_lo, want_hi;
        $display("-- case 9: last_blocks (DN L23, KV L7 h3 V, CV L23 — the top of each region, against plan_state()'s end)");
        // DN layer 23
        dn_fill(DN_BASE + 23 * DN_STRIDE, seed_i + 21, 0);
        mon_clear();
        dcmd(OP_SLD, sdma_arg0(K_DN, 1, 23, 0), 0, 0, 8'h00, "SLD DN s1 L23");
        dma_wait("SLD DN s1 L23");
        want_lo = DN_BASE + 23 * DN_STRIDE;
        want_hi = want_lo + DN_STRIDE;
        chk(ad_lo == want_lo && ad_hi == want_hi,
            $sformatf("DN L23 touched [%0h,%0h), want [%0h,%0h)",
                      ad_lo, ad_hi, want_lo, want_hi));
        // KV layer 7, kvhead 3, V — the last KV block
        wr32(A_LAYER, layer_word(0, 0, 0, 7));
        wr32(A_TCNT2, {3'b0, 13'd8, 3'b0, 13'd0});          // kvhead 3 -> T=8
        kv_fill(KV_BASE + longint'((7*4 + 3)*2 + 1) * KV_STRIDE, 8, seed_i + 4);
        mon_clear();
        dcmd(OP_SLD, sdma_arg0(K_KV, 0, 7, 3*2 + 1), 0, 0, 8'h00,
             "SLD KV s0 L7 h3 V");
        dma_wait("SLD KV s0 L7 h3 V");
        want_lo = KV_BASE + longint'((7*4 + 3)*2 + 1) * KV_STRIDE;
        want_hi = want_lo + KV_EXP_OFF + 64;
        chk(ad_lo == want_lo && ad_hi == want_hi,
            $sformatf("KV L7 h3 V touched [%0h,%0h), want [%0h,%0h)",
                      ad_lo, ad_hi, want_lo, want_hi));
        chk(want_hi <= KV_BASE + 64 * KV_STRIDE,
            "the last KV block runs past the KV region");
        // CV layer 23 — the last conv block, and the region's end
        mon_clear();
        dcmd(OP_SLD, sdma_arg0(K_CV, 1, 23, 0), 0, 0, 8'h00, "SLD CV s1 L23");
        dma_wait("SLD CV s1 L23");
        want_lo = CV_BASE + 23 * CV_STRIDE;
        want_hi = want_lo + CV_STRIDE;
        chk(ad_lo == want_lo && ad_hi == want_hi,
            $sformatf("CV L23 touched [%0h,%0h), want [%0h,%0h)",
                      ad_lo, ad_hi, want_lo, want_hi));
        chk(want_hi == STATE_END,
            $sformatf("the last CV block ends at %0h, plan_state end is %0h",
                      want_hi, STATE_END));
    endtask

    // -- case 10: every error code on its own cause ---------------------
    task automatic tc_errors();
        /* verilator lint_off UNUSEDSIGNAL */
        logic [31:0] d, c0, c1;
        /* verilator lint_on UNUSEDSIGNAL */
        $display("-- case 10: e_base / e_range / e_layer / e_axi");
        // --- E_DMA_BASE: the kind's base CSR is zero at dispatch
        wr32(A_SB_DN, 32'd0);
        dcmd(OP_SLD, sdma_arg0(K_DN, 0, 3, 0), 0, 0, E_DMA_BASE,
             "SLD DN with SB_DN = 0");
        wr32(A_SB_DN, 32'(SB_DN_V));
        wr32(A_SDMA, 32'd0);
        // --- E_DMA_RANGE, one cause at a time
        dcmd(OP_SLD, sdma_arg0(3, 0, 0, 0), 0, 0, E_DMA_RANGE, "SLD kind 3");
        wr32(A_SDMA, 32'd0);
        dcmd(OP_SLD, sdma_arg0(K_DN, 0, 0, 1), 0, 0, E_DMA_RANGE,
             "SLD DN head 1 (A1.1: a DN transfer is a whole layer)");
        wr32(A_SDMA, 32'd0);
        dcmd(OP_SLD, sdma_arg0(K_KV, 0, 8, 0), 0, 0, E_DMA_RANGE,
             "SLD KV layer 8 (max 7)");
        wr32(A_SDMA, 32'd0);
        dcmd(OP_SLD, sdma_arg0(K_CV, 0, 0, 1), 0, 0, E_DMA_RANGE,
             "SLD CV head 1");
        wr32(A_SDMA, 32'd0);
        dcmd(OP_SLD, sdma_arg0(K_DN, 0, 3, 0), 32'd1, 0, E_DMA_RANGE,
             "SLD with arg1 = 1 (reserved)");
        wr32(A_SDMA, 32'd0);
        dcmd(OP_SLD, sdma_arg0(K_DN, 0, 3, 0), 0, 32'd1, E_DMA_RANGE,
             "SLD with arg2 = 1 (reserved)");
        wr32(A_SDMA, 32'd0);
        wr32(A_LAYER, layer_word(0, 0, 0, 2));
        wr32(A_TCNT, {3'b0, 13'd0, 3'b0, 13'd4097});
        dcmd(OP_SLD, sdma_arg0(K_KV, 0, 2, 0), 0, 0, E_DMA_RANGE,
             "SLD KV with TCNT 4097 (> T_MAX)");
        wr32(A_TCNT, {3'b0, 13'd0, 3'b0, 13'd0});
        wr32(A_SDMA, 32'd0);
        // --- E_LAYER: a LAYER slot field above 1 at a compute dispatch
        wr32(A_LAYER, layer_word(2, 0, 0, 0));
        dcmd(OP_DNZ, 32'(GOLD_HEAD), 0, 0, E_LAYER, "DNZ with dn_slot = 2");
        wr32(A_LAYER, layer_word(0, 0, 0, 0));
        wr32(A_SDMA, 32'd0);
        // --- E_ENV: the S9 envelope still reports, now with a code
        dcmd(OP_CONV, 32'h0000_6000, 0, 0, E_ENV,      // nch 1, first 8192
             "CONV past the conv slot's 8192 rows");
        wr32(A_SDMA, 32'd0);
        // --- E_DMA_AXI: SLVERR on one burst, sticky, host-cleared
        bfm_err_addr = 34'(DN_BASE + 3*DN_STRIDE + 4096);
        bfm_err_en   = 1'b1;
        dcmd(OP_SLD, sdma_arg0(K_DN, 0, 3, 0), 0, 0, 8'h00,
             "SLD DN s0 L3 with an injected SLVERR (accepted at dispatch)");
        dma_wait("errored SLD");
        rd32(A_STAT, d);
        chk(d[1] === 1'b1, "E_DMA_AXI did not set STATUS.err_op");
        rd32(A_SDMA, d);
        chk(d[7:0] === E_DMA_AXI,
            $sformatf("SDMA.err = %02h after an SLVERR, want 12", d[7:0]));
        bfm_err_en = 1'b0;
        // sticky ACROSS the next compute dispatch (spec A1.4)
        rd32(A_STAT, c0);
        wr32(A_ARG0, 32'(GOLD_HEAD)); wr32(A_ARG1, 32'd0); wr32(A_ARG2, 32'd0);
        wr32(A_CMD, 32'(OP_DNZ));
        forever begin
            rd32(A_STAT, c1);
            if (c1[31:16] == 16'(c0[31:16] + 16'd1)) break;
            repeat (20) @(negedge aclk);
        end
        chk(c1[1] === 1'b1, "E_DMA_AXI was cleared by the next dispatch");
        rd32(A_SDMA, d);
        chk(d[7:0] === E_DMA_AXI, "SDMA.err was cleared by the next dispatch");
        // ...and a LATER REFUSAL must not overwrite the sticky code either
        // (fix round 1, I4): the refusal still sets err_op, but SDMA.err
        // keeps reading 0x12 until the host clears it.
        dcmd(OP_SLD, sdma_arg0(3, 0, 0, 0), 0, 0, E_DMA_AXI,
             "SLD kind 3 refused while E_DMA_AXI stands");
        rd32(A_STAT, d);
        chk(d[1] === 1'b1, "the refusal after E_DMA_AXI cleared err_op");
        wr32(A_SDMA, 32'd0);
        rd32(A_SDMA, d);
        chk(d[7:0] === 8'h00, "a write to SDMA did not clear err");
        rd32(A_STAT, d);
        chk(d[1] === 1'b0, "a write to SDMA did not clear err_op");
    endtask

    // -- case 11: DNZ/CONVZ warm their slot; busy_any vs the accept gate -
    task automatic tc_warm_and_busy();
        /* verilator lint_off UNUSEDSIGNAL */
        logic [31:0] c0, c1, d;
        /* verilator lint_on UNUSEDSIGNAL */
        $display("-- case 11: dnz_warms / convz_warms / busy_any");
        // DNZ warms a cold DN slot, so the DNST behind it is accepted
        wr32(A_LAYER, layer_word(1, 0, 1, 0));
        dcmd(OP_SST, sdma_arg0(K_DN, 1, 4, 0), 0, 0, 8'h00,
             "SST DN s1 (make it cold again)");
        dma_wait("cold slot 1");
        dcmd(OP_DNZ, 32'(GOLD_HEAD), 0, 0, 8'h00, "DNZ on a cold slot");
        dcmd(OP_DNST, 32'(GOLD_HEAD), 32'((SC_K << 16) | SC_Q),
             32'((SC_DST << 16) | SC_V), 8'h00, "DNST after DNZ warmed slot 1");
        // CONVW sel 2 (CONVZ) warms the conv slot; sel 0/1 are retired
        dcmd(OP_CONVW, 32'h0004_0002, 0, 0, 8'h00,    // nch 4, first 0, sel 2
             "CONVZ on a cold conv slot");
        dcmd(OP_CONV, 32'h0001_0000,                  // nch 4, first 0
             32'((SC_DST << 16) | SC_V), 0, 8'h00, "CONV after CONVZ warmed it");
        dcmd(OP_CONVW, 32'h0004_0000, 0, 0,
             E_DMA_RANGE, "CONVW sel 0 (retired: conv blocks arrive by SLD)");
        wr32(A_SDMA, 32'd0);
        dcmd(OP_CONVW, 32'h0004_0001, 0, 0,
             E_DMA_RANGE, "CONVW sel 1 (retired)");
        wr32(A_SDMA, 32'd0);
        // busy_any: STATUS bit 0 is high during an SLD, and the accept gate
        // (busy_cmp) still takes the NEXT SLD.
        wr32(A_LAYER, layer_word(0, 0, 0, 0));
        dn_fill(DN_BASE + 3 * DN_STRIDE, seed_i + 31, 0);
        rd32(A_STAT, c0);
        wr32(A_ARG0, sdma_arg0(K_DN, 0, 3, 0));
        wr32(A_ARG1, 32'd0); wr32(A_ARG2, 32'd0);
        wr32(A_CMD, 32'(OP_SLD));
        rd32(A_STAT, d);
        chk(d[0] === 1'b1, "busy_any is not set while an SLD is in flight");
        chk(d[31:16] == 16'(c0[31:16] + 16'd1),
            "cmd_cnt did not advance when the SLD was ENQUEUED");
        // a second SLD, accepted while busy_any is high
        rd32(A_STAT, c0);
        wr32(A_ARG0, sdma_arg0(K_DN, 1, 3, 0));
        wr32(A_CMD, 32'(OP_SLD));
        rd32(A_STAT, c1);
        chk(c1[31:16] == 16'(c0[31:16] + 16'd1),
            "the accept gate is busy_ANY, not busy_cmp: the second SLD was dropped");
        dma_wait("case 11 drain");
        rd32(A_STAT, d);
        chk(d[0] === 1'b0, "busy_any stayed set after the DMA lane drained");
        rd32(A_SDMACY, d);
        chk(d > 32'd1000, $sformatf("SDMA_CYC = %0d after two 1 MiB loads (want thousands)", d));
        wr32(A_SDMACY, 32'd0);
        rd32(A_SDMACY, d);
        chk(d === 32'd0, "a write to SDMA_CYC did not clear it");

        // the DMA queue is FOUR deep and the accept gate is busy_cmp, so six
        // back-to-back SLDs must all retire: #1 runs, #2..#5 fill the queue
        // and #6 is HELD at dispatch until there is room.  A silent drop
        // here would leave cmd_cnt short and the last block unloaded.
        dn_fill(DN_BASE + 3 * DN_STRIDE, seed_i + 41, 0);
        dn_zero(DN_BASE + 10 * DN_STRIDE);
        rd32(A_STAT, c0);
        for (int i = 0; i < 6; i++)
            dcmd(OP_SLD, sdma_arg0(K_DN, int'(i[0]), 3, 0), 0, 0, 8'h00,
                 $sformatf("SLD DN s%0d L3 (queue depth %0d)", i[0], i));
        rd32(A_STAT, c1);
        chk(c1[31:16] == 16'(c0[31:16] + 16'd6),
            $sformatf("six queued SLDs retired %0d commands (want 6)",
                      c1[31:16] - c0[31:16]));
        chk(qhold_n > 0, "the DMA queue never actually filled — the six-SLD case proved nothing");
        $display("   a full DMA queue held a record at dispatch for %0d cycles", qhold_n);
        dma_wait("queue-depth drain");
        dcmd(OP_SST, sdma_arg0(K_DN, 1, 10, 0), 0, 0, 8'h00, "SST DN s1 L10");
        dma_wait("queue-depth verify");
        chk(dn_blk_cmp(DN_BASE + 10*DN_STRIDE, DN_BASE + 3*DN_STRIDE, 0, 0) == 0,
            "the sixth queued SLD did not land");
    endtask

    // ==================================================================
    // 7. the run
    // ==================================================================
    int unsigned wd_ms = 120;

    initial begin
        int fd, n;
        int unsigned pv;
        if (!$value$plusargs("vecdir=%s", vecdir)) vecdir = "vectors/s1";
        if ($value$plusargs("seed=%d", pv)) seed_i = pv;
        if ($value$plusargs("watchdog_ms=%d", pv)) wd_ms = pv;
        $readmemh({vecdir, "/dn_sin.hex"},  sin_v);
        $readmemh({vecdir, "/dn_sout.hex"}, sout_v);
        $readmemh({vecdir, "/dn_q.hex"}, gq);
        $readmemh({vecdir, "/dn_k.hex"}, gk);
        $readmemh({vecdir, "/dn_v.hex"}, gv);
        $readmemh({vecdir, "/dn_o.hex"}, go_);
        fd = $fopen({vecdir, "/dn_gates.txt"}, "r");
        if (fd == 0) $fatal(1, "TB_LAYER_SDMA: cannot open %s/dn_gates.txt",
                            vecdir);
        n = $fscanf(fd, "%d %d", g_dec, g_bet);
        if (n != 2) $fatal(1, "TB_LAYER_SDMA: bad dn_gates.txt");
        $fclose(fd);

        awvalid = 0; wvalid = 0; arvalid = 0; wstrb = 4'hF;
        awaddr = 0; araddr = 0; wdata = 0;
        repeat (8) @(negedge aclk);
        aresetn = 1;
        repeat (8) @(negedge aclk);

        $display("TB_LAYER_SDMA start: vecdir=%s seed=%0d nofence=%0d",
                 vecdir, seed_i, SDMA_NOFENCE);

        tc_dn_roundtrip();
        tc_kv_roundtrip();
        tc_cv_roundtrip();
        tc_f1_stall();
        tc_f1_cold();
        tc_f2_hold();
        tc_f2_release();
        tc_f2_order();
        tc_f2_other_slot();
        tc_last_blocks();
        tc_errors();
        tc_warm_and_busy();

        chk(own_bad == 0, $sformatf("the ownership invariant broke on %0d cycles across the whole run", own_bad));
        $display("TB_LAYER_SDMA PASS: %0d checks, seed %0d", checks, seed_i);
        $finish;
    end

    initial begin
        #1ms;
        forever begin
            #1ms;
            if ($time / 1000000 > 64'(wd_ms)) begin
                $display("WATCHDOG (%0d ms): dut.st=%0d busy_cmp=%0b busy_dma=%0b checks=%0d",
                         wd_ms, dut.st, dut.busy_cmp, dut.busy_dma, checks);
                $fatal(1, "TB_LAYER_SDMA: watchdog");
            end
        end
    end

endmodule
