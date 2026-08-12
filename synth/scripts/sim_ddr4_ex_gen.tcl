# sim_ddr4_ex_gen.tcl — generate the DDR4 IP example design (with our custom
# Ballistix part) and run its xsim simulation: calibration + traffic test.
# This is the sim-before-hardware evidence for the DDR4 configuration.
# Usage: vivado -mode batch -source sim_ddr4_ex.tcl -tclargs <out_dir>

if {[llength $argv] < 1} { puts "FATAL: need <out_dir>"; exit 1 }
set OutDir [lindex $argv 0]

set ScriptDir [file dirname [file normalize [info script]]]
set RepoRoot  [file normalize "$ScriptDir/../.."]
set ConstrDir "$RepoRoot/synth/constraints"

proc must {script} {
    if {[catch {uplevel 1 $script} err]} { puts "FATAL: $err"; exit 1 }
}

set_param general.maxThreads 8

must {create_project ddr4_ex $OutDir/proj -part xcvu9p-fsgd2104-2L-e}
must {import_files -norecurse $ConstrDir/BLS4G4D240FSB.csv}
set csv_file [lindex [get_files */BLS4G4D240FSB.csv] 0]

must {create_ip -name ddr4 -vendor xilinx.com -library ip -version 2.2 -module_name ddr4_ex0}
must {set_property -dict [list \
    CONFIG.C0.DDR4_TimePeriod {833} \
    CONFIG.C0.DDR4_InputClockPeriod {3332} \
    CONFIG.C0.DDR4_CLKOUT0_DIVIDE {5} \
    CONFIG.C0.DDR4_CustomParts $csv_file \
    CONFIG.C0.DDR4_isCustom {true} \
    CONFIG.C0.DDR4_MemoryType {UDIMMs} \
    CONFIG.C0.DDR4_MemoryPart {BLS4G4D240FSB-2400} \
    CONFIG.C0.DDR4_DataWidth {64} \
    CONFIG.C0.DDR4_AxiSelection {true} \
] [get_ips ddr4_ex0]}

must {generate_target all [get_ips ddr4_ex0]}
must {open_example_project -force -dir $OutDir/ex [get_ips ddr4_ex0]}
puts "GEN_DDR4_EX_DONE"
