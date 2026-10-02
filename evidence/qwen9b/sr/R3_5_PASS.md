# R3-5 — the pass emits a real MOVX broadcast (`--rtl r3`)

Task R3-5 of the R3 campaign (MOVX broadcast, form (a); plan
`docs/superpowers/plans/2026-09-29-r3-broadcast.md`, Task R3-5). The contract
is `docs/SEQ_ISA.md` §B17.3 (the per-destination running rule at
`docs/SEQ_ISA.md:1644`, the admission at `docs/SEQ_ISA.md:1657`); the validator
is R3-2's (`evidence/qwen9b/sr/R3_2_VALIDATOR.md`), the model R3-3's
(`evidence/qwen9b/sr/R3_3_MODEL.md`), the one-window pricing R3-4's
(`evidence/qwen9b/sr/R3_4_COST.md`). Started from a65f87c (HEAD had moved to
ce2532c, R3-0's fix round, which touches none of this task's files). Every run
on snoke through `evidence/qwen9b/sr/sr_run.sh`, logs n2700–n2741. Labels:
**E** printed by a committed run, **D** derived by a committed script run on
snoke.

## 1. What changed, by function

`ref/scripts/reorder_e4.py`, **zero line drift**: the R3 block sits after
every line any document cites and before the `__main__` guard
(`ref/scripts/reorder_e4.py:1219-1714`); the existing functions reach it
through 15 one-line rewrites in place.

| where | what |
|---|---|
| `ref/scripts/reorder_e4.py:1278-1280` | RTLS / CAPS_OF / DEPTH gain r3 = {R1,R2,R3}, depth 2 (module level, before any call; lines 130-137 untouched) |
| `ref/scripts/reorder_e4.py:243` | assert_no_pending_hazard's channel goes through _r3_chan (`ref/scripts/reorder_e4.py:1284`): a broadcast MOVX is checked against EVERY pending channel's x range (HazardError naming the channel), any other channel field of 4 or more is refused by name. Today's line filed a broadcast under channel 15 and checked nothing (plan case (h)) |
| `ref/scripts/reorder_e4.py:303`, `ref/scripts/reorder_e4.py:321` | schedule_segment: after ov_census.build_edges, _r3_merge (`ref/scripts/reorder_e4.py:1431`) returns None below r3; at r3 it merges and S carries its bookkeeping |
| `ref/scripts/reorder_e4.py:357` | order_and_fences: r3 takes r1/r2's masked-FENCE path (the carrier's stream-edges name all four channels' readers, so the mask follows) |
| `ref/scripts/reorder_e4.py:425` | replay's post-check adds the per-destination XWIN rule (_r3_post / _r3_xcheck, `ref/scripts/reorder_e4.py:1471-1506`) when the segment carries broadcasts; r0-r2 unchanged |
| `ref/scripts/reorder_e4.py:559` | emit_segment: the carrier's record becomes the broadcast (flags[7:4] = 0xF) through _r3_rec (`ref/scripts/reorder_e4.py:1509`); its target is banked()'s bank start word (0 / 1536) |
| `ref/scripts/reorder_e4.py:664` | reorder refuses an INPUT carrying a broadcast, by name (_r3_input, `ref/scripts/reorder_e4.py:1314`) — before ov_census's per-channel elision key would KeyError on channel 15 (`evidence/qwen9b/ov/ov_census.py:669-674`) |
| `ref/scripts/reorder_e4.py:720` | the r2 report (predict()'s pred_mk beside replay_mk, the banks) also runs at r3 |
| `ref/scripts/reorder_e4.py:739` | per segment, _r3_seg (`ref/scripts/reorder_e4.py:1548`): the consumer assert, the per-destination post-check of the SCHEDULE, the counts |
| `ref/scripts/reorder_e4.py:783`, `ref/scripts/reorder_e4.py:801` | admission: r3 keeps r2's refused-at-{R1} check; _r3_admit (`ref/scripts/reorder_e4.py:1576`) requires REFUSED at {R1,R2} whenever a broadcast is present |
| `ref/scripts/reorder_e4.py:869`, `ref/scripts/reorder_e4.py:872` | write_out: r3 records r2's fields plus (_r3_meta, `ref/scripts/reorder_e4.py:1596`) broadcasts / siblings_merged / forced / unicast_left_groups / unicast_left_movx / refused_at_r1r2, and requires shape_isa in the manifest; seq_isa 2.3, caps [R1, R2, R3] |
| `ref/scripts/reorder_e4.py:1083`, `ref/scripts/reorder_e4.py:1192` | --selftest runs selftest_r3 (`ref/scripts/reorder_e4.py:1682`, its four-channel synthetic at `ref/scripts/reorder_e4.py:1643`); main prints the r3 lines (_r3_print) |

**The broadcast node** (_r3_groups `ref/scripts/reorder_e4.py:1401`, _r3_merge).
After OV1's own edges at depth 2 (r2's), each run of MOVX nodes (a matvec's
MOVX, XOPs allowed between — ov_census.segment_matvecs' cut) is split by
(source range, length) over its LIVE MOVX; a key group with exactly one MOVX on
each of channels 0..3 becomes ONE node. The carrier is its first MOVX (the
census's carrier); its window is the carrier's; its done- and stream-edges are
the union of the four siblings' (latest-of-four,
`evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md:771-773`); every edge onto a
sibling is redirected to it; the siblings leave the live set. Any other key
group stays unicast and is counted (unicast-left groups and MOVX).

**The bank** (_r3_xwin, `ref/scripts/reorder_e4.py:1330`). The model has no
bank-forcing logic and does not name a disagreeing consumer (R3-3's review), so
the pass forces the bank. It re-walks the XWIN part of ov_census.build_edges
with each broadcast written at its carrier on all four channels. The bank is
channel 0's census bank. A channel whose own rotation would have picked the
other bank is FORCED: its WAR stream-edges come from its last readers of the
forced bank (the added edge), and its XWIN writer and rotation state follow
the forced bank, so its consuming MVGO's XBANK is the forced bank and its later
rotation continues from there. A K > 6144 vector spans both banks on every
channel (word 0) and forces nothing. The re-walk is a port of the census's
rule, so it is **checked on every r3 segment**: re-walked with no merge, it
must reproduce build_edges' XWIN edges and banks exactly, or the pass refuses.

**The consumer assert** (assert_bcast_consumers,
`ref/scripts/reorder_e4.py:1523`). Every MVGO whose x the re-walk says a
broadcast wrote must come after that broadcast and carry XBANK = its window.
Otherwise it raises HazardError naming both records. It runs on every emitted
segment: 1,370 consumers per segment on the 9B streams (E:
`evidence/qwen9b/sr/n2720_r3_5_reorder_s1_B_r3.log:51`).

**Flags, not copies** (plan I-5). `evidence/qwen9b/sr/sr11b_gate.sh:28` takes
the caps as an optional third argument (default R1,R2, today's value; the
usage lines rewritten in place). `evidence/qwen9b/sr/sr11b_r2_check.py` takes
`--caps` and `--want-manifest-caps` (defaults R1,R2). With a non-default set,
the stream must be REFUSED at EVERY proper subset, and the refusal at the set
minus R3 must name the BROADCAST. Its default output is byte-identical to
today's: 33 body lines against R3-3's n2521 (E:
`evidence/qwen9b/sr/n2736_r3_5_r2_check_default_compare.log:6`), and lines
1-41 of the file, which `:36-41` cites, did not move. `evidence/qwen9b/ov/ov_census.py`:
**no change** (its printed rows do not move; the pass never feeds it a
broadcast, TDD (h)).

New files: `evidence/qwen9b/sr/r3_pass_tdd.py` (the TDD — a new file, not a
group on `evidence/qwen9b/sr/sr11b_pass_tdd.py`, whose cases are r2-specific
throughout: two-channel synthetics, the r2 cost correction, base 99c13ce. It
is imported for its two-channel synthetic and stub engine),
`evidence/qwen9b/sr/r3_5_regen.sh`, `evidence/qwen9b/sr/r3_5_pin_compare.sh`,
`evidence/qwen9b/sr/r3_5_derive.py`, this document.

## 2. RED then GREEN

| run | tree | result |
|---|---|---|
| n2700 RED | ec7c2be (the TDD committed, the pass at base) | 36 PASS / 30 FAIL; every lettered case (a)-(i) has a failure (E: `evidence/qwen9b/sr/n2700_r3_5_pass_tdd_RED.log:365-367`) |
| n2701 GREEN | a7dd4ed (implementation dbcb41d) | 66 PASS / 0 FAIL (E: `evidence/qwen9b/sr/n2701_r3_5_pass_tdd_GREEN.log:116-118`) |

The cases (the file's docstring has them in full):
* (a) one broadcast per four-live-MOVX matvec, at 1536 / 0 / 1536, with
  replay no slower than r2. The one-channel `_synthetic` emits none, is
  counted unicast-left, and is byte-identical to its r2 output.
* (b) the carrier's edges are the union of the siblings' r2 edges, and it
  starts after the LATEST of the four channels' readers.
* (c) the forced case: ONE forced node (channel 3, bank 1 → 0), the edge from
  channel 3's last bank-0 reader added, and the model at {R1,R2,R3} running it
  to the r0 output's final state.
* (d) differing sources stay four unicast MOVX, counted.
* (e) the hazard assert, per destination. A broadcast hand-hoisted above
  channel 3's FENCE is refused naming mv3; R3-2's M1 row is refused.
* (f) VALID only at {R1,R2,R3}; the first refusal at {R1,R2} is the broadcast.
* (g) r0/r1/r2 on five synthetics × two forms: stream, checkpoints and
  manifest bytes equal to the pass at a65f87c; the real s1 at r0/r1/r2
  regenerates its three pins; the r3 manifest fields.
* (h) chan 0xF on every channel-keyed path, by name.
* (i) the forced channel's MVGO XBANK is the forced bank, its rotation
  follows, and the consumer assert names a flipped consumer.

The TDD was corrected once after RED, before GREEN (commit 07bdb1e,
test-only). Case (b) mapped only the group under test's siblings. Case (c)/(i)
assumed a matvec's MVGOs follow its broadcast, but the pass hoists C's
broadcast above B's. Both now use an independent XWIN walk of the emitted
order and a program-order intent check. The RED stands: at ec7c2be every
lettered case failed on the missing `--rtl r3` or chan-0xF handling.

(g) is a regression guard: it compares the base with itself at RED. Its r3
row (the manifest) is what failed there.

## 3. Regressions (unmoved)

* `reorder_e4.py --selftest` PASS, including the static group and the new r3
  group (E: `evidence/qwen9b/sr/n2702_r3_5_reorder_selftest.log:30-32`).
* `sw/chat_seq.py --selftest` 407/1, the known [22] baseline (E:
  `evidence/qwen9b/sr/n2703_r3_5_chat_seq_selftest.log:40`).
* Boardfree 2840/0, 85/0, 407/1 (E:
  `evidence/qwen9b/sr/n2704_r3_5_boardfree.log:66`,
  `evidence/qwen9b/sr/n2704_r3_5_boardfree.log:112`,
  `evidence/qwen9b/sr/n2704_r3_5_boardfree.log:143`).

## 4. r0 / r1 / r2 byte-identical on the real streams (step 4)

The twelve pinned streams (r0: SV1 n32/n34/n35/n36; r1: SR4 n410-n413; r2:
SR11b n1161-n1164) were regenerated with their recipes (form B, CSV windows)
into the NEW scratch directory `tb/scripts/w9_r3regen/`. The first run refuses
an existing directory and creates it (E:
`evidence/qwen9b/sr/n2705_r3_5_regen_s1_B_r0.log:11`); every run asserts its
`--out` resolves outside `tb/scripts/w9/` (E:
`evidence/qwen9b/sr/n2705_r3_5_regen_s1_B_r0.log:12`). The pins were read
read-only.

**12/12 FULL sha256 identical**, both the `.seq` and its manifest's
stream_sha256 (E: `evidence/qwen9b/sr/n2717_r3_5_pin_compare.log:84`;
per stream at `evidence/qwen9b/sr/n2717_r3_5_pin_compare.log:12-83`). The
r1/r2 manifests are byte-identical too. The four r0 manifests differ from
SV1's pinned manifests only by the `"cost": "csv"` key, which S1P's
write_out added after SV1 wrote those pins (`ref/scripts/reorder_e4.py:857`).
That difference predates R3-5, and TDD (g) shows the base pass writes the same
manifest bytes. The `.seqdata.bin` copies are identical. The scratch directory
was deleted after the logs, which carry every hash, were committed (423603f).

## 5. The r3 streams (step 5)

`FABLE5_MODEL=9b FABLE5_RS_F=7 ref/scripts/reorder_e4.py --in tb/scripts/w9/model_9b_s{k}.e4 --out tb/scripts/w9/model_9b_s{k}_reordB_r3.e4 --form B --cost csv --rtl r3 --stats`
(k = 1..4; none existed before, and `--out` refuses to overwrite).
Regenerated a second time into a scratch directory with identical shas
(n2724–n2727; the scratch was deleted). POSTCHECK 0 violations; the whole-stream
hazard assert passed.

| stream | FULL sha256 (pinned here) | records | broadcasts | forced | unicast-left | cite |
|---|---|---|---|---|---|---|
| model_9b_s1_reordB_r3 | 3e77e57ca39452b987d3acea708c5daf40f6def43a9bf35524caf1d47e51d3ff | 159,176 | 516 (4 seg × 129) | 0 | 0 | `evidence/qwen9b/sr/n2720_r3_5_reorder_s1_B_r3.log:61` |
| model_9b_s2_reordB_r3 | 4584810a1f340c9dd8ea2510dd00d5e1767d219a1693fd26bd39cdaa3db03012 | 79,609 | 258 (2 × 129) | 0 | 0 | `evidence/qwen9b/sr/n2721_r3_5_reorder_s2_B_r3.log:41` |
| model_9b_s3_reordB_r3 | b282ca19b6729e65052f95ea096d5087a18fe99cd2bc8a89291403668f0dd4c8 | 79,609 | 258 (2 × 129) | 0 | 0 | `evidence/qwen9b/sr/n2722_r3_5_reorder_s3_B_r3.log:41` |
| model_9b_s4_reordB_r3 | 735a73882ecaad2cfe183debdd25e971f28d500ba03f9eefb1b58d65450f23f4 | 159,176 | 516 (4 × 129) | 0 | 0 | `evidence/qwen9b/sr/n2723_r3_5_reorder_s4_B_r3.log:61` |

The second generation matched every sha (E:
`evidence/qwen9b/sr/n2724_r3_5_reorder_s1_B_r3_again.log:61`,
`evidence/qwen9b/sr/n2725_r3_5_reorder_s2_B_r3_again.log:41`,
`evidence/qwen9b/sr/n2726_r3_5_reorder_s3_B_r3_again.log:41`,
`evidence/qwen9b/sr/n2727_r3_5_reorder_s4_B_r3_again.log:61`).

### 5.1 Broadcast count against the census (SR16 §3)

The census counts 129 carriers and 387 siblings per token
(`evidence/qwen9b/sr/n1600_sr16_r3_census.log:19-20`). The pass emits
**129 broadcasts, 387 siblings merged, 0 forced and 0 unicast-left in every
segment of every stream: AS THE CENSUS**, +0 / +0 (**D**:
`evidence/qwen9b/sr/n2737_r3_5_derive.log:35`). "0 forced" means every
channel's own census rotation already agreed with channel 0's at every
broadcast: each live matvec loads all four channels, so the four rotations
never diverge. The census inferred bank forcing and did not model it; here it
is modelled, and it costs nothing on these streams.

### 5.2 Predicted body cycles, corrected convention (what R3-7 anchors on)

| body (every stream: same template windows, tok 4) | r2 (SR11b) | r3 (this task) | saving |
|---|---|---|---|
| replay_mk, census convention | 26,146,927 (`evidence/qwen9b/sr/n1165_reorder_s1_B_r2.log:50`) | **24,102,767** (`evidence/qwen9b/sr/n2720_r3_5_reorder_s1_B_r3.log:49`) | 2,044,160 |
| pred_mk, SR11b's corrected convention (reorder_e4.predict) | 26,183,590 (`evidence/qwen9b/sr/n1165_reorder_s1_B_r2.log:56`) | **24,139,430** (`evidence/qwen9b/sr/n2720_r3_5_reorder_s1_B_r3.log:59`) | 2,044,160 |

(D: `evidence/qwen9b/sr/r3_5_derive.py`, run as n2737; per stream at
`evidence/qwen9b/sr/n2737_r3_5_derive.log:11-34`.)

* **The census cross-check holds exactly.** The r3 body replay is the census
  R3 row, 24,102,767 (`evidence/qwen9b/sr/n1600_sr16_r3_census.log:26`),
  +0. The census-convention saving is R3-4's 2,044,160
  (`evidence/qwen9b/sr/n2606_r3_4_derive.log:24`), +0. The real node's
  latest-of-four edges and bank rules cost 0 cycles here, as SR16's R3lat
  sensitivity said (`evidence/qwen9b/sr/n1600_sr16_r3_census.log:32`).
* **The corrected convention moves by the same amount.** The pred − replay
  excess is +36,663 at r3 and at r2 (FENCE records, tails and the CMD residual
  are unchanged: the broadcast removes MOVX windows, not FENCEs). So the
  corrected saving is also 2,044,160 cyc/token. R3-4's note that "the pass's
  real node is expected to move it" is **not borne out**: the real node moved
  neither convention. All of this is MODEL, the census's one-window pricing
  (R3-4); the chip TB tests it (R3-9b).
* Per segment, s1 and s4 predict 24,124,425 / 24,129,395 / 24,134,391 /
  24,139,430; s2 and s3's two segments predict 24,134,391 / 24,139,430 (E:
  `evidence/qwen9b/sr/n2720_r3_5_reorder_s1_B_r3.log:59`,
  `evidence/qwen9b/sr/n2721_r3_5_reorder_s2_B_r3.log:39`).

### 5.3 Admission, through the validator (not a self-check)

`evidence/qwen9b/sr/sr11b_r2_check.py --caps R1,R2,R3` checks, on all four:
sha = manifest; VALID at {R1,R2,R3}; REFUSED at {R1,R2}, {R1,R3}, {R2,R3},
{R1}, {R2}, {R3} and {}, the refusal at {R1,R2} being the broadcast record
(rec 53); the range-aware hazard assert; manifest caps [R1, R2, R3], seq_isa
2.3 → SR11B_R2_CHECK: PASS (E:
`evidence/qwen9b/sr/n2730_r3_5_r3_check.log:58`, the {R1,R2} refusal at
`evidence/qwen9b/sr/n2730_r3_5_r3_check.log:8`). The pass's own admission
agrees (E: `evidence/qwen9b/sr/n2720_r3_5_reorder_s1_B_r3.log:48`,
`evidence/qwen9b/sr/n2720_r3_5_reorder_s1_B_r3.log:50`). Every manifest keeps
shape_isa (write_out refuses an r3 manifest without it).

### 5.4 The model gate, 4 seeds, tokens identical

`evidence/qwen9b/sr/sr11b_gate.sh <stem> <base> R1,R2,R3` (the model gate at
the named caps, with every running-range and unwritten-read refusal armed; the
wrapper sets `FABLE5_MODEL=9b FABLE5_RS_F=7`). The four ran in parallel on
snoke, on the clean committed tree 423603f.

| stream | CHECKPT | TOKENS (vs the shipped reference) | verdict | cite |
|---|---|---|---|---|
| s1 | 2358/2358 ALL BIT-EXACT | IDENTICAL [2614, 314, 279, 369, 11751, 13] | SEQ GATE: PASS, rc 0 | `evidence/qwen9b/sr/n2731_r3_5_gate_s1_reordB_r3.log:17-24` |
| s2 | 2358/2358 ALL BIT-EXACT | IDENTICAL [279, 264, 854, 11, 303, 264] | SEQ GATE: PASS, rc 0 | `evidence/qwen9b/sr/n2732_r3_5_gate_s2_reordB_r3.log:17-24` |
| s3 | 2358/2358 ALL BIT-EXACT | IDENTICAL [313, 430, 2510, 198, 1445, 27180] | SEQ GATE: PASS, rc 0 | `evidence/qwen9b/sr/n2733_r3_5_gate_s3_reordB_r3.log:17-24` |
| s4 | 2358/2358 ALL BIT-EXACT | IDENTICAL [11, 0, 271, 803, 369, 498] | SEQ GATE: PASS, rc 0 | `evidence/qwen9b/sr/n2734_r3_5_gate_s4_reordB_r3.log:17-24` |

**4/4.** Each gate's token list equals the r2 stream's gate token list, R3-3's
n2513–n2516 (`evidence/qwen9b/sr/n2513_r3_3_gate_s1_reordB_r2.log:21`,
`evidence/qwen9b/sr/n2514_r3_3_gate_s2_reordB_r2.log:21`,
`evidence/qwen9b/sr/n2515_r3_3_gate_s3_reordB_r2.log:21`,
`evidence/qwen9b/sr/n2516_r3_3_gate_s4_reordB_r2.log:21`). The model replays
every broadcast exactly, with no RunningChannelError and no
UnwrittenReadError. This is the proof that the forced-bank rule and the
consumer assert held on the real streams: a consumer reading a stale intact
vector would have broken the bit-exact compare.

## 6. Citations and drift

The layout is zero-drift, and no cited line moved: the o3 check reports **0
drifted, 0 missing** over 33 citations into the three edited files (E:
`evidence/qwen9b/sr/n2740_r3_5_drift_check.log`). It also reports 5
"unresolved" citations. These are the cited lines R3-5 rewrote **in place**:
`ref/scripts/reorder_e4.py:243`, `ref/scripts/reorder_e4.py:357`,
`ref/scripts/reorder_e4.py:720`, `ref/scripts/reorder_e4.py:783` and
`ref/scripts/reorder_e4.py:801`, cited by the plan,
`evidence/qwen9b/sr/SR11b_R2_PASS.md` and `evidence/qwen9b/sr/SR4_R1_MODEL.md`.
Each line still holds the statement those documents describe, now extended to
r3, so no repair is needed and no `--fix` was run. spec_cites over those three
documents passes (E:
`evidence/qwen9b/sr/n2741_r3_5_spec_cites_affected_docs.log`). The same holds
for `evidence/qwen9b/sr/sr11b_gate.sh:28` and `evidence/qwen9b/sr/sr11b_gate.sh:32`
(the CAPS line and the gate call, rewritten in place and unmoved) and for
`evidence/qwen9b/sr/sr11b_r2_check.py:36-41`, which is unmoved.

## 7. Judgment calls

1. **A re-walk of the census's XWIN rule, not an edit of ov_census.** The
   forced bank must change a channel's rotation state mid-walk, and
   build_edges has no hook for that. ov_census stays unchanged (its rows must
   not move). The port is guarded on every r3 segment: with no merge it must
   reproduce build_edges' XWIN edges and banks exactly, or the pass refuses.
2. **Siblings leave the live set through the `redundant` flag.** That is the
   flag ov_census.schedule and the pass already use to drop a node. The
   elision count (`movx_elided`, build_edges' own) is unchanged, and the
   merged count is reported separately (siblings_merged).
3. **Key groups within a run.** A run is split by (source range, length). A
   group with exactly one MOVX per channel 0..3 merges; every other group
   (1–3 MOVX, a repeated channel, or a differing source) is unicast-left and
   counted. Carrier = the group's first MOVX, the census's.
4. **The consumer assert is node-level.** Which broadcast a MVGO reads is the
   pass's knowledge (the re-walk), not the stream's, because a later
   broadcast may be hoisted between a matvec's MVGO groups. So the pass
   records (MVGO, broadcast) pairs and asserts them on the emitted records
   (assert_bcast_consumers). The stream-level assert_no_pending_hazard checks
   the ranges per destination. The TDD adds an independent emitted-order
   XWIN walk (r3_pass_tdd.xwalk / intent_mismatch). The model gates are the
   final proof.
5. **sr11b_r2_check's refused sets.** With a non-default --caps, every proper
   subset is checked, not only the {R1,R2} / {R1} / {} ladder, and the
   refusal at caps − {R3} must name the broadcast. The default path is
   literally unchanged.
6. **Step 4 covers r0 too.** The addendum lists the r0 pins, so 12
   regenerations were run, not the plan's 8. The logs are n2705–n2716 and the
   compare is n2717, one more than the plan's n2705–n2712.
7. **The scratch directory is not gitignored**, so the step-4 logs stamp
   `+dirty` for `?? tb/scripts/w9_r3regen/` alone, plus the concurrent R3-8's
   tb/ and rtl/ edits. None of those is an input to the pass. The same
   concurrent edits stamp n2701–n2704 and n2737–n2741. The r3 stream
   generations (n2720–n2727), the r3 check (n2730) and the model gates
   (n2731–n2734) ran on a clean committed tree (423603f).
8. **A stray no-op log.** A shell-quoting slip wrote a log named n273 (cmd: true)
   before the gates were launched. It was deleted uncommitted and holds no
   evidence.

## 8. What is NOT established

* That the RTL executes a broadcast as the model does (R3-9), or the speed
  (R3-9b). Every cycle number above is MODEL (the census's windows and R3-4's
  one-window pricing).
* That the four r3 streams' saving survives DMA-queue stalls in the new order,
  which an order-only rule cannot predict (the placement band, R3-7).

## 9. Logs

n2700 RED; n2701 GREEN; n2702 selftest; n2703 chat_seq; n2704 boardfree;
n2705–n2716 the scratch regenerations; n2717 the pin compare; n2720–n2723 the
r3 streams; n2724–n2727 the determinism reruns; n2730 the r3 admission check;
n2731–n2734 the model gates; n2735/n2736 the check's default output against
n2521; n2737 the derivation; n2740 the o3 drift check; n2741 spec_cites over
the documents that cite the rewritten lines; n2799 spec_cites LAST over this
document.
