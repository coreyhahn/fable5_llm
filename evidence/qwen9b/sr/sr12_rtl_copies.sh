#!/usr/bin/env bash
# sr12_rtl_copies.sh — Task SR12: the two RTL copies the RED run and the
# negative control build from, never the working tree's rtl/.
#   base   `git show <base>:rtl/<f>` for the four files SR12 edits
#          (seq_unit, seq_movers, matvec_chan, matvec_engine): the RED run
#   mut    the WORKING TREE's four files with the R2 bank fields IGNORED —
#          seq_movers latches the MOVX start word and the MOVY start row as
#          0 (`& 12'd0`), matvec_engine loads x_line / row_in as if XBANK /
#          RBANK were 0 (`& 1'b0`) — every signal stays read, so the copy is
#          still -Wall clean and the TBs, not the linter, must catch it
# into tb/scripts_scratch/sr12_{base,mut}_rtl/ (gitignored), with sha256s.
# Run ON SNOKE through sr_run.sh.   sr12_rtl_copies.sh <base-commit>
set -u
BASE=${1:?base commit}
ROOT=$(cd "$(dirname "$0")/../../.." && pwd); cd "$ROOT" || exit 1
B=tb/scripts_scratch/sr12_base_rtl; M=tb/scripts_scratch/sr12_mut_rtl
rm -rf "$B" "$M"; mkdir -p "$B" "$M"
FILES="seq_unit.sv seq_movers.sv matvec_chan.sv matvec_engine.sv"
for f in $FILES; do
  git show "$BASE:rtl/$f" > "$B/$f" || exit 1
  cp "rtl/$f" "$M/$f"
done
# --- the mutant: ignore every R2 bank field ---------------------------
sed -i 's/res_row_q <= cmd_row; /res_row_q <= cmd_row \& 12'"'"'d0; /' "$M/seq_movers.sv"
sed -i 's/xword_q   <= cmd_xword; /xword_q   <= cmd_xword \& 12'"'"'d0; /' "$M/seq_movers.sv"
sed -i 's/cfg_xbank ? XB_LINE : 7'"'"'d0;/(cfg_xbank \& 1'"'"'b0) ? XB_LINE : 7'"'"'d0;/g' "$M/matvec_engine.sv"
sed -i 's/cfg_rbank ? RB_ROW : '"'"'0;/(cfg_rbank \& 1'"'"'b0) ? RB_ROW : '"'"'0;/' "$M/matvec_engine.sv"
echo "base $BASE:"
for f in $FILES; do echo "  $B/$f sha256 $(sha256sum < "$B/$f" | cut -c1-16)"; done
echo "working tree (R2) and its mutant:"
for f in $FILES; do
  echo "  rtl/$f sha256 $(sha256sum < "rtl/$f" | cut -c1-16)  mut $(sha256sum < "$M/$f" | cut -c1-16)"
done
echo "--- mutant diff vs the working tree (must be exactly the 5 bank lines):"
n=0
for f in $FILES; do
  d=$(diff "rtl/$f" "$M/$f" | grep -c '^>')
  diff "rtl/$f" "$M/$f" | grep '^[<>]'
  n=$((n + d))
done
echo "SR12 MUTANT: $n changed lines"
[ "$n" -eq 5 ]
