#!/bin/bash
# run_g4b_ooc.sh — G4b Step 1 launcher.  Run ON SNOKE (house rule: Vivado on
# snoke / darthplagueis only).
#
#   ./run_g4b_ooc.sh <tag> <top> [dn_pipe]
#
# Output goes to synth/out_ooc9b_<tag>/ — a FRESH dir per run, never reused
# (house rule; synth/scripts/launch_build.sh and Track P's launch_exp.sh both
# do the same).  synth/out_* is gitignored, so collect the load-bearing report
# sections into evidence/qwen9b/g4/ afterwards.
#
# Detach with:
#   nohup ./run_g4b_ooc.sh layer_pipe2 layer_chan > /dev/null 2>&1 &
set -euo pipefail

TAG=${1:?usage: run_g4b_ooc.sh <tag> <top> [dn_pipe]}
TOP=${2:?}
DNPIPE=${3:--1}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
OUT_DIR="$REPO_ROOT/synth/out_ooc9b_${TAG}"

if [ -d "$OUT_DIR" ]; then
    echo "FATAL: $OUT_DIR already exists — OOC out dirs are never overwritten" >&2
    exit 1
fi
mkdir -p "$OUT_DIR"
# stage the ROM hex files so $readmemh's relative default names resolve
# against the Vivado process CWD (= $OUT_DIR, cd'd into below)
for r in rsqrt_rom sigmoid_pair_rom softplus_pair_rom exp2_pair_rom recip_rom; do
    ln -sf "$REPO_ROOT/rtl/roms/$r.hex" "$OUT_DIR/$r.hex"
done

set +u
source /home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh
set -u

cd "$OUT_DIR"
{
  echo "=== G4b OOC structure run: $TAG ==="
  echo "host      : $(hostname)"
  echo "date      : $(date -Is)"
  echo "tree      : $(cd "$REPO_ROOT" && git rev-parse --short=8 HEAD) $(cd "$REPO_ROOT" && git status --porcelain | wc -l) dirty files"
  echo "vivado    : $(which vivado)"
  echo "params    : top=$TOP dn_pipe=$DNPIPE (-1 = the RTL's own default)"
} | tee run.log

vivado -mode batch -nojournal -log vivado.log \
    -source "$REPO_ROOT/synth/scripts/ooc_9b.tcl" \
    -tclargs "$OUT_DIR" "$TOP" "$DNPIPE" \
    2>&1 | tee -a run.log || true

echo "=== exit: $(grep -c OOC9B_DONE run.log) OOC9B_DONE marker(s) ===" | tee -a run.log
grep -E "^(OOC9B_|=== |host |date |tree |vivado |params )" run.log | tee summary.txt
