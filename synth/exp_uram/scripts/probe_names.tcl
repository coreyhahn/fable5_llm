# probe_names.tcl — one-off: what do the DN pipeline group cells actually look
# like in the synthesized netlist?  Input to G5a's pblock patterns.
open_checkpoint [lindex $argv 0]
foreach pat {*rq_p* *rq_p_reg* *g_grp?0?.rq* *dn_rdq_gq* *g_grp?0?.w_p_reg* *g_grp?0?.wd_p_reg?1?*
             *g_grp?0?.ra_p_reg?1?* *g_grp?0?.wa_p_reg?1?* *g_grp?0?.bs_p_reg?1?*} {
    set l [get_cells -quiet -hier -filter "NAME =~ $pat"]
    puts "PRB {$pat} -> [llength $l]"
    foreach c [lrange $l 0 2] { puts "   e.g. [get_property NAME $c] ([get_property REF_NAME $c])" }
}
# every distinct *_reg base name directly under a g_grp scope
array set base {}
foreach c [get_cells -quiet -hier -filter {NAME =~ *g_grp?0?.*}] {
    set n [get_property NAME $c]
    if {[regexp {g_grp\[0\]\.([^./\[]+)} $n -> b]} {
        if {[info exists base($b)]} { incr base($b) } else { set base($b) 1 }
    }
}
foreach b [lsort [array names base]] { puts "PRB_BASE $b $base($b)" }
puts "PRB_DONE"
