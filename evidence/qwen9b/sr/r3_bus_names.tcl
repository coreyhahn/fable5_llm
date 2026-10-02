# r3_bus_names.tcl <dcp> <name_glob> — R3-10: READ-ONLY listing of the sequential cells whose NAME matches
# <name_glob> in a checkpoint (used on seq_0's OOC synth dcp to learn the synthesized names of the push-bus
# flops before fixing r3_push_probe.tcl's filters — "fix the name, never add a constraint").
open_checkpoint [lindex $argv 0]
set g [lindex $argv 1]
set c [get_cells -quiet -hierarchical -filter "IS_SEQUENTIAL && NAME =~ $g"]
puts "NM count=[llength $c] glob=$g"
foreach x [lsort -dictionary $c] { puts "NM $x REF=[get_property REF_NAME $x]" }
puts "NM_DONE"
