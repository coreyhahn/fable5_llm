#!/bin/bash
# collect_evidence.sh — copy the load-bearing report sections of each variant
# into an evidence directory (synth/out_* is gitignored, so the reports have to
# be carried into evidence to be committed).
#   ./collect_evidence.sh [-d <evidence-dir>] <variant> [<variant> ...]
#
# -d defaults to evidence/qwen_next/place_exp (Track P's directory, so every
# existing invocation in PLACE_EXP.md 6 keeps working byte for byte).  G5a
# passes -d evidence/qwen9b/g5.  The path is REPO-RELATIVE or absolute.
set -uo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
EV_REL="evidence/qwen_next/place_exp"
if [ "${1:-}" = "-d" ]; then EV_REL=$2; shift 2; fi
case "$EV_REL" in /*) EV="$EV_REL" ;; *) EV="$REPO_ROOT/$EV_REL" ;; esac
mkdir -p "$EV"
echo "collect_evidence: out dirs = $REPO_ROOT/synth/out_exp_uram_<variant>, evidence = $EV"

for V in "$@"; do
    D="$REPO_ROOT/synth/out_exp_uram_$V"
    [ -d "$D" ] || { echo "skip $V (no $D)"; continue; }
    echo "=== $V ==="
    # the EXP_ marker stream is the run's own headline record
    # EXTRA_XDC is included from G5a on: exp_ooc.tcl prints the floorplan it
    # was given in full_impl.tcl's marker form, and a summary that omitted it
    # would not say which variant a number belongs to.
    grep -E "^(=== |host |date |tree |vivado |params |extra_xdc |rtl |EXP_|EXTRA_XDC)" "$D/run.log" \
        > "$EV/${V}_summary.log" 2>/dev/null
    # G5a: finish_reports.tcl and family_census.tcl complete / decompose a run
    # from its own post_place.dcp.  Their marker streams are part of the run's
    # record, so they are carried with it.
    for X in finish_run finish_run2 finish_run3 family_run; do
        # provenance header: these are SEPARATE Vivado invocations from the run
        # itself, so they carry their own host/date/tree line rather than
        # inheriting the run's (G5a fix round 1, minor 12).
        if [ -f "$D/$X.log" ]; then
            {
              echo "=== $X for $V, re-derived from $D/post_place.dcp"
              echo "=== host: $(hostname)"
              echo "=== date: $(date -Is)"
              echo "=== tree: $(cd "$REPO_ROOT" && git rev-parse --short HEAD)$(cd "$REPO_ROOT" && git diff --quiet || echo '+dirty')"
              echo "=== dcp:  $(stat -c '%y %s bytes' "$D/post_place.dcp" 2>/dev/null)"
              echo "=== ---"
            } > "$EV/${V}_${X}.log"
        fi
        [ -f "$D/$X.log" ] && grep -E "^(FIN_|FAM_)" "$D/$X.log" \
            >> "$EV/${V}_${X}.log" 2>/dev/null
        [ -s "$EV/${V}_${X}.log" ] || rm -f "$EV/${V}_${X}.log"
    done
    # utilization: keep the CLB / memory / arithmetic / SLR sections only
    for R in util_synth util_placed util_placed_slr; do
        [ -f "$D/reports/$R.rpt" ] && cp "$D/reports/$R.rpt" "$EV/${V}_${R}.rpt"
    done
    # every per-path report this evidence set cites, including the two the
    # DN_PIPE>0 variants add.  An earlier revision omitted the last two and
    # PLACE_EXP.md section 6 promised them -- that gap is what this fixes.
    for R in uram_slr_census dn_bank_mux_paths kv_bank_mux_paths \
             dn_group_return_paths dn_write_fanout_paths kv_write_fanout_paths \
             conv_bram_paths; do
        [ -f "$D/reports/$R.rpt" ] && cp "$D/reports/$R.rpt" "$EV/${V}_${R}.rpt"
    done
    # timing summary: copy it WHOLE (~17 KB / ~325 lines).  The previous
    # 200-line cutoff truncated two lines before the worst-path block that
    # section 3.3 and section 4 quote (v2wide's write-fan-out endpoint is at
    # line 204), so the document cited a decomposition that was not committed.
    if [ -f "$D/reports/timing_summary_placed.rpt" ]; then
        cp "$D/reports/timing_summary_placed.rpt" \
            "$EV/${V}_timing_summary_placed.rpt"
        rm -f "$EV/${V}_timing_summary_placed_head.rpt"
    fi
    # any Vivado ERROR / CRITICAL WARNING is load-bearing when place fails
    grep -E "^(ERROR|CRITICAL WARNING)" "$D/vivado.log" 2>/dev/null | sort -u \
        > "$EV/${V}_vivado_errors.log"
    [ -s "$EV/${V}_vivado_errors.log" ] || rm -f "$EV/${V}_vivado_errors.log"
    ls -la "$EV" | grep "${V}_" | awk '{print "  " $NF, $5}'
done
