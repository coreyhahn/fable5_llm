# G2 / D-TOL — the `attn softmax+pv` bound in `ref/layer_fixed.py`

Task 2 of
`docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md:422-486`. Spec defect **D-TOL**, executed early because it blocks G2's
readability.

## Ruling

**The BOUND is wrong. The code is right, and it is right for a reason: it is
a line-for-line mirror of shipped silicon.**

`3e-02` → **`8e-02`**, one constant and its derivation comment in
`ref/layer_fixed.py`. Nothing on the numeric path is touched, so this lands
under the plan's M1 rule (`plan:156-165`) while Task 1 (G1) is measuring
through that same file. **How it landed is itself a finding — see §7.**

And the framing the plan offered — "a 0.8B-tuned tolerance that legitimately
loosens with geometry" — is **not** what is happening, which matters because
the obvious fix (a per-geometry bound) would have encoded a false mechanism.
The block does not change with the geometry at all. `T` and `HD` are the same
at 0.8B, 2B, 4B and 9B; no head count enters the block. What changes is
**which random draw the block gets**, because the shared `rng` has been
advanced by `2·LR.H` normals by the `rmsnorm1p` check above it. `2.666e-02`
and `3.288e-02` are the same computation on two samples of a statistic whose
standard deviation is `6.7e-03`. The old bound sat *inside* that
distribution and false-failed **66 %** of the time.

## 1. Reproduction

Bit-identical to the committed baseline, twice, on a pristine
`git archive HEAD ref` tree unpacked on snoke (Task 1 was editing
`ref/layer_fixed.py` in the shared working tree throughout this task, so no
measurement here was taken from the working tree):

| tag | `attn softmax+pv` | verdict | matches |
|---|---|---|---|
| 0.8b | `rel=2.666e-02  bound=3e-02` | OK | `evidence/qwen_next/ladder/ref_selftests.log:131` |
| 2b | `rel=3.288e-02  bound=3e-02` | **FAIL** | `evidence/qwen_next/ladder/ref_selftests.log:371`, `evidence/qwen_next/ladder/head_baseline_layer_fixed_2b.log` |

Reproduced at `64e4b4e` (the commit the plan binds to) **and** at `4965057`
(Task 1's first G1 commit), with identical values — which is an independent
confirmation that Task 1's state-container law is inert for this check, as it
claims to be. `[D]`

## 2. Derivation — where `3.288e-02` comes from

### 2.1 The block does not move with the geometry

`ref/layer_fixed.py`'s attention stanza is `T, HD = 48, LR.HD`. Read from the
committed configs (`ref/qwen3_5_*_config.json`), by
`evidence/qwen9b/g2/dtol_probe.py --panels geom`:

```
    tag      H    HD   NQ  NKV  LNH  LNKH  LDK    T
   0.8b   1024   256    8    2   16    16  128   48
     2b   2048   256    8    2   16    16  128   48
     4b   2560   256   16    4   32    16  128   48
     9b   4096   256   16    4   32    16  128   48
```

`HD = 256` and `T = 48` at every geometry this campaign will ever run. The
block indexes **one** head; `NQ`, `NKV`, `LNH` and `LNKH` never enter it. The
plan asks for the score "at the head counts that differ" — the answer is that
the head counts are not an input, so **a bound that scales with head count
would be a fiction.** `[D]`

The one quantity that does move is `H`, and `H` is not an input to the block
either. It is an input to the **random number stream**: the `rmsnorm1p` check
twelve lines above draws `rng.normal(0, 2, LR.H)` and `rng.normal(0, 0.1, LR.H)`
from the same `np.random.default_rng(21)`.

### 2.2 Proof: a standalone replay with `H` as the only free parameter

`dtol_probe.py --panels replay` transcribes the block, replays only the four
prefix draws that precede it, and varies nothing but `H`:

```
  H=1024  (0.8b)  rel=2.666e-02
  H=2048  (  2b)  rel=3.288e-02
  H=2560  (  4b)  rel=4.041e-02
  H=4096  (  9b)  rel=3.918e-02
  -> reproduces the committed 0.8b/2b values exactly: YES
```

Both committed values fall out of a stream offset. That is the whole
geometry dependence. `[D]`

**The 9B row has zero degrees of freedom, and measurement then confirmed it.**
`panel_replay` hardcodes `HD, LDK = 256, 128` and `T = 48` and **never reads
the 9B config**; the only per-tag input is the literal `H`. So once the
`H = 1024` and `H = 2048` rows reproduce the two committed values, the
`H = 4096` row is fully determined — there is no parameter left to fit, and no
way to tune the answer toward a measurement. It is a derivation, not a
regression.

Measurement then agreed. `ref/layer_fixed.py` run at 9B on a
`git archive 64e4b4e` tree — the **pre-fix** state, bound still `3e-02` —
printed:

```
  attn softmax+pv        rel=3.918e-02  bound=3e-02  FAIL
```

`3.918e-02`, matching the derivation to every printed digit.
Log: `evidence/qwen9b/g2/prefix_9b_layer_fixed.log`. `[D]`

> **Dated correction, 2026-08-29 (review finding F3).** This paragraph
> previously claimed the 9B value was *predicted before it was measured*.
> **That temporal claim is withdrawn.** It may well be true of the working
> session, but it is not attested by anything committed — the committed
> artefacts' timestamps run the other way (sweep `18:12` → commit `18:17` →
> probe log `18:20`), so a reader has no way to check it. The zero-degree-of-
> freedom argument above is what the evidence actually supports, and it is the
> stronger claim in any case: it does not depend on the order in which two
> runs happened. **Commit message `f3da761` carries the superseded "PREDICTED
> before it was measured" wording** and cannot be amended (commits stack); this
> note supersedes it, as does the campaign-ledger entry.

Two consequences stand unchanged. **The old bound would have blocked 9B**: the
plan's requirement that this check "must not block 9B when its geometry
arrives" was not hypothetical — at `3e-02` the 9B geometry fails on arrival,
for the same non-reason 2B does. And **it was the only thing blocking it**:
that whole 9B run contains exactly two `FAIL` lines, this check and the
`LAYER_FIXED SELFTEST FAIL` summary it causes. Every other check in
`_selftest` — the DYNQ16 and EPS-NORM soaks, salience and GPTQ invariance,
`rmsnorm1p`, `rope`, `l2norm`, both DeltaNet checks, all four trajectory soaks
and the whole W8 section — already passes at 9B, untouched. `[D]`

### 2.3 What the error actually is

`dtol_probe.py --panels attrib` replaces one fixed-point stage at a time with
exact float (400 draws each):

| variant | mean `rel` | share of variance |
|---|---|---|
| full (as shipped) | `3.3307e-02` | — |
| **PV accumulation rounding only** | **`3.0565e-02`** | **84.2 %** `[S]` |
| V int8 KV cache only | `9.1050e-03` | 7.5 % `[S]` |
| K int8 KV cache only | `8.7818e-03` | 7.0 % `[S]` |
| fixed softmax only (`exp_neg_q`/`recip_q`/Q15 p) | `9.5285e-04` | 0.1 % `[S]` |
| everything except acc rounding | `1.3048e-02` | — |

Quadrature sum of the four isolated means: `3.3093e-02` against the full
`3.3307e-02` — **0.64 % apart.** The error budget closes. There is no
unexplained residual, which is the evidence that no defect is hiding under
the bound. `[D]`

The dominant term is the per-term round into `Q.QKV_F`:

```python
sh = 15 - ve - QKV_F
acc += rshr(term, sh) if sh >= 0 else term << (-sh)
```

Each of the `T` tokens carries its **own** power-of-two KV exponent `ve`, so
the terms cannot be accumulated before alignment; each is shifted and rounded
into the `Q.QKV_F` accumulator, and `T` half-LSB roundings accumulate.

### 2.4 The closed form, checked against measurement

```
rel  ~=  2^-QKV_F * sqrt(T/12)  /  ( sigma_v * sqrt( sum_t p_t^2 ) )
```

Numerator: `T` independent uniform `(-1/2, +1/2)` LSB errors per output dim,
so `sd = 2^-QKV_F * sqrt(T/12)`. Denominator: `ref_d = sum_t p_t v_td` with
`v ~ N(0, sigma_v^2)`, so `sd = sigma_v * sqrt(sum p^2)`. `_blk` divides
`max_d|err|` by `max_d|ref|`, and both are the maximum of `HD` iid zero-mean
Gaussians, so **the order-statistic factor cancels.**

`dtol_probe.py --panels law`, 600 draws:

```
  measured/predicted ratio: mean=1.015 sd=0.169  p5=0.769 p95=1.322
  order-statistic factor, numerator  max|err|/sd = 3.041 (sd 0.361)
  order-statistic factor, denominator max|ref|/sd = 3.035 (sd 0.357)
```

`3.041` vs `3.035` — the cancellation is real, not asserted. `[D]`

Two consequences, both measured rather than argued
(`dtol_probe.py --panels scale`):

- **`HD`-independent.** `HD = 64/128/256/512` give mean `rel` of
  `3.357e-02 / 3.435e-02 / 3.401e-02 / 3.380e-02`. `[D]`
- **Grows with `T`**, and faster than `sqrt(T)`, because the numerator rises
  as `sqrt(T)` while the denominator falls as `1/sqrt(T_eff)` — the softmax
  spreads over more tokens. `T = 32/48/64/128/256` give
  `2.35e-02 / 3.40e-02 / 4.19e-02 / 7.46e-02 / 1.457e-01`; `rel/T` is
  `7.35 / 7.09 / 6.55 / 5.83 / 5.69` (×`1e-4`), i.e. very nearly linear. `[D]`

**The residual spread is `sum_t p_t^2`** — the softmax peakiness of the one
draw the selftest happens to take. That is the whole reason the statistic
moves, and no bound on a single draw can make it stop moving.

### 2.5 The distribution, and what `3e-02` really was

`dtol_probe.py --panels mc --mc-draws 40000`, four seeds × 10 000 draws of the
identical block:

```
  pooled n=40000  mean=3.3030e-02  sd=6.681e-03  min=1.213e-02  max=6.749e-02
  quantiles: p1=1.906e-02  p5=2.282e-02  p25=2.841e-02  p50=3.258e-02
             p75=3.715e-02  p90=4.175e-02  p95=4.470e-02  p99=5.078e-02
             p99.9=5.842e-02
  P(rel >= 3e-02) = 0.6626
```

Per-seed `P(>=3e-02)` was `0.664 / 0.662 / 0.660 / 0.664` — stable across the
four seeds the campaign requires. `[D]`

**`3e-02` was the 34th percentile of the statistic it was bounding.** 0.8B's
`2.666e-02` is a `p25`-ish draw; 2B's `3.288e-02` is a `p51` draw. The check
was a coin flip weighted 2:1 against passing, and it has been failing for the
2B geometry for exactly that reason.

## 3. Why the code is not wrong

The host model's per-term round is not a modelling choice that could be
tightened. It is what the shipped RTL does, gate for gate:

Four correspondences. Each RTL line is quoted and cited; the host line
beside it is the one named in the §2.3 code block above.

1. the product. Host: term = p[t] * v8.
   `rtl/attn_core.sv:213` — `pv_p[d] <= 26'(33'(p_t_r[d/64]) * 33'(signed'(kv_data[d*8 +: 8])));`
2. the shift amount. Host: sh = 15 - ve - QKV_F, with QKV_F = 8.
   `rtl/attn_core.sv:461` — `shamt_q <= 4'(8'sd15 - ve_q - 8'sd8);   // in [6,15]`
3. the rounding. Host: rshr, i.e. round-half-away-from-zero.
   `rtl/attn_core.sv:462` — `vadd_q <= 15'(16'd1 << (4'(8'sd15 - ve_q - 8'sd8) - 4'd1));`
   and `rtl/attn_core.sv:215-220` adds that addend to the **magnitude**, shifts,
   and restores the sign — which is precisely what `rshift_round` does in
   `ref/w4a8_ref.py:90-99`.
4. the accumulation. Host: acc += the shifted, rounded term.
   `rtl/attn_core.sv:224` — `acc[d] <= 40'(acc[d] + 40'(pv_s[d]));`
   The 40-bit accumulator adds a term that has **already** been shifted and
   rounded; it never sees the full-precision product.

`ve_q <= kv_exp` is re-registered per token (`rtl/attn_core.sv:457`), which is
the architectural reason the rounding cannot be deferred to the end of the
sum.

**Scope of "line-for-line", stated so it is not read wider than it is.** The
host line is `acc += rshr(term, sh) if sh >= 0 else term << (-sh)`, and **the
`else` branch has no RTL counterpart at all**: `rtl/attn_core.sv:175` declares
`logic [3:0] shamt_q` — a 4-bit **unsigned** field, commented *"in [6,15]"* —
which cannot express a negative shift. That is not a gap in the mirror, it is
dead host code. `sh = 15 - ve - QKV_F` with `ve = e - QKV_F` reduces to
`sh = 15 - e`, and `e` is `dyn_quant_i8`'s minimal shift for an **int16**
input, so `e ∈ [0, 9]` (at `m = 32767`: `e = 8` gives `(32767+128)>>8 = 128 >
127`, so `e = 9`) and therefore **`sh ∈ [6, 15]`** — exactly the range the RTL
comment claims, and never negative. The `else` branch would need `e > 15`,
i.e. `|v| ≥ 127·2^15`, which no int16 can reach. The correspondence is
line-for-line **over the reachable domain**; the unreachable branch is
unmirrored by construction.
**Changing the host model here would put it out of step with the bitstream
now serving the 2B**, which is the opposite of a fix. `[D]`

## 4. Choosing `8e-02`

`dtol_probe.py --panels damage --damage-draws 3000` injects five realistic
defect classes and scores detection at candidate bounds:

```
  detection probability P(rel >= bound), by candidate bound:
        3e-02      5e-02      6e-02      7e-02      8e-02      1e-01   defect
       1.0000     1.0000     1.0000     0.9993     0.9953     0.9690   trunc
       0.9970     0.8137     0.5323     0.2360     0.0750     0.0043   acc_f_m1
       1.0000     1.0000     1.0000     1.0000     1.0000     1.0000   no_maxsub
       1.0000     1.0000     1.0000     1.0000     1.0000     1.0000   scale_hd
       1.0000     1.0000     1.0000     1.0000     1.0000     1.0000   p_shift
       0.6523     0.0147     0.0010     0.0000     0.0000     0.0000   HEALTHY   <- FALSE-FAILURE rate
```

| mode | what was injected | mean | min |
|---|---|---|---|
| `trunc` | PV accumulation truncates instead of rounding (`>>` vs `rshr`) | `1.492e-01` | `6.836e-02` |
| `acc_f_m1` | accumulator carries one fewer fraction bit | `6.146e-02` | `2.699e-02` |
| `no_maxsub` | softmax forgets the running-max subtraction | `6.352e-01` | `2.565e-01` |
| `scale_hd` | score scale `1/HD` instead of `1/sqrt(HD)` | `7.073e-01` | `3.355e-01` |
| `p_shift` | off-by-one in the Q15 probability shift | `5.000e-01` | `4.652e-01` |
| `HEALTHY` | nothing | `3.299e-02` | max `6.197e-02` |

`8e-02` is:
- **`2.42×` the measured central value** and **`1.19×` the largest of the
  43 000 healthy draws taken here** (40 000 MC + 3 000 damage-panel HEALTHY;
  pooled max `6.749e-02`); `mean + 7.0 sd`. `[D]`
- a false-failure probability of order **`1.5e-07` per invocation** `[E]`,
  extrapolating the measured tail (`p99.9 = 5.842e-02`, empirical max
  `6.749e-02` at `p ≈ 2.5e-05`, i.e. `0.57e-02` per decade of tail
  probability).
- still refusing every structural defect measured at **100 %**, and
  truncation-instead-of-rounding at **99.5 %**.

**The `7e-02` alternative, and what choosing `8e-02` gives up.** Stated
plainly, because the give-up falls on the exact class this ruling declares the
check blind to:

| | `7e-02` | `8e-02` (chosen) |
|---|---|---|
| measured false-failure, 3 000 healthy draws | `0.0000` | `0.0000` |
| extrapolated false-failure `[E]` | `~9e-06` | `~1.5e-07` |
| headroom over the largest of 43 000 healthy draws | `1.04×` | `1.19×` |
| `trunc` detection | `0.9993` | `0.9953` |
| **`acc_f_m1` detection** | **`0.2360`** | **`0.0750`** |

At the **measured** false-failure rate the two are indistinguishable — both
zero in 3 000 draws — and `7e-02` detects `acc_f_m1` **`3.1×` better** on the
very class §4 calls the blind spot. The case for `8e-02` is therefore
**entirely the `[E]` tail-margin argument**: `7e-02` sits only `1.04×` above
the largest healthy draw ever observed and extrapolates to `~60×` more
likely to repeat this very incident. That is a judgement about which error is
more expensive — a false failure blocks a gate and costs an investigation, and
is what cost this campaign the task you are reading — and **not** a claim that
`8e-02` detects better. On `acc_f_m1` it detects **worse**, by `3.1×`, and a
reader who weighs a flaky gate more cheaply than this document does is
entitled to re-take the trade from the table above.

### What the new bound does and does not admit

Because this changes a *tolerance*, which is a claim about what "correct"
means, in full:

**It admits** the block's own arithmetic noise at every geometry — the
`Q.QKV_F` per-term rounding of a `T = 48` PV accumulation, the int8 KV cache
on both K and V, and the PWL `exp_neg_q`/`recip_q` — across the full observed
range of softmax peakiness, at `HD` from 64 to 512 and at every `H` in
`{1024, 2048, 2560, 4096}`.

**It refuses**, at 100 % of draws: a missing softmax max-subtraction, a
`1/HD`-for-`1/sqrt(HD)` score scale, and an off-by-one in the probability
shift. At 99.5 %: truncation where the RTL rounds.

**It does NOT refuse** a one-bit narrowing of the PV accumulator
(`acc_f_m1`, detected on only 7.5 % of draws) — and **no bound catches that
class reliably**: the defect's minimum (`2.699e-02`) is below the healthy
median (`3.258e-02`), so no threshold separates the two distributions. It is a
matter of degree rather than of possibility, and the degree is measured:
`6e-02` reaches **53 %** detection at a `1.0e-03` false-failure rate, `5e-02`
reaches **81 %** at `1.47e-02`. Both buy partial coverage of one class with a
flaky gate, which is the trade §4 declines — but they are on the table and the
numbers are above.

This is a property of the check, not of the number, and `trunc` shows the same
shape more mildly: its minimum (`6.836e-02`) is only `1.3 %` above the healthy
maximum (`6.749e-02`). **The healthy and damaged distributions overlap in
their tails**, so a single-draw max-relative-error statistic cannot be a
precision gate at any constant. Fixing that needs a different statistic, not a
different number — §8.2.

**What else covers that class — stated narrowly, because the obvious answer
is wrong.** An earlier draft of this document claimed `tb/tb_attn_core.sv`
catches an accumulator narrowing bit-exactly. **That claim was false and is
withdrawn** (2026-08-29, review finding F1). Two independent reasons:

1. **The golden is frozen.** `tb/Makefile:399`'s `tb_attn_core:` target has no
   prerequisites and no recipe line that regenerates vectors — it compiles and
   replays `vectors/s1`…`s4`. Nothing in `tb/Makefile` invokes
   `ref/gen_layer_vectors.py` at all. `tb/vectors/s1/attn_acc.hex` was last
   written on **2026-06-12 by `5d28637`**, and the freeze is deliberate:
   `tb/Makefile:285-286` — *"tb/vectors/ stays frozen, so every pre-existing
   unit case replays byte-identical inputs"*. A host-model change cannot move
   a file nothing rewrites.
2. **Even regenerated, it would not see a layer_fixed-local change.**
   `ref/gen_layer_vectors.py:116-120` is the **third** transcription of this
   accumulation (§8.1), not a call into the model — it never invokes
   `attn_decode_fx` or the `_selftest` stanza. What it does share is the
   **constants and the helpers**: `LF.QKV_F`, `LF.kv_quant`,
   `fp.exp_neg_q`/`fp.recip_q`, and `w4a8_ref.rshift_round`. So a change to
   any of *those* propagates and would be caught; a change to the
   shift-round-accumulate arithmetic **written out separately in each of the
   three copies** does not propagate and would not be.

The true coverage, split by where the fraction bit is lost:

| change | covered by |
|---|---|
| the shared constants and helpers (`QKV_F`, `kv_quant`, `exp_neg_q`, `recip_q`, `rshift_round`) | `tb/tb_attn_core.sv`, **bit-exactly, but only after the goldens are regenerated** — the generator calls them, so its output moves and the exact compare fails |
| the transcribed loop in `attn_decode_fx` (the **live** path) | surfaces as a host↔RTL mismatch in Task 11's G4a replay and Task 12's census, because the RTL is unchanged and still mirrors the pre-change host; and it is where `ref/fidelity_check.py` would show a moved metric |
| the transcribed loop in the `_selftest` stanza (**test-only**) | **nothing but this check** — and this check is blind to it at 7.5 %. A bit lost there is a defect in the test's fidelity to the model, not in the model, but it would silently weaken the only host-side guard the block has |

So the rail this constant provides is a **gross-error rail on the reference
model**, and it is now correctly sized to be exactly that. It is not, and
after this ruling does not pretend to be, a precision gate — and the row above
that reads "nothing but this check" is the honest residual, not a rhetorical
flourish. Wiring the goldens to their generator is on the handed-back list
(§8.4).

## 5. Sweep — before and after, three geometries

Runner: `evidence/qwen9b/g2/run_ref_selftests_9b.sh`, a fork of
`evidence/qwen_next/ladder/run_ref_selftests.sh` with `9b` added as a third
tag. **The ladder runner was not edited and its default log was not
written** — it is Track L's committed evidence, and
`evidence/qwen_next/ladder/LADDER.md` §6.10 cites
`evidence/qwen_next/ladder/ref_selftests.log:515` and
`evidence/qwen_next/ladder/ref_selftests.log:541` by line. `LOG` is
overridden to `evidence/qwen9b/g2/ref_selftests_dtol.log` (plan `:456-463`).

The `rel` values below are unchanged by this task — only the bound they are
compared against moved, so the "before" column is the same measurement:

| tag | `attn softmax+pv` | vs `3e-02` (before) | vs `8e-02` (after) | margin |
|---|---|---|---|---|
| 0.8b | `2.666e-02` | OK | OK | `3.00×` |
| 2b | `3.288e-02` | **FAIL** | OK | `2.43×` |
| 9b | `3.918e-02` | **FAIL** (measured on the pre-fix tree) | OK | `2.04×` |

So the fix does not merely un-break 2B: it removes a failure the 9B geometry
would have hit on its first run, at a bound that had nothing to say about
either.

Full three-tag sweep: `evidence/qwen9b/g2/ref_selftests_dtol.log` — 21
invocations, 7 modules × 3 tags, run on the staging tree
(`4965057` + this task's hunk, `md5 16310d33…`, recorded in the log's own
`=== md5:` header).

**And confirmed again at the tree that actually exists.** HEAD moved three
times while this task ran — `4965057` and `379475f` (Task 1's G1 commits, the
second of which carries this hunk; see §7), then `f3da761` (this task's
evidence commit, which changes no `ref/` file, so `379475f` and `f3da761`
share a `ref/` tree). `ref/layer_fixed.py` was re-run at **`f3da761`**
(`ref/layer_fixed.py` md5 `257eac2d7940f02726ea0ad9f3101cf7`) on a
`git archive` tree, both shipped geometries, `OMP_NUM_THREADS=3`:

```
  attn softmax+pv        rel=2.666e-02  bound=8e-02  OK     LAYER_FIXED SELFTEST PASS   (0.8b)
  attn softmax+pv        rel=3.288e-02  bound=8e-02  OK     LAYER_FIXED SELFTEST PASS   (2b)
```

Log: `evidence/qwen9b/g2/head_08b_2b_layer_fixed.log`.
**The 2B `layer_fixed` selftest passes on `main` for the first time**, which
is the state this task was asked to reach. `[D]`

> **Dated note, 2026-08-29 (review finding F3).** Both this row and the
> pre-fix 9B row in §2.2 were originally quoted from runs whose logs were
> **not committed** — the same shape as the `a9d06ca` retraction. Both have
> been re-run from `git archive` trees and their logs committed, which is what
> the two paths above are. Both re-runs reproduced the originally quoted values
> exactly.

A caveat stated rather than hidden: HEAD is a moving target while G1 runs, so
"the sweep is green" is a claim about the trees named above and not a standing
one. Task 3 (G2a) re-runs the same three-tag sweep as one of its own exit
conditions (`plan:792-795`), and that is where it becomes current again.

## 6. Provenance

- Host **snoke** for every numeric run (`OMP_NUM_THREADS` pinned and recorded
  in each log header). darthplagueis was used only for editing and git.
- Interpreter: `uv run --no-project --with numpy [--with torch --with
  transformers] python`, the form the plan's standing-hazards note prescribes
  (`plan:120-125`). numpy `2.5.2`.
- All measurement ran on trees unpacked from `git archive HEAD ref`, never on
  the shared working tree, because Task 1 was editing `ref/layer_fixed.py`
  concurrently. The sweep tree is `4965057` plus **exactly one hunk** — this
  task's bound and its comment — md5
  `16310d33657beb539f8c6a3e59a9a68c` for `ref/layer_fixed.py`, recorded in
  the sweep log's `=== md5:` header line.
- `evidence/qwen9b/g2/dtol_probe.py` is the committed script every `[D]`
  number here comes from, and its `replay` panel reproduces the two committed
  values before any new number is quoted — the plan's `[D]` label condition.
  Its consolidated run is `evidence/qwen9b/g2/dtol_probe.log` (+ `.json`).
  **The probe emits its own provenance header** — host, date, python/numpy,
  and the md5 of every file it actually reads (`ref/fixedpoint.py`,
  `ref/w4a8_ref.py`, the four config JSONs, and itself). It deliberately does
  **not** record an `ref/layer_fixed.py` md5: it never imports that file, the
  block under test is transcribed into the probe, and an earlier version of
  this log carried such an md5 as decoration alongside a stale tree label
  (2026-08-29, review finding F3).
- **Every headline measurement now has a committed log**, and each was produced
  by the committed runner on a `git archive` tree of the commit it names:
  - `evidence/qwen9b/g2/ref_selftests_dtol.log` — the 21-invocation three-tag
    sweep, staging tree `4965057` + this task's hunk.
  - `evidence/qwen9b/g2/prefix_9b_layer_fixed.log` — the pre-fix 9B row of
    §2.2, tree `64e4b4e`, `MODULES=layer_fixed TAGS=9b`.
  - `evidence/qwen9b/g2/head_08b_2b_layer_fixed.log` — the at-HEAD
    confirmation of §5, tree `f3da761`, `MODULES=layer_fixed TAGS="0.8b 2b"`.
  `MODULES` and `TAGS` are overrides on
  `evidence/qwen9b/g2/run_ref_selftests_9b.sh`; `MODULES` exists so a single
  module can be re-measured on an old tree without paying for a full sweep.
- **`ref/layer_fixed.py` is cited by ANCHOR TEXT, not by `path:NNN`**, in this
  document and in the probe. Task 1 moved every line in that file twice
  during this task (`_selftest`'s `_blk` call went `ref/layer_fixed.py:2151` →
  `ref/layer_fixed.py:2438` in one
  commit); a line citation into a file another task is actively editing is a
  citation that will be wrong by the time it is read. Every other citation
  here — `rtl/attn_core.sv`, `ref/gen_layer_vectors.py`, the plan, the ladder
  logs — is to a file no live task is editing, and those stay by line.

### Labels

`[M]` measured on this board — none, this is a host-only task.
`[D]` computed by a committed script that reproduces a committed number first
— every figure in §1, §2 and §4. The script is `evidence/qwen9b/g2/dtol_probe.py`; the committed
numbers it reproduces first are `2.666e-02` and `3.288e-02`.
`[T]` toolchain-measured on real RTL — none. **§3's host/RTL correspondence
is not `[T]`**: it is a source-to-source reading of `rtl/attn_core.sv`, cited
by line so it can be checked by eye. No simulation was run for it, and the
claim it supports is about what the RTL *says*, not what it measured.
`[E]` extrapolated — the `~1.5e-07` and `~9e-06` false-failure rates in §4,
which are tail extrapolations from 43 000 draws and are **not** measured; the
measured statement is only "zero false failures in 43 000 draws".
`[S]` this document's arithmetic — the variance shares in §2.3 (squares of
measured means) and the multiples in §4. Nothing here is deferred to a later
gate for measurement.

## 7. The M1 rule has a hole, and it opened during this task

**The hunk landed inside Task 1's commit `379475f`, not inside a D-TOL
commit.** Recorded here because the commit message does not say so, and
because the mechanism is a live hazard for the rest of the campaign.

What happened, in order. Both tasks write `ref/layer_fixed.py` in one shared
working tree. This task made its one-hunk edit immediately after a
`git diff --stat` showed the file clean (Task 1 had just committed
`4965057`); by the time the edit was diff-verified moments later, Task 1 had
further numeric-path edits in the same file. Task 1 then committed with
`git commit -m … -- ref/layer_fixed.py` — and a **pathspec commit takes the
WORKING-TREE content of the named path**, so it carried this task's tolerance
hunk along with its own work. Verified: the hunk is present in `HEAD`
byte-identical to what was written here, and `ref, 3e-2)` no longer occurs
anywhere in the file.

**The plan's rule does not prevent this.** `plan:163-165` says both tasks
"commit **named files only**, never a directory that could sweep the other's
work" — which defends against a *directory* pathspec. It has nothing to say
about two tasks naming the **same file**, and against that a file pathspec is
not a defence but the mechanism itself: `git commit -- <path>` ignores the
index and snapshots the worktree.

**No history was rewritten in response.** The Global Constraints say commits
stack and are never amended, and rewriting a concurrently-running gate's
commit would be far worse than the provenance gap it would fix. The record
lives here and in **the campaign ledger,
`.superpowers/sdd/2026-08-29-qwen35-9b-migration/progress.md`** — named by
path on purpose. **"The ledger" is ambiguous in this campaign**: the spec at
`docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md:24` gives
that name to a *different* file, `.superpowers/sdd/2026-08-25-qwen-next-derisking/progress.md`
(the de-risking ledger), which carries none of this. An earlier draft of this
document said only "the ledger" and sent a reviewer to the wrong file
(2026-08-29, review finding F2). Both ledger files are gitignored
(`.superpowers/sdd/.gitignore`), so neither appears in any commit — which is
the more important half of the warning. Disambiguating the spec's naming is on
the handed-back list (§8.3).

**The substance of M1 held, and this is the part that matters for G1.** The
swept hunk is a tolerance constant and a comment inside `_selftest`. It is
not on the numeric path, `ref/fidelity_check.py` never reads it, and it
cannot move a G1 measurement. **No numeric-path change from this task landed
under G1's feet, and none is proposed to** — the two numeric-path items this
task found are in §8 and are explicitly handed on rather than landed.

**It could have gone the other way, and that is the warning.** Had the timing
reversed — this task committing `-- ref/layer_fixed.py` while Task 1 had
uncommitted numeric-path edits — a commit labelled "tolerance-only" would
have carried a state-container change into main and destroyed G1's
single-variable premise at the campaign's one STOP gate. That did not happen
only because the file was polled for a clean window before every commit
attempt, and because when the window never opened, this task committed **no
code path at all** and let the sweep run from a staging tree instead. For the
remaining tasks that share a file with a live gate: **poll `git diff --stat`
on the shared file immediately before committing it, and if it is dirty with
another task's work, do not commit that path.**

## 8. Not established / handed on

1. **The PV block is transcribed three times.** `attn_decode_fx`'s
   `acc_QKV_F = sum_t rshr(p[t]*v8, 15 - ve)` loop, the `# attention core:
   identical KV content, T=48` stanza in `_selftest` (both in
   `ref/layer_fixed.py`, cited by anchor — see the note under §6), and
   `ref/gen_layer_vectors.py:116-120` each carry their own copy of the same
   accumulation. That is a live
   duplication hazard for a geometry migration — a change must be made in
   three places or the golden generator and the model disagree. Not fixed
   here: de-duplicating it is a **numeric-path** change and the M1 rule
   forbids landing one while G1 is running. Recorded for whoever sequences
   the numeric-path work after G1.
2. **The check is a one-draw statistic and could be made a mean of a few
   draws**, which would cut the spread by `sqrt(n)` and let the bound be
   genuinely tight — the only way to close the `acc_f_m1` hole in §4. Not
   done, for two reasons: it edits `_selftest`, which is a code change under
   G1's feet; and `_w8_invariance`'s contract in `ref/layer_fixed.py`
   (*"everything the W4 sections print above is a byte-identical prefix of
   this log"*) means changing the rng stream
   would move every printed number below it. Any future attempt must budget
   for that.
3. **Three committed documents describe this defect with a mechanism this
   ruling disproves, and one of them would have led a reader to the wrong
   fix.** The spec's D-TOL row
   (`docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md:2571`)
   calls it *"a 0.8B-tuned bound the 2B geometry overshoots by 9.6 %"* and
   still carries the status `open, unowned`;
   `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md:2573`
   repeats the framing.
   <!--cites:noquote-->
   *(**POINTER REPAIR, 2026-09-10, pre-ship tool chore.** Those two numbers
   were line 1796 and line 1529 until today (written here as prose, not as
   citations: they name a tree that has moved on), and both were wrong IN
   MEANING — not stale by a few lines but pointing at unrelated sections.
   Line 1796 had become the G5a URAM/SLR paragraph, line 1529 the matvec w8
   removal
   list. They were renumbered faithfully by successive
   `evidence/qwen9b/o3/o3_cite_drift.py` passes, which is exactly what a mechanical renumber does to a citation
   whose target has been REWRITTEN rather than moved — the tool maps the
   line, not the claim. Repaired to the two places the framing actually
   lives at HEAD:
   `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md:2571`
   is the D-TOL row and
   `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md:2573`
   opens the **D-TOL CORRECTION (2026-08-31)** block, into which the §4.3
   `ref/layer_fixed.py` prose that used to repeat the framing was folded.
   TWO CLAUSES ABOVE ARE NOW HISTORICAL AND ARE LEFT AS WRITTEN, because
   this section records the state at the ruling: the row's strikethrough
   and its `CORRECTED 2026-08-31` marker, and its status moving from
   `open, unowned` to `CLOSED 2026-08-29 at G2 (Task 2)`, are this very
   ruling being taken up by the spec.)*
   **There is no 9.6 % geometry overshoot** — §2 shows the block is identical
   at all four geometries and the two values are two draws of one random
   variable, so a reader following that row would reach for the per-geometry
   bound §2.1 shows to be a fiction. Not edited here: the spec is **not** in
   this task's `Files` list (`plan:424-428`), and Task 3 already names it as a
   modify target, so the dated supersession note belongs in that pass. Two
   further mentions are Track L's committed evidence and were accurate when
   written — `evidence/qwen_next/ladder/LADDER.md:404` and `:462`, and
   `evidence/qwen_next/ladder/CHECKPOINT_VERIFY.md:240` — and by house style
   take dated notes rather than silent edits, if they are touched at all.
   **Add to the same spec pass:** `…-design.md:24` calls
   `.superpowers/sdd/2026-08-25-qwen-next-derisking/progress.md` *"the
   ledger"*, but this campaign keeps its own at
   `.superpowers/sdd/2026-08-29-qwen35-9b-migration/progress.md`. One
   unqualified name for two files sent a reviewer of this very document to the
   wrong one (§7). The spec should name both by path and say which is which.
   Both are gitignored, so neither is recoverable from git history if lost.
4. **`tb/vectors/*/attn_acc.hex` has no wiring to its generator, and the
   review round showed that gap is easy to mistake for coverage.** The goldens
   were written on 2026-06-12 by `5d28637`; `ref/gen_layer_vectors.py` can
   still produce them but **no Makefile target invokes it**, so `make -C tb
   tb_attn_core` proves the RTL still matches a **2026-06-12 snapshot of the
   host model**, not the host model. That is a defensible freeze — `tb/Makefile:285-286`
   chose it deliberately so pre-existing unit cases replay byte-identical
   inputs — but it means the shared-constant coverage claimed in §4 is
   **conditional on a regeneration step that nothing runs**. Two things are
   wanted, and neither is this task's to land (`tb/` is outside Task 2's
   `Files` list, and the wider fix touches the numeric path): a `make` target
   or gate that regenerates the attention goldens and diffs them, so a moved
   `QKV_F` is caught rather than merely catchable; and a decision on whether
   the freeze should be lifted for this vector set specifically. Note the
   interaction with §8.1: while `ref/gen_layer_vectors.py` remains a **third
   transcription** rather than a call into the model, even a regenerated golden
   covers only the shared constant. **Both should be sequenced together** —
   de-duplicating the transcription first, wiring the regeneration second —
   because doing the second alone would buy a smaller guarantee than its
   presence suggests.
5. **`T = 48` is the selftest's literal, not the model's context length.**
   §2.4 shows `rel` is very nearly linear in `T`, so this bound is a
   statement about `T = 48` and nothing else. It is not a bound on the
   attention error at a real context length, and no gate document should
   quote it as one.
