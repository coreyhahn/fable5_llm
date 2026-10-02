#!/usr/bin/env bash
# ref/scripts/sensitivity_scan.sh — per-tensor-class weight-sensitivity scan
# (Track Q task 7).  ONE class is quantized per run, every other class stays at
# the checkpoint's bf16-upcast float, so the PPL delta vs the bf16 anchor
# (evidence/qwen2b/q1/ppl_2b_bf16.json) is attributable to that class alone.
#
#   g64 is the wire format under test because V2 (all:w4g64) is the leading W4
#   candidate — see evidence/qwen2b/q2/v1_v2/DECOMP.md.
#   `emb` is not a W4 class: the residual-seeding table is int16, and the
#   production convention (V1/V2, task 5) is --res-scale 8 => Q4.11.  Bare
#   emb16 at res_scale 1 would be Q7.8, i.e. a DIFFERENT format, so the
#   res_scale is part of the point's definition, not a tuning knob.
#
# SERIALIZED on purpose (one point at a time).  The other hobby servers have no
# torch, and two 2B builds on one host would contend for RAM (peak ~25 GiB) and
# for the same 32 cores that make the eval fast; a contended run is also what
# the two unreproduced impossible-guard trips (DECOMP.md §3.1) happened under.
#
# Usage:
#   ref/scripts/sensitivity_scan.sh                 # all 8 points, skip done
#   ref/scripts/sensitivity_scan.sh dn_in lm_head   # just these points
#   SUFFIX=_rerun ref/scripts/sensitivity_scan.sh dn_in    # confirmation re-run
#   FORCE=1 ...                                     # redo even if json exists
#   EXTRA_ARGS="--max-tokens 1024" ...              # plumbing smoke (NOT a
#                                                   # scan point: truncates the
#                                                   # corpus, so the PPL is not
#                                                   # comparable to the anchor)
set -uo pipefail                    # NOT -e: one bad point must not kill a
                                    # multi-hour queue (failures are collected
                                    # and re-raised as the exit status)

cd "$(dirname "$0")/../.."          # repo root
OUT=${OUT:-evidence/qwen2b/q2/sensitivity}
SUFFIX=${SUFFIX:-}
CORPUS=${CORPUS:-ref/ppl_corpus_eval.txt}
GROUP=${GROUP:-w4g64}
RES_SCALE=${RES_SCALE:-8}           # emb16 only; the W4 images are exactly
                                    # invariant to a power-of-two rescale
mkdir -p "$OUT"

# torch-capable interpreter, same selection rule as ref/scripts/regen_gate.sh
MODELPY=${MODELPY:-$([ -x /home/cah/.venv/bin/python ] \
  && echo /home/cah/.venv/bin/python || command -v python3)}

read -ra EXTRA <<<"${EXTRA_ARGS:-}"

CLASSES=("$@")
[ ${#CLASSES[@]} -eq 0 ] && \
  CLASSES=(qkv o_proj gate_up down dn_in dn_out lm_head emb)

echo "sensitivity_scan: $(date -Is)  host=$(hostname)"
echo "  MODELPY = $MODELPY"
echo "  python  = $("$MODELPY" -c 'import sys,torch;print(sys.version.split()[0], "torch", torch.__version__)' 2>/dev/null || echo '(torch probe failed)')"
echo "  tree    = $(git rev-parse HEAD 2>/dev/null || echo '(not a git tree)')$(git diff --quiet 2>/dev/null || echo ' +dirty')"
echo "  out     = $OUT   suffix='${SUFFIX}'   group=$GROUP"
echo "  points  = ${CLASSES[*]}"

fails=()
for cls in "${CLASSES[@]}"; do
    q=$GROUP
    extra=()
    if [ "$cls" = emb ]; then
        q=emb16
        extra=(--res-scale "$RES_SCALE")
    fi
    json="$OUT/scan_${cls}${SUFFIX}.json"
    log="$OUT/scan_${cls}${SUFFIX}.log"
    if [ -s "$json" ] && [ -z "${FORCE:-}" ]; then
        echo "== skip $cls (have $json; FORCE=1 to redo)"
        continue
    fi
    echo "== $cls:$q ${extra[*]}  -> $json   ($(date -Is))"
    FABLE5_MODEL=2b /usr/bin/time -v "$MODELPY" ref/perplexity_eval.py \
        --corpus "$CORPUS" --inject "$cls:$q" "${extra[@]}" "${EXTRA[@]}" \
        --json-out "$json" >"$log" 2>&1
    rc=$?
    if [ $rc -ne 0 ]; then
        echo "   FAILED rc=$rc — see $log"
        tail -5 "$log" | sed 's/^/   | /'
        fails+=("$cls")
        continue
    fi
    echo "   $(grep -h '^PPL ' "$log")  $(grep -h 'Elapsed (wall clock)' "$log")"
done

if [ ${#fails[@]} -ne 0 ]; then
    echo "SENSITIVITY_SCAN_FAIL: ${fails[*]}"
    exit 1
fi
echo "SENSITIVITY_SCAN_DONE $(date -Is)"
