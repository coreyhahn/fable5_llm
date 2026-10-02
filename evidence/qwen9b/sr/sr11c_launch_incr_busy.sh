#!/usr/bin/env bash
# sr11c_launch_incr_busy.sh — SR11c (SR7 re-review minor): the END-TO-END test
# that synth/scripts/launch_incr.sh REFUSES a busy source project: exit 1 and
# NO out dir created.  proj_busy.sh is tested at its own level
# (evidence/qwen9b/sr/n757_SR7fix1_guard_check.log, 13/0); this tests the
# launcher's wiring to it.  FAKE projects only, never a real one: the source
# is synth/out_sr11c_fakebusy_$$ (gitignored, removed on exit), the reference
# dcp is an empty temp file.  The fake is made busy the way n757's "live" and
# "queued" cases are (a begin marker naming a live pid on this host with no
# end/error marker; a queue marker with no begin marker).
#   case 1  busy (live pid), LAUNCH_INCR_CHECK_ONLY unset -> rc 1, no out dir
#           (the real launch path: a broken guard would rsync + start Vivado
#           on the fake xpr; this case would then see the out dir and FAIL)
#   case 2  busy (queued),   LAUNCH_INCR_CHECK_ONLY=1    -> rc 1, no out dir
#   case 3  CONTROL: the same fake made idle (end marker), CHECK_ONLY=1
#           -> rc 0, the CHECK_ONLY line, no out dir: the refusal in 1/2 is
#           the busy state, not an argument or path error.
# Run on snoke (proj_busy.sh checks the pid on this host).
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
L=synth/scripts/launch_incr.sh
SRCN=sr11c_fakebusy_$$
SRC=synth/out_$SRCN
T=$(mktemp -d /tmp/sr11c_busy.XXXXXX)
sleep 600 & SP=$!
trap 'kill $SP 2>/dev/null; rm -rf "$T" "$SRC" synth/out_${SRCN}_o1 synth/out_${SRCN}_o2 synth/out_${SRCN}_o3' EXIT
H=$(hostname); NP=0; NF=0
ok() { if [ "$2" = "$3" ]; then NP=$((NP+1)); echo "  PASS $1 (rc $3)"; else NF=$((NF+1)); echo "  FAIL $1 (rc $3, want $2)"; fi; }
begin() { printf '<?xml version="1.0"?>\n<ProcessHandle Version="1" Minor="0">\n    <Process Command="vivado" Owner="cah" Host="%s" Pid="%s" HostCore="48" HostMemory="1">\n    </Process>\n</ProcessHandle>\n' "$2" "$3" > "$1/.vivado.begin.rst"; }
[ -e "$SRC" ] && { echo "FATAL: $SRC exists"; exit 1; }
R=$SRC/proj/stage1.runs
mkdir -p "$R/synth_1" "$R/impl_1"; touch "$SRC/proj/stage1.xpr"
begin "$R/synth_1" "$H" 1; touch "$R/synth_1/.vivado.end.rst"
: > "$T/ref.dcp"
noout() { if [ -e "synth/out_$1" ]; then NF=$((NF+1)); echo "  FAIL synth/out_$1 was created"; else NP=$((NP+1)); echo "  PASS no out dir synth/out_$1"; fi; }
has() { if printf '%s\n' "$2" | grep -q -- "$3"; then NP=$((NP+1)); echo "  PASS $1"; else NF=$((NF+1)); echo "  FAIL $1 (no '$3')"; fi; }

echo "== case 1: busy source (live pid $SP on $H, no end marker), real launch path"
begin "$R/impl_1" "$H" "$SP"
echo "  proj_busy says: $(bash synth/scripts/proj_busy.sh "$SRC/proj" | head -1)"
out=$(env -u LAUNCH_INCR_CHECK_ONLY bash $L "$SRCN" "${SRCN}_o1" AltSpreadLogic_high "$T/ref.dcp" TimingClosure 2>&1); rc=$?
printf '%s\n' "$out" | sed 's/^/    /'
ok "busy (live pid) refused" 1 "$rc"; noout "${SRCN}_o1"
has "refusal names the in-flight run" "$out" "has a Vivado run in flight"

echo "== case 2: busy source (queued impl_1), LAUNCH_INCR_CHECK_ONLY=1"
rm -f "$R/impl_1/.vivado.begin.rst"; touch "$R/impl_1/.Vivado_Implementation.queue.rst"
echo "  proj_busy says: $(bash synth/scripts/proj_busy.sh "$SRC/proj" | head -1)"
out=$(LAUNCH_INCR_CHECK_ONLY=1 bash $L "$SRCN" "${SRCN}_o2" AltSpreadLogic_high "$T/ref.dcp" TimingClosure 2>&1); rc=$?
printf '%s\n' "$out" | sed 's/^/    /'
ok "busy (queued) refused" 1 "$rc"; noout "${SRCN}_o2"
has "refusal names the in-flight run" "$out" "has a Vivado run in flight"

echo "== case 3: CONTROL — the same fake made idle, LAUNCH_INCR_CHECK_ONLY=1"
rm -f "$R/impl_1/.Vivado_Implementation.queue.rst"; begin "$R/impl_1" "$H" "$SP"; touch "$R/impl_1/.vivado.end.rst"
echo "  proj_busy says: $(bash synth/scripts/proj_busy.sh "$SRC/proj" | head -1)"
out=$(LAUNCH_INCR_CHECK_ONLY=1 bash $L "$SRCN" "${SRCN}_o3" AltSpreadLogic_high "$T/ref.dcp" TimingClosure 2>&1); rc=$?
printf '%s\n' "$out" | sed 's/^/    /'
ok "idle control accepted (check-only)" 0 "$rc"; noout "${SRCN}_o3"
has "check-only line printed" "$out" "^CHECK_ONLY"

echo "PGREP vivado launched by this test: $(pgrep -af "vivado.*$SRCN" | grep -v pgrep | wc -l)"
echo "sr11c_launch_incr_busy: $NP passed, $NF failed"
[ $NF = 0 ]
