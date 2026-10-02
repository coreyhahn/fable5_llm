# Q0 part 1: Qwen3.5-2B checkpoint downloaded + verified — PASSED

Date: 2026-08-12. Repo `5b8bda7` (branch `qwen2b`), Track Q task 2 — but this
text is **amended through `81f2c3f`** (the param-census correction), which is
the commit it reads as of.
Hosts: darthplagueis (local) and snoke — HF caches are per-machine, so
both were downloaded and both were verified independently.

HF repo id `Qwen/Qwen3.5-2B` exists; revision
`15852e8c16360a2fea060d615a32b45270f8a8fc` on both hosts.
Probed variant `Qwen/Qwen3.5-2B-Instruct` → 404 (does not exist); the
plain `Qwen/Qwen3.5-2B` id in the brief is the right one.

## Verdict against the feasibility study's checkpoint claims

`docs/QWEN2B_FEASIBILITY.md:13-18` claims, each re-verified here:

| claim | result |
|---|---|
| single-file checkpoint, loader-compatible | **CONFIRMED** — one `.safetensors`, `find_checkpoint()` returns it without the multi-shard raise |
| 4.55 GB | **CONFIRMED** — 4,548,221,488 bytes (4.548 GB decimal / 4337.5 MiB) |
| only `hidden_size` 1024→2048 and `intermediate_size` 3584→6144 move | **CONFIRMED** — real-2B vs real-0.8B `text_config` diff is exactly `{hidden_size: (1024, 2048), intermediate_size: (3584, 6144)}`, nothing else |
| identical layer pattern (18 DN + 6 GQA, same positions) | **CONFIRMED** — `layer_types` identical (falls out of the 2-field diff); smoke asserts 24 = 18 + 6 |
| identical DeltaNet geometry (16 heads, dk=dv=128) | **CONFIRMED** — `linear_num_{key,value}_heads`=16, `linear_{key,value}_head_dim`=128 unchanged |
| identical conv, CONV_DIM 6144 | **CONFIRMED** — `dn.conv_w shape=(6144, 4)` at H=2048 |
| identical GQA 8/2, `head_dim` 256 | **CONFIRMED** — unchanged in `text_config` |
| same vocab 248,320 | **CONFIRMED** — `emb shape=(248320, 2048)`, tied LM head |
| byte-identical tokenizer + chat template | **CONFIRMED** — sha256 equal for all 5 tokenizer assets (below) |

No feasibility claim about the checkpoint was falsified.

## 1. Shard: single file, both hosts bit-identical

```
path (both hosts, identical):
  ~/.cache/huggingface/hub/models--Qwen--Qwen3.5-2B/snapshots/
  15852e8c16360a2fea060d615a32b45270f8a8fc/
  model.safetensors-00001-of-00001.safetensors
size:              4,548,221,488 bytes (4337.5 MiB)
safetensors HEADER sha256:
  ccba2c1f645fe59268f89ee7ea552e02ce6bf0c8a087bf332fb0e3bd99bfee9d
tensors:           632 total, 320 under 'model.language_model.'
```

Snoke read back through the same loader (`LQ.find_checkpoint()` +
`LQ.SafeTensors(...).header_sha`) reports byte count, header sha and
tensor count **equal to darthplagueis**, and its on-disk `config.json`
compares equal to the committed `ref/qwen3_5_2b_config.json`:

```
SNOKE bytes: 4548221488
SNOKE header_sha: ccba2c1f645fe59268f89ee7ea552e02ce6bf0c8a087bf332fb0e3bd99bfee9d
SNOKE tensors: 632
SNOKE hf config == repo 2b config: True
SNOKE tokenizer sha: 5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42
```

`find_checkpoint()`'s multi-shard guard (`load_qwen35.py:91-95`) does
NOT fire: the snapshot's only `*.safetensors` glob hit is the one file
above (`model.safetensors.index.json` does not match the pattern).

Header-derived parameter census (whole file, both models). The shard has
**three** top-level tensor prefixes — `model.language_model.`,
`model.visual.` and `mtp.` — and the three account for every tensor and
every parameter (residual exactly 0):

| | 0.8B | 2B |
|---|---|---|
| file bytes | 1,746,942,600 | 4,548,221,488 |
| tensors | 488 = 320 + 153 + 15 | 632 = 320 + 297 + 15 |
| **total params** | **873,438,784** (0.8734 G) | **2,274,069,824** (2.2741 G) |
| `model.language_model.*` (320 t) | 752,393,024 (0.7524 G) | 1,881,825,088 (1.8818 G) |
|   — of which embedding (tied) | 254,279,680 | 508,559,360 |
|   — of which non-embedding | 498,113,344 (0.4981 G) | 1,373,265,728 (1.3733 G) |
| `model.visual.*` (153 / 297 t) | 100,592,896 (0.1006 G) | 331,416,576 (0.3314 G) |
| `mtp.*` (15 t) | 20,452,864 (0.0205 G) | 60,828,160 (0.0608 G) |
| text + visual + mtp == total | yes (residual 0) | yes (residual 0) |

**The MTP head is really in the checkpoint** — `text_config`'s
`mtp_num_hidden_layers: 1` is honest, not vestigial metadata. Its 15
tensors at 2B are one full transformer block plus the fusion front-end:

```
mtp.fc.weight                                 (2048, 4096)
mtp.pre_fc_norm_embedding.weight              (2048,)
mtp.pre_fc_norm_hidden.weight                 (2048,)
mtp.layers.0.input_layernorm.weight           (2048,)
mtp.layers.0.post_attention_layernorm.weight  (2048,)
mtp.layers.0.self_attn.{q,k,v,o}_proj.weight  (4096/512/512/2048, 2048)
mtp.layers.0.self_attn.{q,k}_norm.weight      (256,)
mtp.layers.0.mlp.{gate,up}_proj.weight        (6144, 2048)
mtp.layers.0.mlp.down_proj.weight             (2048, 6144)
mtp.norm.weight                               (2048,)
```

It is a **full_attention** block (GQA 8/2, head_dim 256) at the 2B
width, i.e. it scales with the migration exactly like the body layers.

Scope for this project: `load_layer()` / the whole `ref/` chain filter on
the `model.language_model.` prefix (320 tensors), so **neither the vision
tower nor the MTP head reaches our loader** — the smoke's
"visual/mtp ignored" line is accurate and unchanged by this correction.
Any later parameter-budget or weight-packing arithmetic must budget from
the **1,881,825,088** text figure (or 1,373,265,728 non-embedding), NOT
from the 2,274,069,824 file total, which includes 0.392 G of vision+MTP
weights we never load.

## 2. Config: `text_config` field-exact — DIFFS: none

Brief Step 2 run verbatim:

```
SHARD: .../models--Qwen--Qwen3.5-2B/snapshots/15852e.../model.safetensors-00001-of-00001.safetensors
TEXT_CONFIG DIFFS: none
```

**Fix applied.** A whole-file (not just `text_config`) comparison found
that the Task-1 hand-authored `ref/qwen3_5_2b_config.json` — built by
editing two fields of the 0.8B copy — carried the 0.8B `vision_config`,
which is wrong for 2B in 5 fields:

```
vision_config.depth             ours=12   hf=24
vision_config.hidden_size       ours=768  hf=1024
vision_config.num_heads         ours=12   hf=16
vision_config.intermediate_size ours=3072 hf=4096
vision_config.out_hidden_size   ours=1024 hf=2048
```

The repo convention is that these config JSONs are **verbatim copies**
of the upstream file — proven for the 0.8B, whose committed copy is
byte-identical to its cache original (both sha256
`b90b86f35c8e6925ef74ee04d0e758f0a845c83a42089ad82bbaa948de9b4204`).
`ref/qwen3_5_2b_config.json` was therefore replaced with a verbatim
copy of the downloaded `config.json`:

```
ed1c1723241f23f7f4e23430759cbd7dcfb4103cbdfe052bfe7626b57c2615b4  <cache>/config.json
ed1c1723241f23f7f4e23430759cbd7dcfb4103cbdfe052bfe7626b57c2615b4  ref/qwen3_5_2b_config.json
```

This does not move any number the `ref/` chain reads (`load_config()`
returns `text_config` only, and `text_config` already matched) — it
removes a stale-vision-metadata trap for any later reader.

Task 1's test still green after the swap (all 4 assertions):

```
$ bash ref/scripts/test_model_select.sh
MODEL_SELECT_PASS
```

## 3. Tokenizer: byte-identical to 0.8B

All five tokenizer/chat assets are sha256-equal between the 0.8B and 2B
snapshots (the feasibility study only claimed tokenizer + chat
template; the rest were checked for completeness):

```
IDENTICAL  tokenizer.json         5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42
IDENTICAL  chat_template.jinja    273d8e0e683b885071fb17e08d71e5f2a5ddfb5309756181681de4f5a1822d80
IDENTICAL  vocab.json             ce99b4cb2983d118806ce0a8b777a35b093e2000a503ebde25853284c9dfa003
IDENTICAL  merges.txt             a9d356d7bdf1ef4949e3e748e95b8e10ad9d4e2e838eddc38a0a7b6b94d1db8d
IDENTICAL  tokenizer_config.json  49e2b6e395f959f077f1e992b338919c0d4a9732fc6e613995e06557f843500c
```

Consequence: every committed prompt/token stream tokenizes identically
under 2B — no re-tokenization work in the migration.

## 4. Loader smoke: `FABLE5_MODEL=2b ref/.venv/bin/python ref/load_qwen35.py`

Passes unmodified — the smoke main needed no edits; its shape prints
come from the checkpoint and its asserts are geometry-independent
counts.

```
checkpoint: /home/cah/.cache/huggingface/hub/models--Qwen--Qwen3.5-2B/snapshots/15852e8c16360a2fea060d615a32b45270f8a8fc/model.safetensors-00001-of-00001.safetensors
            4337.5 MiB
header sha256: ccba2c1f645fe59268f89ee7ea552e02ce6bf0c8a087bf332fb0e3bd99bfee9d
tensors: 632 total, 320 under 'model.language_model.' (visual/mtp ignored)

--- layer 0 (linear_attention) ---
  ln1        shape=(2048,)          |max|=   1.0859 rms=  0.15188
  ln2        shape=(2048,)          |max|=   0.9961 rms=  0.10864
  mlp.gate   shape=(6144, 2048)     |max|=   0.1875 rms=  0.00999
  mlp.up     shape=(6144, 2048)     |max|=   0.1147 rms=  0.00822
  mlp.down   shape=(2048, 6144)     |max|=   0.3301 rms=  0.00827
  dn.A_log   shape=(16,)            |max|=   5.9062 rms=  2.84286
  dn.conv_w  shape=(6144, 4)        |max|=   1.5234 rms=  0.06309
  dn.dt_bias shape=(16,)            |max|=  12.3125 rms=  6.37012
  dn.in_a    shape=(16, 2048)       |max|=   0.2217 rms=  0.02909
  dn.in_b    shape=(16, 2048)       |max|=   0.1191 rms=  0.01344
  dn.in_qkv  shape=(6144, 2048)     |max|=   0.3945 rms=  0.01476
  dn.in_z    shape=(2048, 2048)     |max|=   0.3711 rms=  0.01399
  dn.norm_w  shape=(128,)           |max|=   1.0107 rms=  0.92170
  dn.out     shape=(2048, 2048)     |max|=   0.3887 rms=  0.01201

--- layer 3 (full_attention) ---
  ln1        shape=(2048,)          |max|=   0.7109 rms=  0.16404
  ln2        shape=(2048,)          |max|=   0.5117 rms=  0.12433
  mlp.gate   shape=(6144, 2048)     |max|=   0.1582 rms=  0.01153
  mlp.up     shape=(6144, 2048)     |max|=   0.1187 rms=  0.00801
  mlp.down   shape=(2048, 6144)     |max|=   0.3223 rms=  0.00793
  attn.k_norm  shape=(256,)           |max|=   1.5938 rms=  0.46410
  attn.k_proj  shape=(512, 2048)      |max|=   0.1426 rms=  0.01223
  attn.o_proj  shape=(2048, 2048)     |max|=   0.3809 rms=  0.01175
  attn.q_norm  shape=(256,)           |max|=   1.1797 rms=  0.45494
  attn.q_proj  shape=(4096, 2048)     |max|=   0.3203 rms=  0.01605
  attn.v_proj  shape=(512, 2048)      |max|=   0.1396 rms=  0.01190

  ln_f       shape=(2048,)          |max|=   5.3750 rms=  2.57653
  emb        shape=(248320, 2048)   |max|=   0.1973 rms=  0.01501  (tied: LM head == emb)

  emb raw-bytes sha256   b222b11204158144e369ae8fca02cab9cb63b0a8cde1dd59dd4d0c60690824ed
  24-layer raw-bytes sha256 2d9d578cb6edc4cd9a4fe1db457bb1af320866512aea5913849e75d915ed812e
  float64 sum(|emb|)     5.953986e+06

LOAD_QWEN35 SMOKE PASS (24 layers = 18 DeltaNet + 6 GQA, shapes match layer_ref constants)
```

Shapes are exactly the width scale-up the study predicted: MLP
(6144, 2048)/(2048, 6144), DN conv still 6144-wide, GQA q 4096 / k,v 512
(8 and 2 heads x head_dim 256) — the DeltaNet and KV geometries do NOT
move.

### Default (0.8B) path unregressed

```
$ ref/.venv/bin/python ref/load_qwen35.py            # no FABLE5_MODEL
  emb        shape=(248320, 1024)   |max|=   0.2305 rms=  0.01970  (tied: LM head == emb)
  emb raw-bytes sha256   3247e63f0f265462e2fba5316dfb2819941ea8ed62ab5b2c4904e4aab5b9d7aa
  24-layer raw-bytes sha256 c01fbf58d98b8f1dcbc7ecb43d1101300e1425ccd30679f2a113ac2edbfa8740
  float64 sum(|emb|)     3.939775e+06
LOAD_QWEN35 SMOKE PASS (24 layers = 18 DeltaNet + 6 GQA, shapes match layer_ref constants)
```

## Environment note (not a blocker for this task)

`ref/.venv` is NOT usable on snoke: its `bin/python` symlinks to
`/home/cah/.local/share/uv/python/cpython-3.11-.../bin/python3.11`,
which lives in the per-host home dir and is absent on snoke (only
`r2d2/code/` is NFS-shared, not `$HOME`). Snoke's verification above was
run with `uv run --no-project --with numpy` against the same
`ref/load_qwen35.py`; nothing was installed into `ref/.venv`. Any later
Track Q step that wants the `ref/` chain to run ON snoke must first
create a snoke-local venv (`uv venv` in a snoke-local path).
