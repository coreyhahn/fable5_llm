// layer_chan_ipi: plain-Verilog wrapper for layer_chan (IPI module
// references cannot have a SystemVerilog top file). ROM paths are
// absolute so synthesis $readmemh resolves regardless of run dir.

`timescale 1ns/1ps

module layer_chan_ipi (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axil:s_axib, ASSOCIATED_RESET aresetn" *)
    input  wire         aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire         aresetn,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil AWADDR" *)
    (* X_INTERFACE_PARAMETER = "PROTOCOL AXI4LITE, DATA_WIDTH 32, ADDR_WIDTH 12" *)
    input  wire [11:0]  s_axil_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil AWVALID" *)
    input  wire         s_axil_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil AWREADY" *)
    output wire         s_axil_awready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil WDATA" *)
    input  wire [31:0]  s_axil_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil WSTRB" *)
    input  wire [3:0]   s_axil_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil WVALID" *)
    input  wire         s_axil_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil WREADY" *)
    output wire         s_axil_wready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil BRESP" *)
    output wire [1:0]   s_axil_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil BVALID" *)
    output wire         s_axil_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil BREADY" *)
    input  wire         s_axil_bready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil ARADDR" *)
    input  wire [11:0]  s_axil_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil ARVALID" *)
    input  wire         s_axil_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil ARREADY" *)
    output wire         s_axil_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil RDATA" *)
    output wire [31:0]  s_axil_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil RRESP" *)
    output wire [1:0]   s_axil_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil RVALID" *)
    output wire         s_axil_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axil RREADY" *)
    input  wire         s_axil_rready,

    // ---- S6 burst window (docs/RUNG3_SPEC.md): AXI4 slave, 32-bit data,
    // 16-bit address (one 64 KiB segment = the whole 16384-word scratch),
    // ID width 1, SAME aclk as s_axil (zero new CDC).  No LOCK/CACHE/
    // PROT/QOS/REGION/USER: SmartConnect ties them off.
    // NUM_{READ,WRITE}_OUTSTANDING 4 keeps SmartConnect from serializing
    // bursts on this MI (agent-A request).  It is a fabric sizing hint,
    // not a slave capability claim: the shim itself runs ONE burst per
    // direction and simply holds AWREADY/ARREADY low for the next one,
    // which is legal AXI backpressure and cannot deadlock (single ID,
    // in-order responses).
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib AWID" *)
    (* X_INTERFACE_PARAMETER = "PROTOCOL AXI4, DATA_WIDTH 32, ADDR_WIDTH 16, ID_WIDTH 1, READ_WRITE_MODE READ_WRITE, HAS_BURST 1, HAS_LOCK 0, HAS_PROT 0, HAS_CACHE 0, HAS_QOS 0, HAS_REGION 0, HAS_WSTRB 1, HAS_BRESP 1, HAS_RRESP 1, SUPPORTS_NARROW_BURST 0, MAX_BURST_LENGTH 256, NUM_READ_OUTSTANDING 4, NUM_WRITE_OUTSTANDING 4" *)
    input  wire [0:0]   s_axib_awid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib AWADDR" *)
    input  wire [15:0]  s_axib_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib AWLEN" *)
    input  wire [7:0]   s_axib_awlen,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib AWSIZE" *)
    input  wire [2:0]   s_axib_awsize,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib AWBURST" *)
    input  wire [1:0]   s_axib_awburst,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib AWVALID" *)
    input  wire         s_axib_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib AWREADY" *)
    output wire         s_axib_awready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib WDATA" *)
    input  wire [31:0]  s_axib_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib WSTRB" *)
    input  wire [3:0]   s_axib_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib WLAST" *)
    input  wire         s_axib_wlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib WVALID" *)
    input  wire         s_axib_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib WREADY" *)
    output wire         s_axib_wready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib BID" *)
    output wire [0:0]   s_axib_bid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib BRESP" *)
    output wire [1:0]   s_axib_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib BVALID" *)
    output wire         s_axib_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib BREADY" *)
    input  wire         s_axib_bready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib ARID" *)
    input  wire [0:0]   s_axib_arid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib ARADDR" *)
    input  wire [15:0]  s_axib_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib ARLEN" *)
    input  wire [7:0]   s_axib_arlen,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib ARSIZE" *)
    input  wire [2:0]   s_axib_arsize,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib ARBURST" *)
    input  wire [1:0]   s_axib_arburst,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib ARVALID" *)
    input  wire         s_axib_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib ARREADY" *)
    output wire         s_axib_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib RID" *)
    output wire [0:0]   s_axib_rid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib RDATA" *)
    output wire [31:0]  s_axib_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib RRESP" *)
    output wire [1:0]   s_axib_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib RLAST" *)
    output wire         s_axib_rlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib RVALID" *)
    output wire         s_axib_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib RREADY" *)
    input  wire         s_axib_rready
);

    layer_chan #(
        .RSQRT_ROM("/home/cah/r2d2/code/fpga/fable5_llm/rtl/roms/rsqrt_rom.hex"),
        .SIGMOID_ROM("/home/cah/r2d2/code/fpga/fable5_llm/rtl/roms/sigmoid_pair_rom.hex"),
        .SOFTPLUS_ROM("/home/cah/r2d2/code/fpga/fable5_llm/rtl/roms/softplus_pair_rom.hex"),
        .EXP2_ROM("/home/cah/r2d2/code/fpga/fable5_llm/rtl/roms/exp2_pair_rom.hex"),
        .RECIP_ROM("/home/cah/r2d2/code/fpga/fable5_llm/rtl/roms/recip_rom.hex")
    ) u_core (
        .aclk(aclk), .aresetn(aresetn),
        .s_axil_awaddr(s_axil_awaddr), .s_axil_awvalid(s_axil_awvalid),
        .s_axil_awready(s_axil_awready),
        .s_axil_wdata(s_axil_wdata), .s_axil_wstrb(s_axil_wstrb),
        .s_axil_wvalid(s_axil_wvalid), .s_axil_wready(s_axil_wready),
        .s_axil_bresp(s_axil_bresp), .s_axil_bvalid(s_axil_bvalid),
        .s_axil_bready(s_axil_bready),
        .s_axil_araddr(s_axil_araddr), .s_axil_arvalid(s_axil_arvalid),
        .s_axil_arready(s_axil_arready),
        .s_axil_rdata(s_axil_rdata), .s_axil_rresp(s_axil_rresp),
        .s_axil_rvalid(s_axil_rvalid), .s_axil_rready(s_axil_rready),
        .s_axib_awid(s_axib_awid), .s_axib_awaddr(s_axib_awaddr),
        .s_axib_awlen(s_axib_awlen), .s_axib_awsize(s_axib_awsize),
        .s_axib_awburst(s_axib_awburst), .s_axib_awvalid(s_axib_awvalid),
        .s_axib_awready(s_axib_awready),
        .s_axib_wdata(s_axib_wdata), .s_axib_wstrb(s_axib_wstrb),
        .s_axib_wlast(s_axib_wlast), .s_axib_wvalid(s_axib_wvalid),
        .s_axib_wready(s_axib_wready),
        .s_axib_bid(s_axib_bid), .s_axib_bresp(s_axib_bresp),
        .s_axib_bvalid(s_axib_bvalid), .s_axib_bready(s_axib_bready),
        .s_axib_arid(s_axib_arid), .s_axib_araddr(s_axib_araddr),
        .s_axib_arlen(s_axib_arlen), .s_axib_arsize(s_axib_arsize),
        .s_axib_arburst(s_axib_arburst), .s_axib_arvalid(s_axib_arvalid),
        .s_axib_arready(s_axib_arready),
        .s_axib_rid(s_axib_rid), .s_axib_rdata(s_axib_rdata),
        .s_axib_rresp(s_axib_rresp), .s_axib_rlast(s_axib_rlast),
        .s_axib_rvalid(s_axib_rvalid), .s_axib_rready(s_axib_rready)
    );

endmodule
