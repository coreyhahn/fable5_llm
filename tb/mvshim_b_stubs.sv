// mvshim_b_stubs: stand-ins for matvec_engine / ddr_rd_streamer used ONLY by
// tb_mvshim_b (obj_dir_tb_mvshim_b).  They let the S5 burst shim be tested
// against the REAL rtl/matvec_chan.sv without dragging in the W4 datapath.
//
// The engine stub gives the TB two observables it otherwise could not reach
// without backdoor hierarchical writes:
//
//   * RES fill.  Every doorbell (start pulse) sweeps all 4096 rows of the
//     result BRAM writing mvshim_b_pkg::fillpat(row, gen), where gen is the
//     doorbell count.  The TB knows the whole RES image exactly, for every
//     row, so burst readback can be checked at any 12-bit row base (S12).
//   * X echo.  Outside a sweep, every activation write the engine receives
//     (x_we/x_waddr/x_wdata — i.e. every word that made it through the
//     xpm_fifo_async into the ui_clk domain) is echoed into RES row
//     {4'b0, x_waddr}.  That makes "did this XWIN word reach x_mem, at the
//     right index, with the right data" directly observable through the
//     normal result read paths — and identical for AXI-Lite pushes and for
//     s_axib burst-window pushes.
//
// The streamer stub is inert: this TB never runs a real weight stream.

`timescale 1ns/1ps
`default_nettype none

package mvshim_b_pkg;
    // RES fill pattern.  Duplicated nowhere: the TB imports this package.
    function automatic logic [31:0] fillpat(input logic [31:0] row,
                                            input logic [31:0] gen);
        fillpat = (row * 32'h0001_0001) ^ (gen * 32'h5DEE_CE21) ^ 32'hC0DE_1234;
    endfunction
endpackage

// ---------------------------------------------------------------------
module matvec_engine #(
    /* verilator lint_off UNUSEDPARAM */
    parameter int MAX_NG = 96,
    /* verilator lint_on UNUSEDPARAM */
    parameter int ROW_W  = 16
) (
    input  wire                clk,
    input  wire                rstn,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire [6:0]          cfg_ng,
    input  wire [5:0]          cfg_sh,
    input  wire [ROW_W-1:0]    cfg_nrows,
    input  wire                cfg_xbank,   // SR12 (B17.2): the real engine's
    input  wire                cfg_rbank,   // ports, unused by this stub
    /* verilator lint_on UNUSEDSIGNAL */
    input  wire                start,
    output logic               busy,
    output logic               done,

    input  wire                x_we,
    input  wire [11:0]         x_waddr,
    input  wire [31:0]         x_wdata,

    /* verilator lint_off UNUSEDSIGNAL */
    input  wire                s_valid,
    /* verilator lint_on UNUSEDSIGNAL */
    output logic               s_ready,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire [511:0]        s_data,
    /* verilator lint_on UNUSEDSIGNAL */

    output logic               m_valid,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire                m_ready,
    /* verilator lint_on UNUSEDSIGNAL */
    output logic [31:0]        m_y32,
    output logic [ROW_W-1:0]   m_row
);

    logic [31:0] gen_q;
    logic [12:0] sweep;
    logic        sweeping;

    assign s_ready = 1'b1;

    always_ff @(posedge clk) begin
        if (!rstn) begin
            gen_q <= '0; sweep <= '0; sweeping <= 1'b0;
            busy  <= 1'b0; done <= 1'b0;
            m_valid <= 1'b0; m_y32 <= '0; m_row <= '0;
        end else begin
            m_valid <= 1'b0;
            if (start) begin
                gen_q    <= gen_q + 32'd1;
                sweep    <= '0;
                sweeping <= 1'b1;
                busy     <= 1'b1;
                done     <= 1'b0;
            end else if (sweeping) begin
                m_valid <= 1'b1;
                m_row   <= {4'b0, sweep[11:0]};
                m_y32   <= mvshim_b_pkg::fillpat({20'b0, sweep[11:0]}, gen_q);
                sweep   <= sweep + 13'd1;
                if (sweep == 13'd4095) begin
                    sweeping <= 1'b0; busy <= 1'b0; done <= 1'b1;
                end
            end else if (x_we) begin
                m_valid <= 1'b1;
                m_row   <= {4'b0, x_waddr};
                m_y32   <= x_wdata;
            end
`ifndef SYNTHESIS
            if (sweeping && x_we)
                $fatal(1, "mvshim_b stub engine: x write during the RES fill sweep");
`endif
        end
    end

endmodule

// ---------------------------------------------------------------------
module ddr_rd_streamer #(
    parameter int ADDR_W = 34
) (
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire               clk,
    input  wire               rstn,
    input  wire [ADDR_W-1:0]  cfg_base,
    input  wire [31:0]        cfg_beats,
    input  wire               start,
    /* verilator lint_on UNUSEDSIGNAL */
    output logic              busy,
    output logic              done,
    output logic [47:0]       perf_cycles,
    output logic [31:0]       perf_beats,

    output logic [ADDR_W-1:0] m_araddr,
    output logic [7:0]        m_arlen,
    output logic [2:0]        m_arsize,
    output logic [1:0]        m_arburst,
    output logic              m_arvalid,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire               m_arready,
    input  wire [511:0]       m_rdata,
    input  wire [1:0]         m_rresp,
    input  wire               m_rlast,
    input  wire               m_rvalid,
    /* verilator lint_on UNUSEDSIGNAL */
    output logic              m_rready,
    output logic              err_rresp,

    output logic              s_valid,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire               s_ready,
    /* verilator lint_on UNUSEDSIGNAL */
    output logic [511:0]      s_data
);
    assign busy        = 1'b0;
    assign done        = 1'b0;
    assign perf_cycles = '0;
    assign perf_beats  = '0;
    assign m_araddr    = '0;
    assign m_arlen     = '0;
    assign m_arsize    = 3'b110;
    assign m_arburst   = 2'b01;
    assign m_arvalid   = 1'b0;
    assign m_rready    = 1'b0;
    assign err_rresp   = 1'b0;
    assign s_valid     = 1'b0;
    assign s_data      = '0;
endmodule

`default_nettype wire
