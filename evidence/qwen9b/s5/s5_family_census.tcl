# s5_family_census.tcl — S5's copy of synth/exp_uram/scripts/family_census.tcl
# (Task 13), with the FAMILIES rewritten for the state-spill design.
#
# WHY A COPY AND NOT AN EDIT.  Task 13's script is cited by
# evidence/qwen9b/g5/G5A_FLOORPLAN.md §4.4 as the instrument that produced its
# eleven family tables, and S5's commit block does not include
# synth/exp_uram/scripts/.  Copying leaves Task 13's committed instrument byte-
# identical (so its gate doc keeps measuring what it says it measured) and
# keeps S5's change inside S5's own evidence directory — the same rule the
# campaign already applies to the superlative checker.  The ONLY difference
# from the original is the `FAM` list below and the OTHER-family probe at the
# end; the method, the markers and the output format are unchanged, so S5's
# rows and Task 13's rows are read the same way.
#
# THE FAMILIES CHANGED BECAUSE THE DESIGN DID.  Task 13 measured a 928-URAM288
# BANK ARRAY: DN_URAM_WRITE (`*g_dnpipe*g_dn*mem_reg_uram*`), DN_GRP_RETURN,
# DN_MUX_OREG and friends all name cells S2 retired.  What exists now is two
# CACHE SLOTS per kind behind ownership muxes (spec §3, A1.2) plus the state
# DMA engine, so the families are the slots themselves:
#
#   DN_SLOT   every endpoint inside `g_dnslot[*]` — the DN cache URAMs.  Its
#             worst path IS the DN write fan-out under the ownership mux, which
#             is the measurement spec A1.2 asks S5 for (it WITHDREW §3's "no
#             timing change on the compute side").  Task 13's comparable row is
#             DN_URAM_WRITE: -0.001 under 2'cr.
#   KV_SLOT   the same for `g_kvslot[*]` (the KV row URAMs AND the per-slot
#             8192 x 8 b exponent memory, which is block RAM by design).
#             Task 13's comparable row is KV_URAM_WRITE: -0.368 under 2'cr.
#   CV_SLOT   `g_cvslot[*]` — the conv weight/state memory pair.  Task 13's
#             CONV_BRAM was -0.554 under 2'cr and OWNED the residual there.
#   SDMA      `u_dma/*` — the new engine (spec §4); it did not exist in Task 13.
#   ATTN_DSP  `u_attn/*` — unchanged from Task 13.
#   SCRATCH   `*smem_*` — the 2 x 65,536 x 16 b scratchpad, the design's
#             largest block-RAM consumer; Task 13 had no row for it and its
#             endpoints fell into OTHER.
#
# Nothing about the ORIGINAL question changed: once a floorplan moves one
# family off the critical path, WHAT OWNS THE RESIDUAL?
#
# The G5a variants change which path family binds, and "WNS = -0.831" says
# nothing about whether the remaining deficit is the same structural problem
# somewhere else or a new one.  This reports the worst setup path in each
# named family, and the family histogram of the 200 worst endpoints, so the
# gate doc's reading of the residual is measured rather than inferred from one
# worst path.
#
#   vivado -mode batch -nojournal -source s5_family_census.tcl -tclargs <run_out_dir>
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
    DN_SLOT         {*g_dnslot*}
    KV_SLOT         {*g_kvslot*}
    CV_SLOT         {*g_cvslot*}
    SDMA            {u_dma/*}
    ATTN_DSP        {u_attn/*}
    SCRATCH         {*smem_*}
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
# ---- (3) S5 addition: NAME the OTHER bucket.  With six families a path that
# belongs to none of them lands in OTHER, and "OTHER owns the residual" is not
# a finding a reader can act on.  Print the worst OTHER path in full so the
# gate doc can name it (and so a family worth adding announces itself).
set other_worst ""
foreach p [get_timing_paths -quiet -max_paths 200 -nworst 1 -setup -sort_by slack] {
    set ep [get_property ENDPOINT_PIN $p]
    set hit 0
    foreach {name pat} $FAM { if {[string match $pat $ep]} { set hit 1; break } }
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
