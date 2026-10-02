#!/usr/bin/env bash
# run_s4_census.sh — build and run the layer-term cycle census on the
# DDR-state design (S4 Step 3).
#
#   bash evidence/qwen9b/s4/run_s4_census.sh <cfg> <script.txt> [stopm] [emb] [embn] [wd_ms]
#
#     <cfg>       short tag; picks the obj_dir and the binary name, so this
#                 run never shares one with Task 12's (house rule: one
#                 obj_dir per TB, and never two hosts on one obj_dir).
#     <script.txt> the artifact's command script, relative to tb/.  Its
#                 prefix (the path with `.txt` removed) also names the
#                 state image `<prefix>.state.bin` and is passed as +state=.
#     [stopm]     stop just before the n-th M record; 0 = replay to Q.
#
#   S4 FIX ROUND 1 (review I4): two environment knobs.
#
#     LAT=<n>     the modelled read latency of the state window
#                 (`-GP_LAT`, tb/seq_mem_file.sv).  Default 8, the latency
#                 the shipped census measured; 40 is what tb/tb_seq_chip.sv:436
#                 gives the SAME window in the chip replay (WLAT,
#                 tb/tb_seq_chip.sv:69), so LAT=40 is the like-for-like
#                 companion of the chip number.
#     NODRAIN=1   replay with the SEQUENCER's back-pressure rule instead of
#                 the census's drain, so the F1/F2 fence holds become
#                 reachable and are counted.  Per-command cost attribution is
#                 suppressed by the TB in that mode; per-step totals and the
#                 hold tables are printed.
#
#   THE LATENCY IS A BUILD PARAMETER, so the obj_dir CARRIES IT: two LATs are
#   two binaries and two build directories, and the house rule (one obj_dir
#   per build, never two builds or two hosts in one) is kept mechanically
#   rather than by the caller remembering to vary <cfg>.
#
# WHY THIS EXISTS AND IS NOT `evidence/qwen9b/g4/run_g4b_census.sh`.
# Task 12's runner cannot run this census, for two reasons that are both
# about what S2/S3 changed underneath it, and it is outside S4's commit
# block so S4 does not edit it:
#
#   1. it never passes `+state=`.  The layer's state lives in DDR now, so
#      the census TB has a `tb/seq_mem_file.sv` window behind the layer's
#      AXI4 master and it must be loaded from the artifact's own
#      `<prefix>.state.bin` -- without it the CONV taps `seed_conv` wrote
#      are simply not there and the bit-exact replay cannot pass;
#   2. its `p2wait 0` arm seds a `localparam int DN_P2WAIT` that S2 RETIRED
#      (rtl/layer_chan.sv:377), so that arm is dead.  S4 measures the
#      SHIPPING configuration only, which is the arm that has no sed.
#
# Everything else is Task 12's runner, deliberately: the same verilator
# flags, the same `rtl/` cleanliness guard (every census number is claimed
# against HEAD's RTL), the same one-obj_dir-per-cfg rule, the same honest
# `|| RC=$?` so a failure still reports its wall clock.
#
# The census TB reaches `rtl/state_dma.sv` and `tb/seq_mem_file.sv` by
# `include` (see the note at its u_smem instance), so the file list below is
# the SAME list Task 12's runner uses and stays comparable to it.
#
# Run ON SNOKE (user rule 2026-08-09: heavy Verilator sims on snoke).
set -euo pipefail

CFG=${1:?usage: run_s4_census.sh <cfg> <script.txt> [stopm] [emb] [embn] [wd_ms]}
SCRIPT=${2:?}
STOPM=${3:-0}
EMB=${4:-}
EMBN=${5:-4096}
WDMS=${6:-2000000}
LAT=${LAT:-8}
NODRAIN=${NODRAIN:-0}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
TB="$REPO_ROOT/tb"
RTL="$REPO_ROOT/rtl"
CTB="$REPO_ROOT/evidence/qwen9b/g4/tb_layer_census.sv"
MDIR="obj_dir_tb_layer_census_${CFG}_lat${LAT}"
BIN="tb_layer_census_${CFG}_lat${LAT}"
STATE=${SCRIPT%.txt}

# rtl/ must be clean: every census number is claimed against HEAD's RTL.
if ! git -C "$REPO_ROOT" diff --quiet -- rtl/; then
    echo "FATAL: rtl/ is dirty — the census is claimed against HEAD's RTL" >&2
    git -C "$REPO_ROOT" diff --stat -- rtl/ >&2
    exit 2
fi

LAYER_RTL="$RTL/fx_pkg.sv $RTL/fx_rsqrt.sv $RTL/fx_recip.sv $RTL/fx_silu.sv \
  $RTL/vecnorm_unit.sv $RTL/rope_unit.sv $RTL/conv4_silu.sv $RTL/dn_step.sv \
  $RTL/attn_core.sv $RTL/gate_unit.sv $RTL/vec_alu.sv $RTL/layer_chan.sv"

cd "$TB"
[ -f "$STATE.state.bin" ] || {
    echo "FATAL: $TB/$STATE.state.bin missing — the state image is not optional" >&2
    exit 2; }
echo "=== build $CFG into $MDIR (layer_chan from $RTL/layer_chan.sv), LAT=$LAT ==="
# shellcheck disable=SC2086
verilator --binary --timing -j "${JOBS:-8}" -Wall \
    --Mdir "$MDIR" -o "$BIN" \
    -GP_LAT="$LAT" \
    --top-module tb_layer_census \
    $LAYER_RTL "$CTB"

CENSUS="$SCRIPT_DIR/census_${CFG}.txt"
ARGS=(+script="$SCRIPT" +state="$STATE" +census="$CENSUS" +watchdog_ms="$WDMS")
[ "$STOPM" != "0" ] && ARGS+=(+stopm="$STOPM")
[ "$NODRAIN" != "0" ] && ARGS+=(+nodrain=1)
[ -n "$EMB" ] && ARGS+=(+emb="$EMB" +embn="$EMBN")

echo "=== run $CFG: ${ARGS[*]} ==="
T0=$(date +%s)
RC=0
"./$MDIR/$BIN" "${ARGS[@]}" || RC=$?
T1=$(date +%s)
echo "=== census $CFG rc=$RC wall=$((T1 - T0)) s, table in $CENSUS ==="
exit $RC
