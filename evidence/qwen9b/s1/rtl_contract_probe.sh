#!/usr/bin/env bash
# rtl_contract_probe.sh — is sdma_bits.py's RED STRUCTURAL?
#
# THE QUESTION.  `evidence/qwen9b/s1/sdma_bits.py` fails on this tree with
# "rtl/layer_chan.sv has no OP_SLD".  A broken parser would say exactly the
# same thing about an RTL file that DID carry the anchors, and S1 would then
# be shipping an instrument that can never go green.  So the RED is proved
# structural, in three parts, against a fixture that carries the anchors and
# nothing else (evidence/qwen9b/s1/s2_contract_stub.sv):
#
#   1. POSITIVE  the census GREEN on all four views against the stub, and
#                every perturbation — including the two new rtl ones —
#                CAUGHT.
#   2. NEGATIVE  each of the eighteen anchors deleted from a copy of the
#                stub in turn; each deletion must produce a SystemExit that
#                NAMES the missing anchor.  An anchor the parser silently
#                skips is an anchor that proves nothing.
#   3. THE TREE  the same census against the real rtl/layer_chan.sv, which
#                has none of them — S1's committed RED.
#
#   bash evidence/qwen9b/s1/rtl_contract_probe.sh
set -u
cd "$(dirname "$0")/../../.."
STUB=evidence/qwen9b/s1/s2_contract_stub.sv
BITS=evidence/qwen9b/s1/sdma_bits.py
TMP=$(mktemp -d "${TMPDIR:-/tmp}/s1_probe.XXXXXX")
bad=0

echo "=== 1. POSITIVE — the census against the stub"
SDMA_BITS_RTL=$STUB python3 "$BITS" 2>&1 | tail -1
SDMA_BITS_RTL=$STUB python3 "$BITS" >/dev/null 2>&1 || { echo "  *** the stub does not go GREEN"; bad=$((bad+1)); }
echo
SDMA_BITS_RTL=$STUB python3 "$BITS" --control 2>&1 | sed 's/^/  /'
SDMA_BITS_RTL=$STUB python3 "$BITS" --control >/dev/null 2>&1 || { echo "  *** a perturbation was MISSED"; bad=$((bad+1)); }

echo
echo "=== 2. NEGATIVE — each anchor deleted in turn must be NAMED"
ANCHORS=$(/usr/bin/grep -o '// SDMA_BITS: [A-Z0-9_]*' "$STUB" | sed 's/.*: //')
n=0
for a in $ANCHORS; do
  n=$((n+1))
  /usr/bin/grep -v "// SDMA_BITS: $a\( \|$\)" "$STUB" > "$TMP/cut.sv"
  out=$(SDMA_BITS_RTL=$TMP/cut.sv python3 "$BITS" 2>&1 | tail -1)
  case "$out" in
    *"has no $a"*|*"$a has no"*)
      printf '  %-16s REFUSED — %s\n' "$a" "$out" ;;
    *)
      printf '  %-16s *** NOT NAMED — %s\n' "$a" "$out"; bad=$((bad+1)) ;;
  esac
done
echo "  ($n anchors)"

echo
echo "=== 3. THE TREE — rtl/layer_chan.sv as it stands"
python3 "$BITS" 2>&1 | tail -1
python3 "$BITS" >/dev/null 2>&1 && { echo "  *** the tree is GREEN — S2 has landed, retire this note"; bad=$((bad+1)); }

rm -rf "$TMP"
echo
if [ "$bad" -eq 0 ]; then
  echo "RTL_CONTRACT_PROBE: PASS ($n anchors each proved load-bearing; the stub is GREEN with every perturbation CAUGHT; the tree is RED)"
else
  echo "RTL_CONTRACT_PROBE: FAIL ($bad problem(s))"
  exit 1
fi
