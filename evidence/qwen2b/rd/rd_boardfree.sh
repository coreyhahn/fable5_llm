#!/usr/bin/env bash
# rd_boardfree.sh — the board-free gates, run before any hardware access.
cd /home/cah/r2d2/code/fpga/fable5_llm/sw || exit 1
echo "=== version constants in the tree ==="
grep -n 'EXPECTED_SEQ_VERSION = \|EXPECT_VERSION = ' seq_run.py infer.py
echo
echo "=== make seq_selftest ==="; make seq_selftest;         rc1=$?
echo "=== make serve_test ===";   make serve_test;           rc2=$?
echo "=== chat_seq --selftest ==="; .venv/bin/python -u chat_seq.py --selftest; rc3=$?
echo "SELFTEST_RCS seq=$rc1 serve=$rc2 chat=$rc3"
[ $rc1 -eq 0 ] && [ $rc2 -eq 0 ] && [ $rc3 -eq 0 ] && echo "BOARDFREE_PASS" || echo "BOARDFREE_FAIL"
