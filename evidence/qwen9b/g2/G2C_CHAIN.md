# G2c — the 9B artifact chain: goldens, GPTQ at scale, images, fit

Gate document for Task 5 of
`docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md` (Task 5 at
`docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md:952`), spec
`docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md` §7.2.
Campaign ledger: `.superpowers/sdd/2026-08-29-qwen35-9b-migration/progress.md`
(**LOCAL-ONLY** — `.superpowers/sdd/.gitignore` ignores it, so a fresh clone
will not have it; the committed equivalents are this file and the other gate
docs under `evidence/qwen9b/`).

Host only. **No `rtl/`, no `synth/`, no board.**

---

## 0. Verdict

**DONE WITH ONE HALT.** Six of the gate's seven products are measured and
recorded. The seventh — **the emitted 9B image set itself** — is a
**HALT-and-report**: `ref/gen_model_script.py` cannot emit a 9B artifact set,
because `Mach.dump_weights` packs only the wids `Mach.matvec` registered and
`Mach.matvec` is reached only from a token body that five SEQ_ISA v1.7 ARG
fields refuse. §4 demonstrates the refusal at the ratified operating point and
names the task that widens each field. **Nothing was relaxed to get past it.**

| product | state |
|---|---|
| the untied-head producer sites | **DONE**, four sites, both frozen byte-gates green (§2) |
| the 9B bf16 torch golden | **VERIFIED by sha256, not rebuilt** (§3) |
| the 24.06 GiB GPTQ Hessian | **VERIFIED by sha256, not rebuilt** (§3) |
| the 249-image W4 g128 pack, on disk | **HALTED** — the emitter refuses at 9B (§4) |
| the per-channel `plan_weights` fit | **MEASURED** [D], every projected figure reproduced (§5) |
| the LM head's packed footprint | **MEASURED** [D] — 524,451,840 B = 500.2 MiB (§5) |
| both range tools at 9B | **RUN**, clean-with-attention, forked/fixed as needed (§6) |
| `RS_F = 7` under `int16` (A1.8) | **MEASURED, REPEATED, AND NOW ADOPTED BY USER RULING (2026-09-01).** 98/108 vs the baseline's 95/108, rank max 5 both, 0 clips vs 23, repeat byte-identical (§7.3). **The 9B operating point is `int16` + `RS_F = 7`.** This gate still changed no code; the work the ruling re-opens is routed in **§13**. |
| the re-derived chat template | **DONE** (§8) — and the finding is *the wrapper does not move* |

> ## USER RULING, 2026-09-01 — `RS_F = 7` IS ADOPTED
>
> **The 9B operating point is `int16` + `RS_F = 7`.** O5's condition was met
> and exceeded on the repeat-confirmed **98/108** (§7). A1.8's *"`RS_F` stays
> 8"* is superseded by the ruling; the spec and plan are being amended by a
> separate docs-only task and **are not touched here**.
>
> **This gate remains code-unchanged.** It measured the number and it does not
> implement the ruling: `rtl/conv4_silu.sv:50` still reads `9`, the host
> constants still read 8, and no 9B artifact carries `rs_f: 7` yet, because
> none exists (§4). **§13 is the disposition** — what moves, what must
> deliberately NOT move, and who owns each.

---

## 1. Provenance

Every numeric step ran through `evidence/qwen9b/run.sh`, which refuses to
overwrite an existing log and stamps host, date, tree sha + dirty flag, the
command, a per-host `test -x` interpreter probe, `nproc --all` and the thread
pinning into every log.

- **Host:** snoke for every numeric run (`nproc --all` = 48, 247 GiB).
  darthplagueis was used for editing, `git`, and the pure-arithmetic fit tool
  only — it is excluded from numeric compute until it passes a memtest soak.
- **Interpreters,** both `test -x`-probed and recorded in every header:
  `/home/cah/.venv/bin/python` (3.12.3, torch 2.12.0+cpu, safetensors 0.8.0)
  for the byte gates and the guard suite; `uv run --no-project --with torch
  --with transformers --with numpy python` for every 9B numeric run.
  `ref/.venv/bin/python` is **ABSENT on snoke** (a dangling symlink into a
  host-local `$HOME`) and every log says so.
- **Thread pinning** is in every header.
- **The tree label is not the provenance handle for a quantization run; the
  source digest is** (G1's rule). Every 9B fidelity run prints its
  `src_sha256` over `ref/fidelity_check._WQ_SOURCES`.

---

## 2. Step 1 — the untied-head producers: four sites, and one more the plan did not name

The study counted six producer sites; Track L had already done two
(`ref/perplexity_eval.py`, `ref/fidelity_check.py`). **Four remained**, and
each is one variable assignment:

| # | site | before | after |
|---|---|---|---|
| 1 | `ref/gen_model_script.py:527` | the head came from `md["emb"]` | `head_f = md["head"]` |
| 2 | `ref/seq_chat.py:1391` | `GMS.quant_linear_big(md["emb"], …)` | `GMS.quant_linear_big(md["head"], …)` |
| 3 | `sw/infer.py:707` | the head came from `md["emb"]` | `head_f = md["head"]` |
| 4 | `ref/audit_ranges.py:534` | §2b audited `embed_tokens` | `head_w = emb if TIED else st.get(HEAD_KEY)` |

`load_qwen35.load_model()` already returns `head`, `tied` and `head_key`
(Track L), so **`ref/load_qwen35.py` needed no change and is not in this
gate's commit** — the same disposition G2a recorded for `ref/calib_stats.py`.

**Why this is a silent-wrong-answer class and not a tidy-up.** At 0.8B / 2B /
4B `tie_word_embeddings` is true and `load_model` hands back an independent
float COPY of the embedding table as `md["head"]`, so all four sites are
byte-identical to what they did before — which the two byte gates in §9 prove
rather than assert. At 9B the flag is **false**: `lm_head.weight` is a
different 1,017,118,720-parameter tensor that lives OUTSIDE the
`model.language_model.` prefix. Reading `md["emb"]` there would have quantized
the **embedding table** as the LM head and produced a complete, plausible,
wrong image set. Nothing would have raised.

### 2.1 Two more sites, found while doing the four

**(a) `ref/audit_ranges.py` read only the first shard.** `ref/audit_ranges.py`
opened the checkpoint with `LQ.find_checkpoint()` — the FIRST SHARD ONLY, as
that function's own docstring says at `ref/load_qwen35.py:108-113`: *"callers
that read tensors want `find_checkpoints` / `SafeTensors`, which take the whole
shard list."* 0.8B and 2B are single-shard, so the tool was right everywhere it
had ever run; 4B has two shards and 9B four, and layer 0's DeltaNet tensors
live in a later one. G1 could only run it at 9B by forking it under `runpy`
with `find_checkpoint` patched
(`evidence/qwen9b/g1/audit_ranges_9b.py`).

**G2a did not fix this** — `ref/audit_ranges.py` is in G2a's file list but its
checkpoint open was not on G2a's census — so this gate fixed it **at the call
site**, `ref/audit_ranges.py:291`, and not in `find_checkpoint`: that function
is deliberately first-shard-only for callers that want the snapshot
*directory*, and changing it would have been the wrong fix in the right file.
`ref/audit_ranges.py` now runs at 9B unforked (§6).

The other tool, `evidence/qwen2b/q2/audit/gate_port_probe.py`, has the same
defect and is **Track Q's committed evidence**, which this campaign does not
edit in place. It is run through G1's `runpy` fork, unchanged.

**(b) `ref/calib_stats.py`'s `isinstance` filter could double the head's
statistics.** The plan predicted a collision here and it is real, though not
in the way the wording suggests. `HEAD_KEY = "lm_head"` is claimed by a hook on
the FINAL NORM's output, because the head is not a submodule of the text model
in either tie mode — `perplexity_eval.build_model` returns `(model, head_w,
acct)` and computes `hs @ head_w.T` by hand, exactly as the hardware does. An
`nn.Linear` whose stripped name is also `lm_head` would register a **second**
hook on the same key, and both would fire on the same forward with the same
vector.

**The two accumulators behave differently under that, and an earlier revision
of this section got it wrong** *(corrected 2026-08-31 at the T5 review, which
caught it)*:

- the **salience** (`Collector.sum`) is a bare `+=` in `_acc`, so it would come
  out **doubled, silently** — a factor of two on every `lm_head` weight the
  salient quantizers touch;
- the **Hessian** is **already safe**: `_hess_acc` keys on
  `(step, data_ptr, shape)` and returns on the second call with the same
  tensor, or raises if two members of one site are handed different tensors.

So the exposure is the salience half only — which is still silent, and still
enough. It does not happen with the current `build_model`. It now **refuses**
at `ref/calib_stats.py:313` rather than depending on that staying true, and
the docstring that said "the synthetic key `lm_head` for the tied head" now
says why the key is synthetic in **both** tie modes.

`ref/calib_stats.py` also now prints the shard count and the tie mode in its
provenance block, so a Hessian's log says on its face which head it was
collected for.

### 2.2 The quantizer source digest moved, and the quantized weights did not

`ref/fidelity_check._WQ_SOURCES` hashes nine `ref/` files, and G2a edited two
of them (`ref/layer_fixed.py`, `ref/gen_model_script.py`) while this gate
edited two more (`ref/gen_model_script.py`, `ref/calib_stats.py`). So the
weight cache **missed loudly**, exactly as designed — `04a4c9c6…` (G1's wave
2/3 epoch) → **`9689cce9ab7862b10bcc8ede8ddfe5d8132888f6db8f24c44cad6e5d7780aa28`**
— and the 3.03 h rebuild was paid once.

**The rebuild was then compared against the pre-edit one, leaf by leaf**, with
G1's `evidence/qwen9b/g1/cmp_wq_cache.py`:

| payload | leaves | elements | mismatches | verdict | log |
|---|---|---|---|---|---|
| LM head | 5 | 1,025,064,963 | **0** | **BYTE-IDENTICAL CONTENT** | `g2c_cmp_wq_head.log` |
| 32 layers | 1,777 | 6,973,614,393 | **0** | **BYTE-IDENTICAL CONTENT** | `g2c_cmp_wq_layers.log` |
| **total** | **1,782** | **7,998,679,356** | **0** | | |

The only key field that differs is `src_sha256`. **So every `ref/` edit G2a
and G2c made is numerically inert on the quantized artifacts**, and the
fidelity numbers in §7 are comparable to G1's across the digest boundary for
the same reason G1's own wave 1 and wave 2 were: a byte-identical-content
proof bridging two epochs, not an argument that the edits looked harmless.

### 2.2a The digest design caught a live mistake of this gate's, mid-run

**INCIDENT, recorded because the design is only worth what it catches.** The
`RS_F = 8` point was launched at 11:37 and its cold quantization ran until
14:54. At about 12:45, while it was still quantizing, this gate edited **one
line of `ref/gen_model_script.py`'s module docstring** — pure documentation,
in a file whose numeric contribution to that run was already fixed. When the
`RS_F = 7` twin launched off the freshly-saved cache at 14:54 it printed

```
    wq-cache MISS  LM head: no wq_head_9b_c6f25d90b27fe4b7.pkl
```

a **different digest**, and started a second 3-hour cold quantization.
`ref/fidelity_check._WQ_SOURCES` includes `gen_model_script.py`, so a
docstring is inside the key by construction — *"a moved source misses the
cache loudly instead of silently splitting one comparison across two numeric
paths"*, which is exactly the sentence G1 wrote when it designed the key.

**Had the key been narrower, the RS_F pair would have been measured on two
different source trees and nothing would have said so.** It is the one
comparison in this gate that has to be single-variable.

**Disposition:** the twin was killed 10 minutes in, the docstring hunk was
reverted to the text the `RS_F = 8` run imported, the digest was re-computed
and checked equal to `9689cce9…` **before** relaunching, and the twin then
reported `wq-cache HIT` on **both** payloads — the same
`wq_head_9b_dce3bae223ab0e98.pkl` and `wq_layers_9b_68e6c1ff810ce389.pkl` the
baseline wrote. **The two points of §7 are one source digest, one head image
and one layer set, differing in `FABLE5_RS_F` and nothing else.** The
docstring's more precise wording lives in this document instead, which is
where it belonged.

**And the same trade came back one round later, and was taken the other way —
deliberately.** The T5 review found the head-collision comment in
`ref/calib_stats.py` factually wrong about the Hessian (§2.1b). `calib_stats.py`
is also in `_WQ_SOURCES`, so fixing a **comment** moves the digest:

| | digest |
|---|---|
| what both §7 points recorded, and every gate through `d3990bf` | **`9689cce9ab7862b10bcc8ede8ddfe5d8132888f6db8f24c44cad6e5d7780aa28`** |
| after this round's comment-only fix | **`35d2a61fae03d43260a13ba8cf38ff5cc7928641bdc81bc12bd334b4ff2be713`** |

**The comment fix was landed anyway, and the reasoning is worth stating**
because it is the opposite call to the one above. A moved digest costs one
3.03 h cache miss, once, to whoever next quantizes 9B — a known, bounded,
loud price. A false comment sitting next to a guard against a silent
factor-of-two costs the next reader their confidence in the guard, forever,
and silently. **The measurements are not affected either way**: their handle
is the digest each log RECORDS, and both record `9689cce9…`. What is no longer
true is the convenience that the *tree* also carries it — so:

> **Anyone re-running a 9B quantization after this commit will see
> `wq-cache MISS` and pay ≈ 3.03 h. That is expected, it is this line's
> fault, and the cached pkls under `/var/tmp/fable5_wq` keyed `9689cce9…`
> are still the ones §7's numbers came from.**

### 2.3 The regression already existed and was run

`ref/gen_token_script.py` draws the head and the table as two **independent**
random matrices and every `token_s*` TB runs that untied pair through the whole
chain. It is exercised here through the three-tag `ref/` selftest sweep and the
`sw/` board-free suite (§9), both green.

---

## 3. Step 2 — the golden and the Hessian: verified, not rebuilt

The plan's instruction is to **verify by hash first and rebuild only on a
mismatch or a missing file, and to say which happened**. Both matched, so
**neither was rebuilt** and this step cost 88 seconds instead of 40 min + 3.03 h.

| artifact | size | sha256 | committed record | verdict |
|---|---|---|---|---|
| `evidence/qwen_next/ladder/golden_bf16_9b.npz` | 89,440 B | `4fd0616bae5086b8e449901740355a9f192b33ae1c9d18eafc160c0987408fd3` | `evidence/qwen_next/ladder/LADDER.md:88` | **MATCH** |
| `ref/calib_stats_9b_h.npz` | 25,845,351,672 B | `36689b5990c80e1208060b7864841a9387e19ea27e27ec09f0bfd4dd081dd7d4` | `evidence/qwen_next/ladder/calib_9b.log:47` | **MATCH** |

Both are **gitignored regenerable caches with pinned sha256s**, which is what
makes reuse safe and hashing mandatory. `evidence/qwen9b/g2/run_g2c_point.sh`
and `evidence/qwen9b/g2/run_g2c_emit.sh` both re-verify them **before every
run**, so the verification is not a one-off assertion in this document — it is
a precondition of every number below.

**The GPTQ calibration was therefore not re-run.** For the record, the
measured cost if it ever must be: **40.23 min** (183.5 s load + 2,230.1 s pass)
at 8 threads, corpus `ref/ppl_corpus_calib.txt`, which is disjoint from the
pinned eval slice by construction and which `calib_stats` refuses by filename
unless explicitly overridden. The npz carries **one float32 K×K per input
site, 129 sites**, FFN sites at K=12288 → **24.06 GiB**, and lives on the 21 TB
NFS pool, not snoke's 458 GB local disk. Its own metadata reports
`model_tag=9b corpus=ref/ppl_corpus_calib.txt tokens=32768 tensors=249`.
**That `tensors=249` is `n_tensors` in the npz's own metadata — the number of
salience keys `calib_stats` collected, i.e. one per hooked `nn.Linear` plus
the synthetic `lm_head`.** It is therefore counted from the MODEL's module
tree, by a different program, in August, and it agrees with the count §5
derives from `layer_ref`'s `layer_types` and `load_qwen35._EXPECT_*`. Two
routes, one number — and a third, `ref/audit_ranges.py`'s
`8·N_DN + 7·N_GQA + 1`, in §9.

**The caveat travels with it:** GPTQ is calibration-dependent by construction
and a deployment far from this corpus sees less.

---

## 4. Step 3, first half — **HALT: the 9B image set cannot be emitted**

### 4.1 What was attempted

`evidence/qwen9b/g2/run_g2c_emit.sh` runs `ref/gen_model_script.py` at
`FABLE5_MODEL=9b` at the **ratified operating point** — W4 (the default),
`--w4-group=128` (D1, with O2's g64 strip), `--res-scale=1` (spec §4.4: at
H=4096 the raw residual reaches the Q7.8 rail with no rescale applied at all),
`FABLE5_RS_F=8` (A1.8), `FABLE5_DN_STATE` unset (= `int16`, the container
ratified at G1), and the GPTQ env pair pointing at the verified Hessian.

### 4.2 What happened

Log `evidence/qwen9b/g2/g2c_emit_9b_r2.log`, `rc: 1`. The run **paid the full
2 h 55 min quantization and then refused in the emit loop**, which is the
shape the plan needed demonstrating: the weights are fine, the *encoding* is
not.

It got as far as this, and every line of it is a real 9B result:

```
  32 layers, H=4096, vocab=248320
  res_scale=1 DN_NORM_F=11 BF_GUARD=0 mse_scale=True (production) wq=w4 w4_group=128
  quantized 32 layers (24 DN / 8 GQA)
  ln_f folded to (1+w) Q3.12: |q|max 12256 of 32767, 0 out of range
  LM head (248320, 4096) [W4] lm_head.weight e=-3 sh=7; emb table |q|max 120 of 32767
```

Three things worth reading off that block. **The head line names
`lm_head.weight`** — §2's fix, live, in the shipped emitter. **`e = -3, sh =
7`** is the same format `ref/audit_ranges.py` measures with the unweighted
`quant_linear` (§6.2) and the same the fidelity harness reports for its GPTQ
head (§7) — three independent paths, one answer, on the real untied head. And
**`emb table |q|max 120 of 32767`** is the residual seed at `RS_F = 8`,
`res_scale = 1`: 120/32767 = **0.37 %** of the rail, matching §4 of the audit
report exactly.

Then:

```
AssertionError: CONV channel count 8192 does not fit its 13-bit field
```

raised from `ref/gen_layer_script.py:1006`, reached from the whole-block
`M.convz(0, LR.CONV_DIM)` in the emit loop. **`CONV_FIELD_MAX` is the FIRST
of the five walls a 9B body hits**, not one of the later ones, and it is the
narrowest: `CONV_DIM = 8192` against a field that stops at **8191**.

**What the run left behind:** 163,975 bytes of partial script text in the temp
directory, and

```
  weight images written: 0
  weights manifest:      0
  emb table:             0
```

**The guard suite, in the same log, predicts exactly this and shows both
sides**: `PASS RED convz(0, 8192) — refused, naming '13-bit field'`,
`PASS GRN convz(0, 8191) — in-range accepted`, and
`CONV_DIM=8192 vs field max 8191: a whole-block convz REFUSES (Task 10 widens
the field)`. A RED without its GREEN would not distinguish this from a guard
that always throws.

**The discriminator's own regex was too loose, and it is tightened.** The
`WANT` pattern in `evidence/qwen9b/g2/run_g2c_emit.sh` originally carried a
bare `CONV` alternative — which matches any traceback line containing the
substring, including a path — so it could have scored an unrelated failure as
the expected refusal, re-creating the very class the discriminator exists to
prevent. Every alternative is now text from a guard's own message
(`CONV channel count`, `CONV first-channel`, …). Verified both ways: it still
matches the recorded assertion, and no longer matches a line whose only `CONV`
is in a path. **The recorded verdict does not change** — the assertion text is
the same string either way.

**Item carried, not fixed: `ref/audit_ranges.py:534` loads the head BEFORE the
memory guard.** `head_w = emb if TIED else st.get(HEAD_KEY)` runs above
`if memg >= HEAD_MEM_GIB`, so at 9B a 4.07 GB float32 is materialized even on a
machine that will then decline to quantize it. It is a one-line reorder and it
is **deliberately not made in this gate**: the 9B report was being re-run on
the committed tree to close §9a's provenance gap, and editing the file
mid-run would have re-opened it. Handed on with its fix.

**HONESTY ITEM — the traceback's source text is one line off, and the reason
is mine.** Python records the line NUMBER at raise time and renders the source
text from the file *as it is when the traceback prints*. This gate edited
`ref/gen_model_script.py`'s docstring (+1 line) while the run was in its
quantization phase, so the frame that reads `line 595 … M.convw(c, 2048, STG)`
is really the `M.convz(0, LR.CONV_DIM)` one line below it — which is the only
call that can pass `nch = 8192`, since `convw` is chunked at 2048. The
assertion message is unambiguous either way, and the guard suite's RED is the
clean form of the same fact. **Recorded rather than re-run**: a re-run costs
another 2 h 55 min of GPTQ to reach the identical assert.

### 4.3 Why no weight image comes out of that file at 9B — and the honest
version of "structural"

`Mach.dump_weights` packs `self.wids`, and `self.wids` is populated **only**
inside `Mach.matvec`, which is reached **only** from the token body. So the
image set is downstream of the script emission rather than beside it: a
geometry whose body cannot be encoded produces no images from *this entry
point*.

> **CORRECTED 2026-08-31 (T5 review).** An earlier revision of this section
> said the HALT was "structural — there is no `--weights-only` path, and
> inventing one would mean re-implementing the emitter's registration order
> outside the emitter." **That overclaims, and this gate's own §5.4 is the
> counter-example**: it builds the wid registry from the cached quantized
> tensors in nineteen lines and hands it to
> `ref/seq_format.plan_weights_from_wids`. Feeding the same registry to
> `Mach.dump_weights` instead is a handful of lines on committed code, and it
> would write 249 real images.
>
> **What is actually true is narrower and, for a shipped artifact, worse:
> emission is POSSIBLE but UNVERIFIABLE here.** A wid is not a name — it is
> the ORDER `Mach.matvec` first saw a matrix, and every consumer (the MVGO
> `WBASE`, the manifest, `sw/chat_seq.py`'s head wid) binds by that integer.
> At 9B the shapes repeat heavily — 24 identical DeltaNet layers, 8 identical
> GQA layers, `mlp.gate` and `mlp.up` the same `(12288, 4096)` — so a
> registry built in the wrong order produces a manifest that is **structurally
> valid, correctly sized, and bound to the wrong matrices**, with no assert
> anywhere able to see it. At 0.8B and 2B the committed manifests catch that
> (§5.1); at 9B nothing does.
>
> So this gate did not emit, and the disposition it hands to Task 11 is a
> **VERIFICATION, not a build**: emit through `ref/gen_model_script.py` once
> the five fields are widened, and cross-check the wid order against §5.4's
> registry. Building the artifact outside the emitter to save time would
> trade a three-hour wait for an unfalsifiable artifact, which is the wrong
> trade for something a bitstream reads.

The five refusing fields, each with the task that widens it — `CONV_FIELD_MAX`
first, measured (§4.2), and the other four behind it. All five are exercised
RED-and-GREEN by `evidence/qwen9b/g2/isa_guards_check.py`, which returns
**33 passed, 0 failed** at 9B in this gate's own run:

| field | as built | 9B needs | task |
|---|---|---|---|
| `ISA_SADDR_MAX` (`ref/gen_layer_script.py:413`) | 32,768 | a 50,208-word layer-body peak | 7 |
| `Mach.VNW_ISA_MAX` (`ref/gen_layer_script.py:908`) | 2,048 | a 4,096-word `rmsnorm` | 8 |
| `Mach.ARG0_HEAD_BITS` (`ref/gen_layer_script.py:1064`) | 4 | `LNH = 32` DNST heads | 10 |
| `Mach.ALU_LEN_MAX` (`ref/gen_layer_script.py:1207`) | 8,191 | an FFN length of 12,288 | 9 |
| `Mach.CONV_FIELD_MAX` (`ref/gen_layer_script.py:945`) | 8,191 | a CONV_DIM of 8,192 | 10 |

The last one is the narrowest miss in the campaign — **8,192 against 8,191, a
single count** — it was found by G2a's guard suite rather than by reading, and
it is the one the emitter actually stops on.

### 4.4 What this HALT does and does not block

**Blocked, and handed to Task 11 with the streams:** the 249 image files, the
weights manifest, the flat int16 embedding table, and — the item worth naming
separately — **`gen_model_script`'s RUNTIME RANGE AUDIT**. That audit is the
only thing that closes section 5 of `ref/audit_ranges.py`'s report, the eight
activation-dependent formats it explicitly defers to *"a runtime audit in
`gen_model_script`"*. Step 3's instruction about clips (*"if the runtime range
audit trips on clips, record and evaluate before reaching for `--allow-clip`"*)
therefore **has no measurement in this gate** and is carried forward, not
answered.

**Not blocked:** the fit (§5), which needs the manifest's shapes and not its
bytes; both range tools (§6), which read the checkpoint; the fidelity harness
(§7), which runs the reference model; and the chat template (§8).

---

## 5. Step 3, second half — the per-channel fit, measured

`evidence/qwen9b/g2/g2c_pack_fit.py`. **`sw/hwmap.plan_weights`
(`sw/hwmap.py:522`) is the authority and does every address computation**; the
tool only turns geometry into the manifest shape that function wants, exactly
as `ref/seq_format.plan_weights_from_wids` does for live tensors.

### 5.1 The control comes first

The derived manifest is compared **field by field** against the committed
manifests at both geometries that have one, on `nrows`, `k`, `ng`, `nbeats`,
`stride`, `g` and `w8` — every field `plan_weights` reads:

| tag | committed manifest | wids | verdict |
|---|---|---|---|
| 0.8b | `tb/scripts/w4/model_v2_s1.weights.json` | 187 | **PASS**, every field identical |
| 2b (W8) | `tb/scripts/w5/model_w8_2b_s1.weights.json` | 187 | **PASS**, every field identical |
| 9b | — | 249 | no committed manifest exists; none ever has |

**374 committed rows at two geometries and two weight widths** is what the 9B
row rides on. The shapes are read from `load_qwen35._EXPECT_DN` /
`_EXPECT_ATTN` / `_EXPECT_MLP`, the tables `load_layer` checks every real
tensor against; the row law is `w4a8_ref.row_stride` / `row_stride8`, the
functions `dump_weights` itself reaches through `pack_ddr_rows`. Only the wid
**order** and the wid **set** are the tool's own, and the control checks both.

**What "field by field" is worth, counted honestly** *(added at the T5
review, which asked for it)*: seven columns are compared but they are not
seven independent checks.

- **`g` is vacuous here** — it is 128 on every row of both committed sets and
  on every derived row, so that column can never disagree at these operating
  points. It is compared because a future g64 artifact would need it, not
  because it is testing anything today.
- **`w8` is one bit, twice** — `False` across all 187 0.8B rows, `True` across
  all 187 2B rows. A real check (it is the whole difference between the two
  row laws) but not 374 independent ones.
- **`ng`, `stride` and `nbeats` are functions of `nrows` and `k`.** On the
  GOLD side they were written by `dump_weights` at emit time, so agreeing on
  them does test that this tool's row law reproduces the emitter's — that part
  is real. It is not, however, 374 more independent facts.
- **The independent per-row content is `nrows` and `k`: 748 numbers**, plus
  the row-law agreement above and the two-valued `w8`.

**And the control is not reproducible from a clone.**
`tb/scripts/w4/model_v2_s1.weights.json` and
`tb/scripts/w5/model_w8_2b_s1.weights.json` are **gitignored NFS artifacts**;
they are pinned by sha256 in `evidence/qwen9b/g2/FINAL_BYTELOCK.md` and they
exist on this filesystem, but a fresh clone has neither, and after G3 nothing
regenerates them (G2b's supersession notes). The tool reports
`control not available` rather than skipping silently when they are absent.

**The fit's output does not depend on the order anyway** — `plan_weights`
advances each channel's cursor by `align_up(rows_c · stride, WID_ALIGN)`
(`sw/hwmap.py:455`), so a per-channel top is a sum over the multiset of images.
Order is checked because the per-image **bases** do depend on it.

### 5.2 The 9B pack

| quantity | measured | projection it is checked against |
|---|---|---|
| images | **249** | spec §7.2 and plan Step 3: **249 images** |
| bytes/token | **4,091,805,696 B = 3,902.2 MiB** | `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md:1713` |
| busiest channel, nch=4 repacked | **978.6 MiB = 76.45 % of the 1,280 MiB window** — **PASS** | `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md:1713-1714` projects 978.6 MiB = 76.5 % |
| LM head image | **524,451,840 B = 500.2 MiB**, wid **248** | spec §7.2: *"a `plan_weights` output, not a number this spec invents; G3 records it"* |
| embedding table | **248,320 × 4096 × 2 B = 2,034,237,440 B = 1,940.0 MiB** | `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md:1723`, exact |
| channel-0 total | **256 (W_BASE) + 978.6 (pack) + 1,940.0 (emb) = 3,174.6 of 4,096 MiB** | plan Step 3's **(S)** arithmetic, now measured |

Per-channel tops, repacked at nch=4, head `LAYOUT_ILV` and every other wid
`LAYOUT_CONTIG` at `chunk_rows = 2048` — the layout the committed 0.8B
four-channel artifact actually encodes (`tb/scripts/w4/model_v2_s1.e4.seq.json`
carries `ilv_wids: [186]`, i.e. the head and only the head):

```
  chan 0  0x4d290000   978.6 MiB
  chan 1  0x4cf78000   975.5 MiB
  chan 2  0x4ce70000   974.4 MiB
  chan 3  0x4ce70000   974.4 MiB      EMB_BASE = 0x60000000
```

### 5.2a `EMBLOG2 = 13`, and it sits exactly on the ceiling

The manifest carries `emb_row_bytes = 2·H` (R-b's caller-gated key) and the
host derives the CSR from it with `sw/hwmap.seq_emb_log2`, which refuses a
non-power-of-two row and a `log2` outside `[SEQ_EMBLOG2_MIN, SEQ_EMBLOG2_MAX]`
= `[8, 13]`:

| tag | `2·H` | `EMBLOG2` |
|---|---|---|
| 0.8b | 2,048 B | 11 |
| 2b | 4,096 B | 12 |
| **9b** | **8,192 B** | **13 — exactly `SEQ_EMBLOG2_MAX`** |

So 9B is the last geometry this CSR can address, with zero headroom. **[D]**,
from the committed `sw/hwmap.py` on the three geometries.

**No `EMB_BASE` change is needed at W4**, as the plan says: the zero-slack
embedding-channel problem is a W8-only problem and this build does not have it.
The nch-independent pack — the layout every artifact frozen before R-c encodes
— is **3,902.3 MiB against a 1,280 MiB window** and `plan_weights` **refuses**
it rather than returning an address nobody could use. That refusal is a
result, and it is why the repack is a prerequisite and not an optimization.

### 5.3 The tool reproduces the two older geometries before it computes
anything new

| tag | pack | nch-independent | nch=4 repacked, busiest | prior record it matches |
|---|---|---|---|---|
| 0.8b W4 | 398.1 MiB | top `0x28e34000` — **PASS** | 100.4 MiB = 7.8 % | `0x28e34000` is the pack top G2a's `tok_meter_layout_check.py` measured |
| 2b W8 | 1,847.2 MiB | **REFUSED** at `0x8374c000` | 464.8 MiB = 36.3 % | `ref/gen_model_script.py:134-136` — *"The 2B W8 pack is 1,847 MiB nch-independent"*, *"the busiest channel holds 465 MiB"* |

### 5.4 A second route: the manifest from the REAL quantized 9B tensors

`g2c_pack_fit.py --from-wq-cache`, log
`evidence/qwen9b/g2/g2c_pack_fit_live.log` (`rc: 0`), closes most of the gap
the HALT opens. The
weight cache `ref/fidelity_check.py` writes holds exactly the objects
`ref/gen_model_script.py` would hand to `Mach.matvec` — a list of
`layer_fixed.quant_layer` outputs plus the `quant_linear_big` head, at this
build's `(res_scale=1, g=128, w8=False, gptq)`. The wid registry is built from
them in the emitter's call order and handed to
`ref/seq_format.plan_weights_from_wids`, the **committed live-tensor twin** of
`dump_weights`, which delegates every address to `sw/hwmap.plan_weights`.

**Result: 249 live-tensor wids against 249 derived wids, every `nrows`, `k`,
`ng`, `stride` and `nbeats` identical, and the head's per-channel base
`0x452b0000` matching §5.2's.** So the shapes in §5 are not merely consistent
with `_EXPECT_*` — they are the shapes of the real quantized matrices.

**Counted honestly, that is 498 independent numbers, not 1,245.** Both sides
derive `ng`, `stride` and `nbeats` from `(nrows, k)` using the *same committed
functions*, so those three columns agree by construction and test nothing
here. The content is `nrows` and `k` on 249 images — which is exactly the
content that matters, because it is the pair the fit is a function of.

**What this still does not prove** is the wid **order** at 9B. Both routes
here use the same ordering rule; only an emitted 9B manifest can check it, and
the 0.8B and 2B controls are what stand in for it until Task 11.

---

## 6. Step 4 — both range tools at 9B

The plan asks for both tools "against the *emitted* artifacts". Neither tool
reads an emitted artifact: both read the **checkpoint** and run the production
quantizer over it, which is what the images would contain. With no emitted
artifact to read (§4), that is the whole of what this gate can run, and it is
recorded as such rather than as the stronger claim.

### 6.1 `gate_port_probe` — the second axis, unchanged and still unpaid

Log `evidence/qwen9b/g2/g2c_gate_port_probe_9b.log`, `rc: 0`. Run through
G1's `runpy` fork (`evidence/qwen9b/g1/gate_port_probe_9b.py`), which executes
`evidence/qwen2b/q2/audit/gate_port_probe.py` verbatim with `find_checkpoint`
patched to the full shard list. **Every headline reproduces G1's, on the
post-G2a/G2c tree:**

| quantity | this run | G1 |
|---|---|---|
| heads | 768 | 768 |
| `max A = exp(A_log)` against a port of `[0, 8.0)` | **76.9957** | 76.9957 |
| `max abs(dt_bias)` against `±8.0` | **18.5000** | 18.5 |
| `A` out of uint18 Q15 before the clamp | **49 / 768** | 49 / 768 |
| `dt` out of int16 Q12 before the clamp | **12 / 768** | 12 / 768 |
| **decay CHANGED by the production clamp** | **60 / 768** | 60 / 768 |
| decay changed by the pre-`82781e5` wrap | 61 / 768 | — |
| `max abs(conv_w)` against `±4.0` | 1.2344 | — |

The fork's own cross-check also reproduces: DeltaNet layer 0 quantized with
the production `layer_fixed.quant_deltanet`, and `qd["gate_sat"]` compared
entry for entry against the probe's recomputed expressions — **IDENTICAL, 10
of 32 heads**. So the probe is measuring what spec §4.1(d) says the truth is,
not a parallel arithmetic.

**This cost is option-independent and it is still unpriced at scored
resolution.** It is a property of the checkpoint against the frozen
`gate_unit` ports, not of the DeltaNet state container, so G1's `int16` ruling
did not dispose of it. It travels to the RTL phase as spec register row
**D-GATEPORT** (A1.9). Pricing it costs one 168-step `--diag gateport` point,
≈ 7 h, and a diag run may not use the weight cache.

**Two tools, and the reason spec §4.1(d) mandated two, re-confirmed here.**
`ref/audit_ranges.py` §3 calls the same port PASS — printing *"max 76.9957 <
8.0"* as its own justification — in the same gate, minutes apart (§6.2). One
tool would have reported a clean bill of health on the port that matters most.

### 6.2 `ref/audit_ranges.py` at 9B — now on the real head

Log `evidence/qwen9b/g2/g2c_audit_ranges_9b.log`, `rc: 0`; report
`evidence/qwen9b/g2/g2c_audit_ranges_9b_report.md`. **Run unforked** — the
first time this tool has run at 9B from `ref/` — because §2.1(a) fixed the
first-shard open at its call site.

**Diffed against G1's forked report (`evidence/qwen9b/g1/audit_ranges_9b_report.md`),
and the difference is the finding.** §2b is a different matrix now:

| §2b `lm_head` at 9B | G1 (audited `embed_tokens`) | this gate (audits `lm_head.weight`) |
|---|---|---|
| shape | 248320x4096 | 248320x4096 |
| `e` | −2 | **−3** |
| `sh` | 7 | 7 |
| `m` range | 1..8814 | **311..10317** |
| `m == 1` (scale underflow) | **96 / 7,946,240** | **0** |
| `m` clipped up from 0 | **64 / 7,946,240** | **0** |
| INT4 clip | 9,463,800 / 1,017,118,720 | **9,351,546** |
| rel err (Frobenius) | 10.17 % | **10.58 %** |
| y32 headroom wasted | 5.4 b | **4.4 b** |

**Every column but `sh` moves, and one whole ATTENTION item disappears.** G1's report
carried **5 ATTENTION items**; this one carries **4**. The one that went is
*"W4 group-scale underflow: 96/61997056 groups hit `m == 1` (64 clipped up
from 0), annihilating 4131 weights"* — a real property of the **embedding
table** and **not** of the LM head that ships, which underflows **zero**
groups. It is now a PASS line: *"0 of 61997056 groups underflow to `m == 1`
and 0 saturate at 65535; the matrix-wide shared exponent covers the real
per-group dynamic range."* An item that would have been carried into the RTL
phase as a 9B head risk was an artifact of auditing the wrong tensor.

The `e = −3, sh = 7` this run measures with the unweighted `quant_linear` is
also what the GPTQ head in §7's fidelity run reports (`LM head quantized (W4
mse=True g=128) e=-3 sh=7`) — two different quantizers on the same real head,
agreeing on the format.

**The four remaining ATTENTION items, recorded and NOT dispositioned:**

1. W4 value clipping — **73,218,442 of 7,935,623,168 weights (0.923 %)** round
   outside `[-8,7]`, `lm_head` contributing 9,351,546. (G1's figure was
   73,330,696 / 0.924 %; the delta is exactly the head's.)
2. **W4 weight error above the project's own 15 % bound on 5 of 249 matrices**,
   worst `L8.dn.in_b` at **15.47 %** — unchanged from G1, and still not
   asserted anywhere, because the 15 % check only runs inside the synthetic
   self-test. All five are DeltaNet gate projections (`L25/L26/L28/L29.dn.in_a`
   and `L8.dn.in_b`), which feed the decay and beta gates — the same chain
   §6.1's port clamp damages.
3. y32 headroom: conservative `sh` discards up to 5.6 bits (precision, not
   overflow).
4. The embedding at Q7.8 uses **0.37 %** of the int16 range (120 LSB peak,
   3.4 LSB RMS) → **8.4 %** relative RMS error on the layer-0 residual.

**Outside §2b and that ATTENTION list, no number in the report moved**, and
the label families that DID change are **G2a's** parameterization becoming
visible at 9B for the first time, not this gate's: `ln1 / ln2 (48 → 64 tensors)`,
`q_norm / k_norm (6 → 8 GQA layers)`, `linear_attn.norm (18 → 24 layers)`, and
the image-count sentence `187 weight images at 24 layers` →
`249 weight images at 32 layers`. G1's §10 recorded those labels as *"0.8B
strings (counts are 9B-correct)"*; `b2f1223` derived them, and this is the
first 9B report to show it. **The 249 that sentence now prints is
`8·N_DN + 7·N_GQA + 1` evaluated by `ref/audit_ranges.py`, and it agrees with
the completely independent derivation in §5 — two routes, one number.**

**And the two-tool mandate re-earns itself inside this gate's own evidence.**
`evidence/qwen9b/g2/g2c_audit_ranges_9b_report.md:98-99` reads
*"PASS `A` — max 76.9957 < 8.0, fits uint18 Q15."* and
*"PASS `dt_bias` — max |dt| 18.5000 < 8.0."* — two PASS verdicts that print
the number contradicting them, on the same checkpoint that §6.1's probe
reports 60 of 768 heads with a **changed decay** on. Both sentences are in
this gate's committed evidence, minutes apart. One tool would have cleared
the port that matters most.

---

## 7. Step 4′ — `RS_F = 7` under `int16`, the one open rider (A1.8)

**Taken on explicit instruction, as the plan requires. It DECIDES NOTHING —
and by the plan's own words it now has to go back to the user, because the
ratified O5 condition is met.**

### 7.1 First, the baseline reproduces — exactly

Before the rider means anything, the harness has to reproduce G1's committed
`int16` baseline on the post-G2a/G2c tree. It does:

| | G1 `fixed_9b_w4g128gptq_int16_rsf8_a` | this gate `g2c_…_int16_rsf8_g2c` |
|---|---|---|
| top-1 | **95/108** | **95/108** |
| rank median / max | 0.0 / **5** | 0.0 / **5** |
| top-5 overlap | **3.69** | **3.69** |
| `\|x\|max` / residual clips | **32767** / **23** | **32767** / **23** |
| `S_F` sat / `S8` sat / `\|S\|max` | 4392 / 0 / 61096 | 4392 / 0 / 61096 |
| per-prompt top-1 | 26 / 21 / 23 / 25 | 26 / 21 / 23 / 25 |

**And not only the summary line.** `diff` over the two logs from `prompt 1`
through the `=== rc:` line returns **exactly two**: the weight-cache accounting
(*"0 pass, 2 hits"* vs *"1 pass, 0 hits, 2 misses"* — a statement about the
cache, not the model) and the `--json-out` path. Extend the range by the one
remaining line and it is **three**, the third being the trailing
`=== end:` wall-clock stamp. Neither the cache line nor the timestamp is a
measurement; naming all three is more useful than picking the range that gives
the smaller number. **Every per-prompt argmax, every rank
vector, every top-5 vector, both block-float histograms, the saturation line,
all six matvec headroom rows and all four free-run texts are byte-identical to
G1's.** That is Step 4's "reproduce Task 1's numbers" discharged — through the
reference model, since §4 leaves no emitted chain to run it through.

### 7.2 The rider, measured

Single-variable by construction: same quantizer source digest
`9689cce9…`, same `wq_head_9b_dce3bae223ab0e98.pkl`, same
`wq_layers_9b_68e6c1ff810ce389.pkl`, both cache HITs, and
`--wq-cache-verify 2` re-quantized layer 2 live under
`FABLE5_DN_STATE=int16 RS_F=7` and found it **BYTE-IDENTICAL to the cache** —
so `RS_F` demonstrably does not reach the quantizer. **`FABLE5_RS_F` is the
only thing that differs between the two runs** (§2.2a is the incident that
made sure of it).

| quantity | `RS_F = 8` (ships) | **`RS_F = 7`** | Δ |
|---|---|---|---|
| **top-1** | 95/108 | **98/108** | **+3** |
| rank median | 0.0 | 0.0 | — |
| **rank max** | 5 | **5** | **unchanged** |
| **top-5 overlap** | 3.69 | **3.69** | **unchanged** |
| **residual clips** | **23** | **0** | **−23** |
| `\|x\|max` | **32767** (pinned on the rail) | **29916** | off the rail |
| `S_F` sat | 4392 | 4170 | −222 |
| `S8` sat / container rail | 0 / 0 | 0 / 0 | — |
| `\|S\|max` | 61096 (7.4580 @ Q2.13) | 61085 (7.4567) | −11 |
| per-prompt top-1 | 26 / 21 / 23 / 25 | **27 / 23 / 24 / 24** | +1 / +2 / +1 / −1 |
| free-run text | coherent ×4 | coherent ×4 | — |

The matvec int16-dequant headroom improves with it: `4096x12288` clips
**2 → 0**, `4096x4096` **8 → 0**, `32x4096` **496 → 405**, `12288x4096`
**10,897 → 10,816**; `|y|max` falls on every row.

Prompt 1's free run is qualitatively better too — at `RS_F = 8` it generates
*" is Paris.\nThe capital of France is not Paris."*, at `RS_F = 7`
*" is Paris.\nThe capital of France is Paris.\n"*, which is the golden's own
continuation. One prompt is an anecdote, not a result; the 98/108 is the
result.

### 7.3 The confirming repeat — byte-identical

**Authorized after the first point landed** (a decision number gets a repeat
before it reaches a user; every other G1-class number had one) and run as
`g2c_fixed_9b_w4g128gptq_int16_rsf7_g2c_b`. Same launcher, same arguments,
same `OMP_NUM_THREADS=6`, an independent process on an otherwise idle machine.

**The digest was re-computed and checked equal to `9689cce9…` BEFORE launch**,
and the golden and Hessian re-hashed by the launcher — the §2.2a lesson
applied to this gate's own next run rather than left as a story.

| | run `a` | run `b` (repeat) |
|---|---|---|
| tree label | `b242370+dirty` | **`d3990bf`, clean** |
| quantizer source digest | `9689cce9…` | `9689cce9…` |
| head / layers cache | `dce3bae2…` / `68e6c1ff…`, both HIT | same two, both HIT |
| `--wq-cache-verify 2` | BYTE-IDENTICAL | BYTE-IDENTICAL |
| **top-1 / rank med / rank max / top-5** | **98/108 / 0.0 / 5 / 3.69** | **98/108 / 0.0 / 5 / 3.69** |
| `\|x\|max` / clips / `S_F` sat / `\|S\|max` | 29916 / 0 / 4170 / 61085 | 29916 / 0 / 4170 / 61085 |

**`diff` over the report body from `prompt 1` through `=== rc:` returns ONE
line — the `--json-out` path.** Every per-prompt argmax, rank vector, top-5
vector, both block-float histograms, the saturation line, all six matvec
headroom rows, all four free-run texts and the weight-cache accounting are
identical. **Not even the cache line differs**, because both runs were warm.

The json bodies agree on **16 of 17 sub-keys exactly**; the seventeenth is
`_wq.verified.secs` — the wall-clock of the verify step, 300.54 s vs
301.05 s. Nothing measured differs.

**So run-to-run spread on this configuration is exactly zero**, which is what
G1 observed at every granularity it tested and what this gate had cited
without having paid for at `int16`. The +3 is not draw noise.

Two things it is still not. It is **one configuration repeated, not a second
seed or a second prompt set** — the harness is deterministic, so a repeat
tests the *process*, not the *sampling*. And a repeat cannot make a
single-point measurement into a decision; §7.3 below is unchanged by it.

### 7.4 What this means, stated without deciding anything

**The rider's sign is container-dependent, and the third container is the one
that ships.** All three measurements now exist:

| container | top-1 at `RS_F = 8` → `7` | rank max | verdict G1 or this gate recorded |
|---|---|---|---|
| `int8:6` global (G1 wave 1) | 72 → **73** | 214 → **335** (worse) | neutral on top-1, worse on rank |
| `int8e` per-row (G1 wave 3) | 94 → **89** (−5) | 13 → **18** (worse) | **rejected** |
| **`int16` (ships) — this gate** | 95 → **98** (+3) | 5 → **5** | **clipping removed at no top-1 cost — and a gain** |

**The ratified O5 condition is *"take Q8.7 only if it removes residual
clipping WITHOUT costing top-1"*.** Under `int16` it removes the clipping
completely (23 → 0, `|x|max` off the 32,767 rail) and top-1 goes **up**, with
rank max and top-5 overlap unmoved. **On its face the condition is met.**

**This gate does not act on that, and the plan says why.** Step 4′: *"if it is
taken and Q8.7 removes the clipping at no top-1 cost, that is a ratified-O5
condition met and it goes back to the user before anything acts on it, because
it moves `rtl/conv4_silu.sv:50` and a set of host constants that Task 10 has
otherwise been told not to touch."* A1.8 also says plainly: **`RS_F` stays
8.** So:

- **`RS_F` remains 8 in this tree.** Nothing was changed. `rtl/conv4_silu.sv:50`
  still reads `rshr64(64'(acc1), 9)`; no host constant moved; the emitter
  writes `rs_f` into a 9B manifest as **8**.
- The plumbing to change it later already exists and is inert: G2a made `RS_F`
  **model-selected** through the manifest, with the emit/consume tie asserted
  where the key is dropped, and `sw/chat_seq.py`'s `−22` derived from
  `head_logit_exp0(spec.rs_f)` so a switch to 7 moves the expectation to **−21**
  by itself.
- **It is one point.** No repeat was run. G1 measured run-to-run spread as
  **exactly zero** across eighteen-plus 9B runs at every granularity it tested,
  which is why one point was judged enough to report — but a confirming repeat
  is 3.9 h on the warm cache and has not been paid (§10).

**Cost of the measurement:** 3.9 h of scoring on a warm cache, plus the 3.03 h
rebuild the baseline had already paid for other reasons. The plan priced it at
≈ 3.8 h.

---

## 8. Step 5 — the chat template, re-derived

`evidence/qwen9b/g2/g2c_chat_template.py`, run on snoke (the 4B and 9B
snapshots exist only there), log
`evidence/qwen9b/g2/g2c_chat_template_final.log`.

### 8.1 Which files move and which do not — the two facts that get conflated

Measured by sha256 over all four snapshots:

| file | 0.8B | 2B | 4B | 9B | classes |
|---|---|---|---|---|---|
| `tokenizer.json` | `5f9e4d4901a92b99` | same | same | same | **ONE** |
| `vocab.json` | `ce99b4cb2983d118` | same | same | same | **ONE** |
| `merges.txt` | `a9d356d7bdf1ef49` | same | same | same | **ONE** |
| `chat_template.jinja` | `273d8e0e683b8850` | same | `a4aee8afcf2e0711` | same as 4B | **TWO** |
| `tokenizer_config.json` | `49e2b6e395f959f0` | same | `316230d6a809701f` | same as 4B | **TWO** |

**The TOKENIZING files are one class across all four models.** So the pinned
PPL corpus and its 24,528 scored positions carry over unchanged, and so does
every id in the host's wrapper. **The TEMPLATING files are two classes**:
0.8B/2B share one, 4B/9B share the other, and `tokenizer_config.json` differs
only because it embeds a copy of the same jinja.

### 8.2 The diff, and the feasibility study's count reproduced exactly

`chat_template.jinja` is **154 lines** at both geometries (7,755 vs 7,756
bytes). **3 lines are removed and 3 added — 6 changed lines of 154 — inside a
single hunk whose unified body is 12 lines** (6 context + 6 changed). Both
halves of the study's phrase *"a 12-line unified diff touching 3 of the
template's 154 lines"* reproduce; the two counts are of different things and
this gate says which is which.

```
 {%- if add_generation_prompt %}
     {{- '<|im_start|>assistant\n' }}
-    {%- if enable_thinking is defined and enable_thinking is true %}
+    {%- if enable_thinking is defined and enable_thinking is false %}
+        {{- '<think>\n\n</think>\n\n' }}
+    {%- else %}
         {{- '<think>\n' }}
-    {%- else %}
-        {{- '<think>\n\n</think>\n\n' }}
     {%- endif %}
 {%- endif %}
```

It **inverts the `enable_thinking` default**: 0.8B/2B emit a closed
`<think>\n\n</think>\n\n` unless asked for thinking; 4B/9B emit an **open
`<think>\n`** unless asked *not* to. Confirmed exactly as the study reports it.

### 8.3 The finding: the host's wrapper does not move, and that is measured

Every canonical rendering of `docs/INSTRUCT_SPEC.md` was produced by HF's own
`apply_chat_template` at 0.8B and at 9B, in three thinking modes, and compared
against the constants frozen in `sw/chat_seq.py` (transformers 5.11.0):

| conversation | pinned constant | 0.8B default | 0.8B `enable_thinking=False` | 9B default | 9B `enable_thinking=False` |
|---|---|---|---|---|---|
| single turn | `HF_REF_SINGLE`, 19 ids | **==** | **==** | 17 ids, **!=** | **==** |
| with system | `HF_REF_SYSTEM_SINGLE`, 30 ids | **==** | **==** | 28 ids, **!=** | **==** |
| 3-message | `HF_REF_3MSG`, 35 ids | **==** | **==** | 33 ids, **!=** | **==** |

**Reading.** The frozen wrapper is **unchanged as a sequence of ids at 9B** —
every id in it comes from tokenizing files that are byte-identical across the
four models, and the host splices ids rather than rendering jinja (T1: *"ID-SPLICED
WRAPPER, never string-encoded"*). What changes is **which HF invocation the
wrapper corresponds to**: at 0.8B/2B it is `apply_chat_template(...)` with the
default; at 4B/9B it is `apply_chat_template(..., enable_thinking=False)`. So
the T2 decision (*"NEVER enable_thinking=True"*) is unchanged and costs the
same 7 wrapper ids; what must change is the **reference** a 9B selftest
compares against, which has to name the flag explicitly.

The arithmetic behind the 2-id gap, since it is the whole difference: the
closed-empty block is `[<think>, enc("\n\n"), </think>, enc("\n\n")]` = **4
ids** and the open block is `[<think>, enc("\n")]` = **2**, so
`WRAP_GEN_PROMPT` would fall 7 → 5 for a host that took the 9B jinja default.

### 8.4 The `ntok >= 24` UX guidance: **it does not move for this host**, and a
carried claim needs the qualifier

`docs/QWEN35_NEXT_FEASIBILITY.md:259` says *"the `ntok >= 24` UX guidance moves
— a reasoning block now precedes the answer by default"*. That is **true of
the model's own template and false of this host**, and the difference is
measured above: `ChatTemplate.gen_prompt()` splices the **closed** block
unconditionally, so at 9B the model is handed `</think>\n\n` already in
context and no reasoning block precedes the answer. `docs/USAGE.md:269`'s
`--ntok >= 24` guidance therefore carries over unchanged, for the same reason
it was written (a reply cut before EOS leaves a ragged assistant turn in the
KV cache).

**What this gate CANNOT say** is how a 9B *trained* with an open-think default
behaves when handed a closed block. That is a model-behaviour question, not a
plumbing question, and it needs the board — G6. It is in §11.

---

## 9. Gates

Every one of these ran on snoke through `evidence/qwen9b/run.sh`.

| gate | log | result |
|---|---|---|
| 0.8B artifact regeneration | `g2c_regen_gate.log` | **REGEN_GATE_PASS**, sha `a69864d25b6b129a4d6c74b3c78dfcbedf1edce219d32cc05d05bc54f444aaf1` |
| 2B W8 byte-lock | `g2c_t4_bytes_unmoved.log` | **BYTES_UNMOVED PASS**, 15 weight images compared, 0 differ |
| `sw/` board-free suite | `g2c_sw_boardfree.log` | **BOARDFREE_PASS 2758 / 85 / 351** |
| ISA guard suite, 0.8B | `g2c_isa_guards_0.8b.log` | 32 passed, 0 failed |
| ISA guard suite, 2B | `g2c_isa_guards_2b.log` | 32 passed, 0 failed |
| ISA guard suite, 9B | inside `g2c_emit_9b_r2.log` | **33 passed, 0 failed** |
| three-tag `ref/` selftest sweep | `ref_selftests_g2c.log` | **OVERALL exit 0** — 21/21 invocations exit 0, 18 `SELFTEST PASS`, **zero `FAIL`** at 0.8b / 2b / 9b |
| `ref/seq_chat.py --selftest` | `g2c_seq_chat_selftest.log` | **SELFTEST: PASS**, including the emb-geometry check at all four tags |
| per-channel fit + its control | `g2c_pack_fit_g2c.log` | **G2C_PACK_FIT PASS** — 187 + 187 committed rows reproduced field for field |
| live-tensor fit cross-check | `g2c_pack_fit_live.log` | **G2C_FIT_LIVE PASS** — 249 live wids vs 249 derived, every field identical |
| chat template | `g2c_chat_template_final.log` | **G2C_CHAT_TEMPLATE PASS** |
| weight-cache content, old vs new digest | `g2c_cmp_wq_head.log`, `g2c_cmp_wq_layers.log` | **BYTE-IDENTICAL CONTENT** ×2, 7,998,679,356 elements, 0 mismatches |
| 9B fidelity, `int16` `RS_F=8` | `g2c_fixed_9b_w4g128gptq_int16_rsf8_g2c.log` | `rc: 0` — **95/108**, report body byte-identical to G1's baseline but for two lines (§7.1) |
| 9B fidelity, `int16` `RS_F=7` | `g2c_fixed_9b_w4g128gptq_int16_rsf7_g2c.log` | `rc: 0` — **98/108, 0 clips**; `--wq-cache-verify 2` **BYTE-IDENTICAL** under `RS_F=7` (§7.2) |
| 9B fidelity, `int16` `RS_F=7` **repeat** | `g2c_fixed_9b_w4g128gptq_int16_rsf7_g2c_b.log` | `rc: 0` on `=== tree: d3990bf` (clean) — **98/108**, report body identical to run `a` but for the json path (§7.3) |
| 9B emit attempt | `g2c_emit_9b_r2.log` | `rc: 1` — **G2C_EMIT REFUSED_AS_EXPECTED**, 0 images written (§4.2) |
| `spec_cites.py` on this document | — | **SPEC CITES: PASS** and **`--selftest` PASS**, 6/6 CAUGHT + positive control. *(The exact counts are deliberately not restated here: G2b had to correct its own self-reported count twice, because every later edit moves it. Run the checker.)* |
| `spec_cites` standing regression | — | **SPEC_CITES_REGRESSION PASS**, all eight pinned documents at their pinned counts, the `os.devnull` counter-experiment still suppressing 23 real failures |

**The standing regression earned its keep on this gate, on this gate's own
edits.** Its first run after the source changes reported
`evidence/qwen9b/g1/RUNG_INT8_STATE.md` at **FAIL 4 against a pinned 2**. The
cause was mine: the twelve lines this gate added to
`ref/gen_model_script.py`'s module docstring pushed the `PROMPTS` table down,
and G1's gate doc cites it by line for the four prompt seeds. Corrected
from lines 174-187 to lines 190-203, and the document went back to its
pinned 2 (both
pre-existing, both T1's). **That is the whole point of pinning a count rather
than a verdict**: a document nobody in this gate opened was broken by a
docstring edit three files away, and only the number moved to say so.

**And then it moved again, by one, and the checker could not see it.** A later
one-line docstring edit to the same file pushed `PROMPTS` from 190 to 191.
`spec_cites` still reported PASS, because a `QUOTE` check accepts the
quotation within ±6 lines of the cite — so an off-by-one citation passes.
Caught by re-reading the cited lines after the last edit. The docstring hunk
was later reverted for an unrelated reason (§2.2a), so `PROMPTS` ended where
it began and the citation's final value is `ref/gen_model_script.py:191-204` —
which is itself the point: the number moved twice and the checker reported
PASS at both. **That is spec §8 G2's stated blind
spot (a), demonstrated twice on one gate's edits**, and it is why the last
action before this commit was rendering every `path:NNN` beside the line it
names and reading them.

**`--selftest` runs on this document at all only because of G2b's repair** —
before `7bef84f` the case-3/4 constructor asserted on a **zero-quote**
document, which is the normal state of a gate doc written as lists and tables.

**The two byte gates are the load-bearing ones for §2** and they cover
different producers. `ref/scripts/regen_gate.sh` runs
**`ref/gen_model_script.py`** at 0.8B — the file whose head site moved — and
requires the emitted `.e.seq` to hash to the frozen `a69864d2…` and the `.txt`
to `cmp` against the committed copy. `evidence/qwen2b/rc/t4_bytes_unmoved.sh`
runs `ref/gen_layer_script.py` at 2B W8 and byte-compares the script, the
stream, the seqdata, the manifest and all 15 weight images.

**Scoped, because the obvious reading is slightly too strong** *(T5 review)*:
the gate that exercises the changed head site is `ref/scripts/regen_gate.sh`,
and it does
**not** byte-compare a head weight image — it hashes the `.e.seq` and `cmp`s
the `.txt`. The head's coverage there is **indirect**: the `.txt` carries every
step's `argmax` over the full 248,320-row head, so a head quantized from the
wrong matrix would move an argmax and fail the `cmp`. That is a strong signal
and it is not a byte comparison of the image. The 15 images `t4` *does*
byte-compare are 2B **layer** images from a different generator, and that set
contains no head. So: **both gates green means no emitted byte moved at either
frozen geometry, with the head covered by its argmax rather than by its
bytes** — which is exactly what it must mean when `md["head"]` is by
construction a copy of `md["emb"]` there.

**The sweep says mechanically that this gate did not touch the numeric path.**
`ref_selftests_g2c.log` covers `layer_ref`, `w4a8_ref`, `gptq`, `layer_fixed`,
`load_qwen35`, `perplexity_eval` and `calib_stats` at three tags — and
`calib_stats` is in that list, which is why the sweep had to be re-run. Its
`=== md5:` header records `layer_fixed 0a283c01`, `fixedpoint ea56f7a3`,
`w4a8_ref cd42ad17`, `layer_ref f19c2cdf`, **all four identical to the ones
G2a's `ref_selftests_g2a.log` recorded**, and `attn softmax+pv` reads
`2.666e-02 / 3.288e-02 / 3.918e-02` against `8e-02` at 0.8b / 2b / 9b — the
same three numbers Task 2's ruling produced and Task 3 re-confirmed.

**A third, narrower inertness check on `ref/audit_ranges.py`.** Its 0.8B report
was regenerated (`g2c_audit_ranges_0p8b_report.md`) and diffed against Track
Q's committed control `evidence/qwen2b/q2/audit/audit_ranges_0.8b_control.md`.
**Two lines differ and no number does:**

- the tie-mode label, this gate's own change — *"(tied embeddings)"* →
  *"(TIED embeddings: the LM head is a copy of `embed_tokens`)"*;
- the image-count sentence, **which is G2a's change, not this gate's** — the
  literal `187 weight images at 24 layers` became the parameterized
  `8·N_DN + 7·N_GQA + 1` in commit `b2f1223`, and the committed control
  predates it. *(Noted rather than smoothed: at 9B that formula gives
  8·24 + 7·8 + 1 = **249**, which is the same count §5's derivation reaches by
  a completely independent route — two derivations, one number.)*

Everything else in a 15 KB report — every `e`, `sh`, `m` range, INT4-clip
count, Frobenius error, headroom figure and verdict — is byte-identical.

### 9a. Re-run on the COMMITTED tree, with no dirty flag

The table above was produced while the tree was dirty. Everything cheap enough
to repeat was repeated on the commit itself, and every one of these logs
carries `=== tree: 19bbfd6` with **no `+dirty`**:

| gate | log | result |
|---|---|---|
| 0.8B artifact regeneration | `g2c_regen_gate_committed.log` | **REGEN_GATE_PASS**, sha `a69864d2…` |
| 2B W8 byte-lock | `g2c_t4_bytes_unmoved_committed.log` | **BYTES_UNMOVED PASS** |
| G2b's 54-row artifact pin | `g2c_final_bytelock_pin_committed.log` | **FINAL_BYTELOCK_PIN PASS** — every pinned artifact still byte-identical to the set `build_034`/`build_035` were built from |
| `sw/` board-free suite | `g2c_sw_boardfree_committed.log` | **BOARDFREE_PASS** |
| ISA guards, 0.8B / 2B / 9B | `g2c_isa_guards_committed_{0.8b,2b,9b}.log` | 32 / 32 / **33**, 0 failed |
| per-channel fit + control | `g2c_pack_fit_committed.log` | **G2C_PACK_FIT PASS** |
| live-tensor fit cross-check | `g2c_pack_fit_live_committed.log` | **G2C_FIT_LIVE PASS** |
| chat template | `g2c_chat_template_committed.log` | **G2C_CHAT_TEMPLATE PASS** |
| `spec_cites` standing regression | `g2c_spec_cites_regression_committed.log` | **SPEC_CITES_REGRESSION PASS** |
| 9B range audit (T5 review item 4) | `g2c_audit_ranges_9b_committed.log` | `rc: 0` — report **byte-identical** to the pre-commit one but for its `- generated:` stamp |

**Not repeated at first, and one sentence about it was wrong.** The two
168-step fidelity points (≈ 4 h each), the 9B emit attempt (≈ 3 h), the two
`audit_ranges` reports and the three-tag `ref/` selftest sweep were produced on
the pre-commit tree. *(Two of those have since been re-run ON the commit: the
9B range audit, byte-identical, in the correction below; and the `RS_F = 7`
point, whose authorized repeat ran at `d3990bf` clean and reproduced run `a`'s
report body exactly — §7.3. So the one number this gate hands to a user for a
decision is the one measured on the committed tree.)* For the quantization runs **the tree label is not the
handle anyway** — the source digest is, and all three print `9689cce9…`
(§2.2a is the incident that made that hold across both §7 points rather than
by luck). **That digest was the committed tree's at `d3990bf` and is not at
this commit**: the T5 review's comment-only fix to `ref/calib_stats.py` moved
it to `35d2a61f…`, with the cost and the reasoning set out at the end of
§2.2a. The runs' handle is what their logs record, which is unchanged.

> **CORRECTED 2026-08-31 (T5 review).** This paragraph used to end *"for the
> rest, the source files they exercise are in the commit unchanged from the
> versions they ran on."* **That is false for `ref/audit_ranges.py`**, whose
> mtime postdates both of its own reports: the stray-comment deletion landed
> after the 0.8B run began and after the 9B run began. The change was
> comment-only, but "comment-only" is an argument and this campaign's rule is
> to measure. Two things closed it:
>
> - **0.8B, closed empirically by the reviewer**: the report re-run on the
>   committed tree is **byte-identical** to
>   `g2c_audit_ranges_0p8b_report.md`, so the deletion moved nothing.
> - **9B, closed here**: re-run on the committed tree as
>   `g2c_audit_ranges_9b_committed.log` /
>   `g2c_audit_ranges_9b_committed_report.md` — **byte-identical** to `g2c_audit_ranges_9b_report.md` apart from the
>   `- generated:` timestamp, on `=== tree: d3990bf` with no dirty flag.
>   So the deletion moved nothing at either geometry, measured rather than
>   argued, and both reports in this gate are now backed by a clean-tree
>   twin.
>
> **`ref/audit_ranges.py` was deliberately NOT edited further while that
> re-run was in flight**, which is why item 8's pre-guard `head_w` load is
> carried as a note below rather than fixed: editing the file mid-run would
> have re-opened exactly the gap this correction closes.

---

## 10. NOT ESTABLISHED

1. **No 9B artifact exists on disk** — no image, no manifest, no `.emb.bin`,
   no stream. §4 is a HALT, and everything downstream of a real artifact is
   therefore unmeasured: the file-size cross-check `plan_weights(man, wdir=…)`
   would do, any sha256 manifest of a 9B artifact set, and the byte-level
   agreement between the derived manifest and an emitted one.
2. **The fit is `D`, not `M`.** It is computed from a manifest this gate
   derives, controlled against 187 + 187 committed rows at 0.8B and 2B and
   cross-checked against the real 9B quantized tensors through
   `plan_weights_from_wids` (§5.4) — but the wid **order** at 9B is checked
   only by the two older geometries, because no 9B emitter has ever run. Task
   11 makes it `M`.
3. **The runtime range audit has no 9B measurement** (§4.4), so
   `ref/audit_ranges.py` §5's eight deferred activation-dependent formats are
   still deferred at 9B — including the `S_F = 13` state soak and the
   residual-stream peak. Step 3's `--allow-clip` question is unanswered, not
   answered "no clips".
4. **The gate-port clamp is still unpriced at scored resolution** — 60/768
   heads with a changed decay, ≈ 7 h to price (§6.1). Unchanged by this gate.
5. **`ref/audit_ranges.py`'s ATTENTION items at 9B are recorded, not
   dispositioned** (§6.2). Deciding what to do about W4 error above the
   project's own 15 % bound is not this gate's.
6. **How a 9B trained with an open-`<think>` default behaves when handed a
   closed block is unmeasured** and needs the board (§8.4).
7. **Three of this gate's own changed lines are executed by nothing**, which
   is a narrower and more useful statement than G2a's blanket one:
   - **`sw/infer.py:707`** — inside `_load_and_quantize`, which needs a board.
     `sw/tok_meter.py` remains 0 % executed and `sw/infer.py`'s `step()`
     unexecuted, both carried from G2a's §9a.
   - **`ref/seq_chat.py:1391`** — the head quantization inside
     `_model_weights`' cache-miss branch. `ref/seq_chat.py --selftest` passes
     (§9) but does not reach it: the selftest never builds real weights, so
     the one line this gate changed in that file is covered by the import
     asserts and by nothing that runs.
   - **`ref/calib_stats.py:313`** — the collision refusal. It is a guard whose
     RED can only be reached by a model that registers an `nn.Linear` named
     `lm_head`, and none exists; **it has no RED test**, unlike the four ISA
     guards, which `isa_guards_check.py` trips both ways. That asymmetry is
     stated rather than hidden: this guard is asserted, not demonstrated.

   The three 9B-only host paths above are proven by import asserts plus the
   synthetic guard suite, exactly as G2a recorded for its own.
8. **The `RS_F = 7` rider decides nothing.** It has now been **repeated, and
   the repeat is byte-identical** (§7.3), so run-to-run spread is no longer
   the open question it was when this list was first written. **What is still
   not established about it**: no perplexity, no horizon beyond 168 steps, no
   second prompt set, no second checkpoint — and no measurement at all of what
   the change costs on the RTL side, which is `rtl/conv4_silu.sv:50` plus the
   host constants Task 10 has been told not to touch. A deterministic repeat
   tests the process, not the sampling; it raises confidence that 98/108 is
   what this configuration scores, and says nothing about whether 98/108 is
   worth an RTL literal.
9. **`evidence/qwen2b/q2/audit/gate_port_probe.py` still opens the first shard
   only**, and is usable at 9B only through G1's fork. Not fixed here — it is
   Track Q's committed evidence (§11).

---

## 11. Handoffs

**To Task 7 (G3.1 — the 16-bit scratch ISA):**

1. **The LM head's packed W4 g128 footprint is 524,451,840 B = 500.2 MiB at
   wid 248**, `LAYOUT_ILV`, chunk_rows 2048, base `0x452b0000` on every
   channel under the nch=4 repack. The plan assigns *recording* it to G3 and
   says to carry this gate's number forward rather than measure it twice.
2. **Landing the 16-bit scratch ISA alone does NOT unblock 9B emission, and
   this is the correction that matters most for planning.** The wall the
   emitter actually stops on is **`Mach.CONV_FIELD_MAX`** (§4.2, measured),
   and `Mach.ARG0_HEAD_BITS` is one line behind it — **both are Task 10's**.
   `ISA_SADDR_MAX` is Task 7's and is real, but it is not first and clearing
   it changes nothing on its own: the emit loop reaches
   `ref/gen_model_script.py:595`'s `M.convz(0, LR.CONV_DIM)` first and  <!--cites:noquote-->
   `ref/gen_model_script.py:596-597`'s `for h in range(LR.LNH): M.dnz(h)` on  <!--cites:noquote-->
   the very next statement, so `CONV_FIELD_MAX` refuses, and `dnz`'s
   `ARG0_HEAD_BITS` guard would refuse at `h = 16` immediately after.

   > **CLASS B, dated note 2026-09-10 (pre-ship documentation chore).**
   > Those two quotations are of the emitter as it stood at G2c and **the
   > source no longer exists**: the state-spill's S3 retired the
   > 768-command DNZ/CONVZ preamble outright, and the surviving statement
   > is the single `GLS.sched_preamble(M, types)` call at
   > `ref/gen_model_script.py:600`. The base line numbers and the base text
   > are kept because the point of this paragraph is the ORDER in which the
   > emitter hit its walls at G2c, which is a fact about that tree.
   §4.3 has the full list with the owning task per field. **All five must fall before any 9B artifact comes out of
   `ref/gen_model_script.py`.** What Task 7 does own here is the split G2a
   made — `SCRATCH_MAX` (the array, 65,536) apart from `ISA_SADDR_MAX` (what
   an ARG word carries, 32,768) — which is what makes that refusal loud
   instead of an aliased address.

**To whoever next quantizes 9B (Task 10, 11 or a review):** the weight cache
at `/var/tmp/fable5_wq` holds the images §7's numbers were scored on, keyed
`9689cce9…`, and **this commit's digest is `35d2a61f…`** — a comment-only
move, explained at the end of §2.2a. **The first 9B quantization after this
commit pays ≈ 3.03 h and that is expected, not a defect.** If it matters,
`evidence/qwen9b/g1/cmp_wq_cache.py` is the tool that proves the rebuilt
images identical, and this gate ran it twice already (§2.2).

**To Task 10 (G3.4):** `Mach.CONV_FIELD_MAX` is 8,191 and `CONV_DIM` is
**8,192** at 9B — a one-count miss that refuses a whole-block `convz`. Widening
it is Task 10's, and the RTL field must move with it.

**To Task 11 (G4a — the SEQ streams), which now also inherits the images:**

3. **The 249-image pack, the manifest and the `.emb.bin` table are Task 11's
   to emit**, not just the streams. Everything needed is pinned here: the
   operating point (§4.1), the expected image count and per-channel fit (§5),
   and the two verified inputs (§3). When they exist, `plan_weights` should be
   re-run against the REAL manifest with `wdir` set — which additionally
   cross-checks every image's file size against `nrows·stride` — and the
   result compared against §5's derived numbers. **A mismatch there is a
   finding about this gate's derivation, and it should be reported as one.**
4. **`gen_model_script`'s runtime range audit has no measurement in this
   campaign yet** (§4.4). It is the only thing that closes the eight
   activation-dependent formats `ref/audit_ranges.py` §5 defers, including the
   `S_F = 13` DeltaNet-state soak and the residual-stream peak at `RS_F = 8`
   that A1.8's rider is about.

**To Task 15 (G6 — board bring-up):**

5. **The 9B chat wrapper needs `enable_thinking=False` named explicitly** in
   any HF reference it is compared against (§8.3). Its ids do not move; the
   reference invocation does.
6. **Whether a 9B trained with an open-think default answers well when handed
   a closed `<think>\n\n</think>\n\n` block is unmeasured** and is a
   model-behaviour question, not a plumbing one. It needs the board.
7. **`EMBLOG2 = 13` is exactly `SEQ_EMBLOG2_MAX`** (§5.2a) — no headroom.

**To whoever next touches `evidence/qwen2b/q2/audit/gate_port_probe.py`:** it
still opens the checkpoint with `find_checkpoint` (first shard only) and still
prints *"clamps in force … (layer_fixed.py:805-806)"*, a citation that was
already stale when G1 found it and is staler now. It is **Track Q's committed
evidence** and this campaign does not edit committed evidence in place, so
both are carried, not fixed. Running it at 9B requires
`evidence/qwen9b/g1/gate_port_probe_9b.py`.

**And it is not alone — five more frozen readers have the same defect**, all
under `evidence/qwen2b/q2/`, all Track Q's or Track V3's committed evidence,
none touched here and none runnable at 4B or 9B without the same `runpy`
patch: `evidence/qwen2b/q2/audit/deadrow_probe.py:5`,
`evidence/qwen2b/q2/audit/res_scale_seed_probe.py:30`,
`evidence/qwen2b/q2/audit/over15_probe.py:18`,
`evidence/qwen2b/q2/audit/ln_f_fold_probe.py:17` and
`evidence/qwen2b/q2/v3/calib_crosshost_check.py:94`. **Recorded so nobody
re-discovers it six times.** Two callers that look like the same pattern and
are NOT defects: `ref/perplexity_eval.py:782` takes
`os.path.dirname(find_checkpoint())` — it wants the snapshot DIRECTORY, which
is what the singular form is for — and `sw/chat_seq.py:6014` is inside a
comment.

---

## 12. Deviations declared

1. **The commit block gained files the plan's block does not name.** Task 5's
   block names `evidence/qwen9b/g2/G2C_CHAIN.md`,
   `evidence/qwen9b/g2/run_g2c_emit.sh` and `evidence/qwen9b/g2/run_g2c_fit.sh`;
   all three exist. Beyond them the commit names, individually: one more
   launcher, `run_g2c_point.sh` — a **fork** of
   `evidence/qwen9b/g1/run_g1_point.sh`, because
   the original writes into `evidence/qwen9b/g1/`, which is G1's committed
   evidence and is cited by section; two measurement tools,
   `g2c_pack_fit.py` (§5) and `g2c_chat_template.py` (§8); and every log,
   json and report those runs produced. **`evidence/qwen9b/g2/` was never named
   as a directory** — it is a shared tree (T2, T3 and T4 all wrote there) and a
   directory pathspec on it is exactly the 2026-08-25 near-miss.
2. **`evidence/qwen_next/spec_cites.py` is not in the plan's Task 5 file list
   and is in the commit.** One line: `evidence/qwen9b/g2/G2C_CHAIN.md` comes
   out of `PENDING`, because this gate creates it and a stale `PENDING` entry
   suppresses the `EXIST` check on a live path — the harm T1, T2, T3 and T4
   each declared when they removed theirs. Nothing else in that file moved.
3. **`ref/load_qwen35.py` is in the plan's file list and is NOT in the commit.**
   Its untied-head site was already done by Track L (`load_model` returns
   `head` / `tied` / `head_key`), so there was nothing to change. Same
   disposition G2a recorded for `ref/calib_stats.py`, which G2a listed and did
   not commit.
4. **`sw/chat_seq.py` and `docs/INSTRUCT_SPEC.md` carry the host-side chat
   template and are in NEITHER the plan's Task 5 file list nor this commit.**
   Step 5 asks for the template to be "rebuilt"; §8.3 measures that **the
   wrapper's ids do not change at 9B**, so there is nothing to rebuild — the
   change is to the REFERENCE a selftest compares against, and that selftest
   is pinned to the 0.8B geometry the frozen bitstreams still serve. Landing a
   9B reference there is handed to the task that owns those files. Had the ids
   moved, this would have been a stop rather than a handoff.
5. **`evidence/qwen9b/g1/RUNG_INT8_STATE.md` — G1's closed gate doc — is in
   this commit, for two reasons and no others.** (i) A citation drift this
   gate caused: `ref/gen_model_script.py`'s docstring grew and pushed the
   `PROMPTS` table down, breaking a line citation G1's doc makes (§9). (ii) A
   dated supersession note, appended not rewritten, on the paragraph that says
   both range tools open the first shard only — half of that is no longer true
   (§2.1a). G1's numbers, verdict and structure are untouched; the standing
   regression pins the document at `FAIL 2` and it is still `FAIL 2`.
6. **The 9B emit was run twice and the first log is kept.** The first attempt
   (`g2c_emit_9b.log`) failed on a `FileNotFoundError` — a repo-relative
   Hessian path against the generator's `cd ref` — and the launcher's verdict
   block scored that non-zero exit as the expected ISA refusal. That is the
   "passed for the wrong reason" class G2a caught in `damage_defect_b.py`, on
   the same day, one gate earlier. It is kept rather than deleted because the
   correction is the evidence: the launcher now **discriminates**, requiring
   the failure to name one of the five ARG fields and reporting
   `UNEXPECTED_FAILURE` otherwise. `g2c_emit_9b_r2.log` is the measurement.
7. **A first, unwrapped-table chat-template log was produced and deleted
   before any commit.** Its numbers were identical to
   `g2c_chat_template_final.log`'s; the table's column widths were narrower
   than the digests they held, so the sha256 columns ran together and the log
   was unreadable. Deleted rather than committed alongside, because two logs
   with the same numbers and one of them illegible is worse than one.

---

## 13. FINAL DISPOSITION — the `RS_F = 7` ruling, and what it re-opens

**USER RULING, 2026-09-01: `RS_F = 7` ADOPTED. The 9B operating point is
`int16` + `RS_F = 7`.** The ratified O5 condition — *"take Q8.7 only if it
removes residual clipping WITHOUT costing top-1"* — is met and exceeded: the
clipping goes to zero, `|x|max` comes off the 32,767 rail, rank max and top-5
overlap do not move, and top-1 gains three tokens. §7.3's repeat is
byte-identical over the whole report body, so the +3 is not draw noise.

**A1.8 (*"`RS_F` stays 8"*) is superseded by this ruling.** The spec and plan
are being amended by a separate docs-only task; **nothing under `docs/` is
touched from here**, and this section is deliberately written so it does not
depend on the amendment landing.

### 13.1 What this gate did NOT do

**No code changed for the ruling.** This gate measured the number; it did not
implement it. At this commit:

- `rtl/conv4_silu.sv:50` still reads `rshr64(64'(acc1), 9)`;  <!--cites:noquote-->
- every host constant that reads `8` still reads `8`;
- no 9B artifact carries `rs_f: 7`, because **no 9B artifact exists** (§4).

That is the correct terminal state for a gate whose plan told it to report the
number and decide nothing, and whose successor tasks own every file involved.

### 13.2 The RTL: one literal, and its host twin follows by itself

**`rtl/conv4_silu.sv:50` → Task 10.** The line is  <!--cites:noquote-->

```systemverilog
        pre = rshr64(64'(acc1), 9);          // RS_F + CW_F - 12 = 9
```

> **CLASS B, dated note 2026-09-10 (pre-ship documentation chore).** §13.1
> and §13.2 quote the shift as it stood **at this gate's commit**, which is
> the whole point of §13.1 — it records that G2c changed no code. **Task 10
> landed the change at `bbda679`**: the literal is 8 now, and at HEAD it is
> at `rtl/conv4_silu.sv:54`, under the A2.1 comment block that begins at
> `rtl/conv4_silu.sv:50`. So the pointer still names the right block and
> only the value moved. The quotations keep their exemption markers rather
> than being rewritten, because rewriting them would delete the fact this
> section exists to record.

With `CW_F = 13` (`ref/layer_fixed.py:145`) and `RS_F` now 7, the shift becomes
**8**, and the comment's own derivation is what says so. **This is the only
RTL literal the ruling moves** — the one G1, wave 3 and the plan all named.

**The host twin needs nothing**, and that is worth stating because it is easy
to assume otherwise: `ref/layer_fixed.py:1512` is
`pre = rshr(acc, RS_F + CW_F - 12)` — it already reads the knob, so the
reference model tracked `RS_F = 7` through both §7 runs with no edit. **The
host is ahead of the RTL here, not behind it**, so Task 10's job is to make
the silicon agree with a model that is already right.

### 13.3 The host constants: the reflex is to change them, and it is WRONG

The plan's `sw/` literal census (Task 3 Step 4, *"the three hard-coded `RS_F`
consumers the spec names"* plus *"three sites the spec's census does not name,
all of which break at `RS_F = 7`"*) is the right checklist, but **its line
numbers are pre-G2a and G2a moved every one of them.** They are given here at
their current locations. *(The census's own plan lines are deliberately not
cited by number: a concurrent docs-only task is amending that document, and a
line citation into a file being edited is the drift class this gate was bitten
by twice — §9.)*

| census row (pre-G2a) | current site | disposition under the ruling |
|---|---|---|
| `chat_seq` line 221, the literal `−22` | `sw/chat_seq.py:355-360` — `head_logit_exp0()` + `HEAD_LOGIT_EXP0` | **already derived by G2a; do NOT move to −21** |
| `chat_seq` line 3717, the literal assert | `sw/chat_seq.py:5032` — `HEAD_LOGIT_EXP0 == -22` | **stays `−22`** |
| `chat_seq` line 2112, the head-spec comparison | `sw/chat_seq.py:3233` — `head_logit_exp0(self.head.spec.rs_f)` | **already per-artifact; nothing to do** |
| `chat_seq` lines 4283-4284, the algebra | `sw/chat_seq.py:5480-5485` | **already asserts `head_logit_exp0(7) == HEAD_LOGIT_EXP0 + 1`** |
| `head_cache` line 105, the `RS_F` fallback | `sw/head_cache.py:105` — `RS_F_FALLBACK = HW.RS_F_DEFAULT` | **stays 8** |
| `head_cache` lines 638-639, the pinned exponents | `sw/head_cache.py:636` — `want == [-22, -17, -7]` | **stays** |
| `hwmap` line 225, `MANIFEST_META_KEYS` | `sw/hwmap.py:503` — `RS_F_DEFAULT = 8` | **stays 8** |

**Why they stay, which is the whole point of G2a's design.** `rs_f` is a
**caller-gated** manifest key — `ref/gen_model_script.py:666` passes
`rs_f=None if MS.TAG in BYTELOCKED_TAGS else RS_F` — so the frozen artifacts
carry **no** `rs_f` key at all and a reader answers the default. **Measured on
the committed manifests rather than asserted:**
`tb/scripts/w4/model_v2_s1.weights.json` has **no non-wid keys whatsoever**,
and `tb/scripts/w5/model_w8_2b_s1.weights.json` has exactly one,
`emb_row_bytes`. Neither carries `rs_f`. So every constant above describes
**the frozen artifacts**, not the 9B one — and the 9B artifact will carry
`rs_f: 7` **explicitly**, which the live path already honours
(`sw/chat_seq.py:2686`). **Changing `RS_F_DEFAULT` or `HEAD_LOGIT_EXP0` to
match the ruling would silently mis-dequantize every 0.8B and 2B logit by a
factor of two** — the exact failure `ref/gen_layer_script.py:1649`'s emit/
consume assert exists to prevent, pointed the other way.

**So the handoff to the owning host task is a VERIFICATION, not a change:**
confirm these seven sites are still 8 / `−22` after the ruling lands, and that
`sw/chat_seq.py --selftest` still passes. Selftest [18] at
`sw/chat_seq.py:5059-5062` already checks the *moving* half —
`head_logit_exp0(7) == HEAD_LOGIT_EXP0 + 1` and
`split_manifest({"rs_f": 7})["rs_f"] == 7` — so the mechanism is tested today,
at `RS_F = 7`, with no artifact.

### 13.4 The emission task: `rs_f: 7`, and one hazard worth closing

**The emitter needs no change to write `rs_f: 7`.** `Mach.dump_weights` is
caller-gated and `ref/gen_model_script.py` already passes
`rs_f=None if MS.TAG in BYTELOCKED_TAGS else RS_F`, so a 9B emit under
`FABLE5_RS_F=7` writes `rs_f: 7` today. **Two items travel with that:**

1. **`b9e0851:ref/layer_fixed.py:74` defaults `FABLE5_RS_F` to 8** — CLOSED
   2026-09-10 (#26): `RS_F` is derived from `MS.TAG` now and the citation is
   PINNED to the tree this finding was made on. **A 9B artifact
   emitted without the env var set is **self-consistent and wrong** — body,
   manifest and host would all agree on 8, no assert would fire, and the
   result would simply not be the ratified operating point. **The 9B operating
   point should be enforced rather than remembered**: either make the default
   model-selected, or have the emission path assert `RS_F == 7` at
   `FABLE5_MODEL=9b`. **Design call for the owning task; recorded here because
   nothing currently catches it.**
2. **`ref/layer_fixed.py:58-60` now carries a stale comment** — it says
   *"A1.8 leaves that literal ALONE — `RS_F` stays 8"*. Superseded by the
   ruling. Note that `ref/layer_fixed.py` is in `ref/fidelity_check.py`'s
   `_WQ_SOURCES`, so **fixing that comment costs a 3.03 h weight-cache
   miss** — the trade §2.2a documents twice. Worth batching with whatever
   else opens that file.

### 13.5 The measurement caveat carried forward: no perplexity point

**AVAILABLE AT G4, NOT RUN.** The ruling rests on a 168-step teacher-forced
top-1 comparison at four prompts, repeated byte-identically. It does **not**
rest on a perplexity measurement, and none was taken at `RS_F = 7` at any
container.

The harness for one exists and is pinned: `ref/perplexity_eval.py` over
`ref/ppl_corpus_eval.txt`, whose **24,528 scored positions carry over to 9B
unchanged** because the tokenizing files are byte-identical across all four
models (§8.1) — so a 9B PPL point is directly comparable to the 2B campaign's
without re-pinning anything. **It is the natural place to check that a +3 on
108 teacher-forced tokens is a real quality gain rather than a favourable
draw on a small sample**, which four prompts cannot settle however many times
they are repeated.

Carried as **available-at-G4-not-run** rather than as a blocker: the ruling is
taken, and G4a replays the whole model anyway.

### 13.6 Routing summary

| item | goes to |
|---|---|
| `rtl/conv4_silu.sv:50`, `9` → `8` | **Task 10** (G3.4) |
| verify the seven host sites stay 8 / `−22`; `chat_seq --selftest` | the task that owns `sw/chat_seq.py` / `sw/head_cache.py` |
| 9B manifest `rs_f: 7`, plus enforcing `RS_F = 7` at `FABLE5_MODEL=9b` | the emission task (**Task 11**, which §4 already hands the images) |
| `ref/layer_fixed.py:58-60`'s stale A1.8 comment (costs a cache miss) | batch with the next `ref/layer_fixed.py` opener |
| a 9B perplexity point at `RS_F = 7` | **G4**, available-not-run (§13.5) |
| everything else this gate opened | §11 |

**Task 5 is COMPLETE.** The HALT (§4) is Task 7's and Task 10's to clear and
Task 11's to close; the ruling above is routed and not acted on here.
