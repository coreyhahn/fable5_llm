# Track L gate 0 — the 4B and 9B checkpoints, verified — PASSED (both)

Date 2026-08-25. Host **snoke** (all compute for this track runs there).
Script `checkpoint_verify.py`, logs `checkpoint_verify_4b.log` /
`checkpoint_verify_9b.log`, download log `fetch_checkpoints.log`.
Same shape as `evidence/qwen2b/q0/checkpoint_verify.md`, which is the model.

The script does not print a summary and stop; it **asserts every shape, count
and parameter total that `docs/QWEN35_NEXT_FEASIBILITY.md` §1/§1.1/§1.3
predicts**, prints a `DEVIATION` line for any mismatch and exits non-zero.
Both models exit 0.

> **VERDICT: the feasibility study's §1 census is correct in every particular
> at both targets. Zero deviations.** Including the two that mattered most —
> the 16-key/32-value DeltaNet head split and the 9B's untied top-level LM
> head — which are now confirmed against the tensors, not against `config.json`.

---

## 1. Download and disk

| | 4B | 9B |
|---|---|---|
| revision | `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` | `c202236235762e1c871ad0ccb60c8ee5ba337b9a` |
| shards | **2** | **4** |
| bytes | 9,319,828,096 = **8.680 GiB** | 19,306,310,880 = **17.980 GiB** |
| study §1 predicted | 8.68 GiB | 17.98 GiB |
| download wall-clock | 38.7 s | 68.5 s |

Disk on snoke, re-verified on the day as the plan required
(`docs/QWEN35_NEXT_FEASIBILITY.md` §5 recorded 94 GB free):

```
before      /dev/nvme0n1p1  458G  341G   94G  79% /
after 4B    /dev/nvme0n1p1  458G  350G   85G  81% /
after 9B    /dev/nvme0n1p1  458G  368G   67G  85% /
```

**94 GB free confirmed, 67 GB left after both checkpoints.** One correction to
the §5 disk plan is carried in `LADDER.md` §caveats: the GPTQ Hessian npz is
**bigger than §5 estimated** (13.71 GiB at 4B and 24.06 GiB at 9B against the
study's 10.1 / 21.4), because it stores one float32 K×K second moment per input
*site* and the 4B/9B `mlp_down_in` sites are K=9216 / K=12288.

### Per-shard header digests

```
4B  [0] model.safetensors-00001-of-00002.safetensors  5,329,398,688 B
        f46b4aa8c303583fedfb3780fd2a3b981300ee9cad9bc624999bac343e799fd7
    [1] model.safetensors-00002-of-00002.safetensors  3,990,429,408 B
        270d6faae3bc0e1642498e5ef12d222429a666c781022fb891302e42361b9d66
    COMBINED 6e73db95dda030ff8fa43e99e2cebb3307f91363a756b2ba115e67ae0efb72fd

9B  [0] model.safetensors-00001-of-00004.safetensors  5,276,436,216 B
        9bcf722bdd0eee137b7f0e225f4bfb50683b9b33c42de0d560498ce92a8c63b0
    [1] model.safetensors-00002-of-00004.safetensors  5,335,161,512 B
        6fb55b1326b7e6b47a38ce4723552eada6c80d09e58eda1d46f25cb8d3e06658
    [2] model.safetensors-00003-of-00004.safetensors  5,368,717,440 B
        fd6ddcdceb46ce1b198534560343050523cbf70d15e9435d7716b693d4a67bab
    [3] model.safetensors-00004-of-00004.safetensors  3,325,995,712 B
        245c737a43e483e0a9e743be9c75a366d56bec2ea238086dda8b5c2bc224571a
    COMBINED 2721100f724faea555e4afd11064461b2b231914be53e8d7468ed1be9d9f4c3b
```

**Read the COMBINED digest correctly.** For a single-shard checkpoint
`SafeTensors.header_sha` is unchanged — 0.8B's and 2B's committed digests
(`ccba2c1f…` at 2B) still print exactly as before, which is what keeps every
existing json's provenance field meaningful. For a sharded checkpoint it is a
**different kind of number**: the sha256 of the per-shard header digests,
newline-joined, in shard order. Every json this track writes also carries
`checkpoint_shard_sha256`, the per-file list, so nothing is lost.

## 2. Whole-file parameter census by top-level prefix

Every tensor in the file is accounted for by four prefixes, residual exactly
zero (the script asserts `OTHER == 0`):

| prefix | 2B (for reference) | **4B** | **9B** |
|---|---|---|---|
| `model.language_model.` | 320 t, 1,881,825,088 p | **426 t, 4,205,751,296 p** | **426 t, 7,936,684,544 p** |
| `lm_head.` (top level) | — | — | **1 t, 1,017,118,720 p** |
| `mtp.` | 15 t, 60,828,160 p | **15 t, 120,599,552 p** | **15 t, 243,290,624 p** |
| `model.visual.` | 297 t, 331,416,576 p | **297 t, 333,514,240 p** | **333 t, 456,010,480 p** |
| **file total** | 632 t, 2,274,069,824 p | **738 t, 4,659,865,088 p** | **775 t, 9,653,104,368 p** |

Every one of those twelve numbers is a §1.3 prediction and every one matches.

The vision tower and the MTP head are present at both targets, are filtered out
by `load_layer()`'s `model.language_model.` prefix exactly as at 2B, and are
**shipped-unused**. Parameter-budget arithmetic must start from the text figure
(**plus the untied head at 9B**): the loadable total is
**4,205,751,296 at 4B** and **8,953,803,264 at 9B**, and the ladder's own
`_total` accounting reproduces those two numbers independently
(4,841.450 M and 8,953.803 M, where 4B double-counts its *tied* head by
635.699 M — see `ppl_4b_bf16.log` / `ppl_9b_bf16.log`).

## 3. Geometry — `text_config` and the derived `layer_ref` constants

All twelve `text_config` fields and the 24/8 layer split confirmed at both
targets. The derived constants are the ones that matter to this repo, because
`ref/layer_ref.py` had a latent bug here (§5 below):

| | 4B | 9B |
|---|---|---|
| `LR.H` | 2560 | 4096 |
| `LR.LNH` (VALUE heads) | **32** | **32** |
| `LR.LNKH` (KEY heads) | **16** | **16** |
| `LR.LKD` = LNKH·LDK | 2048 | 2048 |
| `LR.LVD` = LNH·LDV | 4096 | 4096 |
| `LR.CONV_DIM` = 2·LKD + LVD | **8192** | **8192** |

And the tensor that proves it rather than asserting it:
`2·LKD + LVD == in_qkv.shape[0] == 8192` at both — i.e.
`8192 = 2·(16·128) + 32·128`, **16 key heads and 32 value heads**, exactly
§1.1's reading.

## 4. Per-tensor shapes vs §1.1

Every DeltaNet and GQA shape in §1.1's two tables, plus the MLP pair, checked
on the first layer of each type. All OK. The 4B set, for the record:

```
L0.dn.in_qkv  (8192, 2560)     L3.attn.q_proj (8192, 2560)
L0.dn.in_z    (4096, 2560)     L3.attn.k_proj (1024, 2560)
L0.dn.in_a    (32, 2560)       L3.attn.v_proj (1024, 2560)
L0.dn.in_b    (32, 2560)       L3.attn.o_proj (2560, 4096)
L0.dn.A_log   (32,)            L3.attn.q_norm (256,)
L0.dn.dt_bias (32,)            L3.attn.k_norm (256,)
L0.dn.conv_w  (8192, 4)        L*.mlp.gate    (9216, 2560)
L0.dn.norm_w  (128,)           L*.mlp.down    (2560, 9216)
L0.dn.out     (2560, 4096)
```

9B is the same with H 2560 → 4096 and FFN 9216 → 12288.

## 5. The 9B LM head — untied, and now proven against the tensors

§1.2's ground-truth table reproduces exactly:

| | top-level `tie_word_embeddings` | `text_config.tie_word_embeddings` |
|---|---|---|
| 4B | present, `True` | present, `True` |
| **9B** | present, **`False`** | **ABSENT** |

`ref/load_qwen35.py` previously read only `text_config`, where the 9B key is
absent, so the `True` default won and **the config guard passed silently** —
§1.2 called this out and it is confirmed. This track replaced it with
`checkpoint_is_tied()`, which takes the **tensor** as ground truth and refuses
any disagreement between the flag and the file, in either direction.

The 9B head is a genuinely different matrix, not a stored copy of the
embedding table:

```
emb      (248320, 4096)  rms=0.013466  |max|=0.4707
                         raw-bytes sha256 d87d444a38822588c6c1ed07dec4404cc…
lm_head  (248320, 4096)  rms=0.015476  |max|=0.3555
                         raw-bytes sha256 6d6ff4dbf261f833246d32e7c6088f87…
np.array_equal(emb, lm_head) == False
```

That matters beyond bookkeeping: at 9B the fixed-point harness must quantize
`lm_head` while seeding the residual from `emb`, and the two now come from
different tensors. Every 9B number in `LADDER.md` was produced that way.

## 6. Config JSONs are verbatim copies

The repo convention (`evidence/qwen2b/q0/checkpoint_verify.md` §2) is that
`ref/qwen3_5_*_config.json` are **byte-identical** copies of the upstream
`config.json`. Both new files are, and the script asserts it:

```
ddc63e1c717afa86c865bb5e01313d89d72bb53b97ad4a8a03ba8510c0621670  ref/qwen3_5_4b_config.json
d0883072e01861ed0b2d47be3c16c36a8e81c224c7ffaa310c6558fb3f932b05  ref/qwen3_5_9b_config.json
```

(The 0.8B and 2B copies were re-checked at the same time and are still
byte-identical to their snapshots.)

## 7. Tokenizer identity — §1.4 confirmed, both halves

```
tokenizer.json         IDENTICAL across 0.8B / 2B / 4B / 9B  5f9e4d4901a92b99…
vocab.json             IDENTICAL across all four             ce99b4cb2983d118…
merges.txt             IDENTICAL across all four             a9d356d7bdf1ef49…
chat_template.jinja    0.8B/2B 273d8e0e683b8850…   4B/9B a4aee8afcf2e0711…
tokenizer_config.json  0.8B/2B 49e2b6e395f959f0…   4B/9B 316230d6a809701f…
```

Exactly the split §1.4 predicts, including the two `tokenizer_config.json`
digests it names. **Consequence for this track: the pinned corpus carries
over unchanged** — `ref/ppl_corpus_eval.txt` sha256
`6bf4f8677a3b3fff178c6915e2a55b7326e534f6e54650067e33b056e4c27876` (verified
before use), and every run at both geometries scores the **same 24,528
positions** the whole 2B study scored. That is what makes the cross-study
comparison in `LADDER.md` legitimate rather than approximate.

## 8. Instruct vs base — the family layout is unchanged, and §1's implicit
assumption holds

The 2B Q0 probed `Qwen/Qwen3.5-2B-Instruct` → 404 and concluded "the plain id
is the right one". Re-run across the family, the picture is sharper and it is
**consistent at all four sizes**:

| repo id | exists | `chat_template.jinja` |
|---|---|---|
| `Qwen/Qwen3.5-{0.8B,2B,4B,9B}` | **yes** | **yes** — post-trained |
| `Qwen/Qwen3.5-{0.8B,2B,4B,9B}-Base` | **yes** | **no** — pretrained |
| `Qwen/Qwen3.5-{2B,4B,9B}-Instruct` | **404** | — |

So: there is no `-Instruct` variant at any size, a `-Base` sibling exists at
**every** size (including 0.8B and 2B, which the 2B Q0 did not record), and the
plain id is the post-trained model everywhere. **The ladder therefore scores
the same variant class the 2B study scored** — plain id, post-trained — and no
cross-study row is comparing a post-trained model against a base one.

*(One small correction to the 2B record, stated because it was stated the
other way: "the plain id is the right one" was right, but not because no
sibling exists — `Qwen/Qwen3.5-2B-Base` does exist. The distinguishing asset
is the chat template, not the repository's absence.)*

## 9. Host-model changes this gate required

Recorded here because they are the reason the two logs above are clean, and
because `LADDER.md` §walls prices them:

| change | file | why |
|---|---|---|
| multi-shard `SafeTensors` + `find_checkpoints()` | `ref/load_qwen35.py` | 4B has 2 shards, 9B has 4; the old loader raised "expected ONE safetensors shard" |
| `checkpoint_is_tied()` / `config_says_tied()`, `load_model` returns `head` + `tied` | `ref/load_qwen35.py` | the 9B untied head, and the silent `text_config` default §1.2 documented |
| `LNKH` / `VREP`, `LKD = LNKH·LDK` | `ref/layer_ref.py` | §2.9's "key heads == value heads" bug — silently computes CONV_DIM 12288 against the checkpoint's 8192 |
| `q/k` slice + `h // VREP` key index | `ref/layer_ref.py`, `ref/layer_fixed.py`, `ref/fidelity_check.py` | the same bug in the float reference, the fixed-point datapath and the block probe |
| `CkptSource.head()`, `head_f` vs `emb_f` split | `ref/perplexity_eval.py`, `ref/fidelity_check.py` | the LM head and the embedding lookup are different tensors at 9B |
| `4b` / `9b` tags | `ref/model_select.py` | selection only |

Regression discipline: `run_ref_selftests.sh` re-runs every `ref/` selftest at
**0.8b and 2b** after these edits — **15 of 16 invocations exit 0**, and the
one failure is **pre-existing on committed main**, not Track L's:

* `FABLE5_MODEL=2b ref/layer_fixed.py` fails `attn softmax+pv rel=3.288e-02`
  against a `3e-02` bound. A pristine `git archive HEAD ref` tree reproduces
  the identical value and the identical failure
  (`head_baseline_layer_fixed_2b.log`), so the diff is exonerated and the
  finding belongs to whoever owns that tolerance — see `LADDER.md`.

Everything else at the two shipped geometries is unmoved: every change is
behind `VREP > 1`, `n_shards > 1` or `not tied`, all false there, or is a new
table entry. Two independent confirmations beyond the selftests:
`load_qwen35.py`'s 2B smoke reproduces the committed raw-byte digests exactly
(`emb b222b112…`, `24-layer 2d9d578c…`, header `ccba2c1f…`), and
`bytes_per_token.py --selftest` still reproduces every committed 0.8B/2B byte
budget after the `LKD` fix. Log: `ref_selftests.log`.

---

## SUPERSEDED, dated note 2026-09-10 (pre-ship documentation chore)

**The `attn softmax+pv rel=3.288e-02` failure recorded in the regression
discipline paragraph above is real, and the framing around it is not.** It was
read across Track L as a 0.8B-tuned tolerance that a wider geometry
overshoots. **G2's D-TOL gate measured that and it is wrong**: the block is
identical at all four geometries, and the two values are two draws of one
random check rather than two geometries. See `evidence/qwen9b/g2/D_TOL.md` §2.
The sentence is kept verbatim because this document is Track L's committed
evidence and was accurate against the tree it was written on; what must not
survive it is the idea of a per-geometry attention error bound, which the
D-TOL ruling proved fictional. `evidence/qwen_next/ladder/LADDER.md` carries
the same framing and the same note.
