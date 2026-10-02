# ooc_dnpipe_attrib.tcl — G4b Step 1: ATTRIBUTE the DN_PIPE 0 -> 2 LUT move.
#
# The brief makes a LUT or URAM move a STOP condition, on the reasoning that
# it would mean "the pipelining was not built the way Track P built it".  The
# measured URAM move is zero; the measured LUT move is small but not zero, so
# it has to be attributed to a hierarchy cell by cell rather than waved past.
#
# This opens both post-synth checkpoints and prints, per primitive class, the
# count and the parent instances that hold them.  Run it and read the
# difference; the gate doc quotes the ATTRIB lines.
#
#   vivado -mode batch -nojournal -nolog -source ooc_dnpipe_attrib.tcl \
#          -tclargs <dcp-p0> <dcp-p2>

if {[llength $argv] < 2} { puts "FATAL: need <dcp-p0> <dcp-p2>"; exit 1 }
lassign $argv Dcp0 Dcp2

proc census {tag dcp} {
    open_checkpoint $dcp
    puts "ATTRIB ==== $tag  $dcp"
    foreach ref {LUT1 LUT2 LUT3 LUT4 LUT5 LUT6 CARRY8 FDRE FDSE
                 RAMS64E1 RAMD64E RAMD32 RAMS32 SRL16E
                 RAMB36E2 RAMB18E2 URAM288 DSP48E2 MUXF7 MUXF8 MUXF9} {
        set cs [get_cells -quiet -hier -filter "REF_NAME == $ref"]
        if {[llength $cs] == 0} continue
        puts "ATTRIB $tag $ref total [llength $cs]"
        # group by the parent instance, biggest first, top 6
        set seen [dict create]
        foreach c $cs { dict incr seen [regsub {/[^/]*$} $c ""] }
        set pairs {}
        foreach {k v} $seen { lappend pairs [list $k $v] }
        set pairs [lsort -integer -decreasing -index 1 $pairs]
        set i 0
        foreach p $pairs {
            puts "ATTRIB $tag   $ref [lindex $p 0] [lindex $p 1]"
            incr i; if {$i >= 6} break
        }
    }
    # the two cells the DN pipeline itself adds, named explicitly
    foreach pat {*g_dnpipeN* *g_grp* *sc_mem*} {
        foreach ref {FDRE SRL16E RAMS64E1 RAMB18E2 LUT6} {
            set n [llength [get_cells -quiet -hier \
                -filter "REF_NAME == $ref && NAME =~ $pat"]]
            if {$n > 0} { puts "ATTRIB $tag PAT $pat $ref $n" }
        }
    }
    close_design
}

census P0 $Dcp0
census P2 $Dcp2
puts "ATTRIB DONE"
