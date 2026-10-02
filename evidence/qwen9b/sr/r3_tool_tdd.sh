#!/usr/bin/env bash
# r3_tool_tdd.sh <tag> — Task R3-0 of the R3 campaign (MOVX broadcast, form
# (a)): the TDD of the four tooling items the R3 build (R3-10) and board
# session (R3-11) run under.  NO BOARD, NO REAL PROJECT, NO DMA:
#   (i)   sw/program_fpga.sh --expect-sha256 <64 hex> [--check-only], and the
#         attached-hw_server-client refusal inside the programming command
#   (ii)  SYNTH_ONLY=1 synth/scripts/launch_build.sh / build.tcl `synth_only`,
#         and the post-impl sanity block factored into
#         synth/scripts/postimpl_sanity.tcl
#   (iii) evidence/qwen9b/sr/r3_preflight.sh (the parameterised pre-flight)
#   (iv)  evidence/qwen9b/g6/g6_state.py's VERSION check before any DMA
#         (the Python half, evidence/qwen9b/sr/r3_g6state_tdd.py, run last)
# <tag> names this run's fake-project dir synth/out_r3_synthonly_probe_<tag>
# (never reused: the harness refuses an existing one).  Run ON SNOKE through
# evidence/qwen9b/sr/sr_run.sh.
#
# TRIPWIRES (the plan's R3-0 Step 1, and SR6's scripted-device pattern):
#   * every program_fpga.sh case runs with PATH="$T/bin:$PATH", where $T/bin
#     holds tripwire `sudo` and `vivado` stubs (each records its argv and
#     exits 97) and a stub `ss` (scripted: no client, or one ESTABLISHED
#     :3121 client); the harness asserts `command -v sudo|vivado|ss` resolve
#     to the stubs first.  FABLE5_BOARD_LOCK points at a scratch lock file.
#     Each case runs under `strace -f -e trace=openat,execve`: the case fails
#     if the REAL board lock (/home/cah/r2d2/code/fpga/.fable5_board.lock) is
#     opened or sw/pcie_helper.sh is exec'd; it must open the scratch lock
#     (the checks run inside the lock hold).  program_fpga.sh sources the
#     real settings64.sh only AFTER [1/3] remove, which the stub sudo fails,
#     so no case can reach the real vivado; `--jtag-only` is never run.
#   * the pre-flight cases point --root at a `git clone --shared` scratch
#     clone and every board/lock probe variable (PF_IDENT, PF_LSPCI,
#     PF_XDMA_LS, PF_LSMOD, PF_SS, PF_LOCK_STATUS, PF_HWSERVER, PF_PROCS,
#     PF_BOARD_USERS) and the interpreter PF_PY at stubs; a tripwire python
#     (first on PATH too) records every call and FAILS any call naming
#     sr8_ident / xdma / board_lock, else passes through to the shipped venv;
#     `strace` must show no openat of /dev/xdma*, no sr8_ident.py and no
#     exec of the real lspci / lsmod / ss.  The harness asserts the
#     pre-flight printed OVERRIDE (never DEFAULT) for every probe first.
#   * the Vivado cases run the REAL Vivado on a ONE-FLOP fake project only
#     (evidence/qwen9b/sr/r3_synthonly_probe.tcl): the direct build.tcl
#     `synth_only` run in synth/out_r3_synthonly_probe_<tag>/, and SCRATCH
#     ROOTS under its roots/ — a git-initialised copy of the launcher +
#     build.tcl (+ postimpl_sanity.tcl) with the probe as create_project.tcl
#     — so launch_build.sh runs end to end with no real design.  The
#     `old_noflag` root holds build.tcl / launch_build.sh AS AT c5f255d (the
#     tree before R3-0): the no-flag comparison is against that.
#
# Cases (the plan's R3-0 Step 1 (a)..(f), plus controls):
#   (a)  --expect-sha256 <wrong> <bit>, no client -> exit 5, untouched
#   (a') both `--expect-sha256 <hex> <bit>` and `--expect-sha256=<hex> <bit>`
#        bind the hex to the option and the path to the bit (printed); a
#        63-digit value, a missing value and two positionals are refused
#        (exit 2); a missing bit file with a sha is exit 5
#   (b)  right sha + an ESTABLISHED :3121 client -> exit 6, untouched;
#   (b') wrong sha AND a client -> exit 5 (the sha check runs first);
#   (b'') no sha flag + a client -> exit 6 (the client check is on for
#        every caller — the controller addendum's FYI)
#   (c)  right sha, no client, --check-only -> CHECK_ONLY, exit 0, untouched
#   (n0) CONTROL / no-flag check: `program_fpga.sh <bit>` with no flag and no
#        client reaches `[1/3] remove` exactly as before — the stub sudo
#        records `-n <repo>/sw/pcie_helper.sh remove` then `rescan` (the
#        EXIT trap) and nothing else; vivado is never reached
#   (c') the factored sanity block: the no-flag launcher + build.tcl on the
#        one-flop project print the SAME build.tcl lines (CLOCK_GATE_OK,
#        TIMING, PCIE_LOC, GT_LOC, BITSTREAM, BUILD_OK, the no-clock
#        WARNING) in the SAME order as c5f255d's, the launcher's build.log is
#        the same (paths / hash / exit time normalised), the no-clock report
#        is the same; the procs also run READ-ONLY on the routed checkpoint;
#        the one-flop project has no PCIE4 / GTYE4 cell, so both lists print
#        empty (recorded, not a defect)
#   (d)  build.tcl `synth_only` on the one-flop project -> SYNTH_OK, synth_1
#        100 % (read back read-only), no impl_1/.vivado.begin.rst, no .bit,
#        proj_busy.sh PROJ_IDLE, LAUNCH_INCR_CHECK_ONLY=1 launch_incr.sh
#        accepts it (no out dir made); SYNTH_ONLY=1 launch_build.sh in a
#        scratch root -> `=== SYNTH DONE: <out> ===`, no .bit; SYNTH_ONLY=yes
#        refused before create_project
#   (e)  the pre-flight, board-free: clean clone -> PREFLIGHT: PASS; one
#        modified tracked file -> FAIL naming the tree; a session log
#        (n33NN_*) untracked -> still PASS; another untracked file -> FAIL;
#        a stub identity that is not build_041 -> FAIL; a stub :3121 client
#        -> FAIL; a short sha argument -> refused (exit 2)
#   (f)  g6_state.py against a mock Dev (r3_g6state_tdd.py)
#
# RED PREDICTION (written before the first run, against the committed tests
# on c5f255d's tools): FAIL on (a), (a') [c5f255d's loop takes the hex as
# the bitfile and every case reaches the stub remove], (b), (b'), (b''),
# (c), (c') [postimpl_sanity.tcl absent], (d) [old build.tcl ignores
# `synth_only`: impl_1 runs and writes a .bit; the old launcher ignores
# SYNTH_ONLY], (e) [r3_preflight.sh absent], and (f)'s refusal cases (see
# r3_g6state_tdd.py).  PASS on (n0), on (c')'s old-vs-new comparisons (both
# roots run c5f255d's code in RED), on (d)'s synth_1-finished / PROJ_IDLE /
# launch_incr-accepts checks, and on (f)'s two proceed cases.
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
cd "$ROOT" || exit 1
TAG=${1:?usage: r3_tool_tdd.sh <tag>  (e.g. n2200)}
BASE_REF=c5f255d
REAL_LOCK=/home/cah/r2d2/code/fpga/.fable5_board.lock
SETTINGS=/home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh
VPY=/home/cah/.venv/bin/python
PROBE_NAME="r3_synthonly_probe_${TAG}"
PROBE_OUT="$ROOT/synth/out_${PROBE_NAME}"
[ -e "$PROBE_OUT" ] && { echo "FATAL: $PROBE_OUT exists — never reused"; exit 1; }
T=$(mktemp -d /tmp/r3_tool_tdd.XXXXXX)
trap 'rm -rf "$T"' EXIT
echo "scratch: $T   fake project: $PROBE_OUT   base (before R3-0): $BASE_REF"

declare -A CP CF
ORDER=()
ok() {   # ok <case> <name> <cond-rc> [detail]
    local c=$1 n=$2 r=$3 d=${4:-}
    [[ " ${ORDER[*]} " == *" $c "* ]] || ORDER+=("$c")
    if [ "$r" = 0 ]; then CP[$c]=$(( ${CP[$c]:-0} + 1 )); echo "  [$c] PASS $n${d:+  ($d)}"
    else CF[$c]=$(( ${CF[$c]:-0} + 1 )); echo "  [$c] FAIL $n${d:+  -- $d}"; fi
}
t() { local c=$1 n=$2; shift 2; "$@"; ok "$c" "$n" $?; }
has() { grep -q -- "$1" "$2"; }
hasE() { grep -q -E -- "$1" "$2"; }
nothas() { ! grep -q -E -- "$1" "$2"; }

# ======================================================================
# (i) sw/program_fpga.sh — stubs, tripwires, scratch lock
# ======================================================================
mkdir -p "$T/bin"
for s in sudo vivado; do
    printf '#!/bin/bash\necho "TRIP %s $*" >> %s/trip.log\nexit 97\n' "$s" "$T" > "$T/bin/$s"
done
cat > "$T/bin/ss" <<EOF
#!/bin/bash
echo "ss \$*" >> $T/ss.calls
echo "Recv-Q Send-Q Local Address:Port  Peer Address:Port Process"
[ "\$(cat $T/ss.mode 2>/dev/null)" = client ] && echo '0      0      127.0.0.1:3121     127.0.0.1:51234 users:(("vivado",pid=4242,fd=17))'
exit 0
EOF
chmod +x "$T/bin/"*
head -c 65536 /dev/urandom > "$T/scratch.bit"
BIT="$T/scratch.bit"
H=$(sha256sum "$BIT" | cut -d' ' -f1)
WRONG=$(printf '%s' "$H" | tr '0-9a-f' '1-9a-f0')
H63=${H:0:63}
HUP=$(printf '%s' "$H" | tr 'a-f' 'A-F')
echo "scratch bit $BIT sha256 $H (wrong: $WRONG)"
echo "== harness: the stubs resolve first under the case PATH"
for s in sudo vivado ss; do
    got=$(env PATH="$T/bin:$PATH" bash -c "command -v $s")
    [ "$got" = "$T/bin/$s" ]; ok H "command -v $s -> $got" $?
done

PRC=0
pf() {   # pf <ss-mode> <args...>
    : > "$T/trip.log"; : > "$T/ss.calls"; echo "$1" > "$T/ss.mode"; shift
    rm -f "$T/strace.pf" "$T/board.lock"
    echo "  \$ program_fpga.sh $*"
    env PATH="$T/bin:$PATH" FABLE5_BOARD_LOCK="$T/board.lock" \
        strace -f -qq -e trace=openat,execve -o "$T/strace.pf" \
        bash sw/program_fpga.sh "$@" > "$T/pf.out" 2>&1
    PRC=$?
    sed 's/^/    | /' "$T/pf.out"
    echo "    rc=$PRC  tripwire calls: $(wc -l < "$T/trip.log")  ss calls: $(wc -l < "$T/ss.calls")"
    sed 's/^/    trip: /' "$T/trip.log"
}
untouched() {   # untouched <case>: no tripwire, no real lock, no pcie_helper, scratch lock taken
    local c=$1
    [ ! -s "$T/trip.log" ]; ok "$c" "tripwires (sudo, vivado) untouched" $?
    ! grep -q -F "$REAL_LOCK" "$T/strace.pf"; ok "$c" "the real board lock never opened" $?
    ! grep -q -E 'execve\("[^"]*pcie_helper\.sh"' "$T/strace.pf"; ok "$c" "sw/pcie_helper.sh never exec'd" $?
    grep -q -F "openat(AT_FDCWD, \"$T/board.lock\"" "$T/strace.pf"; ok "$c" "the scratch lock was taken (checks inside the hold)" $?
}

echo "== (a) wrong sha256, no client -> exit 5, nothing removed"
pf none --expect-sha256 "$WRONG" "$BIT"
[ $PRC = 5 ]; ok a "exit 5" $? "rc $PRC"
t a "FATAL: sha256 mismatch printed" has "FATAL: sha256 mismatch" "$T/pf.out"
t a "no [1/3] remove printed" nothas '\[1/3\] remove' "$T/pf.out"
untouched a

echo "== (a') option values bind; malformed values refused"
pf none --expect-sha256 "$H" --check-only "$BIT"
[ $PRC = 0 ]; ok "a'" "space form + --check-only: exit 0" $? "rc $PRC"
t "a'" "space form: the hex bound to --expect-sha256 (printed)" has "expect-sha256: $H" "$T/pf.out"
t "a'" "space form: the path bound to the bitfile (printed)" has "bitfile: $BIT" "$T/pf.out"
untouched "a'"
pf none "--expect-sha256=$H" --check-only "$BIT"
[ $PRC = 0 ]; ok "a'" "= form + --check-only: exit 0" $? "rc $PRC"
t "a'" "= form: the hex bound to --expect-sha256 (printed)" has "expect-sha256: $H" "$T/pf.out"
t "a'" "= form: the path bound to the bitfile (printed)" has "bitfile: $BIT" "$T/pf.out"
untouched "a'"
pf none --expect-sha256 "$HUP" --check-only "$BIT"
[ $PRC = 0 ]; ok "a'" "upper-case hex accepted (normalised), exit 0" $? "rc $PRC"
pf none --expect-sha256 "$H63" "$BIT"
[ $PRC = 2 ]; ok "a'" "63-digit value refused, exit 2" $? "rc $PRC"
t "a'" "63-digit: the refusal names 64 hex digits" has "64 hex" "$T/pf.out"
[ ! -s "$T/trip.log" ]; ok "a'" "63-digit: tripwires untouched" $?
pf none "$BIT" --expect-sha256
[ $PRC = 2 ]; ok "a'" "missing value refused, exit 2" $? "rc $PRC"
[ ! -s "$T/trip.log" ]; ok "a'" "missing value: tripwires untouched" $?
pf none --expect-sha256 "$H" "$BIT" "$T/other.bit"
[ $PRC = 2 ]; ok "a'" "two positionals refused, exit 2" $? "rc $PRC"
[ ! -s "$T/trip.log" ]; ok "a'" "two positionals: tripwires untouched" $?
pf none --expect-sha256 "$H" --check-only "$T/absent.bit"
[ $PRC = 5 ]; ok "a'" "absent bit file with a sha: exit 5" $? "rc $PRC"
[ ! -s "$T/trip.log" ]; ok "a'" "absent bit file: tripwires untouched" $?

echo "== (b) right sha256, an ESTABLISHED :3121 client -> exit 6"
pf client --expect-sha256 "$H" "$BIT"
[ $PRC = 6 ]; ok b "exit 6" $? "rc $PRC"
t b "FATAL: a client is attached to hw_server" has "FATAL: a client is attached to hw_server" "$T/pf.out"
t b "the client line is shown" has "127.0.0.1:3121" "$T/pf.out"
untouched b
echo "== (b') wrong sha256 AND a client -> exit 5 (the sha check runs first)"
pf client --expect-sha256 "$WRONG" "$BIT"
[ $PRC = 5 ]; ok "b'" "exit 5" $? "rc $PRC"
[ ! -s "$T/ss.calls" ]; ok "b'" "ss never called (the sha refusal came first)" $?
untouched "b'"
echo "== (b'') no sha flag, a client -> exit 6 (on for every caller)"
pf client "$BIT"
[ $PRC = 6 ]; ok "b''" "exit 6" $? "rc $PRC"
untouched "b''"

echo "== (c) right sha256, no client, --check-only -> CHECK_ONLY"
pf none --expect-sha256 "$H" --check-only "$BIT"
[ $PRC = 0 ]; ok c "exit 0" $? "rc $PRC"
t c "CHECK_ONLY: sha256 OK, no attached client" has "CHECK_ONLY: sha256 OK, no attached client" "$T/pf.out"
[ -s "$T/ss.calls" ]; ok c "the client check ran (ss called)" $?
a=$(grep -n "sha256 OK" "$T/pf.out" | head -1 | cut -d: -f1); b=$(grep -n "no client attached" "$T/pf.out" | head -1 | cut -d: -f1)
[ -n "$a" ] && [ -n "$b" ] && [ "$a" -lt "$b" ]; ok c "order: sha256 check before the client check" $? "lines ${a:-?} < ${b:-?}"
untouched c

echo "== (n0) CONTROL, no flag: program_fpga.sh <bit> reaches [1/3] remove as before"
pf none "$BIT"
t n0 "[1/3] remove printed" has "=== \[1/3\] remove the endpoint" "$T/pf.out"
[ "$(sed -n 1p "$T/trip.log")" = "TRIP sudo -n $ROOT/sw/pcie_helper.sh remove" ]; ok n0 "stub sudo got '-n <repo>/sw/pcie_helper.sh remove' first" $?
[ "$(sed -n 2p "$T/trip.log")" = "TRIP sudo -n $ROOT/sw/pcie_helper.sh rescan" ]; ok n0 "then 'rescan' (the EXIT trap)" $?
[ "$(wc -l < "$T/trip.log")" = 2 ]; ok n0 "exactly those two stub calls (vivado never reached)" $?
! grep -q -E 'execve\("[^"]*pcie_helper\.sh"' "$T/strace.pf"; ok n0 "sw/pcie_helper.sh never exec'd" $?
! grep -q -F "$REAL_LOCK" "$T/strace.pf"; ok n0 "the real board lock never opened" $?

# ======================================================================
# (ii) the synth-only launch + the factored sanity block (REAL Vivado on a
# ONE-FLOP fake project only)
# ======================================================================
echo "== (c')/(d) Vivado on the one-flop fake project (4 runs in parallel)"
mkdir -p "$PROBE_OUT/roots"
mkroot() {   # mkroot <name> <launch_build.sh src> <build.tcl src> [postimpl src]
    local R="$PROBE_OUT/roots/$1"
    mkdir -p "$R/synth/scripts"
    cp "$2" "$R/synth/scripts/launch_build.sh"; cp "$3" "$R/synth/scripts/build.tcl"
    [ -n "${4:-}" ] && [ -f "$4" ] && cp "$4" "$R/synth/scripts/postimpl_sanity.tcl"
    cp evidence/qwen9b/sr/r3_synthonly_probe.tcl "$R/synth/scripts/create_project.tcl"
    (cd "$R" && git init -q && git add -A && git -c user.name=r3tdd -c user.email=r3tdd@localhost commit -q -m "R3-0 scratch root $1")
    echo "$R"
}
git show "$BASE_REF:synth/scripts/launch_build.sh" > "$T/old_launch_build.sh"
git show "$BASE_REF:synth/scripts/build.tcl" > "$T/old_build.tcl"
R_OLD=$(mkroot old_noflag "$T/old_launch_build.sh" "$T/old_build.tcl")
R_NEW=$(mkroot new_noflag synth/scripts/launch_build.sh synth/scripts/build.tcl synth/scripts/postimpl_sanity.tcl)
R_SYN=$(mkroot new_synthonly synth/scripts/launch_build.sh synth/scripts/build.tcl synth/scripts/postimpl_sanity.tcl)
R_BAD=$(mkroot new_badvalue synth/scripts/launch_build.sh synth/scripts/build.tcl synth/scripts/postimpl_sanity.tcl)
printf 'puts "STUB_CREATE_REACHED"\nexit 1\n' > "$R_BAD/synth/scripts/create_project.tcl"
for R in "$R_OLD" "$R_NEW" "$R_SYN" "$R_BAD"; do
    echo "  root $(basename "$R"): launch_build.sh $(sha256sum < "$R/synth/scripts/launch_build.sh" | cut -c1-16)  build.tcl $(sha256sum < "$R/synth/scripts/build.tcl" | cut -c1-16)  postimpl_sanity.tcl $([ -f "$R/synth/scripts/postimpl_sanity.tcl" ] && sha256sum < "$R/synth/scripts/postimpl_sanity.tcl" | cut -c1-16 || echo absent)"
done
echo "  start: $(date -Is)"
( cd "$R_OLD" && env -u SYNTH_ONLY bash synth/scripts/launch_build.sh probe > launch.out 2>&1; echo $? > launch.rc ) &
( cd "$R_NEW" && env -u SYNTH_ONLY bash synth/scripts/launch_build.sh probe > launch.out 2>&1; echo $? > launch.rc ) &
( cd "$R_SYN" && SYNTH_ONLY=1 bash synth/scripts/launch_build.sh probe > launch.out 2>&1; echo $? > launch.rc ) &
( set +u; source "$SETTINGS"; set -u; cd "$PROBE_OUT" \
  && vivado -mode batch -nojournal -log create.log -source "$ROOT/evidence/qwen9b/sr/r3_synthonly_probe.tcl" -tclargs "$PROBE_OUT" "$TAG" > create.out 2>&1 \
  && vivado -mode batch -nojournal -log build_run.log -source "$ROOT/synth/scripts/build.tcl" -tclargs "$PROBE_OUT" synth_only > build_run.out 2>&1; echo $? > "$PROBE_OUT/direct.rc" ) &
( cd "$R_BAD" && SYNTH_ONLY=yes bash synth/scripts/launch_build.sh probe > launch.out 2>&1; echo $? > launch.rc )
wait
echo "  end:   $(date -Is)"
for R in "$R_OLD" "$R_NEW" "$R_SYN" "$R_BAD"; do
    echo "  --- $(basename "$R") (rc $(cat "$R/launch.rc")): launcher output"
    sed 's/^/    | /' "$R/launch.out"
done
echo "  --- direct build.tcl synth_only (rc $(cat "$PROBE_OUT/direct.rc"))"

# the lines build.tcl itself prints (never the '# ' command trace)
BTL='^(FATAL|CLOCK_GATE_OK|WARNING: [0-9]+ register/latch pins with no clock|TIMING:|PCIE_LOC|GT_LOC|BITSTREAM:|BUILD_OK|SYNTH_OK)'
plines() { grep -E "$BTL" "$1/synth/out_probe/build_run.log" 2>/dev/null | sed "s#$1#<ROOT>#g"; }
plines "$R_OLD" > "$T/p_old"; plines "$R_NEW" > "$T/p_new"
echo "  build.tcl printed lines, c5f255d (old_noflag):"; sed 's/^/    | /' "$T/p_old"
echo "  build.tcl printed lines, this tree (new_noflag):"; sed 's/^/    | /' "$T/p_new"

echo "== (c') the factored sanity block"
[ -f synth/scripts/postimpl_sanity.tcl ]; ok "c'" "synth/scripts/postimpl_sanity.tcl exists" $?
[ "$(cat "$R_OLD/launch.rc")" = 0 ] && grep -q '^=== DONE' "$R_OLD/launch.out"; ok "c'" "c5f255d no-flag launch: exit 0, === DONE" $?
[ "$(cat "$R_NEW/launch.rc")" = 0 ] && grep -q '^=== DONE' "$R_NEW/launch.out"; ok "c'" "this tree's no-flag launch: exit 0, === DONE" $?
NPL=$(wc -l < "$T/p_new")
[ -s "$T/p_old" ] && cmp -s "$T/p_old" "$T/p_new"; ok "c'" "build.tcl printed lines + order IDENTICAL to c5f255d's ($NPL lines)" $?
grep -q '^CLOCK_GATE_OK: 250MHz clocks: probe_clk$' "$T/p_new"; ok "c'" "CLOCK_GATE_OK names the 4 ns probe_clk" $?
[ "$(grep -c -E '^(PCIE_LOC|GT_LOC)' "$T/p_new")" = 0 ] && [ "$(grep -c -E '^(PCIE_LOC|GT_LOC)' "$T/p_old")" = 0 ]
ok "c'" "RECORDED: no PCIE4 / GTYE4 cell in the one-flop project -> both lists print empty, old and new" $?
nb() { sed "s#$1#<ROOT>#g; s#create_project ([0-9a-f]\{8\})#create_project (<hash>)#; s#(version [0-9a-f]\{8\})#(version <hash>)#" "$1/synth/out_probe/build.log" | grep -v 'Exiting Vivado'; }
nb "$R_OLD" > "$T/b_old"; nb "$R_NEW" > "$T/b_new"
cmp -s "$T/b_old" "$T/b_new"; ok "c'" "the launcher's build.log IDENTICAL (paths, hash, exit time normalised)" $?
diff "$T/b_old" "$T/b_new" | sed 's/^/    diff| /'
# the report body (from its Table of Contents on; the header box carries date / host / path)
nr() { sed -n '/^Table of Contents/,$p' "$1/synth/out_probe/reports/check_timing_noclock.rpt" 2>/dev/null; }
nr "$R_OLD" > "$T/r_old"; nr "$R_NEW" > "$T/r_new"
[ -s "$T/r_old" ] && cmp -s "$T/r_old" "$T/r_new"; ok "c'" "check_timing_noclock.rpt body IDENTICAL (header box dropped)" $?
sed 's/^/    rpt| /' "$T/r_new"
grep -q "# Command line.*-tclargs $R_NEW/synth/out_probe\$" "$R_NEW/synth/out_probe/build_run.log"
ok "c'" "no-flag launcher passed build.tcl the one word <out_dir> (no synth_only)" $?
echo "  RECORDED (not a check): the '# ' command-trace lines that differ, c5f255d vs this tree:"
echo "  (Vivado's '# Xxx: ' session-header lines — pid, CPU clock, host — excluded)"
diff <(grep '^# ' "$R_OLD/synth/out_probe/build_run.log" | grep -v -E '^# [A-Z][A-Za-z /()-]*: ' | sed "s#$R_OLD#<ROOT>#g") \
     <(grep '^# ' "$R_NEW/synth/out_probe/build_run.log" | grep -v -E '^# [A-Z][A-Za-z /()-]*: ' | sed "s#$R_NEW#<ROOT>#g") | sed 's/^/    trace| /'
RDCP=$(ls "$R_NEW"/synth/out_probe/proj/stage1.runs/impl_1/*_routed.dcp 2>/dev/null | head -1)
if [ -f synth/scripts/postimpl_sanity.tcl ] && [ -n "$RDCP" ]; then
    mkdir -p "$T/ro_rpt"
    cat > "$T/ro.tcl" <<EOF
open_checkpoint $RDCP
source -notrace $ROOT/synth/scripts/postimpl_sanity.tcl
postimpl_clock_gate $T/ro_rpt
postimpl_loc_print
puts "RO_DONE"
EOF
    ( set +u; source "$SETTINGS"; set -u; cd "$T" && vivado -mode batch -nojournal -log ro.log -source "$T/ro.tcl" > /dev/null 2>&1 )
    grep -E "$BTL|^RO_DONE" "$T/ro.log" | sed 's/^/    ro| /'
    [ "$(grep -E '^CLOCK_GATE_OK' "$T/ro.log")" = "$(grep -E '^CLOCK_GATE_OK' "$T/p_new")" ] && grep -q '^RO_DONE' "$T/ro.log"
    ok "c'" "the procs READ-ONLY on the routed checkpoint print the build's CLOCK_GATE_OK line" $?
    sed -n '/^Table of Contents/,$p' "$T/ro_rpt/check_timing_noclock.rpt" > "$T/r_ro" 2>/dev/null
    [ -s "$T/r_ro" ] && cmp -s "$T/r_ro" "$T/r_new"; ok "c'" "the read-only no-clock report body equals the build's" $?
    diff "$T/r_new" "$T/r_ro" | sed 's/^/    ro-diff| /'
else
    ok "c'" "the procs READ-ONLY on the routed checkpoint (postimpl_sanity.tcl or routed dcp absent)" 1
    ok "c'" "the read-only no-clock report equals the build's" 1
fi

echo "== (d) the synth-only launch on the one-flop fake project"
DL="$PROBE_OUT/build_run.log"
[ "$(cat "$PROBE_OUT/direct.rc")" = 0 ]; ok d "direct build.tcl synth_only: vivado exit 0" $?
grep -E "$BTL" "$DL" | sed 's/^/    | /'
t d "SYNTH_OK printed (anchored)" hasE '^SYNTH_OK' "$DL"
[ -e "$PROBE_OUT/proj/stage1.runs/synth_1/.vivado.end.rst" ]; ok d "synth_1 ended (.vivado.end.rst)" $?
SDCP=$(ls "$PROBE_OUT"/proj/stage1.runs/synth_1/*.dcp 2>/dev/null | head -1)
[ -n "$SDCP" ]; ok d "synth_1 checkpoint written (${SDCP:-none})" $?
[ ! -e "$PROBE_OUT/proj/stage1.runs/impl_1/.vivado.begin.rst" ]; ok d "no impl_1/.vivado.begin.rst (impl_1 never started)" $?
nb_bits=$(find "$PROBE_OUT/proj" -name '*.bit' | wc -l)
[ "$nb_bits" = 0 ]; ok d "no bitstream under the project" $? "$nb_bits .bit"
cat > "$T/q.tcl" <<EOF
open_project -read_only $PROBE_OUT/proj/stage1.xpr
puts "Q_SYNTH1_PROGRESS=[get_property PROGRESS [get_runs synth_1]]"
puts "Q_SYNTH1_STATUS=[get_property STATUS [get_runs synth_1]]"
puts "Q_IMPL1_STATUS=[get_property STATUS [get_runs impl_1]]"
close_project
EOF
( set +u; source "$SETTINGS"; set -u; cd "$T" && vivado -mode batch -nojournal -log q.log -source "$T/q.tcl" > /dev/null 2>&1 )
grep '^Q_' "$T/q.log" | sed 's/^/    | /'
t d "synth_1 PROGRESS 100% (read back, read-only open)" has '^Q_SYNTH1_PROGRESS=100%$' "$T/q.log"
t d "impl_1 not started (read back)" has '^Q_IMPL1_STATUS=Not started$' "$T/q.log"
out=$(bash synth/scripts/proj_busy.sh "$PROBE_OUT/proj"); rc=$?
echo "$out" | sed 's/^/    | /'
[ $rc = 0 ] && echo "$out" | grep -q '^PROJ_IDLE'; ok d "proj_busy.sh: PROJ_IDLE" $? "rc $rc"
REFC="$PROBE_OUT/ref_synth_copy.dcp"
[ -n "$SDCP" ] && cp "$SDCP" "$REFC"
out=$(LAUNCH_INCR_CHECK_ONLY=1 bash synth/scripts/launch_incr.sh "$PROBE_NAME" "${PROBE_NAME}_incrchk" Default "$REFC" RuntimeOptimized 2>&1); rc=$?
echo "$out" | sed 's/^/    | /'
[ $rc = 0 ] && echo "$out" | grep -q '^CHECK_ONLY: arguments and source OK'; ok d "LAUNCH_INCR_CHECK_ONLY=1 launch_incr.sh accepts the synth-only project" $? "rc $rc"
[ ! -e "$ROOT/synth/out_${PROBE_NAME}_incrchk" ]; ok d "launch_incr check made no out dir" $?
SO="$R_SYN/synth/out_probe"
[ "$(cat "$R_SYN/launch.rc")" = 0 ]; ok d "SYNTH_ONLY=1 launch_build.sh: exit 0" $? "rc $(cat "$R_SYN/launch.rc")"
t d "SYNTH_ONLY=1: '=== SYNTH DONE: <out> ===' printed" has "^=== SYNTH DONE: $SO ===\$" "$R_SYN/launch.out"
t d "SYNTH_ONLY=1: build.log records SYNTH DONE" has "^=== SYNTH DONE: $SO ===\$" "$SO/build.log"
t d "SYNTH_ONLY=1: no '=== DONE' line" nothas '^=== DONE' "$R_SYN/launch.out"
grep -q "# Command line.*-tclargs $SO synth_only\$" "$SO/build_run.log"; ok d "SYNTH_ONLY=1: build.tcl got '<out_dir> synth_only'" $?
t d "SYNTH_ONLY=1: SYNTH_OK in build_run.log" hasE '^SYNTH_OK' "$SO/build_run.log"
[ "$(find "$SO" -name '*.bit' | wc -l)" = 0 ] && [ ! -e "$SO/proj/stage1.runs/impl_1/.vivado.begin.rst" ]
ok d "SYNTH_ONLY=1: no bitstream, impl_1 never begun" $?
[ "$(cat "$R_BAD/launch.rc")" != 0 ] && grep -q "FATAL: SYNTH_ONLY" "$R_BAD/launch.out"; ok d "SYNTH_ONLY=yes refused by name" $? "rc $(cat "$R_BAD/launch.rc")"
[ ! -e "$R_BAD/synth/out_probe" ]; ok d "SYNTH_ONLY=yes: refused before the out dir / create_project" $?

# ======================================================================
# (iii) the pre-flight, board-free
# ======================================================================
echo "== (e) evidence/qwen9b/sr/r3_preflight.sh, board-free"
PF=evidence/qwen9b/sr/r3_preflight.sh
S="$T/pf"; mkdir -p "$S" "$T/fk"
: > "$T/pf.calls"; : > "$T/py.calls"; : > "$T/pftrip.log"
for p in python3 python; do
cat > "$S/$p" <<EOF
#!/bin/bash
echo "PY \$*" >> $T/py.calls
case "\$*" in *sr8_ident*|*xdma*|*board_lock*) echo "TRIP python \$*" >> $T/pftrip.log; exit 97 ;; esac
exec $VPY "\$@"
EOF
done
stub() { printf '#!/bin/bash\necho "%s $*" >> %s/pf.calls\n%s\n' "$1" "$T" "$2" > "$S/$1"; }
stub ident_041 'printf "  MAGIC        0xfab1e001\n  VERSION      0xc973c18a  want 0xc973c18a  OK\n  CALIB        0xf\n  CAPS_WORD    0xdeadc0de  want 0xdeadc0de  OK\nIDENT: PASS\n"; exit 0'
stub ident_r2 'printf "  VERSION      0x266e3ae7  want 0xc973c18a  MISMATCH\nIDENT: FAIL\n"; exit 1'
stub lspci 'echo "82:00.0 Memory controller [0580]: Xilinx Corporation Device [10ee:9038]"'
stub nodes_ls 'printf "crw-rw-rw- 1 root root 511, 0 Sep 29 07:08 FAKE_xdma0_user\ncrw-rw-rw- 1 root root 511, 1 Sep 29 07:08 FAKE_xdma0_h2c_0\ncrw-rw-rw- 1 root root 511, 2 Sep 29 07:08 FAKE_xdma0_c2h_0\n"'
stub lsmod 'echo "xdma                  110592  0"'
stub ss_none 'echo "Recv-Q Send-Q Local Address:Port Peer Address:Port Process"'
stub ss_client 'echo "Recv-Q Send-Q Local Address:Port Peer Address:Port Process"; echo "0 0 127.0.0.1:3121 127.0.0.1:51234 users:((\"vivado\",pid=4242,fd=17))"'
stub lock 'echo "board lock /scratch/fake.lock"; echo "  state        not held"'
stub hwserver 'echo "4242 /opt/fake/bin/hw_server -s TCP::3121"'
stub procs 'echo "4242 /opt/fake/bin/hw_server -s TCP::3121"'
stub users 'exit 1'
chmod +x "$S"/*
mkfake() { head -c "$2" /dev/urandom > "$T/fk/$1"; sha256sum "$T/fk/$1" | cut -d' ' -f1; }
HB=$(mkfake r3.bit 4096); HB41=$(mkfake b41.bit 4000); HTW=$(mkfake twin.bit 4096)
HS1=$(mkfake s1.e4.seq 1024); HM=$(mkfake m.e4.seq 512)
printf '{"stream_sha256": "%s"}\n' "$HM" > "$T/fk/m.e4.seq.json"
git clone -q --shared "$ROOT" "$T/clone"
echo "  scratch clone $T/clone at $(git -C "$T/clone" rev-parse --short HEAD)"
PIN_LITE=$(grep -E '^PIN r2 lite ' evidence/qwen9b/sr/n1351_sr13b_r2_pins.log | head -1)
PFENV=(PATH="$S:$PATH" PF_PY="$S/python3" PF_IDENT="$S/ident_041" PF_LSPCI="$S/lspci"
       PF_XDMA_LS="$S/nodes_ls" PF_LSMOD="$S/lsmod" PF_SS="$S/ss_none" PF_LOCK_STATUS="$S/lock"
       PF_HWSERVER="$S/hwserver" PF_PROCS="$S/procs" PF_BOARD_USERS="$S/users")
PFARGS=(--root "$T/clone" --bit "$T/fk/r3.bit" --bit-size 4096 --bit-sha256 "$HB"
        --b41-bit "$T/fk/b41.bit" --b41-size 4000 --b41-sha256 "$HB41"
        --twin "$T/fk/twin.bit=$HTW" --stream "$T/fk/s1.e4.seq=$HS1" --manifest "$T/fk/m.e4"
        --chat-pin "REORDER_B_R2_IMAGES=c78312bb293a5c2a16f94a76bfabcba56ce34937457b10b69b12b4bd02ff6d45"
        --pin-line "evidence/qwen9b/sr/n1351_sr13b_r2_pins.log::$PIN_LITE"
        --admit 266E3AE7 --ident-version c973c18a)
PRC=0
pfl() {   # pfl <label> [VAR=value ...] -- [extra args]
    local lab=$1; shift; local ev=(); while [ "$1" != -- ]; do ev+=("$1"); shift; done; shift
    echo "  \$ [$lab] r3_preflight.sh ${PFARGS[*]:0:2} ... $*"
    if [ -f "$PF" ]; then
        env "${PFENV[@]}" "${ev[@]}" strace -f -qq -e trace=openat,execve -o "$T/strace.$lab" \
            bash "$PF" "${PFARGS[@]}" "$@" > "$T/pfl.$lab" 2>&1
        PRC=$?
    else
        echo "bash: $PF: No such file or directory" > "$T/pfl.$lab"; : > "$T/strace.$lab"; PRC=127
    fi
    sed 's/^/    | /' "$T/pfl.$lab"; echo "    rc=$PRC"
}
pfl clean --
[ $PRC = 0 ] && grep -q '^PREFLIGHT: PASS$' "$T/pfl.clean"; ok e "clean clone, build_041 stub identity -> PREFLIGHT: PASS" $? "rc $PRC"
for v in PF_PY PF_IDENT PF_LSPCI PF_XDMA_LS PF_LSMOD PF_SS PF_LOCK_STATUS PF_HWSERVER PF_PROCS PF_BOARD_USERS; do
    grep -q -E "^  $v +OVERRIDE " "$T/pfl.clean"; ok e "probe $v printed OVERRIDE" $?
done
grep -q '^--- \[0\] root ' "$T/pfl.clean" && ! grep -q -E '^  PF_[A-Z_]+ +DEFAULT ' "$T/pfl.clean"; ok e "no default probe command in force (the [0] table printed, no DEFAULT)" $?
[ ! -s "$T/pftrip.log" ]; ok e "tripwire python untouched" $?
NPY=$(wc -l < "$T/py.calls")
grep -q . "$T/py.calls"; ok e "the interpreter used was the tripwire (PF_PY) — $NPY call(s)" $?
grep -q "ident_041" "$T/pf.calls"; ok e "the identity came from the stub" $?
[ -s "$T/strace.clean" ] && ! grep -q -E 'openat\([^)]*"/dev/xdma' "$T/strace.clean"; ok e "strace: no openat of any /dev/xdma* node" $?
[ -s "$T/strace.clean" ] && ! grep -q 'sr8_ident' "$T/strace.clean"; ok e "strace: sr8_ident.py never opened or exec'd" $?
[ -s "$T/strace.clean" ] && ! grep -q -E 'execve\("(/usr)?/s?bin/(lspci|lsmod|ss|pgrep)"' "$T/strace.clean"; ok e "strace: the real lspci / lsmod / ss / pgrep never exec'd" $?
[ -s "$T/strace.clean" ] && ! grep -q -F "$REAL_LOCK" "$T/strace.clean"; ok e "strace: the real board lock never opened" $?
mkdir -p "$T/clone/evidence/qwen9b/sr"; echo x > "$T/clone/evidence/qwen9b/sr/n3301_session_inflight.log"
pfl sesslog --
[ $PRC = 0 ] && grep -q '^PREFLIGHT: PASS$' "$T/pfl.sesslog"; ok e "an untracked session log (n33NN_) is excluded -> PASS" $? "rc $PRC"
echo x > "$T/clone/evidence/qwen9b/sr/stray_untracked.txt"
pfl untracked --
[ $PRC != 0 ] && grep -q '^PREFLIGHT: FAIL$' "$T/pfl.untracked" && grep -q 'stray_untracked.txt' "$T/pfl.untracked"; ok e "another untracked file -> FAIL, named" $? "rc $PRC"
rm -f "$T/clone/evidence/qwen9b/sr/stray_untracked.txt"
echo "# R3-0 TDD: one modified tracked file" >> "$T/clone/docs/USAGE.md"
pfl dirty --
[ $PRC != 0 ] && grep -q '^PREFLIGHT: FAIL$' "$T/pfl.dirty"; ok e "one modified tracked file -> PREFLIGHT: FAIL" $? "rc $PRC"
grep -q -F "FAIL: the tree $T/clone is dirty" "$T/pfl.dirty" && grep -q 'docs/USAGE.md' "$T/pfl.dirty"; ok e "the FAIL names the tree and the file" $?
git -C "$T/clone" checkout -q -- docs/USAGE.md
pfl identr2 PF_IDENT="$S/ident_r2" --
[ $PRC != 0 ] && grep -q '^PREFLIGHT: FAIL$' "$T/pfl.identr2"; ok e "a stub identity that is not build_041 -> FAIL" $? "rc $PRC"
pfl client PF_SS="$S/ss_client" --
[ $PRC != 0 ] && grep -q '^PREFLIGHT: FAIL$' "$T/pfl.client" && grep -q 'a client is attached to hw_server' "$T/pfl.client"; ok e "a stub :3121 client -> FAIL" $? "rc $PRC"
pfl wrongsha -- --bit-sha256 "$HTW"
[ $PRC != 0 ] && grep -q '^PREFLIGHT: FAIL$' "$T/pfl.wrongsha"; ok e "the ruled bit's sha256 differs from the argument -> FAIL" $? "rc $PRC"
pfl shortsha -- --bit-sha256 "${HB:0:16}"
[ $PRC = 2 ]; ok e "a short (not FULL 64-hex) sha argument refused, exit 2" $? "rc $PRC"
[ ! -s "$T/pftrip.log" ]; ok e "tripwire python untouched across every (e) case" $?

# ======================================================================
# (iv) g6_state.py (the Python half)
# ======================================================================
echo "== (f) evidence/qwen9b/g6/g6_state.py against a mock Dev (r3_g6state_tdd.py)"
"$VPY" -u evidence/qwen9b/sr/r3_g6state_tdd.py > "$T/f.out" 2>&1
sed 's/^/    | /' "$T/f.out"
while read -r line; do
    n=$(sed -E 's/^ *\[(f[0-9]+)\] (PASS|FAIL) (.*)$/\1/' <<< "$line")
    r=$(sed -E 's/^ *\[(f[0-9]+)\] (PASS|FAIL) (.*)$/\2/' <<< "$line")
    d=$(sed -E 's/^ *\[(f[0-9]+)\] (PASS|FAIL) (.*)$/\3/' <<< "$line")
    [ "$r" = PASS ]; ok f "$n $d" $?
done < <(grep -E '^ *\[f[0-9]+\] (PASS|FAIL) ' "$T/f.out")
grep -q -E '^ *\[f[0-9]+\] ' "$T/f.out"; ok f "r3_g6state_tdd.py ran and reported" $?

echo "== summary (per case: passed / failed)"
TP=0; TF=0
for c in "${ORDER[@]}"; do
    echo "  ($c) ${CP[$c]:-0} passed / ${CF[$c]:-0} failed"
    TP=$((TP + ${CP[$c]:-0})); TF=$((TF + ${CF[$c]:-0}))
done
echo "r3_tool_tdd: $TP passed, $TF failed"
[ $TF = 0 ]
