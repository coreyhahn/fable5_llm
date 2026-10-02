# census_035.tcl <roll_dir> — per-ENDPOINT census of a routed roll, plus the
# two things RC_W8_GATE.md §"Still owed" demands of the R-c build:
#
#   1. `xline_q0_reg[*]/CE` reported BY NAME, whether or not it still violates.
#      That cone held build_034's 24 worst (waived) endpoints and is the one
#      the W8 rewrite touched (g_cnt 6->7 grew the compare by one bit), so
#      "it only cost one comparator bit" has to stop being an argument.
#   2. the per-module utilization of `u_engine` (the lane array price).
#
# Lineage: census_034_shipped.tcl, generalized to take the roll dir as an
# argument (that script hardcoded build_034's path) and with the SPLIT format
# string corrected — DATAPATH_DELAY is the TOTAL datapath delay, so
# route = datapath - logic (see TIMING.md §5's reading note).
#
# Usage: vivado -mode batch -nojournal -source census_035.tcl -tclargs <roll_dir>

if {[llength $argv] < 1} { puts "FATAL: need <roll_dir>"; exit 1 }
set D [lindex $argv 0]
set dcp $D/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp
if {![file exists $dcp]} {
    # the base roll runs the default strategy: no post-route phys_opt stage
    set dcp $D/proj/stage1.runs/impl_1/bd_wrapper_routed.dcp
}
if {![file exists $dcp]} { puts "FATAL: no routed checkpoint under $D"; exit 1 }
puts "CENSUS_CHECKPOINT: $dcp"
puts "CENSUS_CHECKPOINT_MTIME: [clock format [file mtime $dcp] -format {%Y-%m-%d %H:%M:%S}]"
open_checkpoint $dcp
file mkdir $D/reports

# ---------------------------------------------------------------- headline
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
puts "CENSUS_TIMING: WNS=$wns WHS=$whs"

# ------------------------------------------------- every failing setup path
set paths [get_timing_paths -max_paths 5000 -nworst 1 -setup -slack_lesser_than 0]
puts "CENSUS_COUNT: [llength $paths]"
puts "CENSUS_BEGIN"
foreach p $paths {
    puts [format "EP %7s %-22s lvl=%-3s %s <- %s" \
        [get_property SLACK $p] [get_property GROUP $p] \
        [get_property LOGIC_LEVELS $p] \
        [get_property ENDPOINT_PIN $p] [get_property STARTPOINT_PIN $p]]
}
puts "CENSUS_END"

# owner tally: which module hierarchy owns each failing endpoint
puts "OWNER_TALLY_BEGIN"
foreach p $paths {
    puts "OWNER [join [lrange [split [get_property ENDPOINT_PIN $p] /] 0 2] /]"
}
puts "OWNER_TALLY_END"

# deeper owner tally (5 levels) — separates u_dn / u_topk / u_engine etc.
puts "OWNER5_TALLY_BEGIN"
foreach p $paths {
    puts "OWNER5 [join [lrange [split [get_property ENDPOINT_PIN $p] /] 0 5] /]"
}
puts "OWNER5_TALLY_END"

# route-vs-logic split on the worst paths (route = datapath_total - logic)
foreach p [lrange $paths 0 3] {
    set dp [get_property DATAPATH_DELAY $p]
    set lg [get_property DATAPATH_LOGIC_DELAY $p]
    puts [format "SPLIT slack=%s logic=%s route=%.3f datapath_total=%s ep=%s" \
        [get_property SLACK $p] $lg [expr {$dp - $lg}] $dp \
        [get_property ENDPOINT_PIN $p]]
}

# ------------------------------------------- the xline_q0 CE cone, BY NAME
set xpins [get_pins -quiet -hier -filter {NAME =~ *u_engine/xline_q0_reg*/CE}]
puts "XLINE_CE_PIN_COUNT: [llength $xpins]"
if {[llength $xpins] > 0} {
    set xp [get_timing_paths -to $xpins -setup -max_paths 1000 -nworst 1]
    puts "XLINE_CE_PATH_COUNT: [llength $xp]"
    set worst 99.0
    set nneg 0
    array set chworst {}
    puts "XLINE_CE_BEGIN"
    set i 0
    foreach p $xp {
        set s [get_property SLACK $p]
        set ep [get_property ENDPOINT_PIN $p]
        if {$s < $worst} { set worst $s }
        if {$s < 0} { incr nneg }
        # bucket by mvchan index
        set ch "?"
        if {[regexp {mvchan_(\d+)} $ep -> m]} { set ch $m }
        if {![info exists chworst($ch)] || $s < $chworst($ch)} { set chworst($ch) $s }
        if {$i < 30} {
            puts [format "XLINE_CE %8s lvl=%-3s %s <- %s" $s \
                [get_property LOGIC_LEVELS $p] $ep [get_property STARTPOINT_PIN $p]]
        }
        incr i
    }
    puts "XLINE_CE_END"
    puts "XLINE_CE_WORST: $worst"
    puts "XLINE_CE_NEGATIVE_COUNT: $nneg"
    foreach ch [lsort [array names chworst]] {
        puts "XLINE_CE_WORST_mvchan_$ch: $chworst($ch)"
    }
    # route/logic split of the single worst xline CE path
    set p0 [lindex $xp 0]
    set dp [get_property DATAPATH_DELAY $p0]
    set lg [get_property DATAPATH_LOGIC_DELAY $p0]
    puts [format "XLINE_CE_SPLIT slack=%s logic=%s route=%.3f datapath_total=%s ep=%s" \
        [get_property SLACK $p0] $lg [expr {$dp - $lg}] $dp \
        [get_property ENDPOINT_PIN $p0]]
}

# ------------------------------------------------ per-module utilization
report_utilization -hierarchical -file $D/reports/census_utilization_hier.rpt
report_timing_summary -file $D/reports/census_timing_summary.rpt
puts "CENSUS_OK"
