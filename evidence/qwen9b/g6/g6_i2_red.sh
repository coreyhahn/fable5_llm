#!/usr/bin/env bash
# g6_i2_red.sh — the RED half of round-3 I-1 and I-2, at 0.8B (the frozen
# --nch 1 selection, which is what `--selftest` runs).
#
#  [1] the frozen footprint at 4662b06     — the numbers of record
#  [2] the frozen footprint at 47e07cd     — fix round 2's 8x pool
#  [3] the NEW selftest cases against 47e07cd's implementation: this
#      script SPLICES this tree's two selftest regions (the pos_mode
#      cases and the whole of case [23]) into `git show
#      47e07cd:sw/chat_seq.py`, runs it INSIDE THE 47e07cd WORKTREE — so
#      it imports that tree's ref/seq_chat.py and its T_MAX, not this
#      one's — and deletes it.  Every RED->GREEN line must FAIL and name
#      its own reason.  `--template` points back at the real artifact
#      because the worktree does not carry the gitignored w4 tree.
#
# The two trees are read from git WORKTREES, which this script does NOT
# create and which were REMOVED after the run (they are big).  To re-run it:
#
#   git worktree add --detach ../fable5_llm_wt_i2_4662b06 4662b06
#   git worktree add --detach ../fable5_llm_wt_i2_47e07cd 47e07cd
#   cp evidence/qwen9b/g6/g6_frozen_footprint.py \
#      ../fable5_llm_wt_i2_*/evidence/qwen9b/g6/
#
# --template points back at the real (gitignored) w4 artifact, which is the
# same file for all three trees.
# NO BOARD, NO LOCK.  Run ON SNOKE through evidence/qwen9b/run.sh.
set -u
cd "$(dirname "$0")/../../.."
PY=/home/cah/.venv/bin/python
TPL=/home/cah/r2d2/code/fpga/fable5_llm/tb/scripts/w4/model_v2_s1.e
WT=/home/cah/r2d2/code/fpga
RED=$WT/fable5_llm_wt_i2_47e07cd/sw/.red_chat_seq_47e07cd.py

for T in 4662b06 47e07cd; do
  echo "########## the frozen --nch 1 footprint at $T"
  ( cd $WT/fable5_llm_wt_i2_$T \
    && $PY -u evidence/qwen9b/g6/g6_frozen_footprint.py --template $TPL )
  echo "   rc=$?"; echo
done

echo "########## splicing this tree's NEW selftest cases into 47e07cd"
$PY - "$RED" <<'PYEOF'
import subprocess
import sys
new = open("sw/chat_seq.py").read()
old = subprocess.check_output(["git", "show", "47e07cd:sw/chat_seq.py"]).decode()
A_END = '        check("xrf is refused when it cannot reach --max-ctx", True)\n'
C_END = '\n    log(f"  chat_seq selftest: {npass} passed'


def region(txt, start, end, keep_end=True):
    i = txt.index(start)
    j = txt.index(end, i)
    return i, (j + len(end)) if keep_end else j


i0, i1 = region(new, "    # tag=/cap= are named so these three read", A_END)
a_new = new[i0:i1]
j0, j1 = region(old, '    check("auto pos_mode picks xrf when --max-ctx fits'
                     ' the signed XRF",', A_END)
sp = old[:j0] + a_new + old[j1:]
k0, k1 = region(new, "    # ---------------- 23. E:", C_END, keep_end=False)
c_new = new[k0:k1]
m0, m1 = region(sp, "    # ---------------- 23. E:", C_END, keep_end=False)
sp = sp[:m0] + c_new + sp[m1:]
open(sys.argv[1], "w").write(sp)
print(f"  spliced {len(a_new.splitlines())} + {len(c_new.splitlines())} "
      f"selftest lines into 47e07cd's {len(old.splitlines())}-line file "
      f"-> {len(sp.splitlines())} lines")
PYEOF
echo "  the spliced file's IMPLEMENTATION is 47e07cd's:"
grep -n "^T_MAX = \|^POS_MODE_LDC_ONLY" $RED
grep -n "if tag in POS_MODE_LDC_ONLY" $RED
echo "  ...and it imports 47e07cd's ref/seq_chat.py:"
grep -n "^T_MAX = " $WT/fable5_llm_wt_i2_47e07cd/ref/seq_chat.py
echo

echo "########## the NEW cases against 47e07cd's implementation (RED)"
$PY -u $RED --selftest --template $TPL 2>&1 | grep -E "^  \[2[0-9]|FAIL|passed," | tail -40
echo "   rc=${PIPESTATUS[0]}"
rm -f $RED
echo "  removed $RED: $([ -e $RED ] && echo STILL THERE || echo gone)"
