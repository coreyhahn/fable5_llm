#!/usr/bin/env bash
# 162: the ONE numeric difference between the trees 106 and 149 ran on.
# Read-only: git plumbing, two `git show` greps and two file reads.  No
# model, no board, no DDR byte.  Declared as a new instrument of Task
# 15-D round 2; it writes nothing.
set -u
cd "$(dirname "$0")/../../.."
A=2762662   # the tree 106 ran on (its own === tree: line)
B=8639813   # the tree 149 ran on
echo "A = $A  ($(git log -1 --format='%ad  %s' --date=iso $A))"
echo "B = $B  ($(git log -1 --format='%ad  %s' --date=iso $B))"
echo
echo "---- the replay's execution path, A vs B (EMPTY = byte-identical) ----"
git diff --stat $A $B -- ref/gen_layer_script.py ref/seq_model.py \
    ref/fixedpoint.py ref/w4a8_ref.py ref/layer_ref.py
echo "---- (end; no line above means no file in that list changed) ----"
echo
echo "---- ref/ files that DID change ----"
git diff --stat $A $B -- ref/
echo
echo "---- RS_F at tree A ----"
git show $A:ref/layer_fixed.py | grep -n '^RS_F = '
echo "---- RS_F at tree B ----"
git show $B:ref/layer_fixed.py | grep -n '^RS_F = \|^RS_F_BY_TAG = \|^_RS_F_LAW ='
echo
echo "---- the runtime consumer: Mach.conv ----"
git show $A:ref/gen_layer_script.py | sed -n '1032p;1041p'
echo "---- and it is identical at B ----"
git show $B:ref/gen_layer_script.py | sed -n '1032p;1041p'
echo
echo "---- CW_F, both trees ----"
git show $A:ref/layer_fixed.py | grep -n '^CW_F = '
git show $B:ref/layer_fixed.py | grep -n '^CW_F = '
echo
echo "---- what the shipping RTL bakes ----"
sed -n '50,54p' rtl/conv4_silu.sv
echo
echo "---- what the artifact's manifest says ----"
grep -n '"rs_f"' tb/scripts/w9/model_9b_s1.weights.json
echo
echo "---- when the fix landed, against 106's launch ----"
git log -1 --format='%h %ad  %s' --date=iso 28fac0b
echo "106 launched: $(sed -n '2p' evidence/qwen9b/g6/106_longctx_lockstep_ref.log | tr -d '\r')"
echo
echo "DERIVED: conv shift RS_F+CW_F-12 is 8+13-12=9 at A and 7+13-12=8 at B;"
echo "         the RTL literal is 8, so A is one bit too far."
