# sr1_help_probe.tcl <scratch_dir> — SR1: verify, from Vivado 2024.2's OWN help,
# the incremental-implementation command options and run properties that spec
# §4.3 named from memory (evidence/qwen9b/bm/BM1_T3_BUILD.md §12.4 (a)).
# Read-only with respect to the repo: the throwaway project goes to a fresh
# scratch dir OUTSIDE synth/ (created by the caller), never into any out dir.
set sd [lindex $argv 0]
foreach c {read_checkpoint place_design route_design phys_opt_design report_incremental_reuse} {
    puts "SRH ================ help $c"
    puts [help $c]
}
create_project -force srh_probe $sd/srh_probe -part xcvu9p-fsgd2104-2L-e
set r [get_runs impl_1]
puts "SRH ================ list_property impl_1 (INCREMENTAL / AUTO / DIRECTIVE / PHYS_OPT rows)"
foreach p [lsort [list_property $r]] {
    if {[regexp -nocase {INCREMENTAL|AUTO_INCR|DIRECTIVE|PHYS_OPT|PLACE_DESIGN\.ARGS|ROUTE_DESIGN\.ARGS} $p]} {
        puts [format "SRH_PROP %-60s = '%s'" $p [get_property $p $r]]
    }
}
puts "SRH ================ report_property impl_1 INCREMENTAL rows"
foreach p [lsort [list_property $r]] {
    if {[regexp -nocase {INCREMENTAL} $p]} { puts "SRH_PROPDOC $p : [report_property -all $r $p -return_string]" }
}
close_project
puts "SRH_DONE"
