# po_reports.tcl — regenerate reports for the CHOSEN roll from its exact
# final post-route-phys_opt checkpoint (the raced synth/reports/ were another roll's).
set D /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_034_po2_AltSpreadLogic_high
open_checkpoint $D/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp
file mkdir $D/reports
set w [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set h [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
puts "CHOSEN_ROLL_VERIFY: WNS=$w WHS=$h"
report_timing_summary -file $D/reports/timing_summary.rpt
report_utilization    -file $D/reports/utilization.rpt
report_utilization -hierarchical -file $D/reports/utilization_hier.rpt
puts "REPORTS_OK"
