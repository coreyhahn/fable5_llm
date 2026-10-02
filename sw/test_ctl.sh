#!/bin/bash
# test_ctl.sh — program a control bitstream and test BUSDEV + DMA to BRAM.
# Usage: ./test_ctl.sh [--no-lock] <A|B>
#
# O3 (user ruling 2026-08-29): this script does BOTH dangerous things — a
# bare `pcie_helper.sh remove`/`rescan` pair around a reprogram, and raw
# pread/pwrite on /dev/xdma0_* including a 4 KiB H2C DMA — and until now it
# took no lock at all.  Worse, once program_fpga.sh started locking, THAT
# call took and RELEASED a lock of its own, so the remove/rescan window and
# the DMA on either side of it were still unprotected while looking locked.
#
# The whole script is now ONE hold, taken here and INHERITED by
# program_fpga.sh (which is why it is called with --jtag-only: this script
# owns the remove/rescan, and it owns the lock across them).
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
NO_LOCK=0
POS=()
for a in "$@"; do
    case "$a" in
        --no-lock) NO_LOCK=1 ;;
        *)         POS+=("$a") ;;
    esac
done
V=${POS[0]:?usage: test_ctl.sh [--no-lock] <A|B>}

# NL is passed DOWN: without it program_fpga.sh would take a lock of its own
# inside a --no-lock run and could REFUSE after the endpoint is already out.
NL=()
if [ "$NO_LOCK" = 1 ]; then
    python3 "$SCRIPT_DIR/board_lock.py" \
        --tool "test_ctl.sh $V" --announce-no-lock || true
    NL=(--no-lock)
elif ! python3 "$SCRIPT_DIR/board_lock.py" --check-inherited >/dev/null 2>&1
then
    exec python3 "$SCRIPT_DIR/board_lock.py" \
        --tool "test_ctl.sh $V" --exec -- "$0" "$@"
fi

REPO=$(cd "$SCRIPT_DIR/.." && pwd)
BIT=$(ls $REPO/synth/out_ctl_$V/proj/ctl$V.runs/impl_1/*.bit)
PCIE="sudo -n $SCRIPT_DIR/pcie_helper.sh"
NEED_RESCAN=0

# The endpoint comes back on every exit path (see sw/program_fpga.sh).
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

echo "=== control $V: $BIT"
NEED_RESCAN=1                     # armed BEFORE the remove — see program_fpga.sh
$PCIE remove
# --jtag-only: THIS script owns remove/rescan and already holds the board
# lock, which program_fpga.sh inherits instead of taking a second one.
"$SCRIPT_DIR/program_fpga.sh" --jtag-only "${NL[@]}" "$BIT"
$PCIE rescan
NEED_RESCAN=0
D=/sys/bus/pci/devices/0000:82:00.0
echo "link: $(cat $D/current_link_speed) x$(cat $D/current_link_width)"
python3 - <<'PYEOF'
import os, time
fd = os.open("/dev/xdma0_control", os.O_RDONLY)
rd = lambda a: int.from_bytes(os.pread(fd, 4, a), "little")
print(f"BUSDEV = {rd(0x3004):08x}")
hfd = os.open("/dev/xdma0_h2c_0", os.O_WRONLY)
t0 = time.monotonic()
try:
    pat = bytes(range(256)) * 16
    n = os.pwrite(hfd, pat, 0)
    print(f"DMA H2C: {n}B in {time.monotonic()-t0:.3f}s")
    cfd = os.open("/dev/xdma0_c2h_0", os.O_RDONLY)
    data = os.pread(cfd, 4096, 0)
    ok = "MATCH" if data == pat else "MISMATCH"
    print(f"DMA C2H: {len(data)}B, payload {ok}")
    print("CTL_DMA_PASS" if data == pat else "CTL_DMA_FAIL")
except OSError as e:
    print(f"DMA FAILED after {time.monotonic()-t0:.2f}s: {e}")
    print("CTL_DMA_FAIL")
PYEOF
