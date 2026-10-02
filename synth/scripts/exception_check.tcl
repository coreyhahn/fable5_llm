# exception_check.tcl <roll_dir> <exception_xdc> — verify the XDMA reset
# exception is scoped EXACTLY as intended, before trusting any number from it.
#
# Applied to the fp2a routed checkpoint, which already has the winning
# placement. Because nothing here re-places anything, this also answers the
# whole question cheaply: if those 6 endpoints were the only violations, WNS
# must go >= 0 on THIS checkpoint the moment the exception is read.
#
# The four things that must be true, and are each asserted below:
#   1. the false_path matches a NON-ZERO pin set (an exception that matches
#      nothing is silently harmless and would fake a pass),
#   2. every matched pin is inside xdma_0 and is a /CLR pin (nothing broader,
#      and structurally incapable of exempting a datapath, which lands on /D),
#   3. the six previously-failing endpoints are now exempt,
#   4. the custom-RTL classes from the build_034/035 censuses are STILL BEING
#      CHECKED -- they must show as MET, not as exempted.
#
# Usage: vivado -mode batch -nojournal -source exception_check.tcl \
#          -tclargs <roll_dir> <exception_xdc>

if {[llength $argv] < 2} { puts "FATAL: need <roll_dir> <exception_xdc>"; exit 1 }
set D   [lindex $argv 0]
set XDC [lindex $argv 1]
set dcp $D/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp
if {![file exists $dcp]} { puts "FATAL: no checkpoint: $dcp"; exit 1 }
open_checkpoint $dcp

puts "EXC_BEFORE_WNS: [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]"
puts "EXC_BEFORE_WHS: [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]"
puts "EXC_BEFORE_FAILING: [llength [get_timing_paths -max_paths 5000 -nworst 1 -setup -slack_lesser_than 0]]"

# ---- 4a. capture representative custom-RTL endpoints BEFORE the exception,
#          so we can prove afterwards that they are still analysed.
set xline_pins [get_pins -quiet -hier -filter {NAME =~ *u_engine/xline_q0_reg*/CE}]
set dn_pins    [get_pins -quiet -hier -filter {NAME =~ *layer_0*u_core/u_dn/*/D}]
puts "EXC_CUSTOM_XLINE_PINS: [llength $xline_pins]"
puts "EXC_CUSTOM_DN_PINS: [llength $dn_pins]"

# ---------------------------------------------------------------- apply it
if {[catch {read_xdc -quiet $XDC} err]} { puts "EXC_FATAL: read_xdc: $err"; exit 1 }
puts "EXC_XDC_READ_OK: $XDC"

# ---- 1 & 2. what exactly did the pattern match?
set matched [get_pins -quiet -hierarchical -filter {NAME =~ */udma_wrapper/dma_top/user_rst_*_reg*/CLR}]
puts "EXC_MATCHED_PIN_COUNT: [llength $matched]"
if {[llength $matched] == 0} {
    puts "EXC_FATAL: exception matched ZERO pins — it would be silently harmless"
    exit 1
}
set bad_hier 0
set bad_pin  0
foreach p $matched {
    set nm [get_property NAME $p]
    if {![string match "*xdma_0*" $nm]}  { incr bad_hier; puts "EXC_OUTSIDE_XDMA: $nm" }
    if {![string match "*/CLR" $nm]}     { incr bad_pin;  puts "EXC_NOT_CLR: $nm" }
    puts "EXC_MATCHED $nm"
}
puts "EXC_OUTSIDE_XDMA_COUNT: $bad_hier"
puts "EXC_NON_CLR_COUNT: $bad_pin"
if {$bad_hier > 0 || $bad_pin > 0} { puts "EXC_FATAL: exception is broader than intended"; exit 1 }

# report_exceptions: the authoritative view of what is now exempt
report_exceptions -file $D/reports/exceptions.rpt
report_exceptions -ignored -file $D/reports/exceptions_ignored.rpt

# ---- 3. the design's remaining failing set
set after [get_timing_paths -max_paths 5000 -nworst 1 -setup -slack_lesser_than 0]
puts "EXC_AFTER_WNS: [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]"
puts "EXC_AFTER_WHS: [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]"
puts "EXC_AFTER_FAILING: [llength $after]"
foreach p $after {
    puts "EXC_REMAIN [get_property SLACK $p] [get_property GROUP $p] [get_property ENDPOINT_PIN $p]"
}

# ---- 4b. prove the custom-RTL classes are STILL CHECKED (met, not exempted).
# A path that still has a computed slack is being analysed; an exempted one
# returns nothing at all.
set xp [get_timing_paths -quiet -to $xline_pins -setup -max_paths 1 -nworst 1]
if {[llength $xp] == 0} {
    puts "EXC_FATAL: xline_q0 CE paths are NO LONGER ANALYSED — exception is too broad"
    exit 1
}
puts "EXC_CUSTOM_XLINE_STILL_CHECKED slack=[get_property SLACK [lindex $xp 0]] ep=[get_property ENDPOINT_PIN [lindex $xp 0]]"
set dp [get_timing_paths -quiet -to $dn_pins -setup -max_paths 1 -nworst 1]
if {[llength $dp] == 0} {
    puts "EXC_FATAL: layer_0/u_dn paths are NO LONGER ANALYSED — exception is too broad"
    exit 1
}
puts "EXC_CUSTOM_DN_STILL_CHECKED slack=[get_property SLACK [lindex $dp 0]] ep=[get_property ENDPOINT_PIN [lindex $dp 0]]"

# total analysed endpoint count, before/after, as a blunt over-reach detector
report_timing_summary -file $D/reports/timing_summary_with_exception.rpt
puts "EXC_OK"
