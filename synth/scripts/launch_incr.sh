#!/bin/bash
# launch_incr.sh <src_build> <out_build_name> <place_directive> <ref_dcp> <incr_directive> [<xdc>...]
# — one INCREMENTAL full-recipe re-implementation (synth/scripts/incr_impl.tcl)
# of <src_build>'s synthesised project, in a FRESH out dir synth/out_<out_build_name>.
# Isolation as launch_po2.sh: the source proj/ is only READ (rsync out of it);
# the reference dcp is only READ by path. Run ON SNOKE, detached with nohup.
set -euo pipefail
SRC_NAME=${1:?usage: launch_incr.sh <src_build> <out_name> <place_dir> <ref_dcp> <incr_dir> [xdc...]}
OUT_NAME=${2:?}; D=${3:?}; REF=${4:?}; IDIR=${5:?}; shift 5
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
SRC_DIR="$REPO_ROOT/synth/out_${SRC_NAME}"
OUT="$REPO_ROOT/synth/out_${OUT_NAME}"
[ -d "$SRC_DIR/proj" ] || { echo "FATAL: $SRC_DIR/proj not found" >&2; exit 1; }
[ -f "$REF" ] || { echo "FATAL: reference dcp $REF not found" >&2; exit 1; }
[ -e "$OUT" ] && { echo "FATAL: $OUT exists — never overwritten" >&2; exit 1; }
# SR7 fix round 1 (M-3): never copy a proj/ with a run in flight — the copy's
# reset_run kills the source run (evidence/qwen9b/sr/n712_SR7_base_roll_killed.log).
"$SCRIPT_DIR/proj_busy.sh" "$SRC_DIR/proj" || { echo "FATAL: $SRC_DIR/proj has a Vivado run in flight — wait for it to finish (the base build's '=== DONE'), then launch" >&2; exit 1; }
# LAUNCH_INCR_CHECK_ONLY=1: stop after the argument and source checks (no
# rsync, no Vivado) — the no-launch check of the guard.
[ "${LAUNCH_INCR_CHECK_ONLY:-0}" = 1 ] && { echo "CHECK_ONLY: arguments and source OK, nothing launched"; exit 0; }
set +u; source /home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh; set -u
# rsync, NOT cp -a (copy_file_range hangs on this NFS mount; see launch_po2.sh)
mkdir -p "$OUT/proj"; rsync -a "$SRC_DIR/proj/" "$OUT/proj/"
echo "=== rsync done: $(date -Is)"
cd "$OUT"
vivado -mode batch -nojournal -log incrimpl.log -source "$SCRIPT_DIR/incr_impl.tcl" \
    -tclargs "$OUT/proj/stage1.xpr" "$D" "$REF" "$IDIR" "$@" > incrimpl_run.out 2>&1 || true
echo "=== incr done: $OUT_NAME ==="
grep -h '^TIMING:' "$OUT/incrimpl.log" || { echo "NO TIMING LINE"; exit 1; }
grep -q '^BUILD_OK' "$OUT/incrimpl.log" || { echo "NO BUILD_OK"; exit 1; }
