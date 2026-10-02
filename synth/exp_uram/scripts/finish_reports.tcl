# finish_reports.tcl — complete a G5a run's post-place report set from its
# saved post_place.dcp.
#
# WHY THIS EXISTS.  The seven G5a placement runs used exp_ooc.tcl as committed
# at 5ee5f0e, which carried two defects that bite only AFTER place_design:
#   (a) it looked for the DN final bank-mux OREG as `dn_rdq_n_reg`, the
#       EXPERIMENT COPY's name.  The shipping rtl/ calls it `dn_rdq`
#       (rtl/layer_chan.sv:508, :652), so the search matched nothing and the
#       script recorded "the mux register was absorbed" — a WRONG ANSWER
#       rather than an error, and exactly the DN-mux column the gate doc needs.
#   (b) the timing-summary parse reused `h`, which is an ARRAY earlier in the
#       same script, so `regexp ... -> ... h` died with `can't set "h":
#       variable is array` at the very last marker.
# Both are fixed in exp_ooc.tcl now.  The PLACEMENTS are unaffected — they were
# written to post_place.dcp before either defect fired — so the missing
# sections are re-derived from the checkpoint rather than by re-placing, which
# would have been a different placer draw and therefore a different design.
#
#   vivado -mode batch -nojournal -source finish_reports.tcl -tclargs <run_out_dir>
#
# Markers are FIN_-prefixed so they can never be confused with the EXP_ stream
# the original run emitted; collect_evidence.sh picks up both.
if {[llength $argv] < 1} { puts "FATAL: need <run_out_dir>"; exit 1 }
set OutDir [lindex $argv 0]
set Dcp    $OutDir/post_place.dcp
if {![file exists $Dcp]} { puts "FATAL: no $Dcp"; exit 1 }
file mkdir $OutDir/reports
set_param general.maxThreads 8
puts "FIN_DCP: $Dcp"
open_checkpoint $Dcp
puts "FIN_TOP: [get_property TOP [current_design]]"
puts "FIN_PART: [get_property PART [current_design]]"

proc slr_of_cell {c} {
    set st [get_sites -quiet -of_objects $c]
    if {$st eq ""} { return "unplaced" }
    set s [get_slrs -quiet -of_objects $st]
    if {$s eq ""} { return "?" }
    return [get_property NAME $s]
}

# ---- (a) the 2048-bit DN bank-mux read path, at the SHIPPING name ----------
set muxdst [get_cells -quiet -hier -filter {NAME =~ *dn_rdq_reg*}]
puts "FIN_DNMUX_ENDPOINT_CELLS: [llength $muxdst]"
set fh [open $OutDir/reports/dn_bank_mux_paths.rpt w]
puts $fh "DN 2048-bit bank-mux read path — post-PLACE estimate"
puts $fh "endpoint: dn_rdq_reg\[*\] (the registered final DN_GRP:1 mux fed by"
puts $fh "the per-group return registers).  Clock aclk, 4.000 ns / 250 MHz."
puts $fh "Re-derived from post_place.dcp by finish_reports.tcl; see its header."
puts $fh ""
if {[llength $muxdst] > 0} {
    set paths [get_timing_paths -to $muxdst -max_paths 30 -nworst 30 -setup]
    puts $fh [format "%-9s %-9s %-9s %s" slack levels startSLR endSLR]
    foreach pth $paths {
        set sp [get_property STARTPOINT_PIN $pth]
        set ep [get_property ENDPOINT_PIN $pth]
        puts $fh [format "%-9s %-9s %-9s %-9s  %s -> %s" \
            [get_property SLACK $pth] [get_property LOGIC_LEVELS $pth] \
            [slr_of_cell [get_cells -quiet -of_objects $sp]] \
            [slr_of_cell [get_cells -quiet -of_objects $ep]] $sp $ep]
    }
    set w [lindex $paths 0]
    puts "FIN_DNMUX_WORST_SLACK: [get_property SLACK $w]"
    puts "FIN_DNMUX_DECOMP: levels=[get_property LOGIC_LEVELS $w] datapath=[get_property DATAPATH_DELAY $w] logic=[get_property DATAPATH_LOGIC_DELAY $w] route=[get_property DATAPATH_NET_DELAY $w]"
    puts $fh ""
    puts $fh "---- full report_timing on the worst 10 ----"
    close $fh
    report_timing -to $muxdst -max_paths 10 -nworst 10 -setup \
        -file $OutDir/reports/dn_bank_mux_paths.rpt -append
} else {
    puts $fh "NO dn_rdq_reg CELLS FOUND — the mux register was absorbed."
    close $fh
    puts "FIN_DNMUX_WORST_SLACK: n/a"
}

# ---- the KV bank mux.  Try the register name, then the net, then report ----
foreach pat {*at_kvdata_reg* *at_kvdata* *kv_rdq_b*} {
    set kvdst [get_cells -quiet -hier -filter "NAME =~ $pat"]
    puts "FIN_KVMUX_TRY {$pat} -> [llength $kvdst]"
    if {[llength $kvdst] > 0} { break }
}
if {[llength $kvdst] > 0} {
    report_timing -to $kvdst -max_paths 10 -nworst 10 -setup \
        -file $OutDir/reports/kv_bank_mux_paths.rpt
    set kw [lindex [get_timing_paths -to $kvdst -max_paths 1 -nworst 1 -setup] 0]
    puts "FIN_KVMUX_WORST_SLACK: [get_property SLACK $kw]"
} else {
    puts "FIN_KVMUX_WORST_SLACK: n/a"
}

# ---- the KV write fan-out, in FULL.  G5a fix round 1 minor 13: the finding
# ---- that the residual is a KV write-control broadcast rested on a family
# ---- census line and a single slack number; the primary artefact for it is a
# ---- report_timing into the KV URAM write pins, so here it is.
set kvw [get_cells -quiet -hier -filter {REF_NAME =~ URAM288* && NAME =~ *g_kv*}]
puts "FIN_KVWRITE_CELLS: [llength $kvw]"
if {[llength $kvw] > 0} {
    report_timing -to $kvw -max_paths 20 -nworst 20 -setup \
        -file $OutDir/reports/kv_write_fanout_paths.rpt
    set kp [lindex [get_timing_paths -to $kvw -max_paths 1 -nworst 1 -setup] 0]
    set kdl [get_property DATAPATH_DELAY $kp]
    set krd [get_property DATAPATH_NET_DELAY $kp]
    puts "FIN_KVWRITE_WORST_SLACK: [get_property SLACK $kp]"
    puts "FIN_KVWRITE_DECOMP: levels=[get_property LOGIC_LEVELS $kp] datapath=$kdl logic=[get_property DATAPATH_LOGIC_DELAY $kp] route=$krd route_pct=[format %.1f [expr {100.0*$krd/$kdl}]]"
    puts "FIN_KVWRITE_START: [get_property STARTPOINT_PIN $kp]"
    puts "FIN_KVWRITE_END: [get_property ENDPOINT_PIN $kp]"
    puts "FIN_KVWRITE_SLR: [slr_of_cell [get_cells -quiet -of_objects [get_property STARTPOINT_PIN $kp]]] -> [slr_of_cell [get_cells -quiet -of_objects [get_property ENDPOINT_PIN $kp]]]"
    # and where the KV array actually landed, which is 5''s whole question
    array unset kvslr; array set kvslr {}
    foreach c $kvw {
        set sl [slr_of_cell $c]
        if {[info exists kvslr($sl)]} { incr kvslr($sl) } else { set kvslr($sl) 1 }
    }
    set line ""
    foreach sl [lsort [array names kvslr]] { append line "$sl=$kvslr($sl) " }
    puts "FIN_KV_URAM_BY_SLR: $line"
}

# ---- the CONV BRAM write fan-out, in full.  G5a fix round 3: the R-C finding
# ---- (the third family does not yield to the technique) rested on a family
# ---- census line, and its primary artefact should be a report_timing too.
set cvw [get_cells -quiet -hier -filter {NAME =~ *g_cv* && (REF_NAME =~ RAMB36* || REF_NAME =~ RAMB18*)}]
puts "FIN_CONV_BRAM_CELLS: [llength $cvw]"
if {[llength $cvw] > 0} {
    report_timing -to $cvw -max_paths 20 -nworst 20 -setup \
        -file $OutDir/reports/conv_bram_paths.rpt
    set cp [lindex [get_timing_paths -to $cvw -max_paths 1 -nworst 1 -setup] 0]
    set cdl [get_property DATAPATH_DELAY $cp]
    set crd [get_property DATAPATH_NET_DELAY $cp]
    puts "FIN_CONV_WORST_SLACK: [get_property SLACK $cp]"
    puts "FIN_CONV_DECOMP: levels=[get_property LOGIC_LEVELS $cp] datapath=$cdl logic=[get_property DATAPATH_LOGIC_DELAY $cp] route=$crd route_pct=[format %.1f [expr {100.0*$crd/$cdl}]]"
    puts "FIN_CONV_START: [get_property STARTPOINT_PIN $cp]"
    puts "FIN_CONV_END: [get_property ENDPOINT_PIN $cp]"
    puts "FIN_CONV_SLR: [slr_of_cell [get_cells -quiet -of_objects [get_property STARTPOINT_PIN $cp]]] -> [slr_of_cell [get_cells -quiet -of_objects [get_property ENDPOINT_PIN $cp]]]"
    array unset cvslr; array set cvslr {}
    foreach c $cvw {
        set sl [slr_of_cell $c]
        if {[info exists cvslr($sl)]} { incr cvslr($sl) } else { set cvslr($sl) 1 }
    }
    set line ""
    foreach sl [lsort [array names cvslr]] { append line "$sl=$cvslr($sl) " }
    puts "FIN_CONV_BRAM_BY_SLR: $line"
}

# ---- (b) TNS / failing endpoints, off the run's OWN committed summary ------
set tsrpt $OutDir/reports/timing_summary_placed.rpt
if {[file exists $tsrpt]} {
    set fh [open $tsrpt r]; set tsdata [read $fh]; close $fh
    set got 0
    foreach line [split $tsdata \n] {
        if {[regexp {^\s*(-?[0-9.]+)\s+(-?[0-9.]+)\s+(\d+)\s+(\d+)\s+(-?[0-9.]+)\s+(-?[0-9.]+)\s+(\d+)\s+(\d+)\s+} $line \
                -> ts_wns ts_tns ts_tfe ts_tte ts_whs ts_ths ts_hfe ts_hte]} {
            puts "FIN_TIMING_SUMMARY: WNS=$ts_wns TNS=$ts_tns TNS_FAILING_EP=$ts_tfe TNS_TOTAL_EP=$ts_tte WHS=$ts_whs THS=$ts_ths THS_FAILING_EP=$ts_hfe THS_TOTAL_EP=$ts_hte"
            set got 1
            break
        }
    }
    if {!$got} { puts "FIN_TIMING_SUMMARY: PARSE FAILED" }
} else {
    puts "FIN_TIMING_SUMMARY: no timing_summary_placed.rpt"
}

# ---- and re-state the headline numbers off the checkpoint itself, so the
# ---- FIN_ stream stands alone as a record of THIS placement
set wp [lindex [get_timing_paths -max_paths 1 -nworst 1 -setup] 0]
puts "FIN_PLACED_WNS: [get_property SLACK $wp]"
puts "FIN_PLACED_WHS: [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]"
puts "FIN_WNS_START: [get_property STARTPOINT_PIN $wp]"
puts "FIN_WNS_END: [get_property ENDPOINT_PIN $wp]"
set wrdst [get_cells -quiet -hier -filter {REF_NAME =~ URAM288* && NAME =~ *g_dn*}]
set ww [lindex [get_timing_paths -to $wrdst -max_paths 1 -nworst 1 -setup] 0]
puts "FIN_DNWRITE_WORST_SLACK: [get_property SLACK $ww]"
set dl [get_property DATAPATH_DELAY $ww]
set rd [get_property DATAPATH_NET_DELAY $ww]
puts "FIN_DNWRITE_DECOMP: levels=[get_property LOGIC_LEVELS $ww] datapath=$dl logic=[get_property DATAPATH_LOGIC_DELAY $ww] route=$rd route_pct=[format %.1f [expr {100.0*$rd/$dl}]]"
puts "FIN_PBLOCKS: [llength [get_pblocks -quiet]]"
foreach pb [get_pblocks -quiet] {
    puts [format "FIN_PBLOCK %s cells=%d range={%s}" $pb \
        [llength [get_cells -quiet -of_objects $pb]] [get_property GRID_RANGES $pb]]
}
puts "FIN_DONE"
