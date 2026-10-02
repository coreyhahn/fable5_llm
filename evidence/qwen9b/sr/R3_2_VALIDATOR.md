# R3-2 — the validator: a broadcast MOVX admitted only at {R1,R2,R3}

Task R3-2 of the R3 campaign (MOVX broadcast, form (a); plan
`docs/superpowers/plans/2026-09-29-r3-broadcast.md`, Task R3-2). The contract
is `docs/SEQ_ISA.md` §B17.3 as R3-1 landed it (heading at `docs/SEQ_ISA.md:1589`;
the running rule per destination at `docs/SEQ_ISA.md:1644`, the admission at
`docs/SEQ_ISA.md:1657`). Started from HEAD 76a0c2d; every run on snoke through
`evidence/qwen9b/sr/sr_run.sh`, logs n2400–n2499. Labels: **E** printed by a
committed run.

## 1. What changed (ref/seq_format.py only)

| where | what |
|---|---|
| `ref/seq_format.py:595` | the channel clause: `if r.chan >= 4 and not _movx_bcast_admitted(r, caps, bad):` — the one rewritten line in `validate()`; the message on the next line is untouched |
| `ref/seq_format.py:768` | `return _bcast_running(recs, n, shape_isa, caps)` — the one rewritten line in validate_stream |
| `ref/seq_format.py:884` | disasm's MOVX line reaches `_movx_dst(r)`: a broadcast prints `MOVX   chan=ALL XWIN <= …` | <!--cites:noquote-->
| `ref/seq_format.py:2567-2659` | the R3 block, after every line any document cites: `MOVX_BCAST = 0xF`, `MOVX_BCAST_CAPS`, `_movx_bcast_admitted`, `_bcast_running`, `_movx_dst` |

Semantics, per B17.3:

* **Admission.** A MOVX with flags[7:4] = `MOVX_BCAST` (0xF) is admitted by
  `validate()` only when `MOVX_BCAST_CAPS` = {R1,R2,R3} ⊆ caps, the DEVICE's
  set (`ref/seq_format.py:2581`). Below it the refusal names the record
  index (via `bad`), the channel field value 0xf, the three capabilities it
  needs, the device's caps and every missing one. The names are checked by
  `hwmap.seq_caps_check` (`ref/seq_format.py:2578`); the bits and the word
  stay hwmap's alone (`sw/hwmap.py:358-360`) — no SEQ_CAPS literal is typed in
  `ref/` (TDD case (a), E: `evidence/qwen9b/sr/n2460_r3_2_validator_tdd_GREEN.log:26`).
* **Window.** An admitted broadcast then meets B17.2's rule on the ONE start
  word exactly as a unicast MOVX does (target[15:12] = 0; start ≤ 3071;
  start + ceil(len/4) ≤ 3072) — the existing R2 branch of the clause, since
  R2 ⊆ caps.
* **Kept refusals.** MOVX flags[7:4] 4..14 and every MVGO with flags[7:4] ≥ 4
  (MVGO 0xF included) keep today's `engine channel N >= 4` (err 0x05);
  indirection on a broadcast keeps today's A1 refusal (it is checked first).
* **Running rule, per destination.** `validate_stream()`'s last step
  (`ref/seq_format.py:2606`) walks the admitted stream in record order and
  refuses a broadcast whose word range overlaps ANY channel's pending x range
  (a NO-WAIT MVGO not yet drained by a waiting MVGO on that channel or by a
  FENCE covering it; an empty broadcast counts as overlapping, as
  `ref/seq_model.py:471-475` does). The message names the record and the
  channel. Below {R1,R2,R3} it returns at once (`ref/seq_format.py:2621`), so
  no pre-R3 stream's verdict can move.

## 2. RED then GREEN

| run | tree | result |
|---|---|---|
| n2400 RED | 1015cd8 (the TDD committed, today's validator) | 87 PASS / 47 FAIL, rc 1 (E: `evidence/qwen9b/sr/n2400_r3_2_validator_tdd_RED.log:153-156`) |
| n2460 GREEN | 638ad5f (the final layout) | 134 PASS / 0 FAIL, rc 0 (E: `evidence/qwen9b/sr/n2460_r3_2_validator_tdd_GREEN.log:159-162`) |

RED failed exactly the groups the edit exists for — (a) admission, (b) the
admitted windows, (e) the running-rule admissions, (f) `chan=ALL`, (g) the
new broadcast difference, (k) the constants — while (c) reserved encodings,
(d) unicast and (h) the 64 w9 streams passed on both sides, as predicted.
The TDD is `evidence/qwen9b/sr/r3_validator_tdd.py`; it loads the BASE
validator (76a0c2d) from git, so every "unchanged" row below is a comparison
of verdict STRINGS, base against tree.

### 2.1 The refusal matrix (E: `evidence/qwen9b/sr/n2460_r3_2_validator_tdd_GREEN.log:17-25`)

| caps | broadcast MOVX | refusal names |
|---|---|---|
| {} | REFUSED | R1, R2, R3 |
| {R1} | REFUSED | R2, R3 |
| {R2} | REFUSED | R1, R3 |
| {R3} | REFUSED | R1, R2 |
| {R1,R2} | REFUSED | R3 |
| {R1,R3} | REFUSED | R2 |
| {R2,R3} | REFUSED | R1 |
| {R1,R2,R3} | ADMITTED (validate and validate_stream) | — |

The same through hwmap's decoder: the set decoded from 0xFAB1CA07 admits,
from 0xFAB1CA03 (build_045), 0xFAB1CA01 (build_044) and 0xDEADC0DE (every
pre-round bitstream) refuses.

### 2.2 The other cases (all E, the same log)

* (b) window at {R1,R2,R3}: start 3000 + 256 words (len 1024) refused; 2048 + 1024, 1536 + 1536, 0 + 3072 and 3071 + 1 admitted; 1537 + 1536 and 3071 + ceil(5/4) refused; target[15:12] ≠ 0 refused.
* (c) MOVX flags[7:4] 4..14 at all 8 caps subsets (88 cases), MVGO 0xF (16), broadcast with flags[3:0] ∈ {1, 2, 3, 0xF} (32): all refused with the base's message string (`evidence/qwen9b/sr/n2460_r3_2_validator_tdd_GREEN.log:38-40`).
* (d) unicast MOVX, channels 0..3 × 5 start words × 6 lengths × 8 caps × 2 layouts: 1920 verdicts, 0 differ from the base (`evidence/qwen9b/sr/n2460_r3_2_validator_tdd_GREEN.log:42`).
* (e) the running rule, for EACH of the four channels: refused while it runs bank 0 (naming the record and `mv<c>`); admitted into bank 1; a pending K = 12288 stream (ng 96) spans both banks and refuses a bank-1 broadcast; admitted after a FENCE, after a FENCE mask covering the channel, after a waiting MVGO; refused after a FENCE mask that skips it; an XBANK stream refuses bank 1 and admits bank 0. Plus: one of four running (mv3 bank 0, the others bank 1) refuses and names mv3; a zero-length broadcast on a running channel is refused; the word just past a pending range is admitted and the last word inside it refused; unicast MOVX over a pending range keeps the base's `validate_stream` verdict at every caps (the unicast rule stays the model gate's).
* (f) `MOVX   chan=ALL XWIN <= scratch[0x0 .. +128] int8`; unicast disasm byte-identical to the base (`evidence/qwen9b/sr/n2460_r3_2_validator_tdd_GREEN.log:86-87`).
* (g) 12000 random records × 8 caps × 3 layouts = 288000 verdicts: 286680 identical; 1155 differ only in the refusal's wording (a broadcast refused by both below {R1,R2,R3}); 165 are broadcasts newly admitted at {R1,R2,R3}; 0 other differences (`evidence/qwen9b/sr/n2460_r3_2_validator_tdd_GREEN.log:89`).
* (h) every one of the 64 `tb/scripts/w9/*.e4.seq` streams (shipped s1..s4, reordA/B, r1, r2, the SR5b/SR11b/SR13a images, lay9b/tok9b): `validate_stream` verdict identical to the base at {}, {R1}, {R1,R2}, {R1,R2,R3}, layout unstated and 9B (`evidence/qwen9b/sr/n2460_r3_2_validator_tdd_GREEN.log:155`).
* (k) `MOVX_BCAST` = 0xF; `MOVX_BCAST_CAPS` = {R1,R2,R3}, valid names in hwmap.

## 3. Existing streams through the same gates (byte-identical verdicts)

The gates SR4 and SR11b used, re-run on 638ad5f and diffed against their
committed logs by `evidence/qwen9b/sr/r3_2_gate_compare.sh` (the gate body
from the interpreter banner to the wall line, per-phase timings stripped;
the body includes the stream sha256, so the regenerable r1/r2 `.e4` files
are the ones those logs gated):

| stream | gate (caps) | new log | prior log | verdict |
|---|---|---|---|---|
| shipped s1..s4 | `evidence/qwen9b/ov/sv1_gate.sh` ({}) | n2481–n2484 | n1174–n1177 | IDENTICAL, SEQ GATE: PASS, tokens identical |
| reordB_r1 s1..s4 | `evidence/qwen9b/sr/sr4_gate.sh` ({R1}) | n2485–n2488 | n414–n417 | IDENTICAL, SEQ GATE: PASS |
| reordB_r2 s1..s4 | `evidence/qwen9b/sr/sr11b_gate.sh` ({R1,R2}) | n2491–n2494 | n1169–n1172 | IDENTICAL, SEQ GATE: PASS |

All twelve IDENTICAL, `R3_2_GATE_COMPARE: PASS`, rc 0
(E: `evidence/qwen9b/sr/n2495_r3_2_gate_compare.log:7-19`); e.g. s1's gate
ends `TOKENS IDENTICAL [2614, 314, 279, 369, 11751, 13]` and `SEQ GATE: PASS`
(E: `evidence/qwen9b/sr/n2481_r3_2_gate_shipped_s1_r0.log:30-31`). The
compare log's own stamp is 3368d06+dirty — R3-0 committed its TDD while the
gates ran; the twelve gate logs themselves are stamped 638ad5f+dirty.
TDD (h) covers the same streams (and 52 more) at {R1,R2,R3} as well.

## 4. Regressions on the final tree (638ad5f)

| check | result (E) | prior |
|---|---|---|
| `evidence/qwen9b/g3/isa_bits.py` | ISA_BITS: PASS, rc 0 (`evidence/qwen9b/sr/n2461_r3_2_isa_bits.log:63`) | — |
| `isa_bits.py --negative-control` | NEGATIVE_CONTROL: PASS (`evidence/qwen9b/sr/n2462_r3_2_isa_bits_negctl.log:37`) | — |
| `sr2_isa_tdd.py` | 39 PASS / 0 FAIL (`evidence/qwen9b/sr/n2463_r3_2_sr2_isa_tdd.log:55`) | 39/0, `evidence/qwen9b/sr/n2302_r3_1_isa_tdd_noflag.log` |
| `sr2_isa_tdd.py --r3` | 59 PASS / 0 FAIL (`evidence/qwen9b/sr/n2464_r3_2_sr2_isa_tdd_r3.log:76`) | 59/0, `evidence/qwen9b/sr/n2301_r3_1_isa_tdd_GREEN.log` |
| `sr11a_r2_tdd.py` | 59 passed, 0 failed (`evidence/qwen9b/sr/n2465_r3_2_sr11a_r2_tdd.log:86`) | 59/0, `evidence/qwen9b/sr/n1101_sr11a_tdd_GREEN.log` |
| `sr4_r1_tdd.py` | 31 passed, 0 failed (`evidence/qwen9b/sr/n2466_r3_2_sr4_r1_tdd.log:64`) | 31/0 |
| host TDDs sr6 / sr7 / sr13b / sr11a fix2 / fix3 | 45/0, 36/0, 42/0, 12/0, 8/0 (`evidence/qwen9b/sr/n2467_r3_2_sr6_host_tdd.log:142`, `evidence/qwen9b/sr/n2468_r3_2_sr7_host_tdd.log:59`, `evidence/qwen9b/sr/n2469_r3_2_sr13b_host_tdd.log:126`, `evidence/qwen9b/sr/n2470_r3_2_sr11afix2_tdd.log:71`, `evidence/qwen9b/sr/n2471_r3_2_sr11afix3_tdd.log:40`) | identical to SR14's n1434–n1438 |
| boardfree (`evidence/qwen2b/rd/rd_boardfree.sh`, FABLE5_MODEL unset) | seq_run 2840/0, serve 85/0, chat_seq 407/1 (`evidence/qwen9b/sr/n2472_r3_2_boardfree.log:70`, `evidence/qwen9b/sr/n2472_r3_2_boardfree.log:116`, `evidence/qwen9b/sr/n2472_r3_2_boardfree.log:147`) | the same triple, the same [22] failure, `evidence/qwen9b/sr/n1725_sr17ff_boardfree.log` |
| `ref/seq_format.py` selftest | OK (`evidence/qwen9b/sr/n2475_r3_2_seq_format_selftest.log:20`) | — |

isa_bits enumerates no MOVX channel encodings (it ties MVGO_MAX_NG, the
SHAPE slices and the RTL MOVX start-word slice), so it gains no 0xF case;
recorded, per the plan's "if".

## 5. Citation drift: zero

The first implementation (dfd8863) inserted lines through the file; its o3
plan (`evidence/qwen9b/sr/n2450_r3_2_drift_plan.log`) asked for 145 REPAIR
and 4 COLLATERAL rewrites across 24 documents, among them `docs/SEQ_ISA.md`
(not this task's) and the plans. Rather than touch them, 638ad5f moved every
addition after the last cited line (SR14 §7's zero-drift rule), leaving three
single-line rewrites. The check at base 15132b2, doc-base 15132b2 through
`evidence/qwen9b/sr/r3_2_drift.sh` (which refuses a non-commit doc-base):
159 distinct citations into `ref/seq_format.py`, 158 unmoved, 0 drifted
(`evidence/qwen9b/sr/n2473_r3_2_drift_check.log:19-20`); the plan: REPAIR 0,
COLLATERAL 0 (`evidence/qwen9b/sr/n2474_r3_2_drift_plan.log:18`). The one
UNRESOLVED token is the plan's own pointer at the line this task was told to
change, `ref/seq_format.py:595-596` in the R3 plan's Task R3-2 text
(`evidence/qwen9b/sr/n2473_r3_2_drift_check.log:22`): line 595 still holds
the channel check and 596 its message, so the token still names the clause;
it is the controller's document and is left as is (no digit would change).
No `--fix` ran, so no `--verify` is owed.

## 6. Judgment calls

1. **The running rule is checked in `validate_stream`, not only left to the
   model.** The addendum lists "refused when any one of the four destination
   banks is running" as a RED case, while B17.3 (`docs/SEQ_ISA.md:1644`) and
   the plan's task text assign the running rule to the model gate and the
   pass. Both are honoured: `validate()` stays stateless as B17.3 says, and
   `validate_stream()` — which already carries stream state — refuses the
   hazard for a BROADCAST only. It is an extra, earlier refusal; it cannot
   move a pre-R3 verdict (it returns at once below {R1,R2,R3}), and R3-3 still
   owes the model's per-destination RunningChannelError. Its walk is in
   record order (a hazard across a JMP back-edge is the model gate's).
2. **`MOVX_BCAST` is not beside `CHAN_SHIFT`.** The plan asked for it at
   `ref/seq_format.py:192`; one line there moves 145 citations in 24
   documents (§5). It lives in the R3 block (`ref/seq_format.py:2574`) with
   the rest of R3's code; zero drift outranks adjacency.
3. **The refusal message for a broadcast below {R1,R2,R3} changed** from
   `engine channel 15 >= 4` to one naming the missing capabilities (the task
   requires it). The VERDICT is unchanged — refused at every such caps set —
   and TDD (g) proves that no other record's message moved.
4. **A new TDD file, not a flag.** The existing validator TDDs are per-task
   mixes of model, pass and doc checks whose content is R1's or R2's; every
   case here is new, and the plan names this file.
5. **disasm shows no start word** for a broadcast, as for a unicast (the
   unicast line is kept byte-identical).
6. **Dirty stamps.** Every final log reads `638ad5f+dirty`; the dirty entries
   are R3-0's in-flight files (`evidence/qwen9b/g6/g6_state.py`,
   `sw/program_fpga.sh`, `synth/scripts/build.tcl`,
   `synth/scripts/launch_build.sh`, and its untracked r3_* and
   synth/scripts/postimpl_sanity.tcl), listed in each header; none is an
   input to the validator, the TDDs or the gates. Not mine to clean.
7. **Superseded logs.** n2401–n2409 and n2440–n2444 ran on dfd8863 (the first
   layout, same semantics) and are committed as such; n2406 ran boardfree
   with FABLE5_MODEL=9b exported, which that 2B path does not take (serve
   84/1 and a chat-template crash — an environment artefact; n2409 and n2472
   with it unset match the baseline). The first launch of the 12 gates
   (n2411–n2434) was killed when the layout changed and its partial logs
   deleted; the gates were re-run on 638ad5f as n2481–n2494.

## 7. Not established here

The model's per-destination running refusal and its broadcast execution
(R3-3); the pass that emits a broadcast (R3-5); the host path (R3-6); the
RTL decode (R3-8). `tb/scripts/gen_seq_unit_vectors.py` carries a twin
validator (the plan's hazard list); it is not in this task's files and still
refuses flags[7:4] = 0xF — the task that lands the RTL decode owns that twin.
