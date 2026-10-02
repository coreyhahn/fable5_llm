#!/usr/bin/env bash
# sr5b_streams.sh — Task SR5b step 2: the identity of SR4's four r1 streams
# before any chip-TB use.  For each seed k:
#   1. the full sha256 SR4 logged for model_9b_s<k>_reordB_r1.e4.seq, read
#      from its own reorder log (evidence/qwen9b/sr/n41{0..3}_reorder_s<k>_B_r1.log,
#      the "=== wrote ... .seq sha256 <hex>" line);
#   2. the sha256 of the file on disk (gitignored, made by SR4);
#   3. a REGENERATION by SR4's recorded recipe — the command line of that log
#      (`--form B --cost csv --rtl r1 --stats`; the STATIC path gives other
#      bytes) — into a fresh prefix tb/scripts/w9/sr5b_regen_s<k>_r1.e4, and
#      its sha256; the .seqdata.bin copies are compared too.
# All three must agree for every seed, or the verdict is STOP (regenerate by
# SR4's recipe, never hand-edit).
#
#   bash evidence/qwen9b/sr/sr5b_streams.sh
#
# Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
PY=/home/cah/.venv/bin/python
cd "$ROOT" || exit 1
W9=tb/scripts/w9
FAIL=0
for k in 1 2 3 4; do
  L=$(ls evidence/qwen9b/sr/n41$((k - 1))_reorder_s${k}_B_r1.log)
  WANT=$(grep -E "^=== wrote $W9/model_9b_s${k}_reordB_r1\.e4\.seq sha256 " "$L" \
         | awk '{print $NF}')
  CMD=$(grep -m1 '^=== cmd : ' "$L" | sed 's/^=== cmd : //')
  echo "--- s$k: SR4's log $L"
  echo "    logged   $WANT"
  HAVE=$(sha256sum "$W9/model_9b_s${k}_reordB_r1.e4.seq" | cut -d' ' -f1)
  echo "    on disk  $HAVE  ($W9/model_9b_s${k}_reordB_r1.e4.seq)"
  OUT=$W9/sr5b_regen_s${k}_r1.e4
  RCMD=$(printf '%s' "$CMD" | sed "s#--out $W9/model_9b_s${k}_reordB_r1\.e4#--out $OUT#")
  case "$RCMD" in
    *"--cost csv --rtl r1"*"--out $OUT"*|*"--out $OUT"*"--cost csv --rtl r1"*) : ;;
    *) echo "    RECIPE NOT RECOGNISED: $RCMD"; FAIL=1; continue ;;
  esac
  echo "    regen    FABLE5_MODEL=9b FABLE5_RS_F=7 $RCMD"
  T0=$(date +%s)
  FABLE5_MODEL=9b FABLE5_RS_F=7 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
    $RCMD > "$OUT.regen.txt" 2>&1
  rc=$?
  grep -E "LOOP BODY|^=== output|^=== OUTPUT hazard|FENCE masks over" "$OUT.regen.txt" \
    | sed 's/^/      /'
  REGEN=$(sha256sum "$OUT.seq" 2>/dev/null | cut -d' ' -f1)
  echo "    regen    $REGEN  (rc $rc, $(( $(date +%s) - T0 )) s)"
  SD=$(cmp -s "$OUT.seqdata.bin" "$W9/model_9b_s${k}_reordB_r1.e4.seqdata.bin" \
       && echo IDENTICAL || echo DIFFER)
  echo "    .seqdata.bin regen vs on disk: $SD"
  if [ -n "$WANT" ] && [ "$rc" = 0 ] && [ "$WANT" = "$HAVE" ] \
     && [ "$WANT" = "$REGEN" ] && [ "$SD" = IDENTICAL ]; then
    echo "    s$k: IDENTITY OK (logged == on disk == regenerated)"
  else
    echo "    s$k: IDENTITY MISMATCH — STOP"; FAIL=1
  fi
done
if [ "$FAIL" = 0 ]; then echo "SR5B_STREAMS: PASS — 4/4 r1 streams are SR4's bytes"
else echo "SR5B_STREAMS: FAIL"; fi
exit "$FAIL"
