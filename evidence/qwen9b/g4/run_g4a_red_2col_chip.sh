#!/usr/bin/env bash
# run_g4a_red_2col_chip.sh — the RED control for G4a fix round 1, finding I6.
#
#   bash evidence/qwen9b/g4/run_g4a_red_2col_chip.sh
#
# I6's green half is easy to state and easy to fake: the goldens now carry
# four counters per kv bank and `tb_seq_chip` compares all four.  What makes
# that a gate rather than a claim is the RED — a STALE two-column `.chip`,
# byte-for-byte what `tb/scripts/gen_seq_chip_vectors.py` wrote BEFORE
# `86bc499`, must be REFUSED rather than half-checked.  Half-checking a stale
# build product is the exact failure the whole block exists to stop, and it is
# how kvheads 2/3 went uncompared for a whole geometry in the first place.
#
# The doctored golden is the ONLY thing that differs: the stream, the const
# blob and the four weight regions are symlinks to the real `lay9b_s1`
# artifact, so a refusal cannot be blamed on a missing or altered input.
# `lay9b_s1` is the layer smoke, which has no `.emb.bin` and takes ~200 s to
# run — but the parse happens before the first cycle, so the RED returns in
# seconds.
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
W=$ROOT/tb/scripts/w9
STEM=${1:-lay9b_s1}
BIN=$ROOT/tb/obj_dir_tb_seq_chip_9b/tb_seq_chip_9b
[ -x "$BIN" ] || { echo "MISSING $BIN (make -C tb tb_seq_chip_9b_build)" >&2
                   exit 3; }
D=$(mktemp -d /var/tmp/g4a_red2col_XXXXXX)
trap 'rm -rf "$D"' EXIT

ln -s "$W/$STEM.e4.seq"         "$D/red.e4.seq"
ln -s "$W/$STEM.e4.seqdata.bin" "$D/red.e4.seqdata.bin"
for c in 0 1 2 3; do ln -s "$W/$STEM.wimg$c.bin" "$D/red.wimg$c.bin"; done
[ -e "$W/$STEM.emb.bin" ] && ln -s "$W/$STEM.emb.bin" "$D/red.emb.bin"
# keep TCNT columns 1..2 only — the pre-86bc499 line shape
awk '$1 == "TCNT" { print $1, $2, $3, $4; next } { print }' \
    "$W/$STEM.e4.chip" > "$D/red.e4.chip"

echo "=== stem      $STEM"
echo "=== binary    $BIN"
echo "=== built     $(date -Is -r "$BIN")"
echo "--- the REAL golden's TCNT lines (4 counters per bank):"
grep '^TCNT' "$W/$STEM.e4.chip" | sed 's/^/    /'
echo "--- the DOCTORED golden's TCNT lines (2, as before 86bc499):"
grep '^TCNT' "$D/red.e4.chip" | sed 's/^/    /'

# RUN FROM tb/: layer_chan and its siblings $readmemh `../rtl/roms/*.hex`
# relative to the process cwd (run_g4a_replay.sh's header has the long
# version of why that matters).
cd "$ROOT/tb"
set +e
"$BIN" +seq="$D/red.e4" +base="$D/red" +watchdog_ms=172800000 2>&1 | tail -20
rc=${PIPESTATUS[0]}
set -e
echo "--- sim rc=$rc"
if [ "$rc" = 0 ]; then
  echo "G4A_RED_2COL_CHIP: FAILED — the two-column golden was ACCEPTED"
  exit 1
fi
echo "G4A_RED_2COL_CHIP: REFUSED as intended (rc=$rc)"
