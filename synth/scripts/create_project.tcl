# create_project.tcl — Stage 1 bring-up design for SQRL BCU-1525
#   XDMA PCIe Gen3 x8 (GTY quad 227, per official VCU1525 board preset)
#   + 4x DDR4-2400 UDIMM controllers (Crucial BLS4G4D240FSB-2400 custom part)
#   + csr_block on the XDMA AXI-Lite master BAR (always-responding status regs)
#
# Usage: vivado -mode batch -source create_project.tcl -tclargs <out_dir> <version_hex8>
#   out_dir      : project output directory (isolated per build)
#   version_hex8 : 8-hex-digit build id (git short hash) for the CSR VERSION reg
#
# Address map (XDMA M_AXI, DMA descriptors address this space):
#   0x0_0000_0000 +4G  ddr4_0   0x1_0000_0000 +4G  ddr4_1
#   0x2_0000_0000 +4G  ddr4_2   0x3_0000_0000 +4G  ddr4_3
# AXI-Lite BAR (XDMA M_AXI_LITE / /dev/xdma0_user), 4K per slave:
#   0x0000 csr_0
#   0x1000 mvchan_0  0x2000 mvchan_1  0x3000 mvchan_2  0x4000 mvchan_3
#   0x5000 layer_0
#   0x6000 seq_0
# seq_0 (the sequencer) is not just a slave: it is also a SECOND AXI-Lite
# MASTER on axil_smc (S01_AXI), so it drives the exact same 0x0000..0x6000
# CSR map the host does, and a SECOND AXI4 read master on axi_smc (S01_AXI),
# so it sees the same 16 GiB ddr4_0..3 view that XDMA M_AXI has.
# RUNG 3 adds a THIRD seq_0 master, m_axib (32-bit AXI4 READ_WRITE), on its
# own burst_smc (1 SI x 5 MI, aclk, no clock conversion) with a PRIVATE
# 64 KiB-stride data map that no other master can see:
#   0x1_0000 mvchan_0  0x2_0000 mvchan_1  0x3_0000 mvchan_2  0x4_0000 mvchan_3
#   0x5_0000 layer_0
# per mvchan: 0x0000-0x3FFF RES read window (row r at byte 4r), 0x4000-0x4FFF
# XWIN write window (word w at byte 4w); layer_0: scratch word w at byte 4w.

if {[llength $argv] < 2} { puts "FATAL: need <out_dir> <version_hex8>"; exit 1 }
set OutDir   [lindex $argv 0]
set BuildVer [lindex $argv 1]

set ScriptDir [file dirname [file normalize [info script]]]
set RepoRoot  [file normalize "$ScriptDir/../.."]
set ConstrDir "$RepoRoot/synth/constraints"
set RtlDir    "$RepoRoot/rtl"

if {[string compare [version -short] "2024.2"] != 0} {
    puts "FATAL: this script expects Vivado 2024.2, got [version -short]"; exit 1
}

proc must {script} {
    if {[catch {uplevel 1 $script} err]} {
        puts "FATAL: $err"
        exit 1
    }
}

set_param general.maxThreads 16

must {create_project stage1 $OutDir/proj -part xcvu9p-fsgd2104-2L-e}

# Sources: custom DDR4 part CSV, board XDCs, CSR RTL
must {import_files -norecurse $ConstrDir/BLS4G4D240FSB.csv}
foreach x {BCU1525_DIMM0.xdc BCU1525_DIMM1.xdc BCU1525_DIMM2.xdc BCU1525_DIMM3.xdc fable5_pcie_clk.xdc fable5_cdc.xdc} {
    must {import_files -fileset constrs_1 -norecurse $ConstrDir/$x}
}
# MCP exceptions for layer_chan (impl only — cell names are post-synth)
must {import_files -fileset constrs_1 -norecurse $ConstrDir/layer_mcp.xdc}
must {set_property USED_IN_SYNTHESIS false [get_files layer_mcp.xdc]}
must {add_files -norecurse $RtlDir/csr_block.sv}
must {add_files -norecurse $RtlDir/csr_block_ipi.v}
must {add_files -norecurse $RtlDir/matvec_engine.sv}
must {add_files -norecurse $RtlDir/ddr_rd_streamer.sv}
must {add_files -norecurse $RtlDir/matvec_chan.sv}
must {add_files -norecurse $RtlDir/matvec_chan_ipi.v}
foreach x {fx_pkg.sv fx_rsqrt.sv fx_recip.sv fx_silu.sv vecnorm_unit.sv \
           rope_unit.sv conv4_silu.sv dn_step.sv attn_core.sv gate_unit.sv \
           vec_alu.sv layer_chan.sv} {
    must {add_files -norecurse $RtlDir/$x}
}
must {add_files -norecurse $RtlDir/layer_chan_ipi.v}
# sequencer (stage 6): seq_unit.sv instantiates seq_movers.sv; seq_unit_ipi.v
# is the plain-Verilog IPI module reference
must {add_files -norecurse $RtlDir/seq_movers.sv}
must {add_files -norecurse $RtlDir/seq_unit.sv}
must {add_files -norecurse $RtlDir/seq_unit_ipi.v}
set_property file_type SystemVerilog [get_files csr_block.sv]
set_property XPM_LIBRARIES {XPM_CDC XPM_FIFO XPM_MEMORY} [current_project]

must {create_bd_design "bd"}

# ---------------- PCIe refclk buffer + XDMA ----------------
must {create_bd_cell -type ip -vlnv xilinx.com:ip:util_ds_buf:2.2 refclk_buf}
must {set_property -dict [list CONFIG.C_BUF_TYPE {IBUFDSGTE}] [get_bd_cells refclk_buf]}
must {make_bd_intf_pins_external [get_bd_intf_pins refclk_buf/CLK_IN_D]}
must {set_property name pcie_refclk [get_bd_intf_ports CLK_IN_D_0]}
must {set_property CONFIG.FREQ_HZ 100000000 [get_bd_intf_ports /pcie_refclk]}

must {create_bd_cell -type ip -vlnv xilinx.com:ip:xdma:4.1 xdma_0}
# NB: set_property on BD cells only WARNS for unknown CONFIG params, so every
# config below is re-read and asserted afterwards.
must {set_property -dict [list CONFIG.mode_selection {Advanced}] [get_bd_cells xdma_0]}
must {set_property -dict [list \
    CONFIG.pl_link_cap_max_link_width {X8} \
    CONFIG.pl_link_cap_max_link_speed {8.0_GT/s} \
] [get_bd_cells xdma_0]}
must {set_property -dict [list \
    CONFIG.axi_data_width {256_bit} \
    CONFIG.axisten_freq {250} \
    CONFIG.en_gt_selection {true} \
    CONFIG.select_quad {GTY_Quad_227} \
    CONFIG.axilite_master_en {true} \
    CONFIG.xdma_pcie_64bit_en {true} \
] [get_bd_cells xdma_0]}
foreach {param want} {
    CONFIG.mode_selection Advanced
    CONFIG.pl_link_cap_max_link_width X8
    CONFIG.pl_link_cap_max_link_speed 8.0_GT/s
    CONFIG.axi_data_width 256_bit
    CONFIG.axisten_freq 250
    CONFIG.en_gt_selection true
    CONFIG.select_quad GTY_Quad_227
    CONFIG.axilite_master_en true
} {
    set got [get_property $param [get_bd_cells xdma_0]]
    if {[string compare $got $want] != 0} {
        puts "FATAL: xdma $param = '$got', wanted '$want'"; exit 1
    }
}
if {[llength [get_bd_intf_pins -quiet xdma_0/M_AXI_LITE]] != 1} {
    puts "FATAL: xdma_0/M_AXI_LITE pin missing"; exit 1
}

must {make_bd_intf_pins_external [get_bd_intf_pins xdma_0/pcie_mgt]}
must {set_property name pcie_mgt [get_bd_intf_ports pcie_mgt_0]}
must {make_bd_pins_external [get_bd_pins xdma_0/sys_rst_n]}
must {set_property name pcie_perstn [get_bd_ports sys_rst_n_0]}

must {connect_bd_net [get_bd_pins refclk_buf/IBUF_DS_ODIV2] [get_bd_pins xdma_0/sys_clk]}
must {connect_bd_net [get_bd_pins refclk_buf/IBUF_OUT] [get_bd_pins xdma_0/sys_clk_gt]}

# ---------------- 4x DDR4 ----------------
# PERST# (active low) inverted to drive DDR4 sys_rst (active high)
must {create_bd_cell -type ip -vlnv xilinx.com:ip:util_vector_logic:2.0 perst_inv}
must {set_property -dict [list CONFIG.C_SIZE {1} CONFIG.C_OPERATION {not}] [get_bd_cells perst_inv]}
must {connect_bd_net [get_bd_ports pcie_perstn] [get_bd_pins perst_inv/Op1]}

set csv_file [lindex [get_files */BLS4G4D240FSB.csv] 0]
for {set i 0} {$i < 4} {incr i} {
    must {create_bd_cell -type ip -vlnv xilinx.com:ip:ddr4:2.2 ddr4_$i}
    must {set_property -dict [list \
        CONFIG.C0.DDR4_TimePeriod {833} \
        CONFIG.C0.DDR4_InputClockPeriod {3332} \
        CONFIG.C0.DDR4_CLKOUT0_DIVIDE {5} \
        CONFIG.C0.DDR4_CustomParts $csv_file \
        CONFIG.C0.DDR4_isCustom {true} \
        CONFIG.C0.DDR4_MemoryType {UDIMMs} \
        CONFIG.C0.DDR4_MemoryPart {BLS4G4D240FSB-2400} \
        CONFIG.C0.DDR4_DataWidth {64} \
        CONFIG.C0.DDR4_AxiSelection {true} \
    ] [get_bd_cells ddr4_$i]}

    must {make_bd_intf_pins_external [get_bd_intf_pins ddr4_$i/C0_DDR4]}
    must {make_bd_intf_pins_external [get_bd_intf_pins ddr4_$i/C0_SYS_CLK]}
    must {connect_bd_net [get_bd_pins perst_inv/Res] [get_bd_pins ddr4_$i/sys_rst]}

    # per-channel UI-clock reset
    must {create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 ddr4_c${i}_reset}
    must {set_property -dict [list CONFIG.C_AUX_RESET_HIGH {0}] [get_bd_cells ddr4_c${i}_reset]}
    must {connect_bd_net [get_bd_pins ddr4_$i/c0_ddr4_ui_clk] [get_bd_pins ddr4_c${i}_reset/slowest_sync_clk]}
    must {connect_bd_net [get_bd_pins ddr4_$i/c0_ddr4_ui_clk_sync_rst] [get_bd_pins ddr4_c${i}_reset/ext_reset_in]}
    must {connect_bd_net [get_bd_pins ddr4_c${i}_reset/peripheral_aresetn] [get_bd_pins ddr4_$i/c0_ddr4_aresetn]}
}

# external port names expected by the XDCs.
# NB: renaming a BD port to its CURRENT name is NOT a no-op — Vivado
# uniquifies against the existing name and silently renames it (e.g.
# C0_DDR4_0 -> C0_DDR4_4), which orphans every XDC constraint. Only rename
# when the name actually changes (C0_DDR4_0 already has the right name).
must {set_property name C1_DDR4_0 [get_bd_intf_ports C0_DDR4_1]}
must {set_property name C2_DDR4_0 [get_bd_intf_ports C0_DDR4_2]}
must {set_property name C3_DDR4_0 [get_bd_intf_ports C0_DDR4_3]}
must {set_property name dimm0_refclk [get_bd_intf_ports C0_SYS_CLK_0]}
must {set_property name dimm1_refclk [get_bd_intf_ports C0_SYS_CLK_1]}
must {set_property name dimm2_refclk [get_bd_intf_ports C0_SYS_CLK_2]}
must {set_property name dimm3_refclk [get_bd_intf_ports C0_SYS_CLK_3]}
# assert the exact top-level port set the XDCs constrain
foreach want {C0_DDR4_0 C1_DDR4_0 C2_DDR4_0 C3_DDR4_0 \
              dimm0_refclk dimm1_refclk dimm2_refclk dimm3_refclk \
              pcie_refclk pcie_mgt} {
    if {[llength [get_bd_intf_ports -quiet $want]] != 1} {
        puts "FATAL: expected intf port '$want' missing"; exit 1
    }
}
if {[llength [get_bd_ports -quiet pcie_perstn]] != 1} {
    puts "FATAL: expected port 'pcie_perstn' missing"; exit 1
}
foreach n {dimm0_refclk dimm1_refclk dimm2_refclk dimm3_refclk} {
    must {set_property CONFIG.FREQ_HZ 300000000 [get_bd_intf_ports /$n]}
}

# ---------------- SmartConnect: XDMA M_AXI + seq_0 -> 4x DDR4 ----------------
# 2 SI: S00 = xdma_0/M_AXI (256b), S01 = seq_0/m_axi (128b, connected in the
# sequencer section below once that cell exists). NUM_CLKS stays 5 — seq_0
# runs on xdma_0/axi_aclk, which is already axi_smc/aclk.
must {create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 axi_smc}
must {set_property -dict [list CONFIG.NUM_MI {4} CONFIG.NUM_SI {2} CONFIG.NUM_CLKS {5}] [get_bd_cells axi_smc]}
must {connect_bd_intf_net [get_bd_intf_pins xdma_0/M_AXI] [get_bd_intf_pins axi_smc/S00_AXI]}
must {connect_bd_net [get_bd_pins xdma_0/axi_aclk] [get_bd_pins axi_smc/aclk]}
must {connect_bd_net [get_bd_pins xdma_0/axi_aresetn] [get_bd_pins axi_smc/aresetn]}
for {set i 0} {$i < 4} {incr i} {
    must {connect_bd_net [get_bd_pins ddr4_$i/c0_ddr4_ui_clk] [get_bd_pins axi_smc/aclk[expr {$i+1}]]}

    # per-channel 2:1 mux: host path (central SMC) + matvec engine, all ui_clk
    must {create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 smc_ch$i}
    must {set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {1} CONFIG.NUM_CLKS {1}] [get_bd_cells smc_ch$i]}
    must {connect_bd_net [get_bd_pins ddr4_$i/c0_ddr4_ui_clk] [get_bd_pins smc_ch$i/aclk]}
    must {connect_bd_net [get_bd_pins ddr4_c${i}_reset/peripheral_aresetn] [get_bd_pins smc_ch$i/aresetn]}
    must {connect_bd_intf_net [get_bd_intf_pins axi_smc/M0${i}_AXI] [get_bd_intf_pins smc_ch$i/S00_AXI]}
    must {connect_bd_intf_net [get_bd_intf_pins smc_ch$i/M00_AXI] [get_bd_intf_pins ddr4_$i/C0_DDR4_S_AXI]}

    must {create_bd_cell -type module -reference matvec_chan_ipi mvchan_$i}
    if {[catch {set_property CONFIG.CHAN_ID $i [get_bd_cells mvchan_$i]} err]} {
        puts "WARN: CHAN_ID on mvchan_$i: $err"
    }
    must {connect_bd_intf_net [get_bd_intf_pins mvchan_$i/m_axi] [get_bd_intf_pins smc_ch$i/S01_AXI]}
    must {connect_bd_net [get_bd_pins ddr4_$i/c0_ddr4_ui_clk] [get_bd_pins mvchan_$i/ui_clk]}
    must {connect_bd_net [get_bd_pins ddr4_c${i}_reset/peripheral_aresetn] [get_bd_pins mvchan_$i/ui_rstn]}
    must {connect_bd_net [get_bd_pins xdma_0/axi_aclk] [get_bd_pins mvchan_$i/aclk]}
    must {connect_bd_net [get_bd_pins xdma_0/axi_aresetn] [get_bd_pins mvchan_$i/aresetn]}
}

# ---------------- CSR block on AXI-Lite ----------------
must {create_bd_cell -type module -reference csr_block_ipi csr_0}
if {[catch {set_property CONFIG.VERSION 0x$BuildVer [get_bd_cells csr_0]} err]} {
    puts "WARN: could not set CSR VERSION parameter: $err"
}
must {create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 axil_smc}
# 2 SI: S00 = xdma_0/M_AXI_LITE (host), S01 = seq_0/m_axil (sequencer, wired
# in the sequencer section below). 7 MI: csr_0, mvchan_0..3, layer_0, seq_0.
must {set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {7} CONFIG.NUM_CLKS {1}] [get_bd_cells axil_smc]}
must {connect_bd_net [get_bd_pins xdma_0/axi_aclk] [get_bd_pins axil_smc/aclk]}
must {connect_bd_net [get_bd_pins xdma_0/axi_aresetn] [get_bd_pins axil_smc/aresetn]}
must {connect_bd_intf_net [get_bd_intf_pins xdma_0/M_AXI_LITE] [get_bd_intf_pins axil_smc/S00_AXI]}
# fully-registered slice per MI: the AXI-Lite hauls from the smc (placed
# near XDMA) into the spread CSR blocks were a violated-path family (017)
for {set i 0} {$i < 7} {incr i} {
    must {create_bd_cell -type ip -vlnv xilinx.com:ip:axi_register_slice:2.1 axil_slice_$i}
    must {set_property -dict [list CONFIG.REG_AW {1} CONFIG.REG_AR {1} CONFIG.REG_W {1} CONFIG.REG_R {1} CONFIG.REG_B {1}] [get_bd_cells axil_slice_$i]}
    must {connect_bd_net [get_bd_pins xdma_0/axi_aclk] [get_bd_pins axil_slice_$i/aclk]}
    must {connect_bd_net [get_bd_pins xdma_0/axi_aresetn] [get_bd_pins axil_slice_$i/aresetn]}
    must {connect_bd_intf_net [get_bd_intf_pins axil_smc/M0${i}_AXI] [get_bd_intf_pins axil_slice_$i/S_AXI]}
}
must {connect_bd_intf_net [get_bd_intf_pins axil_slice_0/M_AXI] [get_bd_intf_pins csr_0/s_axil]}
for {set i 0} {$i < 4} {incr i} {
    must {connect_bd_intf_net [get_bd_intf_pins axil_slice_[expr {$i+1}]/M_AXI] [get_bd_intf_pins mvchan_$i/s_axil]}
}
must {connect_bd_net [get_bd_pins xdma_0/axi_aclk] [get_bd_pins csr_0/aclk]}
must {connect_bd_net [get_bd_pins xdma_0/axi_aresetn] [get_bd_pins csr_0/aresetn]}

# ---------------- layer_chan (stage 3): axil M05, axi_aclk domain ----------------
must {create_bd_cell -type module -reference layer_chan_ipi layer_0}
must {connect_bd_intf_net [get_bd_intf_pins axil_slice_5/M_AXI] [get_bd_intf_pins layer_0/s_axil]}
must {connect_bd_net [get_bd_pins xdma_0/axi_aclk] [get_bd_pins layer_0/aclk]}
must {connect_bd_net [get_bd_pins xdma_0/axi_aresetn] [get_bd_pins layer_0/aresetn]}

# ---------------- seq_unit (stage 6): axil M06 slave + axil/axi master ------
# Everything on axi_aclk (single clock domain; no ui_clk on this module).
must {create_bd_cell -type module -reference seq_unit_ipi seq_0}
must {connect_bd_net [get_bd_pins xdma_0/axi_aclk] [get_bd_pins seq_0/aclk]}
must {connect_bd_net [get_bd_pins xdma_0/axi_aresetn] [get_bd_pins seq_0/aresetn]}
# host-facing CSR window (7th AXI-Lite MI)
must {connect_bd_intf_net [get_bd_intf_pins axil_slice_6/M_AXI] [get_bd_intf_pins seq_0/s_axil]}
# sequencer as AXI-Lite master: 2nd SI on axil_smc, so it reaches csr_0,
# mvchan_0..3, layer_0 (and itself) through the same 4K-per-slave map
must {connect_bd_intf_net [get_bd_intf_pins seq_0/m_axil] [get_bd_intf_pins axil_smc/S01_AXI]}
# sequencer as AXI4 read master: 2nd SI on the central DDR4 SmartConnect
must {connect_bd_intf_net [get_bd_intf_pins seq_0/m_axi] [get_bd_intf_pins axi_smc/S01_AXI]}
# XRF sideband from layer_chan is unused in this build — tie the inputs low
must {create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 seq_xrf_tie_we}
must {set_property -dict [list CONFIG.CONST_WIDTH {1} CONFIG.CONST_VAL {0}] [get_bd_cells seq_xrf_tie_we]}
must {create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 seq_xrf_tie_idx}
must {set_property -dict [list CONFIG.CONST_WIDTH {3} CONFIG.CONST_VAL {0}] [get_bd_cells seq_xrf_tie_idx]}
must {create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 seq_xrf_tie_dat}
must {set_property -dict [list CONFIG.CONST_WIDTH {18} CONFIG.CONST_VAL {0}] [get_bd_cells seq_xrf_tie_dat]}
must {connect_bd_net [get_bd_pins seq_xrf_tie_we/dout]  [get_bd_pins seq_0/xrf_sb_we]}
must {connect_bd_net [get_bd_pins seq_xrf_tie_idx/dout] [get_bd_pins seq_0/xrf_sb_idx]}
must {connect_bd_net [get_bd_pins seq_xrf_tie_dat/dout] [get_bd_pins seq_0/xrf_sb_data]}
# seq_busy / seq_halted / seq_err are readback status only: left dangling on
# purpose (BD allows unconnected outputs; do NOT make them external ports —
# the XDCs constrain an exact top-level port set, asserted above).

# ---------------- burst mover fabric (rung 3, docs/RUNG3_SPEC.md S2/S3) ----
# seq_0/m_axib (32b AXI4, READ_WRITE) -> 1x5 SmartConnect -> the engine
# RES/XWIN windows and the layer scratchpad.  NUM_CLKS 1: every endpoint is
# ALREADY on xdma_0/axi_aclk, so this adds ZERO clock conversion and ZERO
# CDC.  MI order is mvchan_0..3 then layer_0 (S2).  Fully-registered slice
# per MI, same reason as axil_slice_* above (the 017 violated-path family).
must {create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 burst_smc}
must {set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {5} CONFIG.NUM_CLKS {1}] [get_bd_cells burst_smc]}
must {connect_bd_net [get_bd_pins xdma_0/axi_aclk] [get_bd_pins burst_smc/aclk]}
must {connect_bd_net [get_bd_pins xdma_0/axi_aresetn] [get_bd_pins burst_smc/aresetn]}
must {connect_bd_intf_net [get_bd_intf_pins seq_0/m_axib] [get_bd_intf_pins burst_smc/S00_AXI]}
# NB the M0${i} form is only valid for i < 10 (SmartConnect pins are M00..M09)
for {set i 0} {$i < 5} {incr i} {
    must {create_bd_cell -type ip -vlnv xilinx.com:ip:axi_register_slice:2.1 burst_slice_$i}
    must {set_property -dict [list CONFIG.REG_AW {1} CONFIG.REG_AR {1} CONFIG.REG_W {1} CONFIG.REG_R {1} CONFIG.REG_B {1}] [get_bd_cells burst_slice_$i]}
    must {connect_bd_net [get_bd_pins xdma_0/axi_aclk] [get_bd_pins burst_slice_$i/aclk]}
    must {connect_bd_net [get_bd_pins xdma_0/axi_aresetn] [get_bd_pins burst_slice_$i/aresetn]}
    must {connect_bd_intf_net [get_bd_intf_pins burst_smc/M0${i}_AXI] [get_bd_intf_pins burst_slice_$i/S_AXI]}
}
for {set i 0} {$i < 4} {incr i} {
    must {connect_bd_intf_net [get_bd_intf_pins burst_slice_$i/M_AXI] [get_bd_intf_pins mvchan_$i/s_axib]}
}
must {connect_bd_intf_net [get_bd_intf_pins burst_slice_4/M_AXI] [get_bd_intf_pins layer_0/s_axib]}

must {create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 calib_concat}
must {set_property -dict [list CONFIG.NUM_PORTS {4}] [get_bd_cells calib_concat]}
for {set i 0} {$i < 4} {incr i} {
    must {connect_bd_net [get_bd_pins ddr4_$i/c0_init_calib_complete] [get_bd_pins calib_concat/In$i]}
}
must {connect_bd_net [get_bd_pins calib_concat/dout] [get_bd_pins csr_0/calib_in]}

# ---------------- address map ----------------
must {assign_bd_address}
# Pin DDR4 segments at 4GB strides in XDMA's DMA address space
for {set i 0} {$i < 4} {incr i} {
    set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces xdma_0/M_AXI] -filter "NAME =~ *ddr4_$i*"]
    if {[llength $seg] != 1} { puts "FATAL: ddr4_$i seg lookup got: $seg"; exit 1 }
    must {set_property range 4G $seg}
    must {set_property offset [expr {$i * 0x100000000}] $seg}
}
set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces xdma_0/M_AXI_LITE] -filter "NAME =~ *csr_0*"]
if {[llength $seg] != 1} { puts "FATAL: csr seg lookup got: $seg"; exit 1 }
must {set_property offset 0x0 $seg}
# two-pass: park all chan segs high first so finals never collide with
# the auto-assigned layout
for {set i 0} {$i < 4} {incr i} {
    set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces xdma_0/M_AXI_LITE] -filter "NAME =~ *mvchan_$i*"]
    if {[llength $seg] != 1} { puts "FATAL: mvchan_$i axil seg: $seg"; exit 1 }
    must {set_property offset [expr {0x80000 + 0x1000 * $i}] $seg}
}
set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces xdma_0/M_AXI_LITE] -filter "NAME =~ *layer_0*"]
if {[llength $seg] != 1} { puts "FATAL: layer_0 axil seg: $seg"; exit 1 }
must {set_property offset 0x90000 $seg}
set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces xdma_0/M_AXI_LITE] -filter "NAME =~ *seq_0*"]
if {[llength $seg] != 1} { puts "FATAL: seq_0 axil seg: $seg"; exit 1 }
must {set_property offset 0xA0000 $seg}
for {set i 0} {$i < 4} {incr i} {
    set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces xdma_0/M_AXI_LITE] -filter "NAME =~ *mvchan_$i*"]
    must {set_property offset [expr {0x1000 * ($i + 1)}] $seg}
    # engine's read view of its own channel: 4 GiB at 0
    set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces mvchan_$i/m_axi] -filter "NAME =~ *ddr4_$i*"]
    if {[llength $seg] != 1} { puts "FATAL: mvchan_$i ddr seg: $seg"; exit 1 }
    must {set_property range 4G $seg}
    must {set_property offset 0x0 $seg}
}
set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces xdma_0/M_AXI_LITE] -filter "NAME =~ *layer_0*"]
must {set_property offset 0x5000 $seg}
set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces xdma_0/M_AXI_LITE] -filter "NAME =~ *seq_0*"]
must {set_property offset 0x6000 $seg}

# seq_0/m_axil: the sequencer drives the SAME 4K-per-slave CSR map the host
# does, so firmware addresses are identical from either side.
# DELIBERATELY NOT MAPPED: seq_0 -> its own s_axil. The ISA's 0x2nn
# sequencer CSR space (XRF writes, TCNT_SEQ) is decoded INSIDE seq_unit and
# never leaves the module, so the self path is dead — and leaving it out
# keeps the fabric acyclic (a master waiting on a response from its own
# slave is a deadlock shape nobody should have to reason about).
set seq_axil_map {csr_0 0x0 mvchan_0 0x1000 mvchan_1 0x2000 mvchan_2 0x3000 \
                  mvchan_3 0x4000 layer_0 0x5000}
# pass 1: park high first so the finals never collide with the auto layout
set i 0
foreach {sl off} $seq_axil_map {
    set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces seq_0/m_axil] -filter "NAME =~ *$sl*"]
    if {[llength $seg] != 1} { puts "FATAL: seq_0 m_axil $sl seg: $seg"; exit 1 }
    must {set_property offset [expr {0x80000 + 0x1000 * $i}] $seg}
    incr i
}
# the self segment, if assign_bd_address created one, is explicitly excluded
set seg [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces seq_0/m_axil] -filter "NAME =~ *seq_0*"]
if {[llength $seg] == 1} {
    puts "NOTE: excluding the seq_0 -> seq_0 self segment from the address map"
    must {exclude_bd_addr_seg $seg}
}
# pass 2: finals
foreach {sl off} $seq_axil_map {
    set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces seq_0/m_axil] -filter "NAME =~ *$sl*"]
    if {[llength $seg] != 1} { puts "FATAL: seq_0 m_axil $sl seg: $seg"; exit 1 }
    must {set_property offset $off $seg}
}
# seq_0/m_axi: same 16 GiB view of the four DDR4 channels that XDMA M_AXI has
for {set i 0} {$i < 4} {incr i} {
    set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces seq_0/m_axi] -filter "NAME =~ *ddr4_$i*"]
    if {[llength $seg] != 1} { puts "FATAL: seq_0 m_axi ddr4_$i seg: $seg"; exit 1 }
    must {set_property range 4G $seg}
    must {set_property offset [expr {$i * 0x100000000}] $seg}
}
# seq_0/m_axib: the PRIVATE burst map (rung 3, RUNG3_SPEC S4).  64 KiB
# stride, mvchan_c at (c+1)<<16 and layer_0 at 5<<16 — deliberately NOT the
# 4K CSR layout, because these are the wide data windows (RES 16 KiB + XWIN
# 4 KiB per channel, 64 KiB of scratch) and not the register files.  Offset
# 0 is left as a hole so a null/unprogrammed address can never alias a real
# window.  Two-pass parking, same reason as the AXI-Lite map above.
set seq_axib_map {mvchan_0 0x10000 mvchan_1 0x20000 mvchan_2 0x30000 \
                  mvchan_3 0x40000 layer_0 0x50000}
set i 0
foreach {sl off} $seq_axib_map {
    set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces seq_0/m_axib] -filter "NAME =~ *$sl*"]
    if {[llength $seg] != 1} { puts "FATAL: seq_0 m_axib $sl seg: $seg"; exit 1 }
    must {set_property offset [expr {0x800000 + 0x10000 * $i}] $seg}
    incr i
}
foreach {sl off} $seq_axib_map {
    set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces seq_0/m_axib] -filter "NAME =~ *$sl*"]
    must {set_property offset $off $seg}
    # the shims declare a 64 KiB window (ADDR_WIDTH 16); anything else means
    # an agent-B/C interface drifted from the frozen contract
    # RANGE formatting varies by Vivado context ("64K" vs 0x00010000 vs
    # 65536) — normalize before comparing
    set r [get_property RANGE $seg]
    set ok 0
    if {$r eq "64K"} { set ok 1 } elseif {![catch {expr {$r == 65536}} eq_] && $eq_} { set ok 1 }
    if {!$ok} {
        puts "FATAL: seq_0 m_axib $sl range is $r, expected 64K (RUNG3 S4)"
        exit 1
    }
}
puts "ADDRESS MAP:"
foreach s [get_bd_addr_segs -of_objects [get_bd_addr_spaces xdma_0/*]] {
    puts [format "  %-60s off=%s range=%s" $s [get_property OFFSET $s] [get_property RANGE $s]]
}
foreach s [get_bd_addr_segs -of_objects [get_bd_addr_spaces seq_0/*]] {
    puts [format "  %-60s off=%s range=%s" $s [get_property OFFSET $s] [get_property RANGE $s]]
}

must {validate_bd_design}
must {save_bd_design}

set bdfile [get_files bd.bd]
must {make_wrapper -files $bdfile -top}
must {add_files -norecurse $OutDir/proj/stage1.gen/sources_1/bd/bd/hdl/bd_wrapper.v}
must {set_property top bd_wrapper [current_fileset]}

puts "CREATE_PROJECT_OK"
