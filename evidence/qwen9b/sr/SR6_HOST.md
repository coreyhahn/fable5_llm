# SR6 — the host side for R1: the device's capabilities in every validation; `--seq-rtl`

Task SR6 of the sequencer RTL round (`docs/superpowers/plans/2026-09-27-seq-rtl-round.md`).
It is host code only. There was **no RTL change, no build and no board
action**: every device read below is a MOCK of the SEQ window. Every run was
on snoke through `evidence/qwen9b/sr/sr_run.sh`, in log block n600–n699.

**Verdict.**
* The device's capability set is now read once and used in every host
  validation of a stream. It comes from SEQ_CAPS (SEQ 0x64) through
  hwmap.seq_caps_set; 0xDEADC0DE, what build_041/042 read, gives the empty
  set. This covers `sw/seq_run.py`'s three validation sites and
  `sw/chat_seq.py`'s two. An r1 stream loads on a mock that reads
  0xFAB1CA01. It is refused, before any DMA, on a mock that reads 0xDEADC0DE,
  whatever its manifest says.
* **Test-first.** RED was 12 passed / 26 failed
  (`evidence/qwen9b/sr/n600_sr6_host_tdd_RED.log:153`). GREEN is 42 passed /
  0 failed (`evidence/qwen9b/sr/n603_sr6_host_tdd_GREEN.log:125`), after one
  failed GREEN attempt (§3).
* **r1 images (E).** They are pinned: lite `99991122…` (39,314 records) and
  full `bf115a04…` (40,173 records). Their static-model makespans are
  **25,195,119 / 27,135,354 cycles** (`evidence/qwen9b/sr/n601_r1_pins.log:9`,
  `evidence/qwen9b/sr/n601_r1_pins.log:15`). These are this lineage's own
  numbers, **not n120's 27,136,513**. With `--seq-rtl r1`, the B6 exact
  replay passes: tokens and state are identical, 540.0 s
  (`evidence/qwen9b/sr/n608_chat_seq_r1_reorder_check.log:21`).
* **Default unchanged.** r0 regenerates the S1P form-B pins IDENTICAL
  (`evidence/qwen9b/sr/n601_r1_pins.log:20-21`).
* **Boardfree** is 2820/0, 85/0, 407/1 [22] (§4). seq_run gained 10 checks;
  the other two counts are unmoved.

## 1. What changed, by line

**`sw/seq_run.py`**

| what | where |
|---|---|
| the module contract: step 0 IDENTITY (the device's set, or `--caps` on `--dry-run`, never the manifest's); step 1 LOAD validates at that set | `sw/seq_run.py:9-23` |
| manifest_caps_check — a manifest `caps` claim must be a subset of the set, refused BY NAME (SeqError) | `sw/seq_run.py:299` |
| Artifacts takes `caps=` (default empty = every pre-SR6 caller unchanged); the VALIDATOR runs first, then the manifest check | `sw/seq_run.py:412-414` |
| relocate re-validates the relocated stream at `caps=` | `sw/seq_run.py:723` |
| write_synth_repack_artifact (a fixture WRITER, not a load) validates at the set its caller names, default empty | `sw/seq_run.py:913` |
| Dev.seq_caps — reads HW.S_SEQ_CAPS through seq_rd (so only behind an OPEN SEQ gate), decodes with HW.seq_caps_set; unknown bit is a SeqError naming the bit | `sw/seq_run.py:1430` |
| parse_caps / `--caps` (`--dry-run` only, default None = the empty set) | `sw/seq_run.py:3279`, `sw/seq_run.py:3353` |
| main opens the identity gate FIRST (CSR reads only), then the B3 closed-gate refusal, then the capability block, then the artifacts | `sw/seq_run.py:3409-3435`, `sw/seq_run.py:3437-3454` |
| every refusal from Artifacts / relocate is a SystemExit "REFUSING before any DMA" | `sw/seq_run.py:3497`, `sw/seq_run.py:3548` |
| selftest block, +10 checks (the pieces; the end-to-end is sr6_host_tdd.py) | `sw/seq_run.py:3076` |

**`sw/chat_seq.py`**

| what | where |
|---|---|
| load_template and independent_step_images take `caps=` and validate at it | `sw/chat_seq.py:480`, `sw/chat_seq.py:521` |
| the `--seq-rtl` block: SEQ_RTLS, the r1 pins REORDER_B_R1_IMAGES and their log | `sw/chat_seq.py:672-685` |
| check_seq_rtl — a level above r0 needs `--reorder B` (refused naming `--seq-rtl`) | `sw/chat_seq.py:753` |
| resolve_reorder's form-B branch carries the level, its caps and its pins | `sw/chat_seq.py:869` |
| reorder_b_images takes `rtl=` and passes it to reorder_e4.reorder | `sw/chat_seq.py:931`, `sw/chat_seq.py:950` |
| B6: the shipped side's SeqExec at the empty set, the reordered side at the level's caps | `sw/chat_seq.py:1058` |
| ChatSession: seq_rtl, level_caps, caps (the level's until open_board) | `sw/chat_seq.py:2499` |
| each reordered image is validated at the session's set after its pin check | `sw/chat_seq.py:2700` |
| open_board reads the device's caps; admit_caps re-validates the template (load_template), the slices (independent_step_images) and the three RELOCATED images at them, then the level-subset check, before any upload | `sw/chat_seq.py:2779`, `sw/chat_seq.py:2814`, `sw/chat_seq.py:2848-2872` |
| SeqModelVerifier (`--verify`, `--model-only`) runs SeqExec at the session's set | `sw/chat_seq.py:3516` |
| `--seq-rtl` / `$FABLE5_SEQ_RTL` (read at parse; an unknown value is an argparse error) | `sw/chat_seq.py:6879` |
| the level check before the lock (exit 4); open_board's refusal is exit 4 too | `sw/chat_seq.py:7005`, `sw/chat_seq.py:7092` |

**`sw/serve.py`** pins `seq_rtl="r0"` in BoardBackend's `_args` namespace
(`sw/serve.py:623`). **`docs/USAGE.md`** §3 gains one paragraph,
"`--seq-rtl r0|r1`".

## 2. The r1 images — a static-cost lineage with their own pins

`evidence/qwen9b/sr/sr6_r1_pins.py` follows the S1P recipe
(`evidence/qwen9b/ov/s1p_formB_pins.py`, n88) at `rtl="r1"`. It builds the
shipped session's step images and reorders each one on its own with
`reorder_b_images`. That is form B at static costs, position 0, and OV1's
per-channel-fence schedule. It does this twice. Tree 96aedd7, clean.

| image | records | FENCE masks 0001/0010/0100/1000 | static model (program order → replay) | pin |
|---|---|---|---|---|
| lite | 38,858 → 39,314 | 312/312/312/312 (`evidence/qwen9b/sr/n601_r1_pins.log:8`) | 30,209,477 → 25,195,119 cyc (`evidence/qwen9b/sr/n601_r1_pins.log:9`) | `evidence/qwen9b/sr/n601_r1_pins.log:22` |
| full | 39,626 → 40,173 | 343/343/342/342 (`evidence/qwen9b/sr/n601_r1_pins.log:14`) | 32,771,280 → 27,135,354 cyc (`evidence/qwen9b/sr/n601_r1_pins.log:15`) | `evidence/qwen9b/sr/n601_r1_pins.log:23` |

* **Checks.** Both images validate at {R1} and are refused at the empty set.
  The hazard assert passes; the postcheck finds 0 violations. The run is
  deterministic (`evidence/qwen9b/sr/n601_r1_pins.log:19`). **r0 is
  byte-identical**: its images regenerate equal to REORDER_B_IMAGES
  (`evidence/qwen9b/sr/n601_r1_pins.log:20-21`).
* **This makespan is not n120's (E).** The full image's 27,135,354 is this
  lineage's number: a chat step image priced by `ref/seq_cost.py` at
  position 0. n120's 27,136,513 (SR4 §4) is the CSV-costed loop body of the
  `model_9b_s1` template, which is a different stream from a different cost
  source. They are close by coincidence. A later board or TB comparison of
  these images must use n601's numbers.
* **The three gates, boardless, at r1 (tree 341e957, clean).**
  `chat_seq.py --nch 4 --seq-rtl r1 --reorder B --reorder-check`:
  * The pins match (`evidence/qwen9b/sr/n608_chat_seq_r1_reorder_check.log:6`).
  * The hazard assert passes on both images
    (`evidence/qwen9b/sr/n608_chat_seq_r1_reorder_check.log:8-9`).
  * **B6 passes.** The shipped images replay at the empty set and the r1
    images at {R1}. Tokens and state are identical, with state diff empty,
    in 540.0 s (`evidence/qwen9b/sr/n608_chat_seq_r1_reorder_check.log:21`).
    The result is REORDER CHECK: PASS
    (`evidence/qwen9b/sr/n608_chat_seq_r1_reorder_check.log:22`).

## 3. TDD — `evidence/qwen9b/sr/sr6_host_tdd.py`

**How the test drives the code.** The test runs the REAL `seq_run.main` and
`chat_seq.main`. The device is a subclass of the real Dev: its constructor
runs the real `_gate` over a scripted CSR map, and every read outside the
map returns HW.SEQ_CSR_UNMAPPED. The two SEQ_CAPS words come from hwmap:
seq_caps_word of {R1} (0xFAB1CA01) and SEQ_CSR_UNMAPPED (0xDEADC0DE).

**Tripwires (the n35 closed-gate + upload-tripwire pattern).** Every write
and DMA method of the mock trips a wire, and so do `seq_run.upload` and
`ChatSession.bring_up`.
* **LOADS** means the run reached one of those upload tripwires.
* **Refused before any DMA** means a non-zero exit with no tripwire touched.

**The seq_run fixture** is the R-c synthetic repacked artifact at nch=4. It
has 12 real MOVX/MVGO/FENCE/MOVY groups; its FENCEs were rewritten to
single-channel masks for r1.

**The chat cases** run at `FABLE5_MODEL=9b FABLE5_RS_F=7` with `--nch 4`.
B6 is stubbed there; the real B6 run is n608.

| case | what | RED n600 | GREEN n603 |
|---|---|---|---|
| (a) | the r1 stream LOADS through seq_run.main on the 0xFAB1CA01 mock, SEQ_CAPS read first | 0/2 | 2/2 (`evidence/qwen9b/sr/n603_sr6_host_tdd_GREEN.log:13-14`) |
| (b) | the same stream is REFUSED on 0xDEADC0DE before any DMA; the validator's message names the first masked FENCE (record 5) | 2/2 † | 2/2 (`evidence/qwen9b/sr/n603_sr6_host_tdd_GREEN.log:19-20`) |
| (b2) | … and the refusal is device-keyed (SEQ_CAPS was read) | 0/1 | 1/1 |
| (c)/(c2) | an r0 stream loads on both mocks, with SEQ_CAPS read | 2/2, 0/2 | 2/2, 2/2 |
| (d) | an r1 stream whose manifest claims no capabilities still refuses on 0xDEADC0DE and still loads on 0xFAB1CA01 | 1/2 | 2/2 (`evidence/qwen9b/sr/n603_sr6_host_tdd_GREEN.log:40`, `evidence/qwen9b/sr/n603_sr6_host_tdd_GREEN.log:45`) |
| (e) | a manifest claiming R2 on a 0xFAB1CA01 device is refused BY NAME before any DMA | 0/2 | 2/2 (`evidence/qwen9b/sr/n603_sr6_host_tdd_GREEN.log:50-51`) |
| (f) | `chat_seq --nch 4 --seq-rtl r1` on the 0xDEADC0DE mock: exit 4 at open_board, no upload, SEQ_CAPS read, message names the masked FENCE | 0/2 | 2/2 (`evidence/qwen9b/sr/n603_sr6_host_tdd_GREEN.log:93-94`) |
| (g) | **the positive case:** `chat_seq --nch 4 --seq-rtl r1` LOADS on the 0xFAB1CA01 mock (details below) | 0/4 | 6/6 (`evidence/qwen9b/sr/n603_sr6_host_tdd_GREEN.log:100-106`) |
| (g0) | control: the default session (r0, form B) loads on 0xDEADC0DE; images equal REORDER_B_IMAGES | 2/2 | 2/2 (`evidence/qwen9b/sr/n603_sr6_host_tdd_GREEN.log:86-87`) |
| (h) | serve's namespace pins its level to r0 | 0/1 | 1/1 (`evidence/qwen9b/sr/n603_sr6_host_tdd_GREEN.log:78`) |
| (i) | refusals before the board: r1 with `--reorder A` / `off` / env off (exit 4); `--seq-rtl r9`, a bad `$FABLE5_SEQ_RTL` (exit 2) | 1/5 ‡ | 5/5 (`evidence/qwen9b/sr/n603_sr6_host_tdd_GREEN.log:109-119`) |
| (k) | B6 at r1 hands SeqExec the empty set (shipped) and {R1} (reordered); the verifier {R1}; B6 at r0 is the empty set on both sides | 0/1 | 3/3 (`evidence/qwen9b/sr/n603_sr6_host_tdd_GREEN.log:121-123`) |
| (l) | `--caps`: the default is empty; R9 is refused; on a SEQ run it is refused; a dry-run of r1 without it is refused and never reads SEQ_CAPS; with `--caps R1` the dry-run uploads (n603; since fix round 1 it uploads nothing, §9) | 3/6 ‡ | 6/6 (`evidence/qwen9b/sr/n603_sr6_host_tdd_GREEN.log:54-70`) |
| (m) | seq_caps: 0xDEADC0DE → empty, 0xFAB1CA01 → {R1}; a closed gate never reads 0x64; bit 3 is refused before any DMA | 0/3 | 3/3 (`evidence/qwen9b/sr/n603_sr6_host_tdd_GREEN.log:71-76`) |

**Case (g), the positive case, in full.**
* **The route: the MOCK-DEVICE path through the real `chat_seq.main`.**
  main runs resolve_reorder, then ChatSession (the r1 images, checked
  against their pins), then the image hazard assert, then B6 (stubbed), and
  then open_board. open_board reads SEQ_CAPS and calls admit_caps. admit_caps
  calls chat_seq's own two validation sites, load_template and
  independent_step_images, with caps {R1}, after the device read. It then
  validates the three relocated images, and bring_up is reached.
* **The checks.** The event trace shows both sites called with the device's
  caps after the read (`evidence/qwen9b/sr/n603_sr6_host_tdd_GREEN.log:101-102`).
  The loaded images carry 1248 / 1370 masked FENCEs and are refused at the
  empty set. The session's set is the device's {R1}. The images equal the r1
  pins.
* **Why this route and not reorder-check.** The reorder-check path never
  opens a device, so it cannot reach the device-keyed validation.

**The two daggers in the table.**
* † **(b) passes in RED, and should.** Before SR6, seq_run refused every r1
  stream: the validator ran at the empty set. That is the safe direction.
  What RED could not do is (b2), a refusal keyed on the device, or (a), a
  load on an R1 device. The (a) failure is the I3 defect.
* ‡ **The partial RED passes were vacuous, as the docstring predicted.**
  (i)'s unknown level and (l)'s "R9 is an argparse error" passed because the
  flags did not exist yet. (l)'s dry-run refusal passed because today's
  seq_run already refused an r1 stream.

**The failed GREEN attempt, n602 (tree 8aff542).** It scored 40 passed /
2 failed (`evidence/qwen9b/sr/n602_sr6_host_tdd_GREEN.log:125`).
* **What failed.** In (b) and in (l)'s dry-run, the r1 fixture's manifest
  claim of R1 was refused by the manifest subset check before the validator
  could name the masked FENCE record.
* **The fix** (b279c77) runs the validator first. The plan says (b) is
  refused "by the validator", and the validator is the actual guard; the
  manifest check is the secondary, by-name check.
* **The re-run.** n603 on the clean tree b279c77 passes 42/0.

## 4. Selftests, boardfree, serve's coverage line (tree 341e957, clean)

| run | result | log |
|---|---|---|
| `sw/seq_run.py --selftest` | 2820 passed, 0 failed (+10: the SR6 block) | `evidence/qwen9b/sr/n604_seq_run_selftest.log:53` |
| `sw/chat_seq.py --selftest` (FABLE5_MODEL unset) | 407 passed, 1 failed — the pre-existing [22] | `evidence/qwen9b/sr/n605_chat_seq_selftest.log:35` |
| boardfree | seq 2820/0, serve 85/0, chat 407/1 [22] | `evidence/qwen9b/sr/n606_boardfree.log:59`, `evidence/qwen9b/sr/n606_boardfree.log:105`, `evidence/qwen9b/sr/n606_boardfree.log:136` |
| `sw/serve.py --selftest` (Step 3b) | 85 passed, 0 failed | `evidence/qwen9b/sr/n607_serve_selftest.log:49` |
| **serve's coverage line** | "args namespace covers chat_seq's args.* reads" **ok** | `evidence/qwen9b/sr/n607_serve_selftest.log:47`, `evidence/qwen9b/sr/n606_boardfree.log:103` |
| negative control: the same check with seq_rtl dropped from the namespace | reports missing: seq_rtl, MISSING — the check bites | `evidence/qwen9b/sr/n609_serve_coverage_negctl.log:43` |

* **The triple.** The plan's floor is 2810/0, 85/0, 407/1 [22]. The seq_run
  count moved up by exactly the added selftests. The chat_seq FAIL is the
  same [22] region-image case as every baseline
  (`evidence/qwen9b/sr/n605_chat_seq_selftest.log:32`).
* **The coverage line was read, not the count.** chat_seq's main now reads
  `args.seq_rtl`. Without the pin in serve's namespace, that line reports
  MISSING while the count stays 84/1, and n609 shows it does.

## 5. The citation-drift pass (SR6 moved lines that other documents cite)

The pass ran at base 7e72126, SR6's parent, through
`evidence/qwen9b/sr/sr6_drift.sh`.

| step | result | log |
|---|---|---|
| `--plan` (first) | REPAIR 216, COLLATERAL 1 — the one collateral token is in S3_CHAIN.md's hand-repair TABLE, a historical record | `evidence/qwen9b/sr/n610_cite_drift_plan.log:41` |
| `--check` | 189 drifted, 11 unresolved (the rewritten validate_stream calls, the module-contract line, reorder_b_images' def and the moved B3 block) | `evidence/qwen9b/sr/n611_cite_drift_check.log:413` |
| `--plan` (S3_CHAIN.md and tb/tb_seq_chip.sv excluded) | REPAIR 214, COLLATERAL 0, SAFE | `evidence/qwen9b/sr/n612_cite_drift_plan.log:40-41` |
| `--fix` | 189 citations fixed in 28 documents | `evidence/qwen9b/sr/n613_cite_drift_fix.log:44` |
| hand repairs | 20 tokens, 20 OK: the 15 unresolved sw tokens plus 5 tokens into docs/USAGE.md, whose lines the new §3 paragraph moved | `evidence/qwen9b/sr/n617_hand_repairs_check.log:78` |
| `--verify`, hand-repaired documents excluded | PASS, 0 problems | `evidence/qwen9b/sr/n616_cite_drift_verify_excl_hand.log:15` |
| `--doc-cites --verify` | 24 complaints, every one in BOARD_LOCK.md's was/now table | `evidence/qwen9b/sr/n619_doc_cites_verify.log:37` |

* **Every edit is digits only.** Stripping the digits from each edited
  document gives its committed text back.
* **Left alone on purpose, and why.**
  * `evidence/qwen9b/o3/BOARD_LOCK.md:643-648`. This is O3's was/now table
    of its own repair: both columns are history.
  * S3_CHAIN.md's hand-repair table. Also history, and already stale in
    content at 7e72126.
  * `tb/tb_seq_chip.sv`, which is SR5a's territory. Its one comment token,
    sw/seq_run.py:1242, was already wrong in content at 7e72126: it says
    EMBLOG2 programming, but that line is the BM_IDENT check. **It is left
    for its owner.** (SR9, 2026-09-29: the tb token now reads 1762, the EMBLOG2 docstring, per SR11c §12 m3.)
* **The tool's labels are pre-SR6.** The "(the :474 …)" / "(the :514 …)"
  labels in the test's case names are the brief's pre-SR6 line numbers.
  Those sites are now `sw/chat_seq.py:480` and `sw/chat_seq.py:521`.
* **n614 / n615 / n618 are pre-hand-repair or base-sweep runs.** They are
  committed as the record. The GREEN halves are n616, n617 and n619.
* **spec_cites over the 29 documents the pass touched.** Taken alone, it
  reports FAIL 296 (`evidence/qwen9b/sr/n621_spec_cites_precheck_all.log:7`).
  **SR6 introduced none of them.** `evidence/qwen9b/sr/sr6_spec_cites_baseline.sh`
  (the SR3c method) keys every FAIL at three trees:
  * base 7e72126: 246 keys;
  * pre-pass 860d018: 251 keys;
  * work: 246 keys.

  The pass REPAIRED 5, and nothing is INTRODUCED
  (`evidence/qwen9b/sr/n622_spec_cites_baseline.log:8`,
  `evidence/qwen9b/sr/n622_spec_cites_baseline.log:33-34`, `evidence/qwen9b/sr/n622_spec_cites_baseline.log:49`). The last run is
  spec_cites, alone, over this document plus the 14 touched documents with
  zero FAIL keys in work, docs/USAGE.md among them.

## 6. Judgment calls

1. **seq_run opens the identity gate before the artifacts.** The device's set
   must exist before the first validation. Dev's constructor does CSR reads
   only, so moving it earlier adds no DMA. The B3 closed-gate refusal still
   comes before any upload, and seq_run's own B3 selftest still passes
   (2820/0).
2. **`--caps` is for `--dry-run` only, and a SEQ run refuses it.** A run's
   set is the device's. A dry-run never reads the SEQ window, so its set is
   `--caps`, default empty. **Amended in fix round 1 (controller ruling,
   I-1):** a dry-run with a non-empty `--caps` now validates and relocates
   at that set and uploads NOTHING, so the property holds literally: no
   path uploads an r1 stream without a device read (§9).
3. **The validator runs before the manifest check** (§3, n602).
4. **The manifest check is subset-only.** An absent `caps` key claims
   nothing. An unknown name in a manifest is a SeqError.
5. **chat_seq validates twice.**
   * Before open_board it validates at the LEVEL's set. This is the software
     gate: the user named the level, never a manifest, and the r1 images
     cannot be built at the empty set.
   * open_board then re-validates everything at the DEVICE's set before any
     upload.
   * The level-subset check runs after the image validation. It is a
     belt-and-braces check; the image validation already refuses r1 at the
     empty set, naming the record.
6. **r1 needs `--reorder B`.** A form-A r1 template does not exist and was
   not asked for. With auto, r1 resolves to B at 9B `--nch 4` and is refused
   elsewhere.
7. **B6 models each side at the set its images need.** The shipped side is
   modelled at the empty set and the reordered side at the level's set. The
   verifier uses the session's set.
8. **The seq_caps SystemExit/SeqError split.** seq_caps raises SeqError. It
   refuses through require_seq's SystemExit only when the gate is closed.
   seq_run's main turns SeqError into "REFUSING before any DMA", and
   chat_seq's open_board turns it into ChatSeqError (exit 4).
9. **No per-VERSION expected-caps check was added.**
   * Why: the r1 mock runs under VERSION build_041, because no R1 VERSION
     row exists. On silicon build_041 reads 0xDEADC0DE.
   * What the plan says: a VERSION → expected-SEQ_CAPS identity check ("SEQ_CAPS
     not the expected word", Global Constraints) belongs with SR7's
     SEQ_VERSIONS row.
   * Why nothing weakens: caps are feature detection, as BM1's idle-counter
     IDENT is. Admission is still gated on a NAMED VERSION, because
     seq_caps reads only behind the open gate.
10. **Evidence tools are not threaded.** bm1_census, g6_census, g6_clip and
    g6_state build Artifacts / relocate or a Dev themselves. They still
    validate at the default, the empty set, which is fail-closed for any r1
    stream. cycle_census and serve go through open_board, so they do get
    the device-keyed validation.

## 7. Does NOT establish

* That the board admits an R1 VERSION. Its SEQ_VERSIONS row is SR7's last
  step. Until then no bitstream can run r1: seq_caps is read only behind a
  named VERSION, and build_041/042 read the empty set.
* That SEQ_CAPS reads correctly on silicon (SR8), or that any chip-TB or
  board run of these r1 chat images exists. Their evidence is the model
  (B6 at {R1}), the hazard assert and the postcheck.
* Any speed. The makespans above are MODEL numbers from the static cost
  table, at position 0.

## 8. Rule slips, disclosed

* **`python3` ran twice on darthplagueis.**
  * Once as an empty heredoc (`python3 - <<EOF` with no body), so nothing
    executed.
  * Once as `python3 -c "print(1)"`, which prints a constant.
  * Neither did any arithmetic or ran any project code.
* **A syntax check without a log.** `python -m py_compile` of the three sw
  files ran on snoke over plain ssh, not through sr_run.sh. It was a syntax
  check and produced no evidence.
* **Log numbers differ from the brief's plan.** n602 is the failed GREEN, so
  GREEN is n603. The selftests are n604/n605/n607, boardfree is n606, the r1
  B6 is n608, serve's negative control is n609, the drift pass is
  n610–n619, and spec_cites is n620–n623 (n623 is the LAST run).

## 9. Fix round 1 (task review: I-1 ruling, M-1, M-2a, M-3)

* **I-1, the ruling.** "No path uploads an r1 stream without a device read"
  is literal. `sw/seq_run.py --dry-run` with a non-empty `--caps` now stops
  (`sw/seq_run.py:3580`) after validate + relocate at the typed set, prints "validated only,
  nothing uploaded", and exits 0 with no DMA of any kind. A dry-run at the
  empty set keeps its upload; `--caps` on a SEQ run stays refused.
  * **RED** on 382500d (the test's l3 case flipped, committed first): 42
    passed / 2 failed, exactly l3's two new checks
    (`evidence/qwen9b/sr/n624_sr6fix1_host_tdd_RED.log:132`). The
    docstring predicted "41 / 2 of 43"; the failing set was right, the
    total was off by one (the flipped case has three checks, not two).
  * **GREEN** on 655cedd: 44 passed / 0 failed
    (`evidence/qwen9b/sr/n625_sr6fix1_host_tdd_GREEN.log:129`).
  * seq_run `--selftest` 2820/0
    (`evidence/qwen9b/sr/n626_sr6fix1_seq_run_selftest.log:53`). Boardfree
    2820/0, 85/0, 407/1 [22], and serve's coverage line reads ok
    (`evidence/qwen9b/sr/n627_sr6fix1_boardfree.log:59`,
    `evidence/qwen9b/sr/n627_sr6fix1_boardfree.log:103`,
    `evidence/qwen9b/sr/n627_sr6fix1_boardfree.log:105`,
    `evidence/qwen9b/sr/n627_sr6fix1_boardfree.log:136`).
  * §6.2 is amended above.
* **M-1.** docs/USAGE.md §3 now says an r1 session on a non-R1 device is
  refused at open_board, after the ~540 s B6 gate, and how to fail fast.
  `evidence/qwen9b/bm/bm1_ident.py` reads VERSION and CALIB but not SEQ_CAPS,
  and the paragraph says so. No tool prints SEQ_CAPS on its own today.
* **M-2a.** NEXT_SESSION.md §3's admission paragraph gains the SR6 sentence.
* **M-3.** The test's labels now name the post-SR6 sites, chat_seq lines 477
  and 518. The report's commit count is corrected to 21.
* **Citations.** The fix moved seq_run lines and USAGE / NEXT_SESSION lines
  that other documents cite. A second drift pass ran at base 3b3c727
  (`evidence/qwen9b/sr/sr6fix1_drift.sh`):
  * `--verify` PASS, 0 problems
    (`evidence/qwen9b/sr/n632_sr6fix1_drift_verify.log`).
  * This document's own seq_run tokens and the doc-cite tokens into USAGE
    and NEXT_SESSION were re-pointed by hand: 20/20 OK
    (`evidence/qwen9b/sr/n634_sr6fix1_hand_repairs_check.log`).
  * spec_cites over the touched documents: 81 FAIL keys at base, 81 in
    work, **none introduced**
    (`evidence/qwen9b/sr/n637_sr6fix1_spec_cites_baseline.log`). n636 is
    VOID: this document does not exist at the base, so the export failed.
  * Left alone: the records already listed in §5, RD9_GATE.md's sha-pinned
    NEXT_SESSION cite, and the board-idle spec's NEXT_SESSION.md:407. That
    last one was already stale in content at the base.
