# Qwen3.5-2B Track Q (Quantization Tradeoff Study) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure how far every hardware-servable quantization option falls from the Qwen3.5-2B model's native bf16, and produce the decision table for gate D.

**Architecture:** Pure host-side Python. A new torch-based perplexity harness scores weight-quantization variants (quantize→dequantize→inject into the HF model); the existing `ref/fidelity_check.py` scores the bit-exact fixed-point datapath on short prompts; the ablation ladder ties the two levels together. No RTL, no board.

**Tech Stack:** numpy (ref/.venv), torch + transformers 4.57+ with `models.qwen3_5` (system `python3` on darthplagueis; snoke also has torch CPU), uv for one-off deps, HF hub for checkpoint/corpus downloads.

**Spec:** `docs/superpowers/specs/2026-08-12-qwen35-2b-migration-design.md`

## Global Constraints

- NEVER read/grep/copy the pre-existing private implementation (the "answer key") (answer key) — hard rule.
- All work on branch `qwen2b`; commit at every green gate; evidence to `evidence/qwen2b/<stage>/`.
- `ref/.venv` is numpy-only BY DESIGN (`load_qwen35.py:2-13`) — never install torch into it. Torch work uses system `python3` on darthplagueis (proven path per `fidelity_check.py:85-89`) or snoke.
- HF caches are per-machine (verified 2026-08-12): the 2B checkpoint must be downloaded on each host that loads it.
- Default behavior with `FABLE5_MODEL` unset must be byte-identical to today — every frozen 0.8B flow keeps working unmodified. This is Track R-a's regeneration gate; Track Q must not break it.
- Production quantizers only (`audit_ranges.py` principle): every variant scores the code in `ref/layer_fixed.py` / `ref/w4a8_ref.py`, never a re-implementation.
- One-off Python deps (pandas/pyarrow/huggingface_hub for corpus prep) via `uv run --with ...`, never installed into repo venvs.

**Cross-plan interfaces (with Track R plan, `2026-08-12-qwen2b-track-r.md`):**
- This plan's Task 1 (`FABLE5_MODEL` env selection + `ref/qwen3_5_2b_config.json`) is consumed by Track R-a. Do Task 1 FIRST; Track R waits on it.
- Task 10's modeled-tok/s column consumes Track R-a's re-normalized per-row mover costs. If those aren't ready, Task 10 ships the table with the feasibility-study band (11-14 ms movers, marked U) and is amended when they land.

---

### Task 1: Model-select plumbing (`FABLE5_MODEL`) + 2B config JSON

**Files:**
- Create: `ref/qwen3_5_2b_config.json`
- Modify: `ref/layer_ref.py:21-22` (config load), `ref/load_qwen35.py:56` (REPO_DIR), `ref/load_qwen35.py:163-166` (`load_config()`)
- Test: `ref/scripts/test_model_select.sh` (new)

**Interfaces:**
- Produces: env var `FABLE5_MODEL` ∈ {`0.8b` (default), `2b`}. `ref/model_select.py` with `TAG` (str), `CONFIG_JSON` (abs path), `REPO_DIR` (str, `models--Qwen--Qwen3.5-2B` for 2b). `layer_ref.CFG/H/FFN/...` and `load_qwen35.REPO_DIR/load_config()` follow the selection. Consumed by Track R-a and every later Track Q task.

- [ ] **Step 1: Write the 2B config JSON**

Copy `ref/qwen3_5_0.8b_config.json` to `ref/qwen3_5_2b_config.json` and change exactly two values in `text_config` (feasibility: 2B is a pure width scale-up):

```
"hidden_size": 2048,        (was 1024)
"intermediate_size": 6144,  (was 3584)
```

Every other field stays byte-identical (head_dim 256, layer_types pattern, linear_* dims, vocab_size 248320, rope_parameters, ...). Task 2 verifies this file field-by-field against the downloaded checkpoint's real config.json — divergences found there get fixed there.

- [ ] **Step 2: Write the failing test**

```bash
# ref/scripts/test_model_select.sh
#!/bin/bash
set -e
PY=ref/.venv/bin/python
# default unchanged
[ "$($PY -c 'import sys; sys.path.insert(0,"ref"); import layer_ref as LR; print(LR.H, LR.FFN, LR.CONV_DIM)')" = "1024 3584 6144" ]
# 2b selected
[ "$(FABLE5_MODEL=2b $PY -c 'import sys; sys.path.insert(0,"ref"); import layer_ref as LR; print(LR.H, LR.FFN, LR.CONV_DIM)')" = "2048 6144 6144" ]
# loader follows
[ "$(FABLE5_MODEL=2b $PY -c 'import sys; sys.path.insert(0,"ref"); import load_qwen35 as LQ; print(LQ.REPO_DIR)')" = "models--Qwen--Qwen3.5-2B" ]
echo MODEL_SELECT_PASS
```

Note CONV_DIM stays 6144 at 2B (it derives from linear_* dims, which don't move).

- [ ] **Step 3: Run it to verify it fails**

Run: `bash ref/scripts/test_model_select.sh`
Expected: FAIL on the second check (H prints 1024 with FABLE5_MODEL=2b).

- [ ] **Step 4: Implement selection**

Create `ref/model_select.py`:

```python
"""Single source of model selection for the whole ref/ chain.
FABLE5_MODEL: '0.8b' (default) or '2b'. Unset == today's behavior, byte-identical."""
import os
_MODELS = {
    "0.8b": ("qwen3_5_0.8b_config.json", "models--Qwen--Qwen3.5-0.8B"),
    "2b":   ("qwen3_5_2b_config.json",   "models--Qwen--Qwen3.5-2B"),
}
TAG = os.environ.get("FABLE5_MODEL", "0.8b")
if TAG not in _MODELS:
    raise SystemExit(f"FABLE5_MODEL={TAG!r} not in {sorted(_MODELS)}")
_cfg, REPO_DIR = _MODELS[TAG]
CONFIG_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), _cfg)
```

In `ref/layer_ref.py` replace the hardcoded open of `qwen3_5_0.8b_config.json` (:21-22) with `from model_select import CONFIG_JSON` and open that. In `ref/load_qwen35.py` replace `REPO_DIR = "models--Qwen--Qwen3.5-0.8B"` (:56) with `from model_select import REPO_DIR` and make `load_config()` (:163-166) open `model_select.CONFIG_JSON`.

- [ ] **Step 5: Run test to verify it passes**

Run: `bash ref/scripts/test_model_select.sh`
Expected: `MODEL_SELECT_PASS`

- [ ] **Step 6: Guard the frozen flows, then commit**

Run the existing selftests that import the touched modules with the var UNSET, all in `ref/.venv`:
`ref/.venv/bin/python ref/w4a8_ref.py && ref/.venv/bin/python ref/layer_fixed.py` (both have `_selftest` mains) — expect their PASS lines, byte-identical behavior.

```bash
git add ref/model_select.py ref/qwen3_5_2b_config.json ref/layer_ref.py ref/load_qwen35.py ref/scripts/test_model_select.sh
git commit -m "ref: FABLE5_MODEL env selects model config (0.8b default, 2b added); geometry already flows from JSON"
```

---

### Task 2: Download the 2B checkpoint + verify feasibility claims (Q0 part 1)

**Files:**
- Create: `evidence/qwen2b/q0/checkpoint_verify.md` (log)
- Test: the verification checks below ARE the test.

**Interfaces:**
- Consumes: Task 1 (`FABLE5_MODEL=2b` loader path).
- Produces: 2B shard in the HF cache on darthplagueis AND snoke; verified `ref/qwen3_5_2b_config.json`.

- [ ] **Step 1: Download on both hosts (background, ~4.55 GB each)**

```bash
python3 -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3.5-2B')"
ssh snoke 'python3 -c "from huggingface_hub import snapshot_download; snapshot_download(\"Qwen/Qwen3.5-2B\")"'
```

(If `huggingface_hub` is missing from a system python3, use `uv run --with huggingface_hub python3 -c ...`.)

- [ ] **Step 2: Verify single shard + config field-by-field**

Locate the snapshot's `config.json` next to the shard and diff its `text_config` against ours:

```bash
FABLE5_MODEL=2b ref/.venv/bin/python - <<'EOF'
import sys, json, os, glob; sys.path.insert(0,'ref')
import load_qwen35 as LQ
shard = LQ.find_checkpoint()
hf = json.load(open(os.path.join(os.path.dirname(shard), 'config.json')))["text_config"]
ours = LQ.load_config()
diff = {k: (ours.get(k), hf.get(k)) for k in set(ours)|set(hf) if ours.get(k) != hf.get(k)}
print("DIFFS:", diff or "none")
assert not diff, diff
EOF
```

Expected: `DIFFS: none`. If the real config differs (e.g. an unexpected field), update `ref/qwen3_5_2b_config.json` to match the checkpoint and re-run Task 1's test.

- [ ] **Step 3: Verify tokenizer byte-identity + loader smoke**

```bash
sha256sum ~/.cache/huggingface/hub/models--Qwen--Qwen3.5-0.8B/snapshots/*/tokenizer.json \
          ~/.cache/huggingface/hub/models--Qwen--Qwen3.5-2B/snapshots/*/tokenizer.json
FABLE5_MODEL=2b ref/.venv/bin/python ref/load_qwen35.py   # module smoke test main
```

Expected: identical tokenizer hashes; loader smoke passes (its 24-layer 18/6 asserts at `load_qwen35.py:354-355` are geometry-independent counts and still hold). If the smoke main hardcodes 0.8B shapes anywhere else, fix it to derive from `layer_ref` constants.

- [ ] **Step 4: Write the evidence log + commit**

`evidence/qwen2b/q0/checkpoint_verify.md`: shard path+size+sha256 of the safetensors HEADER (use `LQ.SafeTensors(...).header_sha`, cheap), config diff = none, tokenizer sha equality, loader smoke output.

```bash
git add evidence/qwen2b/q0/checkpoint_verify.md ref/qwen3_5_2b_config.json
git commit -m "evidence(q0): 2B checkpoint downloaded + verified (config field-exact, tokenizer byte-identical, loader smoke)"
```

---

### Task 3: 2B bf16 golden + torch cross-validation (Q0 part 2)

**Files:**
- Create: `tb/scripts_scratch/golden_bf16_2b.npz` (NOT committed — regenerable cache), `evidence/qwen2b/q0/golden_2b.md`
- Test: `ref/validate_vs_torch.py` under `FABLE5_MODEL=2b`; golden free-run text inspection.

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces: `tb/scripts_scratch/golden_bf16_2b.npz` (per-step argmax + top-64 logits, `fidelity_check.py:151-168` schema) — consumed by Tasks 5-9. bf16 free-run texts for the standard prompts — the study's "native resolution" reference texts.

- [ ] **Step 1: Cross-validate layer_ref at H=2048 vs transformers (cheap, random-init)**

Run on snoke (torch CPU + transformers): `ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm && FABLE5_MODEL=2b python3 ref/validate_vs_torch.py'`
Expected: `VALIDATE_VS_TORCH PASS` (threshold `max_rel_err < 2e-4`, `validate_vs_torch.py:119`). This proves the numpy decode handles the widened geometry before we spend an hour on the real golden. If it FAILS: stop, debug `layer_ref` geometry handling (systematic-debugging skill), do not proceed.

- [ ] **Step 2: Build the real 2B golden**

On darthplagueis (system python3 has torch+transformers, `fidelity_check.py:85-89`):

```bash
FABLE5_MODEL=2b python3 ref/fidelity_check.py --golden --cache tb/scripts_scratch/golden_bf16_2b.npz --ntok 24 --free-ntok 24 2>&1 | tee /tmp/golden_2b.log
```

Expected: cache written; per-prompt bf16 free-run text printed. ~2.5x the 0.8B golden cost — budget tens of minutes.

- [ ] **Step 3: Judge the bf16 text (the gate)**

Read the four prompts' free-run texts in the log. Gate: coherent, on-topic English — this is the "full native resolution" reference the whole study compares against. Paste all four texts into `evidence/qwen2b/q0/golden_2b.md` verbatim with the validate PASS line and cache sha256.

- [ ] **Step 4: Commit**

```bash
git add evidence/qwen2b/q0/golden_2b.md
git commit -m "evidence(q0): 2B bf16 golden built + validate_vs_torch PASS at H=2048; native-resolution reference texts captured"
```

---

### Task 4: Perplexity harness + pinned corpus (Q1)

**Files:**
- Create: `ref/perplexity_eval.py`, `ref/ppl_corpus_eval.txt` (committed, ~24K tokens), `ref/ppl_corpus_calib.txt` (committed, ~32K tokens, disjoint), `ref/scripts/fetch_ppl_corpus.py` (the one-off fetcher, committed for provenance)
- Test: self-check mode `--selftest` + the 0.8B identity run below.

**Interfaces:**
- Consumes: Task 1 (model select), Task 3 pattern (torch import path `transformers.models.qwen3_5`).
- Produces: `perplexity_eval.py` CLI used by Tasks 5-9:
  `FABLE5_MODEL=<tag> python3 ref/perplexity_eval.py --corpus ref/ppl_corpus_eval.txt [--inject SPEC] [--window 512] [--json-out F]`
  `--inject` spec grammar: comma list of `class:quant` pairs, classes from the table in Step 4, quants ∈ {`w4g128`, `w4g64`, `w8g128`, `emb16`}; special spec `all:w4g64` etc.; absent class ⇒ bf16. Prints `PPL <float>` last line; json-out records per-class bit counts + NLL.

- [ ] **Step 1: Fetch + pin the corpus**

```bash
uv run --with huggingface_hub --with pandas --with pyarrow python ref/scripts/fetch_ppl_corpus.py
```

`fetch_ppl_corpus.py` (committed): downloads `Salesforce/wikitext` dataset files `wikitext-2-raw-v1/validation-00000-of-00001.parquet` and `wikitext-2-raw-v1/train-00000-of-00001.parquet` via `hf_hub_download(repo_type="dataset")`, concatenates the text column, tokenizes with `AutoTokenizer` from the LOCAL 2B snapshot (tokenizer byte-identical to 0.8B per Task 2), truncates validation to the first 24,576 tokens and train to the first 32,768 tokens, detokenizes each back to text, writes `ref/ppl_corpus_eval.txt` / `ref/ppl_corpus_calib.txt`, prints both sha256s. Committing the text files is the pin; the fetcher is provenance.

- [ ] **Step 2: Write the failing invocation**

Run: `python3 ref/perplexity_eval.py --corpus ref/ppl_corpus_eval.txt --selftest`
Expected: FAIL — file does not exist yet.

- [ ] **Step 3: Implement `ref/perplexity_eval.py`**

Core design (torch, runs with system python3; NOT ref/.venv):

```python
#!/usr/bin/env python3
"""Windowed teacher-forced perplexity of Qwen3.5 under weight-quantization
injection. Quantizers are the PRODUCTION ones (layer_fixed/w4a8_ref) —
quantize -> dequantize -> load into the HF model -> batched forward.
Measures WEIGHT damage only (float compute); the fixed-point datapath is
scored by fidelity_check.py, tied together by the ablation ladder."""
import sys, os, json, argparse, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, torch
from transformers.models.qwen3_5 import Qwen3_5ForConditionalGeneration  # same family as fidelity_check --golden
import model_select, load_qwen35 as LQ, layer_fixed as LF, w4a8_ref as W

def dequant_w4(Wf, g):
    q = LF.quant_linear(np.asarray(Wf, np.float32), mse_scale=True, g=g)   # layer_fixed.py:511
    w4, m, e, sh = q["w4"], q["m"], q["e"], q["sh"]
    scale = m.astype(np.float32) * (2.0 ** (e - 16))    # reconstruct per-group scale exactly as matvec_y32 applies it
    return (w4.astype(np.float32).reshape(w4.shape[0], -1, q["g"]) * scale[:, :, None]).reshape(Wf.shape)

def dequant_w8(Wf, g):
    w8, m, e, sh = W.quantize_weights8(np.asarray(Wf, np.float32), g=g)    # added in Task 9; Task 4 ships w4+emb16 only
    ...

def dequant_emb16(Wf):
    return np.round(np.asarray(Wf, np.float32) * 256.0).clip(-32768, 32767) / 256.0  # int16 Q7.8, gen_model_script emb path
```

IMPORTANT — Step 3a before trusting `dequant_w4`: verify the scale reconstruction against the production matvec on random data:

```python
# in --selftest: random W (64x256), x int8; assert
# matvec float(dequant_w4(W)) @ dequant_acts(x)  ==  requant-free path of W.matvec_y32(...) within 1e-4 rel
```

If the `m * 2**(e-16)` reconstruction is wrong, read `w4a8_ref.matvec_y32` (:130) and mirror its exact scale application; the selftest is the arbiter — do not guess.

Name→class mapping: derive from `load_qwen35`'s `_EXPECT_COMMON/_EXPECT_MLP/_EXPECT_DN/_EXPECT_ATTN` dicts (`load_qwen35.py:197-212`) — their keys mirror checkpoint tensor names under `model.language_model.`. Classes: `qkv`, `o_proj`, `gate_up`, `down`, `dn_in`, `dn_out`, `dn_conv`, `lm_head`, `emb`. (`dn_conv` and norms/biases quantize per the HW's actual treatment: conv weights stay in their CW_F fixed format — model with `emb16`-style round-trip at Q2.13 only if the ablation flags them; default: leave float, matching what W4A8 covers.)

PPL loop: tokenize corpus with the snapshot tokenizer, split into `--window` (default 512) token segments, batch forward `model(input_ids, labels=input_ids)` per segment in `torch.no_grad()`, accumulate summed NLL over predicted positions, `PPL = exp(total_nll / total_positions)`. Load model `torch_dtype=torch.float32` (float compute is the design point; bf16 compute noise would blur small deltas).

- [ ] **Step 4: Selftest + 0.8B identity + monotonicity check**

```bash
python3 ref/perplexity_eval.py --selftest                                   # dequant-vs-matvec agreement
python3 ref/perplexity_eval.py --corpus ref/ppl_corpus_eval.txt --json-out /tmp/p08_bf16.json           # 0.8B bf16
python3 ref/perplexity_eval.py --corpus ref/ppl_corpus_eval.txt --inject all:w4g128 --json-out /tmp/p08_w4.json
```

Expected: selftest PASS; bf16 PPL finite and plausible (order 10-40 on wikitext for an instruct 0.8B — record, don't assert a magic number); `PPL(w4g128) > PPL(bf16)` (quantization can't help). ~10-20 min/run at 0.8B on CPU: acceptable.

- [ ] **Step 5: 2B bf16 anchor + commit**

```bash
FABLE5_MODEL=2b python3 ref/perplexity_eval.py --corpus ref/ppl_corpus_eval.txt --json-out evidence/qwen2b/q1/ppl_2b_bf16.json
git add ref/perplexity_eval.py ref/scripts/fetch_ppl_corpus.py ref/ppl_corpus_eval.txt ref/ppl_corpus_calib.txt evidence/qwen2b/q1/
git commit -m "ref: perplexity harness (production-quantizer injection into HF model) + pinned wikitext slices; 2B bf16 anchor"
```

---

### Task 5: V1/V2 scoring + the ablation ladder at 2B

**Files:**
- Create: `evidence/qwen2b/q2/v1_v2/` (logs + json)
- Modify: none expected; `ref/fidelity_check.py` only if 2B geometry trips an assumption (see Step 2 note).

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: PPL(V1 w4g128), PPL(V2 w4g64); fidelity table rows for exact / w4deq / full-fixed at 2B; the weight-vs-datapath loss decomposition that decides whether V6 opens.

- [ ] **Step 1: PPL for V1 and V2**

```bash
FABLE5_MODEL=2b python3 ref/perplexity_eval.py --corpus ref/ppl_corpus_eval.txt --inject all:w4g128,emb:emb16 --json-out evidence/qwen2b/q2/v1_v2/ppl_v1.json
FABLE5_MODEL=2b python3 ref/perplexity_eval.py --corpus ref/ppl_corpus_eval.txt --inject all:w4g64,emb:emb16  --json-out evidence/qwen2b/q2/v1_v2/ppl_v2.json
```

(`all:` covers every linear class incl. lm_head; `emb:emb16` models the int16 Q7.8 table.)

- [ ] **Step 2: Fixed-point fidelity + ablation at 2B**

```bash
FABLE5_MODEL=2b python3 ref/fidelity_check.py --golden --cache tb/scripts_scratch/golden_bf16_2b.npz   # no-op if Task 3 cache is valid
FABLE5_MODEL=2b python3 ref/fidelity_check.py --cache tb/scripts_scratch/golden_bf16_2b.npz --ablate --w4-group 128,64 --ntok 24 --free-ntok 24 2>&1 | tee evidence/qwen2b/q2/v1_v2/ablate_2b.log
FABLE5_MODEL=2b python3 ref/fidelity_check.py --cache tb/scripts_scratch/golden_bf16_2b.npz --res-scale 8 --ntok 24 --free-ntok 24 --wire-group 128 --json-out evidence/qwen2b/q2/v1_v2/fixed_g128.json 2>&1 | tee evidence/qwen2b/q2/v1_v2/fixed_g128.log
FABLE5_MODEL=2b python3 ref/fidelity_check.py --cache tb/scripts_scratch/golden_bf16_2b.npz --res-scale 8 --ntok 24 --free-ntok 24 --wire-group 64  --json-out evidence/qwen2b/q2/v1_v2/fixed_g64.json  2>&1 | tee evidence/qwen2b/q2/v1_v2/fixed_g64.log
```

Note: `--res-scale 8` is the 0.8B production value (`fidelity_check.py:66-70`); if the 2B run reports saturations/clips in the SUMMARY, sweep `--res-scale 4,8,16` and record — res_scale is a per-model calibration, expected to need re-derivation. Budget ~25-30 min per fixed config at 2B (0.8B measured 587.6 s, evidence/stage5/fidelity_mq15_prod.log). If `FxRunner` trips a 2B geometry assumption (crash/assert), fix it minimally in `layer_fixed.py`/`fidelity_check.py` — geometry must come from `layer_ref` constants — and re-run the Task 1 frozen-flow guard afterward.

- [ ] **Step 3: The decomposition table**

Write `evidence/qwen2b/q2/v1_v2/DECOMP.md`: rows = {exact-float, w4deq-g128-float, w4deq-g64-float, fixed-g128, fixed-g64}; columns = {top1/24, rank med, rank max, free-run text verdict, PPL where applicable}. The key derived numbers: (w4deq − exact) = weight damage; (fixed − w4deq) = datapath damage. State which dominates at 2B in one sentence. **Decision recorded here: V6 axis opens iff datapath damage > weight damage on both the fidelity metrics and text quality.** If it opens, that is a plan amendment: add a V6 modeling task (the `docs/FIDELITY_REDESIGN.md` Phase-1B menu — S_F width, block-floating DN output, wider scratch — swept via `fidelity_check --diag` configs at 2B) before Task 10, and tell the user at that moment, not at gate D. (Compare against the 0.8B baseline decomposition: exact 24/24 → w4deq 12/24 → fixed 0/24 pre-redesign, `docs/FIDELITY_REDESIGN.md`; post-redesign production = 15-16/24.)

- [ ] **Step 4: Commit**

```bash
git add evidence/qwen2b/q2/v1_v2/
git commit -m "evidence(q2): V1/V2 PPL + fidelity + ablation decomposition at 2B; V6 axis decision recorded"
```

---

### Task 6: audit_ranges at 2B

**Files:**
- Create: `ref/audit_ranges_2b_report.md` (committed, like the 0.8B one), `evidence/qwen2b/q2/audit/audit_log.txt`

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces: per-container saturation facts at 2B for the study doc's risk column.

- [ ] **Step 1: Run it (numpy-only, ref/.venv)**

```bash
FABLE5_MODEL=2b ref/.venv/bin/python ref/audit_ranges.py -o ref/audit_ranges_2b_report.md 2>&1 | tee evidence/qwen2b/q2/audit/audit_log.txt
```

- [ ] **Step 2: Diff against the 0.8B report**

Read `ref/audit_ranges_2b_report.md` vs `ref/audit_ranges_report.md`. The 0.8B's three documented saturations are per-weight facts — list what changed (new saturating containers, changed margins) in a short section appended to the 2B report. Any NEW hard saturation (scratch ±32767, Av Q3.15, conv CW_F) is a finding for the study doc's V1/V2 risk column, not something to fix silently.

- [ ] **Step 3: Commit**

```bash
git add ref/audit_ranges_2b_report.md evidence/qwen2b/q2/audit/
git commit -m "evidence(q2): audit_ranges at 2B — saturation deltas vs 0.8B recorded"
```

---

### Task 7: Per-tensor-class sensitivity scan (feeds V4)

**Files:**
- Create: `ref/scripts/sensitivity_scan.sh`, `evidence/qwen2b/q2/sensitivity/{scan_*.json, SENSITIVITY.md}`

**Interfaces:**
- Consumes: Task 4 CLI.
- Produces: ranked list of tensor classes by PPL damage — the V4 mixed-precision map (`evidence/qwen2b/q2/sensitivity/SENSITIVITY.md`, table `class | params | PPL | ΔPPL vs bf16`).

- [ ] **Step 1: The scan script**

```bash
# ref/scripts/sensitivity_scan.sh — one class W4 g64 at a time, rest bf16
set -e
for cls in qkv o_proj gate_up down dn_in dn_out lm_head emb; do
  q=w4g64; [ "$cls" = emb ] && q=emb16
  FABLE5_MODEL=2b python3 ref/perplexity_eval.py --corpus ref/ppl_corpus_eval.txt \
    --inject "$cls:$q" --json-out "evidence/qwen2b/q2/sensitivity/scan_$cls.json" &
done
wait
```

Run classes in parallel across hobby servers if darthplagueis is saturated (each run is independent; NFS-shared repo, per-machine HF cache required first). 8 runs x ~30-45 min at 2B.

- [ ] **Step 2: Rank + write SENSITIVITY.md**

Table sorted by ΔPPL descending, param count per class (from tensor shapes), and the derived V4 candidate maps: "W8 on top-1 class", "top-2", "top-3" with their bytes/token cost (computed in Task 9). One paragraph: does the ranking match the arXiv 2505.02214 expectation (down_proj / output projections most sensitive)?

- [ ] **Step 3: Commit**

```bash
git add ref/scripts/sensitivity_scan.sh evidence/qwen2b/q2/sensitivity/
git commit -m "evidence(q2): per-class W4 sensitivity scan at 2B — V4 mixed map ranked"
```

---

### Task 8: V3 — salience-weighted quantizer (wire-format-compatible)

**Files:**
- Create: `ref/calib_stats.py` (activation-salience collector), `ref/calib_stats_2b.npz` (NOT committed — regenerable, sha in evidence), `evidence/qwen2b/q2/v3/`
- Modify: `ref/layer_fixed.py:541` (`quant_linear_mse` grows an optional `salience=None` arg), `ref/layer_fixed.py:585` (`quant_linear` passes it through)
- Test: extend `layer_fixed._selftest` invariance check (Step 3).

**Interfaces:**
- Consumes: Task 4 (`--inject` grows `w4g64s` quant using the salience file via `--calib-stats ref/calib_stats_2b.npz`), calib corpus.
- Produces: PPL(V3) + fidelity spot-check; verdict on whether a smarter quantizer earns its complexity. GPTQ-lite is EXPLICITLY conditional (Step 5).

- [ ] **Step 1: Collect per-input-channel salience**

`ref/calib_stats.py`: torch forward hooks on every Linear in the HF 2B model, accumulate `mean |x|` per input channel over `ref/ppl_corpus_calib.txt` (the train-side slice — NEVER the eval slice), save `{tensor_name: float32[K]}` to npz.

```bash
FABLE5_MODEL=2b python3 ref/calib_stats.py --corpus ref/ppl_corpus_calib.txt --out ref/calib_stats_2b.npz
```

- [ ] **Step 2: Salience-weighted MSE in the production quantizer**

In `quant_linear_mse(Wf, nalpha=17, amin=0.55, g=G, salience=None)`: the existing loop scores candidate scales by sum of squared weight error per group; with `salience` given, weight each column's squared error by `salience[k]^2` (error on channels that see big activations costs more). ~5 lines inside the existing scale-search loop; wire format untouched (`w4/m/e/sh` shapes identical).

- [ ] **Step 3: Invariance test first**

Add to `layer_fixed._selftest`: `quant_linear(W, g=64)` output dict must be bit-identical with `salience=None` vs the arg absent (regression guard for every frozen flow), and `salience=ones(K)` must equal `salience=None` (uniform salience = plain MSE). Run: `ref/.venv/bin/python ref/layer_fixed.py` → PASS lines. Run BEFORE wiring salience into any production path.

- [ ] **Step 4: Score V3**

```bash
FABLE5_MODEL=2b python3 ref/perplexity_eval.py --corpus ref/ppl_corpus_eval.txt --inject all:w4g64s,emb:emb16 --calib-stats ref/calib_stats_2b.npz --json-out evidence/qwen2b/q2/v3/ppl_v3.json
FABLE5_MODEL=2b python3 ref/fidelity_check.py --cache tb/scripts_scratch/golden_bf16_2b.npz --res-scale <winner from Task 5> --wire-group 64 --ntok 24 --free-ntok 24 --json-out evidence/qwen2b/q2/v3/fixed_v3.json
```

(The fidelity run needs the salience-aware quantizer active in the FxRunner path — plumb a `FABLE5_CALIB_STATS` env read in `layer_fixed` for this run, default-off.)

- [ ] **Step 5: Conditional close-out + commit**

Decision rule (record in `evidence/qwen2b/q2/v3/V3.md`): if V3's PPL recovers < 25% of the (V2 − bf16) gap, GPTQ-lite is NOT pursued (diminishing returns, adds error-feedback complexity) — write the number and stop. If ≥ 25%, add one follow-up task for GPTQ-lite to this plan before executing further (plan-amendment, requires user ack at gate D anyway).

```bash
git add ref/calib_stats.py ref/layer_fixed.py evidence/qwen2b/q2/v3/
git commit -m "ref+evidence(q2): V3 salience-weighted MSE quantizer (wire-compatible) scored; GPTQ-lite decision recorded"
```

---

### Task 9: V4/V5 — W8 modeling + bytes/token calculator

**Files:**
- Create: `ref/scripts/bytes_per_token.py`, `evidence/qwen2b/q2/v4_v5/`
- Modify: `ref/w4a8_ref.py` (add `quantize_weights8(W, g=G)` next to `quantize_weights` :94), `ref/perplexity_eval.py` (enable `w8g128` inject)
- Test: `w4a8_ref` selftest extension + calculator validation against two known feasibility numbers.

**Interfaces:**
- Consumes: Task 7's sensitivity ranking (defines V4's W8 class set).
- Produces: PPL(V4 top-1/2/3 maps), PPL(V5); `bytes_per_token.py --model 2b --map <spec>` → exact bytes/token per variant — the throughput column's input. W8 wire-format sketch text for the study doc.

- [ ] **Step 1: `quantize_weights8` with selftest**

Mirror of `quantize_weights` (`w4a8_ref.py:94`): int8 range [-127,127] (symmetric, avoid -128 asymmetry), per-group scale `max|W_g|/127`, same `(m uint16, e, sh)` scale encoding so `dequant` reconstruction reuses Task 4's verified formula. Extend `_selftest` (:236): round-trip `|dequant(quantize_weights8(W)) - W|` must beat the W4 round-trip error on the same matrix by >4x (sanity that 8 bits behave like 8 bits). Run: `ref/.venv/bin/python ref/w4a8_ref.py` → PASS.

- [ ] **Step 2: Score V5 and the V4 ladder**

```bash
FABLE5_MODEL=2b python3 ref/perplexity_eval.py --corpus ref/ppl_corpus_eval.txt --inject all:w8g128,emb:emb16 --json-out evidence/qwen2b/q2/v4_v5/ppl_v5.json
# V4: top-k sensitive classes W8, rest W4 g64 — e.g. if Task 7 ranks down,dn_out top-2:
FABLE5_MODEL=2b python3 ref/perplexity_eval.py --corpus ref/ppl_corpus_eval.txt --inject "all:w4g64,down:w8g128,dn_out:w8g128,emb:emb16" --json-out evidence/qwen2b/q2/v4_v5/ppl_v4_top2.json
```

Run top-1, top-2, top-3 maps (three runs) so gate D sees the mixed-precision curve, not one point.

- [ ] **Step 3: bytes/token calculator, validated**

`ref/scripts/bytes_per_token.py`: from the model config (via `model_select`) + a precision map, compute per-token DDR weight traffic using `w4a8_ref.row_stride(K, g)` for W4 rows and the W8 analog (1 byte/weight, 64/beat + scale beats), summed over the 187-image structure (walk the same shape inventory `gen_layer_script` uses); plus emb row bytes. **Validation gate (hard assert in the script's `--selftest`):** 0.8B W4 g128 = 417,435,648 and 2B W4 g128 = 996,282,368 (both from the feasibility study's self-validated arithmetic). Then emit the table for: V1, V2, V3(=V2 bytes), V4 top-1/2/3, V5 + DDR-fit check against the 1,280 MiB weight window and emb region (fit facts from `sw/hwmap.py` constants — see Track R plan; if V5 exceeds a window, say so, don't silently re-map).

- [ ] **Step 4: W8 wire-format sketch (text only)**

One section in `evidence/qwen2b/q2/v4_v5/W8_SKETCH.md`: beat layout (64 weights/beat vs W4's 128), scale-beat cadence, `SHAPE` word encoding option (one spare bit? — cite the actual bit inventory from `sw/hwmap.py shape_word`, cross-checked in the Track R plan's facts), engine changes in one paragraph (nibble unpack → byte path, accumulator width check), and the explicit statement that RTL exists only if gate D picks V4/V5.

- [ ] **Step 5: Commit**

```bash
git add ref/w4a8_ref.py ref/perplexity_eval.py ref/scripts/bytes_per_token.py evidence/qwen2b/q2/v4_v5/
git commit -m "ref+evidence(q2): W8 quantizer modeled, V4 curve + V5 scored, bytes/token calculator validated against feasibility"
```

---

### Task 10: The study doc + decision table (gate D input)

**Files:**
- Create: `docs/QWEN2B_QUANT_STUDY.md`
- Modify: `docs/QWEN2B_FEASIBILITY.md` (one line at top: "superseded on perf/fidelity numbers by QWEN2B_QUANT_STUDY.md")

**Interfaces:**
- Consumes: every prior task's evidence + Track R-a's re-normalized mover per-row costs (cross-plan; if absent, use the feasibility 11-14 ms band and mark the column U).
- Produces: the gate-D decision table. THE study deliverable.

- [ ] **Step 1: Assemble the decision table**

Columns per variant (V1, V2, V3, V4×{top1,top2,top3}, V5): PPL (Δ vs bf16 2B anchor, absolute + %), fidelity top1/rank (where measured), free-run text verdict (quote one line), bytes/token, modeled tok/s (bandwidth model: measured sustained DDR BW from the 0.8B census + geometry-invariant layer costs + mover band), DDR fit, RTL delta (none / W8 engine mode), timing risk note. Include the 0.8B production row as the familiar reference point.

- [ ] **Step 2: Write the narrative sections**

(a) the ablation decomposition — weight vs datapath damage at 2B, V6 verdict with numbers; (b) sensitivity ranking + how the V4 maps were chosen; (c) W8 wire sketch (from Task 9); (d) risks per variant (audit_ranges findings, res_scale calibration); (e) a one-paragraph recommendation with the two runner-ups named. Every number cites its evidence file path.

- [ ] **Step 3: Self-check + commit**

Check: every variant row's numbers traceable to a committed json/log under `evidence/qwen2b/q2/`; no U-marked cell without a named closing action; recommendation consistent with the table.

```bash
git add docs/QWEN2B_QUANT_STUDY.md docs/QWEN2B_FEASIBILITY.md
git commit -m "docs: Qwen3.5-2B quantization study — decision table for gate D"
```

- [ ] **Step 4: Present gate D**

Combine with Track R's status (timing/utilization facts from R-b if landed) into the one-page decision summary for the user. STOP — the user picks the operating point. The post-D plan (R-c/R-d ± W8 engine mode) is written only after this pick.
