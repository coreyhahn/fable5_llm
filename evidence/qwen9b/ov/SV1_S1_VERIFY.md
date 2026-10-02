# SV1 — S1 VERIFIED ON THE CHIP TESTBENCH: the emitter-only overlap schedule, measured

Task SV1 took OV1's emitter-only schedule, **S1**, and ran it on the full-chip
testbench. S1 is fence-at-use, a dependency-safe reorder and redundant-MOVX
elision (`evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md` §6.1). SV1 built the
reorder pass, gated it against the reference model, and ran it as real
Verilator simulations of the shipped RTL: four seeds, both read/write-set forms.
**No RTL was changed.** The board was not touched.

## 0. HOW TO READ EVERY NUMBER BELOW

* **E** = printed by a run of this task. Each E is cited to the log line that
  printed it. Every log was written ON SNOKE through
  `evidence/qwen9b/ov/ov_run.sh`, and its header records host, tree and command.
* **D** = derived arithmetic. **Every D was computed on snoke** by
  `evidence/qwen9b/ov/sv1_derive.py` and is cited to the line of
  `evidence/qwen9b/ov/n66_derive_predictions.log` (the predictions, written
  before any chip run had landed) or `evidence/qwen9b/ov/n67_derive_measured.log`
  (the measurements) that printed it.
* **T** = transcribed from an older campaign log or document. **S** = stated
  by a source file, cited `path:line`.
* **ms/token** is the whole six-token run's cycle count ÷ 6 at 250 MHz. That
  is exactly how today's 131.138 is defined: 196,706,821 cyc for six tokens
  (**T**, `evidence/qwen9b/s4/S4_REPLAY.md:398`,
  `evidence/qwen9b/bn/BN_CENSUS.md:18`).
* **THE TB IS NOT THE BOARD.** "Board-scaled" means TB × 137.121/131.138 =
  1.04562 (**D**, `evidence/qwen9b/ov/n67_derive_measured.log:18`). That is the
  uniform-scaling *assumption* OV1 used. It is not a board measurement.

## THE VERDICT, stated once and before the details

**S1 is measured on the chip TB at 114.488 ms/token in form B and 117.959
ms/token in form A**, against 131.138 today. That is **1.1454×** and
**1.1117×**, identical on all four seeds (**D**,
`evidence/qwen9b/ov/n67_derive_measured.log:22`,
`evidence/qwen9b/ov/n67_derive_measured.log:36`).

* **The model predicted it to within +0.043 % (B) and +0.021 % (A).** The
  predictions, committed before any run landed, were 114.438 and 117.935
  ms/token (**D**, `evidence/qwen9b/ov/n66_derive_predictions.log:31`,
  `evidence/qwen9b/ov/n66_derive_predictions.log:41`). The chip realised
  99.7 % (B) and 99.8 % (A) of the predicted saving (**D**,
  `evidence/qwen9b/ov/n67_derive_measured.log:22`,
  `evidence/qwen9b/ov/n67_derive_measured.log:36`).
* **Tokens are identical on 8 of 8 runs** (four seeds × two forms), against the
  shipped artifacts' committed records (**E**, §3).
* **Board-scaled, that is 8.353 tok/s (B) and 8.108 tok/s (A), against 7.293
  today** (**D**, `evidence/qwen9b/ov/n67_derive_measured.log:23`,
  `evidence/qwen9b/ov/n67_derive_measured.log:37`).
* **Model and measurement agree on WHERE the time comes from, class by class.**
  Token 4's exposed stream wait fell 8.624 ms, against the model's 8.604 (**D**,
  `evidence/qwen9b/ov/n74_fix1_derive.log:85`). The recovered wait is in_z,
  dn_out and the DN mlp_down, exactly as OV1 said (§4).
* **What the model did not hold fixed:** the layer-command windows grew +0.069
  ms/token under the reorder. That growth more than accounts for the +0.050
  ms/token residual: +0.069 exceeds +0.050, and the measured fence wait
  coming in 0.019 ms under the model makes up the difference (+0.069 − 0.019
  = +0.050; §4.2).

## 1. WHAT RAN, WHERE, ON WHICH BINARY

| item | what | cite |
|---|---|---|
| binary | `tb/obj_dir_seq_chip_sv1/tb_seq_chip_9b_sv1`. It was built by `evidence/qwen9b/ov/sv1_build.sh` from a `git archive` snapshot of 5bb902d, whose `rtl/` and `tb/*.sv[h]` are **identical to 86c94d9**, the shipped tree. The only tb/ change is the Makefile's `TL_MDIR`/`TL_BIN` variable (`tb/Makefile:1547-1551`). sha256 8fc981fd… | **E**, `evidence/qwen9b/ov/n21_build_sv1.log:7`, `evidence/qwen9b/ov/n21_build_sv1.log:79` |
| why a snapshot | Task BM1-T1 edits `rtl/` in the same working tree. A build from the working tree could have picked up an in-flight edit; one from the snapshot cannot | — |
| runner | `evidence/qwen9b/ov/run_sv1_chip.sh`: `evidence/qwen9b/bn/run_bn_timeline.sh`'s discipline. `+seq` is the reordered stream and `+base` the shipped artifact. Tokens are read from `evidence/qwen9b/s4/S4_REPLAY.md` under the SHIPPED stem. Each run must beat today's cycle count for its seed. The acceptance logic was checked first: one GREEN and two REDs on the census's own log | **E**, `evidence/qwen9b/ov/n48_runner_dry_acceptance.log:42`, `evidence/qwen9b/ov/n48_runner_dry_acceptance.log:77`, `evidence/qwen9b/ov/n48_runner_dry_acceptance.log:109` |
| runs | nine, all detached on snoke. Four form-B controls, one form-B timeline (s1) and four form-A controls. Wall time was 7,742–8,255 s each, against the census's 8,472–8,805 s | **E**, `evidence/qwen9b/ov/n56_chip_s4_reordB_control.log:36`, `evidence/qwen9b/ov/n57_chip_s1_reordB_timeline.log:37`; **T**, `evidence/qwen9b/bn/002_control_model_9b_s1.log:20`, `evidence/qwen9b/bn/003_timeline_model_9b_s1.log:21` |
| streams | `tb/scripts/w9/model_9b_s{1..4}_reord{A,B}.e4.*`: .seq, .seqdata.bin (a byte copy), .seq.json and .chip. They are **gitignored and regenerable**, as every `.e4` in `tb/scripts/w9/` is. Their sha256s are in the reorder, gate and runner logs (for example s1 B `57ec3051…`) | **E**, `evidence/qwen9b/ov/n32_reorder_s1_B.log` |
| timeline CSV | `tb/scripts/w9/model_9b_s1_reordB.timeline.csv` is **uncommitted**, following BN1's convention for its large CSVs. Its sha256 is committed at `evidence/qwen9b/ov/sv1_timeline_model_9b_s1_reordB.csv.sha256`, and `sv1_derive.py` checks it before reading a row | **E**, `evidence/qwen9b/ov/n57_chip_s1_reordB_timeline.log:59`, `evidence/qwen9b/ov/n67_derive_measured.log:58` |

## 2. THE PASS AND ITS TWO BINDING HAZARDS

**The model is OV1's, imported rather than ported.** `ref/scripts/reorder_e4.py`
calls `evidence/qwen9b/ov/ov_census.py`'s own read/write sets, edges, list
scheduler and post-check. The schedule it emits is therefore the one OV1's S1
number is the makespan of. On every stream the loop body reproduces OV1
**exactly**:

* form B: 28,612,019 cyc (**E**, `evidence/qwen9b/ov/n32_reorder_s1_B.log:48`;
  OV1 **E**, `evidence/qwen9b/ov/n15_all_fix2.log:817`);
* form A: 29,486,120 cyc (**E**, `evidence/qwen9b/ov/n37_reorder_s1_A.log:51`;
  `evidence/qwen9b/ov/n15_all_fix2.log:781`);
* 480 of 996 MOVX elided per token (**E**,
  `evidence/qwen9b/ov/n32_reorder_s1_B.log:44`;
  `evidence/qwen9b/ov/n15_all_fix2.log:30`).

The pass reorders **all four** decode segments of each stream: three unrolled
tokens and the loop body on s1/s4, one unrolled token and the body on s2/s3.
Each segment is scheduled with its own measured windows, so the whole run is
comparable with 131.138 ms. Fences keep their count (343 per token). 200 of
them (form B) or 216 (form A) are deferred past independent work (**E**,
`evidence/qwen9b/ov/n32_reorder_s1_B.log:44`,
`evidence/qwen9b/ov/n37_reorder_s1_A.log:47`).

**Hazard (1): no MOVX, MVGO or MOVY may land on a channel whose stream is still
pending.** Two independent checks enforce it.

* **The pass's own assert.** `assert_no_pending_hazard`
  (`ref/scripts/reorder_e4.py:225`) walks every output stream statically and
  requires nothing to be pending at the JMP. It **passed on all eight streams**
  (**E**, `evidence/qwen9b/ov/n32_reorder_s1_B.log:51`,
  `evidence/qwen9b/ov/n37_reorder_s1_A.log:54`, and n34–n36, n38–n40).
* **OV1's post-check on the emitted order.** It is run on a replay of the order
  actually written, not on the scheduler's times. It found **0 violations** over
  66,023 edges (form B body; **E**, `evidence/qwen9b/ov/n32_reorder_s1_B.log:50`).
  The replay's makespan equals the scheduler's to the cycle
  (`evidence/qwen9b/ov/n32_reorder_s1_B.log:49`).
* **The model now refuses it too.** `ref/seq_model.py` asserts on a MOVX and an
  MVGO issued to a running channel (`ref/seq_model.py:923`,
  `ref/seq_model.py:945`), beside the existing MOVY refusal
  (`ref/seq_model.py:1035`).
  * Its selftest failed before the change: 1/3 hazards refused (**E**,
    `evidence/qwen9b/ov/n22_refusal_selftest_RED.log:7`).
  * It passes after it: 3/3 refused (**E**,
    `evidence/qwen9b/ov/n23_refusal_selftest_GREEN.log:13`).
  * The four **shipped** streams still gate bit-exact with the refusal armed
    (**E**, `evidence/qwen9b/ov/n24_gate_shipped_s1_refusal.log:20`, and
    n25–n27).

**Hazard (2): a FENCE drains every channel on the shipped RTL.** The pass
therefore only *defers* fences. A FENCE is placed before the first record that
needs any issued, unfenced stream (`ref/scripts/reorder_e4.py:382`).

**TDD.** The pass's selftest covers three cases on a synthetic stream: a fence
deferred, a MOVX elided and three hazards refused. It failed against a stub
(**E**, `evidence/qwen9b/ov/n28_reorder_selftest_RED.log:14`) and passes against
the pass (**E**, `evidence/qwen9b/ov/n30_reorder_selftest_GREEN.log:20`). n29
was a failed attempt, kept: its timing check was too strict and did not allow
for the JMP, which the stream must place last.

## 3. THE GATES AND THE RUNS — per seed

| seed | form | model gate (CHECKPT, tokens) | golden vs shipped | chip TB cycles / 6 tok | ms/token | ×today | tokens (chip) |
|---|---|---|---|---|---|---|---|
| s1 | B | 2358/2358, IDENTICAL (`evidence/qwen9b/ov/n33_gate_s1_reordB.log:19`) | identical except NREC/PC (`evidence/qwen9b/ov/n44_chipvec_s1_reordB.log:28`) | 171,731,320 (`evidence/qwen9b/ov/n53_chip_s1_reordB_control.log:51`) | 114.488 | 1.1454 | IDENTICAL (`evidence/qwen9b/ov/n53_chip_s1_reordB_control.log:55`) |
| s2 | B | 2358/2358 (`evidence/qwen9b/ov/n41_gate_s2_reordB.log:23`) | identical (n45) | 171,731,695 (`evidence/qwen9b/ov/n54_chip_s2_reordB_control.log:52`) | 114.488 | 1.1454 | IDENTICAL (`evidence/qwen9b/ov/n54_chip_s2_reordB_control.log:56`) |
| s3 | B | 2358/2358 (`evidence/qwen9b/ov/n42_gate_s3_reordB.log:23`) | identical (n46) | 171,731,695 (`evidence/qwen9b/ov/n55_chip_s3_reordB_control.log:52`) | 114.488 | 1.1454 | IDENTICAL (`evidence/qwen9b/ov/n55_chip_s3_reordB_control.log:56`) |
| s4 | B | 2358/2358 (`evidence/qwen9b/ov/n43_gate_s4_reordB.log:23`) | identical (n47) | 171,731,425 (`evidence/qwen9b/ov/n56_chip_s4_reordB_control.log:52`) | 114.488 | 1.1454 | IDENTICAL (`evidence/qwen9b/ov/n56_chip_s4_reordB_control.log:56`) |
| s1 | B, timeline | — | — | 171,731,320, = the control (`evidence/qwen9b/ov/n57_chip_s1_reordB_timeline.log:54`) | 114.488 | 1.1454 | IDENTICAL (`evidence/qwen9b/ov/n57_chip_s1_reordB_timeline.log:58`) |
| s1 | A | 2358/2358 (`evidence/qwen9b/ov/n49_gate_s1_reordA.log:37`) | identical (n58) | 176,938,762 (`evidence/qwen9b/ov/n62_chip_s1_reordA_control.log:52`) | 117.959 | 1.1117 | IDENTICAL (`evidence/qwen9b/ov/n62_chip_s1_reordA_control.log:56`) |
| s2 | A | 2358/2358 (`evidence/qwen9b/ov/n50_gate_s2_reordA.log:37`) | identical (n59) | 176,939,059 (`evidence/qwen9b/ov/n63_chip_s2_reordA_control.log:52`) | 117.959 | 1.1117 | IDENTICAL (`evidence/qwen9b/ov/n63_chip_s2_reordA_control.log:56`) |
| s3 | A | 2358/2358 (`evidence/qwen9b/ov/n51_gate_s3_reordA.log:37`) | identical (n60) | 176,939,059 (`evidence/qwen9b/ov/n64_chip_s3_reordA_control.log:52`) | 117.959 | 1.1117 | IDENTICAL (`evidence/qwen9b/ov/n64_chip_s3_reordA_control.log:56`) |
| s4 | A | 2358/2358 (`evidence/qwen9b/ov/n52_gate_s4_reordA.log:37`) | identical (n61) | 176,938,774 (`evidence/qwen9b/ov/n65_chip_s4_reordA_control.log:52`) | 117.959 | 1.1117 | IDENTICAL (`evidence/qwen9b/ov/n65_chip_s4_reordA_control.log:56`) |

Cycles and tokens are **E**. ms/token and ×today are **D**, from
`evidence/qwen9b/ov/n67_derive_measured.log:22-45`. Today's cycles per seed are
196,706,821 / 196,707,670 / 196,707,670 / 196,706,833 (**T**,
`evidence/qwen9b/s4/S4_REPLAY.md:398-401`). Every run's `TB_SEQ_CHIP PASS` also
compared the full architectural end state against the reordered golden. That
golden is itself identical to the shipped golden apart from the record count and
the final PC, which covers every scratch word, the XRF, TCNT and the 112 state
blocks (`evidence/qwen9b/ov/sv1_chipvec.sh`).

**Timeline control.** The timeline run gives the control's cycle count exactly
(171,731,320 twice), so the instrument is inert on this stream too (**E**,
`evidence/qwen9b/ov/n57_chip_s1_reordB_timeline.log:54`).

## 4. MODEL AGAINST MEASUREMENT

### 4.1 Token time

Token 4, the one OV1 modelled, measured 28,624,410 cyc = 114.498 ms against
OV1's 114.448. The residual is +12,391 cyc = **+0.043 %** (**D**,
`evidence/qwen9b/ov/n67_derive_measured.log:53`,
`evidence/qwen9b/ov/n67_derive_measured.log:56`). OV1 said a miss larger than
its one-τ validation error (−0.0035 %) would refute the duration model
(`evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md:726-728`). By that rule the model
is off, by 12 times its self-validation error. It is **also 99.7 % right about
the saving**. §4.2 shows where the difference sits.

### 4.2 Where the time went — per class, token 4, s1 form B (D, `evidence/qwen9b/ov/n74_fix1_derive.log:68-99`)

Exposed stream wait is the FENCE windows. "Model" is OV1's S1 form-B column
(**E**, `evidence/qwen9b/ov/n15_all_fix2.log:867-886`); its total is that
table's own ALL row, 45.789 (`evidence/qwen9b/ov/n15_all_fix2.log:885`).

**The two columns attribute the wait differently.** The measured column
charges each FENCE window to the class of the LAST-ISSUED stream it drains.
OV1's model charges each idle interval of its lane to the stream whose
readiness bound it, its binding reason (`evidence/qwen9b/ov/ov_census.py:945`, `idle_by_mv`). The two agree whenever one class's streams are the
only ones pending at a fence. They can differ when streams of several classes
are drained together. The ALL row does not depend on the attribution.

| class | today | model S1 | measured S1 | recovered: model | recovered: measured |
|---|---|---|---|---|---|
| DN in_z | 2.754 | 0.000 | 0.006 | 2.754 | 2.748 |
| DN dn_out | 2.754 | 0.789 | 0.745 | 1.965 | 2.009 |
| DN mlp_down | 8.251 | 6.561 | 6.562 | 1.690 | 1.689 |
| GQA mlp_down | 2.750 | 2.194 | 2.195 | 0.556 | 0.555 |
| GQA o_proj | 0.918 | 0.369 | 0.369 | 0.549 | 0.549 |
| **all 16 classes** | **54.393** | **45.789** | **45.770** | **8.604** | **8.624** |

* **The model got the overlap right, class by class.** The measured recovered
  wait matches the modelled one to within 0.05 ms in every class. The largest
  gap is dn_out, where the measured recovery is 0.044 ms *more* than modelled.
  The top three (in_z, dn_out, DN mlp_down) are OV1's own top three
  (`evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md:91-92`).
* **The MOVX elision is exactly as modelled.** Lane work in MOVX fell 21.043 →
  12.948 ms, which is −8.095 ms (**D**,
  `evidence/qwen9b/ov/n74_fix1_derive.log:95`). That is OV1's 8.095 to the
  microsecond (`evidence/qwen9b/ov/n15_all_fix2.log:30`).
* **What the model got wrong.** The model holds every non-FENCE window fixed
  under the reorder, and one class of window moved: **CMD windows grew +0.069
  ms/token** (42.526 → 42.594; **D**,
  `evidence/qwen9b/ov/n74_fix1_derive.log:89`). MOVY, MVGO, LDC and CSRWR
  did not move beyond the third decimal.
  * The +0.069 ms of CMD growth is larger than the +0.050 ms residual. The
    measured fence wait came in 0.019 ms under the model (45.770 against
    45.789; **D**, `evidence/qwen9b/ov/n74_fix1_derive.log:86`), which
    accounts for the difference.
  * This is the first measurement of what OV1 §9 item 4 left open. **Measured
    (D): with streams running under them, the layer-command windows sum 0.069
    ms/token higher.** *Inferred, not measured:* the mechanism. The candidate
    paths are the burst fabric and the single-ported scratch that the
    commands share with the mover. No instrument here separates them. The
    aggregate costs 0.16 % of the token.

### 4.3 The s2/s3 record-window caveat

Seeds 2 and 3 have one unrolled token plus a five-step loop. They have no
measured timeline of their own. Their segments take seed 1's windows through an
identical record skeleton (**E**, `evidence/qwen9b/ov/n34_reorder_s2_B.log`).
Their predictions therefore carry seed 1's per-token windows, which is why the
cycles outside any token come out at −8,830 for s2/s3 against +15,360 for s1
(**D**, `evidence/qwen9b/ov/n66_derive_predictions.log:31-37`).

That is a 0.004 % bookkeeping offset in the prediction, not a measurement. The
residuals it leaves, +0.043 % on every seed (**D**,
`evidence/qwen9b/ov/n67_derive_measured.log:25`), show it did not matter. The
schedule's correctness never depended on the windows: the assert, the
post-check, the gate and the chip TB all check the order itself.

## 5. NOT ESTABLISHED

1. **No board number.** Every figure is the TB's. The board-scaled 8.353 / 8.108
   tok/s assume that the TB/board ratio of 1.04562 holds under overlap.
   Nothing here tests that.
2. **What the TB's memory model does and does not include.**
   * **Included.** `tb/seq_mem_file.sv` is a file-backed model: `$fseek`/`$fread`
     one beat at a time (`tb/seq_mem_file.sv:10`). It has fixed first-word
     latencies, `WLAT = 40` for weights and `DDRLAT = 32` for records, LDC and
     EMB (`evidence/qwen9b/bn/BN_CENSUS.md:1028-1029`).
   * **Not included.** It has **no refresh, no bank conflict and no read/write
     turnaround**. Its weight path is 10.0 % faster than the rate the board's
     own measurements imply (**T**,
     `evidence/qwen9b/bn/BN_CENSUS.md:706-713`).
3. **DDR contention is only partly answered.**
   * **What the TB now measures.** Overlap does not slow the weight streams (the
     fence waits recovered as modelled, §4.2), and layer commands slow by 0.069
     ms/token.
   * **What it cannot see.** The channel-3 contention OV1 §9 item 4 named is out
     of reach. In the TB the DDR state region is a SEPARATE `seq_mem_file`
     instance from the per-channel weight models (`tb/tb_seq_chip.sv:420-430`,
     `tb/tb_seq_chip.sv:442-444`). SLD/SST traffic therefore never competes
     with channel 3's weight stream here, while on the board it shares that
     channel's DDR (`sw/hwmap.py:603`).
   * **The risk stays bounded, not measured.** OV1's crude bound is that state
     DMA on the board could cost up to 29–37 % of S1's saving
     (`evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md:753-768`).
4. **S1 only.** R1–R3 need RTL and are untouched. Sub-chunking (OV1 §5) was not
   tried.
5. **One prompt length per seed pair, six tokens, T ≈ 6.** The T → 511 behaviour
   is OV1's model estimate and is not measured here.
6. **The schedule is OV1's heuristic.** Neither form's schedule is optimal. Form
   B relies on the internal-resource list that OV1 §2.3 could not prove
   complete. Eight token-identical runs and 16 bit-exact gates (8 streams, plus
   the 4 shipped streams under the new refusal and the 4 goldens) are strong
   evidence of form B's correctness on these inputs, not a proof for all
   inputs.

## 6. PROVENANCE AND DISCLOSURES

* Logs n21–n76 are in `evidence/qwen9b/ov/`. Each was committed by explicit
  path as it landed. The ledger is `.superpowers/sdd/2026-09-24-overlap/progress.md`.
* Several logs are stamped `+dirty`. Before BM1 committed, the only dirty
  entries were Task BM1-T1's in-flight files under `evidence/qwen9b/bm/` and
  `rtl/`. None of those are inputs to these runs: the binary came from a
  snapshot. The RED/GREEN selftest logs n22, n28–n30 were run with the file
  under test uncommitted, as TDD requires, and their dirty lines name it.
* **One rule slip.** python3 was invoked once on darthplagueis. A heredoc of
  perl text went to python3's stdin and failed on a syntax error before the
  perl edit ran. Nothing numeric happened there.
* n29 (a selftest check too strict) and n31 (stopped by an over-strict ARG
  assert on XRF-indirect ARG writes) are kept, not overwritten.
* **`evidence/qwen9b/ov/n29_reorder_selftest_GREEN.log` has rc 1 despite its
  name.** It was a failed GREEN attempt, disclosed and kept rather than
  renamed. The passing GREEN is n30.
* **Fix round 1.**
  * **The safety checks now raise explicitly** rather than via `assert`, so
    `python -O` cannot strip them. The MOVX/MVGO refusals and, as a one-line
    consistency fix, the pre-existing MOVY refusal raise `RunningChannelError`
    (`ref/seq_model.py:455`). Every check of the reorder pass raises
    `ReorderError` or `HazardError`.
  * **Proof.** The refusal selftest, now with channel-1 cases, passes 5/5
    (**E**, `evidence/qwen9b/ov/n75_fix1_model_selftest_GREEN.log`). It also
    passes under `python -O` (**E**,
    `evidence/qwen9b/ov/n76_fix1_refusal_under_O.log`), as does the reorder
    selftest (**E**, `evidence/qwen9b/ov/n71_fix1_reorder_selftest.log`).
    Shipped s1 and reordered s1 form B re-gate 2358/2358 with tokens
    identical (**E**, `evidence/qwen9b/ov/n72_fix1_gate_shipped_s1.log:31`,
    `evidence/qwen9b/ov/n73_fix1_gate_s1_reordB.log:31`).
  * **A finding outside SV1's changes.** The FULL model selftest under `-O`
    fails in a PRE-EXISTING W8 SHAPE assert that `-O` strips (**E**,
    `evidence/qwen9b/ov/n70_fix1_model_selftest.log`). `ref/seq_model.py`
    therefore still relies on `assert` elsewhere. That is not changed here.
  * **The model-total figures changed.** 8.606 → 8.604 and 0.018 → 0.019 now
    use n15's own ALL total (`evidence/qwen9b/ov/n74_fix1_derive.log:85-86`).
    No measured number changed.
