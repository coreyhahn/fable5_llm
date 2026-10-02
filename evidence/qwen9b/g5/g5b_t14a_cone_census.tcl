# g5b_t14a_cone_census.tcl — Task 14-A's READ-ONLY cone census.
#
# Task 14 failed its gate at WNS -0.130 and section 5.5 of
# evidence/qwen9b/g5/G5B_TIMING.md showed the residual is LOGIC-dominated, not
# routing.  Task 14-A has to decide WHERE register stages go, and for that the
# census that exists is not enough: census_035.tcl decomposes only the four
# worst paths, and g5b_family_census.tcl reports one worst path per family.
# This instrument pulls the top N failing paths PER FAILING CLOCK, each with
# its logic/route split, its logic-level count, both SLRs, and — in a
# companion .rpt — the cell-by-cell expansion that says what those levels ARE.
#
# WHY A NEW FILE AND NOT AN EDIT.  Every script under evidence/qwen9b/g5/ is
# cited by G5B_TIMING.md by name and several by line; Task 14-A's block
# forbids modifying any of them.  Same rule the family census applied to S5's.
#
# READ-ONLY BY CONSTRUCTION: open_checkpoint + report_*; no place, no route,
# no phys_opt, no write_checkpoint, and every file it writes goes to the
# -tclargs output prefix (which the caller points into evidence/), never into
# a synth/out_* directory.
#
#   vivado -mode batch -nojournal -source g5b_t14a_cone_census.tcl \
#          -tclargs <routed.dcp> <out_prefix> [max_paths]
#
# Emits markers T14A_*; writes <out_prefix>_<group>_paths.rpt and
# <out_prefix>_<group>_rda.rpt per failing clock group.

if {[llength $argv] < 2} { puts "FATAL: need <dcp> <out_prefix> \[max_paths\]"; exit 1 }
set DCP  [lindex $argv 0]
set PRE  [lindex $argv 1]
set NMAX 50
if {[llength $argv] > 2} { set NMAX [lindex $argv 2] }
if {![file exists $DCP]} { puts "FATAL: no such checkpoint: $DCP"; exit 1 }

set_param general.maxThreads 8
puts "T14A_DCP: $DCP"
puts "T14A_DCP_MTIME: [clock format [file mtime $DCP] -format {%Y-%m-%d %H:%M:%S}]"
puts "T14A_DCP_BYTES: [file size $DCP]"
puts "T14A_OUT_PREFIX: $PRE"
puts "T14A_MAX_PATHS: $NMAX"
open_checkpoint $DCP

# ------------------------------------------------------------------ headline
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
puts "T14A_TIMING: WNS=$wns WHS=$whs"

proc slr_of {objname} {
    set c [get_cells -quiet -of_objects $objname]
    if {$c eq ""} { return "?" }
    set st [get_sites -quiet -of_objects $c]
    if {$st eq ""} { return "unplaced" }
    set s [get_slrs -quiet -of_objects $st]
    if {$s eq ""} { return "?" }
    return [get_property NAME $s]
}

# ---------------------------------------------- which groups actually fail
# 6000 is above the 4,265 / 6,090 counts both target checkpoints report, so
# this sample is the WHOLE failing set on either of them, not a cap.  The
# marker prints the length so a future reader can tell.
set allp [get_timing_paths -quiet -max_paths 6000 -nworst 1 -setup -slack_lesser_than 0]
puts "T14A_FAILING_SAMPLE: [llength $allp]"
array set gcnt {}
array set gworst {}
foreach p $allp {
    set g [get_property GROUP $p]
    if {[info exists gcnt($g)]} { incr gcnt($g) } else { set gcnt($g) 1 }
    set s [get_property SLACK $p]
    if {![info exists gworst($g)] || $s < $gworst($g)} { set gworst($g) $s }
}
puts "T14A_GROUPS_BEGIN"
foreach g [lsort [array names gcnt]] {
    puts [format "T14A_GROUP %-24s failing=%-6d worst=%s" $g $gcnt($g) $gworst($g)]
}
puts "T14A_GROUPS_END"

# ------------------------------------------- the RTL-site cone tally
# Patterns are ordered; first match wins.  They name RTL SITES, not the
# hierarchy families g5b_family_census.tcl uses, because Task 14-A's question
# is "which register does the stage go in front of", not "which module".
set CONE {
    DN_VDATA        {*u_core/dn_vdata_reg*}
    AT_QDATA        {*u_core/at_qdata_reg*}
    AXIL_RDATA      {*s_axil_rdata_reg*}
    CONV_SILU_M3    {*u_conv*m3_reg*}
    XLINE_Q0_CE     {*u_engine/xline_q0_reg*}
    SDMA            {*u_dma/*}
    ATTN_DSP        {*u_attn/*}
    DN_LANE         {*u_dn/*}
    DN_SLOT         {*g_dnslot*}
    KV_SLOT         {*g_kvslot*}
    CV_SLOT         {*g_cvslot*}
    SCRATCH_SMEM    {*smem_*}
    LAYER_OTHER     {*layer_0*}
    MVCHAN          {*mvchan_*}
    SEQ             {*seq_0*}
    VENDOR          {*}
}
array set ccnt {}
array set cworst {}
array set cworstp {}
foreach p $allp {
    set ep [get_property ENDPOINT_PIN $p]
    set fam "VENDOR"
    foreach {name pat} $CONE { if {[string match $pat $ep]} { set fam $name; break } }
    if {[info exists ccnt($fam)]} { incr ccnt($fam) } else { set ccnt($fam) 1 }
    set s [get_property SLACK $p]
    if {![info exists cworst($fam)] || $s < $cworst($fam)} {
        set cworst($fam) $s
        set cworstp($fam) $p
    }
}
puts "T14A_CONE_TALLY_BEGIN  (over all [llength $allp] failing setup paths)"
foreach f [lsort [array names ccnt]] {
    set p $cworstp($f)
    set dl [get_property DATAPATH_DELAY $p]
    set lg [get_property DATAPATH_LOGIC_DELAY $p]
    set rt [get_property DATAPATH_NET_DELAY $p]
    set pct "n/a"
    if {$dl ne "" && $dl > 0} { set pct [format %.1f [expr {100.0*$lg/$dl}]] }
    puts [format "T14A_CONE %-14s n=%-6d worst=%-8s lvl=%-3s dp=%-7s logic=%-7s route=%-7s logic%%=%-6s group=%s" \
        $f $ccnt($f) $cworst($f) [get_property LOGIC_LEVELS $p] $dl $lg $rt $pct \
        [get_property GROUP $p]]
    puts "T14A_CONE_PATH $f [get_property STARTPOINT_PIN $p] -> [get_property ENDPOINT_PIN $p]"
}
puts "T14A_CONE_TALLY_END"

# ------------------------------------------------ per-group worst-N detail
foreach g [lsort [array names gcnt]] {
    set safe [regsub -all {[^A-Za-z0-9_]} $g "_"]
    # A path-group name that -group will not take (spaces, **async_default**)
    # must not kill the run: say so and move on.
    if {[catch {get_timing_paths -quiet -max_paths $NMAX -nworst 1 -setup \
                    -group $g -slack_lesser_than 0 -sort_by slack} ps]} {
        puts "T14A_DETAIL_SKIP $g : $ps"
        continue
    }
    puts "T14A_DETAIL_BEGIN $g n=[llength $ps]"
    foreach p $ps {
        set dl [get_property DATAPATH_DELAY $p]
        set lg [get_property DATAPATH_LOGIC_DELAY $p]
        set rt [get_property DATAPATH_NET_DELAY $p]
        set pct "n/a"
        if {$dl ne "" && $dl > 0} { set pct [format %.1f [expr {100.0*$lg/$dl}]] }
        set sp [get_property STARTPOINT_PIN $p]
        set ep [get_property ENDPOINT_PIN $p]
        set cone "VENDOR"
        foreach {name pat} $CONE { if {[string match $pat $ep]} { set cone $name; break } }
        set ssl [slr_of $sp]
        set esl [slr_of $ep]
        set xslr [expr {$ssl eq $esl ? "same" : "CROSS"}]
        puts [format "T14A_P %-8s %-14s lvl=%-3s dp=%-7s logic=%-7s route=%-7s logic%%=%-6s %s %s->%s | %s <- %s" \
            [get_property SLACK $p] $cone [get_property LOGIC_LEVELS $p] \
            $dl $lg $rt $pct $xslr $ssl $esl $ep $sp]
    }
    puts "T14A_DETAIL_END $g"
    if {[llength $ps] > 0} {
        report_timing -of_objects $ps -path_type full_clock_expanded -input_pins \
            -file ${PRE}_${safe}_paths.rpt
        puts "T14A_WROTE ${PRE}_${safe}_paths.rpt"
        report_design_analysis -of_timing_paths $ps -logic_level_distribution \
            -file ${PRE}_${safe}_rda.rpt
        report_design_analysis -of_timing_paths $ps -timing -append \
            -file ${PRE}_${safe}_rda.rpt
        puts "T14A_WROTE ${PRE}_${safe}_rda.rpt"
    }
}

# ------------------------------- design-wide logic-level distribution
report_design_analysis -logic_level_distribution -logic_level_dist_paths 20000 \
    -file ${PRE}_lld.rpt
puts "T14A_WROTE ${PRE}_lld.rpt"

# ------------- the named cones, reported by NAME whether or not they fail
# Same discipline final_verify.tcl uses: a cone that no longer appears has to
# say so out loud rather than vanish from the table.
set PROBE {
    DN_VDATA        {*u_core/dn_vdata_reg*/D}
    AT_QDATA        {*u_core/at_qdata_reg*/D}
    AXIL_RDATA      {*s_axil_rdata_reg*/D}
    CONV_SILU_M3    {*u_conv*m3_reg*/D}
    XLINE_Q0_CE     {*u_engine/xline_q0_reg*/CE}
}
puts "T14A_PROBE_BEGIN"
foreach {name pat} $PROBE {
    set pins [get_pins -quiet -hier -filter "NAME =~ $pat"]
    if {[llength $pins] == 0} { puts "T14A_PROBE $name PINS=0 ABSENT"; continue }
    set p [lindex [get_timing_paths -quiet -to $pins -max_paths 1 -nworst 1 -setup] 0]
    if {$p eq ""} { puts "T14A_PROBE $name PINS=[llength $pins] no-path"; continue }
    set dl [get_property DATAPATH_DELAY $p]
    set lg [get_property DATAPATH_LOGIC_DELAY $p]
    set pct "n/a"
    if {$dl ne "" && $dl > 0} { set pct [format %.1f [expr {100.0*$lg/$dl}]] }
    puts [format "T14A_PROBE %-14s PINS=%-6d worst=%-8s lvl=%-3s dp=%-7s logic=%-7s route=%-7s logic%%=%s" \
        $name [llength $pins] [get_property SLACK $p] [get_property LOGIC_LEVELS $p] \
        $dl $lg [get_property DATAPATH_NET_DELAY $p] $pct]
    puts "T14A_PROBE_PATH $name [get_property STARTPOINT_PIN $p] -> [get_property ENDPOINT_PIN $p]"
    report_timing -of_objects [list $p] -path_type full_clock_expanded -input_pins \
        -file ${PRE}_probe_[string tolower $name].rpt
    puts "T14A_WROTE ${PRE}_probe_[string tolower $name].rpt"
}
puts "T14A_PROBE_END"
puts "T14A_DONE"
