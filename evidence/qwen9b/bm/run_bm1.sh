#!/usr/bin/env bash
# run_bm1.sh — ONE run of the BM1-T1 counter gate on the chip testbench
# (spec docs/superpowers/specs/2026-09-24-board-idle-counters-design.md §3).
# A COPY of evidence/qwen9b/bn/run_bn_timeline.sh (the census runner), with
# its discipline kept whole — cd tb, refuse a tracked LOGDIR, refuse an
# existing CSV, a missing ROM is a failure, the cycle count and the tokens
# compared against committed records and a mismatch FAILS — retargeted to
# the BM1 binary and given the BM1 modes:
#
#   bash evidence/qwen9b/bm/run_bm1.sh <stem> <mode> \
#        [--expect <file>] [--csv <path>] [--cycles-ref <N>] [--tokens-ref <doc.md>]
#
#     <stem>   the artifact stem inside tb/scripts/w9, e.g. `model_9b_s1`
#     <mode>   `control`  — NO BM1 plusarg: the counters are in the RTL but
#                           nothing reads them; must print no BM1 line
#              `bm`       — +bm [+bm_expect=<file>]: read the block after
#                           HALT, check it; must print `BM1 L0 PASS`
#              `bmtl`     — `bm` AND +timeline=<csv> (the census instrument)
#
# ---- the census runner's own header follows, kept verbatim ----
#
# WHY A SECOND RUNNER AND NOT `evidence/qwen9b/g4/run_g4a_replay.sh`.
# That runner is Task 11's / S4's rung and its default LOGDIR holds TRACKED
# evidence; it also has no notion of the plusarg this task turns on and off,
# and no notion of an ACCEPTANCE ON THE CYCLE COUNT.  BN1's whole control is
# that the SAME binary, run twice, reproduces
# `evidence/qwen9b/s4/031_full_model_4seeds.log`'s 196,706,821 cycles and
# its six tokens with the instrument on and with it off — so the cycle
# count is a first-class argument here and a MISMATCH IS A FAILURE, not a
# line in the output for a reader to notice.  Everything else is
# run_g4a_replay.sh, deliberately: the same `cd tb` (the ROMs are
# `$readmemh`'d relative to the process cwd and a wrong cwd makes the run
# answer WRONG rather than fail — see that script's note), the same refusal
# to write into a TRACKED log directory, the same "a missing ROM is a
# warning and a warning is not enough" check, the same token comparison
# against a COMMITTED record read out of a document rather than retyped.
#
# It runs the binary the Makefile built (`make -C tb tb_seq_chip_9b_tl_build`,
# obj_dir_seq_chip_tl); it does not build one.  Run ON SNOKE, through
# `evidence/qwen9b/run.sh`, with FABLE5_MODEL=9b.
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
PWD0=$PWD
cd "$ROOT/tb"

STEM=${1:?usage: run_bm1.sh <stem> <mode> [--expect f] [--csv p] [--cycles-ref N] [--tokens-ref doc]}
MODE=${2:?usage: run_bm1.sh <stem> <mode> ...}
shift 2
CSV=""
EXPECT=""
CYCREF=""
TOKREF=""
while [ $# -gt 0 ]; do
  case "$1" in
    --expect)     EXPECT=${2:?--expect needs a file};   shift 2 ;;
    --csv)        CSV=${2:?--csv needs a path};        shift 2 ;;
    --cycles-ref) CYCREF=${2:?--cycles-ref needs a number}; shift 2 ;;
    --tokens-ref) TOKREF=${2:?--tokens-ref needs a document}; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
case "$MODE" in
  control)  { [ -n "$CSV" ] || [ -n "$EXPECT" ]; } && { echo "control mode takes no --csv/--expect" >&2; exit 2; } ;;
  bm)       [ -n "$CSV" ] && { echo "bm mode takes no --csv (use bmtl)" >&2; exit 2; } ;;
  bmtl)     [ -n "$CSV" ] || { echo "bmtl mode needs --csv" >&2; exit 2; } ;;
  *) echo "mode must be 'control', 'bm' or 'bmtl'" >&2; exit 2 ;;
esac
if [ -n "$EXPECT" ]; then
  case "$EXPECT" in /*) : ;; *) EXPECT=$ROOT/$EXPECT ;; esac
  [ -f "$EXPECT" ] || { echo "--expect: no such file: $EXPECT" >&2; exit 2; }
fi
if [ -n "$TOKREF" ]; then
  case "$TOKREF" in
    /*) : ;;
    *)  if   [ -f "$PWD0/$TOKREF" ];                    then TOKREF=$PWD0/$TOKREF
        elif [ -f "$ROOT/$TOKREF" ];                    then TOKREF=$ROOT/$TOKREF
        fi ;;
  esac
  [ -f "$TOKREF" ] || { echo "--tokens-ref: no such document: $TOKREF" >&2
                        exit 2; }
fi

BIN=$ROOT/tb/obj_dir_seq_chip_bm1/tb_seq_chip_9b_bm1
WD=${WD:-172800000}
LOGDIR=${LOGDIR:-$ROOT/evidence/qwen9b/bm/seedlogs_${STEM}_${MODE}}
mkdir -p "$LOGDIR"
# S4's I2 rule: a run NEVER writes into a directory git tracks.
if git -C "$ROOT" ls-files --error-unmatch "$LOGDIR" >/dev/null 2>&1; then
  echo "REFUSING: $LOGDIR holds TRACKED evidence; pass LOGDIR= explicitly" >&2
  exit 4
fi
[ -x "$BIN" ] || { echo "MISSING $BIN (make -C tb tb_seq_chip_9b_bm1_build)" >&2
                   exit 3; }
# A CSV that already exists is refused for the same reason run.sh refuses a
# log that exists: a committed table cited by line is destroyed by a re-run
# in place.
if [ -n "$CSV" ] && [ -e "$CSV" ]; then
  echo "REFUSING: $CSV exists — pick a new name" >&2
  exit 2
fi

echo "=== binary   $BIN"
echo "=== built    $(date -Is -r "$BIN")"
echo "=== stem     $STEM   mode: $MODE"
echo "=== watchdog $WD ms"
echo "=== stdout   $LOGDIR/$STEM.log"
[ -n "$CSV" ]    && echo "=== csv      $CSV"
[ -n "$EXPECT" ] && echo "=== expect   $EXPECT (sha256 $(sha256sum < "$EXPECT" | cut -c1-16)…)"
[ -n "$CYCREF" ] && echo "=== cycles-ref $CYCREF"
[ -n "$TOKREF" ] && echo "=== tokens-ref $TOKREF"

# --- the token record, read out of the document (run_g4a_replay.sh's rule:
# a stem with NO record is a FAILURE, and a stem recorded TWICE with
# DIFFERENT sequences is a FAILURE too) -------------------------------
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
"$BIN" +seq=$ROOT/tb/scripts/w9/$STEM.e4 \
       +base=$ROOT/tb/scripts/w9/$STEM \
       +watchdog_ms=$WD \
       ${CSV:+ +timeline=$CSV} \
       $( [ "$MODE" != control ] && echo +bm ) \
       ${EXPECT:+ +bm_expect=$EXPECT} > "$LOGDIR/$STEM.log" 2>&1
RC=$?
T1=$(date +%s)
echo "=== wall     $((T1 - T0))s   rc=$RC"

FAIL=0
[ "$RC" = 0 ] || FAIL=1
echo "--- verdict lines"
grep -E "^tb_seq_chip:|^  ddr beats|^  state:|^  burst:|^  fetch-empty|^SEQ-CHIP|^LAUNCH |^TB_SEQ_CHIP PASS|%Error|Fatal|err_code|WATCHDOG" \
     "$LOGDIR/$STEM.log" | sed 's/^/    /'
if grep -q 'readmem file not found' "$LOGDIR/$STEM.log"; then
  FAIL=1
  echo "    ROMs NOT LOADED — the run is meaningless (wrong cwd?):"
  grep -m3 'readmem file not found' "$LOGDIR/$STEM.log" | sed 's/^/      /'
fi
grep -q "^TB_SEQ_CHIP PASS" "$LOGDIR/$STEM.log" || { FAIL=1
  echo "    NO PASS LINE — last 15 lines:"
  tail -15 "$LOGDIR/$STEM.log" | sed 's/^/      /'; }

# --- THE CONTROL: the cycle count, against the committed record ---------
GOTCYC=$(awk '/^TB_SEQ_CHIP PASS/ { for (i = 1; i <= NF; i++)
                                      if ($(i+1) == "cycles") print $i }' \
              "$LOGDIR/$STEM.log" | tail -1)
echo "    CYCLES measured  $GOTCYC"
if [ -n "$CYCREF" ]; then
  if [ "$GOTCYC" = "$CYCREF" ]; then
    echo "    CYCLES IDENTICAL TO THE REFERENCE ($CYCREF)"
  else
    FAIL=1
    echo "    CYCLES DIFFER FROM THE REFERENCE: measured $GOTCYC, want $CYCREF"
    echo "           the instrument is PERTURBING the DUT — stop and report"
  fi
fi

# --- and the tokens, against the committed record ----------------------
if [ -n "$TOKREF" ]; then
  GOT=$(tokens_run "$LOGDIR/$STEM.log")
  REF=$(tokens_ref "$TOKREF" "$STEM")
  NREF=$(printf '%s\n' "$REF" | grep -c '[0-9]')
  echo "    TOKENS measured  [$GOT]"
  if [ "$NREF" -eq 0 ]; then
    FAIL=1
    echo "    TOKENS NO RECORD in $(basename "$TOKREF") for $STEM — a stem"
    echo "           with no record is a FAILURE, not a skip"
  elif [ "$NREF" -gt 1 ]; then
    FAIL=1
    echo "    TOKENS RECORD IS AMBIGUOUS — $(basename "$TOKREF") carries"
    echo "           $NREF different sequences for $STEM:"
    printf '%s\n' "$REF" | sed 's/^/             [/;s/$/]/'
  elif [ "$GOT" = "$REF" ]; then
    echo "    TOKENS record    [$REF]  ($(basename "$TOKREF"))"
    echo "    TOKENS IDENTICAL TO THE RECORD"
  else
    FAIL=1
    echo "    TOKENS record    [$REF]  ($(basename "$TOKREF"))"
    echo "    TOKENS DIFFER — $(first_diff "$GOT" "$REF")"
  fi
fi

if [ "$MODE" = bmtl ]; then
  if [ -s "$CSV" ]; then
    echo "    CSV $(wc -c < "$CSV") bytes, $(grep -c '^R,' "$CSV") record rows, $(grep -c '^S,' "$CSV") signature rows"
    grep -q '^#END' "$CSV" || { FAIL=1
      echo "    CSV HAS NO #END MARKER — the final block did not run"; }
  else
    FAIL=1
    echo "    CSV MISSING OR EMPTY: $CSV"
  fi
  # the log must carry the headline on its own (deliverable 1)
  grep -q '^SEQ_TIMELINE END' "$LOGDIR/$STEM.log" || { FAIL=1
    echo "    NO 'SEQ_TIMELINE END' IN THE LOG — the headline block is missing"; }
  echo "--- SEQ_TIMELINE block ($(grep -c '^SEQ_TIMELINE' "$LOGDIR/$STEM.log") lines)"
  grep '^SEQ_TIMELINE' "$LOGDIR/$STEM.log"
else
  if grep -q '^SEQ_TIMELINE' "$LOGDIR/$STEM.log"; then
    FAIL=1
    echo "    THE CONTROL PRINTED A SEQ_TIMELINE BLOCK — the gate leaks"
  else
    echo "    no SEQ_TIMELINE block, as required (no +timeline)"
  fi
fi

# --- BM1: the counter block ------------------------------------------
if [ "$MODE" = control ]; then
  if grep -q "^BM1 \|BM1 counters ON" "$LOGDIR/$STEM.log"; then
    FAIL=1
    echo "    THE CONTROL PRINTED BM1 LINES — the +bm gate leaks"
  else
    echo "    CONTROL: no BM1 line, as required (the counters exist, nothing read them)"
  fi
else
  echo "--- BM1 block ($(grep -c "^BM1 " "$LOGDIR/$STEM.log") lines)"
  grep "^BM1 \|BM1 counters ON" "$LOGDIR/$STEM.log" | sed 's/^/    /'
  if grep -q "^BM1 L0 PASS" "$LOGDIR/$STEM.log" \
     && ! grep -q "^BM1 .*MISMATCH" "$LOGDIR/$STEM.log"; then
    echo "    BM1 COUNTERS: every check OK"
  else
    FAIL=1
    echo "    BM1 COUNTERS: FAIL (no 'BM1 L0 PASS', or a MISMATCH line)"
  fi
  if [ -n "$EXPECT" ] && ! grep -q "^BM1 L0 EXP_" "$LOGDIR/$STEM.log"; then
    FAIL=1
    echo "    --expect GIVEN BUT NO EXP_ LINE PRINTED"
  fi
fi

echo "--- wall $((T1 - T0))s"
if [ "$FAIL" = 0 ]; then echo "BM1_RUN $STEM $MODE: PASS"
else echo "BM1_RUN $STEM $MODE: FAIL"; fi
exit "$FAIL"
