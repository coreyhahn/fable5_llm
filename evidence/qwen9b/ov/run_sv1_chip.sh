#!/usr/bin/env bash
# run_sv1_chip.sh — Task SV1: ONE chip-TB run of a REORDERED stream on SV1's
# own binary.  A copy of evidence/qwen9b/bn/run_bn_timeline.sh's discipline
# (same `cd tb`, same TRACKED-log-dir refusal, same ROM-not-loaded check,
# same token read OUT OF A COMMITTED DOCUMENT with the no-record and
# ambiguous-record failures, same control/timeline split), changed in four
# places only:
#   * the binary is tb/obj_dir_seq_chip_sv1/tb_seq_chip_9b_sv1 (built by
#     evidence/qwen9b/ov/sv1_build.sh from a snapshot of the shipped RTL);
#   * the stream (+seq) and the artifact (+base) are separate stems — the
#     reordered `.e4` shares the shipped artifact's weights, embedding table,
#     state image and token record;
#   * the TOKEN record is looked up under the BASE stem (the reordered stream
#     must produce the shipped artifact's tokens: token-identical is the
#     acceptance, and a difference is a STOP, never tuned away);
#   * the cycle count is not required to EQUAL a reference (the stream is
#     different by design): `--cycles-today N` prints the delta against
#     today's count for the same seed and FAILS if the reordered stream is
#     not faster (a brief STOP condition).
#
#   bash evidence/qwen9b/ov/run_sv1_chip.sh <seq-stem> <base-stem> <mode> \
#        [--csv <path>] [--cycles-today <N>] [--tokens-ref <doc.md>]
#
# Run ON SNOKE through evidence/qwen9b/ov/ov_run.sh, detached.
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
PWD0=$PWD
cd "$ROOT/tb"

SEQ=${1:?usage: run_sv1_chip.sh <seq-stem> <base-stem> <mode> [...]}
BASE=${2:?usage}
MODE=${3:?usage}
shift 3
CSV=""
CYCTODAY=""
TOKREF=""
while [ $# -gt 0 ]; do
  case "$1" in
    --csv)          CSV=${2:?--csv needs a path};              shift 2 ;;
    --cycles-today) CYCTODAY=${2:?--cycles-today needs a number}; shift 2 ;;
    --tokens-ref)   TOKREF=${2:?--tokens-ref needs a document}; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
case "$MODE" in
  control)  [ -n "$CSV" ] && { echo "control mode takes no --csv" >&2; exit 2; } ;;
  timeline) [ -n "$CSV" ] || { echo "timeline mode needs --csv" >&2; exit 2; } ;;
  *) echo "mode must be 'control' or 'timeline'" >&2; exit 2 ;;
esac
if [ -n "$TOKREF" ]; then
  case "$TOKREF" in
    /*) : ;;
    *)  if   [ -f "$PWD0/$TOKREF" ]; then TOKREF=$PWD0/$TOKREF
        elif [ -f "$ROOT/$TOKREF" ]; then TOKREF=$ROOT/$TOKREF
        fi ;;
  esac
  [ -f "$TOKREF" ] || { echo "--tokens-ref: no such document: $TOKREF" >&2
                        exit 2; }
fi

BIN=$ROOT/tb/obj_dir_seq_chip_sv1/tb_seq_chip_9b_sv1
WD=${WD:-172800000}
LOGDIR=${LOGDIR:-$ROOT/evidence/qwen9b/ov/seedlogs_sv1}
mkdir -p "$LOGDIR"
if git -C "$ROOT" ls-files --error-unmatch "$LOGDIR/${SEQ}_$MODE.log" >/dev/null 2>&1 \
   || [ -e "$LOGDIR/${SEQ}_$MODE.log" ]; then
  echo "REFUSING: $LOGDIR/${SEQ}_$MODE.log exists — never overwrite" >&2
  exit 4
fi
[ -x "$BIN" ] || { echo "MISSING $BIN (evidence/qwen9b/ov/sv1_build.sh)" >&2
                   exit 3; }
if [ -n "$CSV" ] && [ -e "$CSV" ]; then
  echo "REFUSING: $CSV exists — pick a new name" >&2
  exit 2
fi
W9=$ROOT/tb/scripts/w9
for f in "$W9/$SEQ.e4.seq" "$W9/$SEQ.e4.seqdata.bin" "$W9/$SEQ.e4.chip"; do
  [ -f "$f" ] || { echo "MISSING $f" >&2; exit 3; }
done
LOG=$LOGDIR/${SEQ}_$MODE.log

echo "=== binary   $BIN"
echo "=== built    $(date -Is -r "$BIN")  sha256 $(sha256sum "$BIN" | cut -c1-16)"
echo "=== seq      $W9/$SEQ.e4  (.seq sha256 $(sha256sum "$W9/$SEQ.e4.seq" | cut -c1-16), .chip sha256 $(sha256sum "$W9/$SEQ.e4.chip" | cut -c1-16))"
echo "=== base     $W9/$BASE   mode: $MODE"
echo "=== watchdog $WD ms"
echo "=== stdout   $LOG"
[ -n "$CSV" ]      && echo "=== csv      $CSV"
[ -n "$CYCTODAY" ] && echo "=== cycles-today $CYCTODAY"
[ -n "$TOKREF" ]   && echo "=== tokens-ref $TOKREF (record of $BASE)"

tokens_ref () {  # $1 = document, $2 = artifact name
  awk -v t="$2" '
    index($0, "`" t "`") == 0 { next }
    { s = $0; cand = ""
      while (match(s, /\[[0-9]+(,[ ]*[0-9]+)*\]/)) {
        cand = substr(s, RSTART, RLENGTH); s = substr(s, RSTART + RLENGTH) }
      if (cand != "") { gsub(/[][ ]/, "", cand); print cand } }' "$1" \
  | sort -u
}
tokens_run () {  # $1 = seed log
  awk '/^ *TOK\[[0-9]+\] *=/ {
         if (match($0, /\([0-9]+\)/)) {
           printf "%s%s", (n++ ? "," : ""), \
                  substr($0, RSTART + 1, RLENGTH - 2) } }
       END { printf "\n" }' "$1"
}
first_diff () {  # $1 = a, $2 = b
  awk -v a="$1" -v b="$2" 'BEGIN {
    na = split(a, A, ","); nb = split(b, B, ",")
    n = (na > nb ? na : nb)
    for (i = 1; i <= n; i++) if (A[i] != B[i]) {
      printf "step %d: measured %s, record %s\n", i - 1,
             (i <= na ? A[i] : "<none>"), (i <= nb ? B[i] : "<none>"); exit } }'
}

T0=$(date +%s)
if [ -n "${DRYLOG:-}" ]; then
  # acceptance-logic self-check: judge an EXISTING seed log instead of
  # running the binary (never used for a measurement)
  echo "=== DRYLOG   $DRYLOG — NO SIMULATION RAN; judging that log"
  cp "$DRYLOG" "$LOG"; RC=0
else
"$BIN" +seq=$W9/$SEQ.e4 \
       +base=$W9/$BASE \
       +watchdog_ms=$WD \
       ${CSV:+ +timeline=$CSV} > "$LOG" 2>&1
RC=$?
fi
T1=$(date +%s)
echo "=== wall     $((T1 - T0))s   rc=$RC"

FAIL=0
[ "$RC" = 0 ] || FAIL=1
echo "--- verdict lines"
grep -E "^tb_seq_chip:|^  TOK\[|^  ddr beats|^  state:|^  burst:|^  fetch-empty|^SEQ-CHIP|^LAUNCH |^TB_SEQ_CHIP PASS|%Error|Fatal|err_code|WATCHDOG" \
     "$LOG" | sed 's/^/    /'
if grep -q 'readmem file not found' "$LOG"; then
  FAIL=1
  echo "    ROMs NOT LOADED — the run is meaningless (wrong cwd?):"
  grep -m3 'readmem file not found' "$LOG" | sed 's/^/      /'
fi
grep -q "^TB_SEQ_CHIP PASS" "$LOG" || { FAIL=1
  echo "    NO PASS LINE — last 15 lines:"
  tail -15 "$LOG" | sed 's/^/      /'; }

GOTCYC=$(awk '/^TB_SEQ_CHIP PASS/ { for (i = 1; i <= NF; i++)
                                      if ($(i+1) == "cycles") print $i }' \
              "$LOG" | tail -1)
echo "    CYCLES measured  $GOTCYC"
if [ -n "$CYCTODAY" ]; then
  if [ -n "$GOTCYC" ] && [ "$GOTCYC" -lt "$CYCTODAY" ]; then
    echo "    CYCLES BELOW TODAY ($CYCTODAY): delta $((GOTCYC - CYCTODAY))"
  else
    FAIL=1
    echo "    CYCLES NOT BELOW TODAY: measured '$GOTCYC', today $CYCTODAY — STOP"
  fi
fi

if [ -n "$TOKREF" ]; then
  GOT=$(tokens_run "$LOG")
  REF=$(tokens_ref "$TOKREF" "$BASE")
  NREF=$(printf '%s\n' "$REF" | grep -c '[0-9]')
  echo "    TOKENS measured  [$GOT]"
  if [ "$NREF" -eq 0 ]; then
    FAIL=1
    echo "    TOKENS NO RECORD in $(basename "$TOKREF") for $BASE"
  elif [ "$NREF" -gt 1 ]; then
    FAIL=1
    echo "    TOKENS RECORD IS AMBIGUOUS — $NREF sequences for $BASE"
    printf '%s\n' "$REF" | sed 's/^/             [/;s/$/]/'
  elif [ "$GOT" = "$REF" ]; then
    echo "    TOKENS record    [$REF]  ($(basename "$TOKREF"), $BASE)"
    echo "    TOKENS IDENTICAL TO THE SHIPPED RECORD"
  else
    FAIL=1
    echo "    TOKENS record    [$REF]  ($(basename "$TOKREF"), $BASE)"
    echo "    TOKENS DIFFER — $(first_diff "$GOT" "$REF") — STOP"
  fi
fi

if [ "$MODE" = timeline ]; then
  if [ -s "$CSV" ]; then
    echo "    CSV $(wc -c < "$CSV") bytes, $(grep -c '^R,' "$CSV") record rows, sha256 $(sha256sum "$CSV" | cut -d' ' -f1)"
    grep -q '^#END' "$CSV" || { FAIL=1
      echo "    CSV HAS NO #END MARKER — the final block did not run"; }
  else
    FAIL=1
    echo "    CSV MISSING OR EMPTY: $CSV"
  fi
  grep -q '^SEQ_TIMELINE END' "$LOG" || { FAIL=1
    echo "    NO 'SEQ_TIMELINE END' IN THE LOG"; }
  echo "--- SEQ_TIMELINE per-token lines"
  grep -E '^SEQ_TIMELINE (meta|tcyc|union|none|stall) ' "$LOG"
else
  if grep -q '^SEQ_TIMELINE' "$LOG"; then
    FAIL=1
    echo "    THE CONTROL PRINTED A SEQ_TIMELINE BLOCK — the gate leaks"
  else
    echo "    CONTROL: no SEQ_TIMELINE block, as required"
  fi
fi

echo "--- wall $((T1 - T0))s"
if [ "$FAIL" = 0 ]; then echo "SV1_CHIP $SEQ $MODE: PASS"
else echo "SV1_CHIP $SEQ $MODE: FAIL"; fi
exit "$FAIL"
