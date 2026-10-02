#!/usr/bin/env bash
# rd_seed_diff.sh — the seed-determinism claim, done MECHANICALLY.
#
#   * runs A and B at seed 4242 must produce the SAME generated ids;
#   * seed 4243 must produce DIFFERENT ones;
#   * the JSON reports' `sampling` blocks (draw counts, knobs) must agree
#     between A and B.
# The chat_seq JSON report does not carry the token ids, so the ids come
# from the `ids [...]` line of each session's own tee'd log.
set -u
R=/home/cah/r2d2/code/fpga/fable5_llm/evidence/qwen2b/rd
ids() { grep -oP '^\s+ids \[\K[^]]*' "$R/$1" | tail -1; }

A=$(ids hw_09_sampled_seed4242_a.log)
B=$(ids hw_10_sampled_seed4242_b.log)
C=$(ids hw_11_sampled_seed4243.log)
D=$(ids hw_12_sampled_seed4244.log)
E=$(ids hw_13_sampled_seed4245.log)

echo "4242 A: [$A]"
echo "4242 B: [$B]"
echo "4243  : [$C]"
echo "4244  : [$D]"
echo "4245  : [$E]"
echo
ok=1
[ "$A" = "$B" ] && echo "DETERMINISM  seed 4242 x2: IDENTICAL ids" \
                || { echo "DETERMINISM  seed 4242 x2: *** DIFFER ***"; ok=0; }
[ "$A" != "$C" ] && echo "SENSITIVITY  4242 vs 4243: DIFFER" \
                 || { echo "SENSITIVITY  4242 vs 4243: *** IDENTICAL ***"; ok=0; }
for s in "$C" "$D" "$E"; do
  [ "$A" != "$s" ] || { echo "SENSITIVITY  a seed collided with 4242"; ok=0; }
done
echo
echo "--- JSON sampling blocks, 4242 A vs B ---"
/home/cah/r2d2/code/fpga/fable5_llm/sw/.venv/bin/python - "$R" <<'PY'
import json, sys
r = sys.argv[1]
a = json.load(open(f"{r}/chat_sampled_seed4242_a.json"))
b = json.load(open(f"{r}/chat_sampled_seed4242_b.json"))
for k in ("sampling", "template", "context", "launches"):
    same = a.get(k) == b.get(k)
    print(f"  {k:<10} equal={same}   {json.dumps(a.get(k))[:150]}")
PY
[ $ok -eq 1 ] && echo "SEED_GATE_PASS" || echo "SEED_GATE_FAIL"
