// tb_layershim_c: unit gate for the rung-3 S6 burst window (docs/
// RUNG3_SPEC.md) on the REAL rtl/layer_chan.sv — no behavioural stub
// anywhere.  Agent-C namespace: obj_dir_tb_layershim_c.
//
// What it proves
//   T1  burst WRITE -> AXI-Lite SWIN readback, bit-exact (lengths 1, 2,
//       3, 255, 256 + random, random bases, random WVALID gaps)
//   T2  AXI-Lite SWIN write -> burst READ, bit-exact, RLAST exactly on
//       the final beat, RRESP=OKAY on every beat, random RREADY gaps
//   T3  SLVERR while busy.  A REAL vec_alu ADD command (op 4, len 1024)
//       is kicked through the CSRs; mid-command a burst write AND a
//       burst read are fired at the scratchpad.  Asserts: BRESP=SLVERR,
//       RRESP=SLVERR on EVERY beat with the full beat count and RLAST
//       (drained, never silently dropped — R8), the burst's target words
//       are untouched, and the command's 1024 results are bit-exact
//       against the golden -> the running command was not disturbed.
//   T4  the same burst re-issued once the command retires now lands with
//       BRESP=OKAY (the block is not sticky)
//   T5  busy from a NON-ALU command (DNZ) — the `busy && !alu_owns` mux
//       arm — also answers SLVERR and leaves the scratch alone
//   T6  AXI-Lite SWIN writes CONCURRENT with a burst write to a disjoint
//       region: the hardware arbitration (bw_grant) must lose no beat on
//       either side
//   T7  a WSTRB=0 beat is a legal no-op: consumed, OKAY, no write
//   T8  the mover fence: the FIRST burst issued after a CMD DONE poll
//       observes busy already low -> BRESP OKAY, never a spurious SLVERR
//
// plusargs:  +seed=<n>   own xorshift32 PRNG (reproducible on any sim)
// Discipline: every DUT input is driven at NEGEDGE and every DUT output
// is sampled at NEGEDGE (the DUT changes state on posedge).  Failures
// are $fatal(1, ...) — $finish does not set an exit code.

`timescale 1ns/1ps
module tb_layershim_c;

    logic aclk = 0;
    /* verilator lint_off BLKSEQ */
    always #2 aclk = ~aclk;
    /* verilator lint_on BLKSEQ */
    logic aresetn = 0;

    // ---- AXI-Lite (CSR) ----
    logic [11:0] awaddr;  logic awvalid; wire awready;
    logic [31:0] wdata;   logic [3:0] wstrb; logic wvalid; wire wready;
    wire  [1:0]  bresp;   wire bvalid;   logic bready = 0;
    logic [11:0] araddr;  logic arvalid; wire arready;
    wire  [31:0] rdata;   wire [1:0] rresp; wire rvalid; logic rready = 0;

    // ---- AXI4 burst window ----
    logic [0:0]  bawid;   logic [17:0] bawaddr; logic [7:0] bawlen;
    logic [2:0]  bawsize; logic [1:0]  bawburst;
    logic        bawvalid; wire bawready;
    logic [31:0] bwdata;  logic [3:0]  bwstrb; logic bwlast;
    logic        bwvalid; wire bwready;
    wire  [0:0]  bbid;    wire [1:0]   bbresp; wire bbvalid; logic bbready = 0;
    logic [0:0]  barid;   logic [17:0] baraddr; logic [7:0] barlen;
    logic [2:0]  barsize; logic [1:0]  barburst;
    logic        barvalid; wire barready;
    wire  [0:0]  brid;    wire [31:0]  brdata; wire [1:0] brresp;
    wire         brlast;  wire brvalid; logic brready = 0;

    /* verilator lint_off UNUSEDSIGNAL */
    wire [5:0] unused_tb = {bresp, rresp, bbid, brid};
    /* verilator lint_on UNUSEDSIGNAL */

    // S2: layer_chan gained the state-DMA master (m_axis).  This TB gates
    // the BURST WINDOW and issues no SLD/SST, so the master is tied idle —
    // a mechanical tie-off with no behaviour change: every *READY and
    // *VALID the DUT samples is 0.  The DMA's own gate is tb_layer_sdma.
    /* verilator lint_off UNUSEDSIGNAL */
    wire [33:0]  nc_mawaddr, nc_maraddr;
    wire [7:0]   nc_mawlen, nc_marlen;
    wire         nc_mawvalid, nc_mwlast, nc_mwvalid, nc_mbready,
                 nc_marvalid, nc_mrready;
    wire [511:0] nc_mwdata;
    wire [63:0]  nc_mwstrb;
    /* verilator lint_on UNUSEDSIGNAL */

    layer_chan #(
        .RSQRT_ROM("../rtl/roms/rsqrt_rom.hex"),
        .SIGMOID_ROM("../rtl/roms/sigmoid_pair_rom.hex"),
        .SOFTPLUS_ROM("../rtl/roms/softplus_pair_rom.hex"),
        .EXP2_ROM("../rtl/roms/exp2_pair_rom.hex"),
        .RECIP_ROM("../rtl/roms/recip_rom.hex")
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
        .s_axib_awid(bawid), .s_axib_awaddr(bawaddr), .s_axib_awlen(bawlen),
        .s_axib_awsize(bawsize), .s_axib_awburst(bawburst),
        .s_axib_awvalid(bawvalid), .s_axib_awready(bawready),
        .s_axib_wdata(bwdata), .s_axib_wstrb(bwstrb), .s_axib_wlast(bwlast),
        .s_axib_wvalid(bwvalid), .s_axib_wready(bwready),
        .s_axib_bid(bbid), .s_axib_bresp(bbresp), .s_axib_bvalid(bbvalid),
        .s_axib_bready(bbready),
        .s_axib_arid(barid), .s_axib_araddr(baraddr), .s_axib_arlen(barlen),
        .s_axib_arsize(barsize), .s_axib_arburst(barburst),
        .s_axib_arvalid(barvalid), .s_axib_arready(barready),
        .s_axib_rid(brid), .s_axib_rdata(brdata), .s_axib_rresp(brresp),
        .s_axib_rlast(brlast), .s_axib_rvalid(brvalid),
        .s_axib_rready(brready),
        .m_axis_awaddr(nc_mawaddr), .m_axis_awlen(nc_mawlen),
        .m_axis_awvalid(nc_mawvalid), .m_axis_awready(1'b0),
        .m_axis_wdata(nc_mwdata), .m_axis_wstrb(nc_mwstrb),
        .m_axis_wlast(nc_mwlast), .m_axis_wvalid(nc_mwvalid),
        .m_axis_wready(1'b0),
        .m_axis_bresp(2'b00), .m_axis_bvalid(1'b0),
        .m_axis_bready(nc_mbready),
        .m_axis_araddr(nc_maraddr), .m_axis_arlen(nc_marlen),
        .m_axis_arvalid(nc_marvalid), .m_axis_arready(1'b0),
        .m_axis_rdata(512'd0), .m_axis_rresp(2'b00),
        .m_axis_rlast(1'b0), .m_axis_rvalid(1'b0),
        .m_axis_rready(nc_mrready)
    );

    // ==================================================================
    // xorshift32 PRNG — reproducible independent of the simulator
    // ==================================================================
    int unsigned rs = 32'h1357_9BDF;
    function automatic int unsigned rnd32();
        rs = rs ^ (rs << 13);
        rs = rs ^ (rs >> 17);
        rs = rs ^ (rs << 5);
        return rs;
    endfunction
    function automatic int rndm(input int m);        // 0 .. m-1
        return int'(rnd32() % unsigned'(m));
    endfunction

    // ==================================================================
    // CSR map
    // ==================================================================
    localparam logic [11:0] A_CMD  = 12'h00, A_STAT = 12'h04, A_ARG0 = 12'h08,
                            A_ARG1 = 12'h0C, A_ARG2 = 12'h10, A_SPTR = 12'h14,
                            A_SWIN = 12'h18;
    localparam logic [1:0]  RESP_OK = 2'b00, RESP_SLVERR = 2'b10;

    int errors = 0;

    // ==================================================================
    // AXI-Lite master (negedge discipline, same shape as tb_layer_chan)
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

    // ==================================================================
    // shared buffers (module level: Verilator-friendly, no open arrays)
    // ==================================================================
    localparam int MAXB = 256;
    logic [15:0] tx_d   [MAXB];       // burst / SWIN write payload
    logic [15:0] rx_d   [MAXB];       // burst read capture
    logic [1:0]  rx_rsp [MAXB];
    logic        rx_lst [MAXB];
    logic [1:0]  last_bresp;
    int          rx_n;                // beats actually collected

    // CSR scratch values — every call site reads a different field, so the
    // unused-bit warning is expected and suppressed here only.
    /* verilator lint_off UNUSEDSIGNAL */
    logic [31:0] cs, cv;
    /* verilator lint_on UNUSEDSIGNAL */

    // ---- AXI-Lite SWIN helpers ----
    task automatic swin_wr(input int wbase, input int n);
        wr32(A_SPTR, 32'(wbase));
        for (int i = 0; i < n; i++) wr32(A_SWIN, {16'b0, tx_d[i]});
    endtask

    task automatic swin_rd(input int wbase, input int n);
        wr32(A_SPTR, 32'(wbase));
        for (int i = 0; i < n; i++) begin
            rd32(A_SWIN, cv);
            rx_d[i] = cv[15:0];
        end
    endtask

    // ==================================================================
    // AXI4 burst master
    //   gapw: 0 = no WVALID gaps, else a gap with probability 1/gapw
    // ==================================================================
    task automatic axib_wr(input int wbase, input int n, input int gapw,
                           input logic [3:0] strb);
        fork
            begin : aw_thread
                @(negedge aclk);
                bawid = 1'b0; bawaddr = 18'(wbase * 4); bawlen = 8'(n - 1);
                bawsize = 3'd2; bawburst = 2'b01; bawvalid = 1'b1;
                while (!bawready) @(negedge aclk);
                @(negedge aclk);
                bawvalid = 1'b0;
            end
            begin : w_thread
                int i;
                logic rdy;
                i = 0;
                @(negedge aclk);
                while (i < n) begin
                    if (gapw != 0 && rndm(gapw) == 0) begin
                        bwvalid = 1'b0;
                        @(negedge aclk);
                    end else begin
                        bwdata = {16'hFFFF, tx_d[i]};   // upper half MUST be
                        bwstrb = strb;                  // ignored by the shim
                        bwlast = (i == n - 1);
                        bwvalid = 1'b1;
                        rdy = bwready;   // the value in effect at the posedge
                        @(negedge aclk);
                        if (rdy) i++;
                    end
                end
                bwvalid = 1'b0;
            end
            begin : b_thread
                @(negedge aclk);
                bbready = 1'b1;
                while (!bbvalid) @(negedge aclk);
                last_bresp = bbresp;
                @(negedge aclk);
                bbready = 1'b0;
            end
        join
    endtask

    // gapr: 0 = RREADY always high, else stall with probability 1/gapr
    task automatic axib_rd(input int wbase, input int n, input int gapr);
        int i;
        @(negedge aclk);
        barid = 1'b0; baraddr = 18'(wbase * 4); barlen = 8'(n - 1);
        barsize = 3'd2; barburst = 2'b01; barvalid = 1'b1;
        while (!barready) @(negedge aclk);
        @(negedge aclk);
        barvalid = 1'b0;
        i = 0;
        while (i < n) begin
            brready = (gapr == 0) ? 1'b1 : (rndm(gapr) != 0);
            if (brvalid && brready) begin
                rx_d[i]   = brdata[15:0];
                rx_rsp[i] = brresp;
                rx_lst[i] = brlast;
                if (brdata[31:16] != 16'h0000)
                    $fatal(1, "T?: RDATA upper half not zero (%08h)", brdata);
                i++;
            end
            @(negedge aclk);
        end
        brready = 1'b0;
        rx_n = i;
    endtask

    // ==================================================================
    // command helpers
    // ==================================================================
    task automatic wait_idle();
        cs = 32'h1;
        while (cs[0]) rd32(A_STAT, cs);
    endtask

    task automatic wait_busy();
        cs = 32'h0;
        while (!cs[0]) rd32(A_STAT, cs);
    endtask

    function automatic logic [15:0] clip16(input int v);
        if (v >  32767) return 16'sh7FFF;
        if (v < -32768) return 16'sh8000;
        return 16'(v);
    endfunction

    // ==================================================================
    // scenarios
    // ==================================================================
    int seed_arg = 1;
    int t1_words = 0, t2_words = 0, t6_words = 0;

    // T3/T5 layout (disjoint regions inside the 65536-word scratchpad)
    // G3.1: SCR_WORDS is the ONE place the depth is written down here;
    // every burst placement below derives from it.
    localparam int SCR_WORDS = 65536;
    localparam int ALU_LEN  = 2048;
    localparam int A_SRCA   = 0;             //     0 .. 2047
    localparam int A_SRCB   = 2048;          //  2048 .. 4095
    localparam int A_DST    = 4096;          //  4096 .. 6143
    localparam int A_VICTIM = 8192;          //  8192 .. 8447  (burst target)
    localparam int VIC_N    = 256;
    localparam int N6       = 128;           // T6
    localparam int SW_BASE  = 10000;
    localparam int BU_BASE  = 12000;
    localparam int N7       = 8;             // T7
    localparam int B7       = 14000;

    logic [15:0] gold_dst [ALU_LEN];
    logic [15:0] gold_vic [VIC_N];
    logic [15:0] t2_wrote [MAXB];

    task automatic t1_burst_write_swin_read();
        int base, n;
        for (int c = 0; c < 12; c++) begin
            case (c)
                0: n = 1;    1: n = 2;    2: n = 3;
                3: n = 255;  4: n = 256;  5: n = 16;
                default: n = 1 + rndm(MAXB);
            endcase
            // G3.1: the window is SCR_WORDS words; case 0 pins the
            // burst at the very TOP so the new high half is always
            // exercised, and case 1 just under the OLD 32K top so the
            // R-b/G3.1 boundary itself is covered.
            base = (c == 0) ? (SCR_WORDS - n)
                 : (c == 1) ? (32768 - n)
                 : rndm(SCR_WORDS - n + 1);
            for (int i = 0; i < n; i++) tx_d[i] = 16'(rnd32());
            axib_wr(base, n, (c % 3 == 0) ? 0 : 4, 4'hF);
            if (last_bresp !== RESP_OK)
                $fatal(1, "T1: BRESP %02b on an idle burst write (base %0d n %0d)",
                       last_bresp, base, n);
            // SWIN readback: the AXI-Lite path must see exactly those words
            for (int i = 0; i < n; i++) rx_d[i] = 16'hDEAD;
            swin_rd(base, n);
            for (int i = 0; i < n; i++)
                if (rx_d[i] !== tx_d[i]) begin
                    $display("T1 MISMATCH base %0d i %0d: swin %04h != wrote %04h",
                             base, i, rx_d[i], tx_d[i]);
                    errors++;
                end
            t1_words += n;
        end
        if (errors != 0) $fatal(1, "T1: %0d mismatches", errors);
        $display("T1 OK: %0d words burst-written, SWIN readback bit-exact",
                 t1_words);
    endtask

    task automatic t2_swin_write_burst_read();
        int base, n;
        for (int c = 0; c < 8; c++) begin
            case (c)
                0: n = 1;    1: n = 2;    2: n = 256;
                default: n = 1 + rndm(MAXB);
            endcase
            base = (c == 0) ? (SCR_WORDS - n)
                 : (c == 1) ? (32768 - n)
                 : rndm(SCR_WORDS - n + 1);
            for (int i = 0; i < n; i++) begin
                tx_d[i] = 16'(rnd32());
                t2_wrote[i] = tx_d[i];
            end
            swin_wr(base, n);
            axib_rd(base, n, (c % 2 == 0) ? 0 : 3);
            if (rx_n != n) $fatal(1, "T2: got %0d beats, expected %0d", rx_n, n);
            for (int i = 0; i < n; i++) begin
                if (rx_d[i] !== t2_wrote[i]) begin
                    $display("T2 MISMATCH base %0d i %0d: burst %04h != swin %04h",
                             base, i, rx_d[i], t2_wrote[i]);
                    errors++;
                end
                if (rx_rsp[i] !== RESP_OK) begin
                    $display("T2: RRESP %02b on beat %0d of an idle read",
                             rx_rsp[i], i);
                    errors++;
                end
                if (rx_lst[i] !== ((i == n - 1) ? 1'b1 : 1'b0)) begin
                    $display("T2: RLAST %0b on beat %0d of %0d", rx_lst[i], i, n);
                    errors++;
                end
            end
            t2_words += n;
        end
        if (errors != 0) $fatal(1, "T2: %0d mismatches", errors);
        $display("T2 OK: %0d words SWIN-written, burst readback bit-exact",
                 t2_words);
    endtask

    // T3: a REAL vec_alu ADD (op 4) runs while bursts hammer the scratchpad
    task automatic t3_slverr_while_busy();
        int cnt0, cnt1;
        int nerr;

        // Operands + the victim region go in through the AXI-Lite path that
        // T1/T2 just proved.  |a|,|b| < 8192 so clip16 never fires and the
        // golden is a plain sum.
        for (int base = 0; base < ALU_LEN; base += MAXB) begin
            for (int i = 0; i < MAXB; i++) tx_d[i] = 16'(signed'(rnd32()) % 8192);
            swin_wr(A_SRCA + base, MAXB);
            for (int i = 0; i < MAXB; i++) gold_dst[base + i] = tx_d[i];
        end
        for (int base = 0; base < ALU_LEN; base += MAXB) begin
            for (int i = 0; i < MAXB; i++) tx_d[i] = 16'(signed'(rnd32()) % 8192);
            swin_wr(A_SRCB + base, MAXB);
            for (int i = 0; i < MAXB; i++)
                gold_dst[base + i] = clip16(int'(signed'(gold_dst[base + i]))
                                          + int'(signed'(tx_d[i])));
        end
        for (int i = 0; i < VIC_N; i++) begin
            tx_d[i] = 16'(rnd32());
            gold_vic[i] = tx_d[i];
        end
        swin_wr(A_VICTIM, VIC_N);

        rd32(A_STAT, cs);
        cnt0 = int'(cs[31:16]);

        // kick the command:  ALU op 4 (ADD), len 1024
        // G3.1: SEQ_ISA v2.0 pairs — ARG1 = {srcb[31:16], srca[15:0]} and
        // ARG2 = {dst[31:16], p0[15:0]}.  These were `<< 14` / `<< 17`, a
        // hand-coded v1.7 packing spec 7.5's family-B census did not list;
        // under v2.0 the ALU dst decoded as 8192 = A_VICTIM and the ADD
        // scribbled over the very region T3 checks for a blocked write, so
        // the failure read as "the blocked write landed" — a wrong-command
        // bug wearing a fabric bug's clothes.
        wr32(A_ARG0, 32'(ALU_LEN) << 4 | 32'd4);
        wr32(A_ARG1, 32'(A_SRCB) << 16 | 32'(A_SRCA));
        wr32(A_ARG2, 32'(A_DST)  << 16);
        wr32(A_CMD,  32'd11);
        wait_busy();

        // ---- burst WRITE into the victim region while busy ----
        for (int i = 0; i < VIC_N; i++) tx_d[i] = ~gold_vic[i];
        axib_wr(A_VICTIM, VIC_N, 0, 4'hF);
        if (last_bresp !== RESP_SLVERR)
            $fatal(1, "T3: BRESP %02b on a burst write while busy (want SLVERR)",
                   last_bresp);
        rd32(A_STAT, cs);
        if (!cs[0]) $fatal(1, "T3: command retired before the blocked write finished — test is not exercising the busy path");

        // ---- burst READ while busy: every beat SLVERR, none dropped ----
        axib_rd(A_VICTIM, VIC_N, 3);
        if (rx_n != VIC_N)
            $fatal(1, "T3: blocked read returned %0d beats, expected %0d",
                   rx_n, VIC_N);
        nerr = 0;
        for (int i = 0; i < VIC_N; i++) begin
            if (rx_rsp[i] === RESP_SLVERR) nerr++;
            if (rx_lst[i] !== ((i == VIC_N - 1) ? 1'b1 : 1'b0))
                $fatal(1, "T3: RLAST %0b on beat %0d of the blocked read",
                       rx_lst[i], i);
        end
        if (nerr != VIC_N)
            $fatal(1, "T3: only %0d/%0d blocked read beats answered SLVERR",
                   nerr, VIC_N);
        rd32(A_STAT, cs);
        if (!cs[0]) $fatal(1, "T3: command retired before the blocked read finished");

        // ---- the command must be completely unaffected ----
        wait_idle();
        rd32(A_STAT, cs);
        cnt1 = int'(cs[31:16]);
        if (cnt1 != cnt0 + 1)
            $fatal(1, "T3: cmd_cnt %0d -> %0d (expected +1)", cnt0, cnt1);
        for (int base = 0; base < ALU_LEN; base += MAXB) begin
            swin_rd(A_DST + base, MAXB);
            for (int i = 0; i < MAXB; i++)
                if (rx_d[i] !== gold_dst[base + i]) begin
                    $display("T3 ALU RESULT CORRUPTED at %0d: %04h != %04h",
                             base + i, rx_d[i], gold_dst[base + i]);
                    errors++;
                end
        end
        swin_rd(A_VICTIM, VIC_N);
        for (int i = 0; i < VIC_N; i++)
            if (rx_d[i] !== gold_vic[i]) begin
                $display("T3 BLOCKED WRITE LANDED at %0d: %04h != %04h",
                         i, rx_d[i], gold_vic[i]);
                errors++;
            end
        if (errors != 0) $fatal(1, "T3: %0d failures", errors);
        $display("T3 OK: burst W/R during a live ALU op 4 (len %0d) -> SLVERR on %0d/%0d read beats + BRESP SLVERR; %0d ALU results bit-exact; %0d victim words untouched",
                 ALU_LEN, nerr, VIC_N, ALU_LEN, VIC_N);
    endtask

    // T4: the very same burst, now that the engine is idle, must land
    task automatic t4_retry_after_busy();
        for (int i = 0; i < VIC_N; i++) tx_d[i] = ~gold_vic[i];
        axib_wr(A_VICTIM, VIC_N, 0, 4'hF);
        if (last_bresp !== RESP_OK)
            $fatal(1, "T4: BRESP %02b retrying the burst while idle", last_bresp);
        swin_rd(A_VICTIM, VIC_N);
        for (int i = 0; i < VIC_N; i++)
            if (rx_d[i] !== 16'(~gold_vic[i])) begin
                $display("T4 MISMATCH at %0d: %04h != %04h",
                         i, rx_d[i], 16'(~gold_vic[i]));
                errors++;
            end
        if (errors != 0) $fatal(1, "T4: %0d mismatches", errors);
        $display("T4 OK: the blocked burst retried clean once idle (%0d words)",
                 VIC_N);
        for (int i = 0; i < VIC_N; i++) gold_vic[i] = ~gold_vic[i];
    endtask

    // T5: busy from a NON-ALU command (DNZ) — the busy && !alu_owns arm
    task automatic t5_slverr_non_alu();
        int cnt0, cnt1;
        rd32(A_STAT, cs);
        cnt0 = int'(cs[31:16]);
        wr32(A_ARG0, 32'd3);            // DNZ head 3
        wr32(A_CMD,  32'd12);
        wait_busy();
        for (int i = 0; i < 16; i++) tx_d[i] = 16'hA5A5;
        axib_wr(A_VICTIM, 16, 0, 4'hF);
        if (last_bresp !== RESP_SLVERR)
            $fatal(1, "T5: BRESP %02b on a burst write during DNZ (want SLVERR)",
                   last_bresp);
        wait_idle();
        rd32(A_STAT, cs);
        cnt1 = int'(cs[31:16]);
        if (cnt1 != cnt0 + 1) $fatal(1, "T5: DNZ did not retire (%0d -> %0d)",
                                     cnt0, cnt1);
        swin_rd(A_VICTIM, 16);
        for (int i = 0; i < 16; i++)
            if (rx_d[i] !== gold_vic[i]) begin
                $display("T5 BLOCKED WRITE LANDED at %0d: %04h != %04h",
                         i, rx_d[i], gold_vic[i]);
                errors++;
            end
        if (errors != 0) $fatal(1, "T5: %0d failures", errors);
        $display("T5 OK: DNZ (busy, non-ALU mux arm) -> SLVERR, scratch untouched");
    endtask

    // T6: AXI-Lite SWIN writes CONCURRENT with a burst write, disjoint
    // regions.  Exercises the bw_grant collision arbitration: the SWIN
    // write wins the cycle, the shim holds its bundle and retries.
    logic [15:0] t6_swin_d [MAXB];
    task automatic t6_concurrent_swin_and_burst();
        for (int i = 0; i < N6; i++) t6_swin_d[i] = 16'(rnd32());
        fork
            begin : swin_thread
                wr32(A_SPTR, 32'(SW_BASE));
                for (int i = 0; i < N6; i++)
                    wr32(A_SWIN, {16'b0, t6_swin_d[i]});
            end
            begin : burst_thread
                for (int i = 0; i < N6; i++) tx_d[i] = 16'(rnd32() ^ 32'hFFFF);
                axib_wr(BU_BASE, N6, 0, 4'hF);
            end
        join
        if (last_bresp !== RESP_OK)
            $fatal(1, "T6: BRESP %02b on the concurrent burst", last_bresp);
        swin_rd(BU_BASE, N6);
        for (int i = 0; i < N6; i++)
            if (rx_d[i] !== tx_d[i]) begin
                $display("T6 BURST BEAT LOST at %0d: %04h != %04h",
                         i, rx_d[i], tx_d[i]);
                errors++;
            end
        swin_rd(SW_BASE, N6);
        for (int i = 0; i < N6; i++)
            if (rx_d[i] !== t6_swin_d[i]) begin
                $display("T6 SWIN WRITE LOST at %0d: %04h != %04h",
                         i, rx_d[i], t6_swin_d[i]);
                errors++;
            end
        if (errors != 0) $fatal(1, "T6: %0d failures", errors);
        t6_words = N6;
        $display("T6 OK: %0d SWIN writes concurrent with a %0d-beat burst, no beat lost on either side",
                 N6, N6);
    endtask

    // T7: WSTRB=0 is a legal no-op beat (consumed, OKAY, nothing written)
    task automatic t7_zero_strobe();
        for (int i = 0; i < N7; i++) tx_d[i] = 16'(rnd32());
        axib_wr(B7, N7, 0, 4'hF);
        for (int i = 0; i < N7; i++) rx_d[i] = tx_d[i];
        for (int i = 0; i < N7; i++) tx_d[i] = ~rx_d[i];
        axib_wr(B7, N7, 0, 4'h0);              // zero strobe: must not write
        if (last_bresp !== RESP_OK)
            $fatal(1, "T7: BRESP %02b on a zero-strobe burst (want OKAY)",
                   last_bresp);
        for (int i = 0; i < N7; i++) tx_d[i] = rx_d[i];
        swin_rd(B7, N7);
        for (int i = 0; i < N7; i++)
            if (rx_d[i] !== tx_d[i]) begin
                $display("T7 ZERO-STROBE BEAT WROTE at %0d: %04h != %04h",
                         i, rx_d[i], tx_d[i]);
                errors++;
            end
        if (errors != 0) $fatal(1, "T7: %0d failures", errors);
        $display("T7 OK: WSTRB=0 beats consumed, answered OKAY, wrote nothing");
    endtask

    // T8: the mover fence.  Agent A retires a record on its last B and
    // then polls the layer CMD DONE.  DONE_S drops busy and bumps cmd_cnt
    // on the SAME edge and STATUS latches both in the SAME cycle, so a
    // poll that observes completion can never be racing a still-high
    // busy.  Prove it: the FIRST burst issued after the poll must be
    // OKAY, never SLVERR, over many command/burst pairs.
    task automatic t8_burst_right_after_done();
        localparam int N8 = 32;
        for (int k = 0; k < 8; k++) begin
            wr32(A_ARG0, 32'd64 << 4 | 32'd4);       // short ALU ADD
            wr32(A_ARG1, 32'(A_SRCB) << 16 | 32'(A_SRCA));
            wr32(A_ARG2, 32'(A_DST)  << 16);
            wr32(A_CMD,  32'd11);
            wait_idle();                             // the DONE poll
            for (int i = 0; i < N8; i++) tx_d[i] = 16'(rnd32());
            axib_wr(A_VICTIM, N8, 0, 4'hF);          // first burst after it
            if (last_bresp !== RESP_OK)
                $fatal(1, "T8: spurious SLVERR on the first burst after the DONE poll (iter %0d)", k);
            swin_rd(A_VICTIM, N8);
            for (int i = 0; i < N8; i++)
                if (rx_d[i] !== tx_d[i]) begin
                    $display("T8 MISMATCH iter %0d i %0d: %04h != %04h",
                             k, i, rx_d[i], tx_d[i]);
                    errors++;
                end
        end
        if (errors != 0) $fatal(1, "T8: %0d failures", errors);
        $display("T8 OK: 8x (CMD -> DONE poll -> immediate burst) all BRESP OKAY and bit-exact");
    endtask

    // ==================================================================
    initial begin
        if (!$value$plusargs("seed=%d", seed_arg)) seed_arg = 1;
        rs = 32'(seed_arg) * 32'h9E37_79B1 + 32'h1234_5677;
        if (rs == 0) rs = 32'hDEADBEEF;

        awvalid = 0; wvalid = 0; arvalid = 0; wstrb = 4'hF;
        awaddr = '0; araddr = '0; wdata = '0;
        bawvalid = 0; bwvalid = 0; barvalid = 0;
        bawid = '0; bawaddr = '0; bawlen = '0; bawsize = 3'd2;
        bawburst = 2'b01; bwdata = '0; bwstrb = 4'hF; bwlast = 0;
        barid = '0; baraddr = '0; barlen = '0; barsize = 3'd2;
        barburst = 2'b01;

        repeat (20) @(negedge aclk);
        aresetn = 1;
        repeat (20) @(negedge aclk);

        t1_burst_write_swin_read();
        t2_swin_write_burst_read();
        t3_slverr_while_busy();
        t4_retry_after_busy();
        t5_slverr_non_alu();
        t6_concurrent_swin_and_burst();
        t7_zero_strobe();
        t8_burst_right_after_done();

        if (errors != 0) $fatal(1, "TB_LAYERSHIM_C FAIL: %0d errors", errors);
        $display("TB_LAYERSHIM_C PASS (seed %0d): T1 %0d w, T2 %0d w, T3 ALU %0d + %0d SLVERR beats, T6 %0d w, T4/T5/T7/T8 ok",
                 seed_arg, t1_words, t2_words, ALU_LEN, VIC_N, t6_words);
        $finish;
    end

    // watchdog (4 ns/cycle; the whole run is ~150k cycles)
    initial begin
        #20_000_000;
        $fatal(1, "TB_LAYERSHIM_C: watchdog timeout");
    end

endmodule
