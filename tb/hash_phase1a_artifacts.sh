#!/bin/bash
# sha256 manifests for the Phase-1A regenerated script families.
# Paths in the manifest are PROJECT-RELATIVE so `sha256sum -c` works from
# the repo root.  chain_* / token24_* / model_v2_* are gitignored (size),
# so these manifests ARE the committed provenance for them.
set -eu
cd "$(dirname "$0")/.."
EV=evidence/stage5

for fam in chain token24 model_v2; do
  out="$EV/phase1a_${fam}_artifacts.sha256"
  : > "$out"
  for s in 1 2 3 4; do
    p="tb/scripts/${fam}_s${s}"
    for f in "$p.txt" "$p.weights.json" "$p.emb.bin"; do
      [ -f "$f" ] && sha256sum "$f" >> "$out"
    done
    ls "${p}_w"*.bin 2>/dev/null | sort -V | xargs -r sha256sum >> "$out"
  done
  echo "$out: $(wc -l < "$out") files"
done
