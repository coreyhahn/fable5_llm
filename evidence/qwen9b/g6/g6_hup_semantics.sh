#!/usr/bin/env bash
# g6_hup_semantics.sh — what bash ACTUALLY does with SIGHUP and an EXIT trap.
#
#   bash evidence/qwen9b/g6/g6_hup_semantics.sh
#
# Two shells, identical but for one word in the trap line, each hung up 1 s
# into an 8 s foreground command.  Reported for each: WHEN the handler ran
# relative to the signal, HOW MANY TIMES, and the EXIT CODE the caller sees.
# No board, no sudo, no device.
set -uo pipefail
P=$(mktemp -t hupsem.XXXXXX)
cat > "$P" <<'INNER'
#!/bin/bash
set -euo pipefail
MODE=$1
on_exit(){ rc=$?; echo "HANDLER-RAN rc=$rc t=$(date +%s.%N)"; exit $rc; }
if [ "$MODE" = with ]; then
    trap on_exit EXIT INT TERM HUP
else
    trap on_exit EXIT INT TERM
fi
echo "START t=$(date +%s.%N)"
sleep 8
echo "FOREGROUND-COMMAND-RETURNED"
INNER
chmod +x "$P"
trap 'rm -f "$P" /tmp/hupsem.out.*' EXIT

echo "=== bash: $(bash --version | head -1)"
for m in without with; do
    echo "=== ----------------------------------------------------------"
    echo "=== trap on_exit EXIT INT TERM$([ "$m" = with ] && echo ' HUP')"
    O=/tmp/hupsem.out.$m
    "$P" "$m" > "$O" 2>&1 &
    PID=$!
    sleep 1
    T0=$(date +%s.%N)
    echo "=== kill -HUP $PID at t=$T0  (the foreground 'sleep 8' has ~7 s left)"
    kill -HUP "$PID"
    wait "$PID"; RC=$?
    echo "=== the caller sees rc=$RC"
    cat "$O"
    N=$(grep -c HANDLER-RAN "$O")
    TH=$(grep -m1 HANDLER-RAN "$O" | sed 's/.*t=//')
    echo "=== handler ran $N time(s); first at t=$TH"
    python3 -c "print('=== DELAY from signal to handler: %.3f s' % ($TH - $T0))"
done
