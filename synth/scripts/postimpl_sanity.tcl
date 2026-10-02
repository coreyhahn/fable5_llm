# postimpl_sanity.tcl — the post-implementation sanity checks that
# synth/scripts/build.tcl runs on the opened impl_1 design, factored into two
# procs (Task R3-0 (ii), evidence/qwen9b/sr/R3_0_TOOLING.md) so they can
# also run READ-ONLY on a routed checkpoint that build.tcl never saw — a
# synth-only project implemented by synth/scripts/launch_incr.sh has no base
# roll, and neither synth/scripts/incr_impl.tcl nor
# synth/scripts/final_verify.tcl carries these checks (R3-10 step 4):
#     open_checkpoint <routed.dcp>
#     source -notrace synth/scripts/postimpl_sanity.tcl
#     postimpl_clock_gate <report_dir>
#     postimpl_loc_print
# build.tcl sources this file (-notrace) and calls the two procs at the two
# places the blocks stood, so its printed lines and their ORDER are the ones
# it printed before the factoring (existing log parsers match them): the
# proc bodies are the blocks verbatim, with $OutDir/reports -> $rptdir.
# Defines procs only; running nothing when sourced.

# Site 1 (after open_run impl_1, before the reports).
# Clock-sanity gate (added after the unconstrained-pcie_refclk incident):
# the XDMA axi_aclk domain (250 MHz / 4 ns) MUST exist as a timed clock,
# and unconstrained register pins must be enumerated for review.
# Writes <rptdir>/check_timing_noclock.rpt; exits Vivado 1 on no 4 ns clock.
proc postimpl_clock_gate {rptdir} {
    set clk4 [get_clocks -quiet -filter {PERIOD < 4.05 && PERIOD > 3.95}]
    if {[llength $clk4] == 0} {
        puts "FATAL: no 4ns (250MHz) clock found — XDMA clock tree unconstrained"
        exit 1
    }
    puts "CLOCK_GATE_OK: 250MHz clocks: $clk4"
    check_timing -override_defaults no_clock -file $rptdir/check_timing_noclock.rpt
    set fh [open $rptdir/check_timing_noclock.rpt r]
    set ct [read $fh]; close $fh
    if {[regexp {There are (\d+) register/latch pins with no clock} $ct -> n] && $n > 0} {
        puts "WARNING: $n register/latch pins with no clock (see check_timing_noclock.rpt)"
    }
}

# Site 2 (after the TIMING: headline).
# PCIe block + GT placement sanity (must be quad 226/227 per board wiring)
proc postimpl_loc_print {} {
    set pcie_cells [get_cells -hier -filter {REF_NAME =~ PCIE4*}]
    foreach c $pcie_cells { puts "PCIE_LOC: $c -> [get_property LOC $c]" }
    foreach c [get_cells -hier -filter {REF_NAME =~ GTYE4_CHANNEL*}] {
        puts "GT_LOC: [get_property LOC $c]"
    }
}
