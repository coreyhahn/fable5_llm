# bm1_exoneration.tcl <routed_dcp> <out_dir> — BM1-T3 fix round 1, READ-ONLY.
# The complete (not 144-printed-paths) check of whether ANY failing setup/hold
# endpoint of a routed roll starts or ends inside bd_i/seq_0 (the counters' block)
# or passes through a mv_busy_bm net.  open_checkpoint + timing queries +
# report_timing only: no place/route/phys_opt/write_checkpoint/write_bitstream.
# Report files go to <out_dir> (a FRESH dir); every count is also printed.
if {[llength $argv] < 2} { puts "FATAL: need <routed_dcp> <out_dir>"; exit 1 }
set DCP [lindex $argv 0]; set OUT [lindex $argv 1]
if {[file exists $OUT]} { puts "FATAL: $OUT exists — fresh dir only"; exit 1 }
file mkdir $OUT
open_checkpoint $DCP
puts "EX_DCP: $DCP"
set seq  [get_cells -hier -quiet -filter {IS_PRIMITIVE && NAME =~ bd_i/seq_0/*}]
set nets [get_nets -hier -quiet -filter {NAME =~ *mv_busy_bm*}]
puts "EX_SEQ0_PRIMITIVES: [llength $seq]"
puts "EX_MVBUSY_NETS: [llength $nets]"
foreach n $nets { puts "EX_MVBUSY_NET: $n" }
proc incell {pin} {
    if {$pin eq ""} { return 0 }
    return [string match "bd_i/seq_0/*" [get_property NAME $pin]]
}
foreach mode {setup hold} {
    # ALL failing endpoints: -nworst 1 gives one path per endpoint; max_paths is
    # raised until the count stops growing (printed for each cap).
    set prev -1
    foreach cap {5000 50000 500000} {
        set ps [get_timing_paths -$mode -slack_lesser_than 0 -max_paths $cap -nworst 1 -quiet]
        set n [llength $ps]
        puts "EX_${mode}_FAILING_PATHS cap=$cap count=$n"
        if {$n == $prev || $n < $cap} { break }
        set prev $n
    }
    set in_seq 0
    foreach p $ps {
        if {[incell [get_property STARTPOINT_PIN $p]] || [incell [get_property ENDPOINT_PIN $p]]} { incr in_seq }
    }
    puts "EX_${mode}_FAILING_START_OR_END_IN_SEQ0: $in_seq of [llength $ps]"
    set thr [get_timing_paths -$mode -slack_lesser_than 0 -through $nets -max_paths 500000 -nworst 1 -quiet]
    puts "EX_${mode}_FAILING_THROUGH_MVBUSY: [llength $thr]"
    set to  [get_timing_paths -$mode -slack_lesser_than 0 -to   $seq -max_paths 500000 -nworst 1 -quiet]
    set fr  [get_timing_paths -$mode -slack_lesser_than 0 -from $seq -max_paths 500000 -nworst 1 -quiet]
    puts "EX_${mode}_FAILING_TO_SEQ0: [llength $to]"
    puts "EX_${mode}_FAILING_FROM_SEQ0: [llength $fr]"
    foreach {tag sel} [list to [list -to $seq] from [list -from $seq] through [list -through $nets]] {
        set w [get_timing_paths -$mode {*}$sel -max_paths 1 -nworst 1 -quiet]
        set s [expr {[llength $w] ? [get_property SLACK $w] : "none"}]
        puts "EX_${mode}_WORST_${tag}: slack=$s"
        set f $OUT/${mode}_${tag}.rpt
        report_timing -$mode {*}$sel -max_paths 10 -nworst 1 -file $f
        puts "EX_${mode}_REPORT_${tag}: $f"
        puts [report_timing -$mode {*}$sel -max_paths 10 -nworst 1 -return_string]
    }
}
puts "EX_DONE"
