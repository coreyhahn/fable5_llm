#!/usr/bin/env bash
# run_g4a_memwatch.sh — what four full-model 9B replays cost in memory.
#
#   bash evidence/qwen9b/g4/run_g4a_memwatch.sh [pattern] [interval_s]
#
# The controller's ruling on the 4-seed full-model rung says to "check memory
# headroom first and record it".  Headroom is a `free` reading and is easy;
# the number that is actually worth having is the PEAK, and that can only be
# measured while the four processes run.  So this samples until the last one
# exits and prints the peak, rather than asserting a budget up front.
#
# It runs BESIDE the campaign, in its own log, because folding a sampler into
# `run_g4a_replay.sh` would put a background loop inside the script whose
# wall-clock number the gate quotes.
set -u
# The pattern is matched against the EXECUTABLE (argv[0]), not the whole
# command line.  The first cut matched the whole line and counted its own
# wrapper shells -- `bash run_g4a_memwatch.sh tb_seq_chip_9b` contains the
# pattern too -- so it reported `procs 7` for four simulations.  Matching
# argv[0] cannot do that: a shell's argv[0] is `bash`.
PAT=${1:-tb_seq_chip_9b}
IVL=${2:-60}
echo "=== pattern  $PAT"
echo "=== interval ${IVL}s"
echo "=== machine  $(nproc --all) cores"
echo "--- free -g at the start (headroom BEFORE the campaign):"
free -g | sed 's/^/    /'
PEAK_TOT=0; PEAK_ONE=0; PEAK_N=0; SAMPLES=0
# one sample: count, total RSS (KiB) and largest RSS over processes whose
# EXECUTABLE matches $PAT
sample() {
  ps -eo rss,args | awk -v p="$PAT" \
      '$2 ~ p {n++; t+=$1; if ($1>m) m=$1} END {print n+0, t+0, m+0}'
}
# wait for the first process rather than exiting on an empty first sample
for _ in $(seq 1 60); do
  read -r n _ _ <<< "$(sample)"; [ "$n" -gt 0 ] && break
  sleep 5
done
while :; do
  read -r n tot one <<< "$(sample)"
  [ "$n" -gt 0 ] || break
  SAMPLES=$((SAMPLES + 1))
  [ "$tot" -gt "$PEAK_TOT" ] && PEAK_TOT=$tot
  [ "$one" -gt "$PEAK_ONE" ] && PEAK_ONE=$one
  [ "$n"   -gt "$PEAK_N"   ] && PEAK_N=$n
  printf "SAMPLE %3d  %s  procs %d  total RSS %8.3f GiB  largest %8.3f GiB  avail %s GiB\n" \
         "$SAMPLES" "$(date +%H:%M:%S)" "$n" \
         "$(awk -v v="$tot" 'BEGIN{print v/1048576}')" \
         "$(awk -v v="$one" 'BEGIN{print v/1048576}')" \
         "$(free -g | awk '/^Mem:/{print $NF}')"
  sleep "$IVL"
done
echo "--- free -g at the end:"
free -g | sed 's/^/    /'
printf "G4A_MEMWATCH: peak %d process(es), total RSS %.3f GiB, largest single %.3f GiB, %d sample(s)\n" \
       "$PEAK_N" \
       "$(awk -v v="$PEAK_TOT" 'BEGIN{print v/1048576}')" \
       "$(awk -v v="$PEAK_ONE" 'BEGIN{print v/1048576}')" \
       "$SAMPLES"
