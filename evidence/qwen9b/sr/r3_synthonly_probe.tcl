# r3_synthonly_probe.tcl <out_dir> [<version_hex8>] — Task R3-0 (ii): create a
# ONE-FLOP scratch project at <out_dir>/proj/stage1.xpr, the fake project the
# synth-only launch mode and the factored post-impl sanity block are tested
# on (evidence/qwen9b/sr/r3_tool_tdd.sh cases (c') and (d)).  NEVER a real
# design: one IBUFDS, one flop, one input, one output.
#
# Built to stand in for synth/scripts/create_project.tcl: same arguments
# (<out_dir> <version>; the version is only printed), same project name
# (stage1, which synth/scripts/build.tcl opens), same part, and the same
# CREATE_PROJECT_OK line synth/scripts/launch_build.sh greps for — so a
# SCRATCH copy of the launcher can run it end to end with the real Vivado.
#
# Constrained as the controller addendum asks, so check_timing reports only
# what the real design would: a 4.000 ns (250 MHz) clock (build.tcl's
# CLOCK_GATE_OK looks for a 3.95..4.05 ns clock) on a clock-capable
# differential pair, and both IO ports with input / output delays.  The pins
# and IOSTANDARDs are board pins from synth/constraints/BCU1525_DIMM0.xdc
# (the DIMM0 300 MHz refclk pair, the DIMM0 reset and PERST) purely so
# write_bitstream's IO DRCs pass; the bitstream is never programmed.
if {[llength $argv] < 1} { puts "FATAL: need <out_dir> \[<version_hex8>\]"; exit 1 }
set OutDir [file normalize [lindex $argv 0]]
set Ver [expr {[llength $argv] > 1 ? [lindex $argv 1] : "none"}]
if {[file exists $OutDir/proj]} { puts "FATAL: $OutDir/proj exists — never reused"; exit 1 }
file mkdir $OutDir/src

set fh [open $OutDir/src/r3_probe_top.v w]
puts $fh {// r3_probe_top — Task R3-0's one-flop scratch design (never programmed)
module r3_probe_top (
    input  wire clk_p,
    input  wire clk_n,
    input  wire d,
    output reg  q
);
    wire clk;
    IBUFDS u_ibuf (.I(clk_p), .IB(clk_n), .O(clk));
    always @(posedge clk) q <= d;
endmodule}
close $fh

set fh [open $OutDir/src/r3_probe.xdc w]
puts $fh {# r3_probe.xdc — Task R3-0's one-flop scratch design
set_property -dict {PACKAGE_PIN AY37 IOSTANDARD DIFF_SSTL12} [get_ports clk_p]
set_property -dict {PACKAGE_PIN AY38 IOSTANDARD DIFF_SSTL12} [get_ports clk_n]
set_property -dict {PACKAGE_PIN BD21 IOSTANDARD LVCMOS12} [get_ports d]
set_property -dict {PACKAGE_PIN AU31 IOSTANDARD LVCMOS12 DRIVE 8} [get_ports q]
create_clock -name probe_clk -period 4.000 [get_ports clk_p]
set_input_delay -clock probe_clk 0.500 [get_ports d]
set_output_delay -clock probe_clk 0.500 [get_ports q]}
close $fh

if {[catch {
    create_project stage1 $OutDir/proj -part xcvu9p-fsgd2104-2L-e
    add_files -norecurse $OutDir/src/r3_probe_top.v
    add_files -fileset constrs_1 -norecurse $OutDir/src/r3_probe.xdc
    set_property top r3_probe_top [current_fileset]
    update_compile_order -fileset sources_1
    close_project
} err]} {
    puts "FATAL: $err"; exit 1
}
puts "R3_PROBE: one-flop project at $OutDir/proj/stage1.xpr (version $Ver)"
puts "CREATE_PROJECT_OK"
