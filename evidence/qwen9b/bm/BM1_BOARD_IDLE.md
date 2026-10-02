# BM1-T4: the idle counters on silicon, and S1 on silicon

**Status: DONE (2026-09-27).** The board is back on the SHIPPED build_041
(`evidence/qwen9b/bm/n76_T4_ident_041_restored.log:7`).

## 0. How to read this

Every number carries a label:
- **T**: transcribed from a committed log.
- **D**: derived, with the arithmetic in `evidence/qwen9b/bm/bm1_board_table.py`, which ran on snoke as
  `evidence/qwen9b/bm/n84_T4fix1_board_table.log` (fix round 1; it supersedes the first table log, n78, whose rows it repeats one line lower). Its `+dirty` stamp (`evidence/qwen9b/bm/n84_T4fix1_board_table.log:2-3`) is the working copy of `bm1_board_table.py` at the time, modified against `672c5af`; the T4 fix-round re-review re-ran the script at HEAD and got byte-identical output (overlap ledger, BM1-T4 minors, 2026-09-27; that re-run is not a committed log).
- **S**: stated by a source document.
- **E**: an exact equality that a script checked.

All board steps ran on snoke through `evidence/qwen9b/bm/bm_run.sh`. Clock: aclk 250 MHz.

The instrumented bitstream is the roll with a **MEASUREMENT-ONLY timing waiver**:
- build_042_bm1 `ckr2b_ExtraNetDelay_low`, VERSION 0x9b588e78, WNS −0.124.
- Its detectors of a real violation are the token checks and the control run.
- Both passed (§2, §3).

Two kinds of run:
- **Chat sessions:** the committed 16-copy long-context prompt at context 511, `--ntok 9`.
  They run through `evidence/qwen9b/bm/bm1_chat511.sh` and `evidence/qwen9b/bm/bm1_census.py`,
  which record both lanes and the B16 block for every launch.
- **Stream censuses:** the 6-token `model_9b_s1` stream, the RD9 §10 path.
  These are the direct comparand for the chip-TB census.

## 1. The board's idle structure, against the chip-TB census

Stream census, per token. Every percentage is a fraction of `PERF_CYC` (**D**, rows 9–11 of
`evidence/qwen9b/bm/n84_T4fix1_board_table.log:10-12`).

| run | cyc/token | ms/token | weight path busy (C0 MVANY) | FENCE wait (C5) | mover work (C6) | issue FSM in I_MOVER (C8) | L_LCYC | per-channel max/min |
|---|---|---|---|---|---|---|---|---|
| chip TB census (S, BM1_T1_GATE §3.2) | 32,784,469 | 131.1379 | 41.53 % | 41.47 % | 24.82 % | 66.32 % | 31.73 % | 1.0042 |
| **board BM1, shipped order** (n72) | 34,279,887 | 137.1195 | **42.19 %** | **41.96 %** | **24.23 %** | **66.21 %** | 30.33 % | 1.0043 |
| board BM1, S1 form A (n73) | 30,891,384 | 123.5655 | 47.06 % | 40.11 % | 20.28 % | 60.41 % | 33.66 % | 1.0093 |

Sources:
- **TB comparands.** The TB row's registers are G1's
  (`evidence/qwen9b/bm/BM1_T1_GATE.md:193`, `evidence/qwen9b/bm/BM1_T1_GATE.md:198`,
  `evidence/qwen9b/bm/BM1_T1_GATE.md:199`, `evidence/qwen9b/bm/BM1_T1_GATE.md:202`,
  `evidence/qwen9b/bm/BM1_T1_GATE.md:224`).
  - The mover-work comparand follows ruling B2: C6 alone against BN_CENSUS §9.1(i-b)'s
    "mover work, nothing streaming" row, 24.82 % (`evidence/qwen9b/bn/BN_CENSUS.md:651`).
  - The weight-streaming row there is 41.49 % (`evidence/qwen9b/bn/BN_CENSUS.md:648`).
  - I_MOVER is 66.32 % (`evidence/qwen9b/bn/BN_CENSUS.md:972`).
- **Board rows.** The raw registers are at `evidence/qwen9b/bm/n72_T4_bm1_stream_model_9b_s1.log:19`
  and `evidence/qwen9b/bm/n73_T4_bm1_stream_reordA.log:19`. Both runs' tokens are IDENTICAL
  (`evidence/qwen9b/bm/n72_T4_bm1_stream_model_9b_s1.log:35`,
  `evidence/qwen9b/bm/n73_T4_bm1_stream_reordA.log:35`).

**Reading.**
1. **The board has the TB's idle structure, to within about 0.6 points on every counter.** The FENCE wait is 41.96 % vs 41.47 %. Mover work is 24.23 % vs 24.82 %. Any-engine busy is 42.19 % vs 41.53 %. The weight path is idle for 57.81 % of the step vs 58.47 % (**D**, `evidence/qwen9b/bm/n84_T4fix1_board_table.log:17`).
2. **The board step is 4.56 % longer than the TB step, and the weight path accounts for it.** The ratios below are board/TB per counter (**D**, `evidence/qwen9b/bm/n84_T4fix1_board_table.log:14`).

   | counter | board/TB |
   |---|---|
   | whole step | 1.0456 |
   | MVANY | 1.0622 |
   | per-channel engine busy | 1.058 each |
   | FENCE | 1.0579 |
   | L_LCYC | **0.9995** |
   | MOVX | 1.0072 |
   | MOVY | 1.0171 |

   - The layer compute lane matches the TB to 0.05 %.
   - The extra cycles are in engine-busy time, and the FENCE waits for it. That fits real DDR streaming more slowly than the TB's memory model. It is an inference: nothing here counts R-beats (D4).
   - RD9 §10.2a left open why the compute lane read 9.9 % below the *draining* census. This board run reads it equal to the non-draining chip TB, which supports RD9's "different instruments" candidate. It is not a proof.
3. **The step time reproduces RD9.** n72's 137.1195 ms/token is RD9 §10's 137.1210 on build_041, 0.001 % apart (`evidence/qwen9b/g6/RD9_GATE.md:1447`).
4. **At context ≈ 510 (chat), the mix shifts toward attention and the state DMA.** The per-launch means for a BM1 full step are:

   | counter | % of the step |
   |---|---|
   | FENCE | 38.95 |
   | MVWORK | 22.49 |
   | MVANY | 39.16 |
   | IMOVER | 61.46 |
   | L_LCYC | 35.31 |
   | L_SDMA | 4.36 |

   (**D**, `evidence/qwen9b/bm/n84_T4fix1_board_table.log:26`.)
5. **C7 MVWORK_ANY** is 0.26 % of the stream step. It is reported without a census comparand (erratum E1). Its board/TB ratio of 3.0 is on a quantity of 544,692 cycles per launch. "Mover work with no engine busy" (C6 − C7) is 8,213,862 cycles per token (**D**, `evidence/qwen9b/bm/n84_T4fix1_board_table.log:15`).

## 2. Does the instrumented bitstream move the step time?

It does not. Same prompt, same context of 511, same `--ntok 9`, per-launch means:

| launch kind | build_041 control (n68) | BM1 (n71) | BM1 / 041 |
|---|---|---|---|
| lite, 502 launches | 131.6174 ms | 131.6154 ms | **−0.0015 %** |
| full, 9 launches | 147.7088 ms | 147.7082 ms | **−0.0004 %** |

- **Numbers.** **D**, `evidence/qwen9b/bm/n84_T4fix1_board_table.log:31-32`. The raw lines are
  `evidence/qwen9b/bm/n68_T4_control_041_chat511.log:65`,
  `evidence/qwen9b/bm/n68_T4_control_041_chat511.log:68`,
  `evidence/qwen9b/bm/n71_T4_bm1_chat511.log:78` and
  `evidence/qwen9b/bm/n71_T4_bm1_chat511.log:92`.
- **Tokens.** Both runs produced `[760, 20438, 18253, 5134, 421, 279, 3177, 314, 11751]`
  (`evidence/qwen9b/bm/n68_T4_control_041_chat511.log:46`, `evidence/qwen9b/bm/n71_T4_bm1_chat511.log:48`).
  That is the first nine ids of the pinned reference (`evidence/qwen9b/g6/083_longctx_9b.log:93`).
- **Lanes.** They agree too: L_LCYC is 34.80 / 35.31 % on both bitstreams.
- **Token identity is checked by a script, not by eye** (fix round 1, I2). `evidence/qwen9b/bm/bm1_board_table.py` compares the reply ids of n68, n71 and n74 with the pinned reference and exits 1 on any difference. It printed IDENTICAL for all three (`evidence/qwen9b/bm/n84_T4fix1_board_table.log:31`). Future runs fail closed through `bm1_census.py --chat --want-ids`, set via `$BM1_WANT_IDS` in `bm1_chat511.sh`. Its boardless TDD went RED (`evidence/qwen9b/bm/n80_T4fix1_ids_test_RED.log`), then GREEN 9/0 on the committed tree (`evidence/qwen9b/bm/n83_T4fix1_ids_test_GREEN.log`); a one-id difference exits non-zero and prints both lists.
- **The paired spread** (fix round 1). The lite step time rises with position, so only launches at the same position are compared across sessions (**D**, `evidence/qwen9b/bm/n84_T4fix1_board_table.log:36-39`).
  - lite, BM1 vs 041 over 502 positions: mean −0.0015 %, sd 0.0022 %, range −0.0087 .. +0.0049 %.
    The mean is resolved (|mean|/SE 15.7) but it is about 490 cycles in a 33-million-cycle step.
  - full, over 9 positions: −0.0004 ± 0.0015 %, which is not resolved (0.80 SE).
  - Either way, the instrumented bitstream's effect on the step is below 0.01 % at every position.
- **The waiver.** Under the −0.124 ns waiver, on this workload the tokens are identical, and there is no per-step change above 0.01 % (−0.0015 % resolved at 15.7 SE, `evidence/qwen9b/bm/n84_T4fix1_board_table.log:36`).

## 3. S1 (form A, ruling B7) on silicon

**The gate ran before the board was touched** (ruling B6; `sw/chat_seq.py` `--reorder A`).
- The tool regenerates the reordered template in-process, and it must equal the SV1-gated pin `b6ced3f9…` byte for byte.
- The hazard assert passed, and the postcheck found 0 violations on 220,008 edges (`evidence/qwen9b/bm/n74_T4_bm1_chat511_reordA.log:16`).
- The B6 model gate replays shipped-order and reordered images and requires an exact match. It PASSED in 510 s (`evidence/qwen9b/bm/n74_T4_bm1_chat511_reordA.log:29`).
- TDD, all green in the end:
  - RED: `evidence/qwen9b/bm/n61_T4_reorder_tdd_RED.log:24`.
  - GREEN: `evidence/qwen9b/bm/n62_T4_reorder_tdd_GREEN_dirty.log:45`.
  - The B6 gate is exact on the real images: `evidence/qwen9b/bm/n63_T4_reorder_tdd_GREEN_slow.log:52`.
  - With the flag OFF, the images are byte-identical to the pre-flag tool, on the clean tree 850b504: `evidence/qwen9b/bm/n63_T4_reorder_tdd_GREEN_slow.log:13-15`.
  - **The negative test, as rebuilt in fix round 1 (I1).** Both arms use a lite override patched exactly like the gate's own step (tok 760 @ pos 0). The only difference between them is one CSRWR L_ARG1 imm32 bit.
    The UNCORRUPTED control arm PASSES the gate, and the corrupted arm FAILS it. Both results are on the clean tree 672c5af (`evidence/qwen9b/bm/n85_T4fix1_reorder_tdd_T6b_clean2.log:52`, `evidence/qwen9b/bm/n85_T4fix1_reorder_tdd_T6b_clean2.log:61`); the whole TDD is 16/0 (`evidence/qwen9b/bm/n85_T4fix1_reorder_tdd_T6b_clean2.log:62`).
    The corrupted arm still emits token 513, and the gate catches it by the STATE: 37,171 scratch words differ (`evidence/qwen9b/bm/n85_T4fix1_reorder_tdd_T6b_clean2.log:60`). That is why the gate compares the whole machine state and the region, not only the tokens.
    n82 is the same run with an identical result, but its tree stamp read "+dirty" from an NFS stat artifact (`git status` was clean on both hosts right after), so n85 is the one cited.
    The earlier n64 run is SUPERSEDED: its override skipped the patch, so its FAIL did not isolate the corruption.
  - The S1 speed-up is also PAIRED by position: lite ×1.1149 (sd 0.0030, range ×1.1099 .. ×1.1202, 502 positions); full ×1.1010 (sd < 0.0001) (**D**, `evidence/qwen9b/bm/n84_T4fix1_board_table.log:37`, `evidence/qwen9b/bm/n84_T4fix1_board_table.log:39`).

| | shipped order (BM1) | S1 form A (BM1) | speed-up | TB (SV1) |
|---|---|---|---|---|
| chat lite, ctx ≤ 511 | 131.6154 ms | 118.0582 ms | **1.1148×** | — |
| chat full, ctx 502..510 | 147.7082 ms | 134.1548 ms | **1.1010×** | — |
| 6-token stream | 137.1195 ms/token | 123.5655 ms/token | **1.1097×** | 1.1117× (131.138 → 117.959, **S**, `evidence/qwen9b/ov/SV1_S1_VERIFY.md:32-34`) |

- **Timings.** **D**, `evidence/qwen9b/bm/n84_T4fix1_board_table.log:16`,
  `evidence/qwen9b/bm/n84_T4fix1_board_table.log:31-32`. The raw lines are
  `evidence/qwen9b/bm/n74_T4_bm1_chat511_reordA.log:93` and
  `evidence/qwen9b/bm/n74_T4_bm1_chat511_reordA.log:107`.
- **Tokens are IDENTICAL on silicon.** The chat run gave the reference ids
  (`evidence/qwen9b/bm/n74_T4_bm1_chat511_reordA.log:63`), and the stream gave its six tokens
  (`evidence/qwen9b/bm/n73_T4_bm1_stream_reordA.log:35`).
- **Channel-3 contention.** This is the test the TB could not run: the state region sits on DDR
  channel 3 while S1 overlaps streams with state-DMA commands. On the stream, S1 reaches 1.1097×
  on the board vs 1.1117× in the TB.
  - The absolute saving is larger on the board: 13.55 ms/token vs 13.18.
  - Channel 3's engine-busy time grows by only 0.19 % under S1 (86,004,642 vs 85,838,765, **T**, `evidence/qwen9b/bm/n73_T4_bm1_stream_reordA.log:25`, `evidence/qwen9b/bm/n72_T4_bm1_stream_model_9b_s1.log:25`).
  - No divergence and no measurable contention cost. It stays bounded by what the counters see (§4).

**Counters under S1 vs shipped order, BM1 full chat step** (**D**, `evidence/qwen9b/bm/n84_T4fix1_board_table.log:26`,
`evidence/qwen9b/bm/n84_T4fix1_board_table.log:29`):

| counter | shipped order | S1 form A |
|---|---|---|
| FENCE | 38.95 % | 36.94 % |
| MVWORK | 22.49 % | 18.68 % |
| MVANY | 39.16 % | 43.35 % |
| I_MOVER | 61.46 % | 55.64 % |

- MOVX drops from 5,294,619 to 3,254,633 cycles per launch, from the elided moves (**T**, `evidence/qwen9b/bm/n71_T4_bm1_chat511.log:104`, `evidence/qwen9b/bm/n74_T4_bm1_chat511_reordA.log:119`).
- The weight path is busy for a larger share of a shorter step, which is the overlap S1 was built to create.

## 4. What this does NOT establish

1. **Form B is not run on silicon.** Ruling B7 deferred it: `derive_geometry` refuses its template. (Superseded 2026-09-27: S1P ran form B on silicon, n95, `evidence/qwen9b/ov/S1P_SHIP.md` §3.)
2. **No R-beat counts (D4).** "The weight path streams more slowly on the board" (§1, reading 2) is inferred from engine-busy time, not measured in bytes per cycle.
3. **One session per condition.**
   - The spec's four-run spread (§5 step 6) and the `--prefill full` T-curve (§5 step 7) were not run.
   - The per-launch spread inside a session is in n84, table 2; the PAIRED spread across sessions is in §2.
   - The four TB seeds are replaced by 502 lite + 9 full launches of one prompt.
4. **The timing waiver is not closed.** A token match and an identical step time on one workload are not a sign-off for the −0.124 ns roll.
5. **S1 is measured through the chat tool only at context ≤ 511**, and the B6 gate replays only preamble + one lite + one full step. The whole 511-step session is checked on silicon only by its tokens.
6. **What the B6 replay covers.**
   - It replays EMITTER-space images (data_delta 0) at pos 0 and pos 1 only: preamble, one lite step, one full step.
   - The RELOCATED bytes the board runs are covered separately, by the session's agent-A cross-check and the relocation readback.
   - Every other position is checked on silicon only by its tokens.
   - The gate runs inside `chat_seq` after the board lock is taken, so a `--reorder A` session holds the lock for about 510 s before it touches the board (`evidence/qwen9b/bm/n74_T4_bm1_chat511_reordA.log:29`).
7. **`NEXT_SESSION.md` §1 is stale.** The board lost power (snoke reboots of 09-18..09-20 and 09-27), so the weight pack and the state region were re-uploaded several times. That section was not updated here, because it is outside this task's files.
8. **The weight pack is re-uploaded after every reprogram, because DDR does not survive one.**
   - Cold (first after power-up): 347 s (`evidence/qwen9b/bm/n68_T4_control_041_chat511.log:16`).
   - Warm: 29 s (`evidence/qwen9b/bm/n71_T4_bm1_chat511.log:18`).
   - Both uploads were readback-verified.
9. **Two cycles of edge uncertainty per busy window** on silicon (spec §7 item 4). The TB's cycle-exactness does not transfer.

## 5. Traceability

| step | log | result |
|---|---|---|
| JTAG census | `evidence/qwen9b/bm/n53_T4_jtag_list.log:35` | one target, xcvu9p_0 |
| program 041 / load / ident (controller, on the user's authority) | n65 / n66 / n67 (commit ce781bc) | IDENT PASS |
| step 1 control | `evidence/qwen9b/bm/n68_T4_control_041_chat511.log:4` | env unset; pack re-uploaded (`evidence/qwen9b/bm/n68_T4_control_041_chat511.log:16`) |
| step 2 program BM1 | `evidence/qwen9b/bm/n69_T4_program_bm1.log:14` | PROGRAM_OK, rescan 9038 (`evidence/qwen9b/bm/n69_T4_program_bm1.log:16`) |
| identity BM1 | `evidence/qwen9b/bm/n70_T4_ident_bm1.log:13` | VERSION 0x9b588e78 (`evidence/qwen9b/bm/n70_T4_ident_bm1.log:7`), BM_IDENT at SEQ 0x100 (`evidence/qwen9b/bm/n70_T4_ident_bm1.log:12`) |
| step 3 instrumented | `evidence/qwen9b/bm/n71_T4_bm1_chat511.log:4` | env 9b588e78; SEQ READY (`evidence/qwen9b/bm/n71_T4_bm1_chat511.log:14`) |
| stream census | `evidence/qwen9b/bm/n72_T4_bm1_stream_model_9b_s1.log:19`, `evidence/qwen9b/bm/n73_T4_bm1_stream_reordA.log:19` | §1 |
| step 4 S1 | `evidence/qwen9b/bm/n74_T4_bm1_chat511_reordA.log:4` | §3 |
| step 5 restore | `evidence/qwen9b/bm/n75_T4_restore_041.log:14`; `evidence/qwen9b/bm/n76_T4_ident_041_restored.log:13` | VERSION 0xc973c18a |
| restore sanity | `evidence/qwen9b/bm/n77_T4_restore_chat_sanity.log:47`, `evidence/qwen9b/bm/n77_T4_restore_chat_sanity.log:56` | Paris; full 137.7 ms |
| table (fix round 1) | `evidence/qwen9b/bm/n84_T4fix1_board_table.log:10-39` | §1–§3, token assert, paired spread |

**Tools**, each committed before use:
- `evidence/qwen9b/bm/bm1_census.py`
- `evidence/qwen9b/bm/bm1_chat511.sh`
- `evidence/qwen9b/bm/bm1_ident.py`
- `evidence/qwen9b/bm/bm1_jtag_list.tcl`
- `evidence/qwen9b/bm/bm1_board_table.py`
- `evidence/qwen9b/bm/bm1_reorder_tdd.py`
- `sw/chat_seq.py` (`--reorder`)

**Bitstream sha256:**
- build_041: `eeeef897495d783a…`, 53,074,589 B.
- BM1 roll: `73d9e93d922491d2…`, 52,710,545 B.
- The BM1 roll's `.mmi` comes from the same implementation run.
