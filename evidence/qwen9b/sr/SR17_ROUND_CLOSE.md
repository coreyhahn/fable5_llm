# SR17 — the sequencer RTL round, closed: the ladder, the tasks, the board, what is NOT established, the backlog

Task SR17 of `docs/superpowers/plans/2026-09-27-seq-rtl-round.md` (docs at the round's close). Docs only: no
RTL, no build, no board action, nothing numeric. Every number below is **T** — transcribed from the gate doc
it cites; none is recomputed. Logs n1700–n1712 (+ the spec_cites logs of §6) ran on snoke through
`evidence/qwen9b/sr/sr_run.sh`. The ledger `.superpowers/sdd/2026-09-27-seq-rtl/progress.md` is gitignored and
cited by path and date, never by line.

## 0. Verdict

**The round is CLOSED at R2 on the documentation side; its one open item is the user's R3 ruling, PENDING.**

* **R1 (the FENCE channel mask) and R2 (the XWIN/RES bank bits) are built, signed off with no waiver and
  proven on silicon, tokens IDENTICAL on every run** (`evidence/qwen9b/sr/SR8_R1_BOARD.md`,
  `evidence/qwen9b/sr/SR15_R2_BOARD.md`, the verdicts). **Neither is resident**: build_041 is, restored after
  each session (§3).
* **The decode step went 6.770 (shipped order) → 7.619 (S1 form B) → 7.929 (R1) → 8.182 (R2) tok/s** (§1).
* **R3 (MOVX broadcast) is NOT BUILT.** SR16's decision document `evidence/qwen9b/sr/SR16_R3_DECISION.md`
  (COMPLETE at `2398e5e`) offers A (form (a), recommended) / B (form (b)) / C (stop at R2); `NEXT_SESSION.md` §8
  item 3 carries the three options and the line "R3 ruling: PENDING (asked 2026-09-29; SR16_R3_DECISION.md is
  the brief)" — the controller adds the ruling there in a one-line commit.
* **Docs closed:** `NEXT_SESSION.md` §7 / §8 / §9 / pointers / History, `docs/USAGE.md` §3's `r2` paragraph,
  `docs/HISTORY.md` the round's ladder table, the spec's §2.1 SR10 pointer and `docs/SEQ_ISA.md` B17.3's
  "not built" line (§6). Cite drift repaired digits-only and verified (§6.2); spec_cites LAST alone (§6.3).

## 1. The round's ladder — MEASURED on silicon, tokens IDENTICAL at every rung

Chat = the chat511 decode step (full image, context 502..510, per launch). Stream = the 6-token `model_9b_s1`
form-B census (per token). FENCE = the C5 FENCE-wait share of the stream.

| rung | chat full ms | **chat tok/s** | stream ms/token | **stream tok/s** | FENCE % | source |
|---|---|---|---|---|---|---|
| shipped order (build_041 chat n68; build_042_bm1 stream n72) | 147.7088 | **6.770** | 137.1195 | **7.293** | 41.96 | `evidence/qwen9b/sr/SR15_R2_BOARD.md` §3.1, §3.2 |
| S1 form B (software; the R2 bitstream at r0, n1506 / n1511) | 131.2479 | **7.619** | 120.5367 | **8.296** | 38.50 | same |
| R1 (the R2 bitstream at r1, n1507 / n1510) | 126.1135 | **7.929** | 114.3885 | **8.742** | 35.12 | same |
| **R2** (build_045_r2_incr at r2, n1508 / n1509) | **122.2175** | **8.182** | **110.4066** | **9.057** | **32.78** | same |

The board table lines: `evidence/qwen9b/sr/n1516_sr15_board_table.log:18-19` (n68),
`evidence/qwen9b/sr/n1516_sr15_board_table.log:30-35` (n1506–n1508),
`evidence/qwen9b/sr/n1516_sr15_board_table.log:89` (n72), `evidence/qwen9b/sr/n1516_sr15_board_table.log:92-94`
(n1511–n1509), `evidence/qwen9b/sr/n1516_sr15_board_table.log:100` (the FENCE shares); the same rows are
`evidence/qwen9b/sr/SR16_R3_DECISION.md` §1's. R1 on its own bitstream (SR8) read the same 7.929 / 8.742
(`evidence/qwen9b/sr/SR8_R1_BOARD.md` §3); the R2 netlist moves r1 by −0.0011 % on the full step
(`evidence/qwen9b/sr/SR15_R2_BOARD.md` §3.1).

Per rung on the same bitstream, chat full: S1-B → R1 ×1.0407, R1 → R2 ×1.0319; R2 against build_041's shipped
order ×1.2086 (`evidence/qwen9b/sr/SR15_R2_BOARD.md` §3.1). The stream against the model: R1 0.9922, R2 0.9905
(`evidence/qwen9b/sr/SR16_R3_DECISION.md` §1).

**R3, expected (MODEL-derived, SR16 — not measured):** form (a) chat 8.70–8.77 / stream 9.70–9.83 tok/s; form
(b) 8.57–8.63 / 9.54–9.64 (`evidence/qwen9b/sr/SR16_R3_DECISION.md` §1, §5).

A note on the SR17 addendum's summary line ("shipped 7.293 → S1-B 7.619 → R1 7.929 → R2 8.182 decode tok/s"): its
first figure is the STREAM's shipped rung and the rest are CHAT; the two ladders are kept separate above, as
SR15 and SR16 print them (judgment call 1, §7).

## 2. The tasks

Commit ranges and review outcomes are the ledger's completion lines (`.superpowers/sdd/2026-09-27-seq-rtl/progress.md`,
2026-09-27 … 29); each result is its gate doc's.

| task | what | commits | review | result (gate doc) |
|---|---|---|---|---|
| SR0 | the design spec | `ad7b62b`..`11e8947` | needs-fixes + 1 fix round, re-review clean | `docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md`; the user answered its nine §7 questions 2026-09-27 (`NEXT_SESSION.md` §7) |
| SR-PLAN | the plan | `5437f2b`..`32ce34d` | needs-fixes + 2 fix rounds | `docs/superpowers/plans/2026-09-27-seq-rtl-round.md` |
| SR1 | step 0: the incremental-implementation probe | `45deebf`..`261c538` | approved + 1 fix round | CLOSES (`evidence/qwen9b/sr/SR1_INCR_PROBE.md` §0) |
| SR2 (+SR2b) | ISA v2.3: SEQ_CAPS, the FENCE mask, the validator's `caps=` (SR2b: serve's pins) | `bfabbfe`..`3ae0ff9`; `496a273` | 2 fix rounds; SR2b none | `evidence/qwen9b/sr/SR2_ISA.md` |
| SR3 (+SR3c) | R1 RTL in `seq_0` (SR3c: its cite-drift pass) | `5c369c2`..`b4b2501`; `529e6b0`..`1cccc51` | approved; SR3c controller-verified | `evidence/qwen9b/sr/SR3_R1_RTL.md` |
| SR4 | R1 software: model, cost model, the pass emits masked fences | `76a68cd`..`7e72126` | 1 fix round | `evidence/qwen9b/sr/SR4_R1_MODEL.md` |
| SR5a | R1 chip TB 1: backward compatibility cycle-identical | … `2bdab07` | approved, no fix round | `evidence/qwen9b/sr/SR5a_R1_COMPAT.md` |
| SR5b | R1 chip TB 2: r1 streams tokens IDENTICAL 4/4, the model HELD | `a4f9841`..`6a5a8b8` | 1 fix round | `evidence/qwen9b/sr/SR5b_R1_CHIP.md` |
| SR-ISABITS | isa_bits made a meaningful gate again | `13a65e3`..`73ada3e` | approved + 1 fix round | GREEN (`evidence/qwen9b/sr/SR_ISABITS.md`) |
| SR6 | the host side for R1: device-keyed admission, `--seq-rtl` | `a24c256`..`6bedf91` | + 1 fix round, re-review clean | `evidence/qwen9b/sr/SR6_HOST.md` |
| SR7 | the R1 build | `899f03e`..`966cbcf` | needs-fixes + 1 fix round | SIGNED OFF, build_044_r1_incr (`evidence/qwen9b/sr/SR7_R1_BUILD.md` §0) |
| SR7C | the MMCM compute-clock contingency | — | — | **never ran** (no closure failure); its log block n1800–n1899 is untouched |
| SR8 | the R1 board session | `9f5a072`..`2c66d67` | spec PASS, quality APPROVED, no fix round | R1 ON SILICON, tokens IDENTICAL, 7.929 tok/s (`evidence/qwen9b/sr/SR8_R1_BOARD.md`) |
| SR9 | docs at R1 + R2 | `9f7769c`..`ac302a1` | needs-fixes + 1 fix round | spec_cites FAIL 0 (`evidence/qwen9b/sr/n918_sr9f1_spec_cites_LAST.log`) |
| SR10 | the MIG's accepted DDR4 periods | `628fb3a`..`42b2ebe` | 1 fix round | 833 / 877 / 937 in 833..940; 877 the only ≤ 5 % cut (`evidence/qwen9b/sr/SR10_MIG_PERIOD.md` §0) |
| SR11a | R2 contract, validator, model | `110108e`..`081ec85` | needs-fixes + 3 fix rounds | GREEN (`evidence/qwen9b/sr/SR11a_R2_MODEL.md`) |
| SR11b | the R2 pass, the corrected cost model, r2 streams | `4e3d0c5`..`93380f8` | + 1 fix round | `evidence/qwen9b/sr/SR11b_R2_PASS.md` |
| SR11c | the round's citation drift, one owner | `60b6807`..`a9de900` | + 2 fix rounds | `evidence/qwen9b/sr/SR11c_CITE_DRIFT.md` |
| SR12 | R2 RTL in `seq_0` and the four `mvchan`s | `f4c1fb7`..`9eeaacb` | approved + 1 fix round | `evidence/qwen9b/sr/SR12_R2_RTL.md` |
| SR13a | R2 on the chip TB | `0044b1b`..`266e3ae` | PASS/APPROVED + a doc fix | R2 on the chip TB CLOSED (`evidence/qwen9b/sr/SR13a_R2_CHIP.md`) |
| SR13b | the host's R2 capability, keyless hardening | `7523472`..`a6b0c69` | PASS/APPROVED, no fix round | `evidence/qwen9b/sr/SR13b_HOST_R2.md` |
| SR14 | the R2 build | `c4afeee`..`a4cf5e6` | sign-off HELD + 1 fix round | SIGNED OFF at rung 1, build_045_r2_incr (`evidence/qwen9b/sr/SR14_R2_BUILD.md` §0) |
| SR15 | the R2 board session | `cff0ac3`..`544ee30` | spec PASS, quality APPROVED, no fix round | R2 ON SILICON, tokens IDENTICAL, 8.182 tok/s (`evidence/qwen9b/sr/SR15_R2_BOARD.md`) |
| SR16 | the R3 decision document | `8e4d6aa`..`2398e5e` | PASS/APPROVED + 1 wording round | A / B / C, A recommended (`evidence/qwen9b/sr/SR16_R3_DECISION.md` §5) |
| **SR17** | docs at the round's close | `e0af8d4` onward (§6) | — (this task) | this document |

## 3. What is on the board, and what is on disk

* **On the board: build_041** (`build_041_ckr2_AltSpreadLogic_high`, VERSION `0xc973c18a`, CALIB `0xF`,
  SEQ_CAPS `0xdeadc0de`), restored by SR15 at 06:10:43–06:11:52 on 2026-09-29 and read back `IDENT: PASS`
  (`evidence/qwen9b/sr/n1513_sr15_ident_041_restored.log:8-16`); the last lock holder and DDR writer was
  `n1514`'s chat sanity (06:12:00 → 06:21:32, 24 ids IDENTICAL to n77); the lock was free at 06:21
  (`evidence/qwen9b/sr/n1517_sr15_readonly_status.log:8`). **No board action happened after SR15** (SR16, SR9
  and SR17 are docs and boardless runs), so `NEXT_SESSION.md` §1 stands as SR15 derived it.
* **The two round bitstreams, signed off, each loaded once, NOT resident** (`NEXT_SESSION.md` §3):
  build_044_r1_incr, VERSION `e3c2ff1e`, SEQ_CAPS `0xFAB1CA01`, sha256 `92a2e525…b50816`
  (`evidence/qwen9b/sr/SR7_R1_BUILD.md` §4), with a same-VERSION alternate `_bm1ref`; build_045_r2_incr, VERSION
  `266e3ae7`, SEQ_CAPS `0xFAB1CA03`, sha256 `c4caeb09…4dcb`, with a same-VERSION **TWIN**
  `synth/out_build_045_r2/…` (WNS −0.865, never program it) (`evidence/qwen9b/sr/SR14_R2_BUILD.md` §4). The
  CSRs cannot tell either pair apart: **a load ruling names the file by path AND sha256**.
* **Loading either again needs a load ruling** (the user's Q9 answer: each round bitstream its own ruling,
  `NEXT_SESSION.md` §7). Whether R1 or R2 becomes the resident default is a separate open decision.

## 4. What is NOT established

* **R3 in any form** — no r3 stream, no chip-TB number, no build; the expectations are MODEL-derived
  (`evidence/qwen9b/sr/SR16_R3_DECISION.md` §6).
* **One session per condition** on silicon, one prompt, context ≤ 511, greedy only; no sampled decode, no
  `--verify`, no `--prefill full` T-curve on R1 or R2; the whole 511-step sessions are checked by their tokens
  only; the state region's final image was not read back; only the s1 r2 stream ran on silicon
  (`evidence/qwen9b/sr/SR8_R1_BOARD.md` §7, `evidence/qwen9b/sr/SR15_R2_BOARD.md` §7).
* **Timing margins are thin and single-placement**: R1 WNS +0.001 (`evidence/qwen9b/sr/SR7_R1_BUILD.md` §0),
  R2 WNS +0.004 closed inside route_design (`evidence/qwen9b/sr/SR15_R2_BOARD.md` §7;
  `evidence/qwen9b/sr/SR14_R2_BUILD.md` §2). Any netlist change
  re-opens the whole timing gate.
* **The UI-clock cut at 877 ps**: accepted by the IP, but DIMM calibration there, the block design's
  validation at 877 and a per-VERSION `UI_CLK_HZ` are not established (`evidence/qwen9b/sr/SR10_MIG_PERIOD.md`
  §0 item 4, §5); R2 did not need it.
* **The resident default** (build_041 vs R1 vs R2) is undecided; nothing here argues for one.
* **(Resolved in fix round 1 — kept as a record.)** The user's literal Q-answer text and its mapping ARE in the
  ledger: its RECORD line dated 2026-09-29 (written after SR17's first report) gives "1  Yes 2  ok 3  yes 4 yes 5  each
  on its own" → Q1 / Q3 / Q4 / Q5 / Q9; `NEXT_SESSION.md` §7 now quotes it exactly, with the mapping.

## 5. The tooling backlog — recorded, NOT implemented (owner: the next tooling task)

`NEXT_SESSION.md` §9 (f) item 11 carries the ten items with their sources; in one line each:

1. `evidence/qwen9b/o3/o3_cite_drift.py --verify` accepts an unresolvable `--doc-base` and passes vacuously on
   0 citations (SR15 n1523) — refuse and fail.
2. The inherited spec_cites baseline script scores 0 base keys when a listed file is missing at the base
   (SR15 n1526).
3. `sw/program_fpga.sh` should take an expected sha256 and refuse a mismatch (today: the manual re-hash,
   SR14 / SR15).
4. A synth-only launch mode (SR14 waited ~3 h 25 min for the base roll, which left a same-VERSION twin).
5. The false-path coverage probe should require an explicit exception, not merely "no timed path" (SR14
   review m-2).
6. A pre-flight that FAILS on a dirty tree and re-checks attached hw_manager clients inside the programming
   command (SR15 review M3/M4).
7. `evidence/qwen9b/bm/bm1_census.py` validates at empty caps — retire it for `evidence/qwen9b/sr/sr8_census.py`
   or fix it.
8. `evidence/qwen9b/g6/g6_state.py` has no VERSION check before its 155 MiB DMA.
9. The plan-fix log block n990–n999 is exhausted; n2000–n2099 is SR11c's, so later plan fixes take n2100+
   (`docs/superpowers/plans/2026-09-27-seq-rtl-round.md:550`).
10. o3 `--verify` cannot tell a deliberately kept historical token from a missed repair — a `--keep <doc:line>`
    list (SR9 n915/n916; SR17 n1711/n1712 hit it again, §6.2).

## 6. SR17's own work

### 6.1 The edits (commit `092c2de`)

* `NEXT_SESSION.md`: §7's 2026-09-27 answers row quoted in full from the ledger (Q2's condition, Q4's option 2,
  Q5's step 0, Q6–Q8, Q9 "waiver ruling") plus the user's own words (§4); §8's heading → "the R3 ruling,
  PENDING"; §8 item 3's status → the round's close, the ladder, SR16's three options with bands and costs, the
  line "R3 ruling: PENDING (asked 2026-09-29; SR16_R3_DECISION.md is the brief)"; §9 (a) 12 → SR16 COMPLETE,
  ruling pending; §9 (f) 11 → the ten-item backlog; the pointer table (seven ledgers, the round's row, the
  `--seq-rtl` row, SEQ_ISA's v2.3); the Key-invariants SEQ_ISA line; a History line. §1 untouched (no board
  action since SR15); §3 already carried both bitstreams "loaded once / not resident" with shas and the twin
  warning (SR9) — untouched.
* `docs/USAGE.md` §3: the heading → `--seq-rtl r0|r1|r2`; the `r2` paragraph (pins, gates, device-keyed
  refusal on 0xDEADC0DE and 0xFAB1CA01, naming, the twin, SR15's run).
* `docs/HISTORY.md`: a new top entry — the round's ladder table, and the `NEXT_SESSION.md` text SR17 replaced,
  VERBATIM from `ac302a1`; one intro paragraph.
* The spec §2.1's `mmcm_clkout0` row gains the SR10 pointer (the reviewer's "§2.3 clock table" — §2.3 has no
  table; the clock table is §2.1, judgment call 3). `docs/SEQ_ISA.md` B17.3 gains "NOT BUILT … ruling PENDING".
  Both line-preserving (numstat 1 / 1).
* `CHARTER.md` untouched (no rail changed).

### 6.2 Cite drift (base `ac302a1`, doc-base `092c2de`, wrapper `evidence/qwen9b/sr/sr17_drift.sh`, commit `e0af8d4`)

| doc | plan | check | fix | verify |
|---|---|---|---|---|
| `NEXT_SESSION.md` | n1700 SAFE, REPAIR 1 / COLLATERAL 0 | n1703: 18 read, 5 drifted (3 cited only by the excluded `sr6fix1_hand_repairs.py`) | n1706: `evidence/qwen9b/sr/SR2_ISA.md` 1121-1126 → 1129-1134 | n1709 PASS (18 read, 5 relocated) |
| `docs/USAGE.md` | n1701 SAFE, REPAIR 11 / COLLATERAL 0 | n1704: 30 read, 22 drifted | n1707: 4 docs (two 2026-08 plans, `evidence/qwen9b/o3/BOARD_LOCK.md`, `ref/scripts/regen_gate.sh` — a comment) | n1710 PASS (30 read, 22 relocated) |
| `docs/HISTORY.md` | n1702 SAFE, REPAIR 36 / COLLATERAL 0 | n1705: 40 read, 39 drifted | n1708: 8 docs | n1711 FAIL 4 = exactly the kept token below; n1712 with RD9_GATE excluded PASS (40 read, 39 relocated) |

By hand, in commit `4e6d5a5`: **`evidence/qwen9b/g6/RD9_GATE.md:2590`'s "was" side restored to 456-457** — kept
history, as SR9 fix round 1 (m5) restored it; the "now" side (:2591) and RD9_GATE's other six HISTORY tokens
track. **`evidence/qwen2b/rb/TIMING.md:427`'s comma-joined HISTORY cite, 1016,1038 → 1099,1121**: o3 does not parse the
comma continuation, so n1708 moved only the first; both landings opened (1099 the 2-turn line, 1121 the
`1. smoke:` line, as SR9 I-1 found). Verify ran at the plan's doc-base on the committed fix tree.

### 6.3 spec_cites LAST

Over every doc SR17 touched — its five edited docs, this gate doc, and the ten drift-touched records (the
two 2026-08 plans, the 2026-08-29 migration spec, TIMING.md, G3_3_MATVEC, G3_4_LAYER, G5D_TIMING, RD9_GATE,
BOARD_LOCK, SR2_ISA; `ref/scripts/regen_gate.sh` is not a doc):

* **n1713** precheck over all 16: FAIL — this doc's two own spans (a report path not yet written, and the
  quoted old TIMING token; both rewritten out of backticks) plus the pre-existing FAILs of six drift-touched
  records.
* **n1714** the baseline at `ac302a1` (`evidence/qwen9b/sr/sr17_spec_cites_baseline.sh`) with this doc in the
  list scored **0 base keys** — this doc does not exist at the base: **backlog item 2, hit again**; superseded.
* **n1715** this doc alone after the rewrite: PASS, FAIL 0 (91 exist, 11 range) — a precheck on the working tree.
* **n1716** the baseline over the other 15 (stamped 68298b6+dirty: only this doc, not in its list, was being edited): **base 59 = work 59 line-free keys, 0 introduced**. The pre-existing
  FAILs, all in the drift-touched records: `docs/superpowers/plans/2026-08-12-qwen2b-track-r.md` 35,
  `docs/superpowers/plans/2026-08-16-qwen2b-v5-w8.md` 5, the 2026-08-29 migration spec 4,
  `evidence/qwen9b/g3/G3_3_MATVEC.md` 1, `evidence/qwen9b/g3/G3_4_LAYER.md` 3, `evidence/qwen2b/rb/TIMING.md` 11
  (the last four as SR9 found them). The script prints its parent's tag "SR9_SPEC_CITES_BASELINE" (a copy;
  base `ac302a1` is in its header).
* **The LAST run** — alone, on the committed tree, over the ten docs that can reach zero (the five edited
  docs, this doc, G5D_TIMING, RD9_GATE, BOARD_LOCK, SR2_ISA) — is the log after n1716, in a commit holding only
  that log; its result is in the task report (gitignored), because that commit is cited by nothing.

## 7. Judgment calls

1. **The addendum's mixed ladder** (7.293 is the stream's shipped rung, 7.619 / 7.929 / 8.182 chat) — both
   ladders written separately, as SR15 / SR16 print them.
2. **The replaced `NEXT_SESSION.md` text moved VERBATIM to `docs/HISTORY.md`** (NS1 / SR9's convention), with
   the ladder table in the same new entry — one HISTORY insertion, one drift pass.
3. **"The spec's §2.3 clock table"** is §2.1's table (§2.3 is prose on how a compute-clock cut would be built);
   the SR10 pointer went into §2.1's `mmcm_clkout0` row, the one that said the accepted periods were not
   established.
4. **The user's literal answer string** — first quoted from the SR17 dispatch without a mapping; in fix round 1
   re-quoted exactly from the ledger's RECORD line (2026-09-29), double spaces kept, mapped Q1 / Q3 / Q4 / Q5 / Q9.
5. **SEQ_ISA's literal backticks inside indented blocks** (SR9's rtl/ prefix, backticked so spec_cites checks
   them): **left as they are** — cosmetic, and removing them would make 28 pointers invisible to spec_cites.
6. **`docs/SEQ_ISA.md` B17.2 as-built** was already done by SR9 (`74a5f84`); SR17 only adds B17.3's not-built
   line.
7. **The `--seq-rtl` heading renamed** to `r0|r1|r2`; `evidence/qwen9b/sr/SR6_HOST.md:68` names the old
   heading as a historical record of SR6's edit and is left as written.
8. **`NEXT_SESSION.md` §1's "keep them while the waiver question (§8, the SR0 spec's §7 Q9) is open"**
   (build_042_bm1's out dirs) is stale-ish — Q9 was answered for the round bitstreams, not for build_042_bm1's
   dirs — and §1 was to be kept unless a board action happened; left, noted here.
9. **Backlog item 9** says n2100+, not the addendum's n2000+: n2000–n2099 is SR11c's (SR9 judgment call 9; the
   plan already says so).
10. **SR16's files stay excluded in the drift wrapper** (inherited from SR9); none of them cites the three shifted
    docs by line (checked by grep), so nothing is lost.

## 8. Logs

| log | what |
|---|---|
| n1700–n1702 | o3 `--plan`, NEXT_SESSION / USAGE / HISTORY |
| n1703–n1705 | o3 `--check` (the drifted tokens by name, citation counts) |
| n1706–n1708 | o3 `--fix` |
| n1709–n1712 | o3 `--verify` (n1711 the kept-token FAIL 4, n1712 PASS with RD9_GATE excluded) |
| n1713 | spec_cites precheck over all 16 touched docs (FAIL: 2 own, rewritten; the rest pre-existing) |
| n1714 | the baseline with this doc listed — 0 base keys (backlog item 2), superseded |
| n1715 | spec_cites on this doc alone after the rewrite — PASS |
| n1716 | the baseline over the other 15 — 0 introduced |
| n1717 | spec_cites LAST (the task report) |

## 9. Final fix round (2026-09-29, after the whole-branch review: CLEAN, nine minors, four taken)

The controller took four of the review's nine minors (`.superpowers/sdd/2026-09-27-seq-rtl/final-review.md`,
gitignored). Nothing numeric changed; no board, no Vivado. Every doc and comment edit is line-neutral, so no cite
moved and no o3 drift pass was needed.

* **Minor 1, USAGE r2 (commit `73abfdd`).** The SR17f1 clause said `--reorder B` must be given explicitly. On the
  CLI that is false: main() runs effective_reorder before `check_seq_rtl`, and at 9B `--nch 4` the auto default is
  B, so `--seq-rtl r2 --nch 4` alone passes; `--reorder off` and `A` are refused at r2
  (`evidence/qwen9b/sr/n1719_sr17ff_reorder_probe.log:7-11`, a read-only probe that stops at `check_seq_rtl`,
  before the lock and the board). A namespace that bypasses main() with the auto default is refused
  (`evidence/qwen9b/sr/n1719_sr17ff_reorder_probe.log:12`); serve pins reorder None and r0. The flags are in
  `evidence/qwen9b/sr/n1720_sr17ff_chat_seq_help.log:78-96`.
* **Minor 2, the BM_IDENT table (commit `1692cdc`).** Four new `sw/seq_run.py` selftest cases: every SEQ_VERSIONS
  key has a SEQ_BM_IDENT_BY_VERSION row; each value is the unmapped read or 0xFAB1B301; a row expecting a SEQ_CAPS
  word other than 0xDEADC0DE expects 0xFAB1B301; and pins (034/035/041 unmapped; 042/e3c2ff1e/266e3ae7
  0xFAB1B301). RED by in-process mutation only, never on disk (`evidence/qwen9b/sr/sr17ff_bm_rows_red.py`): five
  mutations each RED as expected, and the control is 2840/0 (`evidence/qwen9b/sr/n1721_sr17ff_bm_rows_RED.log:78-79`).
  GREEN on the clean tree: **2840 passed, 0 failed** (was 2836; +4), `evidence/qwen9b/sr/n1722_sr17ff_seq_run_selftest.log:55`.
* **Minor 4, "state no layout" (commit `73abfdd`).** `ref/seq_format.py`'s three comment sites and the SEQ_ISA
  B17.2 validator paragraph now say what is true: since SR11a fix round 2 the board callers state the DEVICE's
  layout (`evidence/qwen9b/sr/SR11a_R2_MODEL.md` §8).
* **Minor 5, NEXT_SESSION (commit `73abfdd`).** The build_042 dirs line now records Q9 as answered (§7's
  2026-09-27 and 2026-09-29 rows) and keeps the dirs until the user says otherwise; the §3 heading is SIX
  BITSTREAMS, the table's row count.

Regressions on the clean committed tree `73abfdd`: seq_run 2840/0 (n1722); chat_seq 407/1, the same pre-existing
[22] region-image failure (`evidence/qwen9b/sr/n1723_sr17ff_chat_seq_selftest.log:33-35`); hwmap PASS (n1724);
rd_boardfree seq 2840/0, serve 85/0, chat 407/1 (`evidence/qwen9b/sr/n1725_sr17ff_boardfree.log:61-140`).
spec_cites LAST over the four touched docs is n1726, committed alone.
