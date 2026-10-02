#!/bin/bash
# program_fpga.sh — the safe reprogram sequence for the BCU-1525, under the
# shared board lock.  Run ON SNOKE.
#
#   ./program_fpga.sh [--jtag-only] [--no-lock] [--expect-sha256 <64 hex>] [--check-only] <path/to/bitfile.bit>
#
# VOLATILE JTAG CONFIGURATION ONLY.  This never writes board flash (CHARTER).
#
# O3 (user ruling 2026-08-29) — WHY THIS SCRIPT GREW THE WHOLE SEQUENCE.
# The CHARTER flow is  pcie_helper.sh remove -> JTAG -> pcie_helper.sh rescan,
# and the window that matters is not the JTAG step: it is the whole sequence.
# Between `remove` and `rescan` the device is GONE from the PCI tree, so any
# other tool's /dev/xdma0_* fd points at nothing, and a host MMIO to a dead
# endpoint can kernel-panic snoke.  A lock held only across the JTAG call
# would leave both ends of that window open.  So the sequence lives here and
# ONE hold of sw/board_lock.py covers all three steps.
#
# THE ENDPOINT ALWAYS COMES BACK.  Every exit path after a successful
# `remove` — vivado failing, the settings64.sh source failing, a `set -e`
# abort, SIGINT, SIGTERM — runs the rescan through an EXIT trap.  Leaving
# the endpoint off the bus is worse than a bad bitstream: the board looks
# dead to lspci and to every tool, and the next person reaches for a power
# cycle.  (The first cut of this script rescanned only on the success path
# and on the `PROGRAM_OK`-missing path, so a `set -e` abort anywhere in
# between left it removed.)
#
#   --jtag-only  program only; the CALLER owns remove/rescan and MUST hold
#                the board lock (inherited, not re-taken).  A failure here
#                leaves the endpoint removed BY THE CALLER, so the caller
#                needs its own trap — sw/stage1_hw_bringup.sh and
#                sw/test_ctl.sh both have one.
#   --no-lock    do it all with no lock at all.  For a human who has
#                confirmed sole use of the board — never for a script.
#                Announced through sw/board_lock.py so the banner, the
#                standing rule and the audit line are the SAME ones every
#                Python tool prints.  See evidence/qwen9b/o3/BOARD_LOCK.md §6.
set -euo pipefail

# R3-0 (i) — the twin-bitstream guard (evidence/qwen9b/sr/R3_0_TOOLING.md):
#   --expect-sha256 <64 hex>   (or --expect-sha256=<64 hex>) the bit file's
#                sha256 must equal this, checked INSIDE the lock hold, just
#                before [1/3] remove: a mismatch is `FATAL: sha256 mismatch`,
#                exit 5, nothing removed.  Two bitstreams of one netlist
#                share VERSION / SEQ_CAPS / BM_IDENT, so the CSRs cannot tell
#                them apart after the fact (SR14 §4); the hash is the only
#                check that names the FILE.  Optional; mandatory by procedure
#                for the R3 board session (R3-11).
#   --check-only stop after the checks below (`CHECK_ONLY: ...`, exit 0):
#                nothing removed, nothing programmed.
# And for EVERY caller, in the same place: an ESTABLISHED TCP client of
# hw_server's port 3121 (another hw_manager attached) is `FATAL: a client is
# attached to hw_server`, exit 6, nothing removed (the SR15 pre-flight's
# check, now inside the programming command).  Order: sha256, client, remove.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
JTAG_ONLY=0
NO_LOCK=0
CHECK_ONLY=0
EXPECT_SHA=
SHA_GIVEN=0
ARGS=("$@")                 # re-exec'd whole under the lock (below)
USAGE="usage: program_fpga.sh [--jtag-only] [--no-lock] [--expect-sha256 <64 hex>] [--check-only] <bitfile>"
POS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --jtag-only)  JTAG_ONLY=1 ;;
        --no-lock)    NO_LOCK=1 ;;
        --check-only) CHECK_ONLY=1 ;;
        --expect-sha256)
            [ $# -ge 2 ] || { echo "FATAL: --expect-sha256 needs a value (64 hex digits)" >&2; echo "$USAGE" >&2; exit 2; }
            EXPECT_SHA=$2; SHA_GIVEN=1; shift ;;
        --expect-sha256=*) EXPECT_SHA=${1#--expect-sha256=}; SHA_GIVEN=1 ;;
        *)            POS+=("$1") ;;
    esac
    shift
done
BIT=${POS[0]:-}
[ -n "$BIT" ] || { echo "$USAGE" >&2; exit 2; }
[ ${#POS[@]} -eq 1 ] || { echo "FATAL: one bitfile only, got ${#POS[@]}: ${POS[*]}" >&2; echo "$USAGE" >&2; exit 2; }
if [ "$SHA_GIVEN" = 1 ]; then
    [[ "$EXPECT_SHA" =~ ^[0-9a-fA-F]{64}$ ]] || { echo "FATAL: --expect-sha256 '$EXPECT_SHA' is not a full sha256 (64 hex digits)" >&2; exit 2; }
    EXPECT_SHA=$(printf '%s' "$EXPECT_SHA" | tr 'A-F' 'a-f')
fi

# ---- O3: take the board lock for the WHOLE sequence -------------------
# --check-inherited exits 0 only if this process VERIFIABLY inherited the
# holder's own locked file descriptor (fstat dev/ino against the lock path,
# plus a flock on that fd that can only succeed for the holder's OFD).  It
# is not satisfiable from the environment, so it cannot loop and cannot be
# forged; see sw/board_lock.py:_inherited_ok.
if [ "$NO_LOCK" != 1 ] \
   && ! python3 "$SCRIPT_DIR/board_lock.py" --check-inherited >/dev/null 2>&1
then
    exec python3 "$SCRIPT_DIR/board_lock.py" \
        --tool "program_fpga.sh $(basename -- "$BIT")" --exec -- "$0" "${ARGS[@]}"
fi
if [ "$NO_LOCK" = 1 ]; then
    python3 "$SCRIPT_DIR/board_lock.py" \
        --tool "program_fpga.sh $(basename -- "$BIT")" --announce-no-lock || true
    echo "*** The device leaves the PCI tree during this sequence; anything"
    echo "*** else holding /dev/xdma0_* is talking to a dead endpoint."
fi

PCIE="sudo -n $SCRIPT_DIR/pcie_helper.sh"
NEED_RESCAN=0
VLOG=

# The endpoint must come back on EVERY exit path, not just the happy one.
on_exit() {
    rc=$?
    if [ "$NEED_RESCAN" = 1 ]; then
        NEED_RESCAN=0
        echo "=== [3/3] rescan the PCI tree (exit code so far: $rc)"
        $PCIE rescan || echo "FATAL: rescan FAILED — the endpoint is OFF THE" \
            "BUS.  Run: sudo -n $SCRIPT_DIR/pcie_helper.sh rescan" >&2
    fi
    if [ -n "$VLOG" ] && [ -f "$VLOG" ]; then
        if [ "$rc" = 0 ]; then
            rm -f "$VLOG"
        else
            echo "vivado log kept for diagnosis: $VLOG" >&2
        fi
    fi
    exit $rc
}
trap on_exit EXIT INT TERM

# ---- R3-0 (i): the checks, INSIDE the lock hold, BEFORE [1/3] remove ----
# (NEED_RESCAN is still 0 here: an exit below removes nothing and rescans
# nothing.)  1. the file is the ruled one; 2. no other hw_manager attached.
echo "=== [0/3] bitfile: $BIT"
if [ -n "$EXPECT_SHA" ]; then
    echo "=== [0/3] expect-sha256: $EXPECT_SHA"
    GOT_SHA=$(sha256sum -- "$BIT" 2>/dev/null | cut -d' ' -f1) || GOT_SHA=
    if [ "$GOT_SHA" != "$EXPECT_SHA" ]; then
        echo "FATAL: sha256 mismatch — $BIT is ${GOT_SHA:-UNREADABLE}, the ruled file is $EXPECT_SHA.  Nothing removed, nothing programmed." >&2
        exit 5
    fi
    echo "=== [0/3] sha256 OK: $GOT_SHA"
fi
if ! SS_OUT=$(ss -tnp state established '( sport = :3121 or dport = :3121 )' 2>&1); then
    echo "FATAL: could not list hw_server (port 3121) clients with ss: $SS_OUT" >&2
    exit 6
fi
SS_EST=$(printf '%s\n' "$SS_OUT" | tail -n +2 | grep -v '^[[:space:]]*$' || true)
if [ -n "$SS_EST" ]; then
    printf '%s\n' "$SS_EST" | sed 's/^/    /' >&2
    echo "FATAL: a client is attached to hw_server (port 3121) — another hw_manager / xsdb session is connected.  Close it first.  Nothing removed, nothing programmed." >&2
    exit 6
fi
echo "=== [0/3] no client attached to hw_server (port 3121)"
if [ "$CHECK_ONLY" = 1 ]; then
    if [ -n "$EXPECT_SHA" ]; then
        echo "CHECK_ONLY: sha256 OK, no attached client"
    else
        echo "CHECK_ONLY: no sha256 named, no attached client"
    fi
    exit 0
fi

if [ "$JTAG_ONLY" != 1 ]; then
    echo "=== [1/3] remove the endpoint from the PCI tree (host-hang safety)"
    # ARMED BEFORE THE REMOVE, not after: a remove that fails PART WAY
    # still has to be undone, and `set -e` would skip an arming line
    # placed after it.  A rescan with nothing removed is a no-op.
    NEED_RESCAN=1
    $PCIE remove
else
    echo "=== [1/3] SKIPPED (--jtag-only): the caller owns remove/rescan"
fi

echo "=== [2/3] JTAG program (VOLATILE — never flash): $BIT"
set +u
source /home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh
set -u

PROG_OK=0
VLOG=$(mktemp -t program_fpga.XXXXXX)
set +e
vivado -mode batch -nojournal -nolog \
    -source "$SCRIPT_DIR/../synth/scripts/program.tcl" -tclargs "$BIT" \
    > "$VLOG" 2>&1
set -e
grep -E "PROGRAM_OK|FATAL|ERROR" "$VLOG" || true
if grep -q PROGRAM_OK "$VLOG"; then PROG_OK=1; fi

if [ "$PROG_OK" != 1 ]; then
    echo "FATAL: no PROGRAM_OK from synth/scripts/program.tcl." >&2
    echo "       *** THE RESIDENT BITSTREAM IS NOW UNKNOWN. ***  A JTAG run" >&2
    echo "       that never started configuration leaves the OLD bitstream" >&2
    echo "       in the FPGA, and it will re-enumerate and answer CSR reads" >&2
    echo "       normally — so nothing downstream looks wrong.  This exit" >&2
    echo "       code is the ONLY staleness warning you get: verify the CSR" >&2
    echo "       VERSION against the build you meant to load before any DMA." >&2
    if [ "$JTAG_ONLY" = 1 ]; then
        echo "       --jtag-only: the endpoint is still REMOVED (the caller" >&2
        echo "       took it out and owns putting it back)." >&2
    fi
    exit 1                                  # the trap rescans on the way out
fi
echo "PROGRAM_OK  $BIT"
