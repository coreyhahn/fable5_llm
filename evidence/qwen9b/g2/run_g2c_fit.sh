#!/usr/bin/env bash
# G2c Step 3 — the per-channel weight-pack fit, wrapped for provenance.
#
#   bash evidence/qwen9b/g2/run_g2c_fit.sh <run-tag>
#
# `g2c_pack_fit.py` is pure arithmetic over `sw/hwmap.plan_weights` — no
# checkpoint, no torch, no threads, no quantization — so it is the one numeric
# step in this gate that does not have to run on snoke.  It runs there anyway,
# because "numeric on snoke" is a campaign rule and the cost is a second.
#
# The tool FORKS one subprocess per geometry: `ref/model_select.py` freezes
# FABLE5_MODEL at import, so one process is one geometry, always (plan,
# standing hazards).  It refuses to print a 9B number until the derived
# manifest has reproduced the committed 0.8B and 2B manifests field for field.
set -u
cd "$(dirname "$0")/../../.."
TAG=${1:?usage: run_g2c_fit.sh <run-tag>}
PY=${FITPY:-$([ -x /home/cah/.venv/bin/python ] \
  && echo /home/cah/.venv/bin/python || command -v python3)}
exec bash evidence/qwen9b/run.sh "g2/g2c_pack_fit_${TAG}.log" \
  "$PY" -u evidence/qwen9b/g2/g2c_pack_fit.py \
  --json-out "$PWD/evidence/qwen9b/g2/g2c_pack_fit_${TAG}.json"
