# R-b HW GATE — the widened bitstream reproduces the FULL 0.8B ladder (2026-08-16)

Board: **BCU-1525 on snoke**, PCIe 82:00.0, Gen3 x8. Bitstream:
`synth/out_build_034_po2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper.bit`
(50,115,049 B, mtime 2026-08-14 17:50:51), netlist **`4f908df2`** — read back
from the VERSION CSR on silicon after the reprogram. Programmed by the safe
JTAG flow (`pcie_helper.sh remove` → `program_fpga.sh` → `pcie_helper.sh
rescan`), **volatile only, flash never touched**. Host tree `3c4bccc` on branch
`qwen2b` plus the four `sw/` edits this gate required (below); the *netlist* is
`4f908df2` and that is what the VERSION CSR asserts.

**This bitstream ships with WNS −0.025 / WHS +0.001 under a written user
waiver** — `evidence/qwen2b/rb/TIMING.md` §5 (authoritative per-endpoint
census) and §6 (the waiver, re-affirmed 2026-08-16 on the corrected rationale).
50 failing setup endpoints of 1,193,865, all custom RTL, in three classes:
A `mvchan_2/u_chan/u_engine` 24 EP (−0.025…−0.007, ch2 UI clock),
B `layer_0/u_core` 23 EP (18 in `u_dn`, −0.011…−0.001, 250 MHz),
C `seq_0/u_seq` MOV addressing 3 EP (−0.010, −0.003, −0.002, 250 MHz).
The waiver's stated mitigation is that **every rung below is bit-exact**, so a
real silicon setup failure is a detectable mismatch, not silent drift. This
document is the arbiter the waiver named. **Result: the ladder reproduces
build_033 exactly, and the three watch-item domains are clean — with the
channel-2 comparison done directly rather than inferred (§ Watch items).**

**Outcome: R-b HW gate PASS. The board's resident bitstream is now build_034
(`out_build_034_po2_AltSpreadLogic_high`, `4f908df2`).**

---

## Headline

Two amortization conventions are reported throughout, because the project has
both on the record and they differ by the session-once 8.671 ms preamble:

- **gate convention** — `device_ms / 6`, the basis of build_033's published
  46.46 / 32.94 and of the 30.4 tok/s ladder number;
- **steady-state** — `(device_ms − 8.671) / 6`, the corrected basis from
  `evidence/qwen2b/ra/MOVER_NORM.md` (45.02 / 31.50). It is also measured
  *directly* by `chat_seq --canned`, which never re-charges the preamble.

| metric | build_033 (`33d720e5`) | build_034 (`4f908df2`) | delta |
|---|---|---|---|
| `seq_run` nch=1 device / 6 tok | 278.779 ms | **278.797 ms** | +0.018 ms (+0.006%) |
| — gate convention | 46.4632 ms/tok · 21.522 tok/s | **46.4662 ms/tok · 21.521 tok/s** | −0.001 tok/s |
| — steady-state | 45.0180 ms/tok · 22.213 tok/s | **45.0210 ms/tok · 22.212 tok/s** | −0.001 tok/s |
| `seq_run4` nch=4 device / 6 tok | 197.635 ms | **197.685 ms** | +0.050 ms (+0.025%) |
| — gate convention | 32.9392 ms/tok · **30.359 tok/s** | **32.9475 ms/tok · 30.351 tok/s** | −0.008 tok/s |
| — steady-state | 31.4940 ms/tok · 31.752 tok/s | **31.5023 ms/tok · 31.744 tok/s** | −0.008 tok/s |
| `chat4 --canned` per-step device (direct steady-state) | mean 31.4937 (31.476–31.512) | **mean 31.4998 (31.482–31.519)** | +0.0061 ms (+0.019%) |
| session preamble | 8.672 ms | **8.672 / 8.671 ms** | identical |
| `seq_run4` cycles | 49,408,845 | 49,421,189 | +0.025% |
| `seq_run` nch=1 cycles | 69,694,659 | 69,699,257 | +0.007% |

**The 30.4 tok/s headline reproduces: 30.351 tok/s (gate convention),
31.744 tok/s (steady-state).** Every delta is ≤ 0.025% and tracks the host
poll count (`axil_rd` 2,127,031 → 2,127,840 at nch=4), i.e. run-to-run noise,
not a silicon regression. Tokens are bit-identical on every rung.

`tok_meter4` (layer+matvec device basis, a different metric from the 30.4
end-to-end figure) reads **47.01 device tok/s at 21.27 ms/token, 70.70 GB/s
aggregate DDR read**, with `beats*64` an EXACT match against the manifest
(2,504,613,888 B).

> **Correction — 47.01 is NOT the milestone it superficially matches.**
> `TOKS.md:144-149` lists two levers in sequence: lever 1 (wide `vec_alu` +
> `vecnorm_unit`) projects **~47 tok/s / 21.2 ms** *with matvec unchanged at
> 10.16 ms*; lever 2 (remove the matvec per-row bubble) then projects
> **~61 tok/s / 16.4 ms**. **build_034 has both**, so the applicable
> projection is **~61, not ~47** — and the ~47 "match" is the product of two
> offsetting errors. The measured split settles it:
>
> | bucket | TOKS.md lever-2 projection | build_034 measured | gap |
> |---|---|---|---|
> | matvec | 5.43 ms/tok | **5.905** | +0.47 (met, ~9% over) |
> | **layer** | **11.0 ms/tok** | **15.368** | **+4.37 (40% over)** |
> | device total | 16.4 ms · ~61 tok/s | **21.27 ms · 47.01 tok/s** | **−22.9% tok/s** |
>
> The zero-bubble work landed — matvec is essentially at target. **The entire
> shortfall is layer-side**: 4.37 of the 4.84 ms/token gap (90%) is
> `t_layer`. The wide-ALU lever under-delivered against its own arithmetic.
> This is a *finding*, not a regression: nothing here is worse than
> build_033, which is what the gate tests. It is the standing #1 lever
> restated with a number.
>
> **Routing note for Q10 / gate D — the layer term moved between builds.**
> `docs/ARCHITECTURE.md:626` carries **14.13 ms/token** as the 0.8B layer
> bucket, and the quant study's 2B model geometry-scales *that* figure to its
> **17.4 ms** layer term (`QWEN2B_QUANT_STUDY.md:264`, already flagged there
> as unverified and as the widest uncertainty in the tok/s column). build_034
> measures the same quantity — the `L_LCYC` census, same model geometry,
> 0.417436 GB/token — at **15.368 ms/token**, i.e. **+1.24 ms above the
> figure the 2B projection is anchored to**. The 2B layer input should be
> re-anchored to build_034's measurement. **Direction of the correction:
> it worsens modeled tok/s slightly and does so for every variant equally —
> the layer term is quantization-independent, so the relative column and the
> variant ranking are unaffected.** No gate-D decision flips on this; it is a
> calibration fix to make before absolute 2B tok/s numbers are quoted.

---

## Gates

### Board-free (sim/host, run first)

| # | gate | result |
|---|---|---|
| B0 | `make seq_selftest` | **PASS 2570 / 0 failed** (incl. the R-b `emb_row_bytes` + EMBLOG2 cases) |
| B1 | `make serve_test` | **PASS 85 / 0 failed** — after fixing a stale assertion, see Follow-on 1 |

### Hardware — identity, before any DMA

| # | gate | result |
|---|---|---|
| H0 | reprogram | `PROGRAM_OK` on the po2 `.bit`; `rescan OK: 82:00.0 … Device 9038` |
| H0 | MAGIC | `0xfab1e001` ✓ |
| H0 | **VERSION** | **`0x4f908df2`** ✓ (= the shipped netlist; was `0x4b15b576` before — see Concerns) |
| H0 | **CALIB** | **`0xf`** ✓ — all four DDR4 channels calibrated, DMA cleared |
| H0 | LAYER / SEQ / TOPK IDENT | `0xfab1e5a0` / `0xfab1e5e0` / `0xfab1704b` ✓ |
| H0 | **EMBLOG2 (SEQ 0x60)** | **11 at reset** ✓ — the R-b CSR exists and is at the 0.8B geometry (2048 B rows). Never written to anything but 11 in this gate; `seq_run` programs it to the artifact's value, which for 0.8B *is* 11. |

### Hardware — the ladder, in the brief's order

| # | gate | result |
|---|---|---|
| H1 | `make seq_dry_run` (upload + readback, no SEQ CSRs) | **PASS** — 885 MiB written, 885 MiB read back and compared, 6.5 s; 187 weight images + 485 MiB embedding + seqdata + stream all `readback OK`; SEQ window never accessed |
| H2 | `make seq_run` (nch=1) | **PASS** — halted pc 60494/60495, `STATUS=0x00010004 err=False`, 278.797 ms device; tokens `[561,314,279,369,279,6511]` **IDENTICAL** to `.seq.json`; **7188 golden chip-state checks ALL MATCH** |
| H3 | `make seq_run4` (nch=4 row-split + interleaved head) | **PASS** — halted pc 68118/68119, `err=False`, 197.685 ms device; tokens **IDENTICAL**; **7188 golden chip-state checks ALL MATCH**; `xrf_ovf=False`, `fetch_starved_cyc=97` |
| H4 | `chat_seq --verify --ntok 8` (lockstep vs `ref/seq_model`) | **PASS — 26/26 steps `== seq_model`, 0 mismatch** (18 lite prefill + 8 full decode). Output `'The capital of France is **Paris**.'`, ids `[760,6511,314,9338,369,2972,57590,159034]`. OUT FIFO clean, sticky `of_ovf` clear |
| H5 | `make chat4_canned` (B1 argmax regression) | **PASS — MATCH**: got `[561,314,279,369,279,6511]` == `expect_tokens`, committed == got, per-step 31.482–31.519 ms device |
| H6 | sampled chat, `--nch 4 --temp 0.8 --seed 4242 --ntok 24`, **twice** | **PASS — byte-identical ids on both runs** (mechanically diffed). Text: *"the golden frost hangs upon the windows like ice draped on my cheeks like cold winds the ice.285"* |
| H7 | same, `--seed 4243` | **PASS — differs**: *"```i\ncold fingers reach across and soft with your own love.\nleaves rust with seasons and then slowly lose"* |
| H8 | seeds 4244, 4245 (to 4 distinct seeds) | **PASS** — both distinct, both coherent; 4244 reached EOS in 22 tok |
| H9 | `make tok_meter4` | **PASS** — 47.01 device tok/s, 70.70 GB/s aggregate, `beats*64` vs manifest **EXACT MATCH** (2,504,613,888 vs 2,504,613,888), 0 errors |
| H10 | per-channel matvec probe, `matvec_test.py` (added, see Watch items) | **PASS — 4 seeds × 2 runs × 4 channels = 32/32 bit-exact, 0 errors** |
| H11 | post-ladder residency restore (`chat_seq --nch 4 --canned`) | **PASS** — probe correctly reported **23 MISS** after H10 clobbered 6 weight images, re-uploaded them, re-probed **0 MISS**, B1 **MATCH** again. The board is left in the production 0.8B state |

**Cross-build reproduction of the sampled trajectories.** `RUNG4_GATE.md:26-31`
recorded build_033's seed-4242 text as *"the golden frost hangs upon the windows
like ice draped…"* and seed-4243 as *"cold fingers reach across…"* — **elided
prefixes, not full trajectories**. Build_034 **matches both recorded prefixes**,
which is as strong a cross-build claim as the 033 record supports: build_033's
full token ids were not archived for these two sessions, so this is a
prefix match, not a token-for-token comparison. Within build_034 the
determinism claim *is* token-for-token (H6, all 24 step records deep-compared).

**Note on the gate-table order.** The table lists the brief's prescribed order;
two rows ran out of that order because the extra seeds were added after the
ladder proper. Actual wall-clock order (log mtimes, 2026-08-16): H1 13:51 · H2
13:51 · H3 13:52 · per-channel PERF 13:53 · H4 14:00 · H5 14:00 · H6 14:00–14:01
· H7 14:01 · **H9 14:03** · **H8 14:05** · H10 14:05 · H11 14:06. Nothing
depends on the ordering — H8 and H9 share no state — but the record should say
what happened.

---

## Watch items — disposition

The waiver (§6) named three domains and asked this gate to exercise each.
**None of the three shows any anomaly.** Every rung above is bit-exact, so the
answer is not "no failure was noticed" but "no mismatch exists in 32 bit-exact
matvec comparisons, 2 × 7188 golden state checks, 26 lockstep steps, 3 canned
argmax runs and 5 sampled sessions."

### 1. Class A — DDR channel 2 (`mvchan_2/u_chan/u_engine`, 24 EP, −0.025…−0.007)

The waiver's stated signature is *"an asymmetry between ch2 and the other
three"*. Measured directly, two independent ways:

**(a) `matvec_test.py` — 4 seeds × 2 runs × 4 channels, each result compared
bit-exact against `ref/w4a8_ref.py`** (`hw_12_matvec_perchan.log`,
`matvec_test_20260816_140538.json`):

| channel | runs | beats | mean cycles | min–max cycles | mean GB/s (2 dp, from the log) | errors |
|---|---|---|---|---|---|---|
| ch0 | 8 | 118784 | **127625.8** | 127556–127723 | 17.8750 | **0** |
| ch1 | 8 | 118784 | 127672.2 | 127561–127719 | 17.8700 | **0** |
| **ch2** | 8 | 118784 | **127640.2** | 127568–127708 | 17.8762 | **0** |
| ch3 | 8 | 118784 | 127641.5 | 127558–127726 | 17.8750 | **0** |

**No measurable ch2 penalty: the four channels lie within 0.0364%** (46.5
cycles of 127,626), with identical beat counts and **32/32 bit-exact results,
0 errors**.

> **Ranking correction.** An earlier revision of this document called ch2 "the
> fastest of the four" off the GB/s column. That is a **display-rounding
> artifact** — `matvec_test` prints GB/s to two decimals, and the underlying
> raw cycle counts in `matvec_test_20260816_140538.json` rank
> **ch0 fastest and ch2 second** — the full mean-cycle ranking is
> **ch0 127,625.8 < ch2 127,640.2 < ch3 127,641.5 < ch1 127,672.2**, i.e. ch2
> trails ch0 by **0.0114%** and leads ch3 by 1.3 cycles.
> The defensible claim is the one above — *no measurable penalty*, a
> four-channel spread far below any plausible setup-failure signature — not a
> ch2 win.

Secondary line, and this one *is* a ch2 win: the per-channel `PERF_CYC` /
`PERF_BEATS` read straight off the engines after `seq_run4`
(`hw_04b_perchan_perf_after_seq_run4.log`) — an independent counter, on the
real 0.8B workload rather than the synthetic probe. The counters latch the last
MVGO on each engine:

| channel | SHAPE | PERF_BEATS | PERF_CYC | beats/cyc |
|---|---|---|---|---|
| ch0 | `0x00800148` | 18432 | 19809 | 93.05% |
| ch1 | `0x00200148` | 4608 | 4991 | 92.33% |
| **ch2** | `0x00800148` | 18432 | **19795** | **93.11%** |
| ch3 | `0x00800148` | 18432 | 19933 | 92.47% |

On the three engines whose last MVGO shares shape and beat count, **ch2 is the
fastest** (19,795 vs 19,809 / 19,933 cycles) — a single-sample observation, so
it carries less weight than (a)'s 8-run means, but it points the same way. ch1's
smaller shape is the expected consequence of the interleaved LM head (chunk *j*
→ engine *j*%4), not an anomaly.

**Disposition: no measurable ch2 penalty on either probe, and 32/32 bit-exact
results on the channel the waiver flagged. Class A did not manifest.**

### 2. Class B — `dn_step` in `layer_0` (`u_dn` 18 EP + `u_topk` 2 + 3 loose, −0.011…−0.001)

`dn_step` outputs are inside the bit-exact envelope, so a mis-selected output
appears as a mismatch. Coverage: **2 × 7188 golden chip-state checks** (nch=1
and nch=4 post-halt state vs the frozen `.chip` goldens), **26/26 lockstep steps
against `ref/seq_model`**, and **3 canned argmax runs**. `tok_meter4`
independently exercises the DNST opcode 288 commands/token for 3.408 ms/token
(22.2% of layer busy time) with 0 errors, and `u_topk` is exercised on every
one of the 5 sampled sessions (chip top-k k=32 feeds every draw; a corrupted
top-k list would break the cross-build trajectory reproduction, which held).
**Disposition: 0 mismatches. Class B did not manifest.**

### 3. Class C — `seq_0` MOV addressing (`mv_wbase_reg[33]/CE`, `u_mov/yf_cnt_reg[0,1]/CE`, 3 EP)

A `mv_wbase` mis-capture corrupts MOV base addressing and a `yf_cnt` slip
corrupts the Y-fetch count; both would corrupt scratch loads. Coverage: **1592
MVGO WBASEs (nch=1) / 3464 (nch=4) verified row-aligned inside their images
before the run**, then the run itself with **7188 golden state checks each** —
the post-halt chip state includes the scratch contents the movers wrote. The
nch=4 stream additionally issues 2992 MOVX / 3464 MOVY / 868 FENCE records.
**Disposition: 0 mismatches, `err_code=0x00`, `xrf_ovf=False` on both runs.
Class C did not manifest.**

### Summary

| watch item | domain | probe | result |
|---|---|---|---|
| A | `mvchan_2` ch2, 24 EP | 32 bit-exact per-channel matvecs + per-channel PERF | **clean — no measurable ch2 penalty (4 channels within 0.0364%), 0 errors** |
| B | `layer_0/u_dn` (+`u_topk`), 23 EP | 14,376 golden checks + 26 lockstep steps + 3 canned | **clean — 0 mismatches** |
| C | `seq_0` MOV addressing, 3 EP | 5056 MVGO base checks + 14,376 golden checks | **clean — 0 mismatches** |

**Every *hardware* rung (H0–H11) passed on its first execution; none was
retried.** The one gate that needed a second run is the board-free B1
(`serve_test`), which failed on a stale assertion in `sw/serve.py`, was fixed at
source, and passed on re-run — disclosed in its row above and in Follow-on 1.

---

## Artifacts

All under `evidence/qwen2b/rb/`:

| file | contents |
|---|---|
| `hw_00_boardfree_selftests.log` | seq_selftest 2570/0 + serve_test 85/0, **as run at gate time** |
| `hw_14_postedit_selftests.log` | the same two, **re-run after all `sw/` source edits** (version constants, `serve.py` assertion, comment blocks) — 2570/0 and 85/0 again. `hw_00` predates those edits; this is the log that covers the committed tree |
| `hw_01_reprogram_034.log` | remove → PROGRAM_OK → rescan, then the CSR identity + EMBLOG2 reads |
| `hw_02_seq_dry_run.log`, `seq_dry_run_build034.json` | 885 MiB upload + readback |
| `hw_03_seq_run_nch1.log`, `seq_run_build034.json` | nch=1 run, 278.797 ms, 7188 golden checks |
| `hw_04_seq_run_nch4.log`, `seq_run4_build034.json` | nch=4 run, 197.685 ms, 7188 golden checks |
| `hw_04b_perchan_perf_after_seq_run4.log` | per-channel PERF_CYC/BEATS (watch item 1b) |
| `hw_05_chat_seq_verify_ntok8.log`, `chat_seq_verify_build034.json` | lockstep 26/26, 0 mismatch |
| `hw_06_chat4_canned.log`, `chat4_canned_build034.json` | B1 MATCH, per-step 31.48–31.52 ms |
| `hw_07/08_sampled_seed4242_a/b.log` + JSONs | determinism, byte-identical |
| `hw_09_sampled_seed4243.log` + JSON | seed sensitivity |
| `hw_11_sampled_seeds_4244_4245.log` + JSONs | seeds 3 and 4 |
| `hw_10_tok_meter4.log`, `tokmeter_4chan_build034.json` | 47.01 device tok/s, beats EXACT |
| `hw_12_matvec_perchan.log`, `matvec_test_20260816_140538.json` | 32/32 per-channel bit-exact (watch item 1a) |
| `hw_13_chat4_canned_post_restore.log`, `chat4_canned_build034_post.json` | residency restored, B1 MATCH again |

---

## Concerns

**The bitstream this gate replaced was NOT build_033.** The task premise was
that build_033 (`33d720e5`) was resident; the VERSION CSR read
**`0x4b15b576`** at gate start.

> **Evidence grade, stated plainly.** That readback was **not tee'd to a log at
> the time** — it ran as a separate command and its output went only to the
> session transcript. It is transcribed verbatim into
> `hw_01_reprogram_034.log` under an explicit after-the-fact provenance header,
> and it is **not independently reproducible now**. The corroborating mtime
> correlation (this repo's other worktree's `sw/` at 2026-08-15 14:25 against
> `/dev/xdma0_*` node mtimes of 14:23) is **also gone** — this gate's own
> rescan at 13:51 rewrote those node mtimes. **Treat the specific value
> `0x4b15b576` and the worktree attribution as UNCONFIRMED.**

**What needs no readback, and is not in doubt:** the resident bitstream was not
build_033's. `4b15b57` is a real commit in this repository (*"evidence(qwen2b):
2B g64 top-1 65/127; mixed-g knobs; weight bytes"*, 2026-08-15 05:54) and
**none of the 34 build directories under `synth/out_build_*/` stamps
`4b15b576`** — all were checked; the five most recent stamp `9e1e0bae`,
`4d71adcc`, `0c991953`, `33d720e5`, `4f908df2`. The most likely source is the
second git worktree, `/home/cah/r2d2/code/fpga/grok46_llm/fable5` (branch
`grok46-qwen2b`), which was demonstrably active on this machine throughout.
**The board-sharing follow-on below rests on the premise mismatch, which is
undisputed, not on the unconfirmed attribution.**

**Preconditions were nevertheless clean and the board was taken without
contention:** `pgrep -af 'chat_seq|seq_run|serve'` was empty on snoke, nothing
held `/dev/xdma0_*`, that worktree had been off the board for ~23 h, and it was
mid-Vivado reroll (`out_qwen2b_t1024_rr_AltSpreadLogic_low`, ~1h50m elapsed) for
the whole duration of this ladder. Interference would also have been loud
rather than silent: every sequencer tool hard-gates on the VERSION CSR, so a
concurrent reprogram mid-ladder aborts the run instead of corrupting it.

**Standing risk:** one board, two live workstreams on the same NFS filesystem,
and no cross-worktree lock. `sw/.seq.lock` is per-checkout (`flock` on
`sw/.seq.lock` in *this* tree) and therefore does **not** exclude the other
worktree's tools. A shared lock path — or simply a rule that only one worktree
owns the board — is worth deciding before the next hardware campaign.

**Recovery was not exercised.** The BLOCKED contingency (reprogram build_033's
`.bit` to return the board to a known-good state) was never invoked, because no
gate failed. The board is left resident on build_034 by design, which is the
R-b exit condition.

---

## Follow-ons

1. **`sw/serve.py` selftest assertion was stale and had been failing silently
   in `make serve_test`.** The check `"rung 4" in errs[0]["error"]` was written
   in `c92a1d2`; the message it inspects was reworded to *"rung-4"* by the
   documentation pass `6472f92`, so the assertion had been red ever since — a
   pre-existing break, unrelated to build_034. Fixed by asserting the emitted
   error **equals the backend's own `sampling["why"]`**, which cannot drift
   with wording. `serve_test` now reads 85/0.
2. **Version constants bumped to the new netlist** — `sw/seq_run.py`
   `EXPECTED_SEQ_VERSION`, `sw/infer.py` `EXPECT_VERSION` (and the
   `sw/chat_seq.py` docstring) moved `0x33D720E5` → **`0x4F908DF2`**. These are
   hard gates: every sequencer tool refuses the board unless the VERSION CSR
   matches. `docs/USAGE.md` named `0x33D720E5` as "today's" value in three
   places (the identity check at :75, the reprogram example in §2, and the
   troubleshooting row at :417); all three were updated to build_034 in this
   commit, since an operator following the old text would be told every tool
   should refuse the now-resident board.
3. **`tok_meter4` has no build_033 baseline on record, and the projection it
   should be read against is ~61 tok/s, not ~47.** `evidence/stage5/` holds
   only `tokmeter_4chan_build026.json` (12.23 device tok/s, a pre-wide-ALU
   architecture). Against `TOKS.md`'s applicable lever-2 projection
   (~61 tok/s / 16.4 ms — build_034 has *both* the wide ALU and the zero-bubble
   matvec) the measured 47.01 / 21.27 is **22.9% short, entirely on the layer
   side** (see the Headline correction). Two follow-ons fall out:
   **(a)** `tokmeter_4chan_build034.json` is now the baseline for future
   builds; **(b)** the layer bucket measures **15.368 ms/token** here against
   the **14.13** on record at `ARCHITECTURE.md:563` — that on-record figure is
   what the quant study geometry-scales into its 2B **17.4 ms** layer term
   (`QWEN2B_QUANT_STUDY.md:264`), so **Q10 / gate D should re-anchor the 2B
   layer input to build_034's measurement.** The correction worsens modeled
   absolute tok/s slightly and equally for every variant (the layer term is
   quantization-independent); **no variant ranking changes.**
4. **The residency probe's nch=1 witness set cannot distinguish a 4-chan board
   from a 1-chan one in every case** — H4 probed 0 MISS immediately after the
   nch=4 upload. It was harmless here (the nch=4 row-split writes chan 0's
   quarter at the same addresses the nch=1 layout uses, leaving the rest of the
   nch=1 image intact from H2), and the lockstep gate would have caught any
   consequence. H11 shows the probe *does* catch real damage (23 MISS after
   `matvec_test` overwrote 6 images). Worth a targeted witness in the
   post-quarter region if the layout flip is ever automated.
5. **The timing waiver stands unchallenged by hardware but is not retired by
   it.** This gate is one temperature, one voltage, one board. The residual
   risk in `TIMING.md` §6 (real setup violations in `mvchan_2`, `u_dn` and
   `seq_0`, worst-case PVT) is unchanged; what this gate establishes is that
   at the operating point the project actually runs, all three classes are
   silent. The highest-leverage untried lever remains a pblock/soft floorplan
   — the design still has **no pblocks at all**.

---

## Gate D input

R-b's exit condition — *"the board's resident bitstream becomes build_034 only
if the FULL 0.8B ladder reproduces"* — is **met**. The board is resident on
`4f908df2` with the 0.8B weights uploaded and verified, EMBLOG2 at its reset
value of 11, and the production `chat_seq --nch 4` path measured at
**30.351 tok/s (gate convention) / 31.744 tok/s (steady-state)**, tokens
bit-exact against build_033 everywhere.
