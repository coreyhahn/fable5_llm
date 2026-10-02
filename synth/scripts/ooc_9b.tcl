# ooc_9b.tcl — G4b Step 1: out-of-context STRUCTURE synthesis on the
# SHIPPING rtl/, at the 9B geometry Tasks 7-10 built.
#
# THIS IS NOT synth/exp_uram/scripts/exp_ooc.tcl.  That script reads
# synth/exp_uram/rtl/ (Track P's experiment copies, never functionally
# verified) and takes the geometry from -tclargs.  This one reads the real
# rtl/ and takes the geometry FROM THE RTL: at G3.4 the layer geometry became
# localparams (`rtl/layer_chan.sv:361-365` LNH/N_DN/N_KV/NKVH/CVD), so there
# is nothing left to pass and nothing that can silently disagree with what
# the testbenches replayed.
#
# It is COUNT ONLY.  synth_design answers inference; placement and timing are
# Task 13's, and this script deliberately does not run opt/place so that a
# structure number is never confused with a timing number.  (Track P already
# PLACED the equivalent wide geometry — evidence/qwen_next/place_exp/.)
#
# Usage:
#   vivado -mode batch -nojournal -source ooc_9b.tcl -tclargs \
#          <out_dir> <top> [dn_pipe]
#     <top>     layer_chan | matvec_chan | seq_unit
#     [dn_pipe] RETIRED (S2, 2026-09-04).  It used to override layer_chan's
#               DN_PIPE parameter, and the DN_PIPE=0 run was the CONTROL the
#               DN_PIPE=2 cost was differenced against.  The state-spill
#               design retired the 928-URAM banked DN array and the pipelined
#               SLR crossing with it, so the parameter no longer exists;
#               passing the argument is now a hard error rather than a
#               generic Vivado would refuse deep inside synth_design.
#
# Launcher: evidence/qwen9b/g4/run_g4b_ooc.sh (one out dir per run, never
# reused, ROM hex staged so $readmemh's relative default names resolve).

if {[llength $argv] < 2} {
    puts "FATAL: need <out_dir> <top> \[dn_pipe\]"
    exit 1
}
set OutDir [lindex $argv 0]
set Top    [lindex $argv 1]
set DnPipe [expr {[llength $argv] > 2 ? [lindex $argv 2] : -1}]
if {$DnPipe >= 0} {
    puts "FATAL: the dn_pipe argument is retired (S2) — layer_chan has no\
          such parameter any more; drop the third tclarg"
    exit 1
}

set ScriptDir [file dirname [file normalize [info script]]]
set RepoRoot  [file normalize "$ScriptDir/../.."]
set Rtl       "$RepoRoot/rtl"

# The board part, asserted rather than assumed: SQRL BCU-1525 carries an
# xcvu9p-fsgd2104-2L-e (repo CLAUDE.md "Lab facts"; create_project.tcl builds
# every shipped bitstream on the same string).
set Part xcvu9p-fsgd2104-2L-e

if {[string compare [version -short] "2024.2"] != 0} {
    puts "FATAL: this script expects Vivado 2024.2, got [version -short]"; exit 1
}

proc must {script} {
    if {[catch {uplevel 1 $script} err]} { puts "FATAL: $err"; exit 1 }
}

file mkdir $OutDir/reports
set_param general.maxThreads 8

puts "OOC9B_TOP: $Top"
puts "OOC9B_PART: $Part"
puts "OOC9B_VIVADO: [version -short]"
puts "OOC9B_DNPIPE_ARG: $DnPipe"

# ---------------------------------------------------------------- read design
# Explicit file order, not a glob: fx_pkg must be compiled before anything that
# imports it.  Same closure the shipped project adds
# (synth/scripts/create_project.tcl:69-101) and the same order the Verilator
# testbenches use (tb/Makefile LAYER_RTL / SEQ_RTL).
switch -- $Top {
    layer_chan {
        # S5 fix round 1 (2026-09-05): state_dma joins the list.  layer_chan
        # instantiates it (`state_dma u_dma`, rtl/layer_chan.sv:705), so a file
        # list without it elaborates the DMA as a BLACK BOX -- Vivado says so
        # only in a warning, while every LUT/FF number comes out silently
        # short.  synth/exp_uram/scripts/exp_ooc.tcl:164-165 carries the same
        # list, and tb/Makefile's LAYER_RTL is the third copy.
        set Files {fx_pkg fx_rsqrt fx_recip fx_silu vecnorm_unit rope_unit
                   conv4_silu dn_step attn_core gate_unit vec_alu state_dma
                   layer_chan}
        set Clocks {aclk}
    }
    matvec_chan {
        set Files {matvec_engine ddr_rd_streamer matvec_chan}
        set Clocks {aclk ui_clk}
    }
    seq_unit {
        set Files {seq_movers seq_unit}
        set Clocks {aclk}
    }
    default { puts "FATAL: unknown top '$Top'"; exit 1 }
}
foreach f $Files { must {read_verilog -sv $Rtl/$f.sv} }

# The ROM hex files keep their default RELATIVE names, so Vivado resolves
# $readmemh against the process CWD — run_g4b_ooc.sh symlinks rtl/roms/*.hex
# into $OutDir and cds there.  Asserted, not assumed:
if {[string equal $Top layer_chan]} {
    foreach r {rsqrt_rom sigmoid_pair_rom softplus_pair_rom exp2_pair_rom recip_rom} {
        if {![file exists $OutDir/$r.hex]} {
            puts "FATAL: $OutDir/$r.hex missing — evidence/qwen9b/g4/run_g4b_ooc.sh must stage rtl/roms"
            exit 1
        }
    }
}

# 250 MHz / 4.000 ns — the xdma_0_axi_aclk domain every shipped bitstream runs
# layer_0 and the four mvchans in (synth/scripts/build.tcl:34-42 gates on
# exactly this period).  matvec_chan's ui_clk is the MIG user clock; it is
# constrained at the same period here only so the OOC run is not unconstrained.
set xdc $OutDir/ooc_9b.xdc
set fh [open $xdc w]
foreach c $Clocks {
    puts $fh "create_clock -period 4.000 -name $c \[get_ports $c\]"
}
close $fh
must {read_xdc $xdc}

# ---------------------------------------------------------------------- synth
# S2 retired layer_chan's read-path pipelining parameter; there is no
# generic left to override on any of the three tops.
# S5 fix round 1 considered deleting the always-empty list and calling
# synth_design directly, and PUT IT BACK: `set generics {}` is the line
# evidence/qwen9b/s2/S2_RTL.md cites as the evidence for its own M2 fix
# ("there is no -generic left to append"), and deleting a line is a poor way
# to preserve the record that the line is empty on purpose.
set generics {}
set t0 [clock seconds]
must {eval synth_design -top $Top -part $Part -mode out_of_context $generics}
puts "OOC9B_SYNTH_S: [expr {[clock seconds]-$t0}]"

must {report_utilization -file $OutDir/reports/util_synth.rpt}
must {report_utilization -hierarchical -file $OutDir/reports/util_synth_hier.rpt}
must {write_checkpoint -force $OutDir/post_synth.dcp}

# ------------------------------------------------------- the headline census
# Primitive counts straight off the netlist, so the marker stream carries the
# numbers the gate doc is judged on without a reader having to parse a table.
proc ncells {pat} { return [llength [get_cells -quiet -hier -filter "REF_NAME =~ $pat"]] }
set uram   [ncells URAM288*]
set bram36 [ncells RAMB36*]
set bram18 [ncells RAMB18*]
set dsp    [ncells DSP48E2*]
puts "OOC9B_URAM: $uram"
puts "OOC9B_BRAM: RAMB36=$bram36 RAMB18=$bram18 tiles=[expr {$bram36 + $bram18 / 2.0}]"
puts "OOC9B_DSP: $dsp"

# report_utilization's own CLB rows, echoed so the marker stream and the .rpt
# cannot drift apart.  These are the rows §5.1 and §3.7 compare against.
proc util_row {rpt name} {
    set fh [open $rpt r]; set data [read $fh]; close $fh
    foreach line [split $data \n] {
        if {[regexp "^\\|\\s*[string map {* \\*} $name]\\s*\\|\\s*(\[0-9.\]+)\\s*\\|" $line -> v]} {
            return $v
        }
    }
    return "n/a"
}
set R $OutDir/reports/util_synth.rpt
set lut  [util_row $R "CLB LUTs*"]
set lutl [util_row $R "LUT as Logic"]
set lutm [util_row $R "LUT as Memory"]
set ff   [util_row $R "CLB Registers"]
set c8   [util_row $R "CARRY8"]
puts "OOC9B_LUT: $lut (logic $lutl, memory $lutm)"
puts "OOC9B_FF: $ff"
puts "OOC9B_CARRY8: $c8"

if {[string equal $Top layer_chan]} {
    # THE STOP CONDITION (brief Step 1), RESTATED FOR THE STATE-SPILL DESIGN
    # (S5 fix round 1, 2026-09-05).  What stood here was the study's 24 DN
    # banks x 29 URAM288 + 8 KV banks x 29 = 928, which Track P PLACED at the
    # same geometry (PLACE_EXP.md 3.1).  S2 retired the banked arrays: each
    # kind now keeps two CACHE SLOTS and the rest of the state lives in DDR
    # (spec 2026-09-04 state-spill 3).  A URAM288 is 4096 x 72 b, so a W-bit
    # row costs ceil(W/72) of them SIDE BY SIDE and a D-row memory ceil(D/4096)
    # DEEP.  DERIVED below by the same proc synth/exp_uram/scripts/exp_ooc.tcl
    # uses (its :115-121), so the two harnesses cannot disagree by a typo:
    #   DN slot  4096 rows x 2048 b                  -> 29
    #   KV slot  8192 rows x 2048 b                  -> 58, plus an 8192 x 8 b
    #            exponent memory that is BLOCK RAM BY DESIGN (`emem` carries no
    #            ram_style, rtl/layer_chan.sv:837) and predicts 0 URAM here
    #   CV slot  8192 x 64 b weights + 8192 x 48 b state -> 2 + 2 = 4
    #   total    N_SLOT x (29 + 58 + 4) = 2 x 91     = 182
    # The geometry is MAINTAINED here, not read out of the RTL
    # (rtl/layer_chan.sv:361-365 LNH/N_DN/N_KV/NKVH/CVD, N_SLOT at :382), so
    # this stays a prediction the measurement can contradict.  A disagreement
    # is news, not a number to reconcile: S5's first count read 174 because the
    # conv slots carried no ram_style and inferred block RAM instead
    # (evidence/qwen9b/s5/011_mem_census.log).
    proc uram_of {depth width} {
        return [expr {int(ceil($width / 72.0)) * int(ceil($depth / 4096.0))}]
    }
    set N_SLOT 2
    set PRED [expr {$N_SLOT * ([uram_of 4096 2048] + [uram_of 8192 2048] +
                               [uram_of 8192 64] + [uram_of 8192 48])}]
    puts "OOC9B_URAM_PREDICT: $PRED (2 slots x (DN 29 + KV 58 + CV 2 + 2))"
    if {$uram == $PRED} {
        puts "OOC9B_URAM_MATCH: YES"
    } else {
        puts "OOC9B_URAM_MATCH: NO — inferred $uram, predicted $PRED"
    }
    # Any SLOT memory that fell OUT of URAM is the "maps to something worse"
    # failure mode; name it rather than leaving it to a reader of the table.
    # S5 fix round 1 widened this from DN-only to all three kinds: a DN-only
    # probe read 0 on the very netlist whose conv slots had gone to block RAM.
    # The KV filter excludes `emem`, which is block RAM BY DESIGN
    # (rtl/layer_chan.sv:813, :837) and would otherwise read as a defect.
    proc nonuram {sel} {
        return [llength [get_cells -quiet -hier -filter \
            "($sel) && (REF_NAME =~ RAMB* || REF_NAME =~ RAMD* || REF_NAME =~ RAMS*)"]]
    }
    set dn_nonuram [nonuram {NAME =~ *g_dnslot*}]
    set kv_nonuram [nonuram {NAME =~ *g_kvslot* && NAME !~ *emem*}]
    set cv_nonuram [nonuram {NAME =~ *g_cvslot*}]
    puts "OOC9B_DN_NONURAM_CELLS: $dn_nonuram"
    puts "OOC9B_SLOT_NONURAM_CELLS: dn=$dn_nonuram kv=$kv_nonuram cv=$cv_nonuram"
    # and the split, so 58/116/8 is checked and not just the total.  The
    # generate-block names are the S2 slot names (`g_dnslot`, `g_kvslot`,
    # `g_cvslot` -- rtl/layer_chan.sv:766, :829, :882); the retired banked
    # array's `g_dn`/`g_kv`/`g_cv` patterns are gone with it.
    set dn_uram [llength [get_cells -quiet -hier \
        -filter {REF_NAME =~ URAM288* && NAME =~ *g_dnslot*}]]
    set kv_uram [llength [get_cells -quiet -hier \
        -filter {REF_NAME =~ URAM288* && NAME =~ *g_kvslot*}]]
    set cv_uram [llength [get_cells -quiet -hier \
        -filter {REF_NAME =~ URAM288* && NAME =~ *g_cvslot*}]]
    puts "OOC9B_URAM_SPLIT: dn=$dn_uram kv=$kv_uram cv=$cv_uram other=[expr {$uram - $dn_uram - $kv_uram - $cv_uram}]"
    # the block-RAM consumers this design is judged on: the scratchpad, the KV
    # exponent memories (block RAM by design), and the conv slots -- which MUST
    # now read 0, since spec 3 puts them in URAM.
    set scr_bram [llength [get_cells -quiet -hier \
        -filter {REF_NAME =~ RAMB36* && (NAME =~ *smem_a* || NAME =~ *smem_b*)}]]
    set cv_bram [llength [get_cells -quiet -hier \
        -filter {REF_NAME =~ RAMB36* && NAME =~ *g_cvslot*}]]
    set kvx_bram [llength [get_cells -quiet -hier \
        -filter {REF_NAME =~ RAMB36* && NAME =~ *g_kvslot*emem*}]]
    puts "OOC9B_BRAM_SPLIT: scratch=$scr_bram conv=$cv_bram kvexp=$kvx_bram"
}

puts "OOC9B_DONE"
