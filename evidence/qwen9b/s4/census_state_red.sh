#!/usr/bin/env bash
# census_state_red.sh — the RED and the GREEN for the census instrument's
# NEW half: the DDR state region S4 wired behind the layer's DMA master.
#
#   bash evidence/qwen9b/s4/census_state_red.sh [<cfg>]
#
# `evidence/qwen9b/g4/tb_layer_census.sv` now reads the layer's state out of
# `tb/seq_mem_file.sv`'s file-backed window instead of out of URAM.  The
# census's bit-exact half (every R / E / A record) is what makes that
# trustworthy — but only if it can actually FAIL when the region holds the
# wrong bytes.  A model that quietly returned zeros would replay a stream
# whose CONV taps came from `seed_conv` and nobody would know.
#
# So, on the SAME binary the census run built and the SAME script:
#
#   GREEN  +state=<the script's own prefix>       -> TB_LAYER_CENSUS PASS
#   RED 1  +state=<ANOTHER seed's state image>    -> must FAIL: the conv taps
#          are a different seed's, and the replay compares bit-exactly
#   RED 2  no +state= at all                      -> must FAIL: there is no
#          image behind the window
#
# RED 1 is the one that matters: it is the only arm that distinguishes "the
# TB reads the region" from "the TB reads SOMETHING and the numbers happen to
# agree".  Task 12's own control (`run_g4b_census_control.sh`) cannot be used
# unchanged here — it hardcodes the `shipped` cfg's obj_dir and predates
# `+state=` entirely — and it is outside S4's commit block, so this is S4's
# control for what S4 added.
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
CFG=${1:-s4shipped}
BIN=$ROOT/tb/obj_dir_tb_layer_census_${CFG}/tb_layer_census_${CFG}
SCRIPT=${SCRIPT:-scripts/w9/lay9b_s1}
OTHER=${OTHER:-scripts/w9/lay9b_s2}
WD=${WD:-600000}
cd "$ROOT/tb" || exit 2
[ -x "$BIN" ] || { echo "FATAL: $BIN missing — run the census first" >&2; exit 2; }
echo "=== binary  $BIN"
echo "=== built   $(date -Is -r "$BIN")"
echo "=== script  $SCRIPT.txt"
echo "=== other   $OTHER.state.bin (the RED's wrong image)"

FAIL=0
arm () {  # $1 = label, $2 = want (PASS|FAIL), $3.. = extra plusargs
  label=$1; want=$2; shift 2
  echo
  echo "=== $label: expecting the replay to $want"
  out=$("$BIN" +script=$SCRIPT.txt +watchdog_ms=$WD "$@" 2>&1)
  rc=$?
  printf '%s\n' "$out" | grep -E "state window|state region|TB_LAYER_CENSUS|FAIL |%Fatal|Fatal|errors=" \
    | head -8 | sed 's/^/    /'
  echo "    rc=$rc"
  if [ "$want" = PASS ] && [ "$rc" != 0 ]; then
    echo "    CONTROL FAIL: $label should have PASSED"; FAIL=1; fi
  if [ "$want" = FAIL ] && [ "$rc" = 0 ]; then
    echo "    CONTROL FAIL: $label should have FAILED — the census is not"
    echo "                  reading the state region it claims to read"; FAIL=1; fi
}

arm green      PASS +state=$SCRIPT
arm red_wrong  FAIL +state=$OTHER
arm red_nostate FAIL

echo
if [ "$FAIL" = 0 ]; then
  echo "CENSUS_STATE_RED: PASS — the census replays bit-exactly against its"
  echo "  own state image and REFUSES another seed's image and no image at all"
  exit 0
fi
echo "CENSUS_STATE_RED: FAIL"
exit 1
