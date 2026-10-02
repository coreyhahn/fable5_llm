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
    // 18-bit address (one 256 KiB segment = the whole 65536-word scratch,
    // G3.1; it was 17-bit / 128 KiB / 32768 words at R-b),
    // ID width 1, SAME aclk as s_axil (zero new CDC).  No LOCK/CACHE/
    // PROT/QOS/REGION/USER: SmartConnect ties them off.
    // NUM_{READ,WRITE}_OUTSTANDING 4 keeps SmartConnect from serializing
    // bursts on this MI (agent-A request).  It is a fabric sizing hint,
    // not a slave capability claim: the shim itself runs ONE burst per
    // direction and simply holds AWREADY/ARREADY low for the next one,
    // which is legal AXI backpressure and cannot deadlock (single ID,
    // in-order responses).
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib AWID" *)
    (* X_INTERFACE_PARAMETER = "PROTOCOL AXI4, DATA_WIDTH 32, ADDR_WIDTH 18, ID_WIDTH 1, READ_WRITE_MODE READ_WRITE, HAS_BURST 1, HAS_LOCK 0, HAS_PROT 0, HAS_CACHE 0, HAS_QOS 0, HAS_REGION 0, HAS_WSTRB 1, HAS_BRESP 1, HAS_RRESP 1, SUPPORTS_NARROW_BURST 0, MAX_BURST_LENGTH 256, NUM_READ_OUTSTANDING 4, NUM_WRITE_OUTSTANDING 4" *)
    input  wire [0:0]   s_axib_awid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axib AWADDR" *)
    input  wire [17:0]  s_axib_awaddr,
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
    input  wire [17:0]  s_axib_araddr,
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
    input  wire         s_axib_rready,

    // ---- S2 (spec 2026-09-04 state-spill §4): the state-DMA master.
    // AXI4, 512-bit data, 34-bit address, ID width 1, on the SAME aclk.  It
    // is the THIRD SI of the central axi_smc, beside xdma_0/M_AXI and
    // seq_0/m_axi, and it carries the same 16 GiB view of the four DDR4
    // channels (synth/scripts/create_project.tcl pins it there).
    // AWSIZE/ARSIZE (64 B beats), AWBURST/ARBURST (INCR) and AWID/ARID are
    // TIED CONSTANT below: state_dma issues nothing else, so the core has
    // no ports for them and the constants cannot drift out of step with the
    // engine.  Bursts are at most 16 beats (1 KiB) and every block base is
    // 64 KiB aligned, so no burst crosses a 4 KiB boundary.
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis AWID" *)
    (* X_INTERFACE_PARAMETER = "PROTOCOL AXI4, READ_WRITE_MODE READ_WRITE, DATA_WIDTH 512, ADDR_WIDTH 34, ID_WIDTH 1, MAX_BURST_LENGTH 16, SUPPORTS_NARROW_BURST 0, HAS_LOCK 0, HAS_PROT 0, HAS_CACHE 0, HAS_QOS 0, HAS_REGION 0, HAS_WSTRB 1, HAS_BRESP 1, HAS_RRESP 1, NUM_READ_OUTSTANDING 8, NUM_WRITE_OUTSTANDING 8" *)
    output wire [0:0]   m_axis_awid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis AWADDR" *)
    output wire [33:0]  m_axis_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis AWLEN" *)
    output wire [7:0]   m_axis_awlen,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis AWSIZE" *)
    output wire [2:0]   m_axis_awsize,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis AWBURST" *)
    output wire [1:0]   m_axis_awburst,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis AWVALID" *)
    output wire         m_axis_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis AWREADY" *)
    input  wire         m_axis_awready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis WDATA" *)
    output wire [511:0] m_axis_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis WSTRB" *)
    output wire [63:0]  m_axis_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis WLAST" *)
    output wire         m_axis_wlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis WVALID" *)
    output wire         m_axis_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis WREADY" *)
    input  wire         m_axis_wready,
    // BID/RID are unread: the master issues a single ID, so responses are
    // in order by construction (the same discipline seq_movers' m_axib uses).
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis BID" *)
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire [0:0]   m_axis_bid,
    /* verilator lint_on UNUSEDSIGNAL */
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis BRESP" *)
    input  wire [1:0]   m_axis_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis BVALID" *)
    input  wire         m_axis_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis BREADY" *)
    output wire         m_axis_bready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis ARID" *)
    output wire [0:0]   m_axis_arid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis ARADDR" *)
    output wire [33:0]  m_axis_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis ARLEN" *)
    output wire [7:0]   m_axis_arlen,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis ARSIZE" *)
    output wire [2:0]   m_axis_arsize,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis ARBURST" *)
    output wire [1:0]   m_axis_arburst,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis ARVALID" *)
    output wire         m_axis_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis ARREADY" *)
    input  wire         m_axis_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis RID" *)
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire [0:0]   m_axis_rid,
    /* verilator lint_on UNUSEDSIGNAL */
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis RDATA" *)
    input  wire [511:0] m_axis_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis RRESP" *)
    input  wire [1:0]   m_axis_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis RLAST" *)
    input  wire         m_axis_rlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis RVALID" *)
    input  wire         m_axis_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axis RREADY" *)
    output wire         m_axis_rready
);

    // the constant ties: 64 B beats, INCR, single ID 0
    assign m_axis_awid    = 1'b0;
    assign m_axis_awsize  = 3'b110;
    assign m_axis_awburst = 2'b01;
    assign m_axis_arid    = 1'b0;
    assign m_axis_arsize  = 3'b110;
    assign m_axis_arburst = 2'b01;

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
        .s_axib_rvalid(s_axib_rvalid), .s_axib_rready(s_axib_rready),
        .m_axis_awaddr(m_axis_awaddr), .m_axis_awlen(m_axis_awlen),
        .m_axis_awvalid(m_axis_awvalid), .m_axis_awready(m_axis_awready),
        .m_axis_wdata(m_axis_wdata), .m_axis_wstrb(m_axis_wstrb),
        .m_axis_wlast(m_axis_wlast), .m_axis_wvalid(m_axis_wvalid),
        .m_axis_wready(m_axis_wready),
        .m_axis_bresp(m_axis_bresp), .m_axis_bvalid(m_axis_bvalid),
        .m_axis_bready(m_axis_bready),
        .m_axis_araddr(m_axis_araddr), .m_axis_arlen(m_axis_arlen),
        .m_axis_arvalid(m_axis_arvalid), .m_axis_arready(m_axis_arready),
        .m_axis_rdata(m_axis_rdata), .m_axis_rresp(m_axis_rresp),
        .m_axis_rlast(m_axis_rlast), .m_axis_rvalid(m_axis_rvalid),
        .m_axis_rready(m_axis_rready)
    );

endmodule
