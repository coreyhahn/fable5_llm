# incr_impl.tcl <proj_xpr> <place_directive> <ref_dcp> <incr_directive> [<extra_xdc>...]
# — the FULL ckr2 recipe of full_impl.tcl (place -directive D, POST-PLACE and
# POST-ROUTE phys_opt AggressiveExplore, implementation-only XDCs), run as an
# INCREMENTAL implementation against a reference routed checkpoint (spec
# docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md §4.3; Task SR1).
# A NEW file beside full_impl.tcl; full_impl.tcl is not edited.
#
# Project mode, because the ckr2 recipe is project mode (launch_po2.sh rsyncs a
# built proj/ and full_impl.tcl re-runs impl_1): synth_1's bd_wrapper.dcp is a
# 0.6 MB top whose OOC IP netlists only the run's link_design assembles.
# Property names VERIFIED from Vivado 2024.2 itself before first use
# (evidence/qwen9b/sr/n001_SR1_vivado_help_probe.log): impl_1 carries
# INCREMENTAL_CHECKPOINT (file), INCREMENTAL_CHECKPOINT.DIRECTIVE (string),
# INCREMENTAL_CHECKPOINT.MORE_OPTIONS, AUTO_INCREMENTAL_CHECKPOINT (bool);
# read_checkpoint -incremental -directive takes RuntimeOptimized (default) |
# TimingClosure | Quick; report_incremental_reuse takes -hierarchical and
# -hierarchical_depth.
#
# SR1 fix round 1: (a) the reuse hook is a place_design TCL.POST, not .PRE (the
# project run sources .PRE BEFORE its own read_checkpoint -incremental, so a
# .PRE report sees no reference: runme.log printed Vivado_Tcl 4-1062 "Incremental
# flow is disabled" twice and wrote nothing); (b) an incremental -directive
# OVERRIDES the place / post-place phys_opt / route directives (Vivado 12-9151),
# so the summary prints REQUESTED and EFFECTIVE directives, the latter read
# from the run's own runme.log by sr_effective_directives below.

# sr_effective_directives <runme.log> — the directives the run ACTUALLY used,
# from the tool's own messages, as a "k=v k=v ..." string:
#   place         Place 46-44 "place_design is using directive X", else the
#                 place_design Command line's -directive, else Default
#   route         Route 35-559 "route_design is using directive X", else the
#                 route_design Command line's -directive, else Default
#   phys_opt_post_place / phys_opt_post_route: the -directive of the
#                 phys_opt_design Command before / after route_design; the
#                 post-place one is reported as UNNAMED(12-9151 override of X)
#                 when Vivado 12-9151 is in the log, because the tool names no
#                 effective directive for it (SR1 runme.log: none printed).
#   incr_override yes/no — whether Vivado 12-9151 appeared.
proc sr_effective_directives {log} {
    if {![file exists $log]} { return "UNKNOWN(no runme.log: $log)" }
    set fh [open $log r]; set txt [read $fh]; close $fh
    set ovr [regexp {\[Vivado 12-9151\]} $txt]
    set place Default; set route Default; set pp NONE; set pr NONE
    if {[regexp {\[Place 46-44\] place_design is using directive (\S+)} $txt -> d]} {
        set place $d
    } elseif {[regexp {Command: place_design[^\n]*-directive (\S+)} $txt -> d]} { set place $d }
    if {[regexp {\[Route 35-559\] route_design is using directive (\S+)} $txt -> d]} {
        set route $d
    } elseif {[regexp {Command: route_design[^\n]*-directive (\S+)} $txt -> d]} { set route $d }
    set rpos [string first "Command: route_design" $txt]
    foreach idx [regexp -all -inline -indices {Command: phys_opt_design[^\n]*} $txt] {
        set line [string range $txt [lindex $idx 0] [lindex $idx 1]]
        set dir Default
        regexp -- {-directive (\S+)} $line -> dir
        if {$rpos < 0 || [lindex $idx 0] < $rpos} {
            set pp [expr {$ovr ? "UNNAMED(12-9151_override_of_$dir)" : $dir}]
        } else {
            set pr $dir
        }
    }
    return "place=$place phys_opt_post_place=$pp route=$route phys_opt_post_route=$pr incr_override=[expr {$ovr ? "yes" : "no"}]"
}
# A no-launch check sets ::INCR_IMPL_PROCS_ONLY and sources this file for the
# proc alone; nothing below runs then.
if {[info exists ::INCR_IMPL_PROCS_ONLY]} { return }

set xpr       [lindex $argv 0]
set directive [lindex $argv 1]
set ref_dcp   [lindex $argv 2]
set idir      [lindex $argv 3]
set extra_xdcs {}
foreach a [lrange $argv 4 end] { if {$a ne ""} { lappend extra_xdcs $a } }
set popt      AggressiveExplore
if {![file exists $ref_dcp]} { puts "FATAL: reference dcp not found: $ref_dcp"; exit 1 }
puts "INCR_REF: $ref_dcp size=[file size $ref_dcp] mtime=[clock format [file mtime $ref_dcp] -format {%Y-%m-%dT%H:%M:%S}]"

open_project $xpr
set od [file normalize [file dirname [file dirname $xpr]]]
file mkdir $od/reports

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
# The incremental part. AUTO off: the standard -incremental mode, not the
# tool-decides mode. No -force_incr: if the tool's own criteria reject the
# reference it falls back to a default placement, and the log says so.
set_property AUTO_INCREMENTAL_CHECKPOINT      0         $r
set_property INCREMENTAL_CHECKPOINT           $ref_dcp  $r
set_property INCREMENTAL_CHECKPOINT.DIRECTIVE $idir     $r
# The reuse as placed: flat + hierarchical reuse reports written by a POST hook
# on place_design (after the run's read_checkpoint -incremental and incremental
# placement; a .PRE hook runs before that read and reports nothing — SR1 fix 1).
# The hook file is generated here into the out dir; each call is caught so a
# failing report cannot fail the implementation run.
set hook $od/incr_hook_postplace.tcl
set fh [open $hook w]
puts $fh "if {\[catch {report_incremental_reuse -file $od/reports/incr_reuse_postplace.rpt} e\]} { puts \"INCR_HOOK_ERR flat: \$e\" }"
puts $fh "if {\[catch {report_incremental_reuse -hierarchical -hierarchical_depth 6 -file $od/reports/incr_reuse_postplace_hier.rpt} e\]} { puts \"INCR_HOOK_ERR hier: \$e\" }"
close $fh
set_property STEPS.PLACE_DESIGN.TCL.POST $hook $r
foreach p {AUTO_INCREMENTAL_CHECKPOINT INCREMENTAL_CHECKPOINT INCREMENTAL_CHECKPOINT.DIRECTIVE STEPS.PLACE_DESIGN.TCL.POST} {
    puts "INCR_PROP: $p = '[get_property $p $r]'"
}
set rroute [get_property STEPS.ROUTE_DESIGN.ARGS.DIRECTIVE $r]
set requested "place=$directive phys_opt_post_place=$popt route=$rroute phys_opt_post_route=$popt"
puts "FULL_IMPL_CFG: place=$directive phys_opt=$popt (post-place AND post-route enabled) incremental=$idir (REQUESTED; see EFFECTIVE_DIRECTIVES after the run)"

reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 12
wait_on_run impl_1
if {[get_property PROGRESS $r] ne "100%"} { puts "FATAL: impl_1 did not complete"; exit 1 }

open_run impl_1
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
set effective [sr_effective_directives [file join [get_property DIRECTORY $r] runme.log]]
puts "EFFECTIVE_DIRECTIVES: $effective"
puts "TIMING: WNS=$wns WHS=$whs REQUESTED={$requested} EFFECTIVE={$effective} RECIPE=full+incr($idir) XDC=[expr {$extra_xdc eq "" ? "none" : $extra_xdc}]"
set pbs [get_pblocks -quiet]
puts "PBLOCK_COUNT: [llength $pbs]"
foreach pb $pbs {
    set cells [get_cells -quiet -of_objects $pb]
    puts [format "PBLOCK %s cells=%d range={%s}" $pb [llength $cells] [get_property GRID_RANGES $pb]]
}
if {$whs < 0} {
    puts "WHS_GATE: NEGATIVE whs=$whs — DO NOT SHIP THIS ROLL WITHOUT A HOLD WAIVER"
} else {
    puts "WHS_GATE: OK whs=$whs"
}
report_timing_summary -file $od/reports/timing_summary.rpt
report_utilization    -file $od/reports/utilization.rpt
report_utilization -hierarchical -file $od/reports/utilization_hier.rpt
report_drc -file $od/reports/drc.rpt
# The post-route reuse, if the opened run still carries the reference.
if {[catch {report_incremental_reuse -hierarchical -hierarchical_depth 6 -file $od/reports/incr_reuse_routed_hier.rpt} e]} {
    puts "INCR_REUSE_ROUTED: not available on the opened run ($e)"
} else {
    puts "INCR_REUSE_ROUTED: $od/reports/incr_reuse_routed_hier.rpt"
}
puts "BUILD_OK"
