#!/bin/bash
# run_g4b_census_control.sh — G4b: the census instrument's RED and GREEN.
#
# A cycle census that could not FAIL would be a stopwatch, not a measurement.
# tb_layer_census keeps tb_layer_chan's bit-exact comparison of every R / E / A
# record, and this fires that half both ways using the binary the shipped
# census already built (no rebuild, no new obj_dir):
#
#   GREEN  layerv2_s1..4 generated at FABLE5_MODEL=9b FABLE5_RS_F=7 — the
#          operating point — must replay bit-exactly and reproduce G3.4's
#          committed tb_layer_chan counts.
#   RED    the SAME seeds generated at FABLE5_RS_F=8 must FAIL, because
#          rtl/conv4_silu.sv:54 bakes the RS_F + CW_F - 12 shift and a script
#          emitted at the wrong residual binary point cannot replay against
#          this RTL.  (A2.5 is unaffected: its rule is never to export
#          FABLE5_RS_F across the byte-lock scripts; this is a generator.)
#
# The RED is expected to exit non-zero.  This script reports PASS only if the
# GREEN passes AND the RED fails.
#
#   ./run_g4b_census_control.sh          # on snoke
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
SUPERSEDED 2026-09-10: run_g4b_census_control.sh was written for the PRE-SPILL layer
  (Task 12, before spec 0b A1/A2 added the SLD/SST DMA lane and the slot
  caches).  It measures a layer that is not on the bitstream.
  USE INSTEAD: evidence/qwen9b/s4/run_s4_census.sh
  (see evidence/qwen9b/s4/S4_REPLAY.md; #122, triage (b)17)
REFUSING to run.
SUPERSEDED_BANNER
exit 2
# ============================================================================
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
TB="$REPO_ROOT/tb"
GENPY=${GENPY:-/home/cah/.venv/bin/python}
BIN=obj_dir_tb_layer_census_shipped/tb_layer_census_shipped
SEEDS=${SEEDS:-"1 2 3 4"}

cd "$TB" || exit 1
[ -x "$BIN" ] || { echo "FATAL: $TB/$BIN missing — run the shipped census first" >&2; exit 2; }

RC=0
for RSF in 7 8; do
    [ "$RSF" = 7 ] && WANT=PASS || WANT=FAIL
    echo "=== FABLE5_RS_F=$RSF — expecting every seed to $WANT ==="
    for s in $SEEDS; do
        # FABLE5_RS_F_RIDER=1 since 2026-09-10 (#26): RS_F is DERIVED from
        # the model tag now (9b => 7) and a disagreeing FABLE5_RS_F is
        # refused, so this control's RED half -- whose whole point is to
        # generate at the WRONG residual binary point -- must say that it
        # means it.  Kept correct behind the banner above.
        ( cd ../ref && FABLE5_MODEL=9b FABLE5_RS_F=$RSF FABLE5_RS_F_RIDER=1 \
            "$GENPY" gen_layer_script.py \
            ../tb/scripts/g4bctl_rsf${RSF}_s"$s".txt "$s" ) || { RC=1; continue; }
        "./$BIN" +script=scripts/g4bctl_rsf${RSF}_s"$s".txt > /tmp/g4bctl.$$ 2>&1
        got=$?
        tail -3 /tmp/g4bctl.$$ | sed "s/^/[rsf$RSF s$s] /"
        rm -f /tmp/g4bctl.$$
        if [ "$WANT" = PASS ] && [ $got -ne 0 ]; then
            echo "CONTROL FAIL: rsf7 seed $s should have passed (rc $got)"; RC=1
        fi
        if [ "$WANT" = FAIL ] && [ $got -eq 0 ]; then
            echo "CONTROL FAIL: rsf8 seed $s should have FAILED but passed"; RC=1
        fi
    done
done
# gen_layer_script.py writes a .txt, a .weights.json and 15 _w*.bin beside
# it; clean up ALL of them, not just the script (an earlier revision left 96
# untracked files in tb/scripts/).
rm -f scripts/g4bctl_rsf*_s*
if [ $RC -eq 0 ]; then
    echo "G4B_CENSUS_CONTROL PASS: the census's bit-exact half fires both ways"
else
    echo "G4B_CENSUS_CONTROL FAIL"
fi
exit $RC
