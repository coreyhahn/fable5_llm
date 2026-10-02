# slr_census.tcl <roll_dir> — where did everything physically LAND?
#
# Input for the floorplan campaign (R-c task 5b). build_035's regression is
# SLR spread (TIMING_035.md §8c: SLL crossings +23%), so before writing a
# single pblock we need the facts a floorplan has to respect:
#   1. SLR geometry: clock-region Y span AND the SLICE Y boundaries, both
#      verified from the device, not assumed from part folklore.
#   2. Which SLR each DDR4 MIG sits in — MIGs have FIXED bank locations, so
#      they are the immovable anchors the mvchans must be drawn toward.
#   3. How far the placer scattered each mvchan / layer_0 / seq_0.
#   4. Which blocks must NEVER be pblocked (GT/PCIe/CMT — fixed sites).
#
# NB on method: `get_cells -hier -filter {...} -of_objects <slr>` silently
# returns nothing (first attempt did exactly that, all zeros). The reliable
# way is to read each leaf cell's LOC and bucket it by the site's Y
# coordinate against verified SLR boundaries. Only SLICE-located cells are
# histogrammed — DSP/BRAM/URAM have their own independent Y scales, and the
# per-SLR counts for those already come from report_utilization.
#
# Usage: vivado -mode batch -nojournal -source slr_census.tcl -tclargs <roll_dir>

if {[llength $argv] < 1} { puts "FATAL: need <roll_dir>"; exit 1 }
set D [lindex $argv 0]
set dcp $D/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp
if {![file exists $dcp]} { set dcp $D/proj/stage1.runs/impl_1/bd_wrapper_routed.dcp }
if {![file exists $dcp]} { puts "FATAL: no routed checkpoint under $D"; exit 1 }
puts "SLRCENSUS_CHECKPOINT: $dcp"
open_checkpoint $dcp

# ---------------------------------------------------------------- 1. geometry
# clock-region Y span per SLR, and the SLICE Y range, both measured.
array set SLR_YMIN {}
array set SLR_YMAX {}
puts "SLR_GEOMETRY_BEGIN"
foreach s [get_slrs] {
    set nm [get_property NAME $s]
    set crs [get_clock_regions -quiet -of_objects $s]
    set crys {}
    foreach cr $crs {
        if {[regexp {X(\d+)Y(\d+)} [get_property NAME $cr] -> x y]} { lappend crys $y }
    }
    set crys [lsort -integer -unique $crys]
    # SLICE Y bounds: sample the sites of this SLR's clock regions
    set ymin 999999; set ymax -1
    foreach cr $crs {
        foreach st [get_sites -quiet -of_objects $cr -filter {SITE_TYPE =~ SLICE*}] {
            if {[regexp {Y(\d+)$} [get_property NAME $st] -> y]} {
                if {$y < $ymin} { set ymin $y }
                if {$y > $ymax} { set ymax $y }
            }
        }
    }
    set SLR_YMIN($nm) $ymin
    set SLR_YMAX($nm) $ymax
    puts [format "SLR %s regions=%d CR_Y=%s..%s SLICE_Y=%d..%d" \
        $nm [llength $crs] [lindex $crys 0] [lindex $crys end] $ymin $ymax]
}
puts "SLR_GEOMETRY_END"

proc slr_of_y {y} {
    global SLR_YMIN SLR_YMAX
    foreach nm [array names SLR_YMIN] {
        if {$y >= $SLR_YMIN($nm) && $y <= $SLR_YMAX($nm)} { return $nm }
    }
    return "?"
}

# ------------------------------------------------- 2/3. instance -> SLR spread
proc slr_hist {inst} {
    array set h {SLR0 0 SLR1 0 SLR2 0 ? 0 unplaced 0}
    set cells [get_cells -quiet -hier -filter "PRIMITIVE_LEVEL == LEAF && NAME =~ $inst/*"]
    foreach loc [get_property LOC $cells] {
        if {$loc eq ""} { incr h(unplaced); continue }
        if {![string match "SLICE*" $loc]} { continue }
        if {[regexp {Y(\d+)$} $loc -> y]} { incr h([slr_of_y $y]) } else { incr h(?) }
    }
    set tot [expr {$h(SLR0)+$h(SLR1)+$h(SLR2)}]
    if {$tot == 0} { set tot 1 }
    return [format "SLR0=%d(%.0f%%) SLR1=%d(%.0f%%) SLR2=%d(%.0f%%) sliceTot=%d nonslice/unplaced=%d" \
        $h(SLR0) [expr {100.0*$h(SLR0)/$tot}] \
        $h(SLR1) [expr {100.0*$h(SLR1)/$tot}] \
        $h(SLR2) [expr {100.0*$h(SLR2)/$tot}] \
        $tot $h(unplaced)]
}

puts "INSTANCE_SLR_BEGIN"
foreach inst {
    bd_i/ddr4_0 bd_i/ddr4_1 bd_i/ddr4_2 bd_i/ddr4_3
    bd_i/mvchan_0 bd_i/mvchan_1 bd_i/mvchan_2 bd_i/mvchan_3
    bd_i/layer_0 bd_i/seq_0 bd_i/xdma_0
    bd_i/smc_ch0 bd_i/smc_ch1 bd_i/smc_ch2 bd_i/smc_ch3
    bd_i/axi_smc bd_i/axil_smc bd_i/burst_smc
} {
    if {[llength [get_cells -quiet $inst]] == 0} { puts "INST $inst ABSENT"; continue }
    puts "INST $inst [slr_hist $inst]"
}
puts "INSTANCE_SLR_END"

puts "ENGINE_SLR_BEGIN"
foreach inst {
    bd_i/mvchan_0/inst/u_chan/u_engine bd_i/mvchan_1/inst/u_chan/u_engine
    bd_i/mvchan_2/inst/u_chan/u_engine bd_i/mvchan_3/inst/u_chan/u_engine
    bd_i/mvchan_0/inst/u_chan/u_streamer bd_i/mvchan_3/inst/u_chan/u_streamer
    bd_i/layer_0/inst/u_core/u_dn bd_i/layer_0/inst/u_core/u_topk
    bd_i/layer_0/inst/u_core/u_attn bd_i/layer_0/inst/u_core/u_alu
} {
    if {[llength [get_cells -quiet $inst]] == 0} { puts "ENG $inst ABSENT"; continue }
    puts "ENG $inst [slr_hist $inst]"
}
puts "ENGINE_SLR_END"

# ------------------------- MIG anchors: which clock regions does each MIG own?
puts "MIG_ANCHOR_BEGIN"
foreach i {0 1 2 3} {
    set cs [get_cells -quiet -hier -filter "PRIMITIVE_LEVEL == LEAF && NAME =~ bd_i/ddr4_$i/*"]
    # The MIG's IMMOVABLE part is its XIPHY/BITSLICE/CMT hardware, which is tied
    # to the memory-interface IO banks. Report the clock regions those occupy —
    # those are the anchor coordinates a floorplan has to be drawn around.
    set regions {}
    foreach st [get_sites -quiet -of_objects $cs] {
        set ty [get_property SITE_TYPE $st]
        if {![regexp {BITSLICE|XIPHY|RIU|MMCM|PLL|BUFGC} $ty]} { continue }
        set c [get_property CLOCK_REGION $st]
        if {$c ne ""} { lappend regions $c }
    }
    set regions [lsort -unique $regions]
    # SLICE-side spread of the same MIG, for contrast
    puts "MIG ddr4_$i anchor_clock_regions={$regions}"
    puts "MIG ddr4_$i slice_spread: [slr_hist bd_i/ddr4_$i]"
}
puts "MIG_ANCHOR_END"

# ------------------------------------------------ 4. do-not-pblock inventory
puts "FIXED_SITE_BEGIN"
foreach c [get_cells -quiet -hier -filter {REF_NAME =~ PCIE4*}] {
    set st [get_sites -quiet -of_objects $c]
    puts "PCIE $c LOC=[get_property LOC $c] CR=[get_property CLOCK_REGION $st]"
}
set gts [get_cells -quiet -hier -filter {REF_NAME =~ GTYE4_CHANNEL*}]
puts "GT_COUNT: [llength $gts]"
foreach c $gts {
    set st [get_sites -quiet -of_objects $c]
    puts "GT [get_property LOC $c] CR=[get_property CLOCK_REGION $st]"
}
puts "FIXED_SITE_END"

# --------------------------------------------------- per-SLR resource ceilings
puts "SLR_CAPACITY_BEGIN"
foreach s [get_slrs] {
    set nm [get_property NAME $s]
    array unset t; array set t {}
    foreach st [get_sites -quiet -of_objects $s] {
        set ty [get_property SITE_TYPE $st]
        if {[info exists t($ty)]} { incr t($ty) } else { set t($ty) 1 }
    }
    foreach ty [lsort [array names t]] {
        if {[regexp {^(SLICEL|SLICEM|DSP48E2|RAMB36E2|RAMB18E2|URAM288)$} $ty]} {
            puts [format "CAP %s %-10s %d" $nm $ty $t($ty)]
        }
    }
}
puts "SLR_CAPACITY_END"
puts "SLRCENSUS_OK"
