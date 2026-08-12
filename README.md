# fable5_llm — a from-scratch LLM inference accelerator on an FPGA

A complete, working LLM serving stack built from first principles on a
**SQRL BCU-1525** (Xilinx VU9P): custom RTL, a custom instruction set, a
bit-exact fixed-point reference model, and a real instruction-tuned LLM —
**Qwen3.5-0.8B (instruct)** — chatting at **30.4 tokens/second** with
**on-chip top-k sampling**. No vendor AI IP, no HLS: SystemVerilog,
Verilator, and a paranoid verification culture.

```
prompt> Write a haiku about winter.            (--temp 0.8 --seed 4242)
the golden frost hangs upon the windows like ice draped on my cheeks...

prompt> Write a haiku about winter.            (--seed 4243)
cold fingers reach across and soft with your own love.
leaves rust with seasons and then slowly lose...
```

Every logit behind those tokens was computed on the FPGA. The host's
contribution to a sampled token is one random draw over 32 chip-ranked
candidates. Same seed → bit-identical poem, every time.

## The performance ladder

Each rung is a measured, gated, committed step. Wall-clock decode of the
same 24-layer model on the same board:

| rung | what changed | tok/s |
|---|---|---|
| 0 | host-driven MMIO orchestration (baseline) | 0.11 |
| 1 | **on-chip command sequencer** — the chip fetches and executes its own 60,495-record decode loop | 4.91 |
| 1b | 4-channel weight split — *functional but 15% slower; retained, documented, and later avenged* | — |
| 2 | vec_alu + vecnorm rebuilt as II=1 element pipelines | 6.40 |
| 3 | burst mover path — 13.2M single-beat AXI-Lite ops eliminated per pass | 15.56 |
| 4 | zero-bubble matvec retire pipeline + 4-channel interleaved LM head + on-chip TOPK-32 | **30.4** |

**276× end to end.** The remaining physics: ~140 tok/s DDR bandwidth
ceiling on this board.

## What's inside

- **The model**: Qwen3.5-0.8B instruct — a hybrid of 18 gated-DeltaNet
  (linear attention) layers and 6 GQA layers, hidden 1024, 248,320-token
  vocabulary — quantized W4A8 with per-group scales by this repo's own
  quantization flow.
- **The hardware** (`rtl/`): four DDR4-fed matvec engines (300 MHz, zero
  inter-row bubble), a banked 24-layer compute engine (DeltaNet recurrence,
  GQA attention, RoPE, SwiGLU, II=1 vector ALU, RMSNorm, a 32-entry on-chip
  top-k capture unit), and a command sequencer with burst data movers that
  runs the entire autoregressive loop with ~570 MMIO operations per token
  (the host-driven baseline needed ~3 million).
- **The ISA** (`docs/SEQ_ISA.md`): a 128-bit record format — 13 opcodes,
  an 8-entry exponent register file, token feedback through an on-chip
  argmax — frozen as a contract, amended only by dated addenda.
- **The reference** (`ref/`): a bit-exact fixed-point model of everything.
  The RTL is wrong by definition if it differs from `ref/layer_fixed.py`
  by one LSB. Silicon runs are gated on token-identity against it.
- **The serving stack** (`sw/`): an interactive CLI with the proper chat
  template, greedy or seeded sampling, and an SSE streaming HTTP API with
  a FIFO request queue.

Start with **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)** for the
system tour and **[`docs/USAGE.md`](docs/USAGE.md)** to run it.

## The method (and the honesty budget)

This project's rule set, enforced from day one:

1. **A bit-exact reference precedes RTL.** Simulation gates precede
   silicon. Hardware claims are gated on multi-seed, multi-run
   token-identity, and every gate's evidence is committed
   (`evidence/*/`).
2. **Negative results are shipped, not buried.** Rung 1b (4-channel was
   *slower*) is documented with the same rigor as the wins — and the
   measurement that explained it redirected two later rungs profitably.
3. **Measure before building.** Every optimization rung began with a
   cycle census on real silicon; two of the four "obvious" next steps
   were refuted by measurement before any RTL was written.
4. **Timing honesty**: reported WNS is from fresh routed checkpoints;
   the resident bitstream's version register traces to the exact git
   commit that built it.

An unusual constraint made the honesty enforceable: a pre-existing
private implementation of the same goal existed the whole time (the
"answer key") and was kept strictly unread — every design decision here
was derived from the datasheets, the measurements, and the math.

This was also an experiment in AI-assisted engineering: the work was
directed by a human and executed by Claude (Anthropic) orchestrating
teams of Opus agents under frozen interface contracts — investigation
agents that measured before speccing, implementation agents on disjoint
file ownership, and verification agents whose testbenches caught two
silent RTL bugs (a descriptor double-execution and a FIFO token-loss
race) before they ever reached hardware. The full session-by-session
narrative is in [`docs/HISTORY.md`](docs/HISTORY.md).

## Honest limitations

- It's a **0.8B model at 4-bit weights**: fast, coherent, frequently
  wrong. Quantization fidelity is 16/24 top-1 vs bf16 on the teacher-
  forcing harness — at the measured W4 ceiling, with the analysis in
  `evidence/stage5/`.
- Context is 512 tokens (KV bank depth in URAM); the chat stack manages
  overflow by reset-and-replay.
- Reproducing this needs the specific board (BCU-1525) and a Vivado
  seat; the frozen test vectors let you run the full sim regression
  with just Verilator.

## License & provenance

MIT (see `LICENSE`). Qwen3.5-0.8B weights are downloaded separately
from Hugging Face under their license and are not distributed here.
Board constraint files derive from the vendor's public board package
(attribution preserved in `synth/constraints/PROVENANCE.md`).
