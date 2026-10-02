# Qwen3.5-2B quantization study — the gate-D decision table

**Status: THE study deliverable of Track Q.** It assembles what tasks Q1-Q9
measured into one decision surface and recommends an operating point. It
decides nothing: **the operating point is the user's pick at gate D.**

**Almost nothing here is re-measured.** Every number is quoted from a committed
json, log or derivation script under `evidence/qwen2b/`; §8 is the traceability
index. Where a figure is arithmetic on quoted values, the arithmetic is the
committed derivation script's (`evidence/qwen2b/q2/v4_v5/v4_v5_table.py`,
output `v4_v5_table.txt`), not retyped. **The one exception**: this task
re-scored the bf16 anchor, V1 and V2 on snoke to close the host-attribution gap
of §6.4 — three new jsons, no new variants, and no ladder value moved.

**Supersedes** `docs/QWEN2B_FEASIBILITY.md` on every perf and fidelity number.

---

## 0. What was measured, and how to read the names

All 2B perplexity rows share one setup — corpus `ref/ppl_corpus_eval.txt`
sha256 `6bf4f867…`, checkpoint header sha256 `ccba2c1f…`, window 512, batch 4,
**24,528 scored positions** — and `v4_v5_table.py` §provenance *asserts* those
against the anchor for every scored variant row before anything is ranked.

Two scoping notes on what that assert does **not** cover, so the guarantee is
not read wider than it is:

* **`res_scale 8`** is asserted on the variant rows only. The **bf16 anchor
  carries `res_scale 1.0` and an empty injection**, which is correct — a
  power-of-two residual rescale has no meaning without `emb16`, and
  `perplexity_eval.check_res_scale` rejects the combination outright.
* **The non-matvec formats `dn_conv:cw13, emb:emb16` are not asserted at all**
  (the map check filters on the W4 matvec classes). They are carried by every
  variant row by construction, so variant-vs-variant comparisons stay
  single-variable; but because the anchor is **pure bf16**, every Δ in Panel A
  includes the emb16+cw13 increment. That increment is *measured*, not assumed:
  **−0.000299 PPL** (`DECOMP.md` Table A, A1 − A3), i.e. 0.02 % of V2's damage
  and a slight *improvement*. It cannot move any ranking in this document.

`ref/perplexity_eval.py` measures **weight damage only** — production
quantizers dequantized back into the float model. The shipped fixed-point
datapath is scored separately by `ref/fidelity_check.py`, and the two are
decomposed against each other in §3. Read the PPL column as *the weight
format's* damage, not as the board's output quality.

**Scope: the text tower only.** The 2B checkpoint carries three top-level
prefixes and this study touches one. `load_layer()` and the whole `ref/` chain
filter on `model.language_model.` (320 of 632 tensors, **1,881,825,088**
params), so neither the **vision tower** (331,416,576) nor the **MTP head**
(15 tensors, **60,828,160**) reaches the loader or any number in this document
(`evidence/qwen2b/q0/checkpoint_verify.md`). Two consequences worth stating at
gate D: any parameter-budget arithmetic must start from the 1.88 G text figure,
not the 2.27 G file total; and the MTP head — a real, full-width
`full_attention` block, not vestigial metadata — is **shipped-unused**. It is
therefore an untouched *throughput* axis (speculative decode) that is
orthogonal to every quantization choice below, and no row in the table gains or
loses by it.

**Naming** (Q9's convention, kept — two different things were called "V4"):

| name | what it is | bytes vs V2 |
|---|---|---|
| **V1 / V2 / V3** | W4 g128 / W4 g64 / W4 g64 + salience-weighted scale search | 0.997 / 1.000 / 1.000 |
| **V4gptq** | full-Hessian GPTQ-lite W4 g64 (`w4g64gptq`) — task 8b's quantizer | **1.000** |
| **V4mix top-k** | V2's W4 base with the k most sensitive classes promoted to W8 g128 | 1.30 / 1.56 / 1.71 |
| **V4gptq + gate_up W8** | the composed frontier point: GPTQ everywhere, `gate_up` at W8 g128 | 1.302 |
| **V5** | W8 g128 everywhere (`all:w8g128`) | 1.938 |
| ~~V6~~ | the datapath-precision axis — **it never opened**, see §3 | — |

---

## 1. THE DECISION TABLE

Two panels over the same variant key: **A = quality**, **B = cost and
buildability**. The 0.8B production row is the familiar reference point; it is
a *different model*, so its Δ is against its own bf16 anchor and its
fixed-point score is on a different ruler (see the row's footnote).

### Panel A — quality

| variant | PPL | Δ vs bf16 | Δ % | % of the V2 gap LEFT | fixed-point top-1 (S=4, 108 steps) | free-run text verdict |
|---|---|---|---|---|---|---|
| **bf16 anchor (2B)** | **12.346298** | — | — | 0 % | 108/108 (exact-float row) | the exact-float reference reproduces the torch golden's argmax at all 108 steps and its free-run text verbatim on 4/4 prompts |
| V1 — W4 g128 | 14.176885 | +1.830587 | +14.83 % | 130.95 % | 80/108 (g128) | 4/4 readable, 3/4 clean; p1 restates its answer |
| V2 — W4 g64 | 13.744231 | +1.397933 | +11.32 % | 100.00 % | 80/108 | 4/4 readable, 3/4 clean; p1 hard repetition loop |
| V3 — W4 g64 + salience | 13.391781 | +1.045483 | +8.47 % | 74.79 % | **86/108** | 4/4 readable, 3/4 clean (same single p1 artifact) |
| **V4gptq — W4 g64 + GPTQ** | **12.941240** | **+0.594941** | **+4.82 %** | **42.56 %** | 85/108 | readable 4/4; same p1 repetition-loop mode as V2/V3 |
| V4mix top-1 (`+gate_up` W8) | 13.275505 | +0.929207 | +7.53 % | 66.47 % | not measured¹ | not measured¹ |
| V4mix top-2 (`+lm_head`) | 12.975961 | +0.629663 | +5.10 % | 45.04 % | not measured¹ | not measured¹ |
| V4mix top-3 (`+dn_in`) | 12.720237 | +0.373939 | +3.03 % | 26.75 % | not measured¹ | not measured¹ |
| **V4gptq + `gate_up` W8** | **12.736774** | **+0.390476** | **+3.16 %** | **27.93 %** | not measured¹ | not measured¹ |
| **V5 — W8 g128 everywhere** | **12.360678** | **+0.014380** | **+0.12 %** | **1.03 %** | not measured¹ | not measured¹ |
| *0.8B production (W4 g128)* | *22.432251* | *+4.952206 vs its own 17.480045 anchor* | *+28.33 %* | *n/a — other model* | *16/24 at S=8²* | *the shipped chat path* |

¹ **No W8 fixed-point path exists.** Q9 added W8 to the wire law
(`ref/w4a8_ref.py`) and to `perplexity_eval`, not to the `layer_fixed`
FxRunner, so the four W8-bearing rows have a float weight-damage score and no
fixed-point or free-run text score. Closing action: it is only worth building
if gate D picks a W8 row — the same decision that would fund the RTL.

² Different ruler, do not compare column-wise: the 0.8B production probe is
24 teacher-forced steps at S=8, the 2B probes are 108 steps at S=4.

*PPL, ΔPPL and "% of the V2 gap left" are `v4_v5_table.txt`'s columns, computed
from the jsons' full-precision PPL. The "Δ %" column is the only arithmetic
added here: `ΔPPL / 12.346298`, on the two values in its own row. (One
1e-6-level rounding artifact, noted so nobody files it as a discrepancy:
`GPTQ.md` quotes V4gptq's ΔPPL as +0.594942 — the subtraction of two 6-decimal
values — where `v4_v5_table.txt` prints +0.594941 from full precision. This
table uses the latter throughout.)*

**The two readings that decide the table.** (a) **The fixed-point probe cannot
resolve the V3/V4gptq difference** — McNemar exact on the paired 108 steps
gives p=1.000 for V3 vs V4gptq, p=0.263 for V2 vs V3, p=0.302 for V2 vs
V4gptq: *not one* of these top-1 differences is statistically resolvable
(`evidence/qwen2b/q2/v4/fixed_significance.log`). The 80/86/85 column is a
**safety screen** — clip-free, readable, no fixed-point regression — not a
quality ranking. The ranking comes from the 24,528-position PPL column.
(b) **V4mix top-2 (12.975961) is worse than V4gptq (12.941240) while costing
1.557× the bytes.** The V2-based mixed-precision middle is not merely
unattractive, it is dominated by a quantizer that is free.

### Panel B — cost and buildability

| variant | bytes/token | ×V2 | modeled tok/s (2B, nch=4) | vs V2 | DDR fit (1,280 MiB window/chan; nch=1 span — `plan_weights` is nch-independent, §5) | RTL delta | timing closure | risk notes |
|---|---|---|---|---|---|---|---|---|
| V1 — W4 g128 | 996,282,368 | 0.997 | 20.77 - 21.53 | +0.1 % | 950 MiB, **74 % OK** | **NONE** | **accepted under waiver** (re-affirmed) — −0.025 / +0.001, violations all in custom RTL incl. migrated `layer_0` (§1.1); **no new RTL**, R9 validates | worst quality on the board; superseded by V2 for +0.011 b/w |
| V2 — W4 g64 | 999,428,096 | 1.000 | **20.75 - 21.51** | — | 953 MiB, **74 % OK** | **NONE** | **accepted under waiver** (re-affirmed) — −0.025 / +0.001, violations all in custom RTL incl. migrated `layer_0` (§1.1); **no new RTL**, R9 validates | the baseline; g64 costs +0.32 % bytes |
| V3 — W4 g64 + salience | 999,428,096 | 1.000 | 20.75 - 21.51 | — | 953 MiB, **74 % OK** | **NONE** | **accepted under waiver** (re-affirmed) — −0.025 / +0.001, violations all in custom RTL incl. migrated `layer_0` (§1.1); **no new RTL**, R9 validates | calibration-dependent (mean\|x\|); 1.9 MiB build-time npz; +0 bits/weight |
| **V4gptq** | **999,428,096** | **1.000** | **20.75 - 21.51** | **—** | **953 MiB, 74 % OK** | **NONE** | **accepted under waiver** (re-affirmed) — −0.025 / +0.001, violations all in custom RTL incl. migrated `layer_0` (§1.1); **no new RTL**, R9 validates | calibration-dependent; image build 918→1,949 s; 4.5 GiB build-time Hessian npz; `audit_ranges` mis-ranks it (§6.3) |
| V4mix top-1 | 1,301,417,984 | 1.302 | 19.00 - 19.84 | −8 % | 1,241 MiB, 97 % OK (3 % margin) | **W8 engine mode + per-class emitter** | **re-opens timing in the worst block** — a W8 mode rewrites `matvec_engine`, which already owns the shipped roll's worst 22 endpoints (24 in total, §1.1) | dominated by the composed point at identical bytes |
| V4mix top-2 | 1,555,697,664 | 1.557 | 17.71 - 18.59 | −15 % | 1,484 MiB, **116 % DOES NOT FIT** | W8 engine mode + per-class emitter + repack | **re-opens timing in the worst block** — a W8 mode rewrites `matvec_engine`, which already owns the shipped roll's worst 22 endpoints (24 in total, §1.1) | worse PPL than free V4gptq |
| V4mix top-3 | 1,707,282,432 | 1.708 | 17.04 - 17.93 | −18 % | 1,628 MiB, **127 % DOES NOT FIT** | W8 engine mode + per-class emitter + repack | **re-opens timing in the worst block** — a W8 mode rewrites `matvec_engine`, which already owns the shipped roll's worst 22 endpoints (24 in total, §1.1) | the composed point matches its PPL for 302 MB and one channel |
| **V4gptq + `gate_up` W8** | **1,301,417,984** | **1.302** | **19.00 - 19.84** | **−8 %** | **1,241 MiB, 97 % OK (3 % margin)** | **W8 engine mode + per-class emitter** | **re-opens timing in the worst block** — a W8 mode rewrites `matvec_engine`, which already owns the shipped roll's worst 22 endpoints (24 in total, §1.1) | mixed image = materially more emitter work than uniform W8; 3 % window margin is thin |
| **V5 — W8 everywhere** | **1,936,920,576** | **1.938** | **16.11 - 17.02** | **−21..−22 %** | **1,847 MiB, 144 % DOES NOT FIT** | **W8 engine mode (uniform) + the §5 per-channel repack** | **re-opens timing in the worst block** — a W8 mode rewrites `matvec_engine`, which already owns the shipped roll's worst 22 endpoints (24 in total, §1.1) | needs a bigger window *or* the repack; nch=4 does **not** rescue it |
| *0.8B production (W4 g128)* | *417,435,648* | *0.418 of 2B V2* | ***30.4 tok/s MEASURED on hardware*** (31.7 steady-state³) | *—* | *398 MiB, 31 % OK* | *shipped* | *WNS +0.009 on build_033_rr* | *the reference point: everything above is modeled, this row is silicon* |

³ The published 30.4 tok/s is 32.94 ms/token, which charges every token 1/6 of
the session-once 8.671 ms preamble. Steady-state per-token is **31.50 ms =
31.7 tok/s**, measured independently by `chat_seq --canned`
(`evidence/qwen2b/ra/MOVER_NORM.md` §3.1, §3.4). The 2B model in this table is
built on the corrected 31.50 ms decomposition, not on 32.94.

### 1.1 The timing cell — what "accepted under waiver" means

All of it from `evidence/qwen2b/rb/TIMING.md` (build_034, netlist / VERSION CSR
`4f908df2`, shipping roll `synth/out_build_034_po2_AltSpreadLogic_high`), whose
**§5 shipped-roll census is the authoritative source** — earlier rolls have
different placements and therefore different failing paths.

> **WNS −0.025 ns, WHS +0.001 — accepted under a WRITTEN WAIVER by USER
> DECISION dated 2026-08-16, and RE-AFFIRMED the same day against a corrected
> technical rationale.** Two prompts are on the record: the first accepted the
> waiver on a failing-path class that later proved wrong, and the second — the
> **operative** decision — re-put it on the corrected facts below (re-affirm /
> targeted-fix-first / hold) and the user chose re-affirm. It is **not** closed
> to ≥ 0.

**The violations are 100 % in our own logic, and that is a change from what an
earlier revision of the timing record said.** Every failing endpoint on the
shipped roll was enumerated (`get_timing_paths -slack_lesser_than 0`, count 50,
reconciling with the design summary; raw output
`evidence/qwen2b/rb/shipped_roll_endpoint_census.log`):

| owner | EP | clock | slack |
|---|---|---|---|
| `mvchan_2/…/u_engine` — **`matvec_engine`** | **24** | ch2 UI, 300 MHz | −0.025 … −0.007 |
| `layer_0/u_core/u_dn` (`dn_step`) | **18** | `xdma_0_axi_aclk`, 250 MHz | −0.011 … −0.001 |
| `layer_0/u_core/u_topk` + 3 loose regs | 5 | 250 MHz | |
| `seq_0/u_seq` MOV addressing | 3 | 250 MHz | −0.010, −0.003, −0.002 |
| **total** | **50** of 1,193,865 (0.0042 %) | TNS −0.613 | |

**Zero endpoints in `ddr4_*`, `xdma_*`, `axi_smc` or `smc_ch*`.** The DDR4 ch3
write-buffer class that dominated the *base and Explore* rolls — and that the
superseded rationale was built on — **does not violate on the shipped roll at
all**: `mmcm_clkout0_1` finishes at **+0.001 with zero failing endpoints**, and
four of the six clocks meet timing outright.

Why the user re-affirmed anyway, and why the study still calls the four W4 rows
buildable today:

* **Bounded**: 0.0042 % of endpoints, TNS −0.613 ns, three well-understood
  classes.
* **Magnitude is picoseconds**: −0.025 ns is 0.75 % of the 3.332 ns period;
  −0.011 ns is 0.28 % of 4.000 ns.
* **Precedent, twice on the same 250 MHz domain**: `build_026` shipped −0.142
  (24/24 runs bit-exact), `build_030` shipped −0.141 (26/26 host ladder,
  board-resident, and its census was likewise recorded as diffuse `layer_0`
  congestion), `build_028` shipped −0.106 (HW 34/34). The `layer_0` class here
  is **13× smaller** than either 250 MHz precedent. *(build_033 at +0.009 and
  build_032 at 0.000 are* not *negative-WNS precedents and should not be cited
  as such.)*
* **A real failure would be caught, not silent**: the R9 hardware ladder is
  bit-exact against the reference model, so a genuine setup failure surfaces as
  a gate mismatch rather than quiet numerical drift.
* **Hold is clean**: WHS +0.001, 0 failing hold endpoints, 0 pulse-width
  failures — though note it was *measured* non-negative throughout and only
  *enforced* by an abort guard in **iteration 3 — not on the shipped roll**,
  which is iteration 2, so +0.001 there is an outcome rather than a guarantee
  of the flow.
* **The playbook is exhausted**: −0.369 base → −0.214 plain spread → −0.134
  post-route phys_opt → **−0.025 full recipe (both phys_opt stages)** → three
  further directives returning **bit-identical** slack (saturation proven) →
  two more placement cards lost (−0.321, −0.493). ~14 h over 4 iterations.
* **Pipelining cannot fix it** — for a routing reason, not a depth reason.
  Depth *varies* across the violating set (class A uniformly 5 logic levels;
  class B's 23 endpoints range 0–11 with a **mode of 2**; class C is 6), so
  there is no single pipelining target. What is uniform is that the delay is
  overwhelmingly interconnect: class A `logic 0.399 ns (12.8 %) / route
  2.714 ns (87.2 %)`, class B `logic 0.311 ns (7.95 %) / route 3.599 ns
  (92.0 %)`. Pipelining subdivides the *logic* term, which is already only
  8–13 % of the path — eliminating it outright would still leave 87–92 % of the
  delay untouched.

**What this costs the migration story, stated plainly.** The waived violations
sit **inside migrated logic** — `layer_0`'s `dn_step` output-select mux carries
18 of the 50 — so R-b cannot be described as timing-neutral. Two scoping points
keep that from being over-read in the other direction:

* **The census attributes endpoints, not causes.** `matvec_engine`'s failing
  family (`xline_q0_reg[*]/CE`) is the *same structure* that was build_033's
  −0.344 critical path, i.e. a recurring hot spot rather than something R-b
  introduced.
* **The two R-b watch items are "not implicated at the top of the violation
  set", not "proven absent".** Neither the R4 96:1 scales mux nor the R6 EMB
  5-bit barrel shift appears in either of the two worst violating paths on the
  shipped roll; `report_timing_summary` lists only the worst path per group, so
  the remaining 48 endpoints are not individually attributed to a watch item
  either way. The R6 3-bit mitigation — which would have cost fidelity — is
  still not indicated.

**R9 validation should target the violating classes specifically:** channel-2
traffic compared against ch0/1/3, which all meet timing (**an asymmetry between
ch2 and the other three is the signature**); `dn_step` behaviour and,
secondarily, top-k selection; and a sequencer **MOV addressing** check for the
`seq_0` tail.

**Utilization**, for the capacity question gate D might ask: device-wide
**+16.0 BRAM tiles** vs build_033 — exactly the R-b prediction — with URAM and
DSP unchanged. The shipped netlist differs from the base roll by **−1086 LUTs /
+2186 registers** (phys_opt replication). The feared SLR1 BRAM concentration
**did not occur**: the placer mirrored SLR1↔SLR2 (URAM and DSP counts swap
exactly between them), so SLR1 Block RAM is 16.25 %, and the per-SLR percentage
is a placement artifact that should not be quoted as a result. The figure that
should be tracked is **SLR1 CLB occupancy 79.88 %** (033: 76.19 %) — the
highest per-SLR pressure in the design.

**The clause that belongs on every W8-bearing row — and the corrected census
makes it sharper, not softer.** A W8 engine mode is new logic on a design
already accepted only by waiver, with no margin in hand and the main untried
lever (floorplanning — **the design has no pblocks at all**) unproven in this
project. Worse for the W8 case specifically: the block a W8 mode would rewrite
is **`matvec_engine`**, which is exactly where the shipped roll's **worst 22
endpoints already sit** (24 of the 50 in total), and `W8_SKETCH.md` widens precisely the structures
around them (the lane array halves in count and doubles in operand width,
`acc_bank` doubles in depth and grows 18 → 20 bits, `g_cnt` 6 → 7 bits). The
sketch's own unpriced item — the lane array's LUT/DSP area, "one synthesis run
of a parameterized `matvec_engine`" — is therefore also the timing question.
The cost of a W8 variant is not just the RTL in `W8_SKETCH.md`; it is a
re-opened timing campaign in the design's worst-behaved block.

**How the tok/s column is built, and what it inherits.** `step = matvec(r) +
movers 15.994 + layer 17.4` ms at nch=4, with `r` over MOVER_NORM's
**calibration-free** bracket [1.000, 1.131] ui-cyc/beat (= 17.0-19.2
GB/s/chan), and matvec taken on the **busiest** channel (3,915,664 beats at
2B, not beats/4). Only the matvec bucket moves with precision — MOVX/MOVY/LDC/
CSRWR move activations, results and constants, and the MVGO record count
follows the row split, not the row stride. Two caveats, both from the source:

* the **17.4 ms layer term is the feasibility study's figure and is NOT
  verified** — MOVER_NORM flags it as the widest uncertainty in this line. It
  is the reason the *absolute* tok/s numbers are weaker than the *relative*
  column, which depends only on the matvec share and is bracketed over both
  `r` and the layer term (V5: −20.9 % at r=1.000, −22.4 % at r=1.131, and
  −31 % in the worst case with the layer bucket removed entirely).
* the 2B record mix is **derived, not emitted** — the SEQ emitter could not
  run at 2B when MOVER_NORM was written (15-bit scratch packing, since fixed
  in R-b). Re-run the census against the first real 2B 4-chan stream.

**Doubling weight traffic does not halve throughput.** The matvec bucket is
only ~28 % of the modeled 2B step, which is why full W8 costs −21..−22 %, not
−50 %; the mover bucket alone (16.0 ms) makes anything near −50 %
arithmetically impossible.

---

## 2. What a PPL point costs in bytes — the frontier

| variant | ΔPPL bought vs V2 | extra bytes/token | **MB per PPL point** |
|---|---|---|---|
| V3 | +0.352450 | 0 | **0** (free) |
| **V4gptq** | **+0.802992** | **0** | **0** (free) |
| V4mix top-1 | +0.468726 | 301,989,888 | 644 |
| V4mix top-2 | +0.768270 | 556,269,568 | 724 |
| V4mix top-3 | +1.023994 | 707,854,336 | 691 |
| **V4gptq + `gate_up` W8** | **+1.007457** | **301,989,888** | **300** |
| V5 | +1.383553 | 937,492,480 | 678 |

Three points carry the study's recommendation: **V4gptq** (free), **V4gptq +
`gate_up` W8** (the cheap intermediate, 2.1-2.4× more byte-efficient than
anything else that spends bytes) and **V5** (near-lossless).

The V2-based mixed maps are **dominated (top-1, top-2) or beaten on value
(top-3)** — see §4. The distinction is worth keeping straight: top-1 and top-2
are *strictly* dominated, top-2 scoring **worse** than free V4gptq while
spending 556 MB more. **Top-3 is not dominated** — at 12.720237 nothing cheaper
scores better, and the composed point is 0.016537 PPL worse, a gap this harness
resolves comfortably. It loses on *value*, not on quality: reaching it costs
**+406 MB/token over the composed point**, overflows the weight window (127 %),
and takes −18 % tok/s instead of −8 %.

---

## 3. Narrative (a): the ablation decomposition, and why V6 never opened

The ladder is `exact float → w4deq (float compute, W4 weights) → fixed
(the whole FxRunner)`, 108 teacher-forced steps = 4 prompts × 27
(`evidence/qwen2b/q2/v1_v2/DECOMP.md` Table B).

| wire group | res_scale | weight damage | datapath damage | total |
|---|---|---|---|---|
| g128 | S=4 | 108→93 = **−15** | 93→80 = **−13** | −28 |
| g128 | S=8 | 108→93 = **−15** | 93→83 = **−10** | −25 |
| g64 | S=4 | 108→94 = **−14** | 94→80 = **−14** | −28 |
| g64 | S=8 | 108→94 = **−14** | 94→86 = **−8** | −22 |

> **THE V6 VERDICT: the datapath-precision axis does NOT open at 2B.** It
> would have opened iff datapath damage exceeded weight damage on both
> fidelity metrics and on text. It does not: the W4 weight format costs 14-15
> top-1 steps of 108 against the entire fixed-point datapath's 8-13, in every
> configuration measured; the datapath never exceeds it and ties only once
> (g64 S=4). Rank median is 0.0 on both sides. Precision work in the RTL is
> therefore not the binding constraint at 2B, and no V6 modeling task was
> added.

Two supporting facts that make the ladder attributable rather than
suggestive: the exact-float row scores **108/108** with rank max 0 and
reproduces the torch golden's free-run text verbatim on all four prompts (the
float reference contributes exactly zero to the loss budget at 2B), and two
independent implementations of the g128 MSE W4 image agree on all 108
argmaxes, all ranks and all four texts.

The one metric that points the other way — rank *max* blowing up to 911/1312
at g64 — is a **step-0 artifact**: step 0 predicts from a one-token context,
the same blow-up is already present in the shipped 0.8B production run (rank
136 and 845 at p1/p2 step 0, `evidence/stage5/fidelity_mq15_prod.log`), and V3
removes it anyway (911 → 7 at S=4). It is a property of ranking a one-token
context, not a 2B or g64 signal.

**Practical consequence, and the one place the two knobs interact.** The
cheapest remaining quality is on the **weight** axis: g64 buys 3.05 % of PPL
for 0.011 bits/weight. But whether the fixed-point path *banks* that gain
depends on res_scale, and at the ruled S=4 it does not — at S=8 g64 buys +3
top-1 steps (83→86), at S=4 it buys **zero** (80→80) and is slightly worse on
text. That interaction is why the two were swept together, and it is why the
free quantizer improvements (V3, V4gptq) matter more than the group-size knob.

---

## 4. Narrative (b): sensitivity, why V4mix died, and how the quantizer axis won

**The ranking.** Per-class one-at-a-time W4 g64 damage
(`evidence/qwen2b/q2/sensitivity/SENSITIVITY.md`, derived by
`ref/scripts/rank_sensitivity.py`, output `rank_sensitivity.txt`):

| rank | class | params | ΔPPL vs bf16 | ΔPPL / Mparam |
|---|---|---|---|---|
| 1 | `gate_up` | 603.98 M | **+0.469470** | +0.00078 |
| 2 | `lm_head` | 508.56 M | **+0.272859** | +0.00054 |
| 3 | `dn_in` | 303.17 M | **+0.185680** | +0.00061 |
| 4 | `down` | 301.99 M | +0.139524 | +0.00046 |
| 5 | `o_proj` | 25.17 M | +0.128317 | **+0.00510** |
| 6 | `qkv` | 62.91 M | +0.116240 | +0.00185 |
| 7 | `dn_out` | 75.50 M | +0.010640 | +0.00014 |
| — | `emb` (emb16, not a W4 class) | 508.56 M | +0.000177 | ~0 |

**Class SIZE predicts damage** (Spearman rho **+0.857** over the 7 W4 classes,
exact permutation p=0.0238); the per-matrix W4 reconstruction error that the
audit flagged predicts it **not at all** (rho **−0.179**, p=0.7131). The
metric's #1 (`qkv`, holding the model's single worst matrix at 17.28 %) ranks
6th of 7 by ΔPPL; `gate_up`, whose worst matrix is nowhere near the bound,
ranks 1st. The scan is complete and mildly super-additive: the 8 deltas sum to
1.322907 = **94.6 %** of V2's joint 1.397933.

**Why that killed the mixed-precision middle.** The ranking put the three
*largest* classes on top — so promoting them by sensitivity is the same thing
as promoting them by bandwidth. Task 7 predicted from bytes alone that V4mix
top-3 would spend 88 % of full-W8 bandwidth to recover 66 % of the damage.
Q9 measured it, and the ladder came in almost exactly where the arithmetic
said — error **+0.000744 / −0.025942 / −0.095986** PPL at k=1/2/3. Note the
signs: k=1 came in slightly **worse** than predicted, k=2 and k=3 better, as
W8's own residual and Task 7's super-additivity trade places. **There is no cheap mixed-precision win at 2B, because damage
tracks size and so does bandwidth.**

**And then the quantizer axis beat it outright.** V3 recovered 25.2 % of the
V2→bf16 gap for **+0.000000 bits/weight**; V4gptq recovers **57.4 %** at the
same 6.752534427466289 bits/weight, identical to V2/V3 to the last digit, with
the wire format, `row_stride`, group scales `m` and shared exponent `e` all
untouched. The decomposition of that gain is single-variable and measured:
swapping the diagonal from `(mean|x|)²` to `E[x²]` buys −0.175659, and the
error feedback a diagonal Hessian *provably cannot express* buys a further
**−0.274943**. Independently of PPL, the per-token RMS output error
`||(W−Wq)Xᵀ||_F/√T` falls **41.7 % mean, better on 7/7** real matrices.

The collision is the finding: **V4mix top-2 costs 556 MB/token more than
V4gptq and scores worse** (12.975961 vs 12.941240). V4mix top-3 does beat
V4gptq by 0.221 PPL — but for 708 MB/token, a pack that overflows the window,
−18 % tok/s and an emitter that must learn per-class precision.

**The composition nobody planned.** Once GPTQ is the W4 base, the interesting
mixed point is no longer "V2 + W8". `all:w4g64gptq,gate_up:w8g128` lands at
**12.736774 — V4mix top-3's quality (12.720237) for top-1's bytes** — still
fits a single channel at 97 % of the window, and costs **300 MB per PPL
point** against 644-724 for every V2-based mixed map and 678 for V5. The same
+302 MB that bought 0.469 PPL on the V2 base buys 0.204 on the GPTQ base
(GPTQ has already repaired much of `gate_up`'s damage) — and still wins,
because it starts 0.8 PPL lower.

So the V2-based V4mix ladder survives as **the controlled measurement of how
mixed precision behaves at 2B**, and not as a candidate.

---

## 5. Narrative (c): the W8 wire sketch, and what a W8 variant would cost

`evidence/qwen2b/q2/v4_v5/W8_SKETCH.md` — **text only, no RTL exists**. It is
the costing basis, not a design. The host side is already committed and
self-tested (`quantize_weights8` / `row_beats8` / `row_stride8` / `pack_w8` /
`pack_ddr_rows8` / `unpack_ddr_rows8` in `ref/w4a8_ref.py`), so the byte
column above is a real number, not an 8.125 b/w idealization.

**The row** is the W4 row with one substitution — a weight is a byte, not a
nibble. Beat size, `[weight beats | scale beats]` order, the
uint16-mantissa-per-group scale with one shared exponent, the 64 B stride and
the final `rshift_round` are all unchanged, so Task 4's arbitrated
dequantization formula applies verbatim (re-checked for W8 to 0.500 lsb / 8.3e-07
relative). Consequence: **W8 is 1.944× its W4 g128 twin at 2B, not 2.000×** —
the weight side doubles, the scale side does not, and beat-padding overhead
*falls* (8.237 b/w against an 8.125 ideal, +1.4 %). *(Mind the denominator:
the byte table's 1.938 is ×**V2**, whose g64 rows carry an extra scale beat at
K=6144. `V4_V5.md` §4 mis-stated 1.938 against "W4 g128"; corrected at source
in `a67a306`. Its 0.8B figure, 1.901, was already against g128.)*

**The one real format constraint it found:** `ng` must keep meaning `K//128`
in W8 mode (weight beats = `2·ng`), or the 6-bit SHAPE field overflows at
K=6144 (96 > 63). Keeping it also reuses the mode-0 scale-beat count
unchanged. `R_SHAPE` bit 29 is proposed as the `w8` flag, leaving [31:30]
spare.

**Engine delta:** the nibble unpack disappears, the lane array halves in count
and doubles in operand width, the beat counter and retire walk run to `2·ng`
with scale index `r_g >> 1`, `acc_bank` grows to `2·MAX_NG` entries (the depth
the scale buffer already has), `acc_bank_{lo,hi}` +2 bits (18→20), `g_cnt`
6→7 bits. The retire product stays **one DSP48E2**, `p_acc` stays 48 b,
`cfg_sh` stays 6 b, `x_mem` and `WBEATS` are unchanged. **Not priced:** the
LUT/DSP area of 64 lanes of 8×8 against 128 lanes of 4×8 — that needs one
synthesis run of a parameterized `matvec_engine`, and the sketch says so
rather than guessing.

**Host/emitter delta** (so the estimate is not "just RTL"): `shape_word()`
gains the `w8` bit, `plan_weights` gains a W8 stride branch, the weight
manifest needs a per-image format tag, and the generators must call the W8
quantizer/packer. **A mixed map is materially more emitter work than V5's
uniform one** — the emitter today has no notion of per-class precision at all.
Nothing in the SEQ ISA moves.

**And the prerequisite that is easy to miss — §5 of `V4_V5.md`:** the weight
window is 1,280 MiB per channel and `sw/layer_test.py:plan_weights` *asserts*
the pack ends below `EMB_BASE`. **`plan_weights` takes no `nch`**: it
accumulates full image footprints from `W_BASE`, and
`sw/seq_run.py:plan_weight_split` then slices each channel's rows *inside*
that span. So the nch=4 column of the byte tables is a **BYTES result, not
today's fit** — V5 trips the same assert at nch=4 as at nch=1. Turning those
per-channel byte counts into a real fit needs per-channel image bases **plus**
per-chunk rebasing of the ILV-placed LM head (whose channel rows are strided,
not contiguous). That is host + emitter work, not RTL, and it is on the
critical path for **every W8 variant beyond top-1**. No re-map is proposed
here — the address map is Track R's.

**Why there is no W8+GPTQ row:** out of scope by argument, not schedule. GPTQ
re-rounds against the quantization residual of neighbouring columns, and at 8
bits that residual is 15-18× smaller than at 4 (measured). V5's *entire*
damage is +0.014380 PPL, so all the headroom a better W8 quantizer could
recover is inside the study's own resolution.

---

## 6. Narrative (d): risks

### 6.1 Range-audit findings at 2B (applies to every row)

`ref/audit_ranges_2b_report.md` §6, against a same-day 0.8B control run so
model-vs-model deltas are not confounded with two production code changes.

> **No NEW hard saturation appears at 2B.**

That is the audit's §6.7 verdict, quoted. Unpacking it in this document's own
words: no container that passed at 0.8B saturates at 2B — the scratch int16
rail and the conv `CW_F` rail hold with room, and most families gain margin.
**The `Av` uint18 Q3.15 gate port is deliberately left off that list**: the
audit reports it as passing, but it is reading *post-clamp* values, and the
pre-clamp probe finds **1 of 288 heads over the port** (item 3 below).

Ranked by what the numbers support:

1. **W4 error above the project's own 15 % bound: 0/187 → 15/187**, worst
   `L19.attn.v_proj` at 17.28 %. Twelve of the fifteen are the 16×2048
   DeltaNet gate projections, which doubled in K without gaining a row. No
   assert fires — the bound only exists inside `w4a8_ref._selftest`. **And
   §4 shows this metric does not predict PPL damage** (rho −0.179): those 12
   matrices are **0.021 %** of all W4 weights (the 0.063 % in
   `SENSITIVITY.md` §5 is the whole 36-matrix `dn.in_a`+`dn.in_b` family). *(Risk: fidelity, low —
   quantified and ranked.)*
2. **Gate-port overflow more than doubles: `dt_bias` over its int16 Q3.12
   port on 2 → 5 of 288 heads**, and the production clamp now changes 5 head
   decays, worst `L0h13` 0.244 → 0.333 (+36 % relative), largest relative
   `L0h3` 0.0105 → 0.0215. Bounded and deterministic, and far better than
   the pre-clamp wrap it replaced — but at 2B it is no longer a 2-head
   curiosity. *(Risk: fidelity, DeltaNet-specific.)*
3. **The auditor is blind to (2)** — `quant_deltanet` saturates `dt_bias` and
   `A` before `audit_ranges` sees them, so sections 1 and 3 report "0 of 288
   out of range" and section 3 prints a literally false justification ("max
   10.4202 < 8.0"). The script now carries `GATE_CLAMP_NOTE` in its header
   and beside both gate tables, but it still does not measure the truth: any
   range claim about `A`/`dt_bias` must come from `qd["gate_sat"]` or
   `evidence/qwen2b/q2/audit/gate_port_probe.py`. *(Risk: process/evidence,
   not silicon.)*
4. **`model.norm` needs the production Q3.12 fold** (79.7 % of the rail at
   2B vs 78.9 % at 0.8B). Section 1's Q1.14 ATTENTION is the auditor's
   format, not the emitter's. *(Risk: none today, 1.25× margin — but that
   margin is a weight fact a future checkpoint can spend.)*
5. **Residual seed resolution 5.73 % → 7.52 % rel RMS at S=1, 1.89 % at the
   ruled S=4**; nothing clips at any S ≤ 16. *(Already priced into the S=4
   ruling.)*
6. **y32 headroom wasted grows 5.3 → 5.9 bits** (`L23.mlp.down`, K=6144).
   Precision only; the RTL still matches the reference bit-for-bit.

Improved at 2B, for the record: conv `CW_F` occupancy 45.5 % → 39.1 %,
`ln1`/`ln2` 73.4 % → 60.2 %, max `A` 10.58 → 10.42, max |`dt_bias`| 13.06 →
12.31, and the W4 group-underflow rate 0.0019 % → 0.0015 % (the *same* 14 dead
rows of `L0.dn.in_qkv`, every value `1.175e-37` = FLT_MIN — a structural
artifact of the Qwen3.5 DeltaNet input projection, measured on both
checkpoints, not a quantizer failure).

### 6.2 `res_scale`: S=4 is the ruled 2B default

`--res-scale 8` is the 0.8B production value; at 2B it **rails the int16
residual**. The sweep (`DECOMP.md` §3):

| S | top-1 /108 | \|x\|max (rail 32768) | residual clips | verdict |
|---|---|---|---|---|
| **4** | 80 (g128) / 80 (g64) | 23165 (71 %) / 26465 (81 %) | **0 / 0** | **clip-free, headroom left — RULED DEFAULT** |
| 8 | 83 / 86 | **32768 (rail)** | 13 / 22 | best top-1, but clipping |
| 16 | — | — | — | run aborted (host fault, §6.4) |

**Rationale for taking the lower-scoring option:** S=8 wins by 3-6 top-1 steps
on a 108-step sample — a margin §1 has just shown is not statistically
resolvable — while clipping 13-22 times. Clipping is a hard nonlinearity whose
incidence grows with context length, so an advantage measured over 24 generated
tokens is no evidence it survives at 512. S=4 keeps 29 % headroom with zero
clips. The embedding table is not the binding term either way (|q|max 202 at
S=4, 404 at S=8, of 32767) — what saturates is the *accumulated residual*,
which is what scales with hidden size. V3 then removed the reason this ruling
had to be hedged: at S=4 the salience quantizer takes the clip-free
configuration to 86/108, the score V2 could only reach by railing.

One consequence recorded for exactness: V1/V2 were scored at S=8 per the
controller's ruling that the study scores what the hardware ships. Adopting
S=4 moves the emb table one bit coarser; the bound on that re-score is ~2× the
measured emb16+cw13 increment, i.e. **~0.0006 PPL against a 1.83 PPL signal**.
The PPL rows stand to well within that bound.

### 6.3 GPTQ-specific risks (V4gptq and the composed point)

1. **The gain is calibration-dependent by construction.** GPTQ compensates
   against the *calibration* activations — 32,768 tokens of
   `ref/ppl_corpus_calib.txt` (the train slice; `main()` refuses the eval
   corpus by filename). It is scored on a **disjoint** eval slice, so the
   −0.45 PPL is genuine generalization, not fitting — but a deployment whose
   input distribution is far from this corpus would see less. V3 has the same
   exposure through its salience, to a smaller degree.
2. **Build cost.** Quantizing the model goes 918 s → 1,949 s (+112 %), plus a
   one-off 241 s calibration producing a **4.5 GiB** npz (gitignored,
   regenerable in ~4 min). It is a **build-time** input only — nothing about
   it reaches the board, and inference/RTL/DDR cost is **zero**.
3. **Ship-readiness — wired, not yet exercised end to end.** Before task 8b
   the DDR image generator could not produce a calibrated image at all
   (`gen_model_script` called `quant_layer` with no `layer_idx`, and
   quantized the LM head with no calibration arguments — a *silently*
   unweighted head under a calibrated name). Both emitters that quantize the
   real checkpoint are now wired, the regen gate still passes, and all **186
   layer + 1 head** lookups resolve in both `gptq` and `salience` modes.
   **Not claimed: no calibrated 2B image has been emitted yet.** That is an
   R-c work item, and it is a prerequisite for shipping any calibrated
   variant — V3 as much as V4gptq.
4. **`audit_ranges` will mis-rank a calibrated image, by design.** It reports
   a per-matrix *Frobenius weight* error; GPTQ minimises `||(W−Wq)Xᵀ||`, not
   `||W−Wq||`, and buys the first with the second — weight error rises 5.510
   → 7.010 on the first row sampled and on every row. **A re-run of that
   audit against a V4 image will read as a regression while the model is
   measurably better.** Two closing actions if a calibrated variant is
   adopted: (a) `audit_ranges` **cannot score a V4/GPTQ image at all today** —
   it re-quantizes from the checkpoint rather than reading an image, and with
   the calibration plumb on it SystemExits for want of a `layer_idx`; it needs
   either that wiring or an image-reading mode; (b) once it can, the Frobenius
   column must be labelled "not the objective for calibrated quantizers", or
   given an output-error column beside it.
5. **What is *not* claimed for GPTQ:** the fixed-point probe is a **tie**
   (85/108 vs V3's 86, p=1.000), and its rank tail moved the wrong way vs V3
   (rank sum 45 → 132, of which 81 of the 87-point rise is two steps; 13
   worse, 13 better, 82 unchanged). V2's 992 puts that in perspective. The
   probe establishes **safety** — clip-free at S=4, residual peak 86 % of the
   rail, S_F saturation *lower* than V3, the same head `e=-4 sh=6`, readable
   free-running text — and nothing more.
6. **"Lite" means no act-order** (it breaks the wire format — the RTL walks a
   row in beat order) **and group scales fixed before the sweep** (the shared
   exponent `e` cannot be known until the last group's scale is, so doing it
   textbook-style is a two-pass problem). The cost of the second choice is
   unmeasured here; the direction is that `m` and `e` are identical to the
   no-feedback rule by construction.

### 6.4 The host fault — and what it does and does not cost the numbers

**What happened.** An assertion that *cannot* trip on correct arithmetic —
`ref/w4a8_ref.py:161`, `assert np.abs(acc).max() < (1<<31)` on an int8×int8
group dot product whose arithmetic ceiling is ~10⁵ — fired repeatedly on
**darthplagueis**: twice during Q5 (unreproduced, under load), then **six
times in one working day** during Q8 on a quiet host, twice inside the frozen
0.8B regen gate with the calibration plumb **OFF**, once killing the process
with SIGSEGV inside numpy (kernel log; OOM explicitly excluded — zero
`oom-kill` events in the window). A committed shim audited 36 trips over 35
distinct calls: operands in legal range every time, the identical call
succeeded on retry every time, and an independently ordered re-reduction
agreed bit-for-bit. Two runs with byte-identical arguments aborted at
*different* call sites, which a deterministic pipeline cannot do. The trips
span three block types and a 4× range of allocation size, so they do not
localize to one buffer or DIMM. Instance 7 appeared during R-b's sim gate,
same signature, green on retry and on snoke. **Diagnosis: transient wrong
results from a large int64 reduction on this host — memory or CPU corruption;
the evidence does not distinguish which.**

**How the published numbers were defended.** The campaign moved to **snoke**
and stayed there: every number from Q8 onward (V3's fixed-point runs, all of
V4gptq, all five Q9 points) was produced on snoke, and every json carries its
`host`. Specifically:

* **V3's PPL was re-scored on snoke** — PPL agrees to all six published
  decimals (13.391781) with `nll_sum` differing 1.05e-8 relative, on a
  different host, interpreter and torch build. That is what closed V3.
* The **calibration npz** was a fault-window artifact too and was regenerated
  on snoke: worst relative delta over 187 vectors **4.191e-07**, zero channels
  over 1e-5, **183/187 W4 images bit-identical**, 4 group scales differing of
  29.4 M and 7 nibbles of 1.88 G. Not corrupted — two torch builds summing a
  float32 forward in different orders, with a 17-point grid search flipping on
  near-ties.
* Both V3 fixed-point runs report **`GUARD-TRIP CENSUS: 0 event(s)`** — with
  zero events the shim is a pure pass-through, i.e. bit-identical to an
  unwrapped run.
* V4gptq's fixed-point run used the **unmodified** production path with no
  shim at all, and the guard never fired.

**The residue, and how task 10 closed it.** Everything above left one real gap:
**the 2B bf16 anchor, V1, V2 and the whole Task 7 sensitivity scan were
produced on darthplagueis** and reproduced only *within* that host (five checks
in Q5 — including two independent implementations of the same W4 image agreeing
on all 108 argmaxes — and two bit-identical re-runs in Q7). The float PPL path
has no arithmetic guard, so a wrong reduction there would be silent, and
same-host agreement is a weak defence against a *deterministic* fault. Since
every Δ in this study is measured against the anchor and the V2 baseline, that
gap sat under the whole table.

**Task 10 re-scored all three on snoke** (`run_snoke_recheck.sh`, torch
2.12.0+cpu, threads=6 — the same interpreter and build that closed V3), and
compared them with `crosshost_check.py` (log: `crosshost_check.log`):

| point | darthplagueis | snoke | \|ΔPPL\| | nll_sum rel | setup fields differing |
|---|---|---|---|---|---|
| bf16 anchor | 12.346298254 | 12.346297872 | 3.8e-07 | **1.23e-08** | NONE |
| V1 | 14.176885073 | 14.176885557 | 4.8e-07 | **1.29e-08** | NONE |
| V2 | 13.744231195 | 13.744231251 | 5.7e-08 | **1.57e-09** | NONE |

**CROSSHOST_PASS.** All three agree at the **1e-9..1e-8 relative** level on
`nll_sum` — the established cross-torch-build band (V3's own cross-host delta
was 1.05e-08; the calibration vectors spread 4.19e-07) — and every setup field
matches: corpus, checkpoint, window, batch, 24,528 positions, injection plan,
bit rate and the whole per-class accounting. A transient wrong int64 reduction
would not hide at 1e-8; this closes the attribution gap.

**One disclosure, because the printed value moves.** V1's PPL prints as
**14.176885 on darthplagueis and 14.176886 on snoke** — the two values are
14.176885073 and 14.176885557, so the number sits on a rounding boundary and
the sixth decimal flips on a 4.8e-07 difference. It is a display artifact of
the same 1e-8 band, not a disagreement: `ΔPPL` is 3.4e-08 relative, against a
V1 row whose decision content is "+1.83 PPL, worst on the board, superseded by
V2". This document keeps the committed original (14.176885) as the citation and
records the snoke value beside it. bf16 and V2 print identically on both hosts.

**Still not re-scored on snoke: the Task 7 sensitivity scan** (8 points +
2 re-runs, darthplagueis). It is not load-bearing for any *table* row — it
selected the V4mix maps, and those maps are the ones §4 rules out — and it
carries the same second-hand cross-host support it always did: Task 7's
prediction for V4mix top-1, built from darthplagueis's V2 and its `gate_up`
scan delta, lands within **+0.000744** of the snoke measurement (0.05 % of the
V2 gap). Closing it properly is ~26 min of snoke time if gate D ever wants the
ranking itself re-proven.

**Recommendation (the user's hardware, the user's call):** run memtest86+ and
an under-load int64 soak on darthplagueis before it is trusted with another
numeric campaign; until then treat Track Q compute as snoke work.

### 6.5 Two evidence-hygiene notes

* **`V1` and `V2` carry `res_scale 8`**, the value the S=4 ruling supersedes —
  bounded at ~0.0006 PPL (§6.2). Every *variant* row shares that value (the
  anchor is pure bf16 at `res_scale 1.0`, §0), so no variant-vs-variant
  comparison in the table is affected.
* **One Q9 rerun pair is not bit-identical**: the composed point's two
  processes agree to six decimals but differ 9.2e-09 relative in `nll_sum`,
  because they ran at **different thread counts** (8 and 10). Torch's threaded
  reduction order, not the quantizer, is what breaks bit identity across
  thread counts — established in Q8b and confirmed by the five matched-thread
  pairs (including all three mixed maps) that *are* bit-identical. Anyone
  repeating it should pin `OMP_NUM_THREADS`.

---

## 7. Narrative (e): recommendation

> **ADDENDUM 2026-08-16 — R9 has since run, and it PASSED.** Everything below
> (and §9 items 1, 6, 9) was written before the board gate and is kept verbatim
> as the dated record; this block corrects it. Source:
> `evidence/qwen2b/rb/RB_GATE.md`.
>
> * **The widened bitstream is on silicon and the ladder reproduces.** The
>   board is resident on build_034, netlist **`4f908df2`**, read back from the
>   VERSION CSR; every hardware rung H0-H11 **passed on its first execution**,
>   30.351 tok/s (gate convention) / 31.744 tok/s (steady-state), tokens
>   bit-exact against build_033 everywhere. "Never been exercised on the board"
>   is no longer true of any sentence in this document.
> * **All three waiver watch classes are clean.** Class A (channel 2): the four
>   channels lie within **0.0364 %** and the per-channel probe is **32/32
>   bit-exact, 0 errors**. Classes B (`dn_step`/top-k) and C (sequencer MOV
>   addressing): **0 mismatches anywhere** — 14,376 golden chip-state checks,
>   26/26 lockstep steps against `ref/seq_model`, 3 canned argmax runs, 5
>   sampled sessions. The waiver is *not retired* by this — one board, one
>   temperature, one voltage (`RB_GATE.md` follow-on 5) — but no class manifested.
> * **The layer term is now measured, and it re-anchors this document's tok/s
>   model.** The **17.4 ms** 2B layer term of §1.1 (`:263-264`) is the feasibility
>   study's geometry-scaling of the 0.8B layer bucket on record at
>   `docs/ARCHITECTURE.md:639` (**14.13 ms**, `L_LCYC` census). build_034
>   measures that same quantity — same model geometry, 0.417436 GB/token — at
>   **15.368 ms/token** (`RB_GATE.md` follow-on 3), i.e. **+1.24 ms**, so the 2B
>   layer input should be re-anchored upward before absolute 2B tok/s are
>   quoted. The layer term is **quantization-independent**, so the correction
>   **worsens the modelled absolute tok/s of every variant equally: no relative
>   penalty and no ranking in this document changes.** This also closes §9
>   item 6 — the run it was waiting on has happened.

> ### Recommended operating point: **V4gptq — W4 g64 with GPTQ-lite.**
>
> It is the only point on the frontier that costs the board **nothing**:
> identical wire format, identical `row_stride`, identical
> 6.752534427466289 bits/weight, identical 999,428,096 bytes/token, full
> 20.75-21.51 tok/s, 74 % of the weight window, and **zero new RTL** — the
> hardware it needs is already built, gate-green in simulation and timing-
> accepted **on the report** — not yet on silicon: the widened bitstream has
> never been exercised on the board, that is R9 (−0.025 ns under the user's
> written waiver, re-affirmed on the corrected failing-path census, §1.1;
> R-b's widened RTL ends
> green on **17 of 17** sim gate groups — 16 first time, the seventeenth the
> regen gate, green on retry there and on snoke, the §6.4 host fault again —
> and replays every frozen 0.8B stream bit-exact, including the
> 2,272,141-cycle chip stream that pre-R-b RTL produced). It
> lands **0.595 PPL from native bf16**, having recovered **57.4 %** of the
> W4 damage that V2 leaves on the table, and it is safe in fixed point
> (clip-free at S=4, no regression, readable free-running text). Its whole
> price is build-side: +1,030 s of image build, a 4.5 GiB regenerable
> calibration file, and the two tooling items of §6.3.

**Runners-up, both real and both named because gate D may weigh quality
differently:**

* **V5 — W8 g128 everywhere — the maximum-quality option.** +0.014380 PPL
  from bf16; W8 recovers **98.97 %** of everything W4 lost, and its
  whole-model damage is only 1.35× what putting the single *least* sensitive
  class into W4 g64 costs on its own. The price is real and threefold:
  **−21 to −22 % tok/s** (16.1-17.0), a **W8 engine mode** that does not
  exist, and a weight pack at **144 % of the window** that needs either a
  bigger window or the per-channel repack of §5 — at nch=4 as much as at
  nch=1. **Add a fourth, from the corrected timing record**: that engine mode
  rewrites `matvec_engine`, which already carries the shipped roll's worst 22
  failing endpoints (24 of 50 in total, §1.1). Its one structural advantage over the mixed middle:
  the image set is **uniform**, so the emitter needs no notion of per-class
  precision.
* **V4gptq + `gate_up` W8 — the middle.** 0.390 PPL from bf16 at 1.302×
  bytes and −8 % tok/s, and **it still fits the current single-span pack**
  (97 % of the window). At 300 MB per PPL point it is more than twice as
  byte-efficient as anything else that spends bytes. Two cautions: it needs
  the same W8 engine mode *plus* per-class emitter support (more work than
  V5's uniform image set) — and so it carries the same `matvec_engine` timing
  exposure as V5 (§1.1) for a smaller quality gain — and 3 % window margin is
  thin: any future image growth breaks it.

**Argued against and rejected as candidates:** V1 (strictly worse than V2 for
0.011 bits/weight), the entire V2-based **V4mix** ladder (top-1 and top-2 are
dominated outright by a free quantizer; top-3's quality is matched by the
composed point for 302 MB and one channel), and **V3** — which is not wrong,
just superseded: V4gptq is the same wire format at the same bit rate and
recovers 43.1 % of the gap V3 leaves open. Keep V3 only as the fallback if the
extra build time or the 4.5 GiB Hessian file is unacceptable.

**What the recommendation does NOT rest on.** The fixed-point probe. It cannot
resolve a −0.45 float-PPL improvement and says so — by its own McNemar
arithmetic it cannot even resolve V3's +6 steps over V2. The recommendation
rests on the 24,528-position PPL (bit-identically reproduced in a second
process) and on the independently measured per-matrix mechanism. It also does
not rest on the absolute tok/s figures, which inherit an unverified 17.4 ms
layer term — but V4gptq is the recommendation *because* it moves no bytes at
all, so it is the one row for which the throughput model does not matter.

**Gate D is the user's decision.** The post-D plan (R-c/R-d, ± the W8 engine
mode and the per-channel repack) is written only after the pick.

---

## 8. Traceability index

Every number in this document, by source. Paths are repo-relative.

| claim | evidence |
|---|---|
| 2B bf16 anchor 12.346298 | `evidence/qwen2b/q1/ppl_2b_bf16.json` |
| 0.8B anchors 17.480045 / 22.432251 | `evidence/qwen2b/q1/ppl_08b_bf16.json`, `ppl_08b_w4g128.json` |
| V1 14.176885 · V2 13.744231 | `evidence/qwen2b/q2/v1_v2/ppl_v1.json`, `ppl_v2.json` |
| **the anchor, V1 and V2 re-scored on snoke** (§6.4) | `evidence/qwen2b/q1/ppl_2b_bf16_snoke.{json,log}`, `evidence/qwen2b/q2/v1_v2/ppl_v{1,2}_snoke.{json,log}`, launcher `run_snoke_recheck.sh` |
| the cross-host comparison itself (CROSSHOST_PASS) | `evidence/qwen2b/q2/v1_v2/crosshost_check.py` → `crosshost_check.log` |
| V3 13.391781 (+ snoke re-proof, + rerun) | `evidence/qwen2b/q2/v3/ppl_v3.json`, `ppl_v3_snoke.json`, `ppl_v3_rerun.json` |
| V4gptq 12.941240 (+ bit-identical rerun) | `evidence/qwen2b/q2/v4/ppl_v4gptq.json`, `ppl_v4gptq_rerun.json` |
| V4h (diagonal only) 13.216183, V3 re-scored 13.391842 | `evidence/qwen2b/q2/v4/ppl_v4h.json`, `ppl_v3_recal.json` |
| V4mix top-1/2/3 13.275505 / 12.975961 / 12.720237 | `evidence/qwen2b/q2/v4_v5/ppl_v4mix_top{1,2,3}.json` |
| **V4gptq + gate_up W8 12.736774** (+ rerun) | `evidence/qwen2b/q2/v4_v5/ppl_v4mix_gptq_top1.json`, `…_rerun.json` |
| **V5 12.360678** (+ bit-identical rerun) | `evidence/qwen2b/q2/v4_v5/ppl_v5.json`, `ppl_v5_rerun.json` |
| ΔPPL, % of gap, MB per PPL point, DDR fit, step decomposition, tok/s bands | `evidence/qwen2b/q2/v4_v5/v4_v5_table.py` → `v4_v5_table.txt` |
| bytes/token, packed footprints, embedding table sizes | `ref/scripts/bytes_per_token.py` → `evidence/qwen2b/q2/v4_v5/bytes_table_2b.log`, `bytes_table_08b.log`; selftest `bytes_selftest.log` |
| fixed-point top-1 / rank / clips, S=4 and S=8 | `evidence/qwen2b/q2/v1_v2/fixed_g{128,64}_S{4,8}.json`, `evidence/qwen2b/q2/v3/fixed_v3_g64_S{4,8}.json`, `evidence/qwen2b/q2/v4/fixed_v4gptq_g64_S4.json` |
| McNemar p-values, rank aggregates | `evidence/qwen2b/q2/v4/fixed_significance.py` → `fixed_significance.log` |
| ablation ladder, weight-vs-datapath decomposition, V6 verdict, res_scale sweep | `evidence/qwen2b/q2/v1_v2/DECOMP.md` (+ `ablate_2b.log`) |
| per-class sensitivity, rho / permutation p, V4 map selection | `evidence/qwen2b/q2/sensitivity/SENSITIVITY.md`, `rank_sensitivity.txt`, `scan_*.json` |
| GPTQ construction, calibration, per-matrix output error, emitter wiring, concerns | `evidence/qwen2b/q2/v4/GPTQ.md` (+ `matrix_error_check.log`, `calib_identity_check.log`, `emitter_wiring_check.log`) |
| W8 format, SHAPE bit, engine widths, host delta, per-channel repack | `evidence/qwen2b/q2/v4_v5/W8_SKETCH.md`, `selftest_w4a8_w8.log` |
| V5/V4mix headline, DDR-fit reasoning, frontier, rerun stamps | `evidence/qwen2b/q2/v4_v5/V4_V5.md`, `rerun_identical.log` |
| mover per-row law, `r` bracket, 2B projection, 31.50 ms/token correction | `evidence/qwen2b/ra/MOVER_NORM.md` |
| range audit at 2B + 0.8B control, gate ports, dead rows, 15 %-bound list | `ref/audit_ranges_2b_report.md` §6, `evidence/qwen2b/q2/audit/*` |
| host fault: trips, census, SIGSEGV, cross-host closure | `evidence/qwen2b/q2/v3/V3.md` §6 (+ `fixed_v3_g64_S4_dp_*.log`, `guarded_matvec_wrapper.py`, `calib_crosshost_check.log`), `evidence/qwen2b/q2/v1_v2/DECOMP.md` §3.1, `evidence/qwen2b/rb/SIM_GATE.md` |
| RTL status: widened RTL, 17/17 sim gates, bit-exact 0.8B replay | `evidence/qwen2b/rb/SIM_GATE.md` |
| **timing: the −0.025 waiver + its re-affirmation, campaign, utilization, SLR mirror** | `evidence/qwen2b/rb/TIMING.md` — **§5 is authoritative for the shipped netlist** (§2 describes the base/Explore rolls and must not be quoted as a property of what ships); waiver and both prompts in §6 |
| **the 50 failing endpoints, enumerated** | `evidence/qwen2b/rb/shipped_roll_endpoint_census.log` (script `synth/scripts/census_034_shipped.tcl`); class-B split `shipped_classB_path_excerpt.rpt` |
| 0.8B measured 30.4 tok/s, WNS +0.009, resident build utilization | `evidence/rung4/RUNG4_GATE.md`, `docs/ARCHITECTURE.md:15`, `evidence/qwen2b/ra/util_resident.md` |
| 0.8B production fixed-point 16/24, step-0 rank artifact | `evidence/stage5/fidelity_mq15_prod.log` |
| golden 2B reference texts, checkpoint verification | `evidence/qwen2b/q0/golden_2b.md`, `checkpoint_verify.md` |

## 9. Open items gate D should see

1. **The design ships under a timing waiver, not a clean closure, and the
   violations are in our own logic** (§1.1) — 50 endpoints, **100 % custom
   RTL**, including 18 inside the migrated `layer_0/dn_step`. The user
   re-affirmed the waiver on those corrected facts. R9 should target the three
   classes named in §1.1: **channel-2 vs ch0/1/3 asymmetry**, `dn_step` and
   top-k, and sequencer **MOV addressing**. It costs the four W4 rows nothing
   further — they run RTL that is already built — but **any W8 variant re-opens
   timing inside `matvec_engine`, the block that already owns the worst 22
   endpoints (24 of 50)**, on a design with no margin and no floorplanning (the design has
   no pblocks at all).
   > *2026-08-16 — R9 ran and all three named classes came back clean on
   > silicon (§7 addendum, `evidence/qwen2b/rb/RB_GATE.md`). The waiver still
   > stands and is **not** retired: one board, one temperature, one voltage,
   > and the W8 re-opening of `matvec_engine` timing is unchanged.*
2. **No calibrated 2B DDR image has been emitted** (V3 or V4gptq). The
   generator is wired and all 187 lookups resolve, but the end-to-end emit is
   an R-c work item and a prerequisite for shipping *any* calibrated variant.
3. **`audit_ranges` cannot score a calibrated image** and its Frobenius column
   would mis-rank error-feedback quantizers by design (§6.3.4). Two named
   closing actions there.
4. **The four W8-bearing rows have no fixed-point or text score** (§1 note 1),
   because no W8 FxRunner path exists. Fund it only with the RTL.
5. **The per-channel repack** (§5) is a host/emitter prerequisite for V5 and
   for any mixed map above top-1, and it is not built.
6. **The 17.4 ms layer term is unverified**, and it dominates the absolute
   tok/s column. The relative penalties are bracketed and robust.
   **Closing action: the R9 cycle census measures it directly** — no modelling
   change is needed, only the run that has not happened yet (item 9).
   > *2026-08-16 — CLOSED. That run happened. build_034 measures the 0.8B
   > layer bucket at **15.368 ms/token** against the **14.13** this document's
   > 17.4 ms is scaled from: re-anchor the 2B layer input upward. Every variant
   > moves equally (the layer term is quantization-independent) — **no ranking
   > changes**. §7 addendum, `RB_GATE.md` follow-on 3.*
7. **The anchor, V1 and V2 are now cross-host clean** (§6.4, CROSSHOST_PASS at
   1e-9..1e-8 relative). What remains is the **Task 7 sensitivity scan**, still
   darthplagueis-only — not load-bearing for any table row, ~26 min of snoke
   time to close if the ranking itself is ever wanted re-proven. Note V1's
   printed sixth decimal differs between hosts on a rounding boundary (§6.4).
8. **The 2B record mix behind the mover model is derived, not emitted.**
   Re-run the census against the first real 2B 4-chan stream now that R-b has
   unblocked the emitter.
9. **R9 has not run — the widened bitstream has never been exercised on the
   board.** Everything in Panel B's tok/s column is *modelled*, and the timing
   verdict of §1.1 is accepted **on the report**, not validated on silicon. The
   only measured hardware number anywhere in this document is the 0.8B
   reference row. R9 is what turns the model into a measurement, checks the
   three violating classes of §1.1, and closes item 6.
   > *2026-08-16 — SUPERSEDED. R9 ran and **PASSED first try**: board resident
   > on build_034 (`4f908df2`), full 0.8B ladder reproduced bit-exact, all
   > three violating classes clean, and the layer term measured at 15.368
   > ms/token (which closes item 6, above). Panel B's tok/s column is still
   > *modelled* for 2B — no 2B image has been emitted (item 2) — but its 0.8B
   > anchor and its layer input are now silicon measurements. §7 addendum,
   > `evidence/qwen2b/rb/RB_GATE.md`.*
