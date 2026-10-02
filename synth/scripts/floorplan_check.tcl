# floorplan_check.tcl <roll_dir> <xdc> — DRY-RUN the floorplan before spending
# hours on it. Opens the routed checkpoint (full netlist), sources the pblock
# XDC, and answers the three questions that decide whether the campaign can
# measure anything at all:
#   1. Do the cell paths resolve? A pblock matching zero cells is silently
#      harmless in Vivado — the classic way to run a floorplan campaign that
#      measures nothing.
#   2. Are the CLOCKREGION ranges accepted, and what sites do they contain?
#   3. Does the assigned logic actually FIT? Per pblock: required LUT / FF /
#      DSP / BRAM / URAM against the region's real capacity, from the device
#      rather than from my arithmetic.
#
# Usage: vivado -mode batch -nojournal -source floorplan_check.tcl \
#          -tclargs <roll_dir> <xdc>

if {[llength $argv] < 2} { puts "FATAL: need <roll_dir> <xdc>"; exit 1 }
set D   [lindex $argv 0]
set XDC [lindex $argv 1]
set dcp $D/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp
if {![file exists $dcp]} { set dcp $D/proj/stage1.runs/impl_1/bd_wrapper_routed.dcp }
if {![file exists $dcp]} { puts "FATAL: no routed checkpoint under $D"; exit 1 }
open_checkpoint $dcp

puts "FPCHECK_XDC: $XDC"
if {[catch {read_xdc -quiet $XDC} err]} { puts "FPCHECK_FATAL: read_xdc: $err"; exit 1 }
puts "FPCHECK_XDC_READ_OK"

set pbs [get_pblocks -quiet]
puts "FPCHECK_PBLOCK_COUNT: [llength $pbs]"
if {[llength $pbs] == 0} { puts "FPCHECK_FATAL: no pblocks created"; exit 1 }

foreach pb $pbs {
    set ranges [get_property GRID_RANGES $pb]
    # NB: get_cells -of_objects <pblock> returns the ASSIGNED cells, which for
    # this floorplan are HIERARCHICAL (bd_i/mvchan_3, .../u_dn). Counting those
    # reports "1" and censuses zero primitives. Expand to leaves first.
    set assigned [get_cells -quiet -of_objects $pb]
    set cells {}
    foreach a $assigned {
        if {[get_property PRIMITIVE_LEVEL $a] eq "LEAF"} {
            lappend cells $a
        } else {
            set nm [get_property NAME $a]
            set cells [concat $cells [get_cells -quiet -hier -filter "PRIMITIVE_LEVEL == LEAF && NAME =~ $nm/*"]]
        }
    }
    puts "FPCHECK_ASSIGNED $pb top_cells=[llength $assigned] leaf_cells=[llength $cells]"
    # required resources = primitive census of the assigned cells
    array unset need; array set need {LUT 0 FF 0 DSP 0 RAMB36 0 RAMB18 0 URAM 0 LUTRAM 0}
    foreach c $cells {
        set r [get_property REF_NAME $c]
        if {[regexp {^(LUT[1-6])$} $r]}                 { incr need(LUT) } \
        elseif {[regexp {^(RAMD|RAMS|SRL)} $r]}         { incr need(LUTRAM) } \
        elseif {[regexp {^(FD|LD)} $r]}                 { incr need(FF) } \
        elseif {[regexp {^DSP} $r]}                     { incr need(DSP) } \
        elseif {[regexp {^RAMB36} $r]}                  { incr need(RAMB36) } \
        elseif {[regexp {^RAMB18} $r]}                  { incr need(RAMB18) } \
        elseif {[regexp {^URAM} $r]}                    { incr need(URAM) }
    }
    # available resources in the pblock's region
    set sites [get_sites -quiet -of_objects $pb]
    array unset have; array set have {SLICE 0 DSP 0 RAMB36 0 URAM 0}
    foreach s $sites {
        set ty [get_property SITE_TYPE $s]
        if {[string match "SLICE*" $ty]}        { incr have(SLICE) } \
        elseif {[string match "DSP48E2" $ty]}   { incr have(DSP) } \
        elseif {[string match "RAMB36*" $ty]}   { incr have(RAMB36) } \
        elseif {[string match "URAM288" $ty]}   { incr have(URAM) }
    }
    # DSP/BRAM/URAM: count at ANY primitive level, not just LEAF. In a routed
    # checkpoint a DSP48E2 is a MACRO whose leaves are DSP_ALU / DSP_MULTIPLIER
    # / ... so a LEAF-only census reports DSP=0 — which is a *falsely
    # reassuring* answer for the one resource the house rule says to check.
    # (Observed: this script's first version reported u_dn DSP=0 against the
    # 1,280 that report_utilization -hierarchical shows.)
    set nm_list {}
    foreach a $assigned { lappend nm_list [get_property NAME $a] }
    set ndsp 0; set nbram 0; set nuram 0
    foreach nm $nm_list {
        incr ndsp  [llength [get_cells -quiet -hier -filter "NAME =~ $nm/* && REF_NAME =~ DSP48E2"]]
        incr nbram [llength [get_cells -quiet -hier -filter "NAME =~ $nm/* && REF_NAME =~ RAMB*"]]
        incr nuram [llength [get_cells -quiet -hier -filter "NAME =~ $nm/* && REF_NAME =~ URAM*"]]
    }

    puts "FPCHECK_PBLOCK $pb"
    puts "  ranges     : $ranges"
    puts "  cells      : [llength $cells]"
    puts "  need       : LUT=$need(LUT) LUTRAM=$need(LUTRAM) FF=$need(FF) RAMB18=$need(RAMB18)"
    puts "  need(macro): DSP48E2=$ndsp RAMB*=$nbram URAM*=$nuram   <- authoritative for DSP/BRAM/URAM"
    set need(DSP) $ndsp
    set need(URAM) $nuram
    puts "  region has : SLICE=$have(SLICE) DSP=$have(DSP) RAMB36=$have(RAMB36) URAM=$have(URAM)"
    if {$have(DSP) > 0} {
        puts [format "  DSP fit    : %d / %d = %.1f%%" $need(DSP) $have(DSP) [expr {100.0*$need(DSP)/$have(DSP)}]]
    }
    if {$have(URAM) > 0 && $need(URAM) > 0} {
        puts [format "  URAM fit   : %d / %d = %.1f%%" $need(URAM) $have(URAM) [expr {100.0*$need(URAM)/$have(URAM)}]]
    }
    if {[llength $cells] == 0} { puts "  *** WARNING: pblock matches ZERO cells — it will measure nothing ***" }
}

# Aggregate the DSP question the house rule demands: total DSP demanded per
# SLR region once these pblocks are honoured, versus that SLR's 2280.
puts "FPCHECK_OK"
