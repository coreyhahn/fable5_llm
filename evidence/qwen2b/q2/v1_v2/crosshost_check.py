#!/usr/bin/env python3
"""Cross-host check: the 2B bf16 anchor, V1 and V2, darthplagueis vs snoke.

Why this exists (Track Q task 10).  `../v3/V3.md` section 6 documents transient
wrong int64 reductions on darthplagueis.  V3 was closed by re-scoring on snoke
(`../v3/ppl_v3_snoke.json`), and every point from task 8b onward ran on snoke
only -- but the bf16 ANCHOR and the W4 baselines V1/V2, which every Delta in
the study is measured against, had only same-host agreement behind them.
`run_snoke_recheck.sh` re-scored all three on snoke; this compares them.

The comparison convention is V3's, not the same-host rerun convention: the
float PPL path is NOT bit-reproducible across torch builds / thread counts
(~1e-8 relative on nll_sum -- `../v3/V3.md` section 4, `../v4/GPTQ.md` section
2.1), so what is asserted is

  (a) the two runs scored the SAME measurement -- corpus, checkpoint, window,
      batch, positions, injection plan, bit rate and per-class accounting all
      identical, and
  (b) the cross-host `nll_sum` delta is inside the band that phenomenon
      produces: < 1e-7 relative, i.e. ~10x looser than the 1.05e-8 V3 measured
      and ~4x looser than the 4.19e-07 the calibration vectors showed.

`ppl` agreement to six published decimals is REPORTED per row, not asserted,
and the reason is a real result of this run rather than a loosened goalpost:
**V1 straddles a rounding boundary.** Its two values are 14.176885073
(darthplagueis) and 14.176885557 (snoke) -- a difference of 4.8e-07 absolute,
3.4e-08 relative, squarely inside the band -- which prints as 14.176885 vs
14.176886. The sixth decimal flips because the number sits at ...8855, not
because the two hosts disagree about anything. bf16 and V2 print identically.
Asserting on the printed decimal would make the verdict depend on where a
value happens to fall relative to a rounding boundary; asserting on the
relative delta measures the thing the fault would corrupt.

    python3 evidence/qwen2b/q2/v1_v2/crosshost_check.py
Exit code 0 iff every pair passes (a) and (b).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
Q1 = os.path.join(HERE, "..", "..", "q1")

# differ legitimately between two hosts / two torch builds
VOLATILE = {"seconds_build", "seconds_eval", "host", "threads", "torch",
            "nll_sum", "nll_per_pos", "ppl"}

# the cross-torch-build float32 band: V3 measured 1.05e-8 on nll_sum across
# two hosts (`../v3/V3.md` section 4) and the calibration vectors 4.19e-07
# (section 6).  1e-7 is ~10x V3's and is the pass threshold here.
BAND = 1e-7

PAIRS = [
    ("bf16 anchor", os.path.join(Q1, "ppl_2b_bf16.json"),
                    os.path.join(Q1, "ppl_2b_bf16_snoke.json")),
    ("V1 w4g128",   os.path.join(HERE, "ppl_v1.json"),
                    os.path.join(HERE, "ppl_v1_snoke.json")),
    ("V2 w4g64",    os.path.join(HERE, "ppl_v2.json"),
                    os.path.join(HERE, "ppl_v2_snoke.json")),
]


def main():
    bad = 0
    print("=== cross-host check: darthplagueis (original) vs snoke (re-score) ===")
    for name, pa, pb in PAIRS:
        if not (os.path.exists(pa) and os.path.exists(pb)):
            print(f"  {name:12s} MISSING json")
            bad += 1
            continue
        with open(pa) as f:
            a = json.load(f)
        with open(pb) as f:
            b = json.load(f)

        # (a) same measurement?  A key the ORIGINAL json predates counts as
        # agreeing iff the new run left it empty -- `perplexity_eval` grew
        # `host`/`threads` and five `calib_*` fields after V1/V2 were scored,
        # and schema growth is not a measurement difference.  A calibrated
        # value in a run whose twin has none would still be flagged.
        def agrees(k):
            if a.get(k) == b.get(k):
                return True
            if k not in a and b.get(k) in (None, {}, [], 0):
                return True
            return False

        diff = sorted(k for k in set(a) | set(b)
                      if k not in VOLATILE and not agrees(k))
        # (b) inside the cross-build band
        agree6 = f"{a['ppl']:.6f}" == f"{b['ppl']:.6f}"
        rel = abs(a["nll_sum"] - b["nll_sum"]) / abs(a["nll_sum"])
        ppl_abs = abs(a["ppl"] - b["ppl"])
        ppl_rel = ppl_abs / abs(a["ppl"])
        ok = rel < BAND and not diff
        print(f"  {name:12s} {a['ppl']:.9f} vs {b['ppl']:.9f}  "
              f"|dPPL| {ppl_abs:.3e} ({ppl_rel:.2e} rel)  "
              f"prints the same to 6 dp: {agree6}"
              f"{'' if agree6 else '  <- rounding boundary, see the docstring'}")
        print(f"  {'':12s} nll_sum {a['nll_sum']:.6f} vs {b['nll_sum']:.6f}  "
              f"rel {rel:.2e}  (band {BAND:.0e}) -> "
              f"{'INSIDE' if rel < BAND else 'OUTSIDE'}   "
              f"bit-identical: {a['nll_sum'] == b['nll_sum']}")
        print(f"  {'':12s} setup fields differing: {diff if diff else 'NONE'}"
              f"   [{a.get('torch')} threads={a.get('threads')} host="
              f"{a.get('host') or 'darthplagueis (pre-stamping)'}"
              f"  ->  {b.get('torch')} threads={b.get('threads')} "
              f"host={b.get('host')}]")
        if not ok:
            bad += 1
    print("CROSSHOST_PASS" if not bad else f"CROSSHOST_FAIL ({bad})")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
