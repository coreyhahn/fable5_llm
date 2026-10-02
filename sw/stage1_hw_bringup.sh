#!/bin/bash
# stage1_hw_bringup.sh — full stage-1 hardware bring-up on snoke, unattended.
# Requires: sudoers NOPASSWD for sw/pcie_helper.sh.
# Usage: ./stage1_hw_bringup.sh <bitfile> <expected_version_hex8>
# Logs everything to evidence/stage1/hw_bringup_<ts>.log; exits nonzero on
# any gate failure. Safe-reprogram flow: remove -> JTAG -> rescan.
#
# O3 (user ruling 2026-08-29): the WHOLE bring-up — remove, JTAG, rescan,
# the CSR gates and both ddr_test runs — is ONE hold of the shared board
# lock (sw/board_lock.py).  Not three: the reprogram window and the 16 GiB
# of DDR writes that follow it are the same critical section, and handing
# the lock back between them would let another checkout in.  program_fpga.sh
# and ddr_test.py INHERIT the hold rather than re-taking it.
set -euo pipefail

BIT=${1:?usage: stage1_hw_bringup.sh <bitfile> <version_hex8>}
EXPECT_VER=${2:?need expected version (git short8 hex)}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

# STAGE1_NO_LOCK=1 is the --no-lock escape for this script.  It is NOT a
# quiet one: it goes through sw/board_lock.py --announce-no-lock, so it
# prints the same banner on stdout AND stderr, names the current holder, and
# appends the same audit line to <lock>.nolock.log as every other tool.  It
# is documented by name in docs/USAGE.md §5 and
# evidence/qwen9b/o3/BOARD_LOCK.md §6.
# NL is passed DOWN to every child that would otherwise take a lock of its
# own.  Without it the escape is a lie: program_fpga.sh and ddr_test.py find
# no inherited fd, take the lock themselves, and a live holder makes one of
# them REFUSE in the middle of the sequence -- after the endpoint is out.
NL=()
if [ "${STAGE1_NO_LOCK:-0}" = 1 ]; then
    python3 "$SCRIPT_DIR/board_lock.py" \
        --tool "stage1_hw_bringup.sh (STAGE1_NO_LOCK=1)" \
        --announce-no-lock || true
    NL=(--no-lock)
elif ! python3 "$SCRIPT_DIR/board_lock.py" --check-inherited >/dev/null 2>&1
then
    exec python3 "$SCRIPT_DIR/board_lock.py" \
        --tool "stage1_hw_bringup.sh" --exec -- "$0" "$@"
fi
REPO=$(cd "$SCRIPT_DIR/.." && pwd)
TS=$(date +%Y%m%d_%H%M%S)
EV="$REPO/evidence/stage1"
LOG="$EV/hw_bringup_${TS}.log"
mkdir -p "$EV"
exec > >(tee "$LOG") 2>&1

PCIE="sudo -n $SCRIPT_DIR/pcie_helper.sh"
BDF=82:00.0
NEED_RESCAN=0

step() { echo; echo "=== [$(date +%H:%M:%S)] $* ==="; }

# `set -e` with no trap used to abort between step 1 (remove) and step 3
# (rescan) and leave the endpoint OFF THE PCI TREE with the lock released on
# unwind -- the board then looks dead to lspci and to every tool.  Every exit
# path now puts it back.
on_exit() {
    rc=$?
    if [ "$NEED_RESCAN" = 1 ]; then
        NEED_RESCAN=0
        echo "=== rescan on exit (rc=$rc): putting the endpoint back"
        $PCIE rescan || echo "FATAL: rescan FAILED — the endpoint is OFF THE" \
            "BUS.  Run: sudo -n $SCRIPT_DIR/pcie_helper.sh rescan" >&2
    fi
    exit $rc
}
trap on_exit EXIT INT TERM

step "0. preconditions"
[ -f "$BIT" ] || { echo "FATAL: bitstream $BIT missing"; exit 1; }
ls -la "$BIT"
echo "expected CSR VERSION: 0x$EXPECT_VER"
echo "-- current device state:"
lspci -s $BDF || true
echo "-- xdma device users (must be none):"
if lsof /dev/xdma0_* 2>/dev/null | grep -v "^COMMAND"; then
    echo "FATAL: xdma devices in use"; exit 1
fi
echo "none"

if [ "${SKIP_PROGRAM:-0}" = "1" ]; then
    step "1-3. SKIPPED (SKIP_PROGRAM=1): using already-programmed design"
else
    step "1. remove device from PCI tree (host-hang safety)"
    NEED_RESCAN=1                 # armed BEFORE the remove — see program_fpga.sh
    $PCIE remove

    step "2. JTAG program (volatile)"
    # --jtag-only: THIS script owns remove/rescan, and it already holds the
    # board lock, which program_fpga.sh inherits instead of re-taking.
    "$SCRIPT_DIR/program_fpga.sh" --jtag-only "${NL[@]}" "$BIT"

    step "3. rescan PCIe"
    $PCIE rescan
    NEED_RESCAN=0
fi

step "4. link state check (want 8GT/s x8)"
# sysfs is world-readable and immune to lspci truncation/permissions
D=/sys/bus/pci/devices/0000:$BDF
SPEED=$(cat $D/current_link_speed)
WIDTH=$(cat $D/current_link_width)
echo "link: $SPEED x$WIDTH (max: $(cat $D/max_link_speed) x$(cat $D/max_link_width))"
[ "$SPEED" = "8.0 GT/s PCIe" ] || { echo "FATAL: link speed '$SPEED' != 8.0 GT/s"; exit 1; }
[ "$WIDTH" = "8" ] || { echo "FATAL: link width '$WIDTH' != 8"; exit 1; }
ls -la /dev/xdma0_user /dev/xdma0_h2c_0 /dev/xdma0_c2h_0

step "5. CSR sanity (MAGIC/VERSION/CALIB)"
python3 - "$EXPECT_VER" <<'EOF'
import os, sys, time
fd = os.open("/dev/xdma0_user", os.O_RDWR)
rd = lambda a: int.from_bytes(os.pread(fd, 4, a), "little")
magic, ver = rd(0x0), rd(0x4)
print(f"MAGIC   = {magic:08x}")
print(f"VERSION = {ver:08x}")
assert magic == 0xFAB1E001, "MAGIC mismatch — wrong design?"
assert ver == int(sys.argv[1], 16), "VERSION mismatch — stale bitstream?"
for i in range(50):
    calib = rd(0xC)
    if calib == 0xF: break
    time.sleep(0.2)
print(f"CALIB   = {calib:x} (after {i*0.2:.1f}s)")
assert calib == 0xF, "not all DDR4 channels calibrated"
u0 = rd(0x10); time.sleep(0.1); u1 = rd(0x10)
print(f"UPTIME ticking: {u0:08x} -> {u1:08x}")
assert u1 != u0, "uptime not ticking"
os.pwrite(fd, (0x5AA5C33C).to_bytes(4,'little'), 0x8)
assert rd(0x8) == 0x5AA5C33C, "scratch readback failed"
print("CSR SANITY PASS")
EOF

step "6. quick integrity test (64 MiB/channel)"
"$REPO/sw/.venv/bin/python" "$SCRIPT_DIR/ddr_test.py" "${NL[@]}" --quick --evidence "$EV"

step "7. FULL integrity test: 4 seeds x 2 runs x 4 ch x 4 GiB, no reprogram"
"$REPO/sw/.venv/bin/python" "$SCRIPT_DIR/ddr_test.py" "${NL[@]}" --evidence "$EV"

step "DONE — STAGE1 HARDWARE GATE PASSED"
echo "log: $LOG"
