# check_pblocks.tcl — G5a Step 1 pre-flight: prove the floorplan candidates'
# cell patterns MATCH before spending an hour of place_design on them.
# "A pblock that failed to match any cell is silently harmless in Vivado, which
# is exactly how a floorplan campaign can measure nothing"
# (synth/scripts/full_impl.tcl:50-52).
#
#   vivado -mode batch -nojournal -source check_pblocks.tcl -tclargs <dcp> <xdc> [<xdc> ...]
#
# The DCP is opened READ-ONLY (nothing is written back into its directory).
if {[llength $argv] < 2} { puts "FATAL: need <dcp> <xdc> \[<xdc> ...\]"; exit 1 }
set Dcp [lindex $argv 0]
open_checkpoint $Dcp
puts "CHK_DCP: $Dcp"
puts "CHK_TOP: [get_property TOP [current_design]]"
puts "CHK_CELLS_TOTAL: [llength [get_cells -quiet -hier]]"
puts "CHK_URAM_TOTAL: [llength [get_cells -quiet -hier -filter {REF_NAME =~ URAM288*}]]"
foreach x [lrange $argv 1 end] {
    puts "CHK_XDC: $x"
    if {[catch {read_xdc $x} err]} { puts "CHK_XDC_ERROR: $err" ; continue }
}
set empty 0
foreach pb [get_pblocks -quiet] {
    set cells [get_cells -quiet -of_objects $pb]
    set u 0
    foreach c $cells { if {[string match URAM288* [get_property REF_NAME $c]]} { incr u } }
    puts [format "CHK_PBLOCK %-14s cells=%-7d uram=%-4d range={%s}" \
        $pb [llength $cells] $u [get_property GRID_RANGES $pb]]
    if {[llength $cells] == 0} { incr empty }
}
puts "CHK_EMPTY_PBLOCKS: $empty"
puts "CHK_DONE"
