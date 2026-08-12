# CHAT-SEQ — FROZEN SPEC (2026-08-09): fast interactive chat on the sequencer

Phase-0 investigation (agent report, 2026-08-09) validated docs/
CHAT_SEQ_PLAN.md with field-level evidence. ZERO RTL: bitstream stays
build_031 (4d71adcc). Template source is the gated artifact
tb/scripts/w4/model_v2_s1.e.seq (60,495 records, sha a69864d2...).

## Architecture (frozen decisions)

1. TEMPLATE SOURCE = byte slices of the committed .e.seq. Emit-only
   SeqEmitter mode REJECTED (emitter is welded to the fixed-point
   reference run; slicing is complete because NOTHING in a step body is
   data- or position-dependent — proven by the 0-record body diff).
2. ONE BODY TEMPLATE. All four step bodies are byte-identical:
   - T_PREAMBLE  = recs [0,1524)      session-once (conv/dnz/L_LAYER/
                                      6x L_TCNT=0 resets)
   - T_SEED_TOK  = rec 1524           hole: imm32@+4 = token id
                                      (CSRWR 0x204C -> XRF[3])
   - T_SEED_POS  = rec 1525           hole: imm32@+4 = pos*1536
                                      (CSRWR 0x2050 -> XRF[4], ABSOLUTE)
   - T_BODY_FULL = recs [1526,16266)  14,740 recs, EMB..AMAXL
   - T_BODY_LITE = recs [1526,15532)  14,006 recs, LM head + AMAXL cut
                                      (suffix starts at body offset
                                      14006 = MOVX XWIN<=scratch[0x800])
   - T_TCNT / T_POSADV / T_JMP / T_HALT = recs 45751 / 60492 / 60493 /
     60494 (holes: TCNT imm32 = n, JMP imm32 = loop-head index)
3. PREFILL-LITE ADOPTED: steps 0..P-2 use T_BODY_LITE (saves ~11%/step;
   OUT FIFO carries reply tokens only; AMAX am_g self-resets via
   ARG2[0]=1 on the first LM chunk — no cross-stream state).
4. LAUNCH GRANULARITY = ONE LAUNCH PER FORWARD STEP from two
   DDR-resident stream images (lite/full). Per launch: patch 48 B
   (seed records: XRF[4]=pos*1536, XRF[3]=tok, TCNT_SEQ) + START.
   This (a) eliminates the OUT FIFO of_cnt race (pop only while
   halted), (b) makes EOS early-stop free (stop launching), (c) makes
   compile+DMA ~0, (d) avoids the 48 MiB stream-window limit.
   The per-turn single-stream form is the validated fallback only.
5. PATCH HOLES (the complete set): XRF[3] token, XRF[4]=pos*1536
   (absolute, never relative), TCNT_SEQ, JMP target, SEQ_LEN.
   ALWAYS emit the token seed (the committed stream skips it when
   tok==prev argmax — an emitter quirk, do not replicate).
6. POSITION BLOB: generated per session = concat over p in [0,T_max)
   of 6 copies of rope_tables_q15(p) (1536 B/position; layer_fixed).
   T_max=512. Committed 6-position pool reproduced byte-exact = gate.
7. SESSION = run T_PREAMBLE once (resets KV/DN/conv/TCNT = fresh
   context). Context continuation across launches is real: START
   clears only pc/err/abort/perf (seq_unit.sv:796-805). Proven on
   seq_model (split==mono, tokens AND full state).
8. CONTEXT GUARD (host-side, mandatory): T + (P-1) + N < 512.
   RTL wraps SILENTLY at T=512 (kv_waddr t[8:0]; attn aliases; no
   error). T==0 at ATTN hangs. seq_run has NO guard today.
9. RESIDENCY PROBE: sha256 witness blocks (4 KiB/image via dma_read,
   ~3 ms for 187 images) vs a host manifest before any skip-upload.
10. EXCLUSIVITY: flock on sw/.seq.lock acquired by EVERYTHING that
    opens /dev/xdma0_* in the chat/serve stack. The seq busy check is
    TOCTOU-only.
11. HOST INTEGRATION: import sw/seq_run.py as a library (Dev, plan_ddr,
    relocate, upload, seq_start_and_poll) — do NOT shell out to its
    CLI, do NOT fabricate .seq.json meta. relocate() runs ONCE per
    session on the resident images (538 LDC + 4 EMB rebases).
12. TIMING MODEL (replaces the plan's 0.12/0.16 split): decode step
    156.2 ms MEASURED; prefill-lite ~138.8 ms DERIVED (measure in
    phase 2 via PERF_CYC per launch). Steps per turn = P + N - 1
    (the last prompt step yields the first reply token).
    20-tok prompt + 50-tok reply ~= 10.4 s.

## Hazards (all confirmed in RTL, the compiler/client MUST respect)

- OUT FIFO: 0x6018 read IS the pop; depth 16; overflow drops SILENTLY;
  only hard reset clears it -> drain (while halted) before every START.
  KNOWN RTL BUG (log only, zero-RTL rung): of_cnt push/pop same-cycle
  race (seq_unit.sv:1049 vs :1100) loses a count if host pops while
  busy — decision 4 makes it unreachable; fix candidate for the next
  RTL rung (case({push,pop}) like the fetch FIFO :443).
- TCNT_SEQ==0 at JMP flags=1 wraps to 2^32-1 (hang until timeout).
  Every compiled image must set it explicitly.
- SEQ_LEN must equal the image's record count (else E_JMP/E_PC).
- XRF seeds go IN-STREAM (host AXI XRF writes don't write through to
  layer_chan, seq_run zeroes XRF before START). Absolute values only.
- ABORT = CTRL[1] at 0x6000 (E_ABORT 0x0C), record-boundary only; no
  watchdog on I_SYNCW/I_AMAXW/I_BULK* — a wedged DDR read needs
  reprogram. Do not write S_LEN/S_BASE/S_TCNT_SEQ/XRF while busy.
- Error codes a bad compile trips: E_PC 0x09, E_JMP 0x08, E_ALIGN 0x0B
  (stale XRF3/4), E_LAYEROP 0x10 / E_CMDTMO 0x11 (skipped preamble).

## File ownership

- Agent A: ref/seq_chat.py (TurnCompiler + posblob gen + tests) ONLY.
  Works in EMITTER address space (0x8000_0000/0x6000_0000); outputs
  byte images + hole offsets; host side does relocation.
- Agent B: sw/chat_seq.py ONLY (+ sw/.seq.lock convention).
- Agent C (after B): sw/serve.py + sw/chat_client.py ONLY.
- Integrator: tb_seq_chip 2-turn gate, HW gates, evidence/chat/,
  ISA doc corrections, commits.

## Gates

A1 seq_model: compiled model_v2 schedule (always-seed rule) ->
   tokens [561,314,279,369,279,6511] + full state == committed golden;
   split-vs-mono equality; per-step-launch equality (invest. exps 1-3
   productized as pytest-style checks runnable via make or uv run).
A2 posblob: 6 committed positions byte-exact; T_max=512 blob size
   786,432 B.
A3 seq_model: 4 fresh prompts, tokens == layer_fixed greedy reference.
B1 HW: canned model_v2 prompt via chat_seq.py -> tokens
   [561,314,279,369,279,6511], 2 runs.
B2 HW: 4 fresh prompts x 2 runs token-identical to seq_model
   prediction; measured lite/full ms per step reported (PERF_CYC).
B3 HW: 2-turn context continuation; context-overflow auto-reset path
   exercised once (forced small --max-ctx).
C1 API: tokens identical to chat_seq.py for same prompts; 2-client
   queue test; restart recovery (residency probe skips upload).
I1 tb_seq_chip: one lite-prefill launch + one full launch, 2-launch
   continuity on real RTL (START preserves banks) — BEFORE first HW
   run of chat_seq.py.

## Phase-1 amendments (RATIFIED 2026-08-09, integrator ruling)

A. POSITION MODE = "ldc" IS THE SHIPPED DEFAULT (via --pos-mode auto).
   Finding (Agent A): XRF is 18-bit and xrf_rd SIGN-EXTENDS every index
   except [3] (seq_unit.sv:240); a CSRWR truncates silently (:841, no
   xrf_ovf — that flag is XOP-only). So XRF[4]=pos*1536 reaches only
   pos<=85, making spec decisions 6/8 unreachable via the XRF hole.
   Ruling: patch the six position-LDC addr_lo fields per launch instead
   (body byte offsets 33544/70856/108168/145480/182792/220104; XRF[4]
   stays 0; XRF[4] has exactly 24 consumers in the artifact, all these
   LDCs). Per-launch patch becomes 72 B in 7 writes (48 B head + 6x4 B)
   — still ~0 vs a 156 ms step. pos_mode="xrf" remains available and
   HARD-REFUSES pos>85. Consequences: (1) looped build_turn cannot use
   ldc (raises) — launch-per-step is the primary path and unaffected;
   (2) ref/seq_model does NOT model the sign extension, so xrf-mode
   bugs past 85 are sim-invisible — gate I1 must include one ldc launch
   at pos>85 on real RTL.
B. prompt_fed in the artifact meta is the SEEDED SUBSET, not the
   prompt (emitter skips the seed when tok==prev argmax). The true
   canned prompt is [760,6511,314,9338]; gate B1's token list
   [561,314,279,369,279,6511] is all six argmaxes and requires
   --prefill full (--canned forces it); prefill-lite emits reply
   tokens only ([369,279,6511]) by design.
C. Exclusivity note: infer.py/seq_run.py/tok_meter.py do not yet take
   sw/.seq.lock — the lock is authoritative only within the chat/serve
   stack; retrofit is a follow-on.

## docs/SEQ_ISA.md corrections (ratified now, applied in this commit)

- ABORT is CTRL[1] at SEQ+0x00 (no SEQ_ABORT register exists).
- STATUS has no pc field: pc is its own reg at SEQ+0x14; STATUS
  carries err_code[31:24] and out_cnt[20:16].
