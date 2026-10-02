#!/usr/bin/env bash
# g6_board_etiquette.sh — Task 15 rung 1: who has the board, what is resident,
# and is the bitstream we are about to program the one Task 14-B signed off?
#
# Reads only.  No sudo, no DMA, no JTAG, no flash.  Run through
# evidence/qwen9b/run.sh so the host and the tree are on the record.
set -u
cd "$(dirname "$0")/../../.."

BIT9B=synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper.bit
BIT2B=synth/out_build_035_fp2a_exc_po/bd_wrapper.bit

echo "=== [1] the PCI endpoint"
lspci -d 10ee: || true
lspci -nn -s 82:00.0 || true
ls -la /dev/xdma0_user /dev/xdma0_h2c_0 /dev/xdma0_c2h_0 /dev/xdma0_control

echo
echo "=== [2] the two worktrees that share this board"
git worktree list

echo
echo "=== [3] other board users (both worktrees, whole host)"
pgrep -af 'seq_run|chat_seq|infer\.py|serve\.py|tok_meter|program_fpga|ddr_test|layer_test|matvec_test|mover_bench|cycle_census|stage1_hw_bringup|test_ctl' \
  | grep -v 'g6_board_etiquette' || echo "  (no board tool is running)"

echo
echo "=== [4] the shared board lock, before we take it"
python3 sw/board_lock.py --status || true
echo "--- the nolock audit trail, if any"
ls -la sw/.board.lock* 2>/dev/null || echo "  (no lock sidecar files)"
tail -5 sw/.board.lock.nolock.log 2>/dev/null || echo "  (no --no-lock escape has ever been taken here)"

echo
echo "=== [5] the bitstream Task 14-B signed off (G5D_TIMING.md 11)"
echo "--- expected: 53074589 B, 2026-09-07 20:46:01, VERSION c973c18a"
ls -la --time-style=full-iso "$BIT9B"
stat -c '  bytes=%s  mtime=%y' "$BIT9B"
sha256sum "$BIT9B"
echo "--- the rollback (build_035, the 2B design, known good)"
ls -la --time-style=full-iso "$BIT2B"
sha256sum "$BIT2B"

echo
echo "=== [6] host thermals before anything is programmed"
sensors 2>/dev/null | sed -n '1,12p' || echo "  (sensors unavailable)"
uptime

echo
echo "=== [7] THE TEED READBACK — what is resident RIGHT NOW"
python3 evidence/qwen9b/g6/g6_ident.py --json evidence/qwen9b/g6/g6_ident_pre.json
