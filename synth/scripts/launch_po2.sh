#!/bin/bash
# launch_po2.sh <src_build> <directive>... — full-recipe re-impl (both phys_opt
# stages) per placer directive, fresh out dir each, run in parallel.
set -euo pipefail
SRC_NAME=${1:?usage: [TAG=po2] launch_po2.sh <src_build> <directive>...}; shift
[ $# -ge 1 ] || { echo "FATAL: need a directive" >&2; exit 1; }
TAG=${TAG:-po2}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
SRC_DIR="$REPO_ROOT/synth/out_${SRC_NAME}"
[ -d "$SRC_DIR/proj" ] || { echo "FATAL: $SRC_DIR/proj not found" >&2; exit 1; }
for D in "$@"; do
    [ -d "$REPO_ROOT/synth/out_${SRC_NAME}_${TAG}_${D}" ] && { echo "FATAL: out_${SRC_NAME}_${TAG}_${D} exists — never overwritten" >&2; exit 1; }
done
set +u; source /home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh; set -u
for D in "$@"; do
    OUT="$REPO_ROOT/synth/out_${SRC_NAME}_${TAG}_${D}"
    # NB: rsync, NOT `cp -a`. coreutils cp uses copy_file_range(), which this
    # NFS mount offloads server-side and can hang indefinitely (observed
    # 2026-08-15: 62 min elapsed, 3.7 MB copied, stuck in handle_async_copy).
    # rsync does plain read/write and is unaffected.
    mkdir -p "$OUT/proj"; rsync -a "$SRC_DIR/proj/" "$OUT/proj/"
    # XDC=<path> adds an implementation-only constraint file (the floorplan
    # campaign uses this); unset means the plain full recipe.
    ( cd "$OUT"; vivado -mode batch -nojournal -log fullimpl.log \
        -source "$SCRIPT_DIR/full_impl.tcl" \
        -tclargs "$OUT/proj/stage1.xpr" "$D" ${XDC:-} > fullimpl_run.out 2>&1 ) &
done
wait
echo "=== ${TAG} done: ${SRC_NAME} $* ==="
for D in "$@"; do
    grep -h '^TIMING:' "$REPO_ROOT/synth/out_${SRC_NAME}_${TAG}_${D}/fullimpl.log" || echo "NO TIMING LINE: $D"
done
