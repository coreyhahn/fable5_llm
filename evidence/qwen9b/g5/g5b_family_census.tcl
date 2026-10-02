# g5b_family_census.tcl — Task 14's copy of evidence/qwen9b/s5/s5_family_census.tcl
# (S5), re-pointed at an IN-CONTEXT project roll.
#
# WHY A COPY AND NOT AN EDIT, again.  S5's script is cited by
# evidence/qwen9b/s5/S5_STRUCT.md sections 4.4 and 4.5 as the instrument that
# produced its family tables, and Task 14's commit block does not include
# evidence/qwen9b/s5/.  Copying leaves S5's committed instrument byte-identical
# and keeps Task 14's change inside Task 14's own evidence directory — the same
# rule S5 applied to Task 13's synth/exp_uram/scripts/family_census.tcl.
#
# THE THREE DIFFERENCES FROM S5's COPY, and nothing else:
#
#  1. THE CHECKPOINT.  S5 ran out of context, where the harness writes
#     <out>/post_place.dcp.  This runs on a full project roll, so it opens the
#     same checkpoint synth/scripts/census_035.tcl does —
#     <roll>/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp, falling
#     back to bd_wrapper_routed.dcp for a roll with no post-route phys_opt
#     stage.  These paths are ROUTED, where S5's were post-place; the marker
#     names are unchanged so the rows are read the same way, but the numbers
#     are a routed design's and S5's are not (S5_STRUCT.md section 6: nothing
#     there is routed).
#
#  2. THE PATTERNS GAIN A LEADING `*`.  Out of context `layer_chan` is the top
#     module and `u_dma/*` matches.  In context every one of those cells is
#     `bd_i/layer_0/inst/u_core/u_dma/...`, so the unprefixed pattern matches
#     ZERO cells and the family would silently report `0 n/a` — the same class
#     of silent-nothing failure the pblock rewrite exists to avoid.  Only
#     SDMA and ATTN_DSP needed it; the four `*g_*slot*`/`*smem_*` patterns
#     already began with `*`.
#
#  3. THE HISTOGRAM GAINS THE REST OF THE DESIGN.  Out of context every path
#     was inside the layer, so six families plus OTHER covered it.  In context
#     the four matvec channels, the sequencer, XDMA, the four MIGs and the
#     SmartConnects are all present, and putting them in one OTHER bucket
#     would make the residual unreadable.  The histogram list therefore adds
#     seven in-context families AFTER the six (first match wins, so the six
#     keep their meaning exactly).  The PROBE list — part (1) — is still the
#     six, deliberately: `get_timing_paths -to` over a whole channel's cell
#     set is minutes of runtime per family and the histogram answers the
#     question the probe would.
#
# Everything else — the method, the markers, the output format, the OTHER
# probe S5 added — is unchanged.
#
#   vivado -mode batch -nojournal -source g5b_family_census.tcl -tclargs <roll_dir>
if {[llength $argv] < 1} { puts "FATAL: need <roll_dir>"; exit 1 }
set D [lindex $argv 0]
set Dcp $D/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp
if {![file exists $Dcp]} { set Dcp $D/proj/stage1.runs/impl_1/bd_wrapper_routed.dcp }
if {![file exists $Dcp]} { puts "FATAL: no routed checkpoint under $D"; exit 1 }
set_param general.maxThreads 8
open_checkpoint $Dcp
puts "FAM_DCP: $Dcp"
puts "FAM_DCP_MTIME: [clock format [file mtime $Dcp] -format {%Y-%m-%d %H:%M:%S}]"

proc slr_of {objname} {
    set c [get_cells -quiet -of_objects $objname]
    if {$c eq ""} { return "?" }
    set st [get_sites -quiet -of_objects $c]
    if {$st eq ""} { return "unplaced" }
    set s [get_slrs -quiet -of_objects $st]
    if {$s eq ""} { return "?" }
    return [get_property NAME $s]
}

# The six S5 families, in the order a path is tested against them.  First
# match wins, so the more specific pattern comes first.
set FAM {
    DN_SLOT         {*g_dnslot*}
    KV_SLOT         {*g_kvslot*}
    CV_SLOT         {*g_cvslot*}
    SDMA            {*u_dma/*}
    ATTN_DSP        {*u_attn/*}
    SCRATCH         {*smem_*}
}
# The histogram list: the six above, then the rest of the in-context design.
set HFAM {
    DN_SLOT         {*g_dnslot*}
    KV_SLOT         {*g_kvslot*}
    CV_SLOT         {*g_cvslot*}
    SDMA            {*u_dma/*}
    ATTN_DSP        {*u_attn/*}
    SCRATCH         {*smem_*}
    LAYER_OTHER     {*layer_0*}
    MATVEC_ENGINE   {*u_engine*}
    MVCHAN_OTHER    {*mvchan_*}
    SEQ             {*seq_0*}
    VENDOR_MIG      {*ddr4_*}
    VENDOR_XDMA     {*xdma_0*}
    VENDOR_SMC      {*smc*}
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
    foreach {name pat} $HFAM {
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
# ---- (3) S5's addition, kept: NAME the OTHER bucket.  A path that belongs to
# no family lands in OTHER, and "OTHER owns the residual" is not a finding a
# reader can act on.  Print the worst OTHER path in full so the gate doc can
# name it (and so a family worth adding announces itself).
set other_worst ""
foreach p [get_timing_paths -quiet -max_paths 200 -nworst 1 -setup -sort_by slack] {
    set ep [get_property ENDPOINT_PIN $p]
    set hit 0
    foreach {name pat} $HFAM { if {[string match $pat $ep]} { set hit 1; break } }
    if {!$hit} { set other_worst $p; break }
}
if {$other_worst ne ""} {
    set dl [get_property DATAPATH_DELAY $other_worst]
    set rd [get_property DATAPATH_NET_DELAY $other_worst]
    set pct "n/a"
    if {$dl ne "" && $dl > 0} { set pct [format %.1f [expr {100.0*$rd/$dl}]] }
    puts "FAM_OTHER_WORST slack=[get_property SLACK $other_worst] levels=[get_property LOGIC_LEVELS $other_worst] datapath=$dl logic=[get_property DATAPATH_LOGIC_DELAY $other_worst] route=$rd route_pct=$pct"
    puts "FAM_OTHER_PATH [get_property STARTPOINT_PIN $other_worst] -> [get_property ENDPOINT_PIN $other_worst]"
} else {
    puts "FAM_OTHER_WORST none (every one of the 200 worst paths is in a named family)"
}
puts "FAM_DONE"
