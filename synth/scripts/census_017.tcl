# Path census on build_017 routed checkpoint: dump all violated paths
# (startpoint, endpoint, slack, levels) for family histogramming.
set dcp /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_017/proj/stage1.runs/impl_1/bd_wrapper_routed.dcp
set out /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_017/census_paths.txt

open_checkpoint $dcp

set paths [get_timing_paths -max_paths 1000 -slack_lesser_than 0 -nworst 1]
set fh [open $out w]
foreach p $paths {
    set sp [get_property STARTPOINT_PIN $p]
    set ep [get_property ENDPOINT_PIN $p]
    set sl [get_property SLACK $p]
    set lv [get_property LOGIC_LEVELS $p]
    puts $fh "SLACK=$sl LV=$lv SP=$sp EP=$ep"
}
close $fh
puts "CENSUS_OK [llength $paths] paths"
