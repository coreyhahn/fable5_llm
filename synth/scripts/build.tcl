# build.tcl — synth + impl + bitstream for an already-created stage1 project.
# Usage: vivado -mode batch -source build.tcl -tclargs <out_dir>
# Writes reports and artifacts into <out_dir>/reports and <out_dir>/.

if {[llength $argv] < 1} { puts "FATAL: need <out_dir>"; exit 1 }
set OutDir [lindex $argv 0]

proc must {script} {
    if {[catch {uplevel 1 $script} err]} {
        puts "FATAL: $err"
        exit 1
    }
}

set_param general.maxThreads 16

must {open_project $OutDir/proj/stage1.xpr}
file mkdir $OutDir/reports

must {launch_runs synth_1 -jobs 16}
must {wait_on_run synth_1}
if {[get_property PROGRESS [get_runs synth_1]] != "100%"} {
    puts "FATAL: synthesis failed"; exit 1
}

must {launch_runs impl_1 -to_step write_bitstream -jobs 16}
must {wait_on_run impl_1}
if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
    puts "FATAL: implementation failed"; exit 1
}

must {open_run impl_1}

# Clock-sanity gate (added after the unconstrained-pcie_refclk incident):
# the XDMA axi_aclk domain (250 MHz / 4 ns) MUST exist as a timed clock,
# and unconstrained register pins must be enumerated for review.
set clk4 [get_clocks -quiet -filter {PERIOD < 4.05 && PERIOD > 3.95}]
if {[llength $clk4] == 0} {
    puts "FATAL: no 4ns (250MHz) clock found — XDMA clock tree unconstrained"
    exit 1
}
puts "CLOCK_GATE_OK: 250MHz clocks: $clk4"
check_timing -override_defaults no_clock -file $OutDir/reports/check_timing_noclock.rpt
set fh [open $OutDir/reports/check_timing_noclock.rpt r]
set ct [read $fh]; close $fh
if {[regexp {There are (\d+) register/latch pins with no clock} $ct -> n] && $n > 0} {
    puts "WARNING: $n register/latch pins with no clock (see check_timing_noclock.rpt)"
}

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
set pcie_cells [get_cells -hier -filter {REF_NAME =~ PCIE4*}]
foreach c $pcie_cells { puts "PCIE_LOC: $c -> [get_property LOC $c]" }
foreach c [get_cells -hier -filter {REF_NAME =~ GTYE4_CHANNEL*}] {
    puts "GT_LOC: [get_property LOC $c]"
}

set bit [glob -nocomplain $OutDir/proj/stage1.runs/impl_1/*.bit]
puts "BITSTREAM: $bit"
puts "BUILD_OK"
