# SR15 — the R2 board session: token identity fail-closed, the rate measured, build_041 restored

Task SR15 of `docs/superpowers/plans/2026-09-27-seq-rtl-round.md`, run 2026-09-29 05:11 → 06:21 on snoke,
under the user's load ruling (Q9, "yes to both", 2026-09-29) for exactly
`synth/out_build_045_r2_incr/proj/stage1.runs/impl_1/bd_wrapper.bit` (53,080,061 B, sha256
c4caeb09…af8b4dcb) and explicitly NOT its base-roll twin under `synth/out_build_045_r2/`, which carries the
same VERSION / SEQ_CAPS / BM_IDENT. One board, one session, JTAG-volatile only, never flash. The session
repeats SR8's flow (`evidence/qwen9b/sr/SR8_R1_BOARD.md`) on the R2 bitstream.

**Labels.** **E** = printed by a run of this session, cited to its log line. **D** = derived by
`evidence/qwen9b/sr/sr15_board_table.py` or `evidence/qwen9b/sr/sr15_predict.py` on snoke, cited to the
log line that printed it. **T** = transcribed from an earlier gate. **MODEL** = a tok/s from the cost model,
not a board measurement. Cycles are 250 MHz aclk cycles; step time is the per-launch `S_PERF_CYC`, as
BM1-T4, S1P and SR8 took it.

## Verdict

**DONE. Every run's tokens IDENTICAL; identity passed before any DMA; the board is back on build_041.**

* **Identity on R2, read before any DMA:** MAGIC 0xfab1e001, VERSION 0x266e3ae7, CALIB 0xF, BM_IDENT
  0xfab1b301, SEQ_CAPS 0xfab1ca03 = {R1,R2} (the exact word and the decoded set), `IDENT: PASS` from both
  `evidence/qwen9b/sr/sr8_ident.py` and `evidence/qwen9b/bm/bm1_ident.py`
  (**E**, `evidence/qwen9b/sr/n1504_sr15_ident_r2.log:8-16`, `evidence/qwen9b/sr/n1504_sr15_ident_r2.log:20-27`).
  It was read again immediately before the first DMA of the session, the pack upload
  (`evidence/qwen9b/sr/n1505_sr15_r2_lockstep_s1s4.log:17`), and before the first DMA of each later tool.
  This is the first read of SEQ_CAPS 0xfab1ca03 off silicon.
* **Tokens, every run, fail-closed:** the RD9 §7 lockstep on the SHIPPED streams 4/4 IDENTICAL to G4A
  §4.1a, with the `.chip` golden ALL MATCH on each; four chat511 sessions (build_041 form B; the R2 bitstream
  at r0 form B, r1 and **r2**) IDENTICAL to the pinned reference; three stream censuses (r2, r1, r0-B)
  IDENTICAL; the restore sanity IDENTICAL to n77 (**D**, `evidence/qwen9b/sr/n1516_sr15_board_table.log:105`).
* **R2 on silicon, same bitstream, paired by position:** **×1.0319 on the full step (the decode step)** and
  ×1.0310 on lite against r1 (**D**, `evidence/qwen9b/sr/n1516_sr15_board_table.log:61-62`); ×1.0739 / ×1.0589
  against S1 form B, the shipped chat default (**D**, `evidence/qwen9b/sr/n1516_sr15_board_table.log:63-64`);
  ×1.2086 / ×1.2110 against build_041's shipped order (**D**, `evidence/qwen9b/sr/n1516_sr15_board_table.log:69-70`).
* **The rate:** chat decode (full step, context 502..510) **8.182 tok/s** (122.2175 ms), against 7.929 for
  r1 and 7.619 for form B on the same bitstream; the 6-token stream **9.057 tok/s** (110.4066 ms/token)
  against the model's **9.144** — measured/model **0.9905** — and against SR13a's TB MODEL **9.137** — **0.9913** (**D**, `evidence/qwen9b/sr/n901_sr9_derive.log:7-8`;
  `evidence/qwen9b/sr/n1516_sr15_board_table.log:31-35`, `evidence/qwen9b/sr/n1516_sr15_board_table.log:99`).
* **The predictions (committed at 23c9f58, before the R2 bitstream was programmed).** The PRIMARY
  absolute-saving form P1' **HELD on both images (lite +0.048 %, full +0.098 %)**; the ratio form P2' held
  loosely (+0.677 % / +0.583 %); the census form P3' **HELD (+0.184 %)** (**D**,
  `evidence/qwen9b/sr/n1516_sr15_board_table.log:73-76`, `evidence/qwen9b/sr/n1516_sr15_board_table.log:98`).
* **R2 moves neither the shipped order nor r1 nor S1-B:** on the R2 bitstream the shipped-order lockstep is
  +0.0002..+0.0024 % against the R1 bitstream, and the r0-B and r1 chat sessions are −0.0001 % and −0.0011 %
  against SR8's (**D**, `evidence/qwen9b/sr/n1516_sr15_board_table.log:9-12`,
  `evidence/qwen9b/sr/n1516_sr15_board_table.log:79-82`).
* **The board NOW:** build_041, VERSION 0xc973c18a, CALIB 0xF, SEQ_CAPS 0xdeadc0de (**E**,
  `evidence/qwen9b/sr/n1513_sr15_ident_041_restored.log:8-16`), serving the shipped default: the n77 prompt
  answered Paris with n77's 24 ids (**E**, `evidence/qwen9b/sr/n1514_sr15_restore_chat_sanity.log:86`).

## 1. Step by step (the brief's steps 0–7)

| step | log | what | result |
|---|---|---|---|
| — predictions | `evidence/qwen9b/sr/n1515_sr15_predictions.log:31` | sr15_predict.py, no device; committed at 23c9f58 with n1500, before any board action | DONE (§4) |
| 0 pre-flight (read-only) | `evidence/qwen9b/sr/n1500_sr15_preflight.log:85` | lock, hw_server and every vivado/hw_server/xsdb/hw_manager process, attached hw_server clients, boot, PCI ID, identity (raw reads; MUST be build_041), both `.bit` and the twin (size, sha256), r2/r1 stream pins and manifests (full sha256), chat r2/r1 pins (full), the 266e3ae7 admission row, venv, git, other users | PASS: lock not held (:9); hw_server pid 10107 (:13-14); processes listed (:16-17); no established connection to port 3121 (:18-19); boot 2026-09-27 07:08 (:22); 10ee:9038 (:24); build_041 IDENT PASS (:40); R2 `.bit` 53,080,061 B c4caeb09… (:43); the twin de6ad363… differs (:47-48); r2 streams (:50-53); manifests (:60-66); 266e3ae7 row (:75) |
| 0 no reprogram needed | — | the board was on build_041 | n1501 not used |
| 1 control, build_041 | `evidence/qwen9b/sr/n1502_sr15_control_041_chat511.log:84` | chat511 form B, variable unset, fail-closed ids | IDENTICAL; lite 115.0951, full 131.2463 ms (:78, :81); weights resident, 0 MISS (:29) |
| 2 program R2 | `evidence/qwen9b/sr/n1503_sr15_program_r2.log:17` | re-hash (size and sha256), then the safe flow under one lock hold | size and sha256 match the ruling (:7-8); PROGRAM_OK; rescan 82:00.0 9038 (:19); lock held/released (:20-21); rc 0 (:22-24) |
| 3 identity | `evidence/qwen9b/sr/n1504_sr15_ident_r2.log:16` | no DMA | the Verdict's words; PASS (both tools) |
| 4a state + lockstep | `evidence/qwen9b/sr/n1505_sr15_r2_lockstep_s1s4.log:442` | identity again (:17), then g6_state --write-initial, then seq_run --expect-version 266e3ae7 on model_9b_s1..s4 (shipped order), each re-uploading the pack readback-verified | 4/4 IDENTICAL and ALL MATCH (§2) |
| 4b bitstream-alone control | `evidence/qwen9b/sr/n1506_sr15_r2bit_r0B_chat511.log:129` | identity (:16), then chat511 form B, r0 images, FABLE5_SEQ_EXPECT_VERSION=266e3ae7, counters on | IDENTICAL; lite 115.0952, full 131.2479 ms (:101, :115) |
| 4c r1 control | `evidence/qwen9b/sr/n1507_sr15_r2bit_r1_chat511.log:118` | chat511 --seq-rtl r1, same env | IDENTICAL; lite 112.0693, full 126.1135 ms (:90, :104) |
| 5 R2 | `evidence/qwen9b/sr/n1508_sr15_r2_chat511.log:118` | chat511 --seq-rtl r2, same env; images == the r2 pins (:11-12) | IDENTICAL; lite 108.7087, full 122.2175 ms (:90, :104) |
| 5 census r2 / r1 / r0-B | `evidence/qwen9b/sr/n1509_sr15_census_r2.log:48`, `evidence/qwen9b/sr/n1510_sr15_census_r1.log:38`, `evidence/qwen9b/sr/n1511_sr15_census_r0B.log:39` | identity (n1509:16), then the n72/n73 recipe, fresh state, sr8_census.py | PASS, tokens IDENTICAL on all three (§3.2) |
| 6 restore | `evidence/qwen9b/sr/n1512_sr15_restore_041.log:17` | re-hash build_041, safe flow | sha256 eeeef897… matches RD9 §2.1 (:7-8); PROGRAM_OK; rescan 9038 (:19); rc 0 (:22-24) |
| 6 identity | `evidence/qwen9b/sr/n1513_sr15_ident_041_restored.log:16` | no DMA | PASS |
| 6 restore sanity | `evidence/qwen9b/sr/n1514_sr15_restore_chat_sanity.log:86` | the n77 prompt, 24 ids fail-closed, variable unset, default form B | IDENTICAL; 47 witness misses → pack re-uploaded 5,842 MiB readback-verified in 29.5 s (:27-29) |
| 7 table | `evidence/qwen9b/sr/n1516_sr15_board_table.log:106` | sr15_board_table.py | DONE, exit 0 |
| — closing status | `evidence/qwen9b/sr/n1517_sr15_readonly_status.log:8` | read-only | lock not held (:8); hw_server 10107 (:11); no port-3121 client (:12); 9038 (:13); boot unchanged (:14) |

**No UI cut was taken** (SR14 kept the 300 MHz UI), so the brief's `sw/ddr_test.py` step did not apply; CALIB
0xF was read on R2 at n1504 and again by every SEQ-driving tool's own gate.

**Identity words read on R2** (the table the addendum names): MAGIC 0xfab1e001, VERSION 0x266e3ae7,
CALIB 0x0000000f, LAYER/SEQ/TOPK idents as build_041, BM_IDENT 0xfab1b301, SEQ_CAPS 0xfab1ca03
(**E**, `evidence/qwen9b/sr/n1504_sr15_ident_r2.log:7-15`). Every SEQ-driving tool on R2 then admitted the
bitstream only by name and read the device's caps itself: the chat sessions print VERSION 0x266e3ae7,
SEQ=READY and caps R1,R2 from SEQ_CAPS 0xfab1ca03 (**E**, `evidence/qwen9b/sr/n1508_sr15_r2_chat511.log:26-28`),
seq_run validated every shipped stream at capabilities R1,R2 (**E**,
`evidence/qwen9b/sr/n1505_sr15_r2_lockstep_s1s4.log:31-35`), and so did the census tool (**E**,
`evidence/qwen9b/sr/n1509_sr15_census_r2.log:19`).

## 2. RD9 §7 on R2 — the four-seed lockstep on the shipped streams

`evidence/qwen9b/g6/g6_state.py --write-initial` placed the initial region, bit-exact on chip (**E**,
`evidence/qwen9b/sr/n1505_sr15_r2_lockstep_s1s4.log:26-27`). Each seed then ran a full `sw/seq_run.py`
(pack re-uploaded and read back, `evidence/qwen9b/sr/n1505_sr15_r2_lockstep_s1s4.log:49-50` for s1).
These are the addendum's "shipped control streams": SR14's closure is thin, so a failure here would have
been the bitstream, not the software.

| seed | tokens vs G4A §4.1a | `.chip` golden | device ms | vs n805 (R1 bitstream) | cite |
|---|---|---|---|---|---|
| s1 | IDENTICAL | 36,886 checks, ALL MATCH | 822.860 | +0.0009 % | `evidence/qwen9b/sr/n1505_sr15_r2_lockstep_s1s4.log:120-126` |
| s2 | IDENTICAL | ALL MATCH | 822.865 | +0.0011 % | `evidence/qwen9b/sr/n1505_sr15_r2_lockstep_s1s4.log:226-232` |
| s3 | IDENTICAL | ALL MATCH | 822.863 | +0.0002 % | `evidence/qwen9b/sr/n1505_sr15_r2_lockstep_s1s4.log:332-338` |
| s4 | IDENTICAL | ALL MATCH | 822.864 | +0.0024 % | `evidence/qwen9b/sr/n1505_sr15_r2_lockstep_s1s4.log:433-439` |

The script check is `evidence/qwen9b/sr/n1516_sr15_board_table.log:9-12` (**D**). The shipped-order stream on
the R2 bitstream keeps BM1's idle structure (FENCE 41.96 %, MVANY 42.18 %), and its cycles are 1.000009 × the
R1 bitstream's (**D**, `evidence/qwen9b/sr/n1516_sr15_board_table.log:13`) — the chip TB said zero cycles
(SR13a rung 1).

## 3. The rate

### 3.1 Chat at context 511 (per-launch means, 502 lite + 9 full)

| run | bitstream / images | lite ms | full ms | full tok/s | FENCE % (full) | cite |
|---|---|---|---|---|---|---|
| n68 (T) | build_041, shipped order | 131.6174 | 147.7088 | 6.770 | — | `evidence/qwen9b/sr/n1516_sr15_board_table.log:18-19` |
| n802 (T) | build_041, form B | 115.0932 | 131.2455 | 7.619 | — | `evidence/qwen9b/sr/n1516_sr15_board_table.log:22-23` |
| n806 (T) | R1 bitstream, r0 form B | 115.0954 | 131.2474 | 7.619 | 35.45 | `evidence/qwen9b/sr/n1516_sr15_board_table.log:24-25` |
| n807 (T) | R1 bitstream, r1 | 112.0705 | 126.1149 | 7.929 | 31.90 | `evidence/qwen9b/sr/n1516_sr15_board_table.log:26-27` |
| **n1502** | build_041, form B | 115.0951 | 131.2463 | 7.619 | — | `evidence/qwen9b/sr/n1516_sr15_board_table.log:28-29` |
| **n1506** | R2 bitstream, r0 form B | 115.0952 | 131.2479 | 7.619 | 35.45 | `evidence/qwen9b/sr/n1516_sr15_board_table.log:30-31` |
| **n1507** | R2 bitstream, r1 | 112.0693 | 126.1135 | 7.929 | 31.89 | `evidence/qwen9b/sr/n1516_sr15_board_table.log:32-33` |
| **n1508** | R2 bitstream, **r2** | **108.7087** | **122.2175** | **8.182** | **29.73** | `evidence/qwen9b/sr/n1516_sr15_board_table.log:34-35` |

Paired by position (**D**, `evidence/qwen9b/sr/n1516_sr15_board_table.log:53-70`):

| pair | lite | full |
|---|---|---|
| n1502 vs n802 — build_041, SR15's and SR8's sessions, 1 h 24 min apart (`evidence/qwen9b/sr/n901_sr9_derive.log:13`) | +0.0016 % (sd 0.0026) | +0.0006 % |
| n1506 vs n1502 — **the bitstream alone** (R2 vs build_041, both r0 B) | +0.0002 % (sd 0.0025) | +0.0012 % |
| n1506 vs n806 — R2 vs R1 bitstream, both r0 B | −0.0001 % | +0.0004 % |
| n1507 vs n807 — **R2 vs R1 bitstream, both r1 (R2 must not move R1)** | −0.0011 % (sd 0.0055) | −0.0011 % |
| **n1508 vs n1507 — r2 vs r1, same bitstream** | **×1.0310** (sd 0.0012, ×1.0287..×1.0333) | **×1.0319** (sd 0.0001) |
| n1508 vs n1506 — r2 vs S1-B, same bitstream | ×1.0589 | ×1.0739 |
| n1508 vs n1502 — r2 vs build_041 form B (the shipped chat default) | ×1.0589 | ×1.0739 |
| n1508 vs n68 — r2 vs build_041 shipped order | ×1.2110 | ×1.2086 |

* **The bitstream alone moves the step by ≤ 0.0012 %**, far below the R2 effect, and R2's netlist does not move
  R1's number (−0.0011 %, inside the addendum's ±0.5 % by three orders of magnitude). So the R2 gain is the r2
  images' double banking, not the netlist.
* **The absolute R2 saving per launch** is 3.3606 ms (lite) and 3.8960 ms (full) against r1 on the same
  bitstream (**D**, `evidence/qwen9b/sr/n1516_sr15_board_table.log:83-84`); the static model's saving for the
  same image pair was 3.4137 / 4.0173 ms (**D**, `evidence/qwen9b/sr/n1515_sr15_predictions.log:9-10`).
* **MOVX / MOVY work is unchanged by R2** (3,237,605 vs 3,237,573 MOVX cycles per lite launch), while the
  FENCE wait drops from 31.89 % to 29.73 % of a full step (**D**,
  `evidence/qwen9b/sr/n1516_sr15_board_table.log:33-35`, `evidence/qwen9b/sr/n1516_sr15_board_table.log:47-50`).

### 3.2 The 6-token stream census (model_9b_s1 form B, fresh state, per token)

| run | ms/token | tok/s | MVANY % | FENCE (C5) % | tokens | cite |
|---|---|---|---|---|---|---|
| n72 (T) build_042_bm1, shipped order | 137.1195 | 7.293 | 42.19 | **41.96** | IDENTICAL | `evidence/qwen9b/sr/n1516_sr15_board_table.log:89` |
| n809 (T) R1 bitstream, r0 form B | 120.5354 | 8.296 | 48.40 | 38.50 | IDENTICAL | `evidence/qwen9b/sr/n1516_sr15_board_table.log:90` |
| n808 (T) R1 bitstream, r1 | 114.3839 | 8.742 | 56.44 | 35.12 | IDENTICAL | `evidence/qwen9b/sr/n1516_sr15_board_table.log:91` |
| n1511 R2 bitstream, r0 form B | 120.5367 | 8.296 | 48.40 | 38.50 | IDENTICAL | `evidence/qwen9b/sr/n1516_sr15_board_table.log:92` |
| n1510 R2 bitstream, r1 | 114.3885 | 8.742 | 56.44 | 35.12 | IDENTICAL | `evidence/qwen9b/sr/n1516_sr15_board_table.log:93` |
| **n1509 R2 bitstream, r2** | **110.4066** | **9.057** | 55.37 | **32.78** | IDENTICAL | `evidence/qwen9b/sr/n1516_sr15_board_table.log:94` |

* r2 / r1 on the same bitstream: **×1.0361** against the chip TB's ×1.0379; r2 vs n72's shipped order ×1.2420
  against the TB's ×1.2528 (**D**, `evidence/qwen9b/sr/n1516_sr15_board_table.log:95`). For R1 the stream ratio
  reproduced the TB to four digits (SR8 §3.2); for R2 silicon keeps a little less than the TB's ratio (not
  attributed here; the census prediction P3', which uses the TB's body ratio, HELD, §4).
* The census controls on the R2 bitstream equal SR8's on the R1 bitstream: r1 +0.0041 %, r0-B +0.0011 % (**D**,
  `evidence/qwen9b/sr/n1516_sr15_board_table.log:96-97`).
* **The stream tok/s beside the model:** 9.057 measured against spec §3.1's 9.144 (MODEL), ratio **0.9905**; against SR13a's TB MODEL 9.137 (`evidence/qwen9b/sr/n1349g_sr13a_derive.log:25`), **0.9913** (**D**, `evidence/qwen9b/sr/n901_sr9_derive.log:8`; added by SR9)
  (−0.95 %, inside ±2 %, outside ±0.5 %) (**D**, `evidence/qwen9b/sr/n1516_sr15_board_table.log:99`).
* **The C5 FENCE-wait share** falls 41.96 % (shipped) → 38.50 % (S1-B) → 35.12 % (R1) → 32.78 % (R2); per token
  14.38 M → 11.60 M → 10.04 M → 9.05 M cycles (**D**, `evidence/qwen9b/sr/n1516_sr15_board_table.log:100`).

## 4. The predictions and the band verdict

Committed before the R2 bitstream was programmed (`evidence/qwen9b/sr/n1515_sr15_predictions.log`, commit
23c9f58). Band method: SR5b's, as SR8 — |measured / predicted − 1| ≤ 0.5 % HELD, ≤ 2 % HELD LOOSELY, else
MISSED. A report, not a gate (acceptance as SR8); the tokens are the gate.

| prediction | lite | full | cite |
|---|---|---|---|
| **P1' (PRIMARY): n807 − the r1→r2 absolute saving per chat image** | 108.6569 → 108.7087 ms, **+0.048 % HELD** | 122.0975 → 122.2175 ms, **+0.098 % HELD** | `evidence/qwen9b/sr/n1516_sr15_board_table.log:73`, `evidence/qwen9b/sr/n1516_sr15_board_table.log:75` |
| P2' (ratio): n807 / 1.0379 | 107.9782, +0.677 % loosely | 121.5097, +0.583 % loosely | `evidence/qwen9b/sr/n1516_sr15_board_table.log:74`, `evidence/qwen9b/sr/n1516_sr15_board_table.log:76` |
| **P3' (census): n808 × 26,171,253 / 27,163,998** | 110.2036 → 110.4066 ms/token, **+0.184 % HELD** | — | `evidence/qwen9b/sr/n1516_sr15_board_table.log:98` |
| controls n1502 = n802, n1506 = n806, n1507 = n807 | +0.0016 %, −0.0001 %, −0.0011 % HELD | +0.0006 %, +0.0004 %, −0.0011 % HELD | `evidence/qwen9b/sr/n1516_sr15_board_table.log:77-82` |
| census controls n1510 = n808, n1511 = n809 | +0.0041 %, +0.0011 % HELD | — | `evidence/qwen9b/sr/n1516_sr15_board_table.log:96-97` |
| lockstep = n805 | +0.0002..+0.0024 % HELD | — | `evidence/qwen9b/sr/n1516_sr15_board_table.log:9-12` |

**Which saving P1' used, and why.** No chip-TB run of the r2 chat images exists (SR13b's "NOT established"), so
P1''s saving is the static model's r1-image makespan minus its r2-image makespan at position 0 — the same model
on both sides — lite 25,195,119 − 24,341,703 and full 27,135,354 − 26,131,018 cycles (`evidence/qwen9b/sr/n601_r1_pins.log:9`,
`evidence/qwen9b/sr/n601_r1_pins.log:15`, `evidence/qwen9b/sr/n1351_sr13b_r2_pins.log:9`, `evidence/qwen9b/sr/n1351_sr13b_r2_pins.log:15`).
The stream-scaled alternative (SR13a's token-4 body saving, 3.9710 ms per launch) was printed beside it as a
reference, not a prediction (`evidence/qwen9b/sr/n1515_sr15_predictions.log:15`). **Note (SR9, from the SR15 review):** P1' used n1351's uncorrected replay makespans; SR13b's corrected ones on the same lines (24,377,574 / 26,168,056 cyc) give P1' 108.8004 / 122.2457 ms, −0.084 % / −0.023 % against n1508 — still HELD (**D**, `evidence/qwen9b/sr/n901_sr9_derive.log:11-12`).

**Reading.** SR8's lesson held a second time: at context ≈ 510 the saving is a fixed number of cycles per launch,
so the absolute form lands inside ±0.1 % on both images, while the ratio form over-predicts (it scales the saving
by the attention time that grows with position). P2' is inside ±2 % on both; not attributed by class (the band
does not require it for the primary, and the model is not a gate).

## 5. RD9 rungs — run and not run

**Run:** §2 the reprogram (n1503, n1512); §3 identity with VERSION off the silicon, CALIB, BM_IDENT and
SEQ_CAPS (n1504, n1513, and re-read before each tool's first DMA); §5 (a) the weight pack per piece,
readback-verified on every upload (n1505 ×4, n1514); §7 the four-seed token lockstep against G4A §4.1a after
`g6_state.py --write-initial`, with the `.chip` golden (n1505); §8 chat with token identity by `--want-ids`
(n1502, n1506, n1507, n1508, n1514); §10 step time by the counters (the B16 block on R2, n1505–n1511).

**Not run** (as SR8): §6 the state region bit-exact against `state_final.bin`
(`g6_state.py --readback`); §8.7 long context — context stayed ≤ 511, T < 512
(`rtl/attn_core.sv:114`'s ceiling); §9 EMBLOG2's discriminating proof (EMBLOG2 read 13 on the R2
bitstream, `evidence/qwen9b/sr/n1509_sr15_census_r2.log:28`, which is not that proof). `sw/ddr_test.py`: not run
(no UI cut, §1).

## 6. Judgment calls and deviations, each recorded

1. **Tools.** `evidence/qwen9b/sr/sr15_preflight.sh` is sr8_preflight.sh retargeted to R2 with the SR8 review's
   minors made hard checks: PREFLIGHT: PASS requires build_041's identity (no auto-program); every
   vivado/hw_server/xsdb/hw_manager process is listed, and an ESTABLISHED TCP connection to hw_server's port 3121
   (an attached hw_manager client) fails it; the r2 and r1 stream pins and the r2 chat pins are checked on the FULL
   sha256; the twin's sha256 is recorded to show it differs. `sr8_ident.py`, `sr8_census.py` ran UNCHANGED (by
   argument). `sr15_board_table.py` is a retargeted copy of `sr8_board_table.py` (hard-coded log names), and
   `sr15_predict.py` is new. Each was committed before its first use (cff0ac3, bd2d399).
2. **The unattributed process.** The pre-flight listed a `vivado-mcp` Python process (pid 1132425) on snoke besides
   hw_server 10107 (`evidence/qwen9b/sr/n1500_sr15_preflight.log:16-17`). It had no established connection to
   hw_server's port (`evidence/qwen9b/sr/n1500_sr15_preflight.log:18-19`), so no hw_manager client was attached;
   the rule passed and it is recorded, not attributed. The closing status again shows no port-3121 client
   (`evidence/qwen9b/sr/n1517_sr15_readonly_status.log:12`).
3. **Identity before every DMA-capable tool's first run** (the addendum's (i)): n1505 re-read identity
   immediately before g6_state's 155 MiB DMA; n1506 before the chat tool's first run; n1509 before the census
   tool's first run. Each is inside the same logged command, with `|| exit` so a failure stops before any DMA.
4. **Predictions numbered n1515** and run before n1500; the step logs keep SR8's n8xx → n15xx offsets (n1501
   unused: no pre-session reprogram), n1516 the table, n1517 the closing status, n1520… the doc gates.
5. **The chat sessions passed `--reorder B` explicitly** and ran with `FABLE5_REORDER` / `FABLE5_SEQ_RTL` removed
   from the environment; n1506 passed `--seq-rtl r0` explicitly, as SR8's n806.
6. **The restore sanity used `evidence/qwen9b/bm/bm1_census.py --chat`** around the n77 command (as SR8's n812),
   because `sw/chat_seq.py` has no `--want-ids`.
7. **One +dirty stamp, not an input:** n1511's names n1509's and n1510's just-written JSONs, which the census does
   not read.
8. **The background launches.** The long steps were started with `nohup` on snoke through an ssh whose command
   also tailed the log; one of those local ssh wrappers (n1502's) reported exit 1 because its `head` raced the log's
   creation (NFS). The runs themselves are judged by their own `=== rc` lines, all 0.
9. **An empty `python3 - <<EOF` heredoc** was run once on darthplagueis while writing a file (it executed no
   statement). No arithmetic, no project code; every number here came from a snoke log.
10. **The cite-drift pass.** SR15's NEXT_SESSION.md edit (a §1 paragraph, the §1/§3 rows, a §6 paragraph) moved
    lines that five other documents cite — the same five as SR8's pass. `evidence/qwen9b/sr/sr15_drift.sh` (the o3
    tool at base 2c66d67) planned 7 repairs and 0 collateral (`evidence/qwen9b/sr/n1521_sr15_drift_plan.log:15-16`),
    fixed 18 citations in 5 documents (`evidence/qwen9b/sr/n1522_sr15_drift_fix.log:19`) and verified
    (`evidence/qwen9b/sr/n1524_sr15_drift_verify.log:20`); the G3_3 historical token moved 465 → 475, as every
    earlier pass moved it. **Two mis-invocations, kept as evidence and superseded:** n1523 ran `--verify` with the
    doc-base `WORKTREE`, which the o3 tool accepted and read 0 citations from (a vacuous PASS; n1524 is the real
    verify); n1526 ran the baseline with this gate doc in its file list, which does not exist at the base, so the
    base side counted 0 keys and every FAIL looked introduced (n1527 is the real baseline, the list SR8 used).
    spec_cites over the five plus NEXT_SESSION.md and this doc reports 21 FAILs
    (`evidence/qwen9b/sr/n1525_sr15_spec_cites_touched.log:6`), all pre-existing: the line-free baseline at 2c66d67
    has the same 21, 0 introduced (`evidence/qwen9b/sr/n1527_sr15_spec_cites_baseline.log:7`,
    `evidence/qwen9b/sr/n1527_sr15_spec_cites_baseline.log:13`; SR8's n825 carried them too). The LAST run is over
    this doc and NEXT_SESSION.md alone.

## 7. What this does NOT establish

* **One session per condition**, one prompt, context ≤ 511, `--ntok 9`; the spread is the paired per-position one,
  not repeated sessions.
* **No sampled decode, no `--verify`, no `--prefill full` T-curve** on R2.
* **The whole 511-step r2 session is checked on silicon by its tokens only**; the r2 images' B6 replays positions
  0 and 1 (SR13b §3).
* **The state region's final image** was not read back (§5); the `.chip` golden covers the lockstep runs.
* **The r2 streams s2..s4 on silicon** — only the s1 r2 stream ran (the census); the lockstep ran the shipped
  streams, as SR8.
* **Sign-off of anything but R2's function on this workload** — build_045's timing sign-off is SR14's
  (`evidence/qwen9b/sr/SR14_R2_BUILD.md` §2.3: WNS +0.004 closed inside route_design, a margin of one placement).

## 8. Logs and tools

| file | what |
|---|---|
| `evidence/qwen9b/sr/n1500_sr15_preflight.log` | step 0 |
| `evidence/qwen9b/sr/n1502_sr15_control_041_chat511.log` (+ .json) | step 1 |
| `evidence/qwen9b/sr/n1503_sr15_program_r2.log`, `evidence/qwen9b/sr/n1504_sr15_ident_r2.log` | steps 2–3 |
| `evidence/qwen9b/sr/n1505_sr15_r2_lockstep_s1s4.log` (+ four .json) | step 4 lockstep |
| `evidence/qwen9b/sr/n1506_sr15_r2bit_r0B_chat511.log`, `evidence/qwen9b/sr/n1507_sr15_r2bit_r1_chat511.log`, `evidence/qwen9b/sr/n1508_sr15_r2_chat511.log` (+ .json) | steps 4–5 chat |
| `evidence/qwen9b/sr/n1509_sr15_census_r2.log`, `evidence/qwen9b/sr/n1510_sr15_census_r1.log`, `evidence/qwen9b/sr/n1511_sr15_census_r0B.log` (+ .json) | step 5 census |
| `evidence/qwen9b/sr/n1512_sr15_restore_041.log`, `evidence/qwen9b/sr/n1513_sr15_ident_041_restored.log`, `evidence/qwen9b/sr/n1514_sr15_restore_chat_sanity.log` (+ .json) | step 6 |
| `evidence/qwen9b/sr/n1515_sr15_predictions.log`, `evidence/qwen9b/sr/n1516_sr15_board_table.log`, `evidence/qwen9b/sr/n1517_sr15_readonly_status.log` | predictions, table, closing status |
| `evidence/qwen9b/sr/n1520_sr15_spec_cites.log` … `evidence/qwen9b/sr/n1527_sr15_spec_cites_baseline.log` | the doc gates (§6 item 10); the LAST spec_cites is n1528 |
| `evidence/qwen9b/sr/sr15_preflight.sh`, `evidence/qwen9b/sr/sr15_predict.py` (cff0ac3), `evidence/qwen9b/sr/sr15_board_table.py` (bd2d399), `evidence/qwen9b/sr/sr15_drift.sh` (8407250), `evidence/qwen9b/sr/sr15_spec_cites_baseline.sh` (0a17178) | tools, each committed before first use |
