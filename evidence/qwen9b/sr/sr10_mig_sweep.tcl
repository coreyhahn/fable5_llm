# sr10_mig_sweep.tcl — Task SR10 step 1, second pass: EVERY integer DDR4
# memory-clock period from 833 to 940 ps (the 5 % UI-cut point is 877, the
# DDR4-2133 grade 938), asked of the MIG (ddr4 v2.2) with this design's
# configuration (synth/scripts/create_project.tcl:166-176 minus the explicit
# CLKOUT0_DIVIDE, which is only right at 833), InputClockPeriod 3332 fixed.
# Why a second pass: n1001 showed the MIG refuses a period by refusing the
# 3332 ps refclk ("[IP_Flow 19-3461] Value '3332' is out of the range for
# parameter ... InputClockPeriod ... Valid values are - ..."), so acceptance
# is a property of each period's MMCM ratio, not of a range; a sparse ladder
# cannot say which in-between periods work.
# One IP instance, one set_property -dict per period (a refused set is
# rolled back by Vivado to the previous valid configuration); no
# validate-then-generate here (n1001 does that for the ladder), no synthesis,
# no run.  NEW scratch project synth/out_sr10_mig_probe_sweep/ (refuses if it
# exists; the n1001 project dir is not reused).  Per period it prints the
# verdict, what the IP holds afterwards (period, refclk, M/D/O), and, on a
# refusal, the valid refclk periods within 3300..3370 from Vivado's message.
# Lines are prefixed MIGS_.

set root  [file normalize [file join [file dirname [info script]] ../../..]]
set out   $root/synth/out_sr10_mig_probe_sweep
set csv   $root/synth/constraints/BLS4G4D240FSB.csv
if {[file exists $out]} {
    puts "MIGS_REFUSE: $out exists — out dirs are never reused"
    exit 2
}
file mkdir $out
create_project sr10_mig_sweep $out/proj -part xcvu9p-fsgd2104-2L-e
import_files -norecurse $csv
set csv_file [lindex [get_files */BLS4G4D240FSB.csv] 0]
set name ddr4_sweep
create_ip -name ddr4 -vendor xilinx.com -library ip -version 2.2 -module_name $name
set ip [get_ips $name]
set lo 833; set hi 940
if {[info exists ::env(SR10_SWEEP_LO)]} { set lo $::env(SR10_SWEEP_LO) }
if {[info exists ::env(SR10_SWEEP_HI)]} { set hi $::env(SR10_SWEEP_HI) }
puts "MIGS_RANGE: $lo..$hi"
set nacc 0; set nref 0; set acc_list [list]
for {set P $lo} {$P <= $hi} {incr P} {
    set cfg [list \
        CONFIG.C0.DDR4_TimePeriod $P \
        CONFIG.C0.DDR4_InputClockPeriod 3332 \
        CONFIG.C0.DDR4_CustomParts $csv_file \
        CONFIG.C0.DDR4_isCustom true \
        CONFIG.C0.DDR4_MemoryType UDIMMs \
        CONFIG.C0.DDR4_MemoryPart BLS4G4D240FSB-2400 \
        CONFIG.C0.DDR4_DataWidth 64 \
        CONFIG.C0.DDR4_AxiSelection true]
    set t0 [clock milliseconds]
    set ok [expr {![catch {set_property -dict $cfg $ip} err]}]
    set t1 [clock milliseconds]
    set rb [list]
    foreach p {TimePeriod InputClockPeriod MemoryPart CLKFBOUT_MULT DIVCLK_DIVIDE CLKOUT0_DIVIDE CasLatency CasWriteLatency} {
        set v "?"; catch {set v [get_property CONFIG.C0.DDR4_$p $ip]}
        lappend rb "$p=$v"
    }
    set held [expr {$ok && [get_property CONFIG.C0.DDR4_TimePeriod $ip] == $P \
                        && [get_property CONFIG.C0.DDR4_InputClockPeriod $ip] == 3332 \
                        && [get_property CONFIG.C0.DDR4_MemoryPart $ip] eq "BLS4G4D240FSB-2400"}]
    set cut [expr {100.0 * (1.0 - 833.0 / $P)}]
    set ui  [expr {1.0e6 / (4.0 * $P)}]
    if {$held} {
        incr nacc; lappend acc_list $P
        set m [get_property CONFIG.C0.DDR4_CLKFBOUT_MULT $ip]
        set d [get_property CONFIG.C0.DDR4_DIVCLK_DIVIDE $ip]
        set o [get_property CONFIG.C0.DDR4_CLKOUT0_DIVIDE $ip]
        # MMCM CLKOUT0 from the 3332 ps refclk: 3332 * D * O / M (ps); VCO = M/(D*3332 ps)
        set mmcm_ps [expr {3332.0 * $d * $o / $m}]
        set vco [expr {1.0e6 * $m / ($d * 3332.0)}]
        puts [format "MIGS_ROW: P=%4d cut=%6.3f%% UI(1/4P)=%8.3fMHz ACCEPTED M=%s D=%s O=%s mmcm_clkout0=%.3fps(=%.3fMHz) 4P=%d vco=%.1fMHz t=%dms | %s" \
              $P $cut $ui $m $d $o $mmcm_ps [expr {1.0e6/$mmcm_ps}] [expr {4*$P}] $vco [expr {$t1-$t0}] [join $rb " "]]
    } else {
        incr nref
        set near "-"
        # the refusal text is in the Vivado log line just printed; the Tcl
        # error string only says "failed due to earlier errors", so the
        # 19-3461 message is recovered from the log by the gate doc's grep.
        puts [format "MIGS_ROW: P=%4d cut=%6.3f%% UI(1/4P)=%8.3fMHz REFUSED set_ok=%d t=%dms err={%s} | holds: %s" \
              $P $cut $ui $ok [expr {$t1-$t0}] [string map {\n " | "} $err] [join $rb " "]]
    }
}
puts "MIGS_SUMMARY: range $lo..$hi accepted=$nacc refused=$nref"
puts "MIGS_ACCEPTED: $acc_list"
close_project
puts "MIGS_DONE"
