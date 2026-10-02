#!/usr/bin/env bash
# r3_9a_cov_gen.sh — Task R3-9a Step 4, part 1: the SYNTHETIC broadcast
# coverage artifacts of ONE seed, and their goldens.  New file (a driver: the
# work is evidence/qwen9b/sr/sr13a_cov.py's broadcast kinds and the campaign's
# own golden generator tb/scripts/gen_seq_chip_vectors.py).
#
#   bash evidence/qwen9b/sr/r3_9a_cov_gen.sh <s>        (s = 1..4; ON SNOKE, sr_run.sh)
#
# 1. FIRST: R3-7's prediction (82d2677) must be an ancestor of HEAD (no
#    broadcast is built or run before the prediction is committed);
# 2. per kind (bcast bcast_overlap bcast_bp bcast_ragged bcast_late), seed
#    s*1000 + 310 + k (s1 = sr13a_cov.py's defaults 1311..1315): the stream,
#    VALID at {R1,R2,R3} and REFUSED at {R1,R2}, {R1}, {} (sr13a_cov.py
#    --caps R1,R2,R3); the golden and the per-channel weight regions by
#    gen_seq_chip_vectors.py --caps R1,R2,R3 (ref/seq_model.py replays it,
#    every one of the 65,536 scratch words is a MEM line);
# 3. the late-reader MUTANT stream of the seed's bcast_late (sr13a_cov.py
#    bcast_late_mut): refused by the validator and the model, paired with
#    the correct stream's golden.
# Fail-closed: set -euo pipefail, nothing filtered.
set -euo pipefail
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
cd "$ROOT"
S=${1:?usage: r3_9a_cov_gen.sh <seed index 1..4>}
PY=/home/cah/.venv/bin/python
export FABLE5_MODEL=9b FABLE5_RS_F=7
echo "=== R3-7's prediction 82d2677 an ancestor of HEAD $(git rev-parse --short HEAD)?"
if git merge-base --is-ancestor 82d2677 HEAD; then echo "    git merge-base --is-ancestor 82d2677 HEAD -> 0 (yes)"
else echo "    NOT AN ANCESTOR — no broadcast may run"; exit 9; fi
W9=tb/scripts/w9
k=0
for kind in bcast bcast_overlap bcast_bp bcast_ragged bcast_late; do
  k=$((k + 1))
  seed=$((S * 1000 + 310 + k))
  st=$W9/r3_9a_${kind}_s$S
  echo "######## $kind seed $seed -> $st"
  "$PY" evidence/qwen9b/sr/sr13a_cov.py "$kind" "$st" --caps R1,R2,R3 --seed "$seed"
  "$PY" tb/scripts/gen_seq_chip_vectors.py "$st.e4" --base "$st" --caps R1,R2,R3
  sha256sum "$st.e4.chip" "$st".wimg?.bin
  echo "    MEM lines in the golden: $(grep -c '^MEM ' "$st.e4.chip")"
done
st=$W9/r3_9a_bcast_late_s$S
echo "######## bcast_late_mut -> ${st}_mut (from $st)"
"$PY" evidence/qwen9b/sr/sr13a_cov.py bcast_late_mut "${st}_mut" --caps R1,R2,R3 --from "$st"
echo "R3_9A_COV_GEN s$S: ALL PASS"
