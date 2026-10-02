# final_verify.tcl <dcp> <exception_xdc> — signoff verification of the SHIPPING
# checkpoint. Independent of the run that produced it: opens the checkpoint,
# applies the final constraint set, and re-derives every claim being made.
set dcp [lindex $argv 0]
set XDC [lindex $argv 1]
open_checkpoint $dcp
read_xdc -quiet $XDC
puts "FV_CHECKPOINT: $dcp"
puts "FV_WNS: [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]"
puts "FV_WHS: [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]"
set fail [get_timing_paths -max_paths 5000 -nworst 1 -setup -slack_lesser_than 0]
puts "FV_FAILING_SETUP: [llength $fail]"
foreach p $fail { puts "FV_FAIL [get_property SLACK $p] [get_property GROUP $p] [get_property ENDPOINT_PIN $p]" }
set hfail [get_timing_paths -max_paths 5000 -nworst 1 -hold -slack_lesser_than 0]
puts "FV_FAILING_HOLD: [llength $hfail]"
# The engine's x-line register cone, by name, per channel.
#
# THE NAME IS NETLIST-DEPENDENT, and hardcoding one of them turns this script
# from a signoff into a false FATAL.  On the W8 netlists (build_034/035) the
# cone is `xline_q0_reg` — the pair of banks RC_W8_GATE.md's outstanding debt
# was written about.  The 9B campaign STRIPPED W8 (plan Goal: "W8 and g64
# stripped"), and rtl/matvec_engine.sv:300 now declares a single
# `logic [1023:0] xline_q`, enable-loaded at rtl/matvec_engine.sv:319-330 —
# so on that netlist the cone is `xline_q_reg` and the old pattern matches
# nothing, which the still-checked loop below would report as
# `FV_FATAL: ... NOT ANALYSED`.
#
# Resolve it from the checkpoint instead: try the W8 name first so build_035's
# checkpoint verifies EXACTLY as it did before, fall back to the 9B name, and
# FATAL only if NEITHER exists — which would mean the cone really is gone.
set XLINE_PAT ""
foreach cand {*u_engine/xline_q0_reg*/CE *u_engine/xline_q_reg*/CE} {
    if {[llength [get_pins -quiet -hier -filter "NAME =~ $cand"]] > 0} {
        set XLINE_PAT $cand; break
    }
}
if {$XLINE_PAT eq ""} {
    puts "FV_FATAL: no u_engine xline register cone found (tried xline_q0_reg and xline_q_reg)"; exit 1
}
puts "FV_XLINE_PATTERN: $XLINE_PAT"
set xp [get_timing_paths -to [get_pins -quiet -hier -filter "NAME =~ $XLINE_PAT"] -setup -max_paths 1000 -nworst 1]
array set cw {}
foreach p $xp {
    set ep [get_property ENDPOINT_PIN $p]; set s [get_property SLACK $p]
    if {[regexp {mvchan_(\d+)} $ep -> m]} { if {![info exists cw($m)] || $s < $cw($m)} { set cw($m) $s } }
}
foreach c [lsort [array names cw]] { puts "FV_XLINE_WORST_mvchan_$c: $cw($c)" }
# Custom-RTL classes still analysed?  The first three are the classes
# build_034 and build_035 tracked; the state spill adds two more that this
# build is the first to place in context, so they are asserted here too —
# `u_dma` is the state-DMA engine (spec 2026-09-04 section 4) and `u_attn` is
# the ATTN_DSP family S5 named as a residual owner (S5_STRUCT.md section 4.5).
# An endpoint class that silently stops being analysed is the failure mode
# this loop exists for.
foreach pat [list *layer_0*u_core/u_dn/*/D *layer_0*u_core/u_dma/*/D *layer_0*u_core/u_attn/*/D *seq_0*u_seq/*/D $XLINE_PAT] {
    set ps [get_pins -quiet -hier -filter "NAME =~ $pat"]
    set tp [get_timing_paths -quiet -to $ps -setup -max_paths 1 -nworst 1]
    if {[llength $tp] == 0} { puts "FV_FATAL: $pat NOT ANALYSED"; exit 1 }
    puts "FV_STILL_CHECKED $pat slack=[get_property SLACK [lindex $tp 0]]"
}
puts "FV_OK"
