// axi_ram_bfm: a RAM-backed AXI4 slave, 512-bit data, 34-bit address —
// the DDR model for the layer's state DMA (spec 2026-09-04 state-spill §4).
//
// WHY IT EXISTS.  `tb/seq_mem_file.sv` is READ-ONLY (araddr..rvalid, no
// AW/W/B — plan "Standing hazards"), so an RTL *store* has nothing to talk
// to.  This model is read/write, RAM-backed and self-contained, so
// `tb_layer_sdma` can round-trip a block DDR -> slot -> DDR and compare it
// byte for byte.  S3's chip-level DDR model may borrow it; nothing here
// knows about layer_chan.
//
// PROTOCOL.  AXI4, INC bursts only, one ID (tied off at the master), all
// beats 64 B (AWSIZE/ARSIZE = 3'b110 are tied constant in
// rtl/layer_chan_ipi.v and are therefore not ports here).  AW and AR are
// queued (depth AWQ/ARQ) so the master's outstanding-burst logic is
// actually exercised; W data follows AW order, which is what AXI requires
// of a single-ID master.  Every READY and VALID is gated by a pseudorandom
// bit derived from `+seed=<n>` if that plusarg is present and from the
// `SEED` parameter otherwise, so no test can accidentally depend on a
// back-to-back handshake AND the seeds a testbench sweeps really do produce
// different AXI timing (fix round 1, I2 — before it, all four seeds shared
// one gap pattern).  The seed in force is reported once at time 0.
//
// ERROR INJECTION (the E_DMA_AXI test).  When `err_en` is high — driven by
// the port, or latched once from a `+err_at=<hex byte address>` plusarg —
// the ONE burst whose address range covers `err_addr` answers SLVERR
// (RRESP on every beat of that burst, or BRESP).  Everything else answers
// OKAY, so the sticky-error test can tell "one burst failed" from "the
// model is broken".
//
// STATISTICS live in the TESTBENCH, not here: tb_layer_sdma declares the
// wires between layer_chan and this model and monitors them directly, so
// this file stays a pure protocol + memory model.

`timescale 1ns/1ps
`default_nettype none

module axi_ram_bfm #(
    parameter int DEPTH = 1024,        // 512-bit words (byte size = DEPTH*64)
    parameter int SEED  = 1,
    parameter int AWQ   = 16,          // queued write bursts
    parameter int ARQ   = 16           // queued read bursts
) (
    input  wire         aclk,
    input  wire         aresetn,

    // error injection (see the header)
    input  wire         err_en,
    input  wire [33:0]  err_addr,

    // ---- AXI4 slave, 512-bit ----
    input  wire [33:0]  awaddr,
    input  wire [7:0]   awlen,
    input  wire         awvalid,
    output logic        awready,
    input  wire [511:0] wdata,
    input  wire [63:0]  wstrb,
    input  wire         wlast,
    input  wire         wvalid,
    output logic        wready,
    output logic [1:0]  bresp,
    output logic        bvalid,
    input  wire         bready,
    input  wire [33:0]  araddr,
    input  wire [7:0]   arlen,
    input  wire         arvalid,
    output logic        arready,
    output logic [511:0] rdata,
    output logic [1:0]  rresp,
    output logic        rlast,
    output logic        rvalid,
    input  wire         rready
);
    localparam logic [1:0] RESP_OKAY   = 2'b00;
    localparam logic [1:0] RESP_SLVERR = 2'b10;

    localparam int AIW = $clog2(DEPTH);        // memory index width
    logic [511:0] mem [DEPTH];

    // ---- the plusarg form of the error window (the port ORs with it) ----
    logic        pa_err_en;
    logic [33:0] pa_err_addr;
    // the seed actually in force: +seed=<n> wins over the SEED parameter
    int unsigned bfm_seed;
    initial begin
        int unsigned pv;
        pa_err_en   = 1'b0;
        pa_err_addr = '0;
        if ($value$plusargs("err_at=%h", pv)) begin
            pa_err_en   = 1'b1;
            pa_err_addr = 34'(pv);
        end
        bfm_seed = SEED;
        void'($value$plusargs("seed=%d", bfm_seed));
        $display("AXI_RAM_BFM: %0d 512-bit words, handshake seed %0d",
                 DEPTH, bfm_seed);
        for (int i = 0; i < DEPTH; i++) mem[i] = '0;
    end
    wire        e_en = err_en | pa_err_en;
    wire [33:0] e_ad = err_en ? err_addr : pa_err_addr;

    // ---- pseudorandom handshake gaps (xorshift32, seeded) ----
    logic [31:0] lfsr;
    always_ff @(posedge aclk) begin
        if (!aresetn) lfsr <= bfm_seed ^ 32'h9E37_79B9;
        else begin
            logic [31:0] x;
            x = lfsr;
            x = x ^ (x << 13);
            x = x ^ (x >> 17);
            x = x ^ (x << 5);
            lfsr <= x;
        end
    end
    // 7-in-8 duty on every channel, on four independent bit triples
    wire g_aw = |lfsr[2:0];
    wire g_w  = |lfsr[5:3];
    wire g_b  = |lfsr[8:6];
    wire g_ar = |lfsr[11:9];
    wire g_r  = |lfsr[14:12];

    // ==================================================================
    // write address queue
    // ==================================================================
    localparam int AWQW = $clog2(AWQ);
    logic [33:0] awq_addr [AWQ];
    logic [7:0]  awq_len  [AWQ];
    logic [AWQW:0] awq_wp, awq_rp;
    wire [AWQW:0]  awq_cnt = awq_wp - awq_rp;
    assign awready = aresetn && g_aw && (awq_cnt < (AWQW+1)'(AWQ));

    // W engine
    logic        w_act;
    logic [33:0] w_addr;
    logic [8:0]  w_left;
    logic        w_err;
    assign wready = w_act && g_w;

    // B queue (one entry per completed write burst)
    localparam int BQ = AWQ + 2;
    localparam int BQW = $clog2(BQ);
    logic        bq_err [BQ];
    logic [BQW:0] bq_wp, bq_rp;

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            awq_wp <= '0; awq_rp <= '0;
            bq_wp  <= '0; bq_rp  <= '0;
            w_act  <= 1'b0; w_left <= '0; w_err <= 1'b0;
            bvalid <= 1'b0; bresp <= RESP_OKAY;
        end else begin
            if (awvalid && awready) begin
                awq_addr[awq_wp[AWQW-1:0]] <= awaddr;
                awq_len [awq_wp[AWQW-1:0]] <= awlen;
                awq_wp <= awq_wp + 1'b1;
            end
            // pop the next burst into the W engine
            if (!w_act && (awq_wp != awq_rp)) begin
                logic [33:0] a;
                logic [7:0]  l;
                a = awq_addr[awq_rp[AWQW-1:0]];
                l = awq_len [awq_rp[AWQW-1:0]];
                w_act  <= 1'b1;
                w_addr <= a;
                w_left <= 9'(l) + 9'd1;
                // SLVERR when the injected address falls inside this burst
                w_err  <= e_en && (e_ad >= a)
                          && (e_ad < a + 34'd64 * (34'(l) + 34'd1));
                awq_rp <= awq_rp + 1'b1;
            end
            if (wvalid && wready) begin
                logic [33:0] widx;
                widx = w_addr >> 6;
                if (widx < 34'(DEPTH)) begin
                    if (&wstrb) mem[widx[AIW-1:0]] <= wdata;
                    else for (int b = 0; b < 64; b++)
                        if (wstrb[b])
                            mem[widx[AIW-1:0]][8*b +: 8] <= wdata[8*b +: 8];
                end
                w_addr <= w_addr + 34'd64;
                w_left <= w_left - 9'd1;
                if (wlast || w_left == 9'd1) begin
                    w_act <= 1'b0;
                    bq_err[bq_wp[BQW-1:0]] <= w_err;
                    bq_wp <= bq_wp + 1'b1;
                end
            end
            // B channel
            if (!bvalid || bready) begin
                if ((bq_wp != bq_rp) && g_b) begin
                    bvalid <= 1'b1;
                    bresp  <= bq_err[bq_rp[BQW-1:0]] ? RESP_SLVERR : RESP_OKAY;
                    bq_rp  <= bq_rp + 1'b1;
                end else bvalid <= 1'b0;
            end
        end
    end

    // ==================================================================
    // read address queue + R engine
    // ==================================================================
    localparam int ARQW = $clog2(ARQ);
    logic [33:0] arq_addr [ARQ];
    logic [7:0]  arq_len  [ARQ];
    logic [ARQW:0] arq_wp, arq_rp;
    wire [ARQW:0]  arq_cnt = arq_wp - arq_rp;
    assign arready = aresetn && g_ar && (arq_cnt < (ARQW+1)'(ARQ));

    logic        r_act;
    logic [33:0] r_addr;
    logic [8:0]  r_left;
    logic        r_err;

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            arq_wp <= '0; arq_rp <= '0;
            r_act  <= 1'b0; r_left <= '0; r_err <= 1'b0;
            rvalid <= 1'b0; rlast <= 1'b0; rresp <= RESP_OKAY;
        end else begin
            if (arvalid && arready) begin
                arq_addr[arq_wp[ARQW-1:0]] <= araddr;
                arq_len [arq_wp[ARQW-1:0]] <= arlen;
                arq_wp <= arq_wp + 1'b1;
            end
            if (!r_act && (arq_wp != arq_rp)) begin
                logic [33:0] a;
                logic [7:0]  l;
                a = arq_addr[arq_rp[ARQW-1:0]];
                l = arq_len [arq_rp[ARQW-1:0]];
                r_act  <= 1'b1;
                r_addr <= a;
                r_left <= 9'(l) + 9'd1;
                r_err  <= e_en && (e_ad >= a)
                          && (e_ad < a + 34'd64 * (34'(l) + 34'd1));
                arq_rp <= arq_rp + 1'b1;
            end
            if (!rvalid || rready) begin
                if (r_act && g_r) begin
                    logic [33:0] ridx;
                    ridx = r_addr >> 6;
                    rvalid <= 1'b1;
                    rdata  <= (ridx < 34'(DEPTH)) ? mem[ridx[AIW-1:0]] : '0;
                    rresp  <= r_err ? RESP_SLVERR : RESP_OKAY;
                    rlast  <= (r_left == 9'd1);
                    r_addr <= r_addr + 34'd64;
                    r_left <= r_left - 9'd1;
                    if (r_left == 9'd1) r_act <= 1'b0;
                end else rvalid <= 1'b0;
            end
        end
    end

`ifndef SYNTHESIS
    // The master this model serves is a single-ID INC master; anything else
    // is a bug in state_dma, not a legal transaction this model may ignore.
    always_ff @(posedge aclk) begin
        if (aresetn) begin
            if (awvalid && awready && awlen > 8'd15)
                $fatal(1, "axi_ram_bfm: AWLEN %0d > 15 (1 KiB bursts)", awlen);
            if (arvalid && arready && arlen > 8'd15)
                $fatal(1, "axi_ram_bfm: ARLEN %0d > 15 (1 KiB bursts)", arlen);
            if (awvalid && awready && awaddr[5:0] != 6'd0)
                $fatal(1, "axi_ram_bfm: AWADDR %h not 64 B aligned", awaddr);
            if (arvalid && arready && araddr[5:0] != 6'd0)
                $fatal(1, "axi_ram_bfm: ARADDR %h not 64 B aligned", araddr);
            if (wvalid && wready && !w_act)
                $fatal(1, "axi_ram_bfm: W beat with no outstanding AW");
            // fix round 1, M3: WLAST must land on the burst's last beat and
            // nowhere else, and a full 16-beat burst must start 1 KiB aligned
            // (that alignment is what keeps a 1 KiB burst inside one 4 KiB
            // page, which the engine's header claims and nothing checked).
            if (wvalid && wready && wlast && w_left != 9'd1)
                $fatal(1, "axi_ram_bfm: early WLAST, %0d beats still owed",
                       w_left - 9'd1);
            if (wvalid && wready && !wlast && w_left == 9'd1)
                $fatal(1, "axi_ram_bfm: last W beat without WLAST");
            if (awvalid && awready && awlen == 8'd15 && awaddr[9:0] != 10'd0)
                $fatal(1, "axi_ram_bfm: 16-beat AW at %h is not 1 KiB aligned",
                       awaddr);
            if (arvalid && arready && arlen == 8'd15 && araddr[9:0] != 10'd0)
                $fatal(1, "axi_ram_bfm: 16-beat AR at %h is not 1 KiB aligned",
                       araddr);
        end
    end
`endif

endmodule

`default_nettype wire
