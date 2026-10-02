#!/usr/bin/env bash
# sr15_preflight.sh — Task SR15 step 0: the READ-ONLY pre-flight for the R2
# board session.  A copy of sr8_preflight.sh retargeted to R2, with the SR8
# review's minors made hard checks (the brief's addendum (ii)/(iii)):
#   * PREFLIGHT: PASS REQUIRES the board to read build_041's identity
#     (VERSION 0xC973C18A, CALIB 0xF) — anything else FAILS (no auto-program);
#   * every hw_server / vivado / xsdb / hw_manager process on snoke is LISTED,
#     and any ESTABLISHED TCP client of hw_server (port 3121) FAILS — no
#     other hw_manager client may be attached before this session programs;
#   * the r2 stream and chat-image pins are checked on the FULL sha256.
# Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.  Touches no board state:
# no lock taken, no DMA, no SEQ window, no sudo; the identity is raw BAR
# preads (sr8_ident.py).  Prints PREFLIGHT: PASS / FAIL.
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
FAIL=0
bad() { echo "  FAIL: $*"; FAIL=1; }
R2BIT=synth/out_build_045_r2_incr/proj/stage1.runs/impl_1/bd_wrapper.bit
R2SHA=c4caeb096b298206c207facca031652a904962a0b0f8a27e98233342af8b4dcb
R2SZ=53080061
B41BIT=synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper.bit
B41SHA=eeeef897495d783aa4eb0b2b555373bbeed36182a4a754089d787b801224f031
B41SZ=53074589
TWIN=synth/out_build_045_r2/proj/stage1.runs/impl_1/bd_wrapper.bit
TWINSHA=de6ad3635f1fbdcd3e798350909fd9b0950a576a89c2965cc3e29147fd21acaa

echo "--- [1] board lock (sw/board_lock.py --status)"
LS=$(python3 sw/board_lock.py --status 2>&1); echo "$LS"
echo "$LS" | grep -q 'state *not held' || bad "the board lock is held"
echo "--- [2] hw_server, and every vivado / hw_server / xsdb / hw_manager process on snoke"
pgrep -a hw_server || bad "hw_server is not running"
HWP=$(pgrep hw_server | head -1)
[ "$HWP" = "10107" ] && echo "  hw_server pid 10107 = the lab's (SR8's close)" \
  || echo "  NOTE: hw_server pid ${HWP:-none} is not SR8's 10107"
echo "  all matching processes (pgrep -af 'vivado|hw_server|xsdb|hw_manager'):"
pgrep -af 'vivado|hw_server|xsdb|hw_manager' | grep -v -E 'pgrep|sr15_preflight' | sed 's/^/    /' || echo "    none"
echo "  established TCP connections to hw_server port 3121 (an attached hw_manager client):"
EST=$(ss -tnp state established '( sport = :3121 or dport = :3121 )' 2>&1 | tail -n +2)
if [ -n "$EST" ]; then echo "$EST" | sed 's/^/    /'; bad "a client is attached to hw_server (port 3121)"; else echo "    none"; fi
echo "--- [3] uptime / last boot (NEXT_SESSION §1: boot 2026-09-27 07:08)"
uptime; BOOT=$(who -b | awk '{print $3" "$4}'); echo "boot: $BOOT"
[ "$BOOT" = "2026-09-27 07:08" ] || bad "snoke rebooted since NEXT_SESSION §1 ($BOOT)"
echo "--- [4] PCI ID at 82:00.0 (want 10ee:9038; 1e24:1525 = factory image)"
LP=$(lspci -nn -s 82:00.0); echo "$LP"
echo "$LP" | grep -q '10ee:9038' || bad "82:00.0 is not 10ee:9038"
ls -l /dev/xdma0_user /dev/xdma0_h2c_0 /dev/xdma0_c2h_0 || bad "xdma nodes missing"
lsmod | grep '^xdma ' || bad "xdma module not loaded"
echo "--- [5] what is on the board (sr8_ident.py --expect c973c18a; raw reads, no DMA) — MUST be build_041"
/home/cah/.venv/bin/python evidence/qwen9b/sr/sr8_ident.py --expect c973c18a \
  || bad "the board does NOT read build_041's identity (STOP, hand back)"
echo "--- [6] the two bitstreams this session may program (size, sha256), and the twin it must NOT"
for pair in "$R2BIT $R2SHA $R2SZ" "$B41BIT $B41SHA $B41SZ"; do
  set -- $pair
  ls -la --time-style=full-iso "$1"
  S=$(stat -c %s "$1"); H=$(sha256sum "$1" | cut -d' ' -f1)
  echo "  size $S sha256 $H"
  [ "$S" = "$3" ] || bad "$1 size $S != $3"
  [ "$H" = "$2" ] || bad "$1 sha256 != $2"
done
ls -la --time-style=full-iso "$TWIN"
TH=$(sha256sum "$TWIN" | cut -d' ' -f1)
echo "  TWIN (never programmed) sha256 $TH"
[ "$TH" = "$TWINSHA" ] && [ "$TH" != "$R2SHA" ] && echo "  the twin differs from the ruled file: OK" \
  || bad "twin hash unexpected"
echo "--- [7] r2 stream .seq sha256 (FULL) vs SR11b's writes (n1161..n1164)"
i=0
for want in 117ed8b061d5662517d67f905ff1b5900520ba39eff680548e8af9a7efc17d19 \
            5d0a8bdd8298ea252af063041c63bb5df654a9aa834be4acb66e8772c23c6756 \
            e35772cc8ed3e554bd3f1fbe93e2f40a754b70e2ea98adaa94d66e71a097a70c \
            8b16c7b15d1f204a00bc47b3cce11f8c85dc580ee4294f069451d41155b28563; do
  i=$((i+1)); f=tb/scripts/w9/model_9b_s${i}_reordB_r2.e4.seq
  H=$(sha256sum "$f" | cut -d' ' -f1); echo "  $f $H"
  [ "$H" = "$want" ] || bad "$f sha256 != $want"
done
echo "--- [7a] r1 stream .seq sha256 (FULL) vs SR4's pins (n800's full digests)"
i=0
for want in 4e11a2ae6872970ecb61e2bb37524b7bd863815e47df1fb9c3af2fbb3218cb28 \
            cc982e4f66be17cef279bf09dcbc36d1170a4347b68b90e31a51d5993b93bbd4 \
            0f85a974ffa9aa7e9431202e9346b74073fb0ab51624bb3720edb3927946fe3b \
            492e0def197b635b9e64b01e2ff1637bc4f1eda4db0899961e994160274e6c95; do
  i=$((i+1)); f=tb/scripts/w9/model_9b_s${i}_reordB_r1.e4.seq
  H=$(sha256sum "$f" | cut -d' ' -f1); echo "  $f $H"
  [ "$H" = "$want" ] || bad "$f sha256 != $want"
done
echo "--- [7b] the streams this session runs (sha256 vs their .seq.json, full)"
for p in model_9b_s1 model_9b_s2 model_9b_s3 model_9b_s4 model_9b_s1_reordB model_9b_s1_reordB_r1 model_9b_s1_reordB_r2; do
  f=tb/scripts/w9/$p.e4
  H=$(sha256sum "$f.seq" | cut -d' ' -f1)
  M=$(python3 -c "import json;print(json.load(open('$f.seq.json'))['stream_sha256'])")
  echo "  $p.e4.seq $H manifest $M"
  [ "$H" = "$M" ] || bad "$p stream sha256 != its manifest"
done
echo "--- [8] chat image pins in sw/chat_seq.py (FULL sha256): r2 (SR13b n1351), r1 (SR6 n601)"
grep -n -A5 '^REORDER_B_R2_IMAGES' sw/chat_seq.py
P=$(sed -n '/^REORDER_B_R2_IMAGES/,/^}/p' sw/chat_seq.py | tr -d ' \n"')
echo "$P" | grep -q 'c78312bb293a5c2a16f94a76bfabcba56ce34937457b10b69b12b4bd02ff6d45' || bad "lite r2 pin"
echo "$P" | grep -q '868ba4e03b26276ddb455c1fbe4aca5595f9a5ff9ab734c2b017a377f2b3ad87' || bad "full r2 pin"
grep -q -E '^PIN r2 lite c78312bb293a5c2a16f94a76bfabcba56ce34937457b10b69b12b4bd02ff6d45 39314$' evidence/qwen9b/sr/n1351_sr13b_r2_pins.log || bad "n1351 lite PIN line"
grep -q -E '^PIN r2 full 868ba4e03b26276ddb455c1fbe4aca5595f9a5ff9ab734c2b017a377f2b3ad87 40173$' evidence/qwen9b/sr/n1351_sr13b_r2_pins.log || bad "n1351 full PIN line"
P1=$(sed -n '/^REORDER_B_R1_IMAGES/,/^}/p' sw/chat_seq.py | tr -d ' \n"')
echo "$P1" | grep -q '999911226f9a70b43dda1b520b95fa544b1aa2c0e15935420aa317c9a5de0723' || bad "lite r1 pin"
echo "$P1" | grep -q 'bf115a04ffcc6bfa8342576c275ef2998b01f7522bc15b315ac63f992adc7281' || bad "full r1 pin"
echo "--- [9] the admission row (sw/seq_run.py has 0x266E3AE7)"
grep -n '0x266E3AE7' sw/seq_run.py | head -4
grep -q '0x266E3AE7' sw/seq_run.py || bad "no 266e3ae7 admission row"
echo "--- [10] the shipped venv"
/home/cah/.venv/bin/python -c 'import sys,numpy;print(sys.executable, sys.version.split()[0], "numpy", numpy.__version__)' || bad "venv"
echo "--- [11] git (snoke's view)"
git log --oneline -1; git status --short | grep -v -E '^\?\? evidence/qwen9b/sr/n15[0-9][0-9]_' ; echo "(end status)"
echo "--- [12] other board users"
pgrep -af 'chat_seq|seq_run|bm1_census|sr8_census|g6_state|serve.py|ddr_test' | grep -v -E 'pgrep|sr15_preflight' || echo "  none"
echo "PREFLIGHT: $([ $FAIL = 0 ] && echo PASS || echo FAIL)"
exit $FAIL
