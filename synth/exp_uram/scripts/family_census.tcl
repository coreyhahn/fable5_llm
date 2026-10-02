# family_census.tcl — G5a Step 3 input: once a floorplan moves the DN write
# fan-out off the critical path, WHAT OWNS THE RESIDUAL?
#
# The G5a variants change which path family binds, and "WNS = -0.831" says
# nothing about whether the remaining deficit is the same structural problem
# somewhere else or a new one.  This reports the worst setup path in each
# named family, and the family histogram of the 200 worst endpoints, so the
# gate doc's reading of the residual is measured rather than inferred from one
# worst path.
#
#   vivado -mode batch -nojournal -source family_census.tcl -tclargs <run_out_dir>
if {[llength $argv] < 1} { puts "FATAL: need <run_out_dir>"; exit 1 }
set OutDir [lindex $argv 0]
set Dcp    $OutDir/post_place.dcp
if {![file exists $Dcp]} { puts "FATAL: no $Dcp"; exit 1 }
set_param general.maxThreads 8
open_checkpoint $Dcp
puts "FAM_DCP: $Dcp"

proc slr_of {objname} {
    set c [get_cells -quiet -of_objects $objname]
    if {$c eq ""} { return "?" }
    set st [get_sites -quiet -of_objects $c]
    if {$st eq ""} { return "unplaced" }
    set s [get_slrs -quiet -of_objects $st]
    if {$s eq ""} { return "?" }
    return [get_property NAME $s]
}

# Families, in the order a path is tested against them.  First match wins, so
# the more specific pattern comes first.
set FAM {
    DN_URAM_WRITE   {*g_dnpipe*g_dn*mem_reg_uram*}
    KV_URAM_WRITE   {*g_kv*mem_reg_uram*}
    KV_EXP_MEM      {*g_kv*emem*}
    CONV_BRAM       {*g_cv*}
    ATTN_DSP        {u_attn/*}
    DN_MUX_OREG     {*dn_rdq_reg*}
    DN_GRP_RETURN   {*g_grp*rq_p_reg*}
}

# ---- (1) the worst path INTO each family's endpoints
# "cells" is a CELL count (the family's endpoint CELLS), not a count of
# timing endpoints or of failing endpoints — one URAM288 cell carries many
# endpoint pins.
puts "FAM_TABLE family cells worst_slack levels datapath logic route route_pct startSLR endSLR"
foreach {name pat} $FAM {
    set dst [get_cells -quiet -hier -filter "NAME =~ $pat"]
    if {[llength $dst] == 0} { puts "FAM_ROW $name 0 n/a n/a n/a n/a n/a n/a n/a n/a"; continue }
    set p [lindex [get_timing_paths -quiet -to $dst -max_paths 1 -nworst 1 -setup] 0]
    if {$p eq ""} { puts "FAM_ROW $name [llength $dst] no-path n/a n/a n/a n/a n/a n/a n/a"; continue }
    set dl [get_property DATAPATH_DELAY $p]
    set rd [get_property DATAPATH_NET_DELAY $p]
    set pct "n/a"
    if {$dl ne "" && $dl > 0} { set pct [format %.1f [expr {100.0*$rd/$dl}]] }
    puts [format "FAM_ROW %-15s %6d %8s %3s %7s %7s %7s %6s %-5s %-5s" \
        $name [llength $dst] [get_property SLACK $p] [get_property LOGIC_LEVELS $p] \
        $dl [get_property DATAPATH_LOGIC_DELAY $p] $rd $pct \
        [slr_of [get_property STARTPOINT_PIN $p]] [slr_of [get_property ENDPOINT_PIN $p]]]
    puts "FAM_PATH $name [get_property STARTPOINT_PIN $p] -> [get_property ENDPOINT_PIN $p]"
}

# ---- (2) the family histogram of the 200 worst endpoints in the design
array set hist {}
array set hworst {}
foreach p [get_timing_paths -quiet -max_paths 200 -nworst 1 -setup -sort_by slack] {
    set ep [get_property ENDPOINT_PIN $p]
    set fam "OTHER"
    foreach {name pat} $FAM {
        if {[string match $pat $ep]} { set fam $name; break }
    }
    if {[info exists hist($fam)]} { incr hist($fam) } else { set hist($fam) 1 }
    set s [get_property SLACK $p]
    if {![info exists hworst($fam)] || $s < $hworst($fam)} { set hworst($fam) $s }
}
puts "FAM_HIST family paths worst_slack   (over the 200 worst setup PATHS)"
foreach f [lsort [array names hist]] {
    puts [format "FAM_HIST_ROW %-15s %4d %8s" $f $hist($f) $hworst($f)]
}
puts "FAM_DONE"
