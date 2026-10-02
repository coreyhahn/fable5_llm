# sr0_ip_query.tcl — Task SR0 fix round 1 (I2): READ-ONLY query of what the
# DDR4 and XDMA IPs allow, from the IPs themselves, on the shipped build's
# project.  Opens synth/out_build_041/proj/stage1.xpr with -read_only, opens
# its block design, prints properties, and closes WITHOUT saving.  No run is
# launched, no checkpoint is opened, nothing is written to the project.
#
#   source /home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh
#   vivado -mode batch -nojournal -nolog -source evidence/qwen9b/ov/sr0_ip_query.tcl
set xpr [file normalize [file join [file dirname [info script]] ../../../synth/out_build_041/proj/stage1.xpr]]
puts "IPQ_XPR: $xpr"
open_project -read_only $xpr
set bd [lindex [get_files -quiet *.bd] 0]
puts "IPQ_BD: $bd"
open_bd_design $bd

proc show {cell prop} {
    set c [get_bd_cells $cell]
    set v [get_property $prop $c]
    set allowed "?"
    if {[catch {set allowed [list_property_value $prop $c]} e]} { set allowed "list_property_value failed: $e" }
    puts "IPQ_PROP: $cell $prop value={$v} allowed={$allowed}"
}

foreach p {CONFIG.C0.DDR4_TimePeriod CONFIG.C0.DDR4_InputClockPeriod CONFIG.C0.DDR4_CLKOUT0_DIVIDE CONFIG.C0.DDR4_MemoryPart CONFIG.C0.DDR4_Mem_Add_Map} {
    if {[catch {show ddr4_0 $p} e]} { puts "IPQ_ERR: ddr4_0 $p: $e" }
}
# the ddr4_0 properties whose NAME mentions period / clock / speed, for completeness
foreach p [lsort [list_property [get_bd_cells ddr4_0]]] {
    if {[regexp -nocase {period|clk|clock|speed|freq} $p]} {
        puts "IPQ_DDR4_PROP: $p = {[get_property $p [get_bd_cells ddr4_0]]}"
    }
}
foreach p {CONFIG.axisten_freq CONFIG.axi_data_width CONFIG.pl_link_cap_max_link_width CONFIG.pl_link_cap_max_link_speed} {
    if {[catch {show xdma_0 $p} e]} { puts "IPQ_ERR: xdma_0 $p: $e" }
}
close_bd_design [get_bd_designs]
close_project
puts "IPQ_DONE"
