# g5b_t14a_smem_cascade.tcl — Task 14-A's second READ-ONLY probe: how much of
# the failing set is the scratchpad's BRAM CASCADE, and how deep is it.
#
# g5b_t14a_cone_census.tcl classified the failing paths by ENDPOINT and found
# four cones with 2.5-2.8 ns of LOGIC.  Reading their cell expansions showed
# all four have the same STARTPOINT class and the same first eight levels:
# `smem_?_reg_bram_N/CLKBWRCLK` and then seven RAMB36E2 hops on
# CASDOUT?->CASDIN?.  This instrument answers the two questions that decides
# the fix, over the WHOLE failing set rather than the worst fifty:
#
#   1. how many failing setup endpoints are LAUNCHED by a scratchpad BRAM,
#      and what their slack / logic / route distribution is;
#   2. what the cascade actually is on the netlist — the CASCADE_ORDER_A/B
#      property of every smem BRAM cell, tallied, which is the measurement
#      that says a CASCADE_HEIGHT cap has something to cap.
#
# READ-ONLY: open_checkpoint + get_*/report_* only.  Writes nothing but the
# report the caller names under evidence/.
#
#   vivado -mode batch -nojournal -source g5b_t14a_smem_cascade.tcl \
#          -tclargs <routed.dcp> <out_prefix>

if {[llength $argv] < 2} { puts "FATAL: need <dcp> <out_prefix>"; exit 1 }
set DCP [lindex $argv 0]
set PRE [lindex $argv 1]
if {![file exists $DCP]} { puts "FATAL: no such checkpoint: $DCP"; exit 1 }
set_param general.maxThreads 8
puts "SMC_DCP: $DCP"
puts "SMC_DCP_MTIME: [clock format [file mtime $DCP] -format {%Y-%m-%d %H:%M:%S}]"
open_checkpoint $DCP

set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
puts "SMC_WNS: $wns"

# ---- (1) the failing set, bucketed by STARTPOINT class -------------------
set allp [get_timing_paths -quiet -max_paths 6000 -nworst 1 -setup -slack_lesser_than 0]
puts "SMC_FAILING_SAMPLE: [llength $allp]"
set n_smem 0
set n_other 0
set smem_worst 99
set smem_best -99
set smem_logic_min 99
set smem_logic_max -99
puts "SMC_SMEM_PATHS_BEGIN"
foreach p $allp {
    set sp [get_property STARTPOINT_PIN $p]
    if {[string match "*smem_?_reg_bram_*" $sp]} {
        incr n_smem
        set s  [get_property SLACK $p]
        set dl [get_property DATAPATH_DELAY $p]
        set lg [get_property DATAPATH_LOGIC_DELAY $p]
        if {$s < $smem_worst} { set smem_worst $s }
        if {$s > $smem_best}  { set smem_best  $s }
        if {$lg < $smem_logic_min} { set smem_logic_min $lg }
        if {$lg > $smem_logic_max} { set smem_logic_max $lg }
        puts [format "SMC_P %8s lvl=%-3s dp=%-7s logic=%-7s route=%-7s | %s <- %s" \
            $s [get_property LOGIC_LEVELS $p] $dl $lg \
            [get_property DATAPATH_NET_DELAY $p] \
            [get_property ENDPOINT_PIN $p] $sp]
    } else {
        incr n_other
    }
}
puts "SMC_SMEM_PATHS_END"
puts "SMC_TALLY: smem_launched=$n_smem other=$n_other of [llength $allp]"
puts "SMC_SMEM_SLACK_RANGE: worst=$smem_worst best=$smem_best"
puts "SMC_SMEM_LOGIC_RANGE: min=$smem_logic_min max=$smem_logic_max"

# ---- (2) the cascade, from the netlist ----------------------------------
foreach arr {smem_a smem_b} {
    set cells [get_cells -quiet -hier -filter "NAME =~ *${arr}_reg_bram_* && PRIMITIVE_TYPE =~ BLOCKRAM.*.*"]
    if {[llength $cells] == 0} {
        set cells [get_cells -quiet -hier -filter "NAME =~ *${arr}_reg_bram_*"]
    }
    array unset oa; array set oa {}
    array unset ob; array set ob {}
    foreach c $cells {
        set a [get_property -quiet CASCADE_ORDER_A $c]
        set b [get_property -quiet CASCADE_ORDER_B $c]
        if {$a eq ""} { set a "(none)" }
        if {$b eq ""} { set b "(none)" }
        if {[info exists oa($a)]} { incr oa($a) } else { set oa($a) 1 }
        if {[info exists ob($b)]} { incr ob($b) } else { set ob($b) 1 }
    }
    puts "SMC_ARRAY $arr cells=[llength $cells]"
    foreach k [lsort [array names oa]] { puts "SMC_CASCADE_A $arr $k = $oa($k)" }
    foreach k [lsort [array names ob]] { puts "SMC_CASCADE_B $arr $k = $ob($k)" }
    # the RAM depth each tile presents, which is what sets the tile count
    set d0 [lindex $cells 0]
    if {$d0 ne ""} {
        puts "SMC_TILE0 $arr [get_property REF_NAME $d0] READ_WIDTH_B=[get_property -quiet READ_WIDTH_B $d0] DOB_REG=[get_property -quiet DOB_REG $d0] RAM_MODE=[get_property -quiet RAM_MODE $d0]"
    }
}

# ---- (3) the four named cones, worst path each, with the full expansion --
set CONES {
    dn_vdata   {*u_core/dn_vdata_reg*/D}
    at_qdata   {*u_core/at_qdata_reg*/D}
    axil_rdata {*u_core/s_axil_rdata_reg*/D}
}
foreach {nm pat} $CONES {
    set pins [get_pins -quiet -hier -filter "NAME =~ $pat"]
    set ps [get_timing_paths -quiet -to $pins -max_paths 10 -nworst 1 -setup -sort_by slack]
    puts "SMC_CONE $nm pins=[llength $pins] paths=[llength $ps]"
    foreach p $ps {
        puts [format "SMC_CONE_P %-10s %8s lvl=%-3s dp=%-7s logic=%-7s route=%-7s | %s" \
            $nm [get_property SLACK $p] [get_property LOGIC_LEVELS $p] \
            [get_property DATAPATH_DELAY $p] [get_property DATAPATH_LOGIC_DELAY $p] \
            [get_property DATAPATH_NET_DELAY $p] [get_property ENDPOINT_PIN $p]]
    }
}
puts "SMC_DONE"
