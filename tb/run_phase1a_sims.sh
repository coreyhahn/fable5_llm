#!/bin/bash
# Phase-1A sim gate: run every regenerated script family through the
# CURRENT tb_layer binary (committed RTL, untouched by Phase 1A).
# Usage: bash tb/run_phase1a_sims.sh          (run from anywhere)
set -u
cd "$(dirname "$0")"
EV=../evidence/stage5
BIN=obj_dir_tb_layer/tb_layer

run() {   # run <logtag> <args...>
  local tag=$1; shift
  ( $BIN "$@" > "$EV/sim_phase1a_$tag.log" 2>&1
    echo "EXIT=$?" >> "$EV/sim_phase1a_$tag.log" ) &
}

for s in 1 2 3 4; do
  run "chain_s$s"    +script=scripts/chain_s$s.txt +watchdog_ms=4000
  run "token24_s$s"  +script=scripts/token24_s$s.txt \
                     +emb=scripts/token24_s$s.emb.bin +watchdog_ms=20000
  run "model_v2_s$s" +script=scripts/model_v2_s$s.txt \
                     +emb=scripts/model_v2_s$s.emb.bin +watchdog_ms=60000
done
wait
echo "ALL PHASE1A SIMS DONE"
