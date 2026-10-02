# po_035.tcl — closure playbook iteration on build_035's best full-recipe roll
# (AltSpreadLogic_high, WNS -0.136 / WHS +0.001).  Lineage: po3_physopt.tcl,
# with the same HOLD GUARD (hold margin is only +0.001, so any pass that drives
# WHS negative stops the sweep rather than trading setup for hold).
#
# The full recipe already spent AggressiveExplore at both phys_opt stages, so
# this sweeps the directives that were NOT spent, exactly as build_034's
# iteration 3 did.
set SRC /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_035_full_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp
set OUT /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_035_po
file mkdir $OUT/reports

open_checkpoint $SRC
proc wns {} { return [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]] }
proc whs {} { return [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]] }
set best [wns]
puts "PO035_PASS0: WNS=$best WHS=[whs]"
write_checkpoint -force $OUT/best.dcp

foreach d {AlternateReplication AggressiveFanoutOpt Explore AggressiveExplore} {
    if {[catch {phys_opt_design -directive $d} err]} { puts "PO035_WARN: $d: $err"; continue }
    set w [wns]; set h [whs]
    puts "PO035_AFTER_$d: WNS=$w WHS=$h"
    if {$h < 0} { puts "PO035_HOLD_REGRESSION on $d (WHS=$h) — stopping, not accepting negative hold"; break }
    if {$w > $best} { set best $w; write_checkpoint -force $OUT/best.dcp; puts "PO035_NEWBEST: $best" }
}

open_checkpoint $OUT/best.dcp
if {[catch {route_design -preserve} err]} { puts "PO035_WARN route: $err" }
set w [wns]; set h [whs]
puts "PO035_FINAL: WNS=$w WHS=$h"
report_timing_summary -file $OUT/reports/timing_summary.rpt
report_utilization    -file $OUT/reports/utilization.rpt
report_utilization -hierarchical -file $OUT/reports/utilization_hier.rpt
write_checkpoint -force $OUT/bd_wrapper_po_routed.dcp
if {$w >= 0 && $h >= 0} {
    write_bitstream -force $OUT/bd_wrapper.bit
    puts "PO035_BITSTREAM: $OUT/bd_wrapper.bit"
    puts "PO035_CLOSED"
} else { puts "PO035_NOT_CLOSED" }
puts "PO035_DONE"
