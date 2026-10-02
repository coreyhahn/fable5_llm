#!/usr/bin/env bash
# sr3c_drift.sh — Task SR3c: the o3 citation-drift pass after SR3's R1 RTL
# edits (5c369c2), at base 3ae0ff9 (SR3's parent).  One place for the long
# argument list so --plan, --fix and --verify ask the SAME question.
#   evidence/qwen9b/sr/sr3c_drift.sh --plan|--fix|--verify|--check
# Run through evidence/qwen9b/sr/sr_run.sh on snoke (log block n1980-n1989).
#
# --exclude: evidence/qwen9b/sr/SR3_R1_RTL.md is SR3's gate doc, written in
# post-SR3 coordinates (it is not in the 3ae0ff9 tree, so the sweep cannot
# see it either; excluded by name so the log says so).
#
# --allow-collateral: the nine COLLATERAL tokens of n315/n1980, each checked
# by hand against `git show 3ae0ff9:rtl/seq_unit.sv` and the working file —
# every one is a genuine base->work move whose endpoints map line for line;
# the tool classes them collateral only because a range START did not move
# or because another cite in the same document moves ONTO the number.
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
exec /home/cah/.venv/bin/python evidence/qwen9b/o3/o3_cite_drift.py \
  --base 3ae0ff9 \
  --edited rtl/seq_unit.sv,rtl/seq_movers.sv,tb/scripts/gen_seq_unit_vectors.py,tb/tb_seq_unit.sv,tb/Makefile \
  --exclude evidence/qwen9b/sr/SR3_R1_RTL.md \
  "--allow-collateral=rtl/seq_unit.sv:40-51=SR3c checked: 40 unmoved, base 51 -> 56 same text; the range was already imprecise at 3ae0ff9 (the err_code table is base 56-68), recorded in the SR3c report, not re-aimed" \
  "--allow-collateral=rtl/seq_unit.sv:19-51=SR3c checked: 19 unmoved, base 51 -> 56 same text; the widening covers the new 0x64 SEQ_CAPS map lines 49-53" \
  "--allow-collateral=rtl/seq_unit.sv:25-50=SR3c checked: 25 unmoved, base 50 (BM_IDENT 0xFAB1B301) -> 55 same text; the new 0x64 SEQ_CAPS lines 49-53 fall inside" \
  "--allow-collateral=rtl/seq_unit.sv:1061-1065=SR3c checked: base 1061 OP_FENCE begin -> 1079, base 1065 end -> 1084 (mv_fmask inserted inside)" \
  "--allow-collateral=rtl/seq_unit.sv:337=SR3c checked: base 337 -> 347 same text; collateral only because the doc's 327 moves onto 337" \
  "--allow-collateral=rtl/seq_unit.sv:1353=SR3c checked: base 1353 bm_clr -> 1372 same text; collateral only because the doc's 1334-1341 moves onto 1353" \
  "--allow-collateral=rtl/seq_unit.sv:328=SR3c checked: base 328 -> 338 same text; collateral only because the same row's 323 moves onto 328" \
  "$@"
