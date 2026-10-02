#!/usr/bin/env bash
# run_g4a_replay.sh — one G4a chip-replay rung: N seeds, N processes, ONE
# binary, with per-seed wall clock.
#
#   bash evidence/qwen9b/g4/run_g4a_replay.sh <stem> [seeds...]
#                                     [--seeds N] [--tokens-ref <doc.md>]
#
# <stem> is the artifact stem inside tb/scripts/w9 WITHOUT the seed, e.g.
# `lay9b_s` or `tok9b_s`; the seeds default to 1 2 3 4.  A stem with no
# trailing `_s` (e.g. `model_9b_s1`) is run once, as itself.  `--seeds N`
# is `1 2 .. N`, the same thing spelled as a count.
#
# `--tokens-ref <doc.md>` (S4) is THE ACCEPTANCE BAR OF THE STATE-SPILL
# AMENDMENT, and it is a comparison against a COMMITTED RECORD rather than
# against anything this run computes.  Each seed's decoded tokens — the
# TB's own `TOK[i] = <hex> (<dec>)` lines, which `tb_seq_chip` has already
# checked against the `.chip` golden — are compared to the token sequence
# <doc.md> records for that artifact.  `evidence/qwen9b/g4/G4A_REPLAY.md`
# §4.1a and §5.3.4 both carry it for `model_9b_s1..s4`, from the OLD
# design (URAM/BRAM layer state); the new design spills that state to DDR
# and must decode the SAME tokens.
#
# The reference is read from the document, not retyped here, and the read
# is strict in both directions:
#   * a stem with NO record in the document is a FAILURE, not a skip —
#     silence must never look like agreement;
#   * a stem the document records TWICE with DIFFERENT sequences is a
#     FAILURE too — the arbiter cannot be a document that contradicts
#     itself.
# A mismatch prints the first divergent step and fails the rung.
#
# WHY A SCRIPT AND NOT THE MAKEFILE TARGET.  `tb/Makefile`'s
# `tb_seq_chip_9b_smoke` runs the same four seeds as four separate processes
# against one binary — which is the rule — but SEQUENTIALLY and without a
# per-seed clock.  The plan wants both a wall-clock number per rung (Task 14
# schedules against it) and the seeds in parallel, so this runs them
# concurrently and prints `SEED <n> ... <secs>s` for each.  It runs the
# binary the Makefile built; it does not build one.
#
# Every seed's full stdout is kept, under $LOGDIR, so a failure is readable
# after the fact rather than only summarised here.
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
# The caller's cwd, kept BEFORE the cd below, so a relative --tokens-ref
# means what the caller typed: the plan's command line runs from
# evidence/qwen9b/g4 and passes a bare `G4A_REPLAY.md`.
PWD0=$PWD
# RUN FROM tb/, not from the repo root.  `rtl/layer_chan.sv` and its
# siblings `$readmemh` their ROMs from `../rtl/roms/...`, a path relative to
# the PROCESS cwd, and every Makefile target runs the binary from `tb/`.
# From the repo root those resolve one directory too high, Verilator prints
# `$readmem file not found` as a WARNING, the ROMs stay X and the run
# produces wrong answers instead of an error.  Measured the hard way.
cd "$ROOT/tb"
STEM=${1:?usage: run_g4a_replay.sh <stem> [seeds...] [--seeds N] [--tokens-ref <doc.md>]}
shift
SEEDS=""
TOKREF=""
while [ $# -gt 0 ]; do
  case "$1" in
    --seeds)      SEEDS="$SEEDS $(seq 1 "${2:?--seeds needs a count}" | tr '\n' ' ')"
                  shift 2 ;;
    --tokens-ref) TOKREF=${2:?--tokens-ref needs a document}; shift 2 ;;
    --*)          echo "unknown option $1" >&2; exit 2 ;;
    *)            SEEDS="$SEEDS $1"; shift ;;
  esac
done
SEEDS=${SEEDS:-1 2 3 4}
if [ -n "$TOKREF" ]; then
  case "$TOKREF" in
    /*) : ;;
    *)  if   [ -f "$PWD0/$TOKREF" ];                        then TOKREF=$PWD0/$TOKREF
        elif [ -f "$ROOT/evidence/qwen9b/g4/$TOKREF" ];     then TOKREF=$ROOT/evidence/qwen9b/g4/$TOKREF
        fi ;;
  esac
  [ -f "$TOKREF" ] || { echo "--tokens-ref: no such document: $TOKREF" >&2
                        exit 2; }
fi
BIN=$ROOT/tb/obj_dir_tb_seq_chip_9b/tb_seq_chip_9b
WD=${WD:-172800000}
# G4a fix round 1: the per-seed stdout is KEPT WITH THE EVIDENCE, not in
# /var/tmp.  The verdict lines are quoted back into the wrapper's log below,
# but the full output of a sim that took hours is worth having, and the TB
# prints ~20 lines on a pass, so it costs nothing to keep.
LOGDIR=${LOGDIR:-$ROOT/evidence/qwen9b/g4/seedlogs_$STEM}
mkdir -p "$LOGDIR"

# S4 fix round 1 (I2): THE DEFAULT LOGDIR CAN BE COMMITTED EVIDENCE.
# For STEM=model_9b_s the default is evidence/qwen9b/g4/seedlogs_model_9b_s,
# whose four per-seed logs are TRACKED — they are Task 11's record, the very
# document `--tokens-ref` reads §4.1a out of and the arbiter of this whole
# amendment.  A re-run of this rung would overwrite the evidence it compares
# itself against.  S4 avoided it by passing LOGDIR=; the script now REFUSES
# instead of relying on that.  An untracked directory (the normal case) does
# not trigger it, and naming one explicitly is always accepted.
if git -C "$ROOT" ls-files --error-unmatch "$LOGDIR" >/dev/null 2>&1; then
  echo "REFUSING: $LOGDIR holds TRACKED evidence; pass LOGDIR= explicitly" >&2
  exit 4
fi

[ -x "$BIN" ] || { echo "MISSING $BIN (make -C tb tb_seq_chip_9b_build)" >&2
                   exit 3; }
echo "=== binary   $BIN"
echo "=== built    $(date -Is -r "$BIN")"
echo "=== stem     $STEM   seeds: $SEEDS"
echo "=== watchdog $WD ms"
echo "=== per-seed stdout under $LOGDIR"
[ -n "$TOKREF" ] && echo "=== tokens-ref $TOKREF"

# --- the token record, read out of the document -----------------------
# Every line that names the artifact in backticks AND carries a bracketed
# list of decimal numbers is a record of that artifact's tokens; they are
# normalised to `a,b,c` and the set of distinct answers must be exactly
# one.  In G4A_REPLAY.md that is §4.1a's SEQ-gate table and §5.3.4's chip
# table, which agree — and the fact that they must agree is the point.
tokens_ref () {  # $1 = document, $2 = artifact name
  awk -v t="$2" '
    index($0, "`" t "`") == 0 { next }
    { s = $0; cand = ""
      while (match(s, /\[[0-9]+(,[ ]*[0-9]+)*\]/)) {
        cand = substr(s, RSTART, RLENGTH); s = substr(s, RSTART + RLENGTH) }
      if (cand != "") { gsub(/[][ ]/, "", cand); print cand } }' "$1" \
  | sort -u
}

# --- the tokens the RTL actually decoded -------------------------------
# `tb_seq_chip` prints one `TOK[i] = <hex> (<dec>) == golden OK` per token
# as it reads seq_unit's OUT FIFO; the decimal in parentheses is the token.
tokens_run () {  # $1 = seed log
  awk '/^ *TOK\[[0-9]+\] *=/ {
         if (match($0, /\([0-9]+\)/)) {
           printf "%s%s", (n++ ? "," : ""), \
                  substr($0, RSTART + 1, RLENGTH - 2) } }
       END { printf "\n" }' "$1"
}

# the first index at which two comma lists differ (1-based), or "" if equal
first_diff () {  # $1 = a, $2 = b
  awk -v a="$1" -v b="$2" 'BEGIN {
    na = split(a, A, ","); nb = split(b, B, ",")
    n = (na > nb ? na : nb)
    for (i = 1; i <= n; i++) if (A[i] != B[i]) {
      printf "step %d: measured %s, record %s\n", i - 1,
             (i <= na ? A[i] : "<none>"), (i <= nb ? B[i] : "<none>"); exit } }'
}

case "$STEM" in
  *_s) TARGETS=""; for s in $SEEDS; do TARGETS="$TARGETS $STEM$s"; done ;;
  *)   TARGETS=" $STEM" ;;
esac

T0=$(date +%s)
for t in $TARGETS; do
  (
    a=$(date +%s)
    "$BIN" +seq=$ROOT/tb/scripts/w9/$t.e4 \
           +base=$ROOT/tb/scripts/w9/$t \
           +watchdog_ms=$WD > "$LOGDIR/$t.log" 2>&1
    rc=$?
    b=$(date +%s)
    echo "SEED $t rc=$rc wall=$((b - a))s"
  ) &
done
wait
T1=$(date +%s)

echo "--- verdict lines, one seed per block ---"
FAIL=0
TOKOK=0
NTOK=0
for t in $TARGETS; do
  echo "--- $t"
  # the launch banner, the cycle/beat summary and the PASS line: everything
  # a reader needs to see that the run did the work, not just that it exited
  grep -E "^tb_seq_chip: launch|^  ddr beats|^  burst:|^TB_SEQ_CHIP PASS|%Error|Fatal|err_code|WATCHDOG" \
       "$LOGDIR/$t.log" | sed 's/^/    /'
  # A MISSING ROM IS A WARNING, AND A WARNING IS NOT ENOUGH.  layer_chan and
  # its siblings $readmemh `../rtl/roms/*.hex` relative to the process cwd;
  # run from the wrong directory Verilator prints "$readmem file not found",
  # leaves every ROM X, and the run answers WRONG rather than failing.  Make
  # it fail here.
  if grep -q 'readmem file not found' "$LOGDIR/$t.log"; then
    FAIL=1
    echo "    ROMs NOT LOADED — the run is meaningless (wrong cwd?):"
    grep -m3 'readmem file not found' "$LOGDIR/$t.log" | sed 's/^/      /'
  fi
  grep -q "^TB_SEQ_CHIP PASS" "$LOGDIR/$t.log" || { FAIL=1
    echo "    NO PASS LINE — last 15 lines:"
    tail -15 "$LOGDIR/$t.log" | sed 's/^/      /'; }
  if [ -n "$TOKREF" ]; then
    NTOK=$((NTOK + 1))
    GOT=$(tokens_run "$LOGDIR/$t.log")
    REF=$(tokens_ref "$TOKREF" "$t")
    NREF=$(printf '%s\n' "$REF" | grep -c '[0-9]')
    echo "    TOKENS measured  [$GOT]"
    if [ "$NREF" -eq 0 ]; then
      FAIL=1
      echo "    TOKENS NO RECORD in $(basename "$TOKREF") for $t — a stem"
      echo "           with no record is a FAILURE, not a skip"
    elif [ "$NREF" -gt 1 ]; then
      FAIL=1
      echo "    TOKENS RECORD IS AMBIGUOUS — $(basename "$TOKREF") carries"
      echo "           $NREF different sequences for $t:"
      printf '%s\n' "$REF" | sed 's/^/             [/;s/$/]/'
    elif [ "$GOT" = "$REF" ]; then
      echo "    TOKENS record    [$REF]  ($(basename "$TOKREF"))"
      echo "    TOKENS IDENTICAL TO G4A"
      TOKOK=$((TOKOK + 1))
    else
      FAIL=1
      echo "    TOKENS record    [$REF]  ($(basename "$TOKREF"))"
      echo "    TOKENS DIFFER FROM G4A — $(first_diff "$GOT" "$REF")"
    fi
  fi
done
echo "--- total wall $((T1 - T0))s for $(echo $TARGETS | wc -w) seed(s) in parallel"
[ -n "$TOKREF" ] && echo "--- TOKENS IDENTICAL TO G4A on $TOKOK of $NTOK seed(s)"
if [ "$FAIL" = 0 ]; then echo "G4A_REPLAY $STEM: ALL PASS"
else echo "G4A_REPLAY $STEM: FAIL"; fi
exit "$FAIL"
