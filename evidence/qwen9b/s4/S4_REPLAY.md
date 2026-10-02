# S4 — the 9B model on the DDR-state design: TOKEN-IDENTICAL, and the layer term measured

**Task S4 of `docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md`.**
**Spec:** `docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md`
§8.1, §8.5, §9. **Consumes:** S1's ISA, S2's RTL, S3's chain, and Task 11's
token record (`evidence/qwen9b/g4/G4A_REPLAY.md` §4.1a) — the answer this
gate has to reproduce.

Every number below is labelled **M**(easured), **D**(erived),
**T**(ranscribed from another gate), **E**(stimate) or **S**(tated), and
every numeric step went through `evidence/qwen9b/run.sh` **on snoke**, which
refuses to overwrite a log and stamps host / date / tree sha + dirty flag /
command / interpreter into every one.

---

## 0. Verdict

**DONE. The acceptance bar is met, and the layer term moved in the
direction nobody promised: DOWN.**

| product | state |
|---|---|
| the four 9B model streams, re-emitted at v2.1 | **DONE**, and each **EMITTED TWICE and byte-identical** — every artifact, not only S3's four (§2) |
| `ref/seq_model.py --gate` on all four | **`SEQ GATE: PASS` ×4**, 2358/2358 checkpoints bit-exact, **`STATE BIT-EXACT`** (112 blocks stored PER TOKEN — DN 24 + conv 24 + KV 64, `evidence/qwen9b/s3/S3_CHAIN.md:201`) (§3) |
| the chip replay, the whole model, 4 seeds | **`TB_SEQ_CHIP PASS` ×4**, `tokens 6`, `smem 112`, `miss 0` (§4.2) |
| **TOKEN IDENTITY with Task 11 — the bar** | **`TOKENS IDENTICAL TO G4A` on 4 of 4 seeds**, 24 of 24 tokens (§4.2) |
| the layer term, measured on the new design | **45.674 ms/token** (mean over 6 steps) against Task 12's **46.079** — **0.405 ms LOWER**, and the difference is 768 × 132 cycles exactly (§5.3). *(COMPUTE lane, LCYC = `busy_cmp`, spec A1.4; the DMA lane's 5.133 ms/token is a separate lane and is not included — see §5.3.3.)* |
| the SLD/SST dispatch cost on the compute lane | **ZERO cycles**, both opcodes, 1,346 commands (§5.3) |
| the DMA lane's cost | **`SDMA_CYC` 1,283,339 cycles/token = 5.133 ms**, 11.24 % of the layer term, at the TB's modelled `LAT = 8` (§5.3) |
| DNST at `RLAT = 2` | **2,958 cycles/command, min == max over 4,608**, against Task 12's 3,090 at `RLAT = 6` (§5.3) |
| F1/F2 stalls actually taken | **MEASURED and BOUNDED by a second instrument fix round 1 built** — the DRAINING census cannot produce one (§5.4). Under the sequencer's own back-pressure rule, on the whole model, **F1 = 0** and **F2 = 120,953 cycles/token = 0.484 ms = 1.05 % of the compute lane** *(queue-full dispatch hold, `rtl/layer_chan.sv:1448-1457`; the spec's F2 fence, counted separately as `F2 FENCE`, is 0 on the shipped schedule — whose double-buffering, four-deep in-order transfer queue and F1 shadow never arm it (§5.5.6) — and the counter FIRES, 1,847 cycles, on the perturbed arm of `evidence/qwen9b/s4/076_census_nodrain_red2.log`, §5.5.6)*, the same to the cycle at `LAT = 8` and at the chip TB's `WLAT = 40`, and `LCYC` minus the holds is §5.3.1's 11,418,473 **per step, exactly** (§5.5) |
| the whole model, end to end | **196,706,821 cycles**, **3,391,371 FEWER** than Task 11's 200,098,192 — 1.7 % faster with the same answer (§4.2) |
| memory | **0.242 GiB** peak total RSS for four full-model replays (§4.3) |

**Two defects found, both in this campaign's own instruments, both reported
rather than worked around silently:** the emit-twice gate could not fire on
the model target (§2.1) and Task 12's census runner and control predate the
state region (§5.1, §7). **Fix round 1 repaired the first of those and two
more the review found** — `evidence/qwen9b/g4/run_g4a_replay.sh`'s default
`LOGDIR` (§7 item 4) and the missing non-draining census (§5.5) — each with
its own RED.

---

## 1. Provenance

### 1.1 The operating point

| | |
|---|---|
| model | `FABLE5_MODEL=9b`, H = 4096, FFN = 12288, 32 layers (24 DN / 8 GQA) |
| fidelity width | `FABLE5_RS_F=7` (A2) |
| pack | `SEQ_PROFILE=epsnorm SEQ_NCH=4 SEQ_REPACK=1` — the only pack that fits (G4a §3.1) |
| quantizer | `--w4-group=128 --res-scale=1`, GPTQ against `ref/calib_stats_9b_h.npz` |
| `--allow-clip` | **NOT passed** — the runtime range audit is left free to fail, and it does (G4a §3.4) |
| ISA | SEQ_ISA v2.1 (S1 B15), 224 SLD/SST per token (S3 §0) |
| RTL | S2's `rtl/layer_chan.sv` + `rtl/state_dma.sv`; DN state in DDR, `dn_step` at (RLAT 2, P2_WAIT 0) |

### 1.2 Hosts

**Every numeric step ran on snoke** — the plan's Global Constraints ban
darthplagueis from numeric compute and S3's review reproduced that host's
wrong-arithmetic abort 3 times in 9. The `=== host:` header of every log
named here reads `snoke`. The citation-drift and `spec_cites` passes are
text tools and ran on darthplagueis, as every earlier task's did.

### 1.3 The trees

| what ran | tree | clean |
|---|---|---|
| the four emissions, the structural probe | `2c881f4` | yes |
| the token-compare RED/GREEN | `7609072` | yes |
| the SEQ gates ×4 | `b4c944a` | yes |
| the chip vectors, the 4-seed replay, the memwatch, the census, the census control | `0fe1407` | yes |
| the citation-drift plan and verify | `57deb5f` | yes |
| **fix round 1**: the emit-twice gate's RED/GREEN, the LOGDIR guard's RED/GREEN, the non-draining census's control, and both model measurements (launched 11:58 and 12:00) | `8f89870` | yes |
| **fix round 1**: the smoke re-gate, launched after the commit that added its script | `2cf08af` | yes |
| **fix round 2**: the six-arm non-draining control, the run that made the spec's F2 fence fire (`076`) | `c530350` | yes |
| the fix round's citation-drift plan and verify | (§10) | yes |

Every one of those is a commit of this task, and the `=== tree:` line of
every log names it with no `+dirty`. The emissions and the replay overlap in
wall-clock time; §7 says why and what it would have cost if a gate had
failed.

---

## 2. Step 1 — the four model emissions, under an emit-twice gate that had to be BUILT

### 2.1 The wired gate COULD NOT fire on the model target — the defect S4 found, and the repair fix round 1 made

S3 fix round 2 wired emit-twice-and-compare into the three 9B artifact
targets. It fired for the two SMOKE targets. **It could not fire for the
MODEL target at all**, for two independent reasons, both of them the runtime
range audit this campaign deliberately leaves failing:

1. **make abandoned the recipe before it.** The emitter was a plain recipe
   line — no `-` prefix, no `|| true` — and `gen_model_script.py` exits
   non-zero at 9B without `--allow-clip`
   (`ref/gen_model_script.py:711-721`, a `raise SystemExit(` whose message
   begins `RANGE AUDIT FAILED`, so the interpreter exits **1** and make
   reports `Error 1` and exits **2**). G4a's own emission logs show exactly
   this — `=== rc: 2` (`evidence/qwen9b/g4/030_emit_9b_s2.log`; the Makefile
   line number in that log is Task 11's tree's, not this one's) — and so does
   S4's own `evidence/qwen9b/s4/001_emit_9b_s1.log:102`, where the line make
   names is the EMITTER's, not the block's. The
   `if [ "$(W9_EMIT2)" = 1 ]` block was never reached.
2. **Even if reached, the gate would have refused the artifact.**
   `evidence/qwen9b/s3/emit_repeat.sh` treated a non-zero emitter rc as
   `run i ABORTED` and FAILED — so it could never PASS on an artifact whose
   emitter exits non-zero **by design** — and it discarded the emitter's
   stdout, so it could not have inspected the audit line either.

**BOTH ARE REPAIRED IN FIX ROUND 1** (§2.1a). At the time of the emissions
both files were outside S4's commit block, so S4 did not edit either. It
built `evidence/qwen9b/s4/emit_model_gated.sh` instead: **the same make target,
run twice, with only `W9_BASE` different**, so the two emissions cannot
differ by command construction or by an environment variable — S3's rule,
kept — followed by S3's four-file comparison **and everything else a model
emission writes that no smoke artifact has**:

| compared | why it is not optional |
|---|---|
| `.txt`, `.e4.seq`, `.e4.seqdata.bin`, `.state_final.bin` | S3's four (`evidence/qwen9b/s3/emit_repeat.sh:62`) |
| `.state.bin` | the image the host uploads and the TB maps |
| .e4.seq.json | the stream's metadata |
| `.emb.bin` (1,940 MiB) | the embedding table; a bit-flip here moves every token |
| the 249 `_w<wid>.bin` images (3,902 MiB) | the weights; keyed by wid, because the two prefixes' basenames differ by construction |
| `_cv<L>.bin` | the conv taps the host uploads |
| .weights.json, prefix-normalised | the manifest legitimately records BASENAMES (`ref/gen_layer_script.py:1630` for the weight images, `ref/gen_layer_script.py:1749` for the conv images), and nothing else may differ |

The comparison half was self-tested before the six-hour runs started, against
S3's own committed smoke pair (`lay9b_s1` vs `emit2/lay9b_s1/rep1`): every
file IDENTICAL, and .weights.json found to differ **only** in the recorded
basenames — which is why it is compared prefix-normalised rather than raw.

**The rc contract.** The script accepts rc 0, or a non-zero rc **only** when
the output carries `RANGE AUDIT FAILED` *and* the finalizer's `SEQ: … records
… -> ` line *and* no traceback or assertion. Anything else is `ABORTED`, and
an aborted emission is PRESERVED, not retried — S3 saw three emitter runs die
inside `w4a8_ref.matvec_y32`'s overflow assert and the dispatch note requires
any repeat to be reported rather than run over.

### 2.1a The repair, and the gate fired BOTH ways at seconds instead of hours

Fix round 1 repairs both halves and proves the repair rather than asserting
it. **No model artifact was re-emitted to do it**:
`evidence/qwen9b/s4/emit_model_gated.sh` had already proved those four
artifacts over a strictly larger file set (§2.1, §2.2), and a second 40
core-hours to re-prove the WIRING would have bought nothing.

**(a) `tb/Makefile:1409-1439`.** The emitter's rc is CAPTURED — and its
output tee'd to a file under `$(EMIT2_DIR)` instead of being thrown away —
and the emit-twice block at `tb/Makefile:1431-1438` is reached on rc 0, **or**
on a non-zero rc only when the output carries `RANGE AUDIT FAILED` **and**
the finalizer's `SEQ: … records … -> ` line **and** no traceback or
assertion. Any other non-zero rc aborts BEFORE the block. After the block the
target still exits with the EMITTER's rc, so `rc 2` keeps meaning what Task
11's and S4's emission logs say it means; a failure of the block itself exits
non-zero whatever the emitter did.

**(b) `evidence/qwen9b/s3/emit_repeat.sh:83-100`.** The same contract, and it
stops discarding the emitter's stdout: each run's output is kept beside its
artifacts, which is what makes the contract checkable at all.

**(c) The proof, at SHIM scale.** `evidence/qwen9b/s4/emit_shim.py` stands in
for `MODELPY`: it ignores the generator name, writes deterministic
SEED-DEPENDENT bytes at the four compared suffixes, prints the finalizer line
and the audit line, and exits 1 — the emitter's exit contract without GPTQ,
without the checkpoint and without the HuggingFace cache. **M**,
`evidence/qwen9b/s4/070_emit2_gate_red.log`, snoke, tree `8f89870`, `rc: 0`,
all four arms inside **1 s** of wall clock (`=== date: …12:03:00` to
`=== end: …12:03:01`), verdict line **`EMIT2_GATE_RED: PASS — the model
target's emit-twice block is REACHED`** — **the first of a four-line
verdict**, the rest reading `on the by-design audit rc and PASSES; it REFUSES
a perturbed second` / `emission; and it is NOT reached when the emitter fails
for any other` / `reason (no audit line, or a traceback)`:

| arm | what the emitter did | the block | make rc |
|---|---|---|---|
| **GREEN** | rc 1 with the audit line and the `SEQ:` line | **REACHED**: `.txt`, `.e4.seq`, `.e4.seqdata.bin`, `.state_final.bin` all `IDENTICAL`, `EMIT_REPEAT: PASS 1 identical emission(s)` | 2 (make's translation of the recipe returning the emitter's 1) |
| RED 1 | the same, with `EMIT2_FORCE_FAIL=1` moving the second emission to seed + 1 | **REACHED and REFUSED**: four `DIFFERS` lines, `EMIT_REPEAT: FAIL` | 2 |
| RED 2 | rc 1 with **no** audit line | **NOT REACHED** — `W9_EMIT2 GATE: ABORT -- rc 1 is NOT the known range-audit failure; the emit-twice block is SKIPPED`, and no `EMIT_REPEAT:` line anywhere in the arm | 2 |
| RED 3 | a `Traceback` and then the audit line | **NOT REACHED**, same marker | 2 |

RED 1 is the arm the gate exists for — it is the shape of the darthplagueis
arithmetic defect, a second emission that disagrees. RED 2 and RED 3 are the
arms that keep the FIX honest: a *broken* emitter must not be let into a
comparison and pass it because both runs broke the same way.

**(d) The SMOKE path still passes, and its bytes did not move.**
`evidence/qwen9b/s3/emit_repeat.sh` is shared with the two smoke targets,
whose artifacts §5.2 and §5.5 replay. **M**,
`evidence/qwen9b/s4/071_smoke_regate.log`, snoke, tree `2cf08af`, `rc: 0`,
**371 s**, verdict line **`SMOKE_REGATE: PASS — the smoke target's
emit-twice gate still passes`** — **the first of a three-line verdict**, the
rest reading `through the repaired emit_repeat.sh, and every byte of lay9b_s1
is` / `where it was`. `w9_9b_smoke_scripts` at `W9_SEEDS=1` emitted
`lay9b_s1`, emitted it again and compared — `EMIT_REPEAT: PASS 1 identical
emission(s)` — and because that comparison is between the two NEW emissions
and could not by itself notice a re-emission that agreed with itself and
disagreed with the artifact already on disk, the script digests the five
`lay9b_s1` files before and after: **all five UNMOVED**, including
`.state.bin` at `36969da490db28c4…`, which is the digest S3's
`evidence/qwen9b/s3/088_state_sha_manifest.log` recorded. **One seed, not
four, and it is declared**: the target's code path does not vary with the
seed, and the machine was carrying the two model censuses at the time.

### 2.2 The four emissions

**M**, `evidence/qwen9b/s4/00{1,2,3,4}_emit_9b_s{1,2,3,4}.log`, snoke, four
seeds concurrently at `OMP_NUM_THREADS=10`, `rc: 0` on every one, last line
**`EMIT_GATED s<n>: PASS — two independent emissions, byte-identical`**.

| | emission A | emission B | total |
|---|---|---|---|
| s1 | 03:19:03 → 06:55:33 (**3 h 36 min**) | → 10:25:32 (**3 h 30 min**) | 7 h 06 min |
| s2 | → 06:54:40 | → 10:25:31 | 7 h 06 min |
| s3 | → 06:56:10 | → 10:26:14 | 7 h 07 min |
| s4 | → 06:55:48 | → 10:24:55 | 7 h 06 min |

**Eight full GPTQ emissions, ~40 core-hours, one verdict each.** Task 11
budgeted 3 h per emission at `OMP_NUM_THREADS=16`; four concurrent at 10
threads cost 3 h 33 min each, so the concurrency is nearly free and the
gate's second pass is the real cost.

**The streams — M.** All under `tb/scripts/w9/` with the stem
`model_9b_s<n>`; the set is regenerable and NOT committed.

**Prompt-dependent — one per seed:**

| file | s1 | s2 | s3 | s4 |
|---|---|---|---|---|
| `.e4.seq` bytes | 2,536,576 | 1,268,624 | 1,268,624 | 2,536,576 |
| `.e4.seq` sha256 | `9760899df53b3b42…` | `dae5873430562646…` | `8dfad7db118d5da4…` | `3483d82ab9116456…` |
| `.txt` bytes | 243,693,027 | 243,693,031 | 243,693,012 | 243,693,059 |
| records | 158,536 | 79,289 | 79,289 | 158,536 |
| `.state_final.bin` sha256 | `7bd38ff095ad91a0…` | `33e522c7fcb9fcb9…` | `0a6a1feb0e60eb3f…` | `ecab9b9f953b9fcf…` |

**Seed-INDEPENDENT — the same bytes on all four:**

| file | bytes | sha256 |
|---|---|---|
| `.e4.seqdata.bin` | 563,712 | `4a7784f2f2c47e07…` |
| `.state.bin` (the initial region image) | 162,529,280 | `3a716409081f0c54…` |
| `.emb.bin` | 2,034,237,440 | `1742f211016525e7…` |
| the 249 weight images | 4,091,805,696 (**S**, `du --apparent-size -cb` over `tb/scripts/w9/model_9b_s1_w*.bin` on snoke; the emission logs print the COUNT and the content digest, not the bytes) | content sha `dd85640709b86ec5…` |
| the 24 `_cv<L>.bin` conv images | 131,072 each | `1e1f9ca7aff092c3…` (`_cv0`) … |

**The rows that are the same on all four seeds are the strongest statement
this step makes.** The weight-side artifacts do not depend on the prompt, so
those bytes are the agreement of **eight independent GPTQ passes**, not four
pairs. The prompt-dependent artifacts — the `.txt`, the `.seq`, the FINAL
state image — differ exactly where they should.

**Against Task 11 (T, `evidence/qwen9b/g4/G4A_REPLAY.md` §3.3):** the s1 stream was 158,483
records with a **2,136,576 B** const blob; it is now 158,536 records with a
**563,712 B** blob. The blob shrank by 1,572,864 B because `CONVW` is retired
(spec §5.5) and the conv taps arrive by `SLD` instead of being staged through
the const blob.

### 2.3 The manifests' state sha, checked against the file's bytes

**M**, the last check in each emission log:

```
  state.bin      162529280 B  manifest 3a716409081f0c54  file 3a716409081f0c54  MATCH
  state plan     dn=15032385536 kv=15057551360 cv=15191769088 end=15194914816
  conv images    24
```

`MATCH` on all four. This is S3 fix round 2's rule — the manifest's
`state.sha256` is a digest of `.state.bin`'s BYTES, so the host's
`verify_state_image` can check what it is about to upload — and the dispatch
note requires it on every new model manifest. The region sits at
`0x3_8000_0000`, the LAST channel's `STATE_MIN_BASE`, 155 MiB long, with 24
conv images beside it.

### 2.4 The structural probe

**A PROBE, NOT A GATE**, and it is here because it changed what this task
risked. **M**, `evidence/qwen9b/s4/000_emit_probe_rtn.log`, snoke, tree
`2c881f4`, **1 h 08 min**, `rc: 2`.

S3 re-emitted only the one- and two-layer SMOKE artifacts. Whether the v2.1
schedule survives the MODEL geometry — 32 layers, 8 attention layers, the
`slot_plan` across all of them — was unanswered, and the four real emissions
would not have answered it for 2 h 30 min each, because GPTQ runs before the
emit loop is reached. So the same make target was run once more with
`W9_GPTQ=` empty: the quantizer becomes uncalibrated RTN and the answer
arrives in 46 minutes.

It emitted `SEQ: 158537 records (2536592 B) + 563712 B const blob …
[profile=epsnorm loop_steps=3]`, 249 images, the state image and 24 conv
images. **The schedule holds at model scale**, and the four real emissions
were left running rather than being stopped on a suspicion.

Its artifacts (`tb/scripts/w9/probe/rtn_s1`) are NOT usable and nothing
downstream reads them: a different quantizer gives different weights, and the
probe's own trajectory differs from the checkpoint's from **step 1** —
its argmax sequence is `[2614, 3177, 279, 11, 11751, 11]`
(`evidence/qwen9b/s4/000_emit_probe_rtn.log:25-30`) against the GPTQ
artifact's `[2614, 314, 279, 369, 11751, 13]`, so the first difference is
3177 against 314 at step 1; **step 3 is the first difference in a GENERATE
step** (argmax 11 where the artifact gives 369), which is the one that
changes the trajectory rather than only the argmax. Either way it is the
confirmation that `W9_GPTQ=` took effect.

---

## 3. Step 1b — the SEQ gates

**M**, `evidence/qwen9b/s4/02{1,2,3,4}_seqgate_model_s{1,2,3,4}.log`, snoke,
tree `b4c944a`, four in parallel, **17 min**, `rc: 0` each, last line
`G4A_SEQGATE: ALL PASS (1 artifact(s))` and `SEQ GATE: PASS` inside.

| artifact | records | checkpoints | scratch | banked | **state** | tokens |
|---|---|---|---|---|---|---|
| `model_9b_s1` | 158,536 | **2358/2358** ALL BIT-EXACT | 4096 of 65536, 0 outside → CLEAN | BIT-EXACT | **BIT-EXACT, 112 blocks** | `[2614, 314, 279, 369, 11751, 13]` |
| `model_9b_s2` | 79,289 | **2358/2358** | 4095, 0 outside → CLEAN | BIT-EXACT | **BIT-EXACT, 112** | `[279, 264, 854, 11, 303, 264]` |
| `model_9b_s3` | 79,289 | **2358/2358** | 4096, 0 outside → CLEAN | BIT-EXACT | **BIT-EXACT, 112** | `[313, 430, 2510, 198, 1445, 27180]` |
| `model_9b_s4` | 158,536 | **2358/2358** | 4095, 0 outside → CLEAN | BIT-EXACT | **BIT-EXACT, 112** | `[11, 0, 271, 803, 369, 498]` |

**2,358 checkpoints is Task 11's count exactly** (T, `evidence/qwen9b/g4/G4A_REPLAY.md` §4.1a) —
the checkpoint count follows the six forward steps, not the schedule, so a
stream that moved the state to DDR still samples the same live state at the
same places. All four token sequences are Task 11's.

**The `STATE` line is what S3 added and what this gate needs**:
`ref/seq_model.StateRegion` is a SECOND, independent implementation of the
B15.1 layouts, and `.txt` vs `.seq` vs the emitter's `StateImage` agree over
all 112 stored blocks. **112 is the PER-TOKEN store count**, not a
whole-run one: `evidence/qwen9b/s3/S3_CHAIN.md:201` decomposes the schedule's
224 transfers/token as DN 24 + 24, conv 24 + 24, KV 64 + 64 — so 112 loads
and 112 stores each token. Three independent instruments land on it: this
gate's `112 block(s) stored`, the chip replay's `smem 112` (§4.2), and the
census's 672 SST over six steps (§5.3.2). `loop 3 steps (looped) STRUCTURALLY SAFE` on s1/s4
and 5 on s2/s3, as at v2.0.

---

## 4. Step 2 — the chip replay, four seeds, TOKEN-IDENTICAL

### 4.1 The comparison itself, and its RED

`--tokens-ref <doc.md>` reads the token record **out of the committed
document** rather than from a number retyped into a script: every line that
names the artifact in backticks and carries a bracketed list of decimals is
a record, they are normalised, and the set of distinct answers must be
exactly one. In `evidence/qwen9b/g4/G4A_REPLAY.md` that is §4.1a's SEQ-gate table and §5.3.4's
chip table, **which agree — and the fact that they must agree is the point.**

The read is strict in both directions, because the two silent failures of a
checker like this are worse than a wrong answer:

* a stem with **no** record FAILS (`TOKENS NO RECORD`) — silence must never
  look like agreement;
* a stem the document records **twice, differently**, FAILS
  (`TOKENS RECORD IS AMBIGUOUS`) — the arbiter cannot be a document that
  contradicts itself.

**The comparison has been fired all four ways, on REAL simulations, before
it was trusted with the model streams.** **M**,
`evidence/qwen9b/s4/010_tokens_ref_red.log`, snoke, tree `7609072` (clean),
**12 min 29 s**, `rc: 0`, last line
**`TOKENS_REF_RED: PASS`**. Four runs of `tok9b_s1` through the UNMODIFIED
`evidence/qwen9b/g4/run_g4a_replay.sh`, four reference documents:

| arm | document | verdict | rc |
|---|---|---|---|
| **GREEN** | the real `evidence/qwen9b/g4/G4A_REPLAY.md` | `TOKENS IDENTICAL TO G4A`, `[2380,6362]` | 0 |
| RED 1 | a fabricated record with different tokens | `TOKENS DIFFER FROM G4A — step 0: measured 2380, record 2381` | 1 |
| RED 2 | a fabricated document with NO record for the stem | `TOKENS NO RECORD` | 1 |
| RED 3 | a fabricated document with TWO different records | `TOKENS RECORD IS AMBIGUOUS` | 1 |

The three fabricated documents were written to a temp directory, printed
into the log so a reader can see exactly what was fed, and deleted on exit:
a fabricated token record must never survive beside the evidence.

**The GREEN is also the first evidence on the bar itself.** `tok9b_s1` is a
9B token-loop artifact, re-emitted at v2.1 by S3 and replayed here against
S2's DDR-state RTL, and it decodes `[2380, 6362]` — the sequence Task 11
recorded on the OLD design (`evidence/qwen9b/g4/G4A_REPLAY.md` §4.1). The model streams are the
arbiter; this said the bar was reachable before three hours of emission were
spent on it.

### 4.2 The replay

**M**, `evidence/qwen9b/s4/031_full_model_4seeds.log`, snoke, tree
`0fe1407`, ONE binary (`built 2026-09-05T03:38:14`), four processes launched
together, `rc: 0`, last lines
**`--- TOKENS IDENTICAL TO G4A on 4 of 4 seed(s)`** and
**`G4A_REPLAY model_9b_s: ALL PASS`**.

| seed | wall | cycles | tokens measured | Task 11's record | verdict |
|---|---|---|---|---|---|
| `model_9b_s1` | 9,211 s = 2 h 33 min | **196,706,821** | `[2614, 314, 279, 369, 11751, 13]` | the same | **IDENTICAL** |
| `model_9b_s2` | 9,227 s = 2 h 34 min | 196,707,670 | `[279, 264, 854, 11, 303, 264]` | the same | **IDENTICAL** |
| `model_9b_s3` | 9,386 s = 2 h 36 min | 196,707,670 | `[313, 430, 2510, 198, 1445, 27180]` | the same | **IDENTICAL** |
| `model_9b_s4` | 9,627 s = 2 h 40 min | 196,706,833 | `[11, 0, 271, 803, 369, 498]` | the same | **IDENTICAL** |
| **all four, in parallel** | **9,627 s = 2 h 40 min 27 s** | | | | |

**Twenty-four tokens, four prompts, six forward steps through 32 real layers
whose DeltaNet, KV and conv state now lives in DDR and is moved by 224
SLD/SST per token — and not one token moved.** Task 11's own numbers
(T, `evidence/qwen9b/g4/G4A_REPLAY.md` §5.3.4) are the right-hand column, and the comparison is
made by the script against the document, not by a reader.

Every seed's `LAUNCH 0 PASS` line carries **`tokens 6, tcnt 8, scratch 36864,
smem 112`** — the 112 state blocks the golden holds, compared beat for beat
— and the run summary carries `decerr 0 non-OK 0` and `weight beats
383606784 total across 4 chan (miss 0)` on every seed. **The two
prompt-dependent counters split by prompt LENGTH**, and the seed logs say so:
s1 and s4 (158,536-record streams) carry `ddr beats 448410 (miss 0)` and
`fetch-empty stall cycles 48`; s2 and s3 (79,289 records) carry
`ddr beats 448413 (miss 0)` and `fetch-empty stall cycles 84`
(`evidence/qwen9b/s4/seedlogs_model_9b_s/model_9b_s2.log:22-23` and its s3
sibling).

**AND IT IS FASTER — M/D.**

| | Task 11 (URAM/BRAM state) | S4 (DDR state) | Δ |
|---|---|---|---|
| s1 cycles | 200,098,192 | **196,706,821** | **−3,391,371 (−1.70 %)** |
| per token | 33,349,699 | 32,784,470 | −565,228 = **−2.261 ms** @250 MHz |
| ms/token, whole model | 133.399 | **131.138** | −2.261 |
| `ddr beats` | 544,805 | 448,410 | −96,395 |

The state spill does not cost end-to-end time on this stream — it **pays**.
§5.3 accounts for where: the `dn_step` instantiation went back to
(RLAT 2, P2_WAIT 0) when the 24-bank URAM array retired, and the preamble's
768 `DNZ` + 120 `CONVW` are gone.

**One number the two testbenches share and neither derives from the other**:
`tb_seq_chip` reports `state: 2676800 read beats, 2659968 write beats, 0
unmapped`, and the census's own window reports `ddr beats r=2676800
w=2659968 miss=0`. Different TB, different memory model instance, same
transfers.

### 4.3 Memory

**M**, `evidence/qwen9b/s4/032_memwatch_4seeds.log`, sampling every 60 s
beside the rung:

```
--- free -g at the start:  total 247  used 127  available 120
G4A_MEMWATCH: peak 4 process(es), total RSS 0.242 GiB,
              largest single 0.060 GiB, 158 sample(s)
--- free -g at the end:    total 247  used  52  available 195
```

Against Task 11's `0.169 GiB total, 0.042 GiB largest`
(T, `evidence/qwen9b/g4/G4A_REPLAY.md` §5.3.4): **the writable state window costs
≈ 0.07 GiB across four full-model replays** — a difference of two
three-significant-figure totals (0.242 − 0.169), so the third digit of a
"73 MiB" is not supported and is not claimed. `tb/seq_mem_file.sv` streams the 3.9 GiB of weight
images and the 1.9 GiB embedding table through `$fseek`/`$fread` and holds
only the WRITTEN state beats in its RAM overlay, so the constraint on this
rung is still wall clock and disk, not RAM. `used 127` at the start is
the four emissions still running beside it (§7); they had finished by the
end, which is where the other 75 GiB went.

---

## 5. Step 3 — the layer-term census, on two lanes

### 5.1 What S4 changed in the instrument

Task 12's `tb_layer_census` could not elaborate against S2's layer at all,
let alone measure it, and the repairs are the measurement's substance rather
than plumbing:

| what | why |
|---|---|
| the `DN_PIPE` override dropped from the instantiation; `dut.DN_RLAT` / `dut.DN_P2WAIT` dropped from the report | S2 RETIRED all three (`rtl/layer_chan.sv:377`). The report now names the literals `dn_step` is instantiated with (`rtl/layer_chan.sv:627`, RLAT 2 / P2_WAIT 0) and says in as many words that `-GP_DN_PIPE` is **accepted and IGNORED**, so a stale knob cannot look live |
| the layer's `m_axis` master wired to `tb/seq_mem_file.sv`'s writable window, loaded from `<prefix>.state.bin` via `+state=` | the state the layer used to hold in URAM is in DDR; without the image the CONV taps `seed_conv` wrote are not there |
| the script's `S` record programs `SB_DN`/`SB_KV`/`SB_CV` **and** the model's window | the script and the model cannot name different addresses |
| `SLD` (13) and `SST` (14) in the per-opcode table | the two commands this amendment adds |
| **every command censused on BOTH lanes** — `LCYC` (0x34, `busy_cmp`, spec A1.4) and `SDMA_CYC` (0x74, `busy_dma`) | an SLD/SST's LCYC cost is its DISPATCH; the transfer is on the other lane, and reporting only LCYC would price the spill at zero |
| an `excess` column, total − count × min | where an F1/F2 stall would appear — see §5.3 for why this instrument cannot produce one |

`rtl/state_dma.sv` (S2) and `tb/seq_mem_file.sv` (S3) are reached by
`` `include ``, and `evidence/qwen9b/s4/run_s4_census.sh` replaces Task 12's
runner: both are worked around rather than edited because both are outside
S4's commit block, and §7 declares it (item 2's reason is corrected there).

**Fix round 1 adds three more**, and §5.5 is what they are for: a
`+nodrain=1` dispatch mode, per-cycle F1/F2 hold counters read as the
dispatcher's own arm conditions, and `LAT` as a build parameter (`-GP_LAT`,
default 8) so the same census can be run at `tb/tb_seq_chip.sv`'s `WLAT = 40`.
The DRAINING mode's per-opcode and per-step TABLES are unchanged, row for row;
what the draining report gains is a `dispatch=` line and **four** appended
totals (`TOTAL_BUSY_ANY_CYCLES`, `TOTAL_F1_HOLD_CYCLES`,
`TOTAL_F2_HOLD_CYCLES`, `TOTAL_F2_FENCE_CYCLES`), so
`evidence/qwen9b/s4/census_s4shipped.txt` differs from what a re-run would
print by those **five** lines and by nothing else. (The TB's own report
comment says "four" where it means five; it is left alone because the fix
round 2 arm needed no change to `evidence/qwen9b/g4/tb_layer_census.sv` and
the round would not touch a measured instrument for a comment — the next
round that opens that file should fix the sentence.)

### 5.2 The control

**M**, `evidence/qwen9b/s4/041_census_state_red.log`, snoke, tree `0fe1407`,
`rc: 0`, last line **`CENSUS_STATE_RED: PASS`** — on the SAME binary the
census run built and, **on the 1-layer 9B smoke `scripts/w9/lay9b_s1`
(978 commands, 174,238 checks) rather than the model stream**, the same
script across all three arms. Using the cheap vehicle is deliberate: the arm
that matters is a WRONG state image, and that arm fails at the first CONV
whatever the stream's length.

| arm | `+state=` | rc | what happened |
|---|---|---|---|
| **GREEN** | the script's own image | 0 | `TB_LAYER_CENSUS PASS: 978 cmds, 174238 checks bit-exact` |
| RED 1 | **another seed's** image | 134 | `FAIL R[5420+0] after cmd 18: got 0010 want fff1` |
| RED 2 | none at all | 134 | `state window: no +state= — the window stays closed`, then `got 0000 want fff1` |

**RED 1 is the arm that matters.** It is what distinguishes *"the census
reads the state region"* from *"the census reads something and the numbers
happen to agree"*: a different seed's conv taps are the same SIZE and in the
same place, and the replay refuses them at the first CONV. RED 2 shows what
the failure would have looked like without a control — zeros, silently, from
a window nobody loaded.

### 5.3 The census

**M**, `evidence/qwen9b/s4/040_census_shipped6.log`, snoke, tree `0fe1407`,
**4,399 s = 1 h 13 min**, `rc: 0`, verdict line
**`TB_LAYER_CENSUS PASS: 56576 cmds, 8600034 checks bit-exact`** — the whole
six-step stream, every R / E / A record compared, `errors=0`. The table is
committed at `evidence/qwen9b/s4/census_s4shipped.txt`.

**8,600,034 is EXACTLY Task 12's check count** (T, `evidence/qwen9b/g4/G4B_STRUCT.md` §5.4a) on
a stream whose command count moved — the checks follow the arithmetic, and
the arithmetic did not move.

#### 5.3.1 THE LAYER TERM

| | cycles/token | ms @ 250 MHz |
|---|---|---|
| Task 12, shipped, step 1 (**T**) | 11,506,810 | 46.027 |
| **S4, step 1 (M)** | **11,405,434** | **45.622** |
| Task 12, shipped, mean over 6 steps | **11,519,849** (**T**, `evidence/qwen9b/g4/G4B_STRUCT.md` §5.4a) | 46.079 (**T**) |
| **S4, mean over 6 steps (M/D)** | **11,418,473** | **45.674** |

**The layer term went DOWN by 101,376 cycles/token, and that number is not
approximate: 768 DNST/token × 132 cycles = 101,376 exactly.** It is exact
BOTH ways: step 1 to step 1 is 11,506,810 − 11,405,434 = 101,376, and
mean to mean is 11,519,849 − 11,418,473 = 101,376. 132 is the
`(RLAT 6, P2WAIT 1) → (RLAT 2, P2WAIT 0)` delta Task 10 measured in
isolation and Task 12 measured on the stream. Nothing else in the compute
lane moved.

**And the arithmetic is confirmed from a second direction.** Task 12's
`pipe0` control — the unpipelined configuration, which also runs `dn_step` at
RLAT 2 / P2WAIT 0 — measured **11,405,434 busy cycles/token**
(T, `evidence/qwen9b/g4/G4B_STRUCT.md` §5.4). S4's step 1 is **11,405,434**. Two gates, two
elaborations, one number; and S4 reaches it with 224 MORE commands per token
than Task 12's 9,205, because the 224 SLD/SST cost the compute lane nothing.

#### 5.3.2 Where the layer term goes, per token

> **CAVEAT ADDED 2026-09-15 (BN1), and nothing else in this section is
> changed: the table below is the `.txt` HOST-DRIVEN schedule's per-opcode
> split, not the shipped `.e4` sequencer path's.** The two halves of the
> dual-driven equivalence issue different command lists — 9,429 layer
> commands per token here against 8,821 on the `.e4` stream, `ALU` 6,219
> against 4,843 and `VN` 1,761 against 2,529 — so `ALU`'s **49.58 %** share
> below is **41.2 %** (17.150 ms of a 41.610 ms lane) on the path the board
> runs. See `evidence/qwen9b/bn/BN_CENSUS.md` §10.2 and §13, measured in
> `evidence/qwen9b/bn/015_fix2_lane_vs_window.log`.

**M** for the cycles (the census's own totals over six steps), **D** for the
per-token and share columns:

| opcode | commands/token | cycles/token | ms | share |
|---|---|---|---|---|
| `ALU` (11) | 6,219 | 5,661,439 | 22.646 | 49.58 % |
| **`DNST` (8)** | **768** | **2,271,744** | **9.087** | **19.90 %** |
| `VN` (1) | 1,761 | 1,092,819 | 4.371 | 9.57 % |
| `CONV` (6) | 24 | 983,328 | 3.933 | 8.61 % |
| `VNW` (2) | 81 | 811,089 | 3.244 | 7.10 % |
| `ATTN` (10) | 128 | 251,200 | 1.005 | 2.20 % |
| `ROPE` (4) | 160 | 164,320 | 0.657 | 1.44 % |
| `KVAP` (9) | 32 | 147,895 | 0.592 | 1.30 % |
| `GATE` (7) | 24 | 31,560 | 0.126 | 0.28 % |
| `ROPET` (3) | 8 | 3,080 | 0.012 | 0.03 % |
| **`SLD` (13)** | **112** | **0** | **0** | **0 %** |
| **`SST` (14)** | **112** | **0** | **0** | **0 %** |
| **total** | **9,429** | **11,418,473** | **45.674** | 100 % |

The ten compute rows sum to the layer term to within the two rounded rows —
11,418,474 against 11,418,473, because ALU (…438.5) and KVAP (…894.83) each
round up — which is the census's own consistency check, and **the two new
rows are zero**: an
SLD/SST is enqueued and the accept gate reopens: `busy_cmp` never rises, so
`LCYC` never counts it (spec A1.4, `rtl/layer_chan.sv:1055`).

**The preamble went from 888 commands to 2.** Task 12's stream spent 888
commands before the first token (768 `DNZ` + 120 `CONVW`); S4's spends two
`SLD`. The DN region is a host memset now and the conv taps arrive by
transfer (spec §5.5, §6.4).

#### 5.3.3 The DMA lane — `SDMA_CYC`

**M**, the census's second table and its per-step column:

| | value |
|---|---|
| `SLD` | 674 commands, 4,026,251 cycles, **5,973 mean** |
| `SST` | 672 commands, 3,701,456 cycles, **5,508 mean** |
| total | **7,727,707 cycles** |
| **per token (steps 1-6)** | 1,280,480 … 1,285,280, **mean 1,283,339** |
| **per token, ms @ 250 MHz** | **5.133** |
| **as a share of the layer term** | **11.24 %** |
| the preamble's 2 SLD | 27,675 cycles |

**Label and caveat, both load-bearing.** These are cycles the DMA lane was
busy *in this testbench's memory model*, `tb/seq_mem_file.sv` at **`LAT = 8`**
— eight cycles of read latency, a modelled number and not the board's. The
COUNT of transfers (224/token, 1,346 total) and the beats (2,676,800 read,
2,659,968 write) are properties of the schedule and are not modelled; the
CYCLES are. A board number needs the board.

**AND THE TWO TESTBENCHES DO NOT MODEL THE SAME WINDOW.** The census
instantiates `seq_mem_file` at `LAT = 8`; `tb/tb_seq_chip.sv:436` gives the
SAME window `LAT(WLAT)` and **`WLAT = 40`** (`tb/tb_seq_chip.sv:69`, and the
seed logs' launch line prints `WLAT=40`). So §4.2's whole-model figure was
measured at the SLOWER memory model, which strengthens it: the 1.7 % speedup
is what a 40-cycle window produced. It also means **5.133 ms/token must NOT
be added to §4.2's 131.138 ms/token** — the chip number already contains a
40-cycle window's transfers. §5.5 measures the non-draining census at LAT 40
as well, which is the like-for-like companion of the chip replay.

**What it means for the design, stated no more strongly than measured**: the
transfers occupy their own lane for 5.1 ms while the compute lane is busy for
45.7 ms, so there is 8.9× more compute time than transfer time to hide them
in — and the chip replay (§4.2), where the two lanes actually overlap, came
out 1.7 % FASTER than the old design rather than slower. That is the
strongest available statement that the spill is hidden on this stream.

#### 5.3.4 DNST at `RLAT = 2`

**M**: **2,958 cycles/command, min == max over 4,608 commands** — exactly
data-independent across all 24 DN layers, all 32 heads and all six steps.

| | cycles/DNST | source |
|---|---|---|
| Task 12, shipped, `RLAT = 6` | 3,090 | T, `evidence/qwen9b/g4/G4B_STRUCT.md` §5.3 |
| Task 12, `pipe0` control, `RLAT = 2` | 2,958 | T, same |
| S2, `tb_dn_step` in isolation, `RLAT = 2` | 1,798 /head | T, `evidence/qwen9b/s2/S2_RTL.md` §4.2 |
| **S4, on the real stream, `RLAT = 2`** | **2,958** | **M** |

1,798 + Task 12's measured 1,160-cycle `layer_chan` wrapper = 2,958. The
prediction the dispatch note made — *"expected ≈ 1,798 + the command
overhead"* — is met to the cycle.

### 5.4 F1 and F2 — what this instrument can and cannot say

**No F1 or F2 stall was observed, and the honest reason is that this
testbench cannot produce one.**

The census attributes cycles to commands by draining the engine between
them: it dispatches a command, polls `STATUS` until the command counter has
advanced AND `busy_any` (= `busy_cmp | busy_dma`) is low, and only then reads
`LCYC`. That drain is what makes each difference *that command's* cost. It
also means a transfer is always complete before the next command is
dispatched — and F1 is precisely *"a compute command whose slot has an SLD
queued or in flight — or ANY transfer in flight — stalls at dispatch"*
(`rtl/layer_chan.sv:111-113`). The elided clause is load-bearing and, quoted
whole, it makes the argument stronger: the drain guarantees that no transfer
is in flight AT ALL, so neither half of the condition can be true.

The census reports the place a stall WOULD appear anyway — the `excess`
column, total − count × min:

| opcode | excess (6 steps) | what it is |
|---|---|---|
| `SLD`, `SST` | **0** | nothing above a zero floor |
| `DNST`, `CONV`, `ROPE`, `GATE`, `ROPET` | **0** | exactly data-independent: min == max |
| `KVAP` | 521 | `T` growth over six steps (max 4,626, min 4,619) |
| `ATTN` | 78,720 | `T` growth (max 2,065, min 1,860) |
| `VN`, `VNW`, `ALU` | 3.3 M / 4.5 M / 32.4 M | length-dependent commands; the floor is the shortest one |

So `excess = 0` on the two new opcodes and on every fixed-cost opcode is a
real statement — those commands took exactly their known cost, every time —
and the large numbers are vector length, not stalls. **A non-zero excess is a
candidate, never a stall count**, and this gate does not present one.

**What IS measured about the stalls' total cost is in §4.2**: the chip replay
streams records back to back through `seq_unit`, so F1 and F2 are live there,
and the whole model came out **3,391,371 cycles FASTER** than Task 11's. Any
stall the design takes is inside that number and is more than paid for.

**Turning that bound into an attribution needs a census that does NOT drain.
Fix round 1 built one — §5.5.**

---

### 5.5 THE FENCE HOLDS, MEASURED — a second census that does NOT drain

§5.4 says this census cannot observe an F1 or F2 stall, and says why. The
brief's *Produces for S5/Task 14* asks for **"the count of F1/F2 stalls
actually taken"**. Fix round 1 built the instrument that can produce one,
rather than leaving the item as a reported impossibility (§7 item 7).

#### 5.5.1 What `+nodrain=1` changes — one condition, and it is the sequencer's

The draining census polls `STATUS` until the command counter has advanced
**and** `busy_any` is low. `+nodrain=1` drops the second half, and it drops
it because that is what the hardware sequencer does:
`rtl/seq_unit.sv:1187-1205` (`I_CMDPOLLW`) compares `rrsp_data[31:16]` with
`cmd_cnt_exp` and **never reads STATUS bit 0**. Since `cmd_cnt` advances for
an SLD/SST at **ENQUEUE** (`rtl/layer_chan.sv:1459-1464`), the next record is
dispatched while the transfer is still moving — which is exactly the
condition F1 and F2 exist for.

**The queue cannot be overrun by this**, and that is a property of the RTL
rather than of the testbench: a fifth SLD/SST against the four-deep queue is
HELD at dispatch and does **not** advance `cmd_cnt`
(`rtl/layer_chan.sv:1448-1457`), so polling `cmd_cnt` *is* the queue's
back-pressure. The poll's backoff moves with the mode — 20 negedges when
draining (the shipped census's number, unchanged), 2 under `+nodrain`, which
puts the poll period at about the AXI-Lite round trip `I_CMDPOLL` /
`I_CMDPOLLW` takes. **The poll's HANG GUARD moves with the mode too**, from
200,000 iterations to 4,000,000 (`evidence/qwen9b/g4/tb_layer_census.sv:658`),
and the reason is on the record: building §5.5.3's RED at `LAT = 4000`
surfaced one `CONV` that waited past 200,000 polls (~1.4 M cycles) on a
LEGITIMATE F1 hold, so the guard was raised WITH the mode rather than the
mode being tuned to fit the guard. `+watchdog_ms` is still the outer limit.

**One cosmetic quirk of the draining report, for the record.** Its
`dispatch=` line reads `dispatch=         DRAINING (poll cmd_cnt AND busy_any
low)`: SystemVerilog pads the shorter arm of the `?:` that builds the string
to the length of the longer one, so the draining label carries nine leading
spaces. It is harmless — the control's `awk` keys on `$2` — and it is in the
committed tables, so it is named here rather than silently repaired.

**Everything the census checks is unchanged.** Every `R` / `E` / `A` record is
still compared bit-exactly, so a `TB_LAYER_CENSUS PASS` in this mode is also
**the first model-scale test of the two fences under back-to-back dispatch** —
the fences are what make a bit-exact answer possible when a compute command
and a transfer contend for a slot, and until now nothing had put them under
that pressure on the whole model.

#### 5.5.2 What it counts, and which lane each one lands on

Counted per cycle, by hierarchical reference to the dispatcher's own arm
conditions, so the instrument cannot disagree with the RTL:

| counter | the RTL arm | lane | inside `LCYC`? |
|---|---|---|---|
| **F1 HOLD** | `rtl/layer_chan.sv:1486-1491` — a compute command held at dispatch because its slot has an SLD queued or in flight | compute | **YES** — the arm raises `busy_cmp` |
| **F2 HOLD** | `rtl/layer_chan.sv:1448-1457` — an SLD/SST held at dispatch because the DMA queue is full | compute | **YES** — same |
| **F2 FENCE** — *the spec's F2 proper* (`rtl/layer_chan.sv:114-115`) | `rtl/layer_chan.sv:2086-2095`, gating the start arm at `rtl/layer_chan.sv:2151` — the transfer at the HEAD of the queue waiting because a compute command holds its slot | DMA | no |

**The first two are NOT the spec's F2**, and the RTL says so itself: the
queue-full branch's own comment reads "`cmd_pend` keeps `cmp_holds` low, **so
F2 still lets the queue drain**" (`rtl/layer_chan.sv:1454-1455`). F2 proper is
the third row, and it is the one §5.5.6 makes fire.

Because the first two are inside `LCYC`, the report prints them **beside** it
and never instead of it: the reader subtracts. `BUSY_ANY` (STATUS bit 0) is
reported too, so the `wall` column can be read — `wall − busy_any` is the time
the engine was idle inside a step, which under `+nodrain` is almost entirely
the census's OWN scratch traffic (every `R` record is an AXI-Lite read and the
sequencer performs none of them). **`wall` is therefore not a per-token wall
time and is not offered as one**; it is comparable between two runs of the
same script, and that is all it is used for here.

#### 5.5.3 The control — and it is stronger than a RED

**M**, `evidence/qwen9b/s4/073_census_nodrain_red.log`, snoke, tree
`8f89870`, `rc: 0`, verdict line **`CENSUS_NODRAIN_RED: PASS — the
fence-hold counters fire under`** — **the first of a five-line verdict**, the
rest of which reads `back-to-back dispatch at a latency the schedule cannot
hide, read` / `zero when the drain makes a hold impossible, account to the
CYCLE` / `for the whole difference between the two dispatch modes, and every`
/ `arm stayed bit-exact`.

Four arms, all on the 1-layer 9B smoke `scripts/w9/lay9b_s1` (978 commands,
174,238 checks — the same cheap vehicle §5.2's control uses, and for the same
reason), all four **`TB_LAYER_CENSUS PASS: 978 cmds, 174238 checks
bit-exact`**:

| arm | dispatch | `LAT` | `LCYC` | F1 hold | F2 hold | F2 fence | `SDMA_CYC` |
|---|---|---|---|---|---|---|---|
| `nd8` | **nodrain** | 8 | 1,309,741 | **0** | **17,275** | 0 | 134,963 |
| `dr8` | draining | 8 | 1,292,466 | 0 | 0 | 0 | 134,963 |
| `nd4000` | **nodrain** | 4000 | 4,159,750 | **2,041,718** | **825,566** | 0 | 3,604,419 |
| `dr4000` | draining | 4000 | 1,292,466 | 0 | 0 | 0 | 3,604,419 |

and three verdicts, of which the third is the one that makes the instrument
believable:

* **THE RED — the counter FIRES.** At `LAT = 4000` the modelled window is slow
  enough that a transfer cannot be hidden behind the compute that follows it,
  and **F1 holds for 2,041,718 cycles** across 2 `CONV` (1,912,313) and 4
  `KVAP` (129,405) commands, with 825,566 more of queue-full hold on 2 `SLD`.
  A counter that had never been non-zero would not be a measurement.
* **THE NEGATIVE ARM — it reads zero when a hold is impossible.** The DRAINING
  mode on the SAME script at BOTH latencies reports `0 / 0`. The drain makes
  the F1 condition unreachable by construction (§5.4), so anything else there
  would have meant the counter was counting something else.
* **THE IDENTITY — the two counters account for the WHOLE difference, to the
  cycle.** The compute lane's real work does not depend on the memory model,
  so every extra `LCYC` cycle that back-to-back dispatch costs must be a fence
  hold. It is: `1,309,741 − 0 − 17,275 = 1,292,466` and
  `4,159,750 − 2,041,718 − 825,566 = 1,292,466`, and **1,292,466 is exactly
  what the draining mode measures at either latency.** Two dispatch modes, two
  memory models 500× apart, one compute-lane number.

#### 5.5.4 The measurement — the whole model, at `LAT = 8` and at the chip's `WLAT = 40`

**M**, two runs, launched together on snoke and each its own build and its
own `obj_dir` (the latency is a `-G` parameter, so two latencies are two
binaries and the runner puts `LAT` in the directory name):

| | log | tree | wall | verdict |
|---|---|---|---|---|
| `LAT = 8` (the census's own) | `evidence/qwen9b/s4/074_census_nodrain_lat8.log` | `8f89870` | **3,590 s = 59 min 50 s** | **`TB_LAYER_CENSUS PASS: 56576 cmds, 8600034 checks bit-exact`**, `rc: 0` |
| **`LAT = 40`** (`tb/tb_seq_chip.sv`'s `WLAT`) | `evidence/qwen9b/s4/075_census_nodrain_lat40.log` | `8f89870` | **3,565 s = 59 min 25 s** | **the same line**, `rc: 0` |

**56,576 commands and 8,600,034 checks — the DRAINING census's counts
exactly** (§5.3), now with the two commands overlapping the DMA. That PASS is
the first model-scale test of the fences under back-to-back dispatch, and it
is a result before any cycle is counted.

**Per token — the mean over the six forward steps, i.e. each census table's
six-step column divided by six — and the two latencies agree to the CYCLE on
every fence column.** The whole-run totals the tables print are
`TOTAL_BUSY_CYCLES 69236558` and `TOTAL_F2_HOLD_CYCLES 725718` on BOTH runs,
and `TOTAL_SDMA_CYCLES` 7,727,707 / 7,757,467; the per-token rows below are
those figures over the six forward steps — 69,236,558 / 6 = 11,539,426.33 and
725,718 / 6 = 120,953 — with the preamble (step 0: 2 commands, 0 compute
cycles, 27,675 / 27,739 DMA cycles) excluded from the `SDMA_CYC` row, which
is why 7,727,707 − 27,675 = 7,700,032 gives 1,283,339.

| | `LAT = 8` | `LAT = 40` |
|---|---|---|
| `LCYC` (compute lane, holds INCLUDED) | **11,539,426** = 46.158 ms | **11,539,426** = 46.158 ms |
| **F1 hold** (load-before-use) | **0** | **0** |
| **F2 hold** (queue full — `rtl/layer_chan.sv:1448-1457`, **not** the spec's F2) | **120,953** = 0.484 ms | **120,953** = 0.484 ms |
| **F2 fence** (the spec's F2: DMA head held by a compute command that owns its slot) | **0** — see §5.5.6 | **0** — see §5.5.6 |
| `LCYC` − F1 − F2 | **11,418,473** = 45.674 ms | **11,418,473** = 45.674 ms |
| `SDMA_CYC` | 1,283,339 | 1,288,288 |
| `BUSY_ANY` | 12,084,293 | 12,085,317 |
| `wall` | 30,628,743 | 30,628,743 |

**AND THE SUBTRACTION LANDS ON THE COMMITTED MEASUREMENT, STEP BY STEP.**
`LCYC − F1 − F2` is not merely *close* to §5.3.1's draining number; it is that
number, per forward step, to the cycle, against
`evidence/qwen9b/s4/census_s4shipped.txt`:

| step | `LCYC` (nodrain) | − F2 hold | the DRAINING census |
|---|---|---|---|
| 1 | 11,526,387 | 11,405,434 | **11,405,434** |
| 2 | 11,531,527 | 11,410,574 | **11,410,574** |
| 3 | 11,536,800 | 11,415,847 | **11,415,847** |
| 4 | 11,542,031 | 11,421,078 | **11,421,078** |
| 5 | 11,547,274 | 11,426,321 | **11,426,321** |
| 6 | 11,552,539 | 11,431,586 | **11,431,586** |

Two dispatch disciplines, two builds, two runs, and the compute work is the
same six numbers. **Everything back-to-back dispatch costs this layer is the
fence, and the counter has all of it.**

**Where the hold is, and why the latency does not move it.** All of it is on
`SLD`: **725,718 hold cycles over 42 commands** in the six steps — **7 per
token**, a mean of exactly **17,279 cycles** each — and no other opcode holds
at all
(`f1_cmds` and `f2_cmds` are 0 on every row but `SLD`). The 1-layer smoke's
single hold was 17,275 cycles (§5.5.3), which is the same event at the same
place in the schedule. The **explanation**, offered as an explanation and not
as a measurement: a queue-full hold waits for the transfer that is ALREADY IN
FLIGHT to finish, and that transfer's AR latency was paid before the hold
began — so the hold costs BEATS, which do not change with `LAT`, rather than
latency. What does move with `LAT` is `SDMA_CYC`, by 4,949 cycles/token
(0.39 %), and `BUSY_ANY`, by 1,024.

**The layer term with the fences charged.** §5.3.1's **45.674 ms/token** is
the compute WORK and is the like-for-like comparison against Task 12's
**46.079** (Task 12 drained too, and had no DMA lane at all to fence
against). Charge the worst-case fence cost on top and the compute lane reads
**46.158 ms/token** — **0.079 ms, 0.17 %, ABOVE Task 12's 46.079**. Both
statements are true and neither is the end-to-end one: §4.2's whole-model
replay, where `seq_unit` dispatches and the two lanes really overlap, came out
**1.70 % faster**. §5.5.5 says why the census's figure is the pessimistic end
of that range.

#### 5.5.5 How to read it: an UPPER bound, and what it sits beside

**It is an UPPER bound on the fences' cost on this stream, not a count of
what the chip takes**, and the reason is arithmetic rather than rhetorical.

A fence hold happens when a compute command arrives before the transfer its
slot needs has finished. Anything that puts TIME between two layer commands
gives the transfer more room and can only REDUCE the hold. So the question is
which dispatcher leaves less room: this census, or `seq_unit`.

* **This census** leaves, per token, `wall − busy_any` = **18,544,450**
  cycles at `LAT = 8` and 18,543,426 at `LAT = 40` — almost all of it
  the golden's own `R`-record scratch reads, which the sequencer does not
  perform.
* **`seq_unit` on the same stream** leaves far more. §4.2's whole model is
  **32,784,470 cycles/token** end to end while this layer's compute lane is
  busy for **11,418,473** of them (§5.3.1) — about **21.4 M cycles/token** in
  which this layer is not computing at all: the record fetch, the CSRWR
  stream, and above all `MOVX`/`MOVY`/`MVGO` moving 383,606,784 weight beats
  through the four `matvec_chan` engines.

**The two bullets do not measure the same thing, so here is the like-for-like
pair.** `wall − busy_any` subtracts BOTH lanes' busy time; the 21.4 M
subtracts only the COMPUTE lane's, so it still counts the chip's DMA-only
cycles as "room". Taken the same way — subtracting only the compute lane —
the census leaves `wall − LCYC` = 30,628,743 − 11,539,426 = **19,089,317
cycles/token, 19.1 M**, against `seq_unit`'s 32,784,470 − 11,418,473 =
**21,365,997, 21.4 M**. **The two `LCYC`s in that pair are not the same
quantity**, and here is which is which: the census's 11,539,426 is
`LCYC` WITH its two dispatch holds still in it (§5.5.4), while the chip's
11,418,473 is the compute work with the holds REMOVED (§5.3.1, and §5.5.3's
identity). Symmetrising either way leaves the conclusion where it is — holds
removed from both, 30,628,743 − 11,418,473 = 19,210,270 against 21,365,997;
the same hold-inclusive figure charged to both, 19,089,317 against
32,784,470 − 11,539,426 = 21,245,044 — and the pairing above is the
CONSERVATIVE one for this section's own claim, because it charges the census
its holds and the chip none. (The other like-for-like pair points the same
way and is even tighter: subtracting both lanes, 18.5 M here against 21.4 M minus
whatever the chip's own DMA lane occupies.)

**19.1 M is smaller than 21.4 M, so this census dispatches TIGHTER than
`seq_unit` does on the same stream, and 120,953 cycles/token is an UPPER
BOUND on what the fences cost the chip at this memory model.** That is the
whole argument, and it is arithmetic rather than assertion. The one thing it
assumes is stated so a reader can attack it: that the sequencer's 21.4 M
cycles of other work are not concentrated AWAY from the seven `SLD` records
that hold. Proving that needs a sequencer-level probe, which is §8's
not-established item and not this gate's.

Two more things the figure is NOT:

* **not a board number.** `LAT = 40` is `tb/tb_seq_chip.sv`'s model, not a
  DDR4 controller under four `matvec_chan` engines (§8).
* **not a per-token wall time.** `wall` includes the census's own CSR
  traffic; the compute lane's occupancy is `LCYC`, and `LCYC` minus the two
  hold columns is the work (§5.5.3's identity).

**And the PASS itself is a result.** Every arm of §5.5.3 and both measurements
here replayed **bit-exactly** with the two commands overlapping the DMA — the
condition the fences exist for and the one the draining census could never
create. Before fix round 1 the fences had been exercised at model scale only
inside `tb_seq_chip`, where a failure would have shown up as a wrong token
rather than as a named record; here the first divergent scratch word names
itself.

#### 5.5.6 The spec's F2, made to fire (fix round 2)

Everything above measures the two DISPATCH holds. **The spec's F2 is a
different thing** — "a transfer at the head of the DMA queue waits while a
compute command holds its slot" (`rtl/layer_chan.sv:114-115`) — the census
counts it separately as `F2 FENCE`, and up to fix round 2 that counter had
read **0 everywhere and had never been seen to fire**. A 0 from a counter no
arm exercises is *not observed*, not *measured zero*, so fix round 2 built the
arm.

**Why the shipped schedule never arms it: THREE legs — the emitter, the
four-deep transfer queue, and F1 — and all three are needed.**

1. **The emitter double-buffers.** `ref/gen_model_script.py` targets every
   group of state transfers at ONE cache slot and runs the compute that
   IMMEDIATELY follows on the OTHER —
   `C e 800 / C e 801 / C d 804 / C d 805` all name KV slot 0, then
   `L 00000008` puts the KVAP/ATTN block that follows on KV slot 1 — and
   `hd_f2` needs the HEAD transfer's slot to be the slot the RUNNING compute
   command owns (`rtl/layer_chan.sv:2086-2095`).
2. **The LAYER DOES come back to a group's slot later — and by then the
   four-deep in-order queue has necessarily popped that group's stores.**
   Leg 1 alone would be too strong a claim, and the shipped stream contains
   240 literal counterexamples to it: an `SST` to KV slot *s* followed 18-20
   records later by a `KVAP`/`ATTN` on that same *s*, out of 960 store /
   compute coincidences in all. What keeps the fence unarmed across every one
   of those 960 is the QUEUE: the MINIMUM number of transfers enqueued
   between the `SST` and the compute command is exactly **4**, `dq` is FOUR
   deep and in order, and a fifth record is HELD at dispatch rather than
   dropped (`rtl/layer_chan.sv:1448-1457`) — so such a store has always been
   popped before that command dispatches and cannot be at the head.
3. **What CAN still be at the head is that group's LOADS to the slot, and
   those raise F1 first.** An F1-stalled command sits in `IDLE` with
   `cmd_pend` set, so `cmp_holds = busy_cmp && !cmd_pend` (`rtl/layer_chan.sv:2067`)
   is LOW and there is nothing for F2 to hold against — which is exactly the
   no-deadlock argument at `rtl/layer_chan.sv:2060-2065`. **F1 shadows F2 by
   construction on this stream.**

**Where the 240 and the 4 come from — and where they do NOT.** Both are the
round-3 REVIEW's derivation, by a scan of the emitted model stream
(`model_9b_s1` under `scripts/w9/` relative to `tb/`; the artifact is
regenerable and `.gitignore`d, so it is named as prose and not as a citation)
with the LAYER decode at `rtl/layer_chan.sv:1107-1110` and the `SLD`/`SST`
argument fields at `docs/SEQ_ISA.md:1264-1270`. They are a property of the
SCHEDULE, read off the stream — not a measurement, and **no committed log in
this directory carries them**; fix round 3 re-derived them read-only, on
darthplagueis, and got the same 960 / 240 / minimum 4 — §7 item 8 says what
it ran. Nothing else in this document depends on them.

`F2 FENCE = 0` on the model runs is therefore a statement about the schedule
and its transfer queue, not about the fence.

**One place still carries the shorter reason, and it is a log.** The control's
own PASS line — quoted VERBATIM in §6 row 18 and printed by
`evidence/qwen9b/s4/census_nodrain_red.sh` — says the fence is one "which the
shipped schedule's double-buffering never arms". Editing that line would
change the control's OUTPUT, and this round re-ran nothing, so the line is
left exactly as `076_census_nodrain_red2.log` recorded it; the script's
COMMENT block carries all three legs, and the discrepancy is named here
rather than papered over.

**The perturbation — two records of the KV group at lines 435,903-435,906 of
the smoke script** (`scripts/w9/lay9b_s1`'s `.txt`, relative to `tb/`; the
artifact is regenerable and `.gitignore` keeps it out of the tree, so it is
named as prose and not as a citation), in the shape of S2's case 6
(`tb/tb_layer_sdma.sv:765-801`), which the S2 report describes as *an SST
queued behind a long SLD, with a CONV holding the SST's slot*. The copy is
generated at run time from the committed script and deleted on exit — the
committed script is never edited:

```
C e 800 0 0   ->   C d 1400 0 0     the LONG transfer that goes AHEAD
C e 801 0 0   ->   C e c01 0 0      the STORE the compute must fence
```

1. the KV store of head 0 becomes an **`SLD` of a conv block into CV slot 1**
   — 8192 rows = **2,048 beats**, which is the arm's own `ddr beats r=57344`
   against `f2half`'s `r=55296`, a delta of exactly 2,048 — on a kind and a
   slot **nothing else in this script touches**, so it can neither stall nor
   corrupt a compute command; it exists only to occupy the DMA lane;
2. the KV store of head 1 is retargeted from slot 0 to **KV slot 1**, the slot
   the KVAP/ATTN block after `L 00000008` owns. Being a STORE it does not
   raise `sld_pend`, so the block is **not** held by F1
   (`rtl/layer_chan.sv:1356-1364`); being BEHIND the long load it is still
   QUEUED when the block claims the slot, and it reaches the head of the queue
   while a `KVAP`/`ATTN` owns KV slot 1. That is F2.

**Why two records and not one — and the arm that shows it.** A KV transfer in
this 1-layer smoke moves at most ONE row, and the arm's own DDR counters say
so: `f2half`'s `r=55296` is exactly the three DN loads (3 × 16,384) plus the
three CV loads (3 × 2,048), so its **six KV loads read 0 beats**, and its
`w=36874` is the two DN plus two CV stores (36,864) plus **5** — four row
beats and one exponent beat — for each of its two KV stores. Tens of cycles
either way, SHORTER than the census's own dispatch path of five AXI-Lite ops.
Retargeting the store ALONE lets it reach the head while
the engine is between commands: it starts, completes, and COOLS its slot
(`rtl/layer_chan.sv:2173`), so the `KVAP` that follows is refused
instead of fencing it. The `f2half` arm IS that one-record
perturbation, and it is in the log for exactly this reason.

**M**, `evidence/qwen9b/s4/076_census_nodrain_red2.log`, snoke, tree
`c530350` (the commit that added the arm), `rc: 0`, 570 s for six arms — it is
the control of §5.5.3 with the two arms added, so its first four arms re-run,
and they **reproduce §5.5.3's table to the cycle**. The four census tables
those arms rewrite came out **byte-identical to the committed ones** (`git`
reports no modification), three hours and one control-script edit later:

| arm | script | `LCYC` | F1 hold | F2 hold | **F2 FENCE** | errors |
|---|---|---|---|---|---|---|
| `f2half` | ONE record retargeted | 853,496 | 0 | 17,275 | **0** | 5 |
| `f2fence` | **both records** | 863,692 | 0 | 17,275 | **1,847** | 1 |

**The counter fires: 1,847 cycles with the DMA queue's head held by a compute
command that owned its slot.** The only difference between the two arms is the
one record that puts a long transfer in front, and the counter moves 0 →
1,847; the shipped schedule and the four arms of §5.5.3 read 0 on the same
counter. Both arms run at the **shipping `LAT = 8`** — the perturbation makes
its own long transfer, so no latency knob is involved.

**Neither arm is a correctness run and neither pretends to be.** The
perturbation drops one KV STORE (`C e 800 0 0` is an `SST`, not a load —
`docs/SEQ_ISA.md:1264-1270`), stores the wrong slot's rows over head 1's DDR
address, and cools KV slot 1 when that store finally completes, so a command
behind it is refused — one command in the `f2fence` arm
(`FAIL cmd 761: err_op`) and five in `f2half`, where the store completes
before the block even starts. **What the census reads is `err_op` and nothing
finer**: the TB tests STATUS bit 1 and never the error code, so *which*
refusal it is comes from the RTL rather than from the instrument — a compute
command on a slot with no completed load since its last `SST` is refused
`E_DMA_COLD` (`cmd_cold`, `rtl/layer_chan.sv:1365-1368`), and that is the only
cause the perturbation creates. It is offered as an explanation and labelled
as one. Both scripts are TRUNCATED with a `Q` fifteen
commands past the perturbation, **before any `R`/`E`/`A` record can read
anything the perturbation touched**: every error in both arms is an `err_op`
refusal, no `FAIL R[…]` / `FAIL E` / `FAIL A` line appears in either, and the
**103,827 checks each arm does run are all bit-exact**. **The middle negative
— no `FAIL R` / `FAIL E` / `FAIL A` line — is DERIVED, not displayed**, and
the derivation is this: the control greps
each perturbed arm's stdout for the census lines and for `FAIL cmd` and for
nothing else, and the stdout itself is deleted by the script's `trap`, so what
the committed log carries is the census's own `errors` total beside the
`FAIL cmd` lines it printed — 5 and 5 on `f2half`, 1 and 1 on `f2fence`.
`errors` is the TB's SINGLE failure counter — the `err_op` refusal
(`evidence/qwen9b/g4/tb_layer_census.sv:752`) and every `R` / `E` / `A`
comparison raise the same variable — so `errors` equal to the number of
`FAIL cmd` lines IS the statement that no other check failed. Adding
`FAIL [REA]` to that grep would SHOW it instead of deriving it; the change is
deliberately NOT made here, because this round re-ran nothing and an
unexercised edit to a control script is worth less than a derivation the
committed log supports. The arm's PASS criterion is `F2 FENCE > 0` and nothing
else; a non-zero rc is expected and the control says so in its own output. The
census table is written before the TB's `$fatal` (the report is emitted at the
end of the replay and the TB's hard stop is 20 errors), so the counter is read
from the table either way.

**What this does and does not change.** It changes nothing in §5.5.4's
measurement: `F2 FENCE` is still **0** on the shipped model stream at both
latencies. What it changes is what that 0 MEANS — it is now a counter that has
been seen to fire, reading zero on a schedule whose double-buffering, four-deep
in-order transfer queue and F1 shadow keep the fence unarmed, rather than a
counter nobody had ever made move.

---

## 6. Gates

Every row is a committed log under `evidence/qwen9b/s4/`, and the verdict
column quotes that log's own verdict line VERBATIM. Where a log's verdict is
not its last line, the row says which line it is.

| # | gate | log | verdict line | rc |
|---|---|---|---|---|
| 1 | the schedule emits at model scale (probe) | `000_emit_probe_rtn.log` | `SEQ: 158537 records …[elided]… loop_steps=3` — **line 92 of 96, not the last line**; the full line is `SEQ: 158537 records (2536592 B) + 563712 B const blob -> …/probe/rtn_s1.e4.seq  [profile=epsnorm loop_steps=3]` | 2 (the audit, by design) |
| 2 | the four streams, emitted twice | `001…004_emit_9b_s*.log` | `EMIT_GATED s<n>: PASS — two independent emissions, byte-identical` | 0 |
| 3 | the token compare's GREEN and three REDs | `010_tokens_ref_red.log` | `TOKENS_REF_RED: PASS` | 0 |
| 4 | the SEQ gate ×4 | `021…024_seqgate_model_s*.log` | `G4A_SEQGATE: ALL PASS (1 artifact(s))` | 0 |
| 5 | the four chip goldens | `030_chip_vectors_9b.log` | `SEED 1 rc=0 wall=988s` and its three siblings (973 / 980 / 986 s) — **the four `SEED` lines are this log's verdict, not its last line**; the per-seed detail block after them is EMPTY because the pattern that was supposed to lift the generator's `.chip:` summary out of each capture file did not match it (the line is indented). The summaries are in the captures the log names, and §4.2's `smem 112` is the same fact checked by the RTL | 0 |
| 6 | **the chip replay, 4 seeds, token-identical** | `031_full_model_4seeds.log` | **`--- TOKENS IDENTICAL TO G4A on 4 of 4 seed(s)`**, `G4A_REPLAY model_9b_s: ALL PASS` | 0 |
| 7 | memory | `032_memwatch_4seeds.log` | `G4A_MEMWATCH: peak 4 process(es), total RSS 0.242 GiB, largest single 0.060 GiB, 158 sample(s)` | 0 |
| 8 | **the layer-term census** | `040_census_shipped6.log` | **`TB_LAYER_CENSUS PASS: 56576 cmds, 8600034 checks bit-exact …[elided]…`** — **line 76 of 80, not the last line**; the full line ends `(scripts/w9/model_9b_s1.txt)`, and the Verilator `$finish` line and the runner's `=== census …` footer follow it | 0 |
| 9 | the census's state-region control | `041_census_state_red.log` | `CENSUS_STATE_RED: PASS` | 0 |
| 10 | citation drift | `050_cite_drift_plan.log`, `051_cite_drift_verify.log` | `O3_FIX_PLAN: SAFE …[elided]…` — the full line is `O3_FIX_PLAN: SAFE — every rewrite repairs a citation --verify reports stale`; and `O3_CITE_DRIFT VERIFY PASS (0 problem(s))` | 0 |
| 11 | **the emit-twice gate FIRES on the model target** (fix round 1, I1) | `070_emit2_gate_red.log` | **`EMIT2_GATE_RED: PASS — the model target's emit-twice block is REACHED`** — **the first of a four-line verdict**; the rest reads `on the by-design audit rc and PASSES; it REFUSES a perturbed second` / `emission; and it is NOT reached when the emitter fails for any other` / `reason (no audit line, or a traceback)` | 0 |
| 12 | the SMOKE path still passes through the repaired gate | `071_smoke_regate.log` | **`SMOKE_REGATE: PASS — the smoke target's emit-twice gate still passes`** — **the first of a three-line verdict**; the rest reads `through the repaired emit_repeat.sh, and every byte of lay9b_s1 is` / `where it was` | 0 |
| 13 | **the replay's tracked-LOGDIR refusal** (fix round 1, I2) | `072_logdir_guard_red.log` | **`LOGDIR_GUARD_RED: PASS — the default LOGDIR for model_9b_s is REFUSED`** — **the first of a two-line verdict**; the rest reads `(rc 4, no simulation) and an untracked LOGDIR still replays clean` | 0 |
| 14 | **the non-draining census's control** (fix round 1, I4) | `073_census_nodrain_red.log` | **`CENSUS_NODRAIN_RED: PASS — the fence-hold counters fire under`** — **the first of a five-line verdict**; the rest reads `back-to-back dispatch at a latency the schedule cannot hide, read` / `zero when the drain makes a hold impossible, account to the CYCLE` / `for the whole difference between the two dispatch modes, and every` / `arm stayed bit-exact` | 0 |
| 15 | **the fence holds, whole model, `LAT = 8`** | `074_census_nodrain_lat8.log` | **`TB_LAYER_CENSUS PASS: 56576 cmds, 8600034 checks bit-exact …[elided]…`** — **line 79 of 83, not the last line**; the full line ends `(scripts/w9/model_9b_s1.txt)`, and the Verilator `$finish` line and the runner's `=== census …` footer follow it | 0 |
| 16 | **the fence holds, whole model, `WLAT = 40`** | `075_census_nodrain_lat40.log` | **the same line, elided the same way** — **line 79 of 83, not the last line** | 0 |
| 17 | citation drift, fix round 1 | `080_cite_drift_plan.log`, `081_cite_drift_verify.log` | `O3_FIX_PLAN: SAFE …[elided]…` (the full line is `O3_FIX_PLAN: SAFE — every rewrite repairs a citation --verify reports stale`); and `O3_CITE_DRIFT VERIFY PASS (0 problem(s))` | 0 |
| 18 | **the SPEC's F2 fence FIRES** (fix round 2, I-2) | `076_census_nodrain_red2.log` | **`CENSUS_NODRAIN_RED: PASS — the fence-hold counters fire under`** — **line 132 of 140, the first of a seven-line verdict**; the rest reads `back-to-back dispatch at a latency the schedule cannot hide, read` / `zero when the drain makes a hold impossible, account to the CYCLE` / `for the whole difference between the two dispatch modes, every` / `measuring arm stayed bit-exact, and the SPEC'S F2 fence — which the` / `shipped schedule's double-buffering never arms — HOLDS a transfer` / `when two records of that schedule are perturbed into case 6's shape` | 0 |
| 19 | the exclusion §10.1 needed, shown | `082_cite_drift_plan_noexclude.log` | `O3_FIX_PLAN: UNSAFE …[elided]…` — the full line is `O3_FIX_PLAN: UNSAFE — 2 of 2 rewrites would move a citation that is already correct; repair the 0 stale one(s) BY HAND or --exclude the document` | 1 |

**Three `spec_cites` logs in this document's directory are superseded and are
kept.** `092_spec_cites.log` and `093_spec_cites.log` were each committed
alone as fix round 1's final log; each was then overtaken because the gate doc
gained a correction after it, and `094_spec_cites.log` is round 1's real last
one. **Fix round 2 did the same thing once more**: `095_spec_cites.log` was
committed alone as that round's final log and was then overtaken by
`096_spec_cites.log` when the doc gained one further correction after it. The
round's last commit message says so; this note is where the DOCUMENT says it.
All three remain true records of the trees they name and are not deleted; the
rule *"the final commit is the `spec_cites` log alone"* was reached on the
third attempt in round 1 and on the second in round 2.

### 6.1 Every green half has a red one

| the check | its RED | fired |
|---|---|---|
| the token compare agrees | a record with different tokens | **`TOKENS DIFFER FROM G4A — step 0: measured 2380, record 2381`** |
| the token compare found a record | a document with none | **`TOKENS NO RECORD`** |
| the record is unambiguous | a document contradicting itself | **`TOKENS RECORD IS AMBIGUOUS`** |
| the census reads the state region | another seed's state image | **`FAIL R[5420+0] after cmd 18: got 0010 want fff1`**, rc 134 |
| the census needs an image at all | no `+state=` | **`got 0000 want fff1`**, rc 134 |
| the emit-twice comparison can refuse | S3's committed RED, `evidence/qwen9b/s3/060_emit2_red.log` | `EMIT2_RED: CAUGHT` (T) |
| the emit-twice block is REACHED on the audit rc | a second emission at a perturbed seed | **four `DIFFERS` lines and `EMIT_REPEAT: FAIL`** (`070`) |
| …and is NOT reached on any other failure | rc 1 with no audit line | **`W9_EMIT2 GATE: ABORT -- rc 1 is NOT the known range-audit failure; the emit-twice block is SKIPPED`**, no `EMIT_REPEAT:` line at all (`070`) |
| …nor when the emitter left a traceback | a `Traceback` and then the audit line | the same marker, and again no `EMIT_REPEAT:` line (`070`) |
| the smoke path still passes, and its bytes did not move | the five `lay9b_s1` digests, before against after | **five × `UNMOVED`** (`071`) |
| the replay refuses a `LOGDIR` that holds evidence | the DEFAULT `LOGDIR` for `model_9b_s` | **`REFUSING: … holds TRACKED evidence; pass LOGDIR= explicitly`**, rc 4, and no `=== binary` / `LAUNCH` / `TB_SEQ_CHIP` in the output (`072`) |
| …and does NOT refuse a fresh one | an untracked `LOGDIR` | `G4A_REPLAY tok9b_s: ALL PASS`, rc 0 (`072`) |
| the fence-hold counter can fire | `+nodrain=1` at `LAT = 4000` | **`TOTAL_F1_HOLD_CYCLES 2041718`** (`073`) |
| …and reads zero when a hold is impossible | the DRAINING mode at `LAT = 8` and at `LAT = 4000` | **`0 / 0` on both** (`073`) |
| …and accounts for the whole difference | `LCYC(nodrain) − F1 − F2` against `LCYC(draining)` | **`1,292,466` at both latencies, to the cycle** (`073`) |
| **the SPEC's F2 fence counter can fire** | two records of the smoke perturbed into S2 case 6's shape — a store on the slot the `KVAP`/`ATTN` block owns, queued behind a conv-block load | **`TOTAL_F2_FENCE_CYCLES 1847`** (`076`, arm `f2fence`) |
| …and one record is not enough to arm it | the retarget alone, no long transfer ahead | **`TOTAL_F2_FENCE_CYCLES 0`** and five `err_op` refusals (`076`, arm `f2half`) |
| the §10.1 exclusion was the tool's own demand | the same plan run WITHOUT `--exclude evidence/qwen9b/s4/emit_model_gated.sh` | **`O3_FIX_PLAN: UNSAFE`**, 2 of 2 rewrites collateral, rc 1 (`082`) |

---

## 7. Deviations declared

1. **The census does not run through Task 12's `evidence/qwen9b/g4/run_g4b_census.sh`.** That
   runner never passes `+state=` (the state region did not exist when it was
   written), and its `p2wait 0` arm seds a localparam S2 retired. It is
   outside S4's commit block, so `evidence/qwen9b/s4/run_s4_census.sh` is
   Task 12's runner with those two changes and nothing else — same verilator
   flags, same `rtl/`-clean guard, same one-obj_dir-per-cfg rule. **The
   controller may prefer to fix the runner instead**; this gate's numbers do
   not depend on which.
2. **`evidence/qwen9b/g4/tb_layer_census.sv` reaches `rtl/state_dma.sv` and `tb/seq_mem_file.sv`
   by `` `include ``**, with the two width-warning classes suppressed over
   the include only — the same two `tb/Makefile:226` already suppresses for
   the same file via `$(XLIB)`. **The reason first given here was stale and
   is corrected:** it said the file list lives in a runner outside the commit
   block, which was true only until S4 wrote
   `evidence/qwen9b/s4/run_s4_census.sh`, whose own `LAYER_RTL` could carry
   both paths. The include is KEPT on the reason that actually holds — it
   keeps the TB elaborable under Task 12's `evidence/qwen9b/g4/run_g4b_census.sh`
   as well as
   under S4's runner, so one file does not fork into two, and the cwd
   dependency it costs is documented at the `u_smem` instance and fails
   loudly (Verilator names the missing include) rather than quietly.
3. **The emit-twice gate was S4's own script, not the Makefile's** (§2.1).
   **Fix round 1 repaired the Makefile's** (§2.1a); the four emissions
   themselves were not re-run, because S4's own script already proved those
   artifacts over a strictly larger file set.
4. **`LOGDIR` was overridden for the replay, and the script now REFUSES the
   unsafe default.** `evidence/qwen9b/g4/run_g4a_replay.sh`'s default is
   `evidence/qwen9b/g4/seedlogs_<stem>`, which for `model_9b_s` is where
   **Task 11's committed per-seed logs live**; the rung would have
   overwritten the evidence it compares itself against. S4 passed
   `LOGDIR=evidence/qwen9b/s4/seedlogs_model_9b_s`. **Fix round 1 replaced
   that discipline with a guard**: after `mkdir -p "$LOGDIR"` the script asks
   `git ls-files --error-unmatch` whether the directory holds TRACKED files
   and, if it does, prints `REFUSING: … holds TRACKED evidence; pass LOGDIR=
   explicitly` and exits 4 **before the binary check and before any
   simulation**. Proved both ways in `evidence/qwen9b/s4/072_logdir_guard_red.log`
   (§6 row 13). One consequence is declared: `evidence/qwen9b/s4/tokens_ref_red.sh`
   wrote four `seedlogs_tokref_*` directories that are committed now, so the
   guard would refuse a re-run of it in place; it takes a `TOKREF_LOGROOT=`
   override for that, and its default — the one `010_tokens_ref_red.log` ran
   with — is unchanged.
5. **The SEQ gates, the chip replay and the census were run BEFORE the
   emit-twice comparison finished** — they started at 06:58, 07:36 and
   07:38; the four `EMIT_GATED … PASS` verdicts landed at 10:25. This was
   deliberate and it is a scheduling choice, not an evidence one: emission A
   writes the kept artifact and emission B writes to a different prefix, so
   the bytes the gates read were final and immutable from **06:56** — s3's
   emission A ended at 06:56:10 (`evidence/qwen9b/s4/003_emit_9b_s3.log:104`),
   the latest of the four, and the first downstream run started 06:58:30. Had any
   comparison failed, every downstream result would have been void and this
   document would say BLOCKED. It saved ~3 h of wall clock and risked only
   machine time.
6. **The census measures one seed** (`model_9b_s1`), as Task 12 did and as
   the brief specifies. The 4-seed rule binds the TB runs (SEQ gate ×4, chip
   replay ×4), which it did.
7. **The brief's Interfaces line asks for "the count of F1/F2 stalls actually
   taken", and the DRAINING census cannot produce one — so fix round 1 built
   a second instrument rather than leaving the item unanswered.** The
   structural reason is §5.4's: the census attributes cycles to commands by
   polling `STATUS` until the command counter has advanced **and** `busy_any`
   is low, so a transfer is always complete before the next dispatch and
   neither half of F1's condition can ever be true. The two options were to
   accept the chip replay's aggregate (§4.2's 3,391,371-cycle speedup) as the
   only bound before Task 14, or to build a NON-DRAINING census. **Fix round 1
   built it** (§5.5): `+nodrain=1` replays the same stream with the
   sequencer's own back-pressure rule and counts the F1 and F2 holds per
   cycle, and it is measured at the census's `LAT = 8` and at the chip
   replay's `WLAT = 40`. **What S5/Task 14 should assume** is §5.5's LAT-40
   figure, read as an UPPER bound: back-to-back dispatch gives the DMA less
   cover than the real sequencer, whose weight streaming sits between layer
   commands. The exact per-token stall count on the shipping schedule is
   still not established (§8); a bound is.

8. **§5.5.6's 240 and 4 are a SCAN of the emitted stream, and no log in this
   directory carries them.** They are the round-3 REVIEW's derivation, and
   fix round 3 — a documentation-only round that re-ran no simulation and
   changed no number — re-derived them read-only rather than take them on
   trust. What it ran: a Python pass over the emitted stream (`model_9b_s1`
   under `scripts/w9/` relative to `tb/`, named as prose because the artifact
   is `.gitignore`d) on darthplagueis, decoding every `C` record with the
   `SLD`/`SST` argument fields of `docs/SEQ_ISA.md:1264-1270` and tracking
   the live KV slot from every `L` record with the LAYER decode at
   `rtl/layer_chan.sv:1107-1110`. What ONE such scan produces, each figure
   labelled with what it counts: over the stream's **56,576** `C` records
   there are **384** KV `SST` and **960** KV consumers (`KVAP` + `ATTN`); of
   the same-slot `SST` → consumer pairs, **240** are 18-20 records apart; and
   the MINIMUM number of transfer records enqueued between any such pair is
   **4** — the leg §5.5.6 actually leans on. The 960 counts COMMANDS, not
   pairs; an earlier form of this sentence read it as a pair count. TWO
   independent read-only scans produce these figures — the round-4 review's
   and fix round 3's — and NO log in this directory carries them. The scanned
   artifact is not committed but it IS regenerable: emission A of
   `evidence/qwen9b/s4/emit_model_gated.sh` runs
   `make -C tb w9_9b_model_script W9_SEED=1 W9_BASE=scripts/w9/model_9b_s1`
   and that command stands recorded at
   `evidence/qwen9b/s4/001_emit_9b_s1.log:19`, with the `.txt` size and
   sha256 of the artifact it wrote at
   `evidence/qwen9b/s4/001_emit_9b_s1.log:202` — so a later reader can
   confirm they scanned the same bytes before trusting the figures above. It
   is a text scan of that regenerable artifact and it proves a property of the
   SCHEDULE rather than of the RTL, so it is NOT committed as a gate and
   §5.5.6 labels its two numbers as the review's derivation, not as a
   measurement.

---

## 8. NOT ESTABLISHED by this gate

* **Nothing is placed, routed or on the board.** No synthesis ran in this
  task; no bitstream exists for the DDR-state design; the board was not
  touched. The timing and area consequences of S2's RTL are S5's.
* **`SDMA_CYC` is not a board number.** §5.3.3: the transfer COUNT and the
  BEAT counts are the schedule's; the CYCLES are `tb/seq_mem_file.sv` at
  `LAT = 8` — and `tb/tb_seq_chip.sv:436` models the SAME window at
  `WLAT = 40`, so the two testbenches' DMA figures are not on one memory
  model and must never be added to each other (§5.3.3, §5.5). A real DDR4
  controller under four `matvec_chan` engines will not be 8 cycles or 40,
  and this gate does not claim it will.
* **The fence holds are BOUNDED, not counted, on the shipping schedule.**
  The draining census cannot produce one at all (§5.4). The non-draining
  census (§5.5) measures them under BACK-TO-BACK dispatch, which gives the
  DMA less cover than the real sequencer does — the sequencer streams weight
  records between layer commands — so its figures are an UPPER bound on what
  the fences cost in the chip, not the count the chip takes. The exact count
  on the shipping schedule needs a sequencer-level probe and is not this
  gate's. The spec's F2 fence in particular reads **0** on this schedule for
  a STRUCTURAL reason and not for want of a counter — the emitter's
  double-buffering, the four-deep in-order transfer queue that has popped a
  group's stores before the LAYER comes back to their slot, and F1's shadow
  over the loads that remain; §5.5.6 gives all three legs and the 240 cases
  in the shipped stream that make the queue leg NECESSARY, and it makes the
  counter fire on a perturbed schedule to establish that.
* **The layer term is one prompt's.** 45.674 ms is the mean over the six
  forward steps of `model_9b_s1`; the T-dependence across those steps is
  26,152 cycles (0.23 %), as at Task 12.
* **Fidelity is unchanged and unmeasured here.** This gate proves the new
  design computes what the old one did, bit for bit; it says nothing new
  about how close either is to bf16. That is Task 5's 98/108, quoted in
  `evidence/qwen9b/g4/G4A_REPLAY.md` §6 and not re-derived.
* **The host path is not exercised.** `sw/seq_run.upload_state` and the
  residency witnesses are S3's code; no host uploaded a state image in this
  task.

---

## 9. Handoffs

**For S5 (placement and timing) and Task 14 (the schedule):**

| what | value | label |
|---|---|---|
| the four stream shas | §2.2 | M |
| the token-identity verdict | **4 of 4 seeds IDENTICAL to Task 11** | M |
| the layer term | **45.674 ms/token** (46.079 before) — *COMPUTE lane, LCYC = `busy_cmp`, spec A1.4; the DMA lane's 5.133 ms/token is a separate lane and is NOT included, see §5.3.3* | M |
| the whole model, end to end | **196,706,821 cycles = 786.83 ms for 6 tokens = 131.14 ms/token** | M |
| DNST | **2,958 cycles/command** at RLAT 2 | M |
| the SLD/SST dispatch cost | **0 compute cycles** | M |
| the DMA lane | **1,283,339 cycles/token = 5.133 ms at LAT 8** — and **do not add it to the row above or to the whole-model row**: `tb/tb_seq_chip.sv:436` models the same window at **`WLAT = 40`** (`tb/tb_seq_chip.sv:69`), so the chip figure already contains a 40-cycle window's transfers | M |
| the transfers | **224/token**, 2,676,800 read + 2,659,968 write beats over 6 tokens | M |
| the 4-seed chip replay's budget | **2 h 40 min** for four in parallel, **0.242 GiB** | M |
| one 9B emission, under the emit-twice gate | **~7 h** (two passes), four seeds concurrently for the same 7 h | M |
| **the fences' cost, bounded above** | **F1 = 0 and F2 = 120,953 cycles/token = 0.484 ms, 1.05 % of the compute lane** *(queue-full dispatch hold, `rtl/layer_chan.sv:1448-1457`; the spec's F2 fence, counted separately as `F2 FENCE`, is 0 on the shipped schedule — its double-buffering, four-deep in-order transfer queue and F1 shadow never arm it, §5.5.6 — and the counter FIRES, 1,847 cycles, on the perturbed arm of `evidence/qwen9b/s4/076_census_nodrain_red2.log`, §5.5.6)* — measured under back-to-back dispatch at `LAT = 8` **and** at the chip TB's `WLAT = 40`, which agree to the cycle. Read it as an UPPER bound (§5.5.5); the count the shipping schedule actually takes is not established | M |
| the layer term with the fences charged | **46.158 ms/token** (`LCYC` including the holds) against the 45.674 of compute work — so the compute lane is 0.17 % ABOVE Task 12's 46.079 at the pessimistic end and 0.88 % below it at the optimistic end; §4.2's whole-model **1.70 % faster** is the only end-to-end number | M/D |

**The two instrument repairs S4 asked the controller to route are DONE, in
fix round 1, each with its own RED**: the emit-twice gate now fires on
`w9_9b_model_script` (§2.1a, `evidence/qwen9b/s4/070_emit2_gate_red.log`) and
`evidence/qwen9b/g4/run_g4a_replay.sh` REFUSES a `LOGDIR` that holds tracked
evidence (§7 item 4, `evidence/qwen9b/s4/072_logdir_guard_red.log`). The third
item — Task 12's stale census runner and control (§7 item 1) — is still open
and is still the controller's to route; this gate's numbers do not depend on
it.

---

## 10. Citation drift

**M**, base `c2ce008` — the tree this task started from — over the two files
S4 edited:

| pass | log | last line |
|---|---|---|
| plan | `evidence/qwen9b/s4/050_cite_drift_plan.log` | `O3_FIX_PLAN: SAFE`, `TOTAL REPAIR 0 COLLATERAL 0` |
| verify | `evidence/qwen9b/s4/051_cite_drift_verify.log` | `O3_CITE_DRIFT VERIFY PASS (0 problem(s))` |

**One citation exists into either file** — `evidence/qwen9b/s3/S3_CHAIN.md:722`
names `evidence/qwen9b/g4/tb_layer_census.sv:7` — and it did not move: S4's
edits to that file begin at its line 23. Nothing was rewritten, so no earlier
base's repairs could be discarded by this pass (the S3 round-2 regression's
failure mode).

### 10.1 Fix round 1

**M**, tree `76bffcc`, base `1742ccb` — the tree the fix round started from —
over the five non-`s4/` files it edited: `evidence/qwen9b/g4/run_g4a_replay.sh`,
`evidence/qwen9b/g4/tb_layer_census.sv`, `tb/Makefile`,
`evidence/qwen9b/s3/emit_repeat.sh` and `evidence/qwen9b/s3/S3_CHAIN.md`.

| pass | log | last line |
|---|---|---|
| plan | `evidence/qwen9b/s4/080_cite_drift_plan.log` | `O3_FIX_PLAN: SAFE …[elided]…`, `TOTAL REPAIR 0 COLLATERAL 0` |
| verify | `evidence/qwen9b/s4/081_cite_drift_verify.log` | `O3_CITE_DRIFT VERIFY PASS (0 problem(s))` |

**No `--fix` ran**, because `REPAIR` is 0: every citation into those five
files either did not move or is carried by a document this round rewrote in
the FINAL tree's coordinates.

**Two documents are `--exclude`d, and the tool asked for the first of them —
and fix round 2 committed the run that shows it**
(`evidence/qwen9b/s4/082_cite_drift_plan_noexclude.log`, darthplagueis, rc 1,
last line `O3_FIX_PLAN: UNSAFE — 2 of 2 rewrites would move a citation that is
already correct; repair the 0 stale one(s) BY HAND or --exclude the
document`). Without `--exclude evidence/qwen9b/s4/emit_model_gated.sh` the
plan reports **`O3_FIX_PLAN: UNSAFE`** — 2 of 2 rewrites would move
`tb/Makefile:1409-1439` and `tb/Makefile:1431-1438`, citations that are
ALREADY correct, to 1444-1474 and 1466-1473: the file was rewritten this round against
the finished `tb/Makefile`, which is exactly the double-shift the flag exists
for. `evidence/qwen9b/s4/S4_REPLAY.md` is excluded under the plan's standing
rule (*"`--exclude` your own gate doc"*) and for the same reason: §2.1 and
§2.1a were rewritten this round and name the new coordinates, and the
citations the base document carried — lines 1355-1358 and 1363-1370 of the
BASE tree's `tb/Makefile`, lines 71-75 of the BASE tree's
`evidence/qwen9b/s3/emit_repeat.sh` — point at lines the fix DELETED. They
are written here as prose rather than as citations, deliberately: as
citations they would read as live pointers into files where those line
numbers now mean something else. They are not re-anchored either, because
the code they named is gone; that is the repair, not drift.

**The edits that land after the pass are all in THIS gate doc, which the pass
excludes, and exactly TWO of them add citations into one of the five edited
files — both written in the FINAL tree's coordinates, so neither can be
stale** —
and `080` and `081`'s verdicts stand at the tree they name. Fix round 1 has
four (`7524efa` committed the two logs; `07f7fed`, `b0494c6`,
`b205214` and `4c3a974` followed), fix round 2 adds its own, and the first of
them was this paragraph: `spec_cites` refused the sentence above in its first form, where
the second range was written as a bare backticked continuation. Such a
continuation binds to the nearest file the line names, and it bound to
`evidence/qwen9b/s3/emit_repeat.sh`, whose 128 lines do not reach line 1363.

**The two exceptions to the sentence above, and both land in the same file.**
Commit `3077489` (fix round 2) added the citation
`evidence/qwen9b/g4/tb_layer_census.sv:658` to §5.5.1 — the poll-guard line
the round-2 review asked for — after `080` and `081` had run; commit
`805d098` (fix round 3) added `evidence/qwen9b/g4/tb_layer_census.sv:752` to
§5.5.6, the `err_op` refusal that raises the TB's single `errors` counter.
Those TWO are every citation any post-pass edit has put into one of the five
files. Line 658 of that file is the `guard_max` assignment itself and line
752 is the `err_op` raise, so BOTH are written in the FINAL tree's
coordinates and there is nothing for a drift pass to repair. The rule that
keeps this paragraph true without a hand re-count next round: every post-pass
citation into those five files is written in the final tree's coordinates,
and `spec_cites` re-checks all of them on the committed tree at the end of
every round — `097_spec_cites.log`, tree `805d098`, is the run that covers
these two, at `FAIL 0`.
