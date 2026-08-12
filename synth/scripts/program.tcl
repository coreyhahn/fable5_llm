# program.tcl — JTAG-program a VOLATILE bitstream (never flash) on the
# BCU-1525 attached to snoke's hw_server.
# Usage: vivado -mode batch -source program.tcl -tclargs <bitfile>

if {[llength $argv] < 1} { puts "FATAL: need <bitfile>"; exit 1 }
set bit [file normalize [lindex $argv 0]]
if {![file exists $bit]} { puts "FATAL: $bit not found"; exit 1 }

open_hw_manager
connect_hw_server -url localhost:3121
open_hw_target
set dev [lindex [get_hw_devices xcvu9p*] 0]
if {$dev eq ""} { puts "FATAL: no xcvu9p device on JTAG"; exit 1 }
current_hw_device $dev
set_property PROGRAM.FILE $bit $dev
program_hw_devices $dev
refresh_hw_device $dev
puts "PROGRAM_OK: $bit"
