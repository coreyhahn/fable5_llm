#!/bin/bash
# pcie_helper.sh — root-required PCIe ops for the BCU-1525 on snoke (82:00.0).
#
# The ONLY safe reprogram flow (avoids host MMIO to a dead endpoint, which
# can kernel-panic the host):
#   1. sudo ./pcie_helper.sh remove     # detach driver + remove from PCI tree
#   2. program new bitstream via JTAG   (sw/program_fpga.sh)
#   3. sudo ./pcie_helper.sh rescan     # re-enumerate, driver rebinds
#
# After a HOST REBOOT the xdma kernel module is gone (it does not auto-load),
# so remove/rescan have nothing to rebind. Run `load` once post-reboot:
#   sudo ./pcie_helper.sh load          # insmod xdma.ko + chmod /dev nodes
#
# Suggested sudoers line (visudo), if you want me to run this unattended:
#   <user> ALL=(root) NOPASSWD: /absolute/path/to/sw/pcie_helper.sh   (template — adjust to your checkout)
# (note: this file must then be root-owned or you accept that cah-writable
#  script == root; alternative is to run the two commands manually each time)
set -euo pipefail

BDF=${BDF:-0000:82:00.0}
DEV=/sys/bus/pci/devices/$BDF

case "${1:?usage: pcie_helper.sh load|remove|rescan|status}" in
  load)
    # insmod the XDMA PCIe driver (dma_ip_drivers) if not already resident,
    # then make the char devices user-accessible. The module does NOT
    # survive a host reboot; remove/rescan assume it is already loaded, so
    # this must run first after any reboot.
    KO=${XDMA_KO:-/home/cah/r2d2/code/fpga/references/dma_ip_drivers/XDMA/linux-kernel/xdma/xdma.ko}
    if lsmod | grep -q '^xdma '; then
        echo "xdma already loaded"
    else
        [ -f "$KO" ] || { echo "FATAL: xdma.ko not found at $KO" >&2; exit 1; }
        insmod "$KO"
        echo "insmod $KO OK"
    fi
    sleep 1
    if ls /dev/xdma0_user >/dev/null 2>&1; then
        chmod a+rw /dev/xdma0_* 2>/dev/null || true
        echo "load OK: $(ls /dev/xdma0_* | tr '\n' ' ')"
    else
        echo "load: /dev/xdma0_* did not appear (is $BDF enumerated?)" >&2
        exit 1
    fi
    ;;
  remove)
    if [ -e "$DEV" ]; then
        echo 1 > "$DEV/remove"
        echo "removed $BDF from PCI tree"
    else
        echo "$BDF not present (already removed?)"
    fi
    ;;
  rescan)
    echo 1 > /sys/bus/pci/rescan
    sleep 2
    if [ -e "$DEV" ]; then
        echo "rescan OK: $(lspci -s ${BDF#0000:})"
        # make xdma char devices accessible to the user
        chmod a+rw /dev/xdma0_* 2>/dev/null || true
    else
        echo "rescan: $BDF did NOT come back" >&2
        exit 1
    fi
    ;;
  status)
    lspci -s "${BDF#0000:}" -vv | head -25 || echo "$BDF not present"
    ;;
  debug)
    echo "##### endpoint lspci -vvv"
    lspci -s "${BDF#0000:}" -vvv 2>/dev/null || echo "$BDF not present"
    echo "##### root port ${RP:-0000:80:02.0} lspci -vvv"
    lspci -s "${RP_BDF:-80:02.0}" -vvv 2>/dev/null
    echo "##### kernel log tail"
    dmesg | tail -60
    ;;
  sbr)
    # Secondary Bus Reset on the root port: hot-resets the endpoint, forces
    # full retrain + re-enumeration. Endpoint must be removed first.
    RP=${RP_BDF:-80:02.0}
    if [ -e "$DEV" ]; then
        echo 1 > "$DEV/remove"
        echo "removed $BDF"
    fi
    sleep 1
    BCTL=$(setpci -s $RP BRIDGE_CONTROL)
    echo "root port BRIDGE_CONTROL=$BCTL"
    setpci -s $RP BRIDGE_CONTROL=$(printf %04x $((0x$BCTL | 0x40)))
    sleep 0.2
    setpci -s $RP BRIDGE_CONTROL=$BCTL
    sleep 1
    echo 1 > /sys/bus/pci/rescan
    sleep 2
    if [ -e "$DEV" ]; then
        echo "SBR+rescan OK: $(lspci -s ${BDF#0000:})"
        chmod a+rw /dev/xdma0_* 2>/dev/null || true
    else
        echo "SBR: $BDF did not come back" >&2
        exit 1
    fi
    ;;
  cfgkick)
    # Issue a benign Type-0 config WRITE to the endpoint (rewrite COMMAND
    # with its current value) so the PCIe block gets a fresh chance to
    # capture its bus/device number.
    CMD=$(setpci -s ${BDF#0000:} COMMAND)
    echo "COMMAND=$CMD (rewriting same value)"
    setpci -s ${BDF#0000:} COMMAND=$CMD
    echo "config write issued"
    ;;
  peek)
    # Dump key XDMA BAR0 registers via mmap of resource0 (root required).
    python3 - "$DEV/resource0" <<'PYEOF'
import mmap, sys
with open(sys.argv[1], "r+b") as f:
    m = mmap.mmap(f.fileno(), 65536)
    for off in (0x0000, 0x0004, 0x0040, 0x1000, 0x2000, 0x3000, 0x3004):
        v = int.from_bytes(m[off:off+4], "little")
        print(f"BAR0+{off:04x} = {v:08x}")
PYEOF
    ;;
  *)
    echo "usage: pcie_helper.sh load|remove|rescan|status|debug|sbr|cfgkick|peek" >&2
    exit 1
    ;;
esac
