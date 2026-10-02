# bm1_jtag_list.tcl — BM1-T4: READ-ONLY JTAG census through snoke's hw_server.
# Lists hw_targets and hw_devices (no programming, no flash, no config).
# Usage (snoke): vivado -mode batch -nojournal -nolog -source evidence/qwen9b/bm/bm1_jtag_list.tcl
open_hw_manager
connect_hw_server -url localhost:3121
set tg [get_hw_targets]
puts "JTAG_TARGETS: [llength $tg] :: $tg"
foreach t $tg {
    if {[catch {open_hw_target $t} e]} { puts "JTAG_OPEN_FAIL: $t :: $e"; continue }
    foreach d [get_hw_devices] {
        puts "JTAG_DEVICE: $t :: $d  part=[get_property PART $d]  idcode=[get_property IDCODE_HEX $d]  done=[get_property REGISTER.CONFIG_STATUS.BIT14_DONE_PIN $d]"
    }
    close_hw_target $t
}
set vu [llength [get_hw_targets]]
puts "JTAG_LIST_DONE"
