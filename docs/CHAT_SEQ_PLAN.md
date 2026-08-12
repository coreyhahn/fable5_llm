# Fast interactive chat on the sequencer -> API serving (plan, 2026-08-09)

Goal: chat at sequencer speed instead of host-MMIO speed, then expose it
as an API. Today: infer.py = 9.3 s/token (98.8% MMIO overhead);
sequencer = 156.2 ms/token device (6.40 tok/s, build_031). Target UX:
streamed tokens at ~6 tok/s, turn latency ~= 0.12 s x prompt_tokens +
0.16 s x reply_tokens (20-tok prompt + 50-tok reply ~= 10 s vs ~650 s
today). ZERO RTL expected — bitstream 4d71adcc untouched; any ISA gap
found in phase 0 becomes a separate build-cycle rung.

## Why this is a stream-compiler problem, not an RTL problem

The ISA (docs/SEQ_ISA.md v1.5) already contains the chat machinery:
- EMB embeds token from XRF[3], "written by AMAXL or BY HOST (prompt
  feed)" — a prefill step is [CSRWR XRF[3]=prompt_id] + generic step
  body; a decode step is [AMAXL] + the SAME body.
- AMAXL pushes each decoded token to the OUT FIFO CSR -> host polls it
  WHILE the loop runs = live token streaming, no RTL.
- JMP flags=1 decrements TCNT_SEQ and loops -> reply length is one
  CSR write per turn.
- T/position comes from layer_chan's auto-incrementing TCNT banks (T
  records only RESET) -> step bodies should be position-generic, i.e.
  byte-reusable templates. model_v2_s1.e's own structure (6 forward
  steps, only 4 distinct step bodies, loop_steps=3) says the decode
  body already re-executes unmodified.
- Weights/LM head/embedding stay resident in DDR across turns; KV/DN
  state + TCNT persist in-chip across streams (no reprogram, no reset
  records) — multi-turn context is free until T hits the KV depth.

So a chat turn = concatenate cached byte templates (session preamble
once; per turn: k x [XRF3-patch + prefill body] + [TCNT_SEQ=n] +
decode loop), DMA ~1-3 MB, write SEQ go, poll OUT FIFO. Compile time
is numpy patching: milliseconds.

## Phase 0 — investigation (read-only agent, then freeze CHAT_SEQ_SPEC)

1. Byte-diff the 4 step bodies in tb/scripts/w4/model_v2_s1.e.seq:
   enumerate EVERY field that differs (expected: only the XRF[3]
   CSRWR / AMAXL prologue, maybe scratch staging parity). Each diff =
   a template hole; anything T-dependent = template killer -> flag.
2. Confirm from seq_unit.sv + seq_run.py: OUT FIFO CSR semantics
   (depth, overflow, read side effects) for live polling; TCNT_SEQ
   write path; what seq_run's "tokens:" actually reads.
3. Confirm the preamble split: which records are session-once (LDC
   const blob, conv weights, dnz, T resets) vs per-turn; verify a
   second stream launch WITHOUT resets continues context (T, KV, DN)
   — first on seq_model, then tb_seq_chip, then HW.
4. Confirm SeqEmitter can emit the templates without running the
   fixed-point reference (emit-only mode), or that we snapshot the
   committed .seq bytes as the template source (preferred: templates
   ARE slices of the gated artifact — provenance for free).
5. EOS/abort: is there a clean host-side sequencer stop (for early
   EOS)? v1 ships without it (over-generating 20 tokens costs ~3 s).

## Phase 1 — turn compiler (ref/, Opus agent A)

ref/seq_chat.py: TurnCompiler class.
- build_session(): preamble stream bytes + const blob (from template
  source), session state {T, history}.
- build_turn(prompt_ids, ntok): patched stream bytes; asserts
  T + len(prompt) + ntok < KV_DEPTH-slack.
- Gate 1 (bit-exact anchor): compiling the model_v2_s1 prompt schedule
  MUST reproduce model_v2_s1.e.seq byte-identically (or record-
  equivalently, whitelisted holes only).
- Gate 2: seq_model executes session+turn streams for 4 fresh prompts;
  tokens must equal ref/layer_fixed.py greedy decode exactly.
- Gate 3: tb_seq_chip (real RTL, snoke) on one 2-turn session stream:
  turn 2 continues turn 1's context bit-exactly.

## Phase 2 — interactive client (sw/, Opus agent B)

sw/chat_seq.py (new; infer.py stays as the host-driven reference):
- Session: CSR sanity (VERSION 0x4D71ADCC, CALIB), upload weights/emb
  from the cached model_v2 images + manifest (skip if resident:
  sha-probe a witness block), run preamble.
- Turn loop: BPE-encode (reuse infer.py's tokenizer + Q:/A: chat
  template), compile turn, DMA stream, launch, poll OUT FIFO ->
  stream tokens to stdout as they decode (~6/s), detokenize
  incrementally, stop display at EOS.
- Context: mirror T; --max-ctx like infer.py; on overflow, auto-reset
  session + re-prefill the (truncated) history.
- --verify mode: same prompt through infer.py's host-driven path;
  token sequences must be IDENTICAL (this is the cross-driver gate).
- HW gate: 4 prompts x 2 runs, token-identical to seq_model + to the
  --verify path; plus the canned model_v2 prompt reproducing its
  committed golden tokens. Wall-clock report per phase (compile/DMA/
  prefill/decode). Evidence -> evidence/chat/.

## Phase 3 — API (sw/, Opus agent C, after phase 2 gates)

sw/serve.py on snoke (uv venv, FastAPI + uvicorn):
- POST /v1/generate {prompt, max_tokens, session_id?} -> SSE token
  stream; GET /v1/health (CSR sanity + VERSION); GET /v1/metrics
  (tok/s, device ms, context fill, uptime).
- The board is ONE context: single worker, FIFO request queue,
  sessions = named histories replayed on switch (re-prefill); honest
  409/queue-position for concurrent callers.
- Bind 127.0.0.1 only (lab tool; access via ssh tunnel). No auth in
  v1 — do not expose beyond localhost.
- Client: sw/chat_client.py (readline + SSE) so chat_seq.py logic and
  serving share the TurnCompiler/session code path.
- Gate: API tokens identical to chat_seq.py for the same prompts;
  2-client queueing test; kill/restart recovers (weights resident,
  session replay).

## Risks / open questions

- Step bodies not fully generic (some T- or step-parity-dependent
  field): plan B is per-turn body emission with per-step patch tables
  — still milliseconds, just more holes. Only an ISA-level gap (none
  expected after the phase-0 reading) would force RTL.
- OUT FIFO overflow if host lags: FIFO depth from phase 0; poll rate
  6 Hz vs depth makes this unlikely; drain-before-launch rule.
- KV depth 512 => ~500-token sessions before auto-reset+replay; fine
  for chat, documented for the API.
- Prefill device time assumed ~0.12 s/token (full pass minus LM head)
  — measure in phase 2, report honestly.
- Concurrency: exactly one stream may own the sequencer; the API
  queue enforces it (and chat_seq.py takes a lockfile on the device).

## Workflow

Same frozen-contract multi-agent pattern as rung 2: phase-0
investigation agent -> freeze docs/CHAT_SEQ_SPEC.md -> agents A/B/C on
disjoint files (A ref/seq_chat.py, B sw/chat_seq.py, C sw/serve.py +
client) -> integration + HW gates + evidence/chat/ in the main
session. Commit at every green gate. Phases 1-2 land "fast chat";
phase 3 lands the API.
