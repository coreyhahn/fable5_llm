#!/usr/bin/env bash
# r3_9a_stream_ident.sh — Task R3-9a Step 1: re-hash every rung-1 stream's .seq and .chip
# (shipped / r1 / r2, seeds 1-4) against the earlier gates' logs (SR13a n1302,
# n1344, n1345-n1348).  Pure sha256 + grep; run ON SNOKE through sr_run.sh.
cd /home/cah/r2d2/code/fpga/fable5_llm
R=evidence/qwen9b/sr
bad=0; n=0
chk () { # file reflog
  local s
  s=$(sha256sum "tb/scripts/w9/$1" | cut -d' ' -f1); n=$((n+1))
  [ -n "$s" ] || { echo "MISSING  $1"; bad=$((bad+1)); return; }
  if grep -q "$s" "$R/$2"; then echo "MATCH    $s  $1  (= $2)"; else echo "MISMATCH $s  $1  (not in $2)"; bad=$((bad+1)); fi
}
for s in 1 2 3 4; do chk model_9b_s$s.e4.seq n1302_sr13a_stream_identity.log; chk model_9b_s$s.e4.chip n1302_sr13a_stream_identity.log; done
for s in 1 2 3 4; do chk model_9b_s${s}_reordB_r1.e4.seq n1302_sr13a_stream_identity.log; chk model_9b_s${s}_reordB_r1.e4.chip n1302_sr13a_stream_identity.log; done
for s in 1 2 3 4; do chk model_9b_s${s}_reordB_r2.e4.seq n1344_sr13a_r2_stream_identity.log; chk model_9b_s${s}_reordB_r2.e4.chip n$((1344+s))_sr13a_chipvec_s${s}_r2.log; done
echo "STREAM_IDENTITY: $n files re-hashed, $bad mismatches"
[ $bad = 0 ]
