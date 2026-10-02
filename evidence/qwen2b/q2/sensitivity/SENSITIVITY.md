# Per-tensor-class W4 sensitivity scan at 2B (Track Q, task 7)

**Headline.** Class **size** predicts W4 perplexity damage at 2B —
Spearman rho **+0.857** against parameter count, **over the 7 W4 classes
(`emb` excluded: it is the int16 residual table, not a W4 matvec class)**,
exact permutation p = 0.0238. The per-matrix W4 reconstruction error that Q6
flagged predicts it **not at all** (rho **−0.179**, p = 0.7131). The V4 map
therefore promotes `gate_up`, then `lm_head`, then `dn_in` — not the
outlier-heavy small projections the weight-error metric names.

Every number in this file is derived by **`ref/scripts/rank_sensitivity.py`**
from the committed jsons and the committed audit table; its verbatim output
is `rank_sensitivity.txt` in this directory.

| rank | class | quant | mats | params | PPL | ΔPPL vs bf16 | Δ% | ΔPPL / Mparam |
|---|---|---|---|---|---|---|---|---|
| 1 | `gate_up` | w4g64 | 48 | 603.98 M | 12.815768 | **+0.469470** | +3.80 % | +0.00078 |
| 2 | `lm_head` | w4g64 | 1 | 508.56 M | 12.619157 | **+0.272859** | +2.21 % | +0.00054 |
| 3 | `dn_in` | w4g64 | 72 | 303.17 M | 12.531978 | **+0.185680** | +1.50 % | +0.00061 |
| 4 | `down` | w4g64 | 24 | 301.99 M | 12.485822 | +0.139524 | +1.13 % | +0.00046 |
| 5 | `o_proj` | w4g64 | 6 | 25.17 M | 12.474616 | +0.128317 | +1.04 % | +0.00510 |
| 6 | `qkv` | w4g64 | 18 | 62.91 M | 12.462538 | +0.116240 | +0.94 % | +0.00185 |
| 7 | `dn_out` | w4g64 | 18 | 75.50 M | 12.356938 | +0.010640 | +0.09 % | +0.00014 |
| 8 | `emb` | emb16 S=8 | 1 | 508.56 M | 12.346475 | +0.000177 | +0.00 % | +0.0000003 |

bf16 anchor **12.346298** (`evidence/qwen2b/q1/ppl_2b_bf16.json`). Median
ΔPPL 0.133921. Params are the harness's own `classes.<c>.n_weights`, i.e.
summed tensor shapes, not a hand count.

## 1. What was measured, and how

`ref/scripts/sensitivity_scan.sh` runs `ref/perplexity_eval.py` once per
class: **that class quantized, every other class left at the checkpoint's
bf16-upcast float**, so the delta is attributable to the one class. Every
point shares the anchor's corpus, checkpoint, window and batch — asserted,
not assumed: `ref/scripts/rank_sensitivity.py` re-checks `corpus_sha256`,
`checkpoint_header_sha256`, `n_positions`, `window`, `batch`, `model_tag`,
`n_tokens`, that `inject_resolved` names exactly one class, and that
`res_scale == 8` on exactly the `emb` point — and raises before printing
anything if any of that fails.

| | |
|---|---|
| harness | `ref/perplexity_eval.py`, `FABLE5_MODEL=2b` |
| corpus | `ref/ppl_corpus_eval.txt`, sha256 `6bf4f867…c27876`, 24576 tokens |
| checkpoint | Qwen3.5-2B shard, header sha256 `ccba2c1f…bfee9d` |
| measurement | window 512, batch 4, **24528 scored positions** (identical to the anchor and to V1/V2) |
| wire format | `w4g64` — matches **V2**, the leading W4 candidate (`../v1_v2/DECOMP.md`) |
| `emb` point | `emb:emb16 --res-scale 8` (Q4.11), the V1/V2 production convention. Bare `emb16` at S=1 would be Q7.8, a *different* format |
| host | darthplagueis, torch 2.6.0+cu124, python 3.13.9, 16 threads, peak RSS 15.0-15.8 GiB/run |
| cost | 8 points in **26 min** wall, serialized (2:48-3:53 each) |

**Serialized, not parallel.** The plan sketched fanning the 8 points across
the hobby servers; those hosts have no torch, so every point ran one at a
time on darthplagueis. This is also the safer choice given §3.

**`dn_conv` is not a scan point.** K=4 has no W4 wire format; its only
format (`cw13`) was already priced in task 5 and is nil.

## 2. Cross-check: the scan is complete, and damage is mildly super-additive

Sum of the 8 one-at-a-time deltas = **1.322907**. The joint V2 delta
(`all:w4g64,dn_conv:cw13,emb:emb16`, `../v1_v2/ppl_v2.json`) =
13.744231 − 12.346298 = **1.397933**.

The scan accounts for **94.6 %** of the joint damage; the missing
**+0.075026** is super-additivity between classes (quantizing everything at
once hurts slightly more than the sum of the parts). That residual is the
error bar on any top-k selection made from this table — it is small enough
that the top-3 ordering is not in question (the gaps between ranks 1-4 are
0.20, 0.09 and 0.05 PPL), and it means a V4 estimate built by *subtracting*
promoted classes from V2 is conservative.

It also confirms nothing was left unmeasured: the 8 points plus the known-nil
`dn_conv` cover every weight the accelerator quantizes.

## 3. Host-fault ruling — confirmation re-runs

The re-run criteria — most anomalous point, plus any point whose ΔPPL is
negative or exceeds 10× the median — come from the **controller's task-7
dispatch**. `../v1_v2/DECOMP.md` §3.1 and track-r task-5 §8.1 are the
*evidence they respond to*: two unreproduced impossible-guard trips on this
host under sustained load. Cite them for the fault, not for the rule.

* **negative ΔPPL: none.** All 8 deltas are ≥ 0.
* **> 10× median (> 1.339): none.** The largest is 0.469470.
* **largest ΔPPL: `gate_up`** — re-run, required.
* **`dn_out`** — re-run, *not* required by the ruling but done anyway
  (2.9 min): it is the low-end outlier at 9 % of the next-smallest delta,
  and the "do not promote `dn_out`" conclusion rests on it.

| point | first run | re-run | agreement |
|---|---|---|---|
| `gate_up` | 12.815768 | 12.815768 | **bit-identical** (`nll_sum` 62562.987946 both) |
| `dn_out` | 12.356938 | 12.356938 | **bit-identical** (`nll_sum` 61668.731806 both) |

Agreement is stronger than the ruling asks for: not merely equal to printed
precision, but equal in the full-precision `nll_sum` recorded in the jsons.
No host fault was observed during this task — all 10 runs (8 + 2) exited 0.

## 4. The V4 candidate maps

V4 = V2 with the top-k classes promoted to W8
(`all:w4g64,<class>:w8g128,…,emb:emb16` — the spelling Task 9 will score).

`emb` is **not** a promotion candidate: it is the int16 residual-seeding
table, not a W4 matvec class, and its ΔPPL is +0.000177 — nil, corroborating
task 5's independently measured −0.000299 for the whole `emb16`+`cw13`
increment. Promotion candidates are the 7 W4 classes only.

| map | W8 classes | ΔPPL recoverable | est. PPL (V2 − ΣΔ) | W4-side bytes/token |
|---|---|---|---|---|
| V2 (baseline) | — | — | 13.744231 (measured) | **999,428,096** |
| **V4 top-1** | `gate_up` | 0.469470 | ≈ 13.274761 | **678,563,840** + W8 rows |
| **V4 top-2** | + `lm_head` | 0.742328 | ≈ 13.001903 | **408,391,680** + W8 rows |
| **V4 top-3** | + `dn_in` | 0.928008 | ≈ 12.816223 | **247,332,864** + W8 rows |

**The est. PPL column is arithmetic, not a measurement** — it assumes W8
removes the promoted class's damage entirely and that damage is additive
(§2 says it is 94.6 % additive). Task 9 measures the real thing; these three
numbers exist so gate D can see the shape of the curve before that lands.

### Bytes/token arithmetic (the W4 side is exact; W8 is Task 9)

Convention: bytes/token = the DDR weight traffic of the **7 W4 classes**,
each row at `w4a8_ref.row_stride(K, g)` bytes (weight beats + scale beats,
64 B each, tail padded — `perplexity_eval.packed_bits`). The `emb` table is
excluded (decode reads one row per token, not the table) as are `dn_conv`
and the float norms. **This convention reproduces the feasibility study's
self-validated figure exactly**: V1 (g128) = 996,282,368 B/token, to the
byte. V2 (g64) = 999,428,096, i.e. +0.316 % — the feasibility's "+0.32 % at
2B".

| class | g64 packed bytes | share of V2 traffic |
|---|---|---|
| `gate_up` | 320,864,256 | 32.10 % |
| `lm_head` | 270,172,160 | 27.03 % |
| `dn_in` | 161,058,816 | 16.12 % |
| `down` | 160,432,128 | 16.05 % |
| `dn_out` | 40,108,032 | 4.01 % |
| `qkv` | 33,423,360 | 3.34 % |
| `o_proj` | 13,369,344 | 1.34 % |
| total | 999,428,096 | 100 % |

    V4 top-1: 999,428,096 − 320,864,256 = 678,563,840 B + W8(gate_up)
    V4 top-2: 999,428,096 − 591,036,416 = 408,391,680 B + W8(gate_up, lm_head)
    V4 top-3: 999,428,096 − 752,095,232 = 247,332,864 B + W8(gate_up, lm_head, dn_in)

**W8 row bytes are deliberately not computed here.** `packed_bits` raises on
`w8g128` by design until Task 9 defines the W8 row format; the ideal format
rate (8 + 16/128 = 8.125 b/w) is a *floor*, and the W4 case shows beat
padding puts the real rate 0-9 % above ideal. Applying that same floor to
**every** class gives the right yardstick:

| map | floor bytes/token | x V2 | % of full-W8 traffic | ΔPPL recovered |
|---|---|---|---|---|
| V2 (all W4 g64) | 999,428,096 | 1.000x | 52.3 % | — |
| V4 top-1 | ≥ 1,291,980,800 | ≥ 1.293x | 67.6 % | 33.6 % |
| V4 top-2 | ≥ 1,538,314,240 | ≥ 1.539x | 80.5 % | 53.1 % |
| V4 top-3 | ≥ 1,685,161,984 | ≥ 1.686x | 88.2 % | 66.4 % |
| V5 (W8 on all seven) | ≥ 1,910,671,360 | ≥ 1.912x | 100 % | (Task 9) |

**That is the finding gate D needs.** The ranking put the three *largest*
classes on top, so **V4 top-3 spends 88 % of full-W8 bandwidth to recover
66 % of the W4 damage** — the mixed-precision middle is nearly as expensive
as going W8 everywhere. There is no cheap mixed-precision win at 2B, because
damage tracks size and so does bandwidth.

*Denominator note.* "66.4 %" is against V2's **joint** delta (1.397933), the
damage a real V4 build would actually be removing. Against the **sum of the
one-at-a-time deltas** (1.322907) the same three classes are 70.1 %. The
joint denominator is the conservative and operationally correct one; both are
printed by `rank_sensitivity.py` so no reader has to guess which is meant.

## 5. Q6 comparison — does the weight-error metric predict PPL rank?

**Stated explicitly, as required.** Q6 (task 6, `../audit/over15_probe.txt`
and `ref/audit_ranges_2b_report.md` §6.4) found 15 of 187 matrices above the
project's 15 % W4 reconstruction-error bound, **12 of them the 16x2048
DeltaNet gate projections `dn.in_a` / `dn.in_b`** — a 2B regression (0 of
187 at 0.8B). The question this scan was built to answer: does `dn_in`'s PPL
delta rank where that metric predicts?

**No — and the metric has essentially no predictive power over the ranking.**

All correlations are **over the 7 W4 classes**; `emb` is excluded because it
is the int16 residual table, not a W4 matvec class, *and* because it would
double-count the tied matrix (`emb` and `lm_head` are two images of the same
508,559,360-weight tensor — byte-identical parameter counts, hence a tie).
Over all 8 with tie-correct midranks the size correlation falls to **+0.479**:
`emb` is joint-largest by size and least damaged of anything measured.

n = 7 is small, so exact permutation p-values are printed rather than implied.
The two-tailed critical value at α = 0.05 is **|rho| = 0.786**:

| predictor (vs ΔPPL rank) | rho | exact p | verdict at α=0.05 |
|---|---|---|---|
| class parameter count | **+0.857** | 0.0238 | **significant** |
| worst per-matrix W4 rel err (audit §2, g128) | **−0.179** | 0.7131 | not significant |
| same err, vs ΔPPL **per parameter** | **+0.714** | 0.0881 | **not significant** — suggestive only |

**The +0.714 row is deliberately not called a result.** The same n = 7 that
makes −0.179 worthless cannot crown +0.714: it sits below the 0.786 critical
value, and one swapped pair would move it substantially. Read it as "the
error metric plausibly tracks per-parameter sensitivity, worth re-testing
with more classes or per-matrix granularity", not as an established fact.

One further caveat on the predictor itself: the audit's rel-err column is
measured at **g128**, while this scan quantizes at **g64**. The per-class
ordering of W4 error is assumed stable between the two group sizes and was
not checked — the g64 scan costs 26 min if a future task wants to close that
(`GROUP=w4g128 SUFFIX=_g128 ref/scripts/sensitivity_scan.sh` gives the other
side).

Read the three rows together:

* `dn_in` ranks **3rd of 7** by ΔPPL. The weight-error metric ranks it 2nd
  (max 16.12 %), so it lands about where predicted — but for the wrong
  reason: it is also **3rd by size**, and size is what the ranking follows.
* The metric's #1, `qkv` (worst single matrix in the model, `L19.attn.v_proj`
  at 17.28 %), ranks **6th of 7** by ΔPPL. `gate_up`, which has no matrix
  anywhere near the bound (10.29-11.69 %, the lowest floor of any class,
  4th of 7 on the metric), ranks **1st**. That inversion is the whole
  result.
* The reason is arithmetic: the 12 over-bound gate matrices are
  `16x2048` = 32768 weights each. `dn.in_a` + `dn.in_b` together are
  1,179,648 weights = **0.389 % of `dn_in`** and **0.063 % of all W4
  weights**. A class cannot move perplexity through 0.4 % of its parameters
  no matter how badly those are quantized.
* The metric may not be useless — it *suggestively* tracks **per-parameter**
  sensitivity (rho +0.714, p = 0.0881, below the 0.786 critical value).
  `o_proj` and `qkv`, the outlier-heavy small projections it names, are 1st
  and 2nd in ΔPPL/Mparam (0.00510 and 0.00185, vs `gate_up`'s 0.00078 and
  `dn_out`'s 0.00014). They just do not carry enough parameters for that to
  matter: `o_proj` + `qkv` are 4.7 % of the byte budget.

**Consequence for the plan.** The 15 %-bound regression stays a *format*
finding — the bound only ever fires inside `w4a8_ref._selftest` on synthetic
Gaussian weights, and the real 2B model exceeds it on 15 matrices with no
assert — and it does **not** promote `dn_in`'s gate projections to a
precision target on this evidence. If a future variant wants to spend bits
where the error metric points, the cheap buy is `o_proj` — 0.128 PPL of
damage sitting on 1.34 % of the byte budget — not `dn_in`.

`dn_out` is the one class that under-performs its size badly (75.5 M
params, 5th largest, but last by ΔPPL at +0.0106 — 9 % of `qkv`'s delta on
20 % more parameters). Confirmed by a bit-identical re-run (§3), so it is a
property of the DeltaNet output projection, not a measurement artifact.

## 6. arXiv 2505.02214 comparison — and a correction to the citation

The plan asks whether the ranking matches "the arXiv 2505.02214 expectation
(`down_proj` / output projections most sensitive)".

**First, the citation does not carry that claim.** 2505.02214 is *An
Empirical Study of Qwen3 Quantization* (Zheng et al., arXiv:2505.02214v1,
4 May 2025) — RTN / GPTQ / AWQ / SmoothQuant / BiLLM, 1-8 bit weights,
WikiText2/C4 perplexity + zero-shot + 5-shot MMLU, per-channel and
per-group-128, tables covering 0.6B-32B. It reports **no per-projection or
per-layer-type sensitivity analysis**; its granularity is method x bit-width
x model size x task.

That negative claim is **first-hand and reproducible**, not a summary:
`arxiv_2505.02214_check.txt` in this directory records the pdf's sha256 and
the term counts over the full pdftotext-extracted text. Every one is **zero**
— `down_proj`, `o_proj`, `gate_proj`, `up_proj`, `q_proj|k_proj|v_proj`,
`lm_head`, "down projection", "output projection", "mixed precision",
"per-layer|layer-wise|layerwise", and "sensitivit*". A paper that never
writes the name of a projection cannot rank projections.

(No parameter range is quoted beyond "tables covering 0.6B-32B" on purpose:
the paper's own §2 sentence says it evaluates "0.6B, 1.8B, 4B, 7B, 14B, and
72B", which matches neither its own tables nor the real Qwen3 lineup. The
discrepancy is noted in the check file and is not load-bearing here.)

The repo's own use of the citation (`docs/QWEN2B_FEASIBILITY.md:54`) is the
size-vs-degradation trend, which the paper does support. The "`down_proj` /
output projections most sensitive" expectation is the general community prior
(the AWQ / outlier-channel line of work, where `down_proj` and `o_proj` take
outlier-heavy activations), not a finding of this paper — **the plan's
parenthetical should be re-attributed.**

**Second, the expectation is not reproduced here.** `down` ranks 4th of 7
and `o_proj` 5th; the top two are `gate_up` and `lm_head`. Two honest
caveats on that comparison:

1. **Different quantity.** The prior is about *activation* outliers making
   `down_proj` / `o_proj` hard to quantize. This scan measures **weight**
   damage only, with float compute (module docstring; the datapath is scored
   separately by `fidelity_check.py` and decomposed in `../v1_v2/DECOMP.md`).
   An activation-outlier effect would show up in the fixed-point ladder, not
   here.
2. **Normalization.** Per parameter, `o_proj` **is** the most sensitive
   class in the model (§5), which is the direction the prior points. The
   prior ranks *matrices*; a bit-budget decision needs *classes*, and the
   two orderings disagree because class sizes span 24x.

So: consistent with the prior on the per-parameter axis, inconsistent on the
axis that decides the V4 map. Where they conflict, this table wins — it is
this model, this quantizer, this corpus.

## 7. Files

| file | what |
|---|---|
| `scan_{qkv,o_proj,gate_up,down,dn_in,dn_out,lm_head,emb}.json` | the 8 scan points (harness json: PPL, nll_sum, per-class accounting, provenance shas) |
| `scan_*.log` | full stdout + `/usr/bin/time -v` per point |
| `scan_{gate_up,dn_out}_rerun.{json,log}` | §3 confirmation re-runs |
| `queue.log`, `queue_rerun.log` | the serialized queue's own log (host, interpreter, tree hash, per-point wall time) |
| `rank_sensitivity.txt` | verbatim output of the derivation script — every number in this doc |
| `arxiv_2505.02214_check.txt` | basis for §6's negative claim (pdf sha256 + zero-hit term counts) |
| `ref/scripts/sensitivity_scan.sh` | the queue |
| `ref/scripts/rank_sensitivity.py` | the derivation: table, rhos + exact permutation p, bytes, cross-check, re-runs |

Reproduce: `ref/scripts/sensitivity_scan.sh` (skips points whose json already
exists; `FORCE=1` to redo, `SUFFIX=_rerun <class>` for a confirmation run),
then `python3 ref/scripts/rank_sensitivity.py`. The derivation script reads
only committed artifacts — the scan jsons, the bf16 anchor, the V1/V2 jsons
and `ref/audit_ranges_2b_report.md` §2 — and hardcodes nothing but the
audit-family-to-class map, so Q9/Q10 can re-derive rather than re-quote.
