# Read-only placement dump for build_046_r3_incr. No writes to the design.
set out [pwd]
set dcp /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_046_r3_incr/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp
set t0 [clock seconds]
open_checkpoint $dcp
puts "TIMING open_checkpoint [expr {[clock seconds]-$t0}] s"
set fh [open $out/meta.tsv w]
puts $fh "PART\t[get_property PART [current_design]]"
puts $fh "DCP\t$dcp"
close $fh

# ---- cells
set t1 [clock seconds]
set all [get_cells -hier -filter {IS_PRIMITIVE}]
puts "INFO all primitive cells: [llength $all]"
set cells [filter $all {LOC != ""}]
puts "INFO placed leaf cells: [llength $cells]"
set fh [open $out/noloc_cells.tsv w]
foreach c [filter $all {LOC == ""}] r [get_property REF_NAME [filter $all {LOC == ""}]] { puts $fh "$c\t$r" }
close $fh
set names [get_property NAME $cells]
set refs  [get_property REF_NAME $cells]
set locs  [get_property LOC $cells]
set fh [open $out/cells.tsv w]
fconfigure $fh -buffering full -buffersize 1048576
foreach n $names r $refs l $locs { puts $fh "$n\t$r\t$l" }
close $fh
puts "TIMING cells [expr {[clock seconds]-$t1}] s"

# ---- sites
set t1 [clock seconds]
set sites [get_sites]
puts "INFO total sites: [llength $sites]"
puts "INFO site props: [list_property [lindex $sites 0]]"
set sn [get_property NAME $sites]
set st [get_property SITE_TYPE $sites]
set rx [get_property RPM_X $sites]
set ry [get_property RPM_Y $sites]
if {[catch {set cr [get_property CLOCK_REGION $sites]} err]} { puts "WARN CLOCK_REGION: $err"; set cr {} }
if {[llength $cr] != [llength $sn]} { puts "WARN CLOCK_REGION list length [llength $cr] != [llength $sn]; omitting"; set cr [lrepeat [llength $sn] {}] }
set fh [open $out/sites.tsv w]
fconfigure $fh -buffering full -buffersize 1048576
foreach a $sn b $st c $rx d $ry e $cr { puts $fh "$a\t$b\t$c\t$d\t$e" }
close $fh
puts "TIMING sites [expr {[clock seconds]-$t1}] s"

# ---- SLR membership
set t1 [clock seconds]
set fh [open $out/slr.tsv w]
fconfigure $fh -buffering full -buffersize 1048576
foreach s [get_slrs] {
  set ss {}
  if {[catch {set ss [get_sites -of_objects $s]} err]} {
    puts "WARN get_sites -of SLR $s failed: $err; using clock regions"
    set ss [get_sites -of_objects [get_clock_regions -of_objects $s]]
    puts "METHOD $s clock_regions"
  } else { puts "METHOD $s get_sites_of_slr" }
  puts "INFO $s sites [llength $ss] clock_regions [get_clock_regions -of_objects $s]"
  foreach x $ss { puts $fh "$x\t$s" }
}
close $fh
puts "TIMING slr [expr {[clock seconds]-$t1}] s"
puts "TIMING total [expr {[clock seconds]-$t0}] s"
close_design
puts "DUMP_DONE"
