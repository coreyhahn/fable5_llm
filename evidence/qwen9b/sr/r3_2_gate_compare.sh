#!/usr/bin/env bash
# r3_2_gate_compare.sh — Task R3-2: are the shipped / r1 / r2 stream gates'
# verdicts BYTE-IDENTICAL to the round's committed gate logs after R3-2's
# validator edit?  For each pair (new log, prior log) it compares the gate's
# own output — every line between the interpreter banner and the wall-clock
# line — with the per-phase timings "(NNN.Ns)" and the "gate wall" line
# removed (they are wall clock, not verdicts).  The prior logs are the ones
# SR4 (n414-n417, sr4_gate.sh, caps R1) and SR11b (n1169-n1172 sr11b_gate.sh
# caps R1,R2; n1174-n1177 the shipped sv1_gate.sh) committed.
#   evidence/qwen9b/sr/r3_2_gate_compare.sh [<12 new logs>]
# Task R3-3 flag ("flags, not copies"): with 12 arguments they replace the
# twelve NEW logs, in the order below (shipped s1..s4, r1 s1..s4, r2 s1..s4);
# the prior logs are unchanged.  No argument = R3-2's run, so n2495 reproduces.
# Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.  rc 0 = every pair identical.
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm/evidence/qwen9b/sr || exit 1
body() {  # the gate's verdict body, timings stripped
  sed -n '/^=== interpreter/,/^=== gate wall/p' "$1" \
    | grep -v -e '^=== gate wall' \
    | sed -E 's/ \([0-9]+\.[0-9]+s\)//g'
}
PAIRS="n2481_r3_2_gate_shipped_s1_r0.log:n1174_gate_shipped_s1_r0.log
n2482_r3_2_gate_shipped_s2_r0.log:n1175_gate_shipped_s2_r0.log
n2483_r3_2_gate_shipped_s3_r0.log:n1176_gate_shipped_s3_r0.log
n2484_r3_2_gate_shipped_s4_r0.log:n1177_gate_shipped_s4_r0.log
n2485_r3_2_gate_s1_reordB_r1.log:n414_gate_s1_reordB_r1.log
n2486_r3_2_gate_s2_reordB_r1.log:n415_gate_s2_reordB_r1.log
n2487_r3_2_gate_s3_reordB_r1.log:n416_gate_s3_reordB_r1.log
n2488_r3_2_gate_s4_reordB_r1.log:n417_gate_s4_reordB_r1.log
n2491_r3_2_gate_s1_reordB_r2.log:n1169_gate_s1_reordB_r2.log
n2492_r3_2_gate_s2_reordB_r2.log:n1170_gate_s2_reordB_r2.log
n2493_r3_2_gate_s3_reordB_r2.log:n1171_gate_s3_reordB_r2.log
n2494_r3_2_gate_s4_reordB_r2.log:n1172_gate_s4_reordB_r2.log"
if [ $# -ne 0 ]; then
  [ $# -eq 12 ] || { echo "r3_2_gate_compare.sh: need 0 or 12 new logs, got $#" >&2; exit 2; }
  i=0; NP=""
  for p in $PAIRS; do
    i=$((i+1)); NP="$NP ${!i}:${p##*:}"
  done
  PAIRS=$NP
fi
bad=0
for p in $PAIRS; do
  new=${p%%:*}; old=${p##*:}
  nb=$(body "$new" | wc -l)
  verdict=$(grep -h -E '^SEQ GATE|^=== rc' "$new" | tr '\n' ' ')
  if diff <(body "$old") <(body "$new") >/dev/null; then
    echo "IDENTICAL  $new == $old  ($nb body lines)  $verdict"
  else
    echo "DIFFERS    $new vs $old  $verdict"; diff <(body "$old") <(body "$new") | head -20
    bad=1
  fi
done
echo "R3_2_GATE_COMPARE: $([ $bad = 0 ] && echo PASS || echo FAIL)"
exit $bad
