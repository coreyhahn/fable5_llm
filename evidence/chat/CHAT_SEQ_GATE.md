# CHAT-SEQ GATE — fast interactive chat + API on the sequencer (2026-08-10)

Zero-RTL rung per docs/CHAT_SEQ_SPEC.md (frozen + phase-1 amendments).
Bitstream unchanged: build_031_rr_AltSpreadLogic_medium (4d71adcc).
All numbers measured on silicon this date, after the snoke disk
incident + rebuild (docs/SNOKE_REBUILD.md) — the board came back to
937.381 ms on the seq_run regression, within 4 us of pre-incident.

## Measured performance (the user-facing result)

| quantity | value |
|---|---|
| decode step (full body) | 150.2 ms device (PERF_CYC 37,548,421 @ 250 MHz) |
| prefill step (lite body, LM head cut) | 100.3 ms device (-33%, vs 11% first estimate) |
| session preamble (context reset) | 36.1 ms |
| steady decode rate | 6.66 tok/s, streamed per-token |
| turn model | 36.1 + (P-1) x 100.3 + N x 150.2 ms |
| MMIO per turn | ~570 reads / ~100 writes (infer.py: ~3M ops/token) |
| server warm restart -> ready | 2.5-2.7 s (residency probe skips 885 MiB) |
| device_frac | 0.988-0.989 (host overhead ~1%) |

vs the host-driven CLI (infer.py, 9.3 s/token): a 20-tok prompt +
50-tok reply turn is now ~9.5 s instead of ~650 s (~68x wall).

## Gate ladder (all PASS, logs/JSONs in this directory)

- Bring-up: JTAG program 4d71adcc, MAGIC/VERSION/CALIB verified;
  seq_run regression 937.381 ms, tokens + 7,188 state checks golden
  (seqrun_postrebuild.json).
- SMOKE: one full-step launch, token 561 == golden, OUT FIFO clean
  (chat_seq_smoke.json). Two bring-up bugs found on this first-ever
  silicon path (tmpl_recs attr typo -> fixed to recs_emit) — the
  selftest/model-only modes structurally cannot reach it; noted.
- B1 x2: --canned reproduces [561,314,279,369,279,6511] both runs
  (chat_seq_b1_run{1,2}.json).
- B2 8/8: 4 fresh prompts x 2 runs, reply ids == the gate-A3 quantized
  reference: Japan [369,25358,13] (" is Tokyo."), Water boils at
  [220,16,15] (" 10.."), My favorite color is [279,799,421],
  In the beginning [314,279,220] (b2_*.log).
- B3a: 2-turn session with --verify lockstep: 18/18 steps
  "== seq_model", 0 mismatches — context continuity bit-exact on
  silicon (b3_2turn_verify.log).
- B3b: forced --max-ctx 20 overflow -> AUTO-RESET (preamble + replay
  last 4 history tokens), completes at 20/20 (b3_overflow.log).
- C1 (API): SSE stream delivers golden tokens with device_ms_total
  937.38 (= the seq_run number exactly); 2-client FIFO with queue
  position + eta events, queued client served after 1.66 s wait with
  golden output; kill + restart -> ready 2.67 s warm -> golden reply
  (c1_server.log).
- I1 (committed earlier, 68dd689): tb_seq_chip multi-launch on real
  RTL — START preserves KV/DN/conv/TCNT; pos-86 ldc RoPE address
  witness (24 bursts correct window, 0 to the xrf-truncation address).

## How to use it

- CLI: ssh snoke; cd .../sw; .venv/bin/python chat_seq.py
  (/reset /stats /ntok N /quit; --max-ctx 500; streams at 6.6 tok/s).
- API: .venv/bin/python serve.py --port 8137 (localhost only; tunnel
  with ssh -L 8137:localhost:8137 snoke). Client: chat_client.py
  --port 8137 [--prompt "..."]. Endpoints: /v1/generate (SSE),
  /v1/health, /v1/metrics, /v1/reset, /v1/sessions.
- EXCLUSIVITY: chat_seq/serve take flock(sw/.seq.lock); infer.py /
  seq_run.py / tok_meter.py DO NOT — never run them while the server
  or chat CLI is up.

## Follow-ons (logged, not blocking)

- Retrofit the flock into infer.py/seq_run.py/tok_meter.py.
- chat_seq --prompt JSON report omits token ids (stdout only); the
  "% of wall was device" stat line prints x1000 too big. Cosmetic.
- OUT FIFO of_cnt push/pop RTL race (seq_unit.sv:1049 vs :1100):
  unreachable under launch-per-step; fix with case({push,pop}) at the
  next RTL rung.
- Session persistence + idle TTL for serve.py if it runs for days.
- Prefill batching (weight-stationary) remains the big prompt lever;
  decode levers per docs/SPEEDUP_LADDER.md (census the ~76 ms/token
  non-matvec remainder first).
