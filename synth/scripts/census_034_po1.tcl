# census_034_po1.tcl — census the Explore roll, then post-route phys_opt.
set RR   /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_034_rr_Explore
set OUT  /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_034_po1
file mkdir $OUT/reports

open_checkpoint $RR/proj/stage1.runs/impl_1/bd_wrapper_routed.dcp

set wns0 [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set whs0 [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
puts "PO1_BEFORE: WNS=$wns0 WHS=$whs0"

report_timing_summary -file $OUT/reports/timing_before.rpt
# census: top 25 setup paths, who owns them
puts "PO1_CENSUS_BEGIN"
set i 0
foreach p [get_timing_paths -max_paths 25 -nworst 1 -setup -sort_by slack] {
    incr i
    set slk [get_property SLACK $p]
    set ep  [get_property ENDPOINT_PIN $p]
    set sp  [get_property STARTPOINT_PIN $p]
    set grp [get_property GROUP $p]
    set lvl [get_property LOGIC_LEVELS $p]
    puts [format "PO1_PATH %2d slack=%7s grp=%-24s lvl=%2s" $i $slk $grp $lvl]
    puts "    SP: $sp"
    puts "    EP: $ep"
}
puts "PO1_CENSUS_END"
