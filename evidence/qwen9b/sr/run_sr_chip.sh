#!/usr/bin/env bash
# run_sr_chip.sh — the SEQUENCER RTL ROUND (Task SR5a onward): ONE chip-TB run
# on the round's own binary.  A copy of evidence/qwen9b/ov/run_sv1_chip.sh
# (itself evidence/qwen9b/bn/run_bn_timeline.sh's discipline: same `cd tb`,
# same never-overwrite refusal, same ROM-not-loaded check, same token read
# OUT OF A COMMITTED DOCUMENT with the no-record and ambiguous-record
# failures, same control/timeline split, same +seq/+base stem split, same
# token record read under the BASE stem from evidence/qwen9b/s4/S4_REPLAY.md),
# changed in four places only:
#   * the binary is tb/obj_dir_seq_chip_sr<K>/tb_seq_chip_9b_sr<K> (K from the
#     environment, default 5), built by evidence/qwen9b/sr/sr_build.sh from a
#     snapshot of a named commit;
#   * the seed log is a FLAT file evidence/qwen9b/sr/sr<K>_seed_<seq>_<mode>.log
#     (not a seedlogs_ directory: evidence/qwen9b/sr/sr_run.sh excludes only
#     untracked *.log files directly under evidence/qwen9b/sr/ from its dirty
#     stamp, so a directory would stamp every parallel sibling run +dirty);
#   * `--cycles-equal N` (new): FAILS on ANY difference from N — the
#     backward-compatibility rung (a shipped stream on new RTL must run
#     cycle-identical) and the S1-B control (SV1's count, exactly);
#   * `--cycles-today N` is kept as SV1 wrote it (FAILS unless below N); the
#     two are mutually exclusive.
#
#   bash evidence/qwen9b/sr/run_sr_chip.sh <seq-stem> <base-stem> <mode> \
#        [--csv <path>] [--cycles-equal <N> | --cycles-today <N>] \
#        [--tokens-ref <doc.md>]
#
# Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh, detached.
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
PWD0=$PWD
cd "$ROOT/tb"

SEQ=${1:?usage: run_sr_chip.sh <seq-stem> <base-stem> <mode> [...]}
BASE=${2:?usage}
MODE=${3:?usage}
shift 3
CSV=""
CYCTODAY=""
CYCEQ=""
TOKREF=""; PLUS=""; LTAG=""   # R3-9a: --plusarg <+arg> (repeatable) and --logtag <t>, both default off
while [ $# -gt 0 ]; do
  case "$1" in
    --csv)          CSV=${2:?--csv needs a path};              shift 2 ;;
    --cycles-today) CYCTODAY=${2:?--cycles-today needs a number}; shift 2 ;;
    --cycles-equal) CYCEQ=${2:?--cycles-equal needs a number};    shift 2 ;;
    --tokens-ref)   TOKREF=${2:?--tokens-ref needs a document}; shift 2 ;; --plusarg) PLUS="$PLUS ${2:?--plusarg needs +arg}"; shift 2 ;; --logtag) LTAG="_${2:?--logtag needs a tag}"; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
if [ -n "$CYCTODAY" ] && [ -n "$CYCEQ" ]; then
  echo "--cycles-today and --cycles-equal are mutually exclusive" >&2; exit 2
fi
if [ -n "$CYCEQ" ] && ! [[ "$CYCEQ" =~ ^[0-9]+$ ]]; then
  echo "--cycles-equal: not a number: $CYCEQ" >&2; exit 2
fi
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

K=${K:-5}
BIN=$ROOT/tb/obj_dir_seq_chip_sr$K/tb_seq_chip_9b_sr$K
WD=${WD:-172800000}
LOGDIR=${LOGDIR:-$ROOT/evidence/qwen9b/sr}
mkdir -p "$LOGDIR"
if git -C "$ROOT" ls-files --error-unmatch "$LOGDIR/sr${K}_seed_${SEQ}_$MODE$LTAG.log" >/dev/null 2>&1 \
   || [ -e "$LOGDIR/sr${K}_seed_${SEQ}_$MODE$LTAG.log" ]; then
  echo "REFUSING: $LOGDIR/sr${K}_seed_${SEQ}_$MODE$LTAG.log exists — never overwrite" >&2
  exit 4
fi
[ -x "$BIN" ] || { echo "MISSING $BIN (evidence/qwen9b/sr/sr_build.sh)" >&2
                   exit 3; }
if [ -n "$CSV" ] && [ -e "$CSV" ]; then
  echo "REFUSING: $CSV exists — pick a new name" >&2
  exit 2
fi
W9=$ROOT/tb/scripts/w9
for f in "$W9/$SEQ.e4.seq" "$W9/$SEQ.e4.seqdata.bin" "$W9/$SEQ.e4.chip"; do
  [ -f "$f" ] || { echo "MISSING $f" >&2; exit 3; }
done
LOG=$LOGDIR/sr${K}_seed_${SEQ}_$MODE$LTAG.log

echo "=== binary   $BIN"
echo "=== built    $(date -Is -r "$BIN")  sha256 $(sha256sum "$BIN" | cut -d' ' -f1)"
echo "=== seq      $W9/$SEQ.e4  (.seq sha256 $(sha256sum "$W9/$SEQ.e4.seq" | cut -c1-16), .chip sha256 $(sha256sum "$W9/$SEQ.e4.chip" | cut -c1-16))"
echo "=== base     $W9/$BASE   mode: $MODE"
echo "=== watchdog $WD ms"
echo "=== stdout   $LOG"; [ -z "$PLUS" ] || echo "=== plusargs$PLUS"
[ -n "$CSV" ]      && echo "=== csv      $CSV"
[ -n "$CYCTODAY" ] && echo "=== cycles-today $CYCTODAY"
[ -n "$CYCEQ" ]    && echo "=== cycles-equal $CYCEQ"
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
       ${CSV:+ +timeline=$CSV} $PLUS > "$LOG" 2>&1
RC=$?
fi
T1=$(date +%s)
echo "=== wall     $((T1 - T0))s   rc=$RC"

FAIL=0
[ "$RC" = 0 ] || FAIL=1
echo "--- verdict lines"
grep -E "^tb_seq_chip:|^  TOK\[|^  ddr beats|^  state:|^  burst:|^  fetch-empty|^SEQ-CHIP|^LAUNCH |^TB_SEQ_CHIP PASS|%Error|Fatal|err_code|WATCHDOG" \
     "$LOG" | sed 's/^/    /'; [ -z "$PLUS" ] || grep -E "SEQ_CAPS|^tb_seq_chip R3|^tb_seq_chip: \+xp_hold" "$LOG" | sed "s/^/    /"
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

if [ -n "$CYCEQ" ]; then
  if [ -n "$GOTCYC" ] && [ "$GOTCYC" = "$CYCEQ" ]; then
    echo "    CYCLES IDENTICAL TO THE REFERENCE ($CYCEQ)"
  else
    FAIL=1
    if [ -n "$GOTCYC" ]; then
      echo "    CYCLES DIFFER: measured $GOTCYC, reference $CYCEQ, delta $((GOTCYC - CYCEQ)) — STOP"
    else
      echo "    CYCLES DIFFER: no cycle count measured, reference $CYCEQ — STOP"
    fi
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
if [ "$FAIL" = 0 ]; then echo "SR_CHIP $SEQ $MODE: PASS"
else echo "SR_CHIP $SEQ $MODE: FAIL"; fi
exit "$FAIL"
