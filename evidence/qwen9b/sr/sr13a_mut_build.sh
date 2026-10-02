#!/usr/bin/env bash
# sr13a_mut_build.sh — Task SR13a: the chip-TB NEGATIVE CONTROL binary.
# The SR12 bank-blind mutant (evidence/qwen9b/sr/sr12_rtl_copies.sh's five
# seds: seq_movers latches the MOVX start word and the MOVY start row as 0,
# matvec_engine loads x_line / row_in as if XBANK / RBANK were 0 — every
# signal still read, so it stays -Wall clean) applied to a `git archive`
# SNAPSHOT of <commit>, never to the working tree, then built with the same
# recipe as evidence/qwen9b/sr/sr_build.sh into tb/obj_dir_seq_chip_sr13_mut
# (binary tb_seq_chip_9b_sr13_mut, so run_sr_chip.sh runs it with K=13_mut).
# The coverage streams (sr13a_cov.py) must FAIL on it: a bank-blind RTL that
# still passed them would make their PASS on the R2 binary vacuous.
#   bash evidence/qwen9b/sr/sr13a_mut_build.sh <commit> [<set>]  (ON SNOKE, sr_run.sh)
#
# R3-9a (flags, not copies; plan re-review n2): an optional MUTATION SET
# names R3's chip-TB mutants, defined in evidence/qwen9b/sr/r3_8_mutants.sh
# (`--meta <set>` gives the obj_dir tag, the expected changed-line count and
# the file list; `--apply <set> <rtldir>` applies it to the SNAPSHOT).  The
# obj_dir is then tb/obj_dir_seq_chip_sr<tag> (binary tb_seq_chip_9b_sr<tag>,
# run_sr_chip.sh K=<tag>).  With no set: SR12's five seds, the 13_mut obj_dir,
# 5 lines, seq_movers.sv + matvec_engine.sv — exactly as before.
set -eu
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
C=$(git -C "$ROOT" rev-parse --short "${1:?usage: sr13a_mut_build.sh <commit> [<set>]}")
SET=${2:-}
MUTS=$ROOT/evidence/qwen9b/sr/r3_8_mutants.sh
if [ -z "$SET" ]; then TAG=13_mut; NLINES=5; FILES="seq_movers.sv matvec_engine.sv"
else read -r TAG NLINES FILES <<< "$(bash "$MUTS" --meta "$SET")" || exit 2
     [ -n "$FILES" ] || { echo "REFUSING: no such mutation set $SET"; exit 2; }
     echo "=== mutation set $SET: obj_dir tag $TAG, $NLINES changed line(s) in $FILES"; fi
MDIR=$ROOT/tb/obj_dir_seq_chip_sr$TAG
BIN=tb_seq_chip_9b_sr$TAG
[ -e "$MDIR" ] && { echo "REFUSING: $MDIR exists (one build per obj_dir)"; exit 2; }
SRCS=$(git -C "$ROOT" ls-tree --name-only "$C" tb/ | grep -E '\.svh?$')
SNAP=/tmp/sr_src_${C}_sr$TAG
rm -rf "$SNAP"; mkdir -p "$SNAP"
git -C "$ROOT" archive "$C" rtl tb/Makefile $SRCS | tar -x -C "$SNAP"
M=$SNAP/rtl
if [ -z "$SET" ]; then
sed -i 's/res_row_q <= cmd_row; /res_row_q <= cmd_row \& 12'"'"'d0; /' "$M/seq_movers.sv"
sed -i 's/xword_q   <= cmd_xword; /xword_q   <= cmd_xword \& 12'"'"'d0; /' "$M/seq_movers.sv"
sed -i 's/cfg_xbank ? XB_LINE : 7'"'"'d0;/(cfg_xbank \& 1'"'"'b0) ? XB_LINE : 7'"'"'d0;/g' "$M/matvec_engine.sv"
sed -i 's/cfg_rbank ? RB_ROW : '"'"'0;/(cfg_rbank \& 1'"'"'b0) ? RB_ROW : '"'"'0;/' "$M/matvec_engine.sv"
else bash "$MUTS" --apply "$SET" "$M" || exit 2; fi
if [ -z "$SET" ]; then echo "=== mutant of $C, diff vs the commit (must be exactly the 5 bank lines):"
else echo "=== mutant of $C, diff vs the commit (must be exactly the $NLINES changed line(s)):"; fi
n=0
for f in $FILES; do
  git -C "$ROOT" show "$C:rtl/$f" > "$SNAP/orig_$f"
  diff "$SNAP/orig_$f" "$M/$f" | grep '^[<>]' | sed 's/^/    /' || true
  n=$((n + $(diff "$SNAP/orig_$f" "$M/$f" | grep -c '^>' || true)))
  rm -f "$SNAP/orig_$f"
done
echo "=== SR13A MUTANT${SET:+ (set $SET)}: $n changed lines"
[ "$n" -eq "$NLINES" ] || { echo "REFUSING: expected $NLINES changed lines"; exit 3; }
for f in $(cd "$SNAP" && find rtl tb -type f -name '*.sv*' | sort); do
  a=$(sha256sum < "$SNAP/$f" | cut -c1-16)
  b=$(git -C "$ROOT" show "$C:$f" | sha256sum | cut -c1-16)
  [ "$a" = "$b" ] || echo "    differs from $C: $f"
done
T0=$(date +%s)
make -C "$SNAP/tb" tb_seq_chip_9b_tl_build JOBS=16 TL_MDIR="$MDIR" TL_BIN="$BIN"
echo "=== build wall $(( $(date +%s) - T0 ))s"
echo "=== binary sha256 $(sha256sum "$MDIR/$BIN" | cut -d' ' -f1)"
echo "=== built from the MUTANT snapshot of $C"
