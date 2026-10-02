# g5b_physopt_playbook.tcl <src_dcp> <out_dir> — the house closure playbook's
# LAST step, run on Task 14's best roll.
#
# WHY A COPY AND NOT AN EDIT, for the third time in this task.
# synth/scripts/po_035.tcl is this playbook, and it HARDCODES build_035's
# checkpoint and out dir (`set SRC …/out_build_035_full_AltSpreadLogic_high/…`,
# `set OUT …/out_build_035_po`).  It is cited by evidence/qwen2b/rc/TIMING_035.md
# section 13.5 as the script that produced build_035's closure, so editing it to
# take arguments would move a record this task has no business moving.  This is
# that script with the two paths taken as arguments and NOTHING else changed:
# the same four directives in the same order, the same hold guard, the same
# best-checkpoint bookkeeping, the same `route_design -preserve` at the end, the
# same refusal to emit a bitstream unless BOTH WNS and WHS are non-negative.
#
# The markers are renamed PO035_* -> POPB_* so a log from this script can never
# be mistaken for one from build_035's.
#
# WHAT THIS STEP IS FOR.  The full recipe already spent AggressiveExplore at
# both phys_opt stages, so this sweeps the directives that were NOT spent —
# exactly what build_034's iteration 3 and build_035's closure did.  On the 2B
# design this move closed -0.091 -> 0.000.
#
#   vivado -mode batch -nojournal -source g5b_physopt_playbook.tcl \
#       -tclargs <src_routed_dcp> <out_dir>

if {[llength $argv] < 2} { puts "FATAL: need <src_dcp> <out_dir>"; exit 1 }
set SRC [lindex $argv 0]
set OUT [lindex $argv 1]
if {![file exists $SRC]} { puts "FATAL: no checkpoint at $SRC"; exit 1 }
file mkdir $OUT/reports

open_checkpoint $SRC
proc wns {} { return [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]] }
proc whs {} { return [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]] }
set best [wns]
puts "POPB_SRC: $SRC"
puts "POPB_PASS0: WNS=$best WHS=[whs]"
write_checkpoint -force $OUT/best.dcp

foreach d {AlternateReplication AggressiveFanoutOpt Explore AggressiveExplore} {
    if {[catch {phys_opt_design -directive $d} err]} { puts "POPB_WARN: $d: $err"; continue }
    set w [wns]; set h [whs]
    puts "POPB_AFTER_$d: WNS=$w WHS=$h"
    if {$h < 0} { puts "POPB_HOLD_REGRESSION on $d (WHS=$h) — stopping, not accepting negative hold"; break }
    if {$w > $best} { set best $w; write_checkpoint -force $OUT/best.dcp; puts "POPB_NEWBEST: $best" }
}

open_checkpoint $OUT/best.dcp
if {[catch {route_design -preserve} err]} { puts "POPB_WARN route: $err" }
set w [wns]; set h [whs]
puts "POPB_FINAL: WNS=$w WHS=$h"
report_timing_summary -file $OUT/reports/timing_summary.rpt
report_utilization    -file $OUT/reports/utilization.rpt
report_utilization -hierarchical -file $OUT/reports/utilization_hier.rpt
write_checkpoint -force $OUT/bd_wrapper_po_routed.dcp
if {$w >= 0 && $h >= 0} {
    write_bitstream -force $OUT/bd_wrapper.bit
    puts "POPB_BITSTREAM: $OUT/bd_wrapper.bit"
    puts "POPB_CLOSED"
} else { puts "POPB_NOT_CLOSED" }
