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
# data map that no other master can see:
#   0x1_0000 mvchan_0  0x2_0000 mvchan_1  0x3_0000 mvchan_2  0x4_0000 mvchan_3
#   0x5_0000-0x7_FFFF DECODE HOLE   0x8_0000 layer_0 (256 KiB, G3.1)
# per mvchan (64 KiB): 0x0000-0x3FFF RES read window (row r at byte 4r),
# 0x4000-0x57FF XWIN write window (word w at byte 4w, 1536 words = K <= 6144)
# — both inside the 64 KiB stride, so the R-b XWIN growth needed no
# address-segment change.  layer_0: scratch word w at byte 4w, w < 65536;
# R-b doubled it to 128 KiB and MOVED it to 0x6_0000, and G3.1 doubled it
# again to 256 KiB and MOVED it to 0x8_0000, each time because an AXI segment
# must be RANGE-ALIGNED and the previous base is not aligned to the new size.

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
# state_dma.sv is S2's 512-bit AXI4 state-DMA engine, instantiated at
# rtl/layer_chan.sv:705 as `u_dma`.  It was MISSING from this list until G5b
# (Task 14, 2026-09-05): S2 added the m_axis bundle to the wrapper and the
# third SmartConnect SI below, and never added the module's source file.  The
# omission is SILENT through create_project — `create_bd_cell -type module
# -reference layer_chan_ipi` built the cell and validate_bd_design got as far
# as reporting a FREQ_HZ mismatch on build_036, so nothing here would have
# said the engine was absent; the first complaint would have come hours later
# out of synthesis, or not at all if the missing module were black-boxed.
foreach x {fx_pkg.sv fx_rsqrt.sv fx_recip.sv fx_silu.sv vecnorm_unit.sv \
           rope_unit.sv conv4_silu.sv dn_step.sv attn_core.sv gate_unit.sv \
           vec_alu.sv state_dma.sv layer_chan.sv} {
    must {add_files -norecurse $RtlDir/$x}
}
# Assert the file list against the modules layer_chan actually instantiates.
# A missing source is the one class of defect this script cannot otherwise
# see, and it is cheap to check here rather than in a synthesis log.
foreach m {fx_rsqrt fx_recip fx_silu vecnorm_unit rope_unit conv4_silu \
           dn_step attn_core gate_unit vec_alu state_dma layer_chan} {
    if {[llength [get_files -quiet */$m.sv]] != 1} {
        puts "FATAL: rtl/$m.sv not in the project (layer_chan instantiates it)"; exit 1
    }
}
puts "LAYER_SOURCES_OK: 12 layer modules present"
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

# ---------------- SmartConnect: XDMA M_AXI + seq_0 + layer_0 -> 4x DDR4 -----
# 3 SI: S00 = xdma_0/M_AXI (256b), S01 = seq_0/m_axi (128b) and S02 =
# layer_0/m_axis (512b, the S2 state DMA) — both connected in the sections
# below once those cells exist.  NUM_CLKS stays 5: seq_0 and layer_0 run on
# xdma_0/axi_aclk, which is already axi_smc/aclk.
must {create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 axi_smc}
must {set_property -dict [list CONFIG.NUM_MI {4} CONFIG.NUM_SI {3} CONFIG.NUM_CLKS {5}] [get_bd_cells axi_smc]}
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
# G5b (Task 14, 2026-09-05): GIVE m_axis A CLOCK.  Without this, and the
# CLK_DOMAIN block just before validate_bd_design below, the design does not
# build at all — validate_bd_design ERRORS:
#   [BD 41-237] Bus Interface property FREQ_HZ does not match between
#   /axi_smc/S02_AXI(250000000) and /layer_0/m_axis(100000000)
# preceded by [BD 41-967] "/layer_0/m_axis is not associated to any clock pin"
# and two SmartConnect clock-domain CRITICAL WARNINGs on S02_AXI (build_036,
# evidence/qwen9b/g5/030_build_036.log).
#
# THE CAUSE is in the wrapper's metadata, not here: rtl/layer_chan_ipi.v:9
# declares `ASSOCIATED_BUSIF s_axil:s_axib` on aclk and S2 never added the
# m_axis master to it, although rtl/layer_chan_ipi.v:123 says the master is
# "on the SAME aclk".  rtl/seq_unit_ipi.v:12 is the working comparand: it
# lists all four of its bundles.  Unassociated, IPI gives m_axis its default
# 100 MHz and no clock domain.
#
# WHAT DOES NOT WORK, MEASURED rather than assumed
# (evidence/qwen9b/g5/033_bd_pin_probe.log, a one-cell probe design):
#   PROBE_ABIF_BEFORE: 's_axil:s_axib'
#   PROBE_ABIF_SET_ERR: (none)
#   PROBE_ABIF_AFTER: 's_axil:s_axib'
# `set_property CONFIG.ASSOCIATED_BUSIF` on the clock pin of a `-type module`
# reference cell is SILENTLY IGNORED — no error, value unchanged.  That is
# precisely the trap this script's own header warns about at line 97-98, and
# build_038 cost a create_project cycle to it.  The association can only be
# fixed in the wrapper's HDL attribute, which is frozen RTL.
#
# WHAT DOES WORK, from the same probe: the two BUS PARAMETERS on the interface
# pin are both writable — FREQ_HZ 100000000 -> 250000000 and CLK_DOMAIN
# '' -> a set value.  Between them they state exactly what the association
# would have propagated, so they are set explicitly and asserted.  FREQ_HZ is
# set here; CLK_DOMAIN needs a donor that only exists once everything is
# connected, so it is set at the end, immediately before validate_bd_design.
# evidence/qwen9b/g5/G5B_TIMING.md records the wrapper repair as a follow-on.
must {set_property CONFIG.FREQ_HZ 250000000 [get_bd_intf_pins layer_0/m_axis]}
set _mfreq [get_property CONFIG.FREQ_HZ [get_bd_intf_pins layer_0/m_axis]]
if {$_mfreq != 250000000} {
    puts "FATAL: layer_0/m_axis FREQ_HZ = '$_mfreq', wanted 250000000"; exit 1
}
puts "SDMA_FREQ_OK: layer_0/m_axis FREQ_HZ=$_mfreq"
# S2 (spec 2026-09-04 state-spill §4): layer_0's 512-bit state DMA is the
# THIRD SI of the central DDR4 SmartConnect.  axi_smc/aclk is already
# xdma_0/axi_aclk (see the SmartConnect section above), which is layer_0's
# clock, so this adds ZERO clock conversion and ZERO CDC.  Its address map
# is pinned to the same four 4 GiB segments seq_0/m_axi gets, below.
must {connect_bd_intf_net [get_bd_intf_pins layer_0/m_axis] [get_bd_intf_pins axi_smc/S02_AXI]}

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
# BM1 (spec docs/superpowers/specs/2026-09-24-board-idle-counters-design.md
# §1.1, the user's ruling D1a): each matvec channel's engine-busy bit into
# seq_0's idle counters (docs/SEQ_ISA.md B16).  Plain scalar nets, the same
# kind of wiring as the xrf_sb tie-offs above.  BOTH ends are on
# xdma_0/axi_aclk (mvchan_$i/aclk and seq_0/aclk, connected above): the
# source is a flop of the channel's ALREADY-synchronised STATUS bit
# (rtl/matvec_chan.sv cdc_sync_stat[0]) and seq_unit takes it through two
# more flops, so this adds no clock, no CDC and no constraint.
for {set i 0} {$i < 4} {incr i} {
    must {connect_bd_net [get_bd_pins mvchan_$i/mv_busy_bm] [get_bd_pins seq_0/mv_busy_bm$i]}
}
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
# layer_0/m_axis (S2): the SAME 16 GiB view.  Without this the 34-bit
# addresses the SB_DN/SB_KV/SB_CV CSRs carry do not decode and every SLD/SST
# answers DECERR (E_DMA_AXI).  Identical form to seq_0/m_axi above.
for {set i 0} {$i < 4} {incr i} {
    set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces layer_0/m_axis] -filter "NAME =~ *ddr4_$i*"]
    if {[llength $seg] != 1} { puts "FATAL: layer_0 m_axis ddr4_$i seg: $seg"; exit 1 }
    must {set_property range 4G $seg}
    must {set_property offset [expr {$i * 0x100000000}] $seg}
}
# seq_0/m_axib: the PRIVATE burst map (rung 3, RUNG3_SPEC S4).  64 KiB
# stride, mvchan_c at (c+1)<<16 and layer_0 at 8<<16 (R-b moved it from
# 5<<16 to 6<<16, G3.1 from 6<<16 to 8<<16 — see the note below) —
# deliberately NOT the
# 4K CSR layout, because these are the wide data windows (RES 16 KiB + XWIN
# 6 KiB per channel, 256 KiB of scratch) and not the register files.  Offset
# 0 is left as a hole so a null/unprogrammed address can never alias a real
# window.  Two-pass parking, same reason as the AXI-Lite map above.
#
# R-b (2026-08-13): layer_0's window doubled to 128 KiB (32768 scratch
# words, ADDR_WIDTH 17) and MOVED from 0x50000 to 0x60000 — an AXI segment
# must be RANGE-ALIGNED and 0x50000 is not 128 KiB-aligned.  0x50000-0x5FFFF
# was then a decode hole.
#
# G3.1 (2026-09-01, spec 4.3 S3/S4): the scratchpad is 65536 words, so
# layer_0's window doubles again to 256 KiB (ADDR_WIDTH 18) and MOVES from
# 0x60000 to 0x80000 for the SAME reason — 0x60000 is not 256 KiB-aligned,
# 0x80000 is.  layer_0 now covers 0x80000-0xBFFFF and the decode hole grows
# to 0x50000-0x7FFFF.  The two-pass parking still works: layer_0 is index 4,
# parked at 0x840000, which is 256 KiB-aligned and clear of the four 64 KiB
# mvchan parking slots ending at 0x83FFFF.  Mirrored in
# rtl/seq_movers.sv LAYB_BASE, rtl/seq_unit.sv LAYB_BASE,
# rtl/layer_chan.sv / rtl/layer_chan_ipi.v s_axib ADDR_WIDTH,
# tb/tb_burst_fabric.sv LAYBASE and docs/SEQ_ISA.md B12.3.
set seq_axib_map {mvchan_0 0x10000 mvchan_1 0x20000 mvchan_2 0x30000 \
                  mvchan_3 0x40000 layer_0 0x80000}
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
    # the mvchan shims declare a 64 KiB window (ADDR_WIDTH 16) and layer_0 a
    # 256 KiB one (ADDR_WIDTH 18, G3.1; it was 128 KiB / 17 at R-b);
    # anything else means an agent-B/C interface drifted from the frozen
    # contract.
    # RANGE formatting varies by Vivado context ("64K" vs 0x00010000 vs
    # 65536) — normalize before comparing
    set want_b [expr {$sl eq "layer_0" ? 262144 : 65536}]
    set want_s [expr {$sl eq "layer_0" ? "256K" : "64K"}]
    set r [get_property RANGE $seg]
    set ok 0
    if {$r eq $want_s} { set ok 1 } elseif {![catch {expr {$r == $want_b}} eq_] && $eq_} { set ok 1 }
    if {!$ok} {
        puts "FATAL: seq_0 m_axib $sl range is $r, expected $want_s (RUNG3 S4 / G3.1)"
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

# G5b: the CLOCK-DOMAIN half of the m_axis fix (see the block in the layer
# section above).  A matching FREQ_HZ alone would silence [BD 41-237] while
# still leaving m_axis in no clock domain, which lets SmartConnect treat
# S02_AXI as asynchronous and infer a clock converter on the state-DMA path —
# a FUNCTIONAL change, not a timing one, and exactly the kind a green build
# hides.  So the domain is copied from a donor that already carries it.
# Donors are tried in order and the first non-empty wins; every one is printed
# so a future failure says which were empty rather than leaving it to guesswork.
set _dom ""
foreach donor {xdma_0/axi_aclk} {
    set _d [get_property -quiet CONFIG.CLK_DOMAIN [get_bd_pins -quiet $donor]]
    puts "SDMA_CLKDOM_DONOR $donor = '$_d'"
    if {$_d ne "" && $_dom eq ""} { set _dom $_d }
}
foreach donor {xdma_0/M_AXI axi_smc/S00_AXI layer_0/s_axil layer_0/s_axib} {
    set _d [get_property -quiet CONFIG.CLK_DOMAIN [get_bd_intf_pins -quiet $donor]]
    puts "SDMA_CLKDOM_DONOR $donor = '$_d'"
    if {$_d ne "" && $_dom eq ""} { set _dom $_d }
}
if {$_dom eq ""} { puts "FATAL: no donor carries a CLK_DOMAIN for layer_0/m_axis"; exit 1 }
must {set_property CONFIG.CLK_DOMAIN $_dom [get_bd_intf_pins layer_0/m_axis]}
set _mdom [get_property CONFIG.CLK_DOMAIN [get_bd_intf_pins layer_0/m_axis]]
if {$_mdom ne $_dom} {
    puts "FATAL: layer_0/m_axis CLK_DOMAIN = '$_mdom', wanted '$_dom'"; exit 1
}
puts "SDMA_CLKDOM_SET: layer_0/m_axis CLK_DOMAIN=$_mdom"
for {set i 0} {$i < 4} {incr i} { foreach {s d} [list seq_0/xpush${i}_valid mvchan_$i/xpush_valid seq_0/xpush${i}_idx mvchan_$i/xpush_idx seq_0/xpush${i}_data mvchan_$i/xpush_data mvchan_$i/xpush_room seq_0/xpush${i}_room mvchan_$i/xpush_busy seq_0/xpush${i}_busy] { must {connect_bd_net [get_bd_pins $s] [get_bd_pins $d]} } }  ;# R3-8: the x-push bus (B17.3), wired BEFORE validation; explained and checked in the R3-8 block after save_bd_design
must {validate_bd_design}

# Post-validate, where parameter propagation has actually run.  The decisive
# test is not that m_axis kept the values set above but that the SmartConnect
# sees S02_AXI in the SAME clock domain as S00_AXI — XDMA's own master, the
# known-good SI on this interconnect.  Equal domains means no clock converter
# on the state-DMA path.
set _mfreq2 [get_property CONFIG.FREQ_HZ [get_bd_intf_pins layer_0/m_axis]]
if {$_mfreq2 != 250000000} { puts "FATAL: layer_0/m_axis FREQ_HZ = '$_mfreq2' after validate"; exit 1 }
set _s00 [get_property CONFIG.CLK_DOMAIN [get_bd_intf_pins axi_smc/S00_AXI]]
set _s02 [get_property CONFIG.CLK_DOMAIN [get_bd_intf_pins axi_smc/S02_AXI]]
if {$_s02 eq "" || $_s02 ne $_s00} {
    puts "FATAL: axi_smc/S02_AXI CLK_DOMAIN '$_s02' != S00_AXI CLK_DOMAIN '$_s00'"; exit 1
}
puts "SDMA_CLOCK_OK: m_axis FREQ_HZ=$_mfreq2 CLK_DOMAIN=[get_property CONFIG.CLK_DOMAIN [get_bd_intf_pins layer_0/m_axis]]; axi_smc S02==S00 domain '$_s02'"
must {save_bd_design}

# ---------------- R3-8: the MOVX-broadcast x-push bus (form (a)) ------------
# docs/SEQ_ISA.md v2.3 B17.3 and spec docs/superpowers/specs/2026-09-27-seq-
# rtl-round-design.md §1.3 (a): seq_0 pushes a broadcast MOVX's x words, with
# their XWIN word index, into all four matvec channels' XWIN FIFOs in
# lockstep, and each channel answers room + busy.  Per channel: 45 FORWARD
# bits (xpush<c>_valid 1 + xpush<c>_idx 12 + xpush<c>_data 32, seq_0 ->
# mvchan_<c>) and 2 RETURN bits (xpush<c>_room, xpush<c>_busy, mvchan_<c> ->
# seq_0) = 47; 188 bits in 20 BD nets in all.  Plain scalar/bus nets, the
# same kind of wiring as the BM1 mv_busy_bm nets above (no interface, no
# IP).  BOTH ends are on xdma_0/axi_aclk (mvchan_$i/aclk and seq_0/aclk,
# connected above) and every bit is REGISTERED AT BOTH ENDS in the RTL
# (seq_movers' output / input flops, matvec_chan's input register / room and
# busy flops), so this adds NO clock, NO CDC and NO constraint — the only
# aclk -> ui_clk crossing these words meet is each channel's existing XWIN
# xpm_fifo_async.  On mvchan_0 the 45 forward bits cross SLR1 -> SLR0 and the
# two return bits cross SLR0 -> SLR1 (evidence/qwen9b/g5/G5D_TIMING.md §8.3);
# R3-10's probe names them (evidence/qwen9b/sr/R3_8_RTL.md, the checklist).
# The 20 connect_bd_net calls are the one-line loop just before
# validate_bd_design above (a blank line there, so no cited line moves and
# the design is validated WITH the bus); this block, after the save, only
# CHECKS it — widths, both ends' clock nets, the 188-bit total — read-only.
set _xp_clk [get_bd_nets -of_objects [get_bd_pins xdma_0/axi_aclk]]
set _xp_bits 0
set _xp_nets 0
for {set i 0} {$i < 4} {incr i} {
    foreach {src dst w} [list seq_0/xpush${i}_valid  mvchan_$i/xpush_valid 1 \
                              seq_0/xpush${i}_idx    mvchan_$i/xpush_idx   12 \
                              seq_0/xpush${i}_data   mvchan_$i/xpush_data  32 \
                              mvchan_$i/xpush_room   seq_0/xpush${i}_room  1 \
                              mvchan_$i/xpush_busy   seq_0/xpush${i}_busy  1] {
        set _n [get_bd_nets -quiet -of_objects [get_bd_pins $src]]
        if {[llength $_n] != 1 || $_n ne [get_bd_nets -quiet -of_objects [get_bd_pins $dst]]} {
            puts "FATAL: $src and $dst are not one net ($_n)"; exit 1
        }
        set _l [get_property LEFT [get_bd_pins $src]]
        set _r [get_property RIGHT [get_bd_pins $src]]
        set _got [expr {($_l eq "") ? 1 : (abs($_l - $_r) + 1)}]
        if {$_got != $w} { puts "FATAL: $src is $_got bits, expected $w"; exit 1 }
        set _cs [get_bd_nets -of_objects [get_bd_pins [lindex [split $src /] 0]/aclk]]
        set _cd [get_bd_nets -of_objects [get_bd_pins [lindex [split $dst /] 0]/aclk]]
        if {$_cs ne $_xp_clk || $_cd ne $_xp_clk} {
            puts "FATAL: $src ($_cs) -> $dst ($_cd): not both on $_xp_clk"; exit 1
        }
        puts "XPUSH_NET: $_n $src -> $dst bits $w clocks $_cs -> $_cd"
        incr _xp_bits $w
        incr _xp_nets
    }
}
if {$_xp_bits != 188 || $_xp_nets != 20} {
    puts "FATAL: x-push bus is $_xp_bits bits in $_xp_nets nets, expected 188 in 20"; exit 1
}
puts "XPUSH_BUS_OK: $_xp_nets BD nets, $_xp_bits bits (47 per channel: 45 forward + 2 return), every end on $_xp_clk"

set bdfile [get_files bd.bd]
must {make_wrapper -files $bdfile -top}
must {add_files -norecurse $OutDir/proj/stage1.gen/sources_1/bd/bd/hdl/bd_wrapper.v}
must {set_property top bd_wrapper [current_fileset]}

puts "CREATE_PROJECT_OK"
