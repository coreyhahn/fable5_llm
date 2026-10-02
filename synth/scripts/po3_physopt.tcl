# po3_physopt.tcl — iteration 3: further post-route phys_opt on the po2
# AltSpreadLogic_high checkpoint (already AggressiveExplore'd; -0.025/+0.001).
# HOLD GUARD: WHS margin is only +0.001 — abort if any pass drives WHS negative.
set SRC /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_034_po2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp
set OUT /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_034_po3
file mkdir $OUT/reports

open_checkpoint $SRC
proc wns {} { return [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]] }
proc whs {} { return [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]] }
set best [wns]
puts "PO3_PASS0: WNS=$best WHS=[whs]"
write_checkpoint -force $OUT/best.dcp

foreach d {AlternateReplication AggressiveFanoutOpt Explore} {
    if {[catch {phys_opt_design -directive $d} err]} { puts "PO3_WARN: $d: $err"; continue }
    set w [wns]; set h [whs]
    puts "PO3_AFTER_$d: WNS=$w WHS=$h"
    if {$h < 0} { puts "PO3_HOLD_REGRESSION on $d (WHS=$h) — stopping, not accepting negative hold"; break }
    if {$w > $best} { set best $w; write_checkpoint -force $OUT/best.dcp; puts "PO3_NEWBEST: $best" }
}

open_checkpoint $OUT/best.dcp
if {[catch {route_design -preserve} err]} { puts "PO3_WARN route: $err" }
set w [wns]; set h [whs]
puts "PO3_FINAL: WNS=$w WHS=$h"
report_timing_summary -file $OUT/reports/timing_summary.rpt
report_utilization    -file $OUT/reports/utilization.rpt
write_checkpoint -force $OUT/bd_wrapper_po3_routed.dcp
if {$w >= 0 && $h >= 0} {
    write_bitstream -force $OUT/bd_wrapper.bit
    puts "PO3_BITSTREAM: $OUT/bd_wrapper.bit"
    puts "PO3_CLOSED"
} else { puts "PO3_NOT_CLOSED" }
puts "PO3_DONE"
