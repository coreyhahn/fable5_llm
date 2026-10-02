# sr14_fp_cover.tcl <routed_dcp> <out_dir> [<cell_globs> <exp_cells> <exp_groups>] — SR14 step 4 (R2-specific), READ-ONLY on the
# routed checkpoint: the false-path coverage check of the eight new mvchan registers
# csr_static_xbank / csr_static_rbank (SR12, rtl/matvec_chan.sv) by the quasi-static
# false path csr_static_* -> mmcm_clkout0* (synth/constraints/fable5_cdc.xdc:14-15),
# plus the SR12 SR14-checklist cones (x_line, row_in, g_q in each u_engine) and seq_0's
# own worst setup slack.  Nothing is written into any out dir: reports go to <out_dir>
# (a scratch dir the caller names), the checkpoint is opened, never saved.
#   FPC_CELLS n            the matched register cells (expected 8: 2 per mvchan)
#   FPC_GROUP mvchan_k x/r  per-group cell counts
#   FPC_EXC_*               report_exceptions -from those cells (quoted to the log)
#   FPC_UI_PATHS            setup+hold paths from them to the UI clocks: all false/inf (timed 0)
#   FPC_VERDICT COVERED|NOT_COVERED
# The optional filter / expected counts exist for the CONTROL runs only (n1402: the
# R1 checkpoint has no xbank/rbank registers, so the default filter matches nothing;
# a positive control points the same probe at a pre-existing csr_static_* register).
# Defaults: the xbank/rbank filter, 8 cells, 8 groups (one 1-bit register per
# mvchan per bank bit, rtl/matvec_chan.sv:231-232).
set dcp [lindex $argv 0]
set od  [lindex $argv 1]
set flt {NAME =~ */csr_static_xbank_reg* || NAME =~ */csr_static_rbank_reg*}
set expc 8; set expg 8
# <cell_globs>: comma-separated NAME globs, no spaces (a filter with spaces does not
# survive -tclargs word splitting: n1403's first attempt parsed {NAME as the filter).
if {[llength $argv] >= 5} {
    set parts {}
    foreach g [split [lindex $argv 2] ,] { lappend parts "NAME =~ $g" }
    set flt [join $parts " || "]; set expc [lindex $argv 3]; set expg [lindex $argv 4]
}
puts "FPC_FILTER: {$flt} expected cells=$expc groups=$expg"
file mkdir $od
open_checkpoint $dcp
puts "FPC_CHECKPOINT: $dcp size=[file size $dcp] mtime=[clock format [file mtime $dcp] -format {%Y-%m-%dT%H:%M:%S}]"
set c [get_cells -quiet -hierarchical -filter $flt]
puts "FPC_CELLS: [llength $c]"
array set grp {}
foreach x [lsort $c] {
    set cp [get_pins -quiet $x/C]
    set ck [get_clocks -quiet -of_objects $cp]
    puts "FPC_CELL $x REF=[get_property REF_NAME $x] clock={$ck}"
    set m ?; set k ?
    regexp {mvchan_(\d+)} $x -> m
    regexp {csr_static_([a-z0-9]+)_reg} $x -> k
    set key "mvchan_$m $k"
    if {![info exists grp($key)]} { set grp($key) 0 }
    incr grp($key)
}
foreach key [lsort [array names grp]] { puts "FPC_GROUP $key cells=$grp($key)" }
puts "FPC_GROUPS: [llength [array names grp]] (expected $expg)"
if {[llength $c] == 0} { puts "FPC_VERDICT: NOT_COVERED (no register matches the filter)"; puts "FPC_DONE"; exit 0 }
# The constraint's own -from set (the filter as written in fable5_cdc.xdc:14):
set statics [get_cells -quiet -hierarchical -filter {NAME =~ */csr_static_*_reg*}]
set inset 0
foreach x $c { if {[lsearch -exact $statics $x] >= 0} { incr inset } }
puts "FPC_STATICS_ALL: [llength $statics]; new registers inside the constraint's -from set: $inset of [llength $c]"
set ui [get_clocks -quiet -filter {NAME =~ mmcm_clkout0*}]
puts "FPC_UI_CLOCKS: $ui"
# Where the new registers' fanout lands (endpoint clocks) — the crossing they make.
foreach x [lsort $c] {
    set eps [all_fanout -quiet -from [get_pins -quiet $x/Q] -endpoints_only -flat]
    set eclk {}
    foreach e $eps {
        set ecell [get_cells -quiet -of_objects $e]
        set ecp [get_pins -quiet -filter {IS_CLOCK} -of_objects $ecell]
        foreach k [get_clocks -quiet -of_objects $ecp] { if {[lsearch -exact $eclk $k] < 0} { lappend eclk $k } }
    }
    puts "FPC_FANOUT $x endpoints=[llength $eps] endpoint_clocks={[lsort $eclk]}"
}
# report_exceptions scoped to the new registers (quoted in full to the log).
if {[catch {report_exceptions -from $c -file $od/fpc_report_exceptions_from.rpt} e]} {
    puts "FPC_EXC_FROM_ERR: $e"
} else {
    set fh [open $od/fpc_report_exceptions_from.rpt r]; set t [read $fh]; close $fh
    foreach l [split $t "\n"] { puts "FPC_EXC_FROM | $l" }
}
if {[catch {report_exceptions -from $c -to $ui -file $od/fpc_report_exceptions_from_to_ui.rpt} e]} {
    puts "FPC_EXC_FROM_TO_UI_ERR: $e"
} else {
    set fh [open $od/fpc_report_exceptions_from_to_ui.rpt r]; set t [read $fh]; close $fh
    foreach l [split $t "\n"] { puts "FPC_EXC_TO_UI | $l" }
}
# Paths from the registers to the UI clocks.  get_timing_paths DOES return a false-pathed
# crossing (n1404: slack inf, "Timing Exception: False Path"), so the check is that every
# such path is a false path with infinite slack, and that there are some (the crossing
# exists).  report_timing has no -unconstrained option in 2024.2 (n1404).
# (If the path object has no EXCEPTION property the tool's report_timing lines below,
# "Timing Exception: False Path", carry the name; nexempty counts those.)
set ntot 0; set nfalse 0; set bad 0; set nexempty 0
foreach dly {setup hold} {
    set tp [get_timing_paths -quiet -from $c -to $ui -$dly -max_paths 1000 -nworst 1]
    foreach p $tp {
        incr ntot
        set s [get_property SLACK $p]; set ex [get_property -quiet EXCEPTION $p]
        if {$ex eq ""} { incr nexempty }
        if {($s eq "" || $s eq "inf") && ($ex eq "" || [string match -nocase "*false*" $ex])} { incr nfalse } else {
            incr bad
            puts "FPC_TIMED $dly [get_property STARTPOINT_PIN $p] -> [get_property ENDPOINT_PIN $p] slack=$s exception={$ex}"
        }
    }
}
puts "FPC_UI_PATHS: total=$ntot false_path_inf=$nfalse timed=$bad (expected total > 0, timed 0); paths with no EXCEPTION property: $nexempty"
report_timing -from $c -to $ui -max_paths 10 -file $od/fpc_report_timing_to_ui.rpt
set fh [open $od/fpc_report_timing_to_ui.rpt r]; set t [read $fh]; close $fh
foreach l [split $t "\n"] { if {[regexp {No timing paths|Slack|Source:|Destination:|Timing Exception|Path Group|Requirement} $l]} { puts "FPC_RT | $l" } }
# Per register: its worst setup path into any UI clock, as the tool reports it.
foreach x [lsort $c] {
    set tp [get_timing_paths -quiet -from $x -to $ui -setup -max_paths 1 -nworst 1]
    foreach p $tp {
        puts "FPC_PATH $x -> [get_property ENDPOINT_PIN $p] slack=[get_property SLACK $p] exception={[get_property -quiet EXCEPTION $p]}"
    }
    if {[llength $tp] == 0} { puts "FPC_PATH $x -> (no path to a UI clock)" }
}
puts "FPC_TIMED_UI_PATHS_NOT_FALSE: $bad"
if {[llength $c] == $expc && [llength [array names grp]] == $expg && $inset == $expc && $ntot > 0 && $bad == 0} {
    puts "FPC_VERDICT: COVERED"
} else {
    puts "FPC_VERDICT: NOT_COVERED"
}
# SR12's SR14 checklist: the UI-clock cones R2 touches, worst setup per channel.
foreach pat {*u_engine/x_line_reg*/D *u_engine/row_in_reg*/D *u_engine/g_q_reg*/D *u_engine/g_cnt_reg*/D} {
    set ps [get_pins -quiet -hier -filter "NAME =~ $pat"]
    if {[llength $ps] == 0} { puts "FPC_CONE $pat: no pins"; continue }
    set tp [get_timing_paths -quiet -to $ps -setup -max_paths 1000 -nworst 1]
    array unset w; array set w {}
    foreach p $tp {
        set ep [get_property ENDPOINT_PIN $p]; set s [get_property SLACK $p]
        if {[regexp {mvchan_(\d+)} $ep -> m]} { if {![info exists w($m)] || $s < $w($m)} { set w($m) $s } }
    }
    set row ""
    foreach m [lsort [array names w]] { append row " mvchan_$m=$w($m)" }
    puts "FPC_CONE $pat pins=[llength $ps] worst_setup:$row"
}
# seq_0's own worst setup / hold (all of seq_0, and u_seq as final_verify's family).
foreach pat {*seq_0/*/D *seq_0*u_seq/*/D} {
    set ps [get_pins -quiet -hier -filter "NAME =~ $pat"]
    set ts [get_timing_paths -quiet -to $ps -setup -max_paths 1 -nworst 1]
    set th [get_timing_paths -quiet -to $ps -hold  -max_paths 1 -nworst 1]
    set ss [expr {[llength $ts] ? [get_property SLACK [lindex $ts 0]] : "none"}]
    set hs [expr {[llength $th] ? [get_property SLACK [lindex $th 0]] : "none"}]
    puts "FPC_SEQ0 $pat pins=[llength $ps] worst_setup=$ss worst_hold=$hs"
    if {[llength $ts]} { puts "FPC_SEQ0   from [get_property STARTPOINT_PIN [lindex $ts 0]] to [get_property ENDPOINT_PIN [lindex $ts 0]]" }
}
puts "FPC_DONE"
