# r3_postimpl_sanity_run.tcl <routed_dcp> <report_dir> — R3-10 step 4 (plan review I-7): runs the two
# procs of synth/scripts/postimpl_sanity.tcl (R3-0) READ-ONLY on a routed checkpoint, as that file's
# header prescribes (a synth-only project implemented by launch_incr.sh never ran build.tcl's checks).
# The checkpoint is opened, never saved; the no-clock report goes to <report_dir> (a scratch dir).
set dcp [lindex $argv 0]
set rd  [lindex $argv 1]
file mkdir $rd
open_checkpoint $dcp
puts "PS_CHECKPOINT: $dcp size=[file size $dcp] mtime=[clock format [file mtime $dcp] -format {%Y-%m-%dT%H:%M:%S}]"
source -notrace /home/cah/r2d2/code/fpga/fable5_llm/synth/scripts/postimpl_sanity.tcl
postimpl_clock_gate $rd
set fh [open $rd/check_timing_noclock.rpt r]; set ct [read $fh]; close $fh
foreach l [split $ct "\n"] { if {[regexp {register/latch pins with no clock|no_clock|There are} $l]} { puts "PS_NOCLOCK | $l" } }
postimpl_loc_print
puts "PS_DONE"
