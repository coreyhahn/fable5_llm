# Q0 part 2: 2B bf16 golden built + `validate_vs_torch` PASS at H=2048 — PASSED

Date: 2026-08-12. Repo `ccf55f9` (branch `qwen2b`), Track Q task 3.
Host: **darthplagueis** for both steps (see "Host choice" below).

Two gates, both green:

| gate | criterion | result |
|---|---|---|
| Step 1 — numpy decode vs transformers at H=2048 | `max_rel_err < 2e-4` (`ref/validate_vs_torch.py:119`) | **PASS** — worst 1.231e-06, ~160x inside the threshold |
| Step 3 — bf16 free-run text | coherent, on-topic English on all four prompts | **PASS** — 4/4 coherent, no repetition loop, no gibberish |

## Host choice: darthplagueis, not snoke (deviation from the brief, forced)

The brief and `ref/validate_vs_torch.py:12` both say "run on snoke". **snoke has no
torch at all** — neither the system interpreter nor its one venv:

```
$ ssh snoke 'python3 -c "import torch"'
ModuleNotFoundError: No module named 'torch'
$ ssh snoke 'ls /home/cah/venvs/'
fable5_np
$ ssh snoke '/home/cah/venvs/fable5_np/bin/python3 -c "import torch"'
ModuleNotFoundError: No module named 'torch'
```

`fable5_np` is the numpy-only venv `ref/fidelity_check.py:87-88` points at for
the *fixed-point* phase, which is all snoke has ever needed. The torch-capable
interpreter is darthplagueis' system `python3` — the same one that built the
0.8B golden (`ref/fidelity_check.py:85-86`) — so both steps ran there:

```
torch 2.6.0+cu124   transformers 5.2.0   numpy 2.3.5   (darthplagueis, 32 cores)
```

This is a host substitution only; the interpreter is the one the reference
chain has always used for torch work. The `validate_vs_torch.py:12` docstring
was stale and was corrected in `7d2af40`.

## Step 1 — `layer_ref` at H=2048 vs transformers (random-init 2-layer)

```
$ FABLE5_MODEL=2b python3 ref/validate_vs_torch.py
The fast path is not available because one of the required library is not installed. Falling back to torch implementation. To install follow https://github.com/fla-org/flash-linear-attention#installation and https://github.com/Dao-AILab/causal-conv1d
layer 0 (linear_attention): max_rel_err = 7.538e-07
  per-token: 4.8e-07 4.8e-07 7.5e-07 5.9e-07 7.5e-07 7.3e-07 6.3e-07 4.8e-07 6.0e-07 6.1e-07 5.8e-07 7.0e-07
layer 1 (full_attention): max_rel_err = 1.231e-06
  per-token: 9.0e-07 7.7e-07 1.2e-06 9.1e-07 8.2e-07 8.7e-07 9.7e-07 8.9e-07 8.7e-07 1.0e-06 8.9e-07 8.4e-07
VALIDATE_VS_TORCH PASS
```

Exit 0, 5.9 s wall. The "fast path" line is the expected `flash-linear-attention`
notice — transformers falls back to its pure-torch DeltaNet kernel, which is the
path we want to be compared against anyway.

What this proves: the numpy **single-token recurrent decode** in `ref/layer_ref.py`
reproduces transformers' **chunked delta-rule prefill** and its masked-prefill
attention at the widened 2B geometry (hidden_size 2048, intermediate_size 6144),
to fp32 round-off. Both layer types are covered — the toy model is built with
`layer_types=["linear_attention", "full_attention"]` (`validate_vs_torch.py:33`).

The error magnitude is the same order as the 0.8B run — the same script under
`FABLE5_MODEL=0.8b`, executed here for the comparison, also PASSes:

| geometry | layer 0 (DeltaNet) | layer 1 (GQA) |
|---|---|---|
| 0.8b (H=1024, I=3584) | 3.964e-07 | 6.148e-07 |
| 2b (H=2048, I=6144) | 7.538e-07 | 1.231e-06 |

Both layers land at almost exactly 2.0x the 0.8B error, tracking the 2x wider
reduction (fp32 accumulation round-off grows with the dot-product length) rather
than showing the step-change a geometry-handling bug would produce. Widening H
did not break the numpy decode. Gate cleared before any golden-build time was
spent.

## Step 2 — the real 2B bf16 golden

```
$ FABLE5_MODEL=2b python3 ref/fidelity_check.py --golden \
    --cache tb/scripts_scratch/golden_bf16_2b.npz --ntok 24 --free-ntok 24
golden: /home/cah/.cache/huggingface/hub/models--Qwen--Qwen3.5-2B/snapshots/15852e8c16360a2fea060d615a32b45270f8a8fc/model.safetensors-00001-of-00001.safetensors
  header sha256 ccba2c1f645fe59268f89ee7ea552e02ce6bf0c8a087bf332fb0e3bd99bfee9d
  24 layers vocab=248320 torch=2.6.0+cu124
  model built + loaded in 23.2s
  ...
  p4 step 26: in=   303 argmax=   279 logit=+18.5607
golden cache -> tb/scripts_scratch/golden_bf16_2b.npz
```

Exit 0. 108 decode steps (4 prompts x 27 steps). The checkpoint header sha256
matches `checkpoint_verify.md` exactly, so this golden is provably built from
the verified shard — and `fidelity_check.py:834-835` will re-assert that
equality for every consumer of the cache.

**Wall time: 83.1 s** (22:49:54.38 -> 22:51:17.48), of which 23.2 s is model
build + load. This is ~40x faster than the brief's "budget tens of minutes"
estimate. The estimate mis-modelled the work: the "~80 s LM-head quantize" cost
cited for 0.8B belongs to the *fixed-point* phase, and `--golden` returns
immediately after `build_golden()` (`fidelity_check.py:816-818`) without ever
entering it. No quantization runs on this path.

### Cache

```
path    tb/scripts_scratch/golden_bf16_2b.npz     (gitignored, .gitignore:14 — regenerable, not committed)
size    89,440 bytes
sha256  853852e8e5738546648eaa9165e4292822d8a489368d35e471782cda031dde6c
```

Schema as built (`fidelity_check.py:151-168`), per prompt p in 1..4:

```
p{p}_argmax (27,)      int64     per-step greedy argmax
p{p}_seq    (27,)      int64     prompt ids then the free-run continuation
p{p}_topk_i (27, 64)   int64     top-64 logit indices
p{p}_topk_v (27, 64)   float32   top-64 logit values
meta        (2,)       int64     [ntok=24, TOPK=64]
header_sha256 ()       <U64      ccba2c1f...bfee9d
```

Note `--free-ntok 24` is a **no-op on the `--golden` path**: `build_golden()`
is called with only `ntok` (`fidelity_check.py:817`), and the free-running
horizon it generates is `ntok` itself — it appends its own argmax once the
prompt is consumed (`fidelity_check.py:161-162`). Because both flags were 24 the result
is exactly what the brief intended; the flag is simply redundant here, and
`--free-ntok` only bites on the fixed-point phases. So the golden argmax IS the
bf16 free run: 4 prompt tokens + 24 generated = the 27 rows above, with the
generated span at `argmax[len(ids) - 1:]`, matching `fidelity_check.py:935`.

## Step 3 — the four bf16 free-run texts (the gate)

Decoded from the cache with `gen_model_script.Tok` (the same tokenizer view
`fidelity_check.py:934` uses to print `text=`). The decoder was first validated
against the committed 0.8B golden, where it reproduces that cache's known texts.
All four verbatim, prompt in plain text and the 24 generated tokens after it:

### prompt 1 — `'The capital of France'` (ids `[760, 6511, 314, 9338]`)

```
gen_text=' is Paris.\nA. True\nB. False\n\n<think>\nThinking Process:\n\n1.  **Analyze'
full_text='The capital of France is Paris.\nA. True\nB. False\n\n<think>\nThinking Process:\n\n1.  **Analyze'
gen_ids=[369, 11751, 13, 198, 32, 13, 2912, 198, 33, 13, 3439, 271, 248068, 198, 90700, 8340, 25, 271, 16, 13, 220, 2972, 2014, 53983]
```

### prompt 2 — `'Once upon a time'` (ids `[12162, 5028, 264, 854]`)

```
gen_text=', in a magical land called the Kingdom of Numbers, there lived a group of very special numbers. These numbers were called'
full_text='Once upon a time, in a magical land called the Kingdom of Numbers, there lived a group of very special numbers. These numbers were called'
gen_ids=[11, 303, 264, 22960, 4128, 2512, 279, 14634, 314, 33565, 11, 1017, 11815, 264, 1809, 314, 1546, 3175, 4947, 13, 4081, 4947, 998, 2512]
```

### prompt 3 — `'import numpy as np'` (ids `[464, 8328, 430, 2510]`)

```
gen_text='\nimport matplotlib.pyplot as plt\nfrom sklearn.datasets import load_iris\nfrom sklearn.model_selection import train_test_split\n'
full_text='import numpy as np\nimport matplotlib.pyplot as plt\nfrom sklearn.datasets import load_iris\nfrom sklearn.model_selection import train_test_split\n'
gen_ids=[198, 464, 16309, 22974, 430, 6313, 198, 1445, 17451, 56199, 1120, 2706, 62, 40561, 198, 1445, 17451, 3090, 22931, 1120, 5257, 4306, 16551, 198]
```

### prompt 4 — `'Hello world! My'` (ids `[9419, 1814, 0, 2921]`)

```
gen_text=' name is **Sara**. I am a **Senior Software Engineer** with over 10 years of experience in the'
full_text='Hello world! My name is **Sara**. I am a **Senior Software Engineer** with over 10 years of experience in the'
gen_ids=[803, 369, 2972, 50, 4897, 159034, 353, 1044, 264, 2972, 45523, 4236, 27458, 332, 440, 888, 220, 16, 15, 1578, 314, 3039, 303, 279]
```

### Verdict: PASS (4/4)

Judged against "coherent, on-topic English", per prompt:

- **p1 PASS, with a noted quirk.** Factually correct and on-topic (`is Paris.`),
  well-formed English throughout, no loop. It then re-frames its own statement
  as a true/false quiz and opens a reasoning trace, emitting the `<think>`
  special token (id 248068) in a raw non-chat continuation. That is a genre
  shift, not a degeneracy: every token is well-formed and topically anchored to
  the France statement. It is ordinary base-model behaviour for a checkpoint
  whose pretraining mix contains exam items and reasoning traces, and 24 tokens
  of greedy decode from a 4-token fragment gives it nothing else to latch onto.
  Flagged here because a later quantized run that drops the `<think>` token, or
  emits it somewhere else, is a *format* difference and should not be scored as
  a semantic regression.
- **p2 PASS.** Fluent, sustained narrative; correct story register; a complete
  clause chain over the full 24 tokens.
- **p3 PASS.** Syntactically valid Python and semantically sensible — the
  canonical numpy/matplotlib/sklearn import block, correct module paths,
  correct `from X import Y` forms. The strongest of the four.
- **p4 PASS.** Coherent self-introduction, consistent register, correct markdown
  emphasis pairing.

No prompt shows a repetition loop, degenerate n-gram cycling, cross-lingual
drift, or gibberish. This is the full-native-resolution reference the rest of
Track Q compares against.

### Sanity contrast with the committed 0.8B golden

Not a gate — recorded because it is the obvious question and it argues the 2B
golden is sound. Same prompts, same greedy decode, 0.8B cache
(`tb/scripts_scratch/golden_bf16.npz`, ntok=8):

| prompt | 0.8B (8 tok) | 2B (24 tok) |
|---|---|---|
| 1 | `' is Paris.\nThe capital of France'` | `' is Paris.\nA. True\nB. False\n\n<think>...'` |
| 2 | `', in a world where everything was made'` | `', in a magical land called the Kingdom of Numbers, ...'` |
| 3 | `'\nimport pandas as pd\nimport matplotlib'` | `'\nimport matplotlib.pyplot as plt\nfrom sklearn...'` |
| 4 | `' name is\nSamantha.\n'` | `' name is **Sara**. I am a **Senior Software Engineer**...'` |

Both models agree on the France answer and on the first generated token of all
four prompts (`369 ' is'`, `11 ','`, `198 '\n'`, `803 ' name'`) — p3 agrees on
the first two (`198 '\n'`, `464 'import'`) — then they diverge, which is what
different weights under greedy decode should do. Worth noting that at p1 the
*0.8B* is the one that loops (its generated tokens 5-8 are `760 6511 314 9338`,
the prompt restated verbatim); the 2B does not repeat. Nothing here suggests a
load or geometry fault in the 2B path.

## Reproduce

```bash
# gate (cheap, ~5-6 s, random-init 2-layer toy)
FABLE5_MODEL=2b python3 ref/validate_vs_torch.py

# golden (~83 s on darthplagueis; needs the verified 2B shard in the HF cache)
FABLE5_MODEL=2b python3 ref/fidelity_check.py --golden \
    --cache tb/scripts_scratch/golden_bf16_2b.npz --ntok 24 --free-ntok 24
sha256sum tb/scripts_scratch/golden_bf16_2b.npz
# -> 853852e8e5738546648eaa9165e4292822d8a489368d35e471782cda031dde6c
```

Both need the torch-capable interpreter (darthplagueis system `python3`), not
snoke. Consumers of the cache (Track Q tasks 5-9) are numpy-only and run
anywhere; they re-check `header_sha256` against the loaded checkpoint on entry.
