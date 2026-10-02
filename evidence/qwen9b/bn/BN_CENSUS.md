# BN — the whole-token TIMELINE CENSUS (post-ship, task BN1)

## 0. HOW TO READ EVERY NUMBER BELOW — stated before the numbers

* **T** = transcribed from a named log in this directory. **D** = derived,
  with the arithmetic shown. **S** = stated by a source, cited. The reading
  rule is `evidence/qwen9b/g6/RD9_GATE.md` §0's and this document does not
  invent a second one.
* **Every number below was produced ON SNOKE**, through
  `evidence/qwen9b/run.sh`, whose header records `=== host: snoke`, the tree
  sha, the command and the operating point (`=== rs_f:`), and whose footer
  records `=== rc:` and `=== end:`. A log is cited only after both exist.
  Nothing numeric ran on darthplagueis.
* **THE TB IS NOT THE BOARD, AND THIS IS SAID ONCE, HERE, FOR THE WHOLE
  DOCUMENT.** Every measurement in this census comes from `tb/tb_seq_chip.sv`
  with its modelled memories (`WLAT = 40`, `DDRLAT = 32`;
  `tb/tb_seq_chip.sv:68-69`). That testbench measures this exact stream at
  **131.138 ms/token** (**S**, `evidence/qwen9b/s4/S4_REPLAY.md` §4.2) while
  the silicon measures **137.121 ms/token** (**S**,
  `evidence/qwen9b/g6/RD9_GATE.md` §10.1) — **the board is 4.6 % SLOWER end
  to end** (**S**, RD9 §10.4). So a share measured here is a share of a
  131 ms token, not of a 137 ms one, and no figure below is a board figure.
* **NO BOARD ACTION WAS TAKEN.** No lock, no DMA, no reprogram, no `sw/`
  tool. This census exists precisely so the question could be answered
  without board time.
* **`rtl/` IS BYTE-IDENTICAL.** The instrument is `tb/seq_timeline.svh`, a
  read-only include in the testbench; `git diff --stat HEAD -- rtl/` is
  empty at every commit in this task.
* **ONE SEED, and why that is enough for a TIME measurement.** The census
  runs `model_9b_s1` alone. `evidence/qwen9b/s4/S4_REPLAY.md` §4.2 measured
  all four model seeds on this stream and the four cycle counts —
  196,706,821 / 196,707,670 / 196,707,670 / 196,706,833 — span **849
  cycles**, i.e. **0.00043 %**. At this prompt length the token time is
  prompt-independent to four decimal places, so a second seed would measure
  the same timeline. **This is a statement about TIME and about nothing
  else**: token identity across seeds is S4's claim, not this one.

**THE VERDICT OF THIS CENSUS, stated once and before the numbers.**

**The 9B token is very nearly SERIAL, and the census measures the three terms
it is serial in.** Weight streaming (**54.408 ms/token**), mover work
(**32.545**) and layer compute (**41.610**) sum to **128.563 ms** inside a
**131.138 ms** token — **98.04 %** of it (**D**, §10.0) — so they barely
overlap at all. The single largest fact is the one the active-set
distribution states directly: for **38.97 %** of the token the four DDR
channels stream weights while the layer lane is IDLE, and for **29.10 %** the
layer computes while **no** channel streams (**T**, §5). **No channel is
streaming for 58.51 % of the token** (**T**, §6).

**The ceiling on fixing that is measured, not modelled.** Under a perfect
overlap the token could not be shorter than the busiest single resource plus
the sequencer's own residue: **55.634 ms** against the measured 131.138, a
saving of **75.503 ms/token = 57.58 %** and a speed-up of **at most 2.36x**
(**D**, §9). The binding resource is the weight path, and it is already
running at **98.68 %** utilisation inside its own streaming windows and at
**r = 1.0031** ui-cycles per 64 B beat — the engine's hard floor (**D**, §6,
§9). **There is no headroom in the streaming rate; the whole opportunity is
the 58.51 % of the token during which nothing streams.**

**On RD9 §10.2a's 9.9 %: ATTRIBUTED, NOT PROVEN — and the mechanism that
gate listed first is REFUTED.** What this census establishes is that the
board's `L_LCYC` (**41.588 ms/token**) is reproduced by the chip TB on the
**same stream** at **41.610** (**+0.053 %**, §10.2), so the 9.9 % is a
property of RD9's COMPARAND — the layer census at 45.674/46.158 — and not of
the silicon. What it **refutes** is the explanation `c995591` shipped:
"the draining instrument accounts for the whole delta" is **WRONG**.
`evidence/qwen9b/s4/S4_REPLAY.md` §5.5.4 is the campaign's own A/B and it
reads `LCYC` **46.158 ms/token** with the drain REMOVED (`NODRAIN=1`, both
`LAT = 8` and `LAT = 40`) against **45.674** with it — the drain is worth
**0.484 ms = 1.1 %, and it moves the census the WRONG WAY**. The candidate
this census can size instead is that **the two instruments do not run the
same command list**: 9,429 layer commands per token in the `.txt` half
against **8,821** in the `.e4` half, **1,376 fewer `ALU` and 768 more `VN`**,
worth **-3.104 ms/token** at the layer census's own per-command means
(**76 %** of the 4.064 ms gap) and **-4.550 ms** at this census's own
per-opcode LANE totals (**112 %** — it OVER-explains). **The two estimates
BRACKET the gap rather than falling short of it**, which is the honest
reading: the schedule difference is big enough to account for the whole of it
and then some, so **something of the opposite sign is also present and this
census did not measure it** (§10.2). **The mechanism is not settled.**

**One of the campaign's numbers is confirmed exactly, one modelled
coefficient is refuted, and two speculations are withdrawn.**

* **CONFIRMED**: the per-channel weight load reproduces
  `evidence/qwen9b/g6/RD9_GATE.md` §10.3's static `plan_weight_split`
  **exactly, byte for byte** (§6) — on the quantity that gate recorded as not
  measurable with this netlist's counters. And the matvec term, compared
  against the busiest channel as the model defines it, lands within
  **0.06 %** of the model's own 58.95 rescaled to this testbench's DDR rate
  (§10.1).
* **REFUTED**: `docs/QWEN35_NEXT_FEASIBILITY.md` §4.2's overlap coefficient
  **`m = 0.9117`** ("8.8 % of counted mover work overlaps engine time"). The
  measured overlap is **0.14 % of mover work**, i.e. **`m = 0.9986`** (§10.1).
  An earlier revision of this document read the mover row as "confirmed to
  0.35 %"; that comparison was not like-for-like and **is withdrawn** — the
  model's term is discounted by `m` and includes `LDC` and `CSRWR` work this
  census's class excludes. Like for like the gap is **-4.7 %**.
* **WITHDRAWN (1)**: RD9 §10.2 offered "the sequencer's own fetch/decode and
  its 106,244 `CSRWR` records" as part of the 65.9 %. Measured, the `CSRWR`
  records cost **0.319 ms/token = 0.24 %**, fetch and decode together
  **0.24 %**, and the fetch-empty stall is **0 to 36 cycles per token**.
  **The sequencer is not a bottleneck** (§11, §12).
* **WITHDRAWN (2)**: this document's own first revision, and the message of
  commit `c995591`, said the draining instrument accounted for the whole of
  RD9 §10.2a's 9.9 %. It does not (§10.2, and the paragraph above).

---

## 1. WHAT RAN, WHERE, ON WHICH TREE

| | |
|---|---|
| instrument | `tb/seq_timeline.svh`, included by `tb/tb_seq_chip.sv`, gated by `+timeline=<csv>` |
| elaboration | `obj_dir_seq_chip_tl` (`make -C tb tb_seq_chip_9b_tl_build`), `NMV=4 WIMGPC=1`, Verilator 5.020, `-Wall` clean |
| build log | `evidence/qwen9b/bn/001_build_tl.log` (the first build) and `evidence/qwen9b/bn/011_rebuild_from_committed_sources.log` (the provenance rung — see below) |
| runner | `evidence/qwen9b/bn/run_bn_timeline.sh` |
| artifact | `tb/scripts/w9/model_9b_s1.e4` — 158,536 records, six tokens |
| control run | `evidence/qwen9b/bn/002_control_model_9b_s1.log` (no `+timeline`) |
| census run | `evidence/qwen9b/bn/003_timeline_model_9b_s1.log` (`+timeline`) |
| raw CSV | `evidence/qwen9b/bn/bn_timeline_model_9b_s1.csv` — **20,081,098 B**, 237,784 `R,` rows + 739 `S,` rows, terminated `#END`. **It is NOT committed**: it is over the 20 MB bar this task was given. What IS committed is its `sha256` (`evidence/qwen9b/bn/bn_timeline_model_9b_s1.csv.sha256`, `a9e74bd01954f12ebf417663000b81641aa6e44d7f8d5d2145aa054bafebfb78`) and a 2,000-line head (`evidence/qwen9b/bn/bn_timeline_model_9b_s1.head2000.csv`). The file itself is on snoke, and the `SEQ_TIMELINE` block in `003`'s per-run stdout carries every total in this document without it. |
| analysis | `evidence/qwen9b/bn/bn_timeline.py` |
| analysis logs | `evidence/qwen9b/bn/008_analysis_model_9b_s1.log`, then `evidence/qwen9b/bn/009_analysis_bounds_model_9b_s1.log` (the same data, re-read after §9's resource-corrected bound and §10.0 were added to the reader) |
| fix-round check rungs | `evidence/qwen9b/bn/012_fix1_checks.log` — **SUPERSEDED by `013`: its row-based half read the CSV one column late, which its own output shows (`chan 3 = 12 beats`, every cell labelled `MLP`, a `3.17x` bound). Its signature-based half is correct and `013` reproduces it digit for digit; only that half is cited here.** Then `evidence/qwen9b/bn/013_fix1_checks_v2.log` (corrected) and `evidence/qwen9b/bn/015_fix2_lane_vs_window.log` (the per-opcode LANE-vs-window histogram) |
| binary hashes | `evidence/qwen9b/bn/016_binary_sha256.log` |
| small-scale control | `evidence/qwen9b/bn/005_smoke_control_tok9b.log` / `evidence/qwen9b/bn/006_smoke_timeline_tok9b.log`, analysed in `evidence/qwen9b/bn/007_smoke_analysis_tok9b.log` |
| runner self-test | `evidence/qwen9b/bn/000_runner_selftest_lay9b.log` |

**Both runs are the SAME BINARY.** That is what makes the control a control:
the difference between them is one plusarg and nothing else. Both run headers
record the identical `=== built 2026-09-15T15:44:07-06:00`, and `002` and
`003` overlap in wall clock, so nothing could have rebuilt between them.

**THE BINARY'S PROVENANCE, stated as the FORWARD claim it is.** The build log
`001` ends at 15:40:38 while the binary every run used is stamped 15:44:07 —
an unlogged second verilate+link sat between them, so the
committed-source-to-binary chain had a hole.

**What IS established**, and it is a forward claim:
`evidence/qwen9b/bn/011_rebuild_from_committed_sources.log` rebuilds from the
**clean committed tree** — its header reads `=== tree: 334f80b` with no
`+dirty` — into the same obj_dir, `rc: 0`; and
`evidence/qwen9b/bn/016_binary_sha256.log` records that this is the binary
that tree produces:
**`6dd2b4e77cac50c63fd7da78e6d1301ce15a3cfc86024d9c09a59497131ce7ca`**
(generated source `Vtb_seq_chip.cpp`:
`bb255c69f026161b741662e76a781e6c064bac7a97f8ee8df584a56a46d88e33`). **The
committed sources in this repository build that binary, and an independent
reviewer verified the same hash on snoke.**

**What is NOT established, and the reason, stated plainly.** The rebuild
**overwrote** the 15:44:07 binary the runs actually used, so **that file no
longer exists and cannot be re-hashed by anyone**. The only hash of it
anywhere is the one `016` prints for `/tmp/bn1_binary_that_ran` — a copy
taken in session at 18:55:24, three minutes before the rebuild — and it does
agree, byte for byte, on both the binary and the generated source. But
**that is a committed log's record of an UNCOMMITTED copy**: the file it
hashes lives in `/tmp` on snoke, is not in this repository, and cannot be
reproduced by a later reader, so its hash is evidence about a copy rather
than about an artefact anyone can check. **The byte-identity of the run
binary to the committed tree's binary is therefore DISCLOSED, not claimed,
and the committed claim of this document is the forward one above.**

What the control actually needs is weaker than either and **is** in evidence:
that both legs ran the same binary (identical `=== built` strings, overlapping
wall clock) and that their cycle counts and tokens match
`evidence/qwen9b/s4/S4_REPLAY.md` §4.2's independent committed record. **No
re-run of the replays was needed, and none was done.**

### 1.1 What the instrument samples, and where each signal lives

Per aclk cycle, while the sequencer is busy (`rtl/seq_unit.sv:360`'s
`busy_r` — the same condition `PERF_CYC` counts on, `rtl/seq_unit.sv:975`,
so the census total is checkable against the DUT's own CSR):

| bit | class | signal | `file:line` |
|---|---|---|---|
| 0 | `L_CMP` | layer compute lane | `rtl/layer_chan.sv:455` |
| 1 | `L_DMA` | layer state-DMA lane | `rtl/layer_chan.sv:687` |
| 2 | `MOVER` | `seq_movers` engine busy | `rtl/seq_unit.sv:877` |
| 3 | `SEQBULK` | LDC/EMB DDR read active | `rtl/seq_unit.sv:507` |
| 4-7 | `MVc_STR` | a weight R beat on channel `c` this cycle | `tb/seq_mem_file.sv:348` |
| 8-11 | `MVc_BSY` | matvec channel `c` engine busy | `rtl/matvec_chan.sv:233-236` |
| 12 | `SMEM_RD` | state-window read beat | `tb/tb_seq_chip.sv:427` |
| 13 | `SMEM_WR` | state-window write beat | `tb/tb_seq_chip.sv:431` |
| 14 | `RECDDR` | record/LDC/EMB read beat | `tb/tb_seq_chip.sv:162` |
| 15 | `BFAB` | burst fabric has a transfer outstanding | `tb/seq_burst_fabric.sv:227` |

Counted beside the signature, not in it: the fetch-empty stall
(`rtl/seq_unit.sv:981`'s own condition), the AXI-Lite fabric's outstanding
counters, the issue FSM state (`rtl/seq_unit.sv:853`) and the mover's
`mv_op`.

**The weight bits cross a clock domain and are COUNTED, not sampled.** The
weight memories run on `ui_clk` (~300 MHz) and the sampler on `clk`
(250 MHz), so a level sampled at the slower edge would drop beats. The
instrument takes the DELTA of each model's own R-beat counter
(`tb/seq_mem_file.sv:348-349`, surfaced at `tb/tb_seq_chip.sv:174`) since
the previous negedge: lossless in the aggregate, and the deltas are what
the beats/cycle rate in §6 is computed from.

### 1.2 The token boundary is the EMB record, and that is a correction

`model_9b_s1` decodes six tokens but does **not** loop six times. Its stream
writes **four** forward steps out — their `OP_EMB` records are at indices
39, 39,663, 79,286 and 118,911 — and the last of them is a `TCNT_SEQ = 3`
loop body (`CSRWR -> 0x2020 imm 3` at record 118,910, `OP_JMP` with
`flags[0]` at 158,534 targeting 118,911; `rtl/seq_unit.sv:1137-1149`). So
**`pc` steps backward only TWICE in the whole launch while six tokens come
out**, and the run's own `SEQ_TIMELINE backjump` line records exactly that.

**What that does and does not break.**
`evidence/qwen9b/g6/RD9_GATE.md` §10.1's steady-state convention — "cycles
between consecutive backward jumps of `S_PC`" — is **fine on this stream**:
the two backward steps land at busy cycles 131,117,936 and 163,909,967, so
the span between them is **32,792,031 cycles = exactly one token** (segment
5, 131.168 ms). The loop body IS one token, run three times. **An earlier
revision of this section claimed that convention measured a three-token span
here; that was wrong and is withdrawn.** What the backward jump cannot do is
**segment** the launch: with only two of them and six tokens, the first four
tokens land in one bucket. **That — and only that — is why the census
segments on `OP_EMB` instead**:
segment 0 is the launch preamble (records 0..38) and segments 1..6 are the
six tokens. The two or three records between an `AMAXL` and the following
`EMB` are charged to the outgoing token.

---

## 2. THE CONTROL — the instrument is READ-ONLY, and it is MEASURED

**T**, both logs, both `rc: 0`:

| run | `+timeline` | cycles | tokens | wall | verdict |
|---|---|---|---|---|---|
| `002_control_model_9b_s1.log` | absent | **196,706,821** | `[2614, 314, 279, 369, 11751, 13]` | 8,805 s | `BN_TIMELINE model_9b_s1 control: PASS` |
| `003_timeline_model_9b_s1.log` | present | **196,706,821** | `[2614, 314, 279, 369, 11751, 13]` | 8,472 s | `BN_TIMELINE model_9b_s1 timeline: PASS` |
| the record (**S**) | — | **196,706,821** | the same | 9,211 s | `evidence/qwen9b/s4/S4_REPLAY.md` §4.2 |

**Not one cycle moved, and not one token moved.** Both runs are the same
binary; the comparison against the committed record is made by the runner
against the document, not by a reader
(`evidence/qwen9b/bn/run_bn_timeline.sh`), and a mismatch on either FAILS
the rung. The control additionally asserts that it printed **no**
`SEQ_TIMELINE` block and the census that it printed one, so the gate cannot
leak in either direction.

**The instrumented run was FASTER in wall clock than the control** — 8,472 s
against 8,805 s, on a shared machine — which is host noise, and it is
reported because it is the honest form of "the instrument costs nothing
measurable". The controlled measurement of that cost is the small-scale
pair, where the two runs of `tok9b_s1.e4` both give **3,893,746** cycles at
172 s and 177 s (**T**, `005`/`006`).

**And the census's own total is the DUT's own counter.** `SEQ_TIMELINE meta
bcyc=196706812` against the testbench's `196,706,821` launch cycles: the
nine-cycle difference is the host BFM's `START` write and `STATUS` poll
either side of `busy_r`, which the testbench's `$time`-based launch window
includes and `rtl/seq_unit.sv:975`'s `perf_cyc` does not.

---

## 3. THE TOKEN, IN CYCLES

**T** for the cycles (`evidence/qwen9b/bn/009_analysis_bounds_model_9b_s1.log`),
**D** for the ms.

| segment | cycles | ms @250 MHz | fetch-empty stall | sequencer-only |
|---|---|---|---|---|
| 0 — the **preamble** (records 0..38) | 173 | 0.001 | 0 | 29 |
| 1 | 32,771,865 | 131.087 | 0 | 309,127 |
| 2 | 32,776,832 | 131.107 | 0 | 307,217 |
| 3 | 32,782,160 | 131.129 | 0 | 306,692 |
| 4 | 32,786,868 | 131.147 | 36 | 306,218 |
| 5 | 32,792,031 | 131.168 | 36 | 305,720 |
| 6 | 32,796,845 | 131.187 | 0 | 305,411 |
| **tokens 1..6** | **196,706,601** | **786.826** | 72 | 1,840,385 |
| **mean per token** | **32,784,433** | **131.138** | 12 | 306,731 |

**Why the preamble row disagrees with the run's own block, and it is not an
error.** `003`'s `SEQ_TIMELINE` prints `tcyc 0 211`, `none 0 65`,
`stall 0 24` for segment 0 where the table above says 173, 29 and 0. The
table is the **per-record** view and the block is the **per-cycle** view, and
they differ by the **38 cycles the sequencer spends in `I_SYNC` before the
first record is ever latched** — inside the signature histogram, inside no
record's window. `009` reports that residue explicitly and the two views
agree everywhere else, on all six tokens, to the cycle. The 173 is therefore
**D** (the per-record partition) while 211 is **T**; the rest of the table is
**T**.

**131.138 ms/token is `evidence/qwen9b/s4/S4_REPLAY.md` §4.2's number to
three decimals**, reached from a completely different direction: S4 divided
the launch total by six, this census sums the per-record windows and
segments them at the `OP_EMB` records. The two agree.

**The token gets monotonically longer: 131.087 -> 131.187 ms, +0.100 ms over
six steps (+0.076 %, D).** That is the KV term growing with `T`, visible at a
prompt length where it is almost nothing;
`evidence/qwen9b/g6/RD9_GATE.md` §8.7 measures the same effect on silicon as
**+7.4 %** at `T ~ 520`. **This census says nothing about long context** — it
is six steps at a short `T` — and the monotonic drift is quoted only because
it is the same phenomenon at its small end.

---

## 4. CLASS TOTALS — where the token's cycles go

Mean over tokens 1..6. **T** for the cycles, **D** for ms and shares. These
classes OVERLAP — that is the whole point of the census — so they do not sum
to 100 %.

| class | cyc/token | ms/token | % of token |
|---|---|---|---|
| `MOVER` (`mv_busy`, **includes the FENCE drain wait**) | 21,734,076 | 86.936 | 66.29 % |
| `MV0_BSY` / `MV1_BSY` / `MV2_BSY` / `MV3_BSY` | 13,582,164 / 13,539,262 / 13,524,904 / 13,524,926 | 54.329 / 54.157 / 54.100 / 54.100 | 41.43 / 41.30 / 41.25 / 41.25 % |
| `MV0_STR` / `MV1_STR` / `MV2_STR` / `MV3_STR` | 13,402,775 / 13,360,363 / 13,346,295 / 13,346,241 | 53.611 / 53.441 / 53.385 / 53.385 | 40.88 / 40.75 / 40.71 / 40.71 % |
| `L_CMP` | 10,402,465 | **41.610** | 31.73 % |
| `BFAB` | 8,334,361 | 33.337 | 25.42 % |
| `L_DMA` | 1,292,900 | **5.172** | 3.94 % |
| `SMEM_RD` / `SMEM_WR` | 446,130 / 443,328 | 1.785 / 1.773 | 1.36 / 1.35 % |
| `SEQBULK` | 322,517 | 1.290 | 0.98 % |
| `RECDDR` | 74,719 | 0.299 | 0.23 % |

Grouped, with each group's cycles taken as its **exact union** out of the
per-cycle signature histogram rather than as a sum of its members (**D**):

| group | cyc/token | ms/token | % of token |
|---|---|---|---|
| mover engine (`mv_busy`) | 21,734,076 | 86.936 | 66.29 % |
| matvec engine, any channel | 13,614,984 | 54.460 | 41.53 % |
| **weight streaming, any channel** | **13,601,885** | **54.408** | **41.49 %** |
| layer compute | 10,402,465 | 41.610 | 31.73 % |
| burst fabric | 8,334,361 | 33.337 | 25.42 % |
| layer state-DMA | 1,292,900 | 5.172 | 3.94 % |
| state window | 889,458 | 3.558 | 2.71 % |
| record/LDC/EMB DDR | 361,840 | 1.447 | 1.10 % |
| **UNION — any class at all** | **32,477,703** | **129.911** | **99.06 %** |
| **RESIDUE — nothing but the sequencer** | **306,731** | **1.227** | **0.94 %** |

Per token rather than averaged (**D**, ms):

| group | seg0 | tok1 | tok2 | tok3 | tok4 | tok5 | tok6 |
|---|---|---|---|---|---|---|---|
| layer compute | 0.000 | 41.558 | 41.578 | 41.599 | 41.620 | 41.641 | 41.662 |
| layer state-DMA | 0.000 | 5.239 | 5.153 | 5.155 | 5.158 | 5.161 | 5.164 |
| mover engine | 0.000 | 86.936 | 86.936 | 86.937 | 86.936 | 86.937 | 86.936 |
| weight streaming | 0.000 | 54.408 | 54.407 | 54.408 | 54.408 | 54.408 | 54.407 |
| matvec engine | 0.000 | 54.460 | 54.460 | 54.460 | 54.460 | 54.460 | 54.460 |
| burst fabric | 0.000 | 33.337 | 33.337 | 33.338 | 33.337 | 33.337 | 33.337 |
| state window | 0.000 | 3.614 | 3.543 | 3.545 | 3.547 | 3.549 | 3.551 |
| record/LDC/EMB DDR | 0.000 | 1.447 | 1.447 | 1.448 | 1.447 | 1.447 | 1.447 |
| UNION | 0.001 | 129.851 | 129.878 | 129.902 | 129.923 | 129.945 | 129.966 |
| RESIDUE | 0.000 | 1.237 | 1.229 | 1.227 | 1.225 | 1.223 | 1.222 |
| TOTAL | 0.001 | 131.087 | 131.107 | 131.129 | 131.147 | 131.168 | 131.187 |

**Every term except the layer's is flat to five significant figures across the
six tokens**, and the whole of the drift lands on `layer compute`
(41.558 -> 41.662, +0.104 ms) with `layer state-DMA` and the state window falling
slightly. That is the KV growth, and it is confined to the layer.

**The residue is 0.94 % of the token.** Under one per cent of the step is
spent with no engine, no DMA and no bus doing anything — the sequencer alone.

---

## 5. THE ACTIVE-SET SIGNATURE DISTRIBUTION — the headline

Per cycle, which set of classes was active, summed over tokens 1..6. **T**
for the cycles, **D** for ms and share. **129 distinct signatures occurred;
the top 12 cover 97.84 % of the token.**

| # | mask | cyc/token | ms/token | share | active set |
|---|---|---|---|---|---|
| 1 | 4084 | 12,775,116 | **51.100** | **38.97 %** | `{mover, all 4 streaming, all 4 engines busy}` |
| 2 | 1 | 9,539,320 | **38.157** | **29.10 %** | `{layer}` — **and nothing else** |
| 3 | 32772 | 7,720,364 | 30.881 | 23.55 % | `{mover, burst fabric}` |
| 4 | 4099 | 346,915 | 1.388 | 1.06 % | `{layer, state-DMA, state-window read}` |
| 5 | 8195 | 332,441 | 1.330 | 1.01 % | `{layer, state-DMA, state-window write}` |
| 6 | 0 | 306,731 | 1.227 | 0.94 % | `{sequencer only}` |
| 7 | 32774 | 200,881 | 0.804 | 0.61 % | `{state-DMA, mover, burst fabric}` |
| 8 | 32776 | 182,764 | 0.731 | 0.56 % | `{LDC/EMB bulk, burst fabric}` |
| 9 | 3956 | 173,918 | 0.696 | 0.53 % | `{mover, chans 0/1/2 streaming, all 4 busy}` |
| 10 | 4068 | 165,792 | 0.663 | 0.51 % | `{mover, chans 1/2/3 streaming, all 4 busy}` |
| 11 | 4052 | 165,379 | 0.662 | 0.50 % | `{mover, chans 0/2/3 streaming, all 4 busy}` |
| 12 | 4020 | 165,368 | 0.661 | 0.50 % | `{mover, chans 0/1/3 streaming, all 4 busy}` |

**A SIGNATURE IS THE COMPLETE ACTIVE SET OF A CYCLE, so distinct rows CANNOT
overlap — that is construction, not a finding.** The finding is **which**
sets dominate, and how few of them there are: 129 occurred and three of them
are 91.62 % of the token.

**READ ROWS 1 AND 2 TOGETHER. THAT IS THE ANSWER TO "WHAT WOULD OVERLAP
BUY".** Row 1 is 38.97 % of the token in which all four DDR channels are
streaming weights and **the layer lane is doing nothing**. Row 2 is 29.10 %
in which the layer lane is computing and **nothing is streaming, nothing is
moving and no bus is busy**. Those two states alone are **68.07 %** of the
token (**D**). Row 3 —
another 23.55 % — is the mover pushing `MOVX`/`MOVY` traffic over the burst
fabric with neither the layer nor the weight path engaged.

**Rows 1, 2 and 3 are 91.62 % of the token between them.** Their
non-overlap is by construction; what is measured is that **three sets out of
129 carry nine tenths of the step**, and that the three are *these* three.
The 9B decode step is three phases, and it spends its time in one at a time.

**Row 6 is the sequencer's whole overhead: 0.94 %.**

---

## 6. WEIGHT STREAMING, PER CHANNEL

**T** for beats and cycles, **D** for the rest. Mean over tokens 1..6.

| chan | beats/token | MiB/token | streaming cyc | engine-busy cyc | beats/cyc | **utilisation inside the streaming window** |
|---|---|---|---|---|---|---|
| 0 | 16,030,080 | **978.40** | 13,402,775 | 13,582,164 | 1.1960 | **98.68 %** |
| 1 | 15,979,392 | **975.30** | 13,360,363 | 13,539,262 | 1.1960 | **98.68 %** |
| 2 | 15,962,496 | **974.27** | 13,346,295 | 13,524,904 | 1.1960 | **98.68 %** |
| 3 | 15,962,496 | **974.27** | 13,346,241 | 13,524,926 | 1.1960 | **98.68 %** |
| total | 63,934,464 | 3,902.24 | — | — | — | — |

**ONE INDEPENDENT CROSS-CHECK AND ONE LOSSLESSNESS CHECK — both exact, and
they are not the same kind of thing.**

1. **Independent** (a different instrument entirely). The four MiB figures are `evidence/qwen9b/g6/RD9_GATE.md` §10.3's
   per-channel weight load — **978.40 / 975.30 / 974.27 / 974.27** — which
   that gate derived STATICALLY from `plan_weight_split` and could not
   measure, because "the per-token per-channel spread is not measurable on
   the sequencer path with the counters this netlist has". **The census
   measures it, and it is the static split byte for byte.** max/min =
   **1.004234** (**D**), RD9 §10.3's own figure.
2. **NOT independent — it is a losslessness check, and worth having as
   that.** 63,934,464 beats/token x 6 tokens = **383,606,784**, which is
   `evidence/qwen9b/s4/S4_REPLAY.md` §4.2's `weight beats 383606784 total
   across 4 chan (miss 0)` exactly. But that figure and this census read the
   **same** `seq_mem_file` R-beat counters (`tb/seq_mem_file.sv:348-349`);
   what the equality proves is that **sampling those counters as negedge
   deltas across the `ui_clk`/`clk` boundary loses nothing** — the one thing
   about the weight bits that could have gone wrong. It is not a second
   instrument and this document does not call it one.

**THE FOUR CHANNELS STREAM TOGETHER, NOT IN TURN.** Cycles per token by how
many channels were streaming at once (**T**/**D**):

| channels streaming | cyc/token | share of the token |
|---|---|---|
| **0** | **19,182,548** | **58.51 %** |
| 1 | 65,078 | 0.20 % |
| 2 | 35,844 | 0.11 % |
| 3 | 684,944 | 2.09 % |
| **4** | **12,816,019** | **39.09 %** |

**94.22 %** of the time any channel is streaming, **all four** are (**D**:
12,816,019 / 13,601,885). The four-channel split is doing its job: the
engines are not taking turns, they are saturating together and finishing
together.

**AND THE PATH IS ALREADY AT ITS FLOOR WHILE IT RUNS.** 1.1960 beats per
aclk cycle is **1.0031 ui-cycles per 64 B beat = 19.14 GB/s/chan** (**D**,
`tb/tb_seq_chip.sv:110-111` gives aclk 250.00 MHz and ui_clk 299.94 MHz),
against the **r = 1.000** that `docs/QWEN35_NEXT_FEASIBILITY.md` §4.2 calls
the engine's hard floor. Inside its own windows the weight path is 98.68 %
busy and running at the floor. **Nothing about the streaming RATE is
available to be improved on this instrument; the 58.51 % idle is the whole
opportunity.**

**Phases.** 343 maximal runs of consecutive records with any matvec engine
busy, per token (**T**) — exactly the **343 `FENCE` records per token**
(§12), so a phase is one fenced matvec batch and there are 343 of them in a
step.

---

## 7. PER LAYER TYPE — DeltaNet, GQA, the LM head

**The boundaries are DERIVED from the record stream, not assumed.** The token
is cut at every `CSRWR -> layer 0x30` (`LAYER`, the cache-slot select —
`rtl/layer_chan.sv:26-27`) and each cell is labelled by the layer opcodes
dispatched inside it. Cells are **not** merged: consecutive cells of the same
label are consecutive layers. Every token gives **64 cells**: **24 `DN`**,
**39 `GQA`**, **1 `HEAD`** (**T**).

**And the derivation is checked against two independent markers in the same
stream** (**T**): `CSRWR -> layer 0x5C` (`DNSB`, "written ONCE PER LAYER
BODY", `rtl/layer_chan.sv:46`) occurs **24 times per token** — exactly the 24
`DN` cells and exactly the 9B's 24 DeltaNet layers — and the `ROPET` layer
command occurs **8 times per token**, exactly the 8 GQA layers.

**THE PER-LAYER DIVISION IS VERIFIED, NOT ASSUMED**
(**T**, `evidence/qwen9b/bn/013_fix1_checks_v2.log`). An earlier revision
asserted that "each GQA layer body crosses several `LAYER` writes" and then
divided 39 cells by 8 layers, which is not an integer and was an explanation
rather than a check. The check:

* the 24 `DN` cells fall into **8 maximal runs** and the 39 `GQA` cells into
  **8 maximal runs** — the 3-DeltaNet-then-1-GQA cadence, per token;
* **every one of the 8 GQA runs contains exactly ONE `ROPET` command**
  (distinct values over all six tokens: `[1]`), so **the 8 runs ARE the 8 GQA
  layers** and dividing by 8 is a measurement;
* **label purity: NONE violated** — no `DN` cell dispatches a
  `ROPET`/`ROPE`/`KVAP`/`ATTN` and no `GQA` cell dispatches a `DNST`, so each
  layer's body does land under its own label;
* the three labels account for **32,779,657 of the token's 32,784,433
  cycles**, leaving **4,777 cycles = 0.0146 %** outside any cell (the records
  before the token's first `LAYER` write). That remainder is why the three
  shares below sum to 99.99 % and not 100 %.

| label | cells/token | layers/token | cyc/token | ms/token | % of token | ms per LAYER |
|---|---|---|---|---|---|---|
| **DN** | 24 | **24** | 23,492,985 | **93.972** | **71.66 %** | **3.916** |
| **GQA** | 39 | **8** | 6,101,817 | **24.407** | **18.61 %** | **3.051** |
| **HEAD** | 1 | 1 | 3,184,855 | **12.739** | **9.71 %** | 12.739 |

The class split inside each cell type (**D**; `wstr`/`mvbsy` are the
**per-channel mean** over the four channels, every other column is that
resource's own busy fraction of the cell; they overlap and do not sum
to 100 %):

| label | layer compute | state-DMA | mover | wstr | matvec | state win | record DDR | burst fabric | seq-only |
|---|---|---|---|---|---|---|---|---|---|
| DN | 35 % | 5 % | 63 % | 38 % | 38 % | 2 % | 1 % | 25 % | 1 % |
| GQA | 29 % | 0 % | 69 % | 42 % | 42 % | 0 % | 1 % | 27 % | 1 % |
| HEAD | **13 %** | 2 % | **87 %** | **63 %** | **63 %** | 1 % | 0 % | 22 % | 0 % |

**The DeltaNet layers are the token.** 24 of 32 layers, 71.66 % of the step,
3.916 ms each against a GQA layer's 3.051 — **28 % more per layer**, and
twenty-four of them.

**The LM head is almost pure weight streaming.** 12.739 ms/token, 9.71 % of
the step, with the layer lane busy only 13 % of it and the weight path 63 %.
It is the one cell where overlap has almost nothing to hide behind: there is
barely any layer compute to hide the stream under.

---

## 8. THE GANTTS

**T**, `evidence/qwen9b/bn/009_analysis_bounds_model_9b_s1.log`. One column
per bucket of records, one row per resource; the glyph is that resource's
busy fraction inside the bucket (` `=0 through `.:-=+*#%@`->100 %).
`wstr`/`mvbsy` are the per-channel mean.

**A DeltaNet layer (token 4, records 118,920..120,336 — 1,417 records,
973,902 cycles = 3.896 ms):**

```
layer compute               |%-    @@@%@%%%@%%%@%%@%%%@%%@%%%@%%%@%%@%%%@%%@%%%@%%%@%%@%%%@%%@%%%@%%%@%%@%%%@%%@%%%@%%%@%%@%%%@%%@%%%@%%%@%%@%%%@%%@%%%@%@ -@ -= -   @@- @ |
layer state-DMA             |@                                                                                                                                            @|
mover engine                | *@@@@                                                                                                                       @: @*+@*@@%  *@  |
weight streaming (any chan) |  ##                                                                                                                         *  #  %  #*   @  |
matvec engine (any chan)    |  ##                                                                                                                         *  #  %  #*   @  |
record/LDC/EMB DDR          |.                                                                                                                             :               |
state window                |-                                                                                                                                            =|
burst fabric                |.*::@@   .                                                                                                                   -* :*=.*@::  *   |
```

Read it left to right: the layer's weights stream at the START of the body
(the `##` at columns 2-3), then the whole middle of the layer — roughly 85 %
of its width — is `layer compute` at 100 % with **nothing streaming at all**,
and the stream returns only at the end for the next body's matvecs. **The
serialization is not subtle; it is the shape of the picture.**

**A GQA layer (token 4, records 123,163..123,462 — 300 records, 208,520
cycles = 0.834 ms):**

```
layer compute               |  @ @ @                     @  @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ # @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @    |
layer state-DMA             |                                                                                                                                                   +@@|
mover engine                |       @@%%@@@@@%@@@@@%%@@*                                                                                                                           |
weight streaming (any chan) |          =@    .@     -@                                                                                                                             |
matvec engine (any chan)    |         .*@    =@    .*@                                                                                                                             |
record/LDC/EMB DDR          |+         .               :  +                                                                 .                                                    = |
state window                |                                                                                                                                                     .|
burst fabric                |@      @@   @@@@  %%@@   %@  @                                                                 :                                                      |
```

The same shape, harder: three short streaming bursts in the first fifth,
then the attention body runs the layer lane flat out for the remaining 80 %
with the weight path completely idle.

**The LM head (token 4, records 157,543..158,534 — 992 records, 3,184,952
cycles = 12.740 ms):**

```
layer compute               |@@@@@*  =@- =.@ -=   *@@@- @  @* .-= =.@ -= --@ .- -=- -- .-= =.@ -= --@ .- -=- -- .-= =.@ -= --@ .- -=- -- .-= =.@ -= --@ .- -=- -- .-= =. *%|
layer state-DMA             |                            %@@@.                                                                                                             |
mover engine                |     -@@  *@+# @*=@@@-   *@    -@%*+@+% @*+@** @%*@*+*@**@%*+@+% @*+@** @%*@*+*@**@%*+@+% @*+@** @%*@*+*@**@%*+@+% @*+@** @%*@*+*@**@%*+@+%@- |
weight streaming (any chan) |       %   @   %   #%     @     %   @   %  @   %  %   @  @   @   %  @   %  %   @  @   @   %  @   %  %   @  @   @   %  @   %  %   @  @   @  :  |
matvec engine (any chan)    |       %   @   %   #%     @     %   @   %  @   %  %   @  @   @   %  @   %  %   @  @   @   %  @   %  %   @  @   @   %  @   %  %   @  @   @  :  |
record/LDC/EMB DDR          |        :                    +                                                                                                                |
state window                |                            -==-                                                                                                              |
burst fabric                |     -@.+ * =# .*=@:.-   *   @ -.#*= +# .*+ **  #* *+* ** #*= +# .*+ **  #* *+* ** #*= +# .*+ **  #* *+* ** #*= +# .*+ **  #* *+* ** #*= +# - |
```

A different regime: the head **interleaves** at a fine grain — stream, a
little compute, stream — because the vocabulary matvec is chopped into many
fenced batches. It is the closest thing in the step to overlapped execution,
and it is still alternating rather than concurrent.

**The whole token (token 4, 39,624 records, 32,786,868 cycles = 131.147 ms),
150 columns of ~265 records:**

```
layer compute               |-@@@::@@@@:@@@@::-:@@@@:@@@@:-@@@-.@:@@@@:-@@@::@@@@.@:-@@@::@@@@:@@@@:--:@@@@:@@@@:=@@@::@:@@@@:-@@@::@@@@.@:-@@@::@@@@:@@@@::-:@@@%:@@@@:-@@@::*. . |
layer state-DMA             |                             .            .            .                            .            .            .                 .                     |
mover engine                |+   *#    #    ##+#    #    #+   *# #    #*   *#    # #*   *#    #    #*+#    #    #+   *# #    #*   *#    # #*   *#    #    ##*#    #    #*   *#-%@%@|
weight streaming (any chan) |-   ==    =    =+-=    =    =:   -= =    =-   ==    = =-   ==    =    =--=    =    =:   == =    =-   ==    = =-   ==    =    =-=-    =    =-   ==:+***|
matvec engine (any chan)    |-   ==    =    =+-=    =    =:   -= =    =-   ==    = =-   ==    =    +--=    =    =:   == =    =-   ==    = =-   ==    =    =-=-    =    =-   ==:+#**|
record/LDC/EMB DDR          |                                                                                                                                                      |
state window                |                                                                                                                                                      |
burst fabric                |-   :-    -    -::-    -    ::   :- -    :-   :-    - :-   :-    -    :-:-    -    ::   :- -    ::   :-    - :-   ::    :    :-:-    -    :-   :-.:.:.|
```

Thirty-two layers of the same alternation, end to end.

---

## 9. THE TWO UPPER BOUNDS

### 9.1 (i) What a PERFECT overlap would save

**What "perfect" assumes, stated exactly, because the number is worthless
without it:** that every resource below could run concurrently with every
other; that there is **no data dependency** between a weight stream and the
layer command that consumes its result; that there is **no shared bus and no
arbitration cost**; that each resource's busy time stays exactly what this
run measured; and that **nothing else changes**. It is an **upper bound on
the saving**, not a design target, and no RTL change is claimed to reach it.

**(i-a) The formula literally, over the instrumented classes** (**D**):

| | cyc/token | ms/token |
|---|---|---|
| union (any class active) | 32,477,703 | 129.911 |
| busiest class — `mover engine` | 21,734,076 | 86.936 |
| **saving bound** | **10,743,627** | **42.975** = 32.77 % of the token |

**(i-b) And the same formula over RESOURCES, which is the one to read.**
(i-a) is bound by `mover engine`, and that class is `mv_busy`, which stands
for the whole of a `FENCE` drain as well as for real mover work — **a WAIT,
not a resource doing anything** (§10a). Splitting it at the signature level
into `MOVER`-with-nothing-streaming (real `MOVX`/`MOVY`/`LDC` traffic) and
`MOVER`-while-streaming (the `FENCE` wait, whose resource is the weight path
and is already counted) gives the resources that actually occupy hardware
(**D**):

| resource | cyc/token | ms/token | % of token |
|---|---|---|---|
| **weight streaming (any chan)** | **13,601,885** | **54.408** | **41.49 %** |
| layer compute | 10,402,465 | 41.610 | 31.73 % |
| burst fabric | 8,334,361 | 33.337 | 25.42 % |
| mover work (`MOVER`, nothing streaming) | 8,136,299 | 32.545 | 24.82 % |
| layer state-DMA | 1,292,900 | 5.172 | 3.94 % |
| state window | 889,458 | 3.558 | 2.71 % |
| record/LDC/EMB DDR | 361,840 | 1.447 | 1.10 % |
| *(for reference: `MOVER` while a channel streams — the `FENCE` wait)* | *13,597,777* | *54.391* | *41.47 %* |

| | cyc/token | ms/token |
|---|---|---|
| union | 32,477,703 | 129.911 |
| **busiest RESOURCE — the weight path** | **13,601,885** | **54.408** |
| **SAVING BOUND** | **18,875,818** | **75.503** = **57.58 %** of the token |
| floor = busiest resource + the sequencer-only residue | 13,908,616 | **55.634** |

**A 131.138 ms token could not, under perfect overlap, be shorter than
55.634 ms — a speed-up of at most 2.36x** (**D**). The residue of 1.227 ms
is not in the union and **no amount of overlap removes it**.

**And 2.36x is the bound for a schedule that leaves the four channels as this
run leaves them.** The binding resource, "weight streaming (any chan)", is
the UNION over four channels that do not finish together: 54.408 ms of union
against the busiest channel's own 53.611 (§9.2). A schedule that also evened
the channels would be bound by a single channel instead, and the floor
becomes **53.611 + 1.227 = 54.838 ms = 2.39x** — or, redistributing the
63,934,464 beats/token evenly and holding the measured 1.1960 beats/cycle,
**53.456 + 1.227 = 54.683 ms = 2.40x** (**T**/**D**,
`evidence/qwen9b/bn/013_fix1_checks_v2.log`). **So the honest ceiling is
2.36x as scheduled and 2.39-2.40x if the channels are rebalanced too**, and
an earlier revision's "nothing above 2.36x is available however the overlap
is built" was 1 % too strong.

### 9.2 (ii) The DDR-bound floor

The busiest channel's weight bytes at the beats/cycle **this run itself
measured** while that channel was streaming (**D**):

| chan | beats/token | beats/cyc | floor cyc/token | floor ms/token |
|---|---|---|---|---|
| **0** | **16,030,080** | 1.1960 | **13,402,775** | **53.611** |
| 1 | 15,979,392 | 1.1960 | 13,360,363 | 53.441 |
| 2 | 15,962,496 | 1.1960 | 13,346,295 | 53.385 |
| 3 | 15,962,496 | 1.1960 | 13,346,241 | 53.385 |

**The floor is 53.611 ms/token = 40.88 % of the step.**

**And the 1.5 % gap to the measured 54.408 ms is CHANNEL SKEW, not rate
headroom — the formula makes it so.** The floor is `beats / (beats per
streaming cycle)`, and the rate's denominator is that channel's own streaming
cycle count, so **the floor column above IS §6's streaming-cycles column,
digit for digit**, and each channel is at **100.0 % of its own floor by
construction**. The 1.5 % is the difference between the **union over four
channels** (54.408) and **chan 0 alone** (53.611) — i.e. the channels not
finishing in lockstep. The brief specified this formula and the number is
per contract; what it measures is skew, and §9.1 turns that into the
rebalanced 2.39-2.40x variant.

**This is THIS MEMORY MODEL'S floor, not the board's.** In the units the
throughput model uses, the testbench's weight path runs at **r = 1.0031
ui-cycles per 64 B beat = 19.14 GB/s/chan** (**D**) against the **r = 1.1037
= 17.40 GB/s/chan** that `docs/QWEN35_NEXT_FEASIBILITY.md` §4.2 SOLVED from
two silicon steps — **the TB's weight memory is 10.0 % faster than the rate
the board's own measurements imply** (**D**). `tb/seq_mem_file.sv` is a
file-backed model with no refresh, no bank conflict and no read/write
turnaround. That is a **reason** to expect this census's matvec term to be
optimistic against the board, and it is stated as a reason and not as a
correction to either number.

---

## 10. RECONCILIATION

### 10.0 IS THE MODEL'S SERIAL STRUCTURE RIGHT? — measured

`docs/QWEN35_NEXT_FEASIBILITY.md` §4.1 writes the step as a **serial sum** of
a matvec term, a mover term and a layer term, with a small overlap factor
`m`; §4.2 fits `m = 0.9117`. **The serialization had never been measured.**
The three terms, measured here like for like — weight streaming, mover WORK
(**not** `mv_busy`), layer compute (**D**):

```
   54.408  (weight streaming)
+  32.545  (mover work)
+  41.610  (layer compute)
= 128.563  ms  against a measured token of 131.138 ms   ->  98.04 %
```

**The three terms are EXACTLY DISJOINT, and that is stronger than "very
nearly".** Measured from the same CSV
(**T**, `evidence/qwen9b/bn/012_fix1_checks.log`,
`evidence/qwen9b/bn/013_fix1_checks_v2.log`):

| pair | cycles/token in which BOTH are active |
|---|---|
| layer compute AND weight streaming | **0** |
| layer compute AND mover work | **0** |
| weight streaming AND mover work | **0** (by construction — mover work is defined as `MOVER` with nothing streaming) |
| **union of the three** | **32,140,649** |
| **sum of the three** | **32,140,649** |

**Union equals sum to the cycle. The model's SERIAL sum is the right SHAPE
for this design, and that is now a MEASURED statement rather than an
assumption.** The remaining **643,784 cyc = 2.575 ms = 1.96 %** of the token
is **time in which NONE of the three is running** — the state-DMA lane alone,
the LDC/EMB bulk read, the record DDR and the sequencer's own residue — not
time in which two of them run at once. An earlier revision said the latter;
it was wrong and the truth is the stronger statement.

### 10.1 (a) Against the serial model, term by term

`docs/QWEN35_NEXT_FEASIBILITY.md` §4.4's **9B W4 g128** row (**S**):
matvec **58.95** + movers **32.66** + layer **47.00** = **138.61 ms/token**.

| term | model (**S**) | measured here (**T**/**D**) | delta |
|---|---|---|---|
| matvec | 58.95 | **53.611** (the busiest channel — see below) | **-9.1 %** |
| movers | 32.66 (= counted 35.82 x m 0.9117) | **34.154** (mover work + LDC + CSRWR, undiscounted) | not like-for-like — see below |
| layer | 47.00 | **41.610** (layer compute) | **-11.5 %** |
| the step | 138.61 | **131.138** measured | the model is **+5.7 %** high |

**THE MOVER ROW IS NOT LIKE-FOR-LIKE, AND AN EARLIER REVISION'S "CONFIRMED TO
0.35 %" IS WITHDRAWN.** `docs/QWEN35_NEXT_FEASIBILITY.md:945` writes the term
as `movers_counted * m`, and `docs/QWEN35_NEXT_FEASIBILITY.md:988` fits **`m = 0.9117`**, so §4.4's 9B cell is
**32.66 = 35.82 x 0.9117** (the 2B row checks it: 15.969 x 0.9117 = 14.56).
Two things were being compared that are not the same quantity:

* the model's **counted** term includes `LDC` (1.00 cyc/word + 595) and
  `CSRWR`/`CMD` (16.99/rec) work (`docs/QWEN35_NEXT_FEASIBILITY.md:958-963`),
  which this census's `MOVER` class **excludes** — here `LDC` is `SEQBULK` /
  `I_BULKRUN` at **1.290 ms** (§11.2) and `CSRWR` is **0.319 ms** (§11.1);
* and the model's figure is **discounted by `m`** while the measurement is
  not.

Like for like, against the model's **counted 35.82**: measured mover-engine
work **32.545** + `LDC` **1.290** + `CSRWR` **0.319** = **34.154 ms**, i.e.
**-4.7 %** (**D**). The old 0.35 % was two definitional differences of
opposite sign cancelling, and **"the strongest validation this campaign has
produced of any modelled term" is withdrawn** — the layer-lane agreement in
§10.2 is the stronger one.

**AND THIS CENSUS REFUTES `m`.** `m = 0.9117` means "8.8 % of counted mover
work overlaps engine time". Measured (**T**,
`evidence/qwen9b/bn/012_fix1_checks.log`): mover work while **any** matvec
engine is busy is **11,727 cyc/token**, which is **0.14 % of the 8,136,299
cycles of mover work** and **0.036 % of the token** — so the measured
**`m = 0.9986`, not 0.9117**. On this design, at this geometry, **mover work
does not hide under engine time at all**. That is a finding against the
model, and it is the one this row actually supports.

**The matvec row: compare against the BUSIEST CHANNEL, because that is what
the model's term is.** `docs/QWEN35_NEXT_FEASIBILITY.md` §4.1 says the
matvec term is the **busiest** channel's counted beats, "the max is used, not
the mean". Its measured counterpart is therefore chan 0's **53.611 ms**, not
the four-channel union 54.408. Re-expressing the model's 58.95 at the DDR
rate this testbench achieved — 58.95 x 1.0031 / 1.1037 = **53.577 ms**
(**D**, §9.2) — leaves the measured **53.611** just **+0.06 %** above it.
**So the whole of the matvec gap is the testbench's DDR rate, to within a
sixteenth of a per cent.**

**One caveat on that arithmetic, because the divisor carries a retraction.**
`docs/QWEN35_NEXT_FEASIBILITY.md:996-1003` RETRACTS its own `r = 1.1037` as
lying **outside** the re-anchored bracket `r <= 1.0851` by 1.7 %, and notes
that MOVER_NORM's point estimate moves 7 % on an 8 % change in a bubble
figure. So "the TB is 10.0 % faster than the board implies" rests on a number
its own source has qualified; at the re-anchored `r <= 1.0851` the same
sentence would read **8.2 %** and the rescaled model term 54.50 ms
(measured -1.6 %). **The direction is robust and the third digit is not.**

**The layer term's -11.5 % is the one the model already disowned.** §4.3 of
that study says its layer coefficient "is a fit intercept, not a measured
cost", and `evidence/qwen9b/g6/RD9_GATE.md` §10.4 instructs that the cycle
census is the better comparand. **It is; see (b).**

### 10.2 (b) Against the board's two lanes — and RD9 §10.2a's open delta

`evidence/qwen9b/g6/RD9_GATE.md` §10.2 (**S**): `L_LCYC` **41.588
ms/token**, `L_SDMA_CYC` **5.125 ms/token**, the two together 34.1 % of the
step, **65.9 % of device time in NEITHER lane**.

| lane | board (**S**) | this census (**T**/**D**) | delta |
|---|---|---|---|
| compute, `busy_cmp` | **41.588** | **41.610** | **+0.053 %** |
| state-DMA, `busy_dma` | **5.125** | **5.172** | **+0.92 %** |
| in neither lane | **65.9 %** | **66.86 %** (87.673 ms/token) | +0.96 pp |

**WHAT THAT FIRST ROW ESTABLISHES — AND WHAT IT DOES NOT.** RD9 §10.2a
compared the board's 41.588 against the chip TB's own layer census,
**46.161 ms/token**, found the board **9.9 % below** it, listed two
candidates, and said of the first — "Different instruments, not different
silicon" — that **"no board rung can measure it"**.

**ESTABLISHED**: the board's compute lane is **reproduced by the chip TB on
the same stream to 0.053 %** (41.610 vs 41.588). So the 9.9 % is a property
of RD9's **comparand**, not of the silicon: there is nothing anomalous about
the board's layer lane, and any future round should stop looking for one.
Stated with its caveat — a testbench figure against a silicon figure across
two different memory models, so **0.053 % is closer than either
measurement's own uncertainty justifies calling exact**.

**REFUTED**: the mechanism. An earlier revision of this document, and the
message of commit `c995591`, said "the draining instrument accounts for the
WHOLE delta". **The campaign's own A/B says otherwise.**
`evidence/qwen9b/s4/S4_REPLAY.md` §5.5.4 ran the layer census with the drain
REMOVED (`NODRAIN=1`, the sequencer's back-pressure rule instead) and got
`LCYC` = **11,539,426 cyc/token = 46.158 ms**, identical at `LAT = 8` and
`LAT = 40`, against **45.674** for the draining run — **the drain is worth
0.484 ms = 1.1 %, and removing it moves the census AWAY from 41.610, not
towards it** (**S**). Draining is not the mechanism.

**ATTRIBUTED, NOT PROVEN — and here is the candidate that fits.** The two
instruments **do not run the same command list**. The layer census replays
the `.txt` host-driven script and the chip census replays the `.e4` sequencer
stream — the two halves of the dual-driven equivalence, which agree at the
model level but decompose into different commands:

| per token | layer census, `.txt` (**S**, `evidence/qwen9b/s4/census_s4shipped.txt`) | this census, `.e4` (**T**) |
|---|---|---|
| layer commands | **9,429** | **8,821** |
| `ALU` | **6,219** | **4,843** |
| `VN` | **1,761** | **2,529** |
| everything else | identical | identical |

**1,376 fewer `ALU` and 768 more `VN` per token** (**T**,
`evidence/qwen9b/bn/015_fix2_lane_vs_window.log` for the `.e4` side). Sized
two ways, and they **bracket** the 4.064 ms between the draining census
(45.674) and this one (41.610):

| estimate | arithmetic | vs the 4.064 ms gap |
|---|---|---|
| at the **layer census's own per-command means** (`ALU` 910 cyc, `VN` 620 cyc) | -1,376 x 910 + 768 x 620 = **-776,000 cyc = -3.104 ms** | **76 %** |
| at **this census's own per-opcode LANE totals** (`ALU` 17.150 vs 22.646, `VN` 5.317 vs 4.371) | (-5.496) + (+0.946) = **-4.550 ms** | **112 %** |

**The second one OVER-explains the gap, and that is the finding.** The
schedule difference is not a partial explanation with a residual left over —
it is large enough to account for the whole gap **and more**, which means
**something of the opposite sign is also present in the comparison and this
census did not measure it**. **No residual figure is quoted here, because
"76 %" and "112 %" do not bound one.** What is settled is that the gap lives
in the comparand and that the command-list difference is the dominant term in
it; the mechanism is **not** settled.

**A note on which per-opcode column is comparable.** `evidence/qwen9b/bn/015_fix2_lane_vs_window.log`
prints two per-opcode columns and only one of them may be set beside S4
§5.3.2: the **LANE** column (the compute lane's own `busy_cmp` cycles inside
a record's window), which sums over all opcodes to **41.610 ms** — this
census's `L_CMP` exactly. The other column is the **record window** itself,
dispatch to the next record, which includes the sequencer's poll and fetch on
either side and sums to the whole 131.138 ms token. An earlier revision of
this section quoted the window column (`ALU` 17.671, `VN` 5.560) against S4's
lane table; the lane column (17.150, 5.317) is the like-for-like one and is
what the table above uses.

**One thing that IS confirmed across the two instruments**: this census
measures **120,568 cyc/token** of `busy_cmp` inside `SLD` records (**T**,
`evidence/qwen9b/bn/015_fix2_lane_vs_window.log`) against S4 §5.5.4's
non-draining **F2 queue-full hold of 120,953 cyc/token over 7 `SLD` per
token** — **0.32 % apart** (**D**). So the holds are charged on
both sides and on the board's side too, exactly as RD9 §10.2a(a) requires.

**The state-DMA lane is confirmed three ways**: S4's modelled 5.133 at
LAT 8, the board's measured 5.125, and this census's 5.172 — a spread of
**0.92 %** across a model, a silicon counter and a chip-TB census.

**The 65.9 % is confirmed and its CONTENT is now known.** RD9 said the rest
"is the sequencer's own fetch/decode and its 106,244 `CSRWR` records, plus
the matvec engines". Measured (§11): the sequencer's own overhead is
**0.94 %** of the token and the `CSRWR` records cost **0.24 %**. **The
66.86 % is the weight path and the movers, essentially all of it** —
54.408 ms of streaming and 32.545 ms of mover work against 1.227 ms of
sequencer.

---

## 11. WHERE THE SEQUENCER'S OWN TIME GOES

### 11.1 By RECORD TYPE — the `FENCE` is the largest single item

**T**/**D**, tokens 1..6. A record's window runs from the cycle the issue FSM
latched it to the cycle before the next is latched, so these rows PARTITION
the token.

| record | records/token | cyc/token | ms/token | % of token | cyc/record |
|---|---|---|---|---|---|
| **`FENCE`** | **343.0** | **13,598,440** | **54.394** | **41.48 %** | **39,645.6** |
| `CMD` | 8,821.0 | 10,628,887 | 42.516 | 32.42 % | 1,205.0 |
| `MOVX` | 996.0 | 5,260,768 | 21.043 | 16.05 % | 5,281.9 |
| `MOVY` | 1,370.0 | 2,847,256 | 11.389 | 8.68 % | 2,078.3 |
| `LDC` | 161.0 | 320,734 | 1.283 | 0.98 % | 1,992.1 |
| `CSRWR` | **26,551.5** | 79,655 | **0.319** | **0.24 %** | **3.0** |
| `MVGO` | 1,370.0 | 43,928 | 0.176 | 0.13 % | 32.1 |
| `EMB` | 1.0 | 4,699 | 0.019 | 0.01 % | 4,699.0 |
| `XOP` | 9.0 | 36 | 0.000 | 0.00 % | 4.0 |
| `AMAXL` | 1.0 | 17 | 0.000 | 0.00 % | 17.0 |
| `JMP` | 0.5 | 13 | 0.000 | 0.00 % | 26.7 |

**343 `FENCE` records cost 41.48 % of the token at 39,646 cycles each** — the
largest single record type, with `CMD` second at 32.42 %.

**54.394 ms of `FENCE` against 54.408 ms of weight streaming** (**D**, 0.03 %
apart) — and **that equality is STRUCTURAL, not a coincidence the census
discovered**. `MVGO` returns in 32.1 cycles and the following `FENCE` blocks
until the drain completes, so the `FENCE` window **contains** the streaming
by construction (`rtl/seq_unit.sv:1099-1102`; §11.3's `mv_op` FENCE total is
13,597,068 cyc against 13,597,777 cyc of `MOVER`-while-streaming). What the
census measures is the **size** of that window, and where it sits: the
`FENCE` is where the serialization lives in the ISA, and it is 41.48 % of the
step.

**`MVGO` costs 32.1 cycles.** Issuing the doorbell is free; **waiting for it
at the `FENCE` is 39,646**.

**`CSRWR` is the record type this design executes most — 26,551 per token —
and it costs 3.0 cycles each and 0.24 % of the step.** RD9 §10.2 named
"its 106,244 `CSRWR` records" as a candidate for the 65.9 %; measured, they
are not.

### 11.2 By ISSUE-FSM STATE

**T**, the run's own per-token histogram over `rtl/seq_unit.sv:844-853`'s
`istate_e`:

| state | cyc/token | ms/token | % of token | what it is |
|---|---|---|---|---|
| `I_MOVER` | 21,742,234 | 86.969 | **66.32 %** | handed to `seq_movers` — `MOVX`/`MOVY`/`MVGO`/`FENCE` |
| `I_CMDPOLLW` | 9,651,254 | 38.605 | **29.44 %** | waiting on the layer `STATUS` read to return |
| `I_CMDPOLL` | 804,271 | 3.217 | 2.45 % | issuing the `STATUS` poll |
| `I_BULKRUN` | 322,517 | 1.290 | 0.98 % | `LDC`/`EMB` bulk streaming |
| `I_CMDDRAIN` | 123,494 | 0.494 | 0.38 % | draining the `CMD` write before the poll |
| `I_FETCH` | 39,636 | 0.159 | 0.12 % | fetching the next record |
| `I_EXEC` | 39,624 | 0.158 | 0.12 % | decoding it |
| `I_WR` | 26,551 | 0.106 | 0.08 % | the `CSRWR` AXI-Lite write |
| `I_XRFSELD` / `I_XRFRDW` | 10,864 / 10,860 | 0.043 / 0.043 | 0.03 % each | the XRF mirror refresh |
| everything else | < 9,000 | < 0.035 | < 0.03 % | — |

**Fetch and decode together are 0.24 % of the token, and the fetch-empty
stall is 0 to 36 cycles per token** (§3) — on a 158,536-record stream with a
prefetch FIFO. **The record path is not a bottleneck and there is nothing
there to win.**

**And the stall figure disagrees with the run's own printed line by exactly
2x, which is the PRINT and not the census.** The logs say
`fetch-empty stall cycles 48` for the launch where the census totals **96**
(and 30 against 60 on the smoke). `tb/tb_seq_chip.sv:1140` prints CSR 0x3C's
`v[31:1]`, and `rtl/seq_unit.sv:1512` packs that CSR as
`{perf_fst[31:1], xrf_ovf}` — so the printed number is **`perf_fst / 2`**.
The census counts `rtl/seq_unit.sv:981`'s condition directly and is right;
the print reads half. Both the smoke and the full run show the same exact
factor of two, which is what identifies it as a packing shift rather than a
counting difference. **Neither number is large enough to matter here** — 96
cycles is 0.0003 % of a token — and this note exists so the next reader does
not have to find it again.

### 11.3 The mover, by operation

**T**, the run's own `mv_op` histogram (`rtl/seq_unit.sv:1070-1102`):

| `mv_op` | cyc/token | ms/token | % of token |
|---|---|---|---|
| **`FENCE` (drain wait)** | **13,597,068** | **54.388** | **41.47 %** |
| `MOVX` | 5,256,784 | 21.027 | 16.03 % |
| `MOVY` | 2,841,776 | 11.367 | 8.67 % |
| `MVGO` | 38,448 | 0.154 | 0.12 % |

(The three work rows sum to **32.548 ms**; §9.1 and §10 quote **32.545**,
the same quantity derived from the per-cycle signature histogram instead of
from this histogram. The two agree to **0.01 %**, and the difference is the
709 cycles in which the mover was busy with a work op while a channel
happened to be streaming.)

**This is the split that makes the `MOVER` class readable.** `mv_busy` is
86.936 ms/token, but **54.388 of it is a WAIT** and only **32.545 ms is work**
— and it is that 32.545 that belongs beside
`docs/QWEN35_NEXT_FEASIBILITY.md` §4.4's 32.66 (§10.1), not the 86.936.

---

## 12. WHAT THIS CENSUS DOES **NOT** ESTABLISH

1. **It is not a board measurement, and none of its numbers replaces one.**
   The memory models are `WLAT = 40` / `DDRLAT = 32`
   (`tb/tb_seq_chip.sv:68-69`); the same testbench runs this stream 4.6 %
   FASTER end to end than the silicon does
   (`evidence/qwen9b/g6/RD9_GATE.md` §10.4). Where RD9 has a board number —
   `L_LCYC`, `L_SDMA_CYC`, the 65.9 % — **the board number stands and this
   one is beside it, not instead of it.**
2. **It does not PROVE the mechanism behind RD9 §10.2a's 9.9 %.** What it
   establishes is narrower and is stated the same way in §0, §10.2 and §13:
   the board's compute lane is **reproduced by the chip TB on the same stream
   to 0.053 %**, so the delta belongs to RD9's comparand and not to the
   silicon. It **refutes** the draining explanation (S4 §5.5.4's own
   `NODRAIN=1` A/B moves `LCYC` by 0.484 ms, the wrong way) and **attributes**
   the gap to the `.txt`-vs-`.e4` command-schedule difference, sized at
   **76 %** one way and **112 %** the other — i.e. the candidate **brackets**
   the gap and on the lane-correct numbers **over-explains** it, so a term of
   opposite sign is present and unmeasured. **No residual figure is quoted,
   because those two estimates do not bound one**; this census does not
   measure the board; and "ATTRIBUTED, NOT PROVEN" is the phrase every section
   uses.
3. **It measures ONE seed at ONE prompt length, six decode steps.** The
   one-seed choice is justified for TIME by S4 §4.2's four cycle counts
   agreeing to 0.00043 %, and for nothing else. **Prefill, first-token
   latency, chat-turn time, long context and MULTI-SEQUENCE DECODE are not
   measured here** — this stream is six decode steps of ONE sequence at a
   short T, and the KV term grows with T
   (`evidence/qwen9b/g6/RD9_GATE.md` §8.7). §13 #4 measures the batching
   PRIZE (the weight stream, which is invariant to the number of sequences);
   its SCALING is arithmetic over a premise a single-stream census cannot
   observe, and #4 says so.
4. **The overlap bound is a BOUND, not a design.** It assumes away every
   data dependency, every shared bus and every arbitration cost. No RTL
   change is claimed to reach it, and the census does not say what a real
   prefetch would cost in BRAM, in scratch pressure or in timing closure.
5. **The DDR-bound floor is this MEMORY MODEL'S floor.** It is computed from
   the beats/cycle the run itself achieved through `tb/seq_mem_file.sv`,
   which is a file-backed model and not a DDR4 controller. A board floor
   needs the board.
6. **The `MOVER` class is `mv_busy`, not mover WORK.** `mv_busy` is high for
   the whole of a `FENCE` drain as well as for `MOVX`/`MVGO`/`MOVY`, so it is
   NOT `docs/QWEN35_NEXT_FEASIBILITY.md` §4.1's counted-mover-work term. §10
   splits the two and compares only like with like.
7. **A signature is a co-occurrence, not a causal claim.** That the layer
   lane is idle while the weight path streams says the two do not overlap in
   THIS schedule; it does not say that they could, and it does not identify
   which side is waiting on the other. The `FENCE` accounting in §11 is the
   closest this census gets to that, and it is an accounting, not a proof.
8. **The two halves of the dual-driven equivalence are NOT the same command
   list**, and this census only measured that they differ and by how much
   (§10.2). It did not establish WHY the `.seq` emitter produces 1,376 fewer
   `ALU` and 768 more `VN` per token than the `.txt` one, nor that the
   difference is benign beyond `ref/seq_model --gate`'s existing model-level
   equivalence proof. **That is a loose end this census opened and did not
   close.**
9. **Per-channel balance here is the SCHEDULE's balance on this stream**, not
   the static row split of `evidence/qwen9b/g6/RD9_GATE.md` §10.3 and not the
   board's per-token per-channel spread, which §10.3 states is **not
   measurable** with the counters this netlist has.

---

## 13. THE BOTTLENECKS, RANKED BY MEASURED IDLE/SERIAL TIME

**The rule this list is written under:** every entry is ranked on a
**MEASURED** idle or serial time from this census, and **no lever is
recommended on a modelled number where a measured one exists**. Where the
only number available is modelled, the entry says so and is ranked below
every measured one.

### #1 — The weight path is IDLE for 58.51 % of the token. **76.7 ms/token.**

**Measured**: no channel is streaming for **19,182,548 cyc/token = 76.730
ms** (§6). The two states that fill it are `{layer}` alone (38.157 ms,
29.10 %) and `{mover, burst fabric}` (30.881 ms, 23.55 %) — §5 rows 2 and 3.
Meanwhile the path is 98.68 % utilised **inside** its windows and at
**r = 1.0031**, the engine's hard floor (§6, §9.2).

**Lever: sequencer-level overlap** — prefetch the next `MVGO`'s weights
while the current layer command and the current mover traffic run, instead
of fencing between them.

**Ceiling, MEASURED**: §9.1(i-b). Union 129.911 ms, busiest resource
54.408 ms, so a perfect overlap saves **at most 75.503 ms/token = 57.58 %**
and the token cannot go below **55.634 ms** — **at most 2.36x**. **Overlap
alone cannot beat 2.36x on this stream**; overlap PLUS evening the four
channels is bound by a single channel instead and reaches **2.39-2.40x**
(§9.1), which is the honest upper end.

**What the census does NOT say**: which side is waiting on the other at any
given cycle, or what a prefetch would cost in scratch pressure, BRAM or
timing closure (§12 items 7 and 4).

### #2 — The `FENCE` is where that idle time is spent. **54.394 ms/token, 343 records.**

**Measured**: 343 `FENCE` records per token at **39,645.6 cycles each** =
**41.48 % of the token** (§11.1), and `FENCE` time equals weight-streaming
time to **0.03 %** (54.394 against 54.408). The issue FSM sits in `I_MOVER`
for 66.32 % of the step (§11.2) and the mover's own `mv_op` histogram says
41.47 % of that is the drain wait (§11.3).

This is the same time as #1, counted from the ISA side rather than the
resource side — it is listed separately because **it names where a change
would land**: the `FENCE`/`MVGO` handshake in `rtl/seq_movers.sv` and the
`no-wait MVGO` path the ISA already has, not the layer and not the memory.

**Ceiling**: the same 2.36x (2.39-2.40x with the channels evened); these are
one bottleneck seen twice, and §11.1 notes that the `FENCE`-equals-streaming
identity is structural rather than a measured coincidence.

### #3 — Layer compute, and inside it the ALU. **41.610 ms/token, 31.73 %.**

**Measured here**: `L_CMP` = **41.610 ms/token**, and it is **0.053 % from
the board's own `L_LCYC`** (§10.2) — so this term is now measured on both
sides and they agree. **Read that with §10.2's status line**: RD9 §10.2a's
9.9 % is **ATTRIBUTED, NOT PROVEN** — the delta belongs to RD9's comparand
rather than to the silicon, the draining explanation is refuted, and the
command-schedule candidate **brackets** the gap (76 % one way, 112 % the
other) rather than leaving a residual. **None of that changes this rank**,
because the rank rests on 41.610 itself, which is measured on both sides.

**Measured elsewhere, cited not re-derived**: `evidence/qwen9b/s4/S4_REPLAY.md`
§5.3.2's per-opcode census of the same stream (**S**) splits that lane as
**`ALU` 22.646 ms (49.58 %)**, **`DNST` 9.087 ms (19.90 %)**, `VN` 4.371,
`CONV` 3.933, `VNW` 3.244, `ATTN` 1.005. **This census does not re-measure
the split** — it measures the lane total — and the two agree on the total to
within S4's own draining/dispatching difference (§10.2).

**One caution on the ALU figure.** S4 §5.3.2's split is measured on the
`.txt` schedule, which issues **6,219 `ALU` per token** where the `.e4`
stream this census ran issues **4,843** (§10.2) — so the 49.58 % share is the
host-driven schedule's, not this stream's. On this stream `ALU` occupies the
compute lane for **17.150 ms of its 41.610 ms = 41.2 %** (**T**,
`evidence/qwen9b/bn/015_fix2_lane_vs_window.log`, the LANE column). **`ALU`
is still the largest item in the lane either way**; the number to quote for
the shipped sequencer path is **17.150 ms**, not 22.646 — and not 17.671,
which is that opcode's record-window total rather than its lane cycles.

**Levers**: the **ALU** (41.2 % of the lane) and the **DN head loop**
(`DNST`, 768 commands/token at S4 §5.3.4's 2,958 cycles each). The census adds one
thing the per-opcode census could not see: **the DeltaNet layers are
71.66 % of the whole token at 3.916 ms each, 24 of them, against a GQA
layer's 3.051** (§7) — so a DN-side win is worth 3.85x a GQA-side win of
the same relative size (**D**, 93.972 / 24.407).

**Ceiling**: bounded by #1. Even a layer lane of ZERO cost cannot take the
token below the 55.634 ms floor, and at 41.610 ms the layer is **not** the
busiest resource — the weight path is. **Fix #1 first; #3 only becomes the
binding term after it.**

### #4 — Amortising the weight stream: batched prefill / multi-sequence decode. **54.408 ms/token.**

**Measured**: the stream is **3,902.24 MiB/token** across four channels
(§6), reproducing RD9 §10.3's static split exactly, and it costs
**54.408 ms/token** at the model's hard floor with **no rate headroom left**
(§9.2). The weight bytes are **independent of how many tokens a pass
decodes**, so B sequences per weight pass divide this term by B.

**Ceiling, from this census's own numbers** (**D**): with the streaming term
divided by B and everything else per token unchanged, the time per token is
`(131.138 - 54.408) + 54.408/B = 76.730 + 54.408/B` ms — **103.934 ms at
B = 2 (1.26x)**, **90.332 at B = 4 (1.45x)**, and **76.730 ms at large B
(1.71x)**, before any overlap. Combined with #1 the two are **not** additive:
overlap hides the stream under compute, batching shrinks it, and whichever
is done first takes most of the win.

**Ranked below #1 because the levers overlap, because the enabling work does
not exist, and because the SCALING is not measured here.**
`evidence/qwen9b/g6/RD9_GATE.md` §16 item 5 records that **there is no
batched prefill in this design** and that prefill runs at decode rate. And
**this census watched ONE sequence**: the prize (the weight stream, which is
invariant to how many sequences a pass decodes) is measured; the `54.408/B`
scaling is arithmetic over a premise a single-stream census **cannot
observe** — it does not see what batching would cost in scratch, in state
traffic or in the layer lane. §12 item 3 carries the same caveat.

### #5 — The burst fabric. **33.337 ms/token, 25.42 %.**

**Measured**: busy for a quarter of the token, carrying the `MOVX`/`MOVY`
data streams. It is **never the binding resource** — it is third, behind the
weight path and the layer — and it is already concurrent with the mover work
it serves (§5 row 3 is `{mover, burst fabric}`). Listed so the ranking is
complete, with **no lever recommended**: nothing in this census shows it
causing a wait.

### #6 — The state-DMA lane. **5.172 ms/token, 3.94 %. Nothing to win.**

**Measured**: 5.172 ms/token, and §5 rows 4 and 5 show it running
**concurrently with the layer lane** (`{layer, sdma, smemR}` and
`{layer, sdma, smemW}`). The lane is active with **no other class at all**
for just **3,435 cyc/token = 0.014 ms** (**T**,
`evidence/qwen9b/bn/012_fix1_checks.log`) — so the spill is hidden to within
a hundredth of a millisecond, which is a stronger statement than "overlapped". S4's spill is hidden, exactly as
`evidence/qwen9b/s4/S4_REPLAY.md` §5.3.3 argued it would be and
`evidence/qwen9b/g6/RD9_GATE.md` §10.2 measured on silicon. **No lever.**

### #7 — The sequencer itself. **1.227 ms/token, 0.94 %. NOT a bottleneck.**

**Measured**: the residue with no engine, no DMA and no bus active is
**0.94 %** of the token (§4); `CSRWR` records cost **0.24 %** (§11.1);
fetch and decode together **0.24 %**; the fetch-empty stall is **0 to 36
cycles per token** (§3, §11.2). **The speculation in RD9 §10.2 that the
sequencer's fetch/decode and its 106,244 `CSRWR` records were part of the
65.9 % is WITHDRAWN by measurement.** No lever, and the entry exists to
close the question rather than to open one.
