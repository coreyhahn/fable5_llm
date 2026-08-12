// csr_block: AXI4-Lite status/scratch register file for BCU-1525 bring-up.
//
// Safety-critical property: this slave ALWAYS completes every transaction in
// bounded time (no wait-state dependencies on anything outside this module),
// so a host MMIO read through the XDMA AXI-Lite BAR can never stall a PCIe
// completion. Single-outstanding, no bursts (AXI-Lite).
//
// Register map (byte addresses, 32-bit registers):
//   0x00  MAGIC      RO  0xFAB1E001
//   0x04  VERSION    RO  VERSION parameter (git short-hash, set at build)
//   0x08  SCRATCH    RW  read/write scratch
//   0x0C  CALIB      RO  {28'd0, ddr4 init_calib_complete[3:0]} (2FF sync)
//   0x10  UPTIME_LO  RO  free-running axi_aclk cycle counter [31:0]
//   0x14  UPTIME_HI  RO  cycle counter [63:32]
//   others           RO  0xDEADC0DE

`timescale 1ns/1ps
`default_nettype none

module csr_block #(
    parameter logic [31:0] VERSION = 32'h0
) (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axil, ASSOCIATED_RESET aresetn" *)
    input  wire         aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire         aresetn,

    // DDR4 calibration status, async inputs (one per channel)
    input  wire [3:0]   calib_in,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil AWADDR" *)
    (* X_INTERFACE_PARAMETER = "PROTOCOL AXI4LITE, DATA_WIDTH 32, ADDR_WIDTH 12, CLK_DOMAIN aclk" *)
    input  wire [11:0]  s_axil_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil AWVALID" *)
    input  wire         s_axil_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil AWREADY" *)
    output logic        s_axil_awready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil WDATA" *)
    input  wire [31:0]  s_axil_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil WSTRB" *)
    input  wire [3:0]   s_axil_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil WVALID" *)
    input  wire         s_axil_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil WREADY" *)
    output logic        s_axil_wready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil BRESP" *)
    output logic [1:0]  s_axil_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil BVALID" *)
    output logic        s_axil_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil BREADY" *)
    input  wire         s_axil_bready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil ARADDR" *)
    input  wire [11:0]  s_axil_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil ARVALID" *)
    input  wire         s_axil_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil ARREADY" *)
    output logic        s_axil_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil RDATA" *)
    output logic [31:0] s_axil_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil RRESP" *)
    output logic [1:0]  s_axil_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil RVALID" *)
    output logic        s_axil_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil RREADY" *)
    input  wire         s_axil_rready
);

    localparam logic [31:0] MAGIC   = 32'hFAB1_E001;
    localparam logic [31:0] BADADDR = 32'hDEAD_C0DE;

    // 2FF synchronizer for async calibration bits
    (* ASYNC_REG = "TRUE" *) logic [3:0] calib_meta, calib_sync;
    always_ff @(posedge aclk) begin
        calib_meta <= calib_in;
        calib_sync <= calib_meta;
    end

    logic [63:0] uptime;
    logic [31:0] scratch;

    // ---- write channel: latch AW and W independently, respond when both seen
    logic        aw_got, w_got;
    logic [9:0]  awaddr_q;          // word address; byte LSBs are don't-care
    logic [31:0] wdata_q;
    logic [3:0]  wstrb_q;

    // 32-bit registers: address bits [1:0] intentionally ignored
    /* verilator lint_off UNUSEDSIGNAL */
    wire [1:0] unused_addr_lsbs = s_axil_awaddr[1:0] | s_axil_araddr[1:0];
    /* verilator lint_on UNUSEDSIGNAL */

    assign s_axil_awready = !aw_got && !s_axil_bvalid;
    assign s_axil_wready  = !w_got  && !s_axil_bvalid;

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            aw_got        <= 1'b0;
            w_got         <= 1'b0;
            s_axil_bvalid <= 1'b0;
            s_axil_bresp  <= 2'b00;
            scratch       <= 32'h0;
            uptime        <= 64'h0;
        end else begin
            uptime <= uptime + 64'd1;

            if (s_axil_awvalid && s_axil_awready) begin
                aw_got   <= 1'b1;
                awaddr_q <= s_axil_awaddr[11:2];
            end
            if (s_axil_wvalid && s_axil_wready) begin
                w_got   <= 1'b1;
                wdata_q <= s_axil_wdata;
                wstrb_q <= s_axil_wstrb;
            end

            if (aw_got && w_got && !s_axil_bvalid) begin
                // commit the write
                if (awaddr_q == 10'h002) begin  // 0x08 SCRATCH
                    if (wstrb_q[0]) scratch[7:0]   <= wdata_q[7:0];
                    if (wstrb_q[1]) scratch[15:8]  <= wdata_q[15:8];
                    if (wstrb_q[2]) scratch[23:16] <= wdata_q[23:16];
                    if (wstrb_q[3]) scratch[31:24] <= wdata_q[31:24];
                end
                s_axil_bvalid <= 1'b1;
                s_axil_bresp  <= 2'b00;  // OKAY even for RO addrs (writes ignored)
                aw_got        <= 1'b0;
                w_got         <= 1'b0;
            end

            if (s_axil_bvalid && s_axil_bready)
                s_axil_bvalid <= 1'b0;
        end
    end

    // ---- read channel: single outstanding, data the cycle after AR accept
    assign s_axil_arready = !s_axil_rvalid;

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            s_axil_rvalid <= 1'b0;
            s_axil_rresp  <= 2'b00;
            s_axil_rdata  <= 32'h0;
        end else begin
            if (s_axil_arvalid && s_axil_arready) begin
                s_axil_rvalid <= 1'b1;
                s_axil_rresp  <= 2'b00;
                unique case (s_axil_araddr[11:2])
                    10'h000: s_axil_rdata <= MAGIC;
                    10'h001: s_axil_rdata <= VERSION;
                    10'h002: s_axil_rdata <= scratch;
                    10'h003: s_axil_rdata <= {28'd0, calib_sync};
                    10'h004: s_axil_rdata <= uptime[31:0];
                    10'h005: s_axil_rdata <= uptime[63:32];
                    default: s_axil_rdata <= BADADDR;
                endcase
            end else if (s_axil_rvalid && s_axil_rready) begin
                s_axil_rvalid <= 1'b0;
            end
        end
    end

endmodule

`default_nettype wire
