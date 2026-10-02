// tb_matvec_chan: full-chain stage-2 sim — the exact hardware flow:
//   AXI-Lite: cfg -> x load (XWIN) -> doorbell -> poll done ->
//   read results (RES_DATA) ... vs golden, bit-exact.
// matvec_chan runs with truly asynchronous aclk(250M)/ui_clk(300M);
// the AXI memory model (random AR/R timing) stands in for the MIG.
// 4 seeds via --seed; vectors via +vecdir.

`timescale 1ns/1ps

module tb_matvec_chan;

    localparam int MAXB = 1 << 16;
    localparam int MAXR = 1 << 12;
    localparam int MAXX = 3072;          // x words (K <= 12288)
    localparam int BASE_BEAT = 128;

    logic aclk = 0, ui_clk = 0;
    /* verilator lint_off BLKSEQ */
    always #2.000 aclk = ~aclk;       // 250 MHz
    always #1.667 ui_clk = (ui_stop && !ui_clk) ? 1'b0 : ~ui_clk;   // ~300 MHz, async to aclk; R3-8: +pushstall stops it (low)
    /* verilator lint_on BLKSEQ */
    logic aresetn = 0, ui_rstn = 0;

    // AXI-Lite
    logic [11:0] awaddr;  logic awvalid; logic awready;
    logic [31:0] wdata;   logic [3:0] wstrb; logic wvalid; logic wready;
    logic [1:0]  bresp;   logic bvalid; logic bready;
    logic [11:0] araddr;  logic arvalid; logic arready;
    logic [31:0] rdata;   logic [1:0] rresp; logic rvalid; logic rready;

    // AXI4 read
    logic [33:0]  m_araddr;
    logic [7:0]   m_arlen;
    logic [2:0]   m_arsize;
    logic [1:0]   m_arburst;
    logic         m_arvalid, m_arready;
    logic [511:0] m_rdata;
    logic [1:0]   m_rresp;
    logic         m_rlast, m_rvalid, m_rready;

    matvec_chan #(.CHAN_ID(4'd2)) dut (
        .aclk, .aresetn,
        .s_axil_awaddr(awaddr), .s_axil_awvalid(awvalid), .s_axil_awready(awready),
        .s_axil_wdata(wdata), .s_axil_wstrb(wstrb), .s_axil_wvalid(wvalid), .s_axil_wready(wready),
        .s_axil_bresp(bresp), .s_axil_bvalid(bvalid), .s_axil_bready(bready),
        .s_axil_araddr(araddr), .s_axil_arvalid(arvalid), .s_axil_arready(arready),
        .s_axil_rdata(rdata), .s_axil_rresp(rresp), .s_axil_rvalid(rvalid), .s_axil_rready(rready),
        // RUNG3 S5 burst window: idle here on purpose - this frozen stage-2
        // regression must keep passing through the AXI-Lite path alone, which
        // is exactly what it proves once the shim exists.  (Burst-window
        // coverage lives in tb_mvshim_b / tb_seq_chip.)
        .s_axib_awid(1'b0), .s_axib_awaddr(bw_awaddr), .s_axib_awlen(bw_awlen),   // R3-8: TB burst writer, idle unless +pushburst/+pushthenburst
        .s_axib_awsize(3'b010), .s_axib_awburst(2'b01), .s_axib_awvalid(bw_awvalid),
        /* verilator lint_off PINCONNECTEMPTY */
        .s_axib_awready(bw_awready), .s_axib_wready(bw_wready), .s_axib_bid(), .s_axib_bresp(bw_bresp),
        .s_axib_bvalid(bw_bvalid), .s_axib_arready(), .s_axib_rid(), .s_axib_rdata(),
        .s_axib_rresp(), .s_axib_rlast(), .s_axib_rvalid(),
        .mv_busy_bm(), .xpush_room(xp_room), .xpush_busy(xp_busy),  // BM1 (SEQ_ISA B16): not observed here; R3-8: the push leg's return
        /* verilator lint_on PINCONNECTEMPTY */
        .s_axib_wdata(bw_wdata), .s_axib_wstrb(4'hF), .s_axib_wlast(bw_wlast),
        .s_axib_wvalid(bw_wvalid), .s_axib_bready(bw_bready),
        .s_axib_arid(1'b0), .s_axib_araddr(16'd0), .s_axib_arlen(8'd0),
        .s_axib_arsize(3'b010), .s_axib_arburst(2'b01), .s_axib_arvalid(1'b0),
        .s_axib_rready(1'b0), .xpush_valid(xp_v), .xpush_idx(xp_idx), .xpush_data(xp_dat),   // R3-8: the x-push leg (TB = seq_0's side)
        .ui_clk, .ui_rstn,
        .m_axi_araddr(m_araddr), .m_axi_arlen(m_arlen), .m_axi_arsize(m_arsize),
        .m_axi_arburst(m_arburst), .m_axi_arvalid(m_arvalid), .m_axi_arready(m_arready),
        .m_axi_rdata(m_rdata), .m_axi_rresp(m_rresp), .m_axi_rlast(m_rlast),
        .m_axi_rvalid(m_rvalid), .m_axi_rready(m_rready)
    );

    /* verilator lint_off UNUSEDSIGNAL */
    wire unused_ok = (^m_arsize) ^ (^m_arburst);
    /* verilator lint_on UNUSEDSIGNAL */

    // ---- AXI read slave model (ui_clk) ----
    logic [511:0] mem [MAXB];
    logic [33:0] q_addr [16];
    logic [7:0]  q_len  [16];
    logic [4:0]  q_wr = 0, q_rd = 0;
    wire  [4:0]  q_count = q_wr - q_rd;
    logic [7:0]  beat_idx = 0;
    logic rready_seen = 0;

    initial begin
        m_arready = 0; m_rvalid = 0; m_rresp = 2'b00; m_rlast = 0; m_rdata = '0;
        forever begin
            @(negedge ui_clk);
            m_arready = (5'(q_wr - q_rd) < 5'd14) && ($urandom_range(0, 9) < 7);
            if (m_arvalid && m_arready) begin
                q_addr[q_wr[3:0]] = m_araddr;
                q_len[q_wr[3:0]]  = m_arlen;
                q_wr = q_wr + 1'b1;
            end
            if (m_rvalid && rready_seen) begin   // see tb_streamer_engine note
                if (m_rlast) begin
                    q_rd = q_rd + 1'b1; beat_idx = 0;
                end else beat_idx = beat_idx + 1'b1;
                m_rvalid = 0;
            end
            if (!m_rvalid && q_wr != q_rd && ($urandom_range(0, 9) < 8)) begin
                m_rdata  = mem[32'(q_addr[q_rd[3:0]] >> 6) + 32'(beat_idx)];
                m_rlast  = (beat_idx == q_len[q_rd[3:0]]);
                m_rvalid = 1;
            end
            rready_seen = m_rready;
        end
    end

    // ---- AXI-Lite master tasks (negedge discipline, see tb_csr) ----
    int errors = 0;
    task automatic check(input bit cond, input string msg);
        if (!cond) begin errors++; $display("[%0t] FAIL: %s", $time, msg); end
    endtask

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

    // ---- golden ----
    logic [31:0] golden [MAXR];
    logic [31:0] xwords [MAXX];
    logic [511:0] beats_raw [MAXB];
    /* verilator lint_off UNUSEDSIGNAL */
    int K, NG, SH, NROWS, BPR, NBEATS;
    /* verilator lint_on UNUSEDSIGNAL */

    // ---- SR12 (docs/SEQ_ISA.md B17.2): the R2 banks through the real CSR ----
    //   +xbank          SHAPE bit 29: x loaded at XPTR = 1536 (bank 0 first
    //                   POISONED with ~x), the engine must read line 48..
    //   +rbank          SHAPE bit 30: results read back from RES_PTR = 2048
    //   +overlap=<dir2> run A (+vecdir, banks 0) and, WHILE it streams, load
    //                   B's x into XWIN bank 1 (the MOVX-into-bank-1 case);
    //                   then run B with XBANK|RBANK: B's rows at 2048
    //                   bit-exact AND A's rows at 0 still intact.  Needs
    //                   NG <= 48 and NROWS <= 2048 for both.
    //   +dumprows       print every RES word read (ROWVAL r y32), so a +rbank
    //                   run diffs against the bank-0 run of the same vectors
    //                   (SR12 fix 1: q2/q3, ng 64/96, where XBANK cannot go)
    // The default (no plusarg) issues exactly the pre-SR12 CSR sequence, so
    // the frozen runs stay cycle-reproducible.
    localparam int XB_WORD = 1536;
    localparam int RB_ROW  = 2048;
    int XB = 0, RB = 0;
    bit ovl = 0;
    string vec2;
    logic [31:0] golden2 [MAXR];
    logic [31:0] xwords2 [MAXX];
    /* verilator lint_off UNUSEDSIGNAL */
    int K2, NG2, SH2, NROWS2, BPR2, NBEATS2;
    /* verilator lint_on UNUSEDSIGNAL */
    int BASE2 = 0;

    task automatic poll_done(output logic [31:0] s);
        int polls = 0;
        do begin
            repeat (20) @(negedge aclk);
            rd32(12'h004, s);
            polls++;
            if (polls > 50000) begin
                check(0, $sformatf("timeout: STATUS=%h", s));
                break;
            end
        end while (!s[1]);                       // done
        check(!s[2], "err_rresp set");
        check(!s[3], "xfifo overflow");
    endtask

    string vecdir;
    logic [31:0] rv, st;
    initial begin
        awvalid = 0; wvalid = 0; bready = 0; arvalid = 0; rready = 0;
        awaddr = '0; wdata = '0; wstrb = '0; araddr = '0;
        if (!$value$plusargs("vecdir=%s", vecdir)) $fatal(1, "need +vecdir=");
        begin
            int fd, n;
            fd = $fopen({vecdir, "/params.txt"}, "r");
            if (fd == 0) $fatal(1, "cannot open params.txt");
            n = $fscanf(fd, "%d %d %d %d %d", K, NG, SH, NROWS, BPR);
            if (n < 5) $fatal(1, "bad params.txt");
            $fclose(fd);
        end
        NBEATS = NROWS * BPR;
        $readmemh({vecdir, "/beats.hex"}, beats_raw);
        $readmemh({vecdir, "/y32.hex"},  golden);
        $readmemh({vecdir, "/x8.hex"},   xwords);
        for (int i = 0; i < NBEATS; i++) mem[BASE_BEAT + i] = beats_raw[i];

        // SR12 plusargs (see the block above)
        XB = $test$plusargs("xbank") ? 1 : 0;
        RB = $test$plusargs("rbank") ? 1 : 0; XP = ($test$plusargs("push") || $test$plusargs("pushthenburst")) ? 1 : 0;   // R3-8
        ovl = $value$plusargs("overlap=%s", vec2) != 0;
        if ((XB != 0 || ovl) && NG > 48)
            $fatal(1, "XBANK/overlap needs NG <= 48, %s has %0d", vecdir, NG);
        if (ovl) begin
            int fd, n;
            if (XB != 0 || RB != 0)
                $fatal(1, "+overlap runs A in bank 0 and B in bank 1 itself");
            fd = $fopen({vec2, "/params.txt"}, "r");
            if (fd == 0) $fatal(1, "cannot open %s/params.txt", vec2);
            n = $fscanf(fd, "%d %d %d %d %d", K2, NG2, SH2, NROWS2, BPR2);
            if (n < 5) $fatal(1, "bad %s/params.txt", vec2);
            $fclose(fd);
            if (NG2 > 48 || NROWS2 > RB_ROW)
                $fatal(1, "+overlap B (%s): NG %0d / NROWS %0d do not fit a bank",
                       vec2, NG2, NROWS2);
            NBEATS2 = NROWS2 * BPR2;
            $readmemh({vec2, "/beats.hex"}, beats_raw);
            $readmemh({vec2, "/y32.hex"},  golden2);
            $readmemh({vec2, "/x8.hex"},   xwords2);
            BASE2 = BASE_BEAT + NBEATS + 64;
            for (int i = 0; i < NBEATS2; i++) mem[BASE2 + i] = beats_raw[i];
        end

        repeat (8) @(negedge aclk);
        aresetn = 1; ui_rstn = 1;
        repeat (8) @(negedge aclk);

        $display("[%0t] phase: identity", $time);
        rd32(12'h034, rv); check(rv == 32'hFAB1C4A2, $sformatf("IDENT=%h", rv));

        $display("[%0t] phase: configure", $time);
        wr32(12'h008, 32'(BASE_BEAT * 64));     // WBASE_LO
        wr32(12'h00C, 32'h0);                   // WBASE_HI
        wr32(12'h010, 32'(NBEATS));             // WBEATS
        // SHAPE: {3'b0, ng[28:22], nrows[21:6], sh[5:0]} -- the G3.3
        // CONTIGUOUS layout.  Bits 29 (w8) and 28 (g64) went with the modes
        // they selected, and ng took bit 28 as its 7th so K = 12288 fits.
        // This expression is one of the SIX INDEPENDENT implementations of
        // the word (sw/hwmap.shape_word, rtl/matvec_chan.sv's decode,
        // ref/seq_format.py's disasm, ref/seq_model.py's executor, here,
        // and evidence/qwen9b/g3/isa_bits.py's checker).
        // SR12 (B17.2): bit 29 = XBANK, bit 30 = RBANK, bit 31 spare — zero
        // unless +xbank / +rbank, so the default word is the G3.3 one.
        wr32(12'h014, {1'b0, 1'(RB), 1'(XB), 7'(NG[6:0]), 16'(NROWS), 6'(SH[5:0])});
        rd32(12'h010, rv); check(rv == 32'(NBEATS), "WBEATS readback");
        // +shapeback only: the extra CSR read shifts the AXI model's
        // $urandom stream, and the frozen W4 vector runs must stay
        // cycle-reproducible against the committed stage-2 evidence.  The
        // 9B runs pass it, so the new field placement IS round-tripped
        // through the real CSR.
        if ($test$plusargs("shapeback")) begin
            rd32(12'h014, rv);
            // SR12: the bank bits are latched but NOT read back — [31:29]
            // still read 0 (rtl/matvec_chan.sv header), so what the banks
            // did is proved by the results, not the readback
            check(rv == {3'b0, 7'(NG[6:0]), 16'(NROWS), 6'(SH[5:0])},
                  $sformatf("SHAPE readback=%h", rv));
        end

        if (XP != 0) xp_prelude(); $display("[%0t] phase: x load", $time);   // R3-8: the collision / burst cases first
        // SR12 +xbank: POISON bank 0 with ~x first, so an engine that
        // ignores XBANK computes on a vector that is certainly wrong
        if (XB != 0) begin
            wr32(12'h028, 32'h0);
            for (int i = 0; i < (K + 3) / 4; i++)
                wr32(12'h024, ~xwords[i]);
        end
        wr32(12'h028, 32'(XB * XB_WORD));
        if (XP != 0) xp_load(XB * XB_WORD); else for (int i = 0; i < (K + 3) / 4; i++)   // R3-8: +push loads x on the push leg
            wr32(12'h024, xwords[i]);
        // XPTR is 12 bits and the x window holds 3072 words (K <= 12288),
        // so no production shape wraps the pointer any more; the modulo is
        // kept so the check still states the counter's real width.
        rd32(12'h028, rv);
        check(rv == 32'((XB * XB_WORD + ((XP != 0) ? 0 : (K + 3) / 4)) % 4096),   // R3-8: a push leaves XPTR (B17.3)
              $sformatf("XPTR=%0d want %0d (K=%0d)", rv,
                        (XB * XB_WORD + (K + 3) / 4) % 4096, K));

        $display("[%0t] phase: doorbell", $time);
        wr32(12'h000, 32'h1);

        // SR12 +overlap: B's x into XWIN bank 1 WHILE A streams from bank 0
        // (the MOVX-into-bank-1 case).  STATUS is sampled every 32 words;
        // the engine must be seen busy during the load, or the overlap is
        // not what ran.
        if (ovl) begin
            int nbusy = 0;
            $display("[%0t] phase: SR12 overlap — B's x -> bank 1 while A runs", $time);
            wr32(12'h028, 32'(XB_WORD));
            for (int i = 0; i < (K2 + 3) / 4; i++) begin
                if (i % 32 == 0) begin
                    rd32(12'h004, st);
                    if (st[0]) nbusy++;
                end
                wr32(12'h024, xwords2[i]);
            end
            check(nbusy > 0, "overlap: the engine was never busy during the bank-1 x load");
            $display("  overlap: engine busy at %0d of %0d STATUS samples during the %0d-word bank-1 load",
                     nbusy, ((K2 + 3) / 4 + 31) / 32, (K2 + 3) / 4);
        end

        $display("[%0t] phase: poll", $time);
        poll_done(st);

        $display("[%0t] phase: results", $time);
        wr32(12'h02C, 32'(RB * RB_ROW));         // RES_PTR = 0 / 2048
        for (int r = 0; r < NROWS; r++) begin
            rd32(12'h030, rv);
            check(rv == golden[r[11:0]],
                  $sformatf("row %0d: y32=%h golden=%h", r, rv, golden[r[11:0]]));
            // SR12 fix 1: +dumprows prints every RES word read, so a bank-1
            // run can be diffed against a bank-0 run of the same vectors
            if ($test$plusargs("dumprows"))
                $display("ROWVAL %0d %08h", r, rv);
        end

        // SR12 +overlap, second half: B on XBANK | RBANK
        if (ovl) begin
            $display("[%0t] phase: SR12 overlap — B on XBANK|RBANK", $time);
            wr32(12'h008, 32'(BASE2 * 64));
            wr32(12'h010, 32'(NBEATS2));
            wr32(12'h014, {1'b0, 1'b1, 1'b1, 7'(NG2[6:0]), 16'(NROWS2),
                           6'(SH2[5:0])});
            wr32(12'h000, 32'h1);
            poll_done(st);
            wr32(12'h02C, 32'(RB_ROW));
            for (int r = 0; r < NROWS2; r++) begin
                rd32(12'h030, rv);
                check(rv == golden2[r[11:0]],
                      $sformatf("B row %0d (RES %0d): y32=%h golden=%h", r,
                                RB_ROW + r, rv, golden2[r[11:0]]));
            end
            // bank 0 still holds A's rows: B wrote only 2048..
            wr32(12'h02C, 32'h0);
            for (int r = 0; r < NROWS; r++) begin
                rd32(12'h030, rv);
                check(rv == golden[r[11:0]],
                      $sformatf("A row %0d after B: y32=%h golden=%h", r, rv,
                                golden[r[11:0]]));
            end
            $display("  overlap: B %0d rows at RES 2048.. and A %0d rows at RES 0.. both bit-exact",
                     NROWS2, NROWS);
        end

        // perf report
        begin
            logic [31:0] pc_lo, pc_hi, pb;
            rd32(12'h018, pc_lo); rd32(12'h01C, pc_hi); rd32(12'h020, pb);
            $display("perf: %0d beats in %0d cycles", pb, {pc_hi[15:0], pc_lo});
            check(pb == 32'(ovl ? NBEATS2 : NBEATS), "perf_beats");
        end

        if (errors == 0) begin
            $display("TB_MATVEC_CHAN PASS: %0d rows bit-exact (K=%0d)",
                     NROWS, K);
            $finish;
        end else
            $fatal(1, "TB_MATVEC_CHAN FAIL: %0d errors", errors);
    end

    initial begin
        #200ms;
        $fatal(1, "TB_MATVEC_CHAN FAIL: global watchdog");
    end


    // ==================================================================
    // R3-8 (docs/SEQ_ISA.md v2.3 B17.3, spec §1.3 (a)) — THE X-PUSH LEG.
    // Appended below every cited line; the DUT connections, the ui_clk stop
    // and the x-load dispatch ride on their existing lines (20, 52-64, 212,
    // 272, 281, 287).  With none of the plusargs below the TB is the frozen
    // stage-2 / SR12 regression, unchanged: the burst writer and the push
    // source stay idle and ui_clk toggles as before.
    //
    // THE TB IS seq_0's SIDE of the bus, modelled flop for flop: it drives
    // xpush_valid/idx/data at NEGEDGE (= seq_movers' output flops), and its
    // push decision in cycle n uses the room value seq_movers' INPUT flop
    // holds, i.e. the room the channel showed two negedges earlier; busy the
    // same.  One word per cycle when room allows — four times the mover's
    // own rate (one word per four scratch beats), the worst case the skid
    // and XP_INFLIGHT are sized for.
    //
    //   +push            x via the push leg (bank 0, or bank 1 with +xbank;
    //                    +rbank as before) instead of AXI-Lite XWIN writes;
    //                    XPTR must stay where the host put it (B17.3)
    //   +pushstall=<n>   ui_clk STOPPED (the XWIN FIFO cannot drain) from the
    //                    first push until room drops, then n more cycles,
    //                    then released: no word lost, no push while the skid
    //                    is full (matvec_chan's own $fatal), room must drop
    //   +pushcoll        before the x load: (1) calibrate the XWIN FIFO's
    //                    capacity with ui stopped, (2) the FORCED collision —
    //                    FIFO one slot from full, an AXI-Lite XWIN write
    //                    committing while a push word waits in the skid
    //                    (swept over 8 phases; at least one must coincide):
    //                    AXI-Lite takes the last slot, xfifo_ovfl stays 0,
    //                    both words land
    //   +pushburst       a 64-beat s_axib XWIN burst (words 2800..) WHILE the
    //                    x pushes run: priority push > burst, never both in
    //                    one cycle (matvec_chan's $fatal), both land
    //   +pushthenburst   the broadcast-then-unicast case: ~x pushed to the
    //                    window, retired, then x BURST to the same window —
    //                    the engine must compute on x (no push word may land
    //                    after the retire and overwrite the burst's)
    //
    // THE COMMIT CONTRACT, as seq_movers keeps it: after the last push the
    // source waits XP_RT cycles, then retires on the first cycle its busy
    // input flop reads low; at that retire EVERY pushed word must already
    // have entered the XWIN FIFO (landed == sent), and any push-leg FIFO
    // write after it is a $fatal.  XP_RT here must equal matvec_chan's
    // XP_FWD_STAGES + XP_RET_STAGES (checked at time 0: one parameter set).
    // ==================================================================
    localparam int XP_RT = 4;
    localparam int XQD   = 8192;
    int  XP = 0;
    logic ui_stop = 1'b0;

    // TB burst writer (idle by default)
    logic [15:0] bw_awaddr = 16'd0;
    logic [7:0]  bw_awlen  = 8'd0;
    logic        bw_awvalid = 1'b0, bw_wlast = 1'b0, bw_wvalid = 1'b0;
    logic        bw_bready = 1'b0;
    logic [31:0] bw_wdata = 32'd0;
    wire         bw_awready, bw_wready, bw_bvalid;
    wire  [1:0]  bw_bresp;

    // the push source
    logic        xp_v = 1'b0;
    logic [11:0] xp_idx = 12'd0;
    logic [31:0] xp_dat = 32'd0;
    wire         xp_room, xp_busy;
    logic [11:0] xq_idx [XQD];
    logic [31:0] xq_dat [XQD];
    int unsigned xq_wp = 0, xq_rp = 0;
    bit          rh1 = 1'b0, rh2 = 1'b0, bh1 = 1'b1;
    int unsigned cyc_n = 0, last_push = 0, xp_sent = 0, xp_landed = 0;
    bit          xp_retired = 1'b1;
    int unsigned n_room_drop = 0, n_pb_both = 0, n_pb_burst = 0;
    int unsigned n_coll_hit = 0, n_retire = 0, skid_max = 0, occ = 0;
    int unsigned rt_wait_max = 0;

    function automatic logic [31:0] xm(input int w);
        return dut.u_engine.x_mem[w % 32][w / 32];
    endfunction

    task automatic xq_push(input int w, input logic [31:0] d);
        xq_idx[xq_wp % XQD] = 12'(w);
        xq_dat[xq_wp % XQD] = d;
        xq_wp++;
    endtask

    /* verilator lint_off BLKSEQ */
    always @(negedge aclk) begin
        cyc_n++;
        if (aresetn) begin
            // the push leg's FIFO writes (combinational in this cycle)
            if (dut.xf_push_p) begin
                if (xp_retired)
                    $fatal(1, "R3-8 COMMIT: a push-leg word (idx %0d) entered the XWIN FIFO after the source retired",
                           dut.xf_din_p[43:32]);
                xp_landed++;
            end
            if (ui_stop && dut.xf_push) occ++;
            if ((dut.xp_cnt != 0) && dut.ws_v && (dut.wstate == 2'd1)) n_pb_both++;
            if (dut.xf_push_b && (dut.xp_cnt != 0)) n_pb_burst++;
            if (32'(dut.xp_cnt) > skid_max) skid_max = 32'(dut.xp_cnt);
            // retire: queue empty, XP_RT cycles after the last push left the
            // output flop, and the busy INPUT FLOP (= busy one negedge ago) low
            if (!xp_retired && (xq_rp == xq_wp) && !xp_v
                && (cyc_n >= last_push + 1 + XP_RT) && !bh1) begin
                if (xp_landed != xp_sent)
                    $fatal(1, "R3-8 COMMIT: retired with %0d of %0d pushed words in the XWIN FIFO",
                           xp_landed, xp_sent);
                if (cyc_n - last_push > rt_wait_max) rt_wait_max = cyc_n - last_push;
                xp_retired = 1'b1;
                n_retire++;
            end
            // this cycle's output flop = the decision made with room from
            // two negedges ago (the input flop's view one cycle ago)
            if ((xq_rp != xq_wp) && rh2) begin
                xp_v = 1'b1;
                xp_idx = xq_idx[xq_rp % XQD];
                xp_dat = xq_dat[xq_rp % XQD];
                xq_rp++;
                xp_sent++;
                last_push = cyc_n;
                xp_retired = 1'b0;
            end else xp_v = 1'b0;
            if (rh1 && !xp_room) n_room_drop++;
            rh2 = rh1; rh1 = xp_room; bh1 = xp_busy;
        end
    end
    /* verilator lint_on BLKSEQ */

    task automatic xp_wait_retired();
        int guard = 0;
        do begin
            @(negedge aclk);
            guard++;
            if (guard > 200000) $fatal(1, "R3-8: the push source never retired (sent %0d landed %0d)",
                                       xp_sent, xp_landed);
        end while (!(xp_retired && (xq_rp == xq_wp)));
    endtask

    task automatic ui_drain();          // ui running, the XWIN FIFO empty
        int guard = 0;
        ui_stop = 1'b0;
        do begin
            @(negedge aclk);
            guard++;
            if (guard > 100000) $fatal(1, "R3-8: the XWIN FIFO never drained");
        end while (!dut.xf_empty);
        repeat (8) @(negedge aclk);
    endtask

    task automatic ui_halt();
        ui_drain();
        ui_stop = 1'b1;
        repeat (4) @(negedge aclk);
        occ = 0;
    endtask

    // s_axib XWIN burst of n words from word w0 (n <= 256, no 4 KiB crossing)
    task automatic bw_burst(input int w0, input int n, input bit inv,
                            input logic [31:0] base_pat);
        // negedge discipline as wr32: READY is sampled at the negedge BEFORE
        // the capturing posedge (it is a function of registered state only)
        @(negedge aclk);
        bw_awaddr = 16'(32'h4000 + 4 * w0); bw_awlen = 8'(n - 1); bw_awvalid = 1'b1;
        while (!bw_awready) @(negedge aclk);
        @(negedge aclk);
        bw_awvalid = 1'b0;
        for (int i = 0; i < n; i++) begin
            bw_wdata = (base_pat != 32'd0) ? (base_pat + 32'(i))
                                           : (inv ? ~xwords[w0 - XB * XB_WORD + i]
                                                  : xwords[w0 - XB * XB_WORD + i]);
            bw_wlast = (i == n - 1); bw_wvalid = 1'b1;
            while (!bw_wready) @(negedge aclk);
            @(negedge aclk);
        end
        bw_wvalid = 1'b0; bw_wlast = 1'b0; bw_bready = 1'b1;
        while (!bw_bvalid) @(negedge aclk);
        check(bw_bresp == 2'b00, "R3-8: XWIN burst BRESP not OKAY");
        @(negedge aclk);
        bw_bready = 1'b0;
    endtask

    task automatic xp_prelude();
        int cap;
        if (32'(dut.XP_FWD_STAGES + dut.XP_RET_STAGES) != 32'(XP_RT))
            $fatal(1, "R3-8: TB XP_RT %0d != matvec_chan XP_FWD_STAGES %0d + XP_RET_STAGES %0d",
                   XP_RT, dut.XP_FWD_STAGES, dut.XP_RET_STAGES);
        $display("[%0t] R3-8: XP_RT %0d = XP_FWD_STAGES %0d + XP_RET_STAGES %0d; XP_INFLIGHT %0d, skid %0d",
                 $time, XP_RT, dut.XP_FWD_STAGES, dut.XP_RET_STAGES,
                 dut.XP_INFLIGHT, dut.XP_SKID);
        if (!$test$plusargs("pushcoll")) return;
        // (1) calibrate the FIFO's capacity, ui stopped, 48 pushes
        $display("[%0t] R3-8 pushcoll: calibrate the XWIN FIFO capacity (ui stopped)", $time);
        ui_halt();
        for (int i = 0; i < 48; i++) xq_push(2900 + i, 32'hC0DE_0000 + 32'(i));
        while (!dut.xf_full) @(negedge aclk);
        cap = int'(occ);
        while (n_room_drop == 0) @(negedge aclk);
        repeat (64) @(negedge aclk);            // stalled: room low, skid holding
        check(xq_rp != xq_wp, "pushcoll: the source did not stall on room");
        ui_stop = 1'b0;
        xp_wait_retired();
        ui_drain();
        for (int i = 0; i < 48; i++)
            check(xm(2900 + i) == 32'hC0DE_0000 + 32'(i),
                  $sformatf("pushcoll calibrate: x_mem[%0d]=%h", 2900 + i, xm(2900 + i)));
        $display("  FIFO capacity %0d words (ui stopped); room dropped; 48/48 words landed", cap);
        // (2) the forced collision, swept over 8 phases
        for (int d = 0; d < 8; d++) begin
            int hit0;
            hit0 = int'(n_coll_hit);
            wr32(12'h028, 32'(3000 + d));               // XPTR for the AXI-Lite word
            ui_halt();
            for (int i = 0; i < cap - 1; i++) xq_push(2950 + (i % 40), 32'hF1F0_0000 + 32'(i));
            while (!((xq_rp == xq_wp) && (dut.xp_cnt == 0) && !xp_v && !dut.xp_in_v))
                @(negedge aclk);
            repeat (4) @(negedge aclk);
            check(!dut.xf_full && (occ == 32'(cap - 1)),
                  $sformatf("pushcoll d=%0d: FIFO not one slot from full (occ %0d cap %0d full %0d)",
                            d, occ, cap, dut.xf_full));
            fork
                wr32(12'h024, 32'hA11E_0000 + 32'(d));  // AXI-Lite XWIN at 3000+d
                begin
                    repeat (d) @(negedge aclk);
                    xq_push(2990 + d, 32'hB0B0_0000 + 32'(d));
                end
                begin : coll_mon
                    for (int k = 0; k < 40; k++) begin
                        @(negedge aclk);
                        if (dut.axil_wr_commit && (dut.xp_cnt != 0) && !dut.xf_full)
                            n_coll_hit++;
                    end
                end
            join
            check(!dut.xfifo_ovfl, $sformatf("pushcoll d=%0d: xfifo_ovfl set (the AXI-Lite word was dropped)", d));
            ui_stop = 1'b0;
            xp_wait_retired();
            ui_drain();
            check(xm(3000 + d) == 32'hA11E_0000 + 32'(d),
                  $sformatf("pushcoll d=%0d: AXI-Lite word x_mem[%0d]=%h", d, 3000 + d, xm(3000 + d)));
            check(xm(2990 + d) == 32'hB0B0_0000 + 32'(d),
                  $sformatf("pushcoll d=%0d: push word x_mem[%0d]=%h", d, 2990 + d, xm(2990 + d)));
            $display("  pushcoll d=%0d: %s", d, (int'(n_coll_hit) > hit0)
                     ? "AXI-Lite commit WITH a push waiting and one free slot (the forced case)"
                     : "no coincidence at this phase");
        end
        check(n_coll_hit > 0, "pushcoll: no phase forced the collision (vacuous)");
        $display("[%0t] R3-8 pushcoll: %0d forced collisions over 8 phases; xfifo_ovfl 0; every word landed",
                 $time, n_coll_hit);
    endtask

    task automatic xp_load(input int base);
        int nw, stall;
        bit ptb, pb;
        nw  = (K + 3) / 4;
        ptb = $test$plusargs("pushthenburst");
        pb  = $test$plusargs("pushburst");
        if (!$value$plusargs("pushstall=%d", stall)) stall = -1;
        $display("[%0t] R3-8 x load on the PUSH leg: %0d words at %0d%s%s%s", $time, nw,
                 base, ptb ? " (~x, then x by burst)" : "",
                 pb ? " + a concurrent burst" : "",
                 (stall >= 0) ? $sformatf(" + ui stopped until room drops, +%0d", stall) : "");
        if (stall >= 0) ui_halt();
        for (int i = 0; i < nw; i++) xq_push(base + i, ptb ? ~xwords[i] : xwords[i]);
        fork
            if (pb) begin
                repeat (6) @(negedge aclk);
                bw_burst(2800, 64, 1'b0, 32'hBB00_0000);
            end
            if (stall >= 0) begin
                int g = 0;
                while (n_room_drop == 0) begin
                    @(negedge aclk);
                    g++;
                    if (g > 100000) $fatal(1, "+pushstall: room never dropped");
                end
                repeat (stall) @(negedge aclk);
                ui_stop = 1'b0;
            end
        join
        xp_wait_retired();
        ui_drain();
        if (pb) begin
            for (int i = 0; i < 64; i++)
                check(xm(2800 + i) == 32'hBB00_0000 + 32'(i),
                      $sformatf("pushburst: burst word x_mem[%0d]=%h", 2800 + i, xm(2800 + i)));
            check(n_pb_both > 0, "pushburst: a push and a burst beat never contended (vacuous)");
        end
        if (ptb) begin
            for (int w = 0; w < nw; w += 256)
                bw_burst(base + w, (nw - w > 256) ? 256 : (nw - w), 1'b0, 32'd0);
            ui_drain();
        end
        for (int i = 0; i < nw; i++)
            check(xm(base + i) == xwords[i],
                  $sformatf("x_mem[%0d]=%h want %h (%s)", base + i, xm(base + i), xwords[i],
                            ptb ? "burst after the pushes" : "pushed"));
        if (stall >= 0) check(n_room_drop > 0, "+pushstall: room never dropped (vacuous)");
        check(n_pb_burst == 0, $sformatf("priority: a burst beat drained %0d times while a push word waited in the skid (push > burst)", n_pb_burst));
        $display("R3-8 XPUSH: sent %0d landed %0d, retires %0d (max %0d cycles last-push -> retire), room drops %0d, skid max %0d, push+burst contended %0d cycles (burst drained beside a waiting push %0d)",
                 xp_sent, xp_landed, n_retire, rt_wait_max, n_room_drop, skid_max,
                 n_pb_both, n_pb_burst);
    endtask

endmodule
