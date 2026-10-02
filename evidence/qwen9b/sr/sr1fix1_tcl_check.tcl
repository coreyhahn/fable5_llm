# sr1fix1_tcl_check.tcl — NO-LAUNCH check of synth/scripts/incr_impl.tcl (SR1 fix 1).
# Run with plain tclsh (no Vivado process at all):
#   tclsh evidence/qwen9b/sr/sr1fix1_tcl_check.tcl
# 1. the whole file is a complete Tcl script (info complete);
# 2. sourcing it with ::INCR_IMPL_PROCS_ONLY set defines sr_effective_directives
#    and executes NOTHING else (no open_project / launch_runs — those are Vivado
#    commands that do not exist in tclsh, so reaching them would error);
# 3. the proc, on two EXISTING run logs read-only, returns the expected values:
#    GREEN: build_043_incr_probe (incremental TimingClosure) and
#    CONTROL: build_042_bm1_ckr2b_ExtraNetDelay_low (ordinary full recipe).
set R /home/cah/r2d2/code/fpga/fable5_llm
set f $R/synth/scripts/incr_impl.tcl
set fh [open $f r]; set src [read $fh]; close $fh
puts "CHK_INFO_COMPLETE: [info complete $src]"
if {![info complete $src]} { puts "CHK_FAIL: incomplete script"; exit 1 }
set ::INCR_IMPL_PROCS_ONLY 1
set ::argv {}
source $f
puts "CHK_SOURCED_OK: proc defined = [llength [info procs sr_effective_directives]]"
puts "CHK_VIVADO_CMDS_PRESENT: [llength [info commands launch_runs]] (0 = plain tclsh, nothing can launch)"
set cases [list \
  $R/synth/out_build_043_incr_probe/proj/stage1.runs/impl_1/runme.log \
  "place=Explore phys_opt_post_place=UNNAMED(12-9151_override_of_AggressiveExplore) route=Explore phys_opt_post_route=AggressiveExplore incr_override=yes" \
  $R/synth/out_build_042_bm1_ckr2b_ExtraNetDelay_low/proj/stage1.runs/impl_1/runme.log \
  "place=ExtraNetDelay_low phys_opt_post_place=AggressiveExplore route=Default phys_opt_post_route=AggressiveExplore incr_override=no" \
  /nonexistent/runme.log "UNKNOWN(no runme.log: /nonexistent/runme.log)"]
set bad 0
foreach {log exp} $cases {
    set got [sr_effective_directives $log]
    set ok [expr {$got eq $exp}]
    if {!$ok} { incr bad }
    puts "CHK_CASE [expr {$ok ? "OK  " : "FAIL"}] $log"
    puts "CHK_GOT      $got"
    if {!$ok} { puts "CHK_EXPECTED $exp" }
}
if {$bad} { puts "CHK_FAIL: $bad case(s)"; exit 1 }
puts "CHK_OK"
