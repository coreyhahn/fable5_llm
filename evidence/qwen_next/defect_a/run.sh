#!/usr/bin/env bash
# run.sh — Track F (defect A) evidence, end to end.  Runs on snoke, no board.
#
#   evidence/qwen_next/defect_a/run.sh
#
# Produces, beside this script:
#   selftest_08b.log     ref/seq_chat.py --selftest            (FABLE5_MODEL unset = 0.8b)
#   embgeom_08b.log      ref/seq_chat.py --emb-geom            at H=1024
#   embgeom_2b.log       ref/seq_chat.py --emb-geom            at H=2048
#   damage_08b.log       the PRE-FIX reader vs the regression  at H=1024 (must PASS)
#   damage_2b.log        the PRE-FIX reader vs the regression  at H=2048 (must FAIL)
#   damage_4b.log        the PRE-FIX reader vs the regression  at H=2560 (must FAIL)
#   damage_9b.log        the PRE-FIX reader vs the regression  at H=4096 (must FAIL)
#   embgeom_4b.log       ref/seq_chat.py --emb-geom            at H=2560
#   embgeom_9b.log       ref/seq_chat.py --emb-geom            at H=4096
#   demo_2b.log          before/after on the real 2B artifact vs the bf16 checkpoint
#   sibling_2b.log       the ref/ twin of defect B in layer_fixed_greedy (fixed here)
#   defect_b_2b.log      defect B is LOUD (not fixed here — migration work item)
#   a1_08b.log           gate A1 (uses _artifacts() -> the patched reader)
#   a3_anchor_08b.log    gate A3's anchor (layer_fixed_greedy, both fixed sites)
set -u
D=$(cd "$(dirname "$0")" && pwd)
R=$(cd "$D"/../../.. && pwd)
# ref/.venv is NFS-shared but its interpreter symlink only resolves on the
# host that made it; /home/cah/.venv is the one every 2B-campaign ref/ run
# used on snoke (evidence/qwen2b/rc/t4_audits.sh:12).
PY=${FABLE5_PY:-}
if [ -z "$PY" ]; then
  for c in "$R/ref/.venv/bin/python" /home/cah/.venv/bin/python \
           "$R/sw/.venv/bin/python" python3; do
    if "$c" -c 'import numpy' >/dev/null 2>&1; then PY=$c; break; fi
  done
fi
rc=0
run() {  # run <logname> <env-assignments...> -- cmd...
  local log="$1"; shift
  echo "### $log"
  ( cd "$R/ref" && env "$@" ) >"$D/$log" 2>&1
  local r=$?
  echo "###   exit $r  -> $log"
  [ $r -eq 0 ] || rc=1
  return 0
}

echo "host $(hostname)   $(date -Is)"
echo "git  $(cd "$R" && git rev-parse --short HEAD)"
echo "py   $PY  ($($PY -c 'import sys,numpy;print(sys.version.split()[0], "numpy", numpy.__version__)'))"
# Self-disclosing dirty tree (review F3): these logs are only reproducible
# from the committed tree if nothing else is modified.  This repo is shared
# with concurrent tracks, so record exactly what was uncommitted at run time
# — a check count that cannot be reproduced from the stated sha is otherwise
# indistinguishable from a wrong count.
echo "--- git status --porcelain at run time:"
(cd "$R" && git status --porcelain) | sed 's/^/     /'
echo "     (end)"
echo

run selftest_08b.log  "$PY" -u "$R/ref/seq_chat.py" --selftest
run embgeom_08b.log   FABLE5_MODEL=0.8b "$PY" -u "$R/ref/seq_chat.py" --emb-geom
run embgeom_2b.log    FABLE5_MODEL=2b   "$PY" -u "$R/ref/seq_chat.py" --emb-geom
run embgeom_4b.log    FABLE5_MODEL=4b   "$PY" -u "$R/ref/seq_chat.py" --emb-geom
run embgeom_9b.log    FABLE5_MODEL=9b   "$PY" -u "$R/ref/seq_chat.py" --emb-geom
run damage_08b.log    FABLE5_MODEL=0.8b "$PY" -u "$D/damage_test.py"
run damage_2b.log     FABLE5_MODEL=2b   "$PY" -u "$D/damage_test.py"
run damage_4b.log     FABLE5_MODEL=4b   "$PY" -u "$D/damage_test.py"
run damage_9b.log     FABLE5_MODEL=9b   "$PY" -u "$D/damage_test.py"
run demo_2b.log       FABLE5_MODEL=2b   "$PY" -u "$D/demo_2b.py"
run sibling_2b.log    FABLE5_MODEL=2b   "$PY" -u "$D/sibling_2b_probe.py"
run defect_b_2b.log   FABLE5_MODEL=2b   "$PY" -u "$D/defect_b_probe.py"
run a1_08b.log        "$PY" -u "$R/ref/seq_chat.py" --a1
run a3_anchor_08b.log "$PY" -u "$D/a3_anchor.py"

echo
echo "RUN: $([ $rc -eq 0 ] && echo PASS || echo FAIL)"
exit $rc
