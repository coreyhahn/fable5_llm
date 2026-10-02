# RD9 — the 9B on silicon (Task 15, G6)

Task 14-B closed a bitstream at **WNS 0.000 / WHS +0.001** with zero failing
endpoints and no waiver, and said in its own §11 that "nothing here is a board
measurement … Task 15 is the first time any of this touches the BCU-1525."
**This document is where that becomes one.** The user approved programming the
board with it on 2026-09-08.

**The headline in one line:** the 9B design is resident, its VERSION was read
back off the silicon, 5,845 MiB of weights upload and verify per piece, the
DDR state region reads back **bit-exact against the emitter's `state_final.bin`**,
and **all four model seeds produce exactly the tokens `evidence/qwen9b/g4/G4A_REPLAY.md` §4.1a
recorded** — 24 tokens, zero mismatches, 36,886 post-halt state checks per run.
**7.2928 tok/s** measured, in both conventions, with both lanes separated for
the first time.

**Two rungs are BLOCKED and are reported as blocked, not approximated**: chat
and long context (§8), whose scope §20 makes precise. **Four defects were
found on hardware** and are written up rather than fixed (§14).

> **FIX ROUND 1, 2026-09-09.** Sections 4.2, 8.1, 9.1-9.2, 10.2a, 12.1, 13.1,
> 13.2, 18.1, 19.1 and 20 are this round's, and four claims in the first
> revision are WITHDRAWN in them: the citation-gate "31 → 8" credit (§19), the
> EMBLOG2 "real write" inference (§9.1), "launched detached" (§2.2, §13.1),
> and "the single cleanest statement this census supports" about the layer
> term (§10.4). The board was NOT reprogrammed and no DDR byte was written:
> the round's two board rungs (`054`, `055`) are AXI-Lite reads and one
> restored CSR.

---

## 0. HOW TO READ EVERY NUMBER BELOW — stated before the numbers

* **T** = transcribed from a named log in this directory. **D** = derived,
  with the arithmetic shown. **S** = stated by a source, cited.
* **Every number below was produced ON SNOKE**, through
  `evidence/qwen9b/run.sh`, whose header records `=== host: snoke`, the tree
  sha, the command and the interpreter, and whose footer records `=== rc:`
  and `=== end:`. A log is cited only after both exist. Nothing numeric ran
  on darthplagueis; the board is on snoke and so is every tool that touched it.
* **The margin is zero and it was produced once.** Every verdict here is
  reported against that fact. `evidence/qwen9b/g5/G5D_TIMING.md` §11: "A re-run of the same
  command is not guaranteed to reproduce 0.000." What this gate can say is
  what the one placement that exists does at speed, repeatedly — and it says
  it with the repeat counts beside it.
* **Every rung's verdict is against its OWN basis**, not one bound: the
  reprogram against the CHARTER flow, identity against the netlist word,
  residency against the artifact's bytes, lockstep against §4.1a, perf
  against S4's and Task 12's comparands, the clip rail against §4.4.
* **JTAG-volatile only.** `sw/program_fpga.sh` ran once (§2). No flash path
  was used, `--no-lock` was never passed, and the lock's .nolock.log sidecar
  does not exist (`001`).
* **The instruments in this directory are NEW and were untracked when the
  runs that used them executed**, so those logs' `=== tree:` lines read
  `+dirty` or the parent sha; `evidence/qwen9b/run.sh`'s tree line uses `git diff --quiet`,
  which tests tracked files only. Each instrument is committed with the
  evidence it produced, in the same commit.
* **A log written from 2026-09-11 on carries its own OPERATING POINT, not
  just its environment.** `evidence/qwen9b/run.sh` emits one more header
  line, and it is the law read out of the tools' own module rather than the
  operator's memory:
  `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:11` is
  `=== rs_f: derived=7 (tag 9b) env=unset rider=0`, indexing
  `ref/layer_fixed.py:103`, `RS_F_BY_TAG = {"0.8b": 8, "2b": 8, "4b": 8, "9b": 7}`.
  A header that says `FABLE5_RS_F=unset` records the ABSENCE of an override
  and NOT the value in force. That distinction cost this campaign one
  17.08 h replay (§22.11) and it is why A′ exists (§22.12a). Read line 11
  before trusting any number that came out of `ref/`.

**THE VERDICT OF THIS GATE, stated once and before the numbers.** **Every
rung of Task 15's amended ladder is PASS on the resident silicon** —
identity, dry, the weight pack per piece and whole, the state region, the
EMBLOG2 write, lockstep at four seeds, the perf census, the clip rail, chat,
sampled chat, the template check and the long context — **with three
deviations, each named where it lives**. (1) The **nch=1 rung cannot exist
on this artifact set**: it is discharged by an address-map REFUSAL measured
on the resident manifest, not by a run (§4.2, §16 item 9). (2) The **SIGHUP
ruling was MEASURED AND DECLINED**, so `sw/program_fpga.sh`,
`sw/stage1_hw_bringup.sh` and `sw/test_ctl.sh` are unchanged (§13). (3) The
**counter wrap withdrew exactly one quoted number** — the long run's
`L_LCYC`, on a 527-launch session (§14.5) — and nothing else.

**THE LONG-CONTEXT LOCKSTEP IS ESTABLISHED at the derived operating point —
AND THE CEILING IS UNCHANGED.** `149` is `LONGCTX_LOCKSTEP: PASS 504/504`
(2 decode) and `171` is `LONGCTX_LOCKSTEP: PASS 526/526` (24 decode,
positions 502..525, the chip's token rank 1 in the reference at every step).
`106`'s FAIL was the reference at `RS_F` 8 (§22.11), and §8.7a is superseded
(§22.12b). **The ceiling stays T < 512 BY ANALYSIS until `denom` is
widened** (§16 item 11): fourteen of those steps ran at T ≥ 512 and all
fourteen agree, which is evidence the worst case was not reached in that
session and NOT proof that it cannot be. **The two halves travel together
everywhere in this document, this paragraph included.**

**And what this gate does NOT establish, in the same breath**: the
**reproducibility of the 0.000 closure**, which is one placement produced
once (§16 item 3); the **`USER_CLOCK_ROOT X2Y2` choice's dependency on the
placer keeping the layer in SLR0** (§12, and `evidence/qwen9b/g5/G5D_TIMING.md` §11);
**prefill, first-token latency and any user-facing turn time**, which §10
does not model (§16 item 5); the **perplexity point, DECLINED** on the
gate-port clamp (§12.1); and **the context ceiling, which `171`'s PASS does
NOT lift** (§16 item 11). §16 is the full list; this paragraph is its index,
not its replacement.

---

## 1. WHAT RAN, WHERE, ON WHICH TREE

**Every row is `=== host: snoke`.** Times are the wrapper's own
`=== date:` → `=== end:`. Non-zero `rc` rows are kept deliberately and each
is explained where it is cited.

| # | log | tree | start → end | rc | what |
|---|---|---|---|---|---|
| 001 | `001_etiquette_resident_readback.log` | `5a08f0b` | 19:28:37 → 19:28:45 | 0 | etiquette, and the resident bitstream TEED (§2.1) |
| 002 | `002_reprogram_9b_build041.log` | `f57fca2` | 19:29:43 → 19:31:00 | 0 | **the safe reprogram** (§2.2) |
| 003 | `003_identity_9b.log` | `f57fca2` | 19:31:24 → 19:31:24 | 0 | **identity: VERSION, CALIB, UPTIME** (§3) |
| 004 | `004_tool_selftests_after_version_move.log` | `f57fca2+dirty` | 19:33:22 → 19:33:22 | 1 | the selftests under the wrong interpreter (§3.2) |
| 005 | `005_tool_selftests_after_version_move.log` | `f57fca2+dirty` | 19:33:38 → 19:33:44 | 0 | the selftests, `/home/cah/.venv/bin/python` (§3.2) |
| 006 | `006_dryrun_lay9b_s1.log` | `b5cb735` | 19:34:43 → 19:35:05 | 0 | the dry rung (§4.1) |
| 007 | `007_live_lay9b_s1.log` | `b5cb735` | 19:35:38 → 19:35:41 | 1 | the first live run, and the pad-size defect (§4.2) |
| 008 | `008_live_lay9b_s1_scratch65k.log` | `b5cb735+dirty` | 19:36:38 → 19:36:41 | 0 | the same run, corrected (§4.2) |
| 009 | `009_live_tok9b_4seeds.log` | `b5cb735+dirty` | 19:36:56 → 19:39:14 | 0 | **the first tokens off 9B silicon**, 4 seeds (§4.3) |
| 010 | `010_model_9b_s1_upload_and_run.log` | `b5cb735+dirty` | 19:39:29 → 19:40:17 | 0 | **the whole model, seed 1** (§7.1) |
| 011 | `011_model_9b_s2s3s4.log` | `0be8334` | 19:41:07 → 19:55:43 | 0 | **seeds 2, 3, 4** (§7.1) |
| 012 | `012_hup_trap_red.log` | `0be8334+dirty` | 19:57:15 → 19:57:25 | 2 | the HUP harness's own first mistake (§13) |
| 013 | `013_hup_trap_red.log` | `0be8334+dirty` | 19:57:39 → 19:57:39 | 1 | the HUP RED — **it did not fire** (§13) |
| 014 | `014_hup_trap_green.log` | `0be8334+dirty` | 19:59:04 → 19:59:10 | 0 | the HUP GREEN — **rc 0 after a hangup** (§13) |
| 015 | `015_hup_trap_semantics.log` | `0be8334+dirty` | 19:59:29 → 19:59:38 | 0 | **the measurement that settles it** (§13) |
| 016 | `016_weight_pack_and_contrived_miss.log` | `aa55828` | 20:01:50 → 20:04:01 | 1 | the pack rung, audited at the wrong moment (§14.1) |
| 017 | `017_weight_pack_and_contrived_miss.log` | `aa55828` | 20:04:53 → 20:10:44 | 0 | **the pack rung: whole-pack hash + the contrived miss** (§5) |
| 018 | `018_state_region_smem_golden.log` | `d52bddc` | 20:11:33 → 20:11:39 | 0 | **the state region, BIT-EXACT both ways** (§6) |
| 019 | `019_perf_census_two_lanes.log` | `d52bddc` | 20:11:50 → 20:11:52 | 1 | the census on a dirty state region (§14.2) |
| 020 | `020_perf_census_two_lanes.log` | `d52bddc` | 20:12:36 → 20:12:39 | 0 | **the perf census, both lanes, both conventions** (§10) |
| 021 | `021_seqmodel_gate_s1.log` | `d52bddc+dirty` | 20:13:14 → 20:13:15 | 1 | the reference gate without `--base` (§7.3) |
| 022 | `022_seqmodel_gate_s1.log` | `d52bddc+dirty` | 20:14:05 → 20:14:06 | 1 | the reference gate without `FABLE5_MODEL=9b` (§7.3) |
| 023 | `023_clip_counters.log` | `d52bddc+dirty` | 20:14:11 → 20:14:15 | 0 | the clip rail, banner naming the wrong binary point (§11) |
| 024 | `024_seqmodel_gate_s1to4.log` | `8962544` | 20:15:07 → 21:18:43 (**1 h 3 m**) | 0 | **the reference gate, all 4 seeds, `G4A_SEQGATE: ALL PASS`** (§7.3) |
| 025 | `025_clip_counters_rsf.log` | `8962544+dirty` | 20:17:36 → 20:17:40 | 0 | **the clip rail, `rs_f` read from the manifest** (§11) |
| 026 | `026_chat_seq_9b_attempt.log` | `8962544+dirty` | 20:17:52 → 20:18:48 | 0 | **chat: BLOCKED, three ways** (§8) |
| 027 | `027_pack_audit_after_chat_attempt.log` | `8962544+dirty` | 20:19:13 → 20:20:37 | 1 | what attempt [1] cost (§14.3) |
| 028 | `028_restore_9b_pack.log` | `8962544+dirty` | 20:20:54 → 20:21:44 | 0 | the pack restored, and §14.1 reproduced (§14.1) |
| 029 | `029_channel_load_split.log` | `8962544+dirty` | 20:22:01 → 20:22:02 | 1 | the per-channel split; the traffic line threw (§10.3) |
| 030 | `030_state_traffic_and_region.log` | `8962544+dirty` | 20:22:20 → 20:22:20 | 0 | **the DDR traffic per token and the region map** (§10.3) |

**FIX ROUND 1** (2026-09-09, `=== tree: 9bcacd6`; the board was NOT
reprogrammed and no DDR byte was written). **Five of the eleven rows read
`+dirty`** — `060` through `064`, while this document's own edits were in
flight — and they are marked below, the way the first-round table marks its
own (re-review round 2, I-B: the header used to say "clean on every row",
which is the one claim a provenance table may not round off):

| # | log | start → end | rc | what |
|---|---|---|---|---|
| 054 | `054_nch_ladder.log` | 21:56:17 → 21:56:18 | 0 | **the plan's nch=1 rung, RUN** — the contract, the 25-artifact enumeration, the address-map refusal (§4.2) |
| 055 | `055_emblog2_write_proof.log` | 21:57:34 → 21:57:35 | 0 | **EMBLOG2 written to 12 and read back 12, then restored to 13** (§9.2) |
| 056 | `056_chat_seq_9b_model_set.log` | 21:59:01 → 21:59:07 | 0 | the chat refusals **with `FABLE5_MODEL=9b` set**, both ways, plus the board-free depth probe (§8.1) |
| 057 | `057_chat_scope_geometry.log` | 22:00:38 → 22:00:40 | 0 | what `sw/chat_seq.py` / `ref/seq_chat.py` are pinned to, and what the 9B stream derives (§20) |
| 058 | `058_tool_selftests_final_tree.log` | 22:00:50 → 22:00:56 | 0 | the two tool selftests on the FINAL tree (§3.2) |
| 059 | `059_spec_cites_selftest.log` | 22:01:06 → 22:01:08 | 1 | `spec_cites --selftest`: **all six negative controls CAUGHT**; the positive control carries the ledgered FAIL 8 (§19) |
| 060 | `060_chat_selftests.log` (`+dirty`) | 22:12:54 → 22:13:24 | 0 | `chat_seq --selftest` under both model selections — 364 passed unset, and where it dies at 9B (§20.4) |
| 061 | `061_cite_drift_fix1_plan.log` (`+dirty`) | 22:18:31 → 22:18:35 | 1 | the drift plan: `REPAIR 18 COLLATERAL 2`, `UNSAFE` (§18.1) |
| 062 | `062_cite_drift_fix1_fix.log` (`+dirty`) | 22:19:24 → 22:19:27 | 0 | `FIXED 25 citation(s) in 4 document(s)`, the spec excluded (§18.1) |
| 063 | `063_cite_drift_fix1_verify.log` (`+dirty`) | 22:19:33 → 22:19:37 | 1 | the verify BEFORE the spec was repaired by hand — 38 problems, all its (§18.1) |
| 064 | `064_cite_drift_fix1_verify_final.log` (`+dirty`) | 22:20:46 → 22:20:49 | 0 | **`O3_CITE_DRIFT VERIFY PASS (0 problem(s))`** (§18.1) |

`065`-`070` (the superlative pairs on the final text, §17, and the closing
`spec_cites` runs, §19.2) are not tabulated here for the reason `053` was not: they
run AFTER this document is final, so a row describing them would be a claim
about a log that does not exist yet. They are cited where they are used.

**FIX ROUND 2** (2026-09-09/10, `=== tree: 4662b06` → `09ed6d7`, some rows
`+dirty` while the code was being written; **the board was NOT reprogrammed
and not one weight byte was written**):

| # | log | start → end | rc | what |
|---|---|---|---|---|
| 071 | `071_state_region_red.log` | 22:49:46 → 22:50:14 | 1 | **the RED**: case `[22]` against the pre-fix tree, `369 passed, 11 failed`, first line `SeqExec got region=None` (§8.3) |
| 072 | `072_state_region_green.log` | 22:50:23 → 22:51:00 | 0 | the GREEN: `chat_seq selftest: 380 passed, 0 failed`, `seq_chat: PASS` (§8.3) |
| 073 | `073_template4_repin.log` | 22:52:45 → 22:53:16 | 0 | **A**: the per-model 4-chan pin, and the artifact's sha against `evidence/qwen9b/s4/001_emit_9b_s1.log:203` (§8.3) |
| 074 | `074_ref_cost_9b.log` | 22:55:22 → 23:00:06 | 0 | **the reference's real cost at 9B** — 131.2 s / 149.3 s per step, board-free (§8.7) |
| 075 | `075_template_9b_jinja.log` | 22:58:47 → 22:58:55 | 0 | **the template against the 9B checkpoint's own jinja** (§8.6) |
| 076 | `076_ctx_ceiling_red.log` | 23:05:00 → 23:05:30 | 1 | the E RED: `389 passed, 8 failed`, `chat_seq 512 / hwmap 4096 / seq_chat 512` (§8.3) |
| 077 | `077_ctx_ceiling_green.log` | 23:05:43 → 23:06:25 | 0 | the E GREEN: `397 passed, 0 failed`, the per-model ceiling table, the live refusal (§8.3) |
| 078 | `078_chat_greedy_9b.log` | 23:07:16 → 23:07:28 | 0 | **greedy chat on 9B silicon** (§8.4) |
| 079 | `079_chat_sampled_9b_4seeds.log` | 23:07:46 → 23:08:30 | 0 | **sampled chat, 4 seeds** (§8.5) |
| 080 | `080_chat_verify_9b.log` | 23:08:56 → 23:53:44 (**44 m 48 s**) | 0 | **`--verify`: 22 of 22 steps `== seq_model`** (§8.6a) |
| 081 | `081_cite_drift_fix2_plan.log` | 23:16:51 → 23:16:55 | 1 | the drift plan: `REPAIR 162 COLLATERAL 3`, `UNSAFE` (§18.2) |
| 082 | `082_cite_drift_fix2_fix.log` | 23:21:24 → 23:21:30 | 0 | `FIXED 136 citation(s) in 25 document(s)`, three excluded (§18.2) |
| 083 | `083_longctx_9b.log` | 23:54:45 → 23:57:20 | 0 on the wrapper; **steps [3] and [6] rc 1** (§8.7) | **the long-context rung: 526 steps, KV row 525** — and the two counter reads that died (§8.7) |
| 084 | `084_longctx_lanes.log` | 23:58:53 → 00:00:10 | 0 | the lanes over a third 526-step run, the traffic at T = 526, `LONGCTX DETERMINISM: IDENTICAL` (§8.7) |
| 085 | `085_tool_selftests_fix2.log` | 23:32:10 → 23:32:57 | 0 | the four tool selftests on the final code tree (§8.3) |
| 086 | `086_lane_counter_width.log` | 00:00:48 → 00:01:00 | 0 | **the counter-wrap discriminator**: 40.573 ms/step on 43 launches (§14.5) |

`087`-`104` (the two drift passes, the superlative pairs
and the closing `spec_cites` runs) run after this document is final, for the same reason
`065`-`070` did, and are cited where they are used.

**FIX ROUND 3** (2026-09-10, `=== tree: 2762662` → `e8e35a0`; the board was
NOT reprogrammed, no weight byte was written, and only `110` touched it at
all):

| # | log | tree | start → end | rc | what |
|---|---|---|---|---|---|
| 105 | `105_longctx_lockstep_smoke.log` | `2762662` | 00:41:46 → 00:43:50 | 0 | the replay's smoke: `--selfcheck` renders both per-step arms and all three verdicts, then one real step at 118.4 s (§8.7) |
| 106 | `106_longctx_lockstep_ref.log` | `2762662` | 00:44:07 → 2026-09-10 **17:48:48** (**17.08 h**) | 1 | **the 526-step board-free reference replay**, detached, `nice -n 10` (§8.7a). It was IN FLIGHT and NOT COMMITTED as fix round 3 closed, and it was committed in Task 15-D once its `=== rc:` existed. Its `LONGCTX_LOCKSTEP: FAIL at step 503` is **the REFERENCE at the wrong `RS_F`, not the chip** — §22.11. **The rule fired once on the way (round-4 review m7):** `bf00696` swept the still-running log into a commit and `4e6e09e` took it back out |
| 107 | `107_i1_i2_red.log` | `6815e3c+dirty` | 00:56:32 → 00:57:19 | 0 | the frozen `--nch 1` footprint at `4662b06` and at `47e07cd`, measured **in each tree's own worktree**; its step [3] splice read this tree's already-fixed `ref/seq_chat.py`, so only the I-1 arms fired — superseded by `108` (§8.3) |
| 108 | `108_i1_i2_red.log` | `6815e3c+dirty` | 00:58:46 → 00:59:21 | 0 | **the RED**: the new cases against `47e07cd`'s implementation **inside its own worktree** — `372 passed, 8 failed`, every FAIL naming its own reason (§8.3) |
| 109 | `109_i1_i2_green.log` | `e8e35a0` | 01:03:00 → 01:03:48 | 0 | **the GREEN**: `chat_seq 408/0`, `seq_chat PASS`, `seq_run 2785/0`, `hwmap PASS`, the frozen footprint back to `4662b06`'s byte for byte, the `T_MAX` table, and m15's measured cost (§8.3) |
| 110 | `110_chat_verify_9b_rd3.log` | `e8e35a0` | 01:04:35 → 01:50:38 (**46 m 03 s**) | 0 | **the board rung after the tool edits**: `--verify`, 22 of 22 steps `== seq_model`, `0 MISS` → `upload SKIPPED` (§8.6a) |

`111`-`…` (this round's drift pass, the superlative pair and the closing
`spec_cites` run) come after this document is final, for the same reason
`065`-`070` and `087`-`104` did.

**Fix round 3 adds three instruments**: `g6_longctx_lockstep.py` (the
board-free 526-step replay — §8.7), `g6_frozen_footprint.py` (what the
frozen `--nch 1` session uploads, so three trees can be compared byte for
byte — §8.3), and the two shell rungs `g6_i2_red.sh` / `g6_i2_green.sh`.

**The artifact this gate uploaded is the one S4 emitted, checked before the
first byte moved.** The dispatch's standing instruction — verify the digest
of anything you upload against S4's emit logs FIRST — is a rung, and it
holds: `006`/`010`/`017`/`028` all print the stream digest
`9760899df53b3b42…`, which is `evidence/qwen9b/s4/001_emit_9b_s1.log:203`;
the `state.bin` digest `3a716409081f0c54…` is
`evidence/qwen9b/s4/001_emit_9b_s1.log:208` and the manifest's `sha256` (§6);
and the post-run `7bd38ff095ad91a0…` is `evidence/qwen9b/s4/S4_REPLAY.md:239`'s
`final_sha256` (§6). **Every digest this gate wrote or read back traces to
S4's emission**, and `sw/seq_run.verify_state_image` checks the state image
against the manifest BEFORE anything is written, which is the amendment's own
ordering.

**The instruments**, all new, all in this directory: `g6_ident.py` (CSR
identity, no DMA), `g6_residency.py` (whole-pack audit, the contrived miss,
and a driver for `chat_seq`'s own sampler), `g6_state.py` (the region, written
and read verbatim), `g6_census.py` (both lanes, both conventions),
`g6_clip.py` (the residual rail), `g6_superlatives.py` (§17), plus the shell rungs
`g6_board_etiquette.sh`, `g6_pack_rung.sh`, `g6_pack_rung2.sh`,
`g6_state_rung.sh`, and the two HUP instruments `g6_hup_trap.sh` /
`g6_hup_semantics.sh`. Fix round 1 adds three more: `g6_nch.py` (§4.2),
`g6_emblog2.py` (§9.2) and `g6_chat_scope_probe.py` (§20). **Fix round 2
adds four more and two shell rungs**: `g6_ref_cost.py` (what one lockstep
step costs at 9B, board-free — §8.7), `g6_template_9b.py` (the 9B jinja —
§8.6), `g6_kv_depth.py` (how deep the silicon wrote into the KV region —
§8.7), `g6_lane_counters.py` (clear/read the two lanes around a chat
session — §8.7, §14.5), plus `g6_longctx_rung.sh` and
`g6_longctx_lanes.sh`.

---

## 2. THE REPROGRAM

### 2.1 Etiquette, and the readback that had never been teed

`evidence/qwen9b/g5/G5D_TIMING.md` §11 recorded the resident bitstream as build_035 **by
inheritance from `NEXT_SESSION.md`**, and the plan's Step 1 asks for a teed
readback this time, because R-b's attribution of the previously resident
bitstream is `UNCONFIRMED` on record for exactly the want of one. **T**, `001`:

```
=== [7] THE TEED READBACK — what is resident RIGHT NOW
--- resident bitstream identity (AXI-Lite reads only; no DMA)
  MAGIC        0xfab1e001 (OK)
  VERSION      0x54443b9f   build_035_fp2a_exc_po (R-d, the 2B W8 design)
  CALIB        0xf        (ALL FOUR CHANNELS CALIBRATED)
  UPTIME       341947318865471 cycles = 1367789.275 s @ 250 MHz
  layer IDENT  0xfab1e5a0 (OK)   matvec0..3 IDENT 0xfab1c4a0..a3 (OK)
  SEQ IDENT    0xfab1e5e0 (OK)
```

**§11's attribution is CONFIRMED**, and the uptime says how long it had been
there: 1,367,789.275 s = **15.83 days** (D: 341,947,318,865,471 / 250e6 /
86,400), i.e. since 2026-08-24 — the day build_035 was programmed
(`docs/HISTORY.md:703-704`). `g6_ident.py` opens `/dev/xdma0_user` and
nothing else and does zero DMA, so it is safe on an unknown bitstream.

**The board was free and nobody else was on it.** `001` §3: no board tool
running. §4: `board lock /home/cah/r2d2/code/fpga/.fable5_board.lock`,
`fstype nfs4`, `state not held`, and no `--no-lock` escape has ever been
taken. §2 lists both worktrees that share the board —
`/home/cah/r2d2/code/fpga/fable5_llm` at `5a08f0b [main]` and
`/home/cah/r2d2/code/fpga/grok46_llm/fable5` at `8ad8be0 [grok46-qwen2b]`.

**The bitstream was checked against `evidence/qwen9b/g5/G5D_TIMING.md` §11 BEFORE it was
programmed** — size and mtime to the second, plus a digest §11 does not
carry. **T**, `001` §5:

| | expected (`evidence/qwen9b/g5/G5D_TIMING.md` §11) | measured (`001`) |
|---|---|---|
| path | `synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper.bit` | same |
| bytes | 53,074,589 | **53,074,589** |
| mtime | 2026-09-07 20:46:01 | **2026-09-07 20:46:01.495503604 −0600** |
| sha256 | — | `eeeef897495d783aa4eb0b2b555373bbeed36182a4a754089d787b801224f031` |

**The rollback was located and digested in the same breath**, so it would not
have to be found in a hurry: `synth/out_build_035_fp2a_exc_po/bd_wrapper.bit`,
54,072,409 B, 2026-08-24 23:13:19, sha256
`58b06450f8f9b2581d3bd42407771a6c77b99a83f323f5c7fc416d78f7e6847e`. **It was
never needed.** Note the path: it is NOT under `proj/stage1.runs/impl_1/` the
way build_041's is.

### 2.2 The flow, and only the flow

**T**, `002`, 19:29:43 → 19:31:00 = **1 m 17 s**, `rc 0`:

```
=== [1/3] remove the endpoint from the PCI tree (host-hang safety)
removed 0000:82:00.0 from PCI tree
=== [2/3] JTAG program (VOLATILE — never flash): …/bd_wrapper.bit
PROGRAM_OK: /home/cah/…/bd_wrapper.bit
=== [3/3] rescan the PCI tree (exit code so far: 0)
rescan OK: 82:00.0 Serial controller: Xilinx Corporation Device 9038
  board lock HELD: /home/cah/r2d2/code/fpga/.fable5_board.lock (program_fpga.sh bd_wrapper.bit)
  board lock released (program_fpga.sh bd_wrapper.bit)
```

One hold of the shared lock across all three steps, which is the whole point
of the O3 ruling (`evidence/qwen9b/o3/BOARD_LOCK.md` §4.1): the dangerous window is not the JTAG
call, it is `remove → rescan`, during which any other tool's `/dev/xdma0_*`
fd points at a dead endpoint and a host MMIO can kernel-panic snoke.

**HOW IT WAS LAUNCHED IS NOT ON THE RECORD.** An earlier revision of this
paragraph said the sequence was "launched DETACHED (`nohup setsid`) on
purpose", and §13 leaned on it. `evidence/qwen9b/run.sh` records the command
it WRAPS and nothing outside it, and `002`'s `=== cmd:` line reads exactly
`bash sw/program_fpga.sh synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper.bit`.
**The claim is withdrawn**: whether the operator's own shell detached the
wrapper is untranscribed. The reasoning behind it stands as reasoning — every
board step in this campaign is driven over ssh from another host, and the one
thing that must not happen is the controlling connection dying between
`[1/3]` and `[3/3]` — but §13.1 is where it is disposed of, and §13's
conclusion does not rest on it.

**No rollback, no STOP.** The device came back on the first rescan and CALIB
was 0xF on the first read (§3), so neither the rollback branch nor the
zero-margin STOP rule was reached.

---

## 3. IDENTITY — the netlist word, off the silicon

### 3.1 The readback

**T**, `003`, `rc 0`:

```
  CALIB poll   0.0 s of 60 s budget
  MAGIC        0xfab1e001 (OK)
  VERSION      0xc973c18a   build_041_ckr2_AltSpreadLogic_high (Task 14-B, the 9B design)
  CALIB        0xf        (ALL FOUR CHANNELS CALIBRATED)
  UPTIME       9535313840 cycles = 38.141 s @ 250 MHz  (lo 0x385957b0 hi 0x00000002)
  layer IDENT  0xfab1e5a0 (OK)
  matvec0..3 IDENT 0xfab1c4a0 / a1 / a2 / a3 (OK)
  SEQ IDENT    0xfab1e5e0 (OK)
  VERSION MATCHES the expected netlist word 0xc973c18a
```

* **CALIB = 0xF on the FIRST read** — `0.0 s of 60 s budget`. All four DDR4
  channels trained. **No DMA happened before this line**: `001` and `003`
  are AXI-Lite only, and `006` is the first run that moves a byte.
* **UPTIME 38.141 s** at 19:31:24 places configuration at ≈ 19:30:46,
  inside `002`'s `[2/3]`→`[3/3]` window. It is the independent corroboration
  that this is a *fresh* configuration and not the old one answering.

**How the VERSION word is derived, stated rather than assumed.**
`synth/scripts/launch_build.sh:12` computes `VERSION=$(cd "$REPO_ROOT" && git
rev-parse --short=8 HEAD)` and passes it to `synth/scripts/create_project.tcl`, which at
line 252 does `set_property CONFIG.VERSION 0x$BuildVer [get_bd_cells csr_0]`.
So the CSR word is **the eight-hex-digit short hash read as hex** — no
truncation of a longer value, no byte swap. `git rev-parse --short=8
c973c18a` returns `c973c18a`, and that commit is `cites(14A): spec_cites
LAST, on the committed tree — FAIL 0`. **D**: expected word `0xc973c18a`;
**T**: read back `0xc973c18a`.

### 3.2 The version constants, moved only after the readback

`sw/seq_run.py:EXPECTED_SEQ_VERSION` and `sw/infer.py:EXPECT_VERSION` both
moved `0x54443B9F` → `0xC973C18A`, committed in `b5cb735`, **after** `003`
had read the word. Both comments say the value came off the board and name
the log.

**Two further `sw/` changes were needed to RUN, and are declared as such.**

1. **`sw/hwmap.py:SHAPE_ISA_BY_VERSION`** gains `0xC973C18A: SHAPE_ISA_9B`.
   Its own comment already said this row lands "in the SAME edit that moves
   `sw/seq_run.EXPECTED_SEQ_VERSION`". Without it `shape_isa_for_version()`
   raises `UnknownBitstream`, which `sw/tok_meter.py` (the census) and
   `sw/infer.py` both hit before packing an `R_SHAPE` word. **There is still
   no default**: `0xDEADBEEF` still refuses, and the selftest asserts it.
2. **`sw/hwmap.py:SCRATCH_WORDS_BUILT` 32,768 → 65,536** — §4.2.

Plus one docstring line in `sw/chat_seq.py` naming the gated VERSION. No
other behaviour changed.

**The selftests were re-run over the edits. T**, `005`, `rc 0`:
`HWMAP SHAPE_WORD SELFTEST PASS … an UNKNOWN VERSION refuses (build_034
0x4f908df2 and build_035 0x54443b9f are isa=1, build_041 0xc973c18a is
isa=2)`, and `seq_run selftest: 2785 passed, 0 failed`.

**`005` covered the FIRST of three `sw/hwmap.py` edits, and no longer
reproduces on the committed tree.** It ran at 19:33:38, before `34452a4`
shortened that banner (to `(034/035 isa=1, 041 0xc973c18a isa=2)`) and before
`0be8334`'s `SCRATCH_WORDS_BUILT` change, and neither of those got a selftest
re-run — so the quotation above is `005`'s text, not HEAD's. **T**, `058`,
`rc 0`, fix round 1, the same two commands on the FINAL tree
(`=== tree: 9bcacd6`, clean):

```
HWMAP SHAPE_WORD SELFTEST PASS: … an UNKNOWN VERSION refuses (034/035 isa=1, 041 0xc973c18a isa=2)
seq_run selftest: 2785 passed, 0 failed
```

Same verdicts, same 2,785 assertions, on the bytes that are committed. (For
the second edit, `008`'s hardware result — `scratch 65536 words zeroed via
SPTR/SWIN and read back: 0 non-zero` — is the stronger evidence anyway.)

`004` is the same command one interpreter earlier and is kept because it is
what happened: `sw/seq_run.py` imports numpy and the system `python3` on
snoke has none. `/home/cah/.venv/bin/python` is the interpreter for every
numeric tool in this gate, and `evidence/qwen9b/run.sh`'s `=== venv:` line records that
`ref/.venv/bin/python` is ABSENT there — the standing hazard.

---

## 4. THE DRY RUNGS

### 4.1 The dry rung — and what it says about the state region

**T**, `006`, `rc 0`:

```
--- board: MAGIC=0xfab1e001 VERSION=0xc973c18a CALIB=0xf  SEQ=REFUSED
  SEQ CSRs untouched: --dry-run: the SEQ CSR window is not touched
  weights   15 images, 211 MiB -> 0x10000000..0x134a2000 (row-split over chans [0, 1, 2, 3])  [readback OK]
  state DN  24 MiB zeroed -> 0x380000000 (chan 3)  [8 witnesses zero]
  state CV  1 conv image(s) -> 0x389800000  [readback OK]
  211 MiB written, 211 MiB read back and compared, 22.2s
--- DRY RUN COMPLETE: DDR images uploaded and readback-verified; the SEQ CSR window was never accessed.
```

The amendment's rung order is honoured by the tool itself: the state region
rides the same H2C path as the weights and is uploaded before any SEQ CSR is
touched. **The region lives on DDR channel 3** — bits [33:32] of the
manifest's 34-bit bases, `0x3_8000_0000`.

### 4.2 nch=1 — the rung, RUN, and what it returned

**The plan's "then nch=1, then nch=4" cannot be run at 9B, and fix round 1
measured that rather than asserting it.** The first revision of this section
retired the rung on the sentence "every 9B stream reports `meta nch = 4`",
with one artifact's `[auto-detected from meta nch]` line (`006`:19) behind
it. Review round 1 called that retiring a required rung on a sentence. **T**,
`054`, `rc 0`, `G6_NCH: PASS (0 problem(s))`, under the lock, AXI-Lite reads
only, replaces it with three measurements:

**(1) The contract — nch is a property of the ARTIFACT, not a flag.**
`054` reads it out of the source it governs: `sw/seq_run.py` declares **no**
`--nch` option; the mode comes from the stream's own `meta["nch"]`
(`sw/seq_run.py:374`), and `--four-chan` — whose own help says "The mode is
otherwise auto-detected from `meta['nch']`; this flag just asserts it"
(`sw/seq_run.py:2877`) — only asserts it. So "run it at nch=1" is a request
for an nch=1 **stream**, and there is no flag that can conjure one.

**(2) The enumeration — the 25 the glob reaches.** `054` prints
`meta["nch"]` for **25** 9B artifacts under `tb/scripts/w9/` and its
`emit2/` repeats: the twelve at the top level (`lay9b_s1..4.e4`,
`model_9b_s1..4.e4`, `tok9b_s1..4.e4`) and the thirteen emit-twice repeats.
**All 25 read `nch=4`; at nch=1: 0.**

Two corrections from re-review round 2 (I-C), because both words were doing
work they had not earned. **They are not "committed"**: `tb/scripts/w9/` is
gitignored (`.gitignore:36`, whose own comment says the tree is regenerable
and that its sha manifest lives in `evidence/qwen9b/g4/G4A_REPLAY.md`), so
`git ls-files tb/scripts/w9` returns nothing. In this campaign "committed" is
a provenance word and zero of the 25 are. **And 25 is not all of them**:
`g6_nch.py`'s two globs are `tb/scripts/w9/*.seq.json` and
`tb/scripts/w9/emit2/*/*.seq.json`, while the tree holds **36** — eleven
more under `rep10/` and one under `probe/`. The reviewer read all twelve and
every one carries `"nch": 4`, so the conclusion is untouched; the sentence
that said "all of them, not one" was 25 of 37 and now says which 25.

The enumeration is not vacuous: the same reader, on the same run,
reports `nch=1 (key absent -> 1)` for `tb/scripts/w4/model_v2_s1.e.seq.json`
and `nch=4` for `tb/scripts/w4/model_v2_s1.e4.seq.json` — at 2B an nch=1
stream exists and this reader finds it. **M-9**: that control exercises
`meta.get("nch", 1)`'s DEFAULT (the key is absent from the 0.8B/2B manifest),
not an artifact that explicitly encodes `"nch": 1`. It shows the reader can
return something other than 4; it does not show it reading a written 1.

**(3) The refusal — why no 9B one can exist.** `054` offers the **resident**
artifact's own manifest (`tb/scripts/w9/model_9b_s1.weights.json`, 249 images,
4,091,805,696 B = 3,902.2 MiB) to `sw/hwmap.plan_weights` at `nch=1` — the
nch-INDEPENDENT pack every pre-R-c artifact encodes — and records what comes
back:

```
  window          W_BASE 0x10000000 .. EMB_BASE 0x60000000 = 1,280 MiB per channel
  nch=1           REFUSED: AssertionError: weight images (249 wids, 4091904000 bytes
                  packed from 0x10000000) reach chan 0 0x103e58000, past EMB_BASE
                  0x60000000 — move EMB_BASE or split the images across DDR channels
  nch=4           ACCEPTED — busiest channel 978.6 MiB = 76.5 % of the window
```

**An nch=1 9B model stream is refused by the address map before any board
tool could be pointed at one.** That is
`evidence/qwen9b/g4/G4A_REPLAY.md` §3.1's measurement
(`evidence/qwen9b/g4/013_inventory_9b.log`) — "there is no 1-channel 9B
stream, and that is measured" — re-made here on the artifact the board is
actually holding. Task 3's repack is four-channel by construction, and
`ref/seq_format.py:1368`'s `assert not (self.repack and self.nch < 2)` is the
emitter's half of the same fact. `--four-chan` is passed explicitly on every
run from `008` onward so the mode is asserted rather than auto-detected.

`054` reads MAGIC/VERSION/CALIB/UPTIME **before and after** and prints both:
`0xc973c18a`, CALIB `0xf`, unchanged, UPTIME advanced 0.252 s. **The rung
moved no byte on the board.**

### 4.2a The pad was the wrong size

**The first live SEQ run on the 9B netlist ran correctly and then the HOST
crashed.** **T**, `007`, `rc 1`:

```
  halted at pc=4090/4091 in 0.017s wall / 15.234 ms device
  STATUS=0x00000004 err=False err_code=0x00 (no error)
  EMBLOG2    13 (8192 B embedding rows)
  state CSR SB_DN=0x38000 SB_KV=0x38180 SB_CV=0x38980  [readback OK]
--- post-halt state vs tb/scripts/w9/lay9b_s1.e4.chip
IndexError: index 42016 is out of bounds for axis 0 with size 32768
```

The golden addresses scratch word 42,016; `SCRATCH_WORDS_BUILT` was 32,768.
The RTL array has been 65,536 words since G3.1 and `build_041` is the first
bitstream that carries it. **The half with teeth is not the read**:
`--zero-scratch` was clearing 32,768 of 65,536 words and reporting the pad
clean, which is precisely the stale-residue failure that flag exists to
prevent. Raised to 65,536; the reverse hazard (a build_034/035 board now
needs a pre-G6 checkout) is written into the constant's own comment.

**T**, `008`, `rc 0`, the same run corrected:
`scratch 65536 words zeroed via SPTR/SWIN and read back: 0 non-zero`, and
`golden 36886 state checks, ALL MATCH`.

### 4.3 The first tokens off 9B silicon

**T**, `009`, `rc 0`, four seeds, four processes, one after another:

| seed | tokens on chip | expected (the artifact's json) | pc | device |
|---|---|---|---|---|
| `tok9b_s1` | `[2380, 6362]` | identical | 2107/2108 | 16.279 ms |
| `tok9b_s2` | `[5290, 4397]` | identical | 2107/2108 | 16.278 ms |
| `tok9b_s3` | `[1235, 4971]` | identical | 2107/2108 | 16.280 ms |
| `tok9b_s4` | `[5591, 703]` | identical | 2107/2108 | 16.278 ms |

`err_code 0x00` on all four, and **36,886 post-halt state checks ALL MATCH**
on each. The device-time spread across four seeds is **0.012 %**
(D: (16.280 − 16.278)/16.279).

---

## 5. THE WEIGHT PACK — per piece, whole-pack, and the contrived miss

Step 3 asks for three things. All three, at 9B, on silicon. **T**, `017`,
`rc 0`, 20:04:53 → 20:10:44.

### 5.1 (a) Per PIECE, not per channel

`sw/seq_run.upload` splits every image with `plan_weight_split` and verifies
each piece **where its own channel holds it** — RD_GATE §4.2's lesson, where
a per-CHANNEL witness let a 61.3 MiB-stale chunk-interleaved LM head answer
with the wrong token and no error anywhere. At 9B that is **1,114 weight
pieces** across 249 images.

**T**, `010`: `5845 MiB written, 5845 MiB read back and compared, 45.7s`
(45.5 s at `017`, 45.8 s at `028`). **D**: 2 × 5,845 MiB / 45.7 s =
**255.8 MiB/s** aggregate over the H2C+C2H pair.

The pack's shape, **T** `010`: 249 images, 3,902 MiB of weights at
`0x10000000`, the embedding 1,940 MiB at `0x60000000`, and
`wid [248] chunk-INTERLEAVED (rung 4 S4)` — the LM head, called out by the
tool itself.

### 5.2 (b) The whole-pack hash — RD_GATE follow-on 2, discharged

Follow-on 2 asks for the witness sample to be **replaced** by a whole-pack
hash rather than made finer. `g6_residency.py --audit` reads back every byte
the host wrote — every weight piece on its own channel, the embedding, and
every conv image — compares each piece against the artifact and folds all of
them into one digest. **T**, `017` §2:

```
  WHOLE-PACK AUDIT  1139 pieces (1114 weight + 24 conv + 1 emb), 5845 MiB read back in 83.0 s (70 MiB/s)
  pack sha256 want  602b008c70fd8aec89bb1174d78fc0ac272ccbc9ebdf8e7fd514d1fef99ea599
  pack sha256 got   602b008c70fd8aec89bb1174d78fc0ac272ccbc9ebdf8e7fd514d1fef99ea599
  PACK IDENTICAL   0 piece(s) MISS of 1139
```

**There is no offset for damage to hide at.** The cost is 83 s for 5,845 MiB
against the sampler's 38 ms for 4,584 KiB — the plan budgeted "~10 s at 9B's
~5.8 GiB" from the 2B's 1,847 MiB in ~3 s; the measured rate is **70 MiB/s
on the C2H read path**, not the ~600 MiB/s that extrapolation assumed, so the
real figure is **83 s**. That is the number a future session should budget.

### 5.3 (c) The contrived miss — and the branch that had never fired

`sw/chat_seq.py:1194-1196` says the whole-pack escalation is
"selftest-proven only — on hardware every observed miss set has been all-187,
which makes the branch a no-op there and unproven". The plan says to contrive
the exercise deliberately. **T**, `017` §4:

```
  CONTRIVED MISS: wrote 4096 B of b'G6-CONTRIVED-MISS-0248' over weight
  model_9b_s1_w248.bin@c0r0 at chan=0 addr=0x454bf800 (piece byte offset
  2160640 of 4325376) — this is EXACTLY the block chat_seq._witness(4325376)
  probes, so the sampling probe cannot miss it
  the bytes that were there: sha256 3fb9fcf02dc3209169ee0be97644ee8a
```

**Exactly how it was contrived**, so nobody has to infer it: one 4,096-byte
DMA write of a repeating ASCII pattern, over wid **248** — the chunk-
interleaved LM head, the image RD_GATE §4.2's blind spot was found in — on
channel 0, at the deterministic offset `_witness()` computes, with the prior
bytes' digest recorded first. Nothing else on the board was touched.

**Both detectors fired, from different directions:**

| detector | verdict | **T** |
|---|---|---|
| whole-pack audit | `PACK DIFFERS 1 piece(s) MISS of 1139`, naming `model_9b_s1_w248.bin@c0r0`, pack sha `021a9697fc6accc8…` | `017` §5 |
| `chat_seq`'s own sampler | `1146 witness blocks … in 39 ms -> 1 MISS` | `017` §6 |
| `chat_seq.reupload_set` | **`1 image(s) missed a witness; the R-d rule escalates to ALL 249 image(s) + the embedding — a miss means the pack is not ours to trust`** | `017` §6 |

**That third line is the branch firing on hardware for the first time.** The
functions driven are `chat_seq`'s own — `build_residency_manifest`,
`probe_residency`, `reupload_set`, imported and called, not reimplemented —
because their residency half carries no template dependency even though the
session half cannot run at 9B (§8).

**And it was undone.** `017` §7 re-uploads the whole pack (45.5 s); §8's
audit reads the same `602b008c70fd8aec…` digest back with `0 piece(s) MISS of
1139`; §9's sampler reports `0 MISS`; and §10 runs the repaired pack and gets
`[2614, 314, 279, 369, 11751, 13]` with `36886 state checks, ALL MATCH`.

---

## 6. THE STATE REGION — the on-chip form of S4's SMEM golden

The amendment asks for the region's final image to be read back and compared
with `state_final.bin`'s `final_sha256`. **A whole-region comparison needs
the board to start where the reference starts**, and
`sw/seq_run.upload_state` deliberately does not put it there: it memsets DN
and writes the conv images but leaves the 128 MiB KV region alone, "which is
128 MiB of DMA this host does not do", because the RTL never reads a KV row
before writing it. `ref/seq_model`'s `StateRegion`, by contrast, is
zero-initialised across all 162,529,280 B. So `g6_state.py --write-initial`
writes `<base>.state.bin` **verbatim, KV included**, and the run then goes
through `--skip-weights`, whose `upload_state(csrs_only=True)` programs the
three base CSRs and writes not one region byte.

**T**, `018`, `rc 0`:

```
--- state region  DN 0x380000000  KV 0x381800000  CV 0x389800000  END 0x389b00000  (155 MiB on DDR channel 3)
  image     …/model_9b_s1.state.bin 162529280 B, sha256 3a716409081f0c54d9bf554b85310e28 == manifest state['sha256'] [OK]
  written   155 MiB -> 0x380000000 (chan 3) in 0.2 s — ALL THREE sub-regions, KV included
  readback  155 MiB … in 0.6 s (257 MiB/s)
  on-chip   sha256 3a716409081f0c54d9bf554b85310e28c66562080865b65da79a99241628e493
  artifact  sha256 3a716409081f0c54d9bf554b85310e28c66562080865b65da79a99241628e493
  STATE BIT-EXACT against model_9b_s1.state.bin
```

then the run (`tokens [2614, 314, 279, 369, 11751, 13]`, `36886 state checks,
ALL MATCH`), then:

```
  on-chip   sha256 7bd38ff095ad91a06de4e5e8ddc5da35179f733e924135d3cf849d8c235e9efe
  artifact  final_sha256 7bd38ff095ad91a06de4e5e8ddc5da35179f733e924135d3cf849d8c235e9efe
  STATE BIT-EXACT against model_9b_s1.state_final.bin
```

**All 162,529,280 bytes, no carve-outs, no excluded ranges.** The emitter's
`final_sha256` for `model_9b_s1` is independently on record at
`evidence/qwen9b/s4/S4_REPLAY.md:239` as `7bd38ff095ad91a0…`, so this closes
the loop from the emitter, through the reference, to the silicon.

**The region map, T `030`:**

| sub-region | base .. top | size | contents |
|---|---|---|---|
| DN | `0x380000000` .. `0x381800000` | 24.00 MiB | 24 blocks × 1,048,576 B |
| KV | `0x381800000` .. `0x389800000` | 128.00 MiB | never host-written |
| CV | `0x389800000` .. `0x389b00000` | 3.00 MiB | 24 × 131,072 B |
| **total** | | **162,529,280 B** | all on **DDR channel 3** |

**The three CSRs, read back on every run** (`006`–`028`, e.g. `018`):
`SB_DN=0x38000 SB_KV=0x38180 SB_CV=0x38980  [readback OK]` — 64 KiB units,
so `0x38000 × 65,536 = 0x380000000` (D). `seq_check_state_bases` refuses a
run whose bases are unset; it never had to.

---

## 7. LOCKSTEP AND THE TOKENS

### 7.1 The tokens, against `evidence/qwen9b/g4/G4A_REPLAY.md` §4.1a

**This is the silicon form of S4's bar.** §4.1a's table and the on-chip
result, side by side. **T**, `010` (s1) and `011` (s2, s3, s4):

| seed | `evidence/qwen9b/g4/G4A_REPLAY.md` §4.1a | **on chip** | verdict | pc | device |
|---|---|---|---|---|---|
| `model_9b_s1` | `[2614, 314, 279, 369, 11751, 13]` | `[2614, 314, 279, 369, 11751, 13]` | **IDENTICAL** | 158535/158536 | 822.793 ms |
| `model_9b_s2` | `[279, 264, 854, 11, 303, 264]` | `[279, 264, 854, 11, 303, 264]` | **IDENTICAL** | 79288/79289 | 822.807 ms |
| `model_9b_s3` | `[313, 430, 2510, 198, 1445, 27180]` | `[313, 430, 2510, 198, 1445, 27180]` | **IDENTICAL** | 79288/79289 | 822.809 ms |
| `model_9b_s4` | `[11, 0, 271, 803, 369, 498]` | `[11, 0, 271, 803, 369, 498]` | **IDENTICAL** | 158535/158536 | 822.787 ms |

**24 tokens, four different prompts, zero mismatches.** `err_code 0x00` on
all four. Note that s2/s3 reach the same six steps on half the records — the
emitter's loop collapse — and take the same device time to 0.003 %, which is
the loop doing what it says.

**The post-halt architectural state**: `golden 36886 state checks, ALL MATCH`
on **every one of the eight full-model runs that ran the check** — `016`
§1, `010`, `011` ×3, `017` §10, `018`, `028` — and on the `009` (×4) and
`008` layer runs at the same count. Thirteen `ALL MATCH` lines in this
directory, and not one mismatch anywhere.

**Repeatability, which is what a zero-margin closure most needs measured.**
The full model ran **eleven** times as a live 6-step program in this session
(`016` §1, `010`, `011` ×3, `017` §10, `018`, `020`, `023`, `025`, `028`;
`017` §1 and §7 are `--dry-run`s and run nothing), **eight of them on seed
1**, and **every one produced its artifact's expected tokens**.

**Nine of the eleven recorded a device time** — `023` and `025` go through
`g6_clip.py`, which calls `seq_start_and_poll` directly and does not print
`sw/seq_run.main`'s `halted at …` line — and those nine are what
`g6_superlatives.py` harvests. Seed 1's six timed runs, **T** from each log:
**822.726, 822.793, 822.795, 822.801, 822.803, 822.806 ms**. **D**: spread
(822.806 − 822.726) / 822.726 = **0.0097 %**. R-d's 2B comparand was
0.0027 % over ten runs; this is the same order, on a design with zero setup
margin. Across all nine timed full-model runs — the six above plus s2, s3
and s4 — the widest spread is (822.809 − 822.726) / 822.726 = **0.0101 %**.

*(This paragraph is the one `g6_superlatives.py` corrected: its first draft
said "six times", listed seven device times, and three of them belonged to
s2/s3/s4. The script harvests the times from the logs itself and classifies a
run by its record count, so the mix-up could not survive it — §17.)*

### 7.2 The `.chip` golden is the on-chip lockstep

The amendment names two silicon lockstep checks and both are green: the
post-halt state against `<prefix>.e4.chip` (36,886 checks, §7.1) and the
region against `final_sha256` (§6). `verify_chip_golden` reads the layer
CSRs **after** the sequencer has halted, which is the arbitration rule.

### 7.3 The reference side — `ref/seq_model.py --gate`

`024` therefore runs **G4a's own script**,
`evidence/qwen9b/g4/run_g4a_seqgate.sh`, which sets `FABLE5_MODEL=9b
FABLE5_RS_F=7` and gates all four seeds. **T**, `024`, 20:15:07 → 21:18:43
(**1 h 3 m**), `rc 0`, last line **`G4A_SEQGATE: ALL PASS (4 artifact(s))`**:

| seed | the amendment's line | tokens |
|---|---|---|
| `model_9b_s1` | `STATE BIT-EXACT (112 block(s) stored; .txt vs .seq vs the emitter's StateImage)` | `IDENTICAL [2614, 314, 279, 369, 11751, 13]` |
| `model_9b_s2` | the same, 112 blocks | `IDENTICAL [279, 264, 854, 11, 303, 264]` |
| `model_9b_s3` | the same, 112 blocks | `IDENTICAL [313, 430, 2510, 198, 1445, 27180]` |
| `model_9b_s4` | the same, 112 blocks | `IDENTICAL [11, 0, 271, 803, 369, 498]` |

`SEQ GATE: PASS` on all four.

**`STATE BIT-EXACT` is the REFERENCE side of §6's silicon result**, and the
two are different questions with the same answer: `024` says the two
independent implementations of B15.1's byte layouts agree (`.txt` vs `.seq`
vs the emitter's `StateImage`, 112 blocks stored per seed); `018` says the
SILICON's 162,529,280 bytes hash to the digest that emitter wrote. Together
they close the loop from the emitter, through the reference, to the chip.

**Two false starts are kept** because they are what a next session will hit:
`021` (`rc 1`) omitted `--base`, which the 9B artifacts need because the
stream prefix (`…s1.e4`) and the generator prefix (`…s1`) differ —
`FileNotFoundError: tb/scripts/w9/model_9b_s1.e4.weights.json`. `022`
(`rc 1`) added `--base` but not the environment: `ValueError: cannot reshape
array of size 524288 into shape (16,128,128)` — `LNH` is 16 unless
`FABLE5_MODEL=9b`, and it is 32 at 9B.

---

## 8. CHAT AND LONG CONTEXT — the block, and the rungs that RETIRED it

> **FIX ROUND 2 (2026-09-09) built the 9B chat path and ran Step 5's rungs
> on the resident silicon.** No reprogram: build_041 has been resident and
> untouched since `002`, and its `VERSION` was read back again at the head
> of every rung below. §8.2 is the verdict; §8 down to §8.1 is the block
> exactly as fix round 1 diagnosed it, kept because it is what the fix was
> built from, and §8.3 says what changed in the tools.


**`sw/chat_seq.py` cannot run a 9B session.** Its three DDR images are BYTE
SLICES of the 0.8B/2B artifact `tb/scripts/w4/model_v2_s1.e`, with the slice
indices and the artifact's sha frozen as constants:
`TEMPLATE_PREFIX` (`sw/chat_seq.py:202`), `TEMPLATE_SHA256`,
`TEMPLATE_NREC = 60495`, `REC_PREAMBLE = (0, 1524)`,
`REC_BODY_FULL = (1526, 16266)`, `REC_BODY_LITE = (1526, 15532)`,
`REC_TCNT = 45751`, `REC_HALT = 60494`. `model_9b_s1.e4` has **158,536**
records.

> **CORRECTED in fix round 1.** This paragraph also said "There is no 9B
> `TurnCompiler` and no code path that derives one." **The second half is
> wrong**, and §20 replaces it: the `--nch 4` path in
> `sw/chat_seq.ChatSession.__init__` does not use the frozen slices at all —
> it calls `derive_geometry`, which reads all nine boundaries out of the
> stream, and compiles through a private clone of `ref/seq_chat.py`
> (`sw/chat_seq.seq_chat_for`). Measured on the 9B artifact at `057`, that
> derivation SUCCEEDS. The frozen slices above govern the `--nch 1` path.
> The block is real and §20 says what it actually consists of.

**The tool at HEAD says so three different ways. T**, `026`:

| attempt | result |
|---|---|
| `--verify --nch 4`, DEFAULT (2B) template | reached the board; **`SEQ halted with err_code=0x10 (layer_chan err_op) at pc=5/1526`**, on the first `CONVW` of the 2B preamble |
| `--verify --nch 4 --template …/model_9b_s1.e4` | refused in `derive_geometry`: **`template geometry: 8 position-indexed LDCs in the body, expected 6`** |
| … `--any-template` as well | the same refusal — `--any-template` drops the sha check, not the geometry check |

The first is **U4 demonstrated rather than asserted**: "there is no 0.8B/2B
back-compat ladder on this bitstream". The 2B stream is SEQ_ISA v1.7 and its
layer ARG words are not what the v2.0 RTL decodes, so the layer answered
`err_op` on the very first command. The second and third are `chat_seq`'s own
N19 guard working: `POS_COPIES` is 6 unless `FABLE5_MODEL=9b`, and the guard
**refuses to derive a stride from a count that does not match the stream**
rather than deriving a wrong one. Its author called that "the better
failure"; this is it failing correctly.

### 8.1 `026` ran with `FABLE5_MODEL` UNSET — and what happens when it is set

`026`'s own header records `FABLE5_MODEL=unset`. Under an unset selection
`POS_COPIES` is 6 (`sw/chat_seq.py:237`), so attempts **[2] and [3]** above
died on the **model-selection guard**, not on anything specific to the 9B
path — and the table did not say so. `docs/USAGE.md`'s troubleshooting row
names exactly that cause ("without `FABLE5_MODEL=9b`"), so the tool knew;
this document did not.

**T**, `056`, fix round 1, the same attempts with `FABLE5_MODEL=9b`
`FABLE5_RS_F=7` exported (the header records both), under the board lock —
`sw/chat_seq.py` takes the lock BEFORE `ChatSession()` and calls
`open_board()` after, so both attempts held the lock and neither opened the
device:

| attempt | result |
|---|---|
| `[4]` `--verify --nch 4 --template …/model_9b_s1.e4` (= `026`'s [2], model selection SET) | the geometry check now PASSES; it refuses one level deeper, on the **frozen artifact gate**: `tb/scripts/w9/model_9b_s1.e4.seq sha256 9760899df53b3b42 != the gated 4-chan template e102e2df0835097d` |
| `[5]` the same selection against the DEFAULT (2B) 4-chan template | the model-select guard fires the OTHER way: `template geometry: 6 position-indexed LDCs in the body, expected 8` |
| `[6]` `--model-only --any-template` on the 9B artifact (**no board, no lock**) | `ChatSession()` SUCCEEDS: the geometry derives, the compiler builds all three images, 324 LDC+EMB records relocate, the 9B tokenizer loads and the templated ids MATCH the 19-id HF rendering. It dies in the VERIFIER: `SLD/SST with no state region: this artifact's manifest carries no state plan (sw/hwmap.plan_state)` |

**Three things follow, and they change the shape of the block.**

1. **The refusal in `[4]` is a real one**: the 4-chan session is gated on
   `TEMPLATE4_SHA256`, which is pinned to the 2B artifact. That is a
   deliberate gate, not an accident, and re-pinning it is a decision with a
   gate behind it, not an edit.
2. **The `026` [1] `err_op` demonstration is only reachable with the model
   selection UNSET.** With `FABLE5_MODEL=9b` the tool refuses the 2B template
   at the geometry gate (`[5]`) and never reaches the board. So U4 stands as
   demonstrated at `026` [1], and it cannot be re-demonstrated under the 9B
   selection — which is itself the guard doing its job.
3. **The compiler is NOT the blocker.** `[6]` gets a 9B turn compiled. §20
   names what is.

**That was the block. §8.2 onwards is what happened when it was lifted.**

### 8.2 THE VERDICT — Step 5's chat rungs, on build_041

**Every row is a run on the resident silicon under the shared lock, with no
reprogram and no flash.** `FABLE5_MODEL=9b` on every one; the artifact is
`tb/scripts/w9/model_9b_s1.e4` and the weight pack is the one §5 left
resident.

| Step-5 rung | verdict | log |
|---|---|---|
| **greedy chat** | **COHERENT and correct**: *"The capital of France is \*\*Paris\*\*."* | `078` |
| **sampled chat, 4 seeds** | **seed-deterministic ×2 IDENTICAL, seed-sensitive on two others** | `079` |
| **`chat_seq --verify`** — lockstep on the chat prompt | **22 of 22 steps `== seq_model`, 0 divergences**; the first four answer tokens are `078`'s first four | `080` |
| **the template vs the 9B checkpoint's OWN jinja** | **PASS**, and it found the `enable_thinking` inversion in the act | `075` |
| **long context, T = 526 > 512** | **RAN**: 526 forward steps, the KV region holds row **525**, three runs token-identical (§8.7). **And it is now reference-verified**: the board-free replay at the derived operating point is `LONGCTX_LOCKSTEP: PASS 526/526`, all 24 decode steps `==` (§22.12b) — **the ceiling is unchanged, §16 item 11** | `083`, `171` |

### 8.3 What changed in the tools — A, B, C, D, E of §20.2

**Five functions, no new compiler**, exactly as §20 scoped it. Board-free
RED then GREEN on every one (`071`/`072`, `076`/`077`):

| # | what landed | where |
|---|---|---|
| **A** | the 4-chan template pin is **per `FABLE5_MODEL`**: the frozen `model_v2_s1.e4` for 0.8B/2B, `tb/scripts/w9/model_9b_s1.e4` for 9B. A NOMINATION of an artifact that already existed — no re-emission | `sw/chat_seq.py:567-578` |
| **B** | `SeqModelVerifier.state_region` builds the artifact's own initial region and `_run` passes it to `ref/seq_model.SeqExec` | `sw/chat_seq.py:3012`, `:3091` |
| **C** | `ChatSession.bring_up_state` WRITES the initial region (never the `csrs_only` path — §14.2) and reads `SB_DN`/`SB_KV`/`SB_CV` back | `sw/chat_seq.py:2399` |
| **D** | the context reset re-zeroes DN **and restores the 24 conv taps** | `sw/chat_seq.py:2442` |
| **E** | `T_MAX` 512 → **4,096 at 9B** in both files (fix round 2 raised it for EVERY selection; fix round 3 made it per selection — see below), and `--pos-mode xrf` REFUSED where the geometry cannot reach the context, in the tool AND in the verifier | `ref/seq_chat.py:178`, `sw/chat_seq.py:251-252`, `sw/chat_seq.py:3131`, `sw/chat_seq.py:2971` |
| **+** | `split_witnesses` takes the conv witnesses OUT of the weight pack's probe — §14.1's 5.8 GiB-per-session re-upload, retired | `sw/chat_seq.py:1206` |

**T**, `078`: `residency 1122 witness blocks (1114 weight + 0 conv + 8 emb,
4488 KiB) in 35 ms -> 0 MISS` followed by `upload SKIPPED: every weight/emb
witness block is already resident`. §14.1 measured the same board at
`24 MISS` of 1,146 and a 45.8 s re-upload of 5,845 MiB; **that is now 35 ms
and nothing**, and the conv blocks are audited where they are written
instead: `24 witness blocks … 0 MISS` immediately after the state upload.

#### 8.3a Fix round 3: what E and the refusal got wrong, and the two fixes

**I-1 — the refusal was keyed on the MODEL TAG, and the verifier's copy had
no geometry at all.** `POS_MODE_LDC_ONLY = ("9b",)` was the *test* in both
`resolve_pos_mode` and `SeqModelVerifier.check_pos_mode`. The hazard is
geometric and nothing else: XRF[4] is a signed 18-bit register, so it reaches
`XRF_POS_MAX = ((1 << 17) - 1) // POS_STRIDE` and `rtl/seq_unit.sv` truncates
a larger write silently, which `ref/seq_model.SeqExec` does not model either.
In `resolve_pos_mode` the tag branch was conservative — the generic tail
already refused an out-of-reach `xrf` at any other selection — but **the
verifier was a real hole**: `check_pos_mode` never looked at `XRF_POS_MAX` or
`--max-ctx`, so for any selection not literally `"9b"` it would certify a
`--verify` run in `xrf` mode whatever the stride. Both now refuse exactly
when `XRF_POS_MAX < --max-ctx - 1`, `auto` is geometric on the same
condition, and `POS_MODE_LDC_ONLY` survives as the policy sentence quoted in
the two messages — consulted by neither decision.

**I-2 — E raised `T_MAX` for every model, and the frozen `--nch 1` path grew
8× with no way to validate it.** `T_MAX` is shared, so a frozen 0.8B/2B
session's position pool went **786,432 → 6,291,456 B** and its const blob
**1,784,576 → 7,289,600 B**. Nothing on this board can check that: the 2B
pack is gone and the 2B stream halts `err_op` on build_041 (§16.7). The
ceiling belongs to the TARGET BITSTREAM, not to the host — build_041 spills
KV to DDR at `T <= 4096` (`sw/hwmap.STATE_T_MAX`, unchanged), while the
frozen build_034/035 still address KV with `rtl/layer_chan.sv kv_waddr =
tcnt[8:0]` — so `ref/seq_chat.T_MAX` is now **4,096 at 9B and 512
everywhere else**, and `sw/chat_seq.py`'s no-`ref/` fallback is keyed the
same way. `ref/seq_chat.py` is line-neutral: `T_MAX` is still `:178`.

**What "the placement moved" does and does not mean.** The round-3 review
expected the `data_base`-relative image placement and the 324 relocated
LDC/EMB addresses to move with the pool. **T**, `108`/`109`, the same probe
in three trees (`107` carries a byte-identical footprint half, but its
step [3] splice read this tree's already-fixed `ref/seq_chat.py`, so the
load-bearing RED is `108` — §1, round-4 review m6): the pool lives in the
const blob and the images live in the
stream window, so **the three compiled images are byte-identical at every
tree** — `preamble@0x9000000` / `lite@0x9005f80` / `full@0x903cb40`, 1,526 /
14,010 / 14,744 records, sha `babfe7db…` / `753f32bc…` / `a1a4a922…`, and
`data_delta` `-0x74000000` either way. What moved was the **const blob**:
`plan.blob_bytes` `0x1b3b00` → `0x6f3b00`, sha `c59d9fe3…` → `0dbd6a6a…`.
At `e8e35a0` it is `c59d9fe3…` again, i.e. `4662b06`'s, byte for byte.

**RED then GREEN.** **T**, `108`, the new cases against `47e07cd`'s
implementation **inside its own worktree**: `372 passed, 8 failed`, and each
FAIL names its own reason — the ceiling (`chat_seq 4096 / seq_chat 4096 /
want 512`), the pool (`6291456 B at t_max 4096`), the blob (`7289600 B`), the
two geometry arms the tuple cannot satisfy, and the two verifier arms.
**T**, `109`: `chat_seq selftest: 408 passed, 0 failed`, `seq_chat: PASS`,
and the two untouched controls `seq_run 2785 passed, 0 failed` /
`HWMAP SHAPE_WORD SELFTEST PASS`.

**THE EIGHTH FAIL LINE, NAMED (round-4 review m1).** Seven reasons are
listed above and `108` prints EIGHT. The one not named is
`FAIL RED->GREEN: ...and the three resident images sit at the offsets that blob end implies`,
and **that case does not exist at HEAD**: it encoded the round-3 review's
premise that the image placement moves with the position pool, which
`108`/`109` then measured to be FALSE — the three compiled images are
byte-identical at all three trees, same record counts and same shas. So the
case was **replaced, not repaired**, by the assertion at
`sw/chat_seq.py:5818`,
`check("...and the three compiled images are untouched by T_MAX: "`. The
RED->GREEN ledger is 8 lines against 7 named reasons because the eighth was
retired on evidence.

**Two properties of the fixed tools, RECORDED rather than defended
(round-4 review m5 and m9), and NO tool edit was made for either.**

1. At `FABLE5_MODEL=9b`, `auto` now returns `xrf` for a `--max-ctx` of 64
   or less, where the old tag branch returned `ldc` unconditionally:
   `sw/chat_seq.py:3606`, `return "xrf" if reach <= cap else "ldc"`.
   `xrf` has never run on build_041. The case is unreachable in any usable
   context — the templated wrapper alone is 12 ids, so a 64-position
   ceiling cannot hold one turn — and `docs/USAGE.md` states the new rule,
   so this is a **follow-on**, carried and not fixed here.
2. `sw/chat_seq.py:256`, `VERIFY_HOST_S_PER_STEP = 140 if MODEL_TAG == "9b" else 6`,
   is the **third** per-tag ladder in that file keyed on the literal string
   for the 9B selection; `_T_MAX_FB` (`sw/chat_seq.py:250`) and
   `TEMPLATE4_BY_MODEL` (`sw/chat_seq.py:567`) are the other two. Its 140
   is a rounded stand-in for `074`'s measured 131.2 / 149.3, printed and
   not enforced, and the comment above it says so. A FOURTH should become a
   table rather than a fourth conditional — also a follow-on.

The `T_MAX` table `109` prints:

| `FABLE5_MODEL` | `seq_chat.T_MAX` | `POS_STRIDE` | position pool | `XRF_POS_MAX` |
|---|---|---|---|---|
| `0.8b` | 512 | 1,536 B | 786,432 B | 85 |
| `2b` | 512 | 1,536 B | 786,432 B | 85 |
| `9b` | **4,096** | 2,048 B | 8,388,608 B | **63** |

**Both fixes are host-side and neither touches the 9B path's bytes**: at
`FABLE5_MODEL=9b` the ceiling is the same 4,096, the compiled images are the
same, and `110` re-ran the board rung on the edited tools to say so.

### 8.4 Greedy chat — the transcript, whole

**T**, `078`, `rc 0`. `FABLE5_MODEL=9b`, `--nch 4 --ntok 24`, greedy
(`--temp 0`, the LM head and the argmax on the FPGA):

```
prompt> What is the capital of France?
  --> "The capital of France is **Paris**.\n\nIt is the country's most populous city and a major global center for finance"
  ids [760, 6511, 314, 9338, 369, 2972, 57590, 159034, 271, 2064, 369, 279, 3046, 579, 1379, 91188, 3177, 321, 264, 3478, 3521, 3990, 364, 16519]   24 tok in 5.68s
  prefill 18 lite x 126.5 ms | decode 24 full x 137.7 ms | 4.22 tok/s wall | 98% of wall was device | context 42/500 (8%)
  launches     43 (1 preamble / 18 lite / 24 full)
  OUT FIFO     clean (depth 64, sticky of_ovf clear)
  MMIO         4564 reads / 606 writes
```

**The two conventions, and which is which.** **4.22 tok/s** is the whole
turn including the 18 prefill launches; the steady-state decode rate is
**1 / 0.1377 s = 7.26 tok/s** (D), which is §10.1's `7.2928` gate figure to
0.4 % on a different program. `--ntok 24` is the guidance
`evidence/qwen9b/g2/G2C_CHAIN.md` §8.4 ruled does NOT move at 9B, and this
reply used all 24 without reaching EOS — which is what that guidance is for.

**Prefill is decode-rate.** 126.5 ms against 137.7 ms is **91.9 %** of a
decode step (D): the `lite` body is the same forward pass without the LM
head. There is no batched prefill in this design and §16.5 stands.

### 8.5 Sampled chat, four seeds

**T**, `079`, four separate sessions, `--temp 0.8 --top-k 32 --top-p 0.95`,
the top-32 capture read from the chip and one seeded host draw over it:

| seed | tokens | reply |
|---|---|---|
| `20260909` | 24 | `"The Republic," and as its political and religious capital in all Europe of nations that can take them! So why was a` |
| `20260909` (repeat) | 24 | **byte-identical ids** to the row above |
| `4242` | 24 | `> 🚀\n**\n\nI'd use emojis where natural—**`28. $, **$`.` |
| `777` | 9 | `🐲:\n\nParis has` — stopped on **EOS** |

**Seed-deterministic and seed-sensitive, both demonstrated**: the two
`20260909` runs print the same 24 ids
(`[9726, 5260, 1288, 321, 430, 1141, 4788, 321, 10072, 6511, 303, 660, 4357, 314, 16185, 421, 628, 1831, 1070, 0, 1987, 3069, 557, 264]`),
and `4242` / `777` differ from them and from each other. `OUT FIFO clean` on
all four.

**Said plainly: the sampled replies at `--temp 0.8` are not good.** The
greedy reply is coherent and correct; these wander. That is the expected
shape of a temperature draw over an int16 Q7.8 residual whose rail §11
observed saturated, and this gate reports it rather than picking a
flattering temperature — what the rung establishes is that the **path** is
correct (on-chip top-32, seeded host draw, determinism), not that 0.8 is a
good operating point.

### 8.6 The chat template, against the 9B checkpoint's own jinja

§20.3's one outstanding rung. `HF_REF_SINGLE` and its two siblings were
derived on the **2B** checkpoint on 2026-08-11; nothing had run the 9B
checkpoint's own `chat_template.jinja` until now.

**T**, `075`, board-free on snoke, `transformers 5.11.0`, snapshot
`c202236235762e1c871ad0ccb60c8ee5ba337b9a`, `chat_template.jinja` 7,756 B
sha256 `a4aee8afcf2e0711942cf848899be660…`:

| rendering | `single` | `system` | `3msg` |
|---|---|---|---|
| `enable_thinking` **unset** (the checkpoint's own default) | 17 ids — **DIFFERS** | 28 — **DIFFERS** | 33 — **DIFFERS** |
| `enable_thinking=False` | 19 — **== the pinned reference** | 30 — **==** | 35 — **==** |

**The `enable_thinking` inversion is real and this run caught it in the
act.** Left unset, the 9B jinja ends the turn `… 248068, 198` — an OPEN
`<think>` block — exactly as `docs/QWEN35_NEXT_FEASIBILITY.md:255` predicted
for 4B/9B; the pinned reference ends `… 248068, 271, 248069, 271`, the
CLOSED-EMPTY block. **It does not reach `chat_seq`**, which builds the
wrapper by ID SPLICE and emits the closed-empty block explicitly, never
passing `enable_thinking`: **T**, `075`,
`ChatTemplate.turn_ids  19 ids  == HF_REF_SINGLE`. So the three pinned
constants are re-verified on the 9B checkpoint, and the reason they hold is
now measured rather than argued.


### 8.6a `chat_seq --verify` — the chat prompt, in lockstep with the reference

**The cross-driver gate, on the chat path.** `--verify` replays every launch
through `ref/seq_model.SeqExec` against the SAME compiled image and the SAME
per-launch patch bytes, and compares the chip's token with the model's before
anything downstream can see it.

**T**, `080`, `rc 0`, 44 minutes 48 seconds of wall clock for 22 forward
steps:

```
  verify     building the ref/seq_model lockstep (~6 s of host time per step; the board idles meanwhile)
    [verify] step  0 lite: None == seq_model (119s host)
    …
    [verify] step 17 lite: None == seq_model (119s host)
    [verify] step 18 full: 760  == seq_model (134s host)
    [verify] step 19 full: 6511 == seq_model (131s host)
    [verify] step 20 full: 314  == seq_model (131s host)
    [verify] step 21 full: 9338 == seq_model (131s host)
  --> 'The capital of France'
  ids [760, 6511, 314, 9338]   4 tok in 2680.42s
  launches     23 (1 preamble / 18 lite / 4 full)
  OUT FIFO     clean (depth 64, sticky of_ovf clear)
```

**22 of 22 steps agree, zero divergences**, on the templated prompt §8.4
answered — and `[760, 6511, 314, 9338]` is `078`'s first four tokens,
unchanged. **This is the rung that makes §8.4's transcript a lockstep
result and not just a plausible one**, and it is the rung function B exists
for: every one of those 22 replays moved SLD/SST blocks through the
`StateRegion` the verifier now builds. Before this round it stopped at the
first one (`056` [6]).

**The `~6 s of host time per step` in the tool's own banner was the 2B
figure and was wrong at 9B by 20×** — the run took 119-134 s per step. Fix
round 2 declined to edit it because it is `sw/chat_seq.py`'s text for every
model; **fix round 3 made it per model instead** (round-3 review m4), and
`110` prints `~140 s of host time per step at FABLE5_MODEL=9b`.

#### 8.6a′ The re-run after fix round 3's tool edits

**Why it exists.** Fix round 3 edited `sw/chat_seq.py` and `ref/seq_chat.py`
(§8.3a). Neither change touches a byte the 9B path computes with — the
ceiling at 9B is the same 4,096, the compiled images are the same, and the
refusal's condition is a different expression of the same answer at this
geometry — but "should not" is not a rung. So the board rung was run again
on the edited tools, on the SAME resident bitstream and the SAME resident
pack, under the lock, with no reprogram.

**T**, `110`, tree `e8e35a0` clean, `rc 0`, 46 m 03 s:

```
  residency  1122 witness blocks (1114 weight + 0 conv + 8 emb, 4488 KiB) in 35 ms -> 0 MISS
  upload     SKIPPED: every weight/emb witness block is already resident
  state CSR  SB_DN=0x38000 SB_KV=0x38180 SB_CV=0x38980  [readback OK]
  residency  24 witness blocks (0 weight + 24 conv + 0 emb, 96 KiB) in 1 ms -> 0 MISS
  verify     building the ref/seq_model lockstep (~140 s of host time per step at FABLE5_MODEL=9b; the board idles meanwhile)
    [verify] step 18 full: 760  == seq_model (138s host)
    [verify] step 19 full: 6511 == seq_model (134s host)
    [verify] step 20 full: 314  == seq_model (135s host)
    [verify] step 21 full: 9338 == seq_model (135s host)
  --> 'The capital of France'
  ids [760, 6511, 314, 9338]   4 tok in 2755.14s
  launches     23 (1 preamble / 18 lite / 4 full)
  OUT FIFO     clean (depth 64, sticky of_ovf clear)
```

**22 of 22 steps `== seq_model`, zero divergences, and the same four ids as
`080` and `078`.** Device time is unchanged to the tenth of a millisecond —
`lite` 126.5 ms (min 126.4, max 126.7, n=18) and `full` 137.5 ms (n=4),
`080`'s numbers exactly — which is what "the tools moved, the bytes did not"
looks like on a counter. **Residency held**: `0 MISS` → `upload SKIPPED`
both times, so **not one of the 5,845 MiB was re-uploaded** by this round
either. The board lock was held for the process's lifetime and released;
the bitstream, the pack and EMBLOG2 are as `086` left them.

### 8.7 THE LONG-CONTEXT RUNG — T = 526, past the ceiling that was 512

**The rung, in one line: a 526-step context ran on silicon, and the KV
region proves it.**

**The context.** One templated turn — a 12-id wrapper around an instruction
plus sixteen copies of one sentence — renders to **503 ids**, so
`--ntok 24` is **502 prefill launches + 24 decode = 526 forward steps**, the
smallest round total that clears 512 with margin. `--max-ctx 700`; before
this round `main()` refused any `--max-ctx >= 512` outright (`076`:
`chat_seq 512 / hwmap 4096 / seq_chat 512`), so **the ceiling this rung
passes is demonstrably the old one**.

**T**, `083`, `rc 0`. `FABLE5_MODEL=9b` is exported by the rung script, not
by the wrapper, so `083`'s `=== env:` header reads `unset` — the session
line two screens below it names `model_9b_s1.e4`, 158,536 records, which
only the 9B selection can reach:

```
  --> 'The passage repeatedly states that the city of Paris grew from a settlement on an island in the Seine, and its streets,'
  ids [760, 20438, 18253, 5134, 421, 279, 3177, 314, 11751, 13538, 494, 264, 16576, 383, 449, 12552, 303, 279, 181474, 11, 321, 1141, 13959, 11]   24 tok in 70.54s
  prefill 502 lite x 131.6 ms | decode 24 full x 147.9 ms | 0.34 tok/s wall | 99% of wall was device | context 526/700 (75%)
  launches     527 (1 preamble / 502 lite / 24 full)
  OUT FIFO     clean (depth 64, sticky of_ovf clear)
```

**It answered the question.** The reply is a summary of the passage it was
given, at a context 12× the one §8.4 used.

**THE KV REGION, READ BACK — the proof that is not a host counter.**
`sess.T` is the driver's own arithmetic. B15.1's KV block is TCNT rows of
256 B from the block base, so the deepest non-zero row IS the deepest
position the layer stored. The region was zeroed first
(`g6_state.py --write-initial`, which writes `state.bin` verbatim, KV
included — `upload_state` and the context reset both leave KV alone by
design), and probed before and after. **T**, `083` steps [1], [2], [5]:

| | L0 K | L0 V | L4 K | L4 V | L7 K | L7 V |
|---|---|---|---|---|---|---|
| **before** — rows non-zero | 0 | 0 | 0 | 0 | 0 | 0 |
| **after** — rows non-zero | 526 | 526 | 526 | 526 | 526 | 526 |
| **after** — deepest row | **525** | **525** | **525** | **525** | **525** | **525** |
| **after** — exponent side array, deepest | 525 | 525 | 525 | 525 | 525 | 525 |

**`DEEPEST KV ROW WRITTEN: 525`**, from `0` in the same six blocks minutes
earlier, on three attention layers, for K and V, rows AND the exponent side
array. The old design's on-chip bound was `T <= 512`.

**Determinism: three runs, one token list.** `083` ran the session twice and
`084` a third time; all three print
`[760, 20438, 18253, 5134, 421, 279, 3177, 314, 11751, 13538, 494, 264, 16576, 383, 449, 12552, 303, 279, 181474, 11, 321, 1141, 13959, 11]`.
**T**, `084` [4], `LONGCTX DETERMINISM: IDENTICAL`. (`083`'s own step [7]
printed `DIFFERS` on the same three-way-identical data: its comparison
included the `24 tok in 70.5Ns` wall-clock suffix. The harness was wrong,
the tokens were not, and `084` compares the LISTS. Both logs are committed.)

**Rate, in both conventions.** Decode is **147.9 ms/step** at T ≈ 520
(**6.76 tok/s** steady state, D) against §8.4's 137.7 ms at T ≈ 30
(7.26 tok/s) — **+7.4 %** (D) for 12× the context, which is the KV term
growing. Prefill is **131.6 ms** (mean of 502, min 126.4, max 136.9). The
**0.34 tok/s** the tool prints is the whole turn including 502 prefill
launches and is a *prefill* number, not a decode one; §16.5's caveat
applies to it.

**The DDR state traffic at this T.** `sw/tok_meter.state_bytes_per_token(526)`
= `{'dn': 50331648, 'cv': 6291456, 'kv': 17309696, 'total': 73932800}` =
**70.51 MiB/token**, LABEL **D** (**T**, `084` [3]) — §10.3's model
evaluated at the T this rung reached, on **DDR channel 3 alone**. The KV
term is 17,309,696 B against 16,842,752 B at T = 512 and 134,742,016 B at
T = 4,096.

**THE TWO COUNTER READS THAT DIED — and why the lane number comes from
`084` and not from `083`.** `083`'s own steps [3] (`--clear`) and [6]
(`--read`) both died: `FileNotFoundError: /dev/xdma0_user_user`, `rc 1`
(`083`:40-51 and `083`:127-138 — the wrapper's `rc 0` is the SCRIPT's, m2).
So **runs A and B carry no lane measurement at all, and the counters were
never cleared before run A.** `084` is the run that has them: its step [1]
is the `--clear` that makes step [3] a per-session read of a THIRD 526-step
session, which is the only reason the numbers below are attributable to one
session rather than to everything the board had done since `002`.

**The DMA lane, measured over the run.** **T**, `084` [3]: `L_SDMA_CYC
762542182 cycles = 3050.169 ms` over 527 launches = **5.788 ms/step**,
against **5.044 ms/step** on the 43-launch session at T ≈ 30 (**T**, `086`)
and §10.2's 5.125 ms/token — **+14.8 %** (D), which is the KV blocks
getting longer. **`L_LCYC` from the same read is NOT usable and §14.5 says
why.**

**THE PER-STEP TOKEN LOCKSTEP — NOT RUN WHEN THIS SECTION WAS WRITTEN,
ESTABLISHED NOW (§22.12b).** §20.3 budgeted the reference at "≈ 45-60
minutes per 512 lockstep-verified steps", from a 2B figure. **T**, `074`,
measured on the 9B artifact: **131.2 s** per `lite` step and **149.3 s** per
`full` one, so 526 steps is **19.3 h** of single-threaded host time (D) —
and `080` spent 44.7 minutes on 22. **That run was not made in fix round
2**, and this section as first written did not imply it was; it has since
been made twice. What was established about the long context WITHOUT it, and
stands unchanged:

* the **position pool for all 4,096 positions** is byte-identical between
  two independent implementations, checked at every session start —
  `crosscheck agent A vs my own spec slices: 6/6 byte-identical (step
  images, const region, position pool)`, printed in `083` and `084`;
* the **same three images and the same patch mechanism** are lockstep-clean
  against the reference at 22 consecutive steps (`080`, §8.6a);
* the **silicon wrote KV row 525** from a zeroed region (above);
* the **tokens reproduce exactly across three independent sessions**;
* every launch halted clean — `OUT FIFO clean`, no `E_*`, `rc 0`.

**What it would take was one number, and the number has been paid — twice.**
~19 h of host time on a board-free replay of `083`'s own step sequence,
needing no board and no lock and detachable. `106` (fix round 3, 17.08 h)
reported a divergence at the second decode step; that was traced to the
REFERENCE, which ran at the 0.8B `RS_F` default rather than the 9B law, and
not to the chip (§22.11). `171` is the same replay at the derived operating
point, 17.82 h: `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:637` is
`LONGCTX_LOCKSTEP: PASS 526/526` — all 24 decode steps, positions 502..525,
every verdict `==`, the chip's token rank 1 in the reference's own logits at
every one.

**So the rung's MECHANISM is proven on silicon** (KV row 525 from a zeroed
region, three token-identical sessions, the 4,096-position pool
byte-identical between two implementations) **and its CORRECTNESS against
the reference is ESTABLISHED** — by `149` at N = 503 and by `171` at
T = 526. **The CEILING is a separate question and it has not moved**:
`rtl/attn_core.sv:114`'s `logic signed [39:0] denom` still bounds this
design at **T < 512 BY ANALYSIS**, a worst-case bound that one session's
agreement does not lift (§22.7, §22.12b).

**The tools moved after `106` was launched, and the replay used the images
compiled at launch (round-4 review m4).** `106` imported `47e07cd`-era
`sw/chat_seq.py` and `ref/seq_chat.py`; fix round 3 edited both afterwards.
At 9B nothing it computes with moved — `T_MAX` is 4,096 either way,
`resolve_pos_mode` returns `ldc` either way at `--max-ctx 700`, and the
three compiled images are byte-identical at every tree in the footprint
probe (§8.3a) — and the edits since are covered by `109`'s selftests and by
`110` on the board, which reproduces `080` to the tenth of a millisecond.
`171` does not carry the question at all: it ran on tree `e1d0d3a`, which is
AFTER fix round 3.

#### 8.7a The replay — LAUNCHED, and IN FLIGHT as this document is written

> **SUPERSEDED 2026-09-14 — read §22.11 and §22.12b first.** What follows is
> fix round 3's record of the FIRST replay's LAUNCH, and it is kept verbatim
> as that record. Its verdict-in-waiting is void: `106` spent its 17.08 h
> against a reference whose `RS_F` was still the 0.8B default rather than
> the 9B law, so the divergence it reported was the REFERENCE's and not the
> chip's (§22.11). The correctness question this subsection leaves open is
> ANSWERED in §22.12b, by `171` — `LONGCTX_LOCKSTEP: PASS 526/526`, 24
> decode steps, at `derived=7`. Nothing below is withdrawn as a record of
> what was launched; every sentence below that reads as an open question
> about the chip is.

**The ruling (round-3 review §3.1, adopted by the controller): run the
board-free replay; the boundary-crossing shortcut is REJECTED.** Seeding the
reference from the chip's state at step 512 would make steps 0-511
self-referential — any divergence accumulated there would be copied into the
reference and become invisible — and what would survive is a test of the
crossing mechanism, which the 4,096-position pool's byte-identity and
`DEEPEST KV ROW WRITTEN: 525` already evidence twice over. It is also not
cheap: `SeqModelVerifier` carries a persistent `mach` across launches, so a
seeded reference would need the chip's scratchpad and XRF as well as its
155 MiB region, and no code loads a `StateRegion` from a board readback.

**`g6_longctx_lockstep.py`** is that replay. It rebuilds the session `083`
step [4] ran — the prompt, `--max-ctx` and `--ntok` are read out of
`083_longctx_chat.json`'s own committed `argv`, the chip's 24 ids out of
`083_longctx_9b.log`'s own `ids [...]` line, so nothing is retyped — and
drives `ref/seq_model.SeqExec` through the same compiled `preamble`/`lite`/
`full` images with the artifact's initial DDR state region, carrying `mach`
and `region` step to step exactly as `--verify` does. **NO BOARD, NO LOCK,
NO DMA.**

**What a per-step verdict means here.** `083` prefilled with the **lite**
body, which has no LM head, so the chip emitted NO token on steps 0-501 and
`ChatSession.step` asserts that. A prefill step's verdict is therefore "both
sides emit no token", which is weak on its own — **the load-bearing
comparison is the 24 decode ids**, and those depend on the whole 502-step
prefill trajectory: one wrong prefill step moves the KV region and the decode
tokens with it. The final line is
`LONGCTX_LOCKSTEP: PASS <n>/526` or `FAIL at step <k>`, and both counts are
printed.

**The launch, on the record.** **T**, `105`, the smoke: `--selfcheck` renders
both per-step arms and all three verdict strings with dummy values (so an
18-hour run cannot discover a formatting bug in its decode arm at step 502),
then one real step — `step 0 lite tok=248045 … ref -> no token  chip -> no
token  ==  [118.4s]`, `LONGCTX_LOCKSTEP: PARTIAL 1/526`. Then:

| | |
|---|---|
| launched | **2026-09-10 00:44:07 −06:00**, snoke, detached (`nohup setsid`, own session, `ppid 1`), `nice -n 10` |
| pid | **878615** (the python; `878584` is the `evidence/qwen9b/run.sh` wrapper) |
| log | `evidence/qwen9b/g6/106_longctx_lockstep_ref.log`, through the wrapper, tree `2762662` clean |
| cost | **≈ 19.3 h** from `074`'s 131.2 s (`lite`) / 149.3 s (`full`); the smoke and the first steps measure **118-121 s/step** under `nice -n 10`, i.e. **≈ 17.2 h** projected |
| parallelism | **none possible** — each step depends on the previous `mach` and `region` |
| committed? | **no, and deliberately not** — this round commits no log without an `=== rc:` line. Collecting `106` means reading its verdict, committing the log, and writing the result into §8.2, §8.7 and §16 item 2. **The rule had to fire once (round-4 review m7):** `bf00696`, fix round 3's drift commit, swept the STILL-RUNNING log in, and `4e6e09e` took it straight back out — its subject says why, that `106` is still running and has no end stamp. `106` was committed in Task 15-D, after its own `=== rc:` existed |

**STATUS AS THIS SUBSECTION WAS WRITTEN: the long-context rung's MECHANISM
is proven on silicon (KV row 525 from a zeroed region, three token-identical
sessions, the position pool byte-identical between two implementations); its
CORRECTNESS against the reference is IN FLIGHT and is not claimed anywhere
in this document.**

**STATUS NOW (2026-09-14): CLOSED, and the rung PASSES.** `106` landed FAIL
and the FAIL was the reference's operating point, not the chip (§22.11);
`149` and then `171` landed PASS at the derived operating point, `171` with
all 24 decode steps of the `083` session compared (§22.12b). The sentence
above that says the correctness "is not claimed anywhere in this document"
no longer holds, and it is superseded rather than deleted so the record of
what was and was not claimed at each round survives.

---

## 9. EMBLOG2

**Written and read back on every live run, and a mismatch is refused.**
`sw/seq_run.seq_set_emb_row_bytes` writes `seq_emb_log2(row_bytes)` to
`S_EMBLOG2`, reads it back, and raises on disagreement. **T**, `008`, `009`
(×4), `010`, `011` (×3), `017`, `018`, `020`, `023`, `025`, `028`:

```
  EMBLOG2    13 (8192 B embedding rows)
```

**13 is the value the plan names**, and it is the manifest's, not a
constant: `emb_row_bytes = 8192` = 2 × H = 2 × 4096 (**D**), read from
`tb/scripts/w9/model_9b_s1.weights.json` by `HW.load_weights_manifest`.
`2^13 = 8192`.

### 9.1 The readback of 13 alone does NOT prove the write took

An earlier revision of this section said "the reset value is
`1 << SEQ_EMBLOG2_RST`, so this is a real write, not the default surviving".
**The RTL refutes it.** `sw/hwmap.py:342` reads `SEQ_EMBLOG2_RST = 13`, and
`rtl/seq_unit.sv:346` reads
`localparam logic [4:0] EMBLOG2_RST = 5'd13;`, assigned at
`rtl/seq_unit.sv:962` (`emb_row_log2 <= EMBLOG2_RST;`). **At 9B the CSR's
reset value in log2 units IS 13 — the same number the manifest asks for** —
so reading 13 back cannot tell a write that landed from a reset default that
survived. (The sentence conflated `EMB_ROW_BYTES_DEFAULT = 1 << 13 = 8192`
*bytes* with the CSR's log2 field. At 2B the R-d record's `EMBLOG2 12` was
distinguishable, which is where the reasoning came from.)

**The rung as the plan asks it is satisfied either way** — Step 4 asks for a
write, a readback and a refusal on mismatch, and
`sw/seq_run.seq_set_emb_row_bytes` does all three against the manifest — but
the *claim* was above its evidence.

### 9.2 The discriminating proof, on the resident silicon

Fix round 1 made the distinction with one CSR and no DMA. **T**, `055`,
`rc 0`, under the lock, `sw/seq_run.Dev`'s identity gate first
(`VERSION 0xc973c18a`, `CALIB 0xf`), sequencer `busy=False`:

```
[0] as found, before this rung writes anything: EMBLOG2 13  (8192 B rows)
[A] write 4096 B rows (EMBLOG2 12) through sw/seq_run.seq_set_emb_row_bytes, then read back
  EMBLOG2    12 (4096 B embedding rows)
  independent re-read: EMBLOG2 12
  ==> THE WRITE TOOK.  12 is not the reset value 13, so this readback cannot be the
      default surviving.
[B] write the manifest's 8192 B rows (EMBLOG2 13) back, then read back
  EMBLOG2    13 (8192 B embedding rows)
  independent re-read: EMBLOG2 13
```

**12 is not the reset value, so a readback of 12 is only possible if the
write landed.** Both writes go through `sw/seq_run.seq_set_emb_row_bytes` —
the function the rung rests on — not a hand-rolled poke, and each is checked
by a second, independent `seq_rd`. Step [B] restores the manifest's value, so
the CSR is exactly as `028` left it; the restore also runs on the error path.
Nothing was written to DDR, so the resident pack and the state region are
untouched — `055` is `G6_EMBLOG2: PASS (0 problem(s))`.

---

## 10. THE PERF CENSUS — both lanes, both conventions

**T**, `020`, `rc 0`, tokens `[2614, 314, 279, 369, 11751, 13]` IDENTICAL.

The instrument clears `L_LCYC` and `L_SDMA_CYC` **while the sequencer is
idle**, samples `S_PERF_CYC` beside `S_PC` **while it is busy** (both SEQ
CSRs — the arbitration rule allows exactly that and nothing else), and reads
the two lane counters **after HALT**. No host clock enters any figure below;
`S_PERF_CYC` is device cycles at `ACLK_HZ = 250 MHz`.

### 10.1 The headline, in both conventions

| convention | ms/token | tok/s | how |
|---|---|---|---|
| **gate** (`device/ntok`) | **137.1210** | **7.2928** | 822.726 ms / 6 tokens (**T**/**D**) |
| **steady-state** | **137.1413** | **7.2917** | one loop iteration measured ON CHIP: 34,285,336 cycles between consecutive backward jumps of `S_PC` (**T**) |

**The two conventions differ by 0.02 ms/token here, not the 2B's 8.671 ms,
and the reason is structural.** RD_GATE §1's steady-state convention
subtracts a session-once preamble, and that constant came from a `chat_seq`
session — the preamble image that runs once before any step. This stream has
no such thing: all six steps run the same body, and the residual
`822.726 − 137.1413 × 6 = −0.122 ms` (**D**) is the measurement's own noise,
not a preamble. **Quoting the 2B's 8.671 ms here would be importing a number
from a mechanism that is not present**, so it is not quoted.

### 10.2 The two lanes — first time on silicon

| lane | cycles | ms total | **ms/token** | comparand | verdict |
|---|---|---|---|---|---|
| `L_LCYC` (compute, `busy_cmp`) | 62,382,496 | 249.530 | **41.588** | S4 §5.3.1's **45.674**; Task 12's **46.079** | **8.9 % / 9.7 % FASTER than either** — but see §10.2a: neither comparand is like-for-like, and the delta is NOT attributed |
| `L_SDMA_CYC` (DMA, `busy_dma`) | 7,687,467 | 30.750 | **5.125** | the **MODELLED** 5.133 (S4, LAT 8) | the board number **REPLACES** it; they agree to **0.16 %** |
| sum | 70,069,963 | 280.280 | 46.713 | — | **34.1 %** of the 822.726 ms device time |

**Read the sum row carefully. 65.9 % of the device time is in neither lane.**
`L_LCYC` counts `layer_chan` busy and `L_SDMA_CYC` counts the state-DMA lane;
the rest is the sequencer's own fetch/decode and its 106,244 `CSRWR` records,
plus the matvec engines, which have their own counters. That is not a
surprise, but it is the first time it has been *measured*, and it says where
a future round's slack is: not in the layer.

**The two lanes overlap.** 41.588 + 5.125 = 46.713 ms/token of lane time
inside a 137.121 ms/token step, so neither lane is the critical path and the
DMA lane's cost is not additive. **The amendment's instruction — "never add
the modelled figure to anything" — is honoured: 5.133 appears here only as
the thing 5.125 replaces.**

### 10.2a The layer-term delta, LIKE-FOR-LIKE — and NOT attributed

The row above compares a raw counter against two figures that are not the
same quantity, and it was published without a mechanism. Both are repaired
here; the direction survives, the attribution does not.

**(a) The comparands are not like-for-like.** S4's **45.674** is the compute
lane with the dispatch holds SUBTRACTED — the row at
`evidence/qwen9b/s4/S4_REPLAY.md:846`, whose subtraction the sentence at
`evidence/qwen9b/s4/S4_REPLAY.md:852` spells out as
`LCYC − F1 − F2` — while the same lane with the fences CHARGED reads
**46.158** (`evidence/qwen9b/s4/S4_REPLAY.md:842`,
`LCYC` (compute lane, holds INCLUDED)). The board's `L_LCYC` is the RTL's own
accumulating `busy_cmp`, read once after HALT, with nothing subtracted — so
the holds-charged figure is the closer of the two.

**(b) And both of those are the PRE-Task-14-A RTL.** The right comparand is
Task 14-A's own chip-TB census of the same script,
`evidence/qwen9b/s4/census_t14a.txt` (**M**), beside the pre-pipelining
`evidence/qwen9b/s4/census_s4shipped.txt`:

| chip-TB census of `model_9b_s1` | LCYC, 6 tokens | cyc/token | ms/token |
|---|---|---|---|
| `evidence/qwen9b/s4/census_s4shipped.txt` (pre-14A, draining) | 68,510,840 | 11,418,473 | **45.674** |
| `evidence/qwen9b/s4/census_t14a.txt` (Task 14-A, draining) | 68,516,360 | 11,419,393 | **45.678** |
| S4 §5.5.4, holds charged (pre-14A) | — | 11,539,426 | **46.158** |
| the same, +14A's pipelining (**D**) | — | 11,540,346 | **46.161** |
| **the board, `020`** | **62,382,496** | **10,397,083** | **41.588** |

**Task 14-A's cost is accounted for EXACTLY, and it points the other way.**
The two censuses differ by 5,520 cycles over 6 tokens = **920 cycles/token**,
and 920 is precisely the number of pipelined commands in one token: 144/6 =
**24 CONV** + 4,608/6 = **768 DNST** + 768/6 = **128 ATTN**, at
`evidence/qwen9b/g5/G5C_RTL.md`'s **+1 cycle per command** (**D**, both
censuses' own per-opcode counts). So the shipped netlist should be **920
cycles/token SLOWER** than S4's, not 1.14 M cycles/token faster.

**Like-for-like, the board's compute lane is 9.9 % below the chip TB's**
((41.588 − 46.161)/46.161 = **−9.91 %**, **D**) — the same direction the row
above reports, on the right pair of numbers.

**What explains it is NOT ESTABLISHED by this gate.** Two candidates, and
what the evidence does to each:

* **Different instruments, not different silicon.** The Task 14-A census's own
  banner reads `dispatch= DRAINING (poll cmd_cnt AND busy_any low)`: it sums
  per-command `busy_cmp` windows with the dispatcher serialised between
  commands. The board's `L_LCYC` is one hardware counter accumulating under
  the REAL sequencer's dispatch, which never drains.
  `evidence/qwen9b/s4/S4_REPLAY.md` §5.5.5 already calls the draining census
  "the pessimistic end" of a range whose other end — §4.2's non-draining
  whole-model replay — came out **1.70 %** faster. **A gap in this direction
  is expected; 9.9 % of gap is not accounted for by anything measured
  here**, and no board rung can measure it.
* **The TB's memory model** (`WLAT 40` / `DDRLAT 32`, named in §10.4's table)
  being pessimistic against real DDR. **The one sweep on record WEAKENS
  this**: S4 §5.5.4 ran the whole model at `LAT = 8` and at `LAT = 40` and
  `LCYC` is **IDENTICAL** (11,539,426) at both; only `SDMA_CYC` (+4,949
  cyc/token, 0.39 %) and `BUSY_ANY` (+1,024) moved. `LAT` is the SDMA
  latency knob and not `WLAT`/`DDRLAT`, so the sweep does not settle the
  question either — it just removes the easiest version of this answer.

**So: the delta is real, it is measured on both sides, and this gate does not
know why.** It is labelled a HYPOTHESIS-FREE observation rather than dressed
in one, and §16 carries it.

**And it does not stand alone.** Beside it, §10.4 records the board **4.6 %
SLOWER than the same chip TB end-to-end** (137.121 vs 131.14 ms/token), and
the sum row above shows **65.9 % of device time is in neither lane**. A
compute lane that reads 9.9 % below the TB inside a step that runs 4.6 %
above it is not a story about a fast layer — it is a pointer at the 65.9 %,
which is where a future round's slack is and where neither instrument has
looked.

### 10.3 Load balance, and the DDR traffic

**Per-channel weight load, from `plan_weight_split` (D, static). T**, `029`:

| chan | bytes | MiB | rows | share |
|---|---|---|---|---|
| 0 | 1,025,925,120 | 978.40 | 420,224 | 25.073 % |
| 1 | 1,022,681,088 | 975.30 | 418,688 | 24.993 % |
| 2 | 1,021,599,744 | 974.27 | 418,176 | 24.967 % |
| 3 | 1,021,599,744 | 974.27 | 418,176 | 24.967 % |
| **total** | **4,091,805,696** | **3,902.25** | | **1,114 pieces** |

**max/min = 1.004234** — the row split is balanced to **0.42 %** across the
four engines.

**The measured per-channel matvec counters are NOT that spread, and must not
be read as it. T**, `020`: matvec0/1/2/3 read 72,656 / 18,098 / 72,795 /
72,653 cycles and 67,584 / 16,896 / 67,584 / 67,584 beats. **D**: 67,584
beats × 64 B = 4.125 MiB, which is three orders of magnitude below the
~3.9 GiB/token the weights imply. `R_PERF_CYC`/`R_PERF_BEATS` are **per
engine RUN**, not accumulators over a token — `sw/tok_meter.py` sums them by
reading once per `V` record, and that is the host-orchestrated path, which
cannot drive a sequencer stream. **So these four numbers describe the LAST
MVGO before HALT and nothing more**, and the per-token per-channel spread is
not measurable on the sequencer path with the counters this netlist has. The
static split above is what this gate can say about balance.

**DDR traffic per token — `sw/tok_meter.state_bytes_per_token`, LABEL D. T**,
`030`:

| T | DN | CV | KV | **total** |
|---|---|---|---|---|
| 512 | 50,331,648 | 6,291,456 | 16,842,752 | **73,465,856 B = 70.06 MiB** |
| 1,024 | 50,331,648 | 6,291,456 | 33,685,504 | 90,308,608 B = 86.12 MiB |
| 2,048 | 50,331,648 | 6,291,456 | 67,371,008 | 123,994,112 B = 118.25 MiB |
| 4,096 | 50,331,648 | 6,291,456 | 134,742,016 | **191,365,120 B = 182.50 MiB** |

**70.06 MiB at T = 512 and 182.50 MiB at T = 4,096** — the amendment's own
two figures, reproduced by the tool at HEAD. The region occupies **DDR
channel 3 alone** (§6), so all of this traffic lands on one of the four
channels while the weights stream from all four.

### 10.4 Against the model, and the attribution the plan demands

| comparand | value | measured | |
|---|---|---|---|
| §10's re-anchored band | ≈ **6.5 – 7.0** tok/s, headline ≈ 6.56 (A1.6) | **7.2928** | **ABOVE the band by 4.2 %** over its top |
| S4's chip-TB whole-model | **131.14 ms/token** (6 tokens, TB memory models WLAT 40 / DDRLAT 32 — **not a board figure**) | **137.121 ms/token** | board is **4.6 % SLOWER** |
| S4's compute lane | 45.674 ms/token | **41.588** | **8.9 % faster** — holds subtracted, pre-14A (§10.2a) |
| Task 12's cycle census | 46.079 ms/token | **41.588** | **9.7 % faster** |
| **the like-for-like lane** | **46.161** ms/token (Task 14-A's netlist, holds charged, **D**) | **41.588** | **9.9 % faster — and UNATTRIBUTED (§10.2a)** |
| the DMA lane, MODELLED | 5.133 ms/token | **5.125** | replaced; 0.16 % |

**The measured number lands outside the band, so it is attributed, as the
plan requires.** The band was "derived for the URAM-resident design with
`DN_PIPE = 2`", which is not the design that shipped: the state spilled to
DDR, and §10.2 shows why that did not cost what the model assumed — the DMA
lane is 5.125 ms/token and it **overlaps** the compute lane rather than
adding to it. The plan itself says the model "fails its only out-of-sample
test (+1.7 % at nch=1), its r-bracket validation is retracted, and its layer
coefficient is a fit intercept, not a measured cost", and instructs that
Task 12's cycle census is the better comparand. **Against that comparand the
silicon is 9.7 % better than predicted on the layer term** — and §10.2a
withdraws the earlier claim that this is "the single cleanest statement this
census supports". It is a clean MEASUREMENT on both sides and an
UNATTRIBUTED one: the comparands were not like-for-like, Task 14-A's
pipelining accounts for +920 cycles/token in the opposite direction, and the
draining-vs-dispatching instrument difference is a candidate this gate cannot
size. **The cleanest statement this census supports is the sum row**: 65.9 %
of device time is in neither lane, measured for the first time.

**The tool disposition Step 6 asks for.** Step 6 says "`sw/tok_meter.py`
learned the repack at Task 3, so use it; if that fix is not in, the census
comes from `evidence/qwen2b/rd/rd_census.py`". **Neither was used, and the
reason is structural rather than a missing fix.** `sw/tok_meter.py` reads
`R_PERF_CYC`/`R_PERF_BEATS` once per `V` record from the HOST — it is the
host-orchestrated path, which cannot drive a sequencer stream at all
(§10.3), and `evidence/qwen2b/rd/rd_census.py` is the 2B form of the same
host loop. A sequencer census has to read `S_PERF_CYC`/`S_PC` while the
engine runs and the two lane counters after HALT, which is what the new
`evidence/qwen9b/g6/g6_census.py` does. The step's own caveat — that it
"must not block on `tok_meter`" — is honoured; `sw/tok_meter.py` is still the
authority for the DDR-traffic figures in §10.3, which is host arithmetic and
needs no engine.

**Everything in §10 is DECODE. Prefill was never modelled and is not
measured here**; there is no batched prefill in this design, so a first-token
or chat-turn latency is a different number and **this gate does not present
one**.

---

## 11. THE RESIDUAL CLIP COUNTERS — observed, on chip

**There is no clip-counter CSR in the RTL.** `rtl/vec_alu.sv` clips on
almost every op (`clip16`, `clip20`, `clip32`) and `rtl/layer_chan.sv`
clips too, and none of them counts. So the count is taken from the chip's own
post-halt scratchpad, where the residual vectors live, plus the two headroom
probes the RTL does publish.

**T**, `025` (`023` is the same measurement with the binary point misnamed in
its banner — see below):

```
--- THE RESIDUAL RAIL, on chip (int16 Q8.7 from the manifest's rs_f=7; |x|max 32767)
  scratch words        65536 read back, 40882 non-zero
  AT +32767            28
  AT -32768            0
  CLIPPED TOTAL        28   (0.0685 % of the non-zero words)
  |x|max observed      32767  (100.00 % of the rail)
  |x| >=   50 % rail   696
  |x| >=   75 % rail   109
  |x| >=   90 % rail   64
  |x| >=   95 % rail   50
  |x| >=   99 % rail   35
--- the RTL's own headroom probes
  L_MAXP (vec_alu op-8 max|prod|, 48b)  64274136  (lo 0x03d4bed8 hi 0x0000)
  L_AMAXI / L_AMAXV (LM head argmax)    13 / 0x0001463a (83514)
```

**What this is, precisely.** It is the residual **after one forward step** —
the pad as the program left it — not a cumulative count over the six steps.
**28 words at the positive rail, none at the negative rail**, out of 40,882
non-zero words. The distribution is steep: 696 words above half the rail,
35 above 99 % of it.

**`|x|max` is 32,767 — the residual IS reaching the rail on silicon.**
§4.4's fragility is now **observed**, not assumed. Track L's reading stands
and is sharpened: the 95/108 top-1 was measured *with* this container in
place, and the container is demonstrably active.

**And it answers a question the clip counters were the wrong step for.** This
rung is the plan's **Step 7** ("the residual clip counters, on chip"), not
Step 5 (lockstep-then-chat) as an earlier revision of this line said. The
question it settles is **`evidence/qwen9b/g4/G4A_REPLAY.md` §6's Step 3′**,
recorded there as **NOT RUN**: whether the `RS_F 8 → 7` free rider removes
the residual clipping. The 9B pack took the free rider — the manifest reads
`rs_f = 7`, i.e. **Q8.7**, and
`evidence/qwen9b/g4/run_g4a_seqgate.sh` sets `FABLE5_RS_F=7`. **Q8.7 did NOT remove residual
clipping**: 28 words are still at the rail, measured on hardware rather than
on the six-step smoke.

**`L_AMAXI = 13` and the last token the OUT FIFO produced is 13** — the
argmax probe and the token stream agree, which is a small independent check
that the probe is reading the run that just happened.

**`023` is kept and its banner is wrong in one word**: it printed "int16
Q7.8" from the `RS_F_DEFAULT` of 8 rather than reading the manifest. Every
count in it is identical to `025`'s — 28 / 0 / 32767 / 696 / 109 / 64 / 50 /
35 — so `023` also serves as the repeat measurement: **the clip counts
reproduce exactly across two runs.**

---

## 12. THE WATCH ITEMS `evidence/qwen9b/g5/G5D_TIMING.md` FLAGGED — disposition, by class

| watch item (`evidence/qwen9b/g5/G5D_TIMING.md`) | what this gate can say |
|---|---|
| **The margin is 0.000/+0.001 and it was produced once**; ±ns placer spread is documented on this part | **The one placement that exists runs at speed and repeats.** Seed 1 ran six times with identical tokens and a device-time spread of **0.0097 %**, the widest over all nine timed runs being **0.0101 %** (§7.1 — the row used to pair the six-run subject with the nine-run number, re-review round 2 M-1); all four seeds and both smoke ladders halted with `err_code 0x00`, 24 tokens, 36,886 state checks each. **This is not a re-measurement of timing margin** and does not make the closure reproducible — it says the closed netlist computes correctly at 250 MHz over ~4 minutes of accumulated device time across 14 board runs, **at an unmeasured host temperature**: §15 records only the pre-program reading (`001` §6) and no rung after it read the host thermals at all |
| **`USER_CLOCK_ROOT X2Y2` is valid only while the placer keeps `layer_0` in SLR0** | **Not re-checked here, and it did not need to be.** The dependency is a property of the *build*, and the guard is `evidence/qwen9b/g5/g5d_clockroot_check.tcl` run on a candidate's routed checkpoint before signoff. This gate programmed the very checkpoint that guard already passed GREEN (`evidence/qwen9b/g5/170_t14b_fix1_clockroot_slr_ckr2_GREEN.log`, `CRC_LAYER_SLR: SLR0 (182 of 182 = 100.0%)`, rc 0). **Nothing on the board can observe a clock root**, so no board rung can discharge or falsify it. It remains live for the NEXT build, with §11's reading rule intact: `CLOCKROOT_SLR_OK ?` is a FAILURE |
| **The 300 MHz `xline_q0` CE cone in the matvec channels** (owned the first campaign's WNS under `ExtraTimingOpt`; closed at worst **+0.014** on the `AltSpreadLogic_high` family) | **The cone is exercised and it holds.** Every matvec beat in this gate crosses it: 3,902 MiB of weights streamed per full run, 5,480 MVGO records per model stream, 14 board runs. A functional failure there would appear as a wrong `y32` and therefore a wrong token or a `.chip` mismatch; **there were none**. That is a *functional* result at temperature, not a timing measurement, and +0.014 ns of margin is not made safer by it |
| **`ATTN_DSP` owned the WNS at −0.156 on the unconstrained roll; the DN/KV/CV caches and `u_dn` were also negative there** | Same reading: those paths are the attention and DeltaNet datapaths, exercised on every one of the 192 layer-steps per model run, and every post-halt state check matched. The +1-cycle `OREG_A/OREG_B` lever §11 names is **still available and still not needed** |
| **Roll #7's bitgen DRC failure** | Untouched. Nothing in the shipped artifact depends on it |
| **"The functional claim is S4's, not this build's"** | **This is the rung that changes that sentence.** §7.1 and §6 make the functional claim on the silicon |

### 12.1 The gate-port clamp — the user's ruling, and where the silicon stands on it

A watch item that is not `evidence/qwen9b/g5/G5D_TIMING.md`'s and belongs in
this disposition anyway. It arrived after the board session and is recorded
here in fix round 1.

**USER RULING, 2026-09-09 (interactive):** the gate-port clamp is **ACCEPTED
as the production operating point**. The reference saturates `dt_bias` to
±8 (Q3.12) and `A` to [0, 8) (Q3.15) into `rtl/gate_unit.sv`'s ports as they
are built; **61 of 768 heads' decay changed**, worst **68.45 % FS at L12
h18** (`evidence/qwen9b/g4/G4B_STRUCT.md` §4.2, `evidence/qwen9b/g4/G4B_STRUCT.md:642`:
`GATECLAMP worst runtime cost: L12h18 22430/32768 = 68.45% FS (spec 1779 -> clamped 24209), carried by A`).
**No bitstream change.** Port widening — a `rtl/gate_unit.sv` RTL change plus
a softplus ROM re-derivation (`evidence/qwen9b/g4/G4B_STRUCT.md` §4.3) — is a
**POST-SHIP follow-on**, carried on Task 16's list; the perplexity point
(≈ 7 h) was declined for now.

**What this gate can add to it.** The clamp was inside the G1/A2 fidelity
loop (`evidence/qwen9b/g4/G4B_STRUCT.md` §4.1), so **the chip and the
reference model it, identically, on both sides of every comparison in this
document**: `010`/`011`'s on-chip tokens are `evidence/qwen9b/g4/G4A_REPLAY.md`
§4.1a's on all four seeds, and `024`'s `ref/seq_model.py --gate` agrees with
`STATE BIT-EXACT`. **The silicon therefore carries the clamped decay and the
lockstep is clamped-against-clamped** — which is what makes the ruling safe
to accept and is also exactly what it does NOT test: no comparison in this
gate is against an unclamped reference, so nothing here measures what the
clamp costs. That measurement is `evidence/qwen9b/g4/G4B_STRUCT.md`'s, and
the follow-on is Task 16's.

---

## 13. THE SIGHUP RULING — measured, and DECLINED

A standing ruling in the migration ledger
(`.superpowers/sdd/2026-08-29-qwen35-9b-migration/progress.md:269`) holds that
`trap on_exit EXIT INT TERM` omits `HUP` in `sw/program_fpga.sh:125`,
`sw/stage1_hw_bringup.sh:68` and `sw/test_ctl.sh:57`, and that a dropped ssh
therefore leaves the endpoint off the PCI tree. It was interposed as a rung
before any further reprogram. **The edit was made, tested, and REVERTED. The
three files are unchanged at HEAD.**

**The board was never cycled to test it.** `g6_hup_trap.sh` runs a COPY of
`sw/program_fpga.sh` against stub `sw/pcie_helper.sh`, `sudo`, `vivado` and
`sw/board_lock.py`, with the Vivado settings64.sh source redirected to a stub
that puts the stub bin on `PATH`; the diff of the copy against the committed
script is printed into the log, so what was stubbed is on the record.

**Which arm is which, said the right way round.** An earlier revision of this
paragraph said "GREEN runs the committed bytes of the trap line; RED puts
back the one word", which reads backwards against HEAD, where the trap has
**no** `HUP`. At test time the working tree carried the PROPOSED edit — the
diff block in `013`'s own log shows it — so, precisely: **RED runs
`trap on_exit EXIT INT TERM`, which is the line as it stands committed at
HEAD**, and **GREEN runs `trap on_exit EXIT INT TERM HUP`, the ruling's
proposed edit**, which was made, tested and reverted. The arms are named for
the ruling's expectation, not for the tree.

**T**, `013` (RED, the OLD trap line, SIGHUP delivered mid-`[2/3]`):

```
=== [3/3] rescan the PCI tree (exit code so far: 0)
STUB-PCIE rescan
RESCAN: RAN — the endpoint was put back
G6_HUP_TRAP RED: DID NOT FIRE — the negative control is vacuous
```

**T**, `014` (GREEN, the trap line WITH `HUP`, same signal): the rescan also
ran — and `=== the script exited with rc=0`.

**T**, `015`, which isolates the mechanism (bash 5.2.21, an 8 s foreground
command hung up after 1 s):

| trap line | rescan | signal → handler | handler runs | caller sees |
|---|---|---|---|---|
| `EXIT INT TERM` (as committed) | **YES** | **0.003 s** | 1× | **rc 129** |
| `EXIT INT TERM HUP` (proposed) | YES | **7.003 s** | 2× | **rc 0** |

**Bash catches untrapped fatal signals and runs the EXIT trap before dying**,
so the rescan was never at risk and the premise does not hold on this host.
Adding `HUP` makes it worse twice over. First, bash **defers a TRAPPED signal
until the current foreground command returns**, so the rescan would wait out
the whole JTAG step instead of 3 ms — widening exactly the window the fix was
meant to close. Second, the handler's `exit $rc` sees `$? = 0`, so a
reprogram hung up mid-JTAG **reports SUCCESS**. That is the state
`sw/program_fpga.sh:186-193` calls "*** THE RESIDENT BITSTREAM IS NOW
UNKNOWN ***", about which it says the exit code "is the ONLY staleness
warning you get".

**`012` (`rc 2`) is kept for what it proves about a different rail.** The
harness's first cut put the stub bin on `PATH` only in the `settings64` stub,
which is sourced at `[2/3]` — after `[1/3]` has already run `sudo -n
pcie_helper.sh remove`. So the REAL `sudo -n` ran, against a stub in `/tmp`,
and answered `sudo: a password is required`. **The NOPASSWD escape is granted
to one absolute path and a stub is not it**: the rail held against this
test's own mistake.

**The reprogram in `002` ran with the traps as they are**, before this was
examined. `002`'s log shows all three steps completing and the endpoint
rescanned, so no drop occurred.

### 13.1 What is on the record about HOW `002` was launched — and what is not

An earlier revision of this section, and of §2.2, said the reprogram was
"launched detached (`nohup setsid`)" and then leaned on it: "which puts it
outside the ssh session's signal reach in the first place". **That is on no
log.** `evidence/qwen9b/run.sh` records the command it WRAPS, and `002`'s
`=== cmd:` line reads exactly:

```
=== cmd:  bash sw/program_fpga.sh synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper.bit
```

Anything outside the wrapper — how the operator's shell invoked
`evidence/qwen9b/run.sh` itself — is not captured, so **the detachment is the
operator's own untranscribed invocation and this document withdraws it as
evidence.** The campaign's standard is that a claim of this kind lives on a
log line; this one does not.

**What that costs, and what it does not.** §13's conclusion does not need it:
`013`/`015` show on their own that the EXIT trap fires on an untrapped
`HUP` — rescan at 0.003 s, `rc 129` — so the hangup hazard is covered by the
scripts as they stand. What DOES rest on the untranscribed detachment is the
**SIGKILL** residual: nothing in `013`/`014`/`015` covers `SIGKILL`, which no
trap can catch, and the only thing that would cover it is a detached launch.
**So `SIGKILL` and a hard ssh drop are NOT covered by anything on this
record**, and that is the honest state of it.

### 13.2 The controller's disposition

**The HUP ruling (migration ledger `M:269`) was WITHDRAWN by the controller
on this measurement** (2026-09-09): bash's EXIT trap already runs on an
untrapped `SIGHUP`, and adding `HUP` re-enters `on_exit` — rescan delayed
0.003 s → 7.003 s, caller rc masked 129 → 0. **The three `sw/` traps stay as
they are**, and the three files are byte-unchanged across this task's whole
range. The two residuals above (bash-implementation-specific EXIT-on-fatal-
signal behaviour, correctly version-pinned in `015`'s log; and no `SIGKILL`
coverage) are recorded, not closed.

---

## 14. FOUR DEFECTS FOUND ON HARDWARE, written up rather than fixed

Each is outside this task's commit block; each is a design decision, not a
typo. They are the substance of what a first silicon rung is for.

### 14.1 The conv witnesses are not a residency invariant across a run

**T**, `016`: the whole-pack audit run AFTER a program reported
`PACK DIFFERS 24 piece(s) MISS of 1139` — **all 24 of them conv images**,
every weight piece and the embedding byte-identical:

```
    ! conv conv[L0] chan=3 addr=0x89800000 131072 B: want 1e1f9ca7aff092c3 got 8aacbb41e1b94f93
    … L1 … L15 (the log lists the first 16 of 24)
```

That is not damage. **The program writes conv state into the same 128 KiB
blocks the host uploaded the conv weight taps into** (`STATE_CV_STRIDE`), so
a host-side hash of those blocks cannot survive a run.
`sw/chat_seq.py:1140-1142` reasons that the conv blocks "are the only part of
the DDR state region the host UPLOADS … so they are the only part a residency
probe can hold a host-side hash of", and `reupload_set` treats a conv miss
exactly like a weight miss.

**Reproduced in the clean flow. T**, `028`, immediately after a good run that
produced §4.1a's tokens with 36,886 state checks matching:

```
  residency  1146 witness blocks (1114 weight + 24 conv + 8 emb, 4584 KiB) in 38 ms -> 24 MISS
  reupload_set  0 image(s) missed a witness; the R-d rule escalates to ALL 249 image(s) + the embedding
```

**Zero weight images missed, and it would still re-upload 5.8 GiB** — 45.8 s,
on a perfectly healthy board, at the start of every session after the first.
The candidate fixes (witness only the weight-tap sub-range of each conv
block; or drop conv witnesses, since `upload_state` rewrites the conv images
unconditionally anyway) are a design decision and are named here, not taken.

> **RETIRED in fix round 2**, by a third answer neither candidate named: the
> two witness classes are probed at DIFFERENT MOMENTS.
> `sw/chat_seq.split_witnesses` (`sw/chat_seq.py:1206`) takes the conv
> witnesses out of the pack's probe — a weight witness covers DDR nothing but
> this host writes, so a miss really does prove another owner wrote it, while
> a conv witness is stale BY DESIGN after any run — and they are re-taken
> AFTER `bring_up_state` restores the region, where they audit the write that
> just happened. **T**, `078` on the same board: `residency 1122 witness
> blocks (1114 weight + 0 conv + 8 emb, 4488 KiB) in 35 ms -> 0 MISS`,
> `upload SKIPPED`, then `24 witness blocks (0 weight + 24 conv + 0 emb) …
> 0 MISS`. **R-d rule (b) is untouched**: a weight or embedding miss still
> invalidates the whole pack, and `--selftest` [22] pins both halves.

### 14.2 `--skip-weights` leaves the state region dirty, and the answer is silently wrong

**T**, `019`: a census run halted at the right PC with `err_code 0x00` and
emitted `[760, 369, 279, 13, 198, 760]` instead of §4.1a's tokens, **with
nothing anywhere reporting a fault**. The cause: that tool uploads no
weights, and `upload_state` under `--skip-weights` is `csrs_only=True`, so
the DN and conv state left in DDR by the PREVIOUS run is the state `SLD`
loads. `sw/seq_run.py`'s `--zero-scratch` exists for exactly this failure
class in the scratchpad; **the state region has no equivalent, and it is a
much bigger surface.**

This is the same shape as RD_GATE §4.2's stale LM head — a clean-looking run
answering with the wrong token — **arriving through the state region instead
of the weight pack**, and it is new to the spill design. `g6_census.py` and
`g6_clip.py` now write the initial region image themselves (`--fresh-state`),
which is a workaround in two instruments, not a fix in the tool.

> **HALF-ADDRESSED in fix round 2, and only on the chat path.**
> `ChatSession.bring_up_state` (`sw/chat_seq.py:2399`) writes the region's
> initial contents on every session and never takes `upload_state`'s
> `csrs_only` branch, and the per-context reset now restores the conv taps as
> well as memsetting DN. `--selftest` [22] pins `csrs_only is False` for
> exactly this reason. **`sw/seq_run.py --skip-weights` is unchanged** and
> the defect stands there: the KV region is still nobody's job, and this
> gate's own long-context rung has to call `g6_state.py --write-initial`
> first (§8.7).

### 14.3 Nothing ties the resident weight pack to the resident MODEL

**T**, `026` attempt [1] followed by `027`: running `sw/chat_seq.py` with its
default template on a board holding the 9B pack made its residency probe miss
every 2B witness, and R-d rule (b) did what it is supposed to — **re-uploaded
the whole 2B pack over the 9B one.** `027`:
`PACK DIFFERS`, with `w1`, `w2`, `w3`, `w4`, `w5` … reading 2B bytes.

Nothing is wrong with rule (b). What is missing is any tie between the weight
pack and the resident model. The identity gate checks MAGIC, CALIB, VERSION
and five IDENTs, **all of which passed**, because the netlist really was the
one the tool expected — it is the ARTIFACT that did not belong. A model
identity beside the VERSION check is the obvious shape of a fix.

**No measurement in this gate is affected**: every one of them precedes
`026`, and `028` restored the pack.

**What `028` actually verified, said precisely.** An earlier revision cited
§5.3 here, which is the whole-pack audit — and `028` ran no whole-pack audit.
What it ran is `sw/seq_run.py`'s own per-piece readback,
`5845 MiB written, 5845 MiB read back and compared, 45.8s` (`028`:35), with
`[readback OK]` on the 249 weight images, the 1,940 MiB embedding, the
seqdata, the stream and the 24 conv images (`028`:29-34) — plus the witness
sampler afterwards, which reported `24 MISS` on the conv blocks alone and
`0 image(s) missed a witness` (`028`:112-113), i.e. §14.1's expected conv
behaviour and nothing else. That is a per-piece byte comparison of every byte
uploaded, which is stronger than the sampler and different from a whole-pack
hash of what the board holds AFTER a run.

### 14.4 `SCRATCH_WORDS_BUILT` was a silent under-clear

§4.2. Raised in this task, as its own comment instructed. Recorded here
because the READ side was merely an `IndexError` while the WRITE side was
`--zero-scratch` reporting a half-cleared pad as clean.

### 14.5 The two lane counters are 32-bit, and a chat-length session WRAPS them

**Found in fix round 2, by the long-context rung.** `L_LCYC` and
`L_SDMA_CYC` are 32-bit accumulators at `ACLK_HZ` (`sw/hwmap.py:199`,
`sw/hwmap.py:229`), so each one covers **2³² / 250 MHz = 17.18 s of BUSY
time** and then wraps — silently, with no flag the host can read. Every
earlier use in this gate is a single ~823 ms program (§10), two orders of
magnitude inside that. **A chat session is not.**

**T**, `084` [3], over the 527-launch long-context session (69.6 s of device
time): `L_LCYC 1766603095 cycles = 7066.412 ms`, i.e. **13.409 ms/step**.
**T**, `086`, the SAME instrument bracketing a 43-launch session minutes
later: **40.573 ms/step**, which is §10.2's 41.588 ms/token to 2.4 % and is
the number a shorter run of the same program gives. A compute lane cannot
get 3× cheaper per step at 12× the context.

**The arithmetic says one wrap, and only one.** 527 steps × ~41 ms ≈
21.6 s of busy time = 5.4 × 10⁹ cycles, against the counter's 4.295 × 10⁹
range. Adding one wrap to the reading gives 6.062 × 10⁹ cycles =
**46.01 ms/step** (D), which is the right side of the short session's 40.573
for a run whose decode steps are 147.9 ms instead of 137.7. **That corrected
number is an INFERENCE and is labelled one**; the raw counter reading is what
`084` contains.

`L_SDMA_CYC` did **not** wrap on the same run — 762,542,182 cycles is 18 %
of the range — so §8.7's 5.788 ms/step is a measurement.

**How long a session each lane survives — corrected (round-3 review m7).**
This section used to say that 18 % of the range on a 70 s session means "a
two-minute session would lose it too". That does not follow: 3.05 s of busy
DMA in 70 s of wall is a **4.4 % duty cycle**, so `L_SDMA_CYC` wraps at
**≈ 6.6 minutes** of session wall clock, not two. The error was on the safe
side, but it was a wrong number inside a defect write-up. The companion
bound the section owed and did not give: at this program's **≈ 31 % compute
duty**, `L_LCYC` wraps at **≈ 55 s** of session wall — about **420
launches**, which is why a 527-launch session lost it and a 43-launch one
did not.

**WHICH QUOTED NUMBERS ARE AFFECTED — every lane reading in this document,
checked against the 4.295 × 10⁹-cycle range (round-3 review §3.2).**

| where | reading | busy time | % of range | verdict |
|---|---|---|---|---|
| §10.2 `L_LCYC` (`020`) | 62,382,496 | 249.5 ms | 5.8 % | **unwrapped** → 41.588 ms/token stands |
| §10.2 `L_SDMA_CYC` (`020`) | 7,687,467 | 30.75 ms | 0.18 % | **unwrapped** → 5.125 ms/token stands |
| §8.7 `L_SDMA_CYC` (`084` [3]) | 762,542,182 | 3,050.2 ms | 17.8 % | **unwrapped** → 5.788 ms/step stands |
| §14.5 `L_LCYC` (`084` [3]) | 1,766,603,095 | 7,066.4 ms | — | **WRAPPED** → 13.409 ms/step is not a measurement |
| §14.5 / §8.7 `086` `L_LCYC` | 436,162,646 | 1,744.7 ms | 10.2 % | **unwrapped** → 40.573 ms/step stands |
| §14.5 / §8.7 `086` `L_SDMA_CYC` | 54,219,240 | 216.9 ms | 1.3 % | **unwrapped** → 5.044 ms/step stands |

**Exactly one quoted number is affected, and this section already withdrew
it.** Everything else in §10 and §8 comes from a different instrument and is
untouched: §10.1's 137.1210 ms/token and 7.2928 tok/s are `S_PERF_CYC` over
822.726 ms (205.7 M cycles, nowhere near 2³²), and every per-step ms in §8.4
and §8.7 (126.5 / 137.7 / 131.6 / 147.9) is a host `device_ms` over a
sub-200 ms launch. The corrected **46.01 ms/step** stays labelled an
INFERENCE.

**Nothing here is an RTL bug**: the counters do what A1.4 says, and
`rtl/layer_chan.sv:473` (`logic [31:0] sdma_cyc;`) / `:475` (`logic [31:0]
lcyc;`) are confirmed 32-bit. The defect is that the HOST has no way to know
a reading wrapped, and both of this project's newest instruments
(`g6_census.py`, `g6_lane_counters.py`) present the reading as a
measurement.

**The two fixes, and which is which (round-3 review m8).** The host bound —
refuse, or warn, when `steps × device_ms` exceeds 17.18 s — **detects** the
hazard and is the right immediate guard for `g6_census.py` /
`g6_lane_counters.py`. It cannot make a wrapped reading usable. **The
durable fix is RTL** — widen `lcyc`/`sdma_cyc` past 32 bits, or add a sticky
wrap bit beside `STATUS` so the host can read whether a counter turned over
— and it therefore needs a bitstream, which makes it **POST-SHIP**. It goes
on Task 16's follow-on list beside the gate-port widening (§12.1). Neither
is taken here.

---

## 15. TEMPERATURE, RUN LENGTH, AND WHAT THE BOARD CARRIES NOW

**There is no temperature CSR.** `rtl/csr_block.sv:149-157` decodes exactly
six read addresses — MAGIC, VERSION, SCRATCH, CALIB, UPTIME lo/hi — and no
XADC/SYSMON path is exposed to the host. So the temperature on record is the
HOST's, from `sensors` on snoke, and it is labelled as such.

**T**, `001` §6, immediately before programming: `Package id 1: +59.0 °C`
(high +85, crit +95), cores 50–53 °C; `snoke` up 21 days, load 1.77.

**Run length.** **Seventeen** sequencer program runs between 19:35 and 20:21
— two one-layer smokes, four token smokes and **eleven** full-model programs
at ~822.8 ms device each — plus the 2B preamble launch at `026` that halted
with `err_op`. **D**: ≈ **9.15 s** of accumulated device time
(11 × 822.8 ms + 4 × 16.28 ms + 2 × 15.2 ms), inside ~46 minutes of wall
clock, and on the order of 35 GiB of DMA in each direction across the
uploads, the re-uploads and the four whole-pack audits.

**What the board carries now**, as of **`148`** — 2026-09-10 **19:33:17**,
Task 15-D's `--verify-head` attempt, **the last run that held the lock and
wrote a DDR byte** — with the KV region as **`141`** (19:22:54) left it,
because `148` refused before it ran a single launch.

**This table has now been re-taken twice, and the second re-take was wrong
too.** It read "as of `086`" until round-4 review I-1 caught it; the
collection round moved it to `110`; the collection round's own review then
found that **thirteen runs held the lock AFTER `110`** — Task 15-D's chip
sessions. Twelve of them print the lock path
(`evidence/qwen9b/g6/128_15d_det_a.log:49` at 19:12:49 through
`evidence/qwen9b/g6/141_15d_bisect_k14.log:49` at 19:22:54) and `148` is the
thirteenth, which held the lock but died before the banner is printed
(`sw/chat_seq.py:6550` acquires it; `sw/chat_seq.py:6588` prints it, and
`148` raised at `sw/chat_seq.py:6581`). **The standing lesson: a heading that
says *now* has to be re-derived from the logs' own timestamps, not from
whichever round last edited the section.**

| | |
|---|---|
| bitstream | `build_041_ckr2_AltSpreadLogic_high`, **VERSION `0xc973c18a`**, JTAG-volatile, CALIB 0xF — **unchanged since `002`**; fix rounds 2 and 3, Task 15-D, Task 15-D2, Task 15-D3 and this collection round all programmed nothing. `evidence/qwen9b/g6/148_15d_verify_head.log:18` reads it back last: `board      MAGIC=0xfab1e001 VERSION=0xc973c18a CALIB=0xf SEQ=READY` |
| weights | **`model_9b_s1`** — 249 images, 3,902 MiB + the 1,940 MiB embedding, **NOT re-uploaded by any rung since `028`**: every chat session, `110`, the 15-D bisect and `148` included, read `1122 witness blocks … 0 MISS` and `upload SKIPPED` (§8.3, and `evidence/qwen9b/g6/148_15d_verify_head.log:21`). The whole-pack sha `602b008c70fd8aec…` is still the digest **as verified at `017` §8, BEFORE the conv blocks moved** |
| stream | `model_9b_s1.e4`, 158,536 records at `0x9000000`; the const blob at `0xc000000` is **8,940,032 B** (4,096 positions × 2,048 B), up from 1,600,000 B — scope E. **Last written by `148`**, whose bring-up re-uploaded the blob and the three images and read them back (`evidence/qwen9b/g6/148_15d_verify_head.log:27`) |
| state region | **in two parts, because the last writer and the last runner are different runs.** (a) **DN and the 24 conv blocks are as `148`'s bring-up left them** — DN zeroed with its eight zero witnesses and the conv images re-written and read back (`evidence/qwen9b/g6/148_15d_verify_head.log:22`-`evidence/qwen9b/g6/148_15d_verify_head.log:23`). (b) **The KV region holds `141`'s 446 rows over the long run's 526**, and TCNT is `141`'s, because `148` raised before its preamble and ran NO launches: `evidence/qwen9b/g6/141_15d_bisect_k14.log:61` records 447 launches (1 preamble / 442 lite / 4 full) and `evidence/qwen9b/g6/141_15d_bisect_k14.log:66` records 446 of 700 forward steps at a KV bank depth of 4,096. A context reset does not clear KV, so rows 446..525 beneath the top are still the 526-step session's and TCNT is what makes them unreadable (§8.7, §22.1) |
| EMBLOG2 | 13 — `evidence/qwen9b/g6/148_15d_verify_head.log:19`, `EMBLOG2    13 (8192 B embedding rows)` |
| lock | released; the shared lock is free. `148` exited `rc 1` on its own refusal (`evidence/qwen9b/g6/148_15d_verify_head.log:42`) and the lock went with the process |
| host | snoke. **The only `sensors` read this campaign holds is `001` §6's, taken BEFORE anything was programmed** — `evidence/qwen9b/g6/001_etiquette_resident_readback.log:49`, `Package id 1:  +59.0°C  (high = +85.0°C, crit = +95.0°C)`, cores 50–53 °C, up 21 days. **No rung after `001` read the host thermals** — not `110`, not Task 15-D's fifteen board processes, not `148` — so there is no later number and none is stated here or in §22.2 |

**A note on citing `141` and its siblings BY LINE — with the exposure
BOUNDED.** The bisect logs carry `sw/chat_seq.py`'s in-place prefill
progress, written with carriage returns: `141_15d_bisect_k14.log` holds
**444** of them over **109** newlines. A reader that treats `\r` as a line
break therefore sees **553** lines where `grep -n`, `sed` and `wc -l` see
**109**. This is not hypothetical, and the two halves of `spec_cites` do not
agree with each other about it: the QUOTE window reads with
`evidence/qwen_next/spec_cites.py:363`, `with open(path, 'r', errors='replace') as f:`
— default universal newlines — and splits the result, giving 554 entries
for 553 lines plus the empty field after the final newline; the RANGE check
counts with `evidence/qwen_next/spec_cites.py:358`,
`with open(path, 'rb') as f:`, which gives **109**. So a `grep -n` citation
into these logs passes RANGE and only its QUOTE window can land elsewhere.

**The exposure is exactly two citations, and both are quote-free.** Of every
`path:line` citation into a carriage-return-bearing log in this document and
in `NEXT_SESSION.md`, only `evidence/qwen9b/g6/141_15d_bisect_k14.log:61` and
`evidence/qwen9b/g6/141_15d_bisect_k14.log:66` resolve to different text
under the two numberings. `evidence/qwen9b/g6/110_chat_verify_9b_rd3.log:44`,
`evidence/qwen9b/g6/128_15d_det_a.log:49` and
`evidence/qwen9b/g6/141_15d_bisect_k14.log:49` are identical either way,
because in each of those files the first carriage return falls after the
cited line. **Every `path:line` citation into these logs in this document is
`grep -n`'s numbering**, and the two figures at
`evidence/qwen9b/g6/141_15d_bisect_k14.log:61` and
`evidence/qwen9b/g6/141_15d_bisect_k14.log:66` are transcribed rather than
machine-quoted for that reason. The bound is
recorded so a later round can re-check it mechanically — two citations, both
quote-free — instead of re-deriving the rule.

**A next session that wants §4.1a's tokens must re-establish the initial
state region** (§14.2) — `g6_state.py --write-initial`, or a full
`seq_run` without `--skip-weights`. **A next session that wants CHAT does
not**: `sw/chat_seq.py` writes the region itself now (§8.3 C).

**THE LOCK — SEVENTEEN logs in this directory print its path, and the list
is now complete.** `078`, `080`, `083`, `084`, `110`, and then Task 15-D's
twelve: `128`, `129`, `130`, `133`, `134`, `135`, `136`, `137`, `138`, `139`,
`140`, `141`. The banner is the same line in every one —
`evidence/qwen9b/g6/110_chat_verify_9b_rd3.log:44`, `board lock /home/cah/r2d2/code/fpga/.fable5_board.lock  held for this process's lifetime`,
and `evidence/qwen9b/g6/141_15d_bisect_k14.log:49` is the last of them.
`079` and `086` do not print it, and the reason is their harness, not their
behaviour: both filter `sw/chat_seq.py`'s output through `grep` to keep four
seeds and two counter reads readable. **`148` does not print it either, and
its reason is different and worth stating**: it HELD the lock — `main()`
acquires it at `sw/chat_seq.py:6550`, before the session object exists — and
raised at `sw/chat_seq.py:6581` (`attach_sampling`), which is before
`sw/chat_seq.py:6588` prints the banner. Neither tool can run without the
lock — `sw/chat_seq.py`'s `main()` acquires it BEFORE the board and exits 4
if it cannot, and `g6_lane_counters.py`, `g6_kv_depth.py` and `g6_state.py`
each acquire it before opening the device, printing no banner of their own
(which is why `127` and `132` hold it silently; `131`, `150` and `151` are
`--compare` runs over two committed JSONs and open nothing) — and
**`--no-lock` appears on no command line anywhere in this gate**, in any
log.

**Fix round 3's own run length, and fix round 2's.** Fix round 3 touched the
board **once**: `110`, one 23-launch `--verify` session (1 preamble / 18
`lite` / 4 `full`), 01:04:35 → 01:50:38, **46 m 03 s** of lock while the
board idled and the host computed — **D**: `18 × 126.5 + 4 × 137.5` =
**2,827 ms ≈ 2.83 s** of accumulated device time, from `110`'s own per-image
means. **No weight DMA, no reprogram, no flash, no sudo.**

**Task 15-D's own run length — the rounds that made this table stale.**
Between **19:10:23 and 19:33:41 on 2026-09-10**, Task 15-D opened
**fifteen** board processes: two readbacks that launch nothing (`127` and
`132`), three 505-launch determinism sessions (`128`/`129`/`130`), nine
bisect sessions (`133`-`141`, the deepest of them `141`'s 447 launches) and
`148`, which brought the board up, wrote the state region and then refused. **Task 15-D2, Task 15-D3 and this
collection round opened none at all** — every log they wrote is a
board-free replay or a checker.

**Fix round 2's own run length.** **Ten** chat sessions between 23:07 and
00:01 — one greedy (43 launches), four sampled (43/43/43/28), one
`--verify` (23), three long-context (527 each) and one 43-launch counter
run — **D**: **1,847 launches** and ≈ **243 s** of accumulated device time
(each session's launch counts times its own per-image device means, as its
log prints them), plus five short CSR/region processes that launch nothing. **Not one byte of
weight DMA in any of them.** The `--verify` rung held the lock for
**44 m 48 s** while the board idled and the host computed, which is what
lockstep costs at 9B (§8.7).

---

## 16. WHAT IS *NOT* ESTABLISHED BY THIS GATE

1. **`024` is complete and green on all four seeds** (§7.3) — this item is
   discharged. It is recorded here only because an earlier revision of this
   document was committed while `024` was still running, with the seed-1
   verdict transcribed and the rest explicitly not claimed; that is the rule
   about never citing a log before its `=== rc:` exists, working.
2. ~~**Chat, sampled chat, the template check, and long context**~~ —
   **DISCHARGED in fix round 2**, §8.2. All four ran on the resident
   silicon. What is *still* not established from those rungs is named where
   it belongs: the sampled rung shows the PATH is correct, not that
   `--temp 0.8` is a good operating point (§8.5); and the long-context
   rung's per-step token lockstep **had not been run** as of fix round 2,
   for the measured reason in §8.7 — `ref/seq_model` costs 131.2 s (`lite`)
   / 149.3 s (`full`) of host time per 9B step (**T**, `074`), so 526 steps
   is **19.3 h**, not §20.3's estimated hour. **Fix round 3 launched exactly
   that replay** (§8.7a, `106`, pid 878615, detached at 00:44:07), and
   **this item is now DISCHARGED too.** `106` landed FAIL, and the FAIL was
   the reference's operating point rather than the chip (§22.11); `149`
   landed `LONGCTX_LOCKSTEP: PASS 504/504` and `171` landed
   `LONGCTX_LOCKSTEP: PASS 526/526`, 24 decode steps at positions 502..525
   (§22.12b). **The long-context rung's correctness against the reference is
   ESTABLISHED at the derived operating point.** What remains not
   established here is the CEILING, which is item 11 below and not this
   one.
3. **No timing margin was re-measured.** Nothing on the board observes WNS.
   §12's functional results are evidence that the closed netlist computes
   correctly at speed; they are not evidence that 0.000 is reproducible, and
   `evidence/qwen9b/g5/G5D_TIMING.md` §11's warning stands unchanged.
4. **The per-token per-channel matvec spread** is not measurable on the
   sequencer path with this netlist's counters (§10.3). The 0.42 % figure is
   the static split, LABEL D.
5. **Prefill, first-token latency and any user-facing turn time.** §10 is
   decode only. There is no batched prefill in this design.
6. **The clip counts are one forward step's**, not cumulative, and from one
   prompt (§11). Two runs agree exactly; four prompts were not censused.
7. **Nothing here re-validates the 2B.** The 2B pack in DDR is gone
   (`evidence/qwen9b/g5/G5D_TIMING.md` §11 predicted exactly that), and `026` shows the 2B
   stream halts with `err_op` on this netlist.
8. **WHY the compute lane reads 9.9 % below the chip TB is NOT
   ESTABLISHED** (§10.2a). The measurement holds on both sides; the
   attribution does not exist. Task 14-A's pipelining is accounted for and
   points the other way (+920 cycles/token), the draining-vs-dispatching
   instrument difference is a candidate this gate cannot size, and S4's own
   `LAT` sweep weakens the memory-model candidate. No board rung can settle
   it.
9. **`nch=1` was never run on this netlist and cannot be** (§4.2). The rung
   is discharged by an address-map REFUSAL measured on the resident
   manifest, not by a run. Whatever a 1-channel weight placement would do on
   this bitstream is untested — at 9B it is unreachable.
10. **`055` proves the EMBLOG2 CSR is writable and reads back; it does not
    prove the embedding FETCH uses it.** That is `008`'s `36886 state checks,
    ALL MATCH` on a stream whose EMB records read 8,192 B rows, and it is a
    different rung.
11. **THE CONTEXT CEILING IS NOT LIFTED BY `171`'s PASS.**
    `rtl/attn_core.sv:114`'s `logic signed [39:0] denom` accumulates Q30
    terms and can wrap where the reference's int64 cannot, so the design is
    bounded at **T < 512 BY ANALYSIS** (§22.7). That bound is a WORST CASE —
    the sum wraps only when every score sits at its maximum — and `171`'s
    fourteen agreeing steps at T = 512..525 are evidence that the worst case
    was **not reached in that session**, not proof that it cannot be
    (§22.12b). `denom` stays a scheduled post-ship RTL fix; the ceiling is
    not an observed defect and the PASS is not a licence to raise it.

---

## 17. THE SUPERLATIVE CHECKER, AND WHAT IT CAUGHT

`g6_superlatives.py` is a copy of `evidence/qwen9b/s5/s5_superlatives.py`
(itself a copy of Task 13's), re-pointed at a board gate. **The reason it
exists is unchanged**: a false superlative slipped into the G5a gate doc in
four successive rounds, twice inside the sentence written to repair the
previous one, and re-reading does not catch that.

**What had to change, because a board gate's risky claims have a different
shape.** S5's variants are Vivado placements and its columns are WNS/TNS/
fan-out slacks. G6 has no placements. Its variants are BOARD RUNS, harvested
from this directory's own logs under the same "nothing is typed in" rule, and
its risky claims are mostly **derived percentages** rather than rankings. So
this copy carries a **second half** S5 has no need of: every derived quantity
the doc states is **recomputed from the harvested numbers** and compared with
what the doc prints, to the last digit.

**It caught a real error in §7.1's first draft** — which is the whole point,
and is recorded rather than quietly fixed. The draft said seed 1 ran "six"
times, listed **seven** device times, and **three of those belonged to s2, s3
and s4**. The script harvests device times itself and classifies each run by
its program's record count (158,536 / 79,289 / 2,108 / 4,091), so it reported
five seed-1 runs and a spread of 0.0097 %, against the draft's 0.0101 %.
§7.1 now states both numbers for what each is.

**It also caught a defect in its own first cut**, which is worth recording
because it is the same class: the token-smoke spread was computed over a
device-time band `10 < ms < 20`, which swept in the ONE-LAYER smoke at
15.234 ms and turned a 0.012 % spread into 6.9 %. Classification is by record
count now, and the reason is a comment in the file.

**AND IT CAUGHT A SECOND ERROR, in the run counts.** The first harvest read
eight full-model device times and reported five seed-1 runs. Adding `016` to
its log set — `016` §1 is a full live run, and leaving it out made "every
full-model run" a claim over a set the harvester could not see — took that to
**nine timed runs, six of them seed 1**, and §7.1 now says eleven full-model
runs, nine timed, eight golden-checked, with the reason `023`/`025` record no
device time. A checker that harvests an incomplete set is a checker that
passes an incomplete claim.

**T**, `068_superlatives_v5.log`: `G6SUP: PASS`, 0 superlative failures, 0
numeric failures, `G6SUP_DERIVED_TOTAL: 17 quantity(ies) recomputed from the
logs` — and all seventeen matching what this document prints. **`068` is the
run over the document as committed**; `031`/`042`/`044`/`046`/`065` are the
same verdict at earlier drafts — `065`/`066` covered every word of this
document except §19.2, which was written after them, and they are kept for
exactly the reason `046` is.

**`046` was NOT that run, and the sentence claiming it was is withdrawn.**
`046`/`047` ran at 21:07:31 and were committed in `87e7028` at 21:07:50; the
document was then rewritten TWICE — `3a9a382` and `bef700b`, together
**+140 / −56** lines, including the whole of §19 and its new numbers, and §16
item 1 — and fix round 1 has rewritten it again. `046`'s own UNCHECKED list
still quotes §16's OLD sentence, which is direct proof the checker never saw
the committed text. **The instrument that certifies a document has to run on
the document**, and `068`/`069` were fix round 1's such run.
**Fix round 2's is `102`/`103`** — `G6SUP: PASS` and
`G6SUP_CONTROL: CAUGHT BOTH — the checker is live` on the text this round
commits, with `089`-`100` kept as the same pair at earlier
revisions, for exactly the reason `046` is kept: each predates a
later edit — several to §17 itself, two to §19.3 to get `095`'s and
`098`'s `spec_cites` failures out, and one to §15 for the lock statement above — and this document does not pretend
otherwise. They are the last thing this round does
before `spec_cites`, with nothing edited after them.

**T**, `069_superlatives_control_v5.log` (and `032`/`043`/`045`/`047`/`066` before it), the
negative control (`superlative-check: quoted` — this paragraph deliberately
restates the planted false claim in order to explain it, and the checker
flagged it as a FAIL until the marker was added, which is the escape hatch
working), which plants BOTH a false superlative — awarding "fastest"
to `011_model_9b_s2s3s4.log`, which is the SLOWEST at 822.809 ms — and a
false derived number: `G6SUP_FAIL` on the first, `G6SUP_NUMFAIL` on the
second, and `G6SUP_CONTROL: CAUGHT BOTH — the checker is live`. **A checker
that cannot fail is not evidence**, so the control runs before the doc is
committed and its log is committed beside the real one.

**The UNCHECKED sentences are listed in the run's own log and are
hand-verified here** — 34 at fix round 1's `068`, 39 at fix round 2's
`102`, **49** at fix round 3's closing pair. Every one of them trips the marker regex on the ordinary English word
"only" ("JTAG-volatile **only**", "AXI-Lite **only**", "decode **only**",
"the **only** staleness warning you get", "the **only** part of the DDR state
region the host UPLOADS"), or on "most" ("what a zero-margin closure **most**
needs measured"), or on the phrase "of the eight" — and **not one is a
comparative ranking between runs**. UNCHECKED is not a pass — that is why
they are enumerated in the log rather than suppressed — but in this document
the residue is idiom, not arithmetic.

**The count was misquoted, and it has also grown twice.** An earlier revision
said "The 18 UNCHECKED sentences", and no log in this directory has ever
reported 18: `031` = 20, `042` = 22, `044` = 20, `046` = 20, `065` = 34,
`089` = 38, `091` = 39, `093` = 39, `096` = 39, `099` = 39, `102` = 39,
`116` = 48, `117` = **49**. The **34** is `068`'s own `G6SUP_UNCHECKED:` line on the text
fix round 1 committed; the rise from 20 was fix round 1's own prose — §4.2,
§9.2, §10.2a, §12.1, §13.1, §18.1, §19.1 and §20 add fourteen more sentences
carrying "only" or "most". **The ten more at `117` are fix round 3's own**, and every one is the
same idiom: §14.1's "witness **only** the weight-tap sub-range", §14.5's
"one wrap, and **only** one" restated, §16's "decode **only**", §17's own
two sentences about the count, §18.2's "checked every one mechanically",
§18.3's "the **only** tokens affected" and "digit-only", §19.2's withdrawn
"**only** in `067` and `070`", §20.6's "covered by the selftest **only**",
and §21's list of what the round answers. **Not one is a comparative
ranking between runs.** **The five more at `102` are fix round 2's own**: §8.5's
"the ONLY transfer whose shape does not depend on the geometry"-class idiom,
§8.7's "the ONLY witness", §14.5's "one wrap, and only one", §20.6's "the
only item with an hour-scale reference cost", and this paragraph, which
carries the word while counting it — all five idiom, none a ranking between
runs, and `089`-`100` are the same pair at earlier revisions, at 38 and then 39 throughout.

---

## 18. CITATION DRIFT — 49 repaired, 8 residual, every one of them examined

This task edited seven files outside `evidence/qwen9b/g6/`:
`sw/seq_run.py`, `sw/infer.py`, `sw/hwmap.py`, `sw/chat_seq.py`,
`docs/USAGE.md`, `docs/ARCHITECTURE.md` and `NEXT_SESSION.md`. Everything
that cites them by line moves when they do, and
`evidence/qwen9b/o3/o3_cite_drift.py` is what closes that.

**THE FIRST PLAN WAS A WARNING, NOT A RESULT.** `033_cite_drift_plan.log`:
**`TOTAL REPAIR 340 COLLATERAL 11`** across **30 documents**,
`O3_FIX_PLAN: UNSAFE`. Almost none of that was the constants. It was
**comment prose**: the first cut of these edits added 36 lines to
`sw/hwmap.py`, 11 to `sw/seq_run.py`, 7 to `sw/infer.py` and 1 to
`sw/chat_seq.py`, and every line inserted near the top of a file drags every
citation below it in every document in the repo.

**So the edits were rewritten to be LINE-NEUTRAL**, which is the right answer
rather than a workaround: the information belongs in this document, and the
code comments only have to point at it. The four `sw/` files are now
**+0 / +0 / +0 / +0** net lines (`sw/hwmap.py` is 19 insertions against 19
deletions), and the two remaining internal offsets inside `hwmap.py` cancel
(+1 at line 251, −1 at line 277). `034`, `035` and `036` are the three
re-plans that measured the shrink: **340 → 44 → 44 → 44 repairs**, and
**11 → 2 → 2 → 1 collateral** as each remaining insertion was absorbed.

**The repair. T**, `037_cite_drift_fix.log` (`rc 0`):
`FIXED 49 citation(s) in 12 document(s)`, with
`docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md` EXCLUDED
because the tool flagged one of its rewrites as collateral and its own rule
is "repair the stale one(s) BY HAND or `--exclude` the document."

**The excluded document was repaired BY HAND, from the tool's own map.**
`039_cite_drift_spec_check.log` lists its 20 drifted lines — every one a
`NEXT_SESSION.md` shift of +61, +63 or +64 caused by this session's new entry
— and the ten citation tokens carrying them were rewritten to exactly those
coordinates. **T**, `040_cite_drift_spec_verify.log`:
`relocated 20 citation(s) checked against the base content and the citing
documents`.

**THE RESIDUAL IS 8, AND ALL EIGHT ARE BENIGN. T**,
`041_cite_drift_verify_final.log` — `relocated 49 citation(s) checked`, then
five `UNRESOLVED` and three `HALF-MAPPED`. The tool cannot map them because
the CONTENT of the cited line changed, not because the line moved, and it
refuses to guess — correctly. Each was checked by hand:

| residual | why the tool could not map it | verdict |
|---|---|---|
| `sw/seq_run.py:130`, cited by `sw/hwmap.py` | the `EXPECTED_SEQ_VERSION` line's text changed | **still line 108** — the citation is CORRECT |
| `sw/infer.py:98`, cited by `sw/hwmap.py` | the `EXPECT_VERSION` line's text changed | **still line 98** — CORRECT |
| `sw/hwmap.py:292`, cited by `docs/SEQ_ISA.md`, `evidence/qwen2b/rb/seq_isa_ref_sweep.txt` | `SCRATCH_WORDS_BUILT = 32768` → `= 65536` | **still line 287** — CORRECT |  <!--cites:noquote-->
| `sw/hwmap.py:287-292` and `:288-292`, same citers | the END endpoint is the line above | both endpoints unmoved — **CORRECT** |
| `docs/ARCHITECTURE.md:15`, cited by `docs/QWEN2B_QUANT_STUDY.md:859` for "0.8B measured 30.4 tok/s" | the decode-rate row was rewritten for 9B | **still line 15, and it still carries "0.8B 30.4 tok/s"** in the historic tail — CORRECT |
| `sw/hwmap.py:96` and `sw/hwmap.py:88-96`, cited by `evidence/qwen9b/g3/G3_3_MATVEC.md:915` | the "Task 16 adds…" comment was rewritten | **DELIBERATELY STALE, and must stay so.** That line is prose *about a past repair* — "the `sw/hwmap.py:88-96` half-mapped range in this very document, which was hand-repaired to `sw/hwmap.py:118-134`". Rewriting a historical coordinate would destroy the record it exists to keep |

**Nothing was left to be discovered**: the residual is eight, every one is
named above with the reason, and none of them is a stale pointer.

### 18.1 Fix round 1's own drift — 25 citations, 4 documents outside the block

Fix round 1 edited exactly two tracked files: `NEXT_SESSION.md` (+36 lines)
and this document. Nothing cites this document by line, so all of the drift
is `NEXT_SESSION.md`'s, and it is the same mechanism as above: a new entry at
the top drags every citation below it.

**T**, `061` (`--plan`, `rc 1`): `TOTAL REPAIR 18 COLLATERAL 2`,
`O3_FIX_PLAN: UNSAFE`, with the collateral in the migration spec — the same
document, for the same reason, as `037`. **T**, `062` (`--fix` with that
document `--exclude`d, `rc 0`): `FIXED 25 citation(s) in 4 document(s)` —
`evidence/qwen9b/g3/G3_3_MATVEC.md`, `evidence/qwen9b/g3/G3_4_LAYER.md`,
`evidence/qwen9b/g5/G5D_TIMING.md` and this document. **T**, `063`
(`--verify`, `rc 1`): the 38 problems the exclusion left, all of them the
spec's. **The excluded document was then repaired BY HAND from the tool's own
map** — 18 endpoints across nine citation tokens, every one a
`NEXT_SESSION.md` shift of +27, +36 or +37 — and **T**, `064`:
`relocated 25 citation(s) checked against the base content and the citing
documents`, `O3_CITE_DRIFT VERIFY PASS (0 problem(s))`.

**Four documents outside fix round 1's commit block were touched by this**,
and they are declared rather than absorbed: the migration spec, the two G3
gate docs and the G5D timing doc. Every edit in them is a citation
coordinate and nothing else, which is the same disposition `34452a4` took for
the thirteen documents §18 above describes.

### 18.2 Fix round 2's own drift — 136 repaired mechanically, 6 that must NOT be

**This round added ~350 lines to `sw/chat_seq.py` and 10 to
`ref/seq_chat.py`, and 27 documents cite those two files by line.** The
question is mechanical and was answered mechanically. **T**, `081`:
`REPAIR 162  COLLATERAL 3`, `O3_FIX_PLAN: UNSAFE`. **T**, `082`:
`FIXED 136 citation(s) in 25 document(s)`, with the three
collateral-carrying documents excluded and repaired by hand
(`docs/QWEN35_NEXT_FEASIBILITY.md`, the migration design spec, and this
document). **T**, `088`: `O3_CITE_DRIFT VERIFY FAIL (6 problem(s))`, and
those six are named below because **repairing them would be wrong**.

**A warning that cost this round an hour, recorded so the next one does not
pay it: `--fix` IS NOT IDEMPOTENT.** Run it twice and a citation whose NEW
value happens to be another citation's OLD value is shifted twice.
It was run three times here before that was noticed; every document was
reverted with `git checkout` and the pass redone ONCE. The symptom to look
for is a range whose endpoints have CROSSED — one citation in the migration
spec came out of the third pass naming `sw/chat_seq.py` lines 4587 through
4344 — which a one-line scan over the working tree finds.

**RESTATED 2026-09-14: that warning is now HALF HISTORY, and the half that
is live is a different one.** Two guards have landed since it was written.
The straight twice-in-a-row case was closed first: `--fix` refuses outright
when `--verify` is already clean at the base, because a second pass would
double-shift every citation the first renumbered. The MIXED-tree case — some
documents repaired by hand in post-fix coordinates while one is still stale,
so `--verify` is dirty because of the stale one and the guard stands
aside — was closed by the tool chore `8f0c5f6`, which lifts `--plan`'s split
into `--fix` so that **a COLLATERAL set NOT CLEARED by `--allow-collateral`
refuses the write** (rc 2), naming each rewrite that would move an
already-correct citation. **The escape is per citation and it is the same
chore's**: `evidence/qwen9b/o3/o3_cite_drift.py:1343`, `_allowed, _coll, _unmatched = split_allowed(_per_doc,`,
runs BEFORE the refusal, so `--allow-collateral <doc|path:NNN>` clears a
token the operator has CHECKED, the write proceeds, and **every cleared
rewrite is NAMED in the log** —
`evidence/qwen9b/o3/111_allow_collateral_live.log:23` is one such
`ALLOWED COLLATERAL` line. The refusal itself, firing on the tool's own
fixtures, is `evidence/qwen9b/o3/115_fixtures_GREEN.log:52`:
`O3_CITE_DRIFT FIX REFUSED — 1 rewrite(s) would move a citation that is ALREADY correct`.

**The citation this paragraph first gave was the WRONG one (collection-round
review M-1), and the correction is worth keeping.** It named
`evidence/qwen9b/g6/114_cite_drift_fix3_verify.log:46`, which prints
`O3_FIX_PLAN: UNSAFE` — the **`--plan` DRY RUN's** diagnostic
(`evidence/qwen9b/o3/o3_cite_drift.py:1039`), from `114`'s SECOND stanza,
which is a `--plan` and not a `--fix`. `114` also ran at tree `4e6e09e`,
which is an **ANCESTOR of `8f0c5f6`**, so the `--fix` guard did not exist
when it ran and could not have fired there. That line is the diagnostic the
guard was BUILT FROM, and it is kept here as that and nothing more.

**So `--fix` can no longer silently double-shift a document.** What remains
true, and is why the paragraph above is kept rather than deleted: the tool
protects the tree it can see, the operator still has to run the passes in
the right order, and a crossed range is still the symptom to scan for when
one gets past a guard.

**The six residuals, and why each one stays.**

| # | residual | why it stays |
|---|---|---|
| 1 | `HALF-MAPPED sw/chat_seq.py:236-288` in `evidence/qwen9b/g3/G3_1_ISA.md` | that row is a RECORD of a citation already repaired in a previous round — "claimed to be `SeqLock` … REPAIRED (round 2) → `sw/chat_seq.py:367-386`". The old coordinates are the point of the row |
| 2 | `UNRESOLVED sw/chat_seq.py:236`, same document | the other endpoint of the same record |
| 3-7 | `UNRESOLVED ref/seq_chat.py:168`, `sw/chat_seq.py:239`, `sw/chat_seq.py:240`, `sw/chat_seq.py:533`, `sw/chat_seq.py:535`, all in **this** document's §20 | these are the FIVE LINES THIS ROUND REWROTE — `T_MAX` in both files, `POSBLOB_BYTES`, and the two flat `TEMPLATE4_*` constants. The tool cannot map a line whose content no longer exists; §20.1, §20.2 A and §20.2 E now name the replacements (`ref/seq_chat.py:178`, `sw/chat_seq.py:251-252`, `sw/chat_seq.py:567-578`) BY HAND, and §20.6 says what replaced what |

**Six problems, seven residual tokens, a reason for each, and none of them
a stale citation left unexamined** — which is the same standard §18 set for
the 8 it repaired. The two counts differ because `088` prints **seven** `!`
lines while reporting `FAIL (6 problem(s))`: the HALF-MAPPED range and its
UNRESOLVED endpoint (rows 1 and 2) are ONE problem to the tool. The row
above was labelled "3-6" over five tokens for the same reason and is now
"3-7" (round-3 review m9).

**The full declaration of what fix round 2's drift pass touched outside
its commit block (round-3 review m10).** The fix report's list was short of
the tree. The complete set is: `docs/ARCHITECTURE.md`, `docs/SEQ_ISA.md`,
`docs/QWEN35_NEXT_FEASIBILITY.md`, four plan/spec documents, **nine** earlier
gate documents (not six — the list omitted `evidence/qwen9b/o3/BOARD_LOCK.md`,
`evidence/qwen9b/s3/S3_CHAIN.md` and `evidence/qwen9b/g5/G5D_TIMING.md`),
`evidence/qwen2b/**`, `evidence/qwen_next/**`, `ref/gen_layer_script.py`,
`ref/load_qwen35.py`, `ref/scripts/regen_gate.sh`, and — the one the list
named nowhere, because it is a SCRIPT and not a document —
`evidence/qwen9b/o3/o3_cite_drift.py`. All 27 are digit-only: the reviewer
checked every one mechanically (`git diff -w -U0`, each `-`/`+` pair compared
with every digit replaced), not a sample. The substance was fine; the
declaration was not.

**And what the pass did to the drift tool's own docstring (round-3 review
m11).** `evidence/qwen9b/o3/o3_cite_drift.py:32` carries an ILLUSTRATIVE
EXAMPLE of the bug the tool describes — "a citation LIST joined by slashes
has its FIRST element rewritten and the rest left behind",
`ref/seq_chat.py:950/936/1213/1214/1215`. The pass rewrote its first element
to `945`, making the example an instance of itself and no longer an
illustration. **Fix round 3 restores it** and marks the block so the tool
skips its own docstring examples; that is a drift-only repair outside this
round's commit block and is declared here.

**And the drift of THIS round's own doc edits** — `docs/USAGE.md` and
`NEXT_SESSION.md` are edited here too, so they get their own pass with
`--edited docs/USAGE.md,NEXT_SESSION.md`, separately, because re-running the
`sw/chat_seq.py` pass would double-shift what `082` already fixed. **T**,
`087`: `O3_FIX_PLAN: SAFE`, then `FIXED 36 citation(s) in 10 document(s)`;
**T**, `088` [2]: `O3_CITE_DRIFT VERIFY PASS (0 problem(s))` on that pass,
with no residual at all.

### 18.3 Fix round 3's own drift — 113 + 25 repaired, 13 residual tokens, all named

**What moved.** `sw/chat_seq.py` gained 159 lines (240 inserted / 81
deleted), so every citation below `VERIFY_HOST_S_PER_STEP` at
`sw/chat_seq.py:253` shifted
by four or more. **`ref/seq_chat.py` did NOT move**: the `T_MAX` block was
rewritten to the same eleven lines on purpose, so `T_MAX` is still at
`ref/seq_chat.py:178`
and the file is 11/11 — the only tokens affected there are the two whose
CONTENT changed. `docs/USAGE.md` is line-neutral too (6/6);
`NEXT_SESSION.md` gained 30.

**The code pass.** **T**, `111` (`--plan`, base `47e07cd`):
`REPAIR 118  COLLATERAL 9`, `O3_FIX_PLAN: UNSAFE`. **T**, `112`: the same
plan with three documents excluded — `REPAIR 86  COLLATERAL 8` — then
`--fix` ONCE: `FIXED 113 citation(s) in 14 document(s)`, one half-range left
alone. Every one of the 60 changed line pairs is **digit-only**, checked
mechanically.

**The three exclusions, and why each.**

| excluded | why |
|---|---|
| `evidence/qwen9b/g6/RD9_GATE.md` | written in post-fix coordinates, and already repaired BY HAND from the base→work map — the same disposition `082` took. Its one COLLATERAL token is a deliberate record (below) |
| `evidence/qwen9b/g6/g6_longctx_lockstep.py` | written this round, in this tree's coordinates |
| `evidence/qwen9b/o3/o3_cite_drift.py` | its docstring's ILLUSTRATIVE example of the citation-list defect, restored this round (m11). The docstring now says to exclude the file |

**The other 8 COLLATERAL tokens were rewritten ON PURPOSE, and the check is
in the log.** For each one the BASE line's content is byte-identical to the
WORK line the map sends it to — `1587→1591`, `1589→1593`, `1583→1587`,
`1584→1588`, `1593→1597`, `1647→1651`, and
`evidence/qwen9b/g3/G3_1_ISA.md`'s `236-300 →
236-304` whose start did not move. They are the tool's "relocated onto
another citation's old number" false alarm: the document names the OLD line
and the rewrite IS the repair. The one real collateral is RD9_GATE.md's, and
that document is excluded.

**The doc class** (citations INTO the documents this round edited). **T**,
`115`: `--plan` **SAFE** (`REPAIR 19  COLLATERAL 0`, RD9_GATE.md excluded),
`--fix` once → `FIXED 25 citation(s) in 4 document(s)`, `--verify`
**FAIL 1** — and that one is a residual, not a miss: `docs/USAGE.md:244`
cited by `evidence/qwen9b/o3/BOARD_LOCK.md:648` is still the `--verify` row
(USAGE is line-neutral); the tool cannot map it because this round rewrote
that row's CONTENT (m4), and `evidence/qwen9b/o3/BOARD_LOCK.md:648` is
itself a before/after
RECORD table.

**The gate doc's own three, by hand.** `docs/HISTORY.md:456-457` →
`docs/HISTORY.md:703-704` (the same "scanner legacy-list hard-error" line);
`sw/chat_seq.py:363-382` → `:367-386` in §18.2's residual row, because that
half of the row quotes `evidence/qwen9b/g3/G3_1_ISA.md`'s **repaired**
pointer, which `112`
just moved; and the bare continuation the B row carried, `2767` →
`sw/chat_seq.py:3091`, in §8.3's
B row, which the hand map's regex had missed and the tool's `CONT` form
caught.

> **RENUMBERED 2026-09-14 (Task 16, G7).** The first pair above was written
> by **fix round 3** — `3943ae0`, *"docs(G6): §18.3 — fix round 3's drift, its
> 13 residuals, and the run that was wrong"* — which is the round **this very
> subsection** is about, and at `f9828f2` it read **bare** — `NEXT_SESSION.md`
> lines 416-417 → lines 448-449, written out of citation form here because
> they are a QUOTATION of what this document used to say, not a live pointer.
> **It was not sha-pinned, and it could not have been** — `f9828f2` did not
> exist when fix round 3 wrote it. The sha-pinned form
> `f9828f2:NEXT_SESSION.md:421-422` is **this note's own new text**, written
> here so the pre-ship coordinates stay quotable; the pair in the body above
> was **RENUMBERED**, not pinned.
>
> The ship rewrote `NEXT_SESSION.md` and moved its whole dated stack —
> `f9828f2:NEXT_SESSION.md:6-731` — **VERBATIM** into
> `docs/HISTORY.md:58-986`, a constant **+40**, so every `NEXT_SESSION.md`
> line this document cited now lives in `docs/HISTORY.md` at `N + 40` and is
> renumbered there. **The lines are the same lines**; only their home
> changed, and the moved block is byte-identical (the diff is empty). The
> same +40 applies to **§18.3's** row 12, **§21.1's** M-5 row, **§21.2's**
> m16 row and §2.1's pointer — §18.2 has no row 12 and §22 has no `m16`, and
> an earlier revision of this note named both wrongly.
>
> **THREE MIS-STATEMENTS IN THIS TASK'S OWN COMMIT MESSAGES, CORRECTED HERE
> BECAUSE HISTORY IS NOT REWRITTEN.** (1) `cc3e357`'s message repeats the two
> errors above — it says the pair is "SHA-PINNED" and puts row 12 in §18.2.
> (2) `6264256`'s message calls `130`'s tree "clean" where the log's own
> header reads `=== tree: cc3e357+dirty`
> (`evidence/qwen9b/o3/130_g7_doc_cites_verify_committed.log:3`); `131` and
> `132`, nine seconds later on the same commit, do read `cc3e357`, so the
> load-bearing GREEN is on a clean tree and only the provenance sentence was
> wrong. (3) `cc3e357` (authored 23:15:05) committed text in this document
> citing logs `130`/`131`/`132`, whose own `=== date:` headers stamp them
> 23:15:14 / 23:15:23 / 23:15:24 — **the document named three logs 9 to 19
> seconds before they existed**, against §0's own rule that a log is cited
> only after its `=== rc:` and `=== end:` exist. Benign here (`126` and `127`
> were the same checks on the pre-commit tree and were already in hand, and
> `6264256` lands the logs immediately after), but it is the campaign's own
> rule and the fix is to land logs in the same commit as the text citing
> them. **This note is the correction of record; no commit was amended.**
>
> Task 16's pass: RED
> `evidence/qwen9b/o3/123_g7_doc_cites_check_RED.log` (49 drifted of 50).
> The tool's own verify on the committed tree is
> `evidence/qwen9b/o3/130_g7_doc_cites_verify_committed.log`, and it NAMES
> this cross-file class as hand work rather than closing it — its line map is
> built per FILE, so a line that leaves one file for another maps to None.
> **The GREEN that does close it** is
> `evidence/qwen9b/o3/131_g7_block_identity_committed.log`, from the harness
> committed beside it, `evidence/qwen9b/o3/g7_block_identity.sh`: one `diff`
> proving the 726-line block byte-identical at +40 — which makes every
> `N → N + 40` repair correct at once — plus a sweep for any surviving live
> `NEXT_SESSION.md:N` token. Its negative control,
> `evidence/qwen9b/o3/132_g7_block_identity_control_committed.log`, is CAUGHT
> at a one-line-off window. Logs `124`-`129` are the pass's working record on
> the pre-commit tree, kept because this campaign does not delete a log.

**The residual tokens, why each stays, and WHICH RUN EACH ROW COMES FROM
(round-4 review m2).** Three runs feed the table below, not one. **T**,
`114` [1] (`--verify` in `088`'s shape, `--doc-base == --base`):
`evidence/qwen9b/g6/114_cite_drift_fix3_verify.log:32`,
`O3_CITE_DRIFT VERIFY FAIL (20 problem(s))` — and every token it names IS
this document's; those are rows 1 through 11. **T**, `114` [2], the doc
class, names one COLLATERAL, `docs/HISTORY.md:330` — row 12. **T**, `115`,
the doc pass itself, carries `docs/USAGE.md:244` — row 13. The earlier
wording, that the 20 were "every one RD9_GATE.md's", was true of `114` [1]
and false of the thirteen-row table it introduced.

**And the three counts — 20, 13, 11 — RECONCILE EXACTLY, and the LOG ALONE
settles it.** The tool's total is
`evidence/qwen9b/o3/o3_cite_drift.py:1395`, `n = len(bad) + len(unresolved) + len(missing)`.
`114` [1] printed **20**, with **4** UNRESOLVED and **0** MISSING surviving,
so `len(bad)` was **16** — and the committed log shows **12** of them.
**Four `bad` lines are missing from the log**, and they can only have been
cut from the TOP, because the tool prints every `bad` line FIRST
(`evidence/qwen9b/o3/o3_cite_drift.py:1367`-1368) and only then `relocated`,
`excluded`, the HALF-MAPPED lines, the UNRESOLVED and MISSING lines, and the
verdict. **That is a conclusion from the committed evidence and nothing
else: the tool's accounting is right to the unit; the log is short.** An
earlier revision of this paragraph called the difference a discrepancy in
`evidence/qwen9b/o3/o3_cite_drift.py` and put it on a follow-on list.
**That claim is WITHDRAWN: there is no defect in the tool and no
follow-on.**

**What cut them — corroboration, with its provenance stated plainly.**
`evidence/qwen9b/g6/114_cite_drift_fix3_verify.log:4` is `=== cmd:  bash /tmp/g6_drift3v2.sh`,
and that script, read on snoke where it still sits, pipes the `--verify`
stanza through a 20-line tail; the log's lines 13 through 32 are exactly
twenty, which is what such a tail leaves. **That script is NOT in this
repository, it is not committed with this finding, and that is the other
half of the finding**: the round ran a gate through a harness in `/tmp`, so
the only in-repo record of how the gate was invoked is one `=== cmd:` line
naming a path that does not survive a reboot. The arithmetic above is
therefore the load-bearing part and the script is the explanation.

**What the truncation costs — stated as a BOUND, because the log does not
determine a number.** How many TOKENS the four cut lines stand for is
undetermined for the same reason the tokens themselves are.
`verify()` has **three** append sites, not two:
`evidence/qwen9b/o3/o3_cite_drift.py:714` appends one line for a
base-content mismatch and then `continue`s, while
`evidence/qwen9b/o3/o3_cite_drift.py:726` and
`evidence/qwen9b/o3/o3_cite_drift.py:729` are independent conditionals, so
one token can produce one line or two. **Four cut lines are therefore two to
four additional tokens, and `114` [1] named 13 to 15 distinct tokens — not
the eleven the committed log shows, and not a provable thirteen.** The table
below names those eleven plus the two from `114` [2] and `115`; **the tokens
the tail removed cannot be recovered from the committed evidence** —
recovering them means re-running `--verify` at tree `4e6e09e` in a worktree,
untruncated, and this round did not do it. **The lesson belongs to the
harness, not the tool: never pipe a gate's output through `tail`, and keep
the harness in the tree beside its log** — which is what
`evidence/qwen9b/run.sh` is for, and every checker run from Task 15-D2
onward is a direct invocation of that wrapper with no pipe.

| # | residual | why it stays |
|---|---|---|
| 1-2 | `sw/chat_seq.py:236-288` and its start endpoint | §18.2's residual row 1 — a RECORD of a citation `evidence/qwen9b/g3/G3_1_ISA.md` still carries. The old coordinates are the point of the row |
| 3-4 | `sw/chat_seq.py:533`, `:535` | §18.2's residual row 3-7 — round 2's own residuals, quoted as such |
| 5 | `ref/seq_chat.py:168` | the same row: the `T_MAX` comment line round 2 rewrote |
| 6-7 | `sw/chat_seq.py:2559`, `:4895` | §19.1's table of the migration spec's eight QUOTE failures. Those are the SPEC's coordinates and `050`'s measurement of where they resolved — a record of a log, carrying `<!--cites:noquote-->` |
| 8-10 | `ref/seq_chat.py:178`, `sw/chat_seq.py:251` and the range that ends at `sw/chat_seq.py:252` | **still correct**, and unmappable for exactly that reason: this round rewrote those lines' CONTENT while keeping them at the same number (`T_MAX` and `POSBLOB_BYTES`, line-neutral by design) |
| 11 | `sw/chat_seq.py:2965` | repaired BY HAND to `:2971` (`def check_pos_mode`, whose signature gained `cap=`); the tool reports the base line as rewritten and cannot see the repair |
| 12 | `docs/HISTORY.md:330` | §21's M-5 row QUOTES the round-2 review's finding, which names the line as it stood then |
| 13 | `docs/USAGE.md:244` | the doc-class residual above |

**Thirteen residual tokens, thirteen reasons, and none of them a stale
citation left unexamined.** Every repaired citation was checked forward the
way §18.2's were: base content located in the new file, and the new number
is where it landed.

**And the run that was wrong.** **T**, `113` is a MIS-INVOCATION, committed
rather than deleted: it ran `--verify` with `--doc-base` at the POST-fix
commit, so the sweep read the already-repaired numbers and mapped them a
second time — `FAIL 186`, every one an artefact of the invocation and not of
the tree. `088`'s shape is `--doc-base == --base`, and `114` is that run.
It is the same class of mistake §18.2 records for `--fix`, made on the
verify side, and it is written down for the same reason.

---

## 19. `spec_cites` — and what running it on the BASE tree found

`evidence/qwen_next/spec_cites.py` is the campaign's citation gate, and the
plan's global constraints run it LAST, on the committed tree. Two things had
to happen here.

**The PENDING prune.** `evidence/qwen_next/spec_cites.py:197` carried
`"evidence/qwen9b/g6/RD9_GATE.md",  # T15` — this document, listed as a path
a future gate creates. It exists now, so it is OUT, for the reason every
removal before it was: **PENDING is checked BEFORE EXIST**, so a stale entry
would let a typo in that path, or a deletion of the file, pass silently on
every document that cites it. That is the one thing PENDING costs, and it is
the S5 lesson applied on the task that created the file rather than a round
later.

**T**, `052_spec_cites_gatedoc.log` — this document, gated the way
`evidence/qwen9b/g5/189_t14b_fix2_spec_cites.log` gated G5D's:
**`SPEC CITES: PASS`**, `160 exist, 33 range, 1 quote, 9 noquote, FAIL 0`.
**`052` covers the revision that existed on 2026-09-09 at 21:2x**, not this
one — fix round 1 has since added seven sections. §19.2 is the run that covers
the text you are reading, and it is the same rule §17 had to be corrected for:
an instrument certifies the revision it ran on and no other.

**`048` and `051` are the attempts before it and they are kept, because they
failed on THIS document and the failures were real.** `048`: `FAIL 34`, and
every one of them
mine: 22 `EXIST` misses where a filename was cited bare as shorthand — the
gate doc said G5D_TIMING.md where the path is
`evidence/qwen9b/g5/G5D_TIMING.md`, and run.sh where it is
`evidence/qwen9b/run.sh`, and ten more like them — one `AMBIG` where a bare
line-range continuation sat on a line naming two files, and **eleven
`QUOTE` failures
caused by the two tables below and in §18** — which quote a source span in
order to talk ABOUT it, and which the tool therefore checked as if the
document were asserting the span lives at the cited line. Every bare name is
now a full path, the continuation is written out, and the nine rows that
quote-to-discuss carry `<!--cites:noquote-->`, which is the exemption the
tool provides for exactly that. `051` is the same run after the first sweep:
`FAIL 4`, three more bare names and one range continuation that had
re-attached itself to `evidence/qwen9b/run.sh` when the line it sat on
changed — the AMBIG hazard the tool's docstring warns about, arriving in the
sentence written to describe it. **A gate document that cites by name has to
pass the citation gate itself**, and this one did not until it was fixed
twice.

**AND THE PAIR IN SCOPE WAS ALREADY FAILING BEFORE THIS TASK TOUCHED IT.**
`spec_cites.py`'s own header names two documents as IN SCOPE for the 9B
campaign — the migration spec and the migration plan — and this task edited
the spec (§18's hand repair). So it was run on the pair, and the number is
not what a reader would assume from `5a08f0b`'s commit subject ("spec_cites
LAST, on the committed tree — FAIL 0"): **that run gated `evidence/qwen9b/g5/G5D_TIMING.md`
alone** (`189…`: 284 exist, 20 range, 3 quote, FAIL 0), not the pair.

| tree | run | verdict | EXIST | QUOTE |
|---|---|---|---|---|
| **base `5a08f0b`**, in a detached worktree | `evidence/qwen9b/g6/050_spec_cites_pair_base.log` | **`FAIL 31`** | 23 | 8 |
| this task's tree | `evidence/qwen9b/g6/049_spec_cites_pair.log` | **`FAIL 8`** | 0 | 8 |

**THE 31 → 8 IS A MEASUREMENT ARTIFACT, AND THIS DOCUMENT WITHDRAWS THE
CREDIT.** An earlier revision of this section said "This task took the pair
from 31 failures to 8, and all 23 that closed were RANGE failures repaired by
§18's drift pass". That is wrong twice over, and review round 1 caught it.

**Where the 23 went.** `050` ran on the base tree **in a detached worktree**
(`/tmp/g6_base_check`). Its 31 failures are **8 QUOTE + 23 EXIST**, and every
one of the 23 EXIST is `.superpowers/sdd/**/progress.md does not exist` (×22)
or `tb/scripts_scratch/d/rtl_fix/seq_movers.sv does not exist` (×1).
**Neither path can exist in any fresh worktree**: `git ls-files .superpowers/`
returns nothing (the SDD tree is untracked; `.superpowers/sdd/.gitignore`
ignores everything under it, and `evidence/qwen9b/o3/BOARD_LOCK.md:11` says of
that tree `(**LOCAL-ONLY**, gitignored — a fresh clone will not have it).`),
and `tb/scripts_scratch/` is named at `.gitignore:14`. So
those 23 are an artifact of **where `050` ran**, not of the base tree's
citations.

**Like-for-like, the pair was at FAIL 8 before this task and FAIL 8 after
it.** The eight QUOTE lines in `049` are **byte-identical** to eight of the
31 in `050` — `diff` of the two `QUOTE` sets is empty. **Nothing closed.**

**And the parenthetical did not support the sentence either.** `552 range` →
`569 range` counts CHECKS PERFORMED, not failures repaired: `050` reports
`1149 exist, 552 range, 24 quote | pending 2 | retired 18 | noquote 98 | FAIL 31`
and `049` reports
`1151 exist, 569 range, 24 quote | pending 0 | retired 18 | noquote 98 | FAIL 8`.
The `pending 2 → 0` is §19's PENDING prune; the range delta is more citations
becoming range-checkable, which is a consequence of §18's drift pass and not
a failure count.

**What this task DID contribute here is the measurement**: that the eight are
pre-existing was not known before, and `050` is what proves it.

**The residual 8 are QUOTE failures, all PRE-EXISTING, and all in the spec.**
Each is a backticked source span that still exists in the named file but has
drifted more than the tool's six-line window from the line the spec cites —
by hundreds of lines, in files this task did not edit:

| spec line | quotation | cited | actually at |
|---|---|---|---|
| 216 | `HEAD_LOGIT_EXP0 = head_logit_exp0()…` | `sw/chat_seq.py:349` | 344 |  <!--cites:noquote-->
| 219 | `want_exp0 = head_logit_exp0(self.head.spec.rs_f)` | `sw/chat_seq.py:2559` | 2377 |  <!--cites:noquote-->
| 222 | `head_logit_exp0(7) == HEAD_LOGIT_EXP0 + 1` | `sw/chat_seq.py:4895` | 4462 |  <!--cites:noquote-->
| 923 | `M.dnst(h, QNS, KN, v_src, …)` | `ref/gen_layer_script.py:1491` | 2019 |  <!--cites:noquote-->
| 944 | `for h in range(LR.LNH):` | `ref/gen_layer_script.py:1474` | 2002 |  <!--cites:noquote-->
| 950 | `decay_base = GD + LR.LNH` | `ref/gen_layer_script.py:151` | 161 |  <!--cites:noquote-->
| 1433 | `KVH_MAX = _KVH - 1` | `ref/gen_layer_script.py:799` | **1075** |  <!--cites:noquote-->
| 2558 | `plan_weights(man, wdir)` | `sw/tok_meter.py:274` + 3 more | 309 / 330 |  <!--cites:noquote-->

(The `1433` row said "— (does not resolve by search)" in an earlier revision.
It does resolve: `KVH_MAX = _KVH - 1` is at `ref/gen_layer_script.py:1075`.
The spacing in the source differs from the spec's quotation, which the tool
normalises and a literal `grep` does not — so all eight are ordinary
renumberings, and none of them is a citation of something that has gone.)

**They are NOT repaired here, and the reason is stated rather than left as an
omission.** `sw/chat_seq.py` is net **+0** lines in this task and
`ref/gen_layer_script.py` and `sw/tok_meter.py` were not touched at all, so
none of these drifts is this gate's doing — `050` proves that on the base
tree. Renumbering eight quotations in a spec whose subject is not this task
is a change made without the context that produced them, at the end of a long
board session.

### 19.1 FAIL 8 is an EXPLICIT, LEDGERED EXCEPTION — not an improvement

The campaign's rule is **FAIL 0** on the checked set;
`evidence/qwen_next/spec_cites.py:62` names the migration spec and the
migration plan as in scope "before every commit that touches them", and this
task DID edit the spec (§18's hand repair). **So the eight cannot be carried
as a credit and are not carried silently.** The controller's ruling
(2026-09-09) is on the record: `spec_cites` **FAIL 8 on the Task 15 pair is
an EXPLICIT EXCEPTION** — pre-existing QUOTE drift in files this task did not
change or changed line-neutrally — **deferred to the pre-ship doc chore**,
which is the round that owns that spec.

**What that costs, stated.** `spec_cites --selftest` cannot pass while it
stands: **T**, `059`, `rc 1`, fix round 1 — its six negative controls all
report `CAUGHT` (`line past EOF`, `nonexistent path`,
`quotation moved away from its cite`, `fabricated quotation`,
`orphan continuation (no file on the line)`,
`ambiguous continuation (two files on the line)`), and it then fails on its
own POSITIVE control, `positive control [unperturbed document]:` … `FAIL 8`,
with `*** the unperturbed document does not pass ***`. **The eight it trips
on are the same eight.** So `059` is simultaneously the negative-control run
the plan's global constraint asks for after an edit to the tool (the PENDING
prune, M-8) — every control fires, `pending 0`, the prune broke nothing — and
the price of the exception, in the tool's own words. **`evidence/qwen_next/spec_cites.py`
needs no fix**, and none was made.

**The measurement is this task's contribution here: the pair is at 8, it was
at 8, and the eight are enumerated above with their real line numbers so the
round that opens that spec can close them in minutes.**

### 19.2 The closing run — what it covers, and what it reports

Fix round 1's LAST action is one `spec_cites` run over **four** documents —
this one, `NEXT_SESSION.md`, and the in-scope pair — on the committed tree, in
its own commit, with its log committed alone and cited by nothing. Its shape
is fixed in advance by everything above, and it is stated here so the number
is not a surprise:

* **this document: 0 failures.** It was taken there by hand during fix round 1
  the same way `048`/`051` took the first revision there — one Task-14-A
  census file named without its directory, one orphaned bare line-range
  continuation, and one quote-to-discuss span that resolved against no cited
  file. All three were written out in full.
* **`NEXT_SESSION.md`: 0 failures.** **Seven** shorthand sites were
  repaired here, LINE-NEUTRALLY, so no citation moved a second time: four
  references to this gate doc, one to G4a's replay doc, and two to `sw/`
  scripts named without their directory. This bullet used to add that the
  file "had **6** before this round touched it" — **that number is on no
  log** (`spec_cites` covered `NEXT_SESSION.md` only in `067` and `070`,
  both AFTER the repair), and its own breakdown counted seven. Re-review
  round 2, I-D: how many the gate would have failed on before the repair is
  **not on the record**, and the claim is withdrawn rather than restated.
* **the migration plan: 0 failures.**
* **the migration spec: 8**, the ledgered exception, byte-identical to
  `049`'s.

**Total FAIL 8, every one of them the spec's, and the campaign's FAIL-0 rule
is met on every document this task actually owns.** `067` is the run of that
command on the tree of `386f600`; this section was written after it, so the
covering run is the one committed last.

### 19.3 Fix round 2's closing run — a DIFFERENT checked set, and it is FAIL 0

**The set moved, on purpose.** Fix round 1 gated this document,
`NEXT_SESSION.md` and the in-scope pair (the migration spec and plan). Fix
round 2 edits `docs/USAGE.md` as well and does NOT edit the spec or the
plan, so its closing run gates **this document, `docs/USAGE.md` and
`NEXT_SESSION.md`** — the three documents this round owns — and the
migration spec's ledgered **FAIL 8** is out of scope for it, unchanged and
still deferred to the pre-ship doc chore (§19.1).

**On the checked set, fix round 2 reports `FAIL 0`.** Getting there took
work on `docs/USAGE.md`, which **no `spec_cites` run had ever covered**: it
carried **25 `EXIST` misses** (twelve filenames cited bare — serve.py,
ddr_test.py, program_fpga.sh and nine more, written without their directory —
where the checker resolves
from the repo root) and **4 `QUOTE`/shorthand failures**, none of them
introduced here. Every bare name is now a full `sw/…` path — **line-neutral,
so nothing moved a second time** — and the four quote-to-discuss spans are
written as prose the checker does not read as a citation. **T**, `095`, the first attempt: `FAIL 5`, all five this round's own —
one bare line-number continuation on a line naming two files, and three
filenames this very section cited without their directory while describing
that class of failure. **T**, `098`, the second: `FAIL 1` — the sentence above, whose own
quotation of the offending continuation WAS one. `104` is the covering run,
committed alone.

### 19.4 Fix round 3's closing run — and every closing run since

**The asymmetry round-4 review m8 names is closed here.** §19.2 records fix
round 1's closing `spec_cites` run and §19.3 fix round 2's; fix round 3's
was recorded only in §1's "come after this document is final" sentence and
in that round's untracked fix report. It is `126_spec_cites_LAST.log`: tree
`d3fa905` clean, committed alone in `5f9afe8`, over the three documents that
round owned — this one, `NEXT_SESSION.md` and `docs/USAGE.md` —
`checked: 578 exist, 157 range, 9 quote  |  pending 0  |  retired 0  |  noquote 10  |  FAIL 0`,
`SPEC CITES: PASS`. `121` is that round's first attempt (`FAIL 23`, all of
it the round's own new prose), and `122` and `125` are the intermediate
covering runs on the way to it.

**The rounds after fix round 3, for completeness, so this section never goes
stale in the same way again.** Task 15-D's closing runs are `165`
(`FAIL 7`), `166` (`FAIL 1`) and `167`, the covering `SPEC CITES: PASS`
(§22.13). Task 15-D2/D3's is `172_15d3_spec_cites_LAST.log`, tree
`af61bf9`, `checked: 611 exist, 225 range, 47 quote  |  pending 0  |  retired 0  |  noquote 10  |  FAIL 0`.
**This collection round's is committed ALONE and LAST, on the committed
tree, and it is the run that certifies the text you are reading** — every
round's log certifies the revision it ran on and no other, which is the rule
§17 and §19 were both corrected for.

---

## 20. THE 9B CHAT PATH — SCOPE, measured rather than estimated

> **BUILT, in fix round 2 (2026-09-09).** This section is kept as WRITTEN,
> because a scope that is edited after the fact stops being evidence of what
> was predicted. §20.6 below records what the round actually did and — more
> usefully — **what differed from this scope**. The short version: §20.1 to
> §20.4 held, item by item; §20.3's REFERENCE BUDGET was wrong by a factor
> of **21-25**, and that is the one thing that changed the round's shape.

§8 says chat is BLOCKED. This section says what the block IS, so the round
that owns it can plan from evidence instead of from the word "task-sized".
Everything below is `057`, `056` and `060`, plus the source those runs
exercise. **No tool was edited in fix round 1.** The same text is delivered
separately to the controller as
`.superpowers/sdd/2026-09-04-qwen35-9b-state-spill/task-15-chat-scope.md`.

### 20.1 What `sw/chat_seq.py` does today — TWO paths, not one

The tool has two completely different template paths, chosen by `--nch`, and
§8's first revision described only the first of them.

**`--nch 1` — THE FROZEN PATH (shipped, and 2B/0.8B by construction).**
`sw/chat_seq.ChatSession.__init__` calls `frozen_geometry()` and hands the
prefix straight to `ref/seq_chat.TurnCompiler` with `verify_sha=True`. Every
boundary is a constant pinned to one artifact,
`tb/scripts/w4/model_v2_s1.e` (`sw/chat_seq.py:202`, `ref/seq_chat.py:125`):

| constant | value | where |
|---|---|---|
| `TEMPLATE_NREC` | **60,495** records | `sw/chat_seq.py:214`, `ref/seq_chat.py:128` |
| `TEMPLATE_ISA_VERSION` | **1** — a SEQ_ISA **v1.7** artifact; this tree emits and decodes v2.0 | `sw/chat_seq.py:213` |
| `TEMPLATE_SHA256` | `a69864d25b6b129a…` | `ref/seq_chat.py:129` |
| `SEQDATA_SHA256` | `13bc65821b18194b…` | `ref/seq_chat.py:131` |
| `CONST_BYTES` | **998,144** — "PINNED: it is the byte length of the committed 0.8B const region, gated by TEMPLATE_SHA256, not a geometry expression" | `ref/seq_chat.py:161` |
| `R_PREAMBLE` / `R_BODY_FULL` / `R_BODY_LITE` / `R_TCNT` / `R_HALT` | (0, 1524) / (1526, 16266) / (1526, 15532) / 45751 / 60494 | `ref/seq_chat.py:135-143` |
| `POS_LDC_REC_OFFSETS` | six RECORD indices into one body — the byte offsets are POS_LDC_BYTE_OFFSETS, o*REC + 8 per record (`ref/seq_chat.py:187`), and the name says so (re-review round 2, M-6) | `ref/seq_chat.py:186` |
| `T_MAX` | **512** at the time of writing; fix round 2 moved it to **4,096** for every selection and fix round 3 made it PER selection — 4,096 at 9B, 512 on the frozen path (§8.3a, §20.6 E) | `ref/seq_chat.py:178`, `sw/chat_seq.py:251` |

`ref/seq_chat.Templates` (`ref/seq_chat.py:346`) checks all of that at load;
`ref/seq_chat.TurnCompiler` (`ref/seq_chat.py:518`) splices the three DDR
images out of those slices. **`model_9b_s1.e4` has 158,536 records**, so none
of the indices means anything against it — which is §8's block, correctly
stated, for this path.

**`--nch 4` — THE DERIVED PATH (and it already works at 9B).**
`sw/chat_seq.ChatSession.__init__` instead calls
`sw/chat_seq.derive_geometry` (`sw/chat_seq.py:586`), which reads all nine
boundaries **out of the stream** — HALT is the last record, the two seeds are
the CSRWRs before body 0, the lite cut is found from the head image's own
MVGO `WBASE`s, the const-blob geometry comes from the position LDCs' own
addresses — and then executes `ref/seq_chat.py` a second time into a private
namespace with those values substituted (`sw/chat_seq.seq_chat_for`,
`sw/chat_seq.py:952`).

**T**, `057` [2]: offered `model_9b_s1.e4`, that derivation SUCCEEDS and
returns the 9B geometry — `TEMPLATE_NREC 158536`, `R_PREAMBLE (0, 37)`,
`R_BODY_FULL (39, 39661)`, `R_BODY_LITE (39, 38893)`, `R_TCNT 118910`,
`R_HALT 158535`, `CONST_BYTES 551424`, `POS_STRIDE 2048`, eight
`POS_LDC_REC_OFFSETS`, `X8_WORD 8192` / `X8_LEN 4096`. **T**, `056` [6]: with
`--any-template` the compiler then builds all three images, relocates 324
LDC+EMB records, loads the 9B tokenizer and renders the templated turn.

**So "there is no code path that derives a 9B `TurnCompiler`" was wrong. The
path exists, it runs, and it is gated shut** — which is a different and much
cheaper problem.

### 20.2 What a 9B chat path needs — by function, with what each costs

| # | what changes | where | why | size |
|---|---|---|---|---|
| **A** | re-pin the 4-chan template gate to a GATED 9B artifact | `sw/chat_seq.py:567-578` (`TEMPLATE4_BY_MODEL`, which replaced the two flat constants `TEMPLATE4_PREFIX` / `TEMPLATE4_SHA256` this row named) | `056` [4]: this is the refusal a correctly configured session hits. The gate is deliberate — its message says "re-run the seq_model 4-chan gate before re-pinning" | **a decision + a gate run**, not an edit |
| **B** | give the verifier a state region | `sw/chat_seq.py:3482` (`self.mach = self.SM._fresh_mach()`) and `sw/chat_seq.py:3514` (`ex = self.SM.SeqExec(recs, self.blob, self.W, emb=self.emb,`) | `056` [6]'s actual failure — the verifier refuses SLD/SST because it was handed no state region. `ref/seq_model.SeqExec` takes a `region=` argument (`ref/seq_model.py:608`); `chat_seq`'s verifier never passes one, because it predates S3's DDR spill | **small** — build a `StateRegion` from the manifest's `state` plan and pass it, per launch |
| **C** | upload the state region and program `SB_DN`/`SB_KV`/`SB_CV` in the chat session | `sw/chat_seq.ChatSession.bring_up` / `open_board` | the board half of B. `sw/seq_run.upload_state` and `sw/seq_run.seq_check_state_bases` already exist and are proven on hardware (§6); the chat session does not call them, and without them the first SLD/SST halts `E_DMA_BASE` | **small** — reuse `sw/seq_run.py`'s functions |
| **D** | the DN/conv reset between contexts | `sw/chat_seq.py` selftest case `[21]` already exists (`S3: conv-image witnesses + the session-reset DN memset`) | a chat context reset must re-zero DN and restore the conv taps, which for a spilled state means DDR writes, not a CSR | **already scaffolded**, needs the board path |
| **E** | `T_MAX` and the position blob | `ref/seq_chat.py:178`, `sw/chat_seq.py:251-252`, and the `--max-ctx` guard at `sw/chat_seq.py:6524` | see §20.3 | **one constant + one guard**, and it is NOT the expensive part |
| **F** | the `--nch 1` frozen path | `ref/seq_chat.py:125-167` and `:180-193` — the slice indices, the pins and the stride, i.e. everything in that block EXCEPT `T_MAX` at `:178`, which E does change (round-3 review I-2: this row said `:125-186` and "no change" over a line E moves) | leave it alone. It is the 0.8B/2B path, gated by sha, and re-pinning it would break the frozen bitstreams' chat | **no change to the pins**; `T_MAX` is E's and is per selection so the frozen footprint is byte-identical (§8.3a) |

**Nothing in this list is a new compiler.** The compiler is `derive_geometry`
+ `seq_chat_for` + `TurnCompiler`, and it already produces 9B images.

### 20.3 Does the EXISTING emission suffice? — YES for chat, NO for long context

**For chat: YES.** The three DDR images a session needs are spliced out of a
gated `.e.seq`, and `tb/scripts/w9/model_9b_s*.e4` are exactly that — emitted
by S4, digest-verified against `evidence/qwen9b/s4/001_emit_9b_s1.log:203`,
and `057` shows `derive_geometry` reading every boundary chat needs out of
one. **The 3.5 h re-emission is NOT on the chat path.**

**The prompt stream is COMPILED, not sliced.** That distinction matters and
is the one thing a reader must not get backwards: `TurnCompiler.build_step`
patches three records at the head of a body image (`R_SEED_TOK`,
`R_SEED_POS`, `R_TCNT`) taken from the 9B artifact's OWN record layout, at
offsets `derive_geometry` read out of that artifact. It does not cut the 2B
stream at 2B indices. Attempt `[6]` at `056` is that compilation running.

**The chat TEMPLATE TEXT is already 9B-correct, with one rung outstanding.**
`sw/chat_seq.ChatTemplate` builds the wrapper ids by hand and NEVER passes
`enable_thinking=True`; `gen_prompt()` emits the closed-empty
`<think>` block explicitly. So the 4B/9B inversion of the
`enable_thinking` default (`docs/QWEN35_NEXT_FEASIBILITY.md:255`) does not
reach it. **T**, `056` [6] under `FABLE5_MODEL=9b`: the 9B tokenizer loads
(`c202236235762e1c871ad0ccb60c8ee5ba337b9a`, 247,587 merges, self-test
reproduces all 4 `gen_model_script` PROMPTS) and the rendered turn is
`[248045, 846, 198, 3710, 369, 279, 6511, 314, 9338, 30, 248046, 198, 248045, 74455, 198, 248068, 271, 248069, 271]`,
identical to the pinned `HF_REF_SINGLE`. **The outstanding rung**: that
constant's provenance is a 2026-08-11 check against HF `apply_chat_template`
on the frozen checkpoint (`sw/chat_seq.py:3328-3329`). **Which one, exactly:**
this row said "the **2B** checkpoint", but the cited comment block's own
reproduction recipe pins `models--Qwen--Qwen3.5-**0.8B**/snapshots/2fc0636…`
(`sw/chat_seq.py:3309`) — re-review round 2, M-2. The outstanding rung (§8.6,
re-verify against the 9B jinja) is unaffected either way. Re-verifying it
against the 9B checkpoint's own jinja is cheap and belongs in the chat round;
it is the plan's Step 5 "verify the template on-device output matches what
Task 5 derived".

**For long context: NO, and this is where the cost is.** Three separate
things, and only the first is a constant:

1. **`T_MAX` 512 → 4,096.** The hardware ceiling is already 4,096
   (`sw/hwmap.STATE_T_MAX`, **T** `057`), and the position blob scales
   linearly: at 9B `POS_STRIDE` is **2,048 B/position**, so `POSBLOB_BYTES`
   goes **1,048,576 B → 8,388,608 B** (**D**, `057`). **8 MiB of DDR is not a
   cost.** The `--max-ctx` guard at `sw/chat_seq.py:6524` moves with it.
2. **`pos_mode` must be `ldc`, not `xrf`.** `XRF_POS_MAX` is
   `((1 << (SF.XRF_BITS - 1)) - 1) // POS_STRIDE`, and at 9B's 2,048 B stride
   that is **63** (**T**, `057`; it is 85 at 2B). XRF[4] is a signed 18-bit
   register and `seq_unit` truncates SILENTLY past it. So the `xrf` position
   mode caps a 9B context at 63 tokens and must be refused, not warned about,
   at 9B.
3. **A long-prompt artifact, and a reference that can run it.** This is the
   expensive item. Every 9B stream in the tree is a **6-step** decode
   (`057`: `R_BODY_FULL (39, 39661)`; the "four bodies" and "`loop_steps` 6"
   this row used to carry as **T** are DERIVED from `TEMPLATE_NREC 158536`
   and `NREC_BODY_FULL 39622`, which `057` does print — it prints neither
   phrase, and `loop_steps` appears in no log in this directory, re-review
   round 2 M-3), so a
   prompt longer than 512 needs either a new emission — the ~3.5 h S4 spent —
   or a chat session that drives >512 launches through the compiled step
   images. **The chat route is the cheaper one and is the reason to do chat
   first**: once B/C land, a long context is 512+ launches of the same
   `lite`/`full` images with a moving `pos`, no new emission at all. What it
   still needs is the REFERENCE side: `ref/seq_model.py` replaying >512 steps
   in numpy, at `evidence/qwen9b/s4/S4_REPLAY.md`'s ~5-7 s of host time per
   step — **≈ 45-60 minutes of host time per 512 steps**, which is the real
   budget line for a lockstep-verified long-context rung.

**The KV traffic the raised ceiling costs is already quantified** (§10.3, **T**
`030`): the per-token KV term rises from 16,842,752 B at T = 512 to
134,742,016 B at T = 4,096 (**D**, ×8.0), on DDR channel 3 alone, taking the
whole per-token state traffic from 70.06 MiB to 182.50 MiB.

### 20.4 The selftests that exist, and which of them need extending

**T**, `060`. `sw/chat_seq.py --selftest` is board-free and takes ~28 s:
**`chat_seq selftest: 364 passed, 0 failed`** under the shipped selection,
across 22 numbered cases — `[1]` template source and slice indices, `[2]`
image assembly against agent A, `[3]` position/const blob, `[4]` the
per-launch patch in both position modes, `[5]` DDR plan and relocation,
`[6]` the context guard, `[7]` residency witnesses, `[8]` the launch protocol
against an offline `seq_unit` model, `[9]`/`[9b]` turn bookkeeping and the
canned schedule, `[10]` tokenizer and stop ids, `[11]` the shared board lock,
`[12]` the chat template's HF id equality, `[13]`-`[16]` sampling and head
verification, `[17]`/`[18]` the S7 layout and the head cache,
`[19]`/`[19c]`/`[20]` the rung-4 nch/FIFO/TOPK work, and `[21]` the S3
conv-image witnesses and session-reset DN memset.

**Under `FABLE5_MODEL=9b` the SAME selftest dies in case `[2]`**, and where it
dies is the map of what to extend. **T**, `060` [2]:

```
seq_chat.ChatSeqError: template check failed: rec 60492 is XOP*   XRF[4:pos] = +XRF[4:pos] +1536,
expected XOP XRF[4] += 2048
```

`ref/seq_chat.Templates._verify` is checking the **frozen 2B artifact**
against the **9B** `POS_STRIDE`. That is the whole shape of the selftest
problem: cases `[1]`-`[4]` are pinned to `tb/scripts/w4/model_v2_s1.e` and
must either stay on the shipped selection or gain a 9B fixture; case `[19]`
(`rung 4 S4: nch sessions, derived geometry, weight placement`) is the one
that already exercises the DERIVED path and is where a 9B geometry case
belongs; and there is **no case at all** for B/C above — a step image whose
SLD/SST run against a state region — which is the test the chat round should
write first, RED, before it touches the board.

### 20.5 The order this should be done in

1. **B + C + a RED selftest case** (state region in the verifier and in the
   session) — board-free, and it is what `056` [6] is asking for.
2. **A**: emit or nominate a gated 9B chat artifact, run the `seq_model`
   4-chan gate on it, re-pin `TEMPLATE4_SHA256`.
3. **The Step-5 chat rungs** on the board: `--verify`, greedy, sampled ×4
   seeds, and the template re-verification against the 9B checkpoint.
4. **E + the long-context rung** last, because it is the only item with an
   hour-scale reference cost and it is cheapest once 1-3 exist.

### 20.6 What fix round 2 BUILT, and what differed from this scope

**The order above was followed.** §20.5's four items map to commits
`1b2cec6` (B + C + D + the RED selftest), `432e6ab` (A), the board rungs
(§8.4-§8.6), and `09ed6d7` (E). §8.3 is the table of what landed and where.

**What held, item by item.**

* §20.1's central claim — **the `--nch 4` path derives a 9B `TurnCompiler`
  and it runs** — held. Nothing in this round wrote a compiler.
* §20.2's five functions were the whole of it. A was a NOMINATION and a
  citation of a gate that already existed (`024`), not an emission; B and C
  were the `region=` argument and two calls to functions `sw/seq_run.py`
  already had; D reused case `[21]`'s shape; E was two constants and a
  refusal.
* §20.3's **"the existing emissions SUFFICE for chat"** held exactly: not one
  byte was re-emitted, and the 3.5 h S4 emission was never on the path.
* §20.4's reading of the selftests held: the new work went into a new case
  `[22]` (B/C/D) and a new case `[23]` (E), the shipped selection's cases
  `[1]`-`[4]` were left alone, and `[21]` was extended rather than replaced.

**What DIFFERED, and it is one thing.**

1. **The reference budget was wrong by 21-25×, and it re-shaped the round.**
   §20.3 costed the reference at "~5-7 s of host time per step" and
   therefore "≈ 45-60 minutes per 512 lockstep-verified steps". That figure
   is the **2B** one `sw/chat_seq.py` prints in its own plan line; nothing
   had measured the 9B one. **T**, `074`: **131.2 s** for a `lite` step and
   **149.3 s** for a `full` one, i.e. **18.7-21.2 h per 512 steps**. §8.7
   says what that cost the long-context rung.
2. **§20.2 A said "a decision + a gate run, not an edit". It was an edit** —
   a small one, and a different shape than predicted: the pin could not
   simply be re-pointed, because the frozen 0.8B/2B `.e4` must keep working
   (scope F). It became a per-`FABLE5_MODEL` table
   (`sw/chat_seq.py:567-578`), which is the same decision with the frozen
   path preserved by construction rather than by care.
3. **§20.2 called `TEMPLATE4_SHA256` the A-blocker and `[6]`'s region the
   B-blocker; both were true, and a THIRD thing had to move that §20 did not
   name**: the conv residency witnesses (§14.1). Without
   `split_witnesses`, every 9B chat session after the first would have begun
   with a 45.8 s, 5.8 GiB re-upload of a healthy pack. It is not a chat bug
   — §14.1 had already measured it — but the chat path is where it would
   have been paid, every session.
4. **§20.3's `pos_mode` item asked for a refusal and got two.**
   `ref/seq_model.SeqExec` shares the XRF blind spot, so a refusal only in
   `resolve_pos_mode` would leave `--verify` able to certify a context the
   silicon truncates. `SeqModelVerifier.check_pos_mode` is the second one.

**And what fix round 3 corrected in this account (§8.3a).** Two of the
sentences above were wrong about their own change and are struck here rather
than left standing:

5. ~~"E was two constants and a refusal"~~ (item 2 of "what held"). E was two
   constants, a refusal, **and an 8× growth of the FROZEN `--nch 1` path's
   uploaded footprint** — position pool 786,432 → 6,291,456 B, const blob
   1,784,576 → 7,289,600 B — because `T_MAX` is shared by every selection.
   That growth is **covered by the selftest only** (`--nch` defaults to 1,
   so the suite's primary session IS the frozen path, and case `[5]` asserts
   `data_base + len(const_blob) <= HW.W_BASE` at the new size) and **cannot
   be covered on hardware**: the 2B pack is gone and the 2B stream halts
   `err_op` on build_041 (§16.7). Fix round 3 made `T_MAX` per selection so
   the frozen footprint is `4662b06`'s byte for byte (`107`/`109`).
6. ~~"the refusal is at 9B"~~. It was keyed on the MODEL TAG at both sites,
   and the verifier's copy had no geometry check at all — so it would have
   certified an `xrf` `--verify` run at any selection not literally `"9b"`,
   whatever the stride. The condition is the geometry now (§8.3a).

---

## 21. FIX ROUND 3 — the two reviews' lists, item by item

Round 3 answers two reviews — the re-review of round 1 (I-A…I-E, M-1…M-9,
doc-only, carried past round 2) and the review of round 2 (I-1, I-2,
m1…m16). The two Importants of each are handled where they belong — I-1 and
I-2 in §8.3a, I-B/I-C/I-D in §1, §4.2 and §19.2. This section is the ledger
for the rest, so that nothing is answered by silence.

### 21.1 Re-review round 2 (I-A…I-E, M-1…M-9)

| # | finding | disposition |
|---|---|---|
| I-A | §16 item 2 still said chat was "blocked on a 9B `TurnCompiler` that does not exist" | **already discharged by fix round 2** — that item was rewritten to `DISCHARGED in fix round 2, §8.2` in `67e47bd`, after the review was written. Round 3 extends it with the long-context lockstep's IN-FLIGHT status |
| I-B | §1's fix-round-1 header claimed a clean tree over five `+dirty` rows | **fixed** — §1: the header no longer says "clean on every row" and `060`-`064` carry the mark |
| I-C | "all 25 **committed** 9B artifacts" — none is committed, and the glob covers 25 of 37 | **fixed** — §4.2 (2): gitignored (`.gitignore:36`), which 25 the glob reaches, and that the other twelve (`rep10/`, `probe/`) were read by the reviewer and are all `nch=4` |
| I-D | §19.2's "`NEXT_SESSION.md` had 6 before this round" is on no log, and its breakdown counts seven | **fixed** — §19.2: the claim is WITHDRAWN, not restated; seven sites repaired line-neutrally, and how many the gate would have failed on before is not on the record |
| I-E | two withdrawn claims still standing in the task's working report | **fixed** — the rung-15 row (the withdrawn FAIL-31→8 credit, and `053` as the last `spec_cites` run) and the SIGHUP section's "launched detached anyway" are struck the way the three corrected in round 2 were, and the rung-15 row now points at `070`. That report lives in the untracked SDD tree, which is why it is named here in prose rather than cited |
| M-1 | §12's watch row pairs the six-run subject with the nine-run spread | **fixed** — 0.0097 % over the six seed-1 runs, 0.0101 % the widest over all nine |
| M-2 | "the 2B checkpoint" over a comment that pins the 0.8B snapshot | **fixed** — §20.1 names the 0.8B snapshot and cites `sw/chat_seq.py:3309` |
| M-3 | the **T** marker over-reaches by "four bodies" and "`loop_steps` 6" | **fixed** — §20.3 marks both as DERIVED from what `057` prints, and records that `loop_steps` appears in no log here |
| M-4 | `sw/chat_seq.py:194` vs `:193` for `TEMPLATE_PREFIX` in two sections | **fixed** — the drift pass moved both, but kept them one apart (`:203` in §8.1, `:202` in §20.1). Both now read `sw/chat_seq.py:202`, which is the assignment; `:203` is its continuation |
| M-5 | `docs/HISTORY.md:330` cited `054`-`067` in a commit made before `065`-`067` existed | **carried, and recorded** — accurate at HEAD, wrong at the moment it was written. The rule it breaks is §1's own; the repair is the discipline, not an edit to a log that is now correct |
| M-6 | `POS_LDC_REC_OFFSETS` called "six **byte** offsets" | **fixed** — §20.1: record indices, with `POS_LDC_BYTE_OFFSETS` (`ref/seq_chat.py:187`) named |
| M-7 | §18.1's heading says 5 documents, its body and the commit subject say four | **fixed** — the heading now reads "4 documents outside the block" |
| M-8 | `054`/`055` print no lock banner | **carried** — the hold is real (`BL.add_lock_args` / `BL.from_args(...).acquire()` in both instruments, sources committed) but the logs carry no positive evidence of it, unlike `002`'s. §15 records the same for this round's two shell-driven rungs. A one-line echo in each instrument is the fix and is not taken here |
| M-9 | `054` §[2]'s control exercises `meta.get("nch", 1)`'s DEFAULT | **fixed** — §4.2 (2) says which of the two it demonstrates |

### 21.2 Review round 3's minors (m1…m16)

| # | finding | disposition |
|---|---|---|
| m1 | the `083` row promises an explanation of the two dead counter reads that no section gives | **fixed** — §8.7 now carries it: both died `FileNotFoundError: /dev/xdma0_user_user`, `rc 1`, so runs A and B have no lane measurement and the counters were never cleared before run A; `084` [1] is the clear that makes `084` [3] a per-session read |
| m2 | §1 labels `083` `rc 0` — that is the wrapper's | **fixed** — the row reads "0 on the wrapper; steps [3] and [6] rc 1" |
| m3 | no RED for a corrupted CONV image — `bring_up_state`'s new refusal was unexercised | **FIXED IN CODE, bounded**: selftest `[22]` now hands `bring_up_state` a mismatching conv witness and asserts the raise, then the same call with every witness matching and asserts it does NOT — `probe_residency` is the seam. The control fires one way only (`109`) |
| m4 | `--verify` prints "~6 s of host time per step", 20× wrong at 9B | **FIXED IN CODE** — `VERIFY_HOST_S_PER_STEP` is per selection (140 at 9B from `074`'s 131.2/149.3, 6 at 0.8B/2B) and is printed in both the banner and `--verify`'s help. `110`:30 shows it: `~140 s of host time per step at FABLE5_MODEL=9b` |
| m5 | `_run`'s docstring says "pos > 85", the 0.8B/2B cap | **FIXED IN CODE** — it cites `SC.XRF_POS_MAX` and names both values |
| m6 | three pre-existing `xrf` selftest sites are model-dependent | **FIXED IN CODE** — they pass `tag="2b", cap=85`, and the geometric refusal removes the abort cause entirely: `ChatSession(_args(pos_mode="xrf", max_ctx=cap+1))` is geometrically sound and no longer raises at any selection |
| m7 | "a two-minute session would lose it too" does not follow from 18 % of range | **fixed** — §14.5: 4.4 % duty ⇒ `L_SDMA_CYC` wraps at ≈ 6.6 min of wall, and the companion bound (≈ 31 % compute duty ⇒ `L_LCYC` at ≈ 55 s ≈ 420 launches) is given |
| m8 | the host bound is called "the cheap fix"; it only detects | **fixed** — §14.5 separates detection (host, immediate) from the durable fix (RTL: a wider counter or a sticky wrap bit), which needs a bitstream and is therefore **post-ship**, on Task 16's list beside the gate-port widening |
| m9 | the residual row is labelled "3-6" over five tokens; `088` prints seven `!` for six problems | **fixed** — §18.2: the row is "3-7" and the section says the tool counts the half-mapped pair once |
| m10 | the fix report's out-of-block declaration is short of the tree | **fixed** — §18.2 carries the complete set, including the nine gate documents and `evidence/qwen9b/o3/o3_cite_drift.py` itself |
| m11 | the drift pass rewrote `evidence/qwen9b/o3/o3_cite_drift.py`'s own illustrative example into an instance of itself | **fixed** — restored and marked so the tool skips its own docstring examples; declared in §18.2 as a drift-only repair outside the block |
| m12 | `077`'s script header says the refusal fires "BEFORE the lock"; it fires inside it | **carried, and recorded here** — it is before the BOARD, which is the claim that matters, and §8.1 states it correctly. The wrong phrasing is in a log's own script header and is repeated in no committed document; a log is not rewritten in place |
| m13 | a `ChatSession` refusal surfaces as a five-frame traceback | **FIXED IN CODE** — the construction is wrapped the way the lock is: `*** {e}` and `exit 4` |
| m14 | `state_region`'s docstring claims the model and the chip start from identical bytes, including KV | **FIXED IN CODE** — it now says DN and the conv images only, that `upload_state` deliberately leaves KV alone, and why the two sides are still equivalent (TCNT is 0, no KV row is read before it is written) |
| m15 | `reset()` re-hashes and re-loads 155 MiB per context reset — 2 × 155 MiB of NFS reads | **MEASURED and carried as a follow-on.** **T**, `109` [6]: `verify_state_image` **0.56 s** + `StateRegion.load` **0.27 s** = **0.84 s** per reset (310 MiB read), repeatable to the hundredth on a second call. Against 131 s/step it is 0.6 % of ONE step, so caching the pristine image is a tidiness fix, not a performance one, and it is not taken here |
| m16 | (a) `079`'s committed JSON names invert the log's `report ->` order; (b) `docs/HISTORY.md:279` implies a 42-row KV region; (c) an unneeded `# noqa: BLE001` | (a) **recorded**: `079_sampled_seed20260909.json` carries `--out …_19523.json` (the SECOND run) and `…_b.json` carries `…_262.json` (the first), so the `_b` suffix inverts the log's order — traceable only through each file's own `argv`, which is why it is written down rather than renamed under a cited log. (b) **fixed** in `NEXT_SESSION.md`. (c) **FIXED IN CODE** |

---

## 22. THE LONG-CONTEXT DIVERGENCE, INVESTIGATED (Task 15-D)

**Section number.** The task brief calls this "§21". §21 was already taken by
fix round 3's review lists, so it is **§22**; nothing was renumbered.

**THE FINDING THIS SECTION INVESTIGATES.** §8.7a's replay finished.
**T**, `106`, 17.08 h, 122.2 s/step, 503 of 526 steps replayed, no board:

```
  step 502 full tok=13      pos=502 ref ->      760  chip -> 760  ==    'The'
  step 503 full tok=760     pos=503 ref ->     3177  chip -> 20438  !! DIVERGENCE   ' city'
  ref ids    [760, 3177]
  chip ids   [760, 20438, 18253, 5134, 421, 279, 3177, 314, 11751, …]
LONGCTX_LOCKSTEP: FAIL at step 503
```

The 502 prefill steps agree, and that agreement carries **no information**:
`083` prefilled `lite`, which has no LM head, so "both sides emit no token"
is what a prefill row says either way (§8.7a). Decode 1 agrees on a real
token. **Decode 2 does not.**

**WHICH SIDE IS WRONG IS NOT ESTABLISHED BY `106`, AND IS NOT ESTABLISHED BY
THIS SECTION EITHER.** The reference has never been run at this prompt length
before; the silicon runs at zero timing margin. What follows is the evidence
that narrows it, and the probe that would settle it.

### 22.1 Step 0 — what the board held, preserved before anything touched it

**T**, `127`, tree `43c1409` clean, rc 0, **not one byte written to DDR**:

| | |
|---|---|
| VERSION | `0xc973c18a` — build_041, **MATCHES** the expected netlist word |
| CALIB | `0xf`, all four channels; MAGIC, layer, matvec0-3 and SEQ IDENTs all OK |
| residency | 1,146 witness blocks → **0 IMAGE missed a witness**. The 24 conv-block misses are §14.1's known non-invariant, and `chat_seq`'s own probe re-takes them after its state upload: every session below printed `1122 … 0 MISS` and then `24 … 0 MISS` |
| region sha256 | `3049c05df09aea642df76bf380180154f8c00c8b243d81b34ae5c82cd3d1e11c` |
| DN alone | `eaa414de679357fc0f908619d36deade404d021b0edbbf0f7e7a06f804f6bd8f` |

The region matches **neither** the artifact's initial `sha256` nor its
`final_sha256`, which is what a board that has run chat sessions holds.
**The 155 MiB region is not committed**: it stays where it is, on the board
at `0x3_8000_0000` (DDR channel 3), and the two hashes above are its record.

**The perishable part.** The KV region is not cleared between sessions, so
rows 500..525 on the board still held the 526-step session's own — the rows
the divergent decode steps read. `127` dumped them (sha256 per 256 B row, the
row's int8 exponent byte, 32 B verbatim) into
`127_15d_kv_rows_pre.json`, committed, before any new session overwrote the
rows beneath them: **26/26 non-zero in all six blocks** (L0/L4/L7 × K,V).

### 22.2 The chip is deterministic AT the divergence — to the last byte of the region

Three independent sessions, `083`'s prompt verbatim, `--ntok 2`
(**T**, `128`, `129`, `130`):

| | run A | run B | run C |
|---|---|---|---|
| ids | `[760, 20438]` | `[760, 20438]` | `[760, 20438]` |
| whole 155 MiB region sha256 | `f1829bfe9c739cb6…` | `f1829bfe9c739cb6…` | `f1829bfe9c739cb6…` |
| DN sub-region sha256 | `e098f93a84ec90e1…` | `e098f93a84ec90e1…` | `e098f93a84ec90e1…` |
| launches | 505 | 505 | 505 |

**Token 2 is 20438 every time**, and the determinism is far stronger than the
token list: **all 162,529,280 B of the state region are bit-identical across
the three runs.** §8.7's three-run determinism was over 24 tokens; this is
over the whole machine state the run leaves behind.

**And it is deterministic ACROSS session lengths too.** **T**, `131`: the
rows the 526-step session left (`127`) against run A's (`128`) — rows **501,
502 and 503 are BYTE-IDENTICAL**, a 24-token session and a 2-token session
writing the same KV at the same positions.

**The lanes.** **T**, `128`/`129`/`130`: `L_SDMA_CYC` **5.758 ms/step** over
505 launches (2,908.0 ms = 16.9 % of the counter's range → a measurement,
§14.5's test), against §8.7's 5.788 on the 527-launch run. `L_LCYC` reads
5,915.0 ms = 11.713 ms/step and **is not a measurement**: §14.5's bound is
≈ 420 launches for this program and this is 505. One wrap gives
(1,478,754,239 + 2³²) / 250 MHz / 505 = **45.73 ms/step** (**D**), beside
§14.5's own 46.01 for the 527-launch run. The wrap is why the bisect runs
below are the ones whose lane numbers are quoted.

**Temperature — WITHDRAWN (2026-09-14).** An earlier revision of this
subsection stated two host readings for the 15-D runs. **They are on no log
in this campaign**: the whole `evidence/` tree contains exactly one `sensors`
block, `001` §6's, taken BEFORE anything was programmed
(`evidence/qwen9b/g6/001_etiquette_resident_readback.log:49`,
`Package id 1:  +59.0°C  (high = +85.0°C, crit = +95.0°C)`), and it reports
one package, not two. **No rung after `001` read the host thermals** — not
`110`, not the 15-D sessions, not `148` — so no number is stated here and
§15's row says the same. There is no temperature CSR to read instead (§15).
This is the same class of unsourced number §15 withdrew, found by the same
grep, and it is withdrawn rather than re-measured because a host temperature
at a run that ended days ago cannot be re-taken.

### 22.3 The exponent side array is written in 64-BYTE BEATS — B15.1's own rule, seen on silicon

`131` also showed rows 504-506 carrying the **same 256 B** as before (the
526-step session's, untouched by a 504-step run) with their **exponent byte
changed from 252/251 to 0**. `132` pins the pattern, L0 kvh0, after a T = 504
session (**T**, `132`):

```
  K exp: 480..503 = 252/253   504..511 = 0   512..525 = 252/253   526..543 = 0
  V exp: 480..503 = 251/250   504..511 = 0   512..525 = 251/250   526..543 = 0
```

This is not a defect; it is `sw/tok_meter.py:138`'s clause observed —
"SST of TCNT rows of 256 B plus the exponent side array rounded
up to one 64 B beat (B15.1's "Length")". A T = 504 store writes exponent
entries 0..511 (eight 64 B beats), so 504..511 get the slot's content past
TCNT, which is zero; 512..525 are the previous, deeper session's, which
nothing reads because TCNT is 504. **The 256 B rows are per row; the
exponents are per 64.** Any row-level comparison between the chip and the
reference has to know this, which is why it is written down here.

### 22.4 The prompt-length bisect, on the chip

The same 12-id wrapper, the same instruction line, the same sentence — the
body truncated at whole sentences, so k copies is a **prefix of 16 copies in
id space**. N is the templated id count each run's own JSON records
(N = 23 + 30k); decode 1 is at position N−1 and decode 2 — the step that
diverged at N = 503 — at position N. `--ntok 4`, greedy (**T**, `133`-`141`,
and `128` for N = 503):

| N | chip's 4 tokens | text |
|---|---|---|
| 53 | `[57590, 26990, 494, 264]` | `'Paris evolved from a'` |
| 83 | `[57590, 26990, 494, 264]` | `'Paris evolved from a'` |
| 113 | `[760, 3177, 314, 11751]` | `'The city of Paris'` |
| 143 | `[760, 3177, 314, 11751]` | `'The city of Paris'` |
| 203 | `[760, 3177, 314, 11751]` | `'The city of Paris'` |
| 263 | `[57590, 26990, 494, 264]` | `'Paris evolved from a'` |
| 323 | `[760, 20438, 16661, 314]` | `'The passage consists of'` |
| 383 | `[760, 20438, 16661, 314]` | `'The passage consists of'` |
| 443 | `[760, 20438, 16661, 314]` | `'The passage consists of'` |
| 503 | `[760, 20438, …]` | `'The passage repeatedly states'` |

**Read this table carefully — on its own it establishes nothing about the
divergence.** The chip's own decode 2 is **3177** at N = 113..203, which is
the id the reference produced at N = 503, and **20438** from N = 323 up. But
a longer prompt is a *different* prompt, and a model is entitled to answer it
differently. The table is the ladder the reference runs climb; it is not a
verdict.

**The lanes over these runs**, where the launch count is inside §14.5's bound
(**T**, `133`-`139`): `L_LCYC` **40.466** ms/step at N = 53, then 41.001,
41.424, 41.803, 42.504, 43.174, **43.829** at N = 323 — it grows with the
context, as §8.7's decode-step time does. `L_SDMA_CYC` over the same runs:
**5.091 → 5.519** ms/step. At 387 and 447 launches (`140`, `141`) the
`L_LCYC` readings (0.083 and 6.685 ms/step) have **wrapped** and are not
measurements; `L_SDMA_CYC` there (5.601, 5.681) has not.

### 22.5 The reference at each N — TWO LANDED, FOUR IN FLIGHT

Six board-free replays of the runs in §22.4 were launched on snoke on
2026-09-10 at 19:32 and 19:39 (−06:00), detached (`nohup setsid`, own
session, `ppid 1`), `nice -n 10`, `OMP_NUM_THREADS=MKL_NUM_THREADS=9` so
they share 48 cores, each through `evidence/qwen9b/run.sh`, each on the tree
`a1fe35f` (the extension's own commit) — **no board, no lock, no DMA**. Each
runs `--top5 5 --continue --dump-kv (N−2)-(N+3)`, so it replays every decode
step instead of stopping at the first disagreement, prints the reference's
five best logits at each, and dumps the reference region's KV rows at the
same positions the chip's own readback covers.

| log | N | steps | pid | verdict |
|---|---|---|---|---|
| `143_15d_bisect_ref_N53.log` | 53 | 56 | 1122647 | **T**, `LONGCTX_LOCKSTEP: PASS 56/56`, rc 0, 2.1 h |
| `144_15d_bisect_ref_N113.log` | 113 | 116 | 1122649 | **T**, `LONGCTX_LOCKSTEP: PASS 116/116`, rc 0, 3.9 h |
| `145_15d_bisect_ref_N263.log` | 263 | 266 | 1122652 | IN FLIGHT, eta 2026-09-11 ≈ 04:30 |
| `146_15d_bisect_ref_N383.log` | 383 | 386 | 1122648 | IN FLIGHT, eta ≈ 08:30 |
| `147_15d_bisect_ref_N443.log` | 443 | 446 | 1122650 | IN FLIGHT, eta ≈ 10:25 |
| `149_15d_bisect_ref_N503.log` | 503 | 504 | 1123825 | IN FLIGHT, eta ≈ 12:30 |

**`149` is the one that will settle it.** It replays `128`'s own 505-launch
session — the run whose KV rows `128_15d_kv_rows_det_a.json` holds — so when
it lands it gives the reference's **top-5 logits and margin at the step that
diverged**, and its **own KV rows at the same six positions the chip's dump
covers**. `106` had neither, which is why `106` could report the
disagreement and not attribute it.

**Cost per step does NOT grow with N.** All six measure **119-122 s** per
`lite` step and **136-138 s** per `full` one at every N from 53 to 503 (**T**,
the six logs' own per-step brackets), against `106`'s 122.2 s running alone.
The attention term is small beside 24 layers of matvec, and six concurrent
single-threaded numpy processes on 48 cores do not contend.

**N = 53 — PASS 56/56** (**T**, `143`). The first end-to-end lockstep of a
whole 9B chat turn:

| step | pos | ref | chip | | top-5 (id:value) | #1−#2 margin |
|---|---|---|---|---|---|---|
| 52 | 52 | 57590 | 57590 | == | `57590:176931 760:174820 1853:141578 …` | 2,111 (1.1931 %) |
| 53 | 53 | 26990 | 26990 | == | `26990:195712 7633:175422 42303:167385 …` | 20,290 (10.3673 %) |
| 54 | 54 | 494 | 494 | == | `494:216532 888:175564 1083:163476 …` | 40,968 (18.9201 %) |
| 55 | 55 | 264 | 264 | == | `264:204878 449:197503 1141:154159 …` | 7,375 (3.5997 %) |

**N = 113 — PASS 116/116** (**T**, `144`):

| step | pos | ref | chip | | top-5 (id:value) | #1−#2 margin |
|---|---|---|---|---|---|---|
| 112 | 112 | 760 | 760 | == | `760:170437 57590:163020 19205:140790 …` | 7,417 (4.3518 %) |
| 113 | 113 | **3177** | **3177** | == | `3177:82189 20438:80938 3766:72325 …` | **1,251 (1.5221 %)** |
| 114 | 114 | 314 | 314 | == | `314:201693 13538:139538 579:138828 …` | 62,155 (30.8166 %) |
| 115 | 115 | 11751 | 11751 | == | `11751:203255 109705:110796 57590:109070 …` | 92,459 (45.4892 %) |

**The chip's token is rank 1 in the reference's own logits at all eight
decode steps, 0 below the top.** Not "close enough" — the same id.

**AND ONE ROW OF THAT TABLE IS THE FINDING.** At N = 113, decode 2 — the
step that diverges at N = 503 — the reference's two best candidates are
**`3177:82189` and `20438:80938`**: the very pair that disagrees at N = 503,
**1,251 apart out of 82,189, 1.52 %**, the closest margin of the eight. Both
sides pick 3177 there. At N = 503 the reference picks 3177 and the chip
picks 20438. **The N = 503 disagreement is a flip between two candidates
that are already nearly tied 390 tokens earlier**, in a prompt that repeats
one sentence — ' city' (continue the sentence) against ' passage' (talk
about the passage) are the two readings of the instruction, and the model is
close to indifferent between them.

### 22.5a The state comparison — the DN region is BIT-EQUAL, silicon against Python

`g6_kv_rows.py --compare` over the chip's own readback and the reference
region's dump, at the same rows (**T**, `150` for N = 53, `151` for N = 113):

| | N = 53 | N = 113 |
|---|---|---|
| `dn_sha256` | **SAME** `0caf9770cab80714…` | **SAME** `6cd5bc6e016f139e…` |
| KV rows the run wrote | **identical**, rows AND exponent bytes (51..55 / 111..115) | |
| the one row above | 56 / 116 differ | |
| `region_sha256` | differs | differs |

**24 MiB of DeltaNet state, byte for byte, between the FPGA and the Python
reference**, after a 56-step and a 116-step turn. The rows that differ are
the ones **the run did not write**: the chip's KV region is never cleared
between sessions, so row 56 (and 116) still holds an earlier, deeper
session's bytes where the reference's region starts zeroed — and TCNT is 56
(116), so nothing read them. §22.3 named this before the comparison was run.
`region_sha256` differs for the same reason: the chip's KV tail above the
run's own depth is history.

### 22.6 `--verify-head` — the cheapest discriminator, and it is NOT AVAILABLE at 9B

The cheapest way to split "the chip's LM head picked the wrong id" from "the
chip's hidden state differs" is `chat_seq --verify-head`: rebuild the head's
logits on the host from the **chip's own** x8/e_x and assert the host argmax
is the chip's token. At 9B it refuses at the first decode step
(**T**, `148`, rc 1):

```
  head build model_9b_s1_w248.bin -> f32 3880 MiB in 13.86s
  ChatSeqError: the manifest's head dequant is 2^(e_x-18), this file expects
                2^(e_x-21) for a head with e=-4 sh=5 at rs_f=7 (S4)
```

That is the right behaviour — a wrong-convention verification would have
"confirmed" whatever it computed — but **the head/hidden-state split cannot
be made this way without a tool change, and Task 15-D does not take one.**
The 3,880 MiB head cache the attempt wrote was deleted afterwards.

### 22.7 THE ONE THING THAT SCALES WITH T — named, READ ONLY

Both sides compute the same attention: score → softmax → P·V
(`rtl/attn_core.sv:4`-`10` is the contract, `ref/gen_layer_script.py`'s
`_attn_acc` and `ref/layer_fixed.py`'s `attn_decode_fx` are the reference).
Exactly **two** accumulations run the length of the context, and only one of
them has a width that T can reach:

1. **`acc[v] += rshr(p[t]*v8[t][v], …)`** — `rtl/attn_core.sv:123`,
   `logic signed [39:0] acc [HD]`. The softmax weights sum to 2¹⁵ by
   construction, so Σ|p·v| ≤ 2¹⁵ · 127 = 2²² **independently of T**, and the
   40-bit accumulator is never in reach. Not a T hazard.
2. **The exponent sum, one row of the context at a time** —
   `rtl/attn_core.sv:114`, `logic signed [39:0] denom;`, accumulated at
   `rtl/attn_core.sv:412`, `denom <= denom + 40'(esv_q);`. Each row's
   contribution is `exp_neg` in **Q30** — `ref/fixedpoint.py:110`, "exp(x) for x <= 0 given as NEGATIVE Q16 int. Returns Q30 in [0,1]."
   — so a row whose score IS the maximum contributes exactly 2³⁰. A signed
   40-bit accumulator holds 2³⁹−1. **T · 2³⁰ > 2³⁹−1 for T ≥ 512** (**D**).
   The reference has no such bound: `ref/layer_fixed.py:1421` is
   `denom = int(es.sum())                               # Q30`, a numpy int64
   sum widened to a Python int, and `ref/gen_layer_script.py`'s `_attn_acc`
   folds the identical sum straight into `fp.recip_q`.

**`denom` is a FIFTH place the T ceiling lives in, and the file's own
header names only four.** `rtl/attn_core.sv:15`-`16`: "S2 (spec 2026-09-04 state-spill A1.5): the T ceiling lives in FOUR
places and widening any subset is a silent wrap". S2 widened
`cfg_t`/`kv_addr`, `sc_mem`/`es_mem`, the `t, T` pair and that contract line
from 512 to 4,096; `denom` stayed 40 bits, sized for the **old 512 ceiling**.

**Does it explain THIS divergence? On the arithmetic, no.** Decode 2 is at
position 503, which reads T = 504 rows, and 504 · 2³⁰ = 5.412 × 10¹¹ against
2³⁹−1 = 5.498 × 10¹¹ — **98.4 % of full scale in the absolute worst case,
and under it** (**D**). The worst case also needs the softmax to be very
nearly uniform over every row: this prompt repeats one sentence sixteen
times, so it has on the order of sixteen near-identical keys per token, not
five hundred. **`denom` is a real hazard for T ≥ 512 that this campaign had
not written down, and it is very probably not the cause of the failure at
T = 504.** Decode steps 10 through 24 of `083`'s own run (positions 511-525,
T = 512-526) are inside the hazard; the first divergence is not.

**Nothing above was changed.** §22 edits no RTL, no testbench, no
`ref/seq_model.py`, no `ref/layer_fixed.py` and no emitter.

### 22.8 What §22 establishes, and what it does NOT

**ESTABLISHED.**

1. **The chip is deterministic at the divergence point** — three 505-launch
   sessions, the same two tokens, and **all 162,529,280 B of the state
   region bit-identical** (`128`/`129`/`130`). A flaky-silicon explanation
   for `106` is not available.
2. **The chip and the reference are in FULL LOCKSTEP at N = 53 and
   N = 113** — every step, every decode token, the chip's token rank 1 in
   the reference's own logits at all eight, the **DN region bit-equal** and
   every KV row the run wrote identical, exponent bytes included
   (`143`/`144`/`150`/`151`). Before this, the longest lockstep on record
   was §8.6a's 22 steps at a 19-token prompt; these are 56 and 116 steps at
   53 and 113.
3. **The N = 503 disagreement is a flip between two candidates the reference
   itself scores 1.52 % apart at N = 113** — `3177:82189` against
   `20438:80938`, the identical pair, with every other decode step in the
   two runs separated by 3.6-45.5 %.
4. **`denom` is a fifth place the T ceiling lives in** — signed 40-bit
   against a Q30 `exp_neg` per row, so `T ≥ 512` can wrap it where the
   reference sums in int64 — and it is **not** reachable at the T = 504 the
   divergence happens at.
5. **The KV exponent side array is written in 64-byte beats**, so rows above
   TCNT in the last beat read zero while their 256 B rows keep the previous
   session's bytes (`131`, `132`).

**NOT ESTABLISHED — and this section does not imply any of it.**

1. **WHICH SIDE IS WRONG AT N = 503.** That is still open. `149` is the run
   that addresses it and it is in flight.
2. **Where the first disagreement is in POSITION terms.** Every comparison
   here is at DECODE granularity. The 502 prefill steps emit no token on
   either side, so a prefill-step disagreement is invisible to this
   instrument — §8.7a said so and it is still true.
3. **Anything about N = 263, 383 or 443.** Those three replays are in
   flight; §22.4's chip tokens at those N have no comparand yet.
4. **The head / hidden-state split.** `--verify-head` refuses at 9B (§22.6),
   so nothing here says whether a divergence would live in x8 or in the LM
   head.
5. **Whether `denom` ever wrapped in `083`'s own run.** The arithmetic says
   decode steps 10-24 (positions 511-525) are inside the hazard; no
   instrument measured the actual sum.

### 22.9 The recommended next probe, in order of value per hour

**A. Collect `149` — already running, costs nothing.** It is the first
measurement of the reference's logits AT the divergent step. Two outcomes,
and they point opposite ways: if `20438` is the reference's **#2 by a
handful of counts**, the disagreement is a near-tie resolved differently by
two implementations whose fixed-point noise floors differ — the reading
§22.5 already supports — and neither side carries a bug. If `20438` is rank
5 or worse in the reference, something structural is wrong, and `149`'s own
`--dump-kv 501-506` against `128_15d_kv_rows_det_a.json` localises it to a
KV row and a position or exonerates the KV region entirely.

**B. The PER-POSITION lockstep — the probe that would localise the first
disagreement exactly.** Run the chip with `--prefill full`, so every one of
the 503 steps emits a token, and replay the reference with the `full` image
at every step: **503 comparisons instead of 2**, and the first disagreeing
POSITION rather than the first disagreeing decode step. Cost: one chip run
of ≈ 80 s plus one ≈ 19 h reference replay (the `full` step is 137 s against
`lite`'s 121). **It needs one small, bounded tool change**: `sw/chat_seq.py:3585`
is `            if out is not None and i >= len(feed) - 1:`, which
discards the prefill steps' tokens, so they exist in no artifact today.
That change is the whole cost, and it buys the one thing §22.8 item 2 says
is missing.

**C. The Verilator census TB — only if A or B points at the RTL.**
`evidence/qwen9b/s4/run_s4_census.sh` drives `tb_layer_census` with
`+state=<prefix>` (a flat region image) and `+script=`. **Two gaps have to
be closed before it can replay the divergent step**: (i) **nothing dumps the
chip's region to a file** — `g6_state.py --readback` hashes it,
`g6_kv_rows.py` samples it; a `--dump <path>` is a handful of lines and
155 MiB; (ii) the TB replays an EMITTER command script, so the one divergent
step has to be emitted as one. And the wall clock must be **measured, not
assumed**: the same census at 9B took **4,399 s for six steps at a tiny
context** (`evidence/qwen9b/s4/040_census_shipped6.log`), and an `ATTN` at
T = 504 walks ~500× the rows it walks there. **There is no cheap reproducer
to measure it on**: N = 53 and N = 113 both PASS, so the smallest known
failing case is still the 503-token one.

**D. `denom` — post-ship, and it belongs on Task 16's list** beside §12.1's
gate-port clamp and §14.5's counter widening, all three of which need a
bitstream. What can be done without one, and would say whether the hazard
was ever live in `083`: a ~20-line tap on the reference's own `es.sum()`
(the same shape as the `--top5` tap, which is read-only and does not touch
`ref/`) reporting the maximum over a run. If the largest `denom` at T = 504
is a few percent of 2³⁹, the hazard is theoretical at these contexts and can
be scheduled; if it is near it, `--max-ctx` needs a bound in the host tool
until the RTL is widened.

**Read together, the evidence so far implicates NEITHER implementation.**
The chip reproduces the reference exactly — tokens, DN state and KV rows —
at every length that has a comparand, and the one place they disagree is a
pair of candidates the reference itself cannot separate by more than a
percent and a half. What `149` decides is whether that stays the reading.

### 22.10 ROUND 2 — H1 ("the chip attends over at most 7 KV blocks") TESTED BY READING, AND **REFUTED**

**The hypothesis.** The flip appears only between N = 443 and N = 503, the
interval in which the KV cache crosses from its 7th 64-row block (rows
384-447) into its 8th (448-511). H1: some loop bound, block index width,
prefetch count or slot tag in the chip's KV path stops at 7 blocks / 448
rows, so a step at T > 448 attends over less than its whole context. This
subsection tests it **statically — by reading the compiled schedule, the
ISA, the RTL and the reference. No run was needed and none was made.**

**(a) How many KV `SLD`s does a step issue, and is the count baked at
compile time?** **NEITHER, in the sense the hypothesis needs.** The schedule
is **T-independent**: `ref/gen_layer_script.py:1842` `def sched_kv_prefetch(layer_types)`
and `ref/gen_layer_script.py:1898` `def sched_attn_layer(M, A, nkv, dn_slot, cv_slot, body)`
emit a FIXED transfer set per token — per attention layer, an `SLD` pair
(K and V) for each kvhead the layer is about to need and an `SST` pair for
each kvhead it has just finished, so **64 KV `SLD`s + 64 KV `SST`s = 128 KV
transfers per forward step at every context length**. That count is
CONFIRMED by a committed census:
`evidence/qwen9b/s4/040_census_shipped6.log`'s SLD+SST column reads **224**
per step at a 6-token context — 128 KV + 48 DN + 48 conv — and a 504-token
step issues the same 224. **No command in the stream carries T at all.** The ROW COUNT is
read by the HARDWARE when the transfer starts:
`rtl/layer_chan.sv:2110`, `14'(tcnt_bank[hd_layer[2:0]][hd_head[2:1]]);`
— a 14-bit field fed from the 13-bit counter at `rtl/layer_chan.sv:466`,
`logic [12:0] tcnt_bank [N_KV][NKVH];`. So the premise "baked from
`model_9b_s1.e4` (emitted for T ≈ 8)" is **false**: the emitted image is
the same 39,626-record `full` body at T = 8 and at T = 504 (`128`'s own
header: `compiler   ref/seq_chat.TurnCompiler(pos_mode='ldc', t_max=4096)`),
and every T-dependent quantity is a runtime read of `tcnt_bank`.

**How a 503-context step attends over 503 rows** is then exactly this:
`ATTN` takes T from the slot's TAG — `rtl/layer_chan.sv:1622` is
`tcnt_bank[kv_tag[layer_kv[0]][4:2]]`, indexed by the tag the filling `SLD`
latched, not by any layer field — and `rtl/attn_core.sv:37` is
`cache length T (<= 4096)` on a 13-bit port.
The cache slot itself is `rtl/layer_chan.sv:385` `localparam int KV_AW  = 13;`
— 4,096 rows per K/V half, one (layer, kvhead) per slot.

**(b) The table. Is any counter, address field, tag or loop bound limited at
7 blocks / 448 rows / a power of two near it?**

| component | the T-dependent quantity | width / limit | reachable at T = 504? | matches the reference? |
|---|---|---|---|---|
| emitted SEQ stream (`sched_attn_layer`, `sched_kv_prefetch`) | none — the schedule is fixed per token | 64 KV transfers/step at any T | n/a | identical: one schedule, five emitters |
| `LAYER.kv_layer` / `kv_slot` (`rtl/layer_chan.sv:26`) | slot SELECT, not a row or block index | 3 b layer, 2 b slot | n/a — selects a cache slot, never a row | the model keeps the same two slots + tag |
| KV slot tag, `rtl/layer_chan.sv:672` `logic [4:0]  kv_tag   [N_SLOT];` | the pair `{layer[2:0], kvhead[1:0]}` | 5 b = 8 layers × 4 kvheads | n/a — no T in it | the model keeps the same tag per slot |
| the KV append counters, `rtl/layer_chan.sv:466` `logic [12:0] tcnt_bank [N_KV][NKVH];` | T itself | **13 b, 0..8191** | yes, 504 ≪ 8191 | the model's own counter array, a Python int |
| `ATTN`'s `at_cfg_t` (`rtl/layer_chan.sv:1621`) | T handed to `attn_core` | 13 b | yes | `_kv_view` returns the same T |
| `attn_core` `cfg_t` / `kv_addr` / `t, T` | the per-row loop | 13 b / `{bank, t[11:0]}` | yes, 4,096 rows | `_attn_acc(kcache, vcache, T, qn)` loops `range(T)` |
| `attn_core` `sc_mem` / `es_mem` | one entry per row | **4,096 deep** | yes | numpy arrays of length T |
| KV cache slot memory (`KV_AW = 13`) | `{kv, t[11:0]}`, 8192 × 2048 b | 4,096 rows per half | yes | `M.kc[slot]` / `M.vc[slot]` lists |
| `SLD`/`SST` row count (`rtl/layer_chan.sv:2110`) | `hd_rows` = TCNT | 14 b | yes | `ref/seq_model.py:249` `t = int(M.T[layer][head >> 1])` |
| `state_dma` row phase | `4 · T` beats, `srow` | 16 b beats / 13 b rows | yes (2,016 beats) | the model copies T rows |
| **`state_dma` exponent phase** | **`ceil(T/64)` beats** — `rtl/state_dma.sv:99` `beats_of = (r16 + 16'd63) >> 6` | **7 beats at T ≤ 448, 8 at 449 ≤ T ≤ 512** | **yes — THE ONLY QUANTITY IN THE PATH THAT CHANGES AT 448** | the model moves **T bytes and no more** |
| KV DDR block (`sw/hwmap.py:624`-`558`) | `STATE_KV_STRIDE = 1 << 21`, exp at `1 << 20`, `STATE_T_MAX = 4096` | 1 MiB rows = 4,096 × 256 B | yes | the model uses the same map |
| position pool / RoPE `LDC` (`ref/seq_chat.py:686`-`672`) | `POS_BLOB_BASE + pos*2048`, patched per launch | full u32 `addr_lo` — `docs/SEQ_ISA.md:424`, `DDR byte address = signed{len_or_addr_hi, addr_lo} +/- XRF[i]` | yes; the ldc position mode is in use, so the 18-bit XRF[4] hazard is not on this path | same bytes, one compiler |
| `denom` (`rtl/attn_core.sv:114`) | `Σ es[t]`, one Q30 term per row | signed 40 b | **504 · 2³⁰ = 98.4 % of 2³⁹−1 — under it** | `ref/layer_fixed.py:1421` `denom = int(es.sum())`, int64 |

**THE VERDICT: there is NO such place. H1 is REFUTED.** Not one counter,
address field, tag or loop bound in the chip's KV path stops at 7 blocks or
448 rows. Every T-dependent quantity is 13 bits or wider, runtime-read from
`tcnt_bank`, and dimensioned for **4,096** — S2 moved all of them together
and the reading confirms it held.

**(c) The one thing that does change at 448, and why it is benign.** The KV
exponent side array is the ONLY quantity in the whole path whose value
differs between T = 448 and T = 504: it travels in `ceil(T/64)` 64-byte
beats (`rtl/state_dma.sv:99`), so **7 beats for T ≤ 448 and 8 for
449 ≤ T ≤ 512** — precisely the 7→8 crossing H1 is built on. It is
computed correctly (`(r16 + 16'd63) >> 6` is ceiling, not floor) and the
beat count is consumed correctly on both sides of the transfer: the load
pops exactly `ceil(T/64)` beats and writes exactly T bytes into the slot's
`emem` (`rtl/state_dma.sv:287`, `slot_wexp    <= bbuf[{l_esub, 3'b0}+:8];`,
with the phase ending on `srow + 1 == ph_rows`), and the store pushes the
same count with the partial last beat zero-filled. The reference moves
**T bytes and no more** (`ref/seq_model.py:252`,
`ex = self.mem[o + HW.STATE_KV_EXP_OFF:`). **The two sides therefore differ
in DDR in the bytes at and above TCNT in the last beat — and in no byte any
reader reads**, because the slot only ever receives T of them and `ATTN`
walks `t < T`. §22.3 measured exactly that on silicon (`132`: `504..511 = 0`)
and §22.5a measured the consequence (every KV row the run WROTE identical;
the rows above it not).

**(d) What the reading DOES implicate — the coverage gap, stated exactly.**
The bisect's chip runs used `--ntok 4` at N ≤ 443 and `--ntok 2` at N = 503,
and a decode step at position p reads T = p + 1 rows. So the deepest T with
a reference comparand is **T = 446** (`147`, step 445) and the divergent
step is at **T = 504**. **57 consecutive values of T — 447 through 503 —
have never been compared at all**, and the 7→8 exponent-beat crossing at
T = 449 sits inside that gap. The gap is a gap in the EVIDENCE; the reading
above says there is nothing in the DESIGN that distinguishes its two ends.

**And the margin evidence now says the near-tie reading is not free either.**
With `145`-`147` landed, the reference's own decode-step margins at the
bisect's four deepest N are (**T**, each log's `top5` line):

| log | N | step / pos | ref | chip | top two | margin |
|---|---|---|---|---|---|---|
| `145` | 263 | 262 | 57590 | 57590 `==` | `57590:172369  760:172117` | **252 (0.1462 %)** |
| `145` | 263 | 263 | 26990 | 26990 `==` | `26990:188698  13538:182888` | 5,810 (3.0790 %) |
| `146` | 383 | 383 | **20438** | 20438 `==` | `20438:82625  3177:81681` | 944 (1.1425 %) |
| `147` | 443 | 443 | **20438** | 20438 `==` | `20438:82169  3177:77945` | 4,224 (5.1406 %) |

Two readings fall out, and they are the round's real finding:

1. **The chip and the reference agree at a margin of 252 counts — 0.1462 %
   of the top logit.** That is the **tightest agreed decision in this
   campaign**, an order of magnitude tighter than the 1.52 % at N = 113 that
   §22.5 called the closest of its eight. It bounds any systematic
   chip-vs-reference logit error at T = 263 to **below ~126 counts**.
   A "two implementations with different fixed-point noise floors resolve a
   near-tie differently" explanation for N = 503 must therefore either put
   `149`'s margin BELOW that, or make the error GROW with T.
2. **The 3177 / 20438 pair is not converging on 3177 as N grows.** The
   reference prefers `20438` by 1.14 % at N = 383 and by **5.14 %** at
   N = 443 — a widening preference — and then, at N = 503, `106` says it
   picks `3177`. Whatever `149` reports, that reversal is not a trend.

**Nothing in §22.10 was run and nothing was changed.** It edits no RTL, no
testbench, no `ref/seq_model.py`, no `ref/layer_fixed.py` and no emitter,
and it adds no instrument.

### 22.11 `149` LANDED — **`LONGCTX_LOCKSTEP: PASS 504/504`**, AND `106`'s FAIL IS EXPLAINED: THE REFERENCE RAN AT THE WRONG `RS_F`

**T**, `149`, 16.85 h, 120.4 s/step, 504 of 504 steps, tree `8639813`, no
board. It replayed `128`'s own 503-token session — the run whose two tokens
are `[760, 20438]` and whose KV rows `128_15d_kv_rows_det_a.json` holds:

```
  step 502 full tok=271     pos=502 ref ->      760  chip -> 760  ==   'The'
      top5    760:90840  19205:77504  57590:73804  1919:69112  88762:68868   #1-#2 margin 13336 (14.6808% of the top logit)
  step 503 full tok=760     pos=503 ref ->    20438  chip -> 20438  ==   ' passage'
      top5    20438:82490  3177:80962  11173:75500  3766:73219  1414:72636   #1-#2 margin 1528 (1.8523% of the top logit)
  ref ids    [760, 20438]
  chip ids   [760, 20438]
LONGCTX_LOCKSTEP: PASS 504/504
```

**THE REFERENCE PRODUCES THE CHIP'S TOKEN.** At the step `106` called a
divergence, the reference's own top two are `20438:82490` and `3177:80962`
— **1,528 apart, 1.8523 %** — and it picks **`20438`**, which is what the
chip picked. `106`'s `3177` is not reproduced. The chip's token is rank 1 in
the reference's logits at **both** decode steps, 0 below the top.

**SO WHY DID `106` SAY `3177`? The two replays ran DIFFERENT REFERENCE
MODELS.** They fed the identical token stream — `106` and `149` print the
same `tok=` at every step from 495 to 503 (`198, 248045, 74455, 198,
248068, 271, 248069, 271, 760`) — and every file in the replay's execution
path is byte-identical between the two trees: `git diff 2762662 8639813 --
ref/gen_layer_script.py ref/seq_model.py ref/fixedpoint.py ref/w4a8_ref.py
ref/layer_ref.py` is **EMPTY** (**T**, `162`, through the round's one new
instrument `evidence/qwen9b/g6/g6_rsf_provenance.sh` — git plumbing and two
`git show` greps, no model and no board; `160` is the same script's FIRST
attempt, `rc 127`, run from a scratch path snoke cannot see, kept because
this campaign does not delete a log). **One constant differs, and it is the
operating point.**

| | `106` | `149` |
|---|---|---|
| tree | `evidence/qwen9b/g6/106_longctx_lockstep_ref.log:3` `=== tree: 2762662` (2026-09-10 00:41:17) | `evidence/qwen9b/g6/149_15d_bisect_ref_N503.log:3` `=== tree: 8639813` (2026-09-10 19:34:01) |
| launched | 2026-09-10 **00:44:07** | 2026-09-10 **19:35:49** |
| `FABLE5_RS_F` | `evidence/qwen9b/g6/106_longctx_lockstep_ref.log:9` `FABLE5_MODEL=9b FABLE5_DN_STATE=unset FABLE5_RS_F=unset` | `evidence/qwen9b/g6/149_15d_bisect_ref_N503.log:9`, the identical line |
| `ref/layer_fixed.RS_F` at that tree | `evidence/qwen9b/g6/162_15d2_rsf_provenance.log:24` `RS_F = int(os.environ.get("FABLE5_RS_F", "8") or "8")` → **8** | `ref/layer_fixed.py:103` `RS_F_BY_TAG = {"0.8b": 8, "2b": 8, "4b": 8, "9b": 7}` → **7** |
| the DeltaNet conv shift it executes | `RS_F + CW_F − 12` = 8 + 13 − 12 = **9** | 7 + 13 − 12 = **8** |
| what the shipping RTL bakes | **8** | **8** |

**The chain, in four links, each one read from the tree:**

1. **The replay executes `Mach.conv`, and `Mach.conv` reads `RS_F` at run
   time.** `ref/gen_layer_script.py:1041`, inside
   `ref/gen_layer_script.py:1032` `def conv(self, first, nch, src, dst):`,
   is `pre_raw = rshr(acc, RS_F + CW_F - 12)`, and
   `ref/gen_layer_script.py:50` binds that name from `layer_fixed` at import:
   `RS_F, QKV_F, NRM_F, S_F, GAT_F, CW_F = (LF.RS_F, LF.QKV_F, LF.NRM_F,`.
   `ref/layer_fixed.py:145` is `CW_F = 13`.
2. **The shipping bitstream bakes 8.** `rtl/conv4_silu.sv:54` is
   `pre = rshr64(64'(acc1), 8);          // RS_F + CW_F - 12 = 8`, under its
   own note at `rtl/conv4_silu.sv:50`-`52`: `RS_F = 7 is the 9B operating point, so the`
   / `baked shift is RS_F + CW_F - 12 = 7 + 13 - 12 = 8.  It was 9 at` /
   `RS_F = 8.`
3. **The artifact agrees with the RTL, not with `106`.**
   `tb/scripts/w9/model_9b_s1.weights.json:2493` is `"rs_f": 7,`.
4. **The fix landed while `106` was still running.**
   `28fac0b tool(b11): RS_F is DERIVED from MS.TAG, not remembered (#26)` is
   dated **2026-09-10 04:51:37**, four hours and seven minutes after `106`
   started and about thirteen hours before it finished. Python binds a module
   constant at import, so `106` ran all 17.08 h at `RS_F = 8`.

**`106` therefore replayed the 9B model with EVERY DeltaNet layer's conv
output shifted one bit too far** — 24 layers × 504 steps = **12,096 wrong
shifts**, each a factor of two on the conv output that feeds the residual
stream. That is the perturbation, and its size explains the pattern exactly:
decode 1, at a **14.68 %** margin, survives it and agrees; decode 2, at
**1.85 %**, does not.

**WHICH SIDE WAS WRONG AT N = 503: THE REFERENCE, AND ONLY IN `106`.** Not
the chip, not `attn_core`, not the KV cache, not block 8, not `denom`. The
silicon has been right at every length this campaign has measured, and the
one measurement that said otherwise was taken against a reference model that
a tool fix had already corrected before the measurement finished.

**The KV rows and the DN state, chip against reference at N = 503.** `149`'s
own `--dump-kv 501-506` against `128`'s board readback (**T**, `161`,
`g6_kv_rows.py --compare`): `dn_sha256      SAME  A e098f93a84ec90e1…  B e098f93a84ec90e1…`
— **24 MiB of DeltaNet state, byte for byte, between the FPGA and the Python
reference, after a 503-token prompt**, and the same hash §22.2 recorded as
the chip's own. The verdict line is
`KV ROW COMPARE: 18 rows differ, lowest differing row 504` — and **504 is
TCNT**: the run wrote rows 0..503, so rows 501, 502 and 503 are identical on
both sides and the three above them differ for §22.3's reason (the chip's KV
tail above its own depth is a deeper session's history where the reference's
region is zero). The reference's own exponent
bytes at rows 501..506 read `[252, 252, 252, 0, 0, 0]` (L0 kvh0 K): three
written rows (501, 502, 503), then zeros above TCNT — **the exponent-beat
behaviour §22.10(c) predicted, now seen on the reference side too.**

### 22.11a What this closes, and the one thing it opens

**CLOSED.** §22.8's open item 1 — "WHICH SIDE IS WRONG AT N = 503" — is
answered: **neither implementation carries a defect at N = 503**, and the
reported divergence was an artefact of a reference run at the wrong
residual binary point. The chip and the reference are now in **full lockstep
at N = 53, 113, 263, 383, 443 and 503** — every length in the bisect, every
decoded token, the chip's token rank 1 in the reference's own logits at all
eighteen decode steps.

**OPEN, and it is a PROCESS finding, not a silicon one.** `106` was launched
from a tree whose `RS_F` default was the 0.8B one, it printed
`FABLE5_RS_F=unset` in its own provenance header, and **nothing in the run
could see that the value was wrong** — which is the exact property #26 was
filed about, quoted in `ref/layer_fixed.py:84`-`86`:
`wrote `rs_f: 8` into its own manifest, passed every byte-lock and every` /
`gate, and had every logit dequantized by 2x the right scale against the` /
`shipping bitstream.` The fix (`28fac0b`) closed it for everything emitted
or replayed **after 04:51 on 2026-09-10**. **`106` is the one committed 9B
measurement taken before it, and §8.7a's reading of `106` is superseded by
this subsection.** The lesson for the campaign: a provenance header that
prints an environment variable as `unset` records the ABSENCE of an
override, not the VALUE in force — and `evidence/qwen9b/run.sh` has no line
that prints `ref/layer_fixed.RS_F` itself. Printing the derived operating
point, not just the env, is a one-line wrapper change and it belongs on the
next round's list.

**`denom`, `--verify-head` and the 57-value coverage gap are UNAFFECTED**:
§22.7's hazard at T ≥ 512 is still real and still post-ship, §22.6's refusal
still stands, and T = 447..503 still has no comparand — but the reason to
close that gap is now curiosity about coverage, not a suspected defect.

### 22.12 THE NEXT PROBE, RE-RANKED — §22.9's list is SUPERSEDED

§22.9's A is **done** (`149`, §22.11) and its premise — that which side is
wrong is open — is **answered**. What is left is coverage and process, not a
suspected defect. The four that remain, in order of value per hour:

**A′. THE WRAPPER SHOULD PRINT THE OPERATING POINT, NOT THE ENVIRONMENT.
~5 lines, free, and it is the change that would have caught this at the
time.** `evidence/qwen9b/run.sh` prints `FABLE5_RS_F=unset` on line 9 of
every log — which records the ABSENCE of an override, **not the value in
force**. `106`'s header is indistinguishable from `149`'s on that line
(`162` prints both), and the two ran at different operating points. A
wrapper line that printed the DERIVED constants — `model_select.TAG` and
`ref/layer_fixed.RS_F` — would have made `106` self-evidently wrong at its
own line 9, seventeen hours before its verdict. **The cost is one Python
import in the wrapper** (numpy, ≈ 1 s per run against runs that take hours)
and a RED control that a mismatched `FABLE5_RS_F` shows up in the header.
Every other probe on this list is worth less than this one.

**B′. REPLAY `083` — the 24-token session — AT THE CORRECT `RS_F`.
≈ 17.5 h of host, board-free, and NO tool change: the instrument already
has `--top5`, `--continue` and `--dump-kv`.** Two things only this run can
give. First, `083` decodes **23 tokens** where `128` decodes 2, so it is
**23 decode comparisons at T = 504 through 526** — the deepest T this
campaign can reach, and the only comparands that exist above T = 504.
Second, **it is the only measurement that can say whether §22.7's `denom`
hazard ever bit**: positions 511-525 are `T ≥ 512`, where a signed 40-bit
accumulator of Q30 terms can wrap in the worst case and the reference's
int64 cannot. If the 23 tokens agree, the hazard was never live in this
session and `denom` stays a scheduled post-ship RTL fix; if they diverge at
exactly T = 512, §22.7 has found its own confirmation. **`106` is the one
committed 9B measurement taken at the wrong `RS_F`, and §8.7a's reading of
it is superseded by §22.11** — this run is what replaces it.

**C′. The attn-core T-sweep** — still the cheapest way to answer "do the two
sides compute the same attention at any T?" in general, and still the only
probe that carries its own positive control. `tb/tb_attn_core.sv:1`-`2`
declares itself `attn_core vs layer_fixed attention-core golden vectors` and
`bit-exact on the 256 output accumulators`, and it is **hard-wired at
T = 48**: `tb/tb_attn_core.sv:52` is `logic [7:0]  k8f [12288];` and
`ref/gen_layer_vectors.py:97` is `# ---- attention core (T=48) ----`. Its KV
model is already deep enough (`tb/tb_attn_core.sv:38`,
`logic [2047:0] kmem [512];`). One `ATTN` at T = 504 is ≈ 22,400 cycles
(**D**, from the 40.9 cycles/row below), so a sweep of
T = 48, 446, 447, 448, 449, 503, 504, 511, 512, 520 × 4 seeds is **minutes**.
The positive control is `denom` itself: a vector set whose scores are all
equal makes the sum exactly `T · 2³⁰`, so the RTL MUST disagree with the
int64 reference at **T ≥ 512** and agree below it. **Cost: a bounded edit to
`tb/tb_attn_core.sv` and a `--T` flag on `ref/gen_layer_vectors.py`, ~40
lines. Task 15-D round 2 did not take it — its rules forbid editing a
testbench** — and B′ measures the same hazard end-to-end without any edit,
which is why B′ ranks above it now.

**D′. The per-position lockstep** (§22.9 B) and **the census TB**
(§22.9 C) are both **low priority now**. For the record, §22.9 C's wall
clock, which it left open, is CLOSED here and the answer is that the
SIMULATION is the cheap half: `evidence/qwen9b/s4/040_census_shipped6.log:61`
is `LAYER_CENSUS TOTAL_BUSY_CYCLES 68510840` in `wall=4399 s`
(`evidence/qwen9b/s4/040_census_shipped6.log:78`) =
**15,574 cycles/s** (**D**), and a step at T = 504 is
`11405434 + 5230.4 × 503` ≈ **14.04 M cycles** (**D**) → **≈ 900 s**. The
5,230.4 is itself a measurement: `evidence/qwen9b/s4/040_census_shipped6.log:70`
and `evidence/qwen9b/s4/040_census_shipped6.log:75` are the same program's
per-step totals at the 1st and 6th step of a fresh session, `11405434` and
`11431586`, and 128 `ATTN`s × the **40.9 cycles/row** its own spread implies
(`evidence/qwen9b/s4/040_census_shipped6.log:57`, `1962     1860     2065`)
is **5,248** — **`ATTN` is the whole
per-step growth, to within 0.4 %** (**D**), with DeltaNet, conv, the FFN and
the LM head all on a fixed-size state and a fixed `9429` commands per step
(`evidence/qwen9b/s4/040_census_shipped6.log:70`). What is expensive in §22.9 C is the TB's INPUT, not its run: a flat
state image at the divergent step needs either a `--dump` on `g6_state.py`
(≈ 1 h, off the board) or a `--dump-region` on `g6_longctx_lockstep.py` and
another ≈ 17 h replay.

**`denom` (§22.9 D) is folded into B′ and C′** — both measure it, neither
needs the ~20-line tap on its own.

### 22.13 Round 2's closing gates

**Superlatives.** **T**, `163`, tree `6f61f30` clean: `G6SUP: PASS`, **17**
DERIVED quantities recomputed from the logs and **69** UNCHECKED (59 after
round 1 — every one of the ten new ones the ordinary-English "only"/"first"
idiom, not a measurement claim). **T**, `164`: `G6SUP_CONTROL: CAUGHT BOTH
— the checker is live`.

**`spec_cites` LAST.** **T**, `165`, on the committed tree `609d64a`:
**FAIL 7**, all seven this round's own and **none of them a wrong claim** —
six `ORPHAN`s — a bare colon-and-line-number continuation on a line that
names no file, which the checker does not bind and therefore does not check
— and one `QUOTE` that paired the OLD tree's `RS_F` expression with the
NEW tree's line number, because the expression the sentence is about does
not exist in the working tree at all. Both classes are repaired in the same
commit as the failing log: every continuation now carries its full path, and
the old expression is quoted from **`162`'s own log**, which is where it is
preserved. `166` then found **FAIL 1** — the sentence above had reproduced
the very defect it describes, by writing the bare form inside backticks —
and `167` is the covering run, on the tree that carries this paragraph.

**Board etiquette.** **No board session was opened this round.** No
reprogram, no flash, no sudo, no DMA, `--no-lock` on no command line, and
not one chip run. The board still carries build_041 (`0xc973c18a`) and the
`model_9b_s1` pack, untouched. Everything that ran on snoke through
`evidence/qwen9b/run.sh` was a checker or a `git` read: `157`, `158`, `165`,
`166` (`spec_cites`), `160`/`162` (`g6_rsf_provenance.sh`), `161`
(`g6_kv_rows.py --compare`), `163`/`164` (superlatives). Nothing numeric ran
on darthplagueis. `149` was the only model run, and it was launched by round
1 and merely collected here.

### 22.12a A′ LANDED AND B′ IS IN FLIGHT (2026-09-11)

**A′ — `evidence/qwen9b/run.sh` NOW PRINTS THE DERIVED OPERATING POINT, NOT
JUST THE ENVIRONMENT.** One line, emitted between the `=== env:` lines and
`=== ---` of every log this wrapper writes from here on:

```
=== rs_f: derived=7 (tag 9b) env=unset rider=0
```

`derived` is the LAW, read out of the tools' own module rather than
remembered: the wrapper imports `ref/model_select.py` and `ref/layer_fixed.py`
the way `ref/gen_layer_script.py:44` imports them (`import layer_fixed as LF`)
and prints `LF.RS_F` beside `MS.TAG` — `evidence/qwen9b/run.sh:82`,
`print("derived=%d (tag %s)" % (LF.RS_F, MS.TAG))` — through the first
executable of the two interpreters the `=== venv:` lines already probe
(`evidence/qwen9b/run.sh:61`,
`for _c in /home/cah/.venv/bin/python ref/.venv/bin/python; do`). The value it
lands on is `ref/layer_fixed.py:103`'s
`RS_F_BY_TAG = {"0.8b": 8, "2b": 8, "4b": 8, "9b": 7}` indexed by the selected
tag (`ref/layer_fixed.py:104`, `_RS_F_LAW = RS_F_BY_TAG[_MS.TAG]`), which is
`ref/model_select.py:21`'s `TAG = os.environ.get("FABLE5_MODEL", "0.8b")`.
**Cost: 0.22 s per wrapped run** (**D**, timed on snoke against runs that take
hours).

**Two properties, both deliberate, both in the file's own header comment.**

1. **A disagreeing `FABLE5_RS_F` is REPORTED here, not obeyed and not fatal
   here.** `ref/layer_fixed.py:106`-`107` is the refusal
   (`if _RS_F_ENV is not None and int(_RS_F_ENV) != _RS_F_LAW:`) and it stays
   the tools' job; the probe strips `FABLE5_RS_F` and `FABLE5_RS_F_RIDER` from
   its OWN environment (`evidence/qwen9b/run.sh:77`,
   `os.environ.pop("FABLE5_RS_F", None)        # the LAW, not the override`) so
   the header can print the law beside the override instead of dying on the
   contradiction. **The header reports the operating point; the guard enforces
   it.**
2. **It can never fail the wrapped command.** Every error path prints
   `=== rs_f: unavailable (<reason>)` and returns 0
   (`evidence/qwen9b/run.sh:87`), and an unset `FABLE5_MODEL` prints
   `derived=n/a (FABLE5_MODEL unset)` (`evidence/qwen9b/run.sh:68`). A 17 h
   replay does not die because a venv moved.

**THE RED/GREEN PAIR — three wrapped `true`s on snoke, tree `15e2394`, all
`rc 0`.** Line 11 of each log, verbatim:

| log | environment | line 11 |
|---|---|---|
| `evidence/qwen9b/g6/168_15d3_rsf_header_green.log:11` | `FABLE5_MODEL=9b` | `=== rs_f: derived=7 (tag 9b) env=unset rider=0` |
| `evidence/qwen9b/g6/169_15d3_rsf_header_red.log:11` | `FABLE5_MODEL=9b` plus `FABLE5_RS_F=8` | `=== rs_f: derived=7 (tag 9b) env=8 rider=0` |
| `evidence/qwen9b/g6/170_15d3_rsf_header_nomodel.log:11` | neither set | `=== rs_f: derived=n/a (FABLE5_MODEL unset) env=unset rider=0` |

**`169` is the control that FIRES**: `derived=7 env=8` is the disagreement,
printed by a wrapper that then RAN the command anyway — while the tools
themselves would have refused that environment by name. And the case that
actually bit is the GREEN one: `evidence/qwen9b/g6/168_15d3_rsf_header_green.log:9`
is `=== env:  FABLE5_MODEL=9b FABLE5_DN_STATE=unset FABLE5_RS_F=unset` —
**character for character what `106`'s line 9 said** — and line 11 now adds
`derived=7`. The same wrapper on `106`'s tree (`2762662`, where the default
was 8) would have printed `derived=8 (tag 9b) env=unset`, **seventeen hours
before that run's verdict**. That is the whole claim of A′, and it is now a
property of the instrument rather than of the operator's memory.

**B′ — THE `083` REPLAY AT THE CORRECT `RS_F` IS IN FLIGHT.**

| | |
|---|---|
| log | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log` |
| launched | **2026-09-11 12:47:07 −06:00**, snoke, detached (`nohup setsid`, own session, `ppid 1`), `nice -n 10`, `OMP_NUM_THREADS=MKL_NUM_THREADS=9` |
| pid | **1273730** (the Python; `1273694` is its `evidence/qwen9b/run.sh` wrapper) |
| tree | `e1d0d3a` — A′'s own commit, clean |
| command | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:4` — `nice -n 10 /home/cah/.venv/bin/python -u evidence/qwen9b/g6/g6_longctx_lockstep.py --selfcheck --top5 5 --continue --dump-kv 501-506 --out evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.json` |
| the operating point | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:11` — `=== rs_f: derived=7 (tag 9b) env=unset rider=0` |
| steps | **526** = 502 prefill + **24 decode**, the `083` session, at 120.7 s/step on step 0 |
| eta | ≈ **17.7 h** → 2026-09-12 ≈ 06:30 −06:00 |
| board | **none** — no reprogram, no DMA, no lock, no chip run |

It is `106`'s command line with `149`'s three instrument flags: the
`--chat-json` / `--chat-log` defaults are `083_longctx_chat.json` and
`083_longctx_9b.log` (`evidence/qwen9b/g6/g6_longctx_lockstep.py:301`,
`default=os.path.join(G6, "083_longctx_chat.json")`), so it replays the
24-token session `106` replayed, and `--top5 5 --continue --dump-kv 501-506`
make it print the reference's five best logits at every decode step, replay
**all 24** instead of stopping at the first disagreement, and dump the
reference region's KV rows at `501..506`. `--selfcheck` renders both per-step
arms and all three verdict lines before the 17 h starts.

**AND THE HEADER PROVES ITS OWN OPERATING POINT.** `FABLE5_RS_F` is NOT set
on this run — it is the derivation that has to speak, and line 11 says
`derived=7`. `106`'s line 9 and this run's line 9 are again identical
(`FABLE5_RS_F=unset`); line 11 is what tells them apart, which is exactly the
failure A′ was written for.

**What it can say that nothing else can.** 23 decode comparisons at
T = 504..526 — the only comparands above T = 504 — and the only end-to-end
measurement of whether `rtl/attn_core.sv:114`'s `logic signed [39:0] denom`
ever bit: positions 511-525 are `T >= 512`, where a signed 40-bit accumulator
of Q30 terms can wrap in the worst case and the reference's int64 cannot. If
the 23 tokens agree, the hazard was never live in this session and `denom`
stays a scheduled post-ship RTL fix; if they diverge at exactly T = 512,
§22.7 has found its own confirmation.

**Board etiquette, this round.** **No board session was opened.** No
reprogram, no flash, no sudo, no DMA, `--no-lock` on no command line, not one
chip run; the board still carries build_041 (`0xc973c18a`) and the
`model_9b_s1` pack, untouched. Everything numeric ran on snoke through
`evidence/qwen9b/run.sh` — `168`, `169`, `170` (three `true`s), `171` (the
replay) — and nothing numeric ran on darthplagueis.


### 22.12b B′ LANDED — **`LONGCTX_LOCKSTEP: PASS 526/526`**, 24 DECODE STEPS AT POSITIONS 502..525, AND `denom` WAS NOT LIVE IN THIS SESSION

**T**, `171`, tree `e1d0d3a` — A′'s own commit — snoke, board-free,
**17.82 h**. The `083` 24-token session replayed against `ref/seq_model` at
the DERIVED operating point, with `FABLE5_RS_F` UNSET so that the derivation
is what speaks: `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:11` is
`=== rs_f: derived=7 (tag 9b) env=unset rider=0`, and line 9 of the same log
is `106`'s line 9 character for character. The run's own summary block:

```
  replayed   526 of 526 steps in 17.82 h (121.9 s/step)
  decode     24/24 of the chip's tokens reproduced (24 decode steps replayed)
LONGCTX_LOCKSTEP: PASS 526/526
=== rc: 0
=== end: 2026-09-12T06:36:13-06:00
```

**T**, the wall clock:
`evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:623`, `replayed   526 of 526 steps in 17.82 h (121.9 s/step)`.
**T**, the decode count:
`evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:626`, `decode     24/24 of the chip's tokens reproduced (24 decode steps replayed)`.
The column-0 verdict is
`evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:637`, with `=== rc: 0`
and the end stamp beneath it. The JSON agrees and adds two numbers the log
rounds away: `fail_at` is **null** and `wall_s` is **64139.3**. The pid the
launch note recorded, 1273730, is gone from snoke.

**THE 24 DECODE STEPS, ONE ROW EACH.** Every verdict is `==`, the chip's
token is **rank 1** in the reference's own logits at every one, and 0 below
the top. The margin and its percentage are QUOTED from the log's own line,
not recomputed; the `chip's ... is rank 1 ...` line sits immediately under
each one.

| pos | ref -> chip | token | verdict | the log's own `#1-#2 margin` line | chip rank | cite |
|---|---|---|---|---|---|---|
| **502** | 760 -> 760 | 'The' | `==` | `#1-#2 margin 13336 (14.6808% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:551` |
| **503** | 20438 -> 20438 | ' passage' | `==` | `#1-#2 margin 1528 (1.8523% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:554` |
| **504** | 18253 -> 18253 | ' repeatedly' | `==` | `#1-#2 margin 1195 (0.7109% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:557` |
| **505** | 5134 -> 5134 | ' states' | `==` | `#1-#2 margin 12951 (7.1691% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:560` |
| **506** | 421 -> 421 | ' that' | `==` | `#1-#2 margin 14716 (7.2831% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:563` |
| **507** | 279 -> 279 | ' the' | `==` | `#1-#2 margin 1810 (1.8953% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:566` |
| **508** | 3177 -> 3177 | ' city' | `==` | `#1-#2 margin 18742 (18.6928% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:569` |
| **509** | 314 -> 314 | ' of' | `==` | `#1-#2 margin 81262 (36.5126% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:572` |
| **510** | 11751 -> 11751 | ' Paris' | `==` | `#1-#2 margin 102647 (45.2205% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:575` |
| **511** | 13538 -> 13538 | ' grew' | `==` | `#1-#2 margin 19481 (9.4550% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:578` |
| **512** | 494 -> 494 | ' from' | `==` | `#1-#2 margin 44782 (19.6230% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:581` |
| **513** | 264 -> 264 | ' a' | `==` | `#1-#2 margin 25841 (12.0876% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:584` |
| **514** | 16576 -> 16576 | ' settlement' | `==` | `#1-#2 margin 63019 (33.0723% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:587` |
| **515** | 383 -> 383 | ' on' | `==` | `#1-#2 margin 61246 (26.4515% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:590` |
| **516** | 449 -> 449 | ' an' | `==` | `#1-#2 margin 49871 (23.4400% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:593` |
| **517** | 12552 -> 12552 | ' island' | `==` | `#1-#2 margin 79060 (35.7282% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:596` |
| **518** | 303 -> 303 | ' in' | `==` | `#1-#2 margin 76576 (32.2731% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:599` |
| **519** | 279 -> 279 | ' the' | `==` | `#1-#2 margin 88589 (38.2988% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:602` |
| **520** | 181474 -> 181474 | ' Seine' | `==` | `#1-#2 margin 58105 (29.7165% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:605` |
| **521** | 11 -> 11 | ',' | `==` | `#1-#2 margin 3897 (3.9363% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:608` |
| **522** | 321 -> 321 | ' and' | `==` | `#1-#2 margin 10637 (5.3350% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:611` |
| **523** | 1141 -> 1141 | ' its' | `==` | `#1-#2 margin 29270 (13.3377% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:614` |
| **524** | 13959 -> 13959 | ' streets' | `==` | `#1-#2 margin 66920 (31.9890% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:617` |
| **525** | 11 -> 11 | ',' | `==` | `#1-#2 margin 65145 (27.9394% of the top logit)` | **1** | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:620` |

**The four tightest, by absolute margin**: pos **504** (1195), pos **503**
(1528), pos **507** (1810) and pos **521** (3897). **Every other step is at
or above 10,637.** The two tightest are the interesting ones: pos 503 is the
step `106` called a divergence, and at 1,528 — `1.8523% of the top logit`
— it is exactly the margin §22.11 showed a one-bit conv shift could flip
and a correct one does not. pos 504, at 1,195 and `0.7109% of the top logit`,
is tighter still and it also agrees.

**THE FOURTEEN STEPS AT T ≥ 512, AND WHAT THEY DO AND DO NOT SETTLE.**
Positions **512 through 525** — fourteen of the twenty-four — run at
T ≥ 512, which is the range §22.7 and §22.12 named for
`rtl/attn_core.sv:114`'s `logic signed [39:0] denom`: a signed 40-bit
accumulator of Q30 terms that can wrap in the worst case where the
reference's int64 cannot. **All fourteen are `==`.**

* **The first half of the statement.** By §22.12's own rule — "if the
  tokens agree, the hazard was never live in this session" — **the hazard
  was NOT live in this session**, and `denom` stays a **scheduled post-ship
  RTL fix**, not an observed defect and not an emergency. §22.7 has not
  found its confirmation: there is no divergence at T = 512 or anywhere
  above it.
* **The second half, and neither half stands without the other.** **The
  ceiling stays T < 512 BY ANALYSIS.** That bound is a WORST CASE — the sum
  wraps only when every score sits at its maximum — and one session's
  agreement at T = 512..526 is evidence that the worst case was **not
  reached**, not proof that it **cannot be**. **`171`'s PASS does not lift
  the ceiling.** Widening `denom` remains the thing that would, and it is on
  Task 16's post-ship list beside the gate-port widening.

**THE STATE COMPARISON AT T = 526 IS *NOT* MADE, and this subsection does
not imply it is.** `171`'s `--dump-kv 501-506` dumps the **REFERENCE**
region after step 526 and nothing else:
`evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:627` is
`dump-kv    the REFERENCE region's rows 501..506, layers [0, 4, 7], through g6_kv_rows.dump()`,
and the JSON's own `source` field says
`ref/seq_model.StateRegion after step 526`. **No chip readback of the whole
region at T = 526 exists to set beside it** — `083_longctx_kv_after.json`
is rows-only, taken through `g6_kv_depth.py`, not a region image — so the
deepest silicon-vs-reference STATE comparison this campaign holds is still
`161` at N = 503, where `dn_sha256` is **SAME** on both sides (§22.11).

**And `127` is NOT the missing comparand either, though it is the thing a
reader will reach for (collection-round review M-4).**
`127_15d_kv_rows_pre.json` IS a chip-side whole-region hash —
`region_sha256 3049c05d…`, `dn_sha256 eaa414de…`, §22.1 — but it was taken
on 2026-09-10 at 19:10, after the fix-round-2 and fix-round-3 chat sessions
had already run over the region, so it is the board AFTER those shallower
sessions, with only rows 500..525 surviving from the 526-step run. It is a
record of what the board held before Task 15-D touched it, not an image of
the chip's state at T = 526, and hashing it against `171`'s reference region
would compare two different histories.
What `171` adds at T = 526 is a TOKEN comparison, twenty-four of them, and
a reference-side region hash for a future chip-side one to be compared
against.

**The reference region's hashes, for that future comparison.** From
`171_longctx_lockstep_ref_rs7_kv.json` and the log's own summary lines:

| | |
|---|---|
| region | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:628` — `region     155 MiB [0x380000000,0x389b00000)  sha256 b6a681d7ed08e760c2c49b086faf102a37966d307146e0eb6e7f1db12a8be625` |
| DN alone | `evidence/qwen9b/g6/171_longctx_lockstep_ref_rs7.log:629` — `DN alone   24 MiB  sha256 38c5da24b0eb8c30bbaeba19c2356f4d6da8e265cf0db4811569abcae1e17d1d` |
| bytes | `region_bytes` 162,529,280 and `dn_bytes` 25,165,824, from the JSON |
| what it is | the REFERENCE's `StateRegion` after step 526, tagged `ref-171_longctx_lockstep_ref_rs7` — **not a board readback** |

The six K/V blocks it dumps (L0, L4, L7, kvhead 0) all read `6/6 non-zero`
at rows 501..506 on the reference side, with the exponent bytes
`[252, 252, 252, 253, 252, 252]` at L0 K — the reference writing every row
it should, above the depth `149`'s dump stopped at.

**One launch-note number is CORRECTED here, and §22.12a's launch facts are
left alone.** §22.12 and §22.12a both projected "**23** decode comparisons
at T = 504..526", counting from the `083` session's 24 ids minus one. The
run made **24**, at positions **502..525**: `--continue` replays every decode
step instead of stopping at the first disagreement, and the first decode
step is position 502, not 504. The launch subsection is the record of what
was launched and keeps its own words; this is the landed count.

**Board etiquette, this round.** **No board session was opened.** No
reprogram, no flash, no sudo, no DMA, `--no-lock` on no command line, and
not one chip run — by the collection round and by the replay alike. The
board still carries build_041 (`0xc973c18a`) and the `model_9b_s1` pack —
the bitstream unchanged since `002` and **not one weight byte re-uploaded
since `028`**, with the DDR state region as `148` and `141` between them
left it on 2026-09-10 (§15). `171` ran on snoke through
`evidence/qwen9b/run.sh`, and so did this round's superlative pair and its
closing `spec_cites`. **Nothing numeric ran on darthplagueis.**
