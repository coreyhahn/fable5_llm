# Two boards over the QSFP28 link — Qwen3.5-27B (dense) and Qwen3.5-35B-A3B (MoE) feasibility study (2026-09-15)

> **NOTHING IN THIS DOCUMENT IS MEASURED ON TWO BOARDS.** There is one
> BCU-1525 in this lab, on snoke at PCIe 82:00.0. No second board exists, no
> QSFP cable was plugged in, no link was brought up, no bitstream was built and
> the resident board was not touched. Every two-board number here is arithmetic
> over one-board measurements plus stated assumptions, and every one of them
> carries a label. The study **picks nothing**: §8 is the user's decision.

> ### THE VERDICT IN ONE PARAGRAPH
>
> **The two targets fail for opposite reasons, and that is the whole finding.**
> The **27B dense** model is a *width* problem — it breaks eight as-built
> ceilings (vecnorm N, the ALU length, `MAX_NG`, EMBLOG2, the **DN cache
> slot**, the DN head field, the conv slot depth and the scratchpad — §2.1's
> rows 1, 2, 3, 4, 5, 6, 8/11 and 10) and then streams **12,784 MiB per
> token**, 3.28× the shipped 9B, which puts it at **2.4–4.7 modelled tok/s** on
> two boards. The **35B-A3B MoE** passes **every** width wall — three of them
> *exactly* at the ceiling — and streams only **1,531 MiB per token**, 39 % of
> the shipped 9B, which models at **10–19 tok/s**. But it is blocked by something the 27B does not have:
> **there is no router, the weight stream is structurally static, and the
> emitter's loop closure requires byte-identical token bodies.** The MoE is
> cheap in every dimension this project has ever measured **except resident
> capacity** — its 18.8 GiB pack needs two boards at any precision this project
> has (§3.2) — and expensive in one dimension it has never built.
>
> Both need two boards for **capacity**, not for speed: at W4 g128 the MoE's
> pack is 17.8 GiB and the 27B's is 12.5 GiB + a 3.8 GiB embedding table
> against 16 GiB per board (§3). Both need the per-channel runtime `EMB_BASE`
> the 4B/9B study priced (§3.2 there) before any split fits. Board B has
> **power only**, so its weights, its stream, its state region, its CSR traffic
> and its per-token activations all cross the link (§5).

Companion to `docs/QWEN35_NEXT_FEASIBILITY.md`, written to the same contract
and structured the same way. Evidence lives under `evidence/qwen_next/feas2/`
and **every numeric step ran on snoke** through
`evidence/qwen_next/feas2/feas2_run.sh` (host/date/tree/venv stamped, a copy of
`evidence/qwen_next/feas/feas_run.sh` with one addition: it refuses to
overwrite a log). Nothing numeric ran on darthplagueis, which
`NEXT_SESSION.md`'s Key invariants retire from numeric work permanently.

**Scope: study only.** No RTL, emitter, host-tool or constraint change; no
Vivado build; no board action; no QSFP experiment; no weight download — the
geometry comes from ranged HTTP reads of each checkpoint's safetensors headers.
Read-only Vivado *queries* on snoke were run and are cited (§5.1).

---

## 0. How to read every number below — stated before the numbers

This document uses `evidence/qwen9b/g6/RD9_GATE.md` §0's reading rule, which is
the one the 9B campaign shipped under, with one addition for extrapolation:

| label | means |
|---|---|
| **T** | **transcribed** from a named log in `evidence/qwen_next/feas2/` or from a cited gate log, with `=== rc  :` and `=== end :` both present |
| **D** | **derived**, with the arithmetic shown, by a committed script that **reproduces a committed number before it computes a new one** |
| **S** | **stated** by a cited source — a spec, a datasheet, a community pin file, an IP description |
| **E** | **extrapolated** past every measurement, or **assumed** where no measurement exists |
| **B** | **measured on the BOARD** — used where this document quotes a silicon figure from a 9B gate log, and kept distinct from **T** because a **T** number may have come from a tool run rather than from the BCU-1525. `evidence/qwen9b/g6/RD9_GATE.md` §0 has no such label; this document adds it. **It is deliberately NOT `M`**: §2.1's and §7.3's `class` columns already use a bolded **M** for the *Medium* effort class, which is a different taxonomy entirely |

Each derivation carries its own validation, and they are not decorative:

* `evidence/qwen_next/feas2/ddr_fit2.py` reproduces the **shipped** 9B W4 g128 pack exactly —
  4,091,805,696 B/token and the per-channel 978.40 / 975.30 / 974.27 / 974.27
  MiB that `evidence/qwen9b/g6/RD9_GATE.md` §10.3 transcribes off the board's
  own plan, max/min 1.004234 — and **asserts** before printing anything new
  (`evidence/qwen_next/feas2/f05_ddr_fit2.log`).
* `evidence/qwen_next/feas2/scratch_peak2.py` reproduces `ref/gen_layer_script.py`'s frozen 0.8B
  `_LEGACY_MAP` **entry for entry** and the committed 9B peaks
  (33,824 / 37,920 / 50,208) before it evaluates 27B or the MoE
  (`evidence/qwen_next/feas2/f10_scratch_peak2.log`).
* `evidence/qwen_next/feas2/resource2.py` reproduces the shipped `OOC9B_URAM: 182`
  (`NEXT_SESSION.md` §9) from the slot declarations before it sizes anything
  (`evidence/qwen_next/feas2/f12_resource2.log`).
* `evidence/qwen_next/feas2/toks2_model.py` **imports** `evidence/qwen_next/feas/toks_model.py` rather
  than replacing it, reproduces its fitted `A` and `Bv` to 1e-18 and its 47.00
  ms 9B layer term, and only then extends it (`evidence/qwen_next/feas2/f11_toks2_model_fix.log`).
* `evidence/qwen_next/feas2/geom2_report.py` carries the 9B in every table as the reproduction anchor
  against `evidence/qwen_next/feas/f02_geom_report.log` (`evidence/qwen_next/feas2/f04_geom2_report.log`).

**Where a derivation could not be validated, or is wrong, this document says
so loudly.** §4.2 scores the committed throughput model against the shipped 9B
on **three** comparands, says why those three, and reports that the 9.9 % gap
between two of them is one its own source **declines to attribute**.
(`evidence/qwen9b/g6/RD9_GATE.md` §10's own table offers four for the layer
lane; §4.2 uses the like-for-like one and the board's, and explains the choice
rather than averaging them.) §4.5 records
**two errors of my own** in an earlier run of this study's script (`f09`),
corrected in `f11`, with the wrong log kept. §6 lists **sixteen** things this
study did not establish. Four facts are recorded as **UNKNOWN** with the
experiment that would settle each: what drives the MGT refclks
`MGTREFCLK0_230/231` and at what frequency, and separately the USER Si570's
programmed frequency (both §5.1); whether board B can be JTAG-programmed at all
(§5.4); and which GTY quad each CMACE4 hard block is reachable from (§5.2).

> **DATED NOTE — FIX ROUNDS 1–3, 2026-09-15.** Round 1 withdrew the
> "corrected" (×0.8851) column an earlier one carried through §4.3, §4.4,
> §4.5, §7.1 and §8.2 (§4.2, §6 item 13); corrects the SLD/SST envelope, which
> **passes for both models under the midpoint pipeline cut** (§2.7, §7.2 item
> 5); corrects "five walls exactly at the ceiling" to **three** (§2.8);
> corrects "the first layer-bound target" (§4.4); corrects §7.1's head-geometry
> cell; re-states the licence finding on the tool's own build log rather than
> on a text scan (§5.2); and splits the Si570 UNKNOWN into the two different
> clocks it conflated (§5.1). Round 2 corrected two stale "five"s, restored the
> DN cache slot to the verdict's list of eight, and relabelled 46.161 **D**.
> Round 3 renamed the board-measured confidence label **M → B** (it collided
> with §2.1's *Medium* effort class), separated what the build logs prove (the
> feature and the date) from what only the `.lic` scan says (the edition name),
> and swept the whole document for over-absolutes the earlier rounds introduced
> or left standing — eight sentences changed, each now agreeing with the
> paragraph around it. **Through all three rounds no number was re-derived, no
> recommendation moved, and §8 still picks nothing.** The reviews that produced
> them are kept **outside the tree**, under
> the project's gitignored SDD directory, so this document does not cite a path
> for them; **the committed record of what changed and why is the `2b1(fix1)`,
> `2b1(fix2)` and `2b1(fix3)` commit messages**, which list every finding and
> its fix.

---

## 1. The geometry — from the checkpoints, not from the model cards (**D**, `f01`/`f04`)

`evidence/qwen_next/feas/fetch_geometry.py` reads every shard's safetensors
JSON header by ranged HTTP and the `config.json` beside it. **No weights were
downloaded.** `evidence/qwen_next/feas2/geom2_report.py` is a new reader — not
an edit of the committed `evidence/qwen_next/feas/geom_report.py`, whose logs cite it by line — that
adds the MoE keys and the derived active-parameter count. Logs
`evidence/qwen_next/feas2/f01_geometry2.log`, `evidence/qwen_next/feas2/f04_geom2_report.log`; raw `evidence/qwen_next/feas2/geometry2_raw.json`.

| field | **9B** (shipped) | **27B** | **35B-A3B** |
|---|---|---|---|
| `hidden_size` | 4096 | **5120** | **2048** |
| `intermediate_size` | 12288 | **17408** | **`<absent>`** |
| `num_hidden_layers` | 32 | **64** | **40** |
| layer types (DN / full) | 24 / 8 | **48 / 16** | **30 / 10** |
| `full_attention_interval` | 4 | 4 | 4 |
| `vocab_size` | 248320 | 248320 | 248320 |
| `head_dim` | 256 | 256 | 256 |
| `num_attention_heads` | 16 | **24** | 16 |
| `num_key_value_heads` | 4 | 4 | **2** |
| `linear_num_key_heads` | 16 | 16 | 16 |
| **`linear_num_value_heads`** | 32 | **48** | 32 |
| `linear_key_head_dim` / `linear_value_head_dim` | 128 / 128 | 128 / 128 | 128 / 128 |
| `linear_conv_kernel_dim` | 4 | 4 | 4 |
| derived `CONV_DIM` | 8192 | **10240** | 8192 |
| `tie_word_embeddings` | present at top level with value `false`, **ABSENT** from `text_config`; untied is established **from the tensor**, not from the flag | **identical** | **identical** |
| `lm_head.weight` in the checkpoint | yes | yes | yes |
| shards | 4 | **11** | **14** |
| on-disk bf16 | 17.98 GiB | **51.75 GiB** | **66.97 GiB** |
| `max_position_embeddings` | 262144 | 262144 | 262144 |
| rope `partial_rotary_factor` / `theta` | 0.25 / 1e7 | 0.25 / 1e7 | 0.25 / 1e7 |

`CONV_DIM` is checked against the checkpoint's own `conv1d.weight` row count in
`evidence/qwen_next/feas2/f05_ddr_fit2.log`, not merely derived: 8192 / **10240** / 8192, all OK.

### 1.1 The 27B: a third DeltaNet head count, and a fourth non-power-of-two width

`linear_num_value_heads` goes 16 (0.8B/2B) → 32 (4B/9B) → **48**. The tensor
shapes confirm it independently, which `config.json` alone cannot:

| tensor (layer 0, a DeltaNet layer) | **9B** | **27B** |
|---|---|---|
| `linear_attn.in_proj_qkv.weight` | [8192, 4096] | **[10240, 5120]** |
| `linear_attn.in_proj_z.weight` | [4096, 4096] | **[6144, 5120]** |
| `linear_attn.in_proj_a` / `in_proj_b` | [32, 4096] | **[48, 5120]** |
| `linear_attn.A_log` / `dt_bias` | [32] | **[48]** |
| `linear_attn.conv1d.weight` | [8192, 1, 4] | **[10240, 1, 4]** |
| `linear_attn.out_proj.weight` | [4096, 4096] | **[5120, 6144]** |

`10240 = 2·(16·128) + 48·128`: **16 key heads and 48 value heads**, three value
heads per key head. The GQA layers move too — `q_proj` **[12288, 5120]** is
`2 · 24 · 256` (the output gate), `k_proj`/`v_proj` are **[1024, 5120]**,
`o_proj` is **[5120, 6144]**.

**`hidden_size` 5120 is not a power of two**, and neither is its embedding row
(5120 × 2 B = **10,240 B**). That is the 4B's wall 2 and wall 5 again, at a
larger size and with one difference that matters: the 4B could pad its rows to
8192 B; the 27B's padded row is 16,384 B, which needs `EMBLOG2` **14** — and
the CSR refuses it (§2.6).

### 1.2 The 35B-A3B: every layer is MoE, and "A3B" is not what streams

The MoE keys, printed **by presence** because `<absent>` and `None` are
different facts (the lesson `docs/QWEN35_NEXT_FEASIBILITY.md` §1.2 paid for):

| key | 9B | 27B | **35B-A3B** |
|---|---|---|---|
| `intermediate_size` | 12288 | 17408 | **`<absent>`** |
| `num_experts` | `<absent>` | `<absent>` | **256** |
| `num_experts_per_tok` | `<absent>` | `<absent>` | **8** |
| `moe_intermediate_size` | `<absent>` | `<absent>` | **512** |
| `shared_expert_intermediate_size` | `<absent>` | `<absent>` | **512** |
| `mlp_only_layers` | `[]` | `[]` | **`[]`** |
| `decoder_sparse_step` / `moe_layer_freq` / `first_k_dense_replace` | `<absent>` | `<absent>` | **`<absent>`** |
| `norm_topk_prob` / `scoring_func` / `topk_method` / `n_group` | `<absent>` | `<absent>` | **`<absent>`** |
| `router_aux_loss_coef` | `<absent>` | `<absent>` | 0.001 |

`mlp_only_layers` is empty and every checked layer carries `mlp.experts`
tensors — layer 0 (DeltaNet) and layer 3 (full attention) both do — so
**all 40 layers are MoE**. There is no dense prefix and no every-other-layer
pattern.

The expert tensors are **fused 3-D**, which decides the whole shape of the DDR
problem:

| tensor (any layer) | shape | what it is |
|---|---|---|
| `mlp.gate.weight` | **[256, 2048]** | the router: 256 scores from H |
| `mlp.experts.gate_up_proj` | **[256, 1024, 2048]** | all 256 experts' gate\|up, stacked |
| `mlp.experts.down_proj` | **[256, 2048, 512]** | all 256 experts' down, stacked |
| `mlp.shared_expert.gate_proj` / `up_proj` | **[512, 2048]** | one always-on expert |
| `mlp.shared_expert.down_proj` | **[2048, 512]** | |
| `mlp.shared_expert_gate.weight` | **[1, 2048]** | a scalar gate on the shared expert |

**The router's normalisation is not in the config.** `norm_topk_prob`,
`scoring_func` and `topk_method` are all `<absent>`, so whether the top-8
weights are renormalised, and whether the gate is softmax or sigmoid, is
**UNKNOWN from the checkpoint alone** — it is in the modelling code, not the
config. It would be settled by reading the released `modeling_*.py` for this
architecture, which this study did not do. §2.11 prices the router under both
readings and the difference is one reciprocal.

### 1.3 The active parameter count, derived from the tensors (**D**, `f04`)

Not read off the model card. The `-A3B` in the name is not evidence.

| | 9B | 27B | **35B-A3B** |
|---|---|---|---|
| DN mixer / layer | 67,403,776 | 115,875,840 | 33,718,272 |
| GQA mixer / layer | 58,720,256 | 104,857,600 | 27,262,976 |
| FFN / layer, **total** | 150,994,944 | 267,386,880 | **808,978,432** |
| FFN / layer, **active** | 150,994,944 | 267,386,880 | **28,837,888** |
| all mixers | 2,087,452,672 | 7,239,761,920 | 1,284,177,920 |
| all FFN, total | 4,831,838,208 | 17,112,760,320 | **32,359,137,280** |
| all FFN, active per token | 4,831,838,208 | 17,112,760,320 | **1,153,515,520** |
| embedding table | 1,017,118,720 | 1,271,398,400 | 508,559,360 |
| `lm_head` | 1,017,118,720 | 1,271,398,400 | 508,559,360 |
| **text tower, resident** | 7,936,409,600 | **25,623,920,640** | **34,151,874,560** |
| **streamed per token** | 7,936,409,600 | **25,623,920,640** | **2,946,252,800** |

The derivation accounts for **100.00 %** of each checkpoint's own
`model.language_model` parameter census (the remainder being norms, biases and
`A_log`), which is the cross-check that makes it a derivation rather than an
assertion.

> **The number that shapes everything below.** The MoE's per-token active
> parameter count is **8.50 %** of its resident tower — 2.95 G streamed (which
> includes the LM head) of 34.66 G resident (the 34.15 G text tower **plus** the
> 0.51 G head, so that both sides carry it) — and
> **37 % of the shipped 9B's 7.94 G**. It is a *smaller* per-token workload
> than the model this project already runs at 7.29 tok/s, sitting inside a
> *four times larger* memory. That is the entire case for it, and §2.11/§2.12
> are the entire case against.

### 1.4 The tokenizer and the chat template — NOT CHECKED

`docs/QWEN35_NEXT_FEASIBILITY.md` §1.4 ran `evidence/qwen_next/feas/tokenizer_check.py` and
`evidence/qwen_next/feas/tokenizer_diff.py` across four checkpoints and found the tokenizer
byte-identical and the chat template changed. **This study did not run either
tool**, so it makes no claim about the two new checkpoints' tokenizers or
templates. `evidence/qwen_next/feas/tokenizer_check.py` would answer it in one
run and it is listed in §6.

---

## 2. Wall census against the AS-BUILT tree

`docs/QWEN35_NEXT_FEASIBILITY.md` §2.1's seventeen rows are the checklist, but
**its ceilings are stale** and re-using them would be wrong. Three things moved
since 2026-08-25: **G3.1** re-encoded the layer ISA to flat 16-bit scratch
addresses, **G3.2** widened vecnorm to N = 4096, and the **state-spill
amendment** (`docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md`)
moved layer state to DDR behind two-slot URAM caches. Every row below is
re-read from HEAD, with `file:line` and the load-bearing lines quoted.

**The state-spill amendment changed the KIND of four rows.** Rows 6, 7, 8 and
16 of the old list were *bank-count* walls — "how many layers fit on chip".
They are now *cache-slot-size* walls — "how big is one slot". The bank count
survives only as the SLD/SST layer-range envelope, and **that envelope is a new
wall both targets fail** (row 16 below).

### 2.1 Summary matrix

| # | wall | ceiling **as built at HEAD** | **27B** | **35B-A3B** | class |
|---|---|---|---|---|---|
| 1 | scratchpad words | **65,536** (G3.1) | **FAIL** 68,720 — a 2-way MLP chunk fixes it (48,240) | **PASS** 29,216 | **S** (27B) |
| 2 | vecnorm N | **4096**, **power-of-two only** | **FAIL twice** — 5120 > 4096 **and** not a power of two | **PASS** 2048 | **XL** (27B) |
| 3 | ALU `cfg_len` | **16,383** (14 b, G3.1) | **FAIL** 17,408 | **PASS** | **S** (27B) |
| 4 | matvec `ng` / SHAPE | **96** = K ≤ 12,288 | **FAIL** `down` K=17,408 → ng 136 | **PASS** max ng 32 | **L** (27B) |
| 5 | EMBLOG2 row stride | **13** = 8192 B, power-of-two only | **FAIL** — row 10,240 B, padded 16,384 needs 14 | **PASS** 12 | **L** (27B) |
| 6 | **DN cache slot rows** | **4096** = 32 heads × 128 | **FAIL** 6,144 (+58 URAM288) | **PASS, exactly** | **M** (27B) |
| 7 | **KV cache slot** | 8192 rows, `T_MAX` 4096, ONE kvhead/slot | **PASS** on geometry | **PASS** | — |
| 8 | **conv cache slot depth** | **`CVD` 8192** | **FAIL** 10,240 (+4 URAM288) | **PASS, exactly** | **M** (27B) |
| 9 | `kvhead` field | **2 b → 4** | **PASS, exactly at the ceiling** | **PASS** 2 | — |
| 10 | `dn_head` field / `gate_unit` NH | **5 b → 32** | **FAIL** 48 | **PASS, exactly** | **M** (27B) |
| 11 | CONV `cvi` executable ceiling | **`CVD` 8192** (field is 14 b) | **FAIL** 10,240 | **PASS, exactly** | (= 8) |
| 12 | multi-shard loader | **no limit** — glob + merge | **PASS** 11 | **PASS** 14 | — |
| 13 | untied LM head | **handled**, both spellings, cross-checked | **PASS** | **PASS** | — |
| 14 | `ref` key/value head algebra | **CLOSED** — `LKD = LNKH · LDK` | **PASS** | **PASS** | — |
| 15 | SCA scalar-tile strides | **CLOSED** — `max(32, …)` floors | **PASS** | **PASS** | — |
| 16 | **NEW** SLD/SST layer envelope | **`N_DN` 24 / `N_KV` 8**, 5-b field | **FAIL** 48 / 16 as a whole model; **PASS EXACTLY** 24 / 8 per board under the midpoint pipeline cut | **FAIL** 30 / 10 whole; **PASS** 15 / 5 per board under the midpoint cut | **M, shared, and SPLIT-CONDITIONAL** |
| 17 | host / `ref` / TB geometry rot | 0.8B…9B tag tables | **FAIL** | **FAIL** | **M, shared** |
| 18 | **NEW, MoE** the router | **no opcode exists** | n/a | **FAIL** | **L** |
| 19 | **NEW, MoE** expert gather | **indirection REFUSED at decode on MVGO** | n/a | **FAIL** | **XL** |
| 20 | **NEW, MoE** the emitter's loop closure | **byte-identical token bodies required** | n/a | **FAIL** | **XL** |
| 21 | **NEW, MoE** the shared expert's gate | `SIGM16` exists | n/a | **PASS — free** | — |
| 22 | context ceiling `T < 512` | 40-bit `denom`, by analysis | **FAIL, inherited** | **FAIL, inherited** | **M, shared** |

**The two targets share almost nothing.** The 27B fails **eight** width walls
(1, 2, 3, 4, 5, 6, 8/11, 10 — **six** of them widenings this project has done
before, and **two**, rows 2 and 5, that need a primitive `vecnorm_unit` and
`seq_unit`'s EMB path have never had) plus the two shared ones (16, 17 — and 16 is
split-conditional, see §2.7) and the inherited 22. The MoE fails **none** of
them — it clears rows 1–15 outright, **three** of them *exactly at the ceiling*
(§2.8) — and fails instead on 16, 17, 22 and the three **new** ones, 18/19/20,
which are not widths at all.

### 2.2 Wall 1 — the scratchpad, now 65,536 words (**D**, `f10`)

G3.1 landed the 16-bit re-encode the 4B/9B study said the 9B "realistically
wants". `rtl/layer_chan.sv:503-504`:

```systemverilog
    (* cascade_height = 2 *) logic signed [15:0] smem_a [65536];
    (* cascade_height = 2 *) logic signed [15:0] smem_b [65536];
```

with flat 16-bit addressing at `rtl/layer_chan.sv:505` `logic [15:0] sa_addr, sb_addr;`
and `rtl/layer_chan.sv:507` `logic [15:0] sw_addr;`, and the two host-side
ceilings now coincide — `ref/gen_layer_script.py:425` `SCRATCH_MAX = 65536` and
`ref/gen_layer_script.py:426` `ISA_SADDR_MAX = 65536`.

`evidence/qwen_next/feas2/scratch_peak2.py` mirrors `ref/gen_layer_script.py`'s allocator as it stands
(the `fix_sca` branch of the 4B/9B study **was adopted**, at
`ref/gen_layer_script.py:125-128`, and `ref/gen_layer_script.py:200` is now
`STG = SCA + max(1024, SCA_SZ)`), reproduces the frozen 0.8B `_LEGACY_MAP`
entry for entry and the committed 9B peaks, and then:

| body | 0.8B | 2B | 9B | **27B** | **35B-A3B** |
|---|---|---|---|---|---|
| `SCA_SZ` | 992 | 992 | 1,056 | **1,136** | 1,056 |
| `PEAK_DN` | 16,384 | 21,504 | 33,824 | **43,120** | 27,680 |
| `PEAK_ATTN` | 15,872 | 23,552 | 37,920 | **48,240** | 29,216 |
| `PEAK_MLP` | 14,848 | 25,600 | 50,208 | **68,720** | 14,368 |
| **PEAK** | 16,384 | 25,600 | 50,208 | **68,720** | **29,216** |
| vs 65,536 | +49,152 | +39,936 | +15,328 | **−3,184** | **+36,320** |

**The 27B is over by 3,184 words — 4.9 % — and that is the cheapest wall it
has.** Chunking the gate/up pair, exactly as the 4B/9B study priced it (its
§2.2, where the *down* stage takes over as the peak):

| chunks | gate/up | down | `PEAK_MLP` | **PEAK** | spare |
|---|---|---|---|---|---|
| 1 | 68,720 | 60,528 | 68,720 | **68,720** | −3,184 |
| 2 | 42,608 | 43,120 | 43,120 | **48,240** | **+17,296** |
| 3 | 33,905 | 37,318 | 37,318 | 48,240 | +17,296 |
| 4 | 29,552 | 34,416 | 34,416 | 48,240 | +17,296 |

At two chunks `PEAK_ATTN` (48,240) binds and no further chunking helps.
**Emitter work, no ISA change, no extra BRAM** — class S.

**The MoE's MLP body is the smallest in this table**, because one expert's
intermediate is 512 wide. Staging all nine active experts at once (8 routed +
1 shared) gives `PEAK_MLP` 22,560 and `PEAK` is still 29,216, set by
`PEAK_ATTN`. Either way it passes with 36,320 words spare — **more headroom
than the 2B had**.

### 2.3 Wall 2 — vecnorm, and why 5120 is the 4B's problem again, worse

G3.2 widened the unit to N = 4096. `rtl/vecnorm_unit.sv:86` still takes
`input  wire [3:0]         cfg_nlog2,` — a **log2** field — and N is still
produced only by shifting, `rtl/vecnorm_unit.sv:285`
`n_total <= 13'd1 << cfg_nlog2;`. There is no plain length input anywhere in
the unit, and the guard is now `rtl/vecnorm_unit.sv:432-434`:

```systemverilog
        if (rstn && start && (st == IDLE) && (cfg_nlog2 >= 4'd13))
            $fatal(1, "vecnorm_unit: cfg_nlog2 %0d unsupported (max 12, N=4096)",
                   cfg_nlog2);
```

* **35B-A3B: H = 2048, `nlog2 = 11`.** Inside the shipped envelope with a
  doubling to spare. **PASS, and nothing to do.**
* **27B: H = 5120.** It fails **twice** and the two failures are independent.
  (a) 5120 > 4096, so every width G3.2 doubled once must double again —
  `xbuf`/`wbuf` 4096 → 8192, the counters 13 → 14 bits, `w_waddr` 12 → 13, the
  `$fatal` moved. (b) **5120 is not a power of two**, so the shift is not the
  right primitive at all: the unit needs a length input and a reciprocal
  multiply for the `1/N` that is currently folded into the rsqrt binary point
  as a shift. That is the 4B's XL wall, and **`vecnorm_unit` has still never
  had one**. Note the *primitive* is not new to the project — `fx_recip` exists
  and is instantiated inside `attn_core` (`rtl/attn_core.sv:96`) — what is new
  is putting one in the normalizer's critical path. **XL.**

### 2.4 Wall 3 — the ALU length field

`rtl/vec_alu.sv:112` is `input  wire [13:0]         cfg_len,` — 14 bits, max
**16,383** — fed from `rtl/layer_chan.sv:942`
`.cfg_op(arg0[3:0]), .cfg_len(arg0[17:4]),   // G3.1: 14-bit len`. The tree
says out loud what it was widened for, `rtl/layer_chan.sv:177-178`:
*"G3.1 takes it to 14, so the 9B FFN=12288 also fits one command.  Max length is now 16383."*

27B's FFN is **17,408** — over by 1,025. The MoE's longest ALU vector is H =
2048, or 512 per expert. **27B FAIL (S: one more bit, and `arg0` is the same
word G3.1 already re-cut), MoE PASS.**

### 2.5 Wall 4 — `MAX_NG`, and the one image that breaks it

`rtl/matvec_engine.sv:142` is
`parameter int MAX_NG   = 96,    // max groups/row (K <= 12288 = the 9B` and
`rtl/matvec_engine.sv:150` defines the unit:
`input  wire [6:0]          cfg_ng,      // groups/row = K/128 = the WEIGHT`.
The SHAPE word gives it 7 bits — `rtl/matvec_chan.sv:18`
`//   0x14 SHAPE     W  {spare[31:29], ng[28:22], nrows[21:6], sh[5:0]}` — and
the X window is sized to match, `rtl/matvec_chan.sv:564`
`localparam int XWIN_WORDS = 3072;` (3072 words × 4 int8 = 12,288). The host
twin is `sw/hwmap.py:85` `SHAPE_MAX_NG = {SHAPE_ISA_PRE_G3: 48, SHAPE_ISA_9B: 96}`.

`ng = K/128` exactly, so per image class:

| class | K at 27B | ng | K at 35B-A3B | ng |
|---|---|---|---|---|
| `gate_up` | 5,120 | 40 | 2,048 | 16 |
| **`down`** | **17,408** | **136 — FAIL** | 512 | 4 |
| `qkv` | 5,120 | 40 | 2,048 | 16 |
| `o_proj` | 6,144 | 48 | 4,096 | 32 |
| `dn_in` | 5,120 | 40 | 2,048 | 16 |
| `dn_out` | 6,144 | 48 | 4,096 | 32 |
| `lm_head` | 5,120 | 40 | 2,048 | 16 |
| router | — | — | 2,048 | 16 |

**Exactly one image class breaks it, and 136 fits the 7-bit field.** What does
not fit is `XWIN_WORDS` (3,072 → 4,352), the `x_mem [32][MAX_NG]` distributed
array at `rtl/matvec_engine.sv:219`, and the 12-bit `xptr`/`wb_ptr`. This is
the 4B/9B study's wall 4 at a larger size — **L**, in the block that already
owns the design's worst waived endpoints. **The MoE's widest image is ng 32,
below even the 2B's 48: it PASSES with the pre-G3 envelope.**

### 2.6 Wall 5 — EMBLOG2, and the 27B's row that fits nowhere

`rtl/seq_unit.sv:346-347`:

```systemverilog
    localparam logic [4:0] EMBLOG2_RST = 5'd13;
    localparam logic [4:0] EMBLOG2_MIN = 5'd8, EMBLOG2_MAX = 5'd13;
```

The **field** is 5 bits and would carry 14; the **guard** caps it at 13, and a
write of 14 is rejected with the register left unchanged — the check is at
lines 1277 to 1281 of the same file. The address arithmetic is a shift,
`rtl/seq_unit.sv:933-934`:

```systemverilog
    wire [ADDR_W-1:0] emb_a = ADDR_W'({r_tgt, r_imm})
                              + (ADDR_W'(xrf[3]) << emb_row_log2);
```

so the stride is power-of-two by construction, and the host twin refuses both
(`sw/hwmap.py:343` `SEQ_EMBLOG2_MIN, SEQ_EMBLOG2_MAX = 8, 13`).

| model | H | natural row | padded row | EMBLOG2 | natural table | padded table | waste |
|---|---|---|---|---|---|---|---|
| 9B | 4096 | 8,192 B | — | **13** | 1,940.0 MiB | — | — |
| **27B** | 5120 | **10,240 B** | **16,384 B** | **14 — REFUSED** | 2,425.0 MiB | **3,880.0 MiB** | **+1,455.0** |
| 35B-A3B | 2048 | 4,096 B | — | **12** | 970.0 MiB | — | — |

> **The 27B's padded table does not fit its own channel.** `W_BASE` is 256 MiB
> (`sw/hwmap.py:483` `W_BASE = 0x1000_0000      # weight images packed from here (per channel)`)
> and the table sits above it on channel 0, so 256 + 3,880 = **4,136 MiB
> against a 4,096 MiB channel — before one weight byte is placed.** Lifting
> `EMBLOG2_MAX` to 14 therefore does not rescue the 27B; it moves the failure
> from the CSR to the address map. The real options are (a) non-power-of-two
> row addressing in `seq_unit`'s EMB path — new logic in a block on a bitstream
> that closed at exactly 0.000 — or (b) splitting the table across channels,
> which is host and emitter work plus a per-channel `EMB_BASE` (§3.3). **L.**

### 2.7 Walls 6, 7, 8, 11, 16 — the state caches, and a bank-count wall that came back

The amendment's three caches are declared in `rtl/layer_chan.sv`:

| kind | declaration | rows × width | slots |
|---|---|---|---|
| DN | `rtl/layer_chan.sv:772` `(* ram_style = "ultra" *) logic [2047:0] mem [4096];` | 4,096 × 2048 b | 2 |
| KV | `rtl/layer_chan.sv:836` `(* ram_style = "ultra" *) logic [2047:0] mem  [8192];` | 8,192 × 2048 b | 2 |
| conv | `rtl/layer_chan.sv:365` `localparam int CVD   = 8192;` | 8,192 × 112 b | 2 |

with `rtl/layer_chan.sv:382` `localparam int N_SLOT = 2;                    // cache slots per kind`,
`rtl/layer_chan.sv:361` `localparam int LNH   = 32;` (which is what fixes the
DN slot at 32 × 128 = 4,096 rows) and `rtl/layer_chan.sv:385`
`localparam int KV_AW  = 13;                   // {kv, t[11:0]}` (which is what
fixes `T_MAX` at 4,096).

`evidence/qwen_next/feas2/resource2.py` reproduces the shipped `OOC9B_URAM: 182` from those three
declarations and then sizes them (**D**, `f12`):

| model | DN rows | DN | KV rows | KV | conv rows | conv | **total of 960** | one SLR? |
|---|---|---|---|---|---|---|---|---|
| 9B | 4,096 | 58 | 8,192 | 116 | 8,192 | 8 | **182 (19.0 %)** | YES |
| **27B** | **6,144** | **116** | 8,192 | 116 | **10,240** | **12** | **244 (25.4 %)** | YES |
| **35B-A3B** | 4,096 | 58 | 8,192 | 116 | 8,192 | 8 | **182 (19.0 %)** | YES |

**The URAM wall that dominated the 4B/9B study is gone.** That study's headline
was 928 of 960 (96.7 %) across three SLRs; the state-spill amendment replaced
that design, and **neither new target comes near it** — the 27B's array is
244 and fits one SLR with room, and the MoE's is *identical to the shipped
one*. The 27B's DN growth is a **second rank**, not a wider row: 6,144 rows do
not fit a URAM288's 4,096, and the 2,048 unused rows of the second rank cannot
be reclaimed because the aspect ratio is fixed.

> **But the bank count came back as a NEW wall, row 16.** SLD/SST carry a
> 5-bit layer field — `rtl/layer_chan.sv:1380` `wire [4:0] sd_layer_a = arg0[9:5];`
> — range-checked against `rtl/layer_chan.sv:362` `localparam int N_DN  = 24;`
> and `rtl/layer_chan.sv:363` `localparam int N_KV  = 8;`. So the DMA lane can
> address **at most 24 DeltaNet layers and 8 attention layers**, and the DDR
> region is sized to match on the host side, `sw/hwmap.py:562`
> `STATE_DN_BLOCKS, STATE_KV_BLOCKS, STATE_CV_BLOCKS = 24 * 32, 8 * 4 * 2, 24`.
> **Both targets fail it as WHOLE models** — 48/16 and 30/10 — **and both
> PASS it under the midpoint pipeline split this study prices in §3.3 and
> §4.5.** Counted from each checkpoint's own `layer_types` list — **not** from
> `full_attention_interval`, which `evidence/qwen_next/feas2/fix1_checks.py` avoids on purpose:
>
> | model | whole model | pipeline at the midpoint, per board |
> |---|---|---|
> | **27B**, cut@32 | 48 DN / 16 GQA — **FAIL** | **24 DN / 8 GQA — PASS, EXACTLY at `N_DN` 24 and `N_KV` 8** |
> | **35B-A3B**, cut@20 | 30 DN / 10 GQA — **FAIL** | **15 DN / 5 GQA — PASS with room** |
>
> **This is the one wall where the choice of split changes the wall**, and it
> cuts both ways. Counting every cut of each model, not just the midpoint
> (**D**, `evidence/qwen_next/feas2/f15_fix1_checks.log`):
>
> | model | cuts that pass on BOTH boards | which |
> |---|---|---|
> | **27B** (64 layers) | **1 of 63** | **only cut@32** |
> | **35B-A3B** (40 layers) | **25 of 39** | cut@8 through cut@32 |
> | *9B, for scale* | *31 of 31* | *the whole model already passes* |
>
> **The 27B's pipeline is not merely knife-edge — there is exactly ONE legal
> cut**, so the split cannot be moved at all, not by one layer, to balance load
> or footprint. A *tensor*-parallel 27B, which leaves all 64 layers on both
> boards, needs a sixth bit in `sd_layer_a` plus `N_DN` 48 / `N_KV` 16. The MoE
> has 25 legal cuts and still fails under tensor- or expert-parallel with
> replicated mixers, where raising the two constants to 30/10 suffices because
> the 5-bit field already carries 32.

### 2.8 Walls 9 and 10 — the two head fields, and how close the MoE sits

`rtl/layer_chan.sv:1513` `dn_head <= arg0[4:0];` — five bits, backed by
`rtl/layer_chan.sv:383` `localparam int HB     = $clog2(LNH);          // 5  dn_head width`
and `rtl/gate_unit.sv:17` `parameter int NH = 32,`. **27B needs 48 heads and
fails; the MoE needs exactly 32 and passes at the ceiling.**

`rtl/layer_chan.sv:1514` `kvhead_r <= arg0[1:0];` — two bits, backed by
`rtl/layer_chan.sv:364` `localparam int NKVH  = 4;`. **27B needs exactly 4 and
passes at the ceiling; the MoE needs 2.**

> **THREE of the MoE's rows sit exactly at a ceiling** — `dn_head` 32 of 32,
> `CONV_DIM` 8,192 of `CVD` 8,192, and the DN cache slot's 4,096 rows of 4,096.
> (An earlier revision said five and counted two rows that have real headroom:
> **`kvhead` 2 of 4** is at **half** the ceiling and **`ng` 32 of 96** at **one
> third**, which is what §2.1's row 9 already records. Those two are margin,
> not coincidence.) The three that do sit on the line are not comfort — they
> are the same geometry the shipped bitstream was built for, which is exactly
> why it fits, and any later checkpoint that moves one of them moves a wall.

### 2.9 Walls 12–15 — four rows the 9B campaign already closed

* **12, multi-shard.** `ref/load_qwen35.py:96` globs
  `pat = os.path.join(root, REPO_DIR, "snapshots", "*", "*.safetensors")` and
  `ref/load_qwen35.py:98` `hits = sorted(glob.glob(pat))`; the shards are merged
  with a duplicate-key check. No shard-count limit, no index file read.
  **11 and 14 shards both PASS.**
* **13, untied head.** `ref/load_qwen35.py:253-255` reads the flag top-level
  first and falls back to `text_config`; `ref/load_qwen35.py:262-268` derives
  `tied` from the *tensor* and **cross-checks it against the config**, raising
  on disagreement. Both targets are untied, exactly like the shipped 9B.
  **PASS.**
* **14, the key/value head algebra.** The 4B/9B study's wall — `LKD = LNVH·LDK`
  — is **closed**: `ref/layer_ref.py:46` is `LKD = LNKH * LDK                          # 2048 everywhere so far`
  and `ref/scripts/bytes_per_token.py:129` is
  `LKD = LNKH * cfg["linear_key_head_dim"]`. **This is load-bearing for this
  study**: it is why `evidence/qwen_next/feas/ddr_fit.py`'s LKD workaround must
  NOT be reused (it would double-correct), and why `evidence/qwen_next/feas2/ddr_fit2.py` passes the true
  config values and checks the derived `CONV_DIM` against the checkpoint's own
  `conv1d` row count. One residual: `sw/chat_seq.py:173`
  `_GEOM_08B = dict(HD=256, LDK=128, LDV=128, LNH=16, ROT=64)` is a `ref`-less
  host fallback with no `LNKH` key at all.
* **15, the SCA scalar tiles.** Closed by adoption:
  `ref/gen_layer_script.py:125-128` places them with `max(32, …)` floors and
  `ref/gen_layer_script.py:200` moves `STG` with `SCA_SZ`. At 48 DeltaNet heads
  the map simply grows to `SCA_SZ` 1,136 (`f10`). **PASS.**

### 2.10 Wall 17 and wall 22 — the shared rows

**17, geometry rot.** Every per-model literal needs a new row, and one of them
**raises on import**: `ref/layer_fixed.py:103`
`RS_F_BY_TAG = {"0.8b": 8, "2b": 8, "4b": 8, "9b": 7}` is indexed at
`ref/layer_fixed.py:104` `_RS_F_LAW = RS_F_BY_TAG[_MS.TAG]`, so a new
`FABLE5_MODEL` tag is a `KeyError` at import time. The tag table itself is
`ref/model_select.py:12-17`, whose `:21-23` already refuses an unknown tag
cleanly. The dangerous one is `sw/chat_seq.py:567-575`, whose
`TEMPLATE4_BY_MODEL` `.get(MODEL_TAG, …)` **silently falls back to the 0.8B
template**. Also carrying 9B literals: `ref/seq_chat.py:178`,
`sw/chat_seq.py:250`, `sw/chat_seq.py:3128`, `sw/infer.py:98`, and
`sw/infer.py:99` `KV_DEPTH = 512            # rtl/layer_chan.sv: kv_waddr uses tcnt[8:0]`,
which is **stale** against `seq_chat`'s 4,096. One host limit both targets
clear: `sw/infer.py:675`
`assert self.vocab <= (1 << 18), "vocab exceeds the 18-bit AMAXI port"` —
248,320 passes with 5.6 % to spare, the same headroom
`docs/ARCHITECTURE.md` already flags.

**22, the context ceiling.** `NEXT_SESSION.md` §9(a) item 1 pins it:
`rtl/attn_core.sv:114`'s 40-bit `denom` bounds usable context at **T < 512 by
analysis**, and that is unchanged by anything in this study. Both targets
inherit it. Say "reachable" only with that attached.

### 2.11 Wall 18 (**NEW**) — there is no router, and the pieces that exist cannot be assembled on chip

This is the MoE's first structural wall, and it is precise.

**No opcode computes a top-k or a normalisation.** The SEQ opcode set is
`rtl/seq_unit.sv:271-274`:

```systemverilog
    localparam logic [7:0] OP_CSRWR = 8'h01, OP_CMD  = 8'h02, OP_MOVX = 8'h03,
                           OP_MOVY  = 8'h04, OP_MVGO = 8'h05, OP_EMB  = 8'h06,
                           OP_AMAXL = 8'h07, OP_JMP  = 8'h08, OP_FENCE= 8'h09,
                           OP_HALT  = 8'h0A, OP_LDC  = 8'h0B, OP_XOP  = 8'h0C;
```

and the layer command set is 1..12 plus the amendment's 13 SLD / 14 SST. No
TOPK, no ROUTER, no GATHER.

**What exists, and exactly how far it gets.**

* **`AMAX32`, ALU sub-op 10** (`rtl/vec_alu.sv:25-32`): a running argmax over
  `len` int32 pairs, chainable across chunks, winner on `amax_idx`/`amax_val`.
  It gives **one** winner, not eight.
* **`layer_topk32`** (`rtl/layer_chan.sv:2745` `module layer_topk32 (`) is a
  **passive sidecar**, not an opcode, fed from the AMAX32 compare site, with
  `rtl/layer_chan.sv:2761` `localparam int K = 32;`. It would hold a top-8 of
  256 easily.
* **And its readback is HOST-ONLY.** `docs/SEQ_ISA.md:592`
  `0x50 TK_PTR    RW {27'b0, ptr[4:0]}  entry cursor` and
  `docs/SEQ_ISA.md:594` `0x58 TK_IDX    R  {14'b0, idx[17:0]} of entry[ptr] — PTR++ ON READ`
  are AXI-Lite registers. **There is no CSR-read opcode in the SEQ ISA at all**;
  the single CSR→sequencer path is hard-wired to one address,
  `rtl/seq_unit.sv:1375-1376`:

```systemverilog
            I_AMAX: begin fsm_rd_valid = 1'b1;
                          fsm_rd_addr  = LAYER_BASE + {20'd0, L_AMAXI}; end
```

  i.e. `OP_AMAXL` reads **only** `L_AMAXI` into `XRF[3]`. **So the top-32 list
  is visible to the host and to nothing else.** A router that must select
  experts *within* a token would round-trip through the host every layer —
  which is precisely the cost the sequencer exists to remove.

**What a router needs and what the ALU has.** Sub-ops are `0 DYNQ8`,
`1 SHIFT32`, `2 SCALE`, `3 EMUL`, `4 ADD`, `5 SILU16`, `6 SILU32`, `7 SIGM16`,
`8 EMUL32`, `9 SHIFT32W`, `10 AMAX32`, `12 DYNQ16`. A softmax router needs
`exp` and a reciprocal: `fx_recip` exists but only inside `attn_core`
(`rtl/attn_core.sv:96`), and the exp pipeline likewise. **Neither is reachable
from a routing vector.** Whether the top-8 weights are renormalised at all is
§1.2's UNKNOWN; under a sigmoid-gate reading it is one `SIGM16` and no
reciprocal, under a softmax reading it is a new datapath. **The difference
between the two readings is the difference between M and L on this row.**

**Row 21, the good news, and the only PASS among the MoE's four new walls.** The
shared expert's `shared_expert_gate` is `[1, 2048]` — one dot product, one
sigmoid, one multiply — and `SIGM16` is exactly a Q15 sigmoid over a vector.
That piece costs nothing.

**And nothing the project WROTE has any MoE awareness.** Grepping `ref/`,
`sw/`, `rtl/` and `docs/SEQ_ISA.md` for an expert or a router returns seven
hits, and **five of them are HuggingFace config sentinels in vendored upstream
code** — `ref/vendor/modular_qwen3_5.py:118-122`, a block of
`AttributeError()` placeholders naming `shared_expert_intermediate_size`,
`num_experts_per_tok`, `num_experts`, `output_router_logits` and
`router_aux_loss_coef`. **Not one line of this project's own RTL, emitter, host
or ISA knows what an expert is.** A `top_k` does appear in several places —
`sw/serve.py`'s and `sw/chat_seq.py`'s host-side **token** samplers,
`sw/head_cache.py`, `ref/fidelity_check.py`, and `sw/hwmap.py`'s mirror of the
TOPK-32 CSR block — and **not one of them is a router**: every one is host-side
sampling, fidelity scoring, or the CSR view of `layer_topk32`. (An earlier
revision wrote "the only `top_k` in the tree"; that was wrong, and the
conclusion is unaffected.)

### 2.12 Walls 19 and 20 (**NEW**) — the weight stream is static BY CONSTRUCTION

This is the decisive finding of the MoE half of this study.

**MVGO's weight address is a compile-time record field.** The format is
`docs/SEQ_ISA.md:116-117`:

```
  - MVGO: imm32=SHAPE, addr_lo=WBASE[31:0],
    len_or_addr_hi={beats[23:0], wbase[39:32]}.
```

consumed verbatim at lines 1035 to 1037 of `rtl/seq_unit.sv`, which latch
`mv_shape`, `mv_wbase` and `mv_beats` straight out of the record. And
**indirection is refused at decode**, `rtl/seq_unit.sv:787-788`:

```systemverilog
            OP_MOVX, OP_MVGO: begin
                if (r_ind != IND_NONE)           begin v_bad=1; v_code=E_IND; end
```

**Is there any data-dependent control anywhere?** Three places, and none of
them reaches the weight port:

* `OP_JMP` is unconditional or a `TCNT` countdown. **No compare, no predicate,
  no data-dependent branch.**
* `LDC` takes a run-time `XRF` offset on its DDR address, but its destination
  is the **scratchpad**. One MoE expert's `gate_up` slice is ≈ 1 MiB at W4;
  eight experts × two tensors is ≈ 12 MiB per layer. **LDC cannot serve expert
  gather.**
* `EMB` is the one genuinely data-dependent address in the machine —
  `rtl/seq_unit.sv:933-934`, quoted in §2.6 — and it is hard-wired to `XRF[3]`,
  which only `AMAXL` writes. **It is the right shape (score → index → address)
  at one-eighth the required width and in the wrong unit.**

> The fused expert tensors make the *data layout* easy and the *control* hard.
> Because `gate_up_proj` is `[256, 1024, 2048]` and `down_proj` is
> `[256, 2048, 512]`, expert *e* is simply a **row range** inside one image —
> `[e·1024, (e+1)·1024)` and `[e·2048, (e+1)·2048)`. So expert gather is a
> **row-offset** problem, not an image-selection problem, and the layer's own
> DMA lane already has base-CSR-plus-index-shift addressing
> (`docs/SEQ_ISA.md:1273-1281`). What it does not have is an index that comes
> from **data** rather than from a compile-time `arg0` field.

**Wall 20 — and the emitter cannot even express it.** The emitted stream is one
fixed schedule per token, and the loop closure *requires* that: the weight
address is a Python integer at emit time (`ref/seq_format.py:2006-2008`), and
`ref/seq_format.py:2324` `def _try_loop(self):` closes the token loop only when
consecutive bodies are byte-identical — `ref/seq_format.py:2331`
`while tail < len(bodies) and bodies[-1 - tail] == bodies[-1]:`, failing with
`ref/seq_format.py:2359` `why = "step bodies differ"`. The module header records
that three data-dependent immediates had to be **removed** for a stack with
full-attention layers to close its loop at all.

> **A data-dependent expert selection reintroduces exactly the class of
> divergence that work eliminated.** With 256 experts and top-8, consecutive
> token bodies differ in 8 of 2·40 MVGO weight bases per layer, `_try_loop`
> returns "step bodies differ", and either every token is emitted **unrolled**
> or every expert is run **densely** — 32× the FFN work, which is 32 × 1,153 M
> = 36.9 G active parameters per token and worse than the 27B.
>
> **The honest summary of rows 18–20: the MoE is not a width problem, it is a
> new sequencer feature.** Minimum: (a) an on-chip path that gets top-k
> *indices* into `XRF`-like registers, where today exactly one argmax index can
> go, via one hard-wired CSR read; and (b) an indirected MVGO whose weight base
> is a register value plus a scaled index rather than a literal — refused today
> at `rtl/seq_unit.sv:788`.
> (b) is a modest RTL change — the `LDC` machinery is next door. **(a) is the
> real work, because it needs a TOPK-to-XRF path and a k-way loop construct the
> ISA has no branch for.**

---

## 3. DDR fit — one board, then two (**D**, `f05`/`f07`)

`evidence/qwen_next/feas2/ddr_fit2.py` is a **new** script, not an edit of the
committed `evidence/qwen_next/feas/ddr_fit.py`, for two stated reasons: that file's `LKD` workaround is
now *wrong* (§2.9 — the bug it routed around is fixed, so it would
double-correct), and the MoE has no `intermediate_size` so its image list must
come from the checkpoint's fused expert tensors. It monkeypatches
`bytes_per_token.inventory` and leaves `fit`, `packed_footprint` and
`per_channel_bytes` — the shipped allocator and this project's own
re-implementation of the split — running unchanged over it.

**Validation first, and it is exact.** The shipped 9B W4 g128 pack reproduces
4,091,805,696 B/token, the per-channel 978.40 / 975.30 / 974.27 / 974.27 MiB
and max/min 1.004234 — every figure transcribed in
`evidence/qwen9b/g6/RD9_GATE.md` §10.3 — and the assert fires before one new
number is printed. Each image list is separately cross-checked against the
checkpoint's own `conv1d` row count and parameter census.

### 3.1 Streamed bytes per token, and the resident pack — one board, nch=4

| map | model | images | B/token **streamed** | MiB/tok | b/w | pack MiB | busiest chan | % of 1,280 | % of 3,840 |
|---|---|---|---|---|---|---|---|---|---|
| **W8 g128** | 9B | 249 | 8,059,617,280 | 7,686.2 | 8.125 | 7,686.9 | 1,927.3 | 150.6 % | 50.2 % |
| | **27B** | 497 | **26,216,366,080** | **25,001.9** | 8.186 | 25,002.8 | 6,257.8 | 488.9 % | 163.0 % |
| | **35B-A3B** | 431 | **3,067,371,520** | **2,925.3** | 8.486 | **34,546.1** | 8,639.4 | 674.9 % | 225.0 % |
| **W4 g128** | 9B | 249 | 4,091,805,696 | 3,902.2 | 4.125 | 3,902.9 | 978.6 | 76.5 % | 25.5 % |
| | **27B** | 497 | **13,405,388,800** | **12,784.4** | 4.186 | 12,784.6 | 3,199.8 | 250.0 % | 83.3 % |
| | **35B-A3B** | 431 | **1,605,263,360** | **1,530.9** | 4.488 | **18,271.7** | 4,569.4 | 357.0 % | 119.0 % |
| **W4 g64** | 27B | 497 | 13,734,051,840 | 13,097.8 | 4.288 | 13,099.2 | 3,278.5 | 256.1 % | 85.4 % |
| | 35B-A3B | 431 | 1,610,506,240 | 1,535.9 | 4.489 | 18,276.7 | 4,570.6 | 357.1 % | 119.0 % |

"% of 1,280" is the **as-built** per-channel weight window, `EMB_BASE − W_BASE`
(`sw/hwmap.py:483` and `sw/hwmap.py:486` `EMB_BASE = 0x6000_0000    # embedding table (channel 0)`);
"% of 3,840" is the window a **per-channel runtime `EMB_BASE`** would give on a
channel with no embedding table, which is the fix
`docs/QWEN35_NEXT_FEASIBILITY.md` §3.2 priced at 0.055 % of throughput.

> **Read the MoE row twice.** Its *streamed* 1,530.9 MiB/token is **39 % of the
> shipped 9B's 3,902.2**, and its *resident* pack is **18,271.7 MiB — 4.7× the
> 9B's**. The two columns are never added and they answer different questions:
> the first sets the matvec term, the second decides how many boards. The MoE's
> `b/w` is 4.488 rather than 4.125 because `down_proj`'s K is only 512, so each
> row carries four groups' scales over a short row — the scale overhead does not
> amortise.

### 3.2 One board: does the whole model fit 4 × 4 GiB?

| model | map | weights GiB | embedding GiB | total GiB | % of 16 | verdict |
|---|---|---|---|---|---|---|
| 9B | W8 | 7.507 | 1.895 | 9.401 | 58.8 % | **FITS** (shipped) |
| 9B | W4 g128 | 3.811 | 1.895 | 5.706 | 35.7 % | **FITS** (shipped) |
| **27B** | W8 | 24.417 | 3.789 | 28.206 | 176.3 % | **OVER** |
| **27B** | **W4 g128** | **12.485** | **3.789** | **16.274** | **101.7 %** | **OVER by 281 MiB** |
| **27B** | W4 g64 | 12.792 | 3.789 | 16.581 | 103.6 % | **OVER** |
| **35B-A3B** | W8 | 33.736 | 0.947 | 34.684 | 216.8 % | **OVER** |
| **35B-A3B** | **W4 g128** | **17.843** | **0.947** | **18.791** | **117.4 %** | **OVER** |

> **The 27B's one-board verdict turns entirely on EMBLOG2.** With the
> **natural** 10,240 B embedding row the table is 2.368 GiB and the total is
> **14.853 GiB — 92.8 %, FITS.** With the **padded** 16,384 B row it is 3.789
> GiB and the total is 16.274 GiB, over by **281 MiB**. The padding costs 1,455
> MiB to save nothing: the padded table does not even fit its own channel
> beside `W_BASE` (§2.6). So *"27B on one board"* is not obviously dead — it is
> **blocked by §2.6's wall 5 and by nothing else in the address map**, and if
> that wall were opened it would be a one-board model with 7 % spare. This
> study does not recommend it: §2's other seven walls do not go away, and the
> modelled throughput (§4) is 2.44 tok/s.

> **The MoE cannot be a one-board model at any precision this project has.**
> 17.8 GiB of weights at W4 g128 over 16 GiB of DDR, and W4 g64 saves nothing
> (5 MiB). Only a fundamentally denser format — W2, or streaming experts from
> the host — would change that, and neither exists here.

### 3.3 Two boards, per channel — and why the runtime `EMB_BASE` is mandatory

Board A keeps the PCIe host and the embedding table; board B has power only.
Packed MiB per channel under the shipped allocator's law (**D**, `f07`):

| model | map | split | board | ch0 | ch1 | ch2 | ch3 | total | worst vs 1,280 | worst vs 3,840 |
|---|---|---|---|---|---|---|---|---|---|---|
| **27B** | W4 g128 | pipeline cut@32, head on B | A | 1,518.5 | 1,518.5 | 1,518.5 | 1,518.5 | 5.932 GiB | **FAIL** | **PASS** |
| | | | B | 1,681.2 | 1,677.3 | 1,676.0 | 1,676.0 | 6.553 GiB | **FAIL** | **PASS** |
| | | tensor-parallel | A/B | 1,599.9 | 1,597.9 | 1,597.2 | 1,597.2 | 6.242 GiB | **FAIL** | **PASS** |
| **27B** | W8 | pipeline cut@32, head on B | A | 2,970.0 | 2,970.0 | 2,970.0 | 2,970.0 | 11.602 GiB | FAIL | PASS |
| | | | B | 3,287.8 | 3,280.1 | 3,277.5 | 3,277.5 | 12.815 GiB | FAIL | PASS |
| **35B-A3B** | W4 g128 | pipeline cut@20, head on B | A | 2,251.8 | 2,251.8 | 2,251.8 | 2,251.8 | 8.796 GiB | **FAIL** | **PASS** |
| | | | B | 2,317.6 | 2,316.0 | 2,315.5 | 2,315.5 | 9.048 GiB | **FAIL** | **PASS** |
| | | expert-parallel, mixers replicated | A | 2,343.5 | 2,343.5 | 2,343.5 | 2,343.5 | 9.154 GiB | **FAIL** | **PASS** |
| | | | B | 2,409.4 | 2,407.8 | 2,407.3 | 2,407.3 | 9.406 GiB | **FAIL** | **PASS** |
| **35B-A3B** | W8 | pipeline cut@20, head on B | A | 4,255.7 | 4,255.7 | 4,255.7 | 4,255.7 | 16.624 GiB | FAIL | **FAIL** |
| | | | B | 4,383.6 | 4,380.5 | 4,379.5 | 4,379.5 | 17.112 GiB | FAIL | **FAIL** |

**At W4 g128, every two-board split of either model FAILS the as-built 1,280
MiB window and PASSES the 3,840 MiB runtime one.** (At W8 the MoE fails both,
as the table's last four rows show; the 27B passes the runtime one.) The per-channel runtime `EMB_BASE` is
therefore not an optimisation here, as it was for the 9B at W8 — it is a
**precondition** for any configuration in this study. And **W8 does not fit two
boards for either model**: the MoE is over even the runtime window, and the
27B's 12.8 GiB per board is only under it because the embedding channel would
have to be re-planned as well.

**Channel 0's own ceiling.** Under a per-channel runtime `EMB_BASE` the
hosting channel has `4,096 − 256 − (the table)` MiB of weight room:

| model | table | ch0 weight room | ch0 weights needed | verdict |
|---|---|---|---|---|
| **27B**, padded row | 3,880 MiB | **−40 MiB** | 1,518.5 | **FAIL — the table alone overflows** |
| **27B**, natural row | 2,425 MiB | 1,415 MiB | 1,518.5 | **FAIL by 103.5 MiB** |
| **35B-A3B** | 970 MiB | 2,870 MiB | 2,251.8 | **PASS**, 618 MiB spare |

> **Even with a non-power-of-two embedding row, the 27B's channel 0 does not
> hold the table plus its quarter of the weights** — it misses by 103.5 MiB
> (**D**: 1,518.5 − 1,415). The table would have to be split across channels,
> or the weight split made asymmetric. **The MoE's channel 0 passes with 618
> MiB to spare.** This is the same shape of finding as
> `docs/QWEN35_NEXT_FEASIBILITY.md` §3.2's zero-slack 9B W8 channel, one step
> worse.

### 3.4 The state region per board, and what the DMA lane carries

The shipped law is `docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md`
§2's block table. At the new geometries (**D**, `f07`; `T` for the 9B row's
comparand):

| model | T | DN | KV | conv | **region** | **traffic/token** |
|---|---|---|---|---|---|---|
| 9B | 512 | 24.00 | 128.00 | 3.00 | **155.00 MiB** | **70.00 MiB** (**T** 70.06, `evidence/qwen9b/g6/RD9_GATE.md` §10.3) |
| 9B | 4,096 | 24.00 | 128.00 | 3.00 | 155.00 MiB | **182.00 MiB** (**T** 182.50) |
| **27B** | 512 | 72.00 | 256.00 | 6.00 | **334.00 MiB** | **188.00 MiB** |
| **27B** | 4,096 | 72.00 | 256.00 | 6.00 | 334.00 MiB | **412.00 MiB** |
| **35B-A3B** | 512 | 30.00 | 80.00 | 3.75 | **113.75 MiB** | **77.50 MiB** |
| **35B-A3B** | 4,096 | 30.00 | 80.00 | 3.75 | 113.75 MiB | **147.50 MiB** |

The 0.06 / 0.50 MiB the 9B rows miss by are the KV exponent side arrays rounded
up to a 64 B beat, which this arithmetic does not model; the agreement is
0.09 % and 0.27 %. **The region is small on every geometry** — a third of a GiB
at worst — but the *traffic* is not: at 27B and T = 4,096 it is 412 MiB/token
on **one channel**, since the region lives on channel 3 alone. The shipped 9B's
DMA lane measured 5.125 ms/token against a 137.121 ms step
(`evidence/qwen9b/g6/RD9_GATE.md` §10.2) and **overlapped** the compute lane;
27B's 2.3× traffic on a longer step is very likely still hidden, but that is
**E** and nothing here measures it.

**Under a two-board split the region splits with the layers** (pipeline) or is
**replicated** (tensor-parallel, expert-parallel with replicated mixers). Board
B's region is its own DDR and it is written over the link at load time —
113.75 MiB at worst, a rounding error beside the weights (§5.4).

---

## 4. Modelled tok/s (**E**, `f13`)

### 4.1 The model, extended not replaced

`evidence/qwen_next/feas2/toks2_model.py` **imports**
`evidence/qwen_next/feas/toks_model.py` and uses its constants, its mover cost
law, its counters, its two-component layer proxy and its `(r, m)` solve
unchanged. The step law is `docs/QWEN35_NEXT_FEASIBILITY.md` §4.1's:

```
step_ms  =  busiest_channel_beats · r / f_ui   +   movers_counted · m   +   layer
```

with `r = 1.1037` ui-cyc/beat and `m = 0.9117` **quoted, not re-fitted**. Two
board terms are added:

```
board_step = matvec(that board's busiest channel) + movers(that board's images)
             + layer(that board's share)
link_ms    = transfers/token · latency  +  bytes/token / rate
```

**One thing had to be restated rather than imported.** `toks_model.fit_layer()`
**raises at HEAD**: it builds its configs through `ddr_fit.cfg_for`, which emits
no `linear_num_key_heads`, and `ref/scripts/bytes_per_token.py:124`
`LNKH = cfg["linear_num_key_heads"]` now requires it. The committed study's
script is **not edited** — its logs cite it by line — so the same arithmetic is
restated in `evidence/qwen_next/feas2/toks2_model.py` over configs carrying true key-head counts, and
asserted against the committed `A = 2.261123283318704e-06` and
`Bv = 1.2744815668202769e-05` (to 1e-18) and against the committed 47.00 ms 9B
layer term.

### 4.2 The committed model, scored against the 9B that has since shipped — and the score is worse than it looks

When `evidence/qwen_next/feas/toks_model.py` was written the 9B was a projection. It has since shipped
and been measured. **T**, `evidence/qwen9b/g6/RD9_GATE.md` §10.1/§10.2:
**137.1413 ms/token steady state, 7.2917 tok/s, `L_LCYC` 41.588 ms/token,
`L_SDMA_CYC` 5.125 ms/token.**

| the committed terms at 9B W4 g128 | value |
|---|---|
| matvec | 58.95 |
| movers | 32.67 |
| layer, **extrapolated** | **46.99** |
| **modelled step** | **138.60 ms** |
| **measured step** | **137.1413 ms** |
| **error at the step** | **+1.07 %** |
| the same terms with the board's `L_LCYC` 41.588 in place of the model's layer | **133.20 ms, −2.87 %** |

**And there are THREE comparands for the layer term, not two.** This is the
thing that governs every projection in this document, and the study's own
primary source states it:

| the layer term at 9B W4 g128 | value | what it is |
|---|---|---|
| this model, extrapolated | **46.99 ms/token** | **E** |
| Task 14-A's chip-TB census, **like for like**, holds charged and 14A's pipelining accounted | **46.161 ms/token** | **D**, `evidence/qwen9b/g6/RD9_GATE.md` §10.2a — that section marks the row **(D)**: 46.158 is the measured holds-charged census and 46.161 adds 14A's +1-cycle-per-command pipelining, derived |
| the board's `L_LCYC`, read once after HALT | **41.588 ms/token** | **T**, `evidence/qwen9b/g6/RD9_GATE.md` §10.2 |

> **HONESTY CHECK, and it governs every figure below.**
>
> * **Against the like-for-like census the model is +1.8 %** (46.99 / 46.161).
>   That is the comparand built from the same script on the same netlist with
>   the holds charged, and it is the one a modelled layer term should be scored
>   against.
> * **The board is 9.9 % BELOW that census** — `evidence/qwen9b/g6/RD9_GATE.md`
>   §10.2a computes `(41.588 − 46.161)/46.161 = −9.91 %` and closes with
>   *"the delta is real, it is measured on both sides, and this gate does not
>   know why."* **RD9 explicitly declines to attribute it.**
> * So the apparent **+13 %** against 41.588 is the model landing on the
>   project's own census and the *board* sitting below **both**, for an
>   unexplained reason. **An unattributed instrument gap is not a model error
>   and must never be turned into a multiplier.**
>
> **An earlier revision of this document did exactly that**: it carried a
> "corrected" column in §4.3, §4.4, §4.5, §7.1 and §8.2, rescaled by
> `41.588 / 46.99 = 0.8851`, and handed those figures to the user as decision
> evidence. **Every one of them is withdrawn.** The tables below carry the
> modelled figures only. `evidence/qwen_next/feas2/f11_toks2_model_fix.log` and
> `evidence/qwen_next/feas2/f13_toks2_model_rates.log` still PRINT a `corr`
> column, because the logs are the record of what was run and are not rewritten
> — **this document does not use it, and §6 item 13 says why.**
>
> **Two further reasons the board figure is not a clean comparand.** `L_LCYC`
> is a busy counter, not an exclusive serial share: `evidence/qwen9b/g6/RD9_GATE.md`
> §10.2 records that the compute and DMA lanes **overlap** — 41.588 + 5.125 =
> 46.713 ms of lane time inside a 137.121 ms step, so neither lane is the
> critical path. And **the 9B is not the same machine as the two calibration
> points**: 0.8B and 2B were measured on `build_034`/`build_035`, whose layer
> state lived in URAM, while the 9B is post-state-spill. `A` and `Bv` are
> **not** re-fitted on it; folding a third bitstream into a two-point fit would
> mix two machines.

**What the tables below therefore carry**: the modelled figure, and nothing
rescaled. The honest uncertainty on the layer term is the +1.8 % against the
census plus the unattributed 9.9 % the board sits below it — i.e. the true
value on silicon could be anywhere in that span, and this document does not
know where.

### 4.3 The layer term at the new geometries

The DeltaNet recurrence is serialized over heads through one engine
(`docs/QWEN35_NEXT_FEASIBILITY.md` §4.3's primary sources, unchanged), so the
head-indexed bucket scales with `n_DN × LNVH`:

| model | n_DN | LNVH | **DNST/token** | invariant work | width work | **layer ms** | × the 9B's own modelled 46.99 |
|---|---|---|---|---|---|---|---|
| 9B | 24 | 32 | **768** | 13,369,344 | 1,314,816 | **46.99** | 1.00 |
| **27B** | 48 | **48** | **2,304** | 39,714,816 | 3,544,064 | **134.97** | **2.87** |
| **35B-A3B** | 30 | 32 | **960** | 16,711,680 | 698,368 | **46.69** | 0.99 |

**The 27B's DNST count is 3× the shipped 9B's**, and that alone is 2,304 heads
× ~1300 cycles ÷ 250 MHz = **11.98 ms/token** of pure recurrence. The MoE's is
1.25× the 9B's, and its *width* bucket is **half** the 9B's because H is 2048
and the per-token FFN width is `(8+1) × 512 = 4,608` rather than 12,288 — so
its layer term lands within 1 % of the shipped 9B's.

### 4.4 One board, if capacity were not a limit (it is — §3.2)

| model | map | MiB/tok | busiest | matvec | movers | layer | **step ms** | **tok/s** |
|---|---|---|---|---|---|---|---|---|
| *9B* | *W4 g128* | *3,902.2* | *978.4* | *58.95* | *32.67* | *46.99* | ***138.60*** | ***7.21*** |
| | | | | | | | *(measured **137.14 / 7.2917**)* | |
| 9B | W8 | 7,686.2 | 1,927.1 | 116.12 | 32.67 | 46.99 | 195.77 | 5.11 |
| **27B** | **W4 g128** | 12,784.4 | 3,199.7 | **192.79** | 82.88 | **134.97** | **410.64** | **2.44** |
| **27B** | W8 | 25,001.9 | 6,257.5 | 377.03 | 82.88 | 134.97 | 594.88 | **1.68** |
| **35B-A3B** | **W4 g128** | 1,530.9 | 384.2 | **23.15** | 28.75 | **46.69** | **98.58** | **10.14** |
| **35B-A3B** | W8 | 2,925.3 | 734.2 | 44.23 | 28.75 | 46.69 | 119.67 | **8.36** |

> **The MoE is modelled FASTER than the shipped 9B on one board — 10.14 against
> a measured 7.2917 — and it cannot run on one board.** That is the study in one
> line. Its matvec term is 23.15 ms against the 9B's 58.95, because it streams
> 39 % of the bytes; its layer term is the same; its mover term is slightly
> lower. It is a *smaller* per-token machine inside a *bigger* memory.

Where the time goes (**D**):

| model | map | matvec | movers | layer |
|---|---|---|---|---|
| 9B | W4 g128 | 42.5 % | 23.6 % | 33.9 % |
| **27B** | W4 g128 | **46.9 %** | 20.2 % | **32.9 %** |
| **35B-A3B** | W4 g128 | **23.5 %** | 29.2 % | **47.4 %** |

The MoE is **layer-bound**, and it is the first *large* target to come back
that way — not the first target. The **measured 0.8B at W4 g128 was more
layer-bound still**: `evidence/qwen_next/feas/f05_toks_model.log:61` carries
`0.8B W4: matvec 5.4754*r + movers 11.332*m + layer 15.128 = 31.5023`, and at
the solved `r`/`m` that is **layer 48.0 %, matvec 19.2 %** of a 31.502 ms step
(**D**, `evidence/qwen_next/feas2/f15_fix1_checks.log`). So the MoE does not
break new ground — **it recovers the 0.8B's
profile at 30× the parameter count**, which is the stronger point. That
matters for where a subsequent optimisation rung would pay, and it is the
opposite of the 9B's W8 profile.

### 4.5 Two boards, per split (**E**, `f13`, W4 g128)

**All numbers below are E.** The link term is assumed throughout: 4 lanes ×
25.78125 Gb/s with 64B/66B already inside that figure gives **12.50 GB/s**
payload; the sweep also carries 90 % of that and a single lane; the one-way
latency bracket is **0.5 / 1.0 / 2.0 µs**, which is a **guess**, not a
datasheet figure (§6 item 3). Activations cross as int16 (2 B/element,
matching the design's Q8.7 residual); tensor-parallel reduce partials as
4 B/element before requantisation.

#### 27B

| split | board A | board B | link/token | **tok/s** |
|---|---|---|---|---|
| **pipeline** cut@32, head on B, 1 stream | 199.42 ms | 211.22 ms | 0.002–0.007 ms | **2.435** |
| **pipeline**, 2 streams in flight (aggregate) | — | — | same | **4.734** |
| **tensor-parallel**, 129 reduces/token | 227.90 ms | 227.90 ms | 0.276–1.103 ms | **4.382–4.367** |

#### 35B-A3B

| split | board A | board B | link/token | **tok/s** |
|---|---|---|---|---|
| **pipeline** cut@20, head on B, 1 stream | 46.33 ms | 52.25 ms | 0.001–0.005 ms | **10.144** |
| **pipeline**, 2 streams in flight (aggregate) | — | — | same | **19.137–19.135** |
| **expert-parallel**, mixers replicated, router **balanced** | 84.64 ms | 90.56 ms | 0.047–0.189 ms | **11.036–11.019** |
| **expert-parallel**, mixers replicated, router **worst case** (all 8 routed experts on ONE board) | — | **99.65 ms** (the loaded board) | 0.047–0.189 ms | **10.031–10.016** |

> **Stated because the worst-case row is the study's most routing-sensitive
> number** — the balanced row above it is equally an assumption about a
> distribution §6 item 6 says is **not modelled at all**. `evidence/qwen_next/feas2/f13_toks2_model_rates.log`
> prints *both* boards charged all eight routed experts (93.72 / 99.65 ms),
> which cannot happen — eight experts land on one board or are split. The
> **bound is nonetheless right**, because the step is `max(A, B)` and the true
> worst case is the head-holding board taking all eight, at 99.65 ms. Only that
> board is printed above.

> **THE LINK IS NOT THE BOTTLENECK IN ANY CONFIGURATION MODELLED HERE**, and
> this is the most robust conclusion in §4 because it survives the whole sweep.
> The worst link term anywhere in the table is **1.103 ms** — tensor-parallel
> 27B, one lane, 2 µs latency — against a **227.90 ms** step: **0.48 %**.
> Pipeline splits move 10,244 B/token and their link term is *microseconds*.
> Even a **single lane** costs at most 0.3 % of throughput. Whatever else
> decides this, it is not link bandwidth, and it is not link latency within an
> order of magnitude of the assumed bracket.

> **Read the pipeline's two rows as two different products.** One stream is a
> **latency** figure: a token waits for both boards, so 2.435 tok/s at 27B and
> 10.144 at the MoE. Two streams in flight is a **throughput** figure: each
> board is busy all the time, but a token still needs both boards, so the
> completion rate is one token per `max(step_A, step_B)` — 4.734 and 19.137.
> Two streams means two independent conversations, not a faster one. (An
> earlier run of this study's script printed `2000/max(...)` and doubled both
> aggregates; `evidence/qwen_next/feas2/f09_toks2_model.log` carries the wrong figure and is kept as the
> record, `f11` and `f13` are right.)

> **Tensor-parallel beats single-stream pipeline at 27B and loses to it
> everywhere else.** At 27B it is 4.382 against 2.435 because both boards work
> on the same token; its cost is that the *width* work — RMSNorm, SwiGLU, the
> residual adds — is replicated on both boards, so the layer term falls only
> from 134.97 to 90.07, not to 67.48. (An earlier run did not split the layer
> term at all and reported 3.66; `f09` again.)

> **Expert-parallel barely beats the single-stream pipeline** — 11.04 against
> 10.14 — because with mixers **replicated** both boards do all 40 layers of
> DeltaNet and attention, and the routed experts they split are only 8.13 ms of
> matvec in the whole model. Splitting the mixers too (tensor-parallel on
> attention and DN, priced for footprint in §3.3) would help, and **its
> throughput is not modelled here**. The router-imbalance cost is small and
> bounded: **9.1 % between the balanced and the all-on-one-board worst case**,
> which is the *only* two-board number in this study that a real routing
> distribution could change.

### 4.6 Prefill

**Decode-rate, as today.** There is no batched prefill in this design
(`evidence/qwen9b/g6/RD9_GATE.md` §16 item 5 records prefill at 131.6 ms/step
against a 137.7 ms decode step on the shipped 9B). So a P-token prompt costs
P × the step above, minus the LM head. `docs/ARCHITECTURE.md` lists
weight-stationary batched prefill as orthogonal and untouched; at these step
times it is worth much more than it was at 2B, and it is **unquantified here**
(**E**, §6 item 8). For the MoE it is worth *less* than for the 27B, because
batching a prefill over positions does not amortise the expert gather — each
position routes to its own eight experts.

---

## 5. The link, and a board with no host — the design space, priced

### 5.1 The physical link (**T**, `f02`; **S** for the community pin data)

Read-only Vivado device-model queries on snoke against
`xcvu9p-fsgd2104-2L-e`, mapping the community BCU-1525 QSFP pin file's package
pins to sites. The pin file itself is GPLv2 community data from
github.com/d953i/Custom\_Part\_Data\_Files, the same source
`synth/constraints/PROVENANCE.md` records for the DDR4 and PCIe constraints; it
is **not** an official board file and nothing on it has been verified on this
board.

| | package pins | site | **GTY quad** | SLR |
|---|---|---|---|---|
| **QSFP0** cage refclk | K11 / K10 | GTYE4\_COMMON\_X1Y12 | **231** | **SLR2** |
| QSFP0 lanes 1–4 | N9/N8 … K2/K1 | GTYE4\_CHANNEL\_X1Y48…X1Y51 | **231** | SLR2 |
| **QSFP1** cage refclk | P11 / P10 | GTYE4\_COMMON\_X1Y11 | **230** | **SLR2** |
| QSFP1 lanes 1–4 | U9/U8 … P2/P1 | GTYE4\_CHANNEL\_X1Y44…X1Y47 | **230** | SLR2 |
| MGT Si570 clock 0 | M11 / M10 | GTYE4\_COMMON\_X1Y12, **MGTREFCLK0\_231** | 231 | SLR2 |
| MGT Si570 clock 1 | T11 / T10 | GTYE4\_COMMON\_X1Y11, **MGTREFCLK0\_230** | 230 | SLR2 |
| PCIe refclk (XDMA) | AM11 / AM10 | GTYE4\_COMMON\_X1Y7 | **226** | **SLR1** |
| PCIe lanes 0–3 | AF2/AF1 … AJ4/AJ3 | GTYE4\_CHANNEL\_X1Y35…X1Y32 | **227** | SLR1 |
| PCIe lanes 4–7 | AK2/AK1 … AN4/AN3 | GTYE4\_CHANNEL\_X1Y31…X1Y28 | **226** | SLR1 |

> **NO COLLISION** — `evidence/qwen_next/feas2/f02_gty_sites.log:498`
> `I: VERDICT = NO COLLISION -- QSFP quads 230 231 are disjoint from PCIe quads 226 227`
> and `evidence/qwen_next/feas2/f02_gty_sites.log:504`
> `I: VERDICT-227 = NO, neither QSFP cage touches GTY_Quad_227 (the XDMA quad)`.
> The run independently reproduces both device-model facts
> `synth/constraints/PROVENANCE.md` records (AM11 = GTYE4\_COMMON\_X1Y7 bank
> 226; AF2 = GTYE4\_CHANNEL\_X1Y35 quad 227).

**Three things follow. The first is a confirmation; the other two are new.**

1. **The x8 PCIe link occupies TWO quads, 226 and 227, not one** — and this
   one is a **confirmation, not a discovery**: `synth/constraints/PROVENANCE.md`
   already records lane 0 at `GTYE4_CHANNEL_X1Y35` in quad 227 and lane 7 at
   `GTYE4_CHANNEL_X1Y28` in quad 226, and the shipped build's own
   `synth/out_build_041/reports` place all eight there.
   `select_quad=GTY_Quad_227` names the XDMA preset's *master* quad; lanes 4–7
   and the refclk are in 226. The `f02` run reproduces it independently. The
   quads to keep clear are both.
2. **The QSFP cages are in SLR2 and XDMA is in SLR1.** Any link engine
   terminating at a cage and feeding the sequencer's datapath crosses an SLR
   boundary over SLLs. That is a floorplanning cost on a bitstream that closed
   at exactly 0.000 — not a blocker, but not free either.
3. **Each cage already has two refclk inputs inside its own quad** — the cage
   oscillator on MGTREFCLK1 and whatever drives `MGT_SI570_CLOCK0`/`1` on
   MGTREFCLK0 (**what that is, and at what frequency, is UNKNOWN (a) below** —
   "programmable" would be an inference from a part name). No cross-quad
   refclk routing is needed for either cage.

**The community file's own comment is wrong and should not be trusted**: it
labels the QSFP1 block *Bank231*, and the tool says QSFP1 is bank **230** and
QSFP0 is **231** — the cages are swapped in the comment. The same file
declares `IOSTANDARD LVCMOS12` on the MGT pins (meaningless for GT pins) and
binds the port name `USER_SI570_CLOCK_N` to two different package pins. Take
the pin *numbers*, not the file's annotations.

**The refclk frequency.** The cage clock is a fixed-select oscillator whose
frequency the FPGA chooses through two pins the file names `QSFP0_FS0`/`FS1`
(AT20 / AU22) and `QSFP1_FS0`/`FS1` (AR21 / AR22), with the mapping stated in
the file itself (**S**): `FS[1:0] = 01` gives **156.25 MHz**, `FS[1:0] = 1X`
gives **161.1328125 MHz**. Both serve 25.78125 Gb/s (× 165 and × 160) and both
serve 10.3125 Gb/s (× 66 and × 64), so **the QSFP path's refclk is a solved
problem on paper**.

> **UNKNOWN — and it is TWO different clocks, which an earlier revision
> conflated.** The community pin file names three separate things and only one
> of them is on the I2C mux:
>
> | net | package pins | what the tool says it is |
> |---|---|---|
> | `MGT_SI570_CLOCK0` | **M11 / M10** | `MGTREFCLK0_231` (`evidence/qwen_next/feas2/f02_gty_sites.log:191`) |
> | `MGT_SI570_CLOCK1` | **T11 / T10** | `MGTREFCLK0_230` (`evidence/qwen_next/feas2/f02_gty_sites.log:195`) |
> | `USER_SI570_CLOCK` | **AU19 / AV19** | ordinary IO — **not a GT refclk pin** |
>
> The mux at 0x74 channel 2 is labelled *"USER Si750 Clock I2C"* in the file
> (the part number is a typo in the source), and the only clock that name binds
> to is the **AU19/AV19** one. **Nothing in the pin file or in `f02`
> establishes that the AU19/AV19 device is the same part as the M11/T11 MGT
> refclk sources, or that the MGT sources sit on any mux channel at all** —
> "programmable" is an inference from a part name.
>
> So there are two UNKNOWNs:
> **(a) what drives `MGTREFCLK0_230/231` and at what frequency.** Not settled
> by reading mux channel 2, and **not settled by anything this study can do**.
> **How it would be settled:** the board schematic, or the vendor — i.e. the
> user. **(b) the USER Si570 at AU19/AV19**, which mux channel 2 does reach and
> which rung 0 of §5.5 can read.
>
> **Neither blocks a link**, because the design does not need either: each cage
> has a second refclk input, `MGTREFCLK1`, fed by the cage oscillator whose
> frequency the FPGA selects on `FS[1:0]`. Design for that, and treat both
> Si570 paths as unavailable until (a) and (b) are answered.

### 5.2 The IP, and the licence (**T**, `f03c`)

The licence property the tool actually has is `REQUIRES_LICENSE`, with
`LICENSE_KEYS` naming the FlexLM features. There is **no** `LICENSE`,
`LICENSED` or `LICENSE_STATUS` property and **no `get_license_status` command
in this build** — `evidence/qwen_next/feas2/f03c_ip_catalog.log:60`. Everything below is the tool's own
output, not an assumption.

| IP | version | `REQUIRES_LICENSE` | keys needed | installed on snoke? |
|---|---|---|---|---|
| **`aurora_64b66b`** | **13.0** | **0** | *(none)* | **no key needed — included** |
| `aurora_8b10b` | 11.1 | **0** | *(none)* | **no key needed — included** |
| **`cmac_usplus`** (100G Ethernet) | **3.1** | **1** | `cmac_usplus@2020.05`, `cmac_an_lt@2020.05`, two `ieee802d3_rs_fec_*` | **NO — all four MISSING** |
| `xxv_ethernet` (10G/25G) | 4.1 | **1** | ten features incl. the four above | **NO — all missing** |

The installed features on snoke are `ISE_Embedded_Edition`, `SDK`,
`Vivado_ML_Enterprise_Edition` and `Vivado_System_Edition_Eval`
(`evidence/qwen_next/feas2/f03c_ip_catalog.log:654`) — no `cmac_*` feature at all.

* **CMAC's key is free of charge but has not been obtained.** The IP's own
  catalog description says *"please generate a no charge license key from the
  UltraScale+ integrated 100G Ethernet product page"*
  (`evidence/qwen_next/feas2/f03c_ip_catalog.log:86`). So it is a **registration gate, not a purchase** —
  but it is a gate, and `cmac_usplus` would fail at IP generation on snoke
  today.
* **`xxv_ethernet` is partly free**: its XML says the standalone BASE-R PCS/PMA
  configuration needs no key while MAC and BASE-KR configurations are fee-based,
  so its `REQUIRES_LICENSE=1` covers the licensed configurations, not all of
  them.
* **Aurora 64B/66B needs nothing at all.** For a two-board point-to-point link
  this is the frictionless path.

> **WHAT `f03c`'S LICENCE SECTION IS, EXACTLY.** It is a **text scan**, not a
> licence checkout: `evidence/qwen_next/feas2/ip_catalog.tcl` globs `~/.Xilinx/*.lic`, opens each file
> and prints fields 1–4 (feature, vendor, version, expiry) of every
> `INCREMENT`/`FEATURE` line. All three of
> `XILINXD_LICENSE_FILE`, `LM_LICENSE_FILE` and `XILINX_LICENSE_FILE` are
> **unset** (`evidence/qwen_next/feas2/f03c_ip_catalog.log:595-597`), and
> `get_license_status` does not exist in this build
> (`evidence/qwen_next/feas2/f03c_ip_catalog.log:60`). The **dates** are the
> files' own; the **status** is an inference from reading text. Read every
> "installed / missing" verdict above with that attached.

> **UNRELATED AND URGENT, and stated on the tool's own words rather than on the
> file scan — with the one part the tool's words do NOT carry marked as such.**
> **What the build logs prove:** the tool checks out licence *features* named
> `'Synthesis'` and `'Implementation'` for `xcvu9p`, and **they expire
> 22-sep-2026 — seven days from the date of this study**. The proof is a build
> of the resident bitstream, dated 2026-09-07:
> `synth/out_build_041/build_run.log:280-281` reads
> `INFO: [Common 17-349] Got license for feature 'Synthesis' and/or device 'xcvu9p'`
> followed by
> `INFO: [Common 17-86] Your Synthesis license expires in 15 day(s)`, and
> Sep 7 + 15 = **22-sep-2026**. The implementation half says the same at
> `synth/out_build_041_ckr2_AltSpreadLogic_high/fullimpl.log:535-536`.
> **What the build logs do NOT carry is the EDITION name**: neither log
> contains the string `Edition`, `Enterprise` or `WebPACK` anywhere. That the
> feature carrying the 22-sep-2026 date is `Vivado_System_Edition_Eval` comes
> only from the `.lic` **text scan** this section has just disclaimed
> (`evidence/qwen_next/feas2/f03c_ip_catalog.log:627-635`). **The date and the
> "every build stops" conclusion rest on the tool; only the name rests on the
> scan.**
> *(An earlier revision of this section led with
> `Vivado_ML_Enterprise_Edition`'s 06-aug-2026 expiry. That is an aside, not
> the finding: the shipped bitstream was built a MONTH after it lapsed, on the
> eval licence, with no effect.)* After 22-sep-2026 no unexpired feature
> remains in `~/.Xilinx` on snoke, and xcvu9p is not a WebPACK device, so
> **every build stops** — not just a link build. It belongs in §8.

**CMACE4 hard blocks: nine, three per SLR** (`evidence/qwen_next/feas2/f03c_ip_catalog.log:513-522`) —
`CMACE4_X0Y0/1/2` in SLR0, `X0Y3/4/5` in SLR1, `X0Y6/7/8` in SLR2. They sit in
column X0; every QSFP and PCIe GTY quad is in column X1.

> **UNKNOWN — which GTY quad each CMACE4 can be driven from.** `report_property`
> on a CMACE4 site exposes only geometry and placement properties; the device
> model does not carry the GT pairing, and the site coordinates do not imply it.
> **How it would be settled:** PG203 / UG578, or a trial
> `cmac_usplus` IP customisation once the free licence key is installed —
> neither of which this study may do. It matters because if the reachable CMAC
> for quads 230/231 is not in SLR2, the Ethernet path adds a second SLR crossing
> on top of §5.1's.

### 5.3 What "Aurora" and "Ethernet" actually buy, side by side

| | **Aurora 64B/66B** | **100G Ethernet (CMAC)** | **10GbE SFP+ as a loader only** |
|---|---|---|---|
| licence | **none** (`f03c`) | free key, **not installed** (`f03c`) | `xxv_ethernet` key not installed; a soft 10G MAC is an alternative |
| what it is | a framed point-to-point channel over GTY, with flow control | a MAC + PCS/PMA hard block | a MAC over one lane |
| framing the design must add | Aurora frames carry arbitrary user data; the design needs its own packet/length/CRC discipline above it | Ethernet/IP/UDP headers, ARP or static ARP, MTU handling | the same |
| what it buys | **the shortest path to a working link**; no MAC, no headers, no NIC | a **host NIC path** — snoke could talk to board B directly, standard tooling (`tcpdump`, sockets) | **the only path that uses hardware snoke already has** |
| what it costs | **no host can talk it.** Only another FPGA. Board B is reachable only through board A | licence gate, a 100G NIC purchase (snoke has none — its fastest port is one Intel 82599 10GbE SFP+), MAC/IP/UDP framing in RTL | 8× longer loads (§5.4), a QSFP28↔SFP+ adapter, and it still needs a MAC |
| hard blocks used | GTY only | one CMACE4 of nine, quad pairing UNKNOWN (§5.2) | GTY only |
| SLR cost | one crossing (SLR2 cage → SLR1 XDMA) | one crossing, **possibly two** (§5.2) | one crossing |

> **The framing question the user's words settle.** "Going to have to load DDR
> via 100G ethernet" has two readings. If it means *snoke must reach board B
> directly*, an Ethernet MAC is required and so is a 100G NIC, because
> **snoke has none** — its network is four BCM5720 1GbE ports and one Intel
> 82599 10GbE SFP+. If it means *the weights must get into board B over the
> QSFP link*, **Aurora is strictly simpler and needs no purchase**: host →
> board A over PCIe (which already works and is measured) → link → board B,
> with board A as a bridge. This study prices both and **picks neither** (§8).

### 5.4 Board B's control plane, with no host at all

Board B has **power only**. There is no PCIe, so no XDMA, no BAR, no
`/dev/xdma0_*`, no `sw/hwmap.py` address map reachable from snoke, and **no
`sudo -n sw/pcie_helper.sh remove/rescan` safety flow** — that flow exists
because a wedged endpoint can panic the host, and board B is not an endpoint of
any host. Everything it needs crosses the link. Seven things do:

1. **The bitstream.** See the UNKNOWN below.
2. **The weights.** 6.55 GiB (27B pipeline, head on B) or 9.05–9.41 GiB (MoE),
   at W4 g128 (**D**, `f07`). At the assumed 12.50 GB/s payload that is
   **0.6 s** and **0.8 s**; at 90 % of it, 0.6 s and 0.9 s; on a single lane,
   2.3 s and 3.2 s; **over 10GbE it is 6.1 s and 8.7 s**. *Loading is not a
   reason to choose one link over another* — even the 10 GbE path loads a model
   in under ten seconds. The reasons are §5.3's.
3. **The SEQ stream and the const blob.** The shipped 9B's are 158,536 records
   at `0x9000000` and 8,940,032 B at `0xc000000` (`NEXT_SESSION.md` §1) —
   megabytes, not gigabytes.
4. **The initial state region** — at most 113.75 MiB (MoE) or 167 MiB (half of
   the 27B's 334), §3.4.
5. **Per-piece verification readback.** The shipped upload discipline verifies
   every piece and the whole pack by sha256 (`NEXT_SESSION.md` §1: *"249
   images, 3,902 MiB + the 1,940 MiB embedding, per-piece verified"*). Over a
   link this doubles the transfer or needs a hash engine on board B; **the
   second is the right answer and it is new RTL.**
6. **A CSR tunnel.** Board A's host must reach board B's CSR blocks — the SEQ
   block at BAR `0x6000` and `layer_chan` at `0x5000` (`NEXT_SESSION.md` Key
   invariants). The first four registers to tunnel are the ones every tool
   asserts before it does anything: `MAGIC` `0xFAB1E001`, `VERSION`, `CALIB`
   and `UPTIME` (`CLAUDE.md`'s address map). **`CALIB` is the load-bearing
   one**: the project's hard rule is *"NEVER DMA to DDR addresses before CSR
   CALIB shows the channel calibrated"*, and on board B that check has to
   happen **over the link, before the first weight byte is sent**. A loader
   that cannot read `CALIB` must refuse to start.
7. **The token path back.** `OUT_FIFO` at `0x18` and `OUT_CNT` at `0x1C`
   (`rtl/seq_unit.sv:33-34`), plus `PC`, `STATUS` and the `PERF_*` counters for
   the same visibility the one-board tools have.

**The safety rails, restated for a machine that cannot panic a host.** The
CHARTER's rail is *"prefer designs where the host can't hang"*. With board B on
the far side of a link, the rail becomes: **board B must never be able to stall
board A's AXI-Lite.** Every tunnelled CSR read needs a timeout that returns a
defined error value rather than waiting, because a read that never completes on
board A's `M_AXI_LITE` is exactly the wedge that panics snoke. That is a
design constraint on the tunnel, not an afterthought, and it is the single
most important new safety property in this study.

> **UNKNOWN — how board B gets a bitstream.** The lab's JTAG is
> *"JTAG via snoke hw_server"* (`CLAUDE.md` Lab facts) to the one resident
> board. Whether a second board can be reached — a second USB-JTAG cable, a
> chained JTAG header, or none at all — **is not knowable from this repo** and
> this study does not assume one. **How it would be settled: only by the user**,
> who can see the hardware. It is §8's first question, and it is a hard
> precondition: with no JTAG, board B cannot be programmed at all, and every
> other number in this study is moot. (Flash is not an alternative — the
> project's rule is JTAG-volatile only, never board flash.)

### 5.5 The self-test ladder that needs NO second board

Every rung below runs on the **one** board that exists, with a DAC cable looped
between its own two QSFP cages. **None of it is approved and none of it was
done** — this is a priced plan, not a result.

| rung | what it proves | needs | bitstream? |
|---|---|---|---|
| **0** | the cage sidebands: `MODPRSL` reads a plugged cable, `RESETL`/`LPMODE` drive, `FS[1:0]` select a refclk, and the I2C mux answers — which settles §5.1's UNKNOWN **(b)** only, the USER Si570 on mux channel 2. It does **not** settle **(a)**, what drives `MGTREFCLK0_230/231` | a DAC cable, an I2C master | **yes** |
| **1** | **link up**: Aurora 64B/66B on quads 230→231, lane alignment, and a BER/throughput/latency measurement — which replaces §4.5's *assumed* latency bracket with a number | rung 0 | **yes** |
| **2** | the **loader engine**: link → AXI DMA → board A's **own** DDR, verified by readback over the same loop. This is the whole loader path, end to end, on one board | rung 1 | **yes** |
| **3** | the **CSR tunnel**: reach board A's own CSR block through the loop and read `MAGIC`/`VERSION`/`CALIB`/`UPTIME`, with the timeout rail of §5.4 exercised by deliberately not answering | rung 2 | **yes** |
| **4** | the **stream path**: write a SEQ stream through the loop, launch, drain `OUT_FIFO` back through it, compare tokens against the one-board run | rung 3 | **yes** |
| **5** | only now, a second board | rungs 0–4, a JTAG answer, a cable | yes |

> **Every rung re-opens the timing gate, and that is stated once here because
> it applies to all of them.** `NEXT_SESSION.md` §9 records the standing ladder
> and its reason: *"The margin is 0.000 and it was produced once"* — any RTL,
> constraint or tool-version change re-opens the whole gate, which is
> lint → unit TBs → the layer census → the S4 replay → OOC counts → a full
> build with the clock-root check → the safe reprogram → the RD9 ladder. A
> link engine is not a small addition to that: it is new GTY instances in SLR2,
> a new AXI master on the SmartConnect, and an SLR crossing into a datapath
> whose floorplan was solved once. **Budget a full timing campaign per rung
> that changes the netlist, not a rebuild.**

---

## 6. What this study did NOT establish

Stated because the 2B and 4B/9B studies' equivalents turned out to be their
most useful sections.

1. **Nothing here is measured on two boards.** There is one board. No link was
   built, no cable plugged, no bitstream made. Every two-board number is
   arithmetic over one-board measurements.
2. **No synthesis, no placement, no routing.** The 4B/9B study's Track P at
   least ran `synth_design` and `place_design` on the widened `layer_chan`.
   This study ran **only read-only device-model and IP-catalog queries**. The
   URAM figures of §2.7 are inferences from slot declarations validated against
   the shipped OOC count — they are **D**, not **T**, and certainly not **B**.
3. **The link's latency is a guess.** §4.5's 0.5 / 1.0 / 2.0 µs bracket has no
   source; it is a placeholder chosen to bracket a plausible fabric→GT→fabric
   path. The conclusion it supports — *the link is not the bottleneck* — is
   robust to it (the term is under 0.5 % at the worst corner), but the
   **number** is not evidence of anything. Rung 1 of §5.5 measures it.
4. **The link's payload rate is a ceiling, not a measurement.** 12.50 GB/s is
   4 × 25.78125 Gb/s × 64/66. No Aurora core's actual user-interface
   efficiency, no flow-control behaviour and no CRC/idle overhead is modelled.
5. **The router's normalisation is UNKNOWN** (§1.2). `norm_topk_prob`,
   `scoring_func` and `topk_method` are all absent from the config, so whether
   the top-8 gate is softmax or sigmoid and whether it is renormalised is not
   established. It moves §2.11 between M and L.
6. **The MoE's expert *distribution* is not modelled.** §4.5's "balanced" and
   "all on one board" are the two extremes of an unmeasured distribution. Real
   routers are not uniform; the spread between the two is 9.1 %, so the
   exposure is bounded, but the actual number would come from running the
   reference model — which this study did not do (no weights were downloaded).
7. **No fidelity number exists for either target**, at any precision, and the
   MoE adds a new fidelity question this project has never faced: **what W4A8
   does to a 256-way router's argmax**. A one-bit routing error swaps an entire
   expert, which is a discontinuity, not a small perturbation. Nothing here
   measures it and §7.2 lists it as the MoE's #1 risk.
8. **Prefill is not modelled** (§4.6), and for the MoE it is qualitatively
   different from every prefill this project has considered.
9. **The tokenizer and chat template were not checked** (§1.4). One run of
   `evidence/qwen_next/feas/tokenizer_check.py` would close it.
10. **The scratch peak is the allocator's algebra, not an empirical probe**,
    exactly as in the 4B/9B study. It reproduces the frozen 0.8B map and the
    committed 9B peaks, which is a strong validation, but no high-water probe
    was run at either new geometry.
11. **Expert-parallel with the mixers SPLIT is priced for footprint (§3.3) and
    NOT for throughput.** It is the configuration most likely to be the right
    one for the MoE and §4.5 does not carry a number for it.
12. **The effort classes in §7.3 are directional**, from counted `file:line`
    sites and not from an implementation — the same caveat the 2B and 4B/9B
    studies attached to theirs, and they were right about ordering rather than
    magnitude. The "≈ 2–3×" multiple is an **opinion**, not a T/D/S/E number,
    and §8.4 exempts it explicitly.
13. **The 9.9 % gap between the board's layer lane and the project's own
    like-for-like chip-TB census is UNATTRIBUTED — by
    `evidence/qwen9b/g6/RD9_GATE.md` §10.2a's own words — and this study does
    not attribute it either.** §4.2: the model sits +1.8 % above the census
    (46.99 vs 46.161) and 13 % above the board (41.588), and which of the two
    is the right target for a *modelled* layer term is exactly what is not
    known. An earlier revision of this document turned that gap into a ×0.8851
    multiplier and carried a "corrected" column through §4.3, §4.4, §4.5, §7.1
    and §8.2; **that column is withdrawn**, because rescaling by an unexplained
    instrument delta is not a correction. The logs
    `evidence/qwen_next/feas2/f11_toks2_model_fix.log` and
    `evidence/qwen_next/feas2/f13_toks2_model_rates.log` still print it; they
    are the record of what was run and are not rewritten. **Closing this needs
    RD9's own follow-on, not this study.**
14. **Nothing establishes that 25.78125 Gb/s per lane is reachable on THIS
    part over THIS board's QSFP channel.** The device is a **-2L** speed grade
    (`xcvu9p-fsgd2104-2L-e`), the whole §4.5 link model assumes 4 lanes at that
    rate, and §6 item 4 disclaims the *efficiency* of the rate rather than its
    *feasibility*. The conclusion survives either way — a single lane costs
    under 0.5 % of the step (§4.5) — but **rung 1 of §5.5 could fail for a
    reason the ladder does not list**, and the fallback (10.3125 Gb/s, which
    both cage refclks also serve, §5.1) is not priced anywhere here.
15. **The MTP head and the vision tower are excluded from every fit and every
    throughput number without being priced.** Both checkpoints carry them
    (`evidence/qwen_next/feas2/f01_geometry2.log`: 27B mtp 810.0 MiB + vision
    878.8 MiB; 35B-A3B mtp 1,611.0 MiB + vision 851.8 MiB), and the loader
    filters them exactly as at 2B and 9B, so the exclusion is right — but it is
    an *assumption that the loader keeps doing that*, and the MoE's MTP head is
    itself a 785-tensor per-expert block, the largest shipped-unused artifact
    this project has ever seen.
16. **The 27B's state traffic is flagged and not carried.** §3.4 puts it at
    **412 MiB/token at T = 4,096 on DDR channel 3 alone**, 2.3× the shipped
    9B's, and observes that the shipped design's DMA lane overlapped its
    compute lane. Whether it still overlaps at 2.3× the traffic on a longer
    step is **E** and nothing here models it — the §4 step law has no DMA term
    at all.

---

## 7. THE DECISION TABLE

### 7.1 Side by side

| | **Qwen3.5-27B (dense)** | **Qwen3.5-35B-A3B (MoE)** |
|---|---|---|
| geometry | H 5120 / FFN 17408 / **64 L** (48 DN + 16 GQA) | H 2048 / **no `intermediate_size`** / **40 L** (30 DN + 10 GQA) |
| head geometry | **24 NQ / 4 NKV / 16 key + 48 value DN heads** | **16 NQ / 2 NKV (the 9B has 4) / 16 key + 32 value DN heads — the DeltaNet geometry identical to the shipped 9B, `NKV` HALVED** |
| `CONV_DIM` | **10,240** | **8,192 — identical to the shipped 9B** |
| FFN shape | dense, 17,408 | **256 experts × 512, top-8, + 1 shared expert of 512, + a 256-way router** |
| text tower, resident | **25.62 G** | **34.15 G** |
| **streamed per token** | **25.62 G (all of it)** | **2.95 G — 8.50 %** of the 34.66 G that tower-plus-head comes to |
| checkpoint | 51.75 GiB, **11 shards** | 66.97 GiB, **14 shards** |
| **width walls FAILED** (**D**) | **eight**: scratch, vecnorm, ALU len, `MAX_NG`, EMBLOG2, DN slot, conv slot, `dn_head` | **NONE** |
| walls passed *exactly at the ceiling* | `kvhead` 4 of 4 | **three**: `dn_head` 32/32, `CONV_DIM` 8192/8192, DN slot 4096/4096 (`kvhead` 2/4 and `ng` 32/96 pass with 2× and 3× headroom) |
| **structural walls FAILED** | SLD/SST envelope (48/16 vs 24/8) **as a whole model — it PASSES at exactly 24/8 per board under the midpoint pipeline cut**; geometry rot; `T < 512` | SLD/SST envelope (30/10 vs 24/8) **as a whole model — PASSES at 15/5 per board under the midpoint cut**; geometry rot; `T < 512`; **the router (no opcode)**; **expert gather (indirection refused at decode)**; **the emitter's loop closure (byte-identical bodies)** |
| **scratchpad** (**D**, `f10`) | **68,720 / 65,536 — FAIL by 3,184**, fixed by a 2-way gate/up chunk (48,240, 17,296 spare). Emitter only, **class S** | **29,216 — PASS, 36,320 spare.** More headroom than the 2B had |
| **vecnorm** (**D**) | **H = 5120 fails TWICE** — above the 4096 G3.2 just reached, **and not a power of two**, so the shift is the wrong primitive. **XL, no precedent in this project** | **H = 2048 — PASS with a doubling to spare** |
| **EMBLOG2 / embedding rows** (**D**, `f07`) | **10,240 B row. EMBLOG2 14 is REFUSED, and the padded 16,384 B table (3,880 MiB) does not fit its own channel beside `W_BASE` (4,136 > 4,096).** Needs non-power-of-two addressing or a split table. **L** | **4,096 B row, EMBLOG2 12 — PASS, one below the shipped 13** |
| **`MAX_NG`** (**D**) | **`down` K = 17,408 → ng 136 vs 96.** `XWIN_WORDS` 3,072 → 4,352, `x_mem`, `xptr`. **L**, in the block with the worst waived endpoints | **max ng 32 — below even the 2B's 48. PASS** |
| **URAM cache array** (**D**, `f12`) | **244 / 960 (25.4 %)**, one SLR, +62 over the shipped 182 | **182 / 960 — IDENTICAL to the shipped design** |
| **one board, W4 g128** (**D**, `f05`) | 12.485 + 3.789 = **16.274 GiB — OVER by 281 MiB**; with the *natural* 10,240 B row **14.853 GiB, FITS at 92.8 %** | **18.791 GiB — OVER by 17.4 %.** No precision in this project closes it |
| **two boards, W4 g128** | **PASSES** the 3,840 MiB runtime window on every split; **FAILS** the as-built 1,280 MiB one. Channel 0 misses by **103.5 MiB** even with a natural row | **PASSES** the runtime window on every split; channel 0 has **618 MiB spare** |
| **two boards, W8** | FAILS | **FAILS** |
| **modelled tok/s, pipeline 1 stream** (**E**) | **2.435** | **10.144** |
| **modelled tok/s, pipeline 2 streams, aggregate** (**E**) | **4.734** | **19.137** |
| **modelled tok/s, tensor-parallel** (**E**) | **4.382–4.367** | n/a (dense-only split) |
| **modelled tok/s, expert-parallel** (**E**) | n/a | **11.036–11.019** balanced, **10.031–10.016** worst case |
| vs the 9B's **measured** 7.2917 (**B**) | **0.33× / 0.65×** (pipeline 1-stream / 2-stream) | **1.39× / 2.62×** |
| bottleneck at W4 g128, one board | matvec 46.9 % / layer 32.9 % | **layer 47.4 %** — the first *large* target to come back layer-bound; the measured 0.8B at W4 was 48.0 % |
| **the link's share of the step** (**E**) | **≤ 0.48 %** at the worst corner modelled | **≤ 0.19 %** |
| loader volume into board B (**D**, `f07`) | 6.553 GiB → 0.6 s at 12.5 GB/s, **6.1 s over 10GbE** | 9.048–9.406 GiB → 0.8 s, **8.7 s over 10GbE** |
| state region per board | 334 MiB whole-model; **412 MiB/token of traffic at T = 4,096** | 113.75 MiB; 147.5 MiB/token |
| **what it needs that does not exist** | a wider vecnorm with a **reciprocal**, a 15-bit ALU length, `MAX_NG` 136, non-power-of-two EMB addressing, a 6-bit `dn_head`, a 10,240-deep conv slot | a **router**, a **data-dependent MVGO**, and an **emitter that can emit a token body that differs from the last one** |
| **what it needs ONLY under some splits** | a 6-bit SLD/SST layer field and `N_DN` 48 / `N_KV` 16 — **tensor-parallel only**; the midpoint pipeline cut passes at exactly 24 / 8 | `N_DN` 30 / `N_KV` 10 (constants, the 5-bit field already carries 32) — **expert-parallel and tensor-parallel only**; the midpoint pipeline cut passes 15 / 5 |

### 7.2 Unique risks

**27B**

1. **The non-power-of-two normalizer.** H = 5120 needs a length input and a
   reciprocal multiply in `vecnorm_unit`, which has never had one — the
   *primitive* exists elsewhere (`rtl/attn_core.sv:96`), so what is new is
   putting it in the normalizer's critical path. It is the 4B's XL wall,
   inherited.
2. **The embedding table has no home.** §2.6/§3.3: padded it overflows its own
   channel; natural it needs new address logic in `seq_unit` **and** still
   leaves channel 0 short by 103.5 MiB. This is two problems that look like one.
3. **`matvec_engine` again.** `MAX_NG` 96 → 136 reopens the block that owns the
   design's worst waived timing endpoints, on a bitstream that closed at 0.000.
4. **Throughput is the real verdict.** 2.4 tok/s single-stream is **one third**
   of what the board serves today. Two streams gets 4.7, and that is two
   conversations, not one faster one.

**35B-A3B**

1. **The router under W4A8 — the #1 risk, and it is qualitatively new.** Every
   fidelity question this project has answered was about *how wrong* an output
   value is. A router's output is an **argmax over 256**: a one-bit error swaps
   an entire expert and the FFN output changes completely. **Nothing in the
   Track-Q framework measures a discontinuity.** The router weights are
   `[256, 2048]` — 0.5 M parameters of 34 G — so keeping them at W8 or bf16
   costs essentially nothing, and §3's tables already price the router as W8.
   That is a mitigation, not an answer; the answer is a measurement nobody has.
2. **The static stream is not a width, and widths are what this project is good
   at.** §2.12: the emitter's loop closure *requires* byte-identical token
   bodies, and the campaign that closed that loop spent a whole wave removing
   data-dependent immediates. Re-introducing one is a design reversal, not a
   parameter change.
3. **Expert load imbalance** — bounded at 9.1 % between the extremes (§4.5),
   and the least of the MoE's problems.
4. **Three walls sit exactly at a ceiling** (§2.8) — `dn_head`, `CONV_DIM` and
   the DN slot. That is a large part of why it fits, and it means the fit is to
   that extent a coincidence of this checkpoint's geometry matching the shipped
   bitstream's; a later MoE checkpoint would not inherit it. **The argument is
   materially weaker on three rows than on the five an earlier revision
   claimed**: `kvhead` (2 of 4) and `ng` (32 of 96) have 2× and 3× headroom, so
   the geometry is not uniformly knife-edge.

**Shared**

5. **The SLD/SST layer envelope** (`N_DN` 24, `N_KV` 8) fails for both as
   whole models and **PASSES for both under the midpoint pipeline cut** — the
   MoE at 15 DN / 5 GQA with room, **the 27B at 24 / 8, exactly on the last
   passing value**. It is the only §2 wall whose PASS/FAIL the throughput choice
   flips (the DDR windows of §3.3 move with the split too, but they fail or pass
   together), and for the 27B it is severe: **exactly one of
   the 63 possible cuts is legal** (`evidence/qwen_next/feas2/f15_fix1_checks.log`),
   against 25 of 39 for the MoE, so the 27B's split cannot be moved by a single
   layer to balance load or footprint. Tensor- and expert-parallel leave every layer on both boards and
   fail — the MoE needs two constants raised, the 27B needs a sixth bit in
   `sd_layer_a` as well.
6. **The CSR tunnel can hang board A's host.** §5.4. A tunnelled read that
   never completes on `M_AXI_LITE` is the wedge the CHARTER's rail exists to
   prevent, and it is a *new* way to reach it.
7. **The 0.000 timing margin, five times.** §5.5's ladder has five netlist
   changes before a second board is touched, and each re-opens the full gate.
8. **The Vivado licence the tool actually checks out — `Vivado_System_Edition_Eval` — expires 22-sep-2026** (§5.2, `synth/out_build_041/build_run.log:280-281`). Nothing can be
   built after that date until it is renewed.

### 7.3 Effort, relative to the 9B migration

The 9B campaign was three ISA waves (G3.1 scratch re-encode, G3.2 vecnorm
widening, G3.3 matvec SHAPE) plus a full state-spill redesign, and it shipped.

| | **27B** | **35B-A3B** |
|---|---|---|
| **width walls** | **8** | **0** |
| the XL ones | the non-power-of-two normalizer | **the data-dependent weight stream** (router + gather + emitter), which is **one problem in three places** |
| the L ones | EMBLOG2 / the embedding table; `MAX_NG` → 136 | the router's datapath, if the gate turns out to be softmax |
| the M ones | DN slot second rank; conv slot depth; `dn_head` 6 bits; geometry rot — **plus** a 6-bit SLD/SST layer field *if and only if* tensor-parallel is chosen (the midpoint pipeline cut passes at exactly 24 / 8) | geometry rot — **plus** `N_DN` 24 → 30 and `N_KV` 8 → 10, two constants, *if and only if* a non-pipeline split is chosen |
| the S ones | scratch (emitter chunking); ALU length +1 bit | — |
| new RTL blocks re-opened for timing | `vecnorm_unit`, `matvec_engine` **+ `matvec_chan`**, `layer_chan` caches, `seq_unit` EMB | `seq_unit` (an indirected MVGO and a TOPK→XRF path), `layer_chan` (nothing, if the geometry holds) |
| **plus, for BOTH**: the link engine, the loader, the CSR tunnel, the far-side `CALIB` rail, and §5.5's five-rung self-test ladder | — | — |
| honest multiple of the 9B campaign (**an OPINION, not T/D/S/E — §8.4 exempts it explicitly**) | **≈ 2–3×** — more walls, six of a kind this project has walked and two (§2.3, §2.6) that it has not, plus the link | **≈ 2–3×** — *none* of those eight, and one problem in three places that is a new machine feature. **The two are comparable in total effort for completely different reasons, and the MoE's is the one with no precedent to estimate from** |

> **The comparison that matters is not the multiple, it is the shape.** The
> 27B is eight width walls, six of them work this project has done before — the
> non-power-of-two normalizer and the non-power-of-two embedding stride are the
> two it has not — and its reward is 2.4–4.7 tok/s. The MoE breaks **none** of
> those eight, needs some of the same M-class chores anyway (geometry rot, and
> two constants if the split is not a pipeline), and adds **one problem in
> three places** that has never been attempted; its reward is 10–19 tok/s — **faster than the
> board serves today**, on a model four times the size. Those two sentences are
> the decision.

---

## 8. OPEN DECISION FOR THE USER

**This study picks nothing.** Below are the questions **only the user can
answer**, then the ones the evidence can inform. Every row is labelled the way
§0 promised.

### 8.1 The five questions this study CANNOT answer

| | question | why only the user | what depends on it |
|---|---|---|---|
| **U1** | **Can board B be JTAG-programmed at all?** A second USB-JTAG cable, a chained header, or nothing? | It is a physical fact about hardware this study cannot see, and `CLAUDE.md`'s lab facts record only *"JTAG via snoke hw_server"* to the one resident board | **Everything.** With no JTAG, board B cannot be programmed and no configuration in this study exists. Flash is not an alternative — the project's rule is JTAG-volatile only |
| **U2** | **A 100G NIC purchase, board A as a bridge, or the 10GbE SFP+ path?** | It is a spend decision. snoke has **no** 100G port — four 1GbE BCM5720 and one Intel 82599 10GbE SFP+ | §5.3. **Aurora + board A as a bridge needs no purchase and no licence**; direct host→B needs a NIC *and* the free CMAC key *and* a MAC in RTL; the 10GbE path needs a QSFP28↔SFP+ adapter and still needs a MAC. **The loader times (0.6 s vs 8.7 s) do not decide it** — all three are fast enough |
| **U3** | **Which model — 27B, 35B-A3B, or neither?** | §7 gives the evidence and takes no position | The whole programme. "Neither" is a legitimate answer and its arithmetic is in §8.2 |
| **U4** | **Which split?** | It trades throughput against a wall (§7.2 item 5) and against latency-vs-aggregate (§4.5) | Pipeline 2-stream is the fastest aggregate for both models; tensor-parallel is the fastest *single-stream* for the 27B; expert-parallel with split mixers is unmodelled (§6 item 11) |
| **U5** | **Is the Vivado licence going to be renewed?** | The feature the tool checks out for xcvu9p is `Vivado_System_Edition_Eval` and it **expires 22-sep-2026** — the tool says so itself in a 2026-09-07 build, `synth/out_build_041/build_run.log:280-281`. (`Vivado_ML_Enterprise_Edition` lapsed 06-aug-2026 and that build ran anyway, so it is not the live one.) | **Every build, not just a link build.** This is unrelated to this study and more urgent than any of it |

### 8.2 The evidence for U3, both models against the same baseline

| (**E** unless marked) | **27B** | **35B-A3B** |
|---|---|---|
| tok/s, two boards, pipeline 1 stream | **2.435** | **10.144** |
| tok/s, two boards, best modelled split | **4.734** (pipeline, 2 streams) | **19.137** (pipeline, 2 streams) |
| vs the shipped 9B's **measured** 7.2917 (**B**) | **0.33× / 0.65×** | **1.39× / 2.62×** |
| width walls to break (**D**) | **8** | **0** |
| structural walls to build (**D**) | 0 new-in-kind | **3 — router, gather, emitter** |
| fits two boards at W4 g128 (**D**) | **yes**, with the runtime `EMB_BASE` and a channel-0 fix | **yes**, with the runtime `EMB_BASE` |

* **The 27B is the familiar kind of hard and the disappointing kind of slow.**
  Eight width walls, **six** of a class this project has broken before — the
  non-power-of-two normalizer (§2.3) and the non-power-of-two embedding stride
  (§2.6) are the two it has not — and
  a result **one third** of what the board serves today on one board. Its one
  bright spot: with a non-power-of-two embedding row it **fits one board** at
  92.8 % (§3.2), which would make it a single-board 25.6 G-parameter model at
  2.44 tok/s — and that is a different, smaller project than the one this study
  was asked about.
* **The MoE is the unfamiliar kind of hard and the surprising kind of fast.**
  Zero width walls, **three** of them clearing *exactly* (§2.8), a per-token
  workload
  **smaller than the shipped 9B's**, and a modelled 10–19 tok/s. What stands in
  the way is not a width: it is that the machine has no router, refuses
  indirection on the weight stream at decode, and has an emitter whose loop
  closure requires identical token bodies.
* **Neither is a legitimate answer**, and its arithmetic is symmetric: the 9B
  serves **7.2917 tok/s measured** today on one board, and the best *modelled*
  single-stream figure in this study is 10.144 — a 39 % gain for a second
  board, a link, a loader, a CSR tunnel, a router and a new sequencer feature.
  The 2-stream 19.137 is a different product (two conversations).

### 8.3 What the evidence says about U4, without picking

* **Pipeline, 2 streams** is the best aggregate for both models and needs the
  least new machinery — one activation transfer per token, a link term in
  *microseconds*, and it **halves the layers per board**, which clears the
  SLD/SST envelope for **both** models without touching the RTL — the MoE at
  15/5 with room, the 27B at exactly 24/8 (§7.2 item 5). The other splits can
  pass it too, but only by changing constants (MoE) or widening a field (27B).
* **Pipeline, 1 stream** is the same hardware and answers the latency question
  instead: 2.435 / 10.144 tok/s.
* **Tensor-parallel** is the 27B's best single-stream figure (4.382) and its
  cost is 129 reduces per token — still under 0.5 % of the step — plus the
  replicated width work that keeps its layer term at 90.07 rather than 67.48.
  It does **not** help the SLD/SST envelope.
* **Expert-parallel** with mixers replicated is barely better than the MoE's
  single-stream pipeline (11.036 vs 10.144) because the mixers dominate. With
  mixers split it should be materially better and **this study did not model
  it** (§6 item 11).

### 8.4 The three opinions this study holds, so they can be discounted as a set

It holds three and no more, and it states none about U3.

**And one exemption, stated so the count is honest**: §7.3's "≈ 2–3×" effort
multiple is also an opinion. It is excluded from the three below because it is
a magnitude on work neither model has had done to it, not a position on a
decision; §6 item 12 carries it.

1. **U1 should be answered before anything else**, because it can invalidate
   the entire programme for the cost of one look at the hardware.
2. **§5.5's rungs 0–2 are the highest information per hour available**, and
   they need no second board, no purchase and no licence: a DAC cable between
   board A's own two cages proves the sidebands, the link, the measured latency
   that replaces §4.5's guess, and the whole loader path end to end — against
   board A's own DDR, verified by readback.
3. **The router's W4A8 fidelity should be measured in the reference model
   before any RTL is written for the MoE** (§7.2 item 1). It needs no board, no
   synthesis and no link — only the weights and `ref/` — and it can retire or
   confirm the MoE's #1 risk, which is a discontinuity nothing in the existing
   Track-Q framework can see.

---

## 9. Traceability index

Every number in this document, by source. All logs carry a host/date/tree/venv
header from `evidence/qwen_next/feas2/feas2_run.sh` and end with `=== rc  :`
and `=== end :`. Paths are repo-relative.

| claim | evidence |
|---|---|
| exact 27B / 35B-A3B geometry, shard counts, per-prefix census, the MoE keys by presence, the per-token ACTIVE parameter count | `evidence/qwen_next/feas/fetch_geometry.py` → `evidence/qwen_next/feas2/f01_geometry2.log`, `evidence/qwen_next/feas2/geometry2_raw.json`; `evidence/qwen_next/feas2/geom2_report.py` → `evidence/qwen_next/feas2/f04_geom2_report.log` |
| 48 DeltaNet value heads and `CONV_DIM` 10,240 at 27B; 256 experts / top-8 / 512 / one shared expert at 35B-A3B; the fused 3-D expert tensors | `evidence/qwen_next/feas2/f04_geom2_report.log` (the layer-0 and layer-3 shape tables) |
| the shipped 9B pack reproduced: 4,091,805,696 B/token, 978.40 / 975.30 / 974.27 / 974.27 MiB, max/min 1.004234 | `evidence/qwen_next/feas2/ddr_fit2.py` → `evidence/qwen_next/feas2/f05_ddr_fit2.log`; the comparand is `evidence/qwen9b/g6/RD9_GATE.md` §10.3 |
| streamed bytes/token, packed footprint, one-board fit, the embedding-row table | `evidence/qwen_next/feas2/f05_ddr_fit2.log` |
| per-board per-channel fit, the window verdicts, channel 0's ceiling, the loader volume and times, the state region | `evidence/qwen_next/feas2/board_split.py` → `evidence/qwen_next/feas2/f07_board_split_fix.log` (`evidence/qwen_next/feas2/f06_board_split.log` is the same run with one misleading column, kept as the record) |
| the scratch peaks, the frozen 0.8B map reproduced, the committed 9B peaks reproduced, the 27B chunking table | `evidence/qwen_next/feas2/scratch_peak2.py` → `evidence/qwen_next/feas2/f10_scratch_peak2.log` |
| the URAM cache array, and the shipped `OOC9B_URAM: 182` reproduced from the slot declarations | `evidence/qwen_next/feas2/resource2.py` → `evidence/qwen_next/feas2/f12_resource2.log`; the comparand is `NEXT_SESSION.md` §9 |
| the throughput model, the committed A/Bv and 47.00 reproduced, the score against the shipped 9B, the layer terms, one-board and two-board projections, the link sweep | `evidence/qwen_next/feas2/toks2_model.py` → `evidence/qwen_next/feas2/f13_toks2_model_rates.log` (`evidence/qwen_next/feas2/f11_toks2_model_fix.log` is the same without the rate sweep; `evidence/qwen_next/feas2/f09_toks2_model.log` carries **two errors of mine**, corrected in f11, and is kept as the record) |
| GTY quads for both QSFP cages and for PCIe, the SLRs, the no-collision verdict | `evidence/qwen_next/feas2/gty_sites.tcl` → `evidence/qwen_next/feas2/f02_gty_sites.log`, verdicts at `evidence/qwen_next/feas2/f02_gty_sites.log:498` and `evidence/qwen_next/feas2/f02_gty_sites.log:504`; cross-checked against `synth/constraints/PROVENANCE.md` |
| Aurora / CMAC / XXV licence status, the installed features, the CMACE4 census, the expiry dates | `evidence/qwen_next/feas2/ip_catalog.tcl` → `evidence/qwen_next/feas2/f03c_ip_catalog.log` (`evidence/qwen_next/feas2/f03_ip_catalog.log` and `evidence/qwen_next/feas2/f03b_ip_catalog.log` are the two failed runs, kept as the record) |
| the shipped 9B's measured 7.2928 tok/s, 137.1210 / 137.1413 ms, `L_LCYC` 41.588, `L_SDMA_CYC` 5.125, the per-channel weight split, the state traffic, prefill at decode rate | `evidence/qwen9b/g6/RD9_GATE.md` §10.1, §10.2, §10.3, §16 |
| what is on the board, the state region bases, EMBLOG2 13, the stream and blob sizes, the standing RTL ladder, the 0.000 margin, the `T < 512` ceiling | `NEXT_SESSION.md` §1, §2, §9 and Key invariants |
| the as-built scratch array, the caches, the head fields, the SLD/SST envelope, the CONV ceiling | `rtl/layer_chan.sv` (lines cited inline in §2) |
| vecnorm's ceiling and its power-of-two-only construction | `rtl/vecnorm_unit.sv:86`, `rtl/vecnorm_unit.sv:285`, `rtl/vecnorm_unit.sv:432-434` |
| the ALU length field | `rtl/vec_alu.sv:112`, `rtl/layer_chan.sv:942` |
| `MAX_NG`, the SHAPE field, the X window | `rtl/matvec_engine.sv:142`, `rtl/matvec_engine.sv:150`, `rtl/matvec_chan.sv:18`, `rtl/matvec_chan.sv:564`, `sw/hwmap.py:85` |
| EMBLOG2's field, its guard and its shift | `rtl/seq_unit.sv:346-347`, `rtl/seq_unit.sv:1328-1332`, `rtl/seq_unit.sv:933-934`, `sw/hwmap.py:343` |
| the SEQ opcode set, MVGO's static address, the indirection refusal, the one CSR read path | `rtl/seq_unit.sv:271-274`, `rtl/seq_unit.sv:1083-1085`, `rtl/seq_unit.sv:787-788`, `rtl/seq_unit.sv:1375-1376` |
| the TOPK sidecar and its host-only readback | `rtl/layer_chan.sv:2745`, `rtl/layer_chan.sv:2761`, `docs/SEQ_ISA.md:592`, `docs/SEQ_ISA.md:594` |
| the emitter's compile-time weight address and its loop closure | `ref/seq_format.py:2006-2008`, `ref/seq_format.py:2301`, `ref/seq_format.py:2331`, `ref/seq_format.py:2336` |
| the closed walls — key/value head algebra, SCA tiles, multi-shard, untied head | `ref/layer_ref.py:46`, `ref/scripts/bytes_per_token.py:129`, `ref/gen_layer_script.py:125-128`, `ref/gen_layer_script.py:200`, `ref/load_qwen35.py:96`, `ref/load_qwen35.py:253-255`, `ref/load_qwen35.py:262-268` |
| the per-model literals a new tag needs | `ref/model_select.py:12-17`, `ref/layer_fixed.py:103`, `ref/seq_chat.py:178`, `sw/chat_seq.py:250`, `sw/chat_seq.py:567-575`, `sw/chat_seq.py:3128`, `sw/infer.py:98`, `sw/infer.py:675` |
| the DDR windows and the packing law | `sw/hwmap.py:483`, `sw/hwmap.py:486`, `sw/hwmap.py:562` |
| the state-spill caches, the block table and the DMA lane | `docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md` §2, §3, §4; `docs/SEQ_ISA.md:1273-1281` |
| the 4B/9B study this one is a companion to — the confidence labels, the wall list's shape, the runtime `EMB_BASE` fix and its 0.055 % price, the layer-term scaling law | `docs/QWEN35_NEXT_FEASIBILITY.md` §0, §2.1, §3.2, §4.3 |
| the committed throughput model, its fitted `A` and `Bv`, its mover cost law | `evidence/qwen_next/feas/toks_model.py`, `evidence/qwen_next/feas/toks_model.json` |
| the charter's two-board stretch goal, the lab facts, the safety rails | `CHARTER.md` |
| the speedup ladder, the ~280 tok/s two-board framing, the 17.875 GB/s/chan probe | `docs/ARCHITECTURE.md` |
| the community QSFP pin data's provenance and the local deviations from upstream | `synth/constraints/PROVENANCE.md` |
| **the Vivado licence that is actually checked out, and its 22-sep-2026 expiry, in the tool's own words** | `synth/out_build_041/build_run.log:280-281` (synthesis, 2026-09-07) and `synth/out_build_041_ckr2_AltSpreadLogic_high/fullimpl.log:535-536` (implementation) — **not** `f03c`'s `.lic` text scan, which is a file read and says so in §5.2 |
| the three comparands for the 9B layer term, and RD9's refusal to attribute the 9.9 % gap | `evidence/qwen9b/g6/RD9_GATE.md` §10.2, §10.2a |
| the measured 0.8B W4 g128 step and its 48.0 % layer share; the legal pipeline cuts per model | `evidence/qwen_next/feas2/fix1_checks.py` → `evidence/qwen_next/feas2/f15_fix1_checks.log`, over `evidence/qwen_next/feas/f05_toks_model.log:61` and each checkpoint's own `layer_types` |

> **A note on every log's `=== tree:` line.** Logs `f01` through `f14` were
> written by a version of `evidence/qwen_next/feas2/feas2_run.sh` that evaluated
> `git status --porcelain` **inside** the block piped into `tee <the log>` — so
> bash had already created the untracked log, and the stamp read `+dirty` on a
> clean tree as much as a dirty one. (Every log of the earlier `feas/` study
> reads `+dirty` for the same reason.) **Those fourteen `+dirty` stamps
> therefore carry no information.** Fix round 1 moved the stamp before the
> pipeline and excludes the log's own path, so `f15` onward means what it says.
> Nothing else about the logs changes, and the `f14` claim is unaffected:
> `git diff` over `docs/QWEN35_2BOARD_FEASIBILITY.md` between its commit and
> `f14`'s is empty either way.

> **One citation deliberately NOT in `path:line` form.** The community QSFP pin
> file lives outside this repository, under
> ~/r2d2/code/fpga/references/Custom\_Part\_Data\_Files/Boards/Xilinx\_BCU1525/ ,
> and is named BCU1525\_QSFP.xdc. It is cited by name rather than as a path
> because the citation checker resolves paths inside the tree, and a path it
> cannot resolve is a failure, not a note.

> **A closing note on the two-board figure this project has carried since the
> beginning.** `docs/ARCHITECTURE.md`'s speedup ladder names *"2-board tensor
> parallelism over QSFP28 (~280 tok/s ceiling)"*. That figure is the **0.8B**
> model's dense tensor-parallel *bandwidth* ceiling — twice the one-board
> physics limit — and it is a **throughput** framing. This study is a
> **capacity** framing of the same hardware, at models 30–40× larger, and its
> numbers are two orders of magnitude below it. The two are not in conflict and
> neither supersedes the other; they answer different questions about the same
> cable.
