#!/usr/bin/env bash
# sr12_mv_each.sh — Task SR12: tb_matvec and tb_matvec_chan built from ONE
# named RTL dir into task-private obj_dirs, and EVERY run of the two make
# targets' lists (the frozen stage-2 runs, the G3.3 9B runs, and the SR12
# bank runs) executed one by one, NOT stopping at the first failure — so a
# RED run on the pre-SR12 RTL and the negative control on a mutant record
# every run's verdict.  The run lists mirror tb/Makefile's tb_matvec,
# tb_matvec_ng (the SR12 row) and tb_matvec_chan targets; the GREEN of
# record is those targets themselves.  Run ON SNOKE, through sr_run.sh.
#   evidence/qwen9b/sr/sr12_mv_each.sh <tag> <rtl_dir> [base]
# <rtl_dir> is relative to tb/ and supplies matvec_engine.sv + matvec_chan.sv;
# `base` builds tb_matvec with +define+SR12_NO_BANK_PORTS (the pre-SR12
# engine has no cfg_xbank / cfg_rbank ports).  The bank runs pass
# +verilator+seed+<s>: Verilator ignores `--seed` (a runtime no-op the
# historical frozen runs keep, so they stay cycle-reproducible), and without
# it the four "seeds" of a run on the SAME vectors would be one random
# stream four times (seen in n1211).
set -u
TAG=${1:?tag}; RTLD=${2:?rtl_dir}; MODE=${3:-}
PY=/home/cah/.venv/bin/python
cd "$(dirname "$0")/../../../tb" || exit 1
DEFS=""; [ "$MODE" = base ] && DEFS="+define+SR12_NO_BANK_PORTS"
MVD=obj_dir_tb_matvec_sr12_$TAG; CHD=obj_dir_tb_chan_sr12_$TAG
echo "SR12 RTL: $RTLD/matvec_engine.sv sha256 $(sha256sum < "$RTLD/matvec_engine.sv" | cut -c1-16)," \
     "$RTLD/matvec_chan.sv sha256 $(sha256sum < "$RTLD/matvec_chan.sv" | cut -c1-16), defs [$DEFS]"
for v in "vec_s1 101 64 1024" "vec_s2 202 32 3584" "vec_s3 303 128 256" "vec_s4 404 16 2048"; do
  $PY ../ref/gen_matvec_vectors.py $v > /dev/null || exit 1
done
make --no-print-directory -s ng_vectors q9_vectors VECPY=$PY || exit 1
make --no-print-directory tb_matvec_build MVDIR=$MVD MVBIN=tb_matvec \
     MV_RTL="$RTLD" MV_DEFS="$DEFS" JOBS=16 > /dev/null || exit 1
make --no-print-directory tb_matvec_chan_build CHANDIR=$CHD \
     MV_RTL="$RTLD" JOBS=16 > /dev/null || exit 1
npass=0; nfail=0; fails=""
run1() {   # <name> <cmd...>
  local n=$1 out rc; shift
  echo "----- SR12RUN $n"
  out=$("$@" 2>&1); rc=$?
  echo "$out" | grep -E "PASS|FAIL|fatal|Error|error|pingpong|overlap|SR12|thru" | head -12
  if [ "$rc" -eq 0 ]; then npass=$((npass+1)); v=PASS
  else nfail=$((nfail+1)); fails="$fails $n"; v=FAIL; fi
  echo "SR12RUN $n $v rc=$rc"
}
guard1() { # <name> <arg> <message>: the guard must trip (message AND rc != 0)
  local n=$1 a=$2 m=$3 out rc
  echo "----- SR12RUN $n"
  out=$($MVD/tb_matvec +bankguard=$a 2>&1); rc=$?
  echo "$out" | grep -E "matvec_engine|TB_MATVEC" | head -3
  if [ $rc -ne 0 ] && [[ "$out" == *"matvec_engine: $m"* ]]; then
    npass=$((npass+1)); v=PASS
  else nfail=$((nfail+1)); fails="$fails $n"; v=FAIL; fi
  echo "SR12RUN $n $v rc=$rc (the guard must trip)"
}
NG6() { local s=$1; echo "vecv2/n1${s}_g128,vecv2/n2${s}_g128,vecv2/n3${s}_g128,vecv2/n4${s}_g128,vecv2/n5${s}_g128,vecv2/n6${s}_g128"; }
# ---- tb_matvec: the frozen runs, then the SR12 bank runs -------------
for s in 1 2 3 4; do run1 mv_frozen_s$s $MVD/tb_matvec --seed $s +vecdir=vec_s$s; done
for s in 1 2 3 4; do
  run1 mv_xrbank_s$s $MVD/tb_matvec --seed $s +verilator+seed+$s +xbank +rbank +vecdirs=vec_s1,vec_s2,vec_s3,vec_s4
  run1 mv_pingpong_s$s $MVD/tb_matvec --seed $s +verilator+seed+$s +pingpong +vecdirs=vec_s2,vec_s1,vec_s4,vec_s3
  run1 mv_pingpong_c3_s$s $MVD/tb_matvec --seed $s +verilator+seed+$s +pingpong +chunk=3 +vecdirs=vec_s2,vec_s1,vec_s4,vec_s3
  run1 mv_ng_xrbank_s$s $MVD/tb_matvec --seed $s +verilator+seed+$s +xbank +rbank +vecdirs=$(NG6 $s)
done
guard1 mv_bankguard_x x XBANK
guard1 mv_bankguard_r r RBANK
# ---- tb_matvec_chan: the frozen runs, the 9B runs, the SR12 bank runs --
for s in 1 2 3 4; do run1 chan_frozen_s$s $CHD/tb_chan --seed $s +vecdir=vec_s$s; done
for s in 1 2 3 4; do for nm in q1 q2 q3; do
  run1 chan_${nm}_s$s $CHD/tb_chan --seed $s +shapeback +vecdir=vecv2/${nm}${s}_g128
done; done
for s in 1 2 3 4; do
  n=$(( s % 4 + 1 ))
  run1 chan_xrbank_s$s $CHD/tb_chan --seed $s +verilator+seed+$s +xbank +rbank +shapeback +vecdir=vec_s$s
  run1 chan_q1_xrbank_s$s $CHD/tb_chan --seed $s +verilator+seed+$s +xbank +rbank +shapeback +vecdir=vecv2/q1${s}_g128
  run1 chan_overlap_s$s $CHD/tb_chan --seed $s +verilator+seed+$s +overlap=vec_s$n +vecdir=vec_s$s
done
echo "SR12 SUMMARY: $npass PASS, $nfail FAIL:$fails"
