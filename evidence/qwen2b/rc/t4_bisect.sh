#!/usr/bin/env bash
# t4_bisect.sh — isolate the tb_seq_chip smoke failure along its three NEW
# axes: {2B geometry} x {W8 weights} x {nch=4 + per-channel repack}.
#
# Each cell is a one-DN + one-ATTN layer script from ref/gen_layer_script.py
# (random weights, no checkpoint needed), its seq_model .chip golden, and a
# tb_seq_chip run.  The 4-channel cells reuse obj_dir_tb_seq_chip_w8
# (-GNMV=4 -GWIMGPC=1); the 1-channel cells use obj_dir_tb_seq_chip
# (-GNMV=1 -GWIMGPC=0), the elaboration every frozen gate uses.
#
#   evidence/qwen2b/rc/t4_bisect.sh <cell> [<cell> ...]
#     cells: 08_w4_n1  08_w4_n4  08_w8_n1  08_w8_n4
#            2b_w4_n1  2b_w4_n4  2b_w8_n1  2b_w8_n4
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
PY=${MODELPY:-/home/cah/.venv/bin/python}
DIR=scripts/w5/bis
cd "$ROOT/tb" || exit 1
mkdir -p "$DIR"

run_cell() {
  local cell=$1
  local model wq nch name
  case "$cell" in
    08_*) model=0.8b ;;
    2b_*) model=2b   ;;
    *) echo "bad cell $cell"; return 1 ;;
  esac
  case "$cell" in
    *_w4_*) wq=w4 ;;
    *_w8_*) wq=w8 ;;
  esac
  case "$cell" in
    *_n1) nch=1 ;;
    *_n4) nch=4 ;;
  esac
  name="$DIR/bis_$cell"
  echo
  echo "################ CELL $cell  (model=$model wq=$wq nch=$nch)"
  local envs="FABLE5_MODEL=$model SEQ_PROFILE=epsnorm SEQ_NCH=$nch"
  [ "$nch" = 4 ] && envs="$envs SEQ_REPACK=1"
  ( cd ../ref && env $envs SEQ_EMIT="$PWD/../tb/$name.e" \
      "$PY" gen_layer_script.py "$PWD/../tb/$name.txt" 1 2 --wq=$wq ) \
    || { echo "CELL $cell GEN FAIL"; return 1; }
  FABLE5_MODEL=$model "$PY" scripts/gen_seq_chip_vectors.py "$name.e" \
      --base "$name" || { echo "CELL $cell VEC FAIL"; return 1; }
  ( cd ../ref && FABLE5_MODEL=$model "$PY" seq_model.py --gate \
      "../tb/$name.e" --base "../tb/$name" 2>&1 | tail -4 ) \
    || { echo "CELL $cell PYGATE FAIL"; return 1; }
  if [ "$nch" = 4 ]; then
    obj_dir_tb_seq_chip_w8/tb_seq_chip_w8 +seq="$name.e" +base="$name" \
      +watchdog_ms=600000 2>&1 | tail -12
  else
    obj_dir_tb_seq_chip/tb_seq_chip +seq="$name.e" +base="$name" \
      +watchdog_ms=600000 2>&1 | tail -12
  fi
  local rc=${PIPESTATUS[0]}
  echo "CELL $cell RTL rc=$rc"
}

for c in "$@"; do run_cell "$c"; done
