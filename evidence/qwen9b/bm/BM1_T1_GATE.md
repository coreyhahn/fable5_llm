# BM1-T1 — the board idle counters in RTL, proven on the chip testbench

**Task BM1-T1** of the BM1 plan (brief:
`.superpowers/sdd/2026-09-24-overlap/task-BM1-T1-brief.md`, not committed),
implementing `docs/superpowers/specs/2026-09-24-board-idle-counters-design.md`
§1–§3 with the user's rulings on its §8 (the recommended options: D1a wire the
four matvec busy bits into `seq_0`, D2a no layer wire, D3a no per-token latch,
D4a no `ui_clk` accumulators, D5 no "all four busy" counter) plus OV1's
request that MOVX and MOVY work be counted separately.

**VERDICT: PASS.** Every counter equals the census's total for
`model_9b_s1` exactly, 0 cycles; the cycle count and the tokens are unchanged
on all four seeds with the readout plusarg off AND on; the G1 run's whole
`SEQ_TIMELINE` block and its CSV body are byte-identical to the census's.
**No Vivado build, no timing, no board** — those are T3 and T4 (§6).

One comparand in the spec is wrong and is reported, not absorbed (§3.3): the
spec's C7 row compares `BM_MVWORK_ANY` with the census's "I-2" figure, which
is a different quantity. The two are reconciled exactly.

---

## 0. How to read every number below

* **T** = transcribed from a named log in `evidence/qwen9b/bm/`. **D** =
  derived, arithmetic shown. **S** = stated by a cited source. **E** =
  established by an exact pass/fail check that a named log prints (the
  testbench `$fatal`s on any difference, and the runner fails the rung).
* **Every numeric step ran ON SNOKE** through
  `evidence/qwen9b/bm/bm_run.sh` (a copy of
  `evidence/qwen_next/nvfp4/nvfp4_run.sh` retargeted here, committed before
  its first use), whose header records the host, the tree, the command and
  the interpreter and whose footer records `=== rc` and `=== end`. Nothing
  numeric ran on darthplagueis. One empty `python3` heredoc (0 bytes of
  input, a botched text-edit fallback) was invoked there; it computed
  nothing and is disclosed in the task ledger.
* **`+dirty` in a log's tree stamp names only Task SV1's untracked files**
  under `evidence/qwen9b/ov/` (SV1 ran concurrently on disjoint files); each
  log's `=== dirty:` lines list them. The wrapper excludes untracked files
  under `evidence/qwen9b/bn/` (the census's uncommitted CSVs) and
  `evidence/qwen9b/bm/` (this task's in-flight logs); every script there was
  committed before its first use.
* **"The census"** is `evidence/qwen9b/bn/BN_CENSUS.md`; its run is
  `evidence/qwen9b/bn/003_timeline_model_9b_s1.log`.

---

## 1. What was built

| piece | where | what |
|---|---|---|
| counters | `rtl/seq_unit.sv:1356-1464` | 12 counters + `BM_IDENT`, the alignment pipeline, the read side |
| CSR decode | `rtl/seq_unit.sv:1639-1640` | 0x100..0x1FC → the block; everything else unchanged |
| new input | `rtl/seq_unit.sv:268-272` | the 4-bit `mv_busy_bm` input |
| header map | `rtl/seq_unit.sv:56-60` | the block in the module's CSR table |
| source flop | `rtl/matvec_chan.sv:182-187`, `rtl/matvec_chan.sv:246-249` | one flop of `cdc_sync_stat[0]` → new output `mv_busy_bm` |
| IPI wrappers | `rtl/matvec_chan_ipi.v:117-120`, `rtl/seq_unit_ipi.v:183-190` | the port on each wrapper (four scalar pins on `seq_0`) |
| BD wiring | `synth/scripts/create_project.tcl:352-362` | mvchan_c's `mv_busy_bm` → seq_0's pin c |
| ISA addendum | `docs/SEQ_ISA.md:1331-1395` | section B16, v2.2 |
| host read | `sw/seq_run.py:141-168`, `sw/seq_run.py:1328-1354` | `seq_perf()` → `seq_bm()`, feature-detected |
| TB readout | `tb/tb_seq_chip.sv:630-653`, `tb/tb_seq_chip.sv:1212-1405` | `+bm` / `+bm_expect=`; the TB's own negedge sampler |
| TB wiring | `tb/tb_seq_chip.sv:174-176` | the four nets, as the BD wires them |
| build | `tb/Makefile:1771-1809` | `tb_seq_chip_9b_bm1_build` (`obj_dir_seq_chip_bm1`), `lint_bm1` |
| runner | `evidence/qwen9b/bm/run_bm1.sh` | a copy of `evidence/qwen9b/bn/run_bn_timeline.sh`, modes control/bm/bmtl |

### 1.1 The wiring is a script edit, not a block-design session

The block design is assembled entirely by `synth/scripts/create_project.tcl`
(the `mvchan_$i` cells at `synth/scripts/create_project.tcl:239`, `seq_0` at
`synth/scripts/create_project.tcl:332`). The four nets are one `for` loop of
`connect_bd_net` calls beside the existing `seq_0/xrf_sb_*` tie-offs
(`synth/scripts/create_project.tcl:360-362`), the same kind of wiring the spec
named (spec §1.1). No Vivado session is needed to make the edit; whether the
project script accepts it is proven only when T3 runs it (§6).

### 1.2 Every counter input is on aclk — no CDC

* `seq_0` and every `mvchan_c/aclk` are on `xdma_0/axi_aclk`
  (`synth/scripts/create_project.tcl:246`, `synth/scripts/create_project.tcl:333`).
* The source flop is clocked by `aclk` and samples `cdc_sync_stat[0]`, the
  output of the channel's EXISTING 2-FF synchroniser
  (`rtl/matvec_chan.sv:241-245`), which is the bit the channel's own STATUS
  read returns (`rtl/matvec_chan.sv:368`). The new flop is not matched by any
  existing false path (`synth/constraints/fable5_cdc.xdc` names only
  `cdc_meta_*`, `csr_static_*`, `perf_cycles`/`perf_beats` and the CSR's
  `calib_meta`).
* Everything else the counters read (`busy_r`, `mv_busy`, `mv_op`, `ist`,
  the decoded record) is `seq_unit`-internal, `aclk`.

**No clock, no CDC structure and no constraint was added.** The STOP
condition "a counter input not on aclk" did not arise.

### 1.3 The counters, their addresses, and the alignment

Map (`docs/SEQ_ISA.md:1343-1358`): 0x100 `BM_IDENT` = 0xFAB1B301, 0x104
`BM_MVANY`, 0x108..0x114 `BM_MV0..3`, 0x118 `BM_FENCE`, 0x11C `BM_MVWORK`,
0x120 `BM_MVWORK_ANY`, 0x124 `BM_IMOVER`, 0x128 `BM_STEPS`, 0x12C reserved
(reads 0), **0x130 `BM_MOVX`, 0x134 `BM_MOVY`** (OV1's split), 0x138..0x1FC
reserved (read 0). Everything in the spec's table sits at the spec's address.
The two added counters take the first words of the range the spec reserved
"for BM1/OV1 additions" (0x130..0x1FC); 0x12C, which the spec lists
separately as reserved, was left reserved. That is a reading of the spec's
adoption rule ("the next free word of the reserved block"), stated here so a
reviewer can overrule it.

Conditions (spec §1.2), with B = `busy_r`, M[c] = the aligned engine-busy
bit, ANY = the OR of the four, MB = `mv_busy`, and the mover op decoded as
FENCE (3), MOVX (0), MOVY (2):
C0 `BM_MVANY` = B and ANY; C1–C4 `BM_MVc` = B and M[c]; C5 `BM_FENCE` = B and
MB and FENCE; C6 `BM_MVWORK` = B and MB and not FENCE; C7 `BM_MVWORK_ANY` = C6's
condition and ANY; C8 `BM_IMOVER` = B and the issue FSM in `I_MOVER`; C9
`BM_STEPS` = an `OP_EMB` record dispatched (issue FSM in `I_EXEC`, record
valid); `BM_MOVX` = B and MB and MOVX; `BM_MOVY` = B and MB and MOVY.

Clear at the START that clears `PERF_*` (the same condition,
`rtl/seq_unit.sv:1404`); counted while the delayed B; frozen at HALT; no write
decode. **Alignment:** the engine bit passes the source flop in `matvec_chan`
and two flops in `seq_unit` (`rtl/seq_unit.sv:1422-1423`); the seven local
terms are packed into one vector (`rtl/seq_unit.sv:1385-1392`) and delayed by
the same three flops (`rtl/seq_unit.sv:1419-1421`), so every counter
evaluates one cycle's values. §3 shows that this reproduces the census's
negedge sampler cycle for cycle.

---

## 2. Test-first: the check was written and seen to FAIL before the RTL

| step | log | result |
|---|---|---|
| expected values, from the census | `evidence/qwen9b/bm/n02_expect_model_9b_s1.log`, `evidence/qwen9b/bm/n03_expect_tok9b_s1.log` | the sums of `003`'s (and the smoke `006`'s) `SEQ_TIMELINE` lines, and a recount of the census CSV — **its sha256 checked against the committed hash first** (`evidence/qwen9b/bm/n02_expect_model_9b_s1.log:14-16`) |
| TB readout committed with NO counter RTL | commit `0110ca5` | — |
| RED build | `evidence/qwen9b/bm/n04_build_bm1_RED.log` | -Wall clean, `rc 0` (`evidence/qwen9b/bm/n04_build_bm1_RED.log:54`) |
| **RED run** | `evidence/qwen9b/bm/n05_RED_smoke_bm_tok9b.log` | every BM register reads 0xDEADC0DE (3,735,929,054), **28 checks differ, FAIL** (`evidence/qwen9b/bm/n05_RED_smoke_bm_tok9b.log:51`, `evidence/qwen9b/bm/n05_RED_smoke_bm_tok9b.log:88`) — while the TB's own sampler already matched the census on `PERF_CYC`, `L_LCYC` and the census's I-2 (`evidence/qwen9b/bm/n05_RED_smoke_bm_tok9b.log:74`, `evidence/qwen9b/bm/n05_RED_smoke_bm_tok9b.log:85-87`) |
| RTL committed | commits `946fe3d` (RTL + BD), `3ef556d` (TB nets) | — |
| lint | `evidence/qwen9b/bm/n06_lint_bm1.log` | `LINT_BM1 OK` (`evidence/qwen9b/bm/n06_lint_bm1.log:34`) |
| GREEN build | `evidence/qwen9b/bm/n07_build_bm1_GREEN.log` | `rc 0` (`evidence/qwen9b/bm/n07_build_bm1_GREEN.log:62`) |
| **GREEN run** (smoke) | `evidence/qwen9b/bm/n08_GREEN_smoke_bm_tok9b.log` | every counter = the TB sampler = the census, cycles 3,893,746 unchanged (`evidence/qwen9b/bm/n08_GREEN_smoke_bm_tok9b.log:36`, `evidence/qwen9b/bm/n08_GREEN_smoke_bm_tok9b.log:78`) |
| smoke control | `evidence/qwen9b/bm/n09_smoke_control_tok9b.log` | no BM1 line, cycles unchanged (`evidence/qwen9b/bm/n09_smoke_control_tok9b.log:34`, `evidence/qwen9b/bm/n09_smoke_control_tok9b.log:38`) |

**Three references per counter, not one.** The testbench checks each RTL
register against (a) its OWN negedge sampler — the census's method, the same
DUT signals, re-implemented in `tb/tb_seq_chip.sv:1274-1299` — exactly; and,
with `+bm_expect=`, (b) the census's integer totals out of `003`; the G1
compare script then checks (c) a recount over the G1 run's own CSV (§3.3).

---

## 3. The acceptance gate (spec §3.3), on snoke

One binary for every rung: `tb/obj_dir_seq_chip_bm1/tb_seq_chip_9b_bm1`,
built from `3ef556d` (`evidence/qwen9b/bm/n07_build_bm1_GREEN.log`), sha256
`72d7494e…` (`evidence/qwen9b/bm/n19_G1_compare.log:68`), NMV = 4 and WIMGPC = 1
as the census. Nine runs in parallel, 8,487–8,869 s each (**T**, the
`=== wall` lines).

### 3.1 A — zero perturbation, exact

| seed | plusarg | log | cycles | tokens | vs `evidence/qwen9b/s4/S4_REPLAY.md` §4.2 |
|---|---|---|---|---|---|
| s1 | `+bm +timeline` (G1) | `evidence/qwen9b/bm/n10_G1_bmtl_model_9b_s1.log:38-42` | 196,706,821 | `[2614,314,279,369,11751,13]` | **IDENTICAL** |
| s1 | `+bm` | `evidence/qwen9b/bm/n11_G2_bm_model_9b_s1.log:32-36` | 196,706,821 | same | **IDENTICAL** |
| s2 | `+bm` | `evidence/qwen9b/bm/n12_G2_bm_model_9b_s2.log:31-35` | 196,707,670 | `[279,264,854,11,303,264]` | **IDENTICAL** |
| s3 | `+bm` | `evidence/qwen9b/bm/n13_G2_bm_model_9b_s3.log:31-35` | 196,707,670 | `[313,430,2510,198,1445,27180]` | **IDENTICAL** |
| s4 | `+bm` | `evidence/qwen9b/bm/n14_G2_bm_model_9b_s4.log:31-35` | 196,706,833 | `[11,0,271,803,369,498]` | **IDENTICAL** |
| s1..s4 | none (control) | `evidence/qwen9b/bm/n15_G2_control_model_9b_s1.log:30-34` … `evidence/qwen9b/bm/n18_G2_control_model_9b_s4.log:30-34` | as above | as above | **IDENTICAL** ×4, and no BM1 line printed |

The cycle and token references are the runner's `--cycles-ref` (S4's
numbers, spec §3.3 A) and `--tokens-ref evidence/qwen9b/s4/S4_REPLAY.md`
(read out of the document, not retyped); a mismatch fails the rung. The
counters are in the RTL in all eight; the plusarg only decides whether the
host reads them after HALT.

**And the whole census instrument agrees, line for line (E).** The G1 run's
`SEQ_TIMELINE` block is identical to `003`'s, all 1,055 lines
(`evidence/qwen9b/bm/n19_G1_compare.log:16-17`), and its CSV equals the
census CSV byte for byte below line 1 (sha256 `204622da…` both;
`evidence/qwen9b/bm/n19_G1_compare.log:24-26`; line 1 names each CSV's own
path). The G1 CSV (20,081,099 B) is not committed, by the census's rule; its
sha256 is (`evidence/qwen9b/bm/bm1_timeline_model_9b_s1.csv.sha256`).

### 3.2 B — every counter against the census, exact (0 cycles)

Launch totals over the busy window (segments 0..6), `model_9b_s1`. The RTL
column is the register read after HALT in G1
(`evidence/qwen9b/bm/n10_G1_bmtl_model_9b_s1.log:1103-1117`); the census
column is the sum of `003`'s lines as `evidence/qwen9b/bm/bm1_expect.py` formed
it (`evidence/qwen9b/bm/n02_expect_model_9b_s1.log:21-34`); the testbench
compared the two and printed OK on each
(`evidence/qwen9b/bm/n10_G1_bmtl_model_9b_s1.log:1126-1140`).

| counter | RTL (**T**) | census (**T**, summed) | census source | Δ |
|---|---|---|---|---|
| `PERF_CYC` (existing) | 196,706,812 | 196,706,812 | `003` meta `bcyc` (`evidence/qwen9b/bn/003_timeline_model_9b_s1.log:40`) | 0 |
| C1 `BM_MV0` | 81,492,987 | 81,492,987 | Σ `class t 8` (e.g. `evidence/qwen9b/bn/003_timeline_model_9b_s1.log:118`) | 0 |
| C2 `BM_MV1` | 81,235,575 | 81,235,575 | Σ `class t 9` (`evidence/qwen9b/bn/003_timeline_model_9b_s1.log:119`) | 0 |
| C3 `BM_MV2` | 81,149,421 | 81,149,421 | Σ `class t 10` (`evidence/qwen9b/bn/003_timeline_model_9b_s1.log:120`) | 0 |
| C4 `BM_MV3` | 81,149,554 | 81,149,554 | Σ `class t 11` (`evidence/qwen9b/bn/003_timeline_model_9b_s1.log:121`) | 0 |
| C5 `BM_FENCE` | 81,582,408 | 81,582,408 | Σ `mvop t 3` (`evidence/qwen9b/bn/003_timeline_model_9b_s1.log:261`) | 0 |
| C6 `BM_MVWORK` | 48,822,048 | 48,822,048 | Σ `mvop t 0+1+2` (`evidence/qwen9b/bn/003_timeline_model_9b_s1.log:255-259`) | 0 |
| `BM_MOVX` | 31,540,704 | 31,540,704 | Σ `mvop t 0` (`evidence/qwen9b/bn/003_timeline_model_9b_s1.log:255`) | 0 |
| `BM_MOVY` | 17,050,656 | 17,050,656 | Σ `mvop t 2` (`evidence/qwen9b/bn/003_timeline_model_9b_s1.log:259`) | 0 |
| C8 `BM_IMOVER` | 130,453,404 | 130,453,404 | Σ `ist t 17` (`evidence/qwen9b/bn/003_timeline_model_9b_s1.log:238`) | 0 |
| C9 `BM_STEPS` | 6 | 6 | Σ `opcyc t 6` count (`evidence/qwen9b/bn/003_timeline_model_9b_s1.log:249`); census §1.2 | 0 |
| `L_LCYC` (existing) | 62,414,792 | 62,414,792 | Σ `class t 0` (`evidence/qwen9b/bn/003_timeline_model_9b_s1.log:110`) | 0 |

(`L_LCYC` is read through a hierarchical probe of the layer's `lcyc`
register — the testbench cannot reach the layer's CSR port, which the
sequencer owns — and printed on the INFO line,
`evidence/qwen9b/bm/n10_G1_bmtl_model_9b_s1.log:1120`.)

**The MOVX/MOVY split sums to the census's mover work (E).** MOVX
31,540,704 + MOVY 17,050,656 + MVGO 230,688 = 48,822,048 = C6 (**D**), where
MVGO is derived on the host as C6 − MOVX − MOVY and equals the census's
`mvop t 1` total exactly (`evidence/qwen9b/bm/n02_expect_model_9b_s1.log:11`;
G1's INFO line, `evidence/qwen9b/bm/n10_G1_bmtl_model_9b_s1.log:1120`). Per token
(÷6, **D**): MOVX 5,256,784, MOVY 2,841,776, MVGO 38,448 cycles — census
§11.3's table to the cycle; the work total 8,137,008 cycles = 32.548 ms at
250 MHz, census §11.3's "three work rows sum to 32.548 ms".

### 3.3 C — the union counters

| counter | RTL (**T**) | spec §3.3 C comparand | exact recount over G1's own CSV (**E**) |
|---|---|---|---|
| C0 `BM_MVANY` | 81,689,902 | 6 × 13,614,984 ± 3 → 81,689,902 is 6 × 13,614,983.7 (**D**) — **within** | 81,689,902 (`evidence/qwen9b/bm/n19_G1_compare.log:35`, `evidence/qwen9b/bm/n19_G1_compare.log:52`) |
| C7 `BM_MVWORK_ANY` | 181,511 | 6 × 11,726.7 ± 1 = 70,360 — **NOT met: a different quantity (below)** | no census recount exists for the spec's C7 definition; the TB sampler matches the RTL exactly (`evidence/qwen9b/bm/n10_G1_bmtl_model_9b_s1.log:1112`) |

C0's comparand is the census's "matvec engine, any channel" union
(`evidence/qwen9b/bn/009_analysis_bounds_model_9b_s1.log:92`); the census CSV
itself, sha-checked, gives the same integer
(`evidence/qwen9b/bm/n02_expect_model_9b_s1.log:18`).

**THE C7 DISAGREEMENT, reported rather than picked.** The spec defines C7
as mover WORK (mover busy, op not FENCE) while any engine is busy (spec
§1.2, row C7) and names as its comparand `013`'s I-2 line, "mover work WHILE
any matvec engine busy 11726.7 cyc"
(`evidence/qwen9b/bn/013_fix1_checks_v2.log:26`). But the script that printed
that line defines "mover work" differently: mover busy with **no R beat
streaming**, whatever the op, AND any engine busy
(`evidence/qwen9b/bn/bn1_fix1_checks.py:48`). The two sets differ by exactly
two kinds of cycle, which the TB counts separately:

* FENCE cycles with an engine busy but no beat (the engine's head/tail
  around its stream): +6,082 in the census's form, not in C7;
* work cycles (MOVX/MVGO/MOVY) with an engine busy AND a beat streaming:
  +117,233 in C7, not in the census's form.

C7 − 117,233 + 6,082 = 181,511 − 117,233 + 6,082 = **70,360** (**D**) = the
census's I-2 total, 6 × 11,726.7 (`evidence/qwen9b/bm/n02_expect_model_9b_s1.log:19`),
and the testbench asserts that identity on every run
(`evidence/qwen9b/bm/n10_G1_bmtl_model_9b_s1.log:1125`; the four terms on
`evidence/qwen9b/bm/n10_G1_bmtl_model_9b_s1.log:1120`). The census's I-2 form
is itself reproduced exactly by the TB sampler, both against the census CSV
and against G1's own (`evidence/qwen9b/bm/n10_G1_bmtl_model_9b_s1.log:1139`,
`evidence/qwen9b/bm/n19_G1_compare.log:53`). **The RTL keeps the spec's
definition** (the one §1.2 specifies and D1a was ruled on); the spec's
comparand for it is what is wrong. The meaning for the board: C6 − C7, "mover
work with no engine busy", is 48,640,537 cycles (**D**: 48,822,048 −
181,511). If the user wants the census's I-2
form on the board instead, it needs the R-beat, which is on `ui_clk` (D4) —
it is not buildable from aclk signals.

### 3.4 D — internal identities, exact, on every `+bm` run

Asserted by the testbench on the RTL registers, and printed OK on G1
(`evidence/qwen9b/bm/n10_G1_bmtl_model_9b_s1.log:1121-1125`) and on each of
s1..s4 (`evidence/qwen9b/bm/n11_G2_bm_model_9b_s1.log:59-63`,
`evidence/qwen9b/bm/n12_G2_bm_model_9b_s2.log:58-62`,
`evidence/qwen9b/bm/n13_G2_bm_model_9b_s3.log:58-62`,
`evidence/qwen9b/bm/n14_G2_bm_model_9b_s4.log:58-62`):
C5 + C6 = the mover-busy cycles (130,404,456 on s1, census §11.3's identity);
C6 ≥ C7; max(C1..C4) ≤ C0 ≤ C1 + C2 + C3 + C4; MOVX + MOVY ≤ C6; and the
C7 ↔ I-2 identity above. The reserved words 0x12C and 0x1FC read 0 and 0x200
(outside the block) still reads 0xDEADC0DE
(`evidence/qwen9b/bm/n10_G1_bmtl_model_9b_s1.log:1115-1119`).

### 3.5 Seeds 2–4

There is no census for s2..s4; on those the RTL is checked exactly against
the testbench's sampler (every line OK, `BM1 L0 PASS`,
`evidence/qwen9b/bm/n12_G2_bm_model_9b_s2.log:63`,
`evidence/qwen9b/bm/n13_G2_bm_model_9b_s3.log:63`,
`evidence/qwen9b/bm/n14_G2_bm_model_9b_s4.log:63`). The figures move by a few
cycles between seeds (C0 81,689,875 … 81,689,906; C5 81,582,395 …
81,582,421) and MOVX/MOVY/C6 are identical on all four (**T**, the same
lines) — the schedule is seed-independent, only the data is not.

**Gate verdict (spec §3.3):** A PASS on G1 and on all four seeds, plusarg
off and on; B PASS, every row 0 cycles; C PASS for C0; C7's comparand is
wrong and the difference is explained to the cycle; D PASS.

---

## 4. Lint

`make -C tb lint_bm1` on snoke, Verilator 5.020, `-Wall`, eight
elaborations: `seq_unit`, `seq_unit_ipi`, `matvec_chan`, `matvec_chan_ipi`,
`tb_seq_chip` at `NMV=4`, and the three other testbenches that instantiate
the two changed modules — `tb_seq_unit`, `tb_matvec_chan`, `tb_mvshim_b` —
all clean (`evidence/qwen9b/bm/n06_lint_bm1.log:34`). Both chip-TB builds are
themselves `-Wall` builds (`evidence/qwen9b/bm/n04_build_bm1_RED.log`,
`evidence/qwen9b/bm/n07_build_bm1_GREEN.log`).

---

## 5. Deviations from the brief and the spec, each stated

1. **Three testbenches outside the brief's file list got one pin each**
   (`tb/tb_seq_unit.sv:220-223`, `tb/tb_matvec_chan.sv:58`,
   `tb/tb_mvshim_b.sv:116-119`). Adding a port to `seq_unit` and
   `matvec_chan` made all three fail `-Wall` with PINMISSING (measured before
   the fix). The spec itself says `tb_seq_unit` ties the new input to 0
   (spec §3.1); the two matvec testbenches leave the new output open under
   the `PINCONNECTEMPTY` waiver `tb_matvec_chan` already uses. No behaviour
   of those testbenches changes. The brief listed only `tb_seq_chip.sv`
   under `tb/`; this is disclosed, not hidden.
2. **The IPI wrappers** `rtl/matvec_chan_ipi.v` and `rtl/seq_unit_ipi.v` are
   the "top/BD wiring files" the brief asked to identify: the block design
   instantiates the wrappers, not the SystemVerilog modules.
3. **One obj_dir, not two.** The spec proposed `obj_dir_seq_chip_bm1` plus
   `obj_dir_seq_chip_bm1_tl`; `+timeline` is a runtime plusarg on the same
   elaboration (the census's `tl` binary is the same `tb_seq_chip`), so one
   binary serves G1 and G2, which also makes the G1/G2 comparison
   single-binary.
4. **Runner and wrapper.** The spec named `evidence/qwen9b/run.sh`; the task
   brief required `evidence/qwen9b/bm/bm_run.sh`, which was used.
5. **The MOVX/MOVY addresses** (§1.3) and **C7's comparand** (§3.3) as above.

---

## 6. What this gate does NOT establish

1. **Nothing about silicon.** No Vivado build ran (T3) and the board was not
   touched (T4). That `synth/scripts/create_project.tcl` accepts the new `connect_bd_net`
   lines and that `validate_bd_design` passes is proven only by T3's build.
2. **No timing.** The counters were written to sit in `seq_0` with
   flop-to-flop crossings (spec §4.2) and `layer_0` is untouched, but the
   shipped roll's WNS 0.000 is not re-measured here, and any netlist change
   reseeds the placer.
3. **TB exactness is a TB property.** On silicon the 2-FF synchroniser
   behind `cdc_sync_stat` resolves each asynchronous edge within a cycle
   either way (spec §7 item 4); the testbench has no metastability.
4. **Engine-busy time, not R-beat time**, and no bytes (D4) — spec §7 items
   3 and 5. C7 in particular is the aclk-buildable form, not the census's
   beat-based I-2 (§3.3).
5. **The host side is minimal**: `seq_perf()` reads the block when
   `BM_IDENT` matches (`sw/seq_run.py --selftest` covers build_041, BM1 and a
   wrong ident, 2,791 passed / 0 failed,
   `evidence/qwen9b/bm/n01_seq_run_selftest.log`). The BM1 VERSION row, the
   identity gate's explicit admission, `chat_seq --lanes` and the census
   tool of spec §2.2 items 1, 2, 4 and 5 are T4's.
6. **One seed against a census.** s2..s4 are checked against the testbench
   sampler only (§3.5).
