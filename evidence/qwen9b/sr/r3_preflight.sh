#!/usr/bin/env bash
# r3_preflight.sh — Task R3-0 (iii): the READ-ONLY pre-flight for the R3 board
# session (R3-11), built from evidence/qwen9b/sr/sr15_preflight.sh's checks
# (NEXT_SESSION.md §9 (f) rules 5 and 7; backlog item 11 entry 6) with:
#   * the tree must be CLEAN: any modified tracked file or untracked file
#     FAILS (sr15 only printed `git status`); excluded ONLY the session's own
#     in-flight logs, untracked evidence/qwen9b/sr/<prefix>NN_* (default
#     prefix n33 — R3-11's block n3300..n3399);
#   * every per-session value is an ARGUMENT (the ruled bitstream's path,
#     size and FULL sha256; build_041's; the twins it must NOT be; the stream
#     and chat-image pins; the admission rows; the expected identity), so the
#     session runs the COMMITTED tool with arguments and never edits it into
#     a dirty tree;
#   * the repo root is an argument (--root, default the repo), and every
#     command that touches the board or the lock is a VARIABLE whose default
#     is sr15's command, so the whole tool can be exercised board-free
#     (evidence/qwen9b/sr/r3_tool_tdd.sh case (e)):
#       PF_PY           the interpreter            /home/cah/.venv/bin/python
#       PF_IDENT        the identity read          $PF_PY evidence/qwen9b/sr/sr8_ident.py --expect <ver> [--want-caps <caps>]
#       PF_LOCK_STATUS  the board lock             python3 sw/board_lock.py --status
#       PF_HWSERVER     hw_server running          pgrep -a hw_server
#       PF_PROCS        every Vivado-family proc   pgrep -af 'vivado|hw_server|xsdb|hw_manager'
#       PF_SS           attached :3121 clients     ss -tnp state established '( sport = :3121 or dport = :3121 )'
#       PF_LSPCI        the PCI ID                 lspci -nn -s 82:00.0
#       PF_XDMA_LS      the /dev/xdma0_* nodes     ls -l /dev/xdma0_user /dev/xdma0_h2c_0 /dev/xdma0_c2h_0
#       PF_LSMOD        the xdma module            lsmod
#       PF_BOARD_USERS  other board tools          pgrep -af 'chat_seq|seq_run|bm1_census|sr8_census|g6_state|serve.py|ddr_test'
#     each printed at the top as DEFAULT or OVERRIDE.
# PASS still REQUIRES the board to read build_041's identity (no
# auto-program); any ESTABLISHED client of hw_server's port 3121 FAILS (and
# sw/program_fpga.sh repeats that check inside its own lock hold).
# Touches no board state: no lock taken, no DMA, no SEQ window, no sudo.
# Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.  Prints PREFLIGHT: PASS
# / FAIL; exit 0 only on PASS, 2 on a usage error.
#
#   r3_preflight.sh --bit <path> --bit-size <bytes> --bit-sha256 <64 hex>
#       [--root <dir>] [--b41-bit <path> --b41-size <n> --b41-sha256 <hex>]
#       [--twin <path>=<64 hex>]... [--stream <path>=<64 hex>]...
#       [--manifest <prefix>]...        (<prefix>.seq's sha256 == <prefix>.seq.json stream_sha256)
#       [--chat-pin <DICT>=<64 hex>]... (the hash appears in sw/chat_seq.py's DICT block)
#       [--pin-line <file>::<exact line>]...
#       [--admit <hex8>]...             (a 0x<hex8> row in sw/seq_run.py)
#       [--ident-version <hex8>] [--ident-caps <caps>] [--boot '<YYYY-MM-DD HH:MM>']
#       [--session-log-prefix <nNN>]
# Relative paths are relative to --root.
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
BIT= BITSZ= BITSHA=
B41BIT=synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper.bit
B41SZ=53074589
B41SHA=eeeef897495d783aa4eb0b2b555373bbeed36182a4a754089d787b801224f031
TWINS=(); STREAMS=(); MANIFESTS=(); CHATPINS=(); PINLINES=(); ADMITS=()
IDENT_VER=c973c18a
IDENT_CAPS=
BOOT=
SLP=n33
usage() { sed -n '/^#   r3_preflight.sh --bit/,/^# Relative paths/p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
die() { echo "r3_preflight: $*" >&2; exit 2; }
is64() { [[ "$1" =~ ^[0-9a-f]{64}$ ]]; }
while [ $# -gt 0 ]; do
    [ $# -ge 2 ] || die "$1 needs a value"
    case "$1" in
        --root)               ROOT=$2 ;;
        --bit)                BIT=$2 ;;
        --bit-size)           BITSZ=$2 ;;
        --bit-sha256)         BITSHA=$2 ;;
        --b41-bit)            B41BIT=$2 ;;
        --b41-size)           B41SZ=$2 ;;
        --b41-sha256)         B41SHA=$2 ;;
        --twin)               TWINS+=("$2") ;;
        --stream)             STREAMS+=("$2") ;;
        --manifest)           MANIFESTS+=("$2") ;;
        --chat-pin)           CHATPINS+=("$2") ;;
        --pin-line)           PINLINES+=("$2") ;;
        --admit)              ADMITS+=("$2") ;;
        --ident-version)      IDENT_VER=$2 ;;
        --ident-caps)         IDENT_CAPS=$2 ;;
        --boot)               BOOT=$2 ;;
        --session-log-prefix) SLP=$2 ;;
        *)                    echo "r3_preflight: unknown argument $1" >&2; usage ;;
    esac
    shift 2
done
# every value validated BEFORE anything runs: a full sha256 or nothing
[ -n "$BIT" ] && [ -n "$BITSZ" ] && [ -n "$BITSHA" ] || { echo "r3_preflight: --bit, --bit-size and --bit-sha256 are required" >&2; usage; }
is64 "$BITSHA" || die "--bit-sha256 '$BITSHA' is not a FULL sha256 (64 lower-case hex)"
is64 "$B41SHA" || die "--b41-sha256 '$B41SHA' is not a FULL sha256"
[[ "$BITSZ" =~ ^[0-9]+$ && "$B41SZ" =~ ^[0-9]+$ ]] || die "sizes must be byte counts"
for kv in "${TWINS[@]}" "${STREAMS[@]}" "${CHATPINS[@]}"; do
    [[ "$kv" == *=* ]] || die "'$kv' is not <name>=<sha256>"
    is64 "${kv##*=}" || die "'$kv': '${kv##*=}' is not a FULL sha256"
done
for pl in "${PINLINES[@]}"; do [[ "$pl" == *::* ]] || die "--pin-line '$pl' is not <file>::<line>"; done
for v in "${ADMITS[@]}" "$IDENT_VER"; do [[ "$v" =~ ^[0-9a-fA-F]{8}$ ]] || die "'$v' is not an 8-hex VERSION"; done
[[ "$SLP" =~ ^n[0-9]{1,3}$ ]] || die "--session-log-prefix '$SLP' is not n<digits>"
cd "$ROOT" || die "cannot cd to --root $ROOT"
ROOT=$(pwd)

: "${PF_PY:=}"
PROBES=(PF_PY PF_IDENT PF_LOCK_STATUS PF_HWSERVER PF_PROCS PF_SS PF_LSPCI PF_XDMA_LS PF_LSMOD PF_BOARD_USERS)
declare -A SRC
for v in "${PROBES[@]}"; do [ -n "${!v:-}" ] && SRC[$v]=OVERRIDE || SRC[$v]=DEFAULT; done
: "${PF_PY:=/home/cah/.venv/bin/python}"
IDENT_CAPS_ARG=; [ -n "$IDENT_CAPS" ] && IDENT_CAPS_ARG=" --want-caps $IDENT_CAPS"
: "${PF_IDENT:=$PF_PY evidence/qwen9b/sr/sr8_ident.py --expect $IDENT_VER$IDENT_CAPS_ARG}"
: "${PF_LOCK_STATUS:=python3 sw/board_lock.py --status}"
: "${PF_HWSERVER:=pgrep -a hw_server}"
: "${PF_PROCS:=pgrep -af 'vivado|hw_server|xsdb|hw_manager'}"
: "${PF_SS:=ss -tnp state established '( sport = :3121 or dport = :3121 )'}"
: "${PF_LSPCI:=lspci -nn -s 82:00.0}"
: "${PF_XDMA_LS:=ls -l /dev/xdma0_user /dev/xdma0_h2c_0 /dev/xdma0_c2h_0}"
: "${PF_LSMOD:=lsmod}"
: "${PF_BOARD_USERS:=pgrep -af 'chat_seq|seq_run|bm1_census|sr8_census|g6_state|serve.py|ddr_test'}"

FAIL=0
bad() { echo "  FAIL: $*"; FAIL=1; }
abspath() { case "$1" in /*) echo "$1" ;; *) echo "$ROOT/$1" ;; esac; }

echo "--- [0] root $ROOT; probes (DEFAULT = sr15's command, OVERRIDE = set by the caller)"
for v in "${PROBES[@]}"; do printf '  %-15s %-8s %s\n' "$v" "${SRC[$v]}" "${!v}"; done
echo "--- [1] board lock"
LS=$(eval "$PF_LOCK_STATUS" 2>&1); echo "$LS"
echo "$LS" | grep -q 'state *not held' || bad "the board lock is held"
echo "--- [2] hw_server, and every vivado / hw_server / xsdb / hw_manager process"
eval "$PF_HWSERVER" || bad "hw_server is not running"
echo "  all matching processes:"
eval "$PF_PROCS" | grep -v -E 'pgrep|r3_preflight' | sed 's/^/    /' || echo "    none"
echo "  established TCP connections to hw_server port 3121 (an attached hw_manager client):"
if ! SSO=$(eval "$PF_SS" 2>&1); then
    echo "$SSO" | sed 's/^/    /'; bad "could not list port-3121 connections"
else
    EST=$(printf '%s\n' "$SSO" | tail -n +2 | grep -v '^[[:space:]]*$')
    if [ -n "$EST" ]; then echo "$EST" | sed 's/^/    /'; bad "a client is attached to hw_server (port 3121)"; else echo "    none"; fi
fi
echo "--- [3] uptime / last boot"
uptime; BOOTNOW=$(who -b | awk '{print $3" "$4}'); echo "boot: $BOOTNOW"
if [ -n "$BOOT" ]; then [ "$BOOTNOW" = "$BOOT" ] || bad "the host rebooted since '$BOOT' (now '$BOOTNOW')"; else echo "  (no --boot given: printed only)"; fi
echo "--- [4] PCI ID at 82:00.0 (want 10ee:9038; 1e24:1525 = factory image), xdma nodes, module"
LP=$(eval "$PF_LSPCI" 2>&1); echo "$LP"
echo "$LP" | grep -q '10ee:9038' || bad "82:00.0 is not 10ee:9038"
eval "$PF_XDMA_LS" || bad "xdma nodes missing"
eval "$PF_LSMOD" | grep '^xdma ' || bad "xdma module not loaded"
echo "--- [5] what is on the board (raw reads, no DMA) — MUST be VERSION $IDENT_VER (build_041 unless named)"
eval "$PF_IDENT" || bad "the board does NOT read the expected identity $IDENT_VER (STOP, hand back)"
echo "--- [6] the bitstreams this session may program (size, FULL sha256), and the twins it must NOT"
for trip in "$BIT|$BITSHA|$BITSZ" "$B41BIT|$B41SHA|$B41SZ"; do
    IFS='|' read -r f want wsz <<< "$trip"; f=$(abspath "$f")
    if [ ! -f "$f" ]; then bad "$f does not exist"; continue; fi
    ls -la --time-style=full-iso "$f"
    S=$(stat -c %s "$f"); Hh=$(sha256sum "$f" | cut -d' ' -f1)
    echo "  size $S sha256 $Hh"
    [ "$S" = "$wsz" ] || bad "$f size $S != $wsz"
    [ "$Hh" = "$want" ] || bad "$f sha256 != $want"
done
for kv in "${TWINS[@]}"; do
    f=$(abspath "${kv%=*}"); want=${kv##*=}
    if [ ! -f "$f" ]; then bad "twin $f does not exist"; continue; fi
    TH=$(sha256sum "$f" | cut -d' ' -f1); echo "  TWIN (never programmed) $f sha256 $TH"
    [ "$TH" = "$want" ] && [ "$TH" != "$BITSHA" ] && echo "  the twin differs from the ruled file: OK" \
        || bad "twin $f hash unexpected (or equal to the ruled file)"
done
echo "--- [7] stream pins (FULL sha256)"
[ ${#STREAMS[@]} = 0 ] && echo "  (none given)"
for kv in "${STREAMS[@]}"; do
    f=$(abspath "${kv%=*}"); want=${kv##*=}
    Hh=$(sha256sum "$f" 2>/dev/null | cut -d' ' -f1); echo "  $f ${Hh:-MISSING}"
    [ "$Hh" = "$want" ] || bad "$f sha256 != $want"
done
echo "--- [7b] streams vs their manifests (.seq sha256 == .seq.json stream_sha256, FULL)"
[ ${#MANIFESTS[@]} = 0 ] && echo "  (none given)"
for p in "${MANIFESTS[@]}"; do
    f=$(abspath "$p")
    Hh=$(sha256sum "$f.seq" 2>/dev/null | cut -d' ' -f1)
    M=$("$PF_PY" -c 'import json,sys;print(json.load(open(sys.argv[1]))["stream_sha256"])' "$f.seq.json" 2>&1)
    echo "  $p.seq ${Hh:-MISSING} manifest $M"
    [ -n "$Hh" ] && [ "$Hh" = "$M" ] || bad "$p stream sha256 != its manifest"
done
echo "--- [8] chat image pins in sw/chat_seq.py (FULL sha256), and pin-log lines"
[ ${#CHATPINS[@]} = 0 ] && echo "  (none given)"
for kv in "${CHATPINS[@]}"; do
    d=${kv%=*}; want=${kv##*=}
    P=$(sed -n "/^$d/,/^}/p" sw/chat_seq.py | tr -d ' \n"')
    [ -n "$P" ] || { bad "no $d block in sw/chat_seq.py"; continue; }
    echo "$P" | grep -q "$want" && echo "  $d has $want" || bad "$d pin $want"
done
for pl in "${PINLINES[@]}"; do
    f=${pl%%::*}; line=${pl#*::}
    grep -q -x -F -- "$line" "$(abspath "$f")" && echo "  $f: '$line'" || bad "$f has no line '$line'"
done
echo "--- [9] the admission rows (sw/seq_run.py)"
[ ${#ADMITS[@]} = 0 ] && echo "  (none given)"
for v in "${ADMITS[@]}"; do
    grep -n -i "0x$v" sw/seq_run.py | head -4
    grep -q -i "0x$v" sw/seq_run.py || bad "no 0x$v admission row in sw/seq_run.py"
done
echo "--- [10] the interpreter ($PF_PY)"
"$PF_PY" -c 'import sys,numpy;print(sys.executable, sys.version.split()[0], "numpy", numpy.__version__)' || bad "interpreter $PF_PY"
echo "--- [11] git: the tree must be CLEAN (excluded: untracked evidence/qwen9b/sr/${SLP}NN_* session logs)"
git log --oneline -1
DIRTY=$(git status --porcelain | grep -v -E "^\?\? evidence/qwen9b/sr/${SLP}[0-9]{2}[a-z]?_")
if [ -n "$DIRTY" ]; then
    echo "$DIRTY" | sed 's/^/    /'
    bad "the tree $ROOT is dirty ($(printf '%s\n' "$DIRTY" | wc -l) entries)"
else
    echo "  clean"
fi
echo "--- [12] other board users"
eval "$PF_BOARD_USERS" | grep -v -E 'pgrep|r3_preflight' || echo "  none"
echo "PREFLIGHT: $([ $FAIL = 0 ] && echo PASS || echo FAIL)"
exit $FAIL
