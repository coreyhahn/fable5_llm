#!/usr/bin/env python3
"""Compare each task-9 PPL json against its independent re-run.

Why this exists: the run script was accidentally launched a second time while
the first batch was still going, truncating five logs in flight (V4_V5.md
section 9.6).  The duplicates were killed and all five points were re-run
from scratch for clean logs.  This checks that the re-run reproduced the
original MEASUREMENT exactly — every field except the wall-clock/host
metadata, which cannot and should not match.

    python3 evidence/qwen2b/q2/v4_v5/rerun_identical.py \
            evidence/qwen2b/q2/v4_v5/run1
        `run1/` holds the preserved first-run jsons (committed so this check
        is reproducible); the ones next to this script are run 2 and are the
        published measurements.
Exit code 0 iff every measured field of every pair is identical.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# fields that legitimately differ between two runs of the same measurement
VOLATILE = {"seconds_build", "seconds_eval", "host", "threads", "torch",
            "tokenizer_snapshot", "checkpoint"}
NAMES = ("ppl_v5", "ppl_v5_rerun", "ppl_v4mix_top1", "ppl_v4mix_top2",
         "ppl_v4mix_top3")


def main(run1):
    bad = 0
    for n in NAMES:
        p1, p2 = os.path.join(run1, n + ".json"), os.path.join(HERE, n + ".json")
        if not (os.path.exists(p1) and os.path.exists(p2)):
            print(f"  {n:18s} MISSING ({p1 if not os.path.exists(p1) else p2})")
            bad += 1
            continue
        with open(p1) as f:
            a = json.load(f)
        with open(p2) as f:
            b = json.load(f)
        diff = sorted(k for k in set(a) | set(b)
                      if k not in VOLATILE and a.get(k) != b.get(k))
        same_nll = a["nll_sum"] == b["nll_sum"]
        print(f"  {n:18s} ppl {a['ppl']:.6f} vs {b['ppl']:.6f}  "
              f"nll_sum bit-identical: {same_nll}  "
              f"differing measured fields: {diff if diff else 'NONE'}  "
              f"(run1 {a['seconds_build']:.0f}+{a['seconds_eval']:.0f}s, "
              f"run2 {b['seconds_build']:.0f}+{b['seconds_eval']:.0f}s)")
        if diff or not same_nll:
            bad += 1
    print("RERUN_IDENTICAL_PASS" if not bad else f"RERUN_IDENTICAL_FAIL ({bad})")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
