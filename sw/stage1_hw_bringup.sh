#!/bin/bash
# stage1_hw_bringup.sh — full stage-1 hardware bring-up on snoke, unattended.
# Requires: sudoers NOPASSWD for sw/pcie_helper.sh.
# Usage: ./stage1_hw_bringup.sh <bitfile> <expected_version_hex8>
# Logs everything to evidence/stage1/hw_bringup_<ts>.log; exits nonzero on
# any gate failure. Safe-reprogram flow: remove -> JTAG -> rescan.
set -euo pipefail

BIT=${1:?usage: stage1_hw_bringup.sh <bitfile> <version_hex8>}
EXPECT_VER=${2:?need expected version (git short8 hex)}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$SCRIPT_DIR/.." && pwd)
TS=$(date +%Y%m%d_%H%M%S)
EV="$REPO/evidence/stage1"
LOG="$EV/hw_bringup_${TS}.log"
mkdir -p "$EV"
exec > >(tee "$LOG") 2>&1

PCIE="sudo -n $SCRIPT_DIR/pcie_helper.sh"
BDF=82:00.0

step() { echo; echo "=== [$(date +%H:%M:%S)] $* ==="; }

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
    $PCIE remove

    step "2. JTAG program (volatile)"
    "$SCRIPT_DIR/program_fpga.sh" "$BIT"

    step "3. rescan PCIe"
    $PCIE rescan
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
"$REPO/sw/.venv/bin/python" "$SCRIPT_DIR/ddr_test.py" --quick --evidence "$EV"

step "7. FULL integrity test: 4 seeds x 2 runs x 4 ch x 4 GiB, no reprogram"
"$REPO/sw/.venv/bin/python" "$SCRIPT_DIR/ddr_test.py" --evidence "$EV"

step "DONE — STAGE1 HARDWARE GATE PASSED"
echo "log: $LOG"
