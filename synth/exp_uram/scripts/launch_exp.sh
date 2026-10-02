#!/bin/bash
# launch_exp.sh — run one Track P URAM placement experiment variant.
# Run ON SNOKE (house rule: Vivado on snoke/darthplagueis only):
#   ./launch_exp.sh <variant> <LNH> <N_DN> <N_KV> <NKVH> <CVD> <DN_EW> <DN_PACK> \
#                    <place0|1> [directive] [extra.xdc ...]
# Detach with:
#   nohup ./launch_exp.sh s5base 32 24 8 4 8192 16 0 1 > /dev/null 2>&1 &
#
# S5 (2026-09-05): DN_PIPE and DN_BPG are GONE from the positional list — S2
# deleted both parameters from rtl/layer_chan.sv with the banked DN array they
# configured, so exp_ooc.tcl passes no -generic at all and its argv shifted by
# two.  A pre-S5 command line silently means something different here now,
# which is why the assignment line below is the order that governs.
#
# THE POSITIONAL ORDER THAT GOVERNS IS THE ASSIGNMENT LINE BELOW, not this
# comment (an earlier revision of the comment omitted DN_PIPE entirely).
#
# G5a (Task 13): argument 13 onward is a list of IMPLEMENTATION-ONLY XDC files
# — the floorplan candidates in synth/constraints/fable5_floorplan_9b_*.xdc.
# exp_ooc.tcl reads them AFTER synth_design and BEFORE opt_design, which is the
# non-project equivalent of synth/scripts/full_impl.tcl's
# `add_files -fileset constrs_1` + `USED_IN_SYNTHESIS false`.
# exp_ooc.tcl now reads the SHIPPING rtl/, not synth/exp_uram/rtl/.
# S5: argument 11 onward is that XDC list (it was 13 before DN_PIPE/DN_BPG went).
#
# Output goes to synth/out_exp_uram_<variant>/ — a FRESH dir per run, never
# reused (house rule; synth/scripts/launch_build.sh does the same).
set -euo pipefail

VARIANT=${1:?usage: launch_exp.sh <variant> <LNH> <N_DN> <N_KV> <NKVH> <CVD> <DN_EW> <DN_PACK> <place> [directive] [extra.xdc ...]}
LNH=${2:?}; N_DN=${3:?}; N_KV=${4:?}; NKVH=${5:?}; CVD=${6:?}; DN_EW=${7:?}; DN_PACK=${8:?}; PLACE=${9:?}; DIRECTIVE=${10:-Default}
shift 10 2>/dev/null || shift $#
EXTRA_XDC=("$@")          # zero or more implementation-only XDC files

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
OUT_DIR="$REPO_ROOT/synth/out_exp_uram_${VARIANT}"

if [ -d "$OUT_DIR" ]; then
    echo "FATAL: $OUT_DIR already exists — experiment dirs are never overwritten" >&2
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
  echo "=== Track P URAM placement experiment: $VARIANT ==="
  echo "host      : $(hostname)"
  echo "date      : $(date -Is)"
  echo "tree      : $(cd "$REPO_ROOT" && git rev-parse --short=8 HEAD) $(cd "$REPO_ROOT" && git status --porcelain | wc -l) dirty files"
  echo "vivado    : $(which vivado)"
  echo "params    : LNH=$LNH N_DN=$N_DN N_KV=$N_KV NKVH=$NKVH CVD=$CVD DN_EW=$DN_EW DN_PACK=$DN_PACK place=$PLACE directive=$DIRECTIVE"
  echo "extra_xdc : ${EXTRA_XDC[*]:-none}"
  echo "rtl       : $REPO_ROOT/rtl (SHIPPING rtl/, re-pointed at G5a Step 1)"
} | tee run.log

vivado -mode batch -nojournal -log vivado.log \
    -source "$SCRIPT_DIR/exp_ooc.tcl" \
    -tclargs "$OUT_DIR" "$VARIANT" "$LNH" "$N_DN" "$N_KV" "$NKVH" "$CVD" "$DN_EW" "$DN_PACK" "$PLACE" "$DIRECTIVE" "${EXTRA_XDC[@]}" \
    2>&1 | tee -a run.log || true

# ANCHORED: Vivado echoes every sourced line into the log prefixed with "# ",
# so an unanchored grep counts the SCRIPT's own text and reports markers that
# were never emitted (G5a round 1 read "2 EXP_DONE marker(s)" on a run that
# printed none).
echo "=== exit: $(grep -c '^EXP_DONE' run.log) EXP_DONE marker(s) ===" | tee -a run.log
grep -E "^EXP_" run.log | tee summary.txt
