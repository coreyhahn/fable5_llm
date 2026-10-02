# g5c_scratch_cascade.tcl — the CASCADE_ORDER_B tally over EVERY scratchpad
# BRAM, using ooc_9b.tcl's own scratch selector (synth/scripts/ooc_9b.tcl:237)
# rather than g5b_t14a_smem_cascade.tcl's `*smem_?_reg_bram_*`, which matches
# only the cells Vivado happens to name that way.  Read-only.
#   vivado -mode batch -source <this> -tclargs <post_synth.dcp> <label>
set DCP [lindex $argv 0]
set LBL [lindex $argv 1]
open_checkpoint $DCP
puts "G5C_LABEL: $LBL"
puts "G5C_DCP: $DCP"
foreach arr {smem_a smem_b} {
    set cells [get_cells -quiet -hier -filter "REF_NAME =~ RAMB36* && NAME =~ *${arr}*"]
    array unset ob; array set ob {}
    foreach c $cells {
        set b [get_property -quiet CASCADE_ORDER_B $c]
        if {$b eq ""} { set b "(none)" }
        if {[info exists ob($b)]} { incr ob($b) } else { set ob($b) 1 }
    }
    puts "G5C_ARRAY $LBL $arr cells=[llength $cells]"
    foreach k [lsort [array names ob]] { puts "G5C_CASCADE_B $LBL $arr $k = $ob($k)" }
    set d0 [lindex $cells 0]
    if {$d0 ne ""} {
        puts "G5C_TILE0 $LBL $arr [get_property NAME $d0] READ_WIDTH_B=[get_property -quiet READ_WIDTH_B $d0] DOB_REG=[get_property -quiet DOB_REG $d0]"
    }
}
puts "G5C_CASCADE_DONE"
