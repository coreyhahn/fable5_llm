#!/usr/bin/env bash
# sv1_build.sh — Task SV1: build SV1's OWN chip-TB binary from a COMMITTED
# tree, never from the working tree (Task BM1-T1 edits rtl/ and tb/ in the
# same working tree concurrently, so a build from it could pick up an
# in-flight RTL edit).  Run ON SNOKE through evidence/qwen9b/ov/ov_run.sh:
#
#   bash evidence/qwen9b/ov/sv1_build.sh <commit>
#
# 1. refuses unless rtl/ and every tb/*.sv / tb/*.svh at <commit> are
#    byte-identical to the SHIPPED tree 86c94d9 (rtl/+tb/ last changed at
#    6a553ea) — the only tb/ change SV1 may carry is the Makefile's
#    TL_MDIR/TL_BIN variable;
# 2. exports exactly those sources + tb/Makefile at <commit> into a fresh
#    snapshot directory with `git archive`;
# 3. runs the census recipe `tb_seq_chip_9b_tl_build` from the snapshot with
#    the Mdir pointed at tb/obj_dir_seq_chip_sv1 in the repo (absolute);
# 4. prints the binary's sha256 and the snapshot's source list sha.
set -eu
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
SHIPPED=86c94d9
C=${1:?usage: sv1_build.sh <commit>}
C=$(git -C "$ROOT" rev-parse --short "$C")
MDIR=$ROOT/tb/obj_dir_seq_chip_sv1
BIN=tb_seq_chip_9b_sv1
[ -e "$MDIR" ] && { echo "REFUSING: $MDIR exists (one build per obj_dir)"; exit 2; }

SRCS=$(git -C "$ROOT" ls-tree --name-only "$C" tb/ | grep -E '\.svh?$')
echo "=== commit $C ; shipped reference $SHIPPED"
if ! git -C "$ROOT" diff --quiet "$SHIPPED" "$C" -- rtl/ $SRCS; then
  echo "REFUSING: rtl/ or tb/*.sv[h] at $C differ from $SHIPPED:"
  git -C "$ROOT" diff --stat "$SHIPPED" "$C" -- rtl/ $SRCS
  exit 3
fi
echo "=== rtl/ + tb/*.sv[h] at $C: IDENTICAL to $SHIPPED"
echo "=== tb/Makefile diff $SHIPPED..$C:"
git -C "$ROOT" diff "$SHIPPED" "$C" -- tb/Makefile | sed 's/^/    /'

SNAP=/tmp/sv1_src_$C
rm -rf "$SNAP"
mkdir -p "$SNAP"
git -C "$ROOT" archive "$C" rtl tb/Makefile $SRCS | tar -x -C "$SNAP"
echo "=== snapshot $SNAP: $(find "$SNAP" -type f | wc -l) files, tree sha" \
     "$(cd "$SNAP" && find . -type f | sort | xargs sha256sum | sha256sum | cut -c1-16)"

T0=$(date +%s)
make -C "$SNAP/tb" tb_seq_chip_9b_tl_build JOBS=16 \
     TL_MDIR="$MDIR" TL_BIN="$BIN"
T1=$(date +%s)
echo "=== build wall $((T1 - T0))s"
ls -la "$MDIR/$BIN"
echo "=== binary sha256 $(sha256sum "$MDIR/$BIN" | cut -d' ' -f1)"
echo "=== built from commit $C (rtl/ + tb sources identical to $SHIPPED)"
