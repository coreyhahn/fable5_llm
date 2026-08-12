# sim_ddr4_ex_run.tcl — open the generated DDR4 example project and run xsim.
# Usage: vivado -mode batch -source sim_ddr4_ex_run.tcl -tclargs <out_dir>
if {[llength $argv] < 1} { puts "FATAL: need <out_dir>"; exit 1 }
set OutDir [lindex $argv 0]
proc must {script} {
    if {[catch {uplevel 1 $script} err]} { puts "FATAL: $err"; exit 1 }
}
set_param general.maxThreads 8
must {open_project $OutDir/ex/ddr4_ex0_ex/ddr4_ex0_ex.xpr}
puts "EXAMPLE_PROJECT: [current_project]"
must {set_property top sim_tb_top [get_filesets sim_1]}
must {set_property top_lib xil_defaultlib [get_filesets sim_1]}
must {set_property -name {xsim.simulate.runtime} -value {-all} -objects [get_filesets sim_1]}
must {launch_simulation}
puts "SIM_DDR4_EX_DONE"
