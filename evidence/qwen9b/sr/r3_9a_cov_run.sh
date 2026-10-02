#!/usr/bin/env bash
# r3_9a_cov_run.sh — Task R3-9a Step 4, part 2: ONE seed's broadcast coverage
# streams through the REAL engine on the chip TB.  New file (a driver over
# evidence/qwen9b/sr/run_sr_chip.sh; the artifacts are r3_9a_cov_gen.sh's).
#
#   bash evidence/qwen9b/sr/r3_9a_cov_run.sh <s> <control|timeline> [<hold> | nohold]
#
#   <s>     seed index 1..4 (stems tb/scripts/w9/r3_9a_<kind>_s<s>)
#   <hold>  +xp_hold's <chan>:<start>:<cycles> for bcast_bp's HELD run (run
#           after the unheld one, logged with --logtag hold); `nohold` or
#           absent: no held run.  `holdonly` as the 4th argument runs ONLY
#           the held bcast_bp run.
#
# Every run: K=r3b (tb/obj_dir_seq_chip_srr3b, whose sha256 run_sr_chip.sh
# prints), the default LOGDIR, +caps_expect=fab1ca07 (the TB $fatals on any
# other SEQ_CAPS).  Per stream it then checks, from the simulator's own log:
#   * TB_SEQ_CHIP PASS (every scratch word, XRF, TCNT, PC vs the golden);
#   * the R3-8 end-to-end line: N broadcasts retired, W words pushed per
#     channel — W must equal sr13a_cov.py's R3_BCAST_WORDS for that stream
#     (the generation log of the seed, n313<s-1>);
#   * the R3-9a line: the X_END-exit check ran (landed == sent at each exit).
# In control mode it also runs the LATE-READER MUTANT stream (bcast_late's
# _mut, the correct golden) and REQUIRES it to FAIL.
# FIRST: R3-7's prediction 82d2677 must be an ancestor of HEAD.
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
cd "$ROOT" || exit 1
S=${1:?usage: r3_9a_cov_run.sh <s> <control|timeline> [<hold>|nohold] [holdonly]}
MODE=${2:?usage}
HOLD=${3:-nohold}
ONLY=${4:-}
echo "=== R3-7's prediction 82d2677 an ancestor of HEAD $(git rev-parse --short HEAD)?"
if git merge-base --is-ancestor 82d2677 HEAD; then echo "    git merge-base --is-ancestor 82d2677 HEAD -> 0 (yes)"
else echo "    NOT AN ANCESTOR — no broadcast may run"; exit 9; fi
export K=r3b
R=evidence/qwen9b/sr
W9=tb/scripts/w9
GEN=$R/n313$((S - 1))_r3_9a_cov_gen_s$S.log
[ -f "$GEN" ] || { echo "MISSING the generation log $GEN"; exit 3; }
F=0
one () {  # $1 stem, $2 kind index (1-based, for R3_BCAST_WORDS), $3 logtag or "", rest: extra
  local st=$1 ki=$2 tag=$3; shift 3
  local args=(--plusarg +caps_expect=fab1ca07) csv="" sl
  if [ "$MODE" = timeline ]; then
    csv=$ROOT/$W9/$st${tag:+_$tag}.timeline.csv; args+=(--csv "$csv"); fi
  [ -n "$tag" ] && args+=(--logtag "$tag")
  echo "######## $st $MODE${tag:+ ($tag)} $*"
  bash $R/run_sr_chip.sh "$st" "$st" "$MODE" "${args[@]}" "$@" || F=1
  sl=$R/srr3b_seed_${st}_$MODE${tag:+_$tag}.log
  local want got
  want=$(grep '^  R3_BCAST_WORDS ' "$GEN" | sed -n "${ki}p" | awk '{print $4}')
  got=$(grep '^tb_seq_chip R3-8: ' "$sl" | awk '{print $6}')
  echo "    R3_BCAST_WORDS (generator) $want, words pushed per channel (TB) $got"
  if [ -n "$want" ] && [ "$want" = "$got" ]; then echo "    PUSH COUNT = GENERATOR"
  else echo "    PUSH COUNT MISMATCH"; F=1; fi
  grep '^tb_seq_chip R3-9a: ' "$sl" | sed 's/^/    /' || { echo "    NO R3-9a X_END-EXIT LINE"; F=1; }
}
k=0
for kind in bcast bcast_overlap bcast_bp bcast_ragged bcast_late; do
  k=$((k + 1))
  [ -n "$ONLY" ] && continue
  one "r3_9a_${kind}_s$S" "$k" ""
done
if [ "$HOLD" != nohold ]; then
  one "r3_9a_bcast_bp_s$S" 3 hold --plusarg "+xp_hold=$HOLD"
fi
if [ "$MODE" = control ] && [ -z "$ONLY" ]; then
  st=r3_9a_bcast_late_s${S}_mut
  echo "######## $st control — THE LATE-READER MUTANT: MUST FAIL"
  if bash $R/run_sr_chip.sh "$st" "r3_9a_bcast_late_s$S" control \
       --plusarg +caps_expect=fab1ca07; then
    echo "    THE MUTANT PASSED — the late reader is not covered"; F=1
  else
    echo "    THE MUTANT FAILED, as required:"
    grep -m4 -E "MEM\[|mismatch|Fatal|comparison failures" "$R/srr3b_seed_${st}_control.log" | sed 's/^/      /'
  fi
fi
[ "$F" = 0 ] && echo "R3_9A_COV_RUN s$S $MODE: ALL PASS" || echo "R3_9A_COV_RUN s$S $MODE: FAIL"
exit "$F"
