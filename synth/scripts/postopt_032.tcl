# Post-route phys_opt on the build_032 best roll (SSI_HighUtilSLRs, -0.091).
# Up to 3 passes; report setup+hold each pass; write bitstream if closed.
set d /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_032_rr_SSI_HighUtilSLRs
open_checkpoint $d/proj/stage1.runs/impl_1/bd_wrapper_routed.dcp

set wns -1
for {set i 1} {$i <= 3} {incr i} {
    phys_opt_design -directive AggressiveExplore
    set wns [get_property SLACK [lindex [get_timing_paths -max_paths 1 -nworst 1 -setup] 0]]
    set whs [get_property SLACK [lindex [get_timing_paths -max_paths 1 -nworst 1 -hold] 0]]
    puts "POSTOPT_PASS$i WNS=$wns WHS=$whs"
    if {$wns >= 0} { break }
}

file mkdir $d/postopt
report_timing_summary -file $d/postopt/timing_summary_postopt.rpt
if {$wns >= 0} {
    write_checkpoint -force $d/postopt/bd_wrapper_postopt.dcp
    write_bitstream  -force $d/postopt/bd_wrapper_postopt.bit
    puts "POSTOPT_BITSTREAM_OK"
}
puts "POSTOPT_DONE WNS=$wns"
