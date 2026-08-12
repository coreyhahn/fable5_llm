# reroll_impl_xdc.tcl <proj_xpr> <place_directive> <extra_xdc> — like
# reroll_impl.tcl but first adds an implementation-only XDC (e.g. MCP
# exceptions) to the project, then re-place/routes the same netlist.
set xpr       [lindex $argv 0]
set directive [lindex $argv 1]
set xdc       [lindex $argv 2]

open_project $xpr
add_files -fileset constrs_1 -norecurse $xdc
set_property USED_IN_SYNTHESIS false [get_files $xdc]
set_property STEPS.PLACE_DESIGN.ARGS.DIRECTIVE $directive [get_runs impl_1]
reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 16
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {
    puts "FATAL: impl_1 did not complete"
    exit 1
}
open_run impl_1
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
puts "TIMING: WNS=$wns WHS=$whs DIRECTIVE=$directive XDC=$xdc"
puts "BUILD_OK"
