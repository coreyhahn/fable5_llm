#!/usr/bin/env bash
# sr_build.sh — the SEQUENCER RTL ROUND's chip-TB binary (Task SR5a onward):
# a copy of evidence/qwen9b/ov/sv1_build.sh (SV1's snapshot build), changed in
# its identity check and its obj_dir only.  It builds from a COMMITTED tree,
# never from the working tree (SR1 and other tasks share this working tree),
# so a build cannot pick up an in-flight edit.  Run ON SNOKE through
# evidence/qwen9b/sr/sr_run.sh:
#
#   bash evidence/qwen9b/sr/sr_build.sh <commit> [k]
#
#   <commit>  the NAMED RTL commit (SR5a: the SR3 green-gate commit 5c369c2)
#   [k]       the task number; the obj_dir is tb/obj_dir_seq_chip_sr<k> and
#             the binary tb_seq_chip_9b_sr<k>.  Default 5 (SR5a/SR5b share
#             one binary: SR5b uses SR5a's unchanged).
#
# 1. refuses if tb/obj_dir_seq_chip_sr<k> exists (one build per obj_dir;
#    never two builds, never two hosts in one);
# 2. exports rtl/ + every tb/*.sv / tb/*.svh + tb/Makefile at <commit> into a
#    fresh snapshot directory with `git archive`;
# 3. IDENTITY (changed from SV1's "rtl/ equals the shipped 86c94d9"): refuses
#    unless every rtl/ and tb/*.sv[h] file in the snapshot is byte-identical
#    to the named commit's blob (sha256 of the extracted file vs sha256 of
#    `git show <commit>:<path>`), and unless the snapshot holds exactly the
#    files the commit lists.  For the record it also prints the RTL delta
#    of <commit> against the shipped tree 86c94d9 and against HEAD;
# 4. runs the census recipe `tb_seq_chip_9b_tl_build` from the snapshot with
#    the Mdir pointed at tb/obj_dir_seq_chip_sr<k> in the repo (absolute);
# 5. prints the binary's sha256 and the snapshot's tree sha.
set -eu
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
SHIPPED=86c94d9
C=${1:?usage: sr_build.sh <commit> [k]}
K=${2:-5}
C=$(git -C "$ROOT" rev-parse --short "$C")
MDIR=$ROOT/tb/obj_dir_seq_chip_sr$K
BIN=tb_seq_chip_9b_sr$K
[ -e "$MDIR" ] && { echo "REFUSING: $MDIR exists (one build per obj_dir)"; exit 2; }

SRCS=$(git -C "$ROOT" ls-tree --name-only "$C" tb/ | grep -E '\.svh?$')
echo "=== named RTL commit $C ; obj_dir $MDIR ; binary $BIN"
echo "=== rtl/ + tb/*.sv[h] delta, shipped $SHIPPED .. $C (for the record):"
git -C "$ROOT" diff --stat "$SHIPPED" "$C" -- rtl/ $SRCS | sed 's/^/    /'
echo "=== rtl/ + tb/*.sv[h] delta, $C .. HEAD $(git -C "$ROOT" rev-parse --short HEAD) (for the record):"
git -C "$ROOT" diff --stat "$C" HEAD -- rtl/ $SRCS | sed 's/^/    /'

SNAP=/tmp/sr_src_${C}_sr$K
rm -rf "$SNAP"
mkdir -p "$SNAP"
git -C "$ROOT" archive "$C" rtl tb/Makefile $SRCS | tar -x -C "$SNAP"

# identity: every rtl/ and tb/*.sv[h] file of the snapshot == the commit's blob
LIST=$( { git -C "$ROOT" ls-tree -r --name-only "$C" rtl/; printf '%s\n' $SRCS; } | sort)
GOTLIST=$(cd "$SNAP" && find rtl tb -type f \( -path 'rtl/*' -o -name '*.sv' -o -name '*.svh' \) | sort)
if [ "$LIST" != "$GOTLIST" ]; then
  echo "REFUSING: the snapshot's file list differs from $C's:"
  diff <(printf '%s\n' "$LIST") <(printf '%s\n' "$GOTLIST") | sed 's/^/    /'
  exit 3
fi
NF=0; NBAD=0
for p in $LIST; do
  a=$(sha256sum "$SNAP/$p" | cut -d' ' -f1)
  b=$(git -C "$ROOT" show "$C:$p" | sha256sum | cut -d' ' -f1)
  NF=$((NF + 1))
  [ "$a" = "$b" ] || { NBAD=$((NBAD + 1)); echo "    MISMATCH $p: snapshot $a, $C $b"; }
done
if [ "$NBAD" != 0 ]; then
  echo "REFUSING: $NBAD of $NF rtl/ + tb/*.sv[h] files differ from $C"
  exit 3
fi
echo "=== IDENTITY: rtl/ + tb/*.sv[h] in the snapshot: $NF files, all byte-identical to $C"
echo "=== snapshot $SNAP: $(find "$SNAP" -type f | wc -l) files, tree sha" \
     "$(cd "$SNAP" && find . -type f | sort | xargs sha256sum | sha256sum | cut -c1-16)"

T0=$(date +%s)
make -C "$SNAP/tb" tb_seq_chip_9b_tl_build JOBS=16 \
     TL_MDIR="$MDIR" TL_BIN="$BIN"
T1=$(date +%s)
echo "=== build wall $((T1 - T0))s"
ls -la "$MDIR/$BIN"
echo "=== binary sha256 $(sha256sum "$MDIR/$BIN" | cut -d' ' -f1)"
echo "=== built from commit $C (rtl/ + tb/*.sv[h] identical to $C)"
