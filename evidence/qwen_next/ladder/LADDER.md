# Track L — the Qwen3.5-4B / 9B quality ladder

**The gate document.** Purpose, from the track brief: retire the W8-vs-W4
question at the two new geometries **before any RTL is written**, and give the
D1 target decision its quality axis. Everything here is host/`ref/` work — no
`rtl/`, no `sw/`, no board, and `ref/seq_chat.py` untouched (Track F owns it).

Gate 0 — the checkpoints themselves — is `CHECKPOINT_VERIFY.md`: **PASSED at
both targets with zero deviations** from the feasibility study's §1 census.

---

## 0. THE ANSWER, in four lines

1. **W8 is not needed — at 9B on BOTH axes, at 4B on the float axis only.**
   Say it that way and nothing has to be walked back later. On the **float
   ladder**, at both sizes, W8 buys 0.72–0.84 PPL over the shipped W4 for
   **2,505 MB per PPL point at 4B and 5,536 MB per PPL point at 9B**, and at
   both sizes a **free** quantizer gets two thirds of the way there. On the
   **shipped fixed-point datapath** — the machine that would actually be
   built — W8 over `W4 g128 + GPTQ` is worth **one token in 108** (96 vs 95
   top-1, §4). That second measurement is the stronger one and it was taken
   last, **but it exists at 9B only**: 4B has no fixed-point number at all
   (§4, §6.2), so its half of this line rests on the float axis alone.
2. **GPTQ at the SHIPPED group size costs the board nothing and gets almost
   all of it**: `W4 g128 + GPTQ` is **+2.81 % at 4B and +2.58 % at 9B** with
   the identical wire format, the identical b/w and the identical bytes/token
   as the shipped W4 — **0 MB per PPL point**. At 4B it even *beats* g64+GPTQ
   (2.81 vs 2.92 %); at 9B g64+GPTQ edges ahead (2.23 vs 2.58 %), i.e. **the
   group-size ordering flips between the two targets** and g64's 0.35 pp costs
   124 MB/token plus the §2.5 `matvec_engine` item. On value, g128+GPTQ wins
   at both.
3. **W4 damage stops improving with model size after 4B.** g128 is +14.83 % at
   2B, **+8.52 % at 4B, +8.79 % at 9B**. §5's hoped-for monotonic improvement
   holds once and then stops. Only the *calibrated* column keeps falling.
4. **The binding constraint at 9B is not the weight format — it is the int16
   residual rail**, which saturates at H=4096 with no rescale applied at all.
   That is an RTL container decision and the float ladder cannot see it. It is
   also **not the only mandatory 9B RTL line**: `rtl/vecnorm_unit.sv` is built
   for a maximum of N=2048 and `$fatal`s at `cfg_nlog2 ≥ 12`, so H=4096 needs
   its widths bumped too (feasibility §2.3 owns and prices that one). §4 carries
   the full list.

---

## 1. Method — what was held fixed

| | value | why it matters |
|---|---|---|
| corpus | `ref/ppl_corpus_eval.txt`, sha256 `6bf4f867…` | **gated, not merely recorded** — see the note below |
| scored positions | **24,528** at 4B and at 9B | *identical to the 2B study's* — **directly measured at every point**, not inferred. See the tokenizer note below for what is and is not byte-identical |
| window / batch | 512 / 4 | the 2B study's |
| anchor | no `--inject`, `res_scale 1.0` | pure bf16; `check_res_scale` rejects a residual rescale without `emb16` |
| every variant | `all:<quant>,dn_conv:cw13,emb:emb16` at `--res-scale 8` | **byte-for-byte the 2B study's variant spec**, so each cross-study delta is single-variable |
| threads | **6, pinned, every point, both geometries** | the **feasibility study** (`docs/QWEN35_NEXT_FEASIBILITY.md`, its own note on the five priced points) flags that its own priced five ran at **6/6/6/10/8** and are therefore "a real elapsed cost on this machine but not a controlled per-point comparison". Pinning removes that confound here. *(An earlier draft of this row attributed the figure to a "§6.5 hygiene note" in the 2B study; it is the feasibility study's caveat, and it is a caveat rather than an instruction.)* |
| host | snoke only | all compute; every json carries `host`, `torch` and `threads` |

**The corpus note — what "pinned" now means.** For most of this campaign the
corpus sha256 was **computed and recorded into every json, and never checked
against anything**. "Verified before use" described a gate that did not exist:
nothing would have stopped a run scoring a different file and reporting its
sha quite honestly. Fixed 2026-08-26, mechanized rather than reworded —
`ref/perplexity_eval.py` gained `--expect-corpus-sha256`, which hashes the
corpus **before tokenizing** and refuses with the expected-vs-actual pair on
mismatch, and `run_ppl_point.sh` passes the pinned
`6bf4f8677a3b3fff178c6915e2a55b7326e534f6e54650067e33b056e4c27876`. Verified
in both directions, including the realistic failure of accidentally passing
`ref/ppl_corpus_calib.txt` (refused, `522afbca…` ≠ `6bf4f867…`). **The numbers
in this document predate the gate**; what carries them is the recorded sha in
each json, now cross-checked by `ladder_table.py` (§below), and the gate
protects everything from here on.

**The tokenizer note — the earlier claim was too broad.** What is byte-identical
across all four models is the part that does the **tokenizing**:
`tokenizer.json` (`5f9e4d49…`), `vocab.json` (`ce99b4cb…`) and `merges.txt`
(`a9d356d7…`). Two files **DIFFER**, 0.8B/2B against 4B/9B:
`chat_template.jinja` and `tokenizer_config.json` — exactly the split
feasibility §1.4 predicts, and `CHECKPOINT_VERIFY.md` §7 has always had it
right. Neither differing file is used by this offline scoring path. And the
claim does not actually rest on the file hashes: **24,528 scored positions is
measured directly at every point** and asserted equal across all three
campaigns by `ladder_table.py`, so the cross-study comparison is grounded in a
measurement, not in an inference from a hash.

**The torch golden cache** (`ref/fidelity_check.py --golden`, the trajectory
every §4 number is teacher-forced against) is gitignored as regenerable, and
`.gitignore:39` promises its sha256 is recorded here. It is:
`golden_bf16_9b.npz` = **`4fd0616bae5086b8e449901740355a9f192b33ae1c9d18eafc160c0987408fd3`**
(89,440 bytes). Rebuild with `run_fidelity.sh 9b golden`. There is no 4B
golden — §4 refuses before one would be built.

The `dn_conv:cw13, emb:emb16` tail is carried by every variant row and not by
the anchor, exactly as at 2B — so every Δ against the anchor includes that
increment. At 2B it was **measured** at −0.000299 PPL (a slight *improvement*,
`evidence/qwen2b/q2/v1_v2/DECOMP.md` Table A); it is far below anything that moves a ranking here.

`ref/perplexity_eval.py` measures **weight damage only** — production
quantizers dequantized back into the float model. The shipped fixed-point
datapath is a separate axis, scored by `ref/fidelity_check.py` (§4).

**Scope: the text tower plus the LM head.** The vision tower and the MTP head
are present in both checkpoints, filtered out by the loader's
`model.language_model.` prefix exactly as at 2B, and shipped-unused.

Every number below is re-derived by `ladder_table.py`, which **asserts**
provenance before printing anything, and its output is committed as
`ladder_table.txt` — the tables here are that output. What it asserts, stated
exactly, because an earlier version of this paragraph credited it with more
than it did:

* **per-geometry rows** (`rows_for`): every variant shares its own anchor's
  corpus sha, checkpoint header sha, scored positions, window, batch, token
  count and model tag, and its `inject_resolved` is the map the byte column is
  computed from.
* **the cross-study rows** (`cross_study`) — **added 2026-08-26; this function
  had no asserts at all** while this paragraph claimed otherwise. It now
  requires every 2B json to carry the anchor's corpus sha and position count,
  to be `model_tag == "2b"`, and — the assert that matters — requires the 4B
  and 9B anchors to have scored **that same corpus over that same number of
  positions**. That is the §3 claim, mechanized.
* **the fidelity rows** (`summary_line`) — also added 2026-08-26: each row's
  `(top1_ok, top1_tot, rank_max, resid_max, clips, s_sat)` derived from the
  json is checked against `fidelity_check.py`'s **own** SUMMARY line in the
  matching `.log`, an independent rendering of the same run. A missing log
  prints a loud `UNCROSSCHECKED` note rather than passing quietly. This exists
  because the script *did* disagree with its own logs (§6.11).

---

## 2. THE DECISION TABLE

### 4B — Qwen3.5-4B (H=2560, 32 layers, anchor PPL 9.709056)

| point | PPL | ΔPPL | Δ % | % of the g128 gap LEFT | bytes/token | b/w | build+eval s |
|---|---|---|---|---|---|---|---|
| bf16 anchor | 9.709056 | — | — | 0 % | — | — | 1,441.8 |
| W4 g128 (shipped) | 10.535895 | +0.826839 | **+8.52 %** | 100 % | 2,201,223,168 | 4.188 | 2,991.9 |
| W4 g64 | 10.348569 | +0.639513 | +6.59 % | 77.34 % | 2,294,808,576 | 4.366 | 3,271.9 |
| **W4 g128 + GPTQ** | **9.981818** | **+0.272763** | **+2.81 %** | **32.99 %** | **2,201,223,168** | **4.188** | 7,034.6 |
| W4 g64 + GPTQ | 9.992644 | +0.283589 | +2.92 % | 34.30 % | 2,294,808,576 | 4.366 | 6,215.7 |
| W8 g128 | 9.696694 | **−0.012361** | **−0.13 %** | −1.50 % | 4,303,618,048 | 8.188 | 1,517.9 |

### 9B — Qwen3.5-9B (H=4096, 32 layers, untied head, anchor PPL 8.218339)

| point | PPL | ΔPPL | Δ % | % of the g128 gap LEFT | bytes/token | b/w | build+eval s |
|---|---|---|---|---|---|---|---|
| bf16 anchor | 8.218339 | — | — | 0 % | — | — | 1,688.8 |
| W4 g128 (shipped) | 8.940587 | +0.722248 | **+8.79 %** | 100 % | 4,091,805,696 | 4.125 | 4,588.2 |
| W4 g64 | 8.826826 | +0.608487 | +7.40 % | 84.25 % | 4,215,799,808 | 4.250 | 4,695.3 |
| **W4 g128 + GPTQ** | **8.430548** | **+0.212209** | **+2.58 %** | **29.38 %** | **4,091,805,696** | **4.125** | 13,492.6 |
| **W4 g64 + GPTQ** | **8.401256** | **+0.182917** | **+2.23 %** | **25.33 %** | 4,215,799,808 | 4.250 | 12,604.7 |
| W8 g128 | 8.223887 | +0.005548 | +0.07 % | 0.77 % | 8,059,617,280 | 8.125 | 2,149.2 |

**Byte caveat, stated once and meant everywhere:** these are BYTES computed by
the shipped `plan_weights` law, **not a fit**. No address map exists for either
geometry and the shipped weight window is 1,280 MiB per channel —
`docs/QWEN35_NEXT_FEASIBILITY.md` §3/§3.2 owns that question, and every row
above is far over it.

### What a PPL point costs in bytes (baseline = the shipped W4 g128)

| point | 4B: ΔPPL bought / extra bytes / **MB per point** | 9B: same |
|---|---|---|
| W4 g64 | +0.187 / 93,585,408 / 500 | +0.114 / 123,994,112 / 1,090 |
| **W4 g128 + GPTQ** | **+0.554 / 0 / 0 (free)** | **+0.510 / 0 / 0 (free)** |
| W4 g64 + GPTQ | +0.543 / 93,585,408 / 172 | +0.539 / 123,994,112 / 230 |
| W8 g128 | +0.839 / 2,102,394,880 / **2,505** | +0.717 / 3,967,811,584 / **5,536** |

---

## 3. Cross-study: the same points at 2B

Read the **Δ %** column across models, never ΔPPL — the anchors differ. What is
identical is the corpus, the window, the batch, the **tokenizing** files
(`tokenizer.json` / `vocab.json` / `merges.txt`) and the 24,528 scored
positions — the last of these **measured at every point and asserted equal
across all three campaigns**, not inferred. `chat_template.jinja` and
`tokenizer_config.json` do differ 0.8B/2B vs 4B/9B and are unused on this
offline path (§1, `CHECKPOINT_VERIFY.md` §7).

| point | 2B Δ % | **4B Δ %** | **9B Δ %** |
|---|---|---|---|
| W4 g128 (shipped) | +14.83 % | **+8.52 %** | **+8.79 %** |
| W4 g64 | +11.32 % | +6.59 % | +7.40 % |
| W4 g128 + GPTQ | — (new here) | **+2.81 %** | **+2.58 %** |
| W4 g64 + GPTQ | +4.82 % | +2.92 % | **+2.23 %** |
| W8 g128 | +0.12 % | **−0.13 %** | +0.07 % |

**Three readings.**

* **The "bigger models quantize better" expectation is only half true.** It
  holds 2B → 4B on every row. From 4B → 9B the *uncalibrated* W4 rows get
  slightly **worse** (g128 +8.52 → +8.79 %, g64 +6.59 → +7.40 %) while the
  calibrated row keeps improving (+2.92 → +2.23 %). §5 wrote "at 4B/9B W4
  should be *better* in relative terms"; that is confirmed against 2B and
  **falsified as a trend between the two new targets**.
* **W8's damage is small enough that its SIGN is not stable across sizes** —
  +0.12 % at 2B, **−0.13 % at 4B**, +0.07 % at 9B. At 4B it scores *better*
  than its own bf16 anchor.

  The defensible statement, and the one that survives review: W8 g128 is a
  **zero-centred perturbation** of the weights at this magnitude — it moves
  PPL by about a tenth of a percent in a direction that is not predictable
  from the model size — and a perturbation of that size **cannot move any
  ranking in this document**, because the next-nearest point on either ladder
  is 2.2–2.9 % away, i.e. ~20× larger. That is enough to retire the W8
  question and it is all these three numbers support.

  It is **not** evidence that W8 is lossless. Calling a −0.13 % result
  "lossless because it is inside the noise band spanned by the three
  measurements" is circular — the band is *made of* the three measurements,
  so any one of them is inside it by construction. This campaign ran **each
  point once** (§6.8) and therefore has **no measurement of run-to-run
  spread** at any point; the honest position is that these three deltas are
  small, not that they are zero. Establishing "lossless" would need repeat
  runs at one geometry, which were not done.
* **The GPTQ column is where the size scaling actually lives**, and it is the
  column that costs the board nothing.

---

## 4. The fidelity harness — the fixed-point datapath

`ref/fidelity_check.py`, the real quantizer and the real `layer_fixed`
datapath, teacher-forced on the torch golden: **27 steps × 4 committed prompts
= 108**, matching the 2B run on record (`evidence/qwen2b/rc/t4_11_fidelity_2b_w8.log`).
Free-run set to 12 tokens rather than 24 — that pass is a readability check,
not a scored metric, and 12 is the production setting in `fidelity_check`'s own
docstring; at 9B a step costs ~85 s, so 24 would add **~1.1–1.2 h per point**
for no extra scored number.

*That step cost was an **estimate** of ~120 s when the decision was made. Both
9B runs have since measured it, and the first correction of it — published in
commit `6d5dd82` — used the wrong denominator (156) and is itself corrected
here. A run executes **168** steps, not 156: 4 prompts × (4 prompt tokens +
24 − 1) = **108 teacher-forced** plus 4 × (4 + 12 − 1) = **60 free-running**.
So the true rates are **89.05 s/step at W8** (14,960.0 s / 168) and **81.13
s/step at W4+GPTQ** (13,630.5 s / 168), and the original ~120 s estimate was
**35–48 % high**, not the 25–37 % first claimed. The `--free-ntok 12` decision
stands on the measured numbers either way.*

### 4B: REFUSED, and the refusal is the measurement

```
REFUSING: FABLE5_MODEL=4b has H=2560, which is NOT a power of two.
```
(`fidelity_4b_REFUSED.log`, and the same refusal now guards
`layer_fixed.rmsnorm_fx` / `eps_norm_scale` themselves.)

`layer_fixed`'s normalizer folds 1/N into the rsqrt binary point **as a shift**,
mirroring `rtl/vecnorm_unit.sv:285,331-333`, where N exists only as
`cfg_nlog2`. There is no representation for N=2560. This is feasibility §2.3
(wall 2) — previously stated as an *RTL* wall — reaching the **host reference
model**: it is not a host patch, it is a reciprocal multiply in a unit on the
layer critical path.

**The precise claim, because the loose one is wrong.** It is *not* that 4B's
fixed-point number is unobtainable without an RTL decision — the pad-to-4096
route below needs no RTL at all. It is that **4B's fixed-point number does not
exist for any machine anyone has proposed.** Normalizing over 2048 or 4096 to
make the harness run would score a machine nobody has designed, so the harness
refuses **up front** rather than after half an hour of quantization.

*The zero-RTL alternative, offered unmeasured and unendorsed but now stated as
an available follow-up, because D1 may well want the number:* zero-pad the
residual to 4096 and fold `sqrt(2560/4096)` into the norm weights, with eps
scaled by 4096/2560 — algebraically exact. It costs Q14 headroom in the norm
weights and **1.6× the vecnorm bandwidth**, and it is a different machine from
the one the 2B artifacts describe, which is why it is not scored here rather
than because it is impossible. **Price, at this campaign's measured rates:**
one point is a quantization pass plus 168 steps, i.e. **~4.2 h at W8 and ~7 h
at W4+GPTQ** by analogy with the 9B runs (4B's H is 0.63× 9B's, so the true
figure is lower — treat these as upper bounds). Nobody has costed the
Q14-headroom loss; that, not the runtime, is the reason to think before
running it.

### 9B W8 g128 — measured

| | 9B W8 (S=1) | 2B W8 (S=4), for reference |
|---|---|---|
| top-1 | **96/108** | 90/108 |
| rank median / max | 0 / **4** | 0 / 37 |
| top-5 overlap | 3.81 | 3.79 |
| \|residual\|max (rail 32768) | **32767** | 28342 |
| residual clips *(see window note)* | **30** / 168 steps | **0** / 216 steps |
| S_F saturation *(same windows)* | 4438 | 411 |

**The 9B model is better in fixed point than 2B was — and it gets there with
the residual container pinned at its rail.**

**Window note — the two clip counts are NOT over the same number of steps, and
the difference runs the safe way.** `top-1`, `rank` and `top-5` are scored on
the teacher-forced pass only: 4 prompts × (4 prompt tokens + 24 − 1) = **108
steps**, identical in both campaigns, so those rows are like-for-like. The
`residual clips` and `S_F saturation` counters run over **every** step the
harness executes, teacher-forced *and* free-running. This campaign used
`--free-ntok 12` → 4 × (27 + 15) = **168 steps**; the 2B run on record used
`--free-ntok 24` → 4 × (27 + 27) = **216 steps**. So **2B had 29 % MORE
opportunity to clip and still clipped zero times**, which makes the
9B-vs-2B contrast *understated* here rather than exaggerated. Per-step, the
gap is 0.179 clips/step at 9B against 0.000 at 2B.

### The res_scale finding (`fidelity_9b_w8_SMOKE*.log`)

Six teacher-forced steps per setting, W8, same prompt:

| S | top-1 | \|x\|max | residual clips |
|---|---|---|---|
| **4** — the 2B RULED default | 4/6 | 32768 (rail) | **84** |
| 2 | 6/6 | 32768 (rail) | 22 |
| **1** — no rescale at all | **6/6** | 32767 | **1** |

At 2B, S=4 was clip-free across **all 216 steps** the 2B run executes, at
|x|max 28342. At H=4096 the **raw** residual reaches the Q7.8 rail with no
rescale applied, so **no power-of-two res_scale removes the clipping** — the
full S=1 run still clips **30 times over its 168 steps**. (Both counters run
over teacher-forced *and* free-running steps; see the window note above. An
earlier draft of this paragraph said "204 steps" for 2B and "108-step" for 9B —
both wrong, and in opposite directions.) The 2B campaign re-ruled S=8 → S=4
going 0.8B → 2B; the pattern does not simply continue, because at 9B the knob
has run out. Fixing it is a **container** decision — a wider residual or a
per-layer rescale — i.e. RTL, and the float PPL ladder is blind to it. Every 9B
fixed-point number here is at **S=1** and carries this caveat.

**The 9B mandatory-RTL list, and it is longer than the residual rail alone.**
Anything that scores 9B on the real datapath needs *both* of these, and this
document previously named only the first:

1. **The residual container** — above. A wider residual or a per-layer
   rescale. Measured here; unpriced.
2. **`rtl/vecnorm_unit.sv` must widen for N=4096** — H=4096 needs
   `cfg_nlog2 = 12`, and the unit is built for a maximum of 2048:
    `ec08638:rtl/vecnorm_unit.sv:159`
   `logic [11:0] cnt, n_total;` is commented *"12 bits: n_total = 2048 must
   FIT"*, and `ec08638:rtl/vecnorm_unit.sv:424-426` `$fatal`s outright on
    `cfg_nlog2 >= 12` with
   *"unsupported (max 11, N=2048)"*. Every width R-b set for N=2048 moves up
   one. This is **not** a Track L finding — feasibility §2.3 owns it and
   prices it in its §2.3 (`docs/QWEN35_NEXT_FEASIBILITY.md`) — but a 9B gate
    list that omits it is incomplete, and
   the host reference model cannot see it because `layer_fixed` mirrors the
   *shift*, not the width.

Note the asymmetry with 4B: 4B dies at wall 2 because **2560 is not a power of
two at all**; 9B passes that test and then hits a **width** limit, which is a
strictly smaller problem — a parameter bump, not a new arithmetic unit.

### 9B best-W4 (`w4g128gptq`) — measured, and it is the most important row here

Same S=1, same golden trajectory, same 108 teacher-forced steps.

| | 9B **W4 g128 + GPTQ** (S=1) | 9B W8 (S=1) | 2B W8 (S=4) |
|---|---|---|---|
| top-1 | **95/108** | 96/108 | 90/108 |
| rank median / max | 0 / 5 | 0 / 4 | 0 / 37 |
| top-5 overlap | 3.69 | 3.81 | 3.79 |
| \|residual\|max (rail 32768) | 32767 | 32767 | 28342 |
| residual clips *(window note above)* | **23** / 168 | 30 / 168 | 0 / 216 |
| S_F saturation *(same windows)* | 4392 | 4438 | 411 |

The two 9B columns share the same 168-step window, so **23 vs 30 is
like-for-like**; only the 2B column is measured over a longer one.

**On the shipped fixed-point datapath, W8 buys ONE token in 108 over a W4 that
costs the same bytes.** The float ladder priced that same step at 2.51 pp of
PPL (+2.58 % → +0.07 %); the datapath prices it at **0.9 pp of top-1 — a
single token out of 108**.

What that does and does not support: a one-token difference on a 108-step
sample **cannot establish that the two formats are equivalent**, and no
repeat-run spread was measured here (§6.8), so "inside the noise" is not a
claim this campaign can make. What it does establish is a **bound**: whatever
W8 buys on this datapath, it is *at most* about a percent of top-1 on the
committed prompts — while costing 3,967,811,584 extra bytes per token. That
bound is what the recommendation needs, and it is what these two runs prove.
§0's recommendation was derived from the byte frontier alone; this row is an
independent axis reaching the same verdict, and it is the stronger of the two
arguments because it scores the machine that would actually be built.

Two second-order observations, neither load-bearing:
* **W4+GPTQ clips the residual *less* than W8 does** (23 vs 30). Not a paradox
  and not an argument for W4: rounding weights harder shrinks activations
  slightly, so the int16 rail is hit less often. It does mean the residual-rail
  problem below is **not** made worse by choosing the cheap format.
* The dominant int16-dequant clip site is the same at both points — the
  12288×4096 FFN matvec, 10,897 clips of 132 M at W4+GPTQ vs 11,240 at W8
  (0.008 %). It is a property of the geometry, not of the weight format.

---

## 5. Walls hit, and what they cost

All host/`ref/` only. Details and file:line in `CHECKPOINT_VERIFY.md` §9.

| wall | where | status |
|---|---|---|
| single-shard loader | `load_qwen35.find_checkpoint` | FIXED — multi-shard `SafeTensors` (4B 2, 9B 4) |
| untied LM head, and its **silent** config default | `load_qwen35`, `perplexity_eval`, `fidelity_check` | FIXED — `checkpoint_is_tied()` takes the tensor as ground truth and refuses any flag/file disagreement; the head and the embedding lookup are now separate everywhere |
| key heads == value heads (`LKD = LNH·LDK`) | `layer_ref`, `layer_fixed`, `fidelity_check.blockprobe`, `bytes_per_token` | FIXED — `LNKH`/`VREP`; value head *h* reads key head `h // VREP` |
| **H=2560 normalizer** | `layer_fixed.rmsnorm_fx` ← `rtl/vecnorm_unit.sv` | **NOT FIXABLE ON THE HOST** — §4 |
| no GPTQ at the shipped g128 cadence | `perplexity_eval`, `bytes_per_token` | ADDED (`w4g128gptq`), bit-rate identical to `w4g128` — **now asserted in both selftests, which was not true when this row first claimed it** (see below) |

**Regression**: 15 of 16 `ref/` selftest invocations exit 0 at 0.8b AND 2b. The
one failure — 2b `layer_fixed` `attn softmax+pv rel=3.288e-02` against a `3e-02`
bound — is **PRE-EXISTING on committed main**: a pristine `git archive HEAD ref`
tree reproduces the identical value (`head_baseline_layer_fixed_2b.log`).
Track L's diff is exonerated, but somebody owns that tolerance: it is a
0.8B-tuned bound that the 2B geometry overshoots by 9.6 %, and it has been
failing silently.

### 5b. What the review round found still exposed, and what was done (2026-08-26)

The head-geometry fix above stopped at three files. It did not cover the rest
of `ref/`, and **9B is the dangerous geometry** precisely because it is
well-behaved: H=4096 IS a power of two, so it sails past every guard that
stops 4B and lands in code that produces a wrong answer rather than an
exception.

| site | what it does at 4B/9B | what was done |
|---|---|---|
| `ref/gen_layer_script.py:~1010` — `for h in range(LR.LNH)` with `q_src = QKV + h*LR.LDK` | LNH=32 but the packed block is `[q:LKD][k:LKD][v:LVD]` with `LKD = LNKH*LDK` — so **every h ≥ 16 reads the K region as Q and V as K, silently** | **GUARDED.** New `require_supported_geometry()` refuses when `LNH != LNKH`, called from `dn_token` (which `sw/infer.py` and `ref/gen_chain_script.py` import directly) and from `main()` |
| `ref/gen_layer_script.py:~270` — `np.zeros((18, ...))`, `assert 0 <= dn_slot < 18` | 0.8B/2B are 18 DN + 6 attn, exactly the bank counts. **4B/9B are 24 DN + 8 attn** — both overflow | **GUARDED** by the same function, from `config["layer_types"]` |
| `ref/debug_torch_diff.py:~115` — `conv_n[:LKD].reshape(LR.LNH, LR.LDK)` | 2048 values into a 4096 view → raises a bare numpy `ValueError` mid-comparison, which reads like a model bug | **GUARDED** at import: refuses with the reason |

These are **refusals, not generalizations.** Making these files work at 4B/9B
is migration work and this track deliberately did not attempt it — the point
is that nobody can now score a silently-wrong 9B number through them.
**Verified inert where it must be**: refuses at 4B and 9B, passes at 0.8B and
2B, and `evidence/qwen2b/rc/t4_bytes_unmoved.sh` **still regenerates the 2B
artifact set byte-for-byte** with the guards in place (`regen_gates.log`) —
which is the real regression test, since a guard that perturbed the emitters
would move bytes.

Three further mechanizations landed in the same round, each replacing a claim
this document made with a check that enforces it:

* **`ref/perplexity_eval.py --expect-corpus-sha256`** — the pinned-corpus gate
  (§1). "Verified before use" had described a gate that did not exist.
* **`ref/scripts/bytes_per_token.py --selftest` sections E-pre / E-bis** — the
  quant tables are a deliberate DUPLICATE of `perplexity_eval`'s (so the byte
  tool need not import torch), the file's own `ref/scripts/bytes_per_token.py:28` contract claimed they were
  validated, and nothing checked them. **The duplication had already drifted
  once**: `w4g128gptq` landed in `perplexity_eval` at `7010157` and here only
  at `161ce2e`. E-pre now reads `perplexity_eval.py` **by AST** and asserts
  `_G_OF`, the matvec quant set and both Hessian points agree; E-bis asserts
  `w4g128gptq == w4g128` and `w4g64gptq == w4g64` **to the byte in all seven
  classes at all four geometries** — the "GPTQ is free" claim, mechanized.
* **`ladder_table.py cross_study()`** — see §1. It had no asserts at all.

Every one of these was confirmed with a **negative control** (perturb the
input, watch it refuse) rather than assumed to work:

| mechanization | negative control | result |
|---|---|---|
| `--expect-corpus-sha256` | pass `deadbeefdeadbeef`; and pass the *calib* corpus with the *eval* sha — the realistic slip | refuses both, printing expected vs actual |
| `bytes_per_token` E-pre | delete `w4g128gptq` from this file's `_G_OF` | `AssertionError: _G_OF has DRIFTED from perplexity_eval's`, both dicts printed |
| `cross_study()` asserts | perturb the 2B anchor's `corpus_sha256` in a shadow tree | refuses, naming the two shas — where before it printed the table silently |
| the geometry guards | run at 0.8b/2b (must pass) and 4b/9b (must refuse) | pass / pass / refuse / refuse |

**And the whole `ref/` selftest sweep was re-run with every one of this round's
edits in place** (`ref_selftests_reverify.log`): **13 of 14 invocations exit
0**, and the one failure is 2b `layer_fixed` `attn softmax+pv rel=3.288e-02`
— **bit-identical** to the pre-existing value above. Nothing this round
touched moved a number at 0.8B or 2B.

**One finding was recorded rather than fixed, on purpose.**
`ref/load_qwen35.py:~394` does `head = emb.copy()` when the head is tied, but
`SafeTensors.get` already returns a fresh writable copy — so this allocates a
**second** full float32 table: 0.95 GiB at 0.8B, **2.03 GB (1.89 GiB) at 2B**,
2.54 GB at 4B (9B is untied and pays nothing). It defeats the deliberate frees
at `ref/gen_model_script.py:525` and `ref/seq_chat.py:1375`, which set
`md["emb"] = None` to release the table while `md["head"]` quietly holds a
twin. These are shipped paths. The one-word fix (`head = emb`) is only safe if
no consumer mutates either array in place, and establishing that is an audit
of every `load_model` caller in `ref/`, `sw/` and `tb/scripts/` — migration
work this track does not own. Aliasing without the audit would trade a memory
cost for a silent correctness bug. Noted at the site with its price.

---

## 6. Honest caveats

1. **The float PPL ladder measures WEIGHT damage only.** Every headline in §2
   is `perplexity_eval`: production quantizers dequantized back into the float
   torch model. It says nothing about the shipped datapath — that is §4, and
   §4 exists at 9B only.
2. **4B has NO fixed-point number at all.** Not "not measured yet" — and the
   precise reason is **not** "not measurable without an RTL decision", which
   overstates it: §4's pad-to-4096 route needs no RTL. The accurate form is
   that **4B's fixed-point number does not exist for any machine anyone has
   proposed**, and this track declined to invent one. Any D1 comparison that
   puts 4B and 9B side by side on quality is comparing a full result against a
   partial one. If D1 wants the padded number, §4 prices the run.
3. **The 9B fixed-point numbers are at S=1 and still clip** — 30 times at W8,
   23 at W4+GPTQ. They are good numbers (96/108 and 95/108) but both were
   obtained with the residual container saturated at `|x|max 32767`. Treat them
   as upper bounds on what today's int16 Q7.8 residual delivers at H=4096, not
   as clean measurements. The W8-vs-W4 *comparison* is on firmer ground than
   either absolute, because both sides carry the same rail.
4. **The 9B fixed-point W4 point is `w4g128gptq`, NOT the 9B PPL-best W4.** By
   float PPL the best W4 at 9B is `w4g64gptq` (+2.23 % vs +2.58 %) — the group
   sizes rank the other way round at 9B than at 4B (§0.2). `w4g128gptq` was
   scored instead because it is the shipped wire cadence, the 4B winner, and
   the point the recommendation actually rests on; `w4g64` additionally costs
   124 MB/token and the §2.5 `matvec_engine` item. The consequence is a real
   gap: **nobody has measured whether g64+GPTQ's 0.35 pp of float PPL survives
   into the fixed-point datapath at 9B.** Repriced at this campaign's *measured*
   W4+GPTQ rates: load 42.6 + head 1,309.5 + layers 10,181 + 168 steps ×
   81.13 s = **~7.0 h** (`w4g64` packs more scale beats per row, so treat that
   as a lower bound). This track declined it. **What that costs the reader, put
   honestly:** the earlier phrasing said the run "cannot change the
   recommendation" — that is stronger than the evidence. What is supported is
   that it cannot change the *byte* argument (g64 costs 124 MB/token more at
   both sizes regardless of how it scores), and that at 9B the two points are
   0.35 pp apart on float PPL where the W8-vs-W4 step they would arbitrate is
   2.51 pp. A fixed-point surprise at g64 is not impossible; it is merely not
   the way the byte frontier is leaning.
5. **Every byte column is a BYTES result, not a fit.** No address map exists
   for either geometry; all rows are far over the 1,280 MiB/channel window.
   §3/§3.2 of the feasibility study owns that.
6. **No tok/s here.** The 2B study's `tok_s_band` carries 2B mover and layer
   constants; applying it to 4B/9B would be wrong. Throughput is §4 of the
   feasibility study.
7. **GPTQ is calibration-dependent by construction** (2B study §6.3). It
   compensates against 32,768 tokens of `ref/ppl_corpus_calib.txt` — the train
   slice — and is scored on a **disjoint** eval slice, so the gain is genuine
   generalization; but a deployment far from this corpus would see less. Same
   caveat as the 2B V4gptq row, now carrying more of the recommendation.
8. **Each point ran once.** The 2B study re-ran its headline points in a second
   process to establish bit-identity. This campaign did not: with thread counts
   pinned at 6 the known 1e-8-relative cross-run band applies, and no ranking
   here is anywhere near that tight. Reruns are ~20-45 min each if wanted.
9. **The 2B rows are quoted, not re-measured**, from the committed jsons of
   `docs/QWEN2B_QUANT_STUDY.md`, preferring the snoke twins.
10. **THREE evidence-hygiene incidents, recorded rather than hidden**, each
   pointed at the artifact that actually records it. (The first version of this
   list said "two" and pointed both at `ref_selftests.log`; only (b) is in that
   file.)
   * **(a) Duplicate launch.** Two processes briefly wrote the same
     `ppl_9b_w4g128gptq` json/log. Both were killed (`kill -9`) and **the
     artifacts were deleted before any number was read**; the point was re-run
     clean, and the committed json is from that clean run. **There is no log of
     this incident, and there cannot be** — deleting the contaminated artifacts
     unread was the correct response and it destroyed the only record. **This
     paragraph is that record.** The committed `ppl_9b_w4g128gptq.log` carries
     a single host stamp and a single `rc`, which is what a clean single run
     looks like.
   * **(b) Stale NFS file handle.** `run_ref_selftests.sh` was edited on NFS
     while bash was still reading it, so the script died after its last section
     and the two `gptq --selftest` invocations were re-run separately.
     Recorded in **`ref_selftests.log:541`**.
   * **(c) A false "16 of 16" claim, corrected.** An early summary line
     asserted all 16 `ref/` selftest invocations exited 0; it had been written
     before an `exit 1` was noticed. Corrected to **15 of 16** with the failing
     invocation named, and the failure then proven **pre-existing on committed
     main** (§5). Recorded in **`ref_selftests.log:515`** and in the Track L
     ledger entry.
11. **This track shipped a defect in its own derivation script, and it is
   listed here rather than only in a commit message.** `ladder_table.py`
   aggregated the `s_sat` saturation **count** with `max()` across prompts
   instead of `sum()`, so it printed `S_F sat 1205` where its own source log
   said `4438`. Found at the end of the campaign, not by a test. The fix added
   `summary_line()`, which now cross-checks every fidelity row against
   `fidelity_check.py`'s independently-written SUMMARY line — but the general
   lesson stands: **the derivation script was trusted for most of this campaign
   without anything checking it against the logs it derives from.** A second
   instance was found in the same review and fixed the same way (`cross_study()`
   had *no* provenance asserts at all while §1 credited it with them).

---

## 7. Cost, against the priced plan

**Like for like first, because the headline "1.4× over" was not fair to the
estimate.** §5 priced a **5**-point ladder, and its five are the 2B campaign's
five: bf16, V1 `w4g128`, V2 `w4g64`, **V4gptq = `w4g64gptq`**, V5 `w8g128`.
This campaign ran **six** — `w4g128gptq` is a point this track ADDED because
the shipped group size had never been scored with GPTQ, and it is the point the
recommendation turned out to rest on. Comparing six against a price for five is
not a miss by the estimate.

| | §5 predicted (5 points) | actual, THE SAME 5 | with the added 6th |
|---|---|---|---|
| 4B ladder | 3.61 h | **4.29 h** (15,439.2 s) — **1.19×** | 6.24 h (22,473.8 s) |
| 9B ladder | 7.68 h | **7.15 h** (25,726.2 s) — **0.93×** | 10.89 h (39,218.8 s) |

**So §5's 9B estimate was GOOD — it came in 7 % under — and its 4B estimate was
19 % light.** The visible "overrun" is almost entirely the sixth point
(`w4g128gptq`: 7,034.6 s at 4B, 13,492.6 s at 9B), which §5 never priced
because nobody had thought to run it.

| | §5 predicted | actual |
|---|---|---|
| GPTQ calibration pass | 9.0 min (4B) / 19.1 min (9B) | **28.21 min** (103.5 s load + 1,588.9 s pass) / **40.23 min** (183.5 + 2,230.1) — **3.13× / 2.11× over**, and it ran at **8 threads**, not the ladder's pinned 6. **Excluded from every ladder sum above**, because the npz is built once and amortized over two GPTQ points. |
| fixed-point points | **not priced at all** | **the single largest line item in this track**: 9B W8 **4.22 h** (load 30.4 + head 23.7 + config 15,128.2 s), 9B W4+GPTQ **6.99 h** (load 42.6 + head 1,309.5 + config 23,826.4 s). Anyone repeating this must budget the fidelity harness separately from the ladder — see §4 for the measured 89.05 / 81.13 s per step. |
| **CAMPAIGN TOTAL** | **11.29 h** (3.61 + 7.68) | **28.35 h** of process time (102,053.4 s) = **2.51× the decided price** — itemized: 4B ladder 6.24 + 9B ladder 10.89 + 9B fixed W8 4.22 + 9B fixed W4+GPTQ 6.99. Plus **1.14 h** of calibration on top, excluded from that total. The overrun is **not** a bad estimate; it is two whole axes §5 did not price (the added GPTQ-at-g128 point, and the entire fidelity harness). |
| GPTQ Hessian npz | 10.1 GiB (4B) / 21.4 GiB (9B) | **13.72 / 24.06 GiB** — bigger; one float32 K×K per input SITE, 129 sites, and the FFN sites are K=9216/12288 |
| disk pressure | "~21 GB headroom, one target at a time" | **not a constraint**: the npz lands on the 21 TB NFS pool (`r2d2:/tank12t/code`), only the checkpoints touch snoke's local 458 GB (94 → 67 GB free). Both targets fit comfortably at once. |

Everything ran on snoke, sharing the machine with Track P's Vivado jobs
throughout.

---

## 8. Where the evidence lives

All under `evidence/qwen_next/ladder/`:

| what | file |
|---|---|
| gate 0 — checkpoint verification | `CHECKPOINT_VERIFY.md`, `checkpoint_verify.py`, `checkpoint_verify_{4b,9b}.log` |
| the PPL points | `ppl_{4b,9b}_{bf16,w4g128,w4g64,w4g128gptq,w4g64gptq,w8g128}.{json,log}` |
| the table, and the script that asserts it | `ladder_table.py` → `ladder_table.txt` |
| fixed-point | `fixed_9b_*.{json,log}`, `fidelity_9b_w8_SMOKE*.log`, `fidelity_4b_REFUSED.log` |
| calibration | `calib_{4b,9b}.log` (npz gitignored; shas in the logs) |
| launchers | `fetch_checkpoints.sh`, `run_ppl_point.sh`, `run_calib.sh`, `run_fidelity.sh`, `run_ref_selftests.sh` |
| regression | `ref_selftests.log` (the campaign run — **and the incident record §6.10 cites by line**), `ref_selftests_reverify.log` (the 2026-08-26 re-run with every review-round edit in place, 13/14, same pre-existing failure), `head_baseline_layer_fixed_2b.log` |
| **regen gates** (2026-08-26) | `regen_gates.log` — `evidence/qwen2b/rc/t4_bytes_unmoved.sh` **PASS** (the 2B artifact set regenerates byte-for-byte *with* the new `ref/` geometry guards in place, which is what proves them inert) and `evidence/qwen2b/rd/rd_golden_shas.sh` **rc 0** |
| the torch golden (gitignored) | `golden_bf16_9b.npz`, sha256 `4fd0616bae5086b8…` — recorded in §1 per `.gitignore:39` |

**Not here, and deliberately:** there is no `fixed_4b_*` (§4 refuses), no
`golden_bf16_4b.npz` (never built, for the same reason), and no
`fixed_9b_w4g64gptq` (§6.4 declines it at ~7.0 h and states what that costs
the reader). The Hessian npzs are gitignored as regenerable; their sha256s are
in `calib_{4b,9b}.log`.

---

## SUPERSEDED, dated note 2026-09-10 (pre-ship documentation chore)

Two statements above are **superseded by later measurement** and are kept
verbatim, because this document is Track L's committed evidence and both were
accurate against the tree they were written on.

1. **The "9.6 % geometry overshoot" in §5's regression paragraph is not a
   geometry effect at all.** The `attn softmax+pv rel=3.288e-02` failure
   against a `3e-02` bound was read here as a 0.8B-tuned tolerance that the 2B
   geometry overshoots. **G2's D-TOL gate measured it and the reading is
   wrong**: the block is IDENTICAL at all four geometries, and the two values
   are two draws of one random check, not two geometries. See
   `evidence/qwen9b/g2/D_TOL.md` §2. **Do not quote a per-geometry attention
   error bound from this paragraph** — there is no such bound, and
   `evidence/qwen_next/ladder/CHECKPOINT_VERIFY.md` carries the same framing
   and the same note.

2. **The vecnorm N=4096 wall in §"what a 9B score needs" item 2 is CLOSED.**
   G3.2 widened `rtl/vecnorm_unit.sv` to 4096: `cnt` / `n_total` are 13 bits
   now and the `$fatal` moved to `cfg_nlog2 >= 13`. The two citations in that
   item are pinned to `ec08638`, the pre-G3.2 tree they describe, so they
   still name what the paragraph says they name; the CURRENT state is in
   `evidence/qwen9b/g3/G3_2_VECNORM.md`.
