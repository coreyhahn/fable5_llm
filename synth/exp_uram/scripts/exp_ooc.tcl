# exp_ooc.tcl — Track P URAM placement experiment, RE-POINTED AT THE SHIPPING
# RTL for G5a (Task 13, the OOC floorplan experiment).
#
# THE QUESTION (docs/QWEN35_NEXT_FEASIBILITY.md §6 item 3, §8 D3):
#   does a layer_chan at the 4B/9B head geometry — DN state 24 URAM banks
#   (24 layers x 32 value heads x 128 rows), KV 8 banks, 928 URAM288 = 96.7 %
#   of the VU9P's 960, necessarily spanning 3 SLRs — synthesize to the
#   predicted 928, and then PLACE?  Track P answered "places, does not close":
#   the binding path is the DN write-control fan-out at -1.391 ns
#   (evidence/qwen_next/place_exp/PLACE_EXP.md §3.7-3.8).  G5a asks whether a
#   PLACEMENT CONSTRAINT closes it, so this script now takes pblocks as data.
#
#   synth_design alone answers INFERENCE only.  place_design is the MINIMUM
#   run that answers placement, because URAM columns are physical and the
#   320-per-SLR limit binds at placement.  This script therefore runs
#   synth_design -mode out_of_context THEN opt_design + place_design.
#
# ===== S5 CHANGE OF DESIGN (2026-09-05, state spill) ========================
# S2 replaced the 928-URAM banked layer state with TWO CACHE SLOTS per kind
# plus DDR behind `state_dma` (spec 2026-09-04 state-spill 0, 3, 4).  Three
# things follow, and all three are in this script:
#   (a) rtl/state_dma.sv joins the file list -- layer_chan instantiates it
#       (rtl/layer_chan.sv:705 `state_dma u_dma`), so a file list without it
#       elaborates the DMA as a BLACK BOX and undercounts the whole design.
#   (b) DN_PIPE and DN_BPG are GONE as parameters.  S2 retired the pipelined
#       fan-out/return structure with the 24-bank array it was built to span,
#       so layer_chan's only non-ROM parameter is SDMA_NOFENCE (a testbench
#       knob whose shipping value is its default 0, rtl/layer_chan.sv:241).
#       They are removed from the POSITIONAL ARGUMENT LIST as well, so
#       launch_exp.sh's -tclargs line moves with them.
#   (c) the URAM prediction is no longer banks x 29.  It is the two-slot
#       arithmetic of spec 3: 2 x 29 + 2 x 58 + 2 x 4 = 182.
# The QUESTION also changes: not "does 928 place across three SLRs" but
# "does 182 place inside ONE" (spec 12 risk 1).
#
# ===== G5a STEP 1 CHANGE OF VEHICLE (2026-09-03) =============================
# Track P read synth/exp_uram/rtl/ — a COPY of rtl/ with an EXPERIMENT banner,
# deliberately never functionally verified.  Tasks 7-10 landed the 9B geometry
# in the SHIPPING rtl/ and the copy drifted (950 diff lines in layer_chan.sv
# alone).  This script now reads $RepoRoot/rtl DIRECTLY, so "the thing placed
# is the thing that ships" is a property of the script rather than of a copy
# that has to be kept in step.  Every file it reads is echoed as EXP_RTL_SRC.
#
# Consequence: at G3.4 the geometry became LOCALPARAMS in rtl/layer_chan.sv
# (now :361-365, LNH/N_DN/N_KV/NKVH/CVD) and DN_EW/DN_PACK were GONE (A1 ruled
# the state container int16).  At G5a, DN_PIPE and DN_BPG were the only two
# parameters left and were passed as -generic; SUPERSEDED BY THE S5 BLOCK
# ABOVE — S2 retired both, and nothing is passed as -generic any more.  The
# remaining positional geometry arguments are kept — Track P's reproduction
# lines and the G5a brief both spell them out — but they are now ASSERTIONS:
# a value the shipping RTL cannot express is a hard error, not a silently
# ignored -generic.
# =============================================================================
#
# Usage (S5 argument order -- DN_PIPE and DN_BPG REMOVED):
#   vivado -mode batch -nojournal -source exp_ooc.tcl -tclargs \
#     <out_dir> <variant> <LNH> <N_DN> <N_KV> <NKVH> <CVD> <DN_EW> <DN_PACK> \
#     <place0|1> [directive] [extra.xdc ...]

if {[llength $argv] < 10} {
    puts "FATAL: need <out_dir> <variant> <LNH> <N_DN> <N_KV> <NKVH> <CVD> <DN_EW> <DN_PACK> <place0|1> \[directive\] \[extra.xdc ...\]"
    exit 1
}
lassign $argv OutDir Variant LNH N_DN N_KV NKVH CVD DN_EW DN_PACK DoPlace
set Directive [expr {[llength $argv] > 10 ? [lindex $argv 10] : "Default"}]
# argv 11 onward: zero or more IMPLEMENTATION-ONLY XDC files, applied in order.
# A LIST rather than a single file, exactly as synth/scripts/full_impl.tcl:11-16
# takes them, so the winning floorplan geometry stays byte-untouched while a
# separate exception file is layered on top.
set ExtraXdcs {}
foreach a [lrange $argv 11 end] { if {$a ne ""} { lappend ExtraXdcs $a } }

set ScriptDir [file dirname [file normalize [info script]]]
set RepoRoot  [file normalize "$ScriptDir/../../.."]
set Rtl       "$RepoRoot/rtl"
set Roms      "$RepoRoot/rtl/roms"

# The board part, asserted rather than assumed: SQRL BCU-1525 carries an
# xcvu9p-fsgd2104-2L-e (repo CLAUDE.md "Lab facts", and create_project.tcl
# builds every shipped bitstream on the same string).
set Part xcvu9p-fsgd2104-2L-e

if {[string compare [version -short] "2024.2"] != 0} {
    puts "FATAL: this script expects Vivado 2024.2, got [version -short]"; exit 1
}

proc must {script} {
    if {[catch {uplevel 1 $script} err]} { puts "FATAL: $err"; exit 1 }
}

file mkdir $OutDir/reports
set_param general.maxThreads 8

# ---------------------------------------------------------------- predictions
# S5: the arithmetic of spec 2026-09-04 state-spill 3, recomputed here so the
# log carries the number the run is judged against.  A URAM288 is 4096 x 72 b,
# so a W-bit row costs ceil(W/72) URAM288s SIDE BY SIDE and a D-row memory
# costs ceil(D/4096) of them DEEP.  This REPLACES the banks x 29 arithmetic of
# study 2.7 / Track P: there are no banks any more, only N_SLOT cache slots
# per kind (spec 3, the table).
#
#   DN slot   4096 rows x 2048 b                 -> 29 x 1 = 29
#   KV slot   8192 rows x 2048 b                 -> 29 x 2 = 58
#             + an 8192 x 8 b exponent memory which is BLOCK RAM BY DESIGN
#               (`emem` deliberately carries no ram_style, rtl/layer_chan.sv:837)
#               and therefore contributes 0 to this prediction
#   CV slot   8192 x 64 b weights + 8192 x 48 b state, TWO memories
#                                                 -> (1 x 2) + (1 x 2) = 4
#   total     N_SLOT x (29 + 58 + 4) = 2 x 91     = 182
#
# N_DN / N_KV / NKVH survive as the LAYER-COUNT envelope of the ISA range
# check (rtl/layer_chan.sv:361-365) and no longer size a bank, so they do NOT
# appear in this arithmetic -- which is the whole point of the state spill.
set N_SLOT  2
proc uram_of {depth width} {
    return [expr {int(ceil($width / 72.0)) * int(ceil($depth / 4096.0))}]
}
set DN_PER  [uram_of 4096 2048]
set KV_PER  [uram_of 8192 2048]
set CV_PER  [expr {[uram_of $CVD 64] + [uram_of $CVD 48]}]
set PRED    [expr {$N_SLOT * ($DN_PER + $KV_PER + $CV_PER)}]
puts "EXP_VARIANT: $Variant"
puts "EXP_PARAMS: LNH=$LNH N_DN=$N_DN N_KV=$N_KV NKVH=$NKVH CVD=$CVD DN_EW=$DN_EW DN_PACK=$DN_PACK N_SLOT=$N_SLOT"
puts "EXP_DIRECTIVE: $Directive"
puts "EXP_PART: $Part"
puts "EXP_PREDICT: DN $N_SLOT x $DN_PER + KV $N_SLOT x $KV_PER + CV $N_SLOT x $CV_PER = $PRED URAM288"

# ---- the geometry arguments are ASSERTIONS now, not -generics --------------
# rtl/layer_chan.sv:361-365 fixes LNH/N_DN/N_KV/NKVH/CVD as localparams, and
# the strings DN_EW / DN_PACK do not occur in that file AT ALL (A1 ruled the
# state container int16 and the G3.4 packing knob went with it), so 16 / 0 are
# the only values this vehicle can build.  Passing anything else would measure
# a design the RTL cannot build, so it stops here rather than producing a
# number under a false label.
# NOTE WHAT THIS IS AND IS NOT: the expected values below are a LITERAL LIST
# MAINTAINED IN THIS SCRIPT.  It is not read from the RTL, so it catches a
# caller passing the wrong geometry but NOT the RTL's localparams changing
# underneath it.  The check that the RTL still builds what the argument
# describes is EXP_SYNTH_URAM vs EXP_PREDICT, further down.
set GeomExpect {LNH 32 N_DN 24 N_KV 8 NKVH 4 CVD 8192 DN_EW 16 DN_PACK 0}
set geom_ok 1
foreach {k v} $GeomExpect {
    if {[set $k] != $v} {
        puts "EXP_GEOM_MISMATCH: $k=[set $k], shipping rtl/layer_chan.sv has $v"
        set geom_ok 0
    }
}
if {!$geom_ok} {
    puts "FATAL: the shipping rtl/ carries the 9B geometry as LOCALPARAMS and has"
    puts "       no DN_EW / DN_PACK knob — this vehicle can only build that one"
    puts "       geometry.  (rtl/layer_chan.sv:361-365)"
    exit 1
}
puts "EXP_GEOM_ASSERT: OK — args match this script's literal GeomExpect list,\n  which tracks rtl/layer_chan.sv:361-365 by MAINTENANCE, not by reading it;\n  EXP_SYNTH_URAM vs EXP_PREDICT is what checks the RTL itself"

# ---------------------------------------------------------------- read design
# THE SHIPPING rtl/, not synth/exp_uram/rtl/.  Same explicit file order and
# same closure as synth/scripts/ooc_9b.tcl:83-85 and create_project.tcl:69-101
# (fx_pkg must be compiled before anything that imports it).
puts "EXP_RTL_DIR: $Rtl"
# S5: state_dma is instantiated by layer_chan (rtl/layer_chan.sv:705) and must
# be read BEFORE it -- without it the DMA elaborates as a BLACK BOX, which
# Vivado reports only as a warning while silently undercounting LUT/FF.
foreach f {fx_pkg fx_rsqrt fx_recip fx_silu vecnorm_unit rope_unit conv4_silu
           dn_step attn_core gate_unit vec_alu state_dma layer_chan} {
    puts "EXP_RTL_SRC: $Rtl/$f.sv"
    must {read_verilog -sv $Rtl/$f.sv}
}

# 250 MHz / 4.000 ns — the xdma_0_axi_aclk domain layer_0 lives in on every
# shipped bitstream (synth/scripts/build.tcl:34-42 gates on exactly this).
set xdc $OutDir/exp_ooc.xdc
# The ROM hex files keep their default RELATIVE names, so Vivado resolves
# $readmemh against the process CWD — launch_exp.sh symlinks rtl/roms/*.hex
# into $OutDir and cds there.  Asserted, not assumed:
foreach r {rsqrt_rom sigmoid_pair_rom softplus_pair_rom exp2_pair_rom recip_rom} {
    if {![file exists $OutDir/$r.hex]} {
        puts "FATAL: $OutDir/$r.hex missing — launch_exp.sh must stage rtl/roms"
        exit 1
    }
}

set fh [open $xdc w]
puts $fh "create_clock -period 4.000 -name aclk \[get_ports aclk\]"
close $fh
must {read_xdc $xdc}

# ---------------------------------------------------------------------- synth
# S5: NO -generic at all.  DN_PIPE and DN_BPG are gone (S2 retired the banked
# DN array they configured); layer_chan's only remaining non-ROM parameter is
# SDMA_NOFENCE (rtl/layer_chan.sv:241), a TESTBENCH knob whose shipping value
# is its default 0 -- overriding it here would synthesize a design that does
# not ship.  Everything else is a localparam.
puts "EXP_GENERICS: none (SDMA_NOFENCE left at its shipping default 0)"
must {synth_design -top layer_chan -part $Part -mode out_of_context}

must {report_utilization -file $OutDir/reports/util_synth.rpt}
must {report_utilization -hierarchical -file $OutDir/reports/util_synth_hier.rpt}
must {write_checkpoint -force $OutDir/post_synth.dcp}

set uram_s [llength [get_cells -quiet -hier -filter {REF_NAME =~ URAM288*}]]
set bram36 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB36*}]]
set bram18 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB18*}]]
set dsp_s  [llength [get_cells -quiet -hier -filter {REF_NAME =~ DSP48E2*}]]
puts "EXP_SYNTH_URAM: $uram_s  (predicted $PRED)"
puts "EXP_SYNTH_BRAM: RAMB36=$bram36 RAMB18=$bram18"
puts "EXP_SYNTH_DSP: $dsp_s"
if {$uram_s == $PRED} {
    puts "EXP_SYNTH_URAM_MATCH: YES"
} else {
    puts "EXP_SYNTH_URAM_MATCH: NO — inferred $uram_s, study predicts $PRED"
}
# Any SLOT memory that fell OUT of URAM is the failure mode the study called
# "maps to something worse"; name it explicitly rather than leaving it to a
# reader of the utilization table.
#
# S5 fix round 2 widened this from DN-only to all three kinds, and the filters
# below are COPIED from synth/scripts/ooc_9b.tcl's OOC9B_SLOT_NONURAM_CELLS so
# the two harnesses probe the same cells.  The reason is this harness's own
# record: the DN-only probe printed EXP_SYNTH_DN_NONURAM_CELLS: 0 on the
# 174-URAM netlist whose CONV slots had gone to block RAM
# (evidence/qwen9b/s5/010_ooc_counts.log) -- true, and blind to the failure.
# The KV filter excludes `emem`, which is block RAM BY DESIGN
# (rtl/layer_chan.sv:813, :837) and would otherwise read as a defect.
proc nonuram {sel} {
    return [llength [get_cells -quiet -hier -filter \
        "($sel) && (REF_NAME =~ RAMB* || REF_NAME =~ RAMD* || REF_NAME =~ RAMS*)"]]
}
set dn_lutram [nonuram {NAME =~ *g_dnslot*}]
set kv_lutram [nonuram {NAME =~ *g_kvslot* && NAME !~ *emem*}]
set cv_lutram [nonuram {NAME =~ *g_cvslot*}]
puts "EXP_SYNTH_DN_NONURAM_CELLS: $dn_lutram"
puts "EXP_SYNTH_KV_NONURAM_CELLS: $kv_lutram"
puts "EXP_SYNTH_CV_NONURAM_CELLS: $cv_lutram"
set slot_nonuram [expr {$dn_lutram + $kv_lutram + $cv_lutram}]
puts "EXP_SYNTH_SLOT_NONURAM_CELLS: dn=$dn_lutram kv=$kv_lutram cv=$cv_lutram total=$slot_nonuram"
# attn_core's sc_mem (rtl/attn_core.sv:69, 512 x 32 b, no ram_style) is a KNOWN
# tool-inference wobble, NOT a design difference: Task 12 saw it as one RAMB18
# at DN_PIPE=0 and as 256 LUTRAM cells at DN_PIPE=2 (a parameter S2 retired;
# the two Task-12 runs are the only place those labels still mean anything),
# while Track P kept it in BRAM both times
# (evidence/qwen9b/g4/G4B_STRUCT.md).  Say which way it went.
set sc_b [llength [get_cells -quiet -hier -filter {NAME =~ *sc_mem* && REF_NAME =~ RAMB*}]]
set sc_l [llength [get_cells -quiet -hier -filter {NAME =~ *sc_mem* && (REF_NAME =~ RAMD* || REF_NAME =~ RAMS*)}]]
puts "EXP_SC_MEM: RAMB=$sc_b LUTRAM=$sc_l"
puts "EXP_SYNTH_OK"

if {$DoPlace == 0} { puts "EXP_DONE (synth only)"; exit 0 }

# ------------------------------------------- implementation-only extra XDC
# synth/scripts/full_impl.tcl:21-30 is the pattern: the extra XDC is applied
# to the IMPLEMENTATION only, never to synthesis.  full_impl.tcl runs in
# PROJECT mode, so it says that with `add_files -fileset constrs_1` +
# `set_property USED_IN_SYNTHESIS false`.  This script is NON-project (
# read_verilog + synth_design in memory), where there is no constrs_1 fileset;
# the equivalent — and the only form available — is read_xdc AFTER
# synth_design and BEFORE opt_design.  Same effect, same marker text, so the
# pblock is DATA and not code.
if {[llength $ExtraXdcs] == 0} {
    puts "EXTRA_XDC: none"
} else {
    foreach x $ExtraXdcs {
        if {![file exists $x]} { puts "FATAL: extra XDC not found: $x"; exit 1 }
        must {read_xdc $x}
        puts "EXTRA_XDC: $x (implementation-only)"
    }
}
# Floorplan sanity, copied from full_impl.tcl:50-59: prove the pblocks actually
# took, rather than assuming the XDC was read.  A pblock that failed to match
# any cell is silently harmless in Vivado, which is exactly how a floorplan
# campaign can measure nothing.
set pbs [get_pblocks -quiet]
puts "EXP_PBLOCK_COUNT: [llength $pbs]"
set pb_empty 0
foreach pb $pbs {
    set cells [get_cells -quiet -of_objects $pb]
    puts [format "EXP_PBLOCK %s cells=%d range={%s}" \
        $pb [llength $cells] [get_property GRID_RANGES $pb]]
    if {[llength $cells] == 0} { incr pb_empty }
}
if {$pb_empty > 0} {
    puts "FATAL: $pb_empty pblock(s) matched ZERO cells — the floorplan measured nothing"
    exit 1
}

# ------------------------------------------------------------- opt + place
# opt_design then place_design is the shipped impl_1 order (build.tcl runs
# launch_runs impl_1, Vivado Implementation Defaults).
set t0 [clock seconds]
if {[catch {opt_design} err]} {
    puts "EXP_OPT_FAILED: $err"
    must {report_utilization -file $OutDir/reports/util_optfail.rpt}
    exit 2
}
puts "EXP_OPT_OK ([expr {[clock seconds]-$t0}] s)"

set t0 [clock seconds]
if {[catch {place_design -directive $Directive} err]} {
    puts "EXP_PLACE_FAILED: $err"
    catch {report_utilization -file $OutDir/reports/util_placefail.rpt}
    catch {write_checkpoint -force $OutDir/post_placefail.dcp}
    puts "EXP_DONE (place FAILED)"
    exit 3
}
set place_s [expr {[clock seconds]-$t0}]
puts "EXP_PLACE_OK ($place_s s)"
must {write_checkpoint -force $OutDir/post_place.dcp}

must {report_utilization -file $OutDir/reports/util_placed.rpt}
catch {report_utilization -slr -file $OutDir/reports/util_placed_slr.rpt}
must {report_timing_summary -file $OutDir/reports/timing_summary_placed.rpt}
must {report_clock_utilization -file $OutDir/reports/clock_util_placed.rpt}

# ------------------------------------------ where the URAM banks landed, by SLR
# Method note (same trap slr_census.tcl documents): filtering cells BY an SLR
# object silently returns nothing.  Map each placed site to its SLR instead.
proc slr_of_cell {c} {
    set st [get_sites -quiet -of_objects $c]
    if {$st eq ""} { return "unplaced" }
    set s [get_slrs -quiet -of_objects $st]
    if {$s eq ""} { return "?" }
    return [get_property NAME $s]
}
proc cr_of_cell {c} {
    set st [get_sites -quiet -of_objects $c]
    if {$st eq ""} { return "unplaced" }
    set r [get_clock_regions -quiet -of_objects $st]
    if {$r eq ""} { return "?" }
    return [get_property NAME $r]
}
set fh [open $OutDir/reports/uram_slr_census.rpt w]
puts $fh "URAM288 placement census — variant $Variant"
puts $fh "part $Part, 960 URAM288 total, 320 per SLR"
puts $fh ""
array set slrcnt {}
foreach c [get_cells -quiet -hier -filter {REF_NAME =~ URAM288*}] {
    set s [slr_of_cell $c]
    if {[info exists slrcnt($s)]} { incr slrcnt($s) } else { set slrcnt($s) 1 }
}
set tot 0
foreach s [lsort [array names slrcnt]] {
    puts $fh [format "  %-10s %4d URAM288" $s $slrcnt($s)]
    incr tot $slrcnt($s)
}
puts $fh [format "  %-10s %4d URAM288" TOTAL $tot]
set nslr [llength [array names slrcnt]]
puts $fh ""
puts $fh "SLRs spanned by the URAM banks: $nslr"
# same census restricted to each cache kind's slots.  S5: the conv slots are
# URAM too now (spec 3: 2 x 4), so CV_CACHE joins DN_STATE and KV_CACHE --
# without it the three per-kind lines would not add up to TOTAL.
foreach {label pat} {DN_STATE *g_dnslot* KV_CACHE *g_kvslot* CV_CACHE *g_cvslot*} {
    array unset h; array set h {}
    foreach c [get_cells -quiet -hier -filter "REF_NAME =~ URAM288* && NAME =~ $pat"] {
        set s [slr_of_cell $c]
        if {[info exists h($s)]} { incr h($s) } else { set h($s) 1 }
    }
    set line ""
    foreach s [lsort [array names h]] { append line [format "%s=%d " $s $h($s)] }
    puts $fh "  $label : $line"
}

# ---- S5 REPLACEMENT of G5a's per-DN-GROUP block.  The DN pipeline groups
# (`g_grp[N]`) and their fan-out register sets (`*_p_reg`) were RETIRED with
# the 24-bank array in S2, so the old block matched nothing and printed an
# empty section.  What S5 needs instead is the clock region of every cache
# slot's URAM, because the question is whether all 182 sit inside ONE SLR --
# and, if they do, which clock-region rows of the URAM columns they use.
puts $fh ""
puts $fh "---- per cache SLOT: URAM SLR and clock regions ----"
puts $fh "(URAM288 sites live only in CLOCKREGION columns X1..X4, 16 per region)"
# `?` is the single-character wildcard of Vivado's -filter glob and is how a
# literal `[` or `]` is matched, exactly as Task 13's XDCs do it: `g_dnslot?0?.`
# means `g_dnslot[0].`.  Enumerating the slots this way needs no regexp against
# a cell name and cannot silently match the wrong slot.
foreach {label stem} {DN g_dnslot KV g_kvslot CV g_cvslot} {
    for {set sl 0} {$sl < $N_SLOT} {incr sl} {
        array unset scr;  array set scr {}
        array unset sslr; array set sslr {}
        set n 0
        foreach c [get_cells -quiet -hier \
                -filter "REF_NAME =~ URAM288* && NAME =~ *${stem}?${sl}?.*"] {
            incr n
            set r [cr_of_cell $c]
            if {[info exists scr($r)]} { incr scr($r) } else { set scr($r) 1 }
            set S [slr_of_cell $c]
            if {[info exists sslr($S)]} { incr sslr($S) } else { set sslr($S) 1 }
        }
        set ul {}; set xl {}
        foreach k [lsort [array names sslr]] { lappend xl "$k=$sslr($k)" }
        foreach k [lsort [array names scr]]  { lappend ul "$k=$scr($k)" }
        puts $fh [format "  %s_slot\[%d\] %4d URAM288  SLR: %s" \
            $label $sl $n [join $xl { }]]
        puts $fh [format "  %s_slot\[%d\]      clock regions: %s" \
            $label $sl [join $ul { }]]
    }
}
close $fh
puts "EXP_URAM_SLR_SPAN: $nslr"
foreach s [lsort [array names slrcnt]] { puts "EXP_URAM_SLR $s $slrcnt($s)" }

# ---------------------------------------- the 2048-bit DN bank-mux read path
# dn_rdq_reg is the fabric OREG the per-bank URAM CQs mux into
# (rtl/layer_chan.sv, "fabric OREG: URAM CQ off the path").
# This is the path §6 item 3 names.  Report it post-place with SLR endpoints.
# rtl/layer_chan.sv:508 declares `dn_rdq` and :652 registers it, so the final
# OREG is dn_rdq_reg[*].  `dn_rdq_n_reg` was the EXPERIMENT COPY's name and
# matches NOTHING in the shipping RTL — which the script then reported as
# "the mux register was absorbed", a wrong answer rather than an error.
set muxdst [get_cells -quiet -hier -filter {NAME =~ *dn_rdq_reg*}]
# G5a's DN_PIPE>0 variants exposed per-group return registers here.  S2
# RETIRED the pipeline groups, so this filter is EXPECTED to match zero cells
# on the state-spill design; a non-zero count would mean the banked structure
# came back.  Kept as that check rather than deleted.
set grpdst [get_cells -quiet -hier -filter {NAME =~ *g_grp*rq_p*reg*}]
puts "EXP_DNGRP_ENDPOINT_CELLS: [llength $grpdst]"
if {[llength $grpdst] > 0} {
    report_timing -to $grpdst -max_paths 10 -nworst 10 -setup \
        -file $OutDir/reports/dn_group_return_paths.rpt
    set gw [lindex [get_timing_paths -to $grpdst -max_paths 1 -nworst 1 -setup] 0]
    puts "EXP_DNGRP_WORST_SLACK: [get_property SLACK $gw]"
}
# and the write-control fan-out, which owns the ACTUAL worst endpoint
set wrdst [get_cells -quiet -hier -filter {REF_NAME =~ URAM288* && NAME =~ *g_dn*}]
if {[llength $wrdst] > 0} {
    report_timing -to $wrdst -max_paths 10 -nworst 10 -setup \
        -file $OutDir/reports/dn_write_fanout_paths.rpt
    set ww [lindex [get_timing_paths -to $wrdst -max_paths 1 -nworst 1 -setup] 0]
    puts "EXP_DNWRITE_WORST_SLACK: [get_property SLACK $ww]"
    # G5a: the DECOMPOSITION, in the marker stream.  The whole reading of this
    # experiment turns on "one logic level, ~96 % route", so it must not live
    # only inside a 40 KB report a reader has to parse.
    # PROPERTY NAMES MEASURED, not guessed: a timing_path carries
    # DATAPATH_LOGIC_DELAY / DATAPATH_NET_DELAY, and there is no LOGIC_DELAY or
    # NET_DELAY — get_property on those raises Common 17-54 and aborts the whole
    # script AFTER place_design, which is the most expensive possible place to
    # find out (evidence/qwen9b/g5/004_timing_path_props.log).
    set dl [get_property DATAPATH_DELAY $ww]
    set ld [get_property DATAPATH_LOGIC_DELAY $ww]
    set rd [get_property DATAPATH_NET_DELAY $ww]
    set lv [get_property LOGIC_LEVELS $ww]
    set pct "n/a"
    if {$dl ne "" && $dl > 0} { set pct [format "%.1f" [expr {100.0*$rd/$dl}]] }
    puts "EXP_DNWRITE_DECOMP: levels=$lv datapath=$dl logic=$ld route=$rd route_pct=$pct"
    puts "EXP_DNWRITE_START: [get_property STARTPOINT_PIN $ww]"
    puts "EXP_DNWRITE_END: [get_property ENDPOINT_PIN $ww]"
    set sc [get_cells -quiet -of_objects [get_property STARTPOINT_PIN $ww]]
    set ec [get_cells -quiet -of_objects [get_property ENDPOINT_PIN $ww]]
    puts "EXP_DNWRITE_SLR: [slr_of_cell $sc] -> [slr_of_cell $ec]"
    puts "EXP_DNWRITE_CR: [cr_of_cell $sc] -> [cr_of_cell $ec]"
}
puts "EXP_DNMUX_ENDPOINT_CELLS: [llength $muxdst]"
set fh [open $OutDir/reports/dn_bank_mux_paths.rpt w]
puts $fh "DN 2048-bit bank-mux read path — post-PLACE estimate, variant $Variant"
puts $fh "endpoint: dn_rdq_reg\[*\] (the registered bank mux fed by the"
puts $fh "per-bank URAM CQ registers).  Clock aclk, 4.000 ns / 250 MHz."
puts $fh ""
if {[llength $muxdst] > 0} {
    set paths [get_timing_paths -to $muxdst -max_paths 30 -nworst 30 -setup]
    puts $fh [format "%-9s %-9s %-9s %s" slack levels startSLR endSLR]
    foreach pth $paths {
        set sp [get_property STARTPOINT_PIN $pth]
        set ep [get_property ENDPOINT_PIN $pth]
        set sc [get_cells -quiet -of_objects $sp]
        set ec [get_cells -quiet -of_objects $ep]
        puts $fh [format "%-9s %-9s %-9s %-9s  %s -> %s" \
            [get_property SLACK $pth] [get_property LOGIC_LEVELS $pth] \
            [slr_of_cell $sc] [slr_of_cell $ec] $sp $ep]
    }
    set w [lindex $paths 0]
    puts "EXP_DNMUX_WORST_SLACK: [get_property SLACK $w]"
    puts $fh ""
    puts $fh "---- full report_timing on the worst 10 ----"
    close $fh
    report_timing -to $muxdst -max_paths 10 -nworst 10 -setup \
        -file $OutDir/reports/dn_bank_mux_paths.rpt -append
} else {
    puts $fh "NO dn_rdq_reg CELLS FOUND — the mux register was absorbed."
    close $fh
    puts "EXP_DNMUX_WORST_SLACK: n/a"
}

# same for the KV bank mux (at_kvdata_reg), 8 banks at the wide geometry
set kvdst [get_cells -quiet -hier -filter {NAME =~ *at_kvdata_reg*}]
if {[llength $kvdst] > 0} {
    report_timing -to $kvdst -max_paths 10 -nworst 10 -setup \
        -file $OutDir/reports/kv_bank_mux_paths.rpt
    set kw [lindex [get_timing_paths -to $kvdst -max_paths 1 -nworst 1 -setup] 0]
    puts "EXP_KVMUX_WORST_SLACK: [get_property SLACK $kw]"
}

# the whole-design worst path, decomposed, whatever family it belongs to
set wp [lindex [get_timing_paths -max_paths 1 -nworst 1 -setup] 0]
set wns [get_property SLACK $wp]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
puts "EXP_PLACED_WNS: $wns"
puts "EXP_PLACED_WHS: $whs"
puts "EXP_WNS_START: [get_property STARTPOINT_PIN $wp]"
puts "EXP_WNS_END: [get_property ENDPOINT_PIN $wp]"
puts "EXP_WNS_DECOMP: levels=[get_property LOGIC_LEVELS $wp] datapath=[get_property DATAPATH_DELAY $wp] logic=[get_property DATAPATH_LOGIC_DELAY $wp] route=[get_property DATAPATH_NET_DELAY $wp]"

# TNS / failing endpoints, straight off the timing summary so the gate doc's
# table is traceable to a committed report rather than to a re-derivation.
set tsrpt $OutDir/reports/timing_summary_placed.rpt
set fh [open $tsrpt r]; set tsdata [read $fh]; close $fh
# NOTE the variable names: `h` is an ARRAY earlier in this script (the
# DN_STATE / KV_CACHE census), and reusing it as a regexp capture kills the run
# with `can't set "h": variable is array` — at the LAST marker, after
# place_design.  Prefixed names cannot collide.
foreach line [split $tsdata \n] {
    if {[regexp {^\s*(-?[0-9.]+)\s+(-?[0-9.]+)\s+(\d+)\s+(\d+)\s+(-?[0-9.]+)\s+(-?[0-9.]+)\s+(\d+)\s+(\d+)\s+} $line \
            -> ts_wns ts_tns ts_tfe ts_tte ts_whs ts_ths ts_hfe ts_hte]} {
        puts "EXP_TIMING_SUMMARY: WNS=$ts_wns TNS=$ts_tns TNS_FAILING_EP=$ts_tfe TNS_TOTAL_EP=$ts_tte WHS=$ts_whs THS=$ts_ths THS_FAILING_EP=$ts_hfe THS_TOTAL_EP=$ts_hte"
        break
    }
}
puts "EXP_DONE"
