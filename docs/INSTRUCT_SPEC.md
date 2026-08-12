# CHAT TEMPLATE — FROZEN SPEC (2026-08-11)

Supersedes docs/INSTRUCT_SWAP_PLAN.md phases 0-2: the investigation
PROVED the cached/board checkpoint IS Qwen/Qwen3.5-0.8B (instruct) —
snapshot 2fc06364, weights blob sha256 04b1c301...4696; the Base was
never downloaded; the 16/24 fidelity baseline is the instruct's own.
The degenerate chat behavior is solely the missing chat template.
Scope = host-side only. Board stays build_032 (0c991953). No new
artifacts; model_v2 remains the frozen stream template.

## Frozen decisions

T1 ID-SPLICED WRAPPER, never string-encoded (BpeTok cannot encode
   added tokens: '<|im_start|>' string-encodes to 6 garbage ids).
   Canonical single-turn form (verified == HF, 19/19 ids):
   [248045]+enc("user\n")+enc(body)+[248046]+enc("\n")
   +[248045]+enc("assistant\n")+[248068]+enc("\n\n")+[248069]+enc("\n\n")
   Special ids: im_start 248045, im_end 248046, think 248068,
   /think 248069, endoftext 248044. All are in the emb table
   (vocab_size 248,320 fully mapped at EMB_BASE).
T2 THINKING MODE: closed-empty think block (template default, 7 ids).
   Never enable_thinking=True (would burn the 500-token context).
T3 MULTI-TURN = INCREMENTAL WITH CARRY (in-chip KV preserved; NO full
   replay). Turn k>1 feed = [carry = last generated token, normally
   im_end] + enc("\n") + user wrapper + body + [248046] + enc("\n")
   + assistant wrapper + think block. Invariant: the concatenation of
   all fed tokens across turns MUST equal the HF-rendered full
   conversation ids — that equality IS the correctness definition and
   the gate (checked in --selftest against a 3-message reference
   rendering, and in --model-only/--verify lockstep).
T4 DEFAULT ON; --raw opts out (raw = today's behavior). The flag is
   --raw; do NOT overload --template (taken: SEQ artifact prefix).
T5 SYSTEM PROMPT: none by default; --system "<text>" adds the system
   message wrapper (+5 ids + text) at session start (turn-1 only).
T6 EOS: generation stops on {248044, 248046} (already derived
   content-based in chat_seq; keep the derivation, keep the selftest
   pin). sw/infer.py gains the same stop-id check in generate()
   (today it has NONE and runs past im_end).
T7 CONTEXT BUDGET: wrapper overhead = 5 x messages + 7 ids; the
   context guard accounts for it (T + feed + ntok < max_ctx as today —
   feed now includes wrapper ids; nothing new needed beyond honest
   stats display of template overhead).
T8 serve.py: template applied in BoardBackend.encode path (serve does
   NOT call run_turn — it reimplements the loop); per-session multi-
   turn follows T3; /v1/generate gains "raw": bool (default false).
T9 NO generator/ref changes; NO model_v3; NO re-pin of TEMPLATE_SHA256.
T10 PROVENANCE (follow-on note, this commit's docs only): future
   evidence records the weights BLOB sha256 (04b1c301...) — the
   safetensors header sha CANNOT distinguish Base from Instruct.

## File ownership (one Opus implementation agent)

sw/chat_seq.py (wrapper builder + --raw/--system + EOS display + carry
logic per T3 + selftests extended with the HF-reference id equality),
sw/serve.py (encode path + raw flag + selftest), sw/infer.py (EOS stop
in generate() + optional --chat flag using the same wrapper builder —
import from chat_seq, do not duplicate). Nothing else.

## T3 amendment (RATIFIED 2026-08-11, integrator ruling)

The Qwen template strips think blocks from HISTORICAL assistant
messages; incremental-with-carry necessarily keeps the 4 think ids each
generated turn fed into the KV. ACCEPTED: the invariant becomes fed
stream == HF_REF_*_INCR (the incremental rendering), with the checked
side condition that deleting the 4 retained ids per past turn
reproduces the canonical HF rendering byte-for-byte. Cost: 4 context
ids per past turn. Exact-replay mode rejected (seconds of re-prefill
per turn). Budget identity: fed + generated im_end = 5*M+7 + 4*(k-1).

## Gates

G1 --selftest: wrapper ids == the HF 19-id reference; 3-message
   incremental concatenation == full HF rendering; overhead formula.
G2 --model-only (board-free): one templated turn through seq_model —
   tokens equal the reference model's greedy continuation of the
   templated ids (generate the expectation with the local HF model,
   record it in the test).
G3 HW (integrator): templated live run — canned question x2 runs
   token-identical; 2-turn incremental session lockstep --verify;
   BEFORE/AFTER transcripts (raw vs templated, same questions)
   captured to evidence/instruct/ — the qualitative point of the
   whole project. serve.py API one templated session via chat_client.
