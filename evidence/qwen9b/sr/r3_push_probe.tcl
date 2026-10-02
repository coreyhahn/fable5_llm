# r3_push_probe.tcl <routed_dcp> <out_dir> [ctl <comma_globs> <exp_cells>] — R3-10 step 4, READ-ONLY on a
# routed checkpoint: proves the R3-8 x-push bus (seq_0 -> mvchan_c XWIN, rtl/seq_movers.sv R3 block,
# rtl/matvec_chan.sv R3 block, the 20 BD nets of synth/scripts/create_project.tcl) is aclk-only at BOTH
# ends and fully TIMED with NO timing exception — so it needs no false path and no XDC edit.
# Built on evidence/qwen9b/sr/sr14_fp_cover.tcl's structure (a different question, so a new file).
# Nothing is written into any out dir: reports go to <out_dir> (a scratch dir), the dcp is never saved.
#
# Default mode (the push bus), per channel c = 0..3, four register groups:
#   SEQ_FWD c  seq_0 u_mov xp_v_q_reg[c], xp_i_q_reg[c][*], xp_d_q_reg[c][*]   (expected 45)
#   MV_FWD  c  mvchan_c xp_in_v_reg, xp_in_d_reg[*]                           (expected 45)
#   MV_RET  c  mvchan_c xpush_room_reg, xpush_busy_reg                        (expected 2)
#   SEQ_RET c  seq_0 u_mov xp_room_q_reg[c], xp_busy_q_reg[c]                 (expected 2)
# (a) cells by name, count and grouping; (b) every C pin clocked by xdma_0_axi_aclk only;
# (c) report_exceptions -from / -to the cells: an EXPLICIT empty result (rows counted);
# (d) get_timing_paths SEQ_FWD->MV_FWD and MV_RET->SEQ_RET, setup and hold, every path timed
#     (finite slack, no EXCEPTION), worst per channel, plus the paths into / out of the bus flops
#     (the R3-8 review's watch list) and the three named mvchan_0 SLR crossings;
# (e) the fanout endpoints of every bus flop are on xdma_0_axi_aclk only, and no timed path runs
#     from a bus flop to a UI clock (mmcm_clkout0*) — the only aclk->UI crossing is u_xfifo's.
#   PP_VERDICT TIMED_NO_EXCEPTION | EXCEPTED | FAIL(<why>)
# ctl mode (the CONTROLS): the cells are the comma-separated NAME globs (no spaces); the same (b), (c),
# (d: every setup/hold path FROM them, any endpoint) checks; verdict TIMED_NO_EXCEPTION or EXCEPTED.
set dcp [lindex $argv 0]
set od  [lindex $argv 1]
set mode push
if {[llength $argv] >= 5 && [lindex $argv 2] eq "ctl"} {
    set mode ctl; set cglobs [split [lindex $argv 3] ,]; set cexp [lindex $argv 4]
}
file mkdir $od
open_checkpoint $dcp
puts "PP_CHECKPOINT: $dcp size=[file size $dcp] mtime=[clock format [file mtime $dcp] -format {%Y-%m-%dT%H:%M:%S}] mode=$mode"
set aclk [get_clocks -quiet xdma_0_axi_aclk]
set ui   [get_clocks -quiet -filter {NAME =~ mmcm_clkout0*}]
puts "PP_CLOCKS: aclk={$aclk} ui={$ui}"

# --- helpers -------------------------------------------------------------------------------------
# clock set of a cell list's C pins
proc pp_clocks {cells} {
    set out {}
    foreach x $cells {
        foreach k [get_clocks -quiet -of_objects [get_pins -quiet $x/C]] { if {[lsearch -exact $out $k] < 0} { lappend out $k } }
    }
    return [lsort $out]
}
# report_exceptions rows (lines beginning with a Position number) into the log; returns the row count
proc pp_exc {tag args} {
    global od
    set f $od/pp_exc_$tag.rpt
    if {[catch {report_exceptions {*}$args -file $f} e]} { puts "PP_EXC $tag ERR: $e"; return -1 }
    set fh [open $f r]; set t [read $fh]; close $fh
    set n 0
    foreach l [split $t "\n"] {
        puts "PP_EXC_RPT $tag | $l"
        if {[regexp {^\s*\d+\s+\S} $l]} { incr n }
    }
    puts "PP_EXC $tag rows=$n"
    return $n
}
# timed-path census: returns {total bad worst_setup worst_hold worst_setup_path}
proc pp_paths {tag fromc toc {maxp 2000}} {
    set tot 0; set bad 0; set ws inf; set wh inf; set wsp ""
    foreach dly {setup hold} {
        set args [list -quiet -$dly -max_paths $maxp -nworst 1]
        if {[llength $fromc]} { lappend args -from $fromc }
        if {[llength $toc]}   { lappend args -to $toc }
        set tp [get_timing_paths {*}$args]
        foreach p $tp {
            incr tot
            set s [get_property SLACK $p]; set ex [get_property -quiet EXCEPTION $p]
            if {$s eq "" || $s eq "inf" || $ex ne ""} {
                incr bad
                puts "PP_UNTIMED $tag $dly [get_property STARTPOINT_PIN $p] -> [get_property ENDPOINT_PIN $p] slack=$s exception={$ex}"
                continue
            }
            if {$dly eq "setup"} {
                if {$ws eq "inf" || $s < $ws} { set ws $s; set wsp "[get_property STARTPOINT_PIN $p] -> [get_property ENDPOINT_PIN $p]" }
            } else {
                if {$wh eq "inf" || $s < $wh} { set wh $s }
            }
        }
    }
    puts "PP_PATHS $tag total=$tot untimed_or_excepted=$bad worst_setup=$ws worst_hold=$wh"
    if {$wsp ne ""} { puts "PP_PATHS $tag   worst setup: $wsp" }
    return [list $tot $bad $ws $wh]
}
proc pp_slr {pin} {
    set c [get_cells -quiet -of_objects [get_pins -quiet $pin]]
    set s [get_slrs -quiet -of_objects $c]
    return [expr {$s eq "" ? "?" : $s}]
}

# --- ctl mode ------------------------------------------------------------------------------------
if {$mode eq "ctl"} {
    set parts {}; foreach g $cglobs { lappend parts "NAME =~ $g" }
    set flt [join $parts " || "]
    set c [get_cells -quiet -hierarchical -filter "($flt) && IS_SEQUENTIAL"]
    puts "PP_CTL_FILTER: {$flt} cells=[llength $c] (expected $cexp)"
    foreach x [lsort $c] { puts "PP_CTL_CELL $x REF=[get_property REF_NAME $x] clock={[pp_clocks $x]} slr=[get_slrs -quiet -of_objects $x]" }
    set ck [pp_clocks $c]
    puts "PP_CTL_CLOCKS: {$ck}"
    set nf [pp_exc ctl_from -from $c]
    set nt [pp_exc ctl_to -to $c]
    set r [pp_paths ctl_from $c {}]
    if {[llength $c] != $cexp} {
        puts "PP_VERDICT: FAIL(cell count [llength $c] != $cexp)"
    } elseif {$nf == 0 && $nt == 0 && [lindex $r 0] > 0 && [lindex $r 1] == 0} {
        puts "PP_VERDICT: TIMED_NO_EXCEPTION"
    } elseif {$nf > 0 || $nt > 0 || [lindex $r 1] > 0} {
        puts "PP_VERDICT: EXCEPTED (exception rows from=$nf to=$nt, untimed/excepted paths=[lindex $r 1])"
    } else {
        puts "PP_VERDICT: FAIL(no timed path from the cells)"
    }
    puts "PP_DONE"; exit 0
}

# --- push mode -----------------------------------------------------------------------------------
set fails {}
set allbus {}
array set G {}
for {set ch 0} {$ch < 4} {incr ch} {
    # n3221 fix: the generate-loop copies are named u_mov/g_xp[c].xp_i_q_reg[c][b] / g_xp[c].xp_d_q_reg[c][b]
    # (seq_0's OOC netlist, n3226); the first filter (u_mov/xp_i_q_reg...) matched none of them.
    set G(SEQ_FWD,$ch) [get_cells -quiet -hierarchical -filter "IS_SEQUENTIAL && (NAME =~ *seq_0/*u_mov/xp_v_q_reg\[$ch\]* || NAME =~ *seq_0/*u_mov/g_xp?$ch?.xp_i_q_reg* || NAME =~ *seq_0/*u_mov/g_xp?$ch?.xp_d_q_reg*)"]
    set G(SEQ_RET,$ch) [get_cells -quiet -hierarchical -filter "IS_SEQUENTIAL && (NAME =~ *seq_0/*u_mov/xp_room_q_reg\[$ch\]* || NAME =~ *seq_0/*u_mov/xp_busy_q_reg\[$ch\]*)"]
    set G(MV_FWD,$ch)  [get_cells -quiet -hierarchical -filter "IS_SEQUENTIAL && (NAME =~ *mvchan_$ch/*xp_in_v_reg* || NAME =~ *mvchan_$ch/*xp_in_d_reg*)"]
    set G(MV_RET,$ch)  [get_cells -quiet -hierarchical -filter "IS_SEQUENTIAL && (NAME =~ *mvchan_$ch/*xpush_room_reg* || NAME =~ *mvchan_$ch/*xpush_busy_reg*)"]
}
array set EXP {SEQ_FWD 45 MV_FWD 45 MV_RET 2 SEQ_RET 2}
# (a) + (b)
for {set ch 0} {$ch < 4} {incr ch} {
    foreach g {SEQ_FWD MV_FWD MV_RET SEQ_RET} {
        set c $G($g,$ch)
        set ck [pp_clocks $c]
        set slrs [lsort -unique [get_slrs -quiet -of_objects $c]]
        set reps [llength [lsearch -all $c *_rep*]]
        puts "PP_GROUP $g ch$ch cells=[llength $c] expected=$EXP($g) replicas=$reps clocks={$ck} slr={$slrs}"
        if {[llength $c] != $EXP($g)} { lappend fails "count $g ch$ch [llength $c]!=$EXP($g)" }
        if {$ck ne $aclk} { lappend fails "clock $g ch$ch {$ck}" }
        foreach x [lsort $c] { puts "PP_CELL $g ch$ch $x REF=[get_property REF_NAME $x] slr=[get_slrs -quiet -of_objects $x]" }
        set allbus [concat $allbus $c]
    }
}
puts "PP_BUS_CELLS: [llength $allbus] (expected 376 = 4 x 94)"
# (c) exceptions, from and to the bus cells, and through their D/Q nets' pins
set nf [pp_exc bus_from -from $allbus]
set nt [pp_exc bus_to -to $allbus]
set nft [pp_exc bus_from_to -from $allbus -to $allbus]
if {$nf != 0 || $nt != 0 || $nft != 0} { lappend fails "exceptions from=$nf to=$nt from_to=$nft" }
# (d) the bus hops, per channel, forward and return; then the watch list into / out of the flops
for {set ch 0} {$ch < 4} {incr ch} {
    set r [pp_paths fwd_ch$ch $G(SEQ_FWD,$ch) $G(MV_FWD,$ch)]
    if {[lindex $r 0] == 0 || [lindex $r 1] != 0} { lappend fails "fwd ch$ch total=[lindex $r 0] bad=[lindex $r 1]" }
    set r [pp_paths ret_ch$ch $G(MV_RET,$ch) $G(SEQ_RET,$ch)]
    if {[lindex $r 0] == 0 || [lindex $r 1] != 0} { lappend fails "ret ch$ch total=[lindex $r 0] bad=[lindex $r 1]" }
    pp_paths into_seqfwd_ch$ch {} $G(SEQ_FWD,$ch)
    pp_paths out_mvfwd_ch$ch $G(MV_FWD,$ch) {}
    pp_paths into_mvret_ch$ch {} $G(MV_RET,$ch)
    pp_paths out_seqret_ch$ch $G(SEQ_RET,$ch) {}
    # watch list 4 / 5: xp_cnt -> ... -> s_axib_wready / burst slice; the skid read -> u_xfifo din
    set xc [get_cells -quiet -hierarchical -filter "IS_SEQUENTIAL && NAME =~ *mvchan_$ch/*xp_cnt_reg*"]
    if {[llength $xc]} { pp_paths wl4_xpcnt_ch$ch $xc {} } else { puts "PP_PATHS wl4_xpcnt_ch$ch: no xp_cnt cells" }
    set xm [get_cells -quiet -hierarchical -filter "NAME =~ *mvchan_$ch/*xp_mem_reg*"]
    set xf [get_cells -quiet -hierarchical -filter "IS_SEQUENTIAL && NAME =~ *mvchan_$ch/*u_xfifo*"]
    if {[llength $xm] && [llength $xf]} { pp_paths wl5_skid_to_xfifo_ch$ch $xm $xf } else { puts "PP_PATHS wl5_skid_to_xfifo_ch$ch: cells skid=[llength $xm] xfifo=[llength $xf]" }
}
# the three named SLR crossings on mvchan_0 (the R3-8 review's watch list 1-3), each named
foreach {tag fromc toc} [list xing_fwd_mv0 $G(SEQ_FWD,0) $G(MV_FWD,0) xing_room_mv0 \
        [get_cells -quiet -hierarchical -filter {IS_SEQUENTIAL && NAME =~ *mvchan_0/*xpush_room_reg*}] \
        [get_cells -quiet -hierarchical -filter {IS_SEQUENTIAL && NAME =~ *seq_0/*u_mov/xp_room_q_reg[0]*}] \
        xing_busy_mv0 \
        [get_cells -quiet -hierarchical -filter {IS_SEQUENTIAL && NAME =~ *mvchan_0/*xpush_busy_reg*}] \
        [get_cells -quiet -hierarchical -filter {IS_SEQUENTIAL && NAME =~ *seq_0/*u_mov/xp_busy_q_reg[0]*}]] {
    foreach dly {setup hold} {
        set tp [get_timing_paths -quiet -from $fromc -to $toc -$dly -max_paths 1 -nworst 1]
        foreach p $tp {
            set sp [get_property STARTPOINT_PIN $p]; set ep [get_property ENDPOINT_PIN $p]
            puts "PP_XING $tag $dly slack=[get_property SLACK $p] $sp (SLR [pp_slr $sp]) -> $ep (SLR [pp_slr $ep]) exception={[get_property -quiet EXCEPTION $p]} logic_levels=[get_property -quiet LOGIC_LEVELS $p] datapath=[get_property -quiet DATAPATH_DELAY $p]"
        }
        if {[llength $tp] == 0} { puts "PP_XING $tag $dly: NO PATH"; lappend fails "xing $tag $dly no path" }
    }
}
# (e) fanout endpoint clocks of every bus flop; timed paths from the bus to a UI clock
set eclk {}
foreach x $allbus {
    foreach e [all_fanout -quiet -from [get_pins -quiet $x/Q] -endpoints_only -flat] {
        set ecp [get_pins -quiet -filter {IS_CLOCK} -of_objects [get_cells -quiet -of_objects $e]]
        foreach k [get_clocks -quiet -of_objects $ecp] { if {[lsearch -exact $eclk $k] < 0} { lappend eclk $k } }
    }
}
puts "PP_FANOUT_ENDPOINT_CLOCKS: {[lsort $eclk]}"
if {[lsort $eclk] ne $aclk} { lappend fails "fanout endpoint clocks {$eclk}" }
set tpu [get_timing_paths -quiet -from $allbus -to $ui -setup -max_paths 100 -nworst 1]
puts "PP_BUS_TO_UI_PATHS: [llength $tpu] (expected 0)"
foreach p $tpu { puts "PP_BUS_TO_UI [get_property STARTPOINT_PIN $p] -> [get_property ENDPOINT_PIN $p] slack=[get_property SLACK $p] exception={[get_property -quiet EXCEPTION $p]}" }
if {[llength $tpu] != 0} { lappend fails "bus->UI paths [llength $tpu]" }
# seq_0's own worst setup / hold (as sr14_fp_cover.tcl prints it)
foreach pat {*seq_0/*/D *seq_0*u_seq/*/D} {
    set ps [get_pins -quiet -hier -filter "NAME =~ $pat"]
    set ts [get_timing_paths -quiet -to $ps -setup -max_paths 1 -nworst 1]
    set th [get_timing_paths -quiet -to $ps -hold  -max_paths 1 -nworst 1]
    set ss [expr {[llength $ts] ? [get_property SLACK [lindex $ts 0]] : "none"}]
    set hs [expr {[llength $th] ? [get_property SLACK [lindex $th 0]] : "none"}]
    puts "PP_SEQ0 $pat pins=[llength $ps] worst_setup=$ss worst_hold=$hs"
    if {[llength $ts]} { puts "PP_SEQ0   from [get_property STARTPOINT_PIN [lindex $ts 0]] to [get_property ENDPOINT_PIN [lindex $ts 0]]" }
}
if {[llength $fails] == 0} {
    puts "PP_VERDICT: TIMED_NO_EXCEPTION"
} else {
    foreach f $fails { puts "PP_FAIL: $f" }
    puts "PP_VERDICT: FAIL([llength $fails] checks)"
}
puts "PP_DONE"
