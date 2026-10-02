// tb_layer_chan: replay a gen_layer_script.py command script against
// layer_chan over AXI-Lite, comparing every R/E record bit-exactly.
// The script's final R of each token is the layer_decode_fx golden.
`timescale 1ns/1ps
module tb_layer_chan;
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

    // RUNG3 S6 tie-off: dangling outputs need named nets (an empty pin
    // connection trips -Wall's PINCONNECTEMPTY).
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
        // RUNG3 S6: this frozen back-compat TB drives the AXI-Lite path only,
        // so the burst slave is tied idle (mechanical tie-off, no behaviour
        // change: every *VALID and *READY the DUT samples is 0).
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
        // S3: the state DMA's 512-bit master.  ARSIZE/ARBURST and the IDs
        // are tied constant in rtl/layer_chan_ipi.v, so the model is given
        // the same constants here.
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
    // S3: the DDR state region behind the layer's own AXI4 master
    // ==================================================================
    // `tb/seq_mem_file.sv`'s writable window, loaded from the script's own
    // `<prefix>.state.bin` -- the artifact `ref/gen_layer_script`'s
    // dump_state writes and the host uploads.  It is the SAME model the
    // chip TB uses, so the conv taps this replay's CONV commands read are
    // the ones the emitter put in the image, not a zero-filled BFM.
    // `win_base`/`win_len` come from the script's S record (B15.3).
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

    seq_mem_file #(.ADDR_W(34), .DATA_W(512), .LAT(8), .NREG(0), .QD(4),
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

    // CSR byte addresses
    localparam logic [11:0] A_CMD = 12'h00, A_STAT = 12'h04, A_ARG0 = 12'h08,
                            A_ARG1 = 12'h0C, A_ARG2 = 12'h10, A_SPTR = 12'h14,
                            A_SWIN = 12'h18, A_EOUT = 12'h1C, A_TCNT = 12'h20,
                            A_LAYER = 12'h030, A_DNSB = 12'h05C,
                            A_TCNT2 = 12'h060,   // G3.4: kvheads 2/3
                            // S3 (SEQ_ISA v2.1 B15.3)
                            A_SB_DN = 12'h064, A_SB_KV = 12'h068,
                            A_SB_CV = 12'h06C;

    // ==================================================================
    // G3.4 DIRECTED MODES (+dnbank / +envtest).  These do NOT replay a
    // script: they are self-checking structural tests of the 9B banking
    // and of spec 5.4's envelope, and they need no reference model —
    // every one of them asserts that two things WHICH MUST BE
    // INDEPENDENT produce identical results from identical inputs.
    // That is exactly the property the pre-G3.4 geometry did not have:
    // head 16 aliased head 0 (dn_head_hw = dn_head[3:0]), kvhead 2
    // aliased kvhead 0 (kvhead_hw = kvhead_r[0]) AND shared its append
    // counter, dn_slot 18..23 and kv_slot 6..7 addressed banks that did
    // not exist, and conv channel 8188 was past a 6144-deep bank.
    // ==================================================================
    localparam int OP_CONVW = 5, OP_CONV = 6, OP_GATE = 7, OP_DNST = 8,
                   OP_KVAP = 9, OP_ATTN = 10, OP_DNZ = 12;
    // rtl/layer_chan.sv CVD — the conv memories' depth (CONV_DIM at 4B/9B)
    localparam int LR_CVD = 8192;

    // scratch map for the directed modes
    localparam int SC_DEC = 'h100, SC_BET = 'h140,      // 32 each
                   SC_K   = 'h200, SC_Q   = 'h400,      // 256 each
                   SC_V   = 'h600, SC_DST = 'h800,      // 512 out
                   SC_GB  = 'h1000, SC_GA = 'h1040, SC_GAA = 'h1080,
                   SC_GDT = 'h1100, SC_GO = 'h1140,     // GATE dst (+66)
                   SC_CW  = 'h1200, SC_CX = 'h1240, SC_CD = 'h1280;

    int derr = 0;

    task automatic dwr(input int addr, input int n, input int seed);
        int i;
        wr32(A_SPTR, 32'(addr));
        for (i = 0; i < n; i++)
            wr32(A_SWIN, 32'((seed + 37 * i) & 32'h3FFF));
    endtask

    task automatic dfill(input int addr, input int n, input int val);
        int i;
        wr32(A_SPTR, 32'(addr));
        for (i = 0; i < n; i++) wr32(A_SWIN, 32'(val));
    endtask

    // dispatch one command and check err_op against what is expected
    task automatic dcmd(input int op, input logic [31:0] a0, a1, a2,
                        input bit want_err, input string what);
        /* verilator lint_off UNUSEDSIGNAL */
        logic [31:0] c0, d;
        /* verilator lint_on UNUSEDSIGNAL */
        int guard;
        wr32(A_ARG0, a0); wr32(A_ARG1, a1); wr32(A_ARG2, a2);
        rd32(A_STAT, c0);
        wr32(A_CMD, 32'(op));
        guard = 0;
        forever begin
            rd32(A_STAT, d);
            if (d[31:16] == 16'(c0[31:16] + 16'd1) && !d[0]) break;
            repeat (20) @(negedge aclk);
            guard++;
            if (guard > 200000) $fatal(1, "%s: timeout", what);
        end
        if (d[1] !== want_err) begin
            derr++;
            $display("FAIL %s: err_op=%0b, expected %0b", what, d[1], want_err);
        end else if (want_err)
            $display("  ENV REFUSED (err_op=1) as required: %s", what);
    endtask

    task automatic dread(input int addr, input int n, ref int unsigned dbuf[]);
        /* verilator lint_off UNUSEDSIGNAL */
        logic [31:0] d;
        /* verilator lint_on UNUSEDSIGNAL */
        int i;
        wr32(A_SPTR, 32'(addr));
        for (i = 0; i < n; i++) begin
            rd32(A_SWIN, d);
            dbuf[i] = 32'(d[15:0]);
        end
    endtask

    task automatic dcmp(ref int unsigned a[], ref int unsigned b[],
                        input int n, input string what);
        int i, bad;
        bad = 0;
        for (i = 0; i < n; i++)
            if (a[i] !== b[i]) begin
                if (bad < 4)
                    $display("FAIL %s: word %0d got %04h want %04h",
                             what, i, b[i], a[i]);
                bad++;
            end
        if (bad != 0) begin
            derr++;
            $display("FAIL %s: %0d of %0d words differ", what, bad, n);
        end else
            $display("  OK %s: %0d words identical", what, n);
    endtask

    // ---------------- +dnbank: RETIRED by S3 -----------------------------
    // `run_dnbank` proved the G3.4 BANKING: that (dn_slot, head) pairs over
    // 24 DN banks, 8 KV banks and 24 conv banks were independent and that
    // every one of them really stored.  S3 RETIRES THE BANKS (SEQ_ISA v2.1
    // B15.2, spec 2026-09-04-qwen35-9b-state-spill-design.md 3): the layer
    // holds TWO CACHE SLOTS per kind and the layer identity lives in the
    // SLD/SST commands, so there is no 24-bank array left to prove
    // independent -- the property moved to the DDR image, where
    // `ref/seq_model.StateRegion` and the SEQ gate's STATE comparison hold
    // it, and to `tb/tb_layer_sdma.sv` (S2), which round-trips a block of
    // every kind through the real DMA.  The `tb_layer_dnbank` target goes
    // with it (tb/Makefile).
    //
    // What DID survive is the SLOT independence the two-slot cache needs,
    // and S2's directed testbench owns it.

    // ---------------- +envtest: spec 5.4 S9, each check FIRES -----------
    // S3 (SEQ_ISA v2.1) moves two families here.  The `dn_slot 24 has no
    // bank` cases are gone with the banks; their replacement is B15.2's
    // E_LAYER -- a LAYER slot field ABOVE 1 names a cache slot that does
    // not exist, and is refused at the next compute command.  And CONVW
    // sel 0/1 is RETIRED (B15.5): conv blocks arrive by SLD, so the two
    // cases that used to be "legal" are now refusals, and CONVW sel 2
    // (CONVZ) carries the legal half.
    task automatic run_envtest();
        int unsigned probe[];
        probe = new[4];
        wr32(A_LAYER, 32'd0);
        // the conv and DN slots must be WARM before any CONV/DNST can run
        // (B15.4 E_DMA_COLD); CONVZ and DNZ warm the slot they write.
        dcmd(OP_CONVW, 32'(2 | (0 << 2) | (LR_CVD << 16)), 0, 0, 0,
             "CONVZ warms conv slot 0");
        dcmd(OP_DNZ, 32'd0, 0, 0, 0, "DNZ warms DN slot 0 head 0");
        // VN: n = 1 << nlog2, and 12 (4096) is the 9B ceiling
        dcmd(1, 32'(13 << 2), 32'h0100_0000, 0, 1, "VN nlog2 13 > 12");
        dcmd(1, 32'(12 << 2), 32'h0100_0000, 0, 0, "VN nlog2 12 legal");
        // VNW: 4096 deep, and 0 MEANS 0
        dcmd(2, 32'd4097, 32'h0000_0100, 0, 1, "VNW len 4097 > 4096");
        dcmd(2, 32'd0,    32'h0000_0100, 0, 1, "VNW len 0 refused");
        dcmd(2, 32'd4096, 32'h0000_0100, 0, 0, "VNW len 4096 legal");
        // CONV / CONVW: first + nch must land inside the 8192-deep bank
        dcmd(OP_CONV,  32'(8190 | (4 << 14)), 32'h0128_0124, 0, 1,
             "CONV 8190+4 > 8192");
        dcmd(OP_CONV,  32'(8188 | (4 << 14)), 32'h0128_0124, 0, 0,
             "CONV 8188+4 legal");
        dcmd(OP_CONVW, 32'(2 | (8190 << 2) | (4 << 16)), 0, 0, 1,
             "CONVZ 8190+4 > 8192");
        dcmd(OP_CONVW, 32'(2 | (0 << 2) | (0 << 16)), 0, 0, 1,
             "CONVZ nch 0 refused (the retired wrap escape)");
        dcmd(OP_CONVW, 32'(2 | (8188 << 2) | (4 << 16)), 0, 0, 0,
             "CONVZ 8188+4 legal");
        // S3 (B15.5): CONVW sel 0 and sel 1 are RETIRED -- conv blocks
        // arrive by SLD -- and the RTL refuses them with E_DMA_RANGE.  The
        // field envelope is not what refuses these: the SUB-OP is.
        dcmd(OP_CONVW, 32'(0 | (0 << 2) | (4 << 16)), 32'h0000_0120, 0, 1,
             "CONVW sel 0 (weight load) is RETIRED");
        dcmd(OP_CONVW, 32'(1 | (0 << 2) | (4 << 16)), 32'h0000_0120, 0, 1,
             "CONVW sel 1 (state load) is RETIRED");
        // S3 (B15.2): a LAYER slot field ABOVE 1 names a cache slot that
        // does not exist, and is refused at the next COMPUTE command
        // (E_LAYER).  One case per field, because they are three fields.
        wr32(A_LAYER, 32'd2);                       // dn_slot = 2
        dcmd(OP_DNZ, 32'd0, 0, 0, 1, "DNZ at dn_slot 2 (E_LAYER)");
        dcmd(OP_DNST, 32'd0, 32'h0400_0200, 32'h0800_0600, 1,
             "DNST at dn_slot 2 (E_LAYER)");
        wr32(A_LAYER, 32'h10);                      // kv_slot = 2
        dcmd(OP_ATTN, 32'd0, 32'h0800_0400, 0, 1,
             "ATTN at kv_slot 2 (E_LAYER)");
        wr32(A_LAYER, 32'h2000);                    // cv_slot = 2
        dcmd(OP_CONV, 32'(0 | (4 << 14)), 32'h0128_0124, 0, 1,
             "CONV at cv_slot 2 (E_LAYER)");
        // and slot 1 of every kind is legal, once it is warm
        wr32(A_LAYER, 32'h1009);                    // cv/kv/dn slot 1
        dcmd(OP_CONVW, 32'(2 | (0 << 2) | (LR_CVD << 16)), 0, 0, 0,
             "CONVZ warms conv slot 1");
        dcmd(OP_DNZ, 32'd31, 0, 0, 0, "DNZ at dn_slot 1 head 31 legal");
        // B15.4 E_DMA_COLD: DN slot 1 head 31 is warm now, but the conv
        // slot the LAYER word below names has never been loaded.
        wr32(A_LAYER, 32'd0);
        dcmd(OP_DNZ, 32'd0, 0, 0, 0, "DNZ re-warms DN slot 0");
        // and the engine still works after a refusal: a real command runs
        dfill('h100, 4, 'h1234);
        dcmd(2, 32'd4, 32'h0000_0100, 0, 0, "VNW after refusals still runs");
        dread('h100, 4, probe);
        if (probe[0] !== 32'h1234) begin
            derr++;
            $display("FAIL scratch clobbered by a refused command");
        end
    endtask

    // Embedding table (+emb=<file.bin>, int16 LE rows of EMB_N words).
    // Read ON DEMAND (one row per M record) instead of slurped into a
    // static array: the real Qwen3.5 table is 248320 x 1024 x 2 B = 485 MiB,
    // far past any practical `logic [7:0] arr [...]` allocation. Only the
    // +emb= path changed; every other record is untouched.
    // R-b: the row size is RUNTIME (`+embn=<words>`, default the 0.8B
    // H=1024), the same widening seq_unit's EMBLOG2 CSR makes on the chip —
    // a 2B artifact has 2048-word rows and must replay through this TB too.
    // G3.4 (brief step 4): this was the bare literal 4096, which is EXACTLY
    // the 9B ceiling and fitted with ZERO MARGIN -- by luck, not by
    // construction.  It is DERIVED now.  The largest embedding row the
    // hardware can name is 2**EMBLOG2_MAX bytes (rtl/seq_unit.sv's
    // `EMBLOG2_MIN = 5'd8, EMBLOG2_MAX = 5'd13`), i.e. half that many int16
    // words, and the row buffer below is sized from it.  The elaboration
    // assert is what turns the coincidence into a contract: it fires if
    // anyone re-literalises EMB_N_MAX or moves the mirror without the
    // buffer.
    // A MIRROR of rtl/seq_unit.sv's EMBLOG2_MAX.  A testbench cannot see
    // another module's localparam, so the mirror is TIED BY
    // evidence/qwen9b/g3/isa_bits.py, which parses both and requires them
    // equal; the assert below is the LOCAL half (buffer vs mirror).
    localparam int TB_EMBLOG2_MAX = 13;   // == rtl/seq_unit.sv EMBLOG2_MAX
    localparam int EMB_N_MAX = (1 << TB_EMBLOG2_MAX) / 2;   // 4096 w = 8 KiB
    initial begin
        if (2 * EMB_N_MAX != (1 << TB_EMBLOG2_MAX))
            $fatal(1, {"tb_layer_chan: the embedding row buffer holds %0d B ",
                       "but the largest row EMBLOG2 can name is %0d B ",
                       "(EMBLOG2_MAX = %0d) -- EMB_N_MAX must stay DERIVED"},
                   2 * EMB_N_MAX, 1 << TB_EMBLOG2_MAX, TB_EMBLOG2_MAX);
    end
    int emb_n = 1024;                            // words per embedding row
    int emb_row_b = 2 * 1024;                    // bytes per embedding row
    logic [7:0] embrow [2 * EMB_N_MAX];
    int embfd;
    string script, embf;
    initial begin
        int fd, r, n, addr, op, a0, a1, a2, val, val2, i, ncmd, nchk;
        int tokid;
        bit dmode;
        longint embn;
        logic [31:0] d;
        /* verilator lint_off UNUSEDSIGNAL */
        logic [31:0] cnt0;   // only [31:16] (cmd_cnt) compared
        /* verilator lint_on UNUSEDSIGNAL */
        string tok;

        // G3.4: the two DIRECTED modes need no script at all.
        dmode = $test$plusargs("envtest");
        if (!dmode) begin
            if (!$value$plusargs("script=%s", script))
                $fatal(1, "need +script= (or +envtest)");
            fd = $fopen(script, "r");
            if (fd == 0) $fatal(1, "cannot open %s", script);
        end else fd = 0;

        embfd = 0;
        embn = 0;
        if (!dmode && $value$plusargs("embn=%d", emb_n)) begin
            if (emb_n <= 0 || emb_n > EMB_N_MAX)
                $fatal(1, "+embn=%0d outside [1,%0d]", emb_n, EMB_N_MAX);
        end
        emb_row_b = 2 * emb_n;
        if (!dmode && $value$plusargs("emb=%s", embf)) begin
            embfd = $fopen(embf, "rb");
            if (embfd == 0) $fatal(1, "cannot open %s", embf);
            r = $fseek(embfd, 0, 2);             // SEEK_END: table size
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

        if (dmode) begin
            run_envtest();
            if (derr == 0)
                $display("TB_LAYER_ENV PASS: every envelope check fired");
            else $fatal(1, "TB_LAYER_ENV FAIL: %0d", derr);
            $finish;
        end else begin

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
                    wr32(A_ARG0, 32'(a0));
                    wr32(A_ARG1, 32'(a1));
                    wr32(A_ARG2, 32'(a2));
                    rd32(A_STAT, cnt0);
                    wr32(A_CMD, 32'(op));
                    guard = 0;
                    forever begin
                        rd32(A_STAT, d);
                        if (d[31:16] == 16'(cnt0[31:16] + 16'd1)
                            && !d[0]) break;
                        repeat (20) @(negedge aclk);
                        guard++;
                        if (guard > 200000)
                            $fatal(1, "cmd %0d (op %0d) timeout", ncmd, op);
                    end
                    if (d[1]) begin
                        errors++; $display("FAIL cmd %0d: err_op", ncmd);
                    end
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
                    // G3.4: ONE script record, BOTH TCNT CSRs.  At NKVH=4
                    // a 32-bit word holds two 10-bit counters, so kvheads
                    // 2/3 live at TCNT2 (0x60); the emitter's Treset()
                    // zeroes all four, so the record must reach all four.
                    r = $fscanf(fd, " %h", val);
                    wr32(A_TCNT, 32'(val));
                    wr32(A_TCNT2, 32'(val));
                end
                "L": begin   // layer-select CSR write (LAYER @ 0x30)
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
                "B": begin   // G3.1 DNSB @ 0x5C: the DeltaNet scalar-pointer
                             // base pair {a_dec_base[31:16], a_beta[15:0]}
                    r = $fscanf(fd, " %h", val);
                    wr32(A_DNSB, 32'(val));
                end
                "V": begin   // hw matvec point: sim injects via W instead
                    int nrows;
                    r = $fscanf(fd, " %h %h %h %h", op, addr, n, nrows);
                    for (i = 0; i < nrows; i++) r = $fscanf(fd, " %h", val);
                end
                "M": begin   // embedding lookup: seek+read row tokid on demand
                    longint off;
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
                    // the buffer is EMB_N_MAX words, so a read returns the
                    // rest of the table (>= one row) unless it really is short
                    if ($fread(embrow, embfd) < emb_row_b)
                        $fatal(1, "emb $fread(tok %0d) short", tokid);
                    wr32(A_SPTR, 32'(addr));
                    for (i = 0; i < n; i++)
                        wr32(A_SWIN, {16'b0, embrow[2 * i + 1], embrow[2 * i]});
                end
                "A": begin   // AMAX32 winner check (idx + value CSRs)
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
            if (errors >= 20) $fatal(1, "TB_LAYER_CHAN FAIL: too many errors");
        end
        $fclose(fd);
        if (embfd != 0) $fclose(embfd);

        // S3 fix round 1, M2.  The same check tb_seq_chip.sv makes: a state
        // read the window did not cover is an address the DMA computed
        // wrong, and it is served as ZEROS rather than refused.  Counting
        // it and failing on it is what turns "the model was quiet" into
        // evidence.
        $display("  state: %0d read beats, %0d write beats, %0d unmapped",
                 sm_nbeats, sm_nwbeats, sm_nmiss);
        if (sm_nmiss != 0) begin
            errors++;
            $display("FAIL state DDR served %0d UNMAPPED beats (outside the window)",
                     sm_nmiss);
        end

        if (errors == 0) begin
            $display("TB_LAYER_CHAN PASS: %0d cmds, %0d checks bit-exact (%s)",
                     ncmd, nchk, script);
            $finish;
        end else $fatal(1, "TB_LAYER_CHAN FAIL: %0d errors", errors);
        end   // !dmode
    end

    initial begin
        int wd_ms;
        wd_ms = 400;                                  // default 400 ms
        void'($value$plusargs("watchdog_ms=%d", wd_ms));
        #(wd_ms * 1ms);                               // 1ms literal scales to timescale
        // S2 split `busy` into busy_cmp (the accept gate, LCYC's source)
        // and busy_any (STATUS bit 0); both are worth seeing here, and so
        // is the DMA lane, because a watchdog on the state path is most
        // likely a transfer that never completed.
        $display("WATCHDOG (%0d ms): dut.st=%0d busy_cmp=%0d busy_dma=%0d",
                 wd_ms, dut.st, dut.busy_cmp, dut.busy_dma);
        $fatal(1, "watchdog");
    end
endmodule
