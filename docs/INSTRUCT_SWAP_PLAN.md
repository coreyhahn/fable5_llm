# Qwen3.5-0.8B-Instruct swap (plan, 2026-08-11) — quality at 15 tok/s

Goal: replace the Base checkpoint with Qwen/Qwen3.5-0.8B (the instruct
variant, same architecture per HF docs) so the box behaves like an
assistant instead of a text-completer. ZERO RTL expected: board stays
build_032 (0c991953). This is a reference/artifact/host project, the
same shape as the fidelity campaign: harness-gated, evidence-committed.

## What actually changes (and what doesn't)

- DOESN'T: RTL, ISA, wire format, stream grammar, TurnCompiler logic,
  serve.py/chat_client, board bitstream.
- DOES: the checkpoint -> new quantized weight/emb images + a NEW
  artifact set ("model_v3": .txt/.seq/.seqdata/const blob) because the
  const blob and per-layer ARG immediates bake in weight-derived
  quantization scales (m_q15, k_a schedules, norms). Chat stack points
  at the new prefix (chat_seq --template / TEMPLATE_PREFIX).
- DOES: host-side chat template (Qwen im_start/im_end format) applied
  at encode time in chat_seq/serve/infer; stop-token handling already
  derives from tokenizer added_tokens — verify ids match the instruct
  tokenizer.
- WATCH: the instruct model ships a VISION ENCODER — load_qwen35.py key
  mapping must select the text decoder (possible key-prefix shift) and
  ignore vision weights. Tokenizer/embedding table may differ in detail.

## Phases

0. INVESTIGATION (Opus, read-only + snoke-safe downloads): checkpoint
   download/cache on darthplagueis + snoke; config identity diff vs
   ref/qwen3_5_0.8b_config.json (layer types, dims, rope_theta, eps,
   vocab, tied embeddings); safetensors key map incl. vision prefix;
   tokenizer identity (merges sha, added/special tokens, chat template
   string, stop ids); which artifacts are weight-dependent (confirm
   const-blob/ARG scale baking); disk budget; fidelity-harness
   readiness for instruct (fidelity_check.py golden path).
1. QUANT + FIDELITY (Agent A, ref/): load_qwen35 instruct support ->
   range audit (audit_ranges) vs frozen formats -> quantize ->
   fidelity_check vs torch bf16 golden (report N/24 vs the Base 16/24
   baseline; g128 vs g64 sweep; --res-scale/--allow-clip decisions on
   evidence, not vibes).
2. ARTIFACTS (Agent B, ref/ generators): model_v3 prompt set (chatty
   prompts through the REAL chat template), gen_model_script + SEQ
   emission -> model_v3_s1.e artifact set + weights manifest; gates:
   seq_model bit-exact vs layer_fixed reference on 4 prompts; hashes.
3. HOST (Agent C, sw/): chat template encode path in chat_seq.py
   (+ --template default flip), serve.py passthrough, infer.py --model;
   stop ids verified; selftests extended; NO stream-logic changes.
4. INTEGRATION (me): tb_seq_chip one launch on a model_v3 stream (RTL
   unchanged but cheap insurance), HW: seq_run model_v3 x2 bit-exact,
   chat_seq canned-v3 + 4 live prompts x2 runs vs seq_model, LIVE
   TRANSCRIPTS (the actual point — qualitative before/after vs Base),
   evidence/instruct/INSTRUCT_GATE.md, ladder/NEXT_SESSION, commits.

## Success criteria

- Fidelity: instruct N/24 within the W4 ceiling story (report honestly;
  if instruct quantizes worse than Base, the g64/format levers get one
  pass before we accept a number).
- HW: tokens bit-exact vs seq_model on every gated prompt; repeatable.
- UX: the live transcript answers questions directly (no Q:/A: tricks),
  stops at EOS, multi-turn follows context — judged and recorded.
- Context: chat template overhead fits the 500-token budget (template
  tokens counted in the gate doc).
