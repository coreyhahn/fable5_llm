# sr7f1_clock_guidance.tcl <physopt_dcp> <routed_dcp> — SR7 fix round 1, M-2.
# Which global clock nets carry Route 35-4475 ("incomplete placer guidance
# tree"), and what is their hold slack.  READ-ONLY on disk: open_checkpoint
# only, NO write_checkpoint / write_bitstream / report -file; everything is
# printed.  Run from the repo root (so .Xil lands there, gitignored), never
# from a signed-off out dir.
#  1. the post-place phys_opt checkpoint (the router's input) is opened and
#     route_design -verbose is run IN MEMORY on the global clock nets only
#     (-nets): the router's Phase 1 prints the 35-4475 net list in verbose
#     mode.  The routed result is discarded (nothing is written).
#  2. the signed-off ROUTED checkpoint is opened and, per clock whose net is
#     named, the worst hold path and its slack are printed.
if {[llength $argv] < 2} { puts "FATAL: need <physopt_dcp> <routed_dcp>"; exit 1 }
set PO [lindex $argv 0]; set RT [lindex $argv 1]
open_checkpoint $PO
set gnets [get_nets -hier -quiet -filter {TYPE == GLOBAL_CLOCK}]
puts "CG_GLOBAL_CLOCK_NETS: [llength $gnets]"
foreach n $gnets { puts "CG_GNET: $n  ROUTE_STATUS=[get_property ROUTE_STATUS $n]" }
if {[catch {route_design -nets $gnets -verbose} e]} { puts "CG_ROUTE_ERR: $e" }
close_design
open_checkpoint $RT
foreach c [get_clocks] {
    set p [get_timing_paths -hold -max_paths 1 -nworst 1 -quiet -to $c]
    if {[llength $p]} { puts [format "CG_HOLD clock=%s worst_hold=%s" $c [get_property SLACK $p]] }
}
puts "CG_DONE"
