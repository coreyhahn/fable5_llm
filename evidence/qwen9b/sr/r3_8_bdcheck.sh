#!/usr/bin/env bash
# r3_8_bdcheck.sh — Task R3-8 Step 4: synth/scripts/create_project.tcl ALONE
# (no synth, no impl, no bitstream) into a NEW scratch out dir on snoke, to
# prove the block design validates with the x-push bus.  New file (not a
# flag on an existing tool): no committed launcher stops after
# create_project — launch_build.sh always goes on to build.tcl.
#   r3_8_bdcheck.sh <out-dir-name> [<reference build out dir>]
# Prints: CREATE_PROJECT_OK, the ERROR / CRITICAL WARNING / WARNING counts,
# the CRITICAL WARNING set against the reference build's create.log
# (default synth/out_build_045_r2, SR14's R2 build) with the out-dir path
# normalised, the 20 XPUSH_NET lines (bits and both ends' clock nets) and
# XPUSH_BUS_OK.  Refuses an existing out dir.  Run ON SNOKE via sr_run.sh.
set -u
NAME=${1:?usage: r3_8_bdcheck.sh <out-dir-name> [ref-out-dir]}
REF=${2:-synth/out_build_045_r2}
ROOT=$(cd "$(dirname "$0")/../../.." && pwd); cd "$ROOT" || exit 1
O=$ROOT/synth/out_$NAME
[ -e "$O" ] && { echo "REFUSING: $O exists (out dirs are never reused)"; exit 2; }
[ -f "$REF/create.log" ] || { echo "no reference $REF/create.log"; exit 2; }
VER=$(git rev-parse --short=8 HEAD)
mkdir -p "$O"
set +u; source /home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh; set -u
echo "BD out $O ; VERSION $VER ; create_project.tcl sha256 $(sha256sum < synth/scripts/create_project.tcl | cut -c1-16)"
( cd "$O" && vivado -mode batch -nojournal -log create.log \
    -source "$ROOT/synth/scripts/create_project.tcl" -tclargs "$O" "$VER" > vivado_stdout.txt 2>&1 )
echo "vivado rc $?"
C=$O/create.log
echo "BD CREATE_PROJECT_OK: $(grep -c '^CREATE_PROJECT_OK' "$C")"
echo "BD create.log ERROR: $(grep -c '^ERROR' "$C")  CRITICAL WARNING: $(grep -c '^CRITICAL WARNING' "$C")  WARNING: $(grep -c '^WARNING' "$C")"
echo "BD reference $REF/create.log ERROR: $(grep -c '^ERROR' "$REF/create.log")  CRITICAL WARNING: $(grep -c '^CRITICAL WARNING' "$REF/create.log")"
norm() { grep "^CRITICAL WARNING" "$1" | sed -e "s#$2#<OUT>#g" | sort; }
if diff <(norm "$C" "$O") <(norm "$REF/create.log" "$ROOT/$REF") > "$O/cw_diff.txt"; then
  echo "BD CRITICAL WARNING set: IDENTICAL to $REF/create.log"
else
  echo "BD CRITICAL WARNING set: DIFFERS from $REF/create.log:"; sed 's/^/BD   /' "$O/cw_diff.txt"
fi
grep '^ERROR' "$C" | sed 's/^/BD   /'
grep -E '^XPUSH_(NET|BUS_OK)' "$C"
echo "BD validate_bd_design calls completed: $(grep -c '^# must {validate_bd_design}' "$C"), save_bd_design: $(grep -c '^# must {save_bd_design}' "$C")"
