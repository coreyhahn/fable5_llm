#!/bin/bash
# s5_finish_and_census.sh — complete each S5 placement run's report set from its
# own post_place.dcp, and take the family census.  Run ON SNOKE.
#
#   bash evidence/qwen9b/s5/s5_finish_and_census.sh <finish|family> <variant> ...
#
# TWO SCRIPTS, TWO INSTRUMENTS:
#   finish -> synth/exp_uram/scripts/finish_reports.tcl (Task 13's, UNMODIFIED).
#             It is what produces the KV write fan-out report in full, the conv
#             memory paths, and the KV/conv per-SLR breakdown that exp_ooc.tcl
#             does not emit.  Its `*g_kv*` / `*g_cv*` filters match the S2 slot
#             names (`g_kvslot`, `g_cvslot`) unchanged.
#   family -> evidence/qwen9b/s5/s5_family_census.tcl (S5's copy, new families).
#
# Output goes to <out_dir>/finish_run.log and <out_dir>/family_run.log, the two
# names synth/exp_uram/scripts/collect_evidence.sh carries into evidence.
# The three variants run CONCURRENTLY; each opens its own checkpoint.
set -uo pipefail
MODE=${1:?usage: s5_finish_and_census.sh <finish|family> <variant> ...}
shift
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)

case "$MODE" in
  finish) TCL="$REPO_ROOT/synth/exp_uram/scripts/finish_reports.tcl"; OUT=finish_run ;;
  family) TCL="$SCRIPT_DIR/s5_family_census.tcl";                     OUT=family_run ;;
  *) echo "FATAL: mode must be finish or family" >&2; exit 2 ;;
esac
echo "S5FC_MODE: $MODE"
echo "S5FC_TCL:  $TCL"

set +u
source /home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh
set -u

pids=()
for V in "$@"; do
    D="$REPO_ROOT/synth/out_exp_uram_$V"
    if [ ! -f "$D/post_place.dcp" ]; then echo "S5FC_SKIP $V (no post_place.dcp)"; continue; fi
    if [ -f "$D/$OUT.log" ]; then echo "S5FC_REFUSE $V ($OUT.log exists — never re-run in place)"; continue; fi
    echo "S5FC_LAUNCH $V -> $D/$OUT.log"
    ( vivado -mode batch -nojournal -log "$D/${OUT}_vivado.log" -source "$TCL" \
        -tclargs "$D" > "$D/$OUT.log" 2>&1 ) &
    pids+=($!)
done
rc=0
for p in "${pids[@]:-}"; do [ -n "$p" ] && { wait "$p" || rc=1; }; done
for V in "$@"; do
    D="$REPO_ROOT/synth/out_exp_uram_$V"
    [ -f "$D/$OUT.log" ] || continue
    echo "=== $V $OUT markers ==="
    grep -E "^(FIN_|FAM_)" "$D/$OUT.log" || echo "  (none)"
done
echo "S5FC_RC: $rc"
exit $rc
