# R3-9a — the chip TB, part 1: rung 1 on the new top, the census, broadcast coverage, mutants (a STOP gate)

Task R3-9a of `docs/superpowers/plans/2026-09-29-r3-broadcast.md` (brief
`.superpowers/sdd/2026-09-29-r3-broadcast/task-R3-9a-brief.md`, its controller addendum and its RESUME
addendum and RESUME addenda #1 and #2). No rtl/ change, no Vivado, no board. Every run was on snoke
through `evidence/qwen9b/sr/sr_run.sh`; logs `n3100–n3146` plus the spec_cites log `n3149`, lettered
suffixes where one step has many runs (SR13a's precedent). `n3147–n3148` are unused.

**Paused three times, resumed three times** (the ledger's PAUSE, PAUSE 2 and PAUSE 3 records,
`.superpowers/sdd/2026-09-29-r3-broadcast/progress.md`, gitignored). PAUSE (user, 2026-09-30 05:13, plan
tokens): the build, stream identity, lint, census, coverage artifacts and mutant builds done, the
shipped-s1 smoke `n3110` running detached. Resume #1 read every untracked log, committed them unchanged
at 5952bc7, re-hashed every binary (all equal their build logs), launched rung 1's other 11 runs
detached (`n3141a–k`, 19:43) and ran the coverage, readers and mutant runs (`n3142–n3146`). PAUSE 2
(user, 21:25, a darthplagueis reboot): the 11 rung-1 runs kept running on snoke (ppid 1). PAUSE 3 (user,
2026-09-30, weekly limit), captured at 22:13: all 11 had finished (last `=== end` 22:11:33). Resume #3
(2026-10-01) verified every log, committed them at 050b71c, finished this document and ran spec_cites.
Nothing was rebuilt and nothing was re-run after a pause; no log was truncated.

**Labels.** **E** = printed by a run of this task, cited to its log line. **T** = transcribed from an
earlier gate, cited to its source. No number here is derived by hand; the one-window extra and the
stall are printed by `evidence/qwen9b/sr/r3_9a_windows.py`.

## Verdict

**GREEN — the STOP gate holds. Nothing to STOP on.**

* **Rung 1: 12 of 12 cycle-identical, tokens IDENTICAL, SEQ_CAPS fab1ca07 on every run** — shipped ×4,
  r1 ×4, r2 ×4 on the new top (§2). A unicast MOVX takes exactly its old path.
* **The layer census bit-exact**: 56,576 cmds, 8,600,034 checks; its table byte-identical to T14A's (§3).
* **Coverage through the REAL engine: 4 seeds × 5 broadcast streams + the held back-pressure run = 24 of
  24 PASS**, bit-exact against `ref/seq_model.py` goldens, every push count equal to the generator's, the
  new landed == sent check run at every broadcast's X_END exit (min margin 3 cycles) (§4). The binding
  cases bind: the late reader holds the broadcast 41,792 cycles behind ch3's FENCE; the +xp_hold on
  channel 2 stalls the broadcast +1,642 cycles with nothing lost; the overlap broadcast runs with all
  four engines busy for every cycle of its window.
* **The one-window fixed extra: +19 cycles** per broadcast over a same-length unicast, at every length
  (256 / 1,024 / 1,536 / 3,072 words) and every seed (§4.3).
* **Mutants: 6 of 6 caught on 4 of 4 seeds** — the late-reader stream mutant (scratch mismatch), bc0
  "the broadcast writes channel 0 only" (scratch mismatch), room0 "lockstep gated on ch0's room only"
  and m1 "the mover ignores room" and m2 "XP_INFLIGHT = 1" (the skid-full lost-word $fatal on channel 2),
  and **xprt0 "XP_RT = 0" on the new check**: `R3-9a COMMIT AT X_END EXIT: channel 1: the mover left
  X_END with 1023 of 1024 pushed words in the XWIN FIFO (XP_RT too short)` (§5). The R3-8 review's I-1
  gap is closed.

## 1. The binary and its identity

| item | value | source |
|---|---|---|
| binary | `tb/obj_dir_seq_chip_srr3b/tb_seq_chip_9b_srr3b`, K=r3b | **E** `evidence/qwen9b/sr/n3100_r3_9a_chip_build_srr3b.log:87` |
| sha256 | 54d174a47e6d8995f4aa8ccd0052707ef2574ae1f3ae3e7c895526c8c8dc8d32 | same line |
| built from | 3f38efd (the landed == sent check in `tb/tb_seq_chip.sv`; rtl/ identical to e4d8166) | **E** `evidence/qwen9b/sr/n3100_r3_9a_chip_build_srr3b.log:37` |
| the engine | rtl/matvec_engine.sv (as ../rtl/matvec_engine.sv) is on the compile line (the REAL engine, not a stub) | **E** `evidence/qwen9b/sr/n3100_r3_9a_chip_build_srr3b.log:43` |
| lint of the chip top | LINT_RC 0, WARNINGS 0 | **E** `evidence/qwen9b/sr/n3104_r3_9a_lint_chiptop.log:9-10` |
| stream identity | 24 `.seq` / `.chip` files re-hashed, 0 mismatches (shipped, r1, r2 × 4 seeds) | **E** `evidence/qwen9b/sr/n3103_r3_9a_stream_identity.log:30` |

Every run log below prints the binary's sha256 again at its start (`run_sr_chip.sh`'s `=== built` line);
every one is 54d174a4…8d32. `n3101` was a scratch identity script with a bash parse bug (it compared
a hash as a number); `n3102` (scratch, fixed) and `n3103` (the committed `r3_9a_stream_ident.sh`)
supersede it — both 24/24 MATCH.

## 2. Rung 1 — R3 moves neither shipped, nor r1, nor r2

Twelve runs of `evidence/qwen9b/sr/run_sr_chip.sh` on srr3b (`K=r3b`), each with `--cycles-equal
<reference>`, `--tokens-ref evidence/qwen9b/s4/S4_REPLAY.md` and `+caps_expect=fab1ca07` on its command
line (line 3), the binary path `tb/obj_dir_seq_chip_srr3b/tb_seq_chip_9b_srr3b` (line 6) and its
sha256 54d174a4…8d32 re-hashed at start (line 7). In every log: line 30 `TB_SEQ_CHIP PASS`, line 32
`SEQ_CAPS fab1ca07 == +caps_expect fab1ca07`, line 34 `CYCLES IDENTICAL TO THE REFERENCE`, line 37
`TOKENS IDENTICAL TO THE SHIPPED RECORD`, line 40 `SR_CHIP … control: PASS`, line 41 `=== rc : 0`,
line 42 `=== end` (**E**).

| stream | seed | reference cycles (**T**) | measured on srr3b (**E**) | tokens | log |
|---|---|---|---|---|---|
| shipped | s1 | 196,706,821 | 196,706,821 IDENTICAL | IDENTICAL | `evidence/qwen9b/sr/n3110_r3_9a_chip_s1_shipped.log:30-42` |
| shipped | s2 | 196,707,670 | 196,707,670 IDENTICAL | IDENTICAL | `evidence/qwen9b/sr/n3141a_r3_9a_chip_s2_shipped.log:30-42` |
| shipped | s3 | 196,707,670 | 196,707,670 IDENTICAL | IDENTICAL | `evidence/qwen9b/sr/n3141b_r3_9a_chip_s3_shipped.log:30-42` |
| shipped | s4 | 196,706,833 | 196,706,833 IDENTICAL | IDENTICAL | `evidence/qwen9b/sr/n3141c_r3_9a_chip_s4_shipped.log:30-42` |
| r1 | s1 | 162,967,117 | 162,967,117 IDENTICAL | IDENTICAL | `evidence/qwen9b/sr/n3141d_r3_9a_chip_s1_r1.log:30-42` |
| r1 | s2 | 162,965,710 | 162,965,710 IDENTICAL | IDENTICAL | `evidence/qwen9b/sr/n3141e_r3_9a_chip_s2_r1.log:30-42` |
| r1 | s3 | 162,965,710 | 162,965,710 IDENTICAL | IDENTICAL | `evidence/qwen9b/sr/n3141f_r3_9a_chip_s3_r1.log:30-42` |
| r1 | s4 | 162,967,195 | 162,967,195 IDENTICAL | IDENTICAL | `evidence/qwen9b/sr/n3141g_r3_9a_chip_s4_r1.log:30-42` |
| r2 | s1 | 157,010,908 | 157,010,908 IDENTICAL | IDENTICAL | `evidence/qwen9b/sr/n3141h_r3_9a_chip_s1_r2.log:30-42` |
| r2 | s2 | 157,011,556 | 157,011,556 IDENTICAL | IDENTICAL | `evidence/qwen9b/sr/n3141i_r3_9a_chip_s2_r2.log:30-42` |
| r2 | s3 | 157,011,490 | 157,011,490 IDENTICAL | IDENTICAL | `evidence/qwen9b/sr/n3141j_r3_9a_chip_s3_r2.log:30-42` |
| r2 | s4 | 157,010,986 | 157,010,986 IDENTICAL | IDENTICAL | `evidence/qwen9b/sr/n3141k_r3_9a_chip_s4_r2.log:30-42` |

References: shipped = S4's counts (`evidence/qwen9b/ov/SV1_S1_VERIFY.md:146-148`, from
`evidence/qwen9b/s4/S4_REPLAY.md:398-401`); r1 = SR5b's, as re-measured by SR13a
(`evidence/qwen9b/sr/n1314_sr13a_chip_s1_r1.log:33`, `evidence/qwen9b/sr/n1315_sr13a_chip_s2_r1.log:33`,
`evidence/qwen9b/sr/n1316_sr13a_chip_s3_r1.log:33`, `evidence/qwen9b/sr/n1317_sr13a_chip_s4_r1.log:33`);
r2 = SR13a's whole-run cycles (`evidence/qwen9b/sr/n1349a_sr13a_chip_s1_r2.log:30`,
`evidence/qwen9b/sr/n1349b_sr13a_chip_s2_r2.log:30`, `evidence/qwen9b/sr/n1349c_sr13a_chip_s3_r2.log:30`,
`evidence/qwen9b/sr/n1349d_sr13a_chip_s4_r2.log:30`). **Zero cycle delta on all twelve**: a unicast
MOVX, and everything else these three streams do, takes exactly its old path on the R3 netlist plus the
new TB check. The 11 runs `n3141a–k` ran in parallel under the memory watcher: peak 15 processes, total
RSS 0.721 GiB (`evidence/qwen9b/sr/n3141l_r3_9a_rung1_memwatch.log:92`).

## 3. The layer census control

`TB_LAYER_CENSUS PASS: 56576 cmds, 8600034 checks bit-exact` (**E**,
`evidence/qwen9b/sr/n3125_r3_9a_layer_census.log:76`), equal to SR13a's PASS line (**T**,
`evidence/qwen9b/sr/n1320_sr13a_layer_census.log:78`). The per-opcode table
`evidence/qwen9b/s4/census_r3b.txt` has sha256 98b9451c…93c5, byte-identical to T14A's
`evidence/qwen9b/s4/census_t14a.txt` (**E**, `evidence/qwen9b/sr/n3126_r3_9a_census_table_vs_t14a.log:7-9`).

## 4. Coverage through the REAL engine

**Order.** R3-7's prediction 82d2677 is an ancestor of HEAD, checked first by both the generator
(`evidence/qwen9b/sr/n3130_r3_9a_cov_gen_s1.log:7`) and every run driver
(`evidence/qwen9b/sr/n3143a_r3_9a_cov_control_s1.log:7`).

**Artifacts** (`evidence/qwen9b/sr/r3_9a_cov_gen.sh`, `n3130–n3133`, one per seed): each of the five
broadcast streams is VALID at {R1,R2,R3} and REFUSED at {R1,R2}, {R1} and {} on its broadcast record; its
golden comes from `tb/scripts/gen_seq_chip_vectors.py --caps R1,R2,R3` (which replays the stream through
`ref/seq_model.py`). `R3_9A_COV_GEN s1: ALL PASS` (`evidence/qwen9b/sr/n3130_r3_9a_cov_gen_s1.log:501`
and its three siblings at the same line). The late-reader MUTANT stream is REFUSED by the model
(`RunningChannelError`) and written with the correct stream's golden for the chip TB to fail.

**Runs** (`evidence/qwen9b/sr/r3_9a_cov_run.sh`, K=r3b, +caps_expect=fab1ca07):
* control, 4 seeds (`n3143a–d`), each with the five streams, bcast_bp's held run
  (`+xp_hold=2:43307:2000`) and the late-reader mutant: `R3_9A_COV_RUN s1 control: ALL PASS`
  (`evidence/qwen9b/sr/n3143a_r3_9a_cov_control_s1.log:223`, siblings at the same line);
* timeline, 4 seeds, unheld (`n3142a–d`, `evidence/qwen9b/sr/n3142a_r3_9a_cov_timeline_s1.log:193`) and the
  held bcast_bp (`n3144a–d`, `evidence/qwen9b/sr/n3144a_r3_9a_cov_hold_timeline_s1.log:47`): ALL PASS;
* the readers over those CSVs (each CSV's sha256 checked against its run log): `n3145`.

### 4.1 Per stream, per seed (control runs)

| stream | what it covers | s1 | s2 | s3 | s4 | broadcasts / words per channel (TB = generator) | X_END exits checked |
|---|---|---|---|---|---|---|---|
| bcast | ng 32/48 into both banks, ng 64/96 bank 0, MVGOs on all four; same-length unicasts on ch2/ch3/ch1 | PASS | PASS | PASS | PASS | 6 / 10,240 | 6 |
| bcast_overlap | a bank-1 broadcast while NO-WAIT bank-0 MVGOs run on all four | PASS | PASS | PASS | PASS | 2 / 3,072 | 2 |
| bcast_bp | the 3,072-word broadcast, unheld | PASS | PASS | PASS | PASS | 1 / 3,072 | 1 |
| bcast_bp + `+xp_hold=2:43307:2000` | **lockstep back-pressure**: ch2's ui_clk held 2,000 cycles mid-broadcast | PASS | PASS | PASS | PASS | 1 / 3,072 | 1 |
| bcast_ragged | 1,021 elements at word 1024, 1,019 at odd word 1281, a zero-length broadcast | PASS | PASS | PASS | PASS | 5 / 2,559 | 4 (a zero-length MOVX goes straight to S_DONE, `rtl/seq_movers.sv:652`) |
| bcast_late | **the late reader + the forced bank**: bank-1 broadcast behind ch3's long NO-WAIT XBANK MVGO | PASS | PASS | PASS | PASS | 2 / 2,048 | 2 |

Lines for s1 (**E**, `evidence/qwen9b/sr/n3143a_r3_9a_cov_control_s1.log`): bcast 33/35/36, overlap
62/64/65, bp 91/93/94, ragged 120/122/123, late 149/151/152, held bp 175/180/182/183 (`SR_CHIP … PASS`,
`PUSH COUNT = GENERATOR`, the R3-9a X_END line). The siblings `n3143b–d` carry the same lines at the
same numbers. Every PASS is `TB_SEQ_CHIP PASS`: every scratch word, XRF, TCNT and PC equal to the golden,
SEQ_CAPS read back fab1ca07 == +caps_expect. Every X_END line reports landed == sent on every built
channel and a min margin (exit cycle − last push-leg FIFO write) of **3 cycles** (e.g.
`evidence/qwen9b/sr/n3143a_r3_9a_cov_control_s1.log:29`).

### 4.2 The binding cases bind (timeline readers, `n3145`)

* **Lockstep back-pressure.** Holding channel 2's ui_clk for 2,000 aclk cycles from cycle 43,307 (≈3,000
  cycles into the 12,523-cycle broadcast window at cycle 40,307 of every seed's unheld timeline)
  stretches the broadcast's window to 14,165: **+1,642 cycles**, the unicast before it +0, the whole
  stream +1,642 (**E**, `evidence/qwen9b/sr/n3145_r3_9a_timeline_readers.log:105-109`; s2–s4 identical,
  lines 203–207, 301–305, 399–403). The push stalled on all four channels together (one mover,
  one window), every channel still received 3,072 words (`evidence/qwen9b/sr/n3143a_r3_9a_cov_control_s1.log:175`), and the
  result is bit-exact (line 180). The channel held is 2, not 0, so mutant room0 (gated on ch0's room) is
  caught (§5).
* **The late reader.** The FENCE on ch3 before the bank-1 broadcast lasts 41,792 cycles with ch3's engine
  busy 41,732 of them and ch0–2 idle (**E**, `evidence/qwen9b/sr/n3145_r3_9a_timeline_readers.log:134`):
  the broadcast waited for the late reader. Ch3's consumers read the FORCED bank and ch3's bank 0 stays
  intact — bit-exact (§4.1). Removing the wait is the late-reader mutant, which fails (§5).
* **Overlap.** The bank-1 broadcast (pc 8) and the unicast after it run with all four engines busy for
  every cycle of their windows: `SR13A_OVERLAP_TL: OVERLAPPED` (**E**,
  `evidence/qwen9b/sr/n3145_r3_9a_timeline_readers.log:98`, s2–s4 at 196, 294, 392).

### 4.3 The one-window measurement

Every coverage stream carries a unicast MOVX of a broadcast's length. Broadcast window − unicast window
(**E**, `evidence/qwen9b/sr/n3145_r3_9a_timeline_readers.log:52-54`, `evidence/qwen9b/sr/n3145_r3_9a_timeline_readers.log:122`):

| length (elements / words) | broadcast window | unicast window | broadcast − unicast | ratio |
|---|---|---|---|---|
| 1,021 / 256 | 1,124 | 1,105 | **+19** | 1.01719 |
| 4,096 / 1,024 | 4,235 | 4,216 | **+19** | 1.00451 |
| 6,144 / 1,536 | 6,307 | 6,288 | **+19** | 1.00302 |
| 12,288 / 3,072 | 12,523 | 12,504 | **+19** | 1.00152 |

The same on all four seeds. The fixed extra is a constant +19 cycles — the three extra closing STATUS
reads R3-7 named (`evidence/qwen9b/sr/R3_7_PREDICTION.md:111-113`), and far below the "hundreds of cycles
per broadcast" that would matter against HELD's half-width (`evidence/qwen9b/sr/R3_7_PREDICTION.md:130-131`).
R3-9b applies it to the 129 broadcasts per token (`evidence/qwen9b/sr/R3_7_PREDICTION.md:124-127`). The
synthetic unicast windows match the r2 stream's own (4,216 here; 4,216.99 mean there, **T**,
`evidence/qwen9b/sr/R3_7_PREDICTION.md:122`).

## 5. The negative controls — every mutant must FAIL

Mutant binaries: git-archive snapshots of 3f38efd, each ONE changed line, own obj_dir
(`evidence/qwen9b/sr/sr13a_mut_build.sh` with `evidence/qwen9b/sr/r3_8_mutants.sh`'s sets; **E**,
`evidence/qwen9b/sr/n3140_r3_9a_mut_builds.log:13-112`). Each run log re-hashes the binary and prints
n3140's recorded sha beside it (equal in all five, line 38–39 of each `n3146` log).

| mutant (brief's name) | the change | stream | caught | the failure line (s1; s2–s4 the same) |
|---|---|---|---|---|
| late-reader stream mutant | the FENCE before the bank-1 broadcast masks ch0 instead of ch3 | bcast_late_mut | 4/4 | `too many scratch mismatches` (`%Fatal: tb_seq_chip.sv:1079`), `SR_CHIP r3_9a_bcast_late_s1_mut control: FAIL`, `THE MUTANT FAILED, as required:` `MEM[8a28] = 0258, expected 0461` (`evidence/qwen9b/sr/n3143a_r3_9a_cov_control_s1.log:211-219`; s2–s4 the same at line 218) |
| **bc0** (M1: the broadcast writes ch0 only) | `xp_v_q    <= {3'd0, xp_fire};` (`evidence/qwen9b/sr/n3140_r3_9a_mut_builds.log:56`) | bcast | 4/4 | `MEM[8200] = 0000, expected 04a2` → `too many scratch mismatches` (`evidence/qwen9b/sr/n3146c_r3_9a_mut_bc0_bcast.log:74-75`; total `evidence/qwen9b/sr/n3146c_r3_9a_mut_bc0_bcast.log:192`) |
| **room0** (M2: the push gated on ch0's room only) | the room AND taken over xp_room_q OR 4'hE (channels 1–3 forced ready; `evidence/qwen9b/sr/n3140_r3_9a_mut_builds.log:76`) | bcast_bp + hold ch2 | 4/4 | `matvec_chan 2: x-push word 750 arrived with the 8-entry skid FULL (a lost word …)` (`evidence/qwen9b/sr/n3146d_r3_9a_mut_room0_bcast_bp_hold.log:74-75`; total line 188) |
| m1 (R3-8 M1: the mover ignores room) | the room AND taken over xp_room_q OR 4'hF (every channel forced ready; `evidence/qwen9b/sr/n3140_r3_9a_mut_builds.log:16`) | bcast_bp + hold ch2 | 4/4 | the same skid-FULL $fatal on channel 2 (`evidence/qwen9b/sr/n3146a_r3_9a_mut_m1_bcast_bp_hold.log:74-75`; total line 188) |
| m2 (R3-8 M2: XP_INFLIGHT = 1) | `localparam int XP_INFLIGHT   = 1;` (`evidence/qwen9b/sr/n3140_r3_9a_mut_builds.log:36`) | bcast_bp + hold ch2 | 4/4 | `… skid FULL (a lost word: XP_INFLIGHT 1 under-sized)` (`evidence/qwen9b/sr/n3146b_r3_9a_mut_m2_bcast_bp_hold.log:74-75`; total line 188) |
| **xprt0 (XP_RT = 0)** | `localparam int XP_RT         = (XP_FWD_STAGES + XP_RET_STAGES) * 0;` (`evidence/qwen9b/sr/n3140_r3_9a_mut_builds.log:96`) | bcast | 4/4 | **`R3-9a COMMIT AT X_END EXIT: channel 1: the mover left X_END with 1023 of 1024 pushed words in the XWIN FIFO (XP_RT too short)`** (`evidence/qwen9b/sr/n3146e_r3_9a_mut_xprt0_bcast.log:71-72`; total `evidence/qwen9b/sr/n3146e_r3_9a_mut_xprt0_bcast.log:176`) |

xprt0 fails on the NEW check, at the X_END exit of the first broadcast, before the four STATUS round
trips after which the R3-8 `done` check (which never fired on this mutant) would look. With the real
XP_RT = 4 the same check passes with a 3-cycle margin (§4.1). This closes the R3-8 review's I-1: before
3f38efd no test would fail if the mover's XP_RT wait were wrong (the late-word $fatal in matvec_chan
cannot fire, tb_matvec_chan checks its own retire model, and tb_seq_chip compared only at `done`, after
four STATUS round trips); now a too-short XP_RT is caught on the first broadcast, on every seed.

**Reading the skid-FULL lines.** m1, room0 and m2 all trip the same sim-only assertion
(`rtl/matvec_chan.sv:818`) on channel 2 — the held channel — at the same cycle and word (750). The
assertion's message names the instance's XP_INFLIGHT parameter ("XP_INFLIGHT 5 under-sized" for m1 and
room0, whose XP_INFLIGHT is unchanged; "XP_INFLIGHT 1" for m2); for m1 and room0 the cause is the mover
pushing past channel 2's room, which is exactly what the lockstep gate (`&xp_room_q` over all four
channels) prevents in the real design. That the room0 mutant — gated on channel 0's room only — loses a
word on channel 2 while the unmutated binary passes the same held run bit-exact with every channel
receiving 3,072 words is the lockstep's proof: the held channel's room stalls the push to all four.

Each mutant's binary was re-hashed before its run and equals n3140's record (m1 e9d46019…, m2 51983281…,
bc0 4d5d76d1…, room0 f85d01f0…, xprt0 9a61d5b5…; **E**, each `n3146` log lines 38–39, and
`evidence/qwen9b/sr/n3140_r3_9a_mut_builds.log:30`, `:50`, `:70`, `:90`, `:110`). Totals: `R3_9A_MUTANT
<set> on <stream>: 4 of 4 seeds CAUGHT` (`evidence/qwen9b/sr/n3146a_r3_9a_mut_m1_bcast_bp_hold.log:188`,
`evidence/qwen9b/sr/n3146b_r3_9a_mut_m2_bcast_bp_hold.log:188`, `evidence/qwen9b/sr/n3146c_r3_9a_mut_bc0_bcast.log:192`,
`evidence/qwen9b/sr/n3146d_r3_9a_mut_room0_bcast_bp_hold.log:188`, `evidence/qwen9b/sr/n3146e_r3_9a_mut_xprt0_bcast.log:176`).

## 6. Judgment calls

1. **Log numbering.** The plan put rung 1 at `n3110–n3121`; the resume addendum and the resume dispatch
   gave the resuming agent `n3141–n3149`. Rung 1's other 11 runs are `n3141a–k` (and `n3141l` the
   memory watcher), coverage `n3142–n3145`, mutants `n3146a–e`, spec_cites `n3149`; `n3147–n3148`
   unused (resume #3 needed no re-run: no log was truncated).
2. **The hold placement** `2:43307:2000` was chosen from the unheld timelines (the broadcast window starts
   at cycle 40,307 on every seed, `n3142a–d`): ≈3,000 cycles in, 2,000 cycles long — far more than the
   32-entry XWIN FIFO plus the 8-entry skid need to fill. The held timeline shows the stall landed
   inside the broadcast (§4.2).
3. **Mutants on four seeds each**, not one, because the TB rule asks for four seeds on every TB run;
   each mutant runs on the stream where its own check bites (bc0 on bcast's scratch compare; m1, m2,
   room0 on the held bcast_bp's skid check; xprt0 on bcast's X_END-exit check).
4. **Scratch drivers.** The timeline readers (`n3145`) and the mutant runs (`n3146`) were driven by
   two short scratch scripts under `tb/scripts_scratch/r3_9a/` (gitignored); each log prints its
   driver's full text first, so the log carries its own provenance. No committed tool was changed.
5. **Timeline mode is passive**: the unheld timeline runs pass with the same push counts and X_END lines
   as the control runs, so the readers' numbers are the control runs' numbers.
6. **`FABLE5_MODEL=unset` in the run headers.** Every chip-TB run here replays a committed, re-hashed
   stream (`n3103`) or a synthetic stream generated in `n3130–n3133`; no reference, emitter or pass ran
   in this task's runs, so the operating-point rule does not bind them — the same header R3-8's logs carry
   (e.g. `evidence/qwen9b/sr/n3046_r3_8_spec_cites_LAST.log:4`).
7. **The lockstep is shown by its effect, not by a per-channel trace.** The timeline records one MOVER
   window per broadcast (one mover feeds all four channels), so the stall of channels 0, 1, 3 behind held
   channel 2 is read from the single window's +1,642 stretch, the unchanged 3,072 words on every
   channel, and the room0 mutant's lost word (§5) — not from four per-channel push traces.

## 7. What is NOT established here

* **No r3 stream has run on the chip TB.** The four real r3 streams, their
  cycle counts against R3-7's committed prediction, and the band verdict are R3-9b's (`n3150–n3199`).
* The one-window extra (+19 cycles) is measured on synthetic streams only; its application to the
  129 broadcasts per token is R3-9b's.
* Nothing about the full build, its timing bar or the board (R3-10 onward); this task ran no Vivado.
* The census control is on the shipped stream's layer TB (unicast only); it does not exercise a
  broadcast.
* **The AXI-Lite XWIN collision has no chip-TB run** (added by R3-9b, read from the RTL): it is covered
  at unit level (`tb/tb_matvec_chan.sv:584-624`; `evidence/qwen9b/sr/R3_8_RTL.md:169`, `evidence/qwen9b/sr/R3_8_RTL.md:184-185`). A SEQ
  stream cannot collide with it: the XWIN register (`rtl/matvec_chan.sv:348`, reg `10'h009`, byte 0x24)
  is the host's legacy path; the sequencer's AXI-Lite master belongs to the mover for its whole job
  (`rtl/seq_unit.sv:906`, `rtl/seq_movers.sv:925`), and the mover writes only CTRL/STATUS/WBASE/BEATS/
  SHAPE/XPTR/RESPTR, never 0x24 (`rtl/seq_movers.sv:180-187`); a CSRWR to `0x1c24` could reach it only
  between mover jobs, i.e. never during a push.
* **ng 64/96 cannot be broadcast into bank 1** (added by R3-9b): bank 1 starts at word XBANK_WORD = 1536
  (`ref/seq_format.py:529`) and an ng-64 vector is 2,048 words, past the 3,072-word window (refused,
  `ref/seq_format.py:615-617`); so §4.1's "ng 32/48 into both banks, ng 64/96 bank 0" is complete as run.
