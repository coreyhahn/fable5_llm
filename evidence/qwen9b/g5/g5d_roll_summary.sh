#!/usr/bin/env bash
# g5d_roll_summary.sh <timing_summary.rpt> <label> <headline...> — copy the
# three sections of a roll's OWN timing_summary.rpt that this gate document
# quotes, into one file, in one shape, for every roll.
#
# WHY A SCRIPT AND NOT A `sed` PER ROLL.  Task 14-B scores N implementation
# rolls against one another and `evidence/qwen9b/g5/g5d_superlatives.py` reads
# the result back to rank them.  A per-roll hand-extraction is a per-roll
# chance to quote a different column, and the checker would then be ranking
# numbers that do not mean the same thing.  This writes:
#
#   * the Design Timing Summary data row — WNS / TNS / TNS-failing-EP /
#     TNS-total / WHS / THS / THS-failing-EP / THS-total / WPWS / ... — which
#     is the row g5d_superlatives.py parses BY SHAPE;
#   * the Clock Summary rows for the six named clocks, which carry each
#     clock's PERIOD and FREQUENCY (the two MIG UI clocks are 3.332 ns /
#     300 MHz and this document names them as such);
#   * the Intra Clock Table rows for the same six, which carry the per-clock
#     WNS / TNS / failing endpoints / WHS / failing hold.
#
# The six are matched by NAME at the start of the line, so the ~20 auto-derived
# GT/BSCAN clocks Vivado also lists are excluded without excluding anything
# that can own the design's WNS.  A clock that stops matching would show up as
# a missing row, not as a silently shorter table.
#
# Read-only with respect to the roll: it only reads the report.
#
#   bash g5d_roll_summary.sh <rpt> <label> ["headline text"] > <nnn>_t14b_roll_<label>.txt
set -u
RPT=${1:?usage: g5d_roll_summary.sh <timing_summary.rpt> <label> [headline]}
LBL=${2:?need a label}
HEAD=${3:-}
[ -r "$RPT" ] || { echo "FATAL: cannot read $RPT" >&2; exit 1; }

CLOCKS='mmcm_clkout0 mmcm_clkout0_1 mmcm_clkout0_2 mmcm_clkout0_3 pipe_clk xdma_0_axi_aclk'

echo "# roll: $LBL"
echo "# source: $RPT (out dirs are gitignored)"
echo "# mtime : $(stat -c %y "$RPT")"
[ -n "$HEAD" ] && echo "# $HEAD"
echo
echo "=== Design Timing Summary ==="
# The data row is the first non-blank line after the COLUMN ruler.  The ruler
# is matched as two-or-more dash groups (`    -------      -------  ...`), not
# as one: the banner underline three lines above it is a single unbroken dash
# run, and matching that returns the COLUMN HEADER instead of the numbers.
awk '/^\| Design Timing Summary/{f=1} f&&/^ *-+ +-+ /{r=1;next} r&&NF{print;exit}' "$RPT"
echo
echo "=== Clock Summary (the six named clocks: name, waveform, period, frequency) ==="
awk -v cl="$CLOCKS" '
  BEGIN{n=split(cl,a," "); for(i=1;i<=n;i++) want[a[i]]=1}
  /^\| Clock Summary/{f=1}
  f && $1 in want && !seen[$1]++ {print}
' "$RPT"
echo
echo "=== Intra Clock Table (the same six) ==="
awk -v cl="$CLOCKS" '
  BEGIN{n=split(cl,a," "); for(i=1;i<=n;i++) want[a[i]]=1}
  /^\| Intra Clock Table/{f=1}
  f && $1 in want && !seen[$1]++ {print}
' "$RPT"
