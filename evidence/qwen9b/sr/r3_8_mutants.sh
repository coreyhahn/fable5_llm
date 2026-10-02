#!/usr/bin/env bash
# r3_8_mutants.sh — Task R3-8 negative controls: the lockstep and the skid
# sizing checks must FAIL on RTL that breaks them.  New file (the mutants are
# R3's own; sr12_rtl_copies.sh mutates the R2 fields).  Mutant copies go to
# tb/scripts_scratch/r3_8_mut_{m1,m2}/ (gitignored), task-private obj_dirs.
#   M1  seq_movers IGNORES room: xp_fire's `&xp_room_q` becomes
#       `&(xp_room_q | 4'hF)` (still reads the flops: -Wall clean).  Run:
#       tb_seq seq_h_bcast +xp_lowroom=0:16:40 — MUST fail (pushes keep
#       arriving at the stub while its room is low).
#   M2  matvec_chan's XP_INFLIGHT = 1 (room ignores the words in flight).
#       Run: tb_matvec_chan +push +pushstall=40 vec_s1 — MUST fail (a push
#       arrives with the skid full: the RTL's own sim-only $fatal).
# A mutant that PASSES is a vacuous check: the script then exits 1.
# Run ON SNOKE through sr_run.sh.
#
# R3-9a (flags, not copies): the same mutations, and three more, as CHIP-TB
# mutation SETS for evidence/qwen9b/sr/sr13a_mut_build.sh (a git-archive
# snapshot of a commit, its own obj_dir tb/obj_dir_seq_chip_sr<tag>; the live
# rtl/ is never touched).  With no argument this script runs R3-8's unit
# mutants exactly as before.
#   --meta  <set>          prints "<obj_dir tag> <changed lines> <files...>"
#   --apply <set> <rtldir> applies the set to the files in <rtldir>/
#   m1     R3-8 M1: seq_movers ignores room                   (tag r3b_m1)
#   m2     R3-8 M2: matvec_chan XP_INFLIGHT = 1               (tag r3b_m2)
#   bc0    the broadcast writes channel 0 only: xp_v_q loads {0,0,0,fire}
#                                                             (tag r3b_mbc0)
#   room0  lockstep broken: the push is gated on channel 0's room only
#          (&(xp_room_q | 4'hE) still reads every flop: -Wall clean)
#                                                             (tag r3b_mroom0)
#   xprt0  XP_RT = 0: the mover trusts busy right after the last push
#          ((FWD + RET) * 0 still reads both stage counts)     (tag r3b_mxprt0)
# Each set is ONE changed line.
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd); cd "$ROOT" || exit 1
S_M1="s/&& (&xp_room_q);/\\&\\& (\\&(xp_room_q | 4'hF));/"
S_M2="s/localparam int XP_INFLIGHT   = XP_FWD_STAGES + XP_RET_STAGES + 1;/localparam int XP_INFLIGHT   = 1;/"
S_BC0="s/xp_v_q    <= {4{xp_fire}};/xp_v_q    <= {3'd0, xp_fire};/"
S_ROOM0="s/&& (&xp_room_q);/\\&\\& (\\&(xp_room_q | 4'hE));/"
S_XPRT0="s/localparam int XP_RT         = XP_FWD_STAGES + XP_RET_STAGES;/localparam int XP_RT         = (XP_FWD_STAGES + XP_RET_STAGES) * 0;/"
mset () {  # $1 = set -> "tag lines file sed"
  case "$1" in
    m1)    echo "r3b_m1 1 seq_movers.sv";     SED=$S_M1 ;;
    m2)    echo "r3b_m2 1 matvec_chan.sv";    SED=$S_M2 ;;
    bc0)   echo "r3b_mbc0 1 seq_movers.sv";   SED=$S_BC0 ;;
    room0) echo "r3b_mroom0 1 seq_movers.sv"; SED=$S_ROOM0 ;;
    xprt0) echo "r3b_mxprt0 1 seq_movers.sv"; SED=$S_XPRT0 ;;
    *) echo "unknown mutation set '$1'" >&2; return 2 ;;
  esac
}
case "${1:-}" in
  --meta)  mset "${2:?--meta <set>}" > /dev/null || exit 2; mset "$2"; exit 0 ;;
  --apply) META=$(mset "${2:?--apply <set> <rtldir>}") || exit 2; mset "$2" > /dev/null
           F=$(echo "$META" | cut -d" " -f3); D=${3:?--apply <set> <rtldir>}
           sed -i "$SED" "$D/$F"; exit 0 ;;
esac
PY=/home/cah/.venv/bin/python
M1=tb/scripts_scratch/r3_8_mut_m1; M2=tb/scripts_scratch/r3_8_mut_m2
rm -rf "$M1" "$M2"; mkdir -p "$M1" "$M2"
cp rtl/seq_unit.sv rtl/seq_movers.sv "$M1/"
sed -i "s/&& (&xp_room_q);/\&\& (\&(xp_room_q | 4'hF));/" "$M1/seq_movers.sv"
cp rtl/matvec_engine.sv rtl/matvec_chan.sv "$M2/"
sed -i 's/localparam int XP_INFLIGHT   = XP_FWD_STAGES + XP_RET_STAGES + 1;/localparam int XP_INFLIGHT   = 1;/' "$M2/matvec_chan.sv"
echo "M1 diff:"; diff rtl/seq_movers.sv "$M1/seq_movers.sv"
echo "M2 diff:"; diff rtl/matvec_chan.sv "$M2/matvec_chan.sv"
n1=$(diff rtl/seq_movers.sv "$M1/seq_movers.sv" | grep -c '^>'); n2=$(diff rtl/matvec_chan.sv "$M2/matvec_chan.sv" | grep -c '^>')
[ "$n1" = 1 ] && [ "$n2" = 1 ] || { echo "MUTANT NOT APPLIED (m1 $n1, m2 $n2 lines)"; exit 1; }
cd tb || exit 1
make --no-print-directory seq_unit_vectors SEQ_VEC=scripts_scratch/seqvec_r3mut VECPY=$PY > /dev/null || exit 1
make --no-print-directory tb_seq_build SEQ_OBJ=obj_dir_seq_unit_r3mut1 JOBS=16 \
     SEQ_RTL="../$M1/seq_unit.sv ../$M1/seq_movers.sv" > /dev/null || { echo "M1 build failed"; exit 1; }
echo "----- M1 run"
obj_dir_seq_unit_r3mut1/tb_seq +vec=scripts_scratch/seqvec_r3mut/seq_h_bcast +xp_lowroom=0:16:40 2>&1 | grep -E "Fatal|PASS|x-push" | head -5
r1=${PIPESTATUS[0]}
$PY ../ref/gen_matvec_vectors.py vec_s1 101 64 1024 > /dev/null || exit 1
make --no-print-directory tb_matvec_chan_build CHANDIR=obj_dir_tb_chan_r3mut2 MV_RTL="../$M2" JOBS=16 > /dev/null \
     || { echo "M2 build failed"; exit 1; }
echo "----- M2 run"
obj_dir_tb_chan_r3mut2/tb_chan --seed 1 +verilator+seed+1 +push +pushstall=40 +vecdir=vec_s1 2>&1 | grep -E "Fatal|PASS|FAIL" | head -5
r2=${PIPESTATUS[0]}
echo "M1 rc $r1 (must be non-zero), M2 rc $r2 (must be non-zero)"
if [ "$r1" != 0 ] && [ "$r2" != 0 ]; then echo "R3-8 MUTANTS: 2 of 2 CAUGHT"; else echo "R3-8 MUTANTS: VACUOUS CHECK"; exit 1; fi
