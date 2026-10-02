# HISTORY — NEXT_SESSION archive (newest first)

Session entries moved out of NEXT_SESSION.md on 2026-08-12, so the
cold-resume file stays short. Everything below is VERBATIM as it was
written at the time: this is a LOG, not maintained truth. Board state,
bitstream names, blockers and "NEXT options" in these entries are almost
all superseded — for current state read NEXT_SESSION.md, for the as-built
ISA/CSR truth read docs/SEQ_ISA.md (v1.7), for what each rung delivered
read evidence/<rung>/*_GATE.md, and for the throughput arc read
docs/SPEEDUP_LADDER.md.

**2026-09-14 (Task 16, G7 — the 9B ship).** The ship moved the WHOLE
2026-09-09 … 2026-08-11 stack out of `NEXT_SESSION.md` into this file,
VERBATIM and newest first, exactly the way 2026-08-12 did — nothing deleted,
nothing edited, including the "Open options (pick with user)" section those
entries fed. `NEXT_SESSION.md` now carries the post-ship state alone. The
2026-09-09 G6 entry at the top of this file is superseded by that state, not
by anything in here.

~~The two newest entries (2026-08-12 rung 4, 2026-08-11 chat template)
stayed in NEXT_SESSION.md and are NOT duplicated here.~~ — no longer true as
of 2026-09-14: both are here now, with everything after them.

**2026-09-27 (NS1 — after the NVFP4 study, SD1 and the overlap campaign
`c948466..03b4f86`).** `NEXT_SESSION.md` was brought to the truth at HEAD
after the board lost power (snoke's unclean reboots of 2026-09-18…20) and was
recovered on 2026-09-27. Every piece of it that stopped being current moved
here VERBATIM — the entry "2026-09-27: moved out of NEXT_SESSION.md at NS1"
at the top of the entries below — and nothing was deleted.

**2026-09-29 (SR9 — the sequencer RTL round's docs pass, after the R1 and R2
board sessions SR8 and SR15).** The two §1 tables those sessions replaced
moved here VERBATIM — the entry "2026-09-29: moved out of NEXT_SESSION.md at
SR9" at the top of the entries below — and nothing was deleted.

**2026-09-29 (SR17 — the sequencer RTL round's close).** The round's ladder
table was written here (entry "2026-09-29: the sequencer RTL round's close —
SR17", the newest), and the `NEXT_SESSION.md` text SR17 replaced (§7's
2026-09-27 answers row, §8's heading and its round-status paragraph, §9 (a)
12's opening and (f) 11) moved into the same entry VERBATIM — nothing was
deleted.

### Standing supersessions (appended, never edited into the entries)

This file is a log, so the entries below are left exactly as written. Where a
later ruling closed something one of them left open, it is recorded here.

- **2026-09-01 — the "flock retrofit" follow-on is CLOSED.** Two entries carry
  it as an open item: `2026-08-11` (*"follow-ons: flock retrofit into
  infer/seq_run/tok_meter"*) and `2026-08-10` (*"serve.py left RUNNING on
  snoke:8137 … holds sw/.seq.lock. NEVER run infer.py/seq_run/tok_meter while
  it's up (they don't take the lock)"*). They are superseded by **user ruling
  O3, 2026-08-29**: one NFS-visible lock,
  `/home/cah/r2d2/code/fpga/.fable5_board.lock`, owned by `sw/board_lock.py`,
  taken by **every** tool that programs or DMAs the board and held across the
  whole `remove` → JTAG → `rescan` sequence. Two things in those entries are
  now wrong rather than merely stale: `sw/.seq.lock` is not the lock any more
  (it was per-checkout, and never excluded the second working tree — which is
  how the R-b gate took an unattributed reprogram), and the named tools *do*
  take the lock. See `docs/USAGE.md` §5 and
  `evidence/qwen9b/o3/BOARD_LOCK.md`.

---

## 📦 2026-09-29: the sequencer RTL round's close — SR17 (the round's ladder; and the text moved out of NEXT_SESSION.md, verbatim from `ac302a1`)

**The round, 2026-09-27 → 29** (spec
`docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md`, plan
`docs/superpowers/plans/2026-09-27-seq-rtl-round.md`, the close
`evidence/qwen9b/sr/SR17_ROUND_CLOSE.md`). R1 (the FENCE channel mask) and R2
(the XWIN/RES bank bits) were built, signed off with no waiver, and run on
silicon for one session each with every token identical; build_041 was
restored after each and is resident. R3 (MOVX broadcast) was decided on
paper by SR16; the user's ruling is pending at this entry.

**The ladder — MEASURED on silicon, every rung tokens IDENTICAL.** Chat = the
chat511 decode step (full image, context 502..510, per launch); stream = the
6-token `model_9b_s1` form-B census (per token); FENCE = the C5 FENCE-wait
share of the stream.

| rung | where | chat full ms | **chat tok/s** | stream ms/token | **stream tok/s** | FENCE % |
|---|---|---|---|---|---|---|
| shipped order | build_041 (chat, n68); build_042_bm1 (stream, n72) | 147.7088 | **6.770** | 137.1195 | **7.293** | 41.96 |
| S1 form B (software) | the R2 bitstream, r0 (n1506, n1511) | 131.2479 | **7.619** | 120.5367 | **8.296** | 38.50 |
| R1 (SR3 / SR7 / SR8) | the R2 bitstream, r1 (n1507, n1510) | 126.1135 | **7.929** | 114.3885 | **8.742** | 35.12 |
| **R2** (SR12 / SR14 / SR15) | build_045_r2_incr, r2 (n1508, n1509) | **122.2175** | **8.182** | **110.4066** | **9.057** | **32.78** |
| R3 form (a), expected (MODEL-derived) | — | — | *8.70–8.77* | — | *9.70–9.83* | — |
| R3 form (b), expected (MODEL-derived) | — | — | *8.57–8.63* | — | *9.54–9.64* | — |

Sources: the measured rows `evidence/qwen9b/sr/SR15_R2_BOARD.md` §3.1, §3.2
(its board table `evidence/qwen9b/sr/n1516_sr15_board_table.log:18-19`,
`evidence/qwen9b/sr/n1516_sr15_board_table.log:30-35`,
`evidence/qwen9b/sr/n1516_sr15_board_table.log:89`,
`evidence/qwen9b/sr/n1516_sr15_board_table.log:92-94`,
`evidence/qwen9b/sr/n1516_sr15_board_table.log:100`), transcribed as
`evidence/qwen9b/sr/SR16_R3_DECISION.md` §1 does; the R1 rung on its own
bitstream (SR8: chat 7.929, stream 8.742) is `evidence/qwen9b/sr/SR8_R1_BOARD.md`
§3; the R3 rows are SR16's expectations, `evidence/qwen9b/sr/SR16_R3_DECISION.md`
§1 and §5 — MODEL-derived, not measured. Per rung on the same bitstream, chat
full: S1-B → R1 ×1.0407, R1 → R2 ×1.0319; R2 against build_041's shipped order
×1.2086 (`evidence/qwen9b/sr/SR15_R2_BOARD.md` §3.1).

**Moved VERBATIM from `NEXT_SESSION.md` at `ac302a1`** (SR17 replaced each; the
replacement is in `NEXT_SESSION.md` at the same place):

From §7, the 2026-09-27 row (SR17 quoted the Q2/Q4/Q5/Q6–Q8/Q9 answers in full from the ledger):

| **2026-09-27** | **The SR0 spec's nine §7 questions, ANSWERED:** Q1 YES — an MMCM compute-clock domain (+ CDC in the two SmartConnects) MAY be added, but only if a build cannot close at 250 MHz (the explicit OK the FPGA-level single-clock rule requires); Q2 moot under Q1's condition; Q3 OK — a UI (DDR4) cut up to ~5 % to close R2 if the MIG accepts the period and the DIMMs calibrate, never a full grade; Q4 YES (R1 first, R2 its own build, R3 from silicon); Q5 YES (step 0 first); Q6/Q7/Q8 at the spec's defaults (R3 form (a) if taken; keep the BM1 counters; no RTL interlock); Q9 each round bitstream needs its own ruling (`.superpowers/sdd/2026-09-27-seq-rtl/progress.md`, USER ANSWERS 2026-09-27; gitignored, cited by path and date) |

From §8, the heading:

    ## 8. OPEN USER DECISIONS — **ONE pending user ACTION (the push) + the sequencer RTL round's next decision, R3** (updated 2026-09-29, SR9)

From §8 item 3, the round-status paragraph:

   **The round's status (SR9, 2026-09-29): R1 and R2 are built, signed off and proven on silicon; neither is resident — build_041 is, and every session restores it.** The chat decode ladder at context 502..510 is 6.770 (shipped order) → 7.619 (form B) → 7.929 (r1) → 8.182 (r2) tok/s, and the 6-token stream census 7.293 (shipped order, n72) → 8.296 (form B) → 8.742 (r1) → 9.057 (r2) tok/s, tokens identical at every rung (`evidence/qwen9b/sr/SR15_R2_BOARD.md` §3.1, §3.2). **The next decision is R3** (MOVX broadcast, spec §1.3, the plan's SR16): the decision document is evidence/qwen9b/sr/SR16_R3_DECISION.md (in flight at SR9 — read it for the options and the recommendation; the user rules). Whether R1 or R2 becomes the resident default is a separate, still-open decision (the plan's open decision 3); until it is taken, build_041 stays resident.

From §9 (a), item 12's opening:

12. **OPEN — the round's next decision (§8):** the R3 decision document is
    evidence/qwen9b/sr/SR16_R3_DECISION.md (SR16, in flight at SR9); the
    user rules. As written before the round:

From §9 (f), item 11:

11. **BACKLOG (SR17 or a tooling task) — `evidence/qwen9b/o3/o3_cite_drift.py
    --verify` must refuse an unresolvable `--doc-base` and fail on 0
    citations when lines moved**: SR15's n1523 accepted the bogus base
    "WORKTREE", read 0 citations and printed a vacuous PASS
    (`evidence/qwen9b/sr/SR15_R2_BOARD.md` §6); **and the inherited
    spec_cites baseline script scores 0 base keys when a listed file is
    missing at the base** (n1526, same section) — it fails safe but misleads.
    Until fixed, read every `--verify` log's citation count.

From the pointer table and the Key invariants (two one-word staleness fixes,
recorded for completeness): `the six ledgers named in §7` → seven;
`` `docs/SEQ_ISA.md` (v2.1) `` → the header's v2.3 noted beside it.

---

## 📦 2026-09-29: moved out of NEXT_SESSION.md at SR9 (verbatim — §1's replaced values, from `a4cf5e6` and `2c66d67`)

Each table below is exactly as `NEXT_SESSION.md` §1 carried it at the commit
named above it. On 2026-09-29 the R1 board session (SR8) and then the R2
board session (SR15) each re-derived §1 from its own logs' stamps and updated
the table row by row; the values each one replaced were left in git only,
not moved, until SR9 moved them here under NS1's convention. The paragraphs
that name each re-derivation, and the NS1 power-loss paragraph, stay in
`NEXT_SESSION.md` §1.

**From §1 — the table as at `a4cf5e6` (the 2026-09-27 NS1 values).**
Superseded on 2026-09-29 by SR8's re-derivation: SR8 loaded the R1
bitstream build_044_r1_incr for one session, restored build_041 and
re-uploaded the pack; its restore sanity `n812` became the last DDR writer
(`evidence/qwen9b/sr/SR8_R1_BOARD.md`).

| | |
|---|---|
| **bitstream** | `build_041_ckr2_AltSpreadLogic_high`, **VERSION `0xc973c18a`**, JTAG-volatile, CALIB `0xF` — **re-programmed 2026-09-27 after the power loss, same `.bit`, same sha**: 07:12:20–07:15:27, `PROGRAM_OK` + `rescan OK: 82:00.0 … Device 9038` under one lock hold (`evidence/qwen9b/bm/n65_T4_program_shipped_041.log:13`, `evidence/qwen9b/bm/n65_T4_program_shipped_041.log:16`); replaced by build_042_bm1 07:28–07:29 for the measurement (§3); **restored 07:42:28–07:43:36** (`evidence/qwen9b/bm/n75_T4_restore_041.log:13`, `evidence/qwen9b/bm/n75_T4_restore_041.log:16`). Read back off the silicon last at 09:01:47, `VERSION 0xc973c18a` / `CALIB 0x0000000f` / `IDENT: PASS` (`evidence/qwen9b/ov/n94_s1p_ident_041.log:19`, `evidence/qwen9b/ov/n94_s1p_ident_041.log:20`, `evidence/qwen9b/ov/n94_s1p_ident_041.log:25`), and again by `n95`'s bring-up (`evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:37`). **The idle counters are NOT on it**: BM_IDENT reads `0xdeadc0de` (`evidence/qwen9b/ov/n94_s1p_ident_041.log:24`) |
| **the .bit** | `synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper.bit`, **53,074,589 bytes**, 2026-09-07 20:46:01 (`evidence/qwen9b/g5/G5D_TIMING.md` §9.2) — sha256 `eeeef897495d783a…` (`evidence/qwen9b/g6/RD9_GATE.md` §2.1), the hash BM1-T4 recorded for the file it programmed (`evidence/qwen9b/bm/BM1_BOARD_IDLE.md:211`) |
| **weights** | the **`model_9b_s1`** pack — 249 images + the embedding, **5,842 MiB — RE-UPLOADED.** The ship-time "not one weight byte re-uploaded since `028`" is **FALSE now**: DDR survives neither the power loss nor a reprogram. Cold upload by `n68`, 347.1 s, readback-verified (`evidence/qwen9b/bm/n68_T4_control_041_chat511.log:16`); again after each of the two reprograms (`n71`, and `n77` below). **Last written by `n77`, 07:43:42–07:44:23**: 47 witness misses → all 249 + the embedding re-uploaded in 29.4 s, readback-verified (`evidence/qwen9b/bm/n77_T4_restore_chat_sanity.log:14`, `evidence/qwen9b/bm/n77_T4_restore_chat_sanity.log:16`). `n95` found it resident, 0 MISS, upload SKIPPED (`evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:40`). The whole-pack sha256 of `017` §8 was **not** re-taken; every upload is per-piece readback-verified |
| **stream** | **NOT `model_9b_s1.e4` any more.** The last writer uploaded `chat_seq`'s three step images, **form-B reordered** — preamble at `0x9000000`, lite at `0x9000280` (38,378 records), full at `0x9096140` (39,146 records) (`evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:29`, `evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:23`, `evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:24`) — plus the const blob, 8,940,032 B (`evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:27`); blob + images 9,942 KiB readback-verified (`evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:46`) |
| **state region** | geometry unchanged — base `0x3_8000_0000` on **DDR channel 3**, **162,529,280 B**, DN / KV / CV as `evidence/qwen9b/g6/RD9_GATE.md` §6 — **contents `n95`'s**: DN zeroed and the 24 conv images written at bring-up (`evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:41`, `evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:42`), reset again at the preamble (`evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:51`), then 511 forward steps |
| **the three base CSRs** | `SB_DN=0x38000 SB_KV=0x38180 SB_CV=0x38980`, read back by `n95` (`evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:43`) |
| **EMBLOG2** | **13** — `evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:38` |
| **last lock holder / last DDR writer** | **`n95`**, 2026-09-27 **09:01:54 → 09:11:56** (`evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:1`, `evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:97`) — `chat_seq --reorder B` through `evidence/qwen9b/bm/bm1_chat511.sh`, holding the shared lock for its lifetime (`evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:62`). **Nothing after it touched the board**: every later log under `evidence/qwen9b/ov/` (`n96` onward) and `evidence/qwen9b/bm/n87_S1Pfix1_reorder_tdd.log` / `evidence/qwen9b/bm/n88_final_reorder_tdd.log` are a table, a TDD, a selftest (its lock case uses a private `.seq.lock.selftest` file), `spec_cites`, or NS1's read-only `board_lock.py --status` query, by its own `=== cmd` line |
| **last forward step** | **`n95`** — 512 launches (1 preamble / 502 lite / 9 full), context **511 of 511** (`evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:74`, `evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:79`) — so the KV region holds `n95`'s 511 rows and TCNT is `n95`'s. Its tokens were IDENTICAL to the pinned reference, checked fail-closed (`evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.log:94`) |
| **lock** | free — `state not held`, identity empty, at 10:07 on 2026-09-27 (`evidence/qwen9b/ov/n107_ns1_readonly_status.log:21`, `evidence/qwen9b/ov/n107_ns1_readonly_status.log:22`) |
| **hw_server** | **running on snoke** since the 07:08 reboot — pid 10107, `hw_server -d -s tcp::3121`, started by the controller (overlap ledger, 2026-09-27) and seen by a read-only `pgrep` at 10:07 (`evidence/qwen9b/ov/n107_ns1_readonly_status.log:25`) |
| **host thermals** | **unchanged — still no later number.** The only `sensors` read on record is `001`'s, taken BEFORE anything was programmed on 2026-09-09: `Package id 1: +59.0 °C` (`evidence/qwen9b/g6/RD9_GATE.md` §15). No run since — the overlap campaign's and the recovery's included — read them, and none is stated here |

**From §1 — the table as at `2c66d67` (SR8's 2026-09-29 values).**
Superseded later on 2026-09-29 by SR15's re-derivation: SR15 loaded the R2
bitstream build_045_r2_incr for one session, restored build_041 and
re-uploaded the pack; its restore sanity `n1514` became the last DDR writer
(`evidence/qwen9b/sr/SR15_R2_BOARD.md`).

| | |
|---|---|
| **bitstream** | `build_041_ckr2_AltSpreadLogic_high`, **VERSION `0xc973c18a`**, JTAG-volatile, CALIB `0xF` — **restored 2026-09-29 by SR8**: 04:36:00–04:37:09, re-hash `eeeef897…` matched, `PROGRAM_OK` + `rescan OK: 82:00.0 … Device 9038` under one lock hold, rc 0 (`evidence/qwen9b/sr/n810_sr8_restore_041.log:8`, `evidence/qwen9b/sr/n810_sr8_restore_041.log:19`, `evidence/qwen9b/sr/n810_sr8_restore_041.log:24`); read back at 04:37:13, `VERSION 0xc973c18a` / `CALIB 0x0000000f` / SEQ_CAPS `0xdeadc0de` / `IDENT: PASS` (`evidence/qwen9b/sr/n811_sr8_ident_041_restored.log:8`, `evidence/qwen9b/sr/n811_sr8_ident_041_restored.log:9`, `evidence/qwen9b/sr/n811_sr8_ident_041_restored.log:14`, `evidence/qwen9b/sr/n811_sr8_ident_041_restored.log:16`). Before it, 04:00:14–04:36, the **R1 bitstream build_044_r1_incr** (VERSION `0xe3c2ff1e`, SEQ_CAPS `0xfab1ca01`) was resident for the SR8 session only (`evidence/qwen9b/sr/n803_sr8_program_r1.log:17`, `evidence/qwen9b/sr/n804_sr8_ident_r1.log:16`). Earlier history (the 2026-09-27 re-program after the power loss, BM1's swap) is the NS1 paragraph above. **The idle counters are NOT on build_041**: BM_IDENT reads `0xdeadc0de` |
| **the .bit** | `synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper.bit`, **53,074,589 bytes**, 2026-09-07 20:46:01 (`evidence/qwen9b/g5/G5D_TIMING.md` §9.2) — sha256 `eeeef897495d783a…` (`evidence/qwen9b/g6/RD9_GATE.md` §2.1), the hash BM1-T4 recorded for the file it programmed (`evidence/qwen9b/bm/BM1_BOARD_IDLE.md:211`) |
| **weights** | the **`model_9b_s1`** pack — 249 images + the embedding, **5,842 MiB — RE-UPLOADED after each of SR8's two reprograms** (DDR does not survive one): on R1 by `n805`'s four `seq_run`s (105.3 s cold for s1, `evidence/qwen9b/sr/n805_sr8_r1_lockstep_s1s4.log:43`), and on build_041 **last by `n812`** (04:37:25–04:46:53, after its B6 gate): 48 witness misses → all 249 + the embedding re-uploaded in 29.5 s, readback-verified (`evidence/qwen9b/sr/n812_sr8_restore_chat_sanity.log:27`, `evidence/qwen9b/sr/n812_sr8_restore_chat_sanity.log:29`). The whole-pack sha256 of `017` §8 was **not** re-taken; every upload is per-piece readback-verified |
| **stream** | **`chat_seq`'s three step images, form-B reordered (r0)**, written by `n812`: preamble at `0x9000000`, lite at `0x9000280`, full at `0x9096140` (`evidence/qwen9b/sr/n812_sr8_restore_chat_sanity.log:15`), plus the const blob; blob + images 9,942 KiB readback-verified (`evidence/qwen9b/sr/n812_sr8_restore_chat_sanity.log:36`) |
| **state region** | geometry unchanged — base `0x3_8000_0000` on **DDR channel 3**, **162,529,280 B**, DN / KV / CV as `evidence/qwen9b/g6/RD9_GATE.md` §6 — **contents `n812`'s**: DN zeroed and the 24 conv images written at bring-up, reset again at the preamble (`evidence/qwen9b/sr/n812_sr8_restore_chat_sanity.log:31-32`, `evidence/qwen9b/sr/n812_sr8_restore_chat_sanity.log:41-42`), then 42 forward steps. The KV tail beyond row 42 was not written since the restore (DDR does not survive a reprogram; the RTL never reads a KV row before writing it) |
| **the three base CSRs** | `SB_DN=0x38000 SB_KV=0x38180 SB_CV=0x38980`, read back by `n812` (`evidence/qwen9b/sr/n812_sr8_restore_chat_sanity.log:33`) |
| **EMBLOG2** | **13** — `evidence/qwen9b/sr/n812_sr8_restore_chat_sanity.log:26` |
| **last lock holder / last DDR writer** | **`n812`**, 2026-09-29 **04:37:25 → 04:46:53** (`evidence/qwen9b/sr/n812_sr8_restore_chat_sanity.log:1`, `evidence/qwen9b/sr/n812_sr8_restore_chat_sanity.log:89`) — the n77 prompt through `evidence/qwen9b/bm/bm1_census.py --chat --want-ids`, `FABLE5_SEQ_EXPECT_VERSION` unset, default form B, holding the shared lock for its lifetime (`evidence/qwen9b/sr/n812_sr8_restore_chat_sanity.log:52`). **Nothing after it touched the board**: `n813` is a table from JSONs and `n816` a read-only status query |
| **last forward step** | **`n812`** — 43 launches (1 preamble / 18 lite / 24 full), context 42 (`evidence/qwen9b/sr/n812_sr8_restore_chat_sanity.log:66`, `evidence/qwen9b/sr/n812_sr8_restore_chat_sanity.log:71`); its 24 ids were IDENTICAL to `n77`'s, checked fail-closed (`evidence/qwen9b/sr/n812_sr8_restore_chat_sanity.log:86`) |
| **lock** | free — `state not held`, identity empty, at 04:50 on 2026-09-29 (`evidence/qwen9b/sr/n816_sr8_readonly_status.log:9`) |
| **hw_server** | **running on snoke** since the 2026-09-27 07:08 reboot — pid 10107, `hw_server -d -s tcp::3121` (`evidence/qwen9b/sr/n816_sr8_readonly_status.log:12`); SR8 used it for both JTAG programs |
| **host thermals** | **unchanged — still no later number.** The only `sensors` read on record is `001`'s, taken BEFORE anything was programmed on 2026-09-09: `Package id 1: +59.0 °C` (`evidence/qwen9b/g6/RD9_GATE.md` §15). No run since — the overlap campaign's and the recovery's included — read them, and none is stated here |

**From §8 — its heading and the open list of the SR0 spec's nine §7 questions** (as at
`544ee30`). Superseded on 2026-09-29 by SR9: the user answered the nine on
2026-09-27 and gave the per-bitstream Q9 rulings on 2026-09-29 (§7's dated
rows), and §8 now names the round's next decision, R3. The heading line is
fenced so it does not read as an entry of this file; its text is unchanged.

```text
## 8. OPEN USER DECISIONS — **ONE pending user ACTION (the push) + the sequencer RTL round's open questions (SR0 spec §7: nine, each with a default)** (2026-09-27)
```

**OPEN — the sequencer RTL round's questions**
(`docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md` §7; cited by §,
because that spec's own fix round may re-word Q2/Q3/Q9 — read §7 there for
the current text). Each has a default the spec assumes if the user says
nothing:

* **Q1** a new compute clock domain if a build misses 250 MHz? — *default:
  no new clock this round; a miss comes back with numbers.*
* **Q2** what is a "small" clock hit? — *default: moot under Q1's default
  (no aclk knob this round); if Q1 is yes, accept up to 5 %, ask beyond.*
* **Q3** a UI (DDR4) clock cut to close the UI clocks? — *default: a cut
  up to ~5 % by the model grid (the 5 % point is above R1-at-full, the 10 %
  point below; ~7 % is a linear interpolation, not a grid result), if the
  MIG permits it and the DIMMs calibrate; never a full grade.*
* **Q4** option 2 (R1, then R2 as its own build; R3 later)? — *default:
  yes.*
* **Q5** run Step 0, the incremental probe on build_042_bm1, first? —
  *default: yes.*
* **Q6** R3's implementation, if taken later: push bus (a), staging buffer
  (b) or splitter (c)? — *default: (a).*
* **Q7** keep the BM1 counters in the round's netlists? — *default: yes.*
* **Q8** keep the pending-channel hazard emitter-enforced (no RTL
  interlock)? — *default: no interlock.*
* **Q9** does the −0.124 roll's measurement waiver (§3) cover the round's
  silicon sessions if a round netlist also misses? — *default: no; each
  round bitstream needs its own ruling.*

**From the top paragraph, §8's closing paragraph and §9 (e) item 1 — the three
"open now" sentences** (as at `544ee30`), each now naming the R3 decision
instead of the nine questions:

```text
Later on 2026-09-27 the user settled §8's five open items (§7): **form B is
now the chat default** at 9B `--nch 4` (Task S1D), the sequencer RTL round is
GO (spec SR0, §8 item 3); open now are the push — the user's action — and the
SR0 spec's nine §7 questions (§8).

emptied the list at that date; the five items above (opened 2026-09-24 and
2026-09-27) were all settled on 2026-09-27. **Open now: the push (a user
action) and the SR0 spec's nine §7 questions**, listed above. The ruling is in

1. **The darthplagueis memtest — DECIDED 2026-09-15: NO MEMTEST.** The host is
   retired from numeric work permanently. **§8's five were all decided on
   2026-09-27; open now are the push (a user action) and the SR0 spec's
   nine §7 questions, each with a default** (§8); the NVFP4 decision is
   DECIDED (2026-09-24, keep shipped).
```

**From §3 and §6 — the build_042_bm1 refusal of the four direct-CSR tools**
(as at `544ee30`; false since `fa7f5df`, SR11a fix round 3, which gave
hwmap its row). §3's sentence, then §6's table row:

```text
reverse holds too: a stale variable naming BM1 on build_041 refuses. **And
never run `sw/tok_meter.py`, `sw/infer.py`, `sw/layer_test.py` or
`sw/matvec_test.py` while build_042_bm1 is loaded** — `sw/hwmap.py` has no row
for it, so they raise `UnknownBitstream` (fail-safe, not usable). Source for
those two sentences: the overlap ledger, BM1-T4prep review entries dated
2026-09-24/25.

| `sw/tok_meter.py`, `sw/infer.py`, `sw/layer_test.py`, `sw/matvec_test.py` | VALID | **REFUSE** (`UnknownBitstream`; `sw/hwmap.py` has no row for `0x9b588e78`) | fail-safe; a row would be a follow-on (§9 (b)) |
```

---

## 📦 2026-09-27: moved out of NEXT_SESSION.md at NS1 (verbatim, as it stood at `03b4f86`)

Each block below is exactly as `NEXT_SESSION.md` carried it at `03b4f86`. The
line above each block says which section it came from and what replaced it.
Two heading lines are fenced so they do not read as entries of this file;
their text is unchanged.

**From §1 — the ship-time "what is on the board" paragraph and table**
(re-taken at Task 15's close). Superseded by §1's 2026-09-27 re-derivation:
the board lost power, build_041 was re-programmed, the pack was re-uploaded,
and the last DDR writer is now S1P's form-B chat session.

From `evidence/qwen9b/g6/RD9_GATE.md` §15, **re-taken from the logs' own
timestamps** at Task 15's close. §15's own standing lesson: *a heading that
says "now" has to be re-derived from the logs' timestamps, not from whichever
round last edited the section* — it was mislabelled three rounds running.

| | |
|---|---|
| **bitstream** | `build_041_ckr2_AltSpreadLogic_high`, **VERSION `0xc973c18a`**, JTAG-volatile, CALIB `0xF` — **unchanged since `002`** (`evidence/qwen9b/g6/RD9_GATE.md` §15). Read back off the silicon last at `evidence/qwen9b/g6/148_15d_verify_head.log:18` |
| **the .bit** | `synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper.bit`, **53,074,589 bytes**, 2026-09-07 20:46:01 (`evidence/qwen9b/g5/G5D_TIMING.md` §9.2) — sha256 `eeeef897495d783a…`, which G5D does not carry and `evidence/qwen9b/g6/RD9_GATE.md` §2.1 does |
| **weights** | the **`model_9b_s1`** pack — 249 images, 3,902 MiB + the 1,940 MiB embedding, per-piece verified; whole-pack sha256 `602b008c70fd8aec…` as verified at `017` §8. **Not one weight byte re-uploaded by any rung since `028`** (§15) |
| **stream** | `model_9b_s1.e4`, 158,536 records at `0x9000000`; the const blob at `0xc000000` is 8,940,032 B (4,096 positions × 2,048 B), last written by `148` (§15) |
| **state region** | base `0x3_8000_0000` on **DDR channel 3**, **162,529,280 B** total: DN `0x380000000`..`0x381800000` (24.00 MiB), KV `0x381800000`..`0x389800000` (128.00 MiB), CV `0x389800000`..`0x389b00000` (3.00 MiB) — `evidence/qwen9b/g6/RD9_GATE.md` §6 |
| **the three base CSRs** | `SB_DN=0x38000 SB_KV=0x38180 SB_CV=0x38980`, 64 KiB units, read back on every run (§6) |
| **EMBLOG2** | **13** — `evidence/qwen9b/g6/148_15d_verify_head.log:19`, `EMBLOG2    13 (8192 B embedding rows)` (§15) |
| **last lock holder / last DDR writer** | **`148`**, 2026-09-10 **19:33:17**, the `chat_seq --verify-head` attempt: its bring-up re-zeroed DN and re-wrote the 24 conv blocks and the blob, then it **refused before any launch** (§15) |
| **last forward step** | **`141`**, 19:22:54 — 447 launches, context 446 — so **the KV region holds `141`'s 446 rows over the long run's 526**, and TCNT is `141`'s. A context reset does not clear KV; rows beneath the top are the deeper session's and TCNT is what makes them unreadable (§15) |
| **lock** | released; the shared lock is free (§15) |
| **host thermals** | the only `sensors` read this campaign holds is `001` §6's, taken BEFORE anything was programmed: `Package id 1: +59.0 °C`. **No rung after `001` read them** — there is no later number, and none is stated here (§15) |

**From §3 — its old heading.** A third bitstream, the measurement-only
build_042_bm1, joined the table on 2026-09-27; the heading now says THREE.

```text
## 3. TWO BITSTREAMS, ONE BOARD — the operational note
```

**From §7 — its old opening.** Three more ledgers are cited since the ship
(the NVFP4 study, SD1, the overlap campaign).

From the three ledgers. **All three are gitignored** — they exist in the
working tree only, so they are cited by path and date, never by line:

* `.superpowers/sdd/2026-08-25-qwen-next-derisking/progress.md` (the pre-campaign D's)
* `.superpowers/sdd/2026-08-29-qwen35-9b-migration/progress.md` (Tasks 1–16)
* `.superpowers/sdd/2026-09-04-qwen35-9b-state-spill/progress.md` (S1–S5, 14/14-A/14-B, 15)

**From §8 — the old heading and list.** The NVFP4 decision was taken on
2026-09-24 (keep the shipped W4 g128 + A8); the list is now five items.

```text
## 8. OPEN USER DECISIONS — **TWO** (2026-09-24)
```

1. **The NVFP4 simulation study's decision** (2026-09-24): the §8.1 blank in
   `docs/NVFP4_STUDY.md`, choosing among the options in its §7. The
   recommendation is withheld.
2. **The commit-trailer rewrite before the push** (2026-09-24): 37 rung-0/1
   commits of the NVFP4 study carry an Opus trailer instead of the mandated
   one (ruling C9 in the study's gitignored ledger).

**From §9 (e) — item 1**, whose "no user decision is open" stopped being true
on 2026-09-24.

1. **The darthplagueis memtest — DECIDED 2026-09-15: NO MEMTEST.** The host is
   retired from numeric work permanently and **no user decision is open**.
   §8 above.

**From "Pointers a cold session needs" — two rows.** The decision trail is now
six ledgers, and the NVFP4 decision is taken.

| you want | read |
|---|---|
| the decision trail | the three ledgers named in §7 — **gitignored, working tree only** |
| the NVFP4 simulation study (2026-09-23/24) — recommendation withheld, §8.1 decision pending | `docs/NVFP4_STUDY.md`; ledger `.superpowers/sdd/2026-09-23-nvfp4-study/progress.md` (gitignored) |

---

## ✅ 2026-09-09: **G6 PASSED — THE 9B RUNS ON THE FPGA.** build_041 is RESIDENT

- **PROGRAM THIS (it is already resident):**
  `synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper.bit`
  (53,074,589 B, 2026-09-07 20:46:01, sha256 `eeeef897495d783a…`).
  **VERSION CSR = `0xc973c18a`, READ BACK OFF THE SILICON**
  (`evidence/qwen9b/g6/003_identity_9b.log`), CALIB **0xF** on the first read,
  MAGIC/layer/matvec0-3/SEQ IDENTs all OK. JTAG-volatile, `--no-lock` never
  passed, no flash. Rollback if ever needed:
  `synth/out_build_035_fp2a_exc_po/bd_wrapper.bit` (54,072,409 B,
  2026-08-24 23:13:19, sha256 `58b06450f8f9b258…`) — note the path is NOT
  under `proj/stage1.runs/impl_1/`.
- **Board resident now:** build_041 (`c973c18a`) + the **`model_9b_s1`**
  weight pack (249 images / 3,902 MiB + the 1,940 MiB embedding), per-piece
  verified, **whole-pack sha256 `602b008c70fd8aec…`**; stream
  `model_9b_s1.e4` at `0x9000000`; the DDR state region at `0x3_8000_0000` on
  **channel 3** with `SB_DN/KV/CV = 0x38000/0x38180/0x38980`; EMBLOG2 **13**.
  **No rung has re-uploaded one byte of the pack since `028`** — every chat
  session, the Task 15-D bisect included, read
  `1122 witness blocks … 0 MISS` and `upload SKIPPED`. **The state region is
  as Task 15-D left it on 2026-09-10, and the last WRITER and the last
  RUNNER are different runs** (`evidence/qwen9b/g6/RD9_GATE.md` §15,
  re-taken 2026-09-14): **`148`** (19:33:17, the `--verify-head` attempt) is
  the last run that held the lock and wrote DDR — its bring-up re-zeroed DN
  and re-wrote the 24 conv blocks — but it refused before its preamble and
  ran **no launches**, so the **KV region holds `141`'s 446 rows over the
  long run's 526** (`141`: 447 launches, context 446). A context reset does
  not clear KV, so rows 446..525 beneath the top are the previous, deeper
  session's and TCNT is what makes them unreadable. **An earlier revision of
  this bullet said "22 rows", which was `110`'s count and was stale by
  thirteen board sessions.** **The 2B pack is GONE.** The 2B stream no longer runs on this netlist at
  all (`err_op` on its first CONVW — plan U4, demonstrated).
- **What G6 established** (`evidence/qwen9b/g6/RD9_GATE.md`): all four model
  seeds produce **exactly** `evidence/qwen9b/g4/G4A_REPLAY.md` §4.1a's tokens — 24 tokens, zero
  mismatches — with **36,886 post-halt state checks ALL MATCH** on each; the
  DDR state region reads back **BIT-EXACT** against the emitter's
  `state_final.bin` (`7bd38ff095ad91a0…`), all 162,529,280 B, no carve-outs;
  **7.2928 tok/s** (gate, 137.1210 ms/token) / **7.2917 tok/s** (steady-state,
  one loop iteration timed on chip); the two lanes separated for the first
  time — `L_LCYC` **41.588 ms/token** (8.9 % better than S4's 45.674, 9.7 %
  better than Task 12's 46.079; **like-for-like it is 9.9 % below Task 14-A's
  own chip-TB census with the holds charged, 46.161 — and the delta is NOT
  ATTRIBUTED**, `evidence/qwen9b/g6/RD9_GATE.md` §10.2a) beside `L_SDMA_CYC` **5.125 ms/token**
  (which REPLACES the modelled 5.133); residual clip rail **observed**: 28 words at
  +32767 of 40,882 non-zero, `|x|max` = 32767, at `rs_f = 7` (Q8.7), so the
  Step-5 free rider did **not** remove clipping.
- **CHAT RUNS AT 9B** (fix round 2 — see the G6 FIX ROUND 2 bullet below).
  `FABLE5_MODEL=9b sw/chat_seq.py --nch 4` is the path; `--nch 1` is the
  frozen 0.8B/2B one and stays that way. `docs/USAGE.md` §3 "Chat at 9B" is
  the how-to.
- **FOUR DEFECTS FOUND ON HARDWARE** (`evidence/qwen9b/g6/RD9_GATE.md`
  §14): (1) ~~the conv witnesses are not a residency invariant across a
  run~~ **RETIRED in fix round 2** — the conv witnesses are out of the weight
  pack's probe and are re-taken after the state upload, so a healthy board
  now reads `0 MISS` and `upload SKIPPED` instead of re-uploading 5.8 GiB
  (§14.1, `078`); (2) `--skip-weights` leaves the DDR state region dirty and
  the next run answers with the **wrong token** at `err_code 0x00` —
  **half-addressed**: `chat_seq` writes the initial region itself now,
  `sw/seq_run.py --skip-weights` is unchanged and the defect stands there;
  (3) **nothing ties the resident weight pack to the resident MODEL** —
  running `chat_seq` with its default template re-uploaded the 2B pack over
  the 9B one and the identity gate passed throughout (STILL OPEN; the
  per-model template pin makes the wrong-template case harder to reach but
  does not tie the PACK to the model); (4) `SCRATCH_WORDS_BUILT` was a silent
  half-clear (fixed here: 65,536).
- **The SIGHUP ruling (ledger:269) was MEASURED AND DECLINED**, and
  `sw/program_fpga.sh` / `sw/stage1_hw_bringup.sh` / `sw/test_ctl.sh` are UNCHANGED.
  On bash 5.2.21 the EXIT trap already runs for an untrapped SIGHUP: with the
  committed line the rescan runs in **0.003 s** and the caller sees **rc 129**;
  adding `HUP` defers it to **7.003 s** (the whole foreground command) and the
  caller sees **rc 0** — a hung-up reprogram reporting SUCCESS.
  `evidence/qwen9b/g6/RD9_GATE.md` §13, logs `013`/`014`/`015`.
- **A next session that wants §4.1a's tokens must re-establish the initial
  state region first** — `evidence/qwen9b/g6/g6_state.py --write-initial`, or
  a full `seq_run` without `--skip-weights`. See defect (2).
- **G6 FIX ROUND 1 (2026-09-09), no reprogram, no DDR byte written**
  (`evidence/qwen9b/g6/RD9_GATE.md`, logs `054`-`067`): the plan's **nch=1 rung RUN** — nch is a
  property of the artifact, all 25 9B artifacts under `tb/scripts/w9/` and
  its `emit2/` repeats are nch=4 (the tree is gitignored — `.gitignore:36`;
  the twelve more under `rep10/`/`probe/` were read by review and are too),
  and an
  nch=1 9B pack is REFUSED by the address map (3,902 MiB against a 1,280 MiB
  window) on the resident manifest (§4.2, `054`); **EMBLOG2 proved WRITABLE**
  by writing 12, reading back 12 and restoring 13 — the plain readback of 13
  could not distinguish a write from the reset value, which is also 13 (§9.2,
  `055`); the layer-term delta made like-for-like and left UNATTRIBUTED
  (§10.2a); the user's gate-port clamp ruling recorded (§12.1); the
  "launched detached" claim WITHDRAWN as untranscribed and the SIGKILL
  residual stated (§13.1); the chat block re-scoped (§20). **The `spec_cites`
  in-scope pair was FAIL 8 BEFORE this task and FAIL 8 after** — the earlier
  "31 → 8" was an artifact of running the base check in a detached worktree
  (23 EXIST misses on untracked/gitignored paths); the eight are pre-existing
  QUOTE drift and are an **explicit ledgered exception** deferred to the
  pre-ship doc chore (§19, §19.1).
- **G6 FIX ROUND 2 (2026-09-09/10) — THE 9B CHAT PATH, BUILT AND RUN. No
  reprogram, no weight byte written** (`evidence/qwen9b/g6/RD9_GATE.md` §8,
  logs `071`-`086`). **Greedy chat answers correctly on 9B silicon**:
  *"The capital of France is \*\*Paris\*\*."*, 24 tokens, decode
  **137.7 ms/step = 7.26 tok/s** steady state (`078`). **Sampled chat on 4
  seeds**: two runs of one seed byte-identical, two other seeds different,
  OUT FIFO clean on all four (`079`) — the path is right; `--temp 0.8`
  itself produces poor prose and the gate says so. **`chat_seq --verify`:
  22 of 22 steps `== seq_model`, 0 divergences** (`080`, 44 m 48 s of host
  time). **The chat template re-verified against the 9B checkpoint's OWN
  `chat_template.jinja`** (`075`): with `enable_thinking` left unset the 9B
  jinja opens a `<think>` block — the 4B/9B inversion, caught in the act —
  and with `enable_thinking=False` all three pinned id lists reproduce
  EXACTLY; `chat_seq` splices the closed-empty block by hand and matches
  regardless. **LONG CONTEXT RAN: 526 forward steps** (503-id prompt + 24
  tokens), the KV region read back holds **row 525** where it held nothing
  before, three runs token-identical, `L_SDMA_CYC` **5.788 ms/step** and
  70.51 MiB/token of state traffic at that T (`083`, `084`). **What changed
  in the tools**: the 4-chan template pin is per `FABLE5_MODEL` (9b →
  `tb/scripts/w9/model_9b_s1.e4`, the S4 artifact its own SEQ gate passed at
  `024` — no re-emission); the session and its `ref/seq_model` verifier both
  get the DDR state region; the context reset restores the conv taps;
  `T_MAX` 512 → **4,096** (per model selection after fix round 3);
  `--pos-mode xrf` is REFUSED where the geometry cannot reach the context,
  in the tool AND in the verifier. **Two caveats to carry.** (1) **The
  long-context rung's per-step token lockstep was NOT run**: `ref/seq_model`
  costs 131.2 s / 149.3 s of host time per 9B step (`074`), so 526 steps is
  **19.3 h** — the scope had budgeted an hour from a 2B figure. It needs no
  board and can be detached. **Fix round 3 launched it** — see below.
  (2) **`L_LCYC` and `L_SDMA_CYC` are 32-bit and a chat-length session WRAPS
  them** (§14.5, new): 2³²/250 MHz = 17.18 s of busy time; the long run's
  `L_LCYC` read 13.4 ms/step where the same instrument reads 40.573 ms/step
  on a 43-launch session (`086`). Every §10 number is safe (one ~823 ms
  program); nothing longer is.
- **TASK 15 IS COMPLETE (2026-09-14). The long-context divergence is
  RESOLVED — NEITHER SIDE HAS A DEFECT — and the long-context LOCKSTEP is
  ESTABLISHED. `106` ran the reference at the wrong `RS_F`**
  (`evidence/qwen9b/g6/RD9_GATE.md` §22, §22.10-§22.12b; logs `127`-`175`).
  **THE VERDICT, in one sentence:** the long-context lockstep is ESTABLISHED
  at the derived operating point — `149` `LONGCTX_LOCKSTEP: PASS 504/504`
  (2 decode) and `171` `LONGCTX_LOCKSTEP: PASS 526/526` (24 decode,
  positions 502..525, the chip's token rank 1 in the reference at every
  step); `106`'s FAIL was the reference at `RS_F` 8 (§22.11), and
  `evidence/qwen9b/g6/RD9_GATE.md` §8.7a is superseded.
  **`149` is `LONGCTX_LOCKSTEP: PASS 504/504`**: replaying `128`'s own
  503-token session, the reference produces **`[760, 20438]`** — the chip's
  own two tokens — and at the step `106` called a divergence its top two are
  `20438:82490` and `3177:80962`, **1.8523 % apart, with `20438` FIRST**.
  The chip's token is rank 1 in the reference's own logits at **all eighteen
  decode steps** of the bisect, at N = 53, 113, 263, 383, 443 **and 503**.
  **Why `106` said `3177`** (§22.11, `162`): it launched 2026-09-10 00:44 on
  tree `2762662`, where `ref/layer_fixed.RS_F` still defaulted to **8**.
  `Mach.conv` — the CONV opcode the replay executes,
  `ref/gen_layer_script.py:1041` — is `rshr(acc, RS_F + CW_F - 12)`, so
  `106`'s DeltaNet conv output was shifted **9** where
  `rtl/conv4_silu.sv:54` bakes **8** and the artifact's own manifest records
  `rs_f: 7`: 24 layers x 504 steps = **12,096 wrong shifts**. `28fac0b`
  ("RS_F is DERIVED from MS.TAG, not remembered", #26) landed at 04:51:37,
  four hours after `106` started and thirteen before it finished, and Python
  binds a module constant at import. **Every other file in the replay's
  execution path is byte-identical between the two trees** (`162`). Decode 1
  survived the perturbation at a 14.68 % margin; decode 2, at 1.85 %, did
  not. **§8.7a's reading of `106` is superseded by §22.11.**
  `161`: **`dn_sha256 SAME`** chip-vs-reference at N = 503 — 24 MiB of
  DeltaNet state byte for byte — and the lowest differing KV row is **504**,
  which is TCNT.
  **H1 ("the chip attends over at most 7 KV blocks past 448 rows") was also
  tested statically and REFUTED** (§22.10's table, no runs): the emitted
  schedule carries no T at all (128 KV transfers per step at every context,
  the census's own 224 minus the 96 DN/conv ones), and every T-dependent
  quantity is a runtime read of `tcnt_bank`, 13 bits, dimensioned 4,096. The
  only quantity that changes at 448 is the KV exponent side array's
  `ceil(T/64)` beat count — correct on both sides, differing only in DDR
  bytes at and above TCNT that no reader reads.
  **THE NEXT ACTIONS** (§22.12, in order) — **A′ IS DONE, B′ IS IN FLIGHT**
  (§22.12a, 2026-09-11). **A′ LANDED**: `evidence/qwen9b/run.sh` now prints
  the DERIVED operating point on its own header line, not just
  `FABLE5_RS_F=unset` (which records the absence of an override and not the
  value in force) — `=== rs_f: derived=7 (tag 9b) env=unset rider=0`, the law
  `RS_F_BY_TAG[model_select.TAG]` imported from `ref/layer_fixed.py` the way
  the tools import it, 0.22 s per run, and it can never fail the wrapped
  command (`unavailable (<reason>)` on any error). Three wrapped `true`s on
  snoke are its RED/GREEN: `168` GREEN `derived=7 … env=unset`, **`169` RED
  `derived=7 … env=8`** — the disagreement the wrapper PRINTS and the tools
  REFUSE — and `170` `derived=n/a (FABLE5_MODEL unset)`. `168`'s line 9 is
  `106`'s line 9 character for character; line 11 is what now tells them
  apart. **B′ LANDED** (`evidence/qwen9b/g6/RD9_GATE.md` §22.12b):
  `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log`, launched
  2026-09-11 **12:47:07 −06:00** on snoke, **pid 1273730** (now gone),
  detached, `nice -n 10`, tree `e1d0d3a`, board-free — the `083` 24-token
  session, **526 steps** (502 prefill + 24 decode), `106`'s command line
  with `149`'s `--top5 5 --continue --dump-kv 501-506`, header line 11
  reading **`=== rs_f: derived=7 (tag 9b) env=unset rider=0`** with
  `FABLE5_RS_F` UNSET (the derivation proving itself). It finished
  **2026-09-12 06:36:13 −06:00**, `=== rc: 0`, **17.82 h at 121.9 s/step**,
  and its verdict is **`LONGCTX_LOCKSTEP: PASS 526/526`** —
  `decode     24/24 of the chip's tokens reproduced (24 decode steps replayed)`.
  **24 decode comparisons at positions 502..525** (the launch note projected
  23; `--continue` replays them all and the first decode step is 502), every
  verdict `==`, the chip's token **rank 1** in the reference's own logits at
  every one, tightest margins pos 504 (1195) and pos 503 (1528).
  **Fourteen of them, positions 512..525, are at T ≥ 512** — the range
  **`rtl/attn_core.sv:114`'s `logic signed [39:0] denom`** names — and all
  fourteen agree, **so the hazard was NOT live in this session and `denom`
  stays a scheduled post-ship RTL fix. The ceiling stays T < 512 BY
  ANALYSIS**: that is a worst-case bound, and one session's agreement is
  evidence the worst case was not reached, not proof it cannot be. **The
  PASS does not lift the ceiling.** **And the STATE comparison at T = 526 is
  NOT made**: `171`'s `--dump-kv` is the REFERENCE region after step 526
  (`region_sha256 b6a681d7…`, `dn_sha256 38c5da24…`) with no chip readback
  of the whole region at that T to set beside it, so the deepest
  silicon-vs-reference STATE comparison is still `161` at N = 503.
  Still true and unaffected: **`--verify-head` refuses at 9B** (head dequant
  `2^(e_x-18)` vs `2^(e_x-21)`), and T = 447..503 has no comparand.
- **G6 FIX ROUND 3 (2026-09-10) — two tool defects and one board rung**
  (`evidence/qwen9b/g6/RD9_GATE.md` §8.3a, §8.7a, §21; logs `105`-`110`).
  **The two fixes**: the `xrf` refusal is now the GEOMETRY
  (`XRF_POS_MAX < --max-ctx - 1`) on both sides, not the model tag — the
  verifier had no geometry check at all and would have certified an `xrf`
  `--verify` at any selection not literally `"9b"`; and `T_MAX` is per model
  selection (4,096 at 9B on build_041, **512** on the frozen 0.8B/2B path
  whose `kv_waddr` is still `tcnt[8:0]`), so that path's uploaded footprint
  is `4662b06`'s byte for byte again — fix round 2 had grown its position
  pool 786,432 → 6,291,456 B on a path no bitstream here can validate.
  RED `108` (372/8, each FAIL naming its reason) → GREEN `109`
  (`chat_seq 408/0`, `seq_chat PASS`, `seq_run 2785/0`, `hwmap PASS`).
  **The board rung after the edits**: `110`, `--verify` **22 of 22 steps
  `== seq_model`**, `1122 witness blocks … 0 MISS` → `upload SKIPPED`, no
  reprogram, under the lock.

## ✅ 2026-09-08: 9B BITSTREAM CLOSED — build_041 ckr2 (VERSION c973c18a), WNS 0.000 / WHS +0.001, no waiver; Task 15 bring-up is next
- **What closed it, in order of size** (`evidence/qwen9b/g5/G5D_TIMING.md`
  §10.1, and §0's reading rule applies to every number here — T/D/S, every
  Vivado run on snoke through `evidence/qwen9b/run.sh`). **The floorplan was
  worth nothing, by design**: Task 14's first campaign
  (`evidence/qwen9b/g5/G5B_TIMING.md` §4.7) priced pblocks *costing* slack
  monotonically — none −0.247, the layer pblock −0.768, plus the one-SLR ctx
  pblock −1.126, i.e. **−0.879 at the far end** — so 14-B ran every roll with
  `PBLOCK_COUNT: 0` and the placer still put the whole layer in one SLR.
  **The RTL round** (`evidence/qwen9b/g5/G5C_RTL.md`, Task 14-A) is worth
  **+0.091** at matched directive, matched recipe and matched (absent) XDC:
  the scratchpad BRAM cascade capped and three stages split (fx_silu's s2,
  the attention output mux, the DeltaNet output mux) — **bit-exact and
  token-identical**, no re-emission. **The clock root closed it**:
  `synth/constraints/fable5_clockroot_9b.xdc` (USER_CLOCK_ROOT X2Y2, the
  measured centroid) at the SAME directive moved WNS **−0.156 → 0.000**
  (+0.156) and 2,507 → 0 failing setup endpoints, by +0.407 ns of clock skew
  with the data path unmoved. The post-route phys_opt playbook bought
  **+0.000** on both positions.
- **The artifact — and it is NOT programmed** (§9.2, §11):
  `synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper.bit`,
  **53,074,589 bytes, 2026-09-07 20:46:01**, **VERSION c973c18a** (baked in by
  create_project.tcl and read from the build log — **not** read back from
  hardware). Nothing in Task 14/14-A/14-B touched the board and nothing wrote
  flash. ~~**The board still carries build_035_fp2a_exc_po** (VERSION
  54443b9f, the 2B W8 design, CALIB 0xF, its 2B pack loaded and audited), so
  Task 15's first act is a REPLACEMENT that invalidates the resident 2B
  weight pack in DDR.~~ **SUPERSEDED 2026-09-09 by G6**: the readback was
  teed (`evidence/qwen9b/g6/001_etiquette_resident_readback.log` — 54443b9f
  CONFIRMED, uptime 15.83 days), build_041 was programmed, and the 2B pack is
  gone. See the G6 entry at the top.
- **Two watch items, both from §11.** (1) **The margin is zero and it was
  produced once.** WNS 0.000 / WHS +0.001 on one placement; this campaign
  measured **0.512 ns of spread** across six unconstrained rolls of the same
  netlist, and a re-run of the same command is **not** guaranteed to reproduce
  0.000. What is reproducible is the mechanism, not the number: any change to
  the RTL, the constraints or the tool version re-opens the whole gate.
  (2) **USER_CLOCK_ROOT X2Y2 is valid only while the placer keeps the layer in
  SLR0** — three campaigns chose three different dies (S5 SLR1, Task 14 SLR2,
  14-B SLR0), and a set_property that lands in the wrong SLR still *succeeds*,
  so the failure would be silent. It is now mechanically asserted:
  `evidence/qwen9b/g5/g5d_clockroot_check.tcl` on the candidate's routed
  checkpoint, before final_verify — marker CLOCKROOT_SLR_OK and rc 0 (GREEN on
  the shipping checkpoint), CLOCKROOT_SLR_MISMATCH and rc 1 (RED on the first
  campaign's SLR2 roll). Do not ship a roll that fails it.
- **NEXT ACTION — Task 15 (G6, board bring-up), user-approved 2026-09-08**
  (interactive: proceed with 14-B's bitstream, the re-roll-for-reproducibility
  option declined). Run it per the plan's **AMENDED 2026-09-08** block at
  `docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md` Task 15, which
  wins wherever it contradicts the steps beneath it: the safe reprogram flow
  only (pcie_helper remove → program_fpga.sh JTAG-volatile → pcie_helper
  rescan, never flash), then the amended ladder — identity with CALIB 0xF
  before any DMA, dry, nch=1/4, the weight upload verified per PIECE, **the
  new state-region upload** (DN memset with its eight zero witnesses, the 24
  conv images readback-verified, the three SB_* base CSRs read back), EMBLOG2,
  lockstep with its STATE line, chat, and the new long-context rung above the
  old 512-token limit.
- **Open items (none blocking Task 15).** The **darthplagueis memtest
  decision** is still open — the host produced wrong arithmetic twice on this
  campaign (Task 10/11, S3) and stays out of every numeric path until it
  passes a soak, or is retired from the campaign; **the deferred-minor triage happens before merge**,
  together with the whole-branch review (each task's ledger close line lists
  its own deferred items); the **latent un-reset rstn_q/rstn_i registers at
  `rtl/layer_chan.sv:526-531`** are inert on a bitstream (FFs power up 0) but
  real — they are what makes tb_layershim_c RED under random reset init, and
  they belong to a later RTL round, not to bring-up; and **tb_seq_layer does
  not build** (broken, not retired — pre-existing at BASE, TB-only warnings,
  nothing depends on it).
- **Where the state lives.** The migration ledger
  `.superpowers/sdd/2026-08-29-qwen35-9b-migration/progress.md` (Tasks 1–13 of
  `docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md`) and the
  state-spill ledger
  `.superpowers/sdd/2026-09-04-qwen35-9b-state-spill/progress.md` (Tasks S1–S5
  plus 14/14-A/14-B, of
  `docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md`, spec
  `docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md`).
  **Resume from the LAST line of the state-spill ledger.**

## 🔁 2026-09-05: 9B STATE SPILL — S1–S5 CLOSED (token-identical on the DDR-state design; the one-SLR floorplan MET post-place at OOC). Control returns to the migration plan at Task 14.
- **Where the state lives:** the migration ledger
  `.superpowers/sdd/2026-08-29-qwen35-9b-migration/progress.md` (Tasks 1–13
  of `docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md`) and the
  state-spill ledger `.superpowers/sdd/2026-09-04-qwen35-9b-state-spill/progress.md`
  (Tasks S1–S5 of `docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md`,
  spec `docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md`).
  Resume from the LAST line of the state-spill ledger.
- **Why the amendment exists:** Task 13 (`evidence/qwen9b/g5/G5A_FLOORPLAN.md`)
  ran 11 OOC placements of the 928-URAM 9B layer and the best (2′cr) sat at
  WNS −0.554 with the DN write fan-out at −0.001 — floorplanning alone could
  not close it. **USER DECISION (2026-09-03/04):** DN state, the KV cache
  (T ≤ 4,096, per-kvhead) and the conv weights/state all move to DDR behind
  two-slot URAM caches (DN 2×29, KV 2×58, conv 2×4 = **182 URAM**, one SLR),
  a 512-bit AXI4 `rtl/state_dma.sv` on the 250 MHz layer clock, two layer
  opcodes SLD(13)/SST(14), fences F1/F2 — sequencer-scheduled (approach A).
- **S1–S4 closed** (ISA v2.1 §B15; RTL with `tb/tb_layer_sdma.sv`; the chain
  with a StateImage/StateRegion lockstep; the replay). **S4 is the acceptance
  bar and it is met** (`evidence/qwen9b/s4/S4_REPLAY.md`): the four 9B model
  streams re-emitted on snoke under an emit-twice gate, `SEQ GATE: PASS` ×4
  with `STATE BIT-EXACT`, the whole model on the chip-level TB decodes
  **Task 11's tokens on 4 of 4 seeds** and runs 1.70 % fewer cycles; the
  compute-lane layer term 45.674 ms/token vs Task 12's 46.079 (exactly the
  DNST RLAT delta); the DMA lane 5.133 ms/token is MODELLED (LAT 8), not a
  board figure; F1 0, queue-full hold 1.05 %, the spec's F2 fence 0 on the
  shipped schedule (its counter fires on a perturbed arm).
- **S5 CLOSED — the structural gate PASSED** (`evidence/qwen9b/s5/S5_STRUCT.md`):
  the counts STOP **fired at 174**, eight short, and the eight were exactly the
  conv slots, whose two memories carried no `ram_style` where the DN and KV slot
  memories carried `(* ram_style = "ultra" *)`; the controller ruled the RTL
  follows the approved spec, and the re-count is **182 URAM from BOTH OOC
  harnesses**. On that netlist the whole layer places **inside SLR1 with 0
  SLLs** and **MEETS post-place: WNS +0.030 (Default) / +0.034
  (`AltSpreadLogic_medium`), TNS 0.000, zero failing endpoints** — and §0's
  reading rule is not softened by a positive number: **OOC success is NECESSARY,
  NOT SUFFICIENT** (`layer_chan` alone on the die; the STOP-back of spec §12
  risk 1 did not fire). The floorplan Task 14 starts from is
  `synth/constraints/fable5_floorplan_9b_1slr.xdc`, whose header states the
  in-context rewrite. **Handoffs to Task 14:** the `ATTN_DSP` residual (the KV
  slot read into the attention DSPs); `SDMA` — the ledger's close line names
  **+0.001**, which is round 1's 174-URAM figure, and `evidence/qwen9b/s5/S5_STRUCT.md` §4.4 has
  it at **+0.203 / +0.087** on the shipped 182 netlist, "still the family to
  watch when Task 14 adds context"; and **DSP 1,838 of 2,280 = 80.6 % of SLR1**,
  the tight resource. Then the migration plan's Task 14 (full build, timing
  closure per the playbook — read its **AMENDED 2026-09-05** block first),
  Tasks 15–16 (board bring-up, chat).
- **Rules learned this campaign (hard):** every emission/reference/Verilator
  run ON SNOKE — darthplagueis produced wrong arithmetic twice (Task 10/11,
  S3) and stays out of numeric paths until it passes a memtest soak
  (**open user decision**: schedule the memtest or retire the host from the
  campaign); `make -C tb w9_9b_model_script W9_EMIT2=1` is the emit-twice
  gate (repaired in S4 — it could not fire on the model target before);
  `evidence/qwen9b/g4/run_g4a_replay.sh` refuses a tracked `LOGDIR`; never
  `git add` a directory a run is writing into; `spec_cites.py` LAST as a
  commit holding only its log; the drift tool cannot tell a sha-pinned
  citation from a live one (inspect `--plan`).
- **Before merge:** a whole-branch review and the deferred-minor triage
  (each task's ledger close lists its deferred items; the census TB's
  comments, Task 12's stale census runner, the drift tool's sha-pin gap).

## 📋 2026-08-25: NEXT-MIGRATION FEASIBILITY STUDY — 4B and 9B, both, no pick
- **USER DECISION (2026-08-25, interactive): study BOTH Qwen3.5-4B and
  Qwen3.5-9B first, then pick at a gate.** The study is
  `docs/QWEN35_NEXT_FEASIBILITY.md`; evidence + every derivation script under
  `evidence/qwen_next/feas/` (f01..f17, all run ON SNOKE through
  `evidence/qwen_next/feas/feas_run.sh`). **It picks nothing — §8 is the open decision.**
- **THE FINDING: neither target is a width scale-up.** Both change the head
  geometry IDENTICALLY — DeltaNet **16 -> 32 value heads** (key heads stay
  16), attention **8 -> 16**, KV **2 -> 4**, layers **24 -> 32** (24 DN + 8
  GQA), CONV_DIM **6144 -> 8192**. Read off the safetensors headers, not
  config.json. So the layer-state banking becomes a **device capacity**
  problem: **928 of 960 URAM (96.7 %), three SLRs** — the same at BOTH
  targets, and the study's #1 risk. ~~**Whether the VU9P PLACES at that
  occupancy is unknown** (no synthesis, no placement run): 928 URAM cannot fit
  in fewer than three SLRs, so the 2048-bit DN bank-mux read path must cross
  BOTH SLR boundaries every access, inside the one block build_035's floorplan
  had to leave unconstrained. Reachability is conditional on that.~~
  **UPDATED 2026-08-25 (Track P ran D3 — `evidence/qwen_next/place_exp/`):**
  **the study was RIGHT and Track P refined it.** Its sharp form named the
  exact net that fails, and that net fails. Synthesis gives **exactly 928
  URAM**, and `place_design` **SUCCEEDS** (312/312/304 of 320 per SLR, no
  error), so the question is now measured rather than open. Two refinements:
  the crossing is **one** boundary per access, not both (the placer centres
  the mux destination), and the regression is **route** (+2.12 ns), not
  **logic** (−0.06 ns). At the as-built read-path structure the named net is
  **−1.848 ns** where the as-built geometry **meets at +0.211** in the same
  flow, and the module's actual worst endpoint is a net the study never
  named — the **write-control fan-out**, at −2.103.
  **But the read path is FIXABLE**: two register stages on the crossings (FFs
  only, ~1.0 % of the device, URAM unchanged) take the named net to **+0.097
  MET** under `AltSpreadLogic_medium` (the same build at the Default directive
  is −0.162, so the MET carries a directive dependency). The blocker is then
  the write fan-out, one logic level and ~96 % route — a **floorplanning**
  problem, and **no floorplan was tried**, so 96.7 % is **neither demonstrated
  live nor dead**. The latency price is two-sided too: the N=1 structure costs
  ~0.15 % but does not close (−0.339); the N=2 structure that reaches MET needs
  a wait state in `dn_step`'s 5-state pass-2 loop (**≈ +10 %**) or an unpriced
  two-outstanding restructure. **Nothing was routed.**
  **Routing was never run.** The live URAM answer is the **int8 DN state**:
  580 URAM with a write-combining register (592 without one, and it stays in
  URAM either way), measured WNS **−0.119** under `AltSpreadLogic_medium`.
  Its **fidelity cost is still unmeasured**.
  **13 of 17 wall rows are shared**, so the second target after the first is
  far cheaper than its standalone cost; **both targets hit 13 of the 14
  distinct walls**, just different ones.
- **Where they differ, and it cuts both ways:** 9B is cleaner on power-of-two
  — H=4096 keeps vecnorm and the EMB shift EXPRESSIBLE (not working: vecnorm
  still `$fatal`s above N=2048 and needs one more doubling of every width R-b
  widened once), where **H=2560 is expressible only by adding a reciprocal
  multiply** to `vecnorm_unit` (N is a shift AND 1/N is folded into the rsqrt
  binary point) and 5120-B emb rows are refused. 4B is cleaner on scratch:
  **36,384** vs 32,768 with only the MLP body over, and a 2-way gate/up chunk
  gives **24,608 (spare 8,160)**; 9B needs **50,208** with ALL THREE bodies
  over — its 2-way chunk is still **over by 1,056** — so the 16-bit scratch
  ISA, and **no 16th address bit exists anywhere in the arg words**.
- **Modelled tok/s** (nch=4, steady-state; ONE figure per target, ±10 % layer
  allowance in brackets): 4B **7.76** (7.51-8.02) W8 / **10.14** (9.73-10.59)
  W4 g128; 9B **5.11** (4.99-5.23) W8 / **7.21** (6.98-7.47) W4 g128, against
  the 2B's measured **16.52**. That is 0.47x/0.61x for 4B and 0.31x/0.44x for
  9B; 4B is **1.52x** the 9B at W8 and **1.41x** at W4 g128.
- ⚠ **The model's two weaknesses, both stated in the doc:** (1) the optimistic
  layer bracket an earlier draft carried is **RETRACTED** — `rtl/dn_step.sv`
  is ONE instance doing ONE head per command (~1300 cyc/head, 128 lanes fully
  occupied) and `gen_layer_script.py:954-961` loops over heads, so 16->32
  heads doubles a SERIAL loop; the real 0.8B stream census confirms 288 DNST
  commands/token = 18x16 (`f16`). (2) **r = 1.1037 is OUTSIDE** MOVER_NORM's
  calibration-free bracket once that bracket is re-anchored on R-d's 15.128
  layer term (it becomes r <= 1.0851); and the model over-predicts the nch=1
  step — its only out-of-sample test — by 1.7-3.1 %. Absolute tok/s carry a
  few per cent of unmodelled configuration dependence; the 4B-vs-9B
  comparison does not.
- **DDR:** 4B W8 fits at 80.4 % of the window; **9B W8's refusal is an ADDRESS
  MAP limit, not capacity** — the board holds 9,626 of 16,384 MiB, and a
  per-channel runtime EMB_BASE costs **0.055 %** of throughput. But it leaves
  the embedding channel at **exactly 100.0 % full** (256 W_BASE + 1,900
  weights + 1,940 table = 4,096 MiB) — zero slack, which the whole-board
  58.8 % figure hides.
- **Tokenizer byte-identical across all four models** (the pinned PPL corpus
  and its 24,528 positions carry over unchanged) but the **chat template is
  NOT**: 4B/9B invert the `enable_thinking` default.
- **Campaign cost, from the MEASURED 2B ladder** (`f17`): the five committed
  snoke points total **5,810.5 s = 96.8 min**, so the fidelity ladder is
  **3.61 h (4B) / 7.68 h (9B)**; both targets with GPTQ is 73.4 GiB of the
  94 GB free, leaving ~21 GB. Two corrections got here: the first draft mixed
  a darthplagueis CUDA anchor with a snoke one (snoke is **2.814x** slower on
  the same point), and the second anchored all four variants on V5 — the
  CHEAPEST of the five, since W8 is a plain rescale while V1/V2 grid-search and
  V4gptq runs a full Hessian. Variant spread is **3.82x**; anchoring on V5 ran
  **2.11x** low. D2's conclusion survives: hours of snoke against a multi-build
  RTL campaign.
- ⚠ **TWO LIVE DEFECTS ON MAIN, and they are NOT the same severity:**
  **(A, ~~fix now~~ FIXED 2026-08-25, Track F — `2a50cac` `22f7ca8` `d999a54`)**
  `ref/seq_chat.py` at `2a50cac^`, lines 935/936 and 1213-1215, reshaped the
  embedding table at 1024 with a matching `//2048`, so `n*1024` always equals
  `V*H`, it **never raises**, and it silently returned fragments of the wrong
  token's row — wrong at 2B TODAY, offline `--a1`/`--a3` only. Same class as
  RD_GATE §4.2's wrong-token-no-error. The stride now comes from the artifact
  manifest, cross-checked against `2*LR.H` **and** the config's `vocab_size`;
  `--emb-geom` is the regression, run once per model by `--selftest`.
  Its loud twin in the same function (lines 1260-1263 at that same sha,
  §2.10's second row) went with it. Evidence + dated corrections:
  `evidence/qwen_next/defect_a/` (`CORRECTIONS.md` C1-C5).
  **(B, still a migration work item)**
  `sw/infer.py:799-803` hard-codes 1024 on the ONLINE `step()` path — one
  in-repo caller. **Refined 2026-08-25**: "loud" is where it *stops*, not
  where it starts going wrong. `vnw_`/`vn`/`alu` at n=1024 normalize half an
  H-word residual **silently first** — measured at 2B, an unevenly-split
  residual comes back with the DYNQ8 exponent shifted and 99.6 % of the
  leading half changed (max|diff| 99) — and only then does `matvec_y32`
  raise. So the old "not wrong at 2B, fails immediately" reading is wrong:
  it is wrong for three lines, then it crashes.
- The study has been through **three** review rounds. Round 3: 3 findings, none
  touching D1 — the layer census input is gitignored but byte-locked by
  `ref/scripts/regen_gate.sh:41` (relabelled, census unchanged); the ladder
  repricing above; and a throughput band that excluded its own top value.
  Round 1: 47 findings, 22 corrections. Round 2: 17 findings, **5 factual and
  one decision-moving** —
  the retracted layer bracket (above), the r-bracket retraction (above), the
  chunked-scratch peaks, the tie_word_embeddings ground truth (it is `false`
  at TOP level and ABSENT from text_config, so `load_config()` hands the guard
  a dict without the key and **the config guard passes SILENTLY**; only the
  lm_head-tensor guard refuses), and the compute repricing. `git log` from
  b254009.
- NEXT ACTION: **the user's gate** (study §8: D1 which target or neither,
  D2 run the fidelity ladder first, D3 which URAM answer, D4 pad or address
  4B's emb rows). The study states **four** opinions and no more: D2 is the
  highest information per hour; D3's PLACEMENT question should be settled
  before D1 because it can invalidate both targets; defect A should be fixed
  now (**done, 2026-08-25 — see the defect bullet above**); and proportional
  compute scaling is the right direction to err. On the pick itself it states
  nothing.
- **Reviewer verdict after round 3: all prior findings resolved** — the layer
  census reproduced independently, the robustness inference tested and held,
  citations resolve. This is the state the user's decision waits on.

## ✅ 2026-08-25: MERGED — qwen2b is main. The migration is complete.
- **T7 executed**: `main` fast-forwarded ea4d703 -> 2e6ef4a (ff-only held;
  main had not moved since the migration started). The qwen2b branch and
  main are now the same history; this entry is the first commit past it.
- **You are on main, and main serves the 2B.** Board resident:
  build_035_fp2a_exc_po (`54443b9f`), 2B W8 weight pack loaded and
  audited. A model switch (0.8B <-> 2B) is a FULL weight re-upload —
  one pack fits DDR at a time (docs/ARCHITECTURE.md).
  **SUPERSEDED 2026-09-09 by G6: the board carries build_041 (`c973c18a`)
  and the 9B pack; build_035 no longer runs the 2B stream.**
- Full pipeline record: gate D study (docs/QWEN2B_QUANT_STUDY.md),
  V5 plan + ledger (docs/superpowers/plans/2026-08-16-qwen2b-v5-w8.md;
  .superpowers/sdd/ is local-only), gates R-c
  (evidence/qwen2b/rc/RC_GATE.md, TIMING_035.md) and R-d
  (evidence/qwen2b/rd/RD_GATE.md). All six V5 tasks + reviews closed
  clean; R-d passed three review rounds (final: CLEAN, every number
  re-derived from primary sources).
- Open follow-ons (none blocking):
  **memtest darthplagueis** (host produced wrong arithmetic 8x — until it
  passes a soak, numeric compute stays on snoke);
  **board-lock convention** for the shared BCU-1525 (two worktrees, one
  board, no shared lock — sw/.seq.lock is per-checkout);
  scanner legacy-list hard-error; x_mem hole comment class;
  ~~W8 CSR-decode range checks~~ **CLOSED 2026-09-02 by G3.3 (Task 9):
  moot — the W8 engine mode and SHAPE bit 29 are gone from
  rtl/matvec_engine.sv and rtl/matvec_chan.sv (spec 5.1 S5), so there is no
  W8 CSR field left to range-check. What replaced it is a range check on
  the fields that DO remain: sw/hwmap.shape_word now refuses an over-wide
  ng/sh/nrows in BOTH layouts, and evidence/qwen9b/g3/isa_bits.py --shape
  round-trips the word through all six implementations with
  --shape-control as its negative control. The HOST-side W8 law stays
  (spec 3.3) and shape_word(..., isa=1) still packs build_035's word,
  pinned to RD_GATE.md:238;**
  **gate-port widening (POST-SHIP, user ruling 2026-09-09)**: the gate-port
  clamp is ACCEPTED as the production operating point — the reference
  saturates dt_bias to +/-8 (Q3.12) and A to [0, 8) (Q3.15) into
  rtl/gate_unit.sv's ports as built, 61 of 768 heads' decay changed, worst
  68.45 % FS at L12 h18 (evidence/qwen9b/g4/G4B_STRUCT.md 4.2); it was inside
  the G1/A2 fidelity loop and chip and reference model it identically, so no
  bitstream change is needed. Widening the ports (a gate_unit RTL change plus
  a softplus ROM re-derivation, G4B_STRUCT.md 4.3) is a follow-on, and the
  perplexity point (~7 h) was declined for now. evidence/qwen9b/g6/RD9_GATE.md 12.1;
  RD_GATE follow-ons 1-3 (--zero-scratch opt-in vs default,
  whole-pack hash audit ~3 s vs witness sampling, tok_meter 2B pack
  planning); ref/seq_chat.py 2048-B emb rows at two offline call sites;
  benchmark runs per docs/QWEN2B_BENCHMARK.md (branch qwen2b + its
  outputs are the answer key — off-limits to contestants).

## ✅ 2026-08-25: R-d GATE PASSED — **the 2B runs on the FPGA**
- Board: **build_035_fp2a_exc_po (`54443b9f` = VERSION CSR = EXPECTED in
  seq_run/infer)** — **SUPERSEDED 2026-09-09 by G6; both constants now read
  `0xC973C18A`** — CALIB 0xF, no waiver — but **WNS/WHS 0.000 is exactly
  ZERO margin**; R-d's intermittency disposition is 10 repeat sequencer runs
  (six 0.8B, four 2B), tokens identical on all ten, device spread 0.0071% /
  0.0027%. Left resident with the
  **2B W8 weights**: 866/866 weight pieces byte-compared (0 damaged of
  1,847.2 MiB) + 8 sampled emb blocks. `evidence/qwen2b/rd/RD_GATE.md`.
- **0.8B ladder reproduced build_034** — sequencer rungs to <=0.0068%
  (seq_run4 197.685 ms to the microsecond; nch=1 -0.0068%), streaming probes
  to <=0.04% (tok_meter DDR +0.0077%; matvec_test worst channel -0.0398%,
  four-channel spread 0.0364% -> 0.0645%). RD_GATE §1 states each rung
  against its own basis rather than one bound. Tokens bit-exact, 2x7188
  golden checks, lockstep 26/26, canned MATCH, tok_meter4 47.01 device tok/s
  + beats EXACT, matvec 32/32 bit-exact, 4 sampled seeds reproducing
  **034's** texts verbatim — vs 033 the claim stays RB_GATE's deliberate
  prefix match.
- **Qwen3.5-2B W8 (V5) on silicon, first time**: 68,503 records, EMBLOG2 12
  written+read back, 2,819 MiB uploaded and readback-verified,
  **16,404 golden state checks ALL MATCH**, tokens bit-exact, `chat_seq
  --verify` **26/26, 0 mismatch**, greedy + sampled chat coherent
  (*"Paris is not only the capital but also the country's largest city…"*).
  W8 engine mode live on all four engines — **bit 29 set in every SHAPE**:
  ch0/2/3 `0x20800290`, ch1 `0x20200290` (its last MVGO is the smaller
  interleaved head chunk, so only the nrows field differs).
- **Measured 16.139 tok/s** (gate convention) / **16.525** (steady-state) —
  inside the plan's re-anchored 15.5–16.5 band, at its top. Layer term
  re-anchored ON SILICON: 0.8B 15.128 / 2B **17.960** ms/token (same
  `L_LCYC` counter, sequencer path) = **+18.7%**, where the study's geometry
  scaling implied +23.1% (17.4/14.13 = 18.925/15.368 = 1.2314). RD_GATE §3.
- ⚠ **THREE host-side defects found, fixed, gated** (RD_GATE §4) — all from
  two model geometries sharing one board for the first time:
  (1) the `.chip` golden compares words the run never writes against
  `seq_model`'s zeroed memory -> `seq_run.py --zero-scratch`;
  (2) **`chat_seq` ran a whole session on a 61.3 MiB-stale LM head and
  answered with the wrong token, silently** — the residency probe took one
  witness per image per CHANNEL and the head is chunk-interleaved. Now one
  witness per PIECE (proven on silicon, hw_36), and any miss re-uploads the
  whole pack (selftest-proven only — on hardware every miss set was already
  all-187, so that branch never fired);
  (3) `chat_seq` had three 0.8B constants baked in (repacked plan, x8
  address, const-blob size) — all derived from the artifact now.
- NEXT ACTION: **T7 — merge qwen2b -> main** (the gate-D decision authorized
  it AT R-d; `git merge --ff-only`, STOP if main moved).

## ✅ 2026-08-24: T5 COMPLETE — build_035 CLOSED, no waiver. R-d (T6) is next.
- **PROGRAM THIS:** `synth/out_build_035_fp2a_exc_po/bd_wrapper.bit`
  (54,072,409 B, 2026-08-24 23:13). **VERSION CSR = `0x54443b9f`** — this is
  the EXPECTED value for seq_run/infer. Netlist is `54443b9f`: T1's W8 engine
  mode + T4's cfg_len widening; everything since build_035 has been XDC-only,
  so the R-c sim gate and every frozen gate still hold.
- **First bitstream in this project's history needing NO timing waiver.**
  WNS 0.000 / WHS 0.000, **0 failing setup and 0 failing hold endpoints**, all
  six clocks meeting, W8 `xline_q0/CE` cone positive on all four channels
  (+0.077…+0.221). build_034 shipped under a −0.025 waiver; 030/028/026 all
  shipped negative. Signoff independently re-derived from the shipping
  checkpoint: `evidence/qwen2b/rc/t5_21_final_signoff_verify.log`.
- Got there with **no RTL**: four soft pblocks giving each matvec engine its
  own MIG's SLR (`synth/constraints/fable5_floorplan_a.xdc`) plus one
  `set_false_path` (`synth/constraints/fable5_xdma_rst_exception.xdc`) extending
  Xilinx's own reset-synchronizer exception across a scope gap in the vendor's XDC.
  USER DECISION 2026-08-24: closed as a **constraint, not a waiver** (waiving
  −0.004 was declined). Full record: `evidence/qwen2b/rc/TIMING_035.md` §11-13.
- ⚠ **DO NOT expect a fresh re-roll to close.** **No roll ever measured 0.000** —
  the seven place-and-route rolls on that floorplan span **−0.004 … −0.428**,
  fp2a (−0.004) is the best of them, and 0.000 is what a phys_opt pass on
  fp2a's checkpoint reports once the exception is applied. Three of the seven
  carried the exception during implementation and still landed −0.080/−0.231/
  −0.264, so the exception does not rescue a worse placement. Four phys_opt
  directives cannot improve fp2a off 0.000 either. Program the existing
  artifact; if the netlist must ever be rebuilt, budget a multi-roll spread and
  expect several attempts. (TIMING_035.md §13.5.)
- ⚠ Floorplan lesson, the expensive way: constraining `layer_0` in ANY form
  costs ~1 ns (variants B/C: −1.078, −1.148). Constrain the four mvchans only.
- NEXT ACTION: **R-d / T6 — 2B bring-up on hardware** with the bitstream above.
  Safe reprogram flow per CHARTER; expect VERSION `0x54443b9f`.
- Open follow-on (not blocking): `layer_0/u_core/s_axil_rdata_reg[3]/D` is 72%
  logic (2.773 ns of 3.835) — a deep AXI-Lite readback mux, the one endpoint
  in the design that pipelining would actually help. TIMING_035.md §6.

## ✅ 2026-08-16: GATE D DECIDED — V5 (W8 everywhere); merge held until R-d
- USER DECISIONS (2026-08-16, interactive, after the full study
  docs/QWEN2B_QUANT_STUDY.md): (1) operating point = **V5, W8 g128 on all
  matvec weights** (PPL 12.361 = 99% of the W4 gap closed; accepted costs:
  −21..22% tok/s ≈ 16.1–17.0, the W8 engine mode, the per-channel DDR
  repack). The study's V4gptq recommendation was declined in favor of
  maximum quality. (2) qwen2b→main merge HELD until the R-d gate, per the
  spec's original sequencing (the final whole-branch review's merge-now
  recommendation was declined; NOTE for anyone on main: the board runs
  THIS branch's bitstream and main's tooling refuses it).
- NEXT ACTION: write the post-D plan (spec §Decision gate D: "a V4/V5 pick
  opens W8 engine mode first"): W8 engine mode in matvec_engine per
  evidence/qwen2b/q2/v4_v5/W8_SKETCH.md (NB: rewrites the block holding
  the worst 24 waived endpoints — timing re-opens; the sketch's widths
  are derived, the lane array is the unpriced synthesis question), the
  per-channel weight repack (plan_weights/wbase_of are nch-independent
  today — V4_V5.md §5; incl. ILV-head chunk rebasing), then R-c (2B W8
  artifact chain + torch golden + audit) and R-d (2B bring-up). GPTQ is
  NOT part of V5 (W8's 1.03% residual makes it marginal — study §2b);
  the GPTQ calibration wiring stays in the tree, unused by this path.
- Whole-branch state: 63 commits, all task+final reviews clean, tree
  clean. Follow-ons list: study §9 + RB_GATE follow-ons + TIMING §7
  (memtest darthplagueis leads; board-lock convention; reroll_impl
  phys_opt; launch_reroll rsync; layer-term re-anchor rolls into the
  post-D plan's projections).

## ✅ 2026-08-16: R-b HW GATE PASSED — build_034 is the resident bitstream
- Board: **build_034_po2_AltSpreadLogic_high (4f908df2 = VERSION CSR =
  EXPECTED in seq_run/infer)**, CALIB 0xF, EMBLOG2 11 (reset, 0.8B).
  Ships at WNS −0.025 / WHS +0.001 under the user waiver in
  evidence/qwen2b/rb/TIMING.md §6.
- The FULL 0.8B ladder reproduced build_033 to ≤0.025%: seq_run 278.797 ms
  (46.47 gate / 45.02 steady), seq_run4 197.685 ms (32.95 gate = **30.35
  tok/s** / 31.50 steady = 31.74), tokens bit-exact, 2x7188 golden checks,
  lockstep 26/26 0 mismatch, chat4 canned MATCH, sampled 4242 x2 identical
  (same text as build_033's record) / 4243 differs, tok_meter4 47.01 device
  tok/s + beats EXACT. evidence/qwen2b/rb/RB_GATE.md.
- Waiver watch items ALL CLEAN: **no measurable ch2 penalty** (matvec_test
  4 seeds x 2 runs x 4 chans = 32/32 bit-exact, 8/8 on ch2; four channels
  within 0.0364% by mean cycles); dn_step + seq_0 MOV covered by the
  bit-exact envelope, 0 mismatches.
- NOTE: the bitstream replaced was NOT build_033. The VERSION readback that
  said so (0x4b15b576) was never tee'd to a log and the corroborating
  /dev/xdma0_* mtimes were overwritten by this gate's own rescan — treat
  the value and the grok46_llm/fable5-worktree attribution as UNCONFIRMED
  (transcribed with provenance in hw_01_reprogram_034.log). Undisputed and
  independent of it: no build.log under synth/out_build_*/ stamps 4b15b576,
  so the resident bitstream was not build_033's. One board, two worktrees,
  no shared lock (sw/.seq.lock is per-checkout) — needs a ruling.
- FLAG for Q10/gate D: tok_meter4's applicable projection is TOKS.md's
  ~61 tok/s (wide ALU + zero-bubble), not ~47; measured 47.01, and the gap
  is ~all layer-side (15.368 ms/tok vs 11.0 projected). The 0.8B layer term
  also moved 14.13 -> 15.368 vs ARCHITECTURE.md:563, which is what the 2B
  study scales into its 17.4 ms term — re-anchor it. Worsens absolute
  modeled tok/s equally for all variants; NO ranking change.
- NEXT: gate D (this + Track Q Task 10) — the operating-point decision.

## ✅ 2026-08-12: RUNG 4 PASSED — 30.4 tok/s + ON-CHIP SAMPLED CHAT
- Board: build_033_rr_AltSpreadLogic_medium (33d720e5 = VERSION CSR =
  EXPECTED in seq_run/infer), WNS +0.009 raw spread, TOPK_IDENT
  0xFAB1704B live at 0x5048.
- Measured: nch=1 46.46 ms/tok (21.5 tok/s), nch=4 32.94 (30.4);
  tokens bit-exact everywhere; sampled chat via chip-topk k=32:
  seed-deterministic (4242 x2 identical), seed-sensitive (4243
  differs), LM head + argmax ON-CHIP every step. Ladder 0.11 -> 30.4
  = 276x. evidence/rung4/RUNG4_GATE.md.
- Chat: chat_seq --nch 4 [--temp 0.8 --seed N]; serve.py --nch 4 with
  temperature/top_k/seed request fields. Board holds the nch=4
  (interleaved-head) weight layout; --nch 1 flips = full re-upload.

## ✅ 2026-08-11: CHAT TEMPLATE SHIPPED — the FPGA answers questions now
- KEY FINDING: the checkpoint was the INSTRUCT model all along (blob
  sha 04b1c301...; Base never downloaded; 16/24 fidelity = instruct's).
  Degenerate chat was solely the missing template. Fix = host-side
  id-spliced ChatTemplate (BpeTok mangles special tokens as strings —
  never string-encode), template ON by default, --raw opt-out,
  incremental multi-turn with carry (T3 amendment: 4 think ids/turn
  retained, checked both ways vs HF renderings).
- Gates: selftests 175/175 + 50/50; model-only == bf16 first tokens;
  HW repeatability x2 identical; lockstep 54/54 steps 0 mismatch; API
  session over SSE. evidence/instruct/INSTRUCT_GATE.md. Board still
  build_032; measured prefill-lite 45.0 / decode 63.2 ms per step.
- UX guidance: use ntok >= 24 so replies reach EOS (ragged mid-sentence
  cuts degrade the next turn's answer — see the Milan datum).

## Open options (pick with user) — newest first

From 2026-08-12 (rung 4) — current:
- NEXT options: layer compute is #1 (14.1 ms, 43%) — dn_step/attn
  element paths; mover/MVGO overlap (S12 door); MVGO guard (0.9 ms);
  weight-stationary batched prefill; Qwen3.5-2B feasibility; QSFP28
  2-board (charter stretch); write-up. Follow-ons in the gate doc
  (am_g vocab headroom, TOPK overflow semantics, geometry cleanup).

Still open from 2026-08-11 (chat template). The matvec row bubble +
argmax-combine item WAS DELIVERED by rung 4; the rest stands:
- NEXT options: matvec row bubble + argmax-combine (~25-29 tok/s);
  layer compute; follow-ons in the gate doc (provenance blob-sha, g64
  evidence contradiction, flock retrofit, serve max_tokens default).


## ✅ 2026-08-11: RUNG 3 PASSED — 15.56 tok/s (2.43x), timing 0.000 via first phys_opt
- Burst mover path (32b single-clock AXI4, zero CDC, zero ISA change):
  seq_run model_v2 385.72 ms /6 tok (was 937.38), tokens bit-exact x2,
  AXIL writes -98.6%. Board holds build_032 postopt bitstream
  (out_build_032_rr_SSI_HighUtilSLRs/postopt/bd_wrapper_postopt.bit,
  VERSION 0x0C991953 = EXPECTED in seq_run.py + infer.py). Closure:
  first roll -0.354 -> spread best -0.091 -> phys_opt pass 1 = 0.000
  flat, 0 failing of 1.167M. NEW PLAYBOOK STEP: census -> reroll
  spread -> post-route phys_opt_design (postopt_032.tcl pattern).
- Chat CLI + serve.py API run 2.4x faster with zero software change
  (chat canned gate golden on build_032; ~63 ms/step -> ~15 tok/s
  streaming). evidence/rung3/RUNG3_GATE.md.
- NEXT options (pick with user):
  * matvec row-bubble fix + RTL argmax-combine/4-chan -> ~25-29 tok/s
    (DDR floor 7.1 ms/token; matvec is 65% of the step now).
  * Qwen3.5-0.8B-INSTRUCT checkpoint swap (zero RTL): same arch as the
    Base model on the board; re-quantize via load_qwen35 + fidelity
    harness + chat template -> real assistant behavior at 15 tok/s.
  * layer compute (22%) after matvec.
  * follow-ons: flock retrofit into infer/seq_run/tok_meter; $urandom
    --seed sweep audit (B's finding); serve.py session persistence.

## ✅ 2026-08-10: CHAT-SEQ SHIPPED — 6.66 tok/s streamed chat + API on silicon
- ALL gates green (evidence/chat/CHAT_SEQ_GATE.md): smoke, B1 x2 canned
  golden, B2 8/8 fresh prompts == reference, B3a 18/18 lockstep-verified
  2-turn continuity, B3b overflow auto-reset, C1 API (SSE golden tokens,
  2-client FIFO, warm restart 2.67 s). Zero RTL — board stays 4d71adcc.
- Measured: full step 150.2 ms, prefill-lite 100.3 ms (-33%), preamble
  36.1 ms, ~570 MMIO reads/turn (was ~3M/token), device_frac 0.988.
- snoke: OS disk failed 2026-08-10, user fixed hardware; rebuild
  checklist at docs/SNOKE_REBUILD.md; board re-programmed via safe
  flow, seq_run regression 937.381 ms (4 us of pre-incident).
- serve.py left RUNNING on snoke:8137 (--prefill full, holds
  sw/.seq.lock). NEVER run infer.py/seq_run/tok_meter while it's up
  (they don't take the lock). kill <pid from /v1/health> to free it.
- NEXT options: census the ~76 ms/token non-matvec remainder -> pick
  rung 3 vs argmax-combine; flock retrofit; weight-stationary batched
  prefill; QSFP28 2-board (charter stretch).

## ▶ 2026-08-10 (resolved): CHAT-SEQ HW gates BLOCKED — snoke sshd wedged (again)
- Chat-seq rung is CODE-COMPLETE, all sim gates green, committed:
  ref/seq_chat.py (2eabe5e, gates A1/A2/A3), sw/chat_seq.py (2eabe5e,
  selftest 142/142 + model-only bit-exact), sw/serve.py + chat_client
  (1b47605, mock 24/24), tb_seq_chip multi-launch gate I1 PASS on real
  RTL (68dd689: START preserves banks; pos-86 ldc RoPE address witness).
  Spec: docs/CHAT_SEQ_SPEC.md incl. phase-1 amendments (ldc default).
- REMAINING (task: HW gates, then evidence/chat/CHAT_SEQ_GATE.md):
  1. smoke: sw/.venv/bin/python chat_seq.py --smoke --out ../evidence/chat/chat_seq_smoke.json
  2. B1: --canned x2 (expect [561,314,279,369,279,6511])
  3. B2: 4 fresh prompts x2 runs vs --model-only predictions
  4. B3: 2-turn continuity + forced --max-ctx overflow reset
  5. C1: serve.py --prefill full + chat_client canned; restart = warm
     residency skip; 2-client FIFO
- BLOCKER: snoke pings but sshd kex-resets (same signature as 08-08,
  NVIDIA-wedge incident; correlated with the user's infer.py session
  ending ~08-10 00:xx). Board held build_031 (4d71adcc, CALIB 0xF)
  before the wedge. If snoke rebooted: xdma needs pcie_helper.sh load
  (rebuild xdma.ko first if kernel bumped); if power was cut, JTAG
  reprogram build_031_rr_AltSpreadLogic_medium via the safe flow.

## ✅ 2026-08-09: RUNG 2 PASSED — 6.40 tok/s, first closed-timing bitstream since 023
- vec_alu + vecnorm are II=1 pipelines (single lane; AMAX32 ordering
  forbids lanes); layer_chan VN feed 4->1 cyc/elem. NO ISA/script/
  numerics change — everything committed replays bit-exact.
- Board holds build_031_rr_AltSpreadLogic_medium, netlist 4d71adcc
  (= VERSION CSR; seq_run.py EXPECTED_SEQ_VERSION updated), **WNS +0.006
  / WHS +0.010, 0 failing endpoints**. DSP +2, LUT -422 vs build_030.
- Measured (seq_run model_v2_s1.e x2, no reprogram): 937.38 ms device
  /6 tok = 156.23 ms/token = **6.40 tok/s** (rung-1: 1220.03 ms, 4.91).
  1.302x, repeatable to 188 cyc. Tokens bit-exact; 7,188 state checks.
  Host ladder same bitstream: frozen 8/8, chain 8/8, token24 8/8,
  model_v2 2/2, 0 errors. evidence/rung2/RUNG2_GATE.md.
- Workflow that delivered it (reuse): investigation agent -> frozen
  docs/RUNG2_SPEC.md -> 3 Opus agents (A vec_alu / B vecnorm+feed /
  C differential TBs vs tb/legacy/ frozen copies) -> integrate ->
  sim ladder -> build+reroll -> HW. Diff-TB pattern (legacy-vs-new,
  sabotage self-tests) is the template for future RTL rungs.
- USER RULE (now in CLAUDE.md): heavy Verilator sims run ON SNOKE
  (seeds in parallel); obj_dirs are NFS-shared — one machine at a time.
- NEXT (open, pick with user):
  * FRESH DEVICE CENSUS first: 156.2 ms/token = matvec+movers ~73 ms
    (47%) + element ~7 + OTHER ~76 (non-ALU layer cmds, seq issue,
    movers). The ~76 ms is unattributed — measure before choosing.
  * RUNG 3 (RTL): matvec row-bubble (~8.9 cyc/row) -> t_matvec ~2x.
  * ARGMAX-COMBINE (RTL): sticky index-base + 4-way combine makes
    rung-1b's 4-chan pay off on the LM head.
  * infer.py: point CLI at build_031 (it still speaks host-driven MMIO;
    a --seq mode would give the user 6.4 tok/s chat).
  * QSFP28 2-board (charter stretch, untouched).

## 2026-08-09: RUNG 1b done — 4-chan sequencer FUNCTIONAL, but 15% SLOWER (bacaac3)
- 4-chan weight-split works on silicon (build_030, no rebuild): sequencer
  drives all 4 matvec_chans concurrently, tokens bit-exact, gated 3 ways
  (seq_model, tb_seq_chip CHIP_NMV=4, HW). nch=1 default byte-identical.
- BUT measured 15% SLOWER (1404 vs 1220 ms device). Root cause: matvec is
  only 36% of device time; the dominant 248k LM head can't parallelize
  under on-chip sequential AMAX32 argmax; 4x MOVX + 13% record overhead
  dominate. evidence/rung1/STAGE5_RUNG1B_GATE.md. 4-chan retained,
  default off.
- REDIRECT: the real decode lever is RUNG 2 = parallelize layer_chan
  vec_alu + vecnorm element ops (they are ~64% of device time; the
  earlier tok_meter analysis put vec_alu at 73% / vecnorm 17% of
  layer_chan busy). That is an RTL rung (build cycle). Also possible:
  RTL "sticky argmax index-base + 4-way combine" to make the LM head
  parallelize -> would finally let rung 1b's 4-chan pay off.
- Board holds build_030 (rung-1 sequencer, VERSION 9e1e0bae, xdma loaded).

## ✅ 2026-08-09: STAGE 5 RUNG 1 PASSED — sequencer runs its own loop (9a53ba5)
- On-chip sequencer executes the full 24-layer real-Qwen3.5 decode loop
  on silicon: seq_run.py --prefix model_v2_s1.e, all 60,495 records,
  tokens bit-identical to golden, 7188 state checks match, repeatable.
  Board: build_030_rr_AltSpreadLogic_medium (9e1e0bae, WNS -0.141,
  EXPECTED_SEQ_VERSION already set). Host-driven ladder 26/26 on same
  bitstream. evidence/rung1/STAGE5_RUNG1_GATE.md.
- Speedup: 1.222s wall vs 30.8s host-driven (25x); device 1220ms ~= wall
  (MMIO overhead eliminated) = 4.91 tok/s (1-chan) vs rung-0 0.195.
- Reboot recovery now self-service: pcie_helper.sh gained a `load`
  subcommand (insmod xdma, NOPASSWD). If a reboot bumps the kernel,
  rebuild xdma.ko first: make in references/dma_ip_drivers/.../xdma.
- NEXT (open, pick with user):
  * RUNG 1b (no RTL): 4-chan weight-split stream option in the generator
    -> ~12 tok/s (tok_meter proved 4.03x matvec scaling). Small.
  * RUNG 2 (RTL): parallelize vec_alu/vecnorm element ops -> toward the
    140 tok/s bandwidth ceiling (see docs/SPEEDUP_LADDER.md).
  * QSFP28 2-board (charter stretch, untouched).

## ▶ 2026-08-09 ~04:30: RUNG-1 BITSTREAM READY — HW gate blocked on XDMA load
- Infra incident RESOLVED (snoke rebooted; cause was an NVIDIA driver
  update not rebooted into — see the 08-08 section). License fixed.
- SEQUENCER BUILT + TIMING-CLOSED. build_030 = pipelined netlist
  (9e1e0bae): the 3 deep combinational paths from build_029 census
  (MOVY dequant, EPS-NORM scale, SEQ fetch) pipelined by retiming
  (commit 9e1e0ba, all sim gates green). Raw -0.188 -> directive spread
  best -0.141 (out_build_030_rr_AltSpreadLogic_medium). ACCEPTED: ==
  build_026's shipped -0.142, same axi_aclk domain, bit-exact at 250MHz
  precedent. Census: diffuse layer_0 congestion, only 3/999 in seq_0.
  THIS IS THE RUNG-1 BITSTREAM:
  synth/out_build_030_rr_AltSpreadLogic_medium/proj/stage1.runs/impl_1/bd_wrapper.bit
  VERSION CSR = 0x9E1E0BAE (== EXPECTED_SEQ_VERSION in sw/seq_run.py).
- BLOCKED ON USER: (1) board not enumerating (power-cycle wiped the
  volatile bitstream — needs JTAG reprogram); (2) XDMA driver NOT loaded
  after reboot, no /dev/xdma0_*, no systemd unit, and Claude cannot
  sudo modprobe (only pcie_helper.sh is NOPASSWD). USER must load the
  xdma module the usual way (from dma_ip_drivers build dir /
  insmod xdma.ko). Then Claude does the rest autonomously:
    a. safe reprogram: sudo -n pcie_helper.sh remove (if enumerated) ->
       program_fpga.sh <the .bit above> -> sudo -n pcie_helper.sh rescan
    b. CSR sanity: MAGIC 0xFAB1E001, VERSION 0x9E1E0BAE, CALIB 0xF,
       layer IDENT 0xFAB1E5A0, matvec IDENTs, seq IDENT 0xFAB1E5E0
    c. HW ladder DUAL-DRIVEN: host-driven frozen regression
       (layer_test.py layer_s1-4/token_s1-4) + chain/token24/model_v2
       THEN sw/seq_run.py --prefix .../model_v2_s1.e (chip runs its own
       60,495-record decode loop) — the rung-1 payoff
    d. tok_meter re-measure vs ~12 tok/s rung-1 target; gate doc + commit
- HEAD 6e525bf. All rung-1 code/sim committed. Sim proved the whole
  sequencer bit-exact incl. full model_v2 (tb_seq_chip). This is the
  first hardware run of the chip executing its own decode loop.

## ⚠ 2026-08-08 ~16:45: LAB INFRA INCIDENT — build_029 blocked, not our code
- RUNG 1 (on-chip sequencer) is CODE-COMPLETE and committed through
  606c452: ref numerics, seq binary format+executor, all RTL (vec_alu
  DYNQ16/op-8 probe/EPS-NORM/XRF, seq_unit+seq_movers), full-chip sim
  (tb_seq_chip 10/10 incl. FULL model_v2_s1 = 181.3M cyc/120.9ms per
  step, matching the 10.1 tok/s projection), host runner sw/seq_run.py
  (version-gated to build_029). ISA frozen at v1.5. NO RTL BUG found in
  any wave. See docs/SEQ_ISA.md, docs/SEQUENCER_PLAN.md, evidence/rung1/.
- BLOCKER: build_029 FAILED 11:03 on a VIVADO LICENSE error (Common
  17-345, no xcvu9p Synthesis license) — fired before synth touched our
  RTL; 66 GB free, so not resources. Then snoke sshd went to
  kex-reset (host pings, TCP 22 opens, resets before banner) and iDRAC
  became unreachable.
- SCOPE (pinged 16:45 from darthplagueis): snoke UP-but-degraded,
  darthvader DOWN, fn2187 DOWN, kyloren UP, r2d2 UP (NFS server fine
  — repo safe). Multi-machine => physical event (power/PDU/thermal).
  HYPOTHESIS: Vivado license server may be darthvader or fn2187 (both
  dark) — would explain the 11:03 license failure directly.
- RESUME once the rack is healthy: (1) confirm snoke sshd + license
  server back; (2) rm -rf synth/out_build_029 (license-failed, no
  artifacts); (3) ssh snoke, nohup ./launch_build.sh build_029 detached;
  (4) watch BUILD_OK + WNS (029 is the largest netlist — +AXI4 read
  master +2 AXIL masters — allow ~4-5h); (5) timing spread if needed;
  (6) safe reprogram; (7) HW ladder DUAL-DRIVEN: host-driven frozen
  regression THEN sw/seq_run.py --prefix model_v2_s1.e (chip runs its
  own 60,495-record decode loop); (8) tok_meter re-measure vs the
  ~12 tok/s rung-1 target; gate doc + commit. EXPECTED_SEQ_VERSION in
  seq_run.py is already 0x123518A6 (build_029 netlist).

## ✅ 2026-08-08: sw/infer.py — interactive live inference (5806c04)
- "Chat with the FPGA": live 24-layer orchestration, chip-computed
  argmax fed back, 9.3 s/tok (21.3 with --verify lockstep). Acceptance:
  reproduced model_v2_s1's recorded tokens exactly on silicon; 39.97M
  readback words bit-exact across 38 forward steps. make chat /
  chat_verify / infer_gate in sw/. Strongest motivation yet for the
  Phase-1B on-chip sequencer (would take ~9 s/tok toward the measured
  81.7 ms/tok device time).

## ✅ 2026-08-06: g64 GATE PASSED (165565a) — dual-mode engine on silicon
- Board holds build_028_rr_SSI_HighUtilSLRs (netlist 67a943bd): WNS
  -0.106 / WHS +0.007, best banked-netlist timing to date. HW 34/34
  runs 0 errors incl. the first mode-1 (g64) real-model runs.
- Default stays g128 (44-sample: 30/44 vs 27/44); g64 per-script via
  --w4-group=64 (better free-run text 3/4 prompts, rank-max 75 vs 845).
- Timing recipe that worked: census -> targeted read-pipeline stage
  (iter5 CV_W3) -> SSI_HighUtilSLRs. Invalid directives (Vivado 2024.2
  placer): SpreadLogic_high, SSI_ExtraTimingOpt.
- Fidelity ladder to date: 0/24 -> 15/24 (dnsn+attnbf+mse) -> 16/24
  (m_q15=65535). Next fidelity levers: g64+datapath interplay,
  Phase-1B sequencer RTL (DYNQ16 + eps vecnorm). Throughput levers:
  ALU/VN parallelization (13.97 tok/s RTL ceiling -> 140 bandwidth
  ceiling). QSFP28 2-board still untouched.

## ✅ 2026-07-27: FIDELITY FIX SHIPPED (07e2d89) — fixed point at W4 ceiling
- 0/24 -> 15/24 top-1 vs bf16 (= the exact W4-mse quantization ceiling);
  free-run text is real language. ZERO RTL — generator/reference only;
  bitstream unchanged (07ffc7b9). Sim 20/20, HW 32/32, 0 errors.
  Record: evidence/stage5/STAGE5_FIDELITY_GATE.md, scope+phase log in
  docs/FIDELITY_REDESIGN.md.
- Cheap follow-ons logged, not done: m_q15 ceiling 65535 (zero-RTL,
  ~3% of heads under-scaled 2x); W4 g=64/32 sweep said 18-20/24 possible
  but changes the DDR beat format (matvec_engine assumes G=128/beat).
- Still open from stage-5 wrap: throughput RTL (ALU/VN parallelization
  toward 140 tok/s), Phase-1B sequencer RTL (DYNQ16 + eps vecnorm),
  QSFP28 2-board stretch.

## ✅ 2026-07-26: STAGE 5 increments ①②③④ ALL GATED ON HARDWARE
- ①+② (53a3eec): 24-layer banked engine, chain + token24 + regression,
  24/24 runs bit-exact on build_026_rr_AltSpreadLogic_medium (07ffc7b9),
  honest WNS -0.142. ③ (24e6192): REAL Qwen3.5-0.8B, full 248,320
  vocab, 4 seeds x 2 runs x 5.79M checks, 0 errors; numerics ledger in
  STAGE5_INC3_GATE.md (S_F sat, dt/A clamp, degenerate text = fidelity
  follow-on). ④ (16c0649): measured tok/s = 12.23 device (4-chan) /
  0.19 wall vs recomputed 140.6 ceiling; bottleneck is layer_chan
  serial ALU/VN (13.97 tok/s RTL ceiling), NOT bandwidth (TOKS.md).
- Board holds build_026_rr_ASM (07ffc7b9). Spread #2 rerolls
  (SSI_*/AltSpread_high/low) may still be finishing in
  synth/out_build_026_rr_*/ — a WNS>=0 roll can swap in (re-gate after).
- Charter stage-5 remaining stretch: 2-board QSFP28 tensor parallelism
  (untouched). Highest-leverage next work, pick with user:
  (a) throughput: parallelize vec_alu/vecnorm element ops (73%/17% of
      layer busy) toward the 140 tok/s bandwidth ceiling;
  (b) fidelity: embedding scale-up via RMSNorm invariance + S_F Q3.12
      (RTL) to fix degenerate text;
  (c) on-chip command sequencer (67x wall, needed for real serving);
  (d) QSFP28 2-board.

## ▶ 2026-07-25: STAGE 5 increment ① — SIM GATES PASSED, build_024 pending
- Plan: ~/.claude/plans/plan-out-the-next-swift-tiger.md (approved; 4 increments).
- d91ef34 committed: layer-banked RTL (LAYER CSR 0x30 {kv_slot[10:8],dn_slot[4:0]},
  LCYC 0x34, dn 9x4096 URAM banks, kv 3x4096, conv 18x6144, tcnt_bank[6][2]),
  gen_chain_script.py, L record in TB+host, chain make targets.
- SIM GATES GREEN: backward compat 8/8 committed stage-3/4 scripts bit-exact
  on banked RTL; 8-layer chain 4 seeds x 3390 cmds / 315,642 checks
  (evidence/stage5/sim_backcompat.log, sim_chain.log).
- build_024 (netlist d91ef34) IS RUNNING on snoke (verified 2026-07-25:
  the ssh-client kill did NOT HUP it — it orphaned and kept going; synth
  done, impl_1 in progress). Do NOT relaunch. Results land in
  synth/out_build_024/ (build.log BUILD_OK marker).
- After BUILD_OK: check WNS (grep "Design Timing Summary" -A12 in
  out_build_024/reports/timing_summary.rpt). Reroll via launch_reroll.sh
  build_024 Explore ExtraTimingOpt ... if negative. Watch: 348 URAM
  (SLR crossing), 9:1x2048b dn read mux, ~540 BRAM.
- Then HW gate (task #2): safe reprogram (autonomous, sudo -n pcie_helper),
  CSR check VERSION=d91ef34?, chain_s1..4 x2 runs via sw/layer_test.py,
  stage-3 layer + stage-4 token scripts x1 as regression, gate doc + commit.
  Chain scripts/bins are gitignored but live in tb/scripts/ (regen:
  ref/.venv/bin/python ref/gen_chain_script.py out seed 3 8 — ref/.venv
  python only works on darthplagueis; sha256 in evidence/stage5/).
- Then increments ② (24-layer token, packed DDR map), ③ (real Qwen3.5 +
  full vocab, audit_ranges first), ④ (tok/s via device counters — user
  chose NO on-chip sequencer). Board still holds build_023_rr_Explore.

## ✅ 2026-07-22: STAGE 4 GATE PASSED (sim + hardware, timing MET)
- Full token path autoregressive on-chip, bit-exact, 4 seeds x 2 runs,
  0 errors: evidence/stage4/STAGE4_GATE.md + token_hw_build023.json.
  Stage-3 layer scripts re-ran clean on the same bitstream
  (layer_hw_build023_regression.json).
- Board holds build_023_rr_Explore (netlist b1ef323a, VERSION CSR
  0xb1ef323a): TIMING FULLY MET — axi_aclk WNS +0.003 (Fmax 250.2 MHz),
  0 failing setup endpoints in the whole design, WHS +0.010, all ui_clk
  met. First outright timing closure of the project.
- Reroll flow that got there: synth/scripts/launch_reroll.sh <build>
  <directive>... (project copy per directive, synth reused, ~3h).
  On this netlist: Explore +0.003, ExtraTimingOpt +0.003,
  ExtraNetDelay_low -0.142, AltSpreadLogic_medium -0.339.
- NEW: pcie_helper.sh is NOPASSWD sudo on snoke (verified sudo -n -l).
  Claude can run the full safe reprogram autonomously. Exact form:
  ssh snoke 'sudo -n /home/cah/r2d2/code/fpga/fable5_llm/sw/pcie_helper.sh remove|rescan'
  (allow rules for both are in .claude/settings.local.json).
- Log-grep gotcha: anchor with "^TIMING:" / "^FATAL" — Vivado echoes
  script text (including the FATAL branch) into logs with "# " prefixes.

## Next: Stage 5 (charter stretch goals — pick with the user)
Charter list: (a) multiple layers chained, (b) real quantized model
weights, (c) measured tok/s vs prediction, (d) 2-board tensor
parallelism over QSFP28. Natural first step: (a) chain N layers by
extending the script generator (scratch/URAM budget check first:
KV cache + DN state per layer), then (c) measure tok/s on the chained
pipeline vs a paper model. Full-vocab LM head (248,320 rows = 61 chunks
of 4096) needs no RTL change — script generation + 61 weight images.
