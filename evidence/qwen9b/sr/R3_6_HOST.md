# R3-6 — the host's r3 level (`--seq-rtl r3`, the r3 image pins, device-keyed refusals)

Task R3-6 of the R3 campaign (MOVX broadcast, form (a); plan
`docs/superpowers/plans/2026-09-29-r3-broadcast.md`, Task R3-6, with the controller's addendum).
This task changes host code only. There is **no RTL, no build and no board action**. Every device
below is a MOCK of the SEQ window on SR6's harness (`evidence/qwen9b/sr/sr6_host_tdd.py`), SR13b's
method one level up (`evidence/qwen9b/sr/SR13b_HOST_R2.md`). Started from a990b40, a descendant of
690196f whose sw/, ref/ and tool files are unchanged since then. Every run was on snoke through
`evidence/qwen9b/sr/sr_run.sh`, in log block n2800–n2823. Labels: **E** printed by a committed run.

**Verdict.**
* **An r3 image or stream is admitted only on a device whose SEQ_CAPS decodes to {R1,R2,R3}
  (0xFAB1CA07).** It is refused before any DMA on 0xFAB1CA03, 0xFAB1CA01 and 0xDEADC0DE, and the
  validator's refusal names the BROADCAST record every time. This holds in `sw/seq_run.py` (a synthetic
  broadcast fixture and the real r3 stream s1) and in `sw/chat_seq.py --seq-rtl r3` (exit 4 at
  open_board). A manifest decides nothing: the caps [R1,R2], seq_isa 2.2 and claim-less manifests are
  refused at every lower word and load at 0xFAB1CA07 (E: `evidence/qwen9b/sr/n2804_r3_6_host_tdd_GREEN.log:48-59`).
* **seq_run needed no admission change for R3.** RED already passed every seq_run r3 case as a
  characterisation, because R3-2's validator names the broadcast and admission has been device-keyed
  since SR6. seq_run gained selftest cases only (§1).
* **Test-first.** RED was 49 passed / 23 failed of 72, exactly the prediction
  (`evidence/qwen9b/sr/n2800_r3_6_host_tdd_RED.log:169`). GREEN is 72 / 0
  (`evidence/qwen9b/sr/n2804_r3_6_host_tdd_GREEN.log:164`).
* **The r3 pins (E)** come from `sr13b_r2_pins.py --rtl r3`, a flag and not a copy. Lite is `8a226ca1…`
  with 38,930 records and 128 broadcasts. Full is `fdfc6d0c…` with 39,786 records and 129 broadcasts
  (`evidence/qwen9b/sr/n2801_r3_6_pins.log:33-34`). r2, r1 and r0 regenerate IDENTICAL to their pins
  (`evidence/qwen9b/sr/n2801_r3_6_pins.log:25-32`). **The B6 replay at r3 is exact**: tokens and state
  are identical (§3).
* **The regressions are unchanged**: seq_run 2850/0 (2840 plus R3-6's 10 checks), chat_seq 407/1 on
  the known [22], SR6 45/0, SR13b 42/0, SR7 36/0, SR11a fix 2 12/0, fix 3 8/0, hwmap PASS, and
  boardfree with serve's coverage line ok. **Cite drift is 0**: 355 citations into the two sw files,
  all unmoved (§4).
* **No `SEQ_VERSIONS` row was added.** That row is R3-10's, written only for a kept bitstream. So
  today every real board refuses an r3 session before any DMA.

## 1. What changed

**`sw/chat_seq.py`** (commit 088eac0). Every addition sits after every cited line (the zero-drift
layout). The two existing places were rewritten in place with the same line count.

| what | where |
|---|---|
| the r3 block: `SEQ_RTLS = SEQ_RTLS + ("r3",)`, `REORDER_B_R3_IMAGES` (the n2801 pins), `REORDER_B_R3_PINS_LOG`, `REORDER_B_PINS_BY_RTL["r3"]`, with a comment giving the admission rule and the XPTR note | `sw/chat_seq.py:7198-7237` |
| the `--seq-rtl` help names r3 and each level's word (0xFAB1CA01 / 0xFAB1CA03 / 0xFAB1CA07); rewritten in place, 12 lines as before, so `--shape-isa` stays at its cited line | `sw/chat_seq.py:6882` |
| resolve_reorder's form-B log line names the bank fields at r3 as at r2 (`level != "r1"`; in place) | `sw/chat_seq.py:886` |

Every consumer reads the level table at call time: seq_rtl_default, seq_rtl_arg, seq_rtl_of,
main's metavar, resolve_reorder and `_reorder_images_b`. `seq_rtl_caps("r3")` is R3-5's
`reorder_e4.CAPS_OF["r3"]` = {R1,R2,R3}. admit_caps and open_board's re-key are unchanged. They
already validate the template, the slices and the three relocated images at the set decoded from the
DEVICE's SEQ_CAPS, then require the level's set to be a subset of it. At no point is a literal set
presented (§2 (j)).

**`sw/seq_run.py`** (commit 088eac0): **no admission change.** Its additions:

| what | where |
|---|---|
| `_selftest_r3`, called at the end of `_selftest_sr14` (after every cited line). It injects a MOCK R3 row trio (0x3B3B3B3B: SEQ_VERSIONS, hwmap SHAPE, BM_IDENT) and runs the real Dev._gate on it. READY only at 0xFAB1CA07 when named. REFUSED at 0xFAB1CA03, 0xFAB1CA01 and 0xDEADC0DE; on the shipped VERSION (the default), the R2 and the R1 VERSION reporting 0xFAB1CA07; and on the mock board by default. It also checks that no real row expects 0xFAB1CA07 and that the injected rows are gone after the run. 10 checks | `sw/seq_run.py:3839`, `sw/seq_run.py:3842` |

**Tools, as flags and not copies** (commit a5d0887). The defaults reproduce today's runs byte for
byte (E: `evidence/qwen9b/sr/n2823_r3_6_default_compare.log:7-8`). The default pins run matches
n1351 over 21 body lines. The default ident run matches n2223 over 62 lines.

| tool | flag |
|---|---|
| `evidence/qwen9b/sr/sr13b_r2_pins.py` | `--rtl r2\|r3` (default r2) (`evidence/qwen9b/sr/sr13b_r2_pins.py:88`). At r3 each image must validate at {R1,R2,R3} and be REFUSED naming the broadcast at {R1,R2}, {R1} and {}. The broadcast, forced and unicast-left counts are printed, and r2, r1 and r0 are regenerated against their pins. The r2 and r3 static makespans are printed side by side (`evidence/qwen9b/sr/sr13b_r2_pins.py:180`) |
| `evidence/qwen9b/sr/sr14_ident_expect.py` | `--want-version` / `--want-caps` (defaults 266e3ae7 / R1,R2) (`evidence/qwen9b/sr/sr14_ident_expect.py:29-31`). At R3 two cases are added: the R1+R2 word and the R2 bitstream named as R3 (`evidence/qwen9b/sr/sr14_ident_expect.py:59`, `evidence/qwen9b/sr/sr14_ident_expect.py:69`) |

New: `evidence/qwen9b/sr/r3_host_tdd.py` (the TDD). It is a new file because the fixture (a
broadcast), the fourth device word and the positive r3 session are new. SR13b's chat runner is
nested and cannot be imported, and SR13b's committed logs must stay reproducible from an unchanged
file. The helpers are imported rather than copied: make_dev / run_seq from SR6, and r2_fixture /
_rewrite from SR13b. `sw/serve.py`: **untouched**. It still pins `reorder=None, seq_rtl="r0"`
(§2 (m)), and its coverage line reads ok (§4).

## 2. TDD — `evidence/qwen9b/sr/r3_host_tdd.py`

The harness is SR6's. It runs the REAL `seq_run.main` / `chat_seq.main` and the REAL `Dev._gate`
over a scripted CSR map. Every write and DMA method is a tripwire, and so are `seq_run.upload` and
`ChatSession.bring_up`. LOADS means an upload tripwire was reached. REFUSED means a non-zero exit
with no tripwire touched. The four words are hwmap's.

The devices are:
* 0xDEADC0DE: build_041.
* 0xFAB1CA01: build_044_r1_incr.
* 0xFAB1CA03: build_045_r2_incr, SR14's REAL row 0x266E3AE7.
* 0xFAB1CA07: no R3 bitstream exists, so a MOCK VERSION 0x3B3B3B3B is used. Its three rows are
  injected by the test and removed after, which is checked
  (`evidence/qwen9b/sr/n2804_r3_6_host_tdd_GREEN.log:162`).

The seq_run fixture is SR13b's r2 fixture with its first MOVX (window word 1536) made a broadcast.
The first broadcast is record 3.

**The refusal matrix** (all E, `evidence/qwen9b/sr/n2804_r3_6_host_tdd_GREEN.log` = `…GREEN.log`):

| stream / manifest | 0xDEADC0DE (041, {}) | 0xFAB1CA01 (044, {R1}) | 0xFAB1CA03 (045, {R1,R2}) | 0xFAB1CA07 (mock {R1,R2,R3}) |
|---|---|---|---|---|
| fixture, honest (seq_isa 2.3, caps [R1,R2,R3]) | REFUSED, BROADCAST rec 3 (`…GREEN.log:45-47`) | REFUSED, BROADCAST rec 3 (`…GREEN.log:38-40`) | REFUSED, BROADCAST rec 3 (`…GREEN.log:31-33`) | LOADS, SEQ_CAPS read first (`…GREEN.log:25-26`) |
| mislabelled caps [R1,R2] | REFUSED (`…GREEN.log:50`) | REFUSED (`…GREEN.log:49`) | REFUSED (`…GREEN.log:48`) | LOADS (`…GREEN.log:51`) |
| mislabelled seq_isa 2.2 | REFUSED (`…GREEN.log:54`) | REFUSED (`…GREEN.log:53`) | REFUSED (`…GREEN.log:52`) | LOADS (`…GREEN.log:55`) |
| no capability claim | REFUSED (`…GREEN.log:58`) | REFUSED (`…GREEN.log:57`) | REFUSED (`…GREEN.log:56`) | LOADS (`…GREEN.log:59`) |
| REAL `model_9b_s1_reordB_r3.e4` (sha re-hashed FULL, `…GREEN.log:11`) | REFUSED, BROADCAST rec 53 (`…GREEN.log:81`) | REFUSED (`…GREEN.log:76`) | REFUSED (`…GREEN.log:71`) | LOADS (`…GREEN.log:66`) |
| `chat_seq --seq-rtl r3` (images carry NO manifest) | exit 4 at open_board, names the broadcast (`…GREEN.log:113-114`) | exit 4 (`…GREEN.log:106-107`) | exit 4 (`…GREEN.log:99-100`) | LOADS (`…GREEN.log:120-127`) |

Every refusal read SEQ_CAPS first, so it was device-keyed, and touched no tripwire. `--dry-run
--caps R1,R2` refuses the fixture. `--caps R1,R2,R3` validates and relocates it and uploads nothing
(`…GREEN.log:60-61`).

| case | what | RED n2800 | GREEN n2804 |
|---|---|---|---|
| setup | 0xFAB1CA07 decodes to {R1,R2,R3}; no row reports it; the four r3 streams' FULL sha = R3-5's; chat_seq at 9B; the mock rows gone after | 5/5 | 5/5 |
| (G) | the real Dev._gate: mock R3 named + 0xFAB1CA07 → READY; + 0xFAB1CA03 / 01 / DEADC0DE → REFUSED on SEQ_CAPS; build_041 (default) + 0xFAB1CA07 → REFUSED; R2 VERSION + 0xFAB1CA07 → REFUSED | 6/6 † | 6/6 (`…GREEN.log:13-18`) |
| (a)–(f), (r) | the seq_run matrix above, dry-run, the real stream | 31/31 † | 31/31 |
| (K) | a keyless r3 artifact REFUSED on 0xFAB1CA07 naming the `shape_isa` key; the four r3 manifests declare shape_isa 2; the frozen set is still build_035's three, none r3 | 3/3 † | 3/3 (`…GREEN.log:87-89`) |
| (m) | serve still pins r0 | 1/1 | 1/1 (`…GREEN.log:91`) |
| (g)(h)(i) | chat r3 on 0xFAB1CA03 / 01 / DEADC0DE → exit 4 at open_board, no upload, names the broadcast | 0/6 | 6/6 |
| (j) | chat r3 LOADS on 0xFAB1CA07. The device's {R1,R2,R3} reaches load_template and independent_step_images after the read. 128 / 129 broadcasts; each image is REFUSED naming the broadcast at {R1,R2}, {R1} and {}. images == r3 pins; session caps {R1,R2,R3}; no manifest | 0/7 | 7/7 (`…GREEN.log:120-127`) |
| (k) | r3 with `--reorder A` / `off` / env off → exit 4 naming --seq-rtl before the board; FABLE5_SEQ_RTL=R3 parses; **the model-aware default (auto → B at 9B --nch 4) satisfies check_seq_rtl at r3 as at r2** (docs/USAGE.md §3's clause) | 1/6 | 6/6 (`…GREEN.log:130-139`) |
| (l) | B6 hands SeqExec {} (shipped) and {R1,R2,R3} (reordered); the verifier runs at {R1,R2,R3} | 0/2 | 2/2 (`…GREEN.log:141-142`) |
| (n) | `bm1_ident.judge()` want {R1,R2,R3}: PASS on 0xFAB1CA07, FAIL on 0xFAB1CA03 (pure); `sr14_ident_expect.py --want-version 3b3b3b3b --want-caps R1,R2,R3` exits 0 (8/0) with the mock row injected | 2/3 | 3/3 (`…GREEN.log:144-155`) |
| (p) | r0/r1/r2 pins unchanged; `REORDER_B_PINS_BY_RTL["r3"]` from n2801, equal to its PIN r3 lines | 1/3 | 3/3 (`…GREEN.log:157-159`) |
| (x) | seq_run / chat_seq / serve carry no XPTR identifier | 1/1 | 1/1 (`…GREEN.log:161`) |

† **Passing in RED is the finding, not a vacuous pass.** The RED docstring predicted it and gave
the reason. The 23 RED failures were exactly the predicted set
(`evidence/qwen9b/sr/n2800_r3_6_host_tdd_RED.log:168`).

## 3. The r3 images, their B6 and the static model (E, MODEL)

`sr13b_r2_pins.py --rtl r3` ran on the committed tree a5d0887:

| image | records (shipped → r3) | broadcasts / forced / unicast-left | static model, position 0: program order → r2 replay → r3 replay (corrected prediction r2 → r3) | pin |
|---|---|---|---|---|
| lite | 38,858 → 38,930 | 128 / 0 / 0 | 30,209,477 → 24,341,703 → 22,297,831 cyc (24,377,574 → 22,333,702) (`evidence/qwen9b/sr/n2801_r3_6_pins.log:26`) | `evidence/qwen9b/sr/n2801_r3_6_pins.log:33` |
| full | 39,626 → 39,786 | 129 / 0 / 0 | 32,771,280 → 26,131,018 → 24,087,146 cyc (26,168,056 → 24,124,184) (`evidence/qwen9b/sr/n2801_r3_6_pins.log:28`) | `evidence/qwen9b/sr/n2801_r3_6_pins.log:34` |

Each image validates at {R1,R2,R3}. Each is refused naming the broadcast at {R1,R2}, {R1} and {}
(`evidence/qwen9b/sr/n2801_r3_6_pins.log:13`, `evidence/qwen9b/sr/n2801_r3_6_pins.log:21`). The
hazard assert passes, and the run is deterministic (`evidence/qwen9b/sr/n2801_r3_6_pins.log:24`).
These are the position-0 `replay_mk` / `pred_mk` of the r2 AND r3 images, the input R3-11's
primary prediction needs. They are static-cost MODEL numbers of the chat step images, not tok/s.

**B6 at r3, boardless** (clean committed tree 0296f4b):
`chat_seq.py --nch 4 --seq-rtl r3 --reorder B --reorder-check`. The level resolves to caps
{R1,R2,R3} (`evidence/qwen9b/sr/n2816_r3_6_chat_seq_r3_reorder_check.log:7`). Both images regenerate
equal to their pins, and the hazard assert passes on both
(`evidence/qwen9b/sr/n2816_r3_6_chat_seq_r3_reorder_check.log:9-10`). The shipped images are replayed
at {} and the r3 images at {R1,R2,R3} (the caps the TDD's (l) pins). Tokens [[], [], [513]] = [[],
[], [513]], and the state diff is empty, in 522.3 s
(`evidence/qwen9b/sr/n2816_r3_6_chat_seq_r3_reorder_check.log:22`). The result is REORDER CHECK:
PASS (`evidence/qwen9b/sr/n2816_r3_6_chat_seq_r3_reorder_check.log:23`).

## 4. Regressions and drift (committed tree 0296f4b)

| run | result | log |
|---|---|---|
| `sw/seq_run.py --selftest` (FABLE5_MODEL unset, the baseline's env) | 2850 / 0 = 2840 + R3-6's 10 | `evidence/qwen9b/sr/n2818_r3_6_seq_run_selftest_unset.log:57` (at 9b too: `evidence/qwen9b/sr/n2803_r3_6_seq_run_selftest.log:57`) |
| `sw/chat_seq.py --selftest` | 407 / 1, the known [22] | `evidence/qwen9b/sr/n2819_r3_6_chat_seq_selftest_unset.log:33-36` |
| `sw/serve.py --selftest` | 85 / 0; "args namespace covers chat_seq's args.* reads" **ok** | `evidence/qwen9b/sr/n2820_r3_6_serve_selftest_unset.log:48-50` |
| `sw/hwmap.py` | PASS | `evidence/qwen9b/sr/n2821_r3_6_hwmap_selftest_unset.log:7` |
| boardfree | 2850/0, 85/0 (coverage ok), 407/1 [22]. BOARDFREE_FAIL on [22] alone, as at every baseline | `evidence/qwen9b/sr/n2822_r3_6_boardfree_unset.log:63`, `evidence/qwen9b/sr/n2822_r3_6_boardfree_unset.log:107-109`, `evidence/qwen9b/sr/n2822_r3_6_boardfree_unset.log:140-142` |
| SR6 host TDD | 45 / 0 | `evidence/qwen9b/sr/n2806_r3_6_sr6_host_tdd.log:134` |
| SR13b host TDD | 42 / 0 | `evidence/qwen9b/sr/n2807_r3_6_sr13b_host_tdd.log:118` |
| SR7 host TDD (`--r1 e3c2ff1e`) | 36 / 0 | `evidence/qwen9b/sr/n2808_r3_6_sr7_host_tdd.log:51` |
| SR11a fix 2 / fix 3 TDDs | 12 / 0, 8 / 0 | `evidence/qwen9b/sr/n2809_r3_6_sr11afix2_tdd.log:63`, `evidence/qwen9b/sr/n2810_r3_6_sr11afix3_tdd.log:32` |
| the flagged tools at their defaults | pins r2: R2 PINS PASS, body identical to n1351; ident: 6/0, identical to n2223 | `evidence/qwen9b/sr/n2814_r3_6_r2_pins_default.log:27`, `evidence/qwen9b/sr/n2815_r3_6_ident_expect_default.log:68`, `evidence/qwen9b/sr/n2823_r3_6_default_compare.log:7-8` |

**Cite drift.** `evidence/qwen9b/sr/r3_2_drift.sh` (R3-3's flags) was run at code base 025eadd,
with the doc base the committed 0296f4b (a real commit), over the edited `sw/chat_seq.py` and
`sw/seq_run.py`. It found **355 citations, 355 unmoved, 0 drifted and 0 unresolved** (E:
`evidence/qwen9b/sr/n2817_r3_6_drift_check.log:11-14`). The count is non-zero, so the pass is not
vacuous. `.superpowers/` (gitignored) is outside the tool's committed tree. Its SR17 review note
cites `sw/chat_seq.py:6887-6893`, a range whose help-text content changed in place but whose
lines did not move. The tools' flag edits moved no cited line: no document cites a line of
`sr13b_r2_pins.py` or `sr14_ident_expect.py`.

The run stamps read `+dirty` because of one untracked file, R3-8's in-flight `R3_8_RTL.md`. It is
another task's file and not under test (each log's `=== dirty` line). No tracked file was modified.

## 5. The addendum's items

* **XPTR.** No host path assumes XPTR = 0 after a broadcast. The sweep (`/usr/bin/grep`) found XPTR
  only in `sw/hwmap.py` (the register definition) and in four direct-drive AXI-Lite tools. Those are
  `sw/layer_test.py`, `sw/matvec_test.py`, `sw/infer.py` and `sw/tok_meter.py`, and none issues a SEQ
  stream: each writes XPTR 0 itself before its own XWIN pushes, and `sw/matvec_test.py` asserts XPTR
  only after those pushes. The SEQ-driving tools (seq_run, chat_seq, serve) name no XPTR identifier
  (TDD (x)). The only other `.py` hits are evidence tests of the model and the RTL, which are not
  host tools.
* **The keyless rule is unchanged at r3.** A keyless r3 artifact is refused, the four r3 manifests
  carry `shape_isa: 2`, and the frozen set is still the three build_035 streams (TDD (K)). chat_seq's
  images carry no manifest, and its template is the shipped keyed one.
* **segments().** No host path re-segments an emitted stream. chat_seq calls `reorder_e4.reorder` only
  on the SHIPPED step images (the pass's input; its own segmentation of them is unchanged). On the
  emitted images it calls only `assert_no_pending_hazard`, which is R3-5's broadcast-aware per-channel
  check. seq_run and serve do not import the pass. There was nothing to handle.
* **serve** is untouched. It pins `reorder=None, seq_rtl="r0"` (TDD (m)), and its coverage line is ok.

## 6. Judgment calls

1. **No `docs/USAGE.md` paragraph** (the addendum overrides the plan's file list). There is no R3
   bitstream to run an r3 session on, so `--help` documents r3 (`sw/chat_seq.py:6882`) and the §3
   clause is deferred to R3-12, conditional on R3-10 keeping a bitstream.
2. **A mock R3 VERSION, not a real row.** 0x3B3B3B3B is injected into all three tables together
   (SEQ_VERSIONS, SHAPE, BM_IDENT; the SR17ff minor-2 invariant) and removed after, both in the TDD
   and in `_selftest_r3`. Removal is checked each time. The 0xFAB1CA03 device is the REAL SR14 row,
   not a mock, which is closer to the board than SR13b's mock R2 VERSION.
3. **The real r3 stream through seq_run** needs `--base tb/scripts/w9/model_9b_s1`, because the pass
   writes the stream beside, not inside, the generator's artifacts. The LOAD case then runs the
   whole host path to the upload tripwire: validation at the device's set, relocation, the weight
   plan and the MVGO targets.
4. **The ident expectation at R3 is exercised in-process.** `sr14_ident_expect.py` takes the BM_IDENT
   expectation from hwmap, and no R3 VERSION exists. So the flag run lives in the TDD, which injects
   the mock row and runs the file through `runpy` (8/0). A standalone run needs R3-10's real row.
5. **seq_run's call site.** `_selftest_r3` is called from the last line of `_selftest_sr14` rather
   than from `_selftest` itself. An added line inside `_selftest` would move SR14's cited R2 row
   (`sw/seq_run.py:3699`) and everything after it.
6. **Tripwire semantics carried unchanged from SR6 / SR13b.** For chat_seq, LOADS = `bring_up`
   reached. For seq_run, it is `upload` reached.

## 7. Does NOT establish

* That any bitstream reads 0xFAB1CA07, or that an R3 build admits an r3 session. There is no R3
  VERSION row, so every real board refuses r3 before any DMA today.
* Any chip-TB or board run of the r3 chat images. Their evidence is the model (B6), the hazard
  assert, the post-check and the pins.
* Any speed. The makespans are static-cost MODEL numbers at position 0, and R3-7 / R3-11 own the
  predictions.

## 8. Slips, disclosed

* **Regression operating point.** The first batch ran chat_seq --selftest, serve --selftest, hwmap
  and boardfree at FABLE5_MODEL=9b. Their baselines run unset, and chat_seq's [2] raised on the 9B
  template there (n2805). They were re-run unset as n2818–n2822. n2805, n2811, n2812 and n2813 are
  superseded and committed as a record.
* **The TDD's (x) case was wrong at first.** It counted XPTR as text and so matched the r3 block's
  comment that says no host path reads XPTR: n2802, 71/1, superseded. It now counts NAME tokens
  (commit 0296f4b), and GREEN is n2804. The comment is accurate. The test was naive.
* **darthplagueis.** `python3` was invoked twice with an empty stdin (a mistyped heredoc), which
  executed nothing, and `/home/cah/.venv/bin/python --version` ran once. None ran project code or
  arithmetic. Every logged run was on snoke.
