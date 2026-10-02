# BM1 — board-side idle counters for the shipped Qwen3.5-9B design: design spec

**Status: DRAFT for the user's review (2026-09-24). Nothing here has been
built, simulated or run on the board.** This file specifies the counters, their
testbench gate, the instrumented build and the board procedure. It changes no
RTL, TB, tool or constraint; the implementation is a later task that starts
only after the user rules on §8.

**Erratum E1 (2026-09-24; I-2 wording corrected in fix round 1, 2026-09-25) — controller ruling B2, on BM1-T1 review finding
Minor 1.** The C7 row (§1.2) and its §3.3 C comparand were mislabelled. C7
(`BM_MVWORK_ANY`, `B & MB & ~FEN & ANY`) is **"mover work while any engine
busy (engine-busy form)"**; the census's I-2 line ("mover work WHILE any
matvec engine busy 11726.7 cyc", `evidence/qwen9b/bn/013_fix1_checks_v2.log:26`)
is a *different* quantity — mover busy AND **no R beat streaming** AND any
engine busy, whatever the op (`MV & ~STR & BSY`,
`evidence/qwen9b/bn/bn1_fix1_checks.py:48`) — so C7 cannot equal
6 × 11,726.7, and "C6 − C7" is **not** the census's "mover work, nothing
streaming" (`evidence/qwen9b/bm/BM1_T1_GATE.md` §3.3). **Ruling B2: the
board's mover-work figure for census §13 #1 is C6 (`BM_MVWORK`) alone**,
compared with `evidence/qwen9b/bn/BN_CENSUS.md` §9.1(i-b)'s row "mover work
(`MOVER`, nothing streaming)" (`evidence/qwen9b/bn/BN_CENSUS.md:651`). The
census's I-2 form on the board would need the R-beat, which is on `ui_clk`
and not wired (**D4**). The RTL keeps C7 as specified; `docs/SEQ_ISA.md` B16
already words it correctly and is unchanged. The edits are in §1.2 (C7 row),
§3.3 C and the §6 board-table list; the original text is otherwise kept.

Written at HEAD `c948466` on `main`. Every statement about existing RTL, CSRs,
scripts and tools is cited `path:line`; every number is transcribed from a
committed log or gate document and cited there (label **S**, stated by a
source), or derived with the arithmetic shown (**D**). No number in this file
was produced by running anything.

---

## 0. Reading rule, and what the measurement is FOR

**Reading rule.** The campaign's: **T** = transcribed from a named log, **D** =
derived with the arithmetic shown, **S** = stated by a cited source
(`evidence/qwen9b/g6/RD9_GATE.md` §0, restated by
`evidence/qwen9b/bn/BN_CENSUS.md` §0). This spec only cites, so its numbers are
**S** unless marked **D**. "The census" below always means
`evidence/qwen9b/bn/BN_CENSUS.md`; "RD9" means `evidence/qwen9b/g6/RD9_GATE.md`.

**What it is for.** The user's direction of 2026-09-24: the target metric is
single-sequence decode tok/s at the board's context ceiling, **T < 512**
(`NEXT_SESSION.md:141`, `NEXT_SESSION.md:407` — bounded by
`rtl/attn_core.sv:114`'s 40-bit denominator); the lever is sequencer-level
overlap of the fenced phases (census §13 #1/#2); the weight format stays W4
g128 + A8; the timing target is the shipped roll (WNS 0.000,
`evidence/qwen9b/g5/G5D_TIMING.md` §10); one board; and **measure the board
before building overlap RTL**.

The overlap case today rests on the census, and the census says, of itself,
that none of its numbers is a board number:

* its memories are models (`WLAT = 40`, `DDRLAT = 32`, `tb/tb_seq_chip.sv:68-69`)
  with no refresh and no bank conflicts, and the same testbench runs the stream
  **4.6 % faster** end to end than silicon (131.138 vs 137.121 ms/token; census
  §0, §12 item 1; RD9 §10.4);
* its DDR-bound floor is the memory model's floor (census §12 item 5);
* the per-token per-channel spread "is not measurable on the sequencer path
  with the counters this netlist has" (RD9 §10.3), because
  `R_PERF_CYC`/`R_PERF_BEATS` are per-engine-RUN registers that describe only
  the last MVGO before HALT (RD9 §10.3; `rtl/matvec_chan.sv:43-44`).

The census's headline — the weight path idle for **58.51 %** of the token, the
`FENCE` at **41.48 %**, a perfect-overlap ceiling of **2.36x** (census §6,
§11.1, §9.1) — is the justification for the overlap RTL. **BM1 replaces those
testbench shares with the board's own before that RTL is designed**, at the
operating point the user chose (T just under 512), with counters whose
testbench readings are first proven to reproduce the census exactly (§3), so
that any board/TB difference is a property of the silicon and not of the
instrument.

**The deliverable of the implementation task** is one gate document
(`evidence/qwen9b/bm/BM1_BOARD_IDLE.md`, §6) holding: the TB gate (§3), the
timing gate (§4), and the board table (§5) — per launch and per T, the
weight-path busy/idle, the `FENCE` wait, mover work, the layer lane, the four
per-channel busy times and their spread.

---

## 1. The counter set

### 1.0 Clock domain — stated first, because the brief's premise is inverted

The brief asked to "state whether every signal is on ui_clk; if any is not,
say so and stop". **None of the proposed counter inputs is on `ui_clk`, and
that is the clean case, not the blocked one**: every input and every counter
is on `xdma_0/axi_aclk` (250 MHz), which is the single clock of the sequencer,
the layer and the CSR side of the matvec channels.

* `seq_0` is on `xdma_0/axi_aclk` (`synth/scripts/create_project.tcl:333`,
  with the comment "Everything on axi_aclk (single clock domain; no ui_clk on
  this module)" at `synth/scripts/create_project.tcl:331`).
* `layer_0` is on the same clock (`synth/scripts/create_project.tcl:281`;
  "Single clock domain (aclk)", `rtl/layer_chan.sv:8`).
* each `mvchan_c` has TWO clocks: `aclk` = `xdma_0/axi_aclk`
  (`synth/scripts/create_project.tcl:246`) for its CSR side and `ui_clk` = its
  own MIG's `c0_ddr4_ui_clk` (`synth/scripts/create_project.tcl:244`) for the
  streamer and engine (`rtl/matvec_chan.sv:3-5`). **Four DIMMs, four separate
  `ui_clk`s.**
* The one matvec signal this design uses, the engine-busy bit, is **already**
  synchronised into `aclk` by the channel's existing 2-FF synchroniser:
  `ui_busy = st_busy || en_busy` (`rtl/matvec_chan.sv:453`) →
  `cdc_meta_stat` → `cdc_sync_stat` (`rtl/matvec_chan.sv:233-238`, `ASYNC_REG`,
  false-pathed by the existing `*cdc_meta_*_reg*/D` constraint in
  `synth/constraints/fable5_cdc.xdc`, enumerated at
  `evidence/qwen9b/g5/G5D_TIMING.md` §9.1). `cdc_sync_stat[0]` is the bit the
  channel's own STATUS CSR returns (`rtl/matvec_chan.sv:357`) **and the exact
  bit the census sampled as `MVc_BSY`** (`tb/seq_timeline.svh:154`).

**So this design adds no CDC structure, no clock and no false path.** The only
quantity that lives on `ui_clk` — the raw R-beat count per channel — is NOT in
the proposed set; counting it on the board would need a new crossing (a
quasi-static read of a `ui_clk` accumulator, the pattern the per-run
`perf_cycles`/`perf_beats` already use, `rtl/matvec_chan.sv:240-242`), and
that is offered to the user as decision **D4** (§8), not built. The case
against needing it: the census found the per-channel byte load equal to the
static `plan_weight_split` **byte for byte** (census §6 check 1), so the bytes
are a property of the schedule; the unknown on silicon is the **time**, which
the aclk busy counters measure.

**What "streaming" means on silicon here.** The census has two per-channel
classes: `MVc_STR` (an R beat this cycle, from the TB's memory model,
`tb/seq_mem_file.sv:348`) and `MVc_BSY` (engine busy, the synchronised
`cdc_sync_stat[0]`). Only the second exists in the RTL. The counters below
therefore measure **engine-busy time**; in the census the two differ by
54.460 vs 54.408 ms/token for the any-channel union (census §4, grouped table)
— **the counters' "weight path busy" is the census's "matvec engine, any
channel", not its "weight streaming"**, and §3's gate compares like with like.

### 1.1 Where the counters live, and the four new wires

**All new counters live in `seq_unit`**, in one host-read block, all gated by
the same `busy_r` window `PERF_CYC` uses (`rtl/seq_unit.sv:360`,
`rtl/seq_unit.sv:975`) and cleared by the same `START` that clears the five
`PERF_*` registers (`rtl/seq_unit.sv:1002-1003`). One window, one clear, one read
site: every counter is directly comparable with `PERF_CYC` and with every
other.

`seq_unit` already sees `busy_r`, `mv_busy` (`rtl/seq_unit.sv:877`), `mv_op`
(`rtl/seq_unit.sv:879`; `2'd3` = FENCE, `rtl/seq_unit.sv:1099-1102`,
`MOP_FENCE` at `rtl/seq_movers.sv:177`), the issue-FSM state `ist`
(`rtl/seq_unit.sv:844-853`) and the decoded opcode. What it does NOT see is any
matvec channel's busy bit — the `FENCE` learns completion by polling STATUS
over AXI-Lite (`rtl/seq_movers.sv:839-842`). So the design adds **four 1-bit
nets, `mvchan_c` → `seq_0`**, each `cdc_sync_stat[0]`:

| net | source | destination | domain |
|---|---|---|---|
| `mv_busy_bm[c]`, c = 0..3 | new output port on `matvec_chan` (and `rtl/matvec_chan_ipi.v`) driven by a dedicated flop of `cdc_sync_stat[0]` (`rtl/matvec_chan.sv:237`) | new input port on `seq_unit` (and `rtl/seq_unit_ipi.v`), two flops deep before use | `aclk` both ends |

In the block design they are plain scalar nets added in
`synth/scripts/create_project.tcl`, the same kind of wiring as the existing
`seq_0/xrf_sb_*` tie-offs (`synth/scripts/create_project.tcl:349-351`).

**`layer_0` is NOT touched** (decision **D2**, §8, argues it): the layer lane
already has an exact accumulating counter, `L_LCYC` (`busy_cmp` cycles,
`rtl/layer_chan.sv:1055`, any write clears, `rtl/layer_chan.sv:1117`, read at
`rtl/layer_chan.sv:1173`), which RD9 §10.2 already read on silicon; and the
one quantity a wire would add — layer busy AND a matvec engine busy, i.e. the
overlap achieved — is **zero in the shipped schedule**: the census's run prints
no `pair s 0 c` line for any matvec-busy class c = 8..11 in any segment, and its
pair lines are printed only when non-zero (**T**,
`evidence/qwen9b/bn/003_timeline_model_9b_s1.log:126-130` is segment 1's
complete `L_CMP` pair list; `evidence/qwen9b/bn/013_fix1_checks_v2.log` prints
`layer AND streaming 0.0 cyc` for the R-beat form). That counter becomes
necessary only once overlap RTL exists — and that RTL is a new build that can
carry it. Leaving `layer_0` byte-identical is also the single strongest thing
this design can do for the `ATTN_DSP` path (§4.2).

### 1.2 The counters

`B` = `busy_r`; `M[c]` = the aligned `mv_busy_bm[c]`; `ANY` = `|M`;
`MB` = `mv_busy`; `FEN` = `(mv_op == 2'd3)`. Every term is delayed by the
same pipeline depth as `M` (§1.3), so each counter counts exactly the cycles
the census's negedge sampler would have classed the same way.

| # | name | counts cycles (or events) of | condition | census comparand (§3) |
|---|---|---|---|---|
| C0 | `BM_MVANY` | **weight path busy**: any matvec engine busy | `B & ANY` | "matvec engine (any chan)", `evidence/qwen9b/bn/009_analysis_bounds_model_9b_s1.log:92` |
| C1–C4 | `BM_MV0`..`BM_MV3` | **per-channel** engine busy — the spread RD9 §10.3 could not see | `B & M[c]` | class `MVc_BSY`, `SEQ_TIMELINE class s 8+c` lines of `evidence/qwen9b/bn/003_timeline_model_9b_s1.log` |
| C5 | `BM_FENCE` | **`FENCE` drain wait** (the mover busy on a FENCE) | `B & MB & FEN` | `mv_op` 3, `SEQ_TIMELINE mvop s 3` lines of `003` (e.g. `evidence/qwen9b/bn/003_timeline_model_9b_s1.log:261`) |
| C6 | `BM_MVWORK` | **mover work**: MOVX/MVGO/MOVY | `B & MB & ~FEN` | `mv_op` 0+1+2, `SEQ_TIMELINE mvop s 0..2` (`evidence/qwen9b/bn/003_timeline_model_9b_s1.log:255-259`) |
| C7 | `BM_MVWORK_ANY` | **mover work while any engine busy (engine-busy form)** — the aclk-buildable co-occurrence of C6 with C0; it is **not** the census's beat-based I-2, and C6 − C7 is **not** the census's "mover work, nothing streaming" (erratum E1, 2026-09-24, at the top of this file) | `B & MB & ~FEN & ANY` | none in the census — the TB sampler's own recount (erratum E1); the board's mover-work figure is **C6** alone, against `evidence/qwen9b/bn/BN_CENSUS.md` §9.1(i-b) |
| C8 | `BM_IMOVER` | issue FSM in `I_MOVER` (census §11.2's 66.32 % row) | `B & (ist == I_MOVER)` | `SEQ_TIMELINE ist s 17` (e.g. `evidence/qwen9b/bn/003_timeline_model_9b_s1.log:238`) |
| C9 | `BM_STEPS` | **forward steps** (events): `OP_EMB` records dispatched | pulse on the `I_EXEC` dispatch of `OP_EMB` (`rtl/seq_unit.sv:1104`) | six per launch of `model_9b_s1` (census §1.2: four `OP_EMB` records, the last in a three-pass loop) |
| C10 | `BM_IDENT` | constant — feature detect | reads a fixed magic | — |

**Not in the set, on purpose:**

* **the layer lane** — `L_LCYC` already is it (§1.1); the host tool clears it
  before `START` and reads it after HALT on every launch (§2.3), exactly as
  `evidence/qwen9b/g6/g6_census.py` did for RD9 §10.2 (its header,
  `evidence/qwen9b/g6/g6_census.py:9-14`). The state-DMA lane likewise stays
  `L_SDMA_CYC` (`rtl/layer_chan.sv:1056`).
* **weight path idle** — it is `PERF_CYC − BM_MVANY`, derived on the host;
  a counter would be redundant.
* **all four channels busy together** (census §6's 94.22 %) — cheap to add,
  but not asked for and not needed for the spread; listed under **D5**.
* **R-beat counts** — `ui_clk`, **D4**.

**The FENCE and I_MOVER pair.** C5 is the drain wait itself; C8 is the issue
FSM's view (it also contains the MOVX/MOVY/MVGO work and the handshake). The
census reports both and they differ by the mover work (census §11.2 vs §11.3),
so carrying both lets the board reproduce that identity; C8 is the cheaper to
drop if the user wants the smallest set.

### 1.3 Width, reset and latch semantics, and the alignment pipeline

* **Width: 32 bits**, like `PERF_CYC` (`rtl/seq_unit.sv:382`). The longest
  single launch any procedure below makes is the six-token `model_9b_s1`
  stream, which silicon measured at **205,681,492** cycles
  (`evidence/qwen9b/g6/020_perf_census_two_lanes.log:26`), inside 32 bits; a
  chat launch is one step. A launch longer than `PERF_CYC` can count would
  wrap every counter together — the same limit the shipped register already
  has, and the tools never launch one.
* **Reset/latch: free-running inside the launch window, cleared at `START`,
  frozen at HALT, read once after HALT** — the `PERF_*` contract
  (`docs/SEQ_ISA.md:257`; clear at `rtl/seq_unit.sv:1002-1003`). Not cleared by
  a host write (no write decode at all — the block is read-only), not by
  ABORT, only by `START` and hard reset.
* **Per-token values come from the launch structure, not from latch logic.**
  `sw/chat_seq.py` makes **one sequencer launch per forward step**
  (`sw/chat_seq.py:1256-1258`, and it refuses a launch that produced more than
  one token, `sw/chat_seq.py:1370-1372`) and reads `seq_perf()` after every
  HALT (`sw/chat_seq.py:1349`). So on the chat path the counters ARE per-step
  latched, for free. Only a multi-token stream (the six-token `model_9b_s1`
  launch) gets a launch total; a per-`OP_EMB` snapshot bank is decision
  **D3**.
* **Alignment.** `M[c]` arrives through the source flop in `matvec_chan` and
  two flops in `seq_unit` (the nets cross SLRs, §4.2). Every local term
  (`busy_r`, `mv_busy`, `mv_op`, `ist == I_MOVER`, the `OP_EMB` pulse) is
  delayed by the same depth before it enters a condition, so every condition
  is evaluated on one consistent cycle. Because `START` clears the counters
  and the delayed `busy_r` is still low for the first cycles of the new
  window, and because a host read after HALT is many AXI-Lite cycles later
  than the delayed window's end, the delay changes no count. (The census's
  sampler reads each cycle's values at the following negedge,
  `tb/seq_timeline.svh:264-265`; an RTL counter evaluates the same values at
  the following posedge — the same cycle set.)

### 1.4 Adopting OV1's set when it lands

Task OV1's deliverable 5 (`.superpowers/sdd/2026-09-24-overlap/task-OV1-brief.md`,
"Deliverables" item 5) will name the minimal counter set its dependency model
needs; OV1 had not delivered when this spec was written. **Adoption rule:**
any counter OV1 names is added to §1.2 if its condition is a function of
signals `seq_unit` already has plus the four `M[c]` nets — i.e. no new port on
`layer_0` and nothing on `ui_clk` — and it takes the next free word of the
reserved block (§2.1), so no address in this spec moves. Anything OV1 needs
that fails that test goes to the user as a decision, with its timing cost
named against `layer_0` (§4.2). OV1's list is compared against §1.2 in the
implementation task's first step, before any RTL is written.

---

## 2. CSR additions — `docs/SEQ_ISA.md` addendum v2.2, and the host tools

### 2.1 The block: SEQ `0x100`..`0x1FC`, host-read-only

**The maps checked for collisions** (all three blocks, as built):

| block | BAR base | map as built | source |
|---|---|---|---|
| SEQ (`seq_0`) | `0x6000`, 4 KiB (`sw/hwmap.py:305`) | `0x00`..`0x3C` CTRL..PERF_FST, `0x40`..`0x5C` XRF[0..7], `0x60` EMBLOG2; everything else reads `0xDEADC0DE` | `rtl/seq_unit.sv:24-48`, read mux `rtl/seq_unit.sv:1487-1516`, `docs/SEQ_ISA.md:231-275` (B1) |
| layer_chan (`layer_0`) | `0x5000` (`sw/hwmap.py:178`) | `0x00`..`0x74` incl. TOPK `0x48`..`0x58`, DNSB `0x5C`, SB_*/SDMA/SDMA_CYC `0x64`..`0x74` | `rtl/layer_chan.sv:12-60`; `docs/SEQ_ISA.md` B7, B15.3 |
| matvec_chan c | `0x1000·(c+1)` | `0x00`..`0x34` | `rtl/matvec_chan.sv:12-49`, read mux `rtl/matvec_chan.sv:356-371` |

**The additions go in the SEQ block at `0x100`..`0x12C`, with `0x130`..`0x1FC`
reserved for BM1/OV1 additions.** Why there:

* **no collision**: nothing in the SEQ map is at or above `0x64`
  (`rtl/seq_unit.sv:1487-1516`), and the read mux's XRF default decodes only
  `s_axil_araddr[11:5] == 7'h02` (`rtl/seq_unit.sv:1637`), which `0x100`+ cannot match;
  the write-side XRF default decodes `csr_waddr[9:3] == 7'h02`
  (`rtl/seq_unit.sv:1337`), which `0x100`+ cannot match either;
* **unreachable from the stream by construction**: an in-stream `CSRWR` reaches
  the SEQ block only through the `0x2nn` space, which admits exactly
  `0x20` and `0x40..0x5C` and halts with err `0x07` on anything else
  (`docs/SEQ_ISA.md:352-355`), and `nn` is 8 bits, so `0x100`+ is not even
  addressable from a record;
* **matvec_chan's and layer_chan's CSR maps do not change at all.** The
  matvec change is one output port; the layer is untouched. Every existing
  tool, register and ISA rule keeps its meaning.

**The v2.2 addendum text** (to be appended to `docs/SEQ_ISA.md` as section B16
by the implementation task, after the tables it cites are re-verified):

```
## B16. BM1 idle counters — SEQ 0x100.. (v2.2)
Host-read-only. Cleared by START with the PERF_* registers, counted while
busy_r (the PERF_CYC window), frozen at HALT. Writes are ignored. Not
reachable from any record (0x2nn admits only 0x20 and 0x40..0x5C).
  0x100 BM_IDENT      R  0xFAB1_B301  (reads 0xDEADC0DE on build_041)
  0x104 BM_MVANY      R  cycles: any matvec engine busy
  0x108 BM_MV0        R  cycles: matvec chan 0 engine busy
  0x10C BM_MV1        R  ... chan 1
  0x110 BM_MV2        R  ... chan 2
  0x114 BM_MV3        R  ... chan 3
  0x118 BM_FENCE      R  cycles: mover busy on a FENCE (drain wait)
  0x11C BM_MVWORK     R  cycles: mover busy on MOVX/MVGO/MOVY
  0x120 BM_MVWORK_ANY R  cycles: mover work while any matvec engine busy
  0x124 BM_IMOVER     R  cycles: issue FSM in I_MOVER
  0x128 BM_STEPS      R  OP_EMB records dispatched (forward steps)
  0x12C (reserved; reads 0)
  0x130..0x1FC reserved for BM1/OV1 additions (read 0)
"engine busy" = matvec_chan's own STATUS bit 0 (cdc_sync_stat[0]),
already in aclk; no new CDC.
```

(The `BM_IDENT` value is a proposal; the rule is only that it differ from
`0xDEADC0DE` and from every IDENT already in use — `0xFAB1E5E0`
`rtl/seq_unit.sv:322`, `0xFAB1E5A0` `rtl/layer_chan.sv:23`, `0xFAB1C4A0|c`
`rtl/matvec_chan.sv:49`, `0xFAB1704B` `rtl/layer_chan.sv:35`.)

### 2.2 Why feature detection, and the VERSION problem

`synth/scripts/launch_build.sh:12` stamps the build's VERSION as the tree's
8-hex git hash, so the instrumented bitstream will report a VERSION no tool
knows, and **the tools refuse unknown VERSIONs by design**:
`sw/hwmap.shape_isa_for_version()` has no default and raises `UnknownBitstream`
(`sw/hwmap.py:118-134`), and the sequencer tools gate on
`EXPECTED_SEQ_VERSION = 0xC973C18A` (`sw/seq_run.py:130`, the identity gate at
`sw/seq_run.py:1119-1184`). Required host changes, all in the implementation
task and none here:

1. **`sw/hwmap.py`**: one row in `SHAPE_ISA_BY_VERSION` (`sw/hwmap.py:96-105`)
   mapping the BM1 VERSION to `SHAPE_ISA_9B` — the netlist's SHAPE decode is
   unchanged — plus its assert beside `sw/hwmap.py:860`, plus register
   constants `S_BM_*` next to `S_PERF_FST` (`sw/hwmap.py:325`).
2. **`sw/seq_run.py`**: the identity gate accepts the BM1 VERSION **only when
   asked** — an explicit `--expect-version` (the gate function already takes
   `expect_version`, `sw/seq_run.py:1119`) plumbed through the two tools below;
   `EXPECTED_SEQ_VERSION` itself stays `0xC973C18A`, because the shipped
   bitstream stays the resident default (§5 step 9).
3. **`seq_perf()`** (`sw/seq_run.py:1307-1313`) reads `BM_IDENT` and, only if
   it matches, the ten BM registers into a `"bm"` sub-dict of the report it
   already returns. On build_041 `BM_IDENT` reads `0xDEADC0DE`
   (`rtl/seq_unit.sv:1516`) and the key is omitted — **feature detection, not
   a VERSION table**, so the same tool runs on both bitstreams.
4. **`sw/chat_seq.py`**: a `--lanes` flag that clears `L_LCYC`/`L_SDMA_CYC`
   before each `START` and reads them after each HALT inside `_launch()`
   (`sw/chat_seq.py:1256-1372`) — legal, the sequencer is idle at both
   points (`docs/SEQ_ISA.md:150-156`) — and stores them in the per-launch
   report beside `"perf"`. Today `chat_seq` "never writes L_LCYC / L_SDMA_CYC"
   (`evidence/qwen9b/g6/g6_longctx_rung.sh:18-19`), which is why RD9's
   long-context lanes were one session-wide bracket.
5. **A census tool for the stream**: `evidence/qwen9b/bm/bm1_census.py`, a copy
   of `evidence/qwen9b/g6/g6_census.py` that additionally prints the BM block
   (the RD9 §10 path: clear lanes while idle, run `model_9b_s1.e4`, read after
   HALT).

---

## 3. Validation on the chip testbench — the acceptance gate, BEFORE any build

**Nothing is built for the board until this gate is PASS.**

### 3.1 What changes in the TB

`tb/tb_seq_chip.sv` instantiates the real `seq_unit` (`tb/tb_seq_chip.sv:189`)
and `NMV` real `matvec_chan`s (`tb/tb_seq_chip.sv:352`); it gains the four
`mv_busy_bm` connections, mirroring the block design (unbuilt slots tie 0, the
way `tb/seq_timeline.svh:150-157` already does). `tb/tb_seq_unit.sv` (stub
channels) ties the new input to 0. The elaboration is a new obj_dir,
`obj_dir_seq_chip_bm1` (and `obj_dir_seq_chip_bm1_tl` for the `+timeline`
variant), built with the same `NMV=4 WIMGPC=1` as the census
(census §1). `-Wall` clean under Verilator 5.020, per the repo rule.

### 3.2 The runs (snoke only, through `evidence/qwen9b/run.sh`)

| rung | stream | what it proves | cost (**S**) |
|---|---|---|---|
| G0 | `tok9b_s1` smoke, control + `+timeline` | the counters elaborate, count, and perturb nothing | 172–177 s per run (census §2) |
| G1 | `model_9b_s1`, `+timeline` | **the gate**: every counter against the census | ~8,472 s (census §2) |
| G2 | `model_9b_s1`..`_s4`, no `+timeline`, one binary, four processes in parallel | zero perturbation on four seeds (the repo's 4-seed rule) | ~8,805 s each, concurrent (census §2) |

### 3.3 The acceptance criteria

**A. Zero perturbation — exact.** Every G1/G2 run reproduces
`evidence/qwen9b/s4/S4_REPLAY.md` §4.2's cycle count for its seed
(196,706,821 / 196,707,670 / 196,707,670 / 196,706,833, as census §0 quotes
them) and its tokens (`[2614, 314, 279, 369, 11751, 13]` for s1, census §2).
G1's `SEQ_TIMELINE` block equals `003`'s line for line (the RTL change adds
registers only; any moved line FAILS the rung). This is the same
control-against-the-record check the census ran (census §2).

**B. Every counter against the census — exact, 0 cycles**, launch totals over
the busy window (segments 0..6):

| counter | must equal | source lines |
|---|---|---|
| `PERF_CYC` (existing) | `bcyc` 196,706,812 | `evidence/qwen9b/bn/003_timeline_model_9b_s1.log:40` |
| C1–C4 | Σ over segments of `class s 8..11` | `003`, e.g. segment 1 at `evidence/qwen9b/bn/003_timeline_model_9b_s1.log:118-121` |
| C5 | Σ `mvop s 3` | `003`, e.g. `evidence/qwen9b/bn/003_timeline_model_9b_s1.log:261` |
| C6 | Σ `mvop s 0` + `s 1` + `s 2` | `003`, e.g. `evidence/qwen9b/bn/003_timeline_model_9b_s1.log:255-259` |
| C8 | Σ `ist s 17` | `003`, e.g. `evidence/qwen9b/bn/003_timeline_model_9b_s1.log:238` |
| C9 | 6 | census §1.2 |
| `L_LCYC` (existing) | Σ `class s 0` (`L_CMP`) | `003`, e.g. `evidence/qwen9b/bn/003_timeline_model_9b_s1.log:110` |

These are exact because each counter's condition is **the same signal the
instrument sampled** (`tb/seq_timeline.svh:271-286` for the class bits,
`tb/seq_timeline.svh:343` for `ist`, `tb/seq_timeline.svh:354` for `mv_op`)
over **the same window** (`dut.busy_r`, `tb/seq_timeline.svh:265`), and the
TB has no metastability. A non-zero difference is a bug in the counter, not
tolerance.

**C. The union counters — to the census's printed precision.** C0 is a
union the log prints only as a per-token mean; C7 has no census comparand
(erratum E1, 2026-09-24):

| counter | must equal | tolerance | source |
|---|---|---|---|
| C0 | 6 × 13,614,984 (**D**: the per-token mean over tokens 1..6; segment 0 has no matvec activity, `evidence/qwen9b/bn/003_timeline_model_9b_s1.log:71-74`) | ±3 cycles — the rounding of an integer-printed mean of six | `evidence/qwen9b/bn/009_analysis_bounds_model_9b_s1.log:92` |
| C7 | ~~6 × 11,726.7~~ — **withdrawn** (erratum E1): that I-2 figure is a different quantity. C7 is checked **exactly** against the TB sampler's engine-busy-form recount, and the identity C7 − (work ∧ engine busy ∧ beat) + (FENCE ∧ engine busy ∧ no beat) = 6 × 11,726.7 ties it to I-2 in the TB only | 0 cycles (TB sampler) | `evidence/qwen9b/bm/BM1_T1_GATE.md` §3.3 |

and, independently of rounding, **exactly** equal to the same unions
recomputed by `evidence/qwen9b/bn/bn_timeline.py` over G1's own CSV (the CSV
is regenerated by G1 and, like the census's, not committed; its sha256 is).

**D. Internal identities, exact:** C6 − C7 ≥ 0; C5 + C6 = Σ over segments of
class `MOVER` (`mv_busy`, `tb/seq_timeline.svh:273`) — the census's §11.3
identity; `max(C1..C4) ≤ C0 ≤ C1+C2+C3+C4`.

**Gate verdict:** A and B and C and D all PASS on G1, and A on all four G2
seeds. Evidence and gate doc per §6. **A FAIL stops BM1 before any Vivado
run.**

---

## 4. The build

### 4.1 Project, top, naming, recipe

* **Tree:** the implementation task's committed tree (clean — the VERSION is
  the tree's hash, `synth/scripts/launch_build.sh:12`), with the RTL of §1,
  the TB of §3 and the BD edit in `synth/scripts/create_project.tcl`. Same top
  (`bd_wrapper`), same project script, same constraints list, same Vivado
  2024.2 on snoke (`CLAUDE.md` Lab facts).
* **Base build:** `synth/scripts/launch_build.sh build_042_bm1` on snoke,
  detached (`nohup`). The launcher refuses an existing out dir
  (`synth/scripts/launch_build.sh:14-17`), so `synth/out_build_042_bm1/` is
  fresh by construction. (`build_041` is the highest build number under
  `synth/`; the implementation task confirms `042` is still free.)
* **The shipped recipe, reproduced exactly:** the roll that closed was
  `TAG=ckr2 XDC=…/fable5_clockroot_9b.xdc synth/scripts/launch_po2.sh
  build_041 AltSpreadLogic_high` — full recipe, `AltSpreadLogic_high`,
  post-place and post-route `phys_opt` `AggressiveExplore`, the one
  implementation-only clock-root XDC, **no pblock**
  (`evidence/qwen9b/g5/G5D_TIMING.md` §8, §9 row 9). BM1 runs the same
  command on `build_042_bm1` → `synth/out_build_042_bm1_ckr2_AltSpreadLogic_high`
  (`synth/scripts/launch_po2.sh` names and refuses existing dirs itself).
* **The first roll is a spread, not a single roll.** `synth/scripts/launch_po2.sh` takes
  several directives and runs them in parallel into separate out dirs; the
  first launch is `AltSpreadLogic_high` **plus** `AltSpreadLogic_medium`,
  `ExtraNetDelay_high` and `ExtraTimingOpt`, all with the clock-root XDC —
  the four best unconstrained directives of the shipped campaign
  (`evidence/qwen9b/g5/G5D_TIMING.md` §9 rows 2, 3, 4, 6). Rationale: the
  shipped WNS was one roll of ten, and the only one carrying the XDC
  (G5D §9's closing note); the placer's run-to-run spread on this device is
  the project's known hazard (the timing-closure playbook, `CLAUDE.md`
  global rules).

### 4.2 The timing goal, and why the counters should cost no ATTN_DSP slack

**Goal: the G5D criterion, unrelaxed** — WNS ≥ 0.000 and WHS ≥ 0.000 on all
clocks, **zero** failing setup/hold/pulse-width endpoints, no waiver
(`evidence/qwen9b/g5/G5D_TIMING.md` §10). The shipped roll met it at WNS
**0.000** on `xdma_0_axi_aclk`, WHS **+0.001**, with the MIG UI clocks at
+0.003 … +0.031 (G5D §8.3, §10) — "a design with no slack to give: any change
to the RTL … requires the whole gate to be re-measured, not assumed" (G5D
§10). **That is the honest frame: no design can promise the ship's 0.000
survives a re-place; this one minimises what changes and re-measures.**

**Where the critical path is.** The shipped worst path is a KV-slot URAM288
clock-to-out into an attention DSP inside `layer_0`
(`…/u_core/g_kvslot[0].mem_reg_uram_50/CLK` → `…/u_attn/g_lane[225].pv_p_reg[225]`,
G5D §8.2), and it is a **clock-skew** problem more than a logic one (+0.407 ns
of skew moved by the clock root, data path +0.047, G5D §8.2). It is on
`xdma_0_axi_aclk` — **the same clock the counters use.**

**Placement of the new logic:**

* **Nothing in `layer_0`** (§1.1) — its RTL, and therefore its synthesized
  netlist, is unchanged. The ATTN_DSP path's own cells do not change; what can
  still move is placement, because any netlist change reseeds the placer.
* **The counters sit in `seq_0`**, which the shipped rolls place wholly in SLR1
  (`evidence/qwen9b/g5/G5D_TIMING.md` §4.2, on the `po2` roll; the closing
  roll's census is `evidence/qwen9b/g5/144_t14b_slrcensus_ckr2.log`, G5D §8.3) and which ended
  the closing roll at **+0.397** ns of slack with the clock root moved away
  from it (G5D §8.2). Eleven 32-bit incrementers plus a read-mux extension
  (the existing mux has sixteen 32-bit arms plus the XRF default,
  `rtl/seq_unit.sv:1487-1516`); the incrementers are local register-to-register
  paths inside SLR1.
* **The four nets are registered at both ends and cross SLRs.** `mvchan_0` sits
  in SLR0 and `mvchan_1..3` in SLR1 on the `po2` roll (G5D §4.2), so
  `mvchan_0`'s net is an SLR0 → SLR1 crossing. Each is a source flop inside
  `matvec_chan`'s **aclk** half (next to `cdc_sync_stat`,
  `rtl/matvec_chan.sv:233-238`) → an SLL route → two flops in `seq_unit`,
  with **no logic between flops**, so the placer can use Laguna registers and
  the path is a single hop. **No constraint is added**: a multicycle would be
  wrong on a level that is counted every cycle, and a false path would hide a
  real path. The `matvec_engine` 300 MHz `xline_q0` CE cone that G5D watches
  (`FV_XLINE_*`, G5D §8.3) is on `ui_clk` and is not touched.
* **One load is added to an existing net**: `cdc_sync_stat[0]` gains the
  source flop (it already feeds the STATUS read mux, `rtl/matvec_chan.sv:357`).

**The timing checks on the BM1 roll**, all existing scripts:
`synth/scripts/final_verify.tcl` (`FV_OK`, `FV_WNS`, `FV_WHS`, the
`FV_STILL_CHECKED` set for `u_dn`/`u_dma`/`u_attn`, G5D §8.3);
`evidence/qwen9b/g5/g5d_clockroot_check.tcl` (the clock root is in the
layer's SLR — `CLOCKROOT_SLR_OK`, `synth/constraints/fable5_clockroot_9b.xdc:115-125`);
the per-SLR census (G5D §4.2's tool) to confirm `layer_0` stayed in one SLR;
and one new report — `report_timing` through the BM1 cells (`seq_0` counters
and the four crossing nets) — to show their own slack. The gate document
reports WNS/TNS/WHS per clock **against the shipped roll's table** (G5D §8.3).

### 4.3 If the first spread misses

In order, each a separate out dir, each reported with before/after WNS:

1. **More directives on the same netlist and XDC** (the remaining ones G5D ran
   or the valid-directive list in the `fpga-tooling-reference` skill), 3–4 in
   parallel — the house practice (timing-closure playbook).
2. **The post-route `phys_opt` playbook** on the best roll
   (`evidence/qwen9b/g5/g5b_physopt_playbook.tcl`, G5D §6) — noting it bought
   +0.000 on the ship (G5D §6, §10.1 item 5), so it is a confirmation step.
3. **Stop and ask** (decision **D6**): the options are an incremental
   implementation against the shipped routed checkpoint
   (`synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper_routed.dcp`),
   which no script in `synth/scripts/` does today and would be new tooling; an
   extra pipeline flop on the crossing; or accepting a stated negative WNS for
   a **measurement-only** bitstream (which the user has never done and this
   spec does not recommend). **No waiver is taken without the user.**

### 4.4 Expected wall time on snoke (**S**, from the shipped campaign)

| step | shipped comparand | source |
|---|---|---|
| `launch_build.sh` (create, synth, default impl) | **3 h 40 m** (`build_041`) | G5D §1 row 103 |
| the `ckr2` roll alone | **4 h 54 m** | G5D §1 row 134, §8 |
| four concurrent full-recipe rolls | **5 h 35 m** (the po2 spread) | G5D §1 row 109, §3.2 |
| final_verify + clock-root check + census | minutes to an hour each (G5D §8.3's logs) | G5D §8.3 |

So **roughly 9–10 hours** from launch to a scored four-roll spread (**D**:
3 h 40 m + 5 h 35 m, with the four-roll spread's wall time standing in for a
four-roll `ckr2` spread), plus the checks. The runs share snoke with any other
project's Vivado jobs (`CLAUDE.md`); one build per project dir, fresh out dir
per build (NEXT_SESSION "Key invariants").

---

## 5. The board procedure

**Rails that bind every step** (`CLAUDE.md`; `NEXT_SESSION.md` §4 and "Key
invariants"): JTAG-volatile only, never flash; the reprogram is
`remove` → JTAG → `rescan`, which `sw/program_fpga.sh` performs itself under
**one hold** of `/home/cah/r2d2/code/fpga/.fable5_board.lock`
(`docs/USAGE.md` §2; `sw/program_fpga.sh:10-29`); **no DMA before CALIB reads
`0xF`** (CSR `0x0C`); every tool takes the lock itself and `--no-lock` is
never used by a script (`NEXT_SESSION.md` §4); every run on snoke through
`evidence/qwen9b/run.sh`, which refuses to overwrite a log. One board.

**Preconditions:** §3 PASS committed; §4 PASS committed with the BM1 `.bit`
path, size and sha256 recorded; the §2.2 host changes committed with their
own `--selftest`/`--mock` runs green (board-free modes take no lock,
`NEXT_SESSION.md` §4).

| step | action | check before the next step |
|---|---|---|
| **1. control on the SHIPPED bitstream** | identity check (`docs/USAGE.md` §1 "Verify the board is alive"): VERSION `0xc973c18a`, CALIB `0xF`. Then the §5.1 session ×4 with `--lanes` (the new flag works on build_041 — lanes exist there; the BM block is feature-detected absent) | tokens identical across the four; per-step `PERF_CYC` recorded — **this is the comparand that proves the BM1 bitstream does not change the step time** |
| **2. reprogram to BM1** | `./sw/program_fpga.sh synth/out_build_042_bm1_ckr2_<directive>/proj/stage1.runs/impl_1/bd_wrapper.bit` (the command form of `docs/USAGE.md` §2) | exit code 0 — a JTAG failure leaves the OLD design answering normally (`docs/USAGE.md` §2, note 2) |
| **3. identity + CALIB** | the identity check again: MAGIC, **VERSION = the BM1 hash**, CALIB `0xF`; `BM_IDENT` reads the §2.1 magic | any mismatch: STOP, no DMA |
| **4. bring-up** | the §5.1 chat session's own bring-up re-establishes weights and state: the residency witness decides whether the 5,845 MiB pack re-uploads (`docs/USAGE.md` §3 "Chat at 9B" table), and `chat_seq` writes the state region itself (`NEXT_SESSION.md` §1) | residency line and upload result in the log; **expect** a re-upload — G5D §11 recorded that a reprogram invalidated the resident pack last time — but let the witness decide |
| **5. the stream census (TB comparand)** | `bm1_census.py --prefix tb/scripts/w9/model_9b_s1.e4 --fresh-state` ×4 (the RD9 §10 path: `evidence/qwen9b/g6/020_perf_census_two_lanes.log:4` is its command line and `evidence/qwen9b/g6/020_perf_census_two_lanes.log:25` its tokens) | tokens `[2614, 314, 279, 369, 11751, 13]`, `err_code 0x00`, all ten BM registers and both lanes read after HALT |
| **6. the metric: chat at T just under 512** | the §5.1 session ×4 on BM1, `--lanes`, JSON per launch | printed context ≤ 511 on every run; tokens identical to step 1's |
| **7. the T-curve** | the same session once with `--prefill full` ("every step emits a token", `sw/chat_seq.py:6420-6422`), so every one of the ~511 launches is a full step and carries its own counters | the report's per-launch `image` and `pos` fields name each step |
| **8. read-out** | nothing extra — every counter is in the per-launch JSON (§2.2 items 3–4) | — |
| **9. restore the shipped bitstream** | `./sw/program_fpga.sh synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper.bit` (`docs/USAGE.md:122-124`); identity: VERSION `0xc973c18a`, CALIB `0xF`; one greedy chat turn (`docs/USAGE.md` §3) to re-establish residency and confirm the path serves | VERSION read back off the silicon and logged; the chat turn's tokens |
| **10. record the resident state** | update `NEXT_SESSION.md` §1's table from the logs' own timestamps (its standing lesson, `NEXT_SESSION.md` §1 preamble) | — |

### 5.1 The session: prompt, context, token count

**Prompt: the committed long-context prompt**, verbatim — the instruction
"Summarise the following passage in one sentence. " followed by sixteen copies
of the Paris sentence, built by `evidence/qwen9b/g6/g6_longctx_rung.sh:38-40`
(and identically by `evidence/qwen9b/g6/g6_longctx_lanes.sh`). It renders to
**503** templated ids (RD9 §8.7), which is the closest committed prompt to the
ceiling.

**Context and count:** `FABLE5_MODEL=9b sw/chat_seq.py --nch 4 --max-ctx 511
--ntok 9 --lanes --prompt "$PROMPT" --out <json>`. RD9 §8.7 counts that prompt
as 502 prefill launches + `ntok` decode steps = the context (502 + 24 = 526 on
that run), so `--ntok 9` gives a context of 511 (**D**: 502 + 9), the last
position below 512. **The run's own `context N/511` line is the check**, not
this arithmetic: if the driver counts one differently, `ntok` is reduced until
the printed context is ≤ 511, and the log says so. `--max-ctx 511` makes the
driver itself refuse to go past the ceiling.

**Why only nine decode steps, and what carries the statistics.** The ceiling
is fixed at 511 and the only committed near-ceiling prompt is 503 ids long, so
the decode tail is short. Two things make up for it: every **prefill** launch
on this path is a full sequencer launch with its own counters (step 6 gives
~502 `lite` launches, step 7 ~511 `full` ones), and four repeats of step 6
give the run-to-run spread of the board itself (DDR refresh is not
deterministic; the TB's single-seed argument, census §0, does not transfer).
A new committed prompt that leaves more decode steps under 511 is decision
**D7**.

**`--ntok ≥ 24`** is the house guidance for answer quality
(`docs/USAGE.md` §3 table); BM1 measures time, not answers, and says so in the
gate doc.

### 5.2 The second bitstream's coexistence (`NEXT_SESSION.md` §3)

The 0.8B and 2B are served by their own frozen bitstreams (`build_034`,
`build_035`) and are unaffected; the BM1 bitstream is a **fourth** VERSION on
the one board. It is resident only between steps 2 and 9. Every tool that
drives it must be given its VERSION explicitly (§2.2 item 2); nothing defaults
to it. The frozen 0.8B/2B rows in `sw/hwmap.py:96-105` and the `nch=1` path
are untouched. **Serving 0.8B/2B again still costs a swap plus a re-upload**,
exactly as `NEXT_SESSION.md` §3 says — BM1 changes nothing there.

---

## 6. Evidence

**Directory:** `evidence/qwen9b/bm/`, logs numbered `001_` upward through
`evidence/qwen9b/run.sh` (never overwritten). Proposed names:

| logs | what |
|---|---|
| `001_build_bm1.log`, `002_g0_smoke_*.log` | TB elaboration, G0 |
| `003_g1_timeline_model_9b_s1.log`, `004..007_g2_model_9b_s{1..4}.log` | G1, G2 |
| `008_g1_compare.log` | the §3.3 comparison script's output (script `evidence/qwen9b/bm/bm1_tb_gate.py`, committed before use) |
| `010_build_042_bm1.log`, `011_spread_ckr2.log`, `012_final_verify.log`, `013_clockroot_check.log`, `014_slrcensus.log`, `015_bm1_paths.rpt` | §4 |
| `020_control_shipped_s{1..4}.json` + `.log` | §5 step 1 |
| `021_program_bm1.log`, `022_identity_bm1.log` | steps 2–3 |
| `023..026_census_bm1_s{1..4}.log/.json` | step 5 |
| `027..030_chat511_bm1_r{1..4}.json/.log` | step 6 |
| `031_chat511_prefill_full.json/.log` | step 7 |
| `032_program_shipped.log`, `033_identity_shipped.log`, `034_restore_chat.log` | step 9 |
| `040_bm1_board_analysis.log` | the board table (script `evidence/qwen9b/bm/bm1_board_table.py`, committed before use) |

**Committed:** every log, JSON and script; the G1 CSV's sha256 (not the CSV —
the census's rule, census §1); the `.bit`'s path, size and sha256 (not the
`.bit`). **Gate doc:** `evidence/qwen9b/bm/BM1_BOARD_IDLE.md`, campaign style
(§0 reading rule, T/D/S labels, every number cited), with: the TB gate table
(§3.3 A–D); the timing table against G5D §8.3; the board table — per launch
class (census stream / chat decode / chat prefill) and per T: `PERF_CYC`,
weight path busy (C0) and idle (`PERF_CYC − C0`), C1–C4 and their max/min,
`FENCE` (C5), mover work (C6, beside census §9.1(i-b)'s "mover work (`MOVER`,
nothing streaming)" row — erratum E1) and its engine-busy part (C7, reported,
no census comparand),
`I_MOVER` (C8), `L_LCYC`, `L_SDMA_CYC`, steps (C9) — each beside the census's
figure; and a §NOT-established. `evidence/qwen_next/spec_cites.py` runs LAST
over the gate doc on the committed tree, its log alone in its own commit,
FAIL 0 (`NEXT_SESSION.md` "Key invariants").

---

## 7. What BM1 does NOT establish

1. **Not a design for overlap, and not a prediction of its speed-up.** It
   measures where the board's time goes under the shipped schedule; the
   reachable overlap is OV1's model, and the census's 2.36x is a bound that
   assumes away every dependency (census §12 item 4).
2. **Not causality.** A busy/idle co-occurrence says the resources do not
   overlap in this schedule, not which waits on which (census §12 item 7).
3. **Not R-beat streaming.** The counters measure engine-busy time
   (`cdc_sync_stat[0]`), which in the TB exceeds R-beat time by the engine's
   own head and tail (census §4: 54.460 vs 54.408 ms/token). Bytes per channel
   are not counted (**D4**).
4. **Two cycles of edge uncertainty per busy window on silicon.** A 2-FF
   synchroniser resolves each asynchronous edge within a cycle either way; the
   TB has no metastability, so §3's exactness is a TB property. At the
   census's **1,370** MVGO per token (census §11.1) this is a bound, not a
   measured error.
5. **Not the DDR floor.** Busy time per channel at the board's rate gives the
   board's streaming time; the census's r = 1.0031 was the memory model's
   (census §6, §12 item 5); BM1 can report the board's per-channel busy time
   but not beats per cycle without **D4**.
6. **Not above T = 511, and not a statement about the ceiling.** The ceiling
   is `rtl/attn_core.sv:114`'s, by analysis (`NEXT_SESSION.md:134-155`); BM1
   runs below it and says nothing about above it.
7. **Not the shipped bitstream.** The BM1 bitstream is a different place &
   route; its step time is compared against the shipped one (§5 step 1), and
   any difference is reported, not assumed away.
8. **Not multi-sequence, prefill batching, or a precision change** — out of
   the user's scope (single sequence, W4 g128 + A8).

---

## 8. Open decisions for the user

| # | decision | options | recommendation |
|---|---|---|---|
| **D1** | Wire the four matvec busy bits into `seq_0` (a BD change) | (a) **wire** — exact any-channel union, co-occurrence with the mover, one read site; (b) **no BD change** — per-channel counters inside each `matvec_chan`'s own CSR block; the any-channel union is then only bracketed by `max(C1..C4)` and the sum, and "mover work with no engine busy" is not measurable | **(a)** — it is the only way to get C0 and C7 exactly, and it costs four register-to-register nets |
| **D2** | Also wire the layer's `busy_cmp` into `seq_0` now | (a) **defer** to the overlap RTL build — today layer∧engine is zero in the TB (§1.1) and `L_LCYC` measures the lane exactly; (b) wire now — one flop and one port on `layer_0`, the block holding the ATTN_DSP path | **(a)** — keep `layer_0` byte-identical for the timing goal |
| **D3** | A per-token latch (snapshot bank at each `OP_EMB`) | (a) **no** — the chat path launches once per step, so per-step values already exist; (b) yes — ~11 × 32 more flops in `seq_0`, gives per-token values inside the six-token stream | **(a)** |
| **D4** | R-beat accumulators per channel (bytes streamed, beats per cycle on silicon) | (a) **no** — the bytes are the static split, confirmed byte for byte (census §6); (b) yes — a `ui_clk` accumulator per channel read quasi-statically after HALT, i.e. **a new CDC path under the existing `perf_*` pattern — needs the user's explicit ruling** (`CLAUDE.md` FPGA conventions; `docs/SEQ_ISA.md:150-156`) | **(a)** |
| **D5** | An "all four channels busy" counter | cheap (one more word in the reserved block) | only if OV1 asks for it |
| **D6** | If the four-roll spread and the playbook both miss | incremental implementation against the shipped routed checkpoint (new tooling); an extra crossing flop; or stop | ask at that point, with the rolls' numbers |
| **D7** | The prompt | (a) the committed 16-copy prompt, `--ntok 9`, context 511 (§5.1); (b) commit a shorter prompt (fewer copies) so more decode steps land under 511 — its id count must then be measured on snoke first | **(a)**, with (b) if the user wants a longer decode tail |
| **D8** | The shipped-bitstream control (§5 step 1) | (a) run it — costs one board session; (b) skip and compare against RD9's logged step times | **(a)** — the only like-for-like proof the instrumented bitstream does not move the step time |

**Nothing in this spec is blocked on a decision**: the recommended options
together are a complete, single-clock-domain design. D4 is the one option that
would need a CDC ruling, and it is not recommended.
