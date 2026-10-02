#!/usr/bin/env bash
# ref/scripts/regen_gate.sh — 0.8B artifacts must regenerate byte-identical
set -e
cd "$(dirname "$0")/../../tb"
GOLD_SEQ_SHA=a69864d25b6b129a4d6c74b3c78dfcbedf1edce219d32cc05d05bc54f444aaf1  # docs/USAGE.md:629-633
# SCOPE NOTE: this gate covers model_v2_s1 only.  tb/scripts/layer_s1.txt and
# token_s1.txt do NOT regenerate from HEAD's generators — that frozen stage-3/4
# set predates the generators' evolution (verified against a pristine HEAD,
# track-R task R1).  They are frozen replay artifacts, not regen targets; the
# files are unchanged and the sim replay gates that consume them are unaffected.
TMP=$(mktemp -d)
# ~950 MB of weight images land in $TMP; clean up on EVERY exit path, not
# just the happy one (set -e would otherwise leak the dir on any failure).
trap 'rm -rf "$TMP"' EXIT
cd ../ref
# torch-capable interpreter.  /home/cah/.venv/bin/python is the snoke one
# (the frozen artifacts were built with it); on darthplagueis that path does
# not exist, so fall back to the system python3 (also torch 2.6.0+cu124).
# Both were verified to reproduce GOLD_SEQ_SHA (2026-08-12).
MODELPY=${MODELPY:-$([ -x /home/cah/.venv/bin/python ] \
  && echo /home/cah/.venv/bin/python || command -v python3)}
# provenance — makes every gate log self-certifying about what produced it
echo "regen_gate: $(date -Is)  host=$(hostname)"
echo "  MODELPY = $MODELPY"
echo "  python  = $("$MODELPY" -c 'import sys,torch;print(sys.version.split()[0], "torch", torch.__version__)' 2>/dev/null || echo '(torch probe failed)')"
echo "  tree    = $(git rev-parse HEAD 2>/dev/null || echo '(not a git tree)')$(git diff --quiet 2>/dev/null || echo ' +dirty')"
# Track Q V3 added an OPT-IN salience plumb to the production quantizer.  The
# frozen 0.8B artifacts are only reproducible with it OFF, so record it: this
# makes "the gate ran with salience off" self-certifying in every gate log
# instead of something asserted after the fact (evidence/qwen2b/q2/v3/V3.md §6).
echo "  calib   = FABLE5_CALIB_STATS=${FABLE5_CALIB_STATS:-<unset>}"
echo "  gold    = $GOLD_SEQ_SHA"
SEQ_EMIT=$TMP/model_v2_s1.e SEQ_PROFILE=epsnorm \
  "$MODELPY" gen_model_script.py $TMP/model_v2_s1.txt 1 3 --res-scale=8 --allow-clip
# Echo the COMPUTED sha next to the gold one before comparing, so a PASS log
# is self-certifying: the reader sees the hash that was actually produced
# rather than having to trust that the comparison below ran on it.
GOT_SEQ_SHA=$(sha256sum $TMP/model_v2_s1.e.seq | cut -d' ' -f1)
echo "  got     = $GOT_SEQ_SHA"
[ "$GOT_SEQ_SHA" = "$GOLD_SEQ_SHA" ] || { echo REGEN_GATE_FAIL; exit 1; }
cmp $TMP/model_v2_s1.txt ../tb/scripts/model_v2_s1.txt || { echo REGEN_GATE_FAIL_TXT; exit 1; }
echo REGEN_GATE_PASS
