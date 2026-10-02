# sr1fix1_prop_probe.tcl <scratch_dir> — list impl_1's STEPS.PLACE_DESIGN.TCL.* properties
# on a throwaway project in a /tmp scratch dir (no run is launched).
set sd [lindex $argv 0]
create_project -force srh_probe $sd/srh_probe -part xcvu9p-fsgd2104-2L-e
set r [get_runs impl_1]
foreach p [lsort [list_property $r]] {
    if {[regexp {^STEPS\.PLACE_DESIGN\.TCL\.} $p]} { puts "SRP_PROP $p = '[get_property $p $r]'" }
}
close_project
puts "SRP_DONE"
