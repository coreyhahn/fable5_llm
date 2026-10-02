# sr10_mig_mandd.tcl — Task SR10 step 1, third pass: the MIG's own
# "Specify M and D" option (C0.DDR4_Specify_MandD, xgui ddr4_v2_2.tcl:1327-1346:
# with it set, the IP DERIVES the input-clock period from TimePeriod and the
# user's CLKFBOUT_MULT / DIVCLK_DIVIDE / CLKOUT0_DIVIDE).  n1002 showed that
# in the default (automatic M/D) mode only 833, 877 and 937 ps accept the
# 3332 ps refclk in 833..940.  This pass asks whether the periods in between
# (834..876, the < 5 % cuts) become legal with hand-picked integer M/D/O.
# For each period P the script searches (in Tcl, on snoke) integer M 2..128,
# D 1..30, O 1..128 with the MMCM's VCO in 800..1600 MHz and PFD in
# 10..500 MHz for 3332*D*O/M closest to 4P, then asks the IP:
#   form A: Specify_MandD true + M/D/O + TimePeriod P + InputClockPeriod 3332
#   form B (only if A is refused): the same without InputClockPeriod,
#           recording what refclk the IP then holds.
# Controls: 833 with M/D/O = 5/1/5 (the shipped values), and 834 with 5/1/5
# (a deliberately wrong ratio: the refclk it implies is 3336, not 3332).
# At the end ONE accepted sub-5 % period (the one nearest a 2 % cut) is
# re-created in its own IP instance and generate_target'ed, and its
# generated XDC and MMCM parameters are printed.  set_property /
# generate_target only — no synthesis, no run.  NEW scratch project
# synth/out_sr10_mig_probe_mandd/ (refuses if it exists).  Lines MIGM_.

set root  [file normalize [file join [file dirname [info script]] ../../..]]
set out   $root/synth/out_sr10_mig_probe_mandd
set csv   $root/synth/constraints/BLS4G4D240FSB.csv
if {[file exists $out]} {
    puts "MIGM_REFUSE: $out exists — out dirs are never reused"
    exit 2
}
file mkdir $out
create_project sr10_mig_mandd $out/proj -part xcvu9p-fsgd2104-2L-e
import_files -norecurse $csv
set csv_file [lindex [get_files */BLS4G4D240FSB.csv] 0]
set fin_mhz [expr {1.0e6 / 3332.0}]

proc base_cfg {P csv_file} {
    return [list \
        CONFIG.C0.DDR4_TimePeriod $P \
        CONFIG.C0.DDR4_CustomParts $csv_file \
        CONFIG.C0.DDR4_isCustom true \
        CONFIG.C0.DDR4_MemoryType UDIMMs \
        CONFIG.C0.DDR4_MemoryPart BLS4G4D240FSB-2400 \
        CONFIG.C0.DDR4_DataWidth 64 \
        CONFIG.C0.DDR4_AxiSelection true]
}

# candidates sorted by |3332*D*O/M - 4P|, then D, then M
proc candidates {P fin_mhz} {
    set out [list]
    for {set D 1} {$D <= 30} {incr D} {
        set pfd [expr {$fin_mhz / $D}]
        if {$pfd < 10.0 || $pfd > 500.0} continue
        for {set M 2} {$M <= 128} {incr M} {
            set vco [expr {$fin_mhz * $M / $D}]
            if {$vco < 800.0 || $vco > 1600.0} continue
            set O [expr {int(round(4.0 * $P * $M / (3332.0 * $D)))}]
            if {$O < 1 || $O > 128} continue
            set ui_ps [expr {3332.0 * $D * $O / $M}]
            set clkin_ps [expr {4.0 * $P * $M / ($D * $O)}]
            set err [expr {abs($clkin_ps - 3332.0)}]
            if {$err < 2.0} { lappend out [list $err $D $M $O $ui_ps $clkin_ps $vco] }
        }
    }
    return [lsort -real -index 0 [lsort -integer -index 2 [lsort -integer -index 1 $out]]]
}

proc hold {ip} {
    set r [list]
    foreach p {TimePeriod InputClockPeriod Specify_MandD CLKFBOUT_MULT DIVCLK_DIVIDE CLKOUT0_DIVIDE MemoryPart CasLatency} {
        set v "?"; catch {set v [get_property CONFIG.C0.DDR4_$p $ip]}
        lappend r "$p=$v"
    }
    return [join $r " "]
}

set name ddr4_mandd
create_ip -name ddr4 -vendor xilinx.com -library ip -version 2.2 -module_name $name
set ip [get_ips $name]

proc try_one {ip P M D O csv_file tag} {
    set cfg [base_cfg $P $csv_file]
    lappend cfg CONFIG.C0.DDR4_Specify_MandD true CONFIG.C0.DDR4_CLKFBOUT_MULT $M \
                CONFIG.C0.DDR4_DIVCLK_DIVIDE $D CONFIG.C0.DDR4_CLKOUT0_DIVIDE $O
    set cfgA $cfg; lappend cfgA CONFIG.C0.DDR4_InputClockPeriod 3332
    set okA [expr {![catch {set_property -dict $cfgA $ip} e]}]
    set hA [hold $ip]
    set heldA [expr {$okA && [get_property CONFIG.C0.DDR4_TimePeriod $ip] == $P
                          && [get_property CONFIG.C0.DDR4_InputClockPeriod $ip] == 3332
                          && [get_property CONFIG.C0.DDR4_CLKFBOUT_MULT $ip] == $M
                          && [get_property CONFIG.C0.DDR4_DIVCLK_DIVIDE $ip] == $D
                          && [get_property CONFIG.C0.DDR4_CLKOUT0_DIVIDE $ip] == $O}]
    if {$heldA} {
        puts "MIGM_TRY: $tag P=$P M=$M D=$D O=$O formA ACCEPTED | $hA"
        return 1
    }
    puts "MIGM_TRY: $tag P=$P M=$M D=$D O=$O formA REFUSED ok=$okA | $hA"
    set okB [expr {![catch {set_property -dict $cfg $ip} e]}]
    set hB [hold $ip]
    puts "MIGM_TRY: $tag P=$P M=$M D=$D O=$O formB set_ok=$okB | $hB"
    return 0
}

puts "MIGM_CONTROL_BEGIN"
try_one $ip 833 5 1 5 $csv_file CONTROL_833_shipped
try_one $ip 834 5 1 5 $csv_file CONTROL_834_wrong_ratio
puts "MIGM_CONTROL_END"

set acc [list]
foreach P [concat [list] [lsort -integer [list 834 835 836 837 838 839 840 841 842 843 844 845 846 847 848 849 850 851 852 853 854 855 856 857 858 859 860 861 862 863 864 865 866 867 868 869 870 871 872 873 874 875 876]]] {
    set c [candidates $P $fin_mhz]
    set cut [expr {100.0 * (1.0 - 833.0 / $P)}]
    if {![llength $c]} {
        puts [format "MIGM_ROW: P=%d cut=%.3f%% NO_CANDIDATE (no integer M/D/O within 2 ps of 3332)" $P $cut]
        continue
    }
    set got 0; set k 0
    foreach cand [lrange $c 0 2] {
        lassign $cand err D M O ui_ps clkin_ps vco
        incr k
        if {[try_one $ip $P $M $D $O $csv_file "P${P}_c$k"]} {
            set got 1
            set ui_mhz [expr {1.0e6 / $ui_ps}]
            set ucut [expr {100.0 * (1.0 - 3332.0 / $ui_ps)}]
            puts [format "MIGM_ROW: P=%d cut=%.3f%% ACCEPTED M=%d D=%d O=%d ui_clk=%.3fps(%.3fMHz, UI cut %.3f%%) implied_clkin=%.3fps vco=%.1fMHz" \
                  $P $cut $M $D $O $ui_ps $ui_mhz $ucut $clkin_ps $vco]
            lappend acc [list $P $M $D $O]
            break
        }
    }
    if {!$got} {
        puts [format "MIGM_ROW: P=%d cut=%.3f%% REFUSED (best %d candidates tried; best M/D/O=%s)" $P $cut $k [lrange [lindex $c 0] 1 3]]
    }
}
puts "MIGM_ACCEPTED: $acc"

# generate one accepted sub-5 % period, nearest a 2 % cut (850 ps)
set best ""; set bd 1e9
foreach a $acc { set d [expr {abs([lindex $a 0] - 850)}]; if {$d < $bd} { set bd $d; set best $a } }
if {$best ne ""} {
    lassign $best P M D O
    set gname ddr4_mandd_gen_p$P
    create_ip -name ddr4 -vendor xilinx.com -library ip -version 2.2 -module_name $gname
    set gip [get_ips $gname]
    if {[try_one $gip $P $M $D $O $csv_file GEN_P$P]} {
        if {[catch {generate_target {synthesis instantiation_template} $gip} e]} {
            puts "MIGM_GENERR: {[string map {\n " | "} $e]}"
        } else {
            set gdir [lindex [glob -nocomplain -types d [file join $out proj *.gen sources_1 ip $gname]] 0]
            foreach f [lsort [concat [glob -nocomplain -types f $gdir/*.xdc] [glob -nocomplain -types f $gdir/par/*.xdc] [glob -nocomplain -types f $gdir/rtl/ip_top/*.sv] [glob -nocomplain -types f $gdir/*.sv]]] {
                set fh [open $f r]; set ln 0
                while {[gets $fh line] >= 0} {
                    incr ln
                    if {[string length $line] > 300} continue
                    if {[regexp {create_clock|PhyIP_CLKFBOUT_MULT|PhyIP_DIVCLK_DIVIDE|PhyIP_CLKOUT0_DIVIDE|PhyIP_tCK|parameter\s+tCK\s|parameter\s+CLKIN_PERIOD_MMCM|parameter\s+CLKFBOUT_MULT_MMCM|parameter\s+DIVCLK_DIVIDE_MMCM|parameter\s+CLKOUT0_DIVIDE_MMCM} $line]} {
                        puts "MIGM_GEN: [file tail $f]:$ln: [string trim $line]"
                    }
                }
                close $fh
            }
        }
    }
}
close_project
puts "MIGM_DONE"
