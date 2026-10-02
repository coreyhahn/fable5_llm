#!/usr/bin/env bash
# g6_hup_trap.sh — does a dropped ssh leave the endpoint OFF THE BUS?
#
#   bash evidence/qwen9b/g6/g6_hup_trap.sh red     # the trap line as it was
#   bash evidence/qwen9b/g6/g6_hup_trap.sh green   # the trap line as it is
#
# THE HAZARD.  sw/program_fpga.sh removes the endpoint from the PCI tree,
# JTAGs, and rescans, and its whole design promise is that "THE ENDPOINT
# ALWAYS COMES BACK … Every exit path after a successful `remove` … runs the
# rescan through an EXIT trap".  Its trap listed EXIT INT TERM and NOT HUP,
# and HUP is precisely what a dropped ssh delivers — which is how every
# board step in this campaign is driven.  An untrapped SIGHUP is fatal to
# bash and does not run the EXIT trap, so the window between [1/3] and [3/3]
# was open to exactly the failure mode the script exists to prevent.
#
# THE BOARD IS NOT TOUCHED BY THIS TEST.  The 9B weight pack is resident and
# a reprogram would wipe 5.8 GiB of DDR, so the sequence is STUBBED: a copy
# of the script runs against stub `pcie_helper.sh`, `sudo`, `vivado` and
# `board_lock.py`, and the Vivado settings64.sh source is redirected to a
# stub that puts the stub bin on PATH.  Nothing here calls sudo, opens
# /dev/xdma0_*, or runs Vivado.  The diff between the copy and the committed
# script is PRINTED, so what was stubbed is on the record.
#
# GREEN runs the COMMITTED bytes of the trap line.  RED puts back the one
# word, and only that word.
set -uo pipefail
cd "$(dirname "$0")/../../.."
MODE=${1:?usage: g6_hup_trap.sh red|green}

T=$(mktemp -d -t g6hup.XXXXXX)
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin"

# ---- the stubs -------------------------------------------------------
cat > "$T/pcie_helper.sh" <<'EOF'
#!/bin/bash
echo "STUB-PCIE $*"
EOF
cat > "$T/bin/sudo" <<'EOF'
#!/bin/bash
# drop -n and exec the rest: the stub pcie_helper needs no privilege
[ "${1:-}" = "-n" ] && shift
exec "$@"
EOF
cat > "$T/bin/vivado" <<'EOF'
#!/bin/bash
# stand in for the JTAG step, long enough to be interrupted
for i in 1 2 3 4 5 6 7 8 9 10; do sleep 0.5; done
echo "PROGRAM_OK: stub"
EOF
cat > "$T/board_lock.py" <<'EOF'
import sys
# --check-inherited exits 0 => the copy proceeds WITHOUT taking the real
# board lock and without re-execing itself under it.
sys.exit(0 if "--check-inherited" in sys.argv else 1)
EOF
cat > "$T/settings64_stub.sh" <<EOF
export PATH="$T/bin:\$PATH"
EOF
chmod +x "$T/pcie_helper.sh" "$T/bin/sudo" "$T/bin/vivado"
: > "$T/stub.bit"

# ---- the copy under test ---------------------------------------------
cp sw/program_fpga.sh "$T/program_fpga.sh"
sed -i "s#/home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh#$T/settings64_stub.sh#" \
    "$T/program_fpga.sh"
if [ "$MODE" = red ]; then
    sed -i 's/^trap on_exit EXIT INT TERM HUP$/trap on_exit EXIT INT TERM/' \
        "$T/program_fpga.sh"
fi
chmod +x "$T/program_fpga.sh"

echo "=== MODE: $MODE"
echo "=== the trap line under test:"
grep -n '^trap on_exit' "$T/program_fpga.sh"
echo "=== what was stubbed (copy vs the committed sw/program_fpga.sh):"
diff -u sw/program_fpga.sh "$T/program_fpga.sh" | sed -n '1,40p'
echo "=== ---"

OUT=$T/out.txt
# The stub bin must be on PATH BEFORE [1/3], not only after the settings64
# source at [2/3]: the first thing the script does is `sudo -n pcie_helper.sh
# remove`.  (The first cut of this harness set it only in the settings64 stub,
# and the real sudo REFUSED the stub path for want of a password — which is
# itself the NOPASSWD rule working exactly as CLAUDE.md describes it: the
# escape is granted to ONE absolute path, and a stub in /tmp is not it.)
export PATH="$T/bin:$PATH"
"$T/program_fpga.sh" "$T/stub.bit" > "$OUT" 2>&1 &
PID=$!

# wait for the script to be INSIDE the window: past [1/3] remove, in [2/3]
for i in $(seq 1 100); do
    grep -q '\[2/3\] JTAG program' "$OUT" 2>/dev/null && break
    sleep 0.1
done
if ! grep -q '\[2/3\] JTAG program' "$OUT"; then
    echo "HARNESS FAILED: never reached [2/3]"; cat "$OUT"; exit 2
fi
echo "=== the endpoint is now REMOVED and the JTAG step is running:"
cat "$OUT"
echo "=== sending SIGHUP to pid $PID (this is what a dropped ssh delivers)"
kill -HUP "$PID"
wait "$PID"; RC=$?
echo "=== the script exited with rc=$RC"
echo "=== its full output:"
cat "$OUT"
echo "=== ---"

if grep -q '\[3/3\] rescan' "$OUT"; then
    echo "RESCAN: RAN — the endpoint was put back"
    RESCAN=1
else
    echo "RESCAN: DID NOT RUN — THE ENDPOINT IS OFF THE BUS"
    RESCAN=0
fi

if [ "$MODE" = red ]; then
    if [ "$RESCAN" = 0 ]; then
        echo "G6_HUP_TRAP RED: CONFIRMED — without HUP in the trap, SIGHUP"
        echo "  killed the script between [1/3] remove and [3/3] rescan and"
        echo "  the rescan never ran (rc=$RC)."
        exit 0
    fi
    echo "G6_HUP_TRAP RED: DID NOT FIRE — the negative control is vacuous"
    exit 1
else
    if [ "$RESCAN" = 1 ]; then
        echo "G6_HUP_TRAP GREEN: the committed trap line rescanned on SIGHUP"
        echo "  (rc=$RC; 129 = 128 + SIGHUP)."
        exit 0
    fi
    echo "G6_HUP_TRAP GREEN: FAILED — the rescan did not run"
    exit 1
fi
