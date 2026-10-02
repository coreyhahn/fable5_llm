# SR13b — the host's R2 capability, and the keyless-manifest hardening

Task SR13b of the sequencer RTL round (`docs/superpowers/plans/2026-09-27-seq-rtl-round.md`),
plus the controller's binding addendum from SR11a's round-3 re-review (the keyless path).
Host code only: **no RTL, no build, no board action**. Every device below is a MOCK of the SEQ
window (SR6's harness, `evidence/qwen9b/sr/sr6_host_tdd.py`). Every run was on snoke through
`evidence/qwen9b/sr/sr_run.sh`, in log block n1350–n1399.

**Verdict.**
* **An r2 stream (B17.2 bank fields) is admitted only on a device whose SEQ_CAPS decodes to a set
  with R2** — refused on 0xDEADC0DE (build_041) and on 0xFAB1CA01 (build_044_r1_incr, R1-only: the
  not-fail-closed hazard of spec §1.2), loaded on 0xFAB1CA03, in `sw/seq_run.py` and in
  `sw/chat_seq.py --seq-rtl r2`. A manifest decides nothing: mislabelled (caps [R1]; seq_isa 2.2)
  and claim-less r2 streams are refused on 0xFAB1CA01 and load on 0xFAB1CA03.
* **seq_run needed no change for R2.** RED already passed every seq_run r2 case (15/15): admission
  has been device-keyed since SR6 and the validator refuses every bank field without R2 since SR11a.
  The new code is chat_seq's r2 level and the keyless hardening.
* **Keyless path closed.** A board run now REQUIRES the manifest's `shape_isa` key, except the three
  frozen pre-G3 streams at an isa=1 device.
* **Test-first.** RED 23 passed / 19 failed of 42, exactly the prediction
  (`evidence/qwen9b/sr/n1350_sr13b_host_tdd_RED.log:125`); GREEN 42 / 0 on the clean tree 3eb0728
  (`evidence/qwen9b/sr/n1352_sr13b_host_tdd_GREEN.log:117`).
* **r2 images (E).** Pinned: lite `c78312bb…` (39,314 records), full `868ba4e0…` (40,173)
  (`evidence/qwen9b/sr/n1351_sr13b_r2_pins.log:24-25`). B6 at r2 passes, tokens and state identical (§3).
* **Regressions green**: seq_run 2826/0 (+3), chat_seq 407/1 [22], SR6 45/0, SR11a fix 2 12/12,
  fix 3 8/8, SR7 36/0, boardfree with serve's coverage line ok (§4).

## 1. What changed

**`sw/seq_run.py`** (commit 3eb0728)

| what | where |
|---|---|
| module contract, step 1: a SEQ run requires the `shape_isa` key; an r2 stream loads only where the device's set has R2 | `sw/seq_run.py:27-32` |
| FROZEN_PRE_G3_STREAMS — the three streams admitted keyless (at isa=1 only), by stream sha256, each the one that ran on build_035 | `sw/seq_run.py:203` |
| layout_key_check — declared → pass; frozen at isa=1 → pass; else SeqError naming the missing `shape_isa` key | `sw/seq_run.py:321` |
| Artifacts(require_layout_key=) calls it before the declared-layout compare and the validator | `sw/seq_run.py:366`, `sw/seq_run.py:399` |
| main passes require_layout_key on every SEQ run (not on `--dry-run`) | `sw/seq_run.py:3499` |
| the synthetic repack fixture declares `shape_isa` (its SHAPE words are this tree's layout) | `sw/seq_run.py:940` |
| selftest +3 (layout_key_check) | `sw/seq_run.py:2915` |

**`sw/chat_seq.py`** (commit 3eb0728)

| what | where |
|---|---|
| SEQ_RTLS gains r2 | `sw/chat_seq.py:672` |
| the r2 block: REORDER_B_R2_IMAGES from n1351, and REORDER_B_PINS_BY_RTL (level → pins, log) | `sw/chat_seq.py:686`, `sw/chat_seq.py:697`, `sw/chat_seq.py:705` |
| resolve_reorder and _reorder_images_b take the level's pins from that table | `sw/chat_seq.py:877`, `sw/chat_seq.py:2681` |
| admit_caps: the keyless check FIRST, before any validation (a ChatSeqError, exit 4) | `sw/chat_seq.py:2839` |
| `--seq-rtl` metavar from SEQ_RTLS; help names r2 and 0xFAB1CA03 | `sw/chat_seq.py:6880` |

No new `args.*` read, so **`sw/serve.py` is untouched**; it still pins `seq_rtl="r0"`, and its
coverage line was read (§4). `reorder_e4.CAPS_OF["r2"]` = {R1, R2} is SR11b's
(`ref/scripts/reorder_e4.py:133-134`); chat_seq's `seq_rtl_caps` reads it.

## 2. TDD — `evidence/qwen9b/sr/sr13b_host_tdd.py`

The harness is SR6's: the REAL `seq_run.main` / `chat_seq.main`, the REAL `Dev._gate` over a
scripted CSR map, every write / DMA method, `seq_run.upload` and `ChatSession.bring_up` tripwires.
LOADS = an upload tripwire reached; REFUSED = non-zero exit with none touched. The three words are
hwmap's: SEQ_CSR_UNMAPPED, seq_caps_word({R1}), seq_caps_word({R1,R2}) = 0xFAB1CA03. No R2
bitstream exists, so the 0xFAB1CA03 device's VERSION row (0x2B2B2B2B, isa=2) is injected by the
test and removed after (SR11a fix 2's convention). The r2 seq_run fixture is SR6's r1 fixture with
its first group banked (MOVX word 1536, MVGO XBANK|RBANK, MOVY row 2048), first banked record 3.

**The refusal matrix for an r2 stream** (seq_run; chat_seq in the lower rows):

| stream / manifest | 0xDEADC0DE (041) | 0xFAB1CA01 (044, R1) | 0xFAB1CA03 (mock R1+R2) |
|---|---|---|---|
| honest (seq_isa 2.3, caps [R1,R2]) | REFUSED, rec 3 (`…GREEN.log:27`) | REFUSED, names R2 + rec 3 (`…GREEN.log:20-22`) | LOADS (`…GREEN.log:14-15`) |
| mislabelled caps [R1] | — | REFUSED (`…GREEN.log:33`) | LOADS (`…GREEN.log:34`) |
| mislabelled seq_isa 2.2 | — | REFUSED (`…GREEN.log:39`) | LOADS (`…GREEN.log:40`) |
| no capability claim | — | REFUSED (`…GREEN.log:45`) | LOADS (`…GREEN.log:46`) |
| chat_seq `--seq-rtl r2` (images carry NO manifest) | exit 4 at open_board (`…GREEN.log:90`) | exit 4 at open_board, names R2 (`…GREEN.log:83-84`) | LOADS (`…GREEN.log:96-102`) |

(`…GREEN.log` = `evidence/qwen9b/sr/n1352_sr13b_host_tdd_GREEN.log`.) Every refusal read SEQ_CAPS
first (device-keyed) and touched no tripwire. `--dry-run --caps R1` refuses the r2 stream;
`--caps R1,R2` validates, relocates and uploads nothing (`…GREEN.log:47-48`).

| case | what | RED n1350 | GREEN n1352 |
|---|---|---|---|
| setup | 0xFAB1CA03 word; chat_seq at 9B | 2/2 | 2/2 |
| (a)–(f) | the seq_run matrix above + dry-run | 15/15 † | 15/15 |
| (K1) | keyless isa=2 artifact named as build_035 → REFUSED naming the `shape_isa` key | 0/1 | 1/1 (`…GREEN.log:54`) |
| (K2) | frozen 2B W8 (isa=1, keyless) at build_035 → LOADS | 1/1 | 1/1 (`…GREEN.log:59`) |
| (K3) | keyless at build_041 → REFUSED naming the key | 0/1 | 1/1 (`…GREEN.log:64`) |
| (K4) | 9B (declared 2) LOADS at 041, 044, the R2 mock | 3/3 | 3/3 (`…GREEN.log:65-67`) |
| (K5) | chat admit_caps: keyless non-frozen template REFUSED at isa=1 and isa=2 before its first validation; frozen W8 at isa=1 passes | 1/3 | 3/3 (`…GREEN.log:69-73`) |
| (h2) | serve still pins r0 | 1/1 | 1/1 |
| (g) (h) | chat r2 on 0xFAB1CA01 / 0xDEADC0DE → exit 4 at open_board, no upload | 0/3 | 3/3 |
| (i) | chat r2 LOADS on 0xFAB1CA03: caps {R1,R2} reach load_template and independent_step_images after the read; 1728 / 1916 bank fields, refused at {R1} and {}; images == pins; session caps {R1,R2} | 0/6 | 6/6 (`…GREEN.log:96-102`) |
| (j) | r2 with `--reorder A` / `off` / env off → exit 4 before the board; FABLE5_SEQ_RTL=R2 parses | 0/4 | 4/4 (`…GREEN.log:105-112`) |
| (k) | B6 at r2: shipped side {}, reordered {R1,R2}; verifier {R1,R2} | 0/2 | 2/2 (`…GREEN.log:113-115`) |

† **Passing in RED is the finding, not a vacuous pass**: the RED docstring predicted it and why.
The 19 RED failures were exactly the predicted set (`evidence/qwen9b/sr/n1350_sr13b_host_tdd_RED.log:124`).

## 3. The r2 images and their B6 (E, MODEL)

`evidence/qwen9b/sr/sr13b_r2_pins.py` is SR6's r1 recipe at `rtl="r2"` (SR11b's reorder_e4 pass),
on the clean tree 925af52:

| image | records | static model (program order → replay), MODEL, position 0 | pin |
|---|---|---|---|
| lite | 38,858 → 39,314 | 30,209,477 → 24,341,703 cyc (`evidence/qwen9b/sr/n1351_sr13b_r2_pins.log:9`) | `evidence/qwen9b/sr/n1351_sr13b_r2_pins.log:24` |
| full | 39,626 → 40,173 | 32,771,280 → 26,131,018 cyc (`evidence/qwen9b/sr/n1351_sr13b_r2_pins.log:15`) | `evidence/qwen9b/sr/n1351_sr13b_r2_pins.log:25` |

Both validate at {R1,R2} and are refused at {R1} and at {}; the hazard assert passes; the run is
deterministic, and r1 and r0 regenerate IDENTICAL to their pins
(`evidence/qwen9b/sr/n1351_sr13b_r2_pins.log:19-23`).

**B6 at r2, boardless** (clean tree ecd536c): `chat_seq.py --nch 4 --seq-rtl r2 --reorder B --reorder-check`. Both images regenerate equal to their pins, and the hazard assert passes on both (`evidence/qwen9b/sr/n1360_chat_seq_r2_reorder_check.log:8-9`). The shipped images are replayed at the empty set and the r2 images at {R1,R2}. Tokens and state are identical, with state diff empty, in 534.7 s (`evidence/qwen9b/sr/n1360_chat_seq_r2_reorder_check.log:21`). The result is REORDER CHECK: PASS (`evidence/qwen9b/sr/n1360_chat_seq_r2_reorder_check.log:22`).

## 4. Regressions (clean tree ecd536c)

| run | result | log |
|---|---|---|
| `sw/seq_run.py --selftest` | 2826 / 0 (2823 + the 3 layout_key_check checks) | `evidence/qwen9b/sr/n1353_seq_run_selftest.log:54` |
| `sw/chat_seq.py --selftest` | 407 / 1, the known [22] | `evidence/qwen9b/sr/n1354_chat_seq_selftest.log:32-35` |
| SR6 host TDD | 45 / 0 | `evidence/qwen9b/sr/n1355_sr6_host_tdd.log:133` |
| SR11a fix 2 TDD | 12 / 12 | `evidence/qwen9b/sr/n1356_sr11afix2_tdd.log:62` |
| SR11a fix 3 TDD | 8 / 8 | `evidence/qwen9b/sr/n1357_sr11afix3_tdd.log:31` |
| SR7 host TDD (`--r1 e3c2ff1e`) | 36 / 0 | `evidence/qwen9b/sr/n1358_sr7_host_tdd.log:50` |
| boardfree | 2826/0, 85/0, 407/1 [22] (BOARDFREE_FAIL on [22] alone, as at every baseline) | `evidence/qwen9b/sr/n1359_boardfree.log:60`, `evidence/qwen9b/sr/n1359_boardfree.log:106`, `evidence/qwen9b/sr/n1359_boardfree.log:137` |
| **serve's coverage line** | "args namespace covers chat_seq's args.* reads" **ok** | `evidence/qwen9b/sr/n1359_boardfree.log:104` |

The fixture writer's new key is why SR6's, fix 2's and fix 3's keyless fixtures still load on
build_041/044 under the new rule: they are built by `write_synth_repack_artifact`.

## 5. Judgment calls

1. **The addendum's rule, reconciled with its own TDD.** Read literally ("require the key whenever
   the device's layout is not isa=1"), a keyless isa=2 artifact named at build_035 would still pass,
   which its first TDD bullet forbids; requiring the key at isa=1 too would refuse the frozen W8
   artifact, which its second bullet forbids. The keyless artifacts cannot be told apart from their
   records, so the rule is: **the key is required on every board run; the only exemption is a frozen
   pre-G3 stream, by stream sha256, at an isa=1 device.** The three shas are the streams that ran on
   build_035 (`evidence/qwen2b/rd/seq_run_build035.json`, `evidence/qwen2b/rd/seq_run4_build035.json`,
   `evidence/qwen2b/rd/seq_run4_2b_build035.json`), and the on-disk manifests carry the same shas.
   This is strictly stronger than the literal rule; no existing refusal is weakened.
2. **What it newly refuses.** A keyless artifact on build_041+: post-G3 0.8b/2b artifacts
   (BYTELOCKED, written without the key) and any 9B artifact emitted before G4a added the key. Every
   9B artifact in `tb/scripts/w9/` carries `shape_isa: 2`. The message says to re-emit, or to add the
   key only when the layout is known. Only SEQ runs are keyed; `--dry-run` and the evidence tools
   that build Artifacts themselves are unchanged (they validate at the stated layout, as before).
3. **"Missing manifest" means no capability claim.** seq_run cannot load a stream without its
   .seq.json (the sha256s live there), so the seq_run case strips `caps` and `seq_isa` and keeps
   the rest; the literal no-manifest case is chat_seq's, whose step images never have one. The
   layout key is the addendum's separate requirement and the r2 fixtures declare it.
4. **The 0xFAB1CA03 device is a test-only VERSION row**, as in SR11a fix 2 (c). No R2 SEQ_VERSIONS
   row was added: no R2 bitstream exists, and a row is written only when a build's VERSION is known.
5. **No `docs/USAGE.md` paragraph.** `--help` documents r2. An r2 session has nowhere to run until
   an R2 bitstream is admitted, and a USAGE paragraph would shift lines that other documents cite.
   The paragraph belongs with that admission.
6. **The cite-drift pass was planned, not applied.** It follows the SR11a precedent: SR13b moved
   lines in both sw files. The plan for `sw/seq_run.py` is REPAIR 93 / COLLATERAL 0, SAFE
   (`evidence/qwen9b/sr/n1361_sr13b_drift_plan_seq_run.log`). The plan for `sw/chat_seq.py` is
   REPAIR 152 / COLLATERAL 5, UNSAFE (`evidence/qwen9b/sr/n1362_sr13b_drift_plan_chat_seq.log`).
   Both are handed to the controller. The wrapper is `evidence/qwen9b/sr/sr13b_drift.sh`, at base 966cbcf.
7. **Log numbers differ from the plan's.** n1351 is the pins run, so GREEN is n1352, the
   regressions are n1353–n1359, the r2 B6 is n1360 and the drift plans are n1361/n1362.

## 6. Does NOT establish

* That any bitstream reads 0xFAB1CA03, or that an R2 build admits an r2 session. There is no R2
  VERSION row, so no board runs r2 today; the gate would refuse it before any DMA.
* Any chip-TB or board run of the r2 chat images. Their evidence is the model (B6), the hazard
  assert, the postcheck and the pins.
* Any speed. The makespans are static-cost MODEL numbers at position 0.

## 7. Rule slips, disclosed

* `python3` ran twice on darthplagueis. The first time it read one JSON file's key names; there was
  no arithmetic. The second time a mistyped heredoc fed a perl script to it, and it failed with a
  syntax error, executing nothing. Neither ran any project code.
