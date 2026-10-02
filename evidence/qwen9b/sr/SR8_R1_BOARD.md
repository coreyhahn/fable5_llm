# SR8 — the R1 board session: token identity fail-closed, the rate measured, build_041 restored

Task SR8 of `docs/superpowers/plans/2026-09-27-seq-rtl-round.md`, run 2026-09-29 03:46 → 04:47 on snoke,
under the user's load ruling (Q9, "yes to both", 2026-09-29) for exactly
`synth/out_build_044_r1_incr/proj/stage1.runs/impl_1/bd_wrapper.bit` (53,076,057 B, sha256
92a2e525…b50816). One board, one session, JTAG-volatile only, never flash.

**Labels.** **E** = printed by a run of this session, cited to its log line. **D** = derived by
`evidence/qwen9b/sr/sr8_board_table.py` or `evidence/qwen9b/sr/sr8_predict.py` on snoke, cited to the
log line that printed it. **T** = transcribed from an earlier gate. Cycles are 250 MHz aclk cycles;
step time is the per-launch `S_PERF_CYC`, as BM1-T4 and S1P took it.

## Verdict

**DONE. Every run's tokens IDENTICAL; identity passed before any DMA; the board is back on build_041.**

* **Identity on R1, read before any DMA:** VERSION 0xe3c2ff1e, CALIB 0xF, BM_IDENT 0xfab1b301,
  SEQ_CAPS 0xfab1ca01 = {R1} (the exact word and the decoded set), `IDENT: PASS` from both
  `evidence/qwen9b/sr/sr8_ident.py` and `evidence/qwen9b/bm/bm1_ident.py`
  (**E**, `evidence/qwen9b/sr/n804_sr8_ident_r1.log:8-16`, `evidence/qwen9b/sr/n804_sr8_ident_r1.log:20-27`).
  This is the first non-empty SEQ_CAPS word read off silicon; the pre-flight had read build_041's 0xdeadc0de 14 min earlier (`evidence/qwen9b/sr/n800_sr8_preflight.log:32`; corrected by SR9).
* **Tokens, every run, fail-closed:** the RD9 §7 lockstep 4/4 IDENTICAL to G4A §4.1a with the `.chip`
  golden ALL MATCH on each; four chat511 sessions IDENTICAL to the pinned reference; both stream
  censuses IDENTICAL; the restore sanity IDENTICAL to n77 (**D**,
  `evidence/qwen9b/sr/n813_sr8_board_table.log:78`).
* **R1 on silicon, same bitstream, paired by position:** ×1.0271 (lite, 502 positions, sd 0.0032) and
  **×1.0407 (full, the decode step)** against S1 form B (**D**,
  `evidence/qwen9b/sr/n813_sr8_board_table.log:44-45`); ×1.1747 / ×1.1712 against build_041's shipped
  order (**D**, `evidence/qwen9b/sr/n813_sr8_board_table.log:48-49`).
* **The rate:** chat decode (full step, context 502..510) **7.929 tok/s** (126.1149 ms), against 7.619
  for form B on the same bitstream; the 6-token stream **8.742 tok/s** (114.3839 ms/token) against the
  model's **8.811** — measured/model **0.9922** (**D**,
  `evidence/qwen9b/sr/n813_sr8_board_table.log:27-28`, `evidence/qwen9b/sr/n813_sr8_board_table.log:72`).
* **The stream ratio reproduces the chip TB exactly:** r1 vs its r0-B control on the same bitstream
  ×1.0538, the TB's ×1.0538 (**D**, `evidence/qwen9b/sr/n813_sr8_board_table.log:71`).
* **The predictions (committed at 286dbde, before any R1 run).** The controller's P1 (n95 / 1.054)
  **MISSED on lite (+2.63 %)** and held loosely on full (+1.28 %); the absolute-saving P3 **HELD on lite
  (+0.25 %)** and held loosely on full (+0.52 %) (**D**,
  `evidence/qwen9b/sr/n813_sr8_board_table.log:52-57`). The model is not a gate (acceptance); §4 reads it.
* **The board NOW:** build_041, VERSION 0xc973c18a, CALIB 0xF, SEQ_CAPS 0xdeadc0de (**E**,
  `evidence/qwen9b/sr/n811_sr8_ident_041_restored.log:8-16`), serving the shipped default: the n77
  prompt answered Paris with n77's 24 ids (**E**, `evidence/qwen9b/sr/n812_sr8_restore_chat_sanity.log:86`).

## 1. Step by step (the brief's steps 0–7)

| step | log | what | result |
|---|---|---|---|
| 0 pre-flight (read-only) | `evidence/qwen9b/sr/n800_sr8_preflight.log:70` | lock, hw_server, boot, PCI ID, identity (raw reads), both `.bit` sha256, r1 stream pins, chat r1 pins, venv, git, other users | PASS: lock not held (:9), hw_server pid 10107 (:13), boot 2026-09-27 07:08 = NEXT_SESSION §1 (:16), 10ee:9038 (:18), build_041 IDENT PASS (:34), R1 `.bit` 53,076,057 B sha256 92a2e525…b50816 (:37), build_041 53,074,589 B eeeef897… (:39) |
| 0 no reprogram needed | — | the board was on build_041 | n801 not used |
| 1 control, build_041 | `evidence/qwen9b/sr/n802_sr8_control_041_chat511.log:84` | chat511 form B, variable unset, fail-closed ids | IDENTICAL; lite 115.0932, full 131.2455 ms (:78, :81); weights resident, 0 MISS (:29) |
| 2 program R1 | `evidence/qwen9b/sr/n803_sr8_program_r1.log:17` | re-hash, then the safe flow under one lock hold | sha256 matches the ruling (:7-8); PROGRAM_OK; rescan 82:00.0 9038 (:19); rc 0 (:24) |
| 3 identity | `evidence/qwen9b/sr/n804_sr8_ident_r1.log:16` | no DMA | the Verdict's words; PASS |
| 4a state + lockstep | `evidence/qwen9b/sr/n805_sr8_r1_lockstep_s1s4.log:431` | g6_state --write-initial, then seq_run --expect-version e3c2ff1e on model_9b_s1..s4 (shipped order), each re-uploading the pack readback-verified | 4/4 IDENTICAL and ALL MATCH (§2) |
| 4b bitstream-alone control | `evidence/qwen9b/sr/n806_sr8_r1bit_r0B_chat511.log:119` | chat511 form B, r0 images, FABLE5_SEQ_EXPECT_VERSION=e3c2ff1e, counters on | IDENTICAL; lite 115.0954, full 131.2474 ms (:91, :105) |
| 5 R1 | `evidence/qwen9b/sr/n807_sr8_r1_chat511.log:118` | chat511 --seq-rtl r1, same env | IDENTICAL; lite 112.0705, full 126.1149 ms (:90, :104) |
| 5 census r1 / r0-B | `evidence/qwen9b/sr/n808_sr8_census_r1.log:37`, `evidence/qwen9b/sr/n809_sr8_census_r0B.log:38` | the n72/n73 recipe, fresh state | PASS, tokens IDENTICAL both (§3) |
| 6 restore | `evidence/qwen9b/sr/n810_sr8_restore_041.log:17` | re-hash build_041, safe flow | sha256 eeeef897… matches RD9 §2.1 (:7-8); PROGRAM_OK; rescan 9038 (:19); rc 0 (:24) |
| 6 identity | `evidence/qwen9b/sr/n811_sr8_ident_041_restored.log:16` | no DMA | PASS |
| 6 restore sanity | `evidence/qwen9b/sr/n812_sr8_restore_chat_sanity.log:86` | the n77 prompt, 24 ids fail-closed, variable unset, default form B | IDENTICAL; pack re-uploaded 5,842 MiB readback-verified in 29.5 s (:29) |
| 7 table | `evidence/qwen9b/sr/n813_sr8_board_table.log:79` | sr8_board_table.py | DONE, exit 0 |

**Identity words read on R1** (the table the addendum names): MAGIC 0xfab1e001, VERSION 0xe3c2ff1e,
CALIB 0x0000000f, LAYER/SEQ/TOPK idents as build_041, BM_IDENT 0xfab1b301, SEQ_CAPS 0xfab1ca01
(**E**, `evidence/qwen9b/sr/n804_sr8_ident_r1.log:8-15`). Every SEQ-driving tool on R1 then admitted the
bitstream only by name and read the device's caps itself: the chat sessions print VERSION 0xe3c2ff1e,
SEQ=READY and caps R1 from SEQ_CAPS 0xfab1ca01 (**E**, `evidence/qwen9b/sr/n807_sr8_r1_chat511.log:26-28`),
seq_run validated every stream at capabilities R1 (**E**,
`evidence/qwen9b/sr/n805_sr8_r1_lockstep_s1s4.log:23`), and so did the census tool (**E**,
`evidence/qwen9b/sr/n808_sr8_census_r1.log:8`).

## 2. RD9 §7 on R1 — the four-seed lockstep

`evidence/qwen9b/g6/g6_state.py --write-initial` placed the initial region, hash-checked on chip
(**E**, `evidence/qwen9b/sr/n805_sr8_r1_lockstep_s1s4.log:12`). Each seed then ran a full `sw/seq_run.py`
(pack re-uploaded and read back: 105.3 s cold for s1, `evidence/qwen9b/sr/n805_sr8_r1_lockstep_s1s4.log:43`).

| seed | tokens vs G4A §4.1a | `.chip` golden | device ms | cite |
|---|---|---|---|---|
| s1 | IDENTICAL | 36,886 checks, ALL MATCH | 822.853 | `evidence/qwen9b/sr/n805_sr8_r1_lockstep_s1s4.log:108-115` |
| s2 | IDENTICAL | ALL MATCH | 822.856 | `evidence/qwen9b/sr/n805_sr8_r1_lockstep_s1s4.log:214-221` |
| s3 | IDENTICAL | ALL MATCH | 822.861 | `evidence/qwen9b/sr/n805_sr8_r1_lockstep_s1s4.log:320-327` |
| s4 | IDENTICAL | ALL MATCH | 822.844 | `evidence/qwen9b/sr/n805_sr8_r1_lockstep_s1s4.log:421-428` |

The script check is `evidence/qwen9b/sr/n813_sr8_board_table.log:9-12` (**D**). The shipped-order
stream on the R1 bitstream has BM1's idle structure to the hundredth: FENCE 41.96 %, MVANY 42.18 %, and
its step is 1.000165 × n72's on build_042_bm1 (**D**, `evidence/qwen9b/sr/n813_sr8_board_table.log:13-14`).
RD9's seed-1 device times on build_041 were 822.726–822.806 ms (**T**, `evidence/qwen9b/g6/RD9_GATE.md` §7.1);
R1's shipped-order runs read 822.844–822.861 ms.

## 3. The rate

### 3.1 Chat at context 511 (per-launch means, 502 lite + 9 full)

| run | bitstream / images | lite ms | full ms | full tok/s | FENCE % (full) | cite |
|---|---|---|---|---|---|---|
| n68 (T) | build_041, shipped order | 131.6174 | 147.7088 | 6.770 | — | `evidence/qwen9b/sr/n813_sr8_board_table.log:19-20` |
| n95 (T) | build_041, form B | 115.0934 | 131.2454 | 7.619 | — | `evidence/qwen9b/sr/n813_sr8_board_table.log:21-22` |
| **n802** | build_041, form B | 115.0932 | 131.2455 | 7.619 | — | `evidence/qwen9b/sr/n813_sr8_board_table.log:23-24` |
| **n806** | R1 bitstream, r0 form B | 115.0954 | 131.2474 | 7.619 | 35.45 | `evidence/qwen9b/sr/n813_sr8_board_table.log:25-26` |
| **n807** | R1 bitstream, **r1** | **112.0705** | **126.1149** | **7.929** | **31.90** | `evidence/qwen9b/sr/n813_sr8_board_table.log:27-28` |

Paired by position (**D**, `evidence/qwen9b/sr/n813_sr8_board_table.log:40-49`):

| pair | lite | full |
|---|---|---|
| n802 vs n95 — the same bitstream two days apart | −0.0002 % (sd 0.0024) | +0.0001 % |
| n806 vs n802 — **the bitstream alone** (R1 vs build_041, both r0 B) | +0.0019 % (sd 0.0023, 18.5 SE) | +0.0014 % |
| **n807 vs n806 — R1 vs S1-B, same bitstream** | **×1.0271** (sd 0.0032, ×1.0219..×1.0332) | **×1.0407** (sd 0.0001) |
| n807 vs n802 — R1 vs build_041 form B | ×1.0271 | ×1.0407 |
| n807 vs n68 — R1 vs build_041 shipped order | ×1.1747 | ×1.1712 |

* **The bitstream alone moves the step +0.002 %**, resolved (18.5 SE) but far below the R1 effect —
  BM1's precedent was −0.0015 % (**T**, `evidence/qwen9b/bm/BM1_BOARD_IDLE.md:92`). So the R1 gain is
  the masked FENCEs, not the netlist.
* **The absolute R1 saving per launch** is 3.025 ms (lite) and 5.133 ms (full) (**D**,
  `evidence/qwen9b/sr/n813_sr8_board_table.log:62-63`); the chip TB's short-context saving was 3.298 /
  5.784 ms (**D**, `evidence/qwen9b/sr/n815_sr8_predictions.log:9`, `evidence/qwen9b/sr/n815_sr8_predictions.log:13`).
  Silicon keeps less of it on the full step than on lite (not attributed; §4).
* **MOVX / MOVY work is unchanged by R1** (3,237,575 vs 3,237,632 cycles per lite launch; the same
  elision), and the FENCE wait drops from 35.45 % to 31.90 % of a full step while MVANY rises from 44.54 %
  to 51.61 % (**D**, `evidence/qwen9b/sr/n813_sr8_board_table.log:26-37`).

### 3.2 The 6-token stream census (model_9b_s1 form B, fresh state, per token)

| run | ms/token | tok/s | MVANY % | FENCE (C5) % | tokens | cite |
|---|---|---|---|---|---|---|
| n72 (T) build_042_bm1, shipped order | 137.1195 | 7.293 | 42.19 | **41.96** | IDENTICAL | `evidence/qwen9b/sr/n813_sr8_board_table.log:68` |
| n809 R1 bitstream, r0 form B | 120.5354 | 8.296 | 48.40 | 38.50 | IDENTICAL | `evidence/qwen9b/sr/n813_sr8_board_table.log:69` |
| **n808 R1 bitstream, r1** | **114.3839** | **8.742** | 56.44 | **35.12** | IDENTICAL | `evidence/qwen9b/sr/n813_sr8_board_table.log:70` |

* r1 / r0-B on the same bitstream: **×1.0538 — the chip TB's ×1.0538** (SR5b); r1 vs n72's shipped order
  ×1.1988 against the TB's ×1.2070 (**D**, `evidence/qwen9b/sr/n813_sr8_board_table.log:71`).
* **The stream tok/s beside the model:** 8.742 measured against spec §3.1's 8.811, ratio **0.9922**
  (−0.78 %, inside ±2 %, outside ±0.5 %) (**D**, `evidence/qwen9b/sr/n813_sr8_board_table.log:72`).
* **The C5 FENCE-wait share** falls 41.96 % (shipped) → 38.50 % (S1-B) → 35.12 % (R1); per token
  14.38 M → 11.60 M → 10.04 M cycles (**D**, `evidence/qwen9b/sr/n813_sr8_board_table.log:73`).

## 4. The predictions and the band verdict

Committed before any R1 run (`evidence/qwen9b/sr/n815_sr8_predictions.log`, commit 286dbde). Band
method: SR5b's — |measured / predicted − 1| ≤ 0.5 % HELD, ≤ 2 % HELD LOOSELY, else MISSED. A report,
not a gate (SR8 acceptance).

| prediction | lite | full | cite |
|---|---|---|---|
| P1 (the controller's): n95 / 1.054 | 109.197 → 112.071 ms, **+2.63 % MISSED** | 124.521 → 126.115, +1.28 % loosely | `evidence/qwen9b/sr/n813_sr8_board_table.log:52`, `evidence/qwen9b/sr/n813_sr8_board_table.log:55` |
| P2: n95 / the chip TB's per-image ratio (×1.0327 / ×1.0532) | 111.449, +0.56 % loosely | 124.616, +1.20 % loosely | `evidence/qwen9b/sr/n813_sr8_board_table.log:53`, `evidence/qwen9b/sr/n813_sr8_board_table.log:56` |
| P3: n95 − the TB's absolute saving | 111.795, **+0.25 % HELD** | 125.461, +0.52 % loosely | `evidence/qwen9b/sr/n813_sr8_board_table.log:54`, `evidence/qwen9b/sr/n813_sr8_board_table.log:57` |
| controls n802, n806 = n95 | −0.0002 %, +0.0017 % HELD | +0.0001 %, +0.0015 % HELD | `evidence/qwen9b/sr/n813_sr8_board_table.log:58-61` |

**Reading.** ×1.054 is the chip TB's R1-vs-S1-B on the 6-token *stream*, and on silicon the stream
reproduced it exactly (§3.2). The chat images are different streams: their TB ratio is ×1.0327 (lite)
and ×1.0532 (full) at short context (SR5b §5), so P1 over-predicted the lite step by construction. At
context ≈ 510 the attention time that nothing overlaps grows, and R1's saving is a roughly fixed number
of cycles, so a ratio model dilutes and an absolute one does not — S1P's own precedent (silicon kept
99.2 % / 98.9 % of the TB's absolute S1 saving, `evidence/qwen9b/sr/n815_sr8_predictions.log:18-19`) is
why P3 was stated. P3 held on lite; full sits 0.52 % over P3. Not attributed by class here (the band did not require it for P3; SR5b §7 names the FENCE-tail
model error that the masked groups carry).

## 5. RD9 rungs — run and not run

**Run:** §2 the reprogram (n803, n810); §3 identity with VERSION off the silicon, CALIB, BM_IDENT and
SEQ_CAPS (n804, n811); §5 (a) the weight pack per piece, readback-verified on every upload (n805 ×4,
n812); §7 the four-seed token lockstep against G4A §4.1a after `g6_state.py --write-initial`, with the
`.chip` golden (n805); §8 chat with token identity by `--want-ids` (n802, n806, n807, n812); §10 step
time by the counters (the B16 block on R1, n806–n809).

**Not run** (as the brief states): §6 the state region bit-exact against `state_final.bin`
(`g6_state.py --readback`); §8.7 long context — context stayed ≤ 511, T < 512
(`rtl/attn_core.sv:114`'s ceiling); §9 EMBLOG2's discriminating proof (EMBLOG2 read 13 on the R1
bitstream, `evidence/qwen9b/sr/n808_sr8_census_r1.log:17`, which is not that proof).

## 6. Judgment calls and deviations, each recorded

1. **`evidence/qwen9b/sr/sr8_census.py` is a copy of `evidence/qwen9b/bm/bm1_census.py`** with one
   change in `--stream` mode: the Dev is opened first and the stream validated and relocated at the
   DEVICE's caps and SHAPE layout, as `sw/seq_run.py`'s main does. bm1_census validates at the empty set
   and refuses every r1 stream (`evidence/qwen9b/sr/SR6_HOST.md` §6 item 10), so the brief's "bm1_census
   stream mode" could not run the r1 census. Both census arms (r1 and its r0-B control) used the copy,
   with the n72/n73 recipe unchanged (fresh state, lanes cleared, B16 read after HALT). `--chat` mode was
   not used from the copy.
2. **`sr8_ident.py` imports bm1_ident's REGS and judge()** rather than re-typing them, and adds the exact
   SEQ_CAPS word check (0xFAB1CA01 for {R1}, 0xDEADC0DE for the empty set, both from `sw/hwmap.py`).
   Boardless selftest 10/0 (`evidence/qwen9b/sr/n814_sr8_ident_selftest.log:17`). Step 3 also ran
   bm1_ident itself, the addendum's named tool.
3. **Three predictions, not one.** The addendum's (P1) is stated as primary; P2 and P3 were added before
   any run, with the reason in the script's header (`evidence/qwen9b/sr/sr8_predict.py`).
4. **The chat sessions passed `--reorder B` explicitly** (form B is the default at 9B `--nch 4`; n95 passed
   it too) and ran with `FABLE5_REORDER` / `FABLE5_SEQ_RTL` removed from the environment; n806 passed
   `--seq-rtl r0` explicitly.
5. **The restore sanity used `evidence/qwen9b/bm/bm1_census.py --chat`** around the n77 command, because
   `sw/chat_seq.py` has no `--want-ids`; the want list is n77's 24 ids
   (`evidence/qwen9b/bm/n77_T4_restore_chat_sanity.log:48`). n77 ran the shipped order; n812 ran the
   default form B and produced the same 24 ids.
6. **Two +dirty stamps, neither an input.** n806's stamp names the then-uncommitted
   `sr8_board_table.py` (committed at 5bef86b before its first use); n809's names n808's just-written
   JSON. Neither file is read by those runs.
7. **Log numbering:** n800–n813 as the brief assigns (n801 unused: no pre-session reprogram); n814 the
   ident selftest, n815 the predictions, n816 the closing read-only status; n820–n826 the doc gates.
8. **The cite-drift pass.** SR8's NEXT_SESSION.md edit (§1 gained a paragraph) moved lines that five
   other documents cite. `evidence/qwen9b/sr/sr8_drift.sh` (the o3 tool at base a4cf5e6) planned 7
   repairs and 0 collateral (`evidence/qwen9b/sr/n821_sr8_drift_plan.log:16`), rewrote 7 citation tokens on 6 lines (commit 0fb3c9a's diff; the tool's "FIXED 15 citation(s)" counts the (file, line) pairs it read — wording by SR9) in 5
   documents (`evidence/qwen9b/sr/n822_sr8_drift_fix.log:19`) and verified
   (`evidence/qwen9b/sr/n823_sr8_drift_verify.log:20`). One rewrite is a historical token in
   `evidence/qwen9b/g3/G3_3_MATVEC.md` ("…:454 was rewritten away" → 465); every earlier drift pass
   moved that token the same way (git history of the line: 162 → … → 449 → 454), so the precedent was
   followed. spec_cites over those five plus NEXT_SESSION.md reports 21 FAILs
   (`evidence/qwen9b/sr/n824_sr8_spec_cites_last.log:6`), all pre-existing: the line-free baseline at
   a4cf5e6 has the same 21, 0 introduced (`evidence/qwen9b/sr/n825_sr8_spec_cites_baseline.log:7`,
   `evidence/qwen9b/sr/n825_sr8_spec_cites_baseline.log:13`; SR7's n745 carried them too). The LAST run
   is over this doc and NEXT_SESSION.md alone.
9. **The drift commit 0fb3c9a was made on snoke** (darthplagueis's NFS view lagged on three of the five
    files), so its author line is snoke's git identity; path-limited, trailer included.
10. **Rule slip, disclosed.** `python3` ran once on darthplagueis as a text editor (a string replace
   that created sr8_census.py from its copy). No arithmetic, no project code executed.

## 7. What this does NOT establish

* **One session per condition**, one prompt, context ≤ 511, `--ntok 9`; the spread is the paired
  per-position one, not repeated sessions.
* **No sampled decode, no `--verify`, no `--prefill full` T-curve** on R1.
* **The whole 511-step R1 session is checked on silicon by its tokens only**; B6 replays positions 0 and 1
  (S1P §5 applies unchanged).
* **The state region's final image** was not read back (§5); the `.chip` golden covers the lockstep runs.
* **Sign-off of anything but R1's function on this workload** — build_044's timing sign-off is SR7's.

## 8. Logs and tools

| file | what |
|---|---|
| `evidence/qwen9b/sr/n800_sr8_preflight.log` | step 0 |
| `evidence/qwen9b/sr/n802_sr8_control_041_chat511.log` (+ .json) | step 1 |
| `evidence/qwen9b/sr/n803_sr8_program_r1.log`, `evidence/qwen9b/sr/n804_sr8_ident_r1.log` | steps 2–3 |
| `evidence/qwen9b/sr/n805_sr8_r1_lockstep_s1s4.log` (+ four .json) | step 4 lockstep |
| `evidence/qwen9b/sr/n806_sr8_r1bit_r0B_chat511.log`, `evidence/qwen9b/sr/n807_sr8_r1_chat511.log` (+ .json) | steps 4–5 chat |
| `evidence/qwen9b/sr/n808_sr8_census_r1.log`, `evidence/qwen9b/sr/n809_sr8_census_r0B.log` (+ .json) | step 5 census |
| `evidence/qwen9b/sr/n810_sr8_restore_041.log`, `evidence/qwen9b/sr/n811_sr8_ident_041_restored.log`, `evidence/qwen9b/sr/n812_sr8_restore_chat_sanity.log` (+ .json) | step 6 |
| `evidence/qwen9b/sr/n813_sr8_board_table.log` | step 7 |
| `evidence/qwen9b/sr/n814_sr8_ident_selftest.log`, `evidence/qwen9b/sr/n815_sr8_predictions.log` | tool test, predictions |
| `evidence/qwen9b/sr/sr8_ident.py`, `evidence/qwen9b/sr/sr8_census.py`, `evidence/qwen9b/sr/sr8_predict.py`, `evidence/qwen9b/sr/sr8_preflight.sh` (9f5a072), `evidence/qwen9b/sr/sr8_board_table.py` (5bef86b) | tools, each committed before first use |
