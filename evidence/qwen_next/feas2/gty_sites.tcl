# gty_sites.tcl -- Qwen3.5-next TWO-BOARD feasibility study, step f02.
# READ-ONLY device-model query on xcvu9p-fsgd2104-2L-e.  No project, no build.
# Q1: which GTY quads do the BCU-1525's two QSFP28 cages land on, and do they
#     collide with GTY_Quad_227 (used by XDMA PCIe x8)?
# Pin data source: references/Custom_Part_Data_Files/Boards/Xilinx_BCU1525/BCU1525_QSFP.xdc
# PCIe pin data source: synth/constraints/BCU1525_DIMM0.xdc + VCU1525 part0_pins.xml

set PART xcvu9p-fsgd2104-2L-e
puts "### PART = $PART"
puts "### Vivado = [version -short]"

create_project -in_memory -part $PART
puts "### create_project -in_memory OK; current part = [get_property PART [current_project]]"
if {[catch {link_design -part $PART} msg]} {
  puts "### link_design NOT used (expected on a netlist-less in-memory project): $msg"
} else {
  puts "### link_design OK"
}

# ---------------------------------------------------------------------------
puts "\n===== SECTION A: property-name discovery on one package pin (K11) ====="
set pp [lindex [get_package_pins K11] 0]
puts "A: object      = $pp"
puts "A: list_property = [join [lsort [list_property $pp]] {, }]"
puts "A: --- report_property -all ---"
if {[catch {report_property -all $pp} msg]} { puts "A: report_property FAILED: $msg" }
puts "A: --- get_sites -of_objects ---"
if {[catch {set s [get_sites -of_objects $pp]} msg]} {
  puts "A: get_sites -of_objects FAILED: $msg"
} else {
  puts "A: get_sites -of_objects K11 = $s"
  if {[llength $s]} {
    puts "A: site list_property = [join [lsort [list_property [lindex $s 0]]] {, }]"
  }
}

# ---------------------------------------------------------------------------
# helper: one line per package pin
proc pinline {tag p} {
  set pp [get_package_pins $p]
  if {[llength $pp] == 0} { puts "PIN $tag $p  -> NOT FOUND"; return }
  set pp [lindex $pp 0]
  set bank "?" ; set func "?" ; set site "?" ; set stype "?" ; set slr "?" ; set cr "?"
  catch {set bank [get_property BANK $pp]}
  catch {set func [get_property PIN_FUNC $pp]}
  catch {set site [get_property SITE_NAME $pp]}
  set so {}
  catch {set so [get_sites -quiet -of_objects $pp]}
  if {[llength $so]} {
    set site [lindex $so 0]
    catch {set stype [get_property SITE_TYPE [lindex $so 0]]}
    catch {set cr    [get_property CLOCK_REGION [lindex $so 0]]}
    catch {set slr   [get_property NAME [get_slrs -quiet -of_objects [lindex $so 0]]]}
    if {$slr eq "" || $slr eq "?"} { catch {set slr [get_property SLR [lindex $so 0]]} }
  }
  puts [format "PIN %-22s %-5s site=%-22s type=%-16s bank=%-5s clkreg=%-6s slr=%-6s func=%s" \
        $tag $p $site $stype $bank $cr $slr $func]
}

puts "\n===== SECTION B: BCU-1525 QSFP0 cage pins (community XDC) ====="
pinline QSFP0_CLOCK_P K11
pinline QSFP0_CLOCK_N K10
pinline QSFP0_TX1_P   N9
pinline QSFP0_TX1_N   N8
pinline QSFP0_RX1_P   N4
pinline QSFP0_RX1_N   N3
pinline QSFP0_TX2_P   M7
pinline QSFP0_TX2_N   M6
pinline QSFP0_RX2_P   M2
pinline QSFP0_RX2_N   M1
pinline QSFP0_TX3_P   L9
pinline QSFP0_TX3_N   L8
pinline QSFP0_RX3_P   L4
pinline QSFP0_RX3_N   L3
pinline QSFP0_TX4_P   K7
pinline QSFP0_TX4_N   K6
pinline QSFP0_RX4_P   K2
pinline QSFP0_RX4_N   K1

puts "\n===== SECTION C: BCU-1525 QSFP1 cage pins (community XDC) ====="
pinline QSFP1_CLOCK_P P11
pinline QSFP1_CLOCK_N P10
pinline QSFP1_TX1_P   U9
pinline QSFP1_TX1_N   U8
pinline QSFP1_RX1_P   U4
pinline QSFP1_RX1_N   U3
pinline QSFP1_TX2_P   T7
pinline QSFP1_TX2_N   T6
pinline QSFP1_RX2_P   T2
pinline QSFP1_RX2_N   T1
pinline QSFP1_TX3_P   R9
pinline QSFP1_TX3_N   R8
pinline QSFP1_RX3_P   R4
pinline QSFP1_RX3_N   R3
pinline QSFP1_TX4_P   P7
pinline QSFP1_TX4_N   P6
pinline QSFP1_RX4_P   P2
pinline QSFP1_RX4_N   P1

puts "\n===== SECTION D: on-board Si570 MGT refclks ====="
pinline MGT_SI570_CLOCK0_P M11
pinline MGT_SI570_CLOCK0_N M10
pinline MGT_SI570_CLOCK1_P T11
pinline MGT_SI570_CLOCK1_N T10

puts "\n===== SECTION E: PCIe / XDMA pins (to fix Quad 227 empirically) ====="
pinline PCIE_REFCLK_P  AM11
pinline PCIE_REFCLK_N  AM10
pinline PCIE_LANE0_P   AF2
pinline PCIE_LANE0_N   AF1
pinline PCIE_LANE1_P   AG4
pinline PCIE_LANE1_N   AG3
pinline PCIE_LANE2_P   AH2
pinline PCIE_LANE2_N   AH1
pinline PCIE_LANE3_P   AJ4
pinline PCIE_LANE3_N   AJ3
pinline PCIE_LANE4_P   AK2
pinline PCIE_LANE4_N   AK1
pinline PCIE_LANE5_P   AL4
pinline PCIE_LANE5_N   AL3
pinline PCIE_LANE6_P   AM2
pinline PCIE_LANE6_N   AM1
pinline PCIE_LANE7_P   AN4
pinline PCIE_LANE7_N   AN3

# ---------------------------------------------------------------------------
puts "\n===== SECTION F: every GTYE4_COMMON site on the part (quad roster) ====="
set commons [get_sites -quiet -filter {SITE_TYPE =~ GTYE4_COMMON*}]
puts "F: GTYE4_COMMON count = [llength $commons]"
foreach s [lsort $commons] {
  set cr "?" ; set slr "?"
  catch {set cr [get_property CLOCK_REGION $s]}
  catch {set slr [get_property NAME [get_slrs -quiet -of_objects $s]]}
  # bank number of the quad: take it from any package pin on that site
  set bank "?"
  set pps [get_package_pins -quiet -of_objects $s]
  if {[llength $pps]} { catch {set bank [get_property BANK [lindex $pps 0]]} }
  puts [format "COMMON %-22s clkreg=%-7s slr=%-6s bank/quad=%-5s pins=%s" $s $cr $slr $bank $pps]
}

puts "\n===== SECTION G: every GTYE4_CHANNEL site on the part ====="
set chans [get_sites -quiet -filter {SITE_TYPE =~ GTYE4_CHANNEL*}]
puts "G: GTYE4_CHANNEL count = [llength $chans]"
foreach s [lsort $chans] {
  set cr "?" ; set slr "?"
  catch {set cr [get_property CLOCK_REGION $s]}
  catch {set slr [get_property NAME [get_slrs -quiet -of_objects $s]]}
  set bank "?"
  set pps [get_package_pins -quiet -of_objects $s]
  if {[llength $pps]} { catch {set bank [get_property BANK [lindex $pps 0]]} }
  puts [format "CHANNEL %-22s clkreg=%-7s slr=%-6s bank/quad=%-5s pins=%s" $s $cr $slr $bank $pps]
}

# ---------------------------------------------------------------------------
puts "\n===== SECTION H: bank roster from get_iobanks (GT banks only) ====="
if {[catch {
  foreach b [lsort -integer [get_property NAME [get_iobanks -quiet *]]] {
    if {$b >= 120 && $b <= 240} {
      set bk [get_iobanks -quiet $b]
      set bt "?"
      catch {set bt [get_property BANK_TYPE $bk]}
      puts "BANK $b  type=$bt"
    }
  }
} msg]} { puts "H: get_iobanks FAILED: $msg" }

# ---------------------------------------------------------------------------
puts "\n===== SECTION I: VERDICT -- quad assignment and Quad-227 collision ====="
proc quadof {p} {
  set pp [get_package_pins -quiet $p]
  if {[llength $pp] == 0} { return "NOTFOUND" }
  set b "?"
  catch {set b [get_property BANK [lindex $pp 0]]}
  return $b
}
proc slrof {p} {
  set pp [get_package_pins -quiet $p]
  if {[llength $pp] == 0} { return "NOTFOUND" }
  set so [get_sites -quiet -of_objects [lindex $pp 0]]
  if {[llength $so] == 0} { return "?" }
  set slr "?"
  catch {set slr [get_property NAME [get_slrs -quiet -of_objects [lindex $so 0]]]}
  return $slr
}
set q0_lanes {}
foreach p {N9 N4 M7 M2 L9 L4 K7 K2} { lappend q0_lanes [quadof $p] }
set q1_lanes {}
foreach p {U9 U4 T7 T2 R9 R4 P7 P2} { lappend q1_lanes [quadof $p] }
set qpcie {}
foreach p {AF2 AG4 AH2 AJ4 AK2 AL4 AM2 AN4} { lappend qpcie [quadof $p] }

puts "I: QSFP0 lane quads      = [lsort -unique $q0_lanes]   (refclk K11 quad = [quadof K11])"
puts "I: QSFP1 lane quads      = [lsort -unique $q1_lanes]   (refclk P11 quad = [quadof P11])"
puts "I: PCIe x8 lane quads    = [lsort -unique $qpcie]      (refclk AM11 quad = [quadof AM11])"
puts "I: MGT_SI570_CLOCK0 M11 quad = [quadof M11] ; MGT_SI570_CLOCK1 T11 quad = [quadof T11]"
puts "I: SLR: QSFP0 lane N9 = [slrof N9] ; QSFP1 lane U9 = [slrof U9] ; PCIe lane AF2 = [slrof AF2] ; PCIe refclk AM11 = [slrof AM11]"

set all_qsfp [lsort -unique [concat $q0_lanes $q1_lanes [quadof K11] [quadof P11] [quadof M11] [quadof T11]]]
set all_pcie [lsort -unique [concat $qpcie [quadof AM11]]]
puts "I: QSFP-side quads (incl refclks) = $all_qsfp"
puts "I: PCIe-side quads (incl refclk)  = $all_pcie"
set clash {}
foreach q $all_qsfp { if {[lsearch -exact $all_pcie $q] >= 0} { lappend clash $q } }
if {[llength $clash]} {
  puts "I: VERDICT = COLLISION -- QSFP and PCIe share quad(s): $clash"
} else {
  puts "I: VERDICT = NO COLLISION -- QSFP quads $all_qsfp are disjoint from PCIe quads $all_pcie"
}
if {[lsearch -exact $all_qsfp 227] >= 0} {
  puts "I: VERDICT-227 = YES, a QSFP cage lands on GTY_Quad_227 (the XDMA quad)"
} else {
  puts "I: VERDICT-227 = NO, neither QSFP cage touches GTY_Quad_227 (the XDMA quad)"
}
puts "\n### gty_sites.tcl DONE"
exit 0
