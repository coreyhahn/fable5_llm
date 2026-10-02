# sr10_mig_period.tcl — Task SR10 step 1: which DDR4 memory-clock periods
# (C0.DDR4_TimePeriod) the MIG (ddr4 v2.2) ACCEPTS for this design's custom
# part (synth/constraints/BLS4G4D240FSB.csv, BLS4G4D240FSB-2400) with the
# 300 MHz DIMM refclk (InputClockPeriod 3332 ps), read from Vivado's own
# validation.  One DDR4 IP instance per period, in a NEW scratch project
# under synth/out_sr10_mig_probe/ (the script refuses if it exists); no
# existing project is opened.  Per instance: set_property with the
# configuration of synth/scripts/create_project.tcl:166-176 except the period
# (and, in the "noDIV" variant, without the explicit CLKOUT0_DIVIDE 5 that is
# only right for 833 ps), read back what the IP holds, validate_ip, then
# generate_target {synthesis instantiation_template} (output products only —
# NO synth_design, NO create_ip_run, NO launch_runs, generate_synth_checkpoint
# false) and scan the generated files for the MMCM settings and create_clock.
#
#   ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm && bash evidence/qwen9b/sr/sr_run.sh \
#     n10xx_....log bash -c "source /home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh >/dev/null \
#     && cd /tmp && exec vivado -mode batch -nojournal -nolog -source evidence/.../sr10_mig_period.tcl"'
#
# Output lines are prefixed MIGP_ for grepping.

set root  [file normalize [file join [file dirname [info script]] ../../..]]
set out   $root/synth/out_sr10_mig_probe
set csv   $root/synth/constraints/BLS4G4D240FSB.csv
if {[file exists $out]} {
    puts "MIGP_REFUSE: $out exists — out dirs are never reused"
    exit 2
}
file mkdir $out
puts "MIGP_OUT: $out"
create_project sr10_mig_probe $out/proj -part xcvu9p-fsgd2104-2L-e
import_files -norecurse $csv
set csv_file [lindex [get_files */BLS4G4D240FSB.csv] 0]
puts "MIGP_CSV: $csv_file"

# ---- the ladder --------------------------------------------------------
# UI clock = 1 / (4 * tCK) (PhyClockRatio 4:1); a UI cut r means
# tCK = 833 / (1 - r).  The script computes each cut's period and prints it.
set base 833
set ladder [list]
lappend ladder [list $base "baseline (DDR4-2400)" BLS4G4D240FSB-2400]
lappend ladder [list 834 "1 ps step" BLS4G4D240FSB-2400]
foreach pct {1 2 3 4 5} {
    set exact [expr {$base / (1.0 - $pct / 100.0)}]
    set p [expr {int(round($exact))}]
    puts [format "MIGP_CUT: %d %% UI cut -> tCK %.3f ps -> integer %d ps (cut %.3f %%)" \
            $pct $exact $p [expr {100.0 * (1.0 - double($base) / $p)}]]
    lappend ladder [list $p "${pct} % UI cut" BLS4G4D240FSB-2400]
    if {$pct == 5} {
        set pf [expr {int(floor($exact))}]
        lappend ladder [list $pf "5 % cut, floor (just under 5 %)" BLS4G4D240FSB-2400]
    }
}
foreach p {896 926} { lappend ladder [list $p "beyond 5 %" BLS4G4D240FSB-2400] }
lappend ladder [list 938  "next grade tCK (DDR4-2133), -2400 part" BLS4G4D240FSB-2400]
lappend ladder [list 938  "next grade, -2133 part row of the CSV"  BLS4G4D240FSB-2133]
lappend ladder [list 1071 "DDR4-1866 tCK, -2400 part" BLS4G4D240FSB-2400]
lappend ladder [list 1600 "CSV Max period of the -2400 row" BLS4G4D240FSB-2400]
# negative controls: outside the CSV row's Min/Max period (833..1600)
lappend ladder [list 750  "CONTROL: faster than part min 833" BLS4G4D240FSB-2400]
lappend ladder [list 1700 "CONTROL: slower than part max 1600" BLS4G4D240FSB-2400]

proc msgcounts {} {
    set e 0; set c 0
    catch {set e [get_msg_config -count -severity ERROR]}
    catch {set c [get_msg_config -count -severity {CRITICAL WARNING}]}
    return [list $e $c]
}

proc readback {ip tag} {
    foreach p {CONFIG.C0.DDR4_TimePeriod CONFIG.C0.DDR4_InputClockPeriod
               CONFIG.C0.DDR4_Specify_MandD CONFIG.C0.DDR4_CLKFBOUT_MULT
               CONFIG.C0.DDR4_DIVCLK_DIVIDE CONFIG.C0.DDR4_CLKOUT0_DIVIDE
               CONFIG.C0.DDR4_PhyClockRatio CONFIG.C0.DDR4_MemoryPart
               CONFIG.C0.DDR4_isCustom CONFIG.C0.DDR4_CasLatency
               CONFIG.C0.DDR4_CasWriteLatency CONFIG.C0.DDR4_DataWidth} {
        set v "<none>"
        catch {set v [get_property $p $ip]}
        puts "MIGP_RB: $tag $p = {$v}"
    }
}

proc scan_generated {ip tag} {
    set d [get_property IP_DIR $ip]
    set gdir ""
    # output products land under <proj>.gen/sources_1/ip/<name>
    set cand [glob -nocomplain -types d [file join [get_property DIRECTORY [current_project]] *.gen sources_1 ip [get_property NAME $ip]]]
    if {[llength $cand]} { set gdir [lindex $cand 0] } else { set gdir $d }
    puts "MIGP_GENDIR: $tag $gdir"
    set files [list]
    foreach pat {*.sv *.v *.xdc par/*.xdc rtl/ip_top/*.sv rtl/clocking/*.sv} {
        foreach f [glob -nocomplain -types f [file join $gdir $pat]] { lappend files $f }
    }
    set n 0
    foreach f [lsort -unique $files] {
        if {[catch {set fh [open $f r]}]} continue
        set ln 0
        while {[gets $fh line] >= 0} {
            incr ln
            if {[string length $line] > 300} continue
            if {[regexp {CLKIN_PERIOD|CLKFBOUT_MULT|DIVCLK_DIVIDE|CLKOUT0_DIVIDE|create_clock|tCK\s|\stCK\s*=|UI_CLOCK|nCK_PER_CLK|MMCM_CLKOUT|CLKOUT0_PHASE} $line]} {
                if {$n < 60} {
                    puts "MIGP_GEN: $tag [file tail $f]:$ln: [string trim $line]"
                }
                incr n
            }
        }
        close $fh
    }
    puts "MIGP_GENLINES: $tag $n"
}

set results [list]
set i 0
foreach row $ladder {
    lassign $row P why part
    foreach variant {noDIV asPROJ} {
        # the -2133 row and the controls: noDIV only; generate only for noDIV
        if {$variant eq "asPROJ" && ($part ne "BLS4G4D240FSB-2400" || [string match CONTROL* $why])} continue
        incr i
        set name [format "ddr4_p%d_%s_%02d" $P $variant $i]
        set tag  "$name"
        puts "MIGP_BEGIN: $tag period=$P part=$part variant=$variant why={$why}"
        lassign [msgcounts] e0 c0
        set ip [create_ip -name ddr4 -vendor xilinx.com -library ip -version 2.2 -module_name $name]
        set ip [get_ips $name]
        catch {set_property generate_synth_checkpoint false [get_files -of_objects $ip *.xci]}
        set cfg [list \
            CONFIG.C0.DDR4_TimePeriod $P \
            CONFIG.C0.DDR4_InputClockPeriod 3332 \
            CONFIG.C0.DDR4_CustomParts $csv_file \
            CONFIG.C0.DDR4_isCustom true \
            CONFIG.C0.DDR4_MemoryType UDIMMs \
            CONFIG.C0.DDR4_MemoryPart $part \
            CONFIG.C0.DDR4_DataWidth 64 \
            CONFIG.C0.DDR4_AxiSelection true]
        if {$variant eq "asPROJ"} { lappend cfg CONFIG.C0.DDR4_CLKOUT0_DIVIDE 5 }
        set setok 1
        if {[catch {set_property -dict $cfg $ip} err]} {
            set setok 0
            puts "MIGP_SETERR: $tag {[string map {\n " | "} $err]}"
        }
        readback $ip $tag
        set rbP 0; set rbI 0; set rbPart ""
        catch {set rbP [get_property CONFIG.C0.DDR4_TimePeriod $ip]}
        catch {set rbI [get_property CONFIG.C0.DDR4_InputClockPeriod $ip]}
        catch {set rbPart [get_property CONFIG.C0.DDR4_MemoryPart $ip]}
        set valok 1
        if {[catch {validate_ip $ip} err]} {
            set valok 0
            puts "MIGP_VALERR: $tag {[string map {\n " | "} $err]}"
        }
        set genok "-"
        if {$variant eq "noDIV" && $setok && $valok} {
            set genok 1
            if {[catch {generate_target {synthesis instantiation_template} $ip} err]} {
                set genok 0
                puts "MIGP_GENERR: $tag {[string map {\n " | "} $err]}"
            }
            if {$genok} { scan_generated $ip $tag }
        }
        lassign [msgcounts] e1 c1
        set de [expr {$e1 - $e0}]; set dc [expr {$c1 - $c0}]
        set held [expr {$rbP == $P && $rbI == 3332 && $rbPart eq $part}]
        set acc [expr {$setok && $valok && $held && $genok ne "0" && $de == 0}]
        set verdict [expr {$acc ? "ACCEPTED" : "REFUSED"}]
        set ui_mhz [expr {1.0e6 / (4.0 * $P)}]
        set cut [expr {100.0 * (1.0 - double($base) / $P)}]
        set line [format "MIGP_ROW: %-28s P=%4d cut=%6.3f%% UI=%8.3fMHz part=%s set=%d validate=%d held(P,refclk,part)=%d gen=%s newERR=%d newCW=%d rbP=%s rbRef=%s => %s" \
                    $tag $P $cut $ui_mhz $part $setok $valok $held $genok $de $dc $rbP $rbI $verdict]
        puts $line
        lappend results $line
    }
}
puts "MIGP_SUMMARY_BEGIN"
foreach l $results { puts $l }
puts "MIGP_SUMMARY_END"
close_project
puts "MIGP_DONE"
