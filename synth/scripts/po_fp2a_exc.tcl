# po_fp2a_exc.tcl — closure playbook on the floorplan winner (fp2a, variant A:
# mvchan channel affinity only), which routed to WNS -0.004 / WHS 0.000.
#
# -0.004 is 4 ps: one or two endpoints, well inside phys_opt reach. The full
# recipe already spent AggressiveExplore at both phys_opt stages, so this
# sweeps the directives that were NOT spent, exactly as po_035.tcl did on
# build_035 (where the same sweep bought +0.004 -- which is all that is needed
# here).
#
# HOLD GUARD: hold margin is 0.000, so ANY pass that drives WHS negative stops
# the sweep. We are not trading setup for hold at this margin.
#
# Unlike the full recipe, this writes a bitstream ONLY on closure (WNS >= 0 and
# WHS >= 0), so the presence of $OUT/bd_wrapper.bit is itself the pass signal.
set SRC /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_035_fp2a_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp
set OUT /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_035_fp2a_exc_po
file mkdir $OUT/reports

open_checkpoint $SRC
# The exception is analysis-only, but it must be in force BEFORE the sweep so
# phys_opt spends its effort on the REAL critical paths instead of the vendor
# reset-synchronizer recovery checks it structurally cannot fix.
read_xdc /home/cah/r2d2/code/fpga/fable5_llm/synth/constraints/fable5_xdma_rst_exception.xdc
puts "POEX_EXCEPTION_READ_OK"
proc wns {} { return [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]] }
proc whs {} { return [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]] }
set best [wns]
puts "POEX_PASS0: WNS=$best WHS=[whs]"
write_checkpoint -force $OUT/best.dcp

foreach d {AlternateReplication AggressiveFanoutOpt Explore AggressiveExplore} {
    if {[catch {phys_opt_design -directive $d} err]} { puts "POEX_WARN: $d: $err"; continue }
    set w [wns]; set h [whs]
    puts "POEX_AFTER_$d: WNS=$w WHS=$h"
    if {$h < 0} { puts "POEX_HOLD_REGRESSION on $d (WHS=$h) — stopping, not accepting negative hold"; break }
    if {$w > $best} { set best $w; write_checkpoint -force $OUT/best.dcp; puts "POEX_NEWBEST: $best" }
}

open_checkpoint $OUT/best.dcp
if {[catch {route_design -preserve} err]} { puts "POEX_WARN route: $err" }
set w [wns]; set h [whs]
puts "POEX_FINAL: WNS=$w WHS=$h"
report_timing_summary -file $OUT/reports/timing_summary.rpt
report_utilization    -file $OUT/reports/utilization.rpt
report_utilization -hierarchical -file $OUT/reports/utilization_hier.rpt
write_checkpoint -force $OUT/bd_wrapper_po_routed.dcp
if {$w >= 0 && $h >= 0} {
    write_bitstream -force $OUT/bd_wrapper.bit
    puts "POEX_BITSTREAM: $OUT/bd_wrapper.bit"
    puts "POEX_CLOSED"
} else { puts "POEX_NOT_CLOSED" }
puts "POEX_DONE"
