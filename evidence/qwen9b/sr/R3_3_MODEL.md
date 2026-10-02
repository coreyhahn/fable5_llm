# R3-3 — the reference model executes a MOVX broadcast

Task R3-3 of the R3 campaign (MOVX broadcast, form (a); plan
`docs/superpowers/plans/2026-09-29-r3-broadcast.md`, Task R3-3). The contract
is `docs/SEQ_ISA.md` §B17.3 (the running rule per destination at
`docs/SEQ_ISA.md:1644`, the XPTR rule at `docs/SEQ_ISA.md:1635`, the admission
at `docs/SEQ_ISA.md:1657`); the validator is R3-2's (`evidence/qwen9b/sr/R3_2_VALIDATOR.md`).
Started from HEAD a2fed67 (R3-0 commits landed on top of it, none touching
`ref/`); every run on snoke through `evidence/qwen9b/sr/sr_run.sh`, logs
n2500–n2599. Labels: **E** printed by a committed run.

## 1. What changed (ref/seq_model.py only; zero citation drift)

| where | what |
|---|---|
| `ref/seq_model.py:654` | `SeqExec.__init__`: `self.xptr = {}` — rewritten in place over a comment line |
| `ref/seq_model.py:937-939` | `SeqExec._movx`: the R3 hook `if _movx_r3(self, r):` / `return`, rewritten in place over two comment lines (the comment above is reflowed into one line); the unicast body below it is untouched |
| `ref/seq_model.py:2129-2206` | the R3 block, after every line any document cites and before the __main__ guard: `_movx_r3`, `_movx_bcast` |

Semantics (B17.3):

* **One read, four writes.** `_movx_bcast` reads `M.mem[addr_lo : addr_lo + len]`
  ONCE (`ref/seq_model.py:2201`) and writes it through `XWinMem.write` into
  channels 0..3 at the one start word, target[11:0] (`ref/seq_model.py:2204-2205`),
  so the same window, hence the same bank, on all four; the ragged tail is
  zero-padded on each, and each channel's vector map (the SR11a
  unwritten-read bookkeeping) records its own write.
* **Running rule per destination.** Before any write, the broadcast's word
  range is checked against EVERY channel's pending x range (`SeqExec.running`,
  SR11a); an overlap raises `RunningChannelError` naming that channel
  (`ref/seq_model.py:2193-2200`) — an explicit raise, so it survives `python -O`.
  An empty broadcast counts as overlapping (`_overlap`, `ref/seq_model.py:471-475`),
  as `validate_stream` does. Because the model walks the stream as executed,
  this is the check a hazard carried round a JMP back-edge meets (C2), which
  `validate_stream`'s record-order walk (`ref/seq_format.py:2606-2652`) cannot see.
* **XPTR.** Modelled for the first time: `SeqExec.xptr` holds the channels a
  unicast MOVX of this stream zeroed (the X_XPTR state that precedes the
  unicast burst, `rtl/seq_movers.sv:904-905`); a broadcast sets none. An
  absent channel means "whatever the host left" (B17.3 XPTR).
* **Caps.** `run()` validates every record at the model's caps first
  (`ref/seq_model.py:1063`, R3-2's clause at `ref/seq_format.py:595`), so a
  broadcast below {R1,R2,R3} never reaches `_movx`. `_movx_bcast` mirrors
  that admission for a DIRECT call: it refuses with `SeqValidationError`
  naming every missing capability, from `MOVX_BCAST_CAPS`
  (`ref/seq_format.py:2581`, names checked by hwmap, `sw/hwmap.py:358-360`) —
  no SEQ_CAPS literal in `ref/seq_model.py`.
* **Counters and cost.** A broadcast is one record: `stats["MOVX"]` counts it
  once (B17.3 COUNTERS); nothing is priced here (R3-4's).
* **A unicast MOVX is unchanged** except for the one XPTR write, which no gate
  or snapshot reads.

## 2. RED then GREEN

| run | tree | result |
|---|---|---|
| n2500 RED | a62f324 (the TDD committed, today's model) | 82 PASS / 35 FAIL, rc 1 (E: `evidence/qwen9b/sr/n2500_r3_3_model_tdd_RED.log:190-192`) |
| n2501 GREEN | c2fdfb3 (the implementation committed) | 117 PASS / 0 FAIL, rc 0 (E: `evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:136-138`) |

The TDD is `evidence/qwen9b/sr/r3_model_tdd.py` (a new file: no model-only
TDD exists to take an `--r3` flag; `sr4_r1_tdd.py` / `sr11a_r2_tdd.py` are
R1's / R2's contract+validator+model mixes, and every case here is new). It
loads the BASE model (a2fed67) from git, so every "unchanged" row is a
bit-identical state comparison.

RED failed exactly the groups the edit exists for and passed the ones that
must not move: (f) 65/65 and the (h) validator-side rows passed on both sides.
**C1 on today's model** (E, the RED log): a broadcast at {R1,R2,R3} wrote a
phantom XWIN channel 15 (`evidence/qwen9b/sr/n2500_r3_3_model_tdd_RED.log:57`),
was ACCEPTED over a pending mv2 (`evidence/qwen9b/sr/n2500_r3_3_model_tdd_RED.log:62`),
and a direct `_movx` below {R1,R2,R3} executed it into channel 15
(`evidence/qwen9b/sr/n2500_r3_3_model_tdd_RED.log:167`).

### 2.1 The cases (all E, `evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log`)

* (a) broadcast + four MVGOs is bit-identical (machine state, RES, XWIN
  bytes, vector map) to four unicast MOVX of the same source + the same four
  MVGOs (`evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:10`); ragged tail (len 130) zero-padded on all four (`evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:11`); a
  bank-1 broadcast lands at word 1536 on all four, bank 0 untouched; exactly
  channels 0..3 written — no phantom 15 (`evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:13`); one MOVX counted.
* (b) a no-wait MVGO pending on mv<c> (bank 0), then a bank-0 broadcast →
  `RunningChannelError` naming mv<c>, for each c in 0..3 (mv2 at `evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:18`), and
  no channel's XWIN is written at the refusal (`evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:20`).
* (c) mv2 pending bank 0, broadcast into bank 1 → admitted, and the XBANK
  MVGO after the FENCE computes on the broadcast x (`evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:22`); all four pending
  bank 0, broadcast bank 1 → admitted.
* (d) mv0..2 pending bank 1, mv3 pending bank 0, broadcast bank 0 → refused
  naming mv3 only (`evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:25`); a pending K = 12288 stream spans both banks; a
  zero-length broadcast on a running channel is refused; word 32 just past
  mv3's range admitted, word 31 refused.
* (e) broadcast into bank 0, then an XBANK MVGO on mv1 → `UnwrittenReadError`
  as today (`evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:31`); a later unicast over part of the broadcast on mv0 kills
  only mv0's vector.
* (f) eight no-broadcast streams (legal R2 mix, plain, masked FENCE, the three
  running hazards, an unwritten read, a bank-1 MOVX over a pending bank-1
  read) × all 8 caps subsets: the outcome (verdict string or full state:
  running set, stats, snapshot, XWIN/RES views, x_mem bytes, vector and
  segment maps) identical to the base model — 64/64, plus the check that the
  legal streams actually RUN at {R1,R2,R3} (`evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:98`).
* (g) XPTR: two unicasts → `{1: 0, 3: 0}`; two broadcasts → `{}`; a unicast
  then a broadcast → `{2: 0}` (`evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:100-102`).
* (h) a broadcast stream at each of the 7 caps subsets below {R1,R2,R3} is
  refused by the validator before execution, naming the missing caps
  (`evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:112` for {R1,R2}); a DIRECT `_movx` at each is refused by the model's
  own mirror (`evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:113`); `MOVX_BCAST_CAPS` is the admission set; no SEQ_CAPS
  literal in the model; a unicast on each channel is base-identical at all
  8 caps subsets.
* (j) **C2**: broadcast; mv1 no-wait MVGO on it; JMP back — `validate_stream`
  (record order) ADMITS the stream, the model refuses the second pass naming
  mv1 (`evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:125`); control: mv1 pending in bank 0 round the back-edge with the
  broadcast into bank 1 is not refused (it runs to `max_steps`). **M1**: mv2's
  pending range popped by FENCE mask 0b0100 (R1), by FENCE mask 0, and a
  FENCE then mv2's waiting MVGO — each then admits the broadcast
  (`evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:127-130`); FENCE mask 0b1011 skipping mv2 leaves it refused (`evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:131`).
* (k) the refusal is an explicit `raise RunningChannelError` in
  `_movx_bcast` (`evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:133`); under `python -O` the broadcast over a pending mv2
  is still refused naming mv2 (`evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:134`); the model's verdict equals
  `validate_stream`'s on every record-order case (`evidence/qwen9b/sr/n2501_r3_3_model_tdd_GREEN.log:135`).

## 3. Existing streams through the same gates (byte-identical)

The gates SR4 and SR11b used, re-run on the clean committed tree c2fdfb3
(all twelve stamped so), concurrently on snoke (971–997 s each), with the
running-channel refusals armed, and diffed against the round's committed logs
by `evidence/qwen9b/sr/r3_2_gate_compare.sh` given the twelve new logs (the
gate body from the interpreter banner to the wall line, per-phase timings
stripped; the body includes the stream sha256, so the regenerable r1/r2 `.e4`
files are the ones those logs gated):

| stream | gate (caps) | new log | prior log | verdict |
|---|---|---|---|---|
| shipped s1..s4 | `evidence/qwen9b/ov/sv1_gate.sh` ({}) | n2505–n2508 | n1174–n1177 | IDENTICAL, SEQ GATE: PASS, tokens identical |
| reordB_r1 s1..s4 | `evidence/qwen9b/sr/sr4_gate.sh` ({R1}) | n2509–n2512 | n414–n417 | IDENTICAL, SEQ GATE: PASS |
| reordB_r2 s1..s4 | `evidence/qwen9b/sr/sr11b_gate.sh` ({R1,R2}) | n2513–n2516 | n1169–n1172 | IDENTICAL, SEQ GATE: PASS |

All twelve IDENTICAL, `R3_2_GATE_COMPARE: PASS`, rc 0
(E: `evidence/qwen9b/sr/n2525_r3_3_gate_compare.log:8-21`); e.g. s1's gate ends
`TOKENS   IDENTICAL  [2614, 314, 279, 369, 11751, 13]` and `SEQ GATE: PASS`
(E: `evidence/qwen9b/sr/n2505_r3_3_gate_shipped_s1_r0.log:21-22`). The compare
log's own stamp is 60fdd58+dirty (other tasks committed meanwhile; the dirty
entries are R3-0's untracked gate doc and this one, neither an input). None of
these streams carries a broadcast, so the gates exercise the unchanged unicast
path plus the one XPTR write per MOVX.

## 4. Regressions on the clean committed tree c2fdfb3

| check | result (E) | prior |
|---|---|---|
| `ref/seq_model.py --selftest` | PASS, rc 0 (`evidence/qwen9b/sr/n2504_r3_3_model_selftest.log:12`) | `evidence/qwen9b/sr/n1145_sr11afix1_model_selftest.log` |
| `python -O ref/seq_model.py --selftest-refusal` | 11/11 hazards refused, 2/2 unwritten reads refused, PASS (`evidence/qwen9b/sr/n2517_r3_3_refusal_selftest_O.log:6`) | the same line, `evidence/qwen9b/sr/n1142_sr11afix1_refusal_selftest_O.log` |
| `sr4_r1_tdd.py` | 31 passed, 0 failed (`evidence/qwen9b/sr/n2518_r3_3_sr4_r1_tdd.log:55`) | 31/0, `evidence/qwen9b/sr/n2466_r3_2_sr4_r1_tdd.log` |
| `sr11a_r2_tdd.py` | 59 passed, 0 failed (`evidence/qwen9b/sr/n2519_r3_3_sr11a_r2_tdd.log:77`) | 59/0, `evidence/qwen9b/sr/n2465_r3_2_sr11a_r2_tdd.log` |
| `r3_validator_tdd.py` (R3-2's) | 134 passed, 0 failed (`evidence/qwen9b/sr/n2520_r3_3_r3_validator_tdd.log:151`) | 134/0, `evidence/qwen9b/sr/n2460_r3_2_validator_tdd_GREEN.log` |
| `sr11b_r2_check.py` (the r2 check) | SR11B_R2_CHECK: PASS (`evidence/qwen9b/sr/n2521_r3_3_sr11b_r2_check.log:38`); output identical to `evidence/qwen9b/sr/n1173_sr11b_r2_check.log` from the venv line to rc | — |
| `sw/chat_seq.py --selftest` | 407 passed, 1 failed — the known [22] region-image case (`evidence/qwen9b/sr/n2502_r3_3_chat_seq_selftest.log:32-33`) | the baseline, `evidence/qwen9b/sr/SR17_ROUND_CLOSE.md` §9 |
| boardfree (`evidence/qwen2b/rd/rd_boardfree.sh`, FABLE5_MODEL unset) | seq_run 2840/0, serve 85/0, chat_seq 407/1 (`evidence/qwen9b/sr/n2503_r3_3_boardfree.log:61`, `evidence/qwen9b/sr/n2503_r3_3_boardfree.log:107`, `evidence/qwen9b/sr/n2503_r3_3_boardfree.log:138`) | the same triple, `evidence/qwen9b/sr/n2472_r3_2_boardfree.log` |

The model's own selftests are untouched (no r3 case was added to
`selftest_running_refusal`: its hazard count stays 11 and `sr11a_r2_tdd.py`
(g) still reads it).

## 5. Citation drift: zero

The layout is R3-2's: one block before the `__main__` guard plus in-place
rewrites of three COMMENT lines (none cited). `evidence/qwen9b/sr/r3_2_drift.sh`
gained three flags (R3_DRIFT_BASE, R3_DRIFT_EDITED, R3_DRIFT_EXCLUDE; the
defaults are R3-2's run) and was run at code base a2ec680 (the implementation's
parent), doc-base a2ec680, edited `ref/seq_model.py`, this gate doc excluded:
126 distinct citations into `ref/seq_model.py`, 126 unmoved, 0 drifted,
0 unresolved, 0 half-mapped (E: `evidence/qwen9b/sr/n2522_r3_3_drift_check.log:11-14`);
the plan: REPAIR 0, COLLATERAL 0 (E: `evidence/qwen9b/sr/n2523_r3_3_drift_plan.log:14`).
No `--fix` ran, so no `--verify` is owed. (The wrapper's default excludes keep
R3-2's gate doc out of the sweep; its one cite into the model,
`ref/seq_model.py:471-475`, names unmoved lines.)

## 6. Judgment calls

1. **XPTR is modelled** (`SeqExec.xptr`), because the addendum lists "XPTRs
   unchanged" as a RED case and the model had no XPTR at all. It records only
   what a stream does (a unicast's X_XPTR = 0); it is not in the snapshot, so
   no gate reads it.
2. **The bank rule needs no model state.** A broadcast names ONE window for
   all four channels, so "the same bank on all four" holds by construction;
   the plan's default 5 (a disagreeing consumer) is the PASS's to repair with
   an edge. In the model a consumer MVGO whose XBANK names another window
   reads THAT window under XWinMem's strict-read rule — refused
   (`UnwrittenReadError`) when nothing intact starts there, case (e). The
   model cannot know which MVGO "consumes" a broadcast, so it cannot call a
   disagreeing bank an error beyond that.
3. **M1's waiting-MVGO pop.** In the model a waiting MVGO on a channel with a
   pending stream is itself refused (one engine), so only a FENCE pops a
   pending range; the TDD exercises the `running.pop` branch of a waiting
   MVGO after that FENCE. `validate_stream`'s waiting-MVGO pop is reached
   only in streams the model refuses anyway.
4. **The caps mirror raises `SeqValidationError`** (the validator's
   exception), not `RunningChannelError`, on a direct `_movx` below
   {R1,R2,R3}: it is an admission refusal, and `run()` meets the validator's
   own refusal first.
5. **Refusal order.** The four destinations are checked in channel order
   0..3 and the first overlapping one is named; a broadcast overlapping two
   pending channels names the lower.
6. **Two round tools gained flags** (not copies): `r3_2_drift.sh` (above) and
   `evidence/qwen9b/sr/r3_2_gate_compare.sh`, which takes the twelve new gate
   logs as optional arguments (none = R3-2's run, so n2495 reproduces).
7. **Stamps.** n2500 ran on a62f324, n2501–n2521 (the twelve gates
   included) on the clean c2fdfb3. n2522's `+dirty` names `evidence/qwen9b/sr/r3_2_drift.sh`, which
   was already committed (09704c4) — snoke's NFS view lagged the commit by
   seconds; n2523's names five documents R3-4 was repairing at that moment
   (its cite-drift pass, committed as 4a79cf7) — none cites into
   `ref/seq_model.py` differently at the doc-base, which is read from git.
   One dev run of the TDD (unlogged) first executed the OLD model because
   snoke's NFS attribute cache had not seen the edit; the logged runs are
   the committed trees.

8. **Doc pre-checks.** `evidence/qwen9b/sr/n2524_r3_3_spec_cites_precheck.log`
   (a draft: FAIL 17 — sixteen bare `:NNN` continuations and one quoted
   field beside a cite, all rewritten) and
   `evidence/qwen9b/sr/n2526_r3_3_spec_cites_precheck.log` (PASS) ran on the
   uncommitted draft; the LAST run is on the committed tree, alone.

## 7. Not established here

The pass that emits a broadcast and its hazard assert per destination (R3-5);
the cost of a broadcast (R3-4); the host path (R3-6); the RTL decode, the push
bus and its commit contract (R3-8); the twin validator/executor in
`tb/scripts/gen_seq_unit_vectors.py`, which still refuses flags[7:4] = 0xF
(R3-8's). No bitstream implements B17.3.
