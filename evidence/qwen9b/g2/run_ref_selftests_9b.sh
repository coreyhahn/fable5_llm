#!/usr/bin/env bash
# G2 / D-TOL — the ref/ selftest sweep at THREE tags: 0.8b, 2b, 9b.
#
# FORK of evidence/qwen_next/ladder/run_ref_selftests.sh, which is Track L's
# COMMITTED EVIDENCE and must not be edited (its default log is cited by line
# from LADDER.md section 6.10).  This copy adds the 9b tag, which is the
# geometry this campaign migrates to, and defaults its log into this gate's
# own directory so nothing Track L wrote can be truncated.
#
# The claim under test is the same narrow one the ladder runner makes, one tag
# wider: at 0.8B and 2B NOTHING MOVED, and at 9B nothing refuses.
#
#   bash evidence/qwen9b/g2/run_ref_selftests_9b.sh          # RUN FROM SNOKE
#   LOG=<path> TAGS="9b" bash evidence/qwen9b/g2/run_ref_selftests_9b.sh
#
# Both LOG and TAGS are overridable; this script TRUNCATES $LOG, so a re-run
# that must not destroy a cited log needs a new LOG.  (Global constraint:
# "Never re-run a committed evidence script in place when a gate doc cites its
# log by line.")
set -u
cd "$(dirname "$0")/../../.."
LOG=${LOG:-evidence/qwen9b/g2/ref_selftests_dtol.log}
TAGS=${TAGS:-"0.8b 2b 9b"}
# MODULES is overridable so a single module can be re-measured on an OLD tree
# without paying for the whole 21-invocation sweep -- which is how D_TOL.md's
# pre-fix 9B row and its at-HEAD confirmation row are regenerated.  The default
# is the ladder runner's full list, in its order.
MODULES=${MODULES:-"layer_ref w4a8_ref gptq layer_fixed load_qwen35 perplexity_eval calib_stats"}
THREADS=${THREADS:-3}
UV="$HOME/.local/bin/uv run --no-project --with numpy --with torch --with transformers python"
: > "$LOG"
# TREE is overridable because this sweep is also run on a staging tree
# unpacked from `git archive HEAD` (see D_TOL.md): Task 1 (G1) is editing
# ref/layer_fixed.py in the shared working tree CONCURRENTLY, so a sweep run
# there could not be attributed to this task's change.  The md5 of the file
# under test is recorded either way, which is the claim that actually matters.
TREE=${TREE:-"$( (git rev-parse --short HEAD 2>/dev/null || echo unknown) )$( (git diff --quiet -- ref 2>/dev/null || echo '+dirty(ref)') )"}
{
  echo "=== host: $(hostname)"
  echo "=== date: $(date -Is)"
  echo "=== tree: $TREE"
  echo "=== cmd:  bash evidence/qwen9b/g2/run_ref_selftests_9b.sh"
  echo "=== venv: uv run --no-project --with numpy --with torch --with transformers"
  echo "=== tags: $TAGS   modules: $MODULES   OMP_NUM_THREADS=$THREADS"
  echo "=== md5:  $(md5sum ref/layer_fixed.py ref/fixedpoint.py ref/w4a8_ref.py \
                            ref/layer_ref.py | tr '\n' ' ')"
} >> "$LOG"
RC=0
for T in $TAGS; do
  for F in $MODULES; do
    case $F in
      perplexity_eval|calib_stats|gptq) ARGS="--selftest" ;;
      *) ARGS="" ;;          # layer_ref / w4a8_ref / layer_fixed / load_qwen35
    esac                     # run their selftest as __main__
    echo "" >> "$LOG"
    echo "===== FABLE5_MODEL=$T ref/$F.py $ARGS =====" >> "$LOG"
    FABLE5_MODEL=$T OMP_NUM_THREADS=$THREADS nice -n 15 $UV ref/$F.py $ARGS >> "$LOG" 2>&1
    r=$?
    echo "----- exit $r" >> "$LOG"
    [ $r -ne 0 ] && RC=1
  done
done
echo "" >> "$LOG"
echo "OVERALL exit $RC" >> "$LOG"
echo "selftests done: exit $RC  ($LOG)"
exit $RC
