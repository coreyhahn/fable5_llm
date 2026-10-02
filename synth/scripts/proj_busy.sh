#!/bin/bash
# proj_busy.sh <proj_dir> — exit 0 and print PROJ_IDLE if no Vivado run of the
# project <proj_dir> (…/proj) is in flight; exit 3 and print PROJ_BUSY with
# the reason otherwise.  Read-only.  (SR7 fix round 1, M-3: SR7 rsynced a
# proj/ whose impl_1 had just started; the copied impl_1/.vivado.begin.rst
# carried the running run's PID/host, and the copy's reset_run KILLED the
# source run — evidence/qwen9b/sr/n712_SR7_base_roll_killed.log.)
# A run is in flight when its stage1.runs/<run>/.vivado.begin.rst exists with
# neither .vivado.end.rst nor .vivado.error.rst beside it AND the Pid it names
# is alive on this host (a begin with a dead pid is a crashed run: reported,
# not busy).  Also busy: any live process whose command line names <proj_dir>
# (a launch_runs parent / wait_on_run holder), or a queued-but-unstarted run
# (.<Flow>.queue.rst with no .vivado.begin.rst).
set -u
P=${1:?usage: proj_busy.sh <proj_dir>}
[ -d "$P" ] || { echo "PROJ_BUSY: $P is not a directory"; exit 3; }
P=$(cd "$P" && pwd)
H=$(hostname)
busy=0
for d in "$P"/*.runs/*/; do
  [ -d "$d" ] || continue
  run=$(basename "$d")
  if [ -e "$d/.vivado.begin.rst" ]; then
    if [ -e "$d/.vivado.end.rst" ] || [ -e "$d/.vivado.error.rst" ]; then continue; fi
    pid=$(grep -o 'Pid="[0-9]*"' "$d/.vivado.begin.rst" | head -1 | tr -dc 0-9)
    host=$(grep -o 'Host="[^"]*"' "$d/.vivado.begin.rst" | head -1 | cut -d'"' -f2)
    if [ -n "$pid" ] && [ "$host" = "$H" ] && kill -0 "$pid" 2>/dev/null; then
      echo "PROJ_BUSY: run $run is in flight (pid $pid on $host, no end/error marker)"; busy=1
    elif [ "$host" != "$H" ]; then
      echo "PROJ_BUSY: run $run began on host '$host' (not $H) with no end/error marker — cannot check its pid here"; busy=1
    else
      echo "PROJ_NOTE: run $run has a begin marker, no end/error marker, and pid ${pid:-?} is dead (a crashed run)"
    fi
  elif ls "$d"/.*.queue.rst >/dev/null 2>&1; then
    echo "PROJ_BUSY: run $run is queued (queue marker, not yet begun)"; busy=1
  fi
done
live=$(pgrep -af -- "$P" | grep -v -e "proj_busy.sh" -e pgrep || true)
if [ -n "$live" ]; then
  echo "PROJ_BUSY: live process(es) naming $P:"; printf '%s\n' "$live" | sed 's/^/  /'; busy=1
fi
[ $busy = 0 ] && { echo "PROJ_IDLE: $P"; exit 0; }
exit 3
