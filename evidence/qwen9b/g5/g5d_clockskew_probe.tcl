# g5d_clockskew_probe.tcl — Task 14-B's READ-ONLY clock-skew probe.
#
# WHY.  Task 14-A's design note section 7.3 recorded a term nobody had costed:
# every layer path carries `Clock Net Delay (Source) ~ 3.0-3.2 ns` on an aclk
# net with fo = 148,450, and the layer's own paths show `Clock Path Skew:
# -0.340 ns` (evidence/qwen9b/g5/063_t14a_po2_probe_dn_vdata.rpt:26) against
# -0.117 ... -0.169 elsewhere.  The note did not propose a change; it recorded
# that the term is there.  Task 14-B's brief item 4 makes it the one
# constraint-side arm, and says: PROBE FIRST, read-only, and only roll a
# clock-root constraint if the probe SUPPORTS one.
#
# WHAT THIS ANSWERS, and nothing else:
#   1. WHERE THE CLOCK ROOT IS.  Every global clock buffer in the design, its
#      LOC, the net it drives, that net's CLOCK_ROOT (the placer's choice) and
#      USER_CLOCK_ROOT (a constraint, empty unless one was applied), and the
#      net's load count.  A clock root is a CLOCK REGION coordinate XnYm.
#   2. WHERE THE LOADS ARE.  The clock-region histogram of layer_0's
#      dedicated blocks (DSP48E2 + URAM288 + RAMB36 — ~2,000 cells, exact and
#      cheap) and of each mvchan's engine, so "the root is in the wrong SLR"
#      is a measurement rather than a reading of one path's report.
#   3. WHAT IT COSTS ON THE PATHS.  full_clock_expanded reports for the worst
#      path in the design, the worst path ENDING in layer_0, and the worst
#      path ending in each mvchan, with their Clock Path Skew / SCD / DCD /
#      Clock Net Delay lines echoed back as greppable CSK_ markers.
#
# READ-ONLY: open_checkpoint + get_*/report_* only.  It writes the reports the
# caller names under evidence/ and changes nothing in the checkpoint.
#
#   vivado -mode batch -nojournal -source g5d_clockskew_probe.tcl \
#          -tclargs <routed.dcp> <out_prefix>

if {[llength $argv] < 2} { puts "FATAL: need <dcp> <out_prefix>"; exit 1 }
set DCP [lindex $argv 0]
set PRE [lindex $argv 1]
if {![file exists $DCP]} { puts "FATAL: no such checkpoint: $DCP"; exit 1 }
set_param general.maxThreads 8
puts "CSK_DCP: $DCP"
puts "CSK_DCP_MTIME: [clock format [file mtime $DCP] -format {%Y-%m-%d %H:%M:%S}]"
open_checkpoint $DCP
puts "CSK_WNS: [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]"

# ---------------------------------------------------------------- 1. the roots
report_clock_utilization -file ${PRE}_clock_util.rpt
puts "CSK_CLOCK_UTIL_RPT: ${PRE}_clock_util.rpt"

puts "CSK_BUFFERS_BEGIN"
foreach c [lsort [get_cells -quiet -hier -filter {REF_NAME =~ BUFG*}]] {
    set nm  [get_property NAME $c]
    set loc [get_property LOC $c]
    set op  [get_pins -quiet -of_objects $c -filter {DIRECTION == OUT}]
    if {[llength $op] == 0} { continue }
    set n [get_nets -quiet -of_objects [lindex $op 0]]
    if {[llength $n] == 0} { continue }
    set n [lindex $n 0]
    set root  [get_property -quiet CLOCK_ROOT $n]
    set uroot [get_property -quiet USER_CLOCK_ROOT $n]
    set fo    [get_property -quiet FLAT_PIN_COUNT $n]
    if {$root  eq ""} { set root  "(none)" }
    if {$uroot eq ""} { set uroot "(none)" }
    if {$fo    eq ""} { set fo    "?" }
    puts "CSK_BUF loc=$loc root=$root user_root=$uroot loads=$fo net=[get_property NAME $n]"
    puts "CSK_BUF_CELL     $nm"
}
puts "CSK_BUFFERS_END"

# ------------------------------------------------------- 2. where the loads are
# Dedicated blocks only: DSP/URAM/BRAM have exact, cheap site lookups and they
# are what pins a compute block to a die.  A SLICE histogram over 200k cells is
# minutes of runtime and answers the same question no better.
proc cr_hist {inst} {
    set cells [get_cells -quiet -hier -filter \
        "NAME =~ $inst/* && (REF_NAME =~ DSP48E2 || REF_NAME =~ URAM288* || REF_NAME =~ RAMB36*)"]
    if {[llength $cells] == 0} { return "NO_BLOCK_CELLS" }
    array unset h; array set h {}
    foreach st [get_sites -quiet -of_objects $cells] {
        set cr [get_property -quiet CLOCK_REGION $st]
        if {$cr eq ""} { set cr "?" }
        if {[info exists h($cr)]} { incr h($cr) } else { set h($cr) 1 }
    }
    set out {}
    foreach k [lsort [array names h]] { lappend out "$k=$h($k)" }
    return "n=[llength $cells] [join $out { }]"
}
puts "CSK_LOADS_BEGIN"
foreach inst {
    bd_i/layer_0 bd_i/mvchan_0 bd_i/mvchan_1 bd_i/mvchan_2 bd_i/mvchan_3 bd_i/seq_0
} {
    if {[llength [get_cells -quiet $inst]] == 0} { puts "CSK_LOADS $inst ABSENT"; continue }
    puts "CSK_LOADS $inst [cr_hist $inst]"
}
puts "CSK_LOADS_END"

# ------------------------------------------------ 3. what it costs on the paths
# Echo the six clock lines out of each full_clock_expanded report so the numbers
# are greppable from the log as well as readable in the .rpt the caller keeps.
proc echo_clock_lines {tag file} {
    if {![file exists $file]} { puts "CSK_RPT_MISSING $tag $file"; return }
    set fh [open $file r]
    while {[gets $fh line] >= 0} {
        if {[regexp {^\s*(Slack|Source:|Destination:|Clock Path Skew|Destination Clock Delay|Source Clock Delay|Clock Pessimism Removal|Clock Net Delay \(Source\)|Clock Net Delay \(Destination\)|Data Path Delay)} $line]} {
            puts "CSK_LINE $tag [string trim $line]"
        }
        if {[regexp {\(CLOCK_ROOT\)} $line]} {
            puts "CSK_ROOTHOP $tag [string trim $line]"
        }
        if {[regexp {SLR Crossing} $line]} {
            puts "CSK_SLRHOP $tag [string trim $line]"
        }
    }
    close $fh
}

proc probe_worst {tag pins} {
    global PRE
    if {[llength $pins] == 0} { puts "CSK_PROBE $tag NO_PINS"; return }
    set tp [get_timing_paths -quiet -to $pins -setup -max_paths 1 -nworst 1]
    if {[llength $tp] == 0} { puts "CSK_PROBE $tag NO_PATH"; return }
    set p [lindex $tp 0]
    set ep [get_property ENDPOINT_PIN $p]
    puts "CSK_PROBE $tag slack=[get_property SLACK $p] endpoint=$ep"
    set f ${PRE}_${tag}.rpt
    report_timing -of_objects $p -path_type full_clock_expanded -input_pins -file $f
    puts "CSK_PROBE_RPT $tag $f"
    echo_clock_lines $tag $f
}

# the design's own worst path, whatever owns it
set wp [get_timing_paths -max_paths 1 -nworst 1 -setup]
if {[llength $wp] > 0} {
    set f ${PRE}_design_worst.rpt
    puts "CSK_PROBE design_worst slack=[get_property SLACK [lindex $wp 0]] endpoint=[get_property ENDPOINT_PIN [lindex $wp 0]]"
    report_timing -of_objects [lindex $wp 0] -path_type full_clock_expanded -input_pins -file $f
    puts "CSK_PROBE_RPT design_worst $f"
    echo_clock_lines design_worst $f
}
probe_worst layer  [get_pins -quiet -hier -filter {NAME =~ bd_i/layer_0/inst/u_core/*/D}]
probe_worst mvchan0 [get_pins -quiet -hier -filter {NAME =~ bd_i/mvchan_0/*/D}]
probe_worst mvchan2 [get_pins -quiet -hier -filter {NAME =~ bd_i/mvchan_2/*/D}]
probe_worst mvchan3 [get_pins -quiet -hier -filter {NAME =~ bd_i/mvchan_3/*/D}]
probe_worst seq    [get_pins -quiet -hier -filter {NAME =~ bd_i/seq_0/*/D}]

puts "CSK_PROBE_DONE"
