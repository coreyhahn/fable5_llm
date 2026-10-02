#!/usr/bin/env bash
# sr7f1_guard_check.sh — SR7 fix round 1, M-3: the no-launch check of
# synth/scripts/proj_busy.sh and its wiring into synth/scripts/launch_incr.sh.
# Unit cases on FAKE projects in a temp dir (no Vivado), the real signed-off
# projects read-only (must be IDLE), and launch_incr.sh with
# LAUNCH_INCR_CHECK_ONLY=1 (must stop before rsync/Vivado; no out dir made).
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
PB=synth/scripts/proj_busy.sh
T=$(mktemp -d /tmp/sr7f1_guard.XXXXXX); trap 'kill $SP 2>/dev/null; pkill -f "$T/procref" 2>/dev/null; rm -rf "$T"' EXIT
H=$(hostname); NP=0; NF=0
ok() { if [ "$2" = "$3" ]; then NP=$((NP+1)); echo "  PASS $1 (rc $3)"; else NF=$((NF+1)); echo "  FAIL $1 (rc $3, want $2)"; fi; }
begin() { printf '<?xml version="1.0"?>\n<ProcessHandle Version="1" Minor="0">\n    <Process Command="vivado" Owner="cah" Host="%s" Pid="%s" HostCore="48" HostMemory="1">\n    </Process>\n</ProcessHandle>\n' "$2" "$3" > "$1/.vivado.begin.rst"; }
mk() { mkdir -p "$T/$1/proj/stage1.runs/impl_1" "$T/$1/proj/stage1.runs/synth_1"; begin "$T/$1/proj/stage1.runs/synth_1" "$H" 1; touch "$T/$1/proj/stage1.runs/synth_1/.vivado.end.rst"; echo "$T/$1/proj/stage1.runs/impl_1"; }
sleep 600 & SP=$!
d=$(mk done);    begin "$d" "$H" $SP; touch "$d/.vivado.end.rst"
d=$(mk errored); begin "$d" "$H" $SP; touch "$d/.vivado.error.rst"
d=$(mk live);    begin "$d" "$H" $SP
d=$(mk crashed); begin "$d" "$H" 999999
d=$(mk queued);  touch "$d/.Vivado_Implementation.queue.rst"
d=$(mk foreign); begin "$d" otherhost 1234
# fix 1 (n756): `sleep 600 <path>` exits at once (two operands), so the case
# had no live process; a bash whose $0 is the path holds it in its cmdline
mk procref >/dev/null; bash -c 'sleep 600; true' "$T/procref/proj/x" & sleep 1
echo "== unit cases (fake projects)"
for c in "done 0" "errored 0" "live 3" "crashed 0" "queued 3" "foreign 3" "procref 3"; do
  set -- $c; out=$(bash $PB "$T/$1/proj"); rc=$?; echo "$out" | sed 's/^/    /'; ok "$1" "$2" "$rc"
done
echo "== the real projects, read-only (must be IDLE)"
# (fix 1: out_build_044_r1_incr/proj left out — n756 found it BUSY, correctly:
# the read-only M-2 probe n755 had its checkpoint open at the time)
for p in synth/out_build_044_r1/proj synth/out_build_043_incr_probe/proj synth/out_build_041_ckr2_AltSpreadLogic_high/proj; do
  out=$(bash $PB "$p"); rc=$?; echo "$out" | sed 's/^/    /'; ok "$p" 0 "$rc"
done
echo "== launch_incr.sh wiring: LAUNCH_INCR_CHECK_ONLY=1 on an idle source"
O=synth/out_build_044_r1_sr7f1_guardcheck
out=$(LAUNCH_INCR_CHECK_ONLY=1 bash synth/scripts/launch_incr.sh build_044_r1 build_044_r1_sr7f1_guardcheck AltSpreadLogic_high \
  /home/cah/r2d2/code/fpga/fable5_llm/synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp TimingClosure 2>&1); rc=$?
echo "$out" | sed 's/^/    /'; ok "check-only on build_044_r1" 0 "$rc"
[ -e "$O" ] && { NF=$((NF+1)); echo "  FAIL $O was created"; } || { NP=$((NP+1)); echo "  PASS no out dir created"; }
echo "$out" | grep -q '^PROJ_IDLE' && { NP=$((NP+1)); echo "  PASS launch_incr ran the guard"; } || { NF=$((NF+1)); echo "  FAIL guard output missing"; }
echo "PGREP vivado launched by this check: $(pgrep -af 'vivado.*sr7f1_guardcheck' | grep -v pgrep | wc -l)"
echo "sr7f1_guard_check: $NP passed, $NF failed"
[ $NF = 0 ]
