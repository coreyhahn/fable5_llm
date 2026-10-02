#!/usr/bin/env bash
# sr8_preflight.sh — Task SR8 step 0: the READ-ONLY pre-flight (controller
# addendum).  Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.  Touches no
# board state: no lock taken, no DMA, no SEQ window, no sudo; the identity
# is raw BAR reads (sr8_ident.py).  Prints PREFLIGHT: PASS / FAIL.
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
FAIL=0
bad() { echo "  FAIL: $*"; FAIL=1; }
R1BIT=synth/out_build_044_r1_incr/proj/stage1.runs/impl_1/bd_wrapper.bit
R1SHA=92a2e52573ad37afaa9f4616a637616494b23bb9858bcf54575f6c9960b50816
R1SZ=53076057
B41BIT=synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper.bit
B41SHA=eeeef897495d783aa4eb0b2b555373bbeed36182a4a754089d787b801224f031
B41SZ=53074589

echo "--- [1] board lock (sw/board_lock.py --status)"
LS=$(python3 sw/board_lock.py --status 2>&1); echo "$LS"
echo "$LS" | grep -q 'state *not held' || bad "the board lock is held"
echo "--- [2] hw_server"
pgrep -a hw_server || bad "hw_server is not running"
echo "--- [3] uptime / last boot (NEXT_SESSION §1: boot 2026-09-27 07:08)"
uptime; BOOT=$(who -b | awk '{print $3" "$4}'); echo "boot: $BOOT"
[ "$BOOT" = "2026-09-27 07:08" ] || bad "snoke rebooted since NEXT_SESSION §1 ($BOOT)"
echo "--- [4] PCI ID at 82:00.0 (want 10ee:9038; 1e24:1525 = factory image)"
LP=$(lspci -nn -s 82:00.0); echo "$LP"
echo "$LP" | grep -q '10ee:9038' || bad "82:00.0 is not 10ee:9038"
ls -l /dev/xdma0_user /dev/xdma0_h2c_0 /dev/xdma0_c2h_0 || bad "xdma nodes missing"
lsmod | grep '^xdma ' || bad "xdma module not loaded"
echo "--- [5] what is on the board (sr8_ident.py --expect c973c18a; raw reads, no DMA)"
/home/cah/.venv/bin/python evidence/qwen9b/sr/sr8_ident.py --expect c973c18a \
  || echo "  NOTE: the board is NOT on build_041 as expected (see values above)"
echo "--- [6] the two bitstreams this session may program (size, sha256)"
for pair in "$R1BIT $R1SHA $R1SZ" "$B41BIT $B41SHA $B41SZ"; do
  set -- $pair
  ls -la --time-style=full-iso "$1"
  S=$(stat -c %s "$1"); H=$(sha256sum "$1" | cut -d' ' -f1)
  echo "  size $S sha256 $H"
  [ "$S" = "$3" ] || bad "$1 size $S != $3"
  [ "$H" = "$2" ] || bad "$1 sha256 != $2"
done
echo "--- [7] r1 stream shas vs SR4's pins (4e11a2ae cc982e4f 0f85a974 492e0def)"
i=0
for want in 4e11a2ae cc982e4f 0f85a974 492e0def; do
  i=$((i+1)); f=tb/scripts/w9/model_9b_s${i}_reordB_r1.e4.seq
  H=$(sha256sum "$f" | cut -d' ' -f1); echo "  $f $H"
  [ "${H:0:8}" = "$want" ] || bad "$f sha256 ${H:0:8} != $want"
done
echo "--- [7b] the streams this session runs (sha256 vs their .seq.json)"
for p in model_9b_s1 model_9b_s2 model_9b_s3 model_9b_s4 model_9b_s1_reordB model_9b_s1_reordB_r1; do
  f=tb/scripts/w9/$p.e4
  H=$(sha256sum "$f.seq" | cut -d' ' -f1)
  M=$(python3 -c "import json;print(json.load(open('$f.seq.json'))['stream_sha256'])")
  echo "  $p.e4.seq $H manifest ${M:0:16}"
  [ "$H" = "$M" ] || bad "$p stream sha256 != its manifest"
done
echo "--- [8] chat r1 image pins in sw/chat_seq.py (SR6: lite 99991122..0723 / full bf115a04..7281)"
grep -n -A5 '^REORDER_B_R1_IMAGES' sw/chat_seq.py
P=$(sed -n '/^REORDER_B_R1_IMAGES/,/^}/p' sw/chat_seq.py | tr -d ' \n"')
echo "$P" | grep -q '999911226f9a70b43dda1b520b95fa544b1aa2c0e15935420aa317c9a5de0723' || bad "lite r1 pin"
echo "$P" | grep -q 'bf115a04ffcc6bfa8342576c275ef2998b01f7522bc15b315ac63f992adc7281' || bad "full r1 pin"
echo "--- [9] the admission row (sw/seq_run.py SEQ_VERSIONS has e3c2ff1e)"
grep -n '0xE3C2FF1E' sw/seq_run.py | head -3
echo "--- [10] the shipped venv"
/home/cah/.venv/bin/python -c 'import sys,numpy;print(sys.executable, sys.version.split()[0], "numpy", numpy.__version__)' || bad "venv"
echo "--- [11] git (snoke's view)"
git log --oneline -1; git status --short | grep -v -E '^\?\? evidence/qwen9b/sr/n8[0-9][0-9]_' ; echo "(end status)"
echo "--- [12] other board users"
pgrep -af 'chat_seq|seq_run|bm1_census|sr8_census|g6_state|serve.py' | grep -v -E 'pgrep|sr8_preflight' || echo "  none"
echo "PREFLIGHT: $([ $FAIL = 0 ] && echo PASS || echo FAIL)"
exit $FAIL
