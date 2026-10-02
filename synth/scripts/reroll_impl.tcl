# reroll_impl.tcl <proj_xpr> <place_directive> — re-place/route an existing
# synthesized project with a different placer directive (same netlist, same
# constraints, ELF associations preserved). For closing route-noise WNS.
#
# SUPERSEDED 2026-08-22 (R-c task 5). DO NOT USE FOR NEW ROLLS.  This script
# enables NEITHER phys_opt stage, which costs a measured +0.040 … +0.100 ns of
# WNS per roll (n=3 same-directive pairs, evidence/qwen2b/rb/TIMING.md §7
# finding 1).  Use synth/scripts/full_impl.tcl via launch_po2.sh instead.
# Retained only so the historical out_*_rr_* rolls stay reproducible.
set xpr [lindex $argv 0]
set directive [lindex $argv 1]

open_project $xpr
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
puts "TIMING: WNS=$wns WHS=$whs DIRECTIVE=$directive"
puts "BUILD_OK"
