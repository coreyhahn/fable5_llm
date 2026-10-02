# SR16 — R3 (MOVX broadcast): the decision from silicon

Task SR16 of `docs/superpowers/plans/2026-09-27-seq-rtl-round.md`. One document for the user: take R3 (and
in which form), or stop the round at R2. No RTL, no build, no board, no model change. Every number below was
printed by a committed run on snoke (`evidence/qwen9b/sr/sr_run.sh`, logs n1600–n1602) or is transcribed from
a gate doc, and is cited.

**Labels.** **MEASURED** = a board counter or step time (BM1 / SR8 / SR15 logs). **MODEL** = OV1's list
schedule over chip-TB windows (`evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md` §0), board-scaled by the uniform
factor unless it says "TB". **D** = derived by `evidence/qwen9b/sr/sr16_decision_table.py` (n1602) or
`evidence/qwen9b/sr/sr16_r3_census.py` (n1600) from those. **T** = transcribed. 250 MHz aclk cycles.
"Stream" = the 6-token `model_9b_s1` form-B census (per token); "chat full" = the chat511 decode step at
context 502..510 (per launch).

## The answer in five lines

1. **R1 and R2 on silicon held the model to within 1 %** at every rung (stream/MODEL 0.9922, 0.9905), and the
   decode step went 7.619 → 7.929 → 8.182 tok/s (MEASURED).
2. **R3 does not remove FENCE wait; it removes mover work.** The model's R3 zeroes 9.711 ms/token of sibling
   MOVX and the lane then waits 1.535 ms more on streams, so the FENCE share RISES (32.78 % → about 36.9 %)
   while the MOVX share falls (11.79 % → about 3.2 %) (**D**, `evidence/qwen9b/sr/n1600_sr16_r3_census.log:36`,
   `evidence/qwen9b/sr/n1602_sr16_decision_table.log:76`).
3. **The dependency part of the census's own caveat (the broadcast waits on the latest of four channels)
   costs 0 cycles** when modelled (bank forcing and the siblings' own-channel occupancy are not modelled, §6):
   the latest-of-four variant schedules to 24,102,767 cycles, the same as OV1's R3 to the cycle
   (**D**, `evidence/qwen9b/sr/n1600_sr16_r3_census.log:26`, `evidence/qwen9b/sr/n1600_sr16_r3_census.log:32`).
4. **Expected R3 form (a): chat full 8.70–8.77 tok/s (central ≈8.74; top 8.77, ×1.072), stream
   9.70–9.83 (central 9.79, ×1.080)**; form (b): chat full 8.57–8.63 (central ≈8.60, top 8.63), stream
   9.54–9.64 (central 9.61) (**D**, `evidence/qwen9b/sr/n1602_sr16_decision_table.log:84-88`,
   `evidence/qwen9b/sr/n1650_sr16f1_midpoints.log:18-21`). On chat the top is R3 carrying over exactly as R2
   did (R2's chat retention is 1.0069 against SR13b's corrected makespans, 0.9698 against the tool's
   uncorrected input, `evidence/qwen9b/sr/n1650_sr16f1_midpoints.log:22`), so the central is the band's
   midpoint. MODEL-derived, anchored on the MEASURED R2 row.
5. **Recommendation: take R3, form (a), with (b) as the named fallback** (§5). The software half (ISA, model,
   pass) is shared by both forms and goes first; the risk is the timing closure, not the gain.

## 1. The ladder (MEASURED, beside the MODEL)

| rung | chat full ms | **chat full tok/s** | stream ms/token | **stream tok/s** | MODEL tok/s (form B) | stream / MODEL |
|---|---|---|---|---|---|---|
| shipped order | 147.7088 | 6.770 | 137.1195 | 7.293 | 7.292 | 1.0001 |
| S1 form B | 131.2479 | 7.619 | 120.5367 | 8.296 | 8.356 | 0.9928 |
| R1 | 126.1135 | 7.929 | 114.3885 | 8.742 | 8.811 | 0.9922 |
| **R2 (now)** | **122.2175** | **8.182** | **110.4066** | **9.057** | 9.144 | 0.9905 |
| R3 form (a) | — | *8.70–8.77 expected* | — | *9.70–9.83 expected* | 9.920 | — |
| R3 form (b) | — | *8.57–8.63 expected* | — | *9.54–9.64 expected* | 9.727 | — |

Sources: measured rows **D** `evidence/qwen9b/sr/n1602_sr16_decision_table.log:9-12` (chat: n68 on build_041,
n1506 / n1507 / n1508 on the R2 bitstream; stream: n72 on build_042_bm1, n1511 / n1510 / n1509 on the R2
bitstream); MODEL rows **T** `evidence/qwen9b/ov/n120_sr0_clock_sens.log:34-39`; expectations §3.

Per rung, same bitstream (**D**, `evidence/qwen9b/sr/n1602_sr16_decision_table.log:13-15`):

| step | chat full | stream | MODEL |
|---|---|---|---|
| shipped → S1-B | ×1.1254 | ×1.1376 | ×1.1459 |
| S1-B → R1 | ×1.0407 | ×1.0537 | ×1.0545 |
| R1 → R2 | ×1.0319 | ×1.0361 | ×1.0378 |
| R2 → R3 (a), expected | ×1.063–×1.072 | ×1.070–×1.085 | ×1.0848 |

The SR8/SR15 controls hold: the stream rows on the R2 bitstream equal SR8's on the R1 bitstream
(FENCE and MOVX shares identical to 0.01 point, **D**, `evidence/qwen9b/sr/n1602_sr16_decision_table.log:50-51`).

## 2. Where the step goes — the shares (MEASURED, BM1 counters)

Stream census, per token, % of PERF_CYC (ms) (**D**, `evidence/qwen9b/sr/n1602_sr16_decision_table.log:21-33`).
Counter meanings: `docs/SEQ_ISA.md` §B16 (C0 MVANY any engine busy; C5 mover on a FENCE; C6 mover on
MOVX/MVGO/MOVY; C7 C6 while an engine is busy; C8 issue FSM in I_MOVER).

| counter | shipped (n72) | S1-B (n1511) | R1 (n1510) | **R2 (n1509)** |
|---|---|---|---|---|
| step | 137.120 ms | 120.537 ms | 114.389 ms | **110.407 ms** |
| weight path busy (C0) | 42.19 % (57.845) | 48.40 % (58.338) | 56.44 % (64.561) | 55.37 % (61.135) |
| **FENCE wait (C5)** | 41.96 % (57.538) | 38.50 % (46.409) | 35.12 % (40.169) | **32.78 % (36.196)** |
| mover work (C6) | 24.23 % (33.219) | 20.79 % (25.059) | 21.91 % (25.059) | 22.70 % (25.058) |
| — **MOVX** | 15.45 % (21.179) | 10.80 % (13.019) | 11.38 % (13.018) | **11.79 % (13.018)** |
| — MOVY | 8.43 % (11.562) | 9.59 % (11.562) | 10.11 % (11.562) | 10.47 % (11.561) |
| — MVGO issue | 0.35 % (0.478) | 0.40 % (0.478) | 0.42 % (0.479) | 0.43 % (0.478) |
| mover work, no engine busy (C6 − C7) | 23.96 % (32.855) | 20.49 % (24.695) | 13.02 % (14.896) | 13.24 % (14.615) |
| issue FSM in I_MOVER (C8) | 66.21 % (90.789) | 59.31 % (71.496) | 57.06 % (65.265) | 55.51 % (61.291) |
| layer lane (L_LCYC) | 30.33 % (41.588) | 34.60 % (41.711) | 36.53 % (41.790) | 37.85 % (41.790) |
| state DMA (L_SDMA) | 3.74 % (5.125) | 4.41 % (5.312) | 4.78 % (5.464) | 4.95 % (5.462) |

The chat full step on the R2 bitstream has the same MOVX, MOVY and MVGO work to the microsecond (13.018 /
11.561 / 0.479 ms) with FENCE 35.45 → 31.89 → 29.73 % for S1-B → R1 → R2 and the layer lane 43.72 % at R2
(**D**, `evidence/qwen9b/sr/n1602_sr16_decision_table.log:37-49`).

**What each rung removed** (stream, ms/token, **D**, `evidence/qwen9b/sr/n1602_sr16_decision_table.log:53-55`):

| step | FENCE | MOVX | MOVY | layer lane | step |
|---|---|---|---|---|---|
| shipped → S1-B | −11.129 | −8.160 (elision) | 0.000 | +0.123 | −16.583 |
| S1-B → R1 | −6.240 | 0.000 | 0.000 | +0.079 | −6.148 |
| R1 → R2 | −3.973 | 0.000 | −0.001 | 0.000 | −3.982 |

R1 and R2 removed FENCE wait only; MOVX work (13.018 ms/token) has been untouched since S1's elision. R3 is the
only rung aimed at it.

## 3. R3 expected, three ways, and the band

**What the model's R3 does** (**D**, n1600). At R2 every matvec has either 0 or 4 live MOVX (120 fully
elided, 129 with four), so R3 turns 516 live MOVX into 129 broadcasts and zeroes 387 siblings: 2,427,816 cycles
= 9.711 ms TB = exactly 75.00 % of the live MOVX window (`evidence/qwen9b/sr/n1600_sr16_r3_census.log:17-20`).
On the one-lane schedule that shortens the lane by 9.711 ms, and the lane then waits 1.535 ms more on weight
streams: net 2,044,160 cycles = 8.177 ms TB/token, ×1.0848 (`evidence/qwen9b/sr/n1600_sr16_r3_census.log:36`).
The staging buffer (b) removes 7.283 ms and waits 1.016 more: 6.267 ms, ×1.0637 (`evidence/qwen9b/sr/n1600_sr16_r3_census.log:37`).
The census's caveat — a real broadcast waits on the LATEST of the four channels' readers
(`evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md:771-773`) — was modelled here as a sensitivity (the carrier MOVX
inherits all four siblings' done- and stream-edges, 1,893 extra edges): same makespan to the cycle, post-check
clean (`evidence/qwen9b/sr/n1600_sr16_r3_census.log:32-34`). With double-banked XWINs the bank a broadcast writes
was last read two matvecs earlier, so (an inference, not traced per edge) no sibling's reader is ever the binding one.

**Board translation.** On silicon the board's MOVX per token is 1.0054 × the TB's live MOVX and the FENCE wait
1.0075 × the model's lane-idle-on-stream (`evidence/qwen9b/sr/n1602_sr16_decision_table.log:69`), so the
model's components carry over at about 1:1. The hard ceiling on any R3 saving is 3/4 of the MEASURED MOVX:
9.764 ms/token (`evidence/qwen9b/sr/n1602_sr16_decision_table.log:70`).

| form | how | (a) chat full | (a) stream | (b) chat full | (b) stream |
|---|---|---|---|---|---|
| (i) ratio | measured R2 × MODEL ratio (×1.0848 / ×1.0637) | 8.876 | 9.826 | 8.704 | 9.635 |
| (i′) ratio × R2's kept gain 0.9507 | the fraction of its TB gain R2 kept on silicon | 8.842 | 9.788 | 8.678 | 9.606 |
| (ii) absolute | measured R2 − the MODEL's TB saving (8.177 / 6.267 ms) | 8.769 | 9.782 | 8.624 | 9.603 |
| (ii′) absolute × lowest retention 0.8877 | the worst board/TB saving of any rung (R1 on chat) | 8.699 | 9.695 | 8.572 | 9.538 |
| (iii) census-share | measured R2 − siblings × MOVX board/TB + idle rise × FENCE board/TB (8.218 / 6.299 ms) | 8.772 | 9.786 | 8.627 | 9.605 |

All **D** from MODEL inputs: `evidence/qwen9b/sr/n1602_sr16_decision_table.log:71-82`.

**Which form to trust: (ii)/(iii), the absolute saving.** Three reasons, all from this round's silicon:
* **The saving is a fixed number of aclk cycles.** Board/TB per rung (**D**,
  `evidence/qwen9b/sr/n1602_sr16_decision_table.log:58-65`): S1 0.9959, R2 1.0028 on the stream; R1 1.0523
  (BM1's MVANY board/TB is 1.0622, `evidence/qwen9b/bm/BM1_BOARD_IDLE.md:61`; why R1's saving grew by about
  that much is not shown — both R1 and R2 removed FENCE wait only, §2).
  R3 removes MOVX, an aclk mover job whose MEASURED board/TB is 1.0054 — that, not a mechanism story, is the
  support for carrying its saving over at about 1:1.
* **The ratio form over-predicts on chat by construction**: SR8's P1/P2 and SR15's P2′ ran 0.6–2.6 % over, while the
  absolute forms P3 and P1′ landed within +0.05 … +0.52 % (`evidence/qwen9b/sr/SR15_R2_BOARD.md:172-174`, `evidence/qwen9b/sr/SR8_R1_BOARD.md:146-148`).
  The chat step carries attention time nothing overlaps, so a ratio dilutes and cycles do not.
* **(ii) and (iii) agree to 0.004 tok/s** although (iii) is built from the measured counters and (ii) from the
  model's net.

**The recommended band** (MODEL-derived; low = (ii′); stream: central = (iii), high = the highest form; chat:
high = (iii), where the ratio forms are excluded, central = the band's midpoint)
(**D**, `evidence/qwen9b/sr/n1602_sr16_decision_table.log:84-89`, `evidence/qwen9b/sr/n1650_sr16f1_midpoints.log:18-21`):

| | chat full (decode step) | stream census |
|---|---|---|
| **R3 form (a)** | **8.70 – 8.77 tok/s, central ≈8.74** (8.735; ×1.063–×1.072; the ratio forms, 8.84–8.88, are excluded on chat as the known over-predictor) | **9.70 – 9.83, central 9.79** (×1.070–×1.085) |
| R3 form (b) | 8.57 – 8.63, central ≈8.60 (8.600; ×1.048–×1.054; ratio forms 8.68–8.70 excluded) | 9.54 – 9.64, central 9.61 (×1.053–×1.064) |

**Why the chat top is not the central.** The top, (iii) 8.772, is what R3 gives if the board keeps its whole
TB saving, as R2 did on chat: 3.8960 ms measured against SR13b's corrected static saving of 3.8692 ms,
retention 1.0069 (`evidence/qwen9b/sr/n1650_sr16f1_midpoints.log:22`; the corrected makespans are SR9's note,
`evidence/qwen9b/sr/SR15_R2_BOARD.md:184`). The 0.9698 at `evidence/qwen9b/sr/n1602_sr16_decision_table.log:65`
uses the uncorrected 4.0173 ms and enters no number here. R1 kept only 0.8877 on chat, so the midpoint is quoted
as the central.

After R3 (a) the stream step is expected at about 102.19 ms with FENCE 36.93 % and MOVX 3.18 % of it
(`evidence/qwen9b/sr/n1602_sr16_decision_table.log:76`).

### 3.1 The R2 residual — what it says, and whether R3 is exposed

Silicon kept ×1.0361 of R2's TB ×1.0379 on the stream, while R1 matched to four digits. **The absolute saving
was kept in full**: 995,482 cycles/token on the board against 992,702 on the TB (1.0028) (**D**,
`evidence/qwen9b/sr/n1602_sr16_decision_table.log:60`). The ratio shortfall is the denominator: the board's R2
step is 1.0548 × the TB's, 5.733 ms/token longer (`evidence/qwen9b/sr/n1602_sr16_decision_table.log:63`), and
BM1 puts that excess in engine-busy time (DDR streaming slower than the TB's memory model,
`evidence/qwen9b/bm/BM1_BOARD_IDLE.md:69`). So the residual does **not** point at extra waits or extra DMA-queue
stalls in the r2 order. SR11b's stall is one SLD stall per token, 17,212 cycles, diagnosed on the chip TB
(`evidence/qwen9b/sr/SR11b_R2_PASS.md:138-139`; the board has no per-command window to check it against); the r1 order measured 8 such stalls on token 4 against the
shipped order's 7 (`evidence/qwen9b/sr/n1191_sr11b_dma_diag.log:122-123`).

**R3's exposure:** the same dilution applies (the ratio will again land a little under the TB's, which is why
the band leads with the absolute form). An r3 order may move DMA commands and add queue stalls that no
order-only rule predicts (SR11b, `evidence/qwen9b/sr/SR11b_R2_PASS.md:143-146`); at 0.069 ms each, even eight
more would be 0.55 ms/token, about 7 % of the saving — inside the band's low end.

## 4. What R3 costs

| item | form (a) direct x-push bus | form (b) staging buffer | source |
|---|---|---|---|
| RTL | ≈150 lines over seq_movers, seq_unit, matvec_chan and both _ipi.v wrappers | ≈120 lines in seq_movers only | spec §1.3, `docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md:341-344` |
| block design | ≈15 lines of create_project.tcl, ≈45 new BD nets per channel (≈180), registered both ends | none | `docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md:320-330` |
| floorplan | one new aclk datapath from seq_0 (SLR1) into mvchan_0 (SLR0, with layer_0) — an SLR crossing | three BRAM36 beside seq_0 | `evidence/qwen9b/g5/G5D_TIMING.md:1062-1066` |
| ISA / validator / model | B17.3 (MOVX chan 0xF = all four), `_movx` for 0xF, every destination XWIN bank free | same | `docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md:346-348`, `docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md:357-358` |
| host admission | a SEQ_CAPS R3 bit and a VERSION admission row (inferred from the plan's Global Constraints, as R1/R2 had; the spec does not list it for R3) | same | the plan's Global Constraints |
| pass | a real broadcast node (not emittable today: the census only zeroes siblings) | same | `docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md:350-355` |
| chip TB | the TB top must wire the push ports — the round's first TB-top change; unit case in tb_matvec_chan | none; unit case in tb_burst_fabric | `docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md:360-363` |
| build | a campaign like SR14's; the BD change touches seq_0, all four mvchans and the BD, so less of the R2 placement is reusable | a campaign; seq_0 only | SR14 took 17:37 → 03:23 (`evidence/qwen9b/sr/n1601_sr16_round_clock.log:27`) |
| board | a session like SR15 (≈1.3 h) under its own load ruling | same | `evidence/qwen9b/sr/n1601_sr16_round_clock.log:29` |
| expected gain, chat full | +0.52 … +0.59 tok/s | +0.39 … +0.44 | `evidence/qwen9b/sr/n1650_sr16f1_midpoints.log:18`, `evidence/qwen9b/sr/n1650_sr16f1_midpoints.log:20` |

**The timing it has to fit into** (R2's sign-off, build_045_r2_incr): design WNS +0.004 (the GTY TXOUTCLK →
aclk pair inside the XDMA), aclk +0.012 (ATTN_DSP), u_attn +0.012, u_dn +0.015, the xline CE cone +0.032, UI
+0.026 … +0.064, seq_0 +0.247 (`evidence/qwen9b/sr/SR14_R2_BUILD.md:126-133`, `evidence/qwen9b/sr/SR14_R2_BUILD.md:150-157`).
R2 closed only inside route_design's in-router re-place, from a post-place WNS of −0.791
(`evidence/qwen9b/sr/SR14_R2_BUILD.md:182-188`): **one placement's margin**. On the ship every worst family
path is SLR0 → SLR0 and ATTN_DSP is exactly 0.000 (`evidence/qwen9b/g5/G5D_TIMING.md:1052-1059`); form (a)'s new
path lands in that SLR. SLLs are not the constraint (4,303 of 17,280 used, `evidence/qwen9b/g5/G5D_TIMING.md:1065-1066`).

**Wall clock** (commit stamps, **E**, `evidence/qwen9b/sr/n1601_sr16_round_clock.log:7-29`): the whole round, spec
to both rungs on silicon, ran 2026-09-27 11:48 → 2026-09-29 06:29 (≈43 h for R1 + R2). R2's own path, model
(SR11a 06:24) to silicon (SR15 06:29 next day), was ≈24 h, of which the build was ≈10 h and the chip TB ≈5 h.
**Estimate for R3 (a): 1.5–2 days if closure goes as R2's did; add 1–3 days if it needs a spread or a campaign**
(G5D's history). (b): about 1–1.5 days. These are ESTIMATES.

**What else the same effort could buy — the census's answer.** After R2 the FENCE share is 32.78 %; if every
FENCE wait vanished with nothing else moving, the stream step would be 74.21 ms = 13.48 tok/s, the chat step
85.89 ms = 11.64 tok/s (MEASURED-derived upper bounds, **D**, `evidence/qwen9b/sr/n1602_sr16_decision_table.log:92-93`).
That is not reachable: the MODEL's dependency critical path (unlimited lanes, R2 buffers, elision) is 86.733 ms
TB = **11.027 tok/s** board-scaled; R2 sits 17.854 ms TB above it and R3 (a) takes 8.177 ms of that, 45.8 %
(**D**, `evidence/qwen9b/sr/n1602_sr16_decision_table.log:94-95`). That path is made of weight streams 51.119 ms,
layer commands 31.468 ms and one MOVX per matvec 3.237 ms (**T**, `evidence/qwen9b/ov/n06_all_final.log:827-828`)
— and 3.237 ms is exactly R3's 129 carriers (`evidence/qwen9b/sr/n1600_sr16_r3_census.log:19`). So after R3
≈9.7 ms TB is left to that floor, and it is **inside the sequencer**: the floor assumes unlimited issue lanes,
so the gap is the single issue lane's (the census's own two-lane idea, B2, a second scratch port, is +3.655 ms,
high risk and not proposed, `evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md:634`). **Only below the floor is the
work outside the sequencer**: the weight-stream time (61.1 ms/token of engine busy at R2; BM1's MVANY
board/TB is 1.062, which BM1 reads, as an inference, as DDR streaming slower than the TB) and the layer lane
(41.8 ms/token at R2) — neither is a sequencer item, and neither has a costed plan.

## 5. The decision — options

| option | what you get (chat full / stream, tok/s) | what it costs | main risk |
|---|---|---|---|
| **A. R3 form (a), direct x-push bus** (Q6's choice) — **RECOMMENDED** | 8.70–8.77 / 9.70–9.83 (central ≈8.74 / 9.79; chat top 8.77) | shared ISA+model+pass; ≈150 RTL + ≈15 BD lines; TB-top change; a build campaign with an SLR crossing into SLR0; a board session; ≈1.5–2 days, +1–3 if closure fights | closure on a one-placement margin; the new path lands in the SLR that holds ATTN_DSP at 0.000 |
| B. R3 form (b), staging buffer | 8.57–8.63 / 9.54–9.64 (central ≈8.60 / 9.61; chat top 8.63) | shared ISA+model+pass; ≈120 RTL lines in seq_movers; 3 BRAM36; no BD, no TB-top change; ≈1–1.5 days | smaller: seq_0 has +0.247; the quarter-window cost is an approximation |
| C. Stop the round at R2 | 8.182 / 9.057 (MEASURED, signed off) | nothing more in the sequencer | none new; it leaves R3's own ≈7–8 % (MODEL, §3) unused, and the sequencer's remaining issue-lane gap to the MODEL floor (17.854 ms TB at R2, §4) untouched; the work below that floor (weight streams, layer lane) has no plan yet |

**Why A:** it is the largest single rung the evidence supports (×1.063–×1.072 on the decode step, against R1's ×1.041 and R2's ×1.032), the model it rests on held within 1 % on every measured rung, its
mechanism (13.018 ms/token of MOVX, the same on chat and stream) is counted directly on silicon, and the
dependency part of the census's stated optimism costs 0 cycles when modelled. **How:** do the shared software first (B17.3, model, validator, the pass's broadcast node,
a chip-TB run of an r3 stream — that TB run is the first real test of the 8.177 ms), then (a)'s RTL; **fall back
to (b)** if (a)'s build does not close within an agreed number of rolls — (b) reuses every software piece and
still keeps ≈75 % of (a)'s gain. Choose **C** if 1.5–4 days of RTL/build/board time is better spent on the
weight-stream path, which is the larger term but uncosted.

## 6. What is NOT established

* **No R3 run of any kind.** No r3 stream exists (the pass cannot emit a broadcast), so no chip-TB or board
  number exists; the 8.177 ms is OV1's census replay over BN1 windows, not SR11b's corrected convention (which
  moved R2's prediction by +0.14 %, `evidence/qwen9b/sr/SR11b_R2_PASS.md:246`).
* **That a form-(a) broadcast costs one MOVX window.** The spec prices it as OV1's R3 (siblings free); the push
  rate, the all-four-FIFOs-have-room lockstep and any back-pressure are not measured.
* **Form (b)'s quarter-window sibling cost** is an approximation (spec §6 item 4).
* **Bank forcing is inferred, not modelled:** every live matvec has 0 or 4 live MOVX, so the per-channel XWIN
  bank rotation stays in step (`evidence/qwen9b/sr/n1600_sr16_r3_census.log:18`); the latest-of-four
  sensitivity adds the dependencies but not a bank constraint.
* **Timing is argued, not measured.** Nothing was built; the SLR-crossing risk rests on G5D's and SR14's
  margins.
* **DMA-queue stalls in an r3 order** are not predictable (no order-only rule, SR11b) — bounded in §3.1, not
  measured.
* **R1's chat retention (0.8877)** that sets the band's low end is itself unattributed (SR8 §4).
* **The effort figures are estimates** from this round's commit stamps.
* **The "elsewhere"** (weight streams, layer lane) has no cost or gain estimate here.
* As SR15: one session per condition, context ≤ 511, greedy decode only.

## 7. Judgment calls, each recorded

1. **The addendum's ladder cites 7.293 as BM1 n68.** 7.293 is n72's stream census; n68's chat full step is
   6.770. Both rows are in §1, each under its own workload.
2. **The addendum asks what fraction of the 32.78 % FENCE wait R3 removes.** The model says none: R3 removes
   MOVX lane work and the FENCE wait grows (§3). The census-share form is therefore built on the MOVX share.
3. **The latest-of-four sensitivity** is a new variant in a new tool that imports OV1's model unchanged; it adds
   edges, it does not change the model. It reproduced n120's R2 / R3 / R3buf rows to the cycle first
   (`evidence/qwen9b/sr/n1600_sr16_r3_census.log:23`, `evidence/qwen9b/sr/n1600_sr16_r3_census.log:26`, `evidence/qwen9b/sr/n1600_sr16_r3_census.log:29`).
4. **Stream rows use SR15's n1511/n1510** (R2 bitstream) for S1-B and R1; SR8's n809/n808 equal them.
5. **The band's low end** uses the worst absolute retention any rung showed on either workload (R1 on chat,
   0.8877) rather than R2's (1.0028) — conservative on purpose.
6. **sr16_decision_table.py was fixed once before its logged run** (the ratio form's retention is the kept gain,
   0.9507, not the absolute retention); an unlogged trial run on snoke found it; both versions are committed.
7. **The chat band's high end is (iii), not the log's BAND maximum.** The BAND line prints the highest of all forms (the ratio, 8.876 for (a)); on chat the ratio over-predicted at both measured rungs, so the band stops at the absolute forms (`evidence/qwen9b/sr/n1602_sr16_decision_table.log:85`, `evidence/qwen9b/sr/n1602_sr16_decision_table.log:88`).
8. **An empty `python3 - <<EOF` heredoc** ran once on darthplagueis while editing a file; it executed no
   statement (as SR15 §6 item 9). No number here came from darthplagueis.

## 8. Logs and tools

| file | what |
|---|---|
| `evidence/qwen9b/sr/sr16_r3_census.py`, `evidence/qwen9b/sr/n1600_sr16_r3_census.log` | OV1's model at r = 0: the MOVX census, R2 / R3 / R3buf / latest-of-four |
| `evidence/qwen9b/sr/sr16_round_clock.sh`, `evidence/qwen9b/sr/n1601_sr16_round_clock.log` | the round's commit-stamp clock |
| `evidence/qwen9b/sr/sr16_decision_table.py`, `evidence/qwen9b/sr/n1602_sr16_decision_table.log` | every derived number above |
| `evidence/qwen9b/sr/n1640_sr16_spec_cites_precheck.log`, `evidence/qwen9b/sr/n1649_sr16_spec_cites_LAST.log` | spec_cites precheck (FAIL 0), then LAST, alone, over the first version on the committed tree |
| `evidence/qwen9b/sr/n1650_sr16f1_midpoints.log` | fix round 1: the band midpoints, the gains, R2's corrected chat retention (a logged one-liner on snoke) |
| n1651 | fix round 1: spec_cites LAST, alone, over this version |

## 9. Fix round 1 (the SR16 review, 2026-09-29)

* **I-1.** Option C no longer says "the next ≈10 % needs work outside the sequencer" (unsourced). It now says
  that stopping at R2 leaves R3's own ≈7–8 % unused and the sequencer's issue-lane gap to the MODEL floor
  untouched; §4 says the ≈9.7 ms TB left after R3 is inside the sequencer and only the work below the floor is
  outside it.
* **I-2.** On chat the central is now the band's midpoint (≈8.74 for (a), ≈8.60 for (b)) and 8.77 / 8.63 is the
  top, with the reason (R2's corrected chat retention 1.0069) in §3. The review suggested ≈8.73; the logged
  midpoint is 8.7353 (`evidence/qwen9b/sr/n1650_sr16f1_midpoints.log:18`), so ≈8.74 is quoted.
* **Minors.** (b)'s chat gain is +0.39 … +0.44 (m1). The uncorrected 4.0173 in `evidence/qwen9b/sr/sr16_decision_table.py`
  is labelled as stale and unused by any band (m2). The mechanism story for R1's retention is dropped for the
  measured MOVX board/TB (m3). BM1's 1.062 is labelled as BM1's inference (m4). SR11b's stall is described as a
  TB diagnosis (m5). The latest-of-four claim is limited to its dependency part (m8). The SEQ_CAPS R3 bit is
  labelled as inferred from the plan (m11). The header of `evidence/qwen9b/sr/sr16_round_clock.sh` no longer
  promises a milestone section it never printed (m10). Comment-only tool edits: no committed log moves. Not
  changed: m6 (gate-doc cites beside the re-derived silicon rows; every figure already agrees to the printed
  digit), m7, m9, m12.
