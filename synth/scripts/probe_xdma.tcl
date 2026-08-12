create_project -in_memory -part xcvu9p-fsgd2104-2L-e
create_bd_design "probe"
create_bd_cell -type ip -vlnv xilinx.com:ip:xdma:4.1 xdma_0
set fh [open xdma_params.txt w]
foreach p [list_property [get_bd_cells xdma_0]] {
    if {[string match CONFIG.* $p]} {
        puts $fh "$p = [get_property $p [get_bd_cells xdma_0]]"
    }
}
close $fh
puts "PROBE_DONE"
