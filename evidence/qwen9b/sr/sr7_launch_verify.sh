#!/usr/bin/env bash
# sr7_launch_verify.sh <out_dir> — SR7 read-only launch check of a create+build run (create.log, build_run.log, processes).
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
O=${1:?usage: sr7_launch_verify.sh <out_dir>}
echo "LV now: $(date -Is)"
echo "LV build.log:"; sed "s/^/LV   /" $O/build.log | grep -E "create_project|CREATE_PROJECT_OK|=== build|FATAL|DONE"
echo "LV CREATE_PROJECT_OK line: $(grep -n CREATE_PROJECT_OK $O/create.log | tail -1)"; ls -la --time-style=full-iso $O/create.log | sed "s/^/LV   /"
echo "LV create.log ERROR lines: $(grep -c "^ERROR" $O/create.log)  CRITICAL WARNING: $(grep -c "^CRITICAL WARNING" $O/create.log)  WARNING: $(grep -c "^WARNING" $O/create.log)"
echo "LV CRITICAL WARNING set vs build_042_bm1 (sorted):"
if diff <(grep "^CRITICAL WARNING" $O/create.log | sort) <(grep "^CRITICAL WARNING" synth/out_build_042_bm1/create.log | sort) >/dev/null; then echo "LV   IDENTICAL to synth/out_build_042_bm1/create.log"; else echo "LV   DIFFERS:"; diff <(grep "^CRITICAL WARNING" $O/create.log | sort) <(grep "^CRITICAL WARNING" synth/out_build_042_bm1/create.log | sort) | head -20 | sed "s/^/LV   /"; fi
echo "LV CSR VERSION set-failures: $(grep -c "WARN: could not set CSR VERSION" $O/create.log)"; grep -n "CONFIG.VERSION" $O/create.log | head -3 | cut -c1-200 | sed "s/^/LV   /"
echo "LV build_run.log: $(wc -l < $O/build_run.log) lines; ERROR: $(grep -c "^ERROR" $O/build_run.log)"; grep -nE "launch_runs|Launched" $O/build_run.log | head -12 | cut -c1-200 | sed "s/^/LV   /"
echo "LV processes:"; pgrep -af "launch_build|vivado" | grep -v -e mcp -e pgrep -e "sr7_launch_verify" | cut -c1-180 | sed "s/^/LV   /"
echo "LV load: $(cat /proc/loadavg)"
