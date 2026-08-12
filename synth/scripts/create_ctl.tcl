# create_ctl.tcl — minimal XDMA + BRAM control design for DMA-path bisection.
# Usage: vivado -mode batch -source create_ctl.tcl -tclargs <out_dir> <variant>
#   variant A: XDMA configured EXACTLY like the official VCU1525 x8 preset
#   variant B: A + the four extra params used by build_005
# BRAM (256KB) on M_AXI at 0x0. Same XDCs (PCIe pins only matter).

if {[llength $argv] < 2} { puts "FATAL: need <out_dir> <A|B>"; exit 1 }
set OutDir  [lindex $argv 0]
set Variant [lindex $argv 1]

set ScriptDir [file dirname [file normalize [info script]]]
set RepoRoot  [file normalize "$ScriptDir/../.."]
set ConstrDir "$RepoRoot/synth/constraints"

proc must {script} {
    if {[catch {uplevel 1 $script} err]} { puts "FATAL: $err"; exit 1 }
}

set_param general.maxThreads 16
must {create_project ctl$Variant $OutDir/proj -part xcvu9p-fsgd2104-2L-e}
# Only DIMM0 XDC needed (PCIe refclk/perst + compression); DDR pins unused.
must {import_files -fileset constrs_1 -norecurse $ConstrDir/BCU1525_DIMM0.xdc}
must {import_files -fileset constrs_1 -norecurse $ConstrDir/fable5_pcie_clk.xdc}
must {create_bd_design "bd"}

must {create_bd_cell -type ip -vlnv xilinx.com:ip:util_ds_buf:2.2 refclk_buf}
must {set_property -dict [list CONFIG.C_BUF_TYPE {IBUFDSGTE}] [get_bd_cells refclk_buf]}
must {make_bd_intf_pins_external [get_bd_intf_pins refclk_buf/CLK_IN_D]}
must {set_property name pcie_refclk [get_bd_intf_ports CLK_IN_D_0]}
must {set_property CONFIG.FREQ_HZ 100000000 [get_bd_intf_ports /pcie_refclk]}

must {create_bd_cell -type ip -vlnv xilinx.com:ip:xdma:4.1 xdma_0}
if {$Variant eq "G"} {
    # Basic mode, no GT selection (default quad is already 227), explicit width/freq
    must {set_property -dict [list \
        CONFIG.pl_link_cap_max_link_speed {8.0_GT/s} \
        CONFIG.pl_link_cap_max_link_width {X8} \
        CONFIG.axi_data_width {256_bit} \
        CONFIG.axisten_freq {250} \
    ] [get_bd_cells xdma_0]}
} else {
# official VCU1525 pciex8_preset, verbatim
must {set_property -dict [list \
    CONFIG.pl_link_cap_max_link_speed {8.0_GT/s} \
    CONFIG.pl_link_cap_max_link_width {X8} \
    CONFIG.mode_selection {Advanced} \
    CONFIG.en_gt_selection {true} \
    CONFIG.select_quad {GTY_Quad_227} \
] [get_bd_cells xdma_0]}
}
# Variant deltas on top of the preset:
#  B = width/freq + axilite + 64bit (build_005's exact set)
#  C = width/freq only
#  D = C + xdma_pcie_64bit_en
#  E = C + axilite_master_en
#  H = B (build_005 config); the pcie_refclk create_clock fix applies to all
if {$Variant in {B C D E H}} {
    must {set_property -dict [list \
        CONFIG.axi_data_width {256_bit} \
        CONFIG.axisten_freq {250} \
    ] [get_bd_cells xdma_0]}
}
if {$Variant in {B E H}} {
    must {set_property -dict [list CONFIG.axilite_master_en {true}] [get_bd_cells xdma_0]}
}
if {$Variant in {B D H}} {
    must {set_property -dict [list CONFIG.xdma_pcie_64bit_en {true}] [get_bd_cells xdma_0]}
}

must {make_bd_intf_pins_external [get_bd_intf_pins xdma_0/pcie_mgt]}
must {set_property name pcie_mgt [get_bd_intf_ports pcie_mgt_0]}
must {make_bd_pins_external [get_bd_pins xdma_0/sys_rst_n]}
must {set_property name pcie_perstn [get_bd_ports sys_rst_n_0]}
must {connect_bd_net [get_bd_pins refclk_buf/IBUF_DS_ODIV2] [get_bd_pins xdma_0/sys_clk]}
must {connect_bd_net [get_bd_pins refclk_buf/IBUF_OUT] [get_bd_pins xdma_0/sys_clk_gt]}

# BRAM target on M_AXI
must {create_bd_cell -type ip -vlnv xilinx.com:ip:axi_bram_ctrl:4.1 bram_ctrl}
must {set_property -dict [list CONFIG.SINGLE_PORT_BRAM {1} CONFIG.DATA_WIDTH {256}] [get_bd_cells bram_ctrl]}
must {create_bd_cell -type ip -vlnv xilinx.com:ip:blk_mem_gen:8.4 bram}
must {set_property -dict [list CONFIG.Memory_Type {Single_Port_RAM}] [get_bd_cells bram]}
must {connect_bd_intf_net [get_bd_intf_pins bram_ctrl/BRAM_PORTA] [get_bd_intf_pins bram/BRAM_PORTA]}
must {connect_bd_intf_net [get_bd_intf_pins xdma_0/M_AXI] [get_bd_intf_pins bram_ctrl/S_AXI]}
must {connect_bd_net [get_bd_pins xdma_0/axi_aclk] [get_bd_pins bram_ctrl/s_axi_aclk]}
must {connect_bd_net [get_bd_pins xdma_0/axi_aresetn] [get_bd_pins bram_ctrl/s_axi_aresetn]}

# axilite variants need the AXI-Lite master port terminated
if {$Variant in {B E H}} {
    must {create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 gpio0}
    must {set_property -dict [list CONFIG.C_ALL_INPUTS {1}] [get_bd_cells gpio0]}
    must {connect_bd_intf_net [get_bd_intf_pins xdma_0/M_AXI_LITE] [get_bd_intf_pins gpio0/S_AXI]}
    must {connect_bd_net [get_bd_pins xdma_0/axi_aclk] [get_bd_pins gpio0/s_axi_aclk]}
    must {connect_bd_net [get_bd_pins xdma_0/axi_aresetn] [get_bd_pins gpio0/s_axi_aresetn]}
}

must {assign_bd_address}
set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces xdma_0/M_AXI] -filter "NAME =~ *bram*"]
must {set_property offset 0x0 $seg}
must {set_property range 256K $seg}
puts "ADDRESS MAP:"
foreach s [get_bd_addr_segs -of_objects [get_bd_addr_spaces xdma_0/*]] {
    puts [format "  %-60s off=%s range=%s" $s [get_property OFFSET $s] [get_property RANGE $s]]
}

must {validate_bd_design}
must {save_bd_design}
set bdfile [get_files bd.bd]
must {make_wrapper -files $bdfile -top}
must {add_files -norecurse $OutDir/proj/ctl$Variant.gen/sources_1/bd/bd/hdl/bd_wrapper.v}
must {set_property top bd_wrapper [current_fileset]}
puts "CREATE_PROJECT_OK"
