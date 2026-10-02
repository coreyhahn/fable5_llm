# g5d_owner_probe.tcl <routed.dcp> <out_prefix> — READ-ONLY.  What would it
# take to close the residual owner Task 14-B is left with?
#
# WHY.  Task 14-A's design note section 7.2 named four route-dominated aclk
# families as "the scope of round two".  Two of them (the sequencer's next-PC
# enable and the state DMA's LUTRAM write cone) are CLOSED on 14-B's best roll
# (+0.278 and +0.143), so that list is stale, and an escalation that repeats it
# would be sending the next round after paths that already meet.  The owner
# that is left is a different shape: `ATTN_DSP`, the compute READ out of a KV
# cache slot into an attention multiplier — TWO logic levels carrying 1.700 ns
# of CELL delay, where the levels are the URAM288 and the DSP48E2 themselves.
#
# The only lever on a two-level cell-delay path is a REGISTER, and on this
# path there are two places a register can go that cost no RTL restructuring:
# the URAM's own output register and the DSP's own input register.  Whether
# either is already in use is a NETLIST property, not something to be reasoned
# about, so this instrument reads it:
#
#   1. the URAM288 cells of each cache slot family (DN / KV / CV): their
#      OREG_* / *_REG properties and the tally of each setting;
#   2. the DSP48E2 cells the failing attention and DN paths end in: AREG /
#      BREG / CREG / MREG / PREG / ADREG, tallied;
#   3. the worst path per family with its logic/route split, so the "what
#      would a stage buy" arithmetic in the gate doc has a measured base.
#
# It changes nothing and writes only the report the caller names.
#
#   vivado -mode batch -nojournal -source g5d_owner_probe.tcl \
#          -tclargs <routed.dcp> <out_prefix>

if {[llength $argv] < 2} { puts "OWP_FATAL: need <dcp> <out_prefix>"; exit 1 }
set DCP [lindex $argv 0]
set PRE [lindex $argv 1]
if {![file exists $DCP]} { puts "OWP_FATAL: no such checkpoint: $DCP"; exit 1 }
set_param general.maxThreads 8
puts "OWP_DCP: $DCP"
puts "OWP_DCP_MTIME: [clock format [file mtime $DCP] -format {%Y-%m-%d %H:%M:%S}]"
open_checkpoint $DCP
puts "OWP_WNS: [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]"

proc tally {cells props label} {
    foreach p $props {
        array unset t; array set t {}
        foreach c $cells {
            set v [get_property -quiet $p $c]
            if {$v eq ""} { set v "(unset)" }
            if {[info exists t($v)]} { incr t($v) } else { set t($v) 1 }
        }
        set out {}
        foreach k [lsort [array names t]] { lappend out "$k=$t($k)" }
        puts "OWP_PROP $label $p [join $out { }]"
    }
}

# ---- 1. the cache URAMs
puts "OWP_URAM_BEGIN"
foreach {nm pat} {DN *g_dnslot*  KV *g_kvslot*  CV *g_cvslot*} {
    set cells [get_cells -quiet -hier -filter "REF_NAME =~ URAM288* && NAME =~ $pat"]
    puts "OWP_URAM $nm cells=[llength $cells]"
    if {[llength $cells] == 0} { continue }
    tally $cells {OREG_A OREG_B OREG_ECC_A OREG_ECC_B REG_CAS_A REG_CAS_B \
                  AUTO_SLEEP_LATENCY CASCADE_ORDER_A CASCADE_ORDER_B} "URAM_$nm"
}
puts "OWP_URAM_END"

# ---- 2. the compute DSPs
puts "OWP_DSP_BEGIN"
foreach {nm pat} {ATTN *u_attn*  DN *u_dn*} {
    set cells [get_cells -quiet -hier -filter "REF_NAME =~ DSP48E2* && NAME =~ $pat"]
    puts "OWP_DSP $nm cells=[llength $cells]"
    if {[llength $cells] == 0} { continue }
    tally $cells {AREG BREG CREG DREG MREG PREG ADREG INMODEREG OPMODEREG \
                  ALUMODEREG CARRYINREG CARRYINSELREG} "DSP_$nm"
}
puts "OWP_DSP_END"

# ---- 3. the worst path per residual family, with the split
puts "OWP_PATHS_BEGIN"
foreach {nm pat} {ATTN_DSP *u_attn/*  DN_LANE *u_dn/*  KV_SLOT *g_kvslot*  DN_SLOT *g_dnslot*} {
    set dst [get_cells -quiet -hier -filter "NAME =~ $pat"]
    if {[llength $dst] == 0} { puts "OWP_PATH $nm NO_CELLS"; continue }
    set p [lindex [get_timing_paths -quiet -to $dst -max_paths 1 -nworst 1 -setup] 0]
    if {$p eq ""} { puts "OWP_PATH $nm NO_PATH"; continue }
    set dp [get_property DATAPATH_DELAY $p]
    set lg [get_property DATAPATH_LOGIC_DELAY $p]
    puts [format "OWP_PATH %-9s slack=%-8s lvl=%-3s datapath=%-7s logic=%-7s route=%-7s logic%%=%.1f" \
        $nm [get_property SLACK $p] [get_property LOGIC_LEVELS $p] $dp $lg \
        [get_property DATAPATH_NET_DELAY $p] [expr {$dp > 0 ? 100.0*$lg/$dp : 0}]]
    puts "OWP_PATH_ENDS $nm [get_property STARTPOINT_PIN $p] -> [get_property ENDPOINT_PIN $p]"
    report_timing -of_objects $p -path_type full -input_pins -file ${PRE}_${nm}.rpt
    puts "OWP_PATH_RPT $nm ${PRE}_${nm}.rpt"
}
puts "OWP_PATHS_END"
puts "OWP_DONE"
