// tb_csr: self-checking testbench for csr_block.
//
// Checks:
//  1. Register values: MAGIC, VERSION, CALIB, SCRATCH (with byte strobes,
//     against a software model), bad-address decode, UPTIME monotonicity.
//  2. Bounded-response property: every accepted AW+W produces B, and every
//     accepted AR produces R, within BOUND cycles, under randomized request
//     skew and randomized BREADY/RREADY backpressure (the "host can never
//     hang" property).
//  3. calib_in propagates through the 2FF synchronizer.
//
// TB discipline (Verilator-safe, race-free): ALL testbench drives and samples
// happen at negedge aclk. DUT state only changes at posedge, so signals are
// stable at every negedge and the DUT never races TB assignments.
//
// PASS prints "TB_CSR PASS"; any failure exits nonzero via $fatal.

`timescale 1ns/1ps

module tb_csr;

    localparam logic [31:0] TB_VERSION = 32'hABCD1234;
    localparam int BOUND = 16;          // max cycles from request to response
    localparam int NOPS  = 20000;

    logic aclk = 0;
    /* verilator lint_off BLKSEQ */
    always #2 aclk = ~aclk;             // 250 MHz
    /* verilator lint_on BLKSEQ */

    logic        aresetn = 0;
    logic [3:0]  calib_in = '0;

    logic [11:0] awaddr;  logic awvalid; logic awready;
    logic [31:0] wdata;   logic [3:0] wstrb; logic wvalid; logic wready;
    logic [1:0]  bresp;   logic bvalid; logic bready;
    logic [11:0] araddr;  logic arvalid; logic arready;
    logic [31:0] rdata;   logic [1:0] rresp; logic rvalid; logic rready;

    csr_block #(.VERSION(TB_VERSION)) dut (
        .aclk, .aresetn, .calib_in,
        .s_axil_awaddr(awaddr), .s_axil_awvalid(awvalid), .s_axil_awready(awready),
        .s_axil_wdata(wdata), .s_axil_wstrb(wstrb), .s_axil_wvalid(wvalid), .s_axil_wready(wready),
        .s_axil_bresp(bresp), .s_axil_bvalid(bvalid), .s_axil_bready(bready),
        .s_axil_araddr(araddr), .s_axil_arvalid(arvalid), .s_axil_arready(arready),
        .s_axil_rdata(rdata), .s_axil_rresp(rresp), .s_axil_rvalid(rvalid), .s_axil_rready(rready)
    );

    int errors = 0;
    logic [31:0] scratch_model = 32'h0;

    task automatic check(input bit cond, input string msg);
        if (!cond) begin
            errors++;
            $display("[%0t] FAIL: %s", $time, msg);
        end
    endtask

    // AXI-Lite write; randomized AW/W skew and B backpressure. Negedge-only.
    task automatic axil_write(input logic [11:0] addr, input logic [31:0] data,
                              input logic [3:0] strb);
        int cycles = 0;
        int aw_delay = $urandom_range(0, 3);
        int w_delay  = $urandom_range(0, 3);
        fork
            begin
                repeat (aw_delay) @(negedge aclk);
                awaddr = addr; awvalid = 1;
                // awready==1 at a negedge => transfer at the next posedge
                while (!awready) @(negedge aclk);
                @(negedge aclk);
                awvalid = 0;
            end
            begin
                repeat (w_delay) @(negedge aclk);
                wdata = data; wstrb = strb; wvalid = 1;
                while (!wready) @(negedge aclk);
                @(negedge aclk);
                wvalid = 0;
            end
        join
        // wait for B (bounded), random backpressure before accepting
        while (!bvalid) begin
            cycles++;
            check(cycles < BOUND, $sformatf("B response not within %0d cycles (addr %h)", BOUND, addr));
            if (cycles >= BOUND) return;
            @(negedge aclk);
        end
        check(bresp == 2'b00, "BRESP != OKAY");
        repeat ($urandom_range(0, 2)) @(negedge aclk);
        bready = 1;
        @(negedge aclk);                 // B handshake at the posedge in between
        bready = 0;
        // update model
        if (addr[11:2] == 10'h002) begin
            if (strb[0]) scratch_model[7:0]   = data[7:0];
            if (strb[1]) scratch_model[15:8]  = data[15:8];
            if (strb[2]) scratch_model[23:16] = data[23:16];
            if (strb[3]) scratch_model[31:24] = data[31:24];
        end
    endtask

    // AXI-Lite read with R backpressure; returns data. Negedge-only.
    task automatic axil_read(input logic [11:0] addr, output logic [31:0] data);
        int cycles = 0;
        @(negedge aclk);
        araddr = addr; arvalid = 1;
        while (!arready) @(negedge aclk);
        @(negedge aclk);                 // AR accepted at the posedge in between
        arvalid = 0;
        while (!rvalid) begin
            cycles++;
            check(cycles < BOUND, $sformatf("R response not within %0d cycles (addr %h)", BOUND, addr));
            if (cycles >= BOUND) return;
            @(negedge aclk);
        end
        data = rdata;                    // stable while rvalid held
        check(rresp == 2'b00, "RRESP != OKAY");
        repeat ($urandom_range(0, 2)) @(negedge aclk);
        rready = 1;
        @(negedge aclk);                 // R handshake at the posedge in between
        rready = 0;
    endtask

    logic [31:0] rd, rd2;
    initial begin
        awvalid = 0; wvalid = 0; bready = 0; arvalid = 0; rready = 0;
        awaddr = '0; wdata = '0; wstrb = '0; araddr = '0;
        repeat (10) @(negedge aclk);
        aresetn = 1;
        repeat (5) @(negedge aclk);

        // --- fixed registers
        axil_read(12'h000, rd); check(rd == 32'hFAB1E001, $sformatf("MAGIC=%h", rd));
        axil_read(12'h004, rd); check(rd == TB_VERSION,   $sformatf("VERSION=%h", rd));
        axil_read(12'h00C, rd); check(rd == 32'h0,        $sformatf("CALIB(init)=%h", rd));
        axil_read(12'hFFC, rd); check(rd == 32'hDEADC0DE, $sformatf("BADADDR=%h", rd));

        // --- uptime monotonic
        axil_read(12'h010, rd);
        axil_read(12'h010, rd2);
        check(rd2 > rd, $sformatf("UPTIME not monotonic: %h -> %h", rd, rd2));

        // --- calib sync
        calib_in = 4'b1010;
        repeat (5) @(negedge aclk);
        axil_read(12'h00C, rd); check(rd == 32'h0000000A, $sformatf("CALIB=%h exp A", rd));
        calib_in = 4'b1111;
        repeat (5) @(negedge aclk);
        axil_read(12'h00C, rd); check(rd == 32'h0000000F, $sformatf("CALIB=%h exp F", rd));

        // --- scratch with strobes
        axil_write(12'h008, 32'h11223344, 4'b1111);
        axil_read (12'h008, rd); check(rd == 32'h11223344, $sformatf("SCRATCH=%h", rd));
        axil_write(12'h008, 32'hAABBCCDD, 4'b0101);
        axil_read (12'h008, rd); check(rd == scratch_model, $sformatf("SCRATCH strobed=%h exp %h", rd, scratch_model));

        // --- randomized soak: random reads/writes everywhere, model-checked
        for (int i = 0; i < NOPS; i++) begin
            logic [11:0] a;
            a = 12'($urandom_range(0, 9) * 4);     // mostly in-map, some beyond
            if ($urandom_range(0, 1) != 32'd0) begin
                axil_write(a, $urandom(), 4'($urandom_range(0, 15)));
            end else begin
                axil_read(a, rd);
                case (a[11:2])
                    10'h000: check(rd == 32'hFAB1E001, "soak MAGIC");
                    10'h001: check(rd == TB_VERSION, "soak VERSION");
                    10'h002: check(rd == scratch_model, $sformatf("soak SCRATCH=%h exp %h", rd, scratch_model));
                    10'h003: check(rd == 32'h0000000F, "soak CALIB");
                    default: ; // uptime / bad-addr: value not model-checked
                endcase
            end
        end

        if (errors == 0) begin
            $display("TB_CSR PASS: all checks passed (%0d soak ops)", NOPS);
            $finish;
        end else begin
            $fatal(1, "TB_CSR FAIL: %0d errors", errors);
        end
    end

    // global watchdog
    initial begin
        #20ms;
        $fatal(1, "TB_CSR FAIL: global timeout");
    end

endmodule
