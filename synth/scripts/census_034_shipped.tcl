# census_034_shipped.tcl — per-ENDPOINT census of every failing setup path on
# the SHIPPED roll, to settle the "100% custom RTL" attribution with evidence
# rather than inference from the 2-block summary report.
set D /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_034_po2_AltSpreadLogic_high
open_checkpoint $D/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp
file mkdir $D/reports

set paths [get_timing_paths -max_paths 2000 -nworst 1 -setup -slack_lesser_than 0]
puts "SHIPPED_CENSUS_COUNT: [llength $paths]"
puts "SHIPPED_CENSUS_BEGIN"
foreach p $paths {
    set ep  [get_property ENDPOINT_PIN $p]
    set sp  [get_property STARTPOINT_PIN $p]
    puts [format "EP %7s %-22s lvl=%-3s %s <- %s" \
        [get_property SLACK $p] [get_property GROUP $p] \
        [get_property LOGIC_LEVELS $p] $ep $sp]
}
puts "SHIPPED_CENSUS_END"

# owner tally: which module hierarchy owns each failing endpoint
puts "OWNER_TALLY_BEGIN"
foreach p $paths {
    set ep [get_property ENDPOINT_PIN $p]
    # bd_i/<top-level cell>/... -> take the first two hierarchy levels
    puts "OWNER [join [lrange [split $ep /] 0 2] /]"
}
puts "OWNER_TALLY_END"

# route-vs-logic delay split on the two worst paths
foreach p [lrange $paths 0 1] {
    # NB DATAPATH_DELAY is the TOTAL datapath delay (logic + route), not route
    # alone; route = datapath - logic. Labelled accordingly.
    set dp [get_property DATAPATH_DELAY $p]
    set lg [get_property DATAPATH_LOGIC_DELAY $p]
    puts [format "SPLIT slack=%s logic=%s route=%.3f datapath_total=%s ep=%s" \
        [get_property SLACK $p] $lg [expr {$dp - $lg}] $dp [get_property ENDPOINT_PIN $p]]
}
puts "SHIPPED_CENSUS_OK"
