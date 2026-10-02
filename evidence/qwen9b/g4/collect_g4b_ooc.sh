#!/bin/bash
# collect_g4b_ooc.sh — carry the load-bearing OOC report sections into
# evidence/qwen9b/g4/.  synth/out_* is gitignored, so a report has to be
# copied here to be committed (same reason Track P's collect_evidence.sh
# exists).
#
#   ./collect_g4b_ooc.sh <tag> [<tag> ...]
set -uo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
EV="$SCRIPT_DIR"

for T in "$@"; do
    D="$REPO_ROOT/synth/out_ooc9b_$T"
    [ -d "$D" ] || { echo "skip $T (no $D)"; continue; }
    echo "=== $T ==="
    # the OOC9B_ marker stream is the run's own headline record
    grep -E "^(=== |host |date |tree |vivado |params |OOC9B_)" "$D/run.log" \
        > "$EV/ooc_${T}_summary.log" 2>/dev/null
    # the whole utilization report (12 KB) — an earlier campaign truncated one
    # and then cited a row past the cut (PLACE_EXP.md 6); do not repeat that.
    [ -f "$D/reports/util_synth.rpt" ] && \
        cp "$D/reports/util_synth.rpt" "$EV/ooc_${T}_util_synth.rpt"
    # AND the HIERARCHICAL one, which ooc_9b.tcl has always written and this
    # collector did not carry.  It is what closes a per-instance question --
    # G4b fix round 1 needed it to attribute the DN_PIPE 0 -> 2 Logic-LUT
    # residual, and a top-N cell census cannot answer that (an instance whose
    # count FALLS never appears in a top-N list at all).
    [ -f "$D/reports/util_synth_hier.rpt" ] && \
        cp "$D/reports/util_synth_hier.rpt" "$EV/ooc_${T}_util_synth_hier.rpt"
    # any Vivado ERROR / CRITICAL WARNING is load-bearing
    grep -E "^(ERROR|CRITICAL WARNING)" "$D/vivado.log" 2>/dev/null | sort -u \
        > "$EV/ooc_${T}_vivado_errors.log"
    [ -s "$EV/ooc_${T}_vivado_errors.log" ] || rm -f "$EV/ooc_${T}_vivado_errors.log"
    ls -la "$EV" | grep "ooc_${T}_" | awk '{print "  " $NF, $5}'
done
