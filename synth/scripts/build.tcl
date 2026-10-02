# build.tcl — synth + impl + bitstream for an already-created stage1 project.
# Usage: vivado -mode batch -source build.tcl -tclargs <out_dir> [synth_only]
# Writes reports and artifacts into <out_dir>/reports and <out_dir>/.
# R3-0 (ii) (evidence/qwen9b/sr/R3_0_TOOLING.md): the optional second word
# `synth_only` (synth/scripts/launch_build.sh passes it under SYNTH_ONLY=1)
# stops after synth_1 at 100 % — prints SYNTH_OK and exits WITHOUT
# launch_runs impl_1, leaving the synth_1 checkpoint for
# synth/scripts/launch_incr.sh — so no base roll runs and no same-VERSION twin
# bitstream is written (SR14 §1.2, §4).  The post-impl sanity checks are the
# two procs of synth/scripts/postimpl_sanity.tcl, called where the blocks
# stood (same printed lines, same order).  With one word: as before.

if {[llength $argv] < 1} { puts "FATAL: need <out_dir>"; exit 1 }
set OutDir [lindex $argv 0]
set SynthOnly 0
if {[llength $argv] > 1} {
    if {[llength $argv] == 2 && [lindex $argv 1] eq "synth_only"} {
        set SynthOnly 1
    } else {
        puts "FATAL: unknown arguments after <out_dir>: [lrange $argv 1 end] (only `synth_only`)"; exit 1
    }
}

proc must {script} {
    if {[catch {uplevel 1 $script} err]} {
        puts "FATAL: $err"
        exit 1
    }
}
must {source -notrace [file join [file dirname [file normalize [info script]]] postimpl_sanity.tcl]}

set_param general.maxThreads 16

must {open_project $OutDir/proj/stage1.xpr}
file mkdir $OutDir/reports

must {launch_runs synth_1 -jobs 16}
must {wait_on_run synth_1}
if {[get_property PROGRESS [get_runs synth_1]] != "100%"} {
    puts "FATAL: synthesis failed"; exit 1
}
if {$SynthOnly} {
    set sdcp [glob -nocomplain [get_property DIRECTORY [get_runs synth_1]]/*.dcp]
    puts "SYNTH_OK: synth_1 100% (synth_only: impl_1 NOT launched, no bitstream) checkpoint: $sdcp"
    close_project
    exit 0
}

must {launch_runs impl_1 -to_step write_bitstream -jobs 16}
must {wait_on_run impl_1}
if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
    puts "FATAL: implementation failed"; exit 1
}

must {open_run impl_1}

# Clock-sanity gate (added after the unconstrained-pcie_refclk incident):
# the XDMA axi_aclk domain (250 MHz / 4 ns) MUST exist as a timed clock, and
# unconstrained register pins are enumerated — synth/scripts/postimpl_sanity.tcl
postimpl_clock_gate $OutDir/reports

must {report_timing_summary -file $OutDir/reports/timing_summary.rpt}
must {report_utilization -file $OutDir/reports/utilization.rpt}
must {report_utilization -hierarchical -file $OutDir/reports/utilization_hier.rpt}
must {report_clock_utilization -file $OutDir/reports/clock_util.rpt}
must {report_drc -file $OutDir/reports/drc.rpt}

# headline numbers into the log
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
puts "TIMING: WNS=$wns WHS=$whs"

# PCIe block + GT placement sanity (must be quad 226/227 per board wiring)
# — synth/scripts/postimpl_sanity.tcl
postimpl_loc_print

set bit [glob -nocomplain $OutDir/proj/stage1.runs/impl_1/*.bit]
puts "BITSTREAM: $bit"
puts "BUILD_OK"
