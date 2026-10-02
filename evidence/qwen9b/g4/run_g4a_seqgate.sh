#!/usr/bin/env bash
# run_g4a_seqgate.sh — `ref/seq_model.py --gate` over a list of 9B artifacts.
#
#   bash evidence/qwen9b/g4/run_g4a_seqgate.sh <stem> [<stem> ...]
#
# <stem> is relative to tb/scripts/w9 and names the ARTIFACT (no `.e4`); the
# gate is run on `<stem>.e4` against `--base <stem>`, which is the pair the
# emitter writes.  Every gate must print `SEQ GATE: PASS`; the script fails
# if any does not, and prints the seven verdict lines of each so the log
# carries what was checked and not merely that it exited 0.
#
# PY must be a numpy interpreter (snoke: /home/cah/.venv/bin/python; the
# repo's ref/.venv is a dangling symlink there).
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT/ref"
PY=${PY:-$([ -x /home/cah/.venv/bin/python ] && echo /home/cah/.venv/bin/python \
           || echo "$ROOT/ref/.venv/bin/python")}
W9=$ROOT/tb/scripts/w9
echo "=== interpreter $PY"
FAIL=0
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
for stem in "$@"; do
  echo "--- $stem"
  FABLE5_MODEL=9b FABLE5_RS_F=7 "$PY" seq_model.py \
      --gate "$W9/$stem.e4" --base "$W9/$stem" > "$TMP" 2>&1
  rc=$?
  sed 's/^/    /' "$TMP"
  if [ "$rc" != 0 ] || ! grep -q "^SEQ GATE: PASS" "$TMP"; then
    FAIL=1
    echo "    NO 'SEQ GATE: PASS' for $stem (rc=$rc)"
  fi
done
if [ "$FAIL" = 0 ]; then echo "G4A_SEQGATE: ALL PASS ($# artifact(s))"
else echo "G4A_SEQGATE: FAIL"; fi
exit "$FAIL"
