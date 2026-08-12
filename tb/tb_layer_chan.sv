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
        .s_axib_awid(1'b0), .s_axib_awaddr(16'd0), .s_axib_awlen(8'd0),
        .s_axib_awsize(3'd2), .s_axib_awburst(2'b01), .s_axib_awvalid(1'b0),
        .s_axib_awready(nc_awready),
        .s_axib_wdata(32'd0), .s_axib_wstrb(4'd0), .s_axib_wlast(1'b0),
        .s_axib_wvalid(1'b0), .s_axib_wready(nc_wready),
        .s_axib_bid(nc_bid), .s_axib_bresp(nc_bresp),
        .s_axib_bvalid(nc_bvalid), .s_axib_bready(1'b0),
        .s_axib_arid(1'b0), .s_axib_araddr(16'd0), .s_axib_arlen(8'd0),
        .s_axib_arsize(3'd2), .s_axib_arburst(2'b01), .s_axib_arvalid(1'b0),
        .s_axib_arready(nc_arready),
        .s_axib_rid(nc_rid), .s_axib_rdata(nc_rdata),
        .s_axib_rresp(nc_rresp), .s_axib_rlast(nc_rlast),
        .s_axib_rvalid(nc_rvalid), .s_axib_rready(1'b0)
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
                            A_LAYER = 12'h030;

    // Embedding table (+emb=<file.bin>, int16 LE rows of EMB_N words).
    // Read ON DEMAND (one row per M record) instead of slurped into a
    // static array: the real Qwen3.5 table is 248320 x 1024 x 2 B = 485 MiB,
    // far past any practical `logic [7:0] arr [...]` allocation. Only the
    // +emb= path changed; every other record is untouched.
    localparam int EMB_N = 1024;                 // words per embedding row
    localparam int EMB_ROW_B = 2 * EMB_N;        // bytes per embedding row
    logic [7:0] embrow [EMB_ROW_B];
    int embfd;
    string script, embf;
    initial begin
        int fd, r, n, addr, op, a0, a1, a2, val, val2, i, ncmd, nchk;
        int tokid;
        longint embn;
        logic [31:0] d;
        /* verilator lint_off UNUSEDSIGNAL */
        logic [31:0] cnt0;   // only [31:16] (cmd_cnt) compared
        /* verilator lint_on UNUSEDSIGNAL */
        string tok;

        if (!$value$plusargs("script=%s", script)) $fatal(1, "need +script=");
        fd = $fopen(script, "r");
        if (fd == 0) $fatal(1, "cannot open %s", script);

        embfd = 0;
        embn = 0;
        if ($value$plusargs("emb=%s", embf)) begin
            embfd = $fopen(embf, "rb");
            if (embfd == 0) $fatal(1, "cannot open %s", embf);
            r = $fseek(embfd, 0, 2);             // SEEK_END: table size
            embn = $ftell(embfd);
            $display("emb table: %0d bytes (%0d rows of %0d) from %s",
                     embn, embn / longint'(EMB_ROW_B), EMB_N, embf);
        end

        repeat (5) @(negedge aclk);
        aresetn = 1;
        repeat (4) @(negedge aclk);

        rd32(12'h24, d);
        if (d !== 32'hFAB1E5A0) begin
            errors++; $display("FAIL IDENT: %h", d);
        end

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
                    r = $fscanf(fd, " %h", val);
                    wr32(A_TCNT, 32'(val));
                end
                "L": begin   // layer-select CSR write (LAYER @ 0x30)
                    r = $fscanf(fd, " %h", val);
                    wr32(A_LAYER, 32'(val));
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
                    if (n != EMB_N)
                        $fatal(1, "M record n=%0d, TB row buffer is %0d",
                               n, EMB_N);
                    off = longint'(tokid) * EMB_ROW_B;
                    if (off + longint'(EMB_ROW_B) > embn)
                        $fatal(1, "M record tok %0d past the %0d-byte table",
                               tokid, embn);
                    if ($fseek(embfd, int'(off), 0) != 0)
                        $fatal(1, "emb $fseek(tok %0d) failed", tokid);
                    if ($fread(embrow, embfd) != EMB_ROW_B)
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

        if (errors == 0) begin
            $display("TB_LAYER_CHAN PASS: %0d cmds, %0d checks bit-exact (%s)",
                     ncmd, nchk, script);
            $finish;
        end else $fatal(1, "TB_LAYER_CHAN FAIL: %0d errors", errors);
    end

    initial begin
        int wd_ms;
        wd_ms = 400;                                  // default 400 ms
        void'($value$plusargs("watchdog_ms=%d", wd_ms));
        #(wd_ms * 1ms);                               // 1ms literal scales to timescale
        $display("WATCHDOG (%0d ms): dut.st=%0d busy=%0d", wd_ms, dut.st, dut.busy);
        $fatal(1, "watchdog");
    end
endmodule
