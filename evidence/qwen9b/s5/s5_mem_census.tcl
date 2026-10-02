# s5_mem_census.tcl — S5 Step 1: NAME every memory primitive in the post-synth
# netlist, so "URAM 174 not 182" and "block RAM 132 tiles not ~90" are answered
# with WHICH memory went where, not with a total.
#
#   vivado -mode batch -nojournal -source s5_mem_census.tcl -tclargs <out_dir>
#
# Reads <out_dir>/post_synth.dcp.  Markers are MEM_-prefixed.
if {[llength $argv] < 1} { puts "FATAL: need <out_dir>"; exit 1 }
set OutDir [lindex $argv 0]
set Dcp    $OutDir/post_synth.dcp
if {![file exists $Dcp]} { puts "FATAL: no $Dcp"; exit 1 }
set_param general.maxThreads 4
open_checkpoint $Dcp
puts "MEM_DCP: $Dcp"
puts "MEM_TOP: [get_property TOP [current_design]]"

proc n {filt} { return [llength [get_cells -quiet -hier -filter $filt]] }

# ---- the totals, restated off this checkpoint -------------------------------
puts "MEM_TOTAL URAM288=[n {REF_NAME =~ URAM288*}] RAMB36=[n {REF_NAME =~ RAMB36*}] RAMB18=[n {REF_NAME =~ RAMB18*}] DSP48E2=[n {REF_NAME =~ DSP48E2*}]"

# ---- every named memory in the design, by the RTL declaration it came from --
# The pattern list is MAINTAINED HERE and is checked for completeness at the
# end: the per-pattern counts must sum to the totals above, or a memory exists
# that this census does not name.
set PATS {
  DN_slot_mem      {*g_dnslot*}
  KV_slot_mem      {*g_kvslot*mem_reg*}
  KV_slot_emem     {*g_kvslot*emem*}
  CV_slot_wm       {*g_cvslot*wm_reg*}
  CV_slot_sm       {*g_cvslot*sm_reg*}
  SCRATCH_smem_a   {*smem_a*}
  SCRATCH_smem_b   {*smem_b*}
  ATTN_sc_mem      {*sc_mem*}
  ATTN_es_mem      {*es_mem*}
  ATTN_other       {u_attn/*}
  VECNORM          {u_vn/*}
  GATE             {u_gate/*}
  ALU              {u_alu/*}
  CONV_UNIT        {u_conv/*}
  SDMA             {u_dma/*}
  ROPE             {u_rope/*}
  DNSTEP           {u_dn/*}
}
puts "MEM_TABLE name URAM288 RAMB36 RAMB18 LUTRAM"
foreach {name pat} $PATS {
    set u [n "REF_NAME =~ URAM288* && NAME =~ $pat"]
    set b [n "REF_NAME =~ RAMB36*  && NAME =~ $pat"]
    set c [n "REF_NAME =~ RAMB18*  && NAME =~ $pat"]
    set l [n "(REF_NAME =~ RAMD* || REF_NAME =~ RAMS*) && NAME =~ $pat"]
    puts [format "MEM_ROW %-16s %5d %5d %5d %7d" $name $u $b $c $l]
}

# ---- the CLAIM under test: spec §3 says the conv slots are URAM (2 x 4 = 8).
# Say in one line what technology each conv memory actually got, and why the
# tool could choose: `wm`/`sm` carry NO ram_style attribute in the RTL, while
# the DN and KV row memories carry (* ram_style = "ultra" *).
foreach {label pat} {CV_wm {*g_cvslot*wm_reg*} CV_sm {*g_cvslot*sm_reg*}} {
    set cells [get_cells -quiet -hier -filter "NAME =~ $pat"]
    array unset refs; array set refs {}
    foreach c $cells {
        set r [get_property REF_NAME $c]
        if {[info exists refs($r)]} { incr refs($r) } else { set refs($r) 1 }
    }
    set line ""
    foreach r [lsort [array names refs]] { append line "$r=$refs($r) " }
    puts "MEM_CONV $label -> $line"
}

# ---- completeness: does the census account for every memory primitive? ------
foreach {kind filt} {URAM288 {REF_NAME =~ URAM288*} RAMB36 {REF_NAME =~ RAMB36*} RAMB18 {REF_NAME =~ RAMB18*}} {
    set all [get_cells -quiet -hier -filter $filt]
    set named {}
    foreach {name pat} $PATS {
        foreach c [get_cells -quiet -hier -filter "$filt && NAME =~ $pat"] { lappend named $c }
    }
    set named [lsort -unique $named]
    set miss {}
    foreach c $all { if {[lsearch -sorted -exact $named $c] < 0} { lappend miss $c } }
    puts "MEM_COVER $kind total=[llength $all] named=[llength $named] unnamed=[llength $miss]"
    foreach c [lrange $miss 0 19] { puts "MEM_UNNAMED $kind [get_property NAME $c]" }
}
puts "MEM_DONE"
