# dev_geom_census.tcl — G5a Step 1 input: the xcvu9p-fsgd2104-2L-e site
# geometry the 9B floorplan candidates are written against, MEASURED off the
# device rather than assumed.  fable5_floorplan_a.xdc's header carries the
# SLR -> CLOCKREGION map (SLR0 = X0Y0..X5Y4, SLR1 = X0Y5..X5Y9,
# SLR2 = X0Y10..X5Y14); what it does NOT carry is the per-CLOCKREGION URAM288
# / DSP48E2 / RAMB36 census, and a DN-array pblock is exactly a URAM-capacity
# constraint.  Standing rule: check DSP and BRAM capacity per SLR before
# constraining anything.
#
#   vivado -mode batch -nojournal -source dev_geom_census.tcl
set Part xcvu9p-fsgd2104-2L-e
if {[string compare [version -short] "2024.2"] != 0} {
    puts "FATAL: expects Vivado 2024.2, got [version -short]"; exit 1
}
create_project -in_memory -part $Part
link_design -part $Part
puts "GEOM_PART: $Part"

# ---- totals, so the per-region table is checkable against a known number
foreach {label pat} {URAM288 URAM288* DSP48E2 DSP48E2* RAMBFIFO36 RAMBFIFO36* RAMB181 RAMB18* SLICE SLICE*} {
    puts "GEOM_TOTAL $label [llength [get_sites -quiet -filter "SITE_TYPE =~ $pat"]]"
}

# ---- per clock region.  A site's clock region comes from get_clock_regions
# -of_objects; the CLOCK_REGION *property* is not carried by every site class,
# so the object query is the safe form.
array set cr_ur {} ; array set cr_ds {} ; array set cr_bs {}
foreach {arr pat} {cr_ur URAM288* cr_ds DSP48E2* cr_bs RAMBFIFO36*} {
    upvar 0 $arr A
    foreach s [get_sites -quiet -filter "SITE_TYPE =~ $pat"] {
        set c [get_clock_regions -quiet -of_objects $s]
        if {$c eq ""} { set c "?" } else { set c [get_property NAME $c] }
        if {[info exists A($c)]} { incr A($c) } else { set A($c) 1 }
    }
}
puts "GEOM_TABLE clockregion uram288 dsp48e2 rambfifo36"
foreach c [lsort -dictionary [array names cr_ur]] {
    set d 0; set b 0
    if {[info exists cr_ds($c)]} { set d $cr_ds($c) }
    if {[info exists cr_bs($c)]} { set b $cr_bs($c) }
    puts [format "GEOM_CR %-12s %4d %5d %5d" $c $cr_ur($c) $d $b]
}
# clock regions with no URAM at all still matter for the DSP/BRAM check
foreach c [lsort -dictionary [array names cr_ds]] {
    if {![info exists cr_ur($c)]} {
        set b 0; if {[info exists cr_bs($c)]} { set b $cr_bs($c) }
        puts [format "GEOM_CR %-12s %4d %5d %5d" $c 0 $cr_ds($c) $b]
    }
}

# ---- per SLR, and the URAM column list per SLR (the DN pblock's real limit)
foreach slr [get_slrs] {
    set n [get_property NAME $slr]
    set us [get_sites -quiet -of_objects $slr -filter {SITE_TYPE =~ URAM288*}]
    set ds [get_sites -quiet -of_objects $slr -filter {SITE_TYPE =~ DSP48E2*}]
    set bs [get_sites -quiet -of_objects $slr -filter {SITE_TYPE =~ RAMBFIFO36*}]
    set sl [get_sites -quiet -of_objects $slr -filter {SITE_TYPE =~ SLICE*}]
    puts [format "GEOM_SLR %-6s uram=%d dsp=%d rambfifo36=%d slice=%d" $n [llength $us] [llength $ds] [llength $bs] [llength $sl]]
    array unset col; array set col {}
    foreach s $us {
        regexp {URAM288_X(\d+)Y(\d+)} [get_property NAME $s] -> x y
        lappend col($x) $y
    }
    foreach x [lsort -integer [array names col]] {
        set ys [lsort -integer $col($x)]
        puts [format "GEOM_SLR_URAMCOL %-6s X%s  n=%d  Y%s..Y%s" \
            $n $x [llength $ys] [lindex $ys 0] [lindex $ys end]]
    }
}
puts "GEOM_DONE"
