# g5d_clockroot_check.tcl <dcp> <xdc> [expected_root] [mode] — the guard for
# synth/constraints/fable5_clockroot_9b.xdc.  Two things are asserted: that the
# constraint TAKES, and that the DEPENDENCY it rests on still holds.
#
# WHY THIS EXISTS AND THE XDC DOES NOT CARRY ITS OWN GUARD.  Vivado's
# managed-project XDC parser accepts `set_property` but NOT `if` and NOT
# `puts`: the first version of that file carried two `if` guards and a
# confirming `puts` and the tool dropped all three with a CRITICAL WARNING
# each, leaving a constraint that could have matched zero nets and said
# nothing (`evidence/qwen9b/g5/132_t14b_clockroot_xdc_RED.txt`).  A
# `-source`d script is parsed by the FULL Tcl interpreter, so the guard works
# here and cannot work there.
#
# WHAT IT CHECKS, on a real checkpoint, in this order:
#   1. the aclk global net resolves to EXACTLY ONE net (the failure the XDC's
#      own `if` was meant to catch);
#   2. `USER_CLOCK_ROOT` on it BEFORE the file is applied — in `dry` mode
#      (the default) this is the RED half and must be EMPTY, or the "after"
#      reading would prove nothing; in `verify` mode (a checkpoint that was
#      IMPLEMENTED with the file) it must already equal the expected region;
#   3. `USER_CLOCK_ROOT` AFTER `read_xdc` of the file — the GREEN half, which
#      must equal the expected clock region.  `verify` mode reads the file
#      too, so the committed file's coordinate is checked against the one the
#      built design actually carries rather than assumed equal to it;
#   4. **THE DEPENDENCY.**  `X2Y2` is the centroid of `bd_i/layer_0`'s
#      dedicated blocks ON A PLACEMENT THAT PUT THE LAYER IN SLR0.  Three
#      campaigns have landed the layer on three different dies (S5 SLR1,
#      Task 14 SLR2, Task 14-B SLR0), so a future roll whose placer chooses a
#      different die makes the constant a COST rather than a gain, silently.
#      This script therefore censuses `layer_0`'s URAM288 cells by clock
#      region, maps each region to its SLR with the SAME device-measured
#      clock-region -> SLR mapping `synth/scripts/slr_census.tcl` uses
#      (`get_clock_regions -of_objects [get_slrs]`, its SLR_GEOMETRY block),
#      and REQUIRES the SLR holding the MAJORITY of those cells to be the SLR
#      of the clock root.  `CLOCKROOT_SLR_OK <slr>` or
#      `CLOCKROOT_SLR_MISMATCH layer=<slr> root=<slr>`, exit 1 on mismatch.
#      A clock-region row outside every MEASURED range answers `?`, and `?`
#      is now a REFUSAL on either side — `CLOCKROOT_SLR_UNRESOLVED`, exit 1
#      (#196).  It used to be carried into the verdict, where one "?" blamed
#      the placement and two compared EQUAL and printed `CLOCKROOT_SLR_OK ?`
#      with rc 0.
#      A URAM census is the right probe because URAM288 is the layer's own
#      dedicated resource (182 cells, all of them cache) and it cannot be
#      replicated or spread the way SLICE logic can.
#   5. the placer's own `CLOCK_ROOT` before and after, reported for contrast.
# Exit code 1 on any failure, so the caller's `=== rc:` is the verdict.
#
# HOW A FUTURE BUILD DETECTS A FLIP: run this script in `verify` mode on the
# candidate's routed checkpoint BEFORE `synth/scripts/final_verify.tcl`.  A
# roll whose placer moved the layer off SLR0 fails here with
# `CLOCKROOT_SLR_MISMATCH` instead of shipping a constraint that is pulling
# the clock root away from its own loads.
#
# READ-ONLY with respect to the design on disk: it opens a checkpoint, reads
# properties and applies the constraint IN MEMORY.  It writes nothing.
#
#   vivado -mode batch -nojournal -source g5d_clockroot_check.tcl \
#          -tclargs <routed.dcp> <xdc> [X2Y2] [dry|verify]

if {[llength $argv] < 2} { puts "CRC_FATAL: need <dcp> <xdc> \[expected_root\] \[dry|verify\]"; exit 1 }
set DCP  [lindex $argv 0]
set XDC  [lindex $argv 1]
set EXP  [expr {[llength $argv] > 2 ? [lindex $argv 2] : "X2Y2"}]
set MODE [expr {[llength $argv] > 3 ? [lindex $argv 3] : "dry"}]
if {$MODE ne "dry" && $MODE ne "verify"} { puts "CRC_FATAL: mode must be dry or verify, got '$MODE'"; exit 1 }
if {![file exists $DCP]} { puts "CRC_FATAL: no such checkpoint: $DCP"; exit 1 }
if {![file exists $XDC]} { puts "CRC_FATAL: no such XDC: $XDC"; exit 1 }
set_param general.maxThreads 8
puts "CRC_DCP: $DCP"
puts "CRC_XDC: $XDC"
puts "CRC_EXPECT: $EXP"
puts "CRC_MODE: $MODE"
open_checkpoint $DCP

set nets [get_nets -quiet -hier -filter {NAME =~ *diablo_gt.diablo_gt_phy_wrapper/phy_clk_i/PHY_USERCLK}]
puts "CRC_NET_COUNT: [llength $nets]"
if {[llength $nets] != 1} {
    puts "CRC_FATAL: expected exactly 1 aclk global net, found [llength $nets] — the XDC would constrain nothing"
    exit 1
}
set n [lindex $nets 0]
puts "CRC_NET: [get_property NAME $n]"
puts "CRC_LOADS: [get_property -quiet FLAT_PIN_COUNT $n]"

set before_user [get_property -quiet USER_CLOCK_ROOT $n]
set before_auto [get_property -quiet CLOCK_ROOT $n]
puts "CRC_BEFORE_USER_CLOCK_ROOT: '[expr {$before_user eq "" ? "(none)" : $before_user}]'"
puts "CRC_BEFORE_CLOCK_ROOT:      '[expr {$before_auto eq "" ? "(none)" : $before_auto}]'"
if {$MODE eq "dry"} {
    if {$before_user ne ""} {
        puts "CRC_FATAL: USER_CLOCK_ROOT is already '$before_user' on this checkpoint — the AFTER reading would prove nothing (use mode 'verify' for an implemented checkpoint)"
        exit 1
    }
    puts "CRC_RED_OK: no USER_CLOCK_ROOT before the file is applied"
} else {
    if {$before_user eq ""} {
        puts "CRC_FATAL: mode 'verify' expects a checkpoint IMPLEMENTED with the file, but USER_CLOCK_ROOT is unset"
        exit 1
    }
    if {$before_user ne $EXP} {
        puts "CRC_FATAL: the built design carries USER_CLOCK_ROOT '$before_user', expected '$EXP'"
        exit 1
    }
    puts "CRC_VERIFY_BEFORE_OK: the built design carries USER_CLOCK_ROOT '$before_user'"
}

if {[catch {read_xdc -quiet $XDC} err]} { puts "CRC_FATAL: read_xdc: $err"; exit 1 }
puts "CRC_XDC_READ_OK"

set after_user [get_property -quiet USER_CLOCK_ROOT $n]
set after_auto [get_property -quiet CLOCK_ROOT $n]
puts "CRC_AFTER_USER_CLOCK_ROOT:  '[expr {$after_user eq "" ? "(none)" : $after_user}]'"
puts "CRC_AFTER_CLOCK_ROOT:       '[expr {$after_auto eq "" ? "(none)" : $after_auto}]'"
if {$after_user ne $EXP} {
    puts "CRC_FATAL: USER_CLOCK_ROOT is '$after_user', expected '$EXP' — the constraint did NOT take"
    exit 1
}
puts "CRC_GREEN_OK: USER_CLOCK_ROOT '$after_user' on the one aclk net"

# ---------------------------------------------------------------------------
# THE DEPENDENCY: is the clock root's SLR the SLR the layer is actually on?
# ---------------------------------------------------------------------------
# Geometry first, measured from the device rather than assumed from folklore —
# the same method and the same objects as synth/scripts/slr_census.tcl's
# SLR_GEOMETRY block, so the two instruments cannot disagree about which
# clock-region rows belong to which die.
array set SLR_CRMIN {}
array set SLR_CRMAX {}
foreach s [get_slrs] {
    set nm [get_property NAME $s]
    set ys {}
    foreach cr [get_clock_regions -quiet -of_objects $s] {
        if {[regexp {X(\d+)Y(\d+)} [get_property NAME $cr] -> cx cy]} { lappend ys $cy }
    }
    set ys [lsort -integer -unique $ys]
    if {[llength $ys] == 0} { continue }
    set SLR_CRMIN($nm) [lindex $ys 0]
    set SLR_CRMAX($nm) [lindex $ys end]
    puts "CRC_SLR_GEOMETRY $nm CR_Y=[lindex $ys 0]..[lindex $ys end]"
}
if {[llength [array names SLR_CRMIN]] == 0} { puts "CRC_FATAL: no SLR geometry — cannot map a clock region to a die"; exit 1 }

proc slr_of_cry {y} {
    global SLR_CRMIN SLR_CRMAX
    foreach nm [lsort [array names SLR_CRMIN]] {
        if {$y >= $SLR_CRMIN($nm) && $y <= $SLR_CRMAX($nm)} { return $nm }
    }
    return "?"
}

# The root's SLR, from the region the constraint actually put on the net.
if {![regexp {^X(\d+)Y(\d+)$} $after_user -> root_x root_y]} {
    puts "CRC_FATAL: cannot parse clock region '$after_user'"
    exit 1
}
set root_slr [slr_of_cry $root_y]
puts "CRC_ROOT_REGION: $after_user"
puts "CRC_ROOT_SLR: $root_slr"
# THE VACUOUS PASS (#196, triage (b)15).  `slr_of_cry` answers "?" for a row
# outside every measured range, and "?" used to be carried straight into the
# verdict: one side "?" printed CLOCKROOT_SLR_MISMATCH and BLAMED THE
# PLACEMENT for what is a mapping failure, and BOTH sides "?" compared equal
# and printed `CLOCKROOT_SLR_OK ?` with rc 0 — the only mechanical guard on
# the shipping bitstream's X2Y2/SLR0 dependency, passing on no evidence at
# all.  Both sides go through a REFUSAL now: "?" is not an SLR and this
# script may not report an SLR verdict without one.
if {$root_slr eq "?"} {
    puts "CLOCKROOT_SLR_UNRESOLVED root_region=$after_user root_cr_y=$root_y"
    puts "CRC_FATAL: clock region '$after_user' is outside every measured SLR clock-region range, so the root's die is UNKNOWN — this check cannot pass on an unresolved SLR (#196)"
    exit 1
}

# The layer's SLR, from its own dedicated blocks.
set LAYER bd_i/layer_0
set urams [get_cells -quiet -hier -filter "REF_NAME =~ URAM288* && NAME =~ $LAYER/*"]
puts "CRC_LAYER_URAM_TOTAL: [llength $urams]"
if {[llength $urams] == 0} {
    puts "CRC_FATAL: no URAM288 cells under $LAYER — this check would assert nothing (the silent-no-op class)"
    exit 1
}
array set uh {}
array set crh {}
set unplaced 0
foreach u $urams {
    set cr ""
    set st [get_sites -quiet -of_objects $u]
    if {[llength $st] > 0} { set cr [get_property -quiet CLOCK_REGION [lindex $st 0]] }
    if {$cr eq ""} {
        set loc [get_property -quiet LOC $u]
        if {$loc ne ""} {
            set st2 [get_sites -quiet $loc]
            if {[llength $st2] > 0} { set cr [get_property -quiet CLOCK_REGION [lindex $st2 0]] }
        }
    }
    if {$cr eq ""} { incr unplaced; continue }
    if {[info exists crh($cr)]} { incr crh($cr) } else { set crh($cr) 1 }
    if {![regexp {^X(\d+)Y(\d+)$} $cr -> lx ly]} { continue }
    set nm [slr_of_cry $ly]
    if {[info exists uh($nm)]} { incr uh($nm) } else { set uh($nm) 1 }
}
foreach cr [lsort [array names crh]] { puts "CRC_LAYER_URAM_CR $cr $crh($cr)" }
puts "CRC_LAYER_URAM_UNPLACED: $unplaced"
set line "CRC_LAYER_URAM_BY_SLR:"
set best ""; set bestn 0; set tot 0
foreach nm [lsort [array names uh]] {
    append line " $nm=$uh($nm)"
    incr tot $uh($nm)
    if {$uh($nm) > $bestn} { set bestn $uh($nm); set best $nm }
}
puts $line
if {$tot == 0} { puts "CRC_FATAL: no URAM288 cell under $LAYER resolved to a clock region"; exit 1 }
puts [format "CRC_LAYER_SLR: %s (%d of %d = %.1f%%)" $best $bestn $tot [expr {100.0*$bestn/$tot}]]
# The layer half of the same refusal (#196).  ANY unresolved cell is a
# refusal, not just an unresolved MAJORITY: a census in which 82 of 182 URAMs
# fell outside every measured range would still elect SLR0 on the other 100
# and print OK, on a geometry that is demonstrably not describing this device.
if {[info exists uh(?)] || $best eq "?"} {
    puts "CLOCKROOT_SLR_UNRESOLVED layer=$best layer_unresolved_cells=[expr {[info exists uh(?)] ? $uh(?) : 0}] of $tot"
    puts "CRC_FATAL: [expr {[info exists uh(?)] ? $uh(?) : 0}] of $tot $LAYER URAM288 cells sit in a clock region outside every measured SLR range, so the layer's die is UNKNOWN — this check cannot pass on an unresolved SLR (#196)"
    exit 1
}

if {$best ne $root_slr} {
    puts "CLOCKROOT_SLR_MISMATCH layer=$best root=$root_slr"
    puts "CRC_FATAL: the clock root '$after_user' is in $root_slr but the majority of $LAYER's URAM288 cells are in $best — USER_CLOCK_ROOT $EXP is the WRONG coordinate for this placement and would pull the root AWAY from its own loads"
    exit 1
}
puts "CLOCKROOT_SLR_OK $best"
puts "CRC_OK"
