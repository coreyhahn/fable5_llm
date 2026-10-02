#!/usr/bin/env bash
# sr12_mv_cycles.sh — Task SR12 backward compatibility at the ENGINE and
# CHANNEL level: every NON-bank run of tb_matvec / tb_matvec_ng /
# tb_matvec_chan is executed on the base-RTL binaries and on the R2-RTL
# binaries (the obj_dirs sr12_mv_each.sh built: `base` from the git-show
# extract with +define+SR12_NO_BANK_PORTS, `green` from ../rtl) and the two
# COMPLETE stdout transcripts are compared byte for byte.  Every $display
# carries its sim time ([%0t] result/phase lines, the +nogap `thru:` cycle
# counts, tb_matvec_chan's `perf: N beats in C cycles`), so byte-identical
# output is cycle identity of every result the TB observes.  Run ON SNOKE
# through sr_run.sh, after sr12_mv_each.sh base AND green.
#   evidence/qwen9b/sr/sr12_mv_cycles.sh <base_tag> <green_tag>
set -u
BT=${1:?base tag}; GT=${2:?green tag}
cd "$(dirname "$0")/../../../tb" || exit 1
MB=obj_dir_tb_matvec_sr12_$BT/tb_matvec; MG=obj_dir_tb_matvec_sr12_$GT/tb_matvec
CB=obj_dir_tb_chan_sr12_$BT/tb_chan;     CG=obj_dir_tb_chan_sr12_$GT/tb_chan
for b in $MB $MG $CB $CG; do
  echo "binary $b $(ls -la --time-style=full-iso $b | awk '{print $6, $7}')"
done
nsame=0; ndiff=0; fails=""
cmp1() {   # <name> <base bin> <green bin> <args...>
  local n=$1 b=$2 g=$3 ob og rb rg; shift 3
  ob=$($b "$@" 2>&1); rb=$?
  og=$($g "$@" 2>&1); rg=$?
  if [ "$ob" == "$og" ] && [ $rb -eq $rg ] && [ $rb -eq 0 ]; then
    nsame=$((nsame+1))
    echo "IDENTICAL $n ($(echo "$ob" | wc -l) lines, rc $rb): $(echo "$ob" | grep -E "thru:|perf:|PASS" | tail -1)"
  else
    ndiff=$((ndiff+1)); fails="$fails $n"
    echo "DIFFERS   $n rc $rb/$rg"
    diff <(echo "$ob") <(echo "$og") | head -6
  fi
}
NG6() { local s=$1; echo "vecv2/n1${s}_g128,vecv2/n2${s}_g128,vecv2/n3${s}_g128,vecv2/n4${s}_g128,vecv2/n5${s}_g128,vecv2/n6${s}_g128"; }
Q3() { local s=$1; echo "vecv2/q1${s}_g128,vecv2/q2${s}_g128,vecv2/q3${s}_g128"; }
for s in 1 2 3 4; do
  cmp1 mv_frozen_s$s $MB $MG --seed $s +vecdir=vec_s$s
  cmp1 mv_ng_s$s $MB $MG --seed $s +vecdirs=$(NG6 $s)
  cmp1 mv_ng_chunk1_s$s $MB $MG --seed $s +chunk=1 +vecdirs=$(NG6 $s)
  cmp1 mv_ng_nogap_s$s $MB $MG --seed $s +nogap +maxstall=0 +ngfloor=6 +vecdirs=$(NG6 $s)
  cmp1 mv_q_s$s $MB $MG --seed $s +vecdirs=$(Q3 $s)
  cmp1 mv_q_nogap_s$s $MB $MG --seed $s +nogap +maxstall=0 +ngfloor=6 +vecdirs=$(Q3 $s)
  cmp1 mv_mixed_s$s $MB $MG --seed $s +vecdirs=vecv2/q3${s}_g128,vecv2/n1${s}_g128,vecv2/q1${s}_g128,vecv2/n5${s}_g128,vecv2/q2${s}_g128,vecv2/q3${s}_g128
  cmp1 chan_frozen_s$s $CB $CG --seed $s +vecdir=vec_s$s
  for nm in q1 q2 q3; do
    cmp1 chan_${nm}_s$s $CB $CG --seed $s +shapeback +vecdir=vecv2/${nm}${s}_g128
  done
done
echo "SR12 MV CYCLES: $((nsame + ndiff)) runs compared, $nsame byte-identical, $ndiff differ:$fails"
[ $ndiff -eq 0 ]
