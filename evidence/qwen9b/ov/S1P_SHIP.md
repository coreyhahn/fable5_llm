# S1P — SHIPPING S1 AS SOFTWARE: a static cost source, form B in the chat tool and on silicon, and the default-switch decision

Task S1P takes the verified S1 schedule (`evidence/qwen9b/ov/SV1_S1_VERIFY.md`,
`evidence/qwen9b/bm/BM1_BOARD_IDLE.md`) the last software steps toward
shipping it. The reorder pass no longer needs the untracked BN1 timeline CSV.
Form B now runs in `sw/chat_seq.py`, and it has run once on the shipped
bitstream. The switch that would make S1 the default is built, but **it is
not flipped**. The decision is the user's (§4).

## 0. HOW TO READ EVERY NUMBER BELOW

* **E** = printed by a run of this task. Every log was written ON SNOKE
  through `evidence/qwen9b/ov/ov_run.sh`, whose header records host, tree,
  command and `FABLE5_MODEL`. Each E is cited `path:line`.
* **D** = derived arithmetic. Every D was computed on snoke by a committed
  script, and is cited to the log line that printed it. No number here was
  computed on darthplagueis.
* **T** = transcribed from an earlier task's log or document. **S** = stated
  by a source file. Both are cited `path:line`.
* Cycles are cycles of the 250 MHz aclk. Board step time is the per-launch
  `S_PERF_CYC`, as BM1-T4 took it.

## THE RESULT, stated once and before the details

1. **The static cost source reproduces OV1's S1 exactly on `model_9b_s1`.**
   `reorder_e4.py --cost static` emits the **SV1-gated pins byte for byte**:
   form B `57ec3051…` and form A `b6ced3f9…`
   (**E**, `evidence/qwen9b/ov/n86_s1p_static_vs_csv.log:48`,
   `evidence/qwen9b/ov/n86_s1p_static_vs_csv.log:72`).
   * It elides the same 480 MOVX per segment, 1,920 in total.
   * It defers the same fences: 800 (B) and 864 (A), and the drained-stream
     sets are identical, fence for fence.
   * Its own modelled makespan is **−0.004 %** from the CSV path's
     114.438 / 117.935 ms/token
     (**E**, `evidence/qwen9b/ov/n86_s1p_static_vs_csv.log:39-41`,
     `evidence/qwen9b/ov/n86_s1p_static_vs_csv.log:63-65`).
   * It prices the chat step images, which **no CSV segment covers**. The CSV
     path refuses them (**E**, `evidence/qwen9b/ov/n86_s1p_static_vs_csv.log:116-126`).
2. **Form B passes all three gates without the board.**
   * The images regenerate equal to their pins.
   * The hazard assert passes on all three images.
   * B6 replays EXACT (511 s).
   * The negative test is sound. The control arm, patched by the real path,
     PASSES. The same bytes with one byte corrupted FAIL.
   * TDD went RED 3/3 (n87), then GREEN 39/0
     (**E**, `evidence/qwen9b/ov/n89_s1p_formB_tdd_GREEN.log:115`).
3. **Form B on silicon (build_041, no reprogram): tokens IDENTICAL** to the
   pinned reference (fail-closed `--want-ids`,
   **E**, `evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:94`).
   * **lite 115.093 ms, full 131.245 ms.**
   * Against shipped: **×1.1436 lite, ×1.1254 full**.
   * Against form A: **×1.0258 lite, ×1.0222 full**
     (**D**, `evidence/qwen9b/ov/n96_s1p_board_table.log:30-35`).
4. **The default is still OFF** (at S1P ship; flipped 2026-09-27, §4). `$FABLE5_REORDER` is the one-line switch
   (`sw/chat_seq.py:773`, `sw/chat_seq.py:6974`), for the chat_seq CLI only. §4
   sets out what flipping it means.

## 1. THE COST TABLE — provenance and fit (deliverable 1)

`ref/seq_cost.py` prices every record from its own fields. It feeds OV1's
unchanged `build_nodes` / `stream_durations` the same row shape the CSV gives:
a window per record, the stream's busy cycles on its MVGO row, and a FENCE row
that ends TAU cycles after the group's last stream
(**S**, `ref/seq_cost.py:339`).

| class | formula | source | fit on the CSV (tokens 1..6) |
|---|---|---|---|
| ALU / VN command | E1 busy + per-key overhead (node − busy_cmp, 3 ARG CSRWRs included) | **T** E1 means `evidence/qwen9b/sd/014_e1_analysis.log:15-41`; overhead **E** `evidence/qwen9b/ov/n83_s1p_cost_fit.log` | CMD class residual: mean \|d\| 0.018 cyc, max 11 (DYNQ8: E1 vs chip +2.78) (**E**, `evidence/qwen9b/ov/n83_s1p_cost_fit.log:137`) |
| ATTN | 1898 + 39 × position | **E** `evidence/qwen9b/ov/n83_s1p_cost_fit.log:48` | exact on positions 0..5 |
| VNW | 3n + 1 + overhead | **E** n83 | exact |
| CONV, DNST, GATE, KVAP, ROPE, ROPET | the measured node window | **E** n83 | exact (sd 0) |
| SLD / SST | 39; the 6th DMA command of a run 17,251 | **E** `evidence/qwen9b/ov/n83_s1p_cost_fit.log:55-56` | 42 of 42 stalls are exactly the 6th; 0 exceptions |
| MOVX | 71.1636 + 1.012031 × len | **E** `evidence/qwen9b/ov/n83_s1p_cost_fit.log:70` | max 2.56, rms 0.99 |
| MOVY | 68.0 + 2.03125 × len (pairs32); 67.0129 + 1.01947 × len (int16) | **E** `evidence/qwen9b/ov/n83_s1p_cost_fit.log:71-72` | max 0 / 4 |
| MVGO stream S | 36.1753 + 0.846518 × beats (1.1813 beats/cyc) | **E** `evidence/qwen9b/ov/n83_s1p_cost_fit.log:73` | max 1.34, rms 0.48 |
| FENCE tail TAU | 47 (4 streams), 61 (2) | **E** `evidence/qwen9b/ov/n83_s1p_cost_fit.log:75-76` | 4-stream sd 14.6, max 56 — the loosest class |
| LDC | 58.2936 + 1.125075 × count | **E** `evidence/qwen9b/ov/n83_s1p_cost_fit.log:77` | max 43.7 (DDR latency), rms 13.5 |
| EMB, XOP, AMAXL, JMP, CSRWR | 4699, 4, 17, 39, 3 (XRF 4, TCNT_SEQ 2) | **E** n83 | EMB ±37, the rest exact |

* **The table IS the fit.** The fit script recomputes every constant from the
  sha-checked CSV and the E1 log, then compares them with `ref/seq_cost.py`:
  *"TABLE MATCHES THE FIT (0 differences)"*
  (**E**, `evidence/qwen9b/ov/n83_s1p_cost_fit.log:123`).
* **Whole-token quality.** The static program-order window sum is within
  −0.0017 % to −0.0027 % of the CSV's on every token. Token 4 is −569 cycles
  on 32,786,868 (**E**, `evidence/qwen9b/ov/n83_s1p_cost_fit.log:132`).
* **Fail-closed — for the KEYED classes only** (scoped by the final review,
  2026-09-27; the full list is the module docstring, `ref/seq_cost.py:36`).
  A key the table does not carry is refused with `StaticCostError`: an
  ALU / VN command key, a fixed-window layer command (DNZ, CONV at another
  width), EMB at another length (**E**,
  `evidence/qwen9b/ov/n82_s1p_seq_cost_selftest_GREEN.log:44`), a MOVY mode
  the table does not carry (a raw `KeyError` until the final fix; **E**,
  `evidence/qwen9b/ov/n115_final_formB_tdd.log:36`), or an opcode it does
  not list. The other classes **EXTRAPOLATE** — they price any value of
  their variable, including values the CSV never showed:
  * MOVX, MOVY (within a known mode) and LDC, linear in length; the MVGO
    stream S, linear in beats; VNW, 3n + 1 in its length;
  * the ATTN line beyond position 5 (`ref/seq_cost.py:179`);
  * the TAU for other group sizes, nearest neighbour (`ref/seq_cost.py:198`);
  * the overhead of the E1 keys the stream never issues (`ref/seq_cost.py:170`).
* **TDD.** The `seq_cost` selftest went RED (n81) then GREEN (n82). The
  `reorder_e4` selftest went RED (n84) then GREEN (n85). The GREEN run checks
  that `--cost static` is the default, never opens the CSV, and refuses a
  stream it cannot price.

## 2. STATIC vs CSV — the reproduction (deliverable 1 acceptance)

Every number below is **E** from `evidence/qwen9b/ov/n86_s1p_static_vs_csv.log`.

| stream / form | MOVX elided csv / static | deferred fences csv / static (both) | modelled ms/token csv → static | output stream |
|---|---|---|---|---|
| s1 B | 1920 / 1920 | 800 / 800 (800) | 114.438 → 114.434 (−0.004 %) | IDENTICAL `57ec3051` (:48) |
| s1 A | 1920 / 1920 | 864 / 864 (864) | 117.935 → 117.930 (−0.004 %) | IDENTICAL `b6ced3f9` (:72) |
| s2 B | 960 / 960 | 400 / 400 (400) | 114.439 → 114.395 (−0.039 %) | IDENTICAL (:93) |
| s2 A | 960 / 960 | 432 / 432 (432) | 117.935 → 117.891 (−0.038 %) | IDENTICAL (:108) |

* **The tolerance was ≤ 1 % on the makespan; the difference is −0.004 %.** The static
  schedule, re-priced at the CSV windows, costs exactly the CSV schedule
  (+0.000 %; `evidence/qwen9b/ov/n86_s1p_static_vs_csv.log:39`). The two
  paths emit the same order on every segment.
* **s2's −0.039 % is the CSV path's error, not the static path's.** The CSV
  path borrows s1's token-3/4 windows for s2's positions 0/1 (SV1 §4.3). The
  static path prices s2 at its own positions.
* **A stream the CSV does NOT cover.** These are the chat tool's lite image
  (38,858 records) and full image (39,626 records). The CSV path refuses both:
  *"matches no template segment's skeleton"*. The static path reorders them:
  * form B: full ×1.1460 and lite ×1.1604, modelled;
  * form A: full ×1.1120 and lite ×1.1227, modelled
    (**E**, `evidence/qwen9b/ov/n86_s1p_static_vs_csv.log:116-126`).
* **Deviation from the brief, disclosed.** The brief says to emit
  `model_9b_s2` with the emitter. I did not re-emit it; that is a 3.5 h 9B
  emission. I used the existing, manifest-sha-verified s2 artifact instead
  (`dae58734…`, :75). It is not "uncovered": its segments skeleton-match the
  template, so the CSV path can reorder it too. The streams the CSV provably
  cannot cover are the two chat images above, and those are the ones §3
  ships.

## 3. FORM B — in the chat tool and on silicon (deliverables 2 and 3)

### 3.1 How the position patch was re-derived — and why per image

**chat_seq never runs the template.** A chat step image is three head records
(tok, pos, tcnt), then the body, then HALT. `lite` is a prefix of the full
body, cut where the LM head's MOVX run opens. In pos_mode `ldc`, which every
9B chat uses, the per-launch patch writes two things:

* the 48-byte head;
* eight position-LDC `addr_lo` words, at body offsets derived from the
  template.

**A whole-template form-B reorder breaks two things:**

* It moves the POSADV XOP off record n−3, which `derive_geometry` requires.
* Its free chain can place non-head work after the head's first MOVX. The
  lite prefix would then silently drop that work.

**So B is reordered PER IMAGE.** The session is built exactly as it is
without the flag: the shipped template, geometry, preamble and crosscheck.
Then each step image is reordered on its own, as a single segment, at static
costs (`sw/chat_seq.py:931`). A lite image is its own segment, so nothing it
holds can fall outside it.

**The patch follows its record.** Every write of the shipped patch is moved to
the reordered position of the record it was aimed at (`sw/chat_seq.py:969`,
`sw/chat_seq.py:2722`). The head records never move, and the code asserts
that. The same `step_patch` serves the board launch, the lockstep verifier
and the B6 gate.

**One construction was sound, so this was not an ambiguous choice.** A
template-level B with a relaxed geometry check would need to prove the lite
prefix complete. The per-image form needs no such proof.

### 3.2 The three gates, boardless (TDD: RED `evidence/qwen9b/ov/n87_s1p_formB_tdd_RED.log:48`, GREEN `evidence/qwen9b/ov/n89_s1p_formB_tdd_GREEN.log:115`)

| gate | result | cite |
|---|---|---|
| regeneration == pin | lite `c9efdf35…` (38,378 records), full `7119833c…` (39,146); deterministic over two builds | **E** `evidence/qwen9b/ov/n88_s1p_formB_pins.log:30-32`, `evidence/qwen9b/ov/n89_s1p_formB_tdd_GREEN.log:63`, `evidence/qwen9b/ov/n89_s1p_formB_tdd_GREEN.log:68` |
| hazard assert on the three images | PASS; a FENCE-less B lite is REFUSED | **E** `evidence/qwen9b/ov/n89_s1p_formB_tdd_GREEN.log:87-88` |
| B6 replay, shipped vs B, exact | PASS, tokens and full state, 511.2 s | **E** `evidence/qwen9b/ov/n89_s1p_formB_tdd_GREEN.log:97` |
| negative test | control override (UNCORRUPTED, patched by `step_patch` like the real path) PASSES; the same bytes with one ARG1 CSRWR `^0x10`, **1 byte different**, FAIL | **E** `evidence/qwen9b/ov/n89_s1p_formB_tdd_GREEN.log:105-114` |
| patch follows the record | patch(reorder(img)) == reorder(patch(img)) at pos 0, 1, 300 (+ a relocation delta) and 510, both images; the 8 mapped writes land on XRF-indirect LDC `addr_lo` fields; the host path uses them | **E** `evidence/qwen9b/ov/n89_s1p_formB_tdd_GREEN.log:74-85` |
| nothing else moved | `reorder=None` and `reorder=A` sessions byte-identical to the pre-S1P tool (06ebccd) | **E** `evidence/qwen9b/ov/n89_s1p_formB_tdd_GREEN.log:33`, `evidence/qwen9b/ov/n89_s1p_formB_tdd_GREEN.log:52` |

**chat_seq's own selftest is 407 passed, 1 failed, both after S1P and at the
pre-S1P base.** The one failure is pre-existing, in [22]
(**E**, `evidence/qwen9b/ov/n91_s1p_chat_seq_selftest_default_model.log:49`,
`evidence/qwen9b/ov/n92_s1p_chat_seq_selftest_BASE_06ebccd.log:51`).

### 3.3 On silicon — one session, shipped build_041, no reprogram

* **Pre-flight.** The T4 fix round's `--want-ids` had landed (20113d7).
  Identity was checked first: VERSION `0xc973c18a` and CALIB `0xF`,
  *"IDENT: PASS"* (**E**, `evidence/qwen9b/ov/n94_s1p_ident_041.log:19`,
  `evidence/qwen9b/ov/n94_s1p_ident_041.log:25`).
* **The session.** `evidence/qwen9b/bm/bm1_chat511.sh` → `bm1_census.py --chat --want-ids`, with
  `FABLE5_SEQ_EXPECT_VERSION` unset and chat_seq holding its own lock
  (**E**, `evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:15`).
  * B6 passed before the board was opened (530.2 s, :36).
  * The weights were resident (:40).
* **Tokens:** *"TOKENS IDENTICAL to --want-ids"* (:94).

| session | lite ms (502) | full ms (9) | lite × | full × |
|---|---|---|---|---|
| n68 build_041 shipped order (T) | 131.6174 | 147.7088 | — | — |
| n74 BM1 roll, form A (T) | 118.0582 | 134.1548 | ×1.1148 vs shipped | ×1.1010 |
| **n95 build_041, form B (E)** | **115.0934** | **131.2454** | **×1.1436 vs shipped; ×1.0258 vs A** | **×1.1254; ×1.0222 vs A** |

* **Source.** **D**, `evidence/qwen9b/ov/n96_s1p_board_table.log:30-35`, with
  n68 and n74 **T** from `evidence/qwen9b/bm/BM1_BOARD_IDLE.md:92` and
  `evidence/qwen9b/bm/BM1_BOARD_IDLE.md:132`.
* **The paired ratios are tight.** They are taken per launch at the same
  image and position. B vs shipped, lite: mean ×1.1437, sd 0.0042. Full:
  ×1.1254, sd 0.0001.
* **The B-vs-A comparison crosses bitstreams.** Form A ran on the BM1 roll,
  form B on build_041. T4 measured the two rolls' shipped-order step times
  −0.0015 % apart (`evidence/qwen9b/bm/BM1_BOARD_IDLE.md:92`).
* **Silicon sits close to the model, measured the same way.** The static
  model gives lite ×1.1604 and full ×1.1460, both at position 0. Silicon at
  context ≤ 511 gives ×1.1436 and ×1.1254. The gap is ATTN: its window grows
  with position, and nothing overlaps it, so at deep positions it dilutes the
  ratio (§5).

## 4. THE DEFAULT-SWITCH DECISION — for the user; NOT taken

**The switch — and exactly what it covers.** `reorder_default()` reads
`$FABLE5_REORDER` (unset/`off` = shipped order, `A`, `B`, case-insensitive;
anything else is refused) (`sw/chat_seq.py:773`). The **`sw/chat_seq.py` CLI**
reads it at argument-parse time as `--reorder`'s default
(`sw/chat_seq.py:6974`; fix round 1: not at import, so an importer never dies
on a bad value). It is documented in `docs/USAGE.md:259`. **Unset, the default
is None: not flipped** (**E**, `evidence/qwen9b/ov/n102_s1p_formB_tdd_fix1.log:37`).

* **The switch reaches `sw/chat_seq.py` ONLY.** `sw/serve.py` builds its own
  session namespace with no `reorder` field (`sw/serve.py:586-612`), and so
  does `sw/cycle_census.py` (`sw/cycle_census.py:69-76`). The served HTTP
  path and the cycle census therefore **always run the shipped order**,
  whatever the variable says.
* **To reach `sw/serve.py`** it would have to set `reorder` in that namespace
  AND run the gates chat_seq's `main()` runs before its board opens
  (`resolve_reorder`, the image hazard assert, B6), which live in `main()`,
  not in `ChatSession`. Not built.
* **Neither form needs the BN1 CSV any more** (fix round 1, I2). Form A now
  regenerates its template at the static costs (`sw/chat_seq.py:904`). It still
  must equal the committed SV1 pin `b6ced3f9…`, and it does, with the CSV
  loader made to raise: 0 CSV reads (**E**,
  `evidence/qwen9b/ov/n113_final_reorderA_nocsv.log:20-23`, on the committed
  tree `ba9ba4f`; `evidence/qwen9b/ov/n100_s1p_reorderA_nocsv.log:23-26` ran on
  a dirty tree and is superseded by n113 at HEAD).

**What the user is deciding (for `sw/chat_seq.py`):**

1. **Which form.** On silicon, B beats A by ×1.026 (lite) and ×1.022 (full),
   and beats shipped by ×1.14 / ×1.13. B is priced with the static table, and
   **its per-image order has no chip-TB run**. SV1 ran the form-B TEMPLATE on
   4 seeds, not these images. A is the SV1-verified template itself.
2. **The per-session gate cost.** Every chat_seq session with `--reorder`
   holds the board lock while it:
   * regenerates the images (A: 20.1 s,
     `evidence/qwen9b/ov/n100_s1p_reorderA_nocsv.log:22`; B: 5.6 s,
     `evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:25`);
   * runs the hazard assert;
   * runs the **B6 replay: 510–530 s of host time**.

   That is paid once per chat_seq process, before the first token.
3. **A cached-pin fast path — proposed, NOT built.** The B6 result is a
   deterministic function of:
   * the shipped and reordered images (both pinned by sha);
   * the const blob;
   * the weight manifest digest;
   * the initial state-region image;
   * the `ref/seq_model.py` sha;
   * the gate's own token/position list.

   A committed cache record keyed by the sha256 of all of these, written only
   by a passing gate run, would let a session whose keys all match skip the
   replay. The regeneration-equals-pin check (seconds) and the hazard assert
   (milliseconds) would still run every time. Any key mismatch falls back to
   the full gate. **Its risk is the key set**: an input the key misses would
   let a stale PASS through, so the key list needs its own review.
4. **What stays unverified if it is flipped** — §5, especially:
   * one session per form on silicon;
   * gate replays at positions 0 and 1 only;
   * no sampled (`--temp > 0`) or `--verify` session run under B.

**Flipped 2026-09-27: the user chose B** (Task S1D; appended — the text above
is the decision record as it stood, left as written). The user chose form B
as `sw/chat_seq.py`'s default, against the controller's "A first"
recommendation, with the forms explained from OV1 §2.3 (overlap ledger
`.superpowers/sdd/2026-09-24-overlap/progress.md`, the second round of user
decisions dated 2026-09-27). What changed, and what did not:

* `reorder_default()`: unset / empty → `"B"`; `off` / `none` → None (the
  shipped order); `A` / `B` explicit; anything else refused, echoing the
  original spelling. The CLI also takes `--reorder off` (→ None). A
  default-B session that cannot run B (not 9B `--nch 4`) refuses before the
  lock and the board, naming `FABLE5_REORDER=off` and `--reorder off`.
* Unchanged: the three gates (regeneration == pin, image hazard assert, B6
  exact replay) stay mandatory before `open_board()`; `--reorder A` stays
  available; `sw/serve.py` and `sw/cycle_census.py` still build namespaces
  with no `reorder` field (checked by reading) and still run the shipped
  order. No cached-gate fast path was built: the ≈ 510–530 s lock-held B6
  replay is now paid by every default `chat_seq.py` session.
* Evidence (all boardless, snoke): TDD RED
  `evidence/qwen9b/ov/n121_S1D_formB_tdd_RED.log` (41/5, exactly the five new
  assertions) → GREEN `evidence/qwen9b/ov/n122_S1D_formB_tdd_GREEN.log`;
  `chat_seq --selftest` `evidence/qwen9b/ov/n123_S1D_chat_seq_selftest.log`
  (407/1, the same pre-existing [22] as n116);
  `evidence/qwen9b/bm/n89_S1D_reorder_tdd.log` (14/0); and the proof at the
  new default — `--reorder-check` with no `--reorder` flag and
  `$FABLE5_REORDER` unset resolves form B, both image pins match, the hazard
  assert passes, the B6 replay is EXACT, and no board is opened:
  `evidence/qwen9b/ov/n124_S1D_reorder_check_default.log` on the clean
  committed tree `846b2a2` — form B with no flag
  (`evidence/qwen9b/ov/n124_S1D_reorder_check_default.log:6`), both pins
  matched with the hazard assert PASS (`evidence/qwen9b/ov/n124_S1D_reorder_check_default.log:8-9`),
  B6 PASS, state diff [], 530.1 s (`evidence/qwen9b/ov/n124_S1D_reorder_check_default.log:21`),
  `REORDER CHECK: PASS` and no `board` line anywhere. **Wall time 539 s**
  (11:58:18 → 12:07:17, `evidence/qwen9b/ov/n124_S1D_reorder_check_default.log:1`, `evidence/qwen9b/ov/n124_S1D_reorder_check_default.log:24`) —
  the per-session cost the default now carries.
* §5 is unchanged by the flip: **no chip-TB run of form B's per-image order**
  is still not established; it is the next task (S1T). *(done 2026-09-27: S1T,
  `evidence/qwen9b/ov/S1T_FORMB_IMAGE_TB.md`; short context only, its §3)*

**Made model-aware 2026-09-27 (S1D fix round 1)** — appended; the bullets
above record the flip as first shipped. Unset, "B" refused every non-9B or
`--nch 1` run at exit 4, which broke the O3 lock gate's `chat_seq.py` row
and the 2B path; the controller ruled the default must be model-aware. Now
`--reorder` parses to a sentinel, and `effective_reorder()`
(`sw/chat_seq.py:798`, called in `main()` at `sw/chat_seq.py:6996`, before
`--selftest` and before any gate) resolves it: an explicit `--reorder` or a
set `$FABLE5_REORDER` is used as given (an explicit form that cannot run
still refuses at exit 4); with neither, **auto → "B" only at
`FABLE5_MODEL=9b --nch 4` on the shipped template**, else None — the
shipped order — with one log line saying why. Everything from the
`if args.reorder or args.reorder_check` test on is unchanged. Evidence:
RED `evidence/qwen9b/ov/n132_S1Dfix1_formB_tdd_RED.log` (47/2) → GREEN
`evidence/qwen9b/ov/n136_S1Dfix1_formB_tdd_GREEN_committed.log` (56/0, on
the committed tree); `chat_seq --selftest`
`evidence/qwen9b/ov/n137_S1Dfix1_chat_seq_selftest_committed.log` (407/1,
the same [22]); `evidence/qwen9b/bm/n91_S1Dfix1_reorder_tdd_committed.log`
(14/0); the re-proof at the model-aware default,
`evidence/qwen9b/ov/n135_S1Dfix1_reorder_check_default.log` (auto → B, pins,
hazard PASS, B6 EXACT 535.6 s, **545 s wall**, no board); and the O3 gate's
`chat_seq.py` row green again, `evidence/qwen9b/ov/n138_S1Dfix1_o3_chat_seq_row.log`
(15 passed / 0 failed).

## 5. NOT ESTABLISHED

* **One board session of form B**, at one prompt, ctx 511, `--ntok 9`. The
  run-to-run spread comes only from the paired per-position ratios, not from
  repeated sessions. There was no `--prefill full` T-curve and no sampled
  decode.
* **The static table is fitted at positions 0..5.** ATTN's +39 cycles per
  position is extrapolated to 511. The layer's F1 wait on KV SLDs, which grow
  with T, is **not modelled**: the stall rule covers only the 6th-in-a-run
  enqueue. Deep-context costs only steer the schedule, never its safety. But
  the modelled ×1.146 is not a prediction at ctx 511, and it was not
  confirmed there (measured ×1.1254 full).
* **`REORDER_B_POS = 0`.** The images are scheduled at position-0 costs
  (`sw/chat_seq.py:647`). Whether a deeper pricing position gives a better
  order at long contexts was not tried.
* **B6 replays the images at positions 0 and 1 in emitter space.** The mapped
  LDC patch is checked at positions 300 and 510 only by byte-equality
  (patch∘reorder == reorder∘patch). The replay does not run there.
* **No chip-TB (Verilator) run of the form-B chat images.** Their evidence is
  the model gate, the hazard assert, the postcheck, and silicon tokens on one
  prompt. *(2026-09-27: still not established after the default flip to B;
  task S1T is that run.)* Note: `chat_seq --model-only` at 9B `--nch 4`
  now models the form-B images **without** the B6 gate (documented in
  `docs/USAGE.md` §3, boardless) — it is not that run.
  **2026-09-27 (Task S1T): DONE on the chip TB** — the chat tool's own
  form-B lite/full images (pins matched), record-following patch, 4 chat
  scenarios × {shipped, B}, 5 launches each incl. last positions 86/300/510,
  on the SV1 binary: 8/8 PASS, tokens IDENTICAL, full ×1.1454 / lite ×1.1598,
  the full image within ±0.009 % of SV1's form-B template token
  (`evidence/qwen9b/ov/S1T_FORMB_IMAGE_TB.md`; what it does not cover: its §3).
* **Channel-3 DDR contention under B** was not counted. build_041 has no B16
  counters. T4 measured it only for A, on the BM1 roll.

## 6. PROVENANCE AND DISCLOSURES

* **Commits:**
  * `97a06e1`: `seq_cost` + fit script.
  * `06ebccd`: `--cost`.
  * `a907438`: n86.
  * `e2ce068`: RED test.
  * `2ce1136`: chat_seq B + switch + USAGE.
  * `c049f9f`: board evidence.
* **`REORDER_B_GATE_LOG` was written after n89 ran.** It names n89, and it is
  a string constant: it changes no image byte. The board session n95
  re-derived the pins and re-ran B6 on the committed tree.
* **n80 is a draft fit, kept.** The same fit, with the table comparison, is
  n83.
* **n90 is chat_seq's selftest at `FABLE5_MODEL=9b`.** It fails in the frozen
  nch=1 template check, identically at the pre-S1P base (n93). The selftest
  targets the default model: n91 and n92.
* **One accidental `python3` invocation on darthplagueis.** It was an empty
  heredoc, so nothing executed and nothing numeric ran. It happened while
  appending to the fit script.
* **The T4 suite's T2b is inverted (fix round 1, M5).** It asserted "form B
  refused (B7)", which S1P lifts; it now asserts form B is admitted, and the
  suite is 14 passed, 0 failed
  (**E**, `evidence/qwen9b/bm/n87_S1Pfix1_reorder_tdd.log:34`).

### 6.1 Fix round 1 (review of 641cb3c..910a4a4)

* **I1** — §4 now states the switch reaches `sw/chat_seq.py` only;
  `sw/serve.py` and `sw/cycle_census.py` always run the shipped order.
* **I2** — form A regenerates at the static costs; the pin still matches with
  the CSV unreadable (**E**, `evidence/qwen9b/ov/n100_s1p_reorderA_nocsv.log:26`;
  superseded by `evidence/qwen9b/ov/n113_final_reorderA_nocsv.log:23` at HEAD, §6.2).
* **M3** — `s1p_compare.py` now asserts the FULL sha256 of both paths'
  output against the committed reordered manifests: s1 B `57ec3051…`, s1 A
  `b6ced3f9…`, s2 B, s2 A all PASS
  (**E**, `evidence/qwen9b/ov/n101_s1p_static_vs_csv_pins.log:54`,
  `evidence/qwen9b/ov/n101_s1p_static_vs_csv_pins.log:79`).
* **M4** — the switch is case-insensitive and read at parse time;
  importing chat_seq with a bad value no longer fails, the CLI refuses it.
* **M1/M2** — comment and cite corrections (8 position LDCs at 9B; E1 rows
  15-41).
* Re-runs: `s1p_formB_tdd.py --slow` 43 passed, 0 failed (was 39; +4 M4
  checks) (**E**, `evidence/qwen9b/ov/n102_s1p_formB_tdd_fix1.log:114`);
  chat_seq `--selftest` still 407/1, the same pre-existing [22]
  failure (**E**, `evidence/qwen9b/ov/n103_s1p_chat_seq_selftest_fix1.log:52`).

### 6.2 Final fix (whole-branch review of c948466..1e591cf)

The fix-round-1 re-runs above ran on `910a4a4+dirty`, before their citing
commit; the final fix re-ran all five on the committed tree `ba9ba4f` (code
commit C1–C3; each log's `+dirty` list holds only the untracked
`evidence/qwen9b/bm/` entries, no modified tracked file). Each result equals
its predecessor except for wall-clock seconds and the new checks.

* **C1** — `ref/seq_cost.py` refuses an unknown MOVY mode with
  `StaticCostError` (was a raw `KeyError`); its docstring lists which classes
  refuse and which extrapolate (`ref/seq_cost.py:36`). `StaticCostError` was
  already an `AssertionError` subclass, so both reorder paths already turn it
  into their refusal.
* **C2** — a bad `$FABLE5_REORDER` is refused echoing what was typed.
* **No-CSV proof of form A** — n100 → **n113**: regenerated == pinned
  `b6ced3f9…`, 0 CSV reads, PASS
  (**E**, `evidence/qwen9b/ov/n113_final_reorderA_nocsv.log:20-23`).
* **Full-sha pins, static vs CSV** — n101 → **n114**: s1 B, s1 A, s2 B, s2 A
  all PASS (**E**, `evidence/qwen9b/ov/n114_final_static_vs_csv_pins.log:49`,
  `evidence/qwen9b/ov/n114_final_static_vs_csv_pins.log:74`,
  `evidence/qwen9b/ov/n114_final_static_vs_csv_pins.log:96`,
  `evidence/qwen9b/ov/n114_final_static_vs_csv_pins.log:112`).
* **Form-B TDD `--slow`** — n102 → **n115**: 45 passed, 0 failed (43 + the
  two new checks, T2 C2 and T8) (**E**,
  `evidence/qwen9b/ov/n115_final_formB_tdd.log:111`).
* **chat_seq `--selftest`** — n103 → **n116**: 407 passed, 1 failed, the same
  pre-existing [22] failure (**E**,
  `evidence/qwen9b/ov/n116_final_chat_seq_selftest.log:45`,
  `evidence/qwen9b/ov/n116_final_chat_seq_selftest.log:47`).
* **The T4 reorder suite** — bm/n87 → **bm/n88**: 14 passed, 0 failed, at a
  clean `ba9ba4f` stamp (**E**, `evidence/qwen9b/bm/n88_final_reorder_tdd.log:2`,
  `evidence/qwen9b/bm/n88_final_reorder_tdd.log:27`).
