# CHAT TEMPLATE GATE — the FPGA becomes an assistant (2026-08-11)

Spec: docs/INSTRUCT_SPEC.md (frozen + T3 amendment). Investigation
finding that reshaped the project: the cached/board checkpoint IS
Qwen/Qwen3.5-0.8B (instruct) — snapshot 2fc06364, weights blob sha256
04b1c301...4696, proven cryptographically and behaviorally; the Base
was never downloaded; the 16/24 fidelity baseline was always the
instruct's. The fix was HOST-SIDE ONLY: id-spliced chat template.
Board: build_032 (0c991953), untouched. Zero RTL, zero artifacts.

## The before/after (same silicon, same weights, same question)

BEFORE (--raw): "What is the capital of France?" ->
  "\nA. Paris\nB. London\nC. Berlin\nD. Tokyo\n\n<think>\nThe user is
  asking for..." — a quiz continuation, never answers, never stops.
AFTER (template): -> "The capital of France is **Paris**." then EOS.
  Turn 2 "And of Italy?" -> "The capital of Italy is **Rome**." (CLI
  session, in-chip context carry). before_raw.log / after_templated_*.

## Gates (all PASS)

- G1 selftests: chat_seq 175/175 (was 142), serve 50/50 (was 24):
  wrapper == the HF apply_chat_template reference (19/19 ids single
  turn; 3-message incremental == HF_REF_3MSG_INCR, and minus the 4
  retained think ids per turn == HF_REF_3MSG byte-for-byte); BpeTok
  special-token mangling pinned as a test; overhead = 5*M+7 (+4*(k-1)).
- G2 model-only (board-free): templated ids == HF reference; first 6
  tokens == bf16 golden exactly ("The capital of France is **");
  seq_model self-consistent x2.
- G3 HW: templated 3-question session x2 runs — token ids IDENTICAL
  (repeatability); 2-turn lockstep --verify 54/54 steps "== seq_model",
  0 mismatches (verify_2turn_clean.log); first 9 HW tokens == bf16
  before quantization divergence (consistent with 16/24 fidelity).
- API: serve.py templated session with per-session carry over SSE;
  turn 1 Paris correct. HONEST datum: turn 2 answered "Milan" — the
  turn-1 reply had been cut at max_tokens=12 mid-sentence (no EOS), and
  the 0.8B W4 model answers follow-ups worse from ragged context. The
  CLI session (EOS-terminated turn 1) said Rome. Plumbing correct;
  model quality is what it is. Practical guidance: let replies reach
  EOS (ntok >= ~24) for best multi-turn behavior.
- Exclusivity battle-tested in passing: a collided relaunch was
  refused by the flock with the holder pid named (spec-10 working).

## Measured (build_032 burst path, templated turns)

prefill-lite 45.0 ms/step, decode 63.2 ms/step, ~2 s for a 9-token
EOS-terminated answer. Template overhead 12 ids first turn, ~13-17
with system message; 500-token context comfortably holds multi-turn.

## What shipped (sw/ only)

chat_seq.py: ChatTemplate id-splicer (pure class), template ON by
default, --raw opt-out, --system, incremental-with-carry multi-turn,
control-id stripping in display, T7 budget line, +33 selftests, and a
pre-existing stats units bug fixed (97167% -> 97%). serve.py: template
in BoardBackend.encode, "raw"/"system" request fields, template
telemetry in start/stats/sessions. infer.py: EOS stop in generate()
(had none), optional --chat, byte-identical default behavior.

## Follow-ons (logged)

Provenance: record weights BLOB sha256 in future evidence (header sha
cannot distinguish Base/Instruct). g64 evidence contradiction
(STAGE5_G64_GATE prose vs gen_model_script comment; the wire-exact
attempt crashed at w4a8_ref.py:161) — unresolved, flagged. audit_ranges
-o default overwrites the committed baseline; its PASS lines print
pre-clamp maxima. Flock retrofit into infer/seq_run/tok_meter still
pending. serve could default max_tokens higher so replies reach EOS.
