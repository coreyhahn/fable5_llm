#!/bin/bash
# launch_reroll.sh — SUPERSEDED SHIM (2026-08-22, R-c task 5).
#
# Kept so existing invocations and docs keep working, but it no longer runs a
# flow of its own: it delegates to launch_po2.sh.  Two independent defects in
# the old implementation made it unsafe to keep alive
# (evidence/qwen2b/rb/TIMING.md §7 findings 1 and 2):
#
#   1. line 34 used `cp -a` on the ~1.7 GB project.  Coreutils cp uses
#      copy_file_range(), which this NFS mount offloads server-side, and the
#      offload can wedge: observed 2026-08-15 at 62 minutes elapsed / 3.7 MB
#      copied, asleep in handle_async_copy.  A stalled reroll is
#      indistinguishable from a slow one, so this silently burns hours.
#      launch_po2.sh uses `rsync -a` (same copy: 875 MB / 40 s).
#
#   2. reroll_impl.tcl enables NEITHER phys_opt stage.  Measured cost, n=3
#      same-directive pairs: +0.040 … +0.100 ns of WNS left on the table every
#      roll.  The full recipe — place -directive D, post-place phys_opt,
#      route, post-route phys_opt — lives in full_impl.tcl and is now what
#      every roll gets.  The phys_opt-less flow is deliberately NOT reachable
#      from here.
#
# Output dirs are named out_<build>_full_<directive> (override with TAG=...),
# NOT the historical out_<build>_rr_<directive>: the tag names the recipe, and
# the existing _rr_ dirs genuinely are phys_opt-less rolls.  Do not re-use the
# _rr_ tag for a full-recipe roll.
#
# Run ON SNOKE:  ./launch_reroll.sh <build_name> <directive> [<directive>...]
# Detach with:   nohup ./launch_reroll.sh build_035 Explore > log.out 2>&1 &
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
TAG=${TAG:-full}
echo "NOTE: launch_reroll.sh is a shim — running the FULL recipe via launch_po2.sh (TAG=$TAG)." >&2
exec env TAG="$TAG" "$SCRIPT_DIR/launch_po2.sh" "$@"
