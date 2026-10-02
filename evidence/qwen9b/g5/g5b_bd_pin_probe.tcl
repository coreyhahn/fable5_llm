# g5b_bd_pin_probe.tcl — WHICH of the BD clock/interface properties on a
# `-type module` reference cell can actually be WRITTEN?
#
# WHY THIS EXISTS.  build_036 died on
#   ERROR: [BD 41-237] FREQ_HZ does not match between /axi_smc/S02_AXI
#   (250000000) and /layer_0/m_axis(100000000)
# because rtl/layer_chan_ipi.v:9 declares `ASSOCIATED_BUSIF s_axil:s_axib` and
# S2 never added the m_axis master to it.  Two BD-level repairs were tried and
# each cost a 7-10 minute create_project cycle to disprove:
#   build_037 — set ASSOCIATED_BUSIF, then read FREQ_HZ: still 100 MHz.
#   build_038 — set ASSOCIATED_BUSIF, then read IT BACK: still `s_axil:s_axib`,
#               i.e. the set_property did not take at all.
# Guessing a third time is not a method.  This probe builds the SMALLEST design
# that can answer the question — one module-reference cell, no XDMA, no MIGs,
# no SmartConnect — and reports, for each property, what it was, whether the
# write raised an error, what it is afterwards, and `report_property`'s own
# read/write flags.  Minutes, not tens of minutes, and the answer is a fact
# rather than an inference.
#
#   vivado -mode batch -nojournal -source g5b_bd_pin_probe.tcl -tclargs <out_dir>

if {[llength $argv] < 1} { puts "FATAL: need <out_dir>"; exit 1 }
set OutDir [lindex $argv 0]
set ScriptDir [file dirname [file normalize [info script]]]
set RepoRoot  [file normalize "$ScriptDir/../../.."]
set RtlDir    "$RepoRoot/rtl"

create_project probe $OutDir/proj -part xcvu9p-fsgd2104-2L-e
foreach x {fx_pkg.sv fx_rsqrt.sv fx_recip.sv fx_silu.sv vecnorm_unit.sv \
           rope_unit.sv conv4_silu.sv dn_step.sv attn_core.sv gate_unit.sv \
           vec_alu.sv state_dma.sv layer_chan.sv} {
    add_files -norecurse $RtlDir/$x
}
add_files -norecurse $RtlDir/layer_chan_ipi.v
set_property XPM_LIBRARIES {XPM_CDC XPM_FIFO XPM_MEMORY} [current_project]
create_bd_design "bd"
create_bd_cell -type module -reference layer_chan_ipi layer_0
puts "PROBE_CELL_OK"

proc show {what obj prop} {
    puts "PROBE_${what}_BEFORE: '[get_property $prop $obj]'"
}
proc try_set {what obj prop val} {
    if {[catch {set_property $prop $val $obj} e]} {
        puts "PROBE_${what}_SET_ERR: $e"
    } else {
        puts "PROBE_${what}_SET_ERR: (none)"
    }
    puts "PROBE_${what}_AFTER: '[get_property $prop $obj]'"
}

set aclk  [get_bd_pins layer_0/aclk]
set maxis [get_bd_intf_pins layer_0/m_axis]
set saxil [get_bd_intf_pins layer_0/s_axil]

show    ABIF    $aclk  CONFIG.ASSOCIATED_BUSIF
try_set ABIF    $aclk  CONFIG.ASSOCIATED_BUSIF {s_axil:s_axib:m_axis}
show    FREQ    $maxis CONFIG.FREQ_HZ
try_set FREQ    $maxis CONFIG.FREQ_HZ 250000000
show    CLKDOM  $maxis CONFIG.CLK_DOMAIN
puts "PROBE_CLKDOM_SAXIL: '[get_property CONFIG.CLK_DOMAIN $saxil]'"
try_set CLKDOM  $maxis CONFIG.CLK_DOMAIN probe_clk_domain

puts "PROBE_REPORT_ACLK_BEGIN"
report_property -all $aclk
puts "PROBE_REPORT_ACLK_END"
puts "PROBE_REPORT_MAXIS_BEGIN"
report_property -all $maxis
puts "PROBE_REPORT_MAXIS_END"
puts "PROBE_OK"
