# G4a — the 9B SEQ streams, emitted and replayed (spec §7.2, plan Task 11)

**Task 11 of the Qwen3.5-9B migration.  Base tree `1c62570`.  Host and
simulation only — no synthesis, no board.**  Every number below is labelled
**M**(easured), **D**(erived), **T**(ranscribed from another gate),
**E**(stimate) or **S**(tated as an intent), and every numeric step went
through `evidence/qwen9b/run.sh`, which refuses to overwrite a log and
stamps host / date / tree sha + dirty flag / command / interpreter probe /
thread pinning into every one.

**The claim.**  **The whole of Qwen3.5-9B has run.**  The artifact set Task 5
could not emit exists — 249 weight images, a 158,483-record SEQ_ISA v2.0
stream, a 1,940 MiB embedding table — and it replays bit-exactly through
`ref/seq_model.py` and then through the real RTL, producing the bf16
checkpoint's own argmax sequence.

---

## 0. Verdict

**DONE.**  Every product of the gate is measured, and two defects were found
along the way that only a 9B run could find.

| product | state |
|---|---|
| the scratch high-water probe, MEASURED at 9B | **DONE** — `MEASURED PEAK=50208 DERIVED PEAK=50208 SCRATCH=65536 headroom=15328` (§2) |
| the 9B artifact set (249 images + manifest + `.emb.bin` + the stream) | **EMITTED**, 3 h 00 min, and every projected number reproduced exactly (§3.3) |
| `gen_model_script`'s runtime range audit — Task 5's un-measured item | **MEASURED, and it FAILS** — deliberately, without `--allow-clip` (§3.4) |
| `ref/seq_model.py --gate` on the full model | **`SEQ GATE: PASS`**, 2,358/2,358 checkpoints bit-exact (§4.1) — **on all FOUR seeds** since fix round 1 (§4.1a) |
| the same gate on 8 smoke artifacts, 4 seeds each | **`G4A_SEQGATE: ALL PASS (8 artifact(s))`** (§4.1) |
| the chip replay, rung A (1 layer x 4 seeds) | **`ALL PASS`**, 3,782,887 cycles each, 189 s (§5.1) |
| the chip replay, rung B (token loop x 4 seeds) | **`ALL PASS`**, 4,049,140 cycles each, 198 s (§5.2) |
| the chip replay, rung C (**the whole model**) | **`TB_SEQ_CHIP PASS`**, 200,098,192 cycles, 6 tokens, 2 h 42 min (§5.3.2) — and **`ALL PASS` at FOUR SEEDS**, 2 h 47 min for all four in parallel, since fix round 1 (§5.3.4) |
| the S9 envelope checks NOT firing | **PROVEN on all nine 9B streams**, at exactly `ng = MAX_NG = 96`, with the RED control (§5.4) |
| the torch-golden lockstep | **`G4A_TORCH_LOCKSTEP: PASS`** — generator == stream == `layer_fixed` == **bf16**, 6/6 (§7) |
| `shape_isa` in the emitted metadata (Task 10 hand-on) | **DONE**, tag-gated; the declared-gap line moved `0 of 13` -> `9 of 22` (§3.2) |
| Step 3′, the `RS_F = 7` widening | **NOT RUN**, on a cache-key measurement, and the doc says which (§6) |
| `tb_token` / `tb_chain` | **RETIRED FOR GOOD**, with the reason at the targets (§5.5) |
| citation drift | **CLOSED** — three passes, one base each, `VERIFY PASS` on every one, 11 hand repairs enumerated (§12) |

**FOUR DEFECTS FOUND BY THE 9B WORK ITSELF, none of them visible at 0.8B or
2B.**  The first two were found by the gate; the last two by its own fix
round, and all four are in the same family — a checker or a reference that
could not represent the 9B geometry:

1. **`ref/seq_model.py` could not execute a 9B stream at all** — `LOFF_TCNT2`
   (0x60, G3.4's second TCNT CSR) was unmodelled, and the first CSR's model
   truncated the kv bank at NKVH = 4.  §4.0.
2. **`tb/tb_seq_chip.sv`'s TCNT golden holders were `[6]`** — the pre-G3.4
   six-bank geometry — so the FIRST full-model replay reported the RTL's
   correct `6/6` for kv slots 6 and 7 as `expected 0/0`.  The RTL was right,
   the reference was right, and the checker could not hold the answer.
   §5.3.1.
3. **The `.chip` golden never carried kvheads 2 and 3**, at any bank, at any
   geometry — so `tcnt 8` counted banks while half of each bank went
   uncompared, and the elaboration assert meant to catch exactly that pinned
   one dimension of two.  Found by the review, closed in fix round 1 with a
   RED.  §5.3.3.
4. **Three `$fatal` calls could not print their own message** — a
   `{"...", "..."}` brace concatenation is not a format string, so the
   refusal arrived as a 200-digit decimal.  Found by (3)'s RED, which is what
   a RED is for.  §5.3.3.

---

## 1. Provenance and the operating point

**Host:** snoke for every numeric run (`nproc --all` = 48, 247 GiB).
darthplagueis was used for editing, `git`, the citation tools and the
pure-arithmetic checks only.

**Interpreters, `test -x`-probed and recorded in every log header** (the
plan's standing hazard: `ref/.venv/bin/python` is a DANGLING SYMLINK on
snoke, and snoke's system `python3` has no numpy, so `tb/Makefile`'s
`VECPY` fallback resolves to the dangling symlink there and must be
overridden):

| host | `/home/cah/.venv/bin/python` | `ref/.venv/bin/python` | used for |
|---|---|---|---|
| snoke | **exists** (3.12.3, torch 2.12.0+cpu, transformers 5.11.0, numpy 2.4.6) | ABSENT | the emit, every vector generator (`MODELPY=`/`VECPY=`), every Verilator target |
| darthplagueis | ABSENT | **exists** (3.11.15, numpy 2.4.6) | the citation tools and the host-side checks |

**The operating point, spelled out** (plan A1/A2, and written into
`tb/Makefile`'s `W9_*` block so a run is never a guess):

| knob | value | why |
|---|---|---|
| `FABLE5_MODEL` | `9b` | H=4096, FFN=12288, 32 layers (24 DN / 8 GQA), vocab 248,320 |
| `FABLE5_RS_F` | **7** | A2, adopted by user ruling 2026-09-01.  `rtl/conv4_silu.sv:54` bakes the matching shift |
| `--res-scale` | 1 | spec §4.4: at H=4096 the raw residual reaches the Q7.8 rail with no rescale at all |
| `--w4-group` | 128 | D1 (the g64 strip is ratified O2) |
| `--wq` | w4 (default) | |
| `FABLE5_CALIB_STATS` / `_MODE` | `ref/calib_stats_9b_h.npz` / `gptq` | the verified 24.06 GiB Hessian |
| `FABLE5_DN_STATE` | unset = `int16` | A1, the ratified container |
| `SEQ_NCH` / `SEQ_REPACK` | 4 / 1 | the ONLY pack that fits — see §3.1 |

**A2.5 was observed.**  `FABLE5_RS_F=7` is exported for the 9B emission and
every 9B replay tool, and for nothing else; no byte-locked (`0.8b`/`2b`)
emit was run in this task at all, so no process that exports it ever
touched a byte-locked tag.

---

## 2. Step 1 — the scratch high-water probe, MEASURED at 9B

**This is the first thing this task ran, before anything else was read**, on
the brief's instruction: S4's 65,536-word scratchpad is sized by the
allocator's ALGEBRA (`ref/gen_layer_script.py`'s `PEAK_DN` / `PEAK_ATTN` /
`PEAK_MLP` -> `PEAK` -> `SCRATCH`), and the empirical high-water probe that
checked that algebra at 0.8B and 2B had never been re-run for the new
geometry.

The driver was never committed — but it is reproduced VERBATIM in the
appendix of the committed log it produced, `evidence/qwen2b/ra/scratch_probe.log`
(from `evidence/qwen2b/ra/scratch_probe.log:27` on).  It was lifted from
there into a scratch file, and it is reproduced verbatim again in the
appendix of **`evidence/qwen9b/g4/002_scratch_probe_9b_committed.log`**, so
the 9B run is reproducible on the same terms the 2B one is.

**Three adaptations, each named in the scratch file's own docstring** — the
appendix is only worth having if what changed is stated:

| # | the 0.8B/2B appendix | at 9B | why |
|---|---|---|---|
| 1 | the kv-cache reset was the two-element literal M.kc[0] = [[], []] | it is now sized from the module: [[] for _ in range(G._KVH)] | `ref/gen_layer_script.py:309` reads `_KVH = 4` at 4B/9B, and it was 2 when the appendix was written; the literal NARROWS the cache and the ATTN body `IndexError`s on kv head 2 |
| 2 | `assert G.PEAK <= 32768` | `assert G.PEAK <= G.SCRATCH_MAX` | 32,768 was the 15-bit ISA's scratch ADDRESS ceiling.  G3.1 split the array depth (`SCRATCH_MAX`, 65,536) from what an ARG word carries (`ISA_SADDR_MAX`), and **50,208 > 32,768 is the entire reason this task exists**.  The `measured <= derived` assert is UNCHANGED |
| 3 | — | the banner prints `SCRATCH_MAX` | so a reader sees which ceiling was applied |

**The result — M**, 4 seeds x 3 tokens x {DN+MLP, ATTN+MLP}, the last three
lines of `evidence/qwen9b/g4/002_scratch_probe_9b_committed.log`:

```
[9b] MEASURED PEAK=50208  DERIVED PEAK=50208  SCRATCH=65536  headroom=15328
[9b] OK: measured <= derived <= 65536
[9b] import-time invariants: PEAK=50208 scratch_map() max end=50208 SCRATCH=65536 SCRATCH_MAX=65536 ISA_SADDR_MAX=65536
```

**MEASURED == DERIVED == 50,208, inside a 65,536-word array, 15,328 words of
margin** — exactly the brief's expectation, so nothing downstream was
re-derived.  Every one of the four seeds reports the same peak on both
bodies (`DN(+MLP)=50208 ATTN(+MLP)=50208`), which is the shape the 2B log
has too: the peak is `PEAK_MLP`, the MLP body both paths end in, so both
report it.

**The conv-weight preamble is EXCLUDED from the peak and reported beside
it**, as at 0.8B/2B: seed 1 reports `conv-preamble=21536` and seeds 2-4
report `50208`, because `HI` is not reset between the DN body and the next
seed's preamble in the appendix's loop — the preamble figure is the
high-water at the moment the preamble finishes, not the preamble's own
extent.  `HI` is a module-level dict shared across seeds, so seed 2 onward
starts at the previous seed's ATTN high-water.  That is the committed
behaviour verbatim at both older geometries — 0.8B reports
`conv-preamble=12288` on seed 1 and `15872` on seeds 2-4, 2B reports
`15360` then `25600` — and it is reproduced rather than "fixed", because
the number the probe exists for is `MEASURED PEAK`, which resets `HI`
explicitly.

**Provenance:** `evidence/qwen9b/g4/001_scratch_probe_9b.log` is the FIRST
run and its header reads `tree: 1c62570+dirty` — it ran before this task's
enablement commit landed.  It is committed as-is; `002` is the same probe on
the committed tree `0cf5f9c` with no dirty flag, and is the log the numbers
above are read from.  Both agree line for line.

---

## 3. Step 1 — the emission

### 3.1 There is no 1-channel 9B stream, and that is measured

The brief's interface line says the task produces `<prefix>.txt` / `.e` /
`.e4`.  **It produces `.txt` and `.e4`, and the missing `.e` is a result,
not an omission.**

`sw/hwmap.plan_weights`' default is the **nch-INDEPENDENT** pack — every
channel reserves the WHOLE image, because a multi-channel stream's MVGO
`WBASE` is `base + r0*stride` with `r0` a GLOBAL row index — and that is
the layout every artifact frozen before R-c encodes, at nch=1 and nch=4
alike.  At 9B that pack is **3,902.3 MiB in one span against a 1,280 MiB
window** (`W_BASE 0x1000_0000` .. `EMB_BASE 0x6000_0000`) and the function
**refuses** rather than returning an address nobody could use.  The nch=4
REPACK, where each channel packs only the rows it owns, lands the busiest
channel at 978.6 MiB = 76.5 %.

Task 5 derived those numbers from shapes; §3.3 measures them on the emitted
manifest, and `evidence/qwen9b/g4/g4a_artifact_inventory.py` offers the SAME
manifest to `plan_weights` with `rows_of=None` and records what comes back.
**M**, `evidence/qwen9b/g4/013_inventory_9b.log`:

```
NCH=1 — the nch-INDEPENDENT pack, offered to the same manifest
  REFUSED: AssertionError: weight images (249 wids, 4091904000 bytes packed
  from 0x10000000) reach chan 0 0x103e58000, past EMB_BASE 0x60000000 —
  move EMB_BASE or split the images across DDR channels
```

So the 9B set is named `.e4`, exactly as the 0.8B four-channel set is, and
`tb/Makefile`'s `W9_SEQ` says so.

### 3.2 `shape_isa` in the emitted metadata — the Task 10 hand-on, closed

G3.4 built the MVGO `ng` envelope so a LOADER arms it from the artifact —
`ref/seq_chat.py:380`, `ref/seq_model.py`'s `gate()` and
`tb/scripts/gen_seq_chip_vectors.py` all read `meta.get("shape_isa")`, and
absent means *not stated* means the check stays off, which is what keeps a
frozen isa=1 build_034/build_035 stream valid.  **No emitter wrote the key**
— Task 10 measured `0 of 13 artifact metas declare shape_isa`.

**Now one does.**  `ref/seq_format.SeqEmitter.finish` writes
`meta["shape_isa"] = SHAPE_ISA_9B`.  This class emits SEQ_ISA v2.0 and
nothing else, so it can state the layout with no caller involved.

**And the emitter now STATES it to its own validator too**, which was the
second hand-on: `finish()` called `validate_stream(recs)` with no
`shape_isa`, so the one BUILDER that could check its own finished stream
was the one not checking.  It now passes `SHAPE_ISA_9B`, the same lockstep
`tb/scripts/gen_seq_unit_vectors.py:812` is in.  It cannot fire in practice
— `_mvgo` packs through `shape_word`, whose own assert refuses an
out-of-envelope `ng` before a record exists — which is exactly why it
belongs: a second, independent reading of the same bound over the finished
byte stream.

**The key is GATED on the tag, and the reason is measured, not assumed.**
`evidence/qwen2b/rc/t3_locks.sh` lock B `cmp`s the WHOLE 0.8B
e4.seq.json, not just the .seq sha
(`evidence/qwen2b/rc/t3_locks.sh:39-43`, whose own echo says the weight
plan lives *outside the hashed stream*), so an unconditional key would
move bytes a gate pins.  The condition is
`_GLS.MS.TAG not in _GLS.BYTELOCKED_TAGS` — the SAME list, in the SAME one
place it lives (`ref/gen_layer_script.py:69`), that spec A2.5 uses to gate
`rs_f`.

**M**, both halves, on freshly emitted streams, and the 0.8B half is a RUN:
`evidence/qwen9b/g4/031_bytelock_08b.log`, `G4A_BYTELOCK_08B: PASS`,
header `FABLE5_RS_F=unset` (A2.5 — `run_g4a_bytelock_08b.sh` REFUSES to run
with it exported).

| tag | emitted meta | the log's line |
|---|---|---|
| `9b` | `shape_isa: 2` | step 5 of `evidence/qwen9b/g4/031_bytelock_08b.log` |
| `0.8b` | key ABSENT, and `rs_f` ABSENT | steps 1-3 of the same log |

and the 0.8B stream still gates: `SEQ GATE: PASS`, `46/46 checkpoints ALL
BIT-EXACT`, `BANKED BIT-EXACT` — step 4.  **That gate is the one that
matters here**, because `ref/seq_format.SeqEmitter.finish` now calls
`validate_stream(recs, shape_isa=SHAPE_ISA_9B)` UNCONDITIONALLY, for every
tag including the byte-locked ones: a behaviour change on the 0.8B emit path,
which without a 0.8B run would have been reasoning rather than evidence.

**What the byte-lock covers, and against which emitter — because "unmoved"
is ambiguous otherwise.**  `ref/scripts/regen_gate.sh:5` pins the sha256 of
the 0.8B `tb/scripts/w4/model_v2_s1.e.seq` and
`ref/scripts/regen_gate.sh:41` compares the emitted .txt against
`tb/scripts/model_v2_s1.txt`; `evidence/qwen2b/rc/t3_locks.sh:39-43` compares
the WHOLE 0.8B `tb/scripts/w4/model_v2_s1.e4.seq.json`, not just the stream;
`evidence/qwen9b/g2/FINAL_BYTELOCK.md` pins 54 file shas, both the stream and
its json, of the committed 0.8B and 2B sets.  Every
one of those checks a RE-EMISSION FROM THE CURRENT TREE against a COMMITTED
v1.7 artifact — and **G3.1 spent that lock**: this tree emits SEQ_ISA v2.0, a
v2.0 emitter cannot reproduce a v1.7 stream byte for byte, and
`ref/gen_layer_script.py:57-63` says so in the source.  §10.6 records that
neither gate was run and why.  So the lock this task can still move, and the
one the claim is about, is HEAD against its own immediate ancestry — which is
exactly what step 3 measures, `cmp` against the same stream emitted from a
worktree at `1c62570`, the tree before `shape_isa` and before the
unconditional validate:

```
  3  IDENTICAL  31840 B  lay_s1.e.seq
     IDENTICAL   5089 B  lay_s1.e.seq.json
     IDENTICAL  63360 B  lay_s1.e.seqdata.bin
     IDENTICAL 1658572 B lay_s1.txt
     both .seq sha256 03338f9425fb13a33147b61e1382224c24a384349b55f323d7192e7ffab0fa4c
```

**The declared-gap line moved, and it is re-measured rather than asserted.**
`evidence/qwen9b/g3/g34_shape_isa_paths.py`, re-run unmodified:

```
  GAP       9 of 22 artifact metas declare shape_isa (no emitter writes it yet — Task 11)
SHAPE_ISA_PATHS: PASS (0 problem(s))
```

The nine are this task's own — four `lay9b_s*`, four `tok9b_s*` and
`model_9b_s1` — and every one of the thirteen older metas still declares
nothing, which is the byte-lock gate doing its job.  **The parenthetical
`(no emitter writes it yet — Task 11)` is now STALE PROSE inside committed
evidence.**  It is deliberately not edited (the campaign does not rewrite
committed evidence in place) and is named in §11 so no reader takes it as
current.

### 3.3 The emit itself

`make -C tb w9_9b_model_script MODELPY=/home/cah/.venv/bin/python`, on snoke,
at the operating point of §1, **without `--allow-clip`** (§3.4 is why).
Log `evidence/qwen9b/g4/003_emit_9b_s1.log`, `rc: 2`.

**Wall clock — M**, from the log's own stamps and the milestone lines:

| phase | wall |
|---|---|
| GPTQ over 32 layers | **2 h 25 min** (`21:43:18` -> `00:08` on the `quantized 32 layers` line) |
| the LM head (248,320 x 4,096, W4 + GPTQ) | **18 min** |
| the emit loop, 6 forward steps x 32 layers + the full-vocab head | **17 min** |
| **total** | **3 h 00 min** (`21:43:18` -> `00:43:04`) |

Task 5 measured 2 h 55 min for the quantization alone at
`OMP_NUM_THREADS=8`; this ran at 16 and the phase took 2 h 25 min, so the
pass is only weakly thread-scaled and **3 h is the number Task 14 should
budget per 9B emission.**

**What came out — M**, `evidence/qwen9b/g4/013_inventory_9b.log`, checked
against Task 5 §5.2's projections, which were derived from shapes:

| quantity | measured here | Task 5's projection |
|---|---|---|
| weight images | **249**, 4,091,805,696 B = **3,902.2 MiB** | 249, 3,902.2 MiB — **exact** |
| embedding table | **2,034,237,440 B = 1,940.0 MiB** | 1,940.0 MiB — **exact** |
| `emb_row_bytes` / `EMBLOG2` | **8192 / 13** | 8,192 / 13, *"exactly `SEQ_EMBLOG2_MAX`"* |
| `rs_f` in the manifest | **7** | A2's adopted value; Task 5 could emit no artifact at all |
| LM-head wid, layout | **248, `LAYOUT_ILV`**, `chunk_rows` 2048 | wid 248, `LAYOUT_ILV`, 2048 — **exact** |
| per-channel tops | **`0x4d290000` / `0x4cf78000` / `0x4ce70000` / `0x4ce70000`** | the same four addresses — **exact** |
| busiest channel | **978.6 MiB = 76.5 %** of the 1,280 MiB window | 978.6 MiB = 76.5 % — **exact** |
| the `.txt` | 247,618,489 B = 236.1 MiB | not projected |

**And the wid ORDER is now checked, which is the thing Task 5 said only an
emitted manifest could check.**  `plan_weights` re-derived from the manifest
on disk, with `wdir` set so it stats every image against `nrows * stride`,
reproduces **all 249 bases identically** to the ones the stream's MVGO
records already encode.  The two sides share no intermediate: one is the
emitter's incremental plan frozen into the record stream, the other is the
manifest read back off the disk.

**The stream — M**, and these are the shas the gate pins (the set is
regenerable and NOT committed):

All of them live under `tb/scripts/w9/` with the stem model_9b_s1:

| file | bytes | sha256 |
|---|---|---|
| model_9b_s1.e4.seq | 2,535,728 | `af6dca2930bb2d8368f0ebde70f25b673676ac16523ce60a406b56a0f7e7f340` |
| model_9b_s1.e4.seqdata.bin | 2,136,576 | `c98c88c29e772fb26536ee1a48984609e8e9383c49145a85568a1324794df7b5` |
| model_9b_s1.e4.seq.json | 114,482 | `b1bc37f48b3aaf2487cfebeaeaca22858a51db579160bcd7ee8dea199dd9150f` |
| model_9b_s1.weights.json | 36,810 | `d11cedf145ca6f1f44a4177321e76b22815f39a86777ead0fbf4a04396b5d338` |
| the 249 images | 4,091,805,696 | image-CONTENT sha256 `57a04d4f94d8f3235414b2ad4d15c1a165ccc8e9f061a2c0fa701265c120b934` |

**That last row was WRONG in the first cut of this gate, and the correction
is the point of it.**  `g4a_artifact_inventory.py` documented "a sha256 over
the sorted per-image (name, size, sha256) list" and computed rows of
`name:size` — no content — so the pin it offered for 3.9 GiB of uncommitted
weight images would have been unchanged by a regeneration that produced
different bytes at the same 249 sizes.  The rows now carry each image's own
sha256 (`evidence/qwen9b/g4/g4a_artifact_inventory.py:100-115`), the printed
label says `image-CONTENT sha256`, and the number above is from the re-run,
`evidence/qwen9b/g4/034_inventory_9b_clean.log`.  The retired value was
`f39d87a0ad17f7387d9dfc9532646fdc6ab155ac4da2dbc04fc1080422b26e90`; it is
recorded here only so a reader of an earlier draft can tell the two apart.

**158,483 records**, `steps 6`, **`loop_steps 3`** with
`loop_structurally_safe true`, `shape_isa 2`, `weight_repack true`,
`nch 4`, `expect_tokens [2614, 314, 279, 369, 11751, 13]`,
`prompt_fed [760, 6511, 9338]`.

**One number worth reading on its own: `emb table |q|max 60 of 32767`.**
Task 5's run at `RS_F = 8` reported **120**.  Exactly half, because
`RS_F = 7` scales the embedding table by one bit less — an independent
confirmation, from inside the emitter, that the operating point actually
took, rather than a claim that the environment variable was set.

### 3.4 The runtime range audit — the measurement Task 5 could not make

Task 5 handed this on explicitly: *"`gen_model_script`'s runtime range audit
has no measurement in this campaign yet"*, and it is the only thing that
closes the eight activation-dependent formats `ref/audit_ranges.py` §5
defers.  **`--allow-clip` was deliberately NOT passed**, so the audit is a
measurement rather than a suppressed banner.

**It FAILS.  M**, and the failure is the result:

```
site            rail hits    of words    |max|
alu1                   18     4432896    32768
alu3                    9     1179648    32768
alu5                  100      589824    32767
alu6                  357     2359296    32767
alu7                    7      196608    32767
conv                  179     1179648    32767
embed                   0       24576       51
gate(Q15)               0        9216    32767
vn0 / vn1 / vn2         0      ...
TOTAL                 670
DeltaNet state S_F=13 (int16 Q2.13, +/-4.0): true saturations=72 of
  75497472 state writes, |S|max=55995 of 32767 (170.9% of the int16 rail,
  = 6.835 in Q2.13)
silu 21-bit port clips: 0
residual stream |x|max = 27008 of 32767 (82.4% of the int16 Q7.8 rail)
```

Read off it:

* **The residual rail: 82.4 % at `res_scale = 1`.**  Spec §4.4 says at
  H = 4096 the raw residual reaches the Q7.8 rail with no rescale applied at
  all; **this is that sentence measured** — 1.21x of margin, and it is why
  the 0.8B S=8 / 2B S=4 rescales are absent from the 9B recipe.
* **The `S_F = 13` soak: 72 saturations of 75,497,472 state writes** —
  9.5e-7 of them — on 19 (dn_slot, head) pairs, worst |S| 6.835 against a
  ±4.0 rail.  Cross-checked by an independent counter:
  `S_F soak cross-check (layer_fixed cache['sat'], ...): 72 saturations`,
  the same number from `ref/layer_fixed.py`'s own cache rather than from the
  scratchpad model.
* **670 rail hits** across the ALU and conv sites out of ~17.9 M written
  words.  `embed`, `gate(Q15)` and all three `vn` sites are CLEAN.
* **The y32 accumulator never overflows**: the worst occupancy is the
  8192x4096 `in_qkv` at 22 magnitude bits of 31, **9 bits spare**.
* **`silu` 21-bit port clips: 0**, and `ATTN k_a clamped up to 0: 0 times`.
* **The gate-port clamp is the biggest un-priced item**, and it is now
  priced: **61** (layer, head) pairs clamp, worst
  `|decay_clamp - decay_spec| = 22430/32768 = 68.45 % FS` at L12h18.  That
  is `layer_fixed.quant_deltanet`'s deliberate saturation of `dt_bias` / `A`
  where the `gate_unit` ports as built would WRAP; it is documented in
  `ref/gen_model_script.py`'s header as future work needing new ROM hex, and
  9B exercises far more of it than 0.8B did.

**What the failure does and does not mean.**  `gen_model_script` says it
itself: *"The script and its artifacts were still written and are BIT-EXACT
against the RTL — the reference models exactly the same clip the hardware
performs, so a sim/HW gate on them still proves the engine correct; what
saturation costs is NUMERICAL FIDELITY to the float model."*  Every gate in
§4, §5 and §7 below is therefore valid, and §7 measures the fidelity cost
directly against the bf16 model rather than inferring it.

**It cost a non-zero rc**, which `make` propagates: `003`'s last lines are
`make: *** [Makefile:1227: w9_9b_model_script] Error 1` and `=== rc: 2`.
The artifacts land regardless because `ref/seq_format._finalize` is an
`atexit` hook — the `SEQ: 158483 records ...` line is printed AFTER the
`RANGE AUDIT FAILED` message, in the same log, which is the evidence that
the ordering is what it is claimed to be.  **No re-run with `--allow-clip`
was made**: it would cost another 3 h to produce byte-identical artifacts
and a quieter log.

---

## 4. Step 2 — the reference lockstep

### 4.0 The 9B stream did not run at all, and the reason was in `ref/seq_model.py`

The dispatch context warned that `ref/seq_model.gate()` and
`tb/scripts/gen_seq_chip_vectors.py` get their FIRST end-to-end run on a
v2.0 stream in this task.  They did, and the first one failed immediately:

```
seq_format.SeqValidationError: CSRWR to unmodelled layer offset 0x60
```

**`LOFF_TCNT2` (0x60) is G3.4's second TCNT CSR** — at NKVH = 4 a kv_slot
has four 10-bit append counters and a 32-bit CSR word holds two, so
`rtl/layer_chan.sv` writes kvheads 0/1 at 0x008 and 2/3 at 0x018 (= L+0x60),
and `ref/seq_format.SeqEmitter.on_treset` emits BOTH CSRWRs.  `SeqExec`
knew only the first.  It is exactly the wall-9 pair the RTL comment
describes, one half of which had never been given a reference model.

**And the half it did have was wrong at NKVH = 4**: `M.T[M.kv_slot] = [0, 0]`
REPLACES the slot's counter list with a two-element one, silently narrowing
the bank.  Nothing would have raised — attention would simply have read a
cache whose counter said something else.

Both are now modelled the way the RTL writes them
(`ref/seq_model.SeqExec._tcnt_wr`): one CSR word = two 10-bit counters,
`{[25:16], [9:0]}`, at `first` and `first+1`.  The `.txt` reader's `T`
record zeroes the whole slot (`[0] * len(...)`) rather than a 2-literal, so
it follows `Mach.Treset`'s `[0] * _KVH` at any NKVH.

**The 0.8B path is unmoved and it was checked, not assumed** — `SEQ GATE:
PASS` on a freshly emitted 0.8B layer stream, `46/46 checkpoints ALL
BIT-EXACT`, `BANKED BIT-EXACT (conv/S/KV/TCNT/EOUT/AMAX)`, step 4 of
`evidence/qwen9b/g4/031_bytelock_08b.log`, with the byte comparison against
the pre-change emitter in step 3 of the same log (§3.2).

The `.chip` golden's `TCNT` line DID move, in fix round 1 and for a different
reason: it now carries all `NKVH` counters per bank instead of the first two
(finding I6, §5.3.3).  At the 0.8B/2B geometries that changes the file too —
and those families are **not re-run**, by the controller's ruling: the 2B W8
smoke is RETIRED at `tb/Makefile:1139` (G3.3 — this bitstream has no W8
engine mode) and G3.1 retired the v1.7 replays, so `obj_dir_tb_seq_chip` and
`obj_dir_tb_seq_chip_w8` have no live gate to break.  `tb_seq_chip_9b` at 9B
supersedes both, and it is the one this document runs.

### 4.1 `SEQ GATE: PASS`

`ref/seq_model.py --gate <prefix>` replays BOTH representations of the same
program — the `.txt` through `TxtReplay` and the `.seq` through `SeqExec` —
and compares live-state checkpoints, the final scratchpad, the banked state
(conv / DeltaNet S / KV / TCNT / EOUT / AMAX) and the token stream.  It is
the arbiter that says the emitter, the executor and the fixed-point model
agree, and the 2B campaign's hardest bugs were exactly here.

**M**, `evidence/qwen9b/g4/010_seqgate_smokes.log`, last line
`G4A_SEQGATE: ALL PASS (8 artifact(s))` — the four layer seeds and the four
token seeds:

| artifact | checkpoints | scratch | banked | tokens |
|---|---|---|---|---|
| `lay9b_s1` .. `s4` | 46/46 ALL BIT-EXACT | 4096 of 65536 differ, **0 outside** the 28,672 declared staging words -> CLEAN | BIT-EXACT | IDENTICAL `[]` |
| `tok9b_s1` | 48/48 ALL BIT-EXACT | 4095 of 65536, 0 outside -> CLEAN | BIT-EXACT | IDENTICAL `[2380, 6362]` |
| `tok9b_s2` | 48/48 ALL BIT-EXACT | 4096 of 65536, 0 outside -> CLEAN | BIT-EXACT | IDENTICAL `[5290, 4397]` |
| `tok9b_s3` | 48/48 ALL BIT-EXACT | 4096 of 65536, 0 outside -> CLEAN | BIT-EXACT | IDENTICAL `[1235, 4971]` |
| `tok9b_s4` | 48/48 ALL BIT-EXACT | 4096 of 65536, 0 outside -> CLEAN | BIT-EXACT | IDENTICAL `[5591, 703]` |

`of 65536` is the 16-bit scratch ISA carrying a real 9B body: the array
Task 7 widened, addressed by a stream Task 5 could not emit.

**And on the full model — M**, `evidence/qwen9b/g4/012_seqgate_model.log`,
last line `G4A_SEQGATE: ALL PASS (1 artifact(s))`:

```
  stream   158483 records, 2535728 B (sha256 af6dca2930bb2d83)
  loop     3 steps  (looped)  STRUCTURALLY SAFE
  .txt     56118 commands, 22550016 host-relayed words,
           checks {'R': 2358, 'E': 1494, 'A': 6, 'V': 1494} (135.1s)
  .seq     52470 commands issued, movers MOVX=5976 MVGO=8220 MOVY=8220
           LDC=1062 EMB=6 AMAXL=6 (835.7s)
  CHECKPT  2358/2358 live-state checkpoints sampled, ALL BIT-EXACT
  SCRATCH  4096 of 65536 words differ at the end; 0 outside the declared
           y32 staging windows (28672 words) -> CLEAN
  BANKED   BIT-EXACT (conv/S/KV/TCNT/EOUT/AMAX)
  TOKENS   IDENTICAL  [2614, 314, 279, 369, 11751, 13]
SEQ GATE: PASS
```

**2,358 live-state checkpoints, all bit-exact**, over 6 forward steps of a
32-layer model with a live KV cache and DeltaNet state — plus 1,494 `E`
(EOUT) and 1,494 `V` (matvec y32) checks, and 6 `A` (argmax) checks on the
full 248,320-row head.  **`loop 3 steps (looped) STRUCTURALLY SAFE`** means
the emitter closed the decode loop AND that no record in the looped body
still carries a data-dependent immediate — the `epsnorm` + `dyn_ka`
combination doing its job at 9B.

**Wall clock:** 135.1 s for the `.txt` replay, 835.7 s for the `.seq`
replay; 16 min for the rung.

#### 4.1a Fix round 1 — Step 2 on ALL FOUR model seeds

The 4-seed ruling binds Step 2 as well as Step 3, and the goldens moved
anyway (§5.3.3), so the whole rung was re-run on the round's tree.  **M**,
`evidence/qwen9b/g4/049_seqgate_model_s1to4.log` (seeds 1-3; truncated, §9.8)
and `evidence/qwen9b/g4/050_seqgate_model_s4.log` (seed 4,
`G4A_SEQGATE: ALL PASS (1 artifact(s))`, `rc: 0`):

| artifact | records | checkpoints | scratch | banked | tokens |
|---|---|---|---|---|---|
| `model_9b_s1` | 158,483 | **2358/2358** ALL BIT-EXACT | 4096 of 65536, 0 outside -> CLEAN | BIT-EXACT | IDENTICAL `[2614, 314, 279, 369, 11751, 13]` |
| `model_9b_s2` | 81,092 | **2358/2358** ALL BIT-EXACT | 4095 of 65536, 0 outside -> CLEAN | BIT-EXACT | IDENTICAL `[279, 264, 854, 11, 303, 264]` |
| `model_9b_s3` | 81,092 | **2358/2358** ALL BIT-EXACT | 4096 of 65536, 0 outside -> CLEAN | BIT-EXACT | IDENTICAL `[313, 430, 2510, 198, 1445, 27180]` |
| `model_9b_s4` | 158,483 | **2358/2358** ALL BIT-EXACT | 4095 of 65536, 0 outside -> CLEAN | BIT-EXACT | IDENTICAL `[11, 0, 271, 803, 369, 498]` |

Four different prompts, four different token trajectories, **the same 2,358
checkpoints** — the checkpoint count follows the six forward steps, not the
prompt, which is why s2 and s3 reach it on half the records.  `SEQ GATE:
PASS` on every one, so Step 2 is green on all four before Step 3 runs any of
them.

### 4.2 The `seq_model` / `layer_fixed` lockstep, and the multi-token run

The brief asks for the SEQ gate, then a `seq_model` / `layer_fixed` lockstep
across a full 9B token, then a multi-token run.  **All three are inside the
one artifact**, and it is worth naming which mechanism carries which,
because they are different mechanisms:

* **`layer_fixed` lockstep** is done DURING EMISSION, per layer, per step,
  by the generator itself: `ref/gen_model_script.py` computes
  `gold = LF.layer_decode_fx(x, qw, cache, t)` and hands it to `dn_token` /
  `attn_token`, which self-check the scratchpad model against it before a
  single command is written.  A 9B `.txt` therefore cannot come out of that
  file unless every layer of every step already matched `layer_fixed`.
* **`seq_model` lockstep** is `--gate`, §4.1: the same program in two
  representations, checkpoint by checkpoint.
* **the multi-token run** is the artifact's own shape: `prompt_seed 1` is 4
  tokens and `ntok = 3`, so **6 forward steps** — 3 prefill and 3 generated
  — through 32 banked layers with a live KV cache and DeltaNet state.  The
  stream's own metadata says so: `steps 6`, `prompt_fed [760, 6511, 9338]`
  (the three fed tokens; from step 3 the generator eats its own argmax),
  `expect_tokens [2614, 314, 279, 369, 11751, 13]`.

**All three passed, and the numbers are §4.1's.**  The `layer_fixed`
lockstep is discharged by the artifact EXISTING: 32 layers x 6 steps =
**192 layer-steps**, each self-checked against `LF.layer_decode_fx` before
its commands were written, and any mismatch would have aborted the emit
rather than produced a `.txt`.  The `seq_model` lockstep is the 2,358
bit-exact checkpoints.  The multi-token run is the 6 steps and the 3
generated tokens, which §7 then takes to the bf16 model.

---

## 5. Step 3 — the chip-level replay in Verilator, on snoke

**The elaboration is its OWN, a THIRD one.**  `obj_dir_tb_seq_chip` is the
NMV=1 / WIMGPC=0 build the frozen 0.8B gates use and `obj_dir_tb_seq_chip_w8`
is the 2B W8 twin; a repacked 9B stream needs `-GNMV=4 -GWIMGPC=1` and gets
`obj_dir_tb_seq_chip_9b`.  Neither of the other two is touched, which is
also the standing rule about never running one obj_dir from two hosts.

### 5.1 Rung A — the one-layer smoke, 4 seeds

One DeltaNet layer + one GQA layer at the 9B geometry, 2 tokens, random
weights (no checkpoint, no HF cache, no Hessian), repacked over 4 channels.
`make -C tb w9_9b_smoke_scripts` builds it; `evidence/qwen9b/g4/run_g4a_replay.sh`
runs the four seeds as four processes against ONE binary, concurrently, and
prints a wall clock for each.

**M**, `evidence/qwen9b/g4/008_smokeA_layer_replay.log`, last line
`G4A_REPLAY lay9b_s: ALL PASS`:

| seed | rc | wall | cycles | verdict |
|---|---|---|---|---|
| 1 | 0 | 186 s | 3,782,887 | `TB_SEQ_CHIP PASS` |
| 2 | 0 | 189 s | 3,782,887 | `TB_SEQ_CHIP PASS` |
| 3 | 0 | 184 s | 3,782,887 | `TB_SEQ_CHIP PASS` |
| 4 | 0 | 181 s | 3,782,887 | `TB_SEQ_CHIP PASS` |

**189 s total wall** for all four in parallel.  Each launch:
`4027 records, 0 tokens, 36864 scratch words, NMV=4 WIMGPC=1`, and
`ddr beats 13459 (miss 0), weight beats 6897792 total across 4 chan (miss 0)
[1724448/1724448/1724448/1724448]` — the four channels carry an exactly
equal share, which is what `LAYOUT_CONTIG` over four equal images should do,
and **zero misses** on either the record/const path or any weight channel:
every beat the engines asked for was inside a region the plan placed.

**The four seeds report the same cycle count and the same beat counts**
because the schedule is data-independent; what differs between them is the
weights, and therefore every checked value.  That is the point of the four.

**Two defects were found by this rung and both are fixed in the tooling
rather than worked around:**

1. **`ref/gen_token_script.py` refused to write a 9B manifest** (log
   `evidence/qwen9b/g4/004_smoke_scripts_build.log`, `rc: 2`):
   `dump_weights` asserts that a manifest with no `rs_f` key is only written
   at `RS_F == 8`, because a reader defaults the missing key to 8 and would
   dequantize every logit by a factor of two.  **The guard is right**; the
   generator was not stating the value.  Fixed by stating it, value-gated
   exactly as `ref/gen_layer_script.py:2277` gates it.
2. **The replay runner ran the binary from the repo root**, where
   `layer_chan`'s `$readmemh ../rtl/roms/*.hex` resolves one directory too
   high.  Verilator prints `$readmem file not found` as a **WARNING**, leaves
   every ROM X and answers WRONG rather than failing — the run in
   `evidence/qwen9b/g4/007_smokeA_layer_replay.log` is the record of it, and
   it is committed as the RED.  The runner now `cd`s to `tb/` **and** fails
   the rung if that string appears in any seed's log, so the class cannot
   come back quietly.  **Provenance caveat, stated because the header cannot
   say it**: `run_g4a_replay.sh` was still UNTRACKED when 007 ran, so 007's
   `tree: a6bf85f` line does not pin the script it ran — that was the
   pre-fix version, which cd'd to the repo root and carried no ROM check.
   008 ran the committed one.  (007's four seeds show `rc=143`: they were
   still spinning on X ROMs at 153 s and were killed, which is itself the
   symptom — a correct run of the same streams takes 186 s and ends in
   `TB_SEQ_CHIP PASS`.)

### 5.2 Rung B — the token loop, 4 seeds

The layer smoke emits `EMB = AMAXL = JMP = 0` — it generates no tokens at
all — so it is blind to the embed / argmax / decode-loop path.  At 9B that
path carries **`EMBLOG2 = 13`, exactly `SEQ_EMBLOG2_MAX`, with zero
headroom** (Task 5 §5.2a), which is the R-c wall-8 failure mode's natural
home.  This rung is 2 layers, 2 generated tokens, vocab 8,192 — minutes
rather than the hours the full vocabulary costs — with the same 4 seeds.

**M**, `evidence/qwen9b/g4/009_smokeB_token_replay.log`, last line
`G4A_REPLAY tok9b_s: ALL PASS`:

| seed | rc | wall | cycles | tokens | verdict |
|---|---|---|---|---|---|
| 1 | 0 | 198 s | 4,049,140 | 2 | `TB_SEQ_CHIP PASS` |
| 2 | 0 | 195 s | 4,049,140 | 2 | `TB_SEQ_CHIP PASS` |
| 3 | 0 | 193 s | 4,049,140 | 2 | `TB_SEQ_CHIP PASS` |
| 4 | 0 | 189 s | 4,049,140 | 2 | `TB_SEQ_CHIP PASS` |

**198 s total wall** for all four in parallel; `2139 records, 2 tokens,
36864 scratch words`, `tcnt 8`, and again `ddr beats 14577 (miss 0), weight
beats 7438464 total across 4 chan (miss 0)`.

`tcnt 8` is worth reading: it is the count of TCNT lines the `.chip` golden
carries and the TB checked — **eight kv slots**, the 9B bank count, each
compared after the run.  §4.0's `_tcnt_wr` is what makes those meaningful at
NKVH = 4.

### 5.3 Rung C — the full 9B model

**The first time the whole model has run on the RTL anywhere.**  One prompt
seed here and four after fix round 1 (§5.3.4), 158,483 records, 6 forward
steps through 32 real layers, four
`matvec_chan` engines each served its own ~975 MiB weight region out of the
files by `tb/seq_mem_file.sv`, plus the 1,940 MiB embedding table and the
2.5 MB record stream.

#### 5.3.1 The first run FAILED, and the checker was wrong

**M**, `evidence/qwen9b/g4/016_full_model_replay.log`, `rc: 134`, **9,844 s
(2 h 44 min)** of wall clock:

```
tb_seq_chip: launch 0 [-] rec_off 0, 158483 records, 6 tokens, 36864 scratch
             words, NMV=4 WIMGPC=1 LAT=4 DDRLAT=32 WLAT=40
  TOK[0] = 00a36 (2614) == golden OK      ... all six OK
  TCNT[kv 6] = 6/6, expected 0/0
  TCNT[kv 7] = 6/6, expected 0/0
%Fatal: tb_seq_chip.sv:872: launch 0: 2 comparison failures
```

**Exactly two comparisons failed** out of six tokens, eight XRF, EOUT, AMAX,
eight TCNT banks and 36,864 scratch words.  And the golden file the TB was
reading **says 6/6 for both**:

```
$ grep ^TCNT tb/scripts/w9/model_9b_s1.e4.chip
TCNT 0 6 6 ... TCNT 5 6 6   TCNT 6 6 6   TCNT 7 6 6
```

So `ref/seq_model.py` said 6/6, `layer_chan` said 6/6, and the **testbench
compared the RTL's correct answer against a zero it had invented**.

`tb/tb_seq_chip.sv` declared `exp_tcnt0/1` and `prev_tcnt0/1` as `[6]` — the
**pre-G3.4 six-bank geometry** — while `rtl/layer_chan.sv:367`'s `tcnt_bank`
is `[N_KV][NKVH] = [8][4]` since G3.4, and the parser indexed them with
`a[2:0]`.  A 9B artifact uses **all eight** kv slots (`slot_plan` gives the
32 layers kv 0..7, one bank per four layers, the eighth GQA layer landing on
kv 7), so the golden's TCNT lines for slots 6 and 7 were written OUT OF
BOUNDS and dropped while `n_exp_tcnt` still counted them; the compare then
read an out-of-bounds zero.

**Nothing at 0.8B or 2B could have found this**: those geometries have six
kv slots and never write a seventh TCNT line.  It took the first 9B
full-model replay, which is what this rung is for.

**The repair is the one this same file's MEM parser already documents** —
*"a golden the checker cannot index is a broken gate, not a mismatch"*:

* the four holders are sized from `TB_KV_NB`, a mirror of `layer_chan`'s
  `N_KV`, and the mirror is checked **against the DUT itself** at time 0
  with `$size(u_layer.tcnt_bank)` rather than tied by a parser;
* the parser **REFUSES** a TCNT line for a slot past the end instead of
  truncating its index, closing the aliasing half of the same defect.

`make -C tb lint_seq_chip_9b` is clean at `-Wall` — `rc: 0`, zero
`%Warning` and zero `%Error`, `evidence/qwen9b/g4/038_lint_seq_chip_9b.log`,
which is the log this sentence lacked in the first cut of this gate — and
`evidence/qwen9b/g4/021_rebuild_and_smoke_regression.log` re-runs both smoke
rungs on the rebuilt binary — `G4A_REPLAY lay9b_s: ALL PASS` and
`G4A_REPLAY tok9b_s: ALL PASS`, 8 seeds, `rc: 0` — so the fix moved nothing
else.  **016 is committed as the RED.**

#### 5.3.2 The re-run — `TB_SEQ_CHIP PASS`

**M**, `evidence/qwen9b/g4/022_full_model_replay_r2.log`, `rc: 0`, last line
`G4A_REPLAY model_9b_s1: ALL PASS`:

```
tb_seq_chip: launch 0 [-] rec_off 0, 158483 records, 6 tokens, 36864 scratch
             words, NMV=4 WIMGPC=1 LAT=4 DDRLAT=32 WLAT=40
  burst: 111930 write bursts (26423808 beats), 162108 read bursts
         (40820736 beats), busy_wr 50894720 busy_rd 47368548,
         decerr 0 non-OK 0, BLAT=4
  ddr beats 544805 (miss 0), weight beats 383606784 total across 4 chan
         (miss 0) [96180480/95876352/95774976/95774976]
TB_SEQ_CHIP PASS: .../model_9b_s1.e4 (launches 1, 200098192 cycles total,
                  scratch 36864/launch, tokens 6, tcnt 8)
```

**Wall clock: 9,712 s = 2 h 41 min 52 s**, one seed, one process.

Read off it:

* **200,098,192 cycles** for 6 forward steps of the whole model — **33.35 M
  cycles per token** at this geometry.  At the 250 MHz `aclk` the TB models
  that is 7.50 tok/s; the feasibility study's board figure is 5.11, and the
  gap is the TB's fabric model (fixed `DDRLAT` / `WLAT`, no refresh, no bank
  conflicts) being kinder than four real DDR4 channels.  **The cycle count is
  the measurement; the tok/s is a division and must not be read as a board
  prediction.**
* **`weight beats 383,606,784` across four channels, `miss 0`** — at 64 B a
  beat that is 24,550,834,176 B = **22.87 GiB** of weight traffic, fetched by
  the engines' own AXI masters out of the real packed images, with not one
  beat outside a region the plan placed.  The per-channel split
  `96180480 / 95876352 / 95774976 / 95774976` is the 978.6 / 975.5 / 974.4 /
  974.4 MiB pack read six times over — 3,902.9 MiB x 6 = 22.87 GiB, which is
  the same number from the other end.
* **`decerr 0 non-OK 0`** on the burst fabric, and `ddr beats 544805
  (miss 0)` on the record / const / embedding path.
* **`tcnt 8`** — all EIGHT kv banks compared, which is the point of §5.3.1.
  It counts BANKS, not counters: at the time of this run each bank compared
  **two** of its four kvheads, because the golden carried only two columns.
  That is finding I6 and §5.3.3 closes it; the number in this line is
  unchanged by the fix (there are still eight banks) but what it certifies
  is not, so read the two sections together.
* **`tokens 6`**, each read out of `seq_unit`'s OUT FIFO and compared against
  the golden: `TOK[0] = 00a36 (2614) == golden OK` through
  `TOK[5] = 0000d (13) == golden OK`.

**Budget, for Task 14** (**M**, and the reason the brief asked for a
wall-clock per rung): Verilator sustains **20,603 cycles/s** on this
elaboration (200,098,192 / 9,712), so a full-model 9B replay is
**~2 h 45 min** and an emission is **~3 h** (§3.3).  **Fix round 1 measured
the parallel case too, and it is the one that matters for scheduling**: four
seeds cost **2 h 47 min total**, not four times that, and three emissions in
parallel cost **3 h 14 min** (§5.3.4).  The 2B W8 twin's
`W8_WD = 172,800,000` watchdog, which `W9_WD` matches, is 4.3e13 cycles —
documentation, not a live bound; bounded wall-clock polling is what actually
limits these runs.

#### 5.3.3 Fix round 1 — the OTHER half of the same geometry (finding I6)

§5.3.1 found that the checker could not HOLD kv banks 6 and 7.  The review
found the half that was invisible for the opposite reason: **the golden never
carried the columns.**  `tb/scripts/gen_seq_chip_vectors.py` wrote

```
    f.write(f"TCNT {s} {int(M.T[s][0])} {int(M.T[s][1])}\n")
```

so kvheads 2 and 3 were absent from the `.chip` at EVERY bank, at every
geometry, and `tb/tb_seq_chip.sv` held a pair of 1-D arrays that could not
have compared them if they had been there.  The `tcnt 8` in §5.3.2 counts
banks; **half of each bank was uncompared**, and the elaboration assert that
was supposed to catch exactly this pinned `$size(u_layer.tcnt_bank)` —
dimension one only.

Fixed in `86bc499` and `0ab38e3`:

* the golden line is `TCNT <slot> <NKVH counters>`, width taken from the
  model's own `M.T[s]`, so it follows any future NKVH by itself
  (`tb/scripts/gen_seq_chip_vectors.py:352-364`);
* `exp_tcnt` / `prev_tcnt` are `[TB_KV_NB][TB_KVH]` and the DUT mirror assert
  pins BOTH dimensions — `$size(u_layer.tcnt_bank[0])` as well
  (`tb/tb_seq_chip.sv:584-603`);
* the parser reads all `TB_KVH` columns and **REFUSES** a golden carrying
  fewer, rather than half-checking a stale build product
  (`tb/tb_seq_chip.sv:678-692`);
* both compares — end-of-launch and the carried-state one — iterate kvheads
  and name the head in the message.

**M**, the covering runs, all on ONE binary
(`built 2026-09-03T09:29:24-06:00`, quoted in each block's header):

| log | what | verdict |
|---|---|---|
| `evidence/qwen9b/g4/039_smoke_goldens_tcnt4.log` | the 8 smoke goldens regenerated | `BEFORE ... TCNT 0 2 2` -> `AFTER ... TCNT 0 2 2 2 2` on every one, each with its sha before and after |
| `evidence/qwen9b/g4/043_final_binary_regression.log` | the RED, then both smoke rungs | `G4A_RED_2COL_CHIP: REFUSED as intended (rc=134)`, `G4A_REPLAY lay9b_s: ALL PASS`, `G4A_REPLAY tok9b_s: ALL PASS` |

**The RED is the half that makes this a gate.**
`evidence/qwen9b/g4/run_g4a_red_2col_chip.sh` runs the same binary against a
STALE two-column golden — byte-for-byte what the generator wrote before
`86bc499` — with the stream, the const blob and all four weight regions
symlinked to the real `lay9b_s1`, so a refusal cannot be blamed on a missing
input:

```
regenerate the .chip golden: make -C tb seq_chip_vectors*
[108000] %Fatal: tb_seq_chip.sv:595: Assertion failed in
         TOP.tb_seq_chip.read_section.unnamedblk2:
         TCNT kv slot 0 carries fewer than 4 counters
```

**And that RED found a second defect**, recorded because it is the kind that
hides: the first run of it
(`evidence/qwen9b/g4/042_red_two_column_chip.log`) refused correctly and
printed a **200-digit decimal** instead of a message.  A
`{"...", "..."}` brace concatenation is not a format string — Verilator takes
it as a packed value, prints it, then appends the arguments raw.  Three sites
had it, and the first arrived with `5d884a0`, so none of the three had ever
fired.  A checker whose refusal cannot be read is half a checker; the long
half is now a `$display` and `$fatal` carries one literal.  042 is kept as the
RED that found it and 043 is the same RED, readable.

**The 0.8B and 2B families are NOT re-run** — the controller's ruling, and
the reason is that neither has a live gate to break: the 2B W8 smoke is
RETIRED at `tb/Makefile:1139` (G3.3: this bitstream has no W8 engine mode)
and G3.1 retired the v1.7 replays.  `tb/tb_seq_chip.sv` is shared by three
obj_dirs, but `obj_dir_tb_seq_chip_9b` is the only one this tree can run.

#### 5.3.4 Fix round 1 — the full model at FOUR SEEDS

§9.3 declared one prompt seed and gave the cost as the reason.  The
controller overruled it: the spec's 4-seed rule binds every TB run and the
brief's Step 3 says so for the chip replay, so the other three seeds were
emitted (3 h 14 min each, three in parallel,
`evidence/qwen9b/g4/030_emit_9b_s2.log` and its two siblings), gated
(§4.1a), and replayed.

**M**, `evidence/qwen9b/g4/051_full_model_4seeds.log`, `rc: 0`, last line
**`G4A_REPLAY model_9b_s: ALL PASS`** — ONE binary
(`built 2026-09-03T09:29:24-06:00`, the same one §5.3.3's smoke rungs and RED
used), four processes, launched together:

| seed | wall | cycles | tokens |
|---|---|---|---|
| `model_9b_s2` | **9,456 s** = 2 h 37 min | 200,098,897 | `[279, 264, 854, 11, 303, 264]` |
| `model_9b_s4` | **9,543 s** = 2 h 39 min | 200,098,216 | `[11, 0, 271, 803, 369, 498]` |
| `model_9b_s1` | **9,798 s** = 2 h 43 min | 200,098,192 | `[2614, 314, 279, 369, 11751, 13]` |
| `model_9b_s3` | **10,034 s** = 2 h 47 min | 200,098,831 | `[313, 430, 2510, 198, 1445, 27180]` |
| **all four, in parallel** | **10,034 s = 2 h 47 min 14 s** | | |

`TB_SEQ_CHIP PASS` on every one, each with `launches 1, scratch
36864/launch, tokens 6, tcnt 8`, `decerr 0 non-OK 0`, `ddr beats 544,80x
(miss 0)` and `weight beats 383606784 total across 4 chan (miss 0)`.  Every
one of the twenty-four tokens matched the golden the SEQ gate had already
produced for that seed — `TOK[0] = 00a36 (2614) == golden OK` and its
twenty-three siblings, in the per-seed logs under
`evidence/qwen9b/g4/seedlogs_model_9b_s/`.

**The four cycle counts differ by 705 out of 200 million — 3.5 ppm.**  That
is the prompt and nothing else: s1/s4 feed a three-token prompt and s2/s3 a
one-token prompt, so the prefill differs by a few hundred cycles while the
six decode steps are identical work.  It is also the strongest statement this
rung can make about seed independence — four different prompts, four
different token trajectories, four different goldens, and the engine does the
same work.

**The scaling number Task 14 should schedule with.**  Verilator sustained
**20,422 cycles/s per process with four running** (200,098,192 / 9,798),
against **20,603** for one alone in §5.3.2 — **0.9 % slower**.  Four 9B seeds
therefore cost the same wall clock as one, and the rung's budget is
**~2 h 50 min for a full 4-seed campaign**, not four times ~2 h 45 min.

**Memory, checked before the launch and measured throughout** — the ruling
asks for both.  **M**, `evidence/qwen9b/g4/053_memwatch_4seeds_r2.log`:

```
--- free -g at the start:  total 247  available 241
G4A_MEMWATCH: peak 4 process(es), total RSS 0.169 GiB,
              largest single 0.042 GiB, 82 sample(s)
--- free -g at the end:    total 247  available 232
```

**Four full-model 9B replays cost 169 MiB.**  `tb/seq_mem_file.sv` streams
the 3.9 GiB of weight images and the 1.9 GiB embedding table through
`$fseek` / `$fread` rather than loading them, so the constraint on this rung
is wall clock and DISK (four artifact sets are ~40 GiB), not RAM.  The
sampler's own first attempt is committed as the RED at
`evidence/qwen9b/g4/052_memwatch_4seeds.log`: it matched its pattern against
the whole command line and counted its own wrapper shells, reporting
`procs 7` for four simulations.

### 5.4 The envelope checks do NOT fire — the other half of G3.4's S9

G3.4 added the MVGO SHAPE `ng` envelope in three places and proved each one
REFUSES an out-of-envelope word.  **A guard that only ever refuses is
indistinguishable from a guard that always refuses.**  The complementary
half — that it ACCEPTS the real 9B shapes — can only be measured where a 9B
stream exists, and this is that place.

**The host half**, `evidence/qwen9b/g4/g4a_envelope.py`, over all NINE 9B
streams this task emitted — **M**, `evidence/qwen9b/g4/014_envelope_all.log`,
last line `G4A_ENVELOPE: PASS (0 problem(s))`:

| stream | records | MVGO | ng histogram | max |
|---|---|---|---|---|
| `lay9b_s1` .. `s4` | 4,027 | 152 | `32:136 96:16` | **96** |
| `tok9b_s1` .. `s4` | 2,139 | 80 | `32:72 96:8` | **96** |
| `model_9b_s1` | 158,483 | **5,480** | `32:4968 96:512` | **96** |

with, on every one:

```
  DECLARED  meta shape_isa = 2
  MAX       ng 96 of MAX_NG 96  — EXACTLY at the ceiling
  GREEN     the whole stream validates under its own declared layout — the envelope does NOT fire
  RED       rec 3717 forced to ng=97 -> REFUSED: MVGO SHAPE ng 97 outside the engine envelope 1..96
```

and the bound itself read out of all three sources and required equal:
`TIED MAX_NG rtl/matvec_engine.sv=96, ref/seq_format.py=96, sw/hwmap.py=96`.

The number that matters is the **maximum**: at 9B `mlp.down` has K = 12,288,
so `ng = K // 128 = 96`, which is **exactly `MAX_NG`**.  The envelope is
therefore exercised at its ceiling by this stream and not stepped around,
and it accepts.  The RED control in the same tool forces one MVGO to
`ng = 97` in a copy of the record list and requires the identical call to
refuse; without it the GREEN would prove only that the clause was skipped.

#### 5.4.1 The census — DNSB per body, and the 16-bit ARG in use

Two things the first cut of this gate never counted, both one more walk of
the stream the envelope tool already unpacks.  **M**,
`evidence/qwen9b/g4/035_envelope_all_clean.log` (the same run as above,
re-done on a clean tree — §9.7), on `model_9b_s1`:

```
  CENSUS    DNSB CSRWR 96 in the stream; steps 6, loop_steps 3 -> 4 body/bodies present, 24 per body
  CENSUS    ARG1 hi (as an addr pair)  n=35276   over 32767: 1440   max 48160
  CENSUS    ARG1 lo (as an addr pair)  n=35276   over 32767: 1408   max 36640
  CENSUS    ARG2 (as an ALU dst)       n=35276   over 32767: 1024   max 49184
  CENSUS    MOVX/MOVY addr_lo          n=9464    over 32767: 864    max 45088
```

* **DNSB: 24 per layer body**, which is one per DeltaNet layer at the 9B
  geometry (24 DN + 8 GQA).  The count is per BODY, not per step: a looped
  stream carries `steps - loop_steps + 1 = 4` bodies because the looped tail
  shares one, so 96 CSRWRs in the file.
* **The 16-bit ARG is in use, and the MOVX/MOVY row proves it on its own.**
  For those two opcodes `addr_lo` IS the scratch address, so **864 records
  above 32,767, reaching 45,088**, cannot be encoded by a SEQ_ISA v1.7 stream
  at all — v1.7 stopped at 32,767 and the 9B layer body peaks at 50,208
  (§2).  That is the whole reason this task exists, counted rather than
  argued.  The ARG1/ARG2 rows decode every layer ARG word as if it were an
  address pair or an ALU dst, which is what the address-carrying commands
  pack — so they are **upper bounds**, stated as such in the tool, and the
  MOVX/MOVY row is the one that stands alone.

**The RTL half is not in that tool and cannot be.**  It is
`TB_SEQ_CHIP PASS` on a run whose final `STATUS[31:24]` err_code is zero.
`tb/tb_seq_chip.sv` fatals on a non-zero err_code twice — while polling
(`SEQ err_code %02h at pc %0d`) and again on the final status (`err_code
%02h (STATUS %08h)`) — and the two codes the envelope reports through are
`E_ENV = 0x0D` (`rtl/seq_unit.sv` refusing the MVGO record before the
doorbell) and `E_LAYEROP = 0x10` (`layer_chan`'s `err_op`, which is how the
S9 command envelope reports).  **Every chip run in §5.1, §5.2 and §5.3 ends
in `TB_SEQ_CHIP PASS`**, so neither fired on any of them.

### 5.5 `tb_token` and `tb_chain`

The controller's ruling: re-base them on the 9B stream set if it is
mechanical, otherwise record them retired for good with the reason.
**Retired for good.**  The reasoning is written at the targets themselves,
in `tb/Makefile`'s stage-3/4 banner, so a reader who runs `make tb_chain`
finds it where they are looking; in summary:

* **`tb_token`** replays `tb/scripts/token_s*.txt`, which are COMMITTED
  pre-Phase-1A evidence.  `tb/Makefile`'s `layer_scripts token_scripts`
  target REFUSES to regenerate them ON PURPOSE.  Re-basing would mean
  overwriting committed evidence or inventing a new artifact family — and
  the new family already exists: `token24_scripts` / `tb_token24` drive the
  SAME generator (`ref/gen_token_script.py`), gitignored and regenerable at
  whatever `FABLE5_MODEL` selects.
* **`tb_chain`** replays `tb/scripts/chain_s*.txt`, which ARE regenerable
  (`chain_scripts`, gitignored), so re-basing it is mechanical in the
  Makefile sense — and that is exactly why the decision needs a reason
  rather than an excuse.  What it would buy is covered twice over at 9B
  already: the single-layer direct drive of `layer_chan` from a host BFM by
  `tb_layer_chan` on the `layerv2_s*` set (**T** — G3.4 ran it at
  `FABLE5_MODEL=9b`, 4 seeds, 1,438 commands / 261,357 checks bit-exact,
  `evidence/qwen9b/g3/G3_4_LAYER.md`), and the many-layers-in-sequence case
  by §5.3 below, which runs thirty-two real layers on real weights through
  `seq_unit` and the movers.

Neither target is deleted: both stay as the record of how stage 3/4 was
gated, and neither is claimed to pass.

---

## 6. Step 3′ — the `RS_F = 7` fidelity width: **NOT RUN, and here is why**

Step 3′ is AVAILABLE, NOT A GATE, and the controller's ruling bounds it:
run it only if it is a **warm-cache** re-run of the existing fidelity
harness costing under about an hour of snoke; otherwise state that the
adoption rests on the narrow sample.  Either way the doc says which.

**It says which: it was NOT run, because the cache is COLD, and that is a
measurement rather than an assumption.**

`ref/fidelity_check.py` keys its quantized-weight cache on, among other
things, a sha256 over `_WQ_SOURCES` (`ref/fidelity_check.py:146-148`) —
nine quantizer sources.  **M**, computed at this task's operating point on
the committed tree:

| | `src_sha256` |
|---|---|
| this tree | `6c1428471661cc5f2397adba81cbdb6bd1b81890dde8d40f01f598cb6b6d21b9` |
| `/var/tmp/fable5_wq/wq_layers_9b_68e6c1ff810ce389.pkl` (the pkl Task 5's §7 numbers were scored on) | `9689cce9ab7862b10bcc8ede8ddfe5d8132888f6db8f24c44cad6e5d7780aa28` |
| `/var/tmp/fable5_wq/wq_layers_9b_a38fc65e99d86157.pkl` | `04a4c9c6be1f1131cc4841ee0c0fb6992a865a207cd0fbdc2f7a0064aa306b5a` |

Neither cached digest is this tree's — Tasks 7-10 edited `layer_fixed.py`
and its siblings, which is exactly what the key is for — so a wider
fidelity run would pay the **full GPTQ pass, measured at 2 h 55 min by Task
5** (`evidence/qwen9b/g2/G2C_CHAIN.md` §4.2), which is roughly three times
the ruling's bound.  Nothing was relaxed to get under it: the cache is not
"probably stale", it is *measurably* not this tree's.

**So the reader is told the width plainly.**  `RS_F = 7` was adopted on
**98 of 108 top-1** — four prompts, 27 teacher-forced steps each — with
run-to-run spread measured at exactly zero and a byte-identical repeat
(Task 5 §7.2/§7.3).  **That is a strong number on a NARROW sample**, and
the adoption rests on it.  It is not a corpus-scale result and this gate
does not present it as one.

**And the corpus-scale version still does not exist in the form a reader
expects, for the reason the brief names**: `ref/perplexity_eval.py`
measures weight damage only, with float compute, and touches `RS_F` at
exactly one place — the int16 embedding-table round trip
(`ref/perplexity_eval.py:474`, documented at `ref/perplexity_eval.py:329`).
A PPL point at 7 would price the *embedding rounding*, not the residual
rail the adoption is about.  **None was run**, and none should be presented
as confirmation.

**What this gate DOES add to the RS_F = 7 evidence, and it is not nothing.**
Every rung below ran at `FABLE5_RS_F=7` end to end — the emitted artifact,
the reference executor, the `.chip` golden and the RTL — so `RS_F = 7` has
now been exercised **through the chain, on real weights, against the bf16
golden** (§7) rather than only inside `ref/layer_fixed.py`.  That widens the
*kind* of evidence, not its statistical width, and the two should not be
confused.

---

## 7. Step 4 — the torch-golden lockstep

The chip replay proves **RTL == `ref/seq_model.py`**.  The SEQ gate proves
**`ref/seq_model.py` == the `.txt` generator == `ref/layer_fixed.py`**.
Neither says anything about the MODEL.  This step closes that last link, and
`evidence/qwen9b/g4/g4a_torch_lockstep.py` puts the four token columns side
by side:

| column | what it is | where it comes from |
|---|---|---|
| **EMIT** | the generator's own `argmax per step`, free-running | the emit log |
| **CHIP** | `ref/seq_model.py`'s OUT FIFO after replaying the STREAM — and the RTL's answer too, because `tb_seq_chip` reads every one of these out of `seq_unit`'s FIFO and fatals on a mismatch | `<prefix>.chip`'s `TOK` lines |
| **FX** | `ref/layer_fixed.py` TEACHER-FORCED onto the golden sequence: a third implementation of the same fixed-point math, with no scratchpad model and no SEQ stream | Task 5 §7.3's RS_F=7 run, `evidence/qwen9b/g2/g2c_fixed_9b_w4g128gptq_int16_rsf7_g2c.json` |
| **GOLD** | **the bf16 checkpoint through `transformers`**, upcast to float32 | the same file's `golden_argmax` |

EMIT / CHIP / FX are the same arithmetic and must agree exactly.  GOLD need
not: that difference IS the quantization, and Task 5 priced it at 98/108
top-1 over four prompts.  **On prompt 1 — the one this artifact set is
emitted for — Task 5 measured 27/27 with rank max 0**, so on this prompt the
fixed-point pipeline and the bf16 model are expected to agree on every step,
and the comparison below has no slack to hide in.

**M**, `evidence/qwen9b/g4/017_torch_lockstep.log`, last line
`G4A_TORCH_LOCKSTEP: PASS (0 problem(s))`:

```
  fidelity top1 27/27, rank max 0

  step | EMIT   CHIP   FX     GOLD   | fx==chip  gold==chip
     0 | 2614   2614   2614   2614   | YES       YES
     1 | 314    314    314    314    | YES       YES
     2 | 279    279    279    279    | YES       YES
     3 | 369    369    369    369    | YES       YES
     4 | 11751  11751  11751  11751  | YES       YES
     5 | 13     13     13     13     | YES       YES

  EMIT == CHIP  : IDENTICAL (6 steps)
  FX   == CHIP  : 6/6
  GOLD == CHIP  : 6/6   <-- the quantization error, reported not asserted
  generated     : [369, 11751, 13]
  free_gen[:3]  : [369, 11751, 13]   IDENTICAL
```

**Four independent implementations, six steps, no disagreement anywhere** —
including against the bf16 checkpoint.  `free_gen` is the fidelity harness's
own free-running pass and it produces the identical three generated tokens,
which decode (Task 5 §7's `free_text`) to **`" is Paris."`** for
*"The capital of France"*.

**Two things this does NOT say, and they matter:**

1. **`GOLD == CHIP : 6/6` is not a fidelity result, it is one prompt.**  The
   campaign's fidelity number is **98/108 over four prompts**, and on THIS
   prompt Task 5 measured 27/27 — so 6/6 here is the expected outcome, not
   new information about the quantizer.  What it IS is a check that nothing
   in the emitter, the executor, the weight pack or the RTL moved the answer
   away from what the reference model already scored.
2. **The CHIP column becomes the RTL column only because §5.3's replay is
   green.**  `<prefix>.chip`'s `TOK` lines are `ref/seq_model.py`'s OUT
   FIFO; `tb_seq_chip` reads each one out of `seq_unit`'s FIFO and fatals on
   a mismatch, so `TB_SEQ_CHIP PASS` is what makes the column silicon-shaped
   rather than model-shaped.

---

## 8. Gates

Every row is a committed log under `evidence/qwen9b/g4/`, and the verdict
column quotes that log's ACTUAL last verdict line.

| # | log | what | verdict (the log's own last verdict line) |
|---|---|---|---|
| 001 | `001_scratch_probe_9b.log` | the scratch high-water probe, 4 seeds — FIRST run, header says `1c62570+dirty` | `[9b] OK: measured <= derived <= 65536`, `rc: 0` |
| 002 | `002_scratch_probe_9b_committed.log` | the same probe on the committed tree `0cf5f9c`, + the driver appendix | `MEASURED PEAK=50208  DERIVED PEAK=50208  SCRATCH=65536  headroom=15328`, `rc: 0` |
| 003 | `003_emit_9b_s1.log` | the 9B emission, 3 h 00 min | `SEQ: 158483 records (2535728 B) + 2136576 B const blob`, `rc: 2` — the RANGE AUDIT, §3.4 |
| 004 | `004_smoke_scripts_build.log` | RED: `gen_token_script` refusing an `rs_f`-less manifest at RS_F=7 | `rc: 2` |
| 005 | `005_chip9b_build.log` | `tb_seq_chip_9b` built into `obj_dir_tb_seq_chip_9b` (-GNMV=4 -GWIMGPC=1) | `rc: 0` |
| 006 | `006_tok_smoke_scripts.log` | the token smoke set, 4 seeds, after the `rs_f` fix | `rc: 0` |
| 007 | `007_smokeA_layer_replay.log` | RED: the runner launching the binary from the repo root, ROMs not loaded | `G4A_REPLAY lay9b_s: FAIL`, `rc: 1` |
| 008 | `008_smokeA_layer_replay.log` | rung A — the layer smoke, 4 seeds | **`G4A_REPLAY lay9b_s: ALL PASS`**, `rc: 0` |
| 009 | `009_smokeB_token_replay.log` | rung B — the token loop, 4 seeds | **`G4A_REPLAY tok9b_s: ALL PASS`**, `rc: 0` |
| 010 | `010_seqgate_smokes.log` | the SEQ gate over the eight smoke artifacts | **`G4A_SEQGATE: ALL PASS (8 artifact(s))`**, `rc: 0` |
| 011 | `011_chip_vectors_9b.log` | the `.chip` golden + four per-channel weight regions | `.chip: 158483 records, pc 158482, 6 tokens`, `rc: 0` |
| 012 | `012_seqgate_model.log` | the SEQ gate on the FULL model | **`G4A_SEQGATE: ALL PASS (1 artifact(s))`**, `rc: 0` |
| 013 | `013_inventory_9b.log` | the artifact inventory, the fit, and the nch=1 refusal | **`G4A_INVENTORY: PASS (0 problem(s))`**, `rc: 0` |
| 014 | `014_envelope_all.log` | the S9 envelope over all nine 9B streams, with the RED control | **`G4A_ENVELOPE: PASS (0 problem(s))`**, `rc: 0` |
| 015 | `015_shape_isa_paths.log` | `evidence/qwen9b/g3/g34_shape_isa_paths.py` re-run unmodified | **`SHAPE_ISA_PATHS: PASS (0 problem(s))`**, `GAP 9 of 22`, `rc: 0` |
| 016 | `016_full_model_replay.log` | **rung C, first run — the RED**: the TB's TCNT golden holder, §5.3.1 | `G4A_REPLAY model_9b_s1: FAIL`, `rc: 1` (the sim itself aborted, `rc=134`) |
| 017 | `017_torch_lockstep.log` | the four token columns against the bf16 golden | **`G4A_TORCH_LOCKSTEP: PASS (0 problem(s))`**, `rc: 0` |
| 018 | `018_cite_drift_fix.log` | the citation `--fix` pass | `O3_CITE_DRIFT FIX APPLIED`, `rc: 0` |
| 019 | `019_cite_drift_verify.log` | `--verify` | **`O3_CITE_DRIFT VERIFY PASS (0 problem(s))`**, `rc: 0` |
| 020 | `020_cite_drift_residue.log` | the hand-repair residue, enumerated (§12) | `CHECK FAIL (10 drifted, 1 unresolved)`, `rc: 1` — expected |
| 021 | `021_rebuild_and_smoke_regression.log` | the TCNT fix regression-tested over both smoke rungs, 8 seeds | **`G4A_REPLAY lay9b_s: ALL PASS`** + **`G4A_REPLAY tok9b_s: ALL PASS`**, `rc: 0` |
| 022 | `022_full_model_replay_r2.log` | **rung C — the whole 9B model on the RTL** | **`G4A_REPLAY model_9b_s1: ALL PASS`**, `rc: 0` |
| 023 | `023_spec_cites_gatedoc.log` | `spec_cites.py` over this document AND the design spec | **`SPEC CITES: PASS`**, `FAIL 0`, `rc: 0` |
| 024 | `024_spec_cites_final.log` | the same, re-run after §12's last edit | **`SPEC CITES: PASS`**, `FAIL 0`, `rc: 0` |

**Fix round 1** (the review of `1c62570..5d884a0`; every row below is a log
added by that round, same directory, same wrapper):

| # | log | what | verdict (the log's own last verdict line) |
|---|---|---|---|
| 031 | `031_bytelock_08b.log` | I2 — the 0.8B half of the byte-lock, `cmp`ed against the pre-change emitter at `1c62570` | **`G4A_BYTELOCK_08B: PASS`**, `rc: 0` |
| 032 | `032_cite_drift_tbchip_fix.log` | I3 — the `--fix` pass with `tb/tb_seq_chip.sv` in the `--edited` set | `O3_CITE_DRIFT FIX APPLIED`, **`FIXED 6 citation(s) in 3 document(s)`**, `rc: 0` |
| 033 | `033_cite_drift_tbchip_verify.log` | `--verify` at the same base | **`O3_CITE_DRIFT VERIFY PASS (0 problem(s))`**, `rc: 0` |
| 034 | `034_inventory_9b_clean.log` | I4 + I5 — the inventory on a CLEAN tree, image pin over CONTENT | **`G4A_INVENTORY: PASS (0 problem(s))`**, `rc: 0` |
| 035 | `035_envelope_all_clean.log` | I5 + the census — nine streams on a CLEAN tree | **`G4A_ENVELOPE: PASS (0 problem(s))`**, `rc: 0` |
| 036 | `036_shape_isa_paths_clean.log` | I5 — the paths tool on a CLEAN tree | **`SHAPE_ISA_PATHS: PASS (0 problem(s))`**, `GAP 9 of 22`, `rc: 0` |
| 037 | `037_rebuild_chip9b_i6.log` | the binary rebuilt with I6's checker | `rc: 0` |
| 038 | `038_lint_seq_chip_9b.log` | the `-Wall` lint §5.3.1 claimed without a log | `rc: 0`, zero `%Warning` / `%Error` |
| 039 | `039_smoke_goldens_tcnt4.log` | I6 — the eight smoke goldens regenerated, sha before and after each | `SMOKE GOLDENS REGENERATED: 8`, `rc: 0` |
| 040 | `040_smokeA_layer_replay_i6.log` | rung A on the I6 binary, 4 seeds | **`G4A_REPLAY lay9b_s: ALL PASS`**, `rc: 0` |
| 041 | `041_smokeB_token_replay_i6.log` | rung B on the I6 binary, 4 seeds | **`G4A_REPLAY tok9b_s: ALL PASS`**, `rc: 0` |
| 042 | `042_red_two_column_chip.log` | **RED** — a stale two-column golden refused, with the unreadable message it exposed | `G4A_RED_2COL_CHIP: REFUSED as intended (rc=134)`, `rc: 0` |
| 043 | `043_final_binary_regression.log` | the FINAL binary: one build, then the RED and both smoke rungs, 8 seeds | **`G4A_REPLAY lay9b_s: ALL PASS`** + **`G4A_REPLAY tok9b_s: ALL PASS`**, `rc: 0` |
| 044 | `044_tok_smoke_scripts_clean.log` | I5 — the token smoke set re-emitted on a CLEAN tree, sha before and after | four artifacts x three files, every `BEFORE` sha equal to its `AFTER`, `rc: 0` |
| 030 | `030_emit_9b_s2.log` `030_emit_9b_s3.log` `030_emit_9b_s4.log` | the other three 9B emissions, in parallel | `SEQ: 81092 / 81092 / 158483 records`, `rc: 2` — the RANGE AUDIT, as on seed 1 |
| 045 | `045_chip_vectors_9b_s1to4.log` | the four model `.chip` goldens regenerated with the widened TCNT line | `SEED 1 rc=0 wall=902s` .. `SEED 3 rc=0 wall=927s`, `rc: 0` |
| 046 | `046_cite_drift_tbchip_r2_fix.log` | the THIRD `--fix` pass, at base `af2f762` (§12) | `O3_CITE_DRIFT FIX APPLIED`, **`FIXED 6 citation(s) in 3 document(s)`**, `rc: 0` |
| 047 | `047_cite_drift_tbchip_r2_verify.log` | `--verify` at that base | **`O3_CITE_DRIFT VERIFY PASS (0 problem(s))`**, `rc: 0` |
| 048 | `048_model_goldens_tcnt4.log` | what 045 produced: sha, all eight TCNT lines, `BASES`, `EMBLOG2`, per seed | `TCNT 0 6 6 6 6` .. `TCNT 7 6 6 6 6` on all four, `rc: 0` |
| 049 | `049_seqgate_model_s1to4.log` | Step 2 on the model, seeds 1-3 — **TRUNCATED**, see §9.8 | 3 x **`SEQ GATE: PASS`**, `CHECKPT 2358/2358 ALL BIT-EXACT`; no `rc` line |
| 050 | `050_seqgate_model_s4.log` | Step 2 on seed 4, re-run detached | **`G4A_SEQGATE: ALL PASS (1 artifact(s))`**, `rc: 0` |
| 052 | `052_memwatch_4seeds.log` | **RED**: the first memory sampler, which counted its own wrapper shells | `procs 7` for four simulations; replaced by 053 |
| 051 | `051_full_model_4seeds.log` | **the WHOLE 9B model at four seeds**, one binary, four processes in parallel | **`G4A_REPLAY model_9b_s: ALL PASS`**, `--- total wall 10034s`, `rc: 0` |
| 053 | `053_memwatch_4seeds_r2.log` | the memory record beside 051 | **`G4A_MEMWATCH: peak 4 process(es), total RSS 0.169 GiB, largest single 0.042 GiB, 82 sample(s)`**, `rc: 0` |
| 054 | `054_spec_cites_round1_final.log` | `spec_cites.py` over this document AND the design spec, last, on the committed tree `98fd606` | **`SPEC CITES: PASS`**, `FAIL 0`, `rc: 0` |

Every log above whose header does NOT say `+dirty` was run on a committed
tree, which is the convention; the **thirteen** that do are declared one by
one in §9.7, and `049`'s truncation in §9.8.  *(Recounted 2026-09-10: this
sentence said ten, and §9.7's own table already listed twelve.)*

### 8.1 The negative controls — every green half has a red one

A guard that only ever passes and a guard that only ever refuses are both
untrustworthy.  Each of this gate's checks carries its opposite:

| green | its red |
|---|---|
| the S9 envelope ACCEPTS ng=96 on all nine streams (014) | the same call, on the same records with one MVGO forced to `ng = 97`, REFUSES — printed beside every green |
| `MEASURED <= DERIVED` in the probe (002) | the probe's asserts are live: `measured {p} EXCEEDS derived PEAK` and `derived PEAK exceeds the 65536-word budget` |
| the nch=4 repack FITS at 76.5 % (013) | the SAME manifest at nch=1 REFUSES, naming the address it reaches and `EMB_BASE` |
| `plan_weights` reproduces all 249 bases (013, 011) | the tool raises `the re-derived weight plan disagrees with the stream's on wid(s) ...`; it fired for real during development, on the nch>1 non-repacked case |
| `TB_SEQ_CHIP PASS` (008, 009, 022 — **022, not 016; 016 is the RED**) | 007 is a real failing run of the same rung, and the runner now fails on `$readmem file not found` as well as on a missing PASS line |
| the `.chip` TCNT golden carries all four kvheads and all four are compared (039, 043) | `run_g4a_red_2col_chip.sh` feeds the same binary a STALE two-column golden and requires a refusal — `G4A_RED_2COL_CHIP: REFUSED as intended (rc=134)`, §5.3.3 |
| the image pin changes when image BYTES change (034) | the retired `name:size` digest did not, which is finding I4 and why the pin moved |
| the `rs_f` manifest key (013) | 004 is `dump_weights` REFUSING to write the manifest without it at RS_F=7 |
| `O3_CITE_DRIFT VERIFY PASS` (019) | `--plan` REFUSED the first pass as UNSAFE (§12), and 020 is the residue reported rather than suppressed |

---

## 9. Deviations declared

1. **The commit block gained files the brief's block does not name.**  The
   brief names `tb/Makefile`, `tb/scripts/gen_seq_chip_vectors.py` and this
   document.  Also committed:

   | file | why it had to move |
   |---|---|
   | `ref/seq_format.py` | the dispatch context's hand-on items 1 and 2 — the emitter must WRITE `shape_isa` and must STATE it to its own `validate_stream`.  There is no other place either can go |
   | `ref/seq_model.py` | **the 9B stream did not run without it.**  `_csrwr` had no case for `LOFF_TCNT2` (0x60, added by G3.4) and modelled a TCNT write as `T[slot] = [0, 0]`, which truncates the kv bank at NKVH = 4.  §4.0 has the measurement |
   | `.gitignore` | `tb/scripts/w9/` is ~10 GiB of regenerable artifacts, exactly as `w3/`, `w4/` and `w5/` are |
   | `evidence/qwen9b/g4/*` | the logs, the two evidence tools and this document |

2. **The 9B stream set is `.e4` only; there is no `.e`.**  The brief's
   interface line says "`<prefix>.txt` / `.e` / `.e4` 9B streams".  A
   1-channel 9B stream cannot be emitted at all — §3.1 has the refusal,
   measured on the real manifest — so the set is `.txt` + `.e4`, and the
   `.e` half of that line is answered by the refusal rather than by a file.

3. ~~**The full-model replay is ONE prompt seed, not four.**~~
   **RETIRED IN FIX ROUND 1 — the deviation no longer exists.**  The
   controller's ruling: the spec's 4-seed rule binds every TB run and the
   brief's Step 3 says so for the chip replay; the 2B precedent
   (`W8_SEED = 1` on `w8_2b_model_script`) predates this plan.  The other
   three seeds were emitted, gated and replayed — §4.1a and §5.3.4 — and
   the cost estimate the deviation rested on was wrong in the direction that
   mattered: three emissions in parallel cost **3 h 14 min**, not three times
   3 h, and four replays in parallel cost **2 h 47 min**, not four times
   2 h 45 min.  The rule was cheaper to honour than to argue with.

4. **`--allow-clip` was NOT passed to the emit**, unlike the 0.8B and 2B
   recipes.  That is deliberate: whether the S_F = 13 DeltaNet-state soak
   saturates at 9B is a MEASUREMENT this gate makes (Task 5 handed it on as
   unmeasured), and `ref/seq_format._finalize` is an `atexit` hook, so the
   artifacts are written on both paths.  §3.3 records the audit's verdict
   and the non-zero rc it costs.

5. **Step 3′ was not run.**  §6, with the cache-key measurement that makes
   it a bounded decision rather than a shrug.

6. **`tb_token` and `tb_chain` are retired for good, not re-based.**  The
   controller's ruling allowed either; §5.5 and the banner in `tb/Makefile`
   carry the reason and the evidence for the superseding coverage.

7. **Thirteen of this gate's logs carry `tree: <sha>+dirty`**, against the
   campaign's own convention that a final log must not — ten of the first 24
   (`001`, `005`, `006`, `011`, `012`, `013`, `014`, `015`, `019`, `020`),
   plus `033`, `047` and `053`.  Declared here in
   full, one line each, because a `+dirty` header with no explanation is a
   log a reader cannot use.  *(Recounted 2026-09-10: the heading said "Ten
   of the first 24" while the table below it already covered twelve, and
   `053` was in neither.)*

   | log | disposition |
   |---|---|
   | `001` | already declared: the probe driver was a scratch file, appended verbatim to `002` and deleted (§2).  `002` is the clean re-run and is the log this gate cites |
   | `005` | the `tb_seq_chip_9b` build — **superseded** by `evidence/qwen9b/g4/037_rebuild_chip9b_i6.log`, `rc: 0`, `tree: af2f762`-era clean, and again inside `043` |
   | `006` | the token smoke emit — **superseded** by `evidence/qwen9b/g4/044_tok_smoke_scripts_clean.log`, and the supersession is a MEASUREMENT: the four artifacts re-emit **byte-identical** on a clean tree — the stream, its json and the (now four-column) chip golden alike |
   | `011` | the model `.chip` golden + weight regions — **superseded** by the round-1 regeneration the widened TCNT line forced (§5.3.3, §5.3.4) |
   | `012` | the model SEQ gate — **superseded** by the round-1 re-run over all four seeds (§5.3.4) |
   | `013` `014` `015` | **re-run clean**: `034_inventory_9b_clean.log`, `035_envelope_all_clean.log`, `036_shape_isa_paths_clean.log`, all `tree: ad1331b`, all PASS |
   | `019` `020` `033` `047` | **unavoidable, and not a defect**: a citation `--fix` pass MODIFIES tracked documents, and `--verify` / the residue check must then measure that same tree.  Committing first would be committing an unverified fix |
   | `053` | the memory record beside `051`, started three minutes after it, on `3389665+dirty` where `051` itself is clean at `6cad40f`.  It measures **RSS over time**, not a result: no number in this gate depends on the tree it ran against.  Named here for completeness rather than explained — what was uncommitted at that moment is not recoverable from the repository either |

   **What was uncommitted at `005`/`006`/`011`/`012` is not recoverable from
   the repository** — git keeps no record of a working tree that was never
   committed — so those four are replaced rather than described.  Guessing
   would be worse than either.

8. **`049_seqgate_model_s1to4.log` is TRUNCATED, and is committed that way.**
   The ssh session carrying it was killed by the agent harness while
   `model_9b_s4` was running, so the log ends after that banner with no
   `G4A_SEQGATE` line and no `=== rc:`.  The three gates it finished are real
   and §4.1a quotes them; seed 4 was re-run alone as
   `evidence/qwen9b/g4/050_seqgate_model_s4.log`, detached under `nohup` so a
   dropped session could not take it down again — as the 4-seed campaign and
   its sampler were then also launched.  **The log is not re-run for
   cosmetics**: a truncated log that says why it is truncated is worth more
   than a tidy one, and this document's whole subject is that a number must
   trace to what a log actually says.

---

## 10. NOT ESTABLISHED by this gate

1. **No silicon has run a 9B stream.**  This is simulation and host
   arithmetic.  `evidence/qwen9b/g3/G3_1_ISA.md` §(the v2.0 consequence) is
   still true — the 0.8B and 2B geometries are served by their frozen
   pre-G3 bitstreams — and no 9B bitstream exists.  Task 14 is the netlist
   and Task 15 the board.
2. **No synthesis, no placement, no routing, no timing.**  The 928-URAM
   question the feasibility study raised is untouched here.
3. **FOUR prompt seeds at the full-model rung** (§5.3.4, fix round 1 — this
   entry said ONE before that round).  What four seeds still cannot see: a
   behaviour that needs a prompt outside the four this generator's seeds
   produce, a longer context than six steps, or anything the `expect_tokens`
   golden itself gets wrong — the chip is compared against the reference, and
   §7 anchors the reference to bf16 for seed 1 only.  What the four DO cover
   that one did not: four distinct prompts, four distinct token
   trajectories, and prefills of both lengths the emitter produces
   (`loop_steps` 3 and 5).
4. **`RS_F = 7` is still adopted on 98/108** (§6).  This gate exercises it
   end to end; it does not widen the sample.
5. **The runtime range audit is measured for THIS prompt only.**  It is a
   measurement over the activations one prompt produces.
6. **`ref/scripts/regen_gate.sh` and `evidence/qwen2b/rc/t3_locks.sh` were
   NOT run.**  Both compare a re-emitted 0.8B artifact against the frozen
   v1.7 gold, and G3.1 SPENT that byte-lock — this tree emits SEQ_ISA v2.0
   and the gold is v1.7, so both must now fail and that is the recorded
   intent (`ref/gen_layer_script.py`'s `BYTELOCKED_TAGS` comment, and
   `evidence/qwen9b/g3/G3_1_ISA.md` on `t4_bytes_unmoved.sh`).  **What this
   gate does instead** is the narrower thing that is still true and still
   worth having: the `shape_isa` key is WITHHELD at `0.8b`/`2b`, measured
   (§3.2), so the byte-lock those gates protect is not moved any FURTHER by
   this task.

---

## 11. Handoffs

**To Task 14 (netlist confidence) and Task 15 (upload):**

1. **The 9B stream set is `<prefix>.txt` + `<prefix>.e4.{seq,seqdata.bin,seq.json}`
   + 249 `<prefix>_w*.bin` + `<prefix>.weights.json` + `<prefix>.emb.bin`,
   under `tb/scripts/w9/`, NOT committed** (`.gitignore`, exactly as `w3/`,
   `w4/` and `w5/` are).  §3.3 carries the sha256 of every small file and
   the sizes of the large ones; `make -C tb w9_9b_model_script
   MODELPY=/home/cah/.venv/bin/python` regenerates it, and §3.3 records what
   that costs.  **There are FOUR such sets since fix round 1**, one per seed,
   ~10 GiB each (`W9_SEED=<n> W9_BASE=scripts/w9/model_9b_s<n>`); §5.3.4 has
   the parallel cost of building and replaying them all.
2. **`emb_row_bytes` is 8,192 and `EMBLOG2` is therefore 13 — exactly
   `SEQ_EMBLOG2_MAX`, with zero headroom** (**T**, Task 5 §5.2a; **M** here,
   in the `.chip` golden's own `EMBLOG2` line).  `rtl/seq_unit.sv`'s
   `EMBLOG2_RST` is 13 since G3.4, so a host that never programs the CSR is
   now right by default at 9B — but a host that programs it from a 0.8B/2B
   manifest and then runs a 9B stream is wrong, and nothing in the artifact
   stops that.
3. **`tb/seq_mem_file.sv` reads its file offsets through a 32-bit `int`**
   (`sz = $ftell(fd)` with `int sz`, and `$fseek(fd, int'(a - base), 0)`),
   and the 9B embedding table is **2,034,237,440 B = 94.7 % of the 2^31
   signed-int range**, leaving 113,246,208 B (108.0 MiB) of margin.  It
   FITS, and this gate's runs prove it does.  But the failure past that
   point is SILENT — a negative `$fseek` offset returns non-zero and
   `mem_rd` ignores the return — so any geometry with a bigger table (a
   larger vocab, or H beyond 4096) must widen those to `longint` first.
   **Recorded, not fixed**: the fix is outside this task and nothing in the
   9B chain needs it.

4. **The gate-port clamp is priced and someone must decide about it before
   the board.**  §0's verdict and §3.4 carry the measurement: **61 (layer,
   head) pairs clamp**, worst `|decay_clamp - decay_spec| = 22430/32768 =
   68.45 % FS` at L12h18, from
   `evidence/qwen9b/g4/003_emit_9b_s1.log:71-132` (61 `worst |decay_clamp`
   lines, 61 distinct `L<n>h<m>` labels).  That is
   `ref/layer_fixed.py`'s `quant_deltanet` saturating `dt_bias` / `A` where
   the `rtl/gate_unit.sv` ports as built would WRAP — documented in
   `ref/gen_model_script.py`'s header as future work needing new ROM hex, and
   9B exercises far more of it than 0.8B did.  §7's torch comparison shows
   THIS prompt's six tokens are unaffected, which bounds the risk without
   removing it.  **The decision package is routed to Task 12's Step 2** by
   the controller; Tasks 14 and 15 should read the answer there rather than
   re-deriving it, and this gate does not make it.

**To whoever next widens the `RS_F = 7` evidence:** §6 has the cache-key
measurement.  The cheap path no longer exists — the wq cache under
`/var/tmp/fable5_wq` is keyed to sources Tasks 7-10 have since edited — so
budget the full GPTQ pass (2 h 55 min measured) before planning a wider run.

**To a reviewer of `evidence/qwen9b/g3/g34_shape_isa_paths.py`:** its GAP
line now reads a different count (§3.2), and the parenthetical it carries —
*"no emitter writes it yet — Task 11"* — is stale prose in committed
evidence as of this gate.  It is **left alone** (the campaign does not edit
committed evidence in place) and named here so nobody reads the
parenthetical as current.

---

## 12. Citation drift

**TWO BASES, THREE PASSES — and the first two are at `1c62570`.**  (This
section opened *"ONE BASE for the whole task"* until 2026-09-10; its own
body below records the third pass at `af2f762`, and the accounting sentence
at the end of the section is the one that was right.)  The `--edited` set of
the first pass is the **six**
source files this task moved lines in — `ref/seq_format.py`,
`ref/seq_model.py`, `ref/gen_token_script.py`, `tb/Makefile`,
`tb/scripts/gen_seq_chip_vectors.py` and **`tb/tb_seq_chip.sv`** — plus
`.gitignore`, which names no citer (`--exclude-control` confirms that a path
with no citer changes nothing in the plan).  118 distinct (file, line) pairs
across the tree cite into that set; 87 did not move.

**`tb/tb_seq_chip.sv` needed a SECOND pass, and the first cut of this section
said five files.**  `7399dd9` (+42/−5, the TCNT holder fix of §5.3.1) landed
AFTER the `--fix` of `77b9ac8`, so everything past line ~450 in that file had
shifted by +37 and six citations pointed at the wrong lines —
`docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md:2090` and
`docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md:2613`, `docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md:1470-1471`
and `evidence/qwen2b/rc/t4_wall2_probe.py:6`.  The tool's refusal guard is
per (base, `--edited` set) and this file had never been in one, so it did
NOT refuse: `--plan` came back `SAFE` (8 repairs, 0 collateral) and the pass
ran at the same base `1c62570`.

| log | last line |
|---|---|
| `032_cite_drift_tbchip_fix.log` | `O3_CITE_DRIFT FIX APPLIED` — **`FIXED 6 citation(s) in 3 document(s)`** |
| `033_cite_drift_tbchip_verify.log` | **`O3_CITE_DRIFT VERIFY PASS (0 problem(s))`** — 6 relocated, and the five files of the first pass re-verify clean at the same base |

**And a THIRD pass, because this round did it to itself.**  `0ab38e3` — the
`$fatal` message fix of §5.3.3 — moved lines in the same file again, restaling
the same six citations by +7.  Leaving that would have reproduced I3 one round
later.  The tool's guard is per (base, `--edited` set) and `1c62570` +
`tb/tb_seq_chip.sv` was spent by `3671c79`, so this pass runs at **`af2f762`**,
the commit immediately before `0ab38e3`, where the documents already carry the
second pass's coordinates:

```
--plan  O3_FIX_PLAN: SAFE — every rewrite repairs a citation --verify reports stale
        REPAIR 8  COLLATERAL 0
046     O3_CITE_DRIFT FIX APPLIED — FIXED 6 citation(s) in 3 document(s)
047     O3_CITE_DRIFT VERIFY PASS (0 problem(s))
```

| old | new | what the new coordinate names |
|---|---|---|
| `tb/tb_seq_chip.sv:700-702` | `tb/tb_seq_chip.sv:707-709` | the MEM parse guard |
| `tb/tb_seq_chip.sv:1032` | `tb/tb_seq_chip.sv:1039` | the derived slice |
| `tb/tb_seq_chip.sv:988` | `tb/tb_seq_chip.sv:995` | the banked-layer-state banner |

So the accounting is **one base per pass, three passes**: `77b9ac8` over five
files at `1c62570`, `3671c79` over the sixth at `1c62570`, and `5ff34d2` over
the sixth again at `af2f762`.  Each is named with its base and its edited set,
which is what the campaign's addendum asked for after Task 10 ended with three
unlabelled base sets.

**What `--check` at `1c62570` still reports, and why it is not a regression.**
Re-running `--check` over all six files at the ORIGINAL base still says
`CHECK FAIL (36 drifted, 1 unresolved)`.  That is the tool working as
designed: the cite sweep is taken from the DOC BASE, so at `1c62570` it reads
the documents as they were BEFORE any repair and re-derives every fix as a
fresh drift.  `020` records the same thing for the first pass and this gate
called it expected there too.  The meaningful statements are the **three**
`--verify` runs — `019` and `033` at base `1c62570`, `047` at base
`af2f762` — and all three PASS.  *(Restated 2026-09-10: this read "the two
`--verify` runs, one per base".)*

**`--plan` before `--fix`, and the first plan REFUSED.**

```
O3_FIX_PLAN: UNSAFE — 2 of 29 rewrites would move a citation that is
already correct; repair the 27 stale one(s) BY HAND or --exclude the document
    collateral  ref/seq_model.py:616-765 -> ref/seq_model.py:616-783
```

Both collateral hits are the same citation, and it is **deliberately
historical**: the spec's D-CITE row says *"`sw/chat_seq.py:1769-1770` cites
`ref/seq_model.py:616-765` for a dispatcher now at ..."* and
`sw/chat_seq.py:1876` says *"The old docstring cited
`ref/seq_model.py:616-765`"*.  Renumbering those would destroy the record
they exist to keep.  So both documents were **excluded**, the plan re-run —
`O3_FIX_PLAN: SAFE — every rewrite repairs a citation --verify reports
stale`, 21 repairs, 0 collateral — and the pass applied.

| log | last line |
|---|---|
| `018_cite_drift_fix.log` | `O3_CITE_DRIFT FIX APPLIED — now run --verify` (**FIXED 30 citation(s) in 9 document(s)**) |
| `019_cite_drift_verify.log` | **`O3_CITE_DRIFT VERIFY PASS (0 problem(s))`** — 30 relocated citations checked against the base content and the citing documents |
| `020_cite_drift_residue.log` | `O3_CITE_DRIFT CHECK FAIL (10 drifted, 1 unresolved, ...)` — the residue, enumerated below |

**The `--exclude` list, in full, with a reason each:**

| excluded | why |
|---|---|
| `evidence/qwen9b/g4/G4A_REPLAY.md` | this document, written in post-fix coordinates (the standing rule) |
| `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md` | carries the historical `ref/seq_model.py:616-765` the plan flagged as collateral; **hand-repaired instead**, below |
| `sw/chat_seq.py` | the same historical citation, and NOTHING ELSE in it drifted (0 REPAIR, 1 COLLATERAL) — so excluding it costs nothing |

**The eleven hand repairs, enumerated — the `--exclude` list did NOT grow to
hide them.**  The tool sweeps citations from the DOC BASE, so a hand repair
is invisible to it and `020` still reports every one at its old coordinate.
That is "the checker's asymptote" (`evidence/qwen9b/g3/G3_4_LAYER.md`
§17.4), not a miss.  Each new coordinate was read back out of the file to
confirm it names the same source line:

| old | new | the source line the new coordinate names |
|---|---|---|
| ref/seq_model.py:756 | `ref/seq_model.py:774` | the `_layer_cmd` def |
| ref/seq_model.py:764-825 | `ref/seq_model.py:782-861` | the op-1 VN case through the unknown-opcode raise |
| ref/seq_model.py:795-796 | `ref/seq_model.py:813-814` | the dec_a1_lo / dec_a1_hi pair |
| ref/seq_model.py:816-817 | `ref/seq_model.py:834-835` | the KVAP call and its kvhead argument |
| ref/seq_model.py:756-893 | `ref/seq_model.py:774-911` | the "now at" half of the D-CITE row |
| tb/scripts/gen_seq_chip_vectors.py:255 | `tb/scripts/gen_seq_chip_vectors.py:325` | the R-c wall-8 EMB-stride comment |
| tb/scripts/gen_seq_chip_vectors.py:93 | **UNRESOLVED — kept** | §15.5 treatment: the base number and its quotation stay, with a dated note saying what G4a did |

**`spec_cites.py` on the design spec, after the hand repairs:**
`checked: 707 exist, 484 range, 21 quote | pending 0 | retired 15 |
noquote 94 | FAIL 0`, **`SPEC CITES: PASS`**.  Two failures were introduced
BY the note and fixed before that run: a bare 303 continuation on a line
that now named two files (AMBIG — written out in full), and a backticked
code span the QUOTE check read as a quotation at line 77 (re-cited to the
line that really carries it, `tb/scripts/gen_seq_chip_vectors.py:131`).

**`spec_cites.py` on THIS document**, run last, after its final edit, in the
same invocation as the design spec so one log covers both:

```
SPEC CITES: PASS          (FAIL 0)
```

The `checked:` counts are in the log rather than quoted here on purpose:
every backticked path in this section is itself an EXIST check, so a
sentence that quotes its own run's totals goes stale the moment it names the
log it came from.  The verdict and the failure count do not, and they are
what the gate turns on.

Its first run reported **FAIL 10**, all of them this document's own: two
QUOTE spans beside a citation that does not carry them, three backticked
BASENAMES of the gitignored 9B artifacts (which the checker rightly resolves
as repo paths and cannot find), one backticked bare basename of an evidence
script, two abbreviated `...` code quotations, and two ORPHAN bare
continuations.  All ten are fixed above by writing full paths where a path
is meant and dropping the backticks where a filename is only a label.  The
one `pending` is this file citing itself, which is on the checker's
deliberate PENDING list.
