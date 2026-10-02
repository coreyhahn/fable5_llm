#!/usr/bin/env bash
# sr16_round_clock.sh — Task SR16: the sequencer RTL round's wall clock, from
# the commit stamps only (read-only git; no arithmetic beyond first/last per
# task tag).  Run ON SNOKE via sr_run.sh.  For each conventional-commit scope
# "(SRxx)" since the round's spec (SR0, 2026-09-27), prints the first and last
# commit time and the commit count, in order of first commit; then the round's
# first SR0 commit and HEAD.  (Fix round 1: the header promised a per-rung
# milestone section that the script never printed; the milestones are read
# off the per-scope lines.)
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
echo "--- per task scope: first -> last commit (author date, local), count"
git log --reverse --format='%ad|%s' --date=format:'%Y-%m-%d %H:%M' --since=2026-09-26 \
  | grep -oE '^[^|]*\|[a-z]+\((SR[0-9A-Za-z-]+)\)' \
  | sed -E 's/\|[a-z]+\(/ /; s/\)$//' \
  | awk '{t=$1" "$2; k=$3; if(!(k in f)){f[k]=t; o[++n]=k} l[k]=t; c[k]++}
         END{for(i=1;i<=n;i++) printf "  %-11s %s -> %s  %3d commits\n", o[i], f[o[i]], l[o[i]], c[o[i]]}'
echo "--- the round's bounding commits"
git log -1 --format='  first SR0 commit: %h %ad %s' --date=format:'%Y-%m-%d %H:%M' \
  $(git log --reverse --format=%h --since=2026-09-26 --grep='(SR0)' | head -1) | cut -c1-160
git log -1 --format='  HEAD: %h %ad %s' --date=format:'%Y-%m-%d %H:%M' | cut -c1-160
echo "SR16_ROUND_CLOCK: DONE"
