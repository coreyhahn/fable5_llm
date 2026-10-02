// seq_unit_ipi: plain-Verilog wrapper for seq_unit (IPI module references
// cannot have a SystemVerilog top file). Single clock domain: the AXI-Lite
// slave (host control), the AXI-Lite master (drives the other blocks' CSRs),
// the AXI4 read-only master (program/data fetch from DDR) and the rung-3
// AXI4 32-bit burst master m_axib (mover data path, into burst_smc) all run
// on aclk.  ZERO new CDC — every m_axib endpoint is already on axi_aclk.

`timescale 1ns/1ps

module seq_unit_ipi (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axil:m_axil:m_axi:m_axib, ASSOCIATED_RESET aresetn" *)
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

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axil AWADDR" *)
    (* X_INTERFACE_PARAMETER = "PROTOCOL AXI4LITE, DATA_WIDTH 32, ADDR_WIDTH 32" *)
    output wire [31:0]  m_axil_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axil AWVALID" *)
    output wire         m_axil_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axil AWREADY" *)
    input  wire         m_axil_awready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axil WDATA" *)
    output wire [31:0]  m_axil_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axil WSTRB" *)
    output wire [3:0]   m_axil_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axil WVALID" *)
    output wire         m_axil_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axil WREADY" *)
    input  wire         m_axil_wready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axil BRESP" *)
    input  wire [1:0]   m_axil_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axil BVALID" *)
    input  wire         m_axil_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axil BREADY" *)
    output wire         m_axil_bready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axil ARADDR" *)
    output wire [31:0]  m_axil_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axil ARVALID" *)
    output wire         m_axil_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axil ARREADY" *)
    input  wire         m_axil_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axil RDATA" *)
    input  wire [31:0]  m_axil_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axil RRESP" *)
    input  wire [1:0]   m_axil_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axil RVALID" *)
    input  wire         m_axil_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axil RREADY" *)
    output wire         m_axil_rready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARADDR" *)
    (* X_INTERFACE_PARAMETER = "PROTOCOL AXI4, READ_WRITE_MODE READ_ONLY, DATA_WIDTH 128, ADDR_WIDTH 34, NUM_READ_OUTSTANDING 4" *)
    output wire [33:0]  m_axi_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARLEN" *)
    output wire [7:0]   m_axi_arlen,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARSIZE" *)
    output wire [2:0]   m_axi_arsize,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARBURST" *)
    output wire [1:0]   m_axi_arburst,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARVALID" *)
    output wire         m_axi_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARREADY" *)
    input  wire         m_axi_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RDATA" *)
    input  wire [127:0] m_axi_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RRESP" *)
    input  wire [1:0]   m_axi_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RLAST" *)
    input  wire         m_axi_rlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RVALID" *)
    input  wire         m_axi_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RREADY" *)
    output wire         m_axi_rready,

    // ---- rung 3: 32-bit AXI4 burst master, the mover data path (S3) ----
    // Drives burst_smc (1 SI x 5 MI, NUM_CLKS 1, aclk) -> mvchan_0..3
    // s_axib + layer_0 s_axib.  INCR only, <= 256 beats, never crossing a
    // 4 KiB boundary; single ID (0), so all responses are in order.
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib AWID" *)
    (* X_INTERFACE_PARAMETER = "PROTOCOL AXI4, READ_WRITE_MODE READ_WRITE, DATA_WIDTH 32, ADDR_WIDTH 32, ID_WIDTH 1, MAX_BURST_LENGTH 256, NUM_READ_OUTSTANDING 4, NUM_WRITE_OUTSTANDING 8, SUPPORTS_NARROW_BURST 0" *)
    output wire         m_axib_awid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib AWADDR" *)
    output wire [31:0]  m_axib_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib AWLEN" *)
    output wire [7:0]   m_axib_awlen,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib AWSIZE" *)
    output wire [2:0]   m_axib_awsize,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib AWBURST" *)
    output wire [1:0]   m_axib_awburst,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib AWVALID" *)
    output wire         m_axib_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib AWREADY" *)
    input  wire         m_axib_awready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib WDATA" *)
    output wire [31:0]  m_axib_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib WSTRB" *)
    output wire [3:0]   m_axib_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib WLAST" *)
    output wire         m_axib_wlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib WVALID" *)
    output wire         m_axib_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib WREADY" *)
    input  wire         m_axib_wready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib BID" *)
    input  wire         m_axib_bid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib BRESP" *)
    input  wire [1:0]   m_axib_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib BVALID" *)
    input  wire         m_axib_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib BREADY" *)
    output wire         m_axib_bready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib ARID" *)
    output wire         m_axib_arid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib ARADDR" *)
    output wire [31:0]  m_axib_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib ARLEN" *)
    output wire [7:0]   m_axib_arlen,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib ARSIZE" *)
    output wire [2:0]   m_axib_arsize,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib ARBURST" *)
    output wire [1:0]   m_axib_arburst,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib ARVALID" *)
    output wire         m_axib_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib ARREADY" *)
    input  wire         m_axib_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib RID" *)
    input  wire         m_axib_rid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib RDATA" *)
    input  wire [31:0]  m_axib_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib RRESP" *)
    input  wire [1:0]   m_axib_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib RLAST" *)
    input  wire         m_axib_rlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib RVALID" *)
    input  wire         m_axib_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axib RREADY" *)
    output wire         m_axib_rready,

    // optional XRF sideband from layer_chan (tied off in the BD for this build)
    input  wire         xrf_sb_we,
    input  wire [2:0]   xrf_sb_idx,
    input  wire [17:0]  xrf_sb_data,

    // BM1 (spec 2026-09-24 §1.1, D1a): matvec_chan c's engine-busy bit, on
    // aclk, wired from mvchan_<c>/mv_busy_bm by synth/scripts/create_project.tcl.
    // Four SCALAR pins (a module-reference cell's bus pin would need an
    // xlconcat in the BD); plain signals, no X_INTERFACE.
    input  wire         mv_busy_bm0,
    input  wire         mv_busy_bm1,
    input  wire         mv_busy_bm2,
    input  wire         mv_busy_bm3,
    output wire xpush0_valid, output wire [11:0] xpush0_idx, output wire [31:0] xpush0_data, input wire xpush0_room, input wire xpush0_busy, output wire xpush1_valid, output wire [11:0] xpush1_idx, output wire [31:0] xpush1_data, input wire xpush1_room, input wire xpush1_busy, output wire xpush2_valid, output wire [11:0] xpush2_idx, output wire [31:0] xpush2_data, input wire xpush2_room, input wire xpush2_busy, output wire xpush3_valid, output wire [11:0] xpush3_idx, output wire [31:0] xpush3_data, input wire xpush3_room, input wire xpush3_busy,  // R3-8 (B17.3): the x-push bus to mvchan_<c>, per-channel scalar/bus pins wired by synth/scripts/create_project.tcl (aclk; no X_INTERFACE)
    // status (plain signals — no X_INTERFACE attributes)
    output wire         seq_busy,
    output wire         seq_halted,
    output wire         seq_err
);

    seq_unit u_seq (
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
        .m_axil_awaddr(m_axil_awaddr), .m_axil_awvalid(m_axil_awvalid),
        .m_axil_awready(m_axil_awready),
        .m_axil_wdata(m_axil_wdata), .m_axil_wstrb(m_axil_wstrb),
        .m_axil_wvalid(m_axil_wvalid), .m_axil_wready(m_axil_wready),
        .m_axil_bresp(m_axil_bresp), .m_axil_bvalid(m_axil_bvalid),
        .m_axil_bready(m_axil_bready),
        .m_axil_araddr(m_axil_araddr), .m_axil_arvalid(m_axil_arvalid),
        .m_axil_arready(m_axil_arready),
        .m_axil_rdata(m_axil_rdata), .m_axil_rresp(m_axil_rresp),
        .m_axil_rvalid(m_axil_rvalid), .m_axil_rready(m_axil_rready),
        .m_axi_araddr(m_axi_araddr), .m_axi_arlen(m_axi_arlen), .m_axi_arsize(m_axi_arsize),
        .m_axi_arburst(m_axi_arburst), .m_axi_arvalid(m_axi_arvalid), .m_axi_arready(m_axi_arready),
        .m_axi_rdata(m_axi_rdata), .m_axi_rresp(m_axi_rresp), .m_axi_rlast(m_axi_rlast),
        .m_axi_rvalid(m_axi_rvalid), .m_axi_rready(m_axi_rready),
        .m_axib_awid(m_axib_awid), .m_axib_awaddr(m_axib_awaddr),
        .m_axib_awlen(m_axib_awlen), .m_axib_awsize(m_axib_awsize),
        .m_axib_awburst(m_axib_awburst), .m_axib_awvalid(m_axib_awvalid),
        .m_axib_awready(m_axib_awready),
        .m_axib_wdata(m_axib_wdata), .m_axib_wstrb(m_axib_wstrb),
        .m_axib_wlast(m_axib_wlast), .m_axib_wvalid(m_axib_wvalid),
        .m_axib_wready(m_axib_wready),
        .m_axib_bid(m_axib_bid), .m_axib_bresp(m_axib_bresp),
        .m_axib_bvalid(m_axib_bvalid), .m_axib_bready(m_axib_bready),
        .m_axib_arid(m_axib_arid), .m_axib_araddr(m_axib_araddr),
        .m_axib_arlen(m_axib_arlen), .m_axib_arsize(m_axib_arsize),
        .m_axib_arburst(m_axib_arburst), .m_axib_arvalid(m_axib_arvalid),
        .m_axib_arready(m_axib_arready),
        .m_axib_rid(m_axib_rid), .m_axib_rdata(m_axib_rdata),
        .m_axib_rresp(m_axib_rresp), .m_axib_rlast(m_axib_rlast),
        .m_axib_rvalid(m_axib_rvalid), .m_axib_rready(m_axib_rready),
        .xrf_sb_we(xrf_sb_we), .xrf_sb_idx(xrf_sb_idx), .xrf_sb_data(xrf_sb_data),
        .mv_busy_bm({mv_busy_bm3, mv_busy_bm2, mv_busy_bm1, mv_busy_bm0}), .xpush_valid({xpush3_valid, xpush2_valid, xpush1_valid, xpush0_valid}), .xpush_idx({xpush3_idx, xpush2_idx, xpush1_idx, xpush0_idx}), .xpush_data({xpush3_data, xpush2_data, xpush1_data, xpush0_data}), .xpush_room({xpush3_room, xpush2_room, xpush1_room, xpush0_room}), .xpush_busy({xpush3_busy, xpush2_busy, xpush1_busy, xpush0_busy}),  // R3-8
        .seq_busy(seq_busy), .seq_halted(seq_halted), .seq_err(seq_err)
    );

endmodule
