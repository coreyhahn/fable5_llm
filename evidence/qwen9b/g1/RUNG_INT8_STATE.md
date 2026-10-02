# G1 — the int8-DeltaNet-state fidelity rung

**Gate:** G1, the first executable gate of the Qwen3.5-9B migration and its one
**STOP-BACK** gate (`docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md`
§4.1, plan Task 1). Host only: no RTL, no board, no synthesis.

> ## VERDICT: **CLOSED — OPTION B RATIFIED. THE STATE SHIPS `int16`.**
>
> **User ruling, 2026-08-31.** Per-row's MARGINAL was offered and **declined**.
> The DeltaNet state stays the shipped **`int16` Q2.13** container at the
> measured **95 / 108** — **fidelity risk on this axis is zero**, because that
> is not a projection but the baseline this gate reproduced exactly. The cost
> moves from fidelity to **timing and floorplan, which are RTL-phase work**.
> **Full disposition in §13.**
>
> **Three waves tested every lever the plan named, and none of them beat
> `int16`:**
>
> | container | exponents | top-1 | rank max | top-5 | band |
> |---|---|---|---|---|---|
> | **`int16` — RATIFIED, SHIPS** | — | **95/108** | **5** | **3.69** | **the baseline** |
> | `int8:6` **global** (best of eight `k`) | 1 | 72/108 | 214 | 2.81 | **FAIL** |
> | `int8h` **per-head** | 768 | 83/108 | 211 | 2.95 | **FAIL** |
> | `int8e` **per-row (L1)** | 98,304 | 94/108 | 13 | 3.56 | **MARGINAL — declined** |
> | `int8e` per-row + `RS_F = 7` | 98,304 | 89/108 | 18 | 3.37 | **FAIL** |
>
> **Wave 1** found the global exponent fails at every `k`, and measured why: the
> state needs **9 bits of range above its own rms** and a shared-exponent int8
> has **7**. **Wave 2** found the granularity axis is real and monotone
> (72 → 83 → 94) and that per-row is URAM-free at 592, with the bit layout the
> spec had asserted and never stated. **Wave 3** tested the one remaining lever
> and refuted it: `RS_F = 7` removes the clipping but **costs 5 top-1 and
> worsens rank max**, so the ratified O5 rider is **not taken**.
>
> **`RS_F` = 8**, the shipped value — no host constant and no RTL literal moves
> (§13.3). **`RS_F = 7` under `int16` was never measured and is recorded as a
> cheap, available RTL-phase measurement (≈ 3.9 h, cache warm) — not run, not
> recommended** (§13.5).
>
> **ONE G1 FINDING SURVIVES THE RULING AND TRAVELS FORWARD UNPAID: the gate
> port.** `max A = 76.9957` against a port of `[0, 8)`; **60 of 768 DN heads
> have their decay changed by the production clamp**. It is a property of the
> checkpoint against the frozen ports, **not of the state container**, so option
> B does not dispose of it. Unpriced at scored resolution; ≈ 7 h to price
> (§13.4).
>
> **Every repeat run in all three waves is byte-identical** — observed
> run-to-run spread across the whole gate is **exactly zero**. **No RTL was
> written by this task.** The per-head and per-row laws remain in `ref/` as
> **measured but unshipped** evidence, inert unless explicitly selected (§13.6).

---

## 0. Provenance

| | |
|---|---|
| host | **snoke** (`nproc --all` = 48), every numeric command; `darthplagueis` stays out of numeric compute (plan Global Constraints) |
| thread pinning | `OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 OPENBLAS_NUM_THREADS=6`, `nice -n 10`, **fixed in the launcher** so it cannot drift between settings |
| interpreter | `uv run --no-project --with torch --with transformers --with numpy python -u` — the form the plan's standing hazard prescribes. Every log records the two candidate venvs as probed by `test -x` **on that host**: `/home/cah/.venv/bin/python` (exists on snoke), `ref/.venv/bin/python` (**ABSENT** on snoke — the dangling symlink the hazard names) |
| provenance wrapper | `evidence/qwen9b/run.sh` (created by this task), which refuses to overwrite an existing log |
| launchers | `evidence/qwen9b/g1/run_g1_smoke.sh`, `evidence/qwen9b/g1/run_g1_point.sh` |
| tree | each log carries `=== tree: <sha>[+dirty]`, and **the label moved under the runs**: of wave 1's eighteen 9B runs, 2 read `379475f+dirty`, **15 read `a971813+dirty`**, 1 reads `ab23466+dirty` — Task 2 was committing to `evidence/qwen9b/g2/` alongside, so `HEAD` advanced while this gate ran, and every run is `+dirty` because the two tasks share one working tree. **The tree label is therefore NOT the provenance handle for this gate; the quantizer-source digest is** (§1), and it is identical across all eighteen |
| checkpoint | `models--Qwen--Qwen3.5-9B` snapshot `c202236235762e1c871ad0ccb60c8ee5ba337b9a`, 4 shards, header sha256 **`2721100f724faea555e4afd11064461b2b231914be53e8d7468ed1be9d9f4c3b`** — identical to the golden's recorded header |
| golden | `evidence/qwen_next/ladder/golden_bf16_9b.npz`, **gitignored cache** (`.gitignore:39`), sha256 **`4fd0616bae5086b8e449901740355a9f192b33ae1c9d18eafc160c0987408fd3`** — **hash-verified before every run by the launchers** and matching `LADDER.md:88`. Not rebuilt: the hash held |
| Hessian | `ref/calib_stats_9b_h.npz`, gitignored, sha256 **`36689b5990c80e1208060b7864841a9387e19ea27e27ec09f0bfd4dd081dd7d4`** — hash-verified before every run, matching `evidence/qwen_next/ladder/calib_9b.log:47` |
| calibration corpus | `ref/ppl_corpus_calib.txt` sha256 `522afbcaa928956d92d35dfd93741a8c795f750e22edc4ef2e00ed0df8478f2d` (matches `evidence/qwen_next/ladder/calib_9b.log:6`), 32,768 tokens, 249 tensors |
| prompts | the four committed seeds `1,2,3,4` from `ref/gen_model_script.py:191-204`: *"The capital of France"*, *"Once upon a time"*, *"import numpy as np"*, *"Hello world! My"* |
| point | 9B, `w4g128gptq`, `S=1`, `--ntok 24 --free-ntok 12` → 108 teacher-forced + 60 free = 168 steps |

**Labels** (spec §0): **M** measured on this board, **D** computed by a committed
script that reproduces a committed number first, **T** toolchain-measured,
**E** extrapolated, **S** this document's own arithmetic.

---

## 1. What was built, and the RED→GREEN record

`FABLE5_DN_STATE` selects the DeltaNet state container, read **once at import**
of `ref/layer_fixed.py` exactly as `FABLE5_CALIB_MODE` is, so a process is one
law for its whole life:

| value | law |
|---|---|
| `int16` | the shipped Q2.13 container — **the default, and exactly `clip16`**, i.e. byte-identical to the shipped model |
| `int8:<k>` | **L0**, `S8 = sat8(rshr_round(S16, k))` → Q2.(13−k) |
| `int8t:<k>` | **L0 truncating**, `S8 = sat8(S16 >> k)` — the record-what-not-to-build point |
| `int8e` | **L1**, int8 mantissa + per-row power-of-two exponent |

`LF.dn_state_narrow(S16)` is the law, applied **after every state update** in
`deltanet_decode_fx`, and it returns the state in the same Q.S_F numbering it
was handed — the container's value re-expanded, not the raw code. Everything
downstream is untouched; what changes is only which values are representable.
`LF.dn_state_pack(S16)` returns the codes an int8 bank would actually hold, for
the selftest and for Task 10's RTL mirror. **This function is the law and the
RTL mirrors it, never the reverse.**

**RED then GREEN, as the plan requires:**

| | log | result |
|---|---|---|
| RED | `evidence/qwen9b/g1/00_red_dn_state_law.log` | `NameError: name 'DN_STATE_LAW' is not defined`, **rc 1** — the selftest was written and run before the law existed |
| GREEN | `evidence/qwen9b/g1/01_green_dn_state_law_0p8b.log` | rc 0, all four properties pass |

The four properties, each proved on a vector (`_dn_state_law()` in
`ref/layer_fixed.py`): **(a)** rounds to nearest rather than truncating, on a
vector whose truncated and rounded results differ; **(b)** saturates
symmetrically at ±127 rather than wrapping, at the int16 rail **and beyond it**;
**(c)** is exactly `clip16` under `int16`; **(d)** is idempotent — which is what
makes it legal to apply on every update.

```
  dn_state int16 : identity in range on 2048 elements, and int16's OWN rail beyond it OK
  dn_state int8:5 : round!=trunc OK  sat+/-127 OK  idempotent OK   [Q2.8: ceiling 0.4961, resolution 0.0039]
  dn_state int8:6 : round!=trunc OK  sat+/-127 OK  idempotent OK   [Q2.7: ceiling 0.9922, resolution 0.0078]
  dn_state int8:7 : round!=trunc OK  sat+/-127 OK  idempotent OK   [Q2.6: ceiling 1.9844, resolution 0.0156]
  dn_state int8:8 : round!=trunc OK  sat+/-127 OK  idempotent OK   [Q2.5: ceiling 3.9688, resolution 0.0312]
  dn_state int8:9 : round!=trunc OK  sat+/-127 OK  idempotent OK   [Q2.4: ceiling 7.9375, resolution 0.0625]
  dn_state int8:10 : round!=trunc OK  sat+/-127 OK  idempotent OK   [Q2.3: ceiling 15.8750, resolution 0.1250]
  dn_state int8e : idempotent + a 2^3 row rescale moves only the exponent + a quiet row keeps e=0 OK
```

**Two defects in the first cut of the law, both caught before any 9B number was
scored**, both recorded because the second one would have been invisible:

1. The law was first applied **after** `clip16`, which made every `k > 8` a
   **double rail** — `127 << 9 = 65024` is outside int16, so an `int8:9`
   container could never reach its own ceiling. Fixed by handing the law the
   unclipped accumulator and letting each container saturate at its own rail;
   under `int16` the law *is* `clip16`, so the shipped path is unchanged.
2. `new_cache_fx` stored the state as `int16` unconditionally, which would have
   **wrapped** those same `k ≥ 9` values on write. The dtype now follows the
   law; `int16` stays `int16`, so every shipped generator path is byte-identical.

Both mattered because the sweep is centred on the **measured** `|S|max` (§4) and
9B's turned out to want exactly that part of the range.

### Inertness at the two frozen geometries

One interpreter per tag (`model_select` freezes `FABLE5_MODEL` at import):

| tag | log | result |
|---|---|---|
| `0.8b` | `evidence/qwen9b/g1/05_ref_selftest_0p8b.log:70` | **`LAYER_FIXED SELFTEST PASS`** |
| `2b` | `evidence/qwen9b/g1/05_ref_selftest_2b.log:57` | `attn softmax+pv rel=3.288e-02 bound=3e-02 FAIL` **and only that** |

The 2b failure is bit-identical to the value on committed main
(`evidence/qwen_next/ladder/head_baseline_layer_fixed_2b.log`) and is the
pre-existing defect **Task 2 (D-TOL) owns**. No other check moved at either
geometry, which is this step's inertness condition.

**Dated, because the tree moved under this line after it was measured.** Those
two logs were taken at 18:04–18:08 with the bound still at `3e-2`. Task 2's
D-TOL ruling then changed that constant to `8e-2`, and — through the shared
working tree — **that hunk is inside this task's own commit `379475f`**
(`ref/layer_fixed.py:2615` now reads `ok &= _blk("attn softmax+pv", acc /
(1 << QKV_F), ref, 8e-2)`). So the 2b selftest **passes on the tree these
measurements ran on**; Task 2's `evidence/qwen9b/g2/head_08b_2b_layer_fixed.log`
is that run. The logs above are kept as taken, with this note, rather than
re-run to make the document tidier.

### M1 — the shared-file rule, discharged mechanically

Tasks 1 and 2 write `ref/layer_fixed.py` in one working tree, and the plan's M1
rule requires that this gate's measurements complete on a numeric path Task 2
has not moved. That is not asserted here, it is **shown**: every run prints the
sha256 of the `ref/` sources that define the quantizer, computed once at process
start. **Across both waves there are 25 9B runs and TWO digests, and the boundary between them is exactly the one edit wave §11.1 describes** — 19 runs at `0c6077f8…` (waves 0-1) and 6 at `04a4c9c6…` (wave 2, after the per-head/per-row implementation). **The two are proved to carry byte-identical weights** (§11.3), so the comparison spans both. Within wave 1, the eighteen runs print:

```
0c6077f82bf35ead85f427e9f11b2bc82ad33b3613219d9f5b3a42ba8cacd44c
```

— the eight `k` smokes, the `int8t` smoke, the `RS_F=7` smoke, the gate-port
diag smoke, the distribution probe, the granularity probe (§4a) and all four
168-step points: **seventeen at the verdict, eighteen with the one measurement
this fix round was authorized to add.** (The one different digest in this
directory, `61cb4812…`, belongs to
`evidence/qwen9b/g1/06_dryrun_0p8b_gateport.log`, a **0.8B** harness dry run,
not a 9B measurement.) **One source text, one comparison — and it holds across
three different `=== tree:` labels**, which is exactly why the digest is the
handle and the tree label is not.

Task 2's swept hunk is inside that text, and it **cannot** reach a measurement:
it is the bound argument of a `_blk` call inside `_selftest`, `_blk` is called
from nowhere else, and `ref/fidelity_check.py` never invokes `_selftest`. M1
held in substance. It held **by luck of ordering rather than by the rule**,
which is Task 2's own finding at
`.superpowers/sdd/2026-08-29-qwen35-9b-migration/progress.md:19` **(LOCAL-ONLY
— `.superpowers/sdd/.gitignore` ignores it, so that path is NOT in any commit
and a reader cloning this repo will not find it; the campaign's committed
record of the same finding is Task 2's `evidence/qwen9b/g2/D_TOL.md`)**: a file
pathspec is not a defence against a shared dirty worktree, it is the sweep
mechanism. The source-digest key above is the mechanical answer to that hazard
for anything that touches the quantizer — a moved source misses the cache
loudly instead of silently splitting one comparison across two numeric paths.

---

## 2. Step 1 — the cost item: the quantized weights are cached, and that is proved

Spec §4.1 "Cost" makes this G1's **first** task. A 9B W4+GPTQ point spends
**1,309.5 s** on the LM head and **10,180.9 s** on 32 layers before it takes a
single step (`evidence/qwen_next/ladder/fixed_9b_w4g128gptq.log:12`, `:15`) —
3.2 h per setting, for artifacts a decode-time state container cannot reach.

`ref/fidelity_check.py` gains `--wq-cache <dir>` and `--wq-cache-verify <layer>`.
The key contains everything the artifacts **do** depend on — model tag,
checkpoint header sha, `w8`, wire group, `mse_scale`, `tighten_e`, `res_scale`,
the Hessian path and its sha256, the calib mode — **plus a sha256 over the
`ref/` sources that define the quantizer**, memoized at process start so an
entry is labelled with the code that produced it. `FABLE5_DN_STATE` and
`FABLE5_RS_F` are deliberately **not** in the key: that is the claim under test.

**It is not left as a claim** (0.8B, `evidence/qwen9b/g1/03_dryrun_0p8b_int16.log` →
`evidence/qwen9b/g1/04_dryrun_0p8b_int8k6.log`):

| | first run (`int16`, cold) | second run (`int8:6`, warm) |
|---|---|---|
| LM head | quantized, **86.8 s** | **cache HIT, 0.2 s** |
| 24 layers | quantized, **134.4 s** | **cache HIT, 0.3 s** |
| config wall | **201.4 s** | **72.0 s** (incl. 5.6 s of verify) |
| whole run | 292 s | **75 s** |
| quantization passes | **1** | **0** |
| verify | — | **layer 2 re-quantized live under `FABLE5_DN_STATE=int8:6`: BYTE-IDENTICAL to the cache** |

The harness also **asserts** the entry count: with a cache on, the weight
quantization stage must be entered at most once per process, and the count is
printed in every log and carried in every json as `_wq`. The 9B runs below
report the same three facts (hit / 0 passes / verify byte-identical) at 9B
scale, which is what makes the k sweep single-variable.

**`--diag` and `--wq-cache` are refused together**, because `DIAGS` moves
`DT_Q12_MIN` / `DT_Q12_MAX` / `A_Q15_MAX` and `quant_deltanet` reads all three:
a diag run quantizes for itself rather than being served a cache that means
something else.

---

### The cost item, measured at 9B

The 9B cold run paid **1,232.9 s** (LM head) + **9,680.6 s** (32 layers) =
**3.03 h** and saved a **0.96 GiB** head and a **6.55 GiB** layer image.
**Fifteen later runs** — the eight `k` smokes, the `int8t` point, the `RS_F 7`
smoke, the distribution probe and all four 168-step points — reloaded them in
**5–7 s** each and reported **0 quantization passes**. That is **≈ 45 h of snoke
not spent**, and, more importantly, it is what makes every row below a
single-variable comparison: **all four full points print the same
`quantizer sources sha256 0c6077f82bf35ead85f427e9f11b2bc82ad33b3613219d9f5b3a42ba8cacd44c`
and the same two cache hits.**

The `--wq-cache-verify` proof, at 9B, on four different settings — each
re-quantizes one layer live and requires byte-equality with the cache:

| run | layer | setting | result | cost |
|---|---|---|---|---|
| `int8:9` smoke | 2 (`linear_attention`) | `FABLE5_DN_STATE=int8:9` | **BYTE-IDENTICAL** | 324.4 s |
| `int8:8` smoke | 2 (`linear_attention`) | `FABLE5_DN_STATE=int8:8` | **BYTE-IDENTICAL** | 310.5 s |
| `int16` probe | 3 (**`full_attention`**) | `FABLE5_DN_STATE=int16` | **BYTE-IDENTICAL** | 289.9 s |
| `RS_F 7` smoke | 2 (`linear_attention`) | `FABLE5_DN_STATE=int8:6`, **`RS_F=7`** | **BYTE-IDENTICAL** | 323.7 s |
| all four points | 2 | the four scored settings | **BYTE-IDENTICAL** | ~300 s each |

Both layer types are covered, and the `RS_F=7` row is the mechanical proof for
the second axis of the key: **neither the state law nor the residual binary
point reaches the quantizer.**

---

## 3. Step 3 — the 9B state range, measured before the sweep was chosen

The prior in the spec is the note at `ref/layer_fixed.py:51-52` — *"|S|max 0.76,
rms 0.009 → 74 LSB rms, range ±4"* — and that note is **0.8B on random weights**.
At 9B, `w4g128gptq`, `S=1` (`evidence/qwen9b/g1/smoke_9b_w4g128gptq_int16_rsf8.log`, six steps):

| quantity | value | | |
|---|---|---|---|
| `|S|max` (pre-narrowing accumulator) | **57,702 LSB** | = **7.0437** at Q2.13 | **M** |
| state writes | 75,497,472 | = 6 steps × 24 DN layers × 32 heads × 128×128 | **M** |
| int16 rail hits | 93 | in six steps | **M** |

**The int16 container is already over its own rail at 9B**: Q2.13 holds ±3.99988
and the accumulator reaches 7.04. That alone re-centres the sweep — the plan's
starting `k ∈ {5,6,7,8}` has ceilings 0.496 / 0.992 / 1.984 / 3.969, all below
the measured max — so the sweep was widened to **`k ∈ {3,4,5,6,7,8,9,10}`**,
ceilings 0.124 … 15.875, which brackets 7.04 from both sides with room to spare.

Then the measurement that actually explains the result, taken with `--dn-probe`
over the same six steps (`evidence/qwen9b/g1/smoke_9b_w4g128gptq_int16_rsf8_probe.log:28-29`):

```
DN state distribution over 75497472 pre-narrowing writes: rms 134.58 LSB (0.016429),
|S|max 57702 LSB (7.0437), 23.39% exactly zero,
dynamic range |S|max/rms = 428.7 -> 9 bits above the rms, before any headroom
log2|S| histogram (bucket i = |S| in [2^i, 2^(i+1)) LSB):
{0: 10584883, 1: 11897579, 2: 11232844, 3: 9192937, 4: 6641659, 5: 4192124,
 6: 2330373, 7: 1133057, 8: 414634, 9: 146841, 10: 48073, 11: 13901,
 12: 5222, 13: 2221, 14: 692, 15: 93}
```

**(S) The arithmetic this forces.** A shared-exponent int8 container has a
**7-bit magnitude field**: 127 codes between zero and its ceiling. The 9B state
needs **9 bits above its own rms** just to reach its maximum, and it is a state
that *accumulates*, so it also needs bits **below** the rms for the increments
not to vanish. 7 < 9, before any headroom at all. The histogram says the same
thing from the other end: **58.3 % of all non-zero writes are `|S| < 8 LSB`**
and the median write sits in bucket 1–2, i.e. **2–7 LSB** — while the container's
own LSB at the `k` that reaches the max (`k=9`) is **512 LSB**. That is not a
tuning problem, and no choice of `k` moves it: the sweep below is the
confirmation, not the discovery.

**(D) The derivation, because an earlier revision of this line said 43.8 % and
that number does not reproduce.** Bucket `i` counts `|S| ∈ [2^i, 2^(i+1))`, so
`|S| < 8` is buckets 0+1+2 = 10,584,883 + 11,897,579 + 11,232,844 =
**33,715,306**. The bucket sum is **57,837,133** non-zero writes, and
75,497,472 − 57,837,133 = 17,660,339 zeros = **23.39 %**, which closes against
the probe's own printed zero fraction. So `33,715,306 / 57,837,133` =
**58.3 % of non-zero writes**, and `33,715,306 / 75,497,472` = **44.7 % of all
writes**. The corrected figure is **worse than the one it replaces**, i.e. this
gate's own case was understated.

*(The probe run also reproduced the un-probed `int16` smoke exactly — 6/6, rank
max 0, top-5 2.83, `|x|max` 32767, 1 clip, `S_F` sat 93, `|S|max` 57702 — which
is both a free repeat and the proof that the probe wrapper is inert.)*

---

## 4. Step 3 — the `k` sweep, all of it

Six teacher-forced steps, prompt 1, 9B `w4g128gptq`, `S=1`, `RS_F=8`, one
process per law. **Saturation is reported beside top-1**, as the plan requires,
because a `k` that wins on top-1 while saturating hard is the fragile answer.

| law | ceiling | resolution | top-1 | rank med | rank max | top-5 | **S8 rail** | `S_F` rail | `|S|max` |
|---|---|---|---|---|---|---|---|---|---|
| **`int16`** (reference) | 3.99988 | 0.000122 | **6/6** | 0.0 | **0** | **2.83** | 0 | 93 | 57,702 |
| `int8:3` | 0.124 | 0.00098 | 4/6 | 0.0 | 115 | 2.67 | 61,297 | 40 | 53,838 |
| `int8:4` | 0.248 | 0.00195 | 4/6 | 0.0 | 114 | 2.83 | 18,746 | 41 | 53,904 |
| `int8:5` | 0.496 | 0.00391 | 4/6 | 0.0 | 2 | 2.67 | 6,720 | 41 | 54,232 |
| **`int8:6`** | 0.992 | 0.00781 | **5/6** | 0.0 | **1** | 2.50 | 2,415 | 42 | 54,929 |
| `int8:7` | 1.984 | 0.01563 | 3/6 | 0.5 | 4 | 2.67 | 654 | 43 | 55,913 |
| `int8:8` | 3.969 | 0.03125 | 2/6 | 6.5 | 68 | 1.33 | 87 | 86 | 57,714 |
| `int8:9` | 7.938 | 0.0625 | 0/6 | 272.5 | 815 | 0.33 | 0 | 107 | 64,413 |
| `int8:10` | 15.875 | 0.125 | 0/6 | 92.5 | 32,614 | 0.67 | 0 | 109 | 64,444 |

Read the two ends together and the shape is unambiguous. `k = 9` and `k = 10`
**never touch the container rail at all** — their ceilings are above the measured
`|S|max` — and they are the two worst points in the table, 0/6 with rank
medians in the hundreds. **The damage is resolution, not range**, exactly as the
distribution predicted. Going the other way, `k = 3` saturates **61,297** times
in six steps and still only reaches 4/6. The optimum is a shallow interior
maximum at `k = 6`, and it is the best of a bad set: **5/6 where the int16
container gets 6/6, on a six-step smoke that cannot resolve anything finer.**

**Winner selected for the full point: `int8:6`** — best top-1, best rank max,
and 2,415 rail hits, which is the middle of the saturation range rather than
either extreme.

### The truncation point, measured once, at the winning `k`

Track P's experiment RTL truncated with no rounding (`PLACE_EXP.md` §5.1). The
spec asks for the price of that as *"a cheap second point only to record what
**not** to build"*:

| law at `k = 6` | top-1 | rank med | rank max | top-5 | S8 rail |
|---|---|---|---|---|---|
| `int8:6` (round-half-away) | **5/6** | 0.0 | **1** | **2.50** | 2,415 |
| `int8t:6` (truncate) | 3/6 | 1.0 | **22,683** | 1.67 | 2,221 |

**Rounding is worth two of six top-1 and four orders of magnitude of rank max**
at identical container geometry. Whatever container this build ends up with,
**it must round.** A unit test proving `round != truncate` is not this
measurement, and this is the measurement.

---

## 4a. The exponent-granularity axis — priced, not implemented (review F3)

**Why this section exists.** §4 swept `k` and found no good value, and an
earlier revision of §8 concluded from that that *"a per-row exponent is the
only remaining L-family answer"*. **That overclaimed, and the overclaim is
visible in this gate's own code**: the `k` that was swept is **GLOBAL** —
`dn_state_pack` returns `np.full(1, k)`, one exponent for the whole model, for
every layer, head, row and token. Between that and `int8e`'s **per-row**
exponent sit **per-layer** and **per-head**, both the same L-family idea and
**both cheaper RTL than per-row** — and neither was swept or even named. So the
sweep priced one point of an axis, not the axis.

**What was measured** (`evidence/qwen9b/g1/smoke_9b_w4g128gptq_int16_rsf8_egran.log`,
one six-step `int16` smoke, **985.6 s = 0.27 h**, cache hit, 0 quantization
passes). For every state write the probe computes the exponent a container of
each granularity would pick — `bitlen(group max) − 7`, the same priority encode
`dn_state_pack` already uses — and scores the state in units of **that**
container's LSB. The statistic is **codes per rms**: how many container codes
one rms of state is worth. **Below 1 means the state is mostly quantized to
zero, which is the failure §4 measured.**

| granularity | exponent | container LSB | **codes per rms** | vs global |
|---|---|---|---|---|
| **GLOBAL** (what the `k` sweep swept) | `e = 9`, one for everything | 512 LSB | **0.263** | — |
| **PER-HEAD** (never swept, cheaper RTL than per-row) | `e ∈ [0…9]` | per head | **2.576** | **9.80×** |
| **PER-ROW** (`int8e`, option A as written) | `e ∈ [0…9]` | per 128-element row | **10.720** | **40.78×** |

```
e_head histogram {0:187, 1:182, 2:406, 3:674, 4:1080, 5:1082, 6:617, 7:171, 8:137, 9:72}
e_row  histogram {0:338105, 1:91837, 2:71033, 3:46257, 4:24561, 5:10658, 6:4585, 7:2059, 8:647, 9:82}
```

**The finding, stated as narrowly as the measurement supports it.** The
per-head exponent spans **ten binades** across the 4,608 head-writes of six
steps, which is why a single global exponent cannot serve them: the loudest
head needs `e = 9` and the quietest would be fine at `e = 0`, and the global
container is forced to the loudest. **Giving the exponent per-head granularity
moves the state from 0.263 codes per rms to 2.576 — across the `codes/rms = 1`
line, and about 3.3 bits of the ~9 bits §3 says are missing.** Per-row buys
another ~2 bits on top.

**What this does NOT say, and it is the important half.** `codes/rms > 1` is
**necessary, not sufficient**: it says the state is no longer quantized mostly
to zero, not that top-1 recovers. **No fidelity was scored at any granularity
other than global** — not per-layer, not per-head, not per-row — and this gate
did not implement any of them, because that is the L1 escalation and the
escalation is the STOP item. The honest statement for the fork is: **per-head
plausibly recovers the resolution the global `k` lost, at less RTL than
option A as written, and nobody has measured whether it recovers the top-1.**
The probe is a `ref/fidelity_check.py` wrapper, so it changed no numeric path
and cost no cache (§9's digest trap) — the same digest `0c6077f8…` and the same
two cache hits as every other run.

## 5. Step 4 — the full point at the winner, and the repeat

168 steps (108 teacher-forced + 60 free) on the four committed prompts, at the
identical harness, golden and prompts as the committed baseline.

**First, the harness reproduces a committed number before it produces a new
one** (label **D**). `fixed_9b_w4g128gptq_int16_rsf8_a` against `LADDER.md` §4:

| quantity | committed baseline | this harness, `int16` | |
|---|---|---|---|
| top-1 | 95 / 108 | **95 / 108** | ✓ |
| rank median / max | 0 / 5 | **0.0 / 5** | ✓ |
| top-5 overlap | 3.69 | **3.69** | ✓ |
| `|x|max` (rail 32768) | 32767 | **32767** | ✓ |
| residual clips | 23 | **23** | ✓ |
| `S_F` saturation | 4,392 | **4,392** | ✓ |

All six of the baseline's published quantities, and the seventh column with
them. The free-run text matches the committed log word for word
(*' is Paris.\nThe capital of France is not Paris.'*, …). So the state law is
inert at `int16`, the cached weights are the same weights Track L quantized
**without** the cache and at a different thread count, the `RS_F` env knob is
inert at 8, and every row below differs from the baseline **only** in the state
container.

**Then the scored point, and its repeat in a fresh process** — the two ran
**concurrently, not sequentially**, launched seconds apart on snoke at the same
pinning; they are independent processes with independent caches and RNG, and
nothing is carried between them, but "fresh process" here means *separate*, not
*later*:

| config | top-1 | rank med | rank max | top-5 | `|x|max` | clips | `S_F` sat | S8 rail | `|S|max` |
|---|---|---|---|---|---|---|---|---|---|
| `int16` `RS_F=8` (baseline) | **95/108** | 0.0 | 5 | 3.69 | 32767 | 23 | 4,392 | 0 | 61,096 |
| **`int8:6` `RS_F=8` run a** | **72/108** | 0.0 | **214** | 2.81 | 32767 | 15 | 635 | 115,073 | 55,757 |
| **`int8:6` `RS_F=8` run b** | **72/108** | 0.0 | **214** | 2.81 | 32767 | 15 | 635 | 115,073 | 55,757 |
| `int8:6` `RS_F=7` | 73/108 | 0.0 | 335 | 2.81 | **27692** | **0** | 541 | 115,095 | 54,389 |

### The repeat run: STOP case 4 is CLEARED, and the bar's premise is now measured

The spec was explicit that "a re-run should reproduce exactly" was **an
argument, not a measurement**, and that `LADDER.md` §6.8 had measured no
run-to-run spread at any point. It is measured now: runs **a** and **b** of
`int8:6`, in two separate concurrent processes, are **byte-identical over the entire report
body** — every per-prompt argmax list, every rank vector, every top-5 vector,
both counters, the free-run token ids and the decoded text. `diff` of the two
logs from the `--- S=1 …` line onward returns **only the json path and the end
timestamp**. The observed spread is **exactly zero**, so the 93-vs-92 threshold
is meaningful and this FAIL is not noise.

*(The plan asks for agreement on **seven** quantities where the spec says six.
Seven is what was checked — top-1, rank median, rank max, top-5 overlap,
`|x|max`, clips, `S_F` saturation — plus this gate's two added columns, S8 rail
and `|S|max`, for nine. The spec/plan discrepancy is recorded here rather than
resolved by dropping a column, as the plan directs.)*

### Free-run coherence

Text is still coherent English and Python on all four prompts even at 72/108 —
this is a rank collapse, not a degeneration:

| prompt | `int16` (95/108) | `int8:6` (72/108) |
|---|---|---|
| 1 | *' is Paris.\nThe capital of France is not Paris.'* | *', Paris, is the city of light.\nThe capital'* |
| 2 | *', in a magical world full of wonders, there was a'* | *' in a small town in the north of the United States,'* |
| 3 | *'\nimport pandas as pd\nimport matplotlib.pyplot as plt\n'* | *'\nfrom scipy import stats\n\ndef get_pearson_cor'* |
| 4 | *' name is [Your Name] and I am a [Your'* | *' name is "Sahil" and I am a "'* |

So the FAIL is carried by the numeric criteria, not by the text criterion. The
per-prompt teacher-forced split shows where it goes: **24/27, 11/27, 19/27,
18/27** — prompt 2 loses more than half its tokens on its own.

---

## 6. Step 5 — the `RS_F 8 → 7` rider

Measured on the same runs, at the winning law, on both the smoke and the point:

| | top-1 | rank max | top-5 | `|x|max` | residual clips |
|---|---|---|---|---|---|
| smoke, `int8:6` `RS_F=8` | 5/6 | 1 | 2.50 | 32767 (rail) | 1 |
| smoke, `int8:6` `RS_F=7` | 5/6 | 1 | **2.83** | **27692** | **0** |
| point, `int8:6` `RS_F=8` | 72/108 | 214 | 2.81 | 32767 (rail) | 15 |
| point, `int8:6` `RS_F=7` | **73/108** | 335 | 2.81 | **27692** | **0** |

**The plan's decision table** — *"if Q8.7 removes residual clipping without
costing top-1, take it; if it costs top-1, do not"* — reads **take `RS_F = 7`**:
clipping goes to **zero** at both resolutions, `|x|max` lands **15 % below the
rail** instead of pinned on it, and top-1 does not fall (72 → 73).

**Two things recorded rather than smoothed over.** Rank max moves the *wrong*
way, 214 → 335; the decision table does not weigh rank max, and this gate does
not add a criterion the table does not have — it records the number.
And the whole rider was measured **inside a law that failed**, so `RS_F = 7` is
a measurement carried forward, **not a ratified decision**: nothing is decided at
a STOP. The one RTL literal it would touch remains
`rtl/conv4_silu.sv:50` `pre = rshr64(64'(acc1), 9);` — `RS_F + CW_F − 12`, which  <!--cites:noquote-->
becomes 8 at Q8.7. **Not measured: `RS_F = 7` under the `int16` container**,
which is the configuration that would actually ship under fork option 1 (§9).

---

## 7. Step 6 — the second axis: BOTH range tools, and why one tool would have lied

### Both tools needed a fork before they could run at 9B — the same one-line defect

> **SUPERSEDED IN PART, 2026-08-31 (G2c, Task 5).** The paragraph below is
> accurate for the tree G1 ran on and is left intact. Since then **one of the
> two tools has been fixed**: `ref/audit_ranges.py` now opens the checkpoint
> with `LQ.find_checkpoints()` (plural) and runs at 9B **unforked** — see
> `evidence/qwen9b/g2/G2C_CHAIN.md` §2.1(a) and §6.2. The line number below is
> therefore given without a `:NNN` (the fix moved it); the sentence still
> describes `evidence/qwen2b/q2/audit/gate_port_probe.py`, which is Track Q's
> committed evidence and is **not** fixed, so G1's fork remains the only way
> to run *it* at 9B.

`ref/audit_ranges.py` and `evidence/qwen2b/q2/audit/gate_port_probe.py` both
open the checkpoint with `LQ.find_checkpoint()`, which returns **the first shard
only** — its own docstring says so (`ref/load_qwen35.py:108-113`: *"callers that
read tensors want `find_checkpoints` / `SafeTensors`, which take the whole shard
list"*). 0.8B and 2B are single-shard, so both tools were correct everywhere
they had ever been run; 9B has four shards and both die with
`KeyError: 'model.language_model.layers.0.linear_attn.A_log'`. Neither committed
script was edited: `evidence/qwen9b/g1/audit_ranges_9b.py` and
`evidence/qwen9b/g1/gate_port_probe_9b.py` run the originals verbatim under
`runpy` with `find_checkpoint` patched to the full shard list, so the
measurement is still the original tool's code.

### Axis 1 — `ref/audit_ranges.py`, the state: 5 ATTENTION items

`evidence/qwen9b/g1/audit_ranges_9b_report.md` (46 min, full 249-matrix
production quantization + the 248320×4096 head):

1. W4 group-scale underflow: 96 / 61,997,056 groups hit `m == 1`, 64 clipped up
   from 0, annihilating 4,131 weights.
2. W4 value clipping: **73,330,696 of 7,935,623,168 weights (0.924 %)** round
   outside `[-8,7]`.
3. **W4 weight error above the project's own 15 % bound on 5 / 249 matrices**,
   worst `L8.dn.in_b` at **15.47 %**. **The offenders are named, because the
   auditor's own prose is boilerplate here**: it explains them as *"the
   outlier-heavy small projections (`v_proj`/`k_proj`/`o_proj`, 512-2048
   rows)"*, but the five matrices it actually lists are `L25.dn.in_a`,
   `L26.dn.in_a`, `L28.dn.in_a`, `L29.dn.in_a` and `L8.dn.in_b` — **all five
   are DeltaNet gate projections (`in_a`/`in_b`), not attention projections at
   all**. That matters for this gate specifically: `in_a` and `in_b` are the
   matvecs feeding `a_q12` and `b_q12`, i.e. the **decay and beta gates** — the
   same gate chain §7's port clamp damages. No assert fires today because the
   15 % check only runs inside the synthetic self-test.
4. y32 headroom: the conservative `sh` discards up to **5.6 bits** of the int32
   accumulator (precision only, no overflow).
5. The embedding at Q7.8 uses **0.368 %** of the int16 range (120 LSB peak,
   3.4 LSB RMS) → 8.4 % relative RMS error on the layer-0 residual.

The DeltaNet-state row is in section 5, *deferred*: the auditor says in its own
text that `S_F = 13` "cannot be settled from weights alone… the bound was
measured on RANDOM weights (|S|max 0.76, rms 0.009)". §3 above is that
measurement, and it is **7.0437 / 0.0164**, i.e. **9.3× the max and 1.8× the rms**
of the note the format was frozen against.

### Axis 2 — `gate_sat` via `gate_port_probe`, the `Av` port: 60 of 768 heads

`evidence/qwen9b/g1/11_gate_port_probe_9b.log`:

```
heads                                   : 768
max A = exp(A_log)      (port [0, 8.0)) : 76.9957
max |dt_bias|           (port +/-8.0)   : 18.5000
max |conv_w|            (port +/-4.0)   : 1.2344
A   out of uint18 Q15 BEFORE the clamp  : 49 / 768
dt  out of int16  Q12 BEFORE the clamp  : 12 / 768
decay CHANGED by the production clamp   : 60 / 768
decay CHANGED by 18-bit/int16 wrap      : 61 / 768  (pre-82781e5 behaviour)
```

Worst individual heads, decay as a fraction of the no-decay rail:
`L12 h18` **0.13895 → 0.81458**, `L14 h5` **0.05362 → 0.55658**,
`L14 h8` 0.75986 → 0.89639, `L17 h18` 0.91882 → 0.96735. A head whose decay
moves from 0.139 to 0.815 is a head that has stopped forgetting.

**The spec required this to come from `qd["gate_sat"]`, and the probe recomputes
the same two expressions instead — so the equivalence is measured, not
assumed.** DN layer 0 was quantized with the production `quant_deltanet` and its
`qd["gate_sat"]` compared entry for entry with the probe's verdict:
**IDENTICAL, 10 of 32 heads** (`evidence/qwen9b/g1/11_gate_port_probe_9b.log`, the cross-check
section). The 2B audit found **1 of 288** heads over its rail; 9B has **60 of
768**.

### Why spec §4.1(d) insisted on two tools — the demonstration

Both tools ran on the same checkpoint minutes apart. `audit_ranges` says, in its
own words:

> PASS `A` — max 76.9957 < 8.0, fits uint18 Q15.
> PASS `dt_bias` — max |dt| 18.5000 < 8.0.
> `decay computed with the TRUNCATED 18-bit A` — **0 / 768 heads give a WRONG decay** — PASS

Three PASS verdicts, one of which prints `76.9957 < 8.0` as its own
justification, because sections 1 and 3 read the values `quant_deltanet` has
**already clamped**. `audit_ranges` prints the caveat itself and names the other
tool. **On this port, one tool would have reported a clean bill of health.**

### The clamp priced, as far as a smoke can price it

Because the class is real, it was measured rather than left as a range table:
one six-step smoke with `--diag gateport` (`DT_Q12_MIN`/`DT_Q12_MAX`/`A_Q15_MAX`
relaxed to ±2³⁰), which pays its own 2.7 h quantization pass because a diag run
may not use the weight cache:

| `int16`, six steps | top-1 | rank max | top-5 | `|x|max` | clips | `S_F` sat | `|S|max` |
|---|---|---|---|---|---|---|---|
| production ports (clamped) | 6/6 | 0 | 2.83 | 32767 | 1 | **93** | **57,702** |
| ports relaxed (`--diag gateport`) | 6/6 | 0 | 2.83 | 32767 | 1 | **82** | **56,276** |

**At smoke resolution the clamp costs nothing scored** — identical top-1, rank
and top-5 — but it demonstrably **changes the DeltaNet state trajectory**
(`S_F` saturation 93 vs 82, `|S|max` 7.044 vs 6.870), which is what 60 heads
that no longer forget would do. A six-step smoke saturated at 6/6 cannot resolve
a small cost, so **this is not a price, it is an upper bound on visibility**.
**NOT ESTABLISHED: what the gate-port clamp costs at 108-step resolution.** The
measurement that would settle it is one 168-step `--diag gateport` point, and it
costs **≈ 7 h** rather than 3.8 h because a diag run cannot reuse the cache.

---

## 8. The verdict against the bar (wave 1)

Scored against spec §4.1(c) and the plan's Task 1 table, from
`fixed_9b_w4g128gptq_int8_k6_rsf8_a` (and `_b`, identical):

| criterion | required for PASS | measured at `int8:6` | |
|---|---|---|---|
| top-1 | **≥ 93 / 108** | **72 / 108** | **FAIL** (−21 against the bar, −23 against int16) |
| rank max | **≤ 8** | **214** | **FAIL** (> 16, i.e. past the MARGINAL band too) |
| top-5 overlap | **≥ 3.50** | **2.81** | **FAIL** |
| free-run text | coherent on all four prompts | coherent on all four | pass |

**Band: FAIL.** top-1 < 90 and rank max > 16 — two independent FAIL triggers,
with the third (top-5) also failing. MARGINAL (90–92) is not in reach: no `k`
in the sweep came close, and the two `k` values with no range loss at all are
the worst in the table.

**The STOP triggers, each stated explicitly** (spec §4.1(f)):

| # | trigger | status |
|---|---|---|
| **1** | L0 lands MARGINAL or FAIL at **every** `k` | **FIRES.** Eight `k` measured, 3…10; the best is 5/6 at smoke and **72/108** at the point |
| **2** | L0 fails and the rung would have to escalate to **L1** | **FIRES.** §3's arithmetic says a **globally** shared exponent cannot span this state, and every remaining answer in the L family gives the exponent a finer granularity — per-layer, per-head or per-row (§4a) — which is the escalation, and escalating is itself a STOP item. *(An earlier revision said "per-row is the only remaining L-family answer". That overclaimed: the `k` this sweep moved is **global** — `dn_state_pack` returns `np.full(1, k)` — so per-layer and per-head sit between it and `int8e`, were never swept, and are cheaper RTL than per-row. §4a measures what they would buy.)* |
| **3** | either range tool reports a saturation class the fidelity top-1 does not reflect | **FIRES.** `gate_sat`: 60/768 heads' decay changed by the clamp, and the smoke's top-1 is identical with and without it (§7) |
| **4** | the repeat run does not reproduce | **DOES NOT FIRE — cleared.** The two runs are byte-identical; the observed spread is exactly zero |

Trigger 4 clearing is the load-bearing one: it is what makes triggers 1–3 mean
something rather than being read as run-to-run noise.

---

## 9. STOP — the fork, with prices attached, and no recommendation

> **RESOLVED 2026-08-31: the user took OPTION B (`int16` state). This section is
> kept as the decision record it was at the STOP — the options and their prices
> as they stood when the choice was made — and is NOT live. §13 is the
> disposition.**

**The plan's STOP protocol is not advisory. No RTL is written. Tasks 3–16 do not
start. The user decides.** The options, with Track P's own measured prices
(`evidence/qwen_next/place_exp/PLACE_EXP.md`, label **T**) and the spec's §4.1
arithmetic:

| option | what it is | price on record | what is unknown |
|---|---|---|---|
| **A — proceed with the L1 law** | **MEASURED, 2026-08-30 (§11) — this row is no longer a proposal.** `int8e`, int8 mantissa + **per-row** power-of-two exponent, the structure the KV bank already uses (`ref/layer_fixed.py:19`; `KVC_F = 6` at `ref/layer_fixed.py:60`; `rtl/layer_chan.sv:714`). **Scored 94/108, rank max 13, top-5 3.56 — MARGINAL, missing PASS on rank max alone, one token below the int16 baseline.** The per-HEAD variant `int8h` (768 exponents instead of 98,304, less RTL) scored **83/108 — FAIL**. | **URAM 592, unchanged, and the bit layout is now stated** (§11.2): each 1024-bit half-row becomes 1032 b, two 1032-bit halves still map to fifteen URAMs each, thirty per bank, with the exponent at bits [1031:1024] of its own half — URAM 14 of that half's 15-URAM slice — so it never straddles the half boundary. **(S)** on Track P's primitive counts; **G4's OOC run must confirm 592**. Per-head needs no in-row exponent at all (768 B beside the array, the `emem` road) but is the one that failed. | **Rank max 13 is the whole gap**, and it is untested against `RS_F = 7`, which removed residual clipping outright elsewhere in this gate (§11.5) — **3.9 h to find out**. Per-row also costs an exponent-timing obligation per-head does not: `dn_step` writes a row at a time, so per-row is computable in-flight while per-head needs a two-pass write or a stale exponent (§11.2). **G4 must re-confirm 592 for whichever is chosen.** |
| **B — option 1: keep the int16 state** | the `wide` variant, 24+8 banks | **928 URAM** of 960, placed OK. **As built (N=0) the module is WNS −2.103 / TNS −12,945.8 / 27,287 failing EP with the named 2048-bit bank-mux at −1.848** — but that is the as-built number and it is **not** where Track P's verdict lands (see the row to the right). Flip-flop cost of pipelining: 54,276 → 78,948 at N=2, ≈ **1 %** of the device, **no LUT change, URAM stays exactly 928** (`PLACE_EXP.md` §3.7) | **The read-path objection is DEAD, and the study says so.** `pipe2alt` (N=2 + `AltSpreadLogic`) takes the named net to **+0.097 ns MET** at the full wide geometry, and `pipe2bank`'s group return to +0.439 MET (§3.8): *"the read path the study named as the sharp form of D3 is not what stops option 1."* **`DN_PIPE=2` does NOT close the module** — −1.391 / −2,007.2 / 6,638 EP, and **per-bank fan-out is worse** at −1.956 / 12,692 EP. **The binding constraint MOVED to the write-control fan-out**, whose worst path is **one logic level and 95.9 % route** — *"a placement signature, not a structural one"*. **The remaining blocker is a pblock that was never tried**, so Track P's verdict is **"neither demonstrated live nor demonstrated dead"** — not "dead". `NEXT_SESSION.md` T5 cuts both ways: constraining `layer_0` *at all* cost `build_035` ~1 ns. **The latency price is bounded, not designed** (§5 item 14): ~0.15 % is `DN_PIPE=1`'s price and **N=1 does not close** (−0.339); N=2 needs a lead of 6 that pass 2's 5-state loop cannot give, so it costs a wait state (**≈ +10 %**) **or a two-outstanding restructure nobody has written or shown to close** — *"an upper bound and an admission, not an implementation"* |
| **C — option 3: DDR spill** | spill the state to DDR | **0.6 %** of 9B W8 traffic | **a large new RTL path**, unpriced |
| **D — abandon** | do not ship 9B on this bitstream | — | — |

**No recommendation is attached to any of them, and none is implied by the order
of the rows.** Four things belong beside the fork because they were measured
here and they bear on more than one option:

* **THE GATE-PORT CLASS IS A COST EVERY BRANCH PAYS. It is option-independent.**
  STOP trigger 3 (§7) is a property of the **checkpoint against the frozen
  `gate_unit` ports**, not of the state container: **60 of 768 DN heads have
  their decay changed by the production clamp** (worst `L12 h18` 0.13895 →
  0.81458), because `max A = exp(A_log)` is **76.9957** against a port of
  `[0, 8)` and `max |dt_bias|` is **18.5** against ±8. **A, B, C and D all
  inherit it unchanged** — option B's int16 state does not remove it, and
  option A's exponent does not touch it. It is unpriced at scored resolution
  (§7), and pricing it costs ≈ 7 h. **The user should read it as a standing
  cost on the whole 9B build, not as a fact about the int8 experiment.**
* **Whatever container is chosen, it must ROUND.** Truncation at the same `k`
  costs 2 of 6 top-1 and takes rank max from 1 to 22,683 (§4).
* **`RS_F = 7` is NOT free, and the answer is container-dependent (§12).** At
  the `int8:6` global container it removed clipping at no top-1 cost (§6). At
  the **per-row** container — the one option A would actually ship — it removes
  the clipping but **costs 5 top-1 (94 → 89) and worsens rank max (13 → 18)**,
  so the ratified O5 condition rejects it and **`RS_F` stays 8**. It remains
  **unmeasured under `int16`**, the container option B would ship.
* **The exponent-granularity axis was priced but not implemented** (§4a). It
  sits between option A as written and the global `k` that failed, and it is
  **cheaper RTL** than per-row.

> **THE CACHE-DIGEST TRAP, because it prices every option's next measurement.**
> `_WQ_SOURCES` in `ref/fidelity_check.py:132-134` lists the `ref/` files whose
> text defines the quantized weights, and **`ref/layer_fixed.py` is one of
> them**. So **any** edit to `ref/layer_fixed.py` — the F5 counter fix below, a
> per-head exponent variant, an L1 scoring run that touches the law — changes
> `src_sha256`, **misses the 6.55 GiB layer cache and the 0.96 GiB head cache,
> and costs 3.03 h before the first token is scored.** That is deliberate: it
> is the same mechanism that discharged M1 in §1, and a silent hit would be
> worse than a slow miss. **`ref/fidelity_check.py` is deliberately NOT in the
> list** — its contribution to the quantized bytes is the *arguments*, which are
> all in the key explicitly — which is why §4a's granularity probe was written
> there and cost 0.27 h instead of 3.3 h. **Sequence any further measurement so
> that every `ref/layer_fixed.py` edit happens once, before the runs that need
> it, not between them.**

**Common mode, stated because it is the one way all these numbers could be
wrong together.** Every row in §4, §5 and §6 was scored against **the same
quantized weight images** — one 3.03 h pass, reloaded from disk, with all
seventeen 9B runs printing the identical `quantizer sources sha256` (§1) and the
cache-hit lines in their own logs (§2). If those images were themselves wrong,
every row would move together and the *comparison* between them would still
hold, because the container is the only thing that differs. What rules out a
common-mode error that could flip the verdict is that **the `int16` row of that
same cache reproduces the committed baseline exactly on all seven quantities**
(§5) — a number produced by Track L from an independent quantization pass, at a
different thread count, with no cache at all. **NOT RUN: the direct interaction
test** — one 168-step point at `int8:6` with the cache disabled, re-deriving the
weights so the FAIL is confirmed against a second, independent quantization
rather than against the same images. Its **incremental** cost over the point
already taken is the quantization pass, measured at **≈ 2.9–3.0 h**
(1,232.9 s + 9,680.6 s = 3.03 h, §2), and it is available on request.

---

## 10. Not established

> **As of the close-out (§13), items 1 and the `RS_F` line below are settled or
> re-scoped; the rest stand. §13.5 carries the one open measurement forward.**

1. ~~**What L1 (`int8e`) scores.**~~ **MEASURED on 2026-08-30 under the user's
   ruling — see §11: `int8e` 94/108 MARGINAL, `int8h` 83/108 FAIL.** The
   estimate this item carried (0.27 h smoke + 3.9 h point ≈ 4.2 h warm, +3.03 h
   for the digest) was accurate: the wave cost 3.03 h rebuild + 2 smokes + 4
   points. What replaces it as unmeasured: **`int8e` at `RS_F = 7`** (§11.5),
   3.9 h, the one measurement that could move it from MARGINAL to PASS.
   *(Superseded text kept for the record: one smoke plus one 168-step point
   would price it: 0.27 h + 3.9 h ≈ 4.2 h on the warm cache — but the `int8e` **saturation counter was fixed in
   this round (review F5)** and that fix edits `ref/layer_fixed.py`, so the
   first run after it **misses the cache and adds 3.03 h**: "fix the counter,
   then score" is **≈ 7.5 h** (§9's digest trap).
   **The counter itself:** `dn_state_narrow`'s `int8e` branch counted
   `|codes| > 127` *after* `dn_state_pack` had already clipped, which is
   structurally zero — a counter that could not fire. Moving it before the clip
   is **also** vacuous, because the `+1` exponent fixup has already removed
   every exceedance. It now counts what actually varies: **`sat8` = elements
   that exceed the rail at the FIRST-CHOICE exponent, `e_fixup` = rows whose
   exponent had to be incremented**, both taken before the fixup. Demonstrated
   firing: a row at `|S|max = 32,700` gives `sat8 = 4, e_fixup = 1` and steps
   `e` from 8 to 9, where `32,639` gives `0, 0`. After the fixup, element-level
   saturation under `int8e` is **exactly zero by construction** — a structural
   property, which is why it must not be reported as a measurement.)*
   **The counters fired in production** (§11.4): `e_fixup` 637/129,024 groups
   (0.49 %) at per-head and 40,844/16,515,072 (0.25 %) at per-row, so neither
   is vacuous.
2. **What the gate-port clamp costs at 108-step resolution** (§7) — ≈ 7 h.
3. **`RS_F = 7` under the `int16` container** — the configuration fork option B
   would ship. Still unmeasured, and §12 now makes it a genuinely open question
   rather than a formality: the rider is **container-dependent**, neutral at
   global and negative at per-row, so its sign under `int16` cannot be inferred
   from either. 3.8 h with the cache warm.
4. **Fidelity at PER-LAYER granularity.** Per-head and per-row are now scored
   (§11.4); **per-layer — 24 exponents, between global's 1 and per-head's
   768 — was never implemented or scored.** §4a's resolution probe did not
   measure it either. Given per-head (768 exponents) scored 83/108 and FAILED,
   per-layer would be expected to sit between 72 and 83, i.e. **also FAIL** —
   but that is an expectation, not a measurement, and this gate does not
   report expectations as results.
5. **`k` values other than 6 at the full point.** The sweep ranks `k` on a
   six-step single-prompt smoke, which is what the spec asks it to do; only
   `k = 6` was scored at 168 steps. `k = 5` (4/6, rank max 2) and `k = 7` (3/6,
   rank max 4) are close enough at smoke resolution that the smoke ranking is
   not proof of the point ranking — but all of them sit far below the 93 bar's
   neighbourhood, so this does not change the band.
6. **Run-to-run spread beyond one configuration.** Measured, and zero, for
   `int8:6` on snoke at 6 threads. Not measured across hosts, thread counts, or
   other laws.
7. **`audit_ranges` section 2b at 9B audits `embed_tokens`, not the LM head.**
   The head is untied at 9B (`ref/load_qwen35.py:371-374`) and section 2b is
   labelled "Tied embedding as the LM head". It is a real audit of a real
   matrix; it is not the head. Its per-family layer-count labels ("18 layers",
   "6 GQA layers") are 0.8B strings — the **counts** are 9B-correct, the
   **labels** are stale.
8. **Both range tools cite `ref/layer_fixed.py:879-880` for the gate clamps.**
   That citation was already stale on committed `main` (the clamps were at
   `64e4b4e:ref/layer_fixed.py:1144-1145`, pinned to that tree because the
   number is a fact about it and not about HEAD); after this task's edits
   they are at `049ccea:ref/layer_fixed.py:1442-1443`, pinned the same way and
   for the same reason. Text only — no measurement moves. *(Pinned 2026-09-10,
   pre-ship documentation chore fix round: left unpinned, this second number
   drifted twice — written as 1331-1332, mapped to 1371-1372 by the pre-ship
   tool chore's mechanical pass — while the clamps themselves never moved. A
   renumber maps the LINE, not the CLAIM.)*
9. **`s_sat` does not cover the free-run pass.** `evidence/qwen_next/ladder/run_fidelity.sh`'s header says
   *"the resid_clip / s_sat counters run over all 168"*; `resid_clip` does, but
   `s_sat` is captured before the free-run loop, so the committed 4,392 is the
   **108-step** count. This gate's own `sat16` counter, which does run over all
   168, reads **6,177** for the same run — the two are consistent, and the
   4,392 reproduces the committed value exactly.
10. **Nothing about hardware.** No RTL, no synthesis, no board. The board stayed
   on `build_035_fp2a_exc_po` serving the 2B throughout.


---

## 11. THE FINER-EXPONENT WAVE (user ruling, 2026-08-30)

**The ruling.** At the G1 STOP the user ruled **score finer exponents first**:
implement per-head and per-row exponents in one edit wave, score both at the
full point, ride `RS_F` only if one passes, and come back. **The STOP on
direction remains in force — options B, C and D stay open and nothing here
chooses between them.**

### 11.1 What was implemented, in ONE edit wave

`ref/layer_fixed.py` gains one law and a granularity map; the grammar is now:

| `FABLE5_DN_STATE` | exponent granularity | exponents at 9B |
|---|---|---|
| `int8:<k>` / `int8t:<k>` | **global** — one `k` for the whole model | 1 |
| **`int8h`** (new) | **per-head**, one per `(dn_slot, head)` | 24 × 32 = **768** |
| **`int8e`** (L1 as the spec defines it) | **per-row**, one per `(dn_slot, head, row)` | 24 × 32 × 128 = **98,304** |

All three hold the same 7-bit magnitude + sign and the same round-half-away
rule (the must-round finding of §4 is binding on all of them). **They differ
only in how many values share an exponent.** "Row" is the last axis of
`S[h]` — 128 codes = the **1024-bit URAM half-row** that `int8naive` writes
independently.

One edit wave, deliberately, because of §9's digest trap: `ref/layer_fixed.py`
is inside `_WQ_SOURCES`, so the wave pays the **3.03 h** rebuild **once** for
both laws rather than twice. The F5 counters (`sat8`, `e_fixup`) are active for
both, so L1's URAM-freeness claim gets a measured check rather than a
structural assertion.

**Selftest, at both granularities** (`ref/layer_fixed.py` `_dn_state_law`):
`int8h` and `int8e` agree exactly on a state whose rows share a max, and
diverge exactly as the axis predicts when one row is louder — *"a 2^6 loud row
leaves a quiet row **128 distinct codes under `int8e` but only 4 under
`int8h`**"*. The rail counters were also proved able to **fire** at both
granularities (`|S|max = 32,700` → `sat8 > 0, e_fixup > 0`; `32,639` → silent),
which is the F5 fix doing its job.

### 11.2 The URAM arithmetic per granularity — and the bit layout, finally stated

The review flagged that spec §4.1 asserts an in-row exponent is URAM-free
*"provided the exponent sits inside its own half-row rather than straddling the
half boundary"* and **never states the layout that satisfies it**. Here it is.

**The primitive.** URAM288 is 4096 × 72 b. S1's `int8naive` map puts the 9B
state at 24 × 32 × 128 = 98,304 rows of 1024 b, two rows per 2048-bit bank row
→ 49,152 bank rows → **12 banks of 4096**. Each 2048-bit bank row is **two
independently written 1024-bit halves**, and Vivado maps each written half to
its own `ceil(1024/72) = 15`-URAM slice → **30 per bank**, 12 × 30 = 360 DN +
232 KV = **592**.

| granularity | exponent store | in-row? | bit-layout obligation | **URAM** |
|---|---|---|---|---|
| **global** | one constant, a CSR/immediate | — | none | **592** |
| **per-head** (`int8h`) | **768 B** (768 × 8 b) in a separate array beside the URAM — the `emem` road, exactly what the KV bank already does (`rtl/layer_chan.sv:714`, `logic [7:0] emem [4096];`, which carries **no** `ram_style = "ultra"` and is therefore inferred outside the URAM array)  <!--cites:noquote--> | **no** — the half-row stays exactly 1024 b, so the `int8naive` map is untouched | **592**, plus ~768 B of LUTRAM/BRAM18, i.e. **nothing** |
| **per-row** (`int8e`) | **96 KiB** (98,304 × 8 b), in-row: each half becomes **1032 b** | **yes** | **stated below** | **592** — `2 × ceil(1032/72) = 2 × 15 = 30` per bank, **unchanged** |
| per-row, out-of-row alternative | the same 96 KiB in a separate array | no | none | **592** + **≈ 22 BRAM36** (786,432 b / 36,864 b) |

> **CLASS B, dated note 2026-09-10 (pre-ship documentation chore).** The
> per-head row quotes the KV bank's exponent array as it stood at G1, and
> **that source no longer exists**: the state-spill's S2 replaced the banked
> KV array with per-slot memories, so the declaration is now eight thousand
> deep rather than four and lives at `rtl/layer_chan.sv:837`, under a comment
> at `rtl/layer_chan.sv:813` that still records the deliberate absence of a
> `ram_style` attribute. **The ARGUMENT is unchanged** — the exponent store
> is still inferred outside the URAM array, which is the only property this
> row uses it for. The G1-era line number and text are kept as the record of
> what was read, with an exemption marker, under the campaign's rule that an
> exemption is for source that no longer exists rather than for a citation
> that has merely moved.

**THE LAYOUT THAT MAKES THE PER-ROW EXPONENT FREE.** A 15-URAM slice carries
15 × 72 = **1080 b**; the half needs 1032, leaving **48 spare bits**. Place
half `H ∈ {0,1}` in URAMs `15H … 15H+14`; within that half put the 128 int8
codes at bits **[1023:0]** and the exponent at bits **[1031:1024]**. Since
`1024 // 72 = 14` and `1031 // 72 = 14`, **both exponent bits land in URAM 14 of
that half's own slice — bits [23:16] of it** — so the exponent is entirely
inside its own half, **no URAM is shared between the two halves, and no write
of one half can disturb the other's exponent.** That is precisely the
obligation §4.1 names, discharged. **(S)** — this is arithmetic on Track P's
primitive counts, not a synthesis result; **G4's OOC run must confirm 592 for
whichever law is chosen**, exactly as the spec requires.

**One asymmetry the URAM table does not show, and it cuts toward per-row.**
`dn_step` walks LDK rows one at a time (`rtl/dn_step.sv:226`, `:261`), so a
**per-row** exponent is computable from the row being written — the max over
the 128 values it already has. A **per-head** exponent needs the whole head's
max **before any of it can be encoded**, which means either buffering the head
(16 KiB) for a two-pass write, or accepting a one-token-**stale** exponent.
**This model takes the exact per-head max, i.e. it models the two-pass form.**
The stale-exponent variant is a different law and **is not measured here**. So
per-head is cheaper in exponent *memory* and more awkward in exponent *timing*;
the fidelity numbers below are for the exact form.

### 11.3 The digest trap, paid once — and it was conservative

The rebuild cost **3.03 h** (1,224 s head + 9,624 s layers) and produced a new
digest `04a4c9c6…`. **Then the images were compared against the ones saved
before the edit** (`evidence/qwen9b/g1/cmp_wq_cache.py`, both pickles loaded and
compared leaf by leaf):

| artifact | leaves | elements | mismatches |
|---|---|---|---|
| `wq_layers_9b` | 1,777 | **6,973,614,393** | **0** |
| `wq_head_9b` | 5 | **1,025,064,963** | **0** |

**The only key field that differs is `src_sha256`.** So the digest is
**conservative, exactly as designed**: it forced a 3.03 h rebuild that produced
**byte-identical content**, because the edit touched only the state-container
code and nothing the quantizer runs. A loud miss rather than a silent hit — and
the price of that safety is now measured rather than asserted.

**The consequence matters more than the cost: every number in §4–§6 was
computed on weights byte-identical to the ones this wave used.** The global-`k`
sweep, the `int8:6` 72/108 point and the `int16` 95/108 baseline reproduction
all carry over unchanged, so **global vs per-head vs per-row is a
single-variable comparison across both waves** — the container is still the
only thing that differs. The rebuild's own `int16` smoke reproduced the
pre-edit `int16` smoke exactly (6/6, rank max 0, top-5 2.83, `|x|max` 32767,
1 clip, `S_F` sat 93, `|S|max` 57,702), which is the same statement from the
fidelity side.

*(Inertness re-checked for this wave at both frozen geometries: `0.8b`
**`LAYER_FIXED SELFTEST PASS`** and — now that Task 2's bound fix is in the
tree — `2b` **`LAYER_FIXED SELFTEST PASS`** as well, `attn softmax+pv
rel=3.288e-02` against the `8e-02` bound.)*

### 11.4 The measurement — three granularities, one variable

Six-step smokes first, then the full 168-step point, **each point run twice in
two concurrent processes**:

| granularity | smoke top-1 | smoke rank max | smoke top-5 |
|---|---|---|---|
| `int16` reference | 6/6 | 0 | 2.83 |
| `int8:6` global (§4's winner) | 5/6 | 1 | 2.50 |
| **`int8h` per-head** | 5/6 | 1 | 2.50 |
| **`int8e` per-row** | **6/6** | **0** | **2.83** |

**The full point, and the whole axis in one table:**

| container | exponents | **top-1** | rank med | **rank max** | **top-5** | `\|x\|max` | clips | `S_F` sat | S8 rail | `\|S\|max` |
|---|---|---|---|---|---|---|---|---|---|---|
| **`int16`** baseline | — | **95/108** | 0.0 | **5** | **3.69** | 32767 | 23 | 4,392 | 0 | 61,096 |
| `int8:6` **global** | 1 | 72/108 | 0.0 | 214 | 2.81 | 32767 | 15 | 635 | 115,073 | 55,757 |
| **`int8h` per-head** | 768 | **83/108** | 0.0 | 211 | 2.95 | 32767 | 37 | 5,967 | 641 | 88,409 |
| **`int8e` per-row** | 98,304 | **94/108** | 0.0 | **13** | **3.56** | 32767 | 23 | 5,983 | 40,949 | 88,373 |

**Both repeats are byte-identical** over the entire report body — every
per-prompt argmax list, rank vector, top-5 vector, counter and free-run string.
Run-to-run spread is **zero** at both granularities, as it was for the global
law, so these are measurements and not draws.

**The granularity axis is real and it is monotone.** Global → per-head →
per-row buys **72 → 83 → 94** top-1 and takes rank max **214 → 211 → 13**.
§4a's prediction from the resolution probe — per-head 9.80× and per-row 40.78×
the global codes-per-rms — ordered the three correctly, and per-row lands **one
token below the int16 container it replaces**.

**Per-prompt splits.** `int8h` 25/15/22/21; `int8e` 26/22/24/22 against
`int16`'s 27-token prompts. Free-run text is coherent on all four prompts for
both, though `int8h` prompt 1 drifts into an enumeration (*' is Paris.\nA.\nB.\nC.'*)
where `int8e` stays in content (*' is Paris.\nA. True\nB. False\n'*).

**The F5 counters fired in production, which is the measured check the ruling
asked for** (not a structural claim):

| law | exponent groups | `e_fixup` (first-choice exponent one binade short) | `sat8` | `e` range |
|---|---|---|---|---|
| `int8h` | 129,024 = 168 × 24 × 32 | **637 (0.49 %)** | 641 | [0, 10] |
| `int8e` | 16,515,072 = ×128 rows | **40,844 (0.25 %)** | 40,949 | [0, 10] |

Both counters are non-zero at both granularities, so neither is vacuous. The
exponent spans **eleven binades** in production, which is why the global `k`
could not work and why the axis pays.

### 11.5 Verdict on the wave, and why NO `RS_F` twin was run

Against the plan's bands:

| container | top-1 ≥ 93 | rank max ≤ 8 | top-5 ≥ 3.50 | text | **BAND** |
|---|---|---|---|---|---|
| **`int8h` per-head** | 83 ✗ | 211 ✗ | 2.95 ✗ | coherent | **FAIL** (top-1 < 90 and rank max > 16) |
| **`int8e` per-row** | **94 ✓** | **13 ✗** | **3.56 ✓** | coherent | **MARGINAL** — rank max lands in the 9–16 band |

**`int8e` misses PASS on rank max alone**, and on nothing else: its top-1 is
**one token** below the int16 container's 95/108, and its top-5 clears the bar.

**The `RS_F ∈ {8,7}` rider was NOT run, and that is deliberate.** The ruling
conditions it on a granularity that **passes** at `RS_F = 8`; `int8e` is
MARGINAL, not PASS, and `int8h` failed. **No twin was authorized, so none was
run.** Recorded here because the argument for running it is strong and belongs
to the user, not to this task: `int8e` at `RS_F = 8` still clips the residual
**23 times** with `|x|max` pinned exactly on the 32,767 rail, and §6 measured
that `RS_F = 7` removes that clipping **completely** (15 → 0, `|x|max` 27,692)
at no top-1 cost. **A rank max of 13 that is partly residual-clipping-driven
could plausibly move under Q8.7 — which is exactly the difference between
MARGINAL and PASS here.** It is one 168-step point, **3.9 h on the warm cache**,
and it is the single highest-value measurement available. **It needs one word
of authorization; this task did not take it.**

---

## 12. THE `RS_F = 7` TWIN AT PER-ROW (user ruling, G1 round 2)

**The ruling.** §11.5 argued that `int8e`'s rank max of 13 might be partly
residual-clipping-driven, and that Q8.7 — which removed clipping outright
elsewhere in this gate — could move it from MARGINAL to PASS. The user
authorized exactly that measurement: the full point at `int8e` + `RS_F = 7`,
smoke first, concurrent byte-identical repeat, with a stated PASS condition —
**rank max ≤ 8 AND top-1 does not drop AND clipping removed**.

**No code changed.** `RS_F` is an env knob, so the twin ran on the **same
weight digest `04a4c9c6…`** as §11's rows, with `--wq-cache-verify` returning
**BYTE-IDENTICAL under `FABLE5_DN_STATE=int8e RS_F=7`** — the second axis of the
cache key re-proved on the wave-2 images. Single variable: the binary point.

| `int8e` per-row | top-1 | rank med | **rank max** | top-5 | `\|x\|max` | **clips** | `S_F` sat | S8 rail |
|---|---|---|---|---|---|---|---|---|
| smoke, `RS_F = 8` | 6/6 | 0.0 | 0 | 2.83 | 32767 | 1 | 123 | 1,146 |
| smoke, `RS_F = 7` | 6/6 | 0.0 | 0 | **3.17** | **27138** | **0** | 96 | 1,236 |
| **point, `RS_F = 8`** | **94/108** | 0.0 | **13** | **3.56** | 32767 (rail) | 23 | 5,983 | 40,949 |
| **point, `RS_F = 7`** | **89/108** | 0.0 | **18** | 3.37 | **28863** | **0** | 5,614 | 41,094 |

Repeat byte-identical, as everywhere in this gate. Free-run text coherent on
all four prompts; per-prompt split 26/17/24/22 against `RS_F = 8`'s 26/22/24/22
— **the whole loss is prompt 2**, which drops 22 → 17.

### 12.1 Disposition: the O5 rider is REJECTED at the per-row container

Against the ruling's PASS condition, one line at a time:

| condition | required | measured | |
|---|---|---|---|
| clipping removed | yes | **23 → 0**, `\|x\|max` 32,767 → 28,863 | **MET** |
| top-1 does not drop | ≥ 94 | **89** | **NOT MET — costs 5 tokens** |
| rank max ≤ 8 | ≤ 8 | **18** | **NOT MET — and worse than the 13 it was meant to fix** |

**So: NOT a PASS, and the ratified O5 rider condition — *"take Q8.7 only if it
removes residual clipping WITHOUT costing top-1"* — reads DO NOT TAKE IT.**
`RS_F` stays at **8** for the per-row container.

**The hypothesis §11.5 offered is refuted, and cleanly.** Rank max 13 was
**not** clipping-driven: removing every clip did not fix it, it made it **worse
(13 → 18)** and cost five top-1 tokens. That is a real result — it closes the
question the user authorized this run to answer, in the direction that says the
container's residual rank behaviour comes from the state quantization, not from
the residual container.

**And it corrects a claim this document made earlier.** §6 measured
`RS_F 8 → 7` at the **`int8:6` global** container and found it neutral-to-
positive (72 → 73), from which the headline read *"take Q8.7 by the decision
table"*. **That reading does not transfer.** The rider is **container-dependent**:
neutral at the global container, clearly **negative** at per-row (−5 top-1,
+5 rank max). Any future quotation of "RS_F = 7 is free" must name the container
it was measured on. **The `RS_F = 7` rows in §6 stand as measured; the
generalisation drawn from them does not.**

### 12.2 Where G1 stands after the twin

**The best configuration this gate has produced remains `int8e` per-row at
`RS_F = 8`: 94/108, rank median 0, rank max 13, top-5 3.56, coherent text on
all four prompts — MARGINAL, missing PASS on rank max alone, one token below
the int16 container it would replace.** The twin did not move it, so the
MARGINAL stands and **G1 does not return PASS**.

---

## 13. FINAL DISPOSITION — the user's ruling, 2026-08-31

**THE RULING: OPTION B. THE DELTANET STATE STAYS `int16`.** Per-row's MARGINAL
was offered for ratification and **declined**. The container is the shipped
Q2.13 `int16` state, at the measured **95 / 108**. **Fidelity risk on this axis
is zero — it is not a projection, it is the baseline this gate reproduced
exactly** — and the cost moves from fidelity to **timing and floorplan, which
become RTL-phase work**.

**G1 is closed. This gate returns no PASS on an int8 container, and it does not
need to: the user has chosen the container that never had a fidelity question.**

### 13.1 What ships

| | |
|---|---|
| **DeltaNet state** | **`int16` Q2.13**, `S_F = 13` — unchanged, the shipped container |
| **fidelity** | **95/108 top-1, rank median 0, rank max 5, top-5 3.69, `\|x\|max` 32767, 23 residual clips, `S_F` saturation 4,392** — reproduced by this gate's harness against the committed `LADDER.md` §4 row on every published quantity, free-run text word for word (§5) |
| **`RS_F`** | **8** — see §13.3 |
| **host code** | **nothing to revert.** `FABLE5_DN_STATE` is unset by default and unset **is** `int16`: `dn_state_narrow` reduces to the `clip16` the recurrence already had, and `new_cache_fx` keeps the `int16` dtype. The 95/108 above was produced by exactly that path, which is the byte-identity proof rather than a claim about it |
| **RTL consequence** | the state banking work item becomes the **`wide` int16 map, 24 + 8 banks, 928 URAM** — **not** the int8 `int8naive` 592. **G4's OOC target moves 592 → 928, and the floorplan becomes the critical work.** *(Recorded as a consequence, not as an amendment: the spec/plan edit is a separate task and this document does not make it.)* |

### 13.2 What the three waves established, and what it cost

| wave | question | answer |
|---|---|---|
| **1** | is a **global**-exponent int8 state good enough? | **No, and not close.** Eight `k` from 3 to 10; best `int8:6` = **72/108**, rank max 214. Root cause **measured**, not guessed: the state carries **9 bits of range above its own rms** and a shared-exponent int8 has **7**, with **58.3 % of non-zero writes below 8 LSB** (§3, §4) |
| **2** | does a **finer exponent** recover it? | **Partly, and monotonically: 72 → 83 → 94** for global → per-head → per-row. **Per-head FAILS (83/108). Per-row is MARGINAL (94/108, rank max 13)** — one token below `int16`, missing PASS on rank max alone. Both are **URAM-free at 592**, and §11.2 states the bit layout the spec had asserted without spelling out (§11) |
| **3** | does `RS_F = 7` close per-row's rank-max gap? | **No — it is worse.** Clipping goes to zero but top-1 drops **94 → 89** and rank max goes **13 → 18**. The hypothesis that the gap was clipping-driven is **refuted**; the gap is state quantization (§12) |

**Cost: ~25 h of snoke across 28 nine-B runs spanning two weight-digest epochs**
— **18 at `0c6077f8…` (waves 0–1) and 10 at `04a4c9c6…` (waves 2–3)** — and the
one boundary between them is bridged by proof: the rebuild those digests
straddle was shown **byte-identical in content** over 6.97 G elements and
1.03 G more (§11.3), so **all 28 runs form one single-variable comparison**. **Every repeat run in all three waves is
byte-identical**, so the observed run-to-run spread across the whole gate is
**exactly zero** and none of the above is draw noise.

### 13.3 `RS_F` disposition: **8**, and the rider is NOT taken

`RS_F` **stays 8**, which is the shipped value, so **no host constant and no RTL
literal moves** — `rtl/conv4_silu.sv:50` keeps its `rshr64(64'(acc1), 9)`  <!--cites:noquote-->
(`RS_F + CW_F − 12 = 9`).

The rider was measured twice and is **container-dependent**, which is the
finding to carry forward rather than any single number: **neutral-to-positive at
the `int8:6` global container** (72 → 73, clipping 15 → 0, §6) and **clearly
negative at per-row** (94 → 89, rank max 13 → 18, §12). The ratified O5
condition — *take Q8.7 only if it removes residual clipping without costing
top-1* — **rejects it at per-row**. Since the shipped container is neither of
those, see §13.5.

### 13.4 The gate-port cost travels forward, unchanged and unpaid

**This is the one G1 finding that option B does not dispose of.** It is a
property of the checkpoint against the frozen `gate_unit` ports, not of the
state container, so **it survives the ruling intact**:

* `max A = exp(A_log)` is **76.9957** against a port of **[0, 8)**; `max |dt_bias|`
  is **18.5** against **±8**.
* **49 / 768** heads exceed the uint18 Q15 port and **12 / 768** the int16 Q12
  port before the clamp; **60 / 768 heads have their decay CHANGED by the
  production clamp**, worst `L12 h18` **0.13895 → 0.81458** — heads that have
  stopped forgetting.
* `audit_ranges` calls the same port **PASS three times**, printing
  *"max 76.9957 < 8.0"* as its own justification, because it audits post-clamp
  values — which is why spec §4.1(d) mandated two tools, and the second tool is
  what found this (§7).
* **Unpriced at scored resolution.** A six-step smoke with the ports relaxed
  showed **identical top-1** but a **demonstrably different state trajectory**;
  a smoke saturated at 6/6 cannot resolve a small cost. **Pricing it is one
  168-step `--diag gateport` point, ≈ 7 h** (a diag run may not use the weight
  cache).

**It goes to the RTL phase as an open, quantified cost on the 9B build.**

### 13.5 The one open note, recorded and NOT run

**`RS_F = 7` under the `int16` container has never been measured** — and §12
makes that a genuine question rather than a formality, because the rider's sign
is container-dependent and `int16` is neither of the two containers it was
measured on. It is **the configuration that would actually ship** if taken.

* **Cost: one 168-step point, ≈ 3.9 h**, on the warm cache at
  `/var/tmp/fable5_wq` (digest `04a4c9c6…`, 7.6 GiB, still present).
* **What it could buy:** the `int16` baseline clips the residual **23 times**
  with `|x|max` pinned exactly on the 32,767 rail (§5), and `LADDER.md` §6.3
  already warns that the 95/108 should be read as *fragile, not wrong* for that
  reason. Q8.7 is the one lever that addresses it.
* **It was NOT run**, because it is outside the close-out the user authorized.
  **Recorded here as a cheap, available measurement for the RTL phase, with its
  price and its cache already warm** — not as a recommendation.

### 13.6 Where the unshipped L1 work lives

The per-head and per-row laws are **implemented, unit-tested and measured, and
deliberately not shipped**. They cost nothing to carry: `FABLE5_DN_STATE`
defaults to `int16`, so every one of them is **inert unless explicitly
selected**, and the shipped path is byte-identical with the env var unset.

| what | where |
|---|---|
| the laws | `ref/layer_fixed.py` — `FABLE5_DN_STATE ∈ {int16, int8:<k>, int8t:<k>, int8h, int8e}`, with `DN_GRAN` naming the granularity of each |
| their unit proofs | `ref/layer_fixed.py` `_dn_state_law()` — rounding vs truncation, symmetric ±127 saturation, `clip16` identity at `int16`, idempotence, per-head vs per-row equivalence and divergence, and the rail counters proved able to fire |
| their measurements | this document §4, §4a, §11, §12, and the committed `evidence/qwen9b/g1/*.{log,json}` behind every row |
| the URAM arithmetic | §11.2, including the bit layout (exponent at [1031:1024] of its own half-row, URAM 14 of that half's slice) that makes an in-row per-row exponent URAM-free |
| the counters | `DN_STATS` — `sat8`, `e_fixup`, `groups`, `e_min`/`e_max`, wired into the SUMMARY row and the json |

**If a later gate re-opens the container** — because the floorplan does not
close, or because 928 URAM proves too expensive — **the fidelity question is
already answered and does not need re-measuring: per-row is 94/108 MARGINAL at
`RS_F = 8`, per-head is 83/108 FAIL, and every global `k` is worse.**
