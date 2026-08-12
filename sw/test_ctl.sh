#!/bin/bash
# test_ctl.sh — program a control bitstream and test BUSDEV + DMA to BRAM.
# Usage: ./test_ctl.sh <A|B>
set -euo pipefail
V=${1:?A or B}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$SCRIPT_DIR/.." && pwd)
BIT=$(ls $REPO/synth/out_ctl_$V/proj/ctl$V.runs/impl_1/*.bit)
PCIE="sudo -n $SCRIPT_DIR/pcie_helper.sh"

echo "=== control $V: $BIT"
$PCIE remove
"$SCRIPT_DIR/program_fpga.sh" "$BIT"
$PCIE rescan
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
