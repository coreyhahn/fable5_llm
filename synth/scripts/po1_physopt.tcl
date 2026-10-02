# po1_physopt.tcl — post-route phys_opt on the Explore roll (playbook finisher).
set RR   /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_034_rr_Explore
set OUT  /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_034_po1
file mkdir $OUT/reports

open_checkpoint $RR/proj/stage1.runs/impl_1/bd_wrapper_routed.dcp
puts "PO1_PASS0: WNS=[get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]] WHS=[get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]"

foreach d {AggressiveExplore AlternateReplication AggressiveFanoutOpt} {
    if {[catch {phys_opt_design -directive $d} err]} {
        puts "PO1_WARN: phys_opt $d failed: $err"
        continue
    }
    set w [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
    set h [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
    puts "PO1_AFTER_$d: WNS=$w WHS=$h"
}

# repair any nets phys_opt left unrouted, preserving existing routing
if {[catch {route_design -preserve} err]} { puts "PO1_WARN: route_design -preserve: $err" }
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
puts "PO1_FINAL: WNS=$wns WHS=$whs"

report_timing_summary -file $OUT/reports/timing_summary.rpt
report_utilization    -file $OUT/reports/utilization.rpt
write_checkpoint -force $OUT/bd_wrapper_po1_routed.dcp

if {$wns >= 0 && $whs >= 0} {
    write_bitstream -force $OUT/bd_wrapper.bit
    puts "PO1_BITSTREAM: $OUT/bd_wrapper.bit"
    puts "PO1_CLOSED"
} else {
    puts "PO1_NOT_CLOSED"
}
puts "PO1_DONE"
