#!/bin/bash
# run_g4b_census.sh — G4b Step 3: build and run the layer-term cycle census.
#
#   ./run_g4b_census.sh <cfg> <dn_pipe> <p2wait> <script.txt> [stopm] [emb] [embn] [wd_ms]
#
#     <cfg>      short config tag; picks the obj_dir and the binary name, so
#                the three configurations never share one (house rule: one
#                obj_dir per TB, and NEVER two hosts on one obj_dir).
#     <dn_pipe>  layer_chan DN_PIPE   (2 = shipped), passed as -GP_DN_PIPE.
#     <p2wait>   -1 = the SHIPPING rtl/layer_chan.sv, untouched.
#                0  = option (ii): a SCRATCH COPY of rtl/layer_chan.sv with
#                     the one localparam forced, built into its own obj_dir.
#     [stopm]    stop just before the n-th M record; 0 = replay to Q
#
# WHY A PATCHED COPY AND NOT A PARAMETER.  DN_P2WAIT is a layer_chan
# localparam (rtl/layer_chan.sv:337) derived from DN_RLAT.  Verilator's -G
# reaches the TOP module only, and `defparam dut.u_dn.P2_WAIT = 0` is
# rejected by Verilator 5.020 ("defparam with more than one dot": UNSUPPORTED
# -- measured, not assumed).  Promoting it to a module parameter WAS built and
# then REVERTED: inserting it moves every line below, and
# `o3_cite_drift.py --base f81902b --edited rtl/layer_chan.sv --plan` scores
# that at 221 citations to repair across 20 documents with 7 collateral
# rewrites -- the tool's own verdict is UNSAFE.  A scratch copy costs nothing,
# keeps rtl/ byte-identical to HEAD, and is auditable: the diff is printed and
# this script REFUSES if it is not exactly the one line.
#
# The two runs therefore differ in one localparam and in nothing else: same
# stream, same host, same tree, same TB source.
#
# Run ON SNOKE (user rule 2026-08-09: heavy Verilator sims on snoke).
# =====================  SUPERSEDED 2026-09-10 — DO NOT RUN  ==================
# Task 12 wrote this against the PRE-SPILL layer.  The state-spill work (S1-S5,
# spec 0b A1/A2) added the SLD/SST DMA lane, the slot caches and the SDMA
# counters, and the census that describes the SHIPPING layer is
#
#     evidence/qwen9b/s4/run_s4_census.sh
#
# whose output has columns this one does not (`excess` per opcode, `SLD+SST`
# and `sdma_cyc` per step) and whose header no longer carries `DN_PIPE=`,
# because S2 retired the parameter.  The numbers this script would produce are
# a measurement of a layer that is not on the bitstream.
#
# It was left EXECUTABLE and UNMARKED, which is the whole defect (#122, triage
# (b)17): the next person reaching for "the census runner" got the wrong one
# and no signal at all.  It is kept in the tree because `evidence/qwen9b/g4/
# G4B_STRUCT.md` cites it by line as the instrument its numbers came from --
# reading it is right, running it is not.
#
# To re-derive a G4b number from the pre-spill layer deliberately, check out
# the tree it was written for and run it there.
cat >&2 <<'SUPERSEDED_BANNER'
SUPERSEDED 2026-09-10: run_g4b_census.sh was written for the PRE-SPILL layer
  (Task 12, before spec 0b A1/A2 added the SLD/SST DMA lane and the slot
  caches).  It measures a layer that is not on the bitstream.
  USE INSTEAD: evidence/qwen9b/s4/run_s4_census.sh
  (see evidence/qwen9b/s4/S4_REPLAY.md; #122, triage (b)17)
REFUSING to run.
SUPERSEDED_BANNER
exit 2
# ============================================================================
set -euo pipefail

CFG=${1:?usage: run_g4b_census.sh <cfg> <dn_pipe> <p2wait> <script.txt> [stopm] [emb] [embn] [wd_ms]}
PIPE=${2:?}
P2W=${3:?}
SCRIPT=${4:?}
STOPM=${5:-0}
EMB=${6:-}
EMBN=${7:-4096}
WDMS=${8:-2000000}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
TB="$REPO_ROOT/tb"
RTL="$REPO_ROOT/rtl"
MDIR="obj_dir_tb_layer_census_${CFG}"
BIN="tb_layer_census_${CFG}"

# rtl/ must be clean: every census number is claimed against HEAD's RTL.
if ! git -C "$REPO_ROOT" diff --quiet -- rtl/; then
    echo "FATAL: rtl/ is dirty — the census is claimed against HEAD's RTL" >&2
    git -C "$REPO_ROOT" diff --stat -- rtl/ >&2
    exit 2
fi

LC="$RTL/layer_chan.sv"
if [ "$P2W" = "0" ]; then
    PDIR="$REPO_ROOT/tb/obj_dir_p2wait0_$CFG"
    rm -rf "$PDIR"; mkdir -p "$PDIR"
    sed 's|^    localparam int DN_P2WAIT = (DN_RLAT > 2) ? 1 : 0;$|    localparam int DN_P2WAIT = 0;   // G4b option (ii), SCRATCH COPY|' \
        "$LC" > "$PDIR/layer_chan.sv"
    echo "=== option (ii) scratch copy: $PDIR/layer_chan.sv ==="
    diff "$LC" "$PDIR/layer_chan.sv" || true
    NDIFF=$(diff "$LC" "$PDIR/layer_chan.sv" | grep -c '^[<>]' || true)
    if [ "$NDIFF" != "2" ]; then
        echo "FATAL: the scratch copy differs from rtl/layer_chan.sv in $NDIFF lines, not the one substitution (2 diff lines)" >&2
        exit 2
    fi
    grep -n "DN_P2WAIT" "$PDIR/layer_chan.sv"
    LC="$PDIR/layer_chan.sv"
fi

LAYER_RTL="$RTL/fx_pkg.sv $RTL/fx_rsqrt.sv $RTL/fx_recip.sv $RTL/fx_silu.sv \
  $RTL/vecnorm_unit.sv $RTL/rope_unit.sv $RTL/conv4_silu.sv $RTL/dn_step.sv \
  $RTL/attn_core.sv $RTL/gate_unit.sv $RTL/vec_alu.sv $LC"

cd "$TB"
echo "=== build $CFG (DN_PIPE=$PIPE, p2wait arg $P2W, layer_chan from $LC) into $MDIR ==="
# shellcheck disable=SC2086
verilator --binary --timing -j "${JOBS:-8}" -Wall \
    --Mdir "$MDIR" -o "$BIN" \
    -GP_DN_PIPE="$PIPE" \
    --top-module tb_layer_census \
    $LAYER_RTL "$SCRIPT_DIR/tb_layer_census.sv"

CENSUS="$SCRIPT_DIR/census_${CFG}.txt"
ARGS=(+script="$SCRIPT" +census="$CENSUS" +watchdog_ms="$WDMS")
[ "$STOPM" != "0" ] && ARGS+=(+stopm="$STOPM")
[ -n "$EMB" ] && ARGS+=(+emb="$EMB" +embn="$EMBN")

echo "=== run $CFG: ${ARGS[*]} ==="
T0=$(date +%s)
# `RC=$?` on the next line would be UNREACHABLE under `set -e`: a
# non-zero exit aborts the script first, so the rc= line below could
# only ever print 0 and the wall clock would be lost on a failure.
# `|| RC=$?` suppresses errexit for exactly this command, so both are
# reported honestly and the script still exits with the real code.
RC=0
"./$MDIR/$BIN" "${ARGS[@]}" || RC=$?
T1=$(date +%s)
echo "=== census $CFG rc=$RC wall=$((T1 - T0)) s, table in $CENSUS ==="
exit $RC
