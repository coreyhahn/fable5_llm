# Qwen3.5-2B migration as an agent benchmark

This file packages the 0.8B → 2B migration (executed 2026-08-12..14 on
branch `qwen2b`) as a repeatable benchmark for coding agents. It contains
the task prompt, the run setup, and the scoring key. **This file is a
spoiler: it is off-limits to contestants**, same as the rest of the
`QWEN2B_*` docs and the `qwen2b` branch (see Setup, item 2).

## The prompt (paste verbatim)

```
Take this repo's LLM accelerator from Qwen3.5-0.8B to Qwen3.5-2B. Plan it
out first, then execute end to end.

One big difference from a plain port: I want to understand how much the
quantization the current code uses costs, versus the 2B model at full
native resolution. All options are on the table — group sizes, better
quantizer algorithms, mixed precision, more weight bits, even RTL datapath
changes; I want the tradeoffs (quality vs tokens/sec vs resources), not a
default. Produce a decision table with evidence behind every number and
stop for my decision before committing the design to one precision.

Hard requirements:
- One bitstream serves both models.
- Every frozen 0.8B artifact regenerates byte-identically and replays
  bit-exact on the widened RTL; the full 0.8B hardware ladder must
  reproduce on the new bitstream before the 2B ever touches the board.
- Evidence for every claim committed under evidence/; commit at every
  green gate.
- Otherwise proceed autonomously; only stop for the precision decision or
  for anything destructive.
```

## Setup

1. **Pin the start state.** Tag `main` at `ea4d703` ("docs: Qwen3.5-2B
   feasibility (corrected)") — feasibility done, nothing executed; the
   state the reference run started from. Each contestant runs in a fresh
   worktree/branch cut from that tag. Harder variant: start one commit
   earlier, before the feasibility study exists.
2. **Two answer keys are off-limits.** For benchmark runs, extend the
   CLAUDE.md off-limits rule to cover, in addition to
   the pre-existing private implementation (the "answer key"):
   branch `qwen2b` and everything it produced — `evidence/qwen2b/`,
   `docs/QWEN2B_*` (including this file), the
   `docs/superpowers/specs/2026-08-12-*` + `plans/2026-08-12-qwen2b-*`
   documents, `.superpowers/sdd/`, and the auto-memory entries written
   during the reference run. Worktrees cut from the `ea4d703` tag will
   not contain these files, but the branch remains reachable in the git
   object store — the rule must name it.
3. **Environment parity.** Same CLAUDE.md, skills, MCP servers, and
   memory state as the reference run. The 2B checkpoint already present
   in the HF caches may stay (downloading is not the interesting part).
4. **Board serialization.** Hardware stages need the real BCU-1525: one
   run at a time, safe-reprogram flow only (`pcie_helper.sh remove` →
   JTAG → `rescan`, volatile bitstreams only), and snoke's Vivado queue
   is a shared resource.
5. **Memtest darthplagueis first.** During the reference run the host
   produced provably wrong arithmetic 7 times in one day (impossible-
   guard trips at `w4a8_ref.py:161`, verified wrong against independent
   re-reduction; one numpy-level SIGSEGV; OOM excluded; details in
   `evidence/qwen2b/q2/v3/V3.md` §6). Until the box passes a memory/CPU
   soak, it is a confound that can sink a run through no fault of the
   model. The reference run moved all numeric compute to snoke.

## Scoring key

### Gates (binary, cheap to verify)

- Emitter regen hash-lock holds: `sha256(model_v2_s1.e.seq) ==
  a69864d2…f444aaf1`, nrec 60495, `model_v2_s1.txt` byte-identical.
- Every frozen 0.8B stream replays bit-exact on the widened RTL
  (`layer_s*`, `token_s*`, `model_v2_s1..s4`, `w3/` seq_chip, `w4/`
  chat_i1) — reference datum: the `w3` tok2 stream replays in exactly
  2,272,141 cycles on both pre- and post-migration RTL.
- Full sim ladder green, 4 seeds everywhere.
- Timing closed (WNS ≥ 0) on the widened build.
- 0.8B HW ladder reproduces on the new bitstream (30.4 tok/s nch=4,
  lockstep 0 mismatch, sampled chat seed-deterministic).
- 2B decision table delivered, precision-gate stop honored, every number
  traceable to committed evidence.

### Known-good numbers (pinned corpus: `ref/ppl_corpus_eval.txt`,
sha `6bf4f867…c27876`, 24,528 positions; checkpoint header
`ccba2c1f…bfee9d`)

| quantity | reference value |
|---|---|
| 2B bf16 PPL anchor | 12.346298 |
| W4 g128 (production quantizer + emb16 + cw13, res_scale 8) | 14.176885 |
| W4 g64 (same config) | 13.744231 |
| W8 g128 everywhere | 12.360678 |
| 2B scratch peak (words of 32K) | 25,600 |
| W4 g128 bytes/token | 996,282,368 |
| W8 g128 bytes/token | 1,936,920,576 |
| dn/kv URAM (geometry-invariant) | 348 = 261 + 87 |
| Scratch BRAM growth | +16 RAMB36 (not the naive +14) |

A contestant's study should land on these or show why theirs differ.
Quantizer-search results (salience/GPTQ class) are corpus- and
calibration-sensitive: score them on method soundness and the pinned
anchors above, not on matching every decimal.

### Discovery score (is what's actually there found?)

- The vecnorm N=2048 deadlock — and its true mechanism (OUT's
  `oidx != n_total`, not FILL).
- The DNST command word being exactly 32 bits full (naive 15-bit
  widening overflows it).
- The matvec scale-beat machinery needing generalization (3 beats g64,
  2 beats g128 at NG=48) — the ref already defined the format.
- The S6 burst window's 128 KiB range-alignment problem (0x5_0000 is
  illegal; window must move).
- The BD IPI wrapper port width as the one sim-invisible failure.
- The documented ~9 ms mover bucket being wrong (~11.4 ms measured;
  preamble mis-amortization; assumed-not-measured matvec term).
- Mixed W4/W8 by class-sensitivity being a dead end (damage tracks class
  size), while quantizer improvements at fixed bytes are the live axis.

### Process cost

Wall-clock, total tokens, review/fix-loop rounds, and the fraction of
claims that survive adversarial re-verification.
