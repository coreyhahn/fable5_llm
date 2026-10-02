# full_impl.tcl <proj_xpr> <place_directive> [<extra_xdc>] — re-implement with
# the FULL 033-style recipe: place -directive D, POST-PLACE phys_opt, route,
# POST-ROUTE phys_opt. reroll_impl.tcl enables NEITHER phys_opt stage.
#
# The optional third argument adds an IMPLEMENTATION-ONLY XDC before the run
# (USED_IN_SYNTHESIS false), which is how the floorplan campaign applies
# synth/constraints/fable5_floorplan.xdc without touching synthesis or RTL.
# Omitting it reproduces the original two-argument behaviour exactly.
set xpr       [lindex $argv 0]
set directive [lindex $argv 1]
# argv 2 onward: zero or more implementation-only XDC files, applied in order.
# A LIST rather than a single file so the winning floorplan geometry
# (fable5_floorplan_a.xdc) stays byte-untouched while a separate exception file
# is layered on top, instead of the two being merged into one edited copy.
set extra_xdcs {}
foreach a [lrange $argv 2 end] { if {$a ne ""} { lappend extra_xdcs $a } }
set popt      AggressiveExplore

open_project $xpr

if {[llength $extra_xdcs] == 0} {
    puts "EXTRA_XDC: none"
} else {
    foreach x $extra_xdcs {
        if {![file exists $x]} { puts "FATAL: extra XDC not found: $x"; exit 1 }
        add_files -fileset constrs_1 -norecurse $x
        set_property USED_IN_SYNTHESIS false [get_files $x]
        puts "EXTRA_XDC: $x (implementation-only)"
    }
}
set extra_xdc [join $extra_xdcs ","]
set r [get_runs impl_1]
set_property STEPS.PLACE_DESIGN.ARGS.DIRECTIVE            $directive $r
set_property STEPS.PHYS_OPT_DESIGN.IS_ENABLED             true       $r
set_property STEPS.PHYS_OPT_DESIGN.ARGS.DIRECTIVE         $popt      $r
set_property STEPS.POST_ROUTE_PHYS_OPT_DESIGN.IS_ENABLED  true       $r
set_property STEPS.POST_ROUTE_PHYS_OPT_DESIGN.ARGS.DIRECTIVE $popt   $r
puts "FULL_IMPL_CFG: place=$directive phys_opt=$popt (post-place AND post-route enabled)"

reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 12
wait_on_run impl_1
if {[get_property PROGRESS $r] ne "100%"} { puts "FATAL: impl_1 did not complete"; exit 1 }

open_run impl_1
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
puts "TIMING: WNS=$wns WHS=$whs DIRECTIVE=$directive RECIPE=full XDC=[expr {$extra_xdc eq "" ? "none" : $extra_xdc}]"

# Floorplan sanity: prove the pblocks actually took, rather than assuming the
# XDC was read. A pblock that failed to match any cell is silently harmless in
# Vivado, which is exactly how a floorplan campaign can measure nothing.
set pbs [get_pblocks -quiet]
puts "PBLOCK_COUNT: [llength $pbs]"
foreach pb $pbs {
    set cells [get_cells -quiet -of_objects $pb]
    puts [format "PBLOCK %s cells=%d range={%s}" \
        $pb [llength $cells] [get_property GRID_RANGES $pb]]
}
# Hold gate. TIMING.md §7 finding 5: this is the script that builds what SHIPS,
# and it used to only *print* WHS, so build_034's +0.001 hold margin was an
# outcome rather than a checked property. Deliberately NON-fatal — aborting
# here would throw away a routed bitstream that may still be the best roll —
# but the verdict is now an explicit, greppable line.
if {$whs < 0} {
    puts "WHS_GATE: NEGATIVE whs=$whs — DO NOT SHIP THIS ROLL WITHOUT A HOLD WAIVER"
} else {
    puts "WHS_GATE: OK whs=$whs"
}
# NB: xpr is <out_dir>/proj/stage1.xpr, so TWO dirname levels, not three.
# (Three landed reports in synth/ where every parallel job raced last-writer-wins.)
set od [file dirname [file dirname $xpr]]
file mkdir $od/reports
report_timing_summary -file $od/reports/timing_summary.rpt
report_utilization    -file $od/reports/utilization.rpt
# -hierarchical is what prices a per-module change (e.g. the W8 lane array in
# matvec_engine); the flat report cannot separate it from the rest of the device.
report_utilization -hierarchical -file $od/reports/utilization_hier.rpt
puts "BUILD_OK"
