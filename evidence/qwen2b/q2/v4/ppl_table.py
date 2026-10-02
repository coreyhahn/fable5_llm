"""Table A's arithmetic, from the committed jsons (Track Q task 8b).

Prints each V4 row's PPL, the fraction of the (V2 - bf16) gap it recovers
and its delta against V3 — i.e. every percentage quoted in GPTQ.md sections
0, 4 and 6, derived from the files rather than typed.  Anchors are quoted
from ../v3/V3.md Table A.

    python3 evidence/qwen2b/q2/v4/ppl_table.py       # from the repo root
"""
import json
import os
import sys

D = "evidence/qwen2b/q2"
ANCH = {"bf16": 12.346298, "V2": 13.744231, "V3 (published)": 13.391781}
rows = []
for tag, path in (("V3 recal", f"{D}/v4/ppl_v3_recal.json"),
                  ("V4h", f"{D}/v4/ppl_v4h.json"),
                  ("V4 gptq", f"{D}/v4/ppl_v4gptq.json"),
                  ("V4 gptq rerun", f"{D}/v4/ppl_v4gptq_rerun.json")):
    if not os.path.exists(path):
        print(f"MISSING {path}")
        continue
    j = json.load(open(path))
    rows.append((tag, j))
    print(f"{tag:16s} PPL {j['ppl']:.6f}  nll_sum {j['nll_sum']:.6f}  "
          f"pos {j['n_positions']}  b/w {j['avg_bits_per_weight']:.9f}  "
          f"inject {j['inject']}  host {j['host']} thr {j['threads']}  "
          f"build {j['seconds_build']:.0f}s eval {j['seconds_eval']:.0f}s")
gap = ANCH["V2"] - ANCH["bf16"]
print(f"\ngap (V2-bf16) = {gap:.6f}")
for tag, j in rows:
    p = j["ppl"]
    print(f"{tag:16s} {p:.6f}  vs bf16 +{p - ANCH['bf16']:.6f}  "
          f"recovers {(ANCH['V2'] - p) / gap * 100:.3f}% of the gap  "
          f"| vs V3(pub) {p - ANCH['V3 (published)']:+.6f} "
          f"= {(ANCH['V3 (published)'] - p) / gap * 100:+.3f} pp of the gap")
