#!/usr/bin/env bash
# Track L — regression gate for the HOST-MODEL changes this track made to the
# ref/ stack (multi-shard loader, untied LM head, KEY-vs-VALUE head split,
# the w4g128gptq quant, the non-power-of-two normalizer refusal).
#
# The claim under test is NARROW and it is the important one: at 0.8B and 2B
# NOTHING MOVED.  Every change is either behind `VREP > 1` / `n_shards > 1` /
# `not tied` — all false at the two shipped geometries — or a new table entry.
#
#   bash evidence/qwen_next/ladder/run_ref_selftests.sh      # RUN FROM SNOKE
set -u
cd "$(dirname "$0")/../../.."
# LOG is overridable, and it MUST be overridden on a re-run.  This script does
# `: > $LOG` — it TRUNCATES.  The default target, ref_selftests.log, carries
# this campaign's incident record (:515 the 15-of-16 correction, :541 the
# stale-NFS-handle incident) and LADDER.md section 6.10 cites BOTH BY LINE.
# Re-running in place destroys the evidence the gate document points at.  This
# actually happened during the 2026-08-26 review round; the original was
# restored from git and the re-run filed as ref_selftests_reverify.log.
#
#   LOG=evidence/qwen_next/ladder/ref_selftests_reverify.log bash <this>
LOG=${LOG:-evidence/qwen_next/ladder/ref_selftests.log}
UV="$HOME/.local/bin/uv run --no-project --with numpy --with torch --with transformers python"
: > $LOG
echo "host $(hostname)  $(date -Is)" >> $LOG
echo "repo $(git rev-parse --short HEAD)  (working tree: Track L edits)" >> $LOG
RC=0
for T in 0.8b 2b; do
  for F in layer_ref w4a8_ref gptq layer_fixed load_qwen35 perplexity_eval calib_stats; do
    case $F in
      perplexity_eval|calib_stats|gptq) ARGS="--selftest" ;;
      *) ARGS="" ;;          # layer_ref / w4a8_ref / layer_fixed / load_qwen35
    esac                     # run their selftest as __main__
    echo "" >> $LOG
    echo "===== FABLE5_MODEL=$T ref/$F.py $ARGS =====" >> $LOG
    FABLE5_MODEL=$T OMP_NUM_THREADS=3 nice -n 15 $UV ref/$F.py $ARGS >> $LOG 2>&1
    r=$?
    echo "----- exit $r" >> $LOG
    [ $r -ne 0 ] && RC=1
  done
done
echo "" >> $LOG
echo "OVERALL exit $RC" >> $LOG
echo "selftests done: exit $RC"
