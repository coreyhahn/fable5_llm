# Dump all params of an XDMA cell configured exactly as build_005's.
create_project -in_memory -part xcvu9p-fsgd2104-2L-e
create_bd_design "probe2"
create_bd_cell -type ip -vlnv xilinx.com:ip:xdma:4.1 xdma_0
set_property -dict [list CONFIG.mode_selection {Advanced}] [get_bd_cells xdma_0]
set_property -dict [list \
    CONFIG.pl_link_cap_max_link_width {X8} \
    CONFIG.pl_link_cap_max_link_speed {8.0_GT/s} \
] [get_bd_cells xdma_0]
set_property -dict [list \
    CONFIG.axi_data_width {256_bit} \
    CONFIG.axisten_freq {250} \
    CONFIG.en_gt_selection {true} \
    CONFIG.select_quad {GTY_Quad_227} \
    CONFIG.axilite_master_en {true} \
    CONFIG.xdma_pcie_64bit_en {true} \
] [get_bd_cells xdma_0]
set fh [open xdma_params_mine.txt w]
foreach p [list_property [get_bd_cells xdma_0]] {
    if {[string match CONFIG.* $p]} {
        puts $fh "$p = [get_property $p [get_bd_cells xdma_0]]"
    }
}
close $fh
puts "PROBE2_DONE"
