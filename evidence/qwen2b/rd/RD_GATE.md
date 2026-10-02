# R-d HW GATE — the 2B runs on the FPGA, on the first bitstream that needed no waiver (2026-08-25)

Board: **BCU-1525 on snoke**, PCIe 82:00.0, Gen3 x8. Bitstream
`synth/out_build_035_fp2a_exc_po/bd_wrapper.bit` (54,072,409 B, sha256
`58b06450f8f9b258…`, mtime 2026-08-24 23:13), netlist **`0x54443b9f`** — read
back from the VERSION CSR on silicon and **tee'd** (`hw_03_identity_035.log`).
Programmed by the safe JTAG flow, **volatile only, flash never touched**.

Host tree: **there is no single one** — each log stamps its own, and **nine**
distinct trees appear across the **57** logs (`b3dd123`, `85d05d6`, `c05b4ee`,
`dcdf5cd`, `bc9ae59`, `1f53a39`, `01b9f0f`, `ce9883f`, `2304aa6`, all
`+dirty`; counted with `ls hw_*.log | wc -l` and
`grep -h '^=== tree' hw_*.log | sort -u | wc -l`, which is how this line
should be refreshed rather than incremented). Broadly: the 0.8B
ladder ran on `b3dd123`/`85d05d6`/`c05b4ee` (T5's review commits landing
concurrently, docs only), the 2B `seq_run` rungs on `dcdf5cd`/`bc9ae59`, the
chat rungs on `1f53a39` after the `chat_seq` fixes, and review round 1 on
`01b9f0f`, with the review-round gates on `ce9883f` and `2304aa6`. `+dirty`
throughout means the
edits under test were uncommitted at run time and were committed immediately
after — read each log's own line rather than this summary.

**build_035 ships with no timing waiver — the first in this project's
history** (`evidence/qwen2b/rc/TIMING_035.md` §13.4).

**Outcome: R-d HW gate PASS.**

1. the **full 0.8B ladder reproduces build_034** — the sequencer rungs to
   ≤0.0068 %, the streaming and synthetic probes to ≤0.04 % (§1, which
   states each rung against its own basis rather than one bound);
2. the **Qwen3.5-2B W8 (V5) model runs on the FPGA** — 68,503 records,
   16,404 post-halt golden state checks ALL MATCH, tokens bit-exact,
   26/26 chat steps in lockstep with `ref/seq_model`, coherent greedy and
   sampled chat;
3. measured **16.139 tok/s** (gate convention) / **16.525 tok/s**
   (steady-state) — inside the re-anchored ~15.5–16.5 band the plan set,
   at its top edge.

The board is left resident on build_035 with the 2B W8 weights: all 866 weight
pieces (1,847.2 MiB) compared byte-for-byte against the artifact files, plus
8 sampled 4 KiB blocks of the 970 MiB embedding table (`hw_44`, T12).

Three host-side defects were found on the way and all three are fixed and
gated (§4). None was RTL, none was the bitstream, none moved an artifact
byte — but one of them was a session **answering with the wrong token and no
error anywhere**, and it had been latent in the shipped tool since rung 4.

---

## 1. Headline

Both amortization conventions, because the project has both on the record and
they differ by the session-once preamble.

> **The preamble constant.** The steady-state convention subtracts **8.671 ms**,
> which `evidence/qwen2b/ra/MOVER_NORM.md:170` took from
> `evidence/rung3/census_step_build032.json` — a **build_032** measurement — and
> `rd_census.py:82` hard-codes it. R-d does not assume it: all 23 sessions in
> this gate measured their own preamble and got
> **8.670–8.671 ms at 0.8B** (n=9) and **8.670–8.672 ms at 2B** (n=14) on
> build_035 — the extremes are `chat2b_verify.json` / `chat_sampled_seed4242_a`
> at 8.670 and `chat2b_canned_reupload.json` (a **2B** session) at 8.672, with
> every other session at 8.671. The constant is confirmed to ±0.001 ms,
> not inherited on trust; ±0.001 ms moves a per-token figure by 0.0002 ms.

| metric | 0.8B on build_034 (R-b) | 0.8B on build_035 | **2B W8 (V5) on build_035** |
|---|---|---|---|
| `seq_run` nch=1 device / 6 tok | 278.797 ms | **278.778 ms** `hw_05` | — |
| `seq_run4` nch=4 device / 6 tok | 197.685 ms | **197.685 ms** `hw_06` | **371.758 ms** `hw_24` |
| — gate convention | 32.9475 ms · 30.3513 tok/s | **32.9475 ms · 30.3513 tok/s** | **61.9597 ms · 16.1395 tok/s** |
| — steady-state | 31.5023 ms · 31.7437 tok/s | **31.5023 ms · 31.7437 tok/s** | **60.5145 ms · 16.5250 tok/s** |
| `chat --canned` per-step device, n=6 | mean 31.4998 | **mean 31.5008** (31.481–31.518) `hw_08` | **mean 60.5155** (60.500–60.530) `hw_44` |
| `--verify` session, decode step, n=8 | 45.2 ms | **mean 45.1661** (45.139–45.193) `hw_07` | **mean 60.6624** (60.640–60.689) `hw_39` |
| `--verify` session, prefill-lite step, n=18 | 33.9 ms | **mean 33.8772** `hw_07` | **mean 49.8707** `hw_39` |
| lite / full, as the session reports it | 75.0 % | **75.0 %** `hw_07` | **82.2 %** `hw_39` |
| session preamble | 8.672 ms | **8.670–8.671 ms** (n=9) | **8.670–8.672 ms** (n=14) |
| weight bytes / token | 417,435,648 | **417,435,648** | **1,936,920,576** (1,847.2 MiB) |

Each row compares like with like: the canned rows are canned sessions, the
decode/prefill rows are `--verify` sessions. The 2B's **greedy** session
(`hw_37`, `chat2b_greedy.json`) ran the same body **0.0650 ms/step** slower —
mean **60.7273** over n=24, min 60.636 max 60.811, against the `--verify`
session's 60.6624 over n=8. The four sampled 2B sessions (`hw_38`) sit with
it, not with the verify run: 60.7267 / 60.7270 / 60.7265 over n=24 and
60.7043 over n=18 (seed 4244 stopped at EOS). This is a longer session
drifting upward within its own run, not a different measurement.

**How closely the 0.8B reproduces build_034, per rung and against its own
basis** — there is no single bound, and an earlier revision of this document
wrongly claimed one:

| rung | 034 | 035 | delta | source |
|---|---|---|---|---|
| `seq_run4` device | 197.685 ms | 197.685 ms | **0.0000 %** | `seq_run4_build035.json` |
| `seq_run4` cycles | 49,421,189 | 49,421,373 | **+0.00037 %** | same |
| `seq_run` nch=1 device | 278.797 ms | 278.778 ms | **−0.0068 %** | `seq_run_build035.json` |
| `seq_run` nch=1 cycles | 69,699,257 | 69,694,517 | **−0.0068 %** | same |
| `chat4 --canned` per-step | 31.4998 ms | 31.5008 ms | **+0.0032 %** | `chat4_canned_build035.json` |
| `tok_meter4` layer term | 0.092207064 s | 0.092207064 s | **0.0000 %** (LCYC is an integer cycle count) | `tokmeter_4chan_build035.json` |
| `tok_meter4` matvec term | 0.03542800213 s | 0.03542526656 s | **−0.0077 %** | same |
| `tok_meter4` aggregate DDR | 70.69588284 GB/s | 70.70134204 GB/s | **+0.0077 %** | same |
| `matvec_test` mean cycles, worst channel | ch3 127,641.50 | ch3 127,590.75 | **−0.0398 %** | `matvec_test_20260824_234646.json` |
| `matvec_test` four-channel spread | 0.0364 % | **0.0645 %** | widened **1.77×** | same, §3 and follow-on 9 |

**The sequencer rungs — the ones the gate turns on — reproduce to ≤0.0068 %
with tokens and golden state bit-identical.** The probes that measure DDR
streaming rather than the sequencer move more: `tok_meter4`'s matvec term and
the aggregate rate by 0.0077 % (they are the same quantity, one divided by the
other), and the synthetic `matvec_test` per-channel means by up to 0.0398 %,
with the four-channel spread widening from 0.0364 % to 0.0645 % — recorded in
§3 and carried as follow-on 9 rather than waved past.

**Run-to-run spread, for scale, stated in its own configuration.** R-d executed
the **nch=4** `seq_run4` six times on this bitstream — 197.685 / 197.682 /
197.673 / 197.687 / 197.681 / 197.679 ms (`seq_run4_build035.json`,
`…_mixmaker.json`, `…_mixmaker2.json`, `…_predecessor.json`,
`…_zeroed_after_2b.json`, `census_08b.json`) — a spread of **0.0071 %**, which
is larger than that configuration's entire 034→035 delta. **The nch=1 stream
ran only once in R-d** (`hw_05`), so it has no repeat spread of its own and the
−0.0068 % above is *not* being compared against a same-configuration noise
figure.

**The 2B is 1.881× the 0.8B's device time per token for 4.640× the weight
traffic** (1,936,920,576 / 417,435,648). In throughput terms, from **this
table's** pair — `hw_24` 371.758 ms against `hw_06` 197.685 ms — the 2B
**retains 53.18 % of the 0.8B's rate on the gate convention** (16.1395 /
30.3513), giving up 46.82 %; on the steady-state convention it retains
**52.06 %** (16.5250 / 31.7437), giving up 47.94 %. §3's census pair
(`hw_41`/`hw_42`, different executions minutes later) gives **53.17 %** and
**52.05 %** — the two pairs agree to **0.003 pp**, which is the point.

### Against the model the plan set

`docs/superpowers/plans/2026-08-16-qwen2b-v5-w8.md` (Global Constraints, last
bullet) re-anchored the 2B projection to build_034's measured layer term and
set the expectation at **~15.5–16.5 tok/s modeled**; `QWEN2B_QUANT_STUDY.md`'s
pre-anchor V5 estimate was 16.1–17.0.

| | modeled | measured |
|---|---|---|
| 2B V5 tok/s (gate convention) | 15.5 – 16.5 (re-anchored) | **16.139** (`hw_41`; `hw_24` gives 16.1395) |
| 2B V5 tok/s (steady-state) | — | **16.525** (both executions) |
| 2B layer term, ms/token | 17.4 pre-anchor · 18.925 re-anchored (17.4 × 15.368/14.13) | **17.960** (§3) |

**Reported as found: it says the study was right.** The measured 16.139 lands
inside the re-anchored band and inside the study's original one. The layer term
lands **between** the two projections — **+3.2 % above** the study's unverified
17.4 and **−5.1 % below** the naive re-anchoring of it.

---

## 2. Gates

### Board-free (before any hardware access, and again after every `sw/` edit)

One column per execution, each read off that log rather than carried forward:

| # | gate | `hw_01` gate start | `hw_23` after `--zero-scratch` | `hw_45` after the `chat_seq` fixes | `hw_46`/`hw_50`/`hw_51` review rounds 1–2 |
|---|---|---|---|---|---|
| B0 | `make seq_selftest` | **2735 / 0** | **2750 / 0** | **2750 / 0** | **2750 / 0** |
| B1 | `make serve_test` | **85 / 0** | **85 / 0** | **85 / 0** | **85 / 0** |
| B2 | `chat_seq --selftest` | **337 / 0** | **337 / 0** | **340 / 0** | **344 / 0** |

The counts grow only where that step's fix added regressions: `hw_23` is
`+15` seq_run checks for `--zero-scratch` and `chat_seq` **unchanged at 337**
(its fixes had not landed yet — an earlier revision of this table wrongly
showed 340 there); `hw_45` is `+3` chat_seq checks for the per-piece witness
set and the derived geometry; `hw_46` is `+4` more for the escalation rule
(§4.2 (b)) and the `.e4` blob geometry; `hw_50` re-runs that same set on the
committed tree, and `hw_51` again after round 2's one code touch (a comment
line-number correction in `seq_run.py`).

### Hardware — identity, before any DMA

| # | gate | result |
|---|---|---|
| H0 | pre-state, **tee'd** (`hw_00`) | snoke last booted **2026-08-19 18:58**, i.e. after the R-b gate. At gate start `lspci` showed **no 82:00.0 and no Xilinx device at all**, `xdma` was not loaded, and `/sys/bus/pci/devices/0000:82:00.0` and `/dev/xdma0_*` did not exist. No other board users; no Vivado jobs. **What is proven is non-enumeration**, and that a boot intervened; the FPGA's configuration state itself was never probed (JTAG was not queried before programming). Non-enumeration is consistent with the volatile bitstream having been lost at the power cycle, which is what `pcie_helper.sh`'s own header predicts, but this gate does not measure it |
| H1 | reprogram | `PROGRAM_OK` in 80 s; `rescan OK: 82:00.0 … Device 9038`; `pcie_helper.sh load` (the script's documented post-reboot step) inserted `xdma.ko` (`hw_02`) |
| H2 | MAGIC | `0xfab1e001` ✓ |
| H2 | **VERSION** | **`0x54443b9f`** ✓ = the shipped netlist, and the value `seq_run.py`/`infer.py` now gate on |
| H2 | **CALIB** | **`0xf`** ✓ — all four DDR4 channels calibrated, DMA cleared |
| H2 | LAYER / SEQ / TOPK IDENT | `0xfab1e5a0` / `0xfab1e5e0` / `0xfab1704b` ✓ |
| H2 | matvec IDENT ×4 | `0xfab1c4a0…a3` ✓ |
| H2 | EMBLOG2 (SEQ 0x60) | **11 at reset** ✓ (2048 B rows, the 0.8B geometry) |

### Hardware — the 0.8B back-compat ladder (EMBLOG2 stays 11)

| # | gate | result | log |
|---|---|---|---|
| L1 | `seq_dry_run` | **PASS** — 885 MiB written, 885 MiB read back and byte-compared; SEQ window never touched | `hw_04` |
| L2 | `seq_run` nch=1 | **PASS** — halted 60494/60495, `err=False`, 278.778 ms, 69,694,517 cyc; tokens `[561,314,279,369,279,6511]` IDENTICAL; **7188 golden checks ALL MATCH** | `hw_05` |
| L3 | `seq_run4` nch=4 | **PASS** — halted 68118/68119, 197.685 ms, 49,421,373 cyc; tokens IDENTICAL; **7188 golden checks ALL MATCH**; `xrf_ovf=False` | `hw_06` |
| L4 | `chat_seq --verify --ntok 8` | **PASS — 26/26 steps `== seq_model`, 0 mismatch**; `'The capital of France is **Paris**.'`, ids `[760,6511,314,9338,369,2972,57590,159034]` — identical to build_034's | `hw_07` |
| L5 | `chat4 --canned` | **PASS — MATCH**, per-step 31.481–31.518 ms | `hw_08` |
| L6 | sampled 4242 ×2 | **PASS — byte-identical ids**, mechanically diffed (`hw_14`) | `hw_09/10` |
| L7 | sampled 4243 / 4244 / 4245 | **PASS** — all differ from 4242 and from each other; 4244 reached EOS at 22 tok, as on 034 | `hw_11/12/13` |
| L8 | `tok_meter4` | **PASS** — **47.01 device tok/s**, 70.70 GB/s aggregate, `beats*64` vs manifest **EXACT** (2,504,613,888); t_matvec 5.905 / t_layer 15.368 ms per token — the R-b split, reproduced | `hw_15` |
| L9 | `matvec_test` 4 seeds × 2 runs × 4 chans | **PASS — 32/32 bit-exact, 0 errors** | `hw_16` |
| L10 | residency restore | **PASS** — probe reported **753 MISS** after the two clobbering probes, re-uploaded 883 MiB in 4.7 s, re-probed **0 MISS**, canned **MATCH** again | `hw_17` |

**Cross-build reproduction of the sampled trajectories, at the strength the
record supports.** All four seeds reproduce **build_034's** texts *verbatim* —
`evidence/qwen2b/rb/` archived the full ids for each. Against **build_033** the
claim stays where `RB_GATE.md:137-144` deliberately put it: a **prefix match
only**, because build_033's full token ids for those sessions were never
archived. This gate does not re-upgrade that.

**Every ladder rung L1–L10 passed on its first execution**, and L2/L3 ran
*before* any 2B run had ever touched the board, so §4.1 does not qualify them.
Later in the gate a 0.8B `seq_run4` *did* fail its golden check (`hw_21a`) —
deliberately, on a board the 2B had just owned; that is §4.1's mirror, not a
ladder result.

### Hardware — the 2B W8 (V5) model, first time on silicon

| # | gate | result | log |
|---|---|---|---|
| T1 | artifact identity | **PASS** — all seven sha256 of the uncommitted 2B set reproduce `RC_GATE.md` §2 exactly; 187 images = 1,936,920,576 B | `hw_18` |
| T1b | **golden identity** | the `.chip` goldens these checks are made against, hashed: 2B `15c39f54f75adcc3…` (16,384 MEM lines, NREC 68503, PC 68502, **EMBLOG2 12**), 0.8B nch=4 `e5436b72e93c3ada…` (7,168 MEM lines) | `hw_47` |
| T2 | upload + readback | **PASS** — **2,819 MiB** written and byte-compared in 21.7 s; per-channel tops `0x2d0c4000 / 0x2cdac000 / 0x2cca4000 / 0x2cca4000` — T3's predicted fit, met on the board; 3,464 MVGO WBASEs row-aligned inside their images | `hw_19` |
| T3 | **EMBLOG2 → 12** | **PASS** — written **and read back**: `EMBLOG2 12 (4096 B embedding rows)`. This is the CSR R-c's wall 8 said silicon needed and the TB never programmed | `hw_24` |
| T4 | **`seq_run4` on the 2B stream** | **PASS** — 68,503 records, halted at the HALT pc, `err=False`, **371.758 ms**, 92,939,555 cycles, `xrf_ovf=False`, `fetch_starved_cyc=95`; tokens `[279,314,279,369,11751,13]` **IDENTICAL** to the artifact; **16,404 post-halt golden state checks ALL MATCH** | `hw_24` |
| T5 | scratch clear | **PASS** — 32,768 words zeroed through SPTR/SWIN in 0.1 s and read back **0 non-zero** (§4.1) | `hw_24` |
| T6 | `chat --canned` on the 2B | **PASS — MATCH**, all six argmaxes `[279,314,279,369,11751,13]` | `hw_31/36/44` |
| T7 | **`chat_seq --verify` lockstep** | **PASS — 26/26 steps `== seq_model`, 0 mismatch** (18 lite prefill + 8 full decode), 530 s of host model time | `hw_39` |
| T8 | greedy chat | **PASS** — *"The capital of France is **Paris**.\n\nParis is not only the capital but also the country's largest city and a"* — visibly better prose than the 0.8B's, which stops at the first sentence | `hw_37` |
| T9 | sampled 4242 ×2 | **PASS — byte-identical ids** | `hw_38` |
| T10 | sampled 4243 / 4244 | **PASS** — both differ; 4244 reached EOS at 18 tok | `hw_38` |
| T11 | census | **PASS** — §3 | `hw_41/42` |
| T12 | final residency audit | **PASS** — **866 of 866 weight pieces byte-identical** (0 damaged of 1,847.2 MiB) and **0 of 8 sampled 4 KiB emb blocks** differ. The weight side is a full compare; the embedding side is a sample | `hw_44` |
| T13 | 0.8B production chat after the `chat_seq` edits | **PASS — MATCH** | `hw_43` |

**The W8 engine mode is live on silicon**, read off the SHAPE register of each
engine after the 2B run (`hw_41:26-29`) — **bit 29 set on all four**:

| | ch0 | ch1 | ch2 | ch3 |
|---|---|---|---|---|
| 2B W8 | `0x20800290` | **`0x20200290`** | `0x20800290` | `0x20800290` |
| 0.8B W4 control (`hw_42:26-29`) | `0x00800148` | `0x00200148` | `0x00800148` | `0x00800148` |

ch1's word differs in the `nrows` field, not bit 29: each register latches that
engine's **last** MVGO, and the interleaved LM head gives ch1 a smaller final
chunk (16,896 beats against 67,584) — the same asymmetry the 0.8B control
shows, and the reason `nrows` reads `0x200` there instead of `0x800`.

**T13, stated precisely.** The board-free gates (B0–B2) ran five times —
`hw_23` after the `--zero-scratch` edit, `hw_45` after the `chat_seq` fixes,
`hw_46` after review round 1, `hw_50` on the committed tree and `hw_51` after
round 2 — i.e. after every `sw/` edit event. The 0.8B *hardware* chat path was re-gated **once**,
after all `chat_seq` edits (`hw_43`): one run, not one per edit.

---

## 3. The census — measured, on the production path

`sw/tok_meter.py` cannot plan a 2B pack (its `plan_weights` is the
nch-independent one, so 1.94 GB collides with `EMB_BASE`; follow-on 3), so the
per-phase census was taken on the sequencer itself, which is the better
measurement anyway. `L_LCYC` is layer_chan's write-clearable 250 MHz
busy-cycle accumulator — the *same* counter `tok_meter` reports as `t_layer` —
so the two are directly comparable (`rd_census.py`).

**These are separate executions from §1's**, run minutes later with
`--zero-scratch`: 2B 371.768 ms here against §1's 371.758 (`hw_24`), 0.8B
197.679 against 197.685 (`hw_06`) — differences of 0.010 ms and 0.006 ms,
inside the six-run 0.8B spread of 0.014 ms and the four-run 2B spread of
0.010 ms quantified in §1 and §6.

| quantity | 0.8B nch=4 `hw_42` | **2B W8 nch=4 `hw_41`** | ratio |
|---|---|---|---|
| device, 6 tokens | 197.679 ms | **371.768 ms** | 1.881× |
| device / token | 32.9465 ms | **61.9613 ms** | 1.881× |
| tok/s, gate convention | 30.352 | **16.139** | 0.532× |
| tok/s, steady-state | 31.745 | **16.525** | 0.521× |
| **layer busy (LCYC)** | 22,692,603 cyc = **15.128 ms/token** | 26,940,149 cyc = **17.960 ms/token** | **1.187×** |
| layer busy, share of device | 45.9 % | **29.0 %** | — |
| weight bytes / token | 398.1 MiB | **1,847.2 MiB** | 4.64× |
| whole-run aggregate DDR read | 12.67 GB/s | **31.26 GB/s** | 2.47× |
| engine beats/cyc (last MVGO, 4 ch) | 92.33–93.11 % (**0.78 pp**) | **92.64–93.04 %** (**0.40 pp**) | — |

**Reading.** The 2B's weight traffic is 4.64× the 0.8B's but its device time
is only 1.881×, because the 2B is far closer to being DDR-bound: layer work
falls from 45.9 % of device time to 29.0 %, and the run-average DDR read rate
rises from 12.67 to 31.26 GB/s (against the 70.70 GB/s `tok_meter` measures
for pure matvec streaming, so there is still headroom that per-token overhead
is eating).

**The layer term, re-anchored on silicon.** The 0.8B LCYC census reads
**15.128 ms/token** against `tok_meter`'s **15.368** on the same board and
bitstream — a −1.6 % difference explained by `tok_meter`'s serialized replay
and its host-driven scratch traffic, which the sequencer overlaps. The 2B's
**17.960 ms/token** is therefore an honest like-for-like: **the 2B layer term
is 18.7 % above the 0.8B's** (17.960 / 15.128 = 1.1872), where the study's
geometry scaling implied **+23.1 %**.

That +23.1 % is the study's own ratio, and it is the same number computed
either way — which is the point of quoting it as a ratio rather than as two
absolute terms:

* un-anchored, as the study wrote it: **17.4 / 14.13 = 1.2314**
  (`QWEN2B_QUANT_STUDY.md:264` over `ARCHITECTURE.md:563`);
* re-anchored to build_034's measurement, as the plan required:
  **18.925 / 15.368 = 1.2314**, where 18.925 = 17.4 × 15.368 / 14.13.

An earlier revision of this document quoted "~34 %", which divided the
*re-anchored* numerator by the *un-anchored* denominator (18.925 / 14.13) —
a mixed basis, and wrong. The measured shortfall against the study is
1.1872 / 1.2314 = **−3.6 % on the ratio**, i.e. the 2B's layer work scales a
little better with geometry than the study assumed.

**Channel symmetry.** Four engines within 0.40 pp (2B) and 0.78 pp (0.8B) on
beats/cyc. The 0.8B synthetic probe (`matvec_test`, 32 bit-exact runs) puts
the four channels within **0.0645 %** by mean cycles (min ch3 127,590.75,
max ch2 127,673.00) — **1.77× build_034's 0.0364 %** (min ch0 127,625.75,
max ch1 127,672.25), a widening worth recording, though both are far below any
plausible setup-failure signature and all 32 results were bit-exact with 0
errors. build_035 has no failing endpoints for this gate to watch, so R-b's
three watch-item classes retire with it; the channel probe is kept as the
standing regression it has become.

---

## 4. Three defects found, all host-side, all fixed and gated

R-d is the first time **two different model geometries have shared this
board**. All three findings are consequences of that, all three were latent in
committed tooling, and all three are the same family as R-c's walls 7 and 8:
the *host model* of the chip, not the chip.

### 4.1 The `.chip` golden compares words the run never writes (benign)

The first 2B `seq_run` produced **bit-exact tokens** but 63 of 16,404 state
checks differed (`hw_20`). The FPGA does not clear the scratchpad between
runs, while `ref/seq_model`'s memory is zero-initialised — so any word the
current stream never writes shows the *previous* model's leftovers, and the
golden calls it a mismatch. Invisible while one geometry owns the board.

Three checks, each of which could have falsified that explanation
(`rd_scratch_residue.py`, `hw_22`):

* all 63 disputed words lie in **0x1810…0x1bff** — **63/63 inside the 0.8B
  stream's staging window** (0x1000–0x3400) and **0/63 inside the 2B's own**
  (0x1c00–0x5c00). The two windows come from the artifacts' committed
  `.seq.json`, which predate the run by two days;
* scratch dumps taken before and after the 2B run are **identical at all 63**
  — the 2B run never wrote them;
* the **mirror reproduces** (`hw_21a`, analysed in `hw_22`): run the 2B first
  and the 0.8B golden then fails at **0xc10…0xfff**, 62 words. Those 62 lie
  **outside both staging windows**, so window membership does not explain
  them — what does is the 2B golden's own expectations: it checks all 62,
  expects **non-zero** at all 62, and **the board holds exactly the 2B
  golden's value at 62 of 62**. They are the 2B run's own output, left
  behind, which the 0.8B stream does not overwrite.

> **Provenance, stated plainly.** These checks were written **after** the two
> dumps were taken (dump mtimes 23:52:24 and 23:53:10, `rd_scratch_residue.py`
> 23:53:37), and `hw_20` had already printed the first eight disputed
> addresses. The claim is therefore *not* "predicted before the data existed".
> What holds is that each check's reference input is independent of the dumps
> — the staging windows are committed artifact metadata, and neither the
> A-vs-B comparison nor the mirror appears in any earlier output.

Fix: `seq_run.py --zero-scratch` writes zeros over all 32,768 words through
SPTR/SWIN (`rtl/layer_chan.sv:1078-1083`; SPTR is `:1013`, and the port is
idle-only per `:1433-1434`, so this must run before START) and reads the pad
back to prove it cleared — 0.1 s. With it **both** goldens pass outright after
the other model has owned the board: 2B **16,404/16,404** (`hw_24`) and 0.8B
**7,188/7,188** (`hw_25`).

### 4.2 The residency probe reported a resident LM head that was 61.3 MiB stale — **and the session answered with the wrong token**

This is the serious one. `chat_seq` took **one 4 KiB witness per image per
channel** and re-uploaded **only the images whose witness missed**. The LM
head is chunk-INTERLEAVED, so a channel owns ~30 of its chunks and the probe
looked at exactly one of them.

What happened, in order:

* `hw_25` — a 0.8B `seq_run4` uploads the 0.8B pack, damaging the 2B one.
* `hw_26` — the first 2B chat session probes **193 MISS**, re-uploads
  **186 of 187** images, leaves **wid 186 — the vocabulary projection** —
  stale, re-probes **0 MISS**, and answers with fluent-shaped nonsense:
  ids `[54307, 54229, 95960, 65899, 3458, 51407, 3557, 45646]`,
  *"_REGEX(dialog度NmdatedPersistentocal dove"*. **This session never emitted
  42805** — it ran the templated prompt, not the canned schedule.
* `hw_27` — the canned gate, on the board `hw_26` left behind, is where
  **42805** first appears, against the artifact's **279**.
* `hw_29`, `hw_30`, `hw_34` — the same canned gate on the same stale pack,
  returning **42805** every time. Four canned runs in total, plus `hw_26`'s
  own deterministic gibberish: **five sessions on the stale pack, none of
  them signalling an error.**

`--verify` located the blame correctly at `hw_29`: *chip 42805, seq_model 279*
— same compiled bytes, both sides, so the fault was on the board's side of the
comparison and not in the image.

Measured rather than argued. `rd_residency_audit.py` reads the whole 1,847.2
MiB pack back and compares it to the artifact files, beside the very same
probe:

| state | witness probe | full compare |
|---|---|---|
| `hw_32` clean board | 0 MISS of 756 | **0 damaged** of 866 pieces |
| `hw_33` after a 0.8B run | 193 MISS | **612/866 pieces, 398.6 MiB, 21.6 %**, all 187 images touched |
| `hw_35` after the selective re-upload of 186 | **0 MISS of 756** | **wid 186 alone — 60 pieces, 61.3 MiB, 0x250e4000…0x28ec4000** |

`hw_35` is the defect in one line: **the probe says everything is resident
while the vocabulary projection is 61.3 MiB wrong.**

Fixed two ways:

**(a) one witness per PIECE**, so every interleaved chunk is represented — a
contiguous image still gets exactly one per channel, and the set grows
748 → 866 blocks, 3.0 → 3.4 MiB, ~27 ms. **Proven on silicon** from a
deliberately re-damaged board (`hw_36`): **208 MISS → 187 images + emb
re-uploaded, 2,817 MiB verified in 14.4 s → canned gate MATCH 6/6**, where the
same sequence gave 42805 before. `chat_seq --selftest` gains a regression that
damages a **non-middle** interleaved chunk and asserts the probe catches it.

**(b) any miss invalidates the whole pack** — a witness set cannot bound what
another owner touched, so a miss now re-uploads every image rather than the
ones that happened to be probed at a damaged offset. **This branch has never
fired on hardware**: in both `hw_36` and `hw_44` the miss set already named all
187 images, so (b) was a no-op there and the silicon proof above belongs to (a)
alone. It is belt-and-braces, and it is proven only where it can be —
`reupload_set()` is a pure function and `--selftest` drives the partial-miss
case directly (one witness missing → all images + emb; emb-only miss → all
images; no miss → nothing).

> **A witness is a sample, not coverage.** 4 KiB of a piece that can be
> megabytes — ~0.19 % of the 2B head's pieces. The hit rate is measurable from
> the table above: 612 damaged pieces produced 193 misses, roughly **one
> detection per three damaged pieces**. Rule (b) is what turns that sample
> into a safe decision, and follow-on 2 is the real fix — a whole-pack hash,
> ~3 s for 1,847 MiB, which retires the sampling question instead of refining
> it.

### 4.3 `chat_seq` had three 0.8B constants baked in where the geometry varies

Found by trying to open a 2B session at all:

* `derive_geometry` could not read a **repacked** plan — `weights[wid]["base"]`
  is a per-channel LIST under R-c's repack. Now mirrors
  `seq_run.check_mvgo_targets`: each MVGO is tested against the span of its
  OWN engine channel, which collapses to the previous single span when there
  is no repack.
* the **DYNQ8 activation** `X8 = 2*H`, `n = H` — now read out of the head's
  own MOVX, with the emitter's `X8 = 2*H` law asserted as an independent
  check.
* the **const blob layout** `CONST_BYTES` and the position pool — now derived
  from the position LDCs' word counts and addresses, checked against
  `seqdata bytes == const + 6 positions`.

The derivation, run over all three artifacts (`hw_48`):

| artifact | X8_WORD / X8_LEN | CONST_BYTES | POS_WORDS / POS_STRIDE |
|---|---|---|---|
| `model_v2_s1.e` (0.8B, nch=1) | 2048 / 1024 | 998,144 | 128 / 1536 |
| `model_v2_s1.e4` (0.8B, nch=4) | 2048 / 1024 | 998,144 | 128 / 1536 |
| `model_w8_2b_s1.e` (2B, nch=4, repacked) | **4096 / 2048** | **1,098,496** | 128 / 1536 |

**How strongly each is checked, precisely.** For the **nch=1** artifact
`--selftest` [19] compares the derived values **field by field against agent
A's frozen literals** in `ref/seq_chat.py` (`TEMPLATE_NREC`, the record
boundaries, `CONST_BYTES`, `POS_BLOB_BASE`, `POS_WORDS`, `POS_COPY_BYTES`,
`POS_STRIDE`, `SEQDATA_SHA256`) plus this file's own `X8_WORD`/`X8_LEN`. The
**`.e4`** is not compared to those literals directly: it gets the structural
checks (nch, interleaved head, same const blob, same weight pack, same
expected tokens, same preamble/seed boundaries) plus — added in review round 1
— an assertion that its derived blob and x8 fields equal the **nch=1
derivation's**, which is the same set of numbers by transitivity.

Two further board-free checks back the 2B path:

* the compiled launch images are **byte-identical to the artifact's own
  records** — full-step body vs `recs[1526:18268]` and preamble vs
  `recs[0:1524]`, for the 2B and for the 0.8B nch=4 control (`hw_49`);
* the host-rebuilt RoPE pool is **byte-identical** to the six positions the 2B
  emitter committed (`hw_28`) — gate A2, extended to the 2B, so the
  512-position pool `chat_seq` uploads is trustworthy there too.

**Not checked on silicon:** `X8_WORD`/`X8_LEN` are used at runtime only by
`read_x8_eout` on the `--verify-head` path, which this gate never exercised at
2B (the chip's own top-k fed every sampled draw). The 2B values are therefore
derived, cross-checked against the emitter's law and against the compiled
images, but never read back off the board. The stride anchor
(`seqdata == const + 6·POS_STRIDE`) is likewise an independent check that
happened to agree rather than one silicon confirmed.

---

## 5. Artifacts

All under `evidence/qwen2b/rd/`. Every log carries a host/date/tree/venv
header (`rd_run.sh`); every readback in this gate is tee'd, which is the R-b
provenance lesson applied.

| file | contents |
|---|---|
| `rd_run.sh` | the stamped runner every step goes through |
| `rd_prestate.sh` | H0's pre-state capture (kept out of `bash -c` so its `pgrep` cannot match itself) |
| `rd_boardfree.sh` | B0–B2 |
| `rd_program_035.sh` | the safe reprogram (remove → JTAG → rescan → load) |
| `rd_identity.py` | the read-only CSR identity gate |
| `rd_2b_artifact_shas.sh` | T1 — the 2B artifact set against RC_GATE §2 |
| `rd_golden_shas.sh` | T1b — the `.chip` goldens the state checks are made against |
| `rd_sampled.sh`, `rd_seed_diff.sh` | the 0.8B sampled sessions and the mechanical seed diff |
| `rd_chat2b.sh` | the 2B chat wrapper (`FABLE5_MODEL=2b`, `--any-template`) |
| `rd_scratch_residue.py`, `rd_zero_scratch.py` | §4.1's three checks; a standalone pad clear |
| `rd_residency_audit.py` | §4.2's whole-pack audit beside the probe |
| `rd_posblob_check.py` | §4.3 — gate A2 at 2B |
| `rd_geom_dump.py` | §4.3 — the derived geometry of all three artifacts |
| `rd_image_dump.py` | §4.3 — compiled images vs the artifact's own records |
| `rd_census.py` | §3 |
| `hw_00…hw_51` | 57 files, one per step in wall-clock order (the numbering has `03a`, `21a`/`21b`, and four `hw_38` files, one per sampled seed) |
| `seq_run*_build035*.json`, `seq_dry_run*.json` | sequencer reports, 0.8B and 2B |
| `chat*_build035*.json`, `chat2b_*.json`, `chat_sampled_*.json` | chat sessions, both models |
| `tokmeter_4chan_build035.json`, `matvec_test_20260824_234646.json`, `census_08b.json`, `census_2b.json` | L8, L9, §3 |
| `scratch_A_08b_nch4.npy`, `scratch_B_2b.npy` | the two scratch dumps §4.1 rests on |

`hw_03a_identity_035_mvoffset_typo.log` is kept deliberately: the first pass of
`rd_identity.py` read the four matvec IDENTs at `+0x24` (`R_XWIN`) instead of
`+0x34` and printed `0xdeadc0de` four times. The six gated CSRs read
identically in both passes; the corrected pass is `hw_03`.

---

## 6. Concerns

**The board was unconfigured when this gate started.** R-b's gate was burned
by a VERSION readback that existed only in a session transcript. Here the
predecessor VERSION could not be read at all, and the *non-enumeration* is in
a tee'd log (`hw_00`) rather than in a claim. That is narrower than "we proved
the FPGA was blank" — the configuration state was never probed — but nothing
in this gate rests on what was resident before, so the distinction costs
nothing. The one place this gate did **not** live up to that standard is
§4.1's analysis, which was written after its inputs were on disk; it is
labelled as such there rather than dressed up.

**build_035 has exactly ZERO margin, not margin.** WNS 0.000 / WHS 0.000 with
0 failing setup and 0 failing hold endpoints (`TIMING_035.md` §13.4) is a
build that meets, not one that meets comfortably. A hold path at 0.000 is the
first suspect for *intermittent* behaviour, which a single pass would not
catch — so, explicitly:

> **Intermittency disposition: none observed, across repeated executions.**
> `seq_run4` ran **six** times at 0.8B — 197.685 / 197.682 / 197.673 /
> 197.687 / 197.681 / 197.679 ms, spread **0.014 ms = 0.0071 %** — and
> **four** times at 2B — 371.763 / 371.762 / 371.758 / 371.768 ms, spread
> **0.010 ms = 0.0027 %** (device times from each run's own JSON report).
> **Tokens were identical on all ten.** Both clean-scratch 2B runs gave
> 16,404/16,404 and all clean 0.8B runs 7,188/7,188. The 2B canned gate
> returned MATCH on all **three** runs where the pack was intact (`hw_31`,
> `hw_36`, `hw_44`) and the *same* wrong token on all **four** where it was
> not (`hw_27`, `hw_29`, `hw_30`, `hw_34` — the count §4.2 gives) — the
> failures were as reproducible as the passes. Sampled seed 4242 was
> byte-identical across two sessions on each
> model. **No rung was ever retried to make it pass**, and no result in this
> gate varied between executions. That is the strongest statement one
> temperature, one voltage and one board can support; it is not a substitute
> for margin.

**`--zero-scratch` is opt-in, not the default.** Every gate in §2 that
compares against a `.chip` golden across a model switch passes it explicitly.
A run without it on a board the other model has owned will still report the
§4.1 mismatches — correctly, since the words really do differ; it is the
*golden's* zeros that are the assumption. Making it the default is follow-on 1.

**The §4.2 fix costs a full re-upload (14.4 s) whenever any witness misses.**
Deliberate: the alternative is trusting a 3.4 MiB sample — which detects
roughly one damaged piece in three — to bound damage across 1,847 MiB. On a
single-model board nothing changes: the probe misses nothing and the upload is
still skipped (`hw_37`, `hw_43`).

**One board, two models, still no cross-worktree lock.** R-b's standing risk
is unchanged and now sharper: the two models *actively* overwrite each other's
DDR. `sw/.seq.lock` remains per-checkout, and `seq_run.py` / `infer.py` still
do not take it.

**A process note, since it briefly misled the diagnosis.** Twice I read the
*tail* of a long log and drew a conclusion the full log contradicted — first
believing `hw_26` had skipped its upload (it re-uploaded 186 images), then
believing `hw_44` had skipped its own (it re-uploaded 187). Both were
corrected against the file before anything was written down, and §4.2's
conclusions rest on the deliberately reproduced `hw_33`/`hw_35`/`hw_36`
sequence.

---

## 7. Follow-ons

1. **Make `--zero-scratch` the default for a `.chip`-golden run** (or teach
   `gen_seq_chip_vectors.py` to emit a written-word mask so the golden asserts
   only what the stream writes). Today the operator must know to pass it.
2. **Replace the witness sample with a whole-pack hash.**
   `rd_residency_audit.py` reads all 1,847 MiB in ~3 s, which is affordable at
   session start and retires the sampling question — §4.2 measures the current
   sample at roughly one detection per three damaged pieces.
3. **`sw/tok_meter.py` cannot plan a 2B pack** — it calls the nch-independent
   `plan_weights` (via `layer_test`), so 1.94 GB collides with `EMB_BASE` and
   it aborts before any DMA. T3 taught `hwmap`/`seq_run` the repack;
   `tok_meter` was not on that list. Until it is, the 2B census comes from
   `rd_census.py` (§3), and `tok_meter`'s richer per-opcode breakdown is
   0.8B-only.
4. **The board-lock convention is still unwritten** (R-b follow-on, restated
   with a second model on the machine).
5. **`ref/seq_chat.py` still hard-codes the 0.8B embedding row size** at two
   **offline** call sites — `_artifacts()` (the gates section) and
   `layer_fixed_greedy()` — both `.reshape(n, 1024)` over 2048 B rows. Neither
   is on the board path (`chat_seq`'s session takes `emb_row_bytes` from the
   manifest and programs EMBLOG2 from it), but a `--model-only` or offline-head
   run at 2B would read the table wrong. Same class as R-c's wall 8.
6. **`X8_WORD`/`X8_LEN` are never read back off silicon at 2B** — the
   `--verify-head` path is the only runtime consumer and this gate did not use
   it. A single `--verify-head` step at 2B would close that loop.
7. **`rd_census.py:82` hard-codes the 8.671 ms preamble** from a build_032
   measurement. R-d's own sessions measure 8.670–8.672 on build_035, so it is
   confirmed rather than assumed; taking it from the session's own JSON would
   remove the constant entirely.
8. **The 2B's DDR headroom.** 31.26 GB/s run-average against 70.70 GB/s of
   measured streaming capability says per-token overhead, not bandwidth, is
   now the 2B's limiter — the same conclusion R-b reached for the 0.8B, and
   the next lever if 16.5 tok/s is not enough.
9. **The `matvec_test` channel spread widened** 0.0364 % → 0.0645 % between
   build_034 and build_035 (mean cycles, 32 runs each). Both are far below any
   failure signature and all 32 results were bit-exact, but the two builds have
   different floorplans and the number is worth watching, not explaining away.

---

## DATED NOTE (2026-08-29) — R-d's golden-sha gate, and three follow-ons, at the 9B migration

**1. `rd_golden_shas.sh` is a RECORDING, not a gate — and the first version of
this note got that wrong.**

> **CORRECTION-OF-CORRECTION (2026-08-29, same day).** The first version of this
> note said this script "must still pass at G2a", is "pinned at G2b" and is
> "retired at G3" — i.e. it assigned it gate semantics. **It has none.** Read the
> script: it `ls`es and `sha256sum`s three `.chip` goldens and counts their `MEM`
> lines. There are **no expected values and no comparison**, so it exits 0 on any
> tree and "passing" it is not evidence of anything. `LADDER.md:615` already
> draws the distinction correctly, reporting `t4_bytes_unmoved.sh` as **PASS**
> and this script as merely **rc 0**.

What is true: the **byte-lock story runs through
`evidence/qwen2b/rc/t4_bytes_unmoved.sh` alone** (see the matching note in
`RC_GATE.md`), and that gate is retired at the Qwen3.5-9B migration's G3 when the
layer-ISA re-encoding lands. This script's real value is unchanged and is why it
stays: it is how the golden bytes get **recorded**, which is what the migration's
G2b pin needs. `build_035` and its 2B W8 pack are unaffected.

**2. Follow-on 3 (`sw/tok_meter.py` cannot plan a 2B pack) is now BLOCKING, not
cosmetic.** It calls the nch-independent `plan_weights` and aborts before any
DMA. At 9B's ~3,902 MiB weight pack the same abort applies, so the 9B bring-up
gate either fixes it or takes the census from `rd_census.py` — exactly the
workaround this gate used. Carried into the migration spec's §9 as **D-TOK**,
owned at its G2.

**3. Follow-on 2 (whole-pack hash instead of witness sampling) is folded into
the 9B upload gate.** §4.2 measured the witness sample at roughly one detection
per three damaged pieces; `rd_residency_audit.py` reads 1,847 MiB in ~3 s here
and ~5.8 GiB in ~10 s at 9B, which is affordable at session start. The migration
spec's G6 step 3 takes it.

**4. And §4.2's whole-pack re-upload branch is still selftest-proven only.** On
this board every miss set was already all-187, so the branch never fired. The 9B
bring-up is the first realistic chance to exercise it, and the migration spec's
G6 step 3 says so.

---

## DATED NOTE (2026-08-31) — the goldens are PINNED, and the recording finally has a gate beside it

The note above was written on 2026-08-29 while the migration's G2 was still
ahead. **G2a passed and G2b has landed** (2026-08-31, snoke, tree `c9d2a2f`),
so items 1 and 2 above can be closed out. Nothing above is edited — including
the correction-of-correction, which stands and is the reason this note exists
in the shape it does.

**1. `rd_golden_shas.sh` is still a RECORDING, and G2b used it as exactly
that.** It ran once more (`evidence/qwen9b/g2/rd_golden_shas_g2b.log`) and
printed the three `.chip` shas and their `MEM`/`NREC` counts —
`model_w8_2b_s1.e.chip` MEM 16,384 NREC 68,503; `model_v2_s1.e4.chip` MEM 7,168
NREC 68,119; `model_v2_s1.e.chip` MEM 7,168 NREC 60,495. All three shas match
`evidence/qwen2b/rd/hw_47_golden_shas.log` from 2026-08-25 to the digit.

**Its `rc 0` still means nothing** — `evidence/qwen2b/rd/rd_golden_shas.sh:16-18`
is a bare `sha256sum` with no expected value and no comparison — and
`evidence/qwen_next/ladder/LADDER.md:618` still draws the line correctly,
reporting `t4_bytes_unmoved.sh` as **PASS** and this script as merely **rc 0**.
What has changed is that **there is now a gate on the same bytes**:
`evidence/qwen9b/g2/final_bytelock_pin.sh` carries the expected sha256 of 54
artifacts — the frozen 0.8B chain, the 2B W8 chain, and the byte-lock's own
4-seed gold — **compares them, and exits non-zero on any mismatch**. The three
`.chip` goldens this script records are three of its rows. The record and the
reasoning are in `evidence/qwen9b/g2/FINAL_BYTELOCK.md`.

> **What the pin found about this gate's own evidence, stated plainly.** Of its
> 54 rows, **19 had an independent prior sha256 record somewhere in the repo
> and 35 did not** — and the 35 include **every byte of
> `evidence/qwen2b/rc/t4_bytes_unmoved.sh`'s reference gold**
> (`tb/scripts/w5/lay2b_w8_s*`, 28 rows). That lock compares against its gold
> **on disk** (`evidence/qwen2b/rc/t4_bytes_unmoved.sh:21`), so until 2026-08-31
> a corrupted or silently regenerated gold would have kept every future PASS
> printing without a symptom. This is not a defect in R-d; it is the hole a pin
> exists to close, and it is closed now.

**2. Follow-on 3 (`sw/tok_meter.py` cannot plan a 2B pack) — the code is
fixed, the board proof is not.** The migration's G2a taught it the repack
(`split_rows` = `LAYOUT_CONTIG`, per-channel bases threaded through the
uploader and the engine driver, the `n*2` embedding stride asserted against the
manifest and `EMBLOG2`). **It has not been exercised end to end, because that
needs a board**, so the standing advice in this document is unchanged: take the
census from `evidence/qwen2b/rd/rd_census.py` until a board run says otherwise.
The migration's G6 is where that happens.

**3. The byte-lock retires at G3, and rebuilding is UNSUPPORTED.** The ARG
re-encoding changes the emitted words at *every* geometry, so
`evidence/qwen2b/rc/t4_bytes_unmoved.sh` stops being runnable against the tree.
**This project does not keep a v1.7 emitter path**
(`docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md:2077-2085`),
so rebuilding the 0.8B or 2B artifacts from the post-migration tree is
**declared unsupported**: they already exist, they are pinned in
`evidence/qwen9b/g2/FINAL_BYTELOCK.md`, and `build_034_po2_AltSpreadLogic_high`
and `build_035_fp2a_exc_po` are frozen. **Anyone who finds the byte-lock
failing after G3 should read this note and the matching one in
`evidence/qwen2b/rc/RC_GATE.md`, not debug the script.** A failure of
`evidence/qwen9b/g2/final_bytelock_pin.sh` is the opposite case and is
serious: it hashes files where they lie and regenerates nothing, so it can only
fail because an artifact was touched, moved or lost.

**4. Items 3 and 4 of the 2026-08-29 note (the whole-pack hash, and the
re-upload branch) are untouched by G2b** and remain the 9B bring-up gate's, as
that note says.

---

## DATED NOTE (2026-08-31, later the same day) — one word too absolute about the pin

Item 3 above says a failure of `evidence/qwen9b/g2/final_bytelock_pin.sh`
*"can only fail because an artifact was touched, moved or lost"*. **That is one
branch short**, and the pin's own negative control exercises the other one.

The pin has **two** failure modes, and they call for opposite responses:

| branch | what it means | what to do |
|---|---|---|
| a sha row mismatches, or a row is `MISSING-KEY` | a pinned artifact really moved or vanished | **restore the bytes.** Nothing regenerates them after G3 |
| `DOC TABLE DRIFT` | the 54-row table in `evidence/qwen9b/g2/FINAL_BYTELOCK.md` no longer equals the script's own `expected()` | the artifacts are fine; **the document and the script disagree** and one of them was edited alone |

The second exists because the gate document reprints the table so it can be
read on its own, and two copies of a table is two things that can drift; the
pin therefore compares them on every run and its `--selftest` perturbs a temp
copy of the document to prove that comparison fires. A `DOC TABLE DRIFT` is a
bookkeeping failure, not a lost artifact, and treating it as one would send a
reader hunting for bytes that never moved.

Nothing else in the note above changes.
