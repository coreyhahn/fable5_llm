#!/usr/bin/env bash
# sr7_incr_verify.sh <out_dir>... — SR7 read-only launch check of incremental runs
# (launch_incr.sh / incr_impl.tcl): the property lines, ERROR/FATAL counts, the
# run's stage checkpoints so far, the reference-read messages, the process.
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
echo "IV now: $(date -Is)"
for R in "$@"; do
  I=$R/proj/stage1.runs/impl_1
  echo "IV ######## $R"
  grep -hE "^(INCR_|EXTRA_XDC|FULL_IMPL_CFG|FATAL)" $R/incrimpl.log | sed "s/^/IV   /"
  echo "IV   ERROR lines: incrimpl.log $(grep -c '^ERROR' $R/incrimpl.log)  runme.log $(grep -c '^ERROR' $I/runme.log 2>/dev/null)"
  echo "IV   checkpoints so far:"; ls -la --time-style=full-iso $I/*.dcp 2>/dev/null | awk '{print "IV     " $6, $7, $5, $9}'
  echo "IV   incremental messages (runme.log):"; grep -nE "read_checkpoint -incremental|Vivado 12-9151|Vivado_Tcl 4-1062|Incremental flow|Place 46-84|Place 46-44|Command: (opt|place|phys_opt|route)_design" $I/runme.log 2>/dev/null | cut -c1-220 | sed "s/^/IV     /"
  echo "IV   runme.log last line: $(tail -1 $I/runme.log 2>/dev/null | cut -c1-200)"
done
echo "IV processes (impl runs, launchers):"; pgrep -af "launch_incr|bd_wrapper.vdi" | grep -v -e pgrep -e sr7_incr_verify | cut -c1-160 | sed "s/^/IV   /"
echo "IV load: $(cat /proc/loadavg)"; free -g | sed -n 2p | sed "s/^/IV   /"
