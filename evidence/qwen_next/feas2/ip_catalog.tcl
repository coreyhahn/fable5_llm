# ip_catalog.tcl -- Qwen3.5-next TWO-BOARD feasibility study, step f03.
# READ-ONLY IP-catalog + device query on xcvu9p-fsgd2104-2L-e.  No IP created,
# no project on disk, no build.
# Q2: which link IPs exist on THIS install, at what version, and what does the
#     tool itself say about their LICENCE?  Plus the CMACE4 hard-block census.

set PART xcvu9p-fsgd2104-2L-e
puts "### PART = $PART"
puts "### Vivado = [version -short]"
puts "### XILINX_VIVADO = $::env(XILINX_VIVADO)"

create_project -in_memory -part $PART
puts "### create_project -in_memory OK; part = [get_property PART [current_project]]"
# f03 FIX (2026-09-15): the first run (f03_ip_catalog.log) returned 0 CMAC/ILKN/
# PCIE sites because get_sites needs a LINKED design, not just an in-memory
# project.  gty_sites.tcl did link_design and its GTY site census worked.
if {[catch {link_design -part $PART} msg]} {
  puts "### link_design FAILED: $msg"
} else {
  puts "### link_design OK -- device model loaded, get_sites is now valid"
}

# ---------------------------------------------------------------------------
puts "\n===== SECTION A: licence-related Tcl commands that exist in this build ====="
puts "A: info commands *license* = [lsort [info commands *license*]]"
puts "A: info commands *License* = [lsort [info commands *License*]]"
foreach c {get_license_status report_license_status xilinx::get_license_status} {
  if {[llength [info commands $c]]} {
    puts "A: $c EXISTS -> [catch {puts [eval $c]} m]; msg=$m"
  } else {
    puts "A: $c does NOT exist in this build"
  }
}

# ---------------------------------------------------------------------------
puts "\n===== SECTION B: FULL report_property on one cmac_usplus ipdef (name discovery) ====="
set cm [get_ipdefs -quiet *cmac_usplus*]
puts "B: get_ipdefs *cmac_usplus* -> [llength $cm] hit(s): $cm"
if {[llength $cm]} {
  set c0 [lindex $cm 0]
  puts "B: list_property = [join [lsort [list_property $c0]] {, }]"
  puts "B: --- report_property -all $c0 ---"
  if {[catch {report_property -all $c0} msg]} { puts "B: report_property FAILED: $msg" }
} else {
  puts "B: NO cmac_usplus ipdef found in the catalog"
}

# ---------------------------------------------------------------------------
proc dumpip {label pattern} {
  puts "\n--- $label : get_ipdefs -quiet $pattern ---"
  set ips [get_ipdefs -quiet $pattern]
  puts "$label: hits = [llength $ips]"
  foreach ip [lsort $ips] {
    puts "$label: IPDEF $ip"
    foreach pr [lsort [list_property $ip]] {
      set v "<err>"
      if {[catch {set v [get_property $pr $ip]}]} { set v "<unreadable>" }
      # keep long property values on one line, truncated, so the log stays greppable
      if {[string length $v] > 300} { set v "[string range $v 0 299]...<truncated>" }
      puts [format "%s:    %-28s = %s" $label $pr $v]
    }
  }
}

puts "\n===== SECTION C: the four link IPs, every property the tool exposes ====="
dumpip AURORA64  *aurora_64b66b*
dumpip AURORA8   *aurora_8b10b*
dumpip CMAC      *cmac_usplus*
dumpip XXV       *xxv_ethernet*

puts "\n===== SECTION D: broader sweeps (catch alternate names) ====="
foreach {lbl pat} {AURORA_ANY *aurora* CMAC_ANY *cmac* ETH_ANY *ethernet* ILKN_ANY *interlaken*} {
  set ips [get_ipdefs -quiet $pat]
  puts "D: $lbl ($pat) -> [llength $ips]"
  foreach ip [lsort $ips] {
    set vlnv "?" ; set disp "?" ; set stat "?"
    catch {set vlnv [get_property VLNV $ip]}
    catch {set disp [get_property DISPLAY_NAME $ip]}
    catch {set stat [get_property STATUS $ip]}
    puts [format "D:   %-52s VLNV=%-52s STATUS=%-10s NAME=%s" $ip $vlnv $stat $disp]
  }
}

# ---------------------------------------------------------------------------
puts "\n===== SECTION E: licence status per IP, via every plausible route ====="
foreach pat {*aurora_64b66b* *aurora_8b10b* *cmac_usplus* *xxv_ethernet*} {
  set ips [get_ipdefs -quiet $pat]
  foreach ip [lsort $ips] {
    puts "E: ==== $ip ===="
    foreach pr {LICENSE LICENSE_KEY LICENSED IS_LICENSED LICENSE_STATUS ORDER_TYPE PURCHASE STATUS SUPPORTED_FAMILIES UPGRADE_VERSIONS} {
      if {[catch {set v [get_property $pr $ip]} m]} {
        puts "E:   $pr -> NO SUCH PROPERTY ($m)"
      } else {
        if {[string length $v] > 300} { set v "[string range $v 0 299]...<truncated>" }
        puts "E:   $pr = $v"
      }
    }
    # the licence feature name, if the catalog exposes it via the XML
    foreach pr {XML_FILE_NAME REPOSITORY} {
      if {![catch {set v [get_property $pr $ip]}]} { puts "E:   $pr = $v" }
    }
  }
}

# ---------------------------------------------------------------------------
puts "\n===== SECTION F: licence feature names declared in the IP component XML ====="
# Defensible, tool-sourced: read the component.xml the catalog itself points at
# and print any <spirit:...license...> / vendorExtensions licence lines.
foreach pat {*aurora_64b66b* *cmac_usplus* *xxv_ethernet* *aurora_8b10b*} {
  foreach ip [lsort [get_ipdefs -quiet $pat]] {
    set xf ""
    catch {set xf [get_property XML_FILE_NAME $ip]}
    puts "F: $ip xml=$xf"
    if {$xf ne "" && [file exists $xf]} {
      set fh [open $xf r]
      set n 0
      while {[gets $fh line] >= 0} {
        incr n
        if {[string match -nocase {*licens*} $line] || [string match -nocase {*core_license*} $line]} {
          puts "F:   xml:$n [string trim $line]"
        }
      }
      close $fh
    } else {
      puts "F:   (xml path not readable from the catalog)"
    }
  }
}

# ---------------------------------------------------------------------------
puts "\n===== SECTION G: CMACE4 / ILKNE4 hard-block census on $PART ====="
puts "G: all distinct SITE_TYPEs containing E4 (so the real CMAC type name is tool-sourced):"
set types {}
foreach s2 [get_sites -quiet] {
  set t ""
  catch {set t [get_property SITE_TYPE $s2]}
  if {$t ne "" && [lsearch -exact $types $t] < 0} { lappend types $t }
}
puts "G: distinct SITE_TYPE count = [llength $types]"
puts "G: SITE_TYPEs = [lsort $types]"
foreach {lbl filt} {CMAC {SITE_TYPE =~ CMAC*} ILKN {SITE_TYPE =~ ILKN*} PCIE {SITE_TYPE =~ PCIE*}} {
  set sites [get_sites -quiet -filter $filt]
  puts "G: $lbl site count = [llength $sites]"
  foreach s [lsort $sites] {
    set st "?" ; set cr "?" ; set slr "?"
    catch {set st [get_property SITE_TYPE $s]}
    catch {set cr [get_property CLOCK_REGION $s]}
    catch {set slr [get_property NAME [get_slrs -quiet -of_objects $s]]}
    puts [format "G:   %-8s %-24s type=%-14s clkreg=%-7s slr=%s" $lbl $s $st $cr $slr]
  }
}

puts "\n===== SECTION H: can the tool say which GTY quad feeds each CMACE4? ====="
set cmacs [get_sites -quiet -filter {SITE_TYPE =~ CMAC*}]
if {[llength $cmacs]} {
  set c0 [lindex $cmacs 0]
  puts "H: list_property of [lindex $cmacs 0] = [join [lsort [list_property $c0]] {, }]"
  puts "H: --- report_property -all $c0 ---"
  catch {report_property -all $c0}
  puts "H: get_sites -of_objects <tile of cmac>:"
  catch {puts "H:   TILE = [get_tiles -quiet -of_objects $c0]"}
  puts "H: NOTE: if no property names a GTY quad, the quad<->CMACE4 pairing is"
  puts "H: NOT derivable from the device model here; PG203 / UG578 is the source."
} else {
  puts "H: no CMAC sites, nothing to probe"
}


# ---------------------------------------------------------------------------
puts "\n===== SECTION I: is the required licence key actually INSTALLED here? ====="
# There is no get_license_status Tcl command in this build (SECTION A), so the
# only tool-independent evidence is the licence file the tool is pointed at.
# We print ONLY feature names + expiry, never the signature lines.
foreach v {XILINXD_LICENSE_FILE LM_LICENSE_FILE XILINX_LICENSE_FILE} {
  if {[info exists ::env($v)]} { puts "I: env $v = $::env($v)" } else { puts "I: env $v = <unset>" }
}
set cands {}
foreach v {XILINXD_LICENSE_FILE LM_LICENSE_FILE XILINX_LICENSE_FILE} {
  if {[info exists ::env($v)]} { foreach tok [split $::env($v) ":;"] { lappend cands $tok } }
}
# f03b FIX (2026-09-15): the f03b run looked only at ~/.Xilinx/Xilinx.lic and
# reported "no licence file".  This host keeps its keys under other names in
# ~/.Xilinx (Xilinx_valid_aug2026.lic etc), which is where Vivado scans.
foreach g [lsort [glob -nocomplain [file join $::env(HOME) .Xilinx *.lic]]] { lappend cands $g }
puts "I: ~/.Xilinx/*.lic glob -> [llength [glob -nocomplain [file join $::env(HOME) .Xilinx *.lic]]] file(s)"
set found 0
foreach f [lsort -unique $cands] {
  if {$f eq ""} { continue }
  if {[file isdirectory $f]} {
    foreach g [glob -nocomplain [file join $f *.lic]] { lappend cands $g }
    continue
  }
  if {![file exists $f]} { puts "I: licence path $f -> DOES NOT EXIST"; continue }
  set found 1
  puts "I: licence file $f -> EXISTS, features:"
  set fh [open $f r]
  set n 0
  while {[gets $fh line] >= 0} {
    incr n
    set line [string trim $line]
    if {[string match -nocase {INCREMENT *} $line] || [string match -nocase {FEATURE *} $line]} {
      set parts [split $line]
      puts "I:   $f:$n  feature=[lindex $parts 1]  vendor=[lindex $parts 2]  ver=[lindex $parts 3]  exp=[lindex $parts 4]"
    }
  }
  close $fh
}
if {!$found} { puts "I: NO licence file found -> licence INSTALL STATUS UNDETERMINED from this host" }

puts "\n===== SECTION J: required key vs INSTALLED feature, per IP ====="
# collect every feature name present in every readable licence file
set have {}
foreach f [lsort -unique $cands] {
  if {$f eq "" || ![file exists $f] || [file isdirectory $f]} { continue }
  set fh [open $f r]
  while {[gets $fh line] >= 0} {
    set line [string trim $line]
    if {[string match -nocase {INCREMENT *} $line] || [string match -nocase {FEATURE *} $line]} {
      lappend have [lindex [split $line] 1]
    }
  }
  close $fh
}
set have [lsort -unique $have]
puts "J: installed feature names = $have"
foreach pat {*aurora_64b66b* *aurora_8b10b* *cmac_usplus* *xxv_ethernet*} {
  foreach ip [lsort [get_ipdefs -quiet $pat]] {
    set req 0 ; set keys {}
    catch {set req [get_property REQUIRES_LICENSE $ip]}
    catch {set keys [get_property LICENSE_KEYS $ip]}
    if {!$req} {
      puts "J: $ip  REQUIRES_LICENSE=0 -> NO KEY NEEDED (included)"
      continue
    }
    set missing {} ; set present {}
    foreach k $keys {
      set feat [lindex [split $k @] 0]
      if {[lsearch -exact $have $feat] >= 0} { lappend present $feat } else { lappend missing $feat }
    }
    puts "J: $ip  REQUIRES_LICENSE=1"
    puts "J:    keys needed  = $keys"
    puts "J:    PRESENT here = $present"
    puts "J:    MISSING here = $missing"
  }
}

puts "I: NOTE: REQUIRES_LICENSE=1 means the IP needs a key to generate/bitstream."
puts "I: Whether that key is INSTALLED is answered only by the features listed above."

puts "\n### ip_catalog.tcl DONE"
exit 0
