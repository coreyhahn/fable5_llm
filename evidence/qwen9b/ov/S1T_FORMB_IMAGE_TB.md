# S1T — FORM B's PER-IMAGE ORDER ON THE CHIP TESTBENCH: the chat images, run

Task S1T closes the gap S1P §5 left open (`evidence/qwen9b/ov/S1P_SHIP.md`
§5): form B's **per-image** order had no chip-TB run. That order is the lite
and full chat step images reordered one at a time, with the position patch
following its record. SV1 had verified form B's **template** order on four
seeds; that is a different set of streams. This task ran the chat tool's own
images on the SV1 chip-TB binary (the shipped RTL). **No RTL changed, no
testbench changed, and the board was not touched.**

## 0. HOW TO READ EVERY NUMBER BELOW, AND THE VERDICT

* **E** = printed by a run of this task. Each log was written ON SNOKE
  through `evidence/qwen9b/ov/ov_run.sh`, whose header records host, tree and
  command. Each E is cited `path:line`.
* **D** = derived arithmetic. Every ratio and percentage was computed on
  snoke by `evidence/qwen9b/ov/s1t_compare.py` and printed in
  `evidence/qwen9b/ov/n163_S1T_compare.log`.
* **T** = transcribed from an earlier document, and cited there.

**Why this order matters.** It is the order every default 9B chat session
runs. Since 2026-09-27 (S1D and its fix round), `sw/chat_seq.py` with neither
`--reorder` nor `$FABLE5_REORDER` resolves **auto → "B"** at
`FABLE5_MODEL=9b --nch 4` on the shipped template. The generator printed this
resolution itself: `effective_reorder(auto, 9b, --nch 4, shipped template) =
'B'` (**E**, `evidence/qwen9b/ov/n151_S1T_vectors_c1.log:6`).

**VERDICT: tokens IDENTICAL, 4 of 4 seeds.** Each seed is a chat scenario.
Every seed ran on the chip TB twice: once in the shipped order and once in
form B per image. All 8 runs PASS. Each run checks every launch's end state
against its golden: XRF, OUT tokens, the TCNT banks, EOUT/AMAX, 36,864
scratch words, and a hash of every stored DDR state block. The carried state
is also checked before each START. The two sides' goldens are identical
launch by launch, apart from the record counts and PC. The chip's tokens
match form B against shipped at every launch of every seed
(**E**, `evidence/qwen9b/ov/n163_S1T_compare.log:44`).

**Cycles.** Form B's full image is **28,619,539–28,624,399 cyc**. That is
**within ±0.009 %** of SV1's form-B template token (28,621,887 = 171,731,320
/ 6). The chip speed-up per image kind is:
* **full ×1.1454.** This is the template's ×1.1454.
* **lite ×1.1598.**

The ratio is the same on all 8 launches of each kind
(**D**, `evidence/qwen9b/ov/n163_S1T_compare.log:40-43`).

## 1. WHAT RAN, AND WHY IT IS THE PER-IMAGE ORDER

**Feasibility (step 0, written before any run;
`.superpowers/sdd/2026-09-24-overlap/task-S1T-report.md`).**
`tb/tb_seq_chip.sv` already runs multi-launch goldens (`tb/tb_seq_chip.sv:36`,
CHAT_SEQ gate I1). It relaunches the never-reset DUT once per section,
exactly as `sw/seq_run.seq_start_and_poll` does. The SV1 binary includes
that reader. What did not exist was a golden for the 9B chat images.

Approach (b) was rejected. It would have reordered the s1 stream's per-token
segments, which is what SV1 already did. That approach exercises neither the
chat images (head records, the lite prefix cut, position-0 static pricing)
nor the record-following patch.

**The generator** is `evidence/qwen9b/ov/s1t_chat_vectors.py`, committed
before its runs at `9b11356`. It is composed only of existing parts:

* **The images.** They come from `sw/chat_seq.py`'s `ChatSession`: one
  session with `reorder=None` and one with `reorder="B"`. The B session's
  `_reorder_images_b` refuses unless lite and full regenerate equal to
  their pins. They did:
  * lite `c9efdf35…`, 38,378 records;
  * full `7119833c…`, 39,146 records;
  * MOVX elided 480 each; fences deferred 200 each;
  * hazard assert PASS on both.

  (**E**, `evidence/qwen9b/ov/n151_S1T_vectors_c1.log:15-16`,
  `evidence/qwen9b/ov/n151_S1T_vectors_c1.log:22-23`.)
* **Every launch image** is `sess.step_patch(kind, tok, pos, tcnt=1,
  data_delta=0).apply(image)`. That is the expression chat_seq's B6 gate
  uses. For form B it is `follow_patch`: the shipped image's patch (the
  48-byte head plus 8 position-LDC `addr_lo` words) moved to each record's
  new index. Emitter space is the chip TB's DDR plan.
* **The goldens.** They come from `ref/seq_model.SeqExec`, run over the
  launch sequence on ONE persistent Mach and ONE `StateRegion` loaded from
  `model_9b_s1.state.bin`. That is B6's method, and the same file the TB
  maps.
  * The `.seq` layout (4 KiB-aligned concatenation) is
    `tb/scripts/gen_chat_i1_vectors.py`'s.
  * The per-launch lines (EMBLOG2, SBASE, all-KVH TCNT, SMEM fnv1a64, MEM
    minus staging) are `tb/scripts/gen_seq_chip_vectors.py`'s.
* **The base** is `tb/scripts/w9/model_9b_s1`, the chat tool's base (the
  weights, embedding table and state image of the shipped template).

**The launch sequence, per seed.** It is a 3-token prompt followed by one
decode, exactly as chat_seq runs them:

| launch | image | token | position |
|---|---|---|---|
| 0 | preamble | — | — |
| 1 | lite | T0 | 0 |
| 2 | lite | T1 | 1 |
| 3 | full | T2 | 2 → emits o1 |
| 4 | full | o1 | P → emits o2 |

**The seeds.** They vary the prompt and, above all, the last position P.
S1P §5 said the mapped LDC patch was checked at positions 300 and 510 only
by byte equality, never run. Here it runs on the RTL at 86, 300 and 510.

| seed | T0 T1 T2 | P | why P | vectors log |
|---|---|---|---|---|
| c1 | 760 2614 314 | 3 | a contiguous chat | `evidence/qwen9b/ov/n151_S1T_vectors_c1.log` |
| c2 | 279 264 854 | 86 | the first position past the XRF cursor | `evidence/qwen9b/ov/n152_S1T_vectors_c2.log` |
| c3 | 313 430 2510 | 300 | S1P §5's byte-equality position | `evidence/qwen9b/ov/n153_S1T_vectors_c3.log` |
| c4 | 11 0 271 | 510 | S1P §5's byte-equality position; max_ctx − 1 | `evidence/qwen9b/ov/n154_S1T_vectors_c4.log` |

**Model-level acceptance, before any chip run.** The generator asserts, for
every launch:
* the two sides' golden lines are identical (other than LAUNCH/PC);
* the form-B image differs from the shipped one (it is reordered);
* the three head records are unmoved;
* the const blob is identical.

All four seeds printed `S1T_VECTORS PASS` (**E**,
`evidence/qwen9b/ov/n151_S1T_vectors_c1.log:30-37` and the same lines in
n152–n154).

**The chip runs.** The binary is `tb/obj_dir_seq_chip_sv1/tb_seq_chip_9b_sv1`,
sha256 `8fc981fd…`, the SV1 binary built from the shipped-RTL snapshot
(`evidence/qwen9b/ov/n155_S1T_chip_c1_ship.log:7`; SV1 §1). The runner is
`evidence/qwen9b/ov/run_sv1_chip.sh`, unchanged, in control mode, with
`LOGDIR=evidence/qwen9b/ov/seedlogs_s1t`.
* Eight runs (n155–n162), all detached on snoke at the same time.
* Wall time was 5,278–6,550 s each.
* Before the launch, `pgrep` found no other user of the obj_dir on snoke,
  kyloren or darthplagueis.

## 2. RESULTS — tokens and cycles per seed

Cycles are **E** from the seed logs, and the ratios are **D**; all are
transcribed from `evidence/qwen9b/ov/n163_S1T_compare.log`. "B" means form B
per image.

| seed | launch | kind | records ship → B | cycles shipped | cycles B | × | chip tokens ship / B |
|---|---|---|---|---|---|---|---|
| c1 | 1 | lite | 38,858 → 38,378 | 30,210,292 | 26,047,645 | 1.1598 | — |
| c1 | 2 | lite | 38,858 → 38,378 | 30,215,077 | 26,052,754 | 1.1598 | — |
| c1 | 3 | full | 39,626 → 39,146 | 32,781,847 | 28,619,539 | 1.1454 | [279] / [279] |
| c1 | 4 | full @3 | 39,626 → 39,146 | 32,786,722 | 28,624,387 | 1.1454 | [2614] / [2614] |
| c2 | 3 | full | | 32,781,886 | 28,619,539 | 1.1454 | [11] / [11] |
| c2 | 4 | full @86 | | 32,786,734 | 28,624,387 | 1.1454 | [279] / [279] |
| c3 | 3 | full | | 32,781,925 | 28,619,551 | 1.1454 | [88] / [88] |
| c3 | 4 | full @300 | | 32,786,773 | 28,624,399 | 1.1454 | [11] / [11] |
| c4 | 3 | full | | 32,781,910 | 28,619,539 | 1.1454 | [11] / [11] |
| c4 | 4 | full @510 | | 32,786,722 | 28,624,387 | 1.1454 | [271] / [271] |

Sources for the rows: `evidence/qwen9b/ov/n163_S1T_compare.log:9-12`,
`evidence/qwen9b/ov/n163_S1T_compare.log:19-20`,
`evidence/qwen9b/ov/n163_S1T_compare.log:27-28` and
`evidence/qwen9b/ov/n163_S1T_compare.log:35-36`.

Over all 8 lite launches (launches 1 and 2 of every seed), shipped spans
30,210,226..30,215,128 and form B 26,047,645..26,052,754
(`evidence/qwen9b/ov/n163_S1T_compare.log:40`). That is a spread of 4,902 cyc
(0.016 %) shipped and 5,109 cyc (0.020 %) form B
(**D**, `evidence/qwen9b/ov/n166_S1Tfix1_compare.log:42`). *(Fix round 1: an
earlier sentence here said c2–c4's lite launches fall inside c1's ranges; on
the shipped side that was false — c3 launch 1 is below c1's, c2 launch 2 above.)*
The preamble is 214 cycles on both sides
(`evidence/qwen9b/ov/n166_S1Tfix1_compare.log:40`).

**Whole runs (5 launches):**

| seed | shipped | form B | × |
|---|---|---|---|
| c1 | 125,994,152 | 109,344,539 | 1.1523 |
| c2 | 125,994,254 | 109,344,539 | 1.1523 |
| c3 | 125,994,239 | 109,344,563 | 1.1523 |
| c4 | 125,994,215 | 109,344,539 | 1.1523 |

Every run's verdict is `TB_SEQ_CHIP PASS` and `SV1_CHIP … PASS`. For example,
c1 B: `(launches 5, 109344539 cycles total, scratch 36864/launch, tokens 2,
tcnt 8)` (**E**, `evidence/qwen9b/ov/n156_S1T_chip_c1_B.log:35`,
`evidence/qwen9b/ov/n156_S1T_chip_c1_B.log:39`).

**What the cycles say.**
* **The per-image full image costs what SV1's form-B template token
  costs.** The difference is −0.008 % / +0.009 %
  (**D**, `evidence/qwen9b/ov/n163_S1T_compare.log:43`), and the speed-up is
  the same ×1.1454. Reordering each chat image on its own, at position-0
  static costs, loses nothing against the template reorder on the chip.
* **The chip agrees with the static model.** Chip ×1.1598 (lite) and
  ×1.1454 (full) sit against the modelled ×1.1604 and ×1.1460 (**T**,
  `evidence/qwen9b/ov/S1P_SHIP.md` §2, `evidence/qwen9b/ov/n86_s1p_static_vs_csv.log:116-126`).
* **Silicon sits below the chip, more so on full.** Silicon at ctx ≤ 511
  measured ×1.1436 (lite) and ×1.1254 (full) (**T**, S1P_SHIP §3.3). The
  larger gap on full is consistent with the ATTN dilution at deep KV that
  S1P §3.3 describes; here the KV length is at most 4, so the TB does not
  see it. (No new ratio is derived here.)
* **Position does not change the cost.** The last launch at P = 86, 300
  and 510 costs the same as at P = 3 to within a few cycles (the table
  above: 28,624,387 at P = 3, 86 and 510; 28,624,399 at P = 300). ATTN's
  cost follows the KV length, not the RoPE position.

## 3. WHAT IS STILL NOT ESTABLISHED

* **Short contexts only.** The KV holds at most 4 rows (TCNT ≤ 4). Deep-KV
  cost and any deep-KV interaction are not covered: the F1 wait on KV SLDs
  and the ATTN window at T ≈ 500. Safety there rests, as before, on the
  hazard assert and the postcheck, which are position-independent.
* **The RoPE position patch was exercised at 3, 86, 300 and 510, but not at
  contiguous deep contexts.** The KV rows those positions attend over were
  written at positions 0–2.
* **One scenario shape.** Each seed is a 3-token prompt plus one decode. No
  auto-reset, no second turn and no multi-turn session were run.
  `--prefill full`, sampled decode and `--verify` are not covered.
* **The chat base only.** Every seed uses `model_9b_s1`, the chat tool's
  only 9B base. The seeds vary prompt and position, not weights.
* **The TB is not the board.** The DDR latencies are the TB's models, and
  channel-3 contention is not counted. The board-side items of S1P §5 are
  unchanged: one silicon session per form, and no `--prefill full` T-curve.
* **The generator is task-local.** `s1t_chat_vectors.py` is not wired into a
  Makefile target. Its outputs (`tb/scripts/w9/s1t_c*_{ship,B}.e4.*`) are
  gitignored and regenerable. **n151–n154 (and the chip logs n155–n162)
  record only 16-hex PREFIXES of their sha256s, not full digests**, and no
  committed file holds the full digests (fix round 1). A regenerated vector
  set can therefore be checked against these runs only by prefix.

*Added in fix round 1 (2026-09-27):*

* **Emitter space, not relocated space.** The TB runs the images with
  `data_delta 0`. The board runs RELOCATED images, and the patch carries a
  delta: the session relocates LDC/EMB by −0x74000000
  (`evidence/qwen9b/ov/n151_S1T_vectors_c1.log:21`). A defect in how
  relocation composes with `follow_patch` at a nonzero delta would pass
  S1T. S1P's byte-equality check (patch∘reorder == reorder∘patch, with a
  relocation delta) and the one silicon session (`evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log`)
  are what cover it.
* **The obj_dir idle check was asserted, not captured.** The `pgrep` on
  snoke, kyloren and darthplagueis before n155–n162 printed nothing, but its
  output is in no committed log.
* **Step 0 (the feasibility write-up) lives in the gitignored ledger report**
  `.superpowers/sdd/2026-09-24-overlap/task-S1T-report.md`; §1 above
  summarises it.
