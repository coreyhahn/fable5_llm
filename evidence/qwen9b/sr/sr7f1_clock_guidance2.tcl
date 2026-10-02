# sr7f1_clock_guidance2.tcl <physopt_dcp> — SR7 fix round 1, M-2, second try.
# n755 showed `route_design -nets` is refused on this checkpoint ("not
# supported in incremental flow"), so this opens the post-place phys_opt
# checkpoint (the router's input) and runs a FULL `route_design -verbose` IN
# MEMORY: Phase 1 (Build RT Design) prints Route 35-4475 and, in verbose
# mode, the nets it names.  READ-ONLY on disk: nothing is written (no
# write_checkpoint / report -file); the caller bounds the run with `timeout`
# and it is killed once Phase 2 starts, the routed result discarded.
# First it prints the TOP-LEVEL global clock nets (-top_net_of_hierarchical
# _group) with their ROUTE_STATUS in this checkpoint.  Run from the repo root.
if {[llength $argv] < 1} { puts "FATAL: need <physopt_dcp>"; exit 1 }
open_checkpoint [lindex $argv 0]
set g [get_nets -hier -quiet -top_net_of_hierarchical_group -filter {TYPE == GLOBAL_CLOCK}]
puts "CG2_TOP_GLOBAL_CLOCK_NETS: [llength $g]"
foreach n $g { puts "CG2_GNET: $n ROUTE_STATUS=[get_property ROUTE_STATUS $n]" }
route_design -verbose
puts "CG2_DONE"
