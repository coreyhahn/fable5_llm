# Qwen3.5-4B / Qwen3.5-9B feasibility study (2026-08-25)

> ### PRE-G3.1 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 7 / G3.1)
>
> Nine rows in this study marked `<!--cites:noquote-->` quote **SEQ_ISA v1.7
> source that G3.1 DELETED** — the 15-bit scratch arrays, `ld_n <= arg0[10:0]`,
> the 13-bit `cfg_len`, the 13-bit CONV/CONVW channel compares, `logic
> kvhead_r;` and `dn_head <= arg0[3:0];`.  They are kept verbatim: this study
> is the record of the tree it was written against, and the walls it names are
> exactly the ones G3.1 removed.  Every citation that had merely MOVED was
> RENUMBERED instead, mechanically
> (`evidence/qwen9b/o3/o3_cite_drift.py --base d2d774b`); the exemption is only
> for source that no longer exists.  Post-G3.1 landmarks for every one:
> `evidence/qwen9b/g3/G3_1_ISA.md` §15.  This document's OTHER
> `spec_cites.py` failures are pre-existing and untouched.


> **VERDICT: NEITHER IS A WIDTH SCALE-UP, AND REACHABILITY IS CONDITIONAL ON
> ONE QUESTION — WHICH TRACK P HAS SINCE PARTLY ANSWERED (2026-08-25).**
> *The URAM question below is no longer unmeasured: it synthesizes to exactly
> 928 and it places. It is unresolved rather than unknown — see the bracketed
> update in the next paragraph, §6 item 3, and
> `evidence/qwen_next/place_exp/PLACE_EXP.md`.*
> The 2B migration was three walls, all field widths, all in blocks whose
> *geometry* never moved. These two share a **head-geometry change** the 2B
> never had — 16 → 32 DeltaNet value heads, 8 → 16 attention heads, 2 → 4 KV
> heads — which turns the layer-state banking into a **device-capacity**
> problem (**928 of 960 URAM, 96.7 %, spanning all three SLRs**) rather than a
> parameter problem. That wall is **identical at both targets**, it is the
> largest item in this study, and ~~**whether the VU9P places and routes at
> that occupancy is not known** — no synthesis was run here.~~
> **[UPDATED 2026-08-25, Track P: synthesis and `place_design` were both run.
> The count is exactly 928 and it PLACES. It fails timing at the as-built
> read-path structure; pipelining the crossings takes that path to MET, and
> the binding constraint becomes a write fan-out that is a floorplanning
> problem nobody has attempted — so 96.7 % is neither demonstrated live nor
> demonstrated dead. Routing was never run. §2.7's int8 lever IS measured
> closable. See §6 item 3's note and
> `evidence/qwen_next/place_exp/PLACE_EXP.md`.]** Both targets are
> reachable *if* it does, or *if* one of §2.7's two levers is taken; if
> neither, neither target proceeds as described. Say "reachable" only with
> that condition attached.
>
> Where they differ is smaller and cuts both ways. **9B is cleaner on
> power-of-two** — H=4096 keeps vecnorm and the embedding shift *expressible*,
> where H=2560 makes them expressible only by adding a reciprocal multiply to
> the normalizer; note this is not "works today", since vecnorm still
> `$fatal`s above N=2048 and needs one more doubling of every width R-b already
> widened once (§2.3). **4B is cleaner on scratch** (one body over the ceiling,
> not three) **and on throughput and DDR fit** — though 4B's own scratch fix
> costs an MLP restructuring, and its 5,120-byte embedding rows cost either
> 727.5 MiB or new logic (§2.6).
>
> **This study picks nothing. §8 is the open decision.**

Companion to `docs/QWEN2B_FEASIBILITY.md`, written to the same contract:
every claim is (**M**) measured on silicon, (**D**) derived by a committed
script that reproduces a committed number, or (**E**) extrapolated and
labelled. Nothing is asserted from memory. Evidence lives under
`evidence/qwen_next/feas/`, and every numeric step ran **on snoke** through
`evidence/qwen_next/feas/feas_run.sh` (host/date/tree/venv stamped, modelled on
`evidence/qwen2b/rd/rd_run.sh`) — darthplagueis is still the host that produced
wrong arithmetic **eight times** — `NEXT_SESSION.md`'s standing count, which
is the number this project uses. *Its source is internally incoherent and this
document does not reproduce the incoherence:* `docs/QWEN2B_QUANT_STUDY.md` §6.4
enumerates two trips in Q5 plus six in one Q8 day (= eight) and then calls a
later one during R-b's sim gate "instance 7", which cannot both be true. The
standing count of eight is used here; the discrepancy is the source doc's, and
it changes nothing — the rule is that numeric work runs on snoke either way.

**Scope: study only.** No RTL was edited, no board was touched, no bitstream
was built, and **no model weights were downloaded** — the geometry below comes
from ranged HTTP reads of each checkpoint's safetensors headers.

---

## 0. How to read the confidence labels

| label | means | example in this document |
|---|---|---|
| **M** | measured on this board, cited to a gate log | the 2B's 17.960 ms layer term |
| **D** | computed by a script under `evidence/qwen_next/feas/` that **reproduces a committed number** before it computes a new one | the scratch peaks, the DDR fit, the URAM budget |
| **E** | extrapolated past every measurement | the 4B/9B layer term, hence the tok/s |
| **T** | **measured by the TOOLCHAIN, not on silicon** — a Vivado `synth_design` / `place_design` result on real RTL and the real part, which is stronger than D but is *not* **M** (added 2026-08-25 for Track P; nothing before that date carries it) | the 928 URAM count and its placement |

Each derivation carries its own validation, and they are not decorative:

* `scratch_peak.py` reproduces the committed 0.8B and 2B scratch maps
  **exactly** (16,384 / 25,600, and every one of `PEAK_DN`/`PEAK_ATTN`/
  `PEAK_MLP`/`STG`/`STG_SZ`/`BIG`) before it evaluates 4B/9B — `f03`.
* `ddr_fit.py` runs the **shipped** `sw/hwmap.py:plan_weights`, and
  cross-checks every synthetic image against the checkpoint's own per-class
  parameter count; it reproduces the committed 2B W8 `1,936,920,576` bytes and
  the per-channel tops it implies (`f04` prints `464.8 MiB` on chan 0,
  which is `0x2d0c4000 - W_BASE`; the hex, the MiB and the 36.3 % all sit on
  `evidence/qwen2b/rc/t3_fit.log:8`, and the board readback is
  `RD_GATE.md:220` — none of them an f04 output).
* `toks_model.py` reproduces **12 of 12** counted quantities of
  `evidence/qwen2b/ra/MOVER_NORM.md` §2's 0.8B stream, plus its
  busiest-channel beat count and its bytes/token — `f05`.
* `resource_budget.py` reproduces build_035's **measured 348 URAM** from the
  bank declarations before it sizes anything — `f08`.
* `layer_cmd_census.py` counts the real 0.8B stream and lands on **288 DNST
  commands per token = 18 DN layers × 16 heads exactly** — `f16`. That stream
  (`tb/scripts/model_v2_s1.txt`) is **gitignored** (`.gitignore:13`, ~45 MB of
  a ~950 MB artifact set) but **byte-locked**: `ref/scripts/regen_gate.sh`
  re-emits it from committed sources, checks `sha256(model_v2_s1.e.seq)`
  against the frozen `GOLD_SEQ_SHA` (`:5`, `:38-40`), then `cmp`s the text
  against this very file (`:41`). So it regenerates byte-identically from a
  clean checkout, and a committed gate proves it — a stronger guarantee than
  an untracked file that merely exists.
* `quant_pricing.py` prices only from jsons carrying `"host": "snoke"`, and
  prints the darthplagueis/snoke ratio it is correcting for — `f17`.

**Where a derivation could not be validated, it says so, and three places in
this document say so loudly**: §4.2 **retracts** the r-bracket validation an
earlier revision claimed and reports the one out-of-sample test as *failing*;
§4.3 **retracts** the optimistic layer bracket outright; and §6 item 3 stated
that the URAM figure has no synthesis or placement behind it — **which Track P
closed on 2026-08-25: both runs now exist, and §6 item 3 carries their result
and two corrections to its own sharp form.** The layer term
at a new DeltaNet geometry is the one quantity with no validation available
anywhere — §4.3 gives it a single figure with a stated ±10 % allowance, and
explains why the *scaling law* is primary-source even though the *coefficient*
is a fit intercept.

---

## 1. The geometry — from the checkpoints, not from `config.json`

`evidence/qwen_next/feas/fetch_geometry.py` (**D**) reads every shard's
safetensors JSON header by ranged HTTP and the `config.json` beside it, for all
four models. Logs `f01_geometry.log`, `f02_geom_report.log`; raw
`geometry_raw.json`.

The 2B campaign's lesson was that checkpoints surprise. They did again.

| field | 0.8B | 2B | **4B** | **9B** |
|---|---|---|---|---|
| `hidden_size` | 1024 | 2048 | **2560** | **4096** |
| `intermediate_size` | 3584 | 6144 | **9216** | **12288** |
| `num_hidden_layers` | 24 | 24 | **32** | **32** |
| layer types (DN / full) | 18 / 6 | 18 / 6 | **24 / 8** | **24 / 8** |
| `vocab_size` | 248320 | 248320 | 248320 | 248320 |
| `head_dim` | 256 | 256 | 256 | 256 |
| **`num_attention_heads`** | 8 | 8 | **16** | **16** |
| **`num_key_value_heads`** | 2 | 2 | **4** | **4** |
| `linear_num_key_heads` | 16 | 16 | 16 | 16 |
| **`linear_num_value_heads`** | 16 | 16 | **32** | **32** |
| `linear_key_head_dim` / `linear_value_head_dim` | 128 / 128 | 128 / 128 | 128 / 128 | 128 / 128 |
| `linear_conv_kernel_dim` | 4 | 4 | 4 | 4 |
| `tie_word_embeddings` | true | true | **true** | **null** (see below) |
| shards | 1 | 1 | **2** | **4** |
| on-disk bf16 | 1.63 GiB | 4.24 GiB | **8.68 GiB** | **17.98 GiB** |

### 1.1 The finding: the DeltaNet head count doubles

Confirmed twice — by `config.json` and independently by the tensor shapes,
which is the check `config.json` alone cannot give:

| tensor (layer 0, a DeltaNet layer) | 2B | **4B** | **9B** |
|---|---|---|---|
| `linear_attn.in_proj_qkv.weight` | [6144, 2048] | **[8192, 2560]** | **[8192, 4096]** |
| `linear_attn.in_proj_z.weight` | [2048, 2048] | **[4096, 2560]** | **[4096, 4096]** |
| `linear_attn.in_proj_a` / `in_proj_b` | [16, 2048] | **[32, 2560]** | **[32, 4096]** |
| `linear_attn.A_log` / `dt_bias` | [16] | **[32]** | **[32]** |
| `linear_attn.conv1d.weight` | [6144, 1, 4] | **[8192, 1, 4]** | **[8192, 1, 4]** |
| `linear_attn.out_proj.weight` | [2048, 2048] | **[2560, 4096]** | **[4096, 4096]** |
| `linear_attn.norm.weight` | [128] | [128] | [128] |

`8192 = 2·(16·128) + 32·128`: **16 key heads and 32 value heads**. Each key
head serves two value heads; the recurrent state is `dk × dv` **per value
head**, so the DeltaNet state **doubles**, and `CONV_DIM` goes 6144 → **8192**.

The full-attention layers move the same way:

| tensor (layer 3, a GQA layer) | 2B | **4B** | **9B** |
|---|---|---|---|
| `self_attn.q_proj.weight` | [4096, 2048] | **[8192, 2560]** | **[8192, 4096]** |
| `self_attn.k_proj` / `v_proj` | [512, 2048] | **[1024, 2560]** | **[1024, 4096]** |
| `self_attn.o_proj.weight` | [2048, 2048] | **[2560, 4096]** | **[4096, 4096]** |

`q_proj` is `2 · NQ · HD` because `attn_output_gate` is true, as at 0.8B/2B.
16 query heads, 4 KV heads: **the KV cache doubles too.**

> **The consequence that shapes everything below.** 4B and 9B have the
> **identical** head geometry, the identical layer count, and the identical
> DeltaNet and KV state size. **Every wall that comes from head count or layer
> count is exactly the same size at both targets** — including the biggest one,
> the 928-URAM state banking. They differ only in `hidden_size` and
> `intermediate_size`.
>
> *(An earlier revision added "any RTL that opens for one opens for the other".
> That is false and §7.3 contradicts it: four of the seventeen wall rows —
> scratch, vecnorm, embedding rows and the untied head — differ between the
> targets, and two of them are XL. The scoped sentence above is the true one.)*

### 1.2 The 9B's LM head, precisely

**Ground truth first, because two earlier revisions of this section got it
wrong in opposite directions** (`f15_tie_ground_truth.log`, which prints the
raw key presence rather than a `.get()` result):

| | top-level `tie_word_embeddings` | `text_config.tie_word_embeddings` |
|---|---|---|
| 0.8B / 2B / 4B | present, `true` | present, `true` |
| **9B** | present, **`false`** | **ABSENT** |

It is **`false` at the top level and ABSENT from `text_config`** — not `null`
anywhere. This study's `fetch_geometry.py` printed `None` for the absent key
(a bare `.get()` with no default) and the first revision read that as an
explicit JSON `null`; review round 1 then "corrected" it into the claim that
the loader guard raises. **Both were wrong.**

What the loader actually does: `ref/load_qwen35.py:169-170` `load_config()`
returns `json.load(...)["text_config"]`, so `:288`'s
`if not cfg.get("tie_word_embeddings", True):` is evaluated on the **text**
config, where the key is **absent** — the `True` default applies, `not True` is
false, and **the config guard passes silently.**

So there is **exactly ONE refusal, not two**: `:291-294`, on the presence of
the tensor. The 9B carries **`lm_head.weight` [248320, 4096]** as a
**top-level** tensor, outside the `model.language_model.` prefix
`load_layer()` filters on, and that guard raises. The config guard being
silent is what makes the tensor guard load-bearing — and it is a small
latent hazard in its own right: a future untied checkpoint that put the flag
in `text_config` and the head under the text prefix would pass both.

### 1.3 The rest of the census (**D**, `f02`)

| prefix | 2B | 4B | 9B |
|---|---|---|---|
| `model.language_model` | 320 t, 1,881,825,088 p | **426 t, 4,205,751,296 p** | **426 t, 7,936,684,544 p** |
| `lm_head` (top level) | — | — | **1 t, 1,017,118,720 p** |
| MTP head | 15 t, 60,828,160 p | **15 t, 120,599,552 p** | **15 t, 243,290,624 p** |
| vision tower | 297 t, 331,416,576 p | 297 t, 333,514,240 p | 333 t, 456,010,480 p |

The MTP head and the vision tower are present at both targets, are filtered out
by the loader exactly as at 2B (`docs/QWEN2B_QUANT_STUDY.md` §0), and are
shipped-unused. Parameter-budget arithmetic must start from the text figure.

### 1.4 The tokenizer: half of what the 2B got for free (**D**, `f10`/`f11`)

`docs/QWEN2B_FEASIBILITY.md:19-20` recorded "byte-identical tokenizer + chat
template". Only half repeats:

* **`tokenizer.json`, `vocab.json`, `merges.txt` are byte-identical across all
  four models.** Tokenization is unchanged, so `ref/ppl_corpus_eval.txt` and
  its **24,528 scored positions carry over exactly** — the whole Track-Q
  harness is reusable without re-pinning.
* **`chat_template.jinja` DIFFERS** — and so does `tokenizer_config.json`,
  which embeds a copy of it (`49e2b6e3…` for 0.8B/2B, `316230d6…` for 4B/9B).
  0.8B/2B share one template, 4B/9B share another.
  The diff is a **12-line unified diff touching 3 of the template's 154
  lines**, and it **inverts the `enable_thinking` default**:
  0.8B/2B emit `<think>\n\n</think>\n\n` unless asked for thinking; 4B/9B emit
  an **open `<think>\n`** unless asked *not* to. The host-side id-spliced
  template (`docs/INSTRUCT_SPEC.md`, `ref/seq_chat.py`) must be re-derived, and
  the `ntok >= 24` UX guidance moves — a reasoning block now precedes the
  answer by default.

  > **DATED NOTE 2026-09-10 (pre-ship documentation chore).** That last
  > clause is true of **the MODEL's own chat template** and false of **this
  > host**. The host does not run the model's template: it splices token ids
  > directly, and what it emits is fixed by `ref/seq_chat.py`'s own
  > `Templates` and by the artifact those ids were baked into — not by
  > whatever `enable_thinking` defaults to upstream. So no UX guidance moves
  > here unless the host template is deliberately re-derived to open a
  > reasoning block, which is the sentence above's first clause and is a
  > decision, not a consequence. The distinction is worth the four lines
  > because a reader was taking a model-template fact as a host fact.

---

## 2. Wall census against the as-built RTL

The 2B campaign's wall list is the checklist; every wall is re-derived at both
new geometries, and the ones the 2B list does not cover are marked **NEW**.
Every limit is cited to `file:line`, and the load-bearing ones are quoted.

### 2.1 Summary matrix

| # | wall | ceiling as built | 4B | 9B | class |
|---|---|---|---|---|---|
| 1 | scratchpad words | 32,768 (15-bit ISA) | **FAIL** 36,384 | **FAIL** 50,208 | L (4B) / XL (9B) |
| 2 | vecnorm N | 2048, **power-of-two only** | **FAIL** — 2560 needs a reciprocal multiply | **FAIL** — 4096 needs nlog2 12 and one more doubling of every width | XL (4B) / M (9B) |
| 3 | ALU `cfg_len` | 8191 | **FAIL** 9216 | **FAIL** 12288 | **S** |
| 4 | matvec `ng` | MAX_NG 48, 6-bit SHAPE field, 6 KiB XWIN decode, 11-bit `xptr` | **FAIL** 72 | **FAIL** 96 | L |
| 5 | EMBLOG2 row stride | power-of-two, max 13 | **FAIL** 5120 B | **PASS** at the ceiling | M (4B) / none (9B) |
| 6 | **DN state URAM banks** | 9 banks = 18 DN × 16 heads | **FAIL** 24 banks | **FAIL** 24 banks | **XL, shared** |
| 7 | **KV URAM banks** | 3 banks = 6 GQA × 2 kv heads | **FAIL** 8 banks | **FAIL** 8 banks | **L, shared** |
| 8 | conv banks + depth | 18 banks × 6144 | **FAIL** 24 × 8192 | **FAIL** 24 × 8192 | L, shared |
| 9 | **NEW** `kvhead` field | **1 bit** | **FAIL** kv=4 | **FAIL** kv=4 | M, shared |
| 10 | **NEW** `dn_head` field / `gate_unit` NH | 4 bits / NH=16 | **FAIL** 32 heads | **FAIL** 32 heads | M, shared |
| 11 | **NEW** CONV `cvi` count field | 13 bits, max 8191 | **FAIL by 1** (8192) — but the CONVW twin's wrap already encodes it | **FAIL by 1** | **S**, shared |
| 12 | **NEW** multi-shard loader | single-file only | **FAIL** 2 shards | **FAIL** 4 shards | **S** |
| 13 | untied LM head | tied assumed; the config guard passes **silently** | n/a (tied) | **FAIL** (tensor guard only) | **S** |
| 14 | **NEW** `ref` key/value head algebra (two sites) | `LKD = LNVH·LDK` | **FAIL** | **FAIL** | **S**, shared |
| 15 | **NEW** SCA scalar-tile strides | 32-word slots | **FAIL** | **FAIL** | **S**, shared |
| 16 | layer banking depth | 18 DN / 6 GQA slots | **FAIL** 24 / 8 | **FAIL** 24 / 8 | (= 6,7,8) |
| 17 | host-model geometry rot | 0.8B literals | **FAIL** | **FAIL** | M, shared |

**Thirteen of the seventeen are the same wall at both targets** (rows 3, 4 and
12 differ only in magnitude — FFN 9216 vs 12288, ng 72 vs 96, 2 shards vs 4).
**The four that are not — 1, 2, 5, 13 — are where the choice actually lives.**

### 2.2 Wall 1 — the scratchpad (**D**, `f03`)

Declared `rtl/layer_chan.sv:476-477`:  <!--cites:noquote-->

```systemverilog
logic signed [15:0] smem_a [32768];
logic signed [15:0] smem_b [32768];
```

with 15-bit addressing throughout (`:254`, `:264`, `:282`, `:793-794`;
`rtl/vec_alu.sv:114-116`) and `ref/gen_layer_script.py:222` `SCRATCH_MAX = 32768`.

`evidence/qwen_next/feas/scratch_peak.py` mirrors the allocator's algebra
(`ref/gen_layer_script.py:69-133`, line-for-line) and **reproduces the committed
0.8B and 2B maps exactly** before evaluating the new geometries:

| body | 0.8B | 2B | **4B** | **9B** |
|---|---|---|---|---|
| `PEAK_DN` | 16,384 | 21,504 | 29,216 | **33,824** |
| `PEAK_ATTN` | 15,872 | 23,552 | **32,288** | **37,920** |
| `PEAK_MLP` | 14,848 | **25,600** | **36,384** | **50,208** |
| **PEAK** | **16,384** | **25,600** | **36,384** | **50,208** |
| vs 32,768 | +16,384 | +7,168 | **−3,616** | **−17,440** |

*(The 2B row is the number `evidence/qwen2b/ra/scratch_probe.log` measured
empirically — `MEASURED PEAK == DERIVED PEAK` at both calibration points.)*

**The ISA cannot simply grow.** `docs/SEQ_ISA.md:828-837` records that DNST's
ARG0 is "32 bits EXACTLY full, with no spare anywhere in it" and that ALU's
ARG2 "has exactly ONE spare bit, 31, and that is where its `dst[14]` went". The
15th address bit had a home in every arg word; **the 16th does not**. A 64K
scratchpad is a re-encoding of the layer ISA, not another bit-borrow — and it
doubles the scratch BRAM and needs `LAYB_BASE` (`rtl/seq_unit.sv:169`) moved to
a 256 KiB-aligned slot, because the AXI segment is exactly 128 KiB and must be
range-aligned (`rtl/seq_movers.sv:14-23`).

**So the question is how many BODIES must be restructured instead**, and here
the two targets separate sharply:

> **Chunking is not as cheap as an earlier revision of this section said.**
> `PEAK_MLP = max(ML_SG + FFN, ML_DDST + H)` (`ref/gen_layer_script.py:130`)
> has **two** terms, and chunking the gate/up pair into `nc` pieces of `C`
> shrinks the first (`STG + 3·C`) twice as fast as the second
> (`STG + 2·C + STGCH + H`). The down-stage therefore takes over as the peak —
> which is exactly what `docs/QWEN2B_SCRATCH_MAP.md:161`, `:171-177` warns
> ("chunking destroys the domination condition"). The earlier numbers carried
> only the first term and over-stated the headroom. Corrected (`f03`), with
> **the down-stage binding in every case**:

| chunks | 4B gate/up | 4B down-stage | **4B peak** | 9B gate/up | 9B down-stage | **9B peak** |
|---|---|---|---|---|---|---|
| 2 | 22,560 | 24,608 | **24,608** (spare 8,160) | 31,776 | 33,824 | **33,824 — OVER by 1,056** |
| 3 | 17,952 | 21,536 | **21,536** (spare 11,232) | 25,632 | 29,728 | **29,728** (spare 3,040) |
| 4 | 15,648 | 20,000 | **20,000** (spare 12,768) | 22,560 | 27,680 | **27,680** (spare 5,088) |

* **4B: one body.** Only the MLP is over. A **two-way** gate/up chunk gives
  **24,608 words, 8,160 spare** (not the 10,208 an earlier revision claimed);
  three ways gives 21,536. Emitter work, no ISA change, no extra BRAM.
  **Caveat, stated because it is thin: 4B's ATTN body clears the ceiling by
  480 words.** Anything that grows an attention tile busts it.
* **9B: all three bodies.** A two-way MLP chunk lands at **33,824 — over by
  1,056**, not the "992 spare" the earlier revision reported; it takes a
  **three-way** chunk to fit the MLP at all (29,728). And `PEAK_ATTN` 37,920
  and `PEAK_DN` 33,824 are over on their own regardless. `PEAK_DN` is
  `BIG + CONV_DIM + LVD = 21,536 + 8,192 + 4,096` — the DeltaNet body's own
  tiles no longer fit; note it equals the two-way MLP peak exactly, which is a
  coincidence of the arithmetic and not a shared cause.
  **9B realistically wants the 16-bit scratch ISA.**

### 2.3 Wall 2 — vecnorm, and why H=2560 is the hard one

> **PRE-G3.2 LINES, KEPT AS THE RECORD — dated note 2026-09-02 (Task 8).**
> **G3.2 LANDED THE H = 4096 WIDENING THIS SECTION PRICES.**  The
> *as built (for N=2048)* column below, and the `n_total` quotation above
> it, quote source G3.2 REWROTE, so those lines carry
> `<!--cites:noquote-->` under spec §7.6's rule (*"an exemption is for
> source that no longer exists, not for a citation that has merely
> moved"*); citations that had merely MOVED were renumbered mechanically
> by `evidence/qwen9b/o3/o3_cite_drift.py --base ec08638`.  The whole
> *needed* column is now the tree's state and the post-G3.2 landmark for
> every row is in `evidence/qwen9b/g3/G3_2_VECNORM.md` §9.  **H = 2560
> is UNAFFECTED and still refused**: G3.2 widened the shift, it did not
> add a length input, so wall 2's non-power-of-two half stands.

`rtl/vecnorm_unit.sv:86` takes `input wire [3:0] cfg_nlog2`, and N is produced
**only** by shifting — `rtl/vecnorm_unit.sv:277` `n_total <= 12'd1 << cfg_nlog2;`,  <!--cites:noquote-->
`rtl/layer_chan.sv:1281` `n_elems <= 15'd1 << arg0[5:2];`. There is no plain  <!--cites:noquote-->
length input anywhere in the unit. Worse, the `1/N` of the mean is folded into
the rsqrt binary point as a shift — `rtl/vecnorm_unit.sv:331-333`:

```systemverilog
rs_p <= 6'(2 * cfg_inf) + (((cfg_mode != 2'd2) || eps_on) ? 6'(cfg_nlog2) : 6'd0);
```

* **H = 4096** needs `nlog2 = 12`, and every width R-b set for N=2048 must move
  again. Stated as deltas, because an earlier revision of this document listed
  the AS-BUILT widths as if they were the needed ones:

  | site | as built (for N=2048) | needed for N=4096 |
  |---|---|---|
  | `:159` `logic [11:0] cnt, n_total;` *"12 bits: n_total = 2048 must FIT"* | 12 b | **13 b** |  <!--cites:noquote-->
  | `:161` `logic [11:0] oidx;` | 12 b | **13 b** |  <!--cites:noquote-->
  | `:106-107` `xbuf [2048]`, `wbuf [2048]` | 2048 | **4096** |  <!--cites:noquote-->
  | `:93` `input wire [10:0] w_waddr,` (comment `:90-91`: *"11 bits: modes 0/1 at n_log2 = 11 need all 2048 wbuf entries reachable"*) | 11 b | **12 b** |  <!--cites:noquote-->
  | `rtl/layer_chan.sv:537` `logic [10:0] vn_waddr;` | 11 b | **12 b** |  <!--cites:noquote-->
  | `:422-425` `$fatal(… cfg_nlog2 >= 4'd12 …, "max 11, N=2048")` | guard | **moved to ≥ 13** |  <!--cites:noquote-->

  (`STG = SCA + max(1024, SCA_SZ)`, i.e. `SCA + 1056` once §2.9's tile fix
  lands, not `SCA + 1024`.) Two that do **not** move: `ss_acc` is 48 b with the comment *"2048 * 32767² <
  2^42, still fine"* — at 4096 it is 2^43, still fine; and `rs_p` is 6 b, which
  holds `nlog2 = 12`. **This is the same widening R-b performed once** (1024 →
  2048, including the `n_total` wrap-to-zero deadlock it uncovered) — one more
  doubling of the same structures, so it is precedented and costed, **not**
  free.
* **H = 2560 is expressible only by adding a reciprocal multiply.** No `k`
  gives `2^k = 2560`, and the `1/N` is a shift, not a divide. Supporting it
  means putting a real reciprocal multiply into the normalizer's datapath — a
  *different* change
  from widening a counter, in a unit that sits on the layer critical path.

Related and independent: the VNW weight-load count is
`rtl/layer_chan.sv:1413` `ld_n <= arg0[10:0]` with 0 encoding 2048 — the escape  <!--cites:noquote-->
value is already spent, so **both** H=2560 and H=4096 need that field widened
regardless.

### 2.4 Wall 3 — the ALU length field (wall-6 redux), and `arg0[17]`

`rtl/vec_alu.sv:112` `input wire [12:0] cfg_len,`; wired at  <!--cites:noquote-->
`rtl/layer_chan.sv:757` `.cfg_len(arg0[16:4]), // R-c: 13-bit len`;  <!--cites:noquote-->
`docs/SEQ_ISA.md:544` "13 bits, max 8191", mirrored host-side as
`ALU_LEN_MAX = (1 << 13) - 1` in **two** emitters
(`ref/gen_layer_script.py:709`, `ref/seq_format.py:1411`) and as a bound in
`ref/seq_model.py`. FFN 9216 and 12288 both exceed it,
and the failure mode is **silent truncation** — the 2B burned this exact wall
once at 12 bits, where "the sequencer asked for 6144 and the engine ran
`6144 & 0xFFF` = 2048" (`docs/SEQ_ISA.md:563`). It cannot be chunked around:
DYNQ8 picks one shared exponent over the whole vector (`rtl/vec_alu.sv:104-110`).

**Is `arg0[17]` provably spare? Yes — by the repo's own methodology, re-run
here at three scopes (D, `f12`/`f14`/`f13`).** `ref/scripts/scan_spare_bits.py` ORs
the ARG words at *ALU dispatch* across streams — so it catches the stale-shadow
hazard against the ARG shadow declared at `rtl/seq_unit.sv:856` — and a bit
that is 0 in the OR
mask was never set by any stream:

| scope | files | ALU dispatches | opcode-11 ARG0 mask | free bits |
|---|---|---|---|---|
| frozen pre-R-b set (the scanner's default) | 32 + 6 | 248,218 | `0x0000f90f` | `31:16`, 10:9, 7:4 |
| **`tb/scripts` + `tb/scripts_scratch` (all committed)** — `f14` | **50 + 22** | **293,768** | **`0x0001fb8f`** | **`31:17`**, 10, 6:4 |
| the above + `.rung1b_wip` (**gitignored**, so not reproducible from a clean checkout) | 53 + 24 | 338,932 | `0x0001fb8f` | `31:17`, 10, 6:4 |

**Bits 31:17 are zero in every scope.** Bit 16 is set in the two post-R-c
scopes and clear in the frozen one — R-c's `len[12]` doing its job at FFN 6144,
which is the control that shows the scan is measuring what it claims to. The
contrast is visible in the same runs: DNST's ARG0 mask is `0xfdbff7ff` with
**bit 17 set**, because `arg0[17:4]` is DNST's `a_dec[13:0]`
(`rtl/layer_chan.sv:1192-1193`) — a different opcode on the same physical CSR.
The repo already anticipated the answer in an assert message at
`ref/gen_layer_script.py:784-785`: *"ARG0[31:17] is still spare"*.

*(The `--all` and explicit-ROOT runs end `SCAN VERDICT: FAIL` and that is
correct, not a problem: the scanner's home table lists R-b's bit-14 and R-c's
`len[12]` homes, which post-R-b streams legitimately set. The scanner documents
this at `:26-33`. The frozen-scope run, which is the one whose verdict means
anything, ends **PASS**.)*

`arg0[17:4]` gives 14 bits, max **16383**, covering both FFNs with headroom.
The change is **not** a one-liner as R-c's was — R-c was cheap because
`ag_i` was already 13 bits, and this time it is not
(`rtl/vec_alu.sv:188`). It is ~16 sites across `rtl/vec_alu.sv`,
`rtl/layer_chan.sv:757`, `ref/gen_layer_script.py:709`, `ref/seq_format.py:1411`,
`ref/seq_model.py:649-656`, `docs/SEQ_ISA.md:544`, the scanner's own home table,
and the TBs — with the **frozen** `tb/legacy/vec_alu_legacy.sv` deliberately
left alone. Still the cheapest wall in this study.

> **One pre-existing hole found on the way.** `sw/chat_seq.py:1759` already
> decodes the ALU count **14 bits wide** (`(a0 >> 4) & 0x3FFF`), wider than the
> hardware field. That is precisely the property `ref/seq_model.py:642-648` and
> `docs/SEQ_ISA.md:565-568` say let wall 6 hide the first time. Benign today
> only because both emitters refuse > 8191.

### 2.5 Wall 4 — `MAX_NG`, and the 6-bit SHAPE field

> ### PRE-G3.3 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 9)
>
> Rows here marked `<!--cites:noquote-->` quote **source that G3.3 DELETED**,
> not source that merely moved: the 6-bit `cfg_ng` / `x_line` / `g_q…g5_q` / `r_g` declarations, the `wbeats` and `ng7` wires, the 1536-word `x_mem`, and the 6 KiB XWIN decode with its 11-bit pointers, together with the `cfg_w8` / `cfg_g64` ports and everything that selected on them, SHAPE bits 28 and 29, and the W8-envelope adder tree.  They are kept verbatim, because they
> are the record of what the pre-G3.3 tree said and the argument they support
> rests on them (§0: nothing is deleted or struck).  The exemption marker is
> used for exactly the reason §7.6 gives — *"an exemption is for source that
> no longer exists, not for a citation that has merely moved"* — and every
> citation that had merely MOVED was RENUMBERED instead, mechanically, by
> `evidence/qwen9b/o3/o3_cite_drift.py --base a08a90b`.
> **The post-G3.3 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_3_MATVEC.md` §11.1.**

`rtl/matvec_engine.sv:209` `parameter int MAX_NG = 48, // max groups/row (K <= 6144)`  <!--cites:noquote-->
and `:199` `input wire [5:0] cfg_ng,`, decoded from SHAPE
(`rtl/matvec_chan.sv:18`, decoded at `:336-340`) which has **exactly 2 spare  <!--cites:noquote-->
bits, [31:30]** — the layout is `:18`'s `{2'b0, w8[29], g64[28], nrows[27:12],
sh[11:6], ng[5:0]}`.

`down_proj` has `K = FFN`, so 4B needs **ng = 72** and 9B **ng = 96** — and
**both overflow the 6-bit field itself (max 63)** before storage is considered.
The design documented this cliff when W8 was added, at `rtl/matvec_engine.sv:10-13`:  <!--cites:noquote-->
*"redefining ng as the W8 beat count would need 96 > 63 at K = 6144 and overflow
the 6-bit SHAPE field"*. The W8 mode's whole format constraint — that `ng` keeps
meaning `K//128` — exists to avoid it (`docs/QWEN2B_QUANT_STUDY.md` §5). At
FFN 12288 the *natural* `ng` is 96 and there is no encoding trick left.

Everything that must move with it, all verified in-file:

| site | today | needed |
|---|---|---|
| `matvec_engine.sv:192` `MAX_NG` | 48 | 96 |
| `matvec_engine.sv:199` `cfg_ng` | 6 b | 7 b (SHAPE bit 30, leaving 1 spare) |
| `:250` `x_mem [32][MAX_NG]` | 1536 words | 3072 |
| `:517-518` `acc_bank_{lo,hi}[2][MAX_NG]` | 48 | 96 |
| `:262-264` `g_cnt` | 7 b (the RTL's own *"2*MAX_NG + 2 = 98"*) | 8 b (2·96+2 = 194) |
| `:275` `wbeats` | 7 b | 8 b |
| `:292-293` `n_scale_beats`, `:300` `scale_beat_idx` | 2 b | 3 b — **but only in g64**, see below |
| `:254` `x_waddr[10:5]` line index (port at `:213`; the unbacked-hole note at `:240-251`) | 64 lines addressable, 48 backed | 96 lines → 12 b |
| `:589` `r_g` retire index | 6 b | 7 b |
| `matvec_chan.sv:552`, `seq_movers.sv:174` `XWIN_WORDS` | 1536 | 3072 |

> **The XWIN aperture does NOT have room, and an earlier revision said it
> did.** The 64 KiB per-channel stride is not the constraint; the *decode* is.
> `rtl/matvec_chan.sv:613-614` hard-wires exactly 6 KiB —  <!--cites:noquote-->
> `wb_win <= (s_axib_awaddr[15:13] == 3'b010) && (s_axib_awaddr[12:11] != 2'b11);`
> which admits `0x4000…0x57FF` and nothing above it — and both pointers are
> 11-bit: `wb_ptr <= s_axib_awaddr[12:2]` on the same line and
> `logic [10:0] xptr;` at `:220` (with the XPTR CSR write at `:336` and its
> readback at `:360` matching). At `MAX_NG = 96`, XWIN is **3072 words =
> 12 KiB**, which overflows the decode *and* both pointers. So the row belongs
> in the table above, not outside it: **`matvec_chan`'s AXI decode and its
> `xptr`/`wb_ptr` widen too** — in the same timing-sensitive block as
> everything else in this wall.

> **The scale-beat field splits by precision, and it matters for the GPTQ row.**
> `rtl/matvec_engine.sv:312-313` is  <!--cites:noquote-->
> `n_scale_beats = cfg_g64 ? 2'((ng7+15)>>4) : 2'((ng7+31)>>5)`, two bits, with
> `scale_beat_idx` at `:300` likewise two bits and commented *"which 32-scale
> slice of the row this beat carries (0, 1 or 2)"*. Evaluated at the new `ng`:
>
> | | ng=48 (today) | ng=72 (4B) | ng=96 (9B) |
> |---|---|---|---|
> | **g128** (and therefore all W8) | 2 | **3 — fits** | **3 — fits** |
> | **g64** | 3 | **5 — OVERFLOWS** | **6 — OVERFLOWS** |
>
> So **W8 and W4 g128 keep the 2-bit scale-beat fields; W4 g64 does not.**
> `sw/hwmap.py:150` and `:660` already assert `not (w8 and g == 64)`, so W8 is
> g128 by construction. The consequence for §4.4's GPTQ note: GPTQ-lite is byte-free on
> the board, but at these geometries its **g64 cadence costs a wider scale-beat
> field inside `matvec_engine`** that W8 and W4 g128 do not need. It is one
> more small item in the same block, not a new wall — but "GPTQ costs the board
> nothing", true at 2B, is **not** true at 4B/9B.

What does **not** move: `ROW_W = 16` row counters, the 48-bit row
accumulator `p_acc` (`rtl/matvec_engine.sv:126` states *"48 b (39 b used),  <!--cites:noquote-->
44 b at K=6144"*; doubling K to 12288 adds one bit, so ≈ 45 b of 48 — this
study's arithmetic on the RTL's own figure, not a measurement), the 4096-row RES
window, and the 18-bit AMAX index (vocab 248,320 of 262,144 — 13,824 spare, 5.6 % of the vocabulary, 5.3 % of the index space) —
all verified safe at both targets.

**Timing note, carried from the 2B record:** `matvec_engine` is the block that
owned build_034's **worst 22 endpoints, and 24 of the 50 in total**,
(`docs/QWEN2B_QUANT_STUDY.md` §1.1), and build_035 closed at **WNS 0.000 with
zero margin** (`evidence/qwen2b/rd/RD_GATE.md` §6). This wall re-opens that
block, exactly as the W8 mode did.

### 2.6 Wall 5 — EMBLOG2 and 4B's 5,120-byte rows (**D**, `f04`/`f06`)

The row address is a **pure barrel shift** — `rtl/seq_unit.sv:934-935`:

```systemverilog
wire [ADDR_W-1:0] emb_a = ADDR_W'({r_tgt, r_imm})
                          + (ADDR_W'(xrf[3]) << emb_row_log2);
```

with the RTL's own admission at `:839-841` that the stride is *"a power of two
by construction"*, a 5-bit register at `:298`, range `[8, 13]` at `:288-289`,
and the host gate `sw/hwmap.py:390-399` raising `ValueError` on a non-power-of-two.
Row bytes are `2 · H`, unpadded (`ref/gen_model_script.py:517` allocates `(vocab, LR.H)` int16, `:618` sets
`emb_row_bytes=2 * LR.H`, `:619` writes it flat;
`ref/scripts/bytes_per_token.py:160-162`).

| model | row | verdict |
|---|---|---|
| 2B | 4096 B | EMBLOG2 12 |
| **4B** | **5120 B** | **REJECTED** — *"emb row 5120 B is not a power of two"* |
| **9B** | **8192 B** | EMBLOG2 **13 — exactly at `SEQ_EMBLOG2_MAX`** |

Options for 4B, costed (`f06`):

| option | DDR cost | RTL cost | note |
|---|---|---|---|
| **(a) pad rows to 8192 B** | table 1,212.5 → **1,940.0 MiB** (**+727.5 MiB, +60 %**) | **none** | channel 0 ends **78.7 % full at W8**, 66.5 % at W4 — it fits |
| **(b) non-pow2 addressing** | saves the 727.5 MiB | small but **badly placed** | 5120 = 4096+1024, a **two-term shift-add**, not a general multiplier — but it lands in `seq_unit`'s EMB address path. **Stated precisely, because an earlier revision overstated it:** build_034's third waived class is *sequencer MOV addressing* — all three of its endpoints are MOV-path (`shipped_roll_endpoint_census.log:133`, `:154`, `:156`) — and `docs/QWEN2B_QUANT_STUDY.md:226-227` says the R6 **EMB** 5-bit barrel shift does **not** appear in either worst violating path. So this is new logic *adjacent to* a waived class, not inside it, on a design now at **zero** timing margin. Also needs EMBLOG2 to stop being a log2 field |
| (c) int8 embeddings | row 2560 B | still non-pow2 | does not avoid (b), and is an unmeasured fidelity change |

**(a) is the cheap one** unless the channel budget tightens. **Both targets land
on EMBLOG2 13, the maximum the CSR encodes** — any future model with H > 4096
needs that field widened even with a clean power-of-two row.

### 2.7 Walls 6–8 — the state banking, and the URAM ceiling (**D**, `f08`)

This is the largest item in the study, and it is **the same size at both
targets**.

As built, `rtl/layer_chan.sv`:

```systemverilog
:423-424  generate for (gd = 0; gd < 9;  gd++) ... logic [2047:0] mem [4096];  // DN state
:475-476  generate for (gk = 0; gk < 3;  gk++) ... logic [2047:0] mem [4096];  // KV cache
          (:477 adds `logic [7:0] emem [4096];` in the same bank)
:512-514  generate for (gc = 0; gc < 18; gc++) ... logic [63:0] wm [6144];
                                                  logic [47:0] sm [6144];     // conv
```

9 DN banks = 36,864 rows = **exactly** 18 DN slots × 16 heads × 128 rows — the
array is full at 18 DN layers, which `evidence/qwen2b/ra/dn_bank_verify.md:64-75`
already recorded. `resource_budget.py` reproduces the **measured 348 URAM** of
build_035 (`evidence/qwen2b/rc/TIMING_035.md:347`, `:851`) from those
declarations — 12 banks × 29 URAM288 each — before sizing anything:

| | DN rows | DN banks | DN URAM | KV rows | KV banks | KV URAM | **total** | of 960 | SLRs |
|---|---|---|---|---|---|---|---|---|---|
| 0.8B / 2B | 36,864 | 9 | 261 | 12,288 | 3 | 87 | **348** | 36.2 % | 2 |
| **4B** | 98,304 | 24 | 696 | 32,768 | 8 | 232 | **928** | **96.7 %** | **3** |
| **9B** | 98,304 | 24 | 696 | 32,768 | 8 | 232 | **928** | **96.7 %** | **3** |

**96.7 % of the device's URAM, on a design whose floorplan campaign already
recorded that `layer_0` at 348 URAM cannot fit in one SLR** (320/SLR —
`evidence/qwen2b/rc/TIMING_035.md:629-630`), whose only clean timing closure
came from four soft pblocks that had to leave `layer_0` unconstrained because
constraining it *in any form* cost ~1 ns (`NEXT_SESSION.md`, T5), and which
closes today at **WNS 0.000**. This is the study's **#1 risk**, and it is a
capacity risk, not a field-width risk.

BRAM is not the wall. Conv banks (18 × 6144 → 24 × 8192) and the scratchpad
(32,768 → 65,536 words, if the ISA grows) take the device from 576.5 to
**886.5 of 2,160 tiles (41.0 %) at 9B**, which needs the 65,536-word
scratchpad, and **858.5 (39.7 %) at 4B**, which does not (§2.2 fits 4B inside
32,768 by chunking the MLP). `f08` prints **886.5 for both** because it assumes
the larger scratchpad at both; **the 858.5 is this document's arithmetic on
f08's own components** — 886.5 − 28 scratch RAMB36 — and appears in no log.

**Two levers, both named rather than proposed:**

1. **Narrow the DN state element from int16 to int8.** The state row is
   2048 b = 128 × 16 b; the KV cache beside it is **already** 8 b/element. At
   int8 two state rows pack into one URAM row and the budget goes
   **928 → 580 of 960 (96.7 % → 60.4 %, three SLRs → two)**. This is a fidelity
   change with **no measurement anywhere in this repo** — `ref/audit_ranges.py`
   would have to score it, and the 2B audit's finding that the `Av` gate port
   already runs 1-of-288 heads over its rail (`docs/QWEN2B_QUANT_STUDY.md`
   `docs/QWEN2B_QUANT_STUDY.md` §6.1) is a reason to expect it to cost something.

   > **DATED NOTE (2026-08-25, Track P).** The **580 is confirmed exactly** —
   > but only for the *write-combined* form, and the sentence "two state rows
   > pack into one 2048-bit URAM row" needs a mechanism this section did not
   > state. A 1024-bit write of a 2048-bit row cannot be expressed per
   > URAM288, because 1024 is not a multiple of 72 and the half-row boundary
   > falls inside URAM #14. Packing therefore needs a **write-combining
   > register** (legal because `dn_step` drives `s_wraddr` ascending within
   > each pass, starting even and ending odd — `rtl/dn_step.sv:262`, `:226`,
   > `:224`, `:234`, LDK = 128). **Without** the combiner the array does
   > **not** leave URAM as one might assume — it costs **592** (each half
   > mapped to its own 15-URAM slice, 30 per bank), which is also what the
   > un-packed 24 × 4096 × 1024b mapping costs. So 580 is the floor and 592 is
   > the price of not being clever; on this evidence 592 is the better trade.
   > **"three SLRs → two" landed as three total, two for the DN state**: the
   > DN banks occupy SLR0+SLR1 (112 + 236 = 348) and the unconstrained placer
   > put the KV array in SLR2. 348 + 232 = 580 ≤ 640, so two SLRs is
   > arithmetically available — but it needs a floorplan, which was not tried.
   > Measured WNS for the packed form: **−0.594** (Default directive),
   > **−0.119** (`AltSpreadLogic_medium`).
   > `evidence/qwen_next/place_exp/PLACE_EXP.md`.
2. **Spill the DN state to DDR.** The state is touched once per token per
   layer, so streaming it costs 2× its size in traffic: **48.0 MiB/token
   against 4,104 MiB of 4B W8 weights — 1.2 %** (0.6 % at 9B W8, 2.3 % at 4B
   W4). The *bandwidth* is nearly free; the cost is a new DMA path in
   `dn_step`/`layer_chan` plus a state-coherency protocol, which is a large RTL
   project.

### 2.8 Walls 9–11 — three NEW field walls the 2B list does not cover

* **`kvhead` is ONE bit.** `rtl/layer_chan.sv:786` `logic kvhead_r;`, dispatched  <!--cites:noquote-->
  at `:892` `kvhead_r <= arg0[0];` (KVAP `:106`, ATTN `:108`), and the KV write
  address at `:1332-1333` is `{kvhead_r, rnd, tcnt[8:0]}` inside an 11-bit
  `kv_waddr` (`:464`). **`num_key_value_heads` 2 → 4 needs two bits**, and the
  12-bit in-bank URAM address (`:469`) has no spare — KV capacity per bank must
  double or `T` must halve. This is not on the 2B list because kv=2 never moved.
* **`dn_head` is FOUR bits** (`rtl/layer_chan.sv:610`, `:1275`) and `gate_unit`
  is hard-parameterized `NH = 16` (`rtl/gate_unit.sv:13`, instantiated without
  override at `rtl/layer_chan.sv:501-502`, `w_addr` 4-bit at
  `rtl/gate_unit.sv:27`), with 16/32/16 literals in the GATE load path
  (`rtl/layer_chan.sv:1432`, `:1703`, `:1708`, `:1713`) and a 32-element store
  bound at `:1169`. **32 value heads need five bits and NH = 32.**
* **ONE of the CONV count fields is over by exactly one — not both, and the
  distinction matters.** Both are 13-bit, max 8191, against `CONV_DIM = 8192`:
  * `rtl/layer_chan.sv:1803` `if (cvi == arg0[25:13])` compares **before**  <!--cites:noquote-->
    incrementing, so it needs the literal value 8192 in the field and
    **genuinely cannot express it**. This one is the wall.
  * `rtl/layer_chan.sv:1850` `if (wi + 1'b1 == arg0[27:15])` and `:1866`  <!--cites:noquote-->
    (the CONVW twin) compare `wi + 1` in **13-bit arithmetic**, so at
    `wi = 8191` the sum **wraps to 0** and a field value of **0 already
    encodes 8192** — an unspent escape, precisely the trick
    `ref/gen_layer_script.py:521-525` documents for VNW's `ld_n`. No change
    needed there beyond making the encoding deliberate and asserted.

  The *address* fields (`arg0[12:0]`, `cw_ra` 13 b) reach 8191 and are fine.
  The 6144-deep `wm`/`sm` memories must grow to 8192 in the same change.

### 2.9 Walls 12–15 — the host and reference model

* **Multi-shard checkpoints are refused.** `ref/load_qwen35.py:91-95` handles a
  single file; 4B has 2 shards, 9B has 4. Small, but it is the first thing that
  fails.
* **The untied head is nearly free.** The head image is **already** a wholly
  separate artifact — a different file (`..._w186.bin` vs `.emb.bin`), a
  different DDR region (`W_BASE` vs `EMB_BASE`), a different layout
  (chunk-interleaved W4/W8 rows vs a flat int16 table), and a different
  hardware read path (matvec MVGO vs `OP_EMB`'s shift). `RD_GATE.md` §4.2 is
  hardware evidence: the head went **61.3 MiB stale** (`RD_GATE.md:405`,
  `:407-408`) while nothing re-uploaded or damaged the embedding table.
  *Inference, not proof, on the embedding half:* §4.2 never states the table's
  condition, and the only residency evidence for it is T12's **8 sampled 4 KiB
  blocks of 970 MiB** (`RD_GATE.md:230`). The delta is one variable assignment repeated at
  ~6 producer sites (`ref/gen_model_script.py:499`, `ref/seq_chat.py:1262-1265`,
  `sw/infer.py:695-696`, `ref/fidelity_check.py`, `ref/perplexity_eval.py:635`,
  `ref/audit_ranges.py:493`), plus the loader branch, plus one `isinstance`
  filter in `ref/calib_stats.py:276-283` where an untied `nn.Linear` head would
  collide with `HEAD_KEY`. **No RTL, no new wid, no new DDR region, and zero
  extra bytes on the board** — the 0.8B and 2B already pay for both copies. It
  is regression-covered today: `ref/gen_token_script.py:154-159` already draws
  the head and the table as two independent random matrices, and every
  `token_s*` TB runs that untied pair through the whole chain.
* **`ref/layer_ref.py:38` and `ref/scripts/bytes_per_token.py:110-111` assume
  key heads == value heads** —
  `LKD = LNH * LDK` with `LNH = linear_num_value_heads`. True at 0.8B/2B,
  **false at 4B/9B**, where it computes `CONV_DIM = 12288` against the
  checkpoint's **8192**. A silent geometry error in the reference model, found
  only because this study read the tensor shapes.
* **The SCA scalar tiles collide at 32 heads.** `ref/gen_layer_script.py:84-93`
  places `B16` (LNH words) at +0, `A16` (2·LNH) at +32 and `GD` (2·LNH) at +64
  on hard 32-word strides. At LNH=16 `A16` and `GD` fill their 32-word slots
  exactly while `B16` uses 16 of its 32; at **LNH=32,
  `A16` needs 64 words in a 32-word slot** and overruns `GD`, which overruns
  `QN`. `SCA_SZ` must go 992 → 1056 (and `STG = SCA + 1024` with it).

### 2.10 Wall 17 — TB/BFM and host-model geometry rot (the walls-7/8 class)

> ### PRE-G3.3 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 9)
>
> Rows here marked `<!--cites:noquote-->` quote **source that G3.3 DELETED**,
> not source that merely moved: the TB twins' 1536-word `MAXX`/`NX`, their 11-bit `x_waddr`/`xptr` and the `0x4000-0x57FF` window maps.  They are kept verbatim, because they
> are the record of what the pre-G3.3 tree said and the argument they support
> rests on them (§0: nothing is deleted or struck).  The exemption marker is
> used for exactly the reason §7.6 gives — *"an exemption is for source that
> no longer exists, not for a citation that has merely moved"* — and every
> citation that had merely MOVED was RENUMBERED instead, mechanically, by
> `evidence/qwen9b/o3/o3_cite_drift.py --base a08a90b`.
> **The post-G3.3 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_3_MATVEC.md` §11.1.**

The 2B campaign's hardest-to-find bugs were the *host model of the chip*, not
the chip. The same class is already sitting in the tree, and some of it is
**already wrong at 2B**:

| site | literal | what breaks |
|---|---|---|
| ~~`ref/seq_chat.py:993`, `:994`, `:1273`, `:1274` (and `:1275` `vocab = nrow`)~~ **FIXED 2026-08-25** | `// 2048`, `.reshape(n, 1024)` | **silent** — `//2048` and `1024` are mutually consistent, so `n*1024` always equals `V*H` and the reshape **never raises**; every `emb[tok]` returns a fragment of the wrong token's row, and `vocab = nrow` becomes 2.5×/4× too large. Offline paths (`--a1`/`--a3`) only |
| ~~`ref/seq_chat.py:1320-1323`~~ **FIXED 2026-08-25** | `1024` ×4 | truncated `ln_f` load, wrong RMSNorm denominator, wrong DYNQ8 exponent — ~~five~~ **13** lines after `:1307` correctly uses `LR.H` |
| **`sw/infer.py:798-802`** | `1024` ×4 (`:798`, `:799`, `:800`, `:802`) | the **online** `step()` — commands the chip to normalize only the first 1024 words of an H-word residual, then crashes in `matvec_y32`'s reshape |
| `sw/chat_seq.py:2360` / `:237` | `HEAD_WID = 186` | at 32 layers the head is a **different wid** (249 images); `:599` derives it correctly but the online call uses the literal |
| `sw/chat_seq.py:314` | `X8_WORD, X8_LEN = 0x800, 1024` | default args of `read_x8_eout` |
| `ref/load_qwen35.py:358,360` | `== 24`, `range(24)` | 32 layers |
| `ref/gen_token_script.py:79` | `DN_SLOTS, KV_SLOTS = 18, 6` | 24 / 8 |
| `ref/gen_layer_script.py:918` | `assert (1 << nlog2) == n` | **H=2560 fails at emit** — the ref-side twin of wall 2 |
| `tb/tb_matvec.sv:66`, `tb_matvec_chan.sv:14`, `tb_mvshim_b.sv:43` | `MAXX/NX = 1536` | K=FFN needs 2304 / 3072 |  <!--cites:noquote-->
| `tb/seq_stub_mvchan.sv:118` | `logic [10:0] xptr;` | K > 8192 int8 wraps |  <!--cites:noquote-->
| `tb/tb_layer_chan.sv:419` | `EMB_N_MAX = 4096` | exactly at the 9B ceiling |
| ~~`tb/scripts/gen_seq_vectors.py:62`~~ **SUPERSEDED 2026-08-31** | ~~`EMB_ROW_BYTES = 2048`~~ | **NOT A MIGRATION SITE — the file was DEAD and G2a DELETED it.** `tb/Makefile` named it in one comment (`tb/Makefile:289`) and never invoked it; it was a stale near-copy of the live `tb/scripts/gen_seq_unit_vectors.py`, which is where this row's fix actually belongs (its own `EMB_ROW_LOG2 = 11`, owned by G3). Following this row would have sent someone to fix a file no test runs. See the 9B spec's §7.5 E and its D-DEAD register row |
| `sw/head_cache.py:669` | `== (248320, 1024, -4, 5, 128)` | selftest fails at any H≠1024 |

The correct, already-parameterized template lives at
`ref/gen_model_script.py:590-595`. Two of these (`ref/seq_chat.py`'s emb
reshape, `sw/infer.py`'s online `step`) are **live defects on main today** and
should be fixed regardless of which target is picked — the first is exactly the
"answers with the wrong token and no error anywhere" failure mode `RD_GATE.md`
§4.2 caught once already.

> **Dated note, 2026-08-25 (Track F, `2a50cac` `22f7ca8` `d999a54`).** Both
> `ref/seq_chat.py` rows above are **fixed on main**: the row stride comes
> from `<base>.weights.json`'s `emb_row_bytes` (cross-checked against `2*LR.H`
> *and* the config's `vocab_size`), and the `:1260-1263` literals are `LR.H`.
> `seq_chat --emb-geom` is the regression; `--selftest` runs it once per
> `model_select.MODELS` entry. Evidence, including a deliberate-damage test
> that fails on the pre-fix reader: `evidence/qwen_next/defect_a/`.
> Two corrections to this table's *neighbourhood*, both dated there
> (`CORRECTIONS.md`): (i) "**2.5×/4× too large**" above is **exactly right**,
> and a first-round fix note that claimed the pre-fix reshape *raises* at
> H=2560 was wrong — 248,320 is even, so `V·H` is a multiple of 1024 at every
> even H and the reshape is legal and silent at **all four** geometries;
> (ii) `ref/gen_layer_script.py:918`'s row is confirmed and there is a second
> one beside it — `:476`'s `assert 1 <= n <= 2048` fails at **both** 2560 and
> 4096, so `layer_fixed_greedy` will refuse to run at 4B *and* 9B, loudly.
>
> **Citation rot warning:** every `ref/seq_chat.py:NNN` in this document is a
> **pre-fix** line number and the fix moved them. Current landmarks:
> `_artifacts`'s table read `:1045`, `layer_fixed_greedy`'s `:1321`, the head
> quantization `:1311`, `M.embed(tok, GLS.X0, LR.H)` `:1353`, the once-`1024`
> normalizer `:1373`. Other files' citations are unaffected.

> **A standing hazard behind all of §2**, worth stating once: **almost every
> envelope guard in the RTL is `` `ifndef SYNTHESIS `` sim-only.** There are no
> hardware range checks on scratch windows, `cfg_ng` or `cfg_nlog2`. On silicon
> an out-of-envelope command wraps, aliases, or hangs — it does not report.

---

## 3. DDR fit (**D**, `f04`)

`evidence/qwen_next/feas/ddr_fit.py` runs the shipped
`sw/hwmap.py:plan_weights` (`:326`) — including R-c's per-channel repack via
its `rows_of` parameter, fed with the LM head's `ilv_chunks` interleave from
`ref/seq_format.py:1214` — on synthetic manifests. Two
validations gate it: the **2B W8 row reproduces the committed
`1,936,920,576` bytes/token and the `464.8 MiB` chan-0 usage exactly** — the
same quantity `RD_GATE.md:220` records on silicon as top `0x2d0c4000` (f04
prints MiB, not the hex) — and
**every image is cross-checked against the checkpoint's own per-class parameter
count** (7 classes × 3 models, all OK, including the 9B's untied head at
1,017,118,720).

Window is `EMB_BASE − W_BASE = 1,280 MiB` per channel (`sw/hwmap.py:408`,
`:411`); the fit assert is `sw/hwmap.py:690-698`.

> **One encoding disclosed rather than buried.** `ref/scripts/bytes_per_token.py:110-111`
> carries the same `LKD = LNVH · LDK` assumption §2.9 reports for
> `ref/layer_ref.py:38`, so at 4B/9B it would compute `CONV_DIM = 12288`
> against the checkpoint's 8192. `ddr_fit.py` routes around it by passing
> `linear_key_head_dim = (16·128)/32 = 64`, which reproduces the true *total*
> key width — the only thing the tool uses LKD for. That is a workaround, and
> the reason it is safe rather than convenient is the per-class parameter
> cross-check above, which would fail if the image list did not describe the
> real checkpoint. It is stated here so nobody re-derives it as a bug.

| map | model | images | bytes/token | MiB | b/w | nch=1 | **busiest chan (nch=4)** | % window | verdict |
|---|---|---|---|---|---|---|---|---|---|
| **W8 g128** | 2B | 187 | 1,936,920,576 | 1,847.2 | 8.237 | 144.3 % | 464.8 MiB | 36.3 % | PASS |
| | **4B** | **249** | **4,303,618,048** | **4,104.2** | 8.188 | 320.7 % | **1,029.8 MiB** | **80.4 %** | **PASS** |
| | **9B** | **249** | **8,059,617,280** | **7,686.2** | 8.125 | 600.5 % | **1,927.3 MiB** | **150.6 %** | **REFUSED** |
| **W4 g128** | 2B | 187 | 996,282,368 | 950.1 | 4.237 | 74.2 % | 239.1 MiB | 18.7 % | PASS |
| | **4B** | 249 | **2,201,223,168** | 2,099.2 | 4.188 | 164.0 % | **526.7 MiB** | **41.1 %** | **PASS** |
| | **9B** | 249 | **4,091,805,696** | 3,902.2 | 4.125 | 304.9 % | **978.6 MiB** | **76.5 %** | **PASS** |
| **W4 g64** | **4B** | 249 | 2,294,808,576 | 2,188.5 | 4.366 | 171.0 % | 549.1 MiB | 42.9 % | PASS |
| | **9B** | 249 | 4,215,799,808 | 4,020.5 | 4.250 | 314.1 % | 1,008.2 MiB | 78.8 % | PASS |

Per-channel spread is small and comes from `split_rows`' uneven quarters plus
the head's 2048-row interleave: 4B W8 is `1029.8 / 1025.9 / 1024.6 / 1024.6`
MiB. An independent re-implementation of the packing agrees with `plan_weights` on
every row it is asked to place — **with one gap worth naming: the 9B W8 row is
the refused one, so `plan_weights` never placed it and `f04` reports its
cross-check as `None`, not `True`.** Its footprint comes from the
re-implementation alone.

> **Two nearly-equal MiB figures, deliberately kept apart.** The
> "busiest chan" column here is the **packed footprint** — what `plan_weights`
> reserves, with each image start rounded up to `WID_ALIGN` = 4096 B. §4.4's
> "busiest MiB" is the **streamed** byte count, which is what the engine
> actually reads and therefore what the throughput model uses. At 4B W8 they
> are 1,029.8 and 1,029.6 MiB; at 9B W8, 1,927.3 and 1,927.1. The same
> distinction exists in the 2B record (1,847.3 packed vs 1,847.2 streamed).

### 3.1 Embedding tables

| model | packed row | packed table | padded row | padded table | waste |
|---|---|---|---|---|---|
| 2B | 4096 B | 970.0 MiB | — | — | — |
| **4B** | **5120 B** (rejected) | 1,212.5 MiB | **8192 B** | **1,940.0 MiB** | **+727.5 MiB (+60 %)** |
| **9B** | **8192 B** | **1,940.0 MiB** | — | — | — |

Channel-0 totals with the padded 4B table: **3,225.6 MiB of 4,096 (78.7 %)** at
W8, 2,722.6 MiB (66.5 %) at W4. Both fit.

### 3.2 The 9B W8 refusal is an address-map limit, not a capacity limit (**D**, `f06`)

| model | map | weights | emb | sum | of 16 GiB |
|---|---|---|---|---|---|
| 4B | W8 | 4,104.2 MiB | 1,940.0 | 6,044.2 | **36.9 %** |
| **9B** | **W8** | 7,686.2 MiB | 1,940.0 | **9,626.2** | **58.8 %** |
| 9B | W4 g128 | 3,902.2 MiB | 1,940.0 | 5,842.2 | 35.7 % |

The board holds it. What refuses it is that `EMB_BASE` is a **compile-time host
constant on every channel**, so the window is 1,280 MiB even on the three
channels that have no embedding table. The hardware already takes the
embedding base from the EMB record itself (`rtl/seq_unit.sv:934-935`), so this
is host/emitter work — which is what `plan_weights`' own assert message says:
*"move EMB_BASE or split the images across DDR channels"* (`sw/hwmap.py:820`).

Making `EMB_BASE` a per-channel runtime value placed **above** the pack gives
the emb-hosting channel **1,900 MiB** of weight room — that is
`4,096 − 256 (W_BASE, `sw/hwmap.py:408`) − 1,940 (the table)` — and the other
three **3,840 MiB** (`4,096 − 256`). The balanced **1,921.6 MiB/chan does not
fit the hosting channel**, so it caps at 1,900 and the other three take
1,928.8 — a **matvec-term penalty of ×1.0008**. On the *step* that is
181.545 → 181.645 ms, i.e. **0.055 %**. Simply splitting asymmetrically
*without* moving `EMB_BASE` does not work: the assert is per-channel and
uniform, and the other three would need 2,135 MiB against the same 1,280
ceiling.

> **The ceiling this exposes, which the "58.8 % of 16 GiB" row hides.** 1,900
> MiB is a **hard ceiling on one channel**, not an allocation, and the
> balanced requirement is 1,921.6 — **101.1 % of it**. Option B works only
> because the *other* three channels absorb the difference, and it leaves that
> channel at **exactly 100.0 % full**: 256 + 1,900 + 1,940 = 4,096 MiB. There
> is **zero** slack on the embedding channel at 9B W8. Any growth in the
> embedding table, the SEQ blob or the weight pack breaks it, and the
> whole-board 58.8 % figure gives no warning of that.

> **9B W8 is a host address-map change worth 0.055 % of throughput, not a
> capacity failure** — with the zero-slack caveat above attached. That is a
> materially different verdict from "does not fit", and it is the one the
> decision table carries.

*(The 181.545 here and §4.4's 181.5 are the same quantity at different
precision; `f06` prints 181.54/181.64 from a slightly different rounding of the
same inputs. Nothing downstream turns on the third decimal.)*

---

## 4. Modelled tok/s (**E**, `f05`)

### 4.1 The model, and where each term comes from

```
step_ms  =  busiest_channel_beats · r / f_ui   +   movers_counted · m   +   layer
```

This is the step decomposition `evidence/qwen2b/ra/MOVER_NORM.md` uses, with
one addition. **It is assembled here, not quoted**: MOVER_NORM's own "cost law"
is §1's per-RECORD law; §3.1 gives the three-bucket split, §3.2 the identity
over the measured step, and §3.3 the numeric components. The symbolic line
above is this study's synthesis of those three. Term by term:

* **matvec (D).** Counted beats from the per-channel split this study computes
  with the shipped allocator, times a DDR rate `r` in ui-cycles per 64 B beat.
  The **busiest** channel is what a FENCE exposes (§3.1 of MOVER_NORM), so the
  max is used, not the mean.
* **movers (D).** Counted work × MOVER_NORM §1's per-row costs, whose
  **rates are RTL-exact and whose per-record residues are fitted from one
  measured donor per class** (§1: *"the rate falls out of the RTL exactly … and
  the residue is a per-record fixed cost"*) —
  MOVX 1.00 cyc/int8 +121/rec, MOVY 1.00 cyc/row int16 +137, 2.00 cyc/row
  pairs32 +163, LDC 1.00 cyc/word +595, CSRWR/CMD 16.99, MVGO config 84.95).
  The counters are re-derived here from geometry and reproduce **12 of 12** of
  MOVER_NORM §2's counted 0.8B nch=4 quantities, plus its busiest-channel beat
  count (1,643,280) and its bytes/token (417,435,648). The small CSRWR/CMD
  terms are *scaled* by image count, not counted — ~0.9 ms, flagged.
* **layer (M at two points, E beyond them).** `evidence/qwen2b/rd/RD_GATE.md`
  §3: **15.128 ms/token at 0.8B and 17.960 at 2B**, same `L_LCYC` accumulator,
  same board, same bitstream.
* **`m`, the overlap factor (D, new here).** R-d re-measured the layer term
  *upward* (MOVER_NORM used build_033's 14.130). With that term a **serial** sum
  over-predicts the 0.8B step — which is direct evidence for what MOVER_NORM
  §3.2 named as the one real modelling gap at nch=4 — and closed *for its own
  purpose* with a bracket that is an identity over the measured step, which is
  why it did not need to quantify the overlap: at nch=4, with no-wait MVGO
  and 217 FENCEs per token, some mover work hides under engine time.

### 4.2 The two unknowns come out of the two silicon steps — and the validation this study first claimed for them is WITHDRAWN

Solving `(r, m)` from the 0.8B W4 and 2B W8 measured steps — nothing else
fitted, neither variable constrained:

```
0.8B W4:  5.4754·r  + 11.332·m + 15.128 = 31.5023      (measured, RD_GATE §1/§3)
2B   W8: 25.3651·r  + 15.969·m + 17.960 = 60.5145
=>  r = 1.1037 ui-cyc/beat = 17.40 GB/s/chan
    m = 0.9117  (8.8 % of counted mover work overlaps engine time)
```

`m` lands inside `[0, 1]`, as an overlap must, and `r` above 1.000, which is
the engine's hard floor. Neither was constrained. But **that is a sanity check,
not a validation, and the validation an earlier revision claimed here is
withdrawn** (`f05`, HONESTY CHECK 1):

> **RETRACTED: "r lands inside MOVER_NORM's calibration-free bracket."**
> MOVER_NORM §3.2(b) derives `r ≤ 1.131` from
> `45.018 = 14.13 + matvec_1 + movers_1` with `movers_1 ≥ 6.308`. **The 14.13
> is build_033's layer term, which R-d supersedes with 15.128** (`RD_GATE.md`
> §3) — the same re-measurement this study leans on everywhere else. Re-running
> that identical inequality with 15.128 gives `matvec_1 ≤ 23.582 ms` and
> **`r ≤ 1.0851`**. This study's `r = 1.1037` is therefore **OUTSIDE the
> re-anchored bracket by 1.7 %**. The earlier claim was true only against the
> bracket's own superseded anchor.
>
> MOVER_NORM is candid about the softness of its point estimate too
> (`:161-165`): `r = 1.0892` rests on a bubble figure of **8.252** where the
> repo's other figure is **8.94** (`evidence/rung3/CENSUS.md:33`), and "8 % on
> the bubble moves `r` 7 %" — to 1.013. So neither the bracket nor 1.0892 is a
> hard rail, and this study does not treat either as one.

**Is there a validation that survives? Only a failing one, and it is reported
rather than dropped.** The `(r, m)` pair is *exactly determined* by two nch=4
equations, so it has no residual at those points and cannot be validated by
them. The one out-of-sample configuration available is **nch=1**, which nothing
here was fitted to (`f05`, HONESTY CHECK 2):

| | predicted step | measured (`RD_GATE` §1) | error |
|---|---|---|---|
| at `m = 1.000` (MOVER_NORM: "at nch=1 nothing overlaps") | 46.422 ms | **45.018 ms** | **+3.1 %** |
| at `m = 0.9117` (this study's nch=4 solve) | 45.776 ms | **45.018 ms** | **+1.7 %** |

The counters themselves are sound — they reproduce MOVER_NORM's nch=1 busiest
beats **exactly** (6,522,432) and its mover total to 0.2 % (7.306 vs 7.293) —
so the miss is in the *model*, not the census. **Consequence, carried into §7
and §8: the absolute tok/s figures below inherit a few per cent of unmodelled
configuration dependence on top of the layer allowance, and the relative
4B-vs-9B comparison — which shares `r`, `m` and the mover law — is much the
sounder of the two.**

### 4.3 The layer term — one figure, not a bracket, and why the optimistic end is gone

> **RETRACTED: the "LOW" layer bracket.** An earlier revision offered
> 4B 27.73 ms / 9B 32.76 ms on the assumption that *"the lane array already
> absorbs 32 value heads in the cycles it spends on 16, so the state term
> scales with DN layers only."* **The as-built RTL refutes that outright, and
> the assumption had no physical basis at any point.** It is deleted, not
> re-tuned, and every tok/s figure in this study revises downward to what were
> its pessimistic ends.

The DeltaNet recurrence is **serialized over heads through a single engine**:

| primary source | what it says |
|---|---|
| `rtl/dn_step.sv:1` | *"one gated-delta-rule recurrence step for **ONE head**"* |
| `rtl/dn_step.sv:13-14` | *"**128 parallel lanes**; lane math is pipelined … **~1300 cycles/head**"* |
| `rtl/layer_chan.sv:525` | **one** `dn_step u_dn (…)` instance in the whole design |
| `rtl/layer_chan.sv:1275` | `dn_head <= arg0[3:0];` — the head is a per-**command** dispatch argument |  <!--cites:noquote-->
| `ref/gen_layer_script.py:1129-1136` | `for h in range(LR.LNH):` emitting `vn` / `alu` / `vn` / `dnst` **per head** |

Heads are the **outer** loop, and the 128-lane array is already fully occupied
(128 lanes across `LDK = 128` rows). There is no idle width for 32 heads to
hide in. **The command census of the real 0.8B stream confirms the count
exactly** (`f16`, `tb/scripts/model_v2_s1.txt` — gitignored but byte-locked by
`ref/scripts/regen_gate.sh:41`, §0): **288 DNST commands per token = 18 DN
layers × 16 heads**, and 576 length-128 `VN` commands = 18 × 16 × 2. At
4B/9B the same structure gives **768 = 24 × 32**, a **2.667×** serial increase.
At the RTL's own ~1300 cycles/head and 250 MHz, that bucket alone is
**1.498 ms/token** at 0.8B/2B and **3.994 ms/token** at 4B/9B.

The model therefore fits two components to the two measured layer terms:

* **head-indexed work** ∝ `n_DN · LNVH` (the DeltaNet recurrence and its
  per-head norms) plus the causal conv ∝ `n_DN · CONV_DIM` — none of it
  depends on hidden size;
* **width work** = two RMSNorms, two residual adds and the SwiGLU pair per
  layer, plus the final norm.

At 0.8B that splits **11.670 ms head-indexed (77.1 %) / 3.458 ms width
(22.9 %)** — which is *why* doubling H at the 2B moved the layer term only
+18.7 %.

> **Read that 77.1 % as a FIT INTERCEPT, not as a measured cost.** Both
> calibration points share DeltaNet geometry, so the head-indexed coefficient
> is simply *whatever is left* once the width term explains the 0.8B→2B
> difference. Nothing measured the DeltaNet contribution directly. What **is**
> primary-source is its **scaling law** — the table above — and that is the
> part the extrapolation turns on. For scale, the DNST commands alone account
> for 1.498 of the 11.670 ms (12.8 %) at 0.8B; the rest of the intercept is
> the per-head norms, the conv, and anything else geometry-invariant.

**The result: one figure per target, with a stated allowance.**

| | 4B | 9B |
|---|---|---|
| **layer term** | **41.92 ms** | **47.00 ms** |
| spread over three width-scaling laws (H-only / FFN-only / mixed) | 41.29 – 42.51 | 46.96 – 47.04 |
| **± 10 % allowance** (no measurement has ever varied the DeltaNet geometry) | **37.73 – 46.11** | **42.30 – 51.70** |

The three width laws barely move it, which is the point: the term is dominated
by head-indexed work whose scaling is known. The **± 10 %** is the honest band
and it is an assumption, not a derivation.

> **The calibration datum, carried as the task requires:** the 2B study's
> geometry scaling projected +23.1 % on the layer ratio and silicon measured
> +18.7 %. `RD_GATE.md` §3 states that as **−3.6 % on the ratio**
> (1.1872 / 1.2314); the reciprocal, **1.2314 / 1.1872 = 1.0372, i.e. 3.7 %
> hot**, is this document's arithmetic on those two numbers, not a quotation.
> This model is *fitted* to both points so it carries no error at them; the
> exposure is entirely in the head-indexed term, whose coefficient is an
> intercept even though its scaling law is not.

### 4.4 The projection

nch=4, steady-state convention (the session-once 8.671 ms preamble removed).

| map | model | MiB/token | busiest MiB | matvec | movers | layer | **step ms** | **tok/s** | tok/s at ±10 % layer |
|---|---|---|---|---|---|---|---|---|---|
| — | *2B W8* | *1,847.2* | *464.6* | *28.00* | *14.56* | *17.96* | ***60.51 (M)*** | ***16.52 (M)*** | *—* |
| **W8 g128** | **4B** | 4,104.2 | 1,029.6 | 62.04 | 24.93 | 41.92 | **128.89** | **7.76** | 7.51 – 8.02 |
| | **9B** | 7,686.2 | 1,927.1 | 116.12 | 32.66 | 47.00 | **195.78** | **5.11** | 4.99 – 5.23 |
| **W4 g128** | **4B** | 2,099.2 | 526.6 | 31.73 | 24.93 | 41.92 | **98.59** | **10.14** | 9.73 – 10.59 |
| | **9B** | 3,902.2 | 978.4 | 58.95 | 32.66 | 47.00 | **138.61** | **7.21** | 6.98 – 7.47 |
| **W4 g64** | **4B** | 2,188.5 | 549.0 | 33.08 | 24.93 | 41.92 | **99.93** | **10.01** | 9.60 – 10.44 |
| | **9B** | 4,020.5 | 1,008.0 | 60.74 | 32.66 | 47.00 | **140.40** | **7.12** | 6.89 – 7.37 |

> **These are ~13 % below what an earlier revision's optimistic ends showed**,
> because that revision's LOW layer bracket is retracted in §4.3. The values
> here are the ones the decision table and §8 carry.

> **Where is the GPTQ row?** It is the **W4 g64 row**. GPTQ-lite changes the
> *values* in the image, not the wire format — `docs/QWEN2B_QUANT_STUDY.md` §7
> records V4gptq at "identical `row_stride`, identical 6.752534427466289
> bits/weight, identical 999,428,096 bytes/token" as plain W4 g64. Its whole
> price is build-side. So the throughput of a GPTQ variant at either target is
> the W4 g64 line above, exactly, and the build-side price is **`≈ 9.0 min`
> (4B) / `≈ 19.1 min` (9B)** of calibration plus a **10.1 / 21.4 GiB** Hessian
> file — snoke-anchored figures, §5.
>
> **One caveat that is new at these geometries**, from §2.5: GPTQ's g64 cadence
> makes `n_scale_beats` 5 (4B) or 6 (9B) against a 2-bit field, where W8 and
> W4 g128 both stay at 3 and fit. **"GPTQ costs the board nothing" was true at
> 2B and is not true here** — it is a small extra item inside `matvec_engine`,
> in the same change as wall 4, but it is no longer free.

Sweeping `r` across MOVER_NORM's original `[1.000, 1.131]` and re-solving `m`
on the 0.8B point alone moves 4B W8 from **8.03** tok/s (at `r = 1.000`) to
**7.69** (at `r = 1.131`), against the central **7.76** — i.e. **+3.5 % / −0.9 %**,
not symmetric — while mis-predicting the 2B step by at most −3.0 %. **The
DDR-rate uncertainty is not what dominates; the layer term is** (its ±10 %
allowance alone spans 7.51 – 8.02).

Where the time goes, at the central layer term:

| model | map | matvec | movers | layer |
|---|---|---|---|---|
| 2B | W8 | 46.3 % | 24.1 % | 29.7 % |
| **4B** | **W8** | 48.1 % | 19.3 % | **32.5 %** |
| **9B** | **W8** | **59.3 %** | 16.7 % | 24.0 % |
| **4B** | **W4 g128** | 32.2 % | 25.3 % | **42.5 %** |
| **9B** | **W4 g128** | 42.5 % | 23.6 % | 33.9 % |

The 9B at W8 is firmly DDR-bound; the 4B at W4 is layer-bound. That matters for
where a *subsequent* optimization rung would pay.

**9B W8 under the §3.2 address-map fix** costs ×1.0008 on the matvec term —
**5.11 tok/s, unchanged to two decimals** — with §3.2's zero-slack caveat on
the embedding channel attached.

---

## 5. Quantization-study scope

The Track-Q framework re-runs essentially unchanged, and that is the cheapest
good news in this study.

**What carries over unmodified:** the pinned corpus `ref/ppl_corpus_eval.txt`
(sha256 `6bf4f867…`) and its **24,528 scored positions** — because
`tokenizer.json`, `vocab.json` and `merges.txt` are byte-identical across all
four models (§1.4, **D**). `ref/perplexity_eval.py`, `ref/fidelity_check.py`,
`ref/w4a8_ref.py`'s W4/W8 wire law, `ref/gptq.py`, `ref/scripts/rank_sensitivity.py`
and `ref/audit_ranges.py` are all geometry-driven.

**What must be re-run** (nothing carries over as a *number* — a different
checkpoint is a different model): the bf16 anchor, the W4 g128 / g64 ladder,
the salience and GPTQ points, the W8 point, the per-class sensitivity scan, and
`audit_ranges` (the 2B found 15 of 187 matrices over the project's own 15 %
W4-error bound and the `dt_bias` gate-port overflow doubling — both are
*per-weight facts* that say nothing about a new checkpoint).

**What the bf16 anchors need: the full checkpoints on snoke.** Disk plan
(**M**, `f07`/`f09`): snoke has **94 GB free of 458 GB** (79 % used) and
**247 GB RAM / 48 threads**, with the HF cache at 6.8 GB holding the 0.8B
(1.7 G) and 2B (4.3 G) weights — plus 104 K / 108 K metadata-only stubs for 4B
and 9B, which are this study's own ranged header reads and hold no weights.

| item | 4B | 9B |
|---|---|---|
| bf16 checkpoint | **8.68 GiB** | **17.98 GiB** |
| W8 images + emb | 4,104 + 1,940 MiB ≈ **5.9 GiB** | 7,686 + 1,940 ≈ **9.4 GiB** |
| W4 images + emb | 2,099 + 1,940 MiB ≈ **3.9 GiB** | 3,902 + 1,940 ≈ **5.7 GiB** |
| GPTQ Hessian npz (optional) | **10.1 GiB** (2B's 4.5 GiB × 4.21/1.88) | **21.4 GiB** |
| **fidelity ladder alone** (checkpoint only) | **8.7 GiB** | **18.0 GiB** |
| **ladder + a W8 image set** | **14.6 GiB** | **27.4 GiB** |

Totals (`f17`): **both targets without GPTQ 42.0 GiB — 52.0 GB headroom**;
**both with GPTQ 73.4 GiB — 20.6 GB headroom** (42.0 + 10.1 + 21.4). One target
with GPTQ is 24.6 GiB (4B) or 48.8 GiB (9B).

**Recommendation on disk: one target at a time.** Either alone is comfortable;
both plus GPTQ leaves **~21 GB** of headroom on a shared machine that also runs
Vivado builds.

**Estimated compute (E) — repriced on SNOKE anchors only (`f17`).**

> **The earlier revision of this table was wrong, and the reason is worth
> naming.** Its anchors were `evidence/qwen2b/q1/ppl_2b_bf16.json` and
> `ppl_08b_bf16.json`, which carry `"torch": "2.6.0+cu124"` and **no `host`
> key** — darthplagueis CUDA runs. The committed snoke twin of the *same* 2B
> bf16 point (`ppl_2b_bf16_snoke.json`, `"host": "snoke"`, torch 2.12.0+cpu) is
> **2.814× slower**. Worse, the "18 min/variant" figure *mixed* a darthplagueis
> bf16 anchor with the snoke `ppl_v5.json` variant anchor. Since the campaign
> must run on snoke, every figure below is snoke-anchored:
>
> * bf16 anchor, 2B, snoke: build 45.914 + eval 404.930 = **450.844 s**
> * one **W8** variant, 2B, snoke (`ppl_v5.json`): build 114.605 + eval
>   462.589 = **577.194 s** (1.280× the anchor) — this is the "one variant"
>   column below, and only that; the ladder is priced separately
>
> **And a second, larger error the first repricing still carried.** It costed
> the ladder as *bf16 + 4 × V5*, but **V5 is the cheapest of the five points**,
> because W8 g128 is a straight per-group rescale while V1/V2 run an MSE grid
> search and V4gptq a full-Hessian pass. All five ran on snoke and are
> committed, so the ladder is priced from **the measured five**, not from one
> of them (`f17`):
>
> | point | build | eval | total | json |
> |---|---|---|---|---|
> | bf16 anchor | 45.914 | 404.930 | **450.844** | `q1/ppl_2b_bf16_snoke.json` |
> | V1 W4 g128 | 746.497 | 519.233 | **1,265.731** | `q2/v1_v2/ppl_v1_snoke.json` |
> | V2 W4 g64 | 768.159 | 543.597 | **1,311.756** | `q2/v1_v2/ppl_v2_snoke.json` |
> | V4gptq | 1,948.814 | 256.130 | **2,204.944** | `q2/v4/ppl_v4gptq.json` |
> | V5 W8 g128 | 114.605 | 462.589 | **577.194** | `q2/v4_v5/ppl_v5.json` |
> | **2B LADDER** | | | **5,810.5 s = 96.8 min** | |
>
> The **variant spread is 3.82×** (2,204.944 / 577.194), which is why anchoring
> on V5 ran **2.11× low**. *Caveat: the five ran at different thread counts
> (6/6/6/10/8), so 5,810.5 s is a real elapsed cost on this machine but not a
> controlled per-point comparison.*
>
> Scaling is **proportional to text-tower parameters** (2B 1,881,825,088; 4B
> 4,205,751,296; 9B 8,953,803,264 including its untied head — counts from
> `evidence/qwen2b/q0/checkpoint_verify.md` and §1.3, **not** from those jsons,
> whose `total_weights` counts the whole file). **Five snoke points at ONE
> geometry still cannot measure an intercept ACROSS geometries** — that needs a
> second geometry on snoke, which does not exist — and the darthplagueis pair
> implies a large one, which would make the truth **sub**-linear. So
> proportional is an **upper bound** on the marginal cost, and that is the
> honest direction to err.

| | 4B (4.21 G text, ×2.235) | 9B (8.95 G text incl. head, ×4.758) |
|---|---|---|
| bf16 anchor (build + eval) | **16.8 min** | **35.8 min** |
| one quantized variant | **21.5 min** | **45.8 min** |
| **a 5-point ladder** (the measured 5,810.5 s scaled) | **3.61 h** | **7.68 h** |
| GPTQ calibration pass | 9.0 min | 19.1 min |
| DDR image build (`gen_model_script`) | 34.2 min | 1.21 h |
| peak RSS, float32 forward | 15.7 GB | 33.4 GB (of 247) |

**The one thing the study cannot promise:** the 2B's *fidelity* result. Public
data says W4 g128 damage shrinks monotonically with size
(`docs/QWEN2B_FEASIBILITY.md`), and the 2B measured W4 g64 + GPTQ at +4.82 %
PPL against W8's +0.12 %. At 4B/9B W4 should be *better* in relative terms —
which matters, because **9B cannot use W8 without the §3.2 address-map change
and 4B's W8 costs ~23 % of its throughput against W4** (7.76 against
10.14 tok/s). If W4 g64 + GPTQ holds up at these sizes, most of the W8
engine-mode cost disappears from both columns — though **not all of it**: §2.5
shows GPTQ's g64 cadence has its own `matvec_engine` item at these `ng`.
That is a measurement, and it is still the cheap one: **3.61 h of snoke time
at 4B** — against an RTL campaign this study puts at 2.5–3× the 2B's.

> **Sequencing note that follows from the above:** the fidelity ladder is the
> only part of this campaign that needs no RTL, no board and no address map. It
> could be run **before** any commitment, on either or both targets, at
> **3.61 h (4B) / 7.68 h (9B)** of snoke time plus the download — 2.11× the
> figure an earlier revision gave, and **the conclusion survives the
> correction**: a few hours of snoke against a multi-build RTL campaign. This document
> offers it as the highest information per hour available; see §8 for the four
> opinions this study does state, and the many it does not.

---

## 6. What this study did NOT establish

Stated because the 2B study's "(U)" list turned out to be its most useful
section.

1. **The layer term at a new DeltaNet geometry has no measurement.** Its
   *scaling law* is now primary-source (§4.3: one `dn_step`, one head per
   command, ~1300 cyc/head, and the 288-per-token census on the real stream),
   but its *coefficient* is a two-point fit intercept and the ±10 % allowance
   around it is an assumption. Every tok/s figure inherits that. Closing it
   properly means a `dn_step`/`layer_chan` simulation at LNH=32, which needs
   only Verilator — no board, no synthesis.
2. **The `(r, m)` solve does not survive its one out-of-sample test.** §4.2:
   it over-predicts the nch=1 step by 1.7–3.1 %, and `r = 1.1037` sits 1.7 %
   outside MOVER_NORM's bracket once that bracket is re-anchored on R-d's
   layer term. Absolute tok/s therefore carry a few per cent of unmodelled
   configuration dependence; the 4B-vs-9B *comparison* does not.
3. **No synthesis and no place-and-route run.** The 928-URAM figure is an
   inference from bank declarations, validated against build_035's measured
   348 — but whether the VU9P **places and routes** at 96.7 % URAM across
   three SLRs, on a design with zero timing margin and no pblocks on
   `layer_0`, is unknown and is the single biggest unpriced risk.
   **What each experiment can and cannot answer, stated precisely because an
   earlier revision over-promised one `synth_design`:**
   * `synth_design` alone answers **inference only** — that the widened banks
     map to 928 URAM primitives and not to something worse. It says nothing
     about placement. Cost: one synthesis run.
   * `place_design` is the **minimum** that answers the real question, because
     URAM columns are physical and the 320-per-SLR limit binds at placement.
     Cost: synthesis + placement, no routing.
   * The **sharp form of the question, which this study should have stated
     outright**: at 24 DN banks the 2048-bit bank-mux read path
     (`rtl/layer_chan.sv:562-575`, feeding `dn_rdq`) must cross **both** SLR
     boundaries on every access, because 928 URAM cannot fit in fewer than
     three SLRs and the mux has one destination. build_035's clean closure came
     from pblocks that deliberately left `layer_0` unconstrained
     (`NEXT_SESSION.md`, T5: constraining it *in any form* cost ~1 ns). A
     mandatory two-boundary crossing inside `layer_0` is a materially harder
     problem than the one that campaign solved.

> **DATED NOTE (2026-08-25, Track P — D3 WAS RUN).** This paragraph is now
> **measured**, and two of its statements are corrected. Evidence:
> `evidence/qwen_next/place_exp/PLACE_EXP.md`.
> * **The count is exact**: `synth_design -mode out_of_context` on the widened
>   `layer_chan` infers **928 URAM288**, zero DN banks falling out of URAM.
> * **`place_design` SUCCEEDS** — 928 URAM legalised at 312/312/304 of 320 per
>   SLR, no ERROR. So placement is no longer unknown. **Routing was NOT run**,
>   so the "and routes" half of this item's own question is still open.
> * **"must cross BOTH SLR boundaries on every access" is TOO STRONG.** The
>   placer centres the mux destination in the middle SLR, so any one access
>   crosses **at most one** boundary — all 30 worst paths are SLR0→SLR1, never
>   SLR0→SLR2. The *path family* spans both because the sources sit in all
>   three SLRs. The conclusion survives a fortiori: one crossing is already
>   **−1.848 ns** against 4.000, where the as-built 9-bank geometry **meets at
>   +0.211** in the identical flow.
> * **It is route, not logic.** Widening the mux 9→24 changed logic delay by
>   −0.06 ns and route delay by **+2.12 ns**.
> * **The named path is not the module's worst path.** `layer_chan`'s actual
>   post-place WNS endpoint at the wide geometry is the **write-control
>   fan-out** (`dnz_we_reg` → `mem_reg_uram_19/BWE_B`, route 5.477 of 5.682 ns),
>   at −2.103 ns. This item named the read mux; there are two SLR-spanning
>   problems, not one.
> * **And the read path is FIXABLE.** With two register stages on the crossings
>   — flip-flops only, ~1.0 % of the device, URAM unchanged — the named net
>   **MEETS at +0.097 ns under `AltSpreadLogic_medium`** (the same N=2 build at
>   the Default directive is −0.162, so the MET result carries a directive
>   dependency). The remaining blocker is the write fan-out, whose worst path
>   is one logic level and ~96 % route: a **floorplanning** problem, and no
>   floorplan was tried. **Its latency price is two-sided**: the N=1 structure
>   costs ~0.15 % but does not close (−0.339); the N=2 structure that reaches
>   MET needs a wait state in `dn_step`'s 5-state pass-2 loop (**≈ +10 %**) or
>   an unpriced two-outstanding restructure. So **this item does not sink
>   either target on its own**, and neither is "96.7 % works" supported. The
>   live URAM answer is still the int8 lever, because it is the one that is
>   *measured* closable (WNS −0.119).

4. **The scratch peaks are the allocator's algebra, not an empirical probe.**
   `evidence/qwen2b/ra/scratch_probe.log` ran a real high-water probe at 0.8B
   and 2B and confirmed `MEASURED == DERIVED`. That probe was never committed
   (it is reproduced verbatim in the log's appendix) and was not re-run here.
5. **No fidelity number exists for either target**, and none for the int8
   DN-state lever of §2.7 at any size.
6. **The MTP head is untouched.** It is a real full-width block at both targets
   (120.6 M / 243.3 M params) and remains a shipped-unused speculative-decode
   axis, orthogonal to everything here.
7. **Prefill was not modelled.** §4 is decode only. At these step times a
   batched-prefill rung becomes much more valuable than it was at 2B, and that
   is unquantified.
8. **The effort classes in §7 are directional.** They come from counted
   file:line sites, not from an implementation. The 2B study's own S/M/L table
   was flagged the same way and was right about ordering, not magnitude.
9. **The layer census rests on a gitignored input.** `tb/scripts/model_v2_s1.txt`
   is byte-locked by `ref/scripts/regen_gate.sh:41` and regenerates from a
   clean checkout (§0), so this is a *reproduction step*, not a hole — but
   anyone re-running `f16` must regenerate the stream first, and this study
   did not re-run the gate to prove the on-disk copy still matches.
10. **The campaign compute is scaled from ONE geometry.** §5's ladder is the
   measured 2B five-point total scaled proportionally by text-tower
   parameters. Its five points ran at **different thread counts (6/6/6/10/8)**,
   so the total is a real elapsed cost and not a controlled comparison, and
   proportional scaling ignores an intercept the darthplagueis pair suggests
   exists. It is an **upper bound**, deliberately.

---

## 7. THE DECISION TABLE

### 7.1 Side by side

| | **Qwen3.5-4B** | **Qwen3.5-9B** |
|---|---|---|
| geometry | H 2560 / FFN 9216 / 32 L (24 DN + 8 GQA) | H 4096 / FFN 12288 / 32 L (24 DN + 8 GQA) |
| head geometry | **16 NQ / 4 NKV / 16 key + 32 value DN heads** | **identical** |
| text params | 4.21 G | 7.94 G + 1.02 G untied head |
| embeddings | TIED | **UNTIED** (cheap — §2.9). The config guard passes **silently**; only the tensor guard refuses (§1.2) |
| checkpoint | 8.68 GiB, 2 shards | 17.98 GiB, 4 shards |
| **wall rows shared with the other target** | 13 of 17 | 13 of 17 |
| **scratch** (**D**) | **36,384 / 32,768** — ONE body over; a 2-way MLP chunk gives **24,608, spare 8,160**. **No ISA change.** ATTN margin only **+480 words** | **50,208 / 32,768** — ALL THREE bodies over. A 2-way MLP chunk is still **over by 1,056**; it takes 3-way. Realistically needs the **16-bit scratch ISA** (no 16th address bit exists anywhere in the arg words) |
| **vecnorm** (**D**) | **H=2560 is not a power of two** — expressible only by adding a **reciprocal multiply** to the normalizer datapath, a change with no precedent here | **H=4096 needs nlog2 12** — one more doubling of every width R-b widened once (counters 12→13 b, buffers 2048→4096, `w_waddr` 11→12 b, the `$fatal` moved). Precedented, **not** free |
| **embedding rows** | **5120 B rejected.** Pad to 8192 (+727.5 MiB, no RTL) or add non-pow2 addressing in a zero-margin timing path | **8192 B, clean — EMBLOG2 13**, at the CSR ceiling |
| ALU `cfg_len` (**D**) | 13 → 14 b, `arg0[17]` proven spare over **293,768** dispatches in the reproducible committed scope | same |
| matvec `ng` (**D**) | 48 → 72; 6-bit SHAPE field overflows; XWIN decode + `xptr`/`wb_ptr` widen | 48 → **96**; same, worse |
| **URAM** (**D**→**T**) | **928 / 960 = 96.7 %**, 3 SLRs — **synth + place now measured by the toolchain (T), routing still unproven, and the timing verdict is unresolved in BOTH directions** — see the §6 item 3 dated note | **identical** |
| BRAM | **858.5 / 2,160 = 39.7 %** (no scratch growth; doc-arithmetic on `f08`, §2.7) | **886.5 / 2,160 = 41.0 %** (**D**) |
| **DDR fit, W8** (**D**) | **80.4 % of window — PASS** | **150.6 % — REFUSED today**; a per-channel runtime `EMB_BASE` fixes it for **0.055 %** throughput, but leaves the embedding channel at **exactly 100.0 % full** (§3.2) |
| **DDR fit, W4 g128** | 41.1 % — PASS | 76.5 % — PASS |
| ch0 total (W8, padded emb) | 3,225.6 / 4,096 MiB (**78.7 %**) | 9,626 MiB across 4 ch (58.8 % of 16 GiB) — **but the embedding channel is at exactly 100.0 %** under the option-B map (§3.2), which the whole-board figure hides |
| **modelled tok/s, W8** (**E**) | **7.76** (7.51 – 8.02 at ±10 % layer) | **5.11** (4.99 – 5.23) |
| **modelled tok/s, W4 g128** (**E**) | **10.14** (9.73 – 10.59) | **7.21** (6.98 – 7.47) |
| vs the 2B's **measured** 16.52, at W8 | **0.47×** | **0.31×** |
| vs the 2B's **measured** 16.52, at W4 g128 | **0.61×** | **0.44×** |
| **vs each other**, same precision (doc-arithmetic on the row above) | **1.52× the 9B** at W8, **1.41×** at W4 g128 | **0.66× the 4B** at W8, **0.71×** at W4 g128 |
| bottleneck at W8 | layer 32.5 % / matvec 48.1 % | **matvec 59.3 %** — DDR-bound |
| chat template | must be re-derived (thinking default inverts) | same |
| quant ladder cost (**E**, measured-ladder anchor) | **3.61 h** snoke | **7.68 h** snoke |
| disk for the campaign | **14.6 GiB** ladder + W8 images | **27.4 GiB** |

### 7.2 Unique risks

**4B only**
1. **The non-power-of-two hidden size is a class of problem this project has
   never had.** It hits `vecnorm_unit` (the reciprocal is a shift), the EMB row
   shift, `ref/gen_layer_script.py:918`'s `assert (1 << nlog2) == n`, and every
   `nlog2` field in the ISA. The embedding side has a zero-RTL escape (pad); the
   **normalizer does not**.
2. **The 480-word ATTN scratch margin.** 4B fits the 32K scratchpad only with
   the MLP chunked — to **24,608**, not the 22,560 an earlier revision claimed,
   because the down-stage term binds (§2.2) — and then by **480 words** on the
   attention body, which chunking does not touch. Any later tile growth
   re-opens the ISA question.

**9B only**
1. **Three scratch bodies over the ceiling** means the 16-bit scratch ISA is
   effectively mandatory — a re-encoding of the layer command set, the AXI
   segment moved and re-aligned, and 2× the scratch BRAM. This is strictly
   larger than R-b's 15th-bit job, which had a spare bit waiting in every word;
   here **no 16th address bit exists anywhere in the arg words**. Note the
   two-way MLP chunk does **not** rescue it (33,824, over by 1,056) — it takes
   a three-way chunk *and* the DN and ATTN bodies still bust independently.
2. **DDR-bound at W8** (59.3 % of the step) *and* refused by today's address
   map, so W8 needs both the engine work and the host re-map to be worth having.
3. **Twice the checkpoint, twice the campaign compute**, on a machine that also
   runs Vivado.

**Shared, and larger than either**
1. **URAM at 96.7 %.** Unpriced by synthesis *and* by placement, on a design
   that closes at WNS 0.000 with no pblocks on `layer_0` and a recorded ~1 ns
   penalty for constraining it at all. **The sharp form:** 928 URAM cannot fit
   in fewer than three SLRs (320 each), so at 24 DN banks the 2048-bit
   bank-mux read path into `dn_rdq` must cross **both** SLR boundaries on every
   access — inside the one block the successful floorplan campaign had to leave
   unconstrained. If this does not place, neither target proceeds without the
   int8-state lever (→ 60.4 %, two SLRs) or the DDR-spill path.

   > **DATED NOTE (2026-08-25, Track P).** Measured. It **places** (928 URAM,
   > 312/312/304 per SLR); it **fails timing** at the as-built read-path
   > structure (−1.848 ns on the named net, vs +0.211 for the as-built
   > geometry in the identical flow) — but **pipelining the crossings takes
   > that net to +0.097 MET** (N=2 under `AltSpreadLogic_medium`; −0.162 at the
   > Default directive) for flip-flops only, so this risk does **not** sink
   > either target on its own. What then binds is the write fan-out, a
   > floorplanning problem that was not attempted. The N=2 latency also costs
   > ≈ +10 % naively (or an unpriced restructure); N=1 costs ~0.15 % but does
   > not close. "**both** SLR boundaries on every access"
   > is **too strong** — at most one per access (see the §6 item 3 note). The
   > module's worst endpoint is not this net but the **write-control fan-out**
   > at −2.103 ns. The int8-state lever is measured LIVE: **580 URAM** with the
   > write combiner, WNS **−0.119** under `AltSpreadLogic_medium`. Routing was
   > never run. `evidence/qwen_next/place_exp/PLACE_EXP.md`.
2. **`matvec_engine` timing re-opens** for wall 4, in the block that owned
   build_034's worst 22 endpoints (24 of 50), on the first bitstream in project history
   that needed no waiver — and it is a *bigger* change than the W8 mode was.
3. **Two live host-model defects on main, and they are NOT the same severity —
   an earlier revision blurred them:** *(as of 2026-08-25: **A is fixed**, B
   is not — see the dated note below this list)*
   * **A (silent, and already wrong at 2B — FIXED 2026-08-25):
     `ref/seq_chat.py`'s embedding reshape.** `// 2048` and `.reshape(n, 1024)` are mutually consistent, so
     `n·1024` always equals `V·H` and **the reshape never raises**; every
     `emb[tok]` silently returns a fragment of the wrong token's row. This is
     the same class as the defect that once made a session answer with the
     wrong token and no error. Scope: the **offline** `--a1`/`--a3` paths only.
   * **B (loud, and only at a new geometry): `sw/infer.py:798-802`'s online
     `step()`.** Hard-coded 1024 would command the chip to normalize the first
     1024 words of an H-word residual and then **crash** in `matvec_y32`'s
     reshape. It is loud, it is not wrong at 2B (H=2048 ≠ 1024 fails
     immediately), and it has one in-repo caller.

   A is the one to fix now. B is a migration work item.

   > **Dated note, 2026-08-25 (Track F).** **A is fixed on main**
   > (`2a50cac` `22f7ca8` `d999a54`), together with the `:1260-1263` row of
   > §2.10 — the loud twin *inside the same function*, without which the A fix
   > was useless at 2B. **B is untouched**, still a migration work item, and
   > its severity claim has been measured rather than reasoned:
   > `matvec_y32` and `matvec_y32_w8` do both raise at `n_in`=1024 on an
   > H-wide head. But **"it is not wrong at 2B" above is too generous, and
   > this bullet is stale on that point**: the crash is where it *stops*, not
   > where it starts. The three lines before it (`vnw_`/`vn`/`alu` at n=1024)
   > run silently on half the residual first, and because RMSNorm's
   > denominator is a mean over the words it is told about, they corrupt even
   > the words they do write — measured at 2B on an unevenly-split residual,
   > the DYNQ8 exponent shifts and **99.6 % of the leading half changes
   > (max |diff| 99)**; on an i.i.d.-uniform one the same measurement gives
   > max |diff| 1, which is why a single sample is not evidence here.
   > Evidence: `evidence/qwen_next/defect_a/` (`sibling_2b.log`,
   > `defect_b_2b.log`, corrections C2 in `CORRECTIONS.md`).

### 7.3 Effort, relative to the 2B migration

The 2B was **3 walls, all field widths**, planned at "3-4 rungs, 5-7 build
cycles" (`docs/QWEN2B_FEASIBILITY.md:65`) and executed as four (R-a…R-d).

Counting **distinct** walls — **§2.1**'s rows 6, 7, 8 and 16 are one
banking-wall family, so collapsing four rows into one leaves **fourteen** walls:

| | 4B | 9B |
|---|---|---|
| distinct walls hit | **13 of 14** (row 13 n/a — 4B is tied) | **13 of 14** (row 5 n/a — 8192 B rows need nothing) |
| the XL ones | **state banking / URAM 96.7 %**, **vecnorm at a non-power-of-two H** | **state banking / URAM 96.7 %**, **the 16-bit scratch ISA** |
| the L ones | scratch MLP chunking; `MAX_NG` → 72 + the SHAPE field; and — inside the banking family — the KV bank growth and the conv bank/depth growth | `MAX_NG` → 96 + the SHAPE field; the KV bank growth; the conv bank/depth growth |
| new RTL blocks re-opened for timing | `matvec_engine` **+ `matvec_chan`** (the XWIN decode, §2.5), `layer_chan` banking, `vecnorm_unit`, `seq_unit` EMB (only if not padding) | `matvec_engine` **+ `matvec_chan`**, `layer_chan` banking, `vecnorm_unit`, the layer ISA |
| honest multiple of the 2B campaign | **≈ 2.5–3×** | **≈ 3–4×** |
| what drives the difference | the reciprocal-multiply normalizer is 4B's own XL | the 16-bit scratch ISA, three scratch bodies, 2× the checkpoint and 2.1× the campaign compute |

**Both targets hit 13 of the 14 distinct walls** — they simply miss *different*
ones (4B has no untied head; 9B needs nothing for its embedding rows). An
earlier revision printed 13 vs 14 and read an asymmetry into it that is not
there.

Because **13 of 17 wall rows are shared and both targets have identical head
geometry, layer count and state size, the marginal cost of the second target
after the first is far below its standalone cost** — mostly the scratch ISA (if
9B is second) or the non-power-of-two normalizer (if 4B is second). The
multiples above are directional (§6, item 8) and they do **not** rest on the
13-vs-14 miscount: they rest on the XL/L rows, which are unchanged.

---

## 8. OPEN DECISION FOR THE USER

**This study does not pick.** Four questions, each with the evidence attached
and each labelled the way §0 promised — (**M**) measured on silicon, (**D**)
derived by a committed script that first reproduces a committed number,
(**E**) extrapolated:

| | rests on | label |
|---|---|---|
| **D1** which target | the geometry census, the DDR fit, the tok/s model | **D** geometry + fit, **E** throughput |
| **D2** ladder first | snoke-anchored compute, the tokenizer identity | **D** identity, **E** compute |
| **D3** URAM answer | the bank census against build_035's measured 348; **as of 2026-08-25 also `synth_design` + `place_design`** (Track P) | **T** the count and the placement (toolchain, not silicon), **UNKNOWN** the routing |
| **D4** emb rows | the row arithmetic and the seq_unit shift | **D** throughout |

~~The one input with no label available is D3's placement question: no synthesis
and no placement run exists, so it is not E — it is unmeasured.~~

> **DATED NOTE (2026-08-25, Track P): SUPERSEDED.** Both runs now exist —
> `synth_design -mode out_of_context` and `place_design`, on the widened
> `layer_chan`, part `xcvu9p-fsgd2104-2L-e`, 4.000 ns, in
> `evidence/qwen_next/place_exp/`. D3's count and placement are **T** —
> toolchain-measured on the real part, **not M**, which §0 reserves for
> silicon. Only
> the **routing** is still unmeasured (no `route_design` was run), together
> with the in-context placement (everything was out-of-context) and the
> fidelity cost of the int8 lever.


**D1 — Which target, or neither?** Both targets are given the same two
baselines, because an earlier revision quoted 4B against 9B and 9B against the
2B, which flattered the first:

| (**E** unless marked) | **4B** | **9B** |
|---|---|---|
| tok/s, W8 | **7.76** | **5.11** |
| tok/s, W4 g128 | **10.14** | **7.21** |
| vs the 2B's **measured** 16.52 (**M**) | **0.47× / 0.61×** (W8 / W4) | **0.31× / 0.44×** |
| vs each other, same precision (doc-arithmetic) | **1.52× / 1.41×** | **0.66× / 0.71×** |

* *4B* is the faster of the two by **1.52× at W8 and 1.41× at W4 g128**
  (the table above — an earlier revision wrote "1.4–1.5×", a band that
  excludes its own top value), fits W8 today at 80.4 % of the
  window, and needs **one** scratch body restructured — but it brings a
  non-power-of-two hidden size, a class of problem this project has never had,
  with **no zero-RTL escape in the normalizer** (the embedding half does have
  one: pad, §2.6).
* *9B* has the cleaner geometry — H = 4096 keeps vecnorm and the EMB shift
  **expressible**, both by widening paths the project has already walked,
  though "already walked" is not "already done" (§2.3) — but it needs the
  16-bit scratch ISA, runs at **0.31×** the 2B's measured rate at W8, and its
  W8 fit needs the host address map re-done to a state with zero slack on one
  channel. **This study measured no quality difference between the two models
  and takes no position on it**; §5's ladder is what would.
* *Neither* is a legitimate answer, and the arithmetic for it is symmetric: the
  2B serves at **16.52 tok/s measured** today, and the best modelled figure
  anywhere in this study is **10.14** (4B at W4 g128).

**D2 — Do the fidelity ladder FIRST?** It needs no RTL, no board and no address
map; it costs **3.61 h (4B) or 7.68 h (9B)** of snoke time plus the download
(§5, snoke-anchored); and it can retire most of the W8 question. If W4 g64 +
GPTQ is good enough at these sizes, the `matvec_engine` W8 work shrinks and
9B's DDR problem disappears — though **not the whole `matvec_engine` change**,
since `MAX_NG` and the XWIN decode move regardless, and GPTQ's own g64 cadence
adds a scale-beat item (§2.5).

> **The opinions this study states, so they can be discounted as a set.** It
> holds four, and no more: (a) D2 is the highest information per hour
> available; (b) D3's placement question should be settled before D1, because
> it can invalidate both targets; (c) defect A of §7.2 should be fixed now,
> independently of everything else — **done 2026-08-25, Track F**; (d)
> proportional compute scaling (§5) is the right direction to err. On the
> actual pick — 4B, 9B or neither — it states nothing.

**D3 — Which URAM answer?** 96.7 % as-is (unpriced, and the #1 risk), the int8
DN state (→ 60.4 %, two SLRs, unmeasured fidelity cost), or the DDR spill
(bandwidth nearly free at 1.2 %, but a large new RTL path).

> **What the cheap experiment can actually answer, corrected.** An earlier
> revision said "a single `synth_design` … would tell you whether the first
> option is even on the table". It would not. `synth_design` answers
> **inference only** — that the widened banks map to 928 URAM primitives.
> The question is a **placement** one, because URAM columns are physical and
> the 320-per-SLR limit binds at `place_design`, which is therefore the
> **minimum** run that answers it. And the sharp form (§6, item 3) is sharper still:
> 928 URAM cannot fit in fewer than three SLRs, so the 2048-bit DN bank-mux
> read path must cross **both** SLR boundaries every access, inside the one
> block build_035's floorplan had to leave unconstrained. Budget synthesis +
> placement, not synthesis.
>
> **DATED NOTE (2026-08-25): this was budgeted, run, and answered.** Track P
> ran synthesis + placement on all of it. Count exact (928). It **places**.
> "Both boundaries every access" → **at most one** (the placer centres the
> destination). The answer to D3:
> * **Option 1 — NEITHER LIVE NOR DEAD.** At the as-built read path it fails
>   (−1.848 ns). But pipelining the crossings takes that path to **+0.097 ns,
>   MET** (N=2 under `AltSpreadLogic_medium`; N=2 at the Default directive is
>   −0.162), so **the read-path objection does not survive**. What binds
>   instead is the **write-control fan-out** (−1.391 to −1.956 ns), one logic
>   level and ~96 % route — a **floorplanning** problem, and **no floorplan
>   was tried**. Its latency price is also two-sided: the N=1 structure costs
>   **~0.15 %** but does not close (−0.339); the N=2 structure that reaches
>   MET needs a wait state in `dn_step`'s 5-state pass-2 loop (**≈ +10 %**) or
>   an unpriced two-outstanding restructure. **Do not read this row as either
>   "96.7 % works" or "96.7 % is dead".**
> * **Option 2 (int8 DN state) is measured live** — 580 URAM (592 without a
>   write combiner, and it stays in URAM either way), WNS **−0.119**, 48
>   failing endpoints. **Fidelity unmeasured.**
> * **Option 3 is untouched.**
>
> Nothing was routed, anywhere. Full result and its **14** stated limits:
> `evidence/qwen_next/place_exp/PLACE_EXP.md`.

**D4 — 4B's embedding rows: pad or address?** Padding costs **727.5 MiB** of a
channel that ends 78.7 % full and **zero RTL**. Non-power-of-two addressing
saves that and costs new logic in `seq_unit`'s EMB address path — which, per
§2.6, is **adjacent to** build_034's waived MOV-addressing class and **not
inside it** (`docs/QWEN2B_QUANT_STUDY.md:226-227` records that the R6 EMB
barrel shift did *not* appear in either worst violating path). An earlier
revision said "one of build_034's three waived timing classes" here; that is
withdrawn. The real cost is that it is new logic in a block on a bitstream
that closes at exactly 0.000, plus turning EMBLOG2 from a 5-bit log2 field
into a row-bytes or two-term encoding.

**Independent of all four**, and recommended regardless: fix **defect A** of
§7.2 — `ref/seq_chat.py`'s embedding reshape, which is wrong at 2B **today**
and **silent** because `// 2048` and `.reshape(n, 1024)` are mutually
consistent so the reshape never raises. **Defect B** (`sw/infer.py:798-802`'s
online `step`) is a migration work item, not an urgent one: it crashes loudly
at any H ≠ 1024 and has one in-repo caller.

> **Dated note, 2026-08-25 (Track F).** Defect A is **fixed on main**
> (`2a50cac` `22f7ca8` `d999a54`), with its `:1260-1263` twin; defect B is
> **still open by design**. Read the §7.2 note for the one correction that
> matters to the migration: defect B is silently wrong for three lines
> *before* it crashes, so "crashes loudly" describes its end, not its whole
> behaviour. Evidence: `evidence/qwen_next/defect_a/`.

---

## 9. Traceability index

Every number in this document, by source. Paths are repo-relative. All logs
carry a host/date/tree/venv header from `evidence/qwen_next/feas/feas_run.sh`.

| claim | evidence |
|---|---|
| exact 4B/9B geometry, per-tensor shapes, shard counts, prefix census | `evidence/qwen_next/feas/fetch_geometry.py` → `f01_geometry.log`, `geometry_raw.json`; `geom_report.py` → `f02_geom_report.log` |
| 32 value heads / 16 key heads, CONV_DIM 8192, 16 NQ / 4 NKV | `f02_geom_report.log` (the layer-0 and layer-3 shape tables) |
| 9B untied: `tie_word_embeddings` **`false` at top level, ABSENT from `text_config`**; `lm_head.weight` a top-level tensor | **`f15_tie_ground_truth.log`** (raw key presence, not a `.get()` result); the ONE effective guard is `ref/load_qwen35.py:291-294`, since `:169-170` hands `:288` the **text** config where the key is absent |
| scratch peaks 36,384 / 50,208; 0.8B/2B validation; mitigation; SCA collision; `LKD` bug | `evidence/qwen_next/feas/scratch_peak.py` → `f03_scratch_peak.log`, `scratch_peak.json` |
| DDR fit, per-channel tops, bytes/token, emb tables, checkpoint cross-check | `evidence/qwen_next/feas/ddr_fit.py` → `f04_ddr_fit.log`, `ddr_fit.json` |
| tok/s model, counter validation, the (r, m) solve, the layer term, the two honesty checks | `evidence/qwen_next/feas/toks_model.py` → `f05_toks_model.log`, `toks_model.json` |
| the DeltaNet per-head serialization, and the 288-DNST-per-token census on the real 0.8B stream | `evidence/qwen_next/feas/layer_cmd_census.py` → **`f16_layer_cmd_census.log`**; `rtl/dn_step.sv:1,:13-14`, `rtl/layer_chan.sv:525,:891`, `ref/gen_layer_script.py:1129-1136` |
| campaign compute and disk, **snoke anchors only** | `evidence/qwen_next/feas/quant_pricing.py` → **`f17_quant_pricing.log`**, `quant_pricing.json` |
| capacity vs address map, the 9B W8 option-B penalty, the 4B emb options, EMBLOG2 headroom | `evidence/qwen_next/feas/addrmap_options.py` → `f06_addrmap.log` |
| snoke disk / RAM / cores | `f07_disk.log`, `f09_snoke_caps.log` |
| URAM 928/960, the 348 validation, BRAM, the int8 lever, CONV count fields | `evidence/qwen_next/feas/resource_budget.py` → `f08_resources.log`, `resource_budget.json` |
| tokenizer byte-identical, chat template differs | `evidence/qwen_next/feas/tokenizer_check.py` → `f10_tokenizer.log`, `tokenizer_sha.json` |
| the chat-template diff (enable_thinking inversion) | `evidence/qwen_next/feas/tokenizer_diff.py` → `f11_tokenizer_diff.log` |
| `arg0[17]` spare — **293,768 ALU dispatches** in the reproducible committed scope (248,218 frozen / 338,932 including gitignored streams) | `ref/scripts/scan_spare_bits.py` (methodology at `:10-25`) → `f12_spare_bits_frozen.log`, **`f14_spare_bits_committed.log`** (the reproducible one the study leans on), `f13_spare_bits_widest.log`; assert message `ref/gen_layer_script.py:784-785` |
| 2B measured: 16.525 tok/s, layer 17.960, 0.8B layer 15.128, bytes/token | `evidence/qwen2b/rd/RD_GATE.md` §1, §3 |
| mover cost law, `r` bracket, counted 0.8B stream | `evidence/qwen2b/ra/MOVER_NORM.md` §1–§3 |
| build_035 utilization: URAM 348 and **Block RAM Tile 576.5** | `evidence/qwen2b/rc/TIMING_035.md:850-851` (§8b's table at `:340-347` reads `561 + 31 RAMB18`, a different split of the same design — do not quote it as 576.5) |
| WNS 0.000 / zero margin; SLR capacity and the `layer_0` URAM straddle | `evidence/qwen2b/rc/TIMING_035.md` §13.4, `:629-630`; `evidence/qwen2b/ra/util_resident.md` |
| `matvec_engine` owns the worst waived endpoints | `docs/QWEN2B_QUANT_STUDY.md` §1.1; `evidence/qwen2b/rb/shipped_roll_endpoint_census.log` |
| the DN bank array is exactly full at 18 DN layers | `evidence/qwen2b/ra/dn_bank_verify.md:64-75` |
| scratch map algebra and the 0.8B/2B empirical probe | `docs/QWEN2B_SCRATCH_MAP.md`; `evidence/qwen2b/ra/scratch_probe.log` |
| quant harness anchors (seconds_eval, 24,528 positions) | `evidence/qwen2b/q1/ppl_*.json`, `evidence/qwen2b/q2/v4_v5/ppl_v5.json` |
| the 2B campaign's own projection error (+23.1 % vs +18.7 %) | `evidence/qwen2b/rd/RD_GATE.md` §3 |
